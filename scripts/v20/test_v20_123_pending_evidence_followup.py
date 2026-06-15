#!/usr/bin/env python
"""Tests for V20.123 pending evidence follow-up."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_123_pending_evidence_followup.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"

OUT_DECISION = CONSOLIDATION / "V20_123_PENDING_EVIDENCE_FOLLOWUP_DECISION.csv"
OUT_RESULT = CONSOLIDATION / "V20_123_EVIDENCE_FOLLOWUP_RESULT_AUDIT.csv"
OUT_CLOSURE = CONSOLIDATION / "V20_123_EVIDENCE_GAP_CLOSURE_AUDIT.csv"
OUT_STATUS = CONSOLIDATION / "V20_123_PENDING_DECISION_STATUS_UPDATE_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_123_EVIDENCE_FOLLOWUP_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_123_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_123_PENDING_EVIDENCE_FOLLOWUP_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_RESULT, OUT_CLOSURE, OUT_STATUS, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = [CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116", "117", "118", "119", "120", "121", "122"]]
UPSTREAM.extend([
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    CONSOLIDATION / "V20_122_PENDING_DECISION_RESOLUTION_PLAN_DECISION.csv",
    CONSOLIDATION / "V20_122_PENDING_DECISION_RESOLUTION_PLAN.csv",
    CONSOLIDATION / "V20_122_REQUIRED_EVIDENCE_GAP_AUDIT.csv",
    CONSOLIDATION / "V20_122_REQUIRED_FOLLOWUP_ACTION_AUDIT.csv",
    CONSOLIDATION / "V20_122_RESOLUTION_BOUNDARY_SAFETY_AUDIT.csv",
    CONSOLIDATION / "V20_121_PENDING_DECISION_GATE_AUDIT.csv",
    CONSOLIDATION / "V20_120_OPERATOR_DECISION_RECORD.csv",
    CONSOLIDATION / "V20_118_REMAINING_BLOCKER_AUDIT.csv",
])
REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_122_gate_consumed", "selected_repair_scenario_id", "resolution_plan_row_count", "followup_result_row_count", "every_resolution_plan_has_followup_result", "operator_acceptance_true_count", "promotion_ready", "v20_124_operator_decision_update_allowed", "pending_evidence_followup_status"},
    OUT_RESULT: {"source_resolution_plan_id", "source_operator_decision_record_id", "blocker_category", "followup_execution_mode", "followup_executed", "operator_acceptance", "promotion_ready"},
    OUT_CLOSURE: {"source_evidence_gap_id", "blocker_category", "gap_closure_status", "operator_review_still_required", "promotion_ready"},
    OUT_STATUS: {"source_operator_decision_record_id", "previous_decision_status", "updated_decision_status", "operator_acceptance", "valid_acceptance_evidence", "promotion_ready"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_122_gate_consumed", "selected_repair_scenario_id", "operator_acceptance", "promotion_ready", "v20_124_operator_decision_update_allowed", "pending_evidence_followup_status"},
}
PROHIBITED_FALSE_FIELDS = ["accepted_weight_created", "accepted_weights_created", "real_book_weight_created", "real_book_action_created", "official_weight_created", "official_weights_created", "official_ranking_created", "official_rankings_created", "official_recommendation_created", "official_recommendations_created", "trade_action_created", "trade_actions_created", "broker_action_created", "broker_actions_created", "authoritative_overwrite_created", "authoritative_overwrites_created", "authoritative_ranking_overwritten", "weight_mutated", "weight_mutations_created", "performance_claim_created", "performance_claims_created", "performance_effectiveness_claim_created", "official_promotion_allowed", "is_official_weight", "promotion_ready"]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def upstream_hashes() -> dict[Path, str]:
    return {path: digest(path) for path in UPSTREAM if path.exists()}


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    bad = [row for row in rows if row.get(field) not in {"", "FALSE"}]
    assert not bad, f"{field} was not FALSE: {bad[:3]}"


def load_module():
    spec = importlib.util.spec_from_file_location("v20_123_pending_evidence_followup_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        for name in ["IN_DECISION", "IN_PLAN", "IN_GAP", "IN_FOLLOWUP", "IN_SAFETY", "IN_GATE", "IN_V121_PENDING", "IN_V120_RECORD", "IN_V118_REMAINING"]:
            setattr(module, name, temp / f"missing_{name}.csv")
        module.REQUIRED_INPUTS = [module.IN_DECISION, module.IN_PLAN, module.IN_GAP, module.IN_FOLLOWUP, module.IN_SAFETY, module.IN_GATE, module.IN_V121_PENDING, module.IN_V120_RECORD, module.IN_V118_REMAINING]
        module.OUT_DECISION = temp / "V20_123_PENDING_EVIDENCE_FOLLOWUP_DECISION.csv"
        module.OUT_RESULT = temp / "V20_123_EVIDENCE_FOLLOWUP_RESULT_AUDIT.csv"
        module.OUT_CLOSURE = temp / "V20_123_EVIDENCE_GAP_CLOSURE_AUDIT.csv"
        module.OUT_STATUS = temp / "V20_123_PENDING_DECISION_STATUS_UPDATE_AUDIT.csv"
        module.OUT_SAFETY = temp / "V20_123_EVIDENCE_FOLLOWUP_SAFETY_BOUNDARY_AUDIT.csv"
        module.OUT_GATE = temp / "V20_123_NEXT_STAGE_GATE.csv"
        module.REPORT = temp / "V20_123_PENDING_EVIDENCE_FOLLOWUP_REPORT.md"
        assert module.main() == 0
        blocked = read_csv(module.OUT_DECISION)[0]
        assert blocked["pending_evidence_followup_status"] == "BLOCKED_V20_123_PENDING_EVIDENCE_FOLLOWUP"
        assert blocked["promotion_ready"] == "FALSE"


def test_pending_evidence_followup() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.122 outputs were mutated"
    stdout = result.stdout
    assert "PARTIAL_PASS_V20_123_EVIDENCE_PARTIALLY_CLOSED_READY_FOR_V20_124" in stdout
    for expected in [
        "V20_122_GATE_CONSUMED=TRUE",
        "V20_123_PENDING_EVIDENCE_FOLLOWUP_ALLOWED_BY_V122=TRUE",
        "V20_122_FINAL_STATUS=PASS_V20_122_PENDING_DECISION_RESOLUTION_PLAN_READY_FOR_V20_123",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "SELECTED_SCENARIO_MATCHES_V20_122=TRUE",
        "RESOLUTION_PLAN_ROW_COUNT=2",
        "FOLLOWUP_RESULT_ROW_COUNT=2",
        "EVERY_RESOLUTION_PLAN_HAS_FOLLOWUP_RESULT=TRUE",
        "EVIDENCE_GAP_CLOSURE_ROW_COUNT=2",
        "PENDING_DECISION_STATUS_UPDATE_ROW_COUNT=2",
        "OPERATOR_ACCEPTANCE_TRUE_COUNT=0",
        "PROMOTION_READY=FALSE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_124_OPERATOR_DECISION_UPDATE_ALLOWED=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"
    decision = read_csv(OUT_DECISION)
    result_rows = read_csv(OUT_RESULT)
    closure = read_csv(OUT_CLOSURE)
    status = read_csv(OUT_STATUS)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    d = decision[0]
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["promotion_ready"] == "FALSE"
    assert d["operator_acceptance_true_count"] == "0"
    assert d["pending_evidence_followup_status"] == "PARTIAL_PASS_V20_123_EVIDENCE_PARTIALLY_CLOSED_READY_FOR_V20_124"
    assert len(result_rows) == 2
    assert len(closure) == 2
    assert len(status) == 2
    assert all(row["followup_executed"] == "TRUE" and row["operator_acceptance"] == "FALSE" and row["promotion_ready"] == "FALSE" for row in result_rows)
    assert all(row["gap_closure_status"] in {"CLOSED_BY_EXISTING_SHADOW_EVIDENCE", "PARTIALLY_CLOSED_NEEDS_OPERATOR_REVIEW", "STILL_OPEN_NEEDS_MORE_EVIDENCE"} for row in closure)
    assert all(row["operator_acceptance"] == "FALSE" and row["updated_decision_status"] == "PENDING_OPERATOR_DECISION" and row["promotion_ready"] == "FALSE" for row in status)
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["operator_acceptance"] == "FALSE"
    assert gate[0]["promotion_ready"] == "FALSE"
    assert gate[0]["v20_124_operator_decision_update_allowed"] == "TRUE"
    every_plan_has_result = d["every_resolution_plan_has_followup_result"] == "TRUE"
    assert d["pending_evidence_followup_status"].startswith("PASS_") == (every_plan_has_result and d["partially_closed_gap_count"] == "0" and d["still_open_gap_count"] == "0")
    for rows in [decision, result_rows, closure, status, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_pending_evidence_followup()
    print("PASS_V20_123_PENDING_EVIDENCE_FOLLOWUP_TESTS")
