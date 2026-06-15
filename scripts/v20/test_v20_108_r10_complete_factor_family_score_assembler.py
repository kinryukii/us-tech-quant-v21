#!/usr/bin/env python
"""Tests for V20.108-R10 complete factor family score assembler."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_108_r10_complete_factor_family_score_assembler.py"
OUT_TABLE = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv"
OUT_AUDIT = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R10_FACTOR_FAMILY_ASSEMBLY_AUDIT.csv"
OUT_VALIDATION = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R10_FACTOR_FAMILY_COMPLETENESS_VALIDATION.csv"
OUT_POLICY = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R10_APPLICABILITY_WEIGHT_POLICY_AUDIT.csv"
OUT_GATE = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R10_SHADOW_RERANK_READINESS_GATE.csv"
OUT_REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_ASSEMBLER_REPORT.md"

FAMILY_COLUMNS = [
    "fundamental_contribution",
    "technical_contribution",
    "strategy_contribution",
    "risk_contribution",
    "market_regime_contribution",
    "data_trust_contribution",
]


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


def test_complete_family_assembler() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    assert any(
        status in stdout
        for status in [
            "PASS_V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_ASSEMBLER_STRICT_EQUITY_READY",
            "PARTIAL_PASS_V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_ASSEMBLER_WITH_NON_EQUITY_APPLICABILITY_BLOCKER",
            "BLOCKED_V20_108_R10_NO_COMPLETE_FACTOR_FAMILY_CANDIDATES",
        ]
    )
    for expected in [
        "CANDIDATE_COUNT=315",
        "SOURCE_RANK_OR_SCORE_USED=FALSE",
        "BASELINE_RANK_USED_AS_FACTOR_CONTRIBUTION=FALSE",
        "FABRICATED_VALUES_CREATED=FALSE",
        "PROXY_VALUES_ACTIVATED=FALSE",
        "MISSING_FUNDAMENTAL_TREATED_AS_ZERO=FALSE",
        "WEIGHT_RENORMALIZATION_PERFORMED=FALSE",
        "SHADOW_RERANK_OUTPUT_CREATED=FALSE",
        "OFFICIAL_RANKING_CREATED=FALSE",
        "AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE",
        "WEIGHT_MUTATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
    ]:
        assert expected in stdout

    for path in [OUT_TABLE, OUT_AUDIT, OUT_VALIDATION, OUT_POLICY, OUT_GATE, OUT_REPORT]:
        assert path.exists(), f"missing output {path}"

    table = read_csv(OUT_TABLE)
    audit = read_csv(OUT_AUDIT)
    validation = read_csv(OUT_VALIDATION)
    policy = read_csv(OUT_POLICY)
    gate = read_csv(OUT_GATE)

    assert len(table) == 315
    assert len(audit) == 315 * 6
    for column in FAMILY_COLUMNS:
        assert column in table[0]

    recomputed_complete = sum(1 for row in table if all(row.get(column) for column in FAMILY_COLUMNS))
    assert recomputed_complete == 297
    assert validation[0]["complete_six_family_contribution_candidate_count"] == str(recomputed_complete)
    assert gate[0]["complete_six_family_contribution_candidate_count"] == str(recomputed_complete)

    non_equity = [row for row in table if row.get("non_applicable_factor_families") == "FUNDAMENTAL"]
    assert len(non_equity) == 18
    assert all(row.get("fundamental_contribution") == "" for row in non_equity)
    assert all(row.get("fundamental_contribution") != "0" for row in non_equity)
    assert all(row.get("complete_six_family_contribution") == "FALSE" for row in non_equity)
    assert all(row.get("applicable_family_contribution_complete") == "TRUE" for row in non_equity)
    assert all(row.get("applicability_weight_policy_required") == "TRUE" for row in non_equity)

    assert validation[0]["non_equity_fundamental_not_applicable_count"] == "18"
    assert validation[0]["fundamental_complete_count"] == "297"
    assert validation[0]["technical_complete_count"] == "315"
    assert validation[0]["strategy_complete_count"] == "315"
    assert validation[0]["risk_complete_count"] == "315"
    assert validation[0]["market_regime_complete_count"] == "315"
    assert validation[0]["data_trust_complete_count"] == "315"

    assert policy[0]["missing_fundamental_treated_as_zero"] == "FALSE"
    assert policy[0]["applicability_adjusted_weight_policy_exists"] == "FALSE"
    assert policy[0]["applicability_adjusted_weight_policy_approved"] == "FALSE"
    assert policy[0]["weight_renormalization_performed"] == "FALSE"
    assert policy[0]["official_weight_created"] == "FALSE"
    assert policy[0]["strict_six_family_equity_subset_allowed"] == "TRUE"
    assert policy[0]["mixed_universe_shadow_rerank_ready"] == "FALSE"

    assert gate[0]["strict_six_family_ready_for_shadow_rerank"] == "TRUE"
    assert gate[0]["mixed_universe_shadow_rerank_ready"] == "FALSE"
    assert gate[0]["partial_applicability_weight_policy_required"] == "TRUE"
    assert gate[0]["next_stage_allowed"] == "FALSE"

    for rows in [table, audit, validation, policy, gate]:
        if "source_rank_or_score_used" in rows[0]:
            assert_false(rows, "source_rank_or_score_used")
        if "baseline_rank_used_as_factor_contribution" in rows[0]:
            assert_false(rows, "baseline_rank_used_as_factor_contribution")
        if "fabricated_values_created" in rows[0]:
            assert_false(rows, "fabricated_values_created")
        if "proxy_values_activated" in rows[0]:
            assert_false(rows, "proxy_values_activated")
        if "shadow_rerank_output_created" in rows[0]:
            assert_false(rows, "shadow_rerank_output_created")
        if "official_ranking_created" in rows[0]:
            assert_false(rows, "official_ranking_created")
        if "authoritative_ranking_overwritten" in rows[0]:
            assert_false(rows, "authoritative_ranking_overwritten")
        assert_safety(rows)


if __name__ == "__main__":
    test_complete_family_assembler()
    print("PASS_V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_ASSEMBLER_TESTS")
