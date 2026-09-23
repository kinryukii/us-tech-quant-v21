#!/usr/bin/env python
"""Tests for V20.191 daily runner regression with DATA_TRUST gate-only metadata."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_191_daily_runner_regression_with_data_trust_gate_only.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_191_DAILY_RUNNER_REGRESSION_AUDIT.csv",
    FACTORS / "V20_191_CANDIDATE_UNIVERSE_REGRESSION_AUDIT.csv",
    FACTORS / "V20_191_RANKING_WEIGHT_REGRESSION_AUDIT.csv",
    FACTORS / "V20_191_READ_CENTER_REGRESSION_AUDIT.csv",
    FACTORS / "V20_191_OFFICIAL_USE_REGRESSION_AUDIT.csv",
    FACTORS / "V20_191_DOWNSTREAM_COMPATIBILITY_REGRESSION_AUDIT.csv",
    FACTORS / "V20_191_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_191_DAILY_RUNNER_REGRESSION_WITH_DATA_TRUST_GATE_ONLY_REPORT.md",
]
PROTECTED = [
    CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    FACTORS / "V20_174_DATA_TRUST_DAILY_RUNNER_OUTPUT_SAMPLE.csv",
    FACTORS / "V20_183_DATA_TRUST_READ_CENTER_DISPLAY_SAMPLE.csv",
    FACTORS / "V20_188_DATA_TRUST_GATE_ONLY_RELEASE_SEAL.csv",
    FACTORS / "V20_188_NEXT_STAGE_GATE.csv",
    FACTORS / "V20_189_DATA_TRUST_CURRENT_CHAIN_HANDOFF_AUDIT.csv",
    FACTORS / "V20_189_DATA_TRUST_CURRENT_CHAIN_COMPATIBILITY_AUDIT.csv",
    FACTORS / "V20_189_OFFICIAL_USE_GUARD_AUDIT.csv",
    FACTORS / "V20_189_NEXT_STAGE_GATE.csv",
    FACTORS / "V20_190_CURRENT_CHAIN_SMOKE_TEST_AUDIT.csv",
    FACTORS / "V20_190_DATA_TRUST_CURRENT_CHAIN_COMPATIBILITY_AUDIT.csv",
    FACTORS / "V20_190_RANKING_WEIGHT_MUTATION_GUARD_AUDIT.csv",
    FACTORS / "V20_190_OFFICIAL_USE_GUARD_AUDIT.csv",
    FACTORS / "V20_190_READ_CENTER_DISPLAY_AUDIT.csv",
    FACTORS / "V20_190_NEXT_STAGE_GATE.csv",
]
PASS_STATUS = "PASS_V20_191_DAILY_RUNNER_REGRESSION_WITH_DATA_TRUST_GATE_ONLY_READY_FOR_V20_192_RELEASE_CANDIDATE"
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


def assert_all_pass(rows: list[dict[str, str]]) -> None:
    assert all(row["regression_passed"] == "TRUE" for row in rows)


def test_daily_runner_regression_with_data_trust_gate_only() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected artifacts were mutated"
    stdout = result.stdout
    for expected in [
        PASS_STATUS,
        "BASELINE_CANDIDATE_COUNT=40",
        "DAILY_RUNNER_CANDIDATE_COUNT=40",
        "READ_CENTER_DISPLAY_CANDIDATE_COUNT=40",
        "CANDIDATE_REMOVED_OR_REORDERED_COUNT=0",
        "OFFICIAL_RANKING_SCORE_MUTATION_COUNT=0",
        "OFFICIAL_RANK_MUTATION_COUNT=0",
        "DATA_TRUST_SCORE_CONTRIBUTION_SUM=0.0000000000",
        "DATA_TRUST_NONZERO_WEIGHT_COUNT=0",
        "DAILY_RUNNER_REGRESSION_PASS=TRUE",
        "CANDIDATE_UNIVERSE_REGRESSION_PASS=TRUE",
        "RANKING_REGRESSION_PASS=TRUE",
        "ZERO_WEIGHT_REGRESSION_PASS=TRUE",
        "READ_CENTER_REGRESSION_PASS=TRUE",
        "OFFICIAL_USE_REGRESSION_PASS=TRUE",
        "DOWNSTREAM_COMPATIBILITY_REGRESSION_PASS=TRUE",
        "READY_FOR_V20_192_DAILY_RUNNER_CURRENT_CHAIN_RELEASE_CANDIDATE=TRUE",
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

    regression = read_csv(OUTPUTS[0])
    universe = read_csv(OUTPUTS[1])
    ranking = read_csv(OUTPUTS[2])
    read_center = read_csv(OUTPUTS[3])
    official = read_csv(OUTPUTS[4])
    downstream = read_csv(OUTPUTS[5])
    gate = read_csv(OUTPUTS[6])[0]
    for rows in [regression, universe, ranking, read_center, official, downstream]:
        assert_all_pass(rows)
    assert gate["final_status"] == PASS_STATUS
    assert gate["daily_runner_regression_pass"] == "TRUE"
    assert gate["candidate_universe_regression_pass"] == "TRUE"
    assert gate["ranking_regression_pass"] == "TRUE"
    assert gate["zero_weight_regression_pass"] == "TRUE"
    assert gate["read_center_regression_pass"] == "TRUE"
    assert gate["official_use_regression_pass"] == "TRUE"
    assert gate["downstream_compatibility_regression_pass"] == "TRUE"
    assert gate["ready_for_v20_192_daily_runner_current_chain_release_candidate"] == "TRUE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert gate["real_book_use_allowed"] == "FALSE"
    assert gate["official_recommendation_created"] == "FALSE"
    assert gate["official_weight_mutation_allowed"] == "FALSE"
    assert_safety([gate, *regression, *universe, *ranking[:2], *official])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "Daily runner regression confirms DATA_TRUST remains zero-weight gate-only audit metadata" in report


if __name__ == "__main__":
    test_daily_runner_regression_with_data_trust_gate_only()
    print("PASS test_v20_191_daily_runner_regression_with_data_trust_gate_only")
