from types import SimpleNamespace
import numpy as np
import pytest
from scripts.research.a2.inference import joint_method_space_optimizer_r6 as q
from scripts.research.a2.risk.shared_risk_budget_r2 import StateBudget,StateCache,StateBudgetError


def inputs():
    n=12;rng=np.random.default_rng(62026)
    raw=rng.normal(.001,.006,(100,n));cov=np.cov(raw,rowvar=False)
    return dict(mu=np.linspace(.0008,.0014,n),uncertainty=np.full(n,.002),covariance=cov,
        current=np.zeros(n),locked=np.zeros(n,bool),allowed=np.ones(n,bool),buy_allowed=np.ones(n,bool),
        slots=20,ticker_rank=np.arange(n),scenarios=raw,prior_scale=.009)


def solve_cache():
    b=StateBudget(0);c=StateCache(b,source_identity="SYNTHETIC_Q_R6",cutoff="2025-01-01T00:00:00Z",
        assets=tuple("A"+str(i) for i in range(12)),return_coordinate="shareholder_value_open_return",horizon=5,identity_epoch="SYN1")
    return b,lambda name,values,compute:c.learn("deterministic_transform",name,values,compute)


@pytest.mark.parametrize("method",q.METHODS)
def test_frozen_recipes_obey_full_candidate_account_constraints(method):
    i=inputs(); result=q.allocate_q(method,**i)
    target=result.gross_cap*result.allocation.q
    assert np.isfinite(target).all() and np.all(target>=-1e-8)
    assert target.sum()<=1+1e-8 and np.max(target)<=.1+1e-8
    assert np.count_nonzero(target>1e-10)<=20
    assert result.whole_objective_calls==(0 if method in {"HRP","HERC"} else 1)
    assert result.allocation.global_optimum_claim is False


def test_herc_sibling_formula_is_true_two_child_erc_not_hrp_variance_split():
    covariance=np.diag([1.,4.]);w,ops=q._herc(covariance,np.arange(2))
    assert np.allclose(w,[2/3,1/3]) and ops==1
    risk=w*(covariance@w)
    assert np.isclose(risk[0],risk[1])
    assert not np.allclose(w,[.8,.2])


def test_herc_has_no_hidden_optimizer_invocation(monkeypatch):
    monkeypatch.setattr(q,"minimize",lambda *a,**k:pytest.fail("Hidden optimizer"))
    result=q.allocate_q("HERC",**inputs(),solve=lambda *a:pytest.fail("Solve charged"))
    assert result.whole_objective_calls==0
    assert result.deterministic_operations["binary_sibling_closed_forms"]==11


def test_exact_aliases_share_complete_context_calls_only():
    b,cache=solve_cache();i=inputs()
    a=q.allocate_q("MV",**i,solve=cache)
    z=q.allocate_q("QUADRATIC_UTILITY",**i,solve=cache)
    assert a.whole_objective_calls==1 and z.whole_objective_calls==0
    assert np.array_equal(a.allocation.q,z.allocation.q)
    q.allocate_q("ERC",**i,solve=cache)
    p=q.allocate_q("RISK_PARITY",**i,solve=cache)
    assert p.whole_objective_calls==0 and len(b.events)==2


def test_ordinary_same_values_different_cost_do_not_charge_again():
    b,cache=solve_cache();i=inputs()
    q.allocate_q("MV",**i,execution_friction_bps=5,solve=cache)
    second=q.allocate_q("MV",**i,execution_friction_bps=20,solve=cache)
    assert second.whole_objective_calls==0 and len(b.events)==1


def test_current_account_mutation_prevents_false_cross_cost_reuse():
    b,cache=solve_cache();i=inputs()
    q.allocate_q("MV",**i,execution_friction_bps=5,solve=cache)
    other=dict(i,current=np.full(12,1/12))
    result=q.allocate_q("MV",**other,execution_friction_bps=20,solve=cache)
    assert result.whole_objective_calls==1 and len(b.events)==2


@pytest.mark.parametrize("method",["TURNOVER_MV","TURNOVER_CVAR","ENTROPY_TURNOVER"])
def test_cost_sensitive_objectives_bind_actual_friction(method):
    b,cache=solve_cache();i=inputs();i["current"]=np.full(12,1/12)
    q.allocate_q(method,**i,execution_friction_bps=5,solve=cache)
    q.allocate_q(method,**i,execution_friction_bps=20,solve=cache)
    assert len(b.events)==2


@pytest.mark.parametrize("method",["CVAR","SEMIVARIANCE","MAD","ENTROPIC","DRO","LOG_UTILITY","FRACTIONAL_KELLY","TURNOVER_CVAR","ENTROPY_TURNOVER"])
def test_missing_genuine_scenarios_blocks_before_optimizer(method):
    i=inputs();i["scenarios"]=None;calls=[]
    with pytest.raises((q.QInputBlocked,q.owner.AllocationUnavailable)):
        q.allocate_q(method,**i,solve=lambda *a:calls.append(a))
    assert calls==[]


def test_fractional_kelly_retains_funding_cap_and_reuses_same_log_solution():
    b,cache=solve_cache();i=inputs()
    full=q.allocate_q("LOG_UTILITY",**i,solve=cache)
    half=q.allocate_q("FRACTIONAL_KELLY",**i,solve=cache)
    assert half.whole_objective_calls==0
    assert np.isclose(half.gross_cap,.5*full.gross_cap)
    assert np.allclose(half.allocation.q,full.allocation.q,atol=1e-8)


