#!/usr/bin/env python
"""Tests for V20.142 third-round operator review packet."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_142_third_round_operator_review_packet.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
REQUIRED_OPTIONS = {"ACCEPT_THIRD_ROUND_EVIDENCE_WITH_LIMITATION", "REJECT_THIRD_ROUND_EVIDENCE_KEEP_BLOCKED", "REQUEST_FINAL_OPERATOR_ESCALATION"}

OUT_DECISION = CONSOLIDATION / "V20_142_THIRD_ROUND_OPERATOR_REVIEW_PACKET_DECISION.csv"
OUT_PACKET = CONSOLIDATION / "V20_142_THIRD_ROUND_OPERATOR_REVIEW_PACKET.csv"
OUT_SUMMARY = CONSOLIDATION / "V20_142_THIRD_ROUND_REVIEW_SUMMARY_AUDIT.csv"
OUT_OPTIONS = CONSOLIDATION / "V20_142_THIRD_ROUND_REVIEW_OPTIONS_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_142_THIRD_ROUND_OPERATOR_REVIEW_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_142_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_142_THIRD_ROUND_OPERATOR_REVIEW_PACKET_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_PACKET, OUT_SUMMARY, OUT_OPTIONS, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = sorted(
    path
    for path in CONSOLIDATION.glob("V20_*")
    if path.is_file() and any(path.name.startswith(f"V20_{stage}_") for stage in range(109, 142))
)
REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_141_gate_consumed", "v20_142_third_round_operator_review_packet_allowed_by_v141", "v20_141_final_status", "selected_repair_scenario_id", "covered_third_round_blocker_count", "third_round_operator_review_packet_row_count", "every_covered_third_round_blocker_has_review_packet", "third_round_review_summary_audit_row_count", "third_round_review_options_audit_row_count", "evidence_acceptance", "operator_acceptance", "promotion_ready", "v20_143_third_round_operator_decision_capture_allowed", "third_round_operator_review_packet_status"},
    OUT_PACKET: {"source_third_round_blocker_coverage_audit_id", "source_remaining_evidence_blocker_status_id", "source_third_round_evidence_plan_id", "source_third_round_evidence_result_audit_id", "blocker_category", "current_blocker_status", "third_round_evidence_coverage_status", "third_round_evidence_source_artifacts", "third_round_dry_run_result_summary", "remaining_limitation_summary", "operator_review_question", "available_review_options", "conservative_default", "evidence_acceptance", "operator_acceptance", "promotion_ready", "ticker_rows_created"},
    OUT_SUMMARY: {"source_third_round_operator_review_packet_id", "source_third_round_blocker_coverage_audit_id", "blocker_category", "third_round_evidence_coverage_status", "third_round_dry_run_result_status", "third_round_review_summary", "operator_review_required", "evidence_acceptance", "operator_acceptance", "promotion_ready"},
    OUT_OPTIONS: {"source_third_round_operator_review_packet_id", "blocker_category", "review_option", "option_available", "option_consequence", "recommended_default", "evidence_acceptance", "operator_acceptance", "promotion_ready"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_141_gate_consumed", "selected_repair_scenario_id", "evidence_acceptance", "operator_acceptance", "promotion_ready", "v20_143_third_round_operator_decision_capture_allowed", "third_round_operator_review_packet_status"},
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
    spec = importlib.util.spec_from_file_location("v20_142_third_round_operator_review_packet_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    mapping = {
        "IN_DECISION": "V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_DECISION.csv",
        "IN_PLAN_RECON": "V20_141_THIRD_ROUND_PLAN_RECONCILIATION_AUDIT.csv",
        "IN_RESULT_RECON": "V20_141_THIRD_ROUND_RESULT_RECONCILIATION_AUDIT.csv",
        "IN_COVERAGE": "V20_141_THIRD_ROUND_BLOCKER_COVERAGE_AUDIT.csv",
        "IN_SAFETY": "V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_SAFETY_BOUNDARY_AUDIT.csv",
        "IN_GATE": "V20_141_NEXT_STAGE_GATE.csv",
        "IN_DRY_RESULT": "V20_140_THIRD_ROUND_EVIDENCE_RESULT_AUDIT.csv",
        "IN_DRY_GAP": "V20_140_THIRD_ROUND_EVIDENCE_GAP_STATUS_AUDIT.csv",
        "IN_PLAN": "V20_139_THIRD_ROUND_EVIDENCE_PLAN.csv",
        "IN_RECORD": "V20_138_SECOND_ROUND_OPERATOR_DECISION_RECORD.csv",
    }
    for attr, filename in mapping.items():
        setattr(module, attr, temp / filename)
    module.REQUIRED_INPUTS = [getattr(module, attr) for attr in mapping]
    module.UPSTREAM_HASH_INPUTS = module.REQUIRED_INPUTS
    module.OUT_DECISION = temp / "V20_142_THIRD_ROUND_OPERATOR_REVIEW_PACKET_DECISION.csv"
    module.OUT_PACKET = temp / "V20_142_THIRD_ROUND_OPERATOR_REVIEW_PACKET.csv"
    module.OUT_SUMMARY = temp / "V20_142_THIRD_ROUND_REVIEW_SUMMARY_AUDIT.csv"
    module.OUT_OPTIONS = temp / "V20_142_THIRD_ROUND_REVIEW_OPTIONS_AUDIT.csv"
    module.OUT_SAFETY = temp / "V20_142_THIRD_ROUND_OPERATOR_REVIEW_SAFETY_BOUNDARY_AUDIT.csv"
    module.OUT_GATE = temp / "V20_142_NEXT_STAGE_GATE.csv"
    module.REPORT = temp / "V20_142_THIRD_ROUND_OPERATOR_REVIEW_PACKET_REPORT.md"


def copy_required_inputs(temp: Path) -> None:
    for filename in [
        "V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_DECISION.csv",
        "V20_141_THIRD_ROUND_PLAN_RECONCILIATION_AUDIT.csv",
        "V20_141_THIRD_ROUND_RESULT_RECONCILIATION_AUDIT.csv",
        "V20_141_THIRD_ROUND_BLOCKER_COVERAGE_AUDIT.csv",
        "V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_SAFETY_BOUNDARY_AUDIT.csv",
        "V20_141_NEXT_STAGE_GATE.csv",
        "V20_140_THIRD_ROUND_EVIDENCE_RESULT_AUDIT.csv",
        "V20_140_THIRD_ROUND_EVIDENCE_GAP_STATUS_AUDIT.csv",
        "V20_139_THIRD_ROUND_EVIDENCE_PLAN.csv",
        "V20_138_SECOND_ROUND_OPERATOR_DECISION_RECORD.csv",
    ]:
        shutil.copy2(CONSOLIDATION / filename, temp / filename)


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        assert module.main() == 0
        blocked = read_csv(module.OUT_DECISION)[0]
        assert blocked["third_round_operator_review_packet_status"] == "BLOCKED_V20_142_THIRD_ROUND_OPERATOR_REVIEW_PACKET"
        assert blocked["v20_143_third_round_operator_decision_capture_allowed"] == "FALSE"
        assert blocked["promotion_ready"] == "FALSE"


def test_missing_review_packet_cannot_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        original_builder = module.build_packet_artifacts

        def incomplete_builder(selected_id, covered_rows, dry_result_rows, dry_gap_rows, plan_rows, record_rows):
            packet, summary, options = original_builder(selected_id, covered_rows, dry_result_rows, dry_gap_rows, plan_rows, record_rows)
            return packet[:-1], summary[:-1], [row for row in options if row["source_third_round_operator_review_packet_id"] != packet[-1]["third_round_operator_review_packet_id"]]

        module.build_packet_artifacts = incomplete_builder
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["third_round_operator_review_packet_status"] == "BLOCKED_V20_142_THIRD_ROUND_OPERATOR_REVIEW_PACKET"
        assert decision["every_covered_third_round_blocker_has_review_packet"] == "FALSE"
        assert decision["v20_143_third_round_operator_decision_capture_allowed"] == "FALSE"


def test_blocked_input_cases_produce_blocked_not_pass() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_required_inputs(temp)
        patch_module_to_temp(module, temp)
        gate = read_csv(module.IN_GATE)
        gate[0]["v20_142_third_round_operator_review_packet_allowed"] = "FALSE"
        write_csv(module.IN_GATE, gate)
        assert module.main() == 0
        decision = read_csv(module.OUT_DECISION)[0]
        assert decision["third_round_operator_review_packet_status"] == "BLOCKED_V20_142_THIRD_ROUND_OPERATOR_REVIEW_PACKET"
        assert decision["third_round_operator_review_packet_status"] != "PASS_V20_142_THIRD_ROUND_OPERATOR_REVIEW_PACKET_READY_FOR_V20_143"
        assert decision["v20_143_third_round_operator_decision_capture_allowed"] == "FALSE"


def test_third_round_operator_review_packet() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.141 outputs were mutated"
    stdout = result.stdout
    assert "PASS_V20_142_THIRD_ROUND_OPERATOR_REVIEW_PACKET_READY_FOR_V20_143" in stdout
    for expected in [
        "V20_141_GATE_CONSUMED=TRUE",
        "V20_142_THIRD_ROUND_OPERATOR_REVIEW_PACKET_ALLOWED_BY_V141=TRUE",
        "V20_141_FINAL_STATUS=PASS_V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_READY_FOR_V20_142",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "SELECTED_SCENARIO_MATCHES_V20_141=TRUE",
        "COVERED_THIRD_ROUND_BLOCKER_COUNT=2",
        "THIRD_ROUND_OPERATOR_REVIEW_PACKET_ROW_COUNT=2",
        "EVERY_COVERED_THIRD_ROUND_BLOCKER_HAS_REVIEW_PACKET=TRUE",
        "THIRD_ROUND_REVIEW_SUMMARY_AUDIT_ROW_COUNT=2",
        "THIRD_ROUND_REVIEW_OPTIONS_AUDIT_ROW_COUNT=6",
        "ALL_PACKET_ROWS_INCLUDE_REQUIRED_OPTIONS=TRUE",
        "ALL_PACKET_ROWS_DEFAULT_REQUEST_FINAL_OPERATOR_ESCALATION=TRUE",
        "EVIDENCE_ACCEPTANCE=FALSE",
        "OPERATOR_ACCEPTANCE=FALSE",
        "PROMOTION_READY=FALSE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_143_THIRD_ROUND_OPERATOR_DECISION_CAPTURE_ALLOWED=TRUE",
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
    summary = read_csv(OUT_SUMMARY)
    options = read_csv(OUT_OPTIONS)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    covered = [row for row in read_csv(CONSOLIDATION / "V20_141_THIRD_ROUND_BLOCKER_COVERAGE_AUDIT.csv") if row["coverage_status"] == "THIRD_ROUND_COVERED_BY_EVIDENCE_FOR_REVIEW"]
    d = decision[0]
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["third_round_operator_review_packet_status"] == "PASS_V20_142_THIRD_ROUND_OPERATOR_REVIEW_PACKET_READY_FOR_V20_143"
    assert d["evidence_acceptance"] == "FALSE"
    assert d["operator_acceptance"] == "FALSE"
    assert d["promotion_ready"] == "FALSE"
    assert d["v20_143_third_round_operator_decision_capture_allowed"] == "TRUE"
    assert len(packet) == len(covered)
    assert {row["source_third_round_blocker_coverage_audit_id"] for row in packet} == {row["third_round_blocker_coverage_audit_id"] for row in covered}
    assert all(set(row["available_review_options"].split(";")) == REQUIRED_OPTIONS for row in packet)
    assert all(row["conservative_default"] == "REQUEST_FINAL_OPERATOR_ESCALATION" and row["evidence_acceptance"] == "FALSE" and row["operator_acceptance"] == "FALSE" and row["promotion_ready"] == "FALSE" and row["ticker_rows_created"] == "0" for row in packet)
    assert summary
    assert options
    option_map = {}
    for row in options:
        option_map.setdefault(row["source_third_round_operator_review_packet_id"], set()).add(row["review_option"])
    assert all(option_map[row["third_round_operator_review_packet_id"]] == REQUIRED_OPTIONS for row in packet)
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["evidence_acceptance"] == "FALSE"
    assert gate[0]["operator_acceptance"] == "FALSE"
    assert gate[0]["promotion_ready"] == "FALSE"
    assert gate[0]["v20_143_third_round_operator_decision_capture_allowed"] == "TRUE"
    for rows in [decision, packet, summary, options, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_missing_review_packet_cannot_pass()
    test_blocked_input_cases_produce_blocked_not_pass()
    test_third_round_operator_review_packet()
    print("PASS_V20_142_THIRD_ROUND_OPERATOR_REVIEW_PACKET_TESTS")

