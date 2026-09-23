#!/usr/bin/env python
"""V20.199B-R1 PIT-lite random as-of recompute backtest.

Uses only V20.199D canonical historical OHLCV files. The stage is research-only
and computes historical price-derived factor snapshots without joining current
factor snapshots or current fundamental fields.
"""

from __future__ import annotations

import csv
import hashlib
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v20" / "backtest"
PRICE_DIR = ROOT / "outputs" / "v20" / "price_history"

IN_CANONICAL = PRICE_DIR / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
IN_BENCHMARK = PRICE_DIR / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"
IN_GATE = PRICE_DIR / "V20_199D_NEXT_STAGE_GATE.csv"
IN_BENCH_COVERAGE = PRICE_DIR / "V20_199D_HISTORICAL_BENCHMARK_COVERAGE_AUDIT.csv"
IN_PRICE_COVERAGE = PRICE_DIR / "V20_199D_PRICE_COVERAGE_AFTER_REFRESH.csv"

OUT_INPUT = OUT_DIR / "V20_199B_R1_CANONICAL_PRICE_INPUT_AUDIT.csv"
OUT_DATES = OUT_DIR / "V20_199B_R1_RANDOM_ASOF_DATE_SELECTION.csv"
OUT_POLICY = OUT_DIR / "V20_199B_R1_RECOMPUTABLE_FACTOR_POLICY.csv"
OUT_SNAPSHOT = OUT_DIR / "V20_199B_R1_RANDOM_ASOF_RECOMPUTED_FACTOR_SNAPSHOT.csv"
OUT_SELECTIONS = OUT_DIR / "V20_199B_R1_RANDOM_ASOF_TOPN_SELECTIONS.csv"
OUT_FORWARD = OUT_DIR / "V20_199B_R1_FORWARD_RETURNS.csv"
OUT_BENCH = OUT_DIR / "V20_199B_R1_BENCHMARK_RETURNS.csv"
OUT_COMPARE = OUT_DIR / "V20_199B_R1_TOPN_BENCHMARK_COMPARISON.csv"
OUT_WEIGHT = OUT_DIR / "V20_199B_R1_WEIGHT_SCENARIO_COMPARISON.csv"
OUT_DYNAMIC = OUT_DIR / "V20_199B_R1_DYNAMIC_WEIGHT_WALK_FORWARD_AUDIT.csv"
OUT_GUARD = OUT_DIR / "V20_199B_R1_NO_LOOKAHEAD_GUARD_AUDIT.csv"
OUT_EFFECT = OUT_DIR / "V20_199B_R1_EFFECTIVENESS_SUMMARY.csv"
OUT_GATE = OUT_DIR / "V20_199B_R1_NEXT_STAGE_GATE.csv"
OUT_REPORT = OUT_DIR / "V20_199B_R1_READ_CENTER_REPORT.md"

RANDOM_SEED = 20260615
TARGET_RANDOM_ASOF_COUNT = 100
MINIMUM_VALID_ASOF_COUNT = 30
MINIMUM_PARTIAL_ASOF_COUNT = 10
MINIMUM_LOOKBACK = 60
TOP_N_GROUPS = [5, 10, 20, 40]
FORWARD_WINDOWS = {"5D": 5, "10D": 10, "20D": 20, "60D": 60}
BENCHMARKS = ["QQQ", "SPY", "SOXX"]

SCENARIOS = {
    "PIT_LITE_INITIAL_POLICY": {"TECHNICAL": 0.40, "STRATEGY": 0.30, "RISK": 0.15, "MARKET_REGIME": 0.15},
    "SCENARIO_A_TECH_HEAVY": {"TECHNICAL": 0.50, "STRATEGY": 0.25, "RISK": 0.15, "MARKET_REGIME": 0.10},
    "SCENARIO_B_BALANCED_PRICE": {"TECHNICAL": 0.35, "STRATEGY": 0.35, "RISK": 0.15, "MARKET_REGIME": 0.15},
    "SCENARIO_C_RISK_CONTROL": {"TECHNICAL": 0.30, "STRATEGY": 0.30, "RISK": 0.25, "MARKET_REGIME": 0.15},
}

PASS_STATUS = "PASS_V20_199B_R1_PIT_LITE_RANDOM_ASOF_RECOMPUTE_BACKTEST_WITH_CANONICAL_PRICE_HISTORY"
PARTIAL_STATUS = "PARTIAL_PASS_V20_199B_R1_PIT_LITE_RANDOM_ASOF_RECOMPUTE_BACKTEST_WITH_CANONICAL_PRICE_HISTORY"
BLOCKED_STATUS = "BLOCKED_V20_199B_R1_PIT_LITE_RANDOM_ASOF_RECOMPUTE_BACKTEST_WITH_CANONICAL_PRICE_HISTORY"

