"""Synthetic C11 lineage and cumulative inference; no real outcomes or fitting."""
from __future__ import annotations
import copy
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.evaluation import selector_classical_evidence as sut


def legacy_design():
    old = [f"LEGACY_{i}" for i in range(105)] + list(sut.c10.c7.TEST_IDS)
    failed = {f"FAILED_{i}": "RETAINED" for i in range(12)}
    return dict(official_freeze=True, formal_freeze_applied=True, research_id=sut.c10.RESEARCH_ID,
        roles=list(sut.c10.ALL_ROLES), target=sut.TARGET, primary_eval_years=list(sut.YEARS),
        mechanism_research_eligible=True, strict_PIT_promotion_eligible=False,
        test2026_locked=True, new2026_estimation_authorized=False,
        evaluation=dict(primary=sut.PRIMARY, common_mature_date_count=732, year_counts=sut.YEAR_COUNTS.copy(),
            exposure_namespace=149, bootstrap=dict(method=sut.BOOT_METHOD, repeats=5000,
                seed=20260928, confidence=.95, family_candidates=137),
            inherited_selection_requirements=dict(pooled_edge_positive=True, year2025_edge_positive=True,
                positive_years_min=2, simultaneous_lower_bound_gt_zero=True),
            test_specs=copy.deepcopy(list(sut.c10.TEST_SPECS)),
            legacy=dict(numeric_ids=old, exposure_ids=old+list(failed), failed_or_untestable=failed)))


def design():
    old = legacy_design()["evaluation"]["legacy"]
    return dict(official_freeze=True, formal_freeze_applied=True, research_id=sut.RESEARCH_ID,
        roles=list(sut.ROLES), target=sut.TARGET, primary_eval_years=list(sut.YEARS),
        mechanism_research_eligible=True, strict_PIT_promotion_eligible=False,
        test2026_locked=True, new2026_estimation_authorized=False,
        evaluation=dict(primary=sut.PRIMARY, common_mature_date_count=732, year_counts=sut.YEAR_COUNTS.copy(),
            original_calendar_dates=752, exposure_namespace=169, numeric_ceiling=157, sanity_diagnostic_only=True,
            bootstrap=dict(method=sut.BOOT_METHOD, repeats=5000, seed=20260928,
                confidence=.95, family_candidates=157),
            inherited_selection_requirements=dict(pooled_edge_positive=True, year2025_edge_positive=True,
                positive_years_min=2, simultaneous_lower_bound_gt_zero=True),
            legacy=dict(numeric_ids=old["numeric_ids"]+list(sut.c10.TEST_IDS),
                exposure_ids=old["exposure_ids"]+list(sut.c10.TEST_IDS),
                failed_or_untestable=old["failed_or_untestable"])))


@pytest.mark.parametrize("field,value", [
    ("official_freeze", False), ("formal_freeze_applied", False), ("research_id", "OTHER"),
    ("roles", list(sut.A_ROLES)), ("target", "ER_3D"), ("primary_eval_years", [2024, 2025]),
    ("strict_PIT_promotion_eligible", True), ("mechanism_research_eligible", False),
    ("test2026_locked", False), ("new2026_estimation_authorized", True),
])
def test_science_freeze_and_future_lock(field, value):
    d=design();d[field]=value
    with pytest.raises(ValueError):sut.validate_design(d)


@pytest.mark.parametrize("field,value", [
    ("common_mature_date_count", 731), ("year_counts", {"2025":230}),
    ("exposure_namespace", 159), ("numeric_ceiling", 147), ("original_calendar_dates", 732),
    ("sanity_diagnostic_only", False),
])
def test_clock_namespace_and_sanity_frozen(field, value):
    d=design();d["evaluation"][field]=value
    with pytest.raises(ValueError):sut.validate_design(d)


@pytest.mark.parametrize("field,value", [
    ("repeats", 150), ("seed", 1), ("confidence", .9), ("family_candidates", 147), ("method", "circular"),
])
def test_shared_max_t_production_rule(field,value):
    d=design();d["evaluation"]["bootstrap"][field]=value
    with pytest.raises(ValueError,match="MAXT"):sut.validate_design(d)


