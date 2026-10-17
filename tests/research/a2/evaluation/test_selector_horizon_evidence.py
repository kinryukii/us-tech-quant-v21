"""Synthetic C7 binding tests: no real artifacts, outcomes or learner fitting."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.evaluation import selector_horizon_evidence as sut
from scripts.research.a2.evaluation import selector_algorithm_breadth_evidence as r5
from scripts.research.a2.evaluation import selector_account_compare as reader


def r5_design():
    old = [f"OLD_{i:02d}" for i in range(99)]
    return dict(official_freeze=True, formal_freeze_applied=True, research_id=r5.RESEARCH_ID,
        mechanism_research_eligible=True, strict_PIT_promotion_eligible=False, roles=list(r5.ROLES),
        target=sut.TARGET, primary_eval_years=list(sut.YEARS), test2026_locked=True,
        new2026_estimation_authorized=False,
        evaluation=dict(primary=sut.PRIMARY, common_mature_date_count=732,
            year_counts=sut.YEAR_COUNTS.copy(), exposure_namespace=117,
            bootstrap=dict(method=sut.BOOT_METHOD, repeats=5000, seed=20260928, confidence=.95),
            inherited_selection_requirements=dict(pooled_edge_positive=True, year2025_edge_positive=True,
                positive_years_min=2, simultaneous_lower_bound_gt_zero=True),
            legacy=dict(numeric_ids=old[:87], exposure_ids=old,
                failed_or_untestable={cid: "RETAINED_FAILED" for cid in old[87:]})))


def design():
    older = r5_design()["evaluation"]["legacy"]
    return dict(official_freeze=True, formal_freeze_applied=True, research_id=sut.RESEARCH_ID,
        mechanism_research_eligible=True, strict_PIT_promotion_eligible=False,
        roles=list(sut.ALL_ROLES), target=sut.TARGET, primary_eval_years=list(sut.YEARS),
        test2026_locked=True, new2026_estimation_authorized=False,
        evaluation=dict(primary=sut.PRIMARY, common_mature_date_count=732,
            year_counts=sut.YEAR_COUNTS.copy(), exposure_namespace=133,
            bootstrap=dict(method=sut.BOOT_METHOD, repeats=5000, seed=20260928, confidence=.95, family_candidates=121),
            inherited_selection_requirements=dict(pooled_edge_positive=True, year2025_edge_positive=True,
                positive_years_min=2, simultaneous_lower_bound_gt_zero=True),
            fixed_mechanism_pairs=[[a, b] for _, a, b in sut.CONTRASTS],
            mechanism_support="RAW_ENDPOINT_AND_MATCHED_MEAN_BOTH_PASS",
            legacy=dict(numeric_ids=[*older["numeric_ids"], *r5.ROLES],
                exposure_ids=[*older["exposure_ids"], *r5.ROLES],
                failed_or_untestable=copy.deepcopy(older["failed_or_untestable"]))))


@pytest.mark.parametrize("field,value", [
    ("official_freeze", False), ("formal_freeze_applied", False),
    ("research_id", "RENAMED_C7"), ("roles", list(sut.ROLES)),
    ("target", "ER_3D"), ("primary_eval_years", [2024, 2025]),
    ("mechanism_research_eligible", False), ("strict_PIT_promotion_eligible", True),
    ("test2026_locked", False), ("new2026_estimation_authorized", True),
])
def test_scientific_question_and_boundaries_frozen(field, value):
    d = design(); d[field] = value
    with pytest.raises(ValueError):
        sut.validate_design(d)


@pytest.mark.parametrize("field,value", [
    ("common_mature_date_count", 731), ("year_counts", {"2024": 252, "2025": 230}),
    ("exposure_namespace", 131), ("fixed_mechanism_pairs", []),
    ("mechanism_support", "RAW_ONLY"),
])
def test_all_old_dates_and_mean_comparators_required(field, value):
    d = design(); d["evaluation"][field] = value
    with pytest.raises(ValueError):
        sut.validate_design(d)


@pytest.mark.parametrize("field,value", [("repeats", 1000), ("seed", 1), ("confidence", .9), ("family_candidates", 105)])
def test_joint_bootstrap_cannot_change(field, value):
    d = design(); d["evaluation"]["bootstrap"][field] = value
    with pytest.raises(ValueError, match="SHARED_MAXT"):
        sut.validate_design(d)


def test_anchors_not_new_exposure_and_failed_old_roles_retained():
    d = design(); assert sut.validate_design(d)["exposure_namespace"] == 133
    assert not set(sut.ANCHORS) & set(sut.TEST_IDS)
    d["evaluation"]["legacy"]["failed_or_untestable"] = {}
    with pytest.raises(ValueError, match="105_NUMERIC"):
        sut.validate_design(d)


def series():
    dates = pd.DatetimeIndex(np.concatenate([pd.bdate_range(f"{y}-01-02", periods=25).to_numpy() for y in sut.YEARS]))
    ids = design()["evaluation"]["legacy"]["numeric_ids"]
    rng = np.random.default_rng(98)
    old = pd.DataFrame(rng.normal(0, .02, (75, 105)), index=dates, columns=ids)
    new = pd.DataFrame(rng.normal(.006, .02, (75, 16)), index=dates, columns=sut.TEST_IDS)
    # A smaller synthetic repeat count tests the delegate; production design stays fixed 5000.
    rule = {**design()["evaluation"]["bootstrap"], "repeats": 150}
    return dates, ids, old, new, rule


def test_121_numeric_133_exposure_uses_shared_existing_maxT():
    dates, ids, old, new, rule = series()
    matrix, summaries, receipt, maxima = sut.statistics(old, new, np.arange(75), dates, rule, ids)
    _, _, legacy, previous = sut.evidence.shared_max_t(old.to_numpy(), np.arange(75), [True]*105,
        {**rule, "family_candidates": 105})
    assert matrix.shape == (75, 121) and len(summaries) == 16
    assert receipt["exposure_namespace"] == 133 and receipt["legacy_shared_draw_sha256"] == legacy["shared_draw_sha256"]
    assert np.all(maxima >= previous-1e-12) and receipt["critical_max_t"] >= legacy["critical_max_t"]-1e-12
    assert all(not s["strict_PIT_promotion_eligible"] for s in summaries)


def test_failure_drops_role_and_its_contrast_never_fills_zeros():
    dates, ids, old, new, rule = series()
    cid, role, _ = sut.CONTRASTS[0]
    matrix, summaries, receipt, _ = sut.statistics(old, new.drop(columns=[role, cid]), np.arange(75), dates,
        rule, ids, {role: "FIT_FAILED", cid: "DEPENDENCY_FAILED"})
    assert matrix.shape == (75, 119) and receipt["exposure_namespace"] == 133
    bad = [s for s in summaries if s["test_id"] in {role, cid}]
    assert len(bad) == 2 and all(s["pooled_edge"] is None and not s["mechanism_supported"] for s in bad)
    with pytest.raises(ValueError, match="IDENTICAL_READINESS"):
        sut.statistics(old, new.drop(columns=[cid]), np.arange(75), dates, rule, ids)


def test_mean_contrast_failure_blocks_otherwise_positive_raw_support(monkeypatch):
    dates, ids, old, new, rule = series()
    new.loc[:, :] += 1
    contrast = sut.CONTRASTS[0][0]; new[contrast] = -1+new[contrast]*.001
    calls = []
    def owner(matrix, positions, complete, boot):
        calls.append(matrix.shape[1]); p=matrix.shape[1]
        return matrix.mean(axis=0)-.001, np.full(p,.01), dict(status="COMPLETE", shared_draw_sha256="FIXED_DRAW",
            critical_max_t=3 if p>105 else 2), np.full(3,3 if p>105 else 2.)
    monkeypatch.setattr(sut.evidence, "shared_max_t", owner)
    _, summary, _, _ = sut.statistics(old, new, np.arange(75), dates, rule, ids)
    role = next(s for s in summary if s["test_id"]==sut.ROLES[0])
    assert calls == [105,121] and role["endpoint_supported"]
    assert not role["matched_mean_contrast_supported"] and not role["mechanism_supported"]


def test_no_filtering_nan_calendar_or_future_dates():
    dates, ids, old, new, rule = series()
    with pytest.raises(ValueError, match="ORIGINAL_CALENDAR"):
        sut.statistics(old,new,np.arange(75),dates.insert(0,pd.Timestamp("2022-12-30")),rule,ids)
    broken=old.copy(); broken.iloc[0,0]=np.nan
    with pytest.raises(ValueError, match="EXACT_FINITE"):
        sut.statistics(broken,new,np.arange(75),dates,rule,ids)
    with pytest.raises(ValueError, match="EXACT_FINITE"):
        sut.statistics(old,new,np.arange(75),dates.append(pd.DatetimeIndex(["2026-01-02"])),rule,ids)


def putj(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2),encoding="utf-8")


def pin(path):
    return dict(path=str(path),sha256=sut.sha(path))


def freeze(run,d):
    putj(run/"DESIGN_FREEZE.json",d); digest=sut.sha(run/"DESIGN_FREEZE.json")
    putj(run/"DESIGN_FREEZE_SHA.json",dict(sha256=digest))
    cfg=sut.readj(run/"run_config.json"); cfg["design_freeze_sha256"]=digest; putj(run/"run_config.json",cfg)
    a=sut.readj(run/"SCORE_ASSEMBLY.json");a["design_freeze_sha256"]=digest;putj(run/"SCORE_ASSEMBLY.json",a)
    putj(run/"EVALUATION_CODE_ACTIVATION.json",dict(design_freeze_sha256=digest,
        score_assembly_sha256=sut.sha(run/"SCORE_ASSEMBLY.json"),sources=d["sources"]))


def pipeline(tmp_path,monkeypatch,immature=False,failed=False):
    backtest,results=tmp_path/"backtest",tmp_path/"results"
    run,out,previous=backtest/"new",results/"new",backtest/"r5"
    for p in (run/"predictions",out,previous):p.mkdir(parents=True)
    dates=pd.DatetimeIndex(np.concatenate([pd.bdate_range(f"{y}-01-02",periods=n).to_numpy()
        for y,n in ((2023,250),(2024,252),(2025,250))]))
    included=np.arange(752)<732; rng=np.random.default_rng(534)
    raw=pd.DataFrame([dict(signal_date=date,ticker=f"S{j:02d}",security_uid=f"UID{j:02d}",
        U_t_fingerprint="SYNTHETIC_FULL_U_T",candidate_id=sut.evidence.RAW,score=float(21-j),rank=j+1,
        target=float(rng.normal(.001,.02)) if included[i] else np.nan,
        label_end_date=date+pd.Timedelta(days=1) if included[i] else pd.NaT)
        for i,date in enumerate(dates) for j in range(21)])
    if immature:
        select=raw.signal_date.eq(dates[0])&raw.security_uid.eq("UID20")
        raw.loc[select,"target"]=np.nan;raw.loc[select,"label_end_date"]=pd.NaT
    rawpath=run/"predictions"/f"scores_{sut.evidence.RAW}_pre2026.parquet"
    raw.to_parquet(rawpath,index=False);bindings={sut.evidence.RAW:pin(rawpath)}
    for cid in sut.ALL_ROLES:
        panel=raw.drop(columns=["target","label_end_date"]).copy();panel["candidate_id"]=cid
        if cid in sut.ROLES and not immature:panel["score"]=rng.normal(size=len(panel))
        if immature and cid==sut.ROLES[0]:panel.loc[panel.security_uid.eq("UID20"),"score"]=2.5
        panel=panel.sort_values(["signal_date","score","security_uid"],ascending=[True,False,True],kind="stable")
        panel["rank"]=panel.groupby("signal_date").cumcount()+1
        p=run/"predictions"/f"scores_{cid}_pre2026.parquet";panel.to_parquet(p,index=False);bindings[cid]=pin(p)
    d=design();legacy=d["evaluation"]["legacy"]
    clockpath,edgepath=previous/"CLOCK.parquet",previous/"EDGES.parquet"
    pd.DataFrame(dict(signal_date=dates,included=included)).to_parquet(clockpath,index=False)
    edge=pd.DataFrame(rng.normal(0,.02,(732,105)),columns=legacy["numeric_ids"])
    for cid in legacy["failed_or_untestable"]:edge[cid]=np.nan
    edge.insert(0,"signal_date",dates[included]);edge.to_parquet(edgepath,index=False)
    olddesign,oldassembly=previous/"DESIGN_FREEZE.json",previous/"SCORE_ASSEMBLY.json"
    putj(olddesign,r5_design());putj(oldassembly,dict(complete_candidates=list(r5.ROLES),failed_or_untestable={},
        design_freeze_sha256=sut.sha(olddesign)))
    legacy.update(edge=pin(edgepath),clock=pin(clockpath),design=pin(olddesign),assembly=pin(oldassembly))
    labels=results/"training.parquet";pd.DataFrame(dict(signal_date=dates,target_end_date=dates)).to_parquet(labels,index=False)
    d["inputs"]={"training":pin(labels)}
    d["sources"]={str(p):sut.sha(p) for p in (Path(sut.__file__),Path(sut.evidence.__file__),Path(r5.__file__),
        sut.REPO/"scripts/research/a2/evaluation/selector_account_compare.py")}
    putj(run/"run_config.json",dict(results_directory=str(out),research_id=sut.RESEARCH_ID,research_line="C_SELECTOR"))
    putj(run/"SCORE_ASSEMBLY.json",dict(complete_candidates=[] if failed else list(sut.ROLES),
        complete_fixed_references=list(sut.ANCHORS),failed_or_untestable={r:"SYNTHETIC_FAILURE" for r in sut.ROLES} if failed else {},
        forecast2026_rows=0,common_rows=len(raw),common_dates=752,score_paths=bindings))
    freeze(run,d)
    paths=SimpleNamespace(backtest_root=backtest,results_root=results)
    monkeypatch.setattr(sut,"resolve",lambda repo:paths)
    monkeypatch.setattr(sut,"assert_safe_output_path",lambda *a,**k:None)
    module=ModuleType("scripts.research.a2.training.selector_horizon_breadth")
    def checked(directory):
        cfg=sut.readj(directory/"run_config.json");p=directory/"DESIGN_FREEZE.json"
        assert sut.sha(p)==cfg["design_freeze_sha256"]==sut.readj(directory/"DESIGN_FREEZE_SHA.json")["sha256"]
        return cfg,sut.readj(p)
    module.checked=checked
    import scripts.research.a2.training as package
    monkeypatch.setitem(sys.modules,module.__name__,module)
    monkeypatch.setattr(package,"selector_horizon_breadth",module,raising=False)
    actual=sut.evidence.shared_max_t
    monkeypatch.setattr(sut.evidence,"shared_max_t",lambda x,positions,complete,rule:actual(x,positions,complete,{**rule,"repeats":150}))
    return run,out


def test_full_adapter_732_dates_121_edges_and_no_anchor_exposure(tmp_path,monkeypatch):
    run,out=pipeline(tmp_path,monkeypatch)
    result=sut.run(run)
    assert result["bootstrap"]["numeric_complete_series"]==121
    assert result["common_mature_dates"]==732 and result["common_year_dates"]==sut.YEAR_COUNTS
    assert len(result["candidates"])==8 and len(result["contrasts"])==8 and len(result["tests"])==16
    assert len(result["exposure_roles"])==133 and not set(sut.ANCHORS)&set(result["exposure_roles"])
    assert not result["strict_PIT_promotion_eligible"] and not result["financial_verified"] and result["finalists"]==[]
    assert result["test2026_rows_read"]==0 and result["unified_evaluation_target"]==sut.TARGET
    matrix=pd.read_parquet(run/"diagnostics/selector_evidence/PRIMARY_DAILY_EDGE.parquet")
    assert matrix.shape==(732,122) and not set(result["legacy_failed_or_untestable"])&set(matrix)
    assert (out/"SELECTION_EVIDENCE.json").is_file()
    with pytest.raises(FileExistsError,match="PRESERVE"):
        sut.run(run)


def test_immature_role_and_contrast_fail_without_date_shrink(tmp_path,monkeypatch):
    run,_=pipeline(tmp_path,monkeypatch,immature=True)
    result=sut.run(run)
    assert result["bootstrap"]["numeric_complete_series"]==119 and result["common_mature_dates"]==732
    assert len(result["failed_or_untestable"])==2
    assert "NO_SHRINK" in result["failed_or_untestable"][sut.ROLES[0]]
    assert "DEPENDENCY_FAILED" in result["failed_or_untestable"][sut.CONTRASTS[0][0]]


def test_no_read_before_freeze_and_assembly_activation(tmp_path,monkeypatch):
    run,_=pipeline(tmp_path,monkeypatch,failed=True)
    d=sut.readj(run/"DESIGN_FREEZE.json");d["official_freeze"]=False;freeze(run,d)
    monkeypatch.setattr(sut,"pre2026",lambda *a,**k:pytest.fail("read before freeze"))
    monkeypatch.setattr(sut,"score_panel",lambda *a,**k:pytest.fail("read before freeze"))
    with pytest.raises(ValueError,match="FORMAL_FREEZE"):
        sut.run(run)


def test_anchor_hash_changed_blocks_before_anchor_projection(tmp_path,monkeypatch):
    run,_=pipeline(tmp_path,monkeypatch,failed=True)
    a=sut.readj(run/"SCORE_ASSEMBLY.json");a["score_paths"][sut.ANCHORS[0]]["sha256"]="0"*64
    putj(run/"SCORE_ASSEMBLY.json",a)
    activation=sut.readj(run/"EVALUATION_CODE_ACTIVATION.json");activation["score_assembly_sha256"]=sut.sha(run/"SCORE_ASSEMBLY.json")
    putj(run/"EVALUATION_CODE_ACTIVATION.json",activation)
    actual=sut.score_panel
    monkeypatch.setattr(sut,"score_panel",lambda r,c:actual(r,c) if c==sut.evidence.RAW else pytest.fail("unbound anchor read"))
    with pytest.raises(ValueError,match="BINDING_CHANGED"):
        sut.run(run)


def test_2026_footer_rejected_before_any_label_projection(tmp_path,monkeypatch):
    p=tmp_path/"mixed.parquet"
    pd.DataFrame(dict(signal_date=pd.to_datetime(["2025-12-31","2026-01-02"]),
        target_end_date=pd.to_datetime(["2025-12-31","2026-01-05"]),target=[1.,2.])).to_parquet(p,index=False)
    monkeypatch.setattr(sut.evidence.pq,"read_table",lambda *a,**k:pytest.fail("future value projection"))
    with pytest.raises(ValueError,match="PHYSICAL_PRE2026"):
        sut.evidence.prove_label_boundary(p,"target_end_date")
