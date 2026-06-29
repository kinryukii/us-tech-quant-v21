#!/usr/bin/env python
"""Tests for V21.011 factor family rescaling and nonlinear interaction test."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_011_factor_family_rescaling_and_nonlinear_interaction_test.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_011_factor_family_rescaling_and_nonlinear_interaction_test.ps1"
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_011_FACTOR_FAMILY_RESCALING_AND_NONLINEAR_INTERACTION_TEST_REPORT.md"

REQUIRED_OUTPUTS = [
    OUT_DIR / "V21_011_V21_008_DECISION_INGEST_AUDIT.csv",
    OUT_DIR / "V21_011_FAMILY_SCORE_AVAILABILITY_AUDIT.csv",
    OUT_DIR / "V21_011_FAMILY_SCORE_SCALE_DISTRIBUTION_AUDIT.csv",
    OUT_DIR / "V21_011_FAMILY_REDUNDANCY_CORRELATION_AUDIT.csv",
    OUT_DIR / "V21_011_LINEAR_ARCHITECTURE_STRESS_TEST.csv",
    OUT_DIR / "V21_011_NONLINEAR_INTERACTION_TEST.csv",
    OUT_DIR / "V21_011_RISK_REGIME_PLACEMENT_DIAGNOSIS.csv",
    OUT_DIR / "V21_011_OVERHEAT_PLACEMENT_DIAGNOSIS.csv",
    OUT_DIR / "V21_011_ARCHITECTURE_REPAIR_CANDIDATES.csv",
    OUT_DIR / "V21_011_ARCHITECTURE_REPAIR_DECISION.csv",
    OUT_DIR / "V21_011_FACTOR_FAMILY_RESCALING_AND_NONLINEAR_INTERACTION_TEST_SUMMARY.csv",
    REPORT,
]

INPUTS = [
    OUT_DIR / "V21_008_V21_007_BLOCKER_INGEST_AUDIT.csv",
    OUT_DIR / "V21_008_REGIME_LABEL_INVENTORY.csv",
    OUT_DIR / "V21_008_REGIME_RANK_BUCKET_PERFORMANCE.csv",
    OUT_DIR / "V21_008_REGIME_FACTOR_FAMILY_IC_STATS.csv",
    OUT_DIR / "V21_008_REGIME_RANDOM_BASELINE_COMPARISON.csv",
    OUT_DIR / "V21_008_REGIME_BENCHMARK_COMPARISON.csv",
    OUT_DIR / "V21_008_REGIME_TRANSITION_CONFLICT_AUDIT.csv",
    OUT_DIR / "V21_008_REGIME_RISK_OVERHEAT_BEHAVIOR.csv",
    OUT_DIR / "V21_008_REGIME_SEGMENTATION_DECISION.csv",
    OUT_DIR / "V21_008_REGIME_SEGMENTED_BACKTEST_SUMMARY.csv",
    ROOT / "outputs" / "v21" / "read_center" / "V21_008_REGIME_SEGMENTED_FACTOR_BACKTEST_REPORT.md",
    OUT_DIR / "V21_005_FACTOR_ABLATION_FORWARD_RETURN_STATS.csv",
    OUT_DIR / "V21_005_FACTOR_FAMILY_IC_STATS.csv",
    OUT_DIR / "V21_005_RANK_BUCKET_FORWARD_RETURN_STATS.csv",
    OUT_DIR / "V21_005_RISK_OVERHEAT_EFFECTIVENESS_STATS.csv",
    OUT_DIR / "V21_006_FACTOR_FAMILY_IC_SIGNIFICANCE_STATS.csv",
    OUT_DIR / "V21_006_RANK_MONOTONICITY_TEST.csv",
    OUT_DIR / "V21_006_OUTLIER_CONCENTRATION_AUDIT.csv",
    OUT_DIR / "V21_006_RISK_OVERHEAT_ROBUSTNESS_TEST.csv",
    OUT_DIR / "V21_006_BACKTEST_STATISTICAL_TEST_SUMMARY.csv",
    OUT_DIR / "V21_007_FACTOR_FAMILY_REPAIR_DIAGNOSIS.csv",
    OUT_DIR / "V21_007_RANK_ARCHITECTURE_DIAGNOSIS.csv",
    OUT_DIR / "V21_007_RISK_OVERHEAT_REPAIR_DIAGNOSIS.csv",
    OUT_DIR / "V21_007_WEIGHT_UPDATE_BLOCKER_DECISION.csv",
    OUT_DIR / "V21_005_OBSERVATION_SELECTION_AUDIT.csv",
]

ALLOWED_NEXT_STAGES = {
    "V21.014_FAMILY_SCORE_RESCALING_RESEARCH_PROTOTYPE",
    "V21.015_NONLINEAR_FACTOR_INTERACTION_RESEARCH_PROTOTYPE",
    "V21.016_RISK_REGIME_GATE_AND_MODIFIER_RESEARCH_PROTOTYPE",
    "V21.017_OVERHEAT_ENTRY_TIMING_AND_FALSE_BLOCK_REPAIR",
    "V21.018_FACTOR_SCORE_DATA_CONTRACT_REPAIR",
    "V21.019_MORE_MATURED_OBSERVATION_ACCUMULATION_PLAN",
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


def test_v21_011_contract() -> None:
    result = run_stage()
    assert "STAGE_NAME=V21_011_FACTOR_FAMILY_RESCALING_AND_NONLINEAR_INTERACTION_TEST" in result.stdout

    for path in REQUIRED_OUTPUTS:
        assert path.exists(), f"missing output {path}"
        assert path.stat().st_size > 0, f"empty output {path}"

    summary = read_csv(OUT_DIR / "V21_011_FACTOR_FAMILY_RESCALING_AND_NONLINEAR_INTERACTION_TEST_SUMMARY.csv")[0]
    assert summary["research_only"] == "TRUE"
    assert summary["v21_008_regime_segmentation_decision"] == "REGIME_SEGMENTATION_REVEALS_ARCHITECTURE_REPAIR_REQUIRED"
    assert summary["official_use_allowed"] == "FALSE"
    assert summary["official_weight_update_blocked"] == "TRUE"
    assert summary["research_only_limited_weight_experiment_allowed"] == "FALSE"
    assert summary["data_trust_ranking_weight"] == "0"
    assert summary["data_trust_alpha_contribution"] == "0"
    assert summary["official_ranking_mutation_count"] == "0"
    assert summary["official_factor_weight_mutation_count"] == "0"
    assert summary["official_recommendation_count"] == "0"
    assert summary["trade_action_count"] == "0"
    assert summary["shadow_activation"] == "FALSE"
    assert summary["recommended_next_stage"] in ALLOWED_NEXT_STAGES
    assert int(summary["architecture_repair_candidate_count"]) >= 1

    forbidden = ["PRODUCTION", "REAL_BOOK", "OFFICIAL_ACTIVATION", "OFFICIAL_RANKING_READINESS", "OFFICIAL_WEIGHT_UPDATE_READINESS"]
    for term in forbidden:
        assert term not in summary["final_status"]
        assert term not in summary["architecture_repair_decision"]

    ingest = read_csv(OUT_DIR / "V21_011_V21_008_DECISION_INGEST_AUDIT.csv")
    assert any(row["audit_item"] == "v21_008_decision_ingested" and row["audit_passed"] == "TRUE" for row in ingest)

    decision = read_csv(OUT_DIR / "V21_011_ARCHITECTURE_REPAIR_DECISION.csv")
    selected = [row for row in decision if row["selected_recommended_next_stage"] == "TRUE"]
    assert len(decision) == 1
    assert len(selected) == 1
    assert selected[0]["official_use_allowed"] == "FALSE"
    assert selected[0]["official_weight_update_blocked"] == "TRUE"

    availability = read_csv(OUT_DIR / "V21_011_FAMILY_SCORE_AVAILABILITY_AUDIT.csv")
    data_trust = [row for row in availability if row["factor_family"] == "DATA_TRUST"]
    assert data_trust and data_trust[0]["availability_status"] == "AUDIT_ONLY_CONTROL"
    assert data_trust[0]["data_trust_alpha_contribution"] == "0"

    candidates = read_csv(OUT_DIR / "V21_011_ARCHITECTURE_REPAIR_CANDIDATES.csv")
    assert candidates
    assert all(row["official_use_allowed"] == "FALSE" for row in candidates)
    assert all(row["research_only"] == "TRUE" for row in candidates)

    report_text = REPORT.read_text(encoding="utf-8").lower()
    for expected in [
        "research-only",
        "final architecture repair decision",
        "v21.008 decision ingestion",
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
        "STAGE_NAME=V21_011_FACTOR_FAMILY_RESCALING_AND_NONLINEAR_INTERACTION_TEST",
        "final_status=",
        "architecture_repair_decision=",
        "official_use_allowed=FALSE",
        "official_weight_update_blocked=TRUE",
        "research_only_limited_weight_experiment_allowed=FALSE",
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
    test_v21_011_contract()
    test_wrapper_parseable()
    print("V21.011 factor family rescaling and nonlinear interaction tests passed")
