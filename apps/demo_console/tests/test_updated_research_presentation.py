"""Updated performance UI over synthetic ledgers; no market or artifact reads."""
import json


def _updated_page():
    from dataclasses import replace
    from unittest.mock import patch
    import streamlit as st
    from apps.demo_console.adapters import workspace_reader
    from apps.demo_console.adapters.benchmarks_reader import BenchmarkHistory
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.models import DecisionOverview
    from apps.demo_console.pages import research
    from apps.demo_console.tests.test_research_view import _synthetic_archive

    st.session_state.setdefault("workspace_source", workspace_reader.LATEST)
    st.session_state.setdefault("_workspace_source_seen", workspace_reader.LATEST)
    st.session_state.setdefault("decision_date", "2025-12-03")
    st.session_state.setdefault("_source_date:frozen", "2025-06-03")
    archive = _synthetic_archive()
    points = tuple(replace(point, reference_nav=None, reference_net_return=None,
                           reference_gross_return=None, reference_transaction_cost=None)
                   for point in archive.points if point.execution_date <= "2025-12-03")
    history = replace(archive, points=points, reference_available=False, reference_identity=None)
    model = DecisionOverview(decision_date="2025-12-03", source_id=workspace_reader.LATEST,
                             performance_cutoff_date="2025-12-03", execution_status="PENDING_NEXT_OPEN")
    def forbidden(*args, **kwargs):
        raise AssertionError("Updated presentation must not fetch a frozen strategy or ETF comparison")
    with language_scope("en"), patch.object(workspace_reader, "read_performance", return_value=history), \
            patch.object(research, "read_performance", forbidden), patch.object(research, "read_benchmarks", forbidden), \
            patch.object(research, "read_updated_benchmarks", return_value=BenchmarkHistory()), \
            patch.object(research, "_historical_comparisons") as reference:
        research.render_research(model, presentation=True)
        assert reference.call_args.args == (points[0].execution_date if st.session_state.get("research_range") != "63 execution days" else points[-63].execution_date, points[-1].execution_date)


def _cards(app):
    return next(item.proto.body for item in app.get("html") if 'class="uq-metrics uq-motion-enter"' in item.proto.body)


def test_updated_metrics_use_real_summary_and_keep_all_analytical_views():
    from streamlit.testing.v1 import AppTest
    from apps.demo_console.tests.test_research_view import _charts
    app = AppTest.from_function(_updated_page, default_timeout=30).run()
    assert not app.exception and not app.error
    cards = _cards(app)
    assert cards.count('class="uq-metric"') == 4 and "N/A" not in cards
    for label in ("Net cumulative return", "Maximum window drawdown", "Worst daily net return", "Gross–net return gap"):
        assert label in cards
    assert "A control period return" not in cards and "A2 − A return difference" not in cards
    assert [tab.label for tab in app.tabs] == ["Performance path", "Drawdown & recovery",
        "Consistency & concentration", "Evidence & method", "Execution frictions"]
    assert "research_reference" not in {toggle.key for toggle in app.toggle}
    assert "research_curve_focus" not in {control.key for control in app.get("button_group")}
    charts = _charts(app)
    assert {"wealth", "month", "year", "distribution", "rolling", "execution", "episode"} <= set(charts)
    assert max(row["execution_date"] for row in charts["wealth"][1]) == "2025-12-03"
    assert all(row.get("reference_net_wealth") is None for row in charts["wealth"][1])
    months = next(table for table in app.dataframe if "Period" in table.value.columns)
    assert "Frozen A control" not in months.value.columns
    daily = next(table for table in app.dataframe if "reference_net_return" in table.value.columns
                 and "gross_return" in table.value.columns)
    assert json.loads(daily.proto.columns)["reference_net_return"]["hidden"] is True
    original = charts["execution"][1]
    app.selectbox(key="research_range").select("63 execution days").run()
    assert not app.exception and not app.error
    assert _charts(app)["execution"][1] == original[-63:]
    app.toggle(key="research_gross").set_value(True).run()
    assert not app.exception and not app.error
    wealth = _charts(app)["wealth"]
    assert "gross_wealth" in json.dumps(wealth[0])
    assert all(row.get("reference_net_wealth") is None for row in wealth[1])


