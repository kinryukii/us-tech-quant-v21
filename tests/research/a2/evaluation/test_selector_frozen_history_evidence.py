"""Synthetic tests only; no retained research data or outcome access."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.evaluation import selector_frozen_history_evidence as sut


def design():
    ids = [f"old_{i:02d}" for i in range(91)]
    return dict(
        official_freeze=True, formal_freeze_applied=True, research_id="SYNTHETIC_C_FH",
        mechanism_research_eligible=True, strict_PIT_promotion_eligible=False,
        roles=list(sut.ROLES), fixed_reference_roles=list(sut.REFERENCES),
        target="MEAN_ER_3D_5D_10D_20D", primary_eval_years=list(sut.YEARS),
        test2026_locked=True, monthly2026_estimation_authorized=False,
        evaluation=dict(
            common_mature_date_count=732, year_counts=sut.YEAR_COUNTS.copy(),
            primary=sut.PRIMARY, candidate_namespace=95, contrast_namespace=4,
            exposure_namespace=99,
            bootstrap=dict(method=sut.BOOT_METHOD, repeats=5000, seed=20260928, confidence=.95),
            fixed_mechanism_pairs=[[a, b] for _, a, b in sut.CONTRASTS],
            inherited_selection_requirements=dict(pooled_edge_positive=True,
                year2025_edge_positive=True, positive_years_min=2,
                simultaneous_lower_bound_gt_zero=True),
            legacy=dict(candidate_ids=ids, complete_ids=ids[:79],
                failed_or_untestable={i: "RETAINED_SYNTHETIC_FAILURE" for i in ids[79:]})))


def test_dual_eligibility_and_fixed_question():
    assert sut.validate_design(design())["exposure_namespace"] == 99


@pytest.mark.parametrize("field,value", [
    ("official_freeze", False), ("formal_freeze_applied", False),
    ("mechanism_research_eligible", False), ("strict_PIT_promotion_eligible", True),
    ("roles", list(sut.ROLES) + ["FIFTH_ROLE"]),
    ("fixed_reference_roles", []), ("target", "NET_EXECUTION_TARGET"),
    ("primary_eval_years", [2024, 2025]), ("test2026_locked", False),
    ("monthly2026_estimation_authorized", True),
])
def test_scientific_contract_change_rejected(field, value):
    d = design()
    d[field] = value
    with pytest.raises(ValueError):
        sut.validate_design(d)


@pytest.mark.parametrize("field,value", [
    ("common_mature_date_count", 482), ("year_counts", {"2024": 252, "2025": 230}),
    ("candidate_namespace", 4), ("exposure_namespace", 8),
    ("contrast_namespace", 0), ("fixed_mechanism_pairs", []),
])
def test_legacy_exposure_or_clock_cannot_be_dropped(field, value):
    d = design()
    d["evaluation"][field] = value
    with pytest.raises(ValueError):
        sut.validate_design(d)


def test_failed_legacy_history_cannot_be_reset():
    d = design()
    d["evaluation"]["legacy"]["failed_or_untestable"] = {}
    with pytest.raises(ValueError, match="CLOSED_91"):
        sut.validate_design(d)


@pytest.mark.parametrize("field,value", [("confidence", .9), ("repeats", 1000), ("seed", 1)])
def test_threshold_and_shared_bootstrap_frozen(field, value):
    d = design()
    d["evaluation"]["bootstrap"][field] = value
    with pytest.raises(ValueError, match="SHARED_MAXT"):
        sut.validate_design(d)


def series_fixture():
    dates = pd.DatetimeIndex(np.concatenate([
        pd.bdate_range(f"{y}-01-02", periods=25).to_numpy() for y in sut.YEARS]))
    ids = design()["evaluation"]["legacy"]["complete_ids"]
    rng = np.random.default_rng(714)
    old = pd.DataFrame(rng.normal(0, .02, (75, 79)), index=dates, columns=ids)
    new = pd.DataFrame(rng.normal(.005, .02, (75, 6)), index=dates,
                       columns=sut.ROLES + sut.REFERENCES)
    return dates, ids, old, new


def test_actual_complete_columns_and_shared_draws_preserve_threshold():
    dates, ids, old, new = series_fixture()
    matrix, summaries, receipt, maxima, failed = sut.statistics(
        old, new, np.arange(len(dates)), dates, design()["evaluation"]["bootstrap"], ids)
    assert len(matrix.columns) == 87
    assert list(matrix.columns[:79]) == ids
    assert receipt["exposure_namespace"] == 99
    assert receipt["numeric_complete_series"] == 87
    assert receipt["legacy_shared_draw_sha256"] == receipt["shared_draw_sha256"]
    assert receipt["critical_max_t"] + 1e-12 >= receipt["legacy_critical_max_t"]
    assert receipt["minimum_draw_wise_max_increment"] >= -1e-12
    assert len(maxima) == 5000 and not failed
    for cid, full, ref in sut.CONTRASTS:
        np.testing.assert_allclose(matrix[cid], new[full] - new[ref])
    assert len(summaries) == 8
    assert all(s["strict_PIT_promotion_eligible"] is False for s in summaries)
    assert all(s["economic_promotion_allowed"] is False for s in summaries)


def test_failed_new_roles_are_metadata_not_zero_series():
    dates, ids, old, new = series_fixture()
    new = new.iloc[:, :0]
    matrix, summaries, receipt, _, failed = sut.statistics(
        old, new, np.arange(len(dates)), dates, design()["evaluation"]["bootstrap"], ids)
    assert list(matrix) == ids and not summaries
    assert receipt["numeric_complete_series"] == 79 and len(failed) == 4


def test_zero_se_cannot_create_support():
    dates, ids, old, new = series_fixture()
    new[sut.ROLES[0]] = .05
    _, summaries, _, _, _ = sut.statistics(
        old, new, np.arange(len(dates)), dates, design()["evaluation"]["bootstrap"], ids)
    summary = next(s for s in summaries if s["test_id"] == sut.ROLES[0])
    assert not summary["research_support_conditions"]["nonzero_bootstrap_se"]
    assert summary["simultaneous_lower_95"] is None
    assert not summary["mechanism_supported"]


def test_clock_positions_cannot_be_reindexed_after_exclusions():
    dates, ids, old, new = series_fixture()
    wrong_calendar = dates.insert(0, pd.Timestamp("2022-12-30"))
    with pytest.raises(ValueError, match="ORIGINAL_CALENDAR_POSITIONS"):
        sut.statistics(old, new, np.arange(len(dates)), wrong_calendar,
                       design()["evaluation"]["bootstrap"], ids)


def test_future_or_nonfinite_edge_is_not_silently_filtered():
    dates, ids, old, new = series_fixture()
    old.iloc[0, 0] = np.nan
    with pytest.raises(ValueError, match="EXACT_FINITE_COMMON_CLOCK"):
        sut.statistics(old, new, np.arange(len(dates)), dates,
                       design()["evaluation"]["bootstrap"], ids)


def test_full_minus_reference_edge_equals_direct_pair_replacement():
    target = np.linspace(-.08, .09, 25)
    raw = np.arange(25) < 20
    annual = np.arange(25) >= 5
    monthly = (np.arange(25) >= 2) & (np.arange(25) < 22)
    difference = (sut.evidence.replacement_edge(target, raw, monthly)
                  - sut.evidence.replacement_edge(target, raw, annual))
    direct = sut.evidence.replacement_edge(target, annual, monthly)
    assert difference == pytest.approx(direct)


def test_footer_rejects_2026_before_value_projection(tmp_path, monkeypatch):
    path = tmp_path / "mixed.parquet"
    pd.DataFrame(dict(signal_date=pd.to_datetime(["2025-12-31", "2026-01-02"]),
                      target_end_date=pd.to_datetime(["2025-12-31", "2026-01-05"]),
                      target=[1., 2.])).to_parquet(path, index=False)
    monkeypatch.setattr(sut.pq, "read_table", lambda *a, **k: pytest.fail("value projection forbidden"))
    with pytest.raises(ValueError, match="PHYSICAL_PRE2026"):
        sut.evidence.prove_label_boundary(path, "target_end_date")


def _putj(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def _pin(path):
    return {"path": str(path), "sha256": sut.sha(path)}


def pipeline_fixture(tmp_path):
    backtest, results = tmp_path / "backtest", tmp_path / "results"
    run, out, old = backtest / "new", results / "new", backtest / "old"
    for p in (run / "predictions", old / "diagnostics", out):
        p.mkdir(parents=True)
    dates = pd.DatetimeIndex(np.concatenate([
        pd.bdate_range(f"{y}-01-02", periods=n).to_numpy()
        for y, n in ((2023, 250), (2024, 252), (2025, 252))]))
    included = dates.year < 2025
    included |= (dates.year == 2025) & (np.arange(len(dates)) < 732)
    rng = np.random.default_rng(1711)
    labels = rng.normal(.001, .02, (len(dates), 21))
    rows = []
    for i, date in enumerate(dates):
        for j in range(21):
            rows.append(dict(signal_date=date, ticker=f"S{j:02d}", security_uid=f"UID{j:02d}",
                U_t_fingerprint="SYNTHETIC_FULL_U_T", candidate_id=sut.evidence.RAW,
                score=float(21 - j), rank=j + 1,
                target=float(labels[i, j]) if included[i] else np.nan,
                label_end_date=date + pd.Timedelta(days=1) if included[i] else pd.NaT))
    raw = pd.DataFrame(rows)
    raw_path = run / "predictions" / f"scores_{sut.evidence.RAW}_pre2026.parquet"
    raw.to_parquet(raw_path, index=False)
    for cid in sut.ROLES + sut.REFERENCES:
        panel = raw.drop(columns=["target", "label_end_date"]).copy()
        panel["candidate_id"] = cid
        panel["score"] = rng.normal(size=len(panel))
        panel = panel.sort_values(["signal_date", "score", "security_uid"],
                                  ascending=[True, False, True], kind="stable")
        panel["rank"] = panel.groupby("signal_date").cumcount() + 1
        panel.to_parquet(run / "predictions" / f"scores_{cid}_pre2026.parquet", index=False)
    clock = pd.DataFrame(dict(signal_date=dates, included=included))
    clock_path = old / "diagnostics" / "COMMON_DATE_MATURITY.parquet"
    clock.to_parquet(clock_path, index=False)
    d = design()
    ids = d["evaluation"]["legacy"]["candidate_ids"]
    edges = pd.DataFrame(rng.normal(0, .02, (732, 91)), columns=ids)
    edges[ids[79:]] = 0.  # Existing failed placeholders are intentionally ignored.
    edges.insert(0, "signal_date", dates[included])
    edge_path = old / "diagnostics" / "PRIMARY_DAILY_EDGE.parquet"
    edges.to_parquet(edge_path, index=False)
    old_design_path = old / "DESIGN_FREEZE.json"
    old_assembly_path = old / "SCORE_ASSEMBLY.json"
    _putj(old_design_path, dict(candidates=ids))
    _putj(old_assembly_path, dict(
        complete_candidates=ids[:79],
        failed_or_untestable=d["evaluation"]["legacy"]["failed_or_untestable"]))
    d["evaluation"]["legacy"].update(
        design=_pin(old_design_path), assembly=_pin(old_assembly_path),
        edge=_pin(edge_path), clock=_pin(clock_path))
    training = results / "training.parquet"
    pd.DataFrame(dict(signal_date=dates, target_end_date=dates)).to_parquet(training, index=False)
    d["inputs"] = {"training": _pin(training)}
    sources = [Path(sut.__file__), Path(sut.evidence.__file__),
               sut.REPO / "scripts/research/a2/evaluation/selector_account_compare.py"]
    d["sources"] = {str(s): sut.sha(s) for s in sources}
    _putj(run / "DESIGN_FREEZE.json", d)
    digest = sut.sha(run / "DESIGN_FREEZE.json")
    _putj(run / "DESIGN_FREEZE_SHA.json", dict(sha256=digest))
    _putj(run / "run_config.json", dict(research_line="C_SELECTOR", research_id=d["research_id"],
                                       design_freeze_sha256=digest, results_directory=str(out)))
    _putj(run / "SCORE_ASSEMBLY.json", dict(
        complete_candidates=list(sut.ROLES), complete_fixed_references=list(sut.REFERENCES),
        failed_or_untestable={}, common_rows=len(raw), common_dates=len(dates),
        raw_candidate_id=sut.evidence.RAW, forecast2026_rows=0,
        mechanism_research_eligible=True, strict_PIT_promotion_eligible=False))
    _putj(run / "EVALUATION_CODE_ACTIVATION.json", dict(
        design_freeze_sha256=digest, score_assembly_sha256=sut.sha(run / "SCORE_ASSEMBLY.json"),
        sources=d["sources"]))
    return run, out, SimpleNamespace(backtest_root=backtest, results_root=results)


def test_production_adapter_runs_complete_synthetic_732_clock(tmp_path, monkeypatch):
    run, out, paths = pipeline_fixture(tmp_path)
    monkeypatch.setattr(sut, "resolve", lambda repo: paths)
    monkeypatch.setattr(sut, "assert_safe_output_path", lambda p, **k: None)
    receipt = sut.run(run)
    assert receipt["status"] == "MECHANISM_EVIDENCE_COMPLETE"
    assert receipt["common_mature_dates"] == 732 and receipt["common_year_dates"] == sut.YEAR_COUNTS
    assert receipt["bootstrap"]["numeric_complete_series"] == 87
    assert len(receipt["legacy_failed_or_untestable"]) == 12
    assert receipt["strict_PIT_promotion_eligible"] is False
    assert receipt["finalists"] == [] and not receipt["economic_promotion_allowed"]
    matrix = pd.read_parquet(run / "diagnostics/selector_evidence/PRIMARY_DAILY_EDGE.parquet")
    assert len(matrix.columns) == 88 and not any(f"old_{i:02d}" in matrix for i in range(79, 91))
    assert (out / "SELECTION_EVIDENCE.json").is_file()
    with pytest.raises(FileExistsError, match="PRESERVE"):
        sut.run(run)


def test_actual_reader_remains_blocked_before_formal_freeze(tmp_path, monkeypatch):
    run, _, paths = pipeline_fixture(tmp_path)
    d = sut.readj(run / "DESIGN_FREEZE.json")
    d["official_freeze"] = False
    _putj(run / "DESIGN_FREEZE.json", d)
    digest = sut.sha(run / "DESIGN_FREEZE.json")
    _putj(run / "DESIGN_FREEZE_SHA.json", dict(sha256=digest))
    cfg = sut.readj(run / "run_config.json")
    cfg["design_freeze_sha256"] = digest
    _putj(run / "run_config.json", cfg)
    monkeypatch.setattr(sut, "resolve", lambda repo: paths)
    monkeypatch.setattr(sut, "assert_safe_output_path", lambda p, **k: None)
    monkeypatch.setattr(sut, "score_panel", lambda *a, **k: pytest.fail("actual outcome read forbidden"))
    with pytest.raises(ValueError, match="FORMAL_FREEZE"):
        sut.run(run)

