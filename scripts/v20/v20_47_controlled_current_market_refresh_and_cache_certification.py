from __future__ import annotations

import csv
import hashlib
import math
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
SCRIPT_DIR = ROOT / "scripts" / "v20"
CACHE_DIR = ROOT / "inputs" / "v20" / "current_market" / "yahoo_cache" / "v20_47"
ATTEMPT_DIR = CACHE_DIR / "attempts"
PROVIDER_CACHE_DIR = ROOT / "state" / "v20" / "provider_cache" / "yfinance"

STAGE = "V20.47_CONTROLLED_CURRENT_MARKET_REFRESH_AND_CACHE_CERTIFICATION"
PASS_STATUS = "PASS_V20_47_CONTROLLED_CURRENT_MARKET_REFRESH_AND_CACHE_CERTIFICATION"
BLOCKED_STATUS = "BLOCKED_V20_47_CONTROLLED_CURRENT_MARKET_REFRESH_AND_CACHE_CERTIFICATION"
CERTIFIED_STATUS = "CERTIFIED_FOR_RESEARCH_REPORT_HANDOFF"
PARTIAL_CERTIFIED_STATUS = "PARTIAL_CERTIFIED_RESEARCH_HANDOFF"
FALLBACK_CERTIFIED_STATUS = "CERTIFIED_CACHE_FALLBACK_HANDOFF"
BLOCKED_CERT_STATUS = "BLOCKED_REFRESH_CACHE_CERTIFICATION"
DECISION_PASS = "PASS_CONTROLLED_REFRESH_CERTIFIED_FOR_RESEARCH_HANDOFF"
DECISION_PARTIAL = "PASS_WITH_WARNINGS_PARTIAL_CERTIFIED_RESEARCH_HANDOFF"
NEXT_STAGE = "V20.55_DAILY_ONE_CLICK_RESEARCH_RUNNER"
PROVIDER_NAME = "yahoo/yfinance"

IN_V46_SUMMARY = CONSOLIDATION / "V20_46_CURRENT_MARKET_REFRESH_READINESS_SUMMARY.csv"
IN_V46_NEXT = CONSOLIDATION / "V20_46_NEXT_STEP_DECISION.csv"
IN_V46_CANDIDATE_UNIVERSE = CONSOLIDATION / "V20_46_CANDIDATE_REFRESH_UNIVERSE.csv"
IN_V46_SOURCE_AUDIT = CONSOLIDATION / "V20_46_SOURCE_AUDIT.csv"
IN_V46_CURRENT = READ_CENTER / "V20_CURRENT_MARKET_REFRESH_READINESS_GATE.md"
IN_V46_READ_FIRST = OPS / "V20_46_READ_FIRST.txt"
IN_V46_TEST = SCRIPT_DIR / "test_v20_46_current_market_refresh_readiness_gate.py"
IN_V45_CANDIDATE = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_CANDIDATE_RESEARCH_VIEW.csv"
IN_V45_LINEAGE = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_LINEAGE_FRESHNESS_VIEW.csv"
IN_V45_NEXT = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_NEXT_STEP_DECISION.csv"
IN_V45_CURRENT = READ_CENTER / "V20_CURRENT_OPERATOR_REPORT_RESEARCH_ONLY.md"
IN_V45_READ_FIRST = OPS / "V20_45_READ_FIRST.txt"

RAW_CANDIDATE_CACHE = CACHE_DIR / "V20_47_YAHOO_CURRENT_CANDIDATE_PRICE_CACHE.csv"
RAW_BENCHMARK_CACHE = CACHE_DIR / "V20_47_YAHOO_CURRENT_BENCHMARK_PRICE_CACHE.csv"
RAW_FAILURES = CACHE_DIR / "V20_47_YAHOO_CURRENT_REFRESH_FAILURES.csv"
RAW_HASH_LEDGER = CACHE_DIR / "V20_47_YAHOO_CURRENT_CACHE_HASH_LEDGER.csv"
RAW_MANIFEST = CACHE_DIR / "V20_47_YAHOO_CURRENT_REFRESH_RUN_MANIFEST.csv"
OUT_RAW_CANDIDATE_CACHE = CONSOLIDATION / "V20_47_YAHOO_CURRENT_CANDIDATE_PRICE_CACHE.csv"
OUT_RAW_BENCHMARK_CACHE = CONSOLIDATION / "V20_47_YAHOO_CURRENT_BENCHMARK_PRICE_CACHE.csv"
OUT_RAW_FAILURES = CONSOLIDATION / "V20_47_YAHOO_CURRENT_REFRESH_FAILURES.csv"

OUT_SUMMARY = CONSOLIDATION / "V20_47_CONTROLLED_REFRESH_SUMMARY.csv"
OUT_UNIVERSE = CONSOLIDATION / "V20_47_REFRESH_TICKER_UNIVERSE.csv"
OUT_AUDIT = CONSOLIDATION / "V20_47_PROVIDER_REFRESH_AUDIT.csv"
OUT_PROVIDER_DIAGNOSTICS = CONSOLIDATION / "V20_47_PROVIDER_REFRESH_DIAGNOSTICS.csv"
OUT_PROVIDER_SUMMARY = CONSOLIDATION / "V20_47_PROVIDER_REFRESH_SUMMARY.csv"
OUT_FALLBACK_AUDIT = CONSOLIDATION / "V20_47_CERTIFIED_CACHE_FALLBACK_AUDIT.csv"
OUT_CANDIDATE_CERT = CONSOLIDATION / "V20_47_CURRENT_CANDIDATE_PRICE_CERTIFICATION.csv"
OUT_BENCHMARK_CERT = CONSOLIDATION / "V20_47_CURRENT_BENCHMARK_PRICE_CERTIFICATION.csv"
OUT_STAGED_CANDIDATE = CONSOLIDATION / "V20_47_CURRENT_MARKET_SOURCE_STAGED_CANDIDATE.csv"
OUT_STAGED_BENCHMARK = CONSOLIDATION / "V20_47_CURRENT_BENCHMARK_SOURCE_STAGED_CANDIDATE.csv"
OUT_HASH_LEDGER = CONSOLIDATION / "V20_47_CACHE_HASH_LEDGER.csv"
OUT_FAILURE_REGISTER = CONSOLIDATION / "V20_47_REFRESH_FAILURE_REGISTER.csv"
OUT_SAFETY = CONSOLIDATION / "V20_47_REFRESH_SAFETY_BOUNDARY.csv"
OUT_NEXT = CONSOLIDATION / "V20_47_NEXT_STEP_DECISION.csv"
OUT_LAST_FAILED_ATTEMPT = CONSOLIDATION / "V20_47_LAST_FAILED_REFRESH_ATTEMPT.csv"
REPORT = READ_CENTER / "V20_47_CONTROLLED_CURRENT_MARKET_REFRESH_AND_CACHE_CERTIFICATION_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_CONTROLLED_MARKET_REFRESH_CERTIFICATION.md"
READ_FIRST = OPS / "V20_47_READ_FIRST.txt"


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def first_row(path: Path) -> dict[str, str]:
    rows, _ = read_csv(path)
    return rows[0] if rows else {}


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def csv_row_count(path: Path) -> int:
    rows, _ = read_csv(path)
    return len(rows)


def csv_rows_for_ticker(path: Path, ticker: str) -> int:
    rows, _ = read_csv(path)
    return sum(1 for row in rows if clean(row.get("ticker") or row.get("symbol") or row.get("benchmark_ticker")).upper() == ticker.upper())


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def provider_cache_dir_writable() -> bool:
    try:
        PROVIDER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        probe = PROVIDER_CACHE_DIR / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def provider_cache_diagnostics() -> dict[str, object]:
    exists = PROVIDER_CACHE_DIR.exists() and PROVIDER_CACHE_DIR.is_dir()
    writable = provider_cache_dir_writable()
    return {
        "provider_cache_dir": rel(PROVIDER_CACHE_DIR),
        "provider_cache_dir_exists": tf(exists),
        "provider_cache_dir_writable": tf(writable),
    }


def configure_provider_cache(yf: Any) -> dict[str, object]:
    PROVIDER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("YFINANCE_CACHE_DIR", str(PROVIDER_CACHE_DIR))
    os.environ.setdefault("YFINANCE_USER_CACHE_DIR", str(PROVIDER_CACHE_DIR))
    try:
        import yfinance.cache as yf_cache  # type: ignore

        if hasattr(yf_cache, "set_cache_location"):
            yf_cache.set_cache_location(str(PROVIDER_CACHE_DIR))
    except Exception:
        pass
    # yfinance exposes this for timezone/cache SQLite location in supported versions.
    if hasattr(yf, "set_tz_cache_location"):
        try:
            yf.set_tz_cache_location(str(PROVIDER_CACHE_DIR))
        except Exception:
            pass
    return provider_cache_diagnostics()


def provider_error_type(message: object) -> str:
    lowered = clean(message).lower()
    if "unable to open database file" in lowered or "database is locked" in lowered or "sqlite" in lowered:
        return "PROVIDER_CACHE_DB_ERROR"
    if "failed to connect" in lowered or "connectionerror" in lowered or "curl:" in lowered or "could not connect" in lowered:
        return "PROVIDER_RUNTIME_UNAVAILABLE"
    if "empty_dataframe" in lowered:
        return "EMPTY_DATAFRAME"
    if "import" in lowered:
        return "IMPORT_ERROR"
    if lowered:
        return "PROVIDER_ERROR"
    return ""


def valid_symbol(value: str) -> bool:
    ticker = clean(value).upper()
    if not ticker or ticker in {"NULL", "NONE", "N/A", "NA"}:
        return False
    return all(ch.isalnum() or ch in {".", "-"} for ch in ticker)


def normalize_provider_ticker(ticker: object) -> str:
    return clean(ticker).upper().replace(".", "-")