def test_old_failed_exposure_cannot_disappear_or_become_zero():
    d=design()
    assert len(sut.ROLES)==20 and len(sut.A_ROLES)==8 and len(sut.B_ROLES)==10
    assert sut.validate_design(d)["exposure_namespace"]==169
    d["evaluation"]["legacy"]["failed_or_untestable"]={}
    with pytest.raises(ValueError,match="137_NUMERIC"):sut.validate_design(d)


def clocks():
    calendar=pd.DatetimeIndex(np.concatenate([pd.bdate_range(f"{y}-01-02",periods=n).to_numpy()
        for y,n in ((2023,250),(2024,252),(2025,250))]))
    positions=np.arange(732)
    return calendar,positions,calendar[positions]


def series():
    calendar,positions,index=clocks()
    ids=design()["evaluation"]["legacy"]["numeric_ids"]
    rng=np.random.default_rng(23)
    old=pd.DataFrame(rng.normal(0,.02,(732,137)),index=index,columns=ids)
    new=pd.DataFrame(rng.normal(.004,.02,(732,20)),index=index,columns=sut.ROLES)
    new[sut.SANITY_ROLES[1]]=0.
    rule={**design()["evaluation"]["bootstrap"],"repeats":80}
    return calendar,positions,ids,old,new,rule


def test_full_157_numeric_169_exposure_shared_owner_and_no_sanity_promotion():
    calendar,positions,ids,old,new,rule=series()
    new[sut.SANITY_ROLES[0]]+=2.
    matrix,rows,receipt,maxima=sut.statistics(old,new,positions,calendar,rule,ids,synthetic=True)
    assert matrix.shape==(732,157) and receipt["exposure_namespace"]==169
    assert receipt["numeric_complete_series"]==157
    assert receipt["shared_draw_sha256"]==receipt["legacy_shared_draw_sha256"]
    assert receipt["critical_max_t"]>=receipt["legacy_critical_max_t"]-1e-12
    assert receipt["minimum_draw_wise_max_increment"]>=-1e-12
    sanity=[r for r in rows if r["diagnostic_only"]]
    assert len(sanity)==2 and all(not r["supported"] for r in sanity)
    raw=sanity[1]
    assert raw["pooled_edge"]==0. and not raw["research_support_conditions"]["nonzero_bootstrap_se"]


def test_all_b_blocked_keep_147_numeric_169_exposure_without_fake_zero():
    calendar,positions,ids,old,new,rule=series()
    new=new.drop(columns=list(sut.B_ROLES))
    failed={r:"BLOCKED_SHARED_BANK" for r in sut.B_ROLES}
    matrix,rows,receipt,_=sut.statistics(old,new,positions,calendar,rule,ids,failed,synthetic=True)
    assert matrix.shape==(732,147) and receipt["exposure_namespace"]==169
    assert matrix.index.equals(old.index) and not set(sut.B_ROLES)&set(matrix)
    blocked=[r for r in rows if r["candidate_id"] in sut.B_ROLES]
    assert all(r["failure_reason"]=="BLOCKED_SHARED_BANK" and r["pooled_edge"] is None
        and r["bootstrap_se"] is None and not r["supported"] for r in blocked)


@pytest.mark.parametrize("mutation", ["date_drop","future","nonfinite","raw_nonzero","position_swap","duplicate_role","failed_complete"])
def test_no_date_shrink_fake_raw_or_future(mutation):
    calendar,positions,ids,old,new,rule=series()
    if mutation=="date_drop":new=new.iloc[1:]
    elif mutation=="future":calendar=calendar.append(pd.DatetimeIndex(["2026-01-01"]))
    elif mutation=="nonfinite":new.iloc[0,0]=np.nan
    elif mutation=="raw_nonzero":new[sut.SANITY_ROLES[1]]=1e-20
    elif mutation=="position_swap":positions[[0,1]]=positions[[1,0]]
    elif mutation=="duplicate_role":new.columns=[sut.ROLES[0],*list(new.columns)[1:-1],sut.ROLES[0]]
    failed={sut.A_ROLES[0]:"FAILED"} if mutation=="failed_complete" else None
    with pytest.raises(ValueError):sut.statistics(old,new,positions,calendar,rule,ids,failed,synthetic=True)


