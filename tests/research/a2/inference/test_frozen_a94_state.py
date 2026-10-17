"""Pure synthetic forward-state equivalence and boundary checks; no source reads.
Only original source bytes are hashed. No models, prices, labels or2026 results.
"""
from copy import deepcopy
import hashlib
import json
import re
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.inference import frozen_a94_state as state


def _history():
    dates=pd.DatetimeIndex([pd.Timestamp("2023-01-03"),*pd.bdate_range("2025-12-24",periods=9)])
    rows=[]
    for j,d in enumerate(dates):
        for n,t in enumerate(("A","B","C","D")):
            rows.append(dict(signal_date=d,ticker=t,security_id="SID_"+t,
                feature_available=True,is_raw_top20=True,raw_top20_set_complete=False,
                new_buy_eligible=j>0 and (t!="B" or j==len(dates)-1),
                raw_a2_rank=n+1,raw_a2_prediction=.1-j*.001,
                **{c:(k+1)*.001+j*.0001 for k,c in enumerate(state.original_inputs.FEATURES)}))
    return dates,pd.DataFrame(rows)


def _labels(pred,cal,native=False):
    rows=[]
    for j in (1,2):
        for row in pred.loc[pred.signal_date.eq(cal[j])].to_dict("records"):
            r={k:row[k] for k in state._KEYS}
            r.update(label_mature_date=cal[j+6],observation_available_at=cal[j+6].tz_localize("America/New_York")+pd.Timedelta(hours=16))
            if native:r.update(label_qualified=True,label_value=.05,source_label_identity=state._H5_SOURCE,label_coordinate=state._H5_COORDINATE,horizon_sessions=5)
            else:r.update(feature_available=True,label_available=True,account_event_unhandled=False,
                label_unsupported_common_event=False,label_coordinate=state.original_inputs.LABEL,y_open5=.05)
            rows.append(r)
    return pd.DataFrame(rows)


@pytest.fixture
def fixture(tmp_path):
    cal,pred=_history();file=tmp_path/"synthetic_action_source.json";file.write_text('{"synthetic":true}',encoding="utf-8")
    ref=dict(path=str(file),sha256=hashlib.sha256(file.read_bytes()).hexdigest())
    a=state.admission.ValidatedDescriptiveAuthority(state.profile.TASK,"SYNTHETIC",pd.Timestamp("2026-01-01"),
        pd.Timestamp("2026-01-31"),pd.Timestamp("2026-10-07T18:42:01.905856Z"),pd.Timestamp("2023-01-01"),
        ("SYNTHETIC94",),json.dumps(dict(source_refs=dict(action_inputs=ref))),state.admission._SEAL,("SYNTHETIC94",))
    return SimpleNamespace(auth=a,cal=cal,pred=pred,day=cal[-1],asof=cal[-1].tz_localize("America/New_York")+pd.Timedelta(hours=16),
        r6=_labels(pred,cal),h5=_labels(pred,cal,True),ref=ref)


def run(f,**changes):
    args=dict(authority=f.auth,prediction_prefix=f.pred,calendar_prefix=f.cal,decision_date=f.day,
        decision_as_of=f.asof,r6_probe_rows=f.r6,native_h5_probe_rows=f.h5,action_source_ref=f.ref)
    args.update(changes)
    return state.build_current_state(**args)


def test_original_full_cohort_all_pairs_and_cross_year_probe_phase(fixture):
    result=run(fixture);r=result.role_frames
    assert set(r)=={"R6:buy","R6:hold","R6:replace","R6:distribution","R6:duration","R6:distribution_pair",
        "R10:ENTRY","R10:INCUMBENT","R10:HAZARD","R10:JOINT_SEQUENCE"}
    assert len(r["R6:replace"])==2 and result.audit["pair_count"]==3
    replace=r["R10:INCUMBENT"].loc[lambda x:x.action_type.eq(1)]
    assert replace.incumbent.tolist()==["A","C","D"]
    assert replace.pair_count_before_labels.eq(3).all()
    np.testing.assert_array_equal(replace.pre_label_group_weight,1/np.full(3,3))
    assert r["R6:duration"].probe_age.eq(7).all() and len(r["R6:duration"])==3
    assert r["R10:HAZARD"].probe_age.eq(7).all() and len(r["R10:HAZARD"])==3
    assert r["R6:hold"].cohort_age_sessions.eq(7).all()
    assert fixture.r6.signal_date.max()<pd.Timestamp("2026-01-01")  # Mature2025 state carries into2026.
    assert result.joint_sequence.shape==(9,5,len(result.sequence_features))
    assert result.sequence_supported.shape==(9,)
    assert all(not set(frame).intersection(state._OUTCOMES) for frame in r.values())
    assert result.audit["source_certified"] is False and "READY" not in result.audit.values()


