"""Five-session allocation, reservations and executable order-control tests."""
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.portfolio import joint_allocation_methods as allocation
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import AccountContext,TargetDecision


def inputs(n=25):
    mu=np.linspace(.005,.02,n)
    sigma=np.full(n,.01)
    covariance=np.diag(np.linspace(.0002,.002,n))+.00005
    current=np.zeros(n)
    locked=np.zeros(n,bool)
    allowed=np.ones(n,bool)
    rng=np.random.default_rng(7)
    scenarios=rng.multivariate_normal(mu,covariance,size=64)
    return mu,sigma,covariance,current,locked,allowed,allowed.copy(),20,np.arange(n),scenarios


@pytest.mark.parametrize("method",allocation.ALLOCATION_METHODS)
def test_every_allocation_objective_or_documented_equivalent_has_real_feasible_solver(method):
    mu,sigma,cov,current,locked,allowed,buy,slots,ranks,scenarios=inputs()
    result=allocation.allocate_q(method,mu,sigma,cov,current,locked,allowed,buy,slots,ranks,
                                scenarios=scenarios,reference=np.ones(len(mu))/len(mu))
    assert result.q.sum()==pytest.approx(1,abs=1e-8)
    assert np.count_nonzero(result.q>1e-10)<=20
    assert np.all(result.q>=-1e-10)
    assert np.max(result.q)<=.1+1e-8
    assert not result.global_optimum_claim
    if method=="l1_weight":
        assert "NO_SPARSITY" in result.equivalence
    if method=="cost_aware":
        assert "ZERO_FEE" in result.equivalence


def test_es_and_kelly_exact_aliases_no_duplicate_optimization_claim():
    args=inputs()
    for a,b in [("mean_es","mean_cvar"),("kelly","log_growth"),("concentration_penalty","l2_weight"),("uncertainty_penalty","robust_mean_variance")]:
        ra=allocation.allocate_q(a,*args[:-1],scenarios=args[-1])
        rb=allocation.allocate_q(b,*args[:-1],scenarios=args[-1])
        np.testing.assert_array_equal(ra.q,rb.q)
        assert ra.objective==rb.objective
        assert "ALIAS" in ra.equivalence


def test_missing_scenarios_and_reference_do_not_turn_into_mean_variance_substitutes():
    args=inputs()
    for method in ("mean_cvar","mean_semivariance","log_growth"):
        with pytest.raises(allocation.AllocationUnavailable,match="SCENARIOS"):
            allocation.allocate_q(method,*args[:-1])
    for method in ("reference_regularization","tracking_error"):
        with pytest.raises(allocation.AllocationUnavailable,match="REFERENCE"):
            allocation.allocate_q(method,*args[:-1])


def test_reserved_holding_and_out_of_pool_upper_never_add_capital():
    mu,sigma,cov,current,locked,allowed,buy,slots,ranks,scenarios=inputs()
    current[0]=.06;locked[0]=True;allowed[0]=False;buy[0]=False
    current[1]=.02;buy[1]=False
    mu[1]=1
    result=allocation.allocate_q("robust_mean_variance",mu,sigma,cov,current,locked,allowed,buy,19,ranks)
    assert result.q[0]==pytest.approx(.06)
    assert result.q[1]<=.02+1e-10
    assert np.count_nonzero(result.q>1e-10)<=20
    assert result.q.sum()==pytest.approx(1)


def test_volatility_target_uses_252_divided_by_5_and_preserves_reserved_units():
    q=np.ones(20)/20
    cov=np.diag(np.full(20,.04))
    transformed,gross=allocation.exposure(q,cov,np.zeros(20),"volatility_targeting")
    assert gross==pytest.approx(.1/np.sqrt((252/5)*(q@cov@q)))
    assert transformed.sum()==pytest.approx(1)
    reserved=np.zeros(20);reserved[0]=.005
    q[0]=.005;q[1:]=.995/19
    transformed,gross=allocation.exposure(q,cov,reserved,"risk_constrained_cash")
    assert (transformed*gross)[0]==pytest.approx(.005)
    assert gross>=reserved.sum()
    assert gross**2*(transformed@cov@transformed)*(252/5)==pytest.approx(.1**2)


def context(n=25):
    return AccountContext(0,pd.Timestamp("2024-01-02"),pd.Timestamp("2024-01-02"),("v24",),
        np.array([f"T{i:02}" for i in range(n)]),np.zeros((1,n)),np.zeros((1,n)),
        np.array([3000.]),np.array([1.]),np.array([3000.]),np.zeros((1,n),bool),
        np.array([0.]),np.array([0]),np.array([1.]),np.array([20]),
        np.ones((1,n),bool),np.zeros((1,n),bool),np.ones((1,n),bool),
        np.ones((1,n),bool),np.zeros((1,n),bool),20,.1,1.)


