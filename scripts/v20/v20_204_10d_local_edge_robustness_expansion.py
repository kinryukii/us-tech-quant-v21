#!/usr/bin/env python
"""V20.204 10D local edge robustness expansion.

Runs a 10D-only research expansion using the V20.201 PIT-safe random-weight
framework helpers, then tests the expanded 10D evidence for outlier sensitivity,
bootstrap confidence, leave-one-cluster robustness, and weight-bias repeatability.
"""

from __future__ import annotations

import csv
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

import v20_201_random_weight_pit_forward_backtest_consolidation as v201


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v20" / "random_weight_backtest"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_REQUIRED = [
    OUT_DIR / "V20_201_RANDOM_WEIGHT_TRIALS.csv",
    OUT_DIR / "V20_201_RANDOM_WEIGHT_FORWARD_OUTCOMES.csv",
    OUT_DIR / "V20_201_ETF_ROTATION_BENCHMARK_OUTCOMES.csv",
    OUT_DIR / "V20_202_FORWARD_WINDOW_EFFECTIVENESS.csv",
    OUT_DIR / "V20_202_SHADOW_WEIGHT_READINESS_GATE.csv",
    OUT_DIR / "V20_203_LOCAL_EDGE_OBSERVATION_GATE.csv",
    OUT_DIR / "V20_203_OUTLIER_SENSITIVITY_CHECK.csv",
    v201.IN_STOCK,
    v201.IN_BENCH,
]

OUT_TRIALS = OUT_DIR / "V20_204_10D_EXPANDED_TRIALS.csv"
OUT_FORWARD = OUT_DIR / "V20_204_10D_EXPANDED_FORWARD_OUTCOMES.csv"
OUT_ETF = OUT_DIR / "V20_204_10D_EXPANDED_ETF_BENCHMARK_OUTCOMES.csv"
OUT_SUMMARY = OUT_DIR / "V20_204_10D_ROBUSTNESS_SUMMARY.csv"
OUT_BOOT = OUT_DIR / "V20_204_10D_BOOTSTRAP_CONFIDENCE.csv"
OUT_TRIM = OUT_DIR / "V20_204_10D_TRIMMED_WINSORIZED_ANALYSIS.csv"
OUT_CLUSTER = OUT_DIR / "V20_204_10D_LEAVE_ONE_CLUSTER_OUT.csv"
OUT_BIAS = OUT_DIR / "V20_204_10D_WEIGHT_BIAS_REPEATABILITY.csv"
OUT_GATE = OUT_DIR / "V20_204_10D_ROBUSTNESS_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_204_10D_LOCAL_EDGE_ROBUSTNESS_EXPANSION_REPORT.md"

EXPANDED_TRIAL_COUNT = 1000
TOP_N = 20
FORWARD_WINDOW = "10D"
FORWARD_OFFSET = 10
RANDOM_SEED_BASE = 202606204
BOOTSTRAP_SEED = 2026062041
BOOTSTRAP_ITERATIONS = 1000
BIAS_BOOTSTRAP_ITERATIONS = 500

FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME"]
FAMILY_LOWER = ["fundamental", "technical", "strategy", "risk", "market_regime"]
ALL_FAMILY_LOWER = [*FAMILY_LOWER, "data_trust"]

