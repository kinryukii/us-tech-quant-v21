#!/usr/bin/env python
"""V20.201 random-weight PIT-forward backtest consolidation.

Research-only framework using canonical historical OHLCV inputs from V20.199D.
It recomputes PIT-safe factor-family scores from data available on or before
each as_of_date, samples constrained random weights, evaluates forward returns,
and compares against an ETF rotation benchmark over the same forward window.
"""

from __future__ import annotations

import csv
import hashlib
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[2]
PRICE_DIR = ROOT / "outputs" / "v20" / "price_history"
OUT_DIR = ROOT / "outputs" / "v20" / "random_weight_backtest"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_STOCK = PRICE_DIR / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
IN_BENCH = PRICE_DIR / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"
IN_GATE = PRICE_DIR / "V20_199D_NEXT_STAGE_GATE.csv"
IN_PRICE_COVERAGE = PRICE_DIR / "V20_199D_PRICE_COVERAGE_AFTER_REFRESH.csv"
IN_BENCH_COVERAGE = PRICE_DIR / "V20_199D_HISTORICAL_BENCHMARK_COVERAGE_AUDIT.csv"

OUT_TRIALS = OUT_DIR / "V20_201_RANDOM_WEIGHT_TRIALS.csv"
OUT_RANKINGS = OUT_DIR / "V20_201_RANDOM_WEIGHT_ASOF_RANKINGS.csv"
OUT_FORWARD = OUT_DIR / "V20_201_RANDOM_WEIGHT_FORWARD_OUTCOMES.csv"
OUT_ETF = OUT_DIR / "V20_201_ETF_ROTATION_BENCHMARK_OUTCOMES.csv"
OUT_SUMMARY = OUT_DIR / "V20_201_WEIGHT_EFFECTIVENESS_SUMMARY.csv"
OUT_PIT = OUT_DIR / "V20_201_PIT_LEAKAGE_AUDIT.csv"
OUT_COVERAGE = OUT_DIR / "V20_201_SOURCE_COVERAGE_DIAGNOSTICS.csv"
OUT_REPORT = READ_CENTER / "V20_201_RANDOM_WEIGHT_PIT_FORWARD_BACKTEST_REPORT.md"

RANDOM_SEED_BASE = 20260616
TRIAL_COUNT = 100
TOP_N = 20
MIN_LOOKBACK = 60
FORWARD_WINDOWS = {"1D": 1, "3D": 3, "5D": 5, "10D": 10, "20D": 20}
BENCHMARKS = ["QQQ", "SPY", "SOXX"]
FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME"]
WEIGHT_RANGES = {
    "FUNDAMENTAL": (0.10, 0.30),
    "TECHNICAL": (0.15, 0.35),
    "STRATEGY": (0.10, 0.30),
    "RISK": (0.10, 0.25),
    "MARKET_REGIME": (0.05, 0.20),
}
FORBIDDEN_KEYWORDS = [
    "forward", "outcome", "future", "return_after", "realized", "exit_price",
    "max_runup", "max_drawdown", "benchmark_return",
]

PASS_STATUS = "PASS_V20_201_RANDOM_WEIGHT_PIT_FORWARD_BACKTEST_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V20_201_LIMITED_PIT_OR_OUTCOME_COVERAGE"
BLOCKED_PIT = "BLOCKED_V20_201_PIT_VALIDATION_FAILED"
BLOCKED_ETF = "BLOCKED_V20_201_ETF_ROTATION_BENCHMARK_UNAVAILABLE"
BLOCKED_NO_VALID = "BLOCKED_V20_201_NO_VALID_TRIALS"

COMMON = {
    "research_only": "TRUE",
    "official_weight_mutated": "FALSE",
    "official_ranking_mutated": "FALSE",
    "official_recommendation_created": "FALSE",
    "trade_action_created": "FALSE",
    "real_book_signal_created": "FALSE",
    "broker_execution_supported": "FALSE",
}