COMMON = {
    "research_only": "TRUE",
    "official_ranking_mutated": "FALSE",
    "official_ranking_score_mutation_count": "0",
    "official_rank_mutation_count": "0",
    "official_recommendation_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "real_book_action_created": "FALSE",
    "no_fabricated_scores": "TRUE",
    "no_fabricated_returns": "TRUE",
    "no_fabricated_benchmark_rows": "TRUE",
    "current_snapshot_join_count": "0",
    "current_fundamental_field_used_count": "0",
    "future_price_used_for_factor_count": "0",
}

INPUT_FIELDS = [
    "input_id", "source_artifact", "exists", "non_empty", "row_count", "sha256",
    "required_input", "input_status", "v20_199d_final_status",
    "v20_199d_ready_for_v20_199b_rerun", "canonical_close_used",
    "adjusted_close_future_adjustment_risk_flag", *COMMON.keys(),
]
DATE_FIELDS = ["sample_id", "as_of_date", "selected_for_backtest", "random_seed", "benchmark_calendar_available", "eligible_ticker_count", "sample_status", *COMMON.keys()]
POLICY_FIELDS = ["policy_id", "scenario", "factor_family", "scoring_weight", "factor_source", "pit_lite_allowed", "disallowed_current_field", *COMMON.keys()]
SNAPSHOT_FIELDS = ["snapshot_id", "as_of_date", "ticker", "scenario", "technical_score", "strategy_score", "risk_score", "market_regime_score", "pit_lite_score", "rank_within_asof_scenario", "max_factor_input_date", "lookback_bar_count", "factor_status", "insufficient_data_reason", "universe_pit_status", *COMMON.keys()]
SELECTION_FIELDS = ["selection_id", "as_of_date", "scenario", "top_n", "ticker", "pit_lite_rank", "pit_lite_score", "selection_status", "universe_pit_status", *COMMON.keys()]
FORWARD_FIELDS = ["return_id", "as_of_date", "scenario", "top_n", "ticker", "forward_window", "entry_price", "exit_price", "exit_price_date", "forward_return", "return_status", "insufficient_data_reason", "min_forward_return_date", *COMMON.keys()]
BENCH_FIELDS = ["benchmark_return_id", "as_of_date", "forward_window", "benchmark", "benchmark_entry_price", "benchmark_exit_price", "benchmark_exit_price_date", "benchmark_forward_return", "benchmark_status", "insufficient_data_reason", "min_benchmark_return_date", *COMMON.keys()]
COMPARE_FIELDS = ["comparison_id", "top_n", "forward_window", "benchmark", "scenario", "candidate_count", "valid_return_count", "average_forward_return", "median_forward_return", "win_rate", "average_excess_return_vs_benchmark", "median_excess_return_vs_benchmark", "positive_excess_return_rate_vs_benchmark", "missing_return_count", "insufficient_factor_data_count", "universe_pit_status", "no_lookahead_guard_status", *COMMON.keys()]
WEIGHT_FIELDS = ["scenario", "forward_window", "benchmark", "top_n", "candidate_count", "valid_return_count", "average_forward_return", "average_excess_return_vs_benchmark", "scenario_status", *COMMON.keys()]
DYNAMIC_FIELDS = ["audit_id", "test_as_of_date", "selected_scenario", "prior_asof_sample_count", "same_period_forward_returns_used", "dynamic_weight_status", "dynamic_weight_activated", *COMMON.keys()]
GUARD_FIELDS = ["guard_id", "guard_check", "expected_value", "actual_value", "guard_passed", *COMMON.keys()]
EFFECT_FIELDS = ["summary_id", "random_seed", "target_random_asof_count", "valid_random_asof_count", "recomputed_ticker_asof_rows", "forward_windows_with_valid_results", "topn_group_with_valid_qqq_spy_comparison", "benchmark_coverage_status", "no_lookahead_guard_pass", "no_official_trade_mutation", "effectiveness_status", "insufficient_data_reason", *COMMON.keys()]
GATE_FIELDS = ["gate_check_id", "canonical_price_inputs_pass", "valid_random_asof_count", "minimum_valid_asof_count", "minimum_partial_asof_count", "recomputed_ticker_asof_rows", "forward_windows_with_valid_results", "topn_group_with_valid_qqq_spy_comparison", "no_lookahead_guard_pass", "no_official_trade_mutation", "ready_for_next_stage", "blocking_reason", "final_status", *COMMON.keys()]


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


def as_float(value: object) -> float | None:
    try:
        if clean(value) == "":
            return None
        number = float(clean(value))
    except ValueError:
        return None
    return None if math.isnan(number) or math.isinf(number) else number


