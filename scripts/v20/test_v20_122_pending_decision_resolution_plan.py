#!/usr/bin/env python
"""Tests for V20.122 pending decision resolution plan."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_122_pending_decision_resolution_plan.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"

OUT_DECISION = CONSOLIDATION / "V20_122_PENDING_DECISION_RESOLUTION_PLAN_DECISION.csv"
OUT_PLAN = CONSOLIDATION / "V20_122_PENDING_DECISION_RESOLUTION_PLAN.csv"
OUT_EVIDENCE_GAP = CONSOLIDATION / "V20_122_REQUIRED_EVIDENCE_GAP_AUDIT.csv"
OUT_FOLLOWUP = CONSOLIDATION / "V20_122_REQUIRED_FOLLOWUP_ACTION_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_122_RESOLUTION_BOUNDARY_SAFETY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_122_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_122_PENDING_DECISION_RESOLUTION_PLAN_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_PLAN, OUT_EVIDENCE_GAP, OUT_FOLLOWUP, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = [CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116", "117", "118", "119", "120", "121"]]
UPSTREAM.extend(
    [
        CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
        CONSOLIDATION / "V20_121_OPERATOR_DECISION_REVIEW_GATE_DECISION.csv",
        CONSOLIDATION / "V20_121_PENDING_DECISION_GATE_AUDIT.csv",
        CONSOLIDATION / "V20_120_OPERATOR_DECISION_RECORD.csv",
        CONSOLIDATION / "V20_119_OPERATOR_REVIEW_REQUIRED_DECISIONS.csv",
        CONSOLIDATION / "V20_118_REMAINING_BLOCKER_AUDIT.csv",
    ]
)

REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_121_gate_consumed", "selected_repair_scenario_id", "pending_operator_decision_count", "resolution_plan_row_count", "promotion_ready", "v20_123_pending_evidence_followup_allowed", "pending_decision_resolution_plan_status"},
    OUT_PLAN: {"source_operator_decision_record_id", "source_required_decision_id", "blocker_category", "current_pending_reason", "missing_evidence", "required_followup_action", "expected_artifact_needed_to_resolve", "operator_judgment_still_required", "resolution_plan_complete"},
    OUT_EVIDENCE_GAP: {"blocker_category", "missing_evidence", "expected_artifact_needed_to_resolve", "evidence_gap_status"},
    OUT_FOLLOWUP: {"blocker_category", "required_followup_action", "operator_judgment_still_required", "followup_action_status"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_121_gate_consumed", "selected_repair_scenario_id", "promotion_ready", "v20_123_pending_evidence_followup_allowed", "pending_decision_resolution_plan_status"},
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
    spec = importlib.util.spec_from_file_location("v20_122_pending_decision_resolution_plan_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        for name in [
            "IN_V121_DECISION",
            "IN_V121_COMPLETENESS",
            "IN_V121_PENDING",
            "IN_V121_ACCEPTANCE",
            "IN_V121_PROMOTION",
            "IN_V121_SAFETY",
            "IN_V121_GATE",
            "IN_V120_RECORD",
            "IN_V120_UNRESOLVED",
            "IN_V119_REQUIRED",
            "IN_V118_REMAINING",
        ]:
            setattr(module, name, temp / f"missing_{name}.csv")
        module.REQUIRED_INPUTS = [
            module.IN_V121_DECISION,
            module.IN_V121_COMPLETENESS,
            module.IN_V121_PENDING,
            module.IN_V121_ACCEPTANCE,
            module.IN_V121_PROMOTION,
            module.IN_V121_SAFETY,
            module.IN_V121_GATE,
            module.IN_V120_RECORD,
            module.IN_V120_UNRESOLVED,
            module.IN_V119_REQUIRED,
            module.IN_V118_REMAINING,
        ]
        module.OUT_DECISION = temp / "V20_122_PENDING_DECISION_RESOLUTION_PLAN_DECISION.csv"
        module.OUT_PLAN = temp / "V20_122_PENDING_DECISION_RESOLUTION_PLAN.csv"
        module.OUT_EVIDENCE_GAP = temp / "V20_122_REQUIRED_EVIDENCE_GAP_AUDIT.csv"
        module.OUT_FOLLOWUP = temp / "V20_122_REQUIRED_FOLLOWUP_ACTION_AUDIT.csv"
        module.OUT_SAFETY = temp / "V20_122_RESOLUTION_BOUNDARY_SAFETY_AUDIT.csv"
        module.OUT_GATE = temp / "V20_122_NEXT_STAGE_GATE.csv"
        module.REPORT = temp / "V20_122_PENDING_DECISION_RESOLUTION_PLAN_REPORT.md"
        assert module.main() == 0
        blocked = read_csv(module.OUT_DECISION)[0]
        assert blocked["pending_decision_resolution_plan_status"] == "BLOCKED_V20_122_PENDING_DECISION_RESOLUTION_PLAN"
        assert blocked["promotion_ready"] == "FALSE"


def test_pending_decision_resolution_plan() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.121 outputs were mutated"
    stdout = result.stdout
    assert "PASS_V20_122_PENDING_DECISION_RESOLUTION_PLAN_READY_FOR_V20_123" in stdout
    for expected in [
        "V20_121_GATE_CONSUMED=TRUE",
        "V20_122_PENDING_DECISION_RESOLUTION_PLAN_ALLOWED_BY_V121=TRUE",
        "V20_121_FINAL_STATUS=PARTIAL_PASS_V20_121_OPERATOR_DECISIONS_STILL_PENDING_READY_FOR_V20_122",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "SELECTED_SCENARIO_MATCHES_V20_121=TRUE",
        "PENDING_OPERATOR_DECISION_COUNT=2",
        "RESOLUTION_PLAN_ROW_COUNT=2",
        "EVERY_PENDING_DECISION_HAS_RESOLUTION_PLAN=TRUE",
        "EVIDENCE_GAP_AUDIT_ROW_COUNT=2",
        "FOLLOWUP_ACTION_AUDIT_ROW_COUNT=2",
        "PROMOTION_READY=FALSE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_123_PENDING_EVIDENCE_FOLLOWUP_ALLOWED=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"
    decision = read_csv(OUT_DECISION)
    plan = read_csv(OUT_PLAN)
    gaps = read_csv(OUT_EVIDENCE_GAP)
    followup = read_csv(OUT_FOLLOWUP)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    d = decision[0]
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["promotion_ready"] == "FALSE"
    assert d["pending_decision_resolution_plan_status"] == "PASS_V20_122_PENDING_DECISION_RESOLUTION_PLAN_READY_FOR_V20_123"
    assert len(plan) == 2
    assert len(gaps) == 2
    assert len(followup) == 2
    assert all(row["resolution_plan_complete"] == "TRUE" and row["operator_judgment_still_required"] == "TRUE" and row["promotion_ready"] == "FALSE" for row in plan)
    assert all(row["missing_evidence"] and row["expected_artifact_needed_to_resolve"] for row in gaps)
    assert all(row["required_followup_action"] and row["followup_action_status"] == "REQUIRED_BEFORE_ANY_PROMOTION_READINESS" for row in followup)
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["promotion_ready"] == "FALSE"
    assert gate[0]["v20_123_pending_evidence_followup_allowed"] == "TRUE"
    every_pending_has_plan = d["every_pending_decision_has_resolution_plan"] == "TRUE"
    assert (d["pending_decision_resolution_plan_status"] == "PASS_V20_122_PENDING_DECISION_RESOLUTION_PLAN_READY_FOR_V20_123") == every_pending_has_plan
    for rows in [decision, plan, gaps, followup, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_pending_decision_resolution_plan()
    print("PASS_V20_122_PENDING_DECISION_RESOLUTION_PLAN_TESTS")
