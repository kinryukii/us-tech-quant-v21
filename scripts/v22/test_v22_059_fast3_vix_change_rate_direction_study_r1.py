from __future__ import annotations

import math
import numpy as np
import pandas as pd
import pytest

import v22_059_fast3_vix_change_rate_direction_study_r1 as mod


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


def valid_058():
    return {
        "final_status": "PASS",
        "final_decision": "RECENT_3BAR_KDJ_INCONCLUSIVE_INSUFFICIENT_SAMPLE",
        "v22_057_validated": True,
        "v22_056_validated": True,
        "vix_mode": "PRIOR_DAY_OFFICIAL_CBOE_ONLY",
        "intraday_vix_used": False,
        "vix_proxy_used": False,
        "recent3_kdj_supported_for_replication": False,
        "kdj_temporal_alignment_executed": True,
        "parameter_sweep_executed": False,
        "entry_threshold_optimization_executed": False,
        "exit_threshold_optimization_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "open_d_called": False,
        "history_download_executed": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
        "candidate_signal_count_by_variant": {"NO_KDJ_CONTROL": 173},
        "trade_count_by_variant": {"NO_KDJ_CONTROL": 168},
    }


def valid_058a():
    return {
        "final_status": "PASS",
        "source_v22_058_status": "PASS",
        "source_variant": "NO_KDJ_CONTROL",
        "canonical_partitions_read": 0,
        "backtest_executed": False,
        "parameter_sweep_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
    }


def test_lineage_validators_accept():
    mod.validate_v22_056(valid_056())
    mod.validate_v22_058(valid_058())
    mod.validate_v22_058a(valid_058a())


def test_v22_058_rejects_missing_no_kdj_count():
    payload = valid_058()
    payload["trade_count_by_variant"] = {}
    with pytest.raises(mod.StudyError):
        mod.validate_v22_058(payload)


def test_study_periods():
    assert mod.study_period(2018) == "2018-2022_DEVELOPMENT"
    assert mod.study_period(2024) == "2023-2024_VALIDATION"
    assert mod.study_period(2026) == "2025-2026_YTD_CONFIRMATION"


def test_rsi_uptrend_high():
    close = pd.Series(np.arange(1.0, 40.0))
    assert mod.rsi_wilder(close).dropna().iloc[-1] == pytest.approx(100.0)


def test_kdj_calculation_remains_available_but_not_a_variant():
    frame = pd.DataFrame({
        "high": np.arange(1.0, 31.0) + 1,
        "low": np.arange(1.0, 31.0) - 1,
        "close": np.arange(1.0, 31.0),
    })
    k, d, j = mod.kdj(frame)
    assert np.isfinite(k.iloc[-1]) and np.isfinite(d.iloc[-1]) and np.isfinite(j.iloc[-1])
    assert all("KDJ" not in variant for variant in mod.VARIANTS)


def test_rolling_prior_percentile_no_current_leakage():
    values = pd.Series(np.arange(300, dtype=float))
    out = mod.rolling_prior_percentile(values, window=252)
    assert out.iloc[:253].isna().all()
    assert out.iloc[253] == pytest.approx(1.0)


def rate_row(rate1, rate3, pctl=0.50, old_long=True, old_short=True):
    return pd.Series({
        "vix_rate_1d_prior": rate1,
        "vix_rate_3d_prior": rate3,
        "vix_rate_1d_pctl_252_prior": pctl,
        "vix_positive_shock_prior": bool(rate1 > 0 and pctl >= mod.VIX_RATE_SHOCK_PERCENTILE),
        "vix_long_regime_allowed_p80": old_long,
        "vix_short_regime_elevated_p50": old_short,
    })


def test_vix_no_control_allows_both():
    row = rate_row(0.10, 0.20, pctl=0.99)
    assert mod.vix_variant_allowed(row, "LONG", "NO_VIX_CONTROL") is True
    assert mod.vix_variant_allowed(row, "SHORT", "NO_VIX_CONTROL") is True


