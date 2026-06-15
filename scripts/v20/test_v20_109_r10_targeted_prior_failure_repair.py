#!/usr/bin/env python
"""Tests for V20.109-R10 targeted prior failure repair."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_109_r10_targeted_prior_failure_repair.py"
OUT_SCENARIOS = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R10_TARGETED_PRIOR_FAILURE_REPAIR_SCENARIOS.csv"
OUT_REPAIR = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R10_120D_TOP20_REPAIR_AUDIT.csv"
OUT_CHURN = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R10_TOP20_TOP40_CHURN_CONSTRAINT_AUDIT.csv"
OUT_RERANK = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R10_REPAIR_RERANK_AUDIT.csv"
OUT_VALIDATION = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R10_REPAIR_EFFECTIVENESS_VALIDATION.csv"
OUT_GUARD = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R10_SCENARIO_SELECTION_GUARD.csv"
OUT_GATE = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R10_NEXT_STAGE_GATE.csv"
OUT_REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_109_R10_TARGETED_PRIOR_FAILURE_REPAIR_REPORT.md"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    assert rows
    bad = [row for row in rows if row.get(field) not in {"FALSE", ""}]
    assert not bad, f"{field} was not FALSE: {bad[:3]}"


def test_targeted_prior_failure_repair() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_109_R10_TARGETED_PRIOR_FAILURE_REPAIR_READY_FOR_R11",
        "PARTIAL_PASS_V20_109_R10_REPAIR_CREATED_WITH_LIMITED_EVIDENCE",
        "BLOCKED_V20_109_R10_MISSING_REQUIRED_R9_INPUTS",
        "BLOCKED_V20_109_R10_120D_TOP20_REPAIR_STILL_UNVALIDATED",
        "WARN_V20_109_R10_REPAIR_EFFECTIVE_BUT_CHURN_TOO_HIGH",
        "WARN_V20_109_R10_REPAIR_EFFECTIVE_BUT_NEEDS_ROBUSTNESS_VALIDATION",
    ])
    for expected in [
        "SEED_SCENARIO_ID=SIM2_002",
        "PRIOR_FAILURE_AREA=120D_TOP20",
        "REPAIR_SCENARIO_COUNT=8",
        "DUPLICATE_RANK_COUNT=0",
        "MISSING_RANK_COUNT=0",
        "V20_110_ACCEPTANCE_GATE_ALLOWED=FALSE",
        "ACCEPTED_WEIGHT_CREATED=FALSE",
        "OFFICIAL_WEIGHT_CREATED=FALSE",
        "NEW_WEIGHTS_CREATED=FALSE",
        "NEW_RERANK_CREATED=FALSE",
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

    for path in [OUT_SCENARIOS, OUT_REPAIR, OUT_CHURN, OUT_RERANK, OUT_VALIDATION, OUT_GUARD, OUT_GATE, OUT_REPORT]:
        assert path.exists(), f"missing output {path}"

    scenarios = read_csv(OUT_SCENARIOS)
    repair = read_csv(OUT_REPAIR)
    churn = read_csv(OUT_CHURN)
    rerank = read_csv(OUT_RERANK)
    validation = read_csv(OUT_VALIDATION)
    guard = read_csv(OUT_GUARD)
    gate = read_csv(OUT_GATE)

    assert len(scenarios) == 8
    assert len(repair) == 8
    assert len(churn) == 16
    assert len(rerank) == 8 * 40
    assert all(row["seed_scenario_id"] == "SIM2_002" for row in scenarios)
    assert all(row["prior_failure_area"] == "120D_TOP20" for row in scenarios)
    assert all(row["target_forward_window"] == "120D" for row in scenarios)
    assert all(row["target_topn_group"] == "20" for row in scenarios)
    assert all(row["prior_failure_area"] == "120D_TOP20" for row in repair)
    assert all(row["target_forward_window"] == "120D" for row in repair)
    assert all(row["target_topn_group"] == "20" for row in repair)
    assert {int(row["top_n"]) for row in churn} == {20, 40}

    v = validation[0]
    assert v["repair_scenario_count"] == "8"
    assert v["duplicate_rank_count"] == "0"
    assert v["missing_rank_count"] == "0"
    assert v["r9_seed_scenario_id"] == "SIM2_002"
    assert v["prior_failure_area"] == "120D_TOP20"
    assert v["accepted_weight_created"] == "FALSE"
    assert v["new_rerank_created"] == "FALSE"

    assert guard[0]["sufficient_for_v20_110_acceptance_gate"] == "FALSE"
    assert gate[0]["v20_110_acceptance_gate_allowed"] == "FALSE"
    if gate[0]["v20_109_r11_repair_robustness_validation_allowed"] == "TRUE":
        assert gate[0]["next_recommended_action"] == "V20.109-R11_REPAIR_ROBUSTNESS_VALIDATION"
    else:
        assert gate[0]["next_recommended_action"] == "V20.109-R10_TARGETED_PRIOR_FAILURE_REPAIR_ITERATION"

    for rows in [scenarios, repair, churn, rerank, validation, guard, gate]:
        for field in [
            "accepted_weight_created",
            "official_weight_created",
            "new_weights_created",
            "new_rerank_created",
            "official_ranking_created",
            "official_recommendation_created",
            "trade_action_created",
            "broker_execution_supported",
            "performance_effectiveness_claim_created",
            "authoritative_ranking_overwritten",
            "official_promotion_allowed",
            "is_official_weight",
            "weight_mutated",
        ]:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_targeted_prior_failure_repair()
    print("PASS_V20_109_R10_TARGETED_PRIOR_FAILURE_REPAIR_TESTS")