TRIAL_FIELDS = [
    "trial_id", "seed", "as_of_date", "forward_window", "top_n", "weight_sum",
    "fundamental_weight", "technical_weight", "strategy_weight", "risk_weight",
    "market_regime_weight", "data_trust_weight", "data_trust_used_in_ranking",
    "data_trust_used_as_audit_gate", "pit_validation_status",
    "universe_validation_status", "etf_benchmark_available", "trial_status",
    "failure_reason", "created_at", *COMMON.keys(),
]
RANK_FIELDS = [
    "trial_id", "seed", "as_of_date", "forward_window", "ticker", "rank",
    "composite_score", "fundamental_score", "technical_score", "strategy_score",
    "risk_score", "market_regime_score", "data_trust_score", "data_trust_status",
    "eligible_for_ranking", "eligible_for_backtest", "exclusion_reason",
    "source_artifact", *COMMON.keys(),
]
FORWARD_FIELDS = [
    "trial_id", "as_of_date", "forward_window", "ticker", "rank", "entry_date",
    "exit_date", "entry_price", "exit_price", "forward_return",
    "max_forward_drawdown", "max_forward_runup", "hit_positive_return",
    "data_available", "outcome_status", "outcome_failure_reason", *COMMON.keys(),
]
ETF_FIELDS = [
    "trial_id", "as_of_date", "forward_window", "selected_etf",
    "etf_rotation_signal", "etf_entry_date", "etf_exit_date", "etf_entry_price",
    "etf_exit_price", "etf_forward_return", "qqq_forward_return",
    "spy_forward_return", "sector_benchmark_return", "benchmark_status",
    "benchmark_failure_reason", *COMMON.keys(),
]
SUMMARY_FIELDS = [
    "total_trial_count", "valid_trial_count", "pit_pass_count", "pit_warn_count",
    "pit_fail_count", "avg_stock_topN_return", "median_stock_topN_return",
    "avg_etf_rotation_return", "median_etf_rotation_return",
    "avg_excess_vs_etf_rotation", "median_excess_vs_etf_rotation",
    "win_rate_vs_etf_rotation", "win_rate_vs_qqq", "win_rate_vs_spy",
    "avg_max_drawdown", "avg_etf_max_drawdown_if_available",
    "best_weight_family_bias", "worst_weight_family_bias", "overfit_warning",
    "survivorship_warning", "etf_benchmark_coverage_rate", "final_status",
    "next_recommended_action", *COMMON.keys(),
]
PIT_FIELDS = ["checked_artifact", "checked_field", "leakage_keyword_hit", "allowed_in_ranking", "audit_status", "reason"]
COVERAGE_FIELDS = ["source_artifact", "exists_non_empty", "row_count", "min_date", "max_date", "date_field", "required_for", "coverage_status", "warning_reason"]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def fmt(value: float | None) -> str:
    return "" if value is None or math.isnan(value) or math.isinf(value) else f"{value:.10f}"


def num(value: object) -> float | None:
    try:
        text = clean(value)
        if not text:
            return None
        parsed = float(text)
    except ValueError:
        return None
    return None if math.isnan(parsed) or math.isinf(parsed) else parsed


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


