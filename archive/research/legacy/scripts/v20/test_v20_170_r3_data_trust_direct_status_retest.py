#!/usr/bin/env python
"""Tests for V20.170-R3 DATA_TRUST direct status retest."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_170_r3_data_trust_direct_status_retest.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_170_R3_DATA_TRUST_DIRECT_STATUS_RETEST_CANDIDATES.csv",
    FACTORS / "V20_170_R3_DATA_TRUST_FIELD_RETEST_AUDIT.csv",
    FACTORS / "V20_170_R3_DATA_TRUST_REMAINING_UNKNOWN_AUDIT.csv",
    FACTORS / "V20_170_R3_DATA_TRUST_FAIL_DIAGNOSTICS.csv",
    FACTORS / "V20_170_R3_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_170_R3_DATA_TRUST_DIRECT_STATUS_RETEST_REPORT.md",
]
PROTECTED = [
    CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv",
    FACTORS / "V20_170_R2B_DERIVATION_VALIDATION_AUDIT.csv",
    FACTORS / "V20_170_R2C_NEXT_STAGE_GATE.csv",
]
WARN_STATUS = "WARN_V20_170_R3_ALL_CANDIDATES_REMAIN_UNKNOWN_REQUIRE_R3_R1_DIAGNOSTICS_REPAIR"

CANDIDATE_COLUMNS = {
    "ticker", "baseline_rank", "direct_status_before_r3", "direct_status_after_r3",
    "factor_family_count", "direct_pass_lineage_row_count", "direct_warn_lineage_row_count",
    "direct_fail_lineage_row_count", "direct_unknown_lineage_row_count",
    "structural_source_contract_gap_present", "remaining_unknown_direct_evidence_count",
    "remaining_fail_direct_evidence_count", "status_changed_from_unknown",
    "accepted_for_v20_171_gate_only_ranking_simulation", "direct_status_reason",
}
FIELD_COLUMNS = {
    "required_field", "field_retest_status", "structural_gap_present_after_r2c",
    "direct_evidence_value_available", "direct_evidence_pass_count", "direct_evidence_warn_count",
    "direct_evidence_fail_count", "direct_evidence_unknown_count", "affected_ticker_count",
    "affected_factor_family_count", "source_contract_patch_applied",
    "producer_patch_applied", "new_source_contract_added", "accepted_for_direct_status",
    "diagnostic_required", "limitation_reason",
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


def test_data_trust_direct_status_retest() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected artifacts were mutated"
    stdout = result.stdout
    for expected in [
        WARN_STATUS,
        "BASELINE_CANDIDATE_COUNT=40",
        "CANDIDATE_RETEST_COUNT=40",
        "DIRECT_PASS_CANDIDATE_COUNT=0",
        "DIRECT_WARN_CANDIDATE_COUNT=0",
        "DIRECT_FAIL_CANDIDATE_COUNT=0",
        "DIRECT_UNKNOWN_CANDIDATE_COUNT=40",
        "STATUS_CHANGED_FROM_UNKNOWN_COUNT=0",
        "STRUCTURAL_SOURCE_CONTRACT_GAP_COUNT=0",
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

    candidates = read_csv(OUTPUTS[0])
    fields = read_csv(OUTPUTS[1])
    unknown = read_csv(OUTPUTS[2])
    fail = read_csv(OUTPUTS[3])
    gate = read_csv(OUTPUTS[4])[0]
    assert CANDIDATE_COLUMNS.issubset(candidates[0].keys())
    assert FIELD_COLUMNS.issubset(fields[0].keys())
    assert len(candidates) == 40
    assert len(fields) == 8
    assert len(unknown) == 240
    assert len(fail) == 0
    assert all(row["direct_status_after_r3"] == "UNKNOWN" for row in candidates)
    assert all(row["accepted_for_v20_171_gate_only_ranking_simulation"] == "FALSE" for row in candidates)
    assert all(row["field_retest_status"] == "UNKNOWN" for row in fields)
    assert all(row["diagnostic_required"] == "TRUE" for row in fields)
    assert gate["final_status"] == WARN_STATUS
    assert gate["ready_for_v20_171_gate_only_ranking_simulation"] == "FALSE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert_safety([gate, *candidates[:3], *fields[:3], *unknown[:3]])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "All candidates remain UNKNOWN" in report


if __name__ == "__main__":
    test_data_trust_direct_status_retest()
    print("PASS test_v20_170_r3_data_trust_direct_status_retest")