def parameters():
    return {"optimizer":{"risk_penalty":4,"uncertainty_penalty":.5,"max_q":.1,"max_positions":20,
                         "iterations":128,"tolerance":2e-6,"turnover_cost":0},
            "action":{"partial_rebalance":.5,"full_action_ablation":1},
            "gross":{"fixed":1,"volatility_target_annual":.1}}


def test_zero_gross_is_actual_explicit_sell_target_and_original_frozen_source_stays_bound():
    n=25;ctx=context(n)
    current=np.zeros((1,n));current[0,:10]=.05
    ctx=replace(ctx,current_weights=current,current_units=(current>0).astype(float),
                cash=np.array([1500.]),cash_weight=np.array([.5]))
    model=allocation.JointAllocationPolicy(["v24"],np.full((1,1,n),-.01),np.full((1,1,n),.01),
        {(2024,"DIAG"):np.eye(n)*.001},roles={"v24":{"risk":"DIAG","rho":1}},
        parameters=parameters(),method="mean_variance",gross_method="dynamic")
    result=model(0,ctx)
    assert result.explicit_mask[0,:10].all()
    assert np.max(result.weights)==0


def test_turnover_hard_limit_works_from_empty_cash_and_never_creates_40_name_union():
    ctx=context()
    class Base:
        def __call__(self,day,ctx):
            target=np.zeros_like(ctx.current_weights);target[0,-20:]=.05
            return TargetDecision(target,ctx.decision_mask)
    controlled=allocation.TradingControlPolicy(Base(),"turnover_limit")
    target=controlled(0,ctx).weights
    assert np.abs(target-ctx.current_weights).sum()<=.2+1e-10
    assert target.sum()==pytest.approx(.2)
    n=40;ctx=context(n)
    current=np.zeros((1,n));current[0,:20]=.05
    ctx=replace(ctx,current_weights=current,current_units=(current>0).astype(float),
                cash=np.array([0.]),cash_weight=np.array([0.]))
    target=controlled(0,ctx).weights
    assert np.count_nonzero(target>1e-10)<=20
    assert np.abs(target-current).sum()<=.2+1e-10


def test_no_trade_hold_preserves_units_mask_and_discrete_contract_is_explicit():
    ctx=context()
    current=np.zeros((1,25));current[0,0]=.05
    ctx=replace(ctx,current_weights=current,current_units=(current>0).astype(float))
    class Base:
        def __call__(self,day,ctx):
            target=current.copy();target[0,0]+=.0001
            return TargetDecision(target,ctx.decision_mask)
    result=allocation.TradingControlPolicy(Base(),"no_trade_band")(0,ctx)
    assert not result.explicit_mask[0,0]
    with pytest.raises(allocation.AllocationUnavailable,match="INTEGER_EXECUTION"):
        allocation.TradingControlPolicy(Base(),"discrete_allocation")

def test_partial_rebalancing_cannot_emit_illegal_target_when_old_weight_grows():
    ctx=context()
    current=np.zeros((1,25));current[0,0]=.15
    ctx=replace(ctx,current_weights=current,current_units=(current>0).astype(float))
    class Base:
        def __call__(self,day,ctx):
            target=np.zeros_like(current);target[0,0]=.1
            return TargetDecision(target,ctx.decision_mask)
    result=allocation.TradingControlPolicy(Base(),"partial_rebalance")(0,ctx)
    assert result.weights[0,0]==pytest.approx(.1)

def test_negative_covariance_can_hedge_reserved_risk_above_standalone_limit():
    cov=np.full((10,10),.002)
    cov[0,0]=.16
    cov[0,1:]=-.0178;cov[1:,0]=-.0178
    cov+=np.eye(10)*1e-12
    assert np.linalg.eigvalsh(cov).min()>0
    q=np.full(10,.1);reserved=np.zeros(10);reserved[0]=.1
    assert reserved@cov@reserved>allocation.SPEC["volatility_target_annual"]**2/allocation.SPEC["annualization"]
    transformed,gross=allocation.exposure(q,cov,reserved,"risk_constrained_cash")
    assert gross==pytest.approx(1)
    np.testing.assert_allclose(transformed,q)
    assert gross**2*(transformed@cov@transformed)*allocation.SPEC["annualization"]<=.1**2


def test_risk_cash_selects_upper_feasible_quadratic_root_with_negative_cross_risk():
    cov=np.array([[.16,-.055],[-.055,.02]])
    cov+=np.eye(2)*1e-12
    q=np.array([.1,.9]);reserved=np.array([.1,0.])
    transformed,gross=allocation.exposure(q,cov,reserved,"volatility_targeting")
    assert 0<gross<1
    w=transformed*gross
    assert w[0]==pytest.approx(.1)
    assert (w@cov@w)*allocation.SPEC["annualization"]==pytest.approx(.1**2)

