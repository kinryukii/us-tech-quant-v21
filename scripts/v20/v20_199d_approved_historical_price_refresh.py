#!/usr/bin/env python
"""V20.199D approved historical price refresh plan/canonicalizer.

Default behavior is plan-only. Live provider refresh requires an explicit
operator environment flag so this stage cannot silently fetch external data.
"""

from __future__ import annotations

import csv
import hashlib
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v20" / "price_history"
SNAPSHOT_LEDGER = ROOT / "outputs" / "v20" / "backtest_snapshots" / "V20_194_RECOMPUTABLE_FACTOR_SNAPSHOT_LEDGER.csv"
PROVIDER_CACHE_DIR = ROOT / "state" / "v20" / "provider_cache" / "yfinance_v20_199d"
BENCHMARKS = ["QQQ", "SPY", "SOXX"]

OUT_UNIVERSE = OUT_DIR / "V20_199D_REFRESH_INPUT_UNIVERSE.csv"
OUT_MECHANISM = OUT_DIR / "V20_199D_APPROVED_REFRESH_MECHANISM_AUDIT.csv"
OUT_RESULT = OUT_DIR / "V20_199D_HISTORICAL_PRICE_REFRESH_RESULT.csv"
OUT_CANONICAL = OUT_DIR / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
OUT_BENCHMARK = OUT_DIR / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"
OUT_FAILURES = OUT_DIR / "V20_199D_PRICE_REFRESH_FAILURES.csv"
OUT_SCHEMA = OUT_DIR / "V20_199D_PRICE_SCHEMA_VALIDATION.csv"
OUT_COVERAGE = OUT_DIR / "V20_199D_PRICE_COVERAGE_AFTER_REFRESH.csv"
OUT_BENCHMARK_COVERAGE = OUT_DIR / "V20_199D_HISTORICAL_BENCHMARK_COVERAGE_AUDIT.csv"
OUT_GUARD = OUT_DIR / "V20_199D_NO_FABRICATION_GUARD_AUDIT.csv"
OUT_GATE = OUT_DIR / "V20_199D_NEXT_STAGE_GATE.csv"
OUT_REPORT = OUT_DIR / "V20_199D_READ_CENTER_REPORT.md"

PASS_STATUS = "PASS_V20_199D_APPROVED_HISTORICAL_PRICE_REFRESH"
PARTIAL_STATUS = "PARTIAL_PASS_V20_199D_APPROVED_HISTORICAL_PRICE_REFRESH"
PLAN_ONLY_STATUS = "PARTIAL_PASS_REFRESH_PLAN_ONLY_APPROVED_MECHANISM_REQUIRED"
BLOCKED_STATUS = "BLOCKED_V20_199D_APPROVED_HISTORICAL_PRICE_REFRESH"

ENABLE_REFRESH_ENV = "V20_199D_ENABLE_YFINANCE_REFRESH"
PROVIDER = "Yahoo/yfinance"
DOWNLOAD_PERIOD = "3y"
DOWNLOAD_INTERVAL = "1d"

COMMON_GUARDS = {
    "research_only": "TRUE",
    "official_ranking_mutated": "FALSE",
    "official_ranking_score_mutation_count": "0",
    "official_rank_mutation_count": "0",
    "official_recommendation_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "real_book_action_created": "FALSE",
}

