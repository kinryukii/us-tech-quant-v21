#!/usr/bin/env python
"""Tests for V20.170-R1B DATA_TRUST upstream PIT producer patch plan."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_170_r1b_data_trust_upstream_pit_producer_patch_plan.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    FACTORS / "V20_170_R1B_UPSTREAM_PIT_PRODUCER_PATCH_PLAN.csv",
    FACTORS / "V20_170_R1B_PIT_MISSING_FIELD_TO_PRODUCER_MAPPING.csv",
    FACTORS / "V20_170_R1B_PIT_REQUIRED_FIELD_DERIVATION_RULES.csv",
    FACTORS / "V20_170_R1B_PIT_PRODUCER_SCRIPT_PATCH_TARGETS.csv",
    FACTORS / "V20_170_R1B_PIT_OUTPUT_SCHEMA_EXTENSION_PLAN.csv",
    FACTORS / "V20_170_R1B_PIT_PATCH_RISK_AND_SAFETY_AUDIT.csv",
    FACTORS / "V20_170_R1B_PIT_PRODUCER_PATCH_NEXT_GATE.csv",
    READ_CENTER / "V20_170_R1B_DATA_TRUST_UPSTREAM_PIT_PRODUCER_PATCH_PLAN_REPORT.md",
]

REQUIRED_R1A_STATUS = "WARN_V20_170_R1A_UPSTREAM_PIT_PRODUCER_PATCH_PLAN_REQUIRED"
PARTIAL_STATUS = "PARTIAL_PASS_V20_170_R1B_PATCH_PLAN_WITH_UNRESOLVED_SOURCE_CONTRACTS_READY_FOR_V20_170_R1C"
BLOCKED_STATUS = "BLOCKED_V20_170_R1B_UPSTREAM_PIT_PRODUCER_PATCH_PLAN"

PLAN_COLUMNS = {
    "missing_required_field", "affected_ticker_count", "affected_lineage_row_count",
    "current_source_artifact", "current_source_field_available", "patch_classification",
    "proposed_upstream_producer_script", "proposed_output_artifact", "proposed_output_field",
    "derivation_rule", "derivation_safe", "requires_code_patch", "requires_schema_extension",
    "requires_backfill", "repair_priority", "blocking_for_direct_pit_pass",
    "recommended_patch_action",
}
TARGET_COLUMNS = {
    "producer_script", "producer_exists", "current_output_artifact", "output_artifact_exists",
    "patch_required", "schema_extension_required", "fields_to_add", "derivable_fields_to_add",
    "non_derivable_fields_to_add", "expected_row_grain", "expected_join_keys",
    "downstream_consumers", "patch_order", "test_required",
}
RULE_COLUMNS = {
    "proposed_output_field", "source_field_or_constant", "derivation_logic", "valid_values",
    "null_handling_rule", "unknown_handling_rule", "fail_handling_rule",
    "pit_safety_implication", "accepted_for_direct_evidence", "limitation_reason",
}
SCHEMA_COLUMNS = {
    "output_artifact", "row_grain", "required_join_keys", "new_field_name", "field_type",
    "required_non_null_for_direct_pass", "allowed_values", "default_value",
    "default_value_allowed_for_direct_pass", "validation_rule", "downstream_required_by",
    "backwards_compatibility_notes",
}
SAFETY_FALSE_FIELDS = [
    "formal_activation_allowed", "promotion_ready", "official_recommendation_created",
    "official_ranking_mutated", "official_weight_change_created",
    "official_weight_registry_mutated", "weight_mutated", "real_book_action_created",
    "trade_action_created", "broker_execution_supported", "performance_claim_created",
    "shadow_weight_expansion_allowed",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    assert rows
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected_hashes() -> dict[Path, str]:
    paths = [
        FACTORS / "V20_170_R1A_UPSTREAM_PIT_SOURCE_CONTRACT.csv",
        FACTORS / "V20_170_R1A_UPSTREAM_PIT_SOURCE_DISCOVERY.csv",
        FACTORS / "V20_170_R1A_TICKER_FACTOR_PIT_LINEAGE_EMITTER.csv",
        FACTORS / "V20_170_R1A_TICKER_LEVEL_PIT_DIRECT_STATUS.csv",
        FACTORS / "V20_170_R1A_PIT_DIRECT_STATUS_MISSING_FIELD_AUDIT.csv",
        FACTORS / "V20_170_R1A_PIT_SOURCE_CONTRACT_REPAIR_BACKLOG.csv",
        FACTORS / "V20_170_R1A_PIT_SOURCE_CONTRACT_COVERAGE_SUMMARY.csv",
        FACTORS / "V20_170_R1A_PIT_SOURCE_CONTRACT_NEXT_GATE.csv",
        FACTORS / "V20_170_R1A_PIT_SOURCE_CONTRACT_SAFETY_AUDIT.csv",
        CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
        CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv",
    ]
    return {p: digest(p) for p in paths if p.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_170_r1b", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.CONSOLIDATION = temp / "consolidation"
    module.FACTORS = temp / "factors"
    module.READ_CENTER = temp / "read_center"
    module.SCRIPTS = temp / "scripts" / "v20"
    module.R1A_INPUTS = [module.FACTORS / p.name for p in module.R1A_INPUTS]
    module.BASELINE = module.CONSOLIDATION / module.BASELINE.name
    module.ACTIVE_WEIGHT_REGISTRY = module.CONSOLIDATION / module.ACTIVE_WEIGHT_REGISTRY.name
    for key in list(module.OUTPUT_ARTIFACTS):
        module.OUTPUT_ARTIFACTS[key] = module.CONSOLIDATION / module.OUTPUT_ARTIFACTS[key].name
    for key in list(module.SCRIPT_BY_ARTIFACT):
        module.SCRIPT_BY_ARTIFACT[key] = module.SCRIPTS / module.SCRIPT_BY_ARTIFACT[key].name
    for name in ["OUT_PLAN", "OUT_MAPPING", "OUT_RULES", "OUT_TARGETS", "OUT_SCHEMA", "OUT_RISK", "OUT_GATE"]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    module.REPORT = module.READ_CENTER / module.REPORT.name
    module.OUTPUT_PATHS = [module.OUT_PLAN, module.OUT_MAPPING, module.OUT_RULES, module.OUT_TARGETS, module.OUT_SCHEMA, module.OUT_RISK, module.OUT_GATE]


def write_common_inputs(module, status_ok: bool = True) -> None:
    for path in module.R1A_INPUTS:
        if path.name == "V20_170_R1A_UPSTREAM_PIT_SOURCE_CONTRACT.csv":
            write_csv(path, [{"contract_field": field} for field in module.REQUIRED_FIELDS])
        elif path.name == "V20_170_R1A_PIT_DIRECT_STATUS_MISSING_FIELD_AUDIT.csv":
            write_csv(path, [
                {"ticker": "AAA", "factor_family": "TECHNICAL", "missing_required_field": "factor_input_as_of_date"},
                {"ticker": "AAA", "factor_family": "TECHNICAL", "missing_required_field": "factor_input_source_timestamp"},
                {"ticker": "BBB", "factor_family": "DATA_TRUST", "missing_required_field": "factor_input_point_in_time_safe"},
            ])
        elif path.name == "V20_170_R1A_PIT_SOURCE_CONTRACT_NEXT_GATE.csv":
            write_csv(path, [{"final_status": REQUIRED_R1A_STATUS if status_ok else "PASS"}])
        else:
            write_csv(path, [{"id": "X"}])
    canonical = module.OUTPUT_ARTIFACTS["CANONICAL"]
    write_csv(canonical, [{"ticker": "AAA", "factor_family": "TECHNICAL"}])
    script = module.SCRIPT_BY_ARTIFACT["CANONICAL"]
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("# temp producer\n", encoding="utf-8")


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE"
        if "data_trust_scoring_weight" in row:
            assert row["data_trust_scoring_weight"] == "0.0000000000"
        if "data_trust_role" in row:
            assert row["data_trust_role"] == "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == BLOCKED_STATUS


def test_blocked_wrong_r1a_status_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_common_inputs(module, status_ok=False)
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == BLOCKED_STATUS


def test_temp_patch_plan_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_common_inputs(module)
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        plan = read_csv(module.OUT_PLAN)
        assert gate["ready_for_v20_170_r1c_producer_patch"] == "TRUE"
        assert gate["ready_for_v20_170_r2_direct_status_retest"] == "FALSE"
        assert any(row["missing_required_field"] == "factor_input_as_of_date" for row in plan)


def test_data_trust_upstream_pit_producer_patch_plan() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected R1A/ranking/weight artifacts were mutated"
    stdout = result.stdout
    for expected in [
        PARTIAL_STATUS,
        f"V20_170_R1A_STATUS={REQUIRED_R1A_STATUS}",
        "MISSING_REQUIRED_PIT_FIELD_COUNT=3360",
        "AFFECTED_TICKER_COUNT=40",
        "AFFECTED_LINEAGE_ROW_COUNT=240",
        "PATCH_PLAN_CREATED=TRUE",
        "READY_FOR_V20_170_R1C_PRODUCER_PATCH=TRUE",
        "READY_FOR_V20_170_R2_DIRECT_STATUS_RETEST=FALSE",
        "READY_FOR_V20_171_GATE_ONLY_RANKING_SIMULATION=FALSE",
        "READY_FOR_OFFICIAL_USE=FALSE",
        "OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE",
        "OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE",
        "RANKING_SIMULATION_CREATED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "REAL_BOOK_ACTION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "PERFORMANCE_CLAIM_CREATED=FALSE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    plan = read_csv(OUTPUTS[0])
    mapping = read_csv(OUTPUTS[1])
    rules = read_csv(OUTPUTS[2])
    targets = read_csv(OUTPUTS[3])
    schema = read_csv(OUTPUTS[4])
    risk = read_csv(OUTPUTS[5])
    gate = read_csv(OUTPUTS[6])[0]
    assert PLAN_COLUMNS.issubset(plan[0].keys())
    assert TARGET_COLUMNS.issubset(targets[0].keys())
    assert RULE_COLUMNS.issubset(rules[0].keys())
    assert SCHEMA_COLUMNS.issubset(schema[0].keys())
    assert len(plan) == 19
    assert len(rules) == 19
    assert len(schema) == 19
    assert mapping
    assert any(row["patch_classification"] == "NEEDS_PRODUCER_PATCH" for row in plan)
    assert any(row["patch_classification"] == "NEEDS_NEW_SOURCE_CONTRACT" for row in plan)
    assert any(row["patch_required"] == "TRUE" for row in targets)
    assert gate["final_status"] == PARTIAL_STATUS
    assert gate["ready_for_v20_170_r1c_producer_patch"] == "TRUE"
    assert gate["ready_for_v20_170_r2_direct_status_retest"] == "FALSE"
    assert gate["ready_for_v20_171_gate_only_ranking_simulation"] == "FALSE"
    assert gate["ready_for_official_use"] == "FALSE"
    assert all(row["safety_passed"] == "TRUE" for row in risk)
    assert_safety([*plan, gate])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert PARTIAL_STATUS in report
    assert "does not mark PIT rows as PASS" in report


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_blocked_wrong_r1a_status_case()
    test_temp_patch_plan_case()
    test_data_trust_upstream_pit_producer_patch_plan()
    print("PASS test_v20_170_r1b_data_trust_upstream_pit_producer_patch_plan")
