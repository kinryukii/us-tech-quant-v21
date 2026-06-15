#!/usr/bin/env python
"""Tests for V20.170-R2 DATA_TRUST direct status retest after PIT producer patch."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_170_r2_data_trust_direct_status_emitter_retest_after_pit_producer_patch.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_170_R2_DATA_TRUST_DIRECT_STATUS_RETEST.csv",
    FACTORS / "V20_170_R2_DATA_TRUST_DIRECT_PASS_FAIL_UNKNOWN.csv",
    FACTORS / "V20_170_R2_PIT_LINEAGE_CONSUMPTION_AUDIT.csv",
    FACTORS / "V20_170_R2_DIRECT_STATUS_BLOCKER_AUDIT.csv",
    FACTORS / "V20_170_R2_DIRECT_STATUS_REPAIR_BACKLOG.csv",
    FACTORS / "V20_170_R2_DIRECT_STATUS_COVERAGE_SUMMARY.csv",
    FACTORS / "V20_170_R2_DIRECT_STATUS_NEXT_GATE.csv",
    FACTORS / "V20_170_R2_DIRECT_STATUS_SAFETY_AUDIT.csv",
    READ_CENTER / "V20_170_R2_DATA_TRUST_DIRECT_STATUS_EMITTER_RETEST_AFTER_PIT_PRODUCER_PATCH_REPORT.md",
]

PROTECTED = [
    CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv",
    CONSOLIDATION / "V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv",
    CONSOLIDATION / "V20_108_R10_PIT_LINEAGE_SCHEMA_EXTENSION_AUDIT.csv",
    CONSOLIDATION / "V20_108_R10_PIT_LINEAGE_SOURCE_CONTRACT_GAP_AUDIT.csv",
    FACTORS / "V20_170_R1C_PIT_PRODUCER_PATCH_NEXT_GATE.csv",
    FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_EMITTER.csv",
    FACTORS / "V20_170_DATA_TRUST_DIRECT_PASS_FAIL_UNKNOWN.csv",
]

WARN_STATUS = "WARN_V20_170_R2_DIRECT_STATUS_RETEST_BLOCKED_BY_SOURCE_CONTRACT_GAPS"
RETEST_COLUMNS = {
    "ticker", "baseline_rank", "prior_direct_data_trust_status",
    "retested_direct_data_trust_status", "retested_direct_data_trust_pass",
    "retested_direct_data_trust_fail", "retested_direct_data_trust_unknown",
    "ticker_identity_match", "price_data_available",
    "required_factor_family_scores_available", "fundamental_score_available",
    "technical_score_available", "strategy_score_available", "risk_score_available",
    "market_regime_score_available", "data_trust_score_excluded_from_scoring",
    "pit_lineage_sidecar_available", "accepted_direct_pit_lineage_row_count",
    "required_pit_lineage_row_count", "source_contract_required_field_count",
    "unknown_required_pit_field_count", "pit_safety_status", "source_quality_status",
    "freshness_status", "schema_status", "current_ranking_eligibility_status",
    "score_lineage_bindable", "direct_status_confidence", "failure_or_unknown_reason",
    "repair_required", "recommended_repair_action",
}
CONSUMPTION_COLUMNS = {
    "ticker", "factor_family", "lineage_sidecar_row_count",
    "accepted_for_data_trust_direct_pit_status_count", "unknown_required_field_count",
    "source_contract_required_field_count", "non_pit_blocker_present",
    "leakage_flag_present", "schema_valid", "source_quality_usable",
    "freshness_usable", "factor_input_point_in_time_safe",
    "lineage_to_ranking_score_available", "consumed_by_direct_status_emitter",
    "rejection_reason",
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


def test_data_trust_direct_status_emitter_retest_after_pit_producer_patch() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected upstream artifacts were mutated"
    stdout = result.stdout
    for expected in [
        WARN_STATUS,
        "BASELINE_CANDIDATE_COUNT=40",
        "RETESTED_DIRECT_DATA_TRUST_PASS_COUNT=0",
        "RETESTED_DIRECT_DATA_TRUST_FAIL_COUNT=0",
        "RETESTED_DIRECT_DATA_TRUST_UNKNOWN_COUNT=40",
        "DIRECT_STATUS_COVERAGE_RATE=0.0000000000",
        "PIT_LINEAGE_SIDECAR_ROW_COUNT=1890",
        "ACCEPTED_DIRECT_PIT_LINEAGE_ROW_COUNT=0",
        "CONSUMED_PIT_LINEAGE_ROW_COUNT=240",
        "READY_FOR_V20_171_GATE_ONLY_RANKING_SIMULATION=FALSE",
        "READY_FOR_V20_170_R2A_SOURCE_CONTRACT_GAP_REPAIR=TRUE",
        "READY_FOR_OFFICIAL_USE=FALSE",
        "RECOMMENDED_NEXT_ACTION=REPAIR_SOURCE_CONTRACT_GAPS_BEFORE_RANKING",
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
    retest = read_csv(OUTPUTS[0])
    status = read_csv(OUTPUTS[1])
    consumption = read_csv(OUTPUTS[2])
    blockers = read_csv(OUTPUTS[3])
    backlog = read_csv(OUTPUTS[4])
    summary = read_csv(OUTPUTS[5])[0]
    gate = read_csv(OUTPUTS[6])[0]
    safety = read_csv(OUTPUTS[7])
    assert len(retest) == 40
    assert len(status) == 40
    assert RETEST_COLUMNS.issubset(retest[0].keys())
    assert CONSUMPTION_COLUMNS.issubset(consumption[0].keys())
    assert all(row["retested_direct_data_trust_unknown"] == "TRUE" for row in retest)
    assert all(row["retested_direct_data_trust_pass"] == "FALSE" for row in retest)
    assert all(row["pit_safety_status"] == "UNKNOWN" for row in retest)
    assert len(consumption) == 40 * 6
    assert sum(int(row["lineage_sidecar_row_count"]) for row in consumption) == 240
    assert len(blockers) == 40
    assert len(backlog) == 40
    assert summary["retested_direct_data_trust_unknown_count"] == "40"
    assert summary["ready_for_v20_171_gate_only_ranking_simulation"] == "FALSE"
    assert gate["final_status"] == WARN_STATUS
    assert gate["source_contract_required_not_treated_as_pass"] == "TRUE"
    assert all(row["safety_passed"] == "TRUE" for row in safety)
    assert_safety([gate, summary, *retest[:3]])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "UNKNOWN/source-contract-required PIT lineage is not treated" in report


if __name__ == "__main__":
    test_data_trust_direct_status_emitter_retest_after_pit_producer_patch()
    print("PASS test_v20_170_r2_data_trust_direct_status_emitter_retest_after_pit_producer_patch")
