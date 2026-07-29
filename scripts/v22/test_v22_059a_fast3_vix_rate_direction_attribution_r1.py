from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

import v22_059a_fast3_vix_rate_direction_attribution_r1 as mod


def valid_summary():
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
        "trade_count_by_variant": {
            mod.NO_VIX: 10,
            mod.OLD_LEVEL: 5,
            mod.RATE_1D: 4,
            mod.RATE_1D_3D: 3,
        },
    }


def sample_trades():
    rows = []
    index = 0
    for period, year in [
        (mod.VALIDATION, 2023),
        (mod.CONFIRMATION, 2025),
    ]:
        for direction in ["LONG", "SHORT"]:
            for alignment, rates in [
                ("aligned", (-0.05, -0.08) if direction == "LONG" else (0.05, 0.08)),
                ("opposed", (0.05, 0.08) if direction == "LONG" else (-0.05, -0.08)),
            ]:
                for offset in range(2):
                    one, three = rates
                    return_value = 0.01 if alignment == "aligned" else -0.01
                    rows.append(
                        {
                            "variant": mod.NO_VIX,
                            "study_period": period,
                            "calendar_year": year,
                            "trade_date": f"{year}-01-{index + 1:02d}",
                            "direction": direction,
                            "execution_symbol": (
                                "SOXL" if direction == "LONG" else "SOXS"
                            ),
                            "exit_reason": (
                                "TRAILING_PROTECTION"
                                if return_value > 0
                                else "HARD_STOP"
                            ),
                            "holding_minutes": 15,
                            "instrument_net_return": return_value,
                            "account_trade_return": return_value * 0.25,
                            "mfe": 0.02,
                            "mae": -0.01,
                            "vix_rate_1d_prior": one,
                            "vix_rate_3d_prior": three,
                            "vix_rate_1d_pctl_252_prior": (
                                0.25 if one < 0 else 0.75
                            ),
                            "vix_positive_shock_prior": False,
                            "entry_signal_60m_net_return": 0.005,
                            "pit_baseline_eligible_60m": True,
                            "entry_excess_pit_60m": (
                                0.002 if alignment == "aligned" else -0.002
                            ),
                        }
                    )
                    index += 1
    return pd.DataFrame(rows)


def sample_candidates():
    trades = sample_trades()
    result = trades[
        [
            "trade_date",
            "study_period",
            "direction",
            "execution_symbol",
            "vix_rate_1d_prior",
            "vix_rate_3d_prior",
            "vix_rate_1d_pctl_252_prior",
            "vix_positive_shock_prior",
        ]
    ].copy()
    for variant in mod.VARIANTS:
        result[f"{variant.lower()}_signal"] = True
    return result


def test_validate_summary():
    mod.validate_v22_059(valid_summary())


def test_validate_summary_rejects():
    summary = valid_summary()
    summary["intraday_vix_used"] = True
    with pytest.raises(mod.DiagnosticError):
        mod.validate_v22_059(summary)


def test_profit_factor():
    assert mod.profit_factor(
        pd.Series([0.02, 0.01, -0.01])
    ) == pytest.approx(3.0)


def test_profit_factor_inf():
    assert math.isinf(mod.profit_factor(pd.Series([0.01])))


def test_maximum_drawdown():
    result = mod.maximum_drawdown(pd.Series([0.10, -0.20, 0.10]))
    assert result == pytest.approx(-0.20)


def test_vix_state():
    assert mod.vix_state(-0.1, -0.2) == "DOWN_DOWN"
    assert mod.vix_state(0.1, -0.2) == "UP_DOWN"


def test_long_alignment():
    assert mod.direction_alignment(
        "LONG", -0.1, -0.2, False
    ) == "ALIGNED_1D_3D"


def test_short_alignment():
    assert mod.direction_alignment(
        "SHORT", 0.1, 0.2, False
    ) == "ALIGNED_1D_3D"


