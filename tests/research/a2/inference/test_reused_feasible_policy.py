"""Synthetic account-capacity and unchanged Q0 default tests; no data IO."""
from dataclasses import replace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.inference.reused_feasible_policy import (
    feasible_target, feasible_capacity, FeasiblePolicyBlocked, ReusedFeasiblePolicy,
)
from scripts.research.a2.portfolio.joint_allocation_methods import allocate_q, AllocationUnavailable
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import AccountContext


def context(n=20, weights=None, locked=None, buy=None, decision=None, operational=None):
    w = np.zeros(n) if weights is None else np.asarray(weights, float)
    mask = lambda v, default: np.full((1, n), default, bool) if v is None else np.asarray(v, bool)[None, :]
    return AccountContext(0, pd.Timestamp('2024-02-01'), pd.Timestamp('2024-02-01T21:00:00Z'),
                          ('SYNTHETIC',), np.array([f'T{i:02}' for i in range(n)]),
                          (w > 0).astype(float)[None, :], w[None, :], np.array([3000. * (1-w.sum())]),
                          np.array([1-w.sum()]), np.array([3000.]), mask(locked, False),
                          np.array([0.]), np.array([0]), np.array([1.]), np.array([20]),
                          mask(buy, True), np.zeros((1, n), bool), np.ones((1, n), bool),
                          mask(decision, True), mask(operational, False), 20, .1, 1.)


def evaluate(kind, ctx, mu=None, sigma=None):
    n = len(ctx.tickers)
    return feasible_target(kind, np.linspace(.01, .02, n) if mu is None else mu,
                           np.full(n, .03) if sigma is None else sigma,
                           np.eye(n) * .002, ctx, covariance_psd_qualified=True)


@pytest.mark.parametrize('kind', ['SIMPLE_FEASIBLE', 'JOINT_REUSE'])
def test_full_capacity_and_subcapacity_have_exact_endogenous_cash(kind):
    full = evaluate(kind, context(20))
    short = evaluate(kind, context(8))
    assert full.receipt['maximum_feasible_gross'] == pytest.approx(1)
    assert full.target.weights.sum() == pytest.approx(1)
    assert short.receipt['maximum_feasible_gross'] == pytest.approx(.8)
    assert short.target.weights.sum() == pytest.approx(.8)
    assert short.receipt['residual_cash_weight'] == pytest.approx(.2)
    assert np.all(short.target.weights <= .1 + 1e-10)


@pytest.mark.parametrize('kind', ['SIMPLE_FEASIBLE', 'JOINT_REUSE'])
def test_locked_units_and_cap_saturation_remain_real(kind):
    w = np.zeros(12); w[0] = .17
    locked = np.zeros(12, bool); locked[0] = True
    decision = np.ones(12, bool); decision[0] = False
    r = evaluate(kind, context(12, weights=w, locked=locked, decision=decision))
    assert not r.target.explicit_mask[0, 0]
    assert r.target.weights[0, 0] == 0
    assert r.target.weights.sum() + .17 == pytest.approx(1)
    assert r.receipt['locked_slots'] == 1


@pytest.mark.parametrize('kind', ['SIMPLE_FEASIBLE', 'JOINT_REUSE'])
def test_no_buy_held_cannot_increase_and_capacity_repair_is_not_a_whitelist(kind):
    w = np.zeros(25); w[0] = .013
    buy = np.ones(25, bool); buy[0] = False
    mu = np.linspace(.01, .02, 25); mu[0] = 10
    r = evaluate(kind, context(25, weights=w, buy=buy), mu=mu)
    assert r.target.weights[0, 0] <= .013 + 1e-10
    assert r.target.weights.sum() == pytest.approx(1)
    assert np.count_nonzero(r.target.weights > 1e-10) <= 20