TRIAL_FIELDS = [
    "trial_id", "seed", "as_of_date", "forward_window", "top_n", "weight_sum",
    "fundamental_weight", "technical_weight", "strategy_weight", "risk_weight",
    "market_regime_weight", "data_trust_weight", "data_trust_used_in_ranking",
    "data_trust_used_as_audit_gate", "pit_validation_status", "etf_benchmark_available",
    "trial_status", "failure_reason", "created_at",
]
FORWARD_FIELDS = [
    "trial_id", "as_of_date", "forward_window", "ticker", "rank", "entry_date",
    "exit_date", "entry_price", "exit_price", "forward_return", "max_forward_drawdown",
    "max_forward_runup", "hit_positive_return", "data_available", "outcome_status",
    "outcome_failure_reason",
]
ETF_FIELDS = [
    "trial_id", "as_of_date", "forward_window", "selected_etf", "etf_rotation_signal",
    "etf_entry_date", "etf_exit_date", "etf_entry_price", "etf_exit_price",
    "etf_forward_return", "qqq_forward_return", "spy_forward_return",
    "sector_benchmark_return", "benchmark_status", "benchmark_failure_reason",
]
SUMMARY_FIELDS = [
    "valid_trial_count", "avg_stock_topN_return", "median_stock_topN_return",
    "avg_etf_rotation_return", "median_etf_rotation_return", "avg_excess_vs_etf_rotation",
    "median_excess_vs_etf_rotation", "win_rate_vs_etf_rotation",
    "positive_excess_rate", "negative_excess_rate", "std_excess", "min_excess",
    "max_excess", "p10_excess", "p25_excess", "p75_excess", "p90_excess",
    "robustness_status",
]
BOOT_FIELDS = [
    "bootstrap_iterations", "mean_excess", "median_excess",
    "mean_excess_ci_lower_95", "mean_excess_ci_upper_95",
    "median_excess_ci_lower_95", "median_excess_ci_upper_95",
    "probability_mean_excess_positive", "probability_median_excess_positive",
    "bootstrap_status",
]
TRIM_FIELDS = [
    "scenario_name", "excluded_or_adjusted_trial_count", "remaining_trial_count",
    "avg_excess_vs_etf_rotation", "median_excess_vs_etf_rotation",
    "win_rate_vs_etf_rotation", "conclusion",
]
CLUSTER_FIELDS = [
    "cluster_type", "excluded_cluster", "excluded_trial_count", "remaining_trial_count",
    "avg_excess_vs_etf_rotation", "median_excess_vs_etf_rotation",
    "win_rate_vs_etf_rotation", "cluster_sensitivity_status",
]
BIAS_FIELDS = [
    "family_name", "avg_weight_all", "avg_weight_top_10pct", "avg_weight_bottom_10pct",
    "top_minus_bottom_weight_delta", "correlation_with_excess",
    "bootstrap_direction_consistency", "repeatability_status",
]
GATE_FIELDS = [
    "final_status", "valid_trial_count", "avg_excess_vs_etf_rotation",
    "median_excess_vs_etf_rotation", "win_rate_vs_etf_rotation",
    "mean_excess_ci_lower_95", "mean_excess_ci_upper_95",
    "probability_mean_excess_positive", "trimmed_5pct_avg_excess",
    "winsorized_5pct_avg_excess", "leave_one_cluster_robust",
    "coherent_weight_bias_detected", "local_edge_observation_recommended",
    "shadow_weight_change_recommended", "reason", "next_recommended_action",
]

STATUS_ROBUST = "PASS_V20_204_10D_LOCAL_EDGE_ROBUST_FOR_OBSERVATION"
STATUS_MIXED = "PARTIAL_PASS_V20_204_10D_EDGE_MIXED_ROBUSTNESS"
STATUS_SMALL = "PARTIAL_PASS_V20_204_INSUFFICIENT_EXPANDED_10D_SAMPLE"
STATUS_NONE = "PASS_V20_204_NO_EXPANDED_10D_EDGE_FOUND"
STATUS_PIT = "BLOCKED_V20_204_PIT_VALIDATION_FAILED"
STATUS_MISSING = "BLOCKED_V20_204_REQUIRED_INPUT_MISSING"


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def num(value: object) -> float | None:
    try:
        text = clean(value)
        if not text:
            return None
        parsed = float(text)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def fmt(value: float | None) -> str:
    return "" if value is None or not math.isfinite(value) else f"{value:.10f}"


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


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


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * pct
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return ordered[int(pos)]
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def corr(xs: list[float], ys: list[float]) -> float | None:
    pairs = [(x, y) for x, y in zip(xs, ys) if math.isfinite(x) and math.isfinite(y)]
    if len(pairs) < 3:
        return None
    x_mean = mean([x for x, _ in pairs])
    y_mean = mean([y for _, y in pairs])
    x_var = sum((x - x_mean) ** 2 for x, _ in pairs)
    y_var = sum((y - y_mean) ** 2 for _, y in pairs)
    if x_var <= 0 or y_var <= 0:
        return None
    return sum((x - x_mean) * (y - y_mean) for x, y in pairs) / math.sqrt(x_var * y_var)


def std(values: list[float]) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return 0.0
    value_mean = mean(values)
    return math.sqrt(sum((value - value_mean) ** 2 for value in values) / (len(values) - 1))


def required_inputs_ready() -> bool:
    return all(path.exists() and path.stat().st_size > 0 and read_csv(path) for path in IN_REQUIRED)


def valid_asof_dates(bench: dict[str, dict[str, dict[str, float]]]) -> list[str]:
    benchmark_dates = sorted(set.intersection(*(set(bench[symbol].keys()) for symbol in v201.BENCHMARKS)))
    dates = []
    for as_of in benchmark_dates:
        if sum(1 for date in benchmark_dates if date <= as_of) < v201.MIN_LOOKBACK:
            continue
        if v201.date_at_offset(benchmark_dates, as_of, FORWARD_OFFSET):
            dates.append(as_of)
    return dates


def score_cache_for_date(
    as_of: str,
    universe: list[str],
    stock: dict[str, dict[str, dict[str, float]]],
    bench: dict[str, dict[str, dict[str, float]]],
    cache: dict[str, list[tuple[str, dict[str, object]]]],
) -> list[tuple[str, dict[str, object]]]:
    if as_of not in cache:
        rows = []
        for ticker in universe:
            scores = v201.family_scores(ticker, as_of, stock[ticker], bench)
            if scores.get("status") == "PASS":
                rows.append((ticker, scores))
        cache[as_of] = rows
    return cache[as_of]


