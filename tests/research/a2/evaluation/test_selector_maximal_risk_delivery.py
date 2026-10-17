"""C14 joint delivery tests: real gates/pure owners, no production artifacts."""
from copy import deepcopy
from pathlib import Path
import hashlib
import importlib.util
import json
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.evaluation import selector_maximal_risk_delivery as s


def metadata():
    path=Path(__file__).parents[1]/"data/test_selector_maximal_risk_outcomes.py"
    spec=importlib.util.spec_from_file_location("joint_c14_metadata_fixture",path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.c14_design()


@pytest.fixture
def boundary(monkeypatch):
    run=Path("D:/us-tech-quant-backtests/V24/SYNTHETIC_JOINT_DELIVERY")
    monkeypatch.setattr(s,"RUN",run)
    monkeypatch.setattr(s.outcomes,"RUN",run)
    objects={};pins=set();calls=[]
    def add(name,obj):
        path=run/name
        raw=json.dumps(obj,sort_keys=True,allow_nan=False,default=str).encode()
        ref=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest())
        objects[(ref["path"],ref["sha256"])]=deepcopy(obj);pins.add((ref["path"],ref["sha256"]))
        return ref
    def read(ref,**kwargs):
        key=(ref["path"],ref["sha256"])
        assert key in objects,"REAL_ARTIFACT_READ_FORBIDDEN"
        return deepcopy(objects[key])
    def pin(ref):
        key=(ref["path"],ref["sha256"])
        assert key in pins,"REAL_PARQUET_OR_LEDGER_READ_FORBIDDEN"
        return Path(ref["path"])
    monkeypatch.setattr(s,"_read",read);monkeypatch.setattr(s.ctl,"pin",pin)
    d=metadata();d["raw_score"]=add("SYNTHETIC_RAW_SCORE.parquet",{})
    d["inputs"]=dict(hlabels=add("SYNTHETIC_MEAN_ER_LABELS.parquet",{}))
    dref=add("DESIGN_FREEZE.json",d)
    # Production design identity stays hard in the function; synthetic hash only.
    monkeypatch.setattr(s.outcomes.binding,"DESIGN_SHA",dref["sha256"])
    statuses={r:"BLOCKED_INPUT" for r in s.ev.ROLES}
    statuses.update(C14_P01="COMPLETE",C14_P09="COMPLETE",C14_G1="COMPLETE",C14_INC_G1="COMPLETE")
    panels={r:add("risk_execution/"+r+"/SYNTHETIC_PANEL.parquet",{}) for r in ("C14_P01","C14_P09","C14_G1")}
    delta=add("RISK_EXECUTION_DELTA.jsonl",{})
    old_ml_ref=dict(path=str(run/"ML_ASSEMBLY.json"),sha256=s.OLD_ML_ASSEMBLY_SHA)
    pins.add((old_ml_ref["path"],old_ml_ref["sha256"]))
    assembly=dict(status="SCORE_ASSEMBLY_COMPLETE",research_id=s.ID,design_freeze_sha256=dref["sha256"],
        pair_key_sha256="d"*64,complete_candidates=["C14_P01","C14_P09","C14_G1"],panels=panels,
        original_ml_assembly_ref=deepcopy(old_ml_ref),native_pair_predictions={},failed_or_untestable={r:"BLOCKED" for r in statuses if statuses[r]!="COMPLETE"},
        all_training_terminal=True,capacity_selection_complete=True,role_statuses=statuses,
        role_failure_details=dict(statuses),all_applicable_risk_roles_terminal=True,forecast2026_rows=0,
        conditional_delta_ref=delta)
    aref=add("risk_execution/SCORE_ASSEMBLY_R1.json",assembly)
    oldgate=dict(status="FINAL_PIPELINES_FROZEN",research_id=s.ID,design_sha256=dref["sha256"],
        all_training_terminal=True,capacity_selection_complete=True,roles=list(s.ev.ROLES),
        role_statuses={r:("COMPLETE" if r in ("C14_P01","C14_P09") else "BLOCKED_INPUT") for r in statuses},
        score_assembly_sha256="a"*64,fit_ledger_sha256="b"*64,pair_key_sha256="d"*64,forecast2026_rows=0)
    oldref=add("FINAL_PIPELINES_FREEZE.json",oldgate)
    monkeypatch.setattr(s.outcomes,"OLD_ML_GATE_SHA",oldref["sha256"])
    gate=dict(oldgate,role_statuses=deepcopy(statuses),score_assembly_sha256=aref["sha256"],fit_ledger_sha256=delta["sha256"],
        conditional_delta_ref=delta,original_ml_gate_ref=oldref)
    fref=add("risk_execution/FINAL_PIPELINES_FREEZE_R1.json",gate)
    qref=add("INPUT_QUALIFICATION.json",dict(research_id=s.ID,pair_key_sha256="d"*64))
    qual=add("risk_execution/INPUT_QUALIFICATION_R1.json",{})
    term=dict(status="RISK_DECISIONS_TERMINAL_JOINT_DELIVERY_PENDING",research_id=s.ID,
        review_ref=add("SYNTHETIC_EXECUTION_REVIEW.json",{"status":"PASS","research_id":s.ID,
            "immutable_inputs":{"ML_ASSEMBLY.json":deepcopy(old_ml_ref)}}),assembly=aref,final_pipeline=fref,
        delta=delta,input_qualification=qual,reserved_fit_slots=0,backend_entered=0,charged_solves=0,
        combined_charged_solves=18006,complete_conditional_roles=["C14_G1"],
        joint_delivery_completed=False,new_risk_estimations=0,scientific_retry=0,test2026_rows_read=0,
        strict_PIT_promotion_eligible=False)
    tref=add("risk_execution/"+s.TERMINAL_NAME,term)
    pref=add("SYNTHETIC_PRECOMPUTED_REVIEW.json",{})
    lref=add("risk_execution/SYNTHETIC_LEGACY_SUMMARY.json",{})
    oldfit=dict(path=str(run/"FIT_LEDGER.json"),sha256=s.transport.BASELINE_HASHES["FIT_LEDGER.json"])
    pins.add((oldfit["path"],oldfit["sha256"]))
    oldev=deepcopy(s.precomputed.C14_EVIDENCE);pins.add((oldev["path"],oldev["sha256"]))
    review=dict(status="PASS",research_id=s.ID,scientific_contract_changed=False,scientific_retry=0,
        test2026_rows_read=0,adapter_sha256=s.outcomes.binding.sha(s.outcomes.binding.__file__),source_pins=s.required_sources(),
        delivery_inputs=dict(terminal=deepcopy(tref),precomputed_review=deepcopy(pref),legacy_summaries=deepcopy(lref)),
        immutable_inputs={"FIT_LEDGER.json":oldfit,"INPUT_QUALIFICATION.json":qref,"ML_ASSEMBLY.json":deepcopy(old_ml_ref),
            "raw_score":d["raw_score"],"hlabels":d["inputs"]["hlabels"],
            "old_report":add("SYNTHETIC_ORIGINAL_FINAL_REPORT.md",{}),"old_evidence":oldev})
    rref=add("SYNTHETIC_DELIVERY_REVIEW.json",review)
    def forbidden(*a,**k): calls.append("NUMERIC");raise AssertionError("BEFORE_TERMINAL_GATE")
    monkeypatch.setattr(s.precomputed,"load_precomputed",forbidden)
    return dict(run=run,term=term,gate=gate,assembly=assembly,review=review,tref=tref,rref=rref,
        pref=pref,lref=lref,add=add,calls=calls,d=d,dref=dref)


def call_gate(b):
    return s.terminal_inputs(b["run"],b["tref"],b["rref"],b["pref"],b["lref"])


def rebind(b,part):
    if part=="term":
        b["tref"]=b["add"]("risk_execution/"+s.TERMINAL_NAME,b["term"])
        b["review"]["delivery_inputs"]["terminal"]=deepcopy(b["tref"])
    elif part=="assembly":
        ar=b["add"]("risk_execution/SCORE_ASSEMBLY_R1.json",b["assembly"])
        b["term"]["assembly"]=ar;b["gate"]["score_assembly_sha256"]=ar["sha256"]
        rebind(b,"gate")
    elif part=="gate":
        b["term"]["final_pipeline"]=b["add"]("risk_execution/FINAL_PIPELINES_FREEZE_R1.json",b["gate"])
        rebind(b,"term")
    b["rref"]=b["add"]("SYNTHETIC_DELIVERY_REVIEW.json",b["review"])


def test_real_terminal_gate_accepts_only_frozen_new_conditional_inputs(boundary):
    result=call_gate(boundary)
    assert result[3]["complete_conditional_roles"]==["C14_G1"]
    assert result[5]["role_statuses"]["C14_G1"]=="COMPLETE"
    assert not boundary["calls"]