def _translate(frame,mapper):
    result=frame.copy()
    pattern=re.compile(r"\d{4}-\d{2}-\d{2}")
    strings={str(k.date()):str(v.date()) for k,v in mapper.items()}
    for col in result:
        if pd.api.types.is_datetime64_any_dtype(result[col]):result[col]=result[col].map(lambda x:mapper.get(pd.Timestamp(x),x))
        elif pd.api.types.is_string_dtype(result[col].dtype) or result[col].dtype==object:
            result[col]=result[col].map(lambda x:pattern.sub(lambda m:strings.get(m[0],m[0]),x) if isinstance(x,str) else x)
            result[col]=result[col].astype(object).where(result[col].notna(),None)
    return result


def test_pre2026_original_kernel_equivalence_without_changing_old_guards(fixture):
    result=run(fixture)
    mapper={d:(d-pd.DateOffset(years=1) if d.year>=2025 else d) for d in fixture.cal}
    cal=pd.DatetimeIndex([mapper[d] for d in fixture.cal]);day=mapper[fixture.day]
    pred=_translate(fixture.pred,mapper);r6=_translate(fixture.r6,mapper);h5=_translate(fixture.h5,mapper)
    samples,_=state.decision.build_samples(pred,r6[list(state.decision.LABEL_COLS)],cal)
    for name in state.decision.OBJECTIVES:
        actual=_translate(result.role_frames["R6:"+name],mapper)
        expected=samples[name].loc[lambda x:x.signal_date.eq(day)].reset_index(drop=True)
        columns=[c for c in actual if c in expected]
        pd.testing.assert_frame_equal(actual[columns],expected[columns],check_dtype=False)
    proxy=state.mechanism_inputs.proxy_state(pred,cal,10)
    keycols=[*state._KEYS,"sample_id","cohort_age_sessions","raw_rank"]
    key={k:samples[k].loc[lambda x:x.signal_date.eq(day),keycols] for k in ("buy","hold")}
    pairs=state.foundation.all_incumbent_pairs(key)
    head={name:state.mechanism_inputs.attach_single_labels(proxy,h5,name) for name in ("ENTRY","INCUMBENT","CONTINUATION")}
    head["REPLACE"]=state.mechanism_inputs.attach_pair_labels(pairs,proxy,h5)
    structured=state.mechanism.structured_action_frame(SimpleNamespace(heads={5:head}),5)
    for name in ("ENTRY","INCUMBENT"):
        actual=_translate(result.role_frames["R10:"+name],mapper)
        expected=_translate(structured[name].loc[lambda x:x.signal_date.eq(day)].reset_index(drop=True),{})
        columns=[c for c in actual if c!="required_actionset_sha256"]
        pd.testing.assert_frame_equal(actual[columns],expected[columns],check_dtype=False)
    hazard=state.mechanism_inputs.hazard_probes(head["CONTINUATION"],cal,ages=(0,7,14),stride=7)
    expected=hazard.loc[lambda x:x.signal_date.eq(day)].reset_index(drop=True)
    actual=_translate(result.role_frames["R10:HAZARD"],mapper)
    common=[c for c in actual if c in expected]
    pd.testing.assert_frame_equal(actual[common],expected[common],check_dtype=False)
    continuation=structured["CONTINUATION"].copy()
    for c in state.mechanism.SINGLE:
        continuation["i_"+c],continuation["e_"+c],continuation["delta_"+c]=continuation[c],0.,0.
    continuation["action_type"]=-1.
    frame=pd.concat([structured["INCUMBENT"],continuation],ignore_index=True,sort=False).loc[lambda x:x.signal_date.eq(day)].reset_index(drop=True)
    bundle=SimpleNamespace(prediction_history=pred,frames=SimpleNamespace(state=proxy),reader=SimpleNamespace(calendar=cal))
    tensor,supported,features=state.mechanism.sequence_dataset(bundle,frame,5)
    np.testing.assert_array_equal(result.joint_sequence,tensor)
    np.testing.assert_array_equal(result.sequence_supported,supported)
    assert result.sequence_features==features
    assert state.original_inputs.BOUNDARY==state.mechanism_inputs.BOUNDARY==pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError,match="2026_LOCKED"):
        state.decision.build_samples(fixture.pred,pd.DataFrame(columns=state.decision.LABEL_COLS),fixture.cal)
    with pytest.raises(ValueError,match="2026_LOCKED"):
        state.mechanism_inputs.proxy_state(fixture.pred,fixture.cal)


