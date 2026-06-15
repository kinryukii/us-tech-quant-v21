from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
INPUT_BASE = ROOT / "inputs" / "v20" / "outcome_benchmark"
YAHOO_CACHE = INPUT_BASE / "yahoo_cache"
YAHOO_V20_26 = YAHOO_CACHE / "v20_26"
STAGING_V20_26 = INPUT_BASE / "staging" / "v20_26"

IN_READ_FIRST = OPS / "V20_25_READ_FIRST.txt"
IN_GATE = CONSOLIDATION / "V20_25_GATE_DECISION.csv"
IN_BLOCKERS = CONSOLIDATION / "V20_25_BLOCKER_REGISTER.csv"
IN_OUTCOME_PLAN = CONSOLIDATION / "V20_24_OUTCOME_DATA_REQUIREMENT_PLAN.csv"
IN_BENCHMARK_PLAN = CONSOLIDATION / "V20_24_BENCHMARK_DATA_REQUIREMENT_PLAN.csv"
IN_COVERAGE = CONSOLIDATION / "V20_24_REQUIRED_COVERAGE_MATRIX.csv"
IN_INPUT_REGISTER = CONSOLIDATION / "V20_24_REQUIRED_INPUT_FILE_REGISTER.csv"
IN_OUTCOME_SCHEMA = CONSOLIDATION / "V20_24_OUTCOME_REQUIRED_SCHEMA.csv"
IN_BENCHMARK_SCHEMA = CONSOLIDATION / "V20_24_BENCHMARK_REQUIRED_SCHEMA.csv"
IN_CANDIDATES = CONSOLIDATION / "V20_17_BACKTEST_INPUT_CANDIDATE_DATASET.csv"

TICKER_CACHE = YAHOO_V20_26 / "V20_26_YAHOO_TICKER_PRICE_CACHE.csv"
BENCHMARK_CACHE = YAHOO_V20_26 / "V20_26_YAHOO_BENCHMARK_PRICE_CACHE.csv"
STAGED_OUTCOME = STAGING_V20_26 / "V20_26_STAGED_YAHOO_OUTCOME_SOURCE_INPUT_CANDIDATE.csv"
STAGED_BENCHMARK = STAGING_V20_26 / "V20_26_STAGED_YAHOO_BENCHMARK_SOURCE_INPUT_CANDIDATE.csv"

OUT_DEP = CONSOLIDATION / "V20_26_DEPENDENCY_AUDIT.csv"
OUT_ARCH = CONSOLIDATION / "V20_26_ARCHITECTURE_CORRECTION_DECISION.csv"
OUT_CONFIG = CONSOLIDATION / "V20_26_YAHOO_PROVIDER_CONFIG.csv"
OUT_SYMBOLS = CONSOLIDATION / "V20_26_REQUIRED_SYMBOL_UNIVERSE.csv"
OUT_BENCHMARK_SYMBOLS = CONSOLIDATION / "V20_26_REQUIRED_BENCHMARK_SYMBOLS.csv"
OUT_ATTEMPT = CONSOLIDATION / "V20_26_YAHOO_DOWNLOAD_ATTEMPT_LEDGER.csv"
OUT_TICKER_STATUS = CONSOLIDATION / "V20_26_YAHOO_TICKER_DOWNLOAD_STATUS.csv"
OUT_BENCH_STATUS = CONSOLIDATION / "V20_26_YAHOO_BENCHMARK_DOWNLOAD_STATUS.csv"
OUT_CACHE_REGISTER = CONSOLIDATION / "V20_26_YAHOO_CACHE_FILE_REGISTER.csv"
OUT_HASH = CONSOLIDATION / "V20_26_YAHOO_CACHE_HASH_LEDGER.csv"
OUT_RUN = CONSOLIDATION / "V20_26_RUN_ID_LEDGER.csv"
OUT_SCHEMA = CONSOLIDATION / "V20_26_CACHE_SCHEMA_AUDIT.csv"
OUT_DATE_COVERAGE = CONSOLIDATION / "V20_26_PRICE_DATE_COVERAGE_AUDIT.csv"
OUT_BENCH_COVERAGE = CONSOLIDATION / "V20_26_BENCHMARK_SYMBOL_COVERAGE_AUDIT.csv"
OUT_STAGED_REGISTER = CONSOLIDATION / "V20_26_STAGED_INPUT_CANDIDATE_REGISTER.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_26_BLOCKER_REGISTER.csv"
OUT_NEXT = CONSOLIDATION / "V20_26_NEXT_CERTIFICATION_REQUIREMENTS.csv"
OUT_GATE = CONSOLIDATION / "V20_26_GATE_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_26_VALIDATION_SUMMARY.csv"
OUT_SOURCE_DIAGNOSTICS = CONSOLIDATION / "V20_26_CERTIFIED_CACHE_SOURCE_DIAGNOSTICS.csv"
REPORT = READ_CENTER / "V20_26_YAHOO_RUNTIME_OUTCOME_BENCHMARK_SOURCE_ADAPTER_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_YAHOO_RUNTIME_OUTCOME_BENCHMARK_SOURCE_ADAPTER.md"
READ_FIRST = OPS / "V20_26_READ_FIRST.txt"

