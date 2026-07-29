from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

import v22_060_fast3_vix_magnitude_risk_and_exit_capture_r1 as mod


def valid_059():
    return {
        "final_status": "PASS",
        "final_decision": "NO_VIX_CHANGE_RATE_CANDIDATE_QUALIFIED",
        "v22_058_validated": True,
        "v22_058a_validated": True,
        "v22_056_validated": True,
        "vix_mode": "PRIOR_DAY_CHANGE_RATE_ONLY_FOR_RATE_VARIANTS",
        "vix_absolute_level_core_used": False,
        "intraday_vix_used": False,
        "vix_proxy_used": False,
        "kdj_entry_used": False,
        "kdj_exit_used": False,
        "old_level_candidate_reproduction_pass": True,
        "old_level_trade_reproduction_pass": True,
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
        "trade_count_by_variant": {mod.SOURCE_VARIANT: 10},
    }


def valid_059a():
    return {
        "final_status": "PASS",
        "source_v22_059_validated": True,
        "hard_entry_gate_supported": False,
        "risk_overlay_candidate": True,
        "recommended_vix_role": "RISK_SCALER_ONLY",
        "canonical_partition_count_read": 0,
        "backtest_executed": False,
        "parameter_sweep_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "intraday_vix_used": False,
        "vix_proxy_used": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }


def synthetic_vix(rows: int = 8000) -> pd.DataFrame:
    dates = pd.bdate_range("1990-01-02", periods=rows)
    close = 20.0 + np.sin(np.arange(rows) / 13.0) + np.arange(rows) * 0.0001
    return pd.DataFrame({"DATE": dates, "CLOSE": close})


def synthetic_source_trades() -> pd.DataFrame:
    vix = synthetic_vix()
    features = mod.build_vix_trade_date_features(vix)
    selected = features.dropna().iloc[-8:].reset_index(drop=True)
    rows = []
    for index, row in selected.iterrows():
        period = mod.VALIDATION if index < 4 else mod.CONFIRMATION
        year = 2023 if index < 4 else 2025
        dynamic = -0.01 if index % 2 == 0 else 0.008
        fixed = 0.012 if index % 2 == 0 else 0.010
        rows.append(
            {
                "variant": mod.SOURCE_VARIANT,
                "study_period": period,
                "calendar_year": year,
                "trade_date": row["trade_date"],
                "direction": "LONG" if index % 2 == 0 else "SHORT",
                "execution_symbol": "SOXL" if index % 2 == 0 else "SOXS",
                "exit_reason": "HARD_STOP" if index % 2 == 0 else "TRAILING_PROTECTION",
                "holding_minutes": 3 if index % 2 == 0 else 20,
                "position_weight": 0.25,
                "instrument_net_return": dynamic,
                "account_trade_return": dynamic * 0.25,
                "mfe": 0.003 if index % 2 == 0 else 0.02,
                "mae": -0.012 if index % 2 == 0 else -0.004,
                "vix_rate_1d_prior": row["vix_rate_1d_prior_rebuilt"],
                "entry_signal_60m_net_return": fixed,
                "pit_baseline_eligible_60m": True,
                "entry_excess_pit_60m": fixed - 0.001,
            }
        )
    return pd.DataFrame(rows), vix


def test_validate_059():
    mod.validate_v22_059(valid_059())


def test_validate_059_rejects():
    summary = valid_059()
    summary["kdj_entry_used"] = True
    with pytest.raises(mod.StudyError):
        mod.validate_v22_059(summary)


def test_validate_059a():
    mod.validate_v22_059a(valid_059a())


def test_profit_factor():
    assert mod.profit_factor(
        pd.Series([0.02, 0.01, -0.01])
    ) == pytest.approx(3.0)


def test_maximum_drawdown():
    assert mod.maximum_drawdown(
        pd.Series([0.10, -0.20, 0.10])
    ) == pytest.approx(-0.20)


def test_cumulative_return():
    assert mod.cumulative_return(
        pd.Series([0.10, -0.10])
    ) == pytest.approx(0.99 - 1.0)


def test_worst_loss_sum():
    assert mod.worst_loss_sum(
        pd.Series([-0.03, -0.01, 0.02]), 1
    ) == pytest.approx(0.03)


def test_prior_absolute_rate_percentile_warmup():
    close = pd.Series(np.arange(400, dtype=float) + 10)
    rate, percentile = mod.prior_absolute_rate_percentile(close)
    assert rate.iloc[0] != rate.iloc[0]
    assert percentile.iloc[: mod.PIT_WINDOW + 1].isna().all()


def test_build_vix_features():
    result = mod.build_vix_trade_date_features(synthetic_vix())
    assert "vix_abs_rate_pctl_252_prior" in result.columns
    assert result["trade_date"].is_unique


def test_risk_scale():
    assert mod.risk_scale(0.50) == 1.0
    assert mod.risk_scale(0.85) == 0.5
    assert mod.risk_scale(0.97) == 0.0


