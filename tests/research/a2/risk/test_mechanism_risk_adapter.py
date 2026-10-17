"""R10 generated synthetic only: shared owner, no data reader/real run."""
from dataclasses import replace
import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.risk import mechanism_risk_adapter as adapter
from scripts.research.a2.risk.shared_risk_engine_r2 import SourceReceipt, RiskInput, SharedRiskEngine


def generated(assets=6, horizons=(3,5,10,20)):
    sessions=pd.bdate_range("2022-01-03","2025-03-01",tz="UTC")+pd.Timedelta(hours=21)
    as_of=pd.Timestamp("2025-01-01T21:00:00Z")
    names=tuple("A"+str(i) for i in range(assets));rng=np.random.default_rng(83)
    receipt=SourceReceipt("GENERATED_STOCK","V1","a"*64,pd.Timestamp("2020-01-01",tz="UTC"))
    rows=[];end=sessions.get_loc(as_of)-23
    for i in range(end-119,end+1):
        for h in horizons:
            for a in names:
                rows.append(dict(asset=a,origin_at=sessions[i],entry_at=sessions[i+1]-pd.Timedelta(hours=6),
                    endpoint_at=sessions[i+h+1]-pd.Timedelta(hours=6),matured_at=sessions[i+h+1]-pd.Timedelta(hours=5),
                    available_at=sessions[i+h+1]-pd.Timedelta(hours=4),horizon=h,uid="SID_"+a,
                    identity_epoch="SYNTHETIC_EPOCH",source_identity=receipt.source_identity,
                    return_value=rng.normal(0,.01)*np.sqrt(h)))
    frame=pd.DataFrame(rows)
    return RiskInput(names,sessions,frame,receipt,{a:"SID_"+a for a in names}),as_of


def support(inputs,h=5):
    out=inputs.observations.loc[inputs.observations.horizon.eq(h),["asset","origin_at"]].copy()
    out["qualified"]=True
    return out


def frozen(plan):
    return dict(frozen=True,risk_fit_admitted=True,plan_sha256=plan["plan_sha256"],code_pins=plan["code_pins"],
                remaining_learned_units=220,**{k:False for k in adapter.FLAGS},**{"2026_locked":True})


def ack(event):
    return dict(ack=True,plan_sha256=event["plan_sha256"],reserved_units=event["required_units"],reservation_id="SYNTHETIC_R10")


def run(inputs,as_of,methods=("DIAG","LW"),h=5,**kw):
    proof=support(inputs,h)
    plan=adapter.audit(inputs,methods,horizon=h,as_of=as_of,support_metadata=proof)
    return adapter.estimate(inputs,plan,frozen(plan),support_metadata=proof,reserve_callback=ack,**kw)


def test_metadata_only_no_y_numeric_read_and_future_append():
    inputs,as_of=generated();proof=support(inputs)
    poison=inputs.observations.copy();poison["return_value"]="MUST_NOT_PARSE"
    a=adapter.audit(replace(inputs,observations=poison),("DIAG","LW"),horizon=5,as_of=as_of,support_metadata=proof)
    b=adapter.audit(inputs,("DIAG","LW"),horizon=5,as_of=as_of,support_metadata=proof)
    assert a==b and a["numeric_finiteness"]=="UNKNOWN_NOT_READ"
    future=poison.iloc[:1].copy()
    for c in ["origin_at","entry_at","endpoint_at","matured_at","available_at"]:future[c]+=pd.Timedelta(days=900)
    appended=replace(inputs,observations=pd.concat([poison,future],ignore_index=True))
    assert adapter.audit(appended,("DIAG","LW"),horizon=5,as_of=as_of,support_metadata=proof)==a


@pytest.mark.parametrize("h",[3,5,10,20])
def test_true_native_horizon_shared_estimate_and_component_count(h):
    inputs,as_of=generated();events=[]
    result=run(inputs,as_of,h=h,on_component_start=lambda e:(events.append(e) or {"ack":True}))
    assert result["status"]=="COMPLETE_MECHANISM_ONLY",result["failures"]
    assert result["root_weighted_reserved_units"]==result["attempted_learned_units"]==3
    assert result["failed_started_units"]==result["unused_reserved_units"]==0
    assert len(events)==3 and result["scaler_fits"]==1
    assert all(state.horizon==h for state in result["states"].values())
    assert not result["admission"]["account_qualified"]
    frame=adapter._numeric_frame(inputs,adapter._supported(inputs,pd.Timestamp(result["states"]["DIAG"].cutoff),h,support(inputs,h)),result["states"]["DIAG"].cutoff,h)
    np.testing.assert_allclose(np.diag(result["states"]["DIAG"].covariance),frame.var().values)


