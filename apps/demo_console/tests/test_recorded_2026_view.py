"""UI mode isolation over synthetic 2026 records; no economic files are read."""
from dataclasses import asdict, replace
from datetime import date
import json
from types import SimpleNamespace

import pyarrow as pa
import pytest

from apps.demo_console.adapters.recorded_2026_reader import (
    Recorded2026History, Recorded2026Point, Recorded2026Series, Recorded2026Subperiod,
)
from apps.demo_console.i18n import language_scope, tr
from apps.demo_console.tests.test_machine_learning_view import learning_app
from apps.demo_console.tests.test_terminal_interactions import _content

_HISTORICAL = "Historical research"
_RECORDED = "2026 recorded performance"
_CASE_DATE = "2025-12-02"
_PRIVATE = r"C:\synthetic-private\recorded-2026\summary.json"
_DEBUG = "SYNTHETIC_RECORDED_2026_IDENTITY_FAILURE"
_ERROR = "The recorded 2026 comparison is unavailable. Its source identity or recorded values could not be verified."


def _synthetic_recorded_window():
    points = (
        Recorded2026Point("2026-06-15", 100, 100, 100, 0, 0, 0, 0, 0, 0),
        Recorded2026Point("2026-06-16", 104, 95, 101, .04, -.05, .01, 0, -.05, 0),
        Recorded2026Point("2026-06-17", 102, 98, 99, -2 / 104, 3 / 95, -2 / 101,
                          -2 / 104, -.02, -2 / 101),
    )


    return Recorded2026History(
        points=points,
        series=(
            Recorded2026Series("A", .02, -2 / 104, -2 / 104, .04, 102, .5, None),
            Recorded2026Series("A2", -.02, -.05, -.05, 3 / 95, 98, .5, None),
            Recorded2026Series("QQQ", -.01, -2 / 101, -2 / 101, .01, 99, .5, None),
        ),
        subperiods=(Recorded2026Subperiod("2026-06-15", "2026-06-17", .02, -.02, -.01),),
        start_date="2026-06-15", end_date="2026-06-17", return_observations=2,
        source_status="FAIL_CLOSED_ANTI_BLOAT_HARD_GATE", classification="E",
        anti_bloat_status="FAIL_HARD_GATE", accounting_complete=False,
        source_refs=((_PRIVATE, "ab" * 32),),
    )


def _synthetic_calendar_window():
    from apps.demo_console.adapters.calendar_2026_reader import Calendar2026Coverage, Calendar2026History
    from apps.demo_console.adapters.benchmarks_reader import BenchmarkPoint

    original = _synthetic_recorded_window()
    days = ('2026-01-02', '2026-01-05', '2026-01-06')
    values = asdict(original)
    values.update(points=tuple(replace(point, date=day) for point, day in zip(original.points, days)),
        series=original.series, subperiods=(replace(original.subperiods[0], start_date=days[0], end_date=days[-1]),),
        start_date=days[0], end_date=days[-1], source_refs=original.source_refs,
        source_status='RECORDED_DESCRIPTIVE_REPLAY_WITH_COVERAGE_LIMITS', classification='DESCRIPTIVE_ONLY',
        anti_bloat_status='NOT_REASSESSED')
    return Calendar2026History(**values,
        spy_points=(BenchmarkPoint(days[0], 500, 0, 1, 0),
                    BenchmarkPoint(days[1], 495, -.01, .99, -.01),
                    BenchmarkPoint(days[2], 505, 10/495, 1.01, 0)),
        coverage=tuple(Calendar2026Coverage(day, '2025Q3', 643, 492, 480) for day in days),
        model_sha256='4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b',
        original_source_status='FAIL_CLOSED_ANTI_BLOAT_HARD_GATE')


