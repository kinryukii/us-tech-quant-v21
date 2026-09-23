#!/usr/bin/env python
"""Tests for V20.128 additional evidence collection plan."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_128_additional_evidence_collection_plan.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"

OUT_DECISION = CONSOLIDATION / "V20_128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN_DECISION.csv"
OUT_PLAN = CONSOLIDATION / "V20_128_EVIDENCE_COLLECTION_PLAN.csv"
OUT_DETAIL = CONSOLIDATION / "V20_128_EVIDENCE_REQUIREMENT_DETAIL_AUDIT.csv"
OUT_PRIORITY = CONSOLIDATION / "V20_128_EVIDENCE_COLLECTION_PRIORITY_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_128_EVIDENCE_COLLECTION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_128_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_PLAN, OUT_DETAIL, OUT_PRIORITY, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    *[CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116", "117", "118", "119", "120", "121", "122", "123", "124", "125", "126", "127"]],
    CONSOLIDATION / "V20_127_OPERATOR_ACTION_RESOLUTION_GATE_DECISION.csv",
    CONSOLIDATION / "V20_127_ACTION_RESOLUTION_AUDIT.csv",
    CONSOLIDATION / "V20_127_REMAINING_BLOCKER_RESOLUTION_STATUS.csv",
    CONSOLIDATION / "V20_127_REQUIRED_NEXT_EVIDENCE_AUDIT.csv",
    CONSOLIDATION / "V20_127_OPERATOR_ACTION_RESOLUTION_SAFETY_BOUNDARY_AUDIT.csv",
]
REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_127_gate_consumed", "v20_128_additional_evidence_collection_plan_allowed_by_v127", "v20_127_final_status", "selected_repair_scenario_id", "unresolved_pending_blocker_count", "evidence_collection_plan_row_count", "every_unresolved_pending_blocker_has_plan_row", "operator_acceptance", "promotion_ready", "v20_129_additional_evidence_collection_dry_run_allowed", "additional_evidence_collection_plan_status"},
    OUT_PLAN: {"source_remaining_blocker_resolution_status_id", "source_action_capture_record_id", "source_operator_decision_record_id", "blocker_category", "current_resolution_status", "missing_evidence_type", "required_evidence_artifact", "proposed_collection_action", "priority", "expected_closure_criterion", "operator_acceptance", "promotion_ready", "ticker_rows_created"},
    OUT_DETAIL: {"source_evidence_collection_plan_id", "source_required_next_evidence_audit_id", "source_action_capture_record_id", "blocker_category", "missing_evidence_type", "required_next_evidence", "required_evidence_artifact", "requirement_detail_status", "promotion_ready"},
    OUT_PRIORITY: {"source_evidence_collection_plan_id", "blocker_category", "priority", "priority_rank", "priority_reason", "promotion_ready"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_127_gate_consumed", "selected_repair_scenario_id", "operator_acceptance", "promotion_ready", "v20_129_additional_evidence_collection_dry_run_allowed", "additional_evidence_collection_plan_status"},
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
    spec = importlib.util.spec_from_file_location("v20_128_additional_evidence_collection_plan_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    mapping = {
        "IN_DECISION": "V20_127_OPERATOR_ACTION_RESOLUTION_GATE_DECISION.csv",
        "IN_ACTION_AUDIT": "V20_127_ACTION_RESOLUTION_AUDIT.csv",
        "IN_REMAINING": "V20_127_REMAINING_BLOCKER_RESOLUTION_STATUS.csv",
        "IN_REQUIRED_EVIDENCE": "V20_127_REQUIRED_NEXT_EVIDENCE_AUDIT.csv",
        "IN_SAFETY": "V20_127_OPERATOR_ACTION_RESOLUTION_SAFETY_BOUNDARY_AUDIT.csv",
        "IN_GATE": "V20_127_NEXT_STAGE_GATE.csv",
    }
    for attr, filename in mapping.items():
        setattr(module, attr, temp / filename)
    module.REQUIRED_INPUTS = [getattr(module, attr) for attr in mapping]
    module.UPSTREAM_HASH_INPUTS = module.REQUIRED_INPUTS
    module.OUT_DECISION = temp / "V20_128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN_DECISION.csv"
    module.OUT_PLAN = temp / "V20_128_EVIDENCE_COLLECTION_PLAN.csv"
    module.OUT_DETAIL = temp / "V20_128_EVIDENCE_REQUIREMENT_DETAIL_AUDIT.csv"
    module.OUT_PRIORITY = temp / "V20_128_EVIDENCE_COLLECTION_PRIORITY_AUDIT.csv"
    module.OUT_SAFETY = temp / "V20_128_EVIDENCE_COLLECTION_SAFETY_BOUNDARY_AUDIT.csv"
    module.OUT_GATE = temp / "V20_128_NEXT_STAGE_GATE.csv"
    module.REPORT = temp / "V20_128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN_REPORT.md"


def copy_required_inputs(temp: Path) -> None:
    for filename in [
        "V20_127_OPERATOR_ACTION_RESOLUTION_GATE_DECISION.csv",
        "V20_127_ACTION_RESOLUTION_AUDIT.csv",
        "V20_127_REMAINING_BLOCKER_RESOLUTION_STATUS.csv",
        "V20_127_REQUIRED_NEXT_EVIDENCE_AUDIT.csv",
        "V20_127_OPERATOR_ACTION_RESOLUTION_SAFETY_BOUNDARY_AUDIT.csv",
        "V20_127_NEXT_STAGE_GATE.csv",
    ]:
        shutil.copy2(CONSOLIDATION / filename, temp / filename)


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        assert module.main() == 0
        blocked = read_csv(module.OUT_DECISION)[0]
        assert blocked["additional_evidence_collection_plan_status"] == "BLOCKED_V20_128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN"
        assert blocked["v20_129_additional_evidence_collection_dry_run_allowed"] == "FALSE"
        assert blocked["promotion_ready"] == "FALSE"


def test_missing_plan_row_cannot_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        original_builder = module.build_plan_artifacts

        def incomplete_builder(selected_id, unresolved_rows, evidence_rows):
            plan, detail, priority = original_builder(selected_id, unresolved_rows, evidence_rows)
            return plan[:-1], detail[:-1], priority[:-1]

        module.build_plan_artifacts = incomplete_builder
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["additional_evidence_collection_plan_status"] == "BLOCKED_V20_128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN"
        assert decision["every_unresolved_pending_blocker_has_plan_row"] == "FALSE"
        assert decision["v20_129_additional_evidence_collection_dry_run_allowed"] == "FALSE"


def test_blocked_input_cases_produce_blocked_not_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        gate = read_csv(module.IN_GATE)
        gate[0]["v20_128_additional_evidence_collection_plan_allowed"] = "FALSE"
        write_csv(module.IN_GATE, gate)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["additional_evidence_collection_plan_status"] == "BLOCKED_V20_128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN"
        assert decision["additional_evidence_collection_plan_status"] != "PASS_V20_128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN_READY_FOR_V20_129"
        assert decision["v20_129_additional_evidence_collection_dry_run_allowed"] == "FALSE"


def test_additional_evidence_collection_plan() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.127 outputs were mutated"
    stdout = result.stdout
    assert "PASS_V20_128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN_READY_FOR_V20_129" in stdout
    for expected in [
        "V20_127_GATE_CONSUMED=TRUE",
        "V20_128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN_ALLOWED_BY_V127=TRUE",
        "V20_127_FINAL_STATUS=PARTIAL_PASS_V20_127_MORE_EVIDENCE_REQUIRED_READY_FOR_V20_128",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "SELECTED_SCENARIO_MATCHES_V20_127=TRUE",
        "UNRESOLVED_PENDING_BLOCKER_COUNT=2",
        "EVIDENCE_COLLECTION_PLAN_ROW_COUNT=2",
        "EVERY_UNRESOLVED_PENDING_BLOCKER_HAS_PLAN_ROW=TRUE",
        "EVIDENCE_REQUIREMENT_DETAIL_AUDIT_ROW_COUNT=2",
        "EVIDENCE_COLLECTION_PRIORITY_AUDIT_ROW_COUNT=2",
        "OPERATOR_ACCEPTANCE=FALSE",
        "PROMOTION_READY=FALSE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_129_ADDITIONAL_EVIDENCE_COLLECTION_DRY_RUN_ALLOWED=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"
    decision = read_csv(OUT_DECISION)
    plan = read_csv(OUT_PLAN)
    detail = read_csv(OUT_DETAIL)
    priority = read_csv(OUT_PRIORITY)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    remaining = [row for row in read_csv(CONSOLIDATION / "V20_127_REMAINING_BLOCKER_RESOLUTION_STATUS.csv") if row["remaining_blocker_requires_review"] == "TRUE"]
    d = decision[0]
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["additional_evidence_collection_plan_status"] == "PASS_V20_128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN_READY_FOR_V20_129"
    assert d["operator_acceptance"] == "FALSE"
    assert d["promotion_ready"] == "FALSE"
    assert d["v20_129_additional_evidence_collection_dry_run_allowed"] == "TRUE"
    assert len(plan) == len(remaining)
    assert {row["source_remaining_blocker_resolution_status_id"] for row in plan} == {row["remaining_blocker_resolution_status_id"] for row in remaining}
    assert all(row["current_resolution_status"] == "NOT_RESOLVED_MORE_EVIDENCE_REQUIRED" for row in plan)
    assert all(row["operator_acceptance"] == "FALSE" and row["promotion_ready"] == "FALSE" and row["ticker_rows_created"] == "0" for row in plan)
    assert detail
    assert priority
    assert {row["source_evidence_collection_plan_id"] for row in detail} == {row["evidence_collection_plan_id"] for row in plan}
    assert {row["source_evidence_collection_plan_id"] for row in priority} == {row["evidence_collection_plan_id"] for row in plan}
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["operator_acceptance"] == "FALSE"
    assert gate[0]["promotion_ready"] == "FALSE"
    assert gate[0]["v20_129_additional_evidence_collection_dry_run_allowed"] == "TRUE"
    for rows in [decision, plan, detail, priority, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_missing_plan_row_cannot_pass()
    test_blocked_input_cases_produce_blocked_not_pass()
    test_additional_evidence_collection_plan()
    print("PASS_V20_128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN_TESTS")
