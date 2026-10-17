"""Synthetic-only matrix/estimator/typed-budget acceptance; no real readers."""
import copy
from dataclasses import asdict, replace
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.evaluation import consensus_method_extension as extension
from scripts.research.a2.inference import consensus_joint_policy as joint
from scripts.research.a2.evaluation.consensus_cash_account import FeeConfig, run_cash_account
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays


def scope():
    return dict(schema=extension.SCHEMA, research_id="SYNTHETIC_FULL_MATRIX",
        forecast_packs=["core5__equal", "core5__nnls_zero_abstain"],
        risk_combinations={"LW":dict(members=["LW"], weights=[1.]),
                           "mix":dict(members=["DIAG","CONSTANT_CORR"],weights=[.5,.5])},
        decision_methods=list(joint.ALLOCATION_METHODS), selection_boundary_exclusive="2026-01-01",
        initial_cash=3000,prior_fit_units=2063,max_fit_units=10000,lookback_sessions=120,
        controls=list(extension.CONTROLS),fee_config=asdict(FeeConfig()))


def inputs():
    names=tuple("ABCDEF")
    dates=pd.bdate_range("2025-07-01",periods=3)
    forecast=pd.DataFrame([dict(signal_date=d,ticker=a,mu=.025,sigma=.008,p_up=.75,
                               q10=-.005,q50=.025,q90=.045) for d in dates for a in names])
    forecast.attrs["unit"]=joint.UNIT
    rng=np.random.default_rng(83)
    past=pd.DataFrame(rng.normal(0,.01,(140,len(names))),
        index=pd.bdate_range(end=dates[0]-pd.Timedelta(days=1),periods=140),columns=names)
    past.attrs["source_id"]="SYNTHETIC_DAILY"
    market=MarketArrays(dates,names,np.full((3,6),100.),np.full((3,6),100.),
        adv=np.full((3,6),1e7),signal_mask=np.array([True,True,False]))
    scenario={d:dict(assets=names,values=rng.normal(.01,.015,(50,6)),source_refs={"labels":{"path":"synthetic://h5","sha256":"a"*64}},
        available_at=d-pd.Timedelta(days=1),label_mature_max=d-pd.Timedelta(days=2),unit=joint.UNIT)
        for d in dates}
    reference={d:dict(assets=names,values=np.full(6,1/6),source_refs={"reference":{"path":"synthetic://reference","sha256":"b"*64}},
        available_at=d-pd.Timedelta(days=1)) for d in dates}
    return forecast,past,market,scenario,reference


def direct_fit(calls):
    def fit(method,past,*,params,dependencies,event):
        calls.append((method,past.copy(),copy.deepcopy(event)))
        return joint.risk.fit_risk_estimator(method,past,
            market_returns=dependencies.get("market_returns"),
            exposure_frame=dependencies.get("exposure_frame"),params=params)
    return fit


def bound(decision="cost_aware",risk="LW",pack="core5__equal",calls=None,**kwargs):
    return extension.bind_joint(joint,scope=scope(),
        coordinate=extension.Coordinate(pack,risk,decision),
        bank_fit=direct_fit([] if calls is None else calls),**kwargs)


def test_scope_is_explicit_matrix_not_fixed17_or_winner_and_budget_never_resets():
    s=scope()
    rows=extension.matrix_plan(s)
    assert len(rows)==2*2*26
    assert all(not r["alias_is_execution"] for r in rows)
    assert {r["coordinate"]["forecast_pack"] for r in rows}==set(s["forecast_packs"])
    for key,value in [("prior_fit_units",0),("initial_cash",10000),("max_fit_units",12000),
                      ("selection_boundary_exclusive","2027-01-01")]:
        invalid=copy.deepcopy(s);invalid[key]=value
        with pytest.raises(ValueError):extension.validate_scope(invalid)
    aliases={r["coordinate"]["decision_method"]:r for r in rows[:26]}
    assert aliases["mean_es"]["evaluation_coordinate"]==aliases["mean_cvar"]["evaluation_coordinate"]
    assert aliases["kelly"]["evaluation_coordinate"]==aliases["log_growth"]["evaluation_coordinate"]
    assert aliases["turnover_limit"]["evaluation_coordinate"]!=aliases["mean_variance"]["evaluation_coordinate"]
    assert joint.PRIMARY_RISKS==("DIAG","LW","EWMA","PCA","OAS","SCOV","FA")
    assert len(joint.CANDIDATE_ALLOCATIONS)==11


