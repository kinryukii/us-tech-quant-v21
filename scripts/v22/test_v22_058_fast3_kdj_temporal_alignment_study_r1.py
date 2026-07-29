from __future__ import annotations

import math
import numpy as np
import pandas as pd
import pytest

import v22_058_fast3_kdj_temporal_alignment_study_r1 as mod


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


def valid_057():
    return {
        "final_status": "PASS",
        "final_decision": "NO_MULTIFACT_CORE_CANDIDATE_QUALIFIED",
        "v22_056_validated": True,
        "vix_mode": "PRIOR_DAY_OFFICIAL_CBOE_ONLY",
        "intraday_vix_used": False,
        "vix_proxy_used": False,
        "core_qualified_for_replication": False,
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
    }


def test_validate_056_accepts():
    mod.validate_v22_056(valid_056())


def test_validate_057_accepts():
    mod.validate_v22_057(valid_057())


def test_validate_057_rejects_qualified_lineage():
    payload = valid_057()
    payload["core_qualified_for_replication"] = True
    with pytest.raises(mod.StudyError):
        mod.validate_v22_057(payload)


def test_study_periods():
    assert mod.study_period(2018) == "2018-2022_DEVELOPMENT"
    assert mod.study_period(2024) == "2023-2024_VALIDATION"
    assert mod.study_period(2026) == "2025-2026_YTD_CONFIRMATION"


def test_rsi_uptrend_high():
    close = pd.Series(np.arange(1.0, 40.0))
    assert mod.rsi_wilder(close).dropna().iloc[-1] == pytest.approx(100.0)


def test_kdj_finite():
    frame = pd.DataFrame({
        "high": np.arange(1.0, 31.0) + 1,
        "low": np.arange(1.0, 31.0) - 1,
        "close": np.arange(1.0, 31.0),
    })
    k, d, j = mod.kdj(frame)
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


def long_gate_row(*, strict: bool, recent: bool) -> pd.Series:
    return pd.Series({
        "qqq_rsi_prior3_in_long_zone": True,
        "qqq_rsi_prior3_min": 45.0,
        "qqq_rsi_prev1": 51.0,
        "qqq_rsi14": 54.0,
        "qqq_kdj_long_cross": strict,
        "qqq_kdj_long_cross_recent3": recent,
        "qqq_kdj_k": 60.0,
        "qqq_kdj_d": 55.0,
        "qqq_kdj_j": 70.0,
        "qqq_j_prev1": 65.0,
        "qqq_two_consecutive_below_vwap_prior3": False,
        "qqq_close": 101.0,
        "qqq_vwap": 100.0,
        "qqq_previous_high": 100.5,
        "qqq_macd_dif": 1.0,
        "qqq_macd_dea": 0.8,
        "qqq_macd_hist": 0.3,
        "qqq_hist_prev1": 0.2,
    })


def short_gate_row(*, strict: bool, recent: bool) -> pd.Series:
    return pd.Series({
        "soxx_rsi_prior3_in_short_zone": True,
        "soxx_rsi_prev1": 50.0,
        "soxx_rsi14": 45.0,
        "soxx_kdj_short_cross": strict,
        "soxx_kdj_short_cross_recent3": recent,
        "soxx_kdj_k": 40.0,
        "soxx_kdj_d": 45.0,
        "soxx_kdj_j": 30.0,
        "soxx_j_prev1": 35.0,
        "soxx_two_consecutive_above_vwap_prior3": False,
        "soxx_close": 99.0,
        "soxx_vwap": 100.0,
        "soxx_previous_low": 99.5,
        "soxx_macd_dif": -1.0,
        "soxx_macd_dea": -0.8,
        "soxx_macd_hist": -0.3,
        "soxx_hist_prev1": -0.2,
    })


def test_recent_long_gate_allows_prior_cross():
    gates = mod.entry_component_gates(
        long_gate_row(strict=False, recent=True), "LONG", "qqq"
    )
    assert gates["rsi"] is True
    assert gates["price"] is True
    assert gates["kdj_strict"] is False
    assert gates["kdj_recent3"] is True


def test_strict_long_gate_is_subset_of_recent():
    gates = mod.entry_component_gates(
        long_gate_row(strict=True, recent=True), "LONG", "qqq"
    )
    assert gates["kdj_strict"] is True
    assert gates["kdj_recent3"] is True


def test_recent_short_gate_allows_prior_cross():
    gates = mod.entry_component_gates(
        short_gate_row(strict=False, recent=True), "SHORT", "soxx"
    )
    assert gates["rsi"] is True
    assert gates["price"] is True
    assert gates["kdj_strict"] is False
    assert gates["kdj_recent3"] is True


def test_candidate_masks():
    frame = pd.DataFrame({
        "strict_same_bar_kdj_signal": [True, False, False],
        "recent_3bar_kdj_signal": [True, True, False],
        "no_kdj_control_signal": [True, True, True],
    })
    assert mod.candidate_mask(frame, "STRICT_SAME_BAR_KDJ").tolist() == [True, False, False]
    assert mod.candidate_mask(frame, "RECENT_3BAR_KDJ").tolist() == [True, True, False]
    assert mod.candidate_mask(frame, "NO_KDJ_CONTROL").tolist() == [True, True, True]


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
    values = pd.Series([0.02, -0.01, 0.01, -0.01])
    assert mod.profit_factor(values) == pytest.approx(1.5)


