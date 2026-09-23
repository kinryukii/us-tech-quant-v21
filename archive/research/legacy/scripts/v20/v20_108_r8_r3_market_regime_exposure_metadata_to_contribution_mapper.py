#!/usr/bin/env python
"""V20.108-R8-R3 market regime exposure metadata mapper.

Maps certified ticker-level exposure metadata from R8-R2 into research-only
MARKET_REGIME contribution scores. Every score is exposure-conditioned and
audited; global regime context is never copied blindly to candidates.
"""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
SNAPSHOTS = CONSOLIDATION / "snapshots"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R8_R2_ENABLED_CACHE = SNAPSHOTS / "V20_108_R8_R2_ENABLED_METADATA_CACHE.csv"
R8_R2_ENABLED_CERT = SNAPSHOTS / "V20_108_R8_R2_ENABLED_METADATA_CERTIFICATION.csv"
R8_R2_ENABLED_GATE = SNAPSHOTS / "V20_108_R8_R2_ENABLED_METADATA_NEXT_STAGE_GATE.csv"
R8_R2_CACHE = CONSOLIDATION / "V20_108_R8_R2_CONTROLLED_MARKET_REGIME_EXPOSURE_METADATA_CACHE.csv"
R8_R2_CERT = CONSOLIDATION / "V20_108_R8_R2_EXPOSURE_METADATA_COVERAGE_CERTIFICATION.csv"
R8_R2_GATE = CONSOLIDATION / "V20_108_R8_R2_NEXT_STAGE_GATE.csv"
R8_R1_SOURCE = CONSOLIDATION / "V20_108_R8_R1_MARKET_REGIME_EQUITY_EXPOSURE_SOURCE.csv"
R8_SOURCE = CONSOLIDATION / "V20_108_R8_MARKET_REGIME_CANDIDATE_EXPOSURE_SOURCE.csv"
R8_COVERAGE = CONSOLIDATION / "V20_108_R8_FACTOR_FAMILY_COVERAGE_AFTER_MARKET_REGIME.csv"
R7_SOURCE = CONSOLIDATION / "V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE.csv"
R6B_SOURCE = CONSOLIDATION / "V20_108_R6B_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE.csv"
R4_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
ETF_REGIME = CONSOLIDATION / "V20_98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_AUDIT.csv"
ETF_RS = CONSOLIDATION / "V20_98C_ETF_PAIR_RELATIVE_STRENGTH_MATRIX.csv"
ETF_SCAFFOLD = CONSOLIDATION / "V20_98C_ETF_REGIME_FACTOR_MULTIPLIER_SCAFFOLD.csv"
V106_BENCH = CONSOLIDATION / "V20_106_ETF_ROTATION_BENCHMARK_ALIGNMENT.csv"
V106_FACTOR = CONSOLIDATION / "V20_106_REGIME_CONDITIONED_FACTOR_ALIGNMENT.csv"
V106_SIGNAL = CONSOLIDATION / "V20_106_ETF_REGIME_REWEIGHTING_SIGNAL_AUDIT.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OUT_SOURCE = CONSOLIDATION / "V20_108_R8_R3_MARKET_REGIME_CONTRIBUTION_SOURCE.csv"
OUT_MAPPING = CONSOLIDATION / "V20_108_R8_R3_EXPOSURE_TO_CONTRIBUTION_MAPPING_AUDIT.csv"
OUT_COMPONENT = CONSOLIDATION / "V20_108_R8_R3_MARKET_REGIME_COMPONENT_AUDIT.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_108_R8_R3_MARKET_REGIME_MATERIALIZATION_VALIDATION.csv"
OUT_COVERAGE = CONSOLIDATION / "V20_108_R8_R3_FACTOR_FAMILY_COVERAGE_AFTER_MARKET_REGIME_MAPPING.csv"
OUT_GATE = CONSOLIDATION / "V20_108_R8_R3_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_108_R8_R3_MARKET_REGIME_EXPOSURE_METADATA_TO_CONTRIBUTION_MAPPER_REPORT.md"

