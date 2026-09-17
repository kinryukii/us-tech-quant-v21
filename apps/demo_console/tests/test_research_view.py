"""Research UI regressions over synthetic observations; never read performance artifacts."""
from dataclasses import asdict, replace
import json
from types import SimpleNamespace

import pandas as pd
import pyarrow as pa
import pytest

from apps.demo_console.i18n import catalog
from apps.demo_console.models import PerformanceHistory, PerformancePoint
from apps.demo_console.tests.test_terminal_interactions import _content, terminal_app


_PATH = r"C:\synthetic-private\performance\portfolio_daily.parquet"
_HASH = "a3" * 32
_DEBUG = f"SYNTHETIC_PRIVATE_PERFORMANCE_DEBUG | {_PATH} | {_HASH}"
_REFERENCE_DEBUG = "SYNTHETIC_PRIVATE_REFERENCE_DEBUG"
_REFERENCE_ERROR = "Frozen A reference is unavailable; A2 remains independently available."
_ERROR = "Frozen performance is unavailable. Check the source evidence in Debug mode."
_INDEPENDENCE_NOTE = (
    "A complete trial history, independent out-of-sample protocol and "
    "selection-bias-adjusted evaluation are not available in this display."
)


def _label(source, language):
    return source if language == "en" else catalog()[source][language]


def _synthetic_archive():
    # This is a synthetic recorded calendar, not an inferred exchange calendar.
    dates = ("2024-12-31", *pd.bdate_range(end="2025-12-04", periods=71).strftime("%Y-%m-%d"))
    points, nav, reference_nav = [], 1.0, 1.0
    for index, day in enumerate(dates):
        net = -0.01 if index == 0 else (0.004, -0.003, 0.002, -0.001, 0.0)[index % 5]
        if day == dates[-1]:
            net = 0.777  # Deliberately conspicuous observation AFTER both selected executions.
        cost = 0.01 if index == 0 else 0.0001
        reference_net, reference_cost = (-0.002, 0.002) if index == 0 else (0.0005, 0.00005)
        gross, reference_gross = net + cost / nav, reference_net + reference_cost / reference_nav
        nav, reference_nav = nav * (1 + net), reference_nav * (1 + reference_net)
        points.append(PerformancePoint(
            execution_date=day, nav=nav, net_return=net, gross_return=gross,
            transaction_cost=cost, turnover=0.1, cash=0.0, position_value=nav,
            holding_count=20, stale_mark_count=0, skipped_buy_count=0,
            blocked_rebalance_count=0, buy_cash_scale=1.0,
            reference_nav=reference_nav, reference_net_return=reference_net,
            reference_gross_return=reference_gross, reference_transaction_cost=reference_cost,
        ))
    return PerformanceHistory(
        points=tuple(points), available_dates=dates, archive_start=dates[0], archive_end=dates[-1],
        initial_nav=1.0, reference_available=True, reference_identity="A1",
        source_refs=((_PATH, _HASH),), debug_error=_DEBUG,
        limitations=("Transaction costs and cash are amounts in initial-NAV units, "
                     "not percentages or currency account balances.",),
    )


def _risk_comparison_app():
    """Render the real Research section using only in-memory synthetic rows."""
    from dataclasses import replace
    import streamlit as st
    from apps.demo_console.components.performance_stats import summarize_performance
    from apps.demo_console.adapters.benchmarks_reader import BenchmarkHistory
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.pages.research import _performance
    from apps.demo_console.tests.test_research_view import _synthetic_archive

    language = st.selectbox("Language", ("en", "zh", "ja"), key="language")
    available = st.checkbox("Synthetic reference available", key="reference_available")
    archive = _synthetic_archive()
    points = archive.points[:3]
    if not available:
        points = tuple(replace(point, reference_nav=None, reference_net_return=None,
                               reference_gross_return=None, reference_transaction_cost=None) for point in points)
    summary = summarize_performance(points, full_history_dates=archive.available_dates)
    with language_scope(language):
        _performance(summary, True, False, points=points,
                     full_history_dates=archive.available_dates, initial_nav=archive.initial_nav,
                     markets=BenchmarkHistory(), presentation=True)


