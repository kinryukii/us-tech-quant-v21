#!/usr/bin/env python
"""Tests for V20.176 DATA_TRUST shadow observation summary."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_176_data_trust_shadow_observation_summary.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_176_DATA_TRUST_CHAIN_SUMMARY.csv",
    FACTORS / "V20_176_DATA_TRUST_STAGE_BY_STAGE_SUMMARY.csv",
    FACTORS / "V20_176_DATA_TRUST_FINAL_GUARDRAIL_SUMMARY.csv",
    FACTORS / "V20_176_DATA_TRUST_DAILY_RUNNER_READINESS_SUMMARY.csv",
    FACTORS / "V20_176_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_176_DATA_TRUST_SHADOW_OBSERVATION_SUMMARY_REPORT.md",
]
PROTECTED = [
    CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv",
    FACTORS / "V20_175_NEXT_STAGE_GATE.csv",
]
PASS_STATUS = "PASS_V20_176_DATA_TRUST_SHADOW_OBSERVATION_SUMMARY_READY_FOR_V20_177"

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


def test_data_trust_shadow_observation_summary() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected artifacts were mutated"
    stdout = result.stdout
    for expected in [
        PASS_STATUS,
        "BASELINE_CANDIDATE_COUNT=40",
        "DIRECT_PASS_CANDIDATE_COUNT=40",
        "DATA_TRUST_CHAIN_SUMMARY_PASS=TRUE",
        "DATA_TRUST_FINAL_GUARDRAIL_PASS=TRUE",
        "DATA_TRUST_DAILY_RUNNER_SHADOW_OBSERVATION_PASS=TRUE",
        "READY_FOR_V20_177_DATA_TRUST_DAILY_RUNNER_CLOSEOUT_OR_MULTIDAY_OBSERVATION=TRUE",
        "READY_FOR_OFFICIAL_USE=FALSE",
        "REAL_BOOK_USE_ALLOWED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "OFFICIAL_WEIGHT_MUTATION_ALLOWED=FALSE",
        "DATA_TRUST_ZERO_WEIGHT=TRUE",
        "DATA_TRUST_GATE_ONLY=TRUE",
        "DATA_TRUST_AUDIT_ONLY=TRUE",
        "DATA_TRUST_SHADOW_OBSERVATION_CONTINUED=TRUE",
        "OFFICIAL_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    chain = read_csv(OUTPUTS[0])
    stages = read_csv(OUTPUTS[1])
    guards = read_csv(OUTPUTS[2])
    daily = read_csv(OUTPUTS[3])
    gate = read_csv(OUTPUTS[4])[0]
    assert len(chain) == 1
    assert len(stages) == 6
    assert len(guards) == 11
    assert len(daily) == 1
    assert chain[0]["chain_summary_pass"] == "TRUE"
    assert all(row["stage_passed"] == "TRUE" for row in stages)
    assert all(row["guardrail_passed"] == "TRUE" for row in guards)
    assert daily[0]["ready_for_multiday_observation_or_closeout"] == "TRUE"
    assert gate["final_status"] == PASS_STATUS
    assert gate["ready_for_v20_177_data_trust_daily_runner_closeout_or_multiday_observation"] == "TRUE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert_safety([gate, *chain, *stages[:3], *guards[:3], *daily])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "zero-weight, gate-only, audit-only" in report


if __name__ == "__main__":
    test_data_trust_shadow_observation_summary()
    print("PASS test_v20_176_data_trust_shadow_observation_summary")