@pytest.mark.parametrize("part,key,value",[
    ("review","status","FAIL"),("review","research_id","C13"),
    ("review","scientific_contract_changed",True),("review","scientific_retry",1),
    ("review","test2026_rows_read",1),
    ("term","status","RUNNING"),("term","joint_delivery_completed",True),
    ("term","new_risk_estimations",1),("term","test2026_rows_read",1),
    ("term","scientific_retry",1),("term","strict_PIT_promotion_eligible",True),
    ("term","reserved_fit_slots",145),("term","backend_entered",1),
    ("term","combined_charged_solves",18007),("term","complete_conditional_roles",["C14_DELTA_RIDGE"]),
    ("gate","all_training_terminal",False),("gate","forecast2026_rows",1),
    ("assembly","all_applicable_risk_roles_terminal",False),
])
def test_rejected_terminal_inputs_never_enter_precomputed_or_outcomes(boundary,part,key,value):
    boundary[part][key]=value;rebind(boundary,part)
    with pytest.raises(ValueError):
        s.deliver(boundary["run"],boundary["tref"],boundary["rref"],boundary["pref"],boundary["lref"])
    assert not boundary["calls"]


@pytest.mark.parametrize("defect",["nonterminal","source","reviewed_terminal","delta","old_gate","labels","missing_panel"])
def test_exact_terminal_and_frozen_sources_custody(boundary,defect):
    if defect=="nonterminal":
        boundary["gate"]["role_statuses"]["C14_G1"]="STARTED"
        boundary["assembly"]["role_statuses"]["C14_G1"]="STARTED";rebind(boundary,"gate")
    elif defect=="source":
        boundary["review"]["source_pins"].pop(str(Path(s.ev.__file__).resolve()));rebind(boundary,"review")
    elif defect=="reviewed_terminal":
        boundary["review"]["delivery_inputs"]["terminal"]["sha256"]="0"*64;rebind(boundary,"review")
    elif defect=="delta":
        boundary["gate"]["conditional_delta_ref"]=boundary["add"]("SYNTHETIC_OTHER_DELTA.jsonl",{});rebind(boundary,"gate")
    elif defect=="old_gate":
        boundary["gate"]["original_ml_gate_ref"]["sha256"]="0"*64;rebind(boundary,"gate")
    elif defect=="labels":
        boundary["review"]["immutable_inputs"]["hlabels"]=boundary["add"]("SYNTHETIC_OTHER_LABELS.parquet",{});rebind(boundary,"review")
    else:
        boundary["assembly"]["panels"].pop("C14_G1");rebind(boundary,"assembly")
    with pytest.raises(ValueError): call_gate(boundary)
    assert not boundary["calls"]


@pytest.fixture(scope="module")
def full_inputs():
    days=pd.DatetimeIndex(list(pd.bdate_range("2023-01-02",periods=250))+
        list(pd.bdate_range("2024-01-01",periods=252))+list(pd.bdate_range("2025-01-01",periods=250)))
    clock=pd.DataFrame(dict(signal_date=days,included=[True]*732+[False]*20))
    reference=pd.DataFrame([(day,f"CUSIP:{i:09d}",f"T{i}",str(j),i,
        i*.001 if j<732 else np.nan,day+pd.Timedelta(days=7) if j<732 else pd.NaT)
        for j,day in enumerate(days) for i in range(1,41)],
        columns=["signal_date","security_uid","ticker","U_t_fingerprint","raw_rank","target","label_end_date"])
    panels={}
    for role in ("C14_D01","C14_G1"):
        p=reference[["signal_date","security_uid","ticker","U_t_fingerprint"]].copy()
        p["rank"]=reference.raw_rank;p["score"]=41-reference.raw_rank;p["candidate_id"]=role
        take=reference.signal_date.dt.year.ge(2024) if role=="C14_G1" else pd.Series(True,index=p.index)
        p.loc[take & reference.raw_rank.eq(20),"rank"]=21
        p.loc[take & reference.raw_rank.eq(21),"rank"]=20
        panels[role]=p
    return days,clock,reference,panels


def test_membership_reuses_frozen_owner_and_keeps732_classical482_progressive(boundary,full_inputs,monkeypatch):
    days,clock,reference,panels=full_inputs
    monkeypatch.setattr(s,"_project",lambda ref,*a,**k:panels[ref["role"]].copy())
    assembly=dict(panels={r:dict(role=r) for r in panels})
    edges,actual,daily=s.new_memberships(boundary["d"],assembly,boundary["gate"],list(panels),reference,clock)
    assert len(edges["C14_D01"])==732 and len(edges["C14_G1"])==482
    assert set(edges["C14_G1"].index.year)=={2024,2025}
    assert len(daily)==752*2 and daily.loc[daily.signal_date.isin(days[732:]),"replacement_edge"].isna().all()
    assert daily.loc[daily.candidate_id.eq("C14_G1") & daily.year.eq(2023),"replacement_count"].eq(0).all()


def test_h5_keys_freeze_only_full732_raw_and_chosen_union(full_inputs):
    days,clock,reference,panels=full_inputs
    keys=s.h5_keys(reference,panels,clock)
    assert keys.signal_date.nunique()==732 and len(keys)==732*21
    assert not keys.signal_date.isin(days[732:]).any() and not keys.duplicated(s.KEYS).any()


def test_h5_gate_contains_exact_terminal_refs_and_key_fingerprint(boundary,full_inputs):
    _,clock,reference,panels=full_inputs
    keys=s.h5_keys(reference,panels,clock)
    gate=s.h5_decision_gate(boundary["dref"],boundary["rref"],boundary["term"],keys)
    assert gate["requested_keys_sha256"]==s.outcomes.content_hash(keys)
    assert gate["full_calendar_count"]==752 and gate["mature_count"]==732 and gate["progressive_mature_count"]==482
    assert gate["risk_delta_ref"]==boundary["term"]["delta"] and gate["outcome_reads_before_gate"]==0


def test_retained_contrast_reads_only_exact_required_endpoint482(full_inputs,monkeypatch):
    _,clock,_,_=full_inputs;_,_,index=s.ev._clock(clock);index=index[index.year>=2024]
    edge=pd.Series(.02,index=index)
    pre=dict(summaries=[dict(candidate_id=r,status="COMPLETE" if r=="C14_P01" else "FAILED_UNTESTABLE") for r in s.ev.ROLES])
    calls=[]
    def reader(ref,cols,**kwargs):
        calls.append((cols,kwargs["dates"]))
        return pd.DataFrame(dict(signal_date=index,C14_P01=.01))
    monkeypatch.setattr(s,"_project",reader)
    edges,ends=s.matched_additions({"C14_G1":edge},pre,clock,dict(diagnostics={"PRIMARY_DAILY_EDGE":{}}))
    assert set(ends)=={"C14_P01"} and set(edges)=={"C14_G1","C14_INC_G1"}
    assert edges["C14_INC_G1"].eq(.01).all()
    assert calls[0][0]==["signal_date","C14_P01"] and calls[0][1].equals(index)


def test_classical_and_gate_never_fabricate_native_pair_calibration(monkeypatch,full_inputs):
    monkeypatch.setattr(s.ctl,"label_pairs",lambda *a,**k:pytest.fail("NO_CLASSICAL_OR_GATE_PAIR_LABELS"))
    result=s.new_pair_diagnostics(s.RUN,{}, {},{}, {},["C14_D01","C14_G1"],full_inputs[1],{})
    assert all(frame.empty for frame in result[:3]) and result[3] is None


@pytest.mark.parametrize("bad_day",[False,True])
def test_frozen_pure_h5_owner_requires_all732_and_preserves_original_code(full_inputs,monkeypatch,bad_day):
    days,clock,reference,panels=full_inputs
    ref=reference.loc[reference.signal_date.isin(days[:732]),s.KEYS].copy()
    ref["return_value"]=.01;ref["qualified"]=True
    ref["label_coordinate"]=s.ev.risk_metrics.H5_COORDINATE
    if bad_day:ref.loc[ref.signal_date.eq(days[10]),"qualified"]=False
    owner=s.ev.risk_metrics;before=dict(owner.risk_diagnostics.__globals__)
    real=s.bind_pinned_kernel;clones=[]
    def bind(fn,**kwargs):
        assert fn is owner.risk_diagnostics and set(kwargs["dependencies"])=={"ACTIVE_ROLES"}
        clone=real(fn,**kwargs);assert clone.__code__ is fn.__code__;clones.append(clone);return clone
    monkeypatch.setattr(s,"bind_pinned_kernel",bind)
    review=dict(source_pins={str(Path(owner.__file__).resolve()):s.outcomes.binding.sha(owner.__file__)})
    inputs,blocked,daily,summary=s.risk_inputs(reference,{"C14_D01":panels["C14_D01"]},
        clock,ref,dict(status="PASS",test2026_reads=0),{},review)
    assert len(daily)==752 and len(clones)==1
    if bad_day:assert not inputs and blocked=={"C14_D01":"BLOCKED_FULL732_NATIVE_H5_UNION_QUALIFICATION"}
    else:
        assert len(inputs["C14_D01"]["raw"])==732 and not blocked
        assert inputs["C14_D01"]["qualification"]["predicted_risk_decreased"] is False
        assert inputs["C14_D01"]["qualification"]["predicted_diagnostic_status"]=="PREDICTED_DIAGNOSTIC_UNAVAILABLE"
    after=owner.risk_diagnostics.__globals__
    assert set(before)==set(after) and all(before[k]is after[k] for k in before)


