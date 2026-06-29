#!/usr/bin/env python
"""V21.022 risk/regime modifier robustness confirmation.

Research-only confirmation of the V21.016 RISK_HARD_GATE_DIAGNOSTIC
candidate. This script never mutates official score, rank, recommendation,
trade, weight, or shadow-policy artifacts.
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


STAGE_NAME = "V21_022_RISK_REGIME_MODIFIER_ROBUSTNESS_CONFIRMATION"
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"
OBS_SELECTION = OUT_DIR / "V21_005_OBSERVATION_SELECTION_AUDIT.csv"

V21_016_INPUTS = [
    OUT_DIR / "V21_016_V21_020_DECISION_INGEST_AUDIT.csv",
    OUT_DIR / "V21_016_RISK_REGIME_FIELD_AVAILABILITY_AUDIT.csv",
    OUT_DIR / "V21_016_EQUIVALENCE_COLLAPSE_ROOT_CAUSE_AUDIT.csv",
    OUT_DIR / "V21_016_RISK_REGIME_PROTOTYPE_VARIANT_SCORE_OUTPUT.csv",
    OUT_DIR / "V21_016_VARIANT_PERFORMANCE_EVALUATION.csv",
    OUT_DIR / "V21_016_REGIME_SPECIFIC_VARIANT_EVALUATION.csv",
    OUT_DIR / "V21_016_RISK_OVERHEAT_FALSE_BLOCK_PROTECTION_TEST.csv",
    OUT_DIR / "V21_016_STATISTICAL_RANDOM_BASELINE_CONFIRMATION.csv",
    OUT_DIR / "V21_016_OUTLIER_AND_REGIME_FRAGILITY_AUDIT.csv",
    OUT_DIR / "V21_016_RISK_REGIME_VARIANT_SELECTION.csv",
    OUT_DIR / "V21_016_RISK_REGIME_GATE_AND_MODIFIER_DECISION.csv",
    OUT_DIR / "V21_016_RISK_REGIME_GATE_AND_MODIFIER_RESEARCH_PROTOTYPE_SUMMARY.csv",
    READ_CENTER_DIR / "V21_016_RISK_REGIME_GATE_AND_MODIFIER_RESEARCH_PROTOTYPE_REPORT.md",
]

INGEST = OUT_DIR / "V21_022_V21_016_CANDIDATE_INGEST_AUDIT.csv"
RECON = OUT_DIR / "V21_022_RISK_HARD_GATE_RECONSTRUCTION_AUDIT.csv"
COMPARE = OUT_DIR / "V21_022_CANDIDATE_VS_ALPHA_ONLY_COMPARISON.csv"
STAT = OUT_DIR / "V21_022_STATISTICAL_CONFIRMATION.csv"
REGIME = OUT_DIR / "V21_022_REGIME_ROBUSTNESS_CONFIRMATION.csv"
FALSE_BLOCK = OUT_DIR / "V21_022_FALSE_BLOCK_AND_MISSED_WINNER_AUDIT.csv"
OUTLIER = OUT_DIR / "V21_022_OUTLIER_DEPENDENCY_RETEST.csv"
CONTEXT = OUT_DIR / "V21_022_MARKET_REGIME_DISTINCT_CONTEXT_LOGIC_AUDIT.csv"
READINESS = OUT_DIR / "V21_022_RESEARCH_DRY_RUN_READINESS_ASSESSMENT.csv"
DECISION = OUT_DIR / "V21_022_RISK_REGIME_MODIFIER_CONFIRMATION_DECISION.csv"
SUMMARY = OUT_DIR / "V21_022_RISK_REGIME_MODIFIER_ROBUSTNESS_CONFIRMATION_SUMMARY.csv"
REPORT = READ_CENTER_DIR / "V21_022_RISK_REGIME_MODIFIER_ROBUSTNESS_CONFIRMATION_REPORT.md"

ALPHA_FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY"]
WINDOWS = ["5d", "10d", "20d"]
REGIMES = ["risk_on", "risk_off", "neutral"]
SEED = 21022
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


def fnum(value: object) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def fint(value: object) -> int | None:
    parsed = fnum(value)
    return int(parsed) if parsed is not None else None


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def yn(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def field(row: dict[str, str], candidates: list[str]) -> str:
    by_norm = {norm(key): key for key in row}
    for candidate in candidates:
        if candidate in by_norm:
            return row.get(by_norm[candidate], "")
    return ""


def family_score(row: dict[str, str], family: str) -> float | None:
    low = family.lower()
    for candidate in [f"normalized_{low}_score", f"{low}_score"]:
        parsed = fnum(row.get(candidate) if candidate in row else field(row, [candidate]))
        if parsed is not None:
            return parsed
    return None


def forward_return(row: dict[str, str], window: str) -> float | None:
    return fnum(row.get(f"forward_return_{window}") or field(row, [f"forward_return_{window}"]))


def detected_regime(row: dict[str, str]) -> str:
    score = family_score(row, "MARKET_REGIME")
    if score is None:
        return "missing"
    if score >= 0.55:
        return "risk_on"
    if score <= 0.45:
        return "risk_off"
    return "neutral"


def alpha_score(row: dict[str, str]) -> float | None:
    vals = [family_score(row, family) for family in ALPHA_FAMILIES]
    vals = [value for value in vals if value is not None]
    return mean(vals) if vals else None


def risk_hard_gate_score(row: dict[str, str]) -> float | None:
    alpha = alpha_score(row)
    risk = family_score(row, "RISK")
    if alpha is None:
        return None
    return alpha - 1.0 if risk is not None and risk < 0.35 else alpha


def is_risk_blocked(row: dict[str, str]) -> bool:
    risk = family_score(row, "RISK")
    return risk is not None and risk < 0.35


def load_primary_rows() -> list[dict[str, str]]:
    selection = [row for row in read_csv(OBS_SELECTION) if row.get("selection_status") == "USABLE_PRIMARY" and row.get("maturity_status") == "MATURED"]
    wanted: dict[str, set[int]] = defaultdict(set)
    selected: dict[tuple[str, int], dict[str, str]] = {}
    for row in selection:
        source = row.get("source_artifact", "")
        number = fint(row.get("row_number"))
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
                merged["_id"] = f"{source}:{idx}"
                merged["_ticker"] = sel.get("ticker") or field(row, ["ticker"])
                merged["_as_of_date"] = sel.get("as_of_date") or field(row, ["as_of_date"])
                merged["_rank"] = sel.get("rank") or field(row, ["rank"])
                merged["_score"] = sel.get("score") or field(row, ["baseline_score", "score"])
                merged["_regime"] = detected_regime(merged)
                output.append(merged)
    return output


def by_date_indices(rows: list[dict[str, str]]) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = defaultdict(list)
    for idx, row in enumerate(rows):
        groups[row.get("_as_of_date", "")].append(idx)
    return groups


def rank_map(rows: list[dict[str, str]], scores: list[float | None]) -> dict[int, int]:
    ranks: dict[int, int] = {}
    for idxs in by_date_indices(rows).values():
        usable = [(idx, scores[idx]) for idx in idxs if scores[idx] is not None]
        for rank, (idx, _score) in enumerate(sorted(usable, key=lambda item: item[1], reverse=True), start=1):
            ranks[idx] = rank
    return ranks


def eval_scores(rows: list[dict[str, str]], scores: list[float | None], window: str) -> dict[str, object]:
    pairs = [(idx, score) for idx, score in enumerate(scores) if score is not None and forward_return(rows[idx], window) is not None]
    if len(pairs) < MIN_N:
        return {"observation_count": len(pairs), "sample_adequacy": "INSUFFICIENT_SAMPLE"}
    groups: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for idx, score in pairs:
        groups[rows[idx].get("_as_of_date", "")].append((idx, score))
    buckets: dict[str, list[float]] = defaultdict(list)
    top_bottom, top_universe, monotonicity, downside = [], [], [], []
    for items in groups.values():
        ordered = sorted(items, key=lambda item: item[1], reverse=True)
        n = len(ordered)
        q = max(1, math.ceil(n * 0.2))
        defs = {"TOP_5": ordered[:5], "TOP_10": ordered[:10], "TOP_20": ordered[:20], "TOP_QUINTILE": ordered[:q], "BOTTOM_QUINTILE": ordered[-q:]}
        for bucket, vals in defs.items():
            buckets[bucket].extend(ret for ret in (forward_return(rows[idx], window) for idx, _ in vals) if ret is not None)
        top_vals = [ret for ret in (forward_return(rows[idx], window) for idx, _ in defs["TOP_QUINTILE"]) if ret is not None]
        bottom_vals = [ret for ret in (forward_return(rows[idx], window) for idx, _ in defs["BOTTOM_QUINTILE"]) if ret is not None]
        universe_vals = [ret for ret in (forward_return(rows[idx], window) for idx, _ in ordered) if ret is not None]
        if top_vals and bottom_vals:
            top_bottom.append(mean(top_vals) - mean(bottom_vals))
        if top_vals and universe_vals:
            top_universe.append(mean(top_vals) - mean(universe_vals))
        downside.extend(value for value in top_vals if value < 0)
        qmeans = []
        for qi in range(5):
            lo = math.floor(n * qi / 5)
            hi = math.floor(n * (qi + 1) / 5) if qi < 4 else n
            vals = [ret for ret in (forward_return(rows[idx], window) for idx, _ in ordered[lo:hi]) if ret is not None]
            qmeans.append(mean(vals) if vals else None)
        comps = [(qmeans[i], qmeans[i + 1]) for i in range(4) if qmeans[i] is not None and qmeans[i + 1] is not None]
        if comps:
            monotonicity.append((len(comps) - sum(1 for left, right in comps if left < right)) / len(comps))
    topq = buckets["TOP_QUINTILE"]
    return {
        "observation_count": len(pairs),
        "top5_mean_return": mean(buckets["TOP_5"]) if buckets["TOP_5"] else None,
        "top10_mean_return": mean(buckets["TOP_10"]) if buckets["TOP_10"] else None,
        "top20_mean_return": mean(buckets["TOP_20"]) if buckets["TOP_20"] else None,
        "top_quintile_mean_return": mean(topq) if topq else None,
        "median_top_quintile_return": median(topq) if topq else None,
        "hit_rate": sum(1 for value in topq if value > 0) / len(topq) if topq else None,
        "top_minus_bottom_spread": mean(top_bottom) if top_bottom else None,
        "top_minus_universe_spread": mean(top_universe) if top_universe else None,
        "rank_monotonicity_score": mean(monotonicity) if monotonicity else None,
        "downside_proxy": mean(downside) if downside else 0.0,
        "sample_adequacy": "SUFFICIENT",
    }


def paired_date_spreads(rows: list[dict[str, str]], candidate: list[float | None], baseline: list[float | None], window: str) -> list[float]:
    spreads = []
    for idxs in by_date_indices(rows).values():
        def top(vals: list[float | None]) -> list[float]:
            pairs = [(idx, vals[idx]) for idx in idxs if vals[idx] is not None and forward_return(rows[idx], window) is not None]
            ordered = sorted(pairs, key=lambda item: item[1], reverse=True)
            q = max(1, math.ceil(len(ordered) * 0.2))
            return [ret for ret in (forward_return(rows[idx], window) for idx, _ in ordered[:q]) if ret is not None]

        cand, base = top(candidate), top(baseline)
        if cand and base:
            spreads.append(mean(cand) - mean(base))
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
    t_stat = mean(values) / (sd / math.sqrt(len(values)))
    return t_stat, math.erfc(abs(t_stat) / math.sqrt(2.0))


def bootstrap_ci(values: list[float], seed: int) -> tuple[float | None, float | None]:
    if len(values) < 2:
        return None, None
    rng = random.Random(seed)
    samples = [mean(values[rng.randrange(len(values))] for _ in values) for _ in range(500)]
    samples.sort()
    return samples[12], samples[487]


def subset_indices(rows: list[dict[str, str]], mode: str) -> list[int]:
    idxs = list(range(len(rows)))
    if mode == "ALL":
        return idxs
    if mode == "EXCLUDE_SINGLE_FORWARD_WINDOW":
        return idxs
    if mode in {"EXCLUDE_BEST_TICKER", "EXCLUDE_WORST_TICKER", "EXCLUDE_BEST_DATE", "EXCLUDE_WORST_DATE"}:
        key = "_ticker" if "TICKER" in mode else "_as_of_date"
        totals: dict[str, float] = defaultdict(float)
        for idx, row in enumerate(rows):
            ret = forward_return(row, "10d")
            if ret is not None:
                totals[row.get(key, "")] += ret
        if totals:
            target = max(totals, key=totals.get) if "BEST" in mode else min(totals, key=totals.get)
            idxs = [idx for idx in idxs if rows[idx].get(key, "") != target]
    elif mode in {"EXCLUDE_TOP_1PCT_RETURNS", "EXCLUDE_BOTTOM_1PCT_RETURNS"}:
        vals = sorted(ret for row in rows if (ret := forward_return(row, "10d")) is not None)
        if vals:
            cut = vals[int(len(vals) * 0.99)] if "TOP" in mode else vals[int(len(vals) * 0.01)]
            idxs = [idx for idx in idxs if (forward_return(rows[idx], "10d") or 0) <= cut] if "TOP" in mode else [idx for idx in idxs if (forward_return(rows[idx], "10d") or 0) >= cut]
    elif mode in {"EXCLUDE_RISK_ON", "EXCLUDE_RISK_OFF", "EXCLUDE_NEUTRAL"}:
        target = mode.replace("EXCLUDE_", "").lower()
        idxs = [idx for idx in idxs if rows[idx].get("_regime") != target]
    return idxs


def take(values: list, idxs: list[int]) -> list:
    return [values[idx] for idx in idxs]


def classify_regime(imp: float | None, mono_imp: float | None, sample: str) -> str:
    if sample != "SUFFICIENT":
        return "INSUFFICIENT_SAMPLE"
    if imp is None:
        return "INSUFFICIENT_SAMPLE"
    if imp > 0.001 and (mono_imp or 0) >= 0:
        return "IMPROVES_IN_REGIME"
    if imp > 0:
        return "WEAK_IMPROVEMENT_IN_REGIME"
    if imp > -0.001:
        return "NO_IMPROVEMENT_IN_REGIME"
    return "HARMS_IN_REGIME"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    missing = [path.relative_to(ROOT).as_posix() for path in V21_016_INPUTS if not path.exists() or path.stat().st_size == 0]
    summary_016 = first(read_csv(OUT_DIR / "V21_016_RISK_REGIME_GATE_AND_MODIFIER_RESEARCH_PROTOTYPE_SUMMARY.csv"))
    decision_016 = first(read_csv(OUT_DIR / "V21_016_RISK_REGIME_GATE_AND_MODIFIER_DECISION.csv"))
    collapse = first(read_csv(OUT_DIR / "V21_016_EQUIVALENCE_COLLAPSE_ROOT_CAUSE_AUDIT.csv"))
    rows = load_primary_rows()
    baseline = [alpha_score(row) for row in rows]
    candidate = [risk_hard_gate_score(row) for row in rows]

    ingest_rows = [
        {"audit_item": "required_v21_016_artifacts_present", "audit_passed": yn(not missing), "observed_value": "|".join(missing) if missing else "ALL_PRESENT", "required_value": "TRUE", "research_only": "TRUE"},
        {"audit_item": "v21_016_decision_ingested", "audit_passed": yn(decision_016.get("risk_regime_decision") == "RISK_REGIME_MODIFIER_CANDIDATE_FOUND_RESEARCH_ONLY"), "observed_value": decision_016.get("risk_regime_decision", ""), "required_value": "RISK_REGIME_MODIFIER_CANDIDATE_FOUND_RESEARCH_ONLY", "research_only": "TRUE"},
        {"audit_item": "selected_variant_risk_hard_gate", "audit_passed": yn(decision_016.get("selected_variant") == "RISK_HARD_GATE_DIAGNOSTIC"), "observed_value": decision_016.get("selected_variant", ""), "required_value": "RISK_HARD_GATE_DIAGNOSTIC", "research_only": "TRUE"},
        {"audit_item": "recommended_next_stage_v21_022", "audit_passed": yn(decision_016.get("recommended_next_stage") == "V21.022_RISK_REGIME_MODIFIER_ROBUSTNESS_CONFIRMATION"), "observed_value": decision_016.get("recommended_next_stage", ""), "required_value": "V21.022_RISK_REGIME_MODIFIER_ROBUSTNESS_CONFIRMATION", "research_only": "TRUE"},
        {"audit_item": "equivalence_collapse_root_cause_captured", "audit_passed": yn(collapse.get("root_cause_classification") != ""), "observed_value": collapse.get("root_cause_classification", ""), "required_value": "CAPTURED", "research_only": "TRUE"},
        {"audit_item": "collapse_due_to_no_distinct_context_logic", "audit_passed": yn(collapse.get("root_cause_classification") == "COLLAPSE_DUE_TO_NO_DISTINCT_CONTEXT_LOGIC"), "observed_value": collapse.get("root_cause_classification", ""), "required_value": "COLLAPSE_DUE_TO_NO_DISTINCT_CONTEXT_LOGIC", "research_only": "TRUE"},
        {"audit_item": "official_use_false", "audit_passed": yn(decision_016.get("official_use_allowed") == "FALSE"), "observed_value": decision_016.get("official_use_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "official_ranking_readiness_false", "audit_passed": yn(decision_016.get("official_ranking_readiness_allowed") == "FALSE"), "observed_value": decision_016.get("official_ranking_readiness_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "official_weight_update_readiness_false", "audit_passed": yn(decision_016.get("official_weight_update_readiness_allowed") == "FALSE"), "observed_value": decision_016.get("official_weight_update_readiness_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "official_weight_update_blocked", "audit_passed": yn(decision_016.get("official_weight_update_blocked") == "TRUE"), "observed_value": decision_016.get("official_weight_update_blocked", ""), "required_value": "TRUE", "research_only": "TRUE"},
        {"audit_item": "data_trust_zero_alpha_ranking_contribution", "audit_passed": yn(summary_016.get("data_trust_alpha_contribution") == "0" and summary_016.get("data_trust_ranking_weight") == "0"), "observed_value": f"{summary_016.get('data_trust_ranking_weight','')}|{summary_016.get('data_trust_alpha_contribution','')}", "required_value": "0|0", "research_only": "TRUE"},
        {"audit_item": "official_ranking_mutation_count_zero", "audit_passed": yn(summary_016.get("official_ranking_mutation_count") == "0"), "observed_value": summary_016.get("official_ranking_mutation_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "official_factor_weight_mutation_count_zero", "audit_passed": yn(summary_016.get("official_factor_weight_mutation_count") == "0"), "observed_value": summary_016.get("official_factor_weight_mutation_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "official_recommendation_count_zero", "audit_passed": yn(summary_016.get("official_recommendation_count") == "0"), "observed_value": summary_016.get("official_recommendation_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "trade_action_count_zero", "audit_passed": yn(summary_016.get("trade_action_count") == "0"), "observed_value": summary_016.get("trade_action_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "shadow_activation_false", "audit_passed": yn(summary_016.get("shadow_activation") == "FALSE"), "observed_value": summary_016.get("shadow_activation", ""), "required_value": "FALSE", "research_only": "TRUE"},
    ]

    v16_scores = [row for row in read_csv(OUT_DIR / "V21_016_RISK_REGIME_PROTOTYPE_VARIANT_SCORE_OUTPUT.csv") if row.get("variant_name") == "RISK_HARD_GATE_DIAGNOSTIC"]
    v16_by_obs = {row.get("observation_id", ""): fnum(row.get("prototype_score")) for row in v16_scores}
    diffs = [abs(v16_by_obs[row["_id"]] - candidate[idx]) for idx, row in enumerate(rows) if row["_id"] in v16_by_obs and v16_by_obs[row["_id"]] is not None and candidate[idx] is not None]
    recon_status = "PASS" if diffs and max(diffs) < 1e-10 else "DOWNGRADED_RECONSTRUCTION_ERROR"
    recon_rows = [{
        "reconstruction_item": "RISK_HARD_GATE_DIAGNOSTIC",
        "matched_observation_count": len(diffs),
        "preserved_observation_count": len(rows),
        "risk_blocked_observation_count": sum(1 for row in rows if is_risk_blocked(row)),
        "mean_absolute_score_error": mean(diffs) if diffs else None,
        "max_absolute_score_error": max(diffs) if diffs else None,
        "reconstruction_status": recon_status,
        "data_trust_alpha_contribution": "0",
        "risk_additive_alpha_contribution": "0",
        "market_regime_additive_alpha_contribution": "0",
        "official_score_overwritten": "FALSE",
        "official_rank_overwritten": "FALSE",
        "research_only": "TRUE",
    }]

    candidate_ranks = rank_map(rows, candidate)
    baseline_ranks = rank_map(rows, baseline)
    compare_rows, stat_rows = [], []
    for window in WINDOWS:
        cstats = eval_scores(rows, candidate, window)
        bstats = eval_scores(rows, baseline, window)
        rank_deltas = [abs(candidate_ranks[idx] - baseline_ranks[idx]) for idx in candidate_ranks.keys() & baseline_ranks.keys()]
        compare_rows.append({
            "forward_return_window": window,
            **{f"candidate_{key}": value for key, value in cstats.items()},
            **{f"alpha_only_{key}": value for key, value in bstats.items()},
            "candidate_minus_alpha_only_top_quintile": (fnum(cstats.get("top_quintile_mean_return")) or 0) - (fnum(bstats.get("top_quintile_mean_return")) or 0),
            "candidate_minus_alpha_only_median": (fnum(cstats.get("median_top_quintile_return")) or 0) - (fnum(bstats.get("median_top_quintile_return")) or 0),
            "candidate_minus_alpha_only_downside_proxy": (fnum(cstats.get("downside_proxy")) or 0) - (fnum(bstats.get("downside_proxy")) or 0),
            "rank_turnover_vs_alpha_only": mean(rank_deltas) if rank_deltas else None,
            "official_use_allowed": "FALSE",
            "research_only": "TRUE",
        })
        spreads = paired_date_spreads(rows, candidate, baseline, window)
        t_stat, p_value = t_p(spreads)
        ci_low, ci_high = bootstrap_ci(spreads, SEED + len(window)) if spreads else (None, None)
        rng = random.Random(SEED + 100 + len(window))
        random_top_returns = []
        for idxs in by_date_indices(rows).values():
            pass
        groups = by_date_indices(rows)
        for _ in range(500):
            vals = []
            for idxs in groups.values():
                usable = [idx for idx in idxs if forward_return(rows[idx], window) is not None]
                if not usable:
                    continue
                q = max(1, math.ceil(len(usable) * 0.2))
                vals.extend(ret for ret in (forward_return(rows[idx], window) for idx in rng.sample(usable, min(q, len(usable)))) if ret is not None)
            if vals:
                random_top_returns.append(mean(vals))
        cand_top = fnum(cstats.get("top_quintile_mean_return"))
        universe_spread = fnum(cstats.get("top_minus_universe_spread"))
        stat_rows.append({
            "forward_return_window": window,
            "paired_date_count": len(spreads),
            "mean_candidate_minus_alpha_only": mean(spreads) if spreads else None,
            "t_stat": t_stat,
            "p_value": p_value,
            "bootstrap_ci_low": ci_low,
            "bootstrap_ci_high": ci_high,
            "probability_candidate_beats_alpha_only_by_date": sum(1 for spread in spreads if spread > 0) / len(spreads) if spreads else None,
            "probability_candidate_beats_equal_weight_universe": 1.0 if universe_spread is not None and universe_spread > 0 else 0.0 if universe_spread is not None else None,
            "random_trial_count": len(random_top_returns),
            "deterministic_seed_base": SEED,
            "candidate_percentile_versus_random": sum(1 for value in random_top_returns if cand_top is not None and cand_top > value) / len(random_top_returns) if random_top_returns else None,
            "sample_adequacy": cstats.get("sample_adequacy"),
            "research_only": "TRUE",
        })

    regime_rows = []
    regime_classes = []
    for regime_name in REGIMES:
        idxs = [idx for idx, row in enumerate(rows) if row.get("_regime") == regime_name]
        sub_rows, sub_c, sub_b = take(rows, idxs), take(candidate, idxs), take(baseline, idxs)
        cstats = eval_scores(sub_rows, sub_c, "10d")
        bstats = eval_scores(sub_rows, sub_b, "10d")
        imp = (fnum(cstats.get("top_quintile_mean_return")) or 0) - (fnum(bstats.get("top_quintile_mean_return")) or 0)
        mono_imp = (fnum(cstats.get("rank_monotonicity_score")) or 0) - (fnum(bstats.get("rank_monotonicity_score")) or 0)
        down_red = (fnum(bstats.get("downside_proxy")) or 0) - (fnum(cstats.get("downside_proxy")) or 0)
        rr = rank_map(sub_rows, sub_c)
        br = rank_map(sub_rows, sub_b)
        turnover = mean([abs(rr[idx] - br[idx]) for idx in rr.keys() & br.keys()]) if rr and br else None
        cls = classify_regime(imp, mono_imp, str(cstats.get("sample_adequacy", "")))
        regime_classes.append(cls)
        regime_rows.append({
            "regime_label": regime_name,
            "observation_count": len(sub_rows),
            "candidate_top_quintile_return": cstats.get("top_quintile_mean_return"),
            "alpha_only_top_quintile_return": bstats.get("top_quintile_mean_return"),
            "candidate_minus_alpha_only_improvement": imp,
            "monotonicity_improvement": mono_imp,
            "downside_reduction": down_red,
            "rank_turnover": turnover,
            "sample_adequacy": cstats.get("sample_adequacy"),
            "regime_result_classification": cls,
            "research_only": "TRUE",
        })
    sufficient_regimes = [cls for cls in regime_classes if cls != "INSUFFICIENT_SAMPLE"]
    if not sufficient_regimes:
        regime_class = "INSUFFICIENT_REGIME_DATA"
    elif all(cls in {"IMPROVES_IN_REGIME", "WEAK_IMPROVEMENT_IN_REGIME"} for cls in sufficient_regimes) and len(sufficient_regimes) == 3:
        regime_class = "ROBUST_ACROSS_AVAILABLE_REGIMES"
    elif sum(cls in {"IMPROVES_IN_REGIME", "WEAK_IMPROVEMENT_IN_REGIME"} for cls in sufficient_regimes) == 1:
        regime_class = "POSITIVE_ONLY_IN_ONE_REGIME"
    elif any(cls == "HARMS_IN_REGIME" for cls in sufficient_regimes):
        regime_class = "NEGATIVE_IN_KEY_REGIME"
    else:
        regime_class = "MIXED_BY_REGIME"
    for row in regime_rows:
        row["final_regime_robustness_classification"] = regime_class

    date_group_sizes = {date: len(idxs) for date, idxs in by_date_indices(rows).items()}
    fb_rows = []
    for window in WINDOWS:
        usable_returns = [ret for row in rows if (ret := forward_return(row, window)) is not None]
        winner_cut = sorted(usable_returns)[int(len(usable_returns) * 0.8)] if usable_returns else None
        downside_cut = sorted(usable_returns)[int(len(usable_returns) * 0.2)] if usable_returns else None
        blocked_high, unblocked_high = [], []
        blocked_winners = blocked_downside = 0
        for idx, row in enumerate(rows):
            ret = forward_return(row, window)
            if ret is None:
                continue
            alpha_rank = baseline_ranks.get(idx, 999999)
            high_rank = alpha_rank <= max(20, math.ceil(date_group_sizes.get(row.get("_as_of_date", ""), 0) * 0.2))
            if high_rank and is_risk_blocked(row):
                blocked_high.append(ret)
                if winner_cut is not None and ret >= winner_cut:
                    blocked_winners += 1
                if downside_cut is not None and ret <= downside_cut:
                    blocked_downside += 1
            elif high_rank:
                unblocked_high.append(ret)
        missed = blocked_winners / len(blocked_high) if blocked_high else None
        protected = blocked_downside / len(blocked_high) if blocked_high else None
        false_rate = missed if missed is not None else None
        if missed is None:
            behavior = "INCONCLUSIVE"
        elif protected is not None and protected > missed and protected >= 0.35:
            behavior = "PROTECTIVE"
        elif missed >= 0.35 and (protected or 0) < missed:
            behavior = "OVERLY_RESTRICTIVE"
        else:
            behavior = "MIXED"
        fb_rows.append({
            "forward_return_window": window,
            "blocked_high_rank_count": len(blocked_high),
            "blocked_future_winner_count": blocked_winners,
            "blocked_downside_avoided_count": blocked_downside,
            "blocked_high_rank_mean_return": mean(blocked_high) if blocked_high else None,
            "unblocked_high_rank_mean_return": mean(unblocked_high) if unblocked_high else None,
            "missed_winner_rate": missed,
            "downside_protection_rate": protected,
            "false_block_candidate_rate": false_rate,
            "risk_gate_behavior_classification": behavior,
            "official_gate_loosening_allowed": "FALSE",
            "research_only": "TRUE",
        })
    behavior_values = {row["risk_gate_behavior_classification"] for row in fb_rows}
    false_block_class = "OVERLY_RESTRICTIVE" if "OVERLY_RESTRICTIVE" in behavior_values else "PROTECTIVE" if behavior_values == {"PROTECTIVE"} else "INCONCLUSIVE" if behavior_values == {"INCONCLUSIVE"} else "MIXED"

    outlier_rows = []
    modes = ["ALL", "EXCLUDE_BEST_TICKER", "EXCLUDE_WORST_TICKER", "EXCLUDE_BEST_DATE", "EXCLUDE_WORST_DATE", "EXCLUDE_TOP_1PCT_RETURNS", "EXCLUDE_BOTTOM_1PCT_RETURNS", "EXCLUDE_RISK_ON", "EXCLUDE_RISK_OFF", "EXCLUDE_NEUTRAL"]
    all_imp = None
    fail_count = 0
    for mode in modes:
        idxs = subset_indices(rows, mode)
        sub_rows, sub_c, sub_b = take(rows, idxs), take(candidate, idxs), take(baseline, idxs)
        cstats = eval_scores(sub_rows, sub_c, "10d")
        bstats = eval_scores(sub_rows, sub_b, "10d")
        imp = (fnum(cstats.get("top_quintile_mean_return")) or 0) - (fnum(bstats.get("top_quintile_mean_return")) or 0)
        if mode == "ALL":
            all_imp = imp
        degraded = cstats.get("sample_adequacy") != "SUFFICIENT" or (all_imp is not None and all_imp > 0 and imp <= 0)
        fail_count += 1 if mode != "ALL" and degraded else 0
        outlier_rows.append({
            "dependency_test": mode,
            "candidate_minus_alpha_only_improvement": imp,
            "sample_adequacy": cstats.get("sample_adequacy"),
            "dependency_flag": "FAIL" if degraded else "PASS",
            "research_only": "TRUE",
        })
    window_imps = [(fnum(row["candidate_minus_alpha_only_top_quintile"]) or 0) for row in compare_rows]
    if fail_count >= 4 or sum(1 for value in window_imps if value > 0) <= 1:
        outlier_class = "HIGH_OUTLIER_DEPENDENCY"
    elif fail_count:
        outlier_class = "MODERATE_OUTLIER_DEPENDENCY"
    elif not rows:
        outlier_class = "INCONCLUSIVE_OUTLIER_DEPENDENCY"
    else:
        outlier_class = "LOW_OUTLIER_DEPENDENCY"
    for row in outlier_rows:
        row["overall_outlier_dependency_classification"] = outlier_class

    market_regime_available = collapse.get("market_regime_available") == "TRUE" or any(row.get("_regime") in REGIMES for row in rows)
    distinct_prior = collapse.get("distinct_context_logic_present_in_v21_020") == "TRUE"
    if not market_regime_available:
        context_status = "DISTINCT_CONTEXT_LOGIC_BLOCKED_BY_LABEL_QUALITY"
    elif not distinct_prior or regime_class in {"INSUFFICIENT_REGIME_DATA", "POSITIVE_ONLY_IN_ONE_REGIME"}:
        context_status = "DISTINCT_CONTEXT_LOGIC_PARTIAL"
    else:
        context_status = "DISTINCT_CONTEXT_LOGIC_CONFIRMED"
    context_rows = [{
        "context_logic_item": "market_regime_available",
        "observed_value": yn(market_regime_available),
        "context_logic_status": context_status,
        "research_only": "TRUE",
    }, {
        "context_logic_item": "distinct_context_logic_present_in_v21_020",
        "observed_value": yn(distinct_prior),
        "context_logic_status": context_status,
        "research_only": "TRUE",
    }, {
        "context_logic_item": "context_only_evaluation_without_global_equivalent_score",
        "observed_value": "BUILT_BY_REGIME_IN_V21_022",
        "context_logic_status": context_status,
        "research_only": "TRUE",
    }, {
        "context_logic_item": "global_score_collapse_avoided",
        "observed_value": "TRUE",
        "context_logic_status": context_status,
        "research_only": "TRUE",
    }]

    mean_imp = mean(window_imps) if window_imps else 0
    insufficient = bool(missing) or recon_status != "PASS" or any(row["audit_passed"] == "FALSE" for row in ingest_rows[:4])
    if insufficient:
        final_decision = "RISK_REGIME_CONFIRMATION_INCONCLUSIVE_REQUIRED_FIELDS_MISSING"
        next_stage = "V21.018_FACTOR_SCORE_DATA_CONTRACT_REPAIR"
    elif false_block_class == "OVERLY_RESTRICTIVE":
        final_decision = "RISK_HARD_GATE_OVERLY_RESTRICTIVE"
        next_stage = "V21.017_OVERHEAT_ENTRY_TIMING_AND_FALSE_BLOCK_REPAIR"
    elif outlier_class == "HIGH_OUTLIER_DEPENDENCY":
        final_decision = "RISK_HARD_GATE_OUTLIER_DEPENDENT"
        next_stage = "V21.015_NONLINEAR_FACTOR_INTERACTION_RESEARCH_PROTOTYPE"
    elif regime_class in {"POSITIVE_ONLY_IN_ONE_REGIME", "MIXED_BY_REGIME", "NEGATIVE_IN_KEY_REGIME", "INSUFFICIENT_REGIME_DATA"}:
        final_decision = "RISK_HARD_GATE_REGIME_FRAGILE"
        next_stage = "V21.024_MARKET_REGIME_CONTEXT_LOGIC_REPAIR" if market_regime_available and not distinct_prior else "V21.019_MORE_MATURED_OBSERVATION_ACCUMULATION_PLAN"
    elif mean_imp > 0.001:
        final_decision = "RISK_HARD_GATE_CONFIRMED_RESEARCH_ONLY"
        next_stage = "V21.023_RISK_HARD_GATE_SHADOW_RESEARCH_PLAN"
    elif mean_imp > 0:
        final_decision = "RISK_HARD_GATE_WEAK_BUT_PROMISING_RESEARCH_ONLY"
        next_stage = "V21.023_RISK_HARD_GATE_SHADOW_RESEARCH_PLAN"
    else:
        final_decision = "RISK_HARD_GATE_NOT_CONFIRMED"
        next_stage = "V21.019_MORE_MATURED_OBSERVATION_ACCUMULATION_PLAN"
    prefix = "PASS" if final_decision == "RISK_HARD_GATE_CONFIRMED_RESEARCH_ONLY" else "PARTIAL_PASS"
    final_status = f"{prefix}_V21_022_{final_decision}"

    readiness_rows = [{
        "readiness_item": "candidate_robust_enough_for_shadow_research_plan",
        "assessment": yn(final_decision in {"RISK_HARD_GATE_CONFIRMED_RESEARCH_ONLY", "RISK_HARD_GATE_WEAK_BUT_PROMISING_RESEARCH_ONLY"}),
        "candidate_too_fragile": yn(final_decision == "RISK_HARD_GATE_REGIME_FRAGILE"),
        "candidate_requires_risk_gate_repair": yn(final_decision == "RISK_HARD_GATE_OVERLY_RESTRICTIVE"),
        "candidate_requires_market_regime_label_repair": yn(context_status in {"DISTINCT_CONTEXT_LOGIC_PARTIAL", "DISTINCT_CONTEXT_LOGIC_BLOCKED_BY_LABEL_QUALITY"}),
        "candidate_requires_more_data": yn(regime_class == "INSUFFICIENT_REGIME_DATA"),
        "official_use_allowed": "FALSE",
        "research_only": "TRUE",
    }]
    decision_rows = [{
        "confirmation_decision": final_decision,
        "final_status": final_status,
        "official_use_allowed": "FALSE",
        "official_ranking_readiness_allowed": "FALSE",
        "official_weight_update_readiness_allowed": "FALSE",
        "official_weight_update_blocked": "TRUE",
        "recommended_next_stage": next_stage,
        "selected_recommended_next_stage": "TRUE",
        "research_only": "TRUE",
    }]
    summary = {
        "stage_name": STAGE_NAME,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "research_only": "TRUE",
        "final_status": final_status,
        "confirmation_decision": final_decision,
        "selected_variant": "RISK_HARD_GATE_DIAGNOSTIC",
        "v21_016_risk_regime_decision": decision_016.get("risk_regime_decision", ""),
        "equivalence_collapse_root_cause": collapse.get("root_cause_classification", ""),
        "regime_robustness_classification": regime_class,
        "risk_gate_behavior_classification": false_block_class,
        "outlier_dependency_classification": outlier_class,
        "context_logic_status": context_status,
        "official_use_allowed": "FALSE",
        "official_ranking_readiness_allowed": "FALSE",
        "official_weight_update_readiness_allowed": "FALSE",
        "official_weight_update_blocked": "TRUE",
        "recommended_next_stage": next_stage,
        "prototype_output_scope": "V21_022_RESEARCH_ONLY",
        "data_trust_ranking_weight": "0",
        "data_trust_alpha_contribution": "0",
        "risk_additive_alpha_contribution": "0",
        "market_regime_additive_alpha_contribution": "0",
        "official_ranking_mutation_count": "0",
        "official_factor_weight_mutation_count": "0",
        "official_recommendation_count": "0",
        "trade_action_count": "0",
        "shadow_activation": "FALSE",
    }

    write_csv(INGEST, ingest_rows, ["audit_item", "audit_passed", "observed_value", "required_value", "research_only"])
    write_csv(RECON, recon_rows, ["reconstruction_item", "matched_observation_count", "preserved_observation_count", "risk_blocked_observation_count", "mean_absolute_score_error", "max_absolute_score_error", "reconstruction_status", "data_trust_alpha_contribution", "risk_additive_alpha_contribution", "market_regime_additive_alpha_contribution", "official_score_overwritten", "official_rank_overwritten", "research_only"])
    write_csv(COMPARE, compare_rows, ["forward_return_window", "candidate_observation_count", "candidate_top5_mean_return", "candidate_top10_mean_return", "candidate_top20_mean_return", "candidate_top_quintile_mean_return", "candidate_median_top_quintile_return", "candidate_hit_rate", "candidate_top_minus_bottom_spread", "candidate_top_minus_universe_spread", "candidate_rank_monotonicity_score", "candidate_downside_proxy", "candidate_sample_adequacy", "alpha_only_observation_count", "alpha_only_top5_mean_return", "alpha_only_top10_mean_return", "alpha_only_top20_mean_return", "alpha_only_top_quintile_mean_return", "alpha_only_median_top_quintile_return", "alpha_only_hit_rate", "alpha_only_top_minus_bottom_spread", "alpha_only_top_minus_universe_spread", "alpha_only_rank_monotonicity_score", "alpha_only_downside_proxy", "alpha_only_sample_adequacy", "candidate_minus_alpha_only_top_quintile", "candidate_minus_alpha_only_median", "candidate_minus_alpha_only_downside_proxy", "rank_turnover_vs_alpha_only", "official_use_allowed", "research_only"])
    write_csv(STAT, stat_rows, ["forward_return_window", "paired_date_count", "mean_candidate_minus_alpha_only", "t_stat", "p_value", "bootstrap_ci_low", "bootstrap_ci_high", "probability_candidate_beats_alpha_only_by_date", "probability_candidate_beats_equal_weight_universe", "random_trial_count", "deterministic_seed_base", "candidate_percentile_versus_random", "sample_adequacy", "research_only"])
    write_csv(REGIME, regime_rows, ["regime_label", "observation_count", "candidate_top_quintile_return", "alpha_only_top_quintile_return", "candidate_minus_alpha_only_improvement", "monotonicity_improvement", "downside_reduction", "rank_turnover", "sample_adequacy", "regime_result_classification", "final_regime_robustness_classification", "research_only"])
    write_csv(FALSE_BLOCK, fb_rows, ["forward_return_window", "blocked_high_rank_count", "blocked_future_winner_count", "blocked_downside_avoided_count", "blocked_high_rank_mean_return", "unblocked_high_rank_mean_return", "missed_winner_rate", "downside_protection_rate", "false_block_candidate_rate", "risk_gate_behavior_classification", "official_gate_loosening_allowed", "research_only"])
    write_csv(OUTLIER, outlier_rows, ["dependency_test", "candidate_minus_alpha_only_improvement", "sample_adequacy", "dependency_flag", "overall_outlier_dependency_classification", "research_only"])
    write_csv(CONTEXT, context_rows, ["context_logic_item", "observed_value", "context_logic_status", "research_only"])
    write_csv(READINESS, readiness_rows, ["readiness_item", "assessment", "candidate_too_fragile", "candidate_requires_risk_gate_repair", "candidate_requires_market_regime_label_repair", "candidate_requires_more_data", "official_use_allowed", "research_only"])
    write_csv(DECISION, decision_rows, ["confirmation_decision", "final_status", "official_use_allowed", "official_ranking_readiness_allowed", "official_weight_update_readiness_allowed", "official_weight_update_blocked", "recommended_next_stage", "selected_recommended_next_stage", "research_only"])
    write_csv(SUMMARY, [summary], list(summary.keys()))

    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(f"""# V21.022 Risk Regime Modifier Robustness Confirmation Report

