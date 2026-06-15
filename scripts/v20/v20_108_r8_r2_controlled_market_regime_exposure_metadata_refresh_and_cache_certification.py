#!/usr/bin/env python
"""V20.108-R8-R2 controlled market regime exposure metadata refresh.

Creates a research-only ticker-level exposure metadata cache. Provider refresh
is blocked unless ENABLE_MARKET_REGIME_EXPOSURE_REFRESH=TRUE and an approved
provider is configured. This stage never creates market_regime_contribution.
"""

from __future__ import annotations

import csv
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from time import sleep


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R8_R1_SOURCE = CONSOLIDATION / "V20_108_R8_R1_MARKET_REGIME_EQUITY_EXPOSURE_SOURCE.csv"
R8_R1_AUDIT = CONSOLIDATION / "V20_108_R8_R1_SECTOR_THEME_SOURCE_AUDIT.csv"
R8_R1_MAPPING = CONSOLIDATION / "V20_108_R8_R1_EXPOSURE_MAPPING_AUDIT.csv"
R8_R1_COVERAGE = CONSOLIDATION / "V20_108_R8_R1_MARKET_REGIME_COVERAGE_AFTER_EXPANSION.csv"
R8_R1_GATE = CONSOLIDATION / "V20_108_R8_R1_NEXT_STAGE_GATE.csv"
R8_SOURCE = CONSOLIDATION / "V20_108_R8_MARKET_REGIME_CANDIDATE_EXPOSURE_SOURCE.csv"
R8_COVERAGE = CONSOLIDATION / "V20_108_R8_FACTOR_FAMILY_COVERAGE_AFTER_MARKET_REGIME.csv"
R7_SOURCE = CONSOLIDATION / "V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE.csv"
R6B_SOURCE = CONSOLIDATION / "V20_108_R6B_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE.csv"
R4_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
V50_CANDIDATES = CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
ETF_REGIME = CONSOLIDATION / "V20_98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_AUDIT.csv"
ETF_RS = CONSOLIDATION / "V20_98C_ETF_PAIR_RELATIVE_STRENGTH_MATRIX.csv"
V106_BENCH = CONSOLIDATION / "V20_106_ETF_ROTATION_BENCHMARK_ALIGNMENT.csv"
V106_FACTOR = CONSOLIDATION / "V20_106_REGIME_CONDITIONED_FACTOR_ALIGNMENT.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OPTIONAL_INPUTS = [
    ROOT / "data" / "v20" / "market_regime" / "V20_MARKET_REGIME_EXPOSURE_METADATA_INPUT.csv",
    ROOT / "cache" / "v20" / "market_regime" / "V20_MARKET_REGIME_EXPOSURE_METADATA_INPUT.csv",
    ROOT / "inputs" / "v20" / "market_regime" / "V20_MARKET_REGIME_EXPOSURE_METADATA_INPUT.csv",
]

OUT_CACHE = CONSOLIDATION / "V20_108_R8_R2_CONTROLLED_MARKET_REGIME_EXPOSURE_METADATA_CACHE.csv"
OUT_AUDIT = CONSOLIDATION / "V20_108_R8_R2_EXPOSURE_METADATA_PROVIDER_AUDIT.csv"
OUT_CERT = CONSOLIDATION / "V20_108_R8_R2_EXPOSURE_METADATA_COVERAGE_CERTIFICATION.csv"
OUT_FAILURE = CONSOLIDATION / "V20_108_R8_R2_EXPOSURE_METADATA_FAILURE_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_108_R8_R2_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_108_R8_R2_CONTROLLED_MARKET_REGIME_EXPOSURE_METADATA_REFRESH_REPORT.md"

PASS_STATUS = "PASS_V20_108_R8_R2_CONTROLLED_MARKET_REGIME_EXPOSURE_METADATA_REFRESH_CERTIFIED"
PARTIAL_STATUS = "PARTIAL_PASS_V20_108_R8_R2_CONTROLLED_MARKET_REGIME_EXPOSURE_METADATA_REFRESH_WITH_PARTIAL_COVERAGE"
BLOCKED_NOT_ENABLED = "BLOCKED_V20_108_R8_R2_MARKET_REGIME_EXPOSURE_REFRESH_NOT_ENABLED"
BLOCKED_NO_PROVIDER = "BLOCKED_V20_108_R8_R2_MARKET_REGIME_EXPOSURE_PROVIDER_NOT_CONFIGURED"
BLOCKED_FAILED = "BLOCKED_V20_108_R8_R2_MARKET_REGIME_EXPOSURE_REFRESH_FAILED"

