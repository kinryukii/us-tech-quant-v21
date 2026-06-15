#!/usr/bin/env python
"""Tests for V20.170-R3-R2 DATA_TRUST direct status retest after materialization."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_170_r3_r2_data_trust_direct_status_retest_after_materialization.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_170_R3_R2_DATA_TRUST_DIRECT_STATUS_RETEST_CANDIDATES.csv",
    FACTORS / "V20_170_R3_R2_FIELD_RETEST_AUDIT.csv",
    FACTORS / "V20_170_R3_R2_CANDIDATE_EVIDENCE_COMPLETENESS_AUDIT.csv",
    FACTORS / "V20_170_R3_R2_REMAINING_UNKNOWN_DIAGNOSTICS.csv",
    FACTORS / "V20_170_R3_R2_REMAINING_FAIL_DIAGNOSTICS.csv",
    FACTORS / "V20_170_R3_R2_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_170_R3_R2_DATA_TRUST_DIRECT_STATUS_RETEST_AFTER_MATERIALIZATION_REPORT.md",
]
PROTECTED = [
    CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv",
    CONSOLIDATION / "V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv",
    FACTORS / "V20_170_R3_R1B_NEXT_STAGE_GATE.csv",
]
PASS_STATUS = "PASS_V20_170_R3_R2_DIRECT_STATUS_RETEST_READY_FOR_V20_171"

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


def test_data_trust_direct_status_retest_after_materialization() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected artifacts were mutated"
    stdout = result.stdout
    for expected in [
        PASS_STATUS,
        "BASELINE_CANDIDATE_COUNT=40",
        "CANDIDATE_RETEST_COUNT=40",
        "DIRECT_PASS_CANDIDATE_COUNT=40",
        "DIRECT_WARN_CANDIDATE_COUNT=0",
        "DIRECT_FAIL_CANDIDATE_COUNT=0",
        "DIRECT_UNKNOWN_CANDIDATE_COUNT=0",
        "MATERIALIZED_EVIDENCE_VALUE_COUNT=1920",
        "REMAINING_MISSING_EVIDENCE_VALUE_COUNT=0",
        "STRUCTURAL_SOURCE_CONTRACT_GAP_COUNT=0",
        "REMAINING_FAIL_EVIDENCE_VALUE_COUNT=0",
        "READY_FOR_V20_171_GATE_ONLY_RANKING_SIMULATION=TRUE",
        "READY_FOR_V20_171_FULL_GATE_ONLY_RANKING_SIMULATION=TRUE",
        "READY_FOR_OFFICIAL_USE=FALSE",
        "NO_DATA_TRUST_STATUS_FABRICATED=TRUE",
        "NO_EVIDENCE_VALUES_FABRICATED=TRUE",
        "NO_TICKER_ROWS_FABRICATED=TRUE",
        "OFFICIAL_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    candidates = read_csv(OUTPUTS[0])
    fields = read_csv(OUTPUTS[1])
    completeness = read_csv(OUTPUTS[2])
    unknown = read_csv(OUTPUTS[3])
    fail = read_csv(OUTPUTS[4])
    gate = read_csv(OUTPUTS[5])[0]
    assert len(candidates) == 40
    assert len(fields) == 8
    assert len(completeness) == 240
    assert len(unknown) == 0
    assert len(fail) == 0
    assert all(row["direct_status_after_materialization"] == "PASS" for row in candidates)
    assert all(row["accepted_for_v20_171_gate_only_ranking_simulation"] == "TRUE" for row in candidates)
    assert all(row["field_retest_status"] == "PASS" for row in fields)
    assert all(row["complete_for_direct_status"] == "TRUE" for row in completeness)
    assert gate["final_status"] == PASS_STATUS
    assert gate["ready_for_v20_171_gate_only_ranking_simulation"] == "TRUE"
    assert gate["ready_for_v20_171_full_gate_only_ranking_simulation"] == "TRUE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert_safety([gate, *candidates[:3], *fields[:3], *completeness[:3]])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "DATA_TRUST remains gate-only" in report


if __name__ == "__main__":
    test_data_trust_direct_status_retest_after_materialization()
    print("PASS test_v20_170_r3_r2_data_trust_direct_status_retest_after_materialization")
