#!/usr/bin/env python
"""Tests for V20.148 promotion-readiness operator review."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_148_promotion_readiness_operator_review.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
OPERATOR_ACTIONS = {"APPROVE_PROMOTION_READINESS_FOR_STAGING", "REJECT_PROMOTION_READINESS_KEEP_RESEARCH_ONLY", "REQUEST_PROMOTION_READINESS_REMEDIATION"}
DEFAULT_ACTION = "AWAITING_EXPLICIT_OPERATOR_PROMOTION_READINESS_REVIEW"

OUT_DECISION = CONSOLIDATION / "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_DECISION.csv"
OUT_PACKET = CONSOLIDATION / "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_PACKET.csv"
OUT_OPTIONS = CONSOLIDATION / "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_OPTIONS_AUDIT.csv"
OUT_REQUIRED = CONSOLIDATION / "V20_148_PROMOTION_READINESS_OPERATOR_REQUIRED_ACTIONS.csv"
OUT_SAFETY = CONSOLIDATION / "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_148_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_PACKET, OUT_OPTIONS, OUT_REQUIRED, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = sorted(
    path
    for path in CONSOLIDATION.glob("V20_*")
    if path.is_file() and any(path.name.startswith(f"V20_{stage}_") for stage in range(109, 148))
)
REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_147_gate_consumed", "v20_148_promotion_readiness_operator_review_allowed_by_v147", "v20_147_final_status", "selected_repair_scenario_id", "operator_review_packet_row_count", "operator_review_options_audit_row_count", "operator_required_actions_row_count", "packet_requirements_met", "operator_actions_complete", "default_operator_action_valid", "operator_action_auto_selected_count", "no_operator_action_auto_selected", "operator_input_required_before_v20_149", "evidence_acceptance", "operator_acceptance", "promotion_ready", "v20_149_promotion_readiness_operator_decision_capture_allowed", "promotion_readiness_operator_review_status"},
    OUT_PACKET: {"source_promotion_readiness_packet_id", "promotion_readiness_recheck_passed", "evidence_acceptance", "operator_acceptance", "promotion_ready", "accepted_limitation_count", "evidence_manifest_row_count", "criteria_pass_count", "criteria_fail_count", "remaining_limitation_summary", "operator_review_question", "allowed_operator_actions", "default_operator_action", "selected_operator_action", "operator_action_auto_selected", "operator_input_required_before_v20_149", "ticker_rows_created"},
    OUT_OPTIONS: {"source_promotion_readiness_operator_review_packet_id", "operator_action_option", "option_available", "option_requires_explicit_operator_input", "option_auto_selected", "option_consequence", "promotion_ready"},
    OUT_REQUIRED: {"source_promotion_readiness_operator_review_packet_id", "required_operator_decision", "allowed_operator_actions", "operator_action_selected", "selected_operator_action", "operator_input_required_before_v20_149", "promotion_readiness_decision_capture_allowed_before_input", "promotion_ready"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_147_gate_consumed", "selected_repair_scenario_id", "operator_input_required_before_v20_149", "evidence_acceptance", "operator_acceptance", "promotion_ready", "v20_149_promotion_readiness_operator_decision_capture_allowed", "promotion_readiness_operator_review_status"},
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
    spec = importlib.util.spec_from_file_location("v20_148_promotion_readiness_operator_review_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    mapping = {
        "IN_DECISION": "V20_147_PROMOTION_READINESS_PACKET_DECISION.csv",
        "IN_PACKET": "V20_147_PROMOTION_READINESS_PACKET.csv",
        "IN_MANIFEST": "V20_147_PROMOTION_READINESS_EVIDENCE_MANIFEST.csv",
        "IN_LIMITATION": "V20_147_PROMOTION_READINESS_LIMITATION_SUMMARY.csv",
        "IN_SAFETY": "V20_147_PROMOTION_READINESS_PACKET_SAFETY_BOUNDARY_AUDIT.csv",
        "IN_GATE": "V20_147_NEXT_STAGE_GATE.csv",
        "IN_CRITERIA": "V20_146_PROMOTION_READINESS_CRITERIA_AUDIT.csv",
        "IN_DISPOSITION": "V20_146_BLOCKER_DISPOSITION_AUDIT.csv",
        "IN_V145_RECORD": "V20_145_FINAL_HUMAN_DECISION_RECORD.csv",
    }
    for attr, filename in mapping.items():
        setattr(module, attr, temp / filename)
    module.REQUIRED_INPUTS = [getattr(module, attr) for attr in mapping]
    module.UPSTREAM_HASH_INPUTS = module.REQUIRED_INPUTS
    module.OUT_DECISION = temp / "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_DECISION.csv"
    module.OUT_PACKET = temp / "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_PACKET.csv"
    module.OUT_OPTIONS = temp / "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_OPTIONS_AUDIT.csv"
    module.OUT_REQUIRED = temp / "V20_148_PROMOTION_READINESS_OPERATOR_REQUIRED_ACTIONS.csv"
    module.OUT_SAFETY = temp / "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_SAFETY_BOUNDARY_AUDIT.csv"
    module.OUT_GATE = temp / "V20_148_NEXT_STAGE_GATE.csv"
    module.REPORT = temp / "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_REPORT.md"


def copy_required_inputs(temp: Path) -> None:
    for filename in [
        "V20_147_PROMOTION_READINESS_PACKET_DECISION.csv",
        "V20_147_PROMOTION_READINESS_PACKET.csv",
        "V20_147_PROMOTION_READINESS_EVIDENCE_MANIFEST.csv",
        "V20_147_PROMOTION_READINESS_LIMITATION_SUMMARY.csv",
        "V20_147_PROMOTION_READINESS_PACKET_SAFETY_BOUNDARY_AUDIT.csv",
        "V20_147_NEXT_STAGE_GATE.csv",
        "V20_146_PROMOTION_READINESS_CRITERIA_AUDIT.csv",
        "V20_146_BLOCKER_DISPOSITION_AUDIT.csv",
        "V20_145_FINAL_HUMAN_DECISION_RECORD.csv",
    ]:
        shutil.copy2(CONSOLIDATION / filename, temp / filename)


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["promotion_readiness_operator_review_status"] == "BLOCKED_V20_148_PROMOTION_READINESS_OPERATOR_REVIEW"
        assert decision["v20_149_promotion_readiness_operator_decision_capture_allowed"] == "FALSE"
        assert decision["promotion_ready"] == "FALSE"


def test_auto_selected_operator_action_cannot_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        original_builder = module.build_review

        def auto_selecting_builder(selected_id, packet, manifest_rows, criteria_rows, limitation_rows):
            review, options, required = original_builder(selected_id, packet, manifest_rows, criteria_rows, limitation_rows)
            review[0]["operator_action_auto_selected"] = "TRUE"
            review[0]["selected_operator_action"] = "APPROVE_PROMOTION_READINESS_FOR_STAGING"
            return review, options, required

        module.build_review = auto_selecting_builder
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["promotion_readiness_operator_review_status"] == "BLOCKED_V20_148_PROMOTION_READINESS_OPERATOR_REVIEW"
        assert decision["no_operator_action_auto_selected"] == "FALSE"


def test_official_scope_cannot_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        packet = read_csv(module.IN_PACKET)
        packet[0]["readiness_packet_scope"] = "OFFICIAL_PROMOTION_PACKET"
        write_csv(module.IN_PACKET, packet)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["promotion_readiness_operator_review_status"] == "BLOCKED_V20_148_PROMOTION_READINESS_OPERATOR_REVIEW"
        assert decision["packet_requirements_met"] == "FALSE"


def test_blocked_input_cases_produce_blocked_not_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        gate = read_csv(module.IN_GATE)
        gate[0]["v20_148_promotion_readiness_operator_review_allowed"] = "FALSE"
        write_csv(module.IN_GATE, gate)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["promotion_readiness_operator_review_status"] == "BLOCKED_V20_148_PROMOTION_READINESS_OPERATOR_REVIEW"
        assert decision["v20_149_promotion_readiness_operator_decision_capture_allowed"] == "FALSE"


def test_promotion_readiness_operator_review() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.147 outputs were mutated"
    stdout = result.stdout
    for expected in [
        "PARTIAL_PASS_V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_AWAITING_OPERATOR_INPUT",
        "V20_147_GATE_CONSUMED=TRUE",
        "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_ALLOWED_BY_V147=TRUE",
        "V20_147_FINAL_STATUS=PASS_V20_147_PROMOTION_READINESS_PACKET_READY_FOR_V20_148",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "OPERATOR_REVIEW_PACKET_ROW_COUNT=1",
        "OPERATOR_REVIEW_OPTIONS_AUDIT_ROW_COUNT=3",
        "OPERATOR_REQUIRED_ACTIONS_ROW_COUNT=1",
        "PACKET_REQUIREMENTS_MET=TRUE",
        "OPERATOR_ACTIONS_COMPLETE=TRUE",
        "DEFAULT_OPERATOR_ACTION_VALID=TRUE",
        "OPERATOR_ACTION_AUTO_SELECTED_COUNT=0",
        "NO_OPERATOR_ACTION_AUTO_SELECTED=TRUE",
        "OPERATOR_INPUT_REQUIRED_BEFORE_V20_149=TRUE",
        "EVIDENCE_ACCEPTANCE=TRUE",
        "OPERATOR_ACCEPTANCE=TRUE",
        "PROMOTION_READY=FALSE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_ALLOWED=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"

    decision = read_csv(OUT_DECISION)
    packet = read_csv(OUT_PACKET)
    options = read_csv(OUT_OPTIONS)
    required = read_csv(OUT_REQUIRED)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    d = decision[0]
    p = packet[0]
    assert d["promotion_readiness_operator_review_status"] == "PARTIAL_PASS_V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_AWAITING_OPERATOR_INPUT"
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert len(packet) == 1
    assert set(p["allowed_operator_actions"].split(";")) == OPERATOR_ACTIONS
    assert p["default_operator_action"] == DEFAULT_ACTION
    assert p["selected_operator_action"] == ""
    assert p["operator_action_auto_selected"] == "FALSE"
    assert p["operator_input_required_before_v20_149"] == "TRUE"
    assert len(options) == 3
    assert {row["operator_action_option"] for row in options} == OPERATOR_ACTIONS
    assert all(row["option_auto_selected"] == "FALSE" and row["option_requires_explicit_operator_input"] == "TRUE" for row in options)
    assert len(required) == 1
    assert required[0]["operator_action_selected"] == "FALSE"
    assert required[0]["selected_operator_action"] == ""
    assert required[0]["operator_input_required_before_v20_149"] == "TRUE"
    assert required[0]["promotion_readiness_decision_capture_allowed_before_input"] == "FALSE"
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["operator_input_required_before_v20_149"] == "TRUE"
    assert gate[0]["v20_149_promotion_readiness_operator_decision_capture_allowed"] == "TRUE"
    assert gate[0]["promotion_ready"] == "FALSE"
    for rows in [decision, packet, options, required, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_auto_selected_operator_action_cannot_pass()
    test_official_scope_cannot_pass()
    test_blocked_input_cases_produce_blocked_not_pass()
    test_promotion_readiness_operator_review()
    print("PASS_V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_TESTS")

