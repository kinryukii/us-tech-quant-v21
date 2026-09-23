#!/usr/bin/env python
"""Tests for V20.145 final human decision capture."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_145_final_human_decision_capture.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
ALLOWED_ACTIONS = {"ACCEPT_WITH_LIMITATION", "REJECT_KEEP_BLOCKED", "MORE_EVIDENCE_REQUIRED"}

OUT_DECISION = CONSOLIDATION / "V20_145_FINAL_HUMAN_DECISION_CAPTURE_DECISION.csv"
OUT_INPUT = CONSOLIDATION / "V20_145_EXPLICIT_HUMAN_DECISION_INPUT.csv"
OUT_RECORD = CONSOLIDATION / "V20_145_FINAL_HUMAN_DECISION_RECORD.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_145_FINAL_HUMAN_DECISION_VALIDATION_AUDIT.csv"
OUT_CONSEQUENCE = CONSOLIDATION / "V20_145_FINAL_HUMAN_DECISION_CONSEQUENCE_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_145_FINAL_HUMAN_DECISION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_145_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_145_FINAL_HUMAN_DECISION_CAPTURE_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_INPUT, OUT_RECORD, OUT_VALIDATION, OUT_CONSEQUENCE, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = sorted(
    path
    for path in CONSOLIDATION.glob("V20_*")
    if path.is_file() and any(path.name.startswith(f"V20_{stage}_") for stage in range(109, 145))
)
REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_144_gate_consumed", "v20_145_final_human_decision_capture_allowed_by_v144", "v20_144_final_status", "selected_repair_scenario_id", "explicit_human_decision_input_count", "final_human_decision_record_count", "every_packet_has_explicit_human_decision", "all_human_actions_allowed", "accept_with_limitation_count", "evidence_acceptance", "operator_acceptance", "promotion_ready", "promotion_readiness_recheck_allowed", "v20_146_promotion_readiness_recheck_allowed", "final_human_decision_capture_status"},
    OUT_INPUT: {"blocker_id", "blocker_category", "selected_human_action", "human_rationale", "input_source"},
    OUT_RECORD: {"source_final_human_confirmation_packet_id", "blocker_id", "blocker_category", "selected_human_action", "human_rationale", "human_decision_source", "decision_status", "blocker_status", "evidence_acceptance", "operator_acceptance", "promotion_ready", "promotion_readiness_recheck_allowed", "ticker_rows_created"},
    OUT_VALIDATION: {"blocker_id", "blocker_category", "selected_human_action", "human_action_allowed_in_v144_packet", "explicit_human_decision_present", "human_rationale_present", "human_decision_valid", "prohibited_authorization_detected", "promotion_ready"},
    OUT_CONSEQUENCE: {"blocker_id", "blocker_category", "selected_human_action", "decision_consequence", "decision_status", "blocker_status", "promotion_readiness_recheck_allowed", "promotion_ready"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_144_gate_consumed", "selected_repair_scenario_id", "evidence_acceptance", "operator_acceptance", "promotion_ready", "promotion_readiness_recheck_allowed", "v20_146_promotion_readiness_recheck_allowed", "final_human_decision_capture_status"},
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
    spec = importlib.util.spec_from_file_location("v20_145_final_human_decision_capture_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    mapping = {
        "IN_DECISION": "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET_DECISION.csv",
        "IN_PACKET": "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET.csv",
        "IN_OPTIONS": "V20_144_FINAL_HUMAN_CONFIRMATION_OPTIONS_AUDIT.csv",
        "IN_REQUIRED": "V20_144_FINAL_HUMAN_CONFIRMATION_REQUIRED_ACTIONS.csv",
        "IN_SAFETY": "V20_144_FINAL_HUMAN_CONFIRMATION_SAFETY_BOUNDARY_AUDIT.csv",
        "IN_GATE": "V20_144_NEXT_STAGE_GATE.csv",
    }
    for attr, filename in mapping.items():
        setattr(module, attr, temp / filename)
    module.REQUIRED_INPUTS = [getattr(module, attr) for attr in mapping]
    module.UPSTREAM_HASH_INPUTS = module.REQUIRED_INPUTS
    module.OUT_DECISION = temp / "V20_145_FINAL_HUMAN_DECISION_CAPTURE_DECISION.csv"
    module.OUT_INPUT = temp / "V20_145_EXPLICIT_HUMAN_DECISION_INPUT.csv"
    module.OUT_RECORD = temp / "V20_145_FINAL_HUMAN_DECISION_RECORD.csv"
    module.OUT_VALIDATION = temp / "V20_145_FINAL_HUMAN_DECISION_VALIDATION_AUDIT.csv"
    module.OUT_CONSEQUENCE = temp / "V20_145_FINAL_HUMAN_DECISION_CONSEQUENCE_AUDIT.csv"
    module.OUT_SAFETY = temp / "V20_145_FINAL_HUMAN_DECISION_SAFETY_BOUNDARY_AUDIT.csv"
    module.OUT_GATE = temp / "V20_145_NEXT_STAGE_GATE.csv"
    module.REPORT = temp / "V20_145_FINAL_HUMAN_DECISION_CAPTURE_REPORT.md"


def copy_required_inputs(temp: Path) -> None:
    for filename in [
        "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET_DECISION.csv",
        "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET.csv",
        "V20_144_FINAL_HUMAN_CONFIRMATION_OPTIONS_AUDIT.csv",
        "V20_144_FINAL_HUMAN_CONFIRMATION_REQUIRED_ACTIONS.csv",
        "V20_144_FINAL_HUMAN_CONFIRMATION_SAFETY_BOUNDARY_AUDIT.csv",
        "V20_144_NEXT_STAGE_GATE.csv",
    ]:
        shutil.copy2(CONSOLIDATION / filename, temp / filename)


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["final_human_decision_capture_status"] == "BLOCKED_V20_145_FINAL_HUMAN_DECISION_CAPTURE"
        assert decision["v20_146_promotion_readiness_recheck_allowed"] == "FALSE"
        assert decision["promotion_ready"] == "FALSE"


def test_missing_explicit_decision_cannot_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        module.EXPLICIT_HUMAN_DECISIONS = module.EXPLICIT_HUMAN_DECISIONS[:-1]
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        validation = read_csv(module.OUT_VALIDATION)
        assert decision["final_human_decision_capture_status"] == "BLOCKED_V20_145_FINAL_HUMAN_DECISION_CAPTURE"
        assert any(row["explicit_human_decision_present"] == "FALSE" for row in validation)


def test_disallowed_human_action_cannot_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        module.EXPLICIT_HUMAN_DECISIONS[0]["selected_human_action"] = "AUTO_ACCEPT_PROMOTION"
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        validation = read_csv(module.OUT_VALIDATION)
        assert decision["final_human_decision_capture_status"] == "BLOCKED_V20_145_FINAL_HUMAN_DECISION_CAPTURE"
        assert any(row["human_action_allowed_in_v144_packet"] == "FALSE" for row in validation)


def test_blocked_input_cases_produce_blocked_not_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        gate = read_csv(module.IN_GATE)
        gate[0]["v20_145_final_human_decision_capture_allowed"] = "FALSE"
        write_csv(module.IN_GATE, gate)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["final_human_decision_capture_status"] == "BLOCKED_V20_145_FINAL_HUMAN_DECISION_CAPTURE"
        assert decision["v20_146_promotion_readiness_recheck_allowed"] == "FALSE"


def test_final_human_decision_capture() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.144 outputs were mutated"
    stdout = result.stdout
    for expected in [
        "PASS_V20_145_FINAL_HUMAN_DECISION_CAPTURE_READY_FOR_PROMOTION_READINESS_RECHECK",
        "V20_144_GATE_CONSUMED=TRUE",
        "V20_145_FINAL_HUMAN_DECISION_CAPTURE_ALLOWED_BY_V144=TRUE",
        "V20_144_FINAL_STATUS=PARTIAL_PASS_V20_144_FINAL_HUMAN_CONFIRMATION_PACKET_AWAITING_OPERATOR_INPUT",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "FINAL_HUMAN_CONFIRMATION_PACKET_ROW_COUNT=2",
        "EXPLICIT_HUMAN_DECISION_INPUT_COUNT=2",
        "FINAL_HUMAN_DECISION_RECORD_COUNT=2",
        "EVERY_PACKET_HAS_EXPLICIT_HUMAN_DECISION=TRUE",
        "ALL_HUMAN_ACTIONS_ALLOWED=TRUE",
        "ACCEPT_WITH_LIMITATION_COUNT=2",
        "EVIDENCE_ACCEPTANCE=TRUE",
        "OPERATOR_ACCEPTANCE=TRUE",
        "PROMOTION_READY=FALSE",
        "PROMOTION_READINESS_RECHECK_ALLOWED=TRUE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_146_PROMOTION_READINESS_RECHECK_ALLOWED=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"

    decision = read_csv(OUT_DECISION)
    explicit_input = read_csv(OUT_INPUT)
    record = read_csv(OUT_RECORD)
    validation = read_csv(OUT_VALIDATION)
    consequence = read_csv(OUT_CONSEQUENCE)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    packet = read_csv(CONSOLIDATION / "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET.csv")
    d = decision[0]
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["final_human_decision_capture_status"] == "PASS_V20_145_FINAL_HUMAN_DECISION_CAPTURE_READY_FOR_PROMOTION_READINESS_RECHECK"
    assert d["evidence_acceptance"] == "TRUE"
    assert d["operator_acceptance"] == "TRUE"
    assert d["promotion_ready"] == "FALSE"
    assert len(explicit_input) == 2
    assert all(row["selected_human_action"] == "ACCEPT_WITH_LIMITATION" for row in explicit_input)
    assert len(record) == len(packet)
    assert {row["blocker_id"] for row in record} == {row["blocker_id"] for row in packet}
    assert all(row["selected_human_action"] in ALLOWED_ACTIONS for row in record)
    assert all(row["selected_human_action"] == "ACCEPT_WITH_LIMITATION" and row["decision_status"] == "FINAL_HUMAN_ACCEPTED_WITH_LIMITATION_FOR_PROMOTION_READINESS_RECHECK_ONLY" for row in record)
    assert all(row["evidence_acceptance"] == "TRUE" and row["operator_acceptance"] == "TRUE" and row["promotion_ready"] == "FALSE" and row["promotion_readiness_recheck_allowed"] == "TRUE" for row in record)
    assert all(row["human_decision_valid"] == "TRUE" and row["prohibited_authorization_detected"] == "FALSE" for row in validation)
    assert all(row["promotion_readiness_recheck_allowed"] == "TRUE" and row["promotion_ready"] == "FALSE" for row in consequence)
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["v20_146_promotion_readiness_recheck_allowed"] == "TRUE"
    assert gate[0]["promotion_ready"] == "FALSE"
    for rows in [decision, explicit_input, record, validation, consequence, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_missing_explicit_decision_cannot_pass()
    test_disallowed_human_action_cannot_pass()
    test_blocked_input_cases_produce_blocked_not_pass()
    test_final_human_decision_capture()
    print("PASS_V20_145_FINAL_HUMAN_DECISION_CAPTURE_TESTS")