def _reference_page():
    from types import SimpleNamespace
    from dataclasses import replace
    from unittest.mock import patch
    import streamlit as st
    from apps.demo_console.pages import research
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.adapters.benchmarks_reader import BenchmarkHistory, BenchmarkSeries, BenchmarkPoint
    from apps.demo_console.tests.test_research_view import _synthetic_archive
    archive = _synthetic_archive()
    st.session_state.setdefault("decision_date", "2026-09-22")
    st.session_state.setdefault("workspace_source", "A2_UPDATED_RESEARCH")
    if st.session_state.get("without_a"):
        archive = replace(archive, points=tuple(replace(point, reference_nav=None, reference_net_return=None,
            reference_gross_return=None, reference_transaction_cost=None) for point in archive.points),
            reference_available=False, reference_identity=None)
    start = st.session_state.get("reference_start", "2025-11-03")
    end = st.session_state.get("reference_end", "2026-09-22")
    config = SimpleNamespace(artifacts=tuple(SimpleNamespace(symbol=symbol, window="historical",
        start_date="2023-01-04", end_date=st.session_state.get("etf_end", "2025-12-30"))
        for symbol in ("QQQ", "SPY")))
    def market(dates, *, baseline_date, config):
        st.session_state["queried_dates"] = dates
        st.session_state["queried_baseline"] = baseline_date
        if st.session_state.get("with_etf"):
            values = tuple(BenchmarkPoint(day, 100.0, 0.0, 1.0, 0.0) for day in dates)
            return BenchmarkHistory(series=(BenchmarkSeries("QQQ", "QQQ", points=values,
                total_return=0.0, max_drawdown=0.0), BenchmarkSeries("SPY", "SPY", error="MISSING_DATES")),
                baseline_date=baseline_date)
        return BenchmarkHistory()
    with language_scope("en"), patch.object(research, "read_performance", return_value=archive) as reader, \
            patch.object(research, "read_benchmarks", side_effect=market), \
            patch.object(research, "default_benchmarks_config", return_value=config):
        research._historical_comparisons(start, end, presentation=True)
        st.session_state["frozen_reader_calls"] = reader.call_args_list


def test_historical_comparison_is_inline_bounded_and_does_not_change_workspace():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_reference_page, default_timeout=30).run()
    assert not app.exception and not app.error
    assert app.session_state["workspace_source"] == "A2_UPDATED_RESEARCH"
    assert app.session_state["decision_date"] == "2026-09-22"
    assert app.session_state["frozen_reader_calls"][0].args == ("2025-12-30",)
    dates = app.session_state["queried_dates"]
    assert min(dates) >= "2025-11-03" and max(dates) <= "2025-12-30"
    assert app.session_state["queried_baseline"] < min(dates)
    assert len(app.get("vega_lite_chart")) == 1
    assert "research_open_historical_comparisons" not in {button.key for button in app.button}
    assert any("Shared reference coverage:" in caption.value for caption in app.caption)
    table = app.dataframe[0].value
    assert len(table) == 2 and set(table["Recorded execution days"]) == {len(dates)}


def test_historical_comparison_respects_earlier_selected_end():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_reference_page, default_timeout=30)
    app.session_state["reference_end"] = "2025-11-10"
    app.run()
    assert not app.exception and not app.error
    assert max(app.session_state["queried_dates"]) <= "2025-11-10"
    assert app.session_state["frozen_reader_calls"][0].args == ("2025-11-10",)


def test_2026_only_window_has_no_frozen_overlap_and_does_not_read_archive():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_reference_page, default_timeout=30)
    app.session_state["reference_start"] = "2026-01-02"
    app.run()
    assert not app.exception and not app.error
    assert not app.session_state["frozen_reader_calls"]
    assert not app.get("vega_lite_chart")
    assert any("No frozen comparison observations overlap" in row.value for row in app.info)