@pytest.mark.parametrize('kind', ['SIMPLE_FEASIBLE', 'JOINT_REUSE'])
def test_all_locked_and_no_eligible_are_valid_cash_results(kind):
    w = np.full(20, .02)
    r = evaluate(kind, context(20, weights=w, locked=np.ones(20, bool), decision=np.zeros(20, bool)))
    assert r.target.weights.sum() == 0
    assert not r.target.explicit_mask.any()
    assert r.receipt['maximum_feasible_gross'] == pytest.approx(.4)
    empty = evaluate(kind, context(7, decision=np.zeros(7, bool), buy=np.zeros(7, bool)))
    assert empty.receipt['maximum_feasible_gross'] == 0
    assert empty.receipt['residual_cash_weight'] == 1


def test_simple_is_equal_and_ticker_ties_are_deterministic():
    c = context(25)
    result = evaluate('SIMPLE_FEASIBLE', c, mu=np.ones(25))
    assert np.flatnonzero(result.target.weights[0]).tolist() == list(range(20))
    assert np.allclose(result.target.weights[0, :20], .05)
    reverse = replace(c, tickers=c.tickers[::-1])
    other = evaluate('SIMPLE_FEASIBLE', reverse, mu=np.ones(25))
    assert set(reverse.tickers[other.target.weights[0] > 0]) == set(c.tickers[:20])


def test_missing_held_forecast_cannot_be_hidden_by_ineligibility_or_lock():
    w = np.zeros(12); w[0] = .03
    decision = np.ones(12, bool); decision[0] = False
    mu = np.ones(12); mu[0] = np.nan
    with pytest.raises(FeasiblePolicyBlocked, match='REQUIRED_FORECAST_UNAVAILABLE'):
        evaluate('SIMPLE_FEASIBLE', context(12, weights=w, decision=decision), mu=mu)


def test_unrequired_forecast_cells_do_not_shrink_required_population():
    decision = np.ones(12, bool); decision[-1] = False
    buy = decision.copy(); mu = np.ones(12); mu[-1] = np.nan
    result = evaluate('JOINT_REUSE', context(12, decision=decision, buy=buy), mu=mu)
    assert result.receipt['required_asset_count'] == 11
    assert result.target.weights[0, -1] == 0
    assert result.target.weights.sum() == pytest.approx(1)


def test_same_capacity_rule_is_independent_of_opportunity_values():
    c = context(8)
    a = evaluate('SIMPLE_FEASIBLE', c, mu=np.arange(8.))
    b = evaluate('JOINT_REUSE', c, mu=-np.arange(8.))
    assert a.receipt['maximum_feasible_gross'] == b.receipt['maximum_feasible_gross']
    assert feasible_capacity(c)['investment_budget'] == pytest.approx(.8)


def q_args(n=12):
    return ('mean_variance', np.linspace(.01, .02, n), np.full(n, .03), np.eye(n)*.002,
            np.zeros(n), np.zeros(n, bool), np.ones(n, bool), np.ones(n, bool), 20, np.arange(n))


def test_allocator_omitted_budget_matches_explicit_original_one_exactly():
    a = allocate_q(*q_args())
    b = allocate_q(*q_args(), investment_budget=1.)
    assert np.array_equal(a.q, b.q)
    assert (a.iterations, a.residual, a.objective, a.status) == (b.iterations, b.residual, b.objective, b.status)
    assert a.q.sum() == pytest.approx(1)


@pytest.mark.parametrize('budget', [-.01, 1.01, np.nan, np.inf])
def test_allocator_rejects_invalid_investment_budget(budget):
    with pytest.raises(AllocationUnavailable, match='INVALID_INVESTMENT_BUDGET'):
        allocate_q(*q_args(), investment_budget=budget)


def test_allocator_budget_below_actual_locked_weight_fails():
    args = list(q_args()); args[4][0] = .2; args[5][0] = True
    with pytest.raises(AllocationUnavailable, match='INVESTMENT_BUDGET_BELOW_RESERVED_WEIGHT'):
        allocate_q(*args, investment_budget=.1)


def test_joint_requires_caller_qualified_existing_covariance():
    c = context(12)
    with pytest.raises(FeasiblePolicyBlocked, match='CALLER_QUALIFIED_EXISTING_COVARIANCE_REQUIRED'):
        feasible_target('JOINT_REUSE', np.ones(12), np.ones(12), np.eye(12), c)