def test_risk_comparison_copy_matches_missing_reference_rows_in_all_three_languages(benchmark_stub):
    from streamlit.testing.v1 import AppTest

    missing = "Frozen A is unavailable for this window. Any complete market references remain visible."
    paired = ("The same execution dates and net-return basis are used for both portfolios. "
              "A higher return can come with a deeper drawdown; this is not a risk-adjusted ranking.")
    app = AppTest.from_function(_risk_comparison_app, default_timeout=20).run()
    original_a2 = None
    for language in ("en", "zh", "ja"):
        app.selectbox(key="language").select(language).run()
        for reference_available in (False, True, False):
            app.checkbox(key="reference_available").set_value(reference_available).run()
            assert not app.exception and not app.error
            panel = next(expander for expander in app.expander
                         if expander.label == _label("Compare return and downside", language))
            captions = [caption.value for caption in panel.caption]
            expected, absent = (paired, missing) if reference_available else (missing, paired)
            assert _label(expected, language) in captions
            assert _label(absent, language) not in captions
            table = panel.dataframe[0].value
            assert len(table) == (2 if reference_available else 1)
            assert table.iloc[0]["series"] == "Raw A2"
            economic = table.iloc[0].drop("series").to_dict()
            if original_a2 is None:
                original_a2 = economic
            assert economic == original_a2
            assert economic["observations"] == 3


def _execution_tabs_app():
    """Exercise the full Research page without any artifact fixture or read."""
    from dataclasses import asdict, replace
    from unittest.mock import patch
    import streamlit as st
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.models import DecisionOverview, Provenance
    from apps.demo_console.pages import research
    from apps.demo_console.tests.test_research_view import _synthetic_archive

    language = st.selectbox("Language", ("en", "zh", "ja"), key="language")
    st.session_state.setdefault("decision_date", "2025-12-02")
    archive = _synthetic_archive()
    original = asdict(archive)
    model = DecisionOverview(decision_date=st.session_state["decision_date"],
                             provenance=Provenance(execution_date="2025-12-03"))

    def performance(cutoff):
        st.session_state.setdefault("synthetic_performance_calls", []).append(cutoff)
        assert cutoff == model.provenance.execution_date
        points = tuple(point for point in archive.points if point.execution_date <= cutoff)
        return replace(archive, points=points, requested_end_date=cutoff, effective_end_date=points[-1].execution_date)

    with language_scope(language), patch.object(research, "read_performance", performance):
        research.render_research(model, presentation=True)
    assert asdict(archive) == original


def test_execution_tab_is_append_only_localized_and_preserves_legacy_routes_and_cutoff(benchmark_stub):
    from streamlit.testing.v1 import AppTest
    from apps.demo_console.tests.test_localized_tabs import _switch_tab

    sources = ("Performance path", "Drawdown & recovery", "Consistency & concentration", "Evidence & method",
               "Execution frictions")
    app = AppTest.from_function(_execution_tabs_app, default_timeout=20)
    app.session_state["_localized_tabs:research_tabs"] = "Execution frictions"
    app.run()
    assert not app.exception and not app.error
    assert app.get("tab_container")[0].proto.tab_container.default_tab_index == 4
    assert [tab.label for tab in app.tabs] == list(sources)
    assert not any("Stale mark count" in table.value.columns for table in app.tabs[0].dataframe)
    assert sum("Stale mark count" in table.value.columns for table in app.tabs[4].dataframe) == 1
    original = _charts(app)["execution"][1]
    assert len(original) == len([point for point in _synthetic_archive().points
                                 if point.execution_date <= "2025-12-03"])
    for language in ("zh", "ja", "en"):
        app.selectbox(key="language").select(language).run()
        assert not app.exception and not app.error
        assert [tab.label for tab in app.tabs] == [_label(source, language) for source in sources]
        assert app.get("tab_container")[0].proto.tab_container.default_tab_index == 4
        assert app.session_state["research_tabs"] == _label("Execution frictions", language)
        assert app.session_state["_localized_tabs:research_tabs"] == "Execution frictions"
        assert _charts(app)["execution"][1] == original
    for index, source in enumerate(sources[:4]):
        app.session_state["_localized_tabs:research_tabs"] = source
        app.run()
        assert not app.exception and not app.error
        assert app.get("tab_container")[0].proto.tab_container.default_tab_index == index
        assert _charts(app)["execution"][1] == original
    _switch_tab(app, "Execution frictions")
    app.selectbox(key="research_range").select("63 execution days").run()
    assert not app.exception and not app.error
    assert app.get("tab_container")[0].proto.tab_container.default_tab_index == 4
    assert _charts(app)["execution"][1] == original[-63:]
    assert all(row["execution_date"] <= "2025-12-03" for row in _charts(app)["execution"][1])
    assert app.session_state["decision_date"] == "2025-12-02"
    assert set(app.session_state["synthetic_performance_calls"]) == {"2025-12-03"}