@pytest.mark.parametrize("change",["future_maturity","equal_maturity","future_available","naive_available","sid","r6_coordinate","native_coordinate","ca_unhandled"])
def test_noncausal_or_wrong_source_probe_rejected_before_outcome_access(fixture,monkeypatch,change):
    r6=fixture.r6.copy();native=fixture.h5.copy()
    if change=="future_maturity":r6.loc[0,"label_mature_date"]=fixture.day+pd.Timedelta(days=1)
    elif change=="equal_maturity":r6.loc[0,"label_mature_date"]=fixture.day
    elif change=="future_available":r6.loc[0,"observation_available_at"]=fixture.asof+pd.Timedelta(seconds=1)
    elif change=="naive_available":r6["observation_available_at"]=r6.observation_available_at.dt.tz_localize(None)
    elif change=="sid":r6.loc[0,"security_id"]="WRONG_SID"
    elif change=="r6_coordinate":r6.loc[0,"label_coordinate"]="PRICE_ONLY"
    elif change=="native_coordinate":native.loc[0,"label_coordinate"]="MOOMOO_PRICE_ONLY"
    else:r6.loc[0,"account_event_unhandled"]=True
    class ForbiddenOutcome:
        def __float__(self):raise AssertionError("noncausal outcome converted")
    if change!="native_coordinate":r6["y_open5"]=[ForbiddenOutcome() for _ in range(len(r6))]
    original=pd.DataFrame.__getitem__;calls=[]
    def trap(self,key):
        if self is r6 and isinstance(key,str) and key=="y_open5":calls.append(key)
        return original(self,key)
    monkeypatch.setattr(pd.DataFrame,"__getitem__",trap)
    with pytest.raises(ValueError,match="PROBE|QUALIFIED_LABEL|NATIVE_CA"):
        run(fixture,r6_probe_rows=r6,native_h5_probe_rows=native)
    if change!="native_coordinate":assert calls==[]


@pytest.mark.parametrize("kind",["negative","unknown"])
def test_original_probe_chain_does_not_recover_invalid_previous_state(fixture,kind):
    r6=fixture.r6.copy();h5=fixture.h5.copy()
    age0=fixture.cal[2]
    if kind=="negative":
        r6.loc[r6.signal_date.eq(age0),"y_open5"]=-.05;h5.loc[h5.signal_date.eq(age0),"label_value"]=-.05
    else:
        r6=r6.loc[~r6.signal_date.eq(age0)].copy();h5=h5.loc[~h5.signal_date.eq(age0)].copy()
    result=run(fixture,r6_probe_rows=r6,native_h5_probe_rows=h5)
    assert result.role_frames["R6:duration"].empty and result.role_frames["R10:HAZARD"].empty
    assert len(result.role_frames["R6:hold"])==3


