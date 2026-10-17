"""Synthetic reader/transport checks only; no provider or real data import."""
from dataclasses import replace
import copy
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.evaluation import joint_event_risk_execution_r5 as e
from scripts.research.a2.evaluation import joint_frozen_history_risk_r3 as old
from scripts.research.a2.data.shared_risk_inputs_r3 import _clock, STORED_LABEL_COORDINATE
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash


def fixture():
    days=pd.bdate_range("2022-01-03",periods=340)
    assets=tuple("ABCDEZ")
    day,prior=days[-1],days[-2]
    uids={a:a+"_UID" for a in assets}
    starts={a:days[0].date().isoformat() for a in assets}
    starts["Z"]=day.date().isoformat()
    epochs={a:"OBSERVED_CONTIGUOUS_UID:"+content_hash(dict(asset=a,uid=uids[a],start=starts[a])) for a in assets}
    sig=dict(ordered_assets=list(assets),asset_uids=uids,asset_epochs=epochs)
    event=dict(decision_date=day.date().isoformat(),decision_asof=_clock(day).isoformat(),
        fit_history_cutoff=_clock(prior).isoformat(),current_identity_available_at=_clock(day).isoformat(),
        requested_assets=list(assets),asset_uids=uids,asset_epochs=epochs,segment_starts=starts,
        complete_structural_signature=sig,structural_signature_sha256=content_hash(sig),
        dependency_local_event_ids={n:n+"event" for n in ("PRIMARY","QQQ","FF48")},
        dependency_local_signature_sha256={n:"b"*64 for n in ("PRIMARY","QQQ","FF48")},
        history_support=dict(current_identity_blockers={},source_metadata_blockers={},parent_origin_count=252,
            qqq_h5_endpoint_key_support=True,parent_origins=[d.date().isoformat() for d in days[80:332]],
            nominal_n={a:252 if a!="Z" else 0 for a in assets}))
    features=pd.DataFrame([dict(ticker=a,signal_date=d,security_id=uids[a] if a!="Z" or d==day else "Z_OLD_UID",
        feature_available=True,all_features_finite=True,feature_source=old.FEATURE_TAGS[0]) for d in days for a in assets])
    labels=pd.DataFrame([dict(ticker=a,signal_date=days[i],execution_date=days[i+1],label_end_date=days[i+6],
        label_mature_date=days[i+6],label_coordinate=STORED_LABEL_COORDINATE,label_available=True,
        label_unsupported_common_event=False,endpoint_pair_available=True) for i in range(332) for a in assets])
    base=labels.loc[:,["ticker","signal_date"]].copy()
    base["security_id"]=[uids[a] if a!="Z" else "Z_OLD_UID" for a in base.ticker]
    raw=pd.DataFrame([dict(ticker=a,trade_date=day,code="US."+a) for a in assets])
    qqq=pd.DataFrame(dict(ticker="QQQ",trade_date=days[:-1]))
    source=dict(research_id="SYNTHETIC_EXACT_BYTES",family_design_freeze_sha256="a"*64,
        sources={"extended_shareholder_y5":{"sha256":"a"*64},"qqq_qfq_years":[{"year":2022,"sha256":"c"*64}]})
    science=dict(scientific_contract_identity="R5_SYNTHETIC_TRANSPORT",scientific_contract_sha256="d"*64,
        actual_snapshot_timestamp="2026-10-04T00:00:00+00:00")
    return dict(labels=labels,base_uids=base,features=features,raw=raw,qqq=qqq,
        source=source,science=science,days=days,event=event,dependency="PRIMARY",source_pins={"primary":"a"*64})


def test_current_known_cold_identity_is_not_prior_uid_and_gets_no_observation():
    args=fixture()
    ctx=e.assemble_event_context(**args)
    assert ctx.inputs.assets==tuple("ABCDEZ")
    assert ctx.inputs.asset_uids["Z"]=="Z_UID"
    assert not ctx.inputs.observations.asset.eq("Z").any()
    assert ctx.original_support_declarations["inference_support"]["Z"] is False
    assert ctx.current_identity_proof["source_qualified"] is True
    assert ctx.current_identity_proof["observations_created"]==0
    assert ctx.inputs.observations.return_value.isna().all()
    assert ctx.inputs.qqq_observations.return_value.isna().all()


def test_history_clocks_are_strictly_prior_and_full_domain_retained():
    args=fixture();ctx=e.assemble_event_context(**args)
    cutoff=pd.Timestamp(args["event"]["fit_history_cutoff"])
    for c in ("origin_at","entry_at","endpoint_at","matured_at","available_at"):
        assert ctx.inputs.observations[c].lt(cutoff).all()
    assert set(ctx.inputs.assets)==set(ctx.current_identity_proof["asset_epochs"])
    assert ctx.inputs.identity_epoch.endswith(content_hash(args["event"]["asset_epochs"]))
    assert ctx.current_identity_proof["current_identity_asof"]!=ctx.current_identity_proof["history_cutoff"]