@pytest.fixture
def research_app(terminal_app, monkeypatch, benchmark_stub):
    from apps.demo_console.adapters import performance_reader
    from apps.demo_console.pages import research

    app, models = terminal_app
    archive = _synthetic_archive()
    before = asdict(archive)
    state = SimpleNamespace(app=app, models=models, archive=archive, calls=[], mode="normal", benchmarks=benchmark_stub)

    def forbidden_real_reader(*args, **kwargs):
        raise AssertionError("Research AppTest must never call the real performance reader")

    def synthetic_performance(end_date=None):
        state.calls.append(end_date)
        if state.mode == "a2_failure":
            return PerformanceHistory(error=_ERROR, debug_error=_DEBUG)
        points = tuple(point for point in archive.points if point.execution_date <= end_date)
        if state.mode == "short_history":
            points = points[-62:]
        history = replace(archive, points=points, requested_end_date=end_date,
                          effective_end_date=points[-1].execution_date if points else None)
        if state.mode == "reference_failure":
            history = replace(
                history,
                points=tuple(replace(point, reference_nav=None, reference_net_return=None,
                                     reference_gross_return=None, reference_transaction_cost=None)
                             for point in points),
                reference_available=False, reference_identity=None,
                reference_error=_REFERENCE_ERROR, reference_debug_error=_REFERENCE_DEBUG,
            )
        return history

    # Patch the already-imported page before navigating to Research. A second
    # guard ensures later refactoring cannot accidentally reach the real reader.
    monkeypatch.setattr(research, "read_performance", synthetic_performance)
    monkeypatch.setattr(performance_reader, "read_performance", forbidden_real_reader)
    yield state
    assert asdict(archive) == before


def _charts(app):
    """Inspect serialized observations actually sent to the research charts."""
    charts = {}
    for element in app.get("vega_lite_chart"):
        payloads = [element.proto.data.data, *(dataset.data.data for dataset in element.proto.datasets)]
        records = [row for payload in payloads if payload
                   for row in pa.ipc.open_stream(payload).read_all().to_pylist() if row]
        assert records, "A research chart lost its serialized observations"
        first = records[0]
        spec = json.loads(element.proto.spec)
        kind = ("episode" if spec.get("name") == "research_drawdown_episode_chart"
                else "month_detail" if spec.get("name") == "research_month_detail_chart"
                else "rolling" if spec.get("name") == "research_rolling_chart"
                else "wealth" if "net_wealth" in first else "drawdown" if "drawdown" in first else "month" if "month" in first
                else "year" if "series" in first else "execution" if "turnover" in first else "distribution")
        assert kind not in charts
        charts[kind] = (spec, records)
    required = {"wealth", "drawdown", "month", "year", "month_detail", "execution", "distribution"}
    if min(row["drawdown"] for row in charts["wealth"][1]) < -1e-12:
        required.add("episode")
    if len(charts["wealth"][1]) >= 63:
        required.add("rolling")
    assert set(charts) == required
    return charts


