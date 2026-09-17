"""Click-driven tour state and real app navigation over synthetic records only."""
from dataclasses import asdict, replace
import json
import shutil
import subprocess

import pytest

from apps.demo_console.components import demo_tour, replay
from apps.demo_console.i18n import catalog, language_scope, tr
from apps.demo_console.models import DecisionOverview, HoldingRow
from apps.demo_console.tests.test_replay import replay_app
from apps.demo_console.tests.test_research_view import _synthetic_archive
from apps.demo_console.tests.test_terminal_interactions import _workspace_action, _content, _tables, _tickers


def _label(source, language):
    return source if language == "en" else catalog()[source][language]


def test_five_sidebar_positions_preserve_both_portfolio_routes_and_ignore_stale_subsections():
    fixed = ("Overview", "Machine learning", "Portfolio", "Research", "Evidence")
    for current in (*demo_tour._VIEWS, None, "Removed workspace"):
        for previous in ("Portfolio", "History", None, "Removed subsection"):
            options = demo_tour.workspace_options(current, previous)
            expected = current if current in ("Portfolio", "History") else previous
            expected = expected if expected in ("Portfolio", "History") else "Portfolio"
            assert options == (*fixed[:2], expected, *fixed[3:])
            assert len(options) == len(set(options)) == 5


def test_tour_callbacks_preserve_date_pause_replay_and_prepare_each_stop(monkeypatch):
    dates = ("2025-10-01", "2025-10-02", "2025-10-03")
    state = {
        "workspace": "History", "decision_date": dates[1], "history_window": "20 snapshots",
        "ticker_search": "stale filter", "membership_filter": "Entered",
        "record_set": "Raw A2 Top20", "research_gross": True, "research_reference": False,
        "ml_section": "Compare outputs", "_localized_tabs:research_tabs": "Performance",
        replay._STATE_KEY: replay.ReplayState(dates, "20 snapshots", index=1),
        replay._TOKEN_KEY: "stale-browser-tick",
    }
    monkeypatch.setattr(demo_tour.st, "session_state", state)
    assert demo_tour._start_tour is demo_tour.start_guided_tour
    demo_tour.start_guided_tour("SYNTH_FIRST")
    assert state["workspace"] == "Overview"
    assert state["ml_section"] == "Compare outputs"
    assert state[demo_tour._ACTIVE] is True
    assert state[replay._STATE_KEY].status == "paused"
    assert state[replay._TOKEN_KEY] is None
    assert state["_research_case_ticker"] == state["system_focus_ticker"] == "SYNTH_FIRST"
    demo_tour._move_tour(-1, None)
    assert state["workspace"] == "Overview"

    demo_tour._move_tour(1, "SYNTH_FIRST")
    assert state["workspace"] == "Machine learning"
    assert state["ml_section"] == "Model engine"
    assert state["ml_engine_ticker"] == state["ml_primary"] == "SYNTH_FIRST"
    assert state["decision_date"] == dates[1]

    demo_tour._move_tour(1, None)
    assert state["workspace"] == "Portfolio"
    assert state["ticker_search"] == ""
    assert state["membership_filter"] == "All names"
    assert state["record_set"] == "Raw A2 Top20"
    assert state["inspect_ticker"] == "SYNTH_FIRST"
    assert state["portfolio_workspace"] == "Portfolio"
    demo_tour._move_tour(1, "SYNTH_FIRST")
    assert state["workspace"] == "History"
    assert state["portfolio_workspace"] == "History"
    assert state["history_window"] == "60 snapshots"
    assert state["_history_focus"] == state["history_ticker"] == "SYNTH_FIRST"
    assert replay._STATE_KEY not in state
    demo_tour._move_tour(1, None)
    assert state["workspace"] == "Research"
    assert state["research_range"] == "All days through selected execution"
    assert state["research_reference"] is True and state["research_gross"] is False
    assert state["_localized_tabs:research_tabs"] == "Drawdown & recovery"
    demo_tour._move_tour(1, None)
    assert state["workspace"] == "Evidence" and state[demo_tour._STEP] == 5
    demo_tour._move_tour(1, None)
    assert state[demo_tour._ACTIVE] is False
    assert state["workspace"] == "Evidence"
    assert state["decision_date"] == dates[1]


