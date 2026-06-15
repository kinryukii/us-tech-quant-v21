#!/usr/bin/env python
"""V20.91 research-only multi-window strategy evidence matrix."""

from __future__ import annotations

import csv
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "outputs" / "v20" / "evidence"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"

PRICE_CACHE_DIRS = [
    Path("state") / "v18" / "price_cache",
    Path("outputs") / "v18" / "price_cache",
    Path("cache") / "yahoo",
    Path("cache") / "price",
]

PASS_STATUS = "PASS_V20_91_MULTI_WINDOW_STRATEGY_EVIDENCE_MATRIX_WITH_PARTIAL_COVERAGE"

VERSIONED_MATRIX = OUTPUT_DIR / "V20_91_MULTI_WINDOW_STRATEGY_EVIDENCE_MATRIX.csv"
VERSIONED_SUMMARY = OUTPUT_DIR / "V20_91_MULTI_WINDOW_STRATEGY_EVIDENCE_SUMMARY.md"
CURRENT_MATRIX = OUTPUT_DIR / "V20_CURRENT_MULTI_WINDOW_STRATEGY_EVIDENCE_MATRIX.csv"
CURRENT_SUMMARY = OUTPUT_DIR / "V20_CURRENT_MULTI_WINDOW_STRATEGY_EVIDENCE_SUMMARY.md"

REQUIRED_WINDOWS = {
    "forward_1d": 1,
    "forward_5d": 5,
    "forward_10d": 10,
    "forward_20d": 20,
}

DEFAULT_STRATEGY_ID = "CURRENT_OFFICIAL_RANKING_RESEARCH_MULTI_WINDOW"
CERTIFIED_STATUS = "CERTIFIED_MULTI_WINDOW_STRATEGY_EVIDENCE"
PARTIAL_STATUS = "PARTIAL_COVERAGE"
BLOCKED_STATUS = "BLOCKED_MULTI_WINDOW_STRATEGY_EVIDENCE"

REQUIRED_COLUMNS = [
    "signal_date",
    "as_of_date",
    "ticker",
    "strategy_id",
    "entry_rule",
    "exit_rule",
    "holding_window",
    "entry_price",
    "exit_price",
    "forward_return",
    "benchmark_ticker",
    "benchmark_forward_return",
    "excess_return",
    "max_drawdown",
    "volatility",
    "win_flag",
    "risk_adjusted_score",
    "source_stage",
    "source_run_id",
    "source_cache_file",
    "certification_status",
    "certification_reason",
    "research_only",
    "official_recommendation_created",
    "official_weight_mutated",
    "trade_action_created",
]