def _economic_payload(app):
    # Labels intentionally change language; economic coordinates must not.
    fields = (
        "execution_date", "net_wealth", "gross_wealth", "drawdown", "reference_net_wealth",
        "reference_gross_wealth", "period", "start_date", "end_date", "observations",
        "net_return", "gross_return", "reference_net_return", "reference_gross_return",
        "net_difference_pp", "window_partial", "coverage_boundary", "series", "return",
    )
    return {kind: [tuple(row.get(field) for field in fields) for row in records]
            for kind, (_, records) in _charts(app).items()}


def _period_table(app, language="en"):
    return next(element.value for element in app.dataframe
                if _label("Period", language) in element.value.columns)


def _folds(value):
    if isinstance(value, dict):
        if "fold" in value:
            yield value["fold"]
        for child in value.values():
            yield from _folds(child)
    elif isinstance(value, list):
        for child in value:
            yield from _folds(child)


def _assert_cutoff(state, decision_date):
    app = state.app
    assert not app.exception and not app.error
    expected_execution = state.models[decision_date].provenance.execution_date
    assert app.selectbox(key="decision_date").value == decision_date
    assert state.calls[-1] == expected_execution
    records = _charts(app)["wealth"][1]
    assert records[-1]["execution_date"] == expected_execution
    assert all(row["execution_date"] <= expected_execution for row in records)
    assert "2025-12-04" not in {row["execution_date"] for row in records}
    detail = _charts(app)["month_detail"][1]
    assert all(row["execution_date"] <= expected_execution for row in detail)
    assert {row["execution_date"] for row in detail} <= {row["execution_date"] for row in records}
    if "episode" in _charts(app):
        episode = _charts(app)["episode"][1]
        full_drawdown = {row["execution_date"]: row["drawdown"] for row in records}
        assert all(row["execution_date"] <= expected_execution for row in episode)
        assert all(row["drawdown"] == full_drawdown[row["execution_date"]] for row in episode)
    risk_table = next(element.value for element in app.dataframe
                      if "worst_daily_net_return" in element.value.columns)
    included_dates = {row["execution_date"] for row in records}
    included_points = [point for point in state.archive.points if point.execution_date in included_dates]
    assert risk_table.iloc[0]["net_total_return"] == pytest.approx(records[-1]["net_wealth"] - 1)
    assert risk_table.iloc[0]["max_drawdown"] == pytest.approx(min(row["drawdown"] for row in records))
    assert risk_table.iloc[0]["worst_daily_net_return"] == pytest.approx(min(point.net_return for point in included_points))
    assert all(count == len(records) for count in risk_table["observations"])
    assert len(risk_table) == (1 if state.mode == "reference_failure" else 2)
    if "rolling" in _charts(app):
        rolling = _charts(app)["rolling"][1]
        assert len(rolling) == len(records) - 62
        assert all(row["end_date"] <= expected_execution and row["observations"] == 63 for row in rolling)
        assert rolling[0]["start_date"] == records[0]["execution_date"]
        assert rolling[-1]["end_date"] == expected_execution


