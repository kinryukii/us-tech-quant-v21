#!/usr/bin/env python
"""Tests for V20.111 shadow acceptance review."""

from __future__ import annotations

import csv
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_111_shadow_acceptance_review.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"

OUT_DECISION = CONSOLIDATION / "V20_111_SHADOW_ACCEPTANCE_REVIEW_DECISION.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_111_SELECTED_SCENARIO_LINEAGE_AUDIT.csv"
OUT_CRITERIA = CONSOLIDATION / "V20_111_SHADOW_REVIEW_CRITERIA_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_111_SHADOW_ACCEPTANCE_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_111_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_111_SHADOW_ACCEPTANCE_REVIEW_REPORT.md"

OUTPUTS = [OUT_DECISION, OUT_LINEAGE, OUT_CRITERIA, OUT_SAFETY, OUT_GATE, OUT_REPORT]

REQUIRED_COLUMNS = {
    OUT_DECISION: {
        "v20_110_gate_consumed",
        "v20_110_shadow_acceptance_review_allowed",
        "selected_repair_scenario_id",
        "selected_scenario_lineage_valid",
        "shadow_only_confirmed",
        "safety_boundary_audit_passed",
        "v20_112_shadow_integration_plan_allowed",
        "shadow_acceptance_review_status",
    },
    OUT_LINEAGE: {
        "selected_repair_scenario_id",
        "v20_110_gate_selected_scenario_id",
        "v20_110_manifest_selected_scenario_id",
        "r11_validation_selected_scenario_id",
        "lineage_valid",
    },
    OUT_CRITERIA: {"criterion_name", "required_value", "observed_value", "criterion_passed"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {
        "v20_110_gate_consumed",
        "v20_110_shadow_acceptance_review_allowed",
        "selected_repair_scenario_id",
        "v20_112_shadow_integration_plan_allowed",
        "shadow_acceptance_review_status",
    },
}

PROHIBITED_FALSE_FIELDS = [
    "accepted_weight_created",
    "accepted_weights_created",
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
    "performance_claim_created",
    "performance_claims_created",
    "performance_effectiveness_claim_created",
    "real_book_weight_created",
    "real_book_action_created",
    "official_promotion_allowed",
    "promotion_ready",
    "is_official_weight",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    bad = [row for row in rows if row.get(field) not in {"", "FALSE"}]
    assert not bad, f"{field} was not FALSE: {bad[:3]}"


def load_module():
    spec = importlib.util.spec_from_file_location("v20_111_shadow_acceptance_review_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        module.IN_V110_DECISION = temp / "missing_decision.csv"
        module.IN_V110_GATE = temp / "missing_gate.csv"
        module.IN_V110_SELECTED = temp / "missing_selected.csv"
        module.IN_V110_SAFETY = temp / "missing_safety.csv"
        module.IN_V110_MANIFEST = temp / "missing_manifest.csv"
        module.IN_R11_VALIDATION = temp / "missing_r11_validation.csv"
        module.IN_R11_SELECTION = temp / "missing_r11_selection.csv"
        module.REQUIRED_INPUTS = [
            module.IN_V110_DECISION,
            module.IN_V110_GATE,
            module.IN_V110_SELECTED,
            module.IN_V110_SAFETY,
            module.IN_V110_MANIFEST,
            module.IN_R11_VALIDATION,
            module.IN_R11_SELECTION,
        ]
        module.OUT_DECISION = temp / "V20_111_SHADOW_ACCEPTANCE_REVIEW_DECISION.csv"
        module.OUT_LINEAGE = temp / "V20_111_SELECTED_SCENARIO_LINEAGE_AUDIT.csv"
        module.OUT_CRITERIA = temp / "V20_111_SHADOW_REVIEW_CRITERIA_AUDIT.csv"
        module.OUT_SAFETY = temp / "V20_111_SHADOW_ACCEPTANCE_SAFETY_BOUNDARY_AUDIT.csv"
        module.OUT_GATE = temp / "V20_111_NEXT_STAGE_GATE.csv"
        module.REPORT = temp / "V20_111_SHADOW_ACCEPTANCE_REVIEW_REPORT.md"
        assert module.main() == 0
        blocked = read_csv(module.OUT_DECISION)[0]
        assert blocked["shadow_acceptance_review_status"] == "BLOCKED_V20_111_SHADOW_ACCEPTANCE_REVIEW"
        assert blocked["v20_112_shadow_integration_plan_allowed"] == "FALSE"


def test_shadow_acceptance_review() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    assert "PASS_V20_111_SHADOW_ACCEPTANCE_REVIEW_READY_FOR_V20_112" in stdout
    for expected in [
        "V20_110_GATE_CONSUMED=TRUE",
        "V20_110_SHADOW_ACCEPTANCE_REVIEW_ALLOWED=TRUE",
        f"SELECTED_REPAIR_SCENARIO_ID={EXPECTED_SCENARIO_ID}",
        "SELECTED_SCENARIO_MATCHES_V20_110=TRUE",
        "SELECTED_SCENARIO_LINEAGE_VALID=TRUE",
        "SHADOW_ONLY_CONFIRMED=TRUE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_112_SHADOW_INTEGRATION_PLAN_ALLOWED=TRUE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "OFFICIAL_RANKING_CREATED=FALSE",
        "ACCEPTED_WEIGHT_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_ACTION_CREATED=FALSE",
        "AUTHORITATIVE_OVERWRITE_CREATED=FALSE",
        "WEIGHT_MUTATED=FALSE",
        "PERFORMANCE_CLAIM_CREATED=FALSE",
        "REAL_BOOK_WEIGHT_CREATED=FALSE",
        "PROMOTION_READY=FALSE",
    ]:
        assert expected in stdout, expected

    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"

    decision = read_csv(OUT_DECISION)
    lineage = read_csv(OUT_LINEAGE)
    criteria = read_csv(OUT_CRITERIA)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)

    d = decision[0]
    assert d["v20_110_gate_consumed"] == "TRUE"
    assert d["v20_110_shadow_acceptance_review_allowed"] == "TRUE"
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["selected_scenario_lineage_valid"] == "TRUE"
    assert d["shadow_only_confirmed"] == "TRUE"
    assert d["safety_boundary_audit_passed"] == "TRUE"
    assert d["shadow_acceptance_review_status"] == "PASS_V20_111_SHADOW_ACCEPTANCE_REVIEW_READY_FOR_V20_112"
    assert d["v20_112_shadow_integration_plan_allowed"] == "TRUE"

    assert lineage
    assert lineage[0]["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert lineage[0]["lineage_valid"] == "TRUE"
    assert all(row["criterion_passed"] == "TRUE" for row in criteria)
    assert all(row["observed_true_count"] == "0" for row in safety)
    assert all(row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["v20_112_shadow_integration_plan_allowed"] == "TRUE"

    strict_conditions = [
        d["v20_110_shadow_acceptance_review_allowed"] == "TRUE",
        d["selected_scenario_id_present"] == "TRUE",
        d["selected_scenario_matches_v20_110"] == "TRUE",
        d["selected_scenario_lineage_valid"] == "TRUE",
        d["shadow_only_confirmed"] == "TRUE",
        d["safety_boundary_audit_passed"] == "TRUE",
        d["prohibited_action_true_count"] == "0",
        d["criteria_all_passed"] == "TRUE",
    ]
    assert (d["shadow_acceptance_review_status"] == "PASS_V20_111_SHADOW_ACCEPTANCE_REVIEW_READY_FOR_V20_112") == all(strict_conditions)

    for rows in [decision, lineage, criteria, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_shadow_acceptance_review()
    print("PASS_V20_111_SHADOW_ACCEPTANCE_REVIEW_TESTS")
