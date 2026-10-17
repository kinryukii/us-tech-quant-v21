"""Only synthetic input fixtures; no actual market/result readers."""
import hashlib
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.inference import consensus_joint_policy as policy
from scripts.research.a2.evaluation.consensus_cash_account import FeeConfig, run_cash_account
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays, OperationalEvidence


def inputs(names=("A", "B"), dates=None):
    dates = pd.bdate_range("2025-07-01", periods=3) if dates is None else pd.DatetimeIndex(dates)
    f = pd.DataFrame([dict(signal_date=d, ticker=t, mu=.025, sigma=.008, p_up=.75,
                          q10=-.005, q50=.025, q90=.045) for d in dates for t in names])
    f.attrs["unit"] = policy.UNIT
    index = pd.bdate_range(end=dates[0]-pd.Timedelta(days=1), periods=140)
    rng = np.random.default_rng(83)
    returns = pd.DataFrame(rng.normal(0,.01,(len(index),len(names))), index=index, columns=names)
    returns.attrs["source_id"] = "UNKNOWN"
    shape = (len(dates), len(names))
    market = MarketArrays(dates, names, np.full(shape,100.), np.full(shape,100.),
        adv=np.full(shape,1e7), signal_mask=np.arange(len(dates)) < len(dates)-1)
    return f, returns, market


def transition(mu=(.03,.02), current=(0.,0.), cash=3000., *, method="cost_aware", fee=None, **kwargs):
    n=len(mu)
    return policy.allocate_transition(method, np.asarray(mu), np.full(n,.01), np.eye(n)*.0005,
        np.asarray(current), np.zeros(n,bool), np.ones(n,bool), np.ones(n,bool), min(20,n), np.arange(n),
        nav=3000., settled_cash=cash, fee_config=fee or FeeConfig(), **kwargs)


def test_catalogue_is_finite_true_ids_no_cartesian_and_sources_unchanged():
    cat=policy.catalogue()
    assert len(cat["risk_methods"])==18 and len(cat["allocation_methods"])==26
    assert cat["unique_primary_paths"]==17
    assert len(cat["primary_paths"])+len(cat["allocation_paths"])==17
    assert "mean_es" not in cat["candidate_allocations"] and "kelly" not in cat["candidate_allocations"]
    before=Path(policy.allocation.__file__).read_bytes()
    target,_,audit=transition()
    assert np.count_nonzero(target)>0 and audit["lineage"]["cost_ast_anchor_count"]==1
    assert hashlib.sha256(before).hexdigest()==policy.OWNER_SHA
    assert Path(policy.allocation.__file__).read_bytes()==before


def test_budget_projection_never_forces_cash_into_fixed_full_mass():
    rules=policy._TransitionRules(np.zeros(2),np.zeros(2,bool),3000.,3000.,FeeConfig())
    result=rules.project(np.array([.03,.02]),np.full(2,.1),.95,2,np.arange(2))
    np.testing.assert_allclose(result,[.03,.02],atol=1e-8)
    zero=rules.project(np.array([-.03,-.02]),np.full(2,.1),.95,2,np.arange(2))
    np.testing.assert_allclose(zero,0.)
    target,_,_=transition(mu=(-.02,-.01))
    np.testing.assert_allclose(target,0.)


def test_exact_fixed_fee_and_settled_cash_are_in_common_utility_and_sizing():
    fee=FeeConfig(25,.5,5,True)
    target,_,audit=transition(cash=100.,fee=fee)
    assert audit["signal_buy_cash_required"]<=100.+1e-7
    assert audit["estimated_transition_fee"]>0 and target.sum()*3000.<100.
    held,mask,audit=transition(mu=(.00001,.00001),current=(.05,.05),cash=0.,fee=fee)
    np.testing.assert_allclose(held,[.05,.05])
    assert audit["no_trade"] and not mask.any()