def test_current_new_asset_is_not_removed_by_frozen_domain():
    args=fixture();new=args["features"].iloc[-1].copy();new["ticker"]="NEW";new["security_id"]="NEW_UID"
    args["features"]=pd.concat([args["features"],pd.DataFrame([new])],ignore_index=True)
    raw=args["raw"].iloc[-1].copy();raw["ticker"]="NEW"
    args["raw"]=pd.concat([args["raw"],pd.DataFrame([raw])],ignore_index=True)
    with pytest.raises(ValueError,match="CURRENT_REQUESTED_POOL_CHANGED"):
        e.assemble_event_context(**args)


@pytest.mark.parametrize("kind",["duplicate","unknown","future"])
def test_identity_failures_are_preserved(kind):
    args=fixture()
    if kind=="duplicate": args["features"]=pd.concat([args["features"],args["features"].iloc[-1:]],ignore_index=True)
    if kind=="unknown": args["features"].loc[args["features"].index[-1],"security_id"]=None
    if kind=="future": args["features"].loc[args["features"].index[-1],"signal_date"]+=pd.Timedelta(days=3)
    with pytest.raises(ValueError): e.assemble_event_context(**args)


def test_numeric_field_rejected_before_metadata_value_access():
    args=fixture();args["labels"]["y_open5"]=object()
    with pytest.raises(ValueError,match="NUMERIC_FIELD_FORBIDDEN"):
        e.assemble_event_context(**args)


def test_unsupported_rows_remain_nan_and_support_change_is_blocked():
    args=fixture();args["labels"].loc[(args["labels"].ticker=="A") & (args["labels"].signal_date==args["days"][300]),"label_available"]=False
    with pytest.raises(ValueError,match="SUPPORT_COUNTS_OR_ORIGINS_CHANGED"):
        e.assemble_event_context(**args)
    args["event"]["history_support"]["nominal_n"]["A"]-=1
    ctx=e.assemble_event_context(**args)
    assert not ctx.support_metadata.loc[(ctx.support_metadata.asset=="A") & (ctx.support_metadata.origin_at==_clock(args["days"][300])),"qualified"].item()
    assert ctx.inputs.observations.return_value.isna().all()


def test_qqq_or_ff_local_support_does_not_use_future_event_clock():
    args=fixture();event=args["event"]
    a=e.source_support_identity(event,"PRIMARY",{"x":"a"*64})
    b=e.source_support_identity(event,"FF48",{"x":"a"*64})
    assert a!=b
    assert not any("next" in k for k in a)
    with pytest.raises(ValueError): e.source_support_identity(event,"NAV",{})


def test_loader_rejects_numeric_before_any_read():
    loader=object.__new__(e.EventInputLoader);loader.numeric_authorised=False
    with pytest.raises(ValueError,match="PRE_NUMERIC_ACTIVATION_REQUIRED"):
        loader.load({},numeric=True)


def test_same_uid_reopen_uses_new_epoch_without_cross_segment_history():
    args=fixture();a="A";start=args["days"][330]
    args["event"]["segment_starts"][a]=start.date().isoformat()
    args["event"]["asset_epochs"][a]="REOPEN_EPOCH"
    args["event"]["complete_structural_signature"]["asset_epochs"][a]="REOPEN_EPOCH"
    args["event"]["structural_signature_sha256"]=content_hash(args["event"]["complete_structural_signature"])
    args["event"]["history_support"]["nominal_n"][a]=2
    ctx=e.assemble_event_context(**args)
    assert ctx.inputs.observations.loc[ctx.inputs.observations.asset.eq(a),"origin_at"].min()==_clock(start)
    assert ctx.current_identity_proof["asset_epochs"][a]=="REOPEN_EPOCH"


def test_whole_freeze_guard_runs_before_loader_or_value_projection(monkeypatch):
    calls=[]
    def blocked(*args,**kwargs):
        calls.append(kwargs)
        raise ValueError("EXACT_WHOLE_FREEZE_REJECTED")
    monkeypatch.setattr(e.runtime,"guard",blocked)
    monkeypatch.setattr(e.old,"read_json",lambda *a:pytest.fail("READ_BEFORE_GUARD"))
    with pytest.raises(ValueError,match="EXACT_WHOLE_FREEZE_REJECTED"):
        e.fit("unused",expected_freeze_sha=None)
    assert calls==[{"numeric":True,"expected_freeze_sha256":None}]


