#!/usr/bin/env python
"""Tests for V20.170-R2B DATA_TRUST safe derivation patch."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_170_r2b_data_trust_safe_derivation_patch.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_170_R2B_SAFE_DERIVATION_PATCH_PLAN.csv",
    FACTORS / "V20_170_R2B_SAFE_DERIVATION_OUTPUT.csv",
    FACTORS / "V20_170_R2B_PATCHED_PIT_LINEAGE_DERIVED_FIELDS.csv",
    FACTORS / "V20_170_R2B_DERIVATION_VALIDATION_AUDIT.csv",
    FACTORS / "V20_170_R2B_REMAINING_SOURCE_CONTRACT_GAPS.csv",
    FACTORS / "V20_170_R2B_DIRECT_STATUS_RETEST_INPUT.csv",
    FACTORS / "V20_170_R2B_SAFE_DERIVATION_NEXT_GATE.csv",
    FACTORS / "V20_170_R2B_SAFE_DERIVATION_SAFETY_AUDIT.csv",
    READ_CENTER / "V20_170_R2B_DATA_TRUST_SAFE_DERIVATION_PATCH_REPORT.md",
]
PROTECTED = [
    CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv",
    CONSOLIDATION / "V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv",
    CONSOLIDATION / "V20_108_R10_PIT_LINEAGE_SCHEMA_EXTENSION_AUDIT.csv",
    CONSOLIDATION / "V20_108_R10_PIT_LINEAGE_SOURCE_CONTRACT_GAP_AUDIT.csv",
    FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_SUMMARY.csv",
    FACTORS / "V20_170_R2A_SAFE_DERIVATION_CANDIDATES.csv",
    FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_NEXT_GATE.csv",
]
PARTIAL_STATUS = "PARTIAL_PASS_V20_170_R2B_SAFE_DERIVATION_PATCH_READY_FOR_V20_170_R2C"

PLAN_COLUMNS = {
    "required_field", "derivation_source_artifact", "derivation_source_field",
    "derivation_rule", "derivation_safe", "derivation_applied",
    "affected_ticker_count", "affected_factor_family_count", "affected_lineage_row_count",
    "derived_non_null_count", "derived_unknown_count", "accepted_for_direct_evidence",
    "limitation_reason",
}
PATCHED_COLUMNS = {
    "ticker", "baseline_rank", "factor_family", "source_artifact", "source_row_id",
    "original_required_field", "original_field_value", "derived_field_value",
    "derivation_rule", "derivation_confidence", "safe_derivation_applied",
    "direct_evidence_after_derivation", "still_unknown_after_derivation",
    "source_contract_required_after_derivation",
    "accepted_for_data_trust_direct_pit_status_after_derivation", "rejection_reason",
}
VALIDATION_COLUMNS = {
    "ticker", "factor_family", "safe_derivation_field_count",
    "safe_derivation_applied_count", "safe_derivation_rejected_count",
    "remaining_unknown_required_field_count",
    "remaining_source_contract_required_field_count", "non_pit_blocker_present",
    "leakage_flag_present", "accepted_direct_pit_lineage_after_derivation",
    "direct_pass_blocker_reason", "ready_for_v20_170_r2c_source_contract_patch",
    "ready_for_v20_170_r3_direct_status_retest",
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


def test_data_trust_safe_derivation_patch() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected upstream artifacts were mutated"
    stdout = result.stdout
    for expected in [
        PARTIAL_STATUS,
        "BASELINE_CANDIDATE_COUNT=40",
        "SAFE_DERIVATION_CANDIDATE_COUNT_BEFORE=4",
        "SAFE_DERIVATION_APPLIED_COUNT=4",
        "SAFE_DERIVATION_REJECTED_COUNT=0",
        "REMAINING_UNKNOWN_REQUIRED_PIT_FIELD_COUNT=1920",
        "REMAINING_SOURCE_CONTRACT_REQUIRED_FIELD_COUNT=1920",
        "ACCEPTED_DIRECT_PIT_LINEAGE_ROW_COUNT_AFTER_DERIVATION=0",
        "DIRECT_PASS_CANDIDATE_COUNT_AFTER_DERIVATION=0",
        "DIRECT_UNKNOWN_CANDIDATE_COUNT_AFTER_DERIVATION=40",
        "REMAINING_PRODUCER_PATCH_REQUIRED_COUNT=6",
        "REMAINING_NEW_SOURCE_CONTRACT_REQUIRED_COUNT=2",
        "READY_FOR_V20_170_R2C_SOURCE_CONTRACT_PATCH=TRUE",
        "READY_FOR_V20_170_R3_DIRECT_STATUS_RETEST=FALSE",
        "READY_FOR_V20_171_GATE_ONLY_RANKING_SIMULATION=FALSE",
        "READY_FOR_OFFICIAL_USE=FALSE",
        "OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE",
        "OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE",
        "RANKING_SIMULATION_CREATED=FALSE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    plan = read_csv(OUTPUTS[0])
    patched = read_csv(OUTPUTS[2])
    validation = read_csv(OUTPUTS[3])
    remaining = read_csv(OUTPUTS[4])
    retest = read_csv(OUTPUTS[5])
    gate = read_csv(OUTPUTS[6])[0]
    safety = read_csv(OUTPUTS[7])

    assert PLAN_COLUMNS.issubset(plan[0].keys())
    assert PATCHED_COLUMNS.issubset(patched[0].keys())
    assert VALIDATION_COLUMNS.issubset(validation[0].keys())
    assert len(plan) == 4
    assert len(patched) == 960
    assert len(validation) == 240
    assert len(retest) == 240
    assert len(remaining) == 8
    assert gate["final_status"] == PARTIAL_STATUS
    assert gate["ready_for_v20_171_gate_only_ranking_simulation"] == "FALSE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert all(row["derivation_safe"] == "TRUE" for row in plan)
    assert all(row["accepted_direct_pit_lineage_after_derivation"] == "FALSE" for row in validation)
    assert all(row["ready_for_v20_170_r2c_source_contract_patch"] == "TRUE" for row in validation)
    assert {row["required_field"] for row in remaining} == {
        "factor_input_as_of_date", "factor_input_source_timestamp",
        "factor_input_publication_lag_handled", "factor_input_point_in_time_safe",
        "non_pit_blocker_present", "leakage_flag_present",
        "source_quality_usable", "freshness_usable",
    }
    assert all(row["safety_passed"] == "TRUE" for row in safety)
    assert_safety([gate, *plan, *patched[:5]])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "does not mark any ticker DIRECT_PASS" in report


if __name__ == "__main__":
    test_data_trust_safe_derivation_patch()
    print("PASS test_v20_170_r2b_data_trust_safe_derivation_patch")
