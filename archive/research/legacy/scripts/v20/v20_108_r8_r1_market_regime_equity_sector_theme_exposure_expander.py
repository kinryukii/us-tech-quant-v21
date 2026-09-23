#!/usr/bin/env python
"""V20.108-R8-R1 market regime equity sector/theme exposure expander.

Carries forward valid R8 ETF/benchmark exposures and expands only from real
candidate-level sector, industry, theme, benchmark, or instrument metadata.
No global regime signal is copied to candidates without exposure conditioning.
"""

from __future__ import annotations

import csv
import math
import os
from pathlib import Path
from time import sleep


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R8_SOURCE = CONSOLIDATION / "V20_108_R8_MARKET_REGIME_CANDIDATE_EXPOSURE_SOURCE.csv"
R8_AUDIT = CONSOLIDATION / "V20_108_R8_MARKET_REGIME_SOURCE_AUDIT.csv"
R8_COMPONENT = CONSOLIDATION / "V20_108_R8_MARKET_REGIME_EXPOSURE_COMPONENT_AUDIT.csv"
R8_VALIDATION = CONSOLIDATION / "V20_108_R8_MARKET_REGIME_MATERIALIZATION_VALIDATION.csv"
R8_COVERAGE = CONSOLIDATION / "V20_108_R8_FACTOR_FAMILY_COVERAGE_AFTER_MARKET_REGIME.csv"
R8_GATE = CONSOLIDATION / "V20_108_R8_NEXT_STAGE_GATE.csv"
R7_SOURCE = CONSOLIDATION / "V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE.csv"
R6B_SOURCE = CONSOLIDATION / "V20_108_R6B_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE.csv"
R4_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
V50_CANDIDATES = CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V48_FACTORS = CONSOLIDATION / "V20_48_REFRESHED_FACTOR_SUPPORT_VIEW.csv"
ETF_REGIME = CONSOLIDATION / "V20_98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_AUDIT.csv"
ETF_RS = CONSOLIDATION / "V20_98C_ETF_PAIR_RELATIVE_STRENGTH_MATRIX.csv"
V106_BENCH = CONSOLIDATION / "V20_106_ETF_ROTATION_BENCHMARK_ALIGNMENT.csv"
V106_FACTOR = CONSOLIDATION / "V20_106_REGIME_CONDITIONED_FACTOR_ALIGNMENT.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OUT_SOURCE = CONSOLIDATION / "V20_108_R8_R1_MARKET_REGIME_EQUITY_EXPOSURE_SOURCE.csv"
OUT_SOURCE_AUDIT = CONSOLIDATION / "V20_108_R8_R1_SECTOR_THEME_SOURCE_AUDIT.csv"
OUT_MAPPING_AUDIT = CONSOLIDATION / "V20_108_R8_R1_EXPOSURE_MAPPING_AUDIT.csv"
OUT_COVERAGE = CONSOLIDATION / "V20_108_R8_R1_MARKET_REGIME_COVERAGE_AFTER_EXPANSION.csv"
OUT_GATE = CONSOLIDATION / "V20_108_R8_R1_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_108_R8_R1_MARKET_REGIME_EQUITY_SECTOR_THEME_EXPOSURE_EXPANDER_REPORT.md"

PASS_STATUS = "PASS_V20_108_R8_R1_MARKET_REGIME_EQUITY_SECTOR_THEME_EXPOSURE_EXPANDER"
PARTIAL_STATUS = "PARTIAL_PASS_V20_108_R8_R1_MARKET_REGIME_EQUITY_SECTOR_THEME_EXPOSURE_EXPANDER_WITH_PARTIAL_COVERAGE"
BLOCKED_STATUS = "BLOCKED_V20_108_R8_R1_NO_SAFE_EQUITY_EXPOSURE_SOURCE_FOUND"

TICKER_COLUMNS = ("ticker", "normalized_ticker", "ticker_or_candidate_id", "symbol", "yf_ticker")
RANK_COLUMNS = {"source_rank_or_score", "baseline_rank", "rank", "report_rank", "composite_candidate_score"}
SECTOR_COLUMNS = {"sector", "gics_sector", "morningstar_sector"}
INDUSTRY_COLUMNS = {"industry", "gics_industry", "industry_group"}
SUB_INDUSTRY_COLUMNS = {"sub_industry", "gics_sub_industry"}
THEME_COLUMNS = {"theme", "primary_theme", "business_description_theme", "source_tags"}
INSTRUMENT_COLUMNS = {"instrument_type", "asset_type", "quote_type", "security_type", "position_type"}
BENCHMARK_COLUMNS = {"benchmark_exposure", "benchmark_symbol", "benchmark_id", "index_exposure"}
ALLOWED_PROVIDERS = {"yfinance", "local_csv", "local_cache"}