def test_report_discloses_scope_no_old_bootstrap_no_account_claim():
    text=s.render_report(dict(status="SYNTHETIC_ONLY",tests=[],risk_tests=[],training_coverage_audit=[]))
    for token in ("旧147/75","482","732","5000","321","MEAN_ER","shareholder H5",
                  "Raw fallback","strict_PIT_promotion_eligible=false","账户净赚","DELTA8"):
        assert token in text


def test_h5_reader_full_owner_closure_is_required():
    pins=s.required_sources()
    for owner in (s.outcomes.owner,s.outcomes.owner.owner,s.outcomes.owner.identity_owner,s.outcomes.owner.namespace_owner):
        assert pins[str(Path(owner.__file__).resolve())]==s.outcomes.binding.sha(owner.__file__)


@pytest.mark.parametrize("defect",["omitted","assembly_omitted","adapter"])
def test_every_complete_new_endpoint_and_exact_adapter_must_be_bound(boundary,defect):
    if defect=="omitted":
        boundary["term"]["complete_conditional_roles"]=[];rebind(boundary,"term")
    elif defect=="assembly_omitted":
        boundary["assembly"]["complete_candidates"].remove("C14_G1");rebind(boundary,"assembly")
    else:
        boundary["review"]["adapter_sha256"]="0"*64;rebind(boundary,"review")
    with pytest.raises(ValueError): call_gate(boundary)
    assert not boundary["calls"]


@pytest.mark.parametrize("defect",["future_mask","bad_footer","missing_mask"])
def test_project_rejects_before_numeric_table_body(monkeypatch,defect):
    events=[]
    monkeypatch.setattr(s.ctl,"pin",lambda ref:events.append("pin") or Path("D:/SYNTHETIC_ONLY.parquet"))
    def footer(ref):
        events.append("footer")
        if defect=="bad_footer": raise ValueError("PHYSICAL_PRE2026_REQUIRED")
    monkeypatch.setattr(s.ctl,"footer",footer)
    monkeypatch.setattr(s.pq,"read_table",lambda *a,**k:pytest.fail("NUMERIC_BODY_MUST_NOT_BE_READ"))
    if defect=="missing_mask":
        with pytest.raises(TypeError):s._project({},["signal_date","value"])
    else:
        dates=pd.DatetimeIndex(["2026-01-02" if defect=="future_mask" else "2025-12-10"])
        with pytest.raises(ValueError):s._project({},["signal_date","value"],dates=dates)
    assert events==(["pin","footer"] if defect=="bad_footer" else [])


def test_project_footer_precedes_exact_date_and_column_predicate(monkeypatch):
    import pyarrow as pa
    events=[];dates=pd.DatetimeIndex(["2025-12-10","2025-12-11"])
    monkeypatch.setattr(s.ctl,"pin",lambda ref:events.append("pin") or Path("D:/SYNTHETIC_ONLY.parquet"))
    monkeypatch.setattr(s.ctl,"footer",lambda ref:events.append("footer"))
    def read(path,**kwargs):
        assert events==["pin","footer"]
        assert kwargs==dict(columns=["signal_date","value"],filters=[("signal_date","in",list(dates))])
        events.append("numeric")
        return pa.Table.from_pandas(pd.DataFrame(dict(signal_date=dates,value=[1.,2.])),preserve_index=False)
    monkeypatch.setattr(s.pq,"read_table",read)
    frame=s._project({},["signal_date","value"],dates=dates)
    assert len(frame)==2 and events==["pin","footer","numeric","pin"]


def test_only_physically_empty_matching_can_bypass_nonempty_clock_footer(monkeypatch):
    from types import SimpleNamespace
    import pyarrow as pa
    columns=[*s.ctl.PAIR_KEYS,"predicted_edge"]
    dates=pd.DatetimeIndex(["2025-12-10"])
    empty=pd.DataFrame({k:pd.Series(dtype="datetime64[ns]" if k=="signal_date" else "float64" if k=="predicted_edge" else "object") for k in columns})
    monkeypatch.setattr(s.ctl,"pin",lambda ref:Path("D:/SYNTHETIC_EMPTY_MATCH.parquet"))
    monkeypatch.setattr(s.pq,"ParquetFile",lambda path:SimpleNamespace(metadata=SimpleNamespace(num_rows=0),schema_arrow=SimpleNamespace(names=columns)))
    monkeypatch.setattr(s.ctl,"footer",lambda ref:pytest.fail("EMPTY_HAS_NO_NUMERIC_CLOCK"))
    calls=[]
    def read(path,**kwargs):
        calls.append(kwargs);return pa.Table.from_pandas(empty,preserve_index=False)
    monkeypatch.setattr(s.pq,"read_table",read)
    result=s._project({},columns,dates=dates,allow_empty=True)
    assert result.empty and calls[0]["filters"]==[("signal_date","in",list(dates))]


def synthetic_journal(boundary,monkeypatch,*,status="UNRESERVED",entered=0,charged=0):
    from types import SimpleNamespace
    slots={str(i):dict(candidate_id="C14_RX1",status="UNRESERVED",entered=0) for i in range(144)}
    slots["0"].update(status=status,entered=entered)
    journal=SimpleNamespace(slots=slots,requests={str(i):{} for i in range(charged)},verify=lambda:None,
        counts=lambda:dict(original_fit_slots=656,conditional_reserved=sum(r["status"]!="UNRESERVED" for r in slots.values()),
            combined_fit_slots=656+sum(r["status"]!="UNRESERVED" for r in slots.values()),
            original_charged_solves=18006,conditional_charged=charged,combined_charged_solves=18006+charged,
            scientific_retry=0,failed_reservation_refund=False))
    monkeypatch.setattr(s.transport,"RiskJournal",lambda run:journal)
    original=Path.exists
    delta=Path(boundary["term"]["delta"]["path"])
    monkeypatch.setattr(Path,"exists",lambda p:True if p==delta else original(p))
    return journal


@pytest.mark.parametrize("defect",["STARTED","RESERVED","reserved","entered","charged"])
def test_actual_delta_must_be_terminal_and_exact_before_first_numeric(boundary,monkeypatch,defect):
    journal=synthetic_journal(boundary,monkeypatch,
        status=defect if defect in ("STARTED","RESERVED") else "FAILED" if defect=="reserved" else "UNRESERVED",
        entered=1 if defect=="entered" else 0,charged=1 if defect=="charged" else 0)
    with pytest.raises(ValueError):
        s.deliver(boundary["run"],boundary["tref"],boundary["rref"],boundary["pref"],boundary["lref"])
    assert not boundary["calls"]


def test_unreserved_nodes_remain_explicit_and_all12_coverage_dimensions(boundary,monkeypatch):
    synthetic_journal(boundary,monkeypatch)
    original=s._read
    def read(ref,**kwargs):
        if ref==boundary["review"]["immutable_inputs"]["FIT_LEDGER.json"]:
            return dict(slots={str(i):dict(candidate_id="C14_P01",status="COMPLETE",entered=1) for i in range(656)})
        return original(ref,**kwargs)
    monkeypatch.setattr(s,"_read",read)
    design=dict(boundary["d"],coverage_plan={dim:dict(planned=["SYNTHETIC_ONLY"],role_members={})
        for dim in s.ev.COVERAGE_DIMENSIONS})
    audit,counts=s.coverage_and_counts(design,boundary["gate"],boundary["term"],boundary["review"])
    assert len(audit)==12 and counts["conditional_reserved"]==0 and counts["combined_fit_slots"]==656
    assert counts["scientific_retry"]==0 and counts["failed_reservation_refund"] is False