def test_sid_change_restarts_cohort_without_prior_sid_probe_contamination(fixture):
    pred=fixture.pred.copy();pred.loc[pred.ticker.eq("A")&pred.signal_date.ge(fixture.cal[6]),"security_id"]="NEW_A"
    result=run(fixture,prediction_prefix=pred)
    holds=result.role_frames["R6:hold"]
    assert holds.loc[holds.ticker.eq("A"),"cohort_age_sessions"].item()==2
    assert not result.role_frames["R6:duration"].ticker.eq("A").any()
    assert not result.role_frames["R10:HAZARD"].ticker.eq("A").any()
    assert result.sequence_supported.dtype==np.dtype(bool)


@pytest.mark.parametrize("change",["not_scoped","wrong_task","future_pred","reset_calendar","before2026","missing_r6","missing_h5","wrong_source","outcome_feature","source_pin","future_asof"])
def test_scope_clock_source_and_missing_reader_failclosed(fixture,monkeypatch,change):
    from dataclasses import replace
    args={}
    if change=="not_scoped":args["authority"]=replace(fixture.auth,runtime_policy_ids=())
    elif change=="wrong_task":args["authority"]=replace(fixture.auth,task_id="OTHER")
    elif change=="future_pred":
        pred=fixture.pred.copy();pred.loc[0,"signal_date"]=fixture.day+pd.Timedelta(days=1);args["prediction_prefix"]=pred
    elif change=="reset_calendar":args["calendar_prefix"]=fixture.cal[fixture.cal.year==2026]
    elif change=="before2026":args["decision_date"]=pd.Timestamp("2025-12-31")
    elif change=="missing_r6":args["r6_probe_rows"]=None
    elif change=="missing_h5":args["native_h5_probe_rows"]=None
    elif change=="wrong_source":args["action_source_ref"]=dict(fixture.ref,sha256="0"*64)
    elif change=="outcome_feature":
        pred=fixture.pred.copy();pred["target"]=0.;args["prediction_prefix"]=pred
    elif change=="source_pin":monkeypatch.setitem(state._PINS,state.decision.__name__,"0"*64)
    else:args["decision_as_of"]=fixture.auth.as_of+pd.Timedelta(days=1)
    with pytest.raises(ValueError,match="A94|DESCRIPTIVE"):
        run(fixture,**args)


def test_input_frames_are_not_mutated_and_only_current_outputs_retained(fixture):
    before=[x.copy(deep=True) for x in (fixture.pred,fixture.r6,fixture.h5)]
    result=run(fixture)
    for a,b in zip((fixture.pred,fixture.r6,fixture.h5),before):pd.testing.assert_frame_equal(a,b)
    for frame in result.role_frames.values():assert frame.signal_date.eq(fixture.day).all()
    assert all(name not in result.audit for name in ("prediction_prefix","labels","model"))


@pytest.mark.parametrize("offset,expected",[(0,3),(1,0)])
def test_publication_exact_close_boundary_and_late_probe_censor(fixture,offset,expected):
    r6=fixture.r6.copy();h5=fixture.h5.copy()
    probe=fixture.cal[2]
    publication=fixture.asof+pd.Timedelta(seconds=offset)
    # For the late case, current run observes it after close; the historical
    # original consumer close stays16:00, never this later run time.
    for frame in (r6,h5):frame.loc[frame.signal_date.eq(probe),"observation_available_at"]=publication
    result=run(fixture,r6_probe_rows=r6,native_h5_probe_rows=h5,
        decision_as_of=fixture.asof+pd.Timedelta(minutes=5))
    assert len(result.role_frames["R6:duration"])==expected
    assert len(result.role_frames["R10:HAZARD"])==expected
    discard=result.audit["late_publication_metadata_discarded"]
    assert discard==dict(R6=0 if not offset else 3,native_H5=0 if not offset else 3)