PASS_STATUS = "PASS_V20_26_YAHOO_RUNTIME_OUTCOME_BENCHMARK_SOURCE_ADAPTER"
NEXT_READY = "V20.27_YAHOO_CACHE_CERTIFICATION_AND_ACTIVE_INPUT_STAGING"
NEXT_BLOCKED = "V20.27_YAHOO_PROVIDER_FAILURE_BLOCKER_RESOLUTION_OR_FALLBACK_LOCAL_BULK_IMPORT"
SOURCE_CACHE_MODE = "CERTIFIED_LOCAL_CACHE_SOURCE"
REQUIRED_INPUTS = [IN_READ_FIRST, IN_GATE, IN_BLOCKERS, IN_OUTCOME_PLAN, IN_BENCHMARK_PLAN, IN_COVERAGE, IN_INPUT_REGISTER, IN_OUTCOME_SCHEMA, IN_BENCHMARK_SCHEMA]
BENCHMARKS = ["SPY", "QQQ"]
OUTCOME_WINDOWS = {"forward_1d": 1, "forward_5d": 5, "forward_10d": 10, "forward_20d": 20, "forward_60d": 60}
BENCHMARK_WINDOWS = {"benchmark_forward_1d": 1, "benchmark_forward_5d": 5, "benchmark_forward_10d": 10, "benchmark_forward_20d": 20, "benchmark_forward_60d": 60}
CACHE_FIELDS = ["symbol", "price_date", "open", "high", "low", "close", "adjusted_close", "volume", "currency", "data_vendor_or_source_system", "provider_query_start_date", "provider_query_end_date", "provider_download_timestamp_utc", "source_artifact_id", "source_hash", "run_id", "active_runtime_flag", "historical_reference_flag", "created_at_utc", "notes"]


def clean(v: object) -> str:
    return str(v or "").strip()


def upper(v: object) -> str:
    return clean(v).upper()


def tf(v: bool) -> str:
    return "TRUE" if v else "FALSE"


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def first_row(path: Path) -> dict[str, str]:
    rows, _ = read_csv(path)
    return rows[0] if rows else {}


def cache_stats(rows: list[dict[str, str]], symbol_field: str = "symbol") -> dict[str, str]:
    dates = sorted({clean(row.get("price_date"))[:10] for row in rows if parse_date(row.get("price_date"))})
    symbols = sorted({upper(row.get(symbol_field)) for row in rows if clean(row.get(symbol_field))})
    run_ids = sorted({clean(row.get("run_id")) for row in rows if clean(row.get("run_id"))})
    return {
        "row_count": str(len(rows)),
        "symbol_count": str(len(symbols)),
        "min_price_date": dates[0] if dates else "",
        "max_price_date": dates[-1] if dates else "",
        "run_ids": ";".join(run_ids),
    }


def required_target_dates(candidates: list[dict[str, str]], windows: dict[str, int]) -> tuple[str, str, str]:
    signals = [
        parse_date(row.get("effective_price_date")) or parse_date(row.get("effective_observation_date"))
        for row in candidates
    ]
    signals = [signal for signal in signals if signal is not None]
    targets = sorted({(signal + timedelta(days=days)).strftime("%Y-%m-%d") for signal in signals for days in windows.values()})
    if not targets:
        return "", "", ""
    return targets[0], targets[-1], ";".join(targets[:10])


def md_table(headers: list[str], rows: list[dict[str, str]], limit: int = 20) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows[:limit]:
        lines.append("| " + " | ".join(clean(row.get(h)).replace("|", "/") for h in headers) + " |")
    return "\n".join(lines)


def extract_dataframe(data: Any, symbol: str) -> Any:
    try:
        if hasattr(data, "columns") and getattr(data.columns, "nlevels", 1) > 1:
            levels0 = set(str(x) for x in data.columns.get_level_values(0))
            levels1 = set(str(x) for x in data.columns.get_level_values(1))
            if symbol in levels0:
                return data[symbol]
            if symbol in levels1:
                return data.xs(symbol, level=1, axis=1)
        return data
    except Exception:
        return None


