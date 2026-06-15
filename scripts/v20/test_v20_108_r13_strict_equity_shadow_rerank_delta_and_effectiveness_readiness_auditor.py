#!/usr/bin/env python
"""Tests for V20.108-R13 shadow rerank delta/readiness auditor."""

from __future__ import annotations

import csv
import subprocess
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_108_r13_strict_equity_shadow_rerank_delta_and_effectiveness_readiness_auditor.py"
R12_RERANK = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R12_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK.csv"
R12_COMPONENT = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R12_SHADOW_SCORE_COMPONENT_CONTRIBUTION_AUDIT.csv"
R11_SCOPE = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R11_STRICT_EQUITY_SCOPE_AUDIT.csv"
OUT_SUMMARY = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R13_SHADOW_RERANK_DELTA_SUMMARY.csv"
OUT_ATTRIBUTION = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R13_FACTOR_FAMILY_RANK_CHANGE_ATTRIBUTION.csv"
OUT_MOVERS = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R13_TOP_MOVER_EXPLAINABILITY_AUDIT.csv"
OUT_OVERLAP = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R13_BASELINE_VS_SHADOW_OVERLAP_AUDIT.csv"
OUT_GATE = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R13_V20_109_EFFECTIVENESS_EVALUATION_READINESS_GATE.csv"
OUT_REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_108_R13_STRICT_EQUITY_SHADOW_RERANK_DELTA_AND_EFFECTIVENESS_READINESS_REPORT.md"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    assert rows
    bad = [row for row in rows if row.get(field) not in {"FALSE", ""}]
    assert not bad, f"{field} was not FALSE: {bad[:3]}"


