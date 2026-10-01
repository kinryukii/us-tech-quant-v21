"""Feasibility, independent small-problem solutions and joint-tail tests."""
import numpy as np
import pytest
from scipy.optimize import minimize
from optimization import optimize, project_budget, _smooth_cvar, SPEC


def test_projection_never_levers_up_and_matches_independent_constrained_solution():
    x=np.array([[.02,.03,.01],[.4,.2,-.1]])
    budget=np.array([.95,.12])
    projected=project_budget(x,budget)
    np.testing.assert_allclose(projected[0],x[0])
    solved=minimize(lambda w:np.sum((w-x[1])**2),[.06,.06,0],bounds=[(0,.1)]*3,
                    constraints=[{"type":"ineq","fun":lambda w:.12-w.sum()}],method="SLSQP",options={"ftol":1e-13})
    assert solved.success
    np.testing.assert_allclose(projected[1],solved.x,atol=2e-7)


def test_positive_equal_is_threshold_rule_with_endogenous_cash():
    mu=np.array([[.003,.002,.001,-.001],[.0001,-.003,.001,.0]])
    result=optimize("positive_equal",mu,np.tile(np.eye(4),(2,1,1)),np.zeros_like(mu),[.15,.95],[4,4])
    np.testing.assert_allclose(result.weights,[[.075,.075,0,0],[0,0,0,0]])
    assert np.all(result.status=="RULE_COMPLETE")


@pytest.mark.parametrize("kind",["mean_variance","robust_mv"])
def test_mean_variance_and_robust_solve_match_independent_convex_small_problem(kind):
    mu=np.array([[.006,.004,.0015]])
    cov=np.array([[[.03,.012,.002],[.012,.02,.001],[.002,.001,.015]]])
    current=np.array([[.035,.025,.02]])
    scale=np.array([[.002,.001,.003]])
    reserved=np.array([[.0002,.0001,.0]])
    result=optimize(kind,mu,cov,current,[.12],[3],uncertainty=scale,risk_linear=reserved)
    adjusted=mu[0]-(.5*scale[0] if kind=="robust_mv" else 0)
    def obj(w):return -adjusted@w+2*w@cov[0]@w+4*reserved[0]@w+.001*np.abs(w-current[0]).sum()
    independent=minimize(obj,current[0],method="SLSQP",bounds=[(0,.1)]*3,
                         constraints=[{"type":"ineq","fun":lambda w:.12-w.sum()}],options={"ftol":1e-13,"maxiter":500})
    assert independent.success
    assert obj(result.weights[0])<=independent.fun+2e-8
    assert result.residual[0]<=SPEC["tolerance"]
    assert result.status[0]=="CONVERGED"
    assert "not a global" in result.residual_kind


def test_correlations_change_risk_allocation_and_cash_can_be_zero_invested():
    mu=np.array([[.007,.004]])
    current=np.zeros_like(mu)
    diagonal=np.array([[[.03,0],[0,.03]]])
    correlated=np.array([[[.03,.029],[.029,.03]]])
    a=optimize("mean_variance",mu,diagonal,current,[.95],[2])
    b=optimize("mean_variance",mu,correlated,current,[.95],[2])
    assert np.max(np.abs(a.weights-b.weights))>.005
    negative=optimize("mean_variance",-mu,diagonal,current,[.95],[2])
    assert negative.weights.sum()==0


def test_cvar_smoothed_solution_matches_independent_solve_and_accounts_for_locked_tail():
    mu=np.array([[.0025,.002]])
    scale=np.array([[.007,.008]])
    scenarios=np.array([[[-1.5,-1.5],[-1,-1],[-.4,-.6],[.2,.1],[.6,.8],[1.5,1.7],[.1,-.1],[-.2,.3],[.4,.2],[.3,.1]]])
    locked=np.array([[.003,.002,.001,-.001,-.002,-.003,0,.001,-.001,0]])
    current=np.array([[.02,.03]])
    result=optimize("cvar",mu,np.array([np.eye(2)*.0001]),current,[.15],[2],uncertainty=scale,scenarios=scenarios,reserved_joint_loss=locked)
    returns=mu[:,None,:]+scale[:,None,:]*scenarios
    def obj(w):
        cvar,_,_=_smooth_cvar(w[None,:],returns,locked)
        return -mu[0]@w+4*cvar[0]+.001*np.abs(w-current[0]).sum()
    independent=minimize(obj,current[0],method="SLSQP",bounds=[(0,.1)]*2,
                         constraints=[{"type":"ineq","fun":lambda w:.15-w.sum()}],options={"ftol":1e-12,"maxiter":500})
    assert independent.success
    assert obj(result.weights[0])<=independent.fun+2e-7
    assert result.residual[0]<=SPEC["tolerance"]
    assert np.isfinite(result.cvar_eta).all()
    # A hedge that pays in reserved-loss scenarios must change the gradient.
    w=np.array([[.04,.03]])
    _,g1,_=_smooth_cvar(w,returns)
    _,g2,_=_smooth_cvar(w,returns,locked)
    assert np.max(np.abs(g1-g2))>1e-4


