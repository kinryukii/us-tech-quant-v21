from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT = Path(__file__).parents[2] / "scripts/run/fast3_r36_payoff_path_decomposition_r1.py"
SPEC = importlib.util.spec_from_file_location("r36", SCRIPT)
R = importlib.util.module_from_spec(SPEC); assert SPEC.loader is not None; SPEC.loader.exec_module(R)


def path_frame(opens, highs, lows):
    return pd.DataFrame({"timestamp_utc": pd.date_range("2020-01-01", periods=len(opens), freq="min", tz="UTC"),
                         "open_return": opens, "high_return": highs, "low_return": lows})


def test_zero_model_fixed_research_budget():
    contract = R.preregistration("fixed")
    assert contract["MODEL_FIT_ALLOWED"] is contract["MODEL_PREDICT_ALLOWED"] is False
    assert contract["FIXED_HORIZONS_MINUTES"] == [5, 10, 15, 30, 60]
    assert contract["STOP_LEVELS"] == [.005, .01, .015, .02]
    assert contract["MAX_TAKE_PROFIT_RULE_COUNT"] == contract["MAX_PATH_RULE_COMBINATION_COUNT"] == 0


def test_corporate_action_normalization_uses_real_long_etf_path():
    start = pd.Timestamp("2020-01-01T00:00Z"); end = start + pd.Timedelta(minutes=1)
    actions = [{"symbol": "SOXS", "effective_timestamp": end.isoformat(), "pre_to_post_price_multiplier": 10.0}]
    raw = pd.DataFrame({"timestamp_utc": [start, end], "open": [5., 51.], "high": [5.1, 52.], "low": [4.9, 50.], "close": [5., 51.]})
    result = R.normalized_bar_returns(raw, start, 5., "SOXS", actions)
    assert np.isclose(result.open_return.iloc[1], .02)
    assert np.isclose(result.high_return.iloc[1], .04)


def test_stop_gap_through_is_conservative_and_cost_once():
    result = R.stop_exit(path_frame([0, -.02], [.001, -.01], [-.001, -.03]), .01, .05)
    assert result["triggered"] and result["gap_through"] and np.isclose(result["net20"], -.022)
    touch = R.stop_exit(path_frame([0], [.01], [-.011]), .01, .05)
    assert touch["triggered"] and not touch["gap_through"] and np.isclose(touch["net20"], -.012)


def test_no_stop_returns_frozen_original_net20():
    result = R.stop_exit(path_frame([0, .01], [.01, .02], [-.001, -.002]), .01, .007)
    assert not result["triggered"] and result["net20"] == .007


def test_payoff_metrics_and_profit_factor_are_exact():
    metrics = R.payoff_metrics(pd.Series([.02, .01, -.01, -.02]))
    assert metrics["signal_count"] == 4 and metrics["win_rate"] == .5
    assert np.isclose(metrics["profit_factor"], 1.0) and metrics["large_loss_2pct_count"] == 1


def test_direction_translation_uses_frozen_event_state_not_rescoring():
    frame = pd.DataFrame({"event_state": ["FAVORABLE_FIRST", "FAVORABLE_FIRST", "ADVERSE_FIRST", "NO_EVENT"],
                          "original_net20": [.01, -.01, .02, -.02]})
    result = R.direction_translation(frame)
    assert result["DIRECTION_CORRECT_TRADE_WIN_COUNT"] == 1
    assert result["DIRECTION_CORRECT_TRADE_LOSS_COUNT"] == 1
    assert result["DIRECTION_WRONG_TRADE_WIN_COUNT"] == 1


def test_classification_priority_is_fixed_and_not_best_rule_selection():
    horizons = pd.DataFrame({"direction": ["ALL"] * 6, "horizon": ["5M", "10M", "15M", "30M", "60M", "ORIGINAL"],
                             "mean_net20": [.01, .005, .001, -.001, -.002, -.005]})
    reversal = {"LOSER_MFE_GE_050_RATE": .5}; mapping = {"UNDERLYING_DIRECTION_CORRECT_RATE": .6, "UNDERLYING_CORRECT_BUT_ETF_LOSS_RATE": .4}
    stops = pd.DataFrame({"direction": ["ALL"], "baseline_to_stop_mean_delta": [.003], "mean_loss_abs_reduction": [.3], "baseline_to_stop_pf_delta": [.3]})
    classification, flags, _ = R.choose_classification(horizons, reversal, mapping, stops)
    assert classification == "A_PATH_REVERSAL_MECHANISM_PRESENT" and all(flags.values())


def test_frozen_lineage_hashes_and_storage():
    assert R.sha256(R.R28_LEDGER) == R.EXPECTED["R28_LEDGER"]
    assert R.sha256(R.ACTION_LEDGER) == R.EXPECTED["ACTION_LEDGER"]
    assert R.sha256(R.ETF_MANIFEST) == R.EXPECTED["ETF_MANIFEST"]
    assert R.RESULTS_ROOT == Path(r"D:\us-tech-quant-results") and not (R.SOURCE_ROOT / "results").exists()


def test_no_ml_search_take_profit_or_prospective_final_paths():
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in (
        "sklearn",
        "HistGradientBoosting",
        "GridSearchCV",
        "RandomizedSearchCV",
        "TAKE_PROFIT_LEVELS",
        "take_profit_exit",
    ):
        assert forbidden not in source
    assert '"MODEL_FIT_COUNT": 0' in source and '"MODEL_PREDICT_CALL_COUNT": 0' in source
    assert '"PROSPECTIVE_DATA_USED": False' in source and '"FINAL_CONFIRMATION_DATA_USED": False' in source
