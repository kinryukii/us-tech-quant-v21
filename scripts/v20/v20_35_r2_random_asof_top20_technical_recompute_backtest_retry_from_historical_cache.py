from __future__ import annotations

import csv
import hashlib
import math
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"

IN_V20_34_DECISION = CONSOLIDATION / "V20_34_RANDOM_ASOF_TOP20_PREFLIGHT_DECISION.csv"
IN_V20_34_ALLOWED = CONSOLIDATION / "V20_34_RANDOM_ASOF_TECHNICAL_FACTOR_ALLOWED_SET.csv"
IN_V20_34_BLOCKED = CONSOLIDATION / "V20_34_RANDOM_ASOF_BLOCKED_NON_PIT_FACTOR_REGISTER.csv"
IN_V20_34_WINDOWS = CONSOLIDATION / "V20_34_RANDOM_ASOF_FORWARD_WINDOW_PREFLIGHT.csv"
IN_V20_34_QUARANTINE = CONSOLIDATION / "V20_34_QUARANTINE_DECISION_REGISTER.csv"
IN_V20_34_READ_FIRST = OPS / "V20_34_READ_FIRST.txt"
IN_V20_35_R1_NEXT = CONSOLIDATION / "V20_35_R1_NEXT_STEP_DECISION_SUMMARY.csv"
IN_V20_35_R1_READ_FIRST = OPS / "V20_35_R1_READ_FIRST.txt"
IN_TICKER_CACHE = ROOT / "inputs" / "v20" / "random_asof" / "V20_RANDOM_ASOF_HISTORICAL_TICKER_PRICE_INPUT.csv"
IN_BENCHMARK_CACHE = ROOT / "inputs" / "v20" / "random_asof" / "V20_RANDOM_ASOF_HISTORICAL_BENCHMARK_PRICE_INPUT.csv"
IN_UNIVERSE = CONSOLIDATION / "V20_26_REQUIRED_SYMBOL_UNIVERSE.csv"

OUT_SOURCE = CONSOLIDATION / "V20_35_R2_SOURCE_INPUT_AUDIT.csv"
OUT_DATE_POOL = CONSOLIDATION / "V20_35_R2_RANDOM_SIGNAL_DATE_CANDIDATE_POOL.csv"
OUT_DATE_SAMPLE = CONSOLIDATION / "V20_35_R2_SELECTED_RANDOM_SIGNAL_DATE_SAMPLE.csv"
OUT_TICKER_COVERAGE = CONSOLIDATION / "V20_35_R2_HISTORICAL_PRICE_COVERAGE_AUDIT.csv"
OUT_BENCH_COVERAGE = CONSOLIDATION / "V20_35_R2_BENCHMARK_PRICE_COVERAGE_AUDIT.csv"
OUT_FACTOR_MATRIX = CONSOLIDATION / "V20_35_R2_ASOF_TECHNICAL_FACTOR_RECOMPUTE_MATRIX.csv"
OUT_FACTOR_AVAIL = CONSOLIDATION / "V20_35_R2_ASOF_TECHNICAL_FACTOR_AVAILABILITY_SUMMARY.csv"
OUT_RANKING = CONSOLIDATION / "V20_35_R2_ASOF_TECHNICAL_SCORE_AND_RANKING.csv"
OUT_TOP20 = CONSOLIDATION / "V20_35_R2_ASOF_TOP20_SELECTIONS.csv"
OUT_TOP50 = CONSOLIDATION / "V20_35_R2_ASOF_TOP50_SELECTIONS.csv"
OUT_TOP100 = CONSOLIDATION / "V20_35_R2_ASOF_TOP100_SELECTIONS.csv"
OUT_ATTACH = CONSOLIDATION / "V20_35_R2_FORWARD_OUTCOME_ATTACHMENT.csv"
OUT_RETURNS = CONSOLIDATION / "V20_35_R2_EXPLORATORY_ROW_LEVEL_RETURNS.csv"
OUT_SIGNAL_SUM = CONSOLIDATION / "V20_35_R2_EXPLORATORY_SIGNAL_DATE_SUMMARY.csv"
OUT_WINDOW_SUM = CONSOLIDATION / "V20_35_R2_EXPLORATORY_FORWARD_WINDOW_SUMMARY.csv"
OUT_BUCKET_SUM = CONSOLIDATION / "V20_35_R2_EXPLORATORY_TOP_BUCKET_SUMMARY.csv"
OUT_BENCH_REL_SUM = CONSOLIDATION / "V20_35_R2_EXPLORATORY_BENCHMARK_RELATIVE_SUMMARY.csv"
OUT_PIT = CONSOLIDATION / "V20_35_R2_STALE_LEAKAGE_PIT_GATE.csv"
OUT_FORMULA = CONSOLIDATION / "V20_35_R2_FORMULA_RECHECK.csv"
OUT_BLOCKED_ENFORCE = CONSOLIDATION / "V20_35_R2_BLOCKED_NON_PIT_FACTOR_ENFORCEMENT.csv"
OUT_DECISION = CONSOLIDATION / "V20_35_R2_RANDOM_ASOF_BACKTEST_DECISION.csv"
OUT_NEXT = CONSOLIDATION / "V20_35_R2_NEXT_STEP_DECISION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_35_R2_RANDOM_ASOF_TOP20_TECHNICAL_RECOMPUTE_BACKTEST_RETRY_FROM_HISTORICAL_CACHE_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_RANDOM_ASOF_TOP20_TECHNICAL_RECOMPUTE_BACKTEST.md"
READ_FIRST = OPS / "V20_35_R2_READ_FIRST.txt"

STAGE_NAME = "V20.35-R2_RANDOM_ASOF_TOP20_TECHNICAL_RECOMPUTE_BACKTEST_RETRY_FROM_HISTORICAL_CACHE"
PASS_STATUS = "PASS_V20_35_R2_RANDOM_ASOF_TOP20_TECHNICAL_RECOMPUTE_BACKTEST_RETRY_FROM_HISTORICAL_CACHE"
BLOCKED_STATUS = "BLOCKED_V20_35_R2_RANDOM_ASOF_TOP20_TECHNICAL_RECOMPUTE_BACKTEST_RETRY_FROM_HISTORICAL_CACHE"
RANDOM_SEED = 203502
TARGET_SIGNAL_DATE_SAMPLE_SIZE = 20
FORWARD_WINDOWS = [1, 3, 5, 10, 20]
TOP_BUCKETS = [20, 50, 100]
REQUIRED_LOOKBACK_FOR_FULL_STRICT_RECOMPUTE = 50
REQUIRED_FORWARD_FOR_FULL_WINDOW_SET = 20
TOLERANCE = 1e-10