def run_expansion() -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], str]:
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    stock = v201.load_price_index(v201.IN_STOCK)
    bench = v201.load_price_index(v201.IN_BENCH)
    pit_rows, pit_ok = v201.pit_audit_rows()
    if not pit_ok:
        return [], [], [], [], STATUS_PIT
    if not stock or not all(bench.get(symbol) for symbol in v201.BENCHMARKS):
        return [], [], [], [], STATUS_MISSING
    dates = valid_asof_dates(bench)
    universe = sorted(symbol for symbol, rows in stock.items() if len(rows) >= v201.MIN_LOOKBACK)
    if not dates or len(universe) < TOP_N:
        return [], [], [], [], STATUS_MISSING

    date_rng = random.Random(RANDOM_SEED_BASE)
    selected_dates = [date_rng.choice(dates) for _ in range(EXPANDED_TRIAL_COUNT)]
    score_cache: dict[str, list[tuple[str, dict[str, object]]]] = {}
    trials: list[dict[str, object]] = []
    forward_rows: list[dict[str, object]] = []
    etf_rows: list[dict[str, object]] = []
    metrics: list[dict[str, object]] = []

    for idx, as_of in enumerate(selected_dates, start=1):
        seed = RANDOM_SEED_BASE + idx
        trial_id = f"V20_204_10D_TRIAL_{idx:04d}"
        try:
            weights = v201.sample_weights(random.Random(seed))
            weight_failure = ""
        except ValueError as exc:
            weights = {family: 0.0 for family in FAMILIES}
            weight_failure = str(exc)
        scored = []
        if not weight_failure:
            for ticker, scores in score_cache_for_date(as_of, universe, stock, bench, score_cache):
                composite = sum(float(scores[family.lower()]) * weights[family] for family in FAMILIES)
                scored.append((ticker, composite, scores))
        scored.sort(key=lambda item: (-item[1], item[0]))
        top_scores = scored[:TOP_N]
        etf_selected, etf_sig = v201.etf_signal(as_of, bench)
        etf_metrics = v201.forward_metrics(bench[etf_selected], as_of, FORWARD_OFFSET) if etf_selected else {"status": "NO_SIGNAL"}
        qqq_metrics = v201.forward_metrics(bench["QQQ"], as_of, FORWARD_OFFSET)
        spy_metrics = v201.forward_metrics(bench["SPY"], as_of, FORWARD_OFFSET)
        soxx_metrics = v201.forward_metrics(bench["SOXX"], as_of, FORWARD_OFFSET)
        etf_ok = etf_metrics.get("status") == "PASS"
        rank_ok = len(top_scores) >= TOP_N and not weight_failure
        trial_returns = []
        for rank, (ticker, _composite, _scores) in enumerate(top_scores, start=1):
            fwd = v201.forward_metrics(stock[ticker], as_of, FORWARD_OFFSET)
            ok = fwd.get("status") == "PASS"
            if ok:
                trial_returns.append(float(fwd["forward_return"]))
            forward_rows.append({
                "trial_id": trial_id, "as_of_date": as_of, "forward_window": FORWARD_WINDOW,
                "ticker": ticker, "rank": str(rank), "entry_date": fwd.get("entry_date", as_of),
                "exit_date": fwd.get("exit_date", ""), "entry_price": fmt(fwd.get("entry_price") if ok else None),
                "exit_price": fmt(fwd.get("exit_price") if ok else None),
                "forward_return": fmt(fwd.get("forward_return") if ok else None),
                "max_forward_drawdown": fmt(fwd.get("max_drawdown") if ok else None),
                "max_forward_runup": fmt(fwd.get("max_runup") if ok else None),
                "hit_positive_return": tf(float(fwd["forward_return"]) > 0) if ok else "FALSE",
                "data_available": tf(ok), "outcome_status": "PASS" if ok else "WARN",
                "outcome_failure_reason": "" if ok else clean(fwd.get("failure") or fwd.get("status")),
            })
        etf_rows.append({
            "trial_id": trial_id, "as_of_date": as_of, "forward_window": FORWARD_WINDOW,
            "selected_etf": etf_selected, "etf_rotation_signal": etf_sig,
            "etf_entry_date": etf_metrics.get("entry_date", as_of),
            "etf_exit_date": etf_metrics.get("exit_date", ""),
            "etf_entry_price": fmt(etf_metrics.get("entry_price") if etf_ok else None),
            "etf_exit_price": fmt(etf_metrics.get("exit_price") if etf_ok else None),
            "etf_forward_return": fmt(etf_metrics.get("forward_return") if etf_ok else None),
            "qqq_forward_return": fmt(qqq_metrics.get("forward_return") if qqq_metrics.get("status") == "PASS" else None),
            "spy_forward_return": fmt(spy_metrics.get("forward_return") if spy_metrics.get("status") == "PASS" else None),
            "sector_benchmark_return": fmt(soxx_metrics.get("forward_return") if soxx_metrics.get("status") == "PASS" else None),
            "benchmark_status": "PASS" if etf_ok else "WARN",
            "benchmark_failure_reason": "" if etf_ok else clean(etf_metrics.get("failure") or etf_metrics.get("status")),
        })
        valid = bool(rank_ok and etf_ok and trial_returns)
        trials.append({
            "trial_id": trial_id, "seed": str(seed), "as_of_date": as_of,
            "forward_window": FORWARD_WINDOW, "top_n": str(TOP_N), "weight_sum": fmt(sum(weights.values())),
            "fundamental_weight": fmt(weights["FUNDAMENTAL"]), "technical_weight": fmt(weights["TECHNICAL"]),
            "strategy_weight": fmt(weights["STRATEGY"]), "risk_weight": fmt(weights["RISK"]),
            "market_regime_weight": fmt(weights["MARKET_REGIME"]), "data_trust_weight": "0.0000000000",
            "data_trust_used_in_ranking": "FALSE", "data_trust_used_as_audit_gate": "TRUE",
            "pit_validation_status": "PASS", "etf_benchmark_available": tf(etf_ok),
            "trial_status": "VALID" if valid else "WARN",
            "failure_reason": weight_failure or ("" if valid else "INSUFFICIENT_TOPN_OR_FORWARD_BENCHMARK"),
            "created_at": created,
        })
        if valid:
            stock_return = mean(trial_returns)
            etf_return = float(etf_metrics["forward_return"])
            metric = {
                "trial_id": trial_id, "as_of_date": as_of, "forward_window": FORWARD_WINDOW,
                "stock_topN_return": stock_return, "etf_rotation_return": etf_return,
                "excess_vs_etf_rotation": stock_return - etf_return,
                "selected_etf": etf_selected, "etf_rotation_signal": etf_sig,
            }
            for family in FAMILY_LOWER:
                metric[f"{family}_weight"] = float(weights[family.upper()])
            metric["data_trust_weight"] = 0.0
            metrics.append(metric)
    return trials, forward_rows, etf_rows, metrics, "PASS"


