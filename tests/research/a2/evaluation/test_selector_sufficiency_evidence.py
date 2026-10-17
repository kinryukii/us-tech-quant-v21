"""Synthetic C10 comparison tests; no real model, outcome, F or 2026 reads."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.evaluation import selector_sufficiency_evidence as sut
from scripts.research.a2.evaluation import selector_account_compare as reader


def c7_design():
    numeric, failed = [f"OLD_{i}" for i in range(105)], [f"FAILED_{i}" for i in range(12)]
    return dict(official_freeze=True, formal_freeze_applied=True, research_id=sut.c7.RESEARCH_ID,
        roles=list(sut.c7.ALL_ROLES), target=sut.TARGET, primary_eval_years=list(sut.YEARS),
        mechanism_research_eligible=True, strict_PIT_promotion_eligible=False,
        test2026_locked=True, new2026_estimation_authorized=False,
        evaluation=dict(primary=sut.PRIMARY, common_mature_date_count=732, year_counts=sut.YEAR_COUNTS.copy(),
            exposure_namespace=133, bootstrap=dict(method=sut.BOOT_METHOD, repeats=5000, seed=20260928,
                confidence=.95, family_candidates=121),
            inherited_selection_requirements=dict(pooled_edge_positive=True, year2025_edge_positive=True,
                positive_years_min=2, simultaneous_lower_bound_gt_zero=True),
            fixed_mechanism_pairs=[[a, b] for _, a, b in sut.c7.CONTRASTS],
            mechanism_support="RAW_ENDPOINT_AND_MATCHED_MEAN_BOTH_PASS",
            legacy=dict(numeric_ids=numeric, exposure_ids=numeric+failed,
                failed_or_untestable={f: "RETAINED_FAILED" for f in failed})))


def design():
    old = c7_design()["evaluation"]["legacy"]
    return dict(official_freeze=True, formal_freeze_applied=True, research_id=sut.RESEARCH_ID,
        roles=list(sut.ALL_ROLES), target=sut.TARGET, primary_eval_years=list(sut.YEARS),
        mechanism_research_eligible=True, strict_PIT_promotion_eligible=False,
        test2026_locked=True, new2026_estimation_authorized=False,
        evaluation=dict(primary=sut.PRIMARY, common_mature_date_count=732, year_counts=sut.YEAR_COUNTS.copy(),
            exposure_namespace=149, bootstrap=dict(method=sut.BOOT_METHOD, repeats=5000, seed=20260928,
                confidence=.95, family_candidates=137),
            inherited_selection_requirements=dict(pooled_edge_positive=True, year2025_edge_positive=True,
                positive_years_min=2, simultaneous_lower_bound_gt_zero=True),
            test_specs=copy.deepcopy(list(sut.TEST_SPECS)),
            legacy=dict(numeric_ids=old["numeric_ids"]+list(sut.c7.TEST_IDS),
                exposure_ids=old["exposure_ids"]+list(sut.c7.TEST_IDS),
                failed_or_untestable=copy.deepcopy(old["failed_or_untestable"]))))


@pytest.mark.parametrize("field,value", [
    ("official_freeze", False), ("formal_freeze_applied", False),
    ("research_id", "RENAMED"), ("roles", list(sut.NEW_ROLES)),
    ("target", "ER_5D"), ("primary_eval_years", [2024, 2025]),
    ("mechanism_research_eligible", False), ("strict_PIT_promotion_eligible", True),
    ("test2026_locked", False), ("new2026_estimation_authorized", True),
])
def test_freeze_and_science_cannot_change(field, value):
    d = design(); d[field] = value
    with pytest.raises(ValueError):
        sut.validate_design(d)


@pytest.mark.parametrize("field,value", [
    ("common_mature_date_count", 731), ("year_counts", {"2024": 252, "2025": 230}),
    ("exposure_namespace", 148), ("test_specs", []),
])
def test_clock_and_sixteen_comparisons_locked(field, value):
    d = design(); d["evaluation"][field] = value
    with pytest.raises(ValueError):
        sut.validate_design(d)


@pytest.mark.parametrize("field,value", [("repeats", 150), ("seed", 1), ("confidence", .9), ("family_candidates", 121)])
def test_production_always_5000_shared_draws(field, value):
    d = design(); d["evaluation"]["bootstrap"][field] = value
    with pytest.raises(ValueError, match="SHARED_MAXT"):
        sut.validate_design(d)


def test_no_full_fixed_raw_or_ridge_promotion_test_and_legacy_not_new():
    assert sut.validate_design(design())["exposure_namespace"] == 149
    assert len(sut.NEW_ROLES) == 11 and len(sut.REFERENCES) == 6 and len(sut.TEST_IDS) == 16
    raw_tests = [s for s in sut.TEST_SPECS if s["right"] == sut.evidence.RAW]
    assert len(raw_tests) == 5
    assert all(s["left"].endswith(sut.NESTED_STATE) for s in raw_tests)
    assert not set(sut.REFERENCES) & set(sut.TEST_IDS)
    d = design(); d["evaluation"]["legacy"]["failed_or_untestable"] = {}
    with pytest.raises(ValueError, match="121_NUMERIC"):
        sut.validate_design(d)


def series():
    dates = pd.DatetimeIndex(np.concatenate([pd.bdate_range(f"{y}-01-02", periods=25).to_numpy() for y in sut.YEARS]))
    ids = design()["evaluation"]["legacy"]["numeric_ids"]
    rng = np.random.default_rng(22)
    old = pd.DataFrame(rng.normal(0, .02, (75, 121)), index=dates, columns=ids)
    new = pd.DataFrame(rng.normal(.004, .02, (75, 16)), index=dates, columns=sut.TEST_IDS)
    return dates, ids, old, new, {**design()["evaluation"]["bootstrap"], "repeats": 150}


def test_137_numeric_149_namespace_shared_existing_owner():
    dates, ids, old, new, rule = series()
    matrix, summaries, receipt, maxima = sut.statistics(old, new, np.arange(75), dates, rule, ids)
    _, _, previous, old_max = sut.evidence.shared_max_t(old.to_numpy(), np.arange(75), [True]*121,
        {**rule, "family_candidates": 121})
    assert matrix.shape == (75, 137) and len(summaries) == 16
    assert receipt["exposure_namespace"] == 149 and receipt["legacy_numeric_complete_series"] == 121
    assert receipt["legacy_shared_draw_sha256"] == previous["shared_draw_sha256"]
    assert np.all(maxima >= old_max-1e-12) and receipt["critical_max_t"] >= previous["critical_max_t"]-1e-12


def test_missing_tests_preserve_failure_without_zero_series_or_pruning():
    dates, ids, old, new, rule = series()
    missing = sut.TEST_IDS[:2]
    new = new.drop(columns=list(missing))
    matrix, summaries, receipt, _ = sut.statistics(old, new, np.arange(75), dates, rule, ids,
        {t: "DEPENDENCY_FAILED" for t in missing})
    assert matrix.shape == (75, 135) and matrix.index.equals(old.index)
    assert receipt["exposure_namespace"] == 149
    assert all(t not in matrix for t in missing)
    assert all(s["status"] == "FAILED_UNTESTABLE" and s["pooled_edge"] is None for s in summaries if s["test_id"] in missing)


def test_fixed_failure_does_not_erase_nested_raw():
    p = sut.PARADIGMS[0]; fixed = sut.role(p, sut.FIXED_STATE)
    available = {*sut.ALL_ROLES, sut.evidence.RAW}-{fixed}
    failed = sut.dependency_failures(available, {fixed: "FAILED"})
    assert f"C10_{p}_DATA_SCALE" in failed and f"C10_{p}_TRAINING_DEPTH" in failed
    assert sut.role(p, sut.NESTED_STATE) not in failed
    assert len(failed) == 2


def test_nested_failure_does_not_erase_data_scale():
    p = sut.PARADIGMS[0]; nested = sut.role(p, sut.NESTED_STATE)
    failed = sut.dependency_failures({*sut.ALL_ROLES, sut.evidence.RAW}-{nested}, {nested: "FAILED"})
    assert f"C10_{p}_DATA_SCALE" not in failed
    assert f"C10_{p}_TRAINING_DEPTH" in failed and nested in failed and len(failed) == 2


def test_ridge_sanity_and_depth_attribution_separate_from_selectors():
    summaries = [dict(test_id=t, supported=True) for t in sut.TEST_IDS]
    p = sut.PARADIGMS[0]
    next(s for s in summaries if s["test_id"] == f"C10_{p}_TRAINING_DEPTH")["supported"] = False
    state = sut.support_status(summaries)
    assert sut.role(p, sut.NESTED_STATE) in state["selector_supported"]
    assert p not in state["depth_attribution"] and state["ridge_sanity_supported"]
    assert all("RIDGE" not in r for r in state["selector_supported"])


def test_zero_se_and_negative_2025_never_supported():
    dates, ids, old, new, rule = series()
    new[sut.TEST_IDS[0]] = 0.
    new.loc[new.index.year == 2025, sut.TEST_IDS[1]] = -.5
    _, summaries, _, _ = sut.statistics(old, new, np.arange(75), dates, rule, ids)
    assert not summaries[0]["supported"] and not summaries[1]["supported"]


@pytest.mark.parametrize("mutation", ["future", "nonfinite", "date_drop", "position_swap", "test_overlap"])
def test_future_nonfinite_and_original_clock_guards(mutation):
    dates, ids, old, new, rule = series(); positions = np.arange(75)
    if mutation == "future": dates = dates.append(pd.DatetimeIndex(["2026-01-01"]))
    elif mutation == "nonfinite": new.iloc[0, 0] = np.nan
    elif mutation == "date_drop": new = new.iloc[1:]
    elif mutation == "position_swap": positions[[0, 1]] = positions[[1, 0]]
    else: new[ids[0]] = 0.
    with pytest.raises(ValueError):
        sut.statistics(old, new, positions, dates, rule, ids)


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    paths = SimpleNamespace(backtest_root=tmp_path/"backtests", results_root=tmp_path/"results")
    run, result = paths.backtest_root/"new", paths.results_root/"new"
    prior, prior_diag = paths.backtest_root/"old", paths.backtest_root/"old"/"diagnostics"/"selector_evidence"
    for p in (run, result, prior_diag): p.mkdir(parents=True)
    def put(path, body):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body) if isinstance(body, dict) else body, encoding="utf-8")
        return dict(path=str(path), sha256=sut.sha(path))
    d = design()
    old_pin = put(prior/"DESIGN_FREEZE.json", c7_design())
    assembly_pin = put(prior/"SCORE_ASSEMBLY.json", dict(complete_candidates=list(sut.c7.ROLES),
        complete_fixed_references=list(sut.c7.ANCHORS), failed_or_untestable={}, design_freeze_sha256=old_pin["sha256"]))
    legacy = d["evaluation"]["legacy"]
    legacy.update(design=old_pin, assembly=assembly_pin,
        evidence=put(prior_diag/"SELECTION_EVIDENCE.json", "MIXED_RESULT_SENTINEL_NOT_JSON"),
        edge=put(prior_diag/"PRIMARY_DAILY_EDGE.parquet", "synthetic-edge"),
        clock=put(prior_diag/"COMMON_DATE_MATURITY.parquet", "synthetic-clock"))
    train_pin = put(paths.results_root/"training.parquet", "synthetic-training")
    d["inputs"] = dict(training=train_pin)
    source_paths = (Path(sut.__file__), Path(sut.evidence.__file__), Path(sut.r5.__file__), Path(sut.c7.__file__), Path(reader.__file__))
    d["sources"] = {str(p):sut.sha(p) for p in source_paths}
    frozen = put(run/"DESIGN_FREEZE.json", d)["sha256"]
    dates = pd.DatetimeIndex(np.concatenate([pd.bdate_range(f"{y}-01-02", periods=n).to_numpy()
        for y, n in zip(sut.YEARS, (250, 252, 250))]))
    clock = pd.DataFrame(dict(signal_date=dates, included=np.r_[np.ones(732,dtype=bool),np.zeros(20,dtype=bool)]))
    included = dates[clock.included]
    rng = np.random.default_rng(32)
    edges = pd.DataFrame(rng.normal(0,.01,(732,121)), columns=legacy["numeric_ids"])
    edges.insert(0,"signal_date",included)
    panels, bindings = {}, {}
    for cid in (sut.evidence.RAW, *sut.ALL_ROLES):
        frame = pd.DataFrame(dict(signal_date=np.repeat(dates,21),security_uid=np.tile(np.arange(21),752)))
        frame["ticker"] = frame.security_uid.map(lambda x:f"T{x}")
        frame["U_t_fingerprint"] = "FIXED_FULL_U"
        frame["score"] = -frame.security_uid.astype(float)
        frame["rank"] = frame.security_uid+1
        frame["candidate_id"] = cid
        panels[cid] = frame
        bindings[cid] = put(sut.score_path(run,cid), "synthetic-score-"+cid)
    assembly = dict(complete_candidates=list(sut.NEW_ROLES), complete_fixed_references=list(sut.REFERENCES),
        failed_or_untestable={}, forecast2026_rows=0, design_freeze_sha256=frozen,
        score_paths=bindings, common_rows=752*21, common_dates=752)
    def save_assembly():
        a = put(run/"SCORE_ASSEMBLY.json",assembly)
        put(run/"EVALUATION_CODE_ACTIVATION.json", dict(design_freeze_sha256=frozen,
            score_assembly_sha256=a["sha256"],sources=d["sources"]))
    save_assembly()
    labels = panels[sut.evidence.RAW][sut.evidence.KEY].copy()
    labels["target"] = np.tile(np.linspace(-.1,.1,21),752)
    labels["label_end_date"] = labels.signal_date+pd.Timedelta(days=1)
    module = ModuleType("scripts.research.a2.training.selector_training_sufficiency")
    module.checked = lambda root:(dict(results_directory=str(result)),d)
    monkeypatch.setitem(sys.modules,module.__name__,module)
    monkeypatch.setattr(sut,"resolve",lambda _:paths)
    monkeypatch.setattr(sut,"assert_safe_output_path",lambda *a,**k:None)
    monkeypatch.setattr(sut.evidence,"prove_label_boundary",lambda *a,**k:None)
    def projection(path,columns,fields):
        p = Path(path)
        frame = clock if p == Path(legacy["clock"]["path"]) else edges if p == Path(legacy["edge"]["path"]) else labels
        return frame[columns].copy()
    monkeypatch.setattr(sut,"pre2026",projection)
    monkeypatch.setattr(sut.r5,"pre2026",projection)
    monkeypatch.setattr(sut.c7,"score_panel",lambda root,cid:(panels[cid].copy(),sut.sha(sut.score_path(root,cid))))
    calls = []
    def fast_diagnose(tid,reference,scores,ranks,right_ranks,mature,common):
        calls.append((tid,right_ranks.copy()))
        metrics = ["ic","spearman_ic","ndcg20","truth_top20_recall","top20_target_mean",
            "precision_target_positive","overlap20","score_std","score_iqr","rank_migration_mean_absolute"]
        return [dict(candidate_id=tid,signal_date=date,common_mature_date=bool(common.loc[date]),
            replacement_edge=.001+(i%7)*.0001,**{m:0. for m in metrics}) for i,date in enumerate(dates)]
    monkeypatch.setattr(sut.evidence,"diagnose",fast_diagnose)
    owner = sut.evidence.shared_max_t
    monkeypatch.setattr(sut.evidence,"shared_max_t",lambda x,p,c,r:owner(x,p,c,{**r,"repeats":150}))
    return SimpleNamespace(run=run,result=result,design=d,assembly=assembly,panels=panels,labels=labels,
        save_assembly=save_assembly,clock=clock,paths=paths,calls=calls)


def test_pipeline_only_16_tests_and_no_mixed_evidence_body_read(pipeline):
    receipt = sut.run(pipeline.run)
    assert len(pipeline.calls) == 16 and {t for t,_ in pipeline.calls} == set(sut.TEST_IDS)
    assert receipt["bootstrap"]["numeric_complete_series"] == 137 and receipt["exposure_namespace"] == 149
    assert len(receipt["exact_reused_references"]) == 6 and not receipt["full_fixed_vs_raw_tests"]
    assert not receipt["ridge_promotion_allowed"] and not receipt["strict_PIT_promotion_eligible"]
    assert receipt["common_mature_dates"] == 732 and receipt["original_calendar_dates"] == 752
    assert receipt["common_year_dates"] == {"2023":250,"2024":252,"2025":230}
    assert receipt["test2026_rows_read"] == 0
    with pytest.raises(FileExistsError,match="PRESERVE_EXISTING"):
        sut.run(pipeline.run)


def test_pipeline_partial_fixed_failure_keeps_nested_raw(pipeline):
    fixed = sut.role(sut.PARADIGMS[0],sut.FIXED_STATE)
    pipeline.assembly["complete_candidates"].remove(fixed)
    pipeline.assembly["failed_or_untestable"][fixed] = "FAILED_SCIENTIFIC_SLOT"
    pipeline.save_assembly()
    receipt = sut.run(pipeline.run)
    p = sut.PARADIGMS[0]
    assert receipt["bootstrap"]["numeric_complete_series"] == 135
    assert f"C10_{p}_DATA_SCALE" in receipt["failed_tests"] and f"C10_{p}_TRAINING_DEPTH" in receipt["failed_tests"]
    assert sut.role(p,sut.NESTED_STATE) not in receipt["failed_tests"]
    assert receipt["exposure_namespace"] == 149 and receipt["common_mature_dates"] == 732


def test_pipeline_new_selected_immaturity_fails_dependencies_no_date_drop(pipeline):
    # UID20 is outside Raw/reference Top20. A new selector chooses it.
    cid = sut.role(sut.PARADIGMS[0],sut.FIXED_STATE)
    date = pipeline.clock.loc[pipeline.clock.included,"signal_date"].iloc[0]
    mask = pipeline.panels[cid].signal_date.eq(date)
    pipeline.panels[cid].loc[mask,"score"] = pipeline.panels[cid].loc[mask,"security_uid"].astype(float)
    pipeline.panels[cid].loc[mask,"rank"] = 21-pipeline.panels[cid].loc[mask,"security_uid"]
    pipeline.labels.loc[pipeline.labels.signal_date.eq(date)&pipeline.labels.security_uid.eq(20),"label_end_date"] = pd.NaT
    pipeline.labels.loc[pipeline.labels.signal_date.eq(date)&pipeline.labels.security_uid.eq(20),"target"] = np.nan
    receipt = sut.run(pipeline.run)
    assert cid in receipt["failed_roles"] and len(receipt["failed_tests"]) == 2
    assert receipt["common_mature_dates"] == 732 and receipt["bootstrap"]["numeric_complete_series"] == 135


def test_legacy_namespace_and_pin_cannot_be_repackaged(pipeline):
    legacy = pipeline.design["evaluation"]["legacy"]
    bad = copy.deepcopy(legacy); bad["numeric_ids"][0] = "NEW_NAME"
    with pytest.raises(ValueError,match="CLOSED_C7_LINEAGE"):
        sut._legacy_identity(bad,pipeline.paths)
    Path(legacy["evidence"]["path"]).write_text("changed",encoding="utf-8")
    with pytest.raises(ValueError,match="ARTIFACT_PIN_CHANGED"):
        sut._legacy_identity(legacy,pipeline.paths)


def test_identity_swap_and_activation_source_change_rejected(pipeline):
    cid = sut.NEW_ROLES[0]
    pipeline.panels[cid].iloc[0,pipeline.panels[cid].columns.get_loc("ticker")] = "SWAPPED"
    with pytest.raises(ValueError,match="EXACT_FULL_COMMON"):
        sut.run(pipeline.run)
    pipeline.design["sources"][str(Path(sut.__file__))] = "0"*64
    with pytest.raises(ValueError,match="FROZEN_EVALUATION"):
        sut.run(pipeline.run)
