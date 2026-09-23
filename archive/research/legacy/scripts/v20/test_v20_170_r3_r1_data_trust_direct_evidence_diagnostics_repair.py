#!/usr/bin/env python
"""Tests for V20.170-R3-R1 DATA_TRUST direct evidence diagnostics repair."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_170_r3_r1_data_trust_direct_evidence_diagnostics_repair.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_170_R3_R1_DIRECT_EVIDENCE_BINDING_DIAGNOSTICS.csv",
    FACTORS / "V20_170_R3_R1_CANDIDATE_UNKNOWN_CAUSE_AUDIT.csv",
    FACTORS / "V20_170_R3_R1_FIELD_UNKNOWN_CAUSE_AUDIT.csv",
    FACTORS / "V20_170_R3_R1_ARTIFACT_EVIDENCE_AVAILABILITY_AUDIT.csv",
    FACTORS / "V20_170_R3_R1_JOIN_KEY_ASOF_MAPPING_AUDIT.csv",
    FACTORS / "V20_170_R3_R1_SAFE_BINDING_REPAIR_AUDIT.csv",
    FACTORS / "V20_170_R3_R1_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_170_R3_R1_DATA_TRUST_DIRECT_EVIDENCE_DIAGNOSTICS_REPAIR_REPORT.md",
]
PROTECTED = [
    CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv",
    CONSOLIDATION / "V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv",
    FACTORS / "V20_170_R3_NEXT_STAGE_GATE.csv",
    FACTORS / "V20_170_R2C_NEXT_STAGE_GATE.csv",
]
WARN_STATUS = "WARN_V20_170_R3_R1_NO_SAFE_BINDING_REPAIR_MANUAL_PRODUCER_REVIEW_REQUIRED"

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


def test_data_trust_direct_evidence_diagnostics_repair() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected artifacts were mutated"
    stdout = result.stdout
    for expected in [
        WARN_STATUS,
        "BASELINE_CANDIDATE_COUNT=40",
        "CANDIDATE_DIAGNOSTIC_COUNT=40",
        "FIELD_DIAGNOSTIC_COUNT=8",
        "ARTIFACT_DIAGNOSTIC_COUNT=8",
        "JOIN_MAPPING_DIAGNOSTIC_COUNT=240",
        "REMAINING_UNKNOWN_DIRECT_EVIDENCE_COUNT_BEFORE_REPAIR=1920",
        "REMAINING_UNKNOWN_DIRECT_EVIDENCE_COUNT_AFTER_REPAIR=1920",
        "UNKNOWN_REDUCTION_COUNT=0",
        "SAFE_BINDING_REPAIR_POSSIBLE_COUNT=0",
        "SAFE_BINDING_REPAIR_APPLIED_COUNT=0",
        "MISSING_EVIDENCE_VALUE_COUNT=1920",
        "READY_FOR_V20_170_R3_R2_RETEST_AFTER_BINDING_REPAIR=FALSE",
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

    binding = read_csv(OUTPUTS[0])
    candidate = read_csv(OUTPUTS[1])
    field = read_csv(OUTPUTS[2])
    artifact = read_csv(OUTPUTS[3])
    join = read_csv(OUTPUTS[4])
    repair = read_csv(OUTPUTS[5])
    gate = read_csv(OUTPUTS[6])[0]
    assert len(binding) == 1920
    assert len(candidate) == 40
    assert len(field) == 8
    assert len(artifact) == 8
    assert len(join) == 240
    assert len(repair) == 8
    assert all(row["unknown_cause"] == "missing_evidence_value" for row in binding)
    assert all(row["dominant_unknown_cause"] == "missing_evidence_value" for row in candidate)
    assert all(row["safe_binding_repair_applied"] == "FALSE" for row in repair)
    assert all(row["fabricated_values_created"] == "FALSE" for row in repair)
    assert gate["final_status"] == WARN_STATUS
    assert gate["ready_for_v20_170_r3_r2_retest_after_binding_repair"] == "FALSE"
    assert gate["ready_for_v20_171_gate_only_ranking_simulation"] == "FALSE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert_safety([gate, *binding[:3], *candidate[:3], *repair[:3]])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "missing_evidence_value" in report


if __name__ == "__main__":
    test_data_trust_direct_evidence_diagnostics_repair()
    print("PASS test_v20_170_r3_r1_data_trust_direct_evidence_diagnostics_repair")
