#!/usr/bin/env python
"""Tests for V20.116 shadow stability regression audit."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_116_shadow_stability_regression_audit.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"

OUT_DECISION = CONSOLIDATION / "V20_116_SHADOW_STABILITY_REGRESSION_DECISION.csv"
OUT_CRITERIA = CONSOLIDATION / "V20_116_STABILITY_CRITERIA_AUDIT.csv"
OUT_HASH = CONSOLIDATION / "V20_116_REGRESSION_HASH_AUDIT.csv"
OUT_DELTA = CONSOLIDATION / "V20_116_SHADOW_DELTA_STABILITY_AUDIT.csv"
OUT_EXCEPTION = CONSOLIDATION / "V20_116_REGRESSION_EXCEPTION_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_116_SHADOW_STABILITY_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_116_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_116_SHADOW_STABILITY_REGRESSION_AUDIT_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_CRITERIA, OUT_HASH, OUT_DELTA, OUT_EXCEPTION, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    CONSOLIDATION / "V20_110_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_111_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_112_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_113_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_114_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_115_NEXT_STAGE_GATE.csv",
]
REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_115_gate_consumed", "v20_116_shadow_stability_regression_audit_allowed_by_v115", "selected_repair_scenario_id", "stability_criteria_passed", "upstream_mutation_detected", "violating_exception_count", "v20_117_multi_run_shadow_observation_allowed", "shadow_stability_regression_audit_status"},
    OUT_CRITERIA: {"criterion_name", "criterion_passed", "criterion_status"},
    OUT_HASH: {"artifact_path", "before_sha256", "after_sha256", "hash_unchanged"},
    OUT_DELTA: {"delta_name", "scenario_level_delta", "explanation_found", "delta_stable"},
    OUT_EXCEPTION: {"exception_type", "exception_present", "exception_violates_pass"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_115_gate_consumed", "selected_repair_scenario_id", "v20_117_multi_run_shadow_observation_allowed", "shadow_stability_regression_audit_status"},
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
    spec = importlib.util.spec_from_file_location("v20_116_shadow_stability_regression_audit_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        for name in ["IN_DECISION", "IN_BASELINE", "IN_DELTA", "IN_EXPLANATION", "IN_SAFETY", "IN_GATE"]:
            setattr(module, name, temp / f"missing_{name}.csv")
        module.REQUIRED_INPUTS = [module.IN_DECISION, module.IN_BASELINE, module.IN_DELTA, module.IN_EXPLANATION, module.IN_SAFETY, module.IN_GATE]
        module.OUT_DECISION = temp / "V20_116_SHADOW_STABILITY_REGRESSION_DECISION.csv"
        module.OUT_CRITERIA = temp / "V20_116_STABILITY_CRITERIA_AUDIT.csv"
        module.OUT_HASH = temp / "V20_116_REGRESSION_HASH_AUDIT.csv"
        module.OUT_DELTA_STABILITY = temp / "V20_116_SHADOW_DELTA_STABILITY_AUDIT.csv"
        module.OUT_EXCEPTION = temp / "V20_116_REGRESSION_EXCEPTION_AUDIT.csv"
        module.OUT_SAFETY = temp / "V20_116_SHADOW_STABILITY_SAFETY_BOUNDARY_AUDIT.csv"
        module.OUT_GATE = temp / "V20_116_NEXT_STAGE_GATE.csv"
        module.REPORT = temp / "V20_116_SHADOW_STABILITY_REGRESSION_AUDIT_REPORT.md"
        assert module.main() == 0
        blocked = read_csv(module.OUT_DECISION)[0]
        assert blocked["shadow_stability_regression_audit_status"] == "BLOCKED_V20_116_SHADOW_STABILITY_REGRESSION_AUDIT"
        assert blocked["v20_117_multi_run_shadow_observation_allowed"] == "FALSE"


def test_shadow_stability_regression_audit() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109/V20.110/V20.111/V20.112/V20.113/V20.114/V20.115 outputs were mutated"
    stdout = result.stdout
    assert "PASS_V20_116_SHADOW_STABILITY_REGRESSION_AUDIT_READY_FOR_V20_117" in stdout
    for expected in [
        "V20_115_GATE_CONSUMED=TRUE",
        "V20_116_SHADOW_STABILITY_REGRESSION_AUDIT_ALLOWED_BY_V115=TRUE",
        "V20_115_FINAL_STATUS=PASS_V20_115_SHADOW_BASELINE_COMPARISON_READY_FOR_V20_116",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "SELECTED_SCENARIO_MATCHES_V20_115=TRUE",
        "STABILITY_CRITERIA_PASSED=TRUE",
        "REGRESSION_HASH_AUDIT_CREATED=TRUE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "UNSTABLE_DELTA_COUNT=0",
        "VIOLATING_EXCEPTION_COUNT=0",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_117_MULTI_RUN_SHADOW_OBSERVATION_ALLOWED=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"
    decision = read_csv(OUT_DECISION)
    criteria = read_csv(OUT_CRITERIA)
    hashes = read_csv(OUT_HASH)
    deltas = read_csv(OUT_DELTA)
    exceptions = read_csv(OUT_EXCEPTION)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    d = decision[0]
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["shadow_stability_regression_audit_status"] == "PASS_V20_116_SHADOW_STABILITY_REGRESSION_AUDIT_READY_FOR_V20_117"
    assert d["v20_117_multi_run_shadow_observation_allowed"] == "TRUE"
    assert criteria and all(row["criterion_passed"] == "TRUE" for row in criteria)
    assert hashes and all(row["hash_unchanged"] == "TRUE" for row in hashes)
    assert deltas and all(row["delta_stable"] == "TRUE" and row["ticker_rows_created"] == "0" for row in deltas)
    assert exceptions and all(row["exception_violates_pass"] == "FALSE" for row in exceptions)
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["v20_117_multi_run_shadow_observation_allowed"] == "TRUE"
    strict = [
        d["v20_116_shadow_stability_regression_audit_allowed_by_v115"] == "TRUE",
        d["v20_115_status_passed"] == "TRUE",
        d["selected_scenario_matches_v20_115"] == "TRUE",
        d["stability_criteria_passed"] == "TRUE",
        d["unstable_delta_count"] == "0",
        d["no_upstream_outputs_mutated"] == "TRUE",
        d["no_violating_regression_exception"] == "TRUE",
        d["no_ticker_rows_fabricated"] == "TRUE",
        d["safety_boundary_audit_passed"] == "TRUE",
        d["prohibited_action_true_count"] == "0",
    ]
    assert (d["shadow_stability_regression_audit_status"] == "PASS_V20_116_SHADOW_STABILITY_REGRESSION_AUDIT_READY_FOR_V20_117") == all(strict)
    for rows in [decision, criteria, hashes, deltas, exceptions, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_shadow_stability_regression_audit()
    print("PASS_V20_116_SHADOW_STABILITY_REGRESSION_AUDIT_TESTS")