def test_unknown_held_and_pool_exit_use_actual_context_without_new_buy_upgrade():
    forecasts,returns,market=inputs()
    forecasts=forecasts[forecasts.ticker.ne("A")].copy()
    forecasts.attrs["unit"]=policy.UNIT
    market.input_present[:,0]=False
    market.new_buy_eligible[:,0]=False
    market.initial_marks[0]=100.
    p=policy.ConsensusJointPolicy(forecasts,returns)
    replay=run_cash_account(market,["x"],p,initial_units=[1.,0.],max_positions=2)
    assert replay.final_units[0,0]==1. and replay.final_units[0,1]>0
    assert not replay.fills.ticker.eq("A").any()
    assert p.diagnostics[0]["risk"]["provenance"]=="UNKNOWN"


@pytest.mark.parametrize("method",policy.PRIMARY_RISKS)
def test_primary_risk_owner_uses_prior_daily_window_and_five_day_scaling(method):
    f,returns,market=inputs(names=tuple("ABCDEF"))
    p=policy.ConsensusJointPolicy(f,returns,config=policy.PolicyConfig(risk_method=method))
    matrix,meta=p._risk(market.dates[0],tuple(market.tickers))
    bundle=next(iter(p.risk_cache.values()))
    assert bundle.status=="FITTED" and len(bundle.fitted_dates)==120
    assert max(pd.Timestamp(x) for x in bundle.fitted_dates)<market.dates[0]
    assert bundle.specification["return_horizon_sessions"]==1 and meta["covariance_horizon_sessions"]==5
    base=policy.risk.risk_matrix(bundle,tuple(market.tickers))
    np.testing.assert_allclose(matrix,base*5.)


def test_future_append_and_test_period_do_not_update_fitted_risk_state():
    f,returns,market=inputs(dates=["2026-01-05","2026-01-06"])
    p=policy.ConsensusJointPolicy(f,returns)
    p.freeze_final_risk(tuple(market.tickers))
    matrix,_=p._risk(market.dates[0],tuple(market.tickers))
    count=len(p.risk_cache)
    q=policy.ConsensusJointPolicy(f,pd.concat([returns,pd.DataFrame([[999.,-999.]],index=pd.DatetimeIndex(["2026-01-07"]),columns=returns.columns)]))
    q.freeze_final_risk(tuple(market.tickers))
    other,_=q._risk(market.dates[1],tuple(market.tickers))
    np.testing.assert_allclose(matrix,other)
    p._risk(market.dates[1],tuple(market.tickers))
    assert len(p.risk_cache)==count==1
    assert max(pd.Timestamp(x) for x in next(iter(p.risk_cache.values())).fitted_dates)<pd.Timestamp("2026-01-01")


def test_missing_required_scenarios_block_without_fake_forecasts_or_training():
    for method in ("mean_cvar","mean_semivariance","log_growth"):
        with pytest.raises(policy.allocation.AllocationUnavailable,match="MATURE_CAUSAL_JOINT_SCENARIOS"):
            transition(method=method)
    f,returns,market=inputs()
    p=policy.ConsensusJointPolicy(f,returns,config=policy.PolicyConfig(allocation_method="mean_cvar"))
    replay=run_cash_account(market,["x"],p)
    assert replay.fills.empty
    assert all(x["status"]=="NOT_TESTABLE_OR_INFEASIBLE_PRESERVE_UNITS" for x in p.diagnostics)


def test_operational_exit_tiny_tail_fee_is_in_target_quote_not_spendable_sales():
    f,returns,market=inputs()
    market.initial_marks[0]=100.
    market.operational_exits[market.dates[0]]={"A":OperationalEvidence("fixture exit",market.signal_asof[0],"fixture")}
    p=policy.ConsensusJointPolicy(f,returns,fee_config=FeeConfig(10,.5,5,True))
    replay=run_cash_account(market,["x"],p,fee_config=p.fee_config,initial_units=[.04,0.],max_positions=1)
    assert replay.final_units[0,0]==0 and replay.final_units[0,1]>0
    assert replay.fills.loc[replay.fills.side.eq("SELL"),"transaction_cost"].iloc[0]==pytest.approx(.504)
    assert p.diagnostics[0]["estimated_transition_fee"]>=.504