def test_old_level_comparator():
    row = rate_row(-0.01, -0.02, old_long=True, old_short=False)
    assert mod.vix_variant_allowed(row, "LONG", "OLD_LEVEL_VIX_CONTROL") is True
    assert mod.vix_variant_allowed(row, "SHORT", "OLD_LEVEL_VIX_CONTROL") is False


def test_vix_rate_1d_direction():
    down = rate_row(-0.01, 0.02)
    up = rate_row(0.01, -0.02)
    assert mod.vix_variant_allowed(down, "LONG", "VIX_RATE_1D") is True
    assert mod.vix_variant_allowed(down, "SHORT", "VIX_RATE_1D") is False
    assert mod.vix_variant_allowed(up, "SHORT", "VIX_RATE_1D") is True
    assert mod.vix_variant_allowed(up, "LONG", "VIX_RATE_1D") is False


def test_vix_rate_1d_3d_confirmation():
    assert mod.vix_variant_allowed(rate_row(-0.01, -0.02), "LONG", "VIX_RATE_1D_3D_CONFIRM") is True
    assert mod.vix_variant_allowed(rate_row(0.01, 0.02), "SHORT", "VIX_RATE_1D_3D_CONFIRM") is True
    assert mod.vix_variant_allowed(rate_row(-0.01, 0.02), "LONG", "VIX_RATE_1D_3D_CONFIRM") is False
    assert mod.vix_variant_allowed(rate_row(0.01, -0.02), "SHORT", "VIX_RATE_1D_3D_CONFIRM") is False


def test_positive_shock_blocks_rate_variants():
    row = rate_row(0.08, 0.12, pctl=0.99)
    assert mod.vix_variant_allowed(row, "SHORT", "VIX_RATE_1D") is False
    assert mod.vix_variant_allowed(row, "SHORT", "VIX_RATE_1D_3D_CONFIRM") is False


def test_negative_vix_move_not_positive_shock():
    row = rate_row(-0.08, -0.12, pctl=0.99)
    assert row["vix_positive_shock_prior"] is False
    assert mod.vix_variant_allowed(row, "LONG", "VIX_RATE_1D_3D_CONFIRM") is True


def test_candidate_masks():
    frame = pd.DataFrame({
        "no_vix_control_signal": [True, False],
        "old_level_vix_control_signal": [True, True],
        "vix_rate_1d_signal": [False, True],
        "vix_rate_1d_3d_confirm_signal": [False, False],
    })
    assert mod.candidate_mask(frame, "NO_VIX_CONTROL").tolist() == [True, False]
    assert mod.candidate_mask(frame, "OLD_LEVEL_VIX_CONTROL").tolist() == [True, True]
    assert mod.candidate_mask(frame, "VIX_RATE_1D").tolist() == [False, True]


def test_rsz_selection():
    assert mod.selected_prefix_and_execution("LONG", 0.3) == ("soxx", "SOXL")
    assert mod.selected_prefix_and_execution("LONG", -0.3) == ("qqq", "TQQQ")
    assert mod.selected_prefix_and_execution("SHORT", -0.3) == ("soxx", "SOXS")
    assert mod.selected_prefix_and_execution("SHORT", 0.3) == ("qqq", "SQQQ")


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
    expected = (101.0 * (1 - mod.EXIT_COST)) / (100.0 * (1 + mod.ENTRY_COST)) - 1
    assert samples[0][1] == pytest.approx(expected)


def test_profit_factor():
    assert mod.profit_factor(pd.Series([0.02, -0.01, 0.01, -0.01])) == pytest.approx(1.5)


def test_max_drawdown():
    assert mod.max_drawdown(pd.Series([0.10, -0.20, 0.10])) == pytest.approx(-0.20)


