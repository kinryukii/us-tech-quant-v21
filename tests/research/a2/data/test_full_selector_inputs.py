"""Synthetic-only full-U/time/identity checks, no real-input imports or reads."""
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.data import full_selector_inputs as owner


def inputs():
    m=pd.DataFrame({"signal_date":pd.to_datetime(["2023-02-01"]*3),"ticker":["OUT40","CORE","OTHER"],
        "cusip":["3","1","2"],"U_t_fingerprint":["FULL"]*3,"active_13f_quarter":["Q"]*3})
    f=m[["signal_date","ticker"]].copy()
    for name in owner.FEATURES:f[name]=[1.,2.,np.nan]
    return m,f


def test_full_U_never_truncated_to_raw_boundary_or_missing_features():
    m,f=inputs();f=f.iloc[:2]
    out=owner.fixed_membership(m,f)
    assert len(out)==3 and set(out.ticker)==set(m.ticker)
    assert out.loc[out.ticker=="OTHER","feature_source_present"].eq(False).all()
    assert "OUT40" in set(out.ticker)


def test_uid_permutation_changes_only_order_not_coordinate_binding():
    m,f=inputs()
    a=owner.fixed_membership(m,f)
    b=owner.fixed_membership(m.iloc[::-1],f.iloc[::-1])
    pd.testing.assert_frame_equal(a,b)


def test_future_append_cannot_change_prior_feature_domain():
    m,f=inputs();a=owner.fixed_membership(m,f)
    extra=m.iloc[:1].copy();extra.signal_date=pd.Timestamp("2025-01-01")
    ef=f.iloc[:1].copy();ef.signal_date=pd.Timestamp("2025-01-01")
    b=owner.fixed_membership(pd.concat([m,extra]),pd.concat([f,ef]))
    pd.testing.assert_frame_equal(a,b.loc[b.signal_date<"2024-01-01"].reset_index(drop=True))


def test_inf_and_missing_identity_are_rejected():
    m,f=inputs();f.loc[0,owner.FEATURES[0]]=np.inf
    with pytest.raises(ValueError,match="INFINITE"):owner.fixed_membership(m,f)
    m.loc[0,"cusip"]=None
    with pytest.raises(ValueError,match="UID"):owner.fixed_membership(m,f.replace(np.inf,1.))


def test_true_endpoint_maturity_not_signal_date_controls_training():
    m,f=inputs();keys=owner.fixed_membership(m,f).drop(columns=list(owner.FEATURES))
    labels=keys[owner.KEYS+["U_t_fingerprint"]].copy()
    for c,h in zip(owner.CLOCKS,(20,3,5,10,20)):labels[c]=pd.Timestamp("2023-12-12")+pd.Timedelta(days=h)
    joined,mask=owner.mature_mask(keys,labels,"2024-01-01")
    assert not mask.any()
    for c,h in zip(owner.CLOCKS,(20,3,5,10,20)):labels[c]=pd.Timestamp("2023-12-01")+pd.Timedelta(days=h)
    _,mask=owner.mature_mask(keys,labels,"2024-01-01")
    assert mask.all()


def test_label_fingerprint_cannot_cross_full_universe_epoch():
    m,f=inputs();keys=owner.fixed_membership(m,f).drop(columns=list(owner.FEATURES))
    labels=keys[owner.KEYS+["U_t_fingerprint"]].copy()
    labels.U_t_fingerprint="OTHER"
    for c,h in zip(owner.CLOCKS,(20,3,5,10,20)):labels[c]=pd.Timestamp("2023-12-01")+pd.Timedelta(days=h)
    with pytest.raises(ValueError,match="FINGERPRINT"):owner.mature_mask(keys,labels,"2024-01-01")



def test_empty_cusip_rejected_before_identity_construction():
    m,f=inputs();m.loc[0,"cusip"]="  "
    with pytest.raises(ValueError,match="EMPTY_SOURCE_UID"):owner.fixed_membership(m,f)