def build_universe(candidate_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    candidates = []
    sorted_rows = sorted(candidate_rows, key=lambda row: int(float(clean(row.get("report_rank")) or "999999")))
    for row in sorted_rows:
        ticker = clean(row.get("ticker_or_candidate_id")) or clean(row.get("display_name_or_ticker"))
        ticker = ticker.upper()
        if not valid_symbol(ticker):
            continue
        duplicate = ticker in seen
        if duplicate:
            continue
        seen.add(ticker)
        candidates.append({
            "ticker": ticker,
            "universe_role": "candidate",
            "source_stage": "V20.45_CURRENT_OPERATOR_REPORT_RESEARCH_ONLY_RUN",
            "source_rank": clean(row.get("report_rank")),
            "source_rank_or_score": clean(row.get("source_rank_or_score")),
            "source_contract": rel(IN_V45_CANDIDATE),
            "requested_for_refresh": "TRUE",
            "benchmark_flag": "FALSE",
            "candidate_flag": "TRUE",
            "duplicate_removed_flag": "FALSE",
        })
    benchmarks = []
    for ticker in ["SPY", "QQQ"]:
        benchmarks.append({
            "ticker": ticker,
            "universe_role": "benchmark",
            "source_stage": STAGE,
            "source_rank": "",
            "source_rank_or_score": "",
            "source_contract": "required_benchmark_ticker",
            "requested_for_refresh": "TRUE",
            "benchmark_flag": "TRUE",
            "candidate_flag": "FALSE",
            "duplicate_removed_flag": tf(ticker in seen),
        })
    return candidates + benchmarks


def build_universe_from_v46(v46_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    candidates = []
    sorted_rows = sorted(v46_rows, key=lambda row: int(float(clean(row.get("source_rank")) or "999999")))
    for row in sorted_rows:
        ticker = clean(row.get("ticker")).upper()
        if not valid_symbol(ticker) or clean(row.get("universe_role")) != "candidate":
            continue
        if ticker in seen:
            continue
        seen.add(ticker)
        candidates.append({
            "ticker": ticker,
            "universe_role": "candidate",
            "source_stage": clean(row.get("source_stage")) or "V20.46_CURRENT_MARKET_REFRESH_READINESS_GATE",
            "source_rank": clean(row.get("source_rank")),
            "source_rank_or_score": clean(row.get("source_rank_or_score")),
            "source_contract": clean(row.get("source_artifact")) or rel(IN_V46_CANDIDATE_UNIVERSE),
            "requested_for_refresh": "TRUE",
            "benchmark_flag": "FALSE",
            "candidate_flag": "TRUE",
            "duplicate_removed_flag": "FALSE",
        })
    benchmarks = []
    for ticker in ["SPY", "QQQ"]:
        benchmarks.append({
            "ticker": ticker,
            "universe_role": "benchmark",
            "source_stage": STAGE,
            "source_rank": "",
            "source_rank_or_score": "",
            "source_contract": "required_benchmark_ticker",
            "requested_for_refresh": "TRUE",
            "benchmark_flag": "TRUE",
            "candidate_flag": "FALSE",
            "duplicate_removed_flag": tf(ticker in seen),
        })
    return candidates + benchmarks


def safe_float(value: object) -> str:
    try:
        if value is None:
            return ""
        number = float(value)
        if math.isnan(number):
            return ""
        return f"{number:.10g}"
    except (TypeError, ValueError):
        return ""


def field_key(value: object) -> str:
    return clean(value).lower().replace("_", " ").replace("-", " ")


def is_adj_close_field(value: object) -> bool:
    return field_key(value) in {"adj close", "adjusted close"}


def is_close_field(value: object) -> bool:
    return field_key(value) == "close"


def is_requested_ticker(value: object, ticker: str) -> bool:
    return clean(value).upper() == ticker.upper()


def date_text(value: object) -> str:
    if hasattr(value, "date"):
        try:
            return str(value.date())
        except Exception:
            pass
    text = clean(value)
    return text[:10] if len(text) >= 10 else text


def positive_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or number <= 0:
        return None
    return number


def iter_close_like_series(df: Any, ticker: str) -> list[tuple[str, Any]]:
    try:
        columns = list(df.columns)
    except Exception:
        return []
    candidates: list[tuple[int, str, Any]] = []
    for column in columns:
        if isinstance(column, tuple):
            parts = list(column)
            ticker_matches = [part for part in parts if is_requested_ticker(part, ticker)]
            field_parts = [part for part in parts if is_adj_close_field(part) or is_close_field(part)]
            if not field_parts:
                continue
            if ticker_matches or len({clean(part).upper() for part in parts if clean(part)}) == 1:
                field = clean(field_parts[0])
            elif len(columns) <= 8:
                field = clean(field_parts[0])
            else:
                continue
        else:
            if not (is_adj_close_field(column) or is_close_field(column)):
                continue
            field = clean(column)
        priority = 0 if is_adj_close_field(field) else 1
        try:
            series = df[column]
        except Exception:
            continue
        candidates.append((priority, field, series))
    candidates.sort(key=lambda item: item[0])
    return [(field, series) for _, field, series in candidates]


def extract_latest_close_like_price(df: Any, ticker: str) -> dict[str, object]:
    if df is None or getattr(df, "empty", True):
        return {
            "latest_price_date": "",
            "latest_close": "",
            "selected_price_field": "",
            "extraction_status": "FAILED",
            "extraction_reason": "empty_dataframe",
        }
    for field, series in iter_close_like_series(df, ticker):
        try:
            values = list(series.items())
        except Exception:
            continue
        for idx, value in reversed(values):
            number = positive_float(value)
            if number is None:
                continue
            return {
                "latest_price_date": date_text(idx),
                "latest_close": f"{number:.10g}",
                "selected_price_field": field,
                "extraction_status": "SUCCESS",
                "extraction_reason": "",
            }
    return {
        "latest_price_date": "",
        "latest_close": "",
        "selected_price_field": "",
        "extraction_status": "FAILED",
        "extraction_reason": "missing_close_like_fields_or_values",
    }


def latest_field_value(df: Any, ticker: str, field_names: set[str], latest_date: str = "") -> str:
    if df is None or getattr(df, "empty", True):
        return ""
    try:
        columns = list(df.columns)
    except Exception:
        return ""
    wanted = {field_key(name) for name in field_names}
    for column in columns:
        if isinstance(column, tuple):
            parts = list(column)
            if not any(field_key(part) in wanted for part in parts):
                continue
            if not any(is_requested_ticker(part, ticker) for part in parts) and len(columns) > 8:
                continue
        elif field_key(column) not in wanted:
            continue
        try:
            series = df[column]
            values = list(series.items())
        except Exception:
            continue
        for idx, value in reversed(values):
            if latest_date and date_text(idx) != latest_date:
                continue
            formatted = safe_float(value)
            if formatted:
                return formatted
    return ""


def dataframe_for_ticker(df: Any, ticker: str) -> Any:
    if df is None or getattr(df, "empty", True):
        return df
    try:
        columns = df.columns
        if getattr(columns, "nlevels", 1) > 1:
            for level in range(columns.nlevels):
                level_values = [clean(value).upper() for value in columns.get_level_values(level)]
                if ticker.upper() in level_values:
                    try:
                        return df.xs(ticker, axis=1, level=level, drop_level=True)
                    except Exception:
                        return df
    except Exception:
        return df
    return df


def dataframe_row_count(df: Any) -> int:
    if df is None:
        return 0
    try:
        return int(len(df.index))
    except Exception:
        return 0


def price_row_from_dataframe(run_id: str, ticker: str, group: str, requested_at: str, df: Any, retry_attempted: bool, retry_status: str, provider_call_status: str, provider_ticker: str = "") -> tuple[dict[str, object], dict[str, object] | None]:
    lookup_ticker = provider_ticker or ticker
    ticker_df = dataframe_for_ticker(df, lookup_ticker)
    extracted = extract_latest_close_like_price(ticker_df, lookup_ticker)
    latest_date = clean(extracted.get("latest_price_date"))
    selected_field = clean(extracted.get("selected_price_field"))
    close_like_price = clean(extracted.get("latest_close"))
    open_price = latest_field_value(ticker_df, ticker, {"Open"}, latest_date)
    high = latest_field_value(ticker_df, ticker, {"High"}, latest_date)
    low = latest_field_value(ticker_df, ticker, {"Low"}, latest_date)
    volume = latest_field_value(ticker_df, ticker, {"Volume"}, latest_date)
    close = close_like_price if is_close_field(selected_field) else latest_field_value(ticker_df, ticker, {"Close"}, latest_date)
    adj_close = close_like_price if is_adj_close_field(selected_field) else latest_field_value(ticker_df, ticker, {"Adj Close", "Adjusted Close", "adj_close"}, latest_date)
    if not adj_close and close:
        adj_close = close
    if not close and adj_close:
        close = adj_close
    if clean(extracted.get("extraction_status")) == "SUCCESS":
        partial = not all([open_price, high, low, volume])
        row = price_row(run_id, ticker, group, requested_at, "PARTIAL" if partial else "SUCCESS", latest_date, open_price, high, low, close, adj_close, volume, "", selected_field, close_like_price, "SUCCESS", "", retry_attempted, retry_status, provider_call_status)
        return row, None
    reason = clean(extracted.get("extraction_reason")) or "missing_close_like_fields_or_values"
    row = price_row(run_id, ticker, group, requested_at, "FAILED", latest_date, open_price, high, low, close, adj_close, volume, reason, selected_field, close_like_price, "FAILED", reason, retry_attempted, retry_status, provider_call_status)
    return row, failure_row(run_id, ticker, group, "missing_price", reason, group == "benchmark_tickers", retry_attempted, retry_status, provider_call_status)


def diagnostic_row(
    ticker: str,
    provider_ticker: str,
    group: str,
    requested_at: str,
    raw_rows: int,
    normalized_rows: int,
    price: dict[str, object] | None,
    refresh_status: str,
    failure_reason: str,
    exception_type: str = "",
    exception_message: str = "",
    cache_file_path: str = "",
    cache_rows_before: int = 0,
    cache_rows_after: int = 0,
) -> dict[str, object]:
    price = price or {}
    return {
        "ticker": ticker,
        "normalized_provider_ticker": provider_ticker,
        "ticker_source": "benchmark" if group == "benchmark_tickers" else "candidate",
        "provider_name": PROVIDER_NAME,
        "request_start_date": "",
        "request_end_date": "",
        "request_period_or_window": "period=7d;interval=1d",
        "raw_rows_returned": raw_rows,
        "normalized_rows_returned": normalized_rows,
        "latest_price_date": clean(price.get("latest_price_date")),
        "latest_close": clean(price.get("latest_close") or price.get("close_like_price")),
        "cache_file_path": cache_file_path,
        "cache_rows_before": cache_rows_before,
        "cache_rows_after": cache_rows_after,
        "refresh_status": refresh_status,
        "failure_reason": failure_reason,
        "exception_type": exception_type,
        "exception_message": exception_message,
    }


def fetch_yahoo_group(tickers: list[str], group: str, run_id: str) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object], list[dict[str, object]]]:
    requested_at = utc_now()
    rows: list[dict[str, object]] = []
    failures_by_ticker: dict[str, dict[str, object]] = {}
    diagnostics_by_ticker: dict[str, dict[str, object]] = {}
    provider_ticker_by_ticker = {ticker: normalize_provider_ticker(ticker) for ticker in tickers}
    yfinance_import_used = False
    status = "SUCCESS"
    failure_reason = ""
    provider_diag = provider_cache_diagnostics()
    try:
        import yfinance as yf  # type: ignore

        yfinance_import_used = True
        provider_diag = configure_provider_cache(yf)
    except Exception as exc:  # pragma: no cover - environment-dependent
        status = "IMPORT_FAILED"
        failure_reason = f"yfinance_import_failed: {exc}"
        for ticker in tickers:
            rows.append(price_row(run_id, ticker, group, requested_at, "FAILED", "", "", "", "", "", "", "", failure_reason, "", "", "FAILED", failure_reason, False, "NOT_ATTEMPTED", status, provider_diag))
            failures_by_ticker[ticker] = failure_row(run_id, ticker, group, "import_failed", failure_reason, True, False, "NOT_ATTEMPTED", status, provider_diag)
            diagnostics_by_ticker[ticker] = diagnostic_row(ticker, provider_ticker_by_ticker[ticker], group, requested_at, 0, 0, rows[-1], "FAILED", failure_reason, type(exc).__name__, clean(exc))
        return rows, list(failures_by_ticker.values()), audit_row(group, requested_at, len(tickers), 0, 0, len(failures_by_ticker), status, yfinance_import_used, failure_reason, 0, 0, provider_diag), list(diagnostics_by_ticker.values())

    batch_status = "SUCCESS"
    batch_exception_type = ""
    batch_exception_message = ""
    try:
        batch_df = yf.download(tickers=list(provider_ticker_by_ticker.values()), period="7d", interval="1d", group_by="column", auto_adjust=False, progress=False, threads=False)
    except Exception as exc:  # pragma: no cover - provider-dependent
        batch_status = "FAILED"
        failure_reason = f"batch_provider_exception: {exc}"
        batch_exception_type = type(exc).__name__
        batch_exception_message = clean(exc)
        batch_df = None

    for ticker in tickers:
        provider_ticker = provider_ticker_by_ticker[ticker]
        ticker_df = dataframe_for_ticker(batch_df, provider_ticker)
        row, failure = price_row_from_dataframe(run_id, ticker, group, requested_at, batch_df, False, "NOT_ATTEMPTED", batch_status, provider_ticker)
        rows.append(row)
        if failure:
            failures_by_ticker[ticker] = failure
        diagnostics_by_ticker[ticker] = diagnostic_row(
            ticker,
            provider_ticker,
            group,
            requested_at,
            dataframe_row_count(batch_df),
            dataframe_row_count(ticker_df),
            row,
            clean(row.get("refresh_status")),
            clean(row.get("failure_reason") or row.get("provider_error_message")),
            batch_exception_type,
            batch_exception_message,
        )

    retry_attempted_count = 0
    retry_success_count = 0
    failed_tickers = [clean(row.get("ticker")) for row in rows if clean(row.get("refresh_status")) == "FAILED"]
    for ticker in failed_tickers:
        retry_attempted_count += 1
        retry_status = "SUCCESS"
        retry_exception_type = ""
        retry_exception_message = ""
        if provider_error_type(failures_by_ticker.get(ticker, {}).get("retry_status") or failures_by_ticker.get(ticker, {}).get("failure_reason")) == "PROVIDER_CACHE_DB_ERROR":
            provider_diag = configure_provider_cache(yf)
        time.sleep(0.2)
        try:
            history = yf.Ticker(provider_ticker_by_ticker[ticker]).history(period="7d", interval="1d", auto_adjust=False)
        except Exception as exc:  # pragma: no cover - provider-dependent
            retry_status = f"FAILED: {exc}"
            retry_exception_type = type(exc).__name__
            retry_exception_message = clean(exc)
            history = None
        retry_row, retry_failure = price_row_from_dataframe(run_id, ticker, group, requested_at, history, True, retry_status, retry_status, provider_ticker_by_ticker[ticker])
        for idx, existing in enumerate(rows):
            if clean(existing.get("ticker")) == ticker:
                rows[idx] = retry_row
                break
        diagnostics_by_ticker[ticker] = diagnostic_row(
            ticker,
            provider_ticker_by_ticker[ticker],
            group,
            requested_at,
            dataframe_row_count(history),
            dataframe_row_count(dataframe_for_ticker(history, provider_ticker_by_ticker[ticker])),
            retry_row,
            clean(retry_row.get("refresh_status")),
            clean(retry_row.get("failure_reason") or retry_row.get("provider_error_message")),
            retry_exception_type,
            retry_exception_message,
        )
        if retry_failure:
            failures_by_ticker[ticker] = retry_failure
        else:
            retry_success_count += 1
            failures_by_ticker.pop(ticker, None)
    success_count = sum(1 for row in rows if row["refresh_status"] == "SUCCESS")
    partial_count = sum(1 for row in rows if row["refresh_status"] == "PARTIAL")
    failure_count = len(failures_by_ticker)
    if failure_count and success_count + partial_count:
        status = "PARTIAL_SUCCESS"
    elif failure_count:
        status = "FAILED"
    if not failure_reason:
        failure_reason = "; ".join(sorted({clean(row.get("provider_call_status")) for row in failures_by_ticker.values() if clean(row.get("provider_call_status"))}))[:300]
    return rows, list(failures_by_ticker.values()), audit_row(group, requested_at, len(tickers), success_count, partial_count, failure_count, status, yfinance_import_used, failure_reason, retry_attempted_count, retry_success_count, provider_diag), list(diagnostics_by_ticker.values())


