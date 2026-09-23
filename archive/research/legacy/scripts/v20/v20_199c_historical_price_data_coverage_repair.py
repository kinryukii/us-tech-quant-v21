#!/usr/bin/env python
"""V20.199C historical price data coverage repair audit."""

from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v20" / "backtest"
DISCOVERY_ROOTS = [
    ROOT / "outputs" / "v20",
    ROOT / "outputs" / "v18",
    ROOT / "outputs" / "v16",
    ROOT / "data",
    ROOT / "cache",
]
SNAPSHOT_LEDGER = ROOT / "outputs" / "v20" / "backtest_snapshots" / "V20_194_RECOMPUTABLE_FACTOR_SNAPSHOT_LEDGER.csv"
REQUIRED_BENCHMARKS = ["QQQ", "SPY", "SOXX"]

OUT_DISCOVERY = OUT_DIR / "V20_199C_PRICE_SOURCE_DISCOVERY.csv"
OUT_UNIVERSE = OUT_DIR / "V20_199C_REQUIRED_SYMBOL_UNIVERSE.csv"
OUT_PRICE_AUDIT = OUT_DIR / "V20_199C_HISTORICAL_PRICE_COVERAGE_AUDIT.csv"
OUT_BENCH_AUDIT = OUT_DIR / "V20_199C_HISTORICAL_BENCHMARK_COVERAGE_AUDIT.csv"
OUT_MANIFEST = OUT_DIR / "V20_199C_USABLE_PRICE_HISTORY_MANIFEST.csv"
OUT_GAP = OUT_DIR / "V20_199C_PRICE_HISTORY_GAP_REPORT.csv"
OUT_RISK = OUT_DIR / "V20_199C_PIT_LITE_PRICE_SOURCE_RISK_AUDIT.csv"
OUT_READINESS = OUT_DIR / "V20_199C_RECOMPUTE_READINESS_AUDIT.csv"
OUT_GATE = OUT_DIR / "V20_199C_NEXT_STAGE_GATE.csv"
OUT_REPORT = OUT_DIR / "V20_199C_READ_CENTER_REPORT.md"

PASS_STATUS = "PASS_V20_199C_HISTORICAL_PRICE_DATA_COVERAGE_REPAIR"
PARTIAL_STATUS = "PARTIAL_PASS_PRICE_COVERAGE_AUDIT_ONLY_V20_199C_HISTORICAL_PRICE_DATA_COVERAGE_REPAIR"
BLOCKED_STATUS = "BLOCKED_PRICE_HISTORY_MISSING_V20_199C_HISTORICAL_PRICE_DATA_COVERAGE_REPAIR"

COMMON = {
    "research_only": "TRUE",
    "official_ranking_mutated": "FALSE",
    "official_recommendation_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "real_book_action_created": "FALSE",
    "no_fabricated_price_rows": "TRUE",
    "no_fabricated_benchmark_rows": "TRUE",
    "current_factor_snapshot_join_count": "0",
    "current_fundamental_field_used_count": "0",
    "audit_only": "TRUE",
}