def test_owner_mismatch_fails_closed(monkeypatch):
    monkeypatch.setattr(policy,"OWNER_SHA","0"*64)
    with pytest.raises(ValueError,match="OWNER_SOURCE_CHANGED"):
        transition()

@pytest.mark.parametrize("method", policy.CANDIDATE_ALLOCATIONS)
def test_actual_allocation_catalogue_uses_owner_or_explicit_block(method):
    scenarios=np.random.default_rng(7).normal(.02,.012,(80,2))
    target,mask,audit=transition(method=method,scenarios=scenarios)
    assert np.isfinite(target).all() and (target>=0).all() and target.sum()<=.95+1e-7
    assert audit["method"]==method and not audit["global_optimum_claim"]
    assert audit["signal_buy_cash_required"]<=3000.+1e-7


def test_factor_dimension_block_does_not_claim_fitted_risk_or_replace_with_lw():
    f,returns,market=inputs()
    p=policy.ConsensusJointPolicy(f,returns,config=policy.PolicyConfig(risk_method="PCA"))
    replay=run_cash_account(market,["x"],p)
    assert replay.fills.empty
    assert p.diagnostics[0]["status"]=="NOT_TESTABLE_RISK_PRESERVE_UNITS"
    assert "FIXED_FACTOR_COUNT" in p.diagnostics[0]["reason"]


def test_full_candidate_bank_is_not_prefiltered_and_limit_is_joint():
    f,returns,market=inputs(names=tuple(f"T{x:03}" for x in range(100)))
    p=policy.ConsensusJointPolicy(f,returns)
    replay=run_cash_account(market,["x"],p,max_positions=20)
    assert len(p.risk_cache)==1
    assert len(next(iter(p.risk_cache.values())).assets)==100
    assert (replay.daily.actual_name_count<=20).all()
    assert replay.final_units.shape==(1,100)
    assert np.count_nonzero(replay.final_units[0])<=20


def test_forecast_cost_config_must_match_actual_account():
    f,returns,market=inputs()
    p=policy.ConsensusJointPolicy(f,returns,fee_config=FeeConfig(25,.5,5,True))
    with pytest.raises(ValueError,match="FEE_CONFIG_MISMATCH"):
        run_cash_account(market,["x"],p,fee_config=FeeConfig(10,0,5,True))


def test_shared_risk_fit_cache_reuses_same_state_but_never_collides_different_history():
    f,returns,market=inputs()
    shared={}
    p=policy.ConsensusJointPolicy(f,returns,shared_risk_cache=shared)
    q=policy.ConsensusJointPolicy(f,returns,shared_risk_cache=shared,config=policy.PolicyConfig(allocation_method="mean_variance"))
    p._risk(market.dates[0],tuple(market.tickers))
    q._risk(market.dates[0],tuple(market.tickers))
    assert len(shared)==1
    changed=returns.copy();changed.iloc[-1,0]+=.01
    other=policy.ConsensusJointPolicy(f,changed,shared_risk_cache=shared)
    other._risk(market.dates[0],tuple(market.tickers))
    assert len(shared)==2


def test_future_unrequested_column_cannot_change_current_covariance():
    f,returns,market=inputs()
    base=policy.ConsensusJointPolicy(f,returns)
    matrix,_=base._risk(market.dates[0],('A','B'))
    extended=returns.copy();extended['FUTURE_POOL_ONLY']=np.random.default_rng(99).normal(0,.4,len(returns))
    other=policy.ConsensusJointPolicy(f,extended)
    changed,meta=other._risk(market.dates[0],('A','B'))
    np.testing.assert_allclose(matrix,changed,rtol=0,atol=1e-14)
    assert set(next(iter(other.risk_cache.values())).assets)=={'A','B'}
    assert meta['unknown_assets']==[]