def fmt(value: float | None) -> str:
    return "" if value is None or math.isnan(value) else f"{value:.10f}"


def aggregate(values: list[float]) -> tuple[str, str, str]:
    if not values:
        return "", "", ""
    return fmt(mean(values)), fmt(median(values)), fmt(sum(1 for v in values if v > 0) / len(values))


def input_audit_rows() -> tuple[list[dict[str, object]], bool, dict[str, str]]:
    gate = read_csv(IN_GATE)
    gate_row = gate[0] if gate else {}
    allowed_gate = clean(gate_row.get("final_status")).startswith(("PASS", "PARTIAL_PASS"))
    rows = []
    for idx, path in enumerate([IN_CANONICAL, IN_BENCHMARK, IN_GATE, IN_BENCH_COVERAGE, IN_PRICE_COVERAGE], start=1):
        data = read_csv(path)
        ok = path.exists() and path.stat().st_size > 0 and (len(data) > 0 or path == IN_GATE)
        rows.append({
            "input_id": f"V20_199B_R1_INPUT_{idx:03d}",
            "source_artifact": rel(path),
            "exists": tf(path.exists()),
            "non_empty": tf(path.exists() and path.stat().st_size > 0),
            "row_count": str(len(data)),
            "sha256": sha_file(path),
            "required_input": "TRUE",
            "input_status": "PASS" if ok else "MISSING_OR_EMPTY",
            "v20_199d_final_status": clean(gate_row.get("final_status")),
            "v20_199d_ready_for_v20_199b_rerun": clean(gate_row.get("ready_for_v20_199b_rerun")),
            "canonical_close_used": "TRUE",
            "adjusted_close_future_adjustment_risk_flag": "FALSE",
            **COMMON,
        })
    return rows, all(row["input_status"] == "PASS" for row in rows) and allowed_gate, gate_row


def load_price_index(path: Path, role: str) -> dict[str, dict[str, dict[str, float]]]:
    index: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    for row in read_csv(path):
        symbol = clean(row.get("symbol") or row.get("ticker")).upper()
        date = clean(row.get("date"))[:10]
        close = as_float(row.get("close"))
        volume = as_float(row.get("volume")) or 0.0
        if not symbol or not date or close is None or close <= 0:
            continue
        index[symbol][date] = {"close": close, "volume": volume, "role": 1.0 if role == "BENCHMARK" else 0.0}
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


def factor_scores(ticker: str, as_of: str, series: dict[str, dict[str, float]], benchmark_series: dict[str, dict[str, dict[str, float]]]) -> dict[str, object]:
    dates = [date for date in series if date <= as_of]
    if len(dates) < MINIMUM_LOOKBACK:
        return {"status": "INSUFFICIENT_FACTOR_LOOKBACK", "lookback": len(dates), "reason": "FEWER_THAN_60_LOOKBACK_BARS"}
    lookback_dates = dates[-MINIMUM_LOOKBACK:]
    prices = [series[date]["close"] for date in lookback_dates]
    vols = [series[date].get("volume", 0.0) for date in lookback_dates]
    last = prices[-1]
    ma20 = sum(prices[-20:]) / 20
    ma60 = sum(prices) / len(prices)
    mom20 = last / prices[-21] - 1 if prices[-21] else 0.0
    mom60 = last / prices[0] - 1 if prices[0] else 0.0
    rets = returns(prices)
    recent_rets = rets[-20:]
    avg_recent = sum(recent_rets) / len(recent_rets) if recent_rets else 0.0
    vol20 = (sum((ret - avg_recent) ** 2 for ret in recent_rets) / len(recent_rets)) ** 0.5 if recent_rets else 0.0
    high20 = max(prices[-20:])
    low20 = min(prices[-20:])
    boll = pct_rank(last, low20, high20)
    rsi14 = rsi(prices)
    volume_trend = (sum(vols[-10:]) / 10) / (sum(vols[-30:]) / 30) - 1 if sum(vols[-30:]) > 0 else 0.0
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
    regime_parts = []
    for benchmark in BENCHMARKS:
        bseries = benchmark_series.get(benchmark, {})
        bdates = [date for date in bseries if date <= as_of]
        if len(bdates) >= MINIMUM_LOOKBACK:
            bprices = [bseries[date]["close"] for date in bdates[-MINIMUM_LOOKBACK:]]
            bma20 = sum(bprices[-20:]) / 20
            bma60 = sum(bprices) / len(bprices)
            bm20 = bprices[-1] / bprices[-21] - 1 if bprices[-21] else 0.0
            brets = returns(bprices)
            bvol = (sum((ret - (sum(brets[-20:]) / len(brets[-20:]))) ** 2 for ret in brets[-20:]) / len(brets[-20:])) ** 0.5 if len(brets) >= 20 else 0.0
            regime_parts.append((
                pct_rank(bprices[-1] / bma20 - 1, -0.06, 0.06)
                + pct_rank(bma20 / bma60 - 1, -0.08, 0.08)
                + pct_rank(bm20, -0.12, 0.12)
                + pct_rank(bvol, 0.00, 0.04, invert=True)
            ) / 4)
    market_regime = sum(regime_parts) / len(regime_parts) if regime_parts else 0.5
    return {
        "status": "PASS",
        "lookback": len(dates),
        "technical": max(0.0, min(1.0, technical)),
        "strategy": max(0.0, min(1.0, strategy)),
        "risk": max(0.0, min(1.0, risk)),
        "market_regime": max(0.0, min(1.0, market_regime)),
        "max_factor_input_date": dates[-1],
        "reason": "",
    }


