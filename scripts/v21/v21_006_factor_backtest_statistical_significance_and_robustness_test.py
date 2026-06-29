#!/usr/bin/env python
"""V21.006 factor backtest statistical significance and robustness test.

Research-only statistical stage for V21.005 usable matured observations. The
stage does not mutate official rankings, weights, recommendations, trades, or
shadow policy.
"""

from __future__ import annotations

import csv
import math
import random
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median


STAGE_NAME = "V21_006_FACTOR_BACKTEST_STATISTICAL_SIGNIFICANCE_AND_ROBUSTNESS_TEST"
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

OBS_SELECTION = OUT_DIR / "V21_005_OBSERVATION_SELECTION_AUDIT.csv"
WINDOW_COVERAGE = OUT_DIR / "V21_005_FORWARD_RETURN_WINDOW_COVERAGE.csv"
RANK_BUCKET_005 = OUT_DIR / "V21_005_RANK_BUCKET_FORWARD_RETURN_STATS.csv"
IC_005 = OUT_DIR / "V21_005_FACTOR_FAMILY_IC_STATS.csv"
RISK_005 = OUT_DIR / "V21_005_RISK_OVERHEAT_EFFECTIVENESS_STATS.csv"
BENCHMARK_005 = OUT_DIR / "V21_005_BENCHMARK_COMPARISON_STATS.csv"
READINESS_005 = OUT_DIR / "V21_005_DECISION_GRADE_READINESS_SCORECARD.csv"
REJECTED_005 = OUT_DIR / "V21_005_REJECTED_OR_LEAKAGE_RISK_OBSERVATIONS.csv"
SUMMARY_005 = OUT_DIR / "V21_005_BACKTEST_ENGINE_SUMMARY.csv"

PRIMARY_VALIDATION = OUT_DIR / "V21_006_PRIMARY_DATASET_VALIDATION.csv"
RANK_BUCKET_SIG = OUT_DIR / "V21_006_RANK_BUCKET_SIGNIFICANCE_STATS.csv"
MONOTONICITY = OUT_DIR / "V21_006_RANK_MONOTONICITY_TEST.csv"
IC_SIG = OUT_DIR / "V21_006_FACTOR_FAMILY_IC_SIGNIFICANCE_STATS.csv"
RANDOM_BASELINE = OUT_DIR / "V21_006_RANDOM_BASELINE_COMPARISON.csv"
SUBSAMPLE = OUT_DIR / "V21_006_SUBSAMPLE_ROBUSTNESS_STATS.csv"
OUTLIER_AUDIT = OUT_DIR / "V21_006_OUTLIER_CONCENTRATION_AUDIT.csv"
RISK_TEST = OUT_DIR / "V21_006_RISK_OVERHEAT_ROBUSTNESS_TEST.csv"
BENCHMARK_SIG = OUT_DIR / "V21_006_BENCHMARK_SIGNIFICANCE_STATS.csv"
SCORECARD = OUT_DIR / "V21_006_DECISION_GRADE_ROBUSTNESS_SCORECARD.csv"
SUMMARY = OUT_DIR / "V21_006_BACKTEST_STATISTICAL_TEST_SUMMARY.csv"
REPORT = READ_CENTER_DIR / "V21_006_FACTOR_BACKTEST_STATISTICAL_SIGNIFICANCE_AND_ROBUSTNESS_TEST_REPORT.md"

FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
CORE_FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME"]
RANK_BUCKETS = ["TOP_5", "TOP_10", "TOP_20", "TOP_QUINTILE", "BOTTOM_QUINTILE"]
RANDOM_TRIALS = 500
BENCHMARK_BOOTSTRAP_TRIALS = 50
RANDOM_BASE_SEED = 21006
MIN_OBSERVATIONS = 1000
MIN_DATES = 24
MIN_TICKERS = 100
MIN_BUCKET_N = 20
MIN_IC_DATES = 12


def norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


def parse_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() in {"NA", "N/A", "NONE", "NULL", "MISSING", "PENDING"}:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def parse_int(value: object) -> int | None:
    parsed = parse_float(value)
    return int(parsed) if parsed is not None else None


def fmt(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.10f}"
    return value


def stdev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mu = mean(values)
    return math.sqrt(sum((value - mu) ** 2 for value in values) / (len(values) - 1))


def t_p(values: list[float]) -> tuple[float | None, float | None]:
    sd = stdev(values)
    if len(values) < 2 or sd is None or sd <= 0:
        return None, None
    t_stat = mean(values) / (sd / math.sqrt(len(values)))
    p_value = math.erfc(abs(t_stat) / math.sqrt(2.0))
    return t_stat, p_value


def bootstrap_ci(values: list[float], seed: int, trials: int = 500) -> tuple[float | None, float | None]:
    if len(values) < 2:
        return None, None
    rng = random.Random(seed)
    n = len(values)
    samples = []
    for _ in range(trials):
        total = 0.0
        for _ in range(n):
            total += values[rng.randrange(n)]
        samples.append(total / n)
    samples.sort()
    return samples[int(0.025 * trials)], samples[int(0.975 * trials) - 1]


def ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    output = [0.0] * len(values)
    idx = 0
    while idx < len(indexed):
        end = idx + 1
        while end < len(indexed) and indexed[end][1] == indexed[idx][1]:
            end += 1
        avg = (idx + 1 + end) / 2.0
        for original_idx, _ in indexed[idx:end]:
            output[original_idx] = avg
        idx = end
    return output


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    x_mu = mean(xs)
    y_mu = mean(ys)
    x_den = sum((x - x_mu) ** 2 for x in xs)
    y_den = sum((y - y_mu) ** 2 for y in ys)
    if x_den <= 0 or y_den <= 0:
        return None
    return sum((x - x_mu) * (y - y_mu) for x, y in zip(xs, ys)) / math.sqrt(x_den * y_den)


def spearman(xs: list[float], ys: list[float]) -> float | None:
    return pearson(ranks(xs), ranks(ys))


def field(row: dict[str, str], candidates: list[str]) -> str:
    by_norm = {norm(key): key for key in row.keys()}
    for candidate in candidates:
        if candidate in by_norm:
            return row.get(by_norm[candidate], "")
    return ""


def forward_return(row: dict[str, str], window: str) -> float | None:
    direct = row.get(f"forward_return_{window}")
    if direct is not None:
        return parse_float(direct)
    return parse_float(field(row, [f"forward_return_{window}"]))


