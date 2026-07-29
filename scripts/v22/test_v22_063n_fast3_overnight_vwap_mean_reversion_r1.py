from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import v22_063n_fast3_overnight_vwap_mean_reversion_r1 as mod


def valid_062n():
    return {
        "final_status": "PASS",
        "final_decision": "NO_OVERNIGHT_BASELINE_CANDIDATE_QUALIFIED",
        "session_name": "OVERNIGHT",
        "supported_exit_variants_for_replication": [],
        "canonical_partition_count_indexed": 582,
        "parameter_sweep_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "new_market_data_cache_created": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }


def valid_062pr():
    return {
        "final_status": "PASS",
        "v22_062pb_validated": True,
        "research_cutoff_date": "2026-07-24",
        "forward_holdout_only": True,
        "rule_change_requires_reset": True,
        "sole_exit_variant": "PREMARKET_0925",
        "historical_pre_cutoff_outcomes_used_for_qualification": False,
        "parameter_sweep_executed": False,
        "threshold_optimization_executed": False,
        "strategy_rule_change_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "new_market_data_cache_created": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }


def valid_063r1():
    return {
        "final_status": "PASS",
        "final_decision": "NO_RTH_VWAP_MEAN_REVERSION_CANDIDATE_QUALIFIED",
        "v22_061_validated": True,
        "v22_062pr_validated": True,
        "premarket_forward_chain_modified": False,
        "session_name": "RTH",
        "supported_exit_variants_for_replication": [],
        "parameter_sweep_executed": False,
        "deviation_threshold_sweep_executed": False,
        "signal_window_sweep_executed": False,
        "exit_threshold_optimization_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "new_market_data_cache_created": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }


def synthetic_session(session_date="2026-01-06", base=100.0):
    evening_date = (pd.Timestamp(session_date) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    evening = pd.date_range(f"{evening_date} 20:00", periods=240, freq="min", tz="America/New_York")
    morning = pd.date_range(f"{session_date} 00:00", periods=240, freq="min", tz="America/New_York")
    timestamp = evening.append(morning).tz_convert("UTC")
    close = base + np.arange(480) * 0.001
    return pd.DataFrame(
        {
            "timestamp_utc": timestamp,
            "open": close,
            "high": close + 0.02,
            "low": close - 0.02,
            "close": close,
            "volume": 100.0,
        }
    )


def grid(base=100.0):
    overnight, _, _ = mod.normalize_and_extract_overnight(synthetic_session(base=base))
    return mod.session_grid(overnight)


def forced_long_grids():
    qqq, soxx = grid(100.0), grid(200.0)
    for current, base in ((qqq, 100.0), (soxx, 200.0)):
        current.loc[180:186, "normalized_close"] = np.linspace(base - 4.0, base - 3.0, 7)
        current.loc[180:186, "normalized_open"] = current.loc[180:186, "normalized_close"]
        current.loc[180:186, "normalized_high"] = current.loc[180:186, "normalized_close"] + 0.1
        current.loc[180:186, "normalized_low"] = current.loc[180:186, "normalized_close"] - 0.1
        current.loc[180:186, "ret_5m"] = 0.01
        current.loc[180:186, "normalized_vwap_deviation"] = -2.5
        current.loc[180:186, "prior_high"] = current.loc[180:186, "normalized_close"] - 0.1
        current.loc[180:186, "tradability_proxy_pass"] = True
    return qqq, soxx


def test_validate_lineage():
    mod.validate_v22_062n(valid_062n())
    mod.validate_v22_062pr(valid_062pr())
    mod.validate_v22_063r1(valid_063r1())


def test_lineage_rejects_supported_rth_exit():
    summary = valid_063r1()
    summary["supported_exit_variants_for_replication"] = ["FIXED_30M"]
    with pytest.raises(mod.StudyError):
        mod.validate_v22_063r1(summary)


def test_overnight_mapping():
    overnight, _, _ = mod.normalize_and_extract_overnight(synthetic_session())
    assert len(overnight) == 480
    assert overnight.session_date.nunique() == 1
    assert overnight.session_minute.min() == 0
    assert overnight.session_minute.max() == 479


def test_session_grid():
    current = grid()
    assert len(current) == 480
    assert bool(current.loc[200, "tradability_proxy_pass"])


def test_sparse_proxy_rejected():
    sparse = synthetic_session().iloc[::5].copy()
    overnight, _, _ = mod.normalize_and_extract_overnight(sparse)
    assert not bool(mod.session_grid(overnight).loc[200, "tradability_proxy_pass"])


def test_build_long_candidate():
    qqq, soxx = forced_long_grids()
    candidate, reasons = mod.build_candidate(
        "2026-01-06",
        qqq,
        soxx,
        {"QQQ": pd.DataFrame(), "SOXX": pd.DataFrame()},
        {"QQQ": pd.DataFrame(), "SOXX": pd.DataFrame()},
    )
    assert not reasons
    assert candidate is not None
    assert candidate["direction"] == "LONG"
    assert candidate["execution_symbol"] in {"TQQQ", "SOXL"}


def test_candidate_blocked_by_event():
    qqq, soxx = forced_long_grids()
    events = pd.DataFrame({"timestamp_utc": [pd.Timestamp("2026-01-06 05:00:00+00:00")]})
    candidate, reasons = mod.build_candidate(
        "2026-01-06",
        qqq,
        soxx,
        {"QQQ": events, "SOXX": pd.DataFrame()},
        {"QQQ": pd.DataFrame(), "SOXX": pd.DataFrame()},
    )
    assert candidate is None
    assert any("SCALE_EVENT" in reason for reason in reasons)


def test_exit_minutes():
    qqq, soxx = grid(), grid(200.0)
    assert mod.exit_minute("FIXED_30M", 200, "LONG", qqq, soxx) == 230
    assert mod.exit_minute("FIXED_60M", 200, "LONG", qqq, soxx) == 260


def test_vwap_touch_exit():
    qqq, soxx = grid(), grid(200.0)
    qqq.loc[200:204, "normalized_close"] = qqq.loc[200:204, "vwap"] - 0.1
    soxx.loc[200:204, "normalized_close"] = soxx.loc[200:204, "vwap"] - 0.1
    qqq.loc[205, "normalized_close"] = qqq.loc[205, "vwap"] + 0.1
    soxx.loc[205, "normalized_close"] = soxx.loc[205, "vwap"] + 0.1
    assert mod.exit_minute("DUAL_VWAP_TOUCH_OR_60M", 200, "LONG", qqq, soxx) == 205


def test_return_from_grid():
    result = mod.return_from_grid(grid(), 200, 230)
    assert result is not None
    assert result[1]["holding_minutes"] == 30


def test_choose_decision():
    frame = pd.DataFrame(
        {
            "exit_variant": list(mod.EXIT_VARIANTS),
            "sample_pass": [True, True, True],
            "research_candidate_for_independent_replication": [False, True, False],
        }
    )
    decision, supported = mod.choose_decision(frame)
    assert "REQUIRES_INDEPENDENT_REPLICATION" in decision
    assert supported == ["FIXED_60M"]


def test_choose_insufficient():
    frame = pd.DataFrame(
        {
            "exit_variant": list(mod.EXIT_VARIANTS),
            "sample_pass": [False, False, False],
            "research_candidate_for_independent_replication": [False, False, False],
        }
    )
    decision, supported = mod.choose_decision(frame)
    assert "INSUFFICIENT_SAMPLE" in decision
    assert supported == []


def test_default_paths():
    args = mod.parse_args(["--execute"])
    assert "V22.062N_FAST3" in args.v22_062n_summary
    assert "V22.062PR_FAST3" in args.v22_062pr_summary
    assert "V22.063R1_FAST3" in args.v22_063r1_summary


def test_policy_constants():
    assert mod.SIGNAL_START == 180
    assert mod.SIGNAL_END == 390
    assert mod.DEVIATION_THRESHOLD == 2.0
    assert mod.FIXED_ACCOUNT_WEIGHT == 0.20