def test_research_cutoff_language_and_controls_preserve_serialized_returns(research_app):
    state, app = research_app, research_app.app
    assert not state.calls
    app.radio(key="workspace").set_value("Research").run()
    _assert_cutoff(state, "2025-12-02")
    charts = _charts(app)
    assert charts["wealth"][1][0]["net_wealth"] == pytest.approx(0.99)
    assert next(row for row in charts["month"][1] if row["period"] == "2024-12")["net_return"] == pytest.approx(-0.01)
    assert next(row for row in charts["year"][1]
                if row["period"] == "2024" and row["series"] == "Raw A2")["return"] == pytest.approx(-0.01)

    # Use non-default controls while retaining the first cost-bearing observation.
    app.selectbox(key="research_range").select("252 execution days").run()
    app.toggle(key="research_reference").set_value(False).run()
    app.toggle(key="research_gross").set_value(True).run()
    app.button(key="previous_date").click().run()
    _assert_cutoff(state, "2025-12-01")
    before = _economic_payload(app)
    ledger = _period_table(app)
    periods, returns = ledger["Period"].tolist(), ledger["Net return"].tolist()
    for language in ("zh", "ja", "en"):
        app.selectbox(key="language").select(language).run()
        _assert_cutoff(state, "2025-12-01")
        assert app.radio(key="workspace").value == "Research"
        assert app.toggle(key="presentation_mode").value is True
        assert app.selectbox(key="research_range").value == "252 execution days"
        assert app.selectbox(key="research_range").label == _label("Research window", language)
        assert app.selectbox(key="research_range").proto.set_value
        assert app.selectbox(key="research_range").proto.raw_value == _label("252 execution days", language)
        assert app.toggle(key="research_reference").value is False
        assert app.toggle(key="research_gross").value is True
        assert app.toggle(key="research_gross").label == _label("Show gross path", language)
        assert _economic_payload(app) == before
        # Endpoint labels reuse the same folded fields as the path layer.
        assert {tuple(fields) for fields in _folds(_charts(app)["wealth"][0])} == {("net_wealth", "gross_wealth")}
        assert {row["series"] for row in _charts(app)["year"][1]} == {"Raw A2"}
        table = _period_table(app, language)
        assert table[_label("Period", language)].tolist() == periods
        assert table[_label("Net return", language)].tolist() == returns
        content = _content(app)
        assert _label(_INDEPENDENCE_NOTE, language) in content
        assert _label("No Sharpe ratio, alpha, confidence interval, DSR, PBO or probability of skill is inferred from these observations.", language) in content
        assert all(secret not in content for secret in (_PATH, _HASH, _DEBUG))

    app.selectbox(key="research_range").select("63 execution days").run()
    assert len(_charts(app)["wealth"][1]) == 63
    assert _charts(app)["wealth"][1][0]["execution_date"] != "2024-12-31"
    app.button(key="next_date").click().run()
    _assert_cutoff(state, "2025-12-02")
    assert app.selectbox(key="research_range").value == "63 execution days"


def test_reference_failure_preserves_a2_and_full_provenance_is_opt_in(research_app):
    state, app = research_app, research_app.app
    state.mode = "reference_failure"
    app.radio(key="workspace").set_value("Research").run()
    _assert_cutoff(state, "2025-12-02")
    assert _REFERENCE_ERROR in _content(app)
    assert all(row["reference_net_wealth"] is None for row in _charts(app)["wealth"][1])
    assert {row["series"] for row in _charts(app)["year"][1]} == {"Raw A2"}
    assert all(value == "N/A" for value in _period_table(app)["Frozen A control"])
    before = _economic_payload(app)
    assert all(secret not in _content(app) for secret in (_PATH, _HASH, _DEBUG, _REFERENCE_DEBUG))
    assert _HASH[:12] in _content(app), "Presentation mode may show shortened artifact identity"

    app.toggle(key="presentation_mode").set_value(False).run()
    _assert_cutoff(state, "2025-12-02")
    assert all(secret in _content(app) for secret in (_PATH, _HASH, _DEBUG))
    assert _economic_payload(app) == before
    app.toggle(key="presentation_mode").set_value(True).run()
    assert all(secret not in _content(app) for secret in (_PATH, _HASH, _DEBUG, _REFERENCE_DEBUG))