def test_backward_or_out_of_order_horizon_cannot_be_called_mature():
    m,f=inputs();keys=owner.fixed_membership(m,f).drop(columns=list(owner.FEATURES))
    labels=keys[owner.KEYS+["U_t_fingerprint"]].copy()
    for c,h in zip(owner.CLOCKS,(20,3,5,10,20)):labels[c]=pd.Timestamp("2023-01-01")+pd.Timedelta(days=h)
    with pytest.raises(ValueError,match="FORWARD_HORIZON"):owner.mature_mask(keys,labels,"2024-01-01")

# Generated-only source/context/H5 integration. No real reader or research run.
def risk_metadata_fixture():
    from scripts.research.a2.data.shared_risk_inputs_r3 import _clock
    from scripts.research.a2.risk.mechanism_risk_adapter import FIXED_POLICY_RISK_FAMILIES
    days=pd.bdate_range("2021-01-01","2024-03-01")
    hist=pd.DataFrame([(a,d,"CUSIP:"+a,_clock(d),True,"GENERATED_EXACT_UID_SOURCE")
        for d in days for a in ("A","B")],columns=list(owner.RISK_IDENTITY_COLUMNS))
    selected=pd.to_datetime(["2023-01-02","2023-01-03","2023-02-01"])
    keys=pd.DataFrame([(d,a,"CUSIP:"+a,"FULL_A_B") for d in selected for a in ("A","B")],
        columns=["signal_date","ticker","security_uid","U_t_fingerprint"])
    events=[dict(effective_at="2020-01-01T21:00:00Z",
        family_source_support={f:{"source_sha":"a"*64,"role":f} for f in FIXED_POLICY_RISK_FAMILIES})]
    return keys,days,hist,events


def test_risk_context_retains_every_train_oof_date_union_not_times18():
    keys,days,hist,events=risk_metadata_fixture()
    value=owner.fixed_policy_risk_metadata_contexts(keys,days,hist,events,security_coordinate="CURRENT_SHARE")
    assert value["all_full_u_dates_retained"] and len(value["decision_to_context"])==3
    assert value["distinct_union_context_upper"]==2 and value["learned_slot_upper"]==142
    assert len(value["plan"]["nodes"])==36
    assert value["numeric_reads"]==value["labels_read"]==value["risk_fits"]==0
    assert all(c["full_252_calendar_window"] and c["unresolved_identity_count"]==0 for c in value["coverage"])
    assert value["unused_slots_status"]=="NOT_REQUIRED_NOT_SUCCEEDED"


def test_risk_uid_source_gap_never_carry_and_known_full_U_never_deleted():
    keys,days,hist,events=risk_metadata_fixture()
    missing=pd.Timestamp("2022-12-30")
    hist=hist.loc[~(hist.ticker.eq("B")&hist.signal_date.eq(missing))].copy()
    epochs=owner.fixed_policy_risk_identity_epochs(hist,days)
    before=epochs.loc[epochs.ticker.eq("B")&epochs.signal_date.eq("2022-12-29"),"identity_epoch"].iloc[0]
    after=epochs.loc[epochs.ticker.eq("B")&epochs.signal_date.eq("2023-01-02"),"identity_epoch"].iloc[0]
    assert before!=after
    result=owner.fixed_policy_risk_metadata_contexts(keys,days,hist.iloc[:0],events,security_coordinate="CURRENT_SHARE")
    assert len(result["decision_to_context"])==3
    assert result["coverage"][0]["full_u_count"]==result["coverage"][0]["unresolved_identity_count"]==2
    # Stable membership metadata cannot manufacture one refresh each ordinary day.
    assert result["distinct_union_context_upper"]==2


