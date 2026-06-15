#!/usr/bin/env python
"""Tests for V20.170-R1A DATA_TRUST upstream PIT source contract repair."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_170_r1a_data_trust_upstream_pit_source_contract_repair.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_170_R1A_UPSTREAM_PIT_SOURCE_CONTRACT.csv",
    FACTORS / "V20_170_R1A_UPSTREAM_PIT_SOURCE_DISCOVERY.csv",
    FACTORS / "V20_170_R1A_TICKER_FACTOR_PIT_LINEAGE_EMITTER.csv",
    FACTORS / "V20_170_R1A_TICKER_LEVEL_PIT_DIRECT_STATUS.csv",
    FACTORS / "V20_170_R1A_PIT_DIRECT_STATUS_MISSING_FIELD_AUDIT.csv",
    FACTORS / "V20_170_R1A_PIT_SOURCE_CONTRACT_REPAIR_BACKLOG.csv",
    FACTORS / "V20_170_R1A_PIT_SOURCE_CONTRACT_COVERAGE_SUMMARY.csv",
    FACTORS / "V20_170_R1A_PIT_SOURCE_CONTRACT_NEXT_GATE.csv",
    FACTORS / "V20_170_R1A_PIT_SOURCE_CONTRACT_SAFETY_AUDIT.csv",
    READ_CENTER / "V20_170_R1A_DATA_TRUST_UPSTREAM_PIT_SOURCE_CONTRACT_REPAIR_REPORT.md",
]

WARN_STATUS = "WARN_V20_170_R1A_UPSTREAM_PIT_PRODUCER_PATCH_PLAN_REQUIRED"
BLOCKED_STATUS = "BLOCKED_V20_170_R1A_UPSTREAM_PIT_SOURCE_CONTRACT_REPAIR"
REQUIRED_R1_STATUS = "WARN_V20_170_R1_NO_TICKER_LEVEL_PIT_SAFETY_EVIDENCE_RECOVERED"

CONTRACT_COLUMNS = {
    "ticker", "ranking_context_id", "ranking_as_of_date", "data_snapshot_id", "source_artifact",
    "source_row_id", "factor_family", "factor_input_name", "factor_input_as_of_date",
    "factor_input_source_timestamp", "factor_input_publication_lag_handled",
    "factor_input_point_in_time_safe", "non_pit_blocker_present", "leakage_flag_present",
    "schema_valid", "source_quality_usable", "freshness_usable",
    "lineage_to_ranking_score_available", "accepted_for_data_trust_direct_pit_status",
}
DISCOVERY_COLUMNS = {
    "source_artifact", "artifact_exists", "row_count", "ticker_level", "has_ticker_column",
    "ticker_column_name", "has_ranking_as_of_date", "has_data_snapshot_id",
    "has_factor_family_field", "has_factor_input_name_field", "has_factor_input_as_of_date",
    "has_source_timestamp", "has_pit_status_field", "has_non_pit_blocker_field",
    "has_leakage_flag_field", "has_schema_valid_field", "has_source_quality_field",
    "has_freshness_field", "usable_for_upstream_pit_contract", "aggregate_only",
    "limitation_reason",
}
STATUS_COLUMNS = {
    "ticker", "baseline_rank", "pit_direct_status", "pit_direct_pass", "pit_direct_fail",
    "pit_direct_unknown", "accepted_pit_lineage_row_count", "required_factor_family_pit_lineage_count",
    "missing_factor_family_pit_lineage_count", "non_pit_blocker_present", "leakage_flag_present",
    "pit_source_artifacts", "pit_missing_fields", "pit_status_confidence",
    "failure_or_unknown_reason", "repair_required", "recommended_repair_action",
}
MISSING_COLUMNS = {
    "ticker", "factor_family", "missing_required_field", "source_artifact",
    "source_field_expected", "available_alternative_field", "can_repair_from_existing_artifact",
    "requires_upstream_producer_patch", "recommended_upstream_stage_or_script",
    "repair_priority",
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


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    assert rows
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected_hashes() -> dict[Path, str]:
    paths = [
        FACTORS / "V20_170_R1_DATA_TRUST_PIT_SOURCE_DISCOVERY.csv",
        FACTORS / "V20_170_R1_TICKER_LEVEL_PIT_SAFETY_STATUS.csv",
        FACTORS / "V20_170_R1_PIT_SAFETY_EVIDENCE_LINEAGE.csv",
        FACTORS / "V20_170_R1_PIT_SAFETY_REPAIR_BACKLOG.csv",
        FACTORS / "V20_170_R1_DATA_TRUST_DIRECT_STATUS_RETEST_INPUT.csv",
        FACTORS / "V20_170_R1_PIT_SAFETY_COVERAGE_AUDIT.csv",
        FACTORS / "V20_170_R1_PIT_SAFETY_NEXT_GATE.csv",
        FACTORS / "V20_170_R1_PIT_SAFETY_SAFETY_AUDIT.csv",
        CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
        CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv",
    ]
    return {p: digest(p) for p in paths if p.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_170_r1a", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.CONSOLIDATION = temp / "consolidation"
    module.FACTORS = temp / "factors"
    module.BACKTEST = temp / "backtest"
    module.READ_CENTER = temp / "read_center"
    module.R1_INPUTS = [module.FACTORS / p.name for p in module.R1_INPUTS]
    module.BASELINE = module.CONSOLIDATION / module.BASELINE.name
    module.ACTIVE_WEIGHT_REGISTRY = module.CONSOLIDATION / module.ACTIVE_WEIGHT_REGISTRY.name
    module.NAMED_SOURCES = [module.FACTORS / "DIRECT_PIT.csv"]
    for name in ["OUT_CONTRACT", "OUT_DISCOVERY", "OUT_EMITTER", "OUT_STATUS", "OUT_MISSING", "OUT_BACKLOG", "OUT_SUMMARY", "OUT_GATE", "OUT_SAFETY"]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    module.REPORT = module.READ_CENTER / module.REPORT.name
    module.OUTPUT_PATHS = [module.OUT_CONTRACT, module.OUT_DISCOVERY, module.OUT_EMITTER, module.OUT_STATUS, module.OUT_MISSING, module.OUT_BACKLOG, module.OUT_SUMMARY, module.OUT_GATE, module.OUT_SAFETY]


def write_common_inputs(module, status_ok: bool = True) -> None:
    for path in module.R1_INPUTS:
        if path.name == "V20_170_R1_PIT_SAFETY_NEXT_GATE.csv":
            write_csv(path, [{"final_status": REQUIRED_R1_STATUS if status_ok else "PASS"}])
        else:
            write_csv(path, [{"id": "X"}])
    write_csv(module.BASELINE, [
        {"ticker": "AAA", "official_current_rank": "1", "ranking_timestamp_utc": "2026-06-06T00:00:00Z", "source_run_id": "RUN1", "source_file": "baseline.csv"},
        {"ticker": "BBB", "official_current_rank": "2", "ranking_timestamp_utc": "2026-06-06T00:00:00Z", "source_run_id": "RUN1", "source_file": "baseline.csv"},
    ])


def write_direct_source(module, include_bbb: bool = False) -> None:
    rows = []
    for ticker in ["AAA"] + (["BBB"] if include_bbb else []):
        for family in module.FACTOR_FAMILIES:
            rows.append({
                "ticker": ticker,
                "ranking_as_of_date": "2026-06-06",
                "data_snapshot_id": "SNAP1",
                "factor_family": family,
                "factor_input_name": f"{family}_INPUT",
                "factor_input_as_of_date": "2026-06-05",
                "source_timestamp": "2026-06-05T00:00:00Z",
                "publication_lag_handled": "TRUE",
                "pit_status": "TRUE",
                "non_pit_blocker": "FALSE",
                "leakage_flag": "FALSE",
                "schema_valid": "TRUE",
                "source_quality": "TRUE",
                "freshness": "TRUE",
                "ranking_lineage": "TRUE",
            })
    write_csv(module.NAMED_SOURCES[0], rows)


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE"
        if "data_trust_scoring_weight" in row:
            assert row["data_trust_scoring_weight"] == "0.0000000000"
        if "data_trust_role" in row:
            assert row["data_trust_role"] == "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == BLOCKED_STATUS


def test_blocked_wrong_r1_status_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_common_inputs(module, status_ok=False)
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == BLOCKED_STATUS


def test_temp_partial_and_pass_cases() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_common_inputs(module)
        write_direct_source(module, include_bbb=False)
        assert module.main() == 0
        assert read_csv(module.OUT_SUMMARY)[0]["pit_direct_pass_count"] == "1"
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_common_inputs(module)
        write_direct_source(module, include_bbb=True)
        assert module.main() == 0
        summary = read_csv(module.OUT_SUMMARY)[0]
        assert summary["pit_direct_pass_count"] == "2"
        assert summary["ready_for_v20_170_r2_direct_status_retest"] == "TRUE"


def test_data_trust_upstream_pit_source_contract_repair() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected R1/ranking/weight artifacts were mutated"
    stdout = result.stdout
    for expected in [
        WARN_STATUS,
        f"V20_170_R1_STATUS={REQUIRED_R1_STATUS}",
        "BASELINE_CANDIDATE_COUNT=40",
        "PIT_DIRECT_PASS_COUNT=0",
        "PIT_DIRECT_FAIL_COUNT=0",
        "PIT_DIRECT_UNKNOWN_COUNT=40",
        "PIT_DIRECT_COVERAGE_RATE=0.0000000000",
        "READY_FOR_V20_170_R2_DIRECT_STATUS_RETEST=FALSE",
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
        "RECOMMENDED_NEXT_ACTION=CREATE_UPSTREAM_PIT_PRODUCER_PATCH_PLAN",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    contract = read_csv(OUTPUTS[0])
    discovery = read_csv(OUTPUTS[1])
    emitter = read_csv(OUTPUTS[2])
    status = read_csv(OUTPUTS[3])
    missing = read_csv(OUTPUTS[4])
    summary = read_csv(OUTPUTS[6])[0]
    gate = read_csv(OUTPUTS[7])[0]
    safety = read_csv(OUTPUTS[8])
    assert CONTRACT_COLUMNS == {row["contract_field"] for row in contract}
    assert DISCOVERY_COLUMNS.issubset(discovery[0].keys())
    assert set(OUTPUTS[2].read_text(encoding="utf-8").splitlines()[0].split(",")).issuperset(CONTRACT_COLUMNS)
    assert len(emitter) == 40 * 6
    assert len(status) == 40
    assert STATUS_COLUMNS.issubset(status[0].keys())
    assert MISSING_COLUMNS.issubset(missing[0].keys())
    assert all(row["pit_direct_unknown"] == "TRUE" for row in status)
    assert all(row["accepted_for_data_trust_direct_pit_status"] == "FALSE" for row in emitter)
    assert summary["pit_direct_pass_count"] == "0"
    assert summary["pit_direct_unknown_count"] == "40"
    assert summary["ready_for_v20_171_gate_only_ranking_simulation"] == "FALSE"
    assert gate["final_status"] == WARN_STATUS
    assert gate["ready_for_official_use"] == "FALSE"
    assert gate["official_weight_change_allowed"] == "FALSE"
    assert gate["official_ranking_mutation_allowed"] == "FALSE"
    assert all(row["safety_passed"] == "TRUE" for row in safety)
    assert_safety([*status, gate, summary])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert WARN_STATUS in report
    assert "Aggregate PIT evidence is not accepted" in report


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_blocked_wrong_r1_status_case()
    test_temp_partial_and_pass_cases()
    test_data_trust_upstream_pit_source_contract_repair()
    print("PASS test_v20_170_r1a_data_trust_upstream_pit_source_contract_repair")
