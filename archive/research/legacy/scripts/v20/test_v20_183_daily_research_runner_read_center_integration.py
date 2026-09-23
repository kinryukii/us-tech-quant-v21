#!/usr/bin/env python
"""Tests for V20.183 daily research runner read-center integration."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_183_daily_research_runner_read_center_integration.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_183_DATA_TRUST_READ_CENTER_INTEGRATION_AUDIT.csv",
    FACTORS / "V20_183_DATA_TRUST_READ_CENTER_DISPLAY_SAMPLE.csv",
    FACTORS / "V20_183_OFFICIAL_USE_GUARD_AUDIT.csv",
    FACTORS / "V20_183_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_183_DAILY_RESEARCH_RUNNER_READ_CENTER_INTEGRATION_REPORT.md",
]
PROTECTED = [
    CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv",
    FACTORS / "V20_174_DATA_TRUST_DAILY_RUNNER_OUTPUT_SAMPLE.csv",
    FACTORS / "V20_182_DATA_TRUST_FINAL_OPERATOR_DECISION_PACKET.csv",
    FACTORS / "V20_182_DATA_TRUST_FINAL_EVIDENCE_SUMMARY.csv",
    FACTORS / "V20_182_DATA_TRUST_FINAL_GUARDRAIL_AUDIT.csv",
    FACTORS / "V20_182_DATA_TRUST_DAILY_RUNNER_INTEGRATION_STATUS.csv",
    FACTORS / "V20_182_NEXT_STAGE_GATE.csv",
]
PASS_STATUS = "PASS_V20_183_DAILY_RESEARCH_RUNNER_READ_CENTER_INTEGRATION_READY_FOR_V20_184_OPERATOR_READABILITY_REVIEW"
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


def test_daily_research_runner_read_center_integration() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected artifacts were mutated"
    stdout = result.stdout
    for expected in [
        PASS_STATUS,
        "READ_CENTER_DISPLAY_CANDIDATE_COUNT=40",
        "OFFICIAL_RANKING_SCORE_MUTATION_COUNT=0",
        "OFFICIAL_RANK_MUTATION_COUNT=0",
        "DATA_TRUST_SCORE_CONTRIBUTION_SUM=0.0000000000",
        "DATA_TRUST_NONZERO_WEIGHT_COUNT=0",
        "DATA_TRUST_READ_CENTER_INTEGRATION_PASS=TRUE",
        "DATA_TRUST_STATUS_DISCLOSURE_PASS=TRUE",
        "OFFICIAL_USE_GUARD_PASS=TRUE",
        "RANKING_MUTATION_GUARD_PASS=TRUE",
        "READY_FOR_V20_184_DAILY_RESEARCH_RUNNER_OPERATOR_READABILITY_REVIEW=TRUE",
        "READY_FOR_OFFICIAL_USE=FALSE",
        "REAL_BOOK_USE_ALLOWED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "OFFICIAL_WEIGHT_MUTATION_ALLOWED=FALSE",
        "DATA_TRUST_ZERO_WEIGHT=TRUE",
        "DATA_TRUST_GATE_ONLY=TRUE",
        "DATA_TRUST_AUDIT_ONLY=TRUE",
        "DATA_TRUST_DAILY_RUNNER_DISCLOSED=TRUE",
        "DATA_TRUST_SHADOW_OBSERVATION_CONTINUED=TRUE",
        "OFFICIAL_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    audit = read_csv(OUTPUTS[0])
    sample = read_csv(OUTPUTS[1])
    guard = read_csv(OUTPUTS[2])
    gate = read_csv(OUTPUTS[3])[0]

    assert len(sample) == 40
    assert all(row["integration_check_passed"] == "TRUE" for row in audit)
    assert all(row["guard_passed"] == "TRUE" for row in guard)
    assert all(row["data_trust_direct_status_summary"] == "PASS" for row in sample)
    assert all(row["data_trust_gate_only_status"] == "TRUE" for row in sample)
    assert all(row["data_trust_zero_weight_status"] == "TRUE" for row in sample)
    assert all(row["data_trust_audit_only_status"] == "TRUE" for row in sample)
    assert all(row["data_trust_shadow_observation_status"] == "TRUE" for row in sample)
    assert all(row["official_use_status"] == "DISABLED" for row in sample)
    assert all(row["real_book_use_status"] == "DISABLED" for row in sample)
    assert all(row["official_recommendation_status"] == "DISABLED" for row in sample)
    assert all(row["official_weight_mutation_status"] == "DISABLED" for row in sample)
    assert all(row["data_trust_score_contribution"] == "0.0000000000" for row in sample)
    assert all(row["data_trust_weight"] == "0.0000000000" for row in sample)
    assert gate["final_status"] == PASS_STATUS
    assert gate["data_trust_read_center_integration_pass"] == "TRUE"
    assert gate["data_trust_status_disclosure_pass"] == "TRUE"
    assert gate["official_use_guard_pass"] == "TRUE"
    assert gate["ranking_mutation_guard_pass"] == "TRUE"
    assert gate["ready_for_v20_184_daily_research_runner_operator_readability_review"] == "TRUE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert gate["real_book_use_allowed"] == "FALSE"
    assert gate["official_recommendation_created"] == "FALSE"
    assert gate["official_weight_mutation_allowed"] == "FALSE"
    assert_safety([gate, *audit[:3], *sample[:3], *guard[:3]])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "Read-center integration now displays DATA_TRUST" in report


if __name__ == "__main__":
    test_daily_research_runner_read_center_integration()
    print("PASS test_v20_183_daily_research_runner_read_center_integration")
