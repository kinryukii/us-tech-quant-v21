#!/usr/bin/env python
"""Tests for V20.170-R3-R1A DATA_TRUST missing evidence value producer review packet."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_170_r3_r1a_data_trust_missing_evidence_value_producer_review_packet.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_170_R3_R1A_MISSING_EVIDENCE_VALUE_DETAIL.csv",
    FACTORS / "V20_170_R3_R1A_MISSING_EVIDENCE_BY_PRODUCER.csv",
    FACTORS / "V20_170_R3_R1A_MISSING_EVIDENCE_BY_FIELD.csv",
    FACTORS / "V20_170_R3_R1A_MISSING_EVIDENCE_BY_CANDIDATE.csv",
    FACTORS / "V20_170_R3_R1A_REMEDIATION_ACTION_PACKET.csv",
    FACTORS / "V20_170_R3_R1A_OPTIONAL_WARN_DOWNGRADE_CANDIDATES.csv",
    FACTORS / "V20_170_R3_R1A_AUDIT_ONLY_RECLASSIFICATION_CANDIDATES.csv",
    FACTORS / "V20_170_R3_R1A_FALLBACK_SOURCE_REQUIRED.csv",
    FACTORS / "V20_170_R3_R1A_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_170_R3_R1A_DATA_TRUST_MISSING_EVIDENCE_VALUE_PRODUCER_REVIEW_PACKET_REPORT.md",
]
PROTECTED = [
    CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv",
    CONSOLIDATION / "V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv",
    FACTORS / "V20_170_R3_R1_NEXT_STAGE_GATE.csv",
]
PASS_STATUS = "PASS_V20_170_R3_R1A_REVIEW_PACKET_READY_FOR_R3_R1B_PRODUCER_VALUE_MATERIALIZATION"

DETAIL_COLUMNS = {
    "ticker", "baseline_rank", "as_of_date", "factor_family", "required_field",
    "source_contract_id", "expected_producer", "expected_artifact", "evidence_type",
    "pit_requirement", "missing_value_classification",
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


def test_data_trust_missing_evidence_value_producer_review_packet() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected artifacts were mutated"
    stdout = result.stdout
    for expected in [
        PASS_STATUS,
        "BASELINE_CANDIDATE_COUNT=40",
        "MISSING_EVIDENCE_VALUE_COUNT=1920",
        "DETAIL_ROW_COUNT=1920",
        "FIELD_SUMMARY_COUNT=8",
        "CANDIDATE_SUMMARY_COUNT=40",
        "PRODUCER_VALUE_NOT_GENERATED_COUNT=1920",
        "SAFE_PRODUCER_MATERIALIZATION_MISSING_VALUE_COUNT=1920",
        "READY_FOR_V20_170_R3_R1B_PRODUCER_VALUE_MATERIALIZATION_PATCH=TRUE",
        "READY_FOR_V20_170_R3_R1C_CONTRACT_REQUIREMENT_RECLASSIFICATION=FALSE",
        "READY_FOR_V20_170_R3_R1D_FALLBACK_SOURCE_CONTRACT_DESIGN=FALSE",
        "READY_FOR_V20_171_GATE_ONLY_RANKING_SIMULATION=FALSE",
        "READY_FOR_OFFICIAL_USE=FALSE",
        "NO_DATA_TRUST_STATUS_FABRICATED=TRUE",
        "NO_EVIDENCE_VALUES_FABRICATED=TRUE",
        "NO_TICKER_ROWS_FABRICATED=TRUE",
        "OFFICIAL_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    detail = read_csv(OUTPUTS[0])
    producer = read_csv(OUTPUTS[1])
    field = read_csv(OUTPUTS[2])
    candidate = read_csv(OUTPUTS[3])
    actions = read_csv(OUTPUTS[4])
    optional = read_csv(OUTPUTS[5])
    audit_only = read_csv(OUTPUTS[6])
    fallback = read_csv(OUTPUTS[7])
    gate = read_csv(OUTPUTS[8])[0]
    assert DETAIL_COLUMNS.issubset(detail[0].keys())
    assert len(detail) == 1920
    assert len(field) == 8
    assert len(candidate) == 40
    assert len(actions) == 8
    assert len(optional) == 0
    assert len(audit_only) == 0
    assert len(fallback) == 0
    assert len(producer) >= 1
    assert all(row["missing_value_classification"] == "producer_value_not_generated" for row in detail)
    assert all(row["safe_to_materialize_by_producer_patch"] == "TRUE" for row in detail)
    assert all(row["fabricated_value_created"] == "FALSE" for row in detail)
    assert all(row["ticker_row_fabricated"] == "FALSE" for row in detail)
    assert gate["final_status"] == PASS_STATUS
    assert gate["ready_for_v20_170_r3_r1b_producer_value_materialization_patch"] == "TRUE"
    assert gate["ready_for_v20_171_gate_only_ranking_simulation"] == "FALSE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert_safety([gate, *detail[:3], *field[:3], *candidate[:3]])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "does not fabricate ticker rows or evidence values" in report


if __name__ == "__main__":
    test_data_trust_missing_evidence_value_producer_review_packet()
    print("PASS test_v20_170_r3_r1a_data_trust_missing_evidence_value_producer_review_packet")