def test_missing_delta_never_creates_new_journal(boundary,monkeypatch):
    original=Path.exists;delta=Path(boundary["term"]["delta"]["path"])
    monkeypatch.setattr(Path,"exists",lambda p:False if p==delta else original(p))
    monkeypatch.setattr(s.transport,"RiskJournal",lambda run:pytest.fail("NO_HEADER_WRITE"))
    with pytest.raises(ValueError,match="EXISTING_DELTA_RESTORE_ONLY"):
        s.coverage_and_counts(boundary["d"],boundary["gate"],boundary["term"],boundary["review"])


def test_saved_native_variance_uses752_classical502_gate_and_never2023_gate(full_inputs,monkeypatch):
    days,clock,_,_=full_inputs;calls=[]
    def project(ref,columns,*,dates,**kwargs):
        calls.append((ref["role"],pd.DatetimeIndex(dates)))
        return pd.DataFrame(dict(signal_date=dates,predicted_variance_before=.02,predicted_variance_after=.01))
    monkeypatch.setattr(s,"_project",project)
    refs={r:dict(role=r) for r in ("C14_D01","C14_G1")}
    frames,summary=s.saved_variance_diagnostics(dict(predicted_risk=refs,variance_diagnostics=refs),
        ["C14_D01","C14_G1","C14_D02","C14_RX1"],clock)
    assert len(frames["C14_D01"])==752 and len(frames["C14_G1"])==502
    assert calls[1][1].year.min()==2024
    g2023=next(r for r in summary if r["candidate_id"]=="C14_G1" and r.get("year")=="2023")
    assert g2023["prediction_dates"]==g2023["mature_dates"]==0
    assert g2023["predicted_variance_before_mean"] is None and not g2023["formal_risk_efficiency_eligible"]
    pooled={r["candidate_id"]:r for r in summary if r.get("year")=="POOLED"}
    assert pooled["C14_G1"]["mature_dates"]==482 and pooled["C14_D01"]["mature_dates"]==732
    assert next(r for r in summary if r["candidate_id"]=="C14_D02")["native_risk_estimates"]==0
    assert next(r for r in summary if r["candidate_id"]=="C14_RX1")["status"]=="PREDICTED_DIAGNOSTIC_UNAVAILABLE"


@pytest.mark.parametrize("defect",["missing_date","changed_ref","negative"])
def test_bad_saved_native_variance_is_not_padded_or_substituted(full_inputs,monkeypatch,defect):
    _,clock,_,_=full_inputs
    def project(ref,columns,*,dates,**kwargs):
        dates=dates[:-1] if defect=="missing_date" else dates
        return pd.DataFrame(dict(signal_date=dates,predicted_variance_before=.02,predicted_variance_after=-.01 if defect=="negative" else .01))
    monkeypatch.setattr(s,"_project",project)
    assembly=dict(predicted_risk={"C14_D01":{"role":"C14_D01"}},variance_diagnostics={"C14_D01":{"role":"C14_D01"}})
    if defect=="changed_ref":assembly["variance_diagnostics"]["C14_D01"]={"role":"OTHER"}
    with pytest.raises(ValueError):s.saved_variance_diagnostics(assembly,["C14_D01"],clock)


def test_saved_variance_reaches_h5_summary_and_formal_criterion_without_covariance_read(full_inputs):
    days,clock,reference,panels=full_inputs
    h5=reference.loc[reference.signal_date.isin(days[:732]),s.KEYS].copy()
    h5["return_value"]=.01;h5["qualified"]=True;h5["label_coordinate"]=s.ev.risk_metrics.H5_COORDINATE
    saved={"C14_D01":pd.DataFrame(dict(predicted_variance_before=.02,predicted_variance_after=.01),index=days)}
    review=dict(source_pins={str(Path(s.ev.risk_metrics.__file__).resolve()):s.outcomes.binding.sha(s.ev.risk_metrics.__file__)})
    inputs,blocked,daily,summary=s.risk_inputs(reference,{"C14_D01":panels["C14_D01"]},
        clock,h5,dict(status="PASS"),{},review,saved_variance=saved)
    assert not blocked and inputs["C14_D01"]["qualification"]["predicted_risk_decreased"] is True
    assert daily.prediction_status.eq("COMPLETE_SAVED_NATIVE_VARIANCE").all()
    pooled=next(r for r in summary if r["year"]=="POOLED")
    assert pooled["valid_predicted_risk_dates"]==752 and pooled["prediction_status"]=="COMPLETE_ORIGINAL_SAVED_VARIANCE"
    assert pooled["predicted_variance_mean"]==pytest.approx(.01)


def test_descriptive_summary_contains_new_regret_calibration_rank_refs_without_null_fill():
    daily=pd.DataFrame([dict(candidate_id="C14_RX1",year=2024,replacement_edge=.001,raw_overlap=19,
        replacement_count=1,membership_turnover=None,challenger_raw_rank_mean=21,incumbent_raw_rank_mean=20)])
    pairs=pd.DataFrame([dict(candidate_id="C14_RX1",year=2024,pair_regret=.1,matching_utility=.01,
        oracle_matching_utility=.02,matching_regret=.01,replacement_count=1,wrong_replacement_count=0,
        correct_replacement_count=1,sign_accuracy=.6,mean_absolute_edge_error=.2)])
    ranks=pd.DataFrame([dict(candidate_id="C14_RX1",side="challenger",raw_rank=21)])
    refs={"NEW_PAIR_CALIBRATION":{"path":"SYNTHETIC_ONLY","sha256":"a"*64}}
    result=s.diagnostic_summary(daily,pairs,pd.DataFrame([{}]),ranks,refs,["C14_RX1","C14_G1"],[])
    assert result["pair_and_matching"][0]["matching_regret"]==.01
    assert result["membership"][0]["membership_turnover"] is None
    assert result["calibration_ref"]==refs["NEW_PAIR_CALIBRATION"] and result["calibration_rows"]==1
    assert result["pair_availability"]["C14_G1"]=="NOT_APPLICABLE_NO_NATIVE_PAIR_PREDICTIONS"
    assert result["replacement_rank_distribution"][0]["replacements"]==1
    json.dumps(result,allow_nan=False)



@pytest.fixture
def statistics_memory(boundary,full_inputs,monkeypatch):
    root=boundary["run"]/"risk_execution"/s.ROOT_NAME
    documents={};frames={};events=[]
    def digest(path):
        path=Path(path)
        if path in documents:
            return hashlib.sha256(json.dumps(documents[path],sort_keys=True,allow_nan=False).encode()).hexdigest()
        if path in frames:return s.incremental.content_hash(frames[path])
        raise ValueError("MISSING_SYNTHETIC_CACHE_ARTIFACT")
    def ref(path):return dict(path=str(path),sha256=digest(path))
    def read(reference,**kwargs):
        path=Path(reference["path"])
        if reference["sha256"]!=digest(path):raise ValueError("PHYSICAL_SYNTHETIC_CACHE_PIN_CHANGED")
        return deepcopy(documents[path])
    def put(path,obj,**kwargs):
        path=Path(path);events.append("put:"+path.name)
        assert path.is_relative_to(root)
        if path in documents:assert documents[path]==obj
        documents[path]=deepcopy(obj)
    def table(path,frame):
        path=Path(path);events.append("table:"+path.name)
        assert path.is_relative_to(root)
        if path in frames:assert frames[path].equals(frame)
        frames[path]=frame.copy(deep=True)
        return ref(path)
    def project(reference,columns):
        path=Path(reference["path"])
        if reference["sha256"]!=digest(path):raise ValueError("PHYSICAL_SYNTHETIC_MAXIMA_PIN_CHANGED")
        assert columns==("max_t",)
        return frames[path].copy(deep=True)
    original_exists=Path.exists
    monkeypatch.setattr(Path,"exists",lambda p:(p in documents or p in frames) if p.is_relative_to(root) else original_exists(p))
    monkeypatch.setattr(s,"_ref",ref);monkeypatch.setattr(s,"_read",read)
    monkeypatch.setattr(s.writer,"put",put);monkeypatch.setattr(s.writer,"table",table)
    monkeypatch.setattr(s.precomputed,"_project",project)
    design=deepcopy(boundary["d"]);maxima=np.linspace(0.,1.,5000)
    pre=dict(maxima=maxima,immutable_published_content="SYNTHETIC_ONLY")
    rows=[dict(spec,status="FAILED_UNTESTABLE",failure_reason="SYNTHETIC_NO_NEW_NUMERIC")
          for spec in design["evaluation"]["new_specs"]]
    legacy=[dict(candidate_id=cid,pooled_edge=.01,bootstrap_se=.002,year_edges={"2023":.01,"2024":.01,"2025":.01})
        for cid in design["evaluation"]["legacy"]["numeric_ids"]]
    updated=maxima+.1
    bootstrap=dict(status="COMPLETE",repeats=5000,exposure_namespace=321,
        strict_PIT_promotion_eligible=False,independent_holdout=False,
        old147_bootstrap_calls=0,old_ml_bootstrap_calls=0,
        incremental_precomputed_sha256=s.incremental.content_hash(pre),
        critical_max_t=float(np.quantile(updated,.95,method="higher")),
        risk_tests=[dict(spec,status="FAILED_UNTESTABLE") for spec in s.ev.RISK_SPECS])
    calls=[]
    def compute(*args,**kwargs):
        calls.append("NEW_STATISTICS_ONCE");events.append("compute")
        return deepcopy(rows),deepcopy(bootstrap),updated.copy(),deepcopy(legacy)
    monkeypatch.setattr(s.incremental,"incremental_statistics",compute)
    kwargs=dict(terminal_ref=deepcopy(boundary["tref"]),source_review_ref=deepcopy(boundary["rref"]),
        precomputed_review_ref=deepcopy(boundary["pref"]),legacy_summary_ref=deepcopy(boundary["lref"]),
        pre=pre,clock=full_inputs[1].copy(),custody={"expected_precomputed_sha256":s.incremental.content_hash(pre)},
        edges={},endpoints={},risk={},failures={},design=design,
        gate=deepcopy(boundary["gate"]),assembly=deepcopy(boundary["assembly"]))
    return dict(root=root,documents=documents,frames=frames,events=events,kwargs=kwargs,
        calls=calls,updated=updated,compute=compute)