def test_history_focus_preserves_valid_canonical_case_then_inspector_then_rank(monkeypatch):
    model = DecisionOverview(ranking=(
        HoldingRow(2, "SYNTH_SECOND", score=None),
        HoldingRow(None, "SYNTH_UNRANKED", score=9999.0),
        HoldingRow(1, "SYNTH_FIRST", score=-5.0),
    ), holdings=(HoldingRow(None, "SYNTH_HELD_ONLY", score=None),))
    state = {demo_tour._ACTIVE: True, "workspace": "Portfolio", "decision_date": "2025-10-02",
             "_history_focus": "SYNTH_MANUAL", "history_ticker": "SYNTH_MANUAL"}
    monkeypatch.setattr(demo_tour.st, "session_state", state)
    original = asdict(model)
    assert demo_tour._history_focus(model) == "SYNTH_FIRST"
    for valid in ("SYNTH_SECOND", "SYNTH_UNRANKED"):
        state["inspect_ticker"] = valid
        assert demo_tour._history_focus(model) == valid
    for invalid in ("SYNTH_HELD_ONLY", "SYNTH_OLD_DATE", "", None, ["SYNTH_SECOND"]):
        state["inspect_ticker"] = invalid
        assert demo_tour._history_focus(model) == "SYNTH_FIRST"
    state["inspect_ticker"] = "SYNTH_SECOND"
    state["_research_case_ticker"] = "SYNTH_FIRST"
    assert demo_tour._history_focus(model) == "SYNTH_FIRST"
    state["_research_case_ticker"] = "SYNTH_OLD_DATE"
    assert demo_tour._history_focus(model) == "SYNTH_SECOND"
    state["inspect_ticker"] = "SYNTH_HELD_ONLY"
    assert demo_tour._history_focus(model) == "SYNTH_FIRST"
    assert demo_tour._history_focus(DecisionOverview()) is None
    assert demo_tour._history_focus(replace(model, error="Synthetic unavailable ranking")) is None
    demo_tour._move_tour(1, None)
    assert state["_history_focus"] == state["history_ticker"] == "SYNTH_MANUAL"
    assert asdict(model) == original


def test_manual_navigation_syncs_explanation_without_resetting_controls_or_date(monkeypatch):
    state = {demo_tour._ACTIVE: True, demo_tour._STEP: 0, "workspace": "Research",
             "decision_date": "2025-10-02", "research_range": "63 execution days",
             "research_reference": False, "research_gross": True,
             "_localized_tabs:research_tabs": "Performance"}
    monkeypatch.setattr(demo_tour.st, "session_state", state)
    assert demo_tour._sync_step("Research") == 4
    assert state["workspace"] == "Research" and state[demo_tour._STEP] == 4
    assert state["research_range"] == "63 execution days"
    assert state["research_gross"] is True and state["research_reference"] is False
    assert state["_localized_tabs:research_tabs"] == "Performance"
    demo_tour._stop_tour()
    assert demo_tour._sync_step("Research") is None
    demo_tour._move_tour(1, None)
    assert state["workspace"] == "Research" and state["decision_date"] == "2025-10-02"


@pytest.fixture
def tour_app(replay_app, monkeypatch):
    from apps.demo_console.adapters import performance_reader
    from apps.demo_console.pages import research

    state = replay_app
    archive = _synthetic_archive()
    state.performance_calls = []

    def synthetic_performance(end_date=None):
        state.performance_calls.append(end_date)
        points = tuple(point for point in archive.points if point.execution_date <= end_date)
        return replace(archive, points=points, requested_end_date=end_date,
                       effective_end_date=points[-1].execution_date if points else None)

    def forbidden(*args, **kwargs):
        raise AssertionError("Tour tests must never call the real performance reader")

    monkeypatch.setattr(research, "read_performance", synthetic_performance)
    monkeypatch.setattr(performance_reader, "read_performance", forbidden)
    return state


def _assert_stop(app, view, date):
    assert not app.exception and not app.error
    assert app.radio(key="workspace").value == view
    assert app.selectbox(key="decision_date").value == date
    assert app.session_state[demo_tour._ACTIVE] is True
    assert app.session_state[demo_tour._STEP] == ("Overview", "Machine learning", "Portfolio", "History", "Research", "Evidence").index(view)
    assert len(app.radio(key="workspace").options) == 5
    if view in ("Portfolio", "History"):
        assert next(control for control in app.get("button_group")
                    if control.key == "portfolio_workspace").value == view


