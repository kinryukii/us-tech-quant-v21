"""ETF additions use synthetic aligned dates and never replace strategy records."""
from dataclasses import asdict, replace
import json

import pyarrow as pa
import pytest
from streamlit.testing.v1 import AppTest

from apps.demo_console.adapters.benchmarks_reader import BenchmarkHistory, BenchmarkPoint, BenchmarkSeries
from apps.demo_console.components.market_benchmarks import benchmark_label
from apps.demo_console.components.performance_charts import wealth_chart
from apps.demo_console.components.performance_stats import summarize_performance
from apps.demo_console.i18n import language_scope, tr
from apps.demo_console.tests.test_performance_charts import _rolling_points, _records, _folded_fields
from apps.demo_console.tests.test_recorded_2026_view import (
    recorded_app, recorded_stub, _enter_recorded, _control, _path_rows, _expected_rows, _assert_recorded_isolation,
)
from apps.demo_console.tests.test_machine_learning_view import learning_app
from apps.demo_console.tests.test_terminal_interactions import _content


def _markets(dates, baseline_date=None, *, missing_spy=False):
    """Build independent, deliberately different ETF values on the supplied dates."""
    series = []
    for symbol, factor in (("QQQ", 1.002), ("SPY", .997)):
        if symbol == "SPY" and missing_spy:
            series.append(BenchmarkSeries(symbol, benchmark_label(symbol), error="Synthetic SPY date is missing"))
            continue
        points, equity, peak = [], 1.0, 1.0
        for index, day in enumerate(dates):
            change = factor - 1 if baseline_date is not None or index else 0.0
            equity *= 1 + change
            peak = max(peak, equity)
            points.append(BenchmarkPoint(day, 100 * equity, change, equity, equity / peak - 1))
        series.append(BenchmarkSeries(symbol, benchmark_label(symbol), points=tuple(points),
            total_return=equity - 1, max_drawdown=min(point.drawdown for point in points),
            source_refs=((f"C:/synthetic-private/benchmarks/{symbol}.parquet", "cb" * 32),)))
    return BenchmarkHistory(tuple(series), dates[0], dates[-1], baseline_date)


def _strategy_rows(rows):
    return [{key: value for key, value in row.items() if not key.startswith("benchmark_")} for row in rows]


def _payload(chart):
    payloads = [chart.proto.data.data, *(item.data.data for item in chart.proto.datasets)]
    return [row for payload in payloads if payload
            for row in pa.ipc.open_stream(payload).read_all().to_pylist()]


def _wealth_payload(app):
    for chart in app.get("vega_lite_chart"):
        rows = _payload(chart)
        if rows and "net_wealth" in rows[0] and json.loads(chart.proto.spec).get("name") != "research_month_detail_chart":
            return json.loads(chart.proto.spec), rows
    raise AssertionError("The main wealth chart was not rendered")


def _comparison(app, *, recorded=False):
    # Non-interactive dataframes do not expose their user key in AppTest 1.63.
    fields = (("series", "return", "drawdown", "worst", "best") if recorded else
              ("series", "net_total_return", "max_drawdown", "worst_daily_net_return", "observations"))
    matches = [table.value for table in app.dataframe if tuple(table.value.columns) == fields]
    assert len(matches) == 1
    return matches[0]


def test_aligned_etf_lines_add_only_their_own_fields_and_reject_incomplete_alignment():
    summary = summarize_performance(_rolling_points(5))
    original = asdict(summary)
    dates = tuple(point.execution_date for point in summary.wealth)
    markets = _markets(dates)
    for language in ("en", "zh", "ja"):
        with language_scope(language):
            spec = wealth_chart(summary, benchmarks=markets.series).to_dict()
        rows = _records(spec)
        assert _strategy_rows(rows) == [asdict(point) for point in summary.wealth]
        assert _folded_fields(spec) == {"net_wealth", "reference_net_wealth", "benchmark_qqq", "benchmark_spy"}
        for series in markets.series:
            assert [row[f"benchmark_{series.symbol.lower()}"] for row in rows] == [point.equity for point in series.points]
        assert asdict(summary) == original
    scaled = summarize_performance(_rolling_points(5), initial_wealth=2.5)
    scaled_rows = _records(wealth_chart(scaled, benchmarks=markets.series).to_dict())
    assert _strategy_rows(scaled_rows) == [asdict(point) for point in scaled.wealth]
    for series in markets.series:
        assert [row[f"benchmark_{series.symbol.lower()}"] for row in scaled_rows] == [
            point.equity * 2.5 for point in series.points]
    for invalid in (replace(markets.series[1], points=markets.series[1].points[:-1]),
                    replace(markets.series[1], points=tuple(reversed(markets.series[1].points))),
                    replace(markets.series[1], error="Synthetic missing date")):
        with pytest.raises(ValueError, match="dates must match exactly"):
            wealth_chart(summary, benchmarks=(invalid,))