def test_existing_durable_ledger_keeps_failed_debits_and_deterministic_zero_cost(monkeypatch,tmp_path):
    monkeypatch.setattr(e.runtime,"guard",lambda run,**kw:tmp_path)
    writes=[]
    monkeypatch.setattr(e.old,"read_json",lambda *a:{"maximum_new_fit_units":1069})
    monkeypatch.setattr(e.old,"write",lambda run,name,value,**kw:writes.append(copy.deepcopy(value)))
    ledger=e.runtime.R5FitLedger(tmp_path,expected_freeze_sha256="a"*64)
    def item(key,kind): return dict(key=key,kind=kind,name=key,status="RESERVED",parameters={},context={})
    ledger.reserve(item("param","covariance"))
    ledger.sync([{**item("param","covariance"),"status":"FAILED"}])
    assert ledger.status["new_fit_units"]==1 and ledger.status["fit_attempts"]==3028
    assert ledger.status["physical_events"][0]["status"]=="FIT_FAILURE"
    with pytest.raises(ValueError,match="NO_AUTOMATIC_RETRY"): ledger.reserve(item("param","covariance"))
    ledger.reserve(item("fixed_input","deterministic_transform"))
    assert ledger.status["new_fit_units"]==1
    assert len(ledger.status["physical_events"])==2 and writes


def test_durable_cumulative_cap_does_not_reset_on_new_event(monkeypatch,tmp_path):
    monkeypatch.setattr(e.runtime,"guard",lambda run,**kw:tmp_path)
    monkeypatch.setattr(e.old,"write",lambda *a,**kw:None)
    monkeypatch.setattr(e.old,"read_json",lambda *a:{"maximum_new_fit_units":1069})
    ledger=e.runtime.R5FitLedger(tmp_path,expected_freeze_sha256="a"*64)
    ledger.status.update(new_fit_units=1069,risk_fit_units=1069,fit_attempts=4096)
    with pytest.raises(ValueError,match="CAP_EXCEEDED"):
        ledger.reserve(dict(key="new_event",kind="covariance",name="x",parameters={},context={}))
    assert ledger.status["fit_attempts"]==4096


def test_policy_binding_is_exact_seven_fields_and_per_asset_epoch(monkeypatch):
    from types import SimpleNamespace
    args=fixture();ctx=e.assemble_event_context(**args)
    current=ctx.current_identity_proof
    identity=e.structural_identity(assets=tuple(current["assets"]),uids=current["asset_uids"],
        epochs=current["asset_epochs"],security_coordinate=current["security_coordinate"],
        source_support_identity=current["source_support_identity"])
    binding=dict(parent_risk="SHR_HP",family="SHR_HP",method="R5::SHR_HP::KNOWN_UID_PRIOR_PREDICTIVE_N0",
        representation="EVENT_HIERARCHICAL_PRIOR",recipe_sha256="a"*64,producer_sha256="b"*64,availability="READY")
    lineage=dict(family="SHR_HP",recipe_sha256="a"*64,structural_identity=identity,
        source_support_identity_sha256=content_hash(current["source_support_identity"]),
        asset_uid_epoch_sha256=content_hash(dict(uids=current["asset_uids"],epochs=current["asset_epochs"])))
    state=SimpleNamespace(method=binding["method"],covariance=np.eye(6),status="PASS_SYNTHETIC",
        coverage={a:dict(uid=current["asset_uids"][a],identity_epoch=current["asset_epochs"][a]) for a in current["assets"]},
        notes={"estimator_lineage":lineage})
    monkeypatch.setattr(e,"replace",lambda value,**kw:SimpleNamespace(**{**vars(value),**kw}))
    bound=e.bind_policy_state(state,binding,current)
    assert set(bound.notes["event_policy_binding"])=={"parent_risk","representation","recipe_sha256","model_producer_sha256",
        "structural_identity","source_support_identity_sha256","asset_uid_epoch_sha256"}
    state.coverage["Z"]["identity_epoch"]="WRONG_PRIOR_EPOCH"
    with pytest.raises(ValueError,match="STATE_CURRENT_UID_EPOCH_REQUIRED"):
        e.bind_policy_state(state,binding,current)


def test_ff_source_absence_blocks_only_that_family_qualification():
    ctx=e.assemble_event_context(**fixture())
    source=e.family_source_qualification(ctx,["SHR_HP","FF48_HIERARCHICAL"])
    assert source["FF48_HIERARCHICAL"]["status"]=="BLOCKED_FAMILY_SOURCE_METADATA"
    assert set(source["FF48_HIERARCHICAL"]["native_cohort"])==set("ABCDE")
    assert ctx.current_identity_proof["source_qualified"] is True
    assert ctx.inputs.assets==tuple("ABCDEZ")


