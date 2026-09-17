"""Pure synthetic execution checks, including unknown data and terminal cash."""
from dataclasses import replace
import json
import unittest
from unittest.mock import MagicMock, patch

from apps.demo_console.components import execution_quality as quality
from apps.demo_console.i18n import language_scope, tr
from apps.demo_console.models import PerformancePoint


def point(day, **changes):
    original = PerformancePoint(day, nav=2, net_return=.01, gross_return=.011,
                                transaction_cost=.002, turnover=.2, cash=.5, position_value=1.5,
                                holding_count=20, stale_mark_count=0, skipped_buy_count=0,
                                blocked_rebalance_count=0, buy_cash_scale=1)
    return replace(original, **changes)


class ExecutionQualityTests(unittest.TestCase):
    def test_counts_are_days_not_the_sum_of_recorded_events(self):
        points = (point("2025-01-02", stale_mark_count=7, blocked_rebalance_count=3),
                  point("2025-01-03", skipped_buy_count=2, buy_cash_scale=.9995),
                  point("2025-01-06", skipped_buy_count=1, buy_cash_scale=None))
        result = quality.summarize_execution(points)
        self.assertEqual([item["days"] for item in result["events"]], [1, 2, 1, 1])
        self.assertEqual([item["observations"] for item in result["events"]], [3, 3, 3, 2])
        self.assertEqual(quality.execution_records(points)[0]["stale_mark_count"], 7)

    def test_missing_and_invalid_fields_are_unknown_not_zero(self):
        points = (point("2025-01-02", nav=0, cash=None, turnover=float("nan"), transaction_cost=None,
                        stale_mark_count=None, skipped_buy_count=True,
                        blocked_rebalance_count=1.5, buy_cash_scale=1.1),)
        records = quality.execution_records(points)
        self.assertTrue(all(records[0][field] is None for field in (
            "cash_share", "turnover", "transaction_cost", "stale_mark_count", "skipped_buy_count",
            "blocked_rebalance_count", "buy_cash_scale")))
        result = quality.summarize_execution(points)
        self.assertTrue(all(item["days"] is None for item in result["events"]))
        self.assertIsNone(result["total_cost"])
        self.assertIsNone(result["cash_share"]["last"])
        self.assertIsNone(result["turnover"]["median"])
        self.assertEqual(quality.summarize_execution(())["observations"], 0)
        self.assertIsNone(quality.summarize_execution(())["total_cost"])

    def test_cash_uses_same_day_nav_and_last_missing_is_not_replaced(self):
        points = (point("2025-01-02", cash=0, nav=1),
                  point("2025-01-03", cash=3, nav=3),
                  point("2025-01-06", cash=None, nav=2))
        result = quality.summarize_execution(points)
        self.assertEqual(result["cash_share"]["minimum"], 0)
        self.assertEqual(result["cash_share"]["maximum"], 1)
        self.assertIsNone(result["cash_share"]["last"])
        self.assertEqual(result["cash_share"]["observations"], 2)
        self.assertEqual(quality.summarize_execution(points[:2])["cash_share"]["last"], 1)
        self.assertIsNone(quality.execution_records((point("2025-01-02", cash=3, nav=2),))[0]["cash_share"])

    def test_cost_amounts_and_window_bounds_are_preserved_without_rebasing(self):
        points = (point("2025-01-02", transaction_cost=.002),
                  point("2025-01-03", transaction_cost=.005, turnover=1.2),
                  point("2025-01-06", transaction_cost=.003))
        self.assertAlmostEqual(quality.summarize_execution(points)["total_cost"], .01)
        result = quality.summarize_execution(points[1:2])
        self.assertEqual(result["total_cost"], .005)
        self.assertEqual(result["turnover"]["median"], 1.2)
        self.assertEqual([row["execution_date"] for row in quality.execution_records(points[1:2])], ["2025-01-03"])
        partial = (points[0], replace(points[1], transaction_cost=None))
        self.assertIsNone(quality.summarize_execution(partial)["total_cost"])
        self.assertEqual(quality.summarize_execution(partial)["cost_observations"], 1)

    def test_chart_keeps_every_actual_date_zero_and_missing_turnover(self):
        points = (point("2024-12-31", turnover=.5), point("2025-01-02", turnover=None),
                  point("2025-01-06", turnover=0))
        spec = quality.turnover_chart(points).to_dict()
        self.assertEqual([row["turnover"] for row in spec["data"]["values"]], [.5, None, 0])
        self.assertEqual(spec["encoding"]["x"]["scale"]["domain"], [row.execution_date for row in points])
        self.assertEqual(spec["encoding"]["x"]["axis"]["labelExpr"], "substring(datum.label, 0, 7)")
        self.assertNotIn("transform", spec)
        self.assertEqual(quality.turnover_chart(()).to_dict()["data"]["values"], [])
        json.dumps(spec, allow_nan=False)

    def test_language_changes_only_display_and_models_remain_immutable(self):
        points = (point("2025-01-02", cash=None),)
        before = repr(points)
        original = quality.execution_records(points)
        for language in ("en", "zh", "ja"):
            with language_scope(language):
                spec = quality.turnover_chart(points).to_dict()
                row = spec["data"]["values"][0]
                self.assertEqual({key: row[key] for key in original[0]}, original[0])
                self.assertEqual(row["cash_share_label"], tr("N/A"))
                self.assertEqual(spec["encoding"]["y"]["title"], tr("Executed turnover"))
        self.assertEqual(repr(points), before)

    def test_ambiguous_dates_are_rejected_instead_of_reordered_or_dropped(self):
        for points in ((point("2025-01-03"), point("2025-01-02")),
                       (point("2025-01-02"), point("2025-01-02")), (point("bad-date"),)):
            with self.subTest(points=points), self.assertRaises(ValueError):
                quality.execution_records(points)

    def test_empty_render_shows_no_metrics_or_chart_and_source_unit_is_validated(self):
        with patch.object(quality.st, "html") as html, patch.object(quality.st, "info") as info, \
                patch.object(quality.st, "altair_chart") as chart:
            quality.render_execution_quality(())
            html.assert_called_once()
            info.assert_called_once()
            chart.assert_not_called()
        for initial in (0, -1, None, float("nan")):
            with self.subTest(initial=initial), self.assertRaises(ValueError):
                quality.render_execution_quality((), initial_nav=initial)

    def test_render_discloses_zero_and_cost_units_and_preserves_raw_detail_counts(self):
        points = (point("2025-01-02", stale_mark_count=4),)
        with patch.object(quality.st, "html"), patch.object(quality.st, "caption") as caption, \
                patch.object(quality.st, "columns", return_value=[MagicMock(), MagicMock()]), \
                patch.object(quality.st, "altair_chart"), patch.object(quality.st, "expander", return_value=MagicMock()), \
                patch.object(quality.st, "dataframe") as frame:
            quality.render_execution_quality(points, initial_nav=1)
            notes = " ".join(call.args[0] for call in caption.call_args_list)
            self.assertIn("initial NAV = 1", notes)
            self.assertIn("Zero means no such event was recorded", notes)
            self.assertIn("ordinary fee funding", notes)
            self.assertEqual(frame.call_args.args[0][0]["Stale mark count"], 4)
            self.assertEqual(frame.call_args.args[0][0]["Transaction cost · Source units"], .002)


if __name__ == "__main__":
    unittest.main()