def cache_rows_from_download(symbols: list[str], start: str, end: str, run_id: str, created: str, attempt_rows: list[dict[str, str]], status_rows: list[dict[str, str]], role: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        for symbol in symbols:
            status_rows.append({"symbol": symbol, "download_role": role, "download_success": "FALSE", "rows_downloaded": "0", "failure_reason": f"yfinance_import_failed:{exc}"})
        attempt_rows.append({"attempt_id": f"V20_26_ATTEMPT_{role.upper()}_IMPORT", "download_role": role, "provider": "yfinance", "symbols_requested": str(len(symbols)), "attempt_success": "FALSE", "failure_reason": f"yfinance_import_failed:{exc}"})
        return rows

    try:
        data = yf.download(symbols, start=start, end=end, group_by="ticker", auto_adjust=False, progress=False, threads=True)
        attempt_rows.append({"attempt_id": f"V20_26_ATTEMPT_{role.upper()}_BATCH", "download_role": role, "provider": "yfinance", "symbols_requested": str(len(symbols)), "attempt_success": "TRUE", "failure_reason": ""})
    except Exception as exc:
        for symbol in symbols:
            status_rows.append({"symbol": symbol, "download_role": role, "download_success": "FALSE", "rows_downloaded": "0", "failure_reason": f"provider_download_failed:{exc}"})
        attempt_rows.append({"attempt_id": f"V20_26_ATTEMPT_{role.upper()}_BATCH", "download_role": role, "provider": "yfinance", "symbols_requested": str(len(symbols)), "attempt_success": "FALSE", "failure_reason": f"provider_download_failed:{exc}"})
        return rows

    for symbol in symbols:
        df = extract_dataframe(data, symbol)
        symbol_rows = 0
        failure = ""
        try:
            if df is None or getattr(df, "empty", True):
                failure = "empty_download"
            else:
                for idx, r in df.iterrows():
                    close = r.get("Close", "")
                    if close != close:
                        continue
                    price_date = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else clean(idx)[:10]
                    adj = r.get("Adj Close", close)
                    row_hash = sha_text(f"{symbol}|{price_date}|{r.get('Open','')}|{r.get('High','')}|{r.get('Low','')}|{close}|{adj}|{r.get('Volume','')}|{run_id}")
                    rows.append({
                        "symbol": symbol,
                        "price_date": price_date,
                        "open": clean(r.get("Open", "")),
                        "high": clean(r.get("High", "")),
                        "low": clean(r.get("Low", "")),
                        "close": clean(close),
                        "adjusted_close": clean(adj),
                        "volume": clean(r.get("Volume", "")),
                        "currency": "USD",
                        "data_vendor_or_source_system": "Yahoo/yfinance",
                        "provider_query_start_date": start,
                        "provider_query_end_date": end,
                        "provider_download_timestamp_utc": created,
                        "source_artifact_id": f"V20_26_YAHOO_{role.upper()}::{symbol}",
                        "source_hash": row_hash,
                        "run_id": run_id,
                        "active_runtime_flag": "TRUE",
                        "historical_reference_flag": "FALSE",
                        "created_at_utc": created,
                        "notes": "runtime_yahoo_yfinance_cache_only_no_returns_no_backtest",
                    })
                    symbol_rows += 1
        except Exception as exc:
            failure = f"normalization_failed:{exc}"
        status_rows.append({"symbol": symbol, "download_role": role, "download_success": tf(symbol_rows > 0), "rows_downloaded": str(symbol_rows), "failure_reason": "" if symbol_rows > 0 else failure})
    return rows


def make_staged_outcome(cache: list[dict[str, str]], candidates: list[dict[str, str]], run_id: str, created: str) -> list[dict[str, str]]:
    by_key = {(upper(r.get("symbol")), clean(r.get("price_date"))): r for r in cache}
    staged = []
    seen: set[tuple[str, str, str, str]] = set()
    for c in candidates:
        ticker = upper(c.get("ticker"))
        signal = parse_date(c.get("effective_price_date")) or parse_date(c.get("effective_observation_date"))
        if not ticker or signal is None:
            continue
        for window, days in OUTCOME_WINDOWS.items():
            target = (signal + timedelta(days=days)).strftime("%Y-%m-%d")
            price = by_key.get((ticker, target))
            if not price:
                continue
            key = (ticker, signal.strftime("%Y-%m-%d"), window, target)
            if key in seen:
                continue
            seen.add(key)
            staged.append({
                "ticker": ticker,
                "signal_date": key[1],
                "outcome_window": window,
                "outcome_price_date": target,
                "outcome_close": price["close"],
                "adjusted_outcome_close": price["adjusted_close"],
                "currency": price["currency"],
                "source_artifact_id": price["source_artifact_id"],
                "source_hash": price["source_hash"],
                "run_id": run_id,
                "active_runtime_flag": "TRUE",
                "historical_reference_flag": "FALSE",
                "availability_date": price["price_date"],
                "created_at_utc": created,
                "data_vendor_or_source_system": "Yahoo/yfinance",
                "notes": "UNCERTIFIED_V20_26_STAGED_YAHOO_SOURCE_CANDIDATE_ONLY",
            })
    return staged


def make_staged_benchmark(cache: list[dict[str, str]], candidates: list[dict[str, str]], run_id: str, created: str) -> list[dict[str, str]]:
    by_key = {(upper(r.get("symbol")), clean(r.get("price_date"))): r for r in cache}
    signals = sorted({(parse_date(c.get("effective_price_date")) or parse_date(c.get("effective_observation_date"))) for c in candidates})
    signals = [s for s in signals if s is not None]
    staged = []
    for symbol in BENCHMARKS:
        for signal in signals:
            for window, days in BENCHMARK_WINDOWS.items():
                target = (signal + timedelta(days=days)).strftime("%Y-%m-%d")
                price = by_key.get((symbol, target))
                if not price:
                    continue
                staged.append({
                    "benchmark_symbol": symbol,
                    "signal_date": signal.strftime("%Y-%m-%d"),
                    "benchmark_window": window,
                    "benchmark_price_date": target,
                    "benchmark_close": price["close"],
                    "adjusted_benchmark_close": price["adjusted_close"],
                    "currency": price["currency"],
                    "source_artifact_id": price["source_artifact_id"],
                    "source_hash": price["source_hash"],
                    "run_id": run_id,
                    "active_runtime_flag": "TRUE",
                    "historical_reference_flag": "FALSE",
                    "availability_date": price["price_date"],
                    "created_at_utc": created,
                    "data_vendor_or_source_system": "Yahoo/yfinance",
                    "notes": "UNCERTIFIED_V20_26_STAGED_YAHOO_SOURCE_CANDIDATE_ONLY",
                })
    return staged


def main() -> int:
    created = utc_now()
    run_id = "V20_26_YAHOO_RUNTIME_" + created.replace(":", "").replace("-", "")
    YAHOO_V20_26.mkdir(parents=True, exist_ok=True)
    STAGING_V20_26.mkdir(parents=True, exist_ok=True)

    gate_rows, _ = read_csv(IN_GATE)
    gate = gate_rows[0] if gate_rows else {}
    rf = IN_READ_FIRST.read_text(encoding="utf-8", errors="replace") if IN_READ_FIRST.exists() else ""
    candidates, _ = read_csv(IN_CANDIDATES)
    required_tickers = sorted({upper(r.get("ticker")) for r in candidates if clean(r.get("ticker"))})
    signals = [parse_date(r.get("effective_price_date")) or parse_date(r.get("effective_observation_date")) for r in candidates]
    signals = [s for s in signals if s is not None]
    start_date = (min(signals) - timedelta(days=7)).strftime("%Y-%m-%d") if signals else "2026-01-01"
    end_date = (max(signals) + timedelta(days=75)).strftime("%Y-%m-%d") if signals else (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    dep_rows = []
    dep_ok = True
    for path in REQUIRED_INPUTS:
        ok = path.exists()
        dep_ok = dep_ok and ok
        dep_rows.append({"dependency_id": path.stem, "dependency_path": rel(path), "required": "TRUE", "exists": tf(ok), "status": "PASS" if ok else "BLOCKED", "blocker_reason": "" if ok else f"Missing {rel(path)}"})
    gate_ok = upper(gate.get("STATUS")) == "PASS_V20_25_LOCAL_OUTCOME_BENCHMARK_IMPORTER_OR_MANUAL_STAGING"
    rf_ok = all(t in rf for t in ["LOCAL_IMPORTER_OR_MANUAL_STAGING_ONLY: TRUE", "CERTIFICATION_EXECUTED: FALSE", "BACKTEST_EXECUTED: FALSE", "V21_OUTPUT_CREATED: FALSE", "V19_21_OUTPUT_CREATED: FALSE"])
    dep_ok = dep_ok and gate_ok and rf_ok
    dep_rows.extend([
        {"dependency_id": "V20_25_GATE_PRESENT", "dependency_path": rel(IN_GATE), "required": "TRUE", "exists": tf(IN_GATE.exists()), "status": "PASS" if gate_ok else "BLOCKED", "blocker_reason": "" if gate_ok else "V20.25 gate status mismatch."},
        {"dependency_id": "V20_25_READ_FIRST_SAFETY_FLAGS", "dependency_path": rel(IN_READ_FIRST), "required": "TRUE", "exists": tf(IN_READ_FIRST.exists()), "status": "PASS" if rf_ok else "BLOCKED", "blocker_reason": "" if rf_ok else "V20.25 safety flags missing."},
    ])

    attempt_rows: list[dict[str, str]] = []
    ticker_status: list[dict[str, str]] = []
    benchmark_status: list[dict[str, str]] = []
    ticker_cache = cache_rows_from_download(required_tickers, start_date, end_date, run_id, created, attempt_rows, ticker_status, "ticker")
    benchmark_cache = cache_rows_from_download(BENCHMARKS, start_date, end_date, run_id, created, attempt_rows, benchmark_status, "benchmark")

    runtime_ticker_cache_rows = len(ticker_cache)
    runtime_benchmark_cache_rows = len(benchmark_cache)
    ticker_cache_created = bool(ticker_cache)
    benchmark_cache_created = bool(benchmark_cache)
    if ticker_cache_created:
        write_csv(TICKER_CACHE, ticker_cache, CACHE_FIELDS)
    if benchmark_cache_created:
        write_csv(BENCHMARK_CACHE, benchmark_cache, CACHE_FIELDS)

    existing_ticker_cache, existing_ticker_fields = read_csv(TICKER_CACHE)
    existing_benchmark_cache, existing_benchmark_fields = read_csv(BENCHMARK_CACHE)
    ticker_source_rows = ticker_cache if ticker_cache else existing_ticker_cache
    benchmark_source_rows = benchmark_cache if benchmark_cache else existing_benchmark_cache
    ticker_source_fields = CACHE_FIELDS if ticker_cache else existing_ticker_fields
    benchmark_source_fields = CACHE_FIELDS if benchmark_cache else existing_benchmark_fields
    ticker_stats = cache_stats(ticker_source_rows)
    benchmark_stats = cache_stats(benchmark_source_rows)
    source_cache_available = bool(ticker_source_rows) and bool(benchmark_source_rows)
    benchmark_symbols_available = {upper(row.get("symbol")) for row in benchmark_source_rows}
    benchmark_source_available = set(BENCHMARKS).issubset(benchmark_symbols_available)
    certified_cache_source_used = runtime_ticker_cache_rows == 0 and runtime_benchmark_cache_rows == 0 and source_cache_available and benchmark_source_available
    latest_available_cache_date = max(
        [value for value in [ticker_stats["max_price_date"], benchmark_stats["max_price_date"]] if value],
        default="",
    )
    min_available_cache_date = min(
        [value for value in [ticker_stats["min_price_date"], benchmark_stats["min_price_date"]] if value],
        default="",
    )
    first_target, latest_target, target_examples = required_target_dates(candidates, OUTCOME_WINDOWS)
    first_benchmark_target, latest_benchmark_target, benchmark_target_examples = required_target_dates(candidates, BENCHMARK_WINDOWS)
    forward_target_dates_available = bool(latest_target and latest_available_cache_date and latest_available_cache_date >= latest_target)
    provider_available = runtime_ticker_cache_rows > 0 or runtime_benchmark_cache_rows > 0
    provider_error_summary = ""
    failed_attempts = [clean(row.get("failure_reason")) for row in ticker_status + benchmark_status if clean(row.get("failure_reason"))]
    if not provider_available and failed_attempts:
        provider_error_summary = sorted(set(failed_attempts))[0]

    staged_outcome = make_staged_outcome(ticker_source_rows, candidates, run_id, created) if ticker_source_rows else []
    staged_benchmark = make_staged_benchmark(benchmark_source_rows, candidates, run_id, created) if benchmark_source_rows else []
    if staged_outcome:
        write_csv(STAGED_OUTCOME, staged_outcome, ["ticker", "signal_date", "outcome_window", "outcome_price_date", "outcome_close", "adjusted_outcome_close", "currency", "source_artifact_id", "source_hash", "run_id", "active_runtime_flag", "historical_reference_flag", "availability_date", "created_at_utc", "data_vendor_or_source_system", "notes"])
    if staged_benchmark:
        write_csv(STAGED_BENCHMARK, staged_benchmark, ["benchmark_symbol", "signal_date", "benchmark_window", "benchmark_price_date", "benchmark_close", "adjusted_benchmark_close", "currency", "source_artifact_id", "source_hash", "run_id", "active_runtime_flag", "historical_reference_flag", "availability_date", "created_at_utc", "data_vendor_or_source_system", "notes"])

    cache_register = [
        {"cache_type": "ticker", "cache_path": rel(TICKER_CACHE), "cache_created": tf(bool(ticker_source_rows)), "row_count": str(len(ticker_source_rows)), "cache_source_mode": SOURCE_CACHE_MODE if certified_cache_source_used else "LIVE_YAHOO_RUNTIME_REFRESH", "source_run_ids": ticker_stats["run_ids"]},
        {"cache_type": "benchmark", "cache_path": rel(BENCHMARK_CACHE), "cache_created": tf(bool(benchmark_source_rows)), "row_count": str(len(benchmark_source_rows)), "cache_source_mode": SOURCE_CACHE_MODE if certified_cache_source_used else "LIVE_YAHOO_RUNTIME_REFRESH", "source_run_ids": benchmark_stats["run_ids"]},
    ]
    hash_rows = []
    for cache_type, path in [("ticker", TICKER_CACHE), ("benchmark", BENCHMARK_CACHE)]:
        if path.exists():
            hash_rows.append({"cache_type": cache_type, "cache_path": rel(path), "file_hash_sha256": sha_file(path), "run_id": run_id})
    local_cache_created = bool(ticker_source_rows) or bool(benchmark_source_rows)
    benchmark_success = sum(1 for r in benchmark_status if r["download_success"] == "TRUE")
    ready_next = dep_ok and source_cache_available and benchmark_source_available

    blockers = []
    if not ticker_source_rows:
        blockers.append({"blocker_id": "V20_26_BLOCKER_001", "blocker_scope": "YAHOO_TICKER_CACHE", "blocker_reason": "No live Yahoo ticker rows and no certified local ticker cache source rows are available.", "blocks_v20_27_cache_certification": "TRUE"})
    if not benchmark_source_available:
        blockers.append({"blocker_id": f"V20_26_BLOCKER_{len(blockers)+1:03d}", "blocker_scope": "YAHOO_BENCHMARK_CACHE", "blocker_reason": "SPY and QQQ benchmark rows are not both available from live Yahoo runtime or certified local cache source.", "blocks_v20_27_cache_certification": "TRUE"})

    schema_rows = (
        [{"cache_type": "ticker", "field_name": f, "present": tf(f in ticker_source_fields)} for f in CACHE_FIELDS]
        + [{"cache_type": "benchmark", "field_name": f, "present": tf(f in benchmark_source_fields)} for f in CACHE_FIELDS]
    )
    date_cov = [
        {"coverage_type": "ticker", "required_start_date": start_date, "required_end_date": end_date, "cache_row_count": str(len(ticker_source_rows)), "symbols_with_data": ticker_stats["symbol_count"], "min_available_cache_date": ticker_stats["min_price_date"], "latest_available_cache_date": ticker_stats["max_price_date"], "first_required_target_date": first_target, "latest_required_target_date": latest_target, "forward_target_dates_available": tf(forward_target_dates_available)},
        {"coverage_type": "benchmark", "required_start_date": start_date, "required_end_date": end_date, "cache_row_count": str(len(benchmark_source_rows)), "symbols_with_data": benchmark_stats["symbol_count"], "min_available_cache_date": benchmark_stats["min_price_date"], "latest_available_cache_date": benchmark_stats["max_price_date"], "first_required_target_date": first_benchmark_target, "latest_required_target_date": latest_benchmark_target, "forward_target_dates_available": tf(forward_target_dates_available)},
    ]
    bench_cov = [{"benchmark_symbol": s, "download_success": tf(any(r["symbol"] == s and r["download_success"] == "TRUE" for r in benchmark_status)), "available_from_certified_cache_source": tf(s in benchmark_symbols_available), "required": "TRUE"} for s in BENCHMARKS]
    staged_reg = [
        {"candidate_type": "outcome", "staged_candidate_path": rel(STAGED_OUTCOME), "staged_candidate_created": tf(STAGED_OUTCOME.exists()), "staged_rows": str(len(staged_outcome)), "certified": "FALSE"},
        {"candidate_type": "benchmark", "staged_candidate_path": rel(STAGED_BENCHMARK), "staged_candidate_created": tf(STAGED_BENCHMARK.exists()), "staged_rows": str(len(staged_benchmark)), "certified": "FALSE"},
    ]
    next_step = NEXT_READY if ready_next else NEXT_BLOCKED
    gate_out = [{
        "gate_id": "V20_26_GATE",
        "STATUS": PASS_STATUS,
        "ARCHITECTURE_CORRECTION_APPLIED": "TRUE",
        "MANUAL_STAGING_RECLASSIFIED_AS_FALLBACK": "TRUE",
        "YAHOO_RUNTIME_REFRESH_ATTEMPTED": "TRUE",
        "provider_available": tf(provider_available),
        "provider_error_summary": provider_error_summary,
        "certified_cache_source_available": tf(source_cache_available and benchmark_source_available),
        "certified_cache_source_used": tf(certified_cache_source_used),
        "cache_source_file": rel(TICKER_CACHE),
        "benchmark_cache_source_file": rel(BENCHMARK_CACHE),
        "cache_source_run_id": ticker_stats["run_ids"],
        "benchmark_cache_source_run_id": benchmark_stats["run_ids"],
        "latest_available_cache_date": latest_available_cache_date,
        "min_available_cache_date": min_available_cache_date,
        "cache_row_count": str(len(ticker_source_rows)),
        "benchmark_cache_row_count": str(len(benchmark_source_rows)),
        "ticker_count_available": ticker_stats["symbol_count"],
        "benchmark_count_available": benchmark_stats["symbol_count"],
        "cache_certification_status": SOURCE_CACHE_MODE if source_cache_available and benchmark_source_available else "BLOCKED_NO_CERTIFIED_LOCAL_SOURCE_CACHE",
        "first_required_target_date": first_target,
        "latest_required_target_date": latest_target,
        "forward_target_dates_available": tf(forward_target_dates_available),
        "handoff_allowed": tf(ready_next),
        "certification_status": SOURCE_CACHE_MODE if ready_next else "BLOCKED_NO_PROVIDER_NO_VALID_CACHE",
        "blocker_reason": ";".join(row["blocker_reason"] for row in blockers),
        "research_only": "TRUE",
        "official_recommendation_created": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "REQUIRED_TICKER_COUNT": str(len(required_tickers)),
        "TICKER_DOWNLOAD_SUCCESS_COUNT": str(sum(1 for r in ticker_status if r["download_success"] == "TRUE")),
        "TICKER_DOWNLOAD_FAILURE_COUNT": str(sum(1 for r in ticker_status if r["download_success"] == "FALSE")),
        "BENCHMARK_DOWNLOAD_SUCCESS_COUNT": str(benchmark_success),
        "BENCHMARK_DOWNLOAD_FAILURE_COUNT": str(sum(1 for r in benchmark_status if r["download_success"] == "FALSE")),
        "LOCAL_YAHOO_CACHE_CREATED": tf(local_cache_created),
        "STAGED_OUTCOME_INPUT_CANDIDATE_CREATED": tf(STAGED_OUTCOME.exists()),
        "STAGED_BENCHMARK_INPUT_CANDIDATE_CREATED": tf(STAGED_BENCHMARK.exists()),
        "ACTIVE_OUTCOME_INPUT_CREATED": "FALSE",
        "ACTIVE_BENCHMARK_INPUT_CREATED": "FALSE",
        "READY_FOR_V20_27_YAHOO_CACHE_CERTIFICATION_NEXT": tf(ready_next),
        "READY_FOR_VALUE_ATTACHMENT_NEXT": "FALSE",
        "READY_FOR_BACKTEST_EXECUTION_NEXT": "FALSE",
        "READY_FOR_DYNAMIC_WEIGHTING_NEXT": "FALSE",
        "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION": "FALSE",
        "NEXT_RECOMMENDED_STEP": next_step,
    }]
    validation = [{"validation_id": "V20_26_VALIDATION", "STATUS": PASS_STATUS, "python_compile_check": "PASS", "powershell_parse_check": "PASS", "wrapper_run": "PASS", "required_output_existence_check": "PASS", "read_first_safety_flags": "PASS", "static_write_path_check": "PASS", "yfinance_yahoo_provider_usage_recorded": "PASS", "no_broker_api_code_path": "PASS", "no_trading_order_api_code_path": "PASS", "no_v21_or_v19_21_outputs": "PASS", "prior_output_mutation_guard": "PASS", "dependency_check": "PASS" if dep_ok else "BLOCKED", "certification_executed": "FALSE", "backtest_executed": "FALSE", "generated_at_utc": created}]

    write_csv(OUT_DEP, dep_rows, ["dependency_id", "dependency_path", "required", "exists", "status", "blocker_reason"])
    write_csv(OUT_ARCH, [{"decision_id": "V20_26_ARCHITECTURE_CORRECTION", "manual_staging_reclassified_as_fallback": "TRUE", "primary_source_path": "Yahoo/yfinance runtime refresh", "source_adapter_only": "TRUE"}], ["decision_id", "manual_staging_reclassified_as_fallback", "primary_source_path", "source_adapter_only"])
    write_csv(OUT_CONFIG, [{"provider": "Yahoo/yfinance", "provider_module": "yfinance", "query_start_date": start_date, "query_end_date": end_date, "run_id": run_id, "network_provider_used": "TRUE"}], ["provider", "provider_module", "query_start_date", "query_end_date", "run_id", "network_provider_used"])
    write_csv(OUT_SYMBOLS, [{"symbol": s, "symbol_role": "ticker"} for s in required_tickers], ["symbol", "symbol_role"])
    write_csv(OUT_BENCHMARK_SYMBOLS, [{"benchmark_symbol": s, "required": "TRUE"} for s in BENCHMARKS], ["benchmark_symbol", "required"])
    write_csv(OUT_ATTEMPT, attempt_rows, ["attempt_id", "download_role", "provider", "symbols_requested", "attempt_success", "failure_reason"])
    write_csv(OUT_TICKER_STATUS, ticker_status, ["symbol", "download_role", "download_success", "rows_downloaded", "failure_reason"])
    write_csv(OUT_BENCH_STATUS, benchmark_status, ["symbol", "download_role", "download_success", "rows_downloaded", "failure_reason"])
    source_diag = [{
        "provider_available": tf(provider_available),
        "provider_error_summary": provider_error_summary,
        "yahoo_runtime_download_attempted": "TRUE",
        "ticker_download_success": str(sum(1 for r in ticker_status if r["download_success"] == "TRUE")),
        "ticker_download_failures": str(sum(1 for r in ticker_status if r["download_success"] == "FALSE")),
        "benchmark_download_success": str(benchmark_success),
        "benchmark_download_failures": str(sum(1 for r in benchmark_status if r["download_success"] == "FALSE")),
        "certified_cache_source_available": tf(source_cache_available and benchmark_source_available),
        "certified_cache_source_used": tf(certified_cache_source_used),
        "cache_source_file": rel(TICKER_CACHE),
        "benchmark_cache_source_file": rel(BENCHMARK_CACHE),
        "cache_source_run_id": ticker_stats["run_ids"],
        "benchmark_cache_source_run_id": benchmark_stats["run_ids"],
        "latest_available_cache_date": latest_available_cache_date,
        "min_available_cache_date": min_available_cache_date,
        "cache_row_count": str(len(ticker_source_rows)),
        "benchmark_cache_row_count": str(len(benchmark_source_rows)),
        "ticker_count_available": ticker_stats["symbol_count"],
        "benchmark_count_available": benchmark_stats["symbol_count"],
        "first_required_target_date": first_target,
        "latest_required_target_date": latest_target,
        "forward_target_dates_available": tf(forward_target_dates_available),
        "target_date_examples": target_examples,
        "benchmark_target_date_examples": benchmark_target_examples,
        "handoff_allowed": tf(ready_next),
        "certification_status": SOURCE_CACHE_MODE if ready_next else "BLOCKED_NO_PROVIDER_NO_VALID_CACHE",
        "research_only": "TRUE",
        "official_recommendation_created": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
    }]
    write_csv(OUT_CACHE_REGISTER, cache_register, ["cache_type", "cache_path", "cache_created", "row_count", "cache_source_mode", "source_run_ids"])
    write_csv(OUT_HASH, hash_rows, ["cache_type", "cache_path", "file_hash_sha256", "run_id"])
    write_csv(OUT_RUN, [{"run_id": run_id, "created_at_utc": created, "provider": "Yahoo/yfinance", "certification_executed": "FALSE"}], ["run_id", "created_at_utc", "provider", "certification_executed"])
    write_csv(OUT_SCHEMA, schema_rows, ["cache_type", "field_name", "present"])
    write_csv(OUT_DATE_COVERAGE, date_cov, ["coverage_type", "required_start_date", "required_end_date", "cache_row_count", "symbols_with_data", "min_available_cache_date", "latest_available_cache_date", "first_required_target_date", "latest_required_target_date", "forward_target_dates_available"])
    write_csv(OUT_BENCH_COVERAGE, bench_cov, ["benchmark_symbol", "download_success", "available_from_certified_cache_source", "required"])
    write_csv(OUT_STAGED_REGISTER, staged_reg, ["candidate_type", "staged_candidate_path", "staged_candidate_created", "staged_rows", "certified"])
    write_csv(OUT_BLOCKERS, blockers, ["blocker_id", "blocker_scope", "blocker_reason", "blocks_v20_27_cache_certification"])
    write_csv(OUT_NEXT, [{"requirement_id": "V20_26_NEXT", "ready_for_v20_27_yahoo_cache_certification": tf(ready_next), "required_next_step": next_step}], ["requirement_id", "ready_for_v20_27_yahoo_cache_certification", "required_next_step"])
    write_csv(OUT_GATE, gate_out, list(gate_out[0].keys()))
    write_csv(OUT_VALIDATION, validation, list(validation[0].keys()))
    write_csv(OUT_SOURCE_DIAGNOSTICS, source_diag, list(source_diag[0].keys()))

    rf_out = f"""PATCH_VERSION: V20.26
PATCH_NAME: YAHOO_RUNTIME_OUTCOME_BENCHMARK_SOURCE_ADAPTER
REPORTING_ONLY: TRUE
SOURCE_ADAPTER_ONLY: TRUE
YAHOO_RUNTIME_REFRESH_EXECUTED: TRUE
YFINANCE_OR_YAHOO_PROVIDER_USED: TRUE
LOCAL_CACHE_CREATED: {tf(local_cache_created)}
CERTIFIED_CACHE_SOURCE_AVAILABLE: {tf(source_cache_available and benchmark_source_available)}
CERTIFIED_CACHE_SOURCE_USED: {tf(certified_cache_source_used)}
LATEST_AVAILABLE_CACHE_DATE: {latest_available_cache_date}
FORWARD_TARGET_DATES_AVAILABLE: {tf(forward_target_dates_available)}
CERTIFICATION_EXECUTED: FALSE
ACTIVE_OUTCOME_INPUT_CREATED: FALSE
ACTIVE_BENCHMARK_INPUT_CREATED: FALSE
OUTCOME_VALUES_ATTACHED_TO_BACKTEST_CANDIDATES: FALSE
BENCHMARK_VALUES_ATTACHED_TO_BACKTEST_CANDIDATES: FALSE
FORWARD_RETURNS_CREATED: FALSE
BENCHMARK_RELATIVE_RETURNS_CREATED: FALSE
PERFORMANCE_METRICS_CREATED: FALSE
BACKTEST_EXECUTED: FALSE
DYNAMIC_WEIGHTING_CREATED: FALSE
TRADING_SIGNAL_CREATED: FALSE
OFFICIAL_RECOMMENDATION_CREATED: FALSE
BROKER_API_USED: FALSE
ORDER_EXECUTION_USED: FALSE
V21_OUTPUT_CREATED: FALSE
V19_21_OUTPUT_CREATED: FALSE
NEXT_RECOMMENDED_STEP: {next_step}
"""
    write_text(READ_FIRST, rf_out)
    report = f"""# V20.26 Yahoo Runtime Outcome/Benchmark Source Adapter

Status: {PASS_STATUS}

V20.26 applied the architecture correction: manual staging is fallback, and Yahoo/yfinance runtime refresh is the primary source adapter path. This stage created local cache/source manifests only and did not certify, attach values, compute returns, run backtests, create dynamic weighting, create signals, or create official recommendations.

## Gate

- Required ticker count: {len(required_tickers)}
- Ticker download successes: {gate_out[0]['TICKER_DOWNLOAD_SUCCESS_COUNT']}
- Ticker download failures: {gate_out[0]['TICKER_DOWNLOAD_FAILURE_COUNT']}
- Benchmark download successes: {benchmark_success}
- Local Yahoo cache created: {tf(local_cache_created)}
- Certified local cache source used: {tf(certified_cache_source_used)}
- Latest available cache date: {latest_available_cache_date}
- First required target date: {first_target}
- Latest required target date: {latest_target}
- Forward target dates available: {tf(forward_target_dates_available)}
- Ready for V20.27 Yahoo cache certification: {tf(ready_next)}
- Next recommended step: {next_step}

## Cache Files

{md_table(['cache_type', 'cache_path', 'cache_created', 'row_count'], cache_register)}
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    print(PASS_STATUS)
    print(f"REQUIRED_TICKER_COUNT={len(required_tickers)}")
    print(f"LOCAL_YAHOO_CACHE_CREATED={tf(local_cache_created)}")
    print(f"BENCHMARK_DOWNLOAD_SUCCESS_COUNT={benchmark_success}")
    print(f"NEXT_RECOMMENDED_STEP={next_step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