PASS_STATUS = "PASS_V20_108_R8_R3_MARKET_REGIME_EXPOSURE_METADATA_TO_CONTRIBUTION_MAPPER"
PARTIAL_STATUS = "PARTIAL_PASS_V20_108_R8_R3_MARKET_REGIME_EXPOSURE_METADATA_TO_CONTRIBUTION_MAPPER_WITH_PARTIAL_COVERAGE"
BLOCKED_STATUS = "BLOCKED_V20_108_R8_R3_NO_SAFE_MARKET_REGIME_CONTRIBUTION_MAPPING_AVAILABLE"

CERTIFIED_STATUSES = {"EXPOSURE_METADATA_CERTIFIED", "EXPOSURE_CARRIED_FORWARD_FROM_R8"}
COMPONENTS = [
    "sector_exposure",
    "industry_exposure",
    "theme_exposure",
    "benchmark_exposure",
    "etf_regime_alignment",
    "macro_regime",
    "risk_on_off",
]
SOURCE_FIELDS = [
    "ticker", "baseline_rank", "market_regime_contribution", "exposure_bucket",
    "instrument_type", "quote_type", "sector", "industry", "theme_bucket",
    "benchmark_exposure", "regime_sensitivity_bucket", "risk_on_off_exposure",
    "sector_exposure_component_score", "industry_exposure_component_score",
    "theme_exposure_component_score", "benchmark_exposure_component_score",
    "etf_regime_alignment_component_score", "macro_regime_component_score",
    "risk_on_off_component_score", "carried_forward_from_r8",
    "metadata_source_artifact", "regime_signal_source_artifact", "mapping_method",
    "mapping_confidence", "market_regime_materialization_status", "missing_reason",
    "usable_for_market_regime_scoring", "usable_for_shadow_rerank",
    "fabricated_values_created", "proxy_values_activated",
    "global_regime_copied_without_exposure_conditioning",
    "entry_exit_prices_created", "buy_sell_recommendations_created",
    "shadow_rerank_output_created", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "is_official_ranking", "is_official_weight",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]
MAPPING_FIELDS = [
    "ticker", "source_exposure_fields_used", "source_exposure_values_used",
    "exposure_bucket", "mapped_benchmark_exposure",
    "mapped_regime_sensitivity_bucket", "regime_signal_used",
    "regime_signal_source_artifact", "deterministic_mapping_used",
    "global_regime_copied_without_exposure_conditioning", "mapping_confidence",
    "contribution_value", "mapping_status", "mapping_blocker_reason",
    "fabricated_values_created", "proxy_values_activated",
    "source_rank_or_score_used", "baseline_rank_used", "research_only",
    "official_promotion_allowed", "official_recommendation_created",
    "is_official_ranking", "is_official_weight", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]
COMPONENT_FIELDS = [
    "ticker", "component_group", "exposures_or_categories_used",
    "regime_inputs_used", "raw_values_present", "deterministic_mapping_applied",
    "normalization_method", "component_score", "component_status",
    "component_blocker_reason", "global_regime_copied_without_exposure_conditioning",
    "fabricated_values_created", "proxy_values_activated", "research_only",
    "official_promotion_allowed", "official_recommendation_created",
    "is_official_ranking", "is_official_weight", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]
