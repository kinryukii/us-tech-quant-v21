#!/usr/bin/env python
"""Tests for V20.109 strict equity shadow effectiveness evaluator."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_109_strict_equity_shadow_weighted_backtest_effectiveness_evaluator.py"
R12_RERANK = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R12_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK.csv"
R11_SCOPE = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R11_STRICT_EQUITY_SCOPE_AUDIT.csv"
OUT_SUMMARY = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_STRICT_EQUITY_SHADOW_VS_BASELINE_EFFECTIVENESS_SUMMARY.csv"
OUT_MATRIX = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_FORWARD_WINDOW_TOPN_EFFECTIVENESS_MATRIX.csv"
OUT_ATTR = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_SHADOW_RERANK_FACTOR_EFFECTIVENESS_ATTRIBUTION.csv"
OUT_QUALITY = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_EFFECTIVENESS_EVIDENCE_QUALITY_AUDIT.csv"
OUT_GATE = ROOT / "outputs" / "v20" / "consolidation" / "V20_109_NEXT_STAGE_GATE.csv"
OUT_REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_109_STRICT_EQUITY_SHADOW_WEIGHTED_BACKTEST_EFFECTIVENESS_REPORT.md"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    assert rows
    bad = [row for row in rows if row.get(field) not in {"FALSE", ""}]
    assert not bad, f"{field} was not FALSE: {bad[:3]}"


def test_effectiveness_evaluator() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    assert any(s in stdout for s in [
        "PASS_V20_109_STRICT_EQUITY_SHADOW_WEIGHTED_BACKTEST_EFFECTIVENESS_EVALUATOR",
        "PARTIAL_PASS_V20_109_EFFECTIVENESS_EVALUATOR_WITH_LIMITED_FORWARD_OUTCOME_COVERAGE",
        "WARN_V20_109_MIXED_OR_INCONCLUSIVE_SHADOW_EFFECTIVENESS_EVIDENCE",
        "BLOCKED_V20_109_MISSING_REQUIRED_EFFECTIVENESS_INPUTS",
    ])
    for expected in [
        "STRICT_EQUITY_CANDIDATE_COUNT=297",
        "EXCLUDED_NON_EQUITY_OR_FUND_CANDIDATE_COUNT=18",
        "EVALUATED_FORWARD_WINDOW_COUNT=5",
        "EVALUATED_TOPN_GROUP_COUNT=4",
        "OFFICIAL_RANKING_CREATED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "IS_OFFICIAL_WEIGHT=FALSE",
        "WEIGHT_MUTATED=FALSE",
        "AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE",
    ]:
        assert expected in stdout

    for path in [OUT_SUMMARY, OUT_MATRIX, OUT_ATTR, OUT_QUALITY, OUT_GATE, OUT_REPORT]:
        assert path.exists(), f"missing output {path}"

    rerank = read_csv(R12_RERANK)
    scope = read_csv(R11_SCOPE)
    summary = read_csv(OUT_SUMMARY)
    matrix = read_csv(OUT_MATRIX)
    attr = read_csv(OUT_ATTR)
    quality = read_csv(OUT_QUALITY)
    gate = read_csv(OUT_GATE)
    excluded = {row["ticker"] for row in scope if row["exclusion_reason"] == "FUNDAMENTAL_NOT_APPLICABLE_REQUIRES_APPLICABILITY_WEIGHT_POLICY"}
    strict = {row["ticker"] for row in rerank}

    assert len(rerank) == 297
    assert len(excluded) == 18
    assert not (strict & excluded)
    assert summary[0]["strict_equity_candidate_count"] == "297"
    assert summary[0]["excluded_non_equity_or_fund_candidate_count"] == "18"
    assert summary[0]["evaluated_forward_window_count"] == "5"
    assert summary[0]["evaluated_topn_group_count"] == "4"

    assert len(matrix) == 20
    assert {row["top_n"] for row in matrix} == {"10", "20", "50", "100"}
    assert {row["forward_window"] for row in matrix} == {"5D", "10D", "20D", "60D", "120D"}
    for row in matrix:
        n = int(row["top_n"])
        baseline = {r["ticker"] for r in rerank if int(r["baseline_rank"]) <= n}
        shadow = {r["ticker"] for r in rerank if int(r["strict_equity_shadow_rank"]) <= n}
        assert int(row["baseline_top_n_count"]) == len(baseline)
        assert int(row["shadow_top_n_count"]) == len(shadow)
        assert int(row["overlap_count"]) == len(baseline & shadow)
        assert int(row["turnover_count"]) == len(shadow - baseline)

    assert len(attr) == 297 * 5
    assert {row["ticker"] for row in attr} == strict
    assert not ({row["ticker"] for row in attr} & excluded)
    assert all(row["diagnostic_only"] == "TRUE" for row in attr)
    assert all(row["official_recommendation_created"] == "FALSE" for row in attr)

    q = quality[0]
    assert q["strict_equity_candidate_count"] == "297"
    assert q["v20_104_forward_outcome_available"] == "TRUE"
    assert q["v20_105_factor_ablation_available"] == "TRUE"
    assert q["v20_106_regime_alignment_available"] == "TRUE"
    assert q["official_promotion_allowed"] == "FALSE"
    assert q["is_official_weight"] == "FALSE"
    assert q["weight_mutated"] == "FALSE"

    g = gate[0]
    assert g["effectiveness_evaluation_candidate_count"] == "297"
    assert g["official_ranking_created"] == "FALSE"
    assert g["official_recommendation_created"] == "FALSE"
    assert g["trade_action_created"] == "FALSE"
    assert g["broker_execution_supported"] == "FALSE"
    assert g["official_promotion_allowed"] == "FALSE"
    assert g["is_official_weight"] == "FALSE"
    assert g["weight_mutated"] == "FALSE"
    if g["performance_effectiveness_claim_created"] == "TRUE":
        assert g["shadow_outperformance_supported"] == "TRUE"
        assert summary[0]["effectiveness_result_status"] == "SHADOW_OUTPERFORMANCE_SUPPORTED_RESEARCH_ONLY"

    for rows in [summary, matrix, attr, quality, gate]:
        for field in [
            "official_recommendation_created",
            "trade_action_created",
            "broker_execution_supported",
            "weight_mutated",
        ]:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_effectiveness_evaluator()
    print("PASS_V20_109_STRICT_EQUITY_SHADOW_EFFECTIVENESS_EVALUATOR_TESTS")
