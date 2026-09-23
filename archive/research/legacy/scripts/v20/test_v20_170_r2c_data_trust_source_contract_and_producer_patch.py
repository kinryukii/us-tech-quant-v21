#!/usr/bin/env python
"""Tests for V20.170-R2C DATA_TRUST source contract and producer patch."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_170_r2c_data_trust_source_contract_and_producer_patch.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_170_R2C_SOURCE_CONTRACT_PATCH_AUDIT.csv",
    FACTORS / "V20_170_R2C_PRODUCER_PATCH_AUDIT.csv",
    FACTORS / "V20_170_R2C_NEW_SOURCE_CONTRACT_AUDIT.csv",
    FACTORS / "V20_170_R2C_REMAINING_GAP_AUDIT.csv",
    FACTORS / "V20_170_R2C_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_170_R2C_DATA_TRUST_SOURCE_CONTRACT_AND_PRODUCER_PATCH_REPORT.md",
]
PROTECTED = [
    CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv",
    CONSOLIDATION / "V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv",
    FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_SUMMARY.csv",
    FACTORS / "V20_170_R2B_REMAINING_SOURCE_CONTRACT_GAPS.csv",
    FACTORS / "V20_170_R2B_SAFE_DERIVATION_NEXT_GATE.csv",
]
PASS_STATUS = "PASS_V20_170_R2C_SOURCE_CONTRACT_AND_PRODUCER_PATCH_READY_FOR_V20_170_R3"

SOURCE_COLUMNS = {
    "required_field", "gap_classification_before_r2c", "source_contract_patch_applied",
    "producer_patch_applied", "new_source_contract_added", "source_contract_definition",
    "source_contract_value_policy", "affected_ticker_count", "affected_factor_family_count",
    "affected_lineage_row_count", "missing_or_unknown_count_before_r2c",
    "source_contract_required_count_before_r2c", "missing_or_unknown_count_after_r2c",
    "source_contract_required_count_after_r2c", "accepted_for_direct_pass",
    "direct_status_retest_required", "fabricated_values_created", "limitation_reason",
}
PRODUCER_COLUMNS = {
    "required_field", "producer_script", "producer_exists", "producer_patch_required",
    "producer_patch_applied", "output_artifact", "output_field", "output_artifact_exists",
    "expected_row_grain", "expected_join_keys", "affected_ticker_count",
    "affected_factor_family_count", "affected_lineage_row_count", "population_mode",
    "unknown_allowed_until_direct_evidence", "fabricated_values_created",
    "direct_status_retest_required", "patch_status", "limitation_reason",
}
NEW_COLUMNS = {
    "required_field", "source_contract_owner_stage", "source_contract_artifact",
    "source_contract_field", "new_source_contract_required", "new_source_contract_added",
    "required_policy_or_evidence", "contract_definition", "contract_acceptance_rule",
    "affected_ticker_count", "affected_lineage_row_count", "fabricated_pit_safety_created",
    "accepted_for_direct_pass", "direct_status_retest_required", "patch_status",
    "limitation_reason",
}
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


def test_data_trust_source_contract_and_producer_patch() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected artifacts were mutated"
    stdout = result.stdout
    for expected in [
        PASS_STATUS,
        "BASELINE_CANDIDATE_COUNT=40",
        "REMAINING_GAP_FIELD_COUNT_BEFORE_R2C=8",
        "PRODUCER_PATCH_REQUIRED_COUNT_BEFORE_R2C=6",
        "PRODUCER_PATCH_APPLIED_COUNT=6",
        "NEW_SOURCE_CONTRACT_REQUIRED_COUNT_BEFORE_R2C=2",
        "NEW_SOURCE_CONTRACT_ADDED_COUNT=2",
        "SOURCE_CONTRACT_PATCH_APPLIED_COUNT=8",
        "REMAINING_GAP_FIELD_COUNT_AFTER_R2C=0",
        "REMAINING_SOURCE_CONTRACT_REQUIRED_COUNT_AFTER_R2C=0",
        "DIRECT_PASS_CANDIDATE_COUNT_AFTER_R2C=0",
        "DIRECT_UNKNOWN_CANDIDATE_COUNT_AFTER_R2C=40",
        "READY_FOR_V20_170_R3_DIRECT_STATUS_RETEST=TRUE",
        "READY_FOR_V20_171_GATE_ONLY_RANKING_SIMULATION=FALSE",
        "READY_FOR_OFFICIAL_USE=FALSE",
        "OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE",
        "OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE",
        "RANKING_SIMULATION_CREATED=FALSE",
        "NO_DATA_TRUST_STATUS_FABRICATED=TRUE",
        "NO_PIT_STATUS_FABRICATED=TRUE",
        "OFFICIAL_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    source = read_csv(OUTPUTS[0])
    producer = read_csv(OUTPUTS[1])
    new = read_csv(OUTPUTS[2])
    remaining = read_csv(OUTPUTS[3])
    gate = read_csv(OUTPUTS[4])[0]
    assert SOURCE_COLUMNS.issubset(source[0].keys())
    assert PRODUCER_COLUMNS.issubset(producer[0].keys())
    assert NEW_COLUMNS.issubset(new[0].keys())
    assert len(source) == 8
    assert len(producer) == 6
    assert len(new) == 2
    assert len(remaining) == 8
    assert gate["final_status"] == PASS_STATUS
    assert gate["ready_for_v20_170_r3_direct_status_retest"] == "TRUE"
    assert gate["ready_for_v20_171_gate_only_ranking_simulation"] == "FALSE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert all(row["source_contract_patch_applied"] == "TRUE" for row in source)
    assert all(row["fabricated_values_created"] == "FALSE" for row in source)
    assert all(row["producer_patch_applied"] == "TRUE" for row in producer)
    assert all(row["new_source_contract_added"] == "TRUE" for row in new)
    assert all(row["fabricated_pit_safety_created"] == "FALSE" for row in new)
    assert all(row["gap_classification_after_r2c"] == "PATCHED_PENDING_R3_DIRECT_STATUS_RETEST" for row in remaining)
    assert all(row["ready_for_v20_171_gate_only_ranking_simulation"] == "FALSE" for row in remaining)
    assert_safety([gate, *source[:3], *producer[:3], *new])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "does not fabricate ticker rows" in report


if __name__ == "__main__":
    test_data_trust_source_contract_and_producer_patch()
    print("PASS test_v20_170_r2c_data_trust_source_contract_and_producer_patch")