def test_max_drawdown():
    assert mod.max_drawdown(pd.Series([0.10, -0.20, 0.10])) == pytest.approx(-0.20)


def period_frame(recent_count=120, no_kdj_count=150, positive=True):
    rows = []
    counts = {
        "STRICT_SAME_BAR_KDJ": (10, 3, 4),
        "RECENT_3BAR_KDJ": (recent_count - 70, 35, 35),
        "NO_KDJ_CONTROL": (no_kdj_count - 80, 40, 40),
    }
    periods = [
        "2018-2022_DEVELOPMENT",
        "2023-2024_VALIDATION",
        "2025-2026_YTD_CONFIRMATION",
    ]
    for variant, variant_counts in counts.items():
        for period, count in zip(periods, variant_counts):
            mean = 0.001 if positive else -0.001
            if variant == "NO_KDJ_CONTROL":
                mean = 0.0005 if positive else -0.0005
            rows.append({
                "variant": variant,
                "study_period": period,
                "trade_count": count,
                "mean_instrument_net_return": mean,
                "median_instrument_net_return": mean / 2,
                "profit_factor": 1.2 if positive else 0.8,
                "mean_entry_excess_pit_60m": mean / 2,
            })
    return pd.DataFrame(rows)


def year_frame():
    rows = []
    for variant in mod.VARIANTS:
        for year in range(2018, 2027):
            rows.append({
                "variant": variant,
                "calendar_year": year,
                "cumulative_return": 0.01,
            })
    return pd.DataFrame(rows)


def test_qualification_sample_gate():
    result = mod.qualification(period_frame(), year_frame())
    recent = result.loc[result["variant"] == "RECENT_3BAR_KDJ"].iloc[0]
    assert bool(recent["sample_evaluable"]) is True
    assert bool(recent["research_candidate_for_next_stage"]) is True


def test_choose_recent3_supported_when_incremental():
    result = mod.qualification(period_frame(), year_frame())
    decision, supported = mod.choose_final_decision(result)
    assert decision == "RECENT_3BAR_KDJ_SUPPORTED_FOR_INDEPENDENT_REPLICATION"
    assert supported is True


def test_choose_recent3_insufficient_sample():
    result = mod.qualification(period_frame(recent_count=80), year_frame())
    decision, supported = mod.choose_final_decision(result)
    assert decision == "RECENT_3BAR_KDJ_INCONCLUSIVE_INSUFFICIENT_SAMPLE"
    assert supported is False


def test_block_bootstrap_short_nan():
    low, high = mod.block_bootstrap_mean_ci(pd.Series([0.1] * 5))
    assert math.isnan(low) and math.isnan(high)


def test_constants_frozen():
    assert mod.KDJ_RECENT_BARS == 3
    assert mod.MIN_FULL_HISTORY_TRADES == 100
    assert mod.MIN_VALIDATION_TRADES == 30
    assert mod.MIN_CONFIRMATION_TRADES == 30
    assert mod.RSZ_THRESHOLD == 0.25


def test_default_paths():
    args = mod.parse_args(["--execute"])
    assert "V22.057_FAST3_MULTIFACT" in args.v22_057_summary
    assert "V22.056_FAST3_CBOE" in args.v22_056_summary
    assert "vix_prior_day_regime_features.parquet" in args.vix_feature_path
    assert "V22.058_FAST3_KDJ_TEMPORAL_ALIGNMENT" in args.result_dir

def test_boolean_ndarray_and_add_factors_np_select_regression():
    nullable = pd.Series([True, pd.NA, False], dtype="boolean")
    converted = mod.boolean_ndarray(nullable.shift(1))
    assert converted.dtype == np.bool_
    assert converted.tolist() == [False, True, False]

    rows = 90
    timestamp = pd.date_range(
        "2026-01-05 14:30:00+00:00",
        periods=rows,
        freq="5min",
    )
    close = 100.0 + np.sin(np.arange(rows) / 4.0) + np.arange(rows) * 0.01
    bars = pd.DataFrame(
        {
            "timestamp_utc": timestamp,
            "timestamp_et": timestamp.tz_convert("America/New_York"),
            "trade_date": ["2026-01-05"] * rows,
            "open": close - 0.05,
            "high": close + 0.20,
            "low": close - 0.20,
            "close": close,
            "volume": np.full(rows, 1000.0),
            "vwap": 100.0 + np.arange(rows) * 0.005,
        }
    )

    result = mod.add_factors(bars)
    assert len(result) == rows
    assert "kdj_long_cross_age3" in result.columns
    assert "kdj_short_cross_age3" in result.columns
    assert result["kdj_long_cross_age3"].dropna().isin([0.0, 1.0, 2.0]).all()
    assert result["kdj_short_cross_age3"].dropna().isin([0.0, 1.0, 2.0]).all()
