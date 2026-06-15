from __future__ import annotations

import csv
import hashlib
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
INPUTS = ROOT / "inputs" / "v20"
R1_CACHE_DIR = INPUTS / "outcome_benchmark" / "yahoo_cache" / "v20_35_r1"
RANDOM_ASOF_DIR = INPUTS / "random_asof"

IN_V20_35_NEXT = CONSOLIDATION / "V20_35_NEXT_STEP_DECISION_SUMMARY.csv"
IN_V20_35_DECISION = CONSOLIDATION / "V20_35_RANDOM_ASOF_BACKTEST_DECISION.csv"
IN_V20_35_READ_FIRST = OPS / "V20_35_READ_FIRST.txt"
IN_V20_34_DECISION = CONSOLIDATION / "V20_34_RANDOM_ASOF_TOP20_PREFLIGHT_DECISION.csv"
IN_UNIVERSE = CONSOLIDATION / "V20_26_REQUIRED_SYMBOL_UNIVERSE.csv"
IN_BENCHMARKS = CONSOLIDATION / "V20_26_REQUIRED_BENCHMARK_SYMBOLS.csv"
IN_PRIOR_TICKER_CACHE = INPUTS / "outcome_benchmark" / "yahoo_cache" / "v20_26" / "V20_26_YAHOO_TICKER_PRICE_CACHE.csv"
IN_PRIOR_BENCHMARK_CACHE = INPUTS / "outcome_benchmark" / "yahoo_cache" / "v20_26" / "V20_26_YAHOO_BENCHMARK_PRICE_CACHE.csv"
IN_PRIOR_HASH = CONSOLIDATION / "V20_26_YAHOO_CACHE_HASH_LEDGER.csv"

OUT_TICKER_CACHE = R1_CACHE_DIR / "V20_35_R1_HISTORICAL_YAHOO_TICKER_PRICE_CACHE.csv"
OUT_BENCHMARK_CACHE = R1_CACHE_DIR / "V20_35_R1_HISTORICAL_YAHOO_BENCHMARK_PRICE_CACHE.csv"
OUT_HASH_LEDGER = R1_CACHE_DIR / "V20_35_R1_HISTORICAL_YAHOO_CACHE_HASH_LEDGER.csv"
OUT_ACTIVE_TICKER = RANDOM_ASOF_DIR / "V20_RANDOM_ASOF_HISTORICAL_TICKER_PRICE_INPUT.csv"
OUT_ACTIVE_BENCHMARK = RANDOM_ASOF_DIR / "V20_RANDOM_ASOF_HISTORICAL_BENCHMARK_PRICE_INPUT.csv"

OUT_BLOCKER = CONSOLIDATION / "V20_35_R1_V20_35_BLOCKER_REVIEW.csv"
OUT_FETCH = CONSOLIDATION / "V20_35_R1_HISTORICAL_YAHOO_FETCH_AUDIT.csv"
OUT_TICKER_CERT = CONSOLIDATION / "V20_35_R1_HISTORICAL_TICKER_CACHE_CERTIFICATION.csv"
OUT_BENCH_CERT = CONSOLIDATION / "V20_35_R1_HISTORICAL_BENCHMARK_CACHE_CERTIFICATION.csv"
OUT_TICKER_COV = CONSOLIDATION / "V20_35_R1_TICKER_HISTORY_COVERAGE_SUMMARY.csv"
OUT_BENCH_COV = CONSOLIDATION / "V20_35_R1_BENCHMARK_HISTORY_COVERAGE_SUMMARY.csv"
OUT_SIGNAL_CAP = CONSOLIDATION / "V20_35_R1_RANDOM_ASOF_SIGNAL_DATE_CAPACITY_AUDIT.csv"
OUT_WINDOW = CONSOLIDATION / "V20_35_R1_FORWARD_WINDOW_SUPPORT_AUDIT.csv"
OUT_FACTOR = CONSOLIDATION / "V20_35_R1_TECHNICAL_FACTOR_FEASIBILITY_AUDIT.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_35_R1_HISTORICAL_CACHE_LINEAGE_AND_HASH_AUDIT.csv"
OUT_NEXT = CONSOLIDATION / "V20_35_R1_NEXT_STEP_DECISION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_35_R1_HISTORICAL_YAHOO_CACHE_EXPANSION_FOR_RANDOM_ASOF_BACKTEST_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_HISTORICAL_YAHOO_CACHE_EXPANSION_FOR_RANDOM_ASOF_BACKTEST.md"
READ_FIRST = OPS / "V20_35_R1_READ_FIRST.txt"

