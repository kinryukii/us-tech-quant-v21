#!/usr/bin/env python
"""V20.108-R6B fundamental score materializer with partial coverage.

Materializes research-only fundamental_contribution for candidates with
certified real ticker-level fundamental metrics from R6A-R2. Non-certified
ETF/fund/non-equity or pending-patch candidates remain blank and excluded.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
SNAPSHOTS = CONSOLIDATION / "snapshots"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

SNAP_CACHE = SNAPSHOTS / "V20_108_R6A_R2_ENABLED_REFRESH_CACHE.csv"
SNAP_CERT = SNAPSHOTS / "V20_108_R6A_R2_ENABLED_REFRESH_CERTIFICATION.csv"
SNAP_GATE = SNAPSHOTS / "V20_108_R6A_R2_ENABLED_REFRESH_NEXT_STAGE_GATE.csv"
R3_REPAIR = CONSOLIDATION / "V20_108_R6A_R3_FUNDAMENTAL_REFRESH_COVERAGE_REPAIR_AUDIT.csv"
R3_GATE = CONSOLIDATION / "V20_108_R6A_R3_PARTIAL_MATERIALIZATION_GATE.csv"
R3_PATCH_TEMPLATE = CONSOLIDATION / "V20_108_R6A_R3_FUNDAMENTAL_LOCAL_PATCH_TEMPLATE.csv"
R4_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
R5_PLAN = CONSOLIDATION / "V20_108_R5_MISSING_UPSTREAM_FACTOR_SCORE_STAGE_PLAN.csv"
V107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R5_WEIGHT_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"
AUTHORITATIVE = CONSOLIDATION / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"

OUT_SOURCE = CONSOLIDATION / "V20_108_R6B_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE.csv"
OUT_COMPONENT = CONSOLIDATION / "V20_108_R6B_FUNDAMENTAL_SCORE_COMPONENT_AUDIT.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_108_R6B_FUNDAMENTAL_MATERIALIZATION_VALIDATION.csv"
OUT_COVERAGE = CONSOLIDATION / "V20_108_R6B_FACTOR_FAMILY_COVERAGE_AFTER_FUNDAMENTAL.csv"
OUT_GATE = CONSOLIDATION / "V20_108_R6B_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_108_R6B_FUNDAMENTAL_CANDIDATE_SCORE_MATERIALIZER_REPORT.md"

PASS_STATUS = "PASS_V20_108_R6B_FUNDAMENTAL_CANDIDATE_SCORE_MATERIALIZER_WITH_PARTIAL_COVERAGE"
PARTIAL_STATUS = "PARTIAL_PASS_V20_108_R6B_FUNDAMENTAL_CANDIDATE_SCORE_MATERIALIZER_WITH_EXCLUSIONS"
BLOCKED_STATUS = "BLOCKED_V20_108_R6B_NO_CERTIFIED_FUNDAMENTAL_METRICS_AVAILABLE"

COMPONENT_METRICS = {
    "growth": ["revenue_growth", "earnings_growth", "revenue_ttm"],
    "profitability": ["profit_margin", "net_income_ttm"],
    "margin": ["gross_margin", "operating_margin", "ebitda_margin"],
    "quality": ["return_on_equity", "return_on_assets"],
    "valuation": ["market_cap", "enterprise_value", "trailing_pe", "forward_pe", "price_to_sales", "price_to_book", "ev_to_ebitda"],
    "cash_flow": ["operating_cashflow", "free_cashflow"],
    "balance_sheet": ["debt_to_equity", "total_debt", "total_cash"],
    "liquidity": ["current_ratio", "quick_ratio"],
    "capex": ["capital_expenditures"],
}
METRICS = [metric for metrics in COMPONENT_METRICS.values() for metric in metrics]
LOWER_IS_BETTER = {
    "trailing_pe", "forward_pe", "price_to_sales", "price_to_book", "ev_to_ebitda",
    "debt_to_equity", "total_debt", "capital_expenditures",
}

SOURCE_FIELDS = [
    "ticker", "baseline_rank", "fundamental_contribution",
    "growth_component_score", "profitability_component_score",
    "margin_component_score", "quality_component_score", "valuation_component_score",
    "cash_flow_component_score", "balance_sheet_component_score",
    "liquidity_component_score", "capex_component_score",
    "present_numeric_metric_count", "missing_metric_count",
    "fundamental_metric_certification_status", "fundamental_materialization_status",
    "fundamental_source_artifact", "fundamental_source_stage",
    "fundamental_normalization_method", "fundamental_applicability_status",
    "usable_for_fundamental_scoring", "usable_for_shadow_rerank",
    "fabricated_values_created", "proxy_values_activated", "shadow_rerank_output_created",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "is_official_ranking", "is_official_weight", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]
COMPONENT_FIELDS = [
    "ticker", "component_group", "metrics_used", "metric_count_used",
    "raw_metric_values_present", "normalization_method",
    "lower_is_better_inversion_applied", "component_score", "component_status",
    "component_blocker_reason", "fabricated_values_created", "proxy_values_activated",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]
VALIDATION_FIELDS = [
    "validation_check_id", "candidate_count", "certified_candidate_count",
    "materialized_fundamental_candidate_count", "excluded_or_pending_candidate_count",
    "fabricated_values_created", "proxy_values_activated", "source_rank_or_score_used",
    "baseline_rank_used", "fundamental_contribution_scores_created",
    "shadow_rerank_output_created", "official_ranking_created",
    "authoritative_ranking_overwritten", "fundamental_partial_materialization_allowed",
    "validation_status", "validation_reason", "research_only",
    "official_promotion_allowed", "official_recommendation_created",
    "is_official_weight", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]
COVERAGE_FIELDS = [
    "factor_family", "required_candidate_count", "materialized_candidate_count",
    "missing_candidate_count", "coverage_ratio", "contribution_coverage_status",
    "usable_for_shadow_rerank", "missing_reason", "recommended_next_stage",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "is_official_weight", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]
GATE_FIELDS = [
    "gate_check_id", "fundamental_materialized",
    "materialized_fundamental_candidate_count",
    "complete_six_family_contribution_candidate_count",
    "usable_for_shadow_rerank_count", "next_stage_allowed",
    "recommended_next_stage", "blocking_reason", "research_only",
    "official_promotion_allowed", "official_recommendation_created",
    "is_official_weight", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def safety(extra: bool = False) -> dict[str, str]:
    row = {
        "research_only": "TRUE",
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
    }
    if extra:
        row["is_official_ranking"] = "FALSE"
        row["is_official_weight"] = "FALSE"
    return row


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str], str]:
    if not path.exists():
        return [], [], "MISSING"
    if path.stat().st_size == 0:
        return [], [], "EMPTY"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [{key: clean(value) for key, value in row.items()} for row in reader]
    return rows, fields, "OK" if fields else "MALFORMED"


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def num(value: object) -> float | None:
    try:
        parsed = float(clean(value))
    except ValueError:
        return None
    return None if math.isnan(parsed) or math.isinf(parsed) else parsed


def fmt(value: float) -> str:
    return f"{value:.10f}"


def first_value(path: Path, field: str, default: str) -> str:
    rows, _, status = read_csv(path)
    if status == "OK" and rows:
        return rows[0].get(field, default) or default
    return default


def normalize_metric(value: float, low: float, high: float, lower_is_better: bool) -> float:
    if high == low:
        return 1.0
    score = (high - value) / (high - low) if lower_is_better else (value - low) / (high - low)
    return max(0.0, min(1.0, score))


def build_metric_ranges(certified_rows: list[dict[str, str]]) -> dict[str, tuple[float, float]]:
    ranges: dict[str, tuple[float, float]] = {}
    for metric in METRICS:
        values = [parsed for row in certified_rows if (parsed := num(row.get(metric))) is not None]
        if values:
            ranges[metric] = (min(values), max(values))
    return ranges


def complete_six_family_count(r4_rows: list[dict[str, str]], materialized_fundamental: set[str]) -> int:
    count = 0
    for row in r4_rows:
        ticker = row.get("ticker", "")
        families = {part for part in row.get("materialized_factor_families", "").split(";") if part}
        if ticker in materialized_fundamental:
            families.add("FUNDAMENTAL")
        if {"FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"}.issubset(families):
            count += 1
    return count


def main() -> int:
    source_rows, _, source_status = read_csv(SNAP_CACHE)
    repair_rows, _, _ = read_csv(R3_REPAIR)
    r3_gate_rows, _, _ = read_csv(R3_GATE)
    r4_rows, _, _ = read_csv(R4_SCORES)
    repair_by_ticker = {row["ticker"]: row for row in repair_rows}
    partial_allowed = bool(r3_gate_rows and r3_gate_rows[0].get("partial_materialization_allowed") == "TRUE")
    certified_rows = [row for row in source_rows if row.get("fundamental_metric_certification_status") == "FUNDAMENTAL_METRICS_CERTIFIED"]
    ranges = build_metric_ranges(certified_rows)
    source_output: list[dict[str, str]] = []
    component_audit: list[dict[str, str]] = []
    materialized_tickers: set[str] = set()

    for row in source_rows:
        ticker = row.get("ticker", "")
        certified = row.get("fundamental_metric_certification_status") == "FUNDAMENTAL_METRICS_CERTIFIED"
        component_scores: dict[str, float] = {}
        materialized = certified and partial_allowed
        for component, metrics in COMPONENT_METRICS.items():
            used: list[str] = []
            raw_values: list[str] = []
            scores: list[float] = []
            inversions: list[str] = []
            if materialized:
                for metric in metrics:
                    value = num(row.get(metric))
                    if value is None or metric not in ranges:
                        continue
                    low, high = ranges[metric]
                    lower = metric in LOWER_IS_BETTER
                    scores.append(normalize_metric(value, low, high, lower))
                    used.append(metric)
                    raw_values.append(f"{metric}={clean(row.get(metric))}")
                    if lower:
                        inversions.append(metric)
            if scores:
                component_score = sum(scores) / len(scores)
                component_scores[component] = component_score
                status = "COMPONENT_MATERIALIZED_FROM_REAL_NUMERIC_METRICS"
                blocker = ""
                score_text = fmt(component_score)
            else:
                status = "COMPONENT_NOT_MATERIALIZED"
                blocker = "CERTIFIED_METRICS_REQUIRED" if not materialized else "NO_REAL_NUMERIC_METRICS_FOR_COMPONENT"
                score_text = ""
            component_audit.append({
                "ticker": ticker,
                "component_group": component,
                "metrics_used": ";".join(used),
                "metric_count_used": str(len(used)),
                "raw_metric_values_present": ";".join(raw_values),
                "normalization_method": "MIN_MAX_NORMALIZATION_WITH_LOWER_IS_BETTER_INVERSION" if used else "NOT_NORMALIZED",
                "lower_is_better_inversion_applied": ";".join(inversions) if inversions else "FALSE",
                "component_score": score_text,
                "component_status": status,
                "component_blocker_reason": blocker,
                "fabricated_values_created": "FALSE",
                "proxy_values_activated": "FALSE",
                **safety(),
            })

        if component_scores:
            contribution = sum(component_scores.values()) / len(component_scores)
            materialized_tickers.add(ticker)
            material_status = "MATERIALIZED_FROM_CERTIFIED_REAL_METRICS"
            applicability = "CERTIFIED_EQUITY_OR_APPLICABLE_FUNDAMENTAL_METRICS"
            usable = "TRUE"
            norm_method = "AVERAGE_OF_COMPONENT_MIN_MAX_NORMALIZED_REAL_NUMERIC_METRICS;LOWER_IS_BETTER_INVERTED_FOR_VALUATION_DEBT_CAPEX"
        else:
            contribution = None
            classification = repair_by_ticker.get(ticker, {}).get("repair_classification", "")
            if classification in {"ETF_OR_FUNDAMENTAL_NOT_APPLICABLE", "NON_EQUITY_INSTRUMENT"}:
                material_status = "EXCLUDED_NON_EQUITY_OR_FUNDAMENTAL_NOT_APPLICABLE"
                applicability = classification
            elif row.get("fundamental_metric_certification_status") in {"FUNDAMENTAL_METRICS_PARTIAL", "FUNDAMENTAL_METRICS_MISSING"}:
                material_status = "PENDING_LOCAL_PATCH"
                applicability = "NON_CERTIFIED_PENDING_LOCAL_PATCH_OR_EXCLUSION"
            else:
                material_status = "MISSING_CERTIFIED_METRICS"
                applicability = "MISSING_CERTIFIED_REAL_METRICS"
            usable = "FALSE"
            norm_method = "NOT_NORMALIZED_NO_CERTIFIED_REAL_METRICS"

        out = {
            "ticker": ticker,
            "baseline_rank": row.get("baseline_rank", ""),
            "fundamental_contribution": fmt(contribution) if contribution is not None else "",
            "growth_component_score": fmt(component_scores["growth"]) if "growth" in component_scores else "",
            "profitability_component_score": fmt(component_scores["profitability"]) if "profitability" in component_scores else "",
            "margin_component_score": fmt(component_scores["margin"]) if "margin" in component_scores else "",
            "quality_component_score": fmt(component_scores["quality"]) if "quality" in component_scores else "",
            "valuation_component_score": fmt(component_scores["valuation"]) if "valuation" in component_scores else "",
            "cash_flow_component_score": fmt(component_scores["cash_flow"]) if "cash_flow" in component_scores else "",
            "balance_sheet_component_score": fmt(component_scores["balance_sheet"]) if "balance_sheet" in component_scores else "",
            "liquidity_component_score": fmt(component_scores["liquidity"]) if "liquidity" in component_scores else "",
            "capex_component_score": fmt(component_scores["capex"]) if "capex" in component_scores else "",
            "present_numeric_metric_count": row.get("present_numeric_metric_count", "0"),
            "missing_metric_count": row.get("missing_metric_count", "25"),
            "fundamental_metric_certification_status": row.get("fundamental_metric_certification_status", ""),
            "fundamental_materialization_status": material_status,
            "fundamental_source_artifact": row.get("metric_source_artifact", ""),
            "fundamental_source_stage": "V20.108-R6A-R2_ENABLED_REFRESH_SNAPSHOT",
            "fundamental_normalization_method": norm_method,
            "fundamental_applicability_status": applicability,
            "usable_for_fundamental_scoring": usable,
            "usable_for_shadow_rerank": "FALSE",
            "fabricated_values_created": "FALSE",
            "proxy_values_activated": "FALSE",
            "shadow_rerank_output_created": "FALSE",
            **safety(extra=True),
        }
        source_output.append(out)

    candidate_count = len(source_output)
    materialized_count = len(materialized_tickers)
    excluded_count = candidate_count - materialized_count
    complete_six_count = complete_six_family_count(r4_rows, materialized_tickers)
    usable_shadow_count = 0
    if materialized_count == 0:
        wrapper_status = BLOCKED_STATUS
        validation_status = "BLOCKED"
        validation_reason = "NO_CERTIFIED_FUNDAMENTAL_METRICS_AVAILABLE"
    elif excluded_count:
        wrapper_status = PARTIAL_STATUS
        validation_status = "PASS"
        validation_reason = "PARTIAL_COVERAGE_MATERIALIZED_CERTIFIED_REAL_METRICS_ONLY_WITH_EXCLUSIONS"
    else:
        wrapper_status = PASS_STATUS
        validation_status = "PASS"
        validation_reason = "ALL_CANDIDATES_MATERIALIZED_FROM_CERTIFIED_REAL_METRICS"

    validation_rows = [{
        "validation_check_id": "V20_108_R6B_VALIDATION_001",
        "candidate_count": str(candidate_count),
        "certified_candidate_count": str(len(certified_rows)),
        "materialized_fundamental_candidate_count": str(materialized_count),
        "excluded_or_pending_candidate_count": str(excluded_count),
        "fabricated_values_created": "FALSE",
        "proxy_values_activated": "FALSE",
        "source_rank_or_score_used": "FALSE",
        "baseline_rank_used": "FALSE",
        "fundamental_contribution_scores_created": tf(materialized_count > 0),
        "shadow_rerank_output_created": "FALSE",
        "official_ranking_created": "FALSE",
        "authoritative_ranking_overwritten": "FALSE",
        "fundamental_partial_materialization_allowed": tf(partial_allowed),
        "validation_status": validation_status,
        "validation_reason": validation_reason,
        **safety(),
        "is_official_weight": "FALSE",
    }]

    coverage_rows = [
        {
            "factor_family": "FUNDAMENTAL",
            "required_candidate_count": str(candidate_count),
            "materialized_candidate_count": str(materialized_count),
            "missing_candidate_count": str(excluded_count),
            "coverage_ratio": f"{(materialized_count / candidate_count if candidate_count else 0.0):.10f}",
            "contribution_coverage_status": "PARTIAL" if excluded_count else "COMPLETE",
            "usable_for_shadow_rerank": "FALSE",
            "missing_reason": "NON_CERTIFIED_ETF_FUND_OR_PENDING_PATCH_EXCLUDED" if excluded_count else "",
            "recommended_next_stage": "V20.108-R7_STRATEGY_CANDIDATE_SCORE_SOURCE_BUILDER",
            **safety(),
            "is_official_weight": "FALSE",
        },
        {
            "factor_family": "TECHNICAL",
            "required_candidate_count": str(candidate_count),
            "materialized_candidate_count": "315",
            "missing_candidate_count": "0",
            "coverage_ratio": "1.0000000000",
            "contribution_coverage_status": "COMPLETE",
            "usable_for_shadow_rerank": "FALSE",
            "missing_reason": "SIX_FAMILY_SET_INCOMPLETE_STRATEGY_RISK_MARKET_REGIME",
            "recommended_next_stage": "V20.108-R7_STRATEGY_CANDIDATE_SCORE_SOURCE_BUILDER",
            **safety(),
            "is_official_weight": "FALSE",
        },
        {
            "factor_family": "DATA_TRUST",
            "required_candidate_count": str(candidate_count),
            "materialized_candidate_count": "315",
            "missing_candidate_count": "0",
            "coverage_ratio": "1.0000000000",
            "contribution_coverage_status": "COMPLETE",
            "usable_for_shadow_rerank": "FALSE",
            "missing_reason": "SIX_FAMILY_SET_INCOMPLETE_STRATEGY_RISK_MARKET_REGIME",
            "recommended_next_stage": "V20.108-R7_STRATEGY_CANDIDATE_SCORE_SOURCE_BUILDER",
            **safety(),
            "is_official_weight": "FALSE",
        },
        {
            "factor_family": "RISK",
            "required_candidate_count": str(candidate_count),
            "materialized_candidate_count": "11",
            "missing_candidate_count": str(candidate_count - 11),
            "coverage_ratio": f"{(11 / candidate_count if candidate_count else 0.0):.10f}",
            "contribution_coverage_status": "PARTIAL",
            "usable_for_shadow_rerank": "FALSE",
            "missing_reason": "RISK_REMAINS_PARTIAL_11_OF_315",
            "recommended_next_stage": "V20.108-R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER",
            **safety(),
            "is_official_weight": "FALSE",
        },
        {
            "factor_family": "STRATEGY",
            "required_candidate_count": str(candidate_count),
            "materialized_candidate_count": "0",
            "missing_candidate_count": str(candidate_count),
            "coverage_ratio": "0.0000000000",
            "contribution_coverage_status": "MISSING",
            "usable_for_shadow_rerank": "FALSE",
            "missing_reason": "STRATEGY_REMAINS_MISSING",
            "recommended_next_stage": "V20.108-R7_STRATEGY_CANDIDATE_SCORE_SOURCE_BUILDER",
            **safety(),
            "is_official_weight": "FALSE",
        },
        {
            "factor_family": "MARKET_REGIME",
            "required_candidate_count": str(candidate_count),
            "materialized_candidate_count": "0",
            "missing_candidate_count": str(candidate_count),
            "coverage_ratio": "0.0000000000",
            "contribution_coverage_status": "MISSING",
            "usable_for_shadow_rerank": "FALSE",
            "missing_reason": "MARKET_REGIME_REMAINS_MISSING",
            "recommended_next_stage": "V20.108-R8_MARKET_REGIME_CANDIDATE_EXPOSURE_BUILDER",
            **safety(),
            "is_official_weight": "FALSE",
        },
    ]
    gate_rows = [{
        "gate_check_id": "V20_108_R6B_NEXT_STAGE_GATE_001",
        "fundamental_materialized": tf(materialized_count > 0),
        "materialized_fundamental_candidate_count": str(materialized_count),
        "complete_six_family_contribution_candidate_count": str(complete_six_count),
        "usable_for_shadow_rerank_count": str(usable_shadow_count),
        "next_stage_allowed": "FALSE",
        "recommended_next_stage": "V20.108-R7_STRATEGY_CANDIDATE_SCORE_SOURCE_BUILDER",
        "blocking_reason": "TRUE_SHADOW_RERANK_BLOCKED_UNTIL_ALL_SIX_FACTOR_FAMILIES_COMPLETE",
        **safety(),
        "is_official_weight": "FALSE",
    }]

    write_csv(OUT_SOURCE, SOURCE_FIELDS, source_output)
    write_csv(OUT_COMPONENT, COMPONENT_FIELDS, component_audit)
    write_csv(OUT_VALIDATION, VALIDATION_FIELDS, validation_rows)
    write_csv(OUT_COVERAGE, COVERAGE_FIELDS, coverage_rows)
    write_csv(OUT_GATE, GATE_FIELDS, gate_rows)

    research_gate = first_value(V49_RESEARCH, "research_only_gate_status", "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE")
    official_gate = first_value(V49_OFFICIAL, "official_promotion_gate_status", "BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE")
    report = [
        "# V20.108-R6B Fundamental Candidate Score Materializer Report",
        "",
        "## Current Result",
        f"- wrapper_status: {wrapper_status}",
        f"- source_cache: {rel(SNAP_CACHE)}",
        f"- source_certification: {rel(SNAP_CERT)}",
        f"- source_next_stage_gate: {rel(SNAP_GATE)}",
        f"- candidate_count: {candidate_count}",
        f"- certified_candidate_count: {len(certified_rows)}",
        f"- materialized_fundamental_candidate_count: {materialized_count}",
        f"- excluded_or_pending_candidate_count: {excluded_count}",
        f"- complete_six_family_contribution_candidate_count: {complete_six_count}",
        f"- usable_for_shadow_rerank_count: {usable_shadow_count}",
        f"- v20_49_research_only_gate_status: {research_gate}",
        f"- v20_49_official_promotion_gate_status: {official_gate}",
        "- source_rank_or_score_used: FALSE",
        "- baseline_rank_used: FALSE",
        "- fabricated_values_created: FALSE",
        "- proxy_values_activated: FALSE",
        "- shadow_rerank_output_created: FALSE",
        "- official_ranking_created: FALSE",
        "- authoritative_ranking_overwritten: FALSE",
        "",
        "## Normalization",
        "- method: component average of min-max normalized real numeric certified metrics",
        "- lower_is_better_inversion_applied_to: trailing_pe;forward_pe;price_to_sales;price_to_book;ev_to_ebitda;debt_to_equity;total_debt;capital_expenditures",
        "- non_certified_candidates: blank contribution, excluded or pending patch",
        "",
        "## Safety Boundary",
        "- research_only: TRUE",
        "- official_promotion_allowed: FALSE",
        "- official_recommendation_created: FALSE",
        "- is_official_ranking: FALSE",
        "- is_official_weight: FALSE",
        "- weight_mutated: FALSE",
        "- trade_action_created: FALSE",
        "- broker_execution_supported: FALSE",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")

    print(wrapper_status)
    print(f"CANDIDATE_COUNT={candidate_count}")
    print(f"MATERIALIZED_FUNDAMENTAL_CANDIDATE_COUNT={materialized_count}")
    print(f"EXCLUDED_OR_PENDING_CANDIDATE_COUNT={excluded_count}")
    print(f"COMPLETE_SIX_FAMILY_CONTRIBUTION_CANDIDATE_COUNT={complete_six_count}")
    print(f"USABLE_FOR_SHADOW_RERANK_COUNT={usable_shadow_count}")
    print("SOURCE_RANK_OR_SCORE_USED=FALSE")
    print("BASELINE_RANK_USED=FALSE")
    print("FABRICATED_VALUES_CREATED=FALSE")
    print("PROXY_VALUES_ACTIVATED=FALSE")
    print("SHADOW_RERANK_OUTPUT_CREATED=FALSE")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("IS_OFFICIAL_WEIGHT=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print(f"OUTPUT_SCORE_SOURCE={rel(OUT_SOURCE)}")
    print(f"OUTPUT_COMPONENT_AUDIT={rel(OUT_COMPONENT)}")
    print(f"OUTPUT_VALIDATION={rel(OUT_VALIDATION)}")
    print(f"OUTPUT_COVERAGE={rel(OUT_COVERAGE)}")
    print(f"OUTPUT_NEXT_STAGE_GATE={rel(OUT_GATE)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