@pytest.mark.parametrize("field",["frozen","risk_fit_admitted","2026_locked"])
@pytest.mark.parametrize("value",[False,None,1])
def test_literal_authorization_fails_before_reservation(field,value):
    inputs,as_of=generated();proof=support(inputs)
    plan=adapter.audit(inputs,("DIAG",),horizon=5,as_of=as_of,support_metadata=proof)
    auth=frozen(plan);auth[field]=value
    with pytest.raises(ValueError,match="AUTHORIZATION"):
        adapter.estimate(inputs,plan,auth,support_metadata=proof,reserve_callback=lambda e:pytest.fail("NO RESERVATION"))


@pytest.mark.parametrize("value",[False,None,1])
def test_ack_literal_true_before_numeric(value):
    inputs,as_of=generated();frame=inputs.observations.copy();frame["return_value"]="NO_NUMERIC"
    inputs=replace(inputs,observations=frame);proof=support(inputs)
    plan=adapter.audit(inputs,("DIAG",),horizon=5,as_of=as_of,support_metadata=proof)
    bad=lambda e:{**ack(e),"ack":value}
    with pytest.raises(ValueError,match="WHOLE_PLAN_ACK"):
        adapter.estimate(inputs,plan,frozen(plan),support_metadata=proof,reserve_callback=bad)


def test_post_ack_source_failure_is_zero_fit_with_reserved_capacity():
    inputs,as_of=generated();frame=inputs.observations.copy();frame["return_value"]="BAD_SOURCE"
    result=run(replace(inputs,observations=frame),as_of)
    assert result["status"]=="BLOCKED_INPUT"
    assert result["attempted_learned_units"]==result["owner_actual_learned_units"]==0
    assert result["unused_reserved_units"]==3 and not result["budget_refund"]


def test_factor_dimension_metadata_block_before_fit():
    inputs,as_of=generated(assets=3)
    plan=adapter.audit(inputs,("PCA",),horizon=5,as_of=as_of,support_metadata=support(inputs))
    assert plan["status"]=="BLOCKED" and any("FACTOR_COUNT" in x for x in plan["block_reasons"])


@pytest.mark.parametrize("method",["GARCH","GJR_GARCH"])
def test_garch_parameter_failure_does_not_claim_correlation_started(monkeypatch,method):
    inputs,as_of=generated()
    bad=lambda x,asymmetric:(np.asarray([.01,.1,.8]),{"success":False})
    monkeypatch.setattr(adapter.joint,"_shared_garch_definition",lambda:(bad,"b"*64))
    result=run(inputs,as_of,methods=(method,))
    assert result["status"]=="FAILED_NO_RETRY",result
    assert result["root_weighted_reserved_units"]==3
    assert result["attempted_learned_units"]==2 and result["failed_started_units"]==1
    assert result["unused_reserved_units"]==1
    assert not any("correlation" in e["name"] for e in result["component_starts"])


def test_garch_correlation_failure_counts_two_actual_components(monkeypatch):
    inputs,as_of=generated()
    good=lambda x,asymmetric:(np.asarray([.01,.1,.8]),{"success":True})
    monkeypatch.setattr(adapter.joint,"_shared_garch_definition",lambda:(good,"b"*64))
    class BadWolf:
        def __init__(self,**kwargs):pass
        def fit(self,*args,**kwargs):raise ValueError("CORRELATION_FAILED")
    monkeypatch.setattr(adapter.joint,"LedoitWolf",BadWolf)
    result=run(inputs,as_of,methods=("GARCH",))
    assert result["status"]=="FAILED_NO_RETRY"
    assert result["attempted_learned_units"]==3 and result["failed_started_units"]==1
    assert result["unused_reserved_units"]==0