def _research_benchmark_app():
    from dataclasses import asdict
    from unittest.mock import patch
    import streamlit as st
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.models import DecisionOverview, PerformanceHistory, Provenance
    from apps.demo_console.pages import research
    from apps.demo_console.tests.test_performance_charts import _rolling_points

    language = st.selectbox("Language", ("en", "zh", "ja"), key="language")
    reference = st.checkbox("Synthetic A reference available", value=True, key="synthetic_reference")
    points = _rolling_points(300, reference=reference)
    dates = tuple(point.execution_date for point in points)
    st.session_state.setdefault("decision_date", "2025-08-21")
    model = DecisionOverview(decision_date=st.session_state["decision_date"],
                             provenance=Provenance(execution_date=dates[-1]))
    archive = PerformanceHistory(points=points, available_dates=dates, initial_nav=1,
        reference_available=reference, reference_identity="SYNTHETIC_A" if reference else None,
        archive_start=dates[0], archive_end=dates[-1])
    original = asdict(archive)

    def synthetic_performance(cutoff):
        assert cutoff == dates[-1]
        return archive

    with language_scope(language), patch.object(research, "read_performance", synthetic_performance):
        research.render_research(model, presentation=True)
    assert asdict(archive) == original


def test_three_languages_and_all_window_sizes_keep_four_paths_and_preceding_baseline(benchmark_stub):
    benchmark_stub.response = _markets
    app = AppTest.from_function(_research_benchmark_app, default_timeout=30).run()
    archive = _rolling_points(300)
    for language in ("en", "zh", "ja"):
        app.selectbox(key="language").select(language).run()
        for source, count in (("All days through selected execution", None),
                              ("63 execution days", 63), ("126 execution days", 126), ("252 execution days", 252)):
            app.selectbox(key="research_range").select(source).run()
            assert not app.exception and not app.error
            included = archive if count is None else archive[-count:]
            dates = tuple(point.execution_date for point in included)
            baseline = None if count is None else archive[-count - 1].execution_date
            assert benchmark_stub.calls[-1] == (dates, baseline)
            spec, rows = _wealth_payload(app)
            assert _strategy_rows(rows) == [asdict(point) for point in summarize_performance(included).wealth]
            assert _folded_fields(spec) == {"net_wealth", "reference_net_wealth", "benchmark_qqq", "benchmark_spy"}
            assert tuple(row["execution_date"] for row in rows) == dates
            assert rows[0]["benchmark_spy"] == pytest.approx(1 if baseline is None else .997)
            table = _comparison(app)
            assert len(table) == 4 and table.iloc[-1]["series"] == "SPY · S&P 500"
            assert all(table["observations"] == len(dates))
            assert app.session_state["decision_date"] == "2025-08-21"
            with language_scope(language):
                assert tr("Observed difference · Not risk-adjusted alpha") in _content(app)
            assert "C:/synthetic-private/benchmarks/" not in _content(app)


def test_spy_missing_date_removes_only_spy_and_keeps_strategy_and_qqq_window(benchmark_stub):
    benchmark_stub.response = _markets
    app = AppTest.from_function(_research_benchmark_app, default_timeout=30).run()
    _, before = _wealth_payload(app)
    original_table = _comparison(app).iloc[:3].copy()
    benchmark_stub.response = lambda dates, baseline: _markets(dates, baseline, missing_spy=True)
    app.run()
    assert not app.exception and not app.error
    spec, after = _wealth_payload(app)
    assert _folded_fields(spec) == {"net_wealth", "reference_net_wealth", "benchmark_qqq"}
    assert after == [{key: value for key, value in row.items() if key != "benchmark_spy"} for row in before]
    assert _comparison(app).equals(original_table)
    assert "Market reference unavailable: SPY. The strategy window is retained in full." in _content(app)
    assert len(after) == 300 and benchmark_stub.calls[-1][1] is None