@pytest.mark.parametrize("method",joint.ALLOCATION_METHODS)
def test_each_registered_decision_reaches_owner_and_original_cash_account(method):
    forecast,past,market,scenarios,references=inputs()
    binding=bound(method,scenarios=scenarios,references=references)
    policy=binding.ConsensusJointPolicy(forecast,past)
    replay=run_cash_account(market,["synthetic-cell"],policy,max_positions=20)
    assert policy.diagnostics
    assert all(d.get("status")!="NOT_TESTABLE_OR_INFEASIBLE_PRESERVE_UNITS" for d in policy.diagnostics),policy.diagnostics
    assert np.isfinite(replay.daily.nav).all()
    assert not (replay.daily.settled_cash < -1e-7).any()
    assert replay.daily.nav.iloc[0]==pytest.approx(3000.)
    assert replay.final_units.shape==(1,6)
    assert all(d["lineage"]["cost_ast_anchor_count"]==1 for d in policy.diagnostics)
    assert all(d["configuration"]["allocation_method"]==method for d in policy.diagnostics)


def test_cache_reuses_true_input_across_packs_but_separates_holdings_domains_and_preserves_month_cadence():
    forecast,past,market,_,_=inputs()
    calls=[];cache={}
    first=bound(calls=calls).ConsensusJointPolicy(forecast,past,shared_risk_cache=cache)
    first._risk(market.dates[0],market.tickers,fit_assets=market.tickers)
    second=bound(pack="core5__nnls_zero_abstain",calls=calls).ConsensusJointPolicy(forecast,past,shared_risk_cache=cache)
    second._risk(market.dates[0],market.tickers,fit_assets=market.tickers)
    assert len(calls)==1
    third=bound(calls=calls).ConsensusJointPolicy(forecast,past,shared_risk_cache=cache)
    third._risk(market.dates[0],market.tickers,fit_assets=market.tickers[:-1])
    assert len(calls)==2
    first._risk(market.dates[1],market.tickers,fit_assets=market.tickers[:-1])
    assert len(calls)==2
    assert tuple(calls[0][2]["assets"])==tuple(market.tickers)


def test_dependency_contents_and_exact_source_identity_are_part_of_cache_key():
    forecast,past,market,_,_=inputs()
    calls=[];cache={};s=scope();s["risk_combinations"]={"index":dict(members=["SINGLE_INDEX"],weights=[1.])}
    def provider(change):
        def load(method,cutoff,assets):
            series=past.mean(axis=1).copy()
            series.iloc[-1]+=change
            return dict(market_returns=series,source_refs={"QQQ":{"path":"synthetic://qqq","sha256":"c"*64}},
                        available_at=cutoff-pd.Timedelta(days=1))
        return load
    for change in [0.,0.,.001]:
        binding=extension.bind_joint(joint,scope=s,coordinate=extension.Coordinate("core5__equal","index","cost_aware"),
                                    bank_fit=direct_fit(calls),bank_dependencies=provider(change))
        binding.ConsensusJointPolicy(forecast,past,shared_risk_cache=cache)._risk(
            market.dates[0],market.tickers,fit_assets=market.tickers)
    assert len(calls)==2


def test_fixed_risk_combination_is_covariance_mix_not_early_single_winner():
    forecast,past,market,_,_=inputs()
    calls=[]
    binding=bound(risk="mix",calls=calls)
    policy=binding.ConsensusJointPolicy(forecast,past)
    result,meta=policy._risk(market.dates[0],market.tickers)
    matrices=[]
    for method,frame,event in calls:
        bundle=joint.risk.fit_risk_estimator(method,frame,params=dict(fit_cutoff=market.dates[0]))
        matrices.append(joint.risk.risk_matrix(bundle,market.tickers)*5)
    np.testing.assert_allclose(result,.5*matrices[0]+.5*matrices[1],rtol=0,atol=1e-14)
    assert len(meta["members"])==2 and policy.matrix_coordinate["risk_combination"]=="mix"


def test_worker_budget_ack_failure_stops_before_owner_fit_and_future_rows_stop_before_ack(monkeypatch):
    forecast,past,market,_,_=inputs()
    class Pipe:
        def __init__(self,reject=False):self.messages=[];self.reject=reject
        def send(self,message):self.messages.append(message)
        def recv(self):return not self.reject
        def close(self):pass
    monkeypatch.setattr(extension.bank,"fit_risk_estimator",lambda *a,**k:pytest.fail("fit before ACK"))
    pipe=Pipe(reject=True)
    extension.risk_fit_worker(pipe,"risk","GARCH",past,None,None,None,{},[],dict(fit_cutoff=market.dates[0]))
    assert [m[0] for m in pipe.messages]==["FIT_START","ERROR"]
    assert "GLOBAL_FIT_BUDGET_REJECTED" in pipe.messages[-1][2]
    future=past.copy();future.index=pd.bdate_range("2026-01-01",periods=len(past))
    pipe=Pipe()
    extension.risk_fit_worker(pipe,"risk","GARCH",future,None,None,None,{},[],dict(fit_cutoff="2026-01-01"))
    assert [m[0] for m in pipe.messages]==["ERROR"]
    assert extension.risk_fit_unit_upper("GARCH",192)==3
    assert extension.risk_fit_unit_upper("GJR_GARCH",1)==3
    assert extension.risk_fit_unit_upper("INDUSTRY",192)==4