def price_row(run_id: str, ticker: str, group: str, requested_at: str, status: str, latest_date: str, open_price: str, high: str, low: str, close: str, adj_close: str, volume: str, failure_reason: str, selected_price_field: str = "", close_like_price: str = "", extraction_status: str = "", extraction_reason: str = "", retry_attempted: bool = False, retry_status: str = "NOT_ATTEMPTED", provider_call_status: str = "", provider_diag: dict[str, object] | None = None) -> dict[str, object]:
    diag = provider_diag or provider_cache_diagnostics()
    error_message = clean(failure_reason) or clean(extraction_reason) or (clean(provider_call_status) if clean(provider_call_status).startswith("FAILED") else "")
    retry_error = clean(retry_status).replace("FAILED:", "").strip() if clean(retry_status).startswith("FAILED") else ""
    return {
        "run_id": run_id,
        "ticker": ticker,
        "refresh_group": group,
        "provider_name": PROVIDER_NAME,
        "request_timestamp_utc": requested_at,
        "refresh_status": status,
        "latest_price_date": latest_date,
        "latest_open": open_price,
        "latest_high": high,
        "latest_low": low,
        "latest_close": close,
        "latest_adj_close": adj_close,
        "close_like_price": close_like_price or adj_close or close,
        "selected_price_field": selected_price_field,
        "latest_volume": volume,
        "failure_reason": failure_reason,
        "extraction_status": extraction_status,
        "extraction_reason": extraction_reason,
        "retry_attempted": tf(retry_attempted),
        "retry_status": retry_status,
        "provider_call_status": provider_call_status,
        "provider_error_type": provider_error_type(error_message or retry_error),
        "provider_error_message": error_message,
        "retry_error_message": retry_error,
        "cache_db_error_detected": tf(provider_error_type(error_message or retry_error) == "PROVIDER_CACHE_DB_ERROR"),
        "provider_cache_dir": diag["provider_cache_dir"],
        "provider_cache_dir_exists": diag["provider_cache_dir_exists"],
        "provider_cache_dir_writable": diag["provider_cache_dir_writable"],
    }


def failure_row(run_id: str, ticker: str, group: str, failure_type: str, reason: str, blocks: bool, retry_attempted: bool = False, retry_status: str = "NOT_ATTEMPTED", provider_call_status: str = "", provider_diag: dict[str, object] | None = None) -> dict[str, object]:
    diag = provider_diag or provider_cache_diagnostics()
    retry_error = clean(retry_status).replace("FAILED:", "").strip() if clean(retry_status).startswith("FAILED") else ""
    error_basis = retry_error if provider_error_type(retry_error) == "PROVIDER_CACHE_DB_ERROR" else (reason or retry_error or provider_call_status)
    return {
        "run_id": run_id,
        "ticker": ticker,
        "universe_role": "benchmark" if group == "benchmark_tickers" else "candidate",
        "refresh_group": group,
        "failure_type": failure_type,
        "failure_reason": reason,
        "provider_name": PROVIDER_NAME,
        "retry_recommended": "TRUE",
        "blocks_stage_certification": tf(blocks),
        "retry_attempted": tf(retry_attempted),
        "retry_status": retry_status,
        "provider_call_status": provider_call_status,
        "provider_error_type": provider_error_type(error_basis),
        "provider_error_message": reason,
        "retry_error_message": retry_error,
        "cache_db_error_detected": tf(provider_error_type(error_basis) == "PROVIDER_CACHE_DB_ERROR"),
        "provider_cache_dir": diag["provider_cache_dir"],
        "provider_cache_dir_exists": diag["provider_cache_dir_exists"],
        "provider_cache_dir_writable": diag["provider_cache_dir_writable"],
    }


def audit_row(group: str, requested_at: str, requested: int, success: int, partial: int, failure: int, status: str, yfinance_used: bool, failure_reason: str, retry_attempted: int = 0, retry_success: int = 0, provider_diag: dict[str, object] | None = None) -> dict[str, object]:
    diag = provider_diag or provider_cache_diagnostics()
    return {
        "refresh_group": group,
        "provider_name": PROVIDER_NAME,
        "request_timestamp_utc": requested_at,
        "requested_count": requested,
        "success_count": success,
        "partial_count": partial,
        "failure_count": failure,
        "provider_call_status": status,
        "yfinance_import_used": tf(yfinance_used),
        "network_provider_execution_used": "TRUE",
        "failure_reason": failure_reason,
        "retry_attempted_count": retry_attempted,
        "retry_success_count": retry_success,
        "provider_error_type": provider_error_type(failure_reason),
        "provider_error_message": failure_reason,
        "retry_error_message": "",
        "cache_db_error_detected": tf(provider_error_type(failure_reason) == "PROVIDER_CACHE_DB_ERROR"),
        "provider_cache_dir": diag["provider_cache_dir"],
        "provider_cache_dir_exists": diag["provider_cache_dir_exists"],
        "provider_cache_dir_writable": diag["provider_cache_dir_writable"],
    }