def test_rolling_table_matches_chart_for_windows_languages_and_short_history(research_app):
    state, app = research_app, research_app.app
    fields = ("start_date", "end_date", "observations", "net_return", "reference_net_return")

    def rolling_table():
        return next(element for element in app.dataframe if tuple(element.value.columns) == fields)

    def assert_consistent():
        assert not app.exception and not app.error
        rows = _charts(app)["rolling"][1]
        expected = [{field: row[field] for field in fields} for row in rows]
        assert rolling_table().value.to_dict("records") == expected
        assert all(row["observations"] == 63 and row["end_date"] <= "2025-12-03" for row in expected)
        return rolling_table().value.copy(deep=True)

    app.radio(key="workspace").set_value("Research").run()
    full = assert_consistent()
    assert len(full) > 1
    app.selectbox(key="research_range").select("63 execution days").run()
    single = assert_consistent()
    assert len(single) == 1
    pd.testing.assert_frame_equal(single.reset_index(drop=True), full.tail(1).reset_index(drop=True))
    for language in ("zh", "ja", "en"):
        app.selectbox(key="language").select(language).run()
        pd.testing.assert_frame_equal(assert_consistent(), single)
        config = json.loads(rolling_table().proto.columns)
        for field, source in zip(fields, ("Window start date", "Window end date",
                                          "Recorded execution days", "Raw A2 · Net", "Frozen A control · Net")):
            assert config[field]["label"] == _label(source, language)
        panel = next(expander for expander in app.expander
                     if expander.label == _label("Inspect fixed 63-day windows", language))
        assert panel.proto.expanded is False
        assert len(panel.dataframe) == 1

    app.selectbox(key="research_range").select("All days through selected execution").run()
    pd.testing.assert_frame_equal(assert_consistent(), full)
    app.toggle(key="research_reference").set_value(False).run()
    pd.testing.assert_frame_equal(assert_consistent(), full)
    assert json.loads(rolling_table().proto.columns)["reference_net_return"]["hidden"] is True
    assert list(_folds(_charts(app)["rolling"][0])) == [["net_return"]]
    app.toggle(key="research_reference").set_value(True).run()
    pd.testing.assert_frame_equal(assert_consistent(), full)
    assert not json.loads(rolling_table().proto.columns)["reference_net_return"].get("hidden", False)
    state.mode = "reference_failure"
    app.run()
    missing = assert_consistent()
    assert missing["reference_net_return"].isna().all()
    pd.testing.assert_series_equal(missing["net_return"], full["net_return"])
    assert json.loads(rolling_table().proto.columns)["reference_net_return"]["hidden"] is True
    assert list(_folds(_charts(app)["rolling"][0])) == [["net_return"]]
    state.mode = "short_history"
    app.run()
    assert not app.exception and not app.error
    assert "rolling" not in _charts(app)
    assert not any(tuple(element.value.columns) == fields for element in app.dataframe)
    assert any("Fewer than 63 execution records" in element.value for element in app.info)


def test_a2_failure_has_safe_localized_body_no_results_and_recovers(research_app):
    state, app = research_app, research_app.app
    state.mode = "a2_failure"
    app.radio(key="workspace").set_value("Research").run()
    assert not app.exception
    assert any(element.value == _ERROR for element in app.error)
    assert not app.get("vega_lite_chart")
    assert not any("Period" in element.value.columns for element in app.dataframe)
    assert all(secret not in _content(app) for secret in (_PATH, _HASH, _DEBUG))

    app.selectbox(key="language").select("zh").run()
    assert not app.exception
    assert any(element.value == _label(_ERROR, "zh") for element in app.error)
    assert not app.get("vega_lite_chart")
    assert all(secret not in _content(app) for secret in (_PATH, _HASH, _DEBUG))
    app.toggle(key="presentation_mode").set_value(False).run()
    assert not app.exception and not app.get("vega_lite_chart")
    assert all(secret in _content(app) for secret in (_PATH, _HASH, _DEBUG))
    app.toggle(key="presentation_mode").set_value(True).run()
    state.mode = "normal"
    app.run()
    _assert_cutoff(state, "2025-12-02")
    assert app.selectbox(key="language").value == "zh"
    assert _period_table(app, "zh") is not None
    assert all(secret not in _content(app) for secret in (_PATH, _HASH, _DEBUG))


