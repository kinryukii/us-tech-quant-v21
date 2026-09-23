#!/usr/bin/env python
"""Tests for V20.109-R5 candidate scenario robustness validation."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_109_r5_candidate_scenario_robustness_validation.py"
R4_SELECTION = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R4_EVIDENCE_QUALITY_AND_SELECTION_AUDIT.csv"
R3_RERANK = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R3_SIMULATED_WEIGHT_STRICT_EQUITY_RERANK.csv"
OUT_SUMMARY = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R5_CANDIDATE_SCENARIO_ROBUSTNESS_SUMMARY.csv"
OUT_WINDOW = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R5_WINDOW_TOPN_ROBUSTNESS_AUDIT.csv"
OUT_BUCKET = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R5_RANK_BUCKET_ROBUSTNESS_AUDIT.csv"
OUT_ATTR = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R5_FACTOR_FAMILY_ROBUSTNESS_ATTRIBUTION.csv"
OUT_SELECTION = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R5_SCENARIO_STABILITY_AND_SELECTION_AUDIT.csv"
OUT_GATE = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R5_NEXT_STAGE_GATE.csv"
OUT_REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_109_R5_CANDIDATE_SCENARIO_ROBUSTNESS_VALIDATION_REPORT.md"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    assert rows
    bad = [row for row in rows if row.get(field) not in {"FALSE", ""}]
    assert not bad, f"{field} was not FALSE: {bad[:3]}"


def test_candidate_scenario_robustness_validation() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_109_R5_CANDIDATE_SCENARIO_ROBUSTNESS_VALIDATION",
        "PARTIAL_PASS_V20_109_R5_ROBUSTNESS_VALIDATION_WITH_LIMITED_FORWARD_OUTCOME_COVERAGE",
        "WARN_V20_109_R5_SELECTED_SCENARIO_NOT_ROBUST",
        "BLOCKED_V20_109_R5_MISSING_R4_SELECTION_OR_SCENARIO_INPUTS",
    ])
    for expected in [
        "SELECTED_SIMULATION_SCENARIO_ID=SIM_004",
        "SELECTED_SCENARIO_TYPE=HIGHER_FUNDAMENTAL_WEIGHT_SCENARIO",
        "STRICT_EQUITY_CANDIDATE_COUNT=297",
        "EVALUATED_CELL_COUNT=20",
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

    for path in [OUT_SUMMARY, OUT_WINDOW, OUT_BUCKET, OUT_ATTR, OUT_SELECTION, OUT_GATE, OUT_REPORT]:
        assert path.exists(), f"missing output {path}"

    r4_selection = read_csv(R4_SELECTION)[0]
    r3_selected = [row for row in read_csv(R3_RERANK) if row["simulation_scenario_id"] == r4_selection["best_scenario_id"]]
    summary = read_csv(OUT_SUMMARY)
    window = read_csv(OUT_WINDOW)
    bucket = read_csv(OUT_BUCKET)
    attr = read_csv(OUT_ATTR)
    selection = read_csv(OUT_SELECTION)
    gate = read_csv(OUT_GATE)

    assert r4_selection["best_scenario_id"] == "SIM_004"
    assert r4_selection["best_scenario_type"] == "HIGHER_FUNDAMENTAL_WEIGHT_SCENARIO"
    assert len({row["ticker"] for row in r3_selected}) == 297

    assert summary[0]["selected_simulation_scenario_id"] == r4_selection["best_scenario_id"]
    assert summary[0]["selected_scenario_type"] == r4_selection["best_scenario_type"]
    assert summary[0]["strict_equity_candidate_count"] == "297"
    assert summary[0]["evaluated_forward_window_count"] == "5"
    assert summary[0]["evaluated_topn_group_count"] == "4"
    assert summary[0]["evaluated_cell_count"] == "20"
    assert summary[0]["robustness_status"] in {
        "ROBUST_DIAGNOSTIC_CANDIDATE",
        "PARTIAL_ROBUSTNESS_LIMITED_COVERAGE",
        "MIXED_OR_UNSTABLE_CANDIDATE",
        "FAILED_ROBUSTNESS_VALIDATION",
    }

    assert len(window) == 20
    assert {int(row["top_n"]) for row in window} == {10, 20, 50, 100}
    assert {row["forward_window"] for row in window} == {"5D", "10D", "20D", "60D", "120D"}
    assert all(row["selected_simulation_scenario_id"] == "SIM_004" for row in window)
    assert all(row["coverage_status"] in {"FULL_FORWARD_OUTCOME_COVERAGE", "PARTIAL_FORWARD_OUTCOME_COVERAGE"} for row in window)

    assert len(bucket) == 25
    assert {row["rank_bucket"] for row in bucket} == {
        "BIG_PROMOTED_BY_SIMULATION",
        "MODERATE_PROMOTED_BY_SIMULATION",
        "UNCHANGED_OR_SMALL_CHANGE",
        "MODERATE_DEMOTED_BY_SIMULATION",
        "BIG_DEMOTED_BY_SIMULATION",
    }
    assert {row["forward_window"] for row in bucket} == {"5D", "10D", "20D", "60D", "120D"}
    assert len(attr) == 6

    assert selection[0]["selected_by_r4"] == "TRUE"
    assert selection[0]["scenario_weight_sum"] == "1.0000000000"
    assert selection[0]["scenario_weight_sum_valid"] == "TRUE"
    assert selection[0]["robustness_sufficient_for_acceptance_gate"] == "FALSE"
    assert gate[0]["robustness_validation_created"] == "TRUE"
    assert gate[0]["selected_simulation_scenario_id"] == "SIM_004"
    assert gate[0]["v20_110_acceptance_gate_allowed"] == "FALSE"

    for rows in [summary, window, bucket, attr, selection, gate]:
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
        if "diagnostic_only" in rows[0]:
            assert all(row["diagnostic_only"] == "TRUE" for row in rows)
        if "simulation_only" in rows[0]:
            assert all(row["simulation_only"] == "TRUE" for row in rows)


if __name__ == "__main__":
    test_candidate_scenario_robustness_validation()
    print("PASS_V20_109_R5_CANDIDATE_SCENARIO_ROBUSTNESS_VALIDATION_TESTS")