@pytest.mark.parametrize("cause",["late_publication","equal_maturity"])
def test_published_today_cannot_restore_missed_age7_riskset_at_age14(fixture,cause):
    # Extend the same original cohort to its age14. The age0 probe was already
    # mature, but was published one second AFTER its age7 consumer close.
    extra=pd.bdate_range(fixture.day+pd.Timedelta(days=1),periods=7)
    cal=fixture.cal.append(extra);pred=fixture.pred.copy()
    additions=[]
    for d in extra:
        for row in fixture.pred.loc[fixture.pred.signal_date.eq(fixture.day)].to_dict("records"):
            row["signal_date"]=d;row["new_buy_eligible"]=True;additions.append(row)
    pred=pd.concat([pred,pd.DataFrame(additions)],ignore_index=True)
    r6=fixture.r6.copy();h5=fixture.h5.copy()
    late=fixture.asof+pd.Timedelta(seconds=1)
    for frame in (r6,h5):
        mask=frame.signal_date.eq(fixture.cal[2])
        frame.loc[mask,"observation_available_at"]=late if cause=="late_publication" else fixture.asof
        if cause=="equal_maturity":frame.loc[mask,"label_mature_date"]=fixture.day
    # A positive age7 outcome is now mature/available; its risk set was missed.
    for native,frame in ((False,r6),(True,h5)):
        rows=[]
        for row in frame.loc[frame.signal_date.eq(fixture.cal[2])].to_dict("records"):
            row["signal_date"]=fixture.day;row["label_mature_date"]=extra[-2]
            row["observation_available_at"]=extra[-2].tz_localize("America/New_York")+pd.Timedelta(hours=16);rows.append(row)
        if native:h5=pd.concat([frame,pd.DataFrame(rows)],ignore_index=True)
        else:r6=pd.concat([frame,pd.DataFrame(rows)],ignore_index=True)
    result=run(fixture,prediction_prefix=pred,calendar_prefix=cal,decision_date=cal[-1],
        decision_as_of=cal[-1].tz_localize("America/New_York")+pd.Timedelta(hours=16),r6_probe_rows=r6,native_h5_probe_rows=h5)
    assert result.role_frames["R6:duration"].empty and result.role_frames["R10:HAZARD"].empty
    count=3 if cause=="late_publication" else 0
    assert result.audit["late_publication_metadata_discarded"]==dict(R6=count,native_H5=count)



def test_duplicate_row_index_rejected_before_filtered_outcome_access(fixture):
    frame=fixture.r6.copy();frame.index=[0]*len(frame)
    class ForbiddenOutcome:
        def __float__(self):raise AssertionError("duplicate index reselected excluded outcome")
    frame["y_open5"]=[ForbiddenOutcome() for _ in range(len(frame))]
    with pytest.raises(ValueError,match="PROBE_ROW_INDEX_NOT_UNIQUE"):
        run(fixture,r6_probe_rows=frame)


@pytest.mark.parametrize("change",[None,"value","maturity","available","flag","coordinate","horizon"])
def test_original_native_parent_h5_reuse_requires_exact_qualified_parent(fixture,change):
    native=fixture.h5.copy()
    native["source_label_identity"]="PARENT_VALID5D_EXACT_REUSE"
    native["parent_valid5d_exact_reuse"]=True;native["horizon_sessions"]=5
    native["label_coordinate"]=state.original_inputs.LABEL
    if change=="value":native.loc[0,"label_value"]+=.001
    elif change=="maturity":native.loc[0,"label_mature_date"]=fixture.cal[6]
    elif change=="available":native.loc[0,"observation_available_at"]+=pd.Timedelta(seconds=1)
    elif change=="flag":native.loc[0,"parent_valid5d_exact_reuse"]=False
    elif change=="coordinate":native.loc[0,"label_coordinate"]="RAW_PRICE_ONLY"
    elif change=="horizon":native.loc[0,"horizon_sessions"]=10
    if change:
        with pytest.raises(ValueError,match="PARENT_H5|NATIVE_CA"):run(fixture,native_h5_probe_rows=native)
    else:
        original=run(fixture);result=run(fixture,native_h5_probe_rows=native)
        for name,frame in result.role_frames.items():pd.testing.assert_frame_equal(frame,original.role_frames[name])
        np.testing.assert_array_equal(result.joint_sequence,original.joint_sequence)