THEME_MAP = [
    (("semiconductor", "chip", "semicap", "soxx", "smh"), ("SEMICONDUCTOR", "QQQ/SMH/SOXX", "RISK_ON_SEMICONDUCTOR_BETA", "RISK_ON", 0.64)),
    (("ai", "artificial intelligence", "data center", "infrastructure"), ("AI_INFRASTRUCTURE", "QQQ/XLK", "RISK_ON_AI_INFRASTRUCTURE", "RISK_ON", 0.63)),
    (("software", "cloud", "saas", "internet", "platform"), ("SOFTWARE_CLOUD", "QQQ/XLK", "RISK_ON_TECHNOLOGY", "RISK_ON", 0.60)),
    (("crypto", "bitcoin", "btc"), ("CRYPTO_BITCOIN", "BTC/IBIT", "CRYPTO_RISK_ON", "RISK_ON", 0.55)),
    (("china", "emerging", "em ", "adr"), ("CHINA_EM", "EEM/KWEB", "EM_CYCLICAL", "RISK_ON", 0.52)),
    (("financial", "bank", "capital markets"), ("FINANCIALS", "XLF", "RATE_SENSITIVE_FINANCIALS", "CYCLICAL", 0.54)),
    (("energy", "commodity", "oil", "gas", "materials", "metal"), ("ENERGY_COMMODITY", "GSG/XLE", "CYCLICAL_COMMODITY", "CYCLICAL", 0.53)),
    (("industrial", "infrastructure", "construction", "machinery"), ("INDUSTRIAL_INFRASTRUCTURE", "RSP/SPY", "CYCLICAL_INDUSTRIAL", "CYCLICAL", 0.55)),
    (("utility", "utilities", "power", "electric"), ("UTILITY_POWER", "XLU/SPY", "DEFENSIVE_RATE_SENSITIVE", "RISK_OFF", 0.51)),
    (("health", "biotech", "medical", "pharma"), ("HEALTHCARE_BIOTECH", "XLV/SPY", "DEFENSIVE_GROWTH", "RISK_OFF", 0.52)),
    (("consumer discretionary", "retail", "travel", "restaurant", "auto"), ("CONSUMER_DISCRETIONARY", "XLY/SPY", "CYCLICAL_CONSUMER", "RISK_ON", 0.54)),
    (("staples", "defensive", "consumer defensive"), ("DEFENSIVE_STAPLES", "XLP/SPY", "DEFENSIVE", "RISK_OFF", 0.50)),
    (("broad index", "index", "etf", "fund"), ("BROAD_INDEX_OR_FUND", "SPY/QQQ", "ETF_OR_FUND_EXPOSURE", "MIXED", 0.50)),
]

SOURCE_FIELDS = [
    "ticker", "baseline_rank", "instrument_type", "sector", "industry", "sub_industry",
    "theme_bucket", "benchmark_exposure", "regime_sensitivity_bucket",
    "risk_on_off_exposure", "market_regime_contribution", "carried_forward_from_r8",
    "exposure_source_artifact", "exposure_source_stage", "exposure_source_provider",
    "exposure_source_status", "exposure_mapping_method", "exposure_mapping_confidence",
    "market_regime_materialization_status", "missing_reason",
    "usable_for_market_regime_scoring", "usable_for_shadow_rerank",
    "fabricated_values_created", "proxy_values_activated",
    "global_regime_copied_without_exposure_conditioning",
    "entry_exit_prices_created", "buy_sell_recommendations_created",
    "shadow_rerank_output_created", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "is_official_ranking", "is_official_weight",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]
SOURCE_AUDIT_FIELDS = [
    "source_artifact", "source_exists", "source_non_empty", "source_provider",
    "source_refresh_allowed", "ticker_column_available", "candidate_rows_found",
    "sector_columns_found", "industry_columns_found", "theme_columns_found",
    "instrument_type_columns_found", "benchmark_exposure_columns_found",
    "accepted_columns", "rejected_columns", "rejection_reason",
    "source_rank_or_score_present", "source_rank_or_score_used_as_market_regime",
    "baseline_rank_used_as_market_regime", "fabricated_values_created",
    "proxy_values_activated", "materialization_allowed",
    "materialization_blocker_reason", "validation_status", "validation_reason",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]