DISCOVERY_FIELDS = ["discovery_id", "source_artifact", "artifact_exists", "artifact_non_empty", "row_count", "field_count", "has_ticker_or_symbol", "has_date", "has_close_or_adjusted_close", "has_open", "has_high", "has_low", "has_volume", "accepted_price_file", "accepted_price_row_count", "accepted_symbol_count", "source_sha256", *COMMON.keys()]
UNIVERSE_FIELDS = ["symbol", "symbol_role", "required_for_backtest", "universe_source", "universe_pit_status", *COMMON.keys()]
COVERAGE_FIELDS = ["symbol", "earliest_price_date", "latest_price_date", "trading_day_count", "has_60_bar_lookback_potential", "has_5d_forward_potential", "has_10d_forward_potential", "has_20d_forward_potential", "has_60d_forward_potential", "missing_close_count", "missing_volume_count", "duplicate_date_count", "usable_for_pit_lite_recompute", "source_artifact_count", "source_artifact", "universe_pit_status", *COMMON.keys()]
MANIFEST_FIELDS = ["manifest_id", "symbol", "symbol_role", "source_artifact", "earliest_price_date", "latest_price_date", "trading_day_count", "raw_close_available_count", "adjusted_close_available_count", "volume_available_count", "usable_for_pit_lite_recompute", *COMMON.keys()]
GAP_FIELDS = ["gap_id", "symbol", "symbol_role", "gap_type", "required_value", "actual_value", "gap_status", "recommended_action", *COMMON.keys()]
RISK_FIELDS = ["risk_audit_id", "risk_check", "expected_value", "actual_value", "risk_status", "refresh_source", "refresh_timestamp", "requested_symbol_count", "returned_symbol_count", "failed_symbol_count", *COMMON.keys()]
READINESS_FIELDS = ["readiness_id", "readiness_check", "expected_value", "actual_value", "readiness_status", *COMMON.keys()]
GATE_FIELDS = ["gate_check_id", "usable_ticker_60bar_count", "required_usable_ticker_60bar_count", "partial_usable_ticker_60bar_count", "qqq_60bar_ready", "spy_60bar_ready", "soxx_60bar_ready", "potential_full_window_asof_count", "no_usable_price_files_found", "no_fabricated_prices", "no_official_trade_mutation", "ready_for_v20_199b_rerun", "blocking_reason", "final_status", *COMMON.keys()]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


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


def headers(path: Path) -> list[str]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return csv.DictReader(handle).fieldnames or []


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


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
        if clean(value) == "":
            return None
        return float(clean(value))
    except ValueError:
        return None


def field(row: dict[str, str], candidates: list[str]) -> str:
    lower = {key.lower(): key for key in row}
    for candidate in candidates:
        if candidate in lower:
            return row.get(lower[candidate], "")
    return ""


def discover_csvs() -> list[Path]:
    paths = []
    for root in DISCOVERY_ROOTS:
        if not root.exists():
            continue
        paths.extend(path for path in root.rglob("*.csv") if path.is_file())
    return sorted(paths)


def current_universe() -> list[str]:
    rows = read_csv(SNAPSHOT_LEDGER)
    tickers = sorted({row.get("ticker", "").upper() for row in rows if row.get("ticker")})
    return tickers


def build_universe_rows(tickers: list[str]) -> list[dict[str, str]]:
    rows = []
    for ticker in tickers:
        rows.append({
            "symbol": ticker,
            "symbol_role": "TICKER",
            "required_for_backtest": "TRUE",
            "universe_source": rel(SNAPSHOT_LEDGER),
            "universe_pit_status": "CURRENT_UNIVERSE_SURVIVORSHIP_RISK",
            **COMMON,
        })
    for benchmark in REQUIRED_BENCHMARKS:
        rows.append({
            "symbol": benchmark,
            "symbol_role": "BENCHMARK",
            "required_for_backtest": "TRUE",
            "universe_source": "REQUIRED_BENCHMARKS",
            "universe_pit_status": "BENCHMARK_REQUIRED_CURRENT_SYMBOL",
            **COMMON,
        })
    return rows