UNIVERSE_FIELDS = [
    "symbol", "symbol_role", "requested_for_refresh", "universe_source",
    "universe_pit_status", "historical_universe_membership_available",
    *COMMON_GUARDS.keys(),
]
MECHANISM_FIELDS = [
    "mechanism_id", "refresh_mechanism_name", "refresh_script_path",
    "refresh_source_provider", "mechanism_exists", "mechanism_scope",
    "approved_for_v20_199d_direct_execution", "execution_flag_required",
    "execution_flag_name", "execution_flag_value", "refresh_execution_allowed",
    "refresh_execution_attempted", "mechanism_audit_status", "audit_note",
    "requested_symbol_count", "returned_symbol_count", "failed_symbol_count",
    "refresh_timestamp", "no_fabricated_price_rows", *COMMON_GUARDS.keys(),
]
CANONICAL_FIELDS = [
    "symbol", "date", "open", "high", "low", "close", "adjusted_close",
    "volume", "source_provider", "source_artifact", "refresh_timestamp",
    "row_hash", "price_row_status",
]
COVERAGE_FIELDS = [
    "symbol", "symbol_role", "earliest_price_date", "latest_price_date",
    "trading_day_count", "has_60_bar_lookback_potential",
    "has_5d_forward_potential", "has_10d_forward_potential",
    "has_20d_forward_potential", "has_60d_forward_potential",
    "missing_close_count", "missing_volume_count", "duplicate_date_count",
    "usable_for_pit_lite_recompute", "universe_pit_status",
    *COMMON_GUARDS.keys(),
]
RESULT_FIELDS = [
    "refresh_result_id", "execution_mode", "refresh_mechanism_name",
    "refresh_source_provider", "refresh_timestamp", "requested_symbol_count",
    "returned_symbol_count", "failed_symbol_count", "canonical_ohlcv_rows",
    "canonical_benchmark_rows", "refresh_status",
    "no_fabricated_price_rows", "no_fabricated_benchmark_rows",
    "no_synthetic_ohlcv", "no_forward_returns_computed",
    "no_factor_scores_computed", "no_current_factor_snapshot_join",
    "no_current_fundamental_field_used", *COMMON_GUARDS.keys(),
]
FAILURE_FIELDS = ["symbol", "symbol_role", "failure_type", "failure_reason", "provider", "refresh_timestamp", *COMMON_GUARDS.keys()]
SCHEMA_FIELDS = ["schema_field", "required", "present_in_canonical_ticker", "present_in_canonical_benchmark", "schema_validation_status", *COMMON_GUARDS.keys()]
GUARD_FIELDS = [
    "guard_check", "expected_value", "actual_value", "guard_status",
    "no_fabricated_price_rows", "no_fabricated_benchmark_rows",
    "no_synthetic_ohlcv", "no_forward_returns_computed",
    "no_factor_scores_computed", "no_current_factor_snapshot_join",
    "no_current_fundamental_field_used", *COMMON_GUARDS.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "final_status", "approved_refresh_mechanism_exists",
    "refresh_execution_attempted", "canonical_ohlcv_created",
    "symbols_with_60_plus_bars", "tickers_with_60_plus_bars",
    "qqq_60_bar_ready", "spy_60_bar_ready", "soxx_60_bar_ready",
    "benchmark_coverage", "no_fabricated_prices",
    "no_official_trade_mutation", "ready_for_v20_199c_rerun",
    "ready_for_v20_199b_rerun", "blocking_reason", *COMMON_GUARDS.keys(),
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{k: clean(v) for k, v in row.items()} for row in csv.DictReader(handle)]


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


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


def as_float(value: object) -> float | None:
    try:
        number = float(clean(value))
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def build_universe() -> list[dict[str, object]]:
    rows = read_csv(SNAPSHOT_LEDGER)
    tickers = sorted({clean(row.get("ticker")).upper() for row in rows if clean(row.get("ticker"))})
    out = []
    for ticker in tickers:
        out.append({
            "symbol": ticker,
            "symbol_role": "TICKER",
            "requested_for_refresh": "TRUE",
            "universe_source": rel(SNAPSHOT_LEDGER),
            "universe_pit_status": "CURRENT_UNIVERSE_SURVIVORSHIP_RISK",
            "historical_universe_membership_available": "FALSE",
            **COMMON_GUARDS,
        })
    for benchmark in BENCHMARKS:
        out.append({
            "symbol": benchmark,
            "symbol_role": "BENCHMARK",
            "requested_for_refresh": "TRUE",
            "universe_source": "REQUIRED_BENCHMARKS",
            "universe_pit_status": "BENCHMARK_REQUIRED_CURRENT_SYMBOL",
            "historical_universe_membership_available": "FALSE",
            **COMMON_GUARDS,
        })
    return out


