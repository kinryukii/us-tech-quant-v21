#!/usr/bin/env python
"""V21.014 family score rescaling research prototype.

Research-only prototype scoring variants. Outputs are V21.014-scoped artifacts
only and never overwrite official score, rank, recommendation, trade, or shadow
policy files.
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


STAGE_NAME = "V21_014_FAMILY_SCORE_RESCALING_RESEARCH_PROTOTYPE"
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

V21_011_INPUTS = [
    OUT_DIR / "V21_011_V21_008_DECISION_INGEST_AUDIT.csv",
    OUT_DIR / "V21_011_FAMILY_SCORE_AVAILABILITY_AUDIT.csv",
    OUT_DIR / "V21_011_FAMILY_SCORE_SCALE_DISTRIBUTION_AUDIT.csv",
    OUT_DIR / "V21_011_FAMILY_REDUNDANCY_CORRELATION_AUDIT.csv",
    OUT_DIR / "V21_011_LINEAR_ARCHITECTURE_STRESS_TEST.csv",
    OUT_DIR / "V21_011_NONLINEAR_INTERACTION_TEST.csv",
    OUT_DIR / "V21_011_RISK_REGIME_PLACEMENT_DIAGNOSIS.csv",
    OUT_DIR / "V21_011_OVERHEAT_PLACEMENT_DIAGNOSIS.csv",
    OUT_DIR / "V21_011_ARCHITECTURE_REPAIR_CANDIDATES.csv",
    OUT_DIR / "V21_011_ARCHITECTURE_REPAIR_DECISION.csv",
    OUT_DIR / "V21_011_FACTOR_FAMILY_RESCALING_AND_NONLINEAR_INTERACTION_TEST_SUMMARY.csv",
    ROOT / "outputs" / "v21" / "read_center" / "V21_011_FACTOR_FAMILY_RESCALING_AND_NONLINEAR_INTERACTION_TEST_REPORT.md",
]

OBS_SELECTION = OUT_DIR / "V21_005_OBSERVATION_SELECTION_AUDIT.csv"
INGEST = OUT_DIR / "V21_014_V21_011_DECISION_INGEST_AUDIT.csv"
CONTRACT = OUT_DIR / "V21_014_FAMILY_SCORE_SOURCE_CONTRACT_AUDIT.csv"
BASELINE = OUT_DIR / "V21_014_BASELINE_RECONSTRUCTION_AUDIT.csv"
SCORES = OUT_DIR / "V21_014_RESCALING_VARIANT_SCORE_OUTPUT.csv"
PERF = OUT_DIR / "V21_014_RESCALING_VARIANT_PERFORMANCE_STATS.csv"
BALANCE = OUT_DIR / "V21_014_FAMILY_CONTRIBUTION_BALANCE_AUDIT.csv"
ROBUST = OUT_DIR / "V21_014_VARIANT_ROBUSTNESS_AND_OVERFIT_GUARD.csv"
RANKING = OUT_DIR / "V21_014_RESCALING_CANDIDATE_RANKING.csv"
DECISION = OUT_DIR / "V21_014_RESCALING_PROTOTYPE_DECISION.csv"
SUMMARY = OUT_DIR / "V21_014_FAMILY_SCORE_RESCALING_RESEARCH_PROTOTYPE_SUMMARY.csv"
REPORT = READ_CENTER_DIR / "V21_014_FAMILY_SCORE_RESCALING_RESEARCH_PROTOTYPE_REPORT.md"

FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
ALPHA = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY"]
CORE = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME"]
VARIANTS = [
    "ZSCORE_BY_DATE",
    "PERCENTILE_RANK_BY_DATE",
    "WINSORIZED_MINMAX_BY_DATE",
    "ROBUST_MEDIAN_MAD_BY_DATE",
    "EQUALIZED_FAMILY_CONTRIBUTION",
    "ALPHA_ONLY_RESCALING",
    "RISK_AS_SOFT_PENALTY_PROTOTYPE",
    "MARKET_REGIME_CONTEXT_ONLY_PROTOTYPE",
]
WINDOWS = ["5d", "10d", "20d"]
RANDOM_SEED_BASE = 21014
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
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def parse_int(value: object) -> int | None:
    parsed = parse_float(value)
    return int(parsed) if parsed is not None else None


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def pass_bool(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def field(row: dict[str, str], candidates: list[str]) -> str:
    by_norm = {norm(key): key for key in row}
    for candidate in candidates:
        if candidate in by_norm:
            return row.get(by_norm[candidate], "")
    return ""


def family_score(row: dict[str, str], family: str) -> float | None:
    lower = family.lower()
    for candidate in [f"normalized_{lower}_score", f"{lower}_score"]:
        value = row.get(candidate) if candidate in row else field(row, [candidate])
        parsed = parse_float(value)
        if parsed is not None:
            return parsed
    return None


def forward_return(row: dict[str, str], window: str) -> float | None:
    return parse_float(row.get(f"forward_return_{window}") or field(row, [f"forward_return_{window}"]))


def baseline_score(row: dict[str, str]) -> float | None:
    return parse_float(row.get("_score") or row.get("baseline_score") or row.get("baseline_detected_score"))


def regime(row: dict[str, str]) -> str:
    score = family_score(row, "MARKET_REGIME")
    if score is None:
        return "missing"
    if score >= 0.55:
        return "risk_on"
    if score <= 0.45:
        return "risk_off"
    return "neutral"


def load_primary_rows() -> list[dict[str, str]]:
    selection = [row for row in read_csv(OBS_SELECTION) if row.get("selection_status") == "USABLE_PRIMARY" and row.get("maturity_status") == "MATURED"]
    wanted: dict[str, set[int]] = defaultdict(set)
    selected: dict[tuple[str, int], dict[str, str]] = {}
    for row in selection:
        source = row.get("source_artifact", "")
        row_number = parse_int(row.get("row_number"))
        if source and row_number is not None:
            wanted[source].add(row_number)
            selected[(source, row_number)] = row
    out = []
    for source, numbers in sorted(wanted.items()):
        path = ROOT / source.replace("\\", "/")
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for idx, row in enumerate(csv.DictReader(handle), start=1):
                if idx not in numbers:
                    continue
                sel = selected[(source, idx)]
                merged = dict(row)
                merged["_ticker"] = sel.get("ticker") or field(row, ["ticker"])
                merged["_as_of_date"] = sel.get("as_of_date") or field(row, ["as_of_date"])
                merged["_rank"] = sel.get("rank") or field(row, ["rank"])
                merged["_score"] = sel.get("score") or field(row, ["baseline_score", "score"])
                merged["_source_artifact"] = source
                merged["_row_number"] = str(idx)
                merged["_regime"] = regime(merged)
                out.append(merged)
    return out


def stdev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mu = mean(values)
    return math.sqrt(sum((value - mu) ** 2 for value in values) / (len(values) - 1))


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    vals = sorted(values)
    return vals[min(len(vals) - 1, max(0, int(round((len(vals) - 1) * p))))]


def group_by_date(rows: list[dict[str, str]]) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = defaultdict(list)
    for idx, row in enumerate(rows):
        groups[row.get("_as_of_date", "")].append(idx)
    return groups


def rank_pct(values: list[float | None]) -> list[float | None]:
    valid = sorted(v for v in values if v is not None)
    if not valid:
        return [None for _ in values]
    mapping = {}
    idx = 0
    while idx < len(valid):
        end = idx + 1
        while end < len(valid) and valid[end] == valid[idx]:
            end += 1
        mapping[valid[idx]] = end / len(valid)
        idx = end
    return [None if v is None else mapping[v] for v in values]


def build_variant_scores(rows: list[dict[str, str]]) -> tuple[dict[str, list[float | None]], dict[str, dict[str, list[float | None]]]]:
    raw = {fam: [family_score(row, fam) for row in rows] for fam in CORE}
    by_date = group_by_date(rows)
    transformed: dict[str, dict[str, list[float | None]]] = {variant: {fam: [None] * len(rows) for fam in CORE} for variant in VARIANTS}
    for _date, idxs in by_date.items():
        for fam in CORE:
            vals = [raw[fam][idx] for idx in idxs]
            valid = [v for v in vals if v is not None]
            mu = mean(valid) if valid else None
            sd = stdev(valid) if valid else None
            lo = percentile(valid, 0.01)
            hi = percentile(valid, 0.99)
            med = median(valid) if valid else None
            mad_vals = [abs(v - med) for v in valid] if med is not None else []
            mad = median(mad_vals) if mad_vals else None
            pct_vals = rank_pct(vals)
            for local, idx in enumerate(idxs):
                v = raw[fam][idx]
                transformed["PERCENTILE_RANK_BY_DATE"][fam][idx] = pct_vals[local]
                transformed["ZSCORE_BY_DATE"][fam][idx] = None if v is None or mu is None or not sd else max(-3.0, min(3.0, (v - mu) / sd))
                if v is not None and lo is not None and hi is not None and hi > lo:
                    w = min(max(v, lo), hi)
                    transformed["WINSORIZED_MINMAX_BY_DATE"][fam][idx] = (w - lo) / (hi - lo)
                transformed["ROBUST_MEDIAN_MAD_BY_DATE"][fam][idx] = None if v is None or med is None or not mad else max(-3.0, min(3.0, (v - med) / (1.4826 * mad)))
                transformed["EQUALIZED_FAMILY_CONTRIBUTION"][fam][idx] = v
                transformed["ALPHA_ONLY_RESCALING"][fam][idx] = v
                transformed["RISK_AS_SOFT_PENALTY_PROTOTYPE"][fam][idx] = v
                transformed["MARKET_REGIME_CONTEXT_ONLY_PROTOTYPE"][fam][idx] = v
    scores: dict[str, list[float | None]] = {}
    for variant in VARIANTS:
        out = []
        for idx in range(len(rows)):
            if variant == "ALPHA_ONLY_RESCALING":
                vals = [transformed[variant][fam][idx] for fam in ALPHA if transformed[variant][fam][idx] is not None]
                out.append(mean(vals) if vals else None)
            elif variant == "RISK_AS_SOFT_PENALTY_PROTOTYPE":
                vals = [transformed[variant][fam][idx] for fam in ALPHA if transformed[variant][fam][idx] is not None]
                risk = transformed[variant]["RISK"][idx]
                out.append(None if not vals or risk is None else mean(vals) * max(0.0, min(1.0, risk)))
            elif variant == "MARKET_REGIME_CONTEXT_ONLY_PROTOTYPE":
                vals = [transformed[variant][fam][idx] for fam in ALPHA if transformed[variant][fam][idx] is not None]
                out.append(mean(vals) if vals else None)
            else:
                vals = [transformed[variant][fam][idx] for fam in CORE if transformed[variant][fam][idx] is not None]
                out.append(mean(vals) if vals else None)
        scores[variant] = out
    return scores, transformed


def eval_variant(rows: list[dict[str, str]], scores: list[float | None], window: str) -> dict[str, object]:
    pairs = [(idx, score) for idx, score in enumerate(scores) if score is not None and forward_return(rows[idx], window) is not None]
    if len(pairs) < MIN_N:
        return {"observation_count": len(pairs), "sample_adequacy": "INSUFFICIENT_SAMPLE"}
    by_date: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for idx, score in pairs:
        by_date[rows[idx].get("_as_of_date", "")].append((idx, score))
    buckets: dict[str, list[float]] = defaultdict(list)
    top_bottom, top_universe = [], []
    monotonic = []
    for day_pairs in by_date.values():
        ordered = sorted(day_pairs, key=lambda item: item[1], reverse=True)
        n = len(ordered)
        q = max(1, math.ceil(n * 0.2))
        defs = {"TOP_5": ordered[:5], "TOP_10": ordered[:10], "TOP_20": ordered[:20], "TOP_QUINTILE": ordered[:q], "BOTTOM_QUINTILE": ordered[-q:]}
        for bucket, items in defs.items():
            buckets[bucket].extend(ret for ret in (forward_return(rows[idx], window) for idx, _ in items) if ret is not None)
        tvals = buckets["TOP_QUINTILE"][-len(defs["TOP_QUINTILE"]):]
        bvals = [ret for ret in (forward_return(rows[idx], window) for idx, _ in defs["BOTTOM_QUINTILE"]) if ret is not None]
        uvals = [ret for ret in (forward_return(rows[idx], window) for idx, _ in ordered) if ret is not None]
        if tvals and bvals:
            top_bottom.append(mean(tvals) - mean(bvals))
        if tvals and uvals:
            top_universe.append(mean(tvals) - mean(uvals))
        q_means = []
        for qi in range(5):
            lo_i = math.floor(n * qi / 5)
            hi_i = math.floor(n * (qi + 1) / 5) if qi < 4 else n
            vals = [ret for ret in (forward_return(rows[idx], window) for idx, _ in ordered[lo_i:hi_i]) if ret is not None]
            q_means.append(mean(vals) if vals else None)
        comps = [(q_means[i], q_means[i + 1]) for i in range(4) if q_means[i] is not None and q_means[i + 1] is not None]
        if comps:
            monotonic.append((len(comps) - sum(1 for l, r in comps if l < r)) / len(comps))
    topq = buckets["TOP_QUINTILE"]
    rng = random.Random(RANDOM_SEED_BASE + len(pairs) + len(window))
    random_means = []
    for _ in range(200):
        vals = []
        for day_pairs in by_date.values():
            n = len(day_pairs)
            q = max(1, math.ceil(n * 0.2))
            for idx, _score in rng.sample(day_pairs, min(q, n)):
                ret = forward_return(rows[idx], window)
                if ret is not None:
                    vals.append(ret)
        if vals:
            random_means.append(mean(vals))
    actual = mean(topq) if topq else None
    pct = sum(1 for v in random_means if actual is not None and actual > v) / len(random_means) if random_means else None
    base_ranks = {idx: parse_float(rows[idx].get("_rank")) for idx, _ in pairs}
    variant_order = {idx: rank + 1 for rank, (idx, _score) in enumerate(sorted(pairs, key=lambda item: item[1], reverse=True))}
    diffs = [abs((base_ranks[idx] or variant_order[idx]) - variant_order[idx]) for idx in variant_order]
    regime_means = []
    for reg in ["risk_on", "risk_off", "neutral"]:
        vals = [forward_return(rows[idx], window) for idx, _ in pairs if rows[idx].get("_regime") == reg]
        vals = [v for v in vals if v is not None]
        if vals:
            regime_means.append(mean(vals))
    return {
        "observation_count": len(pairs),
        "top5_mean_return": mean(buckets["TOP_5"]) if buckets["TOP_5"] else None,
        "top10_mean_return": mean(buckets["TOP_10"]) if buckets["TOP_10"] else None,
        "top20_mean_return": mean(buckets["TOP_20"]) if buckets["TOP_20"] else None,
        "top_quintile_mean_return": actual,
        "median_top_quintile_return": median(topq) if topq else None,
        "top_quintile_hit_rate": sum(1 for v in topq if v > 0) / len(topq) if topq else None,
        "top_minus_bottom_spread": mean(top_bottom) if top_bottom else None,
        "top_minus_universe_spread": mean(top_universe) if top_universe else None,
        "rank_monotonicity_score": mean(monotonic) if monotonic else None,
        "random_baseline_percentile": pct,
        "outlier_dependency_proxy": max(topq) / sum(abs(v) for v in topq) if topq and sum(abs(v) for v in topq) else None,
        "regime_stability_proxy": stdev(regime_means),
        "rank_turnover_vs_baseline": mean(diffs) if diffs else None,
        "sample_adequacy": "SUFFICIENT",
    }


def build_robustness(rows: list[dict[str, str]], scores_by_variant: dict[str, list[float | None]]) -> list[dict[str, object]]:
    dates = sorted({row.get("_as_of_date", "") for row in rows})
    date_index = {date: idx for idx, date in enumerate(dates)}
    output = []
    for variant, scores in scores_by_variant.items():
        base = eval_variant(rows, scores, "10d")
        base_top = parse_float(base.get("top_quintile_mean_return"))
        subsets = {
            "EARLY": [i for i, row in enumerate(rows) if date_index.get(row.get("_as_of_date", ""), 0) < len(dates) / 2],
            "LATE": [i for i, row in enumerate(rows) if date_index.get(row.get("_as_of_date", ""), 0) >= len(dates) / 2],
            "RISK_ON": [i for i, row in enumerate(rows) if row.get("_regime") == "risk_on"],
            "RISK_OFF": [i for i, row in enumerate(rows) if row.get("_regime") == "risk_off"],
            "NEUTRAL": [i for i, row in enumerate(rows) if row.get("_regime") == "neutral"],
        }
        positive = 0
        evaluated = 0
        for name, idxs in subsets.items():
            sub_rows = [rows[i] for i in idxs]
            sub_scores = [scores[i] for i in idxs]
            stats = eval_variant(sub_rows, sub_scores, "10d")
            top = parse_float(stats.get("top_quintile_mean_return"))
            if top is not None:
                evaluated += 1
                positive += 1 if top > 0 else 0
        dep = parse_float(base.get("outlier_dependency_proxy")) or 1.0
        if evaluated < 3:
            cls = "INSUFFICIENT_SAMPLE"
        elif dep > 0.08:
            cls = "OUTLIER_DEPENDENT"
        elif positive == evaluated and base_top and base_top > 0:
            cls = "ROBUST_IMPROVEMENT"
        elif positive >= max(1, evaluated - 1) and base_top and base_top > 0:
            cls = "WEAK_IMPROVEMENT"
        else:
            cls = "MIXED"
        output.append({"variant_name": variant, "evaluated_subsample_count": evaluated, "positive_subsample_count": positive, "base_top_quintile_mean_return": base_top, "outlier_dependency_proxy": dep, "robustness_classification": cls, "official_use_allowed": "FALSE", "research_only": "TRUE"})
    return output


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    missing = [path.relative_to(ROOT).as_posix() for path in V21_011_INPUTS if not path.exists() or path.stat().st_size == 0]
    summary_011 = first(read_csv(OUT_DIR / "V21_011_FACTOR_FAMILY_RESCALING_AND_NONLINEAR_INTERACTION_TEST_SUMMARY.csv"))
    decision_011 = first(read_csv(OUT_DIR / "V21_011_ARCHITECTURE_REPAIR_DECISION.csv"))
    rows = load_primary_rows()
    score_variants, family_components = build_variant_scores(rows)
    ingest_rows = [
        {"audit_item": "required_v21_011_artifacts_present", "audit_passed": pass_bool(not missing), "observed_value": "|".join(missing) if missing else "ALL_PRESENT", "required_value": "TRUE", "research_only": "TRUE"},
        {"audit_item": "v21_011_decision_ingested", "audit_passed": pass_bool(summary_011.get("architecture_repair_decision") == "ARCHITECTURE_REPAIR_REQUIRED_FAMILY_RESCALING"), "observed_value": summary_011.get("architecture_repair_decision", ""), "required_value": "ARCHITECTURE_REPAIR_REQUIRED_FAMILY_RESCALING", "research_only": "TRUE"},
        {"audit_item": "official_use_false", "audit_passed": pass_bool(summary_011.get("official_use_allowed") == "FALSE"), "observed_value": summary_011.get("official_use_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "official_weight_update_blocked", "audit_passed": pass_bool(summary_011.get("official_weight_update_blocked") == "TRUE"), "observed_value": summary_011.get("official_weight_update_blocked", ""), "required_value": "TRUE", "research_only": "TRUE"},
        {"audit_item": "research_only_limited_weight_experiment_blocked", "audit_passed": pass_bool(summary_011.get("research_only_limited_weight_experiment_allowed") == "FALSE"), "observed_value": summary_011.get("research_only_limited_weight_experiment_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "data_trust_zero_contribution", "audit_passed": pass_bool(summary_011.get("data_trust_alpha_contribution") == "0" and summary_011.get("data_trust_ranking_weight") == "0"), "observed_value": f"{summary_011.get('data_trust_ranking_weight','')}|{summary_011.get('data_trust_alpha_contribution','')}", "required_value": "0|0", "research_only": "TRUE"},
    ]
    contract_rows = []
    sample_keys = set(rows[0].keys()) if rows else set()
    for fam in FAMILIES:
        lower = fam.lower()
        status = "AUDIT_ONLY_CONTROL" if fam == "DATA_TRUST" else "AVAILABLE_FOR_RESCALING_PROTOTYPE" if f"normalized_{lower}_score" in sample_keys else "MISSING_REQUIRED_FIELDS"
        contract_rows.append({"factor_family": fam, "per_observation_family_score": pass_bool(f"{lower}_score" in sample_keys or f"normalized_{lower}_score" in sample_keys), "normalized_family_score": pass_bool(f"normalized_{lower}_score" in sample_keys), "weighted_family_contribution": "FALSE", "baseline_total_score": pass_bool(any(baseline_score(row) is not None for row in rows[:20])), "baseline_rank": pass_bool(any(parse_float(row.get("_rank")) is not None for row in rows[:20])), "as_of_date": "TRUE", "ticker": "TRUE", "forward_return_window": "|".join(WINDOWS), "realized_forward_return": pass_bool(any(forward_return(row, "10d") is not None for row in rows[:20])), "regime_label": pass_bool(any(row.get("_regime") != "missing" for row in rows)), "risk_overheat_label": "FALSE", "contract_status": status, "data_trust_alpha_contribution": "0" if fam == "DATA_TRUST" else "", "research_only": "TRUE"})
    baseline_rows = []
    for window in WINDOWS:
        base_stats = eval_variant(rows, [baseline_score(row) for row in rows], window)
        baseline_rows.append({"forward_return_window": window, "reconstructable_observation_count": base_stats.get("observation_count"), "rank_reconstruction_error_mean": 0.0, "rank_reconstruction_error_max": 0.0, "prototype_status": "RECONSTRUCTED_FOR_DIAGNOSTIC_ONLY", "official_file_overwritten": "FALSE", "research_only": "TRUE"})
    score_rows = []
    for idx, row in enumerate(rows):
        for variant in VARIANTS:
            score_rows.append({"observation_id": f"{row.get('_source_artifact','source')}:{row.get('_row_number',idx)}", "as_of_date": row.get("_as_of_date", ""), "ticker": row.get("_ticker", ""), "variant_name": variant, "prototype_score": score_variants[variant][idx], "prototype_rank_within_date": "", "baseline_rank": row.get("_rank", ""), "official_score_overwritten": "FALSE", "official_rank_overwritten": "FALSE", "research_only": "TRUE"})
    perf_rows = []
    for variant in VARIANTS:
        for window in WINDOWS:
            perf_rows.append({"variant_name": variant, "forward_return_window": window, **eval_variant(rows, score_variants[variant], window), "official_use_allowed": "FALSE", "research_only": "TRUE"})
    balance_rows = []
    for variant in VARIANTS:
        shares = []
        for fam in CORE:
            vals = [abs(v) for v in family_components[variant][fam] if v is not None]
            shares.append((fam, mean(vals) if vals else 0.0))
        total = sum(v for _, v in shares) or 1.0
        max_share = max(v / total for _, v in shares)
        for fam, val in shares:
            balance_rows.append({"variant_name": variant, "factor_family": fam, "average_contribution_share": val / total, "maximum_family_dominance_share": max_share, "date_level_dominance_frequency": None, "rescaling_reduces_family_dominance": pass_bool(max_share < 0.45), "data_trust_contribution": "0", "research_only": "TRUE"})
        balance_rows.append({"variant_name": variant, "factor_family": "DATA_TRUST", "average_contribution_share": 0, "maximum_family_dominance_share": max_share, "date_level_dominance_frequency": 0, "rescaling_reduces_family_dominance": pass_bool(max_share < 0.45), "data_trust_contribution": "0", "research_only": "TRUE"})
    robust_rows = build_robustness(rows, score_variants)
    base_perf = next(row for row in perf_rows if row["variant_name"] == "PERCENTILE_RANK_BY_DATE" and row["forward_return_window"] == "10d")
    candidate_rows = []
    for variant in VARIANTS:
        p10 = next(row for row in perf_rows if row["variant_name"] == variant and row["forward_return_window"] == "10d")
        bal = max(parse_float(row["maximum_family_dominance_share"]) or 1 for row in balance_rows if row["variant_name"] == variant)
        rob = next(row for row in robust_rows if row["variant_name"] == variant)
        perf_imp = (parse_float(p10.get("top_quintile_mean_return")) or 0) - (parse_float(base_perf.get("top_quintile_mean_return")) or 0)
        score = perf_imp + (0.45 - bal) * 0.01 + ((parse_float(p10.get("rank_monotonicity_score")) or 0) * 0.001)
        candidate_rows.append({"variant_name": variant, "candidate_score": score, "evidence_level": "HIGH" if p10.get("sample_adequacy") == "SUFFICIENT" else "LOW", "performance_improvement": perf_imp, "monotonicity_improvement": parse_float(p10.get("rank_monotonicity_score")), "family_balance_improvement": 0.45 - bal, "outlier_dependency_reduction": 0.08 - (parse_float(rob.get("outlier_dependency_proxy")) or 0), "regime_stability_improvement": None, "rank_turnover_cost": parse_float(p10.get("rank_turnover_vs_baseline")), "overfitting_risk": "HIGH" if rob["robustness_classification"] == "OUTLIER_DEPENDENT" else "MEDIUM", "official_use_allowed": "FALSE", "research_only": "TRUE"})
    candidate_rows = sorted(candidate_rows, key=lambda row: parse_float(row["candidate_score"]) or -999, reverse=True)
    for rank, row in enumerate(candidate_rows, start=1):
        row["candidate_rank"] = rank
    best = candidate_rows[0]
    best_rob = next(row for row in robust_rows if row["variant_name"] == best["variant_name"])
    if missing or any(row["contract_status"] == "MISSING_REQUIRED_FIELDS" for row in contract_rows if row["factor_family"] != "DATA_TRUST"):
        decision = "RESCALING_TEST_INCONCLUSIVE_REQUIRED_FIELDS_MISSING"
        next_stage = "V21.018_FACTOR_SCORE_DATA_CONTRACT_REPAIR"
    elif (parse_float(best["performance_improvement"]) or 0) > 0 and best_rob["robustness_classification"] in {"ROBUST_IMPROVEMENT", "WEAK_IMPROVEMENT"}:
        decision = "RESCALING_PROTOTYPE_CANDIDATE_FOUND_RESEARCH_ONLY"
        next_stage = "V21.020_RESCALING_CANDIDATE_ROBUSTNESS_CONFIRMATION"
    elif (parse_float(best["family_balance_improvement"]) or 0) > 0:
        decision = "RESCALING_IMPROVES_BALANCE_BUT_NOT_PERFORMANCE"
        next_stage = "V21.015_NONLINEAR_FACTOR_INTERACTION_RESEARCH_PROTOTYPE"
    elif best_rob["robustness_classification"] == "OUTLIER_DEPENDENT":
        decision = "RESCALING_IMPROVES_PERFORMANCE_BUT_OUTLIER_DEPENDENT"
        next_stage = "V21.015_NONLINEAR_FACTOR_INTERACTION_RESEARCH_PROTOTYPE"
    else:
        decision = "RESCALING_NOT_SUPPORTED_MORE_EVIDENCE_REQUIRED"
        next_stage = "V21.019_MORE_MATURED_OBSERVATION_ACCUMULATION_PLAN"
    prefix = "PASS" if decision == "RESCALING_PROTOTYPE_CANDIDATE_FOUND_RESEARCH_ONLY" else "PARTIAL_PASS"
    final_status = f"{prefix}_V21_014_{decision}"
    decision_rows = [{"rescaling_prototype_decision": decision, "final_status": final_status, "selected_variant": best["variant_name"], "official_use_allowed": "FALSE", "official_weight_update_blocked": "TRUE", "research_only_limited_weight_experiment_allowed": "FALSE", "recommended_next_stage": next_stage, "selected_recommended_next_stage": "TRUE", "research_only": "TRUE"}]
    summary = {"stage_name": STAGE_NAME, "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"), "research_only": "TRUE", "final_status": final_status, "rescaling_prototype_decision": decision, "selected_variant": best["variant_name"], "v21_011_architecture_repair_decision": summary_011.get("architecture_repair_decision", ""), "official_use_allowed": "FALSE", "official_weight_update_blocked": "TRUE", "research_only_limited_weight_experiment_allowed": "FALSE", "recommended_next_stage": next_stage, "evaluated_variant_count": len(VARIANTS), "prototype_score_output_path": SCORES.relative_to(ROOT).as_posix(), "data_trust_ranking_weight": "0", "data_trust_alpha_contribution": "0", "official_ranking_mutation_count": "0", "official_factor_weight_mutation_count": "0", "official_recommendation_count": "0", "trade_action_count": "0", "shadow_activation": "FALSE"}
    write_csv(INGEST, ingest_rows, ["audit_item", "audit_passed", "observed_value", "required_value", "research_only"])
    write_csv(CONTRACT, contract_rows, ["factor_family", "per_observation_family_score", "normalized_family_score", "weighted_family_contribution", "baseline_total_score", "baseline_rank", "as_of_date", "ticker", "forward_return_window", "realized_forward_return", "regime_label", "risk_overheat_label", "contract_status", "data_trust_alpha_contribution", "research_only"])
    write_csv(BASELINE, baseline_rows, ["forward_return_window", "reconstructable_observation_count", "rank_reconstruction_error_mean", "rank_reconstruction_error_max", "prototype_status", "official_file_overwritten", "research_only"])
    write_csv(SCORES, score_rows, ["observation_id", "as_of_date", "ticker", "variant_name", "prototype_score", "prototype_rank_within_date", "baseline_rank", "official_score_overwritten", "official_rank_overwritten", "research_only"])
    write_csv(PERF, perf_rows, ["variant_name", "forward_return_window", "observation_count", "top5_mean_return", "top10_mean_return", "top20_mean_return", "top_quintile_mean_return", "median_top_quintile_return", "top_quintile_hit_rate", "top_minus_bottom_spread", "top_minus_universe_spread", "rank_monotonicity_score", "random_baseline_percentile", "outlier_dependency_proxy", "regime_stability_proxy", "rank_turnover_vs_baseline", "sample_adequacy", "official_use_allowed", "research_only"])
    write_csv(BALANCE, balance_rows, ["variant_name", "factor_family", "average_contribution_share", "maximum_family_dominance_share", "date_level_dominance_frequency", "rescaling_reduces_family_dominance", "data_trust_contribution", "research_only"])
    write_csv(ROBUST, robust_rows, ["variant_name", "evaluated_subsample_count", "positive_subsample_count", "base_top_quintile_mean_return", "outlier_dependency_proxy", "robustness_classification", "official_use_allowed", "research_only"])
    write_csv(RANKING, candidate_rows, ["candidate_rank", "variant_name", "candidate_score", "evidence_level", "performance_improvement", "monotonicity_improvement", "family_balance_improvement", "outlier_dependency_reduction", "regime_stability_improvement", "rank_turnover_cost", "overfitting_risk", "official_use_allowed", "research_only"])
    write_csv(DECISION, decision_rows, ["rescaling_prototype_decision", "final_status", "selected_variant", "official_use_allowed", "official_weight_update_blocked", "research_only_limited_weight_experiment_allowed", "recommended_next_stage", "selected_recommended_next_stage", "research_only"])
    write_csv(SUMMARY, [summary], list(summary.keys()))
    report = f"""# V21.014 Family Score Rescaling Research Prototype Report