def test_zero_se_and_negative2025_do_not_support():
    calendar,positions,ids,old,new,rule=series()
    new[sut.A_ROLES[0]]=1.
    new.loc[new.index.year==2025,sut.A_ROLES[1]]=-1.
    _,rows,_,_=sut.statistics(old,new,positions,calendar,rule,ids,synthetic=True)
    assert not rows[0]["supported"] and not rows[1]["supported"]
    with pytest.raises(ValueError,match="MAXT"):sut.statistics(old,new,positions,calendar,rule,ids)


def test_threshold_may_not_drop_even_if_owner_is_regressed(monkeypatch):
    calendar,positions,ids,old,new,rule=series()
    owner=sut.evidence.shared_max_t
    def broken(x,p,c,r):
        lower,se,rec,maxima=owner(x,p,c,r)
        if x.shape[1]>137:
            rec={**rec,"critical_max_t":-100.}
            maxima=maxima-100.
        return lower,se,rec,maxima
    monkeypatch.setattr(sut.evidence,"shared_max_t",broken)
    with pytest.raises(ValueError,match="NOT_LOWER"):
        sut.statistics(old,new,positions,calendar,rule,ids,synthetic=True)


def panels():
    calendar,positions,index=clocks()
    clock=pd.DataFrame({"signal_date":calendar,"included":np.isin(np.arange(752),positions)})
    rows=[]
    for date in calendar:
        for uid in range(21):
            rows.append(dict(signal_date=date,security_uid=uid,ticker=f"S{uid}",U_t_fingerprint="SYNTHETIC",
                candidate_id=sut.RAW,score=float(uid),rank=21-uid,target=float(uid)/100,
                label_end_date=date+pd.Timedelta(days=1)))
    raw=pd.DataFrame(rows)
    panel=raw.drop(columns=["target","label_end_date"]).copy()
    panel["candidate_id"]=sut.A_ROLES[0]
    panel["score"]=0. # Formula ties resolved by Raw rank, never UID-first.
    return raw,panel,clock


def test_formula_score_raw_rank_uid_tie_not_old_uid_tie():
    raw,panel,clock=panels()
    mature,metadata=sut.validate_panel(raw,panel,clock)
    assert mature.all() and metadata.included.all() and panel.score.eq(0).all()
    wrong=panel.copy();wrong["rank"]=wrong.security_uid+1
    with pytest.raises(ValueError,match="RAW_RANK_UID"):sut.validate_panel(raw,wrong,clock)


@pytest.mark.parametrize("mutation",["raw_score","raw_rank","missing_uid","selected_immature","clock_drop","duplicate_column"])
def test_full_u_raw_identity_and_maturity(mutation):
    raw,panel,clock=panels()
    if mutation.startswith("raw_"):
        panel=raw.drop(columns=["target","label_end_date"]).copy()
        panel["candidate_id"]=sut.SANITY_ROLES[1]
        if mutation=="raw_score":panel["score"]+=.001
        else:panel["rank"]=panel.security_uid+1
    elif mutation=="missing_uid":panel=panel.iloc[1:].reset_index(drop=True)
    elif mutation=="selected_immature":raw.loc[raw["rank"].eq(1),"label_end_date"]=pd.NaT
    elif mutation=="clock_drop":clock=clock.iloc[1:]
    else:panel=pd.concat([panel,panel[["score"]]],axis=1)
    with pytest.raises(ValueError):sut.validate_panel(raw,panel,clock)


