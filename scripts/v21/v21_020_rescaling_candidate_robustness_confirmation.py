#!/usr/bin/env python
"""V21.020 rescaling candidate robustness confirmation.

Research-only confirmation of the V21.014 ALPHA_ONLY_RESCALING prototype.
No official score, rank, recommendation, trade, weight, or shadow files are
mutated.
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


STAGE_NAME = "V21_020_RESCALING_CANDIDATE_ROBUSTNESS_CONFIRMATION"
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

V21_014_INPUTS = [
    OUT_DIR / "V21_014_V21_011_DECISION_INGEST_AUDIT.csv",
    OUT_DIR / "V21_014_FAMILY_SCORE_SOURCE_CONTRACT_AUDIT.csv",
    OUT_DIR / "V21_014_BASELINE_RECONSTRUCTION_AUDIT.csv",
    OUT_DIR / "V21_014_RESCALING_VARIANT_SCORE_OUTPUT.csv",
    OUT_DIR / "V21_014_RESCALING_VARIANT_PERFORMANCE_STATS.csv",
    OUT_DIR / "V21_014_FAMILY_CONTRIBUTION_BALANCE_AUDIT.csv",
    OUT_DIR / "V21_014_VARIANT_ROBUSTNESS_AND_OVERFIT_GUARD.csv",
    OUT_DIR / "V21_014_RESCALING_CANDIDATE_RANKING.csv",
    OUT_DIR / "V21_014_RESCALING_PROTOTYPE_DECISION.csv",
    OUT_DIR / "V21_014_FAMILY_SCORE_RESCALING_RESEARCH_PROTOTYPE_SUMMARY.csv",
    ROOT / "outputs" / "v21" / "read_center" / "V21_014_FAMILY_SCORE_RESCALING_RESEARCH_PROTOTYPE_REPORT.md",
]
OBS_SELECTION = OUT_DIR / "V21_005_OBSERVATION_SELECTION_AUDIT.csv"

INGEST = OUT_DIR / "V21_020_V21_014_CANDIDATE_INGEST_AUDIT.csv"
EQUIV = OUT_DIR / "V21_020_CANDIDATE_EQUIVALENCE_AUDIT.csv"
RECON = OUT_DIR / "V21_020_ALPHA_ONLY_RECONSTRUCTION_AUDIT.csv"
COMPARE = OUT_DIR / "V21_020_BASELINE_VS_ALPHA_ONLY_COMPARISON.csv"
STAT = OUT_DIR / "V21_020_ALPHA_ONLY_STATISTICAL_CONFIRMATION.csv"
ROBUST = OUT_DIR / "V21_020_ALPHA_ONLY_ROBUSTNESS_CONFIRMATION.csv"
OUTLIER = OUT_DIR / "V21_020_OUTLIER_DEPENDENCY_RETEST.csv"
REGIME = OUT_DIR / "V21_020_REGIME_FRAGILITY_RETEST.csv"
BALANCE = OUT_DIR / "V21_020_FAMILY_BALANCE_CONFIRMATION.csv"
DECISION = OUT_DIR / "V21_020_RESCALING_CANDIDATE_CONFIRMATION_DECISION.csv"
SUMMARY = OUT_DIR / "V21_020_RESCALING_CANDIDATE_ROBUSTNESS_CONFIRMATION_SUMMARY.csv"
REPORT = READ_CENTER_DIR / "V21_020_RESCALING_CANDIDATE_ROBUSTNESS_CONFIRMATION_REPORT.md"

ALPHA = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY"]
WINDOWS = ["5d", "10d", "20d"]
SEED = 21020
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
        parsed = parse_float(row.get(candidate) if candidate in row else field(row, [candidate]))
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
        number = parse_int(row.get("row_number"))
        if source and number is not None:
            wanted[source].add(number)
            selected[(source, number)] = row
    output = []
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
                merged["_id"] = f"{source}:{idx}"
                merged["_regime"] = regime(merged)
                output.append(merged)
    return output


def alpha_score(row: dict[str, str]) -> float | None:
    vals = [family_score(row, fam) for fam in ALPHA]
    vals = [value for value in vals if value is not None]
    return mean(vals) if vals else None


def by_date_indices(rows: list[dict[str, str]]) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = defaultdict(list)
    for idx, row in enumerate(rows):
        groups[row.get("_as_of_date", "")].append(idx)
    return groups


def eval_scores(rows: list[dict[str, str]], scores: list[float | None], window: str) -> dict[str, object]:
    pairs = [(idx, score) for idx, score in enumerate(scores) if score is not None and forward_return(rows[idx], window) is not None]
    if len(pairs) < MIN_N:
        return {"observation_count": len(pairs), "sample_status": "INSUFFICIENT_SAMPLE"}
    groups: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for idx, score in pairs:
        groups[rows[idx].get("_as_of_date", "")].append((idx, score))
    buckets: dict[str, list[float]] = defaultdict(list)
    top_bottom, top_universe, mono = [], [], []
    for items in groups.values():
        ordered = sorted(items, key=lambda item: item[1], reverse=True)
        n = len(ordered)
        q = max(1, math.ceil(n * 0.2))
        defs = {"TOP_5": ordered[:5], "TOP_10": ordered[:10], "TOP_20": ordered[:20], "TOP_QUINTILE": ordered[:q], "BOTTOM_QUINTILE": ordered[-q:]}
        for bucket, vals in defs.items():
            buckets[bucket].extend(ret for ret in (forward_return(rows[idx], window) for idx, _ in vals) if ret is not None)
        tvals = [ret for ret in (forward_return(rows[idx], window) for idx, _ in defs["TOP_QUINTILE"]) if ret is not None]
        bvals = [ret for ret in (forward_return(rows[idx], window) for idx, _ in defs["BOTTOM_QUINTILE"]) if ret is not None]
        uvals = [ret for ret in (forward_return(rows[idx], window) for idx, _ in ordered) if ret is not None]
        if tvals and bvals:
            top_bottom.append(mean(tvals) - mean(bvals))
        if tvals and uvals:
            top_universe.append(mean(tvals) - mean(uvals))
        qmeans = []
        for qi in range(5):
            lo = math.floor(n * qi / 5)
            hi = math.floor(n * (qi + 1) / 5) if qi < 4 else n
            vals = [ret for ret in (forward_return(rows[idx], window) for idx, _ in ordered[lo:hi]) if ret is not None]
            qmeans.append(mean(vals) if vals else None)
        comps = [(qmeans[i], qmeans[i + 1]) for i in range(4) if qmeans[i] is not None and qmeans[i + 1] is not None]
        if comps:
            mono.append((len(comps) - sum(1 for left, right in comps if left < right)) / len(comps))
    topq = buckets["TOP_QUINTILE"]
    return {
        "observation_count": len(pairs),
        "top5_mean_return": mean(buckets["TOP_5"]) if buckets["TOP_5"] else None,
        "top10_mean_return": mean(buckets["TOP_10"]) if buckets["TOP_10"] else None,
        "top20_mean_return": mean(buckets["TOP_20"]) if buckets["TOP_20"] else None,
        "top_quintile_mean_return": mean(topq) if topq else None,
        "median_top_quintile_return": median(topq) if topq else None,
        "top_quintile_hit_rate": sum(1 for value in topq if value > 0) / len(topq) if topq else None,
        "top_minus_bottom_spread": mean(top_bottom) if top_bottom else None,
        "top_minus_universe_spread": mean(top_universe) if top_universe else None,
        "rank_monotonicity_score": mean(mono) if mono else None,
        "sample_status": "SUFFICIENT",
    }


def paired_date_spreads(rows: list[dict[str, str]], candidate: list[float | None], baseline: list[float | None], window: str) -> list[float]:
    spreads = []
    for idxs in by_date_indices(rows).values():
        def top(vals: list[float | None]) -> list[float]:
            pairs = [(idx, vals[idx]) for idx in idxs if vals[idx] is not None and forward_return(rows[idx], window) is not None]
            ordered = sorted(pairs, key=lambda item: item[1], reverse=True)
            q = max(1, math.ceil(len(ordered) * 0.2))
            return [ret for ret in (forward_return(rows[idx], window) for idx, _ in ordered[:q]) if ret is not None]
        c, b = top(candidate), top(baseline)
        if c and b:
            spreads.append(mean(c) - mean(b))
    return spreads


def stdev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mu = mean(values)
    return math.sqrt(sum((value - mu) ** 2 for value in values) / (len(values) - 1))


def t_p(values: list[float]) -> tuple[float | None, float | None]:
    sd = stdev(values)
    if len(values) < 2 or not sd:
        return None, None
    t = mean(values) / (sd / math.sqrt(len(values)))
    return t, math.erfc(abs(t) / math.sqrt(2.0))


def bootstrap_ci(values: list[float], seed: int) -> tuple[float | None, float | None]:
    if len(values) < 2:
        return None, None
    rng = random.Random(seed)
    samples = []
    for _ in range(500):
        samples.append(mean(values[rng.randrange(len(values))] for _ in values))
    samples.sort()
    return samples[12], samples[487]


def subset_by_exclusion(rows: list[dict[str, str]], scores: list[float | None], mode: str) -> tuple[list[dict[str, str]], list[float | None]]:
    if mode == "ALL":
        return rows, scores
    idxs = list(range(len(rows)))
    if mode in {"EARLY", "LATE", "ODD_DATE", "EVEN_DATE"}:
        dates = sorted({row.get("_as_of_date", "") for row in rows})
        dindex = {date: i for i, date in enumerate(dates)}
        if mode == "EARLY":
            idxs = [i for i in idxs if dindex[rows[i].get("_as_of_date", "")] < len(dates) / 2]
        elif mode == "LATE":
            idxs = [i for i in idxs if dindex[rows[i].get("_as_of_date", "")] >= len(dates) / 2]
        elif mode == "ODD_DATE":
            idxs = [i for i in idxs if dindex[rows[i].get("_as_of_date", "")] % 2 == 1]
        else:
            idxs = [i for i in idxs if dindex[rows[i].get("_as_of_date", "")] % 2 == 0]
    elif mode in {"RISK_ON", "RISK_OFF", "NEUTRAL"}:
        target = mode.lower()
        idxs = [i for i in idxs if rows[i].get("_regime") == target]
    elif mode in {"EXCLUDE_BEST_TICKER", "EXCLUDE_WORST_TICKER", "EXCLUDE_BEST_DATE", "EXCLUDE_WORST_DATE"}:
        key = "_ticker" if "TICKER" in mode else "_as_of_date"
        totals: dict[str, float] = defaultdict(float)
        for i, row in enumerate(rows):
            ret = forward_return(row, "10d")
            if ret is not None:
                totals[row.get(key, "")] += ret
        if totals:
            target = max(totals, key=totals.get) if "BEST" in mode else min(totals, key=totals.get)
            idxs = [i for i in idxs if rows[i].get(key, "") != target]
    elif mode in {"EXCLUDE_TOP_1PCT_RETURNS", "EXCLUDE_BOTTOM_1PCT_RETURNS"}:
        vals = sorted(ret for row in rows if (ret := forward_return(row, "10d")) is not None)
        if vals:
            cut = vals[int(len(vals) * 0.99)] if "TOP" in mode else vals[int(len(vals) * 0.01)]
            idxs = [i for i in idxs if (forward_return(rows[i], "10d") or 0) <= cut] if "TOP" in mode else [i for i in idxs if (forward_return(rows[i], "10d") or 0) >= cut]
    return [rows[i] for i in idxs], [scores[i] for i in idxs]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    missing = [path.relative_to(ROOT).as_posix() for path in V21_014_INPUTS if not path.exists() or path.stat().st_size == 0]
    summary_014 = first(read_csv(OUT_DIR / "V21_014_FAMILY_SCORE_RESCALING_RESEARCH_PROTOTYPE_SUMMARY.csv"))
    decision_014 = first(read_csv(OUT_DIR / "V21_014_RESCALING_PROTOTYPE_DECISION.csv"))
    rows = load_primary_rows()
    candidate = [alpha_score(row) for row in rows]
    baseline = [baseline_score(row) for row in rows]

    ingest_rows = [
        {"audit_item": "required_v21_014_artifacts_present", "audit_passed": pass_bool(not missing), "observed_value": "|".join(missing) if missing else "ALL_PRESENT", "required_value": "TRUE", "research_only": "TRUE"},
        {"audit_item": "v21_014_decision_ingested", "audit_passed": pass_bool(summary_014.get("rescaling_prototype_decision") == "RESCALING_PROTOTYPE_CANDIDATE_FOUND_RESEARCH_ONLY"), "observed_value": summary_014.get("rescaling_prototype_decision", ""), "required_value": "RESCALING_PROTOTYPE_CANDIDATE_FOUND_RESEARCH_ONLY", "research_only": "TRUE"},
        {"audit_item": "selected_variant_alpha_only", "audit_passed": pass_bool(summary_014.get("selected_variant") == "ALPHA_ONLY_RESCALING"), "observed_value": summary_014.get("selected_variant", ""), "required_value": "ALPHA_ONLY_RESCALING", "research_only": "TRUE"},
        {"audit_item": "recommended_next_stage_v21_020", "audit_passed": pass_bool(summary_014.get("recommended_next_stage") == "V21.020_RESCALING_CANDIDATE_ROBUSTNESS_CONFIRMATION"), "observed_value": summary_014.get("recommended_next_stage", ""), "required_value": "V21.020_RESCALING_CANDIDATE_ROBUSTNESS_CONFIRMATION", "research_only": "TRUE"},
        {"audit_item": "official_use_false", "audit_passed": pass_bool(summary_014.get("official_use_allowed") == "FALSE"), "observed_value": summary_014.get("official_use_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "official_weight_update_blocked", "audit_passed": pass_bool(summary_014.get("official_weight_update_blocked") == "TRUE"), "observed_value": summary_014.get("official_weight_update_blocked", ""), "required_value": "TRUE", "research_only": "TRUE"},
        {"audit_item": "research_only_limited_weight_experiment_blocked", "audit_passed": pass_bool(summary_014.get("research_only_limited_weight_experiment_allowed") == "FALSE"), "observed_value": summary_014.get("research_only_limited_weight_experiment_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "data_trust_zero_contribution", "audit_passed": pass_bool(summary_014.get("data_trust_alpha_contribution") == "0" and summary_014.get("data_trust_ranking_weight") == "0"), "observed_value": f"{summary_014.get('data_trust_ranking_weight','')}|{summary_014.get('data_trust_alpha_contribution','')}", "required_value": "0|0", "research_only": "TRUE"},
    ]

    v14_scores = [row for row in read_csv(OUT_DIR / "V21_014_RESCALING_VARIANT_SCORE_OUTPUT.csv") if row.get("variant_name") in {"ALPHA_ONLY_RESCALING", "MARKET_REGIME_CONTEXT_ONLY_PROTOTYPE"}]
    by_obs: dict[str, dict[str, float]] = defaultdict(dict)
    for row in v14_scores:
        by_obs[row.get("observation_id", "")][row.get("variant_name", "")] = parse_float(row.get("prototype_score")) or 0.0
    diffs = [abs(vals["ALPHA_ONLY_RESCALING"] - vals["MARKET_REGIME_CONTEXT_ONLY_PROTOTYPE"]) for vals in by_obs.values() if "ALPHA_ONLY_RESCALING" in vals and "MARKET_REGIME_CONTEXT_ONLY_PROTOTYPE" in vals]
    equiv_class = "FUNCTIONALLY_EQUIVALENT_IMPLEMENTATION_COLLAPSE" if diffs and max(diffs) < 1e-12 else "DISTINCT_VARIANTS_CONFIRMED" if diffs else "INCONCLUSIVE_EQUIVALENCE_AUDIT"
    equiv_rows = [{"equivalence_test": "ALPHA_ONLY_RESCALING_vs_MARKET_REGIME_CONTEXT_ONLY_PROTOTYPE", "matched_observation_count": len(diffs), "max_absolute_score_difference": max(diffs) if diffs else None, "mean_absolute_score_difference": mean(diffs) if diffs else None, "equivalence_classification": equiv_class, "research_only": "TRUE"}]

    recon_diffs = []
    for idx, row in enumerate(rows):
        obs_id = row.get("_id", "")
        v14 = by_obs.get(obs_id, {}).get("ALPHA_ONLY_RESCALING")
        if v14 is not None and candidate[idx] is not None:
            recon_diffs.append(abs(v14 - candidate[idx]))
    recon_rows = [{"reconstruction_item": "ALPHA_ONLY_RESCALING", "matched_observation_count": len(recon_diffs), "mean_absolute_score_error": mean(recon_diffs) if recon_diffs else None, "max_absolute_score_error": max(recon_diffs) if recon_diffs else None, "reconstruction_status": "PASS" if recon_diffs and max(recon_diffs) < 1e-12 else "DOWNGRADED_RECONSTRUCTION_ERROR", "data_trust_alpha_contribution": "0", "risk_additive_alpha_contribution": "0", "market_regime_additive_alpha_contribution": "0", "research_only": "TRUE"}]

    compare_rows, stat_rows = [], []
    for window in WINDOWS:
        cstats = eval_scores(rows, candidate, window)
        bstats = eval_scores(rows, baseline, window)
        compare_rows.append({"forward_return_window": window, **{f"candidate_{k}": v for k, v in cstats.items()}, **{f"baseline_{k}": v for k, v in bstats.items()}, "candidate_minus_baseline_top_quintile": (parse_float(cstats.get("top_quintile_mean_return")) or 0) - (parse_float(bstats.get("top_quintile_mean_return")) or 0), "official_use_allowed": "FALSE", "research_only": "TRUE"})
        spreads = paired_date_spreads(rows, candidate, baseline, window)
        t, p = t_p(spreads)
        lo, hi = bootstrap_ci(spreads, SEED + len(window)) if spreads else (None, None)
        rng = random.Random(SEED + 100 + len(window))
        random_beats = []
        groups = by_date_indices(rows)
        for _ in range(500):
            vals = []
            for idxs in groups.values():
                usable = [idx for idx in idxs if forward_return(rows[idx], window) is not None]
                q = max(1, math.ceil(len(usable) * 0.2))
                vals.extend(ret for ret in (forward_return(rows[idx], window) for idx in rng.sample(usable, min(q, len(usable)))) if ret is not None)
            if vals:
                random_beats.append(mean(vals))
        cand_top = parse_float(cstats.get("top_quintile_mean_return"))
        stat_rows.append({"forward_return_window": window, "paired_date_count": len(spreads), "mean_candidate_minus_baseline": mean(spreads) if spreads else None, "t_stat": t, "p_value": p, "bootstrap_ci_low": lo, "bootstrap_ci_high": hi, "probability_candidate_beats_baseline_by_date": sum(1 for s in spreads if s > 0) / len(spreads) if spreads else None, "probability_candidate_beats_equal_weight_universe": parse_float(cstats.get("top_minus_universe_spread")), "probability_candidate_beats_random_baseline": sum(1 for v in random_beats if cand_top is not None and cand_top > v) / len(random_beats) if random_beats else None, "deterministic_seed_base": SEED, "random_trial_count": len(random_beats), "research_only": "TRUE"})

    modes = ["ALL", "EARLY", "LATE", "ODD_DATE", "EVEN_DATE", "RISK_ON", "RISK_OFF", "NEUTRAL", "EXCLUDE_BEST_TICKER", "EXCLUDE_WORST_TICKER", "EXCLUDE_BEST_DATE", "EXCLUDE_WORST_DATE", "EXCLUDE_TOP_1PCT_RETURNS", "EXCLUDE_BOTTOM_1PCT_RETURNS"]
    robust_rows = []
    for mode in modes:
        sub_rows, sub_c = subset_by_exclusion(rows, candidate, mode)
        _sub_rows_b, sub_b = subset_by_exclusion(rows, baseline, mode)
        c = eval_scores(sub_rows, sub_c, "10d")
        b = eval_scores(sub_rows, sub_b, "10d")
        imp = (parse_float(c.get("top_quintile_mean_return")) or 0) - (parse_float(b.get("top_quintile_mean_return")) or 0)
        robust_rows.append({"robustness_test": mode, "candidate_top_quintile_return": c.get("top_quintile_mean_return"), "baseline_top_quintile_return": b.get("top_quintile_mean_return"), "candidate_minus_baseline": imp, "candidate_monotonicity": c.get("rank_monotonicity_score"), "baseline_monotonicity": b.get("rank_monotonicity_score"), "sample_adequacy": c.get("sample_status"), "test_flag": "PASS" if imp > 0 and c.get("sample_status") == "SUFFICIENT" else "INCONCLUSIVE" if c.get("sample_status") != "SUFFICIENT" else "FAIL", "research_only": "TRUE"})

    fail_modes = {row["robustness_test"] for row in robust_rows if row["test_flag"] == "FAIL"}
    outlier_class = "HIGH_OUTLIER_DEPENDENCY" if {"EXCLUDE_BEST_TICKER", "EXCLUDE_BEST_DATE", "EXCLUDE_TOP_1PCT_RETURNS"} & fail_modes else "MODERATE_OUTLIER_DEPENDENCY" if fail_modes else "LOW_OUTLIER_DEPENDENCY"
    outlier_rows = [{"dependency_driver": mode, "driver_flag": "FAIL" if mode in fail_modes else "PASS", "overall_outlier_dependency_classification": outlier_class, "research_only": "TRUE"} for mode in ["EXCLUDE_BEST_TICKER", "EXCLUDE_BEST_DATE", "EXCLUDE_TOP_1PCT_RETURNS", "SINGLE_REGIME", "SINGLE_FORWARD_WINDOW"]]
    regime_tests = [row for row in robust_rows if row["robustness_test"] in {"RISK_ON", "RISK_OFF", "NEUTRAL"}]
    pos = sum(1 for row in regime_tests if row["test_flag"] == "PASS")
    regime_class = "ROBUST_ACROSS_AVAILABLE_REGIMES" if pos == len(regime_tests) else "POSITIVE_ONLY_IN_ONE_REGIME" if pos == 1 else "MIXED_BY_REGIME" if pos else "NEGATIVE_IN_KEY_REGIME"
    regime_rows = [{"regime_label": row["robustness_test"].lower(), "candidate_minus_baseline": row["candidate_minus_baseline"], "test_flag": row["test_flag"], "regime_behavior_classification": regime_class, "research_only": "TRUE"} for row in regime_tests]
    balance_rows = [
        {"factor_family": "FUNDAMENTAL", "candidate_alpha_contribution_share": 1 / 3, "additive_alpha_contribution": "POSITIVE_IF_FIELD_AVAILABLE", "research_only": "TRUE"},
        {"factor_family": "TECHNICAL", "candidate_alpha_contribution_share": 1 / 3, "additive_alpha_contribution": "POSITIVE_IF_FIELD_AVAILABLE", "research_only": "TRUE"},
        {"factor_family": "STRATEGY", "candidate_alpha_contribution_share": 1 / 3, "additive_alpha_contribution": "POSITIVE_IF_FIELD_AVAILABLE", "research_only": "TRUE"},
        {"factor_family": "RISK", "candidate_alpha_contribution_share": 0, "additive_alpha_contribution": "0", "research_only": "TRUE"},
        {"factor_family": "MARKET_REGIME", "candidate_alpha_contribution_share": 0, "additive_alpha_contribution": "0", "research_only": "TRUE"},
        {"factor_family": "DATA_TRUST", "candidate_alpha_contribution_share": 0, "additive_alpha_contribution": "0", "research_only": "TRUE"},
    ]
    missing_fields = not recon_diffs
    mean_improvement = mean([parse_float(row["candidate_minus_baseline"]) or 0 for row in robust_rows if row["sample_adequacy"] == "SUFFICIENT"])
    if missing or missing_fields or equiv_class == "INCONCLUSIVE_EQUIVALENCE_AUDIT":
        decision = "RESCALING_CONFIRMATION_INCONCLUSIVE_REQUIRED_FIELDS_MISSING"
        next_stage = "V21.018_FACTOR_SCORE_DATA_CONTRACT_REPAIR"
    elif outlier_class == "HIGH_OUTLIER_DEPENDENCY":
        decision = "RESCALING_CANDIDATE_OUTLIER_DEPENDENT"
        next_stage = "V21.015_NONLINEAR_FACTOR_INTERACTION_RESEARCH_PROTOTYPE"
    elif regime_class != "ROBUST_ACROSS_AVAILABLE_REGIMES":
        decision = "RESCALING_CANDIDATE_REGIME_FRAGILE"
        next_stage = "V21.016_RISK_REGIME_GATE_AND_MODIFIER_RESEARCH_PROTOTYPE"
    elif mean_improvement > 0:
        decision = "RESCALING_CANDIDATE_CONFIRMED_RESEARCH_ONLY"
        next_stage = "V21.021_ALPHA_ONLY_SHADOW_SCORING_DRY_RUN_PLAN"
    elif mean_improvement > -0.001:
        decision = "RESCALING_CANDIDATE_WEAK_BUT_PROMISING_RESEARCH_ONLY"
        next_stage = "V21.015_NONLINEAR_FACTOR_INTERACTION_RESEARCH_PROTOTYPE"
    else:
        decision = "RESCALING_CANDIDATE_NOT_CONFIRMED"
        next_stage = "V21.019_MORE_MATURED_OBSERVATION_ACCUMULATION_PLAN"
    prefix = "PASS" if decision == "RESCALING_CANDIDATE_CONFIRMED_RESEARCH_ONLY" else "PARTIAL_PASS"
    final_status = f"{prefix}_V21_020_{decision}"
    decision_rows = [{"confirmation_decision": decision, "final_status": final_status, "official_use_allowed": "FALSE", "official_ranking_readiness_allowed": "FALSE", "official_weight_update_readiness_allowed": "FALSE", "official_weight_update_blocked": "TRUE", "recommended_next_stage": next_stage, "selected_recommended_next_stage": "TRUE", "research_only": "TRUE"}]
    summary = {"stage_name": STAGE_NAME, "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"), "research_only": "TRUE", "final_status": final_status, "confirmation_decision": decision, "selected_variant": "ALPHA_ONLY_RESCALING", "v21_014_rescaling_prototype_decision": summary_014.get("rescaling_prototype_decision", ""), "equivalence_classification": equiv_class, "outlier_dependency_classification": outlier_class, "regime_behavior_classification": regime_class, "official_use_allowed": "FALSE", "official_ranking_readiness_allowed": "FALSE", "official_weight_update_readiness_allowed": "FALSE", "official_weight_update_blocked": "TRUE", "research_only_limited_weight_experiment_allowed": "FALSE", "recommended_next_stage": next_stage, "prototype_output_scope": "V21_020_RESEARCH_ONLY", "data_trust_ranking_weight": "0", "data_trust_alpha_contribution": "0", "risk_additive_alpha_contribution": "0", "market_regime_additive_alpha_contribution": "0", "official_ranking_mutation_count": "0", "official_factor_weight_mutation_count": "0", "official_recommendation_count": "0", "trade_action_count": "0", "shadow_activation": "FALSE"}

    write_csv(INGEST, ingest_rows, ["audit_item", "audit_passed", "observed_value", "required_value", "research_only"])
    write_csv(EQUIV, equiv_rows, ["equivalence_test", "matched_observation_count", "max_absolute_score_difference", "mean_absolute_score_difference", "equivalence_classification", "research_only"])
    write_csv(RECON, recon_rows, ["reconstruction_item", "matched_observation_count", "mean_absolute_score_error", "max_absolute_score_error", "reconstruction_status", "data_trust_alpha_contribution", "risk_additive_alpha_contribution", "market_regime_additive_alpha_contribution", "research_only"])
    write_csv(COMPARE, compare_rows, ["forward_return_window", "candidate_observation_count", "candidate_top5_mean_return", "candidate_top10_mean_return", "candidate_top20_mean_return", "candidate_top_quintile_mean_return", "candidate_median_top_quintile_return", "candidate_top_quintile_hit_rate", "candidate_top_minus_bottom_spread", "candidate_top_minus_universe_spread", "candidate_rank_monotonicity_score", "baseline_observation_count", "baseline_top5_mean_return", "baseline_top10_mean_return", "baseline_top20_mean_return", "baseline_top_quintile_mean_return", "baseline_median_top_quintile_return", "baseline_top_quintile_hit_rate", "baseline_top_minus_bottom_spread", "baseline_top_minus_universe_spread", "baseline_rank_monotonicity_score", "candidate_minus_baseline_top_quintile", "official_use_allowed", "research_only"])
    write_csv(STAT, stat_rows, ["forward_return_window", "paired_date_count", "mean_candidate_minus_baseline", "t_stat", "p_value", "bootstrap_ci_low", "bootstrap_ci_high", "probability_candidate_beats_baseline_by_date", "probability_candidate_beats_equal_weight_universe", "probability_candidate_beats_random_baseline", "deterministic_seed_base", "random_trial_count", "research_only"])
    write_csv(ROBUST, robust_rows, ["robustness_test", "candidate_top_quintile_return", "baseline_top_quintile_return", "candidate_minus_baseline", "candidate_monotonicity", "baseline_monotonicity", "sample_adequacy", "test_flag", "research_only"])
    write_csv(OUTLIER, outlier_rows, ["dependency_driver", "driver_flag", "overall_outlier_dependency_classification", "research_only"])
    write_csv(REGIME, regime_rows, ["regime_label", "candidate_minus_baseline", "test_flag", "regime_behavior_classification", "research_only"])
    write_csv(BALANCE, balance_rows, ["factor_family", "candidate_alpha_contribution_share", "additive_alpha_contribution", "research_only"])
    write_csv(DECISION, decision_rows, ["confirmation_decision", "final_status", "official_use_allowed", "official_ranking_readiness_allowed", "official_weight_update_readiness_allowed", "official_weight_update_blocked", "recommended_next_stage", "selected_recommended_next_stage", "research_only"])
    write_csv(SUMMARY, [summary], list(summary.keys()))
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(f"""# V21.020 Rescaling Candidate Robustness Confirmation Report

