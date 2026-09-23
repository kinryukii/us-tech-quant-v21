#!/usr/bin/env python
"""Tests for V20.130 evidence collection reconciliation."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_130_evidence_collection_reconciliation.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"

OUT_DECISION = CONSOLIDATION / "V20_130_EVIDENCE_COLLECTION_RECONCILIATION_DECISION.csv"
OUT_PLAN = CONSOLIDATION / "V20_130_EVIDENCE_PLAN_RECONCILIATION_AUDIT.csv"
OUT_RESULT = CONSOLIDATION / "V20_130_EVIDENCE_RESULT_RECONCILIATION_AUDIT.csv"
OUT_COVERAGE = CONSOLIDATION / "V20_130_BLOCKER_EVIDENCE_COVERAGE_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_130_EVIDENCE_RECONCILIATION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_130_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_130_EVIDENCE_COLLECTION_RECONCILIATION_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_PLAN, OUT_RESULT, OUT_COVERAGE, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    *[CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116", "117", "118", "119", "120", "121", "122", "123", "124", "125", "126", "127", "128", "129"]],
    CONSOLIDATION / "V20_129_ADDITIONAL_EVIDENCE_COLLECTION_DRY_RUN_DECISION.csv",
    CONSOLIDATION / "V20_129_EVIDENCE_COLLECTION_DRY_RUN_EXECUTION_AUDIT.csv",
    CONSOLIDATION / "V20_129_EVIDENCE_COLLECTION_DRY_RUN_RESULT_AUDIT.csv",
    CONSOLIDATION / "V20_129_EVIDENCE_COLLECTION_GAP_STATUS_AUDIT.csv",
    CONSOLIDATION / "V20_129_EVIDENCE_COLLECTION_DRY_RUN_SAFETY_BOUNDARY_AUDIT.csv",
    CONSOLIDATION / "V20_128_EVIDENCE_COLLECTION_PLAN.csv",
    CONSOLIDATION / "V20_128_EVIDENCE_REQUIREMENT_DETAIL_AUDIT.csv",
    CONSOLIDATION / "V20_127_REQUIRED_NEXT_EVIDENCE_AUDIT.csv",
    CONSOLIDATION / "V20_127_REMAINING_BLOCKER_RESOLUTION_STATUS.csv",
]
REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_129_gate_consumed", "v20_130_evidence_collection_reconciliation_allowed_by_v129", "v20_129_final_status", "selected_repair_scenario_id", "evidence_collection_plan_row_count", "evidence_plan_reconciliation_row_count", "every_evidence_collection_plan_has_reconciliation_row", "evidence_result_reconciliation_row_count", "unresolved_blocker_count", "blocker_evidence_coverage_row_count", "every_unresolved_blocker_has_coverage_status", "operator_acceptance", "promotion_ready", "v20_131_operator_evidence_review_packet_allowed", "evidence_collection_reconciliation_status"},
    OUT_PLAN: {"source_evidence_collection_plan_id", "source_dry_run_execution_audit_id", "source_remaining_blocker_resolution_status_id", "blocker_category", "plan_reconciliation_status", "required_evidence_artifact", "operator_acceptance", "promotion_ready", "ticker_rows_created"},
    OUT_RESULT: {"source_evidence_collection_plan_id", "source_dry_run_result_audit_id", "source_gap_status_audit_id", "blocker_category", "dry_run_result_status", "gap_status", "result_reconciliation_status", "operator_acceptance", "promotion_ready"},
    OUT_COVERAGE: {"source_remaining_blocker_resolution_status_id", "source_required_next_evidence_audit_id", "source_evidence_collection_plan_id", "source_dry_run_result_audit_id", "blocker_category", "coverage_status", "coverage_reason", "operator_acceptance", "promotion_ready"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_129_gate_consumed", "selected_repair_scenario_id", "operator_acceptance", "promotion_ready", "v20_131_operator_evidence_review_packet_allowed", "evidence_collection_reconciliation_status"},
}
PROHIBITED_FALSE_FIELDS = ["accepted_weight_created", "real_book_weight_created", "official_weight_created", "official_ranking_created", "official_recommendation_created", "trade_action_created", "broker_action_created", "authoritative_overwrite_created", "weight_mutated", "performance_claim_created", "promotion_ready"]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    assert rows
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def upstream_hashes() -> dict[Path, str]:
    return {path: digest(path) for path in UPSTREAM if path.exists()}


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    bad = [row for row in rows if row.get(field) not in {"", "FALSE"}]
    assert not bad, f"{field} was not FALSE: {bad[:3]}"


def load_module():
    spec = importlib.util.spec_from_file_location("v20_130_evidence_collection_reconciliation_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    mapping = {
        "IN_DECISION": "V20_129_ADDITIONAL_EVIDENCE_COLLECTION_DRY_RUN_DECISION.csv",
        "IN_EXECUTION": "V20_129_EVIDENCE_COLLECTION_DRY_RUN_EXECUTION_AUDIT.csv",
        "IN_RESULT": "V20_129_EVIDENCE_COLLECTION_DRY_RUN_RESULT_AUDIT.csv",
        "IN_GAP": "V20_129_EVIDENCE_COLLECTION_GAP_STATUS_AUDIT.csv",
        "IN_SAFETY": "V20_129_EVIDENCE_COLLECTION_DRY_RUN_SAFETY_BOUNDARY_AUDIT.csv",
        "IN_GATE": "V20_129_NEXT_STAGE_GATE.csv",
        "IN_PLAN": "V20_128_EVIDENCE_COLLECTION_PLAN.csv",
        "IN_DETAIL": "V20_128_EVIDENCE_REQUIREMENT_DETAIL_AUDIT.csv",
        "IN_V127_REQUIRED": "V20_127_REQUIRED_NEXT_EVIDENCE_AUDIT.csv",
        "IN_V127_REMAINING": "V20_127_REMAINING_BLOCKER_RESOLUTION_STATUS.csv",
    }
    for attr, filename in mapping.items():
        setattr(module, attr, temp / filename)
    module.REQUIRED_INPUTS = [getattr(module, attr) for attr in mapping]
    module.UPSTREAM_HASH_INPUTS = module.REQUIRED_INPUTS
    module.OUT_DECISION = temp / "V20_130_EVIDENCE_COLLECTION_RECONCILIATION_DECISION.csv"
    module.OUT_PLAN = temp / "V20_130_EVIDENCE_PLAN_RECONCILIATION_AUDIT.csv"
    module.OUT_RESULT = temp / "V20_130_EVIDENCE_RESULT_RECONCILIATION_AUDIT.csv"
    module.OUT_COVERAGE = temp / "V20_130_BLOCKER_EVIDENCE_COVERAGE_AUDIT.csv"
    module.OUT_SAFETY = temp / "V20_130_EVIDENCE_RECONCILIATION_SAFETY_BOUNDARY_AUDIT.csv"
    module.OUT_GATE = temp / "V20_130_NEXT_STAGE_GATE.csv"
    module.REPORT = temp / "V20_130_EVIDENCE_COLLECTION_RECONCILIATION_REPORT.md"


def copy_required_inputs(temp: Path) -> None:
    for filename in [
        "V20_129_ADDITIONAL_EVIDENCE_COLLECTION_DRY_RUN_DECISION.csv",
        "V20_129_EVIDENCE_COLLECTION_DRY_RUN_EXECUTION_AUDIT.csv",
        "V20_129_EVIDENCE_COLLECTION_DRY_RUN_RESULT_AUDIT.csv",
        "V20_129_EVIDENCE_COLLECTION_GAP_STATUS_AUDIT.csv",
        "V20_129_EVIDENCE_COLLECTION_DRY_RUN_SAFETY_BOUNDARY_AUDIT.csv",
        "V20_129_NEXT_STAGE_GATE.csv",
        "V20_128_EVIDENCE_COLLECTION_PLAN.csv",
        "V20_128_EVIDENCE_REQUIREMENT_DETAIL_AUDIT.csv",
        "V20_127_REQUIRED_NEXT_EVIDENCE_AUDIT.csv",
        "V20_127_REMAINING_BLOCKER_RESOLUTION_STATUS.csv",
    ]:
        shutil.copy2(CONSOLIDATION / filename, temp / filename)


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        assert module.main() == 0
        blocked = read_csv(module.OUT_DECISION)[0]
        assert blocked["evidence_collection_reconciliation_status"] == "BLOCKED_V20_130_EVIDENCE_COLLECTION_RECONCILIATION"
        assert blocked["v20_131_operator_evidence_review_packet_allowed"] == "FALSE"
        assert blocked["promotion_ready"] == "FALSE"


def test_missing_plan_reconciliation_cannot_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        original_builder = module.build_reconciliation_artifacts

        def incomplete_builder(selected_id, plan_rows, execution_rows, result_rows, gap_rows, unresolved_rows, required_rows):
            plan, result, coverage = original_builder(selected_id, plan_rows, execution_rows, result_rows, gap_rows, unresolved_rows, required_rows)
            return plan[:-1], result, coverage

        module.build_reconciliation_artifacts = incomplete_builder
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["evidence_collection_reconciliation_status"] == "BLOCKED_V20_130_EVIDENCE_COLLECTION_RECONCILIATION"
        assert decision["every_evidence_collection_plan_has_reconciliation_row"] == "FALSE"
        assert decision["v20_131_operator_evidence_review_packet_allowed"] == "FALSE"


def test_missing_blocker_coverage_cannot_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        original_builder = module.build_reconciliation_artifacts

        def incomplete_builder(selected_id, plan_rows, execution_rows, result_rows, gap_rows, unresolved_rows, required_rows):
            plan, result, coverage = original_builder(selected_id, plan_rows, execution_rows, result_rows, gap_rows, unresolved_rows, required_rows)
            return plan, result, coverage[:-1]

        module.build_reconciliation_artifacts = incomplete_builder
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["evidence_collection_reconciliation_status"] == "BLOCKED_V20_130_EVIDENCE_COLLECTION_RECONCILIATION"
        assert decision["every_unresolved_blocker_has_coverage_status"] == "FALSE"
        assert decision["v20_131_operator_evidence_review_packet_allowed"] == "FALSE"


def test_blocked_input_cases_produce_blocked_not_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        gate = read_csv(module.IN_GATE)
        gate[0]["v20_130_evidence_collection_reconciliation_allowed"] = "FALSE"
        write_csv(module.IN_GATE, gate)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["evidence_collection_reconciliation_status"] == "BLOCKED_V20_130_EVIDENCE_COLLECTION_RECONCILIATION"
        assert decision["evidence_collection_reconciliation_status"] != "PASS_V20_130_EVIDENCE_COLLECTION_RECONCILIATION_READY_FOR_V20_131"
        assert decision["v20_131_operator_evidence_review_packet_allowed"] == "FALSE"


def test_evidence_collection_reconciliation() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.129 outputs were mutated"
    stdout = result.stdout
    assert "PASS_V20_130_EVIDENCE_COLLECTION_RECONCILIATION_READY_FOR_V20_131" in stdout
    for expected in [
        "V20_129_GATE_CONSUMED=TRUE",
        "V20_130_EVIDENCE_COLLECTION_RECONCILIATION_ALLOWED_BY_V129=TRUE",
        "V20_129_FINAL_STATUS=PASS_V20_129_ADDITIONAL_EVIDENCE_COLLECTION_DRY_RUN_READY_FOR_V20_130",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "SELECTED_SCENARIO_MATCHES_V20_129=TRUE",
        "EVIDENCE_COLLECTION_PLAN_ROW_COUNT=2",
        "EVIDENCE_PLAN_RECONCILIATION_ROW_COUNT=2",
        "EVERY_EVIDENCE_COLLECTION_PLAN_HAS_RECONCILIATION_ROW=TRUE",
        "EVIDENCE_RESULT_RECONCILIATION_ROW_COUNT=2",
        "UNRESOLVED_BLOCKER_COUNT=2",
        "BLOCKER_EVIDENCE_COVERAGE_ROW_COUNT=2",
        "EVERY_UNRESOLVED_BLOCKER_HAS_COVERAGE_STATUS=TRUE",
        "COVERED_BY_DRY_RUN_EVIDENCE_FOR_REVIEW_COUNT=2",
        "OPERATOR_ACCEPTANCE=FALSE",
        "PROMOTION_READY=FALSE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_131_OPERATOR_EVIDENCE_REVIEW_PACKET_ALLOWED=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"
    decision = read_csv(OUT_DECISION)
    plan_recon = read_csv(OUT_PLAN)
    result_recon = read_csv(OUT_RESULT)
    coverage = read_csv(OUT_COVERAGE)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    plan = read_csv(CONSOLIDATION / "V20_128_EVIDENCE_COLLECTION_PLAN.csv")
    unresolved = [row for row in read_csv(CONSOLIDATION / "V20_127_REMAINING_BLOCKER_RESOLUTION_STATUS.csv") if row["remaining_blocker_requires_review"] == "TRUE"]
    d = decision[0]
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["evidence_collection_reconciliation_status"] == "PASS_V20_130_EVIDENCE_COLLECTION_RECONCILIATION_READY_FOR_V20_131"
    assert d["operator_acceptance"] == "FALSE"
    assert d["promotion_ready"] == "FALSE"
    assert d["v20_131_operator_evidence_review_packet_allowed"] == "TRUE"
    assert len(plan_recon) == len(plan)
    assert {row["source_evidence_collection_plan_id"] for row in plan_recon} == {row["evidence_collection_plan_id"] for row in plan}
    assert all(row["plan_reconciliation_status"] == "RECONCILED_TO_DRY_RUN_EXECUTION" and row["operator_acceptance"] == "FALSE" and row["promotion_ready"] == "FALSE" and row["ticker_rows_created"] == "0" for row in plan_recon)
    assert result_recon
    assert {row["source_evidence_collection_plan_id"] for row in result_recon} == {row["evidence_collection_plan_id"] for row in plan}
    assert coverage
    assert len(coverage) == len(unresolved)
    assert {row["source_remaining_blocker_resolution_status_id"] for row in coverage} == {row["remaining_blocker_resolution_status_id"] for row in unresolved}
    assert all(row["coverage_status"] == "COVERED_BY_DRY_RUN_EVIDENCE_FOR_REVIEW" and row["operator_acceptance"] == "FALSE" and row["promotion_ready"] == "FALSE" for row in coverage)
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["operator_acceptance"] == "FALSE"
    assert gate[0]["promotion_ready"] == "FALSE"
    assert gate[0]["v20_131_operator_evidence_review_packet_allowed"] == "TRUE"
    for rows in [decision, plan_recon, result_recon, coverage, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_missing_plan_reconciliation_cannot_pass()
    test_missing_blocker_coverage_cannot_pass()
    test_blocked_input_cases_produce_blocked_not_pass()
    test_evidence_collection_reconciliation()
    print("PASS_V20_130_EVIDENCE_COLLECTION_RECONCILIATION_TESTS")
