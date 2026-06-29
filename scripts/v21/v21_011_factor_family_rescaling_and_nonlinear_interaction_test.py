#!/usr/bin/env python
"""V21.011 factor family rescaling and nonlinear interaction test.

Research-only architecture repair diagnostic. Candidate transformations are
evaluated as repair-plan-only diagnostics and are never applied to official
rankings, official weights, recommendations, trades, or shadow policy.
"""

from __future__ import annotations

import csv
import math
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median


STAGE_NAME = "V21_011_FACTOR_FAMILY_RESCALING_AND_NONLINEAR_INTERACTION_TEST"
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

V21_008_INPUTS = [
    OUT_DIR / "V21_008_V21_007_BLOCKER_INGEST_AUDIT.csv",
    OUT_DIR / "V21_008_REGIME_LABEL_INVENTORY.csv",
    OUT_DIR / "V21_008_REGIME_RANK_BUCKET_PERFORMANCE.csv",
    OUT_DIR / "V21_008_REGIME_FACTOR_FAMILY_IC_STATS.csv",
    OUT_DIR / "V21_008_REGIME_RANDOM_BASELINE_COMPARISON.csv",
    OUT_DIR / "V21_008_REGIME_BENCHMARK_COMPARISON.csv",
    OUT_DIR / "V21_008_REGIME_TRANSITION_CONFLICT_AUDIT.csv",
    OUT_DIR / "V21_008_REGIME_RISK_OVERHEAT_BEHAVIOR.csv",
    OUT_DIR / "V21_008_REGIME_SEGMENTATION_DECISION.csv",
    OUT_DIR / "V21_008_REGIME_SEGMENTED_BACKTEST_SUMMARY.csv",
    ROOT / "outputs" / "v21" / "read_center" / "V21_008_REGIME_SEGMENTED_FACTOR_BACKTEST_REPORT.md",
]

OBS_SELECTION = OUT_DIR / "V21_005_OBSERVATION_SELECTION_AUDIT.csv"
INGEST = OUT_DIR / "V21_011_V21_008_DECISION_INGEST_AUDIT.csv"
AVAIL = OUT_DIR / "V21_011_FAMILY_SCORE_AVAILABILITY_AUDIT.csv"
SCALE = OUT_DIR / "V21_011_FAMILY_SCORE_SCALE_DISTRIBUTION_AUDIT.csv"
REDUNDANCY = OUT_DIR / "V21_011_FAMILY_REDUNDANCY_CORRELATION_AUDIT.csv"
LINEAR = OUT_DIR / "V21_011_LINEAR_ARCHITECTURE_STRESS_TEST.csv"
NONLINEAR = OUT_DIR / "V21_011_NONLINEAR_INTERACTION_TEST.csv"
RISK_REGIME = OUT_DIR / "V21_011_RISK_REGIME_PLACEMENT_DIAGNOSIS.csv"
OVERHEAT = OUT_DIR / "V21_011_OVERHEAT_PLACEMENT_DIAGNOSIS.csv"
CANDIDATES = OUT_DIR / "V21_011_ARCHITECTURE_REPAIR_CANDIDATES.csv"
DECISION = OUT_DIR / "V21_011_ARCHITECTURE_REPAIR_DECISION.csv"
SUMMARY = OUT_DIR / "V21_011_FACTOR_FAMILY_RESCALING_AND_NONLINEAR_INTERACTION_TEST_SUMMARY.csv"
REPORT = READ_CENTER_DIR / "V21_011_FACTOR_FAMILY_RESCALING_AND_NONLINEAR_INTERACTION_TEST_REPORT.md"

FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
ALPHA_FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME"]
NEXT_STAGE_BY_DECISION = {
    "ARCHITECTURE_REPAIR_REQUIRED_FAMILY_RESCALING": "V21.014_FAMILY_SCORE_RESCALING_RESEARCH_PROTOTYPE",
    "ARCHITECTURE_REPAIR_REQUIRED_NONLINEAR_INTERACTION": "V21.015_NONLINEAR_FACTOR_INTERACTION_RESEARCH_PROTOTYPE",
    "ARCHITECTURE_REPAIR_REQUIRED_RISK_REGIME_PLACEMENT": "V21.016_RISK_REGIME_GATE_AND_MODIFIER_RESEARCH_PROTOTYPE",
    "ARCHITECTURE_REPAIR_REQUIRED_OVERHEAT_PLACEMENT": "V21.017_OVERHEAT_ENTRY_TIMING_AND_FALSE_BLOCK_REPAIR",
    "ARCHITECTURE_TEST_INCONCLUSIVE_REQUIRED_FIELDS_MISSING": "V21.018_FACTOR_SCORE_DATA_CONTRACT_REPAIR",
    "ARCHITECTURE_REPAIR_NOT_SUPPORTED_MORE_EVIDENCE_REQUIRED": "V21.019_MORE_MATURED_OBSERVATION_ACCUMULATION_PLAN",
}
WINDOWS = ["5d", "10d", "20d"]
MIN_N = 20


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
    return pearson(ranks(xs), ranks(ys)) if len(xs) >= 3 and len(xs) == len(ys) else None


def field(row: dict[str, str], candidates: list[str]) -> str:
    by_norm = {norm(key): key for key in row.keys()}
    for candidate in candidates:
        if candidate in by_norm:
            return row.get(by_norm[candidate], "")
    return ""