def test_future_market_bank_does_not_change_current_fills_or_risk_fit():
    f,returns,market=inputs();base=policy.ConsensusJointPolicy(f,returns)
    a=run_cash_account(market,['x'],base,max_positions=2)
    _,_,full_market=inputs(names=('A','B','FUTURE_POOL_ONLY'))
    full_market.input_present[:,2]=False;full_market.new_buy_eligible[:,2]=False
    extended=returns.copy();extended['FUTURE_POOL_ONLY']=np.random.default_rng(99).normal(0,.4,len(returns))
    other=policy.ConsensusJointPolicy(f,extended)
    b=run_cash_account(full_market,['x'],other,max_positions=2)
    np.testing.assert_allclose(a.final_units,b.final_units[:,:2],rtol=0,atol=1e-10)
    assert b.final_units[0,2]==0 and not b.fills.ticker.eq('FUTURE_POOL_ONLY').any()
    assert set(next(iter(other.risk_cache.values())).assets)=={'A','B'}
    assert other.diagnostics[0]['risk']['unknown_assets']==['FUTURE_POOL_ONLY']


def test_month_freeze_keeps_first_asset_set_and_new_names_use_unknown_fallback():
    dates=pd.DatetimeIndex(['2025-07-01','2025-07-21','2025-08-01'])
    f,returns,_=inputs(dates=dates)
    rng=np.random.default_rng(51)
    extra=pd.DataFrame(rng.normal(0,.2,(len(pd.bdate_range('2025-07-01','2025-07-31')),2)),
        index=pd.bdate_range('2025-07-01','2025-07-31'),columns=['A','B'])
    history=pd.concat([returns,extra]);history['NEW_IN_MONTH']=rng.normal(0,.02,len(history))
    calls=[];p=policy.ConsensusJointPolicy(f,history,on_risk_fit_started=calls.append)
    first,_=p._risk(dates[0],('A','B'),fit_assets=('A','B'))
    later,meta=p._risk(dates[1],('A','B','NEW_IN_MONTH'),fit_assets=('A','B','NEW_IN_MONTH'))
    np.testing.assert_allclose(first,later[:2,:2],rtol=0,atol=1e-14)
    assert meta['unknown_assets']==['NEW_IN_MONTH'] and len(calls)==1
    assert np.all(later[2,:2]==0) and later[2,2]>0
    p._risk(dates[2],('A','B','NEW_IN_MONTH'),fit_assets=('A','B','NEW_IN_MONTH'))
    assert len(calls)==2 and len(p.risk_cache)==2 and calls[0]['assets']==['A','B']


def test_test_period_requires_pre_frozen_final_state_and_never_fits_inside_test():
    f,returns,market=inputs(dates=['2026-01-05','2026-01-06'])
    calls=[];p=policy.ConsensusJointPolicy(f,returns,on_risk_fit_started=calls.append)
    with pytest.raises(policy.risk.RiskEstimatorBlocked,match='MUST_ALREADY_BE_FROZEN'):
        p._risk(market.dates[0],('A','B'))
    assert calls==[] and p.risk_cache=={}
    p.freeze_final_risk(('A','B'))
    initial,_=p._risk(market.dates[0],('A','B'))
    later,_=p._risk(pd.Timestamp('2026-12-01'),('A','B'))
    np.testing.assert_allclose(initial,later,rtol=0,atol=1e-14)
    assert len(calls)==1 and pd.Timestamp(calls[0]['cutoff'])==pd.Timestamp('2026-01-01')
    assert max(pd.Timestamp(x) for x in next(iter(p.risk_cache.values())).fitted_dates)<pd.Timestamp('2026-01-01')


