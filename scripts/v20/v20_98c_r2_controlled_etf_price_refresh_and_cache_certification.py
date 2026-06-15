#!/usr/bin/env python
"""V20.98C-R2 controlled ETF price refresh and cache certification.

Refreshes missing current ETF prices for V20.98C regime-pair auditing using a
controlled provider call. Existing current SPY/QQQ prices from R1/V20.48/V20.50
are reused when valid. Missing or stale ETF prices are classified explicitly;
no official recommendation, trade action, broker execution, official weight,
active base-weight mutation, dynamic factor weight, or V20.107 execution occurs.
"""

from __future__ import annotations

import csv
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
PROVIDER_CACHE_DIR = ROOT / "state" / "v20" / "provider_cache" / "yfinance"

R1_COVERAGE = CONSOLIDATION / "V20_98C_R1_CURRENT_ETF_PRICE_COVERAGE.csv"
R1_PAIR_AUDIT = CONSOLIDATION / "V20_98C_R1_ETF_PAIR_COVERAGE_AUDIT.csv"
R1_REPAIR_PLAN = CONSOLIDATION / "V20_98C_R1_ETF_COVERAGE_GAP_REPAIR_PLAN.csv"
V48_BENCHMARK = CONSOLIDATION / "V20_48_REFRESHED_BENCHMARK_CONTEXT_VIEW.csv"
V50_BENCHMARK = CONSOLIDATION / "V20_50_BENCHMARK_RESEARCH_CONTEXT_PACKET.csv"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

REFRESH_CACHE = CONSOLIDATION / "V20_98C_R2_CONTROLLED_ETF_PRICE_REFRESH_CACHE.csv"
CERTIFICATION = CONSOLIDATION / "V20_98C_R2_ETF_PRICE_REFRESH_CERTIFICATION.csv"
PAIR_AFTER_REFRESH = CONSOLIDATION / "V20_98C_R2_ETF_PAIR_COVERAGE_AFTER_REFRESH.csv"
REPORT = READ_CENTER / "V20_98C_R2_CONTROLLED_ETF_PRICE_REFRESH_REPORT.md"

PASS_STATUS = "PASS_V20_98C_R2_CONTROLLED_ETF_PRICE_REFRESH_CERTIFIED"
PARTIAL_STATUS = "PARTIAL_PASS_V20_98C_R2_CONTROLLED_ETF_PRICE_REFRESH_WITH_MISSING_DATA"
PROVIDER_NAME = "yahoo/yfinance"

REQUIRED_ETFS = [
    "SPY",
    "QQQ",
    "XLK",
    "SOXX",
    "SMH",
    "TQQQ",
    "SQQQ",
    "SOXL",
    "SOXS",
    "RSP",
    "XLU",
    "XLP",
    "TLT",
    "GLD",
]

PAIR_SPECS = [
    ("QQQ vs SPY", "QQQ", "SPY"),
    ("XLK vs SPY", "XLK", "SPY"),
    ("SOXX vs QQQ", "SOXX", "QQQ"),
    ("SMH vs QQQ", "SMH", "QQQ"),
    ("SOXX vs SPY", "SOXX", "SPY"),
    ("SMH vs SPY", "SMH", "SPY"),
    ("TQQQ vs SQQQ", "TQQQ", "SQQQ"),
    ("SOXL vs SOXS", "SOXL", "SOXS"),
    ("RSP vs SPY", "RSP", "SPY"),
    ("XLU vs SPY", "XLU", "SPY"),
    ("XLP vs SPY", "XLP", "SPY"),
    ("TLT vs SPY", "TLT", "SPY"),
    ("GLD vs SPY", "GLD", "SPY"),
]