def test_qualified_empty_source_and_no_active_cohort_is_computed_zero(fixture):
    pred=fixture.pred.copy();pred["new_buy_eligible"]=False
    result=run(fixture,prediction_prefix=pred,r6_probe_rows=fixture.r6.iloc[:0],native_h5_probe_rows=fixture.h5.iloc[:0])
    assert all(frame.empty for frame in result.role_frames.values())
    assert result.joint_sequence.shape==(0,5,len(result.sequence_features))
    assert result.audit["source_certified"] is False


def test_original_native_labels_parent_branch_matches_forward_parent_projection(fixture):
    mapper={d:(d-pd.DateOffset(years=1) if d.year>=2025 else d) for d in fixture.cal}
    reverse={v:k for k,v in mapper.items()}
    parent=_translate(fixture.r6,mapper)
    plan=_translate(fixture.h5,mapper).drop(columns=["label_value","label_qualified"])
    plan["execution_date"]=plan.signal_date
    plan["label_end_date"]=plan.label_mature_date
    plan["mechanism_coordinate_supported"]=False
    plan["label_quantity_multiplier"]=1.;plan["horizon_sessions"]=5
    quotes=pd.DataFrame({"trade_date":pd.Series(dtype="datetime64[ns]"),"ticker":pd.Series(dtype=str),"open":pd.Series(dtype=float)})
    original=state.mechanism_inputs.native_labels(plan,quotes,parent5=parent)
    assert original.parent_valid5d_exact_reuse.all()
    assert original.source_label_identity.eq("PARENT_VALID5D_EXACT_REUSE").all()
    original=_translate(original,reverse)
    original["observation_available_at"]=fixture.h5.observation_available_at
    result=run(fixture,native_h5_probe_rows=original);expected=run(fixture)
    for name,frame in result.role_frames.items():pd.testing.assert_frame_equal(_translate(frame,{}),_translate(expected.role_frames[name],{}),check_dtype=False)
    np.testing.assert_array_equal(result.joint_sequence,expected.joint_sequence)


@pytest.mark.parametrize("change",[None,"source_is_coordinate","coordinate_is_source","missing_coordinate"])
def test_original_native_producer_identity_and_coordinate_are_independent_fields(fixture,change):
    # Run the unchanged ORIGINAL native pure producer on pre2026 synthetic
    # inputs. Its mechanism flags are not actual-source qualification.
    mapper={d:(d-pd.DateOffset(years=1) if d.year>=2025 else d) for d in fixture.cal}
    reverse={v:k for k,v in mapper.items()};cal=pd.DatetimeIndex([mapper[d] for d in fixture.cal])
    pred=_translate(fixture.pred,mapper)
    keys=_translate(fixture.h5[list(state._KEYS)],mapper)
    quotes=pred[["signal_date","ticker"]].rename(columns={"signal_date":"trade_date"})
    quotes["open"]=10.+quotes.trade_date.map({d:j for j,d in enumerate(cal)})*.1
    def no_events(plan,events):
        return np.ones(len(plan)),np.zeros(len(plan),bool),np.zeros(len(plan),int)
    plan=state.mechanism_inputs.native_endpoint_plan(keys,cal,5,pred,quotes[["trade_date","ticker"]],[],no_events,
        "R10_NATIVE_H5_FROZEN_HISTORY_MECHANISM")
    native=state.mechanism_inputs.native_labels(plan,quotes)
    assert native.source_label_identity.eq("R10_NATIVE_H5_FROZEN_HISTORY_MECHANISM").all()
    assert native.label_coordinate.eq("R10_NATIVE_RAW_OPEN_SHAREHOLDER_H5_SUPPORTED_EVENTS").all()
    assert native.horizon_sessions.eq(5).all() and native.label_qualified.all()
    assert not native.historical_available_at_bound.any()  # No actual-source promotion.
    native=_translate(native,reverse)
    # Explicit SYNTHETIC actual-clock witness, never copy mechanism16:00 field.
    native["observation_available_at"]=fixture.h5.observation_available_at
    if change=="source_is_coordinate":native["source_label_identity"]="R10_NATIVE_RAW_OPEN_SHAREHOLDER_H5_SUPPORTED_EVENTS"
    elif change=="coordinate_is_source":native["label_coordinate"]="R10_NATIVE_H5_FROZEN_HISTORY_MECHANISM"
    elif change=="missing_coordinate":native=native.drop(columns="label_coordinate")
    if change:
        with pytest.raises(ValueError,match="NATIVE_CA|PROBE_SOURCE_SCHEMA"):
            run(fixture,native_h5_probe_rows=native)
    else:
        result=run(fixture,native_h5_probe_rows=native)
        assert len(result.role_frames["R10:HAZARD"])==3 and result.audit["source_certified"] is False