def test_missing_scenarios_still_has_actual_owner_qualification_and_no_fake_account_success():
    forecast,past,market,_,_=inputs()
    policy=bound("mean_es").ConsensusJointPolicy(forecast,past)
    replay=run_cash_account(market,["cell"],policy,max_positions=20)
    assert all(d["status"]=="NOT_TESTABLE_OR_INFEASIBLE_PRESERVE_UNITS" for d in policy.diagnostics)
    assert "MATURE_JOINT_SCENARIOS" in policy.diagnostics[0]["reason"]
    assert replay.fills.empty


def test_future_qualified_scenario_is_rejected_before_solver():
    forecast,past,market,scenarios,_=inputs()
    scenarios[market.dates[0]]["label_mature_max"]=pd.Timestamp("2026-01-01")
    policy=bound("mean_es",scenarios=scenarios).ConsensusJointPolicy(forecast,past)
    with pytest.raises(ValueError,match="PRE2026"):
        run_cash_account(market,["cell"],policy,max_positions=20)


def source_r2_fixture():
    p=Path(__file__).parents[1]/"risk/test_shared_risk_engine_r2.py"
    spec=importlib.util.spec_from_file_location("_matrix_typed_r2_synthetic_fixture",p)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.synthetic_input(assets=6,horizons=(5,))


def test_r2_typed_hook_uses_actual_durable_reservations_and_exact_cache_not_mode_flag():
    inputs,as_of=source_r2_fixture()
    events=[]
    hook=extension.R2FitHook(lambda *args:(inputs,as_of),durable_reserve=events.append)
    bundle,key=hook("RD",cutoff=as_of,assets=inputs.assets)
    assert bundle.status=="FITTED",bundle.failure_reason
    first=hook.last_reservation_delta
    assert first>0 and hook.budget.learned_total==first
    assert len(events)>=first and bundle.fitted_state["typed_state"].notes["real_fit"]==0
    repeated,repeated_key=hook("RD",cutoff=as_of,assets=inputs.assets)
    assert repeated_key==key and hook.last_reservation_delta==0
    assert repeated.budget["total_state_estimations"]==bundle.budget["total_state_estimations"]
    with pytest.raises(ValueError,match="DOMAIN"):
        hook("RD",cutoff=as_of,assets=inputs.assets[:-1])


def test_r2_failed_durable_reservation_is_spent_and_never_retried():
    inputs,as_of=source_r2_fixture()
    calls=[]
    def reject(event):calls.append(event);raise RuntimeError("synthetic durable failure")
    hook=extension.R2FitHook(lambda *args:(inputs,as_of),durable_reserve=reject)
    with pytest.raises(RuntimeError,match="durable"):
        hook("RD",cutoff=as_of,assets=inputs.assets)
    used=hook.budget.learned_total
    assert used>0
    blocked,_=hook("RD",cutoff=as_of,assets=inputs.assets)
    assert blocked.status=="BLOCKED_INPUT"
    assert hook.budget.learned_total==used and len(calls)==1


def synthetic_evaluate(run,method,risk_method,allocation_method,*,diagnostic=None):
    if allocation_method in SCENARIO_METHODS:
        return {"status":"blanket NT"}
    receipt=dict(status="IN_PROGRESS")
    policy=make_policy(method)
    if any(d.get("status")=="NOT_TESTABLE_RISK_PRESERVE_UNITS" for d in policy.diagnostics):
        return dict(receipt,status="NOT_TESTABLE")
    return dict(receipt,status="COMPLETE",flow_id=flow_id(method,risk_method,allocation_method,run=run))


def test_evaluator_hook_preserves_all_coordinates_and_excludes_allocation_nt_from_complete():
    coordinate=extension.Coordinate("core5__equal","LW","mean_es")
    binding=bound("mean_es")
    fn=synthetic_evaluate
    runner=SimpleNamespace(evaluate_flow=fn,make_policy=lambda *a:None)
    factory=lambda *a:SimpleNamespace(diagnostics=[{"status":"NOT_TESTABLE_OR_INFEASIBLE_PRESERVE_UNITS"}])
    result=extension.evaluate_flow(runner,coordinate,None,coordinate.forecast_pack,"LW","mean_es",
                                   binding=binding,make_policy=factory)
    assert result["status"]=="NOT_TESTABLE"
    assert result["matrix_coordinate"]==asdict(coordinate)
    factory=lambda *a:SimpleNamespace(diagnostics=[])
    result=extension.evaluate_flow(runner,coordinate,None,coordinate.forecast_pack,"LW","mean_es",
                                   binding=binding,make_policy=factory)
    assert result["status"]=="COMPLETE" and result["flow_id"]=="matrix__"+coordinate.identity


def test_cache_keeps_full_fit_domain_and_source_refs_even_with_same_known_columns():
    forecast,past,market,_,_=inputs()
    calls=[];cache={}
    for sha,extra in [("a"*64,"G"),("a"*64,"G"),("b"*64,"G"),("b"*64,"H")]:
        version=past.copy()
        version.attrs["source_ref"]={"path":"synthetic://returns","sha256":sha}
        bound(calls=calls).ConsensusJointPolicy(forecast,version,shared_risk_cache=cache)._risk(
            market.dates[0],tuple(market.tickers)+(extra,),fit_assets=tuple(market.tickers)+(extra,))
    assert len(calls)==3


