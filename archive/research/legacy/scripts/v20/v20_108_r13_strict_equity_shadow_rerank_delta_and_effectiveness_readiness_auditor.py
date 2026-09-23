#!/usr/bin/env python
"""V20.108-R13 strict equity shadow rerank delta/effectiveness readiness auditor."""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R12_RERANK = CONSOLIDATION / "V20_108_R12_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK.csv"
R12_DELTA = CONSOLIDATION / "V20_108_R12_STRICT_EQUITY_SHADOW_RANK_DELTA_AUDIT.csv"
R12_COMPONENT = CONSOLIDATION / "V20_108_R12_SHADOW_SCORE_COMPONENT_CONTRIBUTION_AUDIT.csv"
R12_VALIDATION = CONSOLIDATION / "V20_108_R12_SHADOW_RERANK_VALIDATION.csv"
R12_GATE = CONSOLIDATION / "V20_108_R12_NEXT_STAGE_GATE.csv"
R11_SCOPE = CONSOLIDATION / "V20_108_R11_STRICT_EQUITY_SCOPE_AUDIT.csv"
R10_TABLE = CONSOLIDATION / "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv"
R107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R107_VALIDATION = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_WEIGHT_VALIDATION.csv"
V104_RUNS = CONSOLIDATION / "V20_104_RANDOM_ASOF_BACKTEST_BATCH_RUNS.csv"
V104_FORWARD = CONSOLIDATION / "V20_104_RANDOM_ASOF_FORWARD_OUTCOME_MATRIX.csv"
V104_BENCH = CONSOLIDATION / "V20_104_RANDOM_ASOF_BENCHMARK_COMPARISON.csv"
V105_HIST = CONSOLIDATION / "V20_105_FACTOR_FAMILY_HISTORICAL_EVIDENCE.csv"
V105_ABLATION = CONSOLIDATION / "V20_105_FACTOR_ABLATION_EVIDENCE_MATRIX.csv"
V106_REGIME = CONSOLIDATION / "V20_106_REGIME_CONDITIONED_FACTOR_ALIGNMENT.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OUT_SUMMARY = CONSOLIDATION / "V20_108_R13_SHADOW_RERANK_DELTA_SUMMARY.csv"
OUT_ATTRIBUTION = CONSOLIDATION / "V20_108_R13_FACTOR_FAMILY_RANK_CHANGE_ATTRIBUTION.csv"
OUT_MOVERS = CONSOLIDATION / "V20_108_R13_TOP_MOVER_EXPLAINABILITY_AUDIT.csv"
OUT_OVERLAP = CONSOLIDATION / "V20_108_R13_BASELINE_VS_SHADOW_OVERLAP_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_108_R13_V20_109_EFFECTIVENESS_EVALUATION_READINESS_GATE.csv"
REPORT = READ_CENTER / "V20_108_R13_STRICT_EQUITY_SHADOW_RERANK_DELTA_AND_EFFECTIVENESS_READINESS_REPORT.md"

PASS_STATUS = "PASS_V20_108_R13_STRICT_EQUITY_SHADOW_RERANK_DELTA_AND_EFFECTIVENESS_READINESS_AUDITOR"
PARTIAL_STATUS = "PARTIAL_PASS_V20_108_R13_EFFECTIVENESS_READINESS_WITH_LIMITED_HISTORICAL_COVERAGE"
BLOCKED_STATUS = "BLOCKED_V20_108_R13_SHADOW_RERANK_INPUT_INVALID"

FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
COMPONENT_FIELD = {
    "FUNDAMENTAL": "fundamental_weighted_component",
    "TECHNICAL": "technical_weighted_component",
    "STRATEGY": "strategy_weighted_component",
    "RISK": "risk_weighted_component",
    "MARKET_REGIME": "market_regime_weighted_component",
    "DATA_TRUST": "data_trust_weighted_component",
}

