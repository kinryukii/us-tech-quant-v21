"""Curve focus changes visibility, never the verified comparison window or data."""
from dataclasses import asdict

import pytest
from streamlit.testing.v1 import AppTest

from apps.demo_console.i18n import language_scope, tr
from apps.demo_console.tests.test_benchmark_view import (
    _comparison, _markets, _research_benchmark_app, _wealth_payload,
)
from apps.demo_console.tests.test_machine_learning_view import learning_app
from apps.demo_console.tests.test_performance_charts import _folded_fields
from apps.demo_console.tests.test_recorded_2026_view import (
    _assert_recorded_isolation, _control, _enter_recorded, _path_rows,
    _synthetic_calendar_window, recorded_app, recorded_stub,
)

_PAIRS = ("A2 / A", "A2 / QQQ", "A2 / SPY")
_FIELDS = {"A": "reference_net_wealth", "QQQ": "benchmark_qqq", "SPY": "benchmark_spy"}


@pytest.fixture(autouse=True)
def isolate_all_recorded_sources(recorded_stub):
    """Even historical-only tests may not fall through to a real 2026 reader."""
    return recorded_stub


def _focus_app():
    import streamlit as st
    from apps.demo_console.components.market_benchmarks import render_curve_focus
    from apps.demo_console.i18n import language_scope

    language = st.selectbox("Language", ("en", "zh", "ja"), key="language")
    available = tuple(symbol for symbol in ("A", "QQQ", "SPY")
                      if st.checkbox(symbol, value=True, key=f"available_{symbol}"))
    st.session_state.setdefault("decision_date", "2025-12-02")
    with language_scope(language):
        st.session_state["resolved_focus"] = render_curve_focus("focus", available=available)


def _delayed_label(app, key, label):
    # AppTest normally serializes using the new language. Replay the previous
    # displayed label explicitly to represent a delayed browser widget update.
    states = app._tree.get_widget_states()
    widget_id = _control(app, key).proto.id
    next(widget for widget in states.widgets if widget.id == widget_id).string_array_value.data[:] = [label]
    app._run(states)
    assert not app.exception and not app.error


def test_default_all_returns_none_and_pairs_return_only_the_two_original_symbols():
    app = AppTest.from_function(_focus_app).run()
    assert not app.exception
    assert _control(app, "focus").value == "All curves"
    assert _control(app, "focus").options == ["All curves", *_PAIRS]
    assert app.session_state["resolved_focus"] is None
    for selection in _PAIRS:
        _control(app, "focus").select(selection).run()
        assert not app.exception
        assert app.session_state["resolved_focus"] == ("A2", selection.rsplit(" / ", 1)[1])
        assert app.session_state["decision_date"] == "2025-12-02"
    _control(app, "focus").select("All curves").run()
    assert app.session_state["resolved_focus"] is None


@pytest.mark.parametrize("selection", ("All curves", *_PAIRS))
def test_language_round_trips_and_delayed_old_labels_preserve_semantic_selection(selection):
    app = AppTest.from_function(_focus_app).run()
    _control(app, "focus").select(selection).run()
    expected = None if selection == "All curves" else ("A2", selection.rsplit(" / ", 1)[1])
    for language in ("zh", "ja", "en"):
        with language_scope(app.selectbox(key="language").value):
            previous_label = tr(selection)
        app.selectbox(key="language").select(language).run()
        _delayed_label(app, "focus", previous_label)
        assert _control(app, "focus").value == selection
        assert app.session_state["resolved_focus"] == expected
        assert app.session_state["decision_date"] == "2025-12-02"
        with language_scope(language):
            assert _control(app, "focus").formatted_values == [tr(selection)]
        app.run()
        assert not app.exception and app.session_state["resolved_focus"] == expected


@pytest.mark.parametrize("symbol", ("A", "QQQ", "SPY"))
def test_disappearing_reference_removes_its_option_and_resets_old_pair_to_all(symbol):
    app = AppTest.from_function(_focus_app).run()
    selection = f"A2 / {symbol}"
    _control(app, "focus").select(selection).run()
    app.checkbox(key=f"available_{symbol}").uncheck().run()
    assert not app.exception and not app.error
    assert selection not in _control(app, "focus").options
    assert _control(app, "focus").value == "All curves"
    assert app.session_state["resolved_focus"] is None
    _delayed_label(app, "focus", selection)
    assert _control(app, "focus").value == "All curves"
    assert app.session_state["resolved_focus"] is None
    app.checkbox(key=f"available_{symbol}").check().run()
    assert _control(app, "focus").value == "All curves"


@pytest.mark.parametrize("remembered,expected", [("A2 / QQQ", ("A2", "QQQ")),
                                                  ("A2 / UNKNOWN", None)])
def test_unrecognized_control_value_uses_only_a_current_valid_remembered_choice(remembered, expected):
    app = AppTest.from_function(_focus_app)
    app.session_state["focus"] = "Obsolete localized label"
    app.session_state["_focus_selected"] = remembered
    app.run()
    assert not app.exception and app.session_state["resolved_focus"] == expected


