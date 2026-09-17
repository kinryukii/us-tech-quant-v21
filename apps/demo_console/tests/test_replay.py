"""Bounded replay state, actual CCv2 callback dispatch, and chart cutoff checks."""
from dataclasses import replace
from datetime import date, timedelta
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from apps.demo_console.components import replay
from apps.demo_console.models import DecisionOverview, HoldingRow, Provenance
from apps.demo_console.tests.test_history_view import _charts, _history_tables, _security_table
from apps.demo_console.tests.test_terminal_interactions import _workspace_action


_DATES = tuple((date(2025, 9, 1) + timedelta(days=index)).isoformat() for index in range(65))


def test_range_uses_recorded_snapshots_and_never_moves_the_locked_start_backward():
    assert replay.replay_range(_DATES, _DATES[-1], 60) == _DATES[5:]
    assert replay.replay_range(_DATES, _DATES[10], 20) == _DATES[:11]
    assert replay.replay_range(_DATES, _DATES[-1], None) == _DATES
    assert replay.replay_range(_DATES, "2024-01-01", 60) == ()
    for bad in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            replay.replay_range(_DATES, _DATES[-1], bad)


@pytest.fixture
def replay_state(monkeypatch):
    state = {"workspace": "History", "decision_date": _DATES[4],
             "history_window": "20 snapshots", "_history_focus": "SYNTH_21"}
    monkeypatch.setattr(replay.st, "session_state", state)
    replay._start_replay(_DATES, _DATES[4], "20 snapshots", 20)
    return state


def _payload(state, token="frame-token"):
    state[replay._TOKEN_KEY] = token
    return {"token": token, "date": state["decision_date"]}


def test_pause_resume_duplicate_ticks_and_terminal_frame_preserve_focus(replay_state):
    state = replay_state
    assert state["decision_date"] == _DATES[0]
    assert replay.visible_replay_dates(_DATES[0], "20 snapshots") == _DATES[:1]
    first = _payload(state)
    assert replay.accept_tick(first)
    assert state["decision_date"] == state["replay_date"] == _DATES[1]
    assert not replay.accept_tick(first), "A duplicate delivery must not skip a frame"
    replay.pause_replay()
    assert state[replay._STATE_KEY].status == "paused"
    assert not replay.accept_tick(_payload(state))
    assert state["decision_date"] == _DATES[1]
    replay._resume_replay()
    assert state["decision_date"] == _DATES[1]
    for index in range(2, 5):
        assert replay.accept_tick(_payload(state, str(index)))
        assert state["decision_date"] == state["replay_date"] == _DATES[index]
    assert state[replay._STATE_KEY].status == "complete"
    assert not replay.accept_tick(_payload(state))
    assert state["decision_date"] == _DATES[4]
    assert state["_history_focus"] == "SYNTH_21"
    replay._restart_replay()
    assert state["decision_date"] == _DATES[0]
    assert state[replay._STATE_KEY].dates == _DATES[:5]


@pytest.mark.parametrize("changed,value", [
    ("workspace", "Overview"), ("decision_date", _DATES[3]),
    ("history_window", "All available"),
])
def test_navigation_and_manual_selection_win_a_timer_race(replay_state, changed, value):
    state = replay_state
    payload = _payload(state)
    state[changed] = value
    expected = state["decision_date"]
    assert not replay.accept_tick(payload)
    assert state["decision_date"] == expected
    if changed == "workspace":
        assert state[replay._STATE_KEY].status == "paused"
    else:
        assert replay._STATE_KEY not in state


def test_stale_render_token_and_malformed_ticks_cannot_advance(replay_state):
    state = replay_state
    old = _payload(state, "old-render")
    _payload(state, "new-render")
    for payload in (None, [], {}, old, {"token": "new-render", "date": _DATES[-1]}):
        assert not replay.accept_tick(payload)
        assert state["decision_date"] == _DATES[0]
    replay.sync_replay_context("Portfolio", _DATES[0])
    assert state[replay._STATE_KEY].status == "paused"
    state.pop("history_window")  # Streamlit removes widgets on another page.
    replay.restore_replay_window()
    assert state["history_window"] == "20 snapshots"
    replay.sync_replay_context("History", _DATES[2])
    assert replay._STATE_KEY not in state