def cached_statistics(memory,**updates):
    return s.statistics_once(memory["root"],**{**memory["kwargs"],**updates})


def test_statistics_commit_is_immediate_and_report_repair_exactly_reuses_without_bootstrap(statistics_memory,monkeypatch):
    memory=statistics_memory
    first=cached_statistics(memory)
    assert memory["events"][:5]==["put:JOINT_STATISTICS_STARTED_R1.json","compute",
        "put:JOINT_STATISTICS_VALUES_R1.json","table:JOINT_STATISTICS_MAXIMA_R1.parquet",
        "put:JOINT_STATISTICS_COMPLETE_R1.json"]
    # A later report failure leaves the complete statistical cache reusable.
    first[0][0]["failure_reason"]="MUTATED_CALLER_COPY"
    monkeypatch.setattr(s.incremental,"incremental_statistics",lambda *a,**k:pytest.fail("NO_REBOOTSTRAP"))
    second=cached_statistics(memory)
    np.testing.assert_array_equal(second[2],memory["updated"])
    assert second[0][0]["failure_reason"]=="SYNTHETIC_NO_NEW_NUMERIC"
    assert second[4]==first[4] and memory["calls"]==["NEW_STATISTICS_ONCE"]


@pytest.mark.parametrize("defect",["terminal","source_review","precomputed_review","legacy_ref","precomputed_pin",
    "fixed_edges","risk_qualification","values_pin","maxima_pin","complete_content","missing_maxima","missing_started"])
def test_statistics_complete_cache_rejects_any_changed_pin_or_lineage_without_recompute(statistics_memory,monkeypatch,defect):
    memory=statistics_memory;cached_statistics(memory)
    kwargs=deepcopy(memory["kwargs"])
    if defect in ("terminal","source_review","precomputed_review","legacy_ref"):
        name={"terminal":"terminal_ref","source_review":"source_review_ref","precomputed_review":"precomputed_review_ref","legacy_ref":"legacy_summary_ref"}[defect]
        kwargs[name]["sha256"]="0"*64
    elif defect=="precomputed_pin":kwargs["custody"]["expected_precomputed_sha256"]="0"*64
    elif defect=="fixed_edges":kwargs["edges"]={"C14_D01":pd.Series(.01,index=memory["kwargs"]["clock"].signal_date[:732])}
    elif defect=="risk_qualification":kwargs["risk"]={"C14_D01":{"qualification":{"status":"CHANGED"}}}
    elif defect=="values_pin":memory["documents"][memory["root"]/"JOINT_STATISTICS_VALUES_R1.json"]["tests"][0]["status"]="CHANGED"
    elif defect=="maxima_pin":memory["frames"][memory["root"]/"JOINT_STATISTICS_MAXIMA_R1.parquet"].loc[0,"max_t"]+=1
    elif defect=="complete_content":memory["documents"][memory["root"]/"JOINT_STATISTICS_COMPLETE_R1.json"]["output_content_sha256"]="0"*64
    elif defect=="missing_maxima":memory["frames"].pop(memory["root"]/"JOINT_STATISTICS_MAXIMA_R1.parquet")
    else:memory["documents"].pop(memory["root"]/"JOINT_STATISTICS_STARTED_R1.json")
    monkeypatch.setattr(s.incremental,"incremental_statistics",lambda *a,**k:pytest.fail("CACHE_FAILURE_MUST_NOT_REBOOTSTRAP"))
    with pytest.raises(ValueError):s.statistics_once(memory["root"],**kwargs)
    assert len(memory["calls"])==1


def test_started_without_complete_cache_cannot_retry_new_statistics(statistics_memory,monkeypatch):
    memory=statistics_memory
    def failed(*a,**k):
        memory["calls"].append("FAILED_ATTEMPT");raise RuntimeError("SYNTHETIC_NEW_STATISTICS_FAILURE")
    monkeypatch.setattr(s.incremental,"incremental_statistics",failed)
    with pytest.raises(RuntimeError):cached_statistics(memory)
    assert memory["root"]/"JOINT_STATISTICS_STARTED_R1.json" in memory["documents"]
    assert memory["root"]/"JOINT_STATISTICS_COMPLETE_R1.json" not in memory["documents"]
    monkeypatch.setattr(s.incremental,"incremental_statistics",lambda *a,**k:pytest.fail("FAILED_ATTEMPT_RETRY_FORBIDDEN"))
    with pytest.raises(ValueError,match="NO_AUTOMATIC_REBOOTSTRAP"):cached_statistics(memory)
    assert memory["calls"]==["FAILED_ATTEMPT"]


def test_partial_poststatistics_cache_cannot_be_treated_as_complete_or_rebootstrapped(statistics_memory,monkeypatch):
    memory=statistics_memory
    monkeypatch.setattr(s.writer,"table",lambda *a,**k:(_ for _ in ()).throw(RuntimeError("SYNTHETIC_MAXIMA_WRITE_FAILURE")))
    with pytest.raises(RuntimeError):cached_statistics(memory)
    assert memory["root"]/"JOINT_STATISTICS_VALUES_R1.json" in memory["documents"]
    monkeypatch.setattr(s.incremental,"incremental_statistics",lambda *a,**k:pytest.fail("PARTIAL_CACHE_REBOOTSTRAP_FORBIDDEN"))
    with pytest.raises(ValueError,match="NO_AUTOMATIC_REBOOTSTRAP"):cached_statistics(memory)
    assert memory["calls"]==["NEW_STATISTICS_ONCE"]



@pytest.mark.parametrize("defect",["assembly_hash","assembly_path","delivery_review","execution_review","physical"])
def test_original_ml_assembly_is_independently_pinned_before_any_numeric(boundary,monkeypatch,defect):
    if defect=="assembly_hash":
        boundary["assembly"]["original_ml_assembly_ref"]["sha256"]="0"*64;rebind(boundary,"assembly")
    elif defect=="assembly_path":
        boundary["assembly"]["original_ml_assembly_ref"]["path"]=str(boundary["run"]/"OTHER_ML_ASSEMBLY.json");rebind(boundary,"assembly")
    elif defect=="delivery_review":
        boundary["review"]["immutable_inputs"]["ML_ASSEMBLY.json"]["sha256"]="0"*64;rebind(boundary,"review")
    elif defect=="execution_review":
        boundary["term"]["review_ref"]=boundary["add"]("SYNTHETIC_WRONG_EXECUTION_REVIEW.json",
            dict(status="PASS",research_id=s.ID,immutable_inputs={"ML_ASSEMBLY.json":{"path":str(boundary["run"]/"ML_ASSEMBLY.json"),"sha256":"0"*64}}))
        rebind(boundary,"term")
    else:
        original=s.ctl.pin
        def pin(ref):
            if Path(ref["path"]).name=="ML_ASSEMBLY.json":raise ValueError("SYNTHETIC_PHYSICAL_ML_ASSEMBLY_CHANGED")
            return original(ref)
        monkeypatch.setattr(s.ctl,"pin",pin)
    with pytest.raises(ValueError):
        s.deliver(boundary["run"],boundary["tref"],boundary["rref"],boundary["pref"],boundary["lref"])
    assert not boundary["calls"]


