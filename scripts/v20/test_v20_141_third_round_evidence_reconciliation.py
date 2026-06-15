#!/usr/bin/env python
"""Tests for V20.141 third-round evidence reconciliation."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_141_third_round_evidence_reconciliation.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"

OUT_DECISION = CONSOLIDATION / "V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_DECISION.csv"
OUT_PLAN = CONSOLIDATION / "V20_141_THIRD_ROUND_PLAN_RECONCILIATION_AUDIT.csv"
OUT_RESULT = CONSOLIDATION / "V20_141_THIRD_ROUND_RESULT_RECONCILIATION_AUDIT.csv"
OUT_COVERAGE = CONSOLIDATION / "V20_141_THIRD_ROUND_BLOCKER_COVERAGE_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_141_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_PLAN, OUT_RESULT, OUT_COVERAGE, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = sorted(
    path
    for path in CONSOLIDATION.glob("V20_*")
    if path.is_file() and any(path.name.startswith(f"V20_{stage}_") for stage in range(109, 141))
)
REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_140_gate_consumed", "v20_141_third_round_evidence_reconciliation_allowed_by_v140", "v20_140_final_status", "selected_repair_scenario_id", "third_round_evidence_plan_row_count", "third_round_plan_reconciliation_row_count", "every_third_round_evidence_plan_has_reconciliation_row", "third_round_result_reconciliation_row_count", "unresolved_evidence_blocker_count", "third_round_blocker_coverage_row_count", "every_unresolved_evidence_blocker_has_coverage_status", "evidence_acceptance", "operator_acceptance", "promotion_ready", "v20_142_third_round_operator_review_packet_allowed", "third_round_evidence_reconciliation_status"},
    OUT_PLAN: {"source_third_round_evidence_plan_id", "source_third_round_evidence_execution_audit_id", "source_remaining_evidence_blocker_status_id", "blocker_category", "plan_reconciliation_status", "third_round_evidence_requirement", "evidence_acceptance", "operator_acceptance", "promotion_ready", "ticker_rows_created"},
    OUT_RESULT: {"source_third_round_evidence_plan_id", "source_third_round_evidence_result_audit_id", "source_third_round_gap_status_audit_id", "blocker_category", "dry_run_result_status", "gap_status", "result_reconciliation_status", "evidence_acceptance", "operator_acceptance", "promotion_ready"},
    OUT_COVERAGE: {"source_remaining_evidence_blocker_status_id", "source_second_round_operator_decision_record_id", "source_operator_decision_record_id", "source_third_round_evidence_plan_id", "source_third_round_evidence_result_audit_id", "blocker_category", "coverage_status", "coverage_reason", "evidence_acceptance", "operator_acceptance", "promotion_ready"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_140_gate_consumed", "selected_repair_scenario_id", "evidence_acceptance", "operator_acceptance", "promotion_ready", "v20_142_third_round_operator_review_packet_allowed", "third_round_evidence_reconciliation_status"},
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
    spec = importlib.util.spec_from_file_location("v20_141_third_round_evidence_reconciliation_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    mapping = {
        "IN_DECISION": "V20_140_THIRD_ROUND_EVIDENCE_DRY_RUN_DECISION.csv",
        "IN_EXECUTION": "V20_140_THIRD_ROUND_EVIDENCE_EXECUTION_AUDIT.csv",
        "IN_RESULT": "V20_140_THIRD_ROUND_EVIDENCE_RESULT_AUDIT.csv",
        "IN_GAP": "V20_140_THIRD_ROUND_EVIDENCE_GAP_STATUS_AUDIT.csv",
        "IN_SAFETY": "V20_140_THIRD_ROUND_EVIDENCE_SAFETY_BOUNDARY_AUDIT.csv",
        "IN_GATE": "V20_140_NEXT_STAGE_GATE.csv",
        "IN_PLAN": "V20_139_THIRD_ROUND_EVIDENCE_PLAN.csv",
        "IN_REQUIREMENT": "V20_139_THIRD_ROUND_EVIDENCE_REQUIREMENT_AUDIT.csv",
        "IN_V138_RECORD": "V20_138_SECOND_ROUND_OPERATOR_DECISION_RECORD.csv",
        "IN_V133_REMAINING": "V20_133_REMAINING_EVIDENCE_BLOCKER_STATUS.csv",
    }
    for attr, filename in mapping.items():
        setattr(module, attr, temp / filename)
    module.REQUIRED_INPUTS = [getattr(module, attr) for attr in mapping]
    module.UPSTREAM_HASH_INPUTS = module.REQUIRED_INPUTS
    module.OUT_DECISION = temp / "V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_DECISION.csv"
    module.OUT_PLAN = temp / "V20_141_THIRD_ROUND_PLAN_RECONCILIATION_AUDIT.csv"
    module.OUT_RESULT = temp / "V20_141_THIRD_ROUND_RESULT_RECONCILIATION_AUDIT.csv"
    module.OUT_COVERAGE = temp / "V20_141_THIRD_ROUND_BLOCKER_COVERAGE_AUDIT.csv"
    module.OUT_SAFETY = temp / "V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_SAFETY_BOUNDARY_AUDIT.csv"
    module.OUT_GATE = temp / "V20_141_NEXT_STAGE_GATE.csv"
    module.REPORT = temp / "V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_REPORT.md"


def copy_required_inputs(temp: Path) -> None:
    for filename in [
        "V20_140_THIRD_ROUND_EVIDENCE_DRY_RUN_DECISION.csv",
        "V20_140_THIRD_ROUND_EVIDENCE_EXECUTION_AUDIT.csv",
        "V20_140_THIRD_ROUND_EVIDENCE_RESULT_AUDIT.csv",
        "V20_140_THIRD_ROUND_EVIDENCE_GAP_STATUS_AUDIT.csv",
        "V20_140_THIRD_ROUND_EVIDENCE_SAFETY_BOUNDARY_AUDIT.csv",
        "V20_140_NEXT_STAGE_GATE.csv",
        "V20_139_THIRD_ROUND_EVIDENCE_PLAN.csv",
        "V20_139_THIRD_ROUND_EVIDENCE_REQUIREMENT_AUDIT.csv",
        "V20_138_SECOND_ROUND_OPERATOR_DECISION_RECORD.csv",
        "V20_133_REMAINING_EVIDENCE_BLOCKER_STATUS.csv",
    ]:
        shutil.copy2(CONSOLIDATION / filename, temp / filename)


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        assert module.main() == 0
        blocked = read_csv(module.OUT_DECISION)[0]
        assert blocked["third_round_evidence_reconciliation_status"] == "BLOCKED_V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION"
        assert blocked["v20_142_third_round_operator_review_packet_allowed"] == "FALSE"
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
        assert decision["third_round_evidence_reconciliation_status"] == "BLOCKED_V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION"
        assert decision["every_third_round_evidence_plan_has_reconciliation_row"] == "FALSE"
        assert decision["v20_142_third_round_operator_review_packet_allowed"] == "FALSE"


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
        assert decision["third_round_evidence_reconciliation_status"] == "BLOCKED_V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION"
        assert decision["every_unresolved_evidence_blocker_has_coverage_status"] == "FALSE"
        assert decision["v20_142_third_round_operator_review_packet_allowed"] == "FALSE"


def test_blocked_input_cases_produce_blocked_not_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        gate = read_csv(module.IN_GATE)
        gate[0]["v20_141_third_round_evidence_reconciliation_allowed"] = "FALSE"
        write_csv(module.IN_GATE, gate)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["third_round_evidence_reconciliation_status"] == "BLOCKED_V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION"
        assert decision["third_round_evidence_reconciliation_status"] != "PASS_V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_READY_FOR_V20_142"
        assert decision["v20_142_third_round_operator_review_packet_allowed"] == "FALSE"


def test_third_round_evidence_reconciliation() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.140 outputs were mutated"
    stdout = result.stdout
    assert "PASS_V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_READY_FOR_V20_142" in stdout
    for expected in [
        "V20_140_GATE_CONSUMED=TRUE",
        "V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_ALLOWED_BY_V140=TRUE",
        "V20_140_FINAL_STATUS=PASS_V20_140_THIRD_ROUND_EVIDENCE_DRY_RUN_READY_FOR_V20_141",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "SELECTED_SCENARIO_MATCHES_V20_140=TRUE",
        "THIRD_ROUND_EVIDENCE_PLAN_ROW_COUNT=2",
        "THIRD_ROUND_PLAN_RECONCILIATION_ROW_COUNT=2",
        "EVERY_THIRD_ROUND_EVIDENCE_PLAN_HAS_RECONCILIATION_ROW=TRUE",
        "THIRD_ROUND_RESULT_RECONCILIATION_ROW_COUNT=2",
        "UNRESOLVED_EVIDENCE_BLOCKER_COUNT=2",
        "THIRD_ROUND_BLOCKER_COVERAGE_ROW_COUNT=2",
        "EVERY_UNRESOLVED_EVIDENCE_BLOCKER_HAS_COVERAGE_STATUS=TRUE",
        "THIRD_ROUND_COVERED_BY_EVIDENCE_FOR_REVIEW_COUNT=2",
        "EVIDENCE_ACCEPTANCE=FALSE",
        "OPERATOR_ACCEPTANCE=FALSE",
        "PROMOTION_READY=FALSE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_142_THIRD_ROUND_OPERATOR_REVIEW_PACKET_ALLOWED=TRUE",
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
    plan = read_csv(CONSOLIDATION / "V20_139_THIRD_ROUND_EVIDENCE_PLAN.csv")
    unresolved = [row for row in read_csv(CONSOLIDATION / "V20_133_REMAINING_EVIDENCE_BLOCKER_STATUS.csv") if row["remaining_evidence_review_required"] == "TRUE"]
    d = decision[0]
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["third_round_evidence_reconciliation_status"] == "PASS_V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_READY_FOR_V20_142"
    assert d["evidence_acceptance"] == "FALSE"
    assert d["operator_acceptance"] == "FALSE"
    assert d["promotion_ready"] == "FALSE"
    assert d["v20_142_third_round_operator_review_packet_allowed"] == "TRUE"
    assert len(plan_recon) == len(plan)
    assert {row["source_third_round_evidence_plan_id"] for row in plan_recon} == {row["third_round_evidence_plan_id"] for row in plan}
    assert all(row["plan_reconciliation_status"] == "RECONCILED_TO_THIRD_ROUND_DRY_RUN_EXECUTION" and row["evidence_acceptance"] == "FALSE" and row["operator_acceptance"] == "FALSE" and row["promotion_ready"] == "FALSE" and row["ticker_rows_created"] == "0" for row in plan_recon)
    assert result_recon
    assert {row["source_third_round_evidence_plan_id"] for row in result_recon} == {row["third_round_evidence_plan_id"] for row in plan}
    assert coverage
    assert len(coverage) == len(unresolved)
    assert {row["source_remaining_evidence_blocker_status_id"] for row in coverage} == {row["remaining_evidence_blocker_status_id"] for row in unresolved}
    assert all(row["coverage_status"] == "THIRD_ROUND_COVERED_BY_EVIDENCE_FOR_REVIEW" and row["evidence_acceptance"] == "FALSE" and row["operator_acceptance"] == "FALSE" and row["promotion_ready"] == "FALSE" for row in coverage)
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["evidence_acceptance"] == "FALSE"
    assert gate[0]["operator_acceptance"] == "FALSE"
    assert gate[0]["promotion_ready"] == "FALSE"
    assert gate[0]["v20_142_third_round_operator_review_packet_allowed"] == "TRUE"
    for rows in [decision, plan_recon, result_recon, coverage, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_missing_plan_reconciliation_cannot_pass()
    test_missing_blocker_coverage_cannot_pass()
    test_blocked_input_cases_produce_blocked_not_pass()
    test_third_round_evidence_reconciliation()
    print("PASS_V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_TESTS")