STAGE_NAME = "V20.35-R1_HISTORICAL_YAHOO_CACHE_EXPANSION_FOR_RANDOM_ASOF_BACKTEST"
PASS_STATUS = "PASS_V20_35_R1_HISTORICAL_YAHOO_CACHE_EXPANSION_FOR_RANDOM_ASOF_BACKTEST"
WARN_STATUS = "WARN_V20_35_R1_HISTORICAL_YAHOO_CACHE_EXPANSION_FOR_RANDOM_ASOF_BACKTEST"
BLOCKED_STATUS = "BLOCKED_V20_35_R1_HISTORICAL_YAHOO_CACHE_EXPANSION_FOR_RANDOM_ASOF_BACKTEST"
BENCHMARKS = ["SPY", "QQQ"]
TARGET_TRADING_DAYS = 252
MIN_LOOKBACK_DAYS = 50
MAX_FORWARD_DAYS = 20
MIN_RANDOM_SIGNAL_DATE_CAPACITY = 20
MIN_TOTAL_TRADING_DAYS_FOR_RETRY = MIN_LOOKBACK_DAYS + MAX_FORWARD_DAYS + MIN_RANDOM_SIGNAL_DATE_CAPACITY
MIN_TICKER_SUCCESS_RATE = 0.90
DOWNLOAD_PERIOD = "18mo"
DOWNLOAD_INTERVAL = "1d"
CHUNK_SIZE = 80

CACHE_FIELDS = [
    "symbol", "price_date", "open", "high", "low", "close", "adjusted_close", "volume",
    "currency", "data_vendor_or_source_system", "provider_query_start_date",
    "provider_query_end_date", "provider_download_timestamp_utc", "source_artifact_id",
    "source_hash", "run_id", "active_runtime_flag", "historical_reference_flag",
    "created_at_utc", "notes",
]


def clean(value: object) -> str:
    return str(value or "").strip()