MAPPING_FIELDS = [
    "ticker", "source_exposure_field", "source_exposure_value", "mapped_theme_bucket",
    "mapped_benchmark_exposure", "mapped_regime_sensitivity_bucket", "mapping_method",
    "mapping_confidence", "deterministic_mapping_used",
    "global_regime_copied_without_exposure_conditioning", "fabricated_values_created",
    "proxy_values_activated", "mapping_status", "mapping_blocker_reason",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]
COVERAGE_FIELDS = [
    "factor_family", "required_candidate_count", "carried_forward_r8_candidate_count",
    "newly_materialized_candidate_count", "total_materialized_candidate_count",
    "missing_candidate_count", "coverage_ratio", "contribution_coverage_status",
    "usable_for_shadow_rerank", "missing_reason", "recommended_next_stage",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "is_official_weight", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]
GATE_FIELDS = [
    "gate_check_id", "market_regime_exposure_expanded",
    "carried_forward_r8_candidate_count", "newly_materialized_candidate_count",
    "total_market_regime_materialized_candidate_count",
    "complete_six_family_contribution_candidate_count",
    "usable_for_shadow_rerank_count", "next_stage_allowed", "recommended_next_stage",
    "blocking_reason", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "is_official_weight", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
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


def provider_name(path: Path) -> str:
    parts = [part.lower() for part in path.parts]
    if "data" in parts:
        return "local_csv"
    if "cache" in parts:
        return "local_cache"
    if "outputs" in parts:
        return "local_output_artifact"
    return "local_file"


def discover_sources() -> list[Path]:
    seeds = [
        R8_SOURCE, R8_AUDIT, R8_COMPONENT, R8_VALIDATION, R8_COVERAGE, R8_GATE,
        R7_SOURCE, R6B_SOURCE, R4_SCORES, V50_CANDIDATES, V48_CANDIDATES,
        V48_FACTORS, ETF_REGIME, ETF_RS, V106_BENCH, V106_FACTOR, V49_RESEARCH,
        V49_OFFICIAL,
    ]
    found: list[Path] = []
    for root in (ROOT / "data", ROOT / "cache"):
        if root.exists():
            found.extend(root.rglob("*.csv"))
    patterns = ["*SECTOR*.csv", "*INDUSTRY*.csv", "*THEME*.csv", "*EXPOSURE*.csv", "*BENCHMARK*.csv", "*REGIME*.csv"]
    for pattern in patterns:
        found.extend((ROOT / "outputs" / "v20").rglob(pattern))
    for root in (ROOT / "outputs" / "v18", ROOT / "outputs" / "v19", ROOT / "outputs" / "backtest"):
        if root.exists():
            found.extend(root.rglob("*.csv"))
    excluded = {OUT_SOURCE.resolve(), OUT_SOURCE_AUDIT.resolve(), OUT_MAPPING_AUDIT.resolve(), OUT_COVERAGE.resolve(), OUT_GATE.resolve()}
    ordered: list[Path] = []
    seen: set[Path] = set()
    for path in seeds + sorted(found):
        resolved = path.resolve()
        if resolved in excluded or resolved in seen:
            continue
        seen.add(resolved)
        ordered.append(path)
    return ordered


def ticker_value(row: dict[str, str], fields: list[str]) -> str:
    for field in fields:
        if field in TICKER_COLUMNS:
            value = clean(row.get(field))
            if value:
                return value
    return ""


def field_groups(fields: list[str]) -> dict[str, list[str]]:
    lower_to_field = {field.lower(): field for field in fields}
    return {
        "sector": [lower_to_field[name] for name in SECTOR_COLUMNS if name in lower_to_field],
        "industry": [lower_to_field[name] for name in INDUSTRY_COLUMNS if name in lower_to_field],
        "sub_industry": [lower_to_field[name] for name in SUB_INDUSTRY_COLUMNS if name in lower_to_field],
        "theme": [lower_to_field[name] for name in THEME_COLUMNS if name in lower_to_field],
        "instrument": [lower_to_field[name] for name in INSTRUMENT_COLUMNS if name in lower_to_field],
        "benchmark": [lower_to_field[name] for name in BENCHMARK_COLUMNS if name in lower_to_field],
    }


def map_exposure(text: str) -> tuple[str, str, str, str, float] | None:
    haystack = clean(text).lower()
    if not haystack:
        return None
    for needles, mapped in THEME_MAP:
        if any(needle in haystack for needle in needles):
            return mapped
    return None


def best_metadata(row: dict[str, str], groups: dict[str, list[str]]) -> tuple[dict[str, str], list[tuple[str, str]]]:
    meta = {
        "instrument_type": "",
        "sector": "",
        "industry": "",
        "sub_industry": "",
        "theme_bucket": "",
        "benchmark_exposure": "",
        "regime_sensitivity_bucket": "",
        "risk_on_off_exposure": "",
        "market_regime_contribution": "",
        "exposure_mapping_method": "",
        "exposure_mapping_confidence": "",
    }
    observed: list[tuple[str, str]] = []
    for key, fields in groups.items():
        for field in fields:
            value = clean(row.get(field))
            if not value:
                continue
            observed.append((field, value))
            if key == "instrument" and not meta["instrument_type"]:
                meta["instrument_type"] = value
            if key == "sector" and not meta["sector"]:
                meta["sector"] = value
            if key == "industry" and not meta["industry"]:
                meta["industry"] = value
            if key == "sub_industry" and not meta["sub_industry"]:
                meta["sub_industry"] = value
            if key == "benchmark" and not meta["benchmark_exposure"]:
                meta["benchmark_exposure"] = value
    mapping_source = " ".join(value for _, value in observed)
    mapped = map_exposure(mapping_source)
    if mapped:
        theme, benchmark, sensitivity, risk, score = mapped
        meta.update({
            "theme_bucket": theme,
            "benchmark_exposure": meta["benchmark_exposure"] or benchmark,
            "regime_sensitivity_bucket": sensitivity,
            "risk_on_off_exposure": risk,
            "market_regime_contribution": f"{score:.10f}",
            "exposure_mapping_method": "DETERMINISTIC_SECTOR_INDUSTRY_THEME_TO_REGIME_BUCKET_MAPPING",
            "exposure_mapping_confidence": "MEDIUM",
        })
    return meta, observed


def audit_and_collect(candidates: list[dict[str, str]]) -> tuple[list[dict[str, str]], dict[str, dict[str, str]], list[dict[str, str]]]:
    candidate_tickers = {row["ticker"] for row in candidates}
    refresh_allowed = clean(os.environ.get("ENABLE_MARKET_REGIME_EXPOSURE_REFRESH")).upper() == "TRUE"
    metadata: dict[str, dict[str, str]] = {}
    mappings: list[dict[str, str]] = []
    audits: list[dict[str, str]] = []
    for path in discover_sources():
        rows, fields, status = read_csv(path)
        groups = field_groups(fields)
        ticker_available = any(field in fields for field in TICKER_COLUMNS)
        candidate_rows = 0
        accepted: set[str] = set()
        rejected: set[str] = set()
        source_rank_present = "source_rank_or_score" in fields
        if status == "OK" and ticker_available and any(groups.values()):
            for row in rows:
                ticker = ticker_value(row, fields)
                if ticker not in candidate_tickers:
                    continue
                candidate_rows += 1
                meta, observed = best_metadata(row, groups)
                for field, value in observed:
                    accepted.add(field)
                    mapped = map_exposure(value)
                    if mapped:
                        theme, benchmark, sensitivity, _, _ = mapped
                        mappings.append({
                            "ticker": ticker,
                            "source_exposure_field": field,
                            "source_exposure_value": value,
                            "mapped_theme_bucket": theme,
                            "mapped_benchmark_exposure": benchmark,
                            "mapped_regime_sensitivity_bucket": sensitivity,
                            "mapping_method": "DETERMINISTIC_EXPOSURE_MAPPING_TABLE",
                            "mapping_confidence": "MEDIUM",
                            "deterministic_mapping_used": "TRUE",
                            "global_regime_copied_without_exposure_conditioning": "FALSE",
                            "fabricated_values_created": "FALSE",
                            "proxy_values_activated": "FALSE",
                            "mapping_status": "MAPPED",
                            "mapping_blocker_reason": "",
                            **safety(),
                        })
                    else:
                        mappings.append({
                            "ticker": ticker,
                            "source_exposure_field": field,
                            "source_exposure_value": value,
                            "mapped_theme_bucket": "",
                            "mapped_benchmark_exposure": "",
                            "mapped_regime_sensitivity_bucket": "",
                            "mapping_method": "DETERMINISTIC_EXPOSURE_MAPPING_TABLE",
                            "mapping_confidence": "NONE",
                            "deterministic_mapping_used": "TRUE",
                            "global_regime_copied_without_exposure_conditioning": "FALSE",
                            "fabricated_values_created": "FALSE",
                            "proxy_values_activated": "FALSE",
                            "mapping_status": "UNMAPPED",
                            "mapping_blocker_reason": "EXPOSURE_VALUE_NOT_IN_MAPPING_TABLE",
                            **safety(),
                        })
                if meta.get("market_regime_contribution") and ticker not in metadata:
                    meta["exposure_source_artifact"] = rel(path)
                    meta["exposure_source_stage"] = source_stage(path)
                    meta["exposure_source_provider"] = provider_name(path)
                    metadata[ticker] = meta
        for field in fields:
            low = field.lower()
            if low in RANK_COLUMNS or field in TICKER_COLUMNS or low in {f.lower() for cols in groups.values() for f in cols}:
                continue
            if any(term in low for term in ("sector", "industry", "theme", "exposure", "benchmark", "instrument", "asset_type")):
                rejected.add(field)
        allowed = bool(candidate_rows and accepted)
        audits.append({
            "source_artifact": rel(path),
            "source_exists": tf(path.exists()),
            "source_non_empty": tf(path.exists() and path.stat().st_size > 0),
            "source_provider": provider_name(path),
            "source_refresh_allowed": tf(refresh_allowed),
            "ticker_column_available": tf(ticker_available),
            "candidate_rows_found": str(candidate_rows),
            "sector_columns_found": ";".join(groups["sector"]),
            "industry_columns_found": ";".join(groups["industry"]),
            "theme_columns_found": ";".join(groups["theme"] + groups["sub_industry"]),
            "instrument_type_columns_found": ";".join(groups["instrument"]),
            "benchmark_exposure_columns_found": ";".join(groups["benchmark"]),
            "accepted_columns": ";".join(sorted(accepted)),
            "rejected_columns": ";".join(sorted(rejected)),
            "rejection_reason": "NO_MAPPABLE_CANDIDATE_LEVEL_EXPOSURE_VALUES" if candidate_rows and not metadata else "",
            "source_rank_or_score_present": tf(source_rank_present),
            "source_rank_or_score_used_as_market_regime": "FALSE",
            "baseline_rank_used_as_market_regime": "FALSE",
            "fabricated_values_created": "FALSE",
            "proxy_values_activated": "FALSE",
            "materialization_allowed": tf(allowed),
            "materialization_blocker_reason": "" if allowed else "NO_SAFE_EQUITY_SECTOR_THEME_EXPOSURE_SOURCE",
            "validation_status": "PASS" if allowed else "BLOCKED",
            "validation_reason": "CANDIDATE_LEVEL_EXPOSURE_METADATA_FOUND" if allowed else "NO_SAFE_EQUITY_SECTOR_THEME_EXPOSURE_SOURCE",
            **safety(),
        })
    return audits, metadata, mappings


def controlled_yfinance_metadata(candidates: list[dict[str, str]]) -> tuple[list[dict[str, str]], dict[str, dict[str, str]], list[dict[str, str]]]:
    provider = clean(os.environ.get("MARKET_REGIME_EXPOSURE_PROVIDER_NAME")).lower()
    enabled = clean(os.environ.get("ENABLE_MARKET_REGIME_EXPOSURE_REFRESH")).upper() == "TRUE"
    if not enabled or provider != "yfinance":
        return [], {}, []
    try:
        import yfinance as yf  # type: ignore
    except Exception:
        return [], {}, []
    metadata: dict[str, dict[str, str]] = {}
    mappings: list[dict[str, str]] = []
    for candidate in candidates:  # pragma: no cover - explicit network path only
        ticker = candidate["ticker"]
        try:
            info = yf.Ticker(ticker).get_info()
            sleep(0.2)
        except Exception:
            continue
        row = {
            "ticker": ticker,
            "sector": clean(info.get("sector")),
            "industry": clean(info.get("industry")),
            "quote_type": clean(info.get("quoteType")),
        }
        groups = field_groups(list(row.keys()))
        meta, observed = best_metadata(row, groups)
        if meta.get("market_regime_contribution"):
            meta["exposure_source_artifact"] = "CONTROLLED_YFINANCE_METADATA_REFRESH"
            meta["exposure_source_stage"] = "V20.108-R8-R1"
            meta["exposure_source_provider"] = "yfinance"
            metadata[ticker] = meta
        for field, value in observed:
            mapped = map_exposure(value)
            mappings.append({
                "ticker": ticker,
                "source_exposure_field": field,
                "source_exposure_value": value,
                "mapped_theme_bucket": mapped[0] if mapped else "",
                "mapped_benchmark_exposure": mapped[1] if mapped else "",
                "mapped_regime_sensitivity_bucket": mapped[2] if mapped else "",
                "mapping_method": "CONTROLLED_YFINANCE_METADATA_DETERMINISTIC_MAPPING",
                "mapping_confidence": "MEDIUM" if mapped else "NONE",
                "deterministic_mapping_used": "TRUE",
                "global_regime_copied_without_exposure_conditioning": "FALSE",
                "fabricated_values_created": "FALSE",
                "proxy_values_activated": "FALSE",
                "mapping_status": "MAPPED" if mapped else "UNMAPPED",
                "mapping_blocker_reason": "" if mapped else "EXPOSURE_VALUE_NOT_IN_MAPPING_TABLE",
                **safety(),
            })
    audit = [{
        "source_artifact": "CONTROLLED_YFINANCE_METADATA_REFRESH",
        "source_exists": "TRUE",
        "source_non_empty": tf(bool(metadata)),
        "source_provider": "yfinance",
        "source_refresh_allowed": "TRUE",
        "ticker_column_available": "TRUE",
        "candidate_rows_found": str(len(metadata)),
        "sector_columns_found": "sector",
        "industry_columns_found": "industry",
        "theme_columns_found": "",
        "instrument_type_columns_found": "quoteType",
        "benchmark_exposure_columns_found": "",
        "accepted_columns": "sector;industry;quoteType",
        "rejected_columns": "",
        "rejection_reason": "",
        "source_rank_or_score_present": "FALSE",
        "source_rank_or_score_used_as_market_regime": "FALSE",
        "baseline_rank_used_as_market_regime": "FALSE",
        "fabricated_values_created": "FALSE",
        "proxy_values_activated": "FALSE",
        "materialization_allowed": tf(bool(metadata)),
        "materialization_blocker_reason": "" if metadata else "CONTROLLED_REFRESH_RETURNED_NO_MAPPABLE_METADATA",
        "validation_status": "PASS" if metadata else "BLOCKED",
        "validation_reason": "CONTROLLED_METADATA_REFRESH_EXECUTED" if metadata else "NO_MAPPABLE_METADATA",
        **safety(),
    }]
    return audit, metadata, mappings


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
    r8_rows, _, _ = read_csv(R8_SOURCE)
    r8_by_ticker = {row["ticker"]: row for row in r8_rows}
    audits, metadata, mappings = audit_and_collect(candidates)
    refresh_audits, refresh_metadata, refresh_mappings = controlled_yfinance_metadata(candidates)
    audits.extend(refresh_audits)
    metadata.update({ticker: meta for ticker, meta in refresh_metadata.items() if ticker not in metadata})
    mappings.extend(refresh_mappings)

    output_rows = []
    carried = 0
    newly = 0
    for candidate in candidates:
        ticker = candidate["ticker"]
        r8 = r8_by_ticker.get(ticker, {})
        if r8.get("market_regime_contribution"):
            carried += 1
            output_rows.append({
                "ticker": ticker,
                "baseline_rank": candidate.get("baseline_rank", ""),
                "instrument_type": "ETF_OR_FUND",
                "sector": "",
                "industry": "",
                "sub_industry": "",
                "theme_bucket": r8.get("market_regime_exposure_classification", "ETF_OR_FUND_INSTRUMENT_EXPOSURE"),
                "benchmark_exposure": "",
                "regime_sensitivity_bucket": "ETF_REGIME_PAIR_ALIGNMENT",
                "risk_on_off_exposure": "MIXED",
                "market_regime_contribution": r8.get("market_regime_contribution", ""),
                "carried_forward_from_r8": "TRUE",
                "exposure_source_artifact": r8.get("market_regime_source_artifact", ""),
                "exposure_source_stage": r8.get("market_regime_source_stage", ""),
                "exposure_source_provider": "local_output_artifact",
                "exposure_source_status": "CARRIED_FORWARD_VALID_R8_TICKER_CONDITIONED_ETF_EXPOSURE",
                "exposure_mapping_method": "R8_TICKER_CONDITIONED_ETF_EXPOSURE_CARRY_FORWARD",
                "exposure_mapping_confidence": "HIGH",
                "market_regime_materialization_status": "CARRIED_FORWARD_FROM_R8",
                "missing_reason": "",
                "usable_for_market_regime_scoring": "TRUE",
                "usable_for_shadow_rerank": "FALSE",
                "fabricated_values_created": "FALSE",
                "proxy_values_activated": "FALSE",
                "global_regime_copied_without_exposure_conditioning": "FALSE",
                "entry_exit_prices_created": "FALSE",
                "buy_sell_recommendations_created": "FALSE",
                "shadow_rerank_output_created": "FALSE",
                **safety(extra=True),
            })
        elif ticker in metadata:
            newly += 1
            meta = metadata[ticker]
            output_rows.append({
                "ticker": ticker,
                "baseline_rank": candidate.get("baseline_rank", ""),
                "instrument_type": meta.get("instrument_type", "EQUITY_OR_SINGLE_NAME"),
                "sector": meta.get("sector", ""),
                "industry": meta.get("industry", ""),
                "sub_industry": meta.get("sub_industry", ""),
                "theme_bucket": meta.get("theme_bucket", ""),
                "benchmark_exposure": meta.get("benchmark_exposure", ""),
                "regime_sensitivity_bucket": meta.get("regime_sensitivity_bucket", ""),
                "risk_on_off_exposure": meta.get("risk_on_off_exposure", ""),
                "market_regime_contribution": meta.get("market_regime_contribution", ""),
                "carried_forward_from_r8": "FALSE",
                "exposure_source_artifact": meta.get("exposure_source_artifact", ""),
                "exposure_source_stage": meta.get("exposure_source_stage", ""),
                "exposure_source_provider": meta.get("exposure_source_provider", ""),
                "exposure_source_status": "MATERIALIZED_FROM_CANDIDATE_LEVEL_EXPOSURE_METADATA",
                "exposure_mapping_method": meta.get("exposure_mapping_method", ""),
                "exposure_mapping_confidence": meta.get("exposure_mapping_confidence", ""),
                "market_regime_materialization_status": "MATERIALIZED_FROM_EQUITY_SECTOR_THEME_EXPOSURE",
                "missing_reason": "",
                "usable_for_market_regime_scoring": "TRUE",
                "usable_for_shadow_rerank": "FALSE",
                "fabricated_values_created": "FALSE",
                "proxy_values_activated": "FALSE",
                "global_regime_copied_without_exposure_conditioning": "FALSE",
                "entry_exit_prices_created": "FALSE",
                "buy_sell_recommendations_created": "FALSE",
                "shadow_rerank_output_created": "FALSE",
                **safety(extra=True),
            })
        else:
            output_rows.append({
                "ticker": ticker,
                "baseline_rank": candidate.get("baseline_rank", ""),
                "instrument_type": "",
                "sector": "",
                "industry": "",
                "sub_industry": "",
                "theme_bucket": "",
                "benchmark_exposure": "",
                "regime_sensitivity_bucket": "",
                "risk_on_off_exposure": "",
                "market_regime_contribution": "",
                "carried_forward_from_r8": "FALSE",
                "exposure_source_artifact": "",
                "exposure_source_stage": "",
                "exposure_source_provider": "",
                "exposure_source_status": "MISSING_CANDIDATE_LEVEL_MARKET_REGIME_EXPOSURE",
                "exposure_mapping_method": "NO_MAPPING_NO_REAL_EXPOSURE_METADATA",
                "exposure_mapping_confidence": "NONE",
                "market_regime_materialization_status": "MISSING_CANDIDATE_LEVEL_MARKET_REGIME_EXPOSURE",
                "missing_reason": "MISSING_CANDIDATE_LEVEL_MARKET_REGIME_EXPOSURE",
                "usable_for_market_regime_scoring": "FALSE",
                "usable_for_shadow_rerank": "FALSE",
                "fabricated_values_created": "FALSE",
                "proxy_values_activated": "FALSE",
                "global_regime_copied_without_exposure_conditioning": "FALSE",
                "entry_exit_prices_created": "FALSE",
                "buy_sell_recommendations_created": "FALSE",
                "shadow_rerank_output_created": "FALSE",
                **safety(extra=True),
            })

    total = len(output_rows)
    materialized = carried + newly
    missing = total - materialized
    r4_rows, _, _ = read_csv(R4_SCORES)
    fundamental_rows, _, _ = read_csv(R6B_SOURCE)
    strategy_rows, _, _ = read_csv(R7_SOURCE)
    regime_tickers = {row["ticker"] for row in output_rows if row.get("market_regime_contribution")}
    complete_six = complete_six_family_count(r4_rows, fundamental_rows, strategy_rows, regime_tickers)
    usable_shadow = 0
    if materialized == total and total:
        wrapper_status = PASS_STATUS
        coverage_status = "COMPLETE"
    elif materialized:
        wrapper_status = PARTIAL_STATUS
        coverage_status = "PARTIAL"
    else:
        wrapper_status = BLOCKED_STATUS
        coverage_status = "MISSING"

    coverage_rows = [{
        "factor_family": "MARKET_REGIME",
        "required_candidate_count": str(total),
        "carried_forward_r8_candidate_count": str(carried),
        "newly_materialized_candidate_count": str(newly),
        "total_materialized_candidate_count": str(materialized),
        "missing_candidate_count": str(missing),
        "coverage_ratio": f"{(materialized / total if total else 0.0):.10f}",
        "contribution_coverage_status": coverage_status,
        "usable_for_shadow_rerank": "FALSE",
        "missing_reason": "MISSING_CANDIDATE_LEVEL_EQUITY_SECTOR_THEME_EXPOSURE" if missing else "",
        "recommended_next_stage": "V20.108-R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER",
        **safety(),
        "is_official_weight": "FALSE",
    }]
    gate_rows = [{
        "gate_check_id": "V20_108_R8_R1_NEXT_STAGE_GATE_001",
        "market_regime_exposure_expanded": tf(newly > 0),
        "carried_forward_r8_candidate_count": str(carried),
        "newly_materialized_candidate_count": str(newly),
        "total_market_regime_materialized_candidate_count": str(materialized),
        "complete_six_family_contribution_candidate_count": str(complete_six),
        "usable_for_shadow_rerank_count": str(usable_shadow),
        "next_stage_allowed": "FALSE",
        "recommended_next_stage": "V20.108-R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER",
        "blocking_reason": "TRUE_SHADOW_RERANK_BLOCKED_UNTIL_ALL_SIX_FACTOR_FAMILIES_COMPLETE",
        **safety(),
        "is_official_weight": "FALSE",
    }]
    if not mappings:
        mappings = [{
            "ticker": "",
            "source_exposure_field": "",
            "source_exposure_value": "",
            "mapped_theme_bucket": "",
            "mapped_benchmark_exposure": "",
            "mapped_regime_sensitivity_bucket": "",
            "mapping_method": "DETERMINISTIC_EXPOSURE_MAPPING_TABLE",
            "mapping_confidence": "NONE",
            "deterministic_mapping_used": "TRUE",
            "global_regime_copied_without_exposure_conditioning": "FALSE",
            "fabricated_values_created": "FALSE",
            "proxy_values_activated": "FALSE",
            "mapping_status": "NO_MAPPABLE_LOCAL_EXPOSURE_METADATA_FOUND",
            "mapping_blocker_reason": "NO_SAFE_EQUITY_EXPOSURE_SOURCE_FOUND_FOR_MISSING_CANDIDATES",
            **safety(),
        }]

    write_csv(OUT_SOURCE, SOURCE_FIELDS, output_rows)
    write_csv(OUT_SOURCE_AUDIT, SOURCE_AUDIT_FIELDS, audits)
    write_csv(OUT_MAPPING_AUDIT, MAPPING_FIELDS, mappings)
    write_csv(OUT_COVERAGE, COVERAGE_FIELDS, coverage_rows)
    write_csv(OUT_GATE, GATE_FIELDS, gate_rows)

    research_gate = first_value(V49_RESEARCH, "research_only_gate_status", "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE")
    official_gate = first_value(V49_OFFICIAL, "official_promotion_gate_status", "BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE")
    report = [
        "# V20.108-R8-R1 Market Regime Equity Sector Theme Exposure Expander Report",
        "",
        "## Current Result",
        f"- wrapper_status: {wrapper_status}",
        f"- candidate_count: {total}",
        f"- carried_forward_r8_candidate_count: {carried}",
        f"- newly_materialized_candidate_count: {newly}",
        f"- total_market_regime_materialized_candidate_count: {materialized}",
        f"- missing_candidate_count: {missing}",
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
        "## Source Policy",
        "- r8_etf_exposures_carried_forward_when_valid: TRUE",
        "- equity_expansion_requires_real_candidate_level_sector_industry_theme_metadata: TRUE",
        "- external_refresh_requires_ENABLE_MARKET_REGIME_EXPOSURE_REFRESH_TRUE: TRUE",
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
    print(f"CARRIED_FORWARD_R8_CANDIDATE_COUNT={carried}")
    print(f"NEWLY_MATERIALIZED_CANDIDATE_COUNT={newly}")
    print(f"TOTAL_MARKET_REGIME_MATERIALIZED_CANDIDATE_COUNT={materialized}")
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
    print(f"OUTPUT_SOURCE_AUDIT={rel(OUT_SOURCE_AUDIT)}")
    print(f"OUTPUT_MAPPING_AUDIT={rel(OUT_MAPPING_AUDIT)}")
    print(f"OUTPUT_COVERAGE={rel(OUT_COVERAGE)}")
    print(f"OUTPUT_NEXT_STAGE_GATE={rel(OUT_GATE)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