def summarize(metrics: list[dict[str, object]]) -> dict[str, object]:
    stocks = [float(row["stock_topN_return"]) for row in metrics]
    etfs = [float(row["etf_rotation_return"]) for row in metrics]
    excess = [float(row["excess_vs_etf_rotation"]) for row in metrics]
    win_rate = sum(1 for value in excess if value > 0) / len(excess) if excess else None
    if not excess:
        robustness = "NO_VALID_10D_TRIALS"
    elif mean(excess) > 0 and median(excess) > 0 and (win_rate or 0.0) >= 0.55:
        robustness = "POSITIVE_CENTRAL_10D_EDGE_REQUIRES_ROBUSTNESS_CHECKS"
    elif mean(excess) > 0 or median(excess) > 0:
        robustness = "MIXED_10D_EDGE"
    else:
        robustness = "NO_EXPANDED_10D_EDGE"
    return {
        "valid_trial_count": str(len(metrics)),
        "avg_stock_topN_return": fmt(mean(stocks) if stocks else None),
        "median_stock_topN_return": fmt(median(stocks) if stocks else None),
        "avg_etf_rotation_return": fmt(mean(etfs) if etfs else None),
        "median_etf_rotation_return": fmt(median(etfs) if etfs else None),
        "avg_excess_vs_etf_rotation": fmt(mean(excess) if excess else None),
        "median_excess_vs_etf_rotation": fmt(median(excess) if excess else None),
        "win_rate_vs_etf_rotation": fmt(win_rate),
        "positive_excess_rate": fmt(sum(1 for value in excess if value > 0) / len(excess) if excess else None),
        "negative_excess_rate": fmt(sum(1 for value in excess if value < 0) / len(excess) if excess else None),
        "std_excess": fmt(std(excess)),
        "min_excess": fmt(min(excess) if excess else None),
        "max_excess": fmt(max(excess) if excess else None),
        "p10_excess": fmt(percentile(excess, 0.10)),
        "p25_excess": fmt(percentile(excess, 0.25)),
        "p75_excess": fmt(percentile(excess, 0.75)),
        "p90_excess": fmt(percentile(excess, 0.90)),
        "robustness_status": robustness,
    }