def test_cvar_retains_joint_scenario_dependence_instead_of_marginal_independence():
    residual=np.array([-2,-1,-.5,0,.5,1,2,1,.5,0,-.5,-1],dtype=float)
    perfectly_correlated=np.stack([residual,residual],axis=1)[None,:,:]
    hedge=np.stack([residual,-residual],axis=1)[None,:,:]
    weights=np.array([[.05,.05]])
    cv1,_,_=_smooth_cvar(weights,.01*perfectly_correlated)
    cv2,_,_=_smooth_cvar(weights,.01*hedge)
    assert cv1[0]>cv2[0]+.0002
    mu=np.full((1,2),.004)
    scale=np.full((1,2),.01)
    a=optimize("cvar",mu,np.array([np.eye(2)*.0001]),np.zeros_like(mu),[.2],[2],uncertainty=scale,scenarios=perfectly_correlated)
    b=optimize("cvar",mu,np.array([np.eye(2)*.0001]),np.zeros_like(mu),[.2],[2],uncertainty=scale,scenarios=hedge)
    assert b.weights.sum()>a.weights.sum()+.02


def test_every_method_respects_per_row_budget_slots_and_ineligible_caps():
    rng=np.random.default_rng(20250928)
    s,n,h=8,20,24
    mu=rng.normal(.004,.004,(s,n));scale=np.full((s,n),.015)
    current=np.full((s,n),.02);budget=np.linspace(0,.95,s);slots=np.arange(s)*2
    cov=np.tile(np.eye(n)*.000225,(s,1,1));upper=np.full((s,n),.1);upper[:,1]=0
    scenarios=rng.normal(size=(s,h,n))
    for kind in ["positive_equal","mean_variance","robust_mv","cvar"]:
        result=optimize(kind,mu,cov,current,budget,slots,uncertainty=scale,scenarios=scenarios,upper=upper)
        assert np.all(result.weights>=0) and np.all(result.weights<=upper+1e-10)
        assert np.all(result.weights.sum(axis=1)<=budget+1e-9)
        assert np.all(np.count_nonzero(result.weights>0,axis=1)<=slots)
        assert np.isfinite(result.objective).all()
        assert set(result.status).issubset({"RULE_COMPLETE","CONVERGED","ITERATION_LIMIT"})


def test_cvar_cannot_silently_use_only_mv_reserved_correlation():
    with pytest.raises(ValueError,match="reserved_joint_loss"):
        optimize("cvar",np.ones((1,2))*.003,np.array([np.eye(2)]),np.zeros((1,2)),[.2],[2],uncertainty=np.ones((1,2))*.01,
                 scenarios=np.ones((1,3,2)),risk_linear=np.ones((1,2))*.001)


@pytest.mark.parametrize("kind",["mean_variance","robust_mv","cvar"])
def test_exact_fixed_point_dedup_is_identical_to_every_logical_iteration(kind):
    mu=np.array([[.01,.008],[.0001,.0001],[-.004,-.005],[.002,.0015]])
    current=np.array([[0.,0.],[0.,0.],[0.,0.],[.02,.01]])
    cov=np.tile(np.eye(2)*.0004,(4,1,1))
    scale=np.full((4,2),.01)
    scenarios=np.broadcast_to(np.array([[-1.,-1.],[-.5,.5],[.5,-.5],[1.,1.]])[None,:,:],(4,4,2))
    args=(kind,mu,cov,current,np.full(4,.2),np.full(4,2))
    cached=optimize(*args,uncertainty=scale,scenarios=scenarios)
    full=optimize(*args,uncertainty=scale,scenarios=scenarios,deduplicate_exact_fixed_points=False)
    np.testing.assert_array_equal(cached.weights,full.weights)
    np.testing.assert_array_equal(cached.status,full.status)
    np.testing.assert_array_equal(cached.iterations,full.iterations)
    np.testing.assert_array_equal(cached.objective,full.objective)
    np.testing.assert_array_equal(cached.residual,full.residual)
    assert np.any(cached.exact_fixed_point)
    assert np.any(cached.gradient_evaluations<full.gradient_evaluations)
