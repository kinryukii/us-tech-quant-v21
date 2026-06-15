#!/usr/bin/env python
"""Tests for V20.124 operator decision update."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_124_operator_decision_update.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"

OUT_DECISION = CONSOLIDATION / "V20_124_OPERATOR_DECISION_UPDATE_DECISION.csv"
OUT_UPDATED = CONSOLIDATION / "V20_124_UPDATED_OPERATOR_DECISION_RECORD.csv"
OUT_RATIONALE = CONSOLIDATION / "V20_124_DECISION_UPDATE_RATIONALE_AUDIT.csv"
OUT_REMAINING = CONSOLIDATION / "V20_124_REMAINING_OPERATOR_REVIEW_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_124_OPERATOR_DECISION_UPDATE_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_124_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_124_OPERATOR_DECISION_UPDATE_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_UPDATED, OUT_RATIONALE, OUT_REMAINING, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = [CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116", "117", "118", "119", "120", "121", "122", "123"]]
UPSTREAM.extend([
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    CONSOLIDATION / "V20_123_PENDING_EVIDENCE_FOLLOWUP_DECISION.csv",
    CONSOLIDATION / "V20_123_EVIDENCE_FOLLOWUP_RESULT_AUDIT.csv",
    CONSOLIDATION / "V20_123_EVIDENCE_GAP_CLOSURE_AUDIT.csv",
    CONSOLIDATION / "V20_123_PENDING_DECISION_STATUS_UPDATE_AUDIT.csv",
    CONSOLIDATION / "V20_123_EVIDENCE_FOLLOWUP_SAFETY_BOUNDARY_AUDIT.csv",
    CONSOLIDATION / "V20_122_PENDING_DECISION_RESOLUTION_PLAN.csv",
    CONSOLIDATION / "V20_120_OPERATOR_DECISION_RECORD.csv",
])
REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_123_gate_consumed", "selected_repair_scenario_id", "updated_operator_decision_record_count", "every_v123_status_update_carried_forward", "pending_operator_decision_count", "operator_acceptance_true_count", "promotion_ready", "v20_125_operator_review_action_packet_allowed", "operator_decision_update_status"},
    OUT_UPDATED: {"source_operator_decision_record_id", "source_v123_status_update_id", "blocker_category", "gap_closure_status", "updated_decision_status", "operator_acceptance", "valid_human_acceptance_evidence", "promotion_ready", "ticker_rows_created"},
    OUT_RATIONALE: {"source_operator_decision_record_id", "blocker_category", "gap_closure_status", "decision_update_rationale", "operator_acceptance", "promotion_ready"},
    OUT_REMAINING: {"source_operator_decision_record_id", "blocker_category", "remaining_review_required", "remaining_review_reason", "promotion_ready"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_123_gate_consumed", "selected_repair_scenario_id", "operator_acceptance", "promotion_ready", "v20_125_operator_review_action_packet_allowed", "operator_decision_update_status"},
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
    spec = importlib.util.spec_from_file_location("v20_124_operator_decision_update_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        for name in ["IN_DECISION", "IN_RESULT", "IN_CLOSURE", "IN_STATUS", "IN_SAFETY", "IN_GATE", "IN_V122_PLAN", "IN_V120_RECORD"]:
            setattr(module, name, temp / f"missing_{name}.csv")
        module.REQUIRED_INPUTS = [module.IN_DECISION, module.IN_RESULT, module.IN_CLOSURE, module.IN_STATUS, module.IN_SAFETY, module.IN_GATE, module.IN_V122_PLAN, module.IN_V120_RECORD]
        module.OUT_DECISION = temp / "V20_124_OPERATOR_DECISION_UPDATE_DECISION.csv"
        module.OUT_UPDATED = temp / "V20_124_UPDATED_OPERATOR_DECISION_RECORD.csv"
        module.OUT_RATIONALE = temp / "V20_124_DECISION_UPDATE_RATIONALE_AUDIT.csv"
        module.OUT_REMAINING = temp / "V20_124_REMAINING_OPERATOR_REVIEW_AUDIT.csv"
        module.OUT_SAFETY = temp / "V20_124_OPERATOR_DECISION_UPDATE_SAFETY_BOUNDARY_AUDIT.csv"
        module.OUT_GATE = temp / "V20_124_NEXT_STAGE_GATE.csv"
        module.REPORT = temp / "V20_124_OPERATOR_DECISION_UPDATE_REPORT.md"
        assert module.main() == 0
        blocked = read_csv(module.OUT_DECISION)[0]
        assert blocked["operator_decision_update_status"] == "BLOCKED_V20_124_OPERATOR_DECISION_UPDATE"
        assert blocked["promotion_ready"] == "FALSE"


def test_operator_decision_update() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.123 outputs were mutated"
    stdout = result.stdout
    assert "PARTIAL_PASS_V20_124_OPERATOR_DECISIONS_STILL_REQUIRE_REVIEW_READY_FOR_V20_125" in stdout
    for expected in [
        "V20_123_GATE_CONSUMED=TRUE",
        "V20_124_OPERATOR_DECISION_UPDATE_ALLOWED_BY_V123=TRUE",
        "V20_123_FINAL_STATUS=PARTIAL_PASS_V20_123_EVIDENCE_PARTIALLY_CLOSED_READY_FOR_V20_124",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "SELECTED_SCENARIO_MATCHES_V20_123=TRUE",
        "V20_123_STATUS_UPDATE_ROW_COUNT=2",
        "UPDATED_OPERATOR_DECISION_RECORD_COUNT=2",
        "EVERY_V123_STATUS_UPDATE_CARRIED_FORWARD=TRUE",
        "PENDING_OPERATOR_DECISION_COUNT=2",
        "OPERATOR_ACCEPTANCE_TRUE_COUNT=0",
        "REMAINING_OPERATOR_REVIEW_COUNT=2",
        "PROMOTION_READY=FALSE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_125_OPERATOR_REVIEW_ACTION_PACKET_ALLOWED=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"
    decision = read_csv(OUT_DECISION)
    updated = read_csv(OUT_UPDATED)
    rationale = read_csv(OUT_RATIONALE)
    remaining = read_csv(OUT_REMAINING)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    d = decision[0]
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["promotion_ready"] == "FALSE"
    assert d["operator_decision_update_status"] == "PARTIAL_PASS_V20_124_OPERATOR_DECISIONS_STILL_REQUIRE_REVIEW_READY_FOR_V20_125"
    assert len(updated) == 2
    assert len(rationale) == 2
    assert len(remaining) == 2
    assert all(row["updated_decision_status"] == "PENDING_OPERATOR_DECISION" and row["operator_acceptance"] == "FALSE" and row["promotion_ready"] == "FALSE" and row["ticker_rows_created"] == "0" for row in updated)
    assert all(row["operator_acceptance"] == "FALSE" and row["promotion_ready"] == "FALSE" for row in rationale)
    assert all(row["remaining_review_required"] == "TRUE" and row["promotion_ready"] == "FALSE" for row in remaining)
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["operator_acceptance"] == "FALSE"
    assert gate[0]["promotion_ready"] == "FALSE"
    assert gate[0]["v20_125_operator_review_action_packet_allowed"] == "TRUE"
    assert d["operator_decision_update_status"].startswith("PASS_") == (d["remaining_operator_review_count"] == "0" and d["all_required_decisions_accepted_with_valid_human_evidence"] == "TRUE")
    for rows in [decision, updated, rationale, remaining, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_operator_decision_update()
    print("PASS_V20_124_OPERATOR_DECISION_UPDATE_TESTS")