def upper(value: object) -> str:
    return clean(value).upper()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha_file(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def num(value: object) -> float | None:
    try:
        value_f = float(clean(value))
    except ValueError:
        return None
    if math.isnan(value_f) or math.isinf(value_f):
        return None
    return value_f


def parse_date(value: object) -> datetime | None:
    text = clean(value)
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return None


def chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def extract_dataframe(data: Any, symbol: str) -> Any:
    try:
        if hasattr(data, "columns") and getattr(data.columns, "nlevels", 1) > 1:
            levels0 = {str(item) for item in data.columns.get_level_values(0)}
            levels1 = {str(item) for item in data.columns.get_level_values(1)}
            if symbol in levels0:
                return data[symbol]
            if symbol in levels1:
                return data.xs(symbol, level=1, axis=1)
        return data
    except Exception:
        return None


def normalize_download_rows(df: Any, symbol: str, run_id: str, created_at: str, role: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if df is None or getattr(df, "empty", True):
        return rows
    for idx, raw in df.iterrows():
        close = raw.get("Close", "")
        adj_close = raw.get("Adj Close", close)
        close_n = num(close)
        adj_n = num(adj_close)
        if close_n is None and adj_n is None:
            continue
        price_date = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else clean(idx)[:10]
        open_v = raw.get("Open", "")
        high_v = raw.get("High", "")
        low_v = raw.get("Low", "")
        volume_v = raw.get("Volume", "")
        row_hash = sha_text(f"{symbol}|{price_date}|{open_v}|{high_v}|{low_v}|{close}|{adj_close}|{volume_v}|{run_id}")
        rows.append({
            "symbol": symbol,
            "price_date": price_date,
            "open": clean(open_v),
            "high": clean(high_v),
            "low": clean(low_v),
            "close": clean(close),
            "adjusted_close": clean(adj_close),
            "volume": clean(volume_v),
            "currency": "USD",
            "data_vendor_or_source_system": "Yahoo/yfinance",
            "provider_query_start_date": f"period={DOWNLOAD_PERIOD}",
            "provider_query_end_date": "provider_current_end",
            "provider_download_timestamp_utc": created_at,
            "source_artifact_id": f"V20_35_R1_HISTORICAL_YAHOO_{role.upper()}::{symbol}",
            "source_hash": row_hash,
            "run_id": run_id,
            "active_runtime_flag": "TRUE",
            "historical_reference_flag": "TRUE",
            "created_at_utc": created_at,
            "notes": "v20_35_r1_historical_yahoo_cache_expansion_only_no_returns_no_backtest",
        })
    rows.sort(key=lambda row: (clean(row["symbol"]), clean(row["price_date"])))
    return rows


def fetch_symbols(symbols: list[str], role: str, run_id: str, created_at: str) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    fetch_rows: list[dict[str, object]] = []
    cache_rows: list[dict[str, object]] = []
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        for symbol in symbols:
            fetch_rows.append({
                "symbol": symbol, "symbol_role": role, "provider": "yfinance",
                "fetch_status": "PROVIDER_ERROR", "rows_downloaded": 0,
                "min_price_date": "", "max_price_date": "",
                "error_message": f"yfinance_import_failed:{exc}",
            })
        return cache_rows, fetch_rows

    for chunk in chunked(symbols, CHUNK_SIZE):
        try:
            data = yf.download(
                tickers=chunk,
                period=DOWNLOAD_PERIOD,
                interval=DOWNLOAD_INTERVAL,
                group_by="ticker",
                auto_adjust=False,
                actions=False,
                progress=False,
                threads=True,
            )
            chunk_error = ""
        except Exception as exc:
            data = None
            chunk_error = f"provider_download_failed:{exc}"
        for symbol in chunk:
            rows: list[dict[str, object]] = []
            error = chunk_error
            if data is not None:
                try:
                    rows = normalize_download_rows(extract_dataframe(data, symbol), symbol, run_id, created_at, role)
                except Exception as exc:
                    error = f"normalization_failed:{exc}"
            cache_rows.extend(rows)
            dates = [parse_date(row.get("price_date")) for row in rows]
            dates = [date for date in dates if date is not None]
            if not rows:
                status = "PROVIDER_ERROR" if error else "EMPTY"
            elif len(rows) < MIN_TOTAL_TRADING_DAYS_FOR_RETRY:
                status = "INSUFFICIENT_HISTORY"
            elif len(rows) < TARGET_TRADING_DAYS:
                status = "PARTIAL"
            else:
                status = "SUCCESS"
            fetch_rows.append({
                "symbol": symbol,
                "symbol_role": role,
                "provider": "yfinance",
                "fetch_status": status,
                "rows_downloaded": len(rows),
                "min_price_date": min(dates).strftime("%Y-%m-%d") if dates else "",
                "max_price_date": max(dates).strftime("%Y-%m-%d") if dates else "",
                "error_message": error,
            })
    return cache_rows, fetch_rows


def coverage_by_symbol(rows: list[dict[str, object]]) -> dict[str, list[datetime]]:
    out: dict[str, list[datetime]] = defaultdict(list)
    seen = set()
    for row in rows:
        symbol = clean(row.get("symbol"))
        date = parse_date(row.get("price_date"))
        if symbol and date and (symbol, date) not in seen:
            out[symbol].append(date)
            seen.add((symbol, date))
    for symbol in out:
        out[symbol].sort()
    return out


def certify_cache(rows: list[dict[str, object]], required_symbols: list[str], role: str) -> tuple[list[dict[str, object]], bool, dict[str, int]]:
    required = set(required_symbols)
    by_symbol = coverage_by_symbol(rows)
    keys = Counter((clean(row.get("symbol")), clean(row.get("price_date"))) for row in rows)
    duplicate_count = sum(count - 1 for count in keys.values() if count > 1)
    missing_price_count = 0
    negative_price_count = 0
    non_numeric_price_count = 0
    missing_volume_count = 0
    for row in rows:
        close_v = num(row.get("close"))
        adj_v = num(row.get("adjusted_close"))
        prices = [num(row.get(field)) for field in ["open", "high", "low", "close", "adjusted_close"]]
        if close_v is None and adj_v is None:
            missing_price_count += 1
        if any(value is None for value in prices):
            non_numeric_price_count += 1
        if any(value is not None and value < 0 for value in prices):
            negative_price_count += 1
        if clean(row.get("volume")) == "":
            missing_volume_count += 1
    successful_symbols = [symbol for symbol in required if len(by_symbol.get(symbol, [])) >= MIN_TOTAL_TRADING_DAYS_FOR_RETRY]
    certified = (
        bool(rows)
        and duplicate_count == 0
        and missing_price_count == 0
        and negative_price_count == 0
        and len(successful_symbols) / max(len(required), 1) >= (1.0 if role == "benchmark" else MIN_TICKER_SUCCESS_RATE)
    )
    summary = {
        "required_symbol_count": len(required),
        "symbols_with_minimum_history": len(successful_symbols),
        "duplicate_row_count": duplicate_count,
        "missing_price_count": missing_price_count,
        "negative_price_count": negative_price_count,
        "non_numeric_price_count": non_numeric_price_count,
        "missing_volume_count": missing_volume_count,
    }
    rows_out = [{
        "cache_role": role,
        "row_count": len(rows),
        "required_symbol_count": len(required),
        "symbols_with_any_history": len([symbol for symbol in required if by_symbol.get(symbol)]),
        "symbols_with_minimum_history": len(successful_symbols),
        "required_date_field_exists": "TRUE",
        "price_fields_numeric_or_blank_count": non_numeric_price_count,
        "negative_price_count": negative_price_count,
        "missing_adjusted_or_close_count": missing_price_count,
        "volume_missing_count": missing_volume_count,
        "duplicate_symbol_date_row_count": duplicate_count,
        "certification_status": "PASS" if certified else "BLOCKED",
        "certification_notes": "" if certified else "Insufficient coverage or row quality blocker remains.",
    }]
    return rows_out, certified, summary


def date_capacity(ticker_rows: list[dict[str, object]], benchmark_rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], int]:
    ticker_dates = sorted({parse_date(row.get("price_date")) for row in ticker_rows if parse_date(row.get("price_date"))})
    benchmark_by_symbol = coverage_by_symbol(benchmark_rows)
    spy_dates = set(benchmark_by_symbol.get("SPY", []))
    qqq_dates = set(benchmark_by_symbol.get("QQQ", []))
    all_benchmark_dates = spy_dates & qqq_dates
    capacity_rows: list[dict[str, object]] = []
    eligible_count = 0
    for idx, date in enumerate(ticker_dates):
        lookback = idx
        forward = len(ticker_dates) - idx - 1
        benchmark_aligned = date in all_benchmark_dates
        eligible = lookback >= MIN_LOOKBACK_DAYS and forward >= MAX_FORWARD_DAYS and benchmark_aligned
        if eligible:
            eligible_count += 1
        capacity_rows.append({
            "signal_date": date.strftime("%Y-%m-%d"),
            "lookback_trading_days_available": lookback,
            "forward_trading_days_available": forward,
            "spy_qqq_benchmark_aligned": tf(benchmark_aligned),
            "eligible_for_v20_35_retry_random_sample": tf(eligible),
            "exclusion_reason": "" if eligible else "insufficient_lookback_or_forward_or_benchmark_alignment",
        })
    return capacity_rows, eligible_count


def main() -> int:
    created_at = utc_now()
    run_id = "V20_35_R1_HISTORICAL_YAHOO_CACHE_EXPANSION_" + created_at.replace("-", "").replace(":", "").replace("+00:00", "Z")

    next_rows, _ = read_csv(IN_V20_35_NEXT)
    decision_rows, _ = read_csv(IN_V20_35_DECISION)
    universe_rows, _ = read_csv(IN_UNIVERSE)
    benchmark_rows_in, _ = read_csv(IN_BENCHMARKS)

    next_row = next_rows[0] if next_rows else {}
    decision_row = decision_rows[0] if decision_rows else {}
    v20_35_status = clean(next_row.get("STATUS"))
    decision_reason = clean(decision_row.get("decision_reason"))
    blocker_confirmed = (
        v20_35_status.startswith("BLOCKED_V20_35")
        and "insufficient_trading_dates" in decision_reason
        and upper(decision_row.get("current_top20_leakage_detected")) == "FALSE"
    )

    tickers = sorted(clean(row.get("symbol")) for row in universe_rows if upper(row.get("symbol_role")) == "TICKER")
    tickers = [symbol for symbol in tickers if symbol]
    required_benchmarks = sorted(clean(row.get("symbol")) for row in benchmark_rows_in if clean(row.get("symbol"))) or BENCHMARKS
    required_benchmarks = [symbol for symbol in BENCHMARKS if symbol in set(required_benchmarks)] or BENCHMARKS

    blocker_rows = [{
        "review_check": "v20_35_blocked_by_insufficient_history",
        "v20_35_status": v20_35_status,
        "v20_35_decision_reason": decision_reason,
        "current_top20_leakage_detected": clean(decision_row.get("current_top20_leakage_detected")),
        "v20_35_blocker_confirmed_as_insufficient_history": tf(blocker_confirmed),
        "review_status": "PASS" if blocker_confirmed else "BLOCKED",
    }]

    ticker_cache_rows, ticker_fetch_rows = fetch_symbols(tickers, "ticker", run_id, created_at) if blocker_confirmed else ([], [])
    benchmark_cache_rows, benchmark_fetch_rows = fetch_symbols(required_benchmarks, "benchmark", run_id, created_at) if blocker_confirmed else ([], [])
    fetch_rows = ticker_fetch_rows + benchmark_fetch_rows

    write_csv(OUT_TICKER_CACHE, ticker_cache_rows, CACHE_FIELDS)
    write_csv(OUT_BENCHMARK_CACHE, benchmark_cache_rows, CACHE_FIELDS)
    write_csv(OUT_ACTIVE_TICKER, ticker_cache_rows, CACHE_FIELDS)
    write_csv(OUT_ACTIVE_BENCHMARK, benchmark_cache_rows, CACHE_FIELDS)

    ticker_cert_rows, ticker_certified, ticker_cert_summary = certify_cache(ticker_cache_rows, tickers, "ticker")
    bench_cert_rows, bench_certified, bench_cert_summary = certify_cache(benchmark_cache_rows, required_benchmarks, "benchmark")

    ticker_cov = coverage_by_symbol(ticker_cache_rows)
    bench_cov = coverage_by_symbol(benchmark_cache_rows)
    ticker_coverage_rows = []
    for symbol in tickers:
        dates = ticker_cov.get(symbol, [])
        status = "PASS" if len(dates) >= MIN_TOTAL_TRADING_DAYS_FOR_RETRY else ("PARTIAL" if dates else "MISSING")
        ticker_coverage_rows.append({
            "ticker": symbol,
            "trading_date_count": len(dates),
            "min_price_date": dates[0].strftime("%Y-%m-%d") if dates else "",
            "max_price_date": dates[-1].strftime("%Y-%m-%d") if dates else "",
            "meets_v20_35_retry_minimum": tf(len(dates) >= MIN_TOTAL_TRADING_DAYS_FOR_RETRY),
            "coverage_status": status,
        })
    benchmark_coverage_rows = []
    for symbol in required_benchmarks:
        dates = bench_cov.get(symbol, [])
        benchmark_coverage_rows.append({
            "benchmark_symbol": symbol,
            "trading_date_count": len(dates),
            "min_price_date": dates[0].strftime("%Y-%m-%d") if dates else "",
            "max_price_date": dates[-1].strftime("%Y-%m-%d") if dates else "",
            "meets_v20_35_retry_minimum": tf(len(dates) >= MIN_TOTAL_TRADING_DAYS_FOR_RETRY),
            "coverage_status": "PASS" if len(dates) >= MIN_TOTAL_TRADING_DAYS_FOR_RETRY else ("PARTIAL" if dates else "MISSING"),
        })

    signal_capacity_rows, candidate_signal_date_count = date_capacity(ticker_cache_rows, benchmark_cache_rows)
    enough_signal_dates = candidate_signal_date_count >= MIN_RANDOM_SIGNAL_DATE_CAPACITY

    window_rows = []
    for window in [1, 3, 5, 10, 20]:
        window_rows.append({
            "forward_window": f"forward_{window}d",
            "required_forward_trading_days": window,
            "candidate_signal_dates_supported": sum(
                1 for row in signal_capacity_rows
                if int(row["forward_trading_days_available"]) >= window and upper(row["spy_qqq_benchmark_aligned"]) == "TRUE" and int(row["lookback_trading_days_available"]) >= MIN_LOOKBACK_DAYS
            ),
            "window_support_status": "PASS" if enough_signal_dates else "BLOCKED",
        })

    factor_requirements = {
        "MA10": 10,
        "MA20": 20,
        "MA50": 50,
        "RSI": 14,
        "MACD": 26,
        "Bollinger_20d": 20,
        "momentum_20d": 20,
        "relative_strength_20d": 20,
        "volume_trend_20d": 20,
    }
    factor_rows = []
    for factor, lookback in factor_requirements.items():
        feasible = enough_signal_dates and lookback <= MIN_LOOKBACK_DAYS
        factor_rows.append({
            "technical_factor_group": factor,
            "required_lookback_trading_days": lookback,
            "feasible_from_expanded_cache": tf(feasible),
            "feasibility_status": "PASS" if feasible else "BLOCKED",
        })
    technical_factor_feasibility_count = sum(1 for row in factor_rows if row["feasible_from_expanded_cache"] == "TRUE")

    ticker_counts = [int(row["trading_date_count"]) for row in ticker_coverage_rows]
    min_ticker_trading_dates = min(ticker_counts) if ticker_counts else 0
    median_ticker_trading_dates = median(ticker_counts) if ticker_counts else 0
    max_ticker_trading_dates = max(ticker_counts) if ticker_counts else 0

    ticker_status_counts = Counter(clean(row.get("fetch_status")) for row in ticker_fetch_rows)
    bench_status_counts = Counter(clean(row.get("fetch_status")) for row in benchmark_fetch_rows)
    ticker_success_count = ticker_status_counts["SUCCESS"]
    ticker_partial_count = ticker_status_counts["PARTIAL"] + ticker_status_counts["INSUFFICIENT_HISTORY"]
    ticker_failure_count = ticker_status_counts["EMPTY"] + ticker_status_counts["PROVIDER_ERROR"]
    benchmark_success_count = bench_status_counts["SUCCESS"]
    benchmark_failure_count = bench_status_counts["EMPTY"] + bench_status_counts["PROVIDER_ERROR"] + bench_status_counts["INSUFFICIENT_HISTORY"]

    enough_ticker_coverage = ticker_certified
    enough_benchmark_coverage = bench_certified
    ready_retry = blocker_confirmed and ticker_certified and bench_certified and enough_signal_dates
    status = PASS_STATUS if ready_retry else (WARN_STATUS if ticker_cache_rows or benchmark_cache_rows else BLOCKED_STATUS)

    hash_rows = []
    for path, role, certified in [
        (OUT_TICKER_CACHE, "historical_ticker_cache", ticker_certified),
        (OUT_BENCHMARK_CACHE, "historical_benchmark_cache", bench_certified),
        (OUT_ACTIVE_TICKER, "active_random_asof_historical_ticker_input", ticker_certified),
        (OUT_ACTIVE_BENCHMARK, "active_random_asof_historical_benchmark_input", bench_certified),
    ]:
        data_rows, _ = read_csv(path)
        hash_rows.append({
            "file_role": role,
            "file_path": rel(path),
            "row_count": len(data_rows),
            "sha256_hash": sha_file(path),
            "run_id": run_id,
            "source_provider": "Yahoo/yfinance",
            "created_at_utc": created_at,
            "certification_status": "PASS" if certified else "BLOCKED",
            "prior_v20_26_v20_28_cache_mutated": "FALSE",
        })
    write_csv(OUT_HASH_LEDGER, hash_rows, ["file_role", "file_path", "row_count", "sha256_hash", "run_id", "source_provider", "created_at_utc", "certification_status", "prior_v20_26_v20_28_cache_mutated"])

    lineage_rows = []
    for row in hash_rows:
        lineage_rows.append({
            **row,
            "prior_hash_ledger_path": rel(IN_PRIOR_HASH),
            "prior_ticker_cache_path": rel(IN_PRIOR_TICKER_CACHE),
            "prior_benchmark_cache_path": rel(IN_PRIOR_BENCHMARK_CACHE),
            "lineage_notes": "V20.35-R1 wrote versioned historical cache files and did not delete or overwrite V20.26-V20.28 cache artifacts.",
        })

    next_rows_out = [{
        "STAGE_NAME": STAGE_NAME,
        "STATUS": status,
        "V20_35_BLOCKER_CONFIRMED": tf(blocker_confirmed),
        "REQUESTED_TICKER_COUNT": len(tickers),
        "TICKER_DOWNLOAD_SUCCESS_COUNT": ticker_success_count,
        "TICKER_PARTIAL_COUNT": ticker_partial_count,
        "TICKER_FAILURE_COUNT": ticker_failure_count,
        "BENCHMARK_DOWNLOAD_SUCCESS_COUNT": benchmark_success_count,
        "BENCHMARK_FAILURE_COUNT": benchmark_failure_count,
        "HISTORICAL_TICKER_CACHE_ROWS": len(ticker_cache_rows),
        "HISTORICAL_BENCHMARK_CACHE_ROWS": len(benchmark_cache_rows),
        "MIN_TICKER_TRADING_DATES": min_ticker_trading_dates,
        "MEDIAN_TICKER_TRADING_DATES": median_ticker_trading_dates,
        "MAX_TICKER_TRADING_DATES": max_ticker_trading_dates,
        "CANDIDATE_RANDOM_SIGNAL_DATE_COUNT_AFTER_50D_LOOKBACK_AND_20D_FORWARD_BUFFER": candidate_signal_date_count,
        "FORWARD_WINDOW_SUPPORT_SUMMARY": "PASS" if enough_signal_dates else "BLOCKED",
        "TECHNICAL_FACTOR_FEASIBILITY_COUNT": technical_factor_feasibility_count,
        "HISTORICAL_TICKER_CACHE_CERTIFIED": tf(ticker_certified),
        "HISTORICAL_BENCHMARK_CACHE_CERTIFIED": tf(bench_certified),
        "READY_FOR_V20_35_RETRY_RANDOM_ASOF_TOP20_TECHNICAL_RECOMPUTE_BACKTEST": tf(ready_retry),
        "READY_FOR_DYNAMIC_WEIGHTING": "FALSE",
        "READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION": "FALSE",
        "NEXT_RECOMMENDED_STEP": "V20.35_RETRY_RANDOM_ASOF_TOP20_TECHNICAL_RECOMPUTE_BACKTEST" if ready_retry else "V20.35_R1_PROVIDER_OR_COVERAGE_BLOCKER_RESOLUTION",
    }]

    decision_rows_out = [{
        "v20_35_blocker_confirmed_as_insufficient_history": tf(blocker_confirmed),
        "historical_yahoo_cache_expansion_attempted": tf(blocker_confirmed),
        "historical_ticker_cache_created": tf(bool(ticker_cache_rows)),
        "historical_benchmark_cache_created": tf(bool(benchmark_cache_rows)),
        "historical_ticker_cache_certified": tf(ticker_certified),
        "historical_benchmark_cache_certified": tf(bench_certified),
        "enough_candidate_signal_dates_for_v20_35_retry": tf(enough_signal_dates),
        "enough_ticker_coverage_for_v20_35_retry": tf(enough_ticker_coverage),
        "enough_benchmark_coverage_for_v20_35_retry": tf(enough_benchmark_coverage),
        "ready_for_v20_35_retry_random_asof_top20_technical_recompute_backtest": tf(ready_retry),
        "ready_for_v20_36_entry_strategy_matrix_design": "FALSE",
        "ready_for_factor_effectiveness_ablation_audit": "FALSE",
        "ready_for_shadow_dynamic_weighting": "FALSE",
        "ready_for_official_trading_or_recommendation": "FALSE",
    }]

    write_csv(OUT_BLOCKER, blocker_rows, ["review_check", "v20_35_status", "v20_35_decision_reason", "current_top20_leakage_detected", "v20_35_blocker_confirmed_as_insufficient_history", "review_status"])
    write_csv(OUT_FETCH, fetch_rows, ["symbol", "symbol_role", "provider", "fetch_status", "rows_downloaded", "min_price_date", "max_price_date", "error_message"])
    write_csv(OUT_TICKER_CERT, ticker_cert_rows, ["cache_role", "row_count", "required_symbol_count", "symbols_with_any_history", "symbols_with_minimum_history", "required_date_field_exists", "price_fields_numeric_or_blank_count", "negative_price_count", "missing_adjusted_or_close_count", "volume_missing_count", "duplicate_symbol_date_row_count", "certification_status", "certification_notes"])
    write_csv(OUT_BENCH_CERT, bench_cert_rows, ["cache_role", "row_count", "required_symbol_count", "symbols_with_any_history", "symbols_with_minimum_history", "required_date_field_exists", "price_fields_numeric_or_blank_count", "negative_price_count", "missing_adjusted_or_close_count", "volume_missing_count", "duplicate_symbol_date_row_count", "certification_status", "certification_notes"])
    write_csv(OUT_TICKER_COV, ticker_coverage_rows, ["ticker", "trading_date_count", "min_price_date", "max_price_date", "meets_v20_35_retry_minimum", "coverage_status"])
    write_csv(OUT_BENCH_COV, benchmark_coverage_rows, ["benchmark_symbol", "trading_date_count", "min_price_date", "max_price_date", "meets_v20_35_retry_minimum", "coverage_status"])
    write_csv(OUT_SIGNAL_CAP, signal_capacity_rows, ["signal_date", "lookback_trading_days_available", "forward_trading_days_available", "spy_qqq_benchmark_aligned", "eligible_for_v20_35_retry_random_sample", "exclusion_reason"])
    write_csv(OUT_WINDOW, window_rows, ["forward_window", "required_forward_trading_days", "candidate_signal_dates_supported", "window_support_status"])
    write_csv(OUT_FACTOR, factor_rows, ["technical_factor_group", "required_lookback_trading_days", "feasible_from_expanded_cache", "feasibility_status"])
    write_csv(OUT_LINEAGE, lineage_rows, ["file_role", "file_path", "row_count", "sha256_hash", "run_id", "source_provider", "created_at_utc", "certification_status", "prior_v20_26_v20_28_cache_mutated", "prior_hash_ledger_path", "prior_ticker_cache_path", "prior_benchmark_cache_path", "lineage_notes"])
    write_csv(OUT_NEXT, next_rows_out, list(next_rows_out[0].keys()))

    report = f"""# V20.35-R1 Historical Yahoo Cache Expansion For Random Asof Backtest

Status: {status}

Cache expansion only: TRUE
Random as-of Top20 backtest executed: FALSE
Forward returns created: FALSE
Benchmark-relative returns created: FALSE

V20.35 blocker confirmed: {tf(blocker_confirmed)}
Requested tickers: {len(tickers)}
Ticker download success / partial / failure: {ticker_success_count} / {ticker_partial_count} / {ticker_failure_count}
Benchmark download success / failure: {benchmark_success_count} / {benchmark_failure_count}
Historical ticker cache rows: {len(ticker_cache_rows)}
Historical benchmark cache rows: {len(benchmark_cache_rows)}
Candidate signal dates after 50d lookback and 20d forward buffer: {candidate_signal_date_count}
Ready for V20.35 retry: {tf(ready_retry)}

Provider usage: Yahoo/yfinance via period={DOWNLOAD_PERIOD}, interval={DOWNLOAD_INTERVAL}. Prior V20.26-V20.28 cache files were not deleted or overwritten.
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)

    read_first = f"""STAGE_NAME: {STAGE_NAME}
STATUS: {status}
CACHE_EXPANSION_ONLY: TRUE
RANDOM_ASOF_TOP20_BACKTEST_EXECUTED: FALSE
FORWARD_RETURNS_CREATED: FALSE
BENCHMARK_RELATIVE_RETURNS_CREATED: FALSE
OFFICIAL_RECOMMENDATION_CREATED: FALSE
TRADING_SIGNAL_CREATED: FALSE
BROKER_ORDER_EXECUTION_CODE_CREATED: FALSE
OFFICIAL_RANKING_MUTATED: FALSE
OFFICIAL_FACTOR_WEIGHTS_MUTATED: FALSE
DYNAMIC_WEIGHTING_STARTED: FALSE
PORTFOLIO_BACKTEST_CREATED: FALSE
EQUITY_CURVE_CREATED: FALSE
PERFORMANCE_CLAIMS_CREATED: FALSE
V21_OUTPUTS_CREATED: FALSE
V19_21_OUTPUTS_CREATED: FALSE
V20_35_BLOCKER_CONFIRMED: {tf(blocker_confirmed)}
HISTORICAL_TICKER_CACHE_CERTIFIED: {tf(ticker_certified)}
HISTORICAL_BENCHMARK_CACHE_CERTIFIED: {tf(bench_certified)}
READY_FOR_V20_35_RETRY_RANDOM_ASOF_TOP20_TECHNICAL_RECOMPUTE_BACKTEST: {tf(ready_retry)}
READY_FOR_DYNAMIC_WEIGHTING: FALSE
READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION: FALSE
"""
    write_text(READ_FIRST, read_first)

    required_outputs = [
        OUT_TICKER_CACHE, OUT_BENCHMARK_CACHE, OUT_HASH_LEDGER, OUT_ACTIVE_TICKER,
        OUT_ACTIVE_BENCHMARK, OUT_BLOCKER, OUT_FETCH, OUT_TICKER_CERT, OUT_BENCH_CERT,
        OUT_TICKER_COV, OUT_BENCH_COV, OUT_SIGNAL_CAP, OUT_WINDOW, OUT_FACTOR,
        OUT_LINEAGE, OUT_NEXT, REPORT, CURRENT_REPORT, READ_FIRST,
    ]
    missing = [path for path in required_outputs if not path.exists()]
    if missing:
        raise RuntimeError("Missing V20.35-R1 outputs: " + ", ".join(rel(path) for path in missing))

    print(f"STATUS={status}")
    print("FILES_CHANGED=scripts/v20/v20_35_r1_historical_yahoo_cache_expansion_for_random_asof_backtest.py;scripts/v20/run_v20_35_r1_historical_yahoo_cache_expansion_for_random_asof_backtest.ps1")
    print("OUTPUTS_CREATED=" + ";".join(rel(path) for path in required_outputs))
    print(f"V20_35_BLOCKER_CONFIRMED={tf(blocker_confirmed)}")
    print(f"REQUESTED_TICKER_COUNT={len(tickers)}")
    print(f"TICKER_DOWNLOAD_SUCCESS_COUNT={ticker_success_count}")
    print(f"TICKER_PARTIAL_COUNT={ticker_partial_count}")
    print(f"TICKER_FAILURE_COUNT={ticker_failure_count}")
    print(f"BENCHMARK_DOWNLOAD_SUCCESS_COUNT={benchmark_success_count}")
    print(f"BENCHMARK_FAILURE_COUNT={benchmark_failure_count}")
    print(f"HISTORICAL_TICKER_CACHE_ROWS={len(ticker_cache_rows)}")
    print(f"HISTORICAL_BENCHMARK_CACHE_ROWS={len(benchmark_cache_rows)}")
    print(f"MIN_TICKER_TRADING_DATES={min_ticker_trading_dates}")
    print(f"MEDIAN_TICKER_TRADING_DATES={median_ticker_trading_dates}")
    print(f"MAX_TICKER_TRADING_DATES={max_ticker_trading_dates}")
    print(f"CANDIDATE_RANDOM_SIGNAL_DATE_COUNT_AFTER_50D_LOOKBACK_AND_20D_FORWARD_BUFFER={candidate_signal_date_count}")
    print(f"FORWARD_WINDOW_SUPPORT_SUMMARY={'PASS' if enough_signal_dates else 'BLOCKED'}")
    print(f"TECHNICAL_FACTOR_FEASIBILITY_COUNT={technical_factor_feasibility_count}")
    print(f"HISTORICAL_TICKER_CACHE_CERTIFIED={tf(ticker_certified)}")
    print(f"HISTORICAL_BENCHMARK_CACHE_CERTIFIED={tf(bench_certified)}")
    print(f"READY_FOR_V20_35_RETRY_RANDOM_ASOF_TOP20_TECHNICAL_RECOMPUTE_BACKTEST={tf(ready_retry)}")
    print("READY_FOR_DYNAMIC_WEIGHTING=FALSE")
    print("READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