@pytest.mark.parametrize("method", extension.EXTERNAL_DECISION_METHODS)
def test_external_rl_factory_keeps_coordinates_and_calls_original_account_without_rl_solver(method):
    forecast,past,market,_,_=inputs()
    s=scope();s["decision_methods"] += list(extension.EXTERNAL_DECISION_METHODS)
    coordinate=extension.Coordinate("core5__equal","LW",method)
    with pytest.raises(ValueError,match="EXPLICIT_EXTERNAL_RL_POLICY_FACTORY"):
        extension.bind_joint(joint,scope=s,coordinate=coordinate,bank_fit=direct_fit([]))
    called=[]
    class External:
        def __init__(self,base):self.base_policy=base
        def __call__(self,di,ctx):
            called.append((method,di,float(ctx.nav[0])))
            return self.base_policy(di,ctx)
    def factory(name,forecasts,past_daily_returns,*,config,fee_config,**owner_kwargs):
        assert name==config.allocation_method==method
        assert config.risk_method=="LW" and fee_config==FeeConfig()
        return External(bound().ConsensusJointPolicy(forecasts,past_daily_returns,
            fee_config=fee_config,**owner_kwargs))
    binding=extension.bind_joint(joint,scope=s,coordinate=coordinate,bank_fit=direct_fit([]),
                                 external_policy_factory=factory)
    policy=binding.ConsensusJointPolicy(forecast,past)
    replay=run_cash_account(market,["synthetic-rl"],policy,max_positions=20)
    assert called and policy.diagnostics
    assert policy.config.allocation_method==method and policy.matrix_coordinate==asdict(coordinate)
    assert policy.diagnostics is policy._external_owner.diagnostics
    assert policy.risk_cache is policy._external_owner.risk_cache
    assert replay.daily.nav.iloc[0]==pytest.approx(3000.)
    assert np.isfinite(replay.daily.nav).all() and not (replay.daily.settled_cash < -1e-7).any()
    with pytest.raises(ValueError,match="MUST_NOT_ENTER_SOLVER"):
        binding.allocate_transition(method)
    rows=extension.matrix_plan(s)
    assert {r["coordinate"]["decision_method"] for r in rows}==set(s["decision_methods"])


@pytest.mark.parametrize("decision,status",[("cost_aware","COMPLETE"),("mean_es","NOT_TESTABLE")])
def test_original_evaluator_projection_runs_shareholder_owner_and_keeps_matrix_receipt(tmp_path,monkeypatch,decision,status):
    import json
    import joblib
    from scripts.research.a2.evaluation import consensus_evaluation_run as runner
    fixture_path=Path(__file__).with_name("test_consensus_shareholder_account.py")
    spec=importlib.util.spec_from_file_location("_matrix_shareholder_synthetic_fixture",fixture_path)
    fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    forecast,past,market,_,_=inputs()
    dates=pd.DatetimeIndex(["2023-01-03","2023-01-04","2024-01-02","2024-01-03","2025-01-02","2025-01-03"])
    market=MarketArrays(dates,market.tickers,np.full((6,6),100.),np.full((6,6),100.),
        adv=np.full((6,6),1e7),signal_mask=np.array([True,True,True,True,True,False]))
    forecast=pd.DataFrame([dict(signal_date=d,ticker=a,mu=.025,sigma=.008,p_up=.75,q10=-.005,q50=.025,q90=.045)
        for d in dates for a in market.tickers])
    forecast.attrs["unit"]=joint.UNIT
    past.index=pd.bdate_range(end="2022-12-30",periods=len(past))
    loaded=dict(market=market,events=dict(entitlement_events=(),entitlement_security_tickers={},
        entitlement_source_binding=fixture.source_binding((),{})),task_authority=fixture.binding(tmp_path,()),
        settlement_calendar=dates,usable_a=np.zeros_like(market.quality),
        source_scope_ref={"path":"synthetic://scope","sha256":"c"*64})
    monkeypatch.setattr(runner,"write_json_atomic",lambda p,v:p.write_text(json.dumps(v,default=str)))
    def save(path,value,kind):
        value.to_parquet(path,index=False) if kind=="frame" else joblib.dump(value,path)
        return runner.ref(path)
    monkeypatch.setattr(runner,"_save_artifact",save)
    binding=bound(decision)
    def factory(forecasts,returns,config,fee_config,run,receipt,cache,identity):
        return binding.ConsensusJointPolicy(forecasts,returns,config=config,fee_config=fee_config,shared_risk_cache=cache)
    coordinate=extension.Coordinate("core5__equal","LW",decision)
    receipt=extension.evaluate_flow(runner,coordinate,tmp_path,coordinate.forecast_pack,"LW",decision,
        forecast,past,loaded,{"path":"synthetic://freeze","sha256":"d"*64},[],{},binding=binding,make_policy=factory)
    assert receipt["status"]==status,receipt.get("failure")
    assert receipt["matrix_coordinate"]==asdict(coordinate)
    assert receipt["flow_id"]=="matrix__"+coordinate.identity
    assert "daily" in receipt["artifacts"] and "state" in receipt["artifacts"]
    if status=="NOT_TESTABLE":
        diagnostics=pd.read_parquet(receipt["artifacts"]["diagnostics"]["path"])
        assert any("MATURE_JOINT_SCENARIOS" in row for row in diagnostics.json)
    else:
        assert len(receipt["statistics"]["annual_statistics"])==3


