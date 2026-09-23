#!/usr/bin/env python
"""Tests for V20.109-R4 simulated weight effectiveness comparison."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_109_r4_simulated_weight_effectiveness_comparison.py"
R3_RERANK = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R3_SIMULATED_WEIGHT_STRICT_EQUITY_RERANK.csv"
R3_VALIDATION = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R3_SIMULATED_RERANK_VALIDATION.csv"
OUT_SUMMARY = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R4_SIMULATED_SCENARIO_EFFECTIVENESS_SUMMARY.csv"
OUT_MATRIX = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R4_FORWARD_WINDOW_TOPN_SCENARIO_COMPARISON_MATRIX.csv"
OUT_AUDIT = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R4_SCENARIO_VS_BASELINE_AND_CURRENT_SHADOW_AUDIT.csv"
OUT_ATTR = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R4_SIMULATED_SCENARIO_FACTOR_ATTRIBUTION.csv"
OUT_SELECTION = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R4_EVIDENCE_QUALITY_AND_SELECTION_AUDIT.csv"
OUT_GATE = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R4_NEXT_STAGE_GATE.csv"
OUT_REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_109_R4_SIMULATED_WEIGHT_EFFECTIVENESS_COMPARISON_REPORT.md"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    assert rows
    bad = [row for row in rows if row.get(field) not in {"FALSE", ""}]
    assert not bad, f"{field} was not FALSE: {bad[:3]}"


def test_simulated_weight_effectiveness_comparison() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_109_R4_SIMULATED_WEIGHT_EFFECTIVENESS_COMPARISON",
        "PARTIAL_PASS_V20_109_R4_SIMULATED_EFFECTIVENESS_COMPARISON_WITH_LIMITED_FORWARD_OUTCOME_COVERAGE",
        "WARN_V20_109_R4_NO_SIMULATED_SCENARIO_IMPROVES_CURRENT_SHADOW",
        "BLOCKED_V20_109_R4_MISSING_SIMULATED_RERANK_OR_FORWARD_OUTCOME_INPUTS",
    ])
    for expected in [
        "SCENARIO_COUNT=8",
        "STRICT_EQUITY_CANDIDATE_COUNT=297",
        "COMPARISON_CELL_COUNT=160",
        "FORWARD_WINDOWS=5D,10D,20D,60D,120D",
        "TOPN_GROUPS=10,20,50,100",
        "ACCEPTED_WEIGHT_CREATED=FALSE",
        "NEW_WEIGHTS_CREATED=FALSE",
        "NEW_RERANK_CREATED=FALSE",
        "V20_107_WEIGHT_MUTATED=FALSE",
        "V20_98B_R5_WEIGHT_MUTATED=FALSE",
        "OFFICIAL_WEIGHT_CREATED=FALSE",
        "OFFICIAL_RANKING_CREATED=FALSE",
        "AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED=FALSE",
        "V20_110_ACCEPTANCE_GATE_ALLOWED=FALSE",
        "OFFICIAL_PROMOTION_ALLOWED=FALSE",
        "IS_OFFICIAL_WEIGHT=FALSE",
    ]:
        assert expected in stdout

    for path in [OUT_SUMMARY, OUT_MATRIX, OUT_AUDIT, OUT_ATTR, OUT_SELECTION, OUT_GATE, OUT_REPORT]:
        assert path.exists(), f"missing output {path}"

    r3_validation = read_csv(R3_VALIDATION)[0]
    r3_rerank = read_csv(R3_RERANK)
    summary = read_csv(OUT_SUMMARY)
    matrix = read_csv(OUT_MATRIX)
    audit = read_csv(OUT_AUDIT)
    attr = read_csv(OUT_ATTR)
    selection = read_csv(OUT_SELECTION)
    gate = read_csv(OUT_GATE)

    scenario_count = int(r3_validation["scenario_count"])
    assert scenario_count == 8
    assert len({row["simulation_scenario_id"] for row in r3_rerank}) == scenario_count
    assert len({row["ticker"] for row in r3_rerank}) == 297
    assert len(summary) == scenario_count
    assert len(matrix) == scenario_count * 5 * 4
    assert len(audit) == scenario_count * 2
    assert len(attr) == scenario_count * 6

    assert {int(row["top_n"]) for row in matrix} == {10, 20, 50, 100}
    assert {row["forward_window"] for row in matrix} == {"5D", "10D", "20D", "60D", "120D"}
    assert {row["comparison_target"] for row in audit} == {"BASELINE_RANKING", "CURRENT_V20_107_SHADOW_RERANK"}
    assert all(row["scenario_top_n_count"] == row["top_n"] for row in matrix)
    assert all(0 < int(row["baseline_top_n_count"]) <= int(row["top_n"]) for row in matrix)
    assert all(row["current_shadow_top_n_count"] == row["top_n"] for row in matrix)
    assert all(row["available_forward_outcome_count"] != "" for row in matrix)
    assert all(row["coverage_status"] in {"FULL_FORWARD_OUTCOME_COVERAGE", "PARTIAL_FORWARD_OUTCOME_COVERAGE"} for row in matrix)

    assert selection[0]["scenario_count"] == "8"
    assert selection[0]["valid_scenario_count"] == "8"
    assert selection[0]["strict_equity_candidate_count"] == "297"
    assert selection[0]["forward_window_count"] == "5"
    assert selection[0]["topn_group_count"] == "4"
    assert selection[0]["accepted_weight_created"] == "FALSE"
    assert selection[0]["new_weights_created"] == "FALSE"
    assert selection[0]["new_rerank_created"] == "FALSE"
    assert selection[0]["performance_effectiveness_claim_created"] == "FALSE"

    assert gate[0]["simulated_effectiveness_comparison_created"] == "TRUE"
    assert gate[0]["scenario_count"] == "8"
    assert gate[0]["valid_scenario_count"] == "8"
    assert gate[0]["v20_110_acceptance_gate_allowed"] == "FALSE"
    if gate[0]["best_scenario_selected_for_next_validation"] == "TRUE":
        assert gate[0]["v20_109_r5_candidate_scenario_validation_allowed"] == "TRUE"

    for rows in [summary, matrix, audit, attr, selection, gate]:
        for field in [
            "accepted_weight_created",
            "new_weights_created",
            "new_rerank_created",
            "official_ranking_created",
            "official_recommendation_created",
            "trade_action_created",
            "broker_execution_supported",
            "performance_effectiveness_claim_created",
            "official_promotion_allowed",
            "is_official_weight",
            "weight_mutated",
            "official_weight_created",
            "active_weight_mutated",
            "v20_107_weight_mutated",
            "v20_98b_r5_weight_mutated",
            "authoritative_ranking_overwritten",
        ]:
            if field in rows[0]:
                assert_false(rows, field)
        if "diagnostic_only" in rows[0]:
            assert all(row["diagnostic_only"] == "TRUE" for row in rows)
        if "simulation_only" in rows[0]:
            assert all(row["simulation_only"] == "TRUE" for row in rows)


if __name__ == "__main__":
    test_simulated_weight_effectiveness_comparison()
    print("PASS_V20_109_R4_SIMULATED_WEIGHT_EFFECTIVENESS_COMPARISON_TESTS")
