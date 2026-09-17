"""Synthetic arithmetic and display-boundary tests; no artifact access."""
from dataclasses import FrozenInstanceError, asdict, replace
from datetime import date, timedelta
from math import expm1, log1p
import unittest

from apps.demo_console.components.performance_stats import (
    matched_risk_comparison, rolling_returns, summarize_performance,
)
from apps.demo_console.models import PerformancePoint


def point(day, net, *, gross=None, cost=0.0, reference=None):
    return PerformancePoint(
        execution_date=day, nav=1.0 + net, net_return=net,
        gross_return=net if gross is None else gross, transaction_cost=cost,
        turnover=0.0, cash=0.0, position_value=1.0 + net, holding_count=1,
        stale_mark_count=0, skipped_buy_count=0, blocked_rebalance_count=0,
        buy_cash_scale=1.0,
        reference_nav=1.0 + reference if reference is not None else None,
        reference_net_return=reference, reference_gross_return=reference,
        reference_transaction_cost=0.001 if reference is not None else None,
    )


def series(returns):
    start = date(2024, 1, 2)
    return tuple(point((start + timedelta(days=i)).isoformat(), value)
                 for i, value in enumerate(returns))


class PerformanceStatsTests(unittest.TestCase):
    def test_first_day_cost_is_included_and_cost_amount_is_not_a_return_gap(self):
        rows = (
            point("2024-01-02", -0.01, gross=0.0, cost=0.01),
            replace(point("2024-01-03", 0.10, gross=0.11, cost=0.0099), nav=1.089),
        )
        original = tuple(asdict(row) for row in rows)
        result = summarize_performance(rows, initial_wealth=2.0)
        self.assertAlmostEqual(result.wealth[0].net_wealth, 1.98)
        self.assertAlmostEqual(result.wealth[-1].net_wealth, 2.178)
        self.assertAlmostEqual(result.net_total_return, 0.089)
        self.assertAlmostEqual(result.gross_total_return, 0.11)
        self.assertAlmostEqual(result.total_transaction_cost, 0.0199)
        self.assertAlmostEqual(result.gross_net_difference_pp, 2.1)
        self.assertNotAlmostEqual(result.net_total_return, rows[-1].nav / rows[0].nav - 1.0)
        self.assertEqual(tuple(asdict(row) for row in rows), original)

    def test_drawdown_identifies_peak_trough_and_first_recovery(self):
        rows = series([0.1, -0.2, 0.25, 0.01])
        result = summarize_performance(rows)
        self.assertAlmostEqual(result.max_drawdown.depth, -0.2)
        self.assertEqual(result.max_drawdown.peak_date, rows[0].execution_date)
        self.assertEqual(result.max_drawdown.trough_date, rows[1].execution_date)
        self.assertEqual(result.max_drawdown.recovery_date, rows[2].execution_date)
        self.assertFalse(result.max_drawdown.peak_is_initial)
        self.assertEqual(result.wealth[0].drawdown, 0.0)

    def test_first_day_loss_uses_explicit_initial_peak_and_can_remain_unrecovered(self):
        rows = series([-0.1, 0.05])
        deepest = summarize_performance(rows).max_drawdown
        self.assertAlmostEqual(deepest.depth, -0.1)
        self.assertTrue(deepest.peak_is_initial)
        self.assertIsNone(deepest.peak_date)
        self.assertEqual(deepest.trough_date, rows[0].execution_date)
        self.assertIsNone(deepest.recovery_date)
        recovered = summarize_performance(series([-0.1, 1.0 / 0.9 - 1.0]))
        self.assertEqual(recovered.max_drawdown.recovery_date, rows[1].execution_date)

    def test_no_drawdown_has_no_fabricated_episode_dates(self):
        result = summarize_performance(series([0.0, 0.01, 0.02]))
        self.assertEqual(result.max_drawdown.depth, 0.0)
        self.assertIsNone(result.max_drawdown.peak_date)
        self.assertIsNone(result.max_drawdown.trough_date)
        self.assertIsNone(result.max_drawdown.recovery_date)

    def test_period_compounding_distinguishes_window_cuts_and_source_boundaries(self):
        calendar = (
            "2023-12-29", "2024-01-02", "2024-01-31", "2024-02-01",
            "2024-02-29", "2024-03-01", "2024-12-31", "2025-01-02",
        )
        rows = tuple(point(day, value) for day, value in
                     zip(calendar, [0.0, 0.02, 0.05, -0.1, 0.2, 0.01, 0.0, 0.01]))
        result = summarize_performance(rows[2:5], full_history_dates=calendar)
        january, february = result.months
        self.assertEqual((january.period, january.observations), ("2024-01", 1))
        self.assertTrue(january.window_partial)
        self.assertFalse(january.coverage_boundary)
        self.assertFalse(february.window_partial)
        self.assertFalse(february.coverage_boundary)
        self.assertEqual(february.observations, 2)
        self.assertAlmostEqual(february.net_return, 0.08)
        self.assertAlmostEqual(result.years[0].net_return, 0.134)
        self.assertTrue(result.years[0].window_partial)
        self.assertFalse(result.years[0].coverage_boundary)
        full = summarize_performance(rows, full_history_dates=calendar)
        full_january = next(month for month in full.months if month.period == "2024-01")
        self.assertFalse(full_january.window_partial)  # First record need not be day 1.
        self.assertFalse(full_january.coverage_boundary)
        self.assertTrue(full.months[0].coverage_boundary)
        self.assertTrue(full.months[-1].coverage_boundary)
        self.assertTrue(all(not period.window_partial for period in full.years))

    def test_missing_calendar_does_not_claim_to_know_excluded_observations(self):
        result = summarize_performance((point("2024-01-17", 0.01),))
        self.assertFalse(result.months[0].window_partial)
        self.assertTrue(result.months[0].coverage_boundary)

    def test_reference_paths_compound_independently_and_differences_use_percentage_points(self):
        rows = (
            point("2024-12-31", 0.10, reference=0.02),
            point("2025-01-02", -0.10, reference=0.02),
        )
        result = summarize_performance(rows)
        self.assertTrue(result.reference_available)
        self.assertAlmostEqual(result.net_total_return, -0.01)
        self.assertAlmostEqual(result.reference_net_total_return, 0.0404)
        self.assertAlmostEqual(result.wealth[-1].reference_net_wealth, 1.0404)
        self.assertAlmostEqual(result.net_difference_pp, -5.04)
        self.assertAlmostEqual(result.reference_total_transaction_cost, 0.002)
        self.assertAlmostEqual(result.years[0].net_difference_pp, 8.0)
        self.assertAlmostEqual(result.years[1].net_difference_pp, -12.0)

    def test_reference_must_be_complete_everywhere_or_absent_everywhere(self):
        first = point("2024-01-02", 0.01, reference=0.02)
        second = point("2024-01-03", 0.01)
        for rows in ((first, second), (replace(first, reference_nav=None),)):
            with self.subTest(rows=rows), self.assertRaisesRegex(ValueError, "Reference coverage"):
                summarize_performance(rows)
        result = summarize_performance((second,))
        self.assertFalse(result.reference_available)
        self.assertIsNone(result.reference_net_total_return)
        self.assertIsNone(result.net_difference_pp)
        self.assertIsNone(result.wealth[0].reference_net_wealth)

    def test_log_concentration_uses_all_positive_growth_and_keeps_losses_separate(self):
        positives = [expm1(i / 1000.0) for i in range(1, 13)]
        result = summarize_performance(series(positives + [-0.02, -0.03]))
        self.assertAlmostEqual(result.positive_log_growth, 0.078)
        self.assertAlmostEqual(result.negative_log_growth, log1p(-0.02) + log1p(-0.03))
        self.assertAlmostEqual(result.top5_positive_log_share, 0.05 / 0.078)
        self.assertAlmostEqual(result.top10_positive_log_share, 0.075 / 0.078)
        self.assertAlmostEqual(result.positive_log_growth + result.negative_log_growth,
                               log1p(result.net_total_return))
        losses_only = summarize_performance(series([-0.01, 0.0, -0.02]))
        self.assertEqual(losses_only.positive_log_growth, 0.0)
        self.assertIsNone(losses_only.top5_positive_log_share)
        self.assertIsNone(losses_only.top10_positive_log_share)

    def test_daily_extremes_use_recorded_return_and_earliest_date_on_ties(self):
        rows = series([0.03, -0.02, 0.03, -0.02])
        result = summarize_performance(rows)
        self.assertEqual(result.best_day.execution_date, rows[0].execution_date)
        self.assertEqual(result.worst_day.execution_date, rows[1].execution_date)
        self.assertEqual(result.best_day.net_return, 0.03)
        self.assertEqual(result.worst_day.net_return, -0.02)

    def test_autocorrelation_requires_twenty_pairs_and_nonconstant_samples(self):
        alternating = [0.01 if i % 2 else -0.01 for i in range(25)]
        result = summarize_performance(series(alternating))
        self.assertAlmostEqual(result.autocorrelation_lag1, -1.0)
        self.assertAlmostEqual(result.autocorrelation_lag5, -1.0)
        short = summarize_performance(series(alternating[:20]))
        self.assertIsNone(short.autocorrelation_lag1)
        self.assertIsNone(short.autocorrelation_lag5)
        enough_for_one = summarize_performance(series(alternating[:21]))
        self.assertAlmostEqual(enough_for_one.autocorrelation_lag1, -1.0)
        self.assertIsNone(enough_for_one.autocorrelation_lag5)
        constant = summarize_performance(series([0.01] * 25))
        self.assertIsNone(constant.autocorrelation_lag1)
        self.assertIsNone(constant.autocorrelation_lag5)

    def test_constant_returns_remain_unavailable_when_mean_rounding_leaves_residuals(self):
        for value in (0.003, 0.007, 0.1, 0.2, 1e-8, -0.003):
            with self.subTest(value=value):
                result = summarize_performance(series([value] * 25))
                self.assertIsNone(result.autocorrelation_lag1)
                self.assertIsNone(result.autocorrelation_lag5)

    def test_invalid_values_are_rejected_instead_of_dropped_or_filled(self):
        valid = point("2024-01-02", 0.01)
        invalid = (
            replace(valid, net_return=float("nan")),
            replace(valid, gross_return=float("inf")),
            replace(valid, net_return=-1.0),
            replace(valid, net_return=-1.01),
            replace(valid, net_return=True),
            replace(valid, transaction_cost=-0.01),
            replace(valid, transaction_cost=float("inf")),
            replace(valid, execution_date="2024-1-2"),
        )
        for row in invalid:
            with self.subTest(row=row), self.assertRaises(ValueError):
                summarize_performance((row,))
        for initial in (0.0, -1.0, float("nan"), float("inf"), True):
            with self.subTest(initial=initial), self.assertRaises(ValueError):
                summarize_performance((valid,), initial_wealth=initial)
        with self.assertRaises(ValueError):
            summarize_performance(series([1e308, 1e308]))
        with self.assertRaises(ValueError):
            summarize_performance((point("2024-12-31", 1e200), point("2025-01-02", 1e200)),
                                  initial_wealth=1e-300)

    def test_duplicate_reordered_or_omitted_recorded_dates_fail_closed(self):
        rows = series([0.01, 0.02, 0.03])
        calendar = tuple(row.execution_date for row in rows)
        for selected, dates in (
            ((rows[0], rows[0]), None), (rows[::-1], None),
            ((rows[0], rows[2]), calendar), (rows, calendar[1:]),
            (rows, tuple(reversed(calendar))),
        ):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                summarize_performance(selected, full_history_dates=dates)

    def test_empty_input_is_unavailable_not_a_zero_return_strategy(self):
        result = summarize_performance((), initial_wealth=2.0)
        self.assertEqual(result.observations, 0)
        self.assertEqual(result.initial_wealth, 2.0)
        self.assertEqual(result.wealth, ())
        self.assertEqual(result.months, ())
        self.assertIsNone(result.net_total_return)
        self.assertIsNone(result.total_transaction_cost)
        self.assertIsNone(result.best_day)
        self.assertIsNone(result.positive_log_growth)

    def test_rolling_span_rejects_invalid_values_even_for_empty_history(self):
        empty = summarize_performance(())
        for span in (True, False, 0, -1, 63.0, "63", None):
            with self.subTest(span=span), self.assertRaisesRegex(ValueError, "positive integer"):
                rolling_returns(empty, span)
        for count in (0, 1, 62):
            self.assertEqual(rolling_returns(summarize_performance(series([.01] * count))), ())

    def test_rolling_63_and_64_observations_include_initial_cost_then_advance_baseline(self):
        rows = series([-.01] + [0.0] * 62 + [.02])
        rows = (replace(rows[0], gross_return=0.0, transaction_cost=.01), *rows[1:])
        one = rolling_returns(summarize_performance(rows[:63], initial_wealth=2.0))
        two = rolling_returns(summarize_performance(rows, initial_wealth=2.0))
        self.assertEqual(len(one), 1)
        self.assertEqual(len(two), 2)
        self.assertEqual(one, two[:1])
        self.assertEqual((one[0].start_date, one[0].end_date, one[0].observations),
                         (rows[0].execution_date, rows[62].execution_date, 63))
        self.assertAlmostEqual(one[0].net_return, -.01)
        self.assertEqual((two[1].start_date, two[1].end_date),
                         (rows[1].execution_date, rows[63].execution_date))
        self.assertAlmostEqual(two[1].net_return, .02)
        self.assertTrue(all(row.reference_net_return is None for row in two))

    def test_rolling_losses_and_reference_compound_independently_without_mutation(self):
        rows = tuple(replace(row, reference_nav=1.002, reference_net_return=.002,
                             reference_gross_return=.002, reference_transaction_cost=0.0)
                     for row in series([-.003] * 64))
        summary = summarize_performance(rows)
        original_summary = asdict(summary)
        original_points = tuple(asdict(row) for row in rows)
        result = rolling_returns(summary)
        self.assertEqual(len(result), 2)
        for window in result:
            self.assertLess(window.net_return, 0.0)
            self.assertAlmostEqual(window.net_return, .997 ** 63 - 1.0)
            self.assertAlmostEqual(window.reference_net_return, 1.002 ** 63 - 1.0)
        self.assertEqual(asdict(summary), original_summary)
        self.assertEqual(tuple(asdict(row) for row in rows), original_points)
        with self.assertRaises(FrozenInstanceError):
            result[0].net_return = 999

    def test_rolling_uses_only_selected_records_without_prior_or_future_fill(self):
        archive = series([.7] * 10 + [.001] * 64 + [.9])
        calendar = tuple(row.execution_date for row in archive)
        short = summarize_performance(archive[10:72], full_history_dates=calendar)
        selected = summarize_performance(archive[10:74], full_history_dates=calendar)
        self.assertEqual(rolling_returns(short), ())
        result = rolling_returns(selected)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].start_date, archive[10].execution_date)
        self.assertEqual(result[-1].end_date, archive[73].execution_date)
        for window in result:
            self.assertAlmostEqual(window.net_return, 1.001 ** 63 - 1.0)
        # A span counts observed executions, never inferred intervening dates.
        irregular = (point("2024-01-02", -.02), point("2024-02-07", .03))
        singles = rolling_returns(summarize_performance(irregular), span=1)
        self.assertEqual([(row.start_date, row.end_date, row.observations) for row in singles],
                         [(row.execution_date, row.execution_date, 1) for row in irregular])
        for window, row in zip(singles, irregular):
            self.assertAlmostEqual(window.net_return, row.net_return)

    def test_matched_risk_includes_initial_losses_for_both_paths_and_preserves_inputs(self):
        rows = (
            point("2024-01-02", -.1, gross=0.0, cost=.1, reference=-.2),
            point("2024-01-03", .05, reference=.25),
        )
        summary = summarize_performance(rows, initial_wealth=2.0)
        original_summary = asdict(summary)
        original_points = tuple(asdict(row) for row in rows)
        a2, reference = matched_risk_comparison(summary)
        self.assertEqual((a2.series, reference.series), ("Raw A2", "Frozen A control"))
        self.assertAlmostEqual(a2.net_total_return, -.055)
        self.assertAlmostEqual(a2.max_drawdown, -.1)
        self.assertAlmostEqual(a2.worst_daily_net_return, -.1)
        self.assertAlmostEqual(reference.net_total_return, 0.0)
        self.assertAlmostEqual(reference.max_drawdown, -.2)
        self.assertAlmostEqual(reference.worst_daily_net_return, -.2)
        self.assertEqual((a2.observations, reference.observations), (2, 2))
        self.assertEqual(asdict(summary), original_summary)
        self.assertEqual(tuple(asdict(row) for row in rows), original_points)
        with self.assertRaises(FrozenInstanceError):
            a2.max_drawdown = 0

    def test_matched_risk_positive_paths_have_zero_drawdown_and_positive_worst_day(self):
        rows = tuple(replace(row, reference_nav=1 + reference, reference_net_return=reference,
                             reference_gross_return=reference, reference_transaction_cost=0.0)
                     for row, reference in zip(series([.1, .2, .3]), [.02, .03, .04]))
        a2, reference = matched_risk_comparison(summarize_performance(rows))
        self.assertAlmostEqual(a2.net_total_return, .716)
        self.assertAlmostEqual(reference.net_total_return, .092624)
        self.assertEqual((a2.max_drawdown, reference.max_drawdown), (0.0, 0.0))
        self.assertAlmostEqual(a2.worst_daily_net_return, .1)
        self.assertAlmostEqual(reference.worst_daily_net_return, .02)

    def test_matched_risk_does_not_fabricate_missing_or_partial_reference(self):
        self.assertEqual(matched_risk_comparison(summarize_performance(())), ())
        no_reference = summarize_performance(series([-.1, .2]))
        self.assertEqual([row.series for row in matched_risk_comparison(no_reference)], ["Raw A2"])
        rows = (point("2024-01-02", -.1, reference=.01),
                point("2024-01-03", .2, reference=.02))
        complete = summarize_performance(rows)
        partial = replace(complete, wealth=(
            replace(complete.wealth[0], reference_net_wealth=None), complete.wealth[1],
        ))
        for summary in (partial, replace(complete, reference_available=False)):
            result = matched_risk_comparison(summary)
            self.assertEqual([row.series for row in result], ["Raw A2"])
            self.assertEqual(result[0], matched_risk_comparison(complete)[0])

    def test_matched_risk_uses_only_the_selected_execution_window(self):
        rows = tuple(replace(row, reference_nav=1 + reference, reference_net_return=reference,
                             reference_gross_return=reference, reference_transaction_cost=0.0)
                     for row, reference in zip(series([.9, -.1, .3, -.2, -.8]),
                                               [.7, .01, -.02, .01, -.9]))
        calendar = tuple(row.execution_date for row in rows)
        selected = summarize_performance(rows[1:4], full_history_dates=calendar)
        a2, reference = matched_risk_comparison(selected)
        self.assertEqual((a2.observations, reference.observations), (3, 3))
        self.assertAlmostEqual(a2.net_total_return, -.064)
        self.assertAlmostEqual(a2.max_drawdown, -.2)
        self.assertAlmostEqual(a2.worst_daily_net_return, -.2)
        self.assertAlmostEqual(reference.net_total_return, -.000302)
        self.assertAlmostEqual(reference.max_drawdown, -.02)
        self.assertAlmostEqual(reference.worst_daily_net_return, -.02)


if __name__ == "__main__":
    unittest.main()
