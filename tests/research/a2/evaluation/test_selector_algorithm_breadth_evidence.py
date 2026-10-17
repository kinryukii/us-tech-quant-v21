"""Synthetic evidence tests; no real labels, 2026 observations or learner fits."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.evaluation import selector_algorithm_breadth_evidence as sut
from scripts.research.a2.evaluation import selector_frozen_history_evidence as r4


def old_design():
    ids = [f"old_{i:02d}" for i in range(91)]
    return dict(official_freeze=True, formal_freeze_applied=True,
        mechanism_research_eligible=True, strict_PIT_promotion_eligible=False,
        roles=list(r4.ROLES), fixed_reference_roles=list(r4.REFERENCES),
        target="MEAN_ER_3D_5D_10D_20D", primary_eval_years=list(sut.YEARS),
        test2026_locked=True, monthly2026_estimation_authorized=False,
        evaluation=dict(primary=sut.PRIMARY, common_mature_date_count=732,
            year_counts=sut.YEAR_COUNTS.copy(), candidate_namespace=95,
            contrast_namespace=4, exposure_namespace=99,
            bootstrap=dict(method=sut.BOOT_METHOD, repeats=5000, seed=20260928, confidence=.95),
            fixed_mechanism_pairs=[[a, b] for _, a, b in r4.CONTRASTS],
            inherited_selection_requirements=dict(pooled_edge_positive=True,
                year2025_edge_positive=True, positive_years_min=2, simultaneous_lower_bound_gt_zero=True),
            legacy=dict(candidate_ids=ids, complete_ids=ids[:79],
                failed_or_untestable={i: "RETAINED_SYNTHETIC_FAILURE" for i in ids[79:]})))


def design():
    old = old_design()["evaluation"]["legacy"]
    numeric = [*old["complete_ids"], *r4.ROLES, *[c[0] for c in r4.CONTRASTS]]
    exposure = [*old["candidate_ids"], *r4.ROLES, *[c[0] for c in r4.CONTRASTS]]
    return dict(official_freeze=True, formal_freeze_applied=True, research_id=sut.RESEARCH_ID,
        mechanism_research_eligible=True, strict_PIT_promotion_eligible=False,
        roles=list(sut.ROLES), target="MEAN_ER_3D_5D_10D_20D", primary_eval_years=list(sut.YEARS),
        test2026_locked=True, new2026_estimation_authorized=False,
        evaluation=dict(primary=sut.PRIMARY, common_mature_date_count=732,
            year_counts=sut.YEAR_COUNTS.copy(), exposure_namespace=117,
            bootstrap=dict(method=sut.BOOT_METHOD, repeats=5000, seed=20260928, confidence=.95),
            inherited_selection_requirements=dict(pooled_edge_positive=True,
                year2025_edge_positive=True, positive_years_min=2, simultaneous_lower_bound_gt_zero=True),
            legacy=dict(numeric_ids=numeric, exposure_ids=exposure,
                        failed_or_untestable=copy.deepcopy(old["failed_or_untestable"]))))


@pytest.mark.parametrize("field,value", [
    ("official_freeze", False), ("formal_freeze_applied", False),
    ("mechanism_research_eligible", False), ("strict_PIT_promotion_eligible", True),
    ("roles", list(sut.ROLES)[1:]), ("target", "EXECUTABLE_NET_PROFIT"),
    ("primary_eval_years", [2024, 2025]), ("test2026_locked", False),
    ("new2026_estimation_authorized", True), ("research_id", "RENAMED_OLD_STUDY"),
])
def test_question_and_boundaries_cannot_change(field, value):
    d = design()
    d[field] = value
    with pytest.raises(ValueError):
        sut.validate_design(d)


@pytest.mark.parametrize("field,value", [
    ("common_mature_date_count", 731), ("year_counts", {"2024": 252, "2025": 230}),
    ("exposure_namespace", 18), ("primary", "BEST_YEAR_EDGE"),
])
def test_common_clock_and_all_historical_exposure_frozen(field, value):
    d = design()
    d["evaluation"][field] = value
    with pytest.raises(ValueError, match="ORIGINAL_732"):
        sut.validate_design(d)


@pytest.mark.parametrize("field,value", [("repeats", 1000), ("seed", 1), ("confidence", .9)])
def test_bootstrap_rule_cannot_change(field, value):
    d = design()
    d["evaluation"]["bootstrap"][field] = value
    with pytest.raises(ValueError, match="SHARED_MAXT"):
        sut.validate_design(d)


def test_failed_history_never_reset_or_counted_as_numeric():
    d = design()
    assert sut.validate_design(d)["exposure_namespace"] == 117
    d["evaluation"]["legacy"]["failed_or_untestable"] = {}
    with pytest.raises(ValueError, match="CLOSED_87"):
        sut.validate_design(d)


@pytest.fixture(scope="module")
def series():
    dates = pd.DatetimeIndex(np.concatenate([
        pd.bdate_range(f"{y}-01-02", periods=25).to_numpy() for y in sut.YEARS]))
    ids = design()["evaluation"]["legacy"]["numeric_ids"]
    rng = np.random.default_rng(819)
    old = pd.DataFrame(rng.normal(0, .02, (75, 87)), index=dates, columns=ids)
    new = pd.DataFrame(rng.normal(.005, .02, (75, 18)), index=dates, columns=sut.ROLES)
    return dates, ids, old, new


def test_105_actual_series_117_exposure_same_draws_and_never_lower_max(series):
    dates, ids, old, new = series
    matrix, summaries, receipt, maxima = sut.statistics(old, new, np.arange(75), dates,
        design()["evaluation"]["bootstrap"], ids)
    assert len(matrix.columns) == 105 and list(matrix.columns[:87]) == ids
    assert receipt["numeric_complete_series"] == 105 and receipt["exposure_namespace"] == 117
    assert receipt["shared_draw_sha256"] == receipt["legacy_shared_draw_sha256"]
    assert receipt["critical_max_t"] + 1e-12 >= receipt["legacy_critical_max_t"]
    assert receipt["minimum_draw_wise_max_increment"] >= -1e-12
    assert len(maxima) == 5000 and len(summaries) == 18
    assert not receipt["legacy_R2_reselected"] and not receipt["legacy_R4_reselected"]
    assert all(s["strict_PIT_promotion_eligible"] is False for s in summaries)
    assert not any(s["economic_promotion_allowed"] for s in summaries)


def test_failed_new_roles_all_remain_exposure_but_never_zero_placeholders(series):
    dates, ids, old, new = series
    failed = {cid: "SYNTHETIC_FAILURE" for cid in sut.ROLES}
    matrix, summaries, receipt, _ = sut.statistics(old, new.iloc[:, :0], np.arange(75), dates,
        design()["evaluation"]["bootstrap"], ids, failed)
    assert list(matrix) == ids and receipt["numeric_complete_series"] == 87
    assert receipt["exposure_namespace"] == 117 and len(summaries) == 18
    assert all(s["pooled_edge"] is None and s["bootstrap_se"] is None for s in summaries)
    assert all(s["status"] == "FAILED_UNTESTABLE" and not s["mechanism_supported"] for s in summaries)


def test_constant_score_edge_cannot_create_research_support(series):
    dates, ids, old, new = series
    new = new.copy()
    new[sut.ROLES[0]] = .05
    _, summaries, _, _ = sut.statistics(old, new, np.arange(75), dates,
        design()["evaluation"]["bootstrap"], ids)
    s = summaries[0]
    assert s["simultaneous_lower_95"] is None
    assert not s["research_support_conditions"]["nonzero_bootstrap_se"]
    assert not s["mechanism_supported"]


def test_calendar_positions_cannot_be_reindexed_and_nan_cannot_be_filtered(series):
    dates, ids, old, new = series
    with pytest.raises(ValueError, match="ORIGINAL_CALENDAR"):
        sut.statistics(old, new, np.arange(75), dates.insert(0, pd.Timestamp("2022-12-30")),
                       design()["evaluation"]["bootstrap"], ids)
    old = old.copy()
    old.iloc[0, 0] = np.nan
    with pytest.raises(ValueError, match="EXACT_FINITE"):
        sut.statistics(old, new, np.arange(75), dates, design()["evaluation"]["bootstrap"], ids)


def test_2026_footer_block_precedes_value_projection(tmp_path, monkeypatch):
    path = tmp_path / "mixed.parquet"
    pd.DataFrame(dict(signal_date=pd.to_datetime(["2025-12-31", "2026-01-02"]),
        target_end_date=pd.to_datetime(["2025-12-31", "2026-01-05"]),
        target=[1., 2.])).to_parquet(path, index=False)
    monkeypatch.setattr(sut.evidence.pq, "read_table", lambda *a, **k: pytest.fail("forbidden value projection"))
    with pytest.raises(ValueError, match="PHYSICAL_PRE2026"):
        sut.evidence.prove_label_boundary(path, "target_end_date")


def _putj(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def _pin(path):
    return dict(path=str(path), sha256=sut.sha(path))


def _freeze(run, d):
    _putj(run / "DESIGN_FREEZE.json", d)
    digest = sut.sha(run / "DESIGN_FREEZE.json")
    _putj(run / "DESIGN_FREEZE_SHA.json", dict(sha256=digest))
    cfg = sut.readj(run / "run_config.json")
    cfg["design_freeze_sha256"] = digest
    _putj(run / "run_config.json", cfg)
    assembly = sut.readj(run / "SCORE_ASSEMBLY.json")
    assembly["design_freeze_sha256"] = digest
    _putj(run / "SCORE_ASSEMBLY.json", assembly)
    _putj(run / "EVALUATION_CODE_ACTIVATION.json", dict(design_freeze_sha256=digest,
        score_assembly_sha256=sut.sha(run / "SCORE_ASSEMBLY.json"), sources=d["sources"]))


def pipeline_fixture(tmp_path, monkeypatch, immature=False, failed=False):
    backtest, results = tmp_path / "backtest", tmp_path / "results"
    run, out, old = backtest / "new", results / "new", backtest / "old"
    for p in (run / "predictions", old / "diagnostics", out):
        p.mkdir(parents=True)
    # Exact frozen 752 calendar and 732 maturity positions; all dates synthetic.
    dates = pd.DatetimeIndex(np.concatenate([pd.bdate_range(f"{y}-01-02", periods=n).to_numpy()
        for y, n in ((2023, 250), (2024, 252), (2025, 250))]))
    included = np.arange(len(dates)) < 732
    rng = np.random.default_rng(921)
    raw = pd.DataFrame([dict(signal_date=date, ticker=f"S{j:02d}", security_uid=f"UID{j:02d}",
        U_t_fingerprint="SYNTHETIC_FULL_U_T", candidate_id=sut.evidence.RAW,
        score=float(21-j), rank=j+1, target=float(rng.normal(.001, .02)) if included[i] else np.nan,
        label_end_date=date+pd.Timedelta(days=1) if included[i] else pd.NaT)
        for i, date in enumerate(dates) for j in range(21)])
    if immature:
        at = raw.signal_date.eq(dates[0]) & raw.security_uid.eq("UID20")
        raw.loc[at, "target"] = np.nan
        raw.loc[at, "label_end_date"] = pd.NaT
    raw_path = run / "predictions" / f"scores_{sut.evidence.RAW}_pre2026.parquet"
    raw.to_parquet(raw_path, index=False)
    bindings = {sut.evidence.RAW: _pin(raw_path)}
    for k, cid in enumerate(sut.ROLES):
        panel = raw.drop(columns=["target", "label_end_date"]).copy()
        panel["candidate_id"] = cid
        if immature:
            if k == 0:
                panel.loc[panel.security_uid.eq("UID20"), "score"] = 2.5
        else:
            panel["score"] = rng.normal(size=len(panel))
        panel = panel.sort_values(["signal_date", "score", "security_uid"],
                                  ascending=[True, False, True], kind="stable")
        panel["rank"] = panel.groupby("signal_date").cumcount()+1
        path = run / "predictions" / f"scores_{cid}_pre2026.parquet"
        panel.to_parquet(path, index=False)
        bindings[cid] = _pin(path)
    clock_path, edge_path = old / "diagnostics/COMMON_DATE_MATURITY.parquet", old / "diagnostics/PRIMARY_DAILY_EDGE.parquet"
    pd.DataFrame(dict(signal_date=dates, included=included)).to_parquet(clock_path, index=False)
    d = design()
    legacy = d["evaluation"]["legacy"]
    edges = pd.DataFrame(rng.normal(0, .02, (732, 87)), columns=legacy["numeric_ids"])
    # Frozen failed columns may physically exist; reader must not consume them.
    for cid in legacy["failed_or_untestable"]:
        edges[cid] = np.nan
    edges.insert(0, "signal_date", dates[included])
    edges.to_parquet(edge_path, index=False)
    old_design_path, old_assembly_path = old / "DESIGN_FREEZE.json", old / "SCORE_ASSEMBLY.json"
    _putj(old_design_path, old_design())
    _putj(old_assembly_path, dict(complete_candidates=list(r4.ROLES),
        complete_fixed_references=list(r4.REFERENCES), failed_or_untestable={}))
    legacy.update(edge=_pin(edge_path), clock=_pin(clock_path), design=_pin(old_design_path), assembly=_pin(old_assembly_path))
    training_path = results / "training.parquet"
    pd.DataFrame(dict(signal_date=dates, target_end_date=dates)).to_parquet(training_path, index=False)
    d["inputs"] = {"training": _pin(training_path)}
    d["sources"] = {str(s): sut.sha(s) for s in (Path(sut.__file__), Path(sut.evidence.__file__),
        sut.REPO / "scripts/research/a2/evaluation/selector_account_compare.py")}
    _putj(run / "run_config.json", dict(research_line="C_SELECTOR", research_id=sut.RESEARCH_ID,
        results_directory=str(out)))
    _putj(run / "SCORE_ASSEMBLY.json", dict(complete_candidates=[] if failed else list(sut.ROLES),
        failed_or_untestable={cid: "SYNTHETIC_FAILURE" for cid in sut.ROLES} if failed else {},
        forecast2026_rows=0, common_rows=len(raw), common_dates=len(dates), score_paths=bindings))
    _freeze(run, d)
    paths = SimpleNamespace(backtest_root=backtest, results_root=results)
    monkeypatch.setattr(sut, "resolve", lambda repo: paths)
    monkeypatch.setattr(sut, "assert_safe_output_path", lambda p, **k: None)
    module = ModuleType("scripts.research.a2.training.selector_algorithm_breadth")
    def checked(directory):
        cfg = sut.readj(directory / "run_config.json")
        freeze = directory / "DESIGN_FREEZE.json"
        assert sut.sha(freeze) == cfg["design_freeze_sha256"] == sut.readj(directory / "DESIGN_FREEZE_SHA.json")["sha256"]
        return cfg, sut.readj(freeze)
    module.checked = checked
    import scripts.research.a2.training as package
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(package, "selector_algorithm_breadth", module, raising=False)
    return run, out


def test_full_production_adapter_synthetic_732_clock_and_105_columns(tmp_path, monkeypatch):
    run, out = pipeline_fixture(tmp_path, monkeypatch)
    receipt = sut.run(run)
    assert receipt["common_mature_dates"] == 732 and receipt["common_year_dates"] == sut.YEAR_COUNTS
    assert receipt["bootstrap"]["numeric_complete_series"] == 105
    assert len(receipt["exposure_roles"]) == 117 and len(receipt["candidates"]) == 18
    assert receipt["finalists"] == [] and not receipt["economic_promotion_allowed"]
    assert not receipt["financial_verified"] and receipt["test2026_rows_read"] == 0
    matrix = pd.read_parquet(run / "diagnostics/selector_evidence/PRIMARY_DAILY_EDGE.parquet")
    assert matrix.shape == (732, 106)
    assert not set(receipt["legacy_failed_or_untestable"]) & set(matrix)
    assert len(pd.read_parquet(run / "diagnostics/selector_evidence/COMMON_DATE_MATURITY.parquet")) == 752
    assert (out / "SELECTION_EVIDENCE.json").is_file()
    with pytest.raises(FileExistsError, match="PRESERVE"):
        sut.run(run)


def test_immature_new_top20_marks_only_role_untestable_without_clock_shrink(tmp_path, monkeypatch):
    run, _ = pipeline_fixture(tmp_path, monkeypatch, immature=True)
    receipt = sut.run(run)
    assert receipt["common_mature_dates"] == 732
    assert receipt["bootstrap"]["numeric_complete_series"] == 104
    assert receipt["exposure_namespace"] == 117 and len(receipt["candidates"]) == 18
    failed = receipt["candidates"][0]
    assert failed["candidate_id"] == sut.ROLES[0] and failed["status"] == "FAILED_UNTESTABLE"
    assert failed["pooled_edge"] is None and "NO_SHRINK" in failed["failure_reason"]
    matrix = pd.read_parquet(run / "diagnostics/selector_evidence/PRIMARY_DAILY_EDGE.parquet")
    assert len(matrix) == 732 and sut.ROLES[0] not in matrix
    yearly = pd.read_parquet(run / "diagnostics/selector_evidence/YEAR_DIAGNOSTICS.parquet")
    missing = yearly.loc[yearly.candidate_id.eq(sut.ROLES[0])]
    assert list(missing.year) == list(sut.YEARS) and missing.ic.isna().all()


def test_no_real_reader_before_formal_freeze(tmp_path, monkeypatch):
    run, _ = pipeline_fixture(tmp_path, monkeypatch, failed=True)
    d = sut.readj(run / "DESIGN_FREEZE.json")
    d["official_freeze"] = False
    _freeze(run, d)
    monkeypatch.setattr(sut, "score_panel", lambda *a, **k: pytest.fail("outcome read before freeze"))
    monkeypatch.setattr(sut, "pre2026", lambda *a, **k: pytest.fail("outcome projection before freeze"))
    with pytest.raises(ValueError, match="FORMAL_FREEZE"):
        sut.run(run)


def test_changed_assembly_binding_fails_before_score_projection(tmp_path, monkeypatch):
    run, _ = pipeline_fixture(tmp_path, monkeypatch)
    assembly = sut.readj(run / "SCORE_ASSEMBLY.json")
    assembly["score_paths"][sut.ROLES[0]]["sha256"] = "0" * 64
    _putj(run / "SCORE_ASSEMBLY.json", assembly)
    activation = sut.readj(run / "EVALUATION_CODE_ACTIVATION.json")
    activation["score_assembly_sha256"] = sut.sha(run / "SCORE_ASSEMBLY.json")
    _putj(run / "EVALUATION_CODE_ACTIVATION.json", activation)
    actual = sut.score_panel
    monkeypatch.setattr(sut, "score_panel", lambda directory, cid: actual(directory, cid)
        if cid == sut.evidence.RAW else pytest.fail("unbound candidate projection"))
    with pytest.raises(ValueError, match="BINDING_CHANGED"):
        sut.run(run)


def test_changed_raw_binding_fails_before_label_projection(tmp_path, monkeypatch):
    run, _ = pipeline_fixture(tmp_path, monkeypatch)
    assembly = sut.readj(run / "SCORE_ASSEMBLY.json")
    assembly["score_paths"][sut.evidence.RAW]["sha256"] = "0" * 64
    _putj(run / "SCORE_ASSEMBLY.json", assembly)
    activation = sut.readj(run / "EVALUATION_CODE_ACTIVATION.json")
    activation["score_assembly_sha256"] = sut.sha(run / "SCORE_ASSEMBLY.json")
    _putj(run / "EVALUATION_CODE_ACTIVATION.json", activation)
    monkeypatch.setattr(sut, "score_panel", lambda *a, **k: pytest.fail("unbound Raw projection"))
    with pytest.raises(ValueError, match="RAW_SCORE_BINDING_CHANGED"):
        sut.run(run)