## Executive summary
This is a research-only robustness confirmation for the V21.016 RISK_HARD_GATE_DIAGNOSTIC candidate. Prototype scores and diagnostic ranks remain scoped to V21_022 research-only outputs.

## Final confirmation decision
{final_decision}

Final status: {final_status}

## V21.016 candidate ingestion
V21.016 decision: {decision_016.get('risk_regime_decision', '')}. Selected variant: {decision_016.get('selected_variant', '')}. Recommended next stage ingested: {decision_016.get('recommended_next_stage', '')}.

## Risk hard gate reconstruction audit
RISK_HARD_GATE_DIAGNOSTIC was reconstructed from FUNDAMENTAL, TECHNICAL, and STRATEGY alpha families with DATA_TRUST, RISK, and MARKET_REGIME excluded from additive alpha. Reconstruction status: {recon_status}.

## Candidate versus alpha-only comparison
See V21_022_CANDIDATE_VS_ALPHA_ONLY_COMPARISON.csv.

## Statistical confirmation
See V21_022_STATISTICAL_CONFIRMATION.csv. The deterministic random baseline uses seed base {SEED}.

## Regime robustness confirmation
Final regime robustness classification: {regime_class}.

## False-block and missed-winner audit
Risk gate behavior classification: {false_block_class}.

