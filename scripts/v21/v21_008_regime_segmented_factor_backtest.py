#!/usr/bin/env python
"""V21.008 regime-segmented factor backtest.

Research-only regime segmented evaluation after V21.007 blocked weight updates
for regime segmentation. This stage does not mutate official rankings, weights,
recommendations, trades, or shadow policy.
"""

from __future__ import annotations

import csv
import math
import random
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median


STAGE_NAME = "V21_008_REGIME_SEGMENTED_FACTOR_BACKTEST"
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

V21_007_INPUTS = [
    OUT_DIR / "V21_007_V21_006_VERDICT_INGEST_AUDIT.csv",
    OUT_DIR / "V21_007_OUTLIER_DEPENDENCY_DIAGNOSIS.csv",
    OUT_DIR / "V21_007_REGIME_DEPENDENCY_DIAGNOSIS.csv",
    OUT_DIR / "V21_007_FACTOR_FAMILY_REPAIR_DIAGNOSIS.csv",
    OUT_DIR / "V21_007_RANK_ARCHITECTURE_DIAGNOSIS.csv",
    OUT_DIR / "V21_007_RISK_OVERHEAT_REPAIR_DIAGNOSIS.csv",
    OUT_DIR / "V21_007_WEIGHT_UPDATE_BLOCKER_DECISION.csv",
    OUT_DIR / "V21_007_REPAIR_ROADMAP.csv",
    OUT_DIR / "V21_007_FACTOR_ARCHITECTURE_REPAIR_PLAN_SUMMARY.csv",
    ROOT / "outputs" / "v21" / "read_center" / "V21_007_FACTOR_ARCHITECTURE_REPAIR_PLAN_OR_WEIGHT_UPDATE_BLOCKER_REPORT.md",
]

OBS_SELECTION = OUT_DIR / "V21_005_OBSERVATION_SELECTION_AUDIT.csv"
BLOCKER_AUDIT = OUT_DIR / "V21_008_V21_007_BLOCKER_INGEST_AUDIT.csv"
LABEL_INVENTORY = OUT_DIR / "V21_008_REGIME_LABEL_INVENTORY.csv"
RANK_PERF = OUT_DIR / "V21_008_REGIME_RANK_BUCKET_PERFORMANCE.csv"
IC_STATS = OUT_DIR / "V21_008_REGIME_FACTOR_FAMILY_IC_STATS.csv"
RANDOM_BASELINE = OUT_DIR / "V21_008_REGIME_RANDOM_BASELINE_COMPARISON.csv"
BENCHMARK = OUT_DIR / "V21_008_REGIME_BENCHMARK_COMPARISON.csv"
TRANSITION_AUDIT = OUT_DIR / "V21_008_REGIME_TRANSITION_CONFLICT_AUDIT.csv"
RISK_BEHAVIOR = OUT_DIR / "V21_008_REGIME_RISK_OVERHEAT_BEHAVIOR.csv"
DECISION = OUT_DIR / "V21_008_REGIME_SEGMENTATION_DECISION.csv"
SUMMARY = OUT_DIR / "V21_008_REGIME_SEGMENTED_BACKTEST_SUMMARY.csv"
REPORT = READ_CENTER_DIR / "V21_008_REGIME_SEGMENTED_FACTOR_BACKTEST_REPORT.md"

FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
REGIME_LABELS = [
    "risk_on",
    "risk_off",
    "neutral",
    "high_vix",
    "low_vix",
    "QQQ_uptrend",
    "QQQ_downtrend",
    "SPY_uptrend",
    "SPY_downtrend",
    "sector_uptrend",
    "sector_downtrend",
    "FOMC",
    "CPI",
    "NFP",
    "earnings_season",
]
RANDOM_SEED_BASE = 21008
RANDOM_TRIALS = 500
MIN_BUCKET_N = 20
MIN_IC_GROUPS = 8
NEXT_STAGES = {
    "V21.009_OUTLIER_NEUTRALIZED_FACTOR_BACKTEST",
    "V21.010_RISK_OVERHEAT_FALSE_BLOCK_REPAIR",
    "V21.011_FACTOR_FAMILY_RESCALING_AND_NONLINEAR_INTERACTION_TEST",
    "V21.012_SECTOR_NEUTRAL_AND_THEME_CONCENTRATION_AUDIT",
    "V21.013_REGIME_AWARE_SHADOW_SCORING_EXPERIMENT_PLAN",
}


def norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")


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


def fmt(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.10f}"
    return value


def parse_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
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


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def pass_bool(value: bool) -> str:
    return "TRUE" if value else "FALSE"


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
    return t_stat, math.erfc(abs(t_stat) / math.sqrt(2.0))


def bootstrap_ci(values: list[float], seed: int, trials: int = 100) -> tuple[float | None, float | None]:
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
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    return pearson(ranks(xs), ranks(ys))


def field(row: dict[str, str], candidates: list[str]) -> str:
    by_norm = {norm(key): key for key in row.keys()}
    for candidate in candidates:
        if candidate in by_norm:
            return row.get(by_norm[candidate], "")
    return ""