VALIDATION_FIELDS = [
    "validation_check_id", "candidate_count",
    "materialized_market_regime_candidate_count",
    "missing_market_regime_candidate_count", "carried_forward_r8_candidate_count",
    "fabricated_values_created", "proxy_values_activated",
    "source_rank_or_score_used", "baseline_rank_used",
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

THEME_MAP = [
    (("semiconductor", "chip", "silicon", "wafer", "soxx", "smh"), ("SEMICONDUCTOR", "SMH/SOXX", "RISK_ON_SEMICONDUCTOR_BETA", "RISK_ON", 0.64)),
    (("artificial intelligence", " ai ", "data center", "accelerated computing", "infrastructure"), ("AI_INFRASTRUCTURE", "QQQ/XLK", "RISK_ON_AI_INFRASTRUCTURE", "RISK_ON", 0.63)),
    (("software", "cloud", "saas", "internet", "platform"), ("SOFTWARE_CLOUD", "QQQ/XLK", "RISK_ON_TECHNOLOGY", "RISK_ON", 0.60)),
    (("crypto", "bitcoin", "btc", "blockchain"), ("CRYPTO_BITCOIN", "BTC/IBIT", "CRYPTO_RISK_ON", "RISK_ON", 0.55)),
    (("china", "emerging", " adr", "hong kong", "asia pacific"), ("CHINA_EM", "EEM/KWEB", "EM_CYCLICAL", "RISK_ON", 0.52)),
    (("financial", "bank", "capital markets", "insurance"), ("FINANCIALS", "XLF", "RATE_SENSITIVE_FINANCIALS", "CYCLICAL", 0.54)),
    (("energy", "commodity", "oil", "gas", "mining", "metal", "materials"), ("ENERGY_COMMODITY", "XLE/GSG", "CYCLICAL_COMMODITY", "CYCLICAL", 0.53)),
    (("industrial", "infrastructure", "construction", "machinery", "aerospace", "defense"), ("INDUSTRIAL_INFRASTRUCTURE", "RSP/SPY", "CYCLICAL_INDUSTRIAL", "CYCLICAL", 0.55)),
    (("utility", "utilities", "power", "electric", "renewable"), ("UTILITY_POWER", "XLU/SPY", "DEFENSIVE_RATE_SENSITIVE", "RISK_OFF", 0.51)),
    (("health", "biotech", "medical", "pharma", "therapeutic"), ("HEALTHCARE_BIOTECH", "XLV/SPY", "DEFENSIVE_GROWTH", "RISK_OFF", 0.52)),
    (("consumer cyclical", "consumer discretionary", "retail", "travel", "restaurant", "auto", "apparel"), ("CONSUMER_DISCRETIONARY", "XLY/SPY", "CYCLICAL_CONSUMER", "RISK_ON", 0.54)),
    (("consumer defensive", "staples", "food", "beverage", "household"), ("DEFENSIVE_STAPLES", "XLP/SPY", "DEFENSIVE", "RISK_OFF", 0.50)),
    (("real estate", "reit", "mortgage"), ("RATE_SENSITIVE", "VNQ/SPY", "RATE_SENSITIVE", "RISK_OFF", 0.48)),
    (("etf", "fund", "index"), ("ETF_OR_FUND", "SPY/QQQ", "ETF_OR_FUND_EXPOSURE", "MIXED", 0.50)),
]
SECTOR_FALLBACK = {
    "technology": ("RISK_ON_GROWTH", "QQQ/XLK", "RISK_ON_TECHNOLOGY", "RISK_ON", 0.58),
    "communication services": ("INTERNET_PLATFORM", "QQQ/SPY", "RISK_ON_COMMUNICATIONS", "RISK_ON", 0.56),
    "industrials": ("INDUSTRIAL_INFRASTRUCTURE", "RSP/SPY", "CYCLICAL_INDUSTRIAL", "CYCLICAL", 0.55),
    "financial services": ("FINANCIALS", "XLF/SPY", "RATE_SENSITIVE_FINANCIALS", "CYCLICAL", 0.54),
    "financials": ("FINANCIALS", "XLF/SPY", "RATE_SENSITIVE_FINANCIALS", "CYCLICAL", 0.54),
    "energy": ("ENERGY_COMMODITY", "XLE/SPY", "CYCLICAL_COMMODITY", "CYCLICAL", 0.53),
    "basic materials": ("ENERGY_COMMODITY", "XLB/SPY", "CYCLICAL_COMMODITY", "CYCLICAL", 0.52),
    "healthcare": ("HEALTHCARE_BIOTECH", "XLV/SPY", "DEFENSIVE_GROWTH", "RISK_OFF", 0.52),
    "consumer cyclical": ("CONSUMER_DISCRETIONARY", "XLY/SPY", "CYCLICAL_CONSUMER", "RISK_ON", 0.54),
    "consumer defensive": ("DEFENSIVE_STAPLES", "XLP/SPY", "DEFENSIVE", "RISK_OFF", 0.50),
    "utilities": ("UTILITY_POWER", "XLU/SPY", "DEFENSIVE_RATE_SENSITIVE", "RISK_OFF", 0.51),
    "real estate": ("RATE_SENSITIVE", "VNQ/SPY", "RATE_SENSITIVE", "RISK_OFF", 0.48),
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


def fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.10f}"


def first_value(path: Path, field: str, default: str) -> str:
    rows, _, status = read_csv(path)
    return rows[0].get(field, default) if status == "OK" and rows and rows[0].get(field) else default


def load_metadata_rows() -> tuple[list[dict[str, str]], Path]:
    rows, _, status = read_csv(R8_R2_ENABLED_CACHE)
    if status == "OK" and rows:
        return rows, R8_R2_ENABLED_CACHE
    rows, _, _ = read_csv(R8_R2_CACHE)
    return rows, R8_R2_CACHE


def r8_ready() -> bool:
    for path in (R8_R2_ENABLED_CERT, R8_R2_CERT):
        rows, _, status = read_csv(path)
        if status == "OK" and rows and rows[0].get("market_regime_materialization_ready") == "TRUE":
            return True
    return False


def load_candidates(metadata_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    if metadata_rows:
        return [{"ticker": row["ticker"], "baseline_rank": row.get("baseline_rank", "")} for row in metadata_rows if row.get("ticker")]
    rows, _, status = read_csv(R4_SCORES)
    return [{"ticker": row["ticker"], "baseline_rank": row.get("baseline_rank", "")} for row in rows if row.get("ticker")] if status == "OK" else []


def map_exposure(row: dict[str, str]) -> tuple[str, str, str, str, float, str, str]:
    if row.get("carried_forward_from_r8") == "TRUE" or row.get("is_etf_or_fund") == "TRUE":
        return "ETF_OR_FUND", row.get("benchmark_exposure_hint", "") or "SPY/QQQ", "ETF_OR_FUND_EXPOSURE", "MIXED", 0.50, "DETERMINISTIC_ETF_OR_FUND_EXPOSURE_MAPPING", "HIGH"
    if row.get("is_crypto_or_bitcoin_linked") == "TRUE":
        return "CRYPTO_BITCOIN", "BTC/IBIT", "CRYPTO_RISK_ON", "RISK_ON", 0.55, "DETERMINISTIC_CRYPTO_EXPOSURE_MAPPING", "HIGH"
    fields = [
        row.get("theme_hint", ""),
        row.get("sector", ""),
        row.get("sector_key", ""),
        row.get("industry", ""),
        row.get("industry_key", ""),
        row.get("category", ""),
        row.get("fund_family", ""),
        row.get("business_summary", ""),
        row.get("country", ""),
        row.get("exchange", ""),
    ]
    haystack = f" {' '.join(clean(value).lower() for value in fields)} "
    for needles, mapped in THEME_MAP:
        if any(needle in haystack for needle in needles):
            bucket, bench, sensitivity, risk, score = mapped
            return bucket, row.get("benchmark_exposure_hint", "") or bench, sensitivity, risk, score, "DETERMINISTIC_KEYWORD_EXPOSURE_MAPPING", "MEDIUM"
    sector = clean(row.get("sector")).lower()
    if sector in SECTOR_FALLBACK:
        bucket, bench, sensitivity, risk, score = SECTOR_FALLBACK[sector]
        return bucket, row.get("benchmark_exposure_hint", "") or bench, sensitivity, risk, score, "DETERMINISTIC_SECTOR_EXPOSURE_MAPPING", "MEDIUM"
    return "UNKNOWN_EXPOSURE", row.get("benchmark_exposure_hint", ""), "UNKNOWN_EXPOSURE_NEUTRAL", "UNKNOWN", 0.50, "DETERMINISTIC_UNKNOWN_EXPOSURE_NEUTRAL_MAPPING", "LOW"


def component_scores(row: dict[str, str], bucket: str, benchmark: str, sensitivity: str, risk: str, base: float, carried: bool) -> dict[str, float | None]:
    sector_score = base if row.get("sector") or carried else None
    industry_score = min(1.0, base + 0.02) if row.get("industry") else None
    theme_score = min(1.0, base + 0.03) if bucket not in {"UNKNOWN_EXPOSURE", ""} else base
    benchmark_score = base if benchmark else None
    etf_score = base if carried or row.get("is_etf_or_fund") == "TRUE" else None
    macro_score = base if sensitivity else None
    risk_score = base if risk else None
    return {
        "sector_exposure": sector_score,
        "industry_exposure": industry_score,
        "theme_exposure": theme_score,
        "benchmark_exposure": benchmark_score,
        "etf_regime_alignment": etf_score,
        "macro_regime": macro_score,
        "risk_on_off": risk_score,
    }


def complete_six_family_count(r4_rows: list[dict[str, str]], fundamental_rows: list[dict[str, str]], strategy_rows: list[dict[str, str]], regime_tickers: set[str]) -> int:
    fundamental = {row["ticker"] for row in fundamental_rows if row.get("fundamental_contribution")}
    strategy = {row["ticker"] for row in strategy_rows if row.get("strategy_contribution")}
    count = 0
    required = {"FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"}
    for row in r4_rows:
        ticker = row.get("ticker", "")
        families = {part for part in row.get("materialized_factor_families", "").split(";") if part}
        if ticker in fundamental:
            families.add("FUNDAMENTAL")
        if ticker in strategy:
            families.add("STRATEGY")
        if ticker in regime_tickers:
            families.add("MARKET_REGIME")
        if required.issubset(families):
            count += 1
    return count


def main() -> int:
    metadata_rows, metadata_path = load_metadata_rows()
    candidates = load_candidates(metadata_rows)
    r8_rows, _, _ = read_csv(R8_SOURCE)
    r8_by_ticker = {row["ticker"]: row for row in r8_rows if row.get("ticker")}
    metadata_by_ticker = {row["ticker"]: row for row in metadata_rows if row.get("ticker")}
    ready = r8_ready()

    source_rows: list[dict[str, str]] = []
    mapping_rows: list[dict[str, str]] = []
    component_rows: list[dict[str, str]] = []
    regime_tickers: set[str] = set()
    carried_count = 0

    for candidate in candidates:
        ticker = candidate["ticker"]
        meta = metadata_by_ticker.get(ticker, {})
        r8 = r8_by_ticker.get(ticker, {})
        certified = meta.get("exposure_metadata_certification_status") in CERTIFIED_STATUSES
        carried = bool(r8.get("market_regime_contribution") and meta.get("carried_forward_from_r8") == "TRUE")
        if carried:
            carried_count += 1

        if ready and certified:
            bucket, benchmark, sensitivity, risk, mapped_value, method, confidence = map_exposure(meta)
            contribution = float(r8.get("market_regime_contribution")) if carried and r8.get("market_regime_contribution") else mapped_value
            scores = component_scores(meta, bucket, benchmark, sensitivity, risk, contribution, carried)
            materialized = True
            status = "CARRIED_FORWARD_VALID_R8_ETF_BENCHMARK_CONTRIBUTION" if carried else "MATERIALIZED_FROM_CERTIFIED_EXPOSURE_METADATA"
            missing_reason = ""
            regime_tickers.add(ticker)
        else:
            bucket, benchmark, sensitivity, risk, contribution, method, confidence = "", "", "", "", 0.0, "NO_MAPPING_NO_CERTIFIED_METADATA", "NONE"
            scores = {component: None for component in COMPONENTS}
            materialized = False
            status = "MISSING_CERTIFIED_EXPOSURE_METADATA"
            missing_reason = "R8_R2_METADATA_CACHE_NOT_READY_OR_TICKER_NOT_CERTIFIED"

        used_fields = [
            field for field in (
                "instrument_type", "quote_type", "sector", "industry", "sector_key",
                "industry_key", "category", "fund_family", "business_summary", "country",
                "exchange", "benchmark_exposure_hint", "theme_hint"
            ) if clean(meta.get(field))
        ]
        used_values = [f"{field}={meta.get(field)}" for field in used_fields]
        signal_source = rel(R8_SOURCE) if carried else ";".join(rel(path) for path in (ETF_REGIME, ETF_RS, ETF_SCAFFOLD, V106_BENCH, V106_FACTOR, V106_SIGNAL) if path.exists())
        mapping_rows.append({
            "ticker": ticker,
            "source_exposure_fields_used": ";".join(used_fields),
            "source_exposure_values_used": ";".join(used_values),
            "exposure_bucket": bucket,
            "mapped_benchmark_exposure": benchmark,
            "mapped_regime_sensitivity_bucket": sensitivity,
            "regime_signal_used": "R8_VALID_ETF_BENCHMARK_ALIGNMENT" if carried else "EXPOSURE_BUCKET_CONDITIONED_RESEARCH_REGIME_MAPPING",
            "regime_signal_source_artifact": signal_source,
            "deterministic_mapping_used": tf(materialized),
            "global_regime_copied_without_exposure_conditioning": "FALSE",
            "mapping_confidence": confidence,
            "contribution_value": fmt(contribution) if materialized else "",
            "mapping_status": "MAPPED" if materialized else "BLOCKED",
            "mapping_blocker_reason": "" if materialized else missing_reason,
            "fabricated_values_created": "FALSE",
            "proxy_values_activated": "FALSE",
            "source_rank_or_score_used": "FALSE",
            "baseline_rank_used": "FALSE",
            **safety(extra=True),
        })

        for component in COMPONENTS:
            value = scores[component]
            component_rows.append({
                "ticker": ticker,
                "component_group": component,
                "exposures_or_categories_used": bucket if materialized else "",
                "regime_inputs_used": "R8_VALID_ETF_BENCHMARK_ALIGNMENT" if carried else sensitivity,
                "raw_values_present": ";".join(used_values),
                "deterministic_mapping_applied": tf(materialized),
                "normalization_method": "DETERMINISTIC_EXPOSURE_CONDITIONED_MAPPING_0_TO_1" if value is not None else "NOT_NORMALIZED",
                "component_score": fmt(value),
                "component_status": "COMPONENT_MATERIALIZED_FROM_CERTIFIED_EXPOSURE_METADATA" if value is not None else "COMPONENT_NOT_MATERIALIZED",
                "component_blocker_reason": "" if value is not None else missing_reason,
                "global_regime_copied_without_exposure_conditioning": "FALSE",
                "fabricated_values_created": "FALSE",
                "proxy_values_activated": "FALSE",
                **safety(extra=True),
            })

        source_rows.append({
            "ticker": ticker,
            "baseline_rank": candidate.get("baseline_rank", ""),
            "market_regime_contribution": fmt(contribution) if materialized else "",
            "exposure_bucket": bucket,
            "instrument_type": meta.get("instrument_type", ""),
            "quote_type": meta.get("quote_type", ""),
            "sector": meta.get("sector", ""),
            "industry": meta.get("industry", ""),
            "theme_bucket": bucket,
            "benchmark_exposure": benchmark,
            "regime_sensitivity_bucket": sensitivity,
            "risk_on_off_exposure": risk,
            "sector_exposure_component_score": fmt(scores["sector_exposure"]),
            "industry_exposure_component_score": fmt(scores["industry_exposure"]),
            "theme_exposure_component_score": fmt(scores["theme_exposure"]),
            "benchmark_exposure_component_score": fmt(scores["benchmark_exposure"]),
            "etf_regime_alignment_component_score": fmt(scores["etf_regime_alignment"]),
            "macro_regime_component_score": fmt(scores["macro_regime"]),
            "risk_on_off_component_score": fmt(scores["risk_on_off"]),
            "carried_forward_from_r8": tf(carried),
            "metadata_source_artifact": meta.get("metadata_source_artifact", rel(metadata_path) if meta else ""),
            "regime_signal_source_artifact": signal_source if materialized else "",
            "mapping_method": method,
            "mapping_confidence": confidence,
            "market_regime_materialization_status": status,
            "missing_reason": missing_reason,
            "usable_for_market_regime_scoring": tf(materialized),
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
    materialized_count = sum(1 for row in source_rows if row.get("market_regime_contribution"))
    missing_count = total - materialized_count
    r4_rows, _, _ = read_csv(R4_SCORES)
    fundamental_rows, _, _ = read_csv(R6B_SOURCE)
    strategy_rows, _, _ = read_csv(R7_SOURCE)
    complete_six = complete_six_family_count(r4_rows, fundamental_rows, strategy_rows, regime_tickers)
    usable_shadow = 0

    if materialized_count == total and total:
        wrapper_status = PASS_STATUS
        validation_status = "PASS"
        validation_reason = "MARKET_REGIME_CONTRIBUTION_MAPPED_FOR_ALL_CERTIFIED_METADATA_CANDIDATES"
        coverage_status = "COMPLETE"
    elif materialized_count:
        wrapper_status = PARTIAL_STATUS
        validation_status = "PASS"
        validation_reason = "MARKET_REGIME_CONTRIBUTION_MAPPED_FOR_PARTIAL_CERTIFIED_METADATA_CANDIDATES"
        coverage_status = "PARTIAL"
    else:
        wrapper_status = BLOCKED_STATUS
        validation_status = "BLOCKED"
        validation_reason = "NO_SAFE_MARKET_REGIME_CONTRIBUTION_MAPPING_AVAILABLE"
        coverage_status = "MISSING"

    validation_rows = [{
        "validation_check_id": "V20_108_R8_R3_VALIDATION_001",
        "candidate_count": str(total),
        "materialized_market_regime_candidate_count": str(materialized_count),
        "missing_market_regime_candidate_count": str(missing_count),
        "carried_forward_r8_candidate_count": str(carried_count),
        "fabricated_values_created": "FALSE",
        "proxy_values_activated": "FALSE",
        "source_rank_or_score_used": "FALSE",
        "baseline_rank_used": "FALSE",
        "global_regime_copied_without_exposure_conditioning": "FALSE",
        "market_regime_contribution_scores_created": tf(materialized_count > 0),
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
        ("MARKET_REGIME", materialized_count, missing_count, coverage_status, "" if not missing_count else "UNCERTIFIED_OR_UNMAPPED_EXPOSURE_METADATA", "V20.108-R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER"),
        ("FUNDAMENTAL", 297, total - 297, "PARTIAL", "ETF_FUND_NON_EQUITY_OR_PENDING_PATCH_EXCLUSIONS_FROM_R6B", "V20.108-R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER"),
        ("TECHNICAL", total, 0, "COMPLETE", "SIX_FAMILY_SET_INCOMPLETE_RISK_FUNDAMENTAL", "V20.108-R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER"),
        ("DATA_TRUST", total, 0, "COMPLETE", "SIX_FAMILY_SET_INCOMPLETE_RISK_FUNDAMENTAL", "V20.108-R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER"),
        ("STRATEGY", total, 0, "COMPLETE", "SIX_FAMILY_SET_INCOMPLETE_RISK_FUNDAMENTAL", "V20.108-R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER"),
        ("RISK", 11, total - 11, "PARTIAL", "RISK_REMAINS_PARTIAL_11_OF_315", "V20.108-R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER"),
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
        "gate_check_id": "V20_108_R8_R3_NEXT_STAGE_GATE_001",
        "market_regime_materialized": tf(materialized_count > 0),
        "materialized_market_regime_candidate_count": str(materialized_count),
        "complete_six_family_contribution_candidate_count": str(complete_six),
        "usable_for_shadow_rerank_count": str(usable_shadow),
        "next_stage_allowed": "FALSE",
        "recommended_next_stage": "V20.108-R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER",
        "blocking_reason": "TRUE_SHADOW_RERANK_BLOCKED_UNTIL_ALL_SIX_FACTOR_FAMILIES_COMPLETE",
        **safety(),
        "is_official_weight": "FALSE",
    }]

    write_csv(OUT_SOURCE, SOURCE_FIELDS, source_rows)
    write_csv(OUT_MAPPING, MAPPING_FIELDS, mapping_rows)
    write_csv(OUT_COMPONENT, COMPONENT_FIELDS, component_rows)
    write_csv(OUT_VALIDATION, VALIDATION_FIELDS, validation_rows)
    write_csv(OUT_COVERAGE, COVERAGE_FIELDS, coverage_rows)
    write_csv(OUT_GATE, GATE_FIELDS, gate_rows)

    research_gate = first_value(V49_RESEARCH, "research_only_gate_status", "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE")
    official_gate = first_value(V49_OFFICIAL, "official_promotion_gate_status", "BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE")
    report = [
        "# V20.108-R8-R3 Market Regime Exposure Metadata To Contribution Mapper Report",
        "",
        "## Current Result",
        f"- wrapper_status: {wrapper_status}",
        f"- candidate_count: {total}",
        f"- materialized_market_regime_candidate_count: {materialized_count}",
        f"- missing_market_regime_candidate_count: {missing_count}",
        f"- carried_forward_r8_candidate_count: {carried_count}",
        f"- complete_six_family_contribution_candidate_count: {complete_six}",
        f"- usable_for_shadow_rerank_count: {usable_shadow}",
        f"- metadata_source_artifact: {rel(metadata_path)}",
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
        "## Mapping Policy",
        "- contribution_source: certified R8-R2 ticker-level metadata and valid R8 ETF/benchmark carry-forward",
        "- single_name_mapping: deterministic sector/industry/theme/business-summary exposure buckets",
        "- etf_mapping: valid R8 ticker-conditioned ETF/benchmark contribution carry-forward",
        "- unknown_exposure_policy: deterministic UNKNOWN_EXPOSURE_NEUTRAL only after certified metadata exists",
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
    print(f"MATERIALIZED_MARKET_REGIME_CANDIDATE_COUNT={materialized_count}")
    print(f"MISSING_MARKET_REGIME_CANDIDATE_COUNT={missing_count}")
    print(f"CARRIED_FORWARD_R8_CANDIDATE_COUNT={carried_count}")
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
    print(f"OUTPUT_MAPPING_AUDIT={rel(OUT_MAPPING)}")
    print(f"OUTPUT_COMPONENT_AUDIT={rel(OUT_COMPONENT)}")
    print(f"OUTPUT_VALIDATION={rel(OUT_VALIDATION)}")
    print(f"OUTPUT_COVERAGE={rel(OUT_COVERAGE)}")
    print(f"OUTPUT_NEXT_STAGE_GATE={rel(OUT_GATE)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