@pytest.mark.parametrize("candidate,roles",[
    ("R6_BUY_TREE",("R6:buy",)),("R6_HOLD_TREE",("R6:hold",)),
    ("R6_REPLACE_TREE",("R6:replace",)),
    ("R6_DISTRIBUTION_TREE",("R6:distribution","R6:distribution_pair")),
    ("R10_DIRECT_MEAN4_RIDGE",("R10:ENTRY","R10:INCUMBENT")),
    ("R10_SEQUENCE_GRU_L5_MID",("R10:JOINT_SEQUENCE",))])
def test_h5_free_roles_reuse_original_features_without_touching_probe_readers(fixture,monkeypatch,candidate,roles):
    from dataclasses import replace
    expected=run(fixture)
    auth=replace(fixture.auth,allowed_path_ids=(candidate,),runtime_policy_ids=(candidate,))
    monkeypatch.setattr(state.profile,"required_action_roles",lambda cid:roles if cid==candidate else (),raising=False)
    def forbidden(*args,**kwargs):raise AssertionError("H5-free role touched a probe reader")
    monkeypatch.setattr(state,"_probes",forbidden)
    result=run(fixture,authority=auth,required_roles=roles,r6_probe_rows=object(),native_h5_probe_rows=object())
    assert set(result.role_frames)==set(roles)
    for role in roles:pd.testing.assert_frame_equal(result.role_frames[role],expected.role_frames[role],check_dtype=False)
    if "R10:JOINT_SEQUENCE" in roles:
        np.testing.assert_array_equal(result.joint_sequence,expected.joint_sequence)
        np.testing.assert_array_equal(result.sequence_supported,expected.sequence_supported)
        assert result.sequence_features==expected.sequence_features
    else:assert result.joint_sequence.size==0 and result.sequence_features==()
    assert result.audit["probe_readers_consumed"]==dict(R6=False,native_H5=False)
    assert result.audit["source_certified"] is False


@pytest.mark.parametrize("role,candidate,missing",[
    ("R6:duration","R6_DURATION_TREE","r6_probe_rows"),
    ("R10:HAZARD","R10_HAZARD_HGB_LOW","native_h5_probe_rows")])
def test_explicit_h5_dependent_role_still_requires_qualified_reader(fixture,monkeypatch,role,candidate,missing):
    from dataclasses import replace
    auth=replace(fixture.auth,allowed_path_ids=(candidate,),runtime_policy_ids=(candidate,))
    monkeypatch.setattr(state.profile,"required_action_roles",lambda cid:(role,),raising=False)
    with pytest.raises(ValueError,match="QUALIFIED_PROBE_READER"):
        run(fixture,authority=auth,required_roles=(role,),**{missing:None})


@pytest.mark.parametrize("role,candidate,unused",[
    ("R6:duration","R6_DURATION_TREE","native_h5_probe_rows"),
    ("R10:HAZARD","R10_HAZARD_HGB_LOW","r6_probe_rows")])
def test_scoped_probe_role_does_not_read_unrelated_source(fixture,monkeypatch,role,candidate,unused):
    from dataclasses import replace
    expected=run(fixture).role_frames[role]
    auth=replace(fixture.auth,allowed_path_ids=(candidate,),runtime_policy_ids=(candidate,))
    monkeypatch.setattr(state.profile,"required_action_roles",lambda cid:(role,),raising=False)
    result=run(fixture,authority=auth,required_roles=(role,),**{unused:object()})
    pd.testing.assert_frame_equal(result.role_frames[role],expected)
    assert result.audit["probe_readers_consumed"]==dict(R6=role=="R6:duration",native_H5=role=="R10:HAZARD")