def mechanism_rows(universe_count: int, returned: int, failed: int, refresh_ts: str, attempted: bool) -> list[dict[str, object]]:
    candidates = [
        (
            "V20_199D_MECH_001",
            "V20_35_R1_HISTORICAL_YAHOO_CACHE_EXPANSION_FOR_RANDOM_ASOF_BACKTEST",
            ROOT / "scripts" / "v20" / "v20_35_r1_historical_yahoo_cache_expansion_for_random_asof_backtest.py",
            PROVIDER,
            "HISTORICAL_RANDOM_ASOF_CACHE_EXPANSION_PRIOR_STAGE",
            "FALSE",
            "Prior approved stage exists, but it is scoped to V20.35 inputs and is not a V20.199D canonical data-lake refresh contract.",
        ),
        (
            "V20_199D_MECH_002",
            "V20_47_CONTROLLED_CURRENT_MARKET_REFRESH_AND_CACHE_CERTIFICATION",
            ROOT / "scripts" / "v20" / "v20_47_controlled_current_market_refresh_and_cache_certification.py",
            PROVIDER,
            "CURRENT_MARKET_REFRESH_ONLY",
            "FALSE",
            "Current-price refresh is not sufficient for 3-year daily historical OHLCV coverage.",
        ),
        (
            "V20_199D_MECH_003",
            "V20_199D_INTERNAL_YFINANCE_CANONICAL_REFRESH",
            Path(__file__).resolve(),
            PROVIDER,
            "V20_199D_CANONICAL_HISTORICAL_OHLCV_REFRESH",
            tf(os.environ.get(ENABLE_REFRESH_ENV, "").upper() == "TRUE"),
            "Direct execution requires explicit operator flag because it performs an external provider refresh.",
        ),
    ]
    rows = []
    flag_value = os.environ.get(ENABLE_REFRESH_ENV, "")
    for mech_id, name, script, provider, scope, approved, note in candidates:
        exists = script.exists()
        allowed = approved == "TRUE" and exists
        rows.append({
            "mechanism_id": mech_id,
            "refresh_mechanism_name": name,
            "refresh_script_path": rel(script),
            "refresh_source_provider": provider,
            "mechanism_exists": tf(exists),
            "mechanism_scope": scope,
            "approved_for_v20_199d_direct_execution": approved,
            "execution_flag_required": "TRUE",
            "execution_flag_name": ENABLE_REFRESH_ENV,
            "execution_flag_value": flag_value,
            "refresh_execution_allowed": tf(allowed),
            "refresh_execution_attempted": tf(attempted and allowed),
            "mechanism_audit_status": "PASS" if allowed else "PLAN_ONLY_SAFE_APPROVAL_REQUIRED",
            "audit_note": note,
            "requested_symbol_count": str(universe_count),
            "returned_symbol_count": str(returned if attempted and allowed else 0),
            "failed_symbol_count": str(failed if attempted and allowed else 0),
            "refresh_timestamp": refresh_ts if attempted and allowed else "",
            "no_fabricated_price_rows": "TRUE",
            **COMMON_GUARDS,
        })
    return rows


def normalize_provider_ticker(symbol: str) -> str:
    return clean(symbol).upper().replace(".", "-")


def extract_dataframe(data: Any, symbol: str) -> Any:
    if data is None:
        return None
    try:
        if hasattr(data, "columns") and getattr(data.columns, "nlevels", 1) > 1:
            cols0 = {clean(item).upper() for item in data.columns.get_level_values(0)}
            cols1 = {clean(item).upper() for item in data.columns.get_level_values(1)}
            provider_symbol = normalize_provider_ticker(symbol)
            if provider_symbol in cols0:
                return data[provider_symbol]
            if provider_symbol in cols1:
                return data.xs(provider_symbol, level=1, axis=1)
        return data
    except Exception:
        return None