def test_same_shape_scenario_with_wrong_asset_order_stops_before_risk_fit():
    forecast,past,market,scenarios,_=inputs()
    scenarios[market.dates[0]]["assets"]=tuple(reversed(market.tickers))
    calls=[]
    policy=bound("mean_es",scenarios=scenarios,calls=calls).ConsensusJointPolicy(forecast,past)
    with pytest.raises(ValueError,match="ORDERED_ACCOUNT_INPUT_ASSET_DOMAIN"):
        run_cash_account(market,["cell"],policy,max_positions=20)
    assert calls==[]


def test_r2_out_of_domain_padding_cannot_become_active_or_held_and_does_not_refit():
    typed,as_of=source_r2_fixture()
    events=[]
    hook=extension.R2FitHook(lambda *args:(typed,as_of),durable_reserve=events.append)
    forecast,past,_,_,_=inputs()
    s=scope();s["risk_combinations"]={"typed":dict(members=["RD"],weights=[1.])}
    binding=extension.bind_joint(joint,scope=s,coordinate=extension.Coordinate("core5__equal","typed","cost_aware"),
        bank_fit=direct_fit([]),r2_fit=hook)
    policy=binding.ConsensusJointPolicy(forecast,past)
    tickers=typed.assets+("OUTSIDE",)
    policy._risk(as_of,tickers,fit_assets=typed.assets)
    spent=hook.budget.learned_total
    with pytest.raises(ValueError,match="ACTIVE_OR_HELD_ASSET_OUTSIDE_FROZEN"):
        policy._risk(as_of+pd.Timedelta(days=1),tickers,fit_assets=tickers)
    assert hook.budget.learned_total==spent


def test_blocked_typed_bundle_keeps_actual_qualification_reason_instead_of_domain_padding_error():
    forecast,past,market,_,_=inputs()
    bundle=extension.bank.RiskBundle("RD","BLOCKED_INPUT",tuple(market.tickers),(),
        specification={"fit_cutoff":str(market.dates[0])},failure_reason="TYPED_SOURCE_QUALIFICATION_MISSING")
    s=scope();s["risk_combinations"]={"typed":dict(members=["RD"],weights=[1.])}
    binding=extension.bind_joint(joint,scope=s,coordinate=extension.Coordinate("core5__equal","typed","cost_aware"),
        bank_fit=direct_fit([]),r2_fit=lambda *a,**kw:(bundle,("TYPED_BLOCKED",)))
    with pytest.raises(extension.bank.RiskEstimatorBlocked,match="TYPED_SOURCE_QUALIFICATION_MISSING"):
        binding.ConsensusJointPolicy(forecast,past)._risk(market.dates[0],tuple(market.tickers))


@pytest.mark.parametrize("missing",["source","guard"])
def test_guarded_evaluator_requires_both_source_and_guard_hooks(missing):
    coordinate=extension.Coordinate("core5__equal","LW","mean_es")
    runner=SimpleNamespace(evaluate_flow=synthetic_evaluate)
    setattr(runner,"_matrix_execution_guard" if missing=="source" else "_matrix_evaluation_source",
        (lambda function:function) if missing=="source" else synthetic_evaluate)
    with pytest.raises(ValueError,match="PAIRED_MATRIX_SOURCE_AND_EXECUTION_GUARD"):
        extension.evaluate_flow(runner,coordinate,None,coordinate.forecast_pack,"LW","mean_es",binding=bound("mean_es"))


def test_guarded_evaluator_never_executes_raw_reprojection_after_guard_rejects():
    coordinate=extension.Coordinate("core5__equal","LW","mean_es")
    events=[]
    def protect(function):
        events.append("wrapped")
        def reject(*args,**kwargs):
            events.append("guarded");raise ValueError("SYNTHETIC_EXACT_ROUTE_REJECTED")
        return reject
    runner=SimpleNamespace(evaluate_flow=lambda *a:pytest.fail("guarded wrapper is not an AST source"),
        _matrix_evaluation_source=synthetic_evaluate,_matrix_execution_guard=protect)
    with pytest.raises(ValueError,match="EXPLICIT_POLICY_FACTORY"):
        extension.evaluate_flow(runner,coordinate,None,coordinate.forecast_pack,"LW","mean_es",binding=bound("mean_es"))
    with pytest.raises(ValueError,match="SYNTHETIC_EXACT_ROUTE_REJECTED"):
        extension.evaluate_flow(runner,coordinate,None,coordinate.forecast_pack,"LW","mean_es",binding=bound("mean_es"),
            make_policy=lambda *a:pytest.fail("raw evaluator must not be called after guard rejection"))
    assert events==["wrapped","guarded"]


