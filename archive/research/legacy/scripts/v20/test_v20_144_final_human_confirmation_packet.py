#!/usr/bin/env python
"""Tests for V20.144 final human confirmation packet."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_144_final_human_confirmation_packet.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
HUMAN_ACTIONS = {"ACCEPT_WITH_LIMITATION", "REJECT_KEEP_BLOCKED", "MORE_EVIDENCE_REQUIRED"}

OUT_DECISION = CONSOLIDATION / "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET_DECISION.csv"
OUT_PACKET = CONSOLIDATION / "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET.csv"
OUT_OPTIONS = CONSOLIDATION / "V20_144_FINAL_HUMAN_CONFIRMATION_OPTIONS_AUDIT.csv"
OUT_REQUIRED = CONSOLIDATION / "V20_144_FINAL_HUMAN_CONFIRMATION_REQUIRED_ACTIONS.csv"
OUT_SAFETY = CONSOLIDATION / "V20_144_FINAL_HUMAN_CONFIRMATION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_144_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_PACKET, OUT_OPTIONS, OUT_REQUIRED, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = sorted(
    path
    for path in CONSOLIDATION.glob("V20_*")
    if path.is_file() and any(path.name.startswith(f"V20_{stage}_") for stage in range(109, 144))
)
REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_143_gate_consumed", "v20_144_final_human_confirmation_packet_allowed_by_v143", "v20_143_final_status", "selected_repair_scenario_id", "pending_final_human_confirmation_blocker_count", "final_human_confirmation_packet_row_count", "every_pending_blocker_has_final_human_confirmation_packet", "final_human_confirmation_options_audit_row_count", "final_human_confirmation_required_action_row_count", "no_human_action_auto_selected", "no_fourth_round_evidence_plan_created", "evidence_acceptance", "operator_acceptance", "promotion_ready", "v20_145_final_human_decision_capture_allowed", "final_human_confirmation_packet_status"},
    OUT_PACKET: {"blocker_id", "blocker_category", "blocker_status", "first_round_evidence_summary", "second_round_evidence_summary", "third_round_evidence_summary", "current_decision_status", "remaining_limitation_summary", "human_confirmation_question", "allowed_human_actions", "default_action", "selected_human_action", "human_action_auto_selected", "evidence_acceptance", "operator_acceptance", "promotion_ready", "ticker_rows_created"},
    OUT_OPTIONS: {"source_final_human_confirmation_packet_id", "blocker_id", "blocker_category", "human_action_option", "option_available", "option_requires_explicit_human_input", "option_auto_selected", "option_consequence", "evidence_acceptance", "operator_acceptance", "promotion_ready"},
    OUT_REQUIRED: {"source_final_human_confirmation_packet_id", "blocker_id", "blocker_category", "required_human_decision", "allowed_human_actions", "human_action_selected", "selected_human_action", "operator_input_required_before_v20_145", "acceptance_blocker_closure_or_promotion_recheck_allowed_before_input", "evidence_acceptance", "operator_acceptance", "promotion_ready"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_143_gate_consumed", "selected_repair_scenario_id", "human_operator_input_required_before_v20_145", "evidence_acceptance", "operator_acceptance", "promotion_ready", "no_fourth_round_evidence_plan_created", "v20_145_final_human_decision_capture_allowed", "final_human_confirmation_packet_status"},
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
    spec = importlib.util.spec_from_file_location("v20_144_final_human_confirmation_packet_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    mapping = {
        "IN_DECISION": "V20_143_THIRD_ROUND_OPERATOR_DECISION_CAPTURE_DECISION.csv",
        "IN_RECORD": "V20_143_THIRD_ROUND_OPERATOR_DECISION_RECORD.csv",
        "IN_VALIDATION": "V20_143_THIRD_ROUND_DECISION_VALIDATION_AUDIT.csv",
        "IN_CONSEQUENCE": "V20_143_THIRD_ROUND_DECISION_CONSEQUENCE_AUDIT.csv",
        "IN_SAFETY": "V20_143_THIRD_ROUND_OPERATOR_DECISION_SAFETY_BOUNDARY_AUDIT.csv",
        "IN_GATE": "V20_143_NEXT_STAGE_GATE.csv",
        "IN_PACKET": "V20_142_THIRD_ROUND_OPERATOR_REVIEW_PACKET.csv",
        "IN_SUMMARY": "V20_142_THIRD_ROUND_REVIEW_SUMMARY_AUDIT.csv",
        "IN_COVERAGE": "V20_141_THIRD_ROUND_BLOCKER_COVERAGE_AUDIT.csv",
        "IN_RESULT": "V20_140_THIRD_ROUND_EVIDENCE_RESULT_AUDIT.csv",
        "IN_REMAINING": "V20_133_REMAINING_EVIDENCE_BLOCKER_STATUS.csv",
    }
    for attr, filename in mapping.items():
        setattr(module, attr, temp / filename)
    module.REQUIRED_INPUTS = [getattr(module, attr) for attr in mapping]
    module.UPSTREAM_HASH_INPUTS = module.REQUIRED_INPUTS
    module.OUT_DECISION = temp / "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET_DECISION.csv"
    module.OUT_PACKET = temp / "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET.csv"
    module.OUT_OPTIONS = temp / "V20_144_FINAL_HUMAN_CONFIRMATION_OPTIONS_AUDIT.csv"
    module.OUT_REQUIRED = temp / "V20_144_FINAL_HUMAN_CONFIRMATION_REQUIRED_ACTIONS.csv"
    module.OUT_SAFETY = temp / "V20_144_FINAL_HUMAN_CONFIRMATION_SAFETY_BOUNDARY_AUDIT.csv"
    module.OUT_GATE = temp / "V20_144_NEXT_STAGE_GATE.csv"
    module.REPORT = temp / "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET_REPORT.md"


def copy_required_inputs(temp: Path) -> None:
    for filename in [
        "V20_143_THIRD_ROUND_OPERATOR_DECISION_CAPTURE_DECISION.csv",
        "V20_143_THIRD_ROUND_OPERATOR_DECISION_RECORD.csv",
        "V20_143_THIRD_ROUND_DECISION_VALIDATION_AUDIT.csv",
        "V20_143_THIRD_ROUND_DECISION_CONSEQUENCE_AUDIT.csv",
        "V20_143_THIRD_ROUND_OPERATOR_DECISION_SAFETY_BOUNDARY_AUDIT.csv",
        "V20_143_NEXT_STAGE_GATE.csv",
        "V20_142_THIRD_ROUND_OPERATOR_REVIEW_PACKET.csv",
        "V20_142_THIRD_ROUND_REVIEW_SUMMARY_AUDIT.csv",
        "V20_141_THIRD_ROUND_BLOCKER_COVERAGE_AUDIT.csv",
        "V20_140_THIRD_ROUND_EVIDENCE_RESULT_AUDIT.csv",
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
        assert blocked["final_human_confirmation_packet_status"] == "BLOCKED_V20_144_FINAL_HUMAN_CONFIRMATION_PACKET"
        assert blocked["v20_145_final_human_decision_capture_allowed"] == "FALSE"
        assert blocked["promotion_ready"] == "FALSE"


def test_missing_final_packet_cannot_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        original_builder = module.build_packets

        def incomplete_builder(selected_id, pending_rows, packet_rows, summary_rows, coverage_rows, result_rows, remaining_rows):
            packets, options, required = original_builder(selected_id, pending_rows, packet_rows, summary_rows, coverage_rows, result_rows, remaining_rows)
            return packets[:-1], [row for row in options if row["source_final_human_confirmation_packet_id"] != packets[-1]["final_human_confirmation_packet_id"]], required[:-1]

        module.build_packets = incomplete_builder
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["final_human_confirmation_packet_status"] == "BLOCKED_V20_144_FINAL_HUMAN_CONFIRMATION_PACKET"
        assert decision["every_pending_blocker_has_final_human_confirmation_packet"] == "FALSE"


def test_auto_selected_human_action_cannot_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        original_builder = module.build_packets

        def auto_selecting_builder(selected_id, pending_rows, packet_rows, summary_rows, coverage_rows, result_rows, remaining_rows):
            packets, options, required = original_builder(selected_id, pending_rows, packet_rows, summary_rows, coverage_rows, result_rows, remaining_rows)
            packets[0]["human_action_auto_selected"] = "TRUE"
            packets[0]["selected_human_action"] = "ACCEPT_WITH_LIMITATION"
            return packets, options, required

        module.build_packets = auto_selecting_builder
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["final_human_confirmation_packet_status"] == "BLOCKED_V20_144_FINAL_HUMAN_CONFIRMATION_PACKET"
        assert decision["no_human_action_auto_selected"] == "FALSE"
        assert decision["v20_145_final_human_decision_capture_allowed"] == "FALSE"


def test_blocked_input_cases_produce_blocked_not_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        gate = read_csv(module.IN_GATE)
        gate[0]["v20_144_final_human_confirmation_packet_allowed"] = "FALSE"
        write_csv(module.IN_GATE, gate)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["final_human_confirmation_packet_status"] == "BLOCKED_V20_144_FINAL_HUMAN_CONFIRMATION_PACKET"
        assert decision["final_human_confirmation_packet_status"] != "PARTIAL_PASS_V20_144_FINAL_HUMAN_CONFIRMATION_PACKET_AWAITING_OPERATOR_INPUT"


def test_final_human_confirmation_packet() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.143 outputs were mutated"
    stdout = result.stdout
    assert "PARTIAL_PASS_V20_144_FINAL_HUMAN_CONFIRMATION_PACKET_AWAITING_OPERATOR_INPUT" in stdout
    for expected in [
        "V20_143_GATE_CONSUMED=TRUE",
        "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET_ALLOWED_BY_V143=TRUE",
        "V20_143_FINAL_STATUS=PARTIAL_PASS_V20_143_THIRD_ROUND_DECISIONS_PENDING_FINAL_HUMAN_CONFIRMATION_READY_FOR_V20_144",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "SELECTED_SCENARIO_MATCHES_V20_143=TRUE",
        "PENDING_FINAL_HUMAN_CONFIRMATION_BLOCKER_COUNT=2",
        "FINAL_HUMAN_CONFIRMATION_PACKET_ROW_COUNT=2",
        "EVERY_PENDING_BLOCKER_HAS_FINAL_HUMAN_CONFIRMATION_PACKET=TRUE",
        "FINAL_HUMAN_CONFIRMATION_OPTIONS_AUDIT_ROW_COUNT=6",
        "FINAL_HUMAN_CONFIRMATION_REQUIRED_ACTION_ROW_COUNT=2",
        "ALL_PACKETS_HAVE_EXACTLY_THREE_ALLOWED_ACTIONS=TRUE",
        "ALL_PACKETS_DEFAULT_AWAITING_EXPLICIT_HUMAN_CONFIRMATION=TRUE",
        "HUMAN_ACTION_AUTO_SELECTED_COUNT=0",
        "NO_HUMAN_ACTION_AUTO_SELECTED=TRUE",
        "FOURTH_ROUND_EVIDENCE_PLAN_CREATED=FALSE",
        "EVIDENCE_ACCEPTANCE=FALSE",
        "OPERATOR_ACCEPTANCE=FALSE",
        "PROMOTION_READY=FALSE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_145_FINAL_HUMAN_DECISION_CAPTURE_ALLOWED=TRUE",
        "OPERATOR_INPUT_REQUIRED_BEFORE_V20_145=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"
    assert not any((CONSOLIDATION / name).exists() for name in ["V20_144_FOURTH_ROUND_EVIDENCE_PLAN.csv", "V20_144_FOURTH_ROUND_EVIDENCE_PLAN_DECISION.csv"])

    decision = read_csv(OUT_DECISION)
    packets = read_csv(OUT_PACKET)
    options = read_csv(OUT_OPTIONS)
    required = read_csv(OUT_REQUIRED)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    pending = [row for row in read_csv(CONSOLIDATION / "V20_143_THIRD_ROUND_OPERATOR_DECISION_RECORD.csv") if row["third_round_operator_decision"] == "REQUEST_FINAL_OPERATOR_ESCALATION" and row["decision_status"] == "PENDING_FINAL_HUMAN_CONFIRMATION"]
    d = decision[0]
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["final_human_confirmation_packet_status"] == "PARTIAL_PASS_V20_144_FINAL_HUMAN_CONFIRMATION_PACKET_AWAITING_OPERATOR_INPUT"
    assert d["v20_145_final_human_decision_capture_allowed"] == "TRUE"
    assert len(packets) == len(pending)
    assert {row["source_third_round_operator_decision_record_id"] for row in packets} == {row["third_round_operator_decision_record_id"] for row in pending}
    assert all(set(row["allowed_human_actions"].split(";")) == HUMAN_ACTIONS for row in packets)
    assert all(row["default_action"] == "AWAITING_EXPLICIT_HUMAN_CONFIRMATION" and row["selected_human_action"] == "" and row["human_action_auto_selected"] == "FALSE" for row in packets)
    option_map = {}
    for row in options:
        option_map.setdefault(row["source_final_human_confirmation_packet_id"], set()).add(row["human_action_option"])
    assert all(option_map[row["final_human_confirmation_packet_id"]] == HUMAN_ACTIONS for row in packets)
    assert len(options) == len(packets) * 3
    assert all(row["option_auto_selected"] == "FALSE" and row["option_requires_explicit_human_input"] == "TRUE" for row in options)
    assert len(required) == len(packets)
    assert all(row["human_action_selected"] == "FALSE" and row["selected_human_action"] == "" and row["operator_input_required_before_v20_145"] == "TRUE" and row["acceptance_blocker_closure_or_promotion_recheck_allowed_before_input"] == "FALSE" for row in required)
    for rows in [decision, packets, options, required, gate]:
        assert all(row["evidence_acceptance"] == "FALSE" and row["operator_acceptance"] == "FALSE" and row["promotion_ready"] == "FALSE" for row in rows)
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["human_operator_input_required_before_v20_145"] == "TRUE"
    assert gate[0]["v20_145_final_human_decision_capture_allowed"] == "TRUE"
    assert gate[0]["no_fourth_round_evidence_plan_created"] == "TRUE"
    for rows in [decision, packets, options, required, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_missing_final_packet_cannot_pass()
    test_auto_selected_human_action_cannot_pass()
    test_blocked_input_cases_produce_blocked_not_pass()
    test_final_human_confirmation_packet()
    print("PASS_V20_144_FINAL_HUMAN_CONFIRMATION_PACKET_TESTS")