def bootstrap(metrics: list[dict[str, object]]) -> dict[str, object]:
    values = [float(row["excess_vs_etf_rotation"]) for row in metrics]
    if not values:
        return {
            "bootstrap_iterations": str(BOOTSTRAP_ITERATIONS), "bootstrap_status": "NO_VALID_TRIALS",
        }
    rng = random.Random(BOOTSTRAP_SEED)
    means = []
    medians = []
    for _ in range(BOOTSTRAP_ITERATIONS):
        sample = [values[rng.randrange(len(values))] for _ in values]
        means.append(mean(sample))
        medians.append(median(sample))
    lower_mean = percentile(means, 0.025)
    upper_mean = percentile(means, 0.975)
    lower_med = percentile(medians, 0.025)
    upper_med = percentile(medians, 0.975)
    status = "MEAN_CI_POSITIVE" if lower_mean is not None and lower_mean > 0 else "MEAN_CI_INCLUDES_OR_BELOW_ZERO"
    return {
        "bootstrap_iterations": str(BOOTSTRAP_ITERATIONS),
        "mean_excess": fmt(mean(values)),
        "median_excess": fmt(median(values)),
        "mean_excess_ci_lower_95": fmt(lower_mean),
        "mean_excess_ci_upper_95": fmt(upper_mean),
        "median_excess_ci_lower_95": fmt(lower_med),
        "median_excess_ci_upper_95": fmt(upper_med),
        "probability_mean_excess_positive": fmt(sum(1 for value in means if value > 0) / len(means)),
        "probability_median_excess_positive": fmt(sum(1 for value in medians if value > 0) / len(medians)),
        "bootstrap_status": status,
    }


def adjust_values(values: list[float], scenario: str) -> tuple[list[float], int]:
    ordered = sorted(values)
    n = len(ordered)
    if not n:
        return [], 0
    c1 = max(1, math.ceil(n * 0.01))
    c5 = max(1, math.ceil(n * 0.05))
    if scenario == "exclude_bottom_1pct":
        return ordered[c1:], c1
    if scenario == "exclude_bottom_5pct":
        return ordered[c5:], c5
    if scenario == "exclude_top_1pct":
        return ordered[:n - c1], c1
    if scenario == "exclude_top_5pct":
        return ordered[:n - c5], c5
    if scenario == "exclude_top_bottom_1pct":
        return ordered[c1:n - c1], c1 * 2
    if scenario == "exclude_top_bottom_5pct":
        return ordered[c5:n - c5], c5 * 2
    if scenario == "winsorize_1pct":
        low, high = ordered[c1 - 1], ordered[n - c1]
        return [min(max(value, low), high) for value in values], c1 * 2
    if scenario == "winsorize_5pct":
        low, high = ordered[c5 - 1], ordered[n - c5]
        return [min(max(value, low), high) for value in values], c5 * 2
    return values[:], 0


def trimmed_winsorized(metrics: list[dict[str, object]]) -> list[dict[str, object]]:
    scenarios = [
        "no_exclusion", "exclude_bottom_1pct", "exclude_bottom_5pct",
        "exclude_top_1pct", "exclude_top_5pct", "exclude_top_bottom_1pct",
        "exclude_top_bottom_5pct", "winsorize_1pct", "winsorize_5pct",
    ]
    values = [float(row["excess_vs_etf_rotation"]) for row in metrics]
    rows = []
    for scenario in scenarios:
        adjusted, changed = adjust_values(values, scenario)
        avg_value = mean(adjusted) if adjusted else None
        med_value = median(adjusted) if adjusted else None
        win_rate = sum(1 for value in adjusted if value > 0) / len(adjusted) if adjusted else None
        conclusion = (
            "POSITIVE_AFTER_ADJUSTMENT"
            if avg_value is not None and avg_value > 0 and med_value is not None and med_value > 0 and (win_rate or 0.0) >= 0.55
            else "WEAK_OR_NEGATIVE_AFTER_ADJUSTMENT"
        )
        rows.append({
            "scenario_name": scenario,
            "excluded_or_adjusted_trial_count": str(changed),
            "remaining_trial_count": str(len(adjusted)),
            "avg_excess_vs_etf_rotation": fmt(avg_value),
            "median_excess_vs_etf_rotation": fmt(med_value),
            "win_rate_vs_etf_rotation": fmt(win_rate),
            "conclusion": conclusion,
        })
    return rows


def leave_one_cluster(metrics: list[dict[str, object]]) -> list[dict[str, object]]:
    rows = []
    for cluster_type, field in [
        ("as_of_date", "as_of_date"),
        ("selected_etf", "selected_etf"),
        ("etf_rotation_signal", "etf_rotation_signal"),
    ]:
        clusters = sorted({clean(row[field]) for row in metrics if clean(row[field])})
        for cluster in clusters:
            remaining = [row for row in metrics if clean(row[field]) != cluster]
            excluded = len(metrics) - len(remaining)
            values = [float(row["excess_vs_etf_rotation"]) for row in remaining]
            avg_value = mean(values) if values else None
            med_value = median(values) if values else None
            win_rate = sum(1 for value in values if value > 0) / len(values) if values else None
            robust = bool(avg_value is not None and avg_value > 0 and med_value is not None and med_value > 0 and (win_rate or 0.0) >= 0.55)
            rows.append({
                "cluster_type": cluster_type,
                "excluded_cluster": cluster,
                "excluded_trial_count": str(excluded),
                "remaining_trial_count": str(len(remaining)),
                "avg_excess_vs_etf_rotation": fmt(avg_value),
                "median_excess_vs_etf_rotation": fmt(med_value),
                "win_rate_vs_etf_rotation": fmt(win_rate),
                "cluster_sensitivity_status": "ROBUST_AFTER_CLUSTER_EXCLUSION" if robust else "WEAK_AFTER_CLUSTER_EXCLUSION",
            })
    return rows