ALLOWED_PROVIDERS = {"yfinance", "local_csv", "local_cache"}
METADATA_FIELDS = [
    "instrument_type", "quote_type", "sector", "industry", "industry_key",
    "sector_key", "category", "fund_family", "business_summary", "country",
    "exchange", "benchmark_exposure_hint", "theme_hint", "is_etf_or_fund",
    "is_equity_or_adr", "is_crypto_or_bitcoin_linked", "is_non_equity_instrument",
]
MINIMUM_METADATA_THRESHOLD = 3

CACHE_FIELDS = [
    "ticker", "baseline_rank", "provider_name", "provider_refresh_allowed",
    "provider_refresh_status", "metadata_source_status", "metadata_source_artifact",
    "metadata_source_provider", "metadata_source_timestamp", "refresh_timestamp_utc",
    "freshness_status", "carried_forward_from_r8", *METADATA_FIELDS,
    "missing_metadata_count", "present_metadata_count",
    "exposure_metadata_certification_status", "market_regime_contribution_created",
    "fabricated_values_created", "global_regime_copied_without_exposure_conditioning",
    "entry_exit_prices_created", "buy_sell_recommendations_created",
    "shadow_rerank_output_created", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "is_official_ranking", "is_official_weight",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]
AUDIT_FIELDS = [
    "refresh_check_id", "enable_market_regime_exposure_refresh_flag", "provider_name",
    "provider_configured", "provider_refresh_attempted", "provider_refresh_allowed",
    "candidate_count", "carried_forward_r8_candidate_count", "refreshed_candidate_count",
    "partial_candidate_count", "missing_candidate_count", "failed_candidate_count",
    "provider_rate_limit_handling_status", "provider_error_handling_status",
    "source_rank_or_score_used_as_market_regime", "baseline_rank_used_as_market_regime",
    "fabricated_values_created", "global_regime_copied_without_exposure_conditioning",
    "market_regime_contribution_created", "validation_status", "validation_reason",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]
CERT_FIELDS = [
    "coverage_check_id", "required_candidate_count", "candidate_count",
    "carried_forward_r8_candidate_count", "certified_candidate_count",
    "partial_candidate_count", "missing_candidate_count", "refresh_not_enabled_count",
    "provider_not_configured_count", "refresh_failed_count", "minimum_metadata_threshold",
    "candidates_meeting_minimum_metadata_threshold", "coverage_ratio",
    "exposure_metadata_cache_status", "market_regime_materialization_ready",
    "recommended_next_stage", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "is_official_ranking", "is_official_weight",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]
FAILURE_FIELDS = [
    "ticker", "provider_name", "refresh_attempted", "refresh_status", "failure_type",
    "failure_reason", "retry_allowed", "fallback_used", "fabricated_values_created",
    "recommended_repair_action", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]