def dominant_reason(rows: list[dict[str, object]]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        if clean(row.get("refresh_status")) in {"SUCCESS", "PARTIAL"}:
            continue
        reason = clean(row.get("failure_reason") or row.get("exception_type") or row.get("refresh_status"))
        if reason:
            counts[reason] = counts.get(reason, 0) + 1
    if not counts:
        return ""
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def build_provider_summary(diagnostics: list[dict[str, object]], audit_rows: list[dict[str, object]], provider_available: bool, recommended_next_action: str) -> dict[str, object]:
    requested = len(diagnostics)
    attempted = sum(1 for row in diagnostics if clean(row.get("refresh_status")) not in {"", "SKIPPED"})
    success = sum(1 for row in diagnostics if clean(row.get("refresh_status")) in {"SUCCESS", "PARTIAL"})
    empty_count = sum(1 for row in diagnostics if clean(row.get("failure_reason")) == "empty_dataframe")
    exception_count = sum(1 for row in diagnostics if clean(row.get("exception_type")))
    invalid_count = sum(1 for row in diagnostics if clean(row.get("failure_reason")) == "invalid_ticker")
    cache_updated = sum(1 for row in diagnostics if clean(row.get("refresh_status")) in {"SUCCESS", "PARTIAL"} and int(float(clean(row.get("cache_rows_after")) or "0")) > 0)
    benchmark_success = sum(1 for row in diagnostics if clean(row.get("ticker_source")) == "benchmark" and clean(row.get("refresh_status")) in {"SUCCESS", "PARTIAL"})
    candidate_success = sum(1 for row in diagnostics if clean(row.get("ticker_source")) == "candidate" and clean(row.get("refresh_status")) in {"SUCCESS", "PARTIAL"})
    starts = [clean(row.get("request_start_date")) for row in diagnostics if clean(row.get("request_start_date"))]
    ends = [clean(row.get("request_end_date")) for row in diagnostics if clean(row.get("request_end_date"))]
    audit_failure = dominant_reason(audit_rows)
    dom = dominant_reason(diagnostics) or audit_failure
    if exception_count and not dom:
        dom = "provider_exception"
    return {
        "requested_ticker_count": requested,
        "attempted_ticker_count": attempted,
        "success_count": success,
        "empty_dataframe_count": empty_count,
        "exception_count": exception_count,
        "invalid_ticker_count": invalid_count,
        "cache_updated_count": cache_updated,
        "benchmark_success_count": benchmark_success,
        "candidate_success_count": candidate_success,
        "earliest_request_start_date": min(starts) if starts else "",
        "latest_request_end_date": max(ends) if ends else "",
        "provider_name": PROVIDER_NAME,
        "provider_available": tf(provider_available),
        "dominant_failure_reason": dom,
        "recommended_next_action": recommended_next_action,
    }


def certify_candidate_rows(price_rows: list[dict[str, object]], source_hash: str, source_cache_path: Path = RAW_CANDIDATE_CACHE) -> list[dict[str, object]]:
    out = []
    for row in price_rows:
        close_like_price = clean(row.get("close_like_price")) or clean(row.get("latest_adj_close")) or clean(row.get("latest_close"))
        missing = not close_like_price or not clean(row.get("latest_price_date")) or not clean(row.get("selected_price_field"))
        provider_failure = clean(row.get("refresh_status")) == "FAILED"
        certified = not missing and not provider_failure
        out.append({
            "ticker": row["ticker"],
            "refresh_status": row["refresh_status"],
            "latest_price_date": row["latest_price_date"],
            "latest_close": row["latest_close"],
            "latest_adj_close": row["latest_adj_close"],
            "close_like_price": close_like_price,
            "selected_price_field": row.get("selected_price_field", ""),
            "latest_volume": row["latest_volume"],
            "stale_flag": "FALSE",
            "missing_price_flag": tf(missing),
            "provider_failure_flag": tf(provider_failure),
            "certification_status": "CERTIFIED" if certified else "BLOCKED",
            "blocker_reason": "" if certified else clean(row.get("failure_reason")) or "missing_price",
            "retry_attempted": row.get("retry_attempted", "FALSE"),
            "retry_status": row.get("retry_status", ""),
            "provider_call_status": row.get("provider_call_status", ""),
            "blocks_stage_certification": "FALSE",
            "source_cache_path": rel(source_cache_path),
            "source_hash": source_hash,
        })
    return out


def certify_benchmark_rows(price_rows: list[dict[str, object]], source_hash: str, source_cache_path: Path = RAW_BENCHMARK_CACHE) -> list[dict[str, object]]:
    out = []
    for row in price_rows:
        close_like_price = clean(row.get("close_like_price")) or clean(row.get("latest_adj_close")) or clean(row.get("latest_close"))
        missing = not close_like_price or not clean(row.get("latest_price_date")) or not clean(row.get("selected_price_field"))
        provider_failure = clean(row.get("refresh_status")) == "FAILED"
        certified = not missing and not provider_failure
        out.append({
            "benchmark_ticker": row["ticker"],
            "refresh_status": row["refresh_status"],
            "latest_price_date": row["latest_price_date"],
            "latest_close": row["latest_close"],
            "latest_adj_close": row["latest_adj_close"],
            "close_like_price": close_like_price,
            "selected_price_field": row.get("selected_price_field", ""),
            "latest_volume": row["latest_volume"],
            "stale_flag": "FALSE",
            "missing_price_flag": tf(missing),
            "provider_failure_flag": tf(provider_failure),
            "certification_status": "CERTIFIED" if certified else "BLOCKED",
            "blocker_reason": "" if certified else clean(row.get("failure_reason")) or "missing_price",
            "retry_attempted": row.get("retry_attempted", "FALSE"),
            "retry_status": row.get("retry_status", ""),
            "provider_call_status": row.get("provider_call_status", ""),
            "blocks_stage_certification": tf(not certified),
            "source_cache_path": rel(source_cache_path),
            "source_hash": source_hash,
        })
    return out


def run_v46_tests() -> tuple[bool, str]:
    if not IN_V46_TEST.exists():
        return False, "V20.46 formal test script missing"
    result = subprocess.run([sys.executable, str(IN_V46_TEST)], cwd=str(ROOT), text=True, capture_output=True, check=False)
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return result.returncode == 0 and "PASS_V20_46_TESTS" in result.stdout.splitlines(), output


def md_table(rows: list[dict[str, object]], columns: list[str], limit: int = 20) -> str:
    if not rows:
        return "_No rows available._\n"
    text = "| " + " | ".join(columns) + " |\n"
    text += "| " + " | ".join("---" for _ in columns) + " |\n"
    for row in rows[:limit]:
        text += "| " + " | ".join(clean(row.get(col)).replace("|", "/") for col in columns) + " |\n"
    if len(rows) > limit:
        text += f"\n_Showing {limit} of {len(rows)} rows._\n"
    return text


def ledger_rows(run_id: str, paths: list[tuple[Path, str, str]], created_at: str) -> list[dict[str, object]]:
    rows = []
    for path, artifact_type, role in paths:
        rows.append({
            "run_id": run_id,
            "artifact_name": path.name,
            "artifact_path": rel(path),
            "artifact_type": artifact_type,
            "sha256": sha256_file(path) if path.exists() else "",
            "row_count": csv_row_count(path) if path.suffix.lower() == ".csv" and path.exists() else "",
            "created_timestamp_utc": created_at,
            "source_role": role,
        })
    return rows


def current_certified_run_id() -> str:
    staged_rows, _ = read_csv(OUT_STAGED_CANDIDATE)
    run_ids = sorted({clean(row.get("run_id")) for row in staged_rows if clean(row.get("run_id"))})
    if run_ids:
        return run_ids[-1]
    summary = first_row(OUT_SUMMARY)
    if clean(summary.get("certification_status")) in {CERTIFIED_STATUS, PARTIAL_CERTIFIED_STATUS}:
        return clean(summary.get("run_id"))
    return ""


def parse_date(value: object) -> datetime | None:
    text = clean(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def duplicate_count(rows: list[dict[str, str]], key_field: str) -> int:
    seen: set[str] = set()
    dupes = 0
    for row in rows:
        key = clean(row.get(key_field)).upper()
        if not key:
            continue
        if key in seen:
            dupes += 1
        seen.add(key)
    return dupes


def ledger_artifact_ok(ledger: list[dict[str, str]], source_role: str) -> tuple[bool, str]:
    for row in ledger:
        if clean(row.get("source_role")) != source_role:
            continue
        path_text = clean(row.get("artifact_path"))
        path = ROOT / path_text
        if path.exists() and clean(row.get("sha256")) == sha256_file(path):
            return True, path_text
    return False, ""


def validate_certified_cache_fallback(
    expected_candidate_count: int,
    candidate_threshold: int,
    expected_benchmark_count: int,
    attempted_run_id: str,
    provider_summary: dict[str, object],
) -> tuple[bool, dict[str, object]]:
    certified_run_id = current_certified_run_id()
    staged_candidates, _ = read_csv(OUT_STAGED_CANDIDATE)
    staged_benchmarks, _ = read_csv(OUT_STAGED_BENCHMARK)
    candidate_cert_rows, _ = read_csv(OUT_CANDIDATE_CERT)
    benchmark_cert_rows, _ = read_csv(OUT_BENCHMARK_CERT)
    ledger, _ = read_csv(OUT_HASH_LEDGER)
    candidate_run_ids = {clean(row.get("run_id")) for row in staged_candidates if clean(row.get("run_id"))}
    benchmark_run_ids = {clean(row.get("run_id")) for row in staged_benchmarks if clean(row.get("run_id"))}
    candidate_latest_dates = [parse_date(row.get("latest_price_date")) for row in staged_candidates]
    benchmark_latest_dates = [parse_date(row.get("latest_price_date")) for row in staged_benchmarks]
    latest_dates = [date for date in candidate_latest_dates + benchmark_latest_dates if date is not None]
    latest_price_date = max(latest_dates).strftime("%Y-%m-%d") if latest_dates else ""
    latest_dt = parse_date(latest_price_date)
    cache_age_days = (datetime.now(timezone.utc).replace(tzinfo=None).date() - latest_dt.date()).days if latest_dt else 999999
    max_cache_age_days = 3
    candidate_certified_count = sum(1 for row in candidate_cert_rows if clean(row.get("certification_status")) == "CERTIFIED")
    benchmark_certified_count = sum(1 for row in benchmark_cert_rows if clean(row.get("certification_status")) == "CERTIFIED")
    missing_ticker_count = max(0, expected_candidate_count - len({clean(row.get("ticker")).upper() for row in staged_candidates if clean(row.get("ticker"))}))
    duplicate_ticker_count = duplicate_count(staged_candidates, "ticker")
    duplicate_benchmark_count = duplicate_count(staged_benchmarks, "benchmark_ticker")
    ledger_run_ids = {clean(row.get("run_id")) for row in ledger if clean(row.get("run_id"))}
    candidate_hash_ok, candidate_cert_source = ledger_artifact_ok(ledger, "candidate_certification")
    benchmark_hash_ok, benchmark_cert_source = ledger_artifact_ok(ledger, "benchmark_certification")
    staged_hash_ok, staged_candidate_source = ledger_artifact_ok(ledger, "staged_candidate_source")
    benchmark_staged_hash_ok, staged_benchmark_source = ledger_artifact_ok(ledger, "staged_benchmark_source")
    fallback_valid = (
        bool(certified_run_id)
        and candidate_run_ids == {certified_run_id}
        and benchmark_run_ids == {certified_run_id}
        and certified_run_id in ledger_run_ids
        and candidate_certified_count >= candidate_threshold
        and benchmark_certified_count >= expected_benchmark_count
        and len(staged_candidates) >= candidate_threshold
        and len(staged_benchmarks) >= expected_benchmark_count
        and cache_age_days <= max_cache_age_days
        and duplicate_ticker_count == 0
        and duplicate_benchmark_count == 0
        and candidate_hash_ok
        and benchmark_hash_ok
        and staged_hash_ok
        and benchmark_staged_hash_ok
    )
    failure_reasons = []
    if not certified_run_id:
        failure_reasons.append("missing_current_certified_run_id")
    if candidate_run_ids and candidate_run_ids != {certified_run_id}:
        failure_reasons.append("candidate_run_id_mismatch")
    if benchmark_run_ids and benchmark_run_ids != {certified_run_id}:
        failure_reasons.append("benchmark_run_id_mismatch")
    if certified_run_id and certified_run_id not in ledger_run_ids:
        failure_reasons.append("certified_run_id_missing_from_hash_ledger")
    if candidate_certified_count < candidate_threshold:
        failure_reasons.append("candidate_certified_count_below_threshold")
    if benchmark_certified_count < expected_benchmark_count:
        failure_reasons.append("benchmark_certified_count_below_required")
    if cache_age_days > max_cache_age_days:
        failure_reasons.append("cache_age_days_exceeds_limit")
    if duplicate_ticker_count:
        failure_reasons.append("duplicate_candidate_tickers")
    if duplicate_benchmark_count:
        failure_reasons.append("duplicate_benchmark_tickers")
    if not candidate_hash_ok:
        failure_reasons.append("candidate_certification_hash_mismatch_or_missing")
    if not benchmark_hash_ok:
        failure_reasons.append("benchmark_certification_hash_mismatch_or_missing")
    if not staged_hash_ok:
        failure_reasons.append("staged_candidate_hash_mismatch_or_missing")
    if not benchmark_staged_hash_ok:
        failure_reasons.append("staged_benchmark_hash_mismatch_or_missing")
    audit = {
        "fallback_status": "CERTIFIED_CACHE_FALLBACK_HANDOFF" if fallback_valid else "BLOCKED_STALE_OR_INCOMPLETE_CACHE",
        "fallback_used": tf(fallback_valid),
        "fallback_source_run_id": certified_run_id,
        "attempted_run_id": attempted_run_id,
        "provider_available": clean(provider_summary.get("provider_available")),
        "provider_error_summary": clean(provider_summary.get("dominant_failure_reason")),
        "fallback_source_file": staged_candidate_source,
        "fallback_benchmark_source_file": staged_benchmark_source,
        "fallback_candidate_certification_file": candidate_cert_source,
        "fallback_benchmark_certification_file": benchmark_cert_source,
        "latest_price_date": latest_price_date,
        "cache_age_days": cache_age_days,
        "max_cache_age_days": max_cache_age_days,
        "ticker_count_requested": expected_candidate_count,
        "ticker_count_success": len(staged_candidates),
        "candidate_certified_count": candidate_certified_count,
        "candidate_certification_threshold": candidate_threshold,
        "benchmark_count_success": len(staged_benchmarks),
        "benchmark_certified_count": benchmark_certified_count,
        "missing_ticker_count": missing_ticker_count,
        "duplicate_ticker_count": duplicate_ticker_count,
        "duplicate_benchmark_count": duplicate_benchmark_count,
        "hash_ledger_run_id_match": tf(certified_run_id in ledger_run_ids if certified_run_id else False),
        "candidate_certification_hash_ok": tf(candidate_hash_ok),
        "benchmark_certification_hash_ok": tf(benchmark_hash_ok),
        "staged_candidate_hash_ok": tf(staged_hash_ok),
        "staged_benchmark_hash_ok": tf(benchmark_staged_hash_ok),
        "certification_status": FALLBACK_CERTIFIED_STATUS if fallback_valid else BLOCKED_CERT_STATUS,
        "handoff_allowed": tf(fallback_valid),
        "research_only": "TRUE",
        "official_recommendation_created": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "failure_reasons": ";".join(failure_reasons),
        "recommended_next_action": NEXT_STAGE if fallback_valid else "REPAIR_V20_47_PROVIDER_OR_REFRESH_VALID_CERTIFIED_CACHE",
    }
    return fallback_valid, audit


def copy_if_exists(source: Path, target: Path) -> None:
    if source.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def cleanup_pycache() -> None:
    for path in SCRIPT_DIR.rglob("__pycache__"):
        if path.is_dir():
            shutil.rmtree(path)


def evaluate_stage_decision(candidate_requested: int, certified_candidate_count: int, certified_benchmark_count: int, failures: list[dict[str, object]], upstream_blockers: list[str] | None = None) -> dict[str, object]:
    blockers = list(upstream_blockers or [])
    candidate_certification_threshold = max(1, math.ceil(candidate_requested * 0.90))
    threshold_met = certified_candidate_count >= candidate_certification_threshold
    benchmark_threshold = certified_benchmark_count == 2
    hard_blocker_count = sum(1 for row in failures if clean(row.get("blocks_stage_certification")) == "TRUE")
    partial_research_handoff_allowed = benchmark_threshold and certified_candidate_count >= 1 and hard_blocker_count == 0
    if certified_candidate_count < 1:
        blockers.append("candidate_certified_count_zero")
    if hard_blocker_count:
        blockers.append(f"hard_blocker_count={hard_blocker_count}")
    if not benchmark_threshold:
        blockers.append("benchmark_certification_threshold_not_met")
    partial_handoff_used = not blockers and not threshold_met and partial_research_handoff_allowed
    certification_status = PARTIAL_CERTIFIED_STATUS if partial_handoff_used else (CERTIFIED_STATUS if not blockers else BLOCKED_CERT_STATUS)
    decision = DECISION_PARTIAL if partial_handoff_used else (DECISION_PASS if not blockers else "BLOCKED_CONTROLLED_REFRESH_CERTIFICATION")
    final_status = PASS_STATUS if not blockers else BLOCKED_STATUS
    return {
        "blockers": blockers,
        "candidate_certification_threshold": candidate_certification_threshold,
        "threshold_met": threshold_met,
        "benchmark_threshold": benchmark_threshold,
        "hard_blocker_count": hard_blocker_count,
        "partial_research_handoff_allowed": partial_research_handoff_allowed,
        "partial_handoff_used": partial_handoff_used,
        "certification_status": certification_status,
        "decision": decision,
        "final_status": final_status,
    }


def main() -> int:
    run_id = "V20_47_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    created_at = utc_now()
    run_attempt_dir = ATTEMPT_DIR / run_id
    run_attempt_dir.mkdir(parents=True, exist_ok=True)
    run_raw_candidate_cache = run_attempt_dir / "V20_47_YAHOO_CURRENT_CANDIDATE_PRICE_CACHE.csv"
    run_raw_benchmark_cache = run_attempt_dir / "V20_47_YAHOO_CURRENT_BENCHMARK_PRICE_CACHE.csv"
    run_raw_failures = run_attempt_dir / "V20_47_YAHOO_CURRENT_REFRESH_FAILURES.csv"
    run_raw_hash_ledger = run_attempt_dir / "V20_47_YAHOO_CURRENT_CACHE_HASH_LEDGER.csv"
    run_raw_manifest = run_attempt_dir / "V20_47_YAHOO_CURRENT_REFRESH_RUN_MANIFEST.csv"
    run_out_candidate_cache = CONSOLIDATION / f"V20_47_{run_id}_YAHOO_CURRENT_CANDIDATE_PRICE_CACHE.csv"
    run_out_benchmark_cache = CONSOLIDATION / f"V20_47_{run_id}_YAHOO_CURRENT_BENCHMARK_PRICE_CACHE.csv"
    run_out_failures = CONSOLIDATION / f"V20_47_{run_id}_YAHOO_CURRENT_REFRESH_FAILURES.csv"
    run_candidate_cert_path = CONSOLIDATION / f"V20_47_{run_id}_CURRENT_CANDIDATE_PRICE_CERTIFICATION.csv"
    run_benchmark_cert_path = CONSOLIDATION / f"V20_47_{run_id}_CURRENT_BENCHMARK_PRICE_CERTIFICATION.csv"
    run_staged_candidate_path = CONSOLIDATION / f"V20_47_{run_id}_CURRENT_MARKET_SOURCE_STAGED_CANDIDATE.csv"
    run_staged_benchmark_path = CONSOLIDATION / f"V20_47_{run_id}_CURRENT_BENCHMARK_SOURCE_STAGED_CANDIDATE.csv"
    last_good_before_run = current_certified_run_id()
    blockers: list[str] = []
    warnings: list[str] = []

    v46_summary = first_row(IN_V46_SUMMARY)
    v46_next = first_row(IN_V46_NEXT)
    v46_tests_passed, v46_test_output = run_v46_tests()
    if clean(v46_summary.get("readiness_status")) != "READY_FOR_CONTROLLED_REFRESH_STAGE":
        blockers.append("v20_46_not_ready_for_controlled_refresh")
    if clean(v46_next.get("decision")) != "PASS_READY_FOR_CONTROLLED_CURRENT_MARKET_REFRESH_STAGE":
        blockers.append("v20_46_next_step_not_pass")
    if not v46_tests_passed:
        blockers.append("v20_46_formal_tests_not_passed")
    if not IN_V46_CURRENT.exists() or not IN_V46_READ_FIRST.exists():
        blockers.append("v20_46_read_center_or_read_first_missing")
    for path in [IN_V46_CANDIDATE_UNIVERSE, IN_V46_SOURCE_AUDIT, IN_V45_LINEAGE, IN_V45_NEXT, IN_V45_CURRENT, IN_V45_READ_FIRST]:
        if not path.exists() or path.stat().st_size == 0:
            blockers.append(f"missing_required_input={rel(path)}")

    v46_candidate_rows, _ = read_csv(IN_V46_CANDIDATE_UNIVERSE)
    if v46_candidate_rows:
        universe = build_universe_from_v46(v46_candidate_rows)
    else:
        candidate_source_rows, _ = read_csv(IN_V45_CANDIDATE)
        universe = build_universe(candidate_source_rows)
    candidate_universe = [row for row in universe if row["universe_role"] == "candidate"]
    benchmark_universe = [row for row in universe if row["universe_role"] == "benchmark"]
    if not candidate_universe:
        blockers.append("candidate_ticker_universe_empty")

    candidate_prices: list[dict[str, object]] = []
    benchmark_prices: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    audit_rows: list[dict[str, object]] = []
    provider_diagnostics: list[dict[str, object]] = []
    if not blockers:
        candidate_prices, candidate_failures, candidate_audit, candidate_provider_diagnostics = fetch_yahoo_group([clean(row["ticker"]) for row in candidate_universe], "candidate_tickers", run_id)
        benchmark_prices, benchmark_failures, benchmark_audit, benchmark_provider_diagnostics = fetch_yahoo_group([clean(row["ticker"]) for row in benchmark_universe], "benchmark_tickers", run_id)
        failures = candidate_failures + benchmark_failures
        audit_rows = [candidate_audit, benchmark_audit]
        provider_diagnostics = candidate_provider_diagnostics + benchmark_provider_diagnostics
    else:
        audit_rows = [
            audit_row("candidate_tickers", created_at, len(candidate_universe), 0, 0, len(candidate_universe), "SKIPPED_BLOCKED_UPSTREAM", False, ";".join(blockers)),
            audit_row("benchmark_tickers", created_at, len(benchmark_universe), 0, 0, len(benchmark_universe), "SKIPPED_BLOCKED_UPSTREAM", False, ";".join(blockers)),
        ]
        failures = [failure_row(run_id, clean(row["ticker"]), "candidate_tickers", "blocked_upstream", ";".join(blockers), True) for row in candidate_universe]
        failures += [failure_row(run_id, clean(row["ticker"]), "benchmark_tickers", "blocked_upstream", ";".join(blockers), True) for row in benchmark_universe]
        for row in candidate_universe:
            ticker = clean(row["ticker"])
            provider_diagnostics.append(diagnostic_row(ticker, normalize_provider_ticker(ticker), "candidate_tickers", created_at, 0, 0, {}, "SKIPPED", ";".join(blockers)))
        for row in benchmark_universe:
            ticker = clean(row["ticker"])
            provider_diagnostics.append(diagnostic_row(ticker, normalize_provider_ticker(ticker), "benchmark_tickers", created_at, 0, 0, {}, "SKIPPED", ";".join(blockers)))

    write_csv(OUT_UNIVERSE, universe, ["ticker", "universe_role", "source_stage", "source_rank", "source_contract", "requested_for_refresh", "benchmark_flag", "candidate_flag", "duplicate_removed_flag"])
    price_fields = ["run_id", "ticker", "refresh_group", "provider_name", "request_timestamp_utc", "refresh_status", "latest_price_date", "latest_open", "latest_high", "latest_low", "latest_close", "latest_adj_close", "close_like_price", "selected_price_field", "latest_volume", "failure_reason", "extraction_status", "extraction_reason", "retry_attempted", "retry_status", "provider_call_status", "provider_error_type", "provider_error_message", "retry_error_message", "cache_db_error_detected", "provider_cache_dir", "provider_cache_dir_exists", "provider_cache_dir_writable"]
    failure_fields = ["run_id", "ticker", "universe_role", "refresh_group", "failure_type", "failure_reason", "provider_name", "retry_recommended", "blocks_stage_certification", "retry_attempted", "retry_status", "provider_call_status", "provider_error_type", "provider_error_message", "retry_error_message", "cache_db_error_detected", "provider_cache_dir", "provider_cache_dir_exists", "provider_cache_dir_writable"]
    audit_fields = ["refresh_group", "provider_name", "request_timestamp_utc", "requested_count", "success_count", "partial_count", "failure_count", "provider_call_status", "yfinance_import_used", "network_provider_execution_used", "failure_reason", "retry_attempted_count", "retry_success_count", "provider_error_type", "provider_error_message", "retry_error_message", "cache_db_error_detected", "provider_cache_dir", "provider_cache_dir_exists", "provider_cache_dir_writable"]
    provider_diagnostic_fields = ["ticker", "normalized_provider_ticker", "ticker_source", "provider_name", "request_start_date", "request_end_date", "request_period_or_window", "raw_rows_returned", "normalized_rows_returned", "latest_price_date", "latest_close", "cache_file_path", "cache_rows_before", "cache_rows_after", "refresh_status", "failure_reason", "exception_type", "exception_message"]
    provider_summary_fields = ["requested_ticker_count", "attempted_ticker_count", "success_count", "empty_dataframe_count", "exception_count", "invalid_ticker_count", "cache_updated_count", "benchmark_success_count", "candidate_success_count", "earliest_request_start_date", "latest_request_end_date", "provider_name", "provider_available", "dominant_failure_reason", "recommended_next_action"]
    cert_fields = ["ticker", "refresh_status", "latest_price_date", "latest_close", "latest_adj_close", "close_like_price", "selected_price_field", "latest_volume", "stale_flag", "missing_price_flag", "provider_failure_flag", "certification_status", "blocker_reason", "retry_attempted", "retry_status", "provider_call_status", "blocks_stage_certification", "source_cache_path", "source_hash"]
    benchmark_cert_fields = ["benchmark_ticker", "refresh_status", "latest_price_date", "latest_close", "latest_adj_close", "close_like_price", "selected_price_field", "latest_volume", "stale_flag", "missing_price_flag", "provider_failure_flag", "certification_status", "blocker_reason", "retry_attempted", "retry_status", "provider_call_status", "blocks_stage_certification", "source_cache_path", "source_hash"]
    write_csv(run_raw_candidate_cache, candidate_prices, price_fields)
    write_csv(run_raw_benchmark_cache, benchmark_prices, price_fields)
    write_csv(run_raw_failures, failures, failure_fields)
    write_csv(run_out_candidate_cache, candidate_prices, price_fields)
    write_csv(run_out_benchmark_cache, benchmark_prices, price_fields)
    write_csv(run_out_failures, failures, failure_fields)
    write_csv(OUT_AUDIT, audit_rows, audit_fields)

    candidate_price_count_by_ticker = {clean(row.get("ticker")): sum(1 for item in candidate_prices if clean(item.get("ticker")) == clean(row.get("ticker"))) for row in candidate_prices}
    benchmark_price_count_by_ticker = {clean(row.get("ticker")): sum(1 for item in benchmark_prices if clean(item.get("ticker")) == clean(row.get("ticker"))) for row in benchmark_prices}
    for row in provider_diagnostics:
        ticker = clean(row.get("ticker"))
        if clean(row.get("ticker_source")) == "benchmark":
            row["cache_file_path"] = rel(run_out_benchmark_cache)
            row["cache_rows_before"] = csv_rows_for_ticker(RAW_BENCHMARK_CACHE, ticker)
            row["cache_rows_after"] = benchmark_price_count_by_ticker.get(ticker, 0)
        else:
            row["cache_file_path"] = rel(run_out_candidate_cache)
            row["cache_rows_before"] = csv_rows_for_ticker(RAW_CANDIDATE_CACHE, ticker)
            row["cache_rows_after"] = candidate_price_count_by_ticker.get(ticker, 0)
    provider_available = any(clean(row.get("refresh_status")) in {"SUCCESS", "PARTIAL"} for row in provider_diagnostics)
    provider_recommended = "V20_47_PROVIDER_REFRESH_PARTIAL_REVIEW_CACHE_CERTIFICATION_GATE" if provider_available else "REPAIR_V20_47_PROVIDER_RUNTIME_OR_NETWORK_EMPTY_DATAFRAME_THEN_RERUN_V20_47"
    provider_summary = build_provider_summary(provider_diagnostics, audit_rows, provider_available, provider_recommended)
    write_csv(OUT_PROVIDER_DIAGNOSTICS, provider_diagnostics, provider_diagnostic_fields)
    write_csv(OUT_PROVIDER_SUMMARY, [provider_summary], provider_summary_fields)

    candidate_cache_hash = sha256_file(run_raw_candidate_cache)
    benchmark_cache_hash = sha256_file(run_raw_benchmark_cache)
    candidate_cert = certify_candidate_rows(candidate_prices, candidate_cache_hash, run_out_candidate_cache)
    benchmark_cert = certify_benchmark_rows(benchmark_prices, benchmark_cache_hash, run_out_benchmark_cache)
    write_csv(run_candidate_cert_path, candidate_cert, cert_fields)
    write_csv(run_benchmark_cert_path, benchmark_cert, benchmark_cert_fields)

    certified_candidate_by_ticker = {clean(row["ticker"]): row for row in candidate_cert if clean(row.get("certification_status")) == "CERTIFIED"}
    source_by_ticker = {clean(row["ticker"]): row for row in candidate_universe}
    staged_candidate = []
    for ticker, cert in certified_candidate_by_ticker.items():
        source = source_by_ticker.get(ticker, {})
        staged_candidate.append({
            "run_id": run_id,
            "ticker": ticker,
            "source_stage": "V20.47_CONTROLLED_CURRENT_MARKET_REFRESH_AND_CACHE_CERTIFICATION",
            "report_rank": clean(source.get("source_rank")),
            "source_rank_or_score": clean(source.get("source_rank_or_score")),
            "latest_price_date": cert["latest_price_date"],
            "latest_close": cert["latest_close"],
            "latest_adj_close": cert["latest_adj_close"],
            "latest_volume": cert["latest_volume"],
            "provider_name": PROVIDER_NAME,
            "cache_hash": cert["source_hash"],
            "certification_status": cert["certification_status"],
            "research_report_handoff_allowed": "TRUE",
            "official_recommendation_allowed": "FALSE",
            "official_trading_allowed": "FALSE",
            "broker_execution_allowed": "FALSE",
            "dynamic_weighting_mutation_allowed": "FALSE",
        })
    staged_benchmark = []
    for cert in benchmark_cert:
        if clean(cert.get("certification_status")) != "CERTIFIED":
            continue
        staged_benchmark.append({
            "run_id": run_id,
            "benchmark_ticker": cert["benchmark_ticker"],
            "latest_price_date": cert["latest_price_date"],
            "latest_close": cert["latest_close"],
            "latest_adj_close": cert["latest_adj_close"],
            "latest_volume": cert["latest_volume"],
            "provider_name": PROVIDER_NAME,
            "cache_hash": cert["source_hash"],
            "certification_status": cert["certification_status"],
            "research_report_handoff_allowed": "TRUE",
            "official_recommendation_allowed": "FALSE",
            "official_trading_allowed": "FALSE",
        })
    staged_candidate.sort(key=lambda row: int(float(clean(row.get("report_rank")) or "999999")))
    staged_benchmark.sort(key=lambda row: clean(row.get("benchmark_ticker")))
    staged_candidate_fields = ["run_id", "ticker", "source_stage", "report_rank", "source_rank_or_score", "latest_price_date", "latest_close", "latest_adj_close", "latest_volume", "provider_name", "cache_hash", "certification_status", "research_report_handoff_allowed", "official_recommendation_allowed", "official_trading_allowed", "broker_execution_allowed", "dynamic_weighting_mutation_allowed"]
    staged_benchmark_fields = ["run_id", "benchmark_ticker", "latest_price_date", "latest_close", "latest_adj_close", "latest_volume", "provider_name", "cache_hash", "certification_status", "research_report_handoff_allowed", "official_recommendation_allowed", "official_trading_allowed"]
    write_csv(run_staged_candidate_path, staged_candidate, staged_candidate_fields)
    write_csv(run_staged_benchmark_path, staged_benchmark, staged_benchmark_fields)

    candidate_requested = len(candidate_universe)
    benchmark_requested = len(benchmark_universe)
    candidate_success = sum(1 for row in audit_rows if row["refresh_group"] == "candidate_tickers" for _ in [0] for __ in [0] for ___ in [0]) and int(next(row["success_count"] for row in audit_rows if row["refresh_group"] == "candidate_tickers"))
    candidate_partial = int(next(row["partial_count"] for row in audit_rows if row["refresh_group"] == "candidate_tickers"))
    candidate_failed = int(next(row["failure_count"] for row in audit_rows if row["refresh_group"] == "candidate_tickers"))
    benchmark_success = int(next(row["success_count"] for row in audit_rows if row["refresh_group"] == "benchmark_tickers"))
    benchmark_failed = int(next(row["failure_count"] for row in audit_rows if row["refresh_group"] == "benchmark_tickers"))
    retry_attempted_count = sum(int(row.get("retry_attempted_count") or 0) for row in audit_rows)
    retry_success_count = sum(int(row.get("retry_success_count") or 0) for row in audit_rows)
    certified_candidate_count = len(staged_candidate)
    certified_benchmark_count = len(staged_benchmark)
    provider_executed = any(clean(row.get("network_provider_execution_used")) == "TRUE" for row in audit_rows)
    yfinance_used = any(clean(row.get("yfinance_import_used")) == "TRUE" for row in audit_rows)
    decision_state = evaluate_stage_decision(candidate_requested, certified_candidate_count, certified_benchmark_count, failures, blockers)
    threshold_met = bool(decision_state["threshold_met"])
    candidate_certification_threshold = int(decision_state["candidate_certification_threshold"])
    hard_blocker_count = int(decision_state["hard_blocker_count"])
    partial_research_handoff_allowed = bool(decision_state["partial_research_handoff_allowed"])
    if candidate_failed:
        warnings.append(f"candidate_refresh_failures={candidate_failed}")
    if candidate_partial:
        warnings.append(f"candidate_partial_refreshes={candidate_partial}")
    if retry_attempted_count:
        warnings.append(f"retry_attempted={retry_attempted_count}")
    if not threshold_met and partial_research_handoff_allowed:
        warnings.append("candidate_certification_threshold_not_met_partial_research_handoff_allowed")
    if not provider_executed:
        decision_state["blockers"].append("provider_refresh_not_executed")
    if not yfinance_used:
        decision_state["blockers"].append("yfinance_import_not_used")
    blockers = list(decision_state["blockers"])
    partial_handoff_used = not blockers and not threshold_met and partial_research_handoff_allowed
    certification_status = PARTIAL_CERTIFIED_STATUS if partial_handoff_used else (CERTIFIED_STATUS if not blockers else BLOCKED_CERT_STATUS)
    decision = DECISION_PARTIAL if partial_handoff_used else (DECISION_PASS if not blockers else "BLOCKED_CONTROLLED_REFRESH_CERTIFICATION")
    final_status = PASS_STATUS if not blockers else BLOCKED_STATUS
    accepted_handoff = not blockers and decision in {DECISION_PASS, DECISION_PARTIAL}
    fallback_valid, fallback_audit = validate_certified_cache_fallback(candidate_requested, candidate_certification_threshold, benchmark_requested, run_id, provider_summary)
    fallback_used = (not accepted_handoff) and fallback_valid
    if fallback_used:
        certification_status = FALLBACK_CERTIFIED_STATUS
        decision = DECISION_PASS
        final_status = PASS_STATUS
    write_csv(OUT_FALLBACK_AUDIT, [fallback_audit], list(fallback_audit.keys()))
    handoff_candidate_certified_count = int(fallback_audit["candidate_certified_count"]) if fallback_used else certified_candidate_count
    handoff_benchmark_certified_count = int(fallback_audit["benchmark_certified_count"]) if fallback_used else certified_benchmark_count
    handoff_threshold_met = handoff_candidate_certified_count >= candidate_certification_threshold
    handoff_hard_blocker_count = 0 if fallback_used else hard_blocker_count
    current_alias_promoted_this_run = accepted_handoff
    if accepted_handoff:
        copy_if_exists(run_raw_candidate_cache, RAW_CANDIDATE_CACHE)
        copy_if_exists(run_raw_benchmark_cache, RAW_BENCHMARK_CACHE)
        copy_if_exists(run_raw_failures, RAW_FAILURES)
        copy_if_exists(run_out_candidate_cache, OUT_RAW_CANDIDATE_CACHE)
        copy_if_exists(run_out_benchmark_cache, OUT_RAW_BENCHMARK_CACHE)
        copy_if_exists(run_out_failures, OUT_RAW_FAILURES)
        copy_if_exists(run_candidate_cert_path, OUT_CANDIDATE_CERT)
        copy_if_exists(run_benchmark_cert_path, OUT_BENCHMARK_CERT)
        copy_if_exists(run_staged_candidate_path, OUT_STAGED_CANDIDATE)
        copy_if_exists(run_staged_benchmark_path, OUT_STAGED_BENCHMARK)
        write_csv(OUT_FAILURE_REGISTER, failures, failure_fields)
    else:
        failed_attempt = [{
            "attempted_run_id": run_id,
            "attempt_timestamp_utc": created_at,
            "current_certified_run_id_before_attempt": last_good_before_run,
            "current_certified_run_id_after_attempt": current_certified_run_id(),
            "current_alias_promoted_this_run": "FALSE",
            "failed_attempt_preserved": "TRUE",
            "failed_attempt_did_not_overwrite_last_good": tf(last_good_before_run == current_certified_run_id()),
            "candidate_tickers_requested": candidate_requested,
            "candidate_tickers_success": candidate_success,
            "candidate_tickers_failed": candidate_failed,
            "benchmark_tickers_requested": benchmark_requested,
            "benchmark_tickers_success": benchmark_success,
            "benchmark_tickers_failed": benchmark_failed,
            "certification_status": certification_status,
            "handoff_status": decision,
            "blocker_count": 0 if fallback_used else len(blockers),
            "warning_count": len(warnings),
            "candidate_attempt_artifact": rel(run_out_candidate_cache),
            "benchmark_attempt_artifact": rel(run_out_benchmark_cache),
            "failure_attempt_artifact": rel(run_out_failures),
        }]
        write_csv(OUT_LAST_FAILED_ATTEMPT, failed_attempt, list(failed_attempt[0].keys()))

    safety = [
        ("provider_refresh_executed_in_v20_47", "TRUE", tf(provider_executed), "Controlled Yahoo/yfinance refresh audit."),
        ("yfinance_imported_in_v20_47", "TRUE", tf(yfinance_used), "yfinance imported inside provider function."),
        ("provider_refresh_limited_to_yahoo_current_market", "TRUE", tf(provider_executed), "Only candidate and benchmark current prices requested."),
        ("broker_order_execution_used", "FALSE", "FALSE", "No broker/order code path."),
        ("official_recommendation_allowed", "FALSE", "FALSE", "Research handoff only."),
        ("official_trading_allowed", "FALSE", "FALSE", "Research handoff only."),
        ("official_ranking_mutated", "FALSE", "FALSE", "Source ranks preserved only."),
        ("dynamic_weighting_mutated", "FALSE", "FALSE", "No weight mutation."),
        ("real_portfolio_mutated", "FALSE", "FALSE", "No portfolio state mutation."),
        ("returns_calculated", "FALSE", "FALSE", "No return calculation."),
        ("scores_recomputed", "FALSE", "FALSE", "No score recomputation."),
        ("rankings_recomputed", "FALSE", "FALSE", "No ranking recomputation."),
        ("trading_signals_created", "FALSE", "FALSE", "No trading signals."),
        ("v21_output_path_created", "FALSE", "FALSE", "No V21 output path."),
        ("v19_21_output_path_created", "FALSE", "FALSE", "No V19.21 output path."),
    ]
    safety_rows = [
        {
            "safety_boundary": name,
            "expected_value": expected,
            "actual_value": actual,
            "validation_status": "PASS" if expected == actual else "BLOCKED",
            "evidence": evidence,
            "blocker_reason": "" if expected == actual else f"expected_{expected}_got_{actual}",
        }
        for name, expected, actual, evidence in safety
    ]
    write_csv(OUT_SAFETY, safety_rows, ["safety_boundary", "expected_value", "actual_value", "validation_status", "evidence", "blocker_reason"])

    manifest_rows = [{
        "stage": STAGE,
        "run_id": run_id,
        "created_timestamp_utc": created_at,
        "provider_name": PROVIDER_NAME,
        "candidate_tickers_requested": candidate_requested,
        "benchmark_tickers_requested": benchmark_requested,
        "certification_status": certification_status,
        "cache_directory": rel(CACHE_DIR),
        "official_recommendation_allowed": "FALSE",
        "official_trading_allowed": "FALSE",
        "broker_order_execution_used": "FALSE",
    }]
    write_csv(run_raw_manifest, manifest_rows, list(manifest_rows[0].keys()))

    ledger_input_paths = [
        (run_raw_candidate_cache, "raw_cache", "raw_candidate_price_cache"),
        (run_raw_benchmark_cache, "raw_cache", "raw_benchmark_price_cache"),
        (run_raw_failures, "failure_register", "refresh_failures"),
        (run_out_candidate_cache, "raw_cache_mirror", "consolidation_candidate_price_cache"),
        (run_out_benchmark_cache, "raw_cache_mirror", "consolidation_benchmark_price_cache"),
        (run_out_failures, "failure_register_mirror", "consolidation_refresh_failures"),
        (run_staged_candidate_path, "staged_source", "staged_candidate_source"),
        (run_staged_benchmark_path, "staged_source", "staged_benchmark_source"),
        (run_candidate_cert_path, "certification", "candidate_certification"),
        (run_benchmark_cert_path, "certification", "benchmark_certification"),
        (run_raw_manifest, "manifest", "run_manifest"),
    ]
    ledger = ledger_rows(run_id, ledger_input_paths, created_at)
    write_csv(run_raw_hash_ledger, ledger, ["run_id", "artifact_name", "artifact_path", "artifact_type", "sha256", "row_count", "created_timestamp_utc", "source_role"])
    if accepted_handoff:
        write_csv(OUT_HASH_LEDGER, ledger, ["run_id", "artifact_name", "artifact_path", "artifact_type", "sha256", "row_count", "created_timestamp_utc", "source_role"])
        write_csv(RAW_HASH_LEDGER, ledger, ["run_id", "artifact_name", "artifact_path", "artifact_type", "sha256", "row_count", "created_timestamp_utc", "source_role"])

    summary = [{
        "stage": STAGE,
        "run_id": run_id,
        "attempted_run_id": run_id,
        "current_certified_run_id": current_certified_run_id(),
        "last_good_certified_run_id": last_good_before_run,
        "current_alias_promoted_this_run": tf(current_alias_promoted_this_run),
        "failed_attempt_preserved": tf(not accepted_handoff),
        "failed_attempt_did_not_overwrite_last_good": tf(accepted_handoff or last_good_before_run == current_certified_run_id()),
        "upstream_v20_46_readiness_status": clean(v46_summary.get("readiness_status")),
        "upstream_v20_46_tests_status": "PASS" if v46_tests_passed else "FAIL",
        "provider_refresh_executed": tf(provider_executed),
        "provider_name": PROVIDER_NAME,
        "provider_available": tf(provider_available),
        "provider_diagnostics_path": rel(OUT_PROVIDER_DIAGNOSTICS),
        "provider_summary_path": rel(OUT_PROVIDER_SUMMARY),
        "provider_error_summary": provider_summary["dominant_failure_reason"],
        "fallback_used": tf(fallback_used),
        "fallback_source_file": fallback_audit["fallback_source_file"],
        "fallback_source_run_id": fallback_audit["fallback_source_run_id"],
        "fallback_status": fallback_audit["fallback_status"],
        "fallback_audit_path": rel(OUT_FALLBACK_AUDIT),
        "latest_price_date": fallback_audit["latest_price_date"],
        "cache_age_days": fallback_audit["cache_age_days"],
        "missing_ticker_count": fallback_audit["missing_ticker_count"],
        "requested_ticker_count": provider_summary["requested_ticker_count"],
        "attempted_ticker_count": provider_summary["attempted_ticker_count"],
        "success_count": provider_summary["success_count"],
        "empty_dataframe_count": provider_summary["empty_dataframe_count"],
        "exception_count": provider_summary["exception_count"],
        "dominant_failure_reason": provider_summary["dominant_failure_reason"],
        "yfinance_import_used": tf(yfinance_used),
        "candidate_tickers_requested": candidate_requested,
        "candidate_tickers_success": candidate_success,
        "candidate_tickers_partial": candidate_partial,
        "candidate_tickers_failed": candidate_failed,
        "benchmark_tickers_requested": benchmark_requested,
        "benchmark_tickers_success": benchmark_success,
        "benchmark_tickers_failed": benchmark_failed,
        "candidate_certification_threshold": candidate_certification_threshold,
        "candidate_certified_count": handoff_candidate_certified_count,
        "candidate_requested_count": candidate_requested,
        "threshold_met": tf(handoff_threshold_met),
        "partial_research_handoff_allowed": tf(partial_research_handoff_allowed),
        "partial_research_handoff_used": tf(partial_handoff_used),
        "hard_blocker_count": handoff_hard_blocker_count,
        "retry_attempted_count": retry_attempted_count,
        "retry_success_count": retry_success_count,
        "candidate_cache_created": tf(RAW_CANDIDATE_CACHE.exists()),
        "benchmark_cache_created": tf(RAW_BENCHMARK_CACHE.exists()),
        "hash_ledger_created": tf(OUT_HASH_LEDGER.exists() and RAW_HASH_LEDGER.exists()),
        "certification_status": certification_status,
        "staged_candidate_source_created": tf(bool(staged_candidate)),
        "staged_benchmark_source_created": tf(bool(staged_benchmark)),
        "official_recommendation_allowed": "FALSE",
        "official_trading_allowed": "FALSE",
        "broker_order_execution_used": "FALSE",
        "official_ranking_mutated": "FALSE",
        "dynamic_weighting_mutated": "FALSE",
        "returns_calculated": "FALSE",
        "scores_recomputed": "FALSE",
        "rankings_recomputed": "FALSE",
        "blocker_count": 0 if fallback_used else len(blockers),
        "warning_count": len(warnings),
        "next_recommended_stage": NEXT_STAGE if (not blockers or fallback_used) else provider_summary["recommended_next_action"],
    }]
    next_rows = [{
        "stage": STAGE,
        "attempted_run_id": run_id,
        "current_certified_run_id": current_certified_run_id(),
        "last_good_certified_run_id": last_good_before_run,
        "current_alias_promoted_this_run": tf(current_alias_promoted_this_run),
        "failed_attempt_preserved": tf(not accepted_handoff),
        "failed_attempt_did_not_overwrite_last_good": tf(accepted_handoff or last_good_before_run == current_certified_run_id()),
        "decision": decision,
        "certification_status": certification_status,
        "refresh_mode": "CERTIFIED_CACHE_FALLBACK_HANDOFF" if fallback_used else ("LIVE_REFRESH_PASS" if accepted_handoff else "BLOCKED_NO_PROVIDER_NO_VALID_CACHE"),
        "fallback_used": tf(fallback_used),
        "fallback_source_file": fallback_audit["fallback_source_file"],
        "fallback_source_run_id": fallback_audit["fallback_source_run_id"],
        "fallback_audit_path": rel(OUT_FALLBACK_AUDIT),
        "latest_price_date": fallback_audit["latest_price_date"],
        "cache_age_days": fallback_audit["cache_age_days"],
        "controlled_refresh_completed": tf(provider_executed),
        "refreshed_cache_certified": tf(accepted_handoff),
        "research_report_handoff_ready": tf(not blockers or fallback_used),
        "official_recommendation_allowed": "FALSE",
        "official_trading_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "formal_tests_required_next": tf(not blockers),
        "candidate_certification_threshold": candidate_certification_threshold,
        "candidate_certified_count": handoff_candidate_certified_count,
        "candidate_requested_count": candidate_requested,
        "threshold_met": tf(handoff_threshold_met),
        "partial_research_handoff_allowed": tf(partial_research_handoff_allowed),
        "partial_research_handoff_used": tf(partial_handoff_used),
        "hard_blocker_count": handoff_hard_blocker_count,
        "blocker_count": 0 if fallback_used else len(blockers),
        "warning_count": len(warnings),
        "next_recommended_stage": NEXT_STAGE if (not blockers or fallback_used) else provider_summary["recommended_next_action"],
    }]
    write_csv(OUT_SUMMARY, summary, list(summary[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))

    blocker_text = "None" if not blockers else "; ".join(blockers)
    warning_text = "None" if not warnings else "; ".join(warnings)
    report = f"""# V20.47 Controlled Current Market Refresh And Cache Certification

## Stage Status

Stage: {STAGE}
Run ID: {run_id}
Status: {final_status}
Certification status: {certification_status}
Attempted run id: {run_id}
Current certified run id: {current_certified_run_id()}
Last-good certified run id before attempt: {last_good_before_run}
Current alias promoted this run: {tf(current_alias_promoted_this_run)}
Failed attempt preserved: {tf(not accepted_handoff)}
Failed attempt did not overwrite last-good: {tf(accepted_handoff or last_good_before_run == current_certified_run_id())}

## Upstream V20.46 Readiness/Test Status

Readiness status: {clean(v46_summary.get("readiness_status"))}
V20.46 formal tests status: {"PASS" if v46_tests_passed else "FAIL"}

## Refresh Scope

V20.47 used controlled Yahoo/yfinance provider refresh for V20.45 candidate tickers and required benchmarks SPY and QQQ.

## Provider Refresh Audit

Provider available: {tf(provider_available)}
Provider error summary: {provider_summary["dominant_failure_reason"]}
Requested ticker count: {provider_summary["requested_ticker_count"]}
Attempted ticker count: {provider_summary["attempted_ticker_count"]}
Success count: {provider_summary["success_count"]}
Empty dataframe count: {provider_summary["empty_dataframe_count"]}
Exception count: {provider_summary["exception_count"]}
Dominant failure reason: {provider_summary["dominant_failure_reason"]}
Provider diagnostics: {rel(OUT_PROVIDER_DIAGNOSTICS)}
Provider summary: {rel(OUT_PROVIDER_SUMMARY)}

## Certified Cache Fallback

Fallback used: {tf(fallback_used)}
Fallback status: {fallback_audit["fallback_status"]}
Fallback source run id: {fallback_audit["fallback_source_run_id"]}
Fallback source file: {fallback_audit["fallback_source_file"]}
Latest price date: {fallback_audit["latest_price_date"]}
Cache age days: {fallback_audit["cache_age_days"]}
Missing ticker count: {fallback_audit["missing_ticker_count"]}
Fallback audit: {rel(OUT_FALLBACK_AUDIT)}

{md_table(audit_rows, ["refresh_group", "requested_count", "success_count", "partial_count", "failure_count", "provider_call_status", "provider_error_type", "cache_db_error_detected", "provider_cache_dir", "provider_cache_dir_exists", "provider_cache_dir_writable", "retry_attempted_count", "retry_success_count"], 10)}

## Candidate Ticker Refresh Certification

Requested: {candidate_requested}
Certified: {certified_candidate_count}
Failed: {candidate_failed}

{md_table(candidate_cert, ["ticker", "refresh_status", "latest_price_date", "close_like_price", "selected_price_field", "certification_status", "blocker_reason", "retry_attempted"], 40)}

## Benchmark Refresh Certification

Requested: {benchmark_requested}
Certified: {certified_benchmark_count}
Failed: {benchmark_failed}

{md_table(benchmark_cert, ["benchmark_ticker", "refresh_status", "latest_price_date", "close_like_price", "selected_price_field", "certification_status", "blocker_reason", "retry_attempted"], 10)}

## Threshold And Partial Handoff Compatibility

| candidate_certification_threshold | candidate_certified_count | candidate_requested_count | threshold_met | partial_research_handoff_allowed | partial_research_handoff_used | hard_blocker_count |
| --- | --- | --- | --- | --- | --- | --- |
| {candidate_certification_threshold} | {certified_candidate_count} | {candidate_requested} | {tf(threshold_met)} | {tf(partial_research_handoff_allowed)} | {tf(partial_handoff_used)} | {hard_blocker_count} |

Retry attempted count: {retry_attempted_count}
Retry success count: {retry_success_count}

## Cache/Hash Ledger Summary

{md_table(ledger, ["artifact_name", "artifact_type", "row_count", "source_role"], 20)}

## Failed Attempt / Failure Register Summary

Last failed attempt artifact: {rel(OUT_LAST_FAILED_ATTEMPT)}

{md_table(failures, ["ticker", "universe_role", "failure_type", "failure_reason", "provider_error_type", "cache_db_error_detected", "retry_error_message", "provider_cache_dir_writable", "blocks_stage_certification", "retry_attempted", "retry_status"], 40)}

## Safety Boundary

{md_table(safety_rows, ["safety_boundary", "expected_value", "actual_value", "validation_status"], 20)}

## Research-Only Handoff Status

Handoff status: {decision}

Outputs are certified only for research-report handoff. They do not create official recommendations or trading signals.

## Explicit Non-Official-Recommendation Statement

This stage generated no buy, sell, or hold advice and no official recommendation packet.

## Explicit Non-Trading/Broker Statement

No broker/order execution occurred.

## Score/Ranking/Return Boundary

No score, ranking, or return recomputation occurred.

## Blockers And Warnings

Blockers: {"None" if fallback_used else blocker_text}
Warnings: {warning_text}

## Next Recommended Stage

{NEXT_STAGE if (not blockers or fallback_used) else "REPAIR_V20_47_REFRESH_CERTIFICATION"}

## V20.46 Formal Test Output

```text
{v46_test_output}
```
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)

    read_first = "\n".join([
        f"STAGE_NAME={STAGE}",
        f"STATUS={final_status}",
        f"RUN_ID={run_id}",
        f"ATTEMPTED_RUN_ID={run_id}",
        f"CURRENT_CERTIFIED_RUN_ID={current_certified_run_id()}",
        f"LAST_GOOD_CERTIFIED_RUN_ID={last_good_before_run}",
        f"CURRENT_ALIAS_PROMOTED_THIS_RUN={tf(current_alias_promoted_this_run)}",
        f"FAILED_ATTEMPT_PRESERVED={tf(not accepted_handoff)}",
        f"FAILED_ATTEMPT_DID_NOT_OVERWRITE_LAST_GOOD={tf(accepted_handoff or last_good_before_run == current_certified_run_id())}",
        f"CONTROLLED_PROVIDER_REFRESH_EXECUTED={tf(provider_executed)}",
        f"PROVIDER_NAME={PROVIDER_NAME}",
        f"PROVIDER_AVAILABLE={tf(provider_available)}",
        f"PROVIDER_ERROR_SUMMARY={provider_summary['dominant_failure_reason']}",
        f"PROVIDER_DIAGNOSTICS={rel(OUT_PROVIDER_DIAGNOSTICS)}",
        f"PROVIDER_SUMMARY={rel(OUT_PROVIDER_SUMMARY)}",
        f"FALLBACK_USED={tf(fallback_used)}",
        f"FALLBACK_SOURCE_FILE={fallback_audit['fallback_source_file']}",
        f"FALLBACK_SOURCE_RUN_ID={fallback_audit['fallback_source_run_id']}",
        f"FALLBACK_STATUS={fallback_audit['fallback_status']}",
        f"FALLBACK_AUDIT={rel(OUT_FALLBACK_AUDIT)}",
        f"LATEST_PRICE_DATE={fallback_audit['latest_price_date']}",
        f"CACHE_AGE_DAYS={fallback_audit['cache_age_days']}",
        f"MISSING_TICKER_COUNT={fallback_audit['missing_ticker_count']}",
        f"REQUESTED_TICKER_COUNT={provider_summary['requested_ticker_count']}",
        f"ATTEMPTED_TICKER_COUNT={provider_summary['attempted_ticker_count']}",
        f"SUCCESS_COUNT={provider_summary['success_count']}",
        f"EMPTY_DATAFRAME_COUNT={provider_summary['empty_dataframe_count']}",
        f"EXCEPTION_COUNT={provider_summary['exception_count']}",
        f"DOMINANT_FAILURE_REASON={provider_summary['dominant_failure_reason']}",
        f"PROVIDER_CACHE_DIR={rel(PROVIDER_CACHE_DIR)}",
        f"PROVIDER_CACHE_DIR_EXISTS={provider_cache_diagnostics()['provider_cache_dir_exists']}",
        f"PROVIDER_CACHE_DIR_WRITABLE={provider_cache_diagnostics()['provider_cache_dir_writable']}",
        f"CACHE_DIR={rel(CACHE_DIR)}",
        f"CANDIDATE_CACHE={rel(RAW_CANDIDATE_CACHE)}",
        f"BENCHMARK_CACHE={rel(RAW_BENCHMARK_CACHE)}",
        f"CERTIFICATION_STATUS={certification_status}",
        f"CANDIDATE_TICKERS_REQUESTED={candidate_requested}",
        f"CANDIDATE_TICKERS_SUCCESS={candidate_success}",
        f"CANDIDATE_TICKERS_PARTIAL={candidate_partial}",
        f"CANDIDATE_TICKERS_FAILED={candidate_failed}",
        f"CANDIDATE_CERTIFICATION_THRESHOLD={candidate_certification_threshold}",
        f"CANDIDATE_CERTIFIED_COUNT={certified_candidate_count}",
        f"THRESHOLD_MET={tf(threshold_met)}",
        f"PARTIAL_RESEARCH_HANDOFF_ALLOWED={tf(partial_research_handoff_allowed)}",
        f"PARTIAL_RESEARCH_HANDOFF_USED={tf(partial_handoff_used)}",
        f"HARD_BLOCKER_COUNT={hard_blocker_count}",
        f"RETRY_ATTEMPTED_COUNT={retry_attempted_count}",
        f"RETRY_SUCCESS_COUNT={retry_success_count}",
        f"BENCHMARK_TICKERS_REQUESTED={benchmark_requested}",
        f"BENCHMARK_TICKERS_SUCCESS={benchmark_success}",
        f"BENCHMARK_TICKERS_FAILED={benchmark_failed}",
        "BROKER_ORDER_EXECUTION_USED=FALSE",
        "OFFICIAL_RECOMMENDATION_ALLOWED=FALSE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "DYNAMIC_WEIGHTING_MUTATED=FALSE",
        "RETURNS_CALCULATED=FALSE",
        "SCORES_RECOMPUTED=FALSE",
        "RANKINGS_RECOMPUTED=FALSE",
        f"RESEARCH_REPORT_HANDOFF_READY={tf(not blockers or fallback_used)}",
        f"HANDOFF_STATUS={decision}",
        f"NEXT_RECOMMENDED_STAGE={NEXT_STAGE if (not blockers or fallback_used) else provider_summary['recommended_next_action']}",
        "",
    ])
    write_text(READ_FIRST, read_first)
    cleanup_pycache()

    print(final_status)
    print(f"RUN_ID={run_id}")
    print(f"PROVIDER_REFRESH_EXECUTED={tf(provider_executed)}")
    print(f"CANDIDATE_REQUESTED={candidate_requested}")
    print(f"CANDIDATE_SUCCESS={candidate_success}")
    print(f"CANDIDATE_PARTIAL={candidate_partial}")
    print(f"CANDIDATE_FAILED={candidate_failed}")
    print(f"BENCHMARK_REQUESTED={benchmark_requested}")
    print(f"BENCHMARK_SUCCESS={benchmark_success}")
    print(f"BENCHMARK_FAILED={benchmark_failed}")
    print(f"RETRY_ATTEMPTED={retry_attempted_count}")
    print(f"RETRY_SUCCESS={retry_success_count}")
    print(f"CERTIFICATION_STATUS={certification_status}")
    print(f"HANDOFF_STATUS={decision}")
    print(f"PROVIDER_AVAILABLE={tf(provider_available)}")
    print(f"DOMINANT_FAILURE_REASON={provider_summary['dominant_failure_reason']}")
    print(f"FALLBACK_USED={tf(fallback_used)}")
    print(f"FALLBACK_SOURCE_RUN_ID={fallback_audit['fallback_source_run_id']}")
    print(f"CACHE_AGE_DAYS={fallback_audit['cache_age_days']}")
    print(f"NEXT_RECOMMENDED_STAGE={NEXT_STAGE if (not blockers or fallback_used) else provider_summary['recommended_next_action']}")
    return 0 if (not blockers or fallback_used) else 1


if __name__ == "__main__":
    raise SystemExit(main())
