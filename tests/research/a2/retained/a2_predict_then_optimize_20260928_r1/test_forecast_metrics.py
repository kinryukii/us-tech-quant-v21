"""Synthetic forecast diagnostics and future-input gate checks; no model fits."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import forecast_metrics as metrics


class ForecastMetricsTests(unittest.TestCase):
    def labels(self, values, dates=None):
        dates = dates or ["2025-01-03"] * len(values)
        return pd.DataFrame({"signal_date": pd.to_datetime(dates), "ticker": [f"T{i:02}" for i in range(len(values))],
                             "y_next_open": values, "label_available": np.isfinite(values)})

    def predictions(self, labels, mu, sigma=1.):
        result = labels[metrics.KEY].copy()
        result["mu"] = mu
        result["sigma"] = sigma
        result["q10"], result["q50"], result["q90"] = result.mu - 1., result.mu, result.mu + 1.
        return result

    def spec(self, provider="ridge"):
        return dict(forecast_id="single__" + provider, coalition="single", members=[provider], fusion="identity")

    def test_mse_is_date_equal_not_row_equal_and_returns_are_unclipped(self):
        labels = self.labels([1., 1., 3.], ["2025-01-03", "2025-01-03", "2025-01-06"])
        result, _ = metrics.forecast_diagnostics(labels, self.predictions(labels, 0.), self.spec())
        self.assertAlmostEqual(result["mse"], 5.)
        self.assertAlmostEqual(result["mae"], 2.)
        self.assertEqual(result["evaluation_clip"], 0)

    def test_daily_spearman_ties_and_constant_scores(self):
        labels = self.labels([1., 2., 2., 1., 2.], ["2025-01-03"] * 3 + ["2025-01-06"] * 2)
        result, dates = metrics.forecast_diagnostics(labels, self.predictions(labels, [1., 2., 2., 0., 0.]), self.spec())
        self.assertAlmostEqual(result["day_spearman_ic"], 1.)
        self.assertEqual(result["ic_days"], 1)
        self.assertTrue(np.isnan(dates.day_spearman_ic.iloc[1]))

    def test_top20_is_chosen_before_missing_labels_and_no_replacement_occurs(self):
        labels = self.labels([np.nan] + [1.] * 20)
        prediction = self.predictions(labels, np.arange(21, 0, -1))
        result, dates = metrics.forecast_diagnostics(labels, prediction, self.spec())
        self.assertEqual(dates.top20_selected_count.iloc[0], 20)
        self.assertEqual(dates.top20_labelled_count.iloc[0], 19)
        self.assertEqual(result["top20_complete_input_pool_days"], 0)
        self.assertTrue(np.isnan(result["top20_minus_whole_input_pool"]))

    def test_top20_ties_use_ticker_and_whole_pool_diagnostic_is_exact(self):
        labels = self.labels([1.] * 20 + [21.])
        prediction = self.predictions(labels, 0.)
        result, dates = metrics.forecast_diagnostics(labels, prediction, self.spec())
        self.assertEqual(result["top20_complete_input_pool_days"], 1)
        self.assertAlmostEqual(result["top20_target_mean"], 1.)
        self.assertAlmostEqual(result["whole_input_pool_target_mean"], 41. / 21.)
        self.assertEqual(dates.top20_selected_count.iloc[0], 20)

    def test_pinball_and_coverage_have_raw_target_semantics(self):
        labels = self.labels([0., 2.])
        prediction = self.predictions(labels, 0.)
        prediction["q10"], prediction["q50"], prediction["q90"] = -1., 0., 1.
        result, _ = metrics.forecast_diagnostics(labels, prediction, self.spec("hgb_q"))
        self.assertAlmostEqual(result["pinball_q10"], .2)
        self.assertAlmostEqual(result["pinball_q50"], .5)
        self.assertAlmostEqual(result["pinball_q90"], .5)
        self.assertAlmostEqual(result["coverage_below_q90"], .5)
        self.assertAlmostEqual(result["coverage_q10_q90"], .5)
        self.assertIn("approximation", result["normal_nll_semantics"])

    def test_native_normal_nll_and_proxy_semantics_are_separate(self):
        labels = self.labels([0., 0.])
        prediction = self.predictions(labels, 0., 2.)
        native, _ = metrics.forecast_diagnostics(labels, prediction, self.spec("ngboost"))
        proxy, _ = metrics.forecast_diagnostics(labels, prediction, self.spec())
        self.assertAlmostEqual(native["normal_nll"], np.log(2.) + .5 * np.log(2 * np.pi))
        self.assertEqual(native["normal_nll_semantics"], "native_Normal_distribution")
        self.assertIn("proxy", proxy["normal_nll_semantics"])

    def test_true_classifier_probability_is_not_replaced_by_mu(self):
        labels = self.labels([.7, .7])
        prediction = self.predictions(labels, -100.)
        prediction["p_up"] = .9
        result = metrics.native_probability_diagnostics(labels, prediction, "logistic")
        self.assertAlmostEqual(result["brier"], .01)
        self.assertAlmostEqual(result["logloss"], -np.log(.9))
        self.assertFalse(result["proxy_probabilities_used"])

    def test_point_probability_is_unavailable_even_if_proxy_column_exists(self):
        labels = self.labels([.1])
        prediction = self.predictions(labels, .1)
        prediction["p_up"] = .9
        result = metrics.native_probability_diagnostics(labels, prediction, "ridge")
        self.assertEqual(result["status"], "NO_NATIVE_PROBABILITY")
        self.assertTrue(np.isnan(result["brier"]))

    def test_probability_metrics_are_date_equal_and_invalid_probability_is_reported(self):
        labels = self.labels([1., 1., 1.], ["2025-01-03", "2025-01-03", "2025-01-06"])
        prediction = labels[metrics.KEY].copy()
        prediction["p_up"] = [1., 1., 0.]
        result = metrics.native_probability_diagnostics(labels, prediction, "mlp_cls")
        self.assertAlmostEqual(result["brier"], .5)
        prediction.loc[2, "p_up"] = 2.
        result = metrics.native_probability_diagnostics(labels, prediction, "mlp_cls")
        self.assertEqual(result["invalid_native_probability_rows"], 1)
        self.assertEqual(result["status"], "NATIVE_PROBABILITY_COVERAGE_FAILURE")

    def test_pre2026_label_join_is_exact_and_future_endpoint_is_missing(self):
        labels = self.labels([.7, .1])
        source = labels.copy()
        source["execution_date"] = pd.to_datetime(["2025-01-06", "2025-01-06"])
        source["label_end_date"] = pd.to_datetime(["2025-01-07", "2026-01-02"])
        out = metrics.labels_from_pre2026(labels[metrics.KEY], source.iloc[::-1])
        self.assertAlmostEqual(out.y_next_open.iloc[0], .7)
        self.assertFalse(out.label_available.iloc[1])
        self.assertEqual(out.label_missing_reason.iloc[1], "label_not_pre2026")

    def test_calendar_clock_and_next_open_price_guards(self):
        calendar = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"])
        keys = pd.DataFrame({"signal_date": [calendar[0]] * 5, "ticker": ["OK", "WARN", "ZERO", "NAN", "MISSING"]})
        prices = pd.DataFrame({"ticker": [ticker for ticker in ["OK", "WARN", "ZERO", "NAN"] for _ in range(2)],
            "trade_date": [calendar[1], calendar[2]] * 4, "open": [10., 15., 10., 11., 0., 11., 10., np.nan],
            "price_quality_warning": [False, False, False, True, False, False, False, False]})
        out = metrics.labels_from_prices(keys, prices, calendar).set_index("ticker")
        self.assertAlmostEqual(out.loc["OK", "y_next_open"], .5)
        self.assertEqual(out.loc["OK", "execution_date"], calendar[1])
        self.assertEqual(out.loc["OK", "label_end_date"], calendar[2])
        self.assertEqual(out.loc["WARN", "label_missing_reason"], "price_quality_warning_or_unknown")
        self.assertEqual(out.loc["ZERO", "label_missing_reason"], "next_open_price_nonpositive")
        self.assertEqual(out.loc["NAN", "label_missing_reason"], "next_open_price_nonfinite")
        self.assertEqual(out.loc["MISSING", "label_missing_reason"], "next_open_price_missing")

    def test_nullable_warning_and_terminal_calendar_are_not_accepted(self):
        calendar = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])
        keys = pd.DataFrame({"signal_date": [calendar[0], calendar[2]], "ticker": ["A", "A"]})
        prices = pd.DataFrame({"ticker": ["A", "A"], "trade_date": [calendar[1], calendar[2]], "open": [10., 11.],
                               "price_quality_warning": pd.array([False, pd.NA], dtype="boolean")})
        out = metrics.labels_from_prices(keys, prices, calendar)
        self.assertFalse(out.label_available.any())
        self.assertEqual(out.label_missing_reason.iloc[0], "price_quality_warning_or_unknown")
        self.assertEqual(out.label_missing_reason.iloc[1], "next_two_sessions_unavailable")

    def test_2026_gate_is_checked_before_any_source_read(self):
        with patch.object(metrics, "validate_global_freeze", side_effect=RuntimeError("unfrozen")), \
             patch.object(metrics.pd, "read_parquet") as read_frame:
            with self.assertRaisesRegex(RuntimeError, "unfrozen"):
                metrics.load_labels(2026)
            read_frame.assert_not_called()

    def test_duplicate_forecast_keys_fail(self):
        labels = self.labels([.1])
        prediction = self.predictions(labels, .1)
        with self.assertRaisesRegex(ValueError, "DUPLICATE_PREDICTION_KEYS"):
            metrics.forecast_diagnostics(labels, pd.concat([prediction, prediction]), self.spec())


if __name__ == "__main__":
    unittest.main()