def _frozen_cards():
    from apps.demo_console.pages.research import _readout
    from apps.demo_console.components.performance_stats import summarize_performance
    from apps.demo_console.tests.test_research_view import _synthetic_archive
    from apps.demo_console.i18n import language_scope
    archive = _synthetic_archive()
    with language_scope("en"):
        _readout(summarize_performance(archive.points[:3], full_history_dates=archive.available_dates))


def test_original_frozen_comparison_cards_remain_available():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_frozen_cards, default_timeout=20).run()
    assert not app.exception
    cards = _cards(app)
    assert "A control period return" in cards and "A2 − A return difference" in cards
    assert "Worst daily net return" not in cards and "N/A" not in cards


def test_inline_reference_keeps_complete_etf_and_excludes_missing_etf():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_reference_page, default_timeout=30)
    app.session_state["with_etf"] = True
    app.run()
    assert not app.exception and not app.error
    names = set(app.dataframe[0].value["Portfolio / control"])
    assert "QQQ" in names and "SPY · S&P 500" not in names
    assert len(names) == 3
    assert any("SPY" in row.value and "Market reference unavailable" in row.value for row in app.caption)


def test_reference_without_a_or_etf_does_not_render_single_choice_selector():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_reference_page, default_timeout=30)
    app.session_state["without_a"] = True
    app.run()
    assert not app.exception and not app.error
    assert "research_historical_curve_focus" not in {widget.key for widget in app.get("button_group")}
    assert len(app.dataframe[0].value) == 1


def test_shared_reference_window_uses_both_etf_binding_boundaries():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_reference_page, default_timeout=30)
    app.session_state["reference_start"] = "2023-01-01"
    app.session_state["with_etf"] = True
    app.session_state["etf_end"] = "2025-11-20"
    app.run()
    assert not app.exception and not app.error
    dates = app.session_state["queried_dates"]
    assert min(dates) >= "2023-01-04" and max(dates) <= "2025-11-20"
    assert any("keeps its full selected period" in item.value for item in app.caption)


def _calendar_controls_page():
    from types import SimpleNamespace
    import streamlit as st
    from apps.demo_console.pages.research import _select_research_points, _RANGES
    from apps.demo_console.components.performance_range import reset_date_range
    from apps.demo_console.i18n import language_scope
    dates = ("2024-12-31", "2025-01-02", "2025-02-28", "2025-03-31", "2025-04-01",
             "2025-12-31", "2026-01-02", "2026-03-31", "2026-04-01", "2026-09-22")
    sample = st.session_state.get("sample", "historical")
    dates = tuple(day for day in dates if (day < "2026-01-01") == (sample == "historical"))
    history = SimpleNamespace(points=tuple(SimpleNamespace(execution_date=day) for day in dates))
    with language_scope("en"):
        mode = st.selectbox("Window", list(_RANGES), key="research_range",
                            on_change=reset_date_range, args=("research_dates",))
        points, custom, bounds = _select_research_points(history, dates[-1], mode)
        st.session_state["selected_dates"] = tuple(point.execution_date for point in points)
        st.session_state["calendar_bounds"] = bounds


def test_exact_calendar_boundaries_include_leap_month_and_year_end():
    from apps.demo_console.pages.research import _calendar_window
    assert _calendar_window("2024-02") == ("2024-02-01", "2024-02-29")
    assert _calendar_window("2025-12") == ("2025-12-01", "2025-12-31")
    assert _calendar_window("2025-Q4", quarter=True) == ("2025-10-01", "2025-12-31")
    assert _calendar_window("2026-Q1", quarter=True) == ("2026-01-01", "2026-03-31")


