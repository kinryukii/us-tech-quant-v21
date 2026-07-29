from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

import v22_062pa_fast3_premarket_extreme_return_audit_r1 as mod


def valid_summary():
    return {
        "final_status": "PASS",
        "final_decision": "NO_PREMARKET_BASELINE_CANDIDATE_QUALIFIED",
        "v22_062n_validated": True,
        "v22_056_validated": True,
        "overnight_architecture_used": False,
        "rth_orb_architecture_used": False,
        "pullback_reentry_architecture_used": False,
        "session_name": "PREMARKET",
        "maximum_entries_per_session": 1,
        "entry_timing": "EXACT_NEXT_MINUTE_OPEN",
        "tradability_proxy_used": True,
        "bid_ask_spread_available": False,
        "order_book_depth_available": False,
        "rsi_entry_gate_used": False,
        "macd_entry_gate_used": False,
        "kdj_entry_gate_used": False,
        "vix_entry_gate_used": False,
        "vix_risk_scaling_used": False,
        "parameter_sweep_executed": False,
        "session_window_sweep_executed": False,
        "initial_range_length_sweep_executed": False,
        "gap_threshold_sweep_executed": False,
        "liquidity_threshold_sweep_executed": False,
        "indicator_threshold_optimization_executed": False,
        "exit_threshold_optimization_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "new_market_data_cache_created": False,
        "open_d_called": False,
        "history_download_executed": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
        "canonical_partition_count_indexed": 582,
        "supported_exit_variants_for_replication": [],
    }


def sample_trades():
    rows = []
    index = 0
    for variant in mod.EXIT_VARIANTS:
        for period, year in [
            (mod.VALIDATION, 2024),
            (mod.CONFIRMATION, 2025),
        ]:
            for value in [0.01, -0.005, 0.002, -0.003, 0.50]:
                entry = 100.0
                exit_price = (
                    entry
                    * (1.0 + mod.ENTRY_COST)
                    * (1.0 + value)
                    / (1.0 - mod.EXIT_COST)
                )
                rows.append(
                    {
                        "exit_variant": variant,
                        "study_period": period,
                        "session_date": f"{year}-01-{index % 20 + 2:02d}",
                        "calendar_year": year,
                        "direction": "LONG",
                        "execution_symbol": "SOXL",
                        "entry_timestamp_utc": (
                            f"{year}-01-{index % 20 + 2:02d} 12:00:00+00:00"
                        ),
                        "exit_timestamp_utc": (
                            f"{year}-01-{index % 20 + 2:02d} 13:00:00+00:00"
                        ),
                        "entry_price_raw": entry,
                        "exit_price_raw": exit_price,
                        "holding_minutes": 60,
                        "instrument_net_return": value,
                        "account_trade_return": value * 0.20,
                    }
                )
                index += 1
    return pd.DataFrame(rows)


def test_validate_summary():
    mod.validate_v22_062p(valid_summary())


def test_validate_summary_rejects():
    summary = valid_summary()
    summary["vix_entry_gate_used"] = True
    with pytest.raises(mod.AuditError):
        mod.validate_v22_062p(summary)


def test_symbol_month_path():
    path = (
        mod.Path("x")
        / "symbol=US.SOXL"
        / "year=2025"
        / "month=7"
        / "data.parquet"
    )
    assert mod.symbol_month_from_path(path) == (
        "SOXL",
        "2025",
        "07",
    )


def test_normalize_reconstructs_return():
    result = mod.normalize_trades(sample_trades())
    assert result[
        "return_reconstruction_difference"
    ].abs().max() < 1e-9


def test_extreme_flag():
    result = mod.normalize_trades(sample_trades())
    assert result["preliminary_extreme_return"].any()


def test_profit_factor():
    assert mod.profit_factor(
        pd.Series([0.02, 0.01, -0.01])
    ) == pytest.approx(3.0)


def test_positive_profit_share():
    value = mod.positive_profit_share(
        pd.Series([0.8, 0.1, 0.1, -0.2]),
        1,
    )
    assert value == pytest.approx(0.8)


