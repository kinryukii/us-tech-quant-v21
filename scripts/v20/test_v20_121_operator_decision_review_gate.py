#!/usr/bin/env python
"""Tests for V20.121 operator decision review gate."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_121_operator_decision_review_gate.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"

OUT_DECISION = CONSOLIDATION / "V20_121_OPERATOR_DECISION_REVIEW_GATE_DECISION.csv"
OUT_COMPLETENESS = CONSOLIDATION / "V20_121_OPERATOR_DECISION_COMPLETENESS_AUDIT.csv"
OUT_PENDING = CONSOLIDATION / "V20_121_PENDING_DECISION_GATE_AUDIT.csv"
OUT_ACCEPTANCE = CONSOLIDATION / "V20_121_OPERATOR_ACCEPTANCE_VALIDATION_AUDIT.csv"
OUT_PROMOTION = CONSOLIDATION / "V20_121_PROMOTION_READINESS_GATE_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_121_OPERATOR_DECISION_REVIEW_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_121_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_121_OPERATOR_DECISION_REVIEW_GATE_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_COMPLETENESS, OUT_PENDING, OUT_ACCEPTANCE, OUT_PROMOTION, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = [CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110","111","112","113","114","115","116","117","118","119","120"]]
UPSTREAM.append(CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv")

REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_120_gate_consumed","selected_repair_scenario_id","pending_decision_count","promotion_ready","v20_122_pending_decision_resolution_plan_allowed","operator_decision_review_gate_status"},
    OUT_COMPLETENESS: {"source_required_decision_id","blocker_category","decision_represented"},
    OUT_PENDING: {"blocker_category","decision_status","operator_acceptance","promotion_ready","pending_gate_passed"},
    OUT_ACCEPTANCE: {"blocker_category","operator_acceptance","valid_acceptance_evidence","acceptance_valid"},
    OUT_PROMOTION: {"pending_decision_count","all_operator_decisions_accepted_with_valid_evidence","promotion_ready","promotion_gate_status"},
    OUT_SAFETY: {"prohibited_field","observed_true_count","safety_boundary_passed"},
    OUT_GATE: {"v20_120_gate_consumed","selected_repair_scenario_id","promotion_ready","v20_122_pending_decision_resolution_plan_allowed","operator_decision_review_gate_status"},
}
PROHIBITED_FALSE_FIELDS = ["accepted_weight_created","accepted_weights_created","real_book_weight_created","real_book_action_created","official_weight_created","official_weights_created","official_ranking_created","official_rankings_created","official_recommendation_created","official_recommendations_created","trade_action_created","trade_actions_created","broker_action_created","broker_actions_created","authoritative_overwrite_created","authoritative_overwrites_created","authoritative_ranking_overwritten","weight_mutated","weight_mutations_created","performance_claim_created","performance_claims_created","performance_effectiveness_claim_created","official_promotion_allowed","is_official_weight","promotion_ready"]


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
    spec = importlib.util.spec_from_file_location("v20_121_operator_decision_review_gate_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        for name in ["IN_DECISION","IN_RECORD","IN_EVIDENCE","IN_UNRESOLVED","IN_SAFETY","IN_GATE"]:
            setattr(module, name, temp / f"missing_{name}.csv")
        module.REQUIRED_INPUTS = [module.IN_DECISION,module.IN_RECORD,module.IN_EVIDENCE,module.IN_UNRESOLVED,module.IN_SAFETY,module.IN_GATE]
        module.OUT_DECISION = temp / "V20_121_OPERATOR_DECISION_REVIEW_GATE_DECISION.csv"
        module.OUT_COMPLETENESS = temp / "V20_121_OPERATOR_DECISION_COMPLETENESS_AUDIT.csv"
        module.OUT_PENDING = temp / "V20_121_PENDING_DECISION_GATE_AUDIT.csv"
        module.OUT_ACCEPTANCE = temp / "V20_121_OPERATOR_ACCEPTANCE_VALIDATION_AUDIT.csv"
        module.OUT_PROMOTION = temp / "V20_121_PROMOTION_READINESS_GATE_AUDIT.csv"
        module.OUT_SAFETY = temp / "V20_121_OPERATOR_DECISION_REVIEW_SAFETY_BOUNDARY_AUDIT.csv"
        module.OUT_GATE = temp / "V20_121_NEXT_STAGE_GATE.csv"
        module.REPORT = temp / "V20_121_OPERATOR_DECISION_REVIEW_GATE_REPORT.md"
        assert module.main() == 0
        blocked = read_csv(module.OUT_DECISION)[0]
        assert blocked["operator_decision_review_gate_status"] == "BLOCKED_V20_121_OPERATOR_DECISION_REVIEW_GATE"
        assert blocked["promotion_ready"] == "FALSE"


def test_operator_decision_review_gate() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.120 outputs were mutated"
    stdout = result.stdout
    assert "PARTIAL_PASS_V20_121_OPERATOR_DECISIONS_STILL_PENDING_READY_FOR_V20_122" in stdout
    for expected in [
        "V20_120_GATE_CONSUMED=TRUE",
        "V20_121_OPERATOR_DECISION_REVIEW_GATE_ALLOWED_BY_V120=TRUE",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "ALL_REQUIRED_DECISIONS_REPRESENTED=TRUE",
        "PENDING_DECISION_COUNT=2",
        "ACCEPTED_DECISION_COUNT=0",
        "ALL_OPERATOR_DECISIONS_ACCEPTED_WITH_VALID_EVIDENCE=FALSE",
        "PROMOTION_READY=FALSE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_122_PENDING_DECISION_RESOLUTION_PLAN_ALLOWED=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"
    decision = read_csv(OUT_DECISION)
    pending = read_csv(OUT_PENDING)
    acceptance = read_csv(OUT_ACCEPTANCE)
    promotion = read_csv(OUT_PROMOTION)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    d = decision[0]
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["promotion_ready"] == "FALSE"
    assert d["operator_decision_review_gate_status"] == "PARTIAL_PASS_V20_121_OPERATOR_DECISIONS_STILL_PENDING_READY_FOR_V20_122"
    assert all(row["decision_status"] == "PENDING_OPERATOR_DECISION" and row["operator_acceptance"] == "FALSE" and row["promotion_ready"] == "FALSE" for row in pending)
    assert all(row["acceptance_valid"] == "FALSE" for row in acceptance)
    assert promotion[0]["promotion_ready"] == "FALSE"
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["promotion_ready"] == "FALSE"
    assert gate[0]["v20_122_pending_decision_resolution_plan_allowed"] == "TRUE"
    all_accepted = d["all_operator_decisions_accepted_with_valid_evidence"] == "TRUE"
    assert (d["operator_decision_review_gate_status"] == "PASS_V20_121_OPERATOR_DECISION_REVIEW_GATE_READY_FOR_V20_122") == all_accepted
    for rows in [decision, pending, acceptance, promotion, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_operator_decision_review_gate()
    print("PASS_V20_121_OPERATOR_DECISION_REVIEW_GATE_TESTS")
