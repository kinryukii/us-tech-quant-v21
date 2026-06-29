#!/usr/bin/env python
"""Tests for V21.016 risk/regime gate and modifier research prototype."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_016_risk_regime_gate_and_modifier_research_prototype.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_016_risk_regime_gate_and_modifier_research_prototype.ps1"
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_016_RISK_REGIME_GATE_AND_MODIFIER_RESEARCH_PROTOTYPE_REPORT.md"
REQUIRED = [
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
    REPORT,
]
INPUTS = [
    OUT_DIR / "V21_020_RESCALING_CANDIDATE_ROBUSTNESS_CONFIRMATION_SUMMARY.csv",
    OUT_DIR / "V21_020_RESCALING_CANDIDATE_CONFIRMATION_DECISION.csv",
    OUT_DIR / "V21_005_OBSERVATION_SELECTION_AUDIT.csv",
]
ALLOWED = {
    "V21.022_RISK_REGIME_MODIFIER_ROBUSTNESS_CONFIRMATION",
    "V21.017_OVERHEAT_ENTRY_TIMING_AND_FALSE_BLOCK_REPAIR",
    "V21.018_FACTOR_SCORE_DATA_CONTRACT_REPAIR",
    "V21.019_MORE_MATURED_OBSERVATION_ACCUMULATION_PLAN",
    "V21.021_ALPHA_ONLY_SHADOW_SCORING_DRY_RUN_PLAN",
    "V21.015_NONLINEAR_FACTOR_INTERACTION_RESEARCH_PROTOTYPE",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as h:
        return list(csv.DictReader(h))


def snapshot(paths: list[Path]) -> dict[Path, int]:
    return {p: p.stat().st_mtime_ns for p in paths if p.exists()}


def test_v21_016_contract() -> None:
    before = snapshot(INPUTS)
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = snapshot(INPUTS)
    assert not [p for p, m in before.items() if after.get(p) != m]
    assert "STAGE_NAME=V21_016_RISK_REGIME_GATE_AND_MODIFIER_RESEARCH_PROTOTYPE" in result.stdout
    for path in REQUIRED:
        assert path.exists(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"
    summary = read_csv(OUT_DIR / "V21_016_RISK_REGIME_GATE_AND_MODIFIER_RESEARCH_PROTOTYPE_SUMMARY.csv")[0]
    assert summary["research_only"] == "TRUE"
    assert summary["v21_020_confirmation_decision"] == "RESCALING_CANDIDATE_REGIME_FRAGILE"
    assert summary["v21_020_selected_variant"] == "ALPHA_ONLY_RESCALING"
    assert summary["official_use_allowed"] == "FALSE"
    assert summary["official_ranking_readiness_allowed"] == "FALSE"
    assert summary["official_weight_update_readiness_allowed"] == "FALSE"
    assert summary["official_weight_update_blocked"] == "TRUE"
    assert summary["data_trust_ranking_weight"] == "0"
    assert summary["data_trust_alpha_contribution"] == "0"
    assert summary["official_ranking_mutation_count"] == "0"
    assert summary["official_factor_weight_mutation_count"] == "0"
    assert summary["official_recommendation_count"] == "0"
    assert summary["trade_action_count"] == "0"
    assert summary["shadow_activation"] == "FALSE"
    assert summary["recommended_next_stage"] in ALLOWED
    assert summary["prototype_output_scope"] == "V21_016_RESEARCH_ONLY"
    for term in ["PRODUCTION", "REAL_BOOK", "OFFICIAL_ACTIVATION", "OFFICIAL_RANKING_READINESS", "OFFICIAL_WEIGHT_UPDATE_READINESS"]:
        assert term not in summary["final_status"]
        assert term not in summary["risk_regime_decision"]
    ingest = read_csv(OUT_DIR / "V21_016_V21_020_DECISION_INGEST_AUDIT.csv")
    assert any(r["audit_item"] == "v21_020_decision_ingested" and r["audit_passed"] == "TRUE" for r in ingest)
    assert any(r["audit_item"] == "selected_variant_alpha_only" and r["audit_passed"] == "TRUE" for r in ingest)
    assert read_csv(OUT_DIR / "V21_016_EQUIVALENCE_COLLAPSE_ROOT_CAUSE_AUDIT.csv")
    scores = read_csv(OUT_DIR / "V21_016_RISK_REGIME_PROTOTYPE_VARIANT_SCORE_OUTPUT.csv")
    assert scores and all(r["research_only"] == "TRUE" for r in scores[:100])
    assert all(r["official_score_overwritten"] == "FALSE" for r in scores[:100])
    decision = read_csv(OUT_DIR / "V21_016_RISK_REGIME_GATE_AND_MODIFIER_DECISION.csv")
    assert len(decision) == 1
    assert decision[0]["selected_recommended_next_stage"] == "TRUE"
    report = REPORT.read_text(encoding="utf-8").lower()
    for expected in ["research-only", "final risk/regime prototype decision", "equivalence-collapse root cause audit", "data_trust zero-alpha confirmation", "explicit blocked actions", "recommended next stage"]:
        assert expected in report


def test_wrapper_parseable() -> None:
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)], cwd=ROOT, text=True, capture_output=True, check=True)
    for expected in [
        "STAGE_NAME=V21_016_RISK_REGIME_GATE_AND_MODIFIER_RESEARCH_PROTOTYPE",
        "official_use_allowed=FALSE",
        "official_ranking_readiness_allowed=FALSE",
        "official_weight_update_readiness_allowed=FALSE",
        "official_weight_update_blocked=TRUE",
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
    test_v21_016_contract()
    test_wrapper_parseable()
    print("V21.016 risk/regime gate and modifier research prototype tests passed")
