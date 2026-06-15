#!/usr/bin/env python
"""Tests for V20.113 shadow integration dry run."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_113_shadow_integration_dry_run.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"

OUT_DECISION = CONSOLIDATION / "V20_113_SHADOW_INTEGRATION_DRY_RUN_DECISION.csv"
OUT_STEP_AUDIT = CONSOLIDATION / "V20_113_DRY_RUN_STEP_EXECUTION_AUDIT.csv"
OUT_DEPENDENCY = CONSOLIDATION / "V20_113_DRY_RUN_DEPENDENCY_RESULT_AUDIT.csv"
OUT_MANIFEST = CONSOLIDATION / "V20_113_DRY_RUN_OUTPUT_MANIFEST.csv"
OUT_SAFETY = CONSOLIDATION / "V20_113_SHADOW_INTEGRATION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_113_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_113_SHADOW_INTEGRATION_DRY_RUN_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_STEP_AUDIT, OUT_DEPENDENCY, OUT_MANIFEST, OUT_SAFETY, OUT_GATE, OUT_REPORT]

UPSTREAM = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    CONSOLIDATION / "V20_110_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_111_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_112_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_112_SHADOW_INTEGRATION_STEP_PLAN.csv",
]

REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_112_gate_consumed", "v20_113_shadow_integration_dry_run_allowed_by_v112", "selected_repair_scenario_id", "all_planned_steps_dry_run_executed", "dependency_result_all_satisfied_for_dry_run", "dry_run_output_manifest_created", "no_ticker_rows_fabricated", "v20_114_shadow_output_reconciliation_allowed", "shadow_integration_dry_run_status"},
    OUT_STEP_AUDIT: {"source_step_id", "dry_run_step_executed", "upstream_artifact_mutated", "ticker_rows_created", "dry_run_step_status"},
    OUT_DEPENDENCY: {"dependency_name", "dependency_satisfied_for_dry_run", "dependency_result_status"},
    OUT_MANIFEST: {"dry_run_output_name", "audit_only_output", "contains_ticker_rows", "official_artifact", "real_book_artifact", "mutates_upstream"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_112_gate_consumed", "v20_113_shadow_integration_dry_run_allowed_by_v112", "selected_repair_scenario_id", "v20_114_shadow_output_reconciliation_allowed", "shadow_integration_dry_run_status"},
}

PROHIBITED_FALSE_FIELDS = [
    "accepted_weight_created", "accepted_weights_created", "real_book_weight_created", "real_book_action_created",
    "official_weight_created", "official_weights_created", "official_ranking_created", "official_rankings_created",
    "official_recommendation_created", "official_recommendations_created", "trade_action_created", "trade_actions_created",
    "broker_action_created", "broker_actions_created", "authoritative_overwrite_created", "authoritative_overwrites_created",
    "authoritative_ranking_overwritten", "weight_mutated", "weight_mutations_created", "promotion_ready",
    "performance_claim_created", "performance_claims_created", "performance_effectiveness_claim_created",
    "official_promotion_allowed", "is_official_weight",
]


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
    spec = importlib.util.spec_from_file_location("v20_113_shadow_integration_dry_run_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        module.IN_DECISION = temp / "missing_decision.csv"
        module.IN_SCOPE = temp / "missing_scope.csv"
        module.IN_STEP_PLAN = temp / "missing_steps.csv"
        module.IN_DEPENDENCY = temp / "missing_dependency.csv"
        module.IN_SAFETY = temp / "missing_safety.csv"
        module.IN_GATE = temp / "missing_gate.csv"
        module.REQUIRED_INPUTS = [module.IN_DECISION, module.IN_SCOPE, module.IN_STEP_PLAN, module.IN_DEPENDENCY, module.IN_SAFETY, module.IN_GATE]
        module.OUT_DECISION = temp / "V20_113_SHADOW_INTEGRATION_DRY_RUN_DECISION.csv"
        module.OUT_STEP_AUDIT = temp / "V20_113_DRY_RUN_STEP_EXECUTION_AUDIT.csv"
        module.OUT_DEPENDENCY_AUDIT = temp / "V20_113_DRY_RUN_DEPENDENCY_RESULT_AUDIT.csv"
        module.OUT_MANIFEST = temp / "V20_113_DRY_RUN_OUTPUT_MANIFEST.csv"
        module.OUT_SAFETY = temp / "V20_113_SHADOW_INTEGRATION_SAFETY_BOUNDARY_AUDIT.csv"
        module.OUT_GATE = temp / "V20_113_NEXT_STAGE_GATE.csv"
        module.REPORT = temp / "V20_113_SHADOW_INTEGRATION_DRY_RUN_REPORT.md"
        assert module.main() == 0
        blocked = read_csv(module.OUT_DECISION)[0]
        assert blocked["shadow_integration_dry_run_status"] == "BLOCKED_V20_113_SHADOW_INTEGRATION_DRY_RUN"
        assert blocked["v20_114_shadow_output_reconciliation_allowed"] == "FALSE"


def test_shadow_integration_dry_run() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109/V20.110/V20.111/V20.112 outputs were mutated"
    stdout = result.stdout
    assert "PASS_V20_113_SHADOW_INTEGRATION_DRY_RUN_READY_FOR_V20_114" in stdout
    for expected in [
        "V20_112_GATE_CONSUMED=TRUE",
        "V20_113_SHADOW_INTEGRATION_DRY_RUN_ALLOWED_BY_V112=TRUE",
        "V20_112_FINAL_STATUS=PASS_V20_112_SHADOW_INTEGRATION_PLAN_READY_FOR_V20_113",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "SELECTED_SCENARIO_MATCHES_V20_112=TRUE",
        "ALL_PLANNED_STEPS_DRY_RUN_EXECUTED=TRUE",
        "DEPENDENCY_RESULT_AUDIT_CREATED=TRUE",
        "DEPENDENCY_RESULT_ALL_SATISFIED_FOR_DRY_RUN=TRUE",
        "DRY_RUN_OUTPUT_MANIFEST_CREATED=TRUE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "NO_TICKER_ROWS_FABRICATED=TRUE",
        "NON_MUTATING_CONFIRMED=TRUE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_114_SHADOW_OUTPUT_RECONCILIATION_ALLOWED=TRUE",
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
    steps = read_csv(OUT_STEP_AUDIT)
    dependencies = read_csv(OUT_DEPENDENCY)
    manifest = read_csv(OUT_MANIFEST)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    d = decision[0]
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["shadow_integration_dry_run_status"] == "PASS_V20_113_SHADOW_INTEGRATION_DRY_RUN_READY_FOR_V20_114"
    assert d["v20_114_shadow_output_reconciliation_allowed"] == "TRUE"
    assert steps and all(row["dry_run_step_executed"] == "TRUE" and row["upstream_artifact_mutated"] == "FALSE" and row["ticker_rows_created"] == "0" for row in steps)
    assert dependencies and all(row["dependency_satisfied_for_dry_run"] == "TRUE" for row in dependencies)
    assert manifest and all(row["audit_only_output"] == "TRUE" and row["contains_ticker_rows"] == "FALSE" and row["official_artifact"] == "FALSE" and row["real_book_artifact"] == "FALSE" and row["mutates_upstream"] == "FALSE" for row in manifest)
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["v20_114_shadow_output_reconciliation_allowed"] == "TRUE"
    strict = [
        d["v20_113_shadow_integration_dry_run_allowed_by_v112"] == "TRUE",
        d["v20_112_status_passed"] == "TRUE",
        d["selected_scenario_matches_v20_112"] == "TRUE",
        d["all_planned_steps_dry_run_executed"] == "TRUE",
        d["dependency_result_all_satisfied_for_dry_run"] == "TRUE",
        d["dry_run_output_manifest_created"] == "TRUE",
        d["no_ticker_rows_fabricated"] == "TRUE",
        d["non_mutating_confirmed"] == "TRUE",
        d["safety_boundary_audit_passed"] == "TRUE",
        d["prohibited_action_true_count"] == "0",
    ]
    assert (d["shadow_integration_dry_run_status"] == "PASS_V20_113_SHADOW_INTEGRATION_DRY_RUN_READY_FOR_V20_114") == all(strict)
    for rows in [decision, steps, dependencies, manifest, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_shadow_integration_dry_run()
    print("PASS_V20_113_SHADOW_INTEGRATION_DRY_RUN_TESTS")