def test_complete_scenarios_not_covariance_factor_samples():
    i=inputs();i["scenarios"]=np.zeros((29,12));calls=[]
    with pytest.raises(q.QInputBlocked,match="GENUINE_MATURE"):
        q.allocate_q("CVAR",**i,solve=lambda *a:calls.append(a))
    assert calls==[]


def test_held_forecast_missing_blocks_even_when_locked():
    i=inputs();i["current"][0]=.1;i["locked"][0]=True;i["mu"][0]=np.nan;calls=[]
    with pytest.raises(q.QInputBlocked,match="ACTUAL_REQUIRED"):
        q.allocate_q("MV",**i,solve=lambda *a:calls.append(a))
    assert calls==[]


def test_full_candidate_solver_does_not_raw_top20_prefilter():
    i=inputs();i["slots"]=10
    z=q.allocate_q("MV",**i)
    assert len(z.allocation.q)==12 and np.count_nonzero(z.allocation.q>1e-8)==10


def test_failure_consumes_reservation_and_never_scientifically_retries(monkeypatch):
    b,cache=solve_cache();i=inputs();calls=[]
    def fail(*a,**k):calls.append(1);return SimpleNamespace(success=False,x=np.zeros(12),message="fixed failure")
    monkeypatch.setattr(q,"minimize",fail)
    with pytest.raises(q.QInputBlocked,match="FIXED_SLSQP_FAILED"):
        q.allocate_q("MAD",**i,solve=cache)
    with pytest.raises(StateBudgetError,match="FAILED"):
        q.allocate_q("MAD",**i,solve=cache)
    assert calls==[1] and len(b.events)==1 and b.events[0]["status"]=="FAILED"


def test_finite_budget_counts_backend_not_every_policy_day():
    paths=["MV"]*115
    assert q.solve_upper(paths,143,mpc_calls=4*752)["whole_objective_upper"]==19453
    assert q.solve_upper(paths,143,mpc_calls=4*752)["within_20000"]
    assert q.solve_upper(["MV"]*120,752)["whole_objective_upper"]==90240
    assert not q.solve_upper(["MV"]*120,752)["within_20000"]
    assert q.solve_upper(["HERC","HRP"],752)["whole_objective_upper"]==0


@pytest.mark.parametrize("bad",[1,0,7,30])
def test_nonfrozen_cost_rejected_before_any_call(bad):
    calls=[]
    with pytest.raises(q.QInputBlocked,match="FROZEN_COST"):
        q.allocate_q("MV",**inputs(),execution_friction_bps=bad,solve=lambda *a:calls.append(a))
    assert calls==[]


def test_real_mode_requires_existing_guarded_budget_callback():
    with pytest.raises(q.QInputBlocked,match="RESERVATION_CALLBACK"):
        q.allocate_q("MV",**inputs(),synthetic=False)


def test_proximal_has_one_mv_solve_and_separate_transform():
    z=q.allocate_q("PROXIMAL",**inputs())
    assert z.whole_objective_calls==1
    assert z.deterministic_operations["partial_adjust_and_support_projection"]==1


def test_source_pins_are_existing_owners_not_new_account_platform():
    pins=q.code_pins();assert len(pins)==4
    assert any("joint_allocation_methods.py" in p["path"] for p in pins)
    assert any("joint_portfolio_policy.py" in p["path"] for p in pins)
    assert any("retained" in p["path"] for p in pins)


@pytest.mark.parametrize("method",["MAD","ENTROPIC","DRO","TURNOVER_CVAR","ENTROPY_TURNOVER","MAX_DIV","MIN_CORR","ELLIPSOIDAL","COV_ROBUST","LOG_UTILITY"])
def test_new_fixed_objective_analytic_gradient_matches_math(method):
    i=inputs();fn=q._new_objective(method,i["mu"],i["uncertainty"],i["covariance"],i["current"],i["scenarios"],i["prior_scale"],.001)
    w=np.linspace(.03,.10,12);value,gradient=fn(w);numerical=[]
    for j in range(12):
        d=np.zeros(12);d[j]=1e-6
        numerical.append((fn(w+d)[0]-fn(w-d)[0])/2e-6)
    assert np.isfinite(value) and np.allclose(gradient,numerical,rtol=2e-3,atol=2e-6)


def test_reserved_full_account_is_deterministic_not_optimizer():
    i=inputs();i["current"][:10]=.1;i["locked"][:10]=True
    z=q.allocate_q("MV",**i,solve=lambda *a:pytest.fail("No objective needed"))
    assert z.whole_objective_calls==0 and np.allclose(z.allocation.q,i["current"])


def test_locked_fractional_kelly_cannot_erase_reserved_or_exceed_composition_cap():
    i=inputs();i["current"][0]=.1;i["locked"][0]=True
    with pytest.raises(q.QInputBlocked,match="LOCKED_GROWTH"):
        q.allocate_q("FRACTIONAL_KELLY",**i)

def test_indefinite_input_is_blocked_before_objective_reservation():
    i=inputs();i['covariance'][0,1]=i['covariance'][1,0]=1.;calls=[]
    with pytest.raises(q.QInputBlocked,match='INDEFINITE'):
        q.allocate_q('ELLIPSOIDAL',**i,solve=lambda *a:calls.append(a))
    assert calls==[]