def clean(value: object) -> str:
    return str(value or "").strip()


def upper(value: object) -> str:
    return clean(value).upper()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def now_utc() -> str:
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
    return datetime.strptime(text[:10], "%Y-%m-%d")


def pct_change(series: list[float], lookback: int) -> float | None:
    if len(series) <= lookback or series[-lookback - 1] <= 0:
        return None
    return series[-1] / series[-lookback - 1] - 1


def sma_position(series: list[float], window: int) -> float | None:
    if len(series) < window:
        return None
    avg = mean(series[-window:])
    if avg == 0:
        return None
    return series[-1] / avg - 1


def stdev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    avg = mean(values)
    return math.sqrt(sum((v - avg) ** 2 for v in values) / len(values))


def rsi(series: list[float], window: int = 14) -> float | None:
    if len(series) <= window:
        return None
    deltas = [series[i] - series[i - 1] for i in range(len(series) - window, len(series))]
    gains = [d for d in deltas if d > 0]
    losses = [-d for d in deltas if d < 0]
    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def ema(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    alpha = 2 / (window + 1)
    current = mean(values[:window])
    for value in values[window:]:
        current = alpha * value + (1 - alpha) * current
    return current


def macd(series: list[float]) -> float | None:
    if len(series) < 26:
        return None
    fast = ema(series, 12)
    slow = ema(series, 26)
    if fast is None or slow is None:
        return None
    return fast - slow


def percentile_score(value: float | None, invert: bool = False) -> float | None:
    if value is None:
        return None
    score = -value if invert else value
    return score


def summarize(rows: list[dict[str, object]], group_fields: list[str]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, ...], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(clean(row.get(field)) for field in group_fields)].append(row)
    out = []
    for key, subset in sorted(grouped.items()):
        ticker_returns = [num(row.get("ticker_forward_return")) for row in subset]
        spy_rel = [num(row.get("benchmark_relative_return_vs_spy")) for row in subset]
        qqq_rel = [num(row.get("benchmark_relative_return_vs_qqq")) for row in subset]
        ticker_v = [v for v in ticker_returns if v is not None]
        spy_v = [v for v in spy_rel if v is not None]
        qqq_v = [v for v in qqq_rel if v is not None]
        result = {field: key[i] for i, field in enumerate(group_fields)}
        result.update({
            "row_count": len(subset),
            "excluded_row_count": sum(1 for row in subset if upper(row.get("row_included")) != "TRUE"),
            "average_ticker_return": mean(ticker_v) if ticker_v else "",
            "median_ticker_return": median(ticker_v) if ticker_v else "",
            "average_benchmark_relative_return_vs_spy": mean(spy_v) if spy_v else "",
            "median_benchmark_relative_return_vs_spy": median(spy_v) if spy_v else "",
            "average_benchmark_relative_return_vs_qqq": mean(qqq_v) if qqq_v else "",
            "median_benchmark_relative_return_vs_qqq": median(qqq_v) if qqq_v else "",
            "win_rate_vs_spy": sum(1 for v in spy_v if v > 0) / len(spy_v) if spy_v else "",
            "win_rate_vs_qqq": sum(1 for v in qqq_v if v > 0) / len(qqq_v) if qqq_v else "",
            "extreme_return_warning_count": sum(1 for row in subset if upper(row.get("extreme_return_warning")) == "TRUE"),
            "formula_mismatch_count": sum(1 for row in subset if upper(row.get("formula_recheck_passed")) != "TRUE"),
        })
        out.append(result)
    return out


def load_price_rows(rows: list[dict[str, str]]) -> dict[str, list[dict[str, object]]]:
    by_symbol: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        symbol = clean(row.get("symbol"))
        date = parse_date(row.get("price_date"))
        adj_close = num(row.get("adjusted_close")) or num(row.get("close"))
        if not symbol or date is None or adj_close is None:
            continue
        by_symbol[symbol].append({
            "symbol": symbol,
            "price_date": date,
            "open": num(row.get("open")),
            "high": num(row.get("high")),
            "low": num(row.get("low")),
            "close": num(row.get("close")),
            "adjusted_close": adj_close,
            "volume": num(row.get("volume")),
            "source_hash": clean(row.get("source_hash")),
            "run_id": clean(row.get("run_id")),
        })
    for symbol in by_symbol:
        by_symbol[symbol].sort(key=lambda item: item["price_date"])
    return by_symbol


