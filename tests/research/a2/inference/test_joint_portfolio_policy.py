"""Focused synthetic invariants for the JOINT R1 thin policy adapter.

All forecasts, risk matrices, and accounts here are invented; no market or
economic result objects are opened. Retained account/projection tests are not
duplicated.
"""
import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.inference.joint_portfolio_policy import JointResearchPolicy
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import (
    AccountContext, TargetDecision,
)

PARAMETERS = {
    "optimizer": {"risk_penalty": 4, "uncertainty_penalty": .5, "max_q": .1,
                  "max_positions": 20, "iterations": 128, "tolerance": 2e-6,
                  "turnover_cost": 0},
    "gross": {"fixed": 1, "volatility_target_annual": .1},
    "action": {"partial_rebalance": .5, "full_action_ablation": 1},
}


def context(role_ids, count, current=None, reserved=None, buy=None):
    shape = (len(role_ids), count)
    current = np.zeros(shape) if current is None else np.asarray(current, float)
    reserved = np.zeros(shape, bool) if reserved is None else np.asarray(reserved, bool)
    buy = np.ones(shape, bool) if buy is None else np.asarray(buy, bool)
    cash_weight = 1-current.sum(axis=1)
    return AccountContext(
        signal_index=0, signal_date=pd.Timestamp("2024-01-02"),
        signal_asof=pd.Timestamp("2024-01-02"), path_ids=tuple(role_ids),
        tickers=np.array([f"N{i:02}" for i in range(count)]),
        current_units=np.where(current > 0, current*3000/100, 0),
        current_weights=current, cash=cash_weight*3000, cash_weight=cash_weight,
        nav=np.full(len(role_ids), 3000.), reserved_mask=reserved,
        reserved_weight=np.where(reserved, current, 0).sum(axis=1),
        reserved_slots=reserved.sum(axis=1),
        available_budget=1-np.where(reserved, current, 0).sum(axis=1),
        available_slots=20-reserved.sum(axis=1), buy_allowed=buy,
        sell_restricted=np.zeros(shape, bool), input_present=np.ones(shape, bool),
        decision_mask=np.ones(shape, bool), operational_mask=np.zeros(shape, bool),
        max_positions=20, max_weight=.1, max_invested=1.,
    )


def run(role_ids, means, covariance, ctx=None, roles=None, uncertainty=None):
    means = np.asarray(means, float)
    if means.ndim == 1:
        means = np.broadcast_to(means, (len(role_ids), len(means))).copy()
    ctx = context(role_ids, means.shape[1]) if ctx is None else ctx
    uncertainty = np.zeros_like(means) if uncertainty is None else np.asarray(uncertainty, float)
    logs = []
    policy = JointResearchPolicy(
        role_ids, means[None, :, :], uncertainty[None, :, :],
        {(2024, "DIAG"): np.diag(np.diag(covariance)), (2024, "LW"): covariance},
        roles=roles, parameters=PARAMETERS, on_diagnostics=logs.append,
    )
    decision = policy(0, ctx)
    assert isinstance(decision, TargetDecision)
    return decision, logs[0].set_index("path_id")


def assert_complete(record):
    assert record.status != "FALLBACK_PRESERVE_UNITS", record.failure_reason
    assert sum(record.relative_weights) == pytest.approx(1, abs=1e-8)
    assert record.global_optimum_claim == False


def correlated_opportunities():
    means = np.linspace(.01, .009, 21)
    means[-1] = .0089
    covariance = np.eye(21)*.02
    covariance[:20, :20] = .019
    np.fill_diagonal(covariance, .02)
    return means, covariance


def test_full_candidate_joint_support_replaces_high_correlation_raw_name():
    roles = ("CONTROL_RAW_A2_POLICY", "JOINT_SIMPLE_EQUAL", "ABL_ACTION")
    means, covariance = correlated_opportunities()
    decision, diagnostics = run(roles, means, covariance, roles={"ABL_ACTION": {"risk": "LW"}})
    raw_support = np.flatnonzero(decision.weights[0] > 1e-10)
    simple_support = np.flatnonzero(decision.weights[1] > 1e-10)
    joint_support = np.flatnonzero(decision.weights[2] > 1e-10)
    assert raw_support.tolist() == simple_support.tolist() == list(range(20))
    assert 20 in joint_support and 19 not in joint_support
    assert len(joint_support) <= 20
    raw = diagnostics.loc[roles[0]]
    joint = diagnostics.loc[roles[2]]
    assert raw.gross_target == pytest.approx(.95)
    assert decision.weights[0].sum() == pytest.approx(.95)
    assert joint.full_candidate_count == 21
    assert_complete(joint)
    assert decision.weights[2].sum() == pytest.approx(1)
    assert decision.weights[2].max() <= .1+1e-10
    forced_top20 = decision.weights[1]
    forced_objective = means@forced_top20-2*forced_top20@covariance@forced_top20
    assert joint.objective > forced_objective


def test_mass_one_composition_then_frozen_vol_gross_and_partial_action():
    roles = ("PTO_EQUAL_ENSEMBLE_LW", "PTO_EQUAL_ENSEMBLE_LW_VOL", "ABL_ACTION")
    covariance = np.eye(20)*.04
    decision, diagnostics = run(roles, np.full(20, .01), covariance)
    fixed = diagnostics.loc[roles[0]]
    vol = diagnostics.loc[roles[1]]
    full = diagnostics.loc[roles[2]]
    for row in (fixed, vol, full):
        assert_complete(row)
    q = np.asarray(vol.relative_weights)
    expected = .1/np.sqrt(252*q@covariance@q)
    assert fixed.gross_target == pytest.approx(1)
    assert vol.gross_target == pytest.approx(expected)
    assert 0 < vol.gross_target < 1
    assert vol.action_target_gross == pytest.approx(.5*vol.gross_target)
    assert decision.weights[0].sum() == pytest.approx(.5)
    assert decision.weights[1].sum() == pytest.approx(.5*expected)
    assert decision.weights[2].sum() == pytest.approx(1)


