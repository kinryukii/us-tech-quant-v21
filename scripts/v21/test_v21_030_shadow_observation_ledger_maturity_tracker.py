#!/usr/bin/env python
"""Tests for V21.030 shadow observation ledger maturity tracker."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_030_shadow_observation_ledger_maturity_tracker.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_030_shadow_observation_ledger_maturity_tracker.ps1"
OUT_DIR = ROOT / "outputs" / "v21" / "shadow_observation"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_030_SHADOW_OBSERVATION_LEDGER_MATURITY_TRACKER_REPORT.md"

REQUIRED_OUTPUTS = [
    OUT_DIR / "V21_030_V21_029_DECISION_INGEST_AUDIT.csv",
    OUT_DIR / "V21_030_LEDGER_INTEGRITY_AUDIT.csv",
    OUT_DIR / "V21_030_FORWARD_SCHEDULE_MATURITY_AUDIT.csv",
    OUT_DIR / "V21_030_REALIZED_FORWARD_RETURNS.csv",
    OUT_DIR / "V21_030_PENDING_OBSERVATIONS.csv",
    OUT_DIR / "V21_030_MATURITY_SUMMARY_BY_CONTEXT.csv",
    OUT_DIR / "V21_030_MATURITY_SUMMARY_BY_LANE.csv",
    OUT_DIR / "V21_030_FALLBACK_SNAPSHOT_LIMITATION_AUDIT.csv",
    OUT_DIR / "V21_030_SOURCE_GAP_AND_PRICE_AVAILABILITY_AUDIT.csv",
    OUT_DIR / "V21_030_GUARDRAIL_ENFORCEMENT_AUDIT.csv",
    OUT_DIR / "V21_030_SHADOW_LEDGER_MATURITY_TRACKER_DECISION.csv",
    OUT_DIR / "V21_030_SHADOW_OBSERVATION_LEDGER_MATURITY_TRACKER_SUMMARY.csv",
    REPORT,
]

INPUTS = [
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
    ROOT / "outputs" / "v21" / "read_center" / "V21_029_WITHIN_REGIME_SHADOW_OBSERVATION_LEDGER_PRODUCER_REPORT.md",
]

ALLOWED_DECISIONS = {
    "SHADOW_LEDGER_MATURITY_TRACKER_READY_WITH_MATURED_RESULTS",
    "SHADOW_LEDGER_MATURITY_TRACKER_READY_ALL_PENDING",
    "SHADOW_LEDGER_MATURITY_TRACKER_PARTIAL_PRICE_GAPS",
    "SHADOW_LEDGER_MATURITY_TRACKER_BLOCKED_BY_LEDGER_INTEGRITY_FAILURE",
    "SHADOW_LEDGER_MATURITY_TRACKER_BLOCKED_BY_REQUIRED_PRICE_DATA_MISSING",
}
ALLOWED_NEXT = {
    "V21.031_DAILY_WITHIN_REGIME_SHADOW_OBSERVATION_REPORT",
    "V21.032_CURRENT_REPAIRED_LABEL_DAILY_PRODUCER",
    "V21.033_SHADOW_LEDGER_MATURED_RESULT_EVALUATOR",
    "V21.028_MARKET_REGIME_DATA_PRODUCER_IMPLEMENTATION",
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


def test_v21_030_contract() -> None:
    result = run_stage()
    assert "STAGE_NAME=V21_030_SHADOW_OBSERVATION_LEDGER_MATURITY_TRACKER" in result.stdout
    for path in REQUIRED_OUTPUTS:
        assert path.exists(), f"missing output {path}"
        assert path.stat().st_size > 0, f"empty output {path}"

    summary = read_csv(OUT_DIR / "V21_030_SHADOW_OBSERVATION_LEDGER_MATURITY_TRACKER_SUMMARY.csv")[0]
    assert summary["research_only"] == "TRUE"
    assert summary["v21_029_ledger_producer_decision"] in {"SHADOW_OBSERVATION_LEDGER_PARTIAL_CURRENT_SNAPSHOT_FALLBACK", "SHADOW_OBSERVATION_LEDGER_PRODUCED_RESEARCH_ONLY"}
    assert summary["v21_029_recommended_next_stage"] == "V21.030_SHADOW_OBSERVATION_LEDGER_MATURITY_TRACKER"
    for key in ["official_use_allowed", "official_ranking_readiness_allowed", "official_weight_update_readiness_allowed", "broker_execution_supported", "shadow_activation"]:
        assert summary[key] == "FALSE"
    assert summary["official_weight_update_blocked"] == "TRUE"
    for key in ["data_trust_ranking_weight", "data_trust_alpha_contribution", "risk_additive_alpha_contribution", "market_regime_additive_alpha_contribution", "official_ranking_mutation_count", "official_factor_weight_mutation_count", "official_recommendation_count", "trade_action_count"]:
        assert summary[key] == "0"
    assert summary["maturity_tracker_decision"] in ALLOWED_DECISIONS
    assert summary["recommended_next_stage"] in ALLOWED_NEXT
    assert summary["prototype_output_scope"] == "V21_030_RESEARCH_ONLY_SHADOW_OBSERVATION"
    for term in ["PRODUCTION", "REAL_BOOK", "OFFICIAL_ACTIVATION", "OFFICIAL_RANKING_READINESS", "OFFICIAL_WEIGHT_UPDATE_READINESS", "SHADOW_ACTIVATION_READINESS"]:
        assert term not in summary["final_status"]
        assert term not in summary["maturity_tracker_decision"]

    ingest = read_csv(OUT_DIR / "V21_030_V21_029_DECISION_INGEST_AUDIT.csv")
    assert any(row["audit_item"] == "v21_029_decision_ingested" and row["audit_passed"] == "TRUE" for row in ingest)
    assert any(row["audit_item"] == "recommended_next_stage_v21_030" and row["audit_passed"] == "TRUE" for row in ingest)

    integrity = read_csv(OUT_DIR / "V21_030_LEDGER_INTEGRITY_AUDIT.csv")[0]
    assert int(integrity["row_count"]) > 0
    assert "duplicate_observation_id_count" in integrity
    assert integrity["research_only_flag_consistency"] == "TRUE"

    maturity = read_csv(OUT_DIR / "V21_030_FORWARD_SCHEDULE_MATURITY_AUDIT.csv")
    assert maturity
    assert {row["maturity_status"] for row in maturity} & {"MATURED_PRICE_AVAILABLE", "NOT_YET_MATURED", "MATURED_PRICE_MISSING"}

    pending = read_csv(OUT_DIR / "V21_030_PENDING_OBSERVATIONS.csv")
    assert pending
    assert all(row["realized_forward_return"] == "PENDING" for row in pending)

    returns = read_csv(OUT_DIR / "V21_030_REALIZED_FORWARD_RETURNS.csv")
    assert returns
    assert all(row["maturity_status"] == "MATURED_PRICE_AVAILABLE" for row in returns)
    assert all(row["realized_forward_return"] != "" for row in returns)
    assert all(row["pit_validation_status"].startswith("PASS") for row in returns)

    fallback = read_csv(OUT_DIR / "V21_030_FALLBACK_SNAPSHOT_LIMITATION_AUDIT.csv")
    assert fallback
    assert fallback[0]["fallback_as_of_date"] != ""

    gaps = read_csv(OUT_DIR / "V21_030_SOURCE_GAP_AND_PRICE_AVAILABILITY_AUDIT.csv")
    assert any(row["gap_item"] == "missing_vix_labels" for row in gaps)
    assert any(row["gap_item"] == "missing_macro_event_labels" for row in gaps)

    guard = read_csv(OUT_DIR / "V21_030_GUARDRAIL_ENFORCEMENT_AUDIT.csv")
    by_item = {row["guardrail_item"]: row for row in guard}
    assert by_item["no_global_risk_hard_gate"]["guardrail_passed"] == "TRUE"
    assert by_item["official_ranking_mutation_count"]["observed_value"] == "0"
    assert by_item["broker_execution_supported"]["observed_value"] == "FALSE"

    decision = read_csv(OUT_DIR / "V21_030_SHADOW_LEDGER_MATURITY_TRACKER_DECISION.csv")
    selected = [row for row in decision if row["selected_recommended_next_stage"] == "TRUE"]
    assert len(decision) == 1
    assert len(selected) == 1
    assert selected[0]["maturity_tracker_decision"] in ALLOWED_DECISIONS
    assert selected[0]["recommended_next_stage"] in ALLOWED_NEXT
    assert selected[0]["shadow_activation"] == "FALSE"

    for output in REQUIRED_OUTPUTS:
        if output.suffix == ".csv":
            assert output.parent == OUT_DIR
            assert output.name.startswith("V21_030_")
    report_text = REPORT.read_text(encoding="utf-8").lower()
    for expected in ["research-only", "final maturity tracker decision", "ledger integrity audit", "pending observations", "guardrail enforcement", "no shadow activation", "recommended next stage"]:
        assert expected in report_text


def test_wrapper_parseable() -> None:
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)], cwd=ROOT, text=True, capture_output=True, check=True)
    for expected in [
        "STAGE_NAME=V21_030_SHADOW_OBSERVATION_LEDGER_MATURITY_TRACKER",
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
    test_v21_030_contract()
    test_wrapper_parseable()
    print("V21.030 shadow observation ledger maturity tracker tests passed")