@pytest.mark.parametrize("kind",["source","guard","guard_result"])
def test_guarded_evaluator_rejects_noncallable_hooks_and_guard_result(kind):
    coordinate=extension.Coordinate("core5__equal","LW","mean_es")
    runner=SimpleNamespace(evaluate_flow=lambda *args:pytest.fail("guard must not fall through"),
        _matrix_evaluation_source=synthetic_evaluate,_matrix_execution_guard=lambda function:function)
    if kind=="source":runner._matrix_evaluation_source=None
    elif kind=="guard":runner._matrix_execution_guard=None
    else:runner._matrix_execution_guard=lambda function:None
    with pytest.raises(ValueError,match="CALLABLE"):
        extension.evaluate_flow(runner,coordinate,None,coordinate.forecast_pack,"LW","mean_es",binding=bound("mean_es"),
            make_policy=lambda *args:pytest.fail("invalid execution guard must never call policy"))



def advancing_r2_provider(*, defect=None):
    """Synthetic values with simulated frozen-history receipt semantics only."""
    initial, january = source_r2_fixture()
    initial = replace(initial, source_receipt=replace(initial.source_receipt,
        synthetic=False, mechanism=True, status="FROZEN_HISTORY_MECHANISM_SOURCE_BOUND",
        scientific_contract_identity="SYNTHETIC_ONLY_CONTRACT", scientific_contract_sha256="d"*64,
        observation_time_assumed=True, actual_snapshot_timestamp=pd.Timestamp("2025-04-01T00:00:00Z")))
    additions=initial.observations.iloc[:len(initial.assets)].copy()
    for field,value in dict(origin_at="2025-01-02T21:00:00Z",entry_at="2025-01-03T14:30:00Z",
        endpoint_at="2025-01-10T14:30:00Z",matured_at="2025-01-10T14:31:00Z",
        available_at="2025-01-10T14:32:00Z").items(): additions[field]=pd.Timestamp(value)
    later=replace(initial,observations=pd.concat([initial.observations,additions],ignore_index=True))
    if defect == "uid": later=replace(later,asset_uids={**later.asset_uids,later.assets[0]:"NEW_UID"})
    if defect == "source": later=replace(later,source_receipt=replace(later.source_receipt,source_sha256="e"*64))
    if defect == "contract": later=replace(later,source_receipt=replace(later.source_receipt,scientific_contract_sha256="e"*64))
    if defect == "epoch": later=replace(later,identity_epoch="NEW_EPOCH")
    def provider(method,date,assets):
        value=initial if pd.Timestamp(date).month == 1 else later
        asof=pd.Timestamp(date).normalize().tz_localize("UTC")+pd.Timedelta(hours=21)
        position=value.sessions.get_loc(asof)
        receipt=replace(value.source_receipt,available_at=value.sessions[position-1])
        return replace(value,source_receipt=receipt),asof
    return initial,january,provider


def test_quarterly_r2_reuses_same_immutable_january_state_after_mature_window_and_clock_advance():
    typed,january,provider=advancing_r2_provider()
    events=[]
    hook=extension.R2FitHook(provider,durable_reserve=events.append)
    first,key=hook("RU",cutoff=january,assets=typed.assets)
    assert first.status=="FITTED",first.failure_reason
    spent,count=hook.budget.learned_total,len(events)
    frozen_asof=first.fitted_state["typed_state"].as_of
    repeated,repeated_key=hook("RU",cutoff="2025-02-03",assets=typed.assets)
    assert repeated is first and repeated_key==key
    assert repeated.fitted_state["typed_state"].as_of==frozen_asof==january
    assert hook.last_reservation_delta==0 and hook.budget.learned_total==spent and len(events)==count
    assert repeated.fitted_state["new_learned_reservations"]>0


@pytest.mark.parametrize("defect",["uid","source","contract","epoch"])
def test_quarterly_r2_changed_identity_cannot_reuse_or_fit_off_schedule(defect):
    typed,january,provider=advancing_r2_provider(defect=defect)
    events=[];hook=extension.R2FitHook(provider,durable_reserve=events.append)
    first,_=hook("RU",cutoff=january,assets=typed.assets)
    assert first.status=="FITTED",first.failure_reason
    spent,count=hook.budget.learned_total,len(events)
    with pytest.raises(ValueError,match="SCHEDULED_STATE_UNAVAILABLE_OR_SOURCE_UID_DOMAIN_CHANGED"):
        hook("RU",cutoff="2025-02-03",assets=typed.assets)
    assert hook.budget.learned_total==spent and len(events)==count


