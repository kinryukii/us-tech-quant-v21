from __future__ import annotations

import csv
import math
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UNIVERSE_YAML = ROOT / "configs" / "v16" / "universe" / "us_full_second_stage_generated.yaml"
FACTOR_PACK = ROOT / "outputs" / "v18" / "factor_pack" / "V18_CURRENT_RAW105_FACTOR_PACK_RANKING.csv"
PRICE_CACHE = ROOT / "state" / "v18" / "price_cache"
OUT_TIMING = ROOT / "outputs" / "v18" / "technical_timing" / "V18_6A_CURRENT_TECHNICAL_TIMING.csv"
OUT_AUDIT = ROOT / "outputs" / "v18" / "technical_timing" / "V18_6A_CURRENT_TECHNICAL_TIMING_SOURCE_AUDIT.csv"
OUT_STATUS = ROOT / "outputs" / "v18" / "technical_timing" / "V18_6A_CURRENT_TECHNICAL_TIMING_REPAIR_STATUS.csv"
OUT_READ_FIRST = ROOT / "outputs" / "v18" / "read_center" / "V18_6A_CURRENT_TECHNICAL_TIMING_REPAIR_READ_FIRST.txt"

PASS_STATUS = "PASS_V18_CURRENT_TECHNICAL_TIMING_REPAIR"
BLOCKED_STATUS = "BLOCKED_V18_CURRENT_TECHNICAL_TIMING_REPAIR"
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)?$")

FIELDS = [
    "ticker",
    "yf_ticker",
    "price_date",
    "latest_price_date",
    "close",
    "latest_price",
    "sma_10",
    "sma_20",
    "sma_50",
    "sma_200",
    "return_5d",
    "return_20d",
    "distance_to_sma20",
    "distance_to_sma50",
    "rsi_14",
    "bb_mid_20",
    "bb_upper_20_2",
    "bb_lower_20_2",
    "bb_percent_b",
    "bb_bandwidth",
    "volume_ratio_5_20",
    "trend_status",
    "buy_zone_status",
    "technical_timing_status",
    "technical_status",
    "technical_signal",
    "technical_timing_score",
    "pullback_status",
    "overheat_status",
    "execution_status",
    "source_stage",
    "source_file",
    "source_universe",
    "factor_pack_alignment",
    "official_decision_impact",
    "research_only",
]


def clean(value: object) -> str:
    return str(value or "").strip()


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def valid_ticker(token: str) -> bool:
    token = clean(token).upper()
    return bool(token and len(token) <= 12 and TICKER_RE.fullmatch(token))


def to_float(value: object) -> float | None:
    try:
        text = clean(value).replace(",", "")
        if not text:
            return None
        number = float(text)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    except Exception:
        return None


def read_tickers(path: Path) -> list[str]:
    if not path.exists():
        return []
    tickers: list[str] = []
    in_tickers = False
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "tickers:":
            in_tickers = True
            continue
        if in_tickers and line.startswith("- "):
            ticker = line[2:].strip().strip("'\"").upper()
            if valid_ticker(ticker):
                tickers.append(ticker)
        elif in_tickers and not raw.startswith((" ", "\t")):
            break
    return sorted(dict.fromkeys(tickers))


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    for encoding in ("utf-8-sig", "utf-8", "cp932", "latin-1"):
        try:
            with path.open("r", encoding=encoding, newline="", errors="replace") as handle:
                return [dict(row) for row in csv.DictReader(handle)]
        except Exception:
            continue
    return []


def factor_tickers() -> set[str]:
    return {clean(row.get("ticker")).upper() for row in read_csv_rows(FACTOR_PACK) if valid_ticker(clean(row.get("ticker")).upper())}


def read_price_cache(path: Path) -> tuple[list[dict[str, float | str]], str]:
    if not path.exists():
        return [], "price_cache_file_missing"
    rows = read_csv_rows(path)
    parsed: list[dict[str, float | str]] = []
    for row in rows:
        date = clean(row.get("date"))[:10]
        close = to_float(row.get("close") or row.get("adj_close"))
        high = to_float(row.get("high")) or close
        low = to_float(row.get("low")) or close
        volume = to_float(row.get("volume")) or 0.0
        if date and close is not None:
            parsed.append({"date": date, "close": close, "high": high or close, "low": low or close, "volume": volume})
    parsed.sort(key=lambda row: str(row["date"]))
    return parsed, "" if parsed else "no_parseable_price_rows"


def avg(values: list[float]) -> float:
    return sum(values) / len(values)


def pct(current: float, previous: float) -> str:
    return "" if previous == 0 else f"{(current / previous) - 1.0:.6f}"


