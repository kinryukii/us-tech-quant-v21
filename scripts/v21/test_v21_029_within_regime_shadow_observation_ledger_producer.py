#!/usr/bin/env python
"""Tests for V21.029 within-regime shadow observation ledger producer."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_029_within_regime_shadow_observation_ledger_producer.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_029_within_regime_shadow_observation_ledger_producer.ps1"
OUT_DIR = ROOT / "outputs" / "v21" / "shadow_observation"
FB_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_029_WITHIN_REGIME_SHADOW_OBSERVATION_LEDGER_PRODUCER_REPORT.md"

REQUIRED_OUTPUTS = [
    OUT_DIR / "V21_029_V21_025_DECISION_INGEST_AUDIT.csv",
    OUT_DIR / "V21_029_CURRENT_OBSERVATION_UNIVERSE.csv",
    OUT_DIR / "V21_029_WITHIN_REGIME_ALPHA_ONLY_RANKS.csv",
    OUT_DIR / "V21_029_CONTEXT_SPECIFIC_RISK_GATE_OVERLAY.csv",
    OUT_DIR / "V21_029_SHADOW_OBSERVATION_SELECTIONS.csv",
    OUT_DIR / "V21_029_FORWARD_OBSERVATION_SCHEDULE.csv",
    OUT_DIR / "V21_029_OBSERVATION_LEDGER.csv",
    OUT_DIR / "V21_029_LEDGER_DEDUP_LINEAGE_AUDIT.csv",
    OUT_DIR / "V21_029_SOURCE_GAP_ANNOTATION.csv",
    OUT_DIR / "V21_029_MONITORING_BASELINE_SNAPSHOT.csv",
    OUT_DIR / "V21_029_GUARDRAIL_ENFORCEMENT_AUDIT.csv",
    OUT_DIR / "V21_029_SHADOW_OBSERVATION_LEDGER_PRODUCER_DECISION.csv",
    OUT_DIR / "V21_029_WITHIN_REGIME_SHADOW_OBSERVATION_LEDGER_PRODUCER_SUMMARY.csv",
    REPORT,
]

INPUTS = [
    FB_DIR / "V21_025_V21_027_DECISION_INGEST_AUDIT.csv",
    FB_DIR / "V21_025_RESEARCH_CONTEXT_CANDIDATE_SELECTION.csv",
    FB_DIR / "V21_025_SHADOW_RESEARCH_PLAN_DESIGN.csv",
    FB_DIR / "V21_025_PLAN_GUARDRAILS.csv",
    FB_DIR / "V21_025_SHADOW_OBSERVATION_LEDGER_SPEC.csv",
    FB_DIR / "V21_025_SELECTION_POLICY_PROTOTYPE.csv",
    FB_DIR / "V21_025_RISK_GATE_POLICY_PROTOTYPE.csv",
    FB_DIR / "V21_025_REQUIRED_MONITORING_METRICS.csv",
    FB_DIR / "V21_025_PROMOTION_BLOCKER_AND_EXIT_CRITERIA.csv",
    FB_DIR / "V21_025_DRY_RUN_ARTIFACT_PLAN.csv",
    FB_DIR / "V21_025_SHADOW_RESEARCH_PLAN_DECISION.csv",
    FB_DIR / "V21_025_WITHIN_REGIME_ALPHA_ONLY_AND_RISK_GATE_SHADOW_RESEARCH_PLAN_SUMMARY.csv",
    ROOT / "outputs" / "v21" / "read_center" / "V21_025_WITHIN_REGIME_ALPHA_ONLY_AND_RISK_GATE_SHADOW_RESEARCH_PLAN_REPORT.md",
]

ALLOWED_DECISIONS = {
    "SHADOW_OBSERVATION_LEDGER_PRODUCED_RESEARCH_ONLY",
    "SHADOW_OBSERVATION_LEDGER_PRODUCED_WITH_SOURCE_GAPS",
    "SHADOW_OBSERVATION_LEDGER_PARTIAL_CURRENT_SNAPSHOT_FALLBACK",
    "SHADOW_OBSERVATION_LEDGER_BLOCKED_REQUIRED_FIELDS_MISSING",
    "SHADOW_OBSERVATION_LEDGER_INCONCLUSIVE_NO_CURRENT_CANDIDATES",
}
ALLOWED_NEXT = {
    "V21.030_SHADOW_OBSERVATION_LEDGER_MATURITY_TRACKER",
    "V21.028_MARKET_REGIME_DATA_PRODUCER_IMPLEMENTATION",
    "V21.031_DAILY_WITHIN_REGIME_SHADOW_OBSERVATION_REPORT",
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


def test_v21_029_contract() -> None:
    result = run_stage()
    assert "STAGE_NAME=V21_029_WITHIN_REGIME_SHADOW_OBSERVATION_LEDGER_PRODUCER" in result.stdout
    for path in REQUIRED_OUTPUTS:
        assert path.exists(), f"missing output {path}"
        assert path.stat().st_size > 0, f"empty output {path}"

    summary = read_csv(OUT_DIR / "V21_029_WITHIN_REGIME_SHADOW_OBSERVATION_LEDGER_PRODUCER_SUMMARY.csv")[0]
    assert summary["research_only"] == "TRUE"
    assert summary["v21_025_shadow_research_plan_decision"] == "SHADOW_RESEARCH_PLAN_READY_NOT_ACTIVATED"
    assert summary["v21_025_recommended_next_stage"] == "V21.029_WITHIN_REGIME_SHADOW_OBSERVATION_LEDGER_PRODUCER"
    for key in ["official_use_allowed", "official_ranking_readiness_allowed", "official_weight_update_readiness_allowed", "broker_execution_supported", "shadow_activation"]:
        assert summary[key] == "FALSE"
    assert summary["official_weight_update_blocked"] == "TRUE"
    for key in ["data_trust_ranking_weight", "data_trust_alpha_contribution", "risk_additive_alpha_contribution", "market_regime_additive_alpha_contribution", "official_ranking_mutation_count", "official_factor_weight_mutation_count", "official_recommendation_count", "trade_action_count"]:
        assert summary[key] == "0"
    assert summary["ledger_producer_decision"] in ALLOWED_DECISIONS
    assert summary["recommended_next_stage"] in ALLOWED_NEXT
    assert summary["prototype_output_scope"] == "V21_029_RESEARCH_ONLY_SHADOW_OBSERVATION"
    for term in ["PRODUCTION", "REAL_BOOK", "OFFICIAL_ACTIVATION", "OFFICIAL_RANKING_READINESS", "OFFICIAL_WEIGHT_UPDATE_READINESS"]:
        assert term not in summary["final_status"]
        assert term not in summary["ledger_producer_decision"]

    ingest = read_csv(OUT_DIR / "V21_029_V21_025_DECISION_INGEST_AUDIT.csv")
    assert any(row["audit_item"] == "v21_025_decision_ingested" and row["audit_passed"] == "TRUE" for row in ingest)
    assert any(row["audit_item"] == "recommended_next_stage_v21_029" and row["audit_passed"] == "TRUE" for row in ingest)

    overlay = read_csv(OUT_DIR / "V21_029_CONTEXT_SPECIFIC_RISK_GATE_OVERLAY.csv")
    assert overlay
    assert all(row["risk_gate_applied_as_global_hard_gate"] == "FALSE" for row in overlay)
    assert all(row["blocked_or_demoted_preserved_in_diagnostics"] == "TRUE" for row in overlay)

    ledger = read_csv(OUT_DIR / "V21_029_OBSERVATION_LEDGER.csv")
    schedule = read_csv(OUT_DIR / "V21_029_FORWARD_OBSERVATION_SCHEDULE.csv")
    assert ledger
    assert schedule
    ids = [row["observation_id"] for row in ledger]
    assert all(ids)
    assert len(ids) == len(set(ids))
    assert all(row["research_only"] == "TRUE" for row in ledger)
    assert all(row["official_recommendation_created"] == "FALSE" for row in ledger)
    assert all(row["trade_action_created"] == "FALSE" for row in ledger)
    assert all(row["broker_execution_supported"] == "FALSE" for row in ledger)
    assert all(row["shadow_activation"] == "FALSE" for row in ledger)

    selections = read_csv(OUT_DIR / "V21_029_SHADOW_OBSERVATION_SELECTIONS.csv")
    assert selections
    assert all(row["selected_for_shadow_observation"] == "TRUE" for row in selections)
    assert all(row["official_recommendation_created"] == "FALSE" for row in selections)
    assert all(row["trade_action_created"] == "FALSE" for row in selections)

    gaps = read_csv(OUT_DIR / "V21_029_SOURCE_GAP_ANNOTATION.csv")
    assert gaps
    assert all(row["vix_label_missing_status"] == "MISSING_NOT_FABRICATED" for row in gaps)
    assert all("MISSING_NOT_FABRICATED" in row["macro_event_label_missing_status"] for row in gaps)

    guard = read_csv(OUT_DIR / "V21_029_GUARDRAIL_ENFORCEMENT_AUDIT.csv")
    by_item = {row["guardrail_item"]: row for row in guard}
    assert by_item["no_global_risk_hard_gate"]["guardrail_passed"] == "TRUE"
    assert by_item["official_ranking_mutation_count"]["observed_value"] == "0"
    assert by_item["broker_execution_supported"]["observed_value"] == "FALSE"

    decision = read_csv(OUT_DIR / "V21_029_SHADOW_OBSERVATION_LEDGER_PRODUCER_DECISION.csv")
    selected = [row for row in decision if row["selected_recommended_next_stage"] == "TRUE"]
    assert len(decision) == 1
    assert len(selected) == 1
    assert selected[0]["ledger_producer_decision"] in ALLOWED_DECISIONS
    assert selected[0]["recommended_next_stage"] in ALLOWED_NEXT
    assert selected[0]["shadow_activation"] == "FALSE"

    for output in REQUIRED_OUTPUTS:
        if output.suffix == ".csv":
            assert output.parent == OUT_DIR
            assert output.name.startswith("V21_029_")
    report_text = REPORT.read_text(encoding="utf-8").lower()
    for expected in ["research-only", "final ledger producer decision", "no broker execution", "no shadow activation", "what this stage did not produce", "recommended next stage"]:
        assert expected in report_text


def test_wrapper_parseable() -> None:
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)], cwd=ROOT, text=True, capture_output=True, check=True)
    for expected in [
        "STAGE_NAME=V21_029_WITHIN_REGIME_SHADOW_OBSERVATION_LEDGER_PRODUCER",
        "official_use_allowed=FALSE",
        "official_ranking_readiness_allowed=FALSE",
        "official_weight_update_readiness_allowed=FALSE",
        "official_weight_update_blocked=TRUE",
        "broker_execution_supported=FALSE",
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
    test_v21_029_contract()
    test_wrapper_parseable()
    print("V21.029 shadow observation ledger producer tests passed")
