from __future__ import annotations

import csv
import math
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UNIVERSE_YAML = ROOT / "configs" / "v16" / "universe" / "us_full_second_stage_generated.yaml"
PRICE_CACHE = ROOT / "state" / "v18" / "price_cache"
OUT_RANKING = ROOT / "outputs" / "v18" / "factor_pack" / "V18_CURRENT_RAW105_FACTOR_PACK_RANKING.csv"
OUT_AUDIT = ROOT / "outputs" / "v18" / "factor_pack" / "V18_CURRENT_RAW105_FACTOR_PACK_RANKING_SOURCE_AUDIT.csv"
OUT_STATUS = ROOT / "outputs" / "v18" / "factor_pack" / "V18_CURRENT_RAW105_FACTOR_PACK_RANKING_REPAIR_STATUS.csv"
OUT_READ_FIRST = ROOT / "outputs" / "v18" / "read_center" / "V18_CURRENT_RAW105_FACTOR_PACK_RANKING_REPAIR_READ_FIRST.txt"

PASS_STATUS = "PASS_V18_CURRENT_RAW105_FACTOR_PACK_REPAIR"
BLOCKED_STATUS = "BLOCKED_V18_CURRENT_RAW105_FACTOR_PACK_REPAIR"
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)?$")

FIELDS = [
    "factor_pack_rank",
    "ticker",
    "factor_pack_score",
    "latest_price_date",
    "latest_close",
    "ret_5d",
    "ret_20d",
    "ret_60d",
    "ret_120d",
    "volume_ratio_5_20",
    "factor_source",
    "source_universe",
    "source_price_file",
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
    if not token or len(token) > 12:
        return False
    return bool(TICKER_RE.fullmatch(token))


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
            token = line[2:].strip().strip("'\"").upper()
            if valid_ticker(token):
                tickers.append(token)
        elif in_tickers and not raw.startswith((" ", "\t")):
            break
    return sorted(dict.fromkeys(tickers))


def to_float(value: object) -> float | None:
    try:
        text = clean(value).replace(",", "")
        if not text:
            return None
        value_float = float(text)
        if math.isnan(value_float) or math.isinf(value_float):
            return None
        return value_float
    except Exception:
        return None


def read_price_cache(path: Path) -> tuple[list[dict[str, object]], str]:
    if not path.exists():
        return [], "price_cache_file_missing"
    for encoding in ("utf-8-sig", "utf-8", "cp932", "latin-1"):
        try:
            with path.open("r", encoding=encoding, newline="", errors="replace") as handle:
                rows = [dict(row) for row in csv.DictReader(handle)]
            parsed: list[dict[str, object]] = []
            for row in rows:
                date = clean(row.get("date"))[:10]
                close = to_float(row.get("close") or row.get("adj_close"))
                volume = to_float(row.get("volume")) or 0.0
                if date and close is not None:
                    parsed.append({"date": date, "close": close, "volume": volume})
            parsed.sort(key=lambda row: str(row["date"]))
            return parsed, "" if parsed else "no_parseable_price_rows"
        except Exception:
            continue
    return [], "price_cache_parse_failed"


def pct(current: float, previous: float) -> str:
    return "" if previous == 0 else f"{(current / previous) - 1.0:.6f}"


def percentile_score(value: float, lo: float, hi: float, invert: bool = False) -> float:
    score = 50.0 if hi == lo else max(0.0, min(100.0, 100.0 * (value - lo) / (hi - lo)))
    return round(100.0 - score if invert else score, 6)


def factor_row(ticker: str, prices: list[dict[str, object]]) -> dict[str, object]:
    closes = [float(row["close"]) for row in prices]
    volumes = [float(row["volume"]) for row in prices]
    latest = prices[-1]

    def ret(days: int) -> str:
        return pct(closes[-1], closes[-1 - days]) if len(closes) > days else ""

    ret5 = ret(5)
    ret20 = ret(20)
    ret60 = ret(60)
    ret120 = ret(120)
    avg5 = sum(volumes[-5:]) / min(5, len(volumes))
    avg20 = sum(volumes[-20:]) / min(20, len(volumes))
    volume_ratio = round(avg5 / avg20, 6) if avg20 else ""
    mom60 = float(ret60) if ret60 else 0.0
    mom120 = float(ret120) if ret120 else 0.0
    pullback = -float(ret5) if ret5 and mom60 > 0 else 0.0
    composite = (
        0.45 * percentile_score(mom60, -0.5, 0.8)
        + 0.35 * percentile_score(mom120, -0.8, 1.5)
        + 0.20 * percentile_score(pullback, -0.1, 0.2)
    )
    return {
        "factor_pack_rank": "",
        "ticker": ticker,
        "factor_pack_score": f"{round(composite, 6):.6f}",
        "latest_price_date": latest["date"],
        "latest_close": latest["close"],
        "ret_5d": ret5,
        "ret_20d": ret20,
        "ret_60d": ret60,
        "ret_120d": ret120,
        "volume_ratio_5_20": volume_ratio,
        "factor_source": "LOCAL_V18_PRICE_CACHE_FACTOR_REPAIR",
        "source_universe": rel(UNIVERSE_YAML),
        "source_price_file": rel(PRICE_CACHE / f"{ticker}.csv"),
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


def validate_rows(rows: list[dict[str, object]]) -> list[str]:
    blockers: list[str] = []
    if not OUT_RANKING.exists() or OUT_RANKING.stat().st_size <= 0:
        blockers.append("ranking_file_missing_or_empty")
    if not rows:
        blockers.append("row_count_zero")
    tickers = [clean(row.get("ticker")).upper() for row in rows]
    if any(not valid_ticker(ticker) for ticker in tickers):
        blockers.append("invalid_ticker_value")
    if len(tickers) != len(set(tickers)):
        blockers.append("duplicate_ticker")
    if any(to_float(row.get("factor_pack_score")) is None for row in rows):
        blockers.append("missing_or_non_numeric_factor_pack_score")
    if any(to_float(row.get("factor_pack_rank")) is None for row in rows):
        blockers.append("missing_or_non_numeric_factor_pack_rank")
    return blockers


def main() -> int:
    generated_at = now_utc()
    tickers = read_tickers(UNIVERSE_YAML)
    audit_rows: list[dict[str, object]] = []
    factor_rows: list[dict[str, object]] = []

    for ticker in tickers:
        price_file = PRICE_CACHE / f"{ticker}.csv"
        prices, error = read_price_cache(price_file)
        accepted = len(prices) >= 121
        reason = "" if accepted else (error or f"price_history_rows_{len(prices)}_lt_121")
        audit_rows.append({
            "ticker": ticker,
            "source_universe": rel(UNIVERSE_YAML),
            "source_price_file": rel(price_file),
            "price_file_exists": "TRUE" if price_file.exists() else "FALSE",
            "price_history_row_count": len(prices),
            "accepted_for_factor_pack": "TRUE" if accepted else "FALSE",
            "exclusion_reason": reason,
            "latest_price_date": prices[-1]["date"] if prices else "",
        })
        if accepted:
            factor_rows.append(factor_row(ticker, prices))

    factor_rows.sort(key=lambda row: (-(to_float(row.get("factor_pack_score")) or -1.0), clean(row.get("ticker"))))
    for idx, row in enumerate(factor_rows, start=1):
        row["factor_pack_rank"] = idx

    write_csv(OUT_RANKING, factor_rows, FIELDS)
    blockers = validate_rows(factor_rows)
    status = PASS_STATUS if not blockers else BLOCKED_STATUS
    write_csv(OUT_AUDIT, audit_rows, [
        "ticker",
        "source_universe",
        "source_price_file",
        "price_file_exists",
        "price_history_row_count",
        "accepted_for_factor_pack",
        "exclusion_reason",
        "latest_price_date",
    ])
    status_rows = [{
        "STATUS": status,
        "generated_at_utc": generated_at,
        "selected_generator": rel(Path(__file__)),
        "source_universe": rel(UNIVERSE_YAML),
        "source_price_cache_dir": rel(PRICE_CACHE),
        "input_ticker_count": len(tickers),
        "row_count": len(factor_rows),
        "excluded_ticker_count": len([row for row in audit_rows if row["accepted_for_factor_pack"] != "TRUE"]),
        "ranking_path": rel(OUT_RANKING),
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
            "V18 CURRENT RAW105 FACTOR PACK REPAIR READ FIRST",
            f"STATUS: {status}",
            f"GENERATED_AT_UTC: {generated_at}",
            f"SELECTED_GENERATOR: {rel(Path(__file__))}",
            f"SOURCE_UNIVERSE: {rel(UNIVERSE_YAML)}",
            f"SOURCE_PRICE_CACHE_DIR: {rel(PRICE_CACHE)}",
            f"INPUT_TICKER_COUNT: {len(tickers)}",
            f"ROW_COUNT: {len(factor_rows)}",
            f"EXCLUDED_TICKER_COUNT: {status_rows[0]['excluded_ticker_count']}",
            f"RANKING_PATH: {rel(OUT_RANKING)}",
            f"AUDIT_PATH: {rel(OUT_AUDIT)}",
            f"BLOCKER_REASON: {status_rows[0]['blocker_reason']}",
            "RESEARCH_ONLY: TRUE",
            "OFFICIAL_RECOMMENDATION_CREATED: FALSE",
            "BROKER_ORDER_EXECUTION_CONNECTED: FALSE",
            "",
        ]),
    )
    print(status)
    print(f"ROW_COUNT={len(factor_rows)}")
    print(f"RANKING_PATH={rel(OUT_RANKING)}")
    if blockers:
        print(f"BLOCKER_REASON={';'.join(blockers)}")
    return 0 if status == PASS_STATUS else 1


if __name__ == "__main__":
    raise SystemExit(main())
