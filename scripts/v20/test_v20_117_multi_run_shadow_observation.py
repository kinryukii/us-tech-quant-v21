#!/usr/bin/env python
"""Tests for V20.117 multi-run shadow observation."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_117_multi_run_shadow_observation.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"

OUT_DECISION = CONSOLIDATION / "V20_117_MULTI_RUN_SHADOW_OBSERVATION_DECISION.csv"
OUT_REGISTRY = CONSOLIDATION / "V20_117_SHADOW_OBSERVATION_RUN_REGISTRY.csv"
OUT_SUMMARY = CONSOLIDATION / "V20_117_MULTI_RUN_OBSERVATION_SUMMARY.csv"
OUT_CONSISTENCY = CONSOLIDATION / "V20_117_OBSERVATION_CONSISTENCY_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_117_OBSERVATION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_117_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_117_MULTI_RUN_SHADOW_OBSERVATION_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_REGISTRY, OUT_SUMMARY, OUT_CONSISTENCY, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = [CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116"]]
UPSTREAM.append(CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv")

REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_116_gate_consumed", "v20_117_multi_run_shadow_observation_allowed_by_v116", "selected_repair_scenario_id", "observation_registry_created", "observation_consistency_all_passed", "v20_118_promotion_blocker_recheck_allowed", "multi_run_shadow_observation_status"},
    OUT_REGISTRY: {"observation_run_id", "selected_repair_scenario_id", "source_stage", "observation_type", "scenario_level_only", "ticker_rows_created"},
    OUT_SUMMARY: {"observation_run_count", "scenario_level_observation_count", "ticker_rows_created", "summary_status"},
    OUT_CONSISTENCY: {"consistency_rule", "observed_value", "consistency_passed"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_116_gate_consumed", "selected_repair_scenario_id", "v20_118_promotion_blocker_recheck_allowed", "multi_run_shadow_observation_status"},
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
    spec = importlib.util.spec_from_file_location("v20_117_multi_run_shadow_observation_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        for name in ["IN_DECISION", "IN_CRITERIA", "IN_HASH", "IN_DELTA", "IN_EXCEPTION", "IN_SAFETY", "IN_GATE"]:
            setattr(module, name, temp / f"missing_{name}.csv")
        module.REQUIRED_INPUTS = [module.IN_DECISION, module.IN_CRITERIA, module.IN_HASH, module.IN_DELTA, module.IN_EXCEPTION, module.IN_SAFETY, module.IN_GATE]
        module.OUT_DECISION = temp / "V20_117_MULTI_RUN_SHADOW_OBSERVATION_DECISION.csv"
        module.OUT_REGISTRY = temp / "V20_117_SHADOW_OBSERVATION_RUN_REGISTRY.csv"
        module.OUT_SUMMARY = temp / "V20_117_MULTI_RUN_OBSERVATION_SUMMARY.csv"
        module.OUT_CONSISTENCY = temp / "V20_117_OBSERVATION_CONSISTENCY_AUDIT.csv"
        module.OUT_SAFETY = temp / "V20_117_OBSERVATION_SAFETY_BOUNDARY_AUDIT.csv"
        module.OUT_GATE = temp / "V20_117_NEXT_STAGE_GATE.csv"
        module.REPORT = temp / "V20_117_MULTI_RUN_SHADOW_OBSERVATION_REPORT.md"
        assert module.main() == 0
        blocked = read_csv(module.OUT_DECISION)[0]
        assert blocked["multi_run_shadow_observation_status"] == "BLOCKED_V20_117_MULTI_RUN_SHADOW_OBSERVATION"
        assert blocked["v20_118_promotion_blocker_recheck_allowed"] == "FALSE"


def test_multi_run_shadow_observation() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.116 outputs were mutated"
    stdout = result.stdout
    assert "PASS_V20_117_MULTI_RUN_SHADOW_OBSERVATION_READY_FOR_V20_118" in stdout
    for expected in [
        "V20_116_GATE_CONSUMED=TRUE",
        "V20_117_MULTI_RUN_SHADOW_OBSERVATION_ALLOWED_BY_V116=TRUE",
        "V20_116_FINAL_STATUS=PASS_V20_116_SHADOW_STABILITY_REGRESSION_AUDIT_READY_FOR_V20_117",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "SELECTED_SCENARIO_MATCHES_V20_116=TRUE",
        "OBSERVATION_REGISTRY_CREATED=TRUE",
        "OBSERVATION_SUMMARY_CREATED=TRUE",
        "OBSERVATION_CONSISTENCY_ALL_PASSED=TRUE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_118_PROMOTION_BLOCKER_RECHECK_ALLOWED=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"
    decision = read_csv(OUT_DECISION)
    registry = read_csv(OUT_REGISTRY)
    summary = read_csv(OUT_SUMMARY)
    consistency = read_csv(OUT_CONSISTENCY)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    d = decision[0]
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["multi_run_shadow_observation_status"] == "PASS_V20_117_MULTI_RUN_SHADOW_OBSERVATION_READY_FOR_V20_118"
    assert d["v20_118_promotion_blocker_recheck_allowed"] == "TRUE"
    assert registry and all(row["scenario_level_only"] == "TRUE" and row["ticker_rows_created"] == "0" for row in registry)
    assert summary and summary[0]["ticker_rows_created"] == "0"
    assert consistency and all(row["consistency_passed"] == "TRUE" for row in consistency)
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["v20_118_promotion_blocker_recheck_allowed"] == "TRUE"
    strict = [
        d["v20_117_multi_run_shadow_observation_allowed_by_v116"] == "TRUE",
        d["v20_116_status_passed"] == "TRUE",
        d["selected_scenario_matches_v20_116"] == "TRUE",
        d["observation_registry_created"] == "TRUE",
        d["observation_consistency_all_passed"] == "TRUE",
        d["no_ticker_rows_fabricated"] == "TRUE",
        d["no_upstream_outputs_mutated"] == "TRUE",
        d["safety_boundary_audit_passed"] == "TRUE",
        d["prohibited_action_true_count"] == "0",
    ]
    assert (d["multi_run_shadow_observation_status"] == "PASS_V20_117_MULTI_RUN_SHADOW_OBSERVATION_READY_FOR_V20_118") == all(strict)
    for rows in [decision, registry, summary, consistency, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_multi_run_shadow_observation()
    print("PASS_V20_117_MULTI_RUN_SHADOW_OBSERVATION_TESTS")