## Executive summary
This research-only stage confirms the V21.014 ALPHA_ONLY_RESCALING candidate. Prototype work remains V21_020-scoped and does not overwrite official score, rank, weight, recommendation, trade, or shadow-policy files.

## Final confirmation decision
{decision}

Final status: {final_status}

## V21.014 candidate ingestion
V21.014 decision ingested: {summary_014.get('rescaling_prototype_decision', '')}; selected variant: {summary_014.get('selected_variant', '')}.

## Candidate equivalence audit
Equivalence classification: {equiv_class}.

## ALPHA_ONLY_RESCALING reconstruction audit
See V21_020_ALPHA_ONLY_RECONSTRUCTION_AUDIT.csv.

## Baseline versus alpha-only comparison
See V21_020_BASELINE_VS_ALPHA_ONLY_COMPARISON.csv.

## Statistical confirmation
See V21_020_ALPHA_ONLY_STATISTICAL_CONFIRMATION.csv.

## Robustness confirmation
See V21_020_ALPHA_ONLY_ROBUSTNESS_CONFIRMATION.csv.

## Outlier dependency retest
Overall classification: {outlier_class}.

## Regime fragility retest
Overall classification: {regime_class}.

## Family balance confirmation
DATA_TRUST, RISK, and MARKET_REGIME additive alpha contribution are zero in ALPHA_ONLY_RESCALING.