def test_portfolio_group_keeps_external_history_callback_language_and_replay_context(tour_app):
    app = tour_app.app
    assert app.radio(key="workspace").value == "History"
    assert len(app.radio(key="workspace").options) == 5
    app.selectbox(key="history_window").select("20 snapshots").run()
    app.selectbox(key="history_ticker").select("SYNTH_11").run()
    app.button(key="history_replay_play").click().run()
    frame_date = app.selectbox(key="decision_date").value
    assert app.session_state[replay._STATE_KEY].status == "playing"
    _workspace_action(app, "Portfolio").run()
    assert app.radio(key="workspace").value == "Portfolio"
    assert app.session_state[replay._STATE_KEY].status == "paused"
    assert app.selectbox(key="decision_date").value == frame_date
    app.selectbox(key="inspect_ticker").select("SYNTH_11").run()
    # This production callback still writes workspace='History' directly.
    app.button(key="open_security_history").click().run()
    assert not app.exception and not app.error
    assert app.radio(key="workspace").value == "History"
    assert app.selectbox(key="history_ticker").value == "SYNTH_11"
    assert app.selectbox(key="history_window").value == "20 snapshots"
    for language in ("zh", "ja", "en"):
        app.selectbox(key="language").select(language).run()
        assert not app.exception and not app.error
        assert app.radio(key="workspace").value == "History"
        assert len(app.radio(key="workspace").options) == 5
        assert next(control for control in app.get("button_group")
                    if control.key == "portfolio_workspace").value == "History"
        with language_scope(language):
            assert app.radio(key="workspace").options[2] == f'03  {tr("Decisions & portfolio")}'
        assert app.selectbox(key="decision_date").value == frame_date
        assert app.selectbox(key="history_window").value == "20 snapshots"
    app.radio(key="workspace").set_value("Evidence").run()
    app.radio(key="workspace").set_value("History").run()
    assert not app.exception and not app.error
    assert app.radio(key="workspace").value == "History"
    assert app.selectbox(key="decision_date").value == frame_date
    assert app.selectbox(key="history_ticker").value == "SYNTH_11"


def _focus_requests(app):
    return [element.proto for element in app.get("html")
            if "data-uq-tour-focus" in element.proto.body]