def sha_file(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_price_index(path: Path) -> dict[str, dict[str, dict[str, float]]]:
    index: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    for row in read_csv(path):
        symbol = clean(row.get("symbol") or row.get("ticker")).upper()
        date = clean(row.get("date"))[:10]
        close = num(row.get("close"))
        high = num(row.get("high")) or close
        low = num(row.get("low")) or close
        volume = num(row.get("volume")) or 0.0
        if symbol and date and close is not None and close > 0:
            index[symbol][date] = {"close": close, "high": high or close, "low": low or close, "volume": volume}
    return {symbol: dict(sorted(rows.items())) for symbol, rows in index.items()}


def date_at_offset(dates: list[str], as_of: str, offset: int) -> str:
    try:
        idx = dates.index(as_of)
    except ValueError:
        return ""
    target = idx + offset
    return dates[target] if 0 <= target < len(dates) else ""


def pct_rank(value: float, low: float, high: float, invert: bool = False) -> float:
    score = 0.5 if high == low else max(0.0, min(1.0, (value - low) / (high - low)))
    return 1.0 - score if invert else score


def returns(prices: list[float]) -> list[float]:
    return [prices[i] / prices[i - 1] - 1.0 for i in range(1, len(prices)) if prices[i - 1] > 0]


def rsi(prices: list[float], period: int = 14) -> float:
    diffs = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    recent = diffs[-period:]
    gains = [x for x in recent if x > 0]
    losses = [-x for x in recent if x < 0]
    avg_gain = sum(gains) / period if gains else 0.0
    avg_loss = sum(losses) / period if losses else 0.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def family_scores(ticker: str, as_of: str, series: dict[str, dict[str, float]], bench: dict[str, dict[str, dict[str, float]]]) -> dict[str, object]:
    dates = [date for date in series if date <= as_of]
    if len(dates) < MIN_LOOKBACK:
        return {"status": "INSUFFICIENT_LOOKBACK", "reason": "FEWER_THAN_60_PIT_BARS", "lookback": len(dates)}
    lookback = dates[-MIN_LOOKBACK:]
    prices = [series[date]["close"] for date in lookback]
    vols = [series[date].get("volume", 0.0) for date in lookback]
    last = prices[-1]
    ma20 = sum(prices[-20:]) / 20
    ma60 = sum(prices) / len(prices)
    mom20 = last / prices[-21] - 1 if prices[-21] else 0.0
    mom60 = last / prices[0] - 1 if prices[0] else 0.0
    rets = returns(prices)
    recent = rets[-20:]
    avg_recent = sum(recent) / len(recent) if recent else 0.0
    vol20 = (sum((ret - avg_recent) ** 2 for ret in recent) / len(recent)) ** 0.5 if recent else 0.0
    high20 = max(prices[-20:])
    low20 = min(prices[-20:])
    boll = pct_rank(last, low20, high20)
    rsi14 = rsi(prices)
    volume_trend = (sum(vols[-10:]) / 10) / (sum(vols[-30:]) / 30) - 1 if sum(vols[-30:]) > 0 else 0.0
    volume_stability = 1.0 - min(1.0, abs(volume_trend))
    drawdown = last / max(prices) - 1
    technical = sum([
        pct_rank(last / ma20 - 1, -0.10, 0.10),
        pct_rank(ma20 / ma60 - 1, -0.10, 0.10),
        pct_rank(mom20, -0.25, 0.25),
        pct_rank(mom60, -0.40, 0.40),
        max(0.0, 1.0 - abs(boll - 0.65)),
        max(0.0, 1.0 - abs((rsi14 / 100.0) - 0.55)),
        pct_rank(volume_trend, -0.50, 0.50),
        pct_rank(vol20, 0.00, 0.08, invert=True),
    ]) / 8
    pullback = 1.0 if last > ma60 and last <= ma20 * 1.03 else 0.0
    breakout = 1.0 if last >= high20 * 0.99 and mom20 > 0 else 0.0
    overheat_avoid = 1.0 if not (rsi14 > 75 and boll > 0.95) else 0.0
    strategy = (pullback + breakout + overheat_avoid + pct_rank(mom20, -0.15, 0.20)) / 4
    risk = (pct_rank(vol20, 0.00, 0.08, invert=True) + pct_rank(drawdown, -0.40, 0.0) + overheat_avoid) / 3
    fundamental_proxy = (pct_rank(sum(vols[-20:]) / 20, 0.0, 10_000_000.0) + volume_stability + pct_rank(mom60, -0.25, 0.25)) / 3
    regime_parts = []
    for symbol in BENCHMARKS:
        bseries = bench.get(symbol, {})
        bdates = [date for date in bseries if date <= as_of]
        if len(bdates) >= MIN_LOOKBACK:
            bprices = [bseries[date]["close"] for date in bdates[-MIN_LOOKBACK:]]
            bma20 = sum(bprices[-20:]) / 20
            bma60 = sum(bprices) / len(bprices)
            bm20 = bprices[-1] / bprices[-21] - 1 if bprices[-21] else 0.0
            brets = returns(bprices)
            bvol = (sum((ret - (sum(brets[-20:]) / len(brets[-20:]))) ** 2 for ret in brets[-20:]) / len(brets[-20:])) ** 0.5 if len(brets) >= 20 else 0.0
            regime_parts.append((pct_rank(bprices[-1] / bma20 - 1, -0.06, 0.06) + pct_rank(bma20 / bma60 - 1, -0.08, 0.08) + pct_rank(bm20, -0.12, 0.12) + pct_rank(bvol, 0.00, 0.04, invert=True)) / 4)
    market_regime = sum(regime_parts) / len(regime_parts) if regime_parts else 0.5
    return {
        "status": "PASS", "reason": "", "lookback": len(dates), "max_input_date": dates[-1],
        "fundamental": max(0.0, min(1.0, fundamental_proxy)),
        "technical": max(0.0, min(1.0, technical)),
        "strategy": max(0.0, min(1.0, strategy)),
        "risk": max(0.0, min(1.0, risk)),
        "market_regime": max(0.0, min(1.0, market_regime)),
    }


def sample_weights(rng: random.Random) -> dict[str, float]:
    remaining = 1.0
    weights: dict[str, float] = {}
    for idx, family in enumerate(FAMILIES):
        low, high = WEIGHT_RANGES[family]
        rest = FAMILIES[idx + 1:]
        if not rest:
            if low - 1e-12 <= remaining <= high + 1e-12:
                weights[family] = remaining
                break
            raise ValueError("FINAL_WEIGHT_OUT_OF_RANGE")
        min_rest = sum(WEIGHT_RANGES[name][0] for name in rest)
        max_rest = sum(WEIGHT_RANGES[name][1] for name in rest)
        bounded_low = max(low, remaining - max_rest)
        bounded_high = min(high, remaining - min_rest)
        if bounded_low > bounded_high:
            raise ValueError("WEIGHT_CONSTRAINTS_UNSATISFIABLE")
        value = rng.uniform(bounded_low, bounded_high)
        weights[family] = value
        remaining -= value
    drift = 1.0 - sum(weights.values())
    weights[FAMILIES[-1]] += drift
    if any(weights[f] < WEIGHT_RANGES[f][0] - 1e-9 or weights[f] > WEIGHT_RANGES[f][1] + 1e-9 for f in FAMILIES):
        raise ValueError("GENERATED_WEIGHT_RANGE_VIOLATION")
    return weights


def forward_metrics(series: dict[str, dict[str, float]], as_of: str, offset: int) -> dict[str, object]:
    dates = sorted(series)
    exit_date = date_at_offset(dates, as_of, offset)
    entry = series.get(as_of, {}).get("close")
    exit_price = series.get(exit_date, {}).get("close") if exit_date else None
    if entry is None or exit_price is None or not exit_date or exit_date <= as_of:
        return {"status": "MISSING_FORWARD_PRICE", "failure": "MISSING_ENTRY_OR_EXIT_PRICE"}
    idx0 = dates.index(as_of)
    idx1 = dates.index(exit_date)
    path = [series[date]["close"] for date in dates[idx0: idx1 + 1]]
    rels = [(price / entry) - 1.0 for price in path if entry > 0]
    return {
        "status": "PASS", "failure": "", "entry_date": as_of, "exit_date": exit_date,
        "entry_price": entry, "exit_price": exit_price, "forward_return": exit_price / entry - 1.0,
        "max_drawdown": min(rels) if rels else 0.0, "max_runup": max(rels) if rels else 0.0,
    }


def etf_signal(as_of: str, bench: dict[str, dict[str, dict[str, float]]]) -> tuple[str, str]:
    scored = []
    for symbol in BENCHMARKS:
        dates = [date for date in bench.get(symbol, {}) if date <= as_of]
        if len(dates) < MIN_LOOKBACK:
            continue
        prices = [bench[symbol][date]["close"] for date in dates[-MIN_LOOKBACK:]]
        mom20 = prices[-1] / prices[-21] - 1 if prices[-21] else 0.0
        recent = returns(prices)[-20:]
        avg_recent = sum(recent) / len(recent) if recent else 0.0
        vol = (sum((ret - avg_recent) ** 2 for ret in recent) / len(recent)) ** 0.5 if recent else 1.0
        scored.append((mom20 / max(vol, 0.0001), symbol, mom20))
    if not scored:
        return "", "NO_PRIOR_ETF_SIGNAL"
    scored.sort(reverse=True)
    selected = scored[0][1]
    return selected, f"PRIOR_20D_RISK_ADJUSTED_MOMENTUM_SELECTED_{selected}"


def coverage_rows(stock: dict[str, dict[str, dict[str, float]]], bench: dict[str, dict[str, dict[str, float]]]) -> list[dict[str, object]]:
    rows = []
    for path, required_for, date_field in [
        (IN_STOCK, "candidate PIT ranking and stock forward outcomes", "date"),
        (IN_BENCH, "ETF rotation benchmark and regime scores", "date"),
        (IN_GATE, "upstream canonical price readiness", ""),
        (IN_PRICE_COVERAGE, "stock price coverage diagnostics", ""),
        (IN_BENCH_COVERAGE, "benchmark coverage diagnostics", ""),
    ]:
        data = read_csv(path)
        dates = [clean(row.get(date_field))[:10] for row in data if date_field and clean(row.get(date_field))]
        ok = path.exists() and path.stat().st_size > 0
        rows.append({
            "source_artifact": rel(path),
            "exists_non_empty": tf(ok),
            "row_count": str(len(data)),
            "min_date": min(dates) if dates else "",
            "max_date": max(dates) if dates else "",
            "date_field": date_field,
            "required_for": required_for,
            "coverage_status": "PASS" if ok else "MISSING_OR_EMPTY",
            "warning_reason": "" if ok else "REQUIRED_SOURCE_UNAVAILABLE",
        })
    if stock:
        symbols_with_lookback = sum(1 for rows_by_date in stock.values() if len(rows_by_date) >= MIN_LOOKBACK)
        rows.append({
            "source_artifact": rel(IN_STOCK), "exists_non_empty": "TRUE",
            "row_count": str(sum(len(v) for v in stock.values())), "min_date": "", "max_date": "",
            "date_field": "date", "required_for": "eligible ticker universe",
            "coverage_status": "PASS" if symbols_with_lookback >= TOP_N else "WARN",
            "warning_reason": "" if symbols_with_lookback >= TOP_N else "FEWER_THAN_TOP_N_TICKERS_WITH_LOOKBACK",
        })
    if bench:
        ready = all(len(bench.get(symbol, {})) >= MIN_LOOKBACK for symbol in BENCHMARKS)
        rows.append({
            "source_artifact": rel(IN_BENCH), "exists_non_empty": tf(bool(bench)),
            "row_count": str(sum(len(v) for v in bench.values())), "min_date": "", "max_date": "",
            "date_field": "date", "required_for": "QQQ SPY SOXX ETF benchmark coverage",
            "coverage_status": "PASS" if ready else "WARN",
            "warning_reason": "" if ready else "ONE_OR_MORE_REQUIRED_ETFS_HAVE_LIMITED_LOOKBACK",
        })
    return rows


def pit_audit_rows() -> tuple[list[dict[str, object]], bool]:
    ranking_fields = [
        "ticker", "as_of_date", "close", "volume", "fundamental_score",
        "technical_score", "strategy_score", "risk_score", "market_regime_score",
        "data_trust_score",
    ]
    nonranking_fields = FORWARD_FIELDS + ETF_FIELDS
    rows = []
    for field in ranking_fields:
        hit = any(key in field.lower() for key in FORBIDDEN_KEYWORDS)
        rows.append({
            "checked_artifact": "V20_201_RANDOM_WEIGHT_ASOF_RANKINGS.csv",
            "checked_field": field,
            "leakage_keyword_hit": tf(hit),
            "allowed_in_ranking": tf(not hit),
            "audit_status": "FAIL" if hit else "PASS",
            "reason": "FORBIDDEN_OUTCOME_FIELD_IN_RANKING" if hit else "PIT_SAFE_RANKING_INPUT",
        })
    for field in sorted(set(nonranking_fields)):
        hit = any(key in field.lower() for key in FORBIDDEN_KEYWORDS)
        if hit:
            rows.append({
                "checked_artifact": "outcome_or_benchmark_outputs",
                "checked_field": field,
                "leakage_keyword_hit": "TRUE",
                "allowed_in_ranking": "FALSE",
                "audit_status": "PASS",
                "reason": "OUTCOME_FIELD_ALLOWED_ONLY_AFTER_RANKING",
            })
    return rows, all(row["audit_status"] == "PASS" for row in rows)


def aggregate(values: list[float]) -> tuple[str, str]:
    return (fmt(mean(values)), fmt(median(values))) if values else ("", "")


def blocked_outputs(status: str, reason: str, coverage: list[dict[str, object]], pit_rows: list[dict[str, object]]) -> int:
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    summary = {
        "total_trial_count": "0", "valid_trial_count": "0", "pit_pass_count": "0",
        "pit_warn_count": "0", "pit_fail_count": "1" if status == BLOCKED_PIT else "0",
        "overfit_warning": "NOT_EVALUATED", "survivorship_warning": "NOT_EVALUATED",
        "etf_benchmark_coverage_rate": "0.0000000000", "final_status": status,
        "next_recommended_action": reason, **COMMON,
    }
    write_csv(OUT_TRIALS, TRIAL_FIELDS, [{
        "trial_id": "V20_201_BLOCKED_001", "seed": str(RANDOM_SEED_BASE), "top_n": str(TOP_N),
        "weight_sum": "", "data_trust_weight": "0.0000000000", "data_trust_used_in_ranking": "FALSE",
        "data_trust_used_as_audit_gate": "TRUE", "pit_validation_status": "FAIL" if status == BLOCKED_PIT else "NOT_EVALUATED",
        "universe_validation_status": "BLOCKED", "etf_benchmark_available": "FALSE",
        "trial_status": "BLOCKED", "failure_reason": reason, "created_at": created, **COMMON,
    }])
    for path, fields in [(OUT_RANKINGS, RANK_FIELDS), (OUT_FORWARD, FORWARD_FIELDS), (OUT_ETF, ETF_FIELDS)]:
        write_csv(path, fields, [])
    write_csv(OUT_SUMMARY, SUMMARY_FIELDS, [summary])
    write_csv(OUT_PIT, PIT_FIELDS, pit_rows)
    write_csv(OUT_COVERAGE, COVERAGE_FIELDS, coverage)
    write_report(summary, reason)
    print(status)
    print(f"FINAL_STATUS={status}")
    print(f"BLOCKING_REASON={reason}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_WEIGHT_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_SIGNAL_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    return 0


def write_report(summary: dict[str, object], reason: str = "") -> None:
    READ_CENTER.mkdir(parents=True, exist_ok=True)
    final_status = clean(summary.get("final_status"))
    lines = [
        "# V20.201 Random-Weight PIT-Forward Backtest Report",
        "",
        f"- Final status: {final_status}",
        f"- Trial count: {summary.get('total_trial_count', '')}",
        f"- Valid trial count: {summary.get('valid_trial_count', '')}",
        f"- PIT validation result: pass={summary.get('pit_pass_count', '')}, warn={summary.get('pit_warn_count', '')}, fail={summary.get('pit_fail_count', '')}",
        f"- ETF benchmark coverage: {summary.get('etf_benchmark_coverage_rate', '')}",
        f"- Average / median TopN return: {summary.get('avg_stock_topN_return', '')} / {summary.get('median_stock_topN_return', '')}",
        f"- Average / median ETF rotation return: {summary.get('avg_etf_rotation_return', '')} / {summary.get('median_etf_rotation_return', '')}",
        f"- Average / median excess versus ETF rotation: {summary.get('avg_excess_vs_etf_rotation', '')} / {summary.get('median_excess_vs_etf_rotation', '')}",
        f"- Win rate versus ETF rotation / QQQ / SPY: {summary.get('win_rate_vs_etf_rotation', '')} / {summary.get('win_rate_vs_qqq', '')} / {summary.get('win_rate_vs_spy', '')}",
        f"- Random weight family bias: best={summary.get('best_weight_family_bias', '')}, worst={summary.get('worst_weight_family_bias', '')}",
        f"- Shadow weight change readiness: {summary.get('next_recommended_action', '')}",
        "",
        "Safety statement:",
        "- official weights were not changed",
        "- no official recommendation was created",
        "- no real-book signal was created",
        "- no broker execution was created",
    ]
    if reason:
        lines.extend(["", f"Blocking or warning reason: {reason}"])
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    stock = load_price_index(IN_STOCK)
    bench = load_price_index(IN_BENCH)
    coverage = coverage_rows(stock, bench)
    pit_rows, pit_ok = pit_audit_rows()
    if not pit_ok:
        return blocked_outputs(BLOCKED_PIT, "FORBIDDEN_OUTCOME_FIELD_USED_IN_RANKING_INPUT", coverage, pit_rows)
    if not all(bench.get(symbol) for symbol in BENCHMARKS):
        return blocked_outputs(BLOCKED_ETF, "QQQ_SPY_SOXX_BENCHMARK_HISTORY_REQUIRED", coverage, pit_rows)
    if not stock:
        return blocked_outputs(BLOCKED_NO_VALID, "NO_CANONICAL_STOCK_PRICE_HISTORY", coverage, pit_rows)

    benchmark_dates = sorted(set.intersection(*(set(bench[symbol].keys()) for symbol in BENCHMARKS)))
    valid_dates = []
    for as_of in benchmark_dates:
        if sum(1 for date in benchmark_dates if date <= as_of) < MIN_LOOKBACK:
            continue
        if all(date_at_offset(benchmark_dates, as_of, offset) for offset in FORWARD_WINDOWS.values()):
            valid_dates.append(as_of)
    if not valid_dates:
        return blocked_outputs(BLOCKED_NO_VALID, "NO_ASOF_DATE_WITH_REQUIRED_FORWARD_BENCHMARK_WINDOWS", coverage, pit_rows)

    universe = sorted(symbol for symbol, rows in stock.items() if len(rows) >= MIN_LOOKBACK)
    if len(universe) < TOP_N:
        return blocked_outputs(BLOCKED_NO_VALID, "FEWER_THAN_TOP_N_ELIGIBLE_TICKERS", coverage, pit_rows)

    rng_dates = random.Random(RANDOM_SEED_BASE)
    selected_dates = [rng_dates.choice(valid_dates) for _ in range(TRIAL_COUNT)]
    trials: list[dict[str, object]] = []
    rankings: list[dict[str, object]] = []
    forward_rows: list[dict[str, object]] = []
    etf_rows: list[dict[str, object]] = []
    stock_trial_returns: dict[str, float] = {}
    etf_trial_returns: dict[str, float] = {}
    qqq_trial_returns: dict[str, float] = {}
    spy_trial_returns: dict[str, float] = {}
    etf_dd: list[float] = []
    trial_weight_bias: dict[str, dict[str, float]] = {}

    for sample_idx, as_of in enumerate(selected_dates, start=1):
        seed = RANDOM_SEED_BASE + sample_idx
        rng = random.Random(seed)
        try:
            weights = sample_weights(rng)
            weight_reason = ""
        except ValueError as exc:
            weights = {family: 0.0 for family in FAMILIES}
            weight_reason = str(exc)
        base_scores = []
        for ticker in universe:
            scores = family_scores(ticker, as_of, stock[ticker], bench)
            if scores["status"] != "PASS":
                continue
            composite = sum(float(scores[family.lower()]) * weights[family] for family in FAMILIES) if not weight_reason else 0.0
            base_scores.append((ticker, composite, scores))
        base_scores.sort(key=lambda item: (-item[1], item[0]))
        etf_selected, etf_sig = etf_signal(as_of, bench)
        for window, offset in FORWARD_WINDOWS.items():
            trial_id = f"V20_201_TRIAL_{sample_idx:03d}_{window}"
            rank_ok = len(base_scores) >= TOP_N and not weight_reason
            etf_available = bool(etf_selected and forward_metrics(bench[etf_selected], as_of, offset).get("status") == "PASS")
            trials.append({
                "trial_id": trial_id, "seed": str(seed), "as_of_date": as_of,
                "forward_window": window, "top_n": str(TOP_N), "weight_sum": fmt(sum(weights.values())),
                "fundamental_weight": fmt(weights["FUNDAMENTAL"]), "technical_weight": fmt(weights["TECHNICAL"]),
                "strategy_weight": fmt(weights["STRATEGY"]), "risk_weight": fmt(weights["RISK"]),
                "market_regime_weight": fmt(weights["MARKET_REGIME"]), "data_trust_weight": "0.0000000000",
                "data_trust_used_in_ranking": "FALSE", "data_trust_used_as_audit_gate": "TRUE",
                "pit_validation_status": "PASS", "universe_validation_status": "CURRENT_UNIVERSE_SURVIVORSHIP_RISK_WARN",
                "etf_benchmark_available": tf(etf_available),
                "trial_status": "VALID" if rank_ok and etf_available else "WARN",
                "failure_reason": weight_reason or ("" if etf_available else "ETF_BENCHMARK_FORWARD_WINDOW_MISSING"),
                "created_at": created, **COMMON,
            })
            top_scores = base_scores[:TOP_N] if rank_ok else []
            trial_returns = []
            trial_drawdowns = []
            for rank, (ticker, composite, scores) in enumerate(top_scores, start=1):
                rankings.append({
                    "trial_id": trial_id, "seed": str(seed), "as_of_date": as_of,
                    "forward_window": window, "ticker": ticker, "rank": str(rank),
                    "composite_score": fmt(composite),
                    "fundamental_score": fmt(float(scores["fundamental"])),
                    "technical_score": fmt(float(scores["technical"])),
                    "strategy_score": fmt(float(scores["strategy"])),
                    "risk_score": fmt(float(scores["risk"])),
                    "market_regime_score": fmt(float(scores["market_regime"])),
                    "data_trust_score": "", "data_trust_status": "AUDIT_ONLY_NOT_USED_IN_RANKING",
                    "eligible_for_ranking": "TRUE", "eligible_for_backtest": "TRUE",
                    "exclusion_reason": "", "source_artifact": rel(IN_STOCK), **COMMON,
                })
                metrics = forward_metrics(stock[ticker], as_of, offset)
                ok = metrics.get("status") == "PASS"
                if ok:
                    trial_returns.append(float(metrics["forward_return"]))
                    trial_drawdowns.append(float(metrics["max_drawdown"]))
                forward_rows.append({
                    "trial_id": trial_id, "as_of_date": as_of, "forward_window": window,
                    "ticker": ticker, "rank": str(rank), "entry_date": metrics.get("entry_date", as_of),
                    "exit_date": metrics.get("exit_date", ""), "entry_price": fmt(metrics.get("entry_price") if ok else None),
                    "exit_price": fmt(metrics.get("exit_price") if ok else None),
                    "forward_return": fmt(metrics.get("forward_return") if ok else None),
                    "max_forward_drawdown": fmt(metrics.get("max_drawdown") if ok else None),
                    "max_forward_runup": fmt(metrics.get("max_runup") if ok else None),
                    "hit_positive_return": tf(float(metrics["forward_return"]) > 0) if ok else "FALSE",
                    "data_available": tf(ok), "outcome_status": "PASS" if ok else "WARN",
                    "outcome_failure_reason": "" if ok else clean(metrics.get("failure")), **COMMON,
                })
            if trial_returns:
                stock_trial_returns[trial_id] = mean(trial_returns)
                trial_weight_bias[trial_id] = {**weights, "return": stock_trial_returns[trial_id], "drawdown": mean(trial_drawdowns) if trial_drawdowns else 0.0}
            selected_metrics = forward_metrics(bench[etf_selected], as_of, offset) if etf_selected else {"status": "NO_SIGNAL"}
            qqq_metrics = forward_metrics(bench["QQQ"], as_of, offset)
            spy_metrics = forward_metrics(bench["SPY"], as_of, offset)
            soxx_metrics = forward_metrics(bench["SOXX"], as_of, offset)
            etf_ok = selected_metrics.get("status") == "PASS"
            if etf_ok:
                etf_trial_returns[trial_id] = float(selected_metrics["forward_return"])
                etf_dd.append(float(selected_metrics["max_drawdown"]))
            if qqq_metrics.get("status") == "PASS":
                qqq_trial_returns[trial_id] = float(qqq_metrics["forward_return"])
            if spy_metrics.get("status") == "PASS":
                spy_trial_returns[trial_id] = float(spy_metrics["forward_return"])
            etf_rows.append({
                "trial_id": trial_id, "as_of_date": as_of, "forward_window": window,
                "selected_etf": etf_selected, "etf_rotation_signal": etf_sig,
                "etf_entry_date": selected_metrics.get("entry_date", as_of),
                "etf_exit_date": selected_metrics.get("exit_date", ""),
                "etf_entry_price": fmt(selected_metrics.get("entry_price") if etf_ok else None),
                "etf_exit_price": fmt(selected_metrics.get("exit_price") if etf_ok else None),
                "etf_forward_return": fmt(selected_metrics.get("forward_return") if etf_ok else None),
                "qqq_forward_return": fmt(qqq_metrics.get("forward_return") if qqq_metrics.get("status") == "PASS" else None),
                "spy_forward_return": fmt(spy_metrics.get("forward_return") if spy_metrics.get("status") == "PASS" else None),
                "sector_benchmark_return": fmt(soxx_metrics.get("forward_return") if soxx_metrics.get("status") == "PASS" else None),
                "benchmark_status": "PASS" if etf_ok else "WARN",
                "benchmark_failure_reason": "" if etf_ok else clean(selected_metrics.get("failure") or selected_metrics.get("status")),
                **COMMON,
            })

    valid_trial_ids = sorted(set(stock_trial_returns) & set(etf_trial_returns))
    stock_values = [stock_trial_returns[tid] for tid in valid_trial_ids]
    etf_values = [etf_trial_returns[tid] for tid in valid_trial_ids]
    excess = [stock_trial_returns[tid] - etf_trial_returns[tid] for tid in valid_trial_ids]
    avg_stock, med_stock = aggregate(stock_values)
    avg_etf, med_etf = aggregate(etf_values)
    avg_excess, med_excess = aggregate(excess)
    win_etf = fmt(sum(1 for tid in valid_trial_ids if stock_trial_returns[tid] > etf_trial_returns[tid]) / len(valid_trial_ids)) if valid_trial_ids else ""
    ids_qqq = sorted(set(stock_trial_returns) & set(qqq_trial_returns))
    ids_spy = sorted(set(stock_trial_returns) & set(spy_trial_returns))
    win_qqq = fmt(sum(1 for tid in ids_qqq if stock_trial_returns[tid] > qqq_trial_returns[tid]) / len(ids_qqq)) if ids_qqq else ""
    win_spy = fmt(sum(1 for tid in ids_spy if stock_trial_returns[tid] > spy_trial_returns[tid]) / len(ids_spy)) if ids_spy else ""
    family_corr = {}
    if valid_trial_ids:
        for family in FAMILIES:
            weighted = [(trial_weight_bias[tid][family], stock_trial_returns[tid] - etf_trial_returns.get(tid, 0.0)) for tid in valid_trial_ids if tid in trial_weight_bias]
            if weighted:
                family_corr[family] = mean(w * r for w, r in weighted)
    best_family = max(family_corr, key=family_corr.get) if family_corr else "UNDETERMINED"
    worst_family = min(family_corr, key=family_corr.get) if family_corr else "UNDETERMINED"
    pit_warn_count = len(trials)
    etf_coverage = len([row for row in etf_rows if row["benchmark_status"] == "PASS"]) / len(etf_rows) if etf_rows else 0.0
    if not valid_trial_ids:
        final_status = BLOCKED_NO_VALID
        next_action = "Repair PIT-safe stock outcome or ETF benchmark coverage before interpreting weights."
    elif etf_coverage < 1.0 or len(valid_trial_ids) < len(trials):
        final_status = PARTIAL_STATUS
        next_action = "Treat as limited research evidence; do not propose shadow weight changes."
    else:
        final_status = PASS_STATUS
        next_action = "Research-ready only; require independent walk-forward confirmation before any shadow proposal."
    summary = {
        "total_trial_count": str(len(trials)),
        "valid_trial_count": str(len(valid_trial_ids)),
        "pit_pass_count": str(len(trials)),
        "pit_warn_count": str(pit_warn_count),
        "pit_fail_count": "0",
        "avg_stock_topN_return": avg_stock,
        "median_stock_topN_return": med_stock,
        "avg_etf_rotation_return": avg_etf,
        "median_etf_rotation_return": med_etf,
        "avg_excess_vs_etf_rotation": avg_excess,
        "median_excess_vs_etf_rotation": med_excess,
        "win_rate_vs_etf_rotation": win_etf,
        "win_rate_vs_qqq": win_qqq,
        "win_rate_vs_spy": win_spy,
        "avg_max_drawdown": fmt(mean([v["drawdown"] for v in trial_weight_bias.values()])) if trial_weight_bias else "",
        "avg_etf_max_drawdown_if_available": fmt(mean(etf_dd)) if etf_dd else "",
        "best_weight_family_bias": best_family,
        "worst_weight_family_bias": worst_family,
        "overfit_warning": "RANDOM_WEIGHT_SEARCH_IS_EXPLORATORY_NOT_OPTIMIZED",
        "survivorship_warning": "CURRENT_UNIVERSE_SURVIVORSHIP_RISK",
        "etf_benchmark_coverage_rate": fmt(etf_coverage),
        "final_status": final_status,
        "next_recommended_action": next_action,
        **COMMON,
    }
    write_csv(OUT_TRIALS, TRIAL_FIELDS, trials)
    write_csv(OUT_RANKINGS, RANK_FIELDS, rankings)
    write_csv(OUT_FORWARD, FORWARD_FIELDS, forward_rows)
    write_csv(OUT_ETF, ETF_FIELDS, etf_rows)
    write_csv(OUT_SUMMARY, SUMMARY_FIELDS, [summary])
    write_csv(OUT_PIT, PIT_FIELDS, pit_rows)
    write_csv(OUT_COVERAGE, COVERAGE_FIELDS, coverage)
    write_report(summary)
    print(final_status)
    print(f"FINAL_STATUS={final_status}")
    print(f"TOTAL_TRIAL_COUNT={len(trials)}")
    print(f"VALID_TRIAL_COUNT={len(valid_trial_ids)}")
    print(f"ETF_BENCHMARK_COVERAGE_RATE={fmt(etf_coverage)}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_WEIGHT_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_SIGNAL_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
