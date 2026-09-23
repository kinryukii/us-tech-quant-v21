#!/usr/bin/env python
"""Tests for V20.115 shadow baseline comparison."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_115_shadow_baseline_comparison.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"

OUT_DECISION = CONSOLIDATION / "V20_115_SHADOW_BASELINE_COMPARISON_DECISION.csv"
OUT_BASELINE = CONSOLIDATION / "V20_115_BASELINE_REFERENCE_AUDIT.csv"
OUT_DELTA = CONSOLIDATION / "V20_115_SHADOW_VS_BASELINE_DELTA_AUDIT.csv"
OUT_EXPLANATION = CONSOLIDATION / "V20_115_CHANGE_EXPLANATION_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_115_SHADOW_BASELINE_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_115_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_115_SHADOW_BASELINE_COMPARISON_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_BASELINE, OUT_DELTA, OUT_EXPLANATION, OUT_SAFETY, OUT_GATE, OUT_REPORT]

UPSTREAM = [
    CONSOLIDATION / "V20_109_R11_BASELINE_QUALITY_ROBUSTNESS_AUDIT.csv",
    CONSOLIDATION / "V20_110_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_111_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_112_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_113_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_114_NEXT_STAGE_GATE.csv",
]

REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_114_gate_consumed", "v20_115_shadow_baseline_comparison_allowed_by_v114", "selected_repair_scenario_id", "baseline_reference_identified", "delta_audit_created", "change_explanation_audit_created", "no_ticker_rows_fabricated", "no_upstream_outputs_mutated", "v20_116_shadow_stability_regression_audit_allowed", "shadow_baseline_comparison_status"},
    OUT_BASELINE: {"selected_repair_scenario_id", "baseline_reference_source", "baseline_reference_valid"},
    OUT_DELTA: {"delta_name", "baseline_reference_value", "shadow_repair_value", "delta_audit_status"},
    OUT_EXPLANATION: {"change_topic", "explainable", "audit_only_explanation"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_114_gate_consumed", "v20_115_shadow_baseline_comparison_allowed_by_v114", "selected_repair_scenario_id", "v20_116_shadow_stability_regression_audit_allowed", "shadow_baseline_comparison_status"},
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
    spec = importlib.util.spec_from_file_location("v20_115_shadow_baseline_comparison_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        for name in ["IN_DECISION", "IN_STEP_RECON", "IN_OUTPUT_RECON", "IN_DEP_RECON", "IN_SAFETY", "IN_GATE", "IN_V113_MANIFEST", "IN_V113_STEPS", "IN_R11_BASELINE", "IN_R11_PERSISTENCE", "IN_R11_SELECTION"]:
            setattr(module, name, temp / f"missing_{name}.csv")
        module.REQUIRED_INPUTS = [module.IN_DECISION, module.IN_STEP_RECON, module.IN_OUTPUT_RECON, module.IN_DEP_RECON, module.IN_SAFETY, module.IN_GATE, module.IN_V113_MANIFEST, module.IN_V113_STEPS, module.IN_R11_BASELINE, module.IN_R11_PERSISTENCE, module.IN_R11_SELECTION]
        module.OUT_DECISION = temp / "V20_115_SHADOW_BASELINE_COMPARISON_DECISION.csv"
        module.OUT_BASELINE = temp / "V20_115_BASELINE_REFERENCE_AUDIT.csv"
        module.OUT_DELTA = temp / "V20_115_SHADOW_VS_BASELINE_DELTA_AUDIT.csv"
        module.OUT_EXPLANATION = temp / "V20_115_CHANGE_EXPLANATION_AUDIT.csv"
        module.OUT_SAFETY = temp / "V20_115_SHADOW_BASELINE_SAFETY_BOUNDARY_AUDIT.csv"
        module.OUT_GATE = temp / "V20_115_NEXT_STAGE_GATE.csv"
        module.REPORT = temp / "V20_115_SHADOW_BASELINE_COMPARISON_REPORT.md"
        assert module.main() == 0
        blocked = read_csv(module.OUT_DECISION)[0]
        assert blocked["shadow_baseline_comparison_status"] == "BLOCKED_V20_115_SHADOW_BASELINE_COMPARISON"
        assert blocked["v20_116_shadow_stability_regression_audit_allowed"] == "FALSE"


def test_shadow_baseline_comparison() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109/V20.110/V20.111/V20.112/V20.113/V20.114 outputs were mutated"
    stdout = result.stdout
    assert "PASS_V20_115_SHADOW_BASELINE_COMPARISON_READY_FOR_V20_116" in stdout
    for expected in [
        "V20_114_GATE_CONSUMED=TRUE",
        "V20_115_SHADOW_BASELINE_COMPARISON_ALLOWED_BY_V114=TRUE",
        "V20_114_FINAL_STATUS=PASS_V20_114_SHADOW_OUTPUT_RECONCILIATION_READY_FOR_V20_115",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "SELECTED_SCENARIO_MATCHES_V20_114=TRUE",
        "BASELINE_REFERENCE_IDENTIFIED=TRUE",
        "DELTA_AUDIT_CREATED=TRUE",
        "CHANGE_EXPLANATION_AUDIT_CREATED=TRUE",
        "DELTAS_EXPLAINABLE=TRUE",
        "UNAUTHORIZED_ARTIFACT_COUNT=0",
        "NO_UNAUTHORIZED_ARTIFACT_ACCEPTED=TRUE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "NO_TICKER_ROWS_FABRICATED=TRUE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "NO_UPSTREAM_OUTPUTS_MUTATED=TRUE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_116_SHADOW_STABILITY_REGRESSION_AUDIT_ALLOWED=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"
    decision = read_csv(OUT_DECISION)
    baseline = read_csv(OUT_BASELINE)
    delta = read_csv(OUT_DELTA)
    explanation = read_csv(OUT_EXPLANATION)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    d = decision[0]
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["shadow_baseline_comparison_status"] == "PASS_V20_115_SHADOW_BASELINE_COMPARISON_READY_FOR_V20_116"
    assert d["v20_116_shadow_stability_regression_audit_allowed"] == "TRUE"
    assert baseline and baseline[0]["baseline_reference_valid"] == "TRUE"
    assert delta and all(row["performance_claim_created"] == "FALSE" for row in delta)
    assert explanation and all(row["explainable"] == "TRUE" and row["audit_only_explanation"] == "TRUE" for row in explanation)
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["v20_116_shadow_stability_regression_audit_allowed"] == "TRUE"
    strict = [
        d["v20_115_shadow_baseline_comparison_allowed_by_v114"] == "TRUE",
        d["v20_114_status_passed"] == "TRUE",
        d["selected_scenario_matches_v20_114"] == "TRUE",
        d["baseline_reference_identified"] == "TRUE",
        d["delta_audit_created"] == "TRUE",
        d["change_explanation_audit_created"] == "TRUE",
        d["deltas_explainable"] == "TRUE",
        d["no_unauthorized_artifact_accepted"] == "TRUE",
        d["no_ticker_rows_fabricated"] == "TRUE",
        d["no_upstream_outputs_mutated"] == "TRUE",
        d["safety_boundary_audit_passed"] == "TRUE",
        d["prohibited_action_true_count"] == "0",
    ]
    assert (d["shadow_baseline_comparison_status"] == "PASS_V20_115_SHADOW_BASELINE_COMPARISON_READY_FOR_V20_116") == all(strict)
    for rows in [decision, baseline, delta, explanation, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_shadow_baseline_comparison()
    print("PASS_V20_115_SHADOW_BASELINE_COMPARISON_TESTS")