def test_old_owner_all4_short_recipe_actual13_not52():
    path=Path(__file__).with_name("test_short_history_risk_r4.py")
    spec=importlib.util.spec_from_file_location("r10_short_synthetic_fixture",path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    inputs,as_of,proof=module.fixture_input()
    plan=adapter.audit(inputs,adapter.SHORT,horizon=5,as_of=as_of,support_metadata=proof)
    assert plan["required_units"]==13 and plan["status"]=="METADATA_READY",plan
    result=adapter.estimate(inputs,plan,frozen(plan),support_metadata=proof,reserve_callback=ack)
    assert result["status"]=="COMPLETE_MECHANISM_ONLY",result["failures"]
    assert result["attempted_learned_units"]==13 and len(result["states"])==4
    assert result["deterministic_transforms"]>0


def test_projection_fixed_q_delta_and_failclosed_future_or_reference():
    inputs,as_of=generated();result=run(inputs,as_of)
    state=result["states"]["DIAG"];refs={"DIAG":{"verified":True,"risk_state_id":state.risk_state_id}}
    args=dict(assets=inputs.assets,uids=inputs.asset_uids,reference_assets=inputs.assets[:3],decision_at=as_of,horizon=5,verified_state_refs=refs)
    projected=adapter.consumer_projection(result["states"],"R1",**args)
    assert list(projected["reference_weights"].values())==[1/3]*3+[0.]*3
    marginal=projected["features"]["marginal_variance"];sigma=projected["diagnostics"]["predicted_portfolio_sigma"]
    assert adapter.replacement_risk_delta(projected,"A1","A0")==pytest.approx((marginal[1]-marginal[0])/(2*sigma+1e-12))
    with pytest.raises(ValueError):adapter.consumer_projection(result["states"],"R1",**{**args,"decision_at":as_of-pd.Timedelta(days=1)})
    with pytest.raises(ValueError):adapter.consumer_projection(result["states"],"R1",**{**args,"verified_state_refs":{"DIAG":{"verified":1,"risk_state_id":state.risk_state_id}}})
    with pytest.raises(ValueError):adapter.consumer_projection(result["states"],"R7",**args)
    assert all(projected[k] is False for k in adapter.FLAGS)


@pytest.mark.parametrize("sid",["UNKNOWN","UNBOUND","nan","A2_TICKER_x"])
def test_unknown_sid_metadata_rejected(sid):
    inputs,as_of=generated();uids={**inputs.asset_uids,"A0":sid}
    with pytest.raises(ValueError,match="SID"):
        adapter.audit(replace(inputs,asset_uids=uids),("DIAG",),horizon=5,as_of=as_of,support_metadata=support(inputs))


def test_no_future_state_backfill_and_r0_lock():
    inputs,as_of=generated();state=run(inputs,as_of)["states"]["DIAG"]
    with pytest.raises(ValueError):adapter._state_matrix(state,inputs.assets,inputs.asset_uids,pd.Timestamp("2023-02-01",tz="UTC"),5)
    with pytest.raises(ValueError):adapter.consumer_projection({},"R0",assets=inputs.assets,uids=inputs.asset_uids,reference_assets=inputs.assets,decision_at=pd.Timestamp("2026-01-01",tz="UTC"),verified_state_refs={})



def synthetic_spec(years=(2025,)):
    return adapter._seal(dict(schema=adapter.STUDY_SCHEMA,years=years,code_pins=adapter.code_pins(),
        max_risk_learned_units=220,max_scheduled_learned_units=216,shared_direction_max_units_per_year=36,
        representations=("R0","R1","R2","R3","R4","R5","R6","R7"),
        shared_domain_priority=("FULL_REQUESTED_POOL","SOURCE_QUALIFIED_COMPONENT","COMPLETE_COMMON_COMPONENT","ADDITIVE_RISK_CORRECTION"),
        **{k:False for k in adapter.FLAGS},**{"2026_locked":True}))


def test_single_primitive_failure_continues_independent_directions(monkeypatch):
    inputs,as_of=generated();original=adapter.joint._estimate
    def faulty(method,*args,**kwargs):
        if method=="SCOV":raise ValueError("SCIENTIFIC_FAILURE_RETAINED")
        return original(method,*args,**kwargs)
    monkeypatch.setattr(adapter.joint,"_estimate",faulty)
    result=run(inputs,as_of,methods=("SCOV","LW"))
    assert result["status"]=="COMPLETE_WITH_FAILED_DIRECTIONS"
    assert "LW" in result["states"] and "SCOV" not in result["states"]
    assert result["attempted_learned_units"]==3 and result["failed_started_units"]==1
    assert result["failures"][0]["scientific_retry"]==0


def test_whole_shared_engine_closure_36_cap_and_all_projection_groups():
    path=Path(__file__).with_name("test_shared_risk_engine_r2.py")
    spec=importlib.util.spec_from_file_location("r10_shared_synthetic_fixture",path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    inputs,asof=module.synthetic_input()
    source=adapter._shared_produce(inputs,asof,synthetic_spec(),ack,lambda e:{"ack":True})
    assert all(r["method"]=="RM" and r["status"]=="NOT_SCHEDULED_NEW_SCALED_PROXY" for r in source["blocked"]),source["blocked"]
    assert source["attempted_learned_units"]<=36
    states=source["states"]
    primitive=run(inputs,asof,methods=("DIAG","LW","OAS","CONSTANT_CORR"))
    states={**states,**primitive["states"]}
    refs={m:{"verified":True,"risk_state_id":s.risk_state_id} for m,s in states.items()}
    for r in ("R1","R2","R3","R4","R5","R6","R7"):
        projection=adapter.consumer_projection(states,r,assets=inputs.assets,uids=inputs.asset_uids,
            reference_assets=inputs.assets,decision_at=asof,verified_state_refs=refs)
        assert projection["diagnostics"]["PSD"]
        if r=="R7":
            assert set(projection["features"]["group_features"])=={"R2","R3","R4","R5","R6"}
            study={"projections":[dict(request=dict(date="2025-01-01",assets=inputs.assets,uids=inputs.asset_uids,horizon=5,cohort="GENERATED"),representation=r,projection=projection)]}
            row=next(adapter.projection_feature_rows(study))
            assert "risk_R4_portfolio_downside_sigma" in row and "risk_R5_active_regime" in row
            assert not any("probability" in k for k in row)
        if r=="R4":assert np.isfinite(projection["features"]["fixed_q_smooth_CVaR"])
    assert source["RM_coordinate"].startswith("H5_TIME_SCALE_APPROX")


def test_executable_study_helper_generated_no_reader_no_writer():
    inputs,asof=generated();proof=support(inputs)
    request=dict(date="2025-01-01",decision_at=asof,assets=inputs.assets,uids=inputs.asset_uids,
                 reference_assets=inputs.assets[:3],horizon=5,cohort="GENERATED")
    out=adapter.produce_study_risk(None,{"risk_study_spec":synthetic_spec()},reserve_callback=ack,
        on_component_start=lambda e:{"ack":True},synthetic_inputs={(2025,5,"PRIMITIVE"):(inputs,proof,asof)},projection_requests=[request])
    assert out["new_account"]==0 and out["states"] and out["projections"]
    r3_coverage=[c for c in out["coverage"] if c["representation"]=="R3"]
    assert len(r3_coverage)==1 and r3_coverage[0]["status"]=="PASS_MECHANISM_PROJECTION"
    r3=next(p for p in out["projections"] if p["representation"]=="R3")
    assert r3["projection"]["features"]["factor_view"]=="PCA_SHARED_WHOLE_STATE"
    pca=next(s for s in out["states"] if s.method=="PCA")
    assert r3["state_refs"]["PCA"]=={"verified":True,"risk_state_id":pca.risk_state_id}
    assert pca.source_identity==inputs.source_receipt.source_identity
    assert tuple(pca.assets)==inputs.assets
    assert all(pca.coverage[a]["uid"]==inputs.asset_uids[a] for a in inputs.assets)
    assert out["attempted_learned_units"]<=220


def test_native_domain_assembly_retains_sid_quantity_segment_original_source():
    inputs,asof=generated();observed=inputs.observations.copy()
    epochs={a:"SEGMENT_"+a for a in inputs.assets}
    observed["security_segment_epoch"]=observed.asset.map(epochs)
    observed["original_label_identity"]="ORIGINAL_NATIVE_H"
    observed["quantity_multiplier"]=1.
    for k,v in {"aggregate_domain_bound":True,"mechanism_coordinate_supported":True,"strict_endpoint_source_qualified":False,"historical_available_at_bound":False}.items():observed[k]=v
    built=adapter.assemble_native(observed,sessions=inputs.sessions,assets=inputs.assets,uids=inputs.asset_uids,
        asset_epochs=epochs,source_receipt=inputs.source_receipt,identity_epoch=inputs.identity_epoch)
    plan=adapter.audit(built,("DIAG",),horizon=5,as_of=asof,support_metadata=support(inputs))
    assert plan["assembly_binding"]["asset_epochs"]==epochs and plan["native_provenance_sha256"]
    bad=observed.copy();bad.loc[0,"security_segment_epoch"]="WRONG"
    with pytest.raises(ValueError,match="PROVENANCE"):
        adapter.assemble_native(bad,sessions=inputs.sessions,assets=inputs.assets,uids=inputs.asset_uids,
            asset_epochs=epochs,source_receipt=inputs.source_receipt,identity_epoch=inputs.identity_epoch)


def test_shared_state_exact_context_no_contract_sha_substitution():
    inputs,asof=generated();state=run(inputs,asof)["states"]["DIAG"]
    meta=dict(risk_state_id=state.risk_state_id,source_identity=state.source_identity,
        source_cache_identity=inputs.source_receipt.cache_identity(),assets=inputs.assets,asset_uids=inputs.asset_uids,
        identity_epoch=state.identity_epoch,return_coordinate=state.return_coordinate,horizon=state.horizon,
        as_of=state.as_of.isoformat(),cutoff=state.cutoff.isoformat(),status=state.status)
    assert adapter.reuse_admission(meta,meta,decision_at=asof)["new_learned_units"]==0
    expected={**meta,"source_cache_identity":{"scientific_contract_sha256":"NEW_R10_IS_NOT_OLD_B"}}
    with pytest.raises(ValueError,match="EXACT_CONTEXT"):
        adapter.reuse_admission(meta,expected,decision_at=asof)



def test_real_bundle_packaging_path_uses_only_generated_reader_endpoints(monkeypatch):
    from types import SimpleNamespace
    from scripts.research.a2.training import stateful_mechanism_inputs as source_owner
    cal=pd.bdate_range("2022-01-03","2025-02-03")
    names=("A0","A1")
    flags=pd.DataFrame([dict(signal_date=d,ticker=a,security_id="SID_"+a) for d in cal for a in names])
    quotes=pd.DataFrame([dict(trade_date=d,ticker=a,open=100+j*.01+(0.2 if a=="A1" else 0.)) for j,d in enumerate(cal) for a in names])
    class GeneratedReader:
        calendar=cal
        train_flags=flags
        pred_flags=flags
        permit=SimpleNamespace(design_sha256="c"*64)
        records={"raw_market_prices":{"sha256":"a"*64,"file_fingerprint":{"mtime_ns":pd.Timestamp("2026-10-04",tz="UTC").value}}}
        def read(self,name,columns,filters):
            assert name=="raw_market_prices" and filters==[("trade_date","<",source_owner.BOUNDARY)]
            return quotes[columns].copy()
    def no_events(frame,events):
        return np.ones(len(frame)),np.zeros(len(frame),dtype=bool),np.zeros(len(frame),dtype=int)
    monkeypatch.setattr(source_owner,"load_event_owner",lambda p:([],no_events))
    bundle=SimpleNamespace(reader=GeneratedReader(),source_manifest={"metadata_pins":{},"source_hashes":{"generated":"a"*64}})
    native,domains,notes=adapter._real_native_inputs(bundle,synthetic_spec())
    assert (2025,5,"PRIMITIVE") in native
    inputs,proof,asof=native[(2025,5,"PRIMITIVE")]
    assert set(inputs.observations.horizon)=={3,5,10,20}
    assert inputs.observations.aggregate_domain_bound.eq(True).all()
    assert asof==pd.Timestamp("2025-01-01T21:00:00Z")
    assert inputs.source_receipt.strict_PIT_promotion_eligible is False
    assert notes["regime_probability"].startswith("BLOCKED_INPUT")
    assert inputs.observations.original_label_identity.notna().all()


# New task synthetic-only tests; no source reader, worker, real fit or data file.
def fixed_policy_state(family="DIAG", n=80):
    assets=tuple(f"A{i:03d}" for i in range(n))
    uids={a:"SID_"+a for a in assets}
    support={"stock_source":"a"*64,"benchmark_source":"b"*64}
    state=dict(status="ESTIMATED",family=family,assets=assets,asset_uids=uids,
        asset_epochs={a:"SYNTHETIC_EPOCH" for a in assets},horizon_sessions=5,
        return_coordinate=adapter.COORDINATE,
        as_of="2025-01-02T21:00:00+00:00",cutoff="2025-01-01T21:00:00+00:00",
        security_coordinate="SYNTHETIC_CURRENT_SHARE",
        source_support_identity=support,source_cache_identity={"id":"SYNTHETIC","sha256":"a"*64},
        recipe_sha256=adapter.content_hash(adapter.fixed_policy_risk_specification()),
        covariance=np.eye(n),native_assets=assets)
    from scripts.research.a2.risk.event_risk_contract_r5 import structural_identity
    state["structural_sha256"]=structural_identity(assets=assets,uids=uids,
        epochs=state["asset_epochs"],security_coordinate=state["security_coordinate"],
        source_support_identity=support)
    return state


def fixed_policy_row(at, n=6):
    assets=tuple(f"A{i:03d}" for i in range(n))
    return dict(decision_at=at,assets=assets,asset_uids={a:"SID_"+a for a in assets},
        asset_epochs={a:"E0" for a in assets},security_coordinate="CURRENT_SHARE",
        family_source_support={f:{"stock_source":"a"*64,"dependency":"FIXED_"+f}
            for f in adapter.FIXED_POLICY_RISK_FAMILIES})


def test_fixed_policy_exact_eighteen_and_real_budget_components():
    recipe=adapter.fixed_policy_risk_specification()
    assert tuple(recipe["families"])==adapter.FIXED_POLICY_RISK_FAMILIES
    assert len(recipe["families"])==18
    assert recipe["learned_units_per_refresh_upper_bound"]==71
    assert recipe["scientific_retry"]==0 and not recipe["strict_PIT_promotion_eligible"]
    assert recipe["families"]["GARCH"]["parameters"]==adapter.joint.specs("GARCH")
    assert recipe["families"]["GJR_GARCH"]["parameters"]==adapter.joint.specs("GJR_GARCH")
    assert recipe["families"]["UNCERTAINTY_JACKKNIFE"]["replica_count"]==4
    assert recipe["families"]["TAIL_CVAR"]["completion"]=="NONE"


def test_fixed_policy_metadata_monthly_invalidations_and_union_budget():
    rows=[fixed_policy_row("2024-01-02T21:00:00Z"),
          fixed_policy_row("2024-01-03T21:00:00Z"),
          fixed_policy_row("2024-02-01T21:00:00Z"),
          fixed_policy_row("2024-02-02T21:00:00Z")]
    rows[-1]["family_source_support"]["FF48_HIERARCHICAL"]["industry_source"]="c"*64
    plan=adapter.fixed_policy_risk_refresh_nodes(rows)
    assert len(plan["nodes"])==18+18+1
    assert plan["refresh_contexts"]==3 and plan["learned_units_upper_bound"]==3*71
    assert plan["nodes"][-1]["family"]=="FF48_HIERARCHICAL" and plan["numeric_reads"]==0


@pytest.mark.parametrize("bad",["performance","winner","risk_values","returns"])
def test_fixed_policy_no_outcome_driven_refresh(bad):
    row=fixed_policy_row("2024-01-02T21:00:00Z")
    row["family_source_support"]["LW"]["nested"]={bad:"FORBIDDEN"}
    with pytest.raises(ValueError,match="OUTCOME_TRIGGER"):
        adapter.fixed_policy_risk_refresh_nodes([row])


@pytest.mark.parametrize("bad",["2026-01-01T21:00:00Z","2027-01-01T21:00:00Z"])
def test_fixed_policy_no_2026_or_2027_refresh(bad):
    with pytest.raises(ValueError,match="PRE2026"):
        adapter.fixed_policy_risk_refresh_nodes([fixed_policy_row(bad)])


def test_fixed_policy_full_axis_uid_change_refreshes_no_elimination():
    a=fixed_policy_row("2024-01-02T21:00:00Z")
    b=fixed_policy_row("2024-01-03T21:00:00Z")
    b["asset_uids"]["A000"]="SID_NEW_IDENTITY"
    b["asset_epochs"]["A000"]="E1"
    plan=adapter.fixed_policy_risk_refresh_nodes([a,b])
    assert len(plan["nodes"])==36
    assert all(len(x["ordered_assets"])==6 for x in plan["nodes"])


def test_fixed_policy_swap_can_enter_outside_old_raw40_and_quality_bound():
    state=fixed_policy_state()
    variance=np.full(80,100.)
    variance[:20]=1.
    variance[50]=.0001
    state["covariance"]=np.diag(variance)
    result=adapter.fixed_policy_bounded_swap(np.arange(80,0,-1),
        tuple(state["asset_uids"].values()),state)
    assert "A050" in result["members"]
    assert len(result["members"])==20 and len(set(result["members"]))==20
    assert 0<len(result["accepted_swaps"])<=20
    assert result["selected_ordinal_mean"]>=result["ordinal_quality_floor"]
    before=adapter.fixed_policy_risk_objective(state,result["anchor_members"])
    assert result["objective"]<before and not result["global_optimal_claim"]


def test_fixed_policy_swap_uid_tie_and_axis_permutation_invariance():
    state=fixed_policy_state()
    scores=np.ones(80)
    state["covariance"]=np.diag(np.linspace(1.,2.,80))
    a=adapter.fixed_policy_bounded_swap(scores,tuple(state["asset_uids"].values()),state)
    permutation=np.arange(79,-1,-1)
    changed={**state,"assets":tuple(state["assets"][i] for i in permutation),
        "covariance":state["covariance"][np.ix_(permutation,permutation)]}
    b=adapter.fixed_policy_bounded_swap(scores,
        tuple(changed["asset_uids"][x] for x in changed["assets"]),changed)
    assert a["members"]==b["members"] and a["anchor_members"]==b["anchor_members"]


@pytest.mark.parametrize("field,value",[("count",10),("max_swaps",21),("quality_floor",.97)])
def test_fixed_policy_no_relaxed_swap_contract(field,value):
    state=fixed_policy_state()
    with pytest.raises(ValueError,match="FROZEN_FULL_U"):
        adapter.fixed_policy_bounded_swap(np.arange(80),tuple(state["asset_uids"].values()),
            state,**{field:value})


def test_fixed_policy_true_psd_replica_statistic_not_scalar_sigma():
    state=fixed_policy_state("UNCERTAINTY_JACKKNIFE")
    state["psd_replicas"]=[np.eye(80)*x for x in (1.,2.,3.,4.)]
    members=state["assets"][:20]
    sigma=np.sqrt(np.array([1.,2.,3.,4.])/20.)
    expected=np.sqrt(.75*((sigma-sigma.mean())**2).sum())
    assert adapter.fixed_policy_risk_objective(state,members)==pytest.approx(expected)
    state["psd_replicas"]=np.ones((4,80))
    with pytest.raises(ValueError):
        adapter.fixed_policy_risk_objective(state,members)


def test_fixed_policy_native_scenario_axis_and_source_failure_not_gate_rejection():
    state=fixed_policy_state("TAIL_CVAR")
    state["scenario_assets"]=state["assets"]
    state["scenario_returns"]=np.full((30,80),.001)
    result=adapter.fixed_policy_whole_set_gate("H5_CVAR",state["assets"][:20],
        state["assets"][20:40],state)
    assert result["passed"] and result["members"]==state["assets"][:20]
    state["scenario_returns"]=np.full((30,79),.001)
    with pytest.raises(ValueError,match="NATIVE_H5_FULL_U"):
        adapter.fixed_policy_whole_set_gate("H5_CVAR",state["assets"][:20],
            state["assets"][20:40],state)


def test_fixed_policy_base34_exact_two_risk_columns_equal_full_u():
    state=fixed_policy_state()
    state["covariance"]=np.diag(np.arange(1.,81.))
    features=adapter.fixed_policy_single_stock_risk_features(state)
    assert tuple(features.columns)==adapter.FIXED_POLICY_RISK_COLUMNS
    assert tuple(features.index)==state["assets"] and features.shape==(80,2)
    np.testing.assert_allclose(features.iloc[:,0],np.arange(1.,81.))
    np.testing.assert_allclose(features.iloc[:,1],np.arange(1.,81.)/80.)


@pytest.mark.parametrize("kind,family",[("LW_VARIANCE","LW"),("PSD_UNCERTAINTY","UNCERTAINTY_JACKKNIFE")])
def test_fixed_policy_gate_pass_hgb_fail_raw_no_rematch(kind,family):
    state=fixed_policy_state(family)
    state["covariance"]=np.diag(np.r_[np.ones(20),np.ones(60)*2])
    if family=="UNCERTAINTY_JACKKNIFE":
        state["psd_replicas"]=[state["covariance"]*x for x in (1.,2.,3.,4.)]
    hgb,raw=state["assets"][:20],state["assets"][20:40]
    result=adapter.fixed_policy_whole_set_gate(kind,hgb,raw,state)
    assert result["passed"] and result["members"]==hgb
    reverse=adapter.fixed_policy_whole_set_gate(kind,raw,hgb,state)
    assert not reverse["passed"] and reverse["members"]==hgb


@pytest.mark.parametrize("mutation",["uid","epoch","recipe","clock","digest","source"])
def test_fixed_policy_exact_complete_reuse_rejects_changed_bindings(mutation):
    state=fixed_policy_state()
    current={k:state[k] for k in ("assets","asset_uids","asset_epochs",
        "security_coordinate","source_support_identity")}
    current.update(source_qualified=True,maturity_qualified=True)
    from copy import deepcopy
    current=deepcopy(current)
    kw=dict(decision_at="2025-01-03T21:00:00Z",current_identity_proof=current,
        source_cache_identity=state["source_cache_identity"],
        expected_state_digest=adapter.content_hash(state),expected_recipe_sha256=state["recipe_sha256"])
    ok=adapter.validate_fixed_policy_exact_reuse(state,**kw)
    assert ok["learned_units"]==0 and ok["numeric_reestimation"]==0
    if mutation=="uid":current["asset_uids"]["A000"]="SID_NEW"
    elif mutation=="epoch":current["asset_epochs"]["A000"]="E_NEW"
    elif mutation=="recipe":kw["expected_recipe_sha256"]="f"*64
    elif mutation=="clock":kw["decision_at"]="2026-01-01T21:00:00Z"
    elif mutation=="digest":kw["expected_state_digest"]="f"*64
    elif mutation=="source":kw["source_cache_identity"]={"id":"NEW"}
    with pytest.raises(ValueError):
        adapter.validate_fixed_policy_exact_reuse(state,**kw)


def test_fixed_policy_no_current_uid_axis_shrink_in_consumer():
    state=fixed_policy_state()
    with pytest.raises(ValueError,match="FROZEN_FULL_U"):
        adapter.fixed_policy_bounded_swap(np.ones(80),("SID_WRONG",)*80,state)
    state["as_of"]="2026-01-01T21:00:00Z"
    with pytest.raises(ValueError,match="PRE2026"):
        adapter.fixed_policy_single_stock_risk_features(state)


def fixed_policy_generated_refresh():
    inputs,at=generated(assets=6,horizons=(5,))
    names=tuple(sorted(inputs.assets))
    rng=np.random.default_rng(20260928)
    end=inputs.sessions.get_loc(at)-23
    rows=[]
    for i in range(end-299,end+1):
        for a in names:
            rows.append(dict(asset=a,origin_at=inputs.sessions[i],
                entry_at=inputs.sessions[i+1]-pd.Timedelta(hours=6),
                endpoint_at=inputs.sessions[i+6]-pd.Timedelta(hours=6),
                matured_at=inputs.sessions[i+6]-pd.Timedelta(hours=5),
                available_at=inputs.sessions[i+6]-pd.Timedelta(hours=4),
                horizon=5,uid=inputs.asset_uids[a],identity_epoch=inputs.identity_epoch,
                source_identity=inputs.source_receipt.source_identity,
                return_value=rng.normal(0,.01)))
    inputs=replace(inputs,assets=names,observations=pd.DataFrame(rows))
    proof=dict(assets=list(names),asset_uids=dict(inputs.asset_uids),
        asset_epochs={a:inputs.identity_epoch for a in names},source_qualified=True,
        maturity_qualified=True,security_coordinate="SYNTHETIC_CURRENT_SHARE",
        source_support_identity={"stock_source":inputs.source_receipt.source_sha256})
    auth=dict(research_id=adapter.FIXED_POLICY_RESEARCH_ID,frozen=True,
        recipe_sha256=adapter.content_hash(adapter.fixed_policy_risk_specification()))
    return inputs,at,proof,auth


def test_fixed_policy_core_owner_actual_five_learned_units_full_u():
    inputs,at,proof,auth=fixed_policy_generated_refresh()
    events=[]
    result=adapter.estimate_fixed_policy_risk_refresh(inputs,as_of=at,
        support_metadata=support(inputs),current_identity_proof=proof,
        authorization=auth,families=("DIAG","LW","OAS","EWMA"),
        reserve_callback=lambda e:{"ack":True,"reserved_units":71,"reservation_id":"SYNTHETIC_REFRESH"},
        on_component_start=lambda e:(events.append(e) or {"ack":True}))
    assert result["weighted_learned_units"]==5 and len(events)==5
    assert result["logical_cache_learned_units"]==5 and result["scientific_retry"]==0
    assert all(s["status"]=="ESTIMATED" for s in result["states"].values())
    assert all(s["assets"]==inputs.assets and s["covariance"].shape==(6,6)
        for s in result["states"].values())


def test_fixed_policy_core_original_prior_completion_preserves_full_u():
    inputs,at,proof,auth=fixed_policy_generated_refresh()
    remove=inputs.observations.asset.eq(inputs.assets[-1])
    rows=inputs.observations.loc[~remove].copy()
    rows=pd.concat([rows,inputs.observations.loc[remove].tail(2)],ignore_index=True)
    inputs=replace(inputs,observations=rows)
    result=adapter.estimate_fixed_policy_risk_refresh(inputs,as_of=at,
        support_metadata=support(inputs),current_identity_proof=proof,
        authorization=auth,families=("DIAG",),
        reserve_callback=lambda e:{"ack":True,"reserved_units":71,"reservation_id":"SYNTHETIC_REFRESH"})
    state=result["states"]["DIAG"]
    assert state["status"]=="ESTIMATED" and state["assets"]==inputs.assets
    assert state["completion"]["unknown_assets"]==[inputs.assets[-1]]
    assert not state["completion"]["strategy_eligibility_upgraded"]
    assert state["covariance"].shape==(6,6)


def test_fixed_policy_ack_precedes_poisoned_numeric():
    inputs,at,proof,auth=fixed_policy_generated_refresh()
    poison=inputs.observations.copy()
    poison["return_value"]="NOT_NUMERIC"
    inputs=replace(inputs,observations=poison)
    with pytest.raises(ValueError,match="DURABLE_REFRESH_ACK"):
        adapter.estimate_fixed_policy_risk_refresh(inputs,as_of=at,
            support_metadata=support(inputs),current_identity_proof=proof,
            authorization=auth,families=("DIAG",),reserve_callback=lambda e:{"ack":False})
