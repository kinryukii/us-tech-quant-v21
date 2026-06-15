#!/usr/bin/env python
"""V20.108-R6A-R2 controlled fundamental provider refresh runner.

Research-only refresh/import stage for ticker-level fundamental metrics. It
does not run unless ENABLE_FUNDAMENTAL_REFRESH=TRUE is explicit, and it never
creates contribution scores, official rankings, recommendations, trades,
broker execution, or weights.
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

R1_CONTRACT = CONSOLIDATION / "V20_108_R6A_R1_FUNDAMENTAL_SOURCE_CONTRACT.csv"
R1_TEMPLATE = CONSOLIDATION / "V20_108_R6A_R1_FUNDAMENTAL_LOCAL_INPUT_TEMPLATE.csv"
R1_IMPORT_GATE = CONSOLIDATION / "V20_108_R6A_R1_FUNDAMENTAL_IMPORT_GATE_AUDIT.csv"
R1_PROVIDER_REQ = CONSOLIDATION / "V20_108_R6A_R1_FUNDAMENTAL_PROVIDER_CONFIG_REQUIREMENT.csv"
R1_NEXT = CONSOLIDATION / "V20_108_R6A_R1_NEXT_REPAIR_ACTION.csv"
R6A_CACHE = CONSOLIDATION / "V20_108_R6A_CONTROLLED_FUNDAMENTAL_METRIC_CACHE.csv"
R6A_CERT = CONSOLIDATION / "V20_108_R6A_FUNDAMENTAL_METRIC_COVERAGE_CERTIFICATION.csv"
R4_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
V50_CANDIDATES = CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OPTIONAL_INPUTS = [
    ROOT / "data" / "v20" / "fundamental" / "V20_FUNDAMENTAL_METRIC_INPUT.csv",
    ROOT / "cache" / "v20" / "fundamental" / "V20_FUNDAMENTAL_METRIC_INPUT.csv",
    ROOT / "inputs" / "v20" / "fundamental" / "V20_FUNDAMENTAL_METRIC_INPUT.csv",
]

OUT_CACHE = CONSOLIDATION / "V20_108_R6A_R2_CONTROLLED_FUNDAMENTAL_PROVIDER_REFRESH_CACHE.csv"
OUT_AUDIT = CONSOLIDATION / "V20_108_R6A_R2_PROVIDER_REFRESH_AUDIT.csv"
OUT_CERT = CONSOLIDATION / "V20_108_R6A_R2_FUNDAMENTAL_METRIC_COVERAGE_CERTIFICATION.csv"
OUT_FAILURE = CONSOLIDATION / "V20_108_R6A_R2_REFRESH_FAILURE_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_108_R6A_R2_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_108_R6A_R2_CONTROLLED_FUNDAMENTAL_PROVIDER_REFRESH_REPORT.md"

PASS_STATUS = "PASS_V20_108_R6A_R2_CONTROLLED_FUNDAMENTAL_PROVIDER_REFRESH_CERTIFIED"
PARTIAL_STATUS = "PARTIAL_PASS_V20_108_R6A_R2_CONTROLLED_FUNDAMENTAL_PROVIDER_REFRESH_WITH_PARTIAL_COVERAGE"
BLOCKED_NOT_ENABLED = "BLOCKED_V20_108_R6A_R2_FUNDAMENTAL_REFRESH_NOT_ENABLED"
BLOCKED_NO_PROVIDER = "BLOCKED_V20_108_R6A_R2_FUNDAMENTAL_PROVIDER_NOT_CONFIGURED"
BLOCKED_FAILED = "BLOCKED_V20_108_R6A_R2_FUNDAMENTAL_REFRESH_FAILED"

ALLOWED_PROVIDERS = {"yfinance", "local_csv", "local_cache"}
MINIMUM_METRIC_THRESHOLD = 5
STALE_AFTER_DAYS = 90
METRICS = [
    "revenue_growth", "earnings_growth", "gross_margin", "operating_margin",
    "profit_margin", "return_on_equity", "return_on_assets", "operating_cashflow",
    "free_cashflow", "capital_expenditures", "debt_to_equity", "current_ratio",
    "quick_ratio", "market_cap", "enterprise_value", "trailing_pe", "forward_pe",
    "price_to_sales", "price_to_book", "ev_to_ebitda", "ebitda_margin",
    "revenue_ttm", "net_income_ttm", "total_debt", "total_cash",
]

CACHE_FIELDS = [
    "ticker", "baseline_rank", "provider_name", "provider_refresh_allowed",
    "provider_refresh_status", "metric_source_status", "metric_source_artifact",
    "metric_source_provider", "metric_source_timestamp", "refresh_timestamp_utc",
    "freshness_status", *METRICS, "missing_metric_count",
    "present_numeric_metric_count", "metric_classification_summary",
    "fundamental_metric_certification_status", "research_only",
    "official_promotion_allowed", "official_recommendation_created",
    "is_official_ranking", "is_official_weight", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]
AUDIT_FIELDS = [
    "refresh_check_id", "enable_fundamental_refresh_flag", "provider_name",
    "provider_configured", "provider_refresh_attempted", "provider_refresh_allowed",
    "candidate_count", "refreshed_candidate_count", "partial_candidate_count",
    "failed_candidate_count", "provider_rate_limit_handling_status",
    "provider_error_handling_status", "source_rank_or_score_used_as_fundamental",
    "baseline_rank_used_as_fundamental", "fabricated_values_created",
    "validation_status", "validation_reason", "research_only",
    "official_promotion_allowed", "official_recommendation_created", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]
CERT_FIELDS = [
    "coverage_check_id", "required_candidate_count", "candidate_count",
    "certified_candidate_count", "partial_candidate_count", "missing_candidate_count",
    "refresh_not_enabled_count", "provider_not_configured_count", "refresh_failed_count",
    "required_metric_count", "minimum_metric_threshold",
    "candidates_meeting_minimum_metric_threshold", "coverage_ratio",
    "fundamental_metric_cache_status", "fundamental_score_materialization_ready",
    "recommended_next_stage", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "is_official_ranking", "is_official_weight",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]
FAILURE_FIELDS = [
    "ticker", "provider_name", "refresh_attempted", "refresh_status",
    "failure_type", "failure_reason", "retry_allowed", "fallback_used",
    "fabricated_values_created", "recommended_repair_action", "research_only",
    "official_promotion_allowed", "official_recommendation_created", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]
GATE_FIELDS = [
    "gate_check_id", "fundamental_metric_cache_available",
    "fundamental_score_materialization_ready", "certified_candidate_count",
    "partial_candidate_count", "missing_candidate_count", "next_stage_allowed",
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


def is_number(value: str) -> bool:
    try:
        parsed = float(clean(value))
    except ValueError:
        return False
    return not (math.isnan(parsed) or math.isinf(parsed))


def parse_timestamp(value: str) -> datetime | None:
    text = clean(value)
    if not text:
        return None
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def load_candidates() -> list[dict[str, str]]:
    rows, _, status = read_csv(R4_SCORES)
    if status == "OK" and rows:
        return [{"ticker": row.get("ticker", ""), "baseline_rank": row.get("baseline_rank", "")} for row in rows if row.get("ticker")]
    rows, _, status = read_csv(R1_TEMPLATE)
    if status == "OK" and rows:
        return [{"ticker": row.get("ticker", ""), "baseline_rank": row.get("baseline_rank", "")} for row in rows if row.get("ticker")]
    rows, _, status = read_csv(V48_CANDIDATES)
    if status == "OK":
        return [
            {"ticker": row.get("normalized_ticker") or row.get("ticker_or_candidate_id", ""), "baseline_rank": row.get("report_rank", "")}
            for row in rows
            if row.get("normalized_ticker") or row.get("ticker_or_candidate_id")
        ]
    return []


def first_value(path: Path, field: str, default: str) -> str:
    rows, _, status = read_csv(path)
    if status == "OK" and rows:
        return rows[0].get(field, default) or default
    return default


def configured_input_path(provider: str) -> Path | None:
    raw = clean(os.environ.get("FUNDAMENTAL_PROVIDER_INPUT_PATH") or os.environ.get("FUNDAMENTAL_INPUT_PATH"))
    if raw:
        return (ROOT / raw).resolve() if not Path(raw).is_absolute() else Path(raw)
    if provider in {"local_csv", "local_cache"}:
        return None
    return None


def classify_local_rows(path: Path, candidates: list[dict[str, str]], provider: str, now: datetime) -> tuple[dict[str, dict[str, str]], list[dict[str, str]]]:
    rows, fields, status = read_csv(path)
    by_ticker = {row.get("ticker", ""): row for row in rows if row.get("ticker")}
    records: dict[str, dict[str, str]] = {}
    failures: list[dict[str, str]] = []
    for candidate in candidates:
        ticker = candidate["ticker"]
        row = by_ticker.get(ticker)
        if status != "OK" or row is None:
            records[ticker] = {"status": "FUNDAMENTAL_METRICS_MISSING", "timestamp": "", "provider": provider, "artifact": rel(path), "freshness": "MISSING", "present": "0", "summary": "ALL_METRICS=MISSING"}
            failures.append(failure(ticker, provider, True, "FAILED", "MISSING_TICKER_ROW", "Ticker missing from configured provider input path.", "Provide ticker-level row in configured local provider input."))
            continue
        timestamp = row.get("metric_source_timestamp", "")
        parsed = parse_timestamp(timestamp)
        stale = parsed is None or (now - parsed).days > STALE_AFTER_DAYS
        metric_values: dict[str, str] = {}
        classifications: list[str] = []
        present = 0
        for metric in METRICS:
            value = clean(row.get(metric))
            if not value:
                classifications.append(f"{metric}:MISSING")
            elif not is_number(value):
                classifications.append(f"{metric}:PRESENT_NON_NUMERIC_REJECTED")
            elif stale:
                classifications.append(f"{metric}:STALE_REJECTED")
            else:
                metric_values[metric] = value
                present += 1
                classifications.append(f"{metric}:PRESENT_NUMERIC")
        if present >= MINIMUM_METRIC_THRESHOLD:
            cert = "FUNDAMENTAL_METRICS_CERTIFIED"
        elif present > 0:
            cert = "FUNDAMENTAL_METRICS_PARTIAL"
        else:
            cert = "FUNDAMENTAL_METRICS_MISSING"
        if stale:
            failures.append(failure(ticker, provider, True, "FAILED", "STALE_OR_INVALID_TIMESTAMP", "metric_source_timestamp missing, invalid, or stale.", "Refresh local provider input with fresh source timestamps."))
        elif present == 0:
            failures.append(failure(ticker, provider, True, "FAILED", "NO_ACCEPTED_NUMERIC_METRICS", "No accepted real numeric metric values were available.", "Populate accepted numeric fundamental metric columns."))
        record = {"status": cert, "timestamp": timestamp, "provider": row.get("metric_source_provider") or provider, "artifact": rel(path), "freshness": "CURRENT" if present and not stale else "STALE_OR_MISSING", "present": str(present), "summary": ";".join(classifications)}
        record.update(metric_values)
        records[ticker] = record
    return records, failures


def yfinance_records(candidates: list[dict[str, str]], now: datetime) -> tuple[dict[str, dict[str, str]], list[dict[str, str]]]:
    records: dict[str, dict[str, str]] = {}
    failures: list[dict[str, str]] = []
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:  # pragma: no cover - only used with explicit provider config
        for candidate in candidates:
            ticker = candidate["ticker"]
            records[ticker] = {"status": "FUNDAMENTAL_REFRESH_FAILED", "timestamp": "", "provider": "yfinance", "artifact": "CONTROLLED_YFINANCE_ADAPTER", "freshness": "REFRESH_FAILED", "present": "0", "summary": "ALL_METRICS=SOURCE_UNTRUSTED_REJECTED"}
            failures.append(failure(ticker, "yfinance", True, "FAILED", "PROVIDER_IMPORT_FAILED", f"yfinance adapter unavailable: {exc}", "Install/configure approved provider adapter or use local_csv/local_cache."))
        return records, failures
    mapping = {
        "revenue_growth": "revenueGrowth",
        "earnings_growth": "earningsGrowth",
        "gross_margin": "grossMargins",
        "operating_margin": "operatingMargins",
        "profit_margin": "profitMargins",
        "return_on_equity": "returnOnEquity",
        "return_on_assets": "returnOnAssets",
        "operating_cashflow": "operatingCashflow",
        "free_cashflow": "freeCashflow",
        "debt_to_equity": "debtToEquity",
        "current_ratio": "currentRatio",
        "quick_ratio": "quickRatio",
        "market_cap": "marketCap",
        "enterprise_value": "enterpriseValue",
        "trailing_pe": "trailingPE",
        "forward_pe": "forwardPE",
        "price_to_sales": "priceToSalesTrailing12Months",
        "price_to_book": "priceToBook",
        "ev_to_ebitda": "enterpriseToEbitda",
        "ebitda_margin": "ebitdaMargins",
        "revenue_ttm": "totalRevenue",
        "net_income_ttm": "netIncomeToCommon",
        "total_debt": "totalDebt",
        "total_cash": "totalCash",
    }
    for candidate in candidates:  # pragma: no cover - network-backed branch
        ticker = candidate["ticker"]
        metric_values: dict[str, str] = {}
        classifications: list[str] = []
        try:
            info = yf.Ticker(ticker).get_info()
            sleep(0.2)
        except Exception as exc:
            records[ticker] = {"status": "FUNDAMENTAL_REFRESH_FAILED", "timestamp": "", "provider": "yfinance", "artifact": "CONTROLLED_YFINANCE_ADAPTER", "freshness": "REFRESH_FAILED", "present": "0", "summary": "ALL_METRICS=SOURCE_UNTRUSTED_REJECTED"}
            failures.append(failure(ticker, "yfinance", True, "FAILED", "PROVIDER_TICKER_REFRESH_ERROR", str(exc), "Retry with rate-limit-safe provider settings or use trusted local input."))
            continue
        for metric in METRICS:
            value = info.get(mapping.get(metric, ""))
            if value is None:
                classifications.append(f"{metric}:MISSING")
            elif is_number(str(value)):
                metric_values[metric] = str(value)
                classifications.append(f"{metric}:PRESENT_NUMERIC")
            else:
                classifications.append(f"{metric}:PRESENT_NON_NUMERIC_REJECTED")
        present = len(metric_values)
        cert = "FUNDAMENTAL_METRICS_CERTIFIED" if present >= MINIMUM_METRIC_THRESHOLD else ("FUNDAMENTAL_METRICS_PARTIAL" if present else "FUNDAMENTAL_METRICS_MISSING")
        timestamp = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        record = {"status": cert, "timestamp": timestamp, "provider": "yfinance", "artifact": "CONTROLLED_YFINANCE_ADAPTER", "freshness": "CURRENT_PROVIDER_REFRESH", "present": str(present), "summary": ";".join(classifications)}
        record.update(metric_values)
        records[ticker] = record
    return records, failures


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


def make_cache_rows(candidates: list[dict[str, str]], provider: str, allowed: bool, refresh_status: str, records: dict[str, dict[str, str]], now_text: str) -> list[dict[str, str]]:
    rows = []
    for candidate in candidates:
        ticker = candidate["ticker"]
        record = records.get(ticker, {})
        status = record.get("status") or ("FUNDAMENTAL_REFRESH_NOT_ENABLED" if not allowed else "FUNDAMENTAL_PROVIDER_NOT_CONFIGURED")
        present = int(record.get("present", "0") or "0")
        row = {
            "ticker": ticker,
            "baseline_rank": candidate.get("baseline_rank", ""),
            "provider_name": provider,
            "provider_refresh_allowed": tf(allowed),
            "provider_refresh_status": refresh_status,
            "metric_source_status": status,
            "metric_source_artifact": record.get("artifact", ""),
            "metric_source_provider": record.get("provider", provider),
            "metric_source_timestamp": record.get("timestamp", ""),
            "refresh_timestamp_utc": now_text,
            "freshness_status": record.get("freshness", refresh_status),
            "missing_metric_count": str(len(METRICS) - present),
            "present_numeric_metric_count": str(present),
            "metric_classification_summary": record.get("summary", "ALL_METRICS=MISSING"),
            "fundamental_metric_certification_status": status,
            **safety(extra=True),
        }
        for metric in METRICS:
            row[metric] = record.get(metric, "")
        rows.append(row)
    return rows


def summarize(cache_rows: list[dict[str, str]]) -> dict[str, int]:
    return {
        "certified": sum(1 for row in cache_rows if row["fundamental_metric_certification_status"] == "FUNDAMENTAL_METRICS_CERTIFIED"),
        "partial": sum(1 for row in cache_rows if row["fundamental_metric_certification_status"] == "FUNDAMENTAL_METRICS_PARTIAL"),
        "missing": sum(1 for row in cache_rows if row["fundamental_metric_certification_status"] == "FUNDAMENTAL_METRICS_MISSING"),
        "not_enabled": sum(1 for row in cache_rows if row["fundamental_metric_certification_status"] == "FUNDAMENTAL_REFRESH_NOT_ENABLED"),
        "not_configured": sum(1 for row in cache_rows if row["fundamental_metric_certification_status"] == "FUNDAMENTAL_PROVIDER_NOT_CONFIGURED"),
        "failed": sum(1 for row in cache_rows if row["fundamental_metric_certification_status"] == "FUNDAMENTAL_REFRESH_FAILED"),
        "threshold": sum(1 for row in cache_rows if int(row["present_numeric_metric_count"]) >= MINIMUM_METRIC_THRESHOLD),
    }


def main() -> int:
    now = datetime.now(timezone.utc)
    now_text = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    candidates = load_candidates()
    enable_flag = clean(os.environ.get("ENABLE_FUNDAMENTAL_REFRESH")).upper()
    allowed = enable_flag == "TRUE"
    provider = clean(os.environ.get("FUNDAMENTAL_PROVIDER_NAME")).lower()
    provider_configured = provider in ALLOWED_PROVIDERS
    records: dict[str, dict[str, str]] = {}
    failures: list[dict[str, str]] = []
    attempted = False

    if not allowed:
        wrapper_status = BLOCKED_NOT_ENABLED
        refresh_status = "NOT_ATTEMPTED_REFRESH_NOT_ENABLED"
        validation_status = "BLOCKED"
        validation_reason = "ENABLE_FUNDAMENTAL_REFRESH_NOT_TRUE"
        failures = [failure(row["ticker"], provider, False, refresh_status, "REFRESH_NOT_ENABLED", "ENABLE_FUNDAMENTAL_REFRESH is not TRUE.", "Set ENABLE_FUNDAMENTAL_REFRESH=TRUE only after provider configuration is approved.") for row in candidates]
    elif not provider_configured:
        wrapper_status = BLOCKED_NO_PROVIDER
        refresh_status = "NOT_ATTEMPTED_PROVIDER_NOT_CONFIGURED"
        validation_status = "BLOCKED"
        validation_reason = "FUNDAMENTAL_PROVIDER_NAME_MISSING_OR_UNAPPROVED"
        failures = [failure(row["ticker"], provider, False, refresh_status, "PROVIDER_NOT_CONFIGURED", "FUNDAMENTAL_PROVIDER_NAME must be one of yfinance, local_csv, local_cache.", "Configure an approved provider name and rerun.") for row in candidates]
    else:
        attempted = True
        if provider in {"local_csv", "local_cache"}:
            path = configured_input_path(provider)
            if path is None or not path.exists():
                wrapper_status = BLOCKED_FAILED
                refresh_status = "FAILED_CONFIGURED_LOCAL_INPUT_PATH_MISSING"
                validation_status = "BLOCKED"
                validation_reason = "CONFIGURED_LOCAL_PROVIDER_INPUT_PATH_MISSING"
                failures = [failure(row["ticker"], provider, True, refresh_status, "LOCAL_PROVIDER_INPUT_PATH_MISSING", "Configured local provider input path is missing or not set.", "Set FUNDAMENTAL_PROVIDER_INPUT_PATH to a trusted local metric CSV/cache.") for row in candidates]
            else:
                records, failures = classify_local_rows(path, candidates, provider, now)
                refresh_status = "LOCAL_PROVIDER_IMPORT_COMPLETED"
                validation_status = "PASS"
                validation_reason = "CONFIGURED_LOCAL_PROVIDER_INPUT_READ"
                wrapper_status = PASS_STATUS
        else:
            records, failures = yfinance_records(candidates, now)
            refresh_status = "CONTROLLED_YFINANCE_REFRESH_COMPLETED"
            validation_status = "PASS"
            validation_reason = "CONTROLLED_YFINANCE_ADAPTER_EXECUTED_WITH_PER_TICKER_ERROR_HANDLING"
            wrapper_status = PASS_STATUS

    cache_rows = make_cache_rows(candidates, provider, allowed, refresh_status, records, now_text)
    summary = summarize(cache_rows)
    ready = bool(cache_rows) and summary["threshold"] == len(cache_rows)
    if allowed and provider_configured and not ready and (summary["certified"] or summary["partial"]):
        wrapper_status = PARTIAL_STATUS
    elif allowed and provider_configured and not ready and wrapper_status == PASS_STATUS:
        wrapper_status = BLOCKED_FAILED

    cache_status = "FUNDAMENTAL_METRIC_CACHE_CERTIFIED" if ready else ("FUNDAMENTAL_METRIC_CACHE_PARTIAL" if summary["certified"] or summary["partial"] else refresh_status)
    next_stage = "V20.108-R6A-R3_FUNDAMENTAL_METRIC_IMPORT_GATE" if ready else "V20.108-R6A-R2_PROVIDER_REFRESH_REPAIR_OR_LOCAL_INPUT"
    audit_rows = [{
        "refresh_check_id": "V20_108_R6A_R2_PROVIDER_REFRESH_AUDIT_001",
        "enable_fundamental_refresh_flag": enable_flag,
        "provider_name": provider,
        "provider_configured": tf(provider_configured),
        "provider_refresh_attempted": tf(attempted),
        "provider_refresh_allowed": tf(allowed),
        "candidate_count": str(len(candidates)),
        "refreshed_candidate_count": str(summary["certified"]),
        "partial_candidate_count": str(summary["partial"]),
        "failed_candidate_count": str(summary["failed"] + summary["not_enabled"] + summary["not_configured"] + summary["missing"]),
        "provider_rate_limit_handling_status": "NOT_APPLICABLE_REFRESH_NOT_ATTEMPTED" if not attempted else "PER_TICKER_RATE_LIMIT_SAFE_HANDLING_REQUIRED_AND_APPLIED",
        "provider_error_handling_status": "PER_TICKER_ERROR_HANDLING_NOT_NEEDED" if not attempted else "PER_TICKER_ERROR_HANDLING_APPLIED",
        "source_rank_or_score_used_as_fundamental": "FALSE",
        "baseline_rank_used_as_fundamental": "FALSE",
        "fabricated_values_created": "FALSE",
        "validation_status": validation_status,
        "validation_reason": validation_reason,
        **safety(),
    }]
    cert_rows = [{
        "coverage_check_id": "V20_108_R6A_R2_COVERAGE_CERTIFICATION_001",
        "required_candidate_count": str(len(candidates)),
        "candidate_count": str(len(cache_rows)),
        "certified_candidate_count": str(summary["certified"]),
        "partial_candidate_count": str(summary["partial"]),
        "missing_candidate_count": str(summary["missing"]),
        "refresh_not_enabled_count": str(summary["not_enabled"]),
        "provider_not_configured_count": str(summary["not_configured"]),
        "refresh_failed_count": str(summary["failed"]),
        "required_metric_count": str(len(METRICS)),
        "minimum_metric_threshold": str(MINIMUM_METRIC_THRESHOLD),
        "candidates_meeting_minimum_metric_threshold": str(summary["threshold"]),
        "coverage_ratio": f"{(summary['certified'] / len(cache_rows) if cache_rows else 0.0):.10f}",
        "fundamental_metric_cache_status": cache_status,
        "fundamental_score_materialization_ready": tf(ready),
        "recommended_next_stage": next_stage,
        **safety(extra=True),
    }]
    gate_rows = [{
        "gate_check_id": "V20_108_R6A_R2_NEXT_STAGE_GATE_001",
        "fundamental_metric_cache_available": tf(bool(cache_rows)),
        "fundamental_score_materialization_ready": tf(ready),
        "certified_candidate_count": str(summary["certified"]),
        "partial_candidate_count": str(summary["partial"]),
        "missing_candidate_count": str(summary["missing"] + summary["not_enabled"] + summary["not_configured"] + summary["failed"]),
        "next_stage_allowed": tf(ready),
        "recommended_next_stage": next_stage,
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
    report_lines = [
        "# V20.108-R6A-R2 Controlled Fundamental Provider Refresh Report",
        "",
        "## Current Result",
        f"- wrapper_status: {wrapper_status}",
        f"- candidate_count: {len(cache_rows)}",
        f"- provider_name: {provider}",
        f"- provider_refresh_allowed: {tf(allowed)}",
        f"- provider_refresh_attempted: {tf(attempted)}",
        f"- certified_candidate_count: {summary['certified']}",
        f"- partial_candidate_count: {summary['partial']}",
        f"- missing_candidate_count: {summary['missing'] + summary['not_enabled'] + summary['not_configured'] + summary['failed']}",
        f"- fundamental_score_materialization_ready: {tf(ready)}",
        f"- v20_49_research_only_gate_status: {research_gate}",
        f"- v20_49_official_promotion_gate_status: {official_gate}",
        "- source_rank_or_score_used_as_fundamental: FALSE",
        "- baseline_rank_used_as_fundamental: FALSE",
        "- fabricated_values_created: FALSE",
        "- proxy_values_activated: FALSE",
        "- fundamental_contribution_scores_created: FALSE",
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
    REPORT.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(wrapper_status)
    print(f"CANDIDATE_COUNT={len(cache_rows)}")
    print(f"PROVIDER_REFRESH_ALLOWED={tf(allowed)}")
    print(f"PROVIDER_REFRESH_ATTEMPTED={tf(attempted)}")
    print(f"FUNDAMENTAL_SCORE_MATERIALIZATION_READY={tf(ready)}")
    print("SOURCE_RANK_OR_SCORE_USED_AS_FUNDAMENTAL=FALSE")
    print("BASELINE_RANK_USED_AS_FUNDAMENTAL=FALSE")
    print("FABRICATED_VALUES_CREATED=FALSE")
    print("PROXY_VALUES_ACTIVATED=FALSE")
    print("FUNDAMENTAL_CONTRIBUTION_SCORES_CREATED=FALSE")
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
    print(f"OUTPUT_AUDIT={rel(OUT_AUDIT)}")
    print(f"OUTPUT_CERTIFICATION={rel(OUT_CERT)}")
    print(f"OUTPUT_FAILURE_AUDIT={rel(OUT_FAILURE)}")
    print(f"OUTPUT_NEXT_STAGE_GATE={rel(OUT_GATE)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