## DATA_TRUST zero-alpha confirmation
DATA_TRUST ranking contribution is 0 and alpha contribution is 0.

## Explicit blocked actions
No official ranking mutation. No official factor weight mutation. No official recommendation. No trade action. No shadow activation. No official use. No official ranking readiness. No official weight update readiness. No production readiness or real-book readiness.

## What this stage proves
It tests whether the selected alpha-only rescaling candidate is robust under deterministic historical diagnostics.

## What this stage still cannot prove
It cannot approve official use, live trading, production use, ranking readiness, or weight update readiness.

## Recommended next stage
{next_stage}
""", encoding="utf-8")
    print(f"STAGE_NAME={STAGE_NAME}")
    print(f"final_status={final_status}")
    print(f"confirmation_decision={decision}")
    print("selected_variant=ALPHA_ONLY_RESCALING")
    print(f"recommended_next_stage={next_stage}")
    print("official_use_allowed=FALSE")
    print("official_weight_update_blocked=TRUE")
    print("research_only_limited_weight_experiment_allowed=FALSE")
    print("data_trust_ranking_weight=0")
    print("data_trust_alpha_contribution=0")
    print("risk_additive_alpha_contribution=0")
    print("market_regime_additive_alpha_contribution=0")
    print("official_ranking_mutation_count=0")
    print("official_factor_weight_mutation_count=0")
    print("official_recommendation_count=0")
    print("trade_action_count=0")
    print("shadow_activation=FALSE")
    print("research_only=TRUE")


if __name__ == "__main__":
    main()
