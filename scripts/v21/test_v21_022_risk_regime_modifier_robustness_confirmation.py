#!/usr/bin/env python
"""Tests for V21.022 risk/regime modifier robustness confirmation."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_022_risk_regime_modifier_robustness_confirmation.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_022_risk_regime_modifier_robustness_confirmation.ps1"
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_022_RISK_REGIME_MODIFIER_ROBUSTNESS_CONFIRMATION_REPORT.md"

REQUIRED_OUTPUTS = [
    OUT_DIR / "V21_022_V21_016_CANDIDATE_INGEST_AUDIT.csv",
    OUT_DIR / "V21_022_RISK_HARD_GATE_RECONSTRUCTION_AUDIT.csv",
    OUT_DIR / "V21_022_CANDIDATE_VS_ALPHA_ONLY_COMPARISON.csv",
    OUT_DIR / "V21_022_STATISTICAL_CONFIRMATION.csv",
    OUT_DIR / "V21_022_REGIME_ROBUSTNESS_CONFIRMATION.csv",
    OUT_DIR / "V21_022_FALSE_BLOCK_AND_MISSED_WINNER_AUDIT.csv",
    OUT_DIR / "V21_022_OUTLIER_DEPENDENCY_RETEST.csv",
    OUT_DIR / "V21_022_MARKET_REGIME_DISTINCT_CONTEXT_LOGIC_AUDIT.csv",
    OUT_DIR / "V21_022_RESEARCH_DRY_RUN_READINESS_ASSESSMENT.csv",
    OUT_DIR / "V21_022_RISK_REGIME_MODIFIER_CONFIRMATION_DECISION.csv",
    OUT_DIR / "V21_022_RISK_REGIME_MODIFIER_ROBUSTNESS_CONFIRMATION_SUMMARY.csv",
    REPORT,
]

INPUTS = [
    OUT_DIR / "V21_016_V21_020_DECISION_INGEST_AUDIT.csv",
    OUT_DIR / "V21_016_RISK_REGIME_FIELD_AVAILABILITY_AUDIT.csv",
    OUT_DIR / "V21_016_EQUIVALENCE_COLLAPSE_ROOT_CAUSE_AUDIT.csv",
    OUT_DIR / "V21_016_RISK_REGIME_PROTOTYPE_VARIANT_SCORE_OUTPUT.csv",
    OUT_DIR / "V21_016_VARIANT_PERFORMANCE_EVALUATION.csv",
    OUT_DIR / "V21_016_REGIME_SPECIFIC_VARIANT_EVALUATION.csv",
    OUT_DIR / "V21_016_RISK_OVERHEAT_FALSE_BLOCK_PROTECTION_TEST.csv",
    OUT_DIR / "V21_016_STATISTICAL_RANDOM_BASELINE_CONFIRMATION.csv",
    OUT_DIR / "V21_016_OUTLIER_AND_REGIME_FRAGILITY_AUDIT.csv",
    OUT_DIR / "V21_016_RISK_REGIME_VARIANT_SELECTION.csv",
    OUT_DIR / "V21_016_RISK_REGIME_GATE_AND_MODIFIER_DECISION.csv",
    OUT_DIR / "V21_016_RISK_REGIME_GATE_AND_MODIFIER_RESEARCH_PROTOTYPE_SUMMARY.csv",
    ROOT / "outputs" / "v21" / "read_center" / "V21_016_RISK_REGIME_GATE_AND_MODIFIER_RESEARCH_PROTOTYPE_REPORT.md",
    OUT_DIR / "V21_005_OBSERVATION_SELECTION_AUDIT.csv",
]

ALLOWED_DECISIONS = {
    "RISK_HARD_GATE_CONFIRMED_RESEARCH_ONLY",
    "RISK_HARD_GATE_WEAK_BUT_PROMISING_RESEARCH_ONLY",
    "RISK_HARD_GATE_REGIME_FRAGILE",
    "RISK_HARD_GATE_OUTLIER_DEPENDENT",
    "RISK_HARD_GATE_OVERLY_RESTRICTIVE",
    "RISK_HARD_GATE_NOT_CONFIRMED",
    "RISK_REGIME_CONFIRMATION_INCONCLUSIVE_REQUIRED_FIELDS_MISSING",
}

ALLOWED_NEXT = {
    "V21.023_RISK_HARD_GATE_SHADOW_RESEARCH_PLAN",
    "V21.017_OVERHEAT_ENTRY_TIMING_AND_FALSE_BLOCK_REPAIR",
    "V21.018_FACTOR_SCORE_DATA_CONTRACT_REPAIR",
    "V21.019_MORE_MATURED_OBSERVATION_ACCUMULATION_PLAN",
    "V21.015_NONLINEAR_FACTOR_INTERACTION_RESEARCH_PROTOTYPE",
    "V21.024_MARKET_REGIME_CONTEXT_LOGIC_REPAIR",
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


def test_v21_022_contract() -> None:
    result = run_stage()
    assert "STAGE_NAME=V21_022_RISK_REGIME_MODIFIER_ROBUSTNESS_CONFIRMATION" in result.stdout
    for path in REQUIRED_OUTPUTS:
        assert path.exists(), f"missing output {path}"
        assert path.stat().st_size > 0, f"empty output {path}"

    summary = read_csv(OUT_DIR / "V21_022_RISK_REGIME_MODIFIER_ROBUSTNESS_CONFIRMATION_SUMMARY.csv")[0]
    assert summary["research_only"] == "TRUE"
    assert summary["v21_016_risk_regime_decision"] == "RISK_REGIME_MODIFIER_CANDIDATE_FOUND_RESEARCH_ONLY"
    assert summary["selected_variant"] == "RISK_HARD_GATE_DIAGNOSTIC"
    assert summary["official_use_allowed"] == "FALSE"
    assert summary["official_ranking_readiness_allowed"] == "FALSE"
    assert summary["official_weight_update_readiness_allowed"] == "FALSE"
    assert summary["official_weight_update_blocked"] == "TRUE"
    assert summary["data_trust_ranking_weight"] == "0"
    assert summary["data_trust_alpha_contribution"] == "0"
    assert summary["risk_additive_alpha_contribution"] == "0"
    assert summary["market_regime_additive_alpha_contribution"] == "0"
    assert summary["official_ranking_mutation_count"] == "0"
    assert summary["official_factor_weight_mutation_count"] == "0"
    assert summary["official_recommendation_count"] == "0"
    assert summary["trade_action_count"] == "0"
    assert summary["shadow_activation"] == "FALSE"
    assert summary["confirmation_decision"] in ALLOWED_DECISIONS
    assert summary["recommended_next_stage"] in ALLOWED_NEXT
    assert summary["prototype_output_scope"] == "V21_022_RESEARCH_ONLY"

    forbidden = ["PRODUCTION", "REAL_BOOK", "OFFICIAL_ACTIVATION", "OFFICIAL_RANKING_READINESS", "OFFICIAL_WEIGHT_UPDATE_READINESS"]
    for term in forbidden:
        assert term not in summary["final_status"]
        assert term not in summary["confirmation_decision"]

    ingest = read_csv(OUT_DIR / "V21_022_V21_016_CANDIDATE_INGEST_AUDIT.csv")
    assert any(row["audit_item"] == "v21_016_decision_ingested" and row["audit_passed"] == "TRUE" for row in ingest)
    assert any(row["audit_item"] == "selected_variant_risk_hard_gate" and row["audit_passed"] == "TRUE" for row in ingest)

    recon = read_csv(OUT_DIR / "V21_022_RISK_HARD_GATE_RECONSTRUCTION_AUDIT.csv")[0]
    assert recon["data_trust_alpha_contribution"] == "0"
    assert recon["risk_additive_alpha_contribution"] == "0"
    assert recon["market_regime_additive_alpha_contribution"] == "0"
    assert recon["official_score_overwritten"] == "FALSE"
    assert recon["official_rank_overwritten"] == "FALSE"

    assert read_csv(OUT_DIR / "V21_022_FALSE_BLOCK_AND_MISSED_WINNER_AUDIT.csv")
    assert read_csv(OUT_DIR / "V21_022_MARKET_REGIME_DISTINCT_CONTEXT_LOGIC_AUDIT.csv")

    decision = read_csv(OUT_DIR / "V21_022_RISK_REGIME_MODIFIER_CONFIRMATION_DECISION.csv")
    selected = [row for row in decision if row["selected_recommended_next_stage"] == "TRUE"]
    assert len(decision) == 1
    assert len(selected) == 1
    assert selected[0]["confirmation_decision"] in ALLOWED_DECISIONS
    assert selected[0]["recommended_next_stage"] in ALLOWED_NEXT
    assert selected[0]["official_use_allowed"] == "FALSE"

    for output in REQUIRED_OUTPUTS:
        if output.suffix == ".csv":
            assert output.name.startswith("V21_022_")
    report_text = REPORT.read_text(encoding="utf-8").lower()
    for expected in [
        "research-only",
        "final confirmation decision",
        "v21.016 candidate ingestion",
        "risk hard gate reconstruction audit",
        "data_trust zero-alpha confirmation",
        "explicit blocked actions",
        "no production readiness",
        "no real-book readiness",
        "recommended next stage",
    ]:
        assert expected in report_text
    forbidden_report_claims = ["production readiness confirmed", "real-book readiness confirmed", "official activation", "official ranking readiness confirmed", "official weight update readiness confirmed"]
    for claim in forbidden_report_claims:
        assert claim not in report_text


def test_wrapper_parseable() -> None:
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)], cwd=ROOT, text=True, capture_output=True, check=True)
    for expected in [
        "STAGE_NAME=V21_022_RISK_REGIME_MODIFIER_ROBUSTNESS_CONFIRMATION",
        "selected_variant=RISK_HARD_GATE_DIAGNOSTIC",
        "v21_016_risk_regime_decision=RISK_REGIME_MODIFIER_CANDIDATE_FOUND_RESEARCH_ONLY",
        "official_use_allowed=FALSE",
        "official_ranking_readiness_allowed=FALSE",
        "official_weight_update_readiness_allowed=FALSE",
        "official_weight_update_blocked=TRUE",
        "data_trust_ranking_weight=0",
        "data_trust_alpha_contribution=0",
        "risk_additive_alpha_contribution=0",
        "market_regime_additive_alpha_contribution=0",
        "official_ranking_mutation_count=0",
        "official_factor_weight_mutation_count=0",
        "official_recommendation_count=0",
        "trade_action_count=0",
        "shadow_activation=FALSE",
        "research_only=TRUE",
    ]:
        assert expected in result.stdout


if __name__ == "__main__":
    test_v21_022_contract()
    test_wrapper_parseable()
    print("V21.022 risk/regime modifier robustness confirmation tests passed")
