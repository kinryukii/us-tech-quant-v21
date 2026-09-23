#!/usr/bin/env python
"""Tests for V20.170-R2A DATA_TRUST source contract gap repair plan."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_170_r2a_data_trust_source_contract_gap_repair_plan.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_SUMMARY.csv",
    FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_BY_FIELD.csv",
    FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_BY_TICKER.csv",
    FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_BY_FACTOR_FAMILY.csv",
    FACTORS / "V20_170_R2A_SOURCE_CONTRACT_PATCH_TARGETS.csv",
    FACTORS / "V20_170_R2A_SAFE_DERIVATION_CANDIDATES.csv",
    FACTORS / "V20_170_R2A_NEW_SOURCE_CONTRACT_REQUIREMENTS.csv",
    FACTORS / "V20_170_R2A_DIRECT_PASS_BLOCKER_PRIORITY.csv",
    FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_NEXT_GATE.csv",
    FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_SAFETY_AUDIT.csv",
    READ_CENTER / "V20_170_R2A_DATA_TRUST_SOURCE_CONTRACT_GAP_REPAIR_PLAN_REPORT.md",
]
PROTECTED = [
    CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv",
    CONSOLIDATION / "V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv",
    CONSOLIDATION / "V20_108_R10_PIT_LINEAGE_SCHEMA_EXTENSION_AUDIT.csv",
    CONSOLIDATION / "V20_108_R10_PIT_LINEAGE_SOURCE_CONTRACT_GAP_AUDIT.csv",
    FACTORS / "V20_170_R2_DIRECT_STATUS_NEXT_GATE.csv",
    FACTORS / "V20_170_R2_DATA_TRUST_DIRECT_STATUS_RETEST.csv",
    FACTORS / "V20_170_R1C_PIT_FIELD_COMPLETION_AUDIT.csv",
]
PARTIAL_STATUS = "PARTIAL_PASS_V20_170_R2A_SOURCE_CONTRACT_GAP_PLAN_READY_FOR_V20_170_R2B_R2C"

FIELD_COLUMNS = {
    "required_field", "blocker_category", "missing_or_unknown_count",
    "source_contract_required_count", "affected_ticker_count", "affected_factor_family_count",
    "affected_lineage_row_count", "current_available_source_artifact",
    "current_available_source_field", "gap_classification", "safe_derivation_possible",
    "proposed_derivation_rule", "proposed_upstream_producer_script",
    "proposed_output_artifact", "proposed_output_field", "requires_schema_extension",
    "requires_new_source_contract", "blocks_direct_pass", "repair_priority",
    "recommended_repair_action",
}
TICKER_COLUMNS = {
    "ticker", "baseline_rank", "direct_status_after_r2", "direct_pass_blocker_count",
    "missing_required_field_count", "source_contract_required_field_count",
    "affected_factor_family_count", "highest_priority_blocker",
    "can_repair_from_safe_derivation", "requires_producer_patch",
    "requires_new_source_contract", "recommended_next_action",
}
TARGET_COLUMNS = {
    "patch_target_id", "producer_script", "producer_exists", "output_artifact",
    "output_artifact_exists", "fields_to_add", "fields_to_safely_derive",
    "fields_requiring_new_source_contract", "expected_row_grain", "expected_join_keys",
    "downstream_consumers", "patch_sequence_order", "patch_risk", "test_required",
    "recommended_stage_for_patch",
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
    return {p: digest(p) for p in PROTECTED if p.exists()}


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE"
        if "data_trust_scoring_weight" in row:
            assert row["data_trust_scoring_weight"] == "0.0000000000"
        if "data_trust_role" in row:
            assert row["data_trust_role"] == "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"


def test_data_trust_source_contract_gap_repair_plan() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected upstream artifacts were mutated"
    stdout = result.stdout
    for expected in [
        PARTIAL_STATUS,
        "BASELINE_CANDIDATE_COUNT=40",
        "DIRECT_PASS_COUNT_BEFORE_GAP_REPAIR=0",
        "DIRECT_UNKNOWN_COUNT_BEFORE_GAP_REPAIR=40",
        "SOURCE_CONTRACT_REQUIRED_FIELD_COUNT=2160",
        "UNKNOWN_REQUIRED_PIT_FIELD_COUNT=2640",
        "SAFE_DERIVATION_CANDIDATE_COUNT=4",
        "PRODUCER_PATCH_REQUIRED_COUNT=6",
        "NEW_SOURCE_CONTRACT_REQUIRED_COUNT=2",
        "READY_FOR_V20_170_R2B_SAFE_DERIVATION_PATCH=TRUE",
        "READY_FOR_V20_170_R2C_SOURCE_CONTRACT_PATCH=TRUE",
        "READY_FOR_V20_171_GATE_ONLY_RANKING_SIMULATION=FALSE",
        "READY_FOR_OFFICIAL_USE=FALSE",
        "OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE",
        "OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE",
        "RANKING_SIMULATION_CREATED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "REAL_BOOK_ACTION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "PERFORMANCE_CLAIM_CREATED=FALSE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    summary = read_csv(OUTPUTS[0])[0]
    by_field = read_csv(OUTPUTS[1])
    by_ticker = read_csv(OUTPUTS[2])
    by_family = read_csv(OUTPUTS[3])
    targets = read_csv(OUTPUTS[4])
    safe = read_csv(OUTPUTS[5])
    new = read_csv(OUTPUTS[6])
    priority = read_csv(OUTPUTS[7])
    gate = read_csv(OUTPUTS[8])[0]
    safety = read_csv(OUTPUTS[9])
    assert FIELD_COLUMNS.issubset(by_field[0].keys())
    assert TICKER_COLUMNS.issubset(by_ticker[0].keys())
    assert TARGET_COLUMNS.issubset(targets[0].keys())
    assert len(by_field) == 15
    assert len(by_ticker) == 40
    assert len(by_family) == 6
    assert len(safe) == 4
    assert len(new) == 2
    assert priority
    assert summary["distinct_gap_field_count"] == "12"
    assert gate["final_status"] == PARTIAL_STATUS
    assert gate["ready_for_v20_171_gate_only_ranking_simulation"] == "FALSE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert all(row["direct_status_after_r2"] == "UNKNOWN" for row in by_ticker)
    assert all(row["safety_passed"] == "TRUE" for row in safety)
    assert_safety([gate, summary, *by_field[:3]])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "does not mark any ticker DIRECT_PASS" in report


if __name__ == "__main__":
    test_data_trust_source_contract_gap_repair_plan()
    print("PASS test_v20_170_r2a_data_trust_source_contract_gap_repair_plan")