def direction_consistency(metrics: list[dict[str, object]], family: str, observed_delta: float) -> float | None:
    if not metrics:
        return None
    if abs(observed_delta) < 1e-12:
        return 0.0
    sign = 1 if observed_delta > 0 else -1
    rng = random.Random(BOOTSTRAP_SEED + len(family))
    consistent = 0
    size = max(1, math.ceil(len(metrics) * 0.10))
    for _ in range(BIAS_BOOTSTRAP_ITERATIONS):
        sample = [metrics[rng.randrange(len(metrics))] for _ in metrics]
        ordered = sorted(sample, key=lambda row: float(row["excess_vs_etf_rotation"]), reverse=True)
        top = ordered[:size]
        bottom = ordered[-size:]
        delta = mean([float(row[f"{family}_weight"]) for row in top]) - mean([float(row[f"{family}_weight"]) for row in bottom])
        if (1 if delta > 0 else -1 if delta < 0 else 0) == sign:
            consistent += 1
    return consistent / BIAS_BOOTSTRAP_ITERATIONS


def weight_bias(metrics: list[dict[str, object]]) -> list[dict[str, object]]:
    ordered = sorted(metrics, key=lambda row: float(row["excess_vs_etf_rotation"]), reverse=True)
    size = max(1, math.ceil(len(ordered) * 0.10)) if ordered else 0
    top = ordered[:size]
    bottom = ordered[-size:] if size else []
    excess = [float(row["excess_vs_etf_rotation"]) for row in metrics]
    rows = []
    for family in ALL_FAMILY_LOWER:
        weights = [float(row[f"{family}_weight"]) for row in metrics]
        top_avg = mean([float(row[f"{family}_weight"]) for row in top]) if top else None
        bottom_avg = mean([float(row[f"{family}_weight"]) for row in bottom]) if bottom else None
        delta = (top_avg - bottom_avg) if top_avg is not None and bottom_avg is not None else 0.0
        family_corr = corr(weights, excess)
        consistency = direction_consistency(metrics, family, delta)
        if family == "data_trust" and not any(weights):
            repeatability = "AUDIT_ONLY_NOT_RANKING_WEIGHT"
        elif consistency is not None and consistency >= 0.70 and abs(delta) >= 0.01 and abs(family_corr or 0.0) >= 0.10:
            repeatability = "REPEATABLE_DIRECTIONAL_BIAS_FOR_OBSERVATION"
        elif consistency is not None and consistency >= 0.60:
            repeatability = "WEAK_DIRECTIONAL_REPEATABILITY"
        else:
            repeatability = "NO_REPEATABLE_BIAS"
        rows.append({
            "family_name": family,
            "avg_weight_all": fmt(mean(weights) if weights else None),
            "avg_weight_top_10pct": fmt(top_avg),
            "avg_weight_bottom_10pct": fmt(bottom_avg),
            "top_minus_bottom_weight_delta": fmt(delta),
            "correlation_with_excess": fmt(family_corr),
            "bootstrap_direction_consistency": fmt(consistency),
            "repeatability_status": repeatability,
        })
    return rows