def test_focus_script_uses_visible_launcher_or_expand_button_without_opening_sidebar(monkeypatch):
    from apps.demo_console.tests.test_motion import _Markup

    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable for the synthetic focus behavior check")
    rendered = []
    state = {}
    monkeypatch.setattr(demo_tour.st, "session_state", state)
    monkeypatch.setattr(demo_tour.st, "html", lambda body, **kwargs: rendered.append(body))
    scripts = {}
    for target in ("copy", "launcher"):
        state[demo_tour._FOCUS] = target
        demo_tour._render_focus_request(target)
        scripts[target] = "\n".join(_Markup(rendered[-1]).scripts)
        assert demo_tour._FOCUS not in state
        count = len(rendered)
        demo_tour._render_focus_request(target)
        assert len(rendered) == count

    # Execute the production JS with a DOM surface; focus() deliberately permits
    # invisible elements, matching the browser regression that must be avoided.
    program = "const scripts = " + json.dumps(scripts) + r""";
const vm = require('node:vm');
const results = [];
const cases = [
  {name: 'start', target: 'copy', expanded: false, expected: 'copy'},
  {name: 'overview-main-entry', overview: true, expanded: false, expected: 'overview'},
  {name: 'overview-main-before-sidebar', overview: true, expanded: true, expected: 'overview'},
  {name: 'overview-offscreen-fallback', overview: true, hiddenOverview: true, expanded: true, expected: 'launcher'},
  {name: 'expanded', expanded: true, expected: 'launcher'},
  {name: 'collapsed-offscreen', expanded: false, offscreen: true, expected: 'expand'},
  {name: 'collapsed-positive-rect', expanded: false, expected: 'expand'},
  {name: 'expanded-offscreen', expanded: true, offscreen: true, expected: 'expand'},
  {name: 'expanded-display-none', expanded: true, display: 'none', expected: 'expand'},
  {name: 'expanded-hidden', expanded: true, visibility: 'hidden', expected: 'expand'},
  {name: 'expanded-transparent', expanded: true, opacity: '0', expected: 'expand'},
  {name: 'missing-launcher', expanded: true, missing: true, expected: 'expand'},
  {name: 'expanded-scrolled', expanded: true, offscreen: true, hiddenExpand: true, expected: 'heading'},
  {name: 'missing-expand', expanded: false, missingExpand: true, headingTab: '0', expected: 'heading'},
  {name: 'no-visible-destination', expanded: false, hiddenExpand: true, hiddenHeading: true, expected: null},
];
for (const entry of cases) {
  const frames = [], effects = [];
  let active = null, expanded = entry.expanded;
  const makeNode = (name, overrides = {}) => ({
    style: {display: 'block', visibility: 'visible', opacity: '1', ...overrides},
    getBoundingClientRect: () => ({left: 10, top: 10, right: 150, bottom: 50, width: 140, height: 40}),
    focus(options) {active = name; effects.push({name, options});},
    click() {throw Error('Focus must not open or click any control');},
    setAttribute() {throw Error('Focus must not alter the sidebar state');},
  });
  const launcher = makeNode('launcher', Object.fromEntries(
    ['display', 'visibility', 'opacity'].filter(key => key in entry).map(key => [key, entry[key]])));
  if (entry.offscreen) launcher.getBoundingClientRect = () =>
    ({left: -292, top: 1635.55, right: -266.67, bottom: 1980.82, width: 25.33, height: 345.27});
  const expand = makeNode('expand', entry.hiddenExpand ? {display: 'none'} : {});
  const overview = makeNode('overview', entry.hiddenOverview ? {display: 'none'} : {});
  const copy = makeNode('copy');
  const heading = makeNode('heading', entry.hiddenHeading ? {display: 'none'} : {});
  let headingTab = entry.headingTab ?? null, onBlur;
  heading.getAttribute = name => name === 'tabindex' ? headingTab : null;
  heading.setAttribute = (name, value) => {if (name !== 'tabindex') throw Error('Unexpected write'); headingTab = value;};
  heading.removeAttribute = name => {if (name !== 'tabindex') throw Error('Unexpected removal'); headingTab = null;};
  heading.addEventListener = (name, callback, options) => {
    if (name !== 'blur' || !options.once) throw Error('Expected one-time focus cleanup');
    onBlur = callback;
  };
  const sidebar = {getAttribute: key => key === 'aria-expanded' ? String(expanded) : null};
  const document = {querySelector: selector => ({
    '#uq-demo-tour-copy': copy,
    '.st-key-demo_tour_start button': entry.missing ? null : launcher,
    '.st-key-system_start_tour button': entry.overview ? overview : null,
    '[data-testid="stSidebar"]': sidebar,
    '[data-testid="stExpandSidebarButton"]': entry.missingExpand ? null : expand,
    '.uq-page-header h1': heading,
  }[selector] ?? null)};
  vm.runInNewContext(scripts[entry.target ?? 'launcher'], {
    document, window: {innerWidth: 1024, innerHeight: 768},
    getComputedStyle: element => element.style,
    requestAnimationFrame: fn => frames.push(fn),
  });
  if (active !== null || frames.length !== 1) throw Error('Unexpected synchronous focus');
  frames.shift()();
  if (active !== null || frames.length !== 1) throw Error('Missing second paint frame');
  frames.shift()();
  if (active !== entry.expected) throw Error(entry.name + ': wrong focus ' + active);
  if (expanded !== entry.expanded) throw Error('Sidebar state changed');
  if (effects.length !== (entry.expected ? 1 : 0) || effects.some(effect => !effect.options.preventScroll))
    throw Error('Unexpected focus or scrolling');
  if (entry.expected === 'heading') {
    if (headingTab !== '-1' || !onBlur) throw Error('Heading needs temporary programmatic focus');
    onBlur();
    if (headingTab !== (entry.headingTab ?? null)) throw Error('Heading tabindex was not restored');
  }
  results.push(entry.name);
}
process.stdout.write(JSON.stringify(results));
"""
    result = subprocess.run([node], input=program, text=True, encoding="utf-8",
                            capture_output=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
    assert len(json.loads(result.stdout)) == 15


def test_tour_focus_handoff_occurs_once_only_on_start_exit_and_finish(tour_app):
    app = tour_app.app
    assert not _focus_requests(app)
    app.button(key="demo_tour_start").click().run()
    start = _focus_requests(app)
    assert len(start) == 1 and start[0].unsafe_allow_javascript
    assert 'querySelector("#uq-demo-tour-copy")' in start[0].body
    assert start[0].body.count("requestAnimationFrame(") == 2
    assert "focus({preventScroll: true})" in start[0].body
    assert demo_tour._FOCUS not in app.session_state
    copy = next(element.proto.body for element in app.get("html")
                if 'id="uq-demo-tour-copy"' in element.proto.body)
    for attribute in ('tabindex="-1"', 'role="status"', 'aria-live="polite"', 'aria-atomic="true"'):
        assert attribute in copy

    app.run()
    assert not _focus_requests(app)
    for button in ("demo_tour_next", "demo_tour_previous"):
        app.button(key=button).click().run()
        assert not app.exception and not _focus_requests(app)
        assert demo_tour._FOCUS not in app.session_state
    app.selectbox(key="language").select("ja").run()
    assert not _focus_requests(app)

    app.button(key="demo_tour_exit").click().run()
    leave = _focus_requests(app)
    assert len(leave) == 1 and '.st-key-demo_tour_start button' in leave[0].body
    assert "focus({preventScroll: true})" in leave[0].body
    assert app.button(key="system_start_tour")
    assert not any(button.key == "demo_tour_start" for button in app.button)
    assert demo_tour._FOCUS not in app.session_state
    app.run()
    assert not _focus_requests(app)

    app.button(key="system_start_tour").click().run()
    app.radio(key="workspace").set_value("Evidence").run()
    assert not _focus_requests(app)
    app.button(key="demo_tour_next").click().run()
    finish = _focus_requests(app)
    assert len(finish) == 1 and '.st-key-demo_tour_start button' in finish[0].body
    assert app.session_state[demo_tour._ACTIVE] is False
    assert demo_tour._FOCUS not in app.session_state
    app.run()
    assert not app.exception and not app.error and not _focus_requests(app)


def test_actual_app_tour_visits_all_stops_keeps_nonlatest_date_and_finishes(tour_app):
    state, app = tour_app, tour_app.app
    selected = tuple(state.models)[-3]
    app.selectbox(key="decision_date").select(selected).run()
    _workspace_action(app, "Portfolio").run()
    app.selectbox(key="membership_filter").select("Retained").run()
    app.text_input(key="ticker_search").set_value("SYNTH_0").run()
    inspected = app.selectbox(key="inspect_ticker").options[1]
    app.selectbox(key="inspect_ticker").select(inspected).run()
    app.button(key="demo_tour_start").click().run()
    _assert_stop(app, "Overview", selected)
    assert app.session_state["inspect_ticker"] == inspected
    assert app.button(key="demo_tour_previous").disabled
    assert "How does this model record relate to holdings?" in _content(app)
    assert not any(button.key == "demo_tour_start" for button in app.button)
    assert not any(element.label == "Selected decision · full portfolio overview"
                   for element in (*app.expander, *app.status))

    app.button(key="demo_tour_next").click().run()
    _assert_stop(app, "Machine learning", selected)
    assert app.session_state["inspect_ticker"] == inspected
    assert app.session_state["ml_section"] == "Model engine"
    assert "What did the model record for this security?" in _content(app)
    assert app.selectbox(key="ml_engine_ticker").value == inspected

    app.button(key="demo_tour_next").click().run()
    _assert_stop(app, "Portfolio", selected)
    assert app.selectbox(key="record_set").value == "Raw A2 Top20"
    assert app.selectbox(key="membership_filter").value == "All names"
    assert app.text_input(key="ticker_search").value == ""
    assert len(_tickers(_tables(app)[0])) == 20
    assert "Was this security held after execution?" in _content(app)
    assert "Subsequent holding" in _content(app)
    assert app.selectbox(key="inspect_ticker").value == inspected

    app.button(key="demo_tour_next").click().run()
    _assert_stop(app, "History", selected)
    assert app.selectbox(key="history_window").value == "60 snapshots"
    assert app.selectbox(key="history_ticker").value == inspected
    assert app.session_state["_history_focus"] == inspected
    assert state.history_calls[-1] == (selected, 60)
    assert replay._STATE_KEY not in app.session_state
    app.run()
    _assert_stop(app, "History", selected)  # A rerun does not navigate or start replay.
    assert replay._STATE_KEY not in app.session_state

    app.button(key="demo_tour_next").click().run()
    _assert_stop(app, "Research", selected)
    assert app.selectbox(key="research_range").value == "All days through selected execution"
    assert app.toggle(key="research_reference").value is True
    assert app.toggle(key="research_gross").value is False
    assert app.session_state["_localized_tabs:research_tabs"] == "Drawdown & recovery"
    assert app.get("tab_container")[0].proto.tab_container.default_tab_index == 1
    assert state.performance_calls[-1] == state.models[selected].provenance.execution_date
    app.button(key="demo_tour_previous").click().run()
    _assert_stop(app, "History", selected)
    app.button(key="demo_tour_next").click().run()
    _assert_stop(app, "Research", selected)
    app.button(key="demo_tour_next").click().run()
    _assert_stop(app, "Evidence", selected)
    assert "Which records support this case?" in _content(app)
    assert "Artifact integrity does not establish independent predictive skill" in _content(app)
    assert app.session_state["_research_case_ticker"] == inspected
    assert app.button(key="demo_tour_next").label == "Finish"
    app.button(key="demo_tour_next").click().run()
    assert not app.exception and not app.error
    assert app.session_state[demo_tour._ACTIVE] is False
    assert app.radio(key="workspace").value == "Evidence"
    assert app.selectbox(key="decision_date").value == selected
    assert app.button(key="demo_tour_start")


def test_japanese_tour_keeps_inspector_across_overview_and_invalid_values_fall_back(tour_app):
    app = tour_app.app
    date = app.selectbox(key="decision_date").value
    app.selectbox(key="language").select("ja").run()
    _workspace_action(app, "Portfolio").run()
    inspected = app.selectbox(key="inspect_ticker").options[1]
    app.selectbox(key="inspect_ticker").select(inspected).run()
    app.button(key="demo_tour_start").click().run()
    _assert_stop(app, "Overview", date)
    assert app.session_state["inspect_ticker"] == inspected
    app.button(key="demo_tour_next").click().run()
    _assert_stop(app, "Machine learning", date)
    assert app.session_state["inspect_ticker"] == inspected
    app.button(key="demo_tour_next").click().run()
    _assert_stop(app, "Portfolio", date)
    inspector = app.selectbox(key="inspect_ticker")
    assert inspector.value == inspected
    assert inspector.proto.set_value and inspector.proto.raw_value == inspected
    app.button(key="demo_tour_next").click().run()
    _assert_stop(app, "History", date)
    assert app.selectbox(key="history_ticker").value == inspected
    assert replay._STATE_KEY not in app.session_state

    # A stale local inspector cannot displace the valid case carried through
    # the tour, or grant access to a name absent from the current records.
    app.button(key="demo_tour_exit").click().run()
    assert app.session_state["_research_case_ticker"] == inspected
    app.session_state["inspect_ticker"] = "SYNTH_NO_LONGER_AVAILABLE"
    _workspace_action(app, "Portfolio").run()
    inspector = app.selectbox(key="inspect_ticker")
    assert inspector.value == inspected == app.session_state["_research_case_ticker"]
    assert inspector.value in inspector.options
    assert "SYNTH_NO_LONGER_AVAILABLE" not in inspector.options
    assert 'uq-inspector-symbol">SYNTH_NO_LONGER_AVAILABLE' not in _content(app)

    # When the canonical case and every retained navigation preference are
    # absent too, repair to the first current option and remember that case.
    app.radio(key="workspace").set_value("Evidence").run()
    for key in ("_research_case_ticker", "inspect_ticker", "ml_engine_ticker", "ml_trace_ticker",
                "ml_primary", "history_ticker", "_history_focus", "system_focus_ticker"):
        app.session_state[key] = "SYNTH_NO_LONGER_AVAILABLE"
    _workspace_action(app, "Portfolio").run()
    inspector = app.selectbox(key="inspect_ticker")
    assert inspector.value == inspector.options[0] == app.session_state["_research_case_ticker"]
    assert "SYNTH_NO_LONGER_AVAILABLE" not in inspector.options
    assert 'uq-inspector-symbol">SYNTH_NO_LONGER_AVAILABLE' not in _content(app)
    app.selectbox(key="inspect_ticker").select(inspected).run()
    fallback = app.selectbox(key="inspect_ticker").options[-1]
    app.text_input(key="ticker_search").set_value(fallback).run()
    assert app.selectbox(key="inspect_ticker").options == [fallback]
    assert app.selectbox(key="inspect_ticker").value == fallback
    assert app.selectbox(key="decision_date").value == date
    assert not app.exception and not app.error


def test_manual_navigation_languages_and_exit_preserve_user_choices_and_pause_replay(tour_app):
    state, app = tour_app, tour_app.app
    selected = app.selectbox(key="decision_date").value
    app.button(key="demo_tour_start").click().run()
    app.radio(key="workspace").set_value("Research").run()
    _assert_stop(app, "Research", selected)
    app.selectbox(key="research_range").select("63 execution days").run()
    app.toggle(key="research_reference").set_value(False).run()
    app.toggle(key="research_gross").set_value(True).run()
    for language in ("zh", "ja", "en"):
        app.selectbox(key="language").select(language).run()
        _assert_stop(app, "Research", selected)
        assert app.button(key="demo_tour_next").label == _label("Next", language)
        assert _label("How did the portfolio behave during setbacks?", language) in _content(app)
        assert app.selectbox(key="research_range").value == "63 execution days"
        assert app.selectbox(key="research_range").proto.raw_value == _label("63 execution days", language)
        assert app.toggle(key="research_reference").value is False
        assert app.toggle(key="research_gross").value is True

    _workspace_action(app, "History").run()
    _assert_stop(app, "History", selected)
    app.button(key="history_replay_play").click().run()
    frame_date = app.selectbox(key="decision_date").value
    assert app.session_state[replay._STATE_KEY].status == "playing"
    app.radio(key="workspace").set_value("Evidence").run()
    _assert_stop(app, "Evidence", frame_date)
    assert app.session_state[replay._STATE_KEY].status == "paused"
    app.button(key="demo_tour_exit").click().run()
    assert app.session_state[demo_tour._ACTIVE] is False
    assert app.radio(key="workspace").value == "Evidence"
    assert app.selectbox(key="decision_date").value == frame_date
    assert not app.exception and not app.error


def test_programmatic_widget_restore_does_not_log_duplicate_defaults(tour_app, monkeypatch, caplog):
    from streamlit import config
    from streamlit.elements.lib import policies

    app = tour_app.app
    assert not config.get_option("global.disableWidgetStateDuplicationWarning")
    assert app.selectbox(key="history_window").value == "60 snapshots"

    def run_without_duplication(action):
        # Streamlit logs this only once per process; reset that test-local
        # guard so a warning from a later tour stop cannot be hidden.
        monkeypatch.setattr(policies, "_shown_default_value_warning", False)
        caplog.clear()
        action.run()
        assert not app.exception and not app.error
        assert not any("was created with a default value but also had" in record.getMessage()
                       for record in caplog.records)

    run_without_duplication(app.button(key="demo_tour_start").click())
    run_without_duplication(app.button(key="demo_tour_next").click())
    run_without_duplication(app.button(key="demo_tour_next").click())
    run_without_duplication(app.button(key="demo_tour_next").click())
    assert app.selectbox(key="history_window").value == "60 snapshots"
    for language in ("ja", "zh", "en"):
        run_without_duplication(app.selectbox(key="language").select(language))
        assert app.selectbox(key="history_window").value == "60 snapshots"
    run_without_duplication(app.button(key="demo_tour_next").click())
    assert app.toggle(key="research_reference").value is True
    run_without_duplication(app.toggle(key="research_reference").set_value(False))
    run_without_duplication(app.selectbox(key="language").select("ja"))
    assert app.toggle(key="research_reference").value is False
    run_without_duplication(app.button(key="demo_tour_previous").click())
    run_without_duplication(app.button(key="demo_tour_exit").click())
    run_without_duplication(app.selectbox(key="history_window").select("20 snapshots"))
    run_without_duplication(app.button(key="history_replay_play").click())
    run_without_duplication(app.radio(key="workspace").set_value("Overview"))
    run_without_duplication(_workspace_action(app, "History"))
    assert app.selectbox(key="history_window").value == "20 snapshots"
    assert app.session_state[replay._STATE_KEY].status == "paused"
    run_without_duplication(app.selectbox(key="history_window").select(None))
    assert app.selectbox(key="history_window").value == "60 snapshots"
