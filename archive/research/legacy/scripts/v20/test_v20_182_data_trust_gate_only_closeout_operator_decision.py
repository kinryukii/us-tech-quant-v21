#!/usr/bin/env python
"""Tests for V20.182 DATA_TRUST gate-only closeout operator decision."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_182_data_trust_gate_only_closeout_operator_decision.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_182_DATA_TRUST_FINAL_OPERATOR_DECISION_PACKET.csv",
    FACTORS / "V20_182_DATA_TRUST_FINAL_EVIDENCE_SUMMARY.csv",
    FACTORS / "V20_182_DATA_TRUST_FINAL_GUARDRAIL_AUDIT.csv",
    FACTORS / "V20_182_DATA_TRUST_DAILY_RUNNER_INTEGRATION_STATUS.csv",
    FACTORS / "V20_182_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_182_DATA_TRUST_GATE_ONLY_CLOSEOUT_OPERATOR_DECISION_REPORT.md",
]
PROTECTED = [
    FACTORS / "V20_173_DATA_TRUST_OPERATOR_DECISION_PACKET.csv",
    FACTORS / "V20_173_DATA_TRUST_DECISION_EVIDENCE_SUMMARY.csv",
    FACTORS / "V20_173_DATA_TRUST_GUARDRAIL_CONFIRMATION_AUDIT.csv",
    FACTORS / "V20_173_NEXT_STAGE_GATE.csv",
    FACTORS / "V20_174_DATA_TRUST_DAILY_RUNNER_INTEGRATION_AUDIT.csv",
    FACTORS / "V20_174_DATA_TRUST_DAILY_RUNNER_COMPATIBILITY_AUDIT.csv",
    FACTORS / "V20_174_NEXT_STAGE_GATE.csv",
    FACTORS / "V20_175_DATA_TRUST_DAILY_RUNNER_SHADOW_OBSERVATION.csv",
    FACTORS / "V20_175_DATA_TRUST_DISCLOSURE_STABILITY_AUDIT.csv",
    FACTORS / "V20_175_NEXT_STAGE_GATE.csv",
    FACTORS / "V20_177_DATA_TRUST_MULTIDAY_OBSERVATION_PLAN.csv",
    FACTORS / "V20_177_NEXT_STAGE_GATE.csv",
    FACTORS / "V20_178_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_1.csv",
    FACTORS / "V20_178_NEXT_STAGE_GATE.csv",
    FACTORS / "V20_179_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_2.csv",
    FACTORS / "V20_179_NEXT_STAGE_GATE.csv",
    FACTORS / "V20_180_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_3.csv",
    FACTORS / "V20_180_NEXT_STAGE_GATE.csv",
    FACTORS / "V20_181_DATA_TRUST_MULTIDAY_OBSERVATION_3RUN_SUMMARY.csv",
    FACTORS / "V20_181_DATA_TRUST_AGGREGATE_GUARDRAIL_SUMMARY.csv",
    FACTORS / "V20_181_DATA_TRUST_RUN_TO_RUN_STABILITY_SUMMARY.csv",
    FACTORS / "V20_181_DATA_TRUST_CLOSEOUT_DECISION_EVIDENCE_PACKET.csv",
    FACTORS / "V20_181_NEXT_STAGE_GATE.csv",
]
PASS_STATUS = "PASS_V20_182_DATA_TRUST_GATE_ONLY_CLOSEOUT_OPERATOR_DECISION_READY_FOR_V20_183_READ_CENTER_INTEGRATION"
RECOMMENDED_DECISION = "APPROVE_DATA_TRUST_ZERO_WEIGHT_GATE_ONLY_CLOSEOUT_AND_CONTINUE_DAILY_RUNNER_SHADOW_OBSERVATION"
AVAILABLE_DECISIONS = {
    "APPROVE_DATA_TRUST_ZERO_WEIGHT_GATE_ONLY_CLOSEOUT",
    "CONTINUE_DATA_TRUST_MULTIDAY_SHADOW_OBSERVATION",
    "REQUEST_ADDITIONAL_DATA_TRUST_REMEDIATION",
    "REJECT_DATA_TRUST_DAILY_RUNNER_INTEGRATION",
}
SAFETY_FALSE_FIELDS = [
    "formal_activation_allowed", "promotion_ready", "official_recommendation_created",
    "official_ranking_mutated", "official_weight_change_created",
    "official_weight_registry_mutated", "weight_mutated", "real_book_action_created",
    "trade_action_created", "broker_execution_supported", "performance_claim_created",
    "shadow_weight_expansion_allowed",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected_hashes() -> dict[Path, str]:
    return {path: digest(path) for path in PROTECTED if path.exists()}


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE"
        if "data_trust_scoring_weight" in row:
            assert row["data_trust_scoring_weight"] == "0.0000000000"
        if "data_trust_role" in row:
            assert row["data_trust_role"] == "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"


def test_data_trust_gate_only_closeout_operator_decision() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected artifacts were mutated"
    stdout = result.stdout
    for expected in [
        PASS_STATUS,
        f"RECOMMENDED_OPERATOR_DECISION={RECOMMENDED_DECISION}",
        "DATA_TRUST_GATE_ONLY_CLOSEOUT_COMPLETE=TRUE",
        "DATA_TRUST_DAILY_RUNNER_SHADOW_OBSERVATION_CONTINUED=TRUE",
        "DATA_TRUST_ZERO_WEIGHT=TRUE",
        "DATA_TRUST_GATE_ONLY=TRUE",
        "DATA_TRUST_AUDIT_ONLY=TRUE",
        "DATA_TRUST_DAILY_RUNNER_DISCLOSED=TRUE",
        "READY_FOR_V20_183_DAILY_RESEARCH_RUNNER_READ_CENTER_INTEGRATION=TRUE",
        "READY_FOR_OFFICIAL_USE=FALSE",
        "REAL_BOOK_USE_ALLOWED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "OFFICIAL_WEIGHT_MUTATION_ALLOWED=FALSE",
        "OFFICIAL_WEIGHT_REGISTRY_MUTATED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATION_ATTEMPTED=FALSE",
        "REAL_BOOK_USE_ATTEMPTED=FALSE",
        "FINAL_EVIDENCE_SUMMARY_PASS=TRUE",
        "FINAL_GUARDRAIL_AUDIT_PASS=TRUE",
        "DAILY_RUNNER_INTEGRATION_STATUS_PASS=TRUE",
        "OFFICIAL_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    packet = read_csv(OUTPUTS[0])
    evidence = read_csv(OUTPUTS[1])
    guardrail = read_csv(OUTPUTS[2])
    status = read_csv(OUTPUTS[3])
    gate = read_csv(OUTPUTS[4])[0]

    assert {row["operator_decision_option"] for row in packet} == AVAILABLE_DECISIONS
    assert sum(row["recommended_option"] == "TRUE" for row in packet) == 1
    assert all(row["recommended_operator_decision"] == RECOMMENDED_DECISION for row in packet)
    assert all(row["official_use_enabled_by_option"] == "FALSE" for row in packet)
    assert all(row["real_book_use_enabled_by_option"] == "FALSE" for row in packet)
    assert all(row["official_recommendation_enabled_by_option"] == "FALSE" for row in packet)
    assert all(row["official_weight_mutation_enabled_by_option"] == "FALSE" for row in packet)
    assert all(row["evidence_passed"] == "TRUE" for row in evidence)
    assert all(row["guardrail_passed"] == "TRUE" for row in guardrail)
    assert len(status) == 1
    assert status[0]["data_trust_zero_weight"] == "TRUE"
    assert status[0]["data_trust_gate_only"] == "TRUE"
    assert status[0]["data_trust_audit_only"] == "TRUE"
    assert status[0]["data_trust_daily_runner_disclosed"] == "TRUE"
    assert status[0]["data_trust_shadow_observation_continued"] == "TRUE"
    assert status[0]["ready_for_read_center_integration"] == "TRUE"
    assert gate["final_status"] == PASS_STATUS
    assert gate["recommended_operator_decision"] == RECOMMENDED_DECISION
    assert gate["data_trust_gate_only_closeout_complete"] == "TRUE"
    assert gate["data_trust_daily_runner_shadow_observation_continued"] == "TRUE"
    assert gate["ready_for_v20_183_daily_research_runner_read_center_integration"] == "TRUE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert gate["real_book_use_allowed"] == "FALSE"
    assert gate["official_recommendation_created"] == "FALSE"
    assert gate["official_weight_mutation_allowed"] == "FALSE"
    assert_safety([gate, *packet, *evidence[:3], *guardrail[:3], *status])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "Final operator closeout approves DATA_TRUST" in report


if __name__ == "__main__":
    test_data_trust_gate_only_closeout_operator_decision()
    print("PASS test_v20_182_data_trust_gate_only_closeout_operator_decision")
