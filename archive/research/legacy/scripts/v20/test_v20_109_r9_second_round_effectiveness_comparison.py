#!/usr/bin/env python
"""Tests for V20.109-R9 second-round effectiveness comparison."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_109_r9_second_round_effectiveness_comparison.py"
OUT_COMPARE = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R9_SECOND_ROUND_EFFECTIVENESS_COMPARISON.csv"
OUT_PRIOR = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R9_PRIOR_FAILURE_REPAIR_COMPARISON.csv"
OUT_STABILITY = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R9_TOP20_TOP40_STABILITY_AUDIT.csv"
OUT_BASELINE = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R9_BASELINE_VS_SECOND_ROUND_SCENARIO_AUDIT.csv"
OUT_SELECTION = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R9_SCENARIO_SELECTION_RECOMMENDATION.csv"
OUT_GATE = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R9_NEXT_STAGE_GATE.csv"
OUT_REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_109_R9_SECOND_ROUND_EFFECTIVENESS_COMPARISON_REPORT.md"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    assert rows
    bad = [row for row in rows if row.get(field) not in {"FALSE", ""}]
    assert not bad, f"{field} was not FALSE: {bad[:3]}"


def test_second_round_effectiveness_comparison() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_109_R9_SECOND_ROUND_EFFECTIVENESS_COMPARISON_ACCEPTANCE_READY",
        "PARTIAL_PASS_V20_109_R9_EFFECTIVENESS_COMPARISON_WITH_LIMITED_EVIDENCE",
        "BLOCKED_V20_109_R9_MISSING_REQUIRED_R8_INPUTS",
        "BLOCKED_V20_109_R9_PRIOR_FAILURE_REPAIR_NOT_VALIDATED",
        "WARN_V20_109_R9_SCENARIO_EFFECTIVE_BUT_FRAGILE",
    ])
    for expected in [
        "SCENARIO_COUNT=8",
        "VALID_SCENARIO_COUNT=8",
        "PRIOR_FAILURE_AREA=120D_TOP20",
        "DUPLICATE_RANK_COUNT=0",
        "MISSING_RANK_COUNT=0",
        "V20_110_ACCEPTANCE_GATE_ALLOWED=FALSE",
        "ACCEPTED_WEIGHT_CREATED=FALSE",
        "OFFICIAL_WEIGHT_CREATED=FALSE",
        "NEW_WEIGHTS_CREATED=FALSE",
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

    for path in [OUT_COMPARE, OUT_PRIOR, OUT_STABILITY, OUT_BASELINE, OUT_SELECTION, OUT_GATE, OUT_REPORT]:
        assert path.exists(), f"missing output {path}"

    compare = read_csv(OUT_COMPARE)
    prior = read_csv(OUT_PRIOR)
    stability = read_csv(OUT_STABILITY)
    baseline = read_csv(OUT_BASELINE)
    selection = read_csv(OUT_SELECTION)
    gate = read_csv(OUT_GATE)

    scenario_ids = {row["simulation_scenario_id"] for row in compare}
    assert len(scenario_ids) == 8
    assert len(baseline) == 8
    assert len(prior) == 8
    assert len(stability) == 16
    assert {int(row["top_n"]) for row in stability} == {20, 40}
    assert all(row["prior_failure_area"] == "120D_TOP20" for row in prior)
    assert all(row["prior_failure_forward_window"] == "120D" for row in prior)
    assert all(row["prior_failure_top_n"] == "20" for row in prior)
    assert {row["forward_window"] for row in compare} == {"5D", "10D", "20D", "60D", "120D"}
    assert {int(row["top_n"]) for row in compare} == {10, 20, 40, 50, 100}

    assert gate[0]["scenario_count"] == "8"
    assert gate[0]["valid_scenario_count"] == "8"
    assert gate[0]["duplicate_rank_count"] == "0"
    assert gate[0]["missing_rank_count"] == "0"
    assert gate[0]["v20_110_acceptance_gate_allowed"] in {"TRUE", "FALSE"}
    if gate[0]["v20_110_acceptance_gate_allowed"] == "TRUE":
        assert gate[0]["prior_failure_repair_validated"] == "TRUE"
        assert gate[0]["top20_top40_churn_acceptable"] == "TRUE"
        assert gate[0]["evidence_limited_or_fragile"] == "FALSE"
    else:
        assert gate[0]["next_recommended_action"] in {
            "V20.109-R10_TARGETED_PRIOR_FAILURE_REPAIR",
            "V20.109-R10_SCENARIO_SELECTION_GUARD",
            "V20.109-R8_INPUT_REPAIR",
        }
    assert selection[0]["scenario_count"] == "8"
    assert selection[0]["v20_110_acceptance_gate_allowed"] == gate[0]["v20_110_acceptance_gate_allowed"]

    for rows in [compare, prior, stability, baseline, selection, gate]:
        for field in [
            "accepted_weight_created",
            "official_weight_created",
            "new_weights_created",
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
    test_second_round_effectiveness_comparison()
    print("PASS_V20_109_R9_SECOND_ROUND_EFFECTIVENESS_COMPARISON_TESTS")