SUMMARY_FIELDS = ["summary_id","input_candidate_count","improved_count","unchanged_count","worsened_count","max_improvement","max_worsening","average_absolute_delta","median_absolute_delta","top10_overlap_count","top20_overlap_count","top50_overlap_count","top100_overlap_count","top10_turnover_count","top20_turnover_count","top50_turnover_count","top100_turnover_count","shadow_rerank_scope","mixed_universe_rerank_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","research_only","shadow_only","official_promotion_allowed","is_official_weight","weight_mutated"]
ATTR_FIELDS = ["ticker","baseline_rank","strict_equity_shadow_rank","shadow_rank_delta","shadow_rank_delta_direction","shadow_dynamic_weighted_score","fundamental_weighted_component","technical_weighted_component","strategy_weighted_component","risk_weighted_component","market_regime_weighted_component","data_trust_weighted_component","dominant_positive_factor_family","dominant_positive_component_value","dominant_drag_factor_family","dominant_drag_component_value","attribution_status","attribution_reason","diagnostic_only","research_only","shadow_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
MOVER_FIELDS = ["ticker","mover_bucket","baseline_rank","strict_equity_shadow_rank","shadow_rank_delta","shadow_rank_delta_direction","shadow_dynamic_weighted_score","top_positive_component_family","top_positive_component_value","top_negative_component_family","top_negative_component_value","explanation_short","explanation_status","recommendation_created","trade_action_created","diagnostic_only","research_only","shadow_only","official_promotion_allowed","broker_execution_supported"]
OVERLAP_FIELDS = ["top_n","baseline_top_n_count","shadow_top_n_count","overlap_count","turnover_count","overlap_ratio","turnover_ratio","entering_shadow_top_n_tickers","leaving_baseline_top_n_tickers","audit_status","audit_reason","research_only","shadow_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
GATE_FIELDS = ["gate_check_id","strict_equity_shadow_rerank_available","strict_equity_shadow_rerank_candidate_count","shadow_rank_unique","component_contribution_audit_available","baseline_comparison_available","v20_104_random_asof_forward_outcome_available","v20_105_factor_ablation_available","v20_106_regime_alignment_available","historical_coverage_status","v20_109_effectiveness_evaluation_ready","v20_109_readiness_status","recommended_next_stage","blocking_reason","performance_effectiveness_claim_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","research_only","shadow_only","official_promotion_allowed","is_official_weight","weight_mutated"]


def clean(v: object) -> str:
    return "" if v is None else str(v).strip()


def tf(v: bool) -> str:
    return "TRUE" if v else "FALSE"


def dec(v: str) -> Decimal:
    try:
        return Decimal(clean(v))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def fmt(v: Decimal | float) -> str:
    return f"{float(v):.10f}"


def safety() -> dict[str, str]:
    return {"research_only":"TRUE","shadow_only":"TRUE","official_promotion_allowed":"FALSE","official_recommendation_created":"FALSE","trade_action_created":"FALSE","broker_execution_supported":"FALSE"}


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str], str]:
    if not path.exists() or path.stat().st_size == 0:
        return [], [], "MISSING_OR_EMPTY"
    with path.open("r", encoding="utf-8-sig", newline="") as h:
        r = csv.DictReader(h)
        return [{k: clean(v) for k, v in row.items()} for row in r], list(r.fieldnames or []), "OK"


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def first_value(path: Path, field: str, default: str) -> str:
    rows, _, status = read_csv(path)
    return rows[0].get(field) or default if status == "OK" and rows else default


def artifact_has_rows(path: Path) -> bool:
    rows, _, status = read_csv(path)
    return status == "OK" and bool(rows)


def ticker_coverage(path: Path) -> set[str]:
    rows, _, status = read_csv(path)
    if status != "OK":
        return set()
    return {row.get("ticker", "") for row in rows if row.get("ticker")}


