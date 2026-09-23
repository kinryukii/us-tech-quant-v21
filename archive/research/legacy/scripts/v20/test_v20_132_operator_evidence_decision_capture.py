#!/usr/bin/env python
"""Tests for V20.132 operator evidence decision capture."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_132_operator_evidence_decision_capture.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
VALID_DECISIONS = {"ACCEPT_EVIDENCE_WITH_LIMITATION", "REJECT_EVIDENCE_KEEP_BLOCKED", "REQUEST_ADDITIONAL_EVIDENCE"}

OUT_DECISION = CONSOLIDATION / "V20_132_OPERATOR_EVIDENCE_DECISION_CAPTURE_DECISION.csv"
OUT_RECORD = CONSOLIDATION / "V20_132_OPERATOR_EVIDENCE_DECISION_RECORD.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_132_EVIDENCE_DECISION_VALIDATION_AUDIT.csv"
OUT_CONSEQUENCE = CONSOLIDATION / "V20_132_EVIDENCE_DECISION_CONSEQUENCE_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_132_OPERATOR_EVIDENCE_DECISION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_132_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_132_OPERATOR_EVIDENCE_DECISION_CAPTURE_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_RECORD, OUT_VALIDATION, OUT_CONSEQUENCE, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    *[CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116", "117", "118", "119", "120", "121", "122", "123", "124", "125", "126", "127", "128", "129", "130", "131"]],
    CONSOLIDATION / "V20_131_OPERATOR_EVIDENCE_REVIEW_PACKET_DECISION.csv",
    CONSOLIDATION / "V20_131_OPERATOR_EVIDENCE_REVIEW_PACKET.csv",
    CONSOLIDATION / "V20_131_EVIDENCE_REVIEW_SUMMARY_AUDIT.csv",
    CONSOLIDATION / "V20_131_EVIDENCE_ACCEPTANCE_OPTIONS_AUDIT.csv",
    CONSOLIDATION / "V20_131_OPERATOR_EVIDENCE_REVIEW_SAFETY_BOUNDARY_AUDIT.csv",
]
REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_131_gate_consumed", "v20_132_operator_evidence_decision_capture_allowed_by_v131", "v20_131_final_status", "selected_repair_scenario_id", "evidence_review_packet_row_count", "evidence_decision_record_count", "every_evidence_review_packet_has_decision_record", "default_request_additional_evidence_count", "evidence_acceptance", "operator_acceptance", "promotion_ready", "v20_133_evidence_decision_resolution_gate_allowed", "operator_evidence_decision_capture_status"},
    OUT_RECORD: {"source_operator_evidence_review_packet_id", "source_blocker_evidence_coverage_audit_id", "source_remaining_blocker_resolution_status_id", "blocker_category", "operator_evidence_decision", "decision_source", "evidence_acceptance", "operator_acceptance", "evidence_decision_status", "blocker_status", "promotion_ready", "ticker_rows_created"},
    OUT_VALIDATION: {"source_operator_evidence_review_packet_id", "blocker_category", "operator_evidence_decision", "decision_available_in_v131_options", "evidence_decision_valid", "conservative_default_used", "explicit_valid_human_evidence_acceptance", "evidence_acceptance_valid", "operator_acceptance", "promotion_ready"},
    OUT_CONSEQUENCE: {"source_operator_evidence_review_packet_id", "blocker_category", "operator_evidence_decision", "evidence_decision_consequence", "evidence_decision_status", "blocker_status", "evidence_acceptance", "operator_acceptance", "promotion_ready"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_131_gate_consumed", "selected_repair_scenario_id", "evidence_acceptance", "operator_acceptance", "promotion_ready", "v20_133_evidence_decision_resolution_gate_allowed", "operator_evidence_decision_capture_status"},
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
    spec = importlib.util.spec_from_file_location("v20_132_operator_evidence_decision_capture_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    mapping = {
        "IN_DECISION": "V20_131_OPERATOR_EVIDENCE_REVIEW_PACKET_DECISION.csv",
        "IN_PACKET": "V20_131_OPERATOR_EVIDENCE_REVIEW_PACKET.csv",
        "IN_SUMMARY": "V20_131_EVIDENCE_REVIEW_SUMMARY_AUDIT.csv",
        "IN_OPTIONS": "V20_131_EVIDENCE_ACCEPTANCE_OPTIONS_AUDIT.csv",
        "IN_SAFETY": "V20_131_OPERATOR_EVIDENCE_REVIEW_SAFETY_BOUNDARY_AUDIT.csv",
        "IN_GATE": "V20_131_NEXT_STAGE_GATE.csv",
    }
    for attr, filename in mapping.items():
        setattr(module, attr, temp / filename)
    module.REQUIRED_INPUTS = [getattr(module, attr) for attr in mapping]
    module.UPSTREAM_HASH_INPUTS = module.REQUIRED_INPUTS
    module.OUT_DECISION = temp / "V20_132_OPERATOR_EVIDENCE_DECISION_CAPTURE_DECISION.csv"
    module.OUT_RECORD = temp / "V20_132_OPERATOR_EVIDENCE_DECISION_RECORD.csv"
    module.OUT_VALIDATION = temp / "V20_132_EVIDENCE_DECISION_VALIDATION_AUDIT.csv"
    module.OUT_CONSEQUENCE = temp / "V20_132_EVIDENCE_DECISION_CONSEQUENCE_AUDIT.csv"
    module.OUT_SAFETY = temp / "V20_132_OPERATOR_EVIDENCE_DECISION_SAFETY_BOUNDARY_AUDIT.csv"
    module.OUT_GATE = temp / "V20_132_NEXT_STAGE_GATE.csv"
    module.REPORT = temp / "V20_132_OPERATOR_EVIDENCE_DECISION_CAPTURE_REPORT.md"


def copy_required_inputs(temp: Path) -> None:
    for filename in [
        "V20_131_OPERATOR_EVIDENCE_REVIEW_PACKET_DECISION.csv",
        "V20_131_OPERATOR_EVIDENCE_REVIEW_PACKET.csv",
        "V20_131_EVIDENCE_REVIEW_SUMMARY_AUDIT.csv",
        "V20_131_EVIDENCE_ACCEPTANCE_OPTIONS_AUDIT.csv",
        "V20_131_OPERATOR_EVIDENCE_REVIEW_SAFETY_BOUNDARY_AUDIT.csv",
        "V20_131_NEXT_STAGE_GATE.csv",
    ]:
        shutil.copy2(CONSOLIDATION / filename, temp / filename)


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        assert module.main() == 0
        blocked = read_csv(module.OUT_DECISION)[0]
        assert blocked["operator_evidence_decision_capture_status"] == "BLOCKED_V20_132_OPERATOR_EVIDENCE_DECISION_CAPTURE"
        assert blocked["v20_133_evidence_decision_resolution_gate_allowed"] == "FALSE"
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
        assert decision["operator_evidence_decision_capture_status"] == "PARTIAL_PASS_V20_132_EVIDENCE_DECISIONS_DEFAULT_MORE_EVIDENCE_READY_FOR_V20_133"
        records = read_csv(module.OUT_RECORD)
        packets = read_csv(module.IN_PACKET)
        assert len(records) != len(packets)


def test_accept_without_explicit_evidence_cannot_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        original_consequence = module.consequence_for
        module.DEFAULT_DECISION = "ACCEPT_EVIDENCE_WITH_LIMITATION"
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        validation = read_csv(module.OUT_VALIDATION)
        assert decision["operator_evidence_decision_capture_status"] == "BLOCKED_V20_132_OPERATOR_EVIDENCE_DECISION_CAPTURE"
        assert all(row["operator_evidence_decision"] == "ACCEPT_EVIDENCE_WITH_LIMITATION" for row in validation)
        assert all(row["explicit_valid_human_evidence_acceptance"] == "FALSE" for row in validation)
        module.consequence_for = original_consequence


def test_blocked_input_cases_produce_blocked_not_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        gate = read_csv(module.IN_GATE)
        gate[0]["v20_132_operator_evidence_decision_capture_allowed"] = "FALSE"
        write_csv(module.IN_GATE, gate)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["operator_evidence_decision_capture_status"] == "BLOCKED_V20_132_OPERATOR_EVIDENCE_DECISION_CAPTURE"
        assert decision["operator_evidence_decision_capture_status"] != "PASS_V20_132_OPERATOR_EVIDENCE_DECISION_CAPTURE_READY_FOR_V20_133"
        assert decision["v20_133_evidence_decision_resolution_gate_allowed"] == "FALSE"


def test_operator_evidence_decision_capture() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.131 outputs were mutated"
    stdout = result.stdout
    assert "PARTIAL_PASS_V20_132_EVIDENCE_DECISIONS_DEFAULT_MORE_EVIDENCE_READY_FOR_V20_133" in stdout
    for expected in [
        "V20_131_GATE_CONSUMED=TRUE",
        "V20_132_OPERATOR_EVIDENCE_DECISION_CAPTURE_ALLOWED_BY_V131=TRUE",
        "V20_131_FINAL_STATUS=PASS_V20_131_OPERATOR_EVIDENCE_REVIEW_PACKET_READY_FOR_V20_132",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "SELECTED_SCENARIO_MATCHES_V20_131=TRUE",
        "EVIDENCE_REVIEW_PACKET_ROW_COUNT=2",
        "EVIDENCE_DECISION_RECORD_COUNT=2",
        "EVERY_EVIDENCE_REVIEW_PACKET_HAS_DECISION_RECORD=TRUE",
        "DEFAULT_REQUEST_ADDITIONAL_EVIDENCE_COUNT=2",
        "EVIDENCE_ACCEPTANCE=FALSE",
        "OPERATOR_ACCEPTANCE=FALSE",
        "PROMOTION_READY=FALSE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_133_EVIDENCE_DECISION_RESOLUTION_GATE_ALLOWED=TRUE",
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
    packet = read_csv(CONSOLIDATION / "V20_131_OPERATOR_EVIDENCE_REVIEW_PACKET.csv")
    d = decision[0]
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["operator_evidence_decision_capture_status"] == "PARTIAL_PASS_V20_132_EVIDENCE_DECISIONS_DEFAULT_MORE_EVIDENCE_READY_FOR_V20_133"
    assert d["evidence_acceptance"] == "FALSE"
    assert d["operator_acceptance"] == "FALSE"
    assert d["promotion_ready"] == "FALSE"
    assert d["v20_133_evidence_decision_resolution_gate_allowed"] == "TRUE"
    assert len(record) == len(packet)
    assert {row["source_operator_evidence_review_packet_id"] for row in record} == {row["operator_evidence_review_packet_id"] for row in packet}
    assert all(row["operator_evidence_decision"] in VALID_DECISIONS for row in record)
    assert all(row["operator_evidence_decision"] == "REQUEST_ADDITIONAL_EVIDENCE" and row["decision_source"] == "CONSERVATIVE_DEFAULT_NO_EXPLICIT_HUMAN_EVIDENCE_ACCEPTANCE" for row in record)
    assert all(row["evidence_acceptance"] == "FALSE" and row["operator_acceptance"] == "FALSE" and row["promotion_ready"] == "FALSE" for row in record)
    assert all(row["evidence_decision_status"] == "PENDING_MORE_EVIDENCE" and row["blocker_status"] == "UNRESOLVED_OR_PENDING_REVIEW" for row in record)
    assert validation
    assert all(row["evidence_decision_valid"] == "TRUE" and row["conservative_default_used"] == "TRUE" and row["explicit_valid_human_evidence_acceptance"] == "FALSE" and row["evidence_acceptance_valid"] == "FALSE" for row in validation)
    assert consequence
    assert all(row["evidence_decision_status"] == "PENDING_MORE_EVIDENCE" and row["blocker_status"] == "UNRESOLVED_OR_PENDING_REVIEW" and row["promotion_ready"] == "FALSE" for row in consequence)
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["evidence_acceptance"] == "FALSE"
    assert gate[0]["operator_acceptance"] == "FALSE"
    assert gate[0]["promotion_ready"] == "FALSE"
    assert gate[0]["v20_133_evidence_decision_resolution_gate_allowed"] == "TRUE"
    for rows in [decision, record, validation, consequence, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_missing_decision_record_cannot_pass()
    test_accept_without_explicit_evidence_cannot_pass()
    test_blocked_input_cases_produce_blocked_not_pass()
    test_operator_evidence_decision_capture()
    print("PASS_V20_132_OPERATOR_EVIDENCE_DECISION_CAPTURE_TESTS")
