#!/usr/bin/env python
"""Tests for V20.127 operator action resolution gate."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_127_operator_action_resolution_gate.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_127_operator_action_resolution_gate.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"

OUT_DECISION = CONSOLIDATION / "V20_127_OPERATOR_ACTION_RESOLUTION_GATE_DECISION.csv"
OUT_AUDIT = CONSOLIDATION / "V20_127_ACTION_RESOLUTION_AUDIT.csv"
OUT_REMAINING = CONSOLIDATION / "V20_127_REMAINING_BLOCKER_RESOLUTION_STATUS.csv"
OUT_EVIDENCE = CONSOLIDATION / "V20_127_REQUIRED_NEXT_EVIDENCE_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_127_OPERATOR_ACTION_RESOLUTION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_127_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_127_OPERATOR_ACTION_RESOLUTION_GATE_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_AUDIT, OUT_REMAINING, OUT_EVIDENCE, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    *[CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116", "117", "118", "119", "120", "121", "122", "123", "124", "125", "126"]],
    CONSOLIDATION / "V20_126_OPERATOR_ACTION_CAPTURE_DECISION.csv",
    CONSOLIDATION / "V20_126_OPERATOR_ACTION_CAPTURE_RECORD.csv",
    CONSOLIDATION / "V20_126_OPERATOR_ACTION_VALIDATION_AUDIT.csv",
    CONSOLIDATION / "V20_126_OPERATOR_ACTION_CONSEQUENCE_AUDIT.csv",
    CONSOLIDATION / "V20_126_OPERATOR_ACTION_CAPTURE_SAFETY_BOUNDARY_AUDIT.csv",
    CONSOLIDATION / "V20_125_OPERATOR_ACTION_PACKET.csv",
    CONSOLIDATION / "V20_124_REMAINING_OPERATOR_REVIEW_AUDIT.csv",
]
REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_126_gate_consumed", "v20_127_operator_action_resolution_gate_allowed_by_v126", "v20_126_final_status", "selected_repair_scenario_id", "action_capture_record_count", "action_resolution_audit_row_count", "need_more_evidence_action_count", "not_resolved_more_evidence_required_count", "operator_acceptance", "promotion_ready", "v20_128_additional_evidence_collection_plan_allowed", "operator_action_resolution_gate_status"},
    OUT_AUDIT: {"source_action_capture_record_id", "source_action_packet_id", "source_operator_decision_record_id", "blocker_category", "operator_selected_action", "explicit_valid_human_acceptance_evidence", "operator_acceptance_valid", "resolution_status", "decision_status", "blocker_status", "operator_acceptance", "promotion_ready", "ticker_rows_created"},
    OUT_REMAINING: {"source_action_capture_record_id", "source_operator_decision_record_id", "blocker_category", "resolution_status", "decision_status", "blocker_status", "remaining_blocker_requires_review", "promotion_ready"},
    OUT_EVIDENCE: {"source_action_capture_record_id", "source_action_packet_id", "source_operator_decision_record_id", "blocker_category", "operator_selected_action", "required_next_evidence", "evidence_required_for_v20_128", "promotion_ready"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_126_gate_consumed", "selected_repair_scenario_id", "operator_acceptance", "promotion_ready", "v20_128_additional_evidence_collection_plan_allowed", "operator_action_resolution_gate_status"},
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
    spec = importlib.util.spec_from_file_location("v20_127_operator_action_resolution_gate_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    mapping = {
        "IN_DECISION": "V20_126_OPERATOR_ACTION_CAPTURE_DECISION.csv",
        "IN_RECORD": "V20_126_OPERATOR_ACTION_CAPTURE_RECORD.csv",
        "IN_VALIDATION": "V20_126_OPERATOR_ACTION_VALIDATION_AUDIT.csv",
        "IN_CONSEQUENCE": "V20_126_OPERATOR_ACTION_CONSEQUENCE_AUDIT.csv",
        "IN_SAFETY": "V20_126_OPERATOR_ACTION_CAPTURE_SAFETY_BOUNDARY_AUDIT.csv",
        "IN_GATE": "V20_126_NEXT_STAGE_GATE.csv",
        "IN_PACKET": "V20_125_OPERATOR_ACTION_PACKET.csv",
        "IN_REMAINING": "V20_124_REMAINING_OPERATOR_REVIEW_AUDIT.csv",
    }
    for attr, filename in mapping.items():
        setattr(module, attr, temp / filename)
    module.REQUIRED_INPUTS = [getattr(module, attr) for attr in mapping]
    module.UPSTREAM_HASH_INPUTS = module.REQUIRED_INPUTS
    module.OUT_DECISION = temp / "V20_127_OPERATOR_ACTION_RESOLUTION_GATE_DECISION.csv"
    module.OUT_AUDIT = temp / "V20_127_ACTION_RESOLUTION_AUDIT.csv"
    module.OUT_REMAINING = temp / "V20_127_REMAINING_BLOCKER_RESOLUTION_STATUS.csv"
    module.OUT_EVIDENCE = temp / "V20_127_REQUIRED_NEXT_EVIDENCE_AUDIT.csv"
    module.OUT_SAFETY = temp / "V20_127_OPERATOR_ACTION_RESOLUTION_SAFETY_BOUNDARY_AUDIT.csv"
    module.OUT_GATE = temp / "V20_127_NEXT_STAGE_GATE.csv"
    module.REPORT = temp / "V20_127_OPERATOR_ACTION_RESOLUTION_GATE_REPORT.md"


def copy_required_inputs(temp: Path) -> None:
    for filename in [
        "V20_126_OPERATOR_ACTION_CAPTURE_DECISION.csv",
        "V20_126_OPERATOR_ACTION_CAPTURE_RECORD.csv",
        "V20_126_OPERATOR_ACTION_VALIDATION_AUDIT.csv",
        "V20_126_OPERATOR_ACTION_CONSEQUENCE_AUDIT.csv",
        "V20_126_OPERATOR_ACTION_CAPTURE_SAFETY_BOUNDARY_AUDIT.csv",
        "V20_126_NEXT_STAGE_GATE.csv",
        "V20_125_OPERATOR_ACTION_PACKET.csv",
        "V20_124_REMAINING_OPERATOR_REVIEW_AUDIT.csv",
    ]:
        shutil.copy2(CONSOLIDATION / filename, temp / filename)


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        assert module.main() == 0
        blocked = read_csv(module.OUT_DECISION)[0]
        assert blocked["operator_action_resolution_gate_status"] == "BLOCKED_V20_127_OPERATOR_ACTION_RESOLUTION_GATE"
        assert blocked["v20_128_additional_evidence_collection_plan_allowed"] == "FALSE"
        assert blocked["promotion_ready"] == "FALSE"


def test_accept_with_limitation_missing_evidence_cannot_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        records = read_csv(module.IN_RECORD)
        validations = read_csv(module.IN_VALIDATION)
        for row in records:
            row["operator_selected_action"] = "ACCEPT_WITH_LIMITATION"
            row["captured_operator_action"] = "ACCEPT_WITH_LIMITATION"
        for row in validations:
            row["operator_selected_action"] = "ACCEPT_WITH_LIMITATION"
            row["captured_operator_action"] = "ACCEPT_WITH_LIMITATION"
            row["explicit_valid_human_acceptance_evidence"] = "FALSE"
            row["operator_acceptance_valid"] = "FALSE"
        write_csv(module.IN_RECORD, records)
        write_csv(module.IN_VALIDATION, validations)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        audit = read_csv(module.OUT_AUDIT)
        assert decision["operator_action_resolution_gate_status"] != "PASS_V20_127_OPERATOR_ACTION_RESOLUTION_GATE_READY_FOR_V20_128"
        assert decision["operator_acceptance"] == "FALSE"
        assert decision["promotion_ready"] == "FALSE"
        assert all(row["resolution_status"] == "INVALID_ACCEPTANCE_MISSING_EVIDENCE" for row in audit)


def test_blocked_input_cases_produce_blocked_not_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        gate = read_csv(module.IN_GATE)
        gate[0]["v20_127_operator_action_resolution_gate_allowed"] = "FALSE"
        write_csv(module.IN_GATE, gate)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["operator_action_resolution_gate_status"] == "BLOCKED_V20_127_OPERATOR_ACTION_RESOLUTION_GATE"
        assert decision["operator_action_resolution_gate_status"] != "PASS_V20_127_OPERATOR_ACTION_RESOLUTION_GATE_READY_FOR_V20_128"
        assert decision["v20_128_additional_evidence_collection_plan_allowed"] == "FALSE"


def test_operator_action_resolution_gate() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.126 outputs were mutated"
    stdout = result.stdout
    assert "PARTIAL_PASS_V20_127_MORE_EVIDENCE_REQUIRED_READY_FOR_V20_128" in stdout
    for expected in [
        "V20_126_GATE_CONSUMED=TRUE",
        "V20_127_OPERATOR_ACTION_RESOLUTION_GATE_ALLOWED_BY_V126=TRUE",
        "V20_126_FINAL_STATUS=PARTIAL_PASS_V20_126_OPERATOR_ACTIONS_DEFAULT_MORE_EVIDENCE_READY_FOR_V20_127",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "SELECTED_SCENARIO_MATCHES_V20_126=TRUE",
        "ACTION_CAPTURE_RECORD_COUNT=2",
        "ACTION_RESOLUTION_AUDIT_ROW_COUNT=2",
        "EVERY_ACTION_CAPTURE_RECORD_HAS_RESOLUTION_AUDIT=TRUE",
        "NEED_MORE_EVIDENCE_ACTION_COUNT=2",
        "NOT_RESOLVED_MORE_EVIDENCE_REQUIRED_COUNT=2",
        "REMAINING_BLOCKER_RESOLUTION_STATUS_COUNT=2",
        "REQUIRED_NEXT_EVIDENCE_AUDIT_COUNT=2",
        "OPERATOR_ACCEPTANCE=FALSE",
        "PROMOTION_READY=FALSE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN_ALLOWED=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"
    decision = read_csv(OUT_DECISION)
    audit = read_csv(OUT_AUDIT)
    remaining = read_csv(OUT_REMAINING)
    evidence = read_csv(OUT_EVIDENCE)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    capture = read_csv(CONSOLIDATION / "V20_126_OPERATOR_ACTION_CAPTURE_RECORD.csv")
    d = decision[0]
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["operator_action_resolution_gate_status"] == "PARTIAL_PASS_V20_127_MORE_EVIDENCE_REQUIRED_READY_FOR_V20_128"
    assert d["operator_action_resolution_gate_status"] != "PASS_V20_127_OPERATOR_ACTION_RESOLUTION_GATE_READY_FOR_V20_128"
    assert d["operator_acceptance"] == "FALSE"
    assert d["promotion_ready"] == "FALSE"
    assert d["v20_128_additional_evidence_collection_plan_allowed"] == "TRUE"
    assert len(audit) == len(capture)
    assert {row["source_action_capture_record_id"] for row in audit} == {row["action_capture_record_id"] for row in capture}
    assert all(row["operator_selected_action"] == "NEED_MORE_EVIDENCE" for row in audit)
    assert all(row["resolution_status"] == "NOT_RESOLVED_MORE_EVIDENCE_REQUIRED" and row["decision_status"] == "PENDING_OPERATOR_DECISION" and row["blocker_status"] == "UNRESOLVED_OR_PENDING_REVIEW" for row in audit)
    assert remaining
    assert all(row["remaining_blocker_requires_review"] == "TRUE" and row["promotion_ready"] == "FALSE" for row in remaining)
    assert evidence
    assert len(evidence) == sum(1 for row in capture if row["operator_selected_action"] == "NEED_MORE_EVIDENCE")
    assert all(row["evidence_required_for_v20_128"] == "TRUE" and row["promotion_ready"] == "FALSE" for row in evidence)
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["operator_acceptance"] == "FALSE"
    assert gate[0]["promotion_ready"] == "FALSE"
    assert gate[0]["v20_128_additional_evidence_collection_plan_allowed"] == "TRUE"
    for rows in [decision, audit, remaining, evidence, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_accept_with_limitation_missing_evidence_cannot_pass()
    test_blocked_input_cases_produce_blocked_not_pass()
    test_operator_action_resolution_gate()
    print("PASS_V20_127_OPERATOR_ACTION_RESOLUTION_GATE_TESTS")