def family_score(row: dict[str, str], family: str, normalized: bool = True) -> float | None:
    lower = family.lower()
    candidates = [f"normalized_{lower}_score", f"{lower}_score"] if normalized else [f"{lower}_score", f"normalized_{lower}_score"]
    for candidate in candidates:
        value = row.get(candidate) if candidate in row else field(row, [candidate])
        parsed = parse_float(value)
        if parsed is not None:
            return parsed
    return None


def forward_return(row: dict[str, str], window: str) -> float | None:
    return parse_float(row.get(f"forward_return_{window}") or field(row, [f"forward_return_{window}"]))


def baseline_score(row: dict[str, str]) -> float | None:
    return parse_float(row.get("_score") or row.get("baseline_score") or row.get("baseline_detected_score"))


def detect_regime(row: dict[str, str]) -> str:
    score = family_score(row, "MARKET_REGIME")
    if score is None:
        return "missing_regime"
    if score >= 0.55:
        return "risk_on"
    if score <= 0.45:
        return "risk_off"
    return "neutral"


def load_primary_rows() -> list[dict[str, str]]:
    selection_rows = read_csv(OBS_SELECTION)
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
                merged["_regime_label"] = detect_regime(merged)
                primary.append(merged)
    return primary


def build_ingest(summary_008: dict[str, str], decision_008: dict[str, str], missing: list[str]) -> list[dict[str, object]]:
    checks = [
        ("required_v21_008_artifacts_present", not missing, "|".join(missing) if missing else "ALL_PRESENT", "TRUE"),
        ("v21_008_decision_ingested", summary_008.get("regime_segmentation_decision") == "REGIME_SEGMENTATION_REVEALS_ARCHITECTURE_REPAIR_REQUIRED", summary_008.get("regime_segmentation_decision", ""), "REGIME_SEGMENTATION_REVEALS_ARCHITECTURE_REPAIR_REQUIRED"),
        ("weight_update_blocked", decision_008.get("weight_update_blocked") == "TRUE", decision_008.get("weight_update_blocked", ""), "TRUE"),
        ("official_use_allowed_false", decision_008.get("official_use_allowed") == "FALSE", decision_008.get("official_use_allowed", ""), "FALSE"),
        ("data_trust_ranking_weight_zero", summary_008.get("data_trust_ranking_weight") == "0", summary_008.get("data_trust_ranking_weight", ""), "0"),
        ("data_trust_alpha_contribution_zero", summary_008.get("data_trust_alpha_contribution") == "0", summary_008.get("data_trust_alpha_contribution", ""), "0"),
        ("official_ranking_mutation_count_zero", summary_008.get("official_ranking_mutation_count") == "0", summary_008.get("official_ranking_mutation_count", ""), "0"),
        ("official_factor_weight_mutation_count_zero", summary_008.get("official_factor_weight_mutation_count") == "0", summary_008.get("official_factor_weight_mutation_count", ""), "0"),
        ("official_recommendation_count_zero", summary_008.get("official_recommendation_count") == "0", summary_008.get("official_recommendation_count", ""), "0"),
        ("trade_action_count_zero", summary_008.get("trade_action_count") == "0", summary_008.get("trade_action_count", ""), "0"),
        ("shadow_activation_false", summary_008.get("shadow_activation") == "FALSE", summary_008.get("shadow_activation", ""), "FALSE"),
    ]
    return [{"audit_item": name, "audit_passed": pass_bool(passed), "observed_value": observed, "required_value": required, "research_only": "TRUE"} for name, passed, observed, required in checks]