@pytest.fixture
def recorded_stub(monkeypatch, benchmark_stub):
    from apps.demo_console.adapters import recorded_2026_reader

    state = SimpleNamespace(history=_synthetic_recorded_window(), calls=[], benchmarks=benchmark_stub)

    def forbidden(*args, **kwargs):
        raise AssertionError("The UI test must never read a real 2026 source or configuration")

    def synthetic_read(*args, **kwargs):
        assert not args and not kwargs, "The recorded window does not accept a historical case cutoff"
        state.calls.append(True)
        return state.history

    # Patch the adapter before importing the view, and its imported binding
    # afterward. The existing learning_app fixture stubs all historical readers.
    for name in ("default_recorded_2026_config", "_read_daily", "_json"):
        monkeypatch.setattr(recorded_2026_reader, name, forbidden)
    monkeypatch.setattr(recorded_2026_reader, "read_recorded_2026", synthetic_read)
    from apps.demo_console.components import recorded_2026
    monkeypatch.setattr(recorded_2026, "read_recorded_2026", synthetic_read)
    from apps.demo_console.adapters import calendar_2026_reader
    monkeypatch.setattr(calendar_2026_reader, "default_calendar_2026_config", forbidden)
    monkeypatch.setattr(recorded_2026, "read_calendar_2026", forbidden)
    return state


@pytest.fixture
def recorded_app(recorded_stub, request):
    # Explicit dependency ordering guards the initial app render as well.
    state = request.getfixturevalue("learning_app")
    # These tests retain the exact original June source, independently of the
    # new default calendar replay and its separate file-based reader tests.
    state.app.session_state["recorded_2026_source"] = "Original June archive"
    state.recorded = recorded_stub
    before = asdict(recorded_stub.history)
    original = recorded_stub.history
    assert not recorded_stub.calls
    yield state
    assert asdict(original) == before


def _control(app, key):
    return next(item for item in app.get("button_group") if item.key == key)


def _html(app):
    return "\n".join(item.proto.body for item in app.get("html"))


def _path_rows(app):
    charts = app.get("vega_lite_chart")
    assert len(charts) == 1
    chart = charts[0]
    payloads = [chart.proto.data.data, *(dataset.data.data for dataset in chart.proto.datasets)]
    return [row for payload in payloads if payload
            for row in pa.ipc.open_stream(payload).read_all().to_pylist()]


def _expected_rows(history, *, drawdown=False):
    field = "drawdown" if drawdown else "equity"
    return [{"date": point.date, "series": arm, "value": getattr(point, f"{arm.lower()}_{field}")}
            for point in history.points for arm in ("A2", "A", "QQQ")]


def _recorded_path_layer(spec):
    return next(layer for layer in spec["layer"] if layer.get("name") == "recorded_paths")


def _enter_recorded(state):
    app = state.app
    app.selectbox(key="decision_date").select(_CASE_DATE).run()
    app.radio(key="workspace").set_value("Overview").run()
    app.button(key="system_2026").click().run()
    assert not app.exception
    assert app.radio(key="workspace").value == "Research"
    assert _control(app, "research_period").value == _RECORDED
    return app


def _assert_recorded_isolation(state):
    app = state.app
    assert not app.exception
    assert app.session_state["decision_date"] == _CASE_DATE
    assert not any(item.key == "decision_date" for item in app.selectbox)
    assert app.button(key="previous_date").disabled and app.button(key="next_date").disabled
    assert 'class="uq-case-context"' not in _html(app)
    with language_scope(app.selectbox(key="language").value):
        provenance = tr("Decision provenance")
    assert not any(item.label == provenance for item in app.expander)
    assert "SYNTH_ALPHA" not in _content(app)
    assert not state.performance_calls and not state.history_calls


