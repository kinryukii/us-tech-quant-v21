#!/usr/bin/env python
"""Tests for V20.193 final operator acceptance with DATA_TRUST gate-only metadata."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_193_final_operator_acceptance_with_data_trust_gate_only.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_193_FINAL_OPERATOR_ACCEPTANCE_PACKET.csv",
    FACTORS / "V20_193_FINAL_ACCEPTANCE_EVIDENCE_SUMMARY.csv",
    FACTORS / "V20_193_FINAL_GUARDRAIL_CONFIRMATION_AUDIT.csv",
    FACTORS / "V20_193_DAILY_RUNNER_ACCEPTANCE_STATUS.csv",
    FACTORS / "V20_193_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_193_FINAL_OPERATOR_ACCEPTANCE_WITH_DATA_TRUST_GATE_ONLY_REPORT.md",
]
PROTECTED = [
    FACTORS / "V20_192_CURRENT_CHAIN_RELEASE_CANDIDATE_PACKET.csv",
    FACTORS / "V20_192_CURRENT_CHAIN_RELEASE_CANDIDATE_GUARDRAIL_AUDIT.csv",
    FACTORS / "V20_192_CURRENT_CHAIN_READINESS_AUDIT.csv",
    FACTORS / "V20_192_DATA_TRUST_SEALED_STATUS_AUDIT.csv",
    FACTORS / "V20_192_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_192_CURRENT_CHAIN_RELEASE_CANDIDATE_WITH_DATA_TRUST_GATE_ONLY_REPORT.md",
]
PASS_STATUS = "PASS_V20_193_FINAL_OPERATOR_ACCEPTANCE_WITH_DATA_TRUST_GATE_ONLY_READY_FOR_DAILY_RESEARCH_RUNNER_REGULAR_USE"
RECOMMENDED_DECISION = "ACCEPT_CURRENT_CHAIN_RELEASE_CANDIDATE_FOR_DAILY_RESEARCH_USE_WITH_DATA_TRUST_ZERO_WEIGHT_GATE_ONLY_AND_CONTINUED_SHADOW_OBSERVATION"
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


def test_final_operator_acceptance_with_data_trust_gate_only() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected artifacts were mutated"
    stdout = result.stdout
    for expected in [
        PASS_STATUS,
        f"RECOMMENDED_OPERATOR_DECISION={RECOMMENDED_DECISION}",
        "FINAL_OPERATOR_ACCEPTANCE_COMPLETE=TRUE",
        "CURRENT_CHAIN_DAILY_RESEARCH_USE_ACCEPTED=TRUE",
        "DATA_TRUST_ZERO_WEIGHT_GATE_ONLY_AUDIT_STATUS_PRESERVED=TRUE",
        "READY_FOR_DAILY_RESEARCH_RUNNER_REGULAR_USE=TRUE",
        "CANDIDATE_REMOVED_OR_REORDERED_COUNT=0",
        "OFFICIAL_RANKING_SCORE_MUTATION_COUNT=0",
        "OFFICIAL_RANK_MUTATION_COUNT=0",
        "DATA_TRUST_SCORE_CONTRIBUTION_SUM=0.0000000000",
        "DATA_TRUST_NONZERO_WEIGHT_COUNT=0",
        "READY_FOR_OFFICIAL_USE=FALSE",
        "REAL_BOOK_USE_ALLOWED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "OFFICIAL_WEIGHT_MUTATION_ALLOWED=FALSE",
        "DATA_TRUST_ZERO_WEIGHT=TRUE",
        "DATA_TRUST_GATE_ONLY=TRUE",
        "DATA_TRUST_AUDIT_ONLY=TRUE",
        "DATA_TRUST_READ_CENTER_DISCLOSED=TRUE",
        "OFFICIAL_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    packet = read_csv(OUTPUTS[0])
    evidence = read_csv(OUTPUTS[1])
    guardrail = read_csv(OUTPUTS[2])
    status = read_csv(OUTPUTS[3])[0]
    gate = read_csv(OUTPUTS[4])[0]
    assert len(packet) == 4
    assert sum(row["recommended_option"] == "TRUE" for row in packet) == 1
    assert packet[0]["operator_decision_option"] == "ACCEPT_CURRENT_CHAIN_RELEASE_CANDIDATE_FOR_DAILY_RESEARCH_USE"
    assert packet[0]["recommended_operator_decision"] == RECOMMENDED_DECISION
    assert packet[0]["operator_decision_captured"] == "TRUE"
    for row in packet:
        assert row["option_available"] == "TRUE"
        assert row["official_use_enabled_by_option"] == "FALSE"
        assert row["real_book_use_enabled_by_option"] == "FALSE"
        assert row["official_recommendation_enabled_by_option"] == "FALSE"
        assert row["official_weight_mutation_enabled_by_option"] == "FALSE"
    assert all(row["evidence_passed"] == "TRUE" for row in evidence)
    assert all(row["guardrail_passed"] == "TRUE" for row in guardrail)
    assert status["daily_runner_acceptance_status"] == "ACCEPTED_FOR_DAILY_RESEARCH_RUNNER_REGULAR_USE"
    assert status["current_chain_daily_research_use_accepted"] == "TRUE"
    assert status["data_trust_zero_weight_gate_only_audit_status_preserved"] == "TRUE"
    assert status["data_trust_shadow_observation_continued"] == "TRUE"
    assert status["ready_for_daily_research_runner_regular_use"] == "TRUE"
    assert status["ready_for_official_use"] == "FALSE"
    assert status["real_book_use_allowed"] == "FALSE"
    assert status["official_recommendation_created"] == "FALSE"
    assert status["official_weight_mutation_allowed"] == "FALSE"
    assert gate["final_status"] == PASS_STATUS
    assert gate["recommended_operator_decision"] == RECOMMENDED_DECISION
    assert gate["final_operator_acceptance_complete"] == "TRUE"
    assert gate["current_chain_daily_research_use_accepted"] == "TRUE"
    assert gate["data_trust_zero_weight_gate_only_audit_status_preserved"] == "TRUE"
    assert gate["ready_for_daily_research_runner_regular_use"] == "TRUE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert gate["real_book_use_allowed"] == "FALSE"
    assert gate["official_recommendation_created"] == "FALSE"
    assert gate["official_weight_mutation_allowed"] == "FALSE"
    assert_safety([gate, status, *packet, *evidence[:3], *guardrail[:3]])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "Final operator acceptance confirms current chain daily research use" in report


if __name__ == "__main__":
    test_final_operator_acceptance_with_data_trust_gate_only()
    print("PASS test_v20_193_final_operator_acceptance_with_data_trust_gate_only")