def test_month_and_quarter_use_calendar_intersections_in_each_sample():
    from streamlit.testing.v1 import AppTest
    for sample, month, month_dates, quarter, quarter_dates in (
        ("historical", "2024-12", ("2024-12-31",), "2025-Q1", ("2025-01-02", "2025-02-28", "2025-03-31")),
        ("test_2026", "2026-01", ("2026-01-02",), "2026-Q1", ("2026-01-02", "2026-03-31")),
    ):
        app = AppTest.from_function(_calendar_controls_page, default_timeout=30)
        app.session_state["sample"] = sample
        app.run()
        app.selectbox(key="research_range").select("Calendar month").run()
        app.selectbox(key="research_calendar_month").select(month).run()
        assert not app.exception
        assert app.session_state["selected_dates"] == month_dates
        app.selectbox(key="research_range").select("Calendar quarter").run()
        app.selectbox(key="research_calendar_quarter").select(quarter).run()
        assert not app.exception
        assert app.session_state["selected_dates"] == quarter_dates


def test_custom_range_intersects_only_actual_records_without_crossing_sample():
    from datetime import date
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_calendar_controls_page, default_timeout=30)
    app.session_state["sample"] = "test_2026"
    app.run()
    app.selectbox(key="research_range").select("Custom dates").run()
    app.date_input(key="research_dates_draft").set_value((date(2026, 2, 1), date(2026, 4, 1)))
    app.button(key="research_dates_apply").click().run()
    assert not app.exception
    assert app.session_state["selected_dates"] == ("2026-03-31", "2026-04-01")


def _updated_2026_benchmarks_page():
    from dataclasses import replace
    from unittest.mock import patch
    import streamlit as st
    from apps.demo_console.adapters import workspace_reader
    from apps.demo_console.adapters.benchmarks_reader import BenchmarkHistory, BenchmarkSeries, BenchmarkPoint
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.models import DecisionOverview
    from apps.demo_console.pages import research
    from apps.demo_console.tests.test_research_view import _synthetic_archive
    archive = _synthetic_archive()
    dates = ("2026-01-02", "2026-01-05", "2026-03-31", "2026-04-01", "2026-09-22")
    points = tuple(replace(point, execution_date=day, reference_nav=None, reference_net_return=None,
        reference_gross_return=None, reference_transaction_cost=None) for point, day in zip(archive.points, dates))
    history = replace(archive, points=points, available_dates=dates, baseline_date="2025-12-31",
                      reference_available=False, reference_identity=None)
    model = DecisionOverview(decision_date="2026-09-22", source_id=workspace_reader.LATEST,
                             performance_cutoff_date="2026-09-22", execution_status="PENDING_NEXT_OPEN")
    def benchmark(dates, baseline_date=None):
        st.session_state["benchmark_dates"] = dates
        st.session_state["benchmark_baseline"] = baseline_date
        values = tuple(BenchmarkPoint(day, 100.0+i, 0.01, 1.01**(i+1), 0.0) for i, day in enumerate(dates))
        return BenchmarkHistory(series=tuple(BenchmarkSeries(symbol, symbol, adjustment="RAW",
            basis="OPEN_TO_OPEN_PRICE_RETURN", points=values, total_return=values[-1].equity-1,
            max_drawdown=0.0) for symbol in ("QQQ", "SPY")), baseline_date=baseline_date)
    with language_scope("en"), patch.object(workspace_reader, "read_performance", return_value=history), \
            patch.object(research, "read_updated_benchmarks", side_effect=benchmark), \
            patch.object(research, "read_performance", side_effect=AssertionError("No old archive in 2026 sample")):
        research.render_research(model, presentation=True)


def _primary_wealth_records(app):
    import pyarrow as pa
    for element in app.get("vega_lite_chart"):
        payloads = [element.proto.data.data, *(dataset.data.data for dataset in element.proto.datasets)]
        records = [row for payload in payloads if payload for row in pa.ipc.open_stream(payload).read_all().to_pylist()]
        if records and "net_wealth" in records[0]:
            return records
    raise AssertionError("Missing primary wealth chart")


