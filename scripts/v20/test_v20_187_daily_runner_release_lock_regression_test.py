#!/usr/bin/env python
"""Tests for V20.187 DATA_TRUST daily runner release lock regression test."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_187_daily_runner_release_lock_regression_test.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_187_DATA_TRUST_RELEASE_LOCK_REGRESSION_AUDIT.csv",
    FACTORS / "V20_187_DATA_TRUST_FORBIDDEN_USE_REGRESSION_AUDIT.csv",
    FACTORS / "V20_187_DATA_TRUST_MUTATION_GUARD_REGRESSION_AUDIT.csv",
    FACTORS / "V20_187_DATA_TRUST_DOWNSTREAM_COMPATIBILITY_AUDIT.csv",
    FACTORS / "V20_187_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_187_DAILY_RUNNER_RELEASE_LOCK_REGRESSION_TEST_REPORT.md",
]
PROTECTED = [
    CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv",
    FACTORS / "V20_174_DATA_TRUST_DAILY_RUNNER_OUTPUT_SAMPLE.csv",
    FACTORS / "V20_183_DATA_TRUST_READ_CENTER_DISPLAY_SAMPLE.csv",
    FACTORS / "V20_186_DATA_TRUST_GATE_ONLY_RELEASE_LOCK.csv",
    FACTORS / "V20_186_DATA_TRUST_FORBIDDEN_USE_AUDIT.csv",
    FACTORS / "V20_186_DATA_TRUST_MUTATION_GUARD_LOCK_AUDIT.csv",
    FACTORS / "V20_186_NEXT_STAGE_GATE.csv",
]
PASS_STATUS = "PASS_V20_187_DAILY_RUNNER_RELEASE_LOCK_REGRESSION_TEST_READY_FOR_V20_188_RELEASE_SEAL"
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


def test_daily_runner_release_lock_regression_test() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected artifacts were mutated"
    stdout = result.stdout
    for expected in [
        PASS_STATUS,
        "RELEASE_LOCK_REGRESSION_PASS=TRUE",
        "FORBIDDEN_USE_REGRESSION_PASS=TRUE",
        "RANKING_MUTATION_REGRESSION_PASS=TRUE",
        "ZERO_WEIGHT_REGRESSION_PASS=TRUE",
        "OFFICIAL_USE_REGRESSION_PASS=TRUE",
        "DOWNSTREAM_COMPATIBILITY_PASS=TRUE",
        "OFFICIAL_RANKING_SCORE_MUTATION_COUNT=0",
        "OFFICIAL_RANK_MUTATION_COUNT=0",
        "DATA_TRUST_SCORE_CONTRIBUTION_SUM=0.0000000000",
        "DATA_TRUST_NONZERO_WEIGHT_COUNT=0",
        "READY_FOR_V20_188_DAILY_RUNNER_GATE_ONLY_RELEASE_SEAL=TRUE",
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

    regression = read_csv(OUTPUTS[0])
    forbidden = read_csv(OUTPUTS[1])
    mutation = read_csv(OUTPUTS[2])
    compatibility = read_csv(OUTPUTS[3])
    gate = read_csv(OUTPUTS[4])[0]
    assert all(row["regression_passed"] == "TRUE" for row in regression)
    assert {row["surface"] for row in regression} == {
        "daily_runner_output",
        "ranking_score_calculation",
        "ranking_order",
        "read_center_display",
        "official_recommendation_gate",
        "real_book_gate",
        "weight_configuration_contribution_audit",
    }
    assert all(row["forbidden_use_regression_passed"] == "TRUE" for row in forbidden)
    assert all(row["mutation_guard_regression_passed"] == "TRUE" for row in mutation)
    assert all(row["downstream_compatibility_passed"] == "TRUE" for row in compatibility)
    assert gate["final_status"] == PASS_STATUS
    assert gate["release_lock_regression_pass"] == "TRUE"
    assert gate["forbidden_use_regression_pass"] == "TRUE"
    assert gate["ranking_mutation_regression_pass"] == "TRUE"
    assert gate["zero_weight_regression_pass"] == "TRUE"
    assert gate["official_use_regression_pass"] == "TRUE"
    assert gate["ready_for_v20_188_daily_runner_gate_only_release_seal"] == "TRUE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert gate["real_book_use_allowed"] == "FALSE"
    assert gate["official_recommendation_created"] == "FALSE"
    assert gate["official_weight_mutation_allowed"] == "FALSE"
    assert_safety([gate, *regression[:3], *forbidden, *mutation[:3], *compatibility[:3]])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "Regression confirms DATA_TRUST remains zero-weight gate-only audit metadata" in report


if __name__ == "__main__":
    test_daily_runner_release_lock_regression_test()
    print("PASS test_v20_187_daily_runner_release_lock_regression_test")