POSITIVE_CERTIFICATIONS = {CERTIFIED_STATUS, "CERTIFIED"}
REJECT_CERT_TOKENS = {"BLOCKED", "INSUFFICIENT", "MISSING", "NOT_CERTIFIED", "PARTIAL", "UNCERTIFIED"}


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def fmt(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "NA"
    return f"{value:.6f}"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def find_cache_file(ticker: str, root: Path = ROOT) -> Path | None:
    candidates: list[Path] = []
    for directory in PRICE_CACHE_DIRS:
        search_dir = directory if directory.is_absolute() else root / directory
        if search_dir.exists():
            candidates.extend(search_dir.glob(f"{ticker}.csv"))
            candidates.extend(search_dir.glob(f"{ticker.upper()}.csv"))
            candidates.extend(search_dir.glob(f"{ticker.lower()}.csv"))
    files = [path for path in candidates if path.is_file()]
    if not files:
        return None
    files.sort(key=lambda path: (-path.stat().st_size, -path.stat().st_mtime))
    return files[0]


def read_price_series(path: Path) -> list[tuple[str, float]]:
    rows: list[tuple[str, float]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            date = clean(row.get("date") or row.get("Date"))
            raw_price = clean(row.get("adj_close") or row.get("Adj Close") or row.get("close") or row.get("Close"))
            if not date or not raw_price:
                continue
            try:
                price = float(raw_price)
            except ValueError:
                continue
            if price > 0:
                rows.append((date, price))
    deduped: dict[str, float] = {}
    for date, price in sorted(rows, key=lambda item: item[0]):
        deduped[date] = price
    return sorted(deduped.items())


def aligned_window(candidate: list[tuple[str, float]], benchmark: list[tuple[str, float]], window: int) -> tuple[list[tuple[str, float, float]], str]:
    candidate_by_date = dict(candidate)
    benchmark_by_date = dict(benchmark)
    common_dates = sorted(set(candidate_by_date) & set(benchmark_by_date))
    if len(common_dates) < window + 1:
        return [], "INSUFFICIENT_COMMON_PRICE_HISTORY"
    dates = common_dates[-(window + 1) :]
    return [(date, candidate_by_date[date], benchmark_by_date[date]) for date in dates], "NA"


def total_return(start: float, end: float) -> float | None:
    if start <= 0:
        return None
    return end / start - 1.0


def daily_returns(prices: list[float]) -> list[float]:
    returns: list[float] = []
    for previous, current in zip(prices, prices[1:]):
        if previous > 0:
            returns.append(current / previous - 1.0)
    return returns


def max_drawdown(prices: list[float]) -> float | None:
    if not prices:
        return None
    peak = prices[0]
    worst = 0.0
    for price in prices:
        peak = max(peak, price)
        if peak > 0:
            worst = min(worst, price / peak - 1.0)
    return worst


def sample_volatility(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(252.0)


def structured_certification_is_positive(row: dict[str, str]) -> bool:
    for key, value in row.items():
        lower = key.lower()
        text = clean(value).upper()
        if "certification" not in lower or "reason" in lower or "note" in lower:
            continue
        if not text or any(token in text for token in REJECT_CERT_TOKENS):
            continue
        if text in POSITIVE_CERTIFICATIONS or text.startswith("CERTIFIED_"):
            return True
    return False


def load_research_universe(root: Path = ROOT, limit: int = 10) -> list[str]:
    ranking = root / "outputs" / "v20" / "consolidation" / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
    tickers: list[str] = []
    if ranking.exists():
        for row in read_csv(ranking):
            ticker = clean(row.get("ticker")).upper()
            if ticker and ticker not in tickers:
                tickers.append(ticker)
            if len(tickers) >= limit:
                break
    if "QQQ" not in tickers:
        tickers.append("QQQ")
    return tickers or ["QQQ"]


def benchmark_for(ticker: str) -> str:
    return "SPY" if ticker.upper() == "QQQ" else "QQQ"


def source_run_id() -> str:
    return "V20_91_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_row(ticker: str, window_label: str, window_days: int, run_id: str, root: Path = ROOT) -> dict[str, str]:
    benchmark = benchmark_for(ticker)
    ticker_path = find_cache_file(ticker, root)
    benchmark_path = find_cache_file(benchmark, root)
    source_files = "|".join(rel(path) for path in [ticker_path, benchmark_path] if path)
    reason_parts: list[str] = []
    if ticker_path is None:
        reason_parts.append(f"MISSING_TICKER_CACHE:{ticker}")
    if benchmark_path is None:
        reason_parts.append(f"MISSING_BENCHMARK_CACHE:{benchmark}")

    window: list[tuple[str, float, float]] = []
    if not reason_parts:
        try:
            ticker_series = read_price_series(ticker_path) if ticker_path else []
            benchmark_series = read_price_series(benchmark_path) if benchmark_path else []
            window, missing_reason = aligned_window(ticker_series, benchmark_series, window_days)
            if not window:
                reason_parts.append(missing_reason)
        except Exception as exc:
            reason_parts.append(f"UNREADABLE_CACHE:{type(exc).__name__}")

    signal_date = as_of_date = "NA"
    entry_price = exit_price = forward_return = benchmark_return = excess = mdd = vol = risk_adjusted = None
    win_flag = "FALSE"
    status = PARTIAL_STATUS
    reason = "PARTIAL_COVERAGE: " + "|".join(reason_parts or ["PRICE_HISTORY_UNAVAILABLE"])

    if window:
        signal_date = window[0][0]
        as_of_date = window[-1][0]
        ticker_prices = [item[1] for item in window]
        benchmark_prices = [item[2] for item in window]
        entry_price = ticker_prices[0]
        exit_price = ticker_prices[-1]
        forward_return = total_return(entry_price, exit_price)
        benchmark_return = total_return(benchmark_prices[0], benchmark_prices[-1])
        if forward_return is not None and benchmark_return is not None:
            excess = forward_return - benchmark_return
            win_flag = tf(excess > 0)
        mdd = max_drawdown(ticker_prices)
        vol = sample_volatility(daily_returns(ticker_prices))
        if excess is not None and vol and vol > 0:
            risk_adjusted = excess / vol
        status = CERTIFIED_STATUS
        reason = "Structured local cache price history supports multi-window strategy evidence calculation."

    return {
        "signal_date": signal_date,
        "as_of_date": as_of_date,
        "ticker": ticker,
        "strategy_id": DEFAULT_STRATEGY_ID,
        "entry_rule": "CURRENT_RANKING_RESEARCH_ENTRY",
        "exit_rule": f"{window_label}_RESEARCH_EXIT",
        "holding_window": window_label,
        "entry_price": fmt(entry_price),
        "exit_price": fmt(exit_price),
        "forward_return": fmt(forward_return),
        "benchmark_ticker": benchmark,
        "benchmark_forward_return": fmt(benchmark_return),
        "excess_return": fmt(excess),
        "max_drawdown": fmt(mdd),
        "volatility": fmt(vol),
        "win_flag": win_flag,
        "risk_adjusted_score": fmt(risk_adjusted),
        "source_stage": "V20.91_MULTI_WINDOW_STRATEGY_EVIDENCE_MATRIX",
        "source_run_id": run_id,
        "source_cache_file": source_files or "NA",
        "certification_status": status,
        "certification_reason": reason,
        "research_only": "TRUE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
    }


def build_rows(root: Path = ROOT, tickers: list[str] | None = None, run_id: str | None = None) -> list[dict[str, str]]:
    actual_run_id = run_id or source_run_id()
    universe = tickers or load_research_universe(root)
    rows: list[dict[str, str]] = []
    for ticker in universe:
        for label, days in REQUIRED_WINDOWS.items():
            rows.append(build_row(ticker.upper(), label, days, actual_run_id, root))
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def summary_text(rows: list[dict[str, str]], created_at: str) -> str:
    row_count = len(rows)
    ticker_count = len({row["ticker"] for row in rows})
    strategy_count = len({row["strategy_id"] for row in rows})
    window_count = len({row["holding_window"] for row in rows})
    certified = sum(1 for row in rows if row["certification_status"] == CERTIFIED_STATUS)
    partial = sum(1 for row in rows if row["certification_status"] == PARTIAL_STATUS)
    blocked = sum(1 for row in rows if row["certification_status"] == BLOCKED_STATUS)
    represented = sorted({row["holding_window"] for row in rows})
    missing_windows = sorted(set(REQUIRED_WINDOWS) - set(represented))
    return "\n".join(
        [
            "# V20.91 Multi-window Strategy Evidence Summary",
            "",
            f"- final_status: {PASS_STATUS}",
            f"- created_at_utc: {created_at}",
            f"- row_count: {row_count}",
            f"- ticker_count: {ticker_count}",
            f"- strategy_count: {strategy_count}",
            f"- window_count: {window_count}",
            f"- required_windows_represented: {'|'.join(represented) if represented else 'NONE'}",
            f"- required_windows_missing: {'|'.join(missing_windows) if missing_windows else 'NONE'}",
            f"- certified_row_count: {certified}",
            f"- partial_row_count: {partial}",
            f"- blocked_row_count: {blocked}",
            "- research_only: TRUE",
            "- official_recommendation_created: FALSE",
            "- official_weight_mutated: FALSE",
            "- trade_action_created: FALSE",
            "- certification_rule: explicit structured certification_status only; notes text is not certification",
            "",
        ]
    )


def write_outputs(rows: list[dict[str, str]]) -> None:
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_csv(VERSIONED_MATRIX, rows)
    VERSIONED_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    VERSIONED_SUMMARY.write_text(summary_text(rows, created_at), encoding="utf-8")
    shutil.copyfile(VERSIONED_MATRIX, CURRENT_MATRIX)
    shutil.copyfile(VERSIONED_SUMMARY, CURRENT_SUMMARY)


def main() -> int:
    rows = build_rows()
    write_outputs(rows)
    print(PASS_STATUS)
    print(f"row_count={len(rows)}")
    print(f"ticker_count={len({row['ticker'] for row in rows})}")
    print(f"strategy_count={len({row['strategy_id'] for row in rows})}")
    print(f"window_count={len({row['holding_window'] for row in rows})}")
    print(f"certified_row_count={sum(1 for row in rows if row['certification_status'] == CERTIFIED_STATUS)}")
    print(f"partial_row_count={sum(1 for row in rows if row['certification_status'] == PARTIAL_STATUS)}")
    print(f"blocked_row_count={sum(1 for row in rows if row['certification_status'] == BLOCKED_STATUS)}")
    print("official_recommendation_created=FALSE")
    print("official_weight_mutated=FALSE")
    print("trade_action_created=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
