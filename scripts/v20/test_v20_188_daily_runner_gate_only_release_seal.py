#!/usr/bin/env python
"""Tests for V20.188 DATA_TRUST daily runner gate-only release seal."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_188_daily_runner_gate_only_release_seal.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_188_DATA_TRUST_GATE_ONLY_RELEASE_SEAL.csv",
    FACTORS / "V20_188_DATA_TRUST_FINAL_SEAL_GUARDRAIL_AUDIT.csv",
    FACTORS / "V20_188_DATA_TRUST_FINAL_FORBIDDEN_USE_SEAL_AUDIT.csv",
    FACTORS / "V20_188_OPERATOR_FACING_SEAL_SUMMARY.csv",
    FACTORS / "V20_188_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_188_DAILY_RUNNER_GATE_ONLY_RELEASE_SEAL_REPORT.md",
]
PROTECTED = [
    FACTORS / "V20_185_DATA_TRUST_FINAL_GATE_ONLY_RELEASE_PACKET.csv",
    FACTORS / "V20_185_DATA_TRUST_FINAL_RELEASE_GUARDRAIL_AUDIT.csv",
    FACTORS / "V20_185_NEXT_STAGE_GATE.csv",
    FACTORS / "V20_186_DATA_TRUST_GATE_ONLY_RELEASE_LOCK.csv",
    FACTORS / "V20_186_DATA_TRUST_FORBIDDEN_USE_AUDIT.csv",
    FACTORS / "V20_186_DATA_TRUST_MUTATION_GUARD_LOCK_AUDIT.csv",
    FACTORS / "V20_186_NEXT_STAGE_GATE.csv",
    FACTORS / "V20_187_DATA_TRUST_RELEASE_LOCK_REGRESSION_AUDIT.csv",
    FACTORS / "V20_187_DATA_TRUST_FORBIDDEN_USE_REGRESSION_AUDIT.csv",
    FACTORS / "V20_187_DATA_TRUST_MUTATION_GUARD_REGRESSION_AUDIT.csv",
    FACTORS / "V20_187_DATA_TRUST_DOWNSTREAM_COMPATIBILITY_AUDIT.csv",
    FACTORS / "V20_187_NEXT_STAGE_GATE.csv",
]
PASS_STATUS = "PASS_V20_188_DAILY_RUNNER_GATE_ONLY_RELEASE_SEAL_READY_FOR_V20_189_CURRENT_CHAIN_HANDOFF"
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


def test_daily_runner_gate_only_release_seal() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected artifacts were mutated"
    stdout = result.stdout
    for expected in [
        PASS_STATUS,
        "DATA_TRUST_GATE_ONLY_RELEASE_SEALED=TRUE",
        "FINAL_SEAL_GUARDRAIL_PASS=TRUE",
        "FINAL_FORBIDDEN_USE_SEAL_PASS=TRUE",
        "OFFICIAL_RANKING_SCORE_MUTATION_COUNT=0",
        "OFFICIAL_RANK_MUTATION_COUNT=0",
        "DATA_TRUST_SCORE_CONTRIBUTION_SUM=0.0000000000",
        "DATA_TRUST_NONZERO_WEIGHT_COUNT=0",
        "READY_FOR_V20_189_DAILY_RUNNER_SEAL_HANDOFF_TO_CURRENT_CHAIN=TRUE",
        "READY_FOR_OFFICIAL_USE=FALSE",
        "REAL_BOOK_USE_ALLOWED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "OFFICIAL_WEIGHT_MUTATION_ALLOWED=FALSE",
        "DATA_TRUST_ZERO_WEIGHT=TRUE",
        "DATA_TRUST_GATE_ONLY=TRUE",
        "DATA_TRUST_AUDIT_ONLY=TRUE",
        "DATA_TRUST_READ_CENTER_DISCLOSED=TRUE",
        "DATA_TRUST_DAILY_RUNNER_COMPATIBLE=TRUE",
        "DATA_TRUST_SHADOW_OBSERVATION_CONTINUED=TRUE",
        "OFFICIAL_SCORING_FACTOR_FORBIDDEN=TRUE",
        "OFFICIAL_RANKING_WEIGHT_FORBIDDEN=TRUE",
        "OFFICIAL_RECOMMENDATION_TRIGGER_FORBIDDEN=TRUE",
        "REAL_BOOK_PERMISSION_GATE_FORBIDDEN=TRUE",
        "OFFICIAL_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    seal = read_csv(OUTPUTS[0])
    guardrail = read_csv(OUTPUTS[1])
    forbidden = read_csv(OUTPUTS[2])
    summary = read_csv(OUTPUTS[3])
    gate = read_csv(OUTPUTS[4])[0]
    assert len(seal) == 1
    row = seal[0]
    assert row["release_seal_created"] == "TRUE"
    assert row["sealed_zero_weight"] == "TRUE"
    assert row["sealed_gate_only"] == "TRUE"
    assert row["sealed_audit_only"] == "TRUE"
    assert row["sealed_read_center_disclosed"] == "TRUE"
    assert row["sealed_daily_runner_compatible"] == "TRUE"
    assert row["sealed_shadow_observation_continued"] == "TRUE"
    assert row["official_scoring_factor_forbidden"] == "TRUE"
    assert row["official_ranking_weight_forbidden"] == "TRUE"
    assert row["official_recommendation_trigger_forbidden"] == "TRUE"
    assert row["real_book_permission_gate_forbidden"] == "TRUE"
    assert row["official_ranking_score_mutation_count"] == "0"
    assert row["official_rank_mutation_count"] == "0"
    assert row["data_trust_score_contribution_sum"] == "0.0000000000"
    assert row["data_trust_nonzero_weight_count"] == "0"
    assert all(item["final_seal_guardrail_passed"] == "TRUE" for item in guardrail)
    assert all(item["final_forbidden_use_seal_passed"] == "TRUE" for item in forbidden)
    assert len(summary) == 1
    assert summary[0]["data_trust_gate_only_release_sealed"] == "TRUE"
    assert summary[0]["final_seal_guardrail_pass"] == "TRUE"
    assert summary[0]["final_forbidden_use_seal_pass"] == "TRUE"
    assert summary[0]["ready_for_v20_189_daily_runner_seal_handoff_to_current_chain"] == "TRUE"
    assert gate["final_status"] == PASS_STATUS
    assert gate["data_trust_gate_only_release_sealed"] == "TRUE"
    assert gate["final_seal_guardrail_pass"] == "TRUE"
    assert gate["final_forbidden_use_seal_pass"] == "TRUE"
    assert gate["ready_for_v20_189_daily_runner_seal_handoff_to_current_chain"] == "TRUE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert gate["real_book_use_allowed"] == "FALSE"
    assert gate["official_recommendation_created"] == "FALSE"
    assert gate["official_weight_mutation_allowed"] == "FALSE"
    assert_safety([gate, *seal, *guardrail[:3], *forbidden, *summary])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "Final seal confirms DATA_TRUST remains zero-weight" in report


if __name__ == "__main__":
    test_daily_runner_gate_only_release_seal()
    print("PASS test_v20_188_daily_runner_gate_only_release_seal")
