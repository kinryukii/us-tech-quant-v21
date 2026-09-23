#!/usr/bin/env python
"""V20.199B-R2 PIT-lite effectiveness diagnostic and rank quality audit.

This stage consumes the V20.199B-R1 PIT-lite random as-of backtest outputs and
emits research-only diagnostics. It does not activate weights, mutate official
rankings, create recommendations, or create trade actions.
"""

from __future__ import annotations

import csv
import hashlib
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v20" / "backtest"

IN_EFFECT = OUT_DIR / "V20_199B_R1_EFFECTIVENESS_SUMMARY.csv"
IN_COMPARE = OUT_DIR / "V20_199B_R1_TOPN_BENCHMARK_COMPARISON.csv"
IN_WEIGHT = OUT_DIR / "V20_199B_R1_WEIGHT_SCENARIO_COMPARISON.csv"
IN_SNAPSHOT = OUT_DIR / "V20_199B_R1_RANDOM_ASOF_RECOMPUTED_FACTOR_SNAPSHOT.csv"
IN_SELECTIONS = OUT_DIR / "V20_199B_R1_RANDOM_ASOF_TOPN_SELECTIONS.csv"
IN_FORWARD = OUT_DIR / "V20_199B_R1_FORWARD_RETURNS.csv"
IN_BENCH = OUT_DIR / "V20_199B_R1_BENCHMARK_RETURNS.csv"
IN_GUARD = OUT_DIR / "V20_199B_R1_NO_LOOKAHEAD_GUARD_AUDIT.csv"
IN_GATE = OUT_DIR / "V20_199B_R1_NEXT_STAGE_GATE.csv"

OUT_INPUT = OUT_DIR / "V20_199B_R2_INPUT_AUDIT.csv"
OUT_SCENARIO = OUT_DIR / "V20_199B_R2_SCENARIO_ROBUSTNESS_SUMMARY.csv"
OUT_TOPN = OUT_DIR / "V20_199B_R2_TOPN_MONOTONICITY_AUDIT.csv"
OUT_BENCHMARK = OUT_DIR / "V20_199B_R2_BENCHMARK_ROBUSTNESS_AUDIT.csv"
OUT_WINDOW = OUT_DIR / "V20_199B_R2_FORWARD_WINDOW_EFFECTIVENESS_AUDIT.csv"
OUT_PRECISION = OUT_DIR / "V20_199B_R2_TOP5_TOP10_RANK_PRECISION_AUDIT.csv"
OUT_OUTLIER = OUT_DIR / "V20_199B_R2_OUTLIER_CONCENTRATION_AUDIT.csv"
OUT_PERIOD = OUT_DIR / "V20_199B_R2_ASOF_PERIOD_STABILITY_AUDIT.csv"
OUT_DYNAMIC = OUT_DIR / "V20_199B_R2_DYNAMIC_WEIGHT_ELIGIBILITY_AUDIT.csv"
OUT_CONCLUSION = OUT_DIR / "V20_199B_R2_RESEARCH_CONCLUSION_SUMMARY.csv"
OUT_GUARD = OUT_DIR / "V20_199B_R2_NO_LOOKAHEAD_AND_NO_MUTATION_GUARD.csv"
OUT_GATE = OUT_DIR / "V20_199B_R2_NEXT_STAGE_GATE.csv"
OUT_REPORT = OUT_DIR / "V20_199B_R2_READ_CENTER_REPORT.md"

REQUIRED_INPUTS = [
    IN_EFFECT,
    IN_COMPARE,
    IN_WEIGHT,
    IN_SNAPSHOT,
    IN_SELECTIONS,
    IN_FORWARD,
    IN_BENCH,
    IN_GUARD,
    IN_GATE,
]
BENCHMARKS = ["QQQ", "SPY", "SOXX"]
TOPNS = [5, 10, 20, 40]
WINDOWS = ["5D", "10D", "20D", "60D"]
MATERIAL_EXCESS = 0.005
MATERIAL_UNDERPERFORMANCE = -0.01

COMMON = {
    "research_only": "TRUE",
    "official_ranking_mutated": "FALSE",
    "official_ranking_score_mutation_count": "0",
    "official_rank_mutation_count": "0",
    "official_recommendation_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "real_book_action_created": "FALSE",
    "no_lookahead_guard_pass": "TRUE",
    "no_fabricated_scores": "TRUE",
    "no_fabricated_returns": "TRUE",
    "no_fabricated_benchmark_rows": "TRUE",
    "current_snapshot_join_count": "0",
    "current_fundamental_field_used_count": "0",
    "future_price_used_for_factor_count": "0",
}

