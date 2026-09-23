#!/usr/bin/env python
"""Tests for V20.192 current chain release candidate with DATA_TRUST gate-only metadata."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_192_current_chain_release_candidate_with_data_trust_gate_only.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_192_CURRENT_CHAIN_RELEASE_CANDIDATE_PACKET.csv",
    FACTORS / "V20_192_CURRENT_CHAIN_RELEASE_CANDIDATE_GUARDRAIL_AUDIT.csv",
    FACTORS / "V20_192_CURRENT_CHAIN_READINESS_AUDIT.csv",
    FACTORS / "V20_192_DATA_TRUST_SEALED_STATUS_AUDIT.csv",
    FACTORS / "V20_192_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_192_CURRENT_CHAIN_RELEASE_CANDIDATE_WITH_DATA_TRUST_GATE_ONLY_REPORT.md",
]
PROTECTED = [
    FACTORS / "V20_188_DATA_TRUST_GATE_ONLY_RELEASE_SEAL.csv",
    FACTORS / "V20_188_NEXT_STAGE_GATE.csv",
    FACTORS / "V20_189_DATA_TRUST_CURRENT_CHAIN_HANDOFF_AUDIT.csv",
    FACTORS / "V20_189_NEXT_STAGE_GATE.csv",
    FACTORS / "V20_190_CURRENT_CHAIN_SMOKE_TEST_AUDIT.csv",
    FACTORS / "V20_190_NEXT_STAGE_GATE.csv",
    FACTORS / "V20_191_DAILY_RUNNER_REGRESSION_AUDIT.csv",
    FACTORS / "V20_191_CANDIDATE_UNIVERSE_REGRESSION_AUDIT.csv",
    FACTORS / "V20_191_RANKING_WEIGHT_REGRESSION_AUDIT.csv",
    FACTORS / "V20_191_READ_CENTER_REGRESSION_AUDIT.csv",
    FACTORS / "V20_191_OFFICIAL_USE_REGRESSION_AUDIT.csv",
    FACTORS / "V20_191_DOWNSTREAM_COMPATIBILITY_REGRESSION_AUDIT.csv",
    FACTORS / "V20_191_NEXT_STAGE_GATE.csv",
]
PASS_STATUS = "PASS_V20_192_CURRENT_CHAIN_RELEASE_CANDIDATE_WITH_DATA_TRUST_GATE_ONLY_READY_FOR_V20_193_FINAL_OPERATOR_ACCEPTANCE"
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


def test_current_chain_release_candidate_with_data_trust_gate_only() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected artifacts were mutated"
    stdout = result.stdout
    for expected in [
        PASS_STATUS,
        "CURRENT_CHAIN_RELEASE_CANDIDATE_CREATED=TRUE",
        "RELEASE_CANDIDATE_GUARDRAIL_PASS=TRUE",
        "CURRENT_CHAIN_READINESS_PASS=TRUE",
        "DATA_TRUST_SEALED_STATUS_PASS=TRUE",
        "BASELINE_CANDIDATE_COUNT=40",
        "DAILY_RUNNER_CANDIDATE_COUNT=40",
        "READ_CENTER_DISPLAY_CANDIDATE_COUNT=40",
        "CANDIDATE_REMOVED_OR_REORDERED_COUNT=0",
        "OFFICIAL_RANKING_SCORE_MUTATION_COUNT=0",
        "OFFICIAL_RANK_MUTATION_COUNT=0",
        "DATA_TRUST_SCORE_CONTRIBUTION_SUM=0.0000000000",
        "DATA_TRUST_NONZERO_WEIGHT_COUNT=0",
        "READY_FOR_V20_193_FINAL_OPERATOR_ACCEPTANCE=TRUE",
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
    guardrail = read_csv(OUTPUTS[1])
    readiness = read_csv(OUTPUTS[2])
    status = read_csv(OUTPUTS[3])
    gate = read_csv(OUTPUTS[4])[0]
    assert len(packet) == 1
    assert packet[0]["release_candidate_created"] == "TRUE"
    assert packet[0]["data_trust_sealed_status_preserved"] == "TRUE"
    assert packet[0]["data_trust_zero_weight"] == "TRUE"
    assert packet[0]["data_trust_gate_only"] == "TRUE"
    assert packet[0]["data_trust_audit_only"] == "TRUE"
    assert packet[0]["data_trust_read_center_disclosed"] == "TRUE"
    assert packet[0]["daily_runner_candidate_universe_unchanged"] == "TRUE"
    assert packet[0]["candidate_removed_or_reordered_count"] == "0"
    assert packet[0]["official_ranking_score_mutation_count"] == "0"
    assert packet[0]["official_rank_mutation_count"] == "0"
    assert packet[0]["data_trust_score_contribution_sum"] == "0.0000000000"
    assert packet[0]["data_trust_nonzero_weight_count"] == "0"
    assert all(row["audit_check_passed"] == "TRUE" for row in guardrail)
    assert all(row["audit_check_passed"] == "TRUE" for row in readiness)
    assert all(row["audit_check_passed"] == "TRUE" for row in status)
    assert gate["final_status"] == PASS_STATUS
    assert gate["current_chain_release_candidate_created"] == "TRUE"
    assert gate["release_candidate_guardrail_pass"] == "TRUE"
    assert gate["current_chain_readiness_pass"] == "TRUE"
    assert gate["data_trust_sealed_status_pass"] == "TRUE"
    assert gate["ready_for_v20_193_final_operator_acceptance"] == "TRUE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert gate["real_book_use_allowed"] == "FALSE"
    assert gate["official_recommendation_created"] == "FALSE"
    assert gate["official_weight_mutation_allowed"] == "FALSE"
    assert_safety([gate, *packet, *guardrail[:3], *readiness, *status[:3]])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "Release candidate created with DATA_TRUST preserved as zero-weight gate-only audit metadata" in report


if __name__ == "__main__":
    test_current_chain_release_candidate_with_data_trust_gate_only()
    print("PASS test_v20_192_current_chain_release_candidate_with_data_trust_gate_only")