def test_browser_timer_is_one_shot_and_replaced_or_cancelled_on_every_render():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable for the isolated CCv2 timer harness")
    source = replay._TIMER_JS.replace("export default function", "function render", 1)
    scenario = r"""
const timers = new Map(), emitted = [], delays = [];
let serial = 0;
const context = vm.createContext({
  setTimeout(fn, ms) { delays.push(ms); timers.set(++serial, fn); return serial; },
  clearTimeout(id) { timers.delete(id); },
});
vm.runInContext(source, context);
const parent = {};
function render(token, playing = true) {
  return context.render({parentElement: parent, data: {playing, token, date: "2025-10-01"},
    setTriggerValue: (key, value) => emitted.push({key, value})});
}
const firstCleanup = render("old");
const stale = [...timers.values()][0];
const cleanup = render("new");
firstCleanup(); // Old lifecycle cleanup must not remove the new timer.
const afterReplace = timers.size;
stale();
for (const [id, callback] of [...timers]) { timers.delete(id); callback(); }
cleanup();
const stopped = render("paused", false);
const afterPause = timers.size;
stopped();
const unmount = render("unmounted");
unmount();
process.stdout.write(JSON.stringify({afterReplace, afterPause, afterUnmount: timers.size, emitted, delays}));
"""
    program = "const vm = require('node:vm'); const source = " + json.dumps(source) + ";\n" + scenario
    result = subprocess.run([node, "--input-type=commonjs"], input=program, text=True,
                            encoding="utf-8", capture_output=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output == {"afterReplace": 1, "afterPause": 0, "afterUnmount": 0,
                      "emitted": [{"key": "tick", "value": {"token": "new", "date": "2025-10-01"}}],
                      "delays": [3000, 3000, 3000]}


@pytest.fixture
def replay_app(monkeypatch, landing_without_performance):
    """Many synthetic dates expose sliding-window bugs without external files."""
    from streamlit.testing.v1 import AppTest
    from apps.demo_console.adapters import decision_reader

    models = {}
    for index, day in enumerate(_DATES):
        first = 2 if index == len(_DATES) - 1 else 1
        rows = tuple(HoldingRow(rank, f"SYNTH_{number:02}", score=float(rank))
                     for rank, number in enumerate(range(first, first + 20), 1))
        symbols = tuple(row.ticker for row in rows)
        models[day] = DecisionOverview(
            decision_date=day, available_dates=_DATES, ranking=rows, holdings=rows,
            previous_holdings=symbols, retained=symbols, entered=(), exited=(), turnover=.1,
            provenance=Provenance(decision_date=day, information_as_of=day,
                                  execution_date=(date.fromisoformat(day) + timedelta(days=1)).isoformat()))
    state = SimpleNamespace(models=models, history_calls=[], tick_events=[], transform=lambda model: model)

    actual_accept = replay.accept_tick

    def record_tick(payload):
        before = {key: replay.st.session_state.get(key) for key in
                  ("workspace", "decision_date", "history_window", replay._TOKEN_KEY, replay._STATE_KEY)}
        accepted = actual_accept(payload)
        state.tick_events.append((payload, before, accepted))
        return accepted

    monkeypatch.setattr(replay, "accept_tick", record_tick)

    def synthetic_history(end_date=None, window=60):
        state.history_calls.append((end_date, window))
        dates = replay.replay_range(_DATES, end_date or _DATES[-1], window)
        return tuple(state.transform(models[day]) for day in dates)

    monkeypatch.setattr(decision_reader, "load_overview", lambda day=None: models[day or _DATES[-1]])
    monkeypatch.setattr(decision_reader, "load_history", synthetic_history)
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=20)
    app.session_state["workspace"] = "History"
    app.session_state["_history_focus"] = "SYNTH_21"
    state.app = app.run()
    if app.error:
        app.toggle(key="presentation_mode").set_value(False).run()
    assert not app.exception and not app.error, [element.message for element in app.exception]
    return state


def _timer_data(app):
    return json.loads(app.get("bidi_component")[0].proto.json)


def _send_tick(app, payload=None):
    """AppTest has no CCv2 widget API; dispatch its actual v1.63 trigger proto."""
    from streamlit.components.v2.bidi_component.main import _make_trigger_id

    timer = app.get("bidi_component")[0]
    data = _timer_data(app)
    payload = payload or {"token": data["token"], "date": data["date"]}
    widgets = app._tree.get_widget_states()
    # The browser also sends the component's persistent (empty) base state.
    # AppTest's UnknownElement omits it, so include both parts of the CCv2 wire.
    base = widgets.widgets.add()
    base.id = timer.proto.id
    base.json_value = "{}"
    event = widgets.widgets.add()
    event.id = _make_trigger_id(timer.proto.id, "events")
    event.json_trigger_value = json.dumps([{"event": "tick", "value": payload}])
    app._run(widgets)


def _assert_frame(state, dates):
    app = state.app
    assert not app.exception and not app.error
    assert app.selectbox(key="decision_date").value == dates[-1], state.tick_events
    assert app.select_slider(key="replay_date").value == dates[-1]
    assert app.selectbox(key="history_ticker").value == "SYNTH_21"
    assert state.history_calls[-1] == (dates[-1], len(dates))
    for units, rows in _charts(app).values():
        assert sorted({row["decision_date"] for row in rows}) == list(dates)
        assert all(unit["encoding"]["x"]["scale"]["domain"] == list(dates) for unit in units)
    assert all(sorted(table["Decision date"].tolist()) == list(dates) for table in _history_tables(app))
    assert any(dates[-1] in element.value and 'uq-page-header' in element.value for element in app.get("html"))