def test_2026_primary_benchmarks_follow_sample_month_quarter_and_custom_dates():
    from datetime import date
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_updated_2026_benchmarks_page, default_timeout=30).run()
    assert not app.exception and not app.error
    assert app.session_state["benchmark_baseline"] == "2025-12-31"
    assert all(day.startswith("2026-") for day in app.session_state["benchmark_dates"])
    assert any("excluding cash dividends" in item.value for item in app.caption)
    assert any("QQQ / SPY price references" in item.proto.body for item in app.get("html"))
    def check(expected, baseline):
        assert not app.exception and not app.error
        assert app.session_state["benchmark_dates"] == expected
        assert app.session_state["benchmark_baseline"] == baseline
        records = _primary_wealth_records(app)
        assert tuple(row["execution_date"] for row in records) == expected
        assert all(row["benchmark_qqq"] is not None and row["benchmark_spy"] is not None for row in records)
        assert all(row.get("reference_net_wealth") is None for row in records)
        table = next(item.value for item in app.dataframe if "series" in item.value.columns)
        assert set(table["series"]) == {"Raw A2", "QQQ", "SPY · S&P 500"}
        assert set(table["observations"]) == {len(expected)}
    app.selectbox(key="research_range").select("Calendar month").run()
    app.selectbox(key="research_calendar_month").select("2026-01").run()
    check(("2026-01-02", "2026-01-05"), "2025-12-31")
    app.selectbox(key="research_range").select("Calendar quarter").run()
    app.selectbox(key="research_calendar_quarter").select("2026-Q1").run()
    check(("2026-01-02", "2026-01-05", "2026-03-31"), "2025-12-31")
    app.selectbox(key="research_range").select("Custom dates").run()
    app.date_input(key="research_dates_draft").set_value((date(2026, 3, 1), date(2026, 4, 1)))
    app.button(key="research_dates_apply").click().run()
    check(("2026-03-31", "2026-04-01"), "2026-01-05")
    assert "research_curve_focus" in {item.key for item in app.get("button_group")}


def test_single_execution_day_keeps_strategy_and_etf_return_baseline():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_updated_2026_benchmarks_page, default_timeout=30).run()
    app.selectbox(key="research_range").select("Single date").run()
    app.selectbox(key="research_single_date").select("2026-03-31").run()
    assert not app.exception and not app.error
    assert app.session_state["benchmark_dates"] == ("2026-03-31",)
    assert app.session_state["benchmark_baseline"] == "2026-01-05"
    records = _primary_wealth_records(app)
    assert len(records) == 1 and records[0]["benchmark_qqq"] is not None and records[0]["benchmark_spy"] is not None


def test_random_period_is_stable_until_reroll_and_revalidates_sample_bounds():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_calendar_controls_page, default_timeout=30).run()
    app.selectbox(key="research_range").select("Random period").run()
    original = app.session_state["selected_dates"]
    assert len(original) >= 2 and all(day < "2026-01-01" for day in original)
    app.run()
    assert app.session_state["selected_dates"] == original
    app.button(key="research_random_reroll").click().run()
    assert not app.exception
    assert app.session_state["selected_dates"] != original
    app.session_state["sample"] = "test_2026"
    app.run()
    changed = app.session_state["selected_dates"]
    assert len(changed) >= 2 and all("2026-01-01" <= day <= "2026-09-22" for day in changed)
    app.run()
    assert app.session_state["selected_dates"] == changed


def test_single_date_is_revalidated_when_sample_changes():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_calendar_controls_page, default_timeout=30).run()
    app.selectbox(key="research_range").select("Single date").run()
    app.selectbox(key="research_single_date").select("2024-12-31").run()
    assert app.session_state["selected_dates"] == ("2024-12-31",)
    app.session_state["sample"] = "test_2026"
    app.run()
    assert not app.exception
    assert app.session_state["selected_dates"] == ("2026-09-22",)


def test_random_window_handles_one_or_two_observations_without_inventing_dates():
    from apps.demo_console.pages.research import _random_window
    assert _random_window(("2026-01-02",)) == ("2026-01-02", "2026-01-02")
    assert _random_window(("2026-01-02", "2026-01-05")) == ("2026-01-02", "2026-01-05")
