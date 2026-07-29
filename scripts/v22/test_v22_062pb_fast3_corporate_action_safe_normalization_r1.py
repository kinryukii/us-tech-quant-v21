from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import v22_062pb_fast3_corporate_action_safe_normalization_r1 as mod


def valid_p():
    return {
        "final_status": "PASS",
        "final_decision": "NO_PREMARKET_BASELINE_CANDIDATE_QUALIFIED",
        "v22_062n_validated": True,
        "v22_056_validated": True,
        "session_name": "PREMARKET",
        "maximum_entries_per_session": 1,
        "entry_timing": "EXACT_NEXT_MINUTE_OPEN",
        "tradability_proxy_used": True,
        "bid_ask_spread_available": False,
        "order_book_depth_available": False,
        "vix_entry_gate_used": False,
        "vix_risk_scaling_used": False,
        "parameter_sweep_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "new_market_data_cache_created": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
        "canonical_partition_count_indexed": 582,
        "supported_exit_variants_for_replication": [],
    }


def valid_pa():
    return {
        "final_status": "PASS",
        "final_decision": "PREMARKET_RESULT_BLOCKED_BY_EXTREME_RETURN_DATA_ANOMALY",
        "v22_062p_validated": True,
        "mechanical_anomaly_trade_count": 2,
        "full_582_partition_reread": False,
        "strategy_backtest_executed": False,
        "signal_regeneration_executed": False,
        "parameter_sweep_executed": False,
        "threshold_optimization_executed": False,
        "corporate_action_data_downloaded": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "new_market_data_cache_created": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
        "next_stage": "V22.062PB_FAST3_CORPORATE_ACTION_SAFE_PRICE_NORMALIZATION_R1",
    }


def split_frame() -> pd.DataFrame:
    ts = pd.date_range("2025-01-02 10:00", periods=6, freq="min", tz="UTC")
    close = np.array([100.0, 101.0, 102.0, 10.3, 10.4, 10.5])
    return pd.DataFrame({
        "timestamp_utc": ts,
        "open": close,
        "high": close + 0.1,
        "low": close - 0.1,
        "close": close,
        "volume": 100.0,
    })


def reverse_split_frame() -> pd.DataFrame:
    ts = pd.date_range("2025-01-02 10:00", periods=5, freq="min", tz="UTC")
    close = np.array([10.0, 10.1, 101.0, 102.0, 103.0])
    return pd.DataFrame({
        "timestamp_utc": ts,
        "open": close,
        "high": close + 0.1,
        "low": close - 0.1,
        "close": close,
        "volume": 100.0,
    })


def test_validate_p():
    mod.validate_p(valid_p())


def test_validate_p_rejects():
    summary = valid_p()
    summary["vix_entry_gate_used"] = True
    with pytest.raises(mod.StudyError):
        mod.validate_p(summary)


def test_validate_pa():
    mod.validate_pa(valid_pa())


def test_validate_pa_requires_anomaly():
    summary = valid_pa()
    summary["mechanical_anomaly_trade_count"] = 0
    with pytest.raises(mod.StudyError):
        mod.validate_pa(summary)


def test_path_parse():
    path = mod.Path("x") / "symbol=US.SOXL" / "year=2025" / "month=7" / "a.parquet"
    assert mod.symbol_month_from_path(path) == ("SOXL", "2025", "07")


def test_previous_month():
    assert mod.previous_month(2025, 1) == ("2024", "12")


def test_snap_factor_forward():
    factor, error = mod.snap_factor(10.0)
    assert factor == pytest.approx(10.0)
    assert error == pytest.approx(0.0)


def test_snap_factor_reverse():
    factor, _ = mod.snap_factor(0.1)
    assert factor == pytest.approx(0.1)


def test_snap_factor_rejects():
    assert mod.snap_factor(1.35) is None


def test_normalize_forward_split():
    frame, events, unresolved = mod.normalize_scale(split_frame())
    assert len(events) == 1
    assert not unresolved
    assert frame.loc[3, "normalized_open"] == pytest.approx(103.0, rel=0.03)


def test_normalize_reverse_split():
    frame, events, unresolved = mod.normalize_scale(reverse_split_frame())
    assert len(events) == 1
    assert not unresolved
    assert frame.loc[2, "normalized_open"] == pytest.approx(10.1, rel=0.03)


def test_unresolved_jump():
    frame = split_frame().copy()
    frame.loc[3:, ["open", "high", "low", "close"]] *= 1.35
    _, _, unresolved = mod.normalize_scale(frame)
    assert unresolved


def test_profit_factor():
    assert mod.profit_factor(pd.Series([0.02, 0.01, -0.01])) == pytest.approx(3.0)


def test_positive_share():
    assert mod.positive_share(pd.Series([0.8, 0.1, 0.1, -0.1]), 1) == pytest.approx(0.8)


def test_cumulative_return():
    assert mod.cumulative_return(pd.Series([0.10, -0.10])) == pytest.approx(-0.01)


def test_maximum_drawdown():
    assert mod.maximum_drawdown(pd.Series([0.10, -0.20, 0.10])) == pytest.approx(-0.20)


def test_choose_unresolved():
    repairs = pd.DataFrame({"quarantined": [True, False]})
    qual = pd.DataFrame({
        "exit_variant": list(mod.EXIT_VARIANTS),
        "research_candidate_for_replication": [False, False, False],
    })
    decision, next_stage, supported = mod.choose_decision(repairs, qual)
    assert "INCOMPLETE" in decision
    assert "OFFICIAL_CORPORATE_ACTION" in next_stage
    assert supported == []


def test_choose_supported():
    repairs = pd.DataFrame({"quarantined": [False]})
    qual = pd.DataFrame({
        "exit_variant": list(mod.EXIT_VARIANTS),
        "research_candidate_for_replication": [False, True, False],
    })
    decision, next_stage, supported = mod.choose_decision(repairs, qual)
    assert "REQUIRES_INDEPENDENT_REPLICATION" in decision
    assert "REPLICATION" in next_stage
    assert supported == ["FIXED_60M"]


def test_choose_no_edge():
    repairs = pd.DataFrame({"quarantined": [False]})
    qual = pd.DataFrame({
        "exit_variant": list(mod.EXIT_VARIANTS),
        "research_candidate_for_replication": [False, False, False],
    })
    decision, next_stage, supported = mod.choose_decision(repairs, qual)
    assert decision == "PREMARKET_CORPORATE_ACTION_SAFE_EDGE_NOT_SUPPORTED"
    assert "AFTER_HOURS" in next_stage
    assert supported == []


def test_default_paths():
    args = mod.parse_args(["--execute"])
    assert "V22.062P_FAST3" in args.v22_062p_root
    assert "V22.062PA_FAST3" in args.v22_062pa_root
    assert "V22.062PB_FAST3" in args.result_dir


def test_policy_constants():
    assert mod.JUMP_THRESHOLD == 0.20
    assert mod.FACTOR_TOLERANCE == 0.03
    assert mod.EXTREME_RETURN_LIMIT == 0.25
    assert 10.0 in mod.ALLOWED_FACTORS