GATE_FIELDS = [
    "gate_check_id", "exposure_metadata_cache_available",
    "market_regime_materialization_ready", "carried_forward_r8_candidate_count",
    "certified_candidate_count", "partial_candidate_count", "missing_candidate_count",
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


def load_candidates() -> list[dict[str, str]]:
    rows, _, status = read_csv(R4_SCORES)
    if status == "OK":
        return [{"ticker": row["ticker"], "baseline_rank": row.get("baseline_rank", "")} for row in rows if row.get("ticker")]
    rows, _, status = read_csv(V48_CANDIDATES)
    return [{"ticker": row.get("normalized_ticker") or row.get("ticker_or_candidate_id", ""), "baseline_rank": row.get("report_rank", "")} for row in rows] if status == "OK" else []


def provider_input_path(provider: str) -> Path | None:
    raw = clean(os.environ.get("MARKET_REGIME_EXPOSURE_INPUT_PATH") or os.environ.get("MARKET_REGIME_EXPOSURE_PROVIDER_INPUT_PATH"))
    if raw:
        return Path(raw) if Path(raw).is_absolute() else (ROOT / raw).resolve()
    return None


def present_count(row: dict[str, str]) -> int:
    return sum(1 for field in METADATA_FIELDS if clean(row.get(field)))


def infer_flags(row: dict[str, str]) -> dict[str, str]:
    text = " ".join(clean(row.get(field)) for field in ("instrument_type", "quote_type", "category", "fund_family", "business_summary", "theme_hint")).lower()
    quote = clean(row.get("quote_type")).upper()
    is_fund = any(term in text for term in ("etf", "fund")) or quote in {"ETF", "MUTUALFUND"}
    is_crypto = any(term in text for term in ("crypto", "bitcoin", "btc"))
    is_equity = quote in {"EQUITY", "ADR"} or (not is_fund and not is_crypto and clean(row.get("sector")))
    return {
        "is_etf_or_fund": tf(is_fund),
        "is_equity_or_adr": tf(is_equity),
        "is_crypto_or_bitcoin_linked": tf(is_crypto),
        "is_non_equity_instrument": tf(is_fund or is_crypto or (quote and quote not in {"EQUITY", "ADR"})),
    }


def normalize_metadata_row(row: dict[str, str]) -> dict[str, str]:
    out = {field: clean(row.get(field)) for field in METADATA_FIELDS}
    aliases = {
        "instrument_type": ["asset_type", "security_type", "quoteType"],
        "quote_type": ["quoteType", "quote_type"],
        "industry_key": ["industryKey"],
        "sector_key": ["sectorKey"],
        "business_summary": ["longBusinessSummary", "business_description", "description"],
        "fund_family": ["fundFamily"],
    }
    for target, names in aliases.items():
        if out.get(target):
            continue
        for name in names:
            if clean(row.get(name)):
                out[target] = clean(row.get(name))
                break
    flags = infer_flags(out)
    for key, value in flags.items():
        if not out.get(key):
            out[key] = value
    return out


def load_local_metadata(path: Path, candidates: list[dict[str, str]], provider: str) -> tuple[dict[str, dict[str, str]], list[dict[str, str]]]:
    rows, fields, status = read_csv(path)
    by_ticker = {row.get("ticker", ""): row for row in rows if row.get("ticker")}
    metadata: dict[str, dict[str, str]] = {}
    failures: list[dict[str, str]] = []
    for candidate in candidates:
        ticker = candidate["ticker"]
        row = by_ticker.get(ticker)
        if status != "OK" or row is None:
            failures.append(failure(ticker, provider, True, "FAILED", "LOCAL_METADATA_MISSING", "Ticker missing from configured local metadata input.", "Provide ticker-level exposure metadata row."))
            continue
        meta = normalize_metadata_row(row)
        if present_count(meta) > 0:
            meta["_artifact"] = rel(path)
            meta["_provider"] = provider
            meta["_timestamp"] = clean(row.get("metadata_source_timestamp") or row.get("source_timestamp"))
            metadata[ticker] = meta
        else:
            failures.append(failure(ticker, provider, True, "FAILED", "NO_METADATA_FIELDS_PRESENT", "No accepted metadata fields present.", "Populate accepted exposure metadata columns."))
    return metadata, failures


def yfinance_metadata(candidates: list[dict[str, str]]) -> tuple[dict[str, dict[str, str]], list[dict[str, str]]]:
    metadata: dict[str, dict[str, str]] = {}
    failures: list[dict[str, str]] = []
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:  # pragma: no cover
        return {}, [failure(row["ticker"], "yfinance", True, "FAILED", "PROVIDER_IMPORT_FAILED", f"yfinance unavailable: {exc}", "Install/configure yfinance or use trusted local metadata input.") for row in candidates]
    for candidate in candidates:  # pragma: no cover - explicit network path only
        ticker = candidate["ticker"]
        try:
            info = yf.Ticker(ticker).get_info()
            sleep(0.2)
        except Exception as exc:
            failures.append(failure(ticker, "yfinance", True, "FAILED", "PROVIDER_TICKER_METADATA_ERROR", str(exc), "Retry provider metadata refresh or use trusted local metadata."))
            continue
        row = {
            "ticker": ticker,
            "instrument_type": clean(info.get("quoteType")),
            "quote_type": clean(info.get("quoteType")),
            "sector": clean(info.get("sector")),
            "industry": clean(info.get("industry")),
            "industry_key": clean(info.get("industryKey")),
            "sector_key": clean(info.get("sectorKey")),
            "category": clean(info.get("category")),
            "fund_family": clean(info.get("fundFamily")),
            "business_summary": clean(info.get("longBusinessSummary")),
            "country": clean(info.get("country")),
            "exchange": clean(info.get("exchange")),
        }
        meta = normalize_metadata_row(row)
        meta["_artifact"] = "CONTROLLED_YFINANCE_METADATA_REFRESH"
        meta["_provider"] = "yfinance"
        meta["_timestamp"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        metadata[ticker] = meta
    return metadata, failures


def failure(ticker: str, provider: str, attempted: bool, status: str, failure_type: str, reason: str, repair: str) -> dict[str, str]:
    return {
        "ticker": ticker,
        "provider_name": provider,
        "refresh_attempted": tf(attempted),
        "refresh_status": status,
        "failure_type": failure_type,
        "failure_reason": reason,
        "retry_allowed": "TRUE",
        "fallback_used": "FALSE",
        "fabricated_values_created": "FALSE",
        "recommended_repair_action": repair,
        **safety(),
    }


def first_value(path: Path, field: str, default: str) -> str:
    rows, _, status = read_csv(path)
    if status == "OK" and rows:
        return rows[0].get(field, default) or default
    return default


def main() -> int:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    candidates = load_candidates()
    r8_r1_rows, _, _ = read_csv(R8_R1_SOURCE)
    carried = {row["ticker"]: row for row in r8_r1_rows if row.get("carried_forward_from_r8") == "TRUE" and row.get("market_regime_contribution")}
    enable_flag = clean(os.environ.get("ENABLE_MARKET_REGIME_EXPOSURE_REFRESH")).upper()
    provider = clean(os.environ.get("MARKET_REGIME_EXPOSURE_PROVIDER_NAME")).lower()
    refresh_allowed = enable_flag == "TRUE"
    provider_configured = provider in ALLOWED_PROVIDERS
    attempted = False
    metadata: dict[str, dict[str, str]] = {}
    failures: list[dict[str, str]] = []
    provider_status = "NOT_ATTEMPTED"
    validation_status = "BLOCKED"
    validation_reason = ""

    for path in OPTIONAL_INPUTS:
        if path.exists():
            local_meta, local_failures = load_local_metadata(path, candidates, "local_csv" if "data" in [p.lower() for p in path.parts] else "local_cache")
            metadata.update(local_meta)
            failures.extend(local_failures)
            provider_status = "TRUSTED_LOCAL_METADATA_INPUT_READ"
            validation_status = "PASS"
            validation_reason = "TRUSTED_LOCAL_METADATA_INPUT_AVAILABLE"
            break

    if not metadata:
        if not refresh_allowed:
            provider_status = "NOT_ATTEMPTED_REFRESH_NOT_ENABLED"
            validation_status = "BLOCKED"
            validation_reason = "ENABLE_MARKET_REGIME_EXPOSURE_REFRESH_NOT_TRUE"
            failures = [failure(row["ticker"], provider, False, provider_status, "REFRESH_NOT_ENABLED", "ENABLE_MARKET_REGIME_EXPOSURE_REFRESH is not TRUE.", "Provide trusted local metadata input or explicitly enable approved provider refresh.") for row in candidates if row["ticker"] not in carried]
        elif not provider_configured:
            provider_status = "NOT_ATTEMPTED_PROVIDER_NOT_CONFIGURED"
            validation_status = "BLOCKED"
            validation_reason = "MARKET_REGIME_EXPOSURE_PROVIDER_NAME_MISSING_OR_UNAPPROVED"
            failures = [failure(row["ticker"], provider, False, provider_status, "PROVIDER_NOT_CONFIGURED", "Provider must be yfinance, local_csv, or local_cache.", "Configure an approved provider name.") for row in candidates if row["ticker"] not in carried]
        else:
            attempted = True
            if provider in {"local_csv", "local_cache"}:
                path = provider_input_path(provider)
                if path is None or not path.exists():
                    provider_status = "FAILED_CONFIGURED_LOCAL_METADATA_PATH_MISSING"
                    validation_reason = "CONFIGURED_LOCAL_METADATA_PATH_MISSING"
                    failures = [failure(row["ticker"], provider, True, provider_status, "LOCAL_METADATA_PATH_MISSING", "Configured provider input path is missing.", "Set MARKET_REGIME_EXPOSURE_INPUT_PATH to trusted local metadata CSV/cache.") for row in candidates if row["ticker"] not in carried]
                else:
                    metadata, failures = load_local_metadata(path, candidates, provider)
                    provider_status = "LOCAL_METADATA_IMPORT_COMPLETED"
                    validation_status = "PASS"
                    validation_reason = "CONFIGURED_LOCAL_PROVIDER_METADATA_READ"
            else:
                metadata, failures = yfinance_metadata([row for row in candidates if row["ticker"] not in carried])
                provider_status = "CONTROLLED_YFINANCE_METADATA_REFRESH_COMPLETED"
                validation_status = "PASS" if metadata else "BLOCKED"
                validation_reason = "CONTROLLED_YFINANCE_METADATA_REFRESH_EXECUTED"

    cache_rows: list[dict[str, str]] = []
    for candidate in candidates:
        ticker = candidate["ticker"]
        if ticker in carried:
            base = carried[ticker]
            meta = {field: "" for field in METADATA_FIELDS}
            meta.update({
                "instrument_type": base.get("instrument_type", "ETF_OR_FUND") or "ETF_OR_FUND",
                "quote_type": "ETF",
                "theme_hint": base.get("theme_bucket", "ETF_OR_FUND_INSTRUMENT_EXPOSURE"),
                "benchmark_exposure_hint": base.get("benchmark_exposure", ""),
                "is_etf_or_fund": "TRUE",
                "is_equity_or_adr": "FALSE",
                "is_crypto_or_bitcoin_linked": "FALSE",
                "is_non_equity_instrument": "TRUE",
            })
            status = "EXPOSURE_CARRIED_FORWARD_FROM_R8"
            artifact = base.get("exposure_source_artifact", "")
            source_provider = "local_output_artifact"
            timestamp = ""
            freshness = "CARRIED_FORWARD_VALID_R8_EXPOSURE"
        elif ticker in metadata:
            meta = metadata[ticker]
            count = present_count(meta)
            status = "EXPOSURE_METADATA_CERTIFIED" if count >= MINIMUM_METADATA_THRESHOLD else "EXPOSURE_METADATA_PARTIAL"
            artifact = meta.get("_artifact", "")
            source_provider = meta.get("_provider", provider)
            timestamp = meta.get("_timestamp", "")
            freshness = "CURRENT_METADATA_SOURCE"
        else:
            meta = {field: "" for field in METADATA_FIELDS}
            if not refresh_allowed and not metadata:
                status = "EXPOSURE_REFRESH_NOT_ENABLED"
            elif refresh_allowed and not provider_configured:
                status = "EXPOSURE_PROVIDER_NOT_CONFIGURED"
            elif attempted:
                status = "EXPOSURE_REFRESH_FAILED"
            else:
                status = "EXPOSURE_METADATA_MISSING"
            artifact = ""
            source_provider = provider
            timestamp = ""
            freshness = provider_status
        present = present_count(meta)
        row = {
            "ticker": ticker,
            "baseline_rank": candidate.get("baseline_rank", ""),
            "provider_name": provider,
            "provider_refresh_allowed": tf(refresh_allowed),
            "provider_refresh_status": provider_status,
            "metadata_source_status": status,
            "metadata_source_artifact": artifact,
            "metadata_source_provider": source_provider,
            "metadata_source_timestamp": timestamp,
            "refresh_timestamp_utc": now,
            "freshness_status": freshness,
            "carried_forward_from_r8": tf(ticker in carried),
            **{field: meta.get(field, "") for field in METADATA_FIELDS},
            "missing_metadata_count": str(len(METADATA_FIELDS) - present),
            "present_metadata_count": str(present),
            "exposure_metadata_certification_status": status,
            "market_regime_contribution_created": "FALSE",
            "fabricated_values_created": "FALSE",
            "global_regime_copied_without_exposure_conditioning": "FALSE",
            "entry_exit_prices_created": "FALSE",
            "buy_sell_recommendations_created": "FALSE",
            "shadow_rerank_output_created": "FALSE",
            **safety(extra=True),
        }
        cache_rows.append(row)

    certified = sum(1 for row in cache_rows if row["exposure_metadata_certification_status"] == "EXPOSURE_METADATA_CERTIFIED")
    partial = sum(1 for row in cache_rows if row["exposure_metadata_certification_status"] == "EXPOSURE_METADATA_PARTIAL")
    carried_count = sum(1 for row in cache_rows if row["exposure_metadata_certification_status"] == "EXPOSURE_CARRIED_FORWARD_FROM_R8")
    not_enabled = sum(1 for row in cache_rows if row["exposure_metadata_certification_status"] == "EXPOSURE_REFRESH_NOT_ENABLED")
    not_configured = sum(1 for row in cache_rows if row["exposure_metadata_certification_status"] == "EXPOSURE_PROVIDER_NOT_CONFIGURED")
    failed = sum(1 for row in cache_rows if row["exposure_metadata_certification_status"] == "EXPOSURE_REFRESH_FAILED")
    missing = sum(1 for row in cache_rows if row["exposure_metadata_certification_status"] == "EXPOSURE_METADATA_MISSING")
    threshold_count = certified + carried_count
    ready = bool(cache_rows) and threshold_count == len(cache_rows)

    if ready:
        wrapper_status = PASS_STATUS
    elif certified or partial or carried_count:
        wrapper_status = PARTIAL_STATUS if metadata else BLOCKED_NOT_ENABLED if not refresh_allowed else (BLOCKED_NO_PROVIDER if not provider_configured else BLOCKED_FAILED)
    elif not refresh_allowed:
        wrapper_status = BLOCKED_NOT_ENABLED
    elif not provider_configured:
        wrapper_status = BLOCKED_NO_PROVIDER
    else:
        wrapper_status = BLOCKED_FAILED

    audit_rows = [{
        "refresh_check_id": "V20_108_R8_R2_PROVIDER_AUDIT_001",
        "enable_market_regime_exposure_refresh_flag": enable_flag,
        "provider_name": provider,
        "provider_configured": tf(provider_configured),
        "provider_refresh_attempted": tf(attempted),
        "provider_refresh_allowed": tf(refresh_allowed),
        "candidate_count": str(len(cache_rows)),
        "carried_forward_r8_candidate_count": str(carried_count),
        "refreshed_candidate_count": str(certified),
        "partial_candidate_count": str(partial),
        "missing_candidate_count": str(missing + not_enabled + not_configured),
        "failed_candidate_count": str(failed),
        "provider_rate_limit_handling_status": "NOT_APPLICABLE_REFRESH_NOT_ATTEMPTED" if not attempted else "PER_TICKER_RATE_LIMIT_SAFE_HANDLING_APPLIED",
        "provider_error_handling_status": "PER_TICKER_ERROR_HANDLING_NOT_NEEDED" if not attempted else "PER_TICKER_ERROR_HANDLING_APPLIED",
        "source_rank_or_score_used_as_market_regime": "FALSE",
        "baseline_rank_used_as_market_regime": "FALSE",
        "fabricated_values_created": "FALSE",
        "global_regime_copied_without_exposure_conditioning": "FALSE",
        "market_regime_contribution_created": "FALSE",
        "validation_status": validation_status,
        "validation_reason": validation_reason,
        **safety(),
    }]
    cert_rows = [{
        "coverage_check_id": "V20_108_R8_R2_COVERAGE_CERTIFICATION_001",
        "required_candidate_count": str(len(cache_rows)),
        "candidate_count": str(len(cache_rows)),
        "carried_forward_r8_candidate_count": str(carried_count),
        "certified_candidate_count": str(certified),
        "partial_candidate_count": str(partial),
        "missing_candidate_count": str(missing),
        "refresh_not_enabled_count": str(not_enabled),
        "provider_not_configured_count": str(not_configured),
        "refresh_failed_count": str(failed),
        "minimum_metadata_threshold": str(MINIMUM_METADATA_THRESHOLD),
        "candidates_meeting_minimum_metadata_threshold": str(threshold_count),
        "coverage_ratio": f"{(threshold_count / len(cache_rows) if cache_rows else 0.0):.10f}",
        "exposure_metadata_cache_status": "EXPOSURE_METADATA_CACHE_READY" if ready else provider_status,
        "market_regime_materialization_ready": tf(ready),
        "recommended_next_stage": "V20.108-R8-R3_MARKET_REGIME_EXPOSURE_METADATA_TO_CONTRIBUTION_MAPPER" if ready else "PROVIDE_TRUSTED_EXPOSURE_METADATA_OR_ENABLE_APPROVED_REFRESH",
        **safety(extra=True),
    }]
    gate_rows = [{
        "gate_check_id": "V20_108_R8_R2_NEXT_STAGE_GATE_001",
        "exposure_metadata_cache_available": tf(bool(cache_rows)),
        "market_regime_materialization_ready": tf(ready),
        "carried_forward_r8_candidate_count": str(carried_count),
        "certified_candidate_count": str(certified),
        "partial_candidate_count": str(partial),
        "missing_candidate_count": str(missing + not_enabled + not_configured + failed),
        "next_stage_allowed": tf(ready),
        "recommended_next_stage": "V20.108-R8-R3_MARKET_REGIME_EXPOSURE_METADATA_TO_CONTRIBUTION_MAPPER" if ready else "V20.108-R8-R2_EXPOSURE_METADATA_SOURCE_REPAIR",
        "blocking_reason": "" if ready else wrapper_status,
        **safety(),
        "is_official_weight": "FALSE",
    }]

    write_csv(OUT_CACHE, CACHE_FIELDS, cache_rows)
    write_csv(OUT_AUDIT, AUDIT_FIELDS, audit_rows)
    write_csv(OUT_CERT, CERT_FIELDS, cert_rows)
    write_csv(OUT_FAILURE, FAILURE_FIELDS, failures)
    write_csv(OUT_GATE, GATE_FIELDS, gate_rows)

    research_gate = first_value(V49_RESEARCH, "research_only_gate_status", "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE")
    official_gate = first_value(V49_OFFICIAL, "official_promotion_gate_status", "BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE")
    report = [
        "# V20.108-R8-R2 Controlled Market Regime Exposure Metadata Refresh Report",
        "",
        "## Current Result",
        f"- wrapper_status: {wrapper_status}",
        f"- candidate_count: {len(cache_rows)}",
        f"- carried_forward_r8_candidate_count: {carried_count}",
        f"- certified_candidate_count: {certified}",
        f"- partial_candidate_count: {partial}",
        f"- missing_candidate_count: {missing + not_enabled + not_configured + failed}",
        f"- provider_refresh_allowed: {tf(refresh_allowed)}",
        f"- provider_refresh_attempted: {tf(attempted)}",
        f"- market_regime_materialization_ready: {tf(ready)}",
        f"- v20_49_research_only_gate_status: {research_gate}",
        f"- v20_49_official_promotion_gate_status: {official_gate}",
        "- source_rank_or_score_used: FALSE",
        "- baseline_rank_used: FALSE",
        "- fabricated_values_created: FALSE",
        "- global_regime_copied_without_exposure_conditioning: FALSE",
        "- market_regime_contribution_created: FALSE",
        "- entry_exit_prices_created: FALSE",
        "- buy_sell_recommendations_created: FALSE",
        "- shadow_rerank_output_created: FALSE",
        "- official_ranking_created: FALSE",
        "- authoritative_ranking_overwritten: FALSE",
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
    print(f"CANDIDATE_COUNT={len(cache_rows)}")
    print(f"CARRIED_FORWARD_R8_CANDIDATE_COUNT={carried_count}")
    print(f"PROVIDER_REFRESH_ALLOWED={tf(refresh_allowed)}")
    print(f"PROVIDER_REFRESH_ATTEMPTED={tf(attempted)}")
    print(f"MARKET_REGIME_MATERIALIZATION_READY={tf(ready)}")
    print("SOURCE_RANK_OR_SCORE_USED=FALSE")
    print("BASELINE_RANK_USED=FALSE")
    print("FABRICATED_VALUES_CREATED=FALSE")
    print("GLOBAL_REGIME_COPIED_WITHOUT_EXPOSURE_CONDITIONING=FALSE")
    print("MARKET_REGIME_CONTRIBUTION_CREATED=FALSE")
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
    print(f"OUTPUT_CACHE={rel(OUT_CACHE)}")
    print(f"OUTPUT_PROVIDER_AUDIT={rel(OUT_AUDIT)}")
    print(f"OUTPUT_CERTIFICATION={rel(OUT_CERT)}")
    print(f"OUTPUT_FAILURE_AUDIT={rel(OUT_FAILURE)}")
    print(f"OUTPUT_NEXT_STAGE_GATE={rel(OUT_GATE)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
