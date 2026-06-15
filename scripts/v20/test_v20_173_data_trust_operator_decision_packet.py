#!/usr/bin/env python
"""Tests for V20.173 DATA_TRUST operator decision packet."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_173_data_trust_operator_decision_packet.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_173_DATA_TRUST_OPERATOR_DECISION_PACKET.csv",
    FACTORS / "V20_173_DATA_TRUST_DECISION_EVIDENCE_SUMMARY.csv",
    FACTORS / "V20_173_DATA_TRUST_GUARDRAIL_CONFIRMATION_AUDIT.csv",
    FACTORS / "V20_173_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_173_DATA_TRUST_OPERATOR_DECISION_PACKET_REPORT.md",
]
PROTECTED = [
    CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv",
    FACTORS / "V20_170_R3_R2_NEXT_STAGE_GATE.csv",
    FACTORS / "V20_171_NEXT_STAGE_GATE.csv",
    FACTORS / "V20_172_NEXT_STAGE_GATE.csv",
]
PASS_STATUS = "PASS_V20_173_DATA_TRUST_OPERATOR_DECISION_PACKET_READY_FOR_DAILY_RUNNER_GATE_ONLY_INTEGRATION"
RECOMMENDED_DECISION = "KEEP_DATA_TRUST_ZERO_WEIGHT_GATE_ONLY_AUDIT_LAYER_AND_CONTINUE_SHADOW_OBSERVATION"

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


def test_data_trust_operator_decision_packet() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected artifacts were mutated"
    stdout = result.stdout
    for expected in [
        PASS_STATUS,
        "BASELINE_CANDIDATE_COUNT=40",
        "DATA_TRUST_DIRECT_PASS_CANDIDATE_COUNT=40",
        "OFFICIAL_RANKING_SCORE_MUTATION_COUNT=0",
        "OFFICIAL_RANK_MUTATION_COUNT=0",
        "DATA_TRUST_SCORE_CONTRIBUTION_SUM=0.0000000000",
        "DATA_TRUST_NONZERO_WEIGHT_COUNT=0",
        "COMPLETE_DISCLOSURE_CANDIDATE_COUNT=40",
        "GUARDRAIL_FAIL_COUNT=0",
        f"RECOMMENDED_OPERATOR_DECISION={RECOMMENDED_DECISION}",
        "READY_FOR_DATA_TRUST_GATE_ONLY_DAILY_RUNNER_INTEGRATION=TRUE",
        "READY_FOR_OFFICIAL_USE=FALSE",
        "REAL_BOOK_USE_ALLOWED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "OFFICIAL_WEIGHT_MUTATION_ALLOWED=FALSE",
        "OFFICIAL_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    packet = read_csv(OUTPUTS[0])
    summary = read_csv(OUTPUTS[1])
    guardrails = read_csv(OUTPUTS[2])
    gate = read_csv(OUTPUTS[3])[0]
    assert len(packet) == 4
    assert len(summary) == 7
    assert len(guardrails) == 8
    assert {row["decision_option"] for row in packet} == {
        "KEEP_DATA_TRUST_ZERO_WEIGHT_GATE_ONLY_AUDIT_LAYER",
        "CONTINUE_DATA_TRUST_SHADOW_OBSERVATION",
        "REQUEST_ADDITIONAL_DATA_TRUST_VALIDATION",
        "REJECT_DATA_TRUST_GATE_ONLY_INTEGRATION",
    }
    assert all(row["option_available"] == "TRUE" for row in packet)
    assert all(row["official_use_enabled_by_option"] == "FALSE" for row in packet)
    assert all(row["evidence_passed"] == "TRUE" for row in summary)
    assert all(row["guardrail_passed"] == "TRUE" for row in guardrails)
    assert gate["final_status"] == PASS_STATUS
    assert gate["recommended_operator_decision"] == RECOMMENDED_DECISION
    assert gate["ready_for_data_trust_gate_only_daily_runner_integration"] == "TRUE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert_safety([gate, *packet, *summary[:3], *guardrails[:3]])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "zero-weight gate-only audit layer" in report


if __name__ == "__main__":
    test_data_trust_operator_decision_packet()
    print("PASS test_v20_173_data_trust_operator_decision_packet")