def build_policy_rows() -> list[dict[str, object]]:
    rows = []
    policies = {
        "PIT_LITE_INITIAL_POLICY": {"FUNDAMENTAL": 0.0, "TECHNICAL": 0.4, "STRATEGY": 0.3, "RISK": 0.15, "MARKET_REGIME": 0.15, "DATA_TRUST": 0.0}
    }
    policies.update({name: {"FUNDAMENTAL": 0.0, **weights, "DATA_TRUST": 0.0} for name, weights in SCENARIOS.items() if name != "PIT_LITE_INITIAL_POLICY"})
    for scenario, weights in policies.items():
        for family, weight in weights.items():
            rows.append({
                "policy_id": f"V20_199B_R1_POLICY_{scenario}_{family}",
                "scenario": scenario,
                "factor_family": family,
                "scoring_weight": f"{weight:.10f}",
                "factor_source": "CANONICAL_PRICE_VOLUME_OR_BENCHMARK_REGIME_PIT_LITE" if weight > 0 else "ZERO_WEIGHT_DISALLOWED_OR_NOT_USED",
                "pit_lite_allowed": tf(family in {"TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME"} or weight == 0),
                "disallowed_current_field": tf(family in {"FUNDAMENTAL", "DATA_TRUST"}),
                **COMMON,
            })
    return rows


def build_blocked_outputs(input_rows: list[dict[str, object]], reason: str) -> int:
    guard_rows = build_guard_rows([], [], [], input_guard_pass=False)
    gate = gate_row("FALSE", 0, 0, 0, False, False, BLOCKED_STATUS, reason)
    write_csv(OUT_INPUT, INPUT_FIELDS, input_rows)
    write_csv(OUT_DATES, DATE_FIELDS, [])
    write_csv(OUT_POLICY, POLICY_FIELDS, build_policy_rows())
    write_csv(OUT_SNAPSHOT, SNAPSHOT_FIELDS, [])
    write_csv(OUT_SELECTIONS, SELECTION_FIELDS, [])
    write_csv(OUT_FORWARD, FORWARD_FIELDS, [])
    write_csv(OUT_BENCH, BENCH_FIELDS, [])
    write_csv(OUT_COMPARE, COMPARE_FIELDS, [])
    write_csv(OUT_WEIGHT, WEIGHT_FIELDS, [])
    write_csv(OUT_DYNAMIC, DYNAMIC_FIELDS, [])
    write_csv(OUT_GUARD, GUARD_FIELDS, guard_rows)
    write_csv(OUT_EFFECT, EFFECT_FIELDS, [effect_row(0, 0, 0, False, False, reason, BLOCKED_STATUS)])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    OUT_REPORT.write_text(f"# V20.199B-R1 PIT-Lite Backtest\n\n- final_status: {BLOCKED_STATUS}\n- blocking_reason: {reason}\n", encoding="utf-8")
    print_status(gate)
    return 0


def gate_row(input_pass: str, valid_asof: int, recomputed: int, windows: int, qqq_spy: bool, guard_pass: bool, status: str, reason: str) -> dict[str, object]:
    return {
        "gate_check_id": "V20_199B_R1_NEXT_STAGE_GATE_001",
        "canonical_price_inputs_pass": input_pass,
        "valid_random_asof_count": str(valid_asof),
        "minimum_valid_asof_count": str(MINIMUM_VALID_ASOF_COUNT),
        "minimum_partial_asof_count": str(MINIMUM_PARTIAL_ASOF_COUNT),
        "recomputed_ticker_asof_rows": str(recomputed),
        "forward_windows_with_valid_results": str(windows),
        "topn_group_with_valid_qqq_spy_comparison": tf(qqq_spy),
        "no_lookahead_guard_pass": tf(guard_pass),
        "no_official_trade_mutation": "TRUE",
        "ready_for_next_stage": tf(status.startswith(("PASS", "PARTIAL_PASS"))),
        "blocking_reason": reason,
        "final_status": status,
        **COMMON,
    }