def test_drawdown_episode_selection_preserves_window_coordinates_and_repairs_removed_episode(research_app):
    from apps.demo_console.tests.test_localized_tabs import _switch_tab

    state, app = research_app, research_app.app

    def ledger():
        return next(element.value for element in app.dataframe
                    if "first_underwater_date" in element.value.columns)

    def economic_ledger():
        return ledger().drop(columns=["peak_date", "status"]).to_dict("records")

    def assert_episode_matches_selection():
        _assert_cutoff(state, app.selectbox(key="decision_date").value)
        selected = app.selectbox(key="research_drawdown_episode").value
        entry = next(row for row in ledger().to_dict("records")
                     if row["first_underwater_date"] == selected)
        _, points = _charts(app)["episode"]
        full = _charts(app)["wealth"][1]
        full_dates = {row["execution_date"] for row in full}
        start = entry["peak_date"] if entry["peak_date"] in full_dates else full[0]["execution_date"]
        expected = [{"execution_date": row["execution_date"], "drawdown": row["drawdown"]}
                    for row in full if start <= row["execution_date"] <= entry["end_date"]]
        assert points == expected
        assert min(row["drawdown"] for row in points) == pytest.approx(entry["depth"])
        assert points[-1]["execution_date"] == entry["end_date"]
        assert app.selectbox(key="research_range").value in (
            "All days through selected execution", "63 execution days")
        assert all(secret not in _content(app) for secret in (_PATH, _HASH, _DEBUG))
        return points

    app.radio(key="workspace").set_value("Research").run()
    assert app.selectbox(key="research_drawdown_episode").value == ledger().iloc[-1]["first_underwater_date"]
    first = ledger().iloc[0]["first_underwater_date"]
    assert first == "2024-12-31"
    _switch_tab(app, "Drawdown & recovery")
    app.selectbox(key="research_drawdown_episode").select(first).run()
    before = assert_episode_matches_selection()
    assert before[0] == {"execution_date": first, "drawdown": pytest.approx(-.01)}
    original_ledger = economic_ledger()
    for language in ("zh", "ja", "en"):
        app.selectbox(key="language").select(language).run()
        assert app.session_state["_localized_tabs:research_tabs"] == "Drawdown & recovery"
        assert app.get("tab_container")[0].proto.tab_container.default_tab_index == 1
        assert app.selectbox(key="research_drawdown_episode").value == first
        assert app.selectbox(key="research_drawdown_episode").label == _label("Drawdown episode to inspect", language)
        assert assert_episode_matches_selection() == before
        assert economic_ledger() == original_ledger
        assert app.selectbox(key="decision_date").value == "2025-12-02"

    app.selectbox(key="research_range").select("63 execution days").run()
    assert first not in set(ledger()["first_underwater_date"])
    assert app.selectbox(key="research_drawdown_episode").value == ledger().iloc[-1]["first_underwater_date"]
    assert_episode_matches_selection()
    app.button(key="previous_date").click().run()
    assert app.selectbox(key="decision_date").value == "2025-12-01"
    assert_episode_matches_selection()
    app.button(key="next_date").click().run()
    assert app.selectbox(key="decision_date").value == "2025-12-02"
    assert_episode_matches_selection()