def test_historical_focus_keeps_all_values_dates_and_full_risk_table(benchmark_stub):
    benchmark_stub.response = _markets
    app = AppTest.from_function(_research_benchmark_app, default_timeout=30).run()
    app.selectbox(key="research_range").select("63 execution days").run()
    assert not app.exception and not app.error
    original_spec, original_rows = _wealth_payload(app)
    assert len(original_rows) == 63
    assert _folded_fields(original_spec) == {"net_wealth", *_FIELDS.values()}
    original_call = benchmark_stub.calls[-1]
    assert original_call[1] is not None
    for language in ("en", "zh", "ja"):
        app.selectbox(key="language").select(language).run()
        table = _comparison(app).copy(deep=True)
        assert len(table) == 4
        for selection in _PAIRS:
            _control(app, "research_curve_focus").select(selection).run()
            assert not app.exception and not app.error
            spec, rows = _wealth_payload(app)
            assert rows == original_rows
            assert _folded_fields(spec) == {"net_wealth", _FIELDS[selection.rsplit(" / ", 1)[1]]}
            assert _comparison(app).equals(table)
            assert benchmark_stub.calls[-1] == original_call
            assert app.session_state["decision_date"] == "2025-08-21"
        _control(app, "research_curve_focus").select("All curves").run()
        assert _folded_fields(_wealth_payload(app)[0]) == {"net_wealth", *_FIELDS.values()}


def test_historical_missing_spy_resets_focus_without_shortening_any_other_series(benchmark_stub):
    benchmark_stub.response = _markets
    app = AppTest.from_function(_research_benchmark_app, default_timeout=30).run()
    _control(app, "research_curve_focus").select("A2 / SPY").run()
    _, original = _wealth_payload(app)
    table = _comparison(app).iloc[:3].copy(deep=True)
    benchmark_stub.response = lambda dates, baseline: _markets(dates, baseline, missing_spy=True)
    app.run()
    assert not app.exception and not app.error
    assert _control(app, "research_curve_focus").value == "All curves"
    assert "A2 / SPY" not in _control(app, "research_curve_focus").options
    spec, rows = _wealth_payload(app)
    assert _folded_fields(spec) == {"net_wealth", "reference_net_wealth", "benchmark_qqq"}
    assert rows == [{key: value for key, value in row.items() if key != "benchmark_spy"} for row in original]
    assert _comparison(app).equals(table)


@pytest.mark.parametrize("calendar", [False, True])
def test_recorded_focus_filters_both_chart_modes_but_preserves_full_risk_comparison(recorded_app, monkeypatch, calendar):
    from apps.demo_console.components import recorded_2026

    state = recorded_app
    history = _synthetic_calendar_window() if calendar else state.recorded.history
    if calendar:
        monkeypatch.setattr(recorded_2026, "read_calendar_2026", lambda: history)
        state.app.session_state["recorded_2026_source"] = recorded_2026.CALENDAR_REPLAY
    else:
        state.benchmarks.response = _markets
    before = asdict(history)
    app = _enter_recorded(state)
    dates = app.date_input(key="recorded_2026_range_draft").value
    table = _comparison(app, recorded=True).copy(deep=True)
    assert len(table) == 4
    for mode in ("Equity path", "Drawdown path"):
        _control(app, "recorded_2026_chart_mode").select(mode).run()
        _control(app, "recorded_2026_curve_focus").select("All curves").run()
        all_rows = _path_rows(app)
        for selection in _PAIRS:
            _control(app, "recorded_2026_curve_focus").select(selection).run()
            _assert_recorded_isolation(state)
            symbol = selection.rsplit(" / ", 1)[1]
            names = {"A2", "SPY · S&P 500" if symbol == "SPY" else symbol}
            assert _path_rows(app) == [row for row in all_rows if row["series"] in names]
            assert _comparison(app, recorded=True).equals(table)
            assert app.date_input(key="recorded_2026_range_draft").value == dates
    expected = _path_rows(app)
    for language in ("zh", "ja", "en"):
        with language_scope(app.selectbox(key="language").value):
            old_label = tr("A2 / SPY")
        app.selectbox(key="language").select(language).run()
        _delayed_label(app, "recorded_2026_curve_focus", old_label)
        _assert_recorded_isolation(state)
        assert _path_rows(app) == expected
        assert len(_comparison(app, recorded=True)) == 4
        assert app.date_input(key="recorded_2026_range_draft").value == dates
    assert asdict(history) == before


def test_recorded_missing_spy_falls_back_to_three_original_paths_and_keeps_source(recorded_app):
    state = recorded_app
    state.benchmarks.response = _markets
    app = _enter_recorded(state)
    original_rows = [row for row in _path_rows(app) if row["series"] != "SPY · S&P 500"]
    table = _comparison(app, recorded=True).iloc[:3].copy(deep=True)
    source = app.radio(key="recorded_2026_source").value
    _control(app, "recorded_2026_curve_focus").select("A2 / SPY").run()
    state.benchmarks.response = lambda dates, baseline: _markets(dates, baseline, missing_spy=True)
    app.run()
    _assert_recorded_isolation(state)
    assert _control(app, "recorded_2026_curve_focus").value == "All curves"
    assert "A2 / SPY" not in _control(app, "recorded_2026_curve_focus").options
    assert _path_rows(app) == original_rows
    assert _comparison(app, recorded=True).equals(table)
    assert app.radio(key="recorded_2026_source").value == source
