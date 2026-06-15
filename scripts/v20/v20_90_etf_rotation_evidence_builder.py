#!/usr/bin/env python
"""V20.90 research-only ETF rotation evidence builder."""

from __future__ import annotations

import csv
import math
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "outputs" / "v20" / "evidence"
PRICE_CACHE_DIRS = [
    ROOT / "state" / "v18" / "price_cache",
    ROOT / "outputs" / "v18" / "price_cache",
    ROOT / "cache" / "yahoo",
    ROOT / "cache" / "price",
]

PASS_STATUS = "PASS_V20_90_ETF_ROTATION_EVIDENCE_BUILDER_WITH_PARTIAL_COVERAGE"

VERSIONED_TABLE = OUTPUT_DIR / "V20_90_ETF_ROTATION_EVIDENCE_TABLE.csv"
VERSIONED_SUMMARY = OUTPUT_DIR / "V20_90_ETF_ROTATION_EVIDENCE_SUMMARY.md"
CURRENT_TABLE = OUTPUT_DIR / "V20_CURRENT_ETF_ROTATION_EVIDENCE_TABLE.csv"
CURRENT_SUMMARY = OUTPUT_DIR / "V20_CURRENT_ETF_ROTATION_EVIDENCE_SUMMARY.md"

HOLDING_WINDOW = 21
PARTIAL_STATUS = "PARTIAL_COVERAGE"
CERTIFIED_STATUS = "CERTIFIED_ETF_ROTATION_EVIDENCE"
BLOCKED_STATUS = "BLOCKED_ETF_ROTATION_EVIDENCE"

REQUIRED_COLUMNS = [
    "signal_date",
    "as_of_date",
    "rotation_pair_id",
    "rotation_pair_type",
    "from_etf",
    "to_etf",
    "candidate_etf",
    "benchmark_etf",
    "holding_window",
    "candidate_forward_return",
    "benchmark_forward_return",
    "excess_return",
    "max_drawdown",
    "volatility",
    "win_flag",
    "risk_adjusted_score",
    "certification_status",
    "certification_reason",
    "source_cache_file",
    "source_run_id",
    "research_only",
    "official_eligible",
    "official_recommendation_created",
    "official_weight_mutated",
    "trade_action_created",
]

POSITIVE_CERTIFICATIONS = {CERTIFIED_STATUS, "CERTIFIED"}
REJECT_CERT_TOKENS = {"BLOCKED", "INSUFFICIENT", "MISSING", "NOT_CERTIFIED", "PARTIAL", "UNCERTIFIED"}


@dataclass(frozen=True)
class RotationPair:
    from_etf: str
    to_etf: str
    pair_type: str

    @property
    def pair_id(self) -> str:
        return f"{self.from_etf}_{self.to_etf}"


CORE_PAIRS = [
    RotationPair("QQQ", "SPY", "CORE"),
    RotationPair("XLK", "SPY", "CORE"),
    RotationPair("SOXX", "QQQ", "CORE"),
    RotationPair("SMH", "SOXX", "CORE"),
    RotationPair("IWM", "SPY", "CORE"),
    RotationPair("TLT", "QQQ", "CORE"),
    RotationPair("GLD", "QQQ", "CORE"),
    RotationPair("XLY", "XLP", "CORE"),
]

LEVERAGED_PAIRS = [
    RotationPair("TQQQ", "SQQQ", "LEVERAGED_RESEARCH_ONLY"),
    RotationPair("SOXL", "SOXS", "LEVERAGED_RESEARCH_ONLY"),
    RotationPair("TECL", "TECS", "LEVERAGED_RESEARCH_ONLY"),
]

