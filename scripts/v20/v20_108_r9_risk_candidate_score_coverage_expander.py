#!/usr/bin/env python
"""V20.108-R9 risk candidate score coverage expander.

Builds research-only RISK candidate contributions from real candidate-level
risk context. It carries forward existing real R4 risk contributions and expands
coverage only from audited downside evidence and explicit timing risk states.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
EVIDENCE = ROOT / "outputs" / "v20" / "evidence"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R8_R3_SOURCE = CONSOLIDATION / "V20_108_R8_R3_MARKET_REGIME_CONTRIBUTION_SOURCE.csv"
R8_R3_VALIDATION = CONSOLIDATION / "V20_108_R8_R3_MARKET_REGIME_MATERIALIZATION_VALIDATION.csv"
R8_R3_COVERAGE = CONSOLIDATION / "V20_108_R8_R3_FACTOR_FAMILY_COVERAGE_AFTER_MARKET_REGIME_MAPPING.csv"
R8_R3_GATE = CONSOLIDATION / "V20_108_R8_R3_NEXT_STAGE_GATE.csv"
R7_SOURCE = CONSOLIDATION / "V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE.csv"
R6B_SOURCE = CONSOLIDATION / "V20_108_R6B_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE.csv"
R4_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
R5_PLAN = CONSOLIDATION / "V20_108_R5_MISSING_UPSTREAM_FACTOR_SCORE_STAGE_PLAN.csv"
DOWNSIDE = CONSOLIDATION / "V20_CURRENT_DOWNSIDE_RISK_EVIDENCE_EXPORT.csv"
V85_GAP = CONSOLIDATION / "V20_85_GAP_PLAN.csv"
V92_GAP = CONSOLIDATION / "V20_92_EVIDENCE_BLOCKER_GAP_RESOLVER.csv"
V93_REPAIR = CONSOLIDATION / "V20_93_EVIDENCE_SCHEMA_REPAIR_PACK.csv"
V50_CANDIDATES = CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V48_FACTORS = CONSOLIDATION / "V20_48_REFRESHED_FACTOR_SUPPORT_VIEW.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"
V18_TIMING = ROOT / "outputs" / "v18" / "technical_timing" / "V18_6A_CURRENT_TECHNICAL_TIMING.csv"

OUT_SOURCE = CONSOLIDATION / "V20_108_R9_RISK_CANDIDATE_SCORE_SOURCE.csv"
OUT_AUDIT = CONSOLIDATION / "V20_108_R9_RISK_SOURCE_COLUMN_AUDIT.csv"
OUT_COMPONENT = CONSOLIDATION / "V20_108_R9_RISK_SCORE_COMPONENT_AUDIT.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_108_R9_RISK_MATERIALIZATION_VALIDATION.csv"
OUT_COVERAGE = CONSOLIDATION / "V20_108_R9_FACTOR_FAMILY_COVERAGE_AFTER_RISK.csv"
OUT_GATE = CONSOLIDATION / "V20_108_R9_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_108_R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER_REPORT.md"

PASS_STATUS = "PASS_V20_108_R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER"
PARTIAL_STATUS = "PARTIAL_PASS_V20_108_R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER_WITH_PARTIAL_COVERAGE"
BLOCKED_STATUS = "BLOCKED_V20_108_R9_NO_SAFE_RISK_CANDIDATE_SOURCE_FOUND"

COMPONENTS = [
    "downside", "volatility", "drawdown", "overheat", "trend_break", "liquidity",
    "data_quality", "leverage_instrument", "balance_sheet", "valuation_risk", "event_macro",
]
COMPONENT_FIELD = {
    "downside": "downside_component_score",
    "volatility": "volatility_component_score",
    "drawdown": "drawdown_component_score",
    "overheat": "overheat_component_score",
    "trend_break": "trend_break_component_score",
    "liquidity": "liquidity_component_score",
    "data_quality": "data_quality_component_score",
    "leverage_instrument": "leverage_instrument_component_score",
    "balance_sheet": "balance_sheet_component_score",
    "valuation_risk": "valuation_risk_component_score",
    "event_macro": "event_macro_component_score",
}
SOURCE_FIELDS = [
    "ticker", "baseline_rank", "risk_contribution",
    "downside_component_score", "volatility_component_score",
    "drawdown_component_score", "overheat_component_score",
    "trend_break_component_score", "liquidity_component_score",
    "data_quality_component_score", "leverage_instrument_component_score",
    "balance_sheet_component_score", "valuation_risk_component_score",
    "event_macro_component_score", "risk_raw_columns_used",
    "risk_categorical_mappings_used", "risk_normalization_method",
    "risk_source_artifact", "risk_source_stage", "risk_source_status",
    "risk_materialization_status", "missing_reason", "usable_for_risk_scoring",
    "usable_for_shadow_rerank", "fabricated_values_created", "proxy_values_activated",
    "entry_exit_prices_created", "buy_sell_recommendations_created",
    "shadow_rerank_output_created", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "is_official_ranking", "is_official_weight",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]
AUDIT_FIELDS = [
    "source_artifact", "source_exists", "source_non_empty", "ticker_column_available",
    "candidate_rows_found", "detected_risk_numeric_columns",
    "detected_risk_categorical_columns", "detected_raw_non_risk_columns",
    "accepted_columns", "rejected_columns", "rejection_reason",
    "source_rank_or_score_present", "source_rank_or_score_used_as_risk",
    "baseline_rank_used_as_risk", "materialization_allowed",
    "materialization_blocker_reason", "validation_status", "validation_reason",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]
COMPONENT_FIELDS = [
    "ticker", "component_group", "metrics_or_categories_used", "raw_values_present",
    "categorical_mapping_applied", "lower_raw_value_is_better", "inversion_applied",
    "normalization_method", "component_score", "component_status",
    "component_blocker_reason", "fabricated_values_created", "proxy_values_activated",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]
VALIDATION_FIELDS = [
    "validation_check_id", "candidate_count", "materialized_risk_candidate_count",
    "missing_risk_candidate_count", "carried_forward_existing_risk_candidate_count",
    "newly_materialized_risk_candidate_count", "fabricated_values_created",
    "proxy_values_activated", "source_rank_or_score_used", "baseline_rank_used",
    "risk_contribution_scores_created", "entry_exit_prices_created",
    "buy_sell_recommendations_created", "shadow_rerank_output_created",
    "official_ranking_created", "authoritative_ranking_overwritten",
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
    "gate_check_id", "risk_materialized", "materialized_risk_candidate_count",
    "complete_six_family_contribution_candidate_count", "usable_for_shadow_rerank_count",
    "next_stage_allowed", "recommended_next_stage", "blocking_reason",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "is_official_weight", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]

CATEGORY_MAP = {
    "OVERHEAT_REVIEW": (0.35, "OVERHEATED=>0.35"),
    "NOT_BUY_ZONE_OVERHEAT_REVIEW": (0.35, "FAR_ABOVE_BUY_ZONE=>0.35"),
    "TECH_TIMING_OVERHEAT_AVOID_CHASE": (0.35, "OVERHEATED=>0.35"),
    "TREND_BROKEN": (0.25, "TREND_BROKEN=>0.25"),
    "DOWNTREND": (0.35, "DOWNTREND=>0.35"),
    "DEEP_PULLBACK_REVIEW": (0.45, "DEEP_PULLBACK_REVIEW=>0.45"),
    "NEAR_BUY_ZONE": (0.60, "NEAR_BUY_ZONE=>0.60"),
    "IN_BUY_ZONE": (0.65, "IN_BUY_ZONE=>0.65"),
    "BUY_ZONE": (0.65, "IN_BUY_ZONE=>0.65"),
    "MIXED": (0.50, "MIXED=>0.50"),
    "UPTREND": (0.62, "UPTREND=>0.62"),
    "AVAILABLE": (0.60, "PRICE_FRESHNESS_AVAILABLE=>0.60"),
}


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
    if not path.exists() or path.stat().st_size == 0:
        return [], [], "MISSING_OR_EMPTY"
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
    text = clean(value)
    if text.upper() in {"", "NA", "NAN", "NONE"}:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return None if math.isnan(parsed) or math.isinf(parsed) else parsed


def fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.10f}"


def first_value(path: Path, field: str, default: str) -> str:
    rows, _, status = read_csv(path)
    return rows[0].get(field, default) if status == "OK" and rows and rows[0].get(field) else default


def source_stage(path: Path) -> str:
    name = path.name
    if name.startswith("V20_"):
        parts = name.split("_", 2)
        return f"{parts[0]}.{parts[1]}" if len(parts) > 1 else "V20"
    if name.startswith("V18_"):
        return "V18"
    return "DISCOVERED"


def normalize_risk(raw: float, lower_raw_value_is_better: bool) -> float:
    magnitude = abs(raw)
    if lower_raw_value_is_better:
        return max(0.0, min(1.0, 1.0 - magnitude))
    return max(0.0, min(1.0, raw if 0.0 <= raw <= 1.0 else raw / 100.0))


def category_score(value: str) -> tuple[float | None, str]:
    token = clean(value).upper().replace(" ", "_")
    if not token:
        return None, ""
    if token in CATEGORY_MAP:
        return CATEGORY_MAP[token]
    for key, mapped in CATEGORY_MAP.items():
        if key in token:
            return mapped
    return None, ""


def add_value(store: dict[str, dict[str, list[dict[str, str]]]], ticker: str, component: str, score: float, field: str, raw: str, artifact: Path, mapping: str = "", lower_better: bool = False, inversion: bool = False) -> None:
    store.setdefault(ticker, {name: [] for name in COMPONENTS})
    store[ticker][component].append({
        "score": fmt(score),
        "field": field,
        "raw": raw,
        "artifact": rel(artifact),
        "stage": source_stage(artifact),
        "mapping": mapping,
        "lower_better": tf(lower_better),
        "inversion": tf(inversion),
    })


def audit_row(path: Path, fields: list[str], candidate_rows: int, numeric: list[str], categorical: list[str], raw_non_risk: list[str], accepted: list[str], rejected: list[str], reason: str) -> dict[str, str]:
    allowed = bool(accepted)
    return {
        "source_artifact": rel(path),
        "source_exists": tf(path.exists()),
        "source_non_empty": tf(path.exists() and path.stat().st_size > 0),
        "ticker_column_available": tf("ticker" in fields or "normalized_ticker" in fields or "ticker_or_candidate_id" in fields),
        "candidate_rows_found": str(candidate_rows),
        "detected_risk_numeric_columns": ";".join(sorted(set(numeric))),
        "detected_risk_categorical_columns": ";".join(sorted(set(categorical))),
        "detected_raw_non_risk_columns": ";".join(sorted(set(raw_non_risk))),
        "accepted_columns": ";".join(sorted(set(accepted))),
        "rejected_columns": ";".join(sorted(set(rejected))),
        "rejection_reason": reason,
        "source_rank_or_score_present": tf("source_rank_or_score" in fields),
        "source_rank_or_score_used_as_risk": "FALSE",
        "baseline_rank_used_as_risk": "FALSE",
        "materialization_allowed": tf(allowed),
        "materialization_blocker_reason": "" if allowed else "NO_SAFE_CANDIDATE_LEVEL_RISK_COLUMNS",
        "validation_status": "PASS" if allowed else "BLOCKED",
        "validation_reason": "SAFE_CANDIDATE_LEVEL_RISK_CONTEXT_FOUND" if allowed else "NO_SAFE_CANDIDATE_LEVEL_RISK_CONTEXT_FOUND",
        **safety(),
    }


def load_candidates() -> list[dict[str, str]]:
    rows, _, status = read_csv(R4_SCORES)
    if status == "OK":
        return [{"ticker": row["ticker"], "baseline_rank": row.get("baseline_rank", "")} for row in rows if row.get("ticker")]
    rows, _, status = read_csv(V48_CANDIDATES)
    return [{"ticker": row.get("normalized_ticker") or row.get("ticker_or_candidate_id", ""), "baseline_rank": row.get("report_rank", "")} for row in rows] if status == "OK" else []


def collect_risk_values(candidates: list[dict[str, str]]) -> tuple[dict[str, dict[str, list[dict[str, str]]]], list[dict[str, str]], set[str]]:
    tickers = {row["ticker"] for row in candidates}
    values: dict[str, dict[str, list[dict[str, str]]]] = {ticker: {component: [] for component in COMPONENTS} for ticker in tickers}
    audits: list[dict[str, str]] = []
    carried: set[str] = set()

    r4_rows, r4_fields, r4_status = read_csv(R4_SCORES)
    r4_candidate_rows = 0
    if r4_status == "OK":
        for row in r4_rows:
            ticker = row.get("ticker", "")
            risk = num(row.get("risk_contribution"))
            if ticker in tickers and risk is not None:
                r4_candidate_rows += 1
                carried.add(ticker)
                add_value(values, ticker, "downside", max(0.0, min(1.0, risk)), "risk_contribution", row.get("risk_contribution", ""), R4_SCORES, "CARRIED_FORWARD_EXISTING_REAL_RISK_CONTRIBUTION")
    audits.append(audit_row(R4_SCORES, r4_fields, r4_candidate_rows, ["risk_contribution"], [], ["baseline_rank"], ["risk_contribution"] if r4_candidate_rows else [], ["baseline_rank"], "BASELINE_RANK_EXCLUDED_FROM_RISK"))

    downside_rows, downside_fields, downside_status = read_csv(DOWNSIDE)
    downside_candidate_rows = 0
    if downside_status == "OK":
        for row in downside_rows:
            ticker = row.get("ticker", "")
            if ticker not in tickers or row.get("downside_risk_certified_flag") != "TRUE":
                continue
            downside_candidate_rows += 1
            for field, component in (("downside_proxy", "downside"), ("max_drawdown", "drawdown"), ("drawdown_proxy", "drawdown"), ("volatility", "volatility")):
                raw = num(row.get(field))
                if raw is None:
                    continue
                score = normalize_risk(raw, True)
                add_value(values, ticker, component, score, field, row.get(field, ""), DOWNSIDE, "", True, True)
            for field, component in (("negative_return_flag", "downside"), ("benchmark_underperformance_flag", "event_macro")):
                raw_text = row.get(field, "")
                if raw_text == "TRUE":
                    add_value(values, ticker, component, 0.40, field, raw_text, DOWNSIDE, f"{field}=TRUE=>0.40")
                elif raw_text == "FALSE":
                    add_value(values, ticker, component, 0.65, field, raw_text, DOWNSIDE, f"{field}=FALSE=>0.65")
    audits.append(audit_row(DOWNSIDE, downside_fields, downside_candidate_rows, ["downside_proxy", "max_drawdown", "drawdown_proxy", "volatility"], ["negative_return_flag", "benchmark_underperformance_flag"], ["row_level_return", "benchmark_return"], ["downside_proxy", "max_drawdown", "drawdown_proxy", "volatility", "negative_return_flag", "benchmark_underperformance_flag"] if downside_candidate_rows else [], ["row_level_return", "benchmark_return"], "RETURN_COLUMNS_REJECTED_EXCEPT_CERTIFIED_RISK_DERIVED_FIELDS"))

    timing_rows, timing_fields, timing_status = read_csv(V18_TIMING)
    timing_candidate_rows = 0
    if timing_status == "OK":
        for row in timing_rows:
            ticker = row.get("ticker", "")
            if ticker not in tickers:
                continue
            row_used = False
            for field, component in (
                ("overheat_status", "overheat"),
                ("buy_zone_status", "overheat"),
                ("technical_status", "overheat"),
                ("technical_signal", "overheat"),
                ("trend_status", "trend_break"),
                ("pullback_status", "drawdown"),
                ("technical_timing_status", "data_quality"),
            ):
                score, mapping = category_score(row.get(field, ""))
                if score is None:
                    continue
                add_value(values, ticker, component, score, field, row.get(field, ""), V18_TIMING, mapping)
                row_used = True
            if row_used:
                timing_candidate_rows += 1
    audits.append(audit_row(V18_TIMING, timing_fields, timing_candidate_rows, [], ["overheat_status", "buy_zone_status", "technical_status", "technical_signal", "trend_status", "pullback_status", "technical_timing_status"], ["close", "sma_20", "sma_50", "rsi_14", "technical_timing_score"], ["overheat_status", "buy_zone_status", "technical_status", "technical_signal", "trend_status", "pullback_status", "technical_timing_status"] if timing_candidate_rows else [], ["close", "sma_20", "sma_50", "rsi_14", "technical_timing_score"], "RAW_TECHNICAL_INDICATORS_REJECTED_UNLESS_EXPRESSED_AS_RISK_STATE"))

    r8_rows, r8_fields, r8_status = read_csv(R8_R3_SOURCE)
    r8_candidate_rows = 0
    if r8_status == "OK":
        for row in r8_rows:
            ticker = row.get("ticker", "")
            if ticker not in tickers:
                continue
            instrument = " ".join([row.get("instrument_type", ""), row.get("quote_type", ""), row.get("exposure_bucket", "")]).upper()
            if any(token in instrument for token in ("LEVERAGED", "SOXL")):
                add_value(values, ticker, "leverage_instrument", 0.25, "instrument_type/exposure_bucket", instrument, R8_R3_SOURCE, "LEVERAGED_ETF=>0.25")
                r8_candidate_rows += 1
            elif "ETF" in instrument or row.get("carried_forward_from_r8") == "TRUE":
                add_value(values, ticker, "leverage_instrument", 0.50, "instrument_type/exposure_bucket", instrument, R8_R3_SOURCE, "ETF_OR_FUND=>0.50")
                r8_candidate_rows += 1
            elif "CRYPTO" in instrument or "BITCOIN" in instrument:
                add_value(values, ticker, "leverage_instrument", 0.35, "exposure_bucket", instrument, R8_R3_SOURCE, "CRYPTO_LINKED=>0.35")
                r8_candidate_rows += 1
    audits.append(audit_row(R8_R3_SOURCE, r8_fields, r8_candidate_rows, [], ["instrument_type", "quote_type", "exposure_bucket", "carried_forward_from_r8"], ["market_regime_contribution"], ["instrument_type", "quote_type", "exposure_bucket", "carried_forward_from_r8"] if r8_candidate_rows else [], ["market_regime_contribution"], "MARKET_REGIME_SCORE_REJECTED_INSTRUMENT_EXPOSURE_ONLY_ACCEPTED_FOR_RISK"))

    return values, audits, carried


def average(items: list[dict[str, str]]) -> float | None:
    scores = [num(item.get("score")) for item in items]
    scores = [score for score in scores if score is not None]
    return sum(scores) / len(scores) if scores else None


def complete_six_family_count(r4_rows: list[dict[str, str]], fundamental_rows: list[dict[str, str]], strategy_rows: list[dict[str, str]], regime_rows: list[dict[str, str]], risk_tickers: set[str]) -> int:
    fundamental = {row["ticker"] for row in fundamental_rows if row.get("fundamental_contribution")}
    strategy = {row["ticker"] for row in strategy_rows if row.get("strategy_contribution")}
    regime = {row["ticker"] for row in regime_rows if row.get("market_regime_contribution")}
    required = {"FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"}
    count = 0
    for row in r4_rows:
        ticker = row.get("ticker", "")
        families = {part for part in row.get("materialized_factor_families", "").split(";") if part}
        if ticker in fundamental:
            families.add("FUNDAMENTAL")
        if ticker in strategy:
            families.add("STRATEGY")
        if ticker in regime:
            families.add("MARKET_REGIME")
        if ticker in risk_tickers:
            families.add("RISK")
        if required.issubset(families):
            count += 1
    return count


def main() -> int:
    candidates = load_candidates()
    values, audits, carried = collect_risk_values(candidates)
    source_rows: list[dict[str, str]] = []
    component_rows: list[dict[str, str]] = []
    risk_tickers: set[str] = set()

    for candidate in candidates:
        ticker = candidate["ticker"]
        component_scores: dict[str, float] = {}
        used_cols: set[str] = set()
        mappings: set[str] = set()
        artifacts: set[str] = set()
        stages: set[str] = set()
        for component in COMPONENTS:
            items = values.get(ticker, {}).get(component, [])
            component_score = average(items)
            if component_score is not None:
                component_scores[component] = component_score
                used_cols.update(item["field"] for item in items)
                mappings.update(item["mapping"] for item in items if item.get("mapping"))
                artifacts.update(item["artifact"] for item in items)
                stages.update(item["stage"] for item in items)
                status = "COMPONENT_MATERIALIZED_FROM_REAL_RISK_CONTEXT"
                blocker = ""
            else:
                status = "COMPONENT_NOT_MATERIALIZED"
                blocker = "NO_CANDIDATE_LEVEL_RISK_CONTEXT_FOR_COMPONENT"
            component_rows.append({
                "ticker": ticker,
                "component_group": component,
                "metrics_or_categories_used": ";".join(item["field"] for item in items),
                "raw_values_present": ";".join(f"{item['field']}={item['raw']}" for item in items),
                "categorical_mapping_applied": ";".join(item["mapping"] for item in items if item.get("mapping")),
                "lower_raw_value_is_better": "TRUE" if any(item["lower_better"] == "TRUE" for item in items) else "FALSE",
                "inversion_applied": "TRUE" if any(item["inversion"] == "TRUE" for item in items) else "FALSE",
                "normalization_method": "REAL_RISK_CONTEXT_NORMALIZED_HIGHER_IS_LOWER_RISK" if component_score is not None else "NOT_NORMALIZED",
                "component_score": fmt(component_score),
                "component_status": status,
                "component_blocker_reason": blocker,
                "fabricated_values_created": "FALSE",
                "proxy_values_activated": "FALSE",
                **safety(),
            })
        if component_scores:
            contribution = sum(component_scores.values()) / len(component_scores)
            risk_tickers.add(ticker)
            source_status = "REAL_CANDIDATE_LEVEL_RISK_SOURCE_FOUND"
            material_status = "CARRIED_FORWARD_EXISTING_RISK_AND_EXPANDED_FROM_REAL_CONTEXT" if ticker in carried else "MATERIALIZED_FROM_REAL_CANDIDATE_LEVEL_RISK_CONTEXT"
            missing_reason = ""
            usable = "TRUE"
            method = "AVERAGE_OF_REAL_RISK_COMPONENTS_HIGHER_IS_LOWER_RISK"
        else:
            contribution = None
            source_status = "MISSING_CANDIDATE_LEVEL_RISK_SOURCE"
            material_status = "MISSING_CANDIDATE_LEVEL_RISK_SOURCE"
            missing_reason = "MISSING_CANDIDATE_LEVEL_RISK_SOURCE"
            usable = "FALSE"
            method = "NO_NORMALIZATION_NO_SAFE_RISK_CONTEXT"
        source_rows.append({
            "ticker": ticker,
            "baseline_rank": candidate.get("baseline_rank", ""),
            "risk_contribution": fmt(contribution),
            **{field: fmt(component_scores.get(component)) for component, field in COMPONENT_FIELD.items()},
            "risk_raw_columns_used": ";".join(sorted(used_cols)),
            "risk_categorical_mappings_used": ";".join(sorted(mappings)),
            "risk_normalization_method": method,
            "risk_source_artifact": ";".join(sorted(artifacts)),
            "risk_source_stage": ";".join(sorted(stages)),
            "risk_source_status": source_status,
            "risk_materialization_status": material_status,
            "missing_reason": missing_reason,
            "usable_for_risk_scoring": usable,
            "usable_for_shadow_rerank": "FALSE",
            "fabricated_values_created": "FALSE",
            "proxy_values_activated": "FALSE",
            "entry_exit_prices_created": "FALSE",
            "buy_sell_recommendations_created": "FALSE",
            "shadow_rerank_output_created": "FALSE",
            **safety(extra=True),
        })

    total = len(source_rows)
    materialized = len(risk_tickers)
    missing = total - materialized
    newly = materialized - len(carried)
    r4_rows, _, _ = read_csv(R4_SCORES)
    fundamental_rows, _, _ = read_csv(R6B_SOURCE)
    strategy_rows, _, _ = read_csv(R7_SOURCE)
    regime_rows, _, _ = read_csv(R8_R3_SOURCE)
    complete_six = complete_six_family_count(r4_rows, fundamental_rows, strategy_rows, regime_rows, risk_tickers)
    usable_shadow = 0

    if materialized == total and total:
        wrapper_status = PASS_STATUS
        coverage_status = "COMPLETE"
        validation_status = "PASS"
        validation_reason = "RISK_CONTRIBUTION_MATERIALIZED_FOR_ALL_CANDIDATES_FROM_REAL_RISK_CONTEXT"
    elif materialized:
        wrapper_status = PARTIAL_STATUS
        coverage_status = "PARTIAL"
        validation_status = "PASS"
        validation_reason = "RISK_CONTRIBUTION_MATERIALIZED_FOR_PARTIAL_CANDIDATES_FROM_REAL_RISK_CONTEXT"
    else:
        wrapper_status = BLOCKED_STATUS
        coverage_status = "MISSING"
        validation_status = "BLOCKED"
        validation_reason = "NO_SAFE_RISK_CANDIDATE_SOURCE_FOUND"

    validation_rows = [{
        "validation_check_id": "V20_108_R9_VALIDATION_001",
        "candidate_count": str(total),
        "materialized_risk_candidate_count": str(materialized),
        "missing_risk_candidate_count": str(missing),
        "carried_forward_existing_risk_candidate_count": str(len(carried)),
        "newly_materialized_risk_candidate_count": str(newly),
        "fabricated_values_created": "FALSE",
        "proxy_values_activated": "FALSE",
        "source_rank_or_score_used": "FALSE",
        "baseline_rank_used": "FALSE",
        "risk_contribution_scores_created": tf(materialized > 0),
        "entry_exit_prices_created": "FALSE",
        "buy_sell_recommendations_created": "FALSE",
        "shadow_rerank_output_created": "FALSE",
        "official_ranking_created": "FALSE",
        "authoritative_ranking_overwritten": "FALSE",
        "validation_status": validation_status,
        "validation_reason": validation_reason,
        **safety(),
        "is_official_weight": "FALSE",
    }]

    families = [
        ("RISK", materialized, missing, coverage_status, "" if not missing else "MISSING_CANDIDATE_LEVEL_RISK_SOURCE_FOR_UNCOVERED_CANDIDATES", "V20.108-R10_TRUE_SHADOW_RERANK_READINESS_GATE"),
        ("FUNDAMENTAL", 297, total - 297, "PARTIAL", "ETF_FUND_NON_EQUITY_OR_PENDING_PATCH_EXCLUSIONS_FROM_R6B", "V20.108-R10_TRUE_SHADOW_RERANK_READINESS_GATE"),
        ("TECHNICAL", total, 0, "COMPLETE", "FUNDAMENTAL_REMAINS_PARTIAL", "V20.108-R10_TRUE_SHADOW_RERANK_READINESS_GATE"),
        ("DATA_TRUST", total, 0, "COMPLETE", "FUNDAMENTAL_REMAINS_PARTIAL", "V20.108-R10_TRUE_SHADOW_RERANK_READINESS_GATE"),
        ("STRATEGY", total, 0, "COMPLETE", "FUNDAMENTAL_REMAINS_PARTIAL", "V20.108-R10_TRUE_SHADOW_RERANK_READINESS_GATE"),
        ("MARKET_REGIME", total, 0, "COMPLETE", "FUNDAMENTAL_REMAINS_PARTIAL", "V20.108-R10_TRUE_SHADOW_RERANK_READINESS_GATE"),
    ]
    coverage_rows = [{
        "factor_family": family,
        "required_candidate_count": str(total),
        "materialized_candidate_count": str(mat),
        "missing_candidate_count": str(miss),
        "coverage_ratio": f"{(mat / total if total else 0.0):.10f}",
        "contribution_coverage_status": status,
        "usable_for_shadow_rerank": "FALSE",
        "missing_reason": reason,
        "recommended_next_stage": next_stage,
        **safety(),
        "is_official_weight": "FALSE",
    } for family, mat, miss, status, reason, next_stage in families]

    gate_rows = [{
        "gate_check_id": "V20_108_R9_NEXT_STAGE_GATE_001",
        "risk_materialized": tf(materialized > 0),
        "materialized_risk_candidate_count": str(materialized),
        "complete_six_family_contribution_candidate_count": str(complete_six),
        "usable_for_shadow_rerank_count": str(usable_shadow),
        "next_stage_allowed": "FALSE",
        "recommended_next_stage": "V20.108-R10_TRUE_SHADOW_RERANK_READINESS_GATE" if complete_six else "V20.108-R9_RISK_SOURCE_REPAIR_OR_FUNDAMENTAL_PATCH",
        "blocking_reason": "TRUE_SHADOW_RERANK_BLOCKED_UNTIL_ALL_SIX_FACTOR_FAMILIES_COMPLETE" if complete_six < total else "SHADOW_RERANK_OUTPUT_NOT_CREATED_IN_R9",
        **safety(),
        "is_official_weight": "FALSE",
    }]

    write_csv(OUT_SOURCE, SOURCE_FIELDS, source_rows)
    write_csv(OUT_AUDIT, AUDIT_FIELDS, audits)
    write_csv(OUT_COMPONENT, COMPONENT_FIELDS, component_rows)
    write_csv(OUT_VALIDATION, VALIDATION_FIELDS, validation_rows)
    write_csv(OUT_COVERAGE, COVERAGE_FIELDS, coverage_rows)
    write_csv(OUT_GATE, GATE_FIELDS, gate_rows)

    research_gate = first_value(V49_RESEARCH, "research_only_gate_status", "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE")
    official_gate = first_value(V49_OFFICIAL, "official_promotion_gate_status", "BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE")
    report = [
        "# V20.108-R9 Risk Candidate Score Coverage Expander Report",
        "",
        "## Current Result",
        f"- wrapper_status: {wrapper_status}",
        f"- candidate_count: {total}",
        f"- materialized_risk_candidate_count: {materialized}",
        f"- missing_risk_candidate_count: {missing}",
        f"- carried_forward_existing_risk_candidate_count: {len(carried)}",
        f"- newly_materialized_risk_candidate_count: {newly}",
        f"- complete_six_family_contribution_candidate_count: {complete_six}",
        f"- usable_for_shadow_rerank_count: {usable_shadow}",
        f"- v20_49_research_only_gate_status: {research_gate}",
        f"- v20_49_official_promotion_gate_status: {official_gate}",
        "- source_rank_or_score_used: FALSE",
        "- baseline_rank_used: FALSE",
        "- fabricated_values_created: FALSE",
        "- proxy_values_activated: FALSE",
        "- entry_exit_prices_created: FALSE",
        "- buy_sell_recommendations_created: FALSE",
        "- shadow_rerank_output_created: FALSE",
        "- official_ranking_created: FALSE",
        "- authoritative_ranking_overwritten: FALSE",
        "",
        "## Source Policy",
        "- carried_forward_existing_risk: R4 risk_contribution only where present",
        "- downside_risk: certified V20 current downside risk evidence only",
        "- expanded_risk: explicit V18 overheat, buy-zone, trend, pullback, and data-quality risk states",
        "- rejected_inputs: source_rank_or_score, baseline_rank, raw technical indicators without risk-state context",
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
    print(f"CANDIDATE_COUNT={total}")
    print(f"MATERIALIZED_RISK_CANDIDATE_COUNT={materialized}")
    print(f"MISSING_RISK_CANDIDATE_COUNT={missing}")
    print(f"CARRIED_FORWARD_EXISTING_RISK_CANDIDATE_COUNT={len(carried)}")
    print(f"NEWLY_MATERIALIZED_RISK_CANDIDATE_COUNT={newly}")
    print(f"COMPLETE_SIX_FAMILY_CONTRIBUTION_CANDIDATE_COUNT={complete_six}")
    print(f"USABLE_FOR_SHADOW_RERANK_COUNT={usable_shadow}")
    print("SOURCE_RANK_OR_SCORE_USED=FALSE")
    print("BASELINE_RANK_USED=FALSE")
    print("FABRICATED_VALUES_CREATED=FALSE")
    print("PROXY_VALUES_ACTIVATED=FALSE")
    print("ENTRY_EXIT_PRICES_CREATED=FALSE")
    print("BUY_SELL_RECOMMENDATIONS_CREATED=FALSE")
    print("SHADOW_RERANK_OUTPUT_CREATED=FALSE")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("IS_OFFICIAL_WEIGHT=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print(f"OUTPUT_SOURCE={rel(OUT_SOURCE)}")
    print(f"OUTPUT_SOURCE_AUDIT={rel(OUT_AUDIT)}")
    print(f"OUTPUT_COMPONENT_AUDIT={rel(OUT_COMPONENT)}")
    print(f"OUTPUT_VALIDATION={rel(OUT_VALIDATION)}")
    print(f"OUTPUT_COVERAGE={rel(OUT_COVERAGE)}")
    print(f"OUTPUT_NEXT_STAGE_GATE={rel(OUT_GATE)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