def build_gate(
    summary: dict[str, object],
    boot: dict[str, object],
    trim: list[dict[str, object]],
    clusters: list[dict[str, object]],
    bias: list[dict[str, object]],
    run_status: str,
) -> dict[str, object]:
    valid_count = int(summary.get("valid_trial_count") or 0)
    avg_excess = num(summary.get("avg_excess_vs_etf_rotation")) or 0.0
    med_excess = num(summary.get("median_excess_vs_etf_rotation")) or 0.0
    win_rate = num(summary.get("win_rate_vs_etf_rotation")) or 0.0
    ci_lower = num(boot.get("mean_excess_ci_lower_95")) or 0.0
    trim5 = next((row for row in trim if row["scenario_name"] == "exclude_top_bottom_5pct"), {})
    winsor5 = next((row for row in trim if row["scenario_name"] == "winsorize_5pct"), {})
    trimmed_5_avg = num(trim5.get("avg_excess_vs_etf_rotation")) or 0.0
    winsor_5_avg = num(winsor5.get("avg_excess_vs_etf_rotation")) or 0.0
    leave_robust = bool(clusters) and all(row["cluster_sensitivity_status"] == "ROBUST_AFTER_CLUSTER_EXCLUSION" for row in clusters)
    coherent_bias = any(row["repeatability_status"] == "REPEATABLE_DIRECTIONAL_BIAS_FOR_OBSERVATION" for row in bias)

    if run_status == STATUS_PIT:
        final_status = STATUS_PIT
        observe = "FALSE"
        reason = "PIT validation failed; expanded 10D evidence is blocked."
    elif run_status == STATUS_MISSING:
        final_status = STATUS_MISSING
        observe = "FALSE"
        reason = "Required V20.201/V20.202/V20.203 or price inputs are missing."
    elif valid_count < 300:
        final_status = STATUS_SMALL
        observe = "TRUE"
        reason = "Expanded 10D sample is below the minimum robustness threshold."
    elif avg_excess > 0 and med_excess > 0 and win_rate >= 0.55 and ci_lower > 0 and trimmed_5_avg > 0 and winsor_5_avg > 0 and leave_robust:
        final_status = STATUS_ROBUST
        observe = "TRUE"
        reason = "Expanded 10D evidence passes central, CI, outlier, and leave-one-cluster checks for observation only."
    elif avg_excess > 0 or med_excess > 0:
        final_status = STATUS_MIXED
        observe = "TRUE"
        reason = "Expanded 10D evidence is positive in part but robustness checks are mixed."
    else:
        final_status = STATUS_NONE
        observe = "FALSE"
        reason = "Expanded 10D average and median excess do not support a local edge."
    next_action = (
        "Continue 10D local-edge observation only; ETF rotation remains the primary benchmark and shadow weight change is not recommended."
        if observe == "TRUE"
        else "Keep ETF rotation as the primary benchmark and keep random-weight stock ranking research-only."
    )
    return {
        "final_status": final_status,
        "valid_trial_count": str(valid_count),
        "avg_excess_vs_etf_rotation": summary.get("avg_excess_vs_etf_rotation", ""),
        "median_excess_vs_etf_rotation": summary.get("median_excess_vs_etf_rotation", ""),
        "win_rate_vs_etf_rotation": summary.get("win_rate_vs_etf_rotation", ""),
        "mean_excess_ci_lower_95": boot.get("mean_excess_ci_lower_95", ""),
        "mean_excess_ci_upper_95": boot.get("mean_excess_ci_upper_95", ""),
        "probability_mean_excess_positive": boot.get("probability_mean_excess_positive", ""),
        "trimmed_5pct_avg_excess": fmt(trimmed_5_avg),
        "winsorized_5pct_avg_excess": fmt(winsor_5_avg),
        "leave_one_cluster_robust": tf(leave_robust),
        "coherent_weight_bias_detected": tf(coherent_bias),
        "local_edge_observation_recommended": observe,
        "shadow_weight_change_recommended": "FALSE",
        "reason": reason,
        "next_recommended_action": next_action,
    }