def test_missing_a_keeps_both_market_references_and_does_not_claim_only_a2_is_shown(benchmark_stub):
    benchmark_stub.response = _markets
    app = AppTest.from_function(_research_benchmark_app, default_timeout=30).run()
    app.checkbox(key="synthetic_reference").uncheck().run()
    expected = summarize_performance(_rolling_points(300, reference=False))
    for language in ("en", "zh", "ja"):
        app.selectbox(key="language").select(language).run()
        assert not app.exception and not app.error
        spec, rows = _wealth_payload(app)
        assert _folded_fields(spec) == {"net_wealth", "benchmark_qqq", "benchmark_spy"}
        assert _strategy_rows(rows) == [asdict(point) for point in expected.wealth]
        table = _comparison(app)
        assert list(table["series"])[-2:] == ["QQQ", "SPY · S&P 500"] and len(table) == 3
        with language_scope(language):
            content = _content(app)
            assert tr("Frozen A is unavailable for this window. Any complete market references remain visible.") in content
            assert tr("Only Raw A2 is shown; the frozen A comparison is unavailable for this window.") not in content
        assert benchmark_stub.calls[-1] == (tuple(point.execution_date for point in expected.wealth), None)


def test_difference_cards_preserve_positive_negative_and_missing_a_semantics(monkeypatch):
    from apps.demo_console.pages import research
    from apps.demo_console.tests.test_performance_stats import point

    rendered = []
    monkeypatch.setattr(research.st, "html", rendered.append)
    for language in ("en", "zh", "ja"):
        with language_scope(language):
            for net, reference, displayed in ((.03, .01, "+2.00 pp"),
                                               (.01, .03, "-2.00 pp"), (.01, None, tr("N/A"))):
                summary = summarize_performance((point("2025-01-02", net, reference=reference),))
                original = asdict(summary)
                research._readout(summary)
                html = rendered[-1]
                assert tr("A2 − A return difference") in html and displayed in html
                assert tr("Observed difference · Not risk-adjusted alpha") in html
                if reference is None:
                    assert tr("Frozen A comparison unavailable") in html and " pp" not in html
                assert asdict(summary) == original


def test_recorded_window_adds_only_spy_in_three_languages_and_keeps_original_qqq_and_failure(recorded_app):
    state = recorded_app
    state.benchmarks.response = _markets
    app = _enter_recorded(state)
    original = asdict(state.recorded.history)
    dates = tuple(point.date for point in state.recorded.history.points)
    for language in ("en", "zh", "ja"):
        app.selectbox(key="language").select(language).run()
        for mode in ("Equity path", "Drawdown path"):
            _control(app, "recorded_2026_chart_mode").select(mode).run()
            _assert_recorded_isolation(state)
            assert state.benchmarks.calls[-1] == (dates, None)
            drawdown = mode == "Drawdown path"
            original_rows = _expected_rows(state.recorded.history, drawdown=drawdown)
            rows = _path_rows(app)
            assert rows[:len(original_rows)] == original_rows
            spy = _markets(dates).series[1]
            assert rows[len(original_rows):] == [
                {"date": point.date, "series": "SPY · S&P 500",
                 "value": point.drawdown if drawdown else point.equity * 100} for point in spy.points]
            assert {row["series"] for row in rows} == {"A2", "A", "QQQ", "SPY · S&P 500"}
            assert len(_comparison(app, recorded=True)) == 4
            assert "FAIL_CLOSED_ANTI_BLOAT_HARD_GATE" in _content(app)
            assert "FINAL_CLASSIFICATION: E" in _content(app) and "ACCOUNTING_COMPLETE: False" in _content(app)
            assert "-4.00 pp" in _content(app)
            assert asdict(state.recorded.history) == original
    state.benchmarks.response = lambda dates, baseline: _markets(dates, baseline, missing_spy=True)
    app.run()
    _assert_recorded_isolation(state)
    assert _path_rows(app) == _expected_rows(state.recorded.history, drawdown=True)
    assert len(_comparison(app, recorded=True)) == 3
    with language_scope("ja"):
        assert tr("Market reference unavailable: {symbols}. The strategy window is retained in full.", symbols="SPY") in _content(app)
    assert asdict(state.recorded.history) == original
