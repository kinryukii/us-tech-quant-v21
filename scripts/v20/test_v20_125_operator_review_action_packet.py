#!/usr/bin/env python
"""Tests for V20.125 operator review action packet."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_125_operator_review_action_packet.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
REQUIRED_OPTIONS = {"ACCEPT_WITH_LIMITATION", "REJECT_AND_KEEP_BLOCKED", "NEED_MORE_EVIDENCE"}

OUT_DECISION = CONSOLIDATION / "V20_125_OPERATOR_REVIEW_ACTION_PACKET_DECISION.csv"
OUT_PACKET = CONSOLIDATION / "V20_125_OPERATOR_ACTION_PACKET.csv"
OUT_OPTIONS = CONSOLIDATION / "V20_125_OPERATOR_ACTION_OPTIONS_AUDIT.csv"
OUT_EVIDENCE = CONSOLIDATION / "V20_125_OPERATOR_ACTION_EVIDENCE_SUMMARY.csv"
OUT_SAFETY = CONSOLIDATION / "V20_125_OPERATOR_ACTION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_125_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_125_OPERATOR_REVIEW_ACTION_PACKET_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_PACKET, OUT_OPTIONS, OUT_EVIDENCE, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = [CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116", "117", "118", "119", "120", "121", "122", "123", "124"]]
UPSTREAM.extend([
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    CONSOLIDATION / "V20_124_OPERATOR_DECISION_UPDATE_DECISION.csv",
    CONSOLIDATION / "V20_124_UPDATED_OPERATOR_DECISION_RECORD.csv",
    CONSOLIDATION / "V20_124_DECISION_UPDATE_RATIONALE_AUDIT.csv",
    CONSOLIDATION / "V20_124_REMAINING_OPERATOR_REVIEW_AUDIT.csv",
    CONSOLIDATION / "V20_124_OPERATOR_DECISION_UPDATE_SAFETY_BOUNDARY_AUDIT.csv",
    CONSOLIDATION / "V20_123_EVIDENCE_GAP_CLOSURE_AUDIT.csv",
    CONSOLIDATION / "V20_122_PENDING_DECISION_RESOLUTION_PLAN.csv",
    CONSOLIDATION / "V20_119_OPERATOR_REVIEW_REQUIRED_DECISIONS.csv",
    CONSOLIDATION / "V20_118_REMAINING_BLOCKER_AUDIT.csv",
])
REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_124_gate_consumed", "selected_repair_scenario_id", "remaining_pending_decision_count", "action_packet_row_count", "every_remaining_pending_decision_has_action_packet", "operator_acceptance", "promotion_ready", "v20_126_operator_action_capture_allowed", "operator_review_action_packet_status"},
    OUT_PACKET: {"source_remaining_review_id", "source_operator_decision_record_id", "blocker_category", "pending_reason", "evidence_status", "related_evidence_files", "available_operator_actions", "recommended_conservative_default", "operator_acceptance", "promotion_ready", "ticker_rows_created"},
    OUT_OPTIONS: {"source_action_packet_id", "blocker_category", "operator_action", "action_available", "action_consequence", "recommended_default", "promotion_ready"},
    OUT_EVIDENCE: {"source_action_packet_id", "blocker_category", "evidence_status", "related_evidence_files", "evidence_summary", "operator_review_required", "promotion_ready"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_124_gate_consumed", "selected_repair_scenario_id", "operator_acceptance", "promotion_ready", "v20_126_operator_action_capture_allowed", "operator_review_action_packet_status"},
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
    spec = importlib.util.spec_from_file_location("v20_125_operator_review_action_packet_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        for name in ["IN_DECISION", "IN_UPDATED", "IN_RATIONALE", "IN_REMAINING", "IN_SAFETY", "IN_GATE", "IN_V123_CLOSURE", "IN_V122_PLAN", "IN_V119_REQUIRED", "IN_V118_REMAINING"]:
            setattr(module, name, temp / f"missing_{name}.csv")
        module.REQUIRED_INPUTS = [module.IN_DECISION, module.IN_UPDATED, module.IN_RATIONALE, module.IN_REMAINING, module.IN_SAFETY, module.IN_GATE, module.IN_V123_CLOSURE, module.IN_V122_PLAN, module.IN_V119_REQUIRED, module.IN_V118_REMAINING]
        module.OUT_DECISION = temp / "V20_125_OPERATOR_REVIEW_ACTION_PACKET_DECISION.csv"
        module.OUT_PACKET = temp / "V20_125_OPERATOR_ACTION_PACKET.csv"
        module.OUT_OPTIONS = temp / "V20_125_OPERATOR_ACTION_OPTIONS_AUDIT.csv"
        module.OUT_EVIDENCE = temp / "V20_125_OPERATOR_ACTION_EVIDENCE_SUMMARY.csv"
        module.OUT_SAFETY = temp / "V20_125_OPERATOR_ACTION_SAFETY_BOUNDARY_AUDIT.csv"
        module.OUT_GATE = temp / "V20_125_NEXT_STAGE_GATE.csv"
        module.REPORT = temp / "V20_125_OPERATOR_REVIEW_ACTION_PACKET_REPORT.md"
        assert module.main() == 0
        blocked = read_csv(module.OUT_DECISION)[0]
        assert blocked["operator_review_action_packet_status"] == "BLOCKED_V20_125_OPERATOR_REVIEW_ACTION_PACKET"
        assert blocked["promotion_ready"] == "FALSE"


def test_operator_review_action_packet() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.124 outputs were mutated"
    stdout = result.stdout
    assert "PASS_V20_125_OPERATOR_REVIEW_ACTION_PACKET_READY_FOR_V20_126" in stdout
    for expected in [
        "V20_124_GATE_CONSUMED=TRUE",
        "V20_125_OPERATOR_REVIEW_ACTION_PACKET_ALLOWED_BY_V124=TRUE",
        "V20_124_FINAL_STATUS=PARTIAL_PASS_V20_124_OPERATOR_DECISIONS_STILL_REQUIRE_REVIEW_READY_FOR_V20_125",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "SELECTED_SCENARIO_MATCHES_V20_124=TRUE",
        "REMAINING_PENDING_DECISION_COUNT=2",
        "ACTION_PACKET_ROW_COUNT=2",
        "EVERY_REMAINING_PENDING_DECISION_HAS_ACTION_PACKET=TRUE",
        "ACTION_OPTIONS_AUDIT_ROW_COUNT=6",
        "EVIDENCE_SUMMARY_ROW_COUNT=2",
        "ALL_PACKET_ROWS_INCLUDE_REQUIRED_OPTIONS=TRUE",
        "ALL_PACKET_ROWS_DEFAULT_NEED_MORE_EVIDENCE=TRUE",
        "OPERATOR_ACCEPTANCE=FALSE",
        "PROMOTION_READY=FALSE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_126_OPERATOR_ACTION_CAPTURE_ALLOWED=TRUE",
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
    evidence = read_csv(OUT_EVIDENCE)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    d = decision[0]
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["operator_review_action_packet_status"] == "PASS_V20_125_OPERATOR_REVIEW_ACTION_PACKET_READY_FOR_V20_126"
    assert d["promotion_ready"] == "FALSE"
    assert len(packet) == 2
    assert len(options) == 6
    assert len(evidence) == 2
    for row in packet:
        assert set(row["available_operator_actions"].split(";")) == REQUIRED_OPTIONS
        assert row["recommended_conservative_default"] == "NEED_MORE_EVIDENCE"
        assert row["operator_acceptance"] == "FALSE"
        assert row["promotion_ready"] == "FALSE"
        assert row["ticker_rows_created"] == "0"
    assert {row["operator_action"] for row in options} == REQUIRED_OPTIONS
    assert all(row["action_available"] == "TRUE" and row["promotion_ready"] == "FALSE" for row in options)
    assert all(row["operator_review_required"] == "TRUE" and row["promotion_ready"] == "FALSE" for row in evidence)
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["operator_acceptance"] == "FALSE"
    assert gate[0]["promotion_ready"] == "FALSE"
    assert gate[0]["v20_126_operator_action_capture_allowed"] == "TRUE"
    assert d["operator_review_action_packet_status"].startswith("PASS_") == (d["every_remaining_pending_decision_has_action_packet"] == "TRUE" and d["all_packet_rows_include_required_options"] == "TRUE")
    for rows in [decision, packet, options, evidence, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_operator_review_action_packet()
    print("PASS_V20_125_OPERATOR_REVIEW_ACTION_PACKET_TESTS")
