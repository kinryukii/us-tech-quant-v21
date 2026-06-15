#!/usr/bin/env python
"""Tests for V20.186 DATA_TRUST daily runner gate-only release lock."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_186_daily_runner_gate_only_release_lock.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_186_DATA_TRUST_GATE_ONLY_RELEASE_LOCK.csv",
    FACTORS / "V20_186_DATA_TRUST_FORBIDDEN_USE_AUDIT.csv",
    FACTORS / "V20_186_DATA_TRUST_MUTATION_GUARD_LOCK_AUDIT.csv",
    FACTORS / "V20_186_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_186_DAILY_RUNNER_GATE_ONLY_RELEASE_LOCK_REPORT.md",
]
PROTECTED = [
    FACTORS / "V20_185_DATA_TRUST_FINAL_GATE_ONLY_RELEASE_PACKET.csv",
    FACTORS / "V20_185_DATA_TRUST_FINAL_RELEASE_GUARDRAIL_AUDIT.csv",
    FACTORS / "V20_185_OPERATOR_FACING_RELEASE_SUMMARY.csv",
    FACTORS / "V20_185_NEXT_STAGE_GATE.csv",
]
PASS_STATUS = "PASS_V20_186_DAILY_RUNNER_GATE_ONLY_RELEASE_LOCK_READY_FOR_V20_187_REGRESSION_TEST"
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


def test_daily_runner_gate_only_release_lock() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected artifacts were mutated"
    stdout = result.stdout
    for expected in [
        PASS_STATUS,
        "DATA_TRUST_RELEASE_LOCK_CREATED=TRUE",
        "FORBIDDEN_USE_GUARD_PASS=TRUE",
        "MUTATION_GUARD_LOCK_PASS=TRUE",
        "LOCKED_ZERO_WEIGHT=TRUE",
        "LOCKED_GATE_ONLY=TRUE",
        "LOCKED_AUDIT_ONLY=TRUE",
        "LOCKED_READ_CENTER_DISCLOSED=TRUE",
        "LOCKED_SHADOW_OBSERVATION_CONTINUED=TRUE",
        "OFFICIAL_SCORING_FACTOR_FORBIDDEN=TRUE",
        "OFFICIAL_RANKING_WEIGHT_FORBIDDEN=TRUE",
        "OFFICIAL_RECOMMENDATION_TRIGGER_FORBIDDEN=TRUE",
        "REAL_BOOK_PERMISSION_GATE_FORBIDDEN=TRUE",
        "READY_FOR_V20_187_DAILY_RUNNER_RELEASE_LOCK_REGRESSION_TEST=TRUE",
        "READY_FOR_OFFICIAL_USE=FALSE",
        "REAL_BOOK_USE_ALLOWED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "OFFICIAL_WEIGHT_MUTATION_ALLOWED=FALSE",
        "DATA_TRUST_ZERO_WEIGHT=TRUE",
        "DATA_TRUST_GATE_ONLY=TRUE",
        "DATA_TRUST_AUDIT_ONLY=TRUE",
        "OFFICIAL_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    lock = read_csv(OUTPUTS[0])
    forbidden = read_csv(OUTPUTS[1])
    mutation = read_csv(OUTPUTS[2])
    gate = read_csv(OUTPUTS[3])[0]
    assert len(lock) == 1
    lock_row = lock[0]
    assert lock_row["release_lock_created"] == "TRUE"
    assert lock_row["locked_zero_weight"] == "TRUE"
    assert lock_row["locked_gate_only"] == "TRUE"
    assert lock_row["locked_audit_only"] == "TRUE"
    assert lock_row["locked_read_center_disclosed"] == "TRUE"
    assert lock_row["locked_shadow_observation_continued"] == "TRUE"
    assert lock_row["official_scoring_factor_forbidden"] == "TRUE"
    assert lock_row["official_ranking_weight_forbidden"] == "TRUE"
    assert lock_row["official_recommendation_trigger_forbidden"] == "TRUE"
    assert lock_row["real_book_permission_gate_forbidden"] == "TRUE"
    assert all(row["forbidden_use_guard_passed"] == "TRUE" for row in forbidden)
    assert {row["forbidden_use"] for row in forbidden} == {
        "official_scoring_factor",
        "official_ranking_weight",
        "official_recommendation_trigger",
        "real_book_permission_gate",
    }
    assert all(row["mutation_guard_locked"] == "TRUE" for row in mutation)
    assert {row["mutation_guard"] for row in mutation} >= {
        "official_ranking_score_mutation",
        "official_rank_mutation",
        "nonzero_data_trust_score_contribution",
        "nonzero_data_trust_weight",
        "official_recommendation_creation",
        "real_book_use_enablement",
        "official_weight_mutation",
    }
    assert gate["final_status"] == PASS_STATUS
    assert gate["data_trust_release_lock_created"] == "TRUE"
    assert gate["forbidden_use_guard_pass"] == "TRUE"
    assert gate["mutation_guard_lock_pass"] == "TRUE"
    assert gate["ready_for_v20_187_daily_runner_release_lock_regression_test"] == "TRUE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert gate["real_book_use_allowed"] == "FALSE"
    assert gate["official_recommendation_created"] == "FALSE"
    assert gate["official_weight_mutation_allowed"] == "FALSE"
    assert_safety([gate, *lock, *forbidden, *mutation[:3]])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "DATA_TRUST daily runner release is locked as zero-weight gate-only audit metadata" in report


if __name__ == "__main__":
    test_daily_runner_gate_only_release_lock()
    print("PASS test_v20_186_daily_runner_gate_only_release_lock")
