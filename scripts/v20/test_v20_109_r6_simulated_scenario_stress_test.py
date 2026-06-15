#!/usr/bin/env python
"""Tests for V20.109-R6 simulated scenario stress test."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_109_r6_simulated_scenario_stress_test.py"
R5_SUMMARY = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R5_CANDIDATE_SCENARIO_ROBUSTNESS_SUMMARY.csv"
R3_RERANK = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R3_SIMULATED_WEIGHT_STRICT_EQUITY_RERANK.csv"
OUT_SUMMARY = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R6_SIMULATED_SCENARIO_STRESS_TEST_SUMMARY.csv"
OUT_WINDOW = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R6_FORWARD_WINDOW_STRESS_AUDIT.csv"
OUT_TOPN = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R6_TOPN_CONCENTRATION_AND_TURNOVER_STRESS_AUDIT.csv"
OUT_DOWNSIDE = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R6_DOWNSIDE_AND_HIT_RATE_STRESS_AUDIT.csv"
OUT_PRIOR = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R6_PRIOR_FAILURE_AREA_REPAIR_AUDIT.csv"
OUT_SELECTION = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R6_STRESS_TEST_SELECTION_GATE.csv"
OUT_GATE = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R6_NEXT_STAGE_GATE.csv"
OUT_REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_109_R6_SIMULATED_SCENARIO_STRESS_TEST_REPORT.md"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    assert rows
    bad = [row for row in rows if row.get(field) not in {"FALSE", ""}]
    assert not bad, f"{field} was not FALSE: {bad[:3]}"


def test_simulated_scenario_stress_test() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_109_R6_SIMULATED_SCENARIO_STRESS_TEST",
        "PARTIAL_PASS_V20_109_R6_STRESS_TEST_WITH_LIMITED_FORWARD_OUTCOME_COVERAGE",
        "WARN_V20_109_R6_SCENARIO_FRAGILE_OR_PRIOR_FAILURE_NOT_REPAIRED",
        "BLOCKED_V20_109_R6_MISSING_R5_SELECTION_OR_EFFECTIVENESS_INPUTS",
    ])
    for expected in [
        "SELECTED_SIMULATION_SCENARIO_ID=SIM_004",
        "SELECTED_SCENARIO_TYPE=HIGHER_FUNDAMENTAL_WEIGHT_SCENARIO",
        "STRICT_EQUITY_CANDIDATE_COUNT=297",
        "EVALUATED_CELL_COUNT=20",
        "DOMINANT_PRIOR_FAILURE_AREA=120D_TOP20",
        "FORWARD_WINDOWS=5D,10D,20D,60D,120D",
        "TOPN_GROUPS=10,20,50,100",
        "ACCEPTED_WEIGHT_CREATED=FALSE",
        "NEW_WEIGHTS_CREATED=FALSE",
        "NEW_RERANK_CREATED=FALSE",
        "V20_107_WEIGHT_MUTATED=FALSE",
        "V20_98B_R5_WEIGHT_MUTATED=FALSE",
        "OFFICIAL_WEIGHT_CREATED=FALSE",
        "OFFICIAL_RANKING_CREATED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED=FALSE",
        "V20_110_ACCEPTANCE_GATE_ALLOWED=FALSE",
        "OFFICIAL_PROMOTION_ALLOWED=FALSE",
        "IS_OFFICIAL_WEIGHT=FALSE",
    ]:
        assert expected in stdout

    for path in [OUT_SUMMARY, OUT_WINDOW, OUT_TOPN, OUT_DOWNSIDE, OUT_PRIOR, OUT_SELECTION, OUT_GATE, OUT_REPORT]:
        assert path.exists(), f"missing output {path}"

    r5 = read_csv(R5_SUMMARY)[0]
    r3_selected = [row for row in read_csv(R3_RERANK) if row["simulation_scenario_id"] == r5["selected_simulation_scenario_id"]]
    summary = read_csv(OUT_SUMMARY)
    window = read_csv(OUT_WINDOW)
    topn = read_csv(OUT_TOPN)
    downside = read_csv(OUT_DOWNSIDE)
    prior = read_csv(OUT_PRIOR)
    selection = read_csv(OUT_SELECTION)
    gate = read_csv(OUT_GATE)

    assert r5["selected_simulation_scenario_id"] == "SIM_004"
    assert r5["selected_scenario_type"] == "HIGHER_FUNDAMENTAL_WEIGHT_SCENARIO"
    assert len({row["ticker"] for row in r3_selected}) == 297

    assert summary[0]["selected_simulation_scenario_id"] == "SIM_004"
    assert summary[0]["selected_scenario_type"] == "HIGHER_FUNDAMENTAL_WEIGHT_SCENARIO"
    assert summary[0]["strict_equity_candidate_count"] == "297"
    assert summary[0]["evaluated_forward_window_count"] == "5"
    assert summary[0]["evaluated_topn_group_count"] == "4"
    assert summary[0]["evaluated_cell_count"] == "20"
    assert summary[0]["dominant_prior_failure_area"] == "120D_TOP20"
    assert summary[0]["overall_stress_status"] in {
        "PASS_RESEARCH_ONLY_STRESS_TEST",
        "PARTIAL_PASS_LIMITED_COVERAGE_STRESS_TEST",
        "WARN_MIXED_OR_FRAGILE_STRESS_TEST",
        "FAIL_STRESS_TEST",
    }

    assert len(window) == 5
    assert {row["forward_window"] for row in window} == {"5D", "10D", "20D", "60D", "120D"}
    assert all(row["window_cell_count"] == "4" for row in window)
    assert len(topn) == 4
    assert {int(row["top_n"]) for row in topn} == {10, 20, 50, 100}
    assert len(downside) == 20
    assert {row["forward_window"] for row in downside} == {"5D", "10D", "20D", "60D", "120D"}
    assert {int(row["top_n"]) for row in downside} == {10, 20, 50, 100}
    assert all(row["downside_hit_rate_stress_status"] in {
        "PASS_STRESS_CELL",
        "WARN_MIXED_STRESS_CELL",
        "FAIL_STRESS_CELL",
        "INSUFFICIENT_COVERAGE_STRESS_CELL",
    } for row in downside)

    assert len(prior) == 1
    assert prior[0]["prior_failure_area"] == "120D_TOP20"
    assert prior[0]["prior_failure_forward_window"] == "120D"
    assert prior[0]["prior_failure_top_n"] == "20"
    assert prior[0]["failure_area_repaired"] in {"TRUE", "FALSE"}

    assert selection[0]["selected_by_r5"] == "TRUE"
    assert selection[0]["sufficient_for_research_acceptance_review"] == "FALSE"
    assert gate[0]["stress_test_created"] == "TRUE"
    assert gate[0]["v20_110_acceptance_gate_allowed"] == "FALSE"

    for rows in [summary, window, topn, downside, prior, selection, gate]:
        for field in [
            "accepted_weight_created",
            "new_weights_created",
            "new_rerank_created",
            "v20_107_weight_mutated",
            "v20_98b_r5_weight_mutated",
            "official_weight_created",
            "official_ranking_created",
            "official_recommendation_created",
            "trade_action_created",
            "broker_execution_supported",
            "performance_effectiveness_claim_created",
            "official_promotion_allowed",
            "is_official_weight",
            "weight_mutated",
            "authoritative_ranking_overwritten",
        ]:
            if field in rows[0]:
                assert_false(rows, field)
        if "simulation_only" in rows[0]:
            assert all(row["simulation_only"] == "TRUE" for row in rows)


if __name__ == "__main__":
    test_simulated_scenario_stress_test()
    print("PASS_V20_109_R6_SIMULATED_SCENARIO_STRESS_TEST_TESTS")