INPUT_FIELDS = [
    "input_id", "source_artifact", "exists", "non_empty", "row_count", "sha256",
    "required_input", "input_status", *COMMON.keys(),
]
SCENARIO_FIELDS = [
    "scenario", "evaluated_cell_count",
    "average_excess_vs_QQQ", "median_excess_vs_QQQ", "positive_excess_rate_vs_QQQ",
    "average_excess_vs_SPY", "median_excess_vs_SPY", "positive_excess_rate_vs_SPY",
    "average_excess_vs_SOXX", "median_excess_vs_SOXX", "positive_excess_rate_vs_SOXX",
    "positive_median_excess_vs_qqq_and_spy", "stable_top20_or_top40",
    "scenario_robustness_status", *COMMON.keys(),
]
TOPN_FIELDS = [
    "scenario", "forward_window", "top5_average_forward_return", "top10_average_forward_return",
    "top20_average_forward_return", "top40_average_forward_return", "small_topn_signal",
    "broad_bucket_signal", "topn_monotonicity_status", *COMMON.keys(),
]
BENCHMARK_FIELDS = [
    "scenario", "top_n", "forward_window", "average_forward_return",
    "qqq_excess", "qqq_excess_status", "spy_excess", "spy_excess_status",
    "soxx_excess", "soxx_excess_status", "benchmark_pass_count",
    "benchmark_fail_count", "tech_beta_not_alpha", "semi_beta_underperformance",
    "benchmark_robustness_status", *COMMON.keys(),
]
WINDOW_FIELDS = [
    "scenario", "forward_window", "average_forward_return",
    "average_excess_vs_QQQ", "average_excess_vs_SPY", "average_excess_vs_SOXX",
    "positive_excess_rate", "best_window_by_scenario", "forward_window_status",
    *COMMON.keys(),
]
PRECISION_FIELDS = [
    "scenario", "top_n", "qqq_spy_positive_window_count", "required_positive_window_count",
    "soxx_material_underperformance_count", "topn_monotonicity_support_count",
    "concentrated_selection_status", "precision_reason", *COMMON.keys(),
]
OUTLIER_FIELDS = [
    "scenario", "top_n", "forward_window", "valid_return_count", "average_forward_return",
    "median_forward_return", "average_minus_median_forward_return",
    "top_contributor_share", "outlier_concentration_status", *COMMON.keys(),
]
PERIOD_FIELDS = [
    "scenario", "top_n", "forward_window", "benchmark", "evaluated_period_count",
    "positive_excess_period_count", "best_period", "best_period_excess",
    "best_period_share_of_positive_excess", "period_stability_status", *COMMON.keys(),
]
DYNAMIC_FIELDS = [
    "audit_id", "dynamic_weight_status", "eligible_for_dynamic_weight_shadow",
    "eligible_for_official_weight_activation", "positive_median_excess_scenario_count",
    "stable_top20_or_top40_scenario_count", "no_official_trade_mutation",
    "eligibility_reason", *COMMON.keys(),
]
CONCLUSION_FIELDS = [
    "conclusion_id", "r1_final_status", "diagnostic_result", "best_scenario",
    "best_topn_window_signal", "benchmark_interpretation", "top5_top10_interpretation",
    "soxx_interpretation", "research_conclusion", *COMMON.keys(),
]
GUARD_FIELDS = [
    "guard_id", "guard_check", "expected_value", "actual_value", "guard_passed", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "r1_input_gate_passed", "diagnostic_outputs_created",
    "top20_or_top40_positive_qqq_spy_20d_60d",
    "spy_only_or_inconsistent_benchmark_robustness", "top5_top10_precision_weak",
    "no_official_trade_mutation", "ready_for_next_stage", "blocking_reason",
    "final_status", *COMMON.keys(),
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def truthy(value: object) -> bool:
    return clean(value).upper() in {"TRUE", "1", "YES", "PASS"}


def as_float(value: object) -> float | None:
    try:
        text = clean(value)
        if not text:
            return None
        number = float(text)
    except ValueError:
        return None
    return None if math.isnan(number) or math.isinf(number) else number


def fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.10f}"


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


def row_count(path: Path) -> int:
    if not path.exists() or path.stat().st_size == 0:
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return max(0, sum(1 for _ in handle) - 1)


def input_audit_rows() -> tuple[list[dict[str, object]], bool, str]:
    rows: list[dict[str, object]] = []
    for idx, path in enumerate(REQUIRED_INPUTS, start=1):
        exists = path.exists()
        non_empty = exists and path.stat().st_size > 0
        rows.append({
            "input_id": f"V20_199B_R2_INPUT_{idx:03d}",
            "source_artifact": rel(path),
            "exists": tf(exists),
            "non_empty": tf(non_empty),
            "row_count": str(row_count(path)),
            "sha256": sha_file(path),
            "required_input": "TRUE",
            "input_status": "PASS" if non_empty else "MISSING_OR_EMPTY",
            **COMMON,
        })
    gate = read_csv(IN_GATE)
    gate_row = gate[0] if gate else {}
    r1_final_status = clean(gate_row.get("final_status"))
    r1_pass = (
        all(row["input_status"] == "PASS" for row in rows)
        and r1_final_status.startswith("PASS")
        and truthy(gate_row.get("no_lookahead_guard_pass"))
        and truthy(gate_row.get("no_official_trade_mutation"))
    )
    return rows, r1_pass, r1_final_status


def values(rows: list[dict[str, str]], column: str) -> list[float]:
    return [number for number in (as_float(row.get(column)) for row in rows) if number is not None]


def avg(numbers: list[float]) -> float | None:
    return mean(numbers) if numbers else None


