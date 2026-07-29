from __future__ import annotations

import math
import numpy as np
import pandas as pd
import pytest

import v22_057_fast3_multifactor_state_machine_backtest_r1 as mod


def valid_056():
    return {
        "final_status": "PASS",
        "final_decision": "OFFICIAL_CBOE_DAILY_VIX_READY_FOR_PRIOR_DAY_REGIME_FILTER",
        "v22_055_validated": True,
        "prior_day_shift_validated": True,
        "daily_vix_regime_ready": True,
        "intraday_vix_data_ready": False,
        "intraday_vix_features_allowed": False,
        "vix_proxy_substitution_used": False,
        "data_ready_for_daily_vix_multifactor_backtest": True,
        "multifactor_backtest_executed": False,
        "parameter_sweep_executed": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }


def test_validate_056_accepts():
    mod.validate_v22_056(valid_056())


def test_validate_056_rejects_proxy():
    payload = valid_056()
    payload["vix_proxy_substitution_used"] = True
    with pytest.raises(mod.StudyError):
        mod.validate_v22_056(payload)


def test_study_periods():
    assert mod.study_period(2018) == "2018-2022_DEVELOPMENT"
    assert mod.study_period(2024) == "2023-2024_VALIDATION"
    assert mod.study_period(2026) == "2025-2026_YTD_CONFIRMATION"


def test_rsi_uptrend_high():
    close = pd.Series(np.arange(1.0, 40.0))
    assert mod.rsi_wilder(close).dropna().iloc[-1] == pytest.approx(100.0)


def test_kdj_shape_and_finite():
    frame = pd.DataFrame({
        "high": np.arange(1.0, 31.0) + 1,
        "low": np.arange(1.0, 31.0) - 1,
        "close": np.arange(1.0, 31.0),
    })
    k, d, j = mod.kdj(frame)
    assert len(k) == len(frame)
    assert np.isfinite(k.iloc[-1])
    assert np.isfinite(d.iloc[-1])
    assert np.isfinite(j.iloc[-1])


def test_atr_positive():
    frame = pd.DataFrame({
        "high": np.arange(1.0, 40.0) + 1,
        "low": np.arange(1.0, 40.0) - 1,
        "close": np.arange(1.0, 40.0),
    })
    assert mod.atr_wilder(frame).dropna().iloc[-1] > 0


def test_rsz_selection_long():
    assert mod.selected_prefix_and_execution("LONG", 0.3) == ("soxx", "SOXL")
    assert mod.selected_prefix_and_execution("LONG", -0.3) == ("qqq", "TQQQ")
    assert mod.selected_prefix_and_execution("LONG", 0.1) is None


def test_rsz_selection_short():
    assert mod.selected_prefix_and_execution("SHORT", -0.3) == ("soxx", "SOXS")
    assert mod.selected_prefix_and_execution("SHORT", 0.3) == ("qqq", "SQQQ")


def test_running_stats():
    stats = mod.RunningStats()
    stats.add(0.1)
    stats.add(0.2)
    assert stats.count == 2
    assert stats.mean == pytest.approx(0.15)


def test_profit_factor():
    values = pd.Series([0.02, -0.01, 0.01, -0.01])
    assert mod.profit_factor(values) == pytest.approx(1.5)


def test_max_drawdown():
    values = pd.Series([0.10, -0.20, 0.10])
    assert mod.max_drawdown(values) == pytest.approx(-0.20)


def test_fill_exit_gap_below_stop():
    bar = pd.Series({"open": 95.0})
    assert mod.fill_exit_price(bar, 97.0) == 95.0


def test_fill_exit_at_trigger_when_open_above():
    bar = pd.Series({"open": 99.0})
    assert mod.fill_exit_price(bar, 97.0) == 97.0


def test_candidate_masks():
    frame = pd.DataFrame({
        "core_signal": [True, False],
        "no_vix_signal": [True, True],
        "no_kdj_signal": [False, True],
    })
    assert mod.candidate_mask(frame, "CORE_FULL").tolist() == [True, False]
    assert mod.candidate_mask(frame, "ABLATION_NO_VIX").tolist() == [True, True]
    assert mod.candidate_mask(frame, "ABLATION_NO_KDJ").tolist() == [False, True]


def test_unconditional_60m_sample_cost():
    timestamp = pd.date_range("2026-01-05 14:55:00+00:00", periods=61, freq="min")
    minute = pd.DataFrame({
        "timestamp_utc": timestamp,
        "timestamp_et": timestamp.tz_convert("America/New_York"),
        "minute_et": np.arange(595, 656),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 101.0,
    })
    samples = mod.unconditional_60m_samples(minute)
    assert len(samples) >= 1
    expected = (101.0 * (1 - mod.EXIT_COST)) / (100.0 * (1 + mod.ENTRY_COST)) - 1
    assert samples[0][1] == pytest.approx(expected)


def test_block_bootstrap_too_short_nan():
    low, high = mod.block_bootstrap_mean_ci(pd.Series([0.1] * 5))
    assert math.isnan(low) and math.isnan(high)


def test_constants_frozen():
    assert mod.RSZ_THRESHOLD == 0.25
    assert mod.RISK_PER_TRADE == 0.0025
    assert mod.MAX_WEIGHT == 0.33
    assert mod.MAX_TRADES_PER_DAY == 3
    assert mod.MAX_STOP_EXITS_PER_DAY == 2


def test_default_paths():
    args = mod.parse_args(["--execute"])
    assert "V22.056_FAST3_CBOE" in args.v22_056_summary
    assert "vix_prior_day_regime_features.parquet" in args.vix_feature_path
    assert "moomoo_24h_1m" in args.canonical_root
    assert "V22.057_FAST3_MULTIFACT" in args.result_dir