def test_unregistered_scientific_parameter_override_is_rejected():
    args=inputs()
    with pytest.raises(ValueError,match="UNREGISTERED_ALLOCATION_PARAMETER"):
        allocation.allocate_q("mean_variance",*args[:-1],parameters={"risk_penalty":3})



def _pit_risk_budget_inputs(future_names=(), *, holdings=False):
    """Canonical full-array ranks with only current support declared eligible."""
    names = [f"B{i:02d}" for i in range(12)]
    if holdings:
        names += ["A_HELD_OUTPOOL", "Z_HELD_LOCKED"]
    full = np.asarray(sorted(names + list(future_names)), dtype=str)
    count = len(full)
    mu = np.zeros(count)
    uncertainty = np.full(count, .01)
    variance = np.full(count, .001)
    current = np.zeros(count)
    locked = np.zeros(count, bool)
    allowed = np.isin(full, names)
    buy = allowed.copy()
    if holdings:
        outpool = np.flatnonzero(full == "A_HELD_OUTPOOL")[0]
        reserved = np.flatnonzero(full == "Z_HELD_LOCKED")[0]
        current[outpool], current[reserved] = .04, .06
        buy[outpool] = False
        locked[reserved] = True
        allowed[reserved] = buy[reserved] = False
    ranks = np.argsort(np.argsort(full, kind="stable"), kind="stable")
    args = (mu, uncertainty, variance, current, locked, allowed, buy, 20-int(locked.sum()), ranks)
    return full, names, args


@pytest.mark.parametrize("future_names", [
    ["A_FUTURE"], ["B05_FUTURE", "B09_FUTURE"], ["A_FUTURE", "B05_FUTURE", "ZZ_FUTURE"],
])
def test_risk_budget_current_legal_weights_ignore_unavailable_future_roster_insertions(future_names):
    base_names, legal, base = _pit_risk_budget_inputs()
    full_names, _, extended = _pit_risk_budget_inputs(future_names)
    before = allocation.allocate_q("risk_budgeting", *base)
    after = allocation.allocate_q("risk_budgeting", *extended)
    selected = np.asarray([np.flatnonzero(full_names == name)[0] for name in base_names])
    np.testing.assert_allclose(before.q, after.q[selected], rtol=0, atol=1e-11)
    assert np.all(after.q[np.isin(full_names, future_names)] == 0)
    # The old absolute-rank modulo rule really changes despite fixed legal order.
    old = 1 + base[-1] % 3
    contaminated = 1 + extended[-1][selected] % 3
    assert np.any(old != contaminated)


def test_risk_budget_depends_on_relative_active_order_not_absolute_rank_values():
    _, _, args = _pit_risk_budget_inputs()
    shifted = (*args[:-1], 100 + 7*args[-1])
    first = allocation.allocate_q("risk_budgeting", *args)
    second = allocation.allocate_q("risk_budgeting", *shifted)
    np.testing.assert_array_equal(first.q, second.q)
    assert first.objective == second.objective


def test_risk_budget_current_support_includes_locked_and_out_of_pool_holdings():
    base_names, _, base = _pit_risk_budget_inputs(holdings=True)
    full_names, _, extended = _pit_risk_budget_inputs(["A_FUTURE", "B05_FUTURE"], holdings=True)
    first = allocation.allocate_q("risk_budgeting", *base)
    second = allocation.allocate_q("risk_budgeting", *extended)
    selected = np.asarray([np.flatnonzero(full_names == name)[0] for name in base_names])
    np.testing.assert_allclose(first.q, second.q[selected], rtol=0, atol=1e-9)
    assert second.q[full_names == "Z_HELD_LOCKED"][0] == pytest.approx(.06)
    assert second.q[full_names == "A_HELD_OUTPOOL"][0] <= .04+1e-11
    assert second.q.sum() == pytest.approx(1)


def test_risk_budget_may_change_when_new_name_becomes_currently_legal():
    names, _, args = _pit_risk_budget_inputs(["A_NEW"])
    unknown = allocation.allocate_q("risk_budgeting", *args)
    now_allowed, now_buy = args[5].copy(), args[6].copy()
    now_allowed[names == "A_NEW"] = now_buy[names == "A_NEW"] = True
    legal_args = (*args[:5], now_allowed, now_buy, *args[7:])
    disclosed = allocation.allocate_q("risk_budgeting", *legal_args)
    assert unknown.q[names == "A_NEW"][0] == 0
    assert disclosed.q[names == "A_NEW"][0] > 0
    assert np.max(np.abs(unknown.q-disclosed.q)) > 1e-3


