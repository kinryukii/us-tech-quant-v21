#!/usr/bin/env python
"""Tests for V21.024 market regime context logic repair."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_024_market_regime_context_logic_repair.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_024_market_regime_context_logic_repair.ps1"
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_024_MARKET_REGIME_CONTEXT_LOGIC_REPAIR_REPORT.md"

REQUIRED_OUTPUTS = [
    OUT_DIR / "V21_024_V21_022_DECISION_INGEST_AUDIT.csv",
    OUT_DIR / "V21_024_REGIME_CONTEXT_SOURCE_CONTRACT_AUDIT.csv",
    OUT_DIR / "V21_024_REGIME_LABEL_ADEQUACY_CONFLICT_AUDIT.csv",
    OUT_DIR / "V21_024_TRUE_CONTEXT_ONLY_LOGIC_REPAIR_AUDIT.csv",
    OUT_DIR / "V21_024_REGIME_SPECIFIC_SCORING_CONTEXT_TEST.csv",
    OUT_DIR / "V21_024_REGIME_SPECIFIC_RISK_GATE_INTERACTION_TEST.csv",
    OUT_DIR / "V21_024_REGIME_CONTEXT_STATISTICAL_CONFIRMATION.csv",
    OUT_DIR / "V21_024_REGIME_TRANSITION_CONFLICT_EXCLUSION_TEST.csv",
    OUT_DIR / "V21_024_CONTEXT_LOGIC_REPAIR_DECISION.csv",
    OUT_DIR / "V21_024_MARKET_REGIME_CONTEXT_LOGIC_REPAIR_SUMMARY.csv",
    REPORT,
]

INPUTS = [
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
    ROOT / "outputs" / "v21" / "read_center" / "V21_022_RISK_REGIME_MODIFIER_ROBUSTNESS_CONFIRMATION_REPORT.md",
    OUT_DIR / "V21_005_OBSERVATION_SELECTION_AUDIT.csv",
]

ALLOWED_DECISIONS = {
    "MARKET_REGIME_CONTEXT_LOGIC_REPAIRED_RESEARCH_ONLY",
    "MARKET_REGIME_CONTEXT_LOGIC_PARTIAL_LABELS_LIMITED",
    "MARKET_REGIME_CONTEXT_LOGIC_REQUIRES_SOURCE_CONTRACT_REPAIR",
    "MARKET_REGIME_CONTEXT_LOGIC_NOT_SUPPORTED",
    "MARKET_REGIME_CONTEXT_LOGIC_INCONCLUSIVE_REQUIRED_FIELDS_MISSING",
}

ALLOWED_NEXT = {
    "V21.025_WITHIN_REGIME_ALPHA_ONLY_AND_RISK_GATE_SHADOW_RESEARCH_PLAN",
    "V21.026_MARKET_REGIME_SOURCE_CONTRACT_REPAIR",
    "V21.015_NONLINEAR_FACTOR_INTERACTION_RESEARCH_PROTOTYPE",
    "V21.019_MORE_MATURED_OBSERVATION_ACCUMULATION_PLAN",
    "V21.017_OVERHEAT_ENTRY_TIMING_AND_FALSE_BLOCK_REPAIR",
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


def test_v21_024_contract() -> None:
    result = run_stage()
    assert "STAGE_NAME=V21_024_MARKET_REGIME_CONTEXT_LOGIC_REPAIR" in result.stdout
    for path in REQUIRED_OUTPUTS:
        assert path.exists(), f"missing output {path}"
        assert path.stat().st_size > 0, f"empty output {path}"

    summary = read_csv(OUT_DIR / "V21_024_MARKET_REGIME_CONTEXT_LOGIC_REPAIR_SUMMARY.csv")[0]
    assert summary["research_only"] == "TRUE"
    assert summary["v21_022_confirmation_decision"] == "RISK_HARD_GATE_REGIME_FRAGILE"
    assert summary["v21_022_recommended_next_stage"] == "V21.024_MARKET_REGIME_CONTEXT_LOGIC_REPAIR"
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
    assert summary["context_logic_repair_decision"] in ALLOWED_DECISIONS
    assert summary["recommended_next_stage"] in ALLOWED_NEXT
    assert summary["prototype_output_scope"] == "V21_024_RESEARCH_ONLY"
    assert summary["single_global_market_regime_adjusted_score_used"] == "FALSE"

    forbidden = ["PRODUCTION", "REAL_BOOK", "OFFICIAL_ACTIVATION", "OFFICIAL_RANKING_READINESS", "OFFICIAL_WEIGHT_UPDATE_READINESS"]
    for term in forbidden:
        assert term not in summary["final_status"]
        assert term not in summary["context_logic_repair_decision"]

    ingest = read_csv(OUT_DIR / "V21_024_V21_022_DECISION_INGEST_AUDIT.csv")
    assert any(row["audit_item"] == "v21_022_decision_ingested" and row["audit_passed"] == "TRUE" for row in ingest)
    assert any(row["audit_item"] == "recommended_next_stage_v21_024" and row["audit_passed"] == "TRUE" for row in ingest)

    repair = read_csv(OUT_DIR / "V21_024_TRUE_CONTEXT_ONLY_LOGIC_REPAIR_AUDIT.csv")
    by_item = {row["repair_item"]: row for row in repair}
    for item in [
        "no_single_global_market_regime_adjusted_score",
        "global_alpha_only_rank_distinguished",
        "within_regime_alpha_only_rank_distinguished",
        "within_regime_risk_gated_rank_distinguished",
        "regime_context_label_distinguished",
    ]:
        assert by_item[item]["repair_status"] == "PASS"
    assert all(row["uses_single_global_market_regime_adjusted_score"] == "FALSE" for row in repair)
    assert all(row["official_score_overwritten"] == "FALSE" for row in repair)
    assert all(row["official_rank_overwritten"] == "FALSE" for row in repair)

    scoring = read_csv(OUT_DIR / "V21_024_REGIME_SPECIFIC_SCORING_CONTEXT_TEST.csv")
    variants = {row["context_rank_variant"] for row in scoring}
    assert "GLOBAL_ALPHA_ONLY_RANK" in variants
    assert "WITHIN_REGIME_ALPHA_ONLY_RANK" in variants
    assert "WITHIN_REGIME_RISK_GATED_RANK" in variants
    assert all(row["global_market_regime_adjusted_score_used"] == "FALSE" for row in scoring)

    decision = read_csv(OUT_DIR / "V21_024_CONTEXT_LOGIC_REPAIR_DECISION.csv")
    selected = [row for row in decision if row["selected_recommended_next_stage"] == "TRUE"]
    assert len(decision) == 1
    assert len(selected) == 1
    assert selected[0]["context_logic_repair_decision"] in ALLOWED_DECISIONS
    assert selected[0]["recommended_next_stage"] in ALLOWED_NEXT
    assert selected[0]["official_use_allowed"] == "FALSE"

    for output in REQUIRED_OUTPUTS:
        if output.suffix == ".csv":
            assert output.name.startswith("V21_024_")
    report_text = REPORT.read_text(encoding="utf-8").lower()
    for expected in [
        "research-only",
        "final context logic repair decision",
        "v21.022 decision ingestion",
        "true context-only logic repair",
        "no single global market-regime-adjusted score is used",
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
        "STAGE_NAME=V21_024_MARKET_REGIME_CONTEXT_LOGIC_REPAIR",
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
    test_v21_024_contract()
    test_wrapper_parseable()
    print("V21.024 market regime context logic repair tests passed")