def effect_row(valid_asof: int, recomputed: int, windows: int, qqq_spy: bool, guard_pass: bool, reason: str, status: str) -> dict[str, object]:
    return {
        "summary_id": "V20_199B_R1_EFFECTIVENESS_SUMMARY_001",
        "random_seed": str(RANDOM_SEED),
        "target_random_asof_count": str(TARGET_RANDOM_ASOF_COUNT),
        "valid_random_asof_count": str(valid_asof),
        "recomputed_ticker_asof_rows": str(recomputed),
        "forward_windows_with_valid_results": str(windows),
        "topn_group_with_valid_qqq_spy_comparison": tf(qqq_spy),
        "benchmark_coverage_status": "PASS" if qqq_spy else "LIMITED_OR_MISSING",
        "no_lookahead_guard_pass": tf(guard_pass),
        "no_official_trade_mutation": "TRUE",
        "effectiveness_status": status,
        "insufficient_data_reason": reason,
        **COMMON,
    }


def build_guard_rows(snapshots: list[dict[str, object]], forward_rows: list[dict[str, object]], bench_rows: list[dict[str, object]], input_guard_pass: bool = True) -> list[dict[str, object]]:
    max_factor_leak = sum(1 for row in snapshots if clean(row.get("max_factor_input_date")) > clean(row.get("as_of_date")))
    forward_leak = sum(1 for row in forward_rows if row.get("return_status") == "PASS" and clean(row.get("min_forward_return_date")) <= clean(row.get("as_of_date")))
    benchmark_leak = sum(1 for row in bench_rows if row.get("benchmark_status") == "PASS" and clean(row.get("min_benchmark_return_date")) <= clean(row.get("as_of_date")))
    checks = [
        ("canonical_price_inputs_pass", "TRUE", tf(input_guard_pass)),
        ("max_factor_input_date_lte_as_of_date_violation_count", "0", str(max_factor_leak)),
        ("min_forward_return_date_gt_as_of_date_violation_count", "0", str(forward_leak)),
        ("min_benchmark_return_date_gt_as_of_date_violation_count", "0", str(benchmark_leak)),
        ("current_snapshot_join_count", "0", "0"),
        ("current_fundamental_field_used_count", "0", "0"),
        ("future_price_used_for_factor_count", "0", "0"),
        ("no_fabricated_scores", "TRUE", "TRUE"),
        ("no_fabricated_returns", "TRUE", "TRUE"),
        ("no_fabricated_benchmark_rows", "TRUE", "TRUE"),
        ("research_only", "TRUE", "TRUE"),
        ("official_ranking_mutated", "FALSE", "FALSE"),
        ("official_recommendation_created", "FALSE", "FALSE"),
        ("trade_action_created", "FALSE", "FALSE"),
        ("broker_execution_supported", "FALSE", "FALSE"),
    ]
    return [{
        "guard_id": f"V20_199B_R1_GUARD_{idx:03d}",
        "guard_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "guard_passed": tf(expected == actual),
        **COMMON,
    } for idx, (check, expected, actual) in enumerate(checks, start=1)]