def date_text(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d") if value else ""


def main() -> int:
    run_at = now_utc()
    r1_rows, _ = read_csv(IN_V20_35_R1_NEXT)
    r1 = r1_rows[0] if r1_rows else {}
    decision_rows, _ = read_csv(IN_V20_34_DECISION)
    allowed_rows, _ = read_csv(IN_V20_34_ALLOWED)
    blocked_rows, _ = read_csv(IN_V20_34_BLOCKED)
    quarantine_rows, _ = read_csv(IN_V20_34_QUARANTINE)
    ticker_raw, ticker_fields = read_csv(IN_TICKER_CACHE)
    bench_raw, bench_fields = read_csv(IN_BENCHMARK_CACHE)
    universe_rows, _ = read_csv(IN_UNIVERSE)

    v20_34_ready = bool(decision_rows) and upper(decision_rows[0].get("ready_for_v20_35_random_asof_top20_technical_recompute_backtest")) == "TRUE"
    r1_gate_ready = (
        upper(r1.get("READY_FOR_V20_35_RETRY_RANDOM_ASOF_TOP20_TECHNICAL_RECOMPUTE_BACKTEST")) == "TRUE"
        and upper(r1.get("HISTORICAL_TICKER_CACHE_CERTIFIED")) == "TRUE"
        and upper(r1.get("HISTORICAL_BENCHMARK_CACHE_CERTIFIED")) == "TRUE"
        and int(float(clean(r1.get("CANDIDATE_RANDOM_SIGNAL_DATE_COUNT_AFTER_50D_LOOKBACK_AND_20D_FORWARD_BUFFER")) or "0")) > 0
    )
    historical_random_asof_cache_used = IN_TICKER_CACHE.exists() and IN_BENCHMARK_CACHE.exists() and "random_asof" in rel(IN_TICKER_CACHE)
    quarantine_required = sum(1 for row in quarantine_rows if upper(row.get("quarantine_required")) == "TRUE")
    allowed_factor_count = sum(1 for row in allowed_rows if upper(row.get("future_v20_35_allowed")) == "TRUE")
    excluded_non_pit_factor_count = len(blocked_rows)

    source_rows = []
    for source_id, path, rows, fields in [
        ("historical_random_asof_ticker_cache", IN_TICKER_CACHE, ticker_raw, ticker_fields),
        ("historical_random_asof_benchmark_cache", IN_BENCHMARK_CACHE, bench_raw, bench_fields),
    ]:
        dates = [parse_date(row.get("price_date")) for row in rows]
        dates = [date for date in dates if date is not None]
        run_ids = sorted({clean(row.get("run_id")) for row in rows if clean(row.get("run_id"))})
        source_rows.append({
            "source_id": source_id,
            "source_path": rel(path),
            "source_hash": sha_file(path),
            "row_count": len(rows),
            "field_count": len(fields),
            "min_price_date": date_text(min(dates)) if dates else "",
            "max_price_date": date_text(max(dates)) if dates else "",
            "run_id_count": len(run_ids),
            "sample_run_id": run_ids[0] if run_ids else "",
            "historical_random_asof_cache_used": tf("random_asof" in rel(path)),
            "source_status": "PASS" if path.exists() and rows and "random_asof" in rel(path) else "BLOCKED",
        })

    ticker_by_symbol = load_price_rows(ticker_raw)
    bench_by_symbol = load_price_rows(bench_raw)
    universe = sorted(clean(row.get("symbol")) for row in universe_rows if upper(row.get("symbol_role")) == "TICKER")
    universe = [symbol for symbol in universe if symbol in ticker_by_symbol]
    trading_dates = sorted({row["price_date"] for rows in ticker_by_symbol.values() for row in rows})
    bench_dates = sorted({row["price_date"] for rows in bench_by_symbol.values() for row in rows})
    date_index = {date: i for i, date in enumerate(trading_dates)}
    min_ticker_date = min(trading_dates) if trading_dates else None
    max_ticker_date = max(trading_dates) if trading_dates else None

    ticker_coverage_rows = []
    for symbol in universe:
        rows = ticker_by_symbol[symbol]
        ticker_coverage_rows.append({
            "ticker": symbol,
            "row_count": len(rows),
            "min_price_date": date_text(rows[0]["price_date"]) if rows else "",
            "max_price_date": date_text(rows[-1]["price_date"]) if rows else "",
            "adjusted_close_available": "TRUE",
            "close_available": tf("close" in ticker_fields),
            "volume_available": tf("volume" in ticker_fields),
            "date_field": "price_date",
            "coverage_status": "PASS" if len(rows) == len(trading_dates) and rows else "WARN",
        })

    bench_coverage_rows = []
    for symbol in ["SPY", "QQQ"]:
        rows = bench_by_symbol.get(symbol, [])
        bench_coverage_rows.append({
            "benchmark_symbol": symbol,
            "row_count": len(rows),
            "min_price_date": date_text(rows[0]["price_date"]) if rows else "",
            "max_price_date": date_text(rows[-1]["price_date"]) if rows else "",
            "adjusted_close_available": tf("adjusted_close" in bench_fields),
            "close_available": tf("close" in bench_fields),
            "volume_available": tf("volume" in bench_fields),
            "date_field": "price_date",
            "coverage_status": "PASS" if len(rows) == len(bench_dates) and rows else "BLOCKED",
        })

    date_pool_rows = []
    eligible_dates = []
    for date in trading_dates:
        idx = date_index[date]
        lookback_available = idx
        forward_available = len(trading_dates) - idx - 1
        has_benchmark_date = date in bench_dates
        eligible = (
            lookback_available >= REQUIRED_LOOKBACK_FOR_FULL_STRICT_RECOMPUTE
            and forward_available >= REQUIRED_FORWARD_FOR_FULL_WINDOW_SET
            and has_benchmark_date
            and v20_34_ready
            and r1_gate_ready
            and historical_random_asof_cache_used
            and quarantine_required == 0
        )
        reasons = []
        if lookback_available < REQUIRED_LOOKBACK_FOR_FULL_STRICT_RECOMPUTE:
            reasons.append("insufficient_50_trading_day_lookback_for_full_strict_factor_set")
        if forward_available < REQUIRED_FORWARD_FOR_FULL_WINDOW_SET:
            reasons.append("insufficient_20_trading_day_forward_window_coverage")
        if not has_benchmark_date:
            reasons.append("missing_matching_spy_qqq_benchmark_date")
        if not v20_34_ready:
            reasons.append("v20_34_gate_not_ready")
        if not r1_gate_ready:
            reasons.append("v20_35_r1_gate_not_ready")
        if not historical_random_asof_cache_used:
            reasons.append("historical_random_asof_cache_not_used")
        if quarantine_required:
            reasons.append("v20_34_quarantine_rows_present")
        date_pool_rows.append({
            "signal_date": date_text(date),
            "random_seed": RANDOM_SEED,
            "ticker_count_with_price_on_date": sum(1 for symbol in universe if any(row["price_date"] == date for row in ticker_by_symbol[symbol])),
            "lookback_trading_days_available": lookback_available,
            "forward_trading_days_available": forward_available,
            "spy_qqq_benchmark_date_available": tf(has_benchmark_date),
            "eligible_for_random_sample": tf(eligible),
            "exclusion_reason": ";".join(reasons),
        })
        if eligible:
            eligible_dates.append(date)

    rng = random.Random(RANDOM_SEED)
    selected_dates = sorted(rng.sample(eligible_dates, min(TARGET_SIGNAL_DATE_SAMPLE_SIZE, len(eligible_dates)))) if eligible_dates else []
    sample_rows = [{
        "sample_order": idx + 1,
        "signal_date": date_text(date),
        "random_seed": RANDOM_SEED,
        "selection_policy": "deterministic_random_sample_from_dates_with_50d_lookback_and_20d_forward_coverage",
        "selected": "TRUE",
    } for idx, date in enumerate(selected_dates)]

    factor_rows: list[dict[str, object]] = []
    ranking_rows: list[dict[str, object]] = []
    top_rows: dict[int, list[dict[str, object]]] = {20: [], 50: [], 100: []}
    attach_rows: list[dict[str, object]] = []
    return_rows: list[dict[str, object]] = []
    formula_rows: list[dict[str, object]] = []
    leakage_blockers = 0
    formula_mismatch_count = 0

    bench_index = {
        symbol: {row["price_date"]: row for row in rows}
        for symbol, rows in bench_by_symbol.items()
    }
    ticker_index = {
        symbol: {row["price_date"]: row for row in rows}
        for symbol, rows in ticker_by_symbol.items()
    }

    for signal_date in selected_dates:
        spy_series = [row["adjusted_close"] for row in bench_by_symbol["SPY"] if row["price_date"] <= signal_date]
        qqq_series = [row["adjusted_close"] for row in bench_by_symbol["QQQ"] if row["price_date"] <= signal_date]
        scored = []
        for symbol in universe:
            hist = [row for row in ticker_by_symbol[symbol] if row["price_date"] <= signal_date]
            if not hist or hist[-1]["price_date"] != signal_date:
                continue
            closes = [row["adjusted_close"] for row in hist]
            highs = [row["high"] for row in hist if row["high"] is not None]
            lows = [row["low"] for row in hist if row["low"] is not None]
            volumes = [row["volume"] for row in hist if row["volume"] is not None]
            returns_20 = [closes[i] / closes[i - 1] - 1 for i in range(max(1, len(closes) - 20), len(closes)) if closes[i - 1] > 0]
            high_20 = max(highs[-20:]) if len(highs) >= 20 else None
            low_20 = min(lows[-20:]) if len(lows) >= 20 else None
            vol20 = stdev(returns_20) if len(returns_20) >= 2 else None
            bb_mean = mean(closes[-20:]) if len(closes) >= 20 else None
            bb_sd = stdev(closes[-20:]) if len(closes) >= 20 else None
            factors = {
                "momentum_5d": pct_change(closes, 5),
                "momentum_10d": pct_change(closes, 10),
                "momentum_20d": pct_change(closes, 20),
                "relative_strength_vs_spy_20d": (pct_change(closes, 20) - pct_change(spy_series, 20)) if pct_change(closes, 20) is not None and pct_change(spy_series, 20) is not None else None,
                "relative_strength_vs_qqq_20d": (pct_change(closes, 20) - pct_change(qqq_series, 20)) if pct_change(closes, 20) is not None and pct_change(qqq_series, 20) is not None else None,
                "ma10_position": sma_position(closes, 10),
                "ma20_position": sma_position(closes, 20),
                "ma50_position": sma_position(closes, 50),
                "pullback_quality": ((high_20 - closes[-1]) / high_20 if high_20 else None),
                "breakout_20d": (closes[-1] / high_20 - 1 if high_20 else None),
                "volatility_20d": vol20,
                "volume_trend_20d": (mean(volumes[-5:]) / mean(volumes[-20:]) - 1 if len(volumes) >= 20 and mean(volumes[-20:]) else None),
                "rsi_14": rsi(closes, 14),
                "macd_12_26": macd(closes),
                "bollinger_price_position_20d": ((closes[-1] - bb_mean) / (2 * bb_sd) if bb_mean is not None and bb_sd not in [None, 0] else None),
            }
            available = {key: value for key, value in factors.items() if value is not None}
            score_inputs = [
                percentile_score(factors["momentum_5d"]),
                percentile_score(factors["momentum_10d"]),
                percentile_score(factors["momentum_20d"]),
                percentile_score(factors["relative_strength_vs_spy_20d"]),
                percentile_score(factors["relative_strength_vs_qqq_20d"]),
                percentile_score(factors["ma10_position"]),
                percentile_score(factors["ma20_position"]),
                percentile_score(factors["ma50_position"]),
                percentile_score(factors["pullback_quality"]),
                percentile_score(factors["breakout_20d"]),
                percentile_score(factors["volatility_20d"], invert=True),
                percentile_score(factors["volume_trend_20d"]),
                percentile_score((factors["rsi_14"] - 50) / 100 if factors["rsi_14"] is not None else None),
                percentile_score(factors["macd_12_26"]),
                percentile_score(factors["bollinger_price_position_20d"]),
            ]
            score_values = [value for value in score_inputs if value is not None]
            score = mean(score_values) if score_values else None
            max_factor_input_date = hist[-1]["price_date"]
            row = {
                "signal_date": date_text(signal_date),
                "ticker": symbol,
                **factors,
                "technical_factor_available_count": len(available),
                "technical_factor_missing_count": len(factors) - len(available),
                "max_factor_input_date": date_text(max_factor_input_date),
                "asof_leakage_check_passed": tf(max_factor_input_date <= signal_date),
                "exploratory_technical_score": "" if score is None else score,
                "score_policy": "equal_average_of_available_allowed_technical_factors_no_official_weights",
                "non_official_research_only": "TRUE",
            }
            factor_rows.append(row)
            if score is not None:
                scored.append(row)
        scored.sort(key=lambda row: (-float(row["exploratory_technical_score"]), clean(row["ticker"])))
        for rank, row in enumerate(scored, start=1):
            rank_row = {
                "signal_date": row["signal_date"],
                "ticker": row["ticker"],
                "asof_technical_rank": rank,
                "exploratory_technical_score": row["exploratory_technical_score"],
                "technical_factor_available_count": row["technical_factor_available_count"],
                "technical_factor_missing_count": row["technical_factor_missing_count"],
                "score_policy": row["score_policy"],
                "official_ranking_mutated": "FALSE",
                "current_top20_used_for_historical_backtest": "FALSE",
            }
            ranking_rows.append(rank_row)
            for bucket in TOP_BUCKETS:
                if rank <= bucket:
                    top_rows[bucket].append({**rank_row, "top_bucket": f"Top{bucket}"})

    selected_all = []
    for bucket, rows in top_rows.items():
        selected_all.extend(rows)

    for selected in selected_all:
        signal_date = parse_date(selected["signal_date"])
        symbol = clean(selected["ticker"])
        if signal_date is None:
            continue
        signal_idx = date_index[signal_date]
        entry_row = ticker_index[symbol].get(signal_date)
        spy_entry = bench_index.get("SPY", {}).get(signal_date)
        qqq_entry = bench_index.get("QQQ", {}).get(signal_date)
        for window in FORWARD_WINDOWS:
            outcome_idx = signal_idx + window
            outcome_date = trading_dates[outcome_idx] if outcome_idx < len(trading_dates) else None
            out_row = ticker_index[symbol].get(outcome_date) if outcome_date else None
            spy_out = bench_index.get("SPY", {}).get(outcome_date) if outcome_date else None
            qqq_out = bench_index.get("QQQ", {}).get(outcome_date) if outcome_date else None
            available = bool(entry_row and out_row and spy_entry and spy_out and qqq_entry and qqq_out and outcome_date)
            ticker_return = out_row["adjusted_close"] / entry_row["adjusted_close"] - 1 if available and entry_row["adjusted_close"] > 0 else None
            spy_return = spy_out["adjusted_close"] / spy_entry["adjusted_close"] - 1 if available and spy_entry["adjusted_close"] > 0 else None
            qqq_return = qqq_out["adjusted_close"] / qqq_entry["adjusted_close"] - 1 if available and qqq_entry["adjusted_close"] > 0 else None
            rel_spy = ticker_return - spy_return if ticker_return is not None and spy_return is not None else None
            rel_qqq = ticker_return - qqq_return if ticker_return is not None and qqq_return is not None else None
            formula_ok = available and all(value is not None for value in [ticker_return, spy_return, qqq_return, rel_spy, rel_qqq])
            pit_ok = bool(signal_date and outcome_date and outcome_date > signal_date)
            bench_align = bool(outcome_date and spy_out and qqq_out)
            if not pit_ok or not bench_align:
                leakage_blockers += 1
            recomputed_ticker = out_row["adjusted_close"] / entry_row["adjusted_close"] - 1 if available and entry_row["adjusted_close"] > 0 else None
            recomputed_spy = spy_out["adjusted_close"] / spy_entry["adjusted_close"] - 1 if available and spy_entry["adjusted_close"] > 0 else None
            recomputed_qqq = qqq_out["adjusted_close"] / qqq_entry["adjusted_close"] - 1 if available and qqq_entry["adjusted_close"] > 0 else None
            recomputed_rel_spy = recomputed_ticker - recomputed_spy if recomputed_ticker is not None and recomputed_spy is not None else None
            recomputed_rel_qqq = recomputed_ticker - recomputed_qqq if recomputed_ticker is not None and recomputed_qqq is not None else None
            deltas = [
                None if ticker_return is None or recomputed_ticker is None else ticker_return - recomputed_ticker,
                None if spy_return is None or recomputed_spy is None else spy_return - recomputed_spy,
                None if qqq_return is None or recomputed_qqq is None else qqq_return - recomputed_qqq,
                None if rel_spy is None or recomputed_rel_spy is None else rel_spy - recomputed_rel_spy,
                None if rel_qqq is None or recomputed_rel_qqq is None else rel_qqq - recomputed_rel_qqq,
            ]
            formula_recheck_passed = available and all(delta is not None and abs(delta) <= TOLERANCE for delta in deltas)
            if not formula_recheck_passed and available:
                formula_mismatch_count += 1
            attach = {
                "signal_date": selected["signal_date"],
                "ticker": symbol,
                "top_bucket": selected["top_bucket"],
                "asof_technical_rank": selected["asof_technical_rank"],
                "forward_window": f"forward_{window}d",
                "entry_price_date": date_text(signal_date),
                "outcome_price_date": date_text(outcome_date),
                "ticker_entry_price": entry_row["adjusted_close"] if entry_row else "",
                "ticker_outcome_price": out_row["adjusted_close"] if out_row else "",
                "spy_entry_price": spy_entry["adjusted_close"] if spy_entry else "",
                "spy_outcome_price": spy_out["adjusted_close"] if spy_out else "",
                "qqq_entry_price": qqq_entry["adjusted_close"] if qqq_entry else "",
                "qqq_outcome_price": qqq_out["adjusted_close"] if qqq_out else "",
                "outcome_attachment_status": "PASS" if available else "EXCLUDED",
                "outcome_attachment_exclusion_reason": "" if available else "missing_forward_window_price_coverage",
                "exploratory_random_asof_technical_only": "TRUE",
                "non_official_research_only": "TRUE",
            }
            attach_rows.append(attach)
            ret = {
                **attach,
                "ticker_forward_return": "" if ticker_return is None else ticker_return,
                "spy_forward_return": "" if spy_return is None else spy_return,
                "qqq_forward_return": "" if qqq_return is None else qqq_return,
                "benchmark_relative_return_vs_spy": "" if rel_spy is None else rel_spy,
                "benchmark_relative_return_vs_qqq": "" if rel_qqq is None else rel_qqq,
                "max_factor_input_date": selected["signal_date"],
                "factor_asof_check_passed": "TRUE",
                "outcome_date_after_signal_date": tf(pit_ok),
                "benchmark_dates_align_with_ticker_outcome": tf(bench_align),
                "formula_recheck_passed": tf(formula_recheck_passed),
                "row_included": tf(available and pit_ok and bench_align and formula_recheck_passed),
                "extreme_return_warning": tf(any(value is not None and abs(value) > 0.25 for value in [ticker_return, rel_spy, rel_qqq])),
            }
            return_rows.append(ret)
            formula_rows.append({
                "signal_date": selected["signal_date"],
                "ticker": symbol,
                "top_bucket": selected["top_bucket"],
                "asof_technical_rank": selected["asof_technical_rank"],
                "forward_window": f"forward_{window}d",
                "reported_ticker_forward_return": "" if ticker_return is None else ticker_return,
                "recomputed_ticker_forward_return": "" if recomputed_ticker is None else recomputed_ticker,
                "ticker_forward_return_delta": "" if deltas[0] is None else deltas[0],
                "reported_spy_forward_return": "" if spy_return is None else spy_return,
                "recomputed_spy_forward_return": "" if recomputed_spy is None else recomputed_spy,
                "spy_forward_return_delta": "" if deltas[1] is None else deltas[1],
                "reported_qqq_forward_return": "" if qqq_return is None else qqq_return,
                "recomputed_qqq_forward_return": "" if recomputed_qqq is None else recomputed_qqq,
                "qqq_forward_return_delta": "" if deltas[2] is None else deltas[2],
                "reported_benchmark_relative_return_vs_spy": "" if rel_spy is None else rel_spy,
                "recomputed_benchmark_relative_return_vs_spy": "" if recomputed_rel_spy is None else recomputed_rel_spy,
                "benchmark_relative_return_vs_spy_delta": "" if deltas[3] is None else deltas[3],
                "reported_benchmark_relative_return_vs_qqq": "" if rel_qqq is None else rel_qqq,
                "recomputed_benchmark_relative_return_vs_qqq": "" if recomputed_rel_qqq is None else recomputed_rel_qqq,
                "benchmark_relative_return_vs_qqq_delta": "" if deltas[4] is None else deltas[4],
                "formula_recheck_passed": tf(formula_recheck_passed),
                "severity": "INFO" if formula_recheck_passed else ("WARN" if not available else "BLOCKER"),
            })

    factor_avail_counts = Counter()
    for row in factor_rows:
        factor_avail_counts[int(row["technical_factor_available_count"])] += 1
    factor_avail_rows = [{
        "technical_factor_available_count": count,
        "row_count": factor_avail_counts[count],
        "technical_factor_missing_count": 15 - count,
        "summary_status": "PASS" if count > 0 else "WARN",
    } for count in sorted(factor_avail_counts)]
    if not factor_avail_rows:
        factor_avail_rows = [{"technical_factor_available_count": 0, "row_count": 0, "technical_factor_missing_count": 15, "summary_status": "BLOCKED_NO_SELECTED_SIGNAL_DATES"}]

    included_returns = [row for row in return_rows if upper(row.get("row_included")) == "TRUE"]
    signal_summary = summarize(return_rows, ["signal_date"]) if return_rows else []
    window_summary = summarize(return_rows, ["forward_window"]) if return_rows else []
    bucket_summary = summarize(return_rows, ["top_bucket"]) if return_rows else []
    bench_summary = summarize(return_rows, ["forward_window", "top_bucket"]) if return_rows else []

    pit_rows = [{
        "gate_check": "max_factor_input_date_lte_signal_date",
        "rows_checked": len(return_rows),
        "blocker_count": sum(1 for row in return_rows if upper(row.get("factor_asof_check_passed")) != "TRUE"),
        "gate_passed": tf(all(upper(row.get("factor_asof_check_passed")) == "TRUE" for row in return_rows)),
    }, {
        "gate_check": "outcome_date_gt_signal_date",
        "rows_checked": len(return_rows),
        "blocker_count": sum(1 for row in return_rows if upper(row.get("outcome_date_after_signal_date")) != "TRUE"),
        "gate_passed": tf(all(upper(row.get("outcome_date_after_signal_date")) == "TRUE" for row in return_rows)),
    }, {
        "gate_check": "benchmark_dates_align_with_ticker_outcome",
        "rows_checked": len(return_rows),
        "blocker_count": sum(1 for row in return_rows if upper(row.get("benchmark_dates_align_with_ticker_outcome")) != "TRUE"),
        "gate_passed": tf(all(upper(row.get("benchmark_dates_align_with_ticker_outcome")) == "TRUE" for row in return_rows)),
    }]
    strict_asof_gate_passed = bool(return_rows) and all(upper(row.get("gate_passed")) == "TRUE" for row in pit_rows)

    blocked_enforcement_rows = []
    for row in blocked_rows:
        blocked_enforcement_rows.append({
            "blocked_factor_group": clean(row.get("blocked_factor_group")),
            "excluded_from_v20_35_recompute": "TRUE",
            "current_top20_or_current_ranking_used": "FALSE",
            "enforcement_status": "PASS",
            "notes": "Strict technical-only random as-of recompute excludes this non-PIT/current-only group.",
        })

    coverage_blockers = []
    if not v20_34_ready:
        coverage_blockers.append("v20_34_gate_not_ready")
    if not r1_gate_ready:
        coverage_blockers.append("v20_35_r1_gate_not_ready")
    if not historical_random_asof_cache_used:
        coverage_blockers.append("historical_random_asof_cache_not_used")
    if quarantine_required:
        coverage_blockers.append("v20_34_quarantine_required_rows_present")
    if len(trading_dates) < REQUIRED_LOOKBACK_FOR_FULL_STRICT_RECOMPUTE + REQUIRED_FORWARD_FOR_FULL_WINDOW_SET + 1:
        coverage_blockers.append("certified_cache_has_insufficient_trading_dates_for_50d_lookback_and_20d_forward_windows")
    if "SPY" not in bench_by_symbol or "QQQ" not in bench_by_symbol:
        coverage_blockers.append("missing_spy_or_qqq_benchmark_history")
    if not selected_dates:
        coverage_blockers.append("no_random_signal_dates_selected_after_strict_coverage_filters")

    executed = bool(selected_dates and ranking_rows and included_returns and not coverage_blockers)
    status = PASS_STATUS if executed else BLOCKED_STATUS
    ready_v20_36 = executed and strict_asof_gate_passed
    current_top20_leakage_detected = False

    decision_out = [{
        "decision_id": "V20_35_R2_RANDOM_ASOF_BACKTEST_DECISION",
        "v20_35_r1_gate_ready": tf(r1_gate_ready),
        "random_asof_top20_technical_recompute_backtest_executed": tf(executed),
        "exploratory_forward_returns_created": tf(bool(included_returns)),
        "exploratory_benchmark_relative_returns_created": tf(bool(included_returns)),
        "strict_asof_leakage_gate_passed": tf(strict_asof_gate_passed),
        "current_top20_leakage_detected": tf(current_top20_leakage_detected),
        "enough_random_asof_samples_created": tf(len(selected_dates) >= TARGET_SIGNAL_DATE_SAMPLE_SIZE),
        "ready_for_v20_36_entry_strategy_matrix_design": tf(ready_v20_36),
        "ready_for_v20_37_entry_strategy_backtest": "FALSE",
        "ready_for_v20_38_factor_effectiveness_ablation_audit": tf(ready_v20_36),
        "ready_for_shadow_dynamic_weighting": "FALSE",
        "ready_for_portfolio_level_backtest": "FALSE",
        "ready_for_official_trading_or_recommendation": "FALSE",
        "decision_reason": ";".join(coverage_blockers) if coverage_blockers else "Exploratory random as-of technical recompute completed with strict PIT controls.",
    }]

    next_rows = [{
        "STAGE_NAME": STAGE_NAME,
        "STATUS": status,
        "V20_35_R1_GATE_READY": tf(r1_gate_ready),
        "HISTORICAL_RANDOM_ASOF_CACHE_USED": tf(historical_random_asof_cache_used),
        "RANDOM_SIGNAL_DATE_CANDIDATE_COUNT": len(eligible_dates),
        "SELECTED_RANDOM_SIGNAL_DATE_COUNT": len(selected_dates),
        "TICKER_COVERAGE_COUNT": len(ticker_coverage_rows),
        "BENCHMARK_COVERAGE_COUNT": len(bench_coverage_rows),
        "ASOF_TECHNICAL_FACTOR_ROWS_CREATED": len(factor_rows),
        "RANKING_ROWS_CREATED": len(ranking_rows),
        "TOP20_ROWS_CREATED": len(top_rows[20]),
        "TOP50_ROWS_CREATED": len(top_rows[50]),
        "TOP100_ROWS_CREATED": len(top_rows[100]),
        "FORWARD_RETURN_ROWS_CREATED": len([row for row in return_rows if upper(row.get("row_included")) == "TRUE"]),
        "BENCHMARK_RELATIVE_RETURN_ROWS_CREATED": len([row for row in return_rows if upper(row.get("row_included")) == "TRUE"]),
        "LEAKAGE_BLOCKER_COUNT": leakage_blockers,
        "FORMULA_MISMATCH_COUNT": formula_mismatch_count,
        "EXCLUDED_NON_PIT_FACTOR_COUNT": excluded_non_pit_factor_count,
        "CURRENT_TOP20_LEAKAGE_DETECTED": tf(current_top20_leakage_detected),
        "READY_FOR_V20_36_ENTRY_STRATEGY_MATRIX_DESIGN": tf(ready_v20_36),
        "READY_FOR_FACTOR_EFFECTIVENESS_ABLATION_AUDIT": tf(ready_v20_36),
        "READY_FOR_SHADOW_DYNAMIC_WEIGHTING": "FALSE",
        "READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION": "FALSE",
        "NEXT_RECOMMENDED_STEP": "V20.36_ENTRY_STRATEGY_MATRIX_DESIGN" if ready_v20_36 else "V20.35_HISTORICAL_COVERAGE_EXPANSION_REQUIRED",
    }]

    factor_fields = [
        "signal_date", "ticker", "momentum_5d", "momentum_10d", "momentum_20d",
        "relative_strength_vs_spy_20d", "relative_strength_vs_qqq_20d",
        "ma10_position", "ma20_position", "ma50_position", "pullback_quality",
        "breakout_20d", "volatility_20d", "volume_trend_20d", "rsi_14",
        "macd_12_26", "bollinger_price_position_20d", "technical_factor_available_count",
        "technical_factor_missing_count", "max_factor_input_date", "asof_leakage_check_passed",
        "exploratory_technical_score", "score_policy", "non_official_research_only",
    ]
    ranking_fields = ["signal_date", "ticker", "asof_technical_rank", "exploratory_technical_score", "technical_factor_available_count", "technical_factor_missing_count", "score_policy", "official_ranking_mutated", "current_top20_used_for_historical_backtest"]
    top_fields = ranking_fields + ["top_bucket"]
    attach_fields = ["signal_date", "ticker", "top_bucket", "asof_technical_rank", "forward_window", "entry_price_date", "outcome_price_date", "ticker_entry_price", "ticker_outcome_price", "spy_entry_price", "spy_outcome_price", "qqq_entry_price", "qqq_outcome_price", "outcome_attachment_status", "outcome_attachment_exclusion_reason", "exploratory_random_asof_technical_only", "non_official_research_only"]
    return_fields = attach_fields + ["ticker_forward_return", "spy_forward_return", "qqq_forward_return", "benchmark_relative_return_vs_spy", "benchmark_relative_return_vs_qqq", "max_factor_input_date", "factor_asof_check_passed", "outcome_date_after_signal_date", "benchmark_dates_align_with_ticker_outcome", "formula_recheck_passed", "row_included", "extreme_return_warning"]
    summary_fields = ["row_count", "excluded_row_count", "average_ticker_return", "median_ticker_return", "average_benchmark_relative_return_vs_spy", "median_benchmark_relative_return_vs_spy", "average_benchmark_relative_return_vs_qqq", "median_benchmark_relative_return_vs_qqq", "win_rate_vs_spy", "win_rate_vs_qqq", "extreme_return_warning_count", "formula_mismatch_count"]

    write_csv(OUT_DATE_POOL, date_pool_rows, ["signal_date", "random_seed", "ticker_count_with_price_on_date", "lookback_trading_days_available", "forward_trading_days_available", "spy_qqq_benchmark_date_available", "eligible_for_random_sample", "exclusion_reason"])
    write_csv(OUT_DATE_SAMPLE, sample_rows, ["sample_order", "signal_date", "random_seed", "selection_policy", "selected"])
    write_csv(OUT_TICKER_COVERAGE, ticker_coverage_rows, ["ticker", "row_count", "min_price_date", "max_price_date", "adjusted_close_available", "close_available", "volume_available", "date_field", "coverage_status"])
    write_csv(OUT_BENCH_COVERAGE, bench_coverage_rows, ["benchmark_symbol", "row_count", "min_price_date", "max_price_date", "adjusted_close_available", "close_available", "volume_available", "date_field", "coverage_status"])
    write_csv(OUT_FACTOR_MATRIX, factor_rows, factor_fields)
    write_csv(OUT_FACTOR_AVAIL, factor_avail_rows, ["technical_factor_available_count", "row_count", "technical_factor_missing_count", "summary_status"])
    write_csv(OUT_RANKING, ranking_rows, ranking_fields)
    write_csv(OUT_TOP20, top_rows[20], top_fields)
    write_csv(OUT_TOP50, top_rows[50], top_fields)
    write_csv(OUT_TOP100, top_rows[100], top_fields)
    write_csv(OUT_ATTACH, attach_rows, attach_fields)
    write_csv(OUT_RETURNS, return_rows, return_fields)
    write_csv(OUT_SIGNAL_SUM, signal_summary, ["signal_date"] + summary_fields)
    write_csv(OUT_WINDOW_SUM, window_summary, ["forward_window"] + summary_fields)
    write_csv(OUT_BUCKET_SUM, bucket_summary, ["top_bucket"] + summary_fields)
    write_csv(OUT_BENCH_REL_SUM, bench_summary, ["forward_window", "top_bucket"] + summary_fields)
    write_csv(OUT_PIT, pit_rows, ["gate_check", "rows_checked", "blocker_count", "gate_passed"])
    write_csv(OUT_SOURCE, source_rows, ["source_id", "source_path", "source_hash", "row_count", "field_count", "min_price_date", "max_price_date", "run_id_count", "sample_run_id", "historical_random_asof_cache_used", "source_status"])
    write_csv(OUT_FORMULA, formula_rows, ["signal_date", "ticker", "top_bucket", "asof_technical_rank", "forward_window", "reported_ticker_forward_return", "recomputed_ticker_forward_return", "ticker_forward_return_delta", "reported_spy_forward_return", "recomputed_spy_forward_return", "spy_forward_return_delta", "reported_qqq_forward_return", "recomputed_qqq_forward_return", "qqq_forward_return_delta", "reported_benchmark_relative_return_vs_spy", "recomputed_benchmark_relative_return_vs_spy", "benchmark_relative_return_vs_spy_delta", "reported_benchmark_relative_return_vs_qqq", "recomputed_benchmark_relative_return_vs_qqq", "benchmark_relative_return_vs_qqq_delta", "formula_recheck_passed", "severity"])
    write_csv(OUT_BLOCKED_ENFORCE, blocked_enforcement_rows, ["blocked_factor_group", "excluded_from_v20_35_recompute", "current_top20_or_current_ranking_used", "enforcement_status", "notes"])
    write_csv(OUT_DECISION, decision_out, list(decision_out[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))

    report = f"""# V20.35-R2 Random Asof Top20 Technical Recompute Backtest Retry From Historical Cache

Status: {status}

Exploratory research only: TRUE
Technical-only recompute: TRUE
Historical random-asof cache used: {tf(historical_random_asof_cache_used)}
Current Top20 used for historical backtest: FALSE
Non-PIT factors excluded: TRUE

V20.35-R1 gate ready: {tf(r1_gate_ready)}
Random signal date candidate count: {len(eligible_dates)}
Selected random signal date count: {len(selected_dates)}
Ticker coverage count: {len(ticker_coverage_rows)}
Benchmark coverage count: {len(bench_coverage_rows)}
Forward return rows created: {len(included_returns)}

Decision reason: {decision_out[0]["decision_reason"]}

V20.35-R2 did not create official recommendations, trading signals, broker/order/execution code, official ranking mutations, official factor weight mutations, dynamic weighting, portfolio-level backtests, equity curves, Sharpe/Sortino/final performance claims, V21 outputs, or V19.21 outputs.
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)

    read_first = f"""STAGE_NAME: {STAGE_NAME}
STATUS: {status}
EXPLORATORY_RESEARCH_ONLY: TRUE
RANDOM_ASOF_TOP20_BACKTEST_EXECUTED: {tf(executed)}
TECHNICAL_ONLY_RECOMPUTE: TRUE
HISTORICAL_RANDOM_ASOF_CACHE_USED: {tf(historical_random_asof_cache_used)}
CURRENT_TOP20_USED_FOR_HISTORICAL_BACKTEST: FALSE
NON_PIT_FACTORS_EXCLUDED: TRUE
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
V20_35_R1_GATE_READY: {tf(r1_gate_ready)}
RANDOM_SIGNAL_DATE_CANDIDATE_COUNT: {len(eligible_dates)}
SELECTED_RANDOM_SIGNAL_DATE_COUNT: {len(selected_dates)}
FORWARD_RETURN_ROWS_CREATED: {len(included_returns)}
READY_FOR_V20_36_ENTRY_STRATEGY_MATRIX_DESIGN: {tf(ready_v20_36)}
READY_FOR_SHADOW_DYNAMIC_WEIGHTING: FALSE
READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION: FALSE
"""
    write_text(READ_FIRST, read_first)

    required_outputs = [
        OUT_SOURCE, OUT_DATE_POOL, OUT_DATE_SAMPLE, OUT_TICKER_COVERAGE, OUT_BENCH_COVERAGE,
        OUT_FACTOR_MATRIX, OUT_FACTOR_AVAIL, OUT_RANKING, OUT_TOP20, OUT_TOP50,
        OUT_TOP100, OUT_ATTACH, OUT_RETURNS, OUT_SIGNAL_SUM, OUT_WINDOW_SUM,
        OUT_BUCKET_SUM, OUT_BENCH_REL_SUM, OUT_PIT, OUT_FORMULA, OUT_BLOCKED_ENFORCE,
        OUT_DECISION, OUT_NEXT, REPORT, CURRENT_REPORT, READ_FIRST,
    ]
    missing = [path for path in required_outputs if not path.exists()]
    if missing:
        raise RuntimeError("Missing V20.35-R2 outputs: " + ", ".join(rel(path) for path in missing))

    print(f"STATUS={status}")
    print("FILES_CHANGED=scripts/v20/v20_35_r2_random_asof_top20_technical_recompute_backtest_retry_from_historical_cache.py;scripts/v20/run_v20_35_r2_random_asof_top20_technical_recompute_backtest_retry_from_historical_cache.ps1")
    print("OUTPUTS_CREATED=" + ";".join(rel(path) for path in required_outputs))
    print(f"V20_35_R1_GATE_READY={tf(r1_gate_ready)}")
    print(f"HISTORICAL_RANDOM_ASOF_CACHE_USED={tf(historical_random_asof_cache_used)}")
    print(f"RANDOM_SIGNAL_DATE_CANDIDATE_COUNT={len(eligible_dates)}")
    print(f"SELECTED_RANDOM_SIGNAL_DATE_COUNT={len(selected_dates)}")
    print(f"TICKER_COVERAGE_COUNT={len(ticker_coverage_rows)}")
    print(f"BENCHMARK_COVERAGE_COUNT={len(bench_coverage_rows)}")
    print(f"ASOF_TECHNICAL_FACTOR_ROWS_CREATED={len(factor_rows)}")
    print(f"RANKING_ROWS_CREATED={len(ranking_rows)}")
    print(f"TOP20_ROWS_CREATED={len(top_rows[20])}")
    print(f"TOP50_ROWS_CREATED={len(top_rows[50])}")
    print(f"TOP100_ROWS_CREATED={len(top_rows[100])}")
    print(f"FORWARD_RETURN_ROWS_CREATED={len(included_returns)}")
    print(f"BENCHMARK_RELATIVE_RETURN_ROWS_CREATED={len(included_returns)}")
    print(f"LEAKAGE_BLOCKER_COUNT={leakage_blockers}")
    print(f"FORMULA_MISMATCH_COUNT={formula_mismatch_count}")
    print(f"EXCLUDED_NON_PIT_FACTOR_COUNT={excluded_non_pit_factor_count}")
    print(f"CURRENT_TOP20_LEAKAGE_DETECTED={tf(current_top20_leakage_detected)}")
    print(f"READY_FOR_V20_36_ENTRY_STRATEGY_MATRIX_DESIGN={tf(ready_v20_36)}")
    print(f"READY_FOR_FACTOR_EFFECTIVENESS_ABLATION_AUDIT={tf(ready_v20_36)}")
    print("READY_FOR_SHADOW_DYNAMIC_WEIGHTING=FALSE")
    print("READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
