#!/usr/bin/env python
"""Tests for V20.133 evidence decision resolution gate."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_133_evidence_decision_resolution_gate.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"

OUT_DECISION = CONSOLIDATION / "V20_133_EVIDENCE_DECISION_RESOLUTION_GATE_DECISION.csv"
OUT_AUDIT = CONSOLIDATION / "V20_133_EVIDENCE_DECISION_RESOLUTION_AUDIT.csv"
OUT_REMAINING = CONSOLIDATION / "V20_133_REMAINING_EVIDENCE_BLOCKER_STATUS.csv"
OUT_EVIDENCE = CONSOLIDATION / "V20_133_REQUIRED_NEXT_EVIDENCE_ACTION_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_133_EVIDENCE_DECISION_RESOLUTION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_133_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_133_EVIDENCE_DECISION_RESOLUTION_GATE_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_AUDIT, OUT_REMAINING, OUT_EVIDENCE, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    *[CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116", "117", "118", "119", "120", "121", "122", "123", "124", "125", "126", "127", "128", "129", "130", "131", "132"]],
    CONSOLIDATION / "V20_132_OPERATOR_EVIDENCE_DECISION_CAPTURE_DECISION.csv",
    CONSOLIDATION / "V20_132_OPERATOR_EVIDENCE_DECISION_RECORD.csv",
    CONSOLIDATION / "V20_132_EVIDENCE_DECISION_VALIDATION_AUDIT.csv",
    CONSOLIDATION / "V20_132_EVIDENCE_DECISION_CONSEQUENCE_AUDIT.csv",
    CONSOLIDATION / "V20_132_OPERATOR_EVIDENCE_DECISION_SAFETY_BOUNDARY_AUDIT.csv",
    CONSOLIDATION / "V20_131_OPERATOR_EVIDENCE_REVIEW_PACKET.csv",
    CONSOLIDATION / "V20_130_BLOCKER_EVIDENCE_COVERAGE_AUDIT.csv",
]
REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_132_gate_consumed", "v20_133_evidence_decision_resolution_gate_allowed_by_v132", "v20_132_final_status", "selected_repair_scenario_id", "evidence_decision_record_count", "evidence_decision_resolution_audit_row_count", "every_evidence_decision_record_has_resolution_audit", "request_additional_evidence_decision_count", "not_resolved_additional_evidence_requested_count", "evidence_acceptance", "operator_acceptance", "promotion_ready", "v20_134_second_round_evidence_plan_allowed", "evidence_decision_resolution_gate_status"},
    OUT_AUDIT: {"source_evidence_decision_record_id", "source_operator_evidence_review_packet_id", "source_remaining_blocker_resolution_status_id", "blocker_category", "operator_evidence_decision", "explicit_valid_human_evidence_acceptance", "evidence_acceptance_valid", "resolution_status", "evidence_decision_status", "blocker_status", "evidence_acceptance", "operator_acceptance", "promotion_ready", "ticker_rows_created"},
    OUT_REMAINING: {"source_evidence_decision_record_id", "source_remaining_blocker_resolution_status_id", "blocker_category", "resolution_status", "evidence_decision_status", "blocker_status", "remaining_evidence_review_required", "evidence_acceptance", "operator_acceptance", "promotion_ready"},
    OUT_EVIDENCE: {"source_evidence_decision_record_id", "source_operator_evidence_review_packet_id", "source_remaining_blocker_resolution_status_id", "blocker_category", "operator_evidence_decision", "required_next_evidence_action", "evidence_required_for_v20_134", "evidence_acceptance", "operator_acceptance", "promotion_ready"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_132_gate_consumed", "selected_repair_scenario_id", "evidence_acceptance", "operator_acceptance", "promotion_ready", "v20_134_second_round_evidence_plan_allowed", "evidence_decision_resolution_gate_status"},
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
    spec = importlib.util.spec_from_file_location("v20_133_evidence_decision_resolution_gate_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    mapping = {
        "IN_DECISION": "V20_132_OPERATOR_EVIDENCE_DECISION_CAPTURE_DECISION.csv",
        "IN_RECORD": "V20_132_OPERATOR_EVIDENCE_DECISION_RECORD.csv",
        "IN_VALIDATION": "V20_132_EVIDENCE_DECISION_VALIDATION_AUDIT.csv",
        "IN_CONSEQUENCE": "V20_132_EVIDENCE_DECISION_CONSEQUENCE_AUDIT.csv",
        "IN_SAFETY": "V20_132_OPERATOR_EVIDENCE_DECISION_SAFETY_BOUNDARY_AUDIT.csv",
        "IN_GATE": "V20_132_NEXT_STAGE_GATE.csv",
        "IN_PACKET": "V20_131_OPERATOR_EVIDENCE_REVIEW_PACKET.csv",
        "IN_COVERAGE": "V20_130_BLOCKER_EVIDENCE_COVERAGE_AUDIT.csv",
    }
    for attr, filename in mapping.items():
        setattr(module, attr, temp / filename)
    module.REQUIRED_INPUTS = [getattr(module, attr) for attr in mapping]
    module.UPSTREAM_HASH_INPUTS = module.REQUIRED_INPUTS
    module.OUT_DECISION = temp / "V20_133_EVIDENCE_DECISION_RESOLUTION_GATE_DECISION.csv"
    module.OUT_AUDIT = temp / "V20_133_EVIDENCE_DECISION_RESOLUTION_AUDIT.csv"
    module.OUT_REMAINING = temp / "V20_133_REMAINING_EVIDENCE_BLOCKER_STATUS.csv"
    module.OUT_EVIDENCE = temp / "V20_133_REQUIRED_NEXT_EVIDENCE_ACTION_AUDIT.csv"
    module.OUT_SAFETY = temp / "V20_133_EVIDENCE_DECISION_RESOLUTION_SAFETY_BOUNDARY_AUDIT.csv"
    module.OUT_GATE = temp / "V20_133_NEXT_STAGE_GATE.csv"
    module.REPORT = temp / "V20_133_EVIDENCE_DECISION_RESOLUTION_GATE_REPORT.md"


def copy_required_inputs(temp: Path) -> None:
    for filename in [
        "V20_132_OPERATOR_EVIDENCE_DECISION_CAPTURE_DECISION.csv",
        "V20_132_OPERATOR_EVIDENCE_DECISION_RECORD.csv",
        "V20_132_EVIDENCE_DECISION_VALIDATION_AUDIT.csv",
        "V20_132_EVIDENCE_DECISION_CONSEQUENCE_AUDIT.csv",
        "V20_132_OPERATOR_EVIDENCE_DECISION_SAFETY_BOUNDARY_AUDIT.csv",
        "V20_132_NEXT_STAGE_GATE.csv",
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
        assert blocked["evidence_decision_resolution_gate_status"] == "BLOCKED_V20_133_EVIDENCE_DECISION_RESOLUTION_GATE"
        assert blocked["v20_134_second_round_evidence_plan_allowed"] == "FALSE"
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
            row["operator_evidence_decision"] = "ACCEPT_EVIDENCE_WITH_LIMITATION"
            row["evidence_acceptance"] = "FALSE"
        for row in validations:
            row["operator_evidence_decision"] = "ACCEPT_EVIDENCE_WITH_LIMITATION"
            row["explicit_valid_human_evidence_acceptance"] = "FALSE"
            row["evidence_acceptance_valid"] = "FALSE"
        write_csv(module.IN_RECORD, records)
        write_csv(module.IN_VALIDATION, validations)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        audit = read_csv(module.OUT_AUDIT)
        assert decision["evidence_decision_resolution_gate_status"] != "PASS_V20_133_EVIDENCE_DECISION_RESOLUTION_GATE_READY_FOR_V20_134"
        assert decision["evidence_acceptance"] == "FALSE"
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
        gate[0]["v20_133_evidence_decision_resolution_gate_allowed"] = "FALSE"
        write_csv(module.IN_GATE, gate)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["evidence_decision_resolution_gate_status"] == "BLOCKED_V20_133_EVIDENCE_DECISION_RESOLUTION_GATE"
        assert decision["evidence_decision_resolution_gate_status"] != "PASS_V20_133_EVIDENCE_DECISION_RESOLUTION_GATE_READY_FOR_V20_134"
        assert decision["v20_134_second_round_evidence_plan_allowed"] == "FALSE"


def test_evidence_decision_resolution_gate() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.132 outputs were mutated"
    stdout = result.stdout
    assert "PARTIAL_PASS_V20_133_ADDITIONAL_EVIDENCE_STILL_REQUIRED_READY_FOR_V20_134" in stdout
    for expected in [
        "V20_132_GATE_CONSUMED=TRUE",
        "V20_133_EVIDENCE_DECISION_RESOLUTION_GATE_ALLOWED_BY_V132=TRUE",
        "V20_132_FINAL_STATUS=PARTIAL_PASS_V20_132_EVIDENCE_DECISIONS_DEFAULT_MORE_EVIDENCE_READY_FOR_V20_133",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "SELECTED_SCENARIO_MATCHES_V20_132=TRUE",
        "EVIDENCE_DECISION_RECORD_COUNT=2",
        "EVIDENCE_DECISION_RESOLUTION_AUDIT_ROW_COUNT=2",
        "EVERY_EVIDENCE_DECISION_RECORD_HAS_RESOLUTION_AUDIT=TRUE",
        "REQUEST_ADDITIONAL_EVIDENCE_DECISION_COUNT=2",
        "NOT_RESOLVED_ADDITIONAL_EVIDENCE_REQUESTED_COUNT=2",
        "REMAINING_EVIDENCE_BLOCKER_STATUS_COUNT=2",
        "REQUIRED_NEXT_EVIDENCE_ACTION_AUDIT_COUNT=2",
        "EVIDENCE_ACCEPTANCE=FALSE",
        "OPERATOR_ACCEPTANCE=FALSE",
        "PROMOTION_READY=FALSE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_134_SECOND_ROUND_EVIDENCE_PLAN_ALLOWED=TRUE",
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
    records = read_csv(CONSOLIDATION / "V20_132_OPERATOR_EVIDENCE_DECISION_RECORD.csv")
    d = decision[0]
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["evidence_decision_resolution_gate_status"] == "PARTIAL_PASS_V20_133_ADDITIONAL_EVIDENCE_STILL_REQUIRED_READY_FOR_V20_134"
    assert d["evidence_decision_resolution_gate_status"] != "PASS_V20_133_EVIDENCE_DECISION_RESOLUTION_GATE_READY_FOR_V20_134"
    assert d["evidence_acceptance"] == "FALSE"
    assert d["operator_acceptance"] == "FALSE"
    assert d["promotion_ready"] == "FALSE"
    assert d["v20_134_second_round_evidence_plan_allowed"] == "TRUE"
    assert len(audit) == len(records)
    assert {row["source_evidence_decision_record_id"] for row in audit} == {row["evidence_decision_record_id"] for row in records}
    assert all(row["operator_evidence_decision"] == "REQUEST_ADDITIONAL_EVIDENCE" for row in audit)
    assert all(row["resolution_status"] == "NOT_RESOLVED_ADDITIONAL_EVIDENCE_REQUESTED" and row["evidence_decision_status"] == "PENDING_MORE_EVIDENCE" and row["blocker_status"] == "UNRESOLVED_OR_PENDING_REVIEW" for row in audit)
    assert remaining
    assert all(row["remaining_evidence_review_required"] == "TRUE" and row["evidence_acceptance"] == "FALSE" and row["operator_acceptance"] == "FALSE" and row["promotion_ready"] == "FALSE" for row in remaining)
    assert evidence
    assert len(evidence) == sum(1 for row in records if row["operator_evidence_decision"] == "REQUEST_ADDITIONAL_EVIDENCE")
    assert all(row["evidence_required_for_v20_134"] == "TRUE" and row["evidence_acceptance"] == "FALSE" and row["operator_acceptance"] == "FALSE" and row["promotion_ready"] == "FALSE" for row in evidence)
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["evidence_acceptance"] == "FALSE"
    assert gate[0]["operator_acceptance"] == "FALSE"
    assert gate[0]["promotion_ready"] == "FALSE"
    assert gate[0]["v20_134_second_round_evidence_plan_allowed"] == "TRUE"
    for rows in [decision, audit, remaining, evidence, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_accept_with_limitation_missing_evidence_cannot_pass()
    test_blocked_input_cases_produce_blocked_not_pass()
    test_evidence_decision_resolution_gate()
    print("PASS_V20_133_EVIDENCE_DECISION_RESOLUTION_GATE_TESTS")
