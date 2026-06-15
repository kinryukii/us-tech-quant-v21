#!/usr/bin/env python
"""Tests for V20.109-R1 underperformance decomposition and repair plan."""

from __future__ import annotations

import csv
import subprocess
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_109_r1_shadow_underperformance_decomposition_and_weight_repair_plan.py"
V109_MATRIX = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_FORWARD_WINDOW_TOPN_EFFECTIVENESS_MATRIX.csv"
OUT_SUMMARY = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R1_UNDERPERFORMANCE_DECOMPOSITION_SUMMARY.csv"
OUT_FAILURE = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R1_FORWARD_WINDOW_TOPN_FAILURE_MAP.csv"
OUT_FACTOR = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R1_FACTOR_FAMILY_FAILURE_ATTRIBUTION.csv"
OUT_BUCKET = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R1_RANK_DELTA_BUCKET_EFFECTIVENESS_AUDIT.csv"
OUT_PLAN = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R1_SHADOW_WEIGHT_REPAIR_PLAN.csv"
OUT_GATE = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R1_NEXT_STAGE_GATE.csv"
OUT_REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_109_R1_SHADOW_UNDERPERFORMANCE_DECOMPOSITION_AND_WEIGHT_REPAIR_PLAN_REPORT.md"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    assert rows
    bad = [row for row in rows if row.get(field) not in {"FALSE", ""}]
    assert not bad, f"{field} was not FALSE: {bad[:3]}"


def test_underperformance_repair_plan() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    assert any(s in stdout for s in [
        "PASS_V20_109_R1_SHADOW_UNDERPERFORMANCE_DECOMPOSITION_AND_WEIGHT_REPAIR_PLAN",
        "PARTIAL_PASS_V20_109_R1_UNDERPERFORMANCE_DECOMPOSITION_WITH_LIMITED_FORWARD_OUTCOME_COVERAGE",
        "BLOCKED_V20_109_R1_MISSING_REQUIRED_EFFECTIVENESS_INPUTS",
    ])
    for expected in [
        "EVALUATED_CELL_COUNT=20",
        "SHADOW_OUTPERFORMANCE_CELL_COUNT=4",
        "BASELINE_OUTPERFORMANCE_CELL_COUNT=16",
        "NEW_WEIGHTS_CREATED=FALSE",
        "NEW_RERANK_CREATED=FALSE",
        "V20_110_ACCEPTANCE_GATE_ALLOWED=FALSE",
        "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED=FALSE",
        "OFFICIAL_RANKING_CREATED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "IS_OFFICIAL_WEIGHT=FALSE",
        "WEIGHT_MUTATED=FALSE",
    ]:
        assert expected in stdout

    for path in [OUT_SUMMARY, OUT_FAILURE, OUT_FACTOR, OUT_BUCKET, OUT_PLAN, OUT_GATE, OUT_REPORT]:
        assert path.exists(), f"missing output {path}"

    matrix = read_csv(V109_MATRIX)
    summary = read_csv(OUT_SUMMARY)
    failure = read_csv(OUT_FAILURE)
    factor = read_csv(OUT_FACTOR)
    bucket = read_csv(OUT_BUCKET)
    plan = read_csv(OUT_PLAN)
    gate = read_csv(OUT_GATE)

    shadow = sum(1 for row in matrix if Decimal(row["shadow_minus_baseline_mean_return"]) > 0)
    baseline = sum(1 for row in matrix if Decimal(row["shadow_minus_baseline_mean_return"]) < 0)
    mixed = len(matrix) - shadow - baseline
    assert len(matrix) == 20
    assert len(failure) == 20
    assert summary[0]["evaluated_cell_count"] == "20"
    assert summary[0]["shadow_outperformance_cell_count"] == str(shadow) == "4"
    assert summary[0]["baseline_outperformance_cell_count"] == str(baseline) == "16"
    assert summary[0]["mixed_or_inconclusive_cell_count"] == str(mixed)

    assert {row["top_n"] for row in failure} == {"10", "20", "50", "100"}
    assert {row["forward_window"] for row in failure} == {"5D", "10D", "20D", "60D", "120D"}
    assert len(factor) == 6
    assert {row["factor_family"] for row in factor} == {"FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"}
    assert len(bucket) == 25
    assert all(row["diagnostic_only"] == "TRUE" for row in factor)
    assert all(row["diagnostic_only"] == "TRUE" for row in bucket)

    assert len(plan) >= 6
    assert all(row["proposed_weight_mutation_performed"] == "FALSE" for row in plan)
    assert all(row["proposed_rerank_created"] == "FALSE" for row in plan)
    assert all(row["is_official_weight"] == "FALSE" for row in plan)
    assert all(row["weight_mutated"] == "FALSE" for row in plan)

    g = gate[0]
    assert g["underperformance_decomposition_created"] == "TRUE"
    assert g["weight_repair_plan_created"] == "TRUE"
    assert g["new_weights_created"] == "FALSE"
    assert g["new_rerank_created"] == "FALSE"
    assert g["v20_110_acceptance_gate_allowed"] == "FALSE"
    assert g["v20_109_r2_weight_simulation_allowed"] == "TRUE"
    assert "WEIGHT_REPAIR_SIMULATION" in g["recommended_next_stage"]

    for rows in [summary, failure, factor, bucket, plan, gate]:
        for field in [
            "performance_effectiveness_claim_created",
            "official_ranking_created",
            "official_recommendation_created",
            "trade_action_created",
            "broker_execution_supported",
            "weight_mutated",
        ]:
            if field in rows[0]:
                assert_false(rows, field)
        if "official_promotion_allowed" in rows[0]:
            assert_false(rows, "official_promotion_allowed")
        if "is_official_weight" in rows[0]:
            assert_false(rows, "is_official_weight")


if __name__ == "__main__":
    test_underperformance_repair_plan()
    print("PASS_V20_109_R1_UNDERPERFORMANCE_REPAIR_PLAN_TESTS")