def test_normalize_source_trades():
    trades, vix = synthetic_source_trades()
    result = mod.normalize_source_trades(
        trades,
        mod.build_vix_trade_date_features(vix),
    )
    assert len(result) == len(trades)
    assert result["vix_magnitude_risk_scale"].isin(
        [0.0, 0.5, 1.0]
    ).all()


def test_build_risk_variants():
    trades, vix = synthetic_source_trades()
    source = mod.normalize_source_trades(
        trades,
        mod.build_vix_trade_date_features(vix),
    )
    result = mod.build_risk_variant_trades(source)
    assert set(result["risk_variant"]) == set(mod.RISK_VARIANTS)
    assert len(result) == len(source) * 2


def test_build_exit_variants():
    trades, vix = synthetic_source_trades()
    source = mod.normalize_source_trades(
        trades,
        mod.build_vix_trade_date_features(vix),
    )
    result = mod.build_exit_variant_trades(source)
    assert set(result["exit_variant"]) == set(mod.EXIT_VARIANTS)
    assert len(result) == len(source) * 3


def test_hybrid_preserves_hard_stop():
    trades, vix = synthetic_source_trades()
    source = mod.normalize_source_trades(
        trades,
        mod.build_vix_trade_date_features(vix),
    )
    result = mod.build_exit_variant_trades(source)
    hard = result.loc[
        (result["exit_variant"] == mod.HYBRID_EXIT)
        & result["exit_reason"].eq("HARD_STOP")
    ]
    assert np.allclose(
        hard["exit_variant_instrument_return"],
        hard["instrument_net_return"],
    )


def test_daily_returns():
    frame = pd.DataFrame(
        {
            "risk_variant": ["A", "A"],
            "study_period": [mod.VALIDATION] * 2,
            "trade_date": ["2023-01-03"] * 2,
            "scaled_account_trade_return": [0.01, -0.005],
        }
    )
    result = mod.daily_returns(
        frame,
        "risk_variant",
        "scaled_account_trade_return",
    )
    assert result.iloc[0]["daily_return"] == pytest.approx(
        1.01 * 0.995 - 1.0
    )


def test_hard_stop_diagnostic():
    trades, vix = synthetic_source_trades()
    source = mod.normalize_source_trades(
        trades,
        mod.build_vix_trade_date_features(vix),
    )
    result = mod.hard_stop_diagnostic(source)
    assert not result.empty
    assert (
        result["recovered_to_positive_by_60m_rate"] == 1.0
    ).all()


def test_risk_period_summary():
    trades, vix = synthetic_source_trades()
    source = mod.normalize_source_trades(
        trades,
        mod.build_vix_trade_date_features(vix),
    )
    risk = mod.build_risk_variant_trades(source)
    daily = mod.daily_returns(
        risk,
        "risk_variant",
        "scaled_account_trade_return",
    )
    result = mod.summarize_risk_periods(risk, daily)
    assert set(result["risk_variant"]) == set(mod.RISK_VARIANTS)


def test_exit_period_summary():
    trades, vix = synthetic_source_trades()
    source = mod.normalize_source_trades(
        trades,
        mod.build_vix_trade_date_features(vix),
    )
    exits = mod.build_exit_variant_trades(source)
    daily = mod.daily_returns(
        exits,
        "exit_variant",
        "exit_variant_account_return",
    )
    result = mod.summarize_exit_periods(exits, daily)
    assert set(result["exit_variant"]) == set(mod.EXIT_VARIANTS)


def test_evaluate_hard_stops():
    frame = pd.DataFrame(
        {
            "study_period": [mod.VALIDATION, mod.CONFIRMATION],
            "direction": ["LONG", "LONG"],
            "stop_within_5m_rate": [0.5, 0.6],
            "mean_fixed_60m_improvement": [0.01, 0.02],
            "recovered_to_positive_by_60m_rate": [0.4, 0.5],
        }
    )
    result = mod.evaluate_hard_stops(frame)
    assert result["hard_stop_capture_problem"] is True


def test_choose_stop_audit():
    risk_eval = {
        "risk_metrics_pass": False,
        "tradable_edge_pass": False,
    }
    exit_eval = {"preferred_exit_variant": None}
    stop_eval = {"hard_stop_capture_problem": True}
    result = mod.choose_decision(
        risk_eval, exit_eval, stop_eval
    )
    assert result["next_stage"] == (
        "V22.061_FAST3_ENTRY_TIMING_AND_STOP_MECHANICS_AUDIT_R1"
    )


def test_default_paths():
    args = mod.parse_args(["--execute"])
    assert "V22.059_FAST3" in args.v22_059_root
    assert "V22.059A_FAST3" in args.v22_059a_root
    assert "vix_daily.csv" in args.vix_daily
    assert "V22.060_FAST3" in args.result_dir


def test_policy_constants():
    assert mod.ABS_PCTL_FULL_RISK == 0.80
    assert mod.ABS_PCTL_HALF_RISK == 0.95
    assert mod.PIT_WINDOW == 252