def test_custom_calendar_range_controls_all_paths_and_uses_previous_actual_execution(research_app):
    from datetime import date
    from apps.demo_console.components.performance_stats import summarize_performance

    state, app = research_app, research_app.app
    app.radio(key="workspace").set_value("Research").run()
    app.selectbox(key="research_range").select("63 execution days").run()
    selected = (date(2025, 9, 1), date(2025, 10, 15))
    app.date_input(key="research_dates_draft").set_value(selected)
    app.button(key="research_dates_apply").click().run()
    expected = tuple(point for point in state.archive.points
                     if "2025-09-01" <= point.execution_date <= "2025-10-15")
    expected_dates = tuple(point.execution_date for point in expected)
    first_index = state.archive.points.index(expected[0])
    baseline = state.archive.points[first_index - 1].execution_date
    summary = summarize_performance(expected, initial_wealth=state.archive.initial_nav,
                                    full_history_dates=state.archive.available_dates)
    for language in ("en", "zh", "ja"):
        app.selectbox(key="language").select(language).run()
        assert not app.exception and not app.error
        assert app.session_state["decision_date"] == "2025-12-02"
        assert state.calls[-1] == "2025-12-03"
        assert state.benchmarks.calls[-1] == (expected_dates, baseline)
        charts = _charts(app)
        assert charts["wealth"][1] == [asdict(point) for point in summary.wealth]
        assert tuple(row["execution_date"] for row in charts["execution"][1]) == expected_dates
        assert {row["execution_date"] for row in charts["month_detail"][1]} <= set(expected_dates)
        assert sum(row["observations"] for row in charts["month"][1]) == len(expected)
        assert sum(row["observations"] for row in charts["year"][1] if row["series"] == "Raw A2") == len(expected)
        table = next(item.value for item in app.dataframe if "worst_daily_net_return" in item.value.columns)
        assert all(table["observations"] == len(expected))
        assert table.iloc[0]["net_total_return"] == pytest.approx(summary.net_total_return)
        assert app.date_input(key="research_dates_draft").value == selected
        assert _label("CUSTOM DATE RANGE", language) in _content(app)
    # A submitted half-range leaves the previously applied economic window intact.
    before = _economic_payload(app)
    app.date_input(key="research_dates_draft").set_value((date(2025, 9, 12),))
    app.button(key="research_dates_apply").click().run()
    assert not app.exception and _economic_payload(app) == before
    # Choosing a preset deliberately clears custom dates, including the draft.
    app.selectbox(key="research_range").select("126 execution days").run()
    _assert_cutoff(state, "2025-12-02")
    assert len(_charts(app)["wealth"][1]) == len(state.archive.points) - 1


def test_custom_range_cutoff_clips_visible_end_and_empty_interval_clears_results(research_app):
    from datetime import date

    state, app = research_app, research_app.app
    app.radio(key="workspace").set_value("Research").run()
    app.date_input(key="research_dates_draft").set_value((date(2025, 11, 28), date(2025, 12, 3)))
    app.button(key="research_dates_apply").click().run()
    app.button(key="previous_date").click().run()
    assert not app.exception and app.session_state["decision_date"] == "2025-12-01"
    assert app.date_input(key="research_dates_draft").value == (date(2025, 11, 28), date(2025, 12, 2))
    assert "The applied range was adjusted to the available dates." in _content(app)
    expected_dates = tuple(point.execution_date for point in state.archive.points
                           if "2025-11-28" <= point.execution_date <= "2025-12-02")
    prior = max(point.execution_date for point in state.archive.points if point.execution_date < expected_dates[0])
    assert state.benchmarks.calls[-1] == (expected_dates, prior)
    assert tuple(row["execution_date"] for row in _charts(app)["wealth"][1]) == expected_dates
    assert all(row["execution_date"] <= "2025-12-02" for row in _charts(app)["execution"][1])
    assert state.calls[-1] == "2025-12-02"
    # A calendar gap has no fabricated return or retained chart from the old range.
    calls = list(state.benchmarks.calls)
    app.date_input(key="research_dates_draft").set_value((date(2025, 1, 10), date(2025, 1, 11)))
    app.button(key="research_dates_apply").click().run()
    assert not app.exception and not app.error
    assert not app.get("vega_lite_chart")
    # Global decision provenance remains available; performance outputs do not.
    assert all(set(item.value.columns) == {"Field", "Value"} for item in app.dataframe)
    assert not any('class="uq-metrics ' in item.proto.body for item in app.get("html"))
    assert "No recorded execution observations fall within 2025-01-10 → 2025-01-11" in _content(app)
    assert state.benchmarks.calls == calls
    assert app.session_state["decision_date"] == "2025-12-01"
    app.button(key="research_dates_reset").click().run()
    _assert_cutoff(state, "2025-12-01")