def period_frame(candidate_variant=None, small=False):
    rows = []
    periods = ["2018-2022_DEVELOPMENT", "2023-2024_VALIDATION", "2025-2026_YTD_CONFIRMATION"]
    for variant in mod.VARIANTS:
        counts = [80, 40, 40]
        if small and variant == candidate_variant:
            counts = [20, 10, 10]
        for period, count in zip(periods, counts):
            good = variant == candidate_variant
            rows.append({
                "variant": variant,
                "study_period": period,
                "trade_count": count,
                "mean_instrument_net_return": 0.001 if good else -0.001,
                "median_instrument_net_return": 0.0005 if good else -0.0005,
                "profit_factor": 1.2 if good else 0.8,
                "mean_entry_excess_pit_60m": 0.0004 if good else -0.0004,
            })
    return pd.DataFrame(rows)


def year_frame():
    return pd.DataFrame([
        {"variant": variant, "calendar_year": year, "cumulative_return": 0.01}
        for variant in mod.VARIANTS for year in range(2018, 2027)
    ])


def test_qualification_candidate():
    result = mod.qualification(period_frame("VIX_RATE_1D_3D_CONFIRM"), year_frame())
    row = result.loc[result["variant"] == "VIX_RATE_1D_3D_CONFIRM"].iloc[0]
    assert bool(row["sample_evaluable"]) is True
    assert bool(row["research_candidate_for_next_stage"]) is True


def test_choose_prefers_1d3d():
    result = mod.qualification(period_frame("VIX_RATE_1D_3D_CONFIRM"), year_frame())
    decision, variant = mod.choose_final_decision(result)
    assert decision == "VIX_RATE_1D_3D_CONFIRM_SUPPORTED_FOR_INDEPENDENT_REPLICATION"
    assert variant == "VIX_RATE_1D_3D_CONFIRM"


def test_choose_insufficient_sample():
    result = mod.qualification(period_frame("VIX_RATE_1D", small=True), year_frame())
    decision, variant = mod.choose_final_decision(result)
    assert decision == "VIX_CHANGE_RATE_INCONCLUSIVE_INSUFFICIENT_SAMPLE"
    assert variant == "VIX_RATE_1D"


def test_block_bootstrap_short_nan():
    low, high = mod.block_bootstrap_mean_ci(pd.Series([0.1] * 5))
    assert math.isnan(low) and math.isnan(high)


def test_constants_frozen():
    assert mod.VIX_RATE_SHOCK_PERCENTILE == 0.95
    assert mod.MIN_FULL_HISTORY_TRADES == 100
    assert mod.MIN_VALIDATION_TRADES == 30
    assert mod.MIN_CONFIRMATION_TRADES == 30
    assert mod.RSZ_THRESHOLD == 0.25


def test_default_paths():
    args = mod.parse_args(["--execute"])
    assert "V22.058_FAST3" in args.v22_058_summary
    assert "V22.058A_NO_KDJ" in args.v22_058a_summary
    assert "V22.056_FAST3_CBOE" in args.v22_056_summary
    assert "vix_daily.parquet" in args.vix_daily_path
    assert "V22.059_FAST3_VIX_CHANGE_RATE" in args.result_dir


def test_boolean_ndarray_regression():
    nullable = pd.Series([True, pd.NA, False], dtype="boolean")
    converted = mod.boolean_ndarray(nullable.shift(1))
    assert converted.dtype == np.bool_
    assert converted.tolist() == [False, True, False]



def test_add_factors_builds_without_kdj_signal_use():
    rows = 90
    timestamp = pd.date_range("2026-01-05 14:30:00+00:00", periods=rows, freq="5min")
    close = 100.0 + np.sin(np.arange(rows) / 4.0) + np.arange(rows) * 0.01
    bars = pd.DataFrame({
        "timestamp_utc": timestamp,
        "timestamp_et": timestamp.tz_convert("America/New_York"),
        "trade_date": ["2026-01-05"] * rows,
        "open": close - 0.05,
        "high": close + 0.20,
        "low": close - 0.20,
        "close": close,
        "volume": np.full(rows, 1000.0),
        "vwap": 100.0 + np.arange(rows) * 0.005,
    })
    result = mod.add_factors(bars)
    assert len(result) == rows
    assert "kdj_long_cross_recent3" in result.columns
    assert all("KDJ" not in variant for variant in mod.VARIANTS)