def test_exact_raw_sanity_and_generic_owner_binding(tmp_path,monkeypatch):
    raw,panel,clock=panels()
    panel=raw.drop(columns=["target","label_end_date"]).copy();panel["candidate_id"]=sut.SANITY_ROLES[1]
    sut.validate_panel(raw,panel,clock)
    p=tmp_path/"scores.parquet";p.write_bytes(b"SYNTHETIC_NO_DATA")
    calls=[]
    monkeypatch.setattr(sut,"score_path",lambda root,cid:p)
    monkeypatch.setattr(sut,"score_panel",lambda root,cid:(calls.append(cid) or panel,sut.sha(p)))
    assembly={"score_paths":{sut.SANITY_ROLES[1]:{"path":str(p),"sha256":sut.sha(p)}}}
    result,digest=sut.bound_panel(tmp_path,sut.SANITY_ROLES[1],assembly,raw,clock)
    assert calls==[sut.SANITY_ROLES[1]] and result.equals(panel) and digest==sut.sha(p)


@pytest.fixture
def lineage(tmp_path,monkeypatch):
    root=tmp_path/"backtest"/"c10";root.mkdir(parents=True)
    repo=tmp_path/"repo";repo.mkdir()
    source=repo/"synthetic_source.py";source.write_text("# SYNTHETIC\n")
    d=legacy_design();d["sources"]={str(source):sut.sha(source)}
    def put(name,body):
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(body));return {"path":str(p),"sha256":sut.sha(p)}
    design_pin=put("DESIGN_FREEZE.json",d)
    assembly=put("SCORE_ASSEMBLY.json",dict(complete_candidates=list(sut.c10.NEW_ROLES),
        complete_fixed_references=list(sut.c10.REFERENCES),failed_or_untestable={},
        forecast2026_rows=0,design_freeze_sha256=design_pin["sha256"]))
    old=d["evaluation"]["legacy"]
    legacy=dict(design=design_pin,assembly=assembly,
        numeric_ids=old["numeric_ids"]+list(sut.c10.TEST_IDS),
        exposure_ids=old["exposure_ids"]+list(sut.c10.TEST_IDS),
        failed_or_untestable=old["failed_or_untestable"],sources=d["sources"])
    for key,name in (("evidence","SELECTION_EVIDENCE.json"),("edge","PRIMARY_DAILY_EDGE.parquet"),
                     ("clock","COMMON_DATE_MATURITY.parquet")):
        p=root/"diagnostics"/"selector_evidence"/name;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(b"INTENTIONALLY_OPAQUE_NOT_JSON_OR_PARQUET")
        legacy[key]={"path":str(p),"sha256":sut.sha(p)}
    return legacy,SimpleNamespace(backtest_root=tmp_path/"backtest",repo_root=repo)


def test_c10_lineage_opaque_evidence_never_parsed(lineage,monkeypatch):
    legacy,paths=lineage
    owner=sut.readj;read=[]
    def safe(path):
        read.append(str(path))
        assert path.name in ("DESIGN_FREEZE.json","SCORE_ASSEMBLY.json")
        return owner(path)
    monkeypatch.setattr(sut,"readj",safe)
    ev=sut.validate_legacy(legacy,paths)
    assert len(read)==2 and len(ev["legacy"]["numeric_ids"])==121


@pytest.mark.parametrize("mutation",["numeric","exposure","source_bytes","source_list","evidence_bytes","assembly_bytes"])
def test_c10_lineage_and_failed_history_cannot_change(lineage,mutation):
    legacy,paths=lineage
    if mutation=="numeric":legacy["numeric_ids"]=legacy["numeric_ids"][:-1]
    elif mutation=="exposure":legacy["exposure_ids"]=legacy["exposure_ids"][:-1]
    elif mutation=="source_list":legacy["sources"]={}
    else:
        key=mutation.split("_")[0]
        p=next(iter(legacy["sources"])) if key=="source" else legacy[key]["path"]
        from pathlib import Path
        Path(p).write_bytes(b"CHANGED_SYNTHETIC")
    with pytest.raises(ValueError):sut.validate_legacy(legacy,paths)