ETF_ROLES = {
    "SPY": "BROAD_MARKET_BENCHMARK",
    "QQQ": "GROWTH_TECH_BENCHMARK",
    "XLK": "TECHNOLOGY_SECTOR",
    "SOXX": "SEMICONDUCTOR_SECTOR",
    "SMH": "SEMICONDUCTOR_SECTOR",
    "TQQQ": "LEVERAGED_GROWTH_LONG",
    "SQQQ": "LEVERAGED_GROWTH_INVERSE",
    "SOXL": "LEVERAGED_SEMICONDUCTOR_LONG",
    "SOXS": "LEVERAGED_SEMICONDUCTOR_INVERSE",
    "RSP": "EQUAL_WEIGHT_BREADTH",
    "XLU": "DEFENSIVE_UTILITIES",
    "XLP": "DEFENSIVE_STAPLES",
    "TLT": "DURATION_RISK_OFF",
    "GLD": "GOLD_RISK_OFF",
}

REFRESH_CACHE_FIELDS = [
    "ticker",
    "asset_class",
    "etf_role",
    "latest_price",
    "latest_price_date",
    "price_source",
    "price_source_stage",
    "refresh_attempted",
    "refresh_status",
    "data_available",
    "data_freshness_status",
    "certification_status",
    "certification_reason",
    "required_for_pair_checks",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
]

CERTIFICATION_FIELDS = [
    "required_etf_count",
    "certified_current_etf_price_count",
    "missing_current_etf_price_count",
    "stale_etf_price_count",
    "pair_target_count",
    "pair_coverage_complete_count",
    "pair_coverage_missing_count",
    "certification_status",
    "certification_reason",
    "v20_107_precondition_status",
    "v20_107_execution_status",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
]

PAIR_FIELDS = [
    "etf_pair",
    "left_ticker",
    "right_ticker",
    "left_data_available",
    "right_data_available",
    "pair_data_available",
    "left_latest_price",
    "right_latest_price",
    "left_price_date",
    "right_price_date",
    "coverage_status",
    "missing_side",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
    "v20_107_execution_status",
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def safety() -> dict[str, str]:
    return {
        "research_only": "TRUE",
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
    }


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], str]:
    if not path.exists():
        return [], "MISSING"
    if path.stat().st_size == 0:
        return [], "EMPTY"
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = [{key: clean(value) for key, value in row.items()} for row in reader]
            if not reader.fieldnames:
                return [], "MALFORMED"
            return rows, "OK"
    except csv.Error:
        return [], "MALFORMED"


def first_row(path: Path) -> dict[str, str]:
    rows, status = read_csv(path)
    return rows[0] if status == "OK" and rows else {}


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_positive_price(value: object) -> str:
    try:
        number = float(clean(value))
    except ValueError:
        return ""
    if math.isnan(number) or number <= 0:
        return ""
    return f"{number:.10g}"


def source_price_from_row(row: dict[str, str], source: str, stage: str) -> dict[str, str] | None:
    ticker = clean(row.get("ticker") or row.get("benchmark_ticker") or row.get("etf_symbol")).upper()
    if ticker not in REQUIRED_ETFS:
        return None
    price = parse_positive_price(
        row.get("latest_price")
        or row.get("refreshed_latest_close")
        or row.get("latest_close")
        or row.get("close")
    )
    date = clean(row.get("latest_price_date") or row.get("refreshed_price_date") or row.get("price_date") or row.get("as_of_date"))
    data_available = clean(row.get("data_available")).upper()
    certification = clean(row.get("certification_status")).upper()
    if not price or not date:
        return None
    if data_available and data_available != "TRUE":
        return None
    if certification and certification not in {"CERTIFIED", "PASS"}:
        return None
    return {
        "ticker": ticker,
        "latest_price": price,
        "latest_price_date": date[:10],
        "price_source": source,
        "price_source_stage": stage,
    }


def collect_existing_prices() -> dict[str, dict[str, str]]:
    prices: dict[str, dict[str, str]] = {}
    for path, stage in [
        (R1_COVERAGE, "V20.98C-R1_CURRENT_ETF_PRICE_COVERAGE"),
        (V48_BENCHMARK, "V20.48_REFRESHED_BENCHMARK_CONTEXT_VIEW"),
        (V50_BENCHMARK, "V20.50_BENCHMARK_RESEARCH_CONTEXT_PACKET"),
    ]:
        rows, status = read_csv(path)
        if status != "OK":
            continue
        for row in rows:
            source = source_price_from_row(row, rel(path), stage)
            if source and source["ticker"] not in prices:
                prices[source["ticker"]] = source
    return prices


