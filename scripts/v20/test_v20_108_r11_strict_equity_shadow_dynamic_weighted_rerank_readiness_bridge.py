#!/usr/bin/env python
"""Tests for V20.108-R11 strict equity rerank readiness bridge."""

from __future__ import annotations

import csv
import subprocess
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_108_r11_strict_equity_shadow_dynamic_weighted_rerank_readiness_bridge.py"
R10_TABLE = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv"
OUT_MATRIX = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R11_STRICT_EQUITY_SHADOW_RERANK_INPUT_MATRIX.csv"
OUT_WEIGHT_AUDIT = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R11_DYNAMIC_WEIGHT_BINDING_AUDIT.csv"
OUT_SCOPE_AUDIT = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R11_STRICT_EQUITY_SCOPE_AUDIT.csv"
OUT_VALIDATION = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R11_SHADOW_RERANK_READINESS_VALIDATION.csv"
OUT_GATE = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R11_NEXT_STAGE_GATE.csv"
OUT_REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_108_R11_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK_READINESS_BRIDGE_REPORT.md"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


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


def test_readiness_bridge() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    assert any(
        status in stdout
        for status in [
            "PASS_V20_108_R11_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK_READINESS_BRIDGE",
            "BLOCKED_V20_108_R11_STRICT_EQUITY_SHADOW_RERANK_INPUT_NOT_READY",
            "PARTIAL_PASS_V20_108_R11_STRICT_EQUITY_READY_MIXED_UNIVERSE_BLOCKED",
        ]
    )
    for expected in [
        "CANDIDATE_COUNT=315",
        "STRICT_EQUITY_INPUT_CANDIDATE_COUNT=297",
        "EXCLUDED_NON_EQUITY_OR_FUND_CANDIDATE_COUNT=18",
        "DYNAMIC_WEIGHT_SUM=1.0000000000",
        "DYNAMIC_WEIGHT_SUM_VALID=TRUE",
        "STRICT_EQUITY_SHADOW_RERANK_INPUT_READY=TRUE",
        "MIXED_UNIVERSE_SHADOW_RERANK_READY=FALSE",
        "ACTIVE_RESEARCH_BASE_WEIGHTS_MUTATED=FALSE",
        "V20_107_SHADOW_DYNAMIC_WEIGHTS_MUTATED=FALSE",
        "FINAL_WEIGHTED_SCORE_CREATED=FALSE",
        "SHADOW_RERANK_OUTPUT_CREATED=FALSE",
        "OFFICIAL_RANKING_CREATED=FALSE",
        "AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE",
        "SOURCE_RANK_OR_SCORE_USED=FALSE",
        "BASELINE_RANK_USED_AS_FACTOR_CONTRIBUTION=FALSE",
        "FABRICATED_VALUES_CREATED=FALSE",
        "PROXY_VALUES_ACTIVATED=FALSE",
        "WEIGHT_MUTATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
    ]:
        assert expected in stdout

    for path in [OUT_MATRIX, OUT_WEIGHT_AUDIT, OUT_SCOPE_AUDIT, OUT_VALIDATION, OUT_GATE, OUT_REPORT]:
        assert path.exists(), f"missing output {path}"

    r10 = read_csv(R10_TABLE)
    matrix = read_csv(OUT_MATRIX)
    weight_audit = read_csv(OUT_WEIGHT_AUDIT)
    scope = read_csv(OUT_SCOPE_AUDIT)
    validation = read_csv(OUT_VALIDATION)
    gate = read_csv(OUT_GATE)

    strict_tickers = {
        row["ticker"]
        for row in r10
        if row["eligible_for_strict_six_family_shadow_rerank"] == "TRUE"
        and row["complete_six_family_contribution"] == "TRUE"
        and row["applicability_weight_policy_required"] == "FALSE"
    }
    excluded_tickers = {row["ticker"] for row in r10 if row["applicability_weight_policy_required"] == "TRUE"}

    assert len(scope) == 315
    assert len(matrix) == len(strict_tickers) == 297
    assert {row["ticker"] for row in matrix} == strict_tickers
    assert not ({row["ticker"] for row in matrix} & excluded_tickers)

    excluded_scope = [row for row in scope if row["ticker"] in excluded_tickers]
    assert len(excluded_scope) == 18
    assert all(row["included_in_strict_equity_scope"] == "FALSE" for row in excluded_scope)
    assert all(row["exclusion_reason"] == "FUNDAMENTAL_NOT_APPLICABLE_REQUIRES_APPLICABILITY_WEIGHT_POLICY" for row in excluded_scope)

    assert all(row["all_six_family_contributions_present"] == "TRUE" for row in matrix)
    assert all(row["all_six_family_weights_present"] == "TRUE" for row in matrix)
    assert all(row["included_in_strict_equity_shadow_rerank_input"] == "TRUE" for row in matrix)
    assert all(row["preview_only"] == "FALSE" for row in matrix)
    assert "weighted_score" not in matrix[0]
    assert "rank" not in {key.lower() for key in matrix[0]}

    weights = [Decimal(row["shadow_dynamic_weight"]) for row in weight_audit]
    assert len(weight_audit) == 6
    assert sum(weights) == Decimal("1.0000000000")
    assert all(row["binding_status"] == "BOUND" for row in weight_audit)
    assert all(row["active_weight_mutated"] == "FALSE" for row in weight_audit)
    assert all(row["official_weight_created"] == "FALSE" for row in weight_audit)

    v = validation[0]
    assert v["strict_equity_input_candidate_count"] == "297"
    assert v["excluded_non_equity_or_fund_candidate_count"] == "18"
    assert v["six_family_contribution_complete_count"] == "297"
    assert v["six_family_weight_binding_complete"] == "TRUE"
    assert v["dynamic_weight_sum"] == "1.0000000000"
    assert v["strict_equity_shadow_rerank_input_ready"] == "TRUE"
    assert v["mixed_universe_shadow_rerank_ready"] == "FALSE"
    assert v["final_weighted_score_created"] == "FALSE"
    assert v["shadow_rerank_output_created"] == "FALSE"
    assert v["official_ranking_created"] == "FALSE"
    assert v["authoritative_ranking_overwritten"] == "FALSE"

    assert gate[0]["strict_equity_shadow_rerank_input_ready"] == "TRUE"
    assert gate[0]["mixed_universe_shadow_rerank_ready"] == "FALSE"
    assert gate[0]["strict_equity_input_candidate_count"] == "297"
    assert gate[0]["excluded_non_equity_or_fund_candidate_count"] == "18"

    for rows in [matrix, weight_audit, scope, validation, gate]:
        if "source_rank_or_score_used" in rows[0]:
            assert_false(rows, "source_rank_or_score_used")
        if "baseline_rank_used_as_factor_contribution" in rows[0]:
            assert_false(rows, "baseline_rank_used_as_factor_contribution")
        if "fabricated_values_created" in rows[0]:
            assert_false(rows, "fabricated_values_created")
        if "proxy_values_activated" in rows[0]:
            assert_false(rows, "proxy_values_activated")
        if "final_weighted_score_created" in rows[0]:
            assert_false(rows, "final_weighted_score_created")
        if "shadow_rerank_output_created" in rows[0]:
            assert_false(rows, "shadow_rerank_output_created")
        if "official_ranking_created" in rows[0]:
            assert_false(rows, "official_ranking_created")
        if "authoritative_ranking_overwritten" in rows[0]:
            assert_false(rows, "authoritative_ranking_overwritten")
        assert_safety(rows)


if __name__ == "__main__":
    test_readiness_bridge()
    print("PASS_V20_108_R11_STRICT_EQUITY_SHADOW_RERANK_READINESS_BRIDGE_TESTS")