def test_callable_transports_target_and_receipt_only():
    policy = ReusedFeasiblePolicy('SIMPLE_FEASIBLE', lambda day, ctx: dict(mu=np.ones(8), uncertainty=np.ones(8)))
    target = policy(0, context(8))
    assert target.weights.sum() == pytest.approx(.8)
    assert len(policy.diagnostics) == 1
    assert policy.diagnostics[0]['strict_PIT'] is False


def test_actual_current_state_changes_reserved_capacity_causally():
    w = np.full(8, .04)
    locked = np.ones(8, bool)
    before = feasible_capacity(context(8))
    after = feasible_capacity(context(8, weights=w, locked=locked, decision=np.zeros(8, bool)))
    assert before['investment_budget'] == pytest.approx(.8)
    assert after['investment_budget'] == pytest.approx(.32)


def test_simple_rank_magnitude_cannot_turn_equal_top20_into_ten_cap_names():
    c = context(25)
    a = evaluate('SIMPLE_FEASIBLE', c, mu=np.arange(25.) * 1000)
    b = evaluate('SIMPLE_FEASIBLE', c, mu=np.arange(25.) / 100000)
    assert np.flatnonzero(a.target.weights[0]).tolist() == list(range(5, 25))
    assert np.allclose(a.target.weights[0, 5:], .05)
    np.testing.assert_array_equal(a.target.weights, b.target.weights)


@pytest.mark.parametrize('kind', ['SIMPLE_FEASIBLE', 'JOINT_REUSE'])
def test_receivable_nav_cannot_fund_stock_targets_or_be_called_cash(kind):
    c = context(20, weights=np.full(20, .02))
    c = replace(c, cash=np.array([300.]), cash_weight=np.array([.1]))
    r = evaluate(kind, c)
    assert r.receipt['spendable_stock_and_cash_weight'] == pytest.approx(.5)
    assert r.receipt['maximum_feasible_gross'] == pytest.approx(.5)
    assert r.target.weights.sum() == pytest.approx(.5)
    assert r.receipt['residual_cash_weight'] == pytest.approx(0)
    assert r.receipt['nonspendable_NAV_weight'] == pytest.approx(.5)


@pytest.mark.parametrize('name,value', [
    ('cash', np.array([[3000.]])), ('nav', np.array([[3000.]])),
    ('cash_weight', np.array([[1.]])),
])
def test_account_cash_and_nav_shape_is_single_account(name, value):
    with pytest.raises(FeasiblePolicyBlocked, match='ACCOUNT_CONTEXT_SHAPE_MISMATCH:' + name):
        feasible_capacity(replace(context(), **{name: value}))


@pytest.mark.parametrize('cash,weight', [(np.nan, 1.), (np.inf, 1.), (-1., 0.),
                                       (3000., np.nan), (3000., -1.), (3000., .5)])
def test_invalid_or_inconsistent_cash_is_blocked(cash, weight):
    c = replace(context(), cash=np.array([cash]), cash_weight=np.array([weight]))
    with pytest.raises(FeasiblePolicyBlocked, match='ACTUAL_LIQUID_CASH_STATE_INVALID'):
        feasible_capacity(c)


def test_stock_and_cash_cannot_exceed_total_nav():
    c = context(20, weights=np.full(20, .02))
    c = replace(c, cash=np.array([3000.]), cash_weight=np.array([1.]))
    with pytest.raises(FeasiblePolicyBlocked, match='STOCK_AND_CASH_EXCEED_ACCOUNT_NAV'):
        feasible_capacity(c)


@pytest.mark.parametrize('kind', ['SIMPLE_FEASIBLE', 'JOINT_REUSE'])
def test_receivable_and_locked_stock_share_same_real_liquid_budget(kind):
    w = np.zeros(20); w[0] = .4
    locked = np.zeros(20, bool); locked[0] = True
    decision = ~locked
    c = context(20, weights=w, locked=locked, decision=decision)
    c = replace(c, cash=np.array([300.]), cash_weight=np.array([.1]))
    r = evaluate(kind, c)
    assert r.target.weights.sum() + .4 == pytest.approx(.5)
    assert r.receipt['nonspendable_NAV_weight'] == pytest.approx(.5)