def test_nonzero_friction_penalty_reduces_signal_known_expected_turnover():
    """Tiny forecast edge should not justify a more expensive replacement."""
    n=20
    mu=np.zeros(n);mu[10:]=.0003
    sigma=np.full(n,.01);cov=np.eye(n)*.00001
    current=np.r_[np.full(10,.1),np.zeros(10)]
    locked=np.zeros(n,bool);allowed=np.ones(n,bool)
    args=(mu,sigma,cov,current,locked,allowed,allowed,20,np.arange(n))
    blind=allocation.allocate_q("mean_variance",*args)
    aware=allocation.allocate_q("cost_aware",*args,execution_friction_bps=10)
    assert np.abs(aware.q-current).sum()<np.abs(blind.q-current).sum()
    assert aware.q.sum()==pytest.approx(1)
    assert "SIGNAL_KNOWN" in aware.equivalence
    assert not aware.global_optimum_claim


def test_zero_friction_opt_in_remains_exact_mean_variance_alias():
    args=inputs()
    blind=allocation.allocate_q("mean_variance",*args[:-1])
    aware=allocation.allocate_q("cost_aware",*args[:-1],execution_friction_bps=0)
    np.testing.assert_array_equal(blind.q,aware.q)
    assert aware.objective==blind.objective
    assert "ZERO_FEE" in aware.equivalence


@pytest.mark.parametrize("value",[-1,float("nan"),float("inf"),10000])
def test_invalid_execution_friction_is_rejected(value):
    args=inputs()
    with pytest.raises(ValueError,match="EXECUTION_FRICTION"):
        allocation.allocate_q("cost_aware",*args[:-1],execution_friction_bps=value)


def test_execution_friction_cannot_silently_modify_other_objectives():
    args=inputs()
    with pytest.raises(ValueError,match="COST_AWARE_ROLE"):
        allocation.allocate_q("robust_mean_variance",*args[:-1],execution_friction_bps=10)


def test_cost_aware_policy_requires_a_matched_full_rebalance_fixed_gross_pair():
    n=25;ctx=context(n)
    kwargs=dict(roles={"v24":{"risk":"DIAG","rho":1}},parameters=parameters(),
                method="cost_aware",gross_method="fixed",execution_friction_bps=10)
    model=allocation.JointAllocationPolicy(["v24"],np.full((1,1,n),.01),np.full((1,1,n),.01),
                                          {(2024,"DIAG"):np.eye(n)*.001},**kwargs)
    result=model(0,ctx)
    assert np.isfinite(result.weights).all()
    assert model.allocation_receipts[0]["equivalence"].startswith("SIGNAL_KNOWN")
    kwargs["roles"]={"v24":{"risk":"DIAG","rho":.5}}
    with pytest.raises(ValueError,match="FULL_REBALANCE"):
        allocation.JointAllocationPolicy(["v24"],np.full((1,1,n),.01),np.full((1,1,n),.01),
                                        {(2024,"DIAG"):np.eye(n)*.001},**kwargs)



def test_robust_cost_objective_consumes_uncertainty_risk_and_both_trade_legs():
    n=20
    current=np.r_[np.full(10,.1),np.zeros(10)]
    mu=np.r_[np.zeros(10),np.full(10,.0003)]
    sigma=np.full(n,.01);cov=np.eye(n)*.00001
    mask=np.ones(n,bool);lock=np.zeros(n,bool)
    args=(mu,sigma,cov,current,lock,mask,mask,20,np.arange(n))
    zero=allocation.allocate_q('robust_cost_aware',*args)
    original=allocation.allocate_q('robust_mean_variance',*args)
    np.testing.assert_array_equal(zero.q,original.q)
    assert zero.objective==original.objective
    aware=allocation.allocate_q('robust_cost_aware',*args,execution_friction_bps=10)
    assert np.abs(aware.q-current).sum()<np.abs(zero.q-current).sum()
    q=aware.q
    expected=2*float(q@cov@q)-float((mu-.5*sigma)@q)+.001*float(np.abs(q-current).sum())
    assert aware.objective==pytest.approx(expected,abs=1e-12)
    high_sigma=sigma.copy();high_sigma[:10]=1.
    uncertain=allocation.allocate_q('robust_cost_aware',mu,high_sigma,*args[2:],execution_friction_bps=10)
    assert uncertain.q[:10].sum()<aware.q[:10].sum()
    high_risk=cov.copy();high_risk[:10,:10]+=np.eye(10)*.1
    risky=allocation.allocate_q('robust_cost_aware',mu,sigma,high_risk,*args[3:],execution_friction_bps=10)
    assert risky.q[:10].sum()<aware.q[:10].sum()