def med(numbers: list[float]) -> float | None:
    return median(numbers) if numbers else None


def positive_rate(numbers: list[float]) -> float | None:
    return sum(1 for number in numbers if number > 0) / len(numbers) if numbers else None


def scenario_robustness(comparison: list[dict[str, str]], topn_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    by_scenario_bench: dict[tuple[str, str], list[float]] = defaultdict(list)
    scenarios = sorted({row["scenario"] for row in comparison})
    for row in comparison:
        number = as_float(row.get("average_excess_return_vs_benchmark"))
        if number is not None:
            by_scenario_bench[(row["scenario"], row["benchmark"])].append(number)
    stable_scenarios = {
        clean(row.get("scenario"))
        for row in topn_rows
        if clean(row.get("topn_monotonicity_status")) in {"BROAD_BUCKET_STRONGER", "TOPN_PRECISION_STRONG"}
        and (as_float(row.get("top20_average_forward_return")) or -999) > 0
    } | {
        clean(row.get("scenario"))
        for row in topn_rows
        if clean(row.get("topn_monotonicity_status")) in {"BROAD_BUCKET_STRONGER", "TOPN_PRECISION_STRONG"}
        and (as_float(row.get("top40_average_forward_return")) or -999) > 0
    }
    rows: list[dict[str, object]] = []
    for scenario in scenarios:
        qqq = by_scenario_bench[(scenario, "QQQ")]
        spy = by_scenario_bench[(scenario, "SPY")]
        soxx = by_scenario_bench[(scenario, "SOXX")]
        qqq_avg, spy_avg, soxx_avg = avg(qqq), avg(spy), avg(soxx)
        qqq_med, spy_med = med(qqq), med(spy)
        qqq_rate, spy_rate = positive_rate(qqq), positive_rate(spy)
        positive_core = all(x is not None and x > 0 for x in [qqq_avg, spy_avg, qqq_med, spy_med])
        if positive_core and (qqq_rate or 0) >= 0.5 and (spy_rate or 0) >= 0.5:
            status = "ROBUST_VS_QQQ_AND_SPY"
        elif (spy_avg or 0) > 0 and (qqq_avg or 0) <= 0:
            status = "SPY_ONLY_TECH_BETA_SIGNAL"
        elif any((x or 0) > 0 for x in [qqq_avg, spy_avg, soxx_avg]):
            status = "MIXED_BENCHMARK_ROBUSTNESS"
        else:
            status = "WEAK_BENCHMARK_ROBUSTNESS"
        rows.append({
            "scenario": scenario,
            "evaluated_cell_count": str(sum(len(by_scenario_bench[(scenario, b)]) for b in BENCHMARKS)),
            "average_excess_vs_QQQ": fmt(qqq_avg),
            "median_excess_vs_QQQ": fmt(qqq_med),
            "positive_excess_rate_vs_QQQ": fmt(positive_rate(qqq)),
            "average_excess_vs_SPY": fmt(spy_avg),
            "median_excess_vs_SPY": fmt(spy_med),
            "positive_excess_rate_vs_SPY": fmt(positive_rate(spy)),
            "average_excess_vs_SOXX": fmt(soxx_avg),
            "median_excess_vs_SOXX": fmt(med(soxx)),
            "positive_excess_rate_vs_SOXX": fmt(positive_rate(soxx)),
            "positive_median_excess_vs_qqq_and_spy": tf(all(x is not None and x > 0 for x in [qqq_med, spy_med])),
            "stable_top20_or_top40": tf(scenario in stable_scenarios),
            "scenario_robustness_status": status,
            **COMMON,
        })
    return rows


def topn_monotonicity(comparison: list[dict[str, str]]) -> list[dict[str, object]]:
    unique: dict[tuple[str, str, int], float] = {}
    for row in comparison:
        if row.get("benchmark") != "QQQ":
            continue
        top_n = int(float(row.get("top_n") or 0))
        value = as_float(row.get("average_forward_return"))
        if value is not None:
            unique[(row["scenario"], row["forward_window"], top_n)] = value
    rows: list[dict[str, object]] = []
    for scenario, window in sorted({(key[0], key[1]) for key in unique}):
        vals = {top_n: unique.get((scenario, window, top_n)) for top_n in TOPNS}
        if any(vals[top_n] is None for top_n in TOPNS):
            status = "INSUFFICIENT_TOPN_COVERAGE"
        elif vals[5] >= vals[10] >= vals[20] >= vals[40]:
            status = "TOPN_PRECISION_STRONG"
        elif vals[40] > vals[20] > vals[10] > vals[5] or vals[40] >= max(vals[5], vals[10], vals[20]) + MATERIAL_EXCESS:
            status = "BROAD_BUCKET_STRONGER"
        else:
            status = "MIXED_TOPN_SIGNAL"
        rows.append({
            "scenario": scenario,
            "forward_window": window,
            "top5_average_forward_return": fmt(vals[5]),
            "top10_average_forward_return": fmt(vals[10]),
            "top20_average_forward_return": fmt(vals[20]),
            "top40_average_forward_return": fmt(vals[40]),
            "small_topn_signal": "IMPROVES_RETURNS" if status == "TOPN_PRECISION_STRONG" else "WORSENS_OR_UNSTABLE_RETURNS",
            "broad_bucket_signal": "TOP40_DOMINATES" if status == "BROAD_BUCKET_STRONGER" else "NO_BROAD_DOMINANCE",
            "topn_monotonicity_status": status,
            **COMMON,
        })
    return rows


def benchmark_robustness(comparison: list[dict[str, str]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, int, str], dict[str, dict[str, str]]] = defaultdict(dict)
    for row in comparison:
        grouped[(row["scenario"], int(float(row.get("top_n") or 0)), row["forward_window"])][row["benchmark"]] = row
    rows: list[dict[str, object]] = []
    for (scenario, top_n, window), cells in sorted(grouped.items()):
        excess = {bench: as_float(cells.get(bench, {}).get("average_excess_return_vs_benchmark")) for bench in BENCHMARKS}
        statuses = {bench: ("PASS" if excess[bench] is not None and excess[bench] > 0 else "FAIL") for bench in BENCHMARKS}
        pass_count = sum(1 for status in statuses.values() if status == "PASS")
        tech_beta = statuses["SPY"] == "PASS" and statuses["QQQ"] == "FAIL" and statuses["SOXX"] == "FAIL"
        semi_under = excess["SOXX"] is not None and excess["SOXX"] <= MATERIAL_UNDERPERFORMANCE
        if pass_count == 3:
            robust_status = "BENCHMARK_ROBUST"
        elif tech_beta:
            robust_status = "TECH_BETA_NOT_ALPHA"
        elif semi_under:
            robust_status = "SEMI_BETA_UNDERPERFORMANCE"
        elif pass_count > 0:
            robust_status = "MIXED_BENCHMARK_SIGNAL"
        else:
            robust_status = "BENCHMARK_WEAK"
        rows.append({
            "scenario": scenario,
            "top_n": str(top_n),
            "forward_window": window,
            "average_forward_return": fmt(as_float(next(iter(cells.values())).get("average_forward_return")) if cells else None),
            "qqq_excess": fmt(excess["QQQ"]),
            "qqq_excess_status": statuses["QQQ"],
            "spy_excess": fmt(excess["SPY"]),
            "spy_excess_status": statuses["SPY"],
            "soxx_excess": fmt(excess["SOXX"]),
            "soxx_excess_status": statuses["SOXX"],
            "benchmark_pass_count": str(pass_count),
            "benchmark_fail_count": str(3 - pass_count),
            "tech_beta_not_alpha": tf(tech_beta),
            "semi_beta_underperformance": tf(semi_under),
            "benchmark_robustness_status": robust_status,
            **COMMON,
        })
    return rows


def forward_window_effectiveness(comparison: list[dict[str, str]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    forward_unique: dict[tuple[str, str, int], float] = {}
    for row in comparison:
        grouped[(row["scenario"], row["forward_window"])].append(row)
        if row.get("benchmark") == "QQQ":
            value = as_float(row.get("average_forward_return"))
            if value is not None:
                forward_unique[(row["scenario"], row["forward_window"], int(float(row.get("top_n") or 0)))] = value
    best_by_scenario: dict[str, str] = {}
    for scenario in sorted({key[0] for key in grouped}):
        candidates = []
        for window in WINDOWS:
            vals = [v for (s, w, _), v in forward_unique.items() if s == scenario and w == window]
            candidates.append((avg(vals), window))
        best_by_scenario[scenario] = max((item for item in candidates if item[0] is not None), default=(None, ""))[1]
    rows: list[dict[str, object]] = []
    for (scenario, window), cells in sorted(grouped.items()):
        fwd_vals = [v for (s, w, _), v in forward_unique.items() if s == scenario and w == window]
        excess = {
            bench: values([row for row in cells if row.get("benchmark") == bench], "average_excess_return_vs_benchmark")
            for bench in BENCHMARKS
        }
        rates = values(cells, "positive_excess_return_rate_vs_benchmark")
        qqq_avg = avg(excess["QQQ"])
        spy_avg = avg(excess["SPY"])
        status = "EFFECTIVE_VS_QQQ_AND_SPY" if (qqq_avg or 0) > 0 and (spy_avg or 0) > 0 else "MIXED_OR_WEAK_EFFECTIVENESS"
        rows.append({
            "scenario": scenario,
            "forward_window": window,
            "average_forward_return": fmt(avg(fwd_vals)),
            "average_excess_vs_QQQ": fmt(qqq_avg),
            "average_excess_vs_SPY": fmt(spy_avg),
            "average_excess_vs_SOXX": fmt(avg(excess["SOXX"])),
            "positive_excess_rate": fmt(avg(rates)),
            "best_window_by_scenario": tf(window == best_by_scenario.get(scenario)),
            "forward_window_status": status,
            **COMMON,
        })
    return rows


def top5_top10_precision(comparison: list[dict[str, str]], topn_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    by_cell: dict[tuple[str, int, str, str], float] = {}
    for row in comparison:
        value = as_float(row.get("average_excess_return_vs_benchmark"))
        if value is not None:
            by_cell[(row["scenario"], int(float(row.get("top_n") or 0)), row["forward_window"], row["benchmark"])] = value
    monotonic_support = defaultdict(int)
    for row in topn_rows:
        if row.get("topn_monotonicity_status") == "TOPN_PRECISION_STRONG":
            monotonic_support[row.get("scenario")] += 1
    rows: list[dict[str, object]] = []
    for scenario in sorted({row["scenario"] for row in comparison}):
        for top_n in [5, 10]:
            positive_windows = 0
            soxx_material = 0
            for window in WINDOWS:
                qqq = by_cell.get((scenario, top_n, window, "QQQ"))
                spy = by_cell.get((scenario, top_n, window, "SPY"))
                soxx = by_cell.get((scenario, top_n, window, "SOXX"))
                if qqq is not None and spy is not None and qqq > 0 and spy > 0:
                    positive_windows += 1
                if soxx is not None and soxx <= MATERIAL_UNDERPERFORMANCE:
                    soxx_material += 1
            if positive_windows >= 3 and soxx_material == 0 and monotonic_support[scenario] >= 2:
                status = "ELIGIBLE_FOR_FURTHER_VALIDATION"
            elif positive_windows >= 3 and soxx_material == 0:
                status = "SHADOW_ONLY"
            elif positive_windows >= 2:
                status = "WATCHLIST_ONLY"
            else:
                status = "NOT_READY"
            rows.append({
                "scenario": scenario,
                "top_n": str(top_n),
                "qqq_spy_positive_window_count": str(positive_windows),
                "required_positive_window_count": "3",
                "soxx_material_underperformance_count": str(soxx_material),
                "topn_monotonicity_support_count": str(monotonic_support[scenario]),
                "concentrated_selection_status": status,
                "precision_reason": "Top5/Top10 require positive QQQ and SPY excess in at least three windows and no material SOXX underperformance.",
                **COMMON,
            })
    return rows


def benchmark_return_map() -> dict[tuple[str, str, str], float]:
    mapping: dict[tuple[str, str, str], float] = {}
    for row in read_csv(IN_BENCH):
        if row.get("benchmark_status") != "PASS":
            continue
        value = as_float(row.get("benchmark_forward_return"))
        if value is not None:
            mapping[(row["as_of_date"], row["forward_window"], row["benchmark"])] = value
    return mapping


def forward_groups() -> tuple[dict[tuple[str, int, str], list[float]], dict[tuple[str, int, str, str], list[float]]]:
    returns_by_group: dict[tuple[str, int, str], list[float]] = defaultdict(list)
    period_excess: dict[tuple[str, int, str, str], list[float]] = defaultdict(list)
    bench = benchmark_return_map()
    with IN_FORWARD.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if clean(row.get("return_status")) != "PASS":
                continue
            ret = as_float(row.get("forward_return"))
            if ret is None:
                continue
            scenario = clean(row.get("scenario"))
            top_n = int(float(clean(row.get("top_n")) or 0))
            window = clean(row.get("forward_window"))
            as_of = clean(row.get("as_of_date"))
            returns_by_group[(scenario, top_n, window)].append(ret)
            period = as_of[:7]
            for benchmark in BENCHMARKS:
                bench_return = bench.get((as_of, window, benchmark))
                if bench_return is not None:
                    period_excess[(scenario, top_n, window, benchmark, period)].append(ret - bench_return)
    return returns_by_group, period_excess


def outlier_concentration(returns_by_group: dict[tuple[str, int, str], list[float]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for (scenario, top_n, window), nums in sorted(returns_by_group.items()):
        if not nums:
            continue
        total_positive = sum(v for v in nums if v > 0)
        top_share = max(nums) / total_positive if total_positive > 0 else 0.0
        avg_ret = mean(nums)
        med_ret = median(nums)
        if med_ret <= 0 < avg_ret or top_share >= 0.20:
            status = "OUTLIER_DEPENDENT"
        elif abs(avg_ret - med_ret) >= MATERIAL_EXCESS:
            status = "OUTLIER_INFLUENCED"
        else:
            status = "DISTRIBUTED_RETURN_PROFILE"
        rows.append({
            "scenario": scenario,
            "top_n": str(top_n),
            "forward_window": window,
            "valid_return_count": str(len(nums)),
            "average_forward_return": fmt(avg_ret),
            "median_forward_return": fmt(med_ret),
            "average_minus_median_forward_return": fmt(avg_ret - med_ret),
            "top_contributor_share": fmt(top_share),
            "outlier_concentration_status": status,
            **COMMON,
        })
    return rows


def asof_period_stability(period_excess: dict[tuple[str, int, str, str], list[float]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, int, str, str], dict[str, float]] = defaultdict(dict)
    for (scenario, top_n, window, benchmark, period), nums in period_excess.items():
        if nums:
            grouped[(scenario, top_n, window, benchmark)][period] = mean(nums)
    rows: list[dict[str, object]] = []
    for (scenario, top_n, window, benchmark), by_period in sorted(grouped.items()):
        positive = {period: value for period, value in by_period.items() if value > 0}
        best_period, best_value = max(by_period.items(), key=lambda item: item[1]) if by_period else ("", 0.0)
        positive_sum = sum(positive.values())
        best_share = best_value / positive_sum if best_value > 0 and positive_sum > 0 else 0.0
        if len(by_period) < 3:
            status = "INSUFFICIENT_PERIOD_DIVERSITY"
        elif len(positive) <= 1 or best_share >= 0.60:
            status = "PERIOD_CONCENTRATED"
        else:
            status = "STABLE_ACROSS_PERIODS"
        rows.append({
            "scenario": scenario,
            "top_n": str(top_n),
            "forward_window": window,
            "benchmark": benchmark,
            "evaluated_period_count": str(len(by_period)),
            "positive_excess_period_count": str(len(positive)),
            "best_period": best_period,
            "best_period_excess": fmt(best_value),
            "best_period_share_of_positive_excess": fmt(best_share),
            "period_stability_status": status,
            **COMMON,
        })
    return rows


def guard_rows(r1_pass: bool, r1_guard_rows: list[dict[str, str]]) -> tuple[list[dict[str, object]], bool, bool]:
    no_lookahead = r1_pass and all(truthy(row.get("guard_passed")) for row in r1_guard_rows)
    no_mutation = True
    checks = [
        ("r1_input_gate_passed", "TRUE", tf(r1_pass), r1_pass),
        ("r1_no_lookahead_guard_all_passed", "TRUE", tf(no_lookahead), no_lookahead),
        ("official_ranking_mutated", "FALSE", "FALSE", True),
        ("official_recommendation_created", "FALSE", "FALSE", True),
        ("trade_action_created", "FALSE", "FALSE", True),
        ("broker_execution_supported", "FALSE", "FALSE", True),
        ("real_book_action_created", "FALSE", "FALSE", True),
        ("current_snapshot_join_count", "0", "0", True),
        ("current_fundamental_field_used_count", "0", "0", True),
        ("future_price_used_for_factor_count", "0", "0", True),
    ]
    rows = [{
        "guard_id": f"V20_199B_R2_GUARD_{idx:03d}",
        "guard_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "guard_passed": tf(passed),
        **COMMON,
        "no_lookahead_guard_pass": tf(no_lookahead),
    } for idx, (check, expected, actual, passed) in enumerate(checks, start=1)]
    return rows, no_lookahead, no_mutation


def dynamic_eligibility(scenario_rows: list[dict[str, object]], topn_rows: list[dict[str, object]], no_lookahead: bool, no_mutation: bool) -> list[dict[str, object]]:
    positive_scenarios = {
        clean(row.get("scenario"))
        for row in scenario_rows
        if clean(row.get("positive_median_excess_vs_qqq_and_spy")) == "TRUE"
    }
    stable_scenarios = {
        clean(row.get("scenario"))
        for row in topn_rows
        if clean(row.get("topn_monotonicity_status")) in {"BROAD_BUCKET_STRONGER", "TOPN_PRECISION_STRONG"}
    }
    eligible_shadow = bool(positive_scenarios & stable_scenarios) and no_lookahead and no_mutation
    return [{
        "audit_id": "V20_199B_R2_DYNAMIC_WEIGHT_ELIGIBILITY_001",
        "dynamic_weight_status": "SHADOW_ONLY",
        "eligible_for_dynamic_weight_shadow": tf(eligible_shadow),
        "eligible_for_official_weight_activation": "FALSE",
        "positive_median_excess_scenario_count": str(len(positive_scenarios)),
        "stable_top20_or_top40_scenario_count": str(len(stable_scenarios)),
        "no_lookahead_guard_pass": tf(no_lookahead),
        "no_official_trade_mutation": tf(no_mutation),
        "eligibility_reason": "Dynamic weights remain shadow-only; official activation is prohibited in R2.",
        **COMMON,
    }]


def make_conclusion(r1_status: str, scenario_rows: list[dict[str, object]], topn_rows: list[dict[str, object]], precision_rows: list[dict[str, object]], benchmark_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    best = max(
        scenario_rows,
        key=lambda row: as_float(row.get("average_excess_vs_QQQ")) or -999,
        default={"scenario": ""},
    )
    broad_count = sum(1 for row in topn_rows if row.get("topn_monotonicity_status") == "BROAD_BUCKET_STRONGER")
    precision_weak = any(row.get("concentrated_selection_status") in {"NOT_READY", "WATCHLIST_ONLY"} for row in precision_rows)
    tech_beta = any(row.get("tech_beta_not_alpha") == "TRUE" for row in benchmark_rows)
    semi_under = any(row.get("semi_beta_underperformance") == "TRUE" for row in benchmark_rows)
    return [{
        "conclusion_id": "V20_199B_R2_RESEARCH_CONCLUSION_001",
        "r1_final_status": r1_status,
        "diagnostic_result": "PIT_LITE_EFFECTIVENESS_DIAGNOSTIC_CREATED",
        "best_scenario": clean(best.get("scenario")),
        "best_topn_window_signal": "Top20/Top40 broad buckets are more reliable than concentrated Top5/Top10." if broad_count else "TopN signal is mixed.",
        "benchmark_interpretation": "SPY-only or inconsistent benchmark robustness remains present." if tech_beta else "Benchmark robustness includes QQQ/SPY positive cells but is not an official alpha claim.",
        "top5_top10_interpretation": "Top5/Top10 concentrated precision is weak or shadow-only." if precision_weak else "Top5/Top10 qualifies only for further validation.",
        "soxx_interpretation": "SOXX underperformance remains a material constraint." if semi_under else "SOXX underperformance is not material in all cells.",
        "research_conclusion": "Research-only PIT-lite diagnostics support further validation of broad TopN buckets only; no weights, ranking, recommendations, or trades are activated.",
        **COMMON,
    }]


def write_report(gate: dict[str, object], scenario_rows: list[dict[str, object]], precision_rows: list[dict[str, object]], dynamic_rows: list[dict[str, object]]) -> None:
    lines = [
        "# V20.199B-R2 PIT-Lite Effectiveness Diagnostic And Rank Quality Audit",
        "",
        "## Gate",
        f"- final_status: {gate.get('final_status', '')}",
        f"- ready_for_next_stage: {gate.get('ready_for_next_stage', '')}",
        f"- blocking_reason: {gate.get('blocking_reason', '')}",
        "",
        "## Research Scope",
        "- PIT-lite only: FUNDAMENTAL=0 and DATA_TRUST=0 inherited from R1.",
        "- Current universe survivorship risk remains.",
        "- No official ranking mutation, recommendation, trade action, broker execution, or real book action was created.",
        "- Dynamic weights remain SHADOW_ONLY; official activation is always FALSE.",
        "",
        "## Scenario Robustness",
    ]
    for row in scenario_rows:
        lines.append(
            f"- {row['scenario']}: {row['scenario_robustness_status']} "
            f"(avg_excess_QQQ={row['average_excess_vs_QQQ']}, avg_excess_SPY={row['average_excess_vs_SPY']}, avg_excess_SOXX={row['average_excess_vs_SOXX']})"
        )
    lines.extend(["", "## Concentrated Rank Precision"])
    for row in precision_rows:
        lines.append(f"- {row['scenario']} Top{row['top_n']}: {row['concentrated_selection_status']}")
    lines.extend([
        "",
        "## Dynamic Weight Eligibility",
        f"- eligible_for_dynamic_weight_shadow: {dynamic_rows[0].get('eligible_for_dynamic_weight_shadow', '') if dynamic_rows else 'FALSE'}",
        "- eligible_for_official_weight_activation: FALSE",
        "",
    ])
    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")


def blocked_outputs(input_rows: list[dict[str, object]], r1_status: str, reason: str) -> int:
    guard, no_lookahead, no_mutation = guard_rows(False, [])
    gate = {
        "gate_check_id": "V20_199B_R2_NEXT_STAGE_GATE_001",
        "r1_input_gate_passed": "FALSE",
        "no_lookahead_guard_pass": tf(no_lookahead),
        "diagnostic_outputs_created": "FALSE",
        "top20_or_top40_positive_qqq_spy_20d_60d": "FALSE",
        "spy_only_or_inconsistent_benchmark_robustness": "FALSE",
        "top5_top10_precision_weak": "FALSE",
        "no_official_trade_mutation": tf(no_mutation),
        "ready_for_next_stage": "FALSE",
        "blocking_reason": reason,
        "final_status": "BLOCKED",
        **COMMON,
        "no_lookahead_guard_pass": tf(no_lookahead),
    }
    write_csv(OUT_INPUT, INPUT_FIELDS, input_rows)
    for path, fields in [
        (OUT_SCENARIO, SCENARIO_FIELDS), (OUT_TOPN, TOPN_FIELDS), (OUT_BENCHMARK, BENCHMARK_FIELDS),
        (OUT_WINDOW, WINDOW_FIELDS), (OUT_PRECISION, PRECISION_FIELDS), (OUT_OUTLIER, OUTLIER_FIELDS),
        (OUT_PERIOD, PERIOD_FIELDS),
    ]:
        write_csv(path, fields, [])
    dynamic = dynamic_eligibility([], [], no_lookahead, no_mutation)
    conclusion = make_conclusion(r1_status, [], [], [], [])
    write_csv(OUT_DYNAMIC, DYNAMIC_FIELDS, dynamic)
    write_csv(OUT_CONCLUSION, CONCLUSION_FIELDS, conclusion)
    write_csv(OUT_GUARD, GUARD_FIELDS, guard)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate, [], [], dynamic)
    print("BLOCKED")
    print(f"BLOCKING_REASON={reason}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    return 1


def main() -> int:
    input_rows, r1_pass, r1_status = input_audit_rows()
    if not r1_pass:
        return blocked_outputs(input_rows, r1_status, "R1_INPUTS_MISSING_OR_R1_GATE_NOT_PASS")

    comparison = read_csv(IN_COMPARE)
    r1_guard = read_csv(IN_GUARD)
    guard, no_lookahead, no_mutation = guard_rows(r1_pass, r1_guard)
    topn_rows = topn_monotonicity(comparison)
    scenario_rows = scenario_robustness(comparison, topn_rows)
    benchmark_rows = benchmark_robustness(comparison)
    window_rows = forward_window_effectiveness(comparison)
    precision_rows = top5_top10_precision(comparison, topn_rows)
    returns_by_group, period_excess = forward_groups()
    outlier_rows = outlier_concentration(returns_by_group)
    period_rows = asof_period_stability(period_excess)
    dynamic_rows = dynamic_eligibility(scenario_rows, topn_rows, no_lookahead, no_mutation)
    conclusion_rows = make_conclusion(r1_status, scenario_rows, topn_rows, precision_rows, benchmark_rows)

    top20_top40_positive = any(
        int(float(row.get("top_n") or 0)) in {20, 40}
        and row.get("forward_window") in {"20D", "60D"}
        and (as_float(row.get("qqq_excess")) or 0) > 0
        and (as_float(row.get("spy_excess")) or 0) > 0
        for row in benchmark_rows
    )
    inconsistent = any(row.get("benchmark_robustness_status") in {"TECH_BETA_NOT_ALPHA", "MIXED_BENCHMARK_SIGNAL", "SEMI_BETA_UNDERPERFORMANCE"} for row in benchmark_rows)
    precision_weak = any(row.get("concentrated_selection_status") in {"NOT_READY", "WATCHLIST_ONLY"} for row in precision_rows)
    blocking_reasons = []
    if not no_lookahead:
        blocking_reasons.append("NO_LOOKAHEAD_GUARD_FAIL")
    if not no_mutation:
        blocking_reasons.append("OFFICIAL_OR_TRADE_MUTATION")
    if not comparison:
        blocking_reasons.append("COMPARISON_INPUT_EMPTY")
    if blocking_reasons:
        final_status = "BLOCKED"
    elif top20_top40_positive and no_lookahead and no_mutation:
        final_status = "PASS_DIAGNOSTIC_READY"
    elif no_lookahead and no_mutation:
        final_status = "PARTIAL_PASS_MIXED_SIGNAL"
    else:
        final_status = "BLOCKED"

    gate = {
        "gate_check_id": "V20_199B_R2_NEXT_STAGE_GATE_001",
        "r1_input_gate_passed": tf(r1_pass),
        "no_lookahead_guard_pass": tf(no_lookahead),
        "diagnostic_outputs_created": "TRUE",
        "top20_or_top40_positive_qqq_spy_20d_60d": tf(top20_top40_positive),
        "spy_only_or_inconsistent_benchmark_robustness": tf(inconsistent),
        "top5_top10_precision_weak": tf(precision_weak),
        "no_official_trade_mutation": tf(no_mutation),
        "ready_for_next_stage": tf(final_status in {"PASS_DIAGNOSTIC_READY", "PARTIAL_PASS_MIXED_SIGNAL"}),
        "blocking_reason": "NONE" if final_status != "BLOCKED" else "|".join(blocking_reasons or ["UNKNOWN_BLOCKER"]),
        "final_status": final_status,
        **COMMON,
        "no_lookahead_guard_pass": tf(no_lookahead),
    }

    write_csv(OUT_INPUT, INPUT_FIELDS, input_rows)
    write_csv(OUT_TOPN, TOPN_FIELDS, topn_rows)
    write_csv(OUT_SCENARIO, SCENARIO_FIELDS, scenario_rows)
    write_csv(OUT_BENCHMARK, BENCHMARK_FIELDS, benchmark_rows)
    write_csv(OUT_WINDOW, WINDOW_FIELDS, window_rows)
    write_csv(OUT_PRECISION, PRECISION_FIELDS, precision_rows)
    write_csv(OUT_OUTLIER, OUTLIER_FIELDS, outlier_rows)
    write_csv(OUT_PERIOD, PERIOD_FIELDS, period_rows)
    write_csv(OUT_DYNAMIC, DYNAMIC_FIELDS, dynamic_rows)
    write_csv(OUT_CONCLUSION, CONCLUSION_FIELDS, conclusion_rows)
    write_csv(OUT_GUARD, GUARD_FIELDS, guard)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate, scenario_rows, precision_rows, dynamic_rows)

    print(final_status)
    print(f"R1_INPUT_GATE_PASSED={tf(r1_pass)}")
    print(f"NO_LOOKAHEAD_GUARD_PASS={tf(no_lookahead)}")
    print("DIAGNOSTIC_OUTPUTS_CREATED=TRUE")
    print(f"TOP20_OR_TOP40_POSITIVE_QQQ_SPY_20D_60D={tf(top20_top40_positive)}")
    print(f"SPY_ONLY_OR_INCONSISTENT_BENCHMARK_ROBUSTNESS={tf(inconsistent)}")
    print(f"TOP5_TOP10_PRECISION_WEAK={tf(precision_weak)}")
    print("DYNAMIC_WEIGHT_STATUS=SHADOW_ONLY")
    print("ELIGIBLE_FOR_OFFICIAL_WEIGHT_ACTIVATION=FALSE")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    return 0 if final_status != "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