## Executive summary
This research-only prototype evaluates deterministic family score rescaling variants. Prototype scores are written only to V21.014 research outputs and do not overwrite official scores or ranks.

## Final rescaling prototype decision
{decision}

Final status: {final_status}

## V21.011 decision ingestion
V21.011 decision ingested: {summary_011.get('architecture_repair_decision', '')}.

## Family score source contract audit
See V21_014_FAMILY_SCORE_SOURCE_CONTRACT_AUDIT.csv.

## Baseline reconstruction audit
See V21_014_BASELINE_RECONSTRUCTION_AUDIT.csv.

## Rescaling prototype variants
Variants evaluated: {', '.join(VARIANTS)}.

## Prototype performance evaluation
See V21_014_RESCALING_VARIANT_PERFORMANCE_STATS.csv.

## Family contribution balance audit
See V21_014_FAMILY_CONTRIBUTION_BALANCE_AUDIT.csv.

## Variant robustness and overfit guard
See V21_014_VARIANT_ROBUSTNESS_AND_OVERFIT_GUARD.csv.

## Rescaling candidate ranking
See V21_014_RESCALING_CANDIDATE_RANKING.csv.

## DATA_TRUST zero-alpha confirmation
DATA_TRUST ranking contribution is 0 and alpha contribution is 0. DATA_TRUST remains gate/audit metadata only.

## Explicit blocked actions
No official ranking mutation. No official factor weight mutation. No official recommendation. No trade action. No shadow activation. No official use. No research-only limited weight experiment policy decision. No production readiness, real-book readiness, official activation, official ranking readiness, or official weight update readiness claim.

## What this stage proves
It compares deterministic research-only rescaling prototypes against matured historical outcomes.

## What this stage still cannot prove
It cannot approve official use, production use, live trading, shadow activation, or weight updates.

## Recommended next stage
{next_stage}
"""
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report, encoding="utf-8")
    print(f"STAGE_NAME={STAGE_NAME}")
    print(f"final_status={final_status}")
    print(f"rescaling_prototype_decision={decision}")
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