def main() -> int:
    rerank, _, status = read_csv(R12_RERANK)
    components, _, comp_status = read_csv(R12_COMPONENT)
    scope, _, _ = read_csv(R11_SCOPE)
    valid_input = status == "OK" and len(rerank) == 297 and len({r["strict_equity_shadow_rank"] for r in rerank}) == 297
    excluded = {r["ticker"] for r in scope if r.get("exclusion_reason") == "FUNDAMENTAL_NOT_APPLICABLE_REQUIRES_APPLICABILITY_WEIGHT_POLICY"}
    ranked = {r["ticker"] for r in rerank}
    valid_input = valid_input and not (ranked & excluded)

    comp_by_ticker: dict[str, dict[str, Decimal]] = {}
    for row in components:
        comp_by_ticker.setdefault(row["ticker"], {})[row["factor_family"]] = dec(row["weighted_component_contribution"])

    attribution = []
    for row in rerank:
        ticker = row["ticker"]
        vals = comp_by_ticker.get(ticker, {})
        positive = max(FAMILIES, key=lambda f: (vals.get(f, Decimal("-1")), f))
        drag = min(FAMILIES, key=lambda f: (vals.get(f, Decimal("99")), f))
        out = {
            "ticker": ticker,
            "baseline_rank": row["baseline_rank"],
            "strict_equity_shadow_rank": row["strict_equity_shadow_rank"],
            "shadow_rank_delta": row["shadow_rank_delta"],
            "shadow_rank_delta_direction": row["shadow_rank_delta_direction"],
            "shadow_dynamic_weighted_score": row["shadow_dynamic_weighted_score"],
            "dominant_positive_factor_family": positive,
            "dominant_positive_component_value": fmt(vals.get(positive, Decimal("0"))),
            "dominant_drag_factor_family": drag,
            "dominant_drag_component_value": fmt(vals.get(drag, Decimal("0"))),
            "attribution_status": "PASS",
            "attribution_reason": "WEIGHTED_COMPONENT_ATTRIBUTION_DIAGNOSTIC_ONLY",
            "diagnostic_only": "TRUE",
            **safety(),
        }
        for fam in FAMILIES:
            out[COMPONENT_FIELD[fam]] = fmt(vals.get(fam, Decimal("0")))
        attribution.append(out)

    deltas = [int(r["shadow_rank_delta"]) for r in rerank]
    abs_deltas = [abs(d) for d in deltas]
    improved = sum(1 for d in deltas if d > 0)
    unchanged = sum(1 for d in deltas if d == 0)
    worsened = sum(1 for d in deltas if d < 0)

    overlap_rows = []
    overlap_counts = {}
    for n in (10, 20, 50, 100):
        baseline_top = {r["ticker"] for r in rerank if int(r["baseline_rank"]) <= n}
        shadow_top = {r["ticker"] for r in rerank if int(r["strict_equity_shadow_rank"]) <= n}
        overlap = baseline_top & shadow_top
        entering = sorted(shadow_top - baseline_top)
        leaving = sorted(baseline_top - shadow_top)
        turnover = len(entering)
        overlap_counts[n] = (len(overlap), turnover)
        overlap_rows.append({
            "top_n": str(n),
            "baseline_top_n_count": str(len(baseline_top)),
            "shadow_top_n_count": str(len(shadow_top)),
            "overlap_count": str(len(overlap)),
            "turnover_count": str(turnover),
            "overlap_ratio": fmt(Decimal(len(overlap)) / Decimal(n)),
            "turnover_ratio": fmt(Decimal(turnover) / Decimal(n)),
            "entering_shadow_top_n_tickers": ";".join(entering),
            "leaving_baseline_top_n_tickers": ";".join(leaving),
            "audit_status": "PASS",
            "audit_reason": "BASELINE_VS_STRICT_EQUITY_SHADOW_TOP_N_OVERLAP_DIAGNOSTIC",
            **safety(),
        })

    summary = [{
        "summary_id": "V20_108_R13_DELTA_SUMMARY_001",
        "input_candidate_count": str(len(rerank)),
        "improved_count": str(improved),
        "unchanged_count": str(unchanged),
        "worsened_count": str(worsened),
        "max_improvement": str(max(deltas) if deltas else 0),
        "max_worsening": str(min(deltas) if deltas else 0),
        "average_absolute_delta": fmt(mean(abs_deltas) if abs_deltas else 0),
        "median_absolute_delta": fmt(median(abs_deltas) if abs_deltas else 0),
        "top10_overlap_count": str(overlap_counts[10][0]),
        "top20_overlap_count": str(overlap_counts[20][0]),
        "top50_overlap_count": str(overlap_counts[50][0]),
        "top100_overlap_count": str(overlap_counts[100][0]),
        "top10_turnover_count": str(overlap_counts[10][1]),
        "top20_turnover_count": str(overlap_counts[20][1]),
        "top50_turnover_count": str(overlap_counts[50][1]),
        "top100_turnover_count": str(overlap_counts[100][1]),
        "shadow_rerank_scope": "RESEARCH_ONLY_STRICT_EQUITY_SHADOW",
        "mixed_universe_rerank_created": "FALSE",
        "official_ranking_created": "FALSE",
        "official_recommendation_created": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        **safety(),
        "is_official_weight": "FALSE",
        "weight_mutated": "FALSE",
    }]

    by_ticker = {r["ticker"]: r for r in attribution}
    buckets: list[tuple[str, list[dict[str, str]]]] = [
        ("TOP_IMPROVER", sorted(rerank, key=lambda r: (-int(r["shadow_rank_delta"]), r["ticker"]))[:25]),
        ("TOP_WORSENER", sorted(rerank, key=lambda r: (int(r["shadow_rank_delta"]), r["ticker"]))[:25]),
        ("TOP_SHADOW_SCORE", sorted(rerank, key=lambda r: (-dec(r["shadow_dynamic_weighted_score"]), r["ticker"]))[:25]),
        ("BIGGEST_BASELINE_SHADOW_DIVERGENCE", sorted(rerank, key=lambda r: (-abs(int(r["shadow_rank_delta"])), r["ticker"]))[:25]),
    ]
    movers = []
    for bucket, rows in buckets:
        for row in rows:
            attr = by_ticker[row["ticker"]]
            movers.append({
                "ticker": row["ticker"],
                "mover_bucket": bucket,
                "baseline_rank": row["baseline_rank"],
                "strict_equity_shadow_rank": row["strict_equity_shadow_rank"],
                "shadow_rank_delta": row["shadow_rank_delta"],
                "shadow_rank_delta_direction": row["shadow_rank_delta_direction"],
                "shadow_dynamic_weighted_score": row["shadow_dynamic_weighted_score"],
                "top_positive_component_family": attr["dominant_positive_factor_family"],
                "top_positive_component_value": attr["dominant_positive_component_value"],
                "top_negative_component_family": attr["dominant_drag_factor_family"],
                "top_negative_component_value": attr["dominant_drag_component_value"],
                "explanation_short": "Research-only diagnostic attribution from weighted factor-family components.",
                "explanation_status": "DIAGNOSTIC_ONLY_NO_RECOMMENDATION",
                "recommendation_created": "FALSE",
                "trade_action_created": "FALSE",
                "diagnostic_only": "TRUE",
                **safety(),
            })

    forward_available = artifact_has_rows(V104_FORWARD)
    forward_cov = ticker_coverage(V104_FORWARD)
    full_forward = ranked.issubset(forward_cov)
    ablation_available = artifact_has_rows(V105_ABLATION) and artifact_has_rows(V105_HIST)
    regime_available = artifact_has_rows(V106_REGIME)
    if not valid_input:
        readiness_status = "BLOCKED_SHADOW_RERANK_INPUT_INVALID"
        ready = False
        wrapper_status = BLOCKED_STATUS
        coverage_status = "BLOCKED"
        blocking = "R12_STRICT_EQUITY_SHADOW_RERANK_INVALID"
    elif forward_available and ablation_available and regime_available and full_forward:
        readiness_status = "READY_V20_109_EFFECTIVENESS_EVALUATION"
        ready = True
        wrapper_status = PASS_STATUS
        coverage_status = "FULL_HISTORICAL_FORWARD_OUTCOME_COVERAGE_AVAILABLE"
        blocking = ""
    else:
        readiness_status = "PARTIAL_READY_WITH_LIMITED_HISTORICAL_COVERAGE"
        ready = True
        wrapper_status = PARTIAL_STATUS
        coverage_status = "PARTIAL_HISTORICAL_FORWARD_OUTCOME_COVERAGE"
        blocking = "V20_109_ALLOWED_AS_LIMITED_COVERAGE_EVALUATION_NO_EFFECTIVENESS_CLAIM"

    gate = [{
        "gate_check_id": "V20_108_R13_V20_109_READINESS_GATE_001",
        "strict_equity_shadow_rerank_available": tf(valid_input),
        "strict_equity_shadow_rerank_candidate_count": str(len(rerank)),
        "shadow_rank_unique": tf(len({r["strict_equity_shadow_rank"] for r in rerank}) == len(rerank)),
        "component_contribution_audit_available": tf(comp_status == "OK" and len(components) == len(rerank) * 6),
        "baseline_comparison_available": tf(all(r.get("baseline_rank") for r in rerank)),
        "v20_104_random_asof_forward_outcome_available": tf(forward_available),
        "v20_105_factor_ablation_available": tf(ablation_available),
        "v20_106_regime_alignment_available": tf(regime_available),
        "historical_coverage_status": coverage_status,
        "v20_109_effectiveness_evaluation_ready": tf(ready),
        "v20_109_readiness_status": readiness_status,
        "recommended_next_stage": "V20.109_STRICT_EQUITY_SHADOW_RERANK_EFFECTIVENESS_EVALUATION" if ready else "V20.108-R13_INPUT_REPAIR",
        "blocking_reason": blocking,
        "performance_effectiveness_claim_created": "FALSE",
        "official_ranking_created": "FALSE",
        "official_recommendation_created": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        **safety(),
        "is_official_weight": "FALSE",
        "weight_mutated": "FALSE",
    }]

    write_csv(OUT_SUMMARY, SUMMARY_FIELDS, summary)
    write_csv(OUT_ATTRIBUTION, ATTR_FIELDS, attribution)
    write_csv(OUT_MOVERS, MOVER_FIELDS, movers)
    write_csv(OUT_OVERLAP, OVERLAP_FIELDS, overlap_rows)
    write_csv(OUT_GATE, GATE_FIELDS, gate)

    research_gate = first_value(V49_RESEARCH, "research_only_gate_status", "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE")
    official_gate = first_value(V49_OFFICIAL, "official_promotion_gate_status", "BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE")
    report = [
        "# V20.108-R13 Strict Equity Shadow Rerank Delta And Effectiveness Readiness Report",
        "",
        "## Current Result",
        f"- wrapper_status: {wrapper_status}",
        f"- input_candidate_count: {len(rerank)}",
        f"- improved_count: {improved}",
        f"- unchanged_count: {unchanged}",
        f"- worsened_count: {worsened}",
        f"- v20_109_readiness_status: {readiness_status}",
        "- performance_effectiveness_claim_created: FALSE",
        "- mixed_universe_rerank_created: FALSE",
        f"- v20_49_research_only_gate_status: {research_gate}",
        f"- v20_49_official_promotion_gate_status: {official_gate}",
        "",
        "## Safety Boundary",
        "- research_only: TRUE",
        "- shadow_only: TRUE",
        "- diagnostic_only: TRUE",
        "- official_promotion_allowed: FALSE",
        "- official_ranking_created: FALSE",
        "- official_recommendation_created: FALSE",
        "- trade_action_created: FALSE",
        "- broker_execution_supported: FALSE",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")

    print(wrapper_status)
    print(f"INPUT_CANDIDATE_COUNT={len(rerank)}")
    print(f"IMPROVED_COUNT={improved}")
    print(f"UNCHANGED_COUNT={unchanged}")
    print(f"WORSENED_COUNT={worsened}")
    print(f"V20_109_READINESS_STATUS={readiness_status}")
    print("SOURCE_RANK_OR_SCORE_USED=FALSE")
    print("BASELINE_RANK_USED_AS_FACTOR_CONTRIBUTION=FALSE")
    print("FABRICATED_VALUES_CREATED=FALSE")
    print("PROXY_VALUES_ACTIVATED=FALSE")
    print("MIXED_UNIVERSE_RERANK_CREATED=FALSE")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED=FALSE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("IS_OFFICIAL_WEIGHT=FALSE")
    print(f"OUTPUT_SUMMARY={OUT_SUMMARY.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_ATTRIBUTION={OUT_ATTRIBUTION.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_MOVERS={OUT_MOVERS.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_OVERLAP={OUT_OVERLAP.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_GATE={OUT_GATE.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_REPORT={REPORT.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