def test_positive_shock_precedence():
    assert mod.direction_alignment(
        "SHORT", 0.1, 0.2, True
    ) == "POSITIVE_SHOCK"


def test_percentile_bins():
    assert mod.signed_rate_percentile_bin(0.01) == (
        "P00_05_EXTREME_DROP"
    )
    assert mod.signed_rate_percentile_bin(0.97) == (
        "P95_100_EXTREME_RISE"
    )


def test_normalize_trades_adds_fields():
    result = mod.normalize_trades(sample_trades())
    assert "vix_state" in result.columns
    assert "vix_direction_alignment" in result.columns
    assert "realized_minus_fixed_60m" in result.columns


def test_group_summary():
    normalized = mod.normalize_trades(sample_trades())
    result = mod.grouped_summary(
        normalized,
        ["study_period", "direction", "vix_direction_alignment"],
    )
    assert result["trade_count"].sum() == len(normalized)


def test_candidate_funnel():
    candidates = mod.normalize_candidates(sample_candidates())
    result = mod.candidate_funnel(candidates)
    assert result["base_candidate_count"].sum() == len(candidates)


def test_exit_summary():
    normalized = mod.normalize_trades(sample_trades())
    result = mod.exit_summary(normalized)
    assert result["trade_count"].sum() == len(normalized)


def test_tail_summary():
    normalized = mod.normalize_trades(sample_trades())
    result = mod.tail_summary(normalized)
    assert result["worst_5_loss_share"].dropna().between(0, 1).all()


def test_direction_candidate_detects_both_periods():
    normalized = mod.normalize_trades(sample_trades())
    # Duplicate aligned LONG rows to reach sample threshold of 10 in each period.
    aligned_long = normalized.loc[
        (normalized["direction"] == "LONG")
        & (
            normalized["vix_direction_alignment"]
            == "ALIGNED_1D_3D"
        )
    ]
    expanded = pd.concat([normalized, *([aligned_long] * 5)], ignore_index=True)
    summary = mod.grouped_summary(
        expanded,
        ["study_period", "direction", "vix_direction_alignment"],
    )
    assert mod.direction_candidate(summary) == "LONG"


def period_frame():
    return pd.DataFrame(
        [
            {
                "variant": mod.NO_VIX,
                "study_period": mod.VALIDATION,
                "trade_count": 80,
                "mean_instrument_net_return": -0.002,
                "max_drawdown": -0.08,
            },
            {
                "variant": mod.RATE_1D_3D,
                "study_period": mod.VALIDATION,
                "trade_count": 20,
                "mean_instrument_net_return": -0.003,
                "max_drawdown": -0.02,
            },
            {
                "variant": mod.NO_VIX,
                "study_period": mod.CONFIRMATION,
                "trade_count": 60,
                "mean_instrument_net_return": -0.001,
                "max_drawdown": -0.04,
            },
            {
                "variant": mod.RATE_1D_3D,
                "study_period": mod.CONFIRMATION,
                "trade_count": 20,
                "mean_instrument_net_return": -0.001,
                "max_drawdown": -0.01,
            },
        ]
    )


def test_risk_reduction():
    result = mod.compare_risk_reduction(period_frame())
    assert result[
        "both_period_mdd_reduction_at_least_30pct"
    ] is True


def test_choose_risk_overlay():
    normalized = mod.normalize_trades(sample_trades())
    direction = mod.grouped_summary(
        normalized,
        ["study_period", "direction", "vix_direction_alignment"],
    )
    result = mod.choose_decision(period_frame(), direction)
    assert result["recommended_vix_role"] == "RISK_SCALER_ONLY"
    assert result["next_stage"] == (
        "V22.060_FAST3_VIX_RATE_RISK_SCALING_STUDY_R1"
    )


def test_default_paths():
    args = mod.parse_args(["--execute"])
    assert "V22.059_FAST3" in args.root
    assert "V22.059A_FAST3" in args.result_dir