## Outlier dependency retest
Outlier dependency classification: {outlier_class}.

## Market regime distinct-context logic audit
Context logic status: {context_status}. This stage builds regime-separated context evaluation and does not collapse context logic into a single globally equivalent score.

## Research-only dry-run readiness assessment
See V21_022_RESEARCH_DRY_RUN_READINESS_ASSESSMENT.csv. This is not official readiness.

## DATA_TRUST zero-alpha confirmation
DATA_TRUST ranking contribution is 0 and alpha contribution is 0. DATA_TRUST is allowed only as gate or audit metadata.

## Explicit blocked actions
No official ranking mutation. No official factor weight mutation. No official recommendation. No trade action. No shadow activation. No official use. No official ranking readiness. No official weight update readiness. No production readiness. No real-book readiness.

## What this stage proves
It checks whether the selected risk hard gate is reproducible, improves alpha-only diagnostics, preserves observations, avoids over-blocking winners, and can be evaluated by regime as context-only research output.

## What this stage still cannot prove
It cannot approve official scoring, official ranking, official weights, official recommendations, trade actions, production use, real-book use, or shadow-policy activation.

## Recommended next stage
{next_stage}
""", encoding="utf-8")

    print(f"STAGE_NAME={STAGE_NAME}")
    print(f"final_status={final_status}")
    print(f"confirmation_decision={final_decision}")
    print("selected_variant=RISK_HARD_GATE_DIAGNOSTIC")
    print(f"recommended_next_stage={next_stage}")
    print("official_use_allowed=FALSE")
    print("official_ranking_readiness_allowed=FALSE")
    print("official_weight_update_readiness_allowed=FALSE")
    print("official_weight_update_blocked=TRUE")
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