def test_delta_readiness_auditor() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_108_R13_STRICT_EQUITY_SHADOW_RERANK_DELTA_AND_EFFECTIVENESS_READINESS_AUDITOR",
        "PARTIAL_PASS_V20_108_R13_EFFECTIVENESS_READINESS_WITH_LIMITED_HISTORICAL_COVERAGE",
        "BLOCKED_V20_108_R13_SHADOW_RERANK_INPUT_INVALID",
    ])
    for expected in [
        "INPUT_CANDIDATE_COUNT=297",
        "SOURCE_RANK_OR_SCORE_USED=FALSE",
        "BASELINE_RANK_USED_AS_FACTOR_CONTRIBUTION=FALSE",
        "FABRICATED_VALUES_CREATED=FALSE",
        "PROXY_VALUES_ACTIVATED=FALSE",
        "MIXED_UNIVERSE_RERANK_CREATED=FALSE",
        "OFFICIAL_RANKING_CREATED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "WEIGHT_MUTATED=FALSE",
        "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED=FALSE",
        "OFFICIAL_PROMOTION_ALLOWED=FALSE",
        "IS_OFFICIAL_WEIGHT=FALSE",
    ]:
        assert expected in stdout

    for path in [OUT_SUMMARY, OUT_ATTRIBUTION, OUT_MOVERS, OUT_OVERLAP, OUT_GATE, OUT_REPORT]:
        assert path.exists(), f"missing output {path}"

    rerank = read_csv(R12_RERANK)
    components = read_csv(R12_COMPONENT)
    scope = read_csv(R11_SCOPE)
    summary = read_csv(OUT_SUMMARY)
    attribution = read_csv(OUT_ATTRIBUTION)
    movers = read_csv(OUT_MOVERS)
    overlap = read_csv(OUT_OVERLAP)
    gate = read_csv(OUT_GATE)

    excluded = {row["ticker"] for row in scope if row["exclusion_reason"] == "FUNDAMENTAL_NOT_APPLICABLE_REQUIRES_APPLICABILITY_WEIGHT_POLICY"}
    assert len(rerank) == 297
    assert not ({row["ticker"] for row in rerank} & excluded)
    assert int(summary[0]["input_candidate_count"]) == 297

    deltas = [int(row["baseline_rank"]) - int(row["strict_equity_shadow_rank"]) for row in rerank]
    assert int(summary[0]["improved_count"]) == sum(1 for d in deltas if d > 0)
    assert int(summary[0]["unchanged_count"]) == sum(1 for d in deltas if d == 0)
    assert int(summary[0]["worsened_count"]) == sum(1 for d in deltas if d < 0)
    for row in rerank:
        expected_delta = int(row["baseline_rank"]) - int(row["strict_equity_shadow_rank"])
        assert int(row["shadow_rank_delta"]) == expected_delta

    assert {row["top_n"] for row in overlap} == {"10", "20", "50", "100"}
    for row in overlap:
        n = int(row["top_n"])
        baseline = {r["ticker"] for r in rerank if int(r["baseline_rank"]) <= n}
        shadow = {r["ticker"] for r in rerank if int(r["strict_equity_shadow_rank"]) <= n}
        assert int(row["overlap_count"]) == len(baseline & shadow)
        assert int(row["turnover_count"]) == len(shadow - baseline)

    comp_lookup = {}
    for row in components:
        comp_lookup.setdefault(row["ticker"], {})[row["factor_family"]] = row["weighted_component_contribution"]
    attr_by_ticker = {row["ticker"]: row for row in attribution}
    assert len(attribution) == 297
    for ticker, vals in list(comp_lookup.items())[:20]:
        attr = attr_by_ticker[ticker]
        assert attr["fundamental_weighted_component"] == vals["FUNDAMENTAL"]
        assert attr["technical_weighted_component"] == vals["TECHNICAL"]
        assert attr["strategy_weighted_component"] == vals["STRATEGY"]
        assert attr["risk_weighted_component"] == vals["RISK"]
        assert attr["market_regime_weighted_component"] == vals["MARKET_REGIME"]
        assert attr["data_trust_weighted_component"] == vals["DATA_TRUST"]
        max_family = max(vals, key=lambda fam: (Decimal(vals[fam]), fam))
        min_family = min(vals, key=lambda fam: (Decimal(vals[fam]), fam))
        assert attr["dominant_positive_factor_family"] == max_family
        assert attr["dominant_drag_factor_family"] == min_family

    assert len(movers) == 100
    assert {row["mover_bucket"] for row in movers} == {
        "TOP_IMPROVER",
        "TOP_WORSENER",
        "TOP_SHADOW_SCORE",
        "BIGGEST_BASELINE_SHADOW_DIVERGENCE",
    }
    assert all(row["diagnostic_only"] == "TRUE" for row in movers)
    assert all(row["recommendation_created"] == "FALSE" for row in movers)

    g = gate[0]
    assert g["strict_equity_shadow_rerank_candidate_count"] == "297"
    assert g["shadow_rank_unique"] == "TRUE"
    assert g["component_contribution_audit_available"] == "TRUE"
    assert g["baseline_comparison_available"] == "TRUE"
    assert g["performance_effectiveness_claim_created"] == "FALSE"
    assert g["official_ranking_created"] == "FALSE"
    assert g["official_recommendation_created"] == "FALSE"
    assert g["trade_action_created"] == "FALSE"
    assert g["broker_execution_supported"] == "FALSE"
    assert g["official_promotion_allowed"] == "FALSE"
    assert g["is_official_weight"] == "FALSE"
    assert g["weight_mutated"] == "FALSE"
    assert g["v20_109_readiness_status"] in {
        "READY_V20_109_EFFECTIVENESS_EVALUATION",
        "PARTIAL_READY_WITH_LIMITED_HISTORICAL_COVERAGE",
    }

    for rows in [summary, attribution, movers, overlap, gate]:
        if "mixed_universe_rerank_created" in rows[0]:
            assert_false(rows, "mixed_universe_rerank_created")
        if "official_ranking_created" in rows[0]:
            assert_false(rows, "official_ranking_created")
        if "official_recommendation_created" in rows[0]:
            assert_false(rows, "official_recommendation_created")
        if "trade_action_created" in rows[0]:
            assert_false(rows, "trade_action_created")
        if "broker_execution_supported" in rows[0]:
            assert_false(rows, "broker_execution_supported")
        if "weight_mutated" in rows[0]:
            assert_false(rows, "weight_mutated")


if __name__ == "__main__":
    test_delta_readiness_auditor()
    print("PASS_V20_108_R13_SHADOW_RERANK_DELTA_READINESS_AUDITOR_TESTS")