@pytest.mark.parametrize("drawdown", [False, True])
def test_chart_preserves_all_three_original_paths_and_their_losses(drawdown):
    from apps.demo_console.components.recorded_2026 import recorded_2026_chart

    history = _synthetic_recorded_window()
    original = asdict(history)
    spec = recorded_2026_chart(history, drawdown=drawdown).to_dict()
    curve = _recorded_path_layer(spec)
    assert spec["data"]["values"] == _expected_rows(history, drawdown=drawdown)
    assert curve["encoding"]["color"]["scale"]["domain"] == ["A2", "A", "QQQ"]
    assert curve["encoding"]["y"]["scale"]["zero"] is drawdown
    assert curve["encoding"]["x"]["scale"]["domain"] == [history.points[0].date, history.points[-1].date]
    lower, upper = curve["encoding"]["y"]["scale"]["domain"]
    assert lower <= min(row["value"] for row in spec["data"]["values"])
    assert upper >= max(row["value"] for row in spec["data"]["values"])
    if drawdown:
        assert min(row["value"] for row in spec["data"]["values"]) == -.05
        assert max(row["value"] for row in spec["data"]["values"]) == 0
    else:
        assert [row["value"] for row in spec["data"]["values"][-3:]] == [98, 102, 99]
    assert asdict(history) == original


def test_default_historical_mode_never_reads_2026_and_switching_back_restores_case_date(recorded_app):
    state, app = recorded_app, recorded_app.app
    app.selectbox(key="decision_date").select(_CASE_DATE).run()
    app.radio(key="workspace").set_value("Research").run()
    assert not app.exception and not app.error
    assert _control(app, "research_period").value == _HISTORICAL
    assert not state.recorded.calls and state.performance_calls == ["2025-12-03"]
    historical_calls = list(state.performance_calls)
    _control(app, "research_period").select(_RECORDED).run()
    assert not app.exception and not app.error
    assert state.recorded.calls and state.performance_calls == historical_calls
    assert not any(item.key == "decision_date" for item in app.selectbox)
    assert app.session_state["decision_date"] == _CASE_DATE
    recorded_calls = len(state.recorded.calls)
    _control(app, "research_period").select(_HISTORICAL).run()
    assert not app.exception and not app.error
    assert len(state.recorded.calls) == recorded_calls
    assert state.performance_calls == historical_calls + ["2025-12-03"]
    date_control = app.selectbox(key="decision_date")
    assert date_control.value == _CASE_DATE
    assert date_control.proto.set_value and date_control.proto.raw_value == _CASE_DATE
    assert not app.button(key="previous_date").disabled and not app.button(key="next_date").disabled
    assert 'class="uq-case-context"' in _html(app)


def test_home_entry_keeps_failed_acceptance_and_isolates_old_case_provenance(recorded_app):
    state = recorded_app
    app = _enter_recorded(state)
    _assert_recorded_isolation(state)
    assert not app.error
    assert _path_rows(app) == _expected_rows(state.recorded.history)
    content = _content(app)
    assert "2026-06-15" in content and "2026-06-17" in content
    assert "FAIL_CLOSED_ANTI_BLOAT_HARD_GATE" in content and "FAIL_HARD_GATE" in content
    assert "FINAL_CLASSIFICATION: E" in content and "ACCOUNTING_COMPLETE: False" in content
    assert any("did not pass full acceptance" in item.value for item in app.warning)
    assert _PRIVATE not in content and "ab" * 32 not in content


