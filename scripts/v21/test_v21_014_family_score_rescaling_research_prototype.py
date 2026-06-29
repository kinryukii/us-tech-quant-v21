#!/usr/bin/env python
"""Tests for V21.014 family score rescaling research prototype."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_014_family_score_rescaling_research_prototype.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_014_family_score_rescaling_research_prototype.ps1"
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_014_FAMILY_SCORE_RESCALING_RESEARCH_PROTOTYPE_REPORT.md"

REQUIRED_OUTPUTS = [
    OUT_DIR / "V21_014_V21_011_DECISION_INGEST_AUDIT.csv",
    OUT_DIR / "V21_014_FAMILY_SCORE_SOURCE_CONTRACT_AUDIT.csv",
    OUT_DIR / "V21_014_BASELINE_RECONSTRUCTION_AUDIT.csv",
    OUT_DIR / "V21_014_RESCALING_VARIANT_SCORE_OUTPUT.csv",
    OUT_DIR / "V21_014_RESCALING_VARIANT_PERFORMANCE_STATS.csv",
    OUT_DIR / "V21_014_FAMILY_CONTRIBUTION_BALANCE_AUDIT.csv",
    OUT_DIR / "V21_014_VARIANT_ROBUSTNESS_AND_OVERFIT_GUARD.csv",
    OUT_DIR / "V21_014_RESCALING_CANDIDATE_RANKING.csv",
    OUT_DIR / "V21_014_RESCALING_PROTOTYPE_DECISION.csv",
    OUT_DIR / "V21_014_FAMILY_SCORE_RESCALING_RESEARCH_PROTOTYPE_SUMMARY.csv",
    REPORT,
]

INPUTS = [
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
    ROOT / "outputs" / "v21" / "read_center" / "V21_011_FACTOR_FAMILY_RESCALING_AND_NONLINEAR_INTERACTION_TEST_REPORT.md",
    OUT_DIR / "V21_005_OBSERVATION_SELECTION_AUDIT.csv",
]

ALLOWED_NEXT_STAGES = {
    "V21.020_RESCALING_CANDIDATE_ROBUSTNESS_CONFIRMATION",
    "V21.015_NONLINEAR_FACTOR_INTERACTION_RESEARCH_PROTOTYPE",
    "V21.016_RISK_REGIME_GATE_AND_MODIFIER_RESEARCH_PROTOTYPE",
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


def test_v21_014_contract() -> None:
    result = run_stage()
    assert "STAGE_NAME=V21_014_FAMILY_SCORE_RESCALING_RESEARCH_PROTOTYPE" in result.stdout
    for path in REQUIRED_OUTPUTS:
        assert path.exists(), f"missing output {path}"
        assert path.stat().st_size > 0, f"empty output {path}"

    summary = read_csv(OUT_DIR / "V21_014_FAMILY_SCORE_RESCALING_RESEARCH_PROTOTYPE_SUMMARY.csv")[0]
    assert summary["research_only"] == "TRUE"
    assert summary["v21_011_architecture_repair_decision"] == "ARCHITECTURE_REPAIR_REQUIRED_FAMILY_RESCALING"
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
    assert int(summary["evaluated_variant_count"]) >= 1
    assert summary["prototype_score_output_path"].endswith("V21_014_RESCALING_VARIANT_SCORE_OUTPUT.csv")

    forbidden = ["PRODUCTION", "REAL_BOOK", "OFFICIAL_ACTIVATION", "OFFICIAL_RANKING_READINESS", "OFFICIAL_WEIGHT_UPDATE_READINESS"]
    for term in forbidden:
        assert term not in summary["final_status"]
        assert term not in summary["rescaling_prototype_decision"]

    ingest = read_csv(OUT_DIR / "V21_014_V21_011_DECISION_INGEST_AUDIT.csv")
    assert any(row["audit_item"] == "v21_011_decision_ingested" and row["audit_passed"] == "TRUE" for row in ingest)

    scores = read_csv(OUT_DIR / "V21_014_RESCALING_VARIANT_SCORE_OUTPUT.csv")
    assert scores
    assert all(row["research_only"] == "TRUE" for row in scores[:100])
    assert all(row["official_score_overwritten"] == "FALSE" for row in scores[:100])
    assert all(row["official_rank_overwritten"] == "FALSE" for row in scores[:100])

    contract = read_csv(OUT_DIR / "V21_014_FAMILY_SCORE_SOURCE_CONTRACT_AUDIT.csv")
    data_trust = [row for row in contract if row["factor_family"] == "DATA_TRUST"]
    assert data_trust and data_trust[0]["contract_status"] == "AUDIT_ONLY_CONTROL"
    assert data_trust[0]["data_trust_alpha_contribution"] == "0"

    decision = read_csv(OUT_DIR / "V21_014_RESCALING_PROTOTYPE_DECISION.csv")
    selected = [row for row in decision if row["selected_recommended_next_stage"] == "TRUE"]
    assert len(decision) == 1
    assert len(selected) == 1
    assert selected[0]["official_use_allowed"] == "FALSE"
    assert selected[0]["official_weight_update_blocked"] == "TRUE"

    report_text = REPORT.read_text(encoding="utf-8").lower()
    for expected in [
        "research-only",
        "final rescaling prototype decision",
        "v21.011 decision ingestion",
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
        "STAGE_NAME=V21_014_FAMILY_SCORE_RESCALING_RESEARCH_PROTOTYPE",
        "final_status=",
        "rescaling_prototype_decision=",
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
    test_v21_014_contract()
    test_wrapper_parseable()
    print("V21.014 family score rescaling research prototype tests passed")