def test_shared_month_state_counts_actual_fit_start_once_and_budget_denial_precedes_fit(monkeypatch):
    f,returns,market=inputs();shared={};calls=[]
    p=policy.ConsensusJointPolicy(f,returns,shared_risk_cache=shared,on_risk_fit_started=calls.append)
    q=policy.ConsensusJointPolicy(f,returns,shared_risk_cache=shared,on_risk_fit_started=calls.append,
        config=policy.PolicyConfig(allocation_method='mean_variance'))
    p._risk(market.dates[0],('A','B'));q._risk(market.dates[0],('A','B'));p._risk(market.dates[1],('A','B'))
    assert len(calls)==1 and len(shared)==1
    def denied(event):raise RuntimeError('GLOBAL_FIT_BUDGET_EXHAUSTED')
    blocked=policy.ConsensusJointPolicy(f,returns,on_risk_fit_started=denied)
    monkeypatch.setattr(policy.risk,'fit_risk_estimator',lambda *a,**k:pytest.fail('estimation after budget denial'))
    with pytest.raises(RuntimeError,match='GLOBAL_FIT_BUDGET'):blocked._risk(market.dates[0],('A','B'))
    assert blocked.risk_cache=={}


def test_month_state_never_flows_backward_before_its_fit_cutoff():
    dates=pd.DatetimeIndex(['2025-07-01','2025-07-21'])
    f,returns,_=inputs(dates=dates)
    extra=pd.DataFrame(np.random.default_rng(38).normal(0,.02,(14,2)),index=pd.bdate_range('2025-07-01',periods=14),columns=['A','B'])
    p=policy.ConsensusJointPolicy(f,pd.concat([returns,extra]))
    p._risk(dates[1],('A','B'))
    with pytest.raises(policy.risk.RiskEstimatorBlocked,match='FUTURE|BEFORE|BACKWARD|CUTOFF'):
        p._risk(dates[0],('A','B'))


def _cap_fixture_market():
    return MarketArrays(pd.DatetimeIndex(["2025-06-02", "2025-06-03"]), ["A"],
        np.full((2,1),100.), np.full((2,1),100.), adv=np.full((2,1),1e7),
        signal_mask=np.array([True,False]), initial_marks=np.array([100.]),
        initial_mark_dates=np.array(["2025-05-30"],dtype="datetime64[ns]"))


def test_drifted_explicit_cap_native_engine():
    from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2 import fast_account
    target,mask,audit=transition(mu=(.04,),current=(.18,),cash=2460.)
    assert target[0]==pytest.approx(.10) and mask[0]
    # The unchanged controls alone retain 14%; only the existing target cap
    # repairs that incompatible explicit intention before quote and utility.
    w,m=np.array([.10]),np.array([True])
    for control in policy.PolicyConfig().controls:
        w,m=policy.apply_controls(w,m,np.array([.18]),3000.,control=control)
    assert w[0]==pytest.approx(.14) and m[0]
    assert audit["estimated_transition_fee"]==pytest.approx(.24)
    expected=.04*.10-.5*policy.allocation.SPEC["risk_penalty"]*.0005*.10**2-.24/3000.
    assert audit["candidate_utility"]==pytest.approx(expected)
    seen=[]
    def decision(di,ctx):
        t,m,a=policy.allocate_transition("cost_aware",np.array([.04]),np.array([.01]),
            np.eye(1)*.0005,ctx.current_weights[0],ctx.reserved_mask[0],
            ctx.decision_mask[0],ctx.buy_allowed[0],int(ctx.available_slots[0]),np.arange(1),
            nav=float(ctx.nav[0]),settled_cash=float(ctx.cash[0]),fee_config=FeeConfig(),
            investment_budget=float(ctx.max_invested))
        seen.append((t.copy(),m.copy(),a))
        return policy.TargetDecision(t[None,:],m[None,:])
    replay=fast_account.run_many(_cap_fixture_market(),["synthetic"],decision,
        initial_cash=2460.,initial_units=[5.4],cost_bps=10.,max_weight=.10)
    assert len(replay.fills)==1 and replay.fills.iloc[0].side=="SELL"
    assert replay.fills.iloc[0].notional==pytest.approx(240.)
    assert replay.fills.iloc[0].transaction_cost==pytest.approx(seen[0][2]["estimated_transition_fee"])
    assert replay.daily.iloc[-1].nav==pytest.approx(2999.76)
    assert replay.audit["cash_identity_error_max"]<1e-8
    assert replay.audit["nav_identity_error_max"]<1e-8


