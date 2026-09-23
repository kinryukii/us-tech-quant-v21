#!/usr/bin/env python
"""Tests for V20.134 second-round evidence plan."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_134_second_round_evidence_plan.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"

OUT_DECISION = CONSOLIDATION / "V20_134_SECOND_ROUND_EVIDENCE_PLAN_DECISION.csv"
OUT_PLAN = CONSOLIDATION / "V20_134_SECOND_ROUND_EVIDENCE_PLAN.csv"
OUT_REQUIREMENT = CONSOLIDATION / "V20_134_SECOND_ROUND_EVIDENCE_REQUIREMENT_AUDIT.csv"
OUT_PRIORITY = CONSOLIDATION / "V20_134_SECOND_ROUND_EVIDENCE_PRIORITY_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_134_SECOND_ROUND_EVIDENCE_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_134_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_134_SECOND_ROUND_EVIDENCE_PLAN_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_PLAN, OUT_REQUIREMENT, OUT_PRIORITY, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    *[CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116", "117", "118", "119", "120", "121", "122", "123", "124", "125", "126", "127", "128", "129", "130", "131", "132", "133"]],
    CONSOLIDATION / "V20_133_EVIDENCE_DECISION_RESOLUTION_GATE_DECISION.csv",
    CONSOLIDATION / "V20_133_EVIDENCE_DECISION_RESOLUTION_AUDIT.csv",
    CONSOLIDATION / "V20_133_REMAINING_EVIDENCE_BLOCKER_STATUS.csv",
    CONSOLIDATION / "V20_133_REQUIRED_NEXT_EVIDENCE_ACTION_AUDIT.csv",
    CONSOLIDATION / "V20_133_EVIDENCE_DECISION_RESOLUTION_SAFETY_BOUNDARY_AUDIT.csv",
    CONSOLIDATION / "V20_132_OPERATOR_EVIDENCE_DECISION_RECORD.csv",
    CONSOLIDATION / "V20_131_OPERATOR_EVIDENCE_REVIEW_PACKET.csv",
    CONSOLIDATION / "V20_130_BLOCKER_EVIDENCE_COVERAGE_AUDIT.csv",
]
REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_133_gate_consumed", "v20_134_second_round_evidence_plan_allowed_by_v133", "v20_133_final_status", "selected_repair_scenario_id", "unresolved_evidence_blocker_count", "second_round_evidence_plan_row_count", "every_unresolved_evidence_blocker_has_plan_row", "second_round_evidence_requirement_audit_row_count", "second_round_evidence_priority_audit_row_count", "evidence_acceptance", "operator_acceptance", "promotion_ready", "v20_135_second_round_evidence_dry_run_allowed", "second_round_evidence_plan_status"},
    OUT_PLAN: {"source_remaining_evidence_blocker_status_id", "source_evidence_decision_record_id", "source_operator_evidence_review_packet_id", "blocker_category", "prior_evidence_coverage_status", "prior_evidence_decision", "current_resolution_status", "second_round_evidence_requirement", "proposed_second_round_collection_action", "expected_closure_criterion", "priority", "explicit_human_review_still_required", "evidence_acceptance", "operator_acceptance", "promotion_ready", "ticker_rows_created"},
    OUT_REQUIREMENT: {"source_second_round_evidence_plan_id", "source_required_next_evidence_action_audit_id", "source_evidence_decision_record_id", "blocker_category", "prior_evidence_decision", "required_next_evidence_action", "second_round_evidence_requirement", "requirement_status", "evidence_acceptance", "operator_acceptance", "promotion_ready"},
    OUT_PRIORITY: {"source_second_round_evidence_plan_id", "blocker_category", "priority", "priority_rank", "priority_reason", "evidence_acceptance", "operator_acceptance", "promotion_ready"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_133_gate_consumed", "selected_repair_scenario_id", "evidence_acceptance", "operator_acceptance", "promotion_ready", "v20_135_second_round_evidence_dry_run_allowed", "second_round_evidence_plan_status"},
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
    spec = importlib.util.spec_from_file_location("v20_134_second_round_evidence_plan_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    mapping = {
        "IN_DECISION": "V20_133_EVIDENCE_DECISION_RESOLUTION_GATE_DECISION.csv",
        "IN_RESOLUTION": "V20_133_EVIDENCE_DECISION_RESOLUTION_AUDIT.csv",
        "IN_REMAINING": "V20_133_REMAINING_EVIDENCE_BLOCKER_STATUS.csv",
        "IN_REQUIRED_ACTION": "V20_133_REQUIRED_NEXT_EVIDENCE_ACTION_AUDIT.csv",
        "IN_SAFETY": "V20_133_EVIDENCE_DECISION_RESOLUTION_SAFETY_BOUNDARY_AUDIT.csv",
        "IN_GATE": "V20_133_NEXT_STAGE_GATE.csv",
        "IN_RECORD": "V20_132_OPERATOR_EVIDENCE_DECISION_RECORD.csv",
        "IN_PACKET": "V20_131_OPERATOR_EVIDENCE_REVIEW_PACKET.csv",
        "IN_COVERAGE": "V20_130_BLOCKER_EVIDENCE_COVERAGE_AUDIT.csv",
    }
    for attr, filename in mapping.items():
        setattr(module, attr, temp / filename)
    module.REQUIRED_INPUTS = [getattr(module, attr) for attr in mapping]
    module.UPSTREAM_HASH_INPUTS = module.REQUIRED_INPUTS
    module.OUT_DECISION = temp / "V20_134_SECOND_ROUND_EVIDENCE_PLAN_DECISION.csv"
    module.OUT_PLAN = temp / "V20_134_SECOND_ROUND_EVIDENCE_PLAN.csv"
    module.OUT_REQUIREMENT = temp / "V20_134_SECOND_ROUND_EVIDENCE_REQUIREMENT_AUDIT.csv"
    module.OUT_PRIORITY = temp / "V20_134_SECOND_ROUND_EVIDENCE_PRIORITY_AUDIT.csv"
    module.OUT_SAFETY = temp / "V20_134_SECOND_ROUND_EVIDENCE_SAFETY_BOUNDARY_AUDIT.csv"
    module.OUT_GATE = temp / "V20_134_NEXT_STAGE_GATE.csv"
    module.REPORT = temp / "V20_134_SECOND_ROUND_EVIDENCE_PLAN_REPORT.md"


def copy_required_inputs(temp: Path) -> None:
    for filename in [
        "V20_133_EVIDENCE_DECISION_RESOLUTION_GATE_DECISION.csv",
        "V20_133_EVIDENCE_DECISION_RESOLUTION_AUDIT.csv",
        "V20_133_REMAINING_EVIDENCE_BLOCKER_STATUS.csv",
        "V20_133_REQUIRED_NEXT_EVIDENCE_ACTION_AUDIT.csv",
        "V20_133_EVIDENCE_DECISION_RESOLUTION_SAFETY_BOUNDARY_AUDIT.csv",
        "V20_133_NEXT_STAGE_GATE.csv",
        "V20_132_OPERATOR_EVIDENCE_DECISION_RECORD.csv",
        "V20_131_OPERATOR_EVIDENCE_REVIEW_PACKET.csv",
        "V20_130_BLOCKER_EVIDENCE_COVERAGE_AUDIT.csv",
    ]:
        shutil.copy2(CONSOLIDATION / filename, temp / filename)


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        assert module.main() == 0
        blocked = read_csv(module.OUT_DECISION)[0]
        assert blocked["second_round_evidence_plan_status"] == "BLOCKED_V20_134_SECOND_ROUND_EVIDENCE_PLAN"
        assert blocked["v20_135_second_round_evidence_dry_run_allowed"] == "FALSE"
        assert blocked["promotion_ready"] == "FALSE"


def test_missing_plan_row_cannot_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        original_builder = module.build_plan_artifacts

        def incomplete_builder(selected_id, unresolved_rows, action_rows, record_rows, packet_rows, coverage_rows):
            plan, requirement, priority = original_builder(selected_id, unresolved_rows, action_rows, record_rows, packet_rows, coverage_rows)
            return plan[:-1], requirement[:-1], priority[:-1]

        module.build_plan_artifacts = incomplete_builder
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["second_round_evidence_plan_status"] == "BLOCKED_V20_134_SECOND_ROUND_EVIDENCE_PLAN"
        assert decision["every_unresolved_evidence_blocker_has_plan_row"] == "FALSE"
        assert decision["v20_135_second_round_evidence_dry_run_allowed"] == "FALSE"


def test_blocked_input_cases_produce_blocked_not_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        gate = read_csv(module.IN_GATE)
        gate[0]["v20_134_second_round_evidence_plan_allowed"] = "FALSE"
        write_csv(module.IN_GATE, gate)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["second_round_evidence_plan_status"] == "BLOCKED_V20_134_SECOND_ROUND_EVIDENCE_PLAN"
        assert decision["second_round_evidence_plan_status"] != "PASS_V20_134_SECOND_ROUND_EVIDENCE_PLAN_READY_FOR_V20_135"
        assert decision["v20_135_second_round_evidence_dry_run_allowed"] == "FALSE"


def test_second_round_evidence_plan() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.133 outputs were mutated"
    stdout = result.stdout
    assert "PASS_V20_134_SECOND_ROUND_EVIDENCE_PLAN_READY_FOR_V20_135" in stdout
    for expected in [
        "V20_133_GATE_CONSUMED=TRUE",
        "V20_134_SECOND_ROUND_EVIDENCE_PLAN_ALLOWED_BY_V133=TRUE",
        "V20_133_FINAL_STATUS=PARTIAL_PASS_V20_133_ADDITIONAL_EVIDENCE_STILL_REQUIRED_READY_FOR_V20_134",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "SELECTED_SCENARIO_MATCHES_V20_133=TRUE",
        "UNRESOLVED_EVIDENCE_BLOCKER_COUNT=2",
        "SECOND_ROUND_EVIDENCE_PLAN_ROW_COUNT=2",
        "EVERY_UNRESOLVED_EVIDENCE_BLOCKER_HAS_PLAN_ROW=TRUE",
        "SECOND_ROUND_EVIDENCE_REQUIREMENT_AUDIT_ROW_COUNT=2",
        "SECOND_ROUND_EVIDENCE_PRIORITY_AUDIT_ROW_COUNT=2",
        "EVIDENCE_ACCEPTANCE=FALSE",
        "OPERATOR_ACCEPTANCE=FALSE",
        "PROMOTION_READY=FALSE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_135_SECOND_ROUND_EVIDENCE_DRY_RUN_ALLOWED=TRUE",
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
    requirement = read_csv(OUT_REQUIREMENT)
    priority = read_csv(OUT_PRIORITY)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    remaining = [row for row in read_csv(CONSOLIDATION / "V20_133_REMAINING_EVIDENCE_BLOCKER_STATUS.csv") if row["remaining_evidence_review_required"] == "TRUE"]
    d = decision[0]
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["second_round_evidence_plan_status"] == "PASS_V20_134_SECOND_ROUND_EVIDENCE_PLAN_READY_FOR_V20_135"
    assert d["evidence_acceptance"] == "FALSE"
    assert d["operator_acceptance"] == "FALSE"
    assert d["promotion_ready"] == "FALSE"
    assert d["v20_135_second_round_evidence_dry_run_allowed"] == "TRUE"
    assert len(plan) == len(remaining)
    assert {row["source_remaining_evidence_blocker_status_id"] for row in plan} == {row["remaining_evidence_blocker_status_id"] for row in remaining}
    assert all(row["current_resolution_status"] == "NOT_RESOLVED_ADDITIONAL_EVIDENCE_REQUESTED" for row in plan)
    assert all(row["prior_evidence_decision"] == "REQUEST_ADDITIONAL_EVIDENCE" for row in plan)
    assert all(row["explicit_human_review_still_required"] == "TRUE" and row["evidence_acceptance"] == "FALSE" and row["operator_acceptance"] == "FALSE" and row["promotion_ready"] == "FALSE" and row["ticker_rows_created"] == "0" for row in plan)
    assert requirement
    assert priority
    assert {row["source_second_round_evidence_plan_id"] for row in requirement} == {row["second_round_evidence_plan_id"] for row in plan}
    assert {row["source_second_round_evidence_plan_id"] for row in priority} == {row["second_round_evidence_plan_id"] for row in plan}
    assert all(row["evidence_acceptance"] == "FALSE" and row["operator_acceptance"] == "FALSE" and row["promotion_ready"] == "FALSE" for row in requirement + priority)
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["evidence_acceptance"] == "FALSE"
    assert gate[0]["operator_acceptance"] == "FALSE"
    assert gate[0]["promotion_ready"] == "FALSE"
    assert gate[0]["v20_135_second_round_evidence_dry_run_allowed"] == "TRUE"
    for rows in [decision, plan, requirement, priority, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_missing_plan_row_cannot_pass()
    test_blocked_input_cases_produce_blocked_not_pass()
    test_second_round_evidence_plan()
    print("PASS_V20_134_SECOND_ROUND_EVIDENCE_PLAN_TESTS")