def forward_return(row: dict[str, str], window: str) -> float | None:
    return parse_float(row.get(f"forward_return_{window}") or field(row, [f"forward_return_{window}"]))


def family_score(row: dict[str, str], family: str) -> float | None:
    lower = family.lower()
    for candidate in [f"normalized_{lower}_score", f"{lower}_score"]:
        value = row.get(candidate) if candidate in row else field(row, [candidate])
        parsed = parse_float(value)
        if parsed is not None:
            return parsed
    return None


def benchmark_excess(row: dict[str, str], target: str, window: str) -> float | None:
    for key in [f"benchmark_excess_vs_{target}_{window}", f"benchmark_excess_vs_{target.upper()}_{window}", f"benchmark_excess_vs_{target.lower()}_{window}"]:
        if key in row:
            return parse_float(row.get(key))
    return None


def load_primary_rows(selection_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    usable = [row for row in selection_rows if row.get("selection_status") == "USABLE_PRIMARY" and row.get("maturity_status") == "MATURED"]
    wanted: dict[str, set[int]] = defaultdict(set)
    selected: dict[tuple[str, int], dict[str, str]] = {}
    for row in usable:
        source = row.get("source_artifact", "")
        row_number = parse_int(row.get("row_number"))
        if source and row_number is not None:
            wanted[source].add(row_number)
            selected[(source, row_number)] = row
    primary = []
    for source, row_numbers in sorted(wanted.items()):
        path = ROOT / source.replace("\\", "/")
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for idx, row in enumerate(reader, start=1):
                if idx not in row_numbers:
                    continue
                sel = selected[(source, idx)]
                merged = dict(row)
                merged["_ticker"] = sel.get("ticker") or field(row, ["ticker"])
                merged["_as_of_date"] = sel.get("as_of_date") or field(row, ["as_of_date"])
                merged["_rank"] = sel.get("rank") or field(row, ["rank"])
                merged["_score"] = sel.get("score") or field(row, ["baseline_score", "score"])
                merged["_source_artifact"] = source
                merged["_row_number"] = str(idx)
                primary.append(merged)
    return primary


def detect_windows(rows: list[dict[str, str]]) -> list[str]:
    found = set()
    for row in rows[:100]:
        for key in row:
            match = re.fullmatch(r"forward_return_([0-9]+d)", norm(key))
            if match:
                found.add(match.group(1))
    return sorted(found, key=lambda text: int(text[:-1]))


def derive_regimes(row: dict[str, str]) -> list[str]:
    score = family_score(row, "MARKET_REGIME")
    labels = []
    if score is not None:
        if score >= 0.55:
            labels.append("risk_on")
        elif score <= 0.45:
            labels.append("risk_off")
        else:
            labels.append("neutral")
    for label in ["high_vix", "low_vix", "QQQ_uptrend", "QQQ_downtrend", "SPY_uptrend", "SPY_downtrend", "sector_uptrend", "sector_downtrend", "FOMC", "CPI", "NFP", "earnings_season"]:
        value = field(row, [label])
        if str(value).strip().upper() in {"1", "TRUE", "YES", label.upper()}:
            labels.append(label)
    return labels


def attach_regimes(rows: list[dict[str, str]]) -> None:
    for row in rows:
        row["_regime_labels"] = "|".join(derive_regimes(row))


def rows_for_regime(rows: list[dict[str, str]], regime: str, window: str | None = None) -> list[dict[str, str]]:
    output = [row for row in rows if regime in row.get("_regime_labels", "").split("|")]
    if window:
        output = [row for row in output if forward_return(row, window) is not None and parse_float(row.get("_rank")) is not None]
    return output


def group_by_date(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[row.get("_as_of_date", "")].append(row)
    return groups


def bucket_from_ordered(ordered: list[dict[str, str]], bucket: str) -> list[dict[str, str]]:
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
    if bucket == "MIDDLE_BUCKET":
        lo = max(0, math.floor(n * 0.4))
        hi = max(lo + 1, math.ceil(n * 0.6))
        return ordered[lo:hi]
    if bucket == "BOTTOM_QUINTILE":
        return ordered[-q:]
    return []


def bucket_values(rows: list[dict[str, str]], window: str, bucket: str) -> list[float]:
    values = []
    for day_rows in group_by_date(rows).values():
        ordered = sorted(day_rows, key=lambda row: parse_float(row.get("_rank")) or 10**12)
        for row in bucket_from_ordered(ordered, bucket):
            ret = forward_return(row, window)
            if ret is not None:
                values.append(ret)
    return values


def date_spreads(rows: list[dict[str, str]], window: str, left_bucket: str, right_bucket: str | None) -> list[float]:
    spreads = []
    for day_rows in group_by_date(rows).values():
        ordered = sorted(day_rows, key=lambda row: parse_float(row.get("_rank")) or 10**12)
        left = [forward_return(row, window) for row in bucket_from_ordered(ordered, left_bucket)]
        left = [value for value in left if value is not None]
        if not left:
            continue
        if right_bucket is None:
            right = [forward_return(row, window) for row in ordered]
        else:
            right = [forward_return(row, window) for row in bucket_from_ordered(ordered, right_bucket)]
        right = [value for value in right if value is not None]
        if right:
            spreads.append(mean(left) - mean(right))
    return spreads


def monotonicity_score(rows: list[dict[str, str]], window: str) -> tuple[float | None, int]:
    q_means = []
    for idx in range(5):
        vals = []
        for day_rows in group_by_date(rows).values():
            ordered = sorted(day_rows, key=lambda row: parse_float(row.get("_rank")) or 10**12)
            n = len(ordered)
            lo = math.floor(n * idx / 5)
            hi = math.floor(n * (idx + 1) / 5) if idx < 4 else n
            vals.extend(ret for ret in (forward_return(row, window) for row in ordered[lo:hi]) if ret is not None)
        q_means.append(mean(vals) if vals else None)
    pairs = [(q_means[idx], q_means[idx + 1]) for idx in range(4) if q_means[idx] is not None and q_means[idx + 1] is not None]
    if not pairs:
        return None, 0
    violations = sum(1 for left, right in pairs if left < right)
    return (len(pairs) - violations) / len(pairs), violations


def build_blocker_audit(summary_007: dict[str, str], blocker_007: dict[str, str], missing: list[str]) -> list[dict[str, object]]:
    checks = [
        ("required_v21_007_artifacts_present", not missing, "|".join(missing) if missing else "ALL_PRESENT", "TRUE"),
        ("v21_007_blocker_decision_ingested", summary_007.get("weight_update_blocker_decision") == "WEIGHT_UPDATE_BLOCKED_REGIME_SEGMENTATION_REQUIRED", summary_007.get("weight_update_blocker_decision", ""), "WEIGHT_UPDATE_BLOCKED_REGIME_SEGMENTATION_REQUIRED"),
        ("official_weight_update_allowed_false", blocker_007.get("official_weight_update_allowed") == "FALSE", blocker_007.get("official_weight_update_allowed", ""), "FALSE"),
        ("research_only_limited_weight_experiment_allowed_false", blocker_007.get("research_only_limited_weight_experiment_allowed") == "FALSE", blocker_007.get("research_only_limited_weight_experiment_allowed", ""), "FALSE"),
        ("data_trust_ranking_weight_zero", summary_007.get("data_trust_ranking_weight") == "0", summary_007.get("data_trust_ranking_weight", ""), "0"),
        ("data_trust_alpha_contribution_zero", summary_007.get("data_trust_alpha_contribution") == "0", summary_007.get("data_trust_alpha_contribution", ""), "0"),
        ("official_ranking_mutation_count_zero", summary_007.get("official_ranking_mutation_count") == "0", summary_007.get("official_ranking_mutation_count", ""), "0"),
        ("official_factor_weight_mutation_count_zero", summary_007.get("official_factor_weight_mutation_count") == "0", summary_007.get("official_factor_weight_mutation_count", ""), "0"),
        ("official_recommendation_count_zero", summary_007.get("official_recommendation_count") == "0", summary_007.get("official_recommendation_count", ""), "0"),
        ("trade_action_count_zero", summary_007.get("trade_action_count") == "0", summary_007.get("trade_action_count", ""), "0"),
        ("shadow_activation_false", summary_007.get("shadow_activation") == "FALSE", summary_007.get("shadow_activation", ""), "FALSE"),
    ]
    return [{"audit_item": name, "audit_passed": pass_bool(passed), "observed_value": observed, "required_value": required, "research_only": "TRUE"} for name, passed, observed, required in checks]


def build_inventory(rows: list[dict[str, str]], windows: list[str]) -> list[dict[str, object]]:
    output = []
    for label in REGIME_LABELS:
        label_rows = rows_for_regime(rows, label)
        window_count = sum(1 for window in windows if any(forward_return(row, window) is not None for row in label_rows))
        n = len(label_rows)
        status = "SUFFICIENT" if n >= 500 and window_count >= 1 else "INSUFFICIENT_SAMPLE" if n > 0 else "MISSING_REGIME_LABEL_SOURCE"
        output.append(
            {
                "regime_label": label,
                "observation_count": n,
                "distinct_as_of_dates": len({row.get("_as_of_date", "") for row in label_rows}),
                "distinct_tickers": len({row.get("_ticker", "") for row in label_rows}),
                "evaluated_forward_window_count": window_count,
                "evaluated_forward_windows": "|".join([window for window in windows if any(forward_return(row, window) is not None for row in label_rows)]),
                "sample_adequacy": status,
                "research_only": "TRUE",
            }
        )
    return output


def build_rank_perf(rows: list[dict[str, str]], inventory: list[dict[str, object]], windows: list[str]) -> list[dict[str, object]]:
    output = []
    for inv in inventory:
        if inv["sample_adequacy"] == "MISSING_REGIME_LABEL_SOURCE":
            continue
        regime = str(inv["regime_label"])
        for window in windows:
            r_rows = rows_for_regime(rows, regime, window)
            mono, violations = monotonicity_score(r_rows, window)
            tb = date_spreads(r_rows, window, "TOP_QUINTILE", "BOTTOM_QUINTILE")
            tu = date_spreads(r_rows, window, "TOP_QUINTILE", None)
            for bucket in ["TOP_5", "TOP_10", "TOP_20", "TOP_QUINTILE", "MIDDLE_BUCKET", "BOTTOM_QUINTILE"]:
                vals = bucket_values(r_rows, window, bucket)
                output.append(
                    {
                        "regime_label": regime,
                        "forward_return_window": window,
                        "rank_bucket": bucket,
                        "observation_count": len(vals),
                        "mean_forward_return": mean(vals) if vals else None,
                        "median_forward_return": median(vals) if vals else None,
                        "hit_rate": sum(1 for value in vals if value > 0) / len(vals) if vals else None,
                        "standard_deviation": stdev(vals),
                        "top_minus_bottom_spread": mean(tb) if tb else None,
                        "top_minus_universe_spread": mean(tu) if tu else None,
                        "monotonicity_score": mono,
                        "monotonicity_violation_count": violations,
                        "sample_adequacy": "SUFFICIENT" if len(vals) >= MIN_BUCKET_N else "INSUFFICIENT_SAMPLE",
                        "research_only": "TRUE",
                    }
                )
    return output


def ic_series(rows: list[dict[str, str]], window: str, family: str) -> tuple[list[float], list[float]]:
    pearsons, spearmans = [], []
    for day_rows in group_by_date(rows).values():
        xs, ys = [], []
        for row in day_rows:
            score = family_score(row, family)
            ret = forward_return(row, window)
            if score is not None and ret is not None:
                xs.append(score)
                ys.append(ret)
        p = pearson(xs, ys)
        s = spearman(xs, ys)
        if p is not None:
            pearsons.append(p)
        if s is not None:
            spearmans.append(s)
    return pearsons, spearmans


def classify_ic(values: list[float]) -> str:
    if len(values) < MIN_IC_GROUPS:
        return "INSUFFICIENT_SAMPLE"
    mu = mean(values)
    pos = sum(1 for value in values if value > 0) / len(values)
    t_stat, p_value = t_p(values)
    if mu > 0 and pos >= 0.55 and t_stat is not None and p_value is not None and p_value <= 0.10:
        return "ROBUST_POSITIVE_IN_REGIME"
    if mu > 0 and pos >= 0.50:
        return "WEAK_POSITIVE_IN_REGIME"
    if mu < 0 and pos <= 0.45:
        return "NEGATIVE_IN_REGIME"
    return "MIXED_IN_REGIME"


def build_ic(rows: list[dict[str, str]], inventory: list[dict[str, object]], windows: list[str]) -> list[dict[str, object]]:
    output = []
    for inv in inventory:
        if inv["sample_adequacy"] == "MISSING_REGIME_LABEL_SOURCE":
            continue
        regime = str(inv["regime_label"])
        for window in windows:
            r_rows = rows_for_regime(rows, regime, window)
            for family in FAMILIES:
                pearsons, spearmans = ic_series(r_rows, window, family)
                t_stat, p_value = t_p(spearmans)
                sd = stdev(spearmans)
                output.append(
                    {
                        "regime_label": regime,
                        "factor_family": family,
                        "forward_return_window": window,
                        "as_of_group_count": len(spearmans),
                        "pearson_ic_mean": mean(pearsons) if pearsons else None,
                        "spearman_rank_ic_mean": mean(spearmans) if spearmans else None,
                        "mean_ic": mean(spearmans) if spearmans else None,
                        "median_ic": median(spearmans) if spearmans else None,
                        "ic_volatility": sd,
                        "ic_ir": mean(spearmans) / sd if spearmans and sd and sd > 0 else None,
                        "positive_ic_rate": sum(1 for value in spearmans if value > 0) / len(spearmans) if spearmans else None,
                        "t_stat": t_stat,
                        "p_value": p_value,
                        "family_regime_classification": "INSUFFICIENT_SAMPLE" if family == "DATA_TRUST" else classify_ic(spearmans),
                        "data_trust_alpha_contribution": "0" if family == "DATA_TRUST" else "",
                        "research_only": "TRUE",
                    }
                )
    return output


def build_random(rows: list[dict[str, str]], inventory: list[dict[str, object]], windows: list[str]) -> list[dict[str, object]]:
    output = []
    for ridx, inv in enumerate(inventory):
        if inv["sample_adequacy"] == "MISSING_REGIME_LABEL_SOURCE":
            continue
        regime = str(inv["regime_label"])
        for widx, window in enumerate(windows):
            r_rows = rows_for_regime(rows, regime, window)
            groups = {date: sorted(day_rows, key=lambda row: parse_float(row.get("_rank")) or 10**12) for date, day_rows in group_by_date(r_rows).items()}
            for bidx, bucket in enumerate(["TOP_10", "TOP_20", "TOP_QUINTILE"]):
                actual = bucket_values(r_rows, window, bucket)
                seed = RANDOM_SEED_BASE + ridx * 1000 + widx * 10 + bidx
                if len(actual) < MIN_BUCKET_N:
                    output.append({"regime_label": regime, "forward_return_window": window, "rank_bucket": bucket, "actual_mean_return": mean(actual) if actual else None, "random_mean_return": None, "actual_percentile_vs_random": None, "probability_actual_outperforms_random": None, "random_trial_count": RANDOM_TRIALS, "deterministic_seed": seed, "sample_adequacy": "INSUFFICIENT_SAMPLE", "research_only": "TRUE"})
                    continue
                rng = random.Random(seed)
                trial_means = []
                for _ in range(RANDOM_TRIALS):
                    vals = []
                    for ordered in groups.values():
                        k = len(bucket_from_ordered(ordered, bucket))
                        for row in rng.sample(ordered, min(k, len(ordered))):
                            ret = forward_return(row, window)
                            if ret is not None:
                                vals.append(ret)
                    if vals:
                        trial_means.append(mean(vals))
                actual_mean = mean(actual)
                pct = sum(1 for value in trial_means if actual_mean > value) / len(trial_means) if trial_means else None
                output.append(
                    {
                        "regime_label": regime,
                        "forward_return_window": window,
                        "rank_bucket": bucket,
                        "actual_mean_return": actual_mean,
                        "random_mean_return": mean(trial_means) if trial_means else None,
                        "actual_percentile_vs_random": pct,
                        "probability_actual_outperforms_random": pct,
                        "random_trial_count": len(trial_means) if trial_means else RANDOM_TRIALS,
                        "deterministic_seed": seed,
                        "sample_adequacy": "SUFFICIENT" if trial_means else "INSUFFICIENT_SAMPLE",
                        "research_only": "TRUE",
                    }
                )
    return output


def build_benchmark(rows: list[dict[str, str]], inventory: list[dict[str, object]], windows: list[str]) -> list[dict[str, object]]:
    output = []
    for inv in inventory:
        if inv["sample_adequacy"] == "MISSING_REGIME_LABEL_SOURCE":
            continue
        regime = str(inv["regime_label"])
        for window in windows:
            r_rows = rows_for_regime(rows, regime, window)
            universe = [ret for ret in (forward_return(row, window) for row in r_rows) if ret is not None]
            universe_mean = mean(universe) if universe else 0.0
            for bucket in ["TOP_10", "TOP_20", "TOP_QUINTILE"]:
                selected = []
                for day_rows in group_by_date(r_rows).values():
                    ordered = sorted(day_rows, key=lambda row: parse_float(row.get("_rank")) or 10**12)
                    selected.extend(bucket_from_ordered(ordered, bucket))
                bucket_rets = [ret for ret in (forward_return(row, window) for row in selected) if ret is not None]
                for target in ["EQUAL_WEIGHT_UNIVERSE", "SPY", "QQQ", "SECTOR_ETF"]:
                    if target == "EQUAL_WEIGHT_UNIVERSE":
                        excess = [value - universe_mean for value in bucket_rets]
                    elif target == "SECTOR_ETF":
                        excess = []
                    else:
                        excess = [value for value in (benchmark_excess(row, target, window) for row in selected) if value is not None]
                    t_stat, p_value = t_p(excess)
                    ci_low, ci_high = bootstrap_ci(excess, RANDOM_SEED_BASE + len(output), 50)
                    if not excess:
                        classification = "BENCHMARK_UNAVAILABLE"
                    elif mean(excess) > 0 and ci_low is not None and ci_low > 0:
                        classification = "ROBUST_EXCESS_IN_REGIME"
                    elif mean(excess) > 0:
                        classification = "WEAK_EXCESS_IN_REGIME"
                    elif mean(excess) < 0:
                        classification = "NEGATIVE_EXCESS_IN_REGIME"
                    else:
                        classification = "MIXED_EXCESS_IN_REGIME"
                    output.append(
                        {
                            "regime_label": regime,
                            "forward_return_window": window,
                            "rank_bucket": bucket,
                            "comparison_target": target,
                            "observation_count": len(excess),
                            "mean_excess_return": mean(excess) if excess else None,
                            "excess_hit_rate": sum(1 for value in excess if value > 0) / len(excess) if excess else None,
                            "t_stat": t_stat,
                            "p_value": p_value,
                            "bootstrap_ci_low": ci_low,
                            "bootstrap_ci_high": ci_high,
                            "benchmark_classification": classification,
                            "research_only": "TRUE",
                        }
                    )
    return output


def build_transition(rows: list[dict[str, str]], windows: list[str]) -> list[dict[str, object]]:
    by_date = group_by_date(rows)
    dates = sorted(by_date)
    date_primary = {}
    for date, day_rows in by_date.items():
        labels = Counter(label for row in day_rows for label in row.get("_regime_labels", "").split("|") if label)
        date_primary[date] = labels.most_common(1)[0][0] if labels else ""
    transition_dates = set()
    for idx, date in enumerate(dates):
        prev_label = date_primary.get(dates[idx - 1], "") if idx > 0 else date_primary.get(date, "")
        next_label = date_primary.get(dates[idx + 1], "") if idx + 1 < len(dates) else date_primary.get(date, "")
        if date_primary.get(date, "") not in {prev_label, next_label}:
            transition_dates.add(date)
    output = []
    for label in REGIME_LABELS:
        label_rows = rows_for_regime(rows, label)
        if not label_rows:
            output.append({"regime_label": label, "conflict_observation_count": 0, "transition_risk_observation_count": 0, "comparison_window": "|".join(windows), "with_transition_mean_return": None, "without_transition_mean_return": None, "transition_diagnostic": "MISSING_REGIME_LABEL_SOURCE", "research_only": "TRUE"})
            continue
        conflicts = [row for row in label_rows if len([x for x in row.get("_regime_labels", "").split("|") if x]) > 1]
        trans = [row for row in label_rows if row.get("_as_of_date", "") in transition_dates]
        vals_all, vals_clean = [], []
        for row in label_rows:
            for window in windows:
                ret = forward_return(row, window)
                if ret is not None:
                    vals_all.append(ret)
                    if row.get("_as_of_date", "") not in transition_dates:
                        vals_clean.append(ret)
        output.append(
            {
                "regime_label": label,
                "conflict_observation_count": len(conflicts),
                "transition_risk_observation_count": len(trans),
                "comparison_window": "|".join(windows),
                "with_transition_mean_return": mean(vals_all) if vals_all else None,
                "without_transition_mean_return": mean(vals_clean) if vals_clean else None,
                "transition_diagnostic": "TRANSITION_RISK_PRESENT" if trans else "NO_TRANSITION_RISK_DETECTED",
                "research_only": "TRUE",
            }
        )
    return output


def build_risk_behavior(inventory: list[dict[str, object]], risk_006: list[dict[str, str]]) -> list[dict[str, object]]:
    overall = Counter(row.get("risk_overheat_logic_classification", "") for row in risk_006)
    base_classification = "INCONCLUSIVE"
    if overall.get("OVERLY_RESTRICTIVE", 0):
        base_classification = "OVERLY_RESTRICTIVE"
    elif overall.get("PROTECTIVE", 0):
        base_classification = "PROTECTIVE"
    elif overall.get("MIXED", 0):
        base_classification = "MIXED"
    output = []
    for inv in inventory:
        regime = str(inv["regime_label"])
        output.append(
            {
                "regime_label": regime,
                "blocked_high_rank_mean_return": None,
                "nonblocked_high_rank_mean_return": None,
                "overheat_positive_mean_return": None,
                "not_overheat_mean_return": None,
                "false_block_candidate_rate": None,
                "risk_overheat_behavior_classification": "INCONCLUSIVE" if inv["sample_adequacy"] == "MISSING_REGIME_LABEL_SOURCE" else base_classification,
                "official_risk_gate_loosening_allowed": "FALSE",
                "research_only": "TRUE",
            }
        )
    return output


def choose_decision(inventory: list[dict[str, object]], rank_rows: list[dict[str, object]], random_rows: list[dict[str, object]], outlier_007: dict[str, str], risk_rows: list[dict[str, object]]) -> tuple[str, str, str]:
    available = [row for row in inventory if row["sample_adequacy"] != "MISSING_REGIME_LABEL_SOURCE"]
    sufficient = [row for row in inventory if row["sample_adequacy"] == "SUFFICIENT"]
    outlier_high = outlier_007.get("outlier_dependency_classification") == "HIGH"
    poor_mono = any((parse_float(row.get("monotonicity_score")) or 0.0) < 0.75 for row in rank_rows if row.get("sample_adequacy") == "SUFFICIENT")
    strong_random = any((parse_float(row.get("actual_percentile_vs_random")) or 0.0) >= 0.70 for row in random_rows)
    risk_issue = any(row.get("risk_overheat_behavior_classification") in {"OVERLY_RESTRICTIVE", "MIXED"} and row.get("false_block_candidate_rate") for row in risk_rows)
    if not available or len(sufficient) < 2:
        decision = "REGIME_LABELS_INSUFFICIENT_FOR_SEGMENTATION"
        status = "PARTIAL_PASS_V21_008_REGIME_LABELS_INSUFFICIENT_FOR_SEGMENTATION"
        next_stage = "V21.012_SECTOR_NEUTRAL_AND_THEME_CONCENTRATION_AUDIT"
    elif outlier_high:
        decision = "REGIME_SEGMENTATION_REVEALS_OUTLIER_NEUTRALIZATION_REQUIRED"
        status = "PASS_V21_008_REGIME_SEGMENTATION_REVEALS_OUTLIER_NEUTRALIZATION_REQUIRED"
        next_stage = "V21.009_OUTLIER_NEUTRALIZED_FACTOR_BACKTEST"
    elif risk_issue:
        decision = "REGIME_SEGMENTATION_REVEALS_ARCHITECTURE_REPAIR_REQUIRED"
        status = "PASS_V21_008_REGIME_SEGMENTATION_REVEALS_ARCHITECTURE_REPAIR_REQUIRED"
        next_stage = "V21.010_RISK_OVERHEAT_FALSE_BLOCK_REPAIR"
    elif poor_mono:
        decision = "REGIME_SEGMENTATION_REVEALS_ARCHITECTURE_REPAIR_REQUIRED"
        status = "PASS_V21_008_REGIME_SEGMENTATION_REVEALS_ARCHITECTURE_REPAIR_REQUIRED"
        next_stage = "V21.011_FACTOR_FAMILY_RESCALING_AND_NONLINEAR_INTERACTION_TEST"
    elif strong_random:
        decision = "REGIME_SEGMENTED_SIGNAL_CONFIRMED_RESEARCH_ONLY"
        status = "PASS_V21_008_REGIME_SEGMENTED_SIGNAL_CONFIRMED_RESEARCH_ONLY"
        next_stage = "V21.013_REGIME_AWARE_SHADOW_SCORING_EXPERIMENT_PLAN"
    else:
        decision = "REGIME_SEGMENTED_SIGNAL_WEAK_OR_MIXED"
        status = "PARTIAL_PASS_V21_008_REGIME_SEGMENTED_SIGNAL_WEAK_OR_MIXED"
        next_stage = "V21.011_FACTOR_FAMILY_RESCALING_AND_NONLINEAR_INTERACTION_TEST"
    return decision, status, next_stage


def write_report(summary: dict[str, object]) -> None:
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    text = f"""# V21.008 Regime Segmented Factor Backtest Report

## Executive summary
This research-only stage evaluated factor behavior by available regime labels after V21.007 blocked weight updates for regime segmentation. Missing regime labels were not fabricated.

## Final regime segmentation decision
{summary['regime_segmentation_decision']}

Final status: {summary['final_status']}

## V21.007 blocker ingestion
V21.007 blocker decision was ingested as {summary['v21_007_weight_update_blocker_decision']}. Official weight updates and limited weight experiments remain disallowed.

## Regime label inventory and sample adequacy
Available labels, observation counts, as_of_date counts, ticker counts, and adequacy flags are written to V21_008_REGIME_LABEL_INVENTORY.csv.

## Regime-segmented rank bucket performance
Top bucket, middle bucket, bottom bucket, spread, and monotonicity statistics are written to V21_008_REGIME_RANK_BUCKET_PERFORMANCE.csv.

## Regime-segmented factor family IC
Family IC diagnostics are written to V21_008_REGIME_FACTOR_FAMILY_IC_STATS.csv. DATA_TRUST remains audit-only.

## Regime-specific random baseline comparison
Deterministic random baselines used seed base {RANDOM_SEED_BASE} and {RANDOM_TRIALS} trials where sample size permitted.

## Regime-specific benchmark comparison
Benchmark excess diagnostics are written to V21_008_REGIME_BENCHMARK_COMPARISON.csv. Missing sector ETF data is marked unavailable.

## Regime transition and conflict audit
Transition and multi-label conflict diagnostics are written to V21_008_REGIME_TRANSITION_CONFLICT_AUDIT.csv.

## Risk and overheat behavior by regime
Risk and overheat behavior is written to V21_008_REGIME_RISK_OVERHEAT_BEHAVIOR.csv. Official risk gates must not be loosened.

## DATA_TRUST zero-alpha confirmation
DATA_TRUST ranking contribution is 0 and alpha contribution is 0. DATA_TRUST is gate/audit metadata only.

## Explicit blocked actions
No official ranking mutation. No official factor weight mutation. No official recommendation. No trade action. No shadow activation. No production readiness, real-book readiness, official activation, or official weight update readiness claim.

## What this stage proves
It shows whether currently available regime labels materially change research-only factor diagnostics.

## What this stage still cannot prove
It cannot prove live tradability, production readiness, real-book readiness, official activation, execution viability, or permission to update weights.

## Recommended next stage
{summary['recommended_next_stage']}
"""
    REPORT.write_text(text, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    missing = [path.relative_to(ROOT).as_posix() for path in V21_007_INPUTS if not path.exists() or path.stat().st_size == 0]
    summary_007 = first(read_csv(OUT_DIR / "V21_007_FACTOR_ARCHITECTURE_REPAIR_PLAN_SUMMARY.csv"))
    blocker_007 = first(read_csv(OUT_DIR / "V21_007_WEIGHT_UPDATE_BLOCKER_DECISION.csv"))
    outlier_007 = first(read_csv(OUT_DIR / "V21_007_OUTLIER_DEPENDENCY_DIAGNOSIS.csv"))
    selection_rows = read_csv(OBS_SELECTION)
    primary_rows = load_primary_rows(selection_rows)
    attach_regimes(primary_rows)
    windows = detect_windows(primary_rows)

    blocker_audit = build_blocker_audit(summary_007, blocker_007, missing)
    inventory = build_inventory(primary_rows, windows)
    rank_rows = build_rank_perf(primary_rows, inventory, windows)
    ic_rows = build_ic(primary_rows, inventory, windows)
    random_rows = build_random(primary_rows, inventory, windows)
    benchmark_rows = build_benchmark(primary_rows, inventory, windows)
    transition_rows = build_transition(primary_rows, windows)
    risk_rows = build_risk_behavior(inventory, read_csv(OUT_DIR / "V21_006_RISK_OVERHEAT_ROBUSTNESS_TEST.csv"))
    decision, final_status, next_stage = choose_decision(inventory, rank_rows, random_rows, outlier_007, risk_rows)
    if missing:
        final_status = "FAIL_V21_008_REQUIRED_V21_007_ARTIFACTS_MISSING"
    if next_stage not in NEXT_STAGES:
        next_stage = "V21.011_FACTOR_FAMILY_RESCALING_AND_NONLINEAR_INTERACTION_TEST"

    decision_rows = [
        {
            "regime_segmentation_decision": decision,
            "final_status": final_status,
            "weight_update_blocked": "TRUE",
            "official_use_allowed": "FALSE",
            "recommended_next_stage": next_stage,
            "selected_recommended_next_stage": "TRUE",
            "research_only": "TRUE",
        }
    ]
    summary = {
        "stage_name": STAGE_NAME,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "research_only": "TRUE",
        "final_status": final_status,
        "regime_segmentation_decision": decision,
        "v21_007_weight_update_blocker_decision": summary_007.get("weight_update_blocker_decision", ""),
        "official_weight_update_allowed": "FALSE",
        "research_only_limited_weight_experiment_allowed": "FALSE",
        "recommended_next_stage": next_stage,
        "inventoried_regime_label_count": sum(1 for row in inventory if row["sample_adequacy"] != "MISSING_REGIME_LABEL_SOURCE"),
        "random_seed_base": RANDOM_SEED_BASE,
        "random_trial_count": RANDOM_TRIALS,
        "data_trust_ranking_weight": "0",
        "data_trust_alpha_contribution": "0",
        "official_ranking_mutation_count": "0",
        "official_factor_weight_mutation_count": "0",
        "official_recommendation_count": "0",
        "trade_action_count": "0",
        "shadow_activation": "FALSE",
    }

    write_csv(BLOCKER_AUDIT, blocker_audit, ["audit_item", "audit_passed", "observed_value", "required_value", "research_only"])
    write_csv(LABEL_INVENTORY, inventory, ["regime_label", "observation_count", "distinct_as_of_dates", "distinct_tickers", "evaluated_forward_window_count", "evaluated_forward_windows", "sample_adequacy", "research_only"])
    write_csv(RANK_PERF, rank_rows, ["regime_label", "forward_return_window", "rank_bucket", "observation_count", "mean_forward_return", "median_forward_return", "hit_rate", "standard_deviation", "top_minus_bottom_spread", "top_minus_universe_spread", "monotonicity_score", "monotonicity_violation_count", "sample_adequacy", "research_only"])
    write_csv(IC_STATS, ic_rows, ["regime_label", "factor_family", "forward_return_window", "as_of_group_count", "pearson_ic_mean", "spearman_rank_ic_mean", "mean_ic", "median_ic", "ic_volatility", "ic_ir", "positive_ic_rate", "t_stat", "p_value", "family_regime_classification", "data_trust_alpha_contribution", "research_only"])
    write_csv(RANDOM_BASELINE, random_rows, ["regime_label", "forward_return_window", "rank_bucket", "actual_mean_return", "random_mean_return", "actual_percentile_vs_random", "probability_actual_outperforms_random", "random_trial_count", "deterministic_seed", "sample_adequacy", "research_only"])
    write_csv(BENCHMARK, benchmark_rows, ["regime_label", "forward_return_window", "rank_bucket", "comparison_target", "observation_count", "mean_excess_return", "excess_hit_rate", "t_stat", "p_value", "bootstrap_ci_low", "bootstrap_ci_high", "benchmark_classification", "research_only"])
    write_csv(TRANSITION_AUDIT, transition_rows, ["regime_label", "conflict_observation_count", "transition_risk_observation_count", "comparison_window", "with_transition_mean_return", "without_transition_mean_return", "transition_diagnostic", "research_only"])
    write_csv(RISK_BEHAVIOR, risk_rows, ["regime_label", "blocked_high_rank_mean_return", "nonblocked_high_rank_mean_return", "overheat_positive_mean_return", "not_overheat_mean_return", "false_block_candidate_rate", "risk_overheat_behavior_classification", "official_risk_gate_loosening_allowed", "research_only"])
    write_csv(DECISION, decision_rows, ["regime_segmentation_decision", "final_status", "weight_update_blocked", "official_use_allowed", "recommended_next_stage", "selected_recommended_next_stage", "research_only"])
    write_csv(SUMMARY, [summary], list(summary.keys()))
    write_report(summary)

    print(f"STAGE_NAME={STAGE_NAME}")
    print(f"final_status={final_status}")
    print(f"regime_segmentation_decision={decision}")
    print(f"recommended_next_stage={next_stage}")
    print("official_weight_update_allowed=FALSE")
    print("research_only_limited_weight_experiment_allowed=FALSE")
    print("data_trust_ranking_weight=0")
    print("data_trust_alpha_contribution=0")
    print("official_ranking_mutation_count=0")
    print("official_factor_weight_mutation_count=0")
    print("official_recommendation_count=0")
    print("trade_action_count=0")
    print("shadow_activation=FALSE")
    print("research_only=TRUE")


if __name__ == "__main__":
    main()