def test_out_of_pool_incumbent_never_added_despite_large_forecast():
    current = np.zeros((1, 22))
    current[0, 0] = .025
    buy = np.ones((1, 22), bool)
    buy[0, 0] = False
    ctx = context(("ABL_ACTION",), 22, current=current, buy=buy)
    means = np.full(22, .01)
    means[0] = .5
    decision, diagnostics = run(("ABL_ACTION",), means, np.eye(22)*.001, ctx=ctx)
    assert_complete(diagnostics.loc["ABL_ACTION"])
    assert decision.weights[0, 0] <= current[0, 0]+1e-10
    assert decision.explicit_mask[0, 0]
    assert decision.weights.sum() == pytest.approx(1)


def test_reserved_holdings_keep_slots_and_budget_without_fake_means():
    current = np.zeros((1, 30))
    current[0, :6] = .025
    reserved = np.zeros((1, 30), bool)
    reserved[0, :6] = True
    ctx = context(("ABL_ACTION",), 30, current=current, reserved=reserved)
    means = np.linspace(.02, .01, 30)
    means[:6] = np.nan
    decision, diagnostics = run(("ABL_ACTION",), means, np.eye(30)*.001, ctx=ctx)
    record = diagnostics.loc["ABL_ACTION"]
    assert_complete(record)
    assert record.reserved_slots == 6
    assert record.reserved_weight == pytest.approx(.15)
    assert len(record.selected_tickers) <= 14
    assert not decision.explicit_mask[0, :6].any()
    assert not decision.weights[0, :6].any()
    assert decision.weights.sum() == pytest.approx(.85)
    assert decision.weights.sum()+current[0, :6].sum() == pytest.approx(1)
    assert len(record.composition_tickers) <= 20


def test_missing_incumbent_forecast_adds_reservation_and_remains_diagnostic():
    current = np.zeros((1, 25))
    current[0, 0] = .03
    ctx = context(("ABL_ACTION",), 25, current=current)
    means = np.full(25, .01)
    means[0] = np.nan
    decision, diagnostics = run(("ABL_ACTION",), means, np.eye(25)*.001, ctx=ctx)
    record = diagnostics.loc["ABL_ACTION"]
    assert_complete(record)
    assert record.missing_forecast_count == 1
    assert record.reserved_slots == 1
    assert not decision.explicit_mask[0, 0]
    assert decision.weights[0, 0] == 0
    assert len(record.selected_tickers) <= 19
    assert decision.weights.sum() == pytest.approx(.97)


def test_infeasible_composition_records_failure_and_preserves_all_units():
    current = np.zeros((1, 9))
    current[0, 0] = .1
    ctx = context(("ABL_ACTION",), 9, current=current)
    means = np.full(9, .01)
    means[0] = np.nan
    decision, diagnostics = run(("ABL_ACTION",), means, np.eye(9)*.001, ctx=ctx)
    record = diagnostics.loc["ABL_ACTION"]
    assert record.status == "FALLBACK_PRESERVE_UNITS"
    assert record.failure_reason == "INSUFFICIENT_SLOT_OR_CAPACITY_MASS"
    assert record.missing_forecast_count == 1
    assert not decision.explicit_mask.any()
    assert not decision.weights.any()
    assert np.isnan(record.gross_target)


def test_missing_frozen_risk_is_explicit_preserved_units_fallback():
    logs = []
    policy = JointResearchPolicy(
        ("ABL_ACTION",), np.full((1, 1, 20), .01), np.zeros((1, 1, 20)), {},
        parameters=PARAMETERS, on_diagnostics=logs.append,
    )
    decision = policy(0, context(("ABL_ACTION",), 20))
    assert not decision.explicit_mask.any()
    assert logs[0].iloc[0].failure_reason == "FROZEN_RISK_YEAR_OR_KIND_MISSING"
    assert logs[0].iloc[0].status == "FALLBACK_PRESERVE_UNITS"


def test_equal_weight_ablation_uses_same_joint_support():
    means, covariance = correlated_opportunities()
    roles = ("PTO_EQUAL_ENSEMBLE_LW", "ABL_WEIGHT")
    decision, diagnostics = run(roles, means, covariance)
    base, equal = diagnostics.loc[roles[0]], diagnostics.loc[roles[1]]
    assert_complete(base)
    assert_complete(equal)
    assert base.selected_tickers == equal.selected_tickers
    assert 20 in np.flatnonzero(decision.weights[1] > 1e-10)
    assert len(set(np.round(equal.relative_weights, 12))) == 1


def test_partial_rebalance_repairs_grown_selected_weight_to_account_cap():
    current = np.full((1, 20), .82/19)
    current[0, 0] = .18
    ctx = context(("PTO_RIDGE_DIAG",), 20, current=current)
    decision, diagnostics = run(("PTO_RIDGE_DIAG",), np.full(20, .01), np.eye(20)*.001, ctx=ctx)
    record = diagnostics.loc["PTO_RIDGE_DIAG"]
    assert_complete(record)
    assert decision.weights.max() <= .1+1e-10
    assert record.action_projection_repair > 0
    assert decision.weights.sum() <= 1+1e-10
