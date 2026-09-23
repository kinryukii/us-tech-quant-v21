#!/usr/bin/env python
"""Tests for V20.175 DATA_TRUST daily runner shadow observation."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_175_data_trust_daily_runner_shadow_observation.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_175_DATA_TRUST_DAILY_RUNNER_SHADOW_OBSERVATION.csv",
    FACTORS / "V20_175_DATA_TRUST_DISCLOSURE_STABILITY_AUDIT.csv",
    FACTORS / "V20_175_DATA_TRUST_ZERO_WEIGHT_NO_MUTATION_AUDIT.csv",
    FACTORS / "V20_175_OFFICIAL_USE_GUARD_AUDIT.csv",
    FACTORS / "V20_175_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_175_DATA_TRUST_DAILY_RUNNER_SHADOW_OBSERVATION_REPORT.md",
]
PROTECTED = [
    CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv",
    FACTORS / "V20_174_DATA_TRUST_DAILY_RUNNER_OUTPUT_SAMPLE.csv",
    FACTORS / "V20_174_NEXT_STAGE_GATE.csv",
]
PASS_STATUS = "PASS_V20_175_DATA_TRUST_DAILY_RUNNER_SHADOW_OBSERVATION_READY_FOR_V20_176"

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


def test_data_trust_daily_runner_shadow_observation() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected artifacts were mutated"
    stdout = result.stdout
    for expected in [
        PASS_STATUS,
        "BASELINE_CANDIDATE_COUNT=40",
        "SHADOW_OBSERVATION_CANDIDATE_COUNT=40",
        "DATA_TRUST_DISCLOSURE_CANDIDATE_COUNT=40",
        "OFFICIAL_RANKING_SCORE_MUTATION_COUNT=0",
        "OFFICIAL_RANK_MUTATION_COUNT=0",
        "DATA_TRUST_SCORE_CONTRIBUTION_SUM=0.0000000000",
        "DATA_TRUST_NONZERO_WEIGHT_COUNT=0",
        "CANDIDATE_REMOVED_OR_REORDERED_COUNT=0",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "REAL_BOOK_USE_ALLOWED=FALSE",
        "OFFICIAL_WEIGHT_MUTATION_ALLOWED=FALSE",
        "DISCLOSURE_STABILITY_PASS=TRUE",
        "NO_MUTATION_GUARD_PASS=TRUE",
        "ZERO_WEIGHT_GUARD_PASS=TRUE",
        "OFFICIAL_USE_GUARD_PASS=TRUE",
        "READY_FOR_V20_176_DATA_TRUST_SHADOW_OBSERVATION_SUMMARY=TRUE",
        "READY_FOR_OFFICIAL_USE=FALSE",
        "OFFICIAL_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    observation = read_csv(OUTPUTS[0])
    disclosure = read_csv(OUTPUTS[1])
    zero = read_csv(OUTPUTS[2])
    official = read_csv(OUTPUTS[3])
    gate = read_csv(OUTPUTS[4])[0]
    assert len(observation) == 1
    assert len(disclosure) == 40
    assert all(row["disclosure_stability_pass"] == "TRUE" for row in disclosure)
    assert all(row["data_trust_weight"] == "0.0000000000" for row in disclosure)
    assert all(row["data_trust_official_score_contribution"] == "0.0000000000" for row in disclosure)
    assert all(row["guard_passed"] == "TRUE" for row in zero + official)
    assert gate["final_status"] == PASS_STATUS
    assert gate["ready_for_v20_176_data_trust_shadow_observation_summary"] == "TRUE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert_safety([gate, *observation, *disclosure[:3]])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "zero-weight gate-only audit metadata" in report


if __name__ == "__main__":
    test_data_trust_daily_runner_shadow_observation()
    print("PASS test_v20_175_data_trust_daily_runner_shadow_observation")