def test_monthly_r2_fits_on_original_next_month_boundary_instead_of_reusing_quarter():
    typed,january,provider=advancing_r2_provider()
    events=[];hook=extension.R2FitHook(provider,durable_reserve=events.append)
    first,key=hook("RD",cutoff=january,assets=typed.assets)
    spent=hook.budget.learned_total
    second,second_key=hook("RD",cutoff="2025-02-03",assets=typed.assets)
    assert first.status==second.status=="FITTED"
    assert second_key!=key and second is not first
    assert hook.last_reservation_delta>0 and hook.budget.learned_total>spent
    assert second.fitted_state["typed_state"].as_of==pd.Timestamp("2025-02-03T21:00:00Z")


def participation_context(*, held=0., decision=False, reserved=False, operational=False):
    names=tuple("ABCDEF")
    units=np.zeros((1,6));units[0,-1]=held
    masks={key:np.zeros((1,6),bool) for key in ("decision_mask","reserved_mask","operational_mask")}
    masks["decision_mask"][0,:-1]=True
    for key,value in (("decision_mask",decision),("reserved_mask",reserved),("operational_mask",operational)):
        masks[key][0,-1]=value
    return SimpleNamespace(tickers=names,current_units=units,**masks)


def padded_record(*, scenario=True):
    _,_,market,scenarios,references=inputs();date=market.dates[0]
    item=copy.deepcopy((scenarios if scenario else references)[date])
    item.update(assets=tuple(market.tickers[:-1]),account_assets=tuple(market.tickers),
        inactive_zero_padding_assets=(market.tickers[-1],))
    item["values"]=item["values"][:,:-1] if scenario else item["values"][:-1]
    return date,item


def test_proven_inactive_scenario_column_pads_zero_and_reaches_original_cash_account():
    forecast,past,market,scenarios,_=inputs()
    market.input_present[:,-1]=False;market.new_buy_eligible[:,-1]=False
    forecast=forecast[forecast.ticker!="F"].copy()
    for date,item in scenarios.items():
        item.update(assets=tuple(market.tickers[:-1]),account_assets=tuple(market.tickers),
            inactive_zero_padding_assets=("F",),values=item["values"][:,:-1])
    requested=[]
    def lazy_scenario(date,full_assets,required_assets):
        # Reading a UID/label for F here would fail: it has not yet IPO'd.
        assert full_assets==tuple("ABCDEF") and required_assets==tuple("ABCDE")
        requested.append((date,full_assets,required_assets))
        return scenarios[date]
    policy=bound("mean_es",scenarios=lazy_scenario).ConsensusJointPolicy(forecast,past)
    replay=run_cash_account(market,["cell"],policy,max_positions=20)
    assert requested and policy.diagnostics and replay.final_units[0,-1]==0.
    assert all(d["status"]!="NOT_TESTABLE_OR_INFEASIBLE_PRESERVE_UNITS" for d in policy.diagnostics)
    for audit in policy.diagnostics:
        domain=audit["account_input_domains"]["scenarios"]
        assert domain["estimated_assets"]==tuple("ABCDE")
        assert domain["inactive_zero_padding_assets"]==("F",)
        assert "F" not in domain["required_active_held_locked_assets"]
    np.testing.assert_array_equal(policy.scenarios[market.dates[0]][:,-1],0.)
    assert not market.input_present[:,-1].any()


@pytest.mark.parametrize("state",[dict(held=1e-30),dict(decision=True),dict(reserved=True),dict(operational=True)])
def test_scenario_padding_rejects_any_held_eligible_reserved_or_operational_column(state):
    date,item=padded_record()
    required=extension._participating_assets(participation_context(**state))
    with pytest.raises(ValueError,match="ALL_ACTIVE_HELD_LOCKED_INPUT_ASSETS_REQUIRED"):
        extension._qualified_vector({date:item},date,tuple("ABCDEF"),scenario=True,required_assets=required)


@pytest.mark.parametrize("defect",["undeclared","unknown","misordered","future_maturity"])
def test_scenario_padding_still_requires_exact_domain_metadata_and_maturity(defect):
    date,item=padded_record()
    if defect=="undeclared":item.pop("inactive_zero_padding_assets")
    if defect=="unknown":item["assets"]=("A","B","C","D","UNKNOWN")
    if defect=="misordered":item["assets"]=tuple(reversed(item["assets"]))
    if defect=="future_maturity":item["label_mature_max"]=date+pd.Timedelta(days=1)
    with pytest.raises(ValueError):
        extension._qualified_vector({date:item},date,tuple("ABCDEF"),scenario=True,
            required_assets=extension._participating_assets(participation_context()))


