#!/usr/bin/env python
"""Tests for V20.170-R1C DATA_TRUST upstream PIT producer patch implementation."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
R10_SCRIPT = ROOT / "scripts" / "v20" / "v20_108_r10_complete_factor_family_score_assembler.py"
SCRIPT = ROOT / "scripts" / "v20" / "v20_170_r1c_data_trust_upstream_pit_producer_patch_implementation.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R10_TABLE = CONSOLIDATION / "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv"
PIT_LINEAGE = CONSOLIDATION / "V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv"
PIT_SCHEMA_AUDIT = CONSOLIDATION / "V20_108_R10_PIT_LINEAGE_SCHEMA_EXTENSION_AUDIT.csv"
PIT_GAP_AUDIT = CONSOLIDATION / "V20_108_R10_PIT_LINEAGE_SOURCE_CONTRACT_GAP_AUDIT.csv"
BASELINE = CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
ACTIVE_WEIGHT_REGISTRY = CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv"

OUTPUTS = [
    PIT_LINEAGE,
    PIT_SCHEMA_AUDIT,
    PIT_GAP_AUDIT,
    FACTORS / "V20_170_R1C_PIT_PRODUCER_PATCH_IMPLEMENTATION_AUDIT.csv",
    FACTORS / "V20_170_R1C_PATCHED_PIT_LINEAGE_VALIDATION.csv",
    FACTORS / "V20_170_R1C_PIT_FIELD_COMPLETION_AUDIT.csv",
    FACTORS / "V20_170_R1C_UNRESOLVED_SOURCE_CONTRACT_BACKLOG.csv",
    FACTORS / "V20_170_R1C_PIT_PRODUCER_PATCH_NEXT_GATE.csv",
    FACTORS / "V20_170_R1C_PIT_PRODUCER_PATCH_SAFETY_AUDIT.csv",
    READ_CENTER / "V20_170_R1C_DATA_TRUST_UPSTREAM_PIT_PRODUCER_PATCH_IMPLEMENTATION_REPORT.md",
]

WARN_STATUS = "WARN_V20_170_R1C_PIT_PRODUCER_PATCH_CREATED_BUT_NO_ACCEPTED_DIRECT_LINEAGE"
PARTIAL_STATUS = "PARTIAL_PASS_V20_170_R1C_PIT_PRODUCER_PATCH_WITH_SOURCE_CONTRACT_GAPS_READY_FOR_V20_170_R2"

PIT_FIELDS = {
    "ticker", "ranking_context_id", "ranking_as_of_date", "data_snapshot_id",
    "source_artifact", "source_row_id", "factor_family", "factor_input_name",
    "factor_input_as_of_date", "factor_input_source_timestamp",
    "factor_input_publication_lag_handled", "factor_input_point_in_time_safe",
    "non_pit_blocker_present", "leakage_flag_present", "schema_valid",
    "source_quality_usable", "freshness_usable", "lineage_to_ranking_score_available",
    "accepted_for_data_trust_direct_pit_status",
}
R10_ORIGINAL_COLUMNS = {
    "ticker", "baseline_rank", "instrument_type",
    "fundamental_contribution", "technical_contribution", "strategy_contribution",
    "risk_contribution", "market_regime_contribution", "data_trust_contribution",
    "fundamental_materialization_status", "technical_materialization_status",
    "strategy_materialization_status", "risk_materialization_status",
    "market_regime_materialization_status", "data_trust_materialization_status",
    "complete_six_family_contribution", "applicable_family_contribution_complete",
    "missing_factor_families", "non_applicable_factor_families",
    "factor_family_assembly_status", "eligible_for_strict_six_family_shadow_rerank",
    "eligible_for_applicability_adjusted_shadow_rerank",
    "applicability_weight_policy_required", "source_rank_or_score_used",
    "baseline_rank_used_as_factor_contribution", "fabricated_values_created",
    "proxy_values_activated", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "is_official_ranking", "is_official_weight",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
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


def header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle).fieldnames or [])


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected_hashes() -> dict[Path, str]:
    return {p: digest(p) for p in [BASELINE, ACTIVE_WEIGHT_REGISTRY] if p.exists()}


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE"
        if "data_trust_scoring_weight" in row:
            assert row["data_trust_scoring_weight"] == "0.0000000000"
        if "data_trust_role" in row:
            assert row["data_trust_role"] == "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"


def test_data_trust_upstream_pit_producer_patch_implementation() -> None:
    subprocess.run(["python", "-m", "py_compile", str(R10_SCRIPT), str(SCRIPT)], cwd=ROOT, check=True)
    before = protected_hashes()
    old_rows = read_csv(R10_TABLE)
    old_header = header(R10_TABLE)
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "official ranking/weight protected artifacts were mutated"
    stdout = result.stdout
    for expected in [
        "V20_170_R1B_STATUS=PARTIAL_PASS_V20_170_R1B_PATCH_PLAN_WITH_UNRESOLVED_SOURCE_CONTRACTS_READY_FOR_V20_170_R1C",
        "PRODUCER_SCRIPT_PATCHED=TRUE",
        "SIDECAR_PIT_LINEAGE_ARTIFACT_CREATED=TRUE",
        "ROW_COUNT_PRESERVED=TRUE",
        "ACCEPTED_DIRECT_PIT_LINEAGE_ROW_COUNT=0",
        "READY_FOR_V20_170_R2_DIRECT_STATUS_RETEST=TRUE",
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
        "OFFICIAL_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    assert WARN_STATUS in stdout or PARTIAL_STATUS in stdout
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    new_rows = read_csv(R10_TABLE)
    new_header = header(R10_TABLE)
    assert len(old_rows) == len(new_rows)
    assert old_header == new_header
    assert R10_ORIGINAL_COLUMNS.issubset(new_header)
    lineage = read_csv(PIT_LINEAGE)
    gate = read_csv(FACTORS / "V20_170_R1C_PIT_PRODUCER_PATCH_NEXT_GATE.csv")[0]
    audit = read_csv(FACTORS / "V20_170_R1C_PIT_PRODUCER_PATCH_IMPLEMENTATION_AUDIT.csv")[0]
    validation = read_csv(FACTORS / "V20_170_R1C_PATCHED_PIT_LINEAGE_VALIDATION.csv")
    completion = read_csv(FACTORS / "V20_170_R1C_PIT_FIELD_COMPLETION_AUDIT.csv")
    safety = read_csv(FACTORS / "V20_170_R1C_PIT_PRODUCER_PATCH_SAFETY_AUDIT.csv")
    assert PIT_FIELDS.issubset(lineage[0].keys())
    assert len(lineage) == len(new_rows) * 6
    assert all(row["accepted_for_data_trust_direct_pit_status"] == "FALSE" for row in lineage)
    assert any(row["factor_input_point_in_time_safe"] == "UNKNOWN" for row in lineage)
    assert gate["ready_for_v20_170_r2_direct_status_retest"] == "TRUE"
    assert gate["ready_for_v20_171_gate_only_ranking_simulation"] == "FALSE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert audit["row_count_preserved"] == "TRUE"
    assert audit["downstream_compatibility_preserved"] == "TRUE"
    assert len(validation) == len(lineage)
    assert len(completion) == len(PIT_FIELDS)
    assert all(row["safety_passed"] == "TRUE" for row in safety)
    assert_safety([gate, audit, *lineage[:5]])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "does not create direct PIT PASS rows" in report


if __name__ == "__main__":
    test_data_trust_upstream_pit_producer_patch_implementation()
    print("PASS test_v20_170_r1c_data_trust_upstream_pit_producer_patch_implementation")