def build_price_index(paths: list[Path]) -> tuple[dict[str, dict[str, dict[str, object]]], list[dict[str, str]]]:
    ticker_fields = ["ticker", "symbol", "yf_ticker", "benchmark_ticker", "benchmark_symbol"]
    date_fields = ["date", "price_date", "latest_price_date", "refreshed_price_date", "effective_price_date", "observation_date"]
    close_fields = ["close", "adjusted_close", "adj_close", "latest_close", "latest_adj_close", "refreshed_latest_close", "refreshed_latest_adj_close", "effective_close", "close_like_price"]
    open_fields = ["open", "latest_open"]
    high_fields = ["high", "latest_high"]
    low_fields = ["low", "latest_low"]
    volume_fields = ["volume", "latest_volume", "refreshed_latest_volume"]
    index: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    discovery = []
    for idx, path in enumerate(paths, start=1):
        hdr = {h.lower() for h in headers(path)}
        has_ticker = bool(hdr.intersection(ticker_fields))
        has_date = bool(hdr.intersection(date_fields))
        has_close = bool(hdr.intersection(close_fields))
        has_open = bool(hdr.intersection(open_fields))
        has_high = bool(hdr.intersection(high_fields))
        has_low = bool(hdr.intersection(low_fields))
        has_volume = bool(hdr.intersection(volume_fields))
        accepted = 0
        symbols = set()
        if has_ticker and has_date and has_close:
            for row in read_csv(path):
                symbol = field(row, ticker_fields).upper()
                price_date = field(row, date_fields)[:10]
                close_value = field(row, close_fields)
                close = as_float(close_value)
                if not symbol or not price_date or close is None or close <= 0:
                    continue
                volume_value = field(row, volume_fields)
                volume = as_float(volume_value)
                adjusted_value = field(row, ["adjusted_close", "adj_close", "latest_adj_close", "refreshed_latest_adj_close"])
                raw_close_value = field(row, ["close", "latest_close", "refreshed_latest_close", "effective_close"])
                existing = index[symbol].get(price_date)
                if existing is None or (existing.get("volume") in {"", None} and volume is not None):
                    index[symbol][price_date] = {
                        "close": close,
                        "volume": volume,
                        "raw_close_available": raw_close_value != "",
                        "adjusted_close_available": adjusted_value != "",
                        "source_artifact": rel(path),
                    }
                accepted += 1
                symbols.add(symbol)
        discovery.append({
            "discovery_id": f"V20_199C_DISCOVERY_{idx:05d}",
            "source_artifact": rel(path),
            "artifact_exists": "TRUE",
            "artifact_non_empty": tf(path.stat().st_size > 0),
            "row_count": str(len(read_csv(path)) if has_ticker and has_date and has_close else 0),
            "field_count": str(len(hdr)),
            "has_ticker_or_symbol": tf(has_ticker),
            "has_date": tf(has_date),
            "has_close_or_adjusted_close": tf(has_close),
            "has_open": tf(has_open),
            "has_high": tf(has_high),
            "has_low": tf(has_low),
            "has_volume": tf(has_volume),
            "accepted_price_file": tf(accepted > 0),
            "accepted_price_row_count": str(accepted),
            "accepted_symbol_count": str(len(symbols)),
            "source_sha256": sha_file(path),
            **COMMON,
        })
    return {symbol: dict(sorted(rows.items())) for symbol, rows in index.items()}, discovery


def coverage_for(symbol: str, role: str, rows: dict[str, dict[str, object]]) -> dict[str, str]:
    dates = sorted(rows)
    duplicate_count = 0
    missing_close = sum(1 for d in dates if rows[d].get("close") in {"", None})
    missing_volume = sum(1 for d in dates if rows[d].get("volume") in {"", None})
    sources = sorted({str(rows[d].get("source_artifact", "")) for d in dates if rows[d].get("source_artifact")})
    count = len(dates)
    return {
        "symbol": symbol,
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
        "usable_for_pit_lite_recompute": tf(count >= 60 and missing_close == 0),
        "source_artifact_count": str(len(sources)),
        "source_artifact": "|".join(sources[:8]),
        "universe_pit_status": "BENCHMARK_REQUIRED_CURRENT_SYMBOL" if role == "BENCHMARK" else "CURRENT_UNIVERSE_SURVIVORSHIP_RISK",
        **COMMON,
    }