@pytest.fixture
def post_boundary(boundary,monkeypatch):
    b=boundary;run=b["run"];root=run/"risk_execution"/s.POST_REBOOT_ROOT_NAME
    monkeypatch.setattr(s,"RESULTS",run/"SYNTHETIC_RESULTS")
    backups={};priors={}
    for relative,(name,_) in s.PRIOR_DELIVERY_SOURCES.items():
        ref=b["add"]("source_corrections/C14_POST_REBOOT_JOINT_DELIVERY_R1/"+name,{})
        backups[str((s.ctl.REPO/relative).resolve())]=ref;priors[relative]=(name,ref["sha256"])
    monkeypatch.setattr(s,"PRIOR_DELIVERY_SOURCES",priors)
    for key,name,const in (("old_report","FINAL_REPORT.md","OLD_ML_REPORT_SHA"),
            ("old_ml_audit","ML_DELIVERY_AUDIT.md","OLD_ML_AUDIT_SHA")):
        ref=b["add"]("SYNTHETIC_RESULTS/"+name,{})
        b["review"]["immutable_inputs"][key]=ref;monkeypatch.setattr(s,const,ref["sha256"])
    b["review"]["source_pins"][str((s.ctl.REPO/"tests/research/a2/evaluation/test_selector_maximal_risk_delivery.py").resolve())]=s.outcomes.binding.sha(
        s.ctl.REPO/"tests/research/a2/evaluation/test_selector_maximal_risk_delivery.py")
    declared={}
    for role in s.REUSED_CLASSICAL:
        refs={field:b["add"]("risk_execution/source_metadata_recovery_r1/"+role+"/"+name,{})
            for field,name in (("panels","scores_pre2026.parquet"),("predicted_risk","predicted_risk_pre2026.parquet"))}
        refs["variance_diagnostics"]=deepcopy(refs["predicted_risk"]);declared[role]=refs
        for field,ref in refs.items():b["assembly"].setdefault(field,{})[role]=deepcopy(ref)
    for role in s.transport.ACTIVE_RX:
        refs={key:b["add"]("risk_execution/"+s.POST_REBOOT_ROOT_NAME+"/"+role+"/"+name,{})
            for key,name in dict(assembly="HYBRID_ASSEMBLY.json",panel="scores_pre2026.parquet",
                native_pairs="native_pairs_pre2026.parquet",matching="matching_pre2026.parquet").items()}
        declared[role]=refs;b["assembly"]["panels"][role]=deepcopy(refs["panel"])
        b["assembly"]["native_pair_predictions"][role]={**refs["native_pairs"],
            "matching_path":refs["matching"]["path"],"matching_sha256":refs["matching"]["sha256"]}
    for role in s.REMAINING_CLASSICAL:
        b["assembly"]["panels"][role]=b["add"]("risk_execution/"+s.POST_REBOOT_ROOT_NAME+"/"+role+"/scores_pre2026.parquet",{})
        risk=b["add"]("risk_execution/"+s.POST_REBOOT_ROOT_NAME+"/"+role+"/predicted_risk_pre2026.parquet",{})
        b["assembly"]["predicted_risk"][role]=risk;b["assembly"]["variance_diagnostics"][role]=deepcopy(risk)
    roles=[*s.REUSED_CLASSICAL,*s.transport.ACTIVE_RX,*s.REMAINING_CLASSICAL]
    b["term"]["complete_conditional_roles"]=roles
    b["assembly"]["complete_candidates"]=["C14_P01","C14_P09",*roles]
    for role in roles:
        b["gate"]["role_statuses"][role]="COMPLETE";b["assembly"]["role_statuses"][role]="COMPLETE"
        b["assembly"]["failed_or_untestable"].pop(role,None)
    qualification=b["add"]("risk_execution/source_metadata_recovery_r1/INPUT_QUALIFICATION_R1.json",{})
    monkeypatch.setitem(s.transport.SOURCE_GUARD_REFS,"qualification",
         ("risk_execution/source_metadata_recovery_r1/INPUT_QUALIFICATION_R1.json",qualification["sha256"]))
    b["term"]["input_qualification"]=qualification;b["assembly"]["input_qualification"]=deepcopy(qualification)
    checkpoint={key:None for key in s.transport.POST_REBOOT_FIELDS}
    checkpoint.update(status="PASS",research_id=s.ID,independent_review=True,scientific_contract_changed=False,
        remaining_classical_roles=list(s.REMAINING_CLASSICAL),input_qualification=qualification,
        runtime_source_review=b["term"]["review_ref"],
        checkpoint_delta=dict(path=str(run/"RISK_EXECUTION_DELTA.jsonl"),**s.transport.POST_REBOOT_PREFIX),
        completed_role_artifacts=declared,completed_fit_artifacts={"SYNTHETIC_FIT":{}},
        old_recovery_event={"SYNTHETIC_FIXED_EVENT":True},original_source_guard_review={"SYNTHETIC_OLD_REF":True},
        old_marker={"SYNTHETIC_OLD_MARKER":True},snapshot_transport={})
    cref=b["add"](s.transport.POST_REBOOT_REVIEW_NAME,checkpoint)
    marker=dict(status="STARTED_POST_REBOOT_CLASSICAL_ONLY_CHECKPOINT",research_id=s.ID,review=cref,
        runtime_source_review=checkpoint["runtime_source_review"],checkpoint_delta=checkpoint["checkpoint_delta"],
        old_marker=checkpoint["old_marker"],remaining_classical_roles=list(s.REMAINING_CLASSICAL),
        completed_fit_slots_reused=28,interrupted_worker_execution_input_counts="UNKNOWN_DUE_REBOOT",
        joint_delivery_completed=False,scientific_retry=0,test2026_rows_read=0)
    proof=dict(B_freeze=None,original_publication_admission=None,transported_code_refs={},
        original_reader_code_reused=True,original_binding_sha_global_unchanged=True,
        original_metadata_qualification_chain_reused=True,
        native_numeric_reads=0,label_reads=0,fit=0,solve=0,bootstrap=0)
    audit=dict(status="POST_REBOOT_CLASSICAL_ONLY_CHECKPOINT_TERMINAL",research_id=s.ID,review=cref,
        runtime_source_review=checkpoint["runtime_source_review"],checkpoint_delta=checkpoint["checkpoint_delta"],
        old_marker=checkpoint["old_marker"],original_source_guard_review=checkpoint["original_source_guard_review"],
        original_input_qualification=qualification,preserved_old_recovery_event=checkpoint["old_recovery_event"],
        reused_completed_artifacts=declared,reused_completed_fit_artifacts=checkpoint["completed_fit_artifacts"],
        original_complete_cache_counts=deepcopy(s.transport.POST_REBOOT_COUNTS),publication_source_transport=proof,
        RX_reopened=False,new_fit=0,coverage_sufficient_claim_allowed=False,joint_delivery_completed=False,
        interrupted_worker_execution_input_counts="UNKNOWN_DUE_REBOOT",scientific_retry=0,test2026_rows_read=0)
    b.update(checkpoint=checkpoint,cref=cref,marker=marker,audit=audit,post_root=root)
    b["review"].update(schema=s.POST_REBOOT_REVIEW_SCHEMA,classification="POST_REBOOT_JOINT_DELIVERY_ENGINEERING",
        independent_review=True,source_backups=backups)
    post_rebind(b)
    from types import SimpleNamespace
    owner=importlib.import_module("scripts.research.a2.evaluation.selector_maximal_risk_resume")
    monkeypatch.setattr(owner,"TRANSPORT",{})
    b["review"]["source_pins"].update(s.required_sources(include_post_reboot=True))
    b["rref"]=b["add"]("SYNTHETIC_DELIVERY_REVIEW.json",b["review"])
    monkeypatch.setattr(owner,"RUN",b["run"].resolve())
    monkeypatch.setattr(owner,"validate_transport",lambda custody:None)
    b["closure_events"]=[]
    def closure_guard(run,design):
        b["closure_events"].append("ALL_FROZEN_SOURCES")
        if b.get("broken_frozen_source"):raise ValueError("SYNTHETIC_OTHER_FROZEN_SOURCE_CHANGED")
        return {"SYNTHETIC_METADATA_ONLY":True}
    monkeypatch.setattr(s.ctl,"checked_sources",closure_guard)
    with owner.executable_snapshot_guard(SimpleNamespace(ctl=s.ctl),{},{}):
        yield b