def benchmark_excess(row: dict[str, str], target: str, window: str) -> float | None:
    for key in [f"benchmark_excess_vs_{target}_{window}", f"benchmark_excess_vs_{target.upper()}_{window}", f"benchmark_excess_vs_{target.lower()}_{window}"]:
        if key in row:
            return parse_float(row.get(key))
    return parse_float(field(row, [f"benchmark_excess_vs_{target.lower()}_{window}", f"excess_return_vs_{target.lower()}_{window}"]))


def family_score(row: dict[str, str], family: str) -> float | None:
    lower = family.lower()
    for candidate in [f"normalized_{lower}_score", f"{lower}_score"]:
        parsed = parse_float(row.get(candidate)) if candidate in row else parse_float(field(row, [candidate]))
        if parsed is not None:
            return parsed
    return None


def load_primary_rows(selection_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    usable = [row for row in selection_rows if row.get("selection_status") == "USABLE_PRIMARY" and row.get("maturity_status") == "MATURED"]
    wanted: dict[str, set[int]] = defaultdict(set)
    selection_by_key: dict[tuple[str, int], dict[str, str]] = {}
    for row in usable:
        source = row.get("source_artifact", "")
        row_number = parse_int(row.get("row_number"))
        if source and row_number is not None:
            wanted[source].add(row_number)
            selection_by_key[(source, row_number)] = row

    primary: list[dict[str, str]] = []
    for source, row_numbers in sorted(wanted.items()):
        source_path = ROOT / source.replace("\\", "/")
        if not source_path.exists():
            continue
        with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for idx, row in enumerate(reader, start=1):
                if idx not in row_numbers:
                    continue
                selected = selection_by_key[(source, idx)]
                merged = dict(row)
                merged["_selection_status"] = selected.get("selection_status", "")
                merged["_maturity_status"] = selected.get("maturity_status", "")
                merged["_source_artifact"] = source
                merged["_row_number"] = str(idx)
                merged["_rank"] = selected.get("rank") or field(row, ["rank"])
                merged["_score"] = selected.get("score") or field(row, ["baseline_score", "score"])
                merged["_ticker"] = selected.get("ticker") or field(row, ["ticker"])
                merged["_as_of_date"] = selected.get("as_of_date") or field(row, ["as_of_date"])
                primary.append(merged)
    return primary


def available_windows(coverage_rows: list[dict[str, str]], primary_rows: list[dict[str, str]]) -> list[str]:
    windows = [
        row.get("forward_return_window", "")
        for row in coverage_rows
        if row.get("availability_status", "").startswith("AVAILABLE") and parse_int(row.get("usable_observation_count") or "0")
    ]
    if windows:
        return windows
    found = set()
    for row in primary_rows:
        for key in row:
            match = re.fullmatch(r"forward_return_([0-9]+d)", norm(key))
            if match and parse_float(row[key]) is not None:
                found.add(match.group(1))
    return sorted(found, key=lambda text: int(text[:-1]))


def rows_for_window(rows: list[dict[str, str]], window: str) -> list[dict[str, str]]:
    return [row for row in rows if forward_return(row, window) is not None and parse_float(row.get("_rank")) is not None]


def group_by_date(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[row.get("_as_of_date", "")].append(row)
    return groups


def bucket_rows_for_date(day_rows: list[dict[str, str]], bucket: str) -> list[dict[str, str]]:
    ordered = sorted(day_rows, key=lambda row: parse_float(row.get("_rank")) or 10**12)
    return bucket_rows_from_ordered(ordered, bucket)


def bucket_rows_from_ordered(ordered: list[dict[str, str]], bucket: str) -> list[dict[str, str]]:
    n = len(ordered)
    if bucket == "TOP_5":
        return ordered[: min(5, n)]
    if bucket == "TOP_10":
        return ordered[: min(10, n)]
    if bucket == "TOP_20":
        return ordered[: min(20, n)]
    q = max(1, math.ceil(n * 0.2))
    if bucket == "TOP_QUINTILE":
        return ordered[:q]
    if bucket == "BOTTOM_QUINTILE":
        return ordered[-q:]
    return []


def bucket_values(rows: list[dict[str, str]], window: str, bucket: str) -> list[float]:
    values: list[float] = []
    for day_rows in group_by_date(rows).values():
        for row in bucket_rows_for_date(day_rows, bucket):
            ret = forward_return(row, window)
            if ret is not None:
                values.append(ret)
    return values


def date_spreads(rows: list[dict[str, str]], window: str, left_bucket: str, right_bucket: str | None) -> list[float]:
    spreads = []
    for day_rows in group_by_date(rows).values():
        left = [forward_return(row, window) for row in bucket_rows_for_date(day_rows, left_bucket)]
        left_vals = [value for value in left if value is not None]
        if not left_vals:
            continue
        if right_bucket is None:
            right_vals = [forward_return(row, window) for row in day_rows if forward_return(row, window) is not None]
        else:
            right = [forward_return(row, window) for row in bucket_rows_for_date(day_rows, right_bucket)]
            right_vals = [value for value in right if value is not None]
        if right_vals:
            spreads.append(mean(left_vals) - mean(right_vals))
    return spreads


def summarize_values(values: list[float], seed: int) -> dict[str, object]:
    t_stat, p_value = t_p(values)
    ci_low, ci_high = bootstrap_ci(values, seed)
    sd = stdev(values)
    mu = mean(values) if values else None
    med = median(values) if values else None
    hit = sum(1 for value in values if value > 0) / len(values) if values else None
    skew = None
    if len(values) >= 3 and sd and sd > 0 and mu is not None:
        skew = sum(((value - mu) / sd) ** 3 for value in values) / len(values)
    return {
        "observation_count": len(values),
        "mean_return": mu,
        "median_return": med,
        "standard_deviation": sd,
        "hit_rate": hit,
        "skew_proxy": skew,
        "t_stat": t_stat,
        "p_value": p_value,
        "bootstrap_ci_low": ci_low,
        "bootstrap_ci_high": ci_high,
        "sample_status": "SUFFICIENT" if len(values) >= MIN_BUCKET_N else "INSUFFICIENT_SAMPLE",
    }


def build_rank_bucket_significance(primary_rows: list[dict[str, str]], windows: list[str]) -> list[dict[str, object]]:
    rows = []
    for w_idx, window in enumerate(windows):
        w_rows = rows_for_window(primary_rows, window)
        top_bottom = date_spreads(w_rows, window, "TOP_QUINTILE", "BOTTOM_QUINTILE")
        top_universe = date_spreads(w_rows, window, "TOP_QUINTILE", None)
        tb_summary = summarize_values(top_bottom, RANDOM_BASE_SEED + 100 + w_idx)
        tu_summary = summarize_values(top_universe, RANDOM_BASE_SEED + 200 + w_idx)
        for b_idx, bucket in enumerate(RANK_BUCKETS):
            values = bucket_values(w_rows, window, bucket)
            summary = summarize_values(values, RANDOM_BASE_SEED + 300 + w_idx * 10 + b_idx)
            rows.append(
                {
                    "forward_return_window": window,
                    "rank_bucket": bucket,
                    **summary,
                    "top_minus_bottom_spread_mean": mean(top_bottom) if top_bottom else None,
                    "top_minus_bottom_t_stat": tb_summary["t_stat"],
                    "top_minus_bottom_p_value": tb_summary["p_value"],
                    "top_minus_bottom_bootstrap_ci_low": tb_summary["bootstrap_ci_low"],
                    "top_minus_bottom_bootstrap_ci_high": tb_summary["bootstrap_ci_high"],
                    "top_minus_universe_spread_mean": mean(top_universe) if top_universe else None,
                    "top_minus_universe_t_stat": tu_summary["t_stat"],
                    "top_minus_universe_p_value": tu_summary["p_value"],
                    "top_minus_universe_bootstrap_ci_low": tu_summary["bootstrap_ci_low"],
                    "top_minus_universe_bootstrap_ci_high": tu_summary["bootstrap_ci_high"],
                    "primary_stats_maturity_filter": "MATURED_ONLY",
                    "diagnostic_observations_excluded": "TRUE",
                    "research_only": "TRUE",
                }
            )
    return rows


def build_monotonicity(primary_rows: list[dict[str, str]], windows: list[str]) -> list[dict[str, object]]:
    output = []
    for window in windows:
        w_rows = rows_for_window(primary_rows, window)
        q_means = []
        for idx in range(5):
            vals = []
            for day_rows in group_by_date(w_rows).values():
                ordered = sorted(day_rows, key=lambda row: parse_float(row.get("_rank")) or 10**12)
                n = len(ordered)
                lo = math.floor(n * idx / 5)
                hi = math.floor(n * (idx + 1) / 5) if idx < 4 else n
                vals.extend(ret for ret in (forward_return(row, window) for row in ordered[lo:hi]) if ret is not None)
            q_means.append(mean(vals) if vals else None)
        pairs = [(q_means[idx], q_means[idx + 1]) for idx in range(4) if q_means[idx] is not None and q_means[idx + 1] is not None]
        violations = sum(1 for left, right in pairs if left < right)
        score = (len(pairs) - violations) / len(pairs) if pairs else None
        if score is None:
            strength = "INSUFFICIENT_SAMPLE"
        elif score >= 1.0:
            strength = "STRONG"
        elif score >= 0.75:
            strength = "WEAK"
        elif score >= 0.5:
            strength = "MIXED"
        else:
            strength = "ABSENT"
        output.append(
            {
                "forward_return_window": window,
                "quintile_1_best_rank_mean": q_means[0],
                "quintile_2_mean": q_means[1],
                "quintile_3_mean": q_means[2],
                "quintile_4_mean": q_means[3],
                "quintile_5_worst_rank_mean": q_means[4],
                "monotonicity_score": score,
                "monotonicity_violation_count": violations,
                "monotonicity_classification": strength,
                "research_only": "TRUE",
            }
        )
    return output


def ic_series(rows: list[dict[str, str]], window: str, family: str) -> list[float]:
    values = []
    for day_rows in group_by_date(rows_for_window(rows, window)).values():
        xs, ys = [], []
        for row in day_rows:
            score = family_score(row, family)
            ret = forward_return(row, window)
            if score is not None and ret is not None:
                xs.append(score)
                ys.append(ret)
        ic = spearman(xs, ys)
        if ic is not None:
            values.append(ic)
    return values


def classify_ic(values: list[float]) -> str:
    if len(values) < MIN_IC_DATES:
        return "INSUFFICIENT_SAMPLE"
    mu = mean(values)
    pos = sum(1 for value in values if value > 0) / len(values)
    t_stat, p_value = t_p(values)
    if mu > 0 and pos >= 0.55 and t_stat is not None and p_value is not None and p_value <= 0.10:
        return "ROBUST_POSITIVE"
    if mu > 0 and pos >= 0.50:
        return "WEAK_POSITIVE"
    if mu < 0 and pos <= 0.45:
        return "NEGATIVE"
    return "MIXED"


def build_ic_significance(primary_rows: list[dict[str, str]], windows: list[str]) -> list[dict[str, object]]:
    rows = []
    for w_idx, window in enumerate(windows):
        for f_idx, family in enumerate(FAMILIES):
            values = ic_series(primary_rows, window, family)
            t_stat, p_value = t_p(values)
            ci_low, ci_high = bootstrap_ci(values, RANDOM_BASE_SEED + 1000 + w_idx * 10 + f_idx)
            sd = stdev(values)
            rows.append(
                {
                    "factor_family": family,
                    "forward_return_window": window,
                    "as_of_group_count": len(values),
                    "mean_rank_ic": mean(values) if values else None,
                    "median_rank_ic": median(values) if values else None,
                    "ic_volatility": sd,
                    "ic_ir": (mean(values) / sd) if values and sd and sd > 0 else None,
                    "positive_ic_rate": (sum(1 for value in values if value > 0) / len(values)) if values else None,
                    "t_stat": t_stat,
                    "p_value": p_value,
                    "bootstrap_ci_low": ci_low,
                    "bootstrap_ci_high": ci_high,
                    "robustness_classification": classify_ic(values),
                    "alpha_contribution_allowed": "FALSE_AUDIT_ONLY_ZERO_ALPHA_CONTROL" if family == "DATA_TRUST" else "RESEARCH_ONLY_NOT_OFFICIAL",
                    "data_trust_alpha_contribution": "0" if family == "DATA_TRUST" else "",
                    "research_only": "TRUE",
                }
            )
    return rows


def build_random_baseline(primary_rows: list[dict[str, str]], windows: list[str]) -> list[dict[str, object]]:
    output = []
    for w_idx, window in enumerate(windows):
        w_rows = rows_for_window(primary_rows, window)
        groups = {
            date: sorted(day_rows, key=lambda row: parse_float(row.get("_rank")) or 10**12)
            for date, day_rows in group_by_date(w_rows).items()
        }
        for b_idx, bucket in enumerate(["TOP_5", "TOP_10", "TOP_20", "TOP_QUINTILE"]):
            actual = bucket_values(w_rows, window, bucket)
            if len(actual) < MIN_BUCKET_N:
                output.append({"forward_return_window": window, "rank_bucket": bucket, "sample_status": "INSUFFICIENT_SAMPLE", "deterministic_seed": RANDOM_BASE_SEED + w_idx * 100 + b_idx, "random_trial_count": RANDOM_TRIALS, "research_only": "TRUE"})
                continue
            actual_mean = mean(actual)
            seed = RANDOM_BASE_SEED + w_idx * 100 + b_idx
            rng = random.Random(seed)
            trial_means = []
            for _ in range(RANDOM_TRIALS):
                vals = []
                for ordered_rows in groups.values():
                    if not ordered_rows:
                        continue
                    k = len(bucket_rows_from_ordered(ordered_rows, bucket))
                    for row in rng.sample(ordered_rows, min(k, len(ordered_rows))):
                        ret = forward_return(row, window)
                        if ret is not None:
                            vals.append(ret)
                if vals:
                    trial_means.append(mean(vals))
            better_count = sum(1 for value in trial_means if actual_mean > value)
            percentile = better_count / len(trial_means) if trial_means else None
            output.append(
                {
                    "forward_return_window": window,
                    "rank_bucket": bucket,
                    "actual_mean_return": actual_mean,
                    "random_mean_return": mean(trial_means) if trial_means else None,
                    "random_distribution_std": stdev(trial_means),
                    "actual_percentile_vs_random": percentile,
                    "probability_actual_better_than_random": percentile,
                    "random_trial_count": len(trial_means),
                    "deterministic_seed": seed,
                    "sample_status": "SUFFICIENT" if trial_means else "INSUFFICIENT_SAMPLE",
                    "research_only": "TRUE",
                }
            )
    return output


def split_rows(rows: list[dict[str, str]], split_name: str) -> dict[str, list[dict[str, str]]]:
    dates = sorted({row.get("_as_of_date", "") for row in rows})
    date_index = {date: idx for idx, date in enumerate(dates)}
    if split_name == "EARLY_LATE_AS_OF_DATE":
        half = len(dates) // 2
        return {"EARLY": [row for row in rows if date_index.get(row.get("_as_of_date", ""), 0) < half], "LATE": [row for row in rows if date_index.get(row.get("_as_of_date", ""), 0) >= half]}
    if split_name == "ODD_EVEN_AS_OF_DATE":
        return {"ODD": [row for row in rows if date_index.get(row.get("_as_of_date", ""), 0) % 2 == 1], "EVEN": [row for row in rows if date_index.get(row.get("_as_of_date", ""), 0) % 2 == 0]}
    if split_name == "LARGE_SMALL_RANK_UNIVERSE_DAY":
        counts = {date: 0 for date in dates}
        for row in rows:
            counts[row.get("_as_of_date", "")] += 1
        med = median(counts.values()) if counts else 0
        return {"LARGE_UNIVERSE_DAY": [row for row in rows if counts.get(row.get("_as_of_date", ""), 0) >= med], "SMALL_UNIVERSE_DAY": [row for row in rows if counts.get(row.get("_as_of_date", ""), 0) < med]}
    if split_name == "HIGH_LOW_VOLATILITY_PROXY":
        proxy = [(abs(parse_float(field(row, ["max_drawdown_10d"])) or 0.0), row) for row in rows]
        med = median([value for value, _ in proxy]) if proxy else 0
        return {"HIGH_VOL_PROXY": [row for value, row in proxy if value >= med], "LOW_VOL_PROXY": [row for value, row in proxy if value < med]}
    if split_name == "MARKET_REGIME_SCORE":
        scored = [(family_score(row, "MARKET_REGIME"), row) for row in rows]
        valid = [value for value, _ in scored if value is not None]
        if not valid:
            return {}
        med = median(valid)
        return {"HIGH_REGIME_SCORE": [row for value, row in scored if value is not None and value >= med], "LOW_REGIME_SCORE": [row for value, row in scored if value is not None and value < med]}
    return {}


def build_subsample(primary_rows: list[dict[str, str]], windows: list[str]) -> list[dict[str, object]]:
    output = []
    split_names = ["EARLY_LATE_AS_OF_DATE", "ODD_EVEN_AS_OF_DATE", "LIQUIDITY_PROXY", "HIGH_LOW_VOLATILITY_PROXY", "LARGE_SMALL_RANK_UNIVERSE_DAY", "MARKET_REGIME_SCORE"]
    for window in windows:
        w_rows = rows_for_window(primary_rows, window)
        for split_name in split_names:
            parts = split_rows(w_rows, split_name)
            if not parts:
                output.append({"forward_return_window": window, "split_name": split_name, "split_value": "UNAVAILABLE", "sample_status": "MISSING_REQUIRED_FIELD", "persistence_classification": "INCONCLUSIVE", "research_only": "TRUE"})
                continue
            top_means = []
            for split_value, part_rows in parts.items():
                top10 = bucket_values(part_rows, window, "TOP_10")
                top20 = bucket_values(part_rows, window, "TOP_20")
                topq = bucket_values(part_rows, window, "TOP_QUINTILE")
                rank_ic = []
                for day_rows in group_by_date(part_rows).values():
                    xs = [-(parse_float(row.get("_rank")) or 0.0) for row in day_rows]
                    ys = [forward_return(row, window) for row in day_rows]
                    pairs = [(x, y) for x, y in zip(xs, ys) if y is not None]
                    ic = spearman([x for x, _ in pairs], [y for _, y in pairs])
                    if ic is not None:
                        rank_ic.append(ic)
                top_means.append(mean(topq) if topq else None)
                output.append(
                    {
                        "forward_return_window": window,
                        "split_name": split_name,
                        "split_value": split_value,
                        "top10_mean_return": mean(top10) if top10 else None,
                        "top20_mean_return": mean(top20) if top20 else None,
                        "top_quintile_mean_return": mean(topq) if topq else None,
                        "mean_rank_ic": mean(rank_ic) if rank_ic else None,
                        "observation_count": len(part_rows),
                        "sample_status": "SUFFICIENT" if len(part_rows) >= MIN_BUCKET_N else "INSUFFICIENT_SAMPLE",
                        "persistence_classification": "",
                        "research_only": "TRUE",
                    }
                )
            valid = [value for value in top_means if value is not None]
            classification = "INCONCLUSIVE"
            if len(valid) >= 2:
                if all(value > 0 for value in valid):
                    classification = "PERSISTS"
                elif any(value > 0 for value in valid) and any(value < 0 for value in valid):
                    classification = "FLIPS"
                elif all(abs(value) < 1e-12 for value in valid):
                    classification = "DISAPPEARS"
                else:
                    classification = "WEAKENS"
            for row in output:
                if row.get("forward_return_window") == window and row.get("split_name") == split_name and row.get("persistence_classification") == "":
                    row["persistence_classification"] = classification
    return output


def remove_best(rows: list[dict[str, str]], window: str, key: str) -> list[dict[str, str]]:
    totals: dict[str, float] = defaultdict(float)
    for row in rows:
        ret = forward_return(row, window)
        if ret is not None:
            totals[row.get(key, "")] += ret
    if not totals:
        return rows
    best_key = max(totals, key=totals.get)
    return [row for row in rows if row.get(key, "") != best_key]


def top_share(rows: list[dict[str, str]], window: str, key: str) -> float | None:
    totals: dict[str, float] = defaultdict(float)
    for row in rows:
        ret = forward_return(row, window)
        if ret is not None and ret > 0:
            totals[row.get(key, "")] += ret
    total = sum(totals.values())
    if total <= 0:
        return None
    return max(totals.values()) / total


def build_outlier_audit(primary_rows: list[dict[str, str]], windows: list[str]) -> list[dict[str, object]]:
    output = []
    for window in windows:
        w_rows = rows_for_window(primary_rows, window)
        bucket = "TOP_QUINTILE"
        rows = []
        for day_rows in group_by_date(w_rows).values():
            rows.extend(bucket_rows_for_date(day_rows, bucket))
        base_vals = [ret for ret in (forward_return(row, window) for row in rows) if ret is not None]
        sorted_vals = sorted(base_vals)
        lo_cut = sorted_vals[max(0, int(len(sorted_vals) * 0.01) - 1)] if sorted_vals else None
        hi_cut = sorted_vals[min(len(sorted_vals) - 1, int(len(sorted_vals) * 0.99))] if sorted_vals else None
        variants = {
            "BASE_TOP_QUINTILE": rows,
            "EXCLUDE_BEST_TICKER": remove_best(rows, window, "_ticker"),
            "EXCLUDE_BEST_AS_OF_DATE": remove_best(rows, window, "_as_of_date"),
            "EXCLUDE_TOP_1PCT_RETURNS": [row for row in rows if hi_cut is None or (forward_return(row, window) or 0) <= hi_cut],
            "EXCLUDE_BOTTOM_1PCT_RETURNS": [row for row in rows if lo_cut is None or (forward_return(row, window) or 0) >= lo_cut],
        }
        base_mean = mean(base_vals) if base_vals else None
        for variant, variant_rows in variants.items():
            vals = [ret for ret in (forward_return(row, window) for row in variant_rows) if ret is not None]
            variant_mean = mean(vals) if vals else None
            dependency = "ROBUST"
            if base_mean is not None and variant != "BASE_TOP_QUINTILE":
                if variant_mean is None or (base_mean > 0 and variant_mean <= 0) or abs(variant_mean) < abs(base_mean) * 0.5:
                    dependency = "OUTLIER_DEPENDENT"
            output.append(
                {
                    "forward_return_window": window,
                    "audit_variant": variant,
                    "rank_bucket": bucket,
                    "observation_count": len(vals),
                    "mean_return": variant_mean,
                    "base_mean_return": base_mean,
                    "top_ticker_positive_contribution_share": top_share(rows, window, "_ticker"),
                    "top_date_positive_contribution_share": top_share(rows, window, "_as_of_date"),
                    "outlier_dependency_classification": dependency,
                    "research_only": "TRUE",
                }
            )
    return output


def build_risk_test(risk_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    output = []
    by_window: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in risk_rows:
        by_window[row.get("forward_return_window", "")][row.get("risk_overheat_group", "")] = row
    for window, groups in sorted(by_window.items()):
        blocked = parse_float(groups.get("HIGH_RANK_BLOCKED", {}).get("mean_forward_return"))
        not_blocked = parse_float(groups.get("HIGH_RANK_NOT_BLOCKED", {}).get("mean_forward_return"))
        risk_blocked_n = parse_int(groups.get("RISK_BLOCKED", {}).get("observation_count")) or 0
        high_blocked_n = parse_int(groups.get("HIGH_RANK_BLOCKED", {}).get("observation_count")) or 0
        false_block_rate = None
        if blocked is not None and not_blocked is not None and high_blocked_n > 0:
            false_block_rate = 1.0 if blocked > not_blocked else 0.0
        if risk_blocked_n == 0 and high_blocked_n == 0:
            classification = "INCONCLUSIVE"
        elif blocked is not None and not_blocked is not None and blocked < not_blocked:
            classification = "PROTECTIVE"
        elif blocked is not None and not_blocked is not None and blocked > not_blocked:
            classification = "OVERLY_RESTRICTIVE"
        else:
            classification = "MIXED"
        output.append(
            {
                "forward_return_window": window,
                "blocked_high_rank_mean_return": blocked,
                "nonblocked_high_rank_mean_return": not_blocked,
                "risk_blocked_observation_count": risk_blocked_n,
                "high_rank_blocked_observation_count": high_blocked_n,
                "false_block_candidate_rate": false_block_rate,
                "risk_overheat_logic_classification": classification,
                "sample_status": "SUFFICIENT" if high_blocked_n > 0 else "INSUFFICIENT_OR_NO_BLOCKED_NAMES",
                "research_only": "TRUE",
            }
        )
    return output


def build_benchmark_sig(primary_rows: list[dict[str, str]], benchmark_rows: list[dict[str, str]], windows: list[str]) -> list[dict[str, object]]:
    output = []
    targets = sorted({row.get("comparison_target", "") for row in benchmark_rows if row.get("comparison_target")}) or ["EQUAL_WEIGHT_UNIVERSE", "SPY", "QQQ", "SOXX"]
    all_columns = set()
    for row in primary_rows[:1]:
        all_columns.update(row.keys())
    for window in windows:
        w_rows = rows_for_window(primary_rows, window)
        universe = [ret for ret in (forward_return(row, window) for row in w_rows) if ret is not None]
        universe_mean = mean(universe) if universe else 0.0
        for bucket in ["TOP_10", "TOP_20", "TOP_QUINTILE"]:
            selected = []
            for day_rows in group_by_date(w_rows).values():
                selected.extend(bucket_rows_for_date(day_rows, bucket))
            bucket_rets = [ret for ret in (forward_return(row, window) for row in selected) if ret is not None]
            for target in targets:
                if target == "EQUAL_WEIGHT_UNIVERSE":
                    excess = [value - universe_mean for value in bucket_rets]
                    status = "AVAILABLE" if excess else "UNAVAILABLE"
                else:
                    candidate_columns = [
                        f"benchmark_excess_vs_{target}_{window}",
                        f"benchmark_excess_vs_{target.upper()}_{window}",
                        f"benchmark_excess_vs_{target.lower()}_{window}",
                    ]
                    column = next((candidate for candidate in candidate_columns if candidate in all_columns), "")
                    excess = [parse_float(row.get(column)) for row in selected] if column else []
                    excess = [value for value in excess if value is not None]
                    status = "AVAILABLE" if excess else "UNAVAILABLE"
                t_stat, p_value = t_p(excess)
                ci_low, ci_high = bootstrap_ci(excess, RANDOM_BASE_SEED + len(output), BENCHMARK_BOOTSTRAP_TRIALS)
                classification = "UNAVAILABLE"
                if len(excess) >= MIN_BUCKET_N:
                    if mean(excess) > 0 and ci_low is not None and ci_low > 0:
                        classification = "ROBUST"
                    elif mean(excess) > 0:
                        classification = "MIXED"
                    else:
                        classification = "MIXED"
                output.append(
                    {
                        "forward_return_window": window,
                        "rank_bucket": bucket,
                        "comparison_target": target,
                        "observation_count": len(excess),
                        "mean_excess_return": mean(excess) if excess else None,
                        "t_stat": t_stat,
                        "p_value": p_value,
                        "bootstrap_ci_low": ci_low,
                        "bootstrap_ci_high": ci_high,
                        "benchmark_data_status": status,
                        "benchmark_robustness_classification": classification,
                        "research_only": "TRUE",
                    }
                )
    return output


def pass_bool(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def build_validation(selection_rows: list[dict[str, str]], rejected_rows: list[dict[str, str]], summary_005: dict[str, str], windows: list[str], primary_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    return [
        {"validation_item": "primary_usable_matured_observation_count", "validation_value": len(primary_rows), "validation_status": "PASS" if len(primary_rows) > 0 else "FAIL", "research_only": "TRUE"},
        {"validation_item": "distinct_as_of_date_count", "validation_value": len({row.get("_as_of_date", "") for row in primary_rows}), "validation_status": "PASS", "research_only": "TRUE"},
        {"validation_item": "distinct_ticker_count", "validation_value": len({row.get("_ticker", "") for row in primary_rows}), "validation_status": "PASS", "research_only": "TRUE"},
        {"validation_item": "evaluated_forward_return_windows", "validation_value": "|".join(windows), "validation_status": "PASS" if windows else "DOWNGRADED_MISSING_WINDOWS", "research_only": "TRUE"},
        {"validation_item": "rejected_diagnostic_excluded_from_primary_statistics", "validation_value": len(rejected_rows), "validation_status": "PASS", "research_only": "TRUE"},
        {"validation_item": "data_trust_ranking_weight", "validation_value": summary_005.get("data_trust_ranking_weight", "0"), "validation_status": "PASS" if summary_005.get("data_trust_ranking_weight", "0") == "0" else "FAIL", "research_only": "TRUE"},
        {"validation_item": "data_trust_alpha_contribution", "validation_value": summary_005.get("data_trust_alpha_contribution", "0"), "validation_status": "PASS" if summary_005.get("data_trust_alpha_contribution", "0") == "0" else "FAIL", "research_only": "TRUE"},
        {"validation_item": "official_ranking_mutation_count", "validation_value": summary_005.get("official_ranking_mutation_count", "0"), "validation_status": "PASS" if summary_005.get("official_ranking_mutation_count", "0") == "0" else "FAIL", "research_only": "TRUE"},
        {"validation_item": "official_factor_weight_mutation_count", "validation_value": summary_005.get("official_factor_weight_mutation_count", "0"), "validation_status": "PASS" if summary_005.get("official_factor_weight_mutation_count", "0") == "0" else "FAIL", "research_only": "TRUE"},
        {"validation_item": "official_recommendation_count", "validation_value": summary_005.get("official_recommendation_count", "0"), "validation_status": "PASS" if summary_005.get("official_recommendation_count", "0") == "0" else "FAIL", "research_only": "TRUE"},
        {"validation_item": "trade_action_count", "validation_value": summary_005.get("trade_action_count", "0"), "validation_status": "PASS" if summary_005.get("trade_action_count", "0") == "0" else "FAIL", "research_only": "TRUE"},
        {"validation_item": "shadow_activation", "validation_value": summary_005.get("shadow_activation", "FALSE"), "validation_status": "PASS" if summary_005.get("shadow_activation", "FALSE") == "FALSE" else "FAIL", "research_only": "TRUE"},
        {"validation_item": "primary_stats_selection_status", "validation_value": "USABLE_PRIMARY|MATURED", "validation_status": "PASS" if all(row.get("_selection_status") == "USABLE_PRIMARY" and row.get("_maturity_status") == "MATURED" for row in primary_rows) else "FAIL", "research_only": "TRUE"},
    ]


def build_scorecard(primary_rows: list[dict[str, str]], windows: list[str], rank_rows: list[dict[str, object]], ic_rows: list[dict[str, object]], random_rows: list[dict[str, object]], outlier_rows: list[dict[str, object]], validation_rows: list[dict[str, object]], readiness_005: list[dict[str, str]]) -> tuple[list[dict[str, object]], str, str]:
    distinct_dates = len({row.get("_as_of_date", "") for row in primary_rows})
    distinct_tickers = len({row.get("_ticker", "") for row in primary_rows})
    spread_rows = [row for row in rank_rows if row.get("rank_bucket") == "TOP_QUINTILE"]
    top_bottom_pos = sum(1 for row in spread_rows if parse_float(row.get("top_minus_bottom_spread_mean")) is not None and float(row["top_minus_bottom_spread_mean"]) > 0)
    top_universe_pos = sum(1 for row in spread_rows if parse_float(row.get("top_minus_universe_spread_mean")) is not None and float(row["top_minus_universe_spread_mean"]) > 0)
    core_ic = [row for row in ic_rows if row.get("factor_family") in CORE_FAMILIES and row.get("robustness_classification") == "ROBUST_POSITIVE"]
    random_ok = any((parse_float(row.get("actual_percentile_vs_random")) or 0) >= 0.60 for row in random_rows)
    outlier_ok = not any(row.get("outlier_dependency_classification") == "OUTLIER_DEPENDENT" for row in outlier_rows if row.get("audit_variant") != "BASE_TOP_QUINTILE")
    leakage_ok = not any(row.get("hard_gate") == "no_critical_leakage_risk" and row.get("gate_passed") == "FALSE" for row in readiness_005)
    validations_ok = all(row.get("validation_status") == "PASS" for row in validation_rows if row.get("validation_item") in {"data_trust_ranking_weight", "data_trust_alpha_contribution", "official_ranking_mutation_count", "official_factor_weight_mutation_count", "official_recommendation_count", "trade_action_count", "shadow_activation"})
    gates = [
        ("minimum_primary_usable_matured_observations", len(primary_rows) >= MIN_OBSERVATIONS, len(primary_rows), f">={MIN_OBSERVATIONS}"),
        ("minimum_distinct_as_of_dates", distinct_dates >= MIN_DATES, distinct_dates, f">={MIN_DATES}"),
        ("minimum_distinct_tickers", distinct_tickers >= MIN_TICKERS, distinct_tickers, f">={MIN_TICKERS}"),
        ("at_least_two_forward_return_windows_evaluated", len(windows) >= 2, len(windows), ">=2"),
        ("positive_top_minus_bottom_spread_majority_windows", top_bottom_pos > len(spread_rows) / 2 if spread_rows else False, top_bottom_pos, "majority"),
        ("positive_top_minus_universe_spread_majority_windows", top_universe_pos > len(spread_rows) / 2 if spread_rows else False, top_universe_pos, "majority"),
        ("rank_ic_positive_statistically_meaningful_core_family", bool(core_ic), len(core_ic), ">=1"),
        ("random_baseline_percentile_above_threshold", random_ok, max([parse_float(row.get("actual_percentile_vs_random")) or 0 for row in random_rows] or [0]), ">=0.60"),
        ("signal_not_entirely_outlier_dependent", outlier_ok, pass_bool(outlier_ok), "TRUE"),
        ("no_critical_leakage_contamination", leakage_ok, pass_bool(leakage_ok), "TRUE"),
        ("data_trust_zero_contribution", validations_ok, pass_bool(validations_ok), "TRUE"),
        ("no_official_ranking_mutation", validations_ok, pass_bool(validations_ok), "TRUE"),
        ("no_recommendation", validations_ok, pass_bool(validations_ok), "TRUE"),
        ("no_trade_action", validations_ok, pass_bool(validations_ok), "TRUE"),
        ("no_shadow_activation", validations_ok, pass_bool(validations_ok), "TRUE"),
    ]
    rows = [{"hard_gate": name, "gate_passed": pass_bool(passed), "observed_value": observed, "required_value": required, "research_only": "TRUE"} for name, passed, observed, required in gates]
    hard_pass = all(passed for _, passed, _, _ in gates)
    if len(primary_rows) < MIN_OBSERVATIONS or distinct_dates < MIN_DATES or distinct_tickers < MIN_TICKERS:
        verdict = "FAIL_INSUFFICIENT_PRIMARY_OBSERVATIONS_FOR_SIGNIFICANCE_TEST"
        status = "FAIL_V21_006_INSUFFICIENT_PRIMARY_OBSERVATIONS_FOR_SIGNIFICANCE_TEST"
    elif hard_pass:
        verdict = "ROBUST_FACTOR_SIGNAL_PRESENT_BUT_STILL_RESEARCH_ONLY"
        status = "PASS_V21_006_ROBUST_FACTOR_SIGNAL_PRESENT_BUT_STILL_RESEARCH_ONLY"
    elif not outlier_ok:
        verdict = "PARTIAL_PASS_SIGNAL_OUTLIER_OR_REGIME_DEPENDENT"
        status = "PARTIAL_PASS_V21_006_SIGNAL_OUTLIER_OR_REGIME_DEPENDENT"
    else:
        verdict = "PARTIAL_PASS_WEAK_OR_MIXED_STATISTICAL_EVIDENCE"
        status = "PARTIAL_PASS_V21_006_WEAK_OR_MIXED_STATISTICAL_EVIDENCE"
    return rows, verdict, status


def write_report(summary: dict[str, object], sections: dict[str, str]) -> None:
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    text = f"""# V21.006 Factor Backtest Statistical Significance And Robustness Test Report

## Executive summary
Research-only statistical significance and robustness testing was run on V21.005 usable matured primary observations. Official rankings, official factor weights, recommendations, trade actions, and shadow policy were not mutated.

## Final verdict
{summary['final_verdict']}

Final status: {summary['final_status']}

## Primary dataset validation
{sections['validation']}

## Rank bucket statistical significance
{sections['rank']}

## Rank monotonicity test
{sections['monotonicity']}

## Factor family IC significance
{sections['ic']}

## Random baseline comparison
{sections['random']}

## Subsample robustness
{sections['subsample']}

## Outlier and concentration audit
{sections['outlier']}

## Risk and overheat robustness
{sections['risk']}

## Benchmark significance
{sections['benchmark']}

## DATA_TRUST zero-contribution confirmation
DATA_TRUST ranking weight is 0 and DATA_TRUST alpha contribution is 0. DATA_TRUST is treated only as audit/gate metadata and audit-only zero-alpha control.

## Decision-grade robustness scorecard
{sections['scorecard']}

## What this stage proves
This stage tests whether the observed V21.005 research signal is statistically meaningful, robust across basic deterministic subsamples, and better than deterministic random baselines where sample size permits.

## What this stage still cannot prove
This stage cannot prove production readiness, live tradability, absence of all hidden leakage, future persistence, execution quality, slippage resilience, tax impact, or portfolio capacity.

## Explicit blocked actions
No official ranking mutation. No official factor weight mutation. No official recommendation. No trade action. No shadow activation. No production or real-book readiness verdict.

## Recommended next stage
V21.007_FACTOR_ARCHITECTURE_REPAIR_PLAN_OR_WEIGHT_UPDATE_BLOCKER
"""
    REPORT.write_text(text, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    selection_rows = read_csv(OBS_SELECTION)
    rejected_rows = read_csv(REJECTED_005)
    coverage_rows = read_csv(WINDOW_COVERAGE)
    summary_005_rows = read_csv(SUMMARY_005)
    summary_005 = summary_005_rows[0] if summary_005_rows else {}
    readiness_005 = read_csv(READINESS_005)
    primary_rows = load_primary_rows(selection_rows)
    windows = available_windows(coverage_rows, primary_rows)

    validation_rows = build_validation(selection_rows, rejected_rows, summary_005, windows, primary_rows)
    rank_rows = build_rank_bucket_significance(primary_rows, windows)
    monotonicity_rows = build_monotonicity(primary_rows, windows)
    ic_rows = build_ic_significance(primary_rows, windows)
    random_rows = build_random_baseline(primary_rows, windows)
    subsample_rows = build_subsample(primary_rows, windows)
    outlier_rows = build_outlier_audit(primary_rows, windows)
    risk_rows = build_risk_test(read_csv(RISK_005))
    benchmark_rows = build_benchmark_sig(primary_rows, read_csv(BENCHMARK_005), windows)
    scorecard_rows, verdict, status = build_scorecard(primary_rows, windows, rank_rows, ic_rows, random_rows, outlier_rows, validation_rows, readiness_005)

    created_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    summary = {
        "stage_name": STAGE_NAME,
        "created_at": created_at,
        "research_only": "TRUE",
        "audit_only": "FALSE_ANALYTICAL_RESEARCH_ONLY",
        "final_verdict": verdict,
        "final_status": status,
        "usable_primary_matured_observation_count": len(primary_rows),
        "rejected_or_diagnostic_observation_count": len(rejected_rows),
        "distinct_as_of_dates": len({row.get("_as_of_date", "") for row in primary_rows}),
        "distinct_tickers": len({row.get("_ticker", "") for row in primary_rows}),
        "evaluated_forward_windows": "|".join(windows),
        "random_trial_count": RANDOM_TRIALS,
        "random_seed_base": RANDOM_BASE_SEED,
        "data_trust_ranking_weight": "0",
        "data_trust_alpha_contribution": "0",
        "official_ranking_mutation_count": "0",
        "official_factor_weight_mutation_count": "0",
        "official_recommendation_count": "0",
        "trade_action_count": "0",
        "shadow_activation": "FALSE",
        "recommended_next_stage": "V21.007_FACTOR_ARCHITECTURE_REPAIR_PLAN_OR_WEIGHT_UPDATE_BLOCKER",
    }

    write_csv(PRIMARY_VALIDATION, validation_rows, ["validation_item", "validation_value", "validation_status", "research_only"])
    write_csv(RANK_BUCKET_SIG, rank_rows, ["forward_return_window", "rank_bucket", "observation_count", "mean_return", "median_return", "standard_deviation", "hit_rate", "skew_proxy", "t_stat", "p_value", "bootstrap_ci_low", "bootstrap_ci_high", "top_minus_bottom_spread_mean", "top_minus_bottom_t_stat", "top_minus_bottom_p_value", "top_minus_bottom_bootstrap_ci_low", "top_minus_bottom_bootstrap_ci_high", "top_minus_universe_spread_mean", "top_minus_universe_t_stat", "top_minus_universe_p_value", "top_minus_universe_bootstrap_ci_low", "top_minus_universe_bootstrap_ci_high", "sample_status", "primary_stats_maturity_filter", "diagnostic_observations_excluded", "research_only"])
    write_csv(MONOTONICITY, monotonicity_rows, ["forward_return_window", "quintile_1_best_rank_mean", "quintile_2_mean", "quintile_3_mean", "quintile_4_mean", "quintile_5_worst_rank_mean", "monotonicity_score", "monotonicity_violation_count", "monotonicity_classification", "research_only"])
    write_csv(IC_SIG, ic_rows, ["factor_family", "forward_return_window", "as_of_group_count", "mean_rank_ic", "median_rank_ic", "ic_volatility", "ic_ir", "positive_ic_rate", "t_stat", "p_value", "bootstrap_ci_low", "bootstrap_ci_high", "robustness_classification", "alpha_contribution_allowed", "data_trust_alpha_contribution", "research_only"])
    write_csv(RANDOM_BASELINE, random_rows, ["forward_return_window", "rank_bucket", "actual_mean_return", "random_mean_return", "random_distribution_std", "actual_percentile_vs_random", "probability_actual_better_than_random", "random_trial_count", "deterministic_seed", "sample_status", "research_only"])
    write_csv(SUBSAMPLE, subsample_rows, ["forward_return_window", "split_name", "split_value", "top10_mean_return", "top20_mean_return", "top_quintile_mean_return", "mean_rank_ic", "observation_count", "sample_status", "persistence_classification", "research_only"])
    write_csv(OUTLIER_AUDIT, outlier_rows, ["forward_return_window", "audit_variant", "rank_bucket", "observation_count", "mean_return", "base_mean_return", "top_ticker_positive_contribution_share", "top_date_positive_contribution_share", "outlier_dependency_classification", "research_only"])
    write_csv(RISK_TEST, risk_rows, ["forward_return_window", "blocked_high_rank_mean_return", "nonblocked_high_rank_mean_return", "risk_blocked_observation_count", "high_rank_blocked_observation_count", "false_block_candidate_rate", "risk_overheat_logic_classification", "sample_status", "research_only"])
    write_csv(BENCHMARK_SIG, benchmark_rows, ["forward_return_window", "rank_bucket", "comparison_target", "observation_count", "mean_excess_return", "t_stat", "p_value", "bootstrap_ci_low", "bootstrap_ci_high", "benchmark_data_status", "benchmark_robustness_classification", "research_only"])
    write_csv(SCORECARD, scorecard_rows, ["hard_gate", "gate_passed", "observed_value", "required_value", "research_only"])
    write_csv(SUMMARY, [summary], list(summary.keys()))

    sections = {
        "validation": f"Primary usable matured observations: {summary['usable_primary_matured_observation_count']}; dates: {summary['distinct_as_of_dates']}; tickers: {summary['distinct_tickers']}; windows: {summary['evaluated_forward_windows']}. Rejected and diagnostic observations are excluded from primary statistics.",
        "rank": f"{len(rank_rows)} rank-bucket significance rows written to {rel(RANK_BUCKET_SIG)}.",
        "monotonicity": f"{len(monotonicity_rows)} monotonicity rows written to {rel(MONOTONICITY)}.",
        "ic": f"{len(ic_rows)} factor-family IC significance rows written to {rel(IC_SIG)}.",
        "random": f"Deterministic random baselines used {RANDOM_TRIALS} trials per tested bucket with seed base {RANDOM_BASE_SEED}.",
        "subsample": f"{len(subsample_rows)} subsample robustness rows written to {rel(SUBSAMPLE)}.",
        "outlier": f"{len(outlier_rows)} outlier and concentration audit rows written to {rel(OUTLIER_AUDIT)}.",
        "risk": f"{len(risk_rows)} risk/overheat robustness rows written to {rel(RISK_TEST)}.",
        "benchmark": f"{len(benchmark_rows)} benchmark significance rows written to {rel(BENCHMARK_SIG)}.",
        "scorecard": f"{sum(1 for row in scorecard_rows if row['gate_passed'] == 'TRUE')} of {len(scorecard_rows)} hard gates passed. The verdict remains research-only.",
    }
    write_report(summary, sections)

    print(f"STAGE_NAME={STAGE_NAME}")
    print(f"final_verdict={verdict}")
    print(f"final_status={status}")
    print(f"usable_primary_matured_observation_count={len(primary_rows)}")
    print(f"evaluated_forward_windows={'|'.join(windows)}")
    print(f"random_trial_count={RANDOM_TRIALS}")
    print(f"random_seed_base={RANDOM_BASE_SEED}")
    print("research_only=TRUE")


if __name__ == "__main__":
    main()
