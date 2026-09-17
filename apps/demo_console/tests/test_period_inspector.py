"""Synthetic month arithmetic and actual Streamlit controls; no artifact access."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import pyarrow as pa
from streamlit.testing.v1 import AppTest
from streamlit.proto.WidgetStates_pb2 import WidgetState

from apps.demo_console.components import period_inspector
from apps.demo_console.components.period_inspector import daily_records, month_details
from apps.demo_console.models import PerformancePoint


def _fixture():
    dates = ("2024-12-31", "2025-01-02", "2025-01-03", "2025-02-03", "2025-02-04", "2025-03-03")
    returns = (0, -.01, .02, -.10, -.05, .777)
    costs = (0, .01, .00495, .02, .009, 0)
    points = tuple(PerformancePoint(
        execution_date=day, nav=20 + index, net_return=net,
        gross_return=net + cost, transaction_cost=cost, turnover=.2,
        cash=0, position_value=20 + index, holding_count=20,
        stale_mark_count=0, skipped_buy_count=0, blocked_rebalance_count=0, buy_cash_scale=1,
        reference_nav=1.001, reference_net_return=.001, reference_gross_return=.0011,
        reference_transaction_cost=.0001,
    ) for index, (day, net, cost) in enumerate(zip(dates, returns, costs)))
    return points, dates


def _app_script():
    from dataclasses import replace
    import streamlit as st
    from apps.demo_console.components.period_inspector import render_monthly_selector, render_period_inspector
    from apps.demo_console.components.performance_stats import summarize_performance
    from apps.demo_console.components.localized_tabs import localized_tabs
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.tests.test_period_inspector import _fixture

    archive, calendar = _fixture()
    language = st.selectbox("Language", ("en", "zh", "ja"), key="language")
    window = st.selectbox("Synthetic window", ("Full", "First February day", "January only", "Empty"), key="window")
    missing_reference = st.checkbox("Reference unavailable", key="missing_reference")
    show_reference = st.checkbox("Show reference", value=True, key="show_reference")
    st.session_state.setdefault("decision_date", "2025-02-03")
    st.session_state.setdefault("replay_date", "2025-02-03")
    st.session_state.setdefault("workspace", "Research")
    st.session_state.setdefault("research_range", "63 execution days")
    # Neither the earlier December point nor the conspicuous future March
    # return is ever passed to the component. The full calendar is metadata.
    points = {"Full": archive[1:5], "First February day": archive[1:4],
              "January only": archive[1:3], "Empty": ()}[window]
    if missing_reference:
        points = tuple(replace(point, reference_nav=None, reference_net_return=None,
                               reference_gross_return=None, reference_transaction_cost=None) for point in points)
    with language_scope(language):
        performance, method = localized_tabs(("Performance path", "Evidence & method"), key="research_tabs")
        with performance:
            render_monthly_selector(summarize_performance(points, full_history_dates=calendar))
            render_period_inspector(points, full_history_dates=calendar, initial_nav=1,
                                    show_reference=show_reference)
        with method:
            st.write("Synthetic method content")


def _chart_rows(app):
    chart = next(chart for chart in app.get("vega_lite_chart")
                 if json.loads(chart.proto.spec).get("name") == "research_month_detail_chart")
    spec = json.loads(chart.proto.spec)
    assert spec["name"] == "research_month_detail_chart"
    payloads = [chart.proto.data.data, *(dataset.data.data for dataset in chart.proto.datasets)]
    rows = [row for payload in payloads if payload
            for row in pa.ipc.open_stream(payload).read_all().to_pylist()]
    return spec, rows


def _native_month_chart(app):
    return next(chart for chart in app.get("vega_lite_chart")
                if "research_month" in chart.proto.selection_mode)


def _month_click(app, period, *, widget_id=None):
    states = app._tree.get_widget_states()
    states.widgets.append(WidgetState(
        id=widget_id or _native_month_chart(app).proto.id,
        string_value=json.dumps({"selection": {"research_month": [{"period": period}]}}),
    ))
    return app._run(states)


def _folds(spec):
    if isinstance(spec, dict):
        if "fold" in spec:
            yield spec["fold"]
        for child in spec.values():
            yield from _folds(child)
    elif isinstance(spec, list):
        for child in spec:
            yield from _folds(child)


class PeriodInspectorTests(unittest.TestCase):
    def test_month_callback_rejects_foreign_stale_and_malformed_events(self):
        state = {"_research_month_chart_key": "current", "research_month_detail_month": "2025-02",
                 "research_month_detail": False, "decision_date": "2025-02-03"}
        invalid = (None, {}, {"selection": None}, {"selection": {"research_month": []}},
                   {"selection": {"research_month": [{"period": "2025-03"}]}},
                   {"selection": {"research_month": [{"period": ["2025-01"]}]}},
                   {"selection": {"research_month": [{"period": "2025-01"}, {"period": "2025-02"}]}})
        with patch.object(period_inspector.st, "session_state", state):
            for event in invalid:
                state["current"] = event
                before = dict(state)
                period_inspector._select_month(("2025-01", "2025-02"), "current")
                self.assertEqual(state, before)
            state["obsolete"] = {"selection": {"research_month": [{"period": "2025-01"}]}}
            before = dict(state)
            period_inspector._select_month(("2025-01", "2025-02"), "obsolete")
            self.assertEqual(state, before)

    def test_month_rebases_before_first_return_and_preserves_initial_cost(self):
        archive, calendar = _fixture()
        rows, summary = month_details(archive[1:5], "2025-01", full_history_dates=calendar)
        self.assertEqual(tuple(row.execution_date for row in rows), calendar[1:3])
        self.assertAlmostEqual(summary.wealth[0].net_wealth, .99)
        self.assertAlmostEqual(summary.wealth[-1].net_wealth, 1.0098)
        self.assertAlmostEqual(summary.net_total_return, .0098)
        self.assertAlmostEqual(summary.max_drawdown.depth, -.01)
        self.assertTrue(summary.max_drawdown.peak_is_initial)
        self.assertEqual(daily_records(rows)[0]["transaction_cost"], .01)
        self.assertAlmostEqual(summary.total_transaction_cost, .01495)

    def test_negative_month_has_correct_return_and_drawdown(self):
        archive, calendar = _fixture()
        _, summary = month_details(archive[1:5], "2025-02", full_history_dates=calendar)
        self.assertAlmostEqual(summary.net_total_return, -.145)
        self.assertAlmostEqual(summary.max_drawdown.depth, -.145)
        self.assertEqual(summary.observations, 2)
        self.assertEqual(summary.end_date, "2025-02-04")

    def test_month_cut_and_archive_boundary_are_distinct_without_future_rows(self):
        archive, calendar = _fixture()
        rows, summary = month_details(archive[1:4], "2025-02", full_history_dates=calendar)
        self.assertEqual([row.execution_date for row in rows], ["2025-02-03"])
        self.assertTrue(summary.months[0].window_partial)
        self.assertFalse(summary.months[0].coverage_boundary)
        self.assertEqual(summary.observations, 1)
        _, boundary = month_details(archive[:1], "2024-12", full_history_dates=calendar)
        self.assertTrue(boundary.months[0].coverage_boundary)
        self.assertFalse(boundary.months[0].window_partial)
        with self.assertRaises(ValueError):
            month_details(archive[1:5], "2025-03", full_history_dates=calendar)

    def test_daily_values_missing_reference_and_immutable_source_are_preserved(self):
        archive, calendar = _fixture()
        points = tuple(replace(point, reference_nav=None, reference_net_return=None,
                               reference_gross_return=None, reference_transaction_cost=None)
                       for point in archive[1:5])
        before = tuple(asdict(point) for point in points)
        rows, summary = month_details(points, "2025-01", full_history_dates=calendar)
        records = daily_records(rows)
        self.assertFalse(summary.reference_available)
        self.assertTrue(all(row["reference_net_return"] is None for row in records))
        self.assertEqual([row["net_return"] for row in records], [-.01, .02])
        self.assertEqual([row["gross_return"] for row in records], [0.0, .02495])
        self.assertEqual(tuple(asdict(point) for point in points), before)
        self.assertEqual(daily_records(()), [])


class PeriodInspectorAppTests(unittest.TestCase):
    def app(self):
        app = AppTest.from_file(str(Path(__file__)), default_timeout=10).run()
        self.healthy(app)
        return app

    def healthy(self, app):
        self.assertFalse(app.exception)
        self.assertFalse(app.error)

    def test_native_month_click_opens_details_preserving_scope_and_manual_choices(self):
        app = self.app()
        protected = {key: app.session_state[key] for key in
                     ("decision_date", "replay_date", "workspace", "research_range", "research_tabs")}
        first_id = _native_month_chart(app).proto.id
        self.assertFalse(app.expander[0].proto.expanded)
        _month_click(app, "2025-01")
        self.healthy(app)
        self.assertTrue(app.expander[0].proto.expanded)
        self.assertEqual(app.selectbox(key="research_month_detail_month").value, "2025-01")
        self.assertEqual(app.metric[1].value, "+0.98%")
        self.assertEqual([row["execution_date"] for row in _chart_rows(app)[1]],
                         ["2025-01-02", "2025-01-03"])
        clicked_id = _native_month_chart(app).proto.id
        self.assertNotEqual(first_id, clicked_id)
        app.selectbox(key="research_month_detail_month").select("2025-02").run()
        manual_id = _native_month_chart(app).proto.id
        self.assertNotEqual(clicked_id, manual_id)
        _month_click(app, "2025-01", widget_id=clicked_id)
        app.run()
        self.healthy(app)
        self.assertEqual(app.selectbox(key="research_month_detail_month").value, "2025-02")
        self.assertEqual(app.metric[1].value, "-14.50%")
        self.assertEqual({key: app.session_state[key] for key in protected}, protected)
        # Closing the native expander discards the old selection, so clicking
        # the same month again is a fresh action that reopens the details.
        states = app._tree.get_widget_states()
        # AppTest does not currently include stateful expanders in its default
        # widget list, so send the same bool payload as the browser explicitly.
        states.widgets.append(WidgetState(id=app.expander[0].proto.id, bool_value=False))
        app._run(states)
        self.assertFalse(app.expander[0].proto.expanded)
        _month_click(app, "2025-02")
        self.assertTrue(app.expander[0].proto.expanded)
        self.assertEqual(app.selectbox(key="research_month_detail_month").value, "2025-02")

    def test_month_click_survives_language_and_rejects_previous_window_events(self):
        app = self.app()
        _month_click(app, "2025-01")
        before = app.dataframe[0].value.copy(deep=True)
        for language in ("zh", "ja", "en"):
            app.selectbox(key="language").select(language).run()
            self.healthy(app)
            self.assertEqual(app.selectbox(key="research_month_detail_month").value, "2025-01")
            self.assertTrue(app.expander[0].proto.expanded)
            self.assertTrue(app.dataframe[0].value.equals(before))
            self.assertEqual(app.session_state["_localized_tabs:research_tabs"], "Performance path")
        states = app._tree.get_widget_states()
        states.widgets.append(WidgetState(id=app.get("tab_container")[0].proto.tab_container.id,
                                          string_value="Evidence & method"))
        app._run(states)
        _month_click(app, "2025-02")
        self.assertEqual(app.session_state["_localized_tabs:research_tabs"], "Evidence & method")
        self.assertEqual(app.get("tab_container")[0].proto.tab_container.default_tab_index, 1)
        old_id = _native_month_chart(app).proto.id
        app.selectbox(key="window").select("January only").run()
        self.assertNotEqual(_native_month_chart(app).proto.id, old_id)
        _month_click(app, "2025-02", widget_id=old_id)
        self.healthy(app)
        self.assertEqual(app.selectbox(key="research_month_detail_month").value, "2025-01")
        self.assertEqual([row["execution_date"] for row in _chart_rows(app)[1]],
                         ["2025-01-02", "2025-01-03"])
        _month_click(app, "2025-03")
        self.assertEqual(app.selectbox(key="research_month_detail_month").value, "2025-01")
        self.assertEqual(app.session_state["decision_date"], "2025-02-03")
        self.assertEqual(app.session_state["decision_date"], "2025-02-03")
        self.assertEqual(app.session_state["replay_date"], "2025-02-03")
        self.assertEqual(app.session_state["workspace"], "Research")

    def test_latest_default_is_chronological_and_never_exposes_other_months(self):
        app = self.app()
        self.assertEqual(app.selectbox(key="research_month_detail_month").options, ["2025-02", "2025-01"])
        self.assertEqual(app.selectbox(key="research_month_detail_month").value, "2025-02")
        self.assertEqual([metric.value for metric in app.metric], ["2", "-14.50%", "-14.50%"])
        spec, rows = _chart_rows(app)
        self.assertEqual([row["execution_date"] for row in rows], ["2025-02-03", "2025-02-04"])
        self.assertAlmostEqual(rows[0]["net_wealth"], .9)
        self.assertEqual({tuple(fields) for fields in _folds(spec)},
                         {("net_wealth", "reference_net_wealth")})
        self.assertEqual(app.dataframe[0].value["execution_date"].tolist(), ["2025-02-03", "2025-02-04"])

    def test_selected_month_survives_language_and_valid_window_changes(self):
        app = self.app()
        app.selectbox(key="research_month_detail_month").select("2025-01").run()
        before = app.dataframe[0].value.copy(deep=True)
        for language in ("zh", "ja", "en"):
            app.selectbox(key="language").select(language).run()
            self.healthy(app)
            self.assertEqual(app.selectbox(key="research_month_detail_month").value, "2025-01")
            self.assertTrue(app.dataframe[0].value.equals(before))
            _, rows = _chart_rows(app)
            self.assertEqual([row["execution_date"] for row in rows], ["2025-01-02", "2025-01-03"])
            self.assertAlmostEqual(rows[0]["net_wealth"], .99)
            self.assertEqual(app.dataframe[0].value["transaction_cost"].iloc[0], .01)
        app.selectbox(key="window").select("First February day").run()
        self.healthy(app)
        self.assertEqual(app.selectbox(key="research_month_detail_month").value, "2025-01")
        app.selectbox(key="research_month_detail_month").select("2025-02").run()
        self.healthy(app)
        self.assertEqual(app.metric[0].value, "1")
        self.assertTrue(any("cuts this month" in info.value for info in app.info))
        self.assertEqual([row["execution_date"] for row in _chart_rows(app)[1]], ["2025-02-03"])
        app.selectbox(key="window").select("January only").run()
        self.healthy(app)
        self.assertEqual(app.selectbox(key="research_month_detail_month").value, "2025-01")

    def test_native_month_event_is_not_overwritten_by_initial_or_replayed_default(self):
        app = self.app()
        widget = app.selectbox(key="research_month_detail_month")
        self.assertEqual(widget.proto.default, 0)
        self.assertFalse(widget.proto.set_value)
        self.assertFalse(widget.proto.HasField("raw_value"))

        # Send exactly the selectbox's native wire value, rather than mutating
        # Session State. This exercises the real deserializer and registration.
        state = app._tree.get_widget_states()
        for event in state.widgets:
            if event.id == widget.id:
                event.string_value = "2025-01"
        app._run(widget_state=state)
        for _ in range(2):
            self.healthy(app)
            widget = app.selectbox(key="research_month_detail_month")
            self.assertEqual(widget.value, "2025-01")
            self.assertFalse(widget.proto.set_value)
            self.assertFalse(widget.proto.HasField("raw_value"))
            self.assertEqual(app.metric[1].value, "+0.98%")
            self.assertEqual(app.dataframe[0].value["execution_date"].tolist(),
                             ["2025-01-02", "2025-01-03"])
            app.run()

        # Widget cleanup may run when the page/window is temporarily absent.
        # Restoring it must push the saved month, never the latest default.
        app.selectbox(key="window").select("Empty").run()
        self.assertEqual(app.session_state["research_month_detail_month"], "2025-01")
        app.selectbox(key="window").select("Full").run()
        self.healthy(app)
        restored = app.selectbox(key="research_month_detail_month")
        self.assertEqual(restored.value, "2025-01")
        self.assertTrue(restored.proto.set_value)
        self.assertEqual(restored.proto.raw_value, "2025-01")

    def test_absent_reference_is_null_and_empty_window_has_no_chart_or_zero_metrics(self):
        app = self.app()
        app.checkbox(key="missing_reference").check().run()
        self.healthy(app)
        spec, rows = _chart_rows(app)
        self.assertEqual({tuple(fields) for fields in _folds(spec)}, {("net_wealth",)})
        self.assertTrue(all(row["reference_net_wealth"] is None for row in rows))
        self.assertTrue(app.dataframe[0].value["reference_net_return"].isna().all())
        app.checkbox(key="missing_reference").uncheck().run()
        app.checkbox(key="show_reference").uncheck().run()
        self.healthy(app)
        self.assertEqual({tuple(fields) for fields in _folds(_chart_rows(app)[0])}, {("net_wealth",)})
        app.selectbox(key="window").select("Empty").run()
        self.healthy(app)
        self.assertFalse(app.get("vega_lite_chart"))
        self.assertFalse(app.metric)
        self.assertFalse(app.dataframe)
        self.assertTrue(app.info)


if __name__ == "__main__":
    _app_script()
