#!/usr/bin/env python
"""Tests for V20.114 shadow output reconciliation."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_114_shadow_output_reconciliation.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"

OUT_DECISION = CONSOLIDATION / "V20_114_SHADOW_OUTPUT_RECONCILIATION_DECISION.csv"
OUT_STEP_RECON = CONSOLIDATION / "V20_114_STEP_PLAN_RECONCILIATION_AUDIT.csv"
OUT_OUTPUT_RECON = CONSOLIDATION / "V20_114_DRY_RUN_OUTPUT_RECONCILIATION_AUDIT.csv"
OUT_DEP_RECON = CONSOLIDATION / "V20_114_DEPENDENCY_RECONCILIATION_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_114_SHADOW_OUTPUT_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_114_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_114_SHADOW_OUTPUT_RECONCILIATION_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_STEP_RECON, OUT_OUTPUT_RECON, OUT_DEP_RECON, OUT_SAFETY, OUT_GATE, OUT_REPORT]

UPSTREAM = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    CONSOLIDATION / "V20_110_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_111_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_112_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_113_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_113_DRY_RUN_STEP_EXECUTION_AUDIT.csv",
    CONSOLIDATION / "V20_113_DRY_RUN_OUTPUT_MANIFEST.csv",
]

REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_113_gate_consumed", "v20_114_shadow_output_reconciliation_allowed_by_v113", "selected_repair_scenario_id", "missing_planned_step_count", "unauthorized_output_artifact_count", "dependency_reconciliation_all_passed", "no_upstream_outputs_mutated", "v20_115_shadow_baseline_comparison_allowed", "shadow_output_reconciliation_status"},
    OUT_STEP_RECON: {"source_step_id", "dry_run_step_executed", "step_reconciled", "missing_planned_step"},
    OUT_OUTPUT_RECON: {"dry_run_output_name", "expected_audit_only_output", "unauthorized_output_artifact"},
    OUT_DEP_RECON: {"dependency_name", "dependency_satisfied_for_dry_run", "dependency_reconciled"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_113_gate_consumed", "v20_114_shadow_output_reconciliation_allowed_by_v113", "selected_repair_scenario_id", "v20_115_shadow_baseline_comparison_allowed", "shadow_output_reconciliation_status"},
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
    spec = importlib.util.spec_from_file_location("v20_114_shadow_output_reconciliation_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        module.IN_DECISION = temp / "missing_decision.csv"
        module.IN_STEP_EXECUTION = temp / "missing_steps.csv"
        module.IN_DEPENDENCY_RESULT = temp / "missing_dependency.csv"
        module.IN_MANIFEST = temp / "missing_manifest.csv"
        module.IN_SAFETY = temp / "missing_safety.csv"
        module.IN_GATE = temp / "missing_gate.csv"
        module.IN_V112_STEPS = temp / "missing_v112_steps.csv"
        module.IN_V112_DEPENDENCY = temp / "missing_v112_dependency.csv"
        module.REQUIRED_INPUTS = [module.IN_DECISION, module.IN_STEP_EXECUTION, module.IN_DEPENDENCY_RESULT, module.IN_MANIFEST, module.IN_SAFETY, module.IN_GATE, module.IN_V112_STEPS, module.IN_V112_DEPENDENCY]
        module.OUT_DECISION = temp / "V20_114_SHADOW_OUTPUT_RECONCILIATION_DECISION.csv"
        module.OUT_STEP_RECON = temp / "V20_114_STEP_PLAN_RECONCILIATION_AUDIT.csv"
        module.OUT_OUTPUT_RECON = temp / "V20_114_DRY_RUN_OUTPUT_RECONCILIATION_AUDIT.csv"
        module.OUT_DEP_RECON = temp / "V20_114_DEPENDENCY_RECONCILIATION_AUDIT.csv"
        module.OUT_SAFETY = temp / "V20_114_SHADOW_OUTPUT_SAFETY_BOUNDARY_AUDIT.csv"
        module.OUT_GATE = temp / "V20_114_NEXT_STAGE_GATE.csv"
        module.REPORT = temp / "V20_114_SHADOW_OUTPUT_RECONCILIATION_REPORT.md"
        assert module.main() == 0
        blocked = read_csv(module.OUT_DECISION)[0]
        assert blocked["shadow_output_reconciliation_status"] == "BLOCKED_V20_114_SHADOW_OUTPUT_RECONCILIATION"
        assert blocked["v20_115_shadow_baseline_comparison_allowed"] == "FALSE"


def test_shadow_output_reconciliation() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109/V20.110/V20.111/V20.112/V20.113 outputs were mutated"
    stdout = result.stdout
    assert "PASS_V20_114_SHADOW_OUTPUT_RECONCILIATION_READY_FOR_V20_115" in stdout
    for expected in [
        "V20_113_GATE_CONSUMED=TRUE",
        "V20_114_SHADOW_OUTPUT_RECONCILIATION_ALLOWED_BY_V113=TRUE",
        "V20_113_FINAL_STATUS=PASS_V20_113_SHADOW_INTEGRATION_DRY_RUN_READY_FOR_V20_114",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "SELECTED_SCENARIO_MATCHES_V20_113=TRUE",
        "MISSING_PLANNED_STEP_COUNT=0",
        "NO_PLANNED_DRY_RUN_STEP_MISSING=TRUE",
        "UNAUTHORIZED_OUTPUT_ARTIFACT_COUNT=0",
        "NO_UNAUTHORIZED_OUTPUT_ARTIFACT_ACCEPTED=TRUE",
        "DEPENDENCY_RECONCILIATION_ALL_PASSED=TRUE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "NO_TICKER_ROWS_FABRICATED=TRUE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "NO_UPSTREAM_OUTPUTS_MUTATED=TRUE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_115_SHADOW_BASELINE_COMPARISON_ALLOWED=TRUE",
    ]:
        assert expected in stdout, expected

    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"

    decision = read_csv(OUT_DECISION)
    step_recon = read_csv(OUT_STEP_RECON)
    output_recon = read_csv(OUT_OUTPUT_RECON)
    dep_recon = read_csv(OUT_DEP_RECON)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    d = decision[0]
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["shadow_output_reconciliation_status"] == "PASS_V20_114_SHADOW_OUTPUT_RECONCILIATION_READY_FOR_V20_115"
    assert d["v20_115_shadow_baseline_comparison_allowed"] == "TRUE"
    assert step_recon and all(row["missing_planned_step"] == "FALSE" and row["step_reconciled"] == "TRUE" for row in step_recon)
    assert output_recon and all(row["unauthorized_output_artifact"] == "FALSE" for row in output_recon)
    assert dep_recon and all(row["dependency_reconciled"] == "TRUE" for row in dep_recon)
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["v20_115_shadow_baseline_comparison_allowed"] == "TRUE"
    strict = [
        d["v20_114_shadow_output_reconciliation_allowed_by_v113"] == "TRUE",
        d["v20_113_status_passed"] == "TRUE",
        d["selected_scenario_matches_v20_113"] == "TRUE",
        d["no_planned_dry_run_step_missing"] == "TRUE",
        d["no_unauthorized_output_artifact_accepted"] == "TRUE",
        d["dependency_reconciliation_all_passed"] == "TRUE",
        d["no_ticker_rows_fabricated"] == "TRUE",
        d["no_upstream_outputs_mutated"] == "TRUE",
        d["safety_boundary_audit_passed"] == "TRUE",
        d["prohibited_action_true_count"] == "0",
    ]
    assert (d["shadow_output_reconciliation_status"] == "PASS_V20_114_SHADOW_OUTPUT_RECONCILIATION_READY_FOR_V20_115") == all(strict)
    for rows in [decision, step_recon, output_recon, dep_recon, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_shadow_output_reconciliation()
    print("PASS_V20_114_SHADOW_OUTPUT_RECONCILIATION_TESTS")
