#!/usr/bin/env python
"""V20.108-R7 strategy candidate score source builder.

Discovers candidate-level strategy/setup context and materializes research-only
strategy_contribution only from accepted real ticker-level strategy/setup
columns or explicitly audited categorical mappings.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R6B_SOURCE = CONSOLIDATION / "V20_108_R6B_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE.csv"
R6B_VALIDATION = CONSOLIDATION / "V20_108_R6B_FUNDAMENTAL_MATERIALIZATION_VALIDATION.csv"
R6B_COVERAGE = CONSOLIDATION / "V20_108_R6B_FACTOR_FAMILY_COVERAGE_AFTER_FUNDAMENTAL.csv"
R6B_GATE = CONSOLIDATION / "V20_108_R6B_NEXT_STAGE_GATE.csv"
R4_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
R5_PLAN = CONSOLIDATION / "V20_108_R5_MISSING_UPSTREAM_FACTOR_SCORE_STAGE_PLAN.csv"
V50_ENTRY = CONSOLIDATION / "V20_50_ENTRY_STRATEGY_RESEARCH_CONTEXT_PACKET.csv"
V50_CANDIDATES = CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V48_FACTORS = CONSOLIDATION / "V20_48_REFRESHED_FACTOR_SUPPORT_VIEW.csv"
V77_BUY_ZONE = CONSOLIDATION / "V20_77_DYNAMIC_BUY_ZONE_DISTANCE.csv"
V77_R1_BUY_ZONE = CONSOLIDATION / "V20_77_R1_REAL_TECHNICAL_BUY_ZONE_REFRESH.csv"
V78_TECH_RECOMPUTE = CONSOLIDATION / "V20_78_PRICE_SENSITIVE_TECHNICAL_FACTOR_RECOMPUTE.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"
V18_TIMING = ROOT / "outputs" / "v18" / "technical_timing" / "V18_6A_CURRENT_TECHNICAL_TIMING.csv"

OUT_SOURCE = CONSOLIDATION / "V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE.csv"
OUT_COLUMN_AUDIT = CONSOLIDATION / "V20_108_R7_STRATEGY_SOURCE_COLUMN_AUDIT.csv"
OUT_COMPONENT = CONSOLIDATION / "V20_108_R7_STRATEGY_SCORE_COMPONENT_AUDIT.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_108_R7_STRATEGY_MATERIALIZATION_VALIDATION.csv"
OUT_COVERAGE = CONSOLIDATION / "V20_108_R7_FACTOR_FAMILY_COVERAGE_AFTER_STRATEGY.csv"
OUT_GATE = CONSOLIDATION / "V20_108_R7_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE_BUILDER_REPORT.md"

PASS_STATUS = "PASS_V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE_BUILDER"
PARTIAL_STATUS = "PARTIAL_PASS_V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE_BUILDER_WITH_PARTIAL_COVERAGE"
BLOCKED_STATUS = "BLOCKED_V20_108_R7_NO_SAFE_STRATEGY_CANDIDATE_SOURCE_FOUND"

TICKER_COLUMNS = ("ticker", "normalized_ticker", "ticker_or_candidate_id", "symbol", "yf_ticker")
RANK_COLUMNS = {"source_rank_or_score", "baseline_rank", "rank", "report_rank", "composite_candidate_score", "factor_score"}
COMPONENTS = [
    "breakout", "pullback", "entry_setup", "buy_zone",
    "relative_strength", "trend", "volume_confirmation", "overheat_penalty",
]
COMPONENT_OUTPUT = {
    "breakout": "breakout_component_score",
    "pullback": "pullback_component_score",
    "entry_setup": "entry_setup_component_score",
    "buy_zone": "buy_zone_component_score",
    "relative_strength": "relative_strength_component_score",
    "trend": "trend_component_score",
    "volume_confirmation": "volume_confirmation_component_score",
    "overheat_penalty": "overheat_penalty_component_score",
}
ACCEPTED_NUMERIC_COMPONENT = {
    "technical_timing_score": "entry_setup",
    "entry_timing_quality": "entry_setup",
    "entry_setup_quality": "entry_setup",
    "setup_validity": "entry_setup",
    "buy_zone_distance": "buy_zone",
    "breakout_quality": "breakout",
    "momentum_breakout": "breakout",
    "pullback_quality": "pullback",
    "relative_strength": "relative_strength",
    "rs_score": "relative_strength",
    "trend_continuation": "trend",
    "trend_reclaim": "trend",
    "ma20_pullback": "pullback",
    "ma25_pullback": "pullback",
    "ma50_support": "pullback",
    "volume_confirmation": "volume_confirmation",
    "overheat_penalty": "overheat_penalty",
}
ACCEPTED_CATEGORICAL_COMPONENT = {
    "technical_timing_status": "entry_setup",
    "technical_status": "entry_setup",
    "technical_signal": "entry_setup",
    "execution_status": "entry_setup",
    "buy_zone_status": "buy_zone",
    "pullback_status": "pullback",
    "overheat_status": "overheat_penalty",
    "breakout_status": "breakout",
    "setup_status": "entry_setup",
    "entry_setup_status": "entry_setup",
    "entry_timing_status": "entry_setup",
}
RAW_TECHNICAL_ONLY_TERMS = [
    "sma", "ema", "rsi", "macd", "bb_", "bollinger", "close", "latest_price",
    "return_", "distance_to", "volume_ratio", "trend_status", "technical_timing_score_raw",
]
CATEGORICAL_MAPPING = {
    "IN_BUY_ZONE": 0.90,
    "NEAR_BUY_ZONE": 0.70,
    "VALID_PULLBACK": 0.80,
    "BREAKOUT_CONFIRMED": 0.90,
    "OVERHEATED": 0.15,
    "OVERHEAT_REVIEW": 0.20,
    "FAR_ABOVE_BUY_ZONE": 0.20,
    "NOT_BUY_ZONE_OVERHEAT_REVIEW": 0.20,
    "TREND_BROKEN": 0.15,
    "DEEP_PULLBACK_REVIEW": 0.45,
    "NO_VALID_SETUP": 0.10,
    "REVIEW_ONLY": 0.50,
    "READY": 0.85,
    "EXECUTION_READY": 0.85,
    "PULLBACK_WATCH": 0.70,
    "WATCH_POSITIVE": 0.75,
    "BB_NEAR_LOWER": 0.75,
    "BB_BELOW_LOWER": 0.55,
    "BB_LOWER_HALF": 0.65,
    "BB_UPPER_HALF": 0.35,
    "TECH_TIMING_WATCH_POSITIVE": 0.75,
    "TECH_TIMING_PULLBACK_WATCH": 0.70,
    "TECH_TIMING_OVERHEAT_AVOID_CHASE": 0.15,
    "TECH_TIMING_NEUTRAL": 0.50,
    "NONE": 0.80,
}

SOURCE_FIELDS = [
    "ticker", "baseline_rank", "strategy_contribution",
    "breakout_component_score", "pullback_component_score",
    "entry_setup_component_score", "buy_zone_component_score",
    "relative_strength_component_score", "trend_component_score",
    "volume_confirmation_component_score", "overheat_penalty_component_score",
    "strategy_raw_columns_used", "strategy_categorical_mappings_used",
    "strategy_normalization_method", "strategy_source_artifact",
    "strategy_source_stage", "strategy_source_status",
    "strategy_materialization_status", "missing_reason",
    "usable_for_strategy_scoring", "usable_for_shadow_rerank",
    "fabricated_values_created", "proxy_values_activated",
    "entry_exit_prices_created", "buy_sell_recommendations_created",
    "shadow_rerank_output_created", "research_only",
    "official_promotion_allowed", "official_recommendation_created",
    "is_official_ranking", "is_official_weight", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]
COLUMN_AUDIT_FIELDS = [
    "source_artifact", "source_exists", "source_non_empty",
    "ticker_column_available", "candidate_rows_found",
    "detected_strategy_numeric_columns", "detected_strategy_categorical_columns",
    "detected_raw_technical_only_columns", "accepted_columns", "rejected_columns",
    "rejection_reason", "source_rank_or_score_present",
    "source_rank_or_score_used_as_strategy", "baseline_rank_used_as_strategy",
    "materialization_allowed", "materialization_blocker_reason",
    "validation_status", "validation_reason", "research_only",
    "official_promotion_allowed", "official_recommendation_created",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]
COMPONENT_FIELDS = [
    "ticker", "component_group", "metrics_or_categories_used", "raw_values_present",
    "categorical_mapping_applied", "normalization_method", "component_score",
    "component_status", "component_blocker_reason", "fabricated_values_created",
    "proxy_values_activated", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]
VALIDATION_FIELDS = [
    "validation_check_id", "candidate_count", "materialized_strategy_candidate_count",
    "missing_strategy_candidate_count", "fabricated_values_created",
    "proxy_values_activated", "source_rank_or_score_used", "baseline_rank_used",
    "strategy_contribution_scores_created", "entry_exit_prices_created",
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
    "gate_check_id", "strategy_materialized", "materialized_strategy_candidate_count",
    "complete_six_family_contribution_candidate_count", "usable_for_shadow_rerank_count",
    "next_stage_allowed", "recommended_next_stage", "blocking_reason",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
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


def ticker_value(row: dict[str, str]) -> str:
    for key in TICKER_COLUMNS:
        value = clean(row.get(key))
        if value:
            return value
    return ""


def source_stage(path: Path) -> str:
    name = path.name
    if name.startswith("V20_"):
        parts = name.split("_", 2)
        return f"{parts[0]}.{parts[1]}" if len(parts) > 1 else "V20"
    if name.startswith("V18_"):
        return "V18"
    if name.startswith("V19_"):
        return "V19"
    return "DISCOVERED"


def load_candidates() -> list[dict[str, str]]:
    rows, _, status = read_csv(R4_SCORES)
    if status == "OK" and rows:
        return [{"ticker": row["ticker"], "baseline_rank": row.get("baseline_rank", "")} for row in rows if row.get("ticker")]
    rows, _, status = read_csv(V48_CANDIDATES)
    if status == "OK":
        return [{"ticker": row.get("normalized_ticker") or row.get("ticker_or_candidate_id", ""), "baseline_rank": row.get("report_rank", "")} for row in rows]
    return []


def discover_sources() -> list[Path]:
    seeds = [
        R6B_SOURCE, R6B_VALIDATION, R6B_COVERAGE, R6B_GATE, R4_SCORES, R5_PLAN,
        V50_ENTRY, V50_CANDIDATES, V48_CANDIDATES, V48_FACTORS, V77_BUY_ZONE,
        V77_R1_BUY_ZONE, V78_TECH_RECOMPUTE, V49_RESEARCH, V49_OFFICIAL, V18_TIMING,
    ]
    patterns = [
        "*STRATEGY*.csv", "*ENTRY*.csv", "*BUY_ZONE*.csv", "*BREAKOUT*.csv",
        "*PULLBACK*.csv", "*RELATIVE_STRENGTH*.csv", "*RS*.csv", "*TREND*.csv",
        "*VOLUME*.csv",
    ]
    found: list[Path] = []
    for pattern in patterns:
        found.extend(CONSOLIDATION.glob(pattern))
    for root in (ROOT / "outputs" / "v18", ROOT / "outputs" / "v19", ROOT / "outputs" / "backtest"):
        if root.exists():
            found.extend(root.rglob("*.csv"))
    excluded = {OUT_SOURCE.resolve(), OUT_COLUMN_AUDIT.resolve(), OUT_COMPONENT.resolve(), OUT_VALIDATION.resolve(), OUT_COVERAGE.resolve(), OUT_GATE.resolve()}
    ordered: list[Path] = []
    seen: set[Path] = set()
    for path in seeds + sorted(found):
        resolved = path.resolve()
        if resolved in excluded or resolved in seen:
            continue
        seen.add(resolved)
        ordered.append(path)
    return ordered


def raw_technical_only(column: str) -> bool:
    name = column.lower()
    return any(term in name for term in RAW_TECHNICAL_ONLY_TERMS)


def accepted_numeric(column: str) -> str | None:
    name = column.lower()
    if name in ACCEPTED_NUMERIC_COMPONENT:
        return ACCEPTED_NUMERIC_COMPONENT[name]
    for key, component in ACCEPTED_NUMERIC_COMPONENT.items():
        if key in name and not raw_technical_only(name):
            return component
    return None


def accepted_categorical(column: str) -> str | None:
    name = column.lower()
    if name in ACCEPTED_CATEGORICAL_COMPONENT:
        return ACCEPTED_CATEGORICAL_COMPONENT[name]
    return None


def categorical_score(value: str) -> tuple[float | None, str]:
    token = clean(value).upper().replace(" ", "_")
    if not token:
        return None, ""
    if token in CATEGORICAL_MAPPING:
        return CATEGORICAL_MAPPING[token], f"{token}=>{CATEGORICAL_MAPPING[token]:.2f}"
    for key, mapped in CATEGORICAL_MAPPING.items():
        if key in token:
            return mapped, f"{token}~{key}=>{mapped:.2f}"
    return None, ""


def audit_and_collect(candidates: list[dict[str, str]]) -> tuple[list[dict[str, str]], dict[str, dict[str, list[tuple[float, str, str, str, str]]]]]:
    candidate_tickers = {row["ticker"] for row in candidates}
    component_values: dict[str, dict[str, list[tuple[float, str, str, str, str]]]] = {
        ticker: {component: [] for component in COMPONENTS} for ticker in candidate_tickers
    }
    audits: list[dict[str, str]] = []
    for path in discover_sources():
        rows, fields, status = read_csv(path)
        ticker_available = any(field in fields for field in TICKER_COLUMNS)
        source_rank_present = "source_rank_or_score" in fields
        candidate_rows = 0
        detected_numeric: set[str] = set()
        detected_categorical: set[str] = set()
        detected_raw: set[str] = set()
        accepted: set[str] = set()
        rejected: set[str] = set()
        if status == "OK" and rows and ticker_available:
            for row in rows:
                ticker = ticker_value(row)
                if ticker not in candidate_tickers:
                    continue
                candidate_rows += 1
                for field in fields:
                    low = field.lower()
                    if low in RANK_COLUMNS or field in TICKER_COLUMNS:
                        continue
                    value = clean(row.get(field))
                    numeric_component = accepted_numeric(field)
                    categorical_component = accepted_categorical(field)
                    if numeric_component and value:
                        parsed = num(value)
                        if parsed is not None:
                            detected_numeric.add(field)
                            accepted.add(field)
                            component_values[ticker][numeric_component].append((parsed, field, value, rel(path), ""))
                        else:
                            rejected.add(field)
                    elif categorical_component and value:
                        mapped, mapping_text = categorical_score(value)
                        if mapped is not None:
                            detected_categorical.add(field)
                            accepted.add(field)
                            component_values[ticker][categorical_component].append((mapped, field, value, rel(path), mapping_text))
                        else:
                            rejected.add(field)
                    elif raw_technical_only(field):
                        detected_raw.add(field)
                        rejected.add(field)
        allowed = bool(accepted and candidate_rows)
        blocker = "" if allowed else "NO_SAFE_CANDIDATE_LEVEL_STRATEGY_SETUP_COLUMNS"
        rejection_reason = "RAW_TECHNICAL_ONLY_OR_NOT_CANDIDATE_LEVEL_STRATEGY_CONTEXT" if rejected else ""
        audits.append({
            "source_artifact": rel(path),
            "source_exists": tf(path.exists()),
            "source_non_empty": tf(path.exists() and path.stat().st_size > 0),
            "ticker_column_available": tf(ticker_available),
            "candidate_rows_found": str(candidate_rows),
            "detected_strategy_numeric_columns": ";".join(sorted(detected_numeric)),
            "detected_strategy_categorical_columns": ";".join(sorted(detected_categorical)),
            "detected_raw_technical_only_columns": ";".join(sorted(detected_raw)),
            "accepted_columns": ";".join(sorted(accepted)),
            "rejected_columns": ";".join(sorted(rejected)),
            "rejection_reason": rejection_reason,
            "source_rank_or_score_present": tf(source_rank_present),
            "source_rank_or_score_used_as_strategy": "FALSE",
            "baseline_rank_used_as_strategy": "FALSE",
            "materialization_allowed": tf(allowed),
            "materialization_blocker_reason": blocker,
            "validation_status": "PASS" if allowed else "BLOCKED",
            "validation_reason": "REAL_CANDIDATE_LEVEL_STRATEGY_SETUP_CONTEXT_COLUMNS_FOUND" if allowed else blocker,
            **safety(),
        })
    return audits, component_values


def component_score(values: list[tuple[float, str, str, str, str]]) -> float | None:
    if not values:
        return None
    nums = [value for value, _, _, _, _ in values]
    return max(0.0, min(1.0, sum(nums) / len(nums) / (100.0 if max(nums) > 1.0 else 1.0)))


def complete_six_family_count(r4_rows: list[dict[str, str]], fundamental_rows: list[dict[str, str]], strategy_tickers: set[str]) -> int:
    fundamental = {row["ticker"] for row in fundamental_rows if row.get("fundamental_contribution")}
    count = 0
    for row in r4_rows:
        ticker = row.get("ticker", "")
        families = {part for part in row.get("materialized_factor_families", "").split(";") if part}
        if ticker in fundamental:
            families.add("FUNDAMENTAL")
        if ticker in strategy_tickers:
            families.add("STRATEGY")
        if {"FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"}.issubset(families):
            count += 1
    return count


def first_value(path: Path, field: str, default: str) -> str:
    rows, _, status = read_csv(path)
    if status == "OK" and rows:
        return rows[0].get(field, default) or default
    return default


def main() -> int:
    candidates = load_candidates()
    column_audits, component_values = audit_and_collect(candidates)
    r4_rows, _, _ = read_csv(R4_SCORES)
    fundamental_rows, _, _ = read_csv(R6B_SOURCE)
    source_rows: list[dict[str, str]] = []
    component_rows: list[dict[str, str]] = []
    materialized_tickers: set[str] = set()
    for candidate in candidates:
        ticker = candidate["ticker"]
        scores: dict[str, float] = {}
        used_columns: set[str] = set()
        mappings: set[str] = set()
        artifacts: set[str] = set()
        for component in COMPONENTS:
            values = component_values.get(ticker, {}).get(component, [])
            score = component_score(values)
            if score is not None:
                scores[component] = score
                used_columns.update(field for _, field, _, _, _ in values)
                mappings.update(mapping for _, _, _, _, mapping in values if mapping)
                artifacts.update(artifact for _, _, _, artifact, _ in values)
                status = "COMPONENT_MATERIALIZED_FROM_REAL_STRATEGY_SETUP_CONTEXT"
                blocker = ""
            else:
                status = "COMPONENT_NOT_MATERIALIZED"
                blocker = "NO_SAFE_CANDIDATE_LEVEL_STRATEGY_SETUP_CONTEXT_FOR_COMPONENT"
            component_rows.append({
                "ticker": ticker,
                "component_group": component,
                "metrics_or_categories_used": ";".join(field for _, field, _, _, _ in values),
                "raw_values_present": ";".join(f"{field}={raw}" for _, field, raw, _, _ in values),
                "categorical_mapping_applied": ";".join(mapping for _, _, _, _, mapping in values if mapping),
                "normalization_method": "DIRECT_0_TO_1_CATEGORICAL_MAPPING_OR_PERCENT_SCORE_SCALING" if score is not None else "NOT_NORMALIZED",
                "component_score": fmt(score) if score is not None else "",
                "component_status": status,
                "component_blocker_reason": blocker,
                "fabricated_values_created": "FALSE",
                "proxy_values_activated": "FALSE",
                **safety(),
            })
        if scores:
            contribution = sum(scores.values()) / len(scores)
            materialized_tickers.add(ticker)
            source_status = "REAL_CANDIDATE_LEVEL_STRATEGY_SETUP_SOURCE"
            material_status = "MATERIALIZED_FROM_REAL_CANDIDATE_LEVEL_STRATEGY_SETUP_CONTEXT"
            missing_reason = ""
            usable = "TRUE"
            norm_method = "AVERAGE_OF_AVAILABLE_STRATEGY_SETUP_COMPONENTS_FROM_REAL_CANDIDATE_LEVEL_COLUMNS"
        else:
            contribution = None
            source_status = "MISSING_CANDIDATE_LEVEL_STRATEGY_SOURCE"
            material_status = "NOT_MATERIALIZED"
            missing_reason = "MISSING_CANDIDATE_LEVEL_STRATEGY_SOURCE"
            usable = "FALSE"
            norm_method = "NO_NORMALIZATION_NO_SAFE_STRATEGY_SOURCE"
        source_rows.append({
            "ticker": ticker,
            "baseline_rank": candidate.get("baseline_rank", ""),
            "strategy_contribution": fmt(contribution) if contribution is not None else "",
            "breakout_component_score": fmt(scores["breakout"]) if "breakout" in scores else "",
            "pullback_component_score": fmt(scores["pullback"]) if "pullback" in scores else "",
            "entry_setup_component_score": fmt(scores["entry_setup"]) if "entry_setup" in scores else "",
            "buy_zone_component_score": fmt(scores["buy_zone"]) if "buy_zone" in scores else "",
            "relative_strength_component_score": fmt(scores["relative_strength"]) if "relative_strength" in scores else "",
            "trend_component_score": fmt(scores["trend"]) if "trend" in scores else "",
            "volume_confirmation_component_score": fmt(scores["volume_confirmation"]) if "volume_confirmation" in scores else "",
            "overheat_penalty_component_score": fmt(scores["overheat_penalty"]) if "overheat_penalty" in scores else "",
            "strategy_raw_columns_used": ";".join(sorted(used_columns)),
            "strategy_categorical_mappings_used": ";".join(sorted(mappings)),
            "strategy_normalization_method": norm_method,
            "strategy_source_artifact": ";".join(sorted(artifacts)),
            "strategy_source_stage": ";".join(sorted({source_stage(Path(artifact)) for artifact in artifacts})) if artifacts else "",
            "strategy_source_status": source_status,
            "strategy_materialization_status": material_status,
            "missing_reason": missing_reason,
            "usable_for_strategy_scoring": usable,
            "usable_for_shadow_rerank": "FALSE",
            "fabricated_values_created": "FALSE",
            "proxy_values_activated": "FALSE",
            "entry_exit_prices_created": "FALSE",
            "buy_sell_recommendations_created": "FALSE",
            "shadow_rerank_output_created": "FALSE",
            **safety(extra=True),
        })

    total = len(source_rows)
    materialized = len(materialized_tickers)
    missing = total - materialized
    complete_six = complete_six_family_count(r4_rows, fundamental_rows, materialized_tickers)
    usable_shadow = 0
    if materialized == total and total:
        wrapper_status = PASS_STATUS
        coverage_status = "COMPLETE"
        validation_status = "PASS"
        validation_reason = "REAL_CANDIDATE_LEVEL_STRATEGY_SETUP_CONTEXT_MATERIALIZED_FOR_ALL_CANDIDATES"
    elif materialized:
        wrapper_status = PARTIAL_STATUS
        coverage_status = "PARTIAL"
        validation_status = "PASS"
        validation_reason = "REAL_CANDIDATE_LEVEL_STRATEGY_SETUP_CONTEXT_MATERIALIZED_WITH_PARTIAL_COVERAGE"
    else:
        wrapper_status = BLOCKED_STATUS
        coverage_status = "MISSING"
        validation_status = "BLOCKED"
        validation_reason = "NO_SAFE_STRATEGY_CANDIDATE_SOURCE_FOUND"

    validation_rows = [{
        "validation_check_id": "V20_108_R7_VALIDATION_001",
        "candidate_count": str(total),
        "materialized_strategy_candidate_count": str(materialized),
        "missing_strategy_candidate_count": str(missing),
        "fabricated_values_created": "FALSE",
        "proxy_values_activated": "FALSE",
        "source_rank_or_score_used": "FALSE",
        "baseline_rank_used": "FALSE",
        "strategy_contribution_scores_created": tf(materialized > 0),
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

    coverage_rows = [
        {
            "factor_family": "STRATEGY",
            "required_candidate_count": str(total),
            "materialized_candidate_count": str(materialized),
            "missing_candidate_count": str(missing),
            "coverage_ratio": f"{(materialized / total if total else 0.0):.10f}",
            "contribution_coverage_status": coverage_status,
            "usable_for_shadow_rerank": "FALSE",
            "missing_reason": "" if not missing else "MISSING_CANDIDATE_LEVEL_STRATEGY_SOURCE_FOR_UNCOVERED_CANDIDATES",
            "recommended_next_stage": "V20.108-R8_MARKET_REGIME_CANDIDATE_EXPOSURE_BUILDER",
            **safety(),
            "is_official_weight": "FALSE",
        },
        {
            "factor_family": "FUNDAMENTAL",
            "required_candidate_count": str(total),
            "materialized_candidate_count": "297",
            "missing_candidate_count": str(total - 297),
            "coverage_ratio": f"{(297 / total if total else 0.0):.10f}",
            "contribution_coverage_status": "PARTIAL",
            "usable_for_shadow_rerank": "FALSE",
            "missing_reason": "ETF_FUND_NON_EQUITY_OR_PENDING_PATCH_EXCLUSIONS_FROM_R6B",
            "recommended_next_stage": "V20.108-R8_MARKET_REGIME_CANDIDATE_EXPOSURE_BUILDER",
            **safety(),
            "is_official_weight": "FALSE",
        },
        {
            "factor_family": "TECHNICAL",
            "required_candidate_count": str(total),
            "materialized_candidate_count": str(total),
            "missing_candidate_count": "0",
            "coverage_ratio": "1.0000000000",
            "contribution_coverage_status": "COMPLETE",
            "usable_for_shadow_rerank": "FALSE",
            "missing_reason": "SIX_FAMILY_SET_INCOMPLETE_RISK_MARKET_REGIME",
            "recommended_next_stage": "V20.108-R8_MARKET_REGIME_CANDIDATE_EXPOSURE_BUILDER",
            **safety(),
            "is_official_weight": "FALSE",
        },
        {
            "factor_family": "DATA_TRUST",
            "required_candidate_count": str(total),
            "materialized_candidate_count": str(total),
            "missing_candidate_count": "0",
            "coverage_ratio": "1.0000000000",
            "contribution_coverage_status": "COMPLETE",
            "usable_for_shadow_rerank": "FALSE",
            "missing_reason": "SIX_FAMILY_SET_INCOMPLETE_RISK_MARKET_REGIME",
            "recommended_next_stage": "V20.108-R8_MARKET_REGIME_CANDIDATE_EXPOSURE_BUILDER",
            **safety(),
            "is_official_weight": "FALSE",
        },
        {
            "factor_family": "RISK",
            "required_candidate_count": str(total),
            "materialized_candidate_count": "11",
            "missing_candidate_count": str(total - 11),
            "coverage_ratio": f"{(11 / total if total else 0.0):.10f}",
            "contribution_coverage_status": "PARTIAL",
            "usable_for_shadow_rerank": "FALSE",
            "missing_reason": "RISK_REMAINS_PARTIAL_11_OF_315",
            "recommended_next_stage": "V20.108-R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER",
            **safety(),
            "is_official_weight": "FALSE",
        },
        {
            "factor_family": "MARKET_REGIME",
            "required_candidate_count": str(total),
            "materialized_candidate_count": "0",
            "missing_candidate_count": str(total),
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
        "gate_check_id": "V20_108_R7_NEXT_STAGE_GATE_001",
        "strategy_materialized": tf(materialized > 0),
        "materialized_strategy_candidate_count": str(materialized),
        "complete_six_family_contribution_candidate_count": str(complete_six),
        "usable_for_shadow_rerank_count": str(usable_shadow),
        "next_stage_allowed": "FALSE",
        "recommended_next_stage": "V20.108-R8_MARKET_REGIME_CANDIDATE_EXPOSURE_BUILDER",
        "blocking_reason": "TRUE_SHADOW_RERANK_BLOCKED_UNTIL_ALL_SIX_FACTOR_FAMILIES_COMPLETE",
        **safety(),
        "is_official_weight": "FALSE",
    }]

    write_csv(OUT_SOURCE, SOURCE_FIELDS, source_rows)
    write_csv(OUT_COLUMN_AUDIT, COLUMN_AUDIT_FIELDS, column_audits)
    write_csv(OUT_COMPONENT, COMPONENT_FIELDS, component_rows)
    write_csv(OUT_VALIDATION, VALIDATION_FIELDS, validation_rows)
    write_csv(OUT_COVERAGE, COVERAGE_FIELDS, coverage_rows)
    write_csv(OUT_GATE, GATE_FIELDS, gate_rows)

    research_gate = first_value(V49_RESEARCH, "research_only_gate_status", "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE")
    official_gate = first_value(V49_OFFICIAL, "official_promotion_gate_status", "BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE")
    report = [
        "# V20.108-R7 Strategy Candidate Score Source Builder Report",
        "",
        "## Current Result",
        f"- wrapper_status: {wrapper_status}",
        f"- candidate_count: {total}",
        f"- materialized_strategy_candidate_count: {materialized}",
        f"- missing_strategy_candidate_count: {missing}",
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
        "## Accepted Source Policy",
        "- accepted_context: candidate-level strategy/setup/timing columns and audited categorical mappings",
        "- rejected_context: raw technical-only indicator columns without strategy/setup signal context",
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
    print(f"MATERIALIZED_STRATEGY_CANDIDATE_COUNT={materialized}")
    print(f"MISSING_STRATEGY_CANDIDATE_COUNT={missing}")
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
    print(f"OUTPUT_SCORE_SOURCE={rel(OUT_SOURCE)}")
    print(f"OUTPUT_COLUMN_AUDIT={rel(OUT_COLUMN_AUDIT)}")
    print(f"OUTPUT_COMPONENT_AUDIT={rel(OUT_COMPONENT)}")
    print(f"OUTPUT_VALIDATION={rel(OUT_VALIDATION)}")
    print(f"OUTPUT_COVERAGE={rel(OUT_COVERAGE)}")
    print(f"OUTPUT_NEXT_STAGE_GATE={rel(OUT_GATE)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