def test_no_decision_drift_not_forced_into_cap_order():
    from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2 import fast_account
    target,mask,audit=transition(mu=(.04,),current=(.104,),cash=2688.)
    assert target[0]==pytest.approx(.104) and not mask.any()
    assert audit["estimated_transition_fee"]==0.
    replay=fast_account.run_many(_cap_fixture_market(),["synthetic"],
        lambda di,ctx:policy.TargetDecision(target[None,:],mask[None,:]),
        initial_cash=2688.,initial_units=[3.12],cost_bps=10.,max_weight=.10)
    assert replay.fills.empty and replay.final_units[0,0]==pytest.approx(3.12)
    assert replay.daily.iloc[-1].nav==pytest.approx(3000.)


def test_locked_missing_drift_preserves_existing_units():
    current=np.array([.18,0.])
    target,mask,audit=policy.allocate_transition("cost_aware",np.array([.04,.03]),np.full(2,.01),
        np.eye(2)*.0005,current,np.array([True,False]),np.array([False,True]),
        np.array([False,True]),1,np.arange(2),nav=3000.,settled_cash=2460.,fee_config=FeeConfig())
    assert target[0]==pytest.approx(.18) and not mask[0]
    assert target[1]<=.10 and mask[1]
    assert policy.quote_transition_cost(current,target,3000.,FeeConfig())["fees"][0]==0.
    assert audit["signal_buy_cash_required"]<=2460.


def test_full_exit_fee_quote_and_settled_replay_remain_equal():
    fee=FeeConfig(25,.5,5,True)
    target,mask,audit=transition(mu=(-.04,),current=(.18,),cash=2460.,fee=fee)
    assert target[0]==0. and mask[0] and not audit["no_trade"]
    expected=policy.fee_for_notional(np.array([540.]),fee)[0]
    assert audit["estimated_transition_fee"]==pytest.approx(expected)
    assert audit["signal_buy_cash_required"]==0.
    replay=run_cash_account(_cap_fixture_market(),["synthetic"],
        lambda di,ctx:policy.TargetDecision(target[None,:],mask[None,:]),
        fee_config=fee,initial_cash=2460.,initial_units=[5.4],
        settlement_calendar=pd.DatetimeIndex(["2025-06-02","2025-06-03","2025-06-04"]))
    assert len(replay.fills)==1 and replay.fills.iloc[0].side=="SELL"
    assert replay.fills.iloc[0].transaction_cost==pytest.approx(expected)
    assert replay.final_units[0,0]==0.
    assert replay.daily.iloc[-1].settled_cash==pytest.approx(2460.)
    assert replay.daily.iloc[-1].unsettled_cash==pytest.approx(540.-expected)
    assert replay.daily.iloc[-1].nav==pytest.approx(3000.-expected)
    assert replay.audit["cash_identity_error_max"]<1e-8
    assert replay.audit["nav_identity_error_max"]<1e-8


