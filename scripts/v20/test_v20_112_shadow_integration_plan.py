#!/usr/bin/env python
"""Tests for V20.112 shadow integration plan."""

from __future__ import annotations

import csv
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_112_shadow_integration_plan.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"

OUT_DECISION = CONSOLIDATION / "V20_112_SHADOW_INTEGRATION_PLAN_DECISION.csv"
OUT_SCOPE = CONSOLIDATION / "V20_112_SELECTED_SCENARIO_INTEGRATION_SCOPE.csv"
OUT_STEP_PLAN = CONSOLIDATION / "V20_112_SHADOW_INTEGRATION_STEP_PLAN.csv"
OUT_DEPENDENCY = CONSOLIDATION / "V20_112_SHADOW_INTEGRATION_DEPENDENCY_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_112_SHADOW_INTEGRATION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_112_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_112_SHADOW_INTEGRATION_PLAN_REPORT.md"

OUTPUTS = [OUT_DECISION, OUT_SCOPE, OUT_STEP_PLAN, OUT_DEPENDENCY, OUT_SAFETY, OUT_GATE, OUT_REPORT]

REQUIRED_COLUMNS = {
    OUT_DECISION: {
        "v20_111_gate_consumed",
        "v20_112_shadow_integration_plan_allowed_by_v111",
        "v20_111_final_status",
        "selected_repair_scenario_id",
        "integration_scope_created",
        "integration_step_plan_created",
        "dependency_audit_created",
        "v20_113_shadow_integration_dry_run_allowed",
        "shadow_integration_plan_status",
    },
    OUT_SCOPE: {"selected_repair_scenario_id", "scope_item", "scope_included", "scope_boundary"},
    OUT_STEP_PLAN: {"step_id", "step_order", "step_name", "execution_mode", "mutating_step"},
    OUT_DEPENDENCY: {"dependency_name", "dependency_required_before_dry_run", "dependency_status"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {
        "v20_111_gate_consumed",
        "v20_112_shadow_integration_plan_allowed_by_v111",
        "selected_repair_scenario_id",
        "v20_113_shadow_integration_dry_run_allowed",
        "shadow_integration_plan_status",
    },
}

PROHIBITED_FALSE_FIELDS = [
    "accepted_weight_created",
    "accepted_weights_created",
    "real_book_weight_created",
    "real_book_action_created",
    "official_weight_created",
    "official_weights_created",
    "official_ranking_created",
    "official_rankings_created",
    "official_recommendation_created",
    "official_recommendations_created",
    "trade_action_created",
    "trade_actions_created",
    "broker_action_created",
    "broker_actions_created",
    "authoritative_overwrite_created",
    "authoritative_overwrites_created",
    "authoritative_ranking_overwritten",
    "weight_mutated",
    "weight_mutations_created",
    "promotion_ready",
    "performance_claim_created",
    "performance_claims_created",
    "performance_effectiveness_claim_created",
    "official_promotion_allowed",
    "is_official_weight",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    bad = [row for row in rows if row.get(field) not in {"", "FALSE"}]
    assert not bad, f"{field} was not FALSE: {bad[:3]}"


def load_module():
    spec = importlib.util.spec_from_file_location("v20_112_shadow_integration_plan_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        module.IN_DECISION = temp / "missing_decision.csv"
        module.IN_LINEAGE = temp / "missing_lineage.csv"
        module.IN_CRITERIA = temp / "missing_criteria.csv"
        module.IN_SAFETY = temp / "missing_safety.csv"
        module.IN_GATE = temp / "missing_gate.csv"
        module.REQUIRED_INPUTS = [module.IN_DECISION, module.IN_LINEAGE, module.IN_CRITERIA, module.IN_SAFETY, module.IN_GATE]
        module.OUT_DECISION = temp / "V20_112_SHADOW_INTEGRATION_PLAN_DECISION.csv"
        module.OUT_SCOPE = temp / "V20_112_SELECTED_SCENARIO_INTEGRATION_SCOPE.csv"
        module.OUT_STEP_PLAN = temp / "V20_112_SHADOW_INTEGRATION_STEP_PLAN.csv"
        module.OUT_DEPENDENCY = temp / "V20_112_SHADOW_INTEGRATION_DEPENDENCY_AUDIT.csv"
        module.OUT_SAFETY = temp / "V20_112_SHADOW_INTEGRATION_SAFETY_BOUNDARY_AUDIT.csv"
        module.OUT_GATE = temp / "V20_112_NEXT_STAGE_GATE.csv"
        module.REPORT = temp / "V20_112_SHADOW_INTEGRATION_PLAN_REPORT.md"
        assert module.main() == 0
        blocked = read_csv(module.OUT_DECISION)[0]
        assert blocked["shadow_integration_plan_status"] == "BLOCKED_V20_112_SHADOW_INTEGRATION_PLAN"
        assert blocked["v20_113_shadow_integration_dry_run_allowed"] == "FALSE"


def test_shadow_integration_plan() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    assert "PASS_V20_112_SHADOW_INTEGRATION_PLAN_READY_FOR_V20_113" in stdout
    for expected in [
        "V20_111_GATE_CONSUMED=TRUE",
        "V20_112_SHADOW_INTEGRATION_PLAN_ALLOWED_BY_V111=TRUE",
        "V20_111_FINAL_STATUS=PASS_V20_111_SHADOW_ACCEPTANCE_REVIEW_READY_FOR_V20_112",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "SELECTED_SCENARIO_MATCHES_V20_111=TRUE",
        "LINEAGE_VALID_FROM_V20_111=TRUE",
        "INTEGRATION_SCOPE_CREATED=TRUE",
        "INTEGRATION_STEP_PLAN_CREATED=TRUE",
        "DEPENDENCY_AUDIT_CREATED=TRUE",
        "SHADOW_ONLY_CONFIRMED=TRUE",
        "PLANNING_ONLY_CONFIRMED=TRUE",
        "NON_MUTATING_CONFIRMED=TRUE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_113_SHADOW_INTEGRATION_DRY_RUN_ALLOWED=TRUE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "OFFICIAL_RANKING_CREATED=FALSE",
        "ACCEPTED_WEIGHT_CREATED=FALSE",
        "REAL_BOOK_WEIGHT_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_ACTION_CREATED=FALSE",
        "AUTHORITATIVE_OVERWRITE_CREATED=FALSE",
        "WEIGHT_MUTATED=FALSE",
        "PROMOTION_READY=FALSE",
        "PERFORMANCE_CLAIM_CREATED=FALSE",
    ]:
        assert expected in stdout, expected

    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"

    decision = read_csv(OUT_DECISION)
    scope = read_csv(OUT_SCOPE)
    steps = read_csv(OUT_STEP_PLAN)
    dependency = read_csv(OUT_DEPENDENCY)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)

    d = decision[0]
    assert d["v20_111_gate_consumed"] == "TRUE"
    assert d["v20_112_shadow_integration_plan_allowed_by_v111"] == "TRUE"
    assert d["v20_111_final_status"] == "PASS_V20_111_SHADOW_ACCEPTANCE_REVIEW_READY_FOR_V20_112"
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["selected_scenario_matches_v20_111"] == "TRUE"
    assert d["lineage_valid_from_v20_111"] == "TRUE"
    assert d["integration_scope_created"] == "TRUE"
    assert d["integration_step_plan_created"] == "TRUE"
    assert d["dependency_audit_created"] == "TRUE"
    assert d["shadow_only_confirmed"] == "TRUE"
    assert d["planning_only_confirmed"] == "TRUE"
    assert d["non_mutating_confirmed"] == "TRUE"
    assert d["safety_boundary_audit_passed"] == "TRUE"
    assert d["shadow_integration_plan_status"] == "PASS_V20_112_SHADOW_INTEGRATION_PLAN_READY_FOR_V20_113"
    assert d["v20_113_shadow_integration_dry_run_allowed"] == "TRUE"

    assert scope and all(row["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID for row in scope)
    assert steps and all(row["mutating_step"] == "FALSE" and row["official_artifact_step"] == "FALSE" for row in steps)
    assert dependency and all(row["dependency_required_before_dry_run"] == "TRUE" for row in dependency)
    assert all(row["observed_true_count"] == "0" for row in safety)
    assert all(row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["v20_113_shadow_integration_dry_run_allowed"] == "TRUE"

    strict_conditions = [
        d["v20_112_shadow_integration_plan_allowed_by_v111"] == "TRUE",
        d["v20_111_status_passed"] == "TRUE",
        d["selected_scenario_matches_v20_111"] == "TRUE",
        d["lineage_valid_from_v20_111"] == "TRUE",
        d["integration_scope_created"] == "TRUE",
        d["integration_step_plan_created"] == "TRUE",
        d["dependency_audit_created"] == "TRUE",
        d["shadow_only_confirmed"] == "TRUE",
        d["planning_only_confirmed"] == "TRUE",
        d["non_mutating_confirmed"] == "TRUE",
        d["safety_boundary_audit_passed"] == "TRUE",
        d["prohibited_action_true_count"] == "0",
    ]
    assert (d["shadow_integration_plan_status"] == "PASS_V20_112_SHADOW_INTEGRATION_PLAN_READY_FOR_V20_113") == all(strict_conditions)

    for rows in [decision, scope, steps, dependency, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_shadow_integration_plan()
    print("PASS_V20_112_SHADOW_INTEGRATION_PLAN_TESTS")