def post_rebind(b):
    root="risk_execution/"+s.POST_REBOOT_ROOT_NAME+"/"
    b["term"]["assembly"]=b["add"](root+"SCORE_ASSEMBLY_R1.json",b["assembly"])
    b["gate"]["score_assembly_sha256"]=b["term"]["assembly"]["sha256"]
    b["term"]["final_pipeline"]=b["add"](root+"FINAL_PIPELINES_FREEZE_R1.json",b["gate"])
    b["tref"]=b["add"](root+s.TERMINAL_NAME,b["term"]);b["audit"]["terminal"]=deepcopy(b["tref"])
    aref=b["add"](root+s.POST_REBOOT_COMPLETE_NAME,b["audit"])
    mref=b["add"](root+s.POST_REBOOT_MARKER_NAME,b["marker"])
    b["review"]["delivery_inputs"].update(terminal=b["tref"],post_reboot_checkpoint=b["cref"],
        post_reboot_completion=aref,post_reboot_marker=mref)
    b["rref"]=b["add"]("SYNTHETIC_DELIVERY_REVIEW.json",b["review"])


def post_gate(b,**kwargs):
    return s.terminal_inputs(b["run"],b["tref"],b["rref"],b["pref"],b["lref"],
        post_reboot_checkpoint_ref=kwargs.get("checkpoint",b["cref"]))


def test_fixed_root2_receipts_and_root1_artifacts_accept_without_any_numeric(post_boundary):
    assert post_gate(post_boundary)[3]["complete_conditional_roles"]==post_boundary["term"]["complete_conditional_roles"]
    assert not post_boundary["calls"]


@pytest.mark.parametrize("defect",["oldroot","root1","descendant","foreign","mixed_assembly","mixed_final",
    "missing_checkpoint","changed_checkpoint","review_checkpoint","missing_completion","missing_marker",
    "marker_review","marker_runtime","marker_prefix","marker_old","audit_terminal","audit_event","audit_cache",
    "audit_runtime","audit_RX","audit_read_alias","audit_interrupted","qualification","assembly_qualification",
    "reused_artifact","rx_matching","new_classical_path","backup","source_test","report_pin","downgrade"])
def test_root2_any_changed_custody_refuses_before_numeric_or_writer(post_boundary,monkeypatch,defect):
    b=post_boundary;checkpoint=b["cref"]
    if defect in ("oldroot","root1","descendant","foreign"):
        relative={"oldroot":"risk_execution","root1":"risk_execution/source_metadata_recovery_r1",
            "descendant":"risk_execution/"+s.POST_REBOOT_ROOT_NAME+"/nested","foreign":"FOREIGN_ROOT"}[defect]
        b["tref"]=b["add"](relative+"/"+s.TERMINAL_NAME,b["term"])
        b["review"]["delivery_inputs"]["terminal"]=b["tref"]
    elif defect in ("mixed_assembly","mixed_final"):
        key="assembly" if defect=="mixed_assembly" else "final_pipeline"
        b["term"][key]=b["add"]("risk_execution/SYNTHETIC_MIXED.json",{})
        b["tref"]=b["add"]("risk_execution/"+s.POST_REBOOT_ROOT_NAME+"/"+s.TERMINAL_NAME,b["term"])
        b["review"]["delivery_inputs"]["terminal"]=b["tref"]
    elif defect=="missing_checkpoint":checkpoint=None
    elif defect=="changed_checkpoint":checkpoint={**checkpoint,"sha256":"0"*64}
    elif defect=="review_checkpoint":b["review"]["delivery_inputs"]["post_reboot_checkpoint"]={"path":"OTHER","sha256":"0"*64}
    elif defect.startswith("missing_"):b["review"]["delivery_inputs"].pop("post_reboot_"+defect[8:])
    elif defect.startswith("marker_"):
        field={"marker_review":"review","marker_runtime":"runtime_source_review","marker_prefix":"checkpoint_delta",
            "marker_old":"old_marker"}[defect];b["marker"][field]={"CHANGED":True};post_rebind(b)
    elif defect.startswith("audit_"):
        key={"audit_terminal":"terminal","audit_event":"preserved_old_recovery_event","audit_cache":"original_complete_cache_counts",
             "audit_runtime":"runtime_source_review","audit_RX":"RX_reopened","audit_read_alias":"test2026_rows_read",
             "audit_interrupted":"interrupted_worker_execution_input_counts"}[defect]
        value=True if defect=="audit_RX" else False if defect=="audit_read_alias" else "FORGED"
        post_rebind(b);b["audit"][key]=value
        b["review"]["delivery_inputs"]["post_reboot_completion"]=b["add"](
            "risk_execution/"+s.POST_REBOOT_ROOT_NAME+"/"+s.POST_REBOOT_COMPLETE_NAME,b["audit"])
    elif defect=="qualification":b["term"]["input_qualification"]=b["add"]("risk_execution/SYNTHETIC_QUAL.json",{});post_rebind(b)
    elif defect=="assembly_qualification":b["assembly"]["input_qualification"]={};post_rebind(b)
    elif defect=="reused_artifact":b["assembly"]["panels"]["C14_D01"]=b["add"]("SYNTHETIC_OTHER_PANEL.parquet",{});post_rebind(b)
    elif defect=="rx_matching":b["assembly"]["native_pair_predictions"]["C14_RX_HGB_LW"]["matching_sha256"]="0"*64;post_rebind(b)
    elif defect=="new_classical_path":b["assembly"]["panels"]["C14_D09"]=b["add"]("risk_execution/source_metadata_recovery_r1/C14_D09/scores_pre2026.parquet",{});post_rebind(b)
    elif defect=="backup":b["review"]["source_backups"]={}
    elif defect=="source_test":b["review"]["source_pins"].pop(str((s.ctl.REPO/"tests/research/a2/evaluation/test_selector_maximal_risk_delivery.py").resolve()))
    elif defect=="report_pin":b["review"]["immutable_inputs"]["old_ml_audit"]={**b["review"]["immutable_inputs"]["old_ml_audit"],"sha256":"0"*64}
    elif defect=="downgrade":
        b["tref"]=b["add"]("risk_execution/"+s.TERMINAL_NAME,b["term"]);checkpoint=None
        b["review"]["delivery_inputs"]["terminal"]=b["tref"]
    b["rref"]=b["add"]("SYNTHETIC_DELIVERY_REVIEW.json",b["review"])
    monkeypatch.setattr(s.writer,"put",lambda *a,**k:pytest.fail("NO_WRITER_BEFORE_ADMISSION"))
    with pytest.raises((ValueError,AssertionError)):
        s.deliver(b["run"],b["tref"],b["rref"],b["pref"],b["lref"],post_reboot_checkpoint_ref=checkpoint)
    assert not b["calls"]


def test_post_journal_gets_explicit_formal_and_all_solves_must_close(boundary,monkeypatch):
    journal=synthetic_journal(boundary,monkeypatch,charged=1)
    boundary["term"].update(charged_solves=1,combined_charged_solves=18007)
    cref=boundary["add"]("SYNTHETIC_CHECKPOINT.json",{})
    boundary["review"]["delivery_inputs"]["post_reboot_checkpoint"]=cref
    calls=[]
    def construct(run,**kwargs):
        calls.append((run,kwargs));return journal
    monkeypatch.setattr(s.transport,"RiskJournal",construct)
    journal.requests["0"]={"status":"ENTERED"}
    with pytest.raises(ValueError,match="UNRESOLVED_CHARGED_SOLVE"):
        s.coverage_and_counts(boundary["d"],boundary["gate"],boundary["term"],boundary["review"],
            post_reboot_checkpoint_ref=cref)
    assert calls==[(boundary["run"],{"post_reboot_checkpoint_ref":cref})]
    journal.requests["0"]={"status":"FAILED"}
    old_read=s._read
    monkeypatch.setattr(s,"_read",lambda ref,**kw:{"slots":{}} if ref==boundary["review"]["immutable_inputs"]["FIT_LEDGER.json"] else old_read(ref,**kw))
    design=dict(boundary["d"],coverage_plan={dim:dict(planned=["SYNTHETIC_ONLY"],role_members={})
        for dim in s.ev.COVERAGE_DIMENSIONS})
    audit,counts=s.coverage_and_counts(design,boundary["gate"],boundary["term"],boundary["review"],
        post_reboot_checkpoint_ref=cref)
    assert counts["conditional_charged"]==1 and counts["failed_reservation_refund"] is False


@pytest.mark.parametrize("defect",["checkpoint","completion","unpaired"])
def test_statistics_complete_binds_new_checkpoint_and_completion_without_second_compute(statistics_memory,monkeypatch,defect):
    m=statistics_memory;extra=dict(post_reboot_checkpoint_ref={"path":"SYNTHETIC_C","sha256":"a"*64},
        post_reboot_completion_ref={"path":"SYNTHETIC_A","sha256":"b"*64})
    cached_statistics(m,**extra)
    if defect=="unpaired":extra["post_reboot_completion_ref"]=None
    else:extra["post_reboot_"+defect+"_ref"]["sha256"]="0"*64
    monkeypatch.setattr(s.incremental,"incremental_statistics",lambda *a,**k:pytest.fail("NO_SECOND_STATISTICS"))
    with pytest.raises(ValueError):cached_statistics(m,**extra)
    assert len(m["calls"])==1