@pytest.mark.parametrize("roles",[("R10:ENTRY",),(),("R10:HAZARD","R10:HAZARD"),("UNKNOWN",)])
def test_requested_roles_cannot_omit_or_replace_frozen_hazard_dependency(fixture,monkeypatch,roles):
    from dataclasses import replace
    candidate="R10_HAZARD_HGB_LOW"
    auth=replace(fixture.auth,allowed_path_ids=(candidate,),runtime_policy_ids=(candidate,))
    monkeypatch.setattr(state.profile,"required_action_roles",lambda cid:("R10:HAZARD",),raising=False)
    def forbidden(*args,**kwargs):raise AssertionError("role rejected before probe read")
    monkeypatch.setattr(state,"_probes",forbidden)
    with pytest.raises(ValueError,match="REQUIRED_ACTION_ROLES"):
        run(fixture,authority=auth,required_roles=roles)


def test_hazard_parent_reuse_still_requires_exact_original_parent_reader(fixture,monkeypatch):
    from dataclasses import replace
    cid="R10_HAZARD_HGB_LOW";auth=replace(fixture.auth,allowed_path_ids=(cid,),runtime_policy_ids=(cid,))
    monkeypatch.setattr(state.profile,"required_action_roles",lambda cid:("R10:HAZARD",),raising=False)
    native=fixture.h5.copy();native["source_label_identity"]="PARENT_VALID5D_EXACT_REUSE"
    native["parent_valid5d_exact_reuse"]=True;native["label_coordinate"]=state.original_inputs.LABEL
    with pytest.raises(ValueError,match="QUALIFIED_PROBE_READER"):
        run(fixture,authority=auth,required_roles=("R10:HAZARD",),native_h5_probe_rows=native,r6_probe_rows=None)



def test_h5_free_empty_cohort_uses_typed_annotations_without_probe_reader(fixture,monkeypatch):
    from dataclasses import replace
    candidate="R10_DIRECT_MEAN4_RIDGE";roles=("R10:ENTRY","R10:INCUMBENT")
    auth=replace(fixture.auth,allowed_path_ids=(candidate,),runtime_policy_ids=(candidate,))
    monkeypatch.setattr(state.profile,"required_action_roles",lambda cid:roles,raising=False)
    pred=fixture.pred.copy();pred["new_buy_eligible"]=False
    def forbidden(*args,**kwargs):raise AssertionError("empty H5-free cohort touched probe reader")
    monkeypatch.setattr(state,"_probes",forbidden)
    result=run(fixture,authority=auth,prediction_prefix=pred,required_roles=roles,
        r6_probe_rows=None,native_h5_probe_rows=None)
    assert set(result.role_frames)==set(roles) and all(f.empty for f in result.role_frames.values())
    assert result.audit["probe_readers_consumed"]==dict(R6=False,native_H5=False)
    assert result.audit["source_certified"] is False



def test_all_a_l10_uses_original_history_and_cannot_be_replaced_by_l5(fixture):
    from dataclasses import replace
    row=dict(candidate_id="ORIGINAL_L10",required_action_roles=["R10:JOINT_SEQUENCE"],lookback=10)
    prov=json.loads(fixture.auth.provenance_json);prov["candidate_bindings"]=[row]
    auth=replace(fixture.auth,task_id=state.profile.ALL_TASK,allowed_path_ids=("ORIGINAL_L10",),
        runtime_policy_ids=("ORIGINAL_L10",),provenance_json=json.dumps(prov))
    x=run(fixture,authority=auth,required_roles=("R10:JOINT_SEQUENCE",),sequence_length=10,
        r6_probe_rows=None,native_h5_probe_rows=None)
    assert x.joint_sequence.shape[1]==10
    assert x.audit["sequence_length"]==10 and x.audit["original_cohort_phase"]=="2023_PREFIX_NO_ANNUAL_RESET"
    with pytest.raises(ValueError,match="SEQUENCE_LENGTH"):
        run(fixture,authority=auth,required_roles=("R10:JOINT_SEQUENCE",),sequence_length=5,
            r6_probe_rows=None,native_h5_probe_rows=None)