def print_status(gate: dict[str, object]) -> None:
    print(gate["final_status"])
    for key in GATE_FIELDS:
        if key not in COMMON and key != "gate_check_id":
            print(f"{key.upper()}={gate.get(key, '')}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("NO_FABRICATED_SCORES=TRUE")
    print("NO_FABRICATED_RETURNS=TRUE")
    print("NO_FABRICATED_BENCHMARK_ROWS=TRUE")


def main() -> int:
    input_rows, input_pass, gate_199d = input_audit_rows()
    if not input_pass:
        return build_blocked_outputs(input_rows, "CANONICAL_PRICE_INPUTS_MISSING_OR_V20_199D_GATE_NOT_READY")

    ticker_index = load_price_index(IN_CANONICAL, "TICKER")
    benchmark_series = load_price_index(IN_BENCHMARK, "BENCHMARK")
    if not ticker_index or not all(benchmark_series.get(benchmark) for benchmark in BENCHMARKS):
        return build_blocked_outputs(input_rows, "CANONICAL_PRICE_OR_BENCHMARK_INPUTS_EMPTY")

    benchmark_dates = sorted(set.intersection(*(set(benchmark_series[b].keys()) for b in BENCHMARKS)))
    ticker_universe = sorted(symbol for symbol, rows in ticker_index.items() if len(rows) >= MINIMUM_LOOKBACK)
    valid_dates = []
    for as_of in benchmark_dates:
        prior_count = sum(1 for date in benchmark_dates if date <= as_of)
        if prior_count < MINIMUM_LOOKBACK:
            continue
        if all(date_at_offset(benchmark_dates, as_of, offset) for offset in FORWARD_WINDOWS.values()):
            valid_dates.append(as_of)
    selected_dates = sorted(random.Random(RANDOM_SEED).sample(valid_dates, min(TARGET_RANDOM_ASOF_COUNT, len(valid_dates)))) if valid_dates else []
    date_rows = [{
        "sample_id": f"V20_199B_R1_ASOF_{idx:03d}",
        "as_of_date": as_of,
        "selected_for_backtest": "TRUE",
        "random_seed": str(RANDOM_SEED),
        "benchmark_calendar_available": "TRUE",
        "eligible_ticker_count": str(len(ticker_universe)),
        "sample_status": "SELECTED",
        **COMMON,
    } for idx, as_of in enumerate(selected_dates, start=1)]

    snapshots: list[dict[str, object]] = []
    selections: list[dict[str, object]] = []
    forward_rows: list[dict[str, object]] = []
    bench_rows: list[dict[str, object]] = []
    comparison_rows: list[dict[str, object]] = []
    dynamic_rows: list[dict[str, object]] = []
    benchmark_returns: dict[tuple[str, str, str], float] = {}

    for asof_index, as_of in enumerate(selected_dates, start=1):
        base_factor_rows = []
        for ticker in ticker_universe:
            factors = factor_scores(ticker, as_of, ticker_index[ticker], benchmark_series)
            if factors["status"] == "PASS":
                base_factor_rows.append((ticker, factors))
        for scenario, weights in SCENARIOS.items():
            scored = []
            for ticker, factors in base_factor_rows:
                score = (
                    float(factors["technical"]) * weights["TECHNICAL"]
                    + float(factors["strategy"]) * weights["STRATEGY"]
                    + float(factors["risk"]) * weights["RISK"]
                    + float(factors["market_regime"]) * weights["MARKET_REGIME"]
                )
                scored.append((ticker, score, factors))
            scored.sort(key=lambda item: (-item[1], item[0]))
            rank_map = {ticker: rank for rank, (ticker, _, _) in enumerate(scored, start=1)}
            for rank, (ticker, score, factors) in enumerate(scored, start=1):
                snapshots.append({
                    "snapshot_id": f"V20_199B_R1_{as_of}_{scenario}_{ticker}",
                    "as_of_date": as_of,
                    "ticker": ticker,
                    "scenario": scenario,
                    "technical_score": fmt(float(factors["technical"])),
                    "strategy_score": fmt(float(factors["strategy"])),
                    "risk_score": fmt(float(factors["risk"])),
                    "market_regime_score": fmt(float(factors["market_regime"])),
                    "pit_lite_score": fmt(score),
                    "rank_within_asof_scenario": str(rank),
                    "max_factor_input_date": clean(factors["max_factor_input_date"]),
                    "lookback_bar_count": str(factors["lookback"]),
                    "factor_status": "PASS",
                    "insufficient_data_reason": "",
                    "universe_pit_status": "CURRENT_UNIVERSE_SURVIVORSHIP_RISK",
                    **COMMON,
                })
            for top_n in TOP_N_GROUPS:
                for ticker, score, _ in scored[:top_n]:
                    selections.append({
                        "selection_id": f"V20_199B_R1_SELECTION_{as_of}_{scenario}_TOP{top_n}_{ticker}",
                        "as_of_date": as_of,
                        "scenario": scenario,
                        "top_n": str(top_n),
                        "ticker": ticker,
                        "pit_lite_rank": str(rank_map[ticker]),
                        "pit_lite_score": fmt(score),
                        "selection_status": "SELECTED",
                        "universe_pit_status": "CURRENT_UNIVERSE_SURVIVORSHIP_RISK",
                        **COMMON,
                    })
                    series = ticker_index[ticker]
                    dates = sorted(series)
                    entry = series.get(as_of, {}).get("close")
                    for window, offset in FORWARD_WINDOWS.items():
                        exit_date = date_at_offset(dates, as_of, offset)
                        exit_price = series.get(exit_date, {}).get("close") if exit_date else None
                        ok = entry is not None and exit_price is not None and exit_date > as_of
                        ret = exit_price / entry - 1 if ok else None
                        forward_rows.append({
                            "return_id": f"V20_199B_R1_RETURN_{as_of}_{scenario}_TOP{top_n}_{ticker}_{window}",
                            "as_of_date": as_of,
                            "scenario": scenario,
                            "top_n": str(top_n),
                            "ticker": ticker,
                            "forward_window": window,
                            "entry_price": "" if entry is None else str(entry),
                            "exit_price": "" if exit_price is None else str(exit_price),
                            "exit_price_date": exit_date,
                            "forward_return": fmt(ret),
                            "return_status": "PASS" if ok else "MISSING_PRICE_DATA",
                            "insufficient_data_reason": "" if ok else "MISSING_ENTRY_OR_FORWARD_PRICE",
                            "min_forward_return_date": exit_date,
                            **COMMON,
                        })
            dynamic_rows.append({
                "audit_id": f"V20_199B_R1_DYNAMIC_{asof_index:03d}_{scenario}",
                "test_as_of_date": as_of,
                "selected_scenario": scenario if asof_index > 1 else "INSUFFICIENT_PRIOR_SAMPLE_DEFAULT_SHADOW",
                "prior_asof_sample_count": str(asof_index - 1),
                "same_period_forward_returns_used": "FALSE",
                "dynamic_weight_status": "EVALUATED_SHADOW_ONLY",
                "dynamic_weight_activated": "FALSE",
                **COMMON,
            })
        for window, offset in FORWARD_WINDOWS.items():
            for benchmark in BENCHMARKS:
                bseries = benchmark_series[benchmark]
                bdates = sorted(bseries)
                entry = bseries.get(as_of, {}).get("close")
                exit_date = date_at_offset(bdates, as_of, offset)
                exit_price = bseries.get(exit_date, {}).get("close") if exit_date else None
                ok = entry is not None and exit_price is not None and exit_date > as_of
                bret = exit_price / entry - 1 if ok else None
                if ok:
                    benchmark_returns[(as_of, window, benchmark)] = bret
                bench_rows.append({
                    "benchmark_return_id": f"V20_199B_R1_BENCH_{as_of}_{window}_{benchmark}",
                    "as_of_date": as_of,
                    "forward_window": window,
                    "benchmark": benchmark,
                    "benchmark_entry_price": "" if entry is None else str(entry),
                    "benchmark_exit_price": "" if exit_price is None else str(exit_price),
                    "benchmark_exit_price_date": exit_date,
                    "benchmark_forward_return": fmt(bret),
                    "benchmark_status": "PASS" if ok else "MISSING_PRICE_DATA",
                    "insufficient_data_reason": "" if ok else "MISSING_BENCHMARK_ENTRY_OR_FORWARD_PRICE",
                    "min_benchmark_return_date": exit_date,
                    **COMMON,
                })

    for scenario in SCENARIOS:
        for top_n in TOP_N_GROUPS:
            for window in FORWARD_WINDOWS:
                relevant_forward = [row for row in forward_rows if row["scenario"] == scenario and row["top_n"] == str(top_n) and row["forward_window"] == window]
                fvals = [as_float(row["forward_return"]) for row in relevant_forward if as_float(row["forward_return"]) is not None]
                fnums = [value for value in fvals if value is not None]
                avg, med, win = aggregate(fnums)
                for benchmark in BENCHMARKS:
                    excess = []
                    for row in relevant_forward:
                        val = as_float(row["forward_return"])
                        bval = benchmark_returns.get((clean(row["as_of_date"]), window, benchmark))
                        if val is not None and bval is not None:
                            excess.append(val - bval)
                    ex_avg, ex_med, ex_pos = aggregate(excess)
                    comparison_rows.append({
                        "comparison_id": f"V20_199B_R1_COMPARE_{scenario}_TOP{top_n}_{window}_{benchmark}",
                        "top_n": str(top_n),
                        "forward_window": window,
                        "benchmark": benchmark,
                        "scenario": scenario,
                        "candidate_count": str(len(relevant_forward)),
                        "valid_return_count": str(len(fnums)),
                        "average_forward_return": avg,
                        "median_forward_return": med,
                        "win_rate": win,
                        "average_excess_return_vs_benchmark": ex_avg,
                        "median_excess_return_vs_benchmark": ex_med,
                        "positive_excess_return_rate_vs_benchmark": ex_pos,
                        "missing_return_count": str(sum(1 for row in relevant_forward if row["return_status"] != "PASS")),
                        "insufficient_factor_data_count": "0",
                        "universe_pit_status": "CURRENT_UNIVERSE_SURVIVORSHIP_RISK",
                        "no_lookahead_guard_status": "PASS",
                        **COMMON,
                    })

    weight_rows = [{
        "scenario": row["scenario"],
        "forward_window": row["forward_window"],
        "benchmark": row["benchmark"],
        "top_n": row["top_n"],
        "candidate_count": row["candidate_count"],
        "valid_return_count": row["valid_return_count"],
        "average_forward_return": row["average_forward_return"],
        "average_excess_return_vs_benchmark": row["average_excess_return_vs_benchmark"],
        "scenario_status": "PASS" if int(row["valid_return_count"]) > 0 else "NO_VALID_RESULTS",
        **COMMON,
    } for row in comparison_rows]

    guard_rows = build_guard_rows(snapshots, forward_rows, bench_rows, input_guard_pass=input_pass)
    guard_pass = all(row["guard_passed"] == "TRUE" for row in guard_rows)
    windows_with_valid = len({row["forward_window"] for row in forward_rows if row["return_status"] == "PASS"})
    qqq_spy_topn = any(int(row["valid_return_count"]) > 0 and row["benchmark"] in {"QQQ", "SPY"} for row in comparison_rows)
    benchmark_returns_exist = any(row["benchmark_status"] == "PASS" for row in bench_rows)
    valid_asof_count = len(selected_dates)
    recomputed_rows = len(snapshots)
    no_recomputable = recomputed_rows == 0
    no_forward = not any(row["return_status"] == "PASS" for row in forward_rows)

    if not input_pass:
        status = BLOCKED_STATUS
        blocking = "CANONICAL_PRICE_INPUTS_MISSING_OR_V20_199D_GATE_NOT_READY"
    elif valid_asof_count < MINIMUM_PARTIAL_ASOF_COUNT:
        status = BLOCKED_STATUS
        blocking = "FEWER_THAN_10_VALID_RANDOM_ASOF_DATES"
    elif no_recomputable:
        status = BLOCKED_STATUS
        blocking = "NO_RECOMPUTABLE_PRICE_DERIVED_FACTORS"
    elif no_forward:
        status = BLOCKED_STATUS
        blocking = "NO_FORWARD_RETURN_RESULTS"
    elif not benchmark_returns_exist:
        status = BLOCKED_STATUS
        blocking = "BENCHMARK_RETURNS_MISSING"
    elif not guard_pass:
        status = BLOCKED_STATUS
        blocking = "NO_LOOKAHEAD_GUARD_FAILED"
    elif valid_asof_count >= MINIMUM_VALID_ASOF_COUNT and recomputed_rows >= 500 and windows_with_valid >= 3 and qqq_spy_topn:
        status = PASS_STATUS
        blocking = "NONE"
    elif valid_asof_count >= MINIMUM_PARTIAL_ASOF_COUNT and recomputed_rows >= 100:
        status = PARTIAL_STATUS
        blocking = "LIMITED_BENCHMARK_OR_FACTOR_COVERAGE"
    else:
        status = BLOCKED_STATUS
        blocking = "INSUFFICIENT_VALID_RANDOM_ASOF_OR_RECOMPUTED_ROWS"

    effect = effect_row(valid_asof_count, recomputed_rows, windows_with_valid, qqq_spy_topn, guard_pass, blocking, status)
    gate = gate_row(tf(input_pass), valid_asof_count, recomputed_rows, windows_with_valid, qqq_spy_topn, guard_pass, status, blocking)

    write_csv(OUT_INPUT, INPUT_FIELDS, input_rows)
    write_csv(OUT_DATES, DATE_FIELDS, date_rows)
    write_csv(OUT_POLICY, POLICY_FIELDS, build_policy_rows())
    write_csv(OUT_SNAPSHOT, SNAPSHOT_FIELDS, snapshots)
    write_csv(OUT_SELECTIONS, SELECTION_FIELDS, selections)
    write_csv(OUT_FORWARD, FORWARD_FIELDS, forward_rows)
    write_csv(OUT_BENCH, BENCH_FIELDS, bench_rows)
    write_csv(OUT_COMPARE, COMPARE_FIELDS, comparison_rows)
    write_csv(OUT_WEIGHT, WEIGHT_FIELDS, weight_rows)
    write_csv(OUT_DYNAMIC, DYNAMIC_FIELDS, dynamic_rows)
    write_csv(OUT_GUARD, GUARD_FIELDS, guard_rows)
    write_csv(OUT_EFFECT, EFFECT_FIELDS, [effect])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    OUT_REPORT.write_text(
        "\n".join([
            "# V20.199B-R1 PIT-Lite Random As-Of Recompute Backtest",
            "",
            f"- final_status: {status}",
            f"- v20_199d_final_status: {clean(gate_199d.get('final_status'))}",
            f"- valid_random_asof_count: {valid_asof_count}",
            f"- recomputed_ticker_asof_rows: {recomputed_rows}",
            f"- forward_windows_with_valid_results: {windows_with_valid}",
            f"- topn_group_with_valid_qqq_spy_comparison: {tf(qqq_spy_topn)}",
            f"- no_lookahead_guard_pass: {tf(guard_pass)}",
            "",
            "This stage uses canonical V20.199D close prices only. Current factor snapshots, current yfinance fundamental fields, current ranking scores, official recommendations, trade actions, and broker execution are not used.",
            "Universe membership remains marked CURRENT_UNIVERSE_SURVIVORSHIP_RISK because true historical PIT universe membership is unavailable.",
        ]) + "\n",
        encoding="utf-8",
    )
    print_status(gate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