def test_three_languages_keep_drawdown_choice_and_exact_coordinates(recorded_app, monkeypatch, caplog):
    from streamlit.elements.lib import policies

    # Streamlit normally emits this diagnostic only once per Python process.
    # Make the check independent of which other AppTests ran before this one.
    monkeypatch.setattr(policies, "_shown_default_value_warning", False)
    caplog.clear()
    state = recorded_app
    app = _enter_recorded(state)
    _control(app, "recorded_2026_chart_mode").select("Drawdown path").run()
    expected = _expected_rows(state.recorded.history, drawdown=True)
    for language in ("zh", "ja", "en"):
        app.selectbox(key="language").select(language).run()
        _assert_recorded_isolation(state)
        assert not app.error
        assert _control(app, "research_period").value == _RECORDED
        assert _control(app, "recorded_2026_chart_mode").value == "Drawdown path"
        assert _path_rows(app) == expected
        assert _PRIVATE not in _content(app)
    assert not any("recorded_2026_chart_mode" in record.getMessage()
                   and "default value" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("failure", ["error", "empty"])
def test_unavailable_record_fails_closed_without_metrics_or_old_performance_fallback(recorded_app, failure):
    state = recorded_app
    state.recorded.history = (replace(state.recorded.history, error=_ERROR, debug_error=_DEBUG)
                              if failure == "error" else Recorded2026History())
    app = _enter_recorded(state)
    _assert_recorded_isolation(state)
    assert app.error and not app.get("vega_lite_chart") and not app.dataframe
    assert 'class="uq-metrics uq-motion-enter"' not in _html(app)
    assert _DEBUG not in _content(app)
    if failure == "error":
        app.toggle(key="presentation_mode").set_value(False).run()
        _assert_recorded_isolation(state)
        assert _DEBUG in _content(app)
        assert not app.get("vega_lite_chart") and not app.dataframe


def test_explicit_historical_risk_entry_and_tour_research_stop_reset_the_period(recorded_app):
    state = recorded_app
    app = _enter_recorded(state)
    recorded_calls = len(state.recorded.calls)
    app.radio(key="workspace").set_value("Overview").run()
    app.button(key="system_risk").click().run()
    assert not app.exception and not app.error
    assert _control(app, "research_period").value == _HISTORICAL
    assert len(state.recorded.calls) == recorded_calls
    assert app.selectbox(key="decision_date").value == _CASE_DATE
    app.radio(key="workspace").set_value("Overview").run()
    app.button(key="system_2026").click().run()
    recorded_calls = len(state.recorded.calls)
    app.radio(key="workspace").set_value("Overview").run()
    app.button(key="system_start_tour").click().run()
    for _ in range(4):
        app.button(key="demo_tour_next").click().run()
        assert not app.exception and not app.error
        assert app.selectbox(key="decision_date").value == _CASE_DATE
    assert app.radio(key="workspace").value == "Research"
    assert _control(app, "research_period").value == _HISTORICAL
    assert len(state.recorded.calls) == recorded_calls


def test_switching_an_active_tour_to_2026_clears_progress_and_does_not_resume_it(recorded_app):
    state, app = recorded_app, recorded_app.app
    app.selectbox(key="decision_date").select(_CASE_DATE).run()
    app.radio(key="workspace").set_value("Overview").run()
    app.button(key="system_start_tour").click().run()
    for _ in range(4):
        app.button(key="demo_tour_next").click().run()
        assert not app.exception and not app.error
    assert app.radio(key="workspace").value == "Research"
    assert _control(app, "research_period").value == _HISTORICAL
    assert app.session_state["_demo_tour_active"] is True
    assert app.session_state["_demo_tour_step"] == 4
    historical_calls, history_calls = list(state.performance_calls), list(state.history_calls)
    selected_case = app.session_state["_research_case_ticker"]

    _control(app, "research_period").select(_RECORDED).run()
    assert not app.exception and not app.error
    assert app.session_state["_demo_tour_active"] is False
    assert "_demo_tour_step" not in app.session_state
    assert not {"demo_tour_previous", "demo_tour_next", "demo_tour_exit"} & {item.key for item in app.button}
    assert app.session_state["decision_date"] == _CASE_DATE
    assert app.session_state["_research_case_ticker"] == selected_case
    assert not any(item.key == "decision_date" for item in app.selectbox)
    assert state.performance_calls == historical_calls and state.history_calls == history_calls
    assert _path_rows(app) == _expected_rows(state.recorded.history)

    _control(app, "research_period").select(_HISTORICAL).run()
    assert not app.exception and not app.error
    assert app.session_state["_demo_tour_active"] is False
    assert "_demo_tour_step" not in app.session_state
    assert app.selectbox(key="decision_date").value == _CASE_DATE
    assert not any(item.key == "demo_tour_next" for item in app.button)


def _table_with_fields(app, fields):
    matches = [item.value for item in app.dataframe if tuple(item.value.columns) == fields]
    assert len(matches) == 1
    return matches[0]


def test_january_default_discloses_late_coverage_and_empty_q1_retains_only_source_status(recorded_app):
    state = recorded_app
    app = _enter_recorded(state)
    original = asdict(state.recorded.history)
    for language in ("en", "zh", "ja"):
        app.selectbox(key="language").select(language).run()
        _assert_recorded_isolation(state)
        assert app.date_input(key="recorded_2026_range_draft").value == (
            date(2026, 1, 1), date(2026, 6, 17))
        assert _path_rows(app) == _expected_rows(state.recorded.history)
        assert {row["date"] for row in _path_rows(app)} == {"2026-06-15", "2026-06-16", "2026-06-17"}
        with language_scope(language):
            assert tr("This archive contains no observations before {start}. Returns below cover the available observations only; they are not a return since January 1.", start="2026-06-15") in _content(app)
            assert tr("Archive coverage: {start} → {end}. Selected calendar dates do not extend the recorded data.",
                      start="2026-06-15", end="2026-06-17") in _content(app)
        market_calls = list(state.benchmarks.calls)
        app.button(key="recorded_2026_preset_Q1").click().run()
        _assert_recorded_isolation(state)
        assert not app.error and not app.get("vega_lite_chart") and not app.dataframe
        assert 'class="uq-metrics uq-motion-enter"' not in _html(app)
        assert not any(item.key == "recorded_2026_chart_mode" for item in app.get("button_group"))
        assert state.benchmarks.calls == market_calls
        assert "2026-01-01" in _html(app) and "2026-03-31" in _html(app)
        with language_scope(language):
            assert tr("No recorded observations fall within the selected dates.") in _content(app)
        assert "FAIL_CLOSED_ANTI_BLOAT_HARD_GATE" in _content(app)
        assert "FINAL_CLASSIFICATION: E" in _content(app) and "ACCOUNTING_COMPLETE: False" in _content(app)
        assert _PRIVATE not in _content(app) and "ab" * 32 not in _content(app)
        app.button(key="recorded_2026_preset_Since Jan 1").click().run()
        _assert_recorded_isolation(state)
        assert not app.error and _path_rows(app) == _expected_rows(state.recorded.history)
        assert state.benchmarks.calls[-1] == (("2026-06-15", "2026-06-16", "2026-06-17"), None)
        assert asdict(state.recorded.history) == original


def test_custom_2026_range_retains_first_losses_across_languages_navigation_and_single_day(recorded_app):
    from apps.demo_console.tests.test_benchmark_view import _markets

    state = recorded_app
    state.benchmarks.response = _markets
    app = _enter_recorded(state)
    original = asdict(state.recorded.history)
    chosen = (date(2026, 6, 16), date(2026, 6, 17))
    app.date_input(key="recorded_2026_range_draft").set_value(chosen)
    app.button(key="recorded_2026_range_apply").click().run()
    for language in ("en", "zh", "ja"):
        app.selectbox(key="language").select(language).run()
        _assert_recorded_isolation(state)
        assert not app.error and app.date_input(key="recorded_2026_range_draft").value == chosen
        assert state.benchmarks.calls[-1] == (("2026-06-16", "2026-06-17"), "2026-06-15")
        rows = _path_rows(app)
        assert [row["value"] for row in rows if row["series"] == "A2"] == [95, 98]
        assert [row["value"] for row in rows if row["series"] == "A"] == [104, 102]
        assert [row["value"] for row in rows if row["series"] == "QQQ"] == [101, 99]
        assert [row["value"] for row in rows if row["series"] == "SPY · S&P 500"] == pytest.approx([99.7, 99.4009])
        comparison = _table_with_fields(app, ("series", "return", "drawdown", "worst", "best")).set_index("series")
        assert comparison.loc["A2", "return"] == pytest.approx(-.02)
        assert comparison.loc["A2", "worst"] == pytest.approx(-.05)
        assert comparison.loc["SPY · S&P 500", "return"] == pytest.approx(.997 ** 2 - 1)
        assert comparison.loc["SPY · S&P 500", "worst"] == pytest.approx(-.003)
        daily = _table_with_fields(app, ("date", "A2", "A", "QQQ"))
        assert daily.to_dict("records") == [
            {"date": "2026-06-16", "A2": 95, "A": 104, "QQQ": 101},
            {"date": "2026-06-17", "A2": 98, "A": 102, "QQQ": 99}]
        with language_scope(language):
            assert tr("CUSTOM DATE RANGE") in _html(app)
            assert tr("Displayed observations: {start} → {end} · Return baseline: {baseline}",
                      start="2026-06-16", end="2026-06-17", baseline="2026-06-15") in _content(app)
        assert all(button.proto.type == "secondary" for button in app.button
                   if button.key and button.key.startswith("recorded_2026_preset_"))
    before = _path_rows(app)
    app.radio(key="workspace").set_value("Overview").run()
    app.radio(key="workspace").set_value("Research").run()
    _assert_recorded_isolation(state)
    assert app.date_input(key="recorded_2026_range_draft").value == chosen and _path_rows(app) == before
    # One cropped observation is still a return, not a zero-return baseline.
    app.date_input(key="recorded_2026_range_draft").set_value((chosen[0], chosen[0]))
    app.button(key="recorded_2026_range_apply").click().run()
    for mode in ("Equity path", "Drawdown path"):
        _control(app, "recorded_2026_chart_mode").select(mode).run()
        _assert_recorded_isolation(state)
        assert state.benchmarks.calls[-1] == (("2026-06-16",), "2026-06-15")
        spec = json.loads(app.get("vega_lite_chart")[0].proto.spec)
        curve = _recorded_path_layer(spec)
        assert curve["mark"]["point"] is True
        assert curve["encoding"]["x"]["scale"]["domain"] == ["2026-06-15", "2026-06-17"]
        rows = _path_rows(app)
        assert len(rows) == 4 and {row["date"] for row in rows} == {"2026-06-16"}
        expected = {"A2": -.05, "A": 0, "QQQ": 0, "SPY · S&P 500": -.003} if mode == "Drawdown path" else {
            "A2": 95, "A": 104, "QQQ": 101, "SPY · S&P 500": 99.7}
        assert {row["series"]: row["value"] for row in rows} == pytest.approx(expected)
        table = _table_with_fields(app, ("series", "return", "drawdown", "worst", "best")).set_index("series")
        assert table.loc["A2", "return"] == pytest.approx(-.05)
        assert table.loc["SPY · S&P 500", "return"] == pytest.approx(-.003)
        assert table.loc["SPY · S&P 500", "worst"] == pytest.approx(-.003)
        assert "-9.00 pp" in _html(app) and "-5.00%" in _html(app)
        assert _table_with_fields(app, ("date", "A2", "A", "QQQ")).to_dict("records") == [
            {"date": "2026-06-16", "A2": 95, "A": 104, "QQQ": 101}]
    app.button(key="recorded_2026_preset_Q2").click().run()
    _control(app, "recorded_2026_chart_mode").select("Equity path").run()
    _assert_recorded_isolation(state)
    assert app.date_input(key="recorded_2026_range_draft").value == (date(2026, 4, 1), date(2026, 6, 17))
    assert _path_rows(app)[:9] == _expected_rows(state.recorded.history)
    assert state.benchmarks.calls[-1] == (("2026-06-15", "2026-06-16", "2026-06-17"), None)
    assert asdict(state.recorded.history) == original


def test_calendar_replay_has_its_own_four_paths_and_keeps_the_original_source_separate(recorded_app, monkeypatch):
    from apps.demo_console.components import recorded_2026

    state = recorded_app
    history = _synthetic_calendar_window()
    original = asdict(history)
    monkeypatch.setattr(recorded_2026, 'read_calendar_2026', lambda: history)
    state.app.session_state['recorded_2026_source'] = recorded_2026.CALENDAR_REPLAY
    app = _enter_recorded(state)
    _assert_recorded_isolation(state)
    assert not app.error and not state.recorded.calls and not state.benchmarks.calls
    assert {row['series'] for row in _path_rows(app)} == {'A', 'A2', 'QQQ', 'SPY · S&P 500'}
    assert '2026-01-01' in _content(app) and '2026-01-02' in _content(app)
    assert 'DESCRIPTIVE_ONLY' in _content(app) and 'NOT_REASSESSED' in _content(app)
    assert 'ORIGINAL_JUNE_STATUS: FAIL_CLOSED_ANTI_BLOAT_HARD_GATE' in _content(app)
    app.date_input(key='recorded_2026_range_draft').set_value((date(2026, 1, 5), date(2026, 1, 6)))
    app.button(key='recorded_2026_range_apply').click().run()
    expected = _path_rows(app)
    assert {row['date'] for row in expected} == {'2026-01-05', '2026-01-06'}
    assert next(row['value'] for row in expected if row['series'] == 'A2') == 95
    assert next(row['value'] for row in expected if row['series'] == 'SPY · S&P 500') == 99
    for language in ('zh', 'ja', 'en'):
        app.selectbox(key='language').select(language).run()
        _assert_recorded_isolation(state)
        assert not app.error and _path_rows(app) == expected
        assert app.radio(key='recorded_2026_source').value == recorded_2026.CALENDAR_REPLAY
    coverage_tables = [frame.value for frame in app.dataframe if 'eligible' in frame.value.columns]
    assert len(coverage_tables) == 1 and coverage_tables[0]['date'].tolist() == ['2026-01-05', '2026-01-06']
    app.radio(key='recorded_2026_source').set_value(recorded_2026.JUNE_ARCHIVE).run()
    assert not app.exception and not app.error and state.recorded.calls
    assert _path_rows(app) == _expected_rows(state.recorded.history)
    assert 'FINAL_CLASSIFICATION: E' in _content(app)
    assert app.date_input(key='recorded_2026_range_draft').value == (date(2026, 1, 1), date(2026, 6, 17))
    assert asdict(history) == original


@pytest.mark.parametrize("selection", ["quarter", "custom"])
def test_localized_source_round_trip_cannot_reset_the_applied_window(recorded_app, monkeypatch, selection):
    from apps.demo_console.components import recorded_2026

    state = recorded_app
    history = _synthetic_calendar_window()
    monkeypatch.setattr(recorded_2026, "read_calendar_2026", lambda: history)
    state.app.session_state["recorded_2026_source"] = recorded_2026.CALENDAR_REPLAY
    app = _enter_recorded(state)
    app.selectbox(key="language").select("zh").run()
    app.button(key="recorded_2026_preset_Q1").click().run()
    if selection == "custom":
        app.date_input(key="recorded_2026_range_draft").set_value((date(2026, 1, 5), date(2026, 1, 6)))
        app.button(key="recorded_2026_range_apply").click().run()
    expected_dates = app.date_input(key="recorded_2026_range_draft").value
    expected_rows = _path_rows(app)

    for language in ("ja", "en", "zh"):
        with language_scope(app.selectbox(key="language").value):
            previous_source_label = tr(recorded_2026.CALENDAR_REPLAY)
        app.selectbox(key="language").select(language).run()
        # The browser can return the previous language's displayed radio value
        # after receiving updated labels. AppTest's ordinary run uses the new
        # serializer and does not reproduce that delayed client state.
        states = app._tree.get_widget_states()
        radio_id = app.radio(key="recorded_2026_source").proto.id
        next(widget for widget in states.widgets if widget.id == radio_id).string_value = previous_source_label
        app._run(states)
        _assert_recorded_isolation(state)
        assert not app.error
        assert app.session_state["recorded_2026_preset"] == "Q1"
        assert app.date_input(key="recorded_2026_range_draft").value == expected_dates
        assert _path_rows(app) == expected_rows
        source = app.radio(key="recorded_2026_source")
        assert source.value == recorded_2026.CALENDAR_REPLAY
        with language_scope(language):
            assert source.proto.set_value and source.proto.raw_value == tr(recorded_2026.CALENDAR_REPLAY)
        app.run()
        assert not app.exception and not app.error
        assert app.date_input(key="recorded_2026_range_draft").value == expected_dates
        assert _path_rows(app) == expected_rows

    # An actual switch to a different cash baseline still resets both kinds of
    # date selection, so the old calendar interval is never silently reused.
    app.radio(key="recorded_2026_source").set_value(recorded_2026.JUNE_ARCHIVE).run()
    assert not app.exception and not app.error
    assert app.session_state["recorded_2026_preset"] == "Since Jan 1"
    assert app.date_input(key="recorded_2026_range_draft").value == (date(2026, 1, 1), date(2026, 6, 17))
    assert _path_rows(app) == _expected_rows(state.recorded.history)


def test_repeated_source_callback_preserves_semantically_unchanged_selection(monkeypatch):
    from apps.demo_console.components import recorded_2026

    state = {
        "recorded_2026_source": recorded_2026.CALENDAR_REPLAY,
        "_recorded_2026_active_source": recorded_2026.CALENDAR_REPLAY,
        "recorded_2026_preset": "Q1",
        "_performance_range:recorded_2026_range:applied": ("2026-01-05", "2026-01-06"),
    }
    before = dict(state)
    monkeypatch.setattr(recorded_2026, "st", SimpleNamespace(session_state=state))
    recorded_2026._change_source()
    assert state == before


def test_calendar_source_failure_cannot_fall_back_to_a_june_result(recorded_app, monkeypatch):
    from apps.demo_console.adapters.calendar_2026_reader import Calendar2026History
    from apps.demo_console.components import recorded_2026

    state = recorded_app
    monkeypatch.setattr(recorded_2026, 'read_calendar_2026',
        lambda: Calendar2026History(error='Synthetic calendar verification failed'))
    state.app.session_state['recorded_2026_source'] = recorded_2026.CALENDAR_REPLAY
    app = _enter_recorded(state)
    assert app.error and not app.get('vega_lite_chart') and not app.dataframe
    assert not state.recorded.calls and not state.benchmarks.calls
    assert 'class="uq-metric-value"' not in _html(app)


def test_single_day_small_drawdown_has_distinct_actual_vega_axis_labels_in_three_languages():
    from apps.demo_console.components.recorded_2026 import recorded_2026_chart
    from apps.demo_console.components.recorded_2026_window import slice_recorded_2026
    from apps.demo_console.tests.test_vega_initialization import _run_specs

    history = replace(_synthetic_recorded_window(), points=(
        Recorded2026Point("2026-06-15", 100, 100, 100, 0, 0, 0, 0, 0, 0),
        Recorded2026Point("2026-06-16", 100.02, 99.95, 100.01, .0002, -.0005, .0001, 0, -.0005, 0),
    ), series=(), subperiods=(), end_date="2026-06-16", return_observations=1)
    original = asdict(history)
    window = slice_recorded_2026(history, "2026-06-16", "2026-06-16")
    specs = []
    for language in ("en", "zh", "ja"):
        with language_scope(language):
            specs.append(recorded_2026_chart(window, drawdown=True).to_dict())
    for spec, rendered in zip(specs, _run_specs(specs)["results"], strict=True):
        assert rendered["warnings"] == [] and rendered["initialWarnings"] == []
        assert rendered["loadedRows"] == spec["data"]["values"] and rendered["cleared"] == 0
        assert len(rendered["loadedRows"]) == 3 and {row["date"] for row in rendered["loadedRows"]} == {"2026-06-16"}
        assert _recorded_path_layer(spec)["mark"]["point"] is True
        ticks = [item for item in rendered["axisLabels"] if item["text"].endswith("%")]
        assert len(ticks) >= 2
        assert len({item["text"] for item in ticks}) == len(ticks)
        negative = [item for item in ticks if item["value"] < 0]
        assert negative
        for tick in negative:
            displayed = float(tick["text"].replace("\N{MINUS SIGN}", "-").removesuffix("%")) / 100
            assert displayed < 0 and displayed == pytest.approx(tick["value"], rel=.01)
    assert asdict(history) == original
