#!/usr/bin/env python
"""Tests for V20.109-R10-R1 targeted prior failure repair iteration."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_109_r10_r1_targeted_prior_failure_repair_iteration.py"
OUT_ANATOMY = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R10_R1_120D_TOP20_FAILURE_ANATOMY.csv"
OUT_MOVEMENT = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R10_R1_FAILED_TICKER_MOVEMENT_AUDIT.csv"
OUT_LEVER = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R10_R1_REPAIR_LEVER_DIAGNOSTIC.csv"
OUT_SCENARIOS = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R10_R1_TARGETED_REPAIR_SCENARIOS.csv"
OUT_VALIDATION = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R10_R1_REPAIR_VALIDATION.csv"
OUT_CHURN = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R10_R1_CHURN_AND_STABILITY_AUDIT.csv"
OUT_GATE = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R10_R1_NEXT_STAGE_GATE.csv"
OUT_REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_109_R10_R1_TARGETED_PRIOR_FAILURE_REPAIR_ITERATION_REPORT.md"

ALLOWED_MECHANISMS = {
    "TARGET_TICKERS_NOT_ENTERING_TOP20",
    "TARGET_TICKERS_ENTER_BUT_CHURN_TOO_HIGH",
    "SCORE_COMPONENT_INSUFFICIENT",
    "BASELINE_QUALITY_COLLAPSE",
    "RANK_STABILITY_CONSTRAINT_TOO_STRICT",
    "REPAIR_LEVER_NOT_CONNECTED_TO_FAILURE",
    "INSUFFICIENT_EVIDENCE_TO_CLASSIFY",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    assert rows
    bad = [row for row in rows if row.get(field) not in {"FALSE", ""}]
    assert not bad, f"{field} was not FALSE: {bad[:3]}"


def test_targeted_prior_failure_repair_iteration() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_109_R10_R1_TARGETED_REPAIR_READY_FOR_R11",
        "PARTIAL_PASS_V20_109_R10_R1_FAILURE_ANATOMY_CREATED_REPAIR_LIMITED",
        "BLOCKED_V20_109_R10_R1_MISSING_REQUIRED_R10_INPUTS",
        "BLOCKED_V20_109_R10_R1_120D_TOP20_REPAIR_STILL_UNVALIDATED",
        "WARN_V20_109_R10_R1_CHURN_GATE_TOO_STRICT",
        "WARN_V20_109_R10_R1_REPAIR_LEVER_NOT_CONNECTED_TO_FAILURE",
        "WARN_V20_109_R10_R1_INSUFFICIENT_EVIDENCE_TO_CLASSIFY_FAILURE",
    ])
    for expected in [
        "R10_BLOCKED_GATE_CONSUMED=TRUE",
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

    for path in [OUT_ANATOMY, OUT_MOVEMENT, OUT_LEVER, OUT_SCENARIOS, OUT_VALIDATION, OUT_CHURN, OUT_GATE, OUT_REPORT]:
        assert path.exists(), f"missing output {path}"

    anatomy = read_csv(OUT_ANATOMY)
    movement = read_csv(OUT_MOVEMENT)
    lever = read_csv(OUT_LEVER)
    scenarios = read_csv(OUT_SCENARIOS)
    validation = read_csv(OUT_VALIDATION)
    churn = read_csv(OUT_CHURN)
    gate = read_csv(OUT_GATE)

    assert anatomy[0]["r10_blocked_gate_consumed"] == "TRUE"
    assert anatomy[0]["prior_failure_area"] == "120D_TOP20"
    assert anatomy[0]["failure_mechanism_classification"] in ALLOWED_MECHANISMS
    assert anatomy[0]["duplicate_rank_count"] == "0"
    assert anatomy[0]["missing_rank_count"] == "0"
    assert movement
    assert lever
    assert len(scenarios) == 8
    assert all(row["prior_failure_area"] == "120D_TOP20" for row in scenarios)
    assert all(row["target_forward_window"] == "120D" for row in scenarios)
    assert all(row["target_topn_group"] == "20" for row in scenarios)
    assert len(churn) == 16
    assert {int(row["top_n"]) for row in churn} == {20, 40}

    v = validation[0]
    assert v["repair_scenario_count"] == "8"
    assert v["duplicate_rank_count"] == "0"
    assert v["missing_rank_count"] == "0"
    assert v["v20_110_acceptance_gate_allowed"] == "FALSE"
    assert gate[0]["r10_r1_failure_anatomy_created"] == "TRUE"
    assert gate[0]["r10_r1_targeted_repair_scenarios_created"] == "TRUE"
    assert gate[0]["v20_110_acceptance_gate_allowed"] == "FALSE"

    for rows in [anatomy, movement, lever, scenarios, validation, churn, gate]:
        for field in [
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
        ]:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_targeted_prior_failure_repair_iteration()
    print("PASS_V20_109_R10_R1_TARGETED_PRIOR_FAILURE_REPAIR_ITERATION_TESTS")