def test_risk_h5_window_uses_mature_endpoint_exclusive_previous_close():
    from scripts.research.a2.data.shared_risk_inputs_r3 import _calendar
    keys,days,hist,events=risk_metadata_fixture()
    result=owner.fixed_policy_risk_metadata_contexts(keys,days,hist,events,security_coordinate="CURRENT_SHARE")
    day=keys.signal_date.min();i=days.get_loc(day)
    latest=pd.Timestamp(result["coverage"][0]["window_end"])
    assert latest==days[i-8]
    assert _calendar(days)[1][days.get_loc(latest)+6]<_calendar(days)[1][i-1]


def test_risk_future_append_metadata_cannot_change_past_nodes():
    keys,days,hist,events=risk_metadata_fixture()
    a=owner.fixed_policy_risk_metadata_contexts(keys.iloc[:4],days,hist,events,security_coordinate="CURRENT_SHARE")
    b=owner.fixed_policy_risk_metadata_contexts(keys,days,hist,events,security_coordinate="CURRENT_SHARE")
    assert a["decision_to_context"]==b["decision_to_context"][:2]
    assert a["plan"]["nodes"]==b["plan"]["nodes"][:18]


def test_native_h5_requires_source_event_coverage_not_sparse_event_absence():
    keys,days,hist,_=risk_metadata_fixture()
    requests=keys.iloc[:2].rename(columns={"security_uid":"security_id"})
    raw=pd.DataFrame([(a,d,100.) for d in days for a in ("A","B")],
        columns=["ticker","trade_date","open"])
    noevents=lambda plan,_:(np.ones(len(plan)),np.zeros(len(plan),bool),np.zeros(len(plan),int))
    coverage=pd.DataFrame([("A",days[0],pd.Timestamp("2024-04-01"),True)],
        columns=["ticker","start","stop","source_complete"])
    plan=owner.fixed_policy_native_h5_plan(requests,days,hist,raw[["ticker","trade_date"]],
        [],noevents,source_identity="GENERATED_NATIVE_H5",event_coverage=coverage)
    assert plan.loc[plan.ticker.eq("A"),"mechanism_coordinate_supported"].all()
    assert not plan.loc[plan.ticker.eq("B"),"mechanism_coordinate_supported"].any()
    labels=owner.fixed_policy_native_h5_labels(plan,raw)
    assert labels.loc[labels.ticker.eq("A"),"label_available"].all()
    assert not labels.loc[labels.ticker.eq("B"),"label_available"].any()
    assert labels.loc[labels.ticker.eq("B"),"y_open5"].isna().all()


def test_native_h5_gap_even_matching_endpoint_UID_is_not_observed_continuity():
    keys,days,hist,_=risk_metadata_fixture()
    requests=keys.iloc[:2].rename(columns={"security_uid":"security_id"})
    entry=days[days.get_loc(requests.signal_date.iloc[0])+1]
    hist=hist.loc[~(hist.ticker.eq("A")&hist.signal_date.eq(entry+pd.offsets.BDay(1)))]
    raw=pd.DataFrame([(a,d,100.) for d in days for a in ("A","B")],columns=["ticker","trade_date","open"])
    coverage=pd.DataFrame([(a,days[0],pd.Timestamp("2024-04-01"),True) for a in ("A","B")],
        columns=["ticker","start","stop","source_complete"])
    noevents=lambda plan,_:(np.ones(len(plan)),np.zeros(len(plan),bool),np.zeros(len(plan),int))
    plan=owner.fixed_policy_native_h5_plan(requests,days,hist,raw[["ticker","trade_date"]],
        [],noevents,source_identity="GENERATED_NATIVE_H5",event_coverage=coverage)
    assert not plan.loc[plan.ticker.eq("A"),"mechanism_coordinate_supported"].any()
    assert plan.loc[plan.ticker.eq("B"),"mechanism_coordinate_supported"].all()


def test_context_2026_and_future_source_metadata_rejected():
    keys,days,hist,events=risk_metadata_fixture()
    keys.loc[0,"signal_date"]=pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError,match="PRE2026"):
        owner.fixed_policy_risk_metadata_contexts(keys,days,hist,events,security_coordinate="CURRENT_SHARE")
    keys,days,hist,events=risk_metadata_fixture()
    events[0]["effective_at"]="2026-01-01T00:00:00Z"
    with pytest.raises(ValueError,match="PRE2026"):
        owner.fixed_policy_risk_metadata_contexts(keys,days,hist,events,security_coordinate="CURRENT_SHARE")