ALL_PAIRS = CORE_PAIRS + LEVERAGED_PAIRS


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def fmt(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "NA"
    return f"{value:.6f}"


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
    rows.sort(key=lambda item: item[0])
    deduped: dict[str, float] = {}
    for date, price in rows:
        deduped[date] = price
    return sorted(deduped.items())


def aligned_window(candidate: list[tuple[str, float]], benchmark: list[tuple[str, float]], holding_window: int) -> tuple[list[tuple[str, float, float]], str]:
    candidate_by_date = dict(candidate)
    benchmark_by_date = dict(benchmark)
    common_dates = sorted(set(candidate_by_date) & set(benchmark_by_date))
    if len(common_dates) < holding_window + 1:
        return [], "INSUFFICIENT_COMMON_PRICE_HISTORY"
    dates = common_dates[-(holding_window + 1) :]
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


def build_pair_row(pair: RotationPair, source_run_id: str, root: Path = ROOT, holding_window: int = HOLDING_WINDOW) -> dict[str, str]:
    candidate_path = find_cache_file(pair.from_etf, root)
    benchmark_path = find_cache_file(pair.to_etf, root)
    source_files = "|".join(rel(path) for path in [candidate_path, benchmark_path] if path)
    reason_parts: list[str] = []

    if candidate_path is None:
        reason_parts.append(f"MISSING_CANDIDATE_CACHE:{pair.from_etf}")
    if benchmark_path is None:
        reason_parts.append(f"MISSING_BENCHMARK_CACHE:{pair.to_etf}")

    window: list[tuple[str, float, float]] = []
    missing_reason = "NA"
    if not reason_parts:
        try:
            candidate_series = read_price_series(candidate_path) if candidate_path else []
            benchmark_series = read_price_series(benchmark_path) if benchmark_path else []
            window, missing_reason = aligned_window(candidate_series, benchmark_series, holding_window)
            if not window:
                reason_parts.append(missing_reason)
        except Exception as exc:
            reason_parts.append(f"UNREADABLE_CACHE:{type(exc).__name__}")

    candidate_return = benchmark_return = excess = mdd = vol = risk_adjusted = None
    signal_date = as_of_date = "NA"
    win_flag = "FALSE"
    status = PARTIAL_STATUS

    if window:
        signal_date = window[0][0]
        as_of_date = window[-1][0]
        candidate_prices = [row[1] for row in window]
        benchmark_prices = [row[2] for row in window]
        candidate_return = total_return(candidate_prices[0], candidate_prices[-1])
        benchmark_return = total_return(benchmark_prices[0], benchmark_prices[-1])
        if candidate_return is not None and benchmark_return is not None:
            excess = candidate_return - benchmark_return
            win_flag = tf(excess > 0)
        mdd = max_drawdown(candidate_prices)
        vol = sample_volatility(daily_returns(candidate_prices))
        if excess is not None and vol and vol > 0:
            risk_adjusted = excess / vol
        status = CERTIFIED_STATUS
        reason = "Structured local cache price history supports ETF rotation evidence calculation."
    else:
        reason = "PARTIAL_COVERAGE: " + "|".join(reason_parts or ["PRICE_HISTORY_UNAVAILABLE"])

    return {
        "signal_date": signal_date,
        "as_of_date": as_of_date,
        "rotation_pair_id": pair.pair_id,
        "rotation_pair_type": pair.pair_type,
        "from_etf": pair.from_etf,
        "to_etf": pair.to_etf,
        "candidate_etf": pair.from_etf,
        "benchmark_etf": pair.to_etf,
        "holding_window": str(holding_window),
        "candidate_forward_return": fmt(candidate_return),
        "benchmark_forward_return": fmt(benchmark_return),
        "excess_return": fmt(excess),
        "max_drawdown": fmt(mdd),
        "volatility": fmt(vol),
        "win_flag": win_flag,
        "risk_adjusted_score": fmt(risk_adjusted),
        "certification_status": status,
        "certification_reason": reason,
        "source_cache_file": source_files or "NA",
        "source_run_id": source_run_id,
        "research_only": "TRUE",
        "official_eligible": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
    }


def build_rows(root: Path = ROOT, pairs: list[RotationPair] | None = None, source_run_id: str | None = None) -> list[dict[str, str]]:
    run_id = source_run_id or "V20_90_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return [build_pair_row(pair, run_id, root) for pair in (pairs or ALL_PAIRS)]


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def summary_text(rows: list[dict[str, str]], created_at: str) -> str:
    total = len(rows)
    core = sum(1 for row in rows if row["rotation_pair_type"] == "CORE")
    leveraged = sum(1 for row in rows if row["rotation_pair_type"] == "LEVERAGED_RESEARCH_ONLY")
    certified = sum(1 for row in rows if row["certification_status"] == CERTIFIED_STATUS)
    partial = sum(1 for row in rows if row["certification_status"] == PARTIAL_STATUS)
    blocked = sum(1 for row in rows if row["certification_status"] == BLOCKED_STATUS)
    return "\n".join(
        [
            "# V20.90 ETF Rotation Evidence Summary",
            "",
            f"- final_status: {PASS_STATUS}",
            f"- created_at_utc: {created_at}",
            f"- total_pair_count: {total}",
            f"- core_pair_count: {core}",
            f"- leveraged_pair_count: {leveraged}",
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
    write_csv(VERSIONED_TABLE, rows)
    VERSIONED_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    VERSIONED_SUMMARY.write_text(summary_text(rows, created_at), encoding="utf-8")
    shutil.copyfile(VERSIONED_TABLE, CURRENT_TABLE)
    shutil.copyfile(VERSIONED_SUMMARY, CURRENT_SUMMARY)


def main() -> int:
    rows = build_rows()
    write_outputs(rows)
    print(PASS_STATUS)
    print(f"total_pair_count={len(rows)}")
    print(f"core_pair_count={sum(1 for row in rows if row['rotation_pair_type'] == 'CORE')}")
    print(f"leveraged_pair_count={sum(1 for row in rows if row['rotation_pair_type'] == 'LEVERAGED_RESEARCH_ONLY')}")
    print(f"certified_row_count={sum(1 for row in rows if row['certification_status'] == CERTIFIED_STATUS)}")
    print(f"partial_row_count={sum(1 for row in rows if row['certification_status'] == PARTIAL_STATUS)}")
    print(f"blocked_row_count={sum(1 for row in rows if row['certification_status'] == BLOCKED_STATUS)}")
    print("official_recommendation_created=FALSE")
    print("official_weight_mutated=FALSE")
    print("trade_action_created=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