def test_play_pause_resume_real_callback_keeps_global_date_and_all_charts_in_locked_window(replay_app):
    state, app = replay_app, replay_app.app
    assert _timer_data(app)["playing"] is False
    app.button(key="history_replay_play").click().run()
    _assert_frame(state, _DATES[5:6])
    assert all(row["rank"] is None for row in _charts(app)["rank"][1]), "Outside Top20 stays missing"
    first_tick = _timer_data(app)
    app.button(key="history_replay_pause").click().run()
    _assert_frame(state, _DATES[5:6])
    assert app.session_state[replay._STATE_KEY].status == "paused"
    _send_tick(app, {"date": first_tick["date"], "token": first_tick["token"]})
    _assert_frame(state, _DATES[5:6])
    app.button(key="history_replay_play").click().run()
    _send_tick(app)
    _assert_frame(state, _DATES[5:7])
    app.select_slider(key="replay_date").set_value(_DATES[20]).run()
    assert replay._STATE_KEY not in app.session_state
    assert _timer_data(app)["playing"] is False
    assert state.history_calls[-1] == (_DATES[20], 60)
    app.selectbox(key="history_window").select("20 snapshots").run()
    app.button(key="history_replay_play").click().run()
    _assert_frame(state, _DATES[1:2])
    app.selectbox(key="history_window").select("All available").run()
    assert replay._STATE_KEY not in app.session_state
    assert state.history_calls[-1] == (_DATES[1], None)


def test_replay_preserves_missing_portfolio_observations(replay_app):
    state, app = replay_app, replay_app.app
    state.transform = lambda model: replace(model, holdings=(), entered=None, exited=None,
                                            retained=None, previous_holdings=None, turnover=None)
    app.button(key="history_replay_play").click().run()
    _assert_frame(state, _DATES[5:6])
    _send_tick(app)
    _assert_frame(state, _DATES[5:7])
    for metric in ("signed_count", "turnover"):
        assert all(row[metric] is None for row in _charts(app)[metric][1])
    assert set(_security_table(app)["Holdings status"]) == {"Unavailable"}
    assert any("portfolio snapshot(s) unavailable" in message.value for message in app.warning)


def test_replay_reaches_endpoint_and_stops_without_revealing_later_dates(replay_app):
    state, app = replay_app, replay_app.app
    app.select_slider(key="replay_date").set_value(_DATES[1]).run()
    app.button(key="history_replay_play").click().run()
    _assert_frame(state, _DATES[:1])
    _send_tick(app)
    _assert_frame(state, _DATES[:2])
    assert app.session_state[replay._STATE_KEY].status == "complete"
    assert _timer_data(app)["playing"] is False
    assert app.button(key="history_replay_pause").disabled
    _send_tick(app, {"token": "old", "date": _DATES[0]})
    _assert_frame(state, _DATES[:2])
    app.button(key="history_replay_play").click().run()
    _assert_frame(state, _DATES[:1])


def test_navigation_manual_sidebar_dates_and_language_changes_pause_without_losing_focus(replay_app):
    state, app = replay_app, replay_app.app
    app.selectbox(key="history_window").select("20 snapshots").run()
    app.button(key="history_replay_play").click().run()
    _assert_frame(state, _DATES[45:46])
    app.radio(key="workspace").set_value("Overview").run()
    assert not app.exception and not app.error
    assert app.session_state[replay._STATE_KEY].status == "paused"
    assert app.selectbox(key="decision_date").value == _DATES[45]
    assert not app.get("bidi_component")
    _workspace_action(app, "History").run()
    _assert_frame(state, _DATES[45:46])
    assert app.selectbox(key="history_window").value == "20 snapshots"
    app.button(key="history_replay_play").click().run()
    app.selectbox(key="language").select("ja").run()
    assert not app.exception and not app.error
    assert app.session_state[replay._STATE_KEY].status == "paused"
    assert app.selectbox(key="decision_date").value == _DATES[45]
    assert app.selectbox(key="history_ticker").value == "SYNTH_21"
    app.selectbox(key="language").select("en").run()
    app.button(key="history_replay_play").click().run()
    app.button(key="next_date").click().run()
    assert replay._STATE_KEY not in app.session_state
    assert _timer_data(app)["playing"] is False
    assert state.history_calls[-1] == (_DATES[46], 20)
    app.button(key="history_replay_play").click().run()
    app.selectbox(key="decision_date").select(_DATES[60]).run()
    assert replay._STATE_KEY not in app.session_state
    assert state.history_calls[-1] == (_DATES[60], 20)
    assert app.select_slider(key="replay_date").value == _DATES[60]
    assert app.selectbox(key="history_ticker").value == "SYNTH_21"
