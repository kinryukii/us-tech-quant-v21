#!/usr/bin/env python
"""Tests for V20.185 DATA_TRUST daily runner final gate-only release packet."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_185_daily_runner_final_gate_only_release_packet.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_185_DATA_TRUST_FINAL_GATE_ONLY_RELEASE_PACKET.csv",
    FACTORS / "V20_185_DATA_TRUST_FINAL_RELEASE_GUARDRAIL_AUDIT.csv",
    FACTORS / "V20_185_OPERATOR_FACING_RELEASE_SUMMARY.csv",
    FACTORS / "V20_185_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_185_DAILY_RUNNER_FINAL_GATE_ONLY_RELEASE_PACKET_REPORT.md",
]
PROTECTED = [
    FACTORS / "V20_182_DATA_TRUST_FINAL_OPERATOR_DECISION_PACKET.csv",
    FACTORS / "V20_182_DATA_TRUST_FINAL_GUARDRAIL_AUDIT.csv",
    FACTORS / "V20_182_DATA_TRUST_DAILY_RUNNER_INTEGRATION_STATUS.csv",
    FACTORS / "V20_182_NEXT_STAGE_GATE.csv",
    FACTORS / "V20_183_DATA_TRUST_READ_CENTER_INTEGRATION_AUDIT.csv",
    FACTORS / "V20_183_DATA_TRUST_READ_CENTER_DISPLAY_SAMPLE.csv",
    FACTORS / "V20_183_OFFICIAL_USE_GUARD_AUDIT.csv",
    FACTORS / "V20_183_NEXT_STAGE_GATE.csv",
    FACTORS / "V20_184_OPERATOR_READABILITY_AUDIT.csv",
    FACTORS / "V20_184_DATA_TRUST_MISLEADING_LANGUAGE_AUDIT.csv",
    FACTORS / "V20_184_OPERATOR_DISPLAY_RECOMMENDATION.csv",
    FACTORS / "V20_184_NEXT_STAGE_GATE.csv",
]
PASS_STATUS = "PASS_V20_185_DAILY_RUNNER_FINAL_GATE_ONLY_RELEASE_PACKET_READY_FOR_V20_186_RELEASE_LOCK"
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


def test_daily_runner_final_gate_only_release_packet() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected artifacts were mutated"
    stdout = result.stdout
    for expected in [
        PASS_STATUS,
        "DATA_TRUST_GATE_ONLY_RELEASE_PASS=TRUE",
        "RANKING_MUTATION_GUARD_PASS=TRUE",
        "ZERO_WEIGHT_GUARD_PASS=TRUE",
        "OFFICIAL_USE_GUARD_PASS=TRUE",
        "OFFICIAL_RANKING_SCORE_MUTATION_COUNT=0",
        "OFFICIAL_RANK_MUTATION_COUNT=0",
        "DATA_TRUST_SCORE_CONTRIBUTION_SUM=0.0000000000",
        "DATA_TRUST_NONZERO_WEIGHT_COUNT=0",
        "RELEASED_AS_OFFICIAL_SCORING_FACTOR=FALSE",
        "RELEASED_AS_OFFICIAL_RANKING_WEIGHT=FALSE",
        "RELEASED_AS_OFFICIAL_RECOMMENDATION_TRIGGER=FALSE",
        "RELEASED_AS_REAL_BOOK_PERMISSION_GATE=FALSE",
        "READY_FOR_V20_186_DAILY_RESEARCH_RUNNER_RELEASE_LOCK=TRUE",
        "READY_FOR_OFFICIAL_USE=FALSE",
        "REAL_BOOK_USE_ALLOWED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "OFFICIAL_WEIGHT_MUTATION_ALLOWED=FALSE",
        "DATA_TRUST_ZERO_WEIGHT=TRUE",
        "DATA_TRUST_GATE_ONLY=TRUE",
        "DATA_TRUST_AUDIT_ONLY=TRUE",
        "DATA_TRUST_READ_CENTER_DISCLOSED=TRUE",
        "DATA_TRUST_SHADOW_OBSERVATION_CONTINUED=TRUE",
        "OFFICIAL_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    packet = read_csv(OUTPUTS[0])
    guardrail = read_csv(OUTPUTS[1])
    summary = read_csv(OUTPUTS[2])
    gate = read_csv(OUTPUTS[3])[0]
    assert len(packet) == 1
    row = packet[0]
    assert row["release_status"] == "RELEASED_FOR_DAILY_RUNNER_GATE_ONLY_AUDIT_USE"
    assert row["released_as_zero_weight"] == "TRUE"
    assert row["released_as_gate_only"] == "TRUE"
    assert row["released_as_audit_only"] == "TRUE"
    assert row["released_as_read_center_disclosed"] == "TRUE"
    assert row["released_as_shadow_observation_continued"] == "TRUE"
    assert row["released_as_official_scoring_factor"] == "FALSE"
    assert row["released_as_official_ranking_weight"] == "FALSE"
    assert row["released_as_official_recommendation_trigger"] == "FALSE"
    assert row["released_as_real_book_permission_gate"] == "FALSE"
    assert row["official_ranking_score_mutation_count"] == "0"
    assert row["official_rank_mutation_count"] == "0"
    assert row["data_trust_score_contribution_sum"] == "0.0000000000"
    assert row["data_trust_nonzero_weight_count"] == "0"
    assert all(item["guardrail_passed"] == "TRUE" for item in guardrail)
    assert len(summary) == 1
    assert summary[0]["release_packet_pass"] == "TRUE"
    assert summary[0]["ranking_mutation_guard_pass"] == "TRUE"
    assert summary[0]["zero_weight_guard_pass"] == "TRUE"
    assert summary[0]["official_use_guard_pass"] == "TRUE"
    assert summary[0]["ready_for_v20_186_daily_research_runner_release_lock"] == "TRUE"
    assert gate["final_status"] == PASS_STATUS
    assert gate["data_trust_gate_only_release_pass"] == "TRUE"
    assert gate["ranking_mutation_guard_pass"] == "TRUE"
    assert gate["zero_weight_guard_pass"] == "TRUE"
    assert gate["official_use_guard_pass"] == "TRUE"
    assert gate["ready_for_v20_186_daily_research_runner_release_lock"] == "TRUE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert gate["real_book_use_allowed"] == "FALSE"
    assert gate["official_recommendation_created"] == "FALSE"
    assert gate["official_weight_mutation_allowed"] == "FALSE"
    assert_safety([gate, *packet, *guardrail[:3], *summary])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "Final release packet releases DATA_TRUST only as zero-weight gate-only audit metadata" in report


if __name__ == "__main__":
    test_daily_runner_final_gate_only_release_packet()
    print("PASS test_v20_185_daily_runner_final_gate_only_release_packet")