def test_family_local_identity_is_bound_without_replacing_shared_primary_context():
    ctx=e.assemble_event_context(**fixture())
    shared=copy.deepcopy(ctx.current_identity_proof)
    ff=dict(dependency="FF48",dependency_local_event_id="specific_ff",source_pins={"ff":"c"*64})
    current={**shared,"family_source_support_identity":{"FF48_HIERARCHICAL":ff}}
    assert e.effective_family_current(current,"FF48_HIERARCHICAL")["source_support_identity"]==ff
    assert e.effective_family_current(current,"SHR_HP")["source_support_identity"]==shared["source_support_identity"]
    assert current["source_support_identity"]==shared["source_support_identity"]


def test_current_raw_key_cannot_use_next_session_presence():
    args=fixture();args["raw"]["trade_date"]+=pd.Timedelta(days=3)
    with pytest.raises(ValueError,match="CURRENT_RAW_KEY_DATE_REQUIRED"):
        e.assemble_event_context(**args)


def test_fast_metadata_transports_all_frames_and_qualified_proof_exactly():
    from pandas.testing import assert_frame_equal
    from scripts.research.a2.risk.joint_event_risk_estimators_r5 import EventRiskEstimator
    args=fixture();slow=e.assemble_event_context(**args,fast_metadata=False)
    fast=e.assemble_event_context(**args,fast_metadata=True)
    for name in ("observations","qqq_observations"):
        assert_frame_equal(getattr(slow.inputs,name),getattr(fast.inputs,name))
    assert_frame_equal(slow.support_metadata,fast.support_metadata)
    assert_frame_equal(slow.pool["history"],fast.pool["history"])
    assert slow.original_support_declarations==fast.original_support_declarations
    assert slow.current_identity_proof==fast.current_identity_proof
    estimator=EventRiskEstimator()
    kwargs=dict(as_of=pd.Timestamp(args["event"]["decision_asof"]))
    a=estimator.qualify(slow.inputs,support_metadata=slow.support_metadata,
        current_identity_proof=slow.current_identity_proof,**kwargs)
    b=estimator.qualify(fast.inputs,support_metadata=fast.support_metadata,
        current_identity_proof=fast.current_identity_proof,**kwargs)
    assert a==b


def test_fast_row_scalar_semantics_nullable_strings_booleans_and_timezone():
    frame=pd.DataFrame(dict(ticker=pd.Series(["A",pd.NA],dtype="string"),
        label_available=pd.Series([True,pd.NA],dtype="boolean"),
        available_at=pd.to_datetime(["2023-01-03T21:00:00Z",None]),
        label_end_date=pd.to_datetime(["2023-01-03",None])))
    fast=list(e._MetadataFrame(frame).iterrows());slow=list(frame.iterrows())
    for (i,a),(j,b) in zip(fast,slow):
        assert i==j
        for c in frame.columns:
            av,bv=a[c],b[c]
            if pd.isna(bv): assert pd.isna(av)
            else: assert av==bv and getattr(a,c)==getattr(b,c)
        with pytest.raises(AttributeError): getattr(a,"unavailable_column")
    assert isinstance(fast[0][1]["available_at"],pd.Timestamp)


@pytest.mark.parametrize("collision",["name","index","dtype","iloc","_values"])
def test_fast_metadata_uses_original_series_when_column_name_conflicts(collision):
    frame=pd.DataFrame({collision:["column value"],"ticker":["A"]},index=[42])
    _,row=next(e._MetadataFrame(frame).iterrows())
    assert isinstance(row,pd.Series)
    assert row[collision]=="column value"
    assert row.name==42


def test_nullable_missing_clock_failures_are_identical_in_both_paths():
    args=fixture()
    args["labels"]["label_available"]=args["labels"].label_available.astype("boolean")
    args["labels"].loc[0,"label_available"]=pd.NA
    errors=[]
    for fast in (False,True):
        with pytest.raises((ValueError,TypeError)) as error:
            e.assemble_event_context(**args,fast_metadata=fast)
        errors.append((type(error.value),str(error.value)))
    assert errors[0]==errors[1]


def test_numerical_packaging_never_uses_metadata_subclass(monkeypatch):
    args=fixture();args["labels"]["y_open5"]=0.01;args["qqq"]["open"]=100.0
    captured=[];original=e.assemble_risk_inputs
    def observe(labels,*a,**kw):
        captured.append(type(labels));return original(labels,*a,**kw)
    monkeypatch.setattr(e,"assemble_risk_inputs",observe)
    e.assemble_event_context(**args,numeric=True)
    assert captured==[pd.DataFrame]
