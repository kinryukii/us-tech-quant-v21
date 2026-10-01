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