def test_report_keeps_all_roles_failures_original_lower_and_exact_history_without_scientific_call(monkeypatch):
    monkeypatch.setattr(s.incremental,"incremental_statistics",lambda *a,**k:pytest.fail("REPORT_HAS_NO_STATISTICS"))
    roles=["C14_P01","C14_RX_HGB_LW","C14_D12","C14_DELTA_RIDGE"]
    original="SYNTHETIC ORIGINAL ML TABLE\nseed | capacity | OOF\n"
    payload=dict(status="SYNTHETIC",tests=[dict(candidate_id="C14_P01",simultaneous_lower_95=.2)],
        risk_tests=[],role_statuses=dict(zip(roles,["COMPLETE","COMPLETE","BLOCKED_BUDGET","BLOCKED_BUDGET"])),
        role_failure_details={"C14_D12":"BUDGET","C14_DELTA_RIDGE":"BUDGET"},
        design_metadata={"roles":roles},training_coverage_audit=[dict(dimension=dim,planned=1,actual=0,attempted=0,
            blocked={},uncovered=["UNAVAILABLE"],coverage=0.,measurement="SYNTHETIC_SCOPE") for dim in s.ev.COVERAGE_DIMENSIONS],
        published_c14_summaries=[dict(candidate_id="C14_P01",simultaneous_lower_95=.3)],
        retained_published_reports={"原ML审计":dict(source_ref={"path":"SYNTHETIC"},text=original)},
        execution_input_counts={"interrupted_worker_execution_input_counts":"UNKNOWN_DUE_REBOOT"})
    rendered=s.render_report(payload)
    assert all(role in rendered for role in roles) and all(dim in rendered for dim in s.ev.COVERAGE_DIMENSIONS)
    assert original in rendered and "原发布lower" in rendered and "联合lower" in rendered
    assert "0.3" in rendered and "0.2" in rendered and "UNKNOWN_DUE_REBOOT" in rendered
    assert "individual RC" in rendered and "H5" in rendered


def test_report_labels_original_return_details_and_bp_alpha_summary_without_rescaling_payload(monkeypatch):
    monkeypatch.setattr(s.incremental,"incremental_statistics",lambda *a,**k:pytest.fail("UNIT_RENDER_HAS_NO_STATISTICS"))
    row=dict(candidate_id="C14_P01",status="COMPLETE",pooled_edge=.001,bootstrap_se=.0001,
        simultaneous_lower_95=.001,year_edges={"2023":.001,"2024":.001,"2025":.001})
    payload=dict(status="SYNTHETIC_UNITS",tests=[deepcopy(row)],risk_tests=[],
        design_metadata={"roles":["C14_P01"]},role_statuses={"C14_P01":"COMPLETE"},
        published_c14_summaries=[deepcopy(row)],published_legacy_summaries=[{**row,"candidate_id":"HISTORICAL_ID"}],
        legacy_summaries=[{**row,"candidate_id":"HISTORICAL_ID"}],
        variance_summary=[dict(candidate_id="C14_D01",predicted_variance_before_mean=.002,
            predicted_variance_after_mean=.001,predicted_variance_difference_mean=-.001)],
        diagnostic_summary=dict(membership=[dict(candidate_id="C14_P01",replacement_edge=.001)],
            pair_and_matching=[dict(candidate_id="C14_P01",pair_regret=.001,matching_utility=.001,
                oracle_matching_utility=.001,matching_regret=.001,mean_absolute_edge_error=.001)]))
    before=deepcopy(payload);rendered=s.render_report(payload)
    details,alpha=rendered.split("# C14 Selector Maximal Breadth",1)
    for label in ("原发布lower(原return单位)","联合lower(原return单位)","原均值(原return单位)",
            "原SE(原return单位)","原year值(原return单位)","alpha edge(原return单位)",
            "pair regret(原return单位)","matching utility(原return单位)","原oracle(原return单位)",
            "matching regret(原return单位)","MAE(原return单位)","before方差(return²)","after方差(return²)","方差差(return²)"):
        assert label in details
    assert "| 0.001 |" in details and "| 10.0 |" in alpha
    assert "以下alpha汇总表edge/lower单位为bp；" in alpha
    assert "所有edge及lower bound单位为bp" not in rendered
    assert payload==before

def test_saved_coordinate_projection_uses_only_existing_before_after_and_keeps_null_singular(full_inputs,monkeypatch):
    _,clock,_,_=full_inputs;calls=[]
    before=dict(predicted_variance=.02,abs_rc_hhi=.1,condition_number=None,singular_covariance=True,status="COMPLETE",
        enb=10.,max_correlation=.2,max_abs_correlation=.3,diversification_ratio=1.2)
    after={**before,"predicted_variance":.01,"abs_rc_hhi":.08}
    def project(ref,columns,*,dates,**kwargs):
        calls.append(columns)
        return pd.DataFrame(dict(signal_date=dates,predicted_variance_before=.02,predicted_variance_after=.01,
            before=[before]*len(dates),after=[after]*len(dates)))
    monkeypatch.setattr(s,"_project",project)
    monkeypatch.setattr(s.ev.risk_metrics,"risk_coordinates",lambda *a,**k:pytest.fail("NO_COVARIANCE_RECOMPUTATION"))
    ref={"SYNTHETIC_ONLY":True}
    frames,summary=s.saved_variance_diagnostics(
        dict(predicted_risk={"C14_D01":ref},variance_diagnostics={"C14_D01":ref}),["C14_D01"],clock,
        include_saved_coordinates=True)
    pooled=next(row for row in summary if row["year"]=="POOLED")
    assert calls==[["signal_date","predicted_variance_before","predicted_variance_after","before","after"]]
    assert list(frames["C14_D01"].columns)==["predicted_variance_before","predicted_variance_after"]
    assert pooled["saved_coordinates_after"]["abs_rc_hhi"]==pytest.approx(.08)
    assert pooled["saved_coordinates_after"]["condition_number"] is None
    assert pooled["saved_coordinates_after"]["singular_dates"]==752
    assert pooled["individual_rc_vectors_available"] is False and pooled["new_covariance_estimation"] is False


@pytest.mark.parametrize("defect",["missing_module","live_file","function_code","missing_guard"])
def test_actual_executed_snapshot_origin_and_guard_cannot_be_replaced_by_metadata(post_boundary,monkeypatch,tmp_path,defect):
    import sys
    from types import SimpleNamespace
    owner=importlib.import_module("scripts.research.a2.evaluation.selector_maximal_risk_resume")
    name=owner.CA_NAME;path=tmp_path/"synthetic_canonical_source.py"
    path.write_text("def apply_transition_to_positions(): return None\ndef apply_entitlement_lifecycle(): return None\n",encoding="utf-8")
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module);parent=sys.modules[name.rpartition(".")[0]]
    monkeypatch.setitem(sys.modules,name,module);monkeypatch.setattr(parent,name.rpartition(".")[2],module,raising=False)
    monkeypatch.setattr(owner,"TRANSPORT",{name:("SYNTHETIC_ONLY",)})
    checkpoint={"snapshot_transport":{name:{"original_snapshot":{"path":str(path),"sha256":"a"*64}}}}
    s.post_reboot_execution_sources(checkpoint)
    if defect=="missing_module":monkeypatch.delitem(sys.modules,name)
    elif defect=="live_file":module.__file__=str(tmp_path/"live_source.py")
    elif defect=="function_code":
        namespace=module.__dict__;exec(compile("def apply_transition_to_positions(): return None\n",
             str(tmp_path/"live_function.py"),"exec"),namespace)
    else:monkeypatch.setattr(s.ctl,"checked_sources",lambda *a,**k:None)
    with pytest.raises(ValueError):s.post_reboot_execution_sources(checkpoint)


def test_changed_other_frozen_source_fails_before_first_numeric_even_with_correct_snapshot_context(post_boundary):
    b=post_boundary;b["broken_frozen_source"]=True
    with pytest.raises(ValueError,match="OTHER_FROZEN_SOURCE_CHANGED"):
        s.deliver(b["run"],b["tref"],b["rref"],b["pref"],b["lref"],post_reboot_checkpoint_ref=b["cref"])
    assert b["closure_events"]==["ALL_FROZEN_SOURCES"] and not b["calls"]
