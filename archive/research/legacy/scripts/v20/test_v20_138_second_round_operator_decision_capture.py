#!/usr/bin/env python
"""Tests for V20.138 second-round operator decision capture."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_138_second_round_operator_decision_capture.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
VALID_DECISIONS = {"ACCEPT_SECOND_ROUND_EVIDENCE_WITH_LIMITATION", "REJECT_SECOND_ROUND_EVIDENCE_KEEP_BLOCKED", "REQUEST_THIRD_ROUND_EVIDENCE"}

OUT_DECISION = CONSOLIDATION / "V20_138_SECOND_ROUND_OPERATOR_DECISION_CAPTURE_DECISION.csv"
OUT_RECORD = CONSOLIDATION / "V20_138_SECOND_ROUND_OPERATOR_DECISION_RECORD.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_138_SECOND_ROUND_DECISION_VALIDATION_AUDIT.csv"
OUT_CONSEQUENCE = CONSOLIDATION / "V20_138_SECOND_ROUND_DECISION_CONSEQUENCE_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_138_SECOND_ROUND_OPERATOR_DECISION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_138_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_138_SECOND_ROUND_OPERATOR_DECISION_CAPTURE_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_RECORD, OUT_VALIDATION, OUT_CONSEQUENCE, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    *[CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116", "117", "118", "119", "120", "121", "122", "123", "124", "125", "126", "127", "128", "129", "130", "131", "132", "133", "134", "135", "136", "137"]],
    CONSOLIDATION / "V20_137_SECOND_ROUND_OPERATOR_REVIEW_PACKET_DECISION.csv",
    CONSOLIDATION / "V20_137_SECOND_ROUND_OPERATOR_REVIEW_PACKET.csv",
    CONSOLIDATION / "V20_137_SECOND_ROUND_REVIEW_SUMMARY_AUDIT.csv",
    CONSOLIDATION / "V20_137_SECOND_ROUND_REVIEW_OPTIONS_AUDIT.csv",
    CONSOLIDATION / "V20_137_SECOND_ROUND_OPERATOR_REVIEW_SAFETY_BOUNDARY_AUDIT.csv",
]
REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_137_gate_consumed", "v20_138_second_round_operator_decision_capture_allowed_by_v137", "v20_137_final_status", "selected_repair_scenario_id", "second_round_review_packet_row_count", "second_round_operator_decision_record_count", "every_second_round_review_packet_has_decision_record", "default_request_third_round_evidence_count", "evidence_acceptance", "operator_acceptance", "promotion_ready", "v20_139_third_round_evidence_plan_allowed", "second_round_operator_decision_capture_status"},
    OUT_RECORD: {"source_second_round_operator_review_packet_id", "source_second_round_blocker_coverage_audit_id", "source_remaining_evidence_blocker_status_id", "blocker_category", "second_round_operator_decision", "decision_source", "evidence_acceptance", "operator_acceptance", "decision_status", "blocker_status", "promotion_ready", "ticker_rows_created"},
    OUT_VALIDATION: {"source_second_round_operator_review_packet_id", "blocker_category", "second_round_operator_decision", "decision_available_in_v137_options", "second_round_decision_valid", "conservative_default_used", "explicit_valid_human_second_round_acceptance", "second_round_acceptance_valid", "evidence_acceptance", "operator_acceptance", "promotion_ready"},
    OUT_CONSEQUENCE: {"source_second_round_operator_review_packet_id", "blocker_category", "second_round_operator_decision", "second_round_decision_consequence", "decision_status", "blocker_status", "evidence_acceptance", "operator_acceptance", "promotion_ready"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_137_gate_consumed", "selected_repair_scenario_id", "evidence_acceptance", "operator_acceptance", "promotion_ready", "v20_139_third_round_evidence_plan_allowed", "second_round_operator_decision_capture_status"},
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
    spec = importlib.util.spec_from_file_location("v20_138_second_round_operator_decision_capture_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    mapping = {
        "IN_DECISION": "V20_137_SECOND_ROUND_OPERATOR_REVIEW_PACKET_DECISION.csv",
        "IN_PACKET": "V20_137_SECOND_ROUND_OPERATOR_REVIEW_PACKET.csv",
        "IN_SUMMARY": "V20_137_SECOND_ROUND_REVIEW_SUMMARY_AUDIT.csv",
        "IN_OPTIONS": "V20_137_SECOND_ROUND_REVIEW_OPTIONS_AUDIT.csv",
        "IN_SAFETY": "V20_137_SECOND_ROUND_OPERATOR_REVIEW_SAFETY_BOUNDARY_AUDIT.csv",
        "IN_GATE": "V20_137_NEXT_STAGE_GATE.csv",
    }
    for attr, filename in mapping.items():
        setattr(module, attr, temp / filename)
    module.REQUIRED_INPUTS = [getattr(module, attr) for attr in mapping]
    module.UPSTREAM_HASH_INPUTS = module.REQUIRED_INPUTS
    module.OUT_DECISION = temp / "V20_138_SECOND_ROUND_OPERATOR_DECISION_CAPTURE_DECISION.csv"
    module.OUT_RECORD = temp / "V20_138_SECOND_ROUND_OPERATOR_DECISION_RECORD.csv"
    module.OUT_VALIDATION = temp / "V20_138_SECOND_ROUND_DECISION_VALIDATION_AUDIT.csv"
    module.OUT_CONSEQUENCE = temp / "V20_138_SECOND_ROUND_DECISION_CONSEQUENCE_AUDIT.csv"
    module.OUT_SAFETY = temp / "V20_138_SECOND_ROUND_OPERATOR_DECISION_SAFETY_BOUNDARY_AUDIT.csv"
    module.OUT_GATE = temp / "V20_138_NEXT_STAGE_GATE.csv"
    module.REPORT = temp / "V20_138_SECOND_ROUND_OPERATOR_DECISION_CAPTURE_REPORT.md"


def copy_required_inputs(temp: Path) -> None:
    for filename in [
        "V20_137_SECOND_ROUND_OPERATOR_REVIEW_PACKET_DECISION.csv",
        "V20_137_SECOND_ROUND_OPERATOR_REVIEW_PACKET.csv",
        "V20_137_SECOND_ROUND_REVIEW_SUMMARY_AUDIT.csv",
        "V20_137_SECOND_ROUND_REVIEW_OPTIONS_AUDIT.csv",
        "V20_137_SECOND_ROUND_OPERATOR_REVIEW_SAFETY_BOUNDARY_AUDIT.csv",
        "V20_137_NEXT_STAGE_GATE.csv",
    ]:
        shutil.copy2(CONSOLIDATION / filename, temp / filename)


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        assert module.main() == 0
        blocked = read_csv(module.OUT_DECISION)[0]
        assert blocked["second_round_operator_decision_capture_status"] == "BLOCKED_V20_138_SECOND_ROUND_OPERATOR_DECISION_CAPTURE"
        assert blocked["v20_139_third_round_evidence_plan_allowed"] == "FALSE"
        assert blocked["promotion_ready"] == "FALSE"


def test_missing_decision_record_cannot_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        original_write_all = module.write_all

        def incomplete_write_all(decision, record, validation, consequence, safety, gate):
            original_write_all(decision, record[:-1], validation[:-1], consequence[:-1], safety, gate)

        module.write_all = incomplete_write_all
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["second_round_operator_decision_capture_status"] == "PARTIAL_PASS_V20_138_SECOND_ROUND_DECISIONS_DEFAULT_THIRD_ROUND_READY_FOR_V20_139"
        assert len(read_csv(module.OUT_RECORD)) != len(read_csv(module.IN_PACKET))


def test_accept_without_explicit_evidence_cannot_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        module.DEFAULT_DECISION = "ACCEPT_SECOND_ROUND_EVIDENCE_WITH_LIMITATION"
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        validation = read_csv(module.OUT_VALIDATION)
        assert decision["second_round_operator_decision_capture_status"] == "BLOCKED_V20_138_SECOND_ROUND_OPERATOR_DECISION_CAPTURE"
        assert all(row["second_round_operator_decision"] == "ACCEPT_SECOND_ROUND_EVIDENCE_WITH_LIMITATION" for row in validation)
        assert all(row["explicit_valid_human_second_round_acceptance"] == "FALSE" for row in validation)


def test_blocked_input_cases_produce_blocked_not_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        gate = read_csv(module.IN_GATE)
        gate[0]["v20_138_second_round_operator_decision_capture_allowed"] = "FALSE"
        write_csv(module.IN_GATE, gate)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["second_round_operator_decision_capture_status"] == "BLOCKED_V20_138_SECOND_ROUND_OPERATOR_DECISION_CAPTURE"
        assert decision["v20_139_third_round_evidence_plan_allowed"] == "FALSE"


def test_second_round_operator_decision_capture() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.137 outputs were mutated"
    stdout = result.stdout
    assert "PARTIAL_PASS_V20_138_SECOND_ROUND_DECISIONS_DEFAULT_THIRD_ROUND_READY_FOR_V20_139" in stdout
    for expected in [
        "V20_137_GATE_CONSUMED=TRUE",
        "V20_138_SECOND_ROUND_OPERATOR_DECISION_CAPTURE_ALLOWED_BY_V137=TRUE",
        "V20_137_FINAL_STATUS=PASS_V20_137_SECOND_ROUND_OPERATOR_REVIEW_PACKET_READY_FOR_V20_138",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "SELECTED_SCENARIO_MATCHES_V20_137=TRUE",
        "SECOND_ROUND_REVIEW_PACKET_ROW_COUNT=2",
        "SECOND_ROUND_OPERATOR_DECISION_RECORD_COUNT=2",
        "EVERY_SECOND_ROUND_REVIEW_PACKET_HAS_DECISION_RECORD=TRUE",
        "DEFAULT_REQUEST_THIRD_ROUND_EVIDENCE_COUNT=2",
        "EVIDENCE_ACCEPTANCE=FALSE",
        "OPERATOR_ACCEPTANCE=FALSE",
        "PROMOTION_READY=FALSE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_139_THIRD_ROUND_EVIDENCE_PLAN_ALLOWED=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"
    decision = read_csv(OUT_DECISION)
    record = read_csv(OUT_RECORD)
    validation = read_csv(OUT_VALIDATION)
    consequence = read_csv(OUT_CONSEQUENCE)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    packet = read_csv(CONSOLIDATION / "V20_137_SECOND_ROUND_OPERATOR_REVIEW_PACKET.csv")
    d = decision[0]
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["second_round_operator_decision_capture_status"] == "PARTIAL_PASS_V20_138_SECOND_ROUND_DECISIONS_DEFAULT_THIRD_ROUND_READY_FOR_V20_139"
    assert d["second_round_operator_decision_capture_status"] != "PASS_V20_138_SECOND_ROUND_OPERATOR_DECISION_CAPTURE_READY_FOR_V20_139"
    assert d["evidence_acceptance"] == "FALSE"
    assert d["operator_acceptance"] == "FALSE"
    assert d["promotion_ready"] == "FALSE"
    assert d["v20_139_third_round_evidence_plan_allowed"] == "TRUE"
    assert len(record) == len(packet)
    assert {row["source_second_round_operator_review_packet_id"] for row in record} == {row["second_round_operator_review_packet_id"] for row in packet}
    assert all(row["second_round_operator_decision"] in VALID_DECISIONS for row in record)
    assert all(row["second_round_operator_decision"] == "REQUEST_THIRD_ROUND_EVIDENCE" and row["decision_source"] == "CONSERVATIVE_DEFAULT_NO_EXPLICIT_HUMAN_SECOND_ROUND_ACCEPTANCE" for row in record)
    assert all(row["decision_status"] == "PENDING_THIRD_ROUND_EVIDENCE" and row["blocker_status"] == "UNRESOLVED_OR_PENDING_REVIEW" for row in record)
    assert all(row["evidence_acceptance"] == "FALSE" and row["operator_acceptance"] == "FALSE" and row["promotion_ready"] == "FALSE" for row in record)
    assert validation
    assert all(row["second_round_decision_valid"] == "TRUE" and row["conservative_default_used"] == "TRUE" and row["explicit_valid_human_second_round_acceptance"] == "FALSE" and row["second_round_acceptance_valid"] == "FALSE" for row in validation)
    assert consequence
    assert all(row["decision_status"] == "PENDING_THIRD_ROUND_EVIDENCE" and row["blocker_status"] == "UNRESOLVED_OR_PENDING_REVIEW" for row in consequence)
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["evidence_acceptance"] == "FALSE"
    assert gate[0]["operator_acceptance"] == "FALSE"
    assert gate[0]["promotion_ready"] == "FALSE"
    assert gate[0]["v20_139_third_round_evidence_plan_allowed"] == "TRUE"
    for rows in [decision, record, validation, consequence, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_missing_decision_record_cannot_pass()
    test_accept_without_explicit_evidence_cannot_pass()
    test_blocked_input_cases_produce_blocked_not_pass()
    test_second_round_operator_decision_capture()
    print("PASS_V20_138_SECOND_ROUND_OPERATOR_DECISION_CAPTURE_TESTS")