def test_stock_distribution_forced_exit_excludes_child_from_fit_and_quotes_full_sale(monkeypatch):
    from types import SimpleNamespace
    f,returns,market=inputs(names=('A','CHILD'))
    f=f.loc[f.ticker.eq('A')].copy();f.attrs['unit']=policy.UNIT
    p=policy.ConsensusJointPolicy(f,returns);seen=[]
    def covariance(date,tickers,*,fit_assets):
        seen.append(fit_assets);return np.eye(2)*.0005,dict(synthetic=True)
    monkeypatch.setattr(p,'_risk',covariance)
    ctx=SimpleNamespace(signal_date=market.dates[0],tickers=market.tickers,path_ids=('x',),
        fee_config=p.fee_config,current_units=np.array([[1.,3.]]),current_weights=np.array([[.05,.03]]),
        decision_mask=np.array([[True,False]]),stock_distribution_forced_exit_mask=np.array([[False,True]]),
        operational_mask=np.array([[False,True]]),sell_restricted=np.zeros((1,2),bool),reserved_mask=np.array([[False,True]]),
        buy_allowed=np.array([[True,False]]),nav=np.array([3000.]),settled_cash=np.array([2400.]),max_positions=20,max_invested=.95)
    result=p(0,ctx)
    assert seen==[('A',)] and p.last_forced_exit_assets==('CHILD',)
    assert result.weights[0,1]==0. and not result.explicit_mask[0,1]
    assert p.diagnostics[-1]['estimated_transition_fee']>=90.*.001
    assert p.diagnostics[-1]['signal_buy_cash_required']<=2400.
    ctx.signal_date=pd.Timestamp('2025-12-31')
    monkeypatch.setattr(p,'_risk',lambda *a,**kw:pytest.fail('mechanical full exit needs no alpha/risk model'))
    empty=p(1,ctx)
    assert empty.weights[0,1]==0. and not empty.explicit_mask.any()
    ctx.stock_distribution_forced_exit_mask=np.array([[True]])
    with pytest.raises(ValueError,match='FORCED_EXIT_MASK'):p(2,ctx)


@pytest.mark.parametrize('method,mu,cash,slots',[
    ('equal_weight',(0.,0.),3000.,2),
    ('equal_weight',(-.02,-.01),3000.,2),
    ('equal_weight',(.03,.02),0.,2),
    ('equal_weight',(.03,.02),3000.,0),
    ('inverse_volatility',(.03,.02),0.,2),
    ('inverse_volatility',(.03,.02),3000.,0),
])
def test_empty_projected_support_retains_legal_cash_without_normalizing(method,mu,cash,slots):
    with np.errstate(all='raise'):
        target,mask,audit=policy.allocate_transition(method,np.asarray(mu),np.full(2,.01),np.eye(2)*.0005,
            np.zeros(2),np.zeros(2,bool),np.ones(2,bool),np.ones(2,bool),slots,np.arange(2),
            nav=3000.,settled_cash=cash,fee_config=FeeConfig())
    np.testing.assert_array_equal(target,np.zeros(2))
    assert not mask.any() and audit['no_trade']
    assert audit['signal_buy_cash_required']==0. and audit['estimated_transition_fee']==0.
    assert audit['lineage']['empty_support_normalization_guard_count']==2


def test_empty_support_uses_original_full_exit_utility_and_locked_reservation():
    current=np.array([.04,.03,0.]);locked=np.array([True,False,False])
    target,mask,audit=policy.allocate_transition('equal_weight',np.zeros(3),np.full(3,.01),np.eye(3)*.04,
        current,locked,np.array([False,True,True]),np.ones(3,bool),3,np.arange(3),
        nav=3000.,settled_cash=0.,fee_config=FeeConfig())
    np.testing.assert_array_equal(target,np.array([.04,0.,0.]))
    assert not audit['no_trade'] and mask[1] and audit['signal_buy_cash_required']==0.


def test_allocator_template_reuses_code_with_fresh_rules_and_metadata():
    a=policy._TransitionRules(np.zeros(2),np.zeros(2,bool),3000.,3000.,FeeConfig())
    b=policy._TransitionRules(np.zeros(2),np.zeros(2,bool),3000.,10.,FeeConfig(25.,.5,5.,True))
    left,lineage=policy._project_allocator(a);right,other=policy._project_allocator(b)
    assert left.__code__ is right.__code__ and left.__globals__ is not right.__globals__
    assert left.__globals__['_transition'] is a and right.__globals__['_transition'] is b
    assert left.__globals__['allocate_q'] is left and right.__globals__['allocate_q'] is right
    lineage['projected_function_ast_sha256']='0'*64
    assert other['projected_function_ast_sha256']!='0'*64