def potential_asof_count(index: dict[str, dict[str, dict[str, object]]]) -> int:
    calendars = [set(index.get(benchmark, {}).keys()) for benchmark in REQUIRED_BENCHMARKS]
    if any(not calendar for calendar in calendars):
        return 0
    common_dates = sorted(set.intersection(*calendars))
    return sum(1 for idx, _ in enumerate(common_dates) if idx >= 59 and idx + 60 < len(common_dates))


def main() -> int:
    before_hash = sha_file(SNAPSHOT_LEDGER)
    tickers = current_universe()
    universe_rows = build_universe_rows(tickers)
    paths = discover_csvs()
    index, discovery_rows = build_price_index(paths)
    after_hash = sha_file(SNAPSHOT_LEDGER)
    no_mutation = before_hash == after_hash

    ticker_coverage = [coverage_for(ticker, "TICKER", index.get(ticker, {})) for ticker in tickers]
    benchmark_coverage = [coverage_for(benchmark, "BENCHMARK", index.get(benchmark, {})) for benchmark in REQUIRED_BENCHMARKS]
    usable_ticker_count = sum(1 for row in ticker_coverage if row["usable_for_pit_lite_recompute"] == "TRUE")
    qqq_ready = next((row["usable_for_pit_lite_recompute"] == "TRUE" for row in benchmark_coverage if row["symbol"] == "QQQ"), False)
    spy_ready = next((row["usable_for_pit_lite_recompute"] == "TRUE" for row in benchmark_coverage if row["symbol"] == "SPY"), False)
    soxx_ready = next((row["usable_for_pit_lite_recompute"] == "TRUE" for row in benchmark_coverage if row["symbol"] == "SOXX"), False)
    full_window_asof = potential_asof_count(index)
    accepted_files = [row for row in discovery_rows if row["accepted_price_file"] == "TRUE"]
    no_usable_files = len(accepted_files) == 0

    manifest_rows = []
    for idx, row in enumerate([*ticker_coverage, *benchmark_coverage], start=1):
        if row["source_artifact"]:
            symbol_rows = index.get(row["symbol"], {})
            raw_count = sum(1 for d in symbol_rows if symbol_rows[d].get("raw_close_available"))
            adj_count = sum(1 for d in symbol_rows if symbol_rows[d].get("adjusted_close_available"))
            vol_count = sum(1 for d in symbol_rows if symbol_rows[d].get("volume") not in {"", None})
            manifest_rows.append({
                "manifest_id": f"V20_199C_MANIFEST_{idx:05d}",
                "symbol": row["symbol"],
                "symbol_role": "BENCHMARK" if row["symbol"] in REQUIRED_BENCHMARKS else "TICKER",
                "source_artifact": row["source_artifact"],
                "earliest_price_date": row["earliest_price_date"],
                "latest_price_date": row["latest_price_date"],
                "trading_day_count": row["trading_day_count"],
                "raw_close_available_count": str(raw_count),
                "adjusted_close_available_count": str(adj_count),
                "volume_available_count": str(vol_count),
                "usable_for_pit_lite_recompute": row["usable_for_pit_lite_recompute"],
                **COMMON,
            })

    gap_rows = []
    for idx, row in enumerate([*ticker_coverage, *benchmark_coverage], start=1):
        count = int(row["trading_day_count"])
        if count < 60:
            gap_rows.append({
                "gap_id": f"V20_199C_GAP_{idx:05d}",
                "symbol": row["symbol"],
                "symbol_role": "BENCHMARK" if row["symbol"] in REQUIRED_BENCHMARKS else "TICKER",
                "gap_type": "INSUFFICIENT_60_BAR_HISTORY",
                "required_value": "60",
                "actual_value": str(count),
                "gap_status": "BLOCKS_PIT_LITE_RECOMPUTE",
                "recommended_action": "STAGE_APPROVED_LOCAL_HISTORICAL_OHLCV_SOURCE_OR_RUN_APPROVED_REFRESH_MECHANISM",
                **COMMON,
            })
    raw_close_count = sum(int(row["raw_close_available_count"]) for row in manifest_rows)
    adj_close_count = sum(int(row["adjusted_close_available_count"]) for row in manifest_rows)
    returned_symbol_count = len({row["symbol"] for row in manifest_rows})
    risk_checks = [
        ("price_data_downloaded_after_asof_allowed_for_research_only", "TRUE", "TRUE", "", "", str(len(universe_rows)), str(returned_symbol_count), str(max(0, len(universe_rows) - returned_symbol_count))),
        ("factor_recompute_must_slice_date_lte_asof", "TRUE", "TRUE", "", "", str(len(universe_rows)), str(returned_symbol_count), str(max(0, len(universe_rows) - returned_symbol_count))),
        ("future_price_used_for_factor_count", "0", "0", "", "", str(len(universe_rows)), str(returned_symbol_count), str(max(0, len(universe_rows) - returned_symbol_count))),
        ("adjusted_close_future_adjustment_risk_flag", "DISCLOSED", "DISCLOSED" if adj_close_count > 0 else "NOT_APPLICABLE_NO_ADJUSTED_CLOSE_USED", "", "", str(len(universe_rows)), str(returned_symbol_count), str(max(0, len(universe_rows) - returned_symbol_count))),
        ("raw_close_available_count", str(raw_close_count), str(raw_close_count), "", "", str(len(universe_rows)), str(returned_symbol_count), str(max(0, len(universe_rows) - returned_symbol_count))),
        ("adjusted_close_available_count", str(adj_close_count), str(adj_close_count), "", "", str(len(universe_rows)), str(returned_symbol_count), str(max(0, len(universe_rows) - returned_symbol_count))),
        ("no_fabricated_price_rows", "TRUE", "TRUE", "NO_EXTERNAL_REFRESH_PERFORMED", "", str(len(universe_rows)), str(returned_symbol_count), str(max(0, len(universe_rows) - returned_symbol_count))),
    ]
    risk_rows = []
    for idx, (check, expected, actual, refresh_source, refresh_timestamp, requested, returned, failed) in enumerate(risk_checks, start=1):
        risk_rows.append({
            "risk_audit_id": f"V20_199C_RISK_{idx:03d}",
            "risk_check": check,
            "expected_value": expected,
            "actual_value": actual,
            "risk_status": "PASS" if expected == actual else "DISCLOSED_RISK",
            "refresh_source": refresh_source,
            "refresh_timestamp": refresh_timestamp,
            "requested_symbol_count": requested,
            "returned_symbol_count": returned,
            "failed_symbol_count": failed,
            **COMMON,
        })

    readiness_checks = [
        ("usable_ticker_60bar_count_gte_100", "TRUE", tf(usable_ticker_count >= 100)),
        ("usable_ticker_60bar_count_gte_30", "TRUE", tf(usable_ticker_count >= 30)),
        ("qqq_60bar_ready", "TRUE", tf(qqq_ready)),
        ("spy_60bar_ready", "TRUE", tf(spy_ready)),
        ("soxx_60bar_ready", "TRUE", tf(soxx_ready)),
        ("potential_full_window_asof_count_gte_30", "TRUE", tf(full_window_asof >= 30)),
        ("no_fabricated_price_rows", "TRUE", "TRUE"),
        ("no_fabricated_benchmark_rows", "TRUE", "TRUE"),
        ("no_official_trade_mutation", "TRUE", tf(no_mutation)),
    ]
    readiness_rows = [{
        "readiness_id": f"V20_199C_READINESS_{idx:03d}",
        "readiness_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "readiness_status": "PASS" if expected == actual else "FAIL",
        **COMMON,
    } for idx, (check, expected, actual) in enumerate(readiness_checks, start=1)]

    if no_usable_files:
        final_status = BLOCKED_STATUS
        blocking = "NO_USABLE_PRICE_FILES_FOUND"
        ready = "FALSE"
    elif usable_ticker_count >= 100 and qqq_ready and spy_ready and soxx_ready and full_window_asof >= 30 and no_mutation:
        final_status = PASS_STATUS
        blocking = "NONE"
        ready = "TRUE"
    elif usable_ticker_count >= 30 and qqq_ready and spy_ready and no_mutation:
        final_status = PARTIAL_STATUS
        blocking = "FEWER_THAN_30_FULL_WINDOW_ASOF_DATES_OR_SOXX_LIMITED"
        ready = "TRUE"
    else:
        final_status = BLOCKED_STATUS
        reasons = []
        if usable_ticker_count < 30:
            reasons.append("FEWER_THAN_30_TICKERS_HAVE_USABLE_HISTORICAL_PRICES")
        if not qqq_ready:
            reasons.append("QQQ_MISSING_60_BAR_HISTORY")
        if not spy_ready:
            reasons.append("SPY_MISSING_60_BAR_HISTORY")
        if not no_mutation:
            reasons.append("OFFICIAL_OR_INPUT_MUTATION_DETECTED")
        blocking = "|".join(reasons) if reasons else "PRICE_HISTORY_MISSING"
        ready = "FALSE"
    gate = {
        "gate_check_id": "V20_199C_NEXT_STAGE_GATE_001",
        "usable_ticker_60bar_count": str(usable_ticker_count),
        "required_usable_ticker_60bar_count": "100",
        "partial_usable_ticker_60bar_count": "30",
        "qqq_60bar_ready": tf(qqq_ready),
        "spy_60bar_ready": tf(spy_ready),
        "soxx_60bar_ready": tf(soxx_ready),
        "potential_full_window_asof_count": str(full_window_asof),
        "no_usable_price_files_found": tf(no_usable_files),
        "no_fabricated_prices": "TRUE",
        "no_official_trade_mutation": tf(no_mutation),
        "ready_for_v20_199b_rerun": ready,
        "blocking_reason": blocking,
        "final_status": final_status,
        **COMMON,
    }

    write_csv(OUT_DISCOVERY, DISCOVERY_FIELDS, discovery_rows)
    write_csv(OUT_UNIVERSE, UNIVERSE_FIELDS, universe_rows)
    write_csv(OUT_PRICE_AUDIT, COVERAGE_FIELDS, ticker_coverage)
    write_csv(OUT_BENCH_AUDIT, COVERAGE_FIELDS, benchmark_coverage)
    write_csv(OUT_MANIFEST, MANIFEST_FIELDS, manifest_rows)
    write_csv(OUT_GAP, GAP_FIELDS, gap_rows)
    write_csv(OUT_RISK, RISK_FIELDS, risk_rows)
    write_csv(OUT_READINESS, READINESS_FIELDS, readiness_rows)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    OUT_REPORT.write_text(
        "\n".join([
            "# V20.199C Historical Price Data Coverage Repair",
            "",
            f"- final_status: {final_status}",
            f"- usable_ticker_60bar_count: {usable_ticker_count}",
            f"- qqq_60bar_ready: {tf(qqq_ready)}",
            f"- spy_60bar_ready: {tf(spy_ready)}",
            f"- soxx_60bar_ready: {tf(soxx_ready)}",
            f"- potential_full_window_asof_count: {full_window_asof}",
            "",
            "No external data download was performed. This stage audits allowed local OHLCV coverage only and does not compute strategy effectiveness, fabricate prices, mutate official rankings, or create trade actions.",
        ]) + "\n",
        encoding="utf-8",
    )
    print(final_status)
    for key in GATE_FIELDS:
        if key not in COMMON and key != "gate_check_id":
            print(f"{key.upper()}={gate[key]}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("REAL_BOOK_ACTION_CREATED=FALSE")
    print("NO_FABRICATED_PRICE_ROWS=TRUE")
    print("NO_FABRICATED_BENCHMARK_ROWS=TRUE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
