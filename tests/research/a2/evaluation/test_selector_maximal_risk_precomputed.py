"""Only in-memory published scalar fixtures and 5000 synthetic maxima."""
from copy import deepcopy
from pathlib import Path
import hashlib
import importlib.util
import json
import numpy as np
import pandas as pd
import pyarrow as pa
import pytest
from scripts.research.a2.evaluation import selector_maximal_risk_precomputed as s


def design_fixture():
    path=Path(__file__).parents[1]/"data/test_selector_maximal_risk_outcomes.py"
    spec=importlib.util.spec_from_file_location("c14_precomputed_metadata_fixture",path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.c14_design()


@pytest.fixture
def bank(monkeypatch):
    # All artifact paths are virtual: Path.read_text and sha are mapped in memory.
    run=Path("D:/us-tech-quant-backtests/V24/SYNTHETIC_C14_PRECOMPUTED")
    base=Path("D:/us-tech-quant-backtests/V24/SYNTHETIC_PUBLISHED")
    monkeypatch.setattr(s,"RUN",run); monkeypatch.setattr(s,"BASE",base)
    original_sha=s.binding.sha; original_read=Path.read_text
    memory={}; frames={}; reads=[]; projections=[]
    def sha(path):
        p=str(Path(path).resolve())
        return hashlib.sha256(memory[p]).hexdigest() if p in memory else original_sha(path)
    def read(path,*a,**k):
        p=str(path.resolve())
        if p in memory:
            reads.append(p)
            return memory[p].decode("utf-8")
        raise AssertionError("REAL_ARTIFACT_JSON_READ_FORBIDDEN:"+p)
    monkeypatch.setattr(s.binding,"sha",sha)
    monkeypatch.setattr(Path,"read_text",read)
    def put(path,obj):
        p=str(path.resolve())
        memory[p]=json.dumps(obj,sort_keys=True,allow_nan=False).encode()
        return dict(path=str(path),sha256=sha(path))
    def pq_read(path,columns):
        p=str(Path(path).resolve()); projections.append((p,columns))
        assert p in frames, "REAL_PARQUET_READ_FORBIDDEN"
        return pa.Table.from_pandas(frames[p][columns],preserve_index=False)
    monkeypatch.setattr(s.pq,"read_table",pq_read)
    def no_bootstrap(*a,**k): raise AssertionError("NO_OLD_BOOTSTRAP_OR_EDGE_REEVALUATION")
    for obj,key in ((s.owner.shared,"shared_max_t"),(s.owner,"masked_bootstrap"),
                    (s.owner,"risk_bootstrap"),(s.owner,"_draw_counts")):
        monkeypatch.setattr(obj,key,no_bootstrap)
    design=design_fixture()
    ids=[f"SYNTHETIC_LEGACY_{i}" for i in range(147)]
    design["evaluation"]["legacy"]["numeric_ids"]=ids
    failed={f"SYNTHETIC_FAILED_{i}":"RETAINED" for i in range(79)}
    design["evaluation"]["legacy"].update(exposure_ids=ids+list(failed),failed_or_untestable=failed)
    modules=(s.owner,s.owner.shared,s.owner.prior,s.owner.risk_metrics,s.owner.pairs_owner)
    design["sources"]={str(Path(m.__file__).resolve()):sha(m.__file__) for m in modules}
    names=["C12","C11","C10","HORIZON","C5","R4","R2"]
    counts=[0,10,16,16,18,8,79]
    docs={}; at=0
    for name,count in zip(names,counts):
        rows=[]
        for cid in ids[at:at+count]:
            row=dict(candidate_id=cid,status="COMPLETE",pooled_edge=.001,
                bootstrap_se=.01,year_edges={"2023":.001,"2024":.002,"2025":.003})
            if name in ("C10","HORIZON","C5","R4"):
                row["test_id"]=cid
            if name=="C10": row["candidate_id"]="SYNTHETIC_REUSED_ENDPOINT"
            if name=="R4": row.pop("status")
            rows.append(row)
        at+=count
        doc=dict(common_mature_dates=732,common_year_dates=s.owner.YEAR_COUNTS,
            economic_promotion_allowed=False,strict_PIT_promotion_eligible=False,test2026_rows_read=0)
        if name=="R4":
            doc.update(schema="C_FROZEN_HISTORY_SELECTION_EVIDENCE_V1",status="MECHANISM_EVIDENCE_COMPLETE",
                failed_or_untestable={},failed_contrasts={},candidates=rows[:4],fixed_mechanism_contrasts=rows[4:])
        else:
            doc.update(tests=rows)
            if name=="HORIZON": doc["candidates"]=deepcopy(rows[:8])
        docs[name]=doc
    days=pd.DatetimeIndex(list(pd.bdate_range("2023-01-02",periods=250))+
        list(pd.bdate_range("2024-01-01",periods=252))+list(pd.bdate_range("2025-01-01",periods=250)))
    clock=pd.DataFrame(dict(signal_date=days,included=[True]*732+[False]*20))
    specs=s.owner.role_specs()
    new=[]
    for spec in specs:
        complete=spec["candidate_id"] in ("C14_P01","C14_P09")
        new.append(dict(spec,status="COMPLETE" if complete else "FAILED_UNTESTABLE",
            failure_reason=None if complete else "WAITING_INPUT",
            pooled_edge=.02 if complete else None,bootstrap_se=.02 if complete else None,
            year_edges={"2023":None,"2024":.01 if complete else None,"2025":.02 if complete else None}))
    risk=[dict(spec,status="FAILED_UNTESTABLE",failure_reason="WAITING_INPUT",
        pooled_risk_improvement=None,bootstrap_se=None) for spec in s.owner.RISK_SPECS]
    boot=dict(status="COMPLETE",repeats=5000,block_sessions=20,seed=20260928,
        quantile_method="higher",se_ddof=1,se_zero_tolerance=s.owner.shared.SE_TOL,
        studentization="fixed bootstrap-SE plugin; no per-replicate SE refit",
        centering="sample-centered observations, then conditional bootstrap mean recentered per column",
        exposure_namespace=321,legacy_numeric_complete_series=147,legacy_exposure_namespace=226,
        independent_holdout=False,strict_PIT_promotion_eligible=False,
        critical_max_t=3.,legacy_critical_max_t=2.,minimum_draw_wise_max_increment=0.,
        risk_tests=risk,numeric_complete_series=149,family_candidates=149,
        active_nonzero_se_columns=149,shared_draw_sha256="a"*64,legacy_shared_draw_sha256="a"*64)
    c14=dict(research_id=s.ID,strict_PIT_promotion_eligible=False,independent_holdout=False,
        new2026_reads=0,**{"2026_locked":True},tests=new,bootstrap=boot)
    state=dict(run=run,base=base,memory=memory,frames=frames,docs=docs,design=design,
        c14=c14,clock=clock,reads=reads,projections=projections,put=put,sha=sha)
    def rebuild():
        chain=[]; refs={}; target=None
        for name in reversed(names):
            ancestor={"evaluation":{"legacy":{} if target is None else deepcopy(target)}}
            dref=put(base/name/"DESIGN_FREEZE.json",ancestor)
            docs[name]["design_freeze_sha256"]=dref["sha256"]
            eref=put(base/name/"diagnostics/selector_evidence/SELECTION_EVIDENCE.json",docs[name])
            target=dict(design=dref,evidence=eref)
            refs[name]=deepcopy(target)
            chain.append((name,name,dref["sha256"],eref["sha256"]))
        monkeypatch.setattr(s,"CHAIN",tuple(reversed(chain)))
        clockpath=base/"C12/diagnostics/selector_evidence/COMMON_DATE_MATURITY.parquet"
        memory[str(clockpath.resolve())]=b"SYNTHETIC_CLOCK_PARQUET"
        frames[str(clockpath.resolve())]=state["clock"]
        cref=dict(path=str(clockpath),sha256=sha(clockpath)); monkeypatch.setattr(s,"CLOCK",cref)
        design["evaluation"]["legacy"].update(old_design=refs["C12"]["design"],
            evidence=refs["C12"]["evidence"],clock=cref)
        dref=put(run/"DESIGN_FREEZE.json",design); monkeypatch.setattr(s,"DESIGN_SHA",dref["sha256"])
        c14["design"]=dref
        c14["final_pipeline"]=dict(path=str(run/"FINAL_PIPELINES_FREEZE.json"),sha256=s.OLD_ML_GATE_SHA)
        maxpath=run/"diagnostics/selector_evidence/BOOTSTRAP_MAXT.parquet"
        memory[str(maxpath.resolve())]=b"SYNTHETIC_MAX5000_PARQUET"
        frames[str(maxpath.resolve())]=pd.DataFrame(dict(max_t=np.full(5000,3.)))
        mref=dict(path=str(maxpath),sha256=sha(maxpath));monkeypatch.setattr(s,"C14_MAXIMA",mref)
        c14["diagnostics"]={"BOOTSTRAP_MAXT":dict(mref,rows=5000)}
        eref=put(run/"diagnostics/selector_evidence/SELECTION_EVIDENCE.json",c14)
        monkeypatch.setattr(s,"C14_EVIDENCE",eref)
        artifacts={"c14_evidence":eref,"c14_maxima":mref,"clock":cref}
        for name,pair in refs.items():
            artifacts[name+"_design"]=pair["design"];artifacts[name+"_evidence"]=pair["evidence"]
        review=dict(status="PASS",research_id=s.ID,source_pins=s.required_source_pins(),artifact_refs=artifacts)
        rref=put(run/"risk_execution/SYNTHETIC_SOURCE_REVIEW.json",review)
        state.update(dref=dref,rref=rref,review=review,refs=refs)
    state["rebuild"]=rebuild
    rebuild()
    return state


def collect(bank):
    return s.collect_published_legacy(bank["dref"],bank["rref"])


def seal(bank, summary=None):
    summary=collect(bank) if summary is None else summary
    ref=bank["put"](bank["run"]/"risk_execution/PUBLISHED_LEGACY_SUMMARIES.json",summary)
    bank["review"]["artifact_refs"]["legacy_summaries"]=ref
    bank["rref"]=bank["put"](bank["run"]/"risk_execution/SYNTHETIC_SOURCE_REVIEW.json",bank["review"])
    return ref


def test_exact147_published_values_id_priority_native_r4_and_horizon_duplicate_provenance(bank):
    result=collect(bank)
    assert len(result["summaries"])==147
    assert [r["candidate_id"] for r in result["summaries"]]==bank["design"]["evaluation"]["legacy"]["numeric_ids"]
    assert all(r["pooled_edge"]==.001 and r["bootstrap_se"]==.01 for r in result["summaries"])
    assert result["old_bootstrap_calls"]==0 and result["legacy_reselected"] is False
    assert result["strict_PIT_promotion_eligible"] is result["independent_holdout"] is False
    horizon=[r for r in result["summaries"] if any(p["collection"]=="candidates" and "HORIZON" in p["evidence_ref"]["path"] for p in r["provenance"])]
    assert len(horizon)==8 and all(len(r["provenance"])==2 for r in horizon)
    assert sum(r["provenance"][0]["original_status"]=="ABSENT_NATIVE_R4_SCHEMA" for r in result["summaries"])==8
    assert not bank["projections"]


@pytest.mark.parametrize("defect",["missing","conflict","missing_year","nan","negative_se","wrong_status","r4_schema","nonr4_absent","2026","clock"])
def test_invalid_published_row_or_receipt_blocks_without_recomputation(bank,defect):
    docs=bank["docs"]; row=docs["C11"]["tests"][0]
    if defect=="missing": docs["C11"]["tests"].pop()
    elif defect=="conflict": docs["HORIZON"]["candidates"][0]["bootstrap_se"]=2.
    elif defect=="missing_year": row["year_edges"].pop("2023")
    elif defect=="nan": row["pooled_edge"]=None
    elif defect=="negative_se": row["bootstrap_se"]=-.1
    elif defect=="wrong_status": row["status"]="FAILED_UNTESTABLE"
    elif defect=="r4_schema": docs["R4"]["schema"]="UNKNOWN"
    elif defect=="nonr4_absent": row.pop("status")
    elif defect=="2026": docs["C11"]["test2026_rows_read"]=1
    else: docs["C11"]["common_mature_dates"]=731
    bank["rebuild"]()
    with pytest.raises(ValueError): collect(bank)
    assert not bank["projections"]


@pytest.mark.parametrize("defect",["review_fail","review_identity","source_missing","artifact_missing","artifact_pin","design_identity"])
def test_all_review_and_custody_gates_precede_published_rows_and_parquet(bank,defect):
    if defect=="review_fail": bank["review"]["status"]="FAIL"
    elif defect=="review_identity": bank["review"]["research_id"]="C13"
    elif defect=="source_missing": bank["review"]["source_pins"].pop(str(Path(s.incremental.__file__).resolve()))
    elif defect=="artifact_missing": bank["review"]["artifact_refs"].pop("R2_evidence")
    elif defect=="artifact_pin": bank["review"]["artifact_refs"]["R2_evidence"]["sha256"]="0"*64
    else: bank["dref"]=dict(bank["dref"],sha256="0"*64)
    bank["rref"]=bank["put"](bank["run"]/"risk_execution/SYNTHETIC_SOURCE_REVIEW.json",bank["review"])
    bank["reads"].clear()
    with pytest.raises(ValueError): collect(bank)
    assert bank["reads"]==[str(Path(bank["rref"]["path"]).resolve())]
    assert not bank["projections"]


def test_changed_published_physical_bytes_rejected_before_json_payload(bank):
    path=str(Path(bank["refs"]["R2"]["evidence"]["path"]).resolve())
    bank["memory"][path]+=b" "
    with pytest.raises(ValueError,match="PHYSICAL_SHA_CHANGED"): collect(bank)
    assert path not in bank["reads"] and not bank["projections"]


def test_precomputed_is_exact_75_147_and5000_copy_with_independent_legacy_artifact(bank):
    ref=seal(bank)
    payload,clock,receipt=s.load_precomputed(bank["dref"],bank["rref"],ref)
    assert len(payload["summaries"])==75 and len(payload["legacy_summaries"])==147
    np.testing.assert_array_equal(payload["maxima"],np.full(5000,3.))
    pd.testing.assert_frame_equal(clock,bank["clock"])
    assert payload["summaries"]==bank["c14"]["tests"] and payload["bootstrap"]==bank["c14"]["bootstrap"]
    assert receipt["expected_precomputed_sha256"]==s.incremental.content_hash(payload)
    assert receipt["old147_bootstrap_calls"]==receipt["old_ml_bootstrap_calls"]==receipt["test2026_rows_read"]==0
    assert receipt["strict_PIT_promotion_eligible"] is receipt["legacy_reselected"] is False
    assert [cols for _,cols in bank["projections"]]==[["signal_date","included"],["max_t"]]


def test_unreviewed_or_counterfeit_saved_legacy_summary_blocks_before_parquet(bank):
    summary=collect(bank); summary["summaries"][0]["pooled_edge"]+=1
    ref=seal(bank,summary)
    with pytest.raises(ValueError,match="MUST_EQUAL_EXACT"): s.load_precomputed(bank["dref"],bank["rref"],ref)
    assert not bank["projections"]


@pytest.mark.parametrize("defect",["summary_unreviewed","new2026","changed_gate","changed_maxref","changed_draw","shortmax","future_clock"])
def test_loader_boundary_and_original_vector_receipt_preserved(bank,defect):
    ref=seal(bank)
    if defect=="summary_unreviewed":
        bank["review"]["artifact_refs"].pop("legacy_summaries")
        bank["rref"]=bank["put"](bank["run"]/"risk_execution/SYNTHETIC_SOURCE_REVIEW.json",bank["review"])
    elif defect in ("new2026","changed_gate","changed_maxref","changed_draw"):
        c14=bank["c14"]
        if defect=="new2026": c14["new2026_reads"]=1
        elif defect=="changed_gate": c14["final_pipeline"]["sha256"]="0"*64
        elif defect=="changed_maxref": c14["diagnostics"]["BOOTSTRAP_MAXT"]["sha256"]="0"*64
        else: c14["bootstrap"]["legacy_shared_draw_sha256"]="0"*64
        newref=bank["put"](Path(s.C14_EVIDENCE["path"]),c14)
        # Independently reviewed bytes may still be semantically illegal.
        s.C14_EVIDENCE.update(newref)
        bank["review"]["artifact_refs"]["c14_evidence"]=newref
        bank["rref"]=bank["put"](bank["run"]/"risk_execution/SYNTHETIC_SOURCE_REVIEW.json",bank["review"])
    elif defect=="shortmax":
        bank["frames"][str(Path(s.C14_MAXIMA["path"]).resolve())]=pd.DataFrame(dict(max_t=np.ones(4999)))
    else:
        frame=bank["frames"][str(Path(s.CLOCK["path"]).resolve())].copy()
        frame.loc[751,"signal_date"]=pd.Timestamp("2026-01-01")
        bank["frames"][str(Path(s.CLOCK["path"]).resolve())]=frame
    with pytest.raises(ValueError): s.load_precomputed(bank["dref"],bank["rref"],ref)
    if defect in ("summary_unreviewed","new2026","changed_gate","changed_maxref"):
        assert not bank["projections"]

