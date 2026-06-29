#!/usr/bin/env python
"""Tests for V21.007 factor architecture repair plan or weight update blocker."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_007_factor_architecture_repair_plan_or_weight_update_blocker.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_007_factor_architecture_repair_plan_or_weight_update_blocker.ps1"
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_007_FACTOR_ARCHITECTURE_REPAIR_PLAN_OR_WEIGHT_UPDATE_BLOCKER_REPORT.md"

REQUIRED_OUTPUTS = [
    OUT_DIR / "V21_007_V21_006_VERDICT_INGEST_AUDIT.csv",
    OUT_DIR / "V21_007_OUTLIER_DEPENDENCY_DIAGNOSIS.csv",
    OUT_DIR / "V21_007_REGIME_DEPENDENCY_DIAGNOSIS.csv",
    OUT_DIR / "V21_007_FACTOR_FAMILY_REPAIR_DIAGNOSIS.csv",
    OUT_DIR / "V21_007_RANK_ARCHITECTURE_DIAGNOSIS.csv",
    OUT_DIR / "V21_007_RISK_OVERHEAT_REPAIR_DIAGNOSIS.csv",
    OUT_DIR / "V21_007_WEIGHT_UPDATE_BLOCKER_DECISION.csv",
    OUT_DIR / "V21_007_REPAIR_ROADMAP.csv",
    OUT_DIR / "V21_007_FACTOR_ARCHITECTURE_REPAIR_PLAN_SUMMARY.csv",
    REPORT,
]

INPUTS = [
    OUT_DIR / "V21_006_PRIMARY_DATASET_VALIDATION.csv",
    OUT_DIR / "V21_006_RANK_BUCKET_SIGNIFICANCE_STATS.csv",
    OUT_DIR / "V21_006_RANK_MONOTONICITY_TEST.csv",
    OUT_DIR / "V21_006_FACTOR_FAMILY_IC_SIGNIFICANCE_STATS.csv",
    OUT_DIR / "V21_006_RANDOM_BASELINE_COMPARISON.csv",
    OUT_DIR / "V21_006_SUBSAMPLE_ROBUSTNESS_STATS.csv",
    OUT_DIR / "V21_006_OUTLIER_CONCENTRATION_AUDIT.csv",
    OUT_DIR / "V21_006_RISK_OVERHEAT_ROBUSTNESS_TEST.csv",
    OUT_DIR / "V21_006_BENCHMARK_SIGNIFICANCE_STATS.csv",
    OUT_DIR / "V21_006_DECISION_GRADE_ROBUSTNESS_SCORECARD.csv",
    OUT_DIR / "V21_006_BACKTEST_STATISTICAL_TEST_SUMMARY.csv",
    ROOT / "outputs" / "v21" / "read_center" / "V21_006_FACTOR_BACKTEST_STATISTICAL_SIGNIFICANCE_AND_ROBUSTNESS_TEST_REPORT.md",
    OUT_DIR / "V21_005_FACTOR_ABLATION_FORWARD_RETURN_STATS.csv",
    OUT_DIR / "V21_005_RISK_OVERHEAT_EFFECTIVENESS_STATS.csv",
    OUT_DIR / "V21_005_REGIME_CONDITIONED_PERFORMANCE_STATS.csv",
    OUT_DIR / "V21_005_BENCHMARK_COMPARISON_STATS.csv",
    OUT_DIR / "V21_005_BACKTEST_ENGINE_SUMMARY.csv",
]

ALLOWED_NEXT_STAGES = {
    "V21.008_REGIME_SEGMENTED_FACTOR_BACKTEST",
    "V21.009_OUTLIER_NEUTRALIZED_FACTOR_BACKTEST",
    "V21.010_RISK_OVERHEAT_FALSE_BLOCK_REPAIR",
    "V21.011_FACTOR_FAMILY_RESCALING_AND_NONLINEAR_INTERACTION_TEST",
    "V21.012_SECTOR_NEUTRAL_AND_THEME_CONCENTRATION_AUDIT",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def snapshot(paths: list[Path]) -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in paths if path.exists()}


def run_stage() -> subprocess.CompletedProcess[str]:
    before = snapshot(INPUTS)
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = snapshot(INPUTS)
    changed = [path for path, mtime in before.items() if after.get(path) != mtime]
    assert not changed, f"input files modified: {changed}"
    return result


def test_v21_007_contract() -> None:
    result = run_stage()
    assert "STAGE_NAME=V21_007_FACTOR_ARCHITECTURE_REPAIR_PLAN_OR_WEIGHT_UPDATE_BLOCKER" in result.stdout

    for path in REQUIRED_OUTPUTS:
        assert path.exists(), f"missing output {path}"
        assert path.stat().st_size > 0, f"empty output {path}"

    summary = read_csv(OUT_DIR / "V21_007_FACTOR_ARCHITECTURE_REPAIR_PLAN_SUMMARY.csv")[0]
    assert summary["research_only"] == "TRUE"
    assert summary["v21_006_final_status"], "V21.006 final status not ingested"
    assert "OUTLIER_OR_REGIME_DEPENDENT" in summary["v21_006_final_status"] or "OUTLIER_OR_REGIME_DEPENDENT" in summary["v21_006_final_verdict"]
    assert summary["data_trust_ranking_weight"] == "0"
    assert summary["data_trust_alpha_contribution"] == "0"
    assert summary["official_ranking_mutation_count"] == "0"
    assert summary["official_factor_weight_mutation_count"] == "0"
    assert summary["official_recommendation_count"] == "0"
    assert summary["trade_action_count"] == "0"
    assert summary["shadow_activation"] == "FALSE"
    assert "PRODUCTION" not in summary["final_status"]
    assert "REAL_BOOK" not in summary["final_status"]
    assert summary["recommended_next_stage"] in ALLOWED_NEXT_STAGES

    audit_rows = read_csv(OUT_DIR / "V21_007_V21_006_VERDICT_INGEST_AUDIT.csv")
    assert any(row["audit_item"] == "v21_006_final_status_ingested" and row["audit_passed"] == "TRUE" for row in audit_rows)
    assert any(row["audit_item"] == "data_trust_alpha_contribution_zero" and row["audit_passed"] == "TRUE" for row in audit_rows)

    blocker = read_csv(OUT_DIR / "V21_007_WEIGHT_UPDATE_BLOCKER_DECISION.csv")[0]
    assert blocker["weight_update_blocker_decision"], "missing blocker decision"
    assert blocker["official_weight_update_allowed"] == "FALSE"
    assert blocker["recommended_next_stage"] in ALLOWED_NEXT_STAGES

    roadmap = read_csv(OUT_DIR / "V21_007_REPAIR_ROADMAP.csv")
    selected = [row for row in roadmap if row["selected_recommended_next_stage"] == "TRUE"]
    assert len(selected) == 1, "exactly one recommended next stage must be selected"
    assert selected[0]["candidate_next_stage"] == summary["recommended_next_stage"]

    family_rows = read_csv(OUT_DIR / "V21_007_FACTOR_FAMILY_REPAIR_DIAGNOSIS.csv")
    data_trust = [row for row in family_rows if row["factor_family"] == "DATA_TRUST"]
    assert data_trust and data_trust[0]["repair_diagnosis"] == "USE_AS_GATE_NOT_ALPHA"
    assert data_trust[0]["data_trust_alpha_contribution"] == "0"

    report_text = REPORT.read_text(encoding="utf-8").lower()
    for expected in [
        "research-only",
        "final blocker decision",
        "why v21.006 is not enough for weight update",
        "data_trust zero-alpha confirmation",
        "explicit blocked actions",
        "no production readiness",
        "recommended next stage",
    ]:
        assert expected in report_text

    script_text = SCRIPT.read_text(encoding="utf-8").lower()
    for blocked_term in ["yfinance", "requests.", "urllib.request", "http.client", "socket.", "download("]:
        assert blocked_term not in script_text, f"network access term found: {blocked_term}"


def test_wrapper_parseable() -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    for expected in [
        "STAGE_NAME=V21_007_FACTOR_ARCHITECTURE_REPAIR_PLAN_OR_WEIGHT_UPDATE_BLOCKER",
        "final_status=",
        "weight_update_blocker_decision=",
        "recommended_next_stage=",
        "data_trust_ranking_weight=0",
        "data_trust_alpha_contribution=0",
        "official_ranking_mutation_count=0",
        "official_factor_weight_mutation_count=0",
        "official_recommendation_count=0",
        "trade_action_count=0",
        "shadow_activation=FALSE",
        "research_only=TRUE",
    ]:
        assert expected in result.stdout


if __name__ == "__main__":
    test_v21_007_contract()
    test_wrapper_parseable()
    print("V21.007 factor architecture repair plan or weight update blocker tests passed")
