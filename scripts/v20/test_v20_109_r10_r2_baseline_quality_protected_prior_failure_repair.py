#!/usr/bin/env python
"""Tests for V20.109-R10-R2 baseline-quality-protected prior failure repair."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_109_r10_r2_baseline_quality_protected_prior_failure_repair.py"
OUT_COLLAPSE = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R10_R2_BASELINE_QUALITY_COLLAPSE_AUDIT.csv"
OUT_CONSTRAINTS = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R10_R2_QUALITY_PROTECTION_CONSTRAINTS.csv"
OUT_SCENARIOS = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R10_R2_QUALITY_PROTECTED_REPAIR_SCENARIOS.csv"
OUT_REPAIR = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R10_R2_120D_TOP20_REPAIR_UNDER_QUALITY_FLOOR.csv"
OUT_COMPONENT = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R10_R2_COMPONENT_DEVIATION_AUDIT.csv"
OUT_OVERLAP = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R10_R2_TOP20_TOP40_OVERLAP_FLOOR_AUDIT.csv"
OUT_GUARD = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R10_R2_REPAIR_SELECTION_GUARD.csv"
OUT_GATE = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R10_R2_NEXT_STAGE_GATE.csv"
OUT_REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_109_R10_R2_BASELINE_QUALITY_PROTECTED_PRIOR_FAILURE_REPAIR_REPORT.md"

EXPECTED_OUTPUTS = [
    OUT_COLLAPSE,
    OUT_CONSTRAINTS,
    OUT_SCENARIOS,
    OUT_REPAIR,
    OUT_COMPONENT,
    OUT_OVERLAP,
    OUT_GUARD,
    OUT_GATE,
    OUT_REPORT,
]

SAFETY_FIELDS = [
    "accepted_weight_created",
    "official_weight_created",
    "new_weights_created",
    "new_official_rerank_created",
    "official_ranking_created",
    "official_recommendation_created",
    "trade_action_created",
    "broker_execution_supported",
    "performance_effectiveness_claim_created",
    "authoritative_ranking_overwritten",
    "official_promotion_allowed",
    "is_official_weight",
    "weight_mutated",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    assert rows
    bad = [row for row in rows if row.get(field) not in {"FALSE", ""}]
    assert not bad, f"{field} was not FALSE: {bad[:3]}"


def test_baseline_quality_protected_prior_failure_repair() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_109_R10_R2_QUALITY_PROTECTED_REPAIR_READY_FOR_R11",
        "PARTIAL_PASS_V20_109_R10_R2_QUALITY_PROTECTED_REPAIR_LIMITED",
        "BLOCKED_V20_109_R10_R2_MISSING_REQUIRED_R10_R1_INPUTS",
        "BLOCKED_V20_109_R10_R2_BASELINE_QUALITY_COLLAPSE_UNRESOLVED",
        "BLOCKED_V20_109_R10_R2_120D_TOP20_REPAIR_STILL_UNVALIDATED",
        "WARN_V20_109_R10_R2_REPAIR_EFFECTIVE_BUT_QUALITY_FLOOR_FAILED",
        "WARN_V20_109_R10_R2_REPAIR_EFFECTIVE_BUT_COMPONENT_DEVIATION_TOO_HIGH",
        "WARN_V20_109_R10_R2_REPAIR_EFFECTIVE_BUT_OVERLAP_FLOOR_FAILED",
    ])
    for expected in [
        "R10_R1_RESULT_CONSUMED=TRUE",
        "FAILURE_MECHANISM_FOUND=BASELINE_QUALITY_COLLAPSE",
        "PRIOR_FAILURE_AREA=120D_TOP20",
        "REPAIR_SCENARIO_COUNT=8",
        "DUPLICATE_RANK_COUNT=0",
        "MISSING_RANK_COUNT=0",
        "V20_110_ACCEPTANCE_GATE_ALLOWED=FALSE",
        "ACCEPTED_WEIGHT_CREATED=FALSE",
        "OFFICIAL_WEIGHT_CREATED=FALSE",
        "NEW_WEIGHTS_CREATED=FALSE",
        "NEW_OFFICIAL_RERANK_CREATED=FALSE",
        "OFFICIAL_RANKING_CREATED=FALSE",
        "AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED=FALSE",
        "OFFICIAL_PROMOTION_ALLOWED=FALSE",
        "IS_OFFICIAL_WEIGHT=FALSE",
    ]:
        assert expected in stdout

    for path in EXPECTED_OUTPUTS:
        assert path.exists(), f"missing output {path}"

    collapse = read_csv(OUT_COLLAPSE)
    constraints = read_csv(OUT_CONSTRAINTS)
    scenarios = read_csv(OUT_SCENARIOS)
    repair = read_csv(OUT_REPAIR)
    component = read_csv(OUT_COMPONENT)
    overlap = read_csv(OUT_OVERLAP)
    guard = read_csv(OUT_GUARD)
    gate = read_csv(OUT_GATE)

    assert collapse[0]["r10_r1_result_consumed"] == "TRUE"
    assert collapse[0]["failure_mechanism_found"] == "BASELINE_QUALITY_COLLAPSE"
    assert collapse[0]["collapse_source_status"] == "BASELINE_QUALITY_COLLAPSE_CONFIRMED"
    assert collapse[0]["duplicate_rank_count"] == "0"
    assert collapse[0]["missing_rank_count"] == "0"

    constraint_names = {row["constraint_name"] for row in constraints}
    assert {
        "baseline_quality_floor",
        "top20_overlap_floor",
        "top40_overlap_floor",
        "component_deviation_cap",
        "repair_intensity_cap",
    }.issubset(constraint_names)

    assert len(scenarios) == 8
    assert all(row["prior_failure_area"] == "120D_TOP20" for row in scenarios)
    assert all(row["target_forward_window"] == "120D" for row in scenarios)
    assert all(row["target_topn_group"] == "20" for row in scenarios)
    assert all(row["quality_protected"] == "TRUE" for row in scenarios)
    assert all(row["broad_uncontrolled_repair"] == "FALSE" for row in scenarios)

    assert len(repair) == 8
    assert all(row["prior_failure_area"] == "120D_TOP20" for row in repair)
    assert all(row["baseline_quality_floor"] for row in repair)
    assert {row["repair_120d_top20_validated"] for row in repair}.issubset({"TRUE", "FALSE"})

    assert len(component) == 48
    assert {row["factor_family"] for row in component} == {
        "fundamental",
        "technical",
        "strategy",
        "risk",
        "market_regime",
        "data_trust",
    }
    assert all(row["component_deviation_cap"] for row in component)

    assert len(overlap) == 16
    assert {int(row["top_n"]) for row in overlap} == {20, 40}
    assert all(row["overlap_floor"] for row in overlap)

    assert guard[0]["sufficient_for_v20_110_acceptance_gate"] == "FALSE"
    assert gate[0]["baseline_quality_protected_repair_created"] == "TRUE"
    assert gate[0]["failure_mechanism_confirmed"] == "TRUE"
    assert gate[0]["repair_scenario_count"] == "8"
    assert gate[0]["v20_110_acceptance_gate_allowed"] == "FALSE"
    if gate[0]["v20_109_r11_repair_robustness_validation_allowed"] == "TRUE":
        assert gate[0]["next_recommended_action"] == "V20.109-R11_REPAIR_ROBUSTNESS_VALIDATION"
    else:
        assert gate[0]["next_recommended_action"] == "V20.109-R10-R3_BASELINE_QUALITY_PROTECTED_REPAIR_ITERATION"

    for rows in [collapse, constraints, scenarios, repair, component, overlap, guard, gate]:
        for field in SAFETY_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_baseline_quality_protected_prior_failure_repair()
    print("PASS_V20_109_R10_R2_BASELINE_QUALITY_PROTECTED_PRIOR_FAILURE_REPAIR_TESTS")
