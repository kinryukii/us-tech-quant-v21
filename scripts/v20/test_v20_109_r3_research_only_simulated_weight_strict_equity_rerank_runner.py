#!/usr/bin/env python
"""Tests for V20.109-R3 simulated strict equity rerank runner."""

from __future__ import annotations

import csv
import subprocess
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_109_r3_research_only_simulated_weight_strict_equity_rerank_runner.py"
R2_SCENARIOS = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R2_SHADOW_WEIGHT_REPAIR_SIMULATION_SCENARIOS.csv"
R11_MATRIX = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R11_STRICT_EQUITY_SHADOW_RERANK_INPUT_MATRIX.csv"
R11_SCOPE = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R11_STRICT_EQUITY_SCOPE_AUDIT.csv"
OUT_RERANK = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R3_SIMULATED_WEIGHT_STRICT_EQUITY_RERANK.csv"
OUT_DELTA = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R3_SIMULATED_RANK_DELTA_AUDIT.csv"
OUT_COMPONENT = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R3_SIMULATED_SCORE_COMPONENT_AUDIT.csv"
OUT_VALIDATION = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R3_SIMULATED_RERANK_VALIDATION.csv"
OUT_GATE = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_R3_NEXT_STAGE_GATE.csv"
OUT_REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_109_R3_RESEARCH_ONLY_SIMULATED_WEIGHT_STRICT_EQUITY_RERANK_REPORT.md"

PAIRS = [
    ("fundamental_contribution", "simulated_fundamental_weight"),
    ("technical_contribution", "simulated_technical_weight"),
    ("strategy_contribution", "simulated_strategy_weight"),
    ("risk_contribution", "simulated_risk_weight"),
    ("market_regime_contribution", "simulated_market_regime_weight"),
    ("data_trust_contribution", "simulated_data_trust_weight"),
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def q(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP))


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    assert rows
    bad = [row for row in rows if row.get(field) not in {"FALSE", ""}]
    assert not bad, f"{field} was not FALSE: {bad[:3]}"


def test_simulated_rerank_runner() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    assert any(s in stdout for s in [
        "PASS_V20_109_R3_RESEARCH_ONLY_SIMULATED_WEIGHT_STRICT_EQUITY_RERANK_RUNNER",
        "PARTIAL_PASS_V20_109_R3_SIMULATED_RERANK_WITH_LIMITED_EVIDENCE",
        "BLOCKED_V20_109_R3_MISSING_SIMULATION_SCENARIOS_OR_INPUT_MATRIX",
    ])
    for expected in [
        "SCENARIO_COUNT=8",
        "STRICT_EQUITY_CANDIDATE_COUNT=297",
        "ACTUAL_RERANK_ROW_COUNT=2376",
        "EXPECTED_RERANK_ROW_COUNT=2376",
        "ALL_SCENARIO_WEIGHT_SUMS_VALID=TRUE",
        "NEW_WEIGHTS_CREATED=FALSE",
        "OFFICIAL_WEIGHT_CREATED=FALSE",
        "ACTIVE_WEIGHT_MUTATED=FALSE",
        "V20_107_WEIGHT_MUTATED=FALSE",
        "V20_98B_R5_WEIGHT_MUTATED=FALSE",
        "OFFICIAL_RANKING_CREATED=FALSE",
        "AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED=FALSE",
        "V20_110_ACCEPTANCE_GATE_ALLOWED=FALSE",
        "V20_109_R4_EFFECTIVENESS_COMPARISON_ALLOWED=TRUE",
        "OFFICIAL_PROMOTION_ALLOWED=FALSE",
        "IS_OFFICIAL_WEIGHT=FALSE",
    ]:
        assert expected in stdout

    for path in [OUT_RERANK, OUT_DELTA, OUT_COMPONENT, OUT_VALIDATION, OUT_GATE, OUT_REPORT]:
        assert path.exists(), f"missing output {path}"

    scenarios = [row for row in read_csv(R2_SCENARIOS) if row["weight_sum_valid"] == "TRUE"]
    matrix = read_csv(R11_MATRIX)
    scope = read_csv(R11_SCOPE)
    rerank = read_csv(OUT_RERANK)
    delta = read_csv(OUT_DELTA)
    component = read_csv(OUT_COMPONENT)
    validation = read_csv(OUT_VALIDATION)
    gate = read_csv(OUT_GATE)
    excluded = {row["ticker"] for row in scope if row["exclusion_reason"] == "FUNDAMENTAL_NOT_APPLICABLE_REQUIRES_APPLICABILITY_WEIGHT_POLICY"}

    assert len(scenarios) == 8
    assert len(matrix) == 297
    assert len(rerank) == 8 * 297
    assert len(delta) == len(rerank)
    assert len(component) == len(rerank) * 6
    assert not ({row["ticker"] for row in rerank} & excluded)

    for scenario in scenarios:
        sid = scenario["simulation_scenario_id"]
        rows = [row for row in rerank if row["simulation_scenario_id"] == sid]
        assert len(rows) == 297
        ranks = sorted(int(row["simulated_shadow_rank"]) for row in rows)
        assert ranks == list(range(1, 298))
        for row in rows[:10]:
            total = sum(Decimal(row[c]) * Decimal(row[w]) for c, w in PAIRS)
            assert row["simulated_shadow_weighted_score"] == q(total)
            assert row["simulated_weight_sum"] == "1.0000000000"
            assert row["simulation_only"] == "TRUE"
            assert row["official_weight_created"] == "FALSE"
            assert row["active_weight_mutated"] == "FALSE"
            assert row["v20_107_weight_mutated"] == "FALSE"
            assert row["v20_98b_r5_weight_mutated"] == "FALSE"

    v = validation[0]
    assert v["scenario_count"] == "8"
    assert v["valid_scenario_count"] == "8"
    assert v["strict_equity_candidate_count"] == "297"
    assert v["expected_rerank_row_count"] == "2376"
    assert v["actual_rerank_row_count"] == "2376"
    assert v["duplicate_rank_count"] == "0"
    assert v["missing_rank_count"] == "0"
    assert v["simulated_rerank_created"] == "TRUE"
    assert v["new_weights_created"] == "FALSE"
    assert v["official_weight_created"] == "FALSE"
    assert v["authoritative_ranking_overwritten"] == "FALSE"
    assert v["performance_effectiveness_claim_created"] == "FALSE"

    assert gate[0]["simulated_rerank_created"] == "TRUE"
    assert gate[0]["v20_109_r4_effectiveness_comparison_allowed"] == "TRUE"
    assert gate[0]["v20_110_acceptance_gate_allowed"] == "FALSE"

    for rows in [rerank, delta, component, validation, gate]:
        for field in [
            "official_recommendation_created",
            "trade_action_created",
            "broker_execution_supported",
            "official_promotion_allowed",
            "official_weight_created",
            "active_weight_mutated",
            "v20_107_weight_mutated",
            "v20_98b_r5_weight_mutated",
            "new_weights_created",
            "performance_effectiveness_claim_created",
            "authoritative_ranking_overwritten",
        ]:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_simulated_rerank_runner()
    print("PASS_V20_109_R3_SIMULATED_WEIGHT_RERANK_RUNNER_TESTS")