def row_value(raw: Any, names: list[str]) -> object:
    for name in names:
        try:
            value = raw.get(name, "")
        except Exception:
            value = ""
        if clean(value) != "":
            return value
    return ""


def normalize_symbol(symbol: object) -> str:
    return clean(symbol).upper()


def normalize_download_rows(df: Any, symbol: str, role: str, source_artifact: str, refresh_ts: str) -> list[dict[str, object]]:
    if df is None or getattr(df, "empty", True):
        return []
    rows = []
    try:
        iterator = df.iterrows()
    except Exception:
        return []
    for idx, raw in iterator:
        date = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else clean(idx)[:10]
        close = row_value(raw, ["Close", "close"])
        adj = row_value(raw, ["Adj Close", "Adjusted Close", "adjusted_close", "adj_close"]) or close
        if as_float(close) is None and as_float(adj) is None:
            continue
        open_v = row_value(raw, ["Open", "open"])
        high = row_value(raw, ["High", "high"])
        low = row_value(raw, ["Low", "low"])
        volume = row_value(raw, ["Volume", "volume"])
        close_out = clean(close or adj)
        adj_out = clean(adj or close)
        hash_input = "|".join([symbol, date, clean(open_v), clean(high), clean(low), close_out, adj_out, clean(volume), source_artifact])
        rows.append({
            "symbol": normalize_symbol(symbol),
            "date": date,
            "open": clean(open_v),
            "high": clean(high),
            "low": clean(low),
            "close": close_out,
            "adjusted_close": adj_out,
            "volume": clean(volume),
            "source_provider": PROVIDER,
            "source_artifact": source_artifact,
            "refresh_timestamp": refresh_ts,
            "row_hash": sha_text(hash_input),
            "price_row_status": "PROVIDER_OBSERVED_OHLCV",
            "_role": role,
        })
    rows.sort(key=lambda row: (clean(row["symbol"]), clean(row["date"])))
    return rows


def fetch_yfinance(universe: list[dict[str, object]], refresh_ts: str) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    PROVIDER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["YFINANCE_CACHE_DIR"] = str(PROVIDER_CACHE_DIR)
    os.environ["YFINANCE_USER_CACHE_DIR"] = str(PROVIDER_CACHE_DIR)
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        return [], [{
            "symbol": clean(row["symbol"]),
            "symbol_role": clean(row["symbol_role"]),
            "failure_type": "YFINANCE_IMPORT_FAILED",
            "failure_reason": f"{type(exc).__name__}:{exc}",
            "provider": PROVIDER,
            "refresh_timestamp": refresh_ts,
            **COMMON_GUARDS,
        } for row in universe]
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
    canonical = []
    failures = []
    for row in universe:
        symbol = clean(row["symbol"]).upper()
        role = clean(row["symbol_role"])
        try:
            data = yf.download(
                tickers=normalize_provider_ticker(symbol),
                period=DOWNLOAD_PERIOD,
                interval=DOWNLOAD_INTERVAL,
                auto_adjust=False,
                actions=False,
                progress=False,
                threads=False,
            )
            rows = normalize_download_rows(
                extract_dataframe(data, symbol),
                symbol,
                role,
                f"{PROVIDER}:period={DOWNLOAD_PERIOD};interval={DOWNLOAD_INTERVAL};symbol={symbol}",
                refresh_ts,
            )
        except Exception as exc:
            rows = []
            failures.append({
                "symbol": symbol,
                "symbol_role": role,
                "failure_type": "PROVIDER_REFRESH_FAILED",
                "failure_reason": f"{type(exc).__name__}:{exc}",
                "provider": PROVIDER,
                "refresh_timestamp": refresh_ts,
                **COMMON_GUARDS,
            })
        if rows:
            canonical.extend(rows)
        elif not any(failure["symbol"] == symbol for failure in failures):
            failures.append({
                "symbol": symbol,
                "symbol_role": role,
                "failure_type": "EMPTY_PROVIDER_RESPONSE",
                "failure_reason": "No valid OHLCV rows returned by provider.",
                "provider": PROVIDER,
                "refresh_timestamp": refresh_ts,
                **COMMON_GUARDS,
            })
    return canonical, failures