@pytest.mark.parametrize('kind', ['SIMPLE_FEASIBLE', 'JOINT_REUSE'])
@pytest.mark.parametrize('cash_weight', [1., .5])
def test_empty_required_axis_keeps_cash_and_nonspendable_rights_without_stock(kind, cash_weight):
    c = context(0)
    c = replace(c, cash=np.array([3000.*cash_weight]), cash_weight=np.array([cash_weight]))
    result = evaluate(kind, c)
    assert result.target.weights.shape == result.target.explicit_mask.shape == (1, 0)
    assert result.target.weights.sum() == 0
    assert result.receipt['maximum_feasible_gross'] == 0
    assert result.receipt['residual_cash_weight'] == pytest.approx(cash_weight)
    assert result.receipt['nonspendable_NAV_weight'] == pytest.approx(1-cash_weight)



@pytest.mark.parametrize('cash_weight', [1., .1])
def test_pto_uses_actual_spendable_cash_locks_and_outpool_permissions(cash_weight):
    w=np.zeros(25);w[0]=.15;w[1]=.02
    locked=np.zeros(25,bool);locked[0]=True
    buy=np.ones(25,bool);buy[:2]=False
    c=context(25,weights=w,locked=locked,buy=buy,decision=~locked)
    cash=min(cash_weight,1-w.sum())
    c=replace(c,cash=np.array([3000*cash]),cash_weight=np.array([cash]))
    r=evaluate('PTO_REUSE_ROBUST_COST',c)
    effective=np.where(r.target.explicit_mask[0],r.target.weights[0],w)
    assert effective[0]==pytest.approx(.15)
    assert effective[1]<=.02+1e-10
    assert effective.sum()==pytest.approx(w.sum()+cash)
    assert np.count_nonzero(effective>1e-10)<=20
    assert r.receipt['uncertainty_consumed_in_objective']
    assert r.receipt['signal_known_cost_consumed_in_objective']
    np.testing.assert_allclose(np.array(r.receipt['q'])*r.receipt['gross'],effective)
    assert not r.receipt['frozen_historical_identity']



def test_raw_source_descendant_uses_original_rule_not_pto_mean_or_equal_weights():
    c=context(25);mu=np.arange(25,dtype=float)
    r=feasible_target('RAW_A2_SOURCE_REUSE',mu,np.zeros(25),None,c)
    assert r.target.weights.sum()==pytest.approx(.95)
    np.testing.assert_array_equal(np.flatnonzero(r.target.weights[0]),np.arange(5,25))
    np.testing.assert_allclose(r.target.weights[0,5:],.0475)
    assert r.receipt['original_rule_owner']=='JointResearchPolicy:raw'
    assert r.receipt['original_diagnostics'][0]['status']!='FALLBACK_PRESERVE_UNITS'


def test_raw_source_descendant_does_not_turn_no_forecast_into_qualified_hold():
    with pytest.raises(FeasiblePolicyBlocked,match='RAW_REQUIRED_SOURCE'):
        feasible_target('RAW_A2_SOURCE_REUSE',np.full(25,np.nan),np.zeros(25),None,context(25))


def test_raw_fallback_reports_original_failure_reason(monkeypatch):
    import pandas as pd
    from scripts.research.a2.inference.joint_portfolio_policy import JointResearchPolicy
    def fail(self, day, ctx):
        self.callback(pd.DataFrame([dict(status='FALLBACK_PRESERVE_UNITS',
            failure_reason='SYNTHETIC_ORIGINAL_REASON')]))
        raise AssertionError('Fallback must have been rejected')
    monkeypatch.setattr(JointResearchPolicy,'__call__',fail)
    with pytest.raises(FeasiblePolicyBlocked,match='ORIGINAL_RAW_POLICY_FALLBACK:SYNTHETIC_ORIGINAL_REASON'):
        feasible_target('RAW_A2_SOURCE_REUSE',np.arange(25,dtype=float),np.zeros(25),None,context(25))