def rsi(closes: list[float], n: int = 14) -> str:
    if len(closes) <= n:
        return ""
    gains: list[float] = []
    losses: list[float] = []
    for idx in range(-n, 0):
        diff = closes[idx] - closes[idx - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = avg(gains)
    avg_loss = avg(losses)
    if avg_loss == 0:
        return "100.000000"
    return f"{100 - (100 / (1 + avg_gain / avg_loss)):.6f}"


def technical_row(ticker: str, prices: list[dict[str, float | str]], factor_set: set[str]) -> dict[str, object]:
    closes = [float(row["close"]) for row in prices]
    highs = [float(row["high"]) for row in prices]
    lows = [float(row["low"]) for row in prices]
    volumes = [float(row["volume"]) for row in prices]
    latest = prices[-1]
    close = closes[-1]

    sma10 = avg(closes[-10:])
    sma20 = avg(closes[-20:])
    sma50 = avg(closes[-50:])
    sma200 = avg(closes[-200:]) if len(closes) >= 200 else None
    ret5 = pct(close, closes[-6]) if len(closes) > 5 else ""
    ret20 = pct(close, closes[-21]) if len(closes) > 20 else ""
    dist20 = (close / sma20) - 1.0 if sma20 else 0.0
    dist50 = (close / sma50) - 1.0 if sma50 else 0.0
    rsi14 = rsi(closes)

    last20 = closes[-20:]
    mid = avg(last20)
    stdev = math.sqrt(sum((value - mid) ** 2 for value in last20) / len(last20)) if last20 else 0.0
    upper = mid + 2 * stdev
    lower = mid - 2 * stdev
    pct_b = (close - lower) / (upper - lower) if upper != lower else 0.5
    bandwidth = (upper - lower) / mid if mid else 0.0
    avg5_vol = avg(volumes[-5:])
    avg20_vol = avg(volumes[-20:])
    volume_ratio = avg5_vol / avg20_vol if avg20_vol else 0.0

    if close >= sma20 >= sma50:
        trend = "UPTREND"
    elif close < sma20 < sma50:
        trend = "DOWNTREND"
    else:
        trend = "MIXED"

    if pct_b <= 0.35 and trend in {"UPTREND", "MIXED"}:
        buy_zone = "BUY_ZONE_PULLBACK_REVIEW"
    elif pct_b >= 0.90 or (rsi14 and float(rsi14) >= 70):
        buy_zone = "NOT_BUY_ZONE_OVERHEAT_REVIEW"
    else:
        buy_zone = "NEUTRAL_REVIEW"

    score = 50.0
    if rsi14:
        score += 10 if float(rsi14) < 40 else (-10 if float(rsi14) > 70 else 0)
    score += 10 if pct_b < 0.35 else (-10 if pct_b > 0.90 else 0)
    score += 5 if trend == "UPTREND" else (-5 if trend == "DOWNTREND" else 0)
    score = round(max(0.0, min(100.0, score)), 6)

    if buy_zone == "NOT_BUY_ZONE_OVERHEAT_REVIEW":
        signal = "TECH_TIMING_OVERHEAT_AVOID_CHASE"
    elif buy_zone == "BUY_ZONE_PULLBACK_REVIEW":
        signal = "TECH_TIMING_PULLBACK_WATCH"
    elif trend == "UPTREND":
        signal = "TECH_TIMING_WATCH_POSITIVE"
    else:
        signal = "TECH_TIMING_NEUTRAL_REVIEW"

    return {
        "ticker": ticker,
        "yf_ticker": ticker,
        "price_date": latest["date"],
        "latest_price_date": latest["date"],
        "close": f"{close:.6f}",
        "latest_price": f"{close:.6f}",
        "sma_10": f"{sma10:.6f}",
        "sma_20": f"{sma20:.6f}",
        "sma_50": f"{sma50:.6f}",
        "sma_200": "" if sma200 is None else f"{sma200:.6f}",
        "return_5d": ret5,
        "return_20d": ret20,
        "distance_to_sma20": f"{dist20:.6f}",
        "distance_to_sma50": f"{dist50:.6f}",
        "rsi_14": rsi14,
        "bb_mid_20": f"{mid:.6f}",
        "bb_upper_20_2": f"{upper:.6f}",
        "bb_lower_20_2": f"{lower:.6f}",
        "bb_percent_b": f"{pct_b:.6f}",
        "bb_bandwidth": f"{bandwidth:.6f}",
        "volume_ratio_5_20": f"{volume_ratio:.6f}",
        "trend_status": trend,
        "buy_zone_status": buy_zone,
        "technical_timing_status": "AVAILABLE",
        "technical_status": signal,
        "technical_signal": signal,
        "technical_timing_score": f"{score:.6f}",
        "pullback_status": "BB_LOWER_HALF" if pct_b <= 0.4 else ("BB_UPPER_HALF" if pct_b >= 0.6 else "BB_MID"),
        "overheat_status": "OVERHEAT_REVIEW" if signal == "TECH_TIMING_OVERHEAT_AVOID_CHASE" else "NONE",
        "execution_status": "REVIEW_ONLY",
        "source_stage": "V18_CURRENT_TECHNICAL_TIMING_REPAIR",
        "source_file": rel(PRICE_CACHE / f"{ticker}.csv"),
        "source_universe": rel(UNIVERSE_YAML),
        "factor_pack_alignment": "IN_CURRENT_FACTOR_PACK" if ticker in factor_set else "NOT_IN_CURRENT_FACTOR_PACK",
        "official_decision_impact": "NONE",
        "research_only": "TRUE",
    }


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


def validate(rows: list[dict[str, object]]) -> list[str]:
    blockers: list[str] = []
    if not OUT_TIMING.exists() or OUT_TIMING.stat().st_size <= 0:
        blockers.append("technical_timing_file_missing_or_empty")
    if not rows:
        blockers.append("row_count_zero")
    tickers = [clean(row.get("ticker")).upper() for row in rows]
    if len(tickers) != len(set(tickers)):
        blockers.append("duplicate_ticker")
    if any(not valid_ticker(ticker) for ticker in tickers):
        blockers.append("invalid_ticker")
    if any(to_float(row.get("technical_timing_score")) is None for row in rows):
        blockers.append("missing_or_non_numeric_technical_timing_score")
    for field in ("trend_status", "buy_zone_status", "technical_timing_status"):
        if any(not clean(row.get(field)) for row in rows):
            blockers.append(f"missing_{field}")
            break
    return blockers


def main() -> int:
    generated_at = now_utc()
    tickers = read_tickers(UNIVERSE_YAML)
    factor_set = factor_tickers()
    rows: list[dict[str, object]] = []
    audit: list[dict[str, object]] = []
    for ticker in tickers:
        price_file = PRICE_CACHE / f"{ticker}.csv"
        prices, error = read_price_cache(price_file)
        accepted = len(prices) >= 50
        reason = "" if accepted else (error or f"price_history_rows_{len(prices)}_lt_50")
        audit.append({
            "ticker": ticker,
            "source_universe": rel(UNIVERSE_YAML),
            "source_price_file": rel(price_file),
            "price_file_exists": "TRUE" if price_file.exists() else "FALSE",
            "price_history_row_count": len(prices),
            "accepted_for_technical_timing": "TRUE" if accepted else "FALSE",
            "exclusion_reason": reason,
            "latest_price_date": prices[-1]["date"] if prices else "",
            "factor_pack_alignment": "IN_CURRENT_FACTOR_PACK" if ticker in factor_set else "NOT_IN_CURRENT_FACTOR_PACK",
        })
        if accepted:
            rows.append(technical_row(ticker, prices, factor_set))

    rows.sort(key=lambda row: clean(row.get("ticker")))
    write_csv(OUT_TIMING, rows, FIELDS)
    blockers = validate(rows)
    status = PASS_STATUS if not blockers else BLOCKED_STATUS
    write_csv(OUT_AUDIT, audit, [
        "ticker",
        "source_universe",
        "source_price_file",
        "price_file_exists",
        "price_history_row_count",
        "accepted_for_technical_timing",
        "exclusion_reason",
        "latest_price_date",
        "factor_pack_alignment",
    ])
    status_rows = [{
        "STATUS": status,
        "generated_at_utc": generated_at,
        "selected_generator": rel(Path(__file__)),
        "source_universe": rel(UNIVERSE_YAML),
        "source_price_cache_dir": rel(PRICE_CACHE),
        "source_factor_pack": rel(FACTOR_PACK),
        "input_ticker_count": len(tickers),
        "row_count": len(rows),
        "excluded_ticker_count": len([row for row in audit if row["accepted_for_technical_timing"] != "TRUE"]),
        "timing_path": rel(OUT_TIMING),
        "audit_path": rel(OUT_AUDIT),
        "blocker_reason": ";".join(blockers),
        "research_only": "TRUE",
        "official_recommendation_created": "FALSE",
        "broker_order_execution_connected": "FALSE",
    }]
    write_csv(OUT_STATUS, status_rows, list(status_rows[0].keys()))
    write_text(
        OUT_READ_FIRST,
        "\n".join([
            "V18.6A CURRENT TECHNICAL TIMING REPAIR READ FIRST",
            f"STATUS: {status}",
            f"GENERATED_AT_UTC: {generated_at}",
            f"SELECTED_GENERATOR: {rel(Path(__file__))}",
            f"SOURCE_UNIVERSE: {rel(UNIVERSE_YAML)}",
            f"SOURCE_PRICE_CACHE_DIR: {rel(PRICE_CACHE)}",
            f"SOURCE_FACTOR_PACK: {rel(FACTOR_PACK)}",
            f"INPUT_TICKER_COUNT: {len(tickers)}",
            f"ROW_COUNT: {len(rows)}",
            f"EXCLUDED_TICKER_COUNT: {status_rows[0]['excluded_ticker_count']}",
            f"TIMING_PATH: {rel(OUT_TIMING)}",
            f"AUDIT_PATH: {rel(OUT_AUDIT)}",
            f"BLOCKER_REASON: {status_rows[0]['blocker_reason']}",
            "RESEARCH_ONLY: TRUE",
            "OFFICIAL_RECOMMENDATION_CREATED: FALSE",
            "BROKER_ORDER_EXECUTION_CONNECTED: FALSE",
            "",
        ]),
    )
    print(status)
    print(f"ROW_COUNT={len(rows)}")
    print(f"TIMING_PATH={rel(OUT_TIMING)}")
    if blockers:
        print(f"BLOCKER_REASON={';'.join(blockers)}")
    return 0 if status == PASS_STATUS else 1


if __name__ == "__main__":
    raise SystemExit(main())