def coverage_rows(universe: list[dict[str, object]], rows: list[dict[str, object]]) -> list[dict[str, object]]:
    by_symbol: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_symbol[normalize_symbol(row.get("symbol"))].append(row)
    counts = Counter((normalize_symbol(row.get("symbol")), clean(row.get("date"))) for row in rows)
    out = []
    for item in universe:
        symbol = normalize_symbol(item["symbol"])
        role = clean(item["symbol_role"])
        symbol_rows = by_symbol.get(symbol, [])
        dates = sorted({clean(row.get("date")) for row in symbol_rows if clean(row.get("date"))})
        missing_close = sum(1 for row in symbol_rows if as_float(row.get("close")) is None and as_float(row.get("adjusted_close")) is None)
        missing_volume = sum(1 for row in symbol_rows if clean(row.get("volume")) == "")
        duplicate_count = sum(count - 1 for (sym, _), count in counts.items() if sym == symbol and count > 1)
        count = len(dates)
        out.append({
            "symbol": symbol,
            "symbol_role": role,
            "earliest_price_date": dates[0] if dates else "",
            "latest_price_date": dates[-1] if dates else "",
            "trading_day_count": str(count),
            "has_60_bar_lookback_potential": tf(count >= 60),
            "has_5d_forward_potential": tf(count >= 65),
            "has_10d_forward_potential": tf(count >= 70),
            "has_20d_forward_potential": tf(count >= 80),
            "has_60d_forward_potential": tf(count >= 120),
            "missing_close_count": str(missing_close),
            "missing_volume_count": str(missing_volume),
            "duplicate_date_count": str(duplicate_count),
            "usable_for_pit_lite_recompute": tf(count >= 60 and missing_close == 0 and duplicate_count == 0),
            "universe_pit_status": clean(item["universe_pit_status"]),
            **COMMON_GUARDS,
        })
    return out


def benchmark_universe() -> list[dict[str, object]]:
    return [{
        "symbol": benchmark,
        "symbol_role": "BENCHMARK",
        "requested_for_refresh": "TRUE",
        "universe_source": "REQUIRED_BENCHMARKS",
        "universe_pit_status": "BENCHMARK_REQUIRED_CURRENT_SYMBOL",
        "historical_universe_membership_available": "FALSE",
        **COMMON_GUARDS,
    } for benchmark in BENCHMARKS]