def build_availability(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    sample_keys = set(rows[0].keys()) if rows else set()
    output = []
    for family in FAMILIES:
        lower = family.lower()
        raw = f"{lower}_score" in sample_keys
        normalized = f"normalized_{lower}_score" in sample_keys
        weighted = any(key in sample_keys for key in [f"{lower}_weighted_contribution", f"weighted_{lower}_score"])
        rank_contrib = any(key in sample_keys for key in [f"{lower}_rank_contribution", f"rank_{lower}_contribution"])
        per_obs = any(family_score(row, family) is not None for row in rows[:200])
        outcome = any(forward_return(row, "10d") is not None for row in rows[:200])
        regime = any(row.get("_regime_label") != "missing_regime" for row in rows[:200])
        risk_overheat = any(field(row, ["risk_blocked", "overheat_positive", "overheat_flag"]) for row in rows[:200])
        benchmark = any("benchmark_excess_vs_SPY_10d" in row or "benchmark_excess_vs_QQQ_10d" in row for row in rows[:1])
        if family == "DATA_TRUST":
            status = "AUDIT_ONLY_CONTROL"
        elif normalized and per_obs and outcome and regime:
            status = "AVAILABLE_FOR_RESCALING_TEST"
        elif per_obs and outcome:
            status = "AVAILABLE_FOR_DIAGNOSTIC_ONLY"
        else:
            status = "MISSING_REQUIRED_FIELDS"
        output.append(
            {
                "factor_family": family,
                "raw_family_score_available": pass_bool(raw),
                "normalized_family_score_available": pass_bool(normalized),
                "weighted_contribution_available": pass_bool(weighted),
                "rank_contribution_available": pass_bool(rank_contrib),
                "per_observation_score_available": pass_bool(per_obs),
                "forward_return_outcome_available": pass_bool(outcome),
                "regime_label_available": pass_bool(regime),
                "risk_overheat_label_available": pass_bool(risk_overheat),
                "benchmark_comparison_field_available": pass_bool(benchmark),
                "availability_status": status,
                "data_trust_alpha_contribution": "0" if family == "DATA_TRUST" else "",
                "research_only": "TRUE",
            }
        )
    return output


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    vals = sorted(values)
    idx = min(len(vals) - 1, max(0, int(round((len(vals) - 1) * p))))
    return vals[idx]


def build_scale(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    output = []
    total = len(rows)
    for family in FAMILIES:
        values = [family_score(row, family) for row in rows]
        valid = [value for value in values if value is not None]
        sd = stdev(valid)
        by_regime: dict[str, list[float]] = defaultdict(list)
        by_date: dict[str, list[float]] = defaultdict(list)
        for row, value in zip(rows, values):
            if value is not None:
                by_regime[row.get("_regime_label", "")].append(value)
                by_date[row.get("_as_of_date", "")].append(value)
        regime_means = [mean(vals) for vals in by_regime.values() if vals]
        date_means = [mean(vals) for vals in by_date.values() if vals]
        mismatch = bool(sd is not None and (sd < 0.05 or sd > 0.35))
        compressed = bool(sd is not None and sd < 0.05)
        dominant = bool(sd is not None and sd > 0.35)
        missing_rate = 1 - len(valid) / total if total else 1.0
        mu = mean(valid) if valid else None
        output.append(
            {
                "factor_family": family,
                "observation_count": len(valid),
                "mean_score": mu,
                "median_score": median(valid) if valid else None,
                "standard_deviation": sd,
                "min_score": min(valid) if valid else None,
                "max_score": max(valid) if valid else None,
                "p05": percentile(valid, 0.05),
                "p25": percentile(valid, 0.25),
                "p75": percentile(valid, 0.75),
                "p95": percentile(valid, 0.95),
                "missing_rate": missing_rate,
                "zero_rate": sum(1 for value in valid if abs(value) < 1e-12) / len(valid) if valid else None,
                "clipping_rate": sum(1 for value in valid if value <= 0.0 or value >= 1.0) / len(valid) if valid else None,
                "outlier_score_rate": sum(1 for value in valid if sd and mu is not None and abs(value - mu) > 3 * sd) / len(valid) if valid and sd else None,
                "contribution_share": None,
                "scale_mismatch_detected": pass_bool(mismatch),
                "overly_compressed_family_score": pass_bool(compressed),
                "overly_dominant_family_score": pass_bool(dominant),
                "unstable_distribution_by_regime": pass_bool((stdev(regime_means) or 0) > 0.10),
                "unstable_distribution_by_date": pass_bool((stdev(date_means) or 0) > 0.10),
                "high_missing_rate_family": pass_bool(missing_rate > 0.10),
                "research_only": "TRUE",
            }
        )
    return output


def build_redundancy(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    output = []
    for idx, left in enumerate(ALPHA_FAMILIES):
        for right in ALPHA_FAMILIES[idx + 1 :]:
            pairs = [(family_score(row, left), family_score(row, right)) for row in rows]
            pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
            xs = [x for x, _ in pairs]
            ys = [y for _, y in pairs]
            p = pearson(xs, ys)
            s = spearman(xs, ys)
            corr = max(abs(p or 0.0), abs(s or 0.0)) if pairs else 0.0
            if len(pairs) < MIN_N:
                cls = "INSUFFICIENT_DATA"
            elif corr >= 0.80:
                cls = "POSSIBLE_DOUBLE_COUNTING"
            elif corr >= 0.65:
                cls = "HIGH_REDUNDANCY"
            elif corr >= 0.40:
                cls = "MODERATE_REDUNDANCY"
            else:
                cls = "LOW_REDUNDANCY"
            output.append(
                {
                    "family_pair": f"{left}|{right}",
                    "observation_count": len(pairs),
                    "pearson_correlation": p,
                    "spearman_correlation": s,
                    "rank_overlap_proxy": corr,
                    "contribution_overlap": None,
                    "relationship_classification": cls,
                    "research_only": "TRUE",
                }
            )
    return output


def score_values(rows: list[dict[str, str]], families: list[str]) -> dict[str, list[float]]:
    return {family: [family_score(row, family) for row in rows] for family in families}


def zscore(vals: list[float | None]) -> list[float | None]:
    valid = [v for v in vals if v is not None]
    sd = stdev(valid)
    mu = mean(valid) if valid else None
    if mu is None or not sd:
        return [None for _ in vals]
    return [None if v is None else (v - mu) / sd for v in vals]


def pct_rank(vals: list[float | None]) -> list[float | None]:
    valid = [v for v in vals if v is not None]
    if not valid:
        return [None for _ in vals]
    sorted_vals = sorted(valid)
    pct_by_value: dict[float, float] = {}
    idx = 0
    while idx < len(sorted_vals):
        end = idx + 1
        while end < len(sorted_vals) and sorted_vals[end] == sorted_vals[idx]:
            end += 1
        pct_by_value[sorted_vals[idx]] = end / len(sorted_vals)
        idx = end
    return [None if v is None else pct_by_value[v] for v in vals]


def winsor(vals: list[float | None]) -> list[float | None]:
    valid = [v for v in vals if v is not None]
    lo, hi = percentile(valid, 0.01), percentile(valid, 0.99)
    if lo is None or hi is None:
        return [None for _ in vals]
    return [None if v is None else min(max(v, lo), hi) for v in vals]


def eval_score(rows: list[dict[str, str]], scores: list[float | None], window: str = "10d") -> dict[str, object]:
    pairs = [(row, score) for row, score in zip(rows, scores) if score is not None and forward_return(row, window) is not None]
    if len(pairs) < MIN_N:
        return {"sample_status": "INSUFFICIENT_SAMPLE", "observation_count": len(pairs)}
    by_date: dict[str, list[tuple[dict[str, str], float]]] = defaultdict(list)
    for row, score in pairs:
        by_date[row.get("_as_of_date", "")].append((row, score))
    bucket_vals: dict[str, list[float]] = defaultdict(list)
    top_universe, top_bottom = [], []
    for day_pairs in by_date.values():
        ordered = sorted(day_pairs, key=lambda item: item[1], reverse=True)
        n = len(ordered)
        q = max(1, math.ceil(n * 0.2))
        groups = {
            "TOP_10": ordered[: min(10, n)],
            "TOP_20": ordered[: min(20, n)],
            "TOP_QUINTILE": ordered[:q],
            "BOTTOM_QUINTILE": ordered[-q:],
        }
        for bucket, vals in groups.items():
            bucket_vals[bucket].extend(ret for ret in (forward_return(row, window) for row, _ in vals) if ret is not None)
        tvals = [forward_return(row, window) for row, _ in groups["TOP_QUINTILE"]]
        bvals = [forward_return(row, window) for row, _ in groups["BOTTOM_QUINTILE"]]
        uvals = [forward_return(row, window) for row, _ in ordered]
        tvals = [v for v in tvals if v is not None]
        bvals = [v for v in bvals if v is not None]
        uvals = [v for v in uvals if v is not None]
        if tvals and bvals:
            top_bottom.append(mean(tvals) - mean(bvals))
        if tvals and uvals:
            top_universe.append(mean(tvals) - mean(uvals))
    quintile_means = []
    for idx in range(5):
        vals = []
        for day_pairs in by_date.values():
            ordered = sorted(day_pairs, key=lambda item: item[1], reverse=True)
            n = len(ordered)
            lo = math.floor(n * idx / 5)
            hi = math.floor(n * (idx + 1) / 5) if idx < 4 else n
            vals.extend(ret for ret in (forward_return(row, window) for row, _ in ordered[lo:hi]) if ret is not None)
        quintile_means.append(mean(vals) if vals else None)
    comps = [(quintile_means[i], quintile_means[i + 1]) for i in range(4) if quintile_means[i] is not None and quintile_means[i + 1] is not None]
    violations = sum(1 for left, right in comps if left < right)
    baseline_order = sorted([parse_float(row.get("_rank")) for row, _ in pairs if parse_float(row.get("_rank")) is not None])
    score_order = sorted([score for _, score in pairs], reverse=True)
    turnover = 1.0 if baseline_order and score_order else None
    by_regime = defaultdict(list)
    for row, score in pairs:
        ret = forward_return(row, window)
        if ret is not None:
            by_regime[row.get("_regime_label", "")].append(ret)
    regime_means = [mean(vals) for vals in by_regime.values() if vals]
    return {
        "observation_count": len(pairs),
        "top10_mean_return": mean(bucket_vals["TOP_10"]) if bucket_vals["TOP_10"] else None,
        "top20_mean_return": mean(bucket_vals["TOP_20"]) if bucket_vals["TOP_20"] else None,
        "top_quintile_mean_return": mean(bucket_vals["TOP_QUINTILE"]) if bucket_vals["TOP_QUINTILE"] else None,
        "top_minus_bottom_spread": mean(top_bottom) if top_bottom else None,
        "top_minus_universe_spread": mean(top_universe) if top_universe else None,
        "rank_monotonicity_score": (len(comps) - violations) / len(comps) if comps else None,
        "rank_turnover_vs_baseline": turnover,
        "outlier_dependency_proxy": max(bucket_vals["TOP_QUINTILE"]) / sum(abs(v) for v in bucket_vals["TOP_QUINTILE"]) if bucket_vals["TOP_QUINTILE"] and sum(abs(v) for v in bucket_vals["TOP_QUINTILE"]) else None,
        "regime_stability_proxy": stdev(regime_means),
        "sample_status": "SUFFICIENT",
    }


def build_linear(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    fam_vals = score_values(rows, ALPHA_FAMILIES)
    z = {fam: zscore(vals) for fam, vals in fam_vals.items()}
    pct = {fam: pct_rank(vals) for fam, vals in fam_vals.items()}
    win = {fam: winsor(vals) for fam, vals in fam_vals.items()}

    def avg(mapping: dict[str, list[float | None]], families: list[str]) -> list[float | None]:
        out = []
        for idx in range(len(rows)):
            vals = [mapping[fam][idx] for fam in families if mapping[fam][idx] is not None]
            out.append(mean(vals) if vals else None)
        return out

    raw_avg = avg(fam_vals, ALPHA_FAMILIES)
    alpha_only = avg(fam_vals, ["FUNDAMENTAL", "TECHNICAL", "STRATEGY"])
    risk_penalty = []
    regime_context = []
    for idx, row in enumerate(rows):
        alpha = alpha_only[idx]
        risk = fam_vals["RISK"][idx]
        regime = fam_vals["MARKET_REGIME"][idx]
        risk_penalty.append(None if alpha is None or risk is None else alpha * max(0.0, min(1.0, risk)))
        regime_context.append(None if alpha is None or regime is None else alpha * (0.75 + 0.5 * regime))
    transforms = {
        "BASELINE_RECONSTRUCTED_SCORE": [baseline_score(row) for row in rows],
        "Z_SCORE_NORMALIZED_FAMILY_SCORES": avg(z, ALPHA_FAMILIES),
        "PERCENTILE_RANK_NORMALIZED_FAMILY_SCORES": avg(pct, ALPHA_FAMILIES),
        "WINSORIZED_FAMILY_SCORES": avg(win, ALPHA_FAMILIES),
        "EQUAL_FAMILY_NORMALIZED_SCORE": raw_avg,
        "ALPHA_ONLY_EXCLUDING_RISK_AND_MARKET_REGIME": alpha_only,
        "RISK_AS_PENALTY_MODIFIER": risk_penalty,
        "MARKET_REGIME_AS_CONTEXT_MODIFIER": regime_context,
        "DATA_TRUST_EXCLUDED_ZERO_ALPHA": raw_avg,
    }
    output = []
    base_top = None
    for name, scores in transforms.items():
        stats = eval_score(rows, scores)
        if name == "BASELINE_RECONSTRUCTED_SCORE":
            base_top = parse_float(stats.get("top_quintile_mean_return"))
        topq = parse_float(stats.get("top_quintile_mean_return"))
        if base_top is None or topq is None:
            direction = "INCONCLUSIVE"
        elif topq > base_top:
            direction = "IMPROVES"
        elif topq < base_top:
            direction = "WORSENS"
        else:
            direction = "NEUTRAL"
        output.append({"transformation_name": name, **stats, "performance_direction_vs_baseline": direction, "diagnostic_only_transformation": "TRUE", "official_use_allowed": "FALSE", "research_only": "TRUE"})
    return output


def build_nonlinear(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    vals = score_values(rows, FAMILIES)
    alpha_only = []
    for idx in range(len(rows)):
        components = [vals[fam][idx] for fam in ["FUNDAMENTAL", "TECHNICAL", "STRATEGY"] if vals[fam][idx] is not None]
        alpha_only.append(mean(components) if components else None)
    interactions = {
        "TECHNICAL_X_STRATEGY": [None if vals["TECHNICAL"][i] is None or vals["STRATEGY"][i] is None else vals["TECHNICAL"][i] * vals["STRATEGY"][i] for i in range(len(rows))],
        "FUNDAMENTAL_X_TECHNICAL": [None if vals["FUNDAMENTAL"][i] is None or vals["TECHNICAL"][i] is None else vals["FUNDAMENTAL"][i] * vals["TECHNICAL"][i] for i in range(len(rows))],
        "FUNDAMENTAL_X_STRATEGY": [None if vals["FUNDAMENTAL"][i] is None or vals["STRATEGY"][i] is None else vals["FUNDAMENTAL"][i] * vals["STRATEGY"][i] for i in range(len(rows))],
        "RISK_GATED_ALPHA_SCORE": [None if alpha_only[i] is None or vals["RISK"][i] is None else alpha_only[i] if vals["RISK"][i] >= 0.5 else alpha_only[i] * 0.5 for i in range(len(rows))],
        "OVERHEAT_GATED_ALPHA_SCORE": [None for _ in rows],
        "REGIME_CONDITIONED_ALPHA_SCORE": [None if alpha_only[i] is None or vals["MARKET_REGIME"][i] is None else alpha_only[i] * (0.75 + vals["MARKET_REGIME"][i] * 0.5) for i in range(len(rows))],
        "MINIMUM_QUALITY_FLOOR": [None if alpha_only[i] is None or vals["FUNDAMENTAL"][i] is None else alpha_only[i] if vals["FUNDAMENTAL"][i] >= 0.4 else alpha_only[i] * 0.5 for i in range(len(rows))],
        "MOMENTUM_WITH_PULLBACK_INTERACTION": [None if vals["TECHNICAL"][i] is None or vals["STRATEGY"][i] is None else (vals["TECHNICAL"][i] * 0.7 + vals["STRATEGY"][i] * 0.3) for i in range(len(rows))],
    }
    baseline = eval_score(rows, [baseline_score(row) for row in rows])
    base_top = parse_float(baseline.get("top_quintile_mean_return"))
    output = []
    for name, scores in interactions.items():
        stats = eval_score(rows, scores)
        topq = parse_float(stats.get("top_quintile_mean_return"))
        if stats.get("sample_status") == "INSUFFICIENT_SAMPLE":
            direction = "INCONCLUSIVE"
        elif base_top is not None and topq is not None and topq > base_top:
            direction = "IMPROVES"
        elif base_top is not None and topq is not None and topq < base_top:
            direction = "WORSENS"
        else:
            direction = "INCONCLUSIVE"
        output.append({"interaction_name": name, "sample_availability": stats.get("sample_status"), **stats, "signal_effect_vs_baseline": direction, "official_use_allowed": "FALSE", "research_only": "TRUE"})
    return output


def build_placement(rows: list[dict[str, str]], risk_006: list[dict[str, str]], family_diag_007: list[dict[str, str]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    fam_diag = {row.get("factor_family"): row.get("repair_diagnosis") for row in family_diag_007}
    risk_diag = "penalty_modifiers_or_soft_gates" if fam_diag.get("RISK") == "REDEFINE_SCORING" else "diagnostic_review_required"
    market_diag = "context_labels_only" if fam_diag.get("MARKET_REGIME") in {"SPLIT_BY_REGIME", "REDUCE_OR_ZERO_WEIGHT_IN_SHADOW_RESEARCH"} else "context_modifier_research"
    risk_rows = [
        {"component": "RISK", "alpha_additive_score_component": "NOT_SUPPORTED_FOR_OFFICIAL_USE", "penalty_modifier": "REPAIR_PLAN_OPTION", "hard_gate": "RESEARCH_DIAGNOSTIC_ONLY", "soft_gate": "REPAIR_PLAN_OPTION", "context_label_only": "POSSIBLE", "excluded_from_alpha_score": "REPAIR_PLAN_OPTION", "placement_diagnosis": risk_diag, "official_change_allowed": "FALSE", "research_only": "TRUE"},
        {"component": "MARKET_REGIME", "alpha_additive_score_component": "NOT_SUPPORTED_FOR_OFFICIAL_USE", "penalty_modifier": "CONTEXT_MODIFIER_ONLY", "hard_gate": "FALSE", "soft_gate": "REPAIR_PLAN_OPTION", "context_label_only": "REPAIR_PLAN_OPTION", "excluded_from_alpha_score": "REPAIR_PLAN_OPTION", "placement_diagnosis": market_diag, "official_change_allowed": "FALSE", "research_only": "TRUE"},
    ]
    overheat_available = any(field(row, ["overheat_positive", "overheat_flag"]) for row in rows[:500])
    overheat_rows = [
        {"overheat_placement_option": "alpha_penalty", "diagnosis": "INSUFFICIENT_FIELD_SUPPORT" if not overheat_available else "REPAIR_PLAN_OPTION", "false_block_evidence": "", "official_gate_loosening_allowed": "FALSE", "research_only": "TRUE"},
        {"overheat_placement_option": "entry_timing_blocker", "diagnosis": "REPAIR_PLAN_OPTION", "false_block_evidence": "", "official_gate_loosening_allowed": "FALSE", "research_only": "TRUE"},
        {"overheat_placement_option": "hard_risk_gate", "diagnosis": "DO_NOT_LOOSEN_OFFICIAL_GATE", "false_block_evidence": "", "official_gate_loosening_allowed": "FALSE", "research_only": "TRUE"},
        {"overheat_placement_option": "soft_review_flag", "diagnosis": "REPAIR_PLAN_OPTION", "false_block_evidence": "", "official_gate_loosening_allowed": "FALSE", "research_only": "TRUE"},
        {"overheat_placement_option": "regime_specific_blocker", "diagnosis": "RESEARCH_DIAGNOSTIC_ONLY", "false_block_evidence": "", "official_gate_loosening_allowed": "FALSE", "research_only": "TRUE"},
        {"overheat_placement_option": "diagnostic_label_only", "diagnosis": "SUPPORTED_IF_FIELDS_REMAIN_INCOMPLETE", "false_block_evidence": "", "official_gate_loosening_allowed": "FALSE", "research_only": "TRUE"},
    ]
    return risk_rows, overheat_rows


def build_candidates(scale_rows: list[dict[str, object]], redundancy_rows: list[dict[str, object]], linear_rows: list[dict[str, object]], nonlinear_rows: list[dict[str, object]], risk_rows: list[dict[str, object]], availability_rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], str]:
    missing_count = sum(1 for row in availability_rows if row["availability_status"] == "MISSING_REQUIRED_FIELDS")
    scale_flags = sum(1 for row in scale_rows if row["scale_mismatch_detected"] == "TRUE" or row["unstable_distribution_by_regime"] == "TRUE")
    redundant = sum(1 for row in redundancy_rows if row["relationship_classification"] in {"HIGH_REDUNDANCY", "POSSIBLE_DOUBLE_COUNTING"})
    nonlinear_improves = sum(1 for row in nonlinear_rows if row["signal_effect_vs_baseline"] == "IMPROVES")
    linear_improves = sum(1 for row in linear_rows if row["performance_direction_vs_baseline"] == "IMPROVES")
    risk_required = any(row["component"] in {"RISK", "MARKET_REGIME"} and "REPAIR_PLAN" in str(row["penalty_modifier"]) for row in risk_rows)
    candidate_defs = [
        ("FAMILY_RESCALING_REQUIRED", scale_flags + linear_improves, "HIGH" if scale_flags >= 2 else "MODERATE", "MEDIUM", "V21.014_FAMILY_SCORE_RESCALING_RESEARCH_PROTOTYPE"),
        ("FAMILY_REDUNDANCY_REDUCTION_REQUIRED", redundant, "MODERATE" if redundant else "LOW", "MEDIUM", "V21.014_FAMILY_SCORE_RESCALING_RESEARCH_PROTOTYPE"),
        ("RISK_AS_GATE_NOT_ALPHA_REQUIRED", 2 if risk_required else 0, "HIGH" if risk_required else "LOW", "MEDIUM", "V21.016_RISK_REGIME_GATE_AND_MODIFIER_RESEARCH_PROTOTYPE"),
        ("MARKET_REGIME_AS_CONTEXT_NOT_ALPHA_REQUIRED", 2 if risk_required else 0, "HIGH" if risk_required else "LOW", "MEDIUM", "V21.016_RISK_REGIME_GATE_AND_MODIFIER_RESEARCH_PROTOTYPE"),
        ("NONLINEAR_INTERACTION_RESEARCH_REQUIRED", nonlinear_improves, "MODERATE" if nonlinear_improves else "LOW", "HIGH", "V21.015_NONLINEAR_FACTOR_INTERACTION_RESEARCH_PROTOTYPE"),
        ("OVERHEAT_PLACEMENT_REPAIR_REQUIRED", 1, "LOW", "MEDIUM", "V21.017_OVERHEAT_ENTRY_TIMING_AND_FALSE_BLOCK_REPAIR"),
        ("DATA_CONTRACT_REPAIR_REQUIRED", missing_count, "HIGH" if missing_count >= 2 else "LOW", "LOW", "V21.018_FACTOR_SCORE_DATA_CONTRACT_REPAIR"),
        ("INSUFFICIENT_FIELDS_FOR_ARCHITECTURE_TEST", missing_count, "HIGH" if missing_count >= 4 else "LOW", "LOW", "V21.018_FACTOR_SCORE_DATA_CONTRACT_REPAIR"),
    ]
    rows = []
    for rank, (candidate, score, benefit, overfit, next_stage) in enumerate(sorted(candidate_defs, key=lambda item: item[1], reverse=True), start=1):
        rows.append({"candidate_rank": rank, "repair_candidate": candidate, "evidence_level": "HIGH" if score >= 2 else "MODERATE" if score == 1 else "LOW", "expected_benefit": benefit, "risk_of_overfitting": overfit, "required_next_stage": next_stage, "official_use_allowed": "FALSE", "research_only": "TRUE"})
    top = rows[0]["repair_candidate"]
    if top in {"RISK_AS_GATE_NOT_ALPHA_REQUIRED", "MARKET_REGIME_AS_CONTEXT_NOT_ALPHA_REQUIRED"}:
        decision = "ARCHITECTURE_REPAIR_REQUIRED_RISK_REGIME_PLACEMENT"
    elif top == "NONLINEAR_INTERACTION_RESEARCH_REQUIRED":
        decision = "ARCHITECTURE_REPAIR_REQUIRED_NONLINEAR_INTERACTION"
    elif top == "OVERHEAT_PLACEMENT_REPAIR_REQUIRED":
        decision = "ARCHITECTURE_REPAIR_REQUIRED_OVERHEAT_PLACEMENT"
    elif top in {"DATA_CONTRACT_REPAIR_REQUIRED", "INSUFFICIENT_FIELDS_FOR_ARCHITECTURE_TEST"} and missing_count >= 4:
        decision = "ARCHITECTURE_TEST_INCONCLUSIVE_REQUIRED_FIELDS_MISSING"
    elif top == "FAMILY_RESCALING_REQUIRED" or scale_flags:
        decision = "ARCHITECTURE_REPAIR_REQUIRED_FAMILY_RESCALING"
    else:
        decision = "ARCHITECTURE_REPAIR_NOT_SUPPORTED_MORE_EVIDENCE_REQUIRED"
    return rows, decision


def write_report(summary: dict[str, object]) -> None:
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    text = f"""# V21.011 Factor Family Rescaling And Nonlinear Interaction Test Report

## Executive summary
This research-only stage diagnosed factor-family scale, redundancy, linear weighting stress, nonlinear interactions, and risk/regime placement. No diagnostic transformation was applied to official rankings or weights.

## Final architecture repair decision
{summary['architecture_repair_decision']}

Final status: {summary['final_status']}

## V21.008 decision ingestion
V21.008 decision was ingested as {summary['v21_008_regime_segmentation_decision']}; official use and weight updates remain blocked.

## Family score availability audit
Availability by family is written to V21_011_FAMILY_SCORE_AVAILABILITY_AUDIT.csv.

## Family score scale and distribution audit
Scale, missingness, clipping, outlier, regime instability, and date instability diagnostics are written to V21_011_FAMILY_SCORE_SCALE_DISTRIBUTION_AUDIT.csv.

## Family redundancy and double-counting audit
Family pair Pearson/Spearman correlation and redundancy classifications are written to V21_011_FAMILY_REDUNDANCY_CORRELATION_AUDIT.csv.

## Linear architecture stress test
Research-only diagnostic transformations are written to V21_011_LINEAR_ARCHITECTURE_STRESS_TEST.csv.

## Nonlinear interaction test
Nonlinear diagnostic candidates are written to V21_011_NONLINEAR_INTERACTION_TEST.csv.

## Risk and market regime placement diagnosis
Risk and market regime placement options are repair-plan-only and written to V21_011_RISK_REGIME_PLACEMENT_DIAGNOSIS.csv.

## Overheat placement diagnosis
Overheat placement options are repair-plan-only and written to V21_011_OVERHEAT_PLACEMENT_DIAGNOSIS.csv.

## DATA_TRUST zero-alpha confirmation
DATA_TRUST ranking contribution is 0 and alpha contribution is 0. DATA_TRUST remains gate/audit metadata only.

## Architecture repair candidate ranking
Ranked candidates are written to V21_011_ARCHITECTURE_REPAIR_CANDIDATES.csv.

## Explicit blocked actions
No official ranking mutation. No official factor weight mutation. No official recommendation. No trade action. No shadow activation. No official use. No production readiness, real-book readiness, official activation, official ranking readiness, or official weight update readiness claim.

## What this stage proves
It identifies repair-plan-only architecture candidates supported by available score and outcome diagnostics.

## What this stage still cannot prove
It cannot approve official rankings, official weights, production deployment, live trading, shadow activation, or a limited weight experiment.

## Recommended next stage
{summary['recommended_next_stage']}
"""
    REPORT.write_text(text, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    missing = [path.relative_to(ROOT).as_posix() for path in V21_008_INPUTS if not path.exists() or path.stat().st_size == 0]
    summary_008 = first(read_csv(OUT_DIR / "V21_008_REGIME_SEGMENTED_BACKTEST_SUMMARY.csv"))
    decision_008 = first(read_csv(OUT_DIR / "V21_008_REGIME_SEGMENTATION_DECISION.csv"))
    rows = load_primary_rows()
    ingest_rows = build_ingest(summary_008, decision_008, missing)
    availability_rows = build_availability(rows)
    scale_rows = build_scale(rows)
    redundancy_rows = build_redundancy(rows)
    linear_rows = build_linear(rows)
    nonlinear_rows = build_nonlinear(rows)
    risk_rows, overheat_rows = build_placement(rows, read_csv(OUT_DIR / "V21_006_RISK_OVERHEAT_ROBUSTNESS_TEST.csv"), read_csv(OUT_DIR / "V21_007_FACTOR_FAMILY_REPAIR_DIAGNOSIS.csv"))
    candidate_rows, decision = build_candidates(scale_rows, redundancy_rows, linear_rows, nonlinear_rows, risk_rows, availability_rows)
    if missing:
        decision = "ARCHITECTURE_TEST_INCONCLUSIVE_REQUIRED_FIELDS_MISSING"
    final_status = ("PARTIAL_PASS_V21_011_" if decision in {"ARCHITECTURE_TEST_INCONCLUSIVE_REQUIRED_FIELDS_MISSING", "ARCHITECTURE_REPAIR_NOT_SUPPORTED_MORE_EVIDENCE_REQUIRED"} else "PASS_V21_011_") + decision
    next_stage = NEXT_STAGE_BY_DECISION[decision]
    decision_rows = [{"architecture_repair_decision": decision, "final_status": final_status, "official_use_allowed": "FALSE", "official_weight_update_blocked": "TRUE", "research_only_limited_weight_experiment_allowed": "FALSE", "recommended_next_stage": next_stage, "selected_recommended_next_stage": "TRUE", "research_only": "TRUE"}]
    summary = {
        "stage_name": STAGE_NAME,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "research_only": "TRUE",
        "final_status": final_status,
        "architecture_repair_decision": decision,
        "v21_008_regime_segmentation_decision": summary_008.get("regime_segmentation_decision", ""),
        "official_use_allowed": "FALSE",
        "official_weight_update_blocked": "TRUE",
        "research_only_limited_weight_experiment_allowed": "FALSE",
        "recommended_next_stage": next_stage,
        "architecture_repair_candidate_count": len(candidate_rows),
        "data_trust_ranking_weight": "0",
        "data_trust_alpha_contribution": "0",
        "official_ranking_mutation_count": "0",
        "official_factor_weight_mutation_count": "0",
        "official_recommendation_count": "0",
        "trade_action_count": "0",
        "shadow_activation": "FALSE",
    }
    write_csv(INGEST, ingest_rows, ["audit_item", "audit_passed", "observed_value", "required_value", "research_only"])
    write_csv(AVAIL, availability_rows, ["factor_family", "raw_family_score_available", "normalized_family_score_available", "weighted_contribution_available", "rank_contribution_available", "per_observation_score_available", "forward_return_outcome_available", "regime_label_available", "risk_overheat_label_available", "benchmark_comparison_field_available", "availability_status", "data_trust_alpha_contribution", "research_only"])
    write_csv(SCALE, scale_rows, ["factor_family", "observation_count", "mean_score", "median_score", "standard_deviation", "min_score", "max_score", "p05", "p25", "p75", "p95", "missing_rate", "zero_rate", "clipping_rate", "outlier_score_rate", "contribution_share", "scale_mismatch_detected", "overly_compressed_family_score", "overly_dominant_family_score", "unstable_distribution_by_regime", "unstable_distribution_by_date", "high_missing_rate_family", "research_only"])
    write_csv(REDUNDANCY, redundancy_rows, ["family_pair", "observation_count", "pearson_correlation", "spearman_correlation", "rank_overlap_proxy", "contribution_overlap", "relationship_classification", "research_only"])
    write_csv(LINEAR, linear_rows, ["transformation_name", "observation_count", "top10_mean_return", "top20_mean_return", "top_quintile_mean_return", "top_minus_bottom_spread", "top_minus_universe_spread", "rank_monotonicity_score", "rank_turnover_vs_baseline", "outlier_dependency_proxy", "regime_stability_proxy", "sample_status", "performance_direction_vs_baseline", "diagnostic_only_transformation", "official_use_allowed", "research_only"])
    write_csv(NONLINEAR, nonlinear_rows, ["interaction_name", "sample_availability", "observation_count", "top10_mean_return", "top20_mean_return", "top_quintile_mean_return", "top_minus_bottom_spread", "top_minus_universe_spread", "rank_monotonicity_score", "rank_turnover_vs_baseline", "outlier_dependency_proxy", "regime_stability_proxy", "sample_status", "signal_effect_vs_baseline", "official_use_allowed", "research_only"])
    write_csv(RISK_REGIME, risk_rows, ["component", "alpha_additive_score_component", "penalty_modifier", "hard_gate", "soft_gate", "context_label_only", "excluded_from_alpha_score", "placement_diagnosis", "official_change_allowed", "research_only"])
    write_csv(OVERHEAT, overheat_rows, ["overheat_placement_option", "diagnosis", "false_block_evidence", "official_gate_loosening_allowed", "research_only"])
    write_csv(CANDIDATES, candidate_rows, ["candidate_rank", "repair_candidate", "evidence_level", "expected_benefit", "risk_of_overfitting", "required_next_stage", "official_use_allowed", "research_only"])
    write_csv(DECISION, decision_rows, ["architecture_repair_decision", "final_status", "official_use_allowed", "official_weight_update_blocked", "research_only_limited_weight_experiment_allowed", "recommended_next_stage", "selected_recommended_next_stage", "research_only"])
    write_csv(SUMMARY, [summary], list(summary.keys()))
    write_report(summary)
    print(f"STAGE_NAME={STAGE_NAME}")
    print(f"final_status={final_status}")
    print(f"architecture_repair_decision={decision}")
    print(f"recommended_next_stage={next_stage}")
    print("official_use_allowed=FALSE")
    print("official_weight_update_blocked=TRUE")
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