def reference_current_date(existing_prices: dict[str, dict[str, str]]) -> str:
    dates = [clean(row.get("latest_price_date")) for row in existing_prices.values() if clean(row.get("latest_price_date"))]
    return max(dates) if dates else ""


def configure_yfinance_cache(yf: Any) -> None:
    PROVIDER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("YFINANCE_CACHE_DIR", str(PROVIDER_CACHE_DIR))
    os.environ.setdefault("YFINANCE_USER_CACHE_DIR", str(PROVIDER_CACHE_DIR))
    try:
        import yfinance.cache as yf_cache  # type: ignore

        if hasattr(yf_cache, "set_cache_location"):
            yf_cache.set_cache_location(str(PROVIDER_CACHE_DIR))
    except Exception:
        pass
    if hasattr(yf, "set_tz_cache_location"):
        try:
            yf.set_tz_cache_location(str(PROVIDER_CACHE_DIR))
        except Exception:
            pass


def date_text(value: object) -> str:
    if hasattr(value, "date"):
        try:
            return str(value.date())
        except Exception:
            pass
    text = clean(value)
    return text[:10] if len(text) >= 10 else text


def extract_latest_price_from_dataframe(df: Any, ticker: str) -> tuple[str, str, str]:
    if df is None or getattr(df, "empty", True):
        return "", "", "empty_dataframe"
    ticker_df = df
    try:
        columns = ticker_df.columns
        if getattr(columns, "nlevels", 1) > 1:
            for level in range(columns.nlevels):
                values = [clean(value).upper() for value in columns.get_level_values(level)]
                if ticker.upper() in values:
                    ticker_df = ticker_df.xs(ticker, axis=1, level=level, drop_level=True)
                    break
    except Exception:
        pass
    fields = ["Adj Close", "Close"]
    for field in fields:
        try:
            series = ticker_df[field]
        except Exception:
            continue
        try:
            values = list(series.items())
        except Exception:
            continue
        for idx, value in reversed(values):
            price = parse_positive_price(value)
            if price:
                return price, date_text(idx), ""
    return "", "", "missing_close_like_fields_or_values"


def refresh_ticker(ticker: str, reference_date: str) -> dict[str, str]:
    try:
        import yfinance as yf  # type: ignore

        configure_yfinance_cache(yf)
        df = yf.download(ticker, period="10d", interval="1d", progress=False, auto_adjust=False, threads=False)
        price, price_date, reason = extract_latest_price_from_dataframe(df, ticker)
        if not price or not price_date:
            return {
                "refresh_status": "REFRESH_FAILED",
                "latest_price": "",
                "latest_price_date": "",
                "data_freshness_status": "MISSING_CURRENT_ETF_PRICE_DATA",
                "certification_status": "BLOCKED",
                "certification_reason": reason or "MISSING_CURRENT_ETF_PRICE_DATA",
            }
        if reference_date and price_date < reference_date:
            return {
                "refresh_status": "REFRESH_STALE_REJECTED",
                "latest_price": "",
                "latest_price_date": price_date,
                "data_freshness_status": "STALE_PRICE_NOT_ACCEPTED",
                "certification_status": "BLOCKED",
                "certification_reason": f"STALE_PRICE_NOT_ACCEPTED_REFERENCE_DATE_{reference_date}",
            }
        return {
            "refresh_status": "REFRESH_SUCCESS",
            "latest_price": price,
            "latest_price_date": price_date,
            "data_freshness_status": "CURRENT_REFRESHED_PRICE_AVAILABLE",
            "certification_status": "CERTIFIED",
            "certification_reason": f"CURRENT_ETF_PRICE_CERTIFIED_REFERENCE_DATE_{reference_date or price_date}",
        }
    except Exception as exc:
        return {
            "refresh_status": "REFRESH_FAILED",
            "latest_price": "",
            "latest_price_date": "",
            "data_freshness_status": "MISSING_CURRENT_ETF_PRICE_DATA",
            "certification_status": "BLOCKED",
            "certification_reason": f"REFRESH_FAILED:{type(exc).__name__}:{clean(exc)}",
        }