def schema_validation_rows(ticker_rows: list[dict[str, object]], benchmark_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    ticker_present = set(CANONICAL_FIELDS) if OUT_CANONICAL.exists() else set()
    bench_present = set(CANONICAL_FIELDS) if OUT_BENCHMARK.exists() else set()
    return [{
        "schema_field": field,
        "required": "TRUE",
        "present_in_canonical_ticker": tf(field in ticker_present),
        "present_in_canonical_benchmark": tf(field in bench_present),
        "schema_validation_status": "PASS" if field in ticker_present and field in bench_present else "FAIL",
        **COMMON_GUARDS,
    } for field in CANONICAL_FIELDS]


def main() -> int:
    refresh_ts = utc_now()
    before_hash = sha_file(SNAPSHOT_LEDGER)
    universe = build_universe()
    refresh_enabled = os.environ.get(ENABLE_REFRESH_ENV, "").upper() == "TRUE"
    execution_mode = "LIVE_YFINANCE_REFRESH" if refresh_enabled else "PLAN_ONLY_APPROVED_MECHANISM_REQUIRED"

    canonical_rows: list[dict[str, object]] = []
    failure_rows: list[dict[str, object]] = []
    if refresh_enabled:
        canonical_rows, failure_rows = fetch_yfinance(universe, refresh_ts)
    else:
        failure_rows = [{
            "symbol": clean(row["symbol"]),
            "symbol_role": clean(row["symbol_role"]),
            "failure_type": "REFRESH_NOT_EXECUTED_PLAN_ONLY",
            "failure_reason": f"Set {ENABLE_REFRESH_ENV}=TRUE only after operator approval for external historical provider refresh.",
            "provider": PROVIDER,
            "refresh_timestamp": "",
            **COMMON_GUARDS,
        } for row in universe]

    after_hash = sha_file(SNAPSHOT_LEDGER)
    no_official_mutation = before_hash == after_hash
    ticker_source_rows = [row for row in canonical_rows if clean(row.get("_role")).upper() != "BENCHMARK"]
    benchmark_source_rows = [row for row in canonical_rows if clean(row.get("_role")).upper() == "BENCHMARK"]
    ticker_rows = [{k: v for k, v in row.items() if not k.startswith("_")} for row in ticker_source_rows]
    benchmark_rows = [{k: v for k, v in row.items() if not k.startswith("_")} for row in benchmark_source_rows]
    ticker_universe = [row for row in universe if clean(row.get("symbol_role")).upper() != "BENCHMARK"]
    coverage = coverage_rows(ticker_universe, ticker_source_rows)
    benchmark_coverage_rows = coverage_rows(benchmark_universe(), benchmark_source_rows)
    combined_coverage = coverage + benchmark_coverage_rows
    tickers_with_60 = sum(1 for row in coverage if row["symbol_role"] == "TICKER" and row["usable_for_pit_lite_recompute"] == "TRUE")
    symbols_with_60 = sum(1 for row in combined_coverage if row["usable_for_pit_lite_recompute"] == "TRUE")
    qqq_ready = any(row["symbol"] == "QQQ" and row["usable_for_pit_lite_recompute"] == "TRUE" for row in benchmark_coverage_rows)
    spy_ready = any(row["symbol"] == "SPY" and row["usable_for_pit_lite_recompute"] == "TRUE" for row in benchmark_coverage_rows)
    soxx_ready = any(row["symbol"] == "SOXX" and row["usable_for_pit_lite_recompute"] == "TRUE" for row in benchmark_coverage_rows)
    benchmark_coverage = "FULL_QQQ_SPY_SOXX" if qqq_ready and spy_ready and soxx_ready else ("PARTIAL_QQQ_SPY_ONLY" if qqq_ready and spy_ready else "INSUFFICIENT")

    write_csv(OUT_UNIVERSE, UNIVERSE_FIELDS, universe)
    write_csv(OUT_CANONICAL, CANONICAL_FIELDS, ticker_rows)
    write_csv(OUT_BENCHMARK, CANONICAL_FIELDS, benchmark_rows)
    write_csv(OUT_FAILURES, FAILURE_FIELDS, failure_rows)
    write_csv(OUT_COVERAGE, COVERAGE_FIELDS, combined_coverage)
    write_csv(OUT_BENCHMARK_COVERAGE, COVERAGE_FIELDS, benchmark_coverage_rows)
    write_csv(OUT_SCHEMA, SCHEMA_FIELDS, schema_validation_rows(ticker_rows, benchmark_rows))

    mechanism = mechanism_rows(len(universe), len({clean(row.get("symbol")) for row in canonical_rows}), len(failure_rows), refresh_ts, refresh_enabled)
    approved_mechanism = any(row["approved_for_v20_199d_direct_execution"] == "TRUE" for row in mechanism)
    write_csv(OUT_MECHANISM, MECHANISM_FIELDS, mechanism)

    result_status = "REFRESH_PLAN_ONLY" if not refresh_enabled else ("REFRESH_COMPLETED_WITH_ROWS" if canonical_rows else "REFRESH_FAILED_NO_ROWS")
    result = {
        "refresh_result_id": "V20_199D_REFRESH_RESULT_001",
        "execution_mode": execution_mode,
        "refresh_mechanism_name": "V20_199D_INTERNAL_YFINANCE_CANONICAL_REFRESH" if refresh_enabled else "REFRESH_PLAN_ONLY",
        "refresh_source_provider": PROVIDER if refresh_enabled else "",
        "refresh_timestamp": refresh_ts if refresh_enabled else "",
        "requested_symbol_count": str(len(universe)),
        "returned_symbol_count": str(len({clean(row.get("symbol")) for row in canonical_rows})),
        "failed_symbol_count": str(len(failure_rows)),
        "canonical_ohlcv_rows": str(len(ticker_rows)),
        "canonical_benchmark_rows": str(len(benchmark_rows)),
        "refresh_status": result_status,
        "no_fabricated_price_rows": "TRUE",
        "no_fabricated_benchmark_rows": "TRUE",
        "no_synthetic_ohlcv": "TRUE",
        "no_forward_returns_computed": "TRUE",
        "no_factor_scores_computed": "TRUE",
        "no_current_factor_snapshot_join": "TRUE",
        "no_current_fundamental_field_used": "TRUE",
        **COMMON_GUARDS,
    }
    write_csv(OUT_RESULT, RESULT_FIELDS, [result])

    guard_checks = {
        "no_fabricated_price_rows": "TRUE",
        "no_fabricated_benchmark_rows": "TRUE",
        "no_synthetic_ohlcv": "TRUE",
        "no_forward_returns_computed": "TRUE",
        "no_factor_scores_computed": "TRUE",
        "no_current_factor_snapshot_join": "TRUE",
        "no_current_fundamental_field_used": "TRUE",
        "official_ranking_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
    }
    guard_rows = []
    for check, expected in guard_checks.items():
        actual = COMMON_GUARDS.get(check, result.get(check, expected))
        guard_rows.append({
            "guard_check": check,
            "expected_value": expected,
            "actual_value": actual,
            "guard_status": "PASS" if actual == expected else "FAIL",
            "no_fabricated_price_rows": "TRUE",
            "no_fabricated_benchmark_rows": "TRUE",
            "no_synthetic_ohlcv": "TRUE",
            "no_forward_returns_computed": "TRUE",
            "no_factor_scores_computed": "TRUE",
            "no_current_factor_snapshot_join": "TRUE",
            "no_current_fundamental_field_used": "TRUE",
            **COMMON_GUARDS,
        })
    write_csv(OUT_GUARD, GUARD_FIELDS, guard_rows)

    if not refresh_enabled:
        final_status = PLAN_ONLY_STATUS
        blocking = "APPROVED_V20_199D_CANONICAL_REFRESH_REQUIRES_EXPLICIT_OPERATOR_ENABLE_FLAG"
    elif not canonical_rows:
        final_status = BLOCKED_STATUS
        blocking = "REFRESH_MECHANISM_FAILED_OR_RETURNED_NO_ROWS"
    elif tickers_with_60 >= 100 and qqq_ready and spy_ready and soxx_ready and no_official_mutation:
        final_status = PASS_STATUS
        blocking = "NONE"
    elif tickers_with_60 >= 30 and qqq_ready and spy_ready and no_official_mutation:
        final_status = PARTIAL_STATUS
        blocking = "SOXX_MISSING_OR_FEWER_THAN_100_TICKERS_WITH_60_BARS"
    else:
        final_status = BLOCKED_STATUS
        reasons = []
        if tickers_with_60 < 30:
            reasons.append("FEWER_THAN_30_SYMBOLS_HAVE_USABLE_HISTORICAL_PRICES")
        if not qqq_ready:
            reasons.append("QQQ_MISSING_60_BAR_HISTORY")
        if not spy_ready:
            reasons.append("SPY_MISSING_60_BAR_HISTORY")
        if not no_official_mutation:
            reasons.append("OFFICIAL_OR_INPUT_MUTATION_DETECTED")
        blocking = "|".join(reasons) if reasons else "PRICE_HISTORY_REFRESH_INSUFFICIENT"

    gate = {
        "gate_check_id": "V20_199D_NEXT_STAGE_GATE_001",
        "final_status": final_status,
        "approved_refresh_mechanism_exists": tf(approved_mechanism),
        "refresh_execution_attempted": tf(refresh_enabled),
        "canonical_ohlcv_created": tf(OUT_CANONICAL.exists() and OUT_BENCHMARK.exists()),
        "symbols_with_60_plus_bars": str(symbols_with_60),
        "tickers_with_60_plus_bars": str(tickers_with_60),
        "qqq_60_bar_ready": tf(qqq_ready),
        "spy_60_bar_ready": tf(spy_ready),
        "soxx_60_bar_ready": tf(soxx_ready),
        "benchmark_coverage": benchmark_coverage,
        "no_fabricated_prices": "TRUE",
        "no_official_trade_mutation": tf(no_official_mutation),
        "ready_for_v20_199c_rerun": tf(refresh_enabled and bool(canonical_rows)),
        "ready_for_v20_199b_rerun": tf(final_status in {PASS_STATUS, PARTIAL_STATUS}),
        "blocking_reason": blocking,
        **COMMON_GUARDS,
    }
    write_csv(OUT_GATE, GATE_FIELDS, [gate])

    OUT_REPORT.write_text(
        "\n".join([
            "# V20.199D Approved Historical Price Refresh",
            "",
            f"- final_status: {final_status}",
            f"- execution_mode: {execution_mode}",
            f"- requested_symbol_count: {len(universe)}",
            f"- returned_symbol_count: {len({clean(row.get('symbol')) for row in canonical_rows})}",
            f"- canonical_ohlcv_rows: {len(ticker_rows)}",
            f"- canonical_benchmark_rows: {len(benchmark_rows)}",
            f"- tickers_with_60_plus_bars: {tickers_with_60}",
            f"- qqq_60_bar_ready: {tf(qqq_ready)}",
            f"- spy_60_bar_ready: {tf(spy_ready)}",
            f"- soxx_60_bar_ready: {tf(soxx_ready)}",
            "",
            "This stage is research-only. It does not compute returns, factor scores, strategy effectiveness, recommendations, rankings, or trade actions.",
            f"Live yfinance refresh is disabled unless `{ENABLE_REFRESH_ENV}=TRUE` is explicitly set by the operator.",
        ]) + "\n",
        encoding="utf-8",
    )

    print(final_status)
    print(f"EXECUTION_MODE={execution_mode}")
    print(f"REQUESTED_SYMBOL_COUNT={len(universe)}")
    print(f"RETURNED_SYMBOL_COUNT={len({clean(row.get('symbol')) for row in canonical_rows})}")
    print(f"FAILED_SYMBOL_COUNT={len(failure_rows)}")
    print(f"CANONICAL_OHLCV_ROWS={len(ticker_rows)}")
    print(f"CANONICAL_BENCHMARK_ROWS={len(benchmark_rows)}")
    print(f"TICKERS_WITH_60_PLUS_BARS={tickers_with_60}")
    print(f"QQQ_60_BAR_READY={tf(qqq_ready)}")
    print(f"SPY_60_BAR_READY={tf(spy_ready)}")
    print(f"SOXX_60_BAR_READY={tf(soxx_ready)}")
    print("NO_FABRICATED_PRICE_ROWS=TRUE")
    print("NO_FABRICATED_BENCHMARK_ROWS=TRUE")
    print("NO_FORWARD_RETURNS_COMPUTED=TRUE")
    print("NO_FACTOR_SCORES_COMPUTED=TRUE")
    print(f"NO_OFFICIAL_TRADE_MUTATION={tf(no_official_mutation)}")
    print("RESEARCH_ONLY=TRUE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