def write_report(
    gate: dict[str, object],
    boot: dict[str, object],
    trim: list[dict[str, object]],
    clusters: list[dict[str, object]],
    bias: list[dict[str, object]],
) -> None:
    READ_CENTER.mkdir(parents=True, exist_ok=True)
    trim_bottom_top = next((row for row in trim if row["scenario_name"] == "exclude_top_bottom_5pct"), {})
    winsor5 = next((row for row in trim if row["scenario_name"] == "winsorize_5pct"), {})
    asof_weak = sum(1 for row in clusters if row["cluster_type"] == "as_of_date" and row["cluster_sensitivity_status"] != "ROBUST_AFTER_CLUSTER_EXCLUSION")
    etf_weak = sum(1 for row in clusters if row["cluster_type"] == "selected_etf" and row["cluster_sensitivity_status"] != "ROBUST_AFTER_CLUSTER_EXCLUSION")
    repeatable = [row for row in bias if row["repeatability_status"] == "REPEATABLE_DIRECTIONAL_BIAS_FOR_OBSERVATION"]
    lines = [
        "# V20.204 10D Local Edge Robustness Expansion Report",
        "",
        f"- Final status: {gate.get('final_status', '')}",
        "- V20.201 context: random-weight PIT-forward consolidation passed.",
        "- V20.202 context: no shadow weight change was recommended.",
        "- V20.203 context: 10D edge was weak or outlier-sensitive and observation-only.",
        f"- Expanded 10D valid trial count: {gate.get('valid_trial_count', '')}",
        f"- Average / median excess versus ETF rotation: {gate.get('avg_excess_vs_etf_rotation', '')} / {gate.get('median_excess_vs_etf_rotation', '')}",
        f"- Win rate versus ETF rotation: {gate.get('win_rate_vs_etf_rotation', '')}",
        "",
        "Bootstrap confidence:",
        f"- Mean excess 95% CI: {boot.get('mean_excess_ci_lower_95', '')} to {boot.get('mean_excess_ci_upper_95', '')}",
        f"- Median excess 95% CI: {boot.get('median_excess_ci_lower_95', '')} to {boot.get('median_excess_ci_upper_95', '')}",
        f"- Probability mean excess positive: {boot.get('probability_mean_excess_positive', '')}",
        "",
        "Outlier robustness:",
        f"- Top/bottom 5pct exclusion avg_excess: {trim_bottom_top.get('avg_excess_vs_etf_rotation', '')}, conclusion={trim_bottom_top.get('conclusion', '')}",
        f"- Winsorized 5pct avg_excess: {winsor5.get('avg_excess_vs_etf_rotation', '')}, conclusion={winsor5.get('conclusion', '')}",
        "",
        "Leave-one-cluster robustness:",
        f"- Leave-one-as_of_date weak exclusions: {asof_weak}",
        f"- Leave-one-selected-ETF weak exclusions: {etf_weak}",
        f"- Overall leave_one_cluster_robust: {gate.get('leave_one_cluster_robust', '')}",
        "",
        "Weight family bias repeatability:",
        *(f"- {row['family_name']}: delta={row['top_minus_bottom_weight_delta']}, corr={row['correlation_with_excess']}, consistency={row['bootstrap_direction_consistency']}, status={row['repeatability_status']}" for row in repeatable),
        *(["- No repeatable family bias was strong enough for anything beyond observation."] if not repeatable else []),
        "",
        f"- Local-edge observation should continue: {gate.get('local_edge_observation_recommended', '')}",
        f"- Reason: {gate.get('reason', '')}",
        f"- Next recommended action: {gate.get('next_recommended_action', '')}",
        "",
        "Safety statement:",
        "- official weights were not changed",
        "- no official recommendation was created",
        "- no real-book signal was created",
        "- no broker execution was created",
        "- shadow weight change is not recommended in V20.204",
        "- no trade action was created",
    ]
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def blocked_outputs(status_value: str, reason: str) -> int:
    gate = {
        "final_status": status_value, "valid_trial_count": "0",
        "shadow_weight_change_recommended": "FALSE", "reason": reason,
        "next_recommended_action": "Repair required inputs before expanded 10D testing.",
    }
    write_csv(OUT_TRIALS, TRIAL_FIELDS, [])
    write_csv(OUT_FORWARD, FORWARD_FIELDS, [])
    write_csv(OUT_ETF, ETF_FIELDS, [])
    write_csv(OUT_SUMMARY, SUMMARY_FIELDS, [{"valid_trial_count": "0", "robustness_status": status_value}])
    write_csv(OUT_BOOT, BOOT_FIELDS, [{"bootstrap_iterations": str(BOOTSTRAP_ITERATIONS), "bootstrap_status": status_value}])
    write_csv(OUT_TRIM, TRIM_FIELDS, trimmed_winsorized([]))
    write_csv(OUT_CLUSTER, CLUSTER_FIELDS, [])
    write_csv(OUT_BIAS, BIAS_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate, {}, [], [], [])
    print(f"FINAL_STATUS={status_value}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_WEIGHT_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_SIGNAL_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("SHADOW_WEIGHT_CHANGE_RECOMMENDED=FALSE")
    return 0


def main() -> int:
    if not required_inputs_ready():
        missing = [path.name for path in IN_REQUIRED if not path.exists() or path.stat().st_size == 0 or not read_csv(path)]
        return blocked_outputs(STATUS_MISSING, "Missing or empty required inputs: " + ", ".join(missing))
    trials, forward_rows, etf_rows, metrics, run_status = run_expansion()
    if run_status in {STATUS_PIT, STATUS_MISSING}:
        return blocked_outputs(run_status, "Expanded 10D run could not satisfy PIT/input requirements.")

    summary = summarize(metrics)
    boot = bootstrap(metrics)
    trim = trimmed_winsorized(metrics)
    clusters = leave_one_cluster(metrics)
    bias = weight_bias(metrics)
    gate = build_gate(summary, boot, trim, clusters, bias, run_status)

    write_csv(OUT_TRIALS, TRIAL_FIELDS, trials)
    write_csv(OUT_FORWARD, FORWARD_FIELDS, forward_rows)
    write_csv(OUT_ETF, ETF_FIELDS, etf_rows)
    write_csv(OUT_SUMMARY, SUMMARY_FIELDS, [summary])
    write_csv(OUT_BOOT, BOOT_FIELDS, [boot])
    write_csv(OUT_TRIM, TRIM_FIELDS, trim)
    write_csv(OUT_CLUSTER, CLUSTER_FIELDS, clusters)
    write_csv(OUT_BIAS, BIAS_FIELDS, bias)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate, boot, trim, clusters, bias)

    print(f"FINAL_STATUS={gate['final_status']}")
    print(f"VALID_TRIAL_COUNT={gate['valid_trial_count']}")
    print(f"AVG_EXCESS_VS_ETF_ROTATION={gate['avg_excess_vs_etf_rotation']}")
    print(f"MEDIAN_EXCESS_VS_ETF_ROTATION={gate['median_excess_vs_etf_rotation']}")
    print(f"LOCAL_EDGE_OBSERVATION_RECOMMENDED={gate['local_edge_observation_recommended']}")
    print(f"SHADOW_WEIGHT_CHANGE_RECOMMENDED={gate['shadow_weight_change_recommended']}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_WEIGHT_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_SIGNAL_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
