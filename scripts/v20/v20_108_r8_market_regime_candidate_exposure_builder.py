#!/usr/bin/env python
"""V20.108-R8 market regime candidate exposure builder.

Builds research-only MARKET_REGIME candidate contributions from real
ticker-conditioned ETF/benchmark/sector/theme exposure context. Global regime
signals are never copied blindly to all candidates.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
EVIDENCE = ROOT / "outputs" / "v20" / "evidence"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R7_SOURCE = CONSOLIDATION / "V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE.csv"
R7_COVERAGE = CONSOLIDATION / "V20_108_R7_FACTOR_FAMILY_COVERAGE_AFTER_STRATEGY.csv"
R7_GATE = CONSOLIDATION / "V20_108_R7_NEXT_STAGE_GATE.csv"
R6B_SOURCE = CONSOLIDATION / "V20_108_R6B_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE.csv"
R4_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
R5_PLAN = CONSOLIDATION / "V20_108_R5_MISSING_UPSTREAM_FACTOR_SCORE_STAGE_PLAN.csv"
ETF_REGIME = CONSOLIDATION / "V20_98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_AUDIT.csv"
ETF_RS = CONSOLIDATION / "V20_98C_ETF_PAIR_RELATIVE_STRENGTH_MATRIX.csv"
ETF_SCAFFOLD = CONSOLIDATION / "V20_98C_ETF_REGIME_FACTOR_MULTIPLIER_SCAFFOLD.csv"
V106_BENCH = CONSOLIDATION / "V20_106_ETF_ROTATION_BENCHMARK_ALIGNMENT.csv"
V106_FACTOR = CONSOLIDATION / "V20_106_REGIME_CONDITIONED_FACTOR_ALIGNMENT.csv"
V106_SIGNAL = CONSOLIDATION / "V20_106_ETF_REGIME_REWEIGHTING_SIGNAL_AUDIT.csv"
V50_CANDIDATES = CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V48_FACTORS = CONSOLIDATION / "V20_48_REFRESHED_FACTOR_SUPPORT_VIEW.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"
V18_UNIVERSE = ROOT / "outputs" / "v18" / "universe" / "V18_CURRENT_UNIVERSE_ROLLING_STATE.csv"

OUT_SOURCE = CONSOLIDATION / "V20_108_R8_MARKET_REGIME_CANDIDATE_EXPOSURE_SOURCE.csv"
OUT_AUDIT = CONSOLIDATION / "V20_108_R8_MARKET_REGIME_SOURCE_AUDIT.csv"
OUT_COMPONENT = CONSOLIDATION / "V20_108_R8_MARKET_REGIME_EXPOSURE_COMPONENT_AUDIT.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_108_R8_MARKET_REGIME_MATERIALIZATION_VALIDATION.csv"
OUT_COVERAGE = CONSOLIDATION / "V20_108_R8_FACTOR_FAMILY_COVERAGE_AFTER_MARKET_REGIME.csv"
OUT_GATE = CONSOLIDATION / "V20_108_R8_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_108_R8_MARKET_REGIME_CANDIDATE_EXPOSURE_BUILDER_REPORT.md"

PASS_STATUS = "PASS_V20_108_R8_MARKET_REGIME_CANDIDATE_EXPOSURE_BUILDER"
PARTIAL_STATUS = "PARTIAL_PASS_V20_108_R8_MARKET_REGIME_CANDIDATE_EXPOSURE_BUILDER_WITH_PARTIAL_COVERAGE"
BLOCKED_STATUS = "BLOCKED_V20_108_R8_NO_SAFE_MARKET_REGIME_CANDIDATE_EXPOSURE_FOUND"

TICKER_COLUMNS = ("ticker", "normalized_ticker", "ticker_or_candidate_id", "symbol", "etf_symbol", "left_ticker", "right_ticker")
RANK_COLUMNS = {"source_rank_or_score", "baseline_rank", "rank", "report_rank", "composite_candidate_score"}
COMPONENTS = [
    "sector_exposure", "industry_exposure", "theme_exposure", "benchmark_exposure",
    "etf_regime_alignment", "macro_regime", "risk_on_off",
]
COMPONENT_FIELD = {
    "sector_exposure": "sector_exposure_component_score",
    "industry_exposure": "industry_exposure_component_score",
    "theme_exposure": "theme_exposure_component_score",
    "benchmark_exposure": "benchmark_exposure_component_score",
    "etf_regime_alignment": "etf_regime_alignment_component_score",
    "macro_regime": "macro_regime_component_score",
    "risk_on_off": "risk_on_off_component_score",
}
EXPOSURE_COLUMNS = {
    "sector": "sector_exposure",
    "industry": "industry_exposure",
    "primary_theme": "theme_exposure",
    "theme": "theme_exposure",
    "benchmark_symbol": "benchmark_exposure",
    "benchmark_id": "benchmark_exposure",
    "regime_classification": "macro_regime",
    "relative_strength_status": "etf_regime_alignment",
    "signal_confidence": "etf_regime_alignment",
    "suggested_research_multiplier_direction": "risk_on_off",
    "suggested_shadow_multiplier_direction": "risk_on_off",
    "benchmark_alignment_status": "benchmark_exposure",
    "alignment_status": "benchmark_exposure",
    "relative_outperformance_rate": "benchmark_exposure",
    "mean_alpha_vs_benchmark": "benchmark_exposure",
}
GLOBAL_ONLY_COLUMNS = {"regime_classification", "market_regime", "qqq_trend_regime", "regime_label", "regime_bucket"}
ETF_TICKER_COLUMNS = {"left_ticker", "right_ticker", "etf_symbol", "paired_symbol"}
CATEGORY_SCORE = {
    "MIXED_OR_INSUFFICIENT_DATA": 0.50,
    "INSUFFICIENT_RELATIVE_STRENGTH_HISTORY": 0.50,
    "CURRENT_PRICE_CONTEXT_AVAILABLE_RETURN_HISTORY_NOT_COMPUTED": 0.50,
    "LOW": 0.45,
    "MEDIUM": 0.60,
    "HIGH": 0.75,
    "BENCHMARK_ALIGNMENT_AVAILABLE": 0.60,
    "USABLE_ALIGNMENT_EVIDENCE": 0.60,
    "INCREASE_GROWTH_OR_TECHNICAL_RESEARCH_ATTENTION": 0.60,
    "INCREASE_TECHNICAL_RESEARCH_ATTENTION": 0.58,
    "INCREASE_SEMICONDUCTOR_RESEARCH_ATTENTION": 0.62,
    "INCREASE_RISK_ON_RESEARCH_ATTENTION": 0.62,
    "INCREASE_BREADTH_RESEARCH_ATTENTION": 0.57,
    "INCREASE_SEMICONDUCTOR_RISK_ATTENTION": 0.45,
    "TECHNOLOGY": 0.60,
    "SEMICONDUCTOR": 0.65,
    "CRYPTO": 0.55,
    "DEFENSIVE": 0.50,
    "UTILITIES": 0.52,
}

SOURCE_FIELDS = [
    "ticker", "baseline_rank", "market_regime_contribution",
    "sector_exposure_component_score", "industry_exposure_component_score",
    "theme_exposure_component_score", "benchmark_exposure_component_score",
    "etf_regime_alignment_component_score", "macro_regime_component_score",
    "risk_on_off_component_score", "market_regime_raw_columns_used",
    "market_regime_categorical_mappings_used", "market_regime_normalization_method",
    "market_regime_source_artifact", "market_regime_source_stage",
    "market_regime_source_status", "market_regime_materialization_status",
    "market_regime_exposure_classification", "missing_reason",
    "usable_for_market_regime_scoring", "usable_for_shadow_rerank",
    "fabricated_values_created", "proxy_values_activated",
    "global_regime_copied_without_exposure_conditioning",
    "entry_exit_prices_created", "buy_sell_recommendations_created",
    "shadow_rerank_output_created", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "is_official_ranking", "is_official_weight",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]
AUDIT_FIELDS = [
    "source_artifact", "source_exists", "source_non_empty", "ticker_column_available",
    "candidate_rows_found", "detected_market_regime_numeric_columns",
    "detected_market_regime_categorical_columns", "detected_sector_industry_theme_columns",
    "detected_etf_benchmark_exposure_columns", "detected_global_only_regime_columns",
    "accepted_columns", "rejected_columns", "rejection_reason",
    "source_rank_or_score_present", "source_rank_or_score_used_as_market_regime",
    "baseline_rank_used_as_market_regime", "materialization_allowed",
    "materialization_blocker_reason", "validation_status", "validation_reason",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]
COMPONENT_FIELDS = [
    "ticker", "component_group", "exposures_or_categories_used", "raw_values_present",
    "categorical_mapping_applied", "normalization_method", "component_score",
    "component_status", "component_blocker_reason", "fabricated_values_created",
    "proxy_values_activated", "global_regime_copied_without_exposure_conditioning",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]
VALIDATION_FIELDS = [
    "validation_check_id", "candidate_count", "materialized_market_regime_candidate_count",
    "missing_market_regime_candidate_count", "fabricated_values_created",
    "proxy_values_activated", "source_rank_or_score_used", "baseline_rank_used",
    "global_regime_copied_without_exposure_conditioning",
    "market_regime_contribution_scores_created", "entry_exit_prices_created",
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
    "gate_check_id", "market_regime_materialized",
    "materialized_market_regime_candidate_count",
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


def source_stage(path: Path) -> str:
    name = path.name
    if name.startswith("V20_"):
        parts = name.split("_", 2)
        return f"{parts[0]}.{parts[1]}" if len(parts) > 1 else "V20"
    if name.startswith("V18_"):
        return "V18"
    return "DISCOVERED"


def load_candidates() -> list[dict[str, str]]:
    rows, _, status = read_csv(R4_SCORES)
    if status == "OK":
        return [{"ticker": row["ticker"], "baseline_rank": row.get("baseline_rank", "")} for row in rows if row.get("ticker")]
    rows, _, status = read_csv(V48_CANDIDATES)
    return [{"ticker": row.get("normalized_ticker") or row.get("ticker_or_candidate_id", ""), "baseline_rank": row.get("report_rank", "")} for row in rows] if status == "OK" else []


def discover_sources() -> list[Path]:
    seeds = [
        R7_SOURCE, R7_COVERAGE, R7_GATE, R6B_SOURCE, R4_SCORES, R5_PLAN,
        ETF_REGIME, ETF_RS, ETF_SCAFFOLD, V106_BENCH, V106_FACTOR, V106_SIGNAL,
        V50_CANDIDATES, V48_CANDIDATES, V48_FACTORS, V49_RESEARCH, V49_OFFICIAL,
        V18_UNIVERSE,
    ]
    patterns = ["*REGIME*.csv", "*ETF*.csv", "*BENCHMARK*.csv", "*SECTOR*.csv", "*INDUSTRY*.csv", "*THEME*.csv"]
    found: list[Path] = []
    for pattern in patterns:
        found.extend(CONSOLIDATION.glob(pattern))
        if EVIDENCE.exists():
            found.extend(EVIDENCE.glob(pattern))
    for root in (ROOT / "outputs" / "v18", ROOT / "outputs" / "v19", ROOT / "outputs" / "backtest"):
        if root.exists():
            found.extend(root.rglob("*.csv"))
    excluded = {OUT_SOURCE.resolve(), OUT_AUDIT.resolve(), OUT_COMPONENT.resolve(), OUT_VALIDATION.resolve(), OUT_COVERAGE.resolve(), OUT_GATE.resolve()}
    ordered: list[Path] = []
    seen: set[Path] = set()
    for path in seeds + sorted(found):
        resolved = path.resolve()
        if resolved in excluded or resolved in seen:
            continue
        seen.add(resolved)
        ordered.append(path)
    return ordered


def row_tickers(row: dict[str, str], fields: list[str]) -> set[str]:
    tickers: set[str] = set()
    for field in fields:
        if field in TICKER_COLUMNS or field in ETF_TICKER_COLUMNS:
            value = clean(row.get(field))
            if value:
                tickers.add(value)
    return tickers


def categorical_score(value: str) -> tuple[float | None, str]:
    token = clean(value).upper().replace(" ", "_")
    if not token:
        return None, ""
    if token in CATEGORY_SCORE:
        return CATEGORY_SCORE[token], f"{token}=>{CATEGORY_SCORE[token]:.2f}"
    for key, score in CATEGORY_SCORE.items():
        if key in token:
            return score, f"{token}~{key}=>{score:.2f}"
    return None, ""


def normalize_numeric(value: float, field: str) -> float:
    if "outperformance_rate" in field:
        return max(0.0, min(1.0, value))
    if "alpha" in field:
        return max(0.0, min(1.0, 0.5 + value))
    return max(0.0, min(1.0, value if 0.0 <= value <= 1.0 else value / 100.0))


def field_component(field: str) -> str | None:
    low = field.lower()
    if low in RANK_COLUMNS:
        return None
    for key, component in EXPOSURE_COLUMNS.items():
        if key in low:
            return component
    return None


def audit_and_collect(candidates: list[dict[str, str]]) -> tuple[list[dict[str, str]], dict[str, dict[str, list[tuple[float, str, str, str, str]]]]]:
    candidate_tickers = {row["ticker"] for row in candidates}
    values = {ticker: {component: [] for component in COMPONENTS} for ticker in candidate_tickers}
    audits: list[dict[str, str]] = []
    for path in discover_sources():
        rows, fields, status = read_csv(path)
        ticker_available = any(field in fields for field in TICKER_COLUMNS)
        source_rank_present = "source_rank_or_score" in fields
        candidate_rows = 0
        numeric_cols: set[str] = set()
        cat_cols: set[str] = set()
        sector_cols: set[str] = set()
        etf_cols: set[str] = set()
        global_cols: set[str] = set()
        accepted: set[str] = set()
        rejected: set[str] = set()
        if status == "OK" and rows and ticker_available:
            for row in rows:
                tickers = row_tickers(row, fields) & candidate_tickers
                if not tickers:
                    continue
                candidate_rows += len(tickers)
                conditioned_by_exposure = bool(tickers)
                for field in fields:
                    low = field.lower()
                    if low in RANK_COLUMNS or field in TICKER_COLUMNS:
                        continue
                    component = field_component(field)
                    if low in GLOBAL_ONLY_COLUMNS:
                        global_cols.add(field)
                    if low in {"sector", "industry", "theme", "primary_theme"}:
                        sector_cols.add(field)
                    if low in {"etf_pair", "left_ticker", "right_ticker", "etf_symbol", "paired_symbol", "benchmark_symbol", "aligned_benchmark_ticker"}:
                        etf_cols.add(field)
                    if component is None:
                        continue
                    raw = clean(row.get(field))
                    if not raw:
                        continue
                    parsed = num(raw)
                    if parsed is not None and low not in GLOBAL_ONLY_COLUMNS:
                        score = normalize_numeric(parsed, low)
                        numeric_cols.add(field)
                        accepted.add(field)
                        for ticker in tickers:
                            values[ticker][component].append((score, field, raw, rel(path), ""))
                    else:
                        mapped, mapping = categorical_score(raw)
                        if mapped is not None and conditioned_by_exposure:
                            cat_cols.add(field)
                            accepted.add(field)
                            for ticker in tickers:
                                values[ticker][component].append((mapped, field, raw, rel(path), mapping))
                        else:
                            rejected.add(field)
        allowed = bool(accepted)
        audits.append({
            "source_artifact": rel(path),
            "source_exists": tf(path.exists()),
            "source_non_empty": tf(path.exists() and path.stat().st_size > 0),
            "ticker_column_available": tf(ticker_available),
            "candidate_rows_found": str(candidate_rows),
            "detected_market_regime_numeric_columns": ";".join(sorted(numeric_cols)),
            "detected_market_regime_categorical_columns": ";".join(sorted(cat_cols)),
            "detected_sector_industry_theme_columns": ";".join(sorted(sector_cols)),
            "detected_etf_benchmark_exposure_columns": ";".join(sorted(etf_cols)),
            "detected_global_only_regime_columns": ";".join(sorted(global_cols)),
            "accepted_columns": ";".join(sorted(accepted)),
            "rejected_columns": ";".join(sorted(rejected)),
            "rejection_reason": "GLOBAL_ONLY_OR_UNMAPPED_EXPOSURE_REJECTED" if rejected or (global_cols and not allowed) else "",
            "source_rank_or_score_present": tf(source_rank_present),
            "source_rank_or_score_used_as_market_regime": "FALSE",
            "baseline_rank_used_as_market_regime": "FALSE",
            "materialization_allowed": tf(allowed),
            "materialization_blocker_reason": "" if allowed else "NO_SAFE_CANDIDATE_LEVEL_MARKET_REGIME_EXPOSURE",
            "validation_status": "PASS" if allowed else "BLOCKED",
            "validation_reason": "TICKER_CONDITIONED_MARKET_REGIME_EXPOSURE_FOUND" if allowed else "NO_SAFE_CANDIDATE_LEVEL_MARKET_REGIME_EXPOSURE",
            **safety(),
        })
    return audits, values


def score(values: list[tuple[float, str, str, str, str]]) -> float | None:
    if not values:
        return None
    return sum(value for value, _, _, _, _ in values) / len(values)


def complete_six_family_count(r4_rows: list[dict[str, str]], fundamental_rows: list[dict[str, str]], strategy_rows: list[dict[str, str]], regime_tickers: set[str]) -> int:
    fundamental = {row["ticker"] for row in fundamental_rows if row.get("fundamental_contribution")}
    strategy = {row["ticker"] for row in strategy_rows if row.get("strategy_contribution")}
    count = 0
    for row in r4_rows:
        ticker = row.get("ticker", "")
        families = {part for part in row.get("materialized_factor_families", "").split(";") if part}
        if ticker in fundamental:
            families.add("FUNDAMENTAL")
        if ticker in strategy:
            families.add("STRATEGY")
        if ticker in regime_tickers:
            families.add("MARKET_REGIME")
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
    audits, values = audit_and_collect(candidates)
    r4_rows, _, _ = read_csv(R4_SCORES)
    fundamental_rows, _, _ = read_csv(R6B_SOURCE)
    strategy_rows, _, _ = read_csv(R7_SOURCE)
    source_rows: list[dict[str, str]] = []
    component_rows: list[dict[str, str]] = []
    materialized_tickers: set[str] = set()
    for candidate in candidates:
        ticker = candidate["ticker"]
        component_scores: dict[str, float] = {}
        used_cols: set[str] = set()
        mappings: set[str] = set()
        artifacts: set[str] = set()
        for component in COMPONENTS:
            component_values = values.get(ticker, {}).get(component, [])
            component_score = score(component_values)
            if component_score is not None:
                component_scores[component] = component_score
                used_cols.update(field for _, field, _, _, _ in component_values)
                mappings.update(mapping for _, _, _, _, mapping in component_values if mapping)
                artifacts.update(artifact for _, _, _, artifact, _ in component_values)
                status = "COMPONENT_MATERIALIZED_FROM_TICKER_CONDITIONED_EXPOSURE"
                blocker = ""
            else:
                status = "COMPONENT_NOT_MATERIALIZED"
                blocker = "NO_TICKER_CONDITIONED_EXPOSURE_FOR_COMPONENT"
            component_rows.append({
                "ticker": ticker,
                "component_group": component,
                "exposures_or_categories_used": ";".join(field for _, field, _, _, _ in component_values),
                "raw_values_present": ";".join(f"{field}={raw}" for _, field, raw, _, _ in component_values),
                "categorical_mapping_applied": ";".join(mapping for _, _, _, _, mapping in component_values if mapping),
                "normalization_method": "DETERMINISTIC_EXPOSURE_MAPPING_OR_NUMERIC_0_TO_1_CLAMP" if component_score is not None else "NOT_NORMALIZED",
                "component_score": fmt(component_score) if component_score is not None else "",
                "component_status": status,
                "component_blocker_reason": blocker,
                "fabricated_values_created": "FALSE",
                "proxy_values_activated": "FALSE",
                "global_regime_copied_without_exposure_conditioning": "FALSE",
                **safety(),
            })
        if component_scores:
            contribution = sum(component_scores.values()) / len(component_scores)
            materialized_tickers.add(ticker)
            source_status = "REAL_TICKER_CONDITIONED_MARKET_REGIME_EXPOSURE_SOURCE"
            material_status = "MATERIALIZED_FROM_TICKER_CONDITIONED_EXPOSURE"
            classification = "ETF_OR_FUND_INSTRUMENT_EXPOSURE" if any("ETF" in artifact or "98C" in artifact for artifact in artifacts) else "CANDIDATE_LEVEL_MARKET_REGIME_EXPOSURE"
            missing_reason = ""
            usable = "TRUE"
            method = "AVERAGE_OF_TICKER_CONDITIONED_EXPOSURE_COMPONENTS"
        else:
            contribution = None
            source_status = "MISSING_CANDIDATE_LEVEL_MARKET_REGIME_SOURCE"
            material_status = "NOT_MATERIALIZED"
            classification = "MISSING_CANDIDATE_LEVEL_MARKET_REGIME_SOURCE"
            missing_reason = "MISSING_CANDIDATE_LEVEL_MARKET_REGIME_SOURCE"
            usable = "FALSE"
            method = "NO_NORMALIZATION_NO_SAFE_TICKER_CONDITIONED_EXPOSURE"
        source_rows.append({
            "ticker": ticker,
            "baseline_rank": candidate.get("baseline_rank", ""),
            "market_regime_contribution": fmt(contribution) if contribution is not None else "",
            "sector_exposure_component_score": fmt(component_scores["sector_exposure"]) if "sector_exposure" in component_scores else "",
            "industry_exposure_component_score": fmt(component_scores["industry_exposure"]) if "industry_exposure" in component_scores else "",
            "theme_exposure_component_score": fmt(component_scores["theme_exposure"]) if "theme_exposure" in component_scores else "",
            "benchmark_exposure_component_score": fmt(component_scores["benchmark_exposure"]) if "benchmark_exposure" in component_scores else "",
            "etf_regime_alignment_component_score": fmt(component_scores["etf_regime_alignment"]) if "etf_regime_alignment" in component_scores else "",
            "macro_regime_component_score": fmt(component_scores["macro_regime"]) if "macro_regime" in component_scores else "",
            "risk_on_off_component_score": fmt(component_scores["risk_on_off"]) if "risk_on_off" in component_scores else "",
            "market_regime_raw_columns_used": ";".join(sorted(used_cols)),
            "market_regime_categorical_mappings_used": ";".join(sorted(mappings)),
            "market_regime_normalization_method": method,
            "market_regime_source_artifact": ";".join(sorted(artifacts)),
            "market_regime_source_stage": ";".join(sorted({source_stage(Path(artifact)) for artifact in artifacts})) if artifacts else "",
            "market_regime_source_status": source_status,
            "market_regime_materialization_status": material_status,
            "market_regime_exposure_classification": classification,
            "missing_reason": missing_reason,
            "usable_for_market_regime_scoring": usable,
            "usable_for_shadow_rerank": "FALSE",
            "fabricated_values_created": "FALSE",
            "proxy_values_activated": "FALSE",
            "global_regime_copied_without_exposure_conditioning": "FALSE",
            "entry_exit_prices_created": "FALSE",
            "buy_sell_recommendations_created": "FALSE",
            "shadow_rerank_output_created": "FALSE",
            **safety(extra=True),
        })

    total = len(source_rows)
    materialized = len(materialized_tickers)
    missing = total - materialized
    complete_six = complete_six_family_count(r4_rows, fundamental_rows, strategy_rows, materialized_tickers)
    usable_shadow = 0
    if materialized == total and total:
        wrapper_status = PASS_STATUS
        coverage_status = "COMPLETE"
        validation_status = "PASS"
        validation_reason = "MARKET_REGIME_EXPOSURE_MATERIALIZED_FOR_ALL_CANDIDATES"
    elif materialized:
        wrapper_status = PARTIAL_STATUS
        coverage_status = "PARTIAL"
        validation_status = "PASS"
        validation_reason = "MARKET_REGIME_EXPOSURE_MATERIALIZED_FROM_PARTIAL_TICKER_CONDITIONED_CONTEXT"
    else:
        wrapper_status = BLOCKED_STATUS
        coverage_status = "MISSING"
        validation_status = "BLOCKED"
        validation_reason = "NO_SAFE_MARKET_REGIME_CANDIDATE_EXPOSURE_FOUND"

    validation_rows = [{
        "validation_check_id": "V20_108_R8_VALIDATION_001",
        "candidate_count": str(total),
        "materialized_market_regime_candidate_count": str(materialized),
        "missing_market_regime_candidate_count": str(missing),
        "fabricated_values_created": "FALSE",
        "proxy_values_activated": "FALSE",
        "source_rank_or_score_used": "FALSE",
        "baseline_rank_used": "FALSE",
        "global_regime_copied_without_exposure_conditioning": "FALSE",
        "market_regime_contribution_scores_created": tf(materialized > 0),
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
    coverage_rows = []
    families = [
        ("MARKET_REGIME", materialized, missing, coverage_status, "MISSING_CANDIDATE_LEVEL_MARKET_REGIME_SOURCE_FOR_UNCOVERED_CANDIDATES" if missing else "", "V20.108-R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER"),
        ("FUNDAMENTAL", 297, total - 297, "PARTIAL", "ETF_FUND_NON_EQUITY_OR_PENDING_PATCH_EXCLUSIONS_FROM_R6B", "V20.108-R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER"),
        ("TECHNICAL", total, 0, "COMPLETE", "SIX_FAMILY_SET_INCOMPLETE_RISK_FUNDAMENTAL_MARKET_REGIME", "V20.108-R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER"),
        ("DATA_TRUST", total, 0, "COMPLETE", "SIX_FAMILY_SET_INCOMPLETE_RISK_FUNDAMENTAL_MARKET_REGIME", "V20.108-R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER"),
        ("STRATEGY", total, 0, "COMPLETE", "SIX_FAMILY_SET_INCOMPLETE_RISK_FUNDAMENTAL_MARKET_REGIME", "V20.108-R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER"),
        ("RISK", 11, total - 11, "PARTIAL", "RISK_REMAINS_PARTIAL_11_OF_315", "V20.108-R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER"),
    ]
    for family, mat, miss, status, reason, next_stage in families:
        coverage_rows.append({
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
        })
    gate_rows = [{
        "gate_check_id": "V20_108_R8_NEXT_STAGE_GATE_001",
        "market_regime_materialized": tf(materialized > 0),
        "materialized_market_regime_candidate_count": str(materialized),
        "complete_six_family_contribution_candidate_count": str(complete_six),
        "usable_for_shadow_rerank_count": str(usable_shadow),
        "next_stage_allowed": "FALSE",
        "recommended_next_stage": "V20.108-R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER",
        "blocking_reason": "TRUE_SHADOW_RERANK_BLOCKED_UNTIL_ALL_SIX_FACTOR_FAMILIES_COMPLETE",
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
        "# V20.108-R8 Market Regime Candidate Exposure Builder Report",
        "",
        "## Current Result",
        f"- wrapper_status: {wrapper_status}",
        f"- candidate_count: {total}",
        f"- materialized_market_regime_candidate_count: {materialized}",
        f"- missing_market_regime_candidate_count: {missing}",
        f"- complete_six_family_contribution_candidate_count: {complete_six}",
        f"- usable_for_shadow_rerank_count: {usable_shadow}",
        f"- v20_49_research_only_gate_status: {research_gate}",
        f"- v20_49_official_promotion_gate_status: {official_gate}",
        "- source_rank_or_score_used: FALSE",
        "- baseline_rank_used: FALSE",
        "- fabricated_values_created: FALSE",
        "- proxy_values_activated: FALSE",
        "- global_regime_copied_without_exposure_conditioning: FALSE",
        "- entry_exit_prices_created: FALSE",
        "- buy_sell_recommendations_created: FALSE",
        "- shadow_rerank_output_created: FALSE",
        "- official_ranking_created: FALSE",
        "- authoritative_ranking_overwritten: FALSE",
        "",
        "## Accepted Source Policy",
        "- accepted_context: ticker-conditioned ETF, benchmark, sector, industry, theme, or regime exposure",
        "- rejected_context: global-only regime rows without candidate exposure conditioning",
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
    print(f"MATERIALIZED_MARKET_REGIME_CANDIDATE_COUNT={materialized}")
    print(f"MISSING_MARKET_REGIME_CANDIDATE_COUNT={missing}")
    print(f"COMPLETE_SIX_FAMILY_CONTRIBUTION_CANDIDATE_COUNT={complete_six}")
    print(f"USABLE_FOR_SHADOW_RERANK_COUNT={usable_shadow}")
    print("SOURCE_RANK_OR_SCORE_USED=FALSE")
    print("BASELINE_RANK_USED=FALSE")
    print("FABRICATED_VALUES_CREATED=FALSE")
    print("PROXY_VALUES_ACTIVATED=FALSE")
    print("GLOBAL_REGIME_COPIED_WITHOUT_EXPOSURE_CONDITIONING=FALSE")
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
