#!/usr/bin/env python
"""Tests for V20.108-R12 strict equity shadow rerank simulator."""

from __future__ import annotations

import csv
import subprocess
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_108_r12_strict_equity_shadow_dynamic_weighted_rerank_simulator.py"
R11_MATRIX = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R11_STRICT_EQUITY_SHADOW_RERANK_INPUT_MATRIX.csv"
R11_SCOPE = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R11_STRICT_EQUITY_SCOPE_AUDIT.csv"
OUT_RERANK = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R12_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK.csv"
OUT_DELTA = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R12_STRICT_EQUITY_SHADOW_RANK_DELTA_AUDIT.csv"
OUT_COMPONENT = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R12_SHADOW_SCORE_COMPONENT_CONTRIBUTION_AUDIT.csv"
OUT_VALIDATION = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R12_SHADOW_RERANK_VALIDATION.csv"
OUT_GATE = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R12_NEXT_STAGE_GATE.csv"
OUT_REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_108_R12_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK_REPORT.md"

FAMILIES = [
    ("fundamental_contribution", "fundamental_weight"),
    ("technical_contribution", "technical_weight"),
    ("strategy_contribution", "strategy_weight"),
    ("risk_contribution", "risk_weight"),
    ("market_regime_contribution", "market_regime_weight"),
    ("data_trust_contribution", "data_trust_weight"),
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


def assert_safety(rows: list[dict[str, str]]) -> None:
    for field in [
        "official_promotion_allowed",
        "official_recommendation_created",
        "is_official_weight",
        "weight_mutated",
        "trade_action_created",
        "broker_execution_supported",
    ]:
        if field in rows[0]:
            assert_false(rows, field)


def weighted_score(row: dict[str, str]) -> Decimal:
    return sum(Decimal(row[c]) * Decimal(row[w]) for c, w in FAMILIES)


def test_strict_equity_shadow_rerank() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    assert "PASS_V20_108_R12_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK_SIMULATOR" in stdout
    for expected in [
        "INPUT_CANDIDATE_COUNT=297",
        "OUTPUT_CANDIDATE_COUNT=297",
        "EXCLUDED_NON_EQUITY_OR_FUND_CANDIDATE_COUNT=18",
        "DYNAMIC_WEIGHT_SUM=1.0000000000",
        "DYNAMIC_WEIGHT_SUM_VALID=TRUE",
        "ALL_CANDIDATES_SCORED=TRUE",
        "DUPLICATE_SHADOW_RANK_COUNT=0",
        "SOURCE_RANK_OR_SCORE_USED=FALSE",
        "BASELINE_RANK_USED_AS_FACTOR_CONTRIBUTION=FALSE",
        "FABRICATED_VALUES_CREATED=FALSE",
        "PROXY_VALUES_ACTIVATED=FALSE",
        "SHADOW_DYNAMIC_WEIGHTED_SCORE_CREATED=TRUE",
        "STRICT_EQUITY_SHADOW_RERANK_OUTPUT_CREATED=TRUE",
        "MIXED_UNIVERSE_SHADOW_RERANK_OUTPUT_CREATED=FALSE",
        "OFFICIAL_RANKING_CREATED=FALSE",
        "AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "WEIGHT_MUTATED=FALSE",
        "OFFICIAL_PROMOTION_ALLOWED=FALSE",
        "IS_OFFICIAL_WEIGHT=FALSE",
    ]:
        assert expected in stdout

    for path in [OUT_RERANK, OUT_DELTA, OUT_COMPONENT, OUT_VALIDATION, OUT_GATE, OUT_REPORT]:
        assert path.exists(), f"missing output {path}"

    matrix = read_csv(R11_MATRIX)
    scope = read_csv(R11_SCOPE)
    rerank = read_csv(OUT_RERANK)
    delta = read_csv(OUT_DELTA)
    component = read_csv(OUT_COMPONENT)
    validation = read_csv(OUT_VALIDATION)
    gate = read_csv(OUT_GATE)

    strict_tickers = {row["ticker"] for row in matrix}
    excluded = {row["ticker"] for row in scope if row["exclusion_reason"] == "FUNDAMENTAL_NOT_APPLICABLE_REQUIRES_APPLICABILITY_WEIGHT_POLICY"}
    assert len(matrix) == 297
    assert len(rerank) == 297
    assert {row["ticker"] for row in rerank} == strict_tickers
    assert not ({row["ticker"] for row in rerank} & excluded)
    assert len(excluded) == 18
    assert len(delta) == 297
    assert len(component) == 297 * 6

    ranks = [int(row["strict_equity_shadow_rank"]) for row in rerank]
    assert sorted(ranks) == list(range(1, 298))

    by_ticker = {row["ticker"]: row for row in rerank}
    matrix_by_ticker = {row["ticker"]: row for row in matrix}
    for ticker, row in by_ticker.items():
        expected_score = q(weighted_score(matrix_by_ticker[ticker]))
        assert row["shadow_dynamic_weighted_score"] == expected_score
        assert row["baseline_rank"] == matrix_by_ticker[ticker]["baseline_rank"]
        assert row["all_six_family_contributions_present"] == "TRUE"
        assert row["all_six_family_weights_present"] == "TRUE"
        delta_value = int(row["baseline_rank"]) - int(row["strict_equity_shadow_rank"])
        assert row["shadow_rank_delta"] == str(delta_value)
        if delta_value > 0:
            assert row["shadow_rank_delta_direction"] == "IMPROVED"
        elif delta_value < 0:
            assert row["shadow_rank_delta_direction"] == "WORSENED"
        else:
            assert row["shadow_rank_delta_direction"] == "UNCHANGED"

    expected_order = sorted(
        matrix,
        key=lambda row: (
            -weighted_score(row),
            -Decimal(row["risk_contribution"]),
            -Decimal(row["data_trust_contribution"]),
            Decimal(row["baseline_rank"]),
            row["ticker"],
        ),
    )
    assert [row["ticker"] for row in rerank] == [row["ticker"] for row in expected_order]

    weight_sum = sum(Decimal(matrix[0][weight]) for _, weight in FAMILIES)
    assert weight_sum == Decimal("1.0000000000")
    assert all(row["component_used_in_score"] == "TRUE" for row in component)
    assert all(row["source_rank_or_score_used"] == "FALSE" for row in component)
    assert all(row["baseline_rank_used_as_factor_contribution"] == "FALSE" for row in component)

    v = validation[0]
    assert v["input_candidate_count"] == "297"
    assert v["output_candidate_count"] == "297"
    assert v["excluded_non_equity_or_fund_candidate_count"] == "18"
    assert v["dynamic_weight_sum"] == "1.0000000000"
    assert v["dynamic_weight_sum_valid"] == "TRUE"
    assert v["all_candidates_scored"] == "TRUE"
    assert v["duplicate_shadow_rank_count"] == "0"
    assert v["missing_shadow_rank_count"] == "0"
    assert v["strict_equity_shadow_rerank_output_created"] == "TRUE"
    assert v["mixed_universe_shadow_rerank_output_created"] == "FALSE"
    assert v["official_ranking_created"] == "FALSE"
    assert v["authoritative_ranking_overwritten"] == "FALSE"

    assert gate[0]["strict_equity_shadow_rerank_created"] == "TRUE"
    assert gate[0]["strict_equity_shadow_rerank_candidate_count"] == "297"
    assert gate[0]["mixed_universe_shadow_rerank_created"] == "FALSE"

    for rows in [rerank, delta, component, validation, gate]:
        if "fabricated_values_created" in rows[0]:
            assert_false(rows, "fabricated_values_created")
        if "proxy_values_activated" in rows[0]:
            assert_false(rows, "proxy_values_activated")
        if "mixed_universe_shadow_rerank_output_created" in rows[0]:
            assert_false(rows, "mixed_universe_shadow_rerank_output_created")
        if "official_ranking_created" in rows[0]:
            assert_false(rows, "official_ranking_created")
        if "authoritative_ranking_overwritten" in rows[0]:
            assert_false(rows, "authoritative_ranking_overwritten")
        assert_safety(rows)


if __name__ == "__main__":
    test_strict_equity_shadow_rerank()
    print("PASS_V20_108_R12_STRICT_EQUITY_SHADOW_RERANK_SIMULATOR_TESTS")
