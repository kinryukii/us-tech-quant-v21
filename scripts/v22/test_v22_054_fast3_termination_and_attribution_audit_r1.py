from __future__ import annotations

import pandas as pd
import pytest

import v22_054_fast3_termination_and_attribution_audit_r1 as mod


def valid_052():
    return {
        "final_status": "PASS",
        "final_decision": "NO_LONG_NONOVERLAP_CANDIDATE_QUALIFIED",
        "data_ready_for_v22_053": False,
        "entry_filter_optimization_executed": False,
        "exit_optimization_executed": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }


def valid_053():
    return {
        "final_status": "PASS",
        "final_decision": "NO_PULLBACK_REENTRY_CANDIDATE_QUALIFIED",
        "data_ready_for_v22_054": False,
        "entry_filter_optimization_executed": False,
        "exit_optimization_executed": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }


def sample():
    return pd.DataFrame(
        {
            "execution_symbol": ["SOXL", "SOXL", "SOXL", "SOXL"],
            "horizon_minutes": [60, 60, 60, 60],
            "trade_date": ["2023-01-02", "2023-01-02", "2024-01-02", "2025-01-02"],
            "calendar_year": [2023, 2023, 2024, 2025],
            "net_return": [0.01, -0.005, 0.02, -0.03],
            "signal_excess_pit_net": [0.005, -0.002, 0.01, -0.02],
            "matched_pit_count": [25, 25, 30, 10],
        }
    )


def test_validate_052():
    mod.validate_summary(valid_052(), "052")


def test_validate_053():
    mod.validate_summary(valid_053(), "053")


def test_reject_wrong_gate():
    payload = valid_053()
    payload["data_ready_for_v22_054"] = True
    with pytest.raises(mod.AuditError):
        mod.validate_summary(payload, "053")


def test_pit_correction():
    result = mod.normalize_trades(sample(), "X")
    assert result["pit_eligible_corrected"].tolist() == [True, True, True, False]


def test_corrected_annual_count():
    annual = mod.corrected_annual_summary(mod.normalize_trades(sample(), "X"))
    assert int(annual.loc[annual["calendar_year"] == 2023, "pit_eligible_trade_count_corrected"].iloc[0]) == 2


def test_daily_compounding():
    daily = mod.daily_compound(mod.normalize_trades(sample(), "X"))
    value = daily.loc[daily["trade_date"] == "2023-01-02", "daily_compound_net_return"].iloc[0]
    assert value == pytest.approx(1.01 * 0.995 - 1)


def test_nav_and_mdd():
    total, mdd = mod.nav_and_mdd(pd.Series([0.10, -0.20, 0.10]))
    assert total == pytest.approx(1.1 * 0.8 * 1.1 - 1)
    assert mdd == pytest.approx(-0.20)


def test_concentration_bounds():
    result = mod.concentration(pd.Series([0.1, 0.02, -0.03, -0.01]))
    assert 0 <= result["top_5pct_positive_contribution_share"] <= 1
    assert 0 <= result["worst_10_days_negative_contribution_share"] <= 1


def test_leave_one_year_out():
    loo = mod.leave_one_year_out(mod.normalize_trades(sample(), "X"))
    assert set(loo["omitted_year"]) == {2023, 2024, 2025}


def test_loo_summary_sign_flip():
    frame = pd.DataFrame(
        {
            "architecture": ["X", "X"],
            "execution_symbol": ["SOXL", "SOXL"],
            "horizon_minutes": [60, 60],
            "omitted_year": [2023, 2024],
            "remaining_trade_count": [10, 10],
            "mean_net_return": [0.01, -0.01],
            "median_net_return": [0.01, -0.01],
            "positive_rate": [0.6, 0.4],
            "pit_eligible_trade_count": [10, 10],
            "mean_excess_pit": [0.01, -0.01],
            "net_sign_positive": [True, False],
            "excess_sign_positive": [True, False],
        }
    )
    summary = mod.loo_summary(frame)
    assert bool(summary["loo_net_sign_flip"].iloc[0]) is True


def test_worst_days():
    daily = mod.daily_compound(mod.normalize_trades(sample(), "X"))
    worst = mod.worst_days(daily, 1)
    assert worst["daily_compound_net_return"].iloc[0] == pytest.approx(-0.03)


def test_default_paths():
    args = mod.parse_args(["--execute"])
    assert "V22.052_FAST3_LONG_NONOVERLAP" in args.v22_052_root
    assert "V22.053_FAST3_TREND_PULLBACK" in args.v22_053_root
    assert "V22.054_FAST3_TERMINATION" in args.result_dir


def test_policy_constant():
    assert mod.MIN_PIT_COUNT == 20