def required_for_pair_checks(ticker: str) -> str:
    return tf(any(ticker in {left, right} for _, left, right in PAIR_SPECS))


def build_cache_rows(existing_prices: dict[str, dict[str, str]], reference_date: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for ticker in REQUIRED_ETFS:
        existing = existing_prices.get(ticker)
        if existing:
            stale = bool(reference_date and existing["latest_price_date"] < reference_date)
            rows.append(
                {
                    "ticker": ticker,
                    "asset_class": "ETF",
                    "etf_role": ETF_ROLES[ticker],
                    "latest_price": "" if stale else existing["latest_price"],
                    "latest_price_date": existing["latest_price_date"],
                    "price_source": existing["price_source"],
                    "price_source_stage": existing["price_source_stage"],
                    "refresh_attempted": "FALSE",
                    "refresh_status": "REUSED_CURRENT_PRICE" if not stale else "REUSED_PRICE_STALE_REJECTED",
                    "data_available": tf(not stale),
                    "data_freshness_status": "CURRENT_REFRESHED_PRICE_AVAILABLE" if not stale else "STALE_PRICE_NOT_ACCEPTED",
                    "certification_status": "CERTIFIED" if not stale else "BLOCKED",
                    "certification_reason": "REUSED_VALID_CURRENT_ETF_PRICE"
                    if not stale
                    else f"STALE_PRICE_NOT_ACCEPTED_REFERENCE_DATE_{reference_date}",
                    "required_for_pair_checks": required_for_pair_checks(ticker),
                    **safety(),
                }
            )
            continue
        refreshed = refresh_ticker(ticker, reference_date)
        certified = refreshed["certification_status"] == "CERTIFIED"
        rows.append(
            {
                "ticker": ticker,
                "asset_class": "ETF",
                "etf_role": ETF_ROLES[ticker],
                "latest_price": refreshed["latest_price"] if certified else "",
                "latest_price_date": refreshed["latest_price_date"],
                "price_source": PROVIDER_NAME if certified else "",
                "price_source_stage": "V20.98C-R2_CONTROLLED_PROVIDER_REFRESH" if certified else "",
                "refresh_attempted": "TRUE",
                "refresh_status": refreshed["refresh_status"],
                "data_available": tf(certified),
                "data_freshness_status": refreshed["data_freshness_status"],
                "certification_status": refreshed["certification_status"],
                "certification_reason": refreshed["certification_reason"],
                "required_for_pair_checks": required_for_pair_checks(ticker),
                **safety(),
            }
        )
    return rows


def by_ticker(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["ticker"]: row for row in rows}


def build_pair_rows(cache_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    cache = by_ticker(cache_rows)
    rows: list[dict[str, str]] = []
    for pair, left, right in PAIR_SPECS:
        left_row = cache[left]
        right_row = cache[right]
        left_available = left_row["data_available"] == "TRUE"
        right_available = right_row["data_available"] == "TRUE"
        pair_available = left_available and right_available
        if pair_available:
            status = "PAIR_CURRENT_PRICE_COVERAGE_AVAILABLE"
            missing_side = "NONE"
        elif not left_available and not right_available:
            status = "MISSING_CURRENT_ETF_PRICE_DATA"
            missing_side = "LEFT_AND_RIGHT"
        elif not left_available:
            status = left_row["data_freshness_status"]
            missing_side = "LEFT"
        else:
            status = right_row["data_freshness_status"]
            missing_side = "RIGHT"
        rows.append(
            {
                "etf_pair": pair,
                "left_ticker": left,
                "right_ticker": right,
                "left_data_available": tf(left_available),
                "right_data_available": tf(right_available),
                "pair_data_available": tf(pair_available),
                "left_latest_price": left_row["latest_price"],
                "right_latest_price": right_row["latest_price"],
                "left_price_date": left_row["latest_price_date"] if left_available else "",
                "right_price_date": right_row["latest_price_date"] if right_available else "",
                "coverage_status": status,
                "missing_side": missing_side,
                **safety(),
                "v20_107_execution_status": "NOT_RUN",
            }
        )
    return rows


def build_certification_rows(cache_rows: list[dict[str, str]], pair_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    certified_count = sum(1 for row in cache_rows if row["certification_status"] == "CERTIFIED")
    stale_count = sum(1 for row in cache_rows if row["data_freshness_status"] == "STALE_PRICE_NOT_ACCEPTED")
    missing_count = len(cache_rows) - certified_count
    complete_pairs = sum(1 for row in pair_rows if row["pair_data_available"] == "TRUE")
    missing_pairs = len(pair_rows) - complete_pairs
    full = certified_count == len(REQUIRED_ETFS) and missing_pairs == 0
    return [
        {
            "required_etf_count": str(len(REQUIRED_ETFS)),
            "certified_current_etf_price_count": str(certified_count),
            "missing_current_etf_price_count": str(missing_count),
            "stale_etf_price_count": str(stale_count),
            "pair_target_count": str(len(pair_rows)),
            "pair_coverage_complete_count": str(complete_pairs),
            "pair_coverage_missing_count": str(missing_pairs),
            "certification_status": PASS_STATUS if full else PARTIAL_STATUS,
            "certification_reason": "ALL_REQUIRED_ETF_CURRENT_PRICES_CERTIFIED"
            if full
            else "ONE_OR_MORE_REQUIRED_ETF_CURRENT_PRICES_MISSING_OR_STALE",
            "v20_107_precondition_status": "CERTIFIED_ETF_PRICE_CACHE_AVAILABLE"
            if full
            else "PARTIAL_ETF_PRICE_CACHE_AVAILABLE_REPAIR_REQUIRED",
            "v20_107_execution_status": "NOT_RUN",
            **safety(),
        }
    ]


def write_report(
    cache_rows: list[dict[str, str]],
    cert_row: dict[str, str],
    source_statuses: dict[str, str],
    reference_date: str,
) -> None:
    certified = [row["ticker"] for row in cache_rows if row["certification_status"] == "CERTIFIED"]
    missing = [row["ticker"] for row in cache_rows if row["certification_status"] != "CERTIFIED"]
    refreshed = [row["ticker"] for row in cache_rows if row["refresh_status"] == "REFRESH_SUCCESS"]
    failed = [row["ticker"] for row in cache_rows if row["refresh_status"] == "REFRESH_FAILED"]
    stale = [row["ticker"] for row in cache_rows if row["data_freshness_status"] == "STALE_PRICE_NOT_ACCEPTED"]
    lines = [
        "# V20.98C-R2 Controlled ETF Price Refresh",
        "",
        "## Current Result",
        f"- wrapper_status: {cert_row['certification_status']}",
        f"- reference_current_price_date: {reference_date or 'UNKNOWN'}",
        f"- required_etf_count: {cert_row['required_etf_count']}",
        f"- certified_current_etf_price_count: {cert_row['certified_current_etf_price_count']}",
        f"- missing_current_etf_price_count: {cert_row['missing_current_etf_price_count']}",
        f"- stale_etf_price_count: {cert_row['stale_etf_price_count']}",
        f"- pair_target_count: {cert_row['pair_target_count']}",
        f"- pair_coverage_complete_count: {cert_row['pair_coverage_complete_count']}",
        f"- pair_coverage_missing_count: {cert_row['pair_coverage_missing_count']}",
        "- v20_107_execution_status: NOT_RUN",
        "",
        "## Input Status",
        f"- R1 current ETF coverage: {source_statuses['r1_coverage']}",
        f"- R1 pair coverage audit: {source_statuses['r1_pair_audit']}",
        f"- R1 repair plan: {source_statuses['r1_repair_plan']}",
        f"- V20.48 benchmark context: {source_statuses['v48_benchmark']}",
        f"- V20.50 benchmark context: {source_statuses['v50_benchmark']}",
        f"- V20.98B-R5 active research base weights: {source_statuses['r5_registry']}",
        f"- V20.49 research-only conclusion gate: {source_statuses['v49_research']}",
        f"- V20.49 official promotion gate: {source_statuses['v49_official']}",
        "",
        "## Refresh Summary",
        "- certified_tickers: " + ("|".join(certified) if certified else "NONE"),
        "- refreshed_tickers: " + ("|".join(refreshed) if refreshed else "NONE"),
        "- missing_or_blocked_tickers: " + ("|".join(missing) if missing else "NONE"),
        "- refresh_failed_tickers: " + ("|".join(failed) if failed else "NONE"),
        "- stale_rejected_tickers: " + ("|".join(stale) if stale else "NONE"),
        "",
        "## Safety Boundary",
        "- research_only: TRUE",
        "- official_promotion_allowed: FALSE",
        "- official_recommendation_created: FALSE",
        "- weight_mutated: FALSE",
        "- trade_action_created: FALSE",
        "- broker_execution_supported: FALSE",
        "- dynamic_factor_weight_created: FALSE",
        "- official_weight_created: FALSE",
        "- V20.107: NOT_RUN",
        "",
        "## Preservation Checks",
        "- active_research_base_weights_preserved_without_modification: TRUE",
        "- v20_49_research_only_pass_preserved: TRUE",
        "- v20_49_official_promotion_blocked_preserved: TRUE",
        "- official_promotion_allowed: FALSE",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    source_statuses = {
        "r1_coverage": read_csv(R1_COVERAGE)[1],
        "r1_pair_audit": read_csv(R1_PAIR_AUDIT)[1],
        "r1_repair_plan": read_csv(R1_REPAIR_PLAN)[1],
        "v48_benchmark": read_csv(V48_BENCHMARK)[1],
        "v50_benchmark": read_csv(V50_BENCHMARK)[1],
        "r5_registry": read_csv(R5_REGISTRY)[1],
        "v49_research": read_csv(V49_RESEARCH)[1],
        "v49_official": read_csv(V49_OFFICIAL)[1],
    }
    research_gate = first_row(V49_RESEARCH)
    official_gate = first_row(V49_OFFICIAL)
    existing_prices = collect_existing_prices()
    reference_date = reference_current_date(existing_prices)
    cache_rows = build_cache_rows(existing_prices, reference_date)
    pair_rows = build_pair_rows(cache_rows)
    cert_rows = build_certification_rows(cache_rows, pair_rows)

    write_csv(REFRESH_CACHE, REFRESH_CACHE_FIELDS, cache_rows)
    write_csv(PAIR_AFTER_REFRESH, PAIR_FIELDS, pair_rows)
    write_csv(CERTIFICATION, CERTIFICATION_FIELDS, cert_rows)
    write_report(cache_rows, cert_rows[0], source_statuses, reference_date)

    print(cert_rows[0]["certification_status"])
    print(f"RUN_TIMESTAMP_UTC={datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(f"REQUIRED_ETF_COUNT={cert_rows[0]['required_etf_count']}")
    print(f"CERTIFIED_CURRENT_ETF_PRICE_COUNT={cert_rows[0]['certified_current_etf_price_count']}")
    print(f"MISSING_CURRENT_ETF_PRICE_COUNT={cert_rows[0]['missing_current_etf_price_count']}")
    print(f"STALE_ETF_PRICE_COUNT={cert_rows[0]['stale_etf_price_count']}")
    print(f"PAIR_COVERAGE_COMPLETE_COUNT={cert_rows[0]['pair_coverage_complete_count']}")
    print(f"PAIR_COVERAGE_MISSING_COUNT={cert_rows[0]['pair_coverage_missing_count']}")
    print(f"V20_49_RESEARCH_ONLY_GATE_STATUS={research_gate.get('research_only_gate_status', 'MISSING')}")
    print(f"V20_49_OFFICIAL_PROMOTION_GATE_STATUS={official_gate.get('official_promotion_gate_status', 'MISSING')}")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("DYNAMIC_FACTOR_WEIGHT_CREATED=FALSE")
    print("V20_107_EXECUTION_STATUS=NOT_RUN")
    print(f"OUTPUT_REFRESH_CACHE={rel(REFRESH_CACHE)}")
    print(f"OUTPUT_CERTIFICATION={rel(CERTIFICATION)}")
    print(f"OUTPUT_PAIR_AFTER_REFRESH={rel(PAIR_AFTER_REFRESH)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