def test_reference_current_aware_signal_close_is_accepted_only_with_exact_decision_asof():
    date,item=padded_record(scenario=False)
    actual=pd.Timestamp("2025-07-01T16:00:00",tz="America/New_York")
    item.update(decision_as_of=actual,available_at=actual)
    value,metadata=extension._qualified_vector({date:item},date,tuple("ABCDEF"),scenario=False,
        required_assets=extension._participating_assets(participation_context()),decision_as_of=actual,
        return_metadata=True)
    np.testing.assert_array_equal(value[:-1],item["values"])
    assert value[-1]==0. and metadata["inactive_zero_padding_assets"]==("F",)
    for field,invalid in (("available_at",actual+pd.Timedelta(seconds=1)),
                           ("decision_as_of",actual-pd.Timedelta(seconds=1))):
        broken=copy.deepcopy(item);broken[field]=invalid
        with pytest.raises(ValueError,match="EXACT_CURRENT_SIGNAL_ASOF"):
            extension._qualified_vector({date:broken},date,tuple("ABCDEF"),scenario=False,
                required_assets=tuple("ABCDE"),decision_as_of=actual)
    item.pop("decision_as_of")
    with pytest.raises(ValueError,match="STRICT_PRE2026_AVAILABLE_CLOCK_REQUIRED"):
        extension._qualified_vector({date:item},date,tuple("ABCDEF"),scenario=False,
            required_assets=tuple("ABCDE"),decision_as_of=actual)



@pytest.mark.parametrize("clock",["backward","future"])
def test_quarterly_r2_advancing_source_cutoff_cannot_move_backward_or_beyond_decision(clock):
    typed,january,original=advancing_r2_provider()
    def provider(method,date,assets):
        value,asof=original(method,date,assets)
        if pd.Timestamp(date).month==2:
            observed=january-pd.Timedelta(days=2) if clock=="backward" else asof+pd.Timedelta(seconds=1)
            value=replace(value,source_receipt=replace(value.source_receipt,available_at=observed))
        return value,asof
    events=[];hook=extension.R2FitHook(provider,durable_reserve=events.append)
    hook("RU",cutoff=january,assets=typed.assets)
    spent,count=hook.budget.learned_total,len(events)
    with pytest.raises(ValueError,match="OBSERVATION_CLOCK_CHANGED_BACKWARD_OR_FUTURE"):
        hook("RU",cutoff="2025-02-03",assets=typed.assets)
    assert hook.budget.learned_total==spent and len(events)==count


def test_quarterly_r2_missing_scheduled_state_is_explicit_block_before_any_reservation():
    typed,_,provider=advancing_r2_provider()
    events=[];hook=extension.R2FitHook(provider,durable_reserve=events.append)
    with pytest.raises(ValueError,match="SCHEDULED_STATE_UNAVAILABLE_OR_SOURCE_UID_DOMAIN_CHANGED"):
        hook("RU",cutoff="2025-02-03",assets=typed.assets)
    assert hook.budget.learned_total==0 and not events


def test_lazy_reference_receives_real_account_required_domain_and_current_signal_clock():
    forecast,past,market,_,records=inputs()
    market.signal_asof=[d.tz_localize("America/New_York")+pd.Timedelta(hours=16) for d in market.dates]
    clocks=dict(zip(market.dates,market.signal_asof));calls=[]
    def provider(date,full_assets,required_assets):
        assert full_assets==required_assets==tuple(market.tickers)
        calls.append(date)
        return dict(records[date],decision_as_of=clocks[date],available_at=clocks[date])
    policy=bound("tracking_error",references=provider).ConsensusJointPolicy(forecast,past)
    replay=run_cash_account(market,["cell"],policy,max_positions=20)
    assert calls and policy.diagnostics and np.isfinite(replay.daily.nav).all()
    assert all(d["status"]!="NOT_TESTABLE_OR_INFEASIBLE_PRESERVE_UNITS" for d in policy.diagnostics)
    assert all(d["account_input_domains"]["reference"]["estimated_assets"]==tuple(market.tickers)
               for d in policy.diagnostics)



def test_unrelated_decision_never_reads_lazy_scenario_or_reference_sources():
    forecast,past,market,_,_=inputs()
    def unused_provider(*args):pytest.fail("cost_aware must not read scenario labels or reference source")
    policy=bound("cost_aware",scenarios=unused_provider,references=unused_provider).ConsensusJointPolicy(forecast,past)
    replay=run_cash_account(market,["cell"],policy,max_positions=20)
    assert policy.diagnostics and np.isfinite(replay.daily.nav).all()
    assert all(d["account_input_domains"]==dict(scenarios=None,reference=None) for d in policy.diagnostics)


def test_b_pto_new_objective_does_not_expand_existing_consensus_catalogue():
    assert "robust_cost_aware" in extension.allocation.ALLOCATION_METHODS
    assert "robust_cost_aware" not in joint.ALLOCATION_METHODS
    cat=extension.catalogue()
    assert "robust_cost_aware" not in cat["decision_methods"]
    assert "robust_cost_aware" not in cat["exact_owner_decision_aliases"]
    assert cat["exact_owner_decision_aliases"]["risk_constrained_cash"] == "volatility_targeting"
    invalid=scope();invalid["decision_methods"].append("robust_cost_aware")
    with pytest.raises(ValueError):extension.validate_scope(invalid)
