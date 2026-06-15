#!/usr/bin/env python
"""Tests for V20.149 promotion-readiness operator decision capture."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_149_promotion_readiness_operator_decision_capture.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
SELECTED_ACTION = "APPROVE_PROMOTION_READINESS_FOR_STAGING"

OUT_DECISION = CONSOLIDATION / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_DECISION.csv"
OUT_INPUT = CONSOLIDATION / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_INPUT_AUDIT.csv"
OUT_RECORD = CONSOLIDATION / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_RECORD.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_VALIDATION_AUDIT.csv"
OUT_CONSEQUENCE = CONSOLIDATION / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CONSEQUENCE_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_149_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_INPUT, OUT_RECORD, OUT_VALIDATION, OUT_CONSEQUENCE, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = sorted(
    path
    for path in CONSOLIDATION.glob("V20_*")
    if path.is_file() and any(path.name.startswith(f"V20_{stage}_") for stage in range(109, 149))
)
REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_148_gate_consumed", "v20_149_promotion_readiness_operator_decision_capture_allowed_by_v148", "operator_input_required_before_v20_149", "v20_148_final_status", "selected_repair_scenario_id", "operator_decision_input_audit_row_count", "operator_decision_record_count", "selected_operator_action", "operator_action_valid", "operator_action_explicit", "operator_action_auto_selected", "operator_decision_status", "staging_review_allowed", "formal_activation_allowed", "evidence_acceptance", "operator_acceptance", "promotion_ready", "v20_150_staging_review_packet_allowed", "promotion_readiness_operator_decision_capture_status"},
    OUT_INPUT: {"source_promotion_readiness_operator_review_packet_id", "selected_operator_action", "operator_scope", "operator_input_source", "operator_action_auto_selected", "promotion_ready"},
    OUT_RECORD: {"source_promotion_readiness_operator_review_packet_id", "source_promotion_readiness_packet_id", "selected_operator_action", "operator_scope", "operator_decision_status", "staging_review_allowed", "formal_activation_allowed", "evidence_acceptance", "operator_acceptance", "promotion_ready", "ticker_rows_created"},
    OUT_VALIDATION: {"source_promotion_readiness_operator_review_packet_id", "selected_operator_action", "operator_action_valid", "operator_action_available_in_v148_options", "operator_action_explicit", "operator_action_auto_selected", "formal_activation_allowed", "operator_decision_valid", "promotion_ready"},
    OUT_CONSEQUENCE: {"source_promotion_readiness_operator_review_packet_id", "selected_operator_action", "operator_decision_status", "decision_consequence", "staging_review_allowed", "formal_activation_allowed", "promotion_ready"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_148_gate_consumed", "selected_repair_scenario_id", "staging_review_allowed", "formal_activation_allowed", "evidence_acceptance", "operator_acceptance", "promotion_ready", "v20_150_staging_review_packet_allowed", "promotion_readiness_operator_decision_capture_status"},
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
    spec = importlib.util.spec_from_file_location("v20_149_promotion_readiness_operator_decision_capture_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    mapping = {
        "IN_DECISION": "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_DECISION.csv",
        "IN_PACKET": "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_PACKET.csv",
        "IN_OPTIONS": "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_OPTIONS_AUDIT.csv",
        "IN_REQUIRED": "V20_148_PROMOTION_READINESS_OPERATOR_REQUIRED_ACTIONS.csv",
        "IN_SAFETY": "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_SAFETY_BOUNDARY_AUDIT.csv",
        "IN_GATE": "V20_148_NEXT_STAGE_GATE.csv",
        "IN_V147_PACKET": "V20_147_PROMOTION_READINESS_PACKET.csv",
        "IN_V147_MANIFEST": "V20_147_PROMOTION_READINESS_EVIDENCE_MANIFEST.csv",
        "IN_V147_LIMITATION": "V20_147_PROMOTION_READINESS_LIMITATION_SUMMARY.csv",
    }
    for attr, filename in mapping.items():
        setattr(module, attr, temp / filename)
    module.REQUIRED_INPUTS = [getattr(module, attr) for attr in mapping]
    module.UPSTREAM_HASH_INPUTS = module.REQUIRED_INPUTS
    module.OUT_DECISION = temp / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_DECISION.csv"
    module.OUT_INPUT = temp / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_INPUT_AUDIT.csv"
    module.OUT_RECORD = temp / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_RECORD.csv"
    module.OUT_VALIDATION = temp / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_VALIDATION_AUDIT.csv"
    module.OUT_CONSEQUENCE = temp / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CONSEQUENCE_AUDIT.csv"
    module.OUT_SAFETY = temp / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_SAFETY_BOUNDARY_AUDIT.csv"
    module.OUT_GATE = temp / "V20_149_NEXT_STAGE_GATE.csv"
    module.REPORT = temp / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_REPORT.md"


def copy_required_inputs(temp: Path) -> None:
    for filename in [
        "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_DECISION.csv",
        "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_PACKET.csv",
        "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_OPTIONS_AUDIT.csv",
        "V20_148_PROMOTION_READINESS_OPERATOR_REQUIRED_ACTIONS.csv",
        "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_SAFETY_BOUNDARY_AUDIT.csv",
        "V20_148_NEXT_STAGE_GATE.csv",
        "V20_147_PROMOTION_READINESS_PACKET.csv",
        "V20_147_PROMOTION_READINESS_EVIDENCE_MANIFEST.csv",
        "V20_147_PROMOTION_READINESS_LIMITATION_SUMMARY.csv",
    ]:
        shutil.copy2(CONSOLIDATION / filename, temp / filename)


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["promotion_readiness_operator_decision_capture_status"] == "BLOCKED_V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE"
        assert decision["v20_150_staging_review_packet_allowed"] == "FALSE"
        assert decision["promotion_ready"] == "FALSE"


def test_missing_operator_input_cannot_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        module.SELECTED_OPERATOR_ACTION = ""
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["promotion_readiness_operator_decision_capture_status"] == "BLOCKED_V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE"
        assert decision["operator_action_explicit"] == "FALSE"


def test_auto_selected_operator_action_cannot_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        original_build = module.build_capture

        def auto_build(selected_id, review_packet, action=module.SELECTED_OPERATOR_ACTION, auto_selected=False, formal_activation_override=None):
            return original_build(selected_id, review_packet, action, True, formal_activation_override)

        module.build_capture = auto_build
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["promotion_readiness_operator_decision_capture_status"] == "BLOCKED_V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE"
        assert decision["operator_action_auto_selected"] == "TRUE"


def test_formal_activation_allowed_cannot_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        original_build = module.build_capture

        def activation_build(selected_id, review_packet, action=module.SELECTED_OPERATOR_ACTION, auto_selected=False, formal_activation_override=None):
            return original_build(selected_id, review_packet, action, auto_selected, True)

        module.build_capture = activation_build
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["promotion_readiness_operator_decision_capture_status"] == "BLOCKED_V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE"
        assert decision["formal_activation_allowed"] == "TRUE"


def test_blocked_input_cases_produce_blocked_not_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        gate = read_csv(module.IN_GATE)
        gate[0]["v20_149_promotion_readiness_operator_decision_capture_allowed"] = "FALSE"
        write_csv(module.IN_GATE, gate)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["promotion_readiness_operator_decision_capture_status"] == "BLOCKED_V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE"
        assert decision["v20_150_staging_review_packet_allowed"] == "FALSE"


def test_promotion_readiness_operator_decision_capture() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.148 outputs were mutated"
    stdout = result.stdout
    for expected in [
        "PASS_V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_READY_FOR_V20_150",
        "V20_148_GATE_CONSUMED=TRUE",
        "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_ALLOWED_BY_V148=TRUE",
        "OPERATOR_INPUT_REQUIRED_BEFORE_V20_149=TRUE",
        "V20_148_FINAL_STATUS=PARTIAL_PASS_V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_AWAITING_OPERATOR_INPUT",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "OPERATOR_DECISION_INPUT_AUDIT_ROW_COUNT=1",
        "OPERATOR_DECISION_RECORD_COUNT=1",
        f"SELECTED_OPERATOR_ACTION={SELECTED_ACTION}",
        "OPERATOR_ACTION_VALID=TRUE",
        "OPERATOR_ACTION_EXPLICIT=TRUE",
        "OPERATOR_ACTION_AUTO_SELECTED=FALSE",
        "OPERATOR_DECISION_STATUS=APPROVED_FOR_STAGING_REVIEW_ONLY",
        "STAGING_REVIEW_ALLOWED=TRUE",
        "FORMAL_ACTIVATION_ALLOWED=FALSE",
        "EVIDENCE_ACCEPTANCE=TRUE",
        "OPERATOR_ACCEPTANCE=TRUE",
        "PROMOTION_READY=FALSE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_150_STAGING_REVIEW_PACKET_ALLOWED=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"

    decision = read_csv(OUT_DECISION)
    input_rows = read_csv(OUT_INPUT)
    record = read_csv(OUT_RECORD)
    validation = read_csv(OUT_VALIDATION)
    consequence = read_csv(OUT_CONSEQUENCE)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    d = decision[0]
    r = record[0]
    assert d["promotion_readiness_operator_decision_capture_status"] == "PASS_V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_READY_FOR_V20_150"
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert len(input_rows) == 1
    assert len(record) == 1
    assert input_rows[0]["selected_operator_action"] == SELECTED_ACTION
    assert input_rows[0]["operator_action_auto_selected"] == "FALSE"
    assert r["selected_operator_action"] == SELECTED_ACTION
    assert r["operator_decision_status"] == "APPROVED_FOR_STAGING_REVIEW_ONLY"
    assert r["staging_review_allowed"] == "TRUE"
    assert r["formal_activation_allowed"] == "FALSE"
    assert r["evidence_acceptance"] == "TRUE"
    assert r["operator_acceptance"] == "TRUE"
    assert r["promotion_ready"] == "FALSE"
    assert validation[0]["operator_decision_valid"] == "TRUE"
    assert validation[0]["formal_activation_allowed"] == "FALSE"
    assert consequence[0]["staging_review_allowed"] == "TRUE"
    assert consequence[0]["formal_activation_allowed"] == "FALSE"
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["v20_150_staging_review_packet_allowed"] == "TRUE"
    assert gate[0]["formal_activation_allowed"] == "FALSE"
    assert gate[0]["promotion_ready"] == "FALSE"
    for rows in [decision, input_rows, record, validation, consequence, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_missing_operator_input_cannot_pass()
    test_auto_selected_operator_action_cannot_pass()
    test_formal_activation_allowed_cannot_pass()
    test_blocked_input_cases_produce_blocked_not_pass()
    test_promotion_readiness_operator_decision_capture()
    print("PASS_V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_TESTS")