def test_distribution_summary():
    trades = mod.normalize_trades(sample_trades())
    result = mod.distribution_summary(trades)
    assert len(result) == 6
    assert (result["trade_count"] == 5).all()


def test_year_concentration():
    trades = mod.normalize_trades(sample_trades())
    result = mod.year_concentration(trades)
    assert not result.empty
    assert "positive_profit_contribution_share" in result.columns


def test_select_targeted_trades():
    trades = mod.normalize_trades(sample_trades())
    selected = mod.select_targeted_trades(trades)
    assert not selected.empty
    assert selected["trade_id"].is_unique


def test_previous_month():
    assert mod.previous_month(2025, 1) == ("2024", "12")
    assert mod.previous_month(2025, 7) == ("2025", "06")


def test_sensitivity_summary():
    trades = mod.normalize_trades(sample_trades())
    anomaly_id = int(trades.iloc[0]["trade_id"])
    result = mod.sensitivity_summary(trades, {anomaly_id})
    assert set(result["sensitivity_set"]) == {
        "ALL_TRADES",
        "EXCLUDE_MECHANICAL_ANOMALIES",
    }


def test_choose_data_anomaly():
    distribution = pd.DataFrame(
        {
            "study_period": [mod.VALIDATION],
            "top1_positive_profit_share": [0.1],
            "top5_positive_profit_share": [0.2],
        }
    )
    concentration = pd.DataFrame(
        {"positive_profit_contribution_share": [0.2]}
    )
    audit = pd.DataFrame({"mechanical_anomaly": [True]})
    decision, next_stage = mod.choose_decision(
        distribution,
        concentration,
        audit,
    )
    assert decision == (
        "PREMARKET_RESULT_BLOCKED_BY_EXTREME_RETURN_DATA_ANOMALY"
    )
    assert "PRICE_NORMALIZATION" in next_stage


def test_choose_concentrated():
    distribution = pd.DataFrame(
        {
            "study_period": [mod.CONFIRMATION],
            "top1_positive_profit_share": [0.8],
            "top5_positive_profit_share": [0.9],
        }
    )
    concentration = pd.DataFrame(
        {"positive_profit_contribution_share": [0.9]}
    )
    audit = pd.DataFrame({"mechanical_anomaly": [False]})
    decision, next_stage = mod.choose_decision(
        distribution,
        concentration,
        audit,
    )
    assert decision == (
        "PREMARKET_RESULT_NOT_REPLICATION_READY_OUTLIER_AND_YEAR_CONCENTRATED"
    )
    assert "AFTER_HOURS" in next_stage


def test_choose_replication():
    distribution = pd.DataFrame(
        {
            "study_period": [mod.CONFIRMATION],
            "top1_positive_profit_share": [0.2],
            "top5_positive_profit_share": [0.5],
        }
    )
    concentration = pd.DataFrame(
        {"positive_profit_contribution_share": [0.4]}
    )
    audit = pd.DataFrame({"mechanical_anomaly": [False]})
    decision, next_stage = mod.choose_decision(
        distribution,
        concentration,
        audit,
    )
    assert decision == (
        "PREMARKET_RESULT_REQUIRES_INDEPENDENT_REPLICATION"
    )
    assert "REPLICATION" in next_stage


def test_default_paths():
    args = mod.parse_args(["--execute"])
    assert "V22.062P_FAST3" in args.v22_062p_root
    assert "moomoo_24h_1m" in args.canonical_root
    assert "V22.062PA_FAST3" in args.result_dir


def test_policy_constants():
    assert mod.EXTREME_ABS_RETURN_THRESHOLD == 0.25
    assert mod.ADJACENT_MINUTE_JUMP_THRESHOLD == 0.20
    assert mod.TOP1_POSITIVE_PROFIT_SHARE_LIMIT == 0.50
    assert mod.TOP5_POSITIVE_PROFIT_SHARE_LIMIT == 0.80