from pathlib import Path

# Actual-reader proposals use generated files and in-memory freezes only.
def _reader_fixture(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    from scripts.research.a2.data.shared_risk_inputs_r3 import _clock
    from scripts.research.a2.risk.mechanism_risk_adapter import content_hash
    days=pd.bdate_range("2022-01-03",periods=340)
    assets=("A","B","C")
    uids={a:"CUSIP:"+str(i+1).zfill(9) for i,a in enumerate(assets)}
    epochs={a:"FROZEN_CURRENT:"+a for a in assets}
    decision=days[-1];cutoff=_clock(days[-2]);origins=days[-260:-8]
    identity=[];labels=[]
    for i,day in enumerate(days[:-1]):
        for asset in assets:
            cusip=uids[asset].removeprefix("CUSIP:")
            identity.append(dict(signal_date=day,ticker=asset,security_id=cusip,
                security_id_type="CUSIP",cusip=cusip))
            if i+6<len(days)-1:
                labels.append(dict(signal_date=day,ticker=asset,execution_date=days[i+1],
                    label_end_date=days[i+6],label_mature_date=days[i+6],
                    endpoint_pair_available=True,label_available=True,
                    label_unsupported_common_event=False,
                    label_coordinate="SHAREHOLDER_OPEN_T_PLUS_1_TO_T_PLUS_6_5_SESSION_RETURN_SUPPORTED_EVENTS_FAIL_CLOSED",
                    y_open5=.001*(1+assets.index(asset))))
    uid=pd.DataFrame(identity);h5=pd.DataFrame(labels)
    # One missing source UID day breaks C's prior suffix, no backfill.
    uid=uid.loc[~(uid.ticker.eq("C") & uid.signal_date.eq(days[-22]))].copy()
    hpath=tmp_path/"h5.parquet";upath=tmp_path/"uid.parquet"
    h5.to_parquet(hpath,index=False);uid.to_parquet(upath,index=False)
    def ref(path):return dict(path=str(path),sha256=owner.sha256(path))
    sources=dict(absolute_h5=ref(hpath),dated_cusip_history=ref(upath))
    qrefs={}
    for year in range(2019,2026):
        path=tmp_path/("qqq"+str(year)+".parquet")
        qdays=days[(days.year==year)]
        pd.DataFrame(dict(ticker=["QQQ"]*len(qdays),trade_date=list(qdays.strftime("%Y-%m-%d")),
            open=np.arange(len(qdays),dtype=float)+100)).to_parquet(path,index=False)
        qrefs[str(year)]=ref(path)
    sources["qqq_qfq"]=qrefs
    ff=tmp_path/"ff.parquet"
    pd.DataFrame(dict(decision_date=pd.Series(dtype="datetime64[ns]"),
        canonical_security_id=pd.Series(dtype="str"),ticker_at_date=pd.Series(dtype="str"),
        identity_status=pd.Series(dtype="str"),sic_available_at=pd.Series(dtype="datetime64[ns, UTC]"),
        ff48_code=pd.Series(dtype=float),taxonomy_status=pd.Series(dtype="str"))).to_parquet(ff,index=False)
    sources["ff48"]=ref(ff)
    context=dict(signal_date=decision.date().isoformat(),decision_at=_clock(decision).isoformat(),
        cutoff=cutoff.isoformat(),ordered_assets=list(assets),asset_uids=uids,asset_epochs=epochs,
        context_id="b"*64,security_coordinate="shareholder_value_open_return",
        matured_origin_start=origins[0].date().isoformat(),
        matured_origin_stop_exclusive=days[days.get_loc(origins[-1])+1].date().isoformat(),
        source_support_identity={"source":"FROZEN_SYNTHETIC_FILES"},family_source_support_identity={})
    document=dict(calendar_sessions=list(days.strftime("%Y-%m-%d")),full_U_keys={"path":"unused","sha256":"f"*64})
    binding=dict(source_refs=sources,actual_snapshot_timestamp="2026-10-11T00:00:00+00:00")
    run=tmp_path/"run";run.mkdir()
    design=dict(research_id=owner.ID,dag=dict(nodes=[{"node_id":"ESTIMATOR|SYNTHETIC","kind":"ESTIMATOR"}]))
    (run/"DESIGN_FREEZE.json").write_text(json.dumps(design),encoding="utf8")
    fake=lambda _run,_context=None:(run,binding,design,dict(path="generated",sha256="a"*64),document,context if _context is not None else None)
    monkeypatch.setattr(owner,"_fixed_policy_risk_binding",fake)
    ack=dict(ack=True,reserved_units=71,reservation_id="RISK_REFRESH|"+context["signal_date"])
    return run,binding,context,ack,days,design,h5,uid


def test_actual_risk_reader_uses_original_typed_owner_and_full252_axis(tmp_path,monkeypatch):
    run,b,c,ack,days,_,_,_=_reader_fixture(tmp_path,monkeypatch)
    packet=owner.load_fixed_policy_risk_inputs(run,c,reservation_ack=ack)
    frame=packet["inputs"].observations
    assert tuple(packet["inputs"].assets)==("A","B","C")
    assert frame.origin_at.nunique()==252 and len(frame)==3*252
    counts=packet["support_metadata"].groupby("asset").qualified.sum()
    assert counts["A"]==counts["B"]==252 and counts["C"]<30
    assert frame.loc[frame.asset.eq("C"),"return_value"].isna().sum()>220
    assert packet["reservation_ack"]==ack and packet["risk_estimates"]==0
    assert packet["native_scenario_receipt"]["native"] is True
    assert packet["native_scenario_source_projection_sha256"]==packet["native_scenario_receipt"]["source_projection_sha256"]
    assert packet["inputs"].source_receipt.synthetic is False
    packet["inputs"].source_receipt.validate(pd.Timestamp(c["cutoff"]))


@pytest.mark.parametrize("change",[
    dict(ack=False),dict(reserved_units=70),dict(reservation_id="RISK_REFRESH|2099-01-01")])
def test_reader_rejects_ack_before_value_access(tmp_path,monkeypatch,change):
    run,b,c,ack,*_=_reader_fixture(tmp_path,monkeypatch)
    called=[]
    monkeypatch.setattr(owner,"_fixed_policy_selected_h5_values",lambda *a:called.append(True))
    with pytest.raises(ValueError,match="DURABLE_EXACT_REFRESH"):
        owner.load_fixed_policy_risk_inputs(run,c,reservation_ack={**ack,**change})
    assert called==[]


def test_reader_receipt_clock_gate_precedes_native_value_decode(tmp_path,monkeypatch):
    run,b,c,ack,*_=_reader_fixture(tmp_path,monkeypatch)
    b["actual_snapshot_timestamp"]="2018-01-01T00:00:00+00:00"
    called=[]
    monkeypatch.setattr(owner,"_fixed_policy_selected_h5_values",lambda *a:called.append(True))
    with pytest.raises(ValueError,match="ACTUAL_RISK_SOURCE_SNAPSHOT_CLOCK"):
        owner.load_fixed_policy_risk_inputs(run,c,reservation_ack=ack)
    assert called==[]


def test_uid_namespace_transport_rejects_non_cusip_type(tmp_path,monkeypatch):
    run,b,c,ack,days,_,_,uid=_reader_fixture(tmp_path,monkeypatch)
    uid.loc[uid.ticker.eq("A"),"security_id_type"]="TICKER"
    uid.to_parquet(b["source_refs"]["dated_cusip_history"]["path"],index=False)
    packet=owner.load_fixed_policy_risk_inputs(run,c,reservation_ack=ack)
    assert packet["support_metadata"].loc[packet["support_metadata"].asset.eq("A"),"qualified"].sum()==0
    assert tuple(packet["inputs"].assets)==("A","B","C")


def test_missing_and_unsupported_h5_values_are_not_decoded_or_zero_filled(tmp_path,monkeypatch):
    run,b,c,ack,days,_,h5,_=_reader_fixture(tmp_path,monkeypatch)
    h5.loc[h5.ticker.eq("B"),"label_unsupported_common_event"]=True
    h5.loc[h5.ticker.eq("B"),"y_open5"]=np.inf
    h5.to_parquet(b["source_refs"]["absolute_h5"]["path"],index=False)
    packet=owner.load_fixed_policy_risk_inputs(run,c,reservation_ack=ack)
    obs=packet["inputs"].observations
    assert obs.loc[obs.asset.eq("B"),"return_value"].isna().all()
    assert packet["numeric_read_counts"]["native_h5_rows"]==int(packet["support_metadata"].qualified.sum())


def test_qualified_nan_is_rejected(tmp_path,monkeypatch):
    run,b,c,ack,days,_,h5,_=_reader_fixture(tmp_path,monkeypatch)
    h5.loc[h5.ticker.eq("A") & h5.signal_date.eq(pd.Timestamp(c["matured_origin_start"])),"y_open5"]=np.nan
    h5.to_parquet(b["source_refs"]["absolute_h5"]["path"],index=False)
    with pytest.raises(ValueError,match="EXACT_FINITE_NATIVE_H5_VALUES"):
        owner.load_fixed_policy_risk_inputs(run,c,reservation_ack=ack)


def _outer_terminal(run,design):
    import json,sqlite3
    assembly=run/"SCORE_ASSEMBLY.json";assembly.write_text("{}",encoding="utf8")
    policy=run/"policy.parquet";pd.DataFrame({"selected":[True]}).to_parquet(policy,index=False)
    terminal=dict(research_id=owner.ID,status="ALL_POLICIES_FROZEN_BEFORE_OUTCOMES",
        all_scientific_nodes_terminal=True,design_sha256=owner.sha256(run/"DESIGN_FREEZE.json"),
        assembly_ref=dict(path=str(assembly),sha256=owner.sha256(assembly)),
        policy_refs={"HGB":dict(path=str(policy),sha256=owner.sha256(policy))})
    (run/"POLICY_TERMINAL.json").write_text(json.dumps(terminal),encoding="utf8")
    db=sqlite3.connect(run/"TASK_LEDGER.sqlite")
    db.execute("CREATE TABLE authority(design_sha256 TEXT)")
    db.execute("CREATE TABLE nodes(node_id TEXT,kind TEXT,status TEXT)")
    db.execute("INSERT INTO authority VALUES (?)",(terminal["design_sha256"],))
    db.execute("INSERT INTO nodes VALUES ('ESTIMATOR|SYNTHETIC','ESTIMATOR','COMPLETE')")
    db.commit();db.close()
    return terminal


def test_outer_h5_requires_physical_terminal_and_readonly_ledger_before_values(tmp_path,monkeypatch):
    import sqlite3
    run,b,c,ack,days,design,*_=_reader_fixture(tmp_path,monkeypatch)
    terminal=_outer_terminal(run,design)
    clock=pd.DataFrame(dict(signal_date=[days[-12]],ticker=["A"],security_uid=[c["asset_uids"]["A"]]))
    with sqlite3.connect(run/"TASK_LEDGER.sqlite") as db:
        db.execute("UPDATE nodes SET status='STARTED'")
    called=[];monkeypatch.setattr(owner,"_fixed_policy_selected_h5_values",lambda *a:called.append(True))
    with pytest.raises(ValueError,match="ALL_SCIENTIFIC_NODES_TERMINAL"):
        owner.load_fixed_policy_outer_h5(run,terminal,clock)
    assert called==[]


def test_outer_h5_endpoint_identity_gap_is_not_success(tmp_path,monkeypatch):
    run,b,c,ack,days,design,h5,uid=_reader_fixture(tmp_path,monkeypatch)
    terminal=_outer_terminal(run,design)
    origin=days[-15]
    uid=uid.loc[~(uid.ticker.eq("A")&uid.signal_date.eq(days[-12]))]
    uid.to_parquet(b["source_refs"]["dated_cusip_history"]["path"],index=False)
    clock=pd.DataFrame(dict(signal_date=[origin,origin],ticker=["A","B"],
        security_uid=[c["asset_uids"]["A"],c["asset_uids"]["B"]]))
    packet=owner.load_fixed_policy_outer_h5(run,terminal,clock)
    frame=packet["frame"].set_index("ticker")
    assert frame.loc["A","h5_status"]=="NATIVE_H5_NOT_TESTABLE" and pd.isna(frame.loc["A","y_open5"])
    assert frame.loc["B","h5_status"]=="NATIVE_ABSOLUTE_H5_COMPLETE"
    assert packet["missing_filled_with_zero"] is False


def test_outer_policy_opaque_pin_drift_blocks_before_values(tmp_path,monkeypatch):
    run,b,c,ack,days,design,*_=_reader_fixture(tmp_path,monkeypatch)
    terminal=_outer_terminal(run,design)
    Path(terminal["assembly_ref"]["path"]).write_text('{"changed":true}',encoding="utf8")
    clock=pd.DataFrame(dict(signal_date=[days[-15]],ticker=["A"],security_uid=[c["asset_uids"]["A"]]))
    with pytest.raises(ValueError,match="OUTER_TERMINAL_POLICY_ARTIFACT_CHANGED"):
        owner.load_fixed_policy_outer_h5(run,terminal,clock)


def test_metadata_decoder_preserves_old_complete_node_token_contract(tmp_path,monkeypatch):
    import json
    from scripts.research.a2.risk.mechanism_risk_adapter import content_hash,FIXED_POLICY_RISK_FAMILIES
    c=dict(signal_date="2023-01-03",decision_at="2023-01-03T21:00:00+00:00",cutoff="2023-01-02T21:00:00+00:00",
        ordered_assets=["A"],asset_uids={"A":"CUSIP:000000001"},asset_epochs={"A":"E"},
        source_support_identity={"s":"S"},family_source_support_identity={f:{"s":"S"} for f in FIXED_POLICY_RISK_FAMILIES},
        security_coordinate="shareholder_value_open_return")
    c["context_id"]=content_hash(c)
    nodes=[dict(family=f,context_id=c["context_id"],decision_at=c["decision_at"],trigger_reasons=["INITIAL_AVAILABLE"],
        structural_sha256="a"*64,recipe_sha256="b"*64) for f in FIXED_POLICY_RISK_FAMILIES]
    daily=dict(decision_at=c["decision_at"],cutoff=c["cutoff"],context_id=c["context_id"],
        matured_origin_start="2022-01-01",matured_origin_stop_exclusive="2022-12-23",signal_date=c["signal_date"])
    document=dict(schema="C_FIXED_POLICY_RISK_INPUT_CONTEXTS_COMPACT_R1",research_id=owner.ID,
        numeric_target_reads=0,risk_numeric_reads=0,risk_fits=0,contexts=[c],nodes=nodes,decision_to_context=[daily],
        retained_decision_dates=1,family_nodes=18,learned_units_upper_bound=71,recipe={},recipe_sha256="b"*64)
    path=tmp_path/"compact.json";path.write_text(json.dumps(document),encoding="utf8")
    decoded=owner.load_metadata_contexts(dict(path=str(path),sha256=owner.sha256(path)))
    assert decoded["plan"]["learned_units_upper_bound"]==71 and len(decoded["plan"]["nodes"])==18
    tokens={n["family"]:content_hash(n) for n in decoded["plan"]["nodes"]}
    assert decoded["decision_to_context"][0]["family_context_ids"]==tokens
