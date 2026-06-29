#!/usr/bin/env python
"""V21.027 market regime context retest with repaired labels.

Research-only retest using V21.026 DERIVED_RESEARCH_ONLY labels. This stage
does not mutate official score, rank, recommendation, trade, weight, market
regime, or shadow-policy files.
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


STAGE_NAME = "V21_027_MARKET_REGIME_CONTEXT_RETEST_WITH_REPAIRED_LABELS"
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"
OBS_SELECTION = OUT_DIR / "V21_005_OBSERVATION_SELECTION_AUDIT.csv"

V21_026_INPUTS = [
    OUT_DIR / "V21_026_V21_024_DECISION_INGEST_AUDIT.csv",
    OUT_DIR / "V21_026_EXISTING_REGIME_LABEL_FAILURE_AUDIT.csv",
    OUT_DIR / "V21_026_MARKET_REGIME_SOURCE_INVENTORY.csv",
    OUT_DIR / "V21_026_PROPOSED_REGIME_LABEL_CONTRACT.csv",
    OUT_DIR / "V21_026_DERIVED_RESEARCH_ONLY_REGIME_LABELS.csv",
    OUT_DIR / "V21_026_PIT_VALIDATION_AUDIT.csv",
    OUT_DIR / "V21_026_LABEL_COVERAGE_IMPROVEMENT_AUDIT.csv",
    OUT_DIR / "V21_026_SOURCE_CONTRACT_GAP_TABLE.csv",
    OUT_DIR / "V21_026_MARKET_REGIME_SOURCE_CONTRACT_REPAIR_DECISION.csv",
    OUT_DIR / "V21_026_MARKET_REGIME_SOURCE_CONTRACT_REPAIR_SUMMARY.csv",
    READ_CENTER_DIR / "V21_026_MARKET_REGIME_SOURCE_CONTRACT_REPAIR_REPORT.md",
]

INGEST = OUT_DIR / "V21_027_V21_026_DECISION_INGEST_AUDIT.csv"
COVERAGE = OUT_DIR / "V21_027_REPAIRED_LABEL_COVERAGE_AUDIT.csv"
UNIVERSE = OUT_DIR / "V21_027_CONTEXT_RETEST_UNIVERSE.csv"
PERF = OUT_DIR / "V21_027_REPAIRED_CONTEXT_RANK_BUCKET_PERFORMANCE.csv"
STABLE = OUT_DIR / "V21_027_STABLE_VS_UNSTABLE_REGIME_TEST.csv"
COMBO = OUT_DIR / "V21_027_TREND_COMBINATION_CONTEXT_TEST.csv"
RISK = OUT_DIR / "V21_027_RISK_GATE_BY_REPAIRED_CONTEXT.csv"
STAT = OUT_DIR / "V21_027_STATISTICAL_RANDOM_BASELINE_RETEST.csv"
GAPS = OUT_DIR / "V21_027_REMAINING_SOURCE_GAP_IMPACT_AUDIT.csv"
DECISION = OUT_DIR / "V21_027_CONTEXT_RETEST_DECISION.csv"
SUMMARY = OUT_DIR / "V21_027_MARKET_REGIME_CONTEXT_RETEST_WITH_REPAIRED_LABELS_SUMMARY.csv"
REPORT = READ_CENTER_DIR / "V21_027_MARKET_REGIME_CONTEXT_RETEST_WITH_REPAIRED_LABELS_REPORT.md"

WINDOWS = ["5d", "10d", "20d"]
SEED = 21027
MIN_N = 20
STAT_LABEL_LIMIT = 8
LABELS_TO_AUDIT = [
    "QQQ_uptrend", "QQQ_downtrend", "QQQ_neutral",
    "SPY_uptrend", "SPY_downtrend", "SPY_neutral",
    "sector_uptrend", "sector_downtrend", "sector_neutral",
    "semiconductor_uptrend", "semiconductor_downtrend", "semiconductor_neutral",
    "stable_regime_window", "unstable_regime_window",
    "regime_transition_risk", "no_regime_transition_risk", "no_regime_conflict_flag",
    "risk_on", "risk_off", "neutral",
]
COMBINATIONS = [
    ("QQQ_uptrend+SPY_uptrend", ["QQQ_uptrend", "SPY_uptrend"]),
    ("QQQ_downtrend+SPY_downtrend", ["QQQ_downtrend", "SPY_downtrend"]),
    ("semiconductor_uptrend+QQQ_uptrend", ["semiconductor_uptrend", "QQQ_uptrend"]),
    ("semiconductor_downtrend+QQQ_downtrend", ["semiconductor_downtrend", "QQQ_downtrend"]),
    ("sector_uptrend+SPY_uptrend", ["sector_uptrend", "SPY_uptrend"]),
    ("sector_downtrend+SPY_downtrend", ["sector_downtrend", "SPY_downtrend"]),
    ("QQQ_uptrend+stable_regime_window", ["QQQ_uptrend", "stable_regime_window"]),
    ("QQQ_downtrend+unstable_regime_window", ["QQQ_downtrend", "unstable_regime_window"]),
    ("semiconductor_uptrend+stable_regime_window", ["semiconductor_uptrend", "stable_regime_window"]),
    ("semiconductor_downtrend+unstable_regime_window", ["semiconductor_downtrend", "unstable_regime_window"]),
]


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


def alpha_score(row: dict[str, str]) -> float | None:
    vals = [family_score(row, fam) for fam in ["FUNDAMENTAL", "TECHNICAL", "STRATEGY"]]
    vals = [value for value in vals if value is not None]
    return mean(vals) if vals else None


def risk_gate_score(row: dict[str, str]) -> float | None:
    alpha = alpha_score(row)
    risk = family_score(row, "RISK")
    if alpha is None:
        return None
    return alpha - 1.0 if risk is not None and risk < 0.35 else alpha


def risk_blocked(row: dict[str, str]) -> bool:
    risk = family_score(row, "RISK")
    return risk is not None and risk < 0.35


def forward_return(row: dict[str, str], window: str) -> float | None:
    return fnum(row.get(f"forward_return_{window}") or field(row, [f"forward_return_{window}"]))


def load_primary_rows() -> list[dict[str, str]]:
    selection = [row for row in read_csv(OBS_SELECTION) if row.get("selection_status") == "USABLE_PRIMARY" and row.get("maturity_status") == "MATURED"]
    wanted: dict[str, set[int]] = defaultdict(set)
    selected: dict[tuple[str, int], dict[str, str]] = {}
    for row in selection:
        source, number = row.get("source_artifact", ""), fint(row.get("row_number"))
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
                merged["_baseline_rank"] = sel.get("rank", "")
                merged["_baseline_score"] = sel.get("score", "")
                merged["_available_forward_windows"] = sel.get("available_forward_windows", "")
                output.append(merged)
    return output


def group_indices(rows: list[dict[str, str]], key_fields: tuple[str, ...]) -> dict[tuple[str, ...], list[int]]:
    groups: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for idx, row in enumerate(rows):
        groups[tuple(row.get(key, "") for key in key_fields)].append(idx)
    return groups


def rank_map(rows: list[dict[str, str]], scores: list[float | None], keys: tuple[str, ...]) -> dict[int, int]:
    ranks = {}
    for idxs in group_indices(rows, keys).values():
        usable = [(idx, scores[idx]) for idx in idxs if scores[idx] is not None]
        for rank, (idx, _score) in enumerate(sorted(usable, key=lambda item: item[1], reverse=True), start=1):
            ranks[idx] = rank
    return ranks


def eval_ranked(rows: list[dict[str, str]], scores: list[float | None], window: str, keys: tuple[str, ...]) -> dict[str, object]:
    usable = [(idx, score) for idx, score in enumerate(scores) if score is not None and forward_return(rows[idx], window) is not None]
    if len(usable) < MIN_N:
        return {"observation_count": len(usable), "sample_adequacy": "INSUFFICIENT_SAMPLE"}
    buckets: dict[str, list[float]] = defaultdict(list)
    spreads_tb, spreads_tu, monos = [], [], []
    for idxs in group_indices(rows, keys).values():
        pairs = [(idx, scores[idx]) for idx in idxs if scores[idx] is not None and forward_return(rows[idx], window) is not None]
        if not pairs:
            continue
        ordered = sorted(pairs, key=lambda item: item[1], reverse=True)
        n = len(ordered)
        q = max(1, math.ceil(n * 0.2))
        defs = {"TOP_5": ordered[:5], "TOP_10": ordered[:10], "TOP_20": ordered[:20], "TOP_QUINTILE": ordered[:q], "BOTTOM_QUINTILE": ordered[-q:]}
        for bucket, vals in defs.items():
            buckets[bucket].extend(ret for ret in (forward_return(rows[idx], window) for idx, _ in vals) if ret is not None)
        top = [ret for ret in (forward_return(rows[idx], window) for idx, _ in defs["TOP_QUINTILE"]) if ret is not None]
        bottom = [ret for ret in (forward_return(rows[idx], window) for idx, _ in defs["BOTTOM_QUINTILE"]) if ret is not None]
        universe = [ret for ret in (forward_return(rows[idx], window) for idx, _ in ordered) if ret is not None]
        if top and bottom:
            spreads_tb.append(mean(top) - mean(bottom))
        if top and universe:
            spreads_tu.append(mean(top) - mean(universe))
        qmeans = []
        for qi in range(5):
            lo = math.floor(n * qi / 5)
            hi = math.floor(n * (qi + 1) / 5) if qi < 4 else n
            vals = [ret for ret in (forward_return(rows[idx], window) for idx, _ in ordered[lo:hi]) if ret is not None]
            qmeans.append(mean(vals) if vals else None)
        comps = [(qmeans[i], qmeans[i + 1]) for i in range(4) if qmeans[i] is not None and qmeans[i + 1] is not None]
        if comps:
            monos.append((len(comps) - sum(1 for left, right in comps if left < right)) / len(comps))
    topq = buckets["TOP_QUINTILE"]
    return {
        "observation_count": len(usable),
        "top5_mean_return": mean(buckets["TOP_5"]) if buckets["TOP_5"] else None,
        "top5_median_return": median(buckets["TOP_5"]) if buckets["TOP_5"] else None,
        "top10_mean_return": mean(buckets["TOP_10"]) if buckets["TOP_10"] else None,
        "top10_median_return": median(buckets["TOP_10"]) if buckets["TOP_10"] else None,
        "top20_mean_return": mean(buckets["TOP_20"]) if buckets["TOP_20"] else None,
        "top20_median_return": median(buckets["TOP_20"]) if buckets["TOP_20"] else None,
        "top_quintile_mean_return": mean(topq) if topq else None,
        "top_quintile_median_return": median(topq) if topq else None,
        "hit_rate": sum(1 for value in topq if value > 0) / len(topq) if topq else None,
        "top_minus_bottom_spread": mean(spreads_tb) if spreads_tb else None,
        "top_minus_universe_spread": mean(spreads_tu) if spreads_tu else None,
        "rank_monotonicity_score": mean(monos) if monos else None,
        "sample_adequacy": "SUFFICIENT",
    }


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
    samples = [mean(values[rng.randrange(len(values))] for _ in values) for _ in range(500)]
    samples.sort()
    return samples[12], samples[487]


def paired_spreads(rows: list[dict[str, str]], left: list[float | None], right: list[float | None], window: str) -> list[float]:
    spreads = []
    for idxs in group_indices(rows, ("_as_of_date",)).values():
        def top(scores: list[float | None]) -> list[float]:
            pairs = [(idx, scores[idx]) for idx in idxs if scores[idx] is not None and forward_return(rows[idx], window) is not None]
            ordered = sorted(pairs, key=lambda item: item[1], reverse=True)
            q = max(1, math.ceil(len(ordered) * 0.2))
            return [ret for ret in (forward_return(rows[idx], window) for idx, _ in ordered[:q]) if ret is not None]
        lvals, rvals = top(left), top(right)
        if lvals and rvals:
            spreads.append(mean(lvals) - mean(rvals))
    return spreads


def build_context_rows(rows: list[dict[str, str]], date_labels: dict[str, set[str]], label_filter: str | None = None) -> list[dict[str, str]]:
    out = []
    for row in rows:
        labels = sorted(date_labels.get(row["_as_of_date"], set()))
        if label_filter:
            labels = [label for label in labels if label == label_filter]
        for label in labels:
            r = dict(row)
            r["_context_label"] = label
            out.append(r)
    return out


def risk_gate_rows(label: str, rows: list[dict[str, str]], alpha_scores: list[float | None], window: str) -> dict[str, object]:
    alpha_ranks = rank_map(rows, alpha_scores, ("_as_of_date",))
    rets = [forward_return(row, window) for row in rows if forward_return(row, window) is not None]
    if len(rets) < MIN_N:
        return {"context_label": label, "forward_return_window": window, "blocked_high_rank_count": 0, "unblocked_high_rank_count": 0, "risk_gate_context_classification": "INSUFFICIENT_SAMPLE"}
    winner_cut = sorted(rets)[int(len(rets) * 0.8)]
    downside_cut = sorted(rets)[int(len(rets) * 0.2)]
    blocked, unblocked = [], []
    bw = bd = 0
    for idx, row in enumerate(rows):
        ret = forward_return(row, window)
        if ret is None:
            continue
        high = alpha_ranks.get(idx, 999999) <= max(5, math.ceil(len(rows) * 0.2))
        if high and risk_blocked(row):
            blocked.append(ret)
            bw += 1 if ret >= winner_cut else 0
            bd += 1 if ret <= downside_cut else 0
        elif high:
            unblocked.append(ret)
    missed = bw / len(blocked) if blocked else None
    protected = bd / len(blocked) if blocked else None
    if missed is None:
        cls = "INSUFFICIENT_SAMPLE"
    elif protected is not None and protected > missed and protected >= 0.35:
        cls = "PROTECTIVE_IN_CONTEXT"
    elif missed >= 0.35 and (protected or 0) < missed:
        cls = "OVERLY_RESTRICTIVE_IN_CONTEXT"
    elif protected == 0 and missed == 0:
        cls = "NOT_USEFUL_IN_CONTEXT"
    else:
        cls = "MIXED_IN_CONTEXT"
    return {
        "context_label": label,
        "forward_return_window": window,
        "blocked_high_rank_count": len(blocked),
        "unblocked_high_rank_count": len(unblocked),
        "blocked_mean_return": mean(blocked) if blocked else None,
        "unblocked_mean_return": mean(unblocked) if unblocked else None,
        "missed_winner_rate": missed,
        "downside_protection_rate": protected,
        "risk_gate_context_classification": cls,
        "research_only": "TRUE",
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    missing = [path.relative_to(ROOT).as_posix() for path in V21_026_INPUTS if not path.exists() or path.stat().st_size == 0]
    decision_026 = first(read_csv(OUT_DIR / "V21_026_MARKET_REGIME_SOURCE_CONTRACT_REPAIR_DECISION.csv"))
    summary_026 = first(read_csv(OUT_DIR / "V21_026_MARKET_REGIME_SOURCE_CONTRACT_REPAIR_SUMMARY.csv"))
    derived = read_csv(OUT_DIR / "V21_026_DERIVED_RESEARCH_ONLY_REGIME_LABELS.csv")
    gaps_026 = read_csv(OUT_DIR / "V21_026_SOURCE_CONTRACT_GAP_TABLE.csv")
    rows = load_primary_rows()
    labels_by_date: dict[str, set[str]] = defaultdict(set)
    label_meta: dict[str, dict[str, str]] = {}
    for row in derived:
        if row.get("label_status") == "DERIVED_RESEARCH_ONLY" and row.get("research_only") == "TRUE":
            labels_by_date[row.get("as_of_date", "")].add(row.get("label_name", ""))
            label_meta[row.get("label_name", "")] = row
    forbidden_labels = {"high_vix", "low_vix", "normal_vix", "FOMC_window", "CPI_window", "NFP_window", "earnings_season_window"}
    fabricated_forbidden = bool(forbidden_labels & set(label_meta))

    ingest_rows = [
        {"audit_item": "required_v21_026_artifacts_present", "audit_passed": yn(not missing), "observed_value": "|".join(missing) if missing else "ALL_PRESENT", "required_value": "TRUE", "research_only": "TRUE"},
        {"audit_item": "v21_026_decision_ingested", "audit_passed": yn(decision_026.get("source_contract_repair_decision") == "MARKET_REGIME_SOURCE_CONTRACT_PARTIAL_REPAIR_READY_FOR_CONTEXT_RETEST"), "observed_value": decision_026.get("source_contract_repair_decision", ""), "required_value": "MARKET_REGIME_SOURCE_CONTRACT_PARTIAL_REPAIR_READY_FOR_CONTEXT_RETEST", "research_only": "TRUE"},
        {"audit_item": "recommended_next_stage_v21_027", "audit_passed": yn(decision_026.get("recommended_next_stage") == "V21.027_MARKET_REGIME_CONTEXT_RETEST_WITH_REPAIRED_LABELS"), "observed_value": decision_026.get("recommended_next_stage", ""), "required_value": "V21.027_MARKET_REGIME_CONTEXT_RETEST_WITH_REPAIRED_LABELS", "research_only": "TRUE"},
        {"audit_item": "derived_research_only_labels_generated", "audit_passed": yn(bool(derived) and all(row.get("label_status") == "DERIVED_RESEARCH_ONLY" for row in derived)), "observed_value": str(len(derived)), "required_value": ">0_AND_DERIVED_RESEARCH_ONLY", "research_only": "TRUE"},
        {"audit_item": "pit_validation_failures_zero", "audit_passed": yn(summary_026.get("pit_validation_fail_count") == "0"), "observed_value": summary_026.get("pit_validation_fail_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "vix_and_event_labels_not_fabricated", "audit_passed": yn(not fabricated_forbidden), "observed_value": "|".join(sorted(forbidden_labels & set(label_meta))) if fabricated_forbidden else "NOT_FABRICATED", "required_value": "NOT_FABRICATED", "research_only": "TRUE"},
        {"audit_item": "official_use_false", "audit_passed": yn(summary_026.get("official_use_allowed") == "FALSE"), "observed_value": summary_026.get("official_use_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "official_ranking_readiness_false", "audit_passed": yn(summary_026.get("official_ranking_readiness_allowed") == "FALSE"), "observed_value": summary_026.get("official_ranking_readiness_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "official_weight_update_readiness_false", "audit_passed": yn(summary_026.get("official_weight_update_readiness_allowed") == "FALSE"), "observed_value": summary_026.get("official_weight_update_readiness_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "official_weight_update_blocked", "audit_passed": yn(summary_026.get("official_weight_update_blocked") == "TRUE"), "observed_value": summary_026.get("official_weight_update_blocked", ""), "required_value": "TRUE", "research_only": "TRUE"},
        {"audit_item": "data_trust_zero_alpha_ranking_contribution", "audit_passed": yn(summary_026.get("data_trust_alpha_contribution") == "0" and summary_026.get("data_trust_ranking_weight") == "0"), "observed_value": f"{summary_026.get('data_trust_ranking_weight','')}|{summary_026.get('data_trust_alpha_contribution','')}", "required_value": "0|0", "research_only": "TRUE"},
        {"audit_item": "risk_additive_alpha_contribution_zero", "audit_passed": yn(summary_026.get("risk_additive_alpha_contribution") == "0"), "observed_value": summary_026.get("risk_additive_alpha_contribution", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "market_regime_additive_alpha_contribution_zero", "audit_passed": yn(summary_026.get("market_regime_additive_alpha_contribution") == "0"), "observed_value": summary_026.get("market_regime_additive_alpha_contribution", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "official_ranking_mutation_count_zero", "audit_passed": yn(summary_026.get("official_ranking_mutation_count") == "0"), "observed_value": summary_026.get("official_ranking_mutation_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "official_factor_weight_mutation_count_zero", "audit_passed": yn(summary_026.get("official_factor_weight_mutation_count") == "0"), "observed_value": summary_026.get("official_factor_weight_mutation_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "official_recommendation_count_zero", "audit_passed": yn(summary_026.get("official_recommendation_count") == "0"), "observed_value": summary_026.get("official_recommendation_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "trade_action_count_zero", "audit_passed": yn(summary_026.get("trade_action_count") == "0"), "observed_value": summary_026.get("trade_action_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "shadow_activation_false", "audit_passed": yn(summary_026.get("shadow_activation") == "FALSE"), "observed_value": summary_026.get("shadow_activation", ""), "required_value": "FALSE", "research_only": "TRUE"},
    ]

    coverage_rows = []
    for label in LABELS_TO_AUDIT:
        dates = {date for date, labels in labels_by_date.items() if label in labels}
        obs = [row for row in rows if row["_as_of_date"] in dates]
        windows = [w for w in WINDOWS if sum(1 for row in obs if forward_return(row, w) is not None) >= MIN_N]
        coverage_rows.append({
            "label_name": label,
            "observation_count": len(obs),
            "distinct_as_of_date_count": len(dates),
            "distinct_ticker_count": len({row["_ticker"] for row in obs}),
            "available_forward_return_windows": "|".join(windows),
            "pit_eligibility": label_meta.get(label, {}).get("point_in_time_eligible", "FALSE") if dates else "FALSE",
            "sample_adequacy": "SUFFICIENT" if windows else "INSUFFICIENT_SAMPLE",
            "label_source_status": "DERIVED_RESEARCH_ONLY" if label in label_meta else "MISSING_NOT_FABRICATED",
            "derived_research_only": yn(label in label_meta),
            "research_only": "TRUE",
        })

    universe_rows = []
    all_alpha = [alpha_score(row) for row in rows]
    all_gate = [risk_gate_score(row) for row in rows]
    global_rank = rank_map(rows, all_alpha, ("_as_of_date",))
    id_to_global_rank = {row["_id"]: global_rank.get(idx, "") for idx, row in enumerate(rows)}
    for label in LABELS_TO_AUDIT:
        ctx_rows = build_context_rows(rows, labels_by_date, label)
        ctx_alpha = [alpha_score(row) for row in ctx_rows]
        ctx_gate = [risk_gate_score(row) for row in ctx_rows]
        ctx_alpha_rank = rank_map(ctx_rows, ctx_alpha, ("_as_of_date", "_context_label"))
        ctx_gate_rank = rank_map(ctx_rows, ctx_gate, ("_as_of_date", "_context_label"))
        for idx, row in enumerate(ctx_rows):
            if len(universe_rows) < 60000:
                universe_rows.append({
                    "observation_id": row["_id"],
                    "as_of_date": row["_as_of_date"],
                    "ticker": row["_ticker"],
                    "repaired_context_label": label,
                    "label_status": "DERIVED_RESEARCH_ONLY",
                    "GLOBAL_ALPHA_ONLY_RANK": id_to_global_rank.get(row["_id"], ""),
                    "WITHIN_REPAIRED_LABEL_ALPHA_ONLY_RANK": ctx_alpha_rank.get(idx, ""),
                    "WITHIN_REPAIRED_LABEL_RISK_GATED_RANK": ctx_gate_rank.get(idx, ""),
                    "GLOBAL_BASELINE_RANK": row.get("_baseline_rank", ""),
                    "global_market_regime_adjusted_score_used": "FALSE",
                    "research_only": "TRUE",
                })

    coverage_by_label = {row["label_name"]: row for row in coverage_rows}
    stat_labels = [label for label in LABELS_TO_AUDIT if coverage_by_label.get(label, {}).get("sample_adequacy") == "SUFFICIENT"][:STAT_LABEL_LIMIT]
    perf_rows = []
    risk_rows = []
    stat_rows = []
    for label in LABELS_TO_AUDIT:
        ctx_rows = build_context_rows(rows, labels_by_date, label)
        if not ctx_rows:
            continue
        ctx_alpha = [alpha_score(row) for row in ctx_rows]
        ctx_gate = [risk_gate_score(row) for row in ctx_rows]
        ctx_base = [fnum(row.get("_baseline_score")) for row in ctx_rows]
        ranks_global = rank_map(ctx_rows, ctx_alpha, ("_as_of_date",))
        for window in WINDOWS:
            for variant, scores, keys in [
                ("GLOBAL_ALPHA_ONLY_RANK", ctx_alpha, ("_as_of_date",)),
                ("WITHIN_REPAIRED_LABEL_ALPHA_ONLY_RANK", ctx_alpha, ("_as_of_date", "_context_label")),
                ("WITHIN_REPAIRED_LABEL_RISK_GATED_RANK", ctx_gate, ("_as_of_date", "_context_label")),
                ("GLOBAL_BASELINE_RANK", ctx_base, ("_as_of_date",)),
            ]:
                stats = eval_ranked(ctx_rows, scores, window, keys)
                ranks = rank_map(ctx_rows, scores, keys)
                turnover = mean([abs(ranks[i] - ranks_global[i]) for i in ranks.keys() & ranks_global.keys()]) if ranks and ranks_global else None
                perf_rows.append({"context_label": label, "forward_return_window": window, "rank_type": variant, **stats, "rank_turnover_vs_global_alpha_only": turnover, "global_market_regime_adjusted_score_used": "FALSE", "research_only": "TRUE"})
            risk_rows.append(risk_gate_rows(label, ctx_rows, ctx_alpha, window))
            if label in stat_labels:
                spreads_alpha = paired_spreads(ctx_rows, ctx_alpha, ctx_alpha, window)
                spreads_gate = paired_spreads(ctx_rows, ctx_gate, ctx_alpha, window)
                date_returns = []
                for idxs in group_indices(ctx_rows, ("_as_of_date",)).values():
                    usable = [i for i in idxs if forward_return(ctx_rows[i], window) is not None]
                    date_returns.append([forward_return(ctx_rows[i], window) for i in usable])
                for comp, spreads, scores in [
                    ("within_label_alpha_vs_global_alpha", spreads_alpha, ctx_alpha),
                    ("within_label_risk_gated_vs_within_label_alpha", spreads_gate, ctx_gate),
                ]:
                    t, p = t_p(spreads)
                    lo, hi = bootstrap_ci(spreads, SEED + len(label) + len(window)) if spreads else (None, None)
                    rng = random.Random(SEED + len(label) + len(window) + len(comp))
                    random_vals = []
                    for _ in range(500):
                        vals = []
                        for returns in date_returns:
                            usable_returns = [ret for ret in returns if ret is not None]
                            if usable_returns:
                                q = max(1, math.ceil(len(usable_returns) * 0.2))
                                vals.extend(rng.sample(usable_returns, min(q, len(usable_returns))))
                        if vals:
                            random_vals.append(mean(vals))
                    actual = fnum(eval_ranked(ctx_rows, scores, window, ("_as_of_date", "_context_label")).get("top_quintile_mean_return"))
                    stat_rows.append({"context_label": label, "forward_return_window": window, "comparison_name": comp, "paired_group_count": len(spreads), "mean_improvement": mean(spreads) if spreads else None, "t_stat": t, "p_value": p, "bootstrap_ci_low": lo, "bootstrap_ci_high": hi, "deterministic_seed_base": SEED, "random_trial_count": len(random_vals), "actual_percentile_versus_random": sum(1 for v in random_vals if actual is not None and actual > v) / len(random_vals) if random_vals else None, "sample_adequacy": "SUFFICIENT" if len(spreads) >= 2 else "INSUFFICIENT_SAMPLE", "research_only": "TRUE"})

    stable_rows = []
    for label in ["stable_regime_window", "unstable_regime_window", "no_regime_transition_risk", "regime_transition_risk"]:
        ctx_rows = build_context_rows(rows, labels_by_date, label)
        ctx_alpha = [alpha_score(row) for row in ctx_rows]
        ctx_gate = [risk_gate_score(row) for row in ctx_rows]
        for window in WINDOWS:
            a = eval_ranked(ctx_rows, ctx_alpha, window, ("_as_of_date", "_context_label"))
            g = eval_ranked(ctx_rows, ctx_gate, window, ("_as_of_date", "_context_label"))
            stable_rows.append({"context_label": label, "forward_return_window": window, "alpha_top_quintile_return": a.get("top_quintile_mean_return"), "risk_gated_top_quintile_return": g.get("top_quintile_mean_return"), "risk_gate_minus_alpha": (fnum(g.get("top_quintile_mean_return")) or 0) - (fnum(a.get("top_quintile_mean_return")) or 0), "signals_materially_stronger_in_stable_regime": yn(label.startswith("stable") and (fnum(a.get("top_quintile_mean_return")) or 0) > 0), "risk_gate_more_useful_in_unstable_regime": yn(label.startswith("unstable") and ((fnum(g.get("top_quintile_mean_return")) or 0) > (fnum(a.get("top_quintile_mean_return")) or 0))), "sample_adequacy": a.get("sample_adequacy"), "research_only": "TRUE"})

    combo_rows = []
    for combo_name, required in COMBINATIONS:
        dates = {date for date, labels in labels_by_date.items() if all(req in labels for req in required)}
        ctx_rows = [row for row in rows if row["_as_of_date"] in dates]
        ctx_alpha = [alpha_score(row) for row in ctx_rows]
        ctx_gate = [risk_gate_score(row) for row in ctx_rows]
        for window in WINDOWS:
            a = eval_ranked(ctx_rows, ctx_alpha, window, ("_as_of_date",))
            g = eval_ranked(ctx_rows, ctx_gate, window, ("_as_of_date",))
            combo_rows.append({"context_combination": combo_name, "forward_return_window": window, "observation_count": len(ctx_rows), "distinct_as_of_date_count": len(dates), "distinct_ticker_count": len({row['_ticker'] for row in ctx_rows}), "alpha_top10_mean_return": a.get("top10_mean_return"), "alpha_top20_mean_return": a.get("top20_mean_return"), "risk_gated_top10_mean_return": g.get("top10_mean_return"), "risk_gated_top20_mean_return": g.get("top20_mean_return"), "risk_gated_minus_alpha_top20": (fnum(g.get("top20_mean_return")) or 0) - (fnum(a.get("top20_mean_return")) or 0), "monotonicity_score": a.get("rank_monotonicity_score"), "sample_adequacy": a.get("sample_adequacy"), "research_only": "TRUE"})
            risk_rows.append(risk_gate_rows(combo_name, ctx_rows, ctx_alpha, window))

    gap_rows = []
    for gap in gaps_026:
        labels = gap.get("affected_label", "")
        severity = gap.get("severity", "")
        gap_rows.append({"source_gap": gap.get("missing_source", ""), "affected_labels": labels, "affected_conclusions": "volatility/event-conditioned conclusions unavailable" if any(x in labels for x in ["vix", "FOMC", "CPI", "NFP", "earnings"]) else "broad regime metadata remains ambiguous", "severity": severity, "context_retest_can_proceed_without_it": "FALSE" if severity == "HIGH" else "TRUE", "next_stage_must_be_data_producer": "TRUE" if severity == "HIGH" else "FALSE", "cannot_fabricate": gap.get("cannot_fabricate", "TRUE"), "research_only": "TRUE"})

    adequate_perf = [row for row in perf_rows if row.get("rank_type") == "WITHIN_REPAIRED_LABEL_ALPHA_ONLY_RANK" and row.get("sample_adequacy") == "SUFFICIENT"]
    positive = sum(1 for row in adequate_perf if (fnum(row.get("top_quintile_mean_return")) or 0) > 0)
    risk_overly = any(row.get("risk_gate_context_classification") == "OVERLY_RESTRICTIVE_IN_CONTEXT" for row in risk_rows)
    high_gap_blocks = any(row["next_stage_must_be_data_producer"] == "TRUE" for row in gap_rows)
    if missing or any(row["audit_passed"] == "FALSE" for row in ingest_rows[:6]):
        retest_decision = "REPAIRED_LABEL_CONTEXT_RETEST_INCONCLUSIVE_REQUIRED_FIELDS_MISSING"
        next_stage = "V21.028_MARKET_REGIME_DATA_PRODUCER_IMPLEMENTATION"
    elif not adequate_perf:
        retest_decision = "REPAIRED_LABEL_CONTEXT_RETEST_INCONCLUSIVE_REQUIRED_FIELDS_MISSING"
        next_stage = "V21.019_MORE_MATURED_OBSERVATION_ACCUMULATION_PLAN"
    elif risk_overly:
        retest_decision = "REPAIRED_LABEL_CONTEXT_SIGNAL_MIXED_OR_REGIME_DEPENDENT"
        next_stage = "V21.017_OVERHEAT_ENTRY_TIMING_AND_FALSE_BLOCK_REPAIR"
    elif high_gap_blocks and positive < max(1, len(adequate_perf) // 3):
        retest_decision = "REPAIRED_LABEL_CONTEXT_RETEST_BLOCKED_BY_SOURCE_GAPS"
        next_stage = "V21.028_MARKET_REGIME_DATA_PRODUCER_IMPLEMENTATION"
    elif positive >= max(1, math.ceil(len(adequate_perf) * 0.7)):
        retest_decision = "REPAIRED_LABEL_CONTEXT_SIGNAL_CONFIRMED_RESEARCH_ONLY"
        next_stage = "V21.025_WITHIN_REGIME_ALPHA_ONLY_AND_RISK_GATE_SHADOW_RESEARCH_PLAN"
    elif positive >= max(1, math.ceil(len(adequate_perf) * 0.45)):
        retest_decision = "REPAIRED_LABEL_CONTEXT_SIGNAL_WEAK_BUT_PROMISING"
        next_stage = "V21.025_WITHIN_REGIME_ALPHA_ONLY_AND_RISK_GATE_SHADOW_RESEARCH_PLAN"
    else:
        retest_decision = "REPAIRED_LABEL_CONTEXT_SIGNAL_MIXED_OR_REGIME_DEPENDENT"
        next_stage = "V21.015_NONLINEAR_FACTOR_INTERACTION_RESEARCH_PROTOTYPE"
    prefix = "PASS" if retest_decision == "REPAIRED_LABEL_CONTEXT_SIGNAL_CONFIRMED_RESEARCH_ONLY" else "PARTIAL_PASS"
    final_status = f"{prefix}_V21_027_{retest_decision}"
    decision_rows = [{"context_retest_decision": retest_decision, "final_status": final_status, "official_use_allowed": "FALSE", "official_ranking_readiness_allowed": "FALSE", "official_weight_update_readiness_allowed": "FALSE", "official_weight_update_blocked": "TRUE", "recommended_next_stage": next_stage, "selected_recommended_next_stage": "TRUE", "research_only": "TRUE"}]
    summary = {
        "stage_name": STAGE_NAME,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "research_only": "TRUE",
        "final_status": final_status,
        "context_retest_decision": retest_decision,
        "v21_026_source_contract_repair_decision": decision_026.get("source_contract_repair_decision", ""),
        "v21_026_recommended_next_stage": decision_026.get("recommended_next_stage", ""),
        "derived_research_only_label_count": len(derived),
        "adequate_context_count": len(adequate_perf),
        "positive_context_count": positive,
        "vix_and_event_labels_fabricated": yn(fabricated_forbidden),
        "single_global_market_regime_adjusted_score_used": "FALSE",
        "official_use_allowed": "FALSE",
        "official_ranking_readiness_allowed": "FALSE",
        "official_weight_update_readiness_allowed": "FALSE",
        "official_weight_update_blocked": "TRUE",
        "recommended_next_stage": next_stage,
        "prototype_output_scope": "V21_027_RESEARCH_ONLY",
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
    write_csv(COVERAGE, coverage_rows, ["label_name", "observation_count", "distinct_as_of_date_count", "distinct_ticker_count", "available_forward_return_windows", "pit_eligibility", "sample_adequacy", "label_source_status", "derived_research_only", "research_only"])
    write_csv(UNIVERSE, universe_rows, ["observation_id", "as_of_date", "ticker", "repaired_context_label", "label_status", "GLOBAL_ALPHA_ONLY_RANK", "WITHIN_REPAIRED_LABEL_ALPHA_ONLY_RANK", "WITHIN_REPAIRED_LABEL_RISK_GATED_RANK", "GLOBAL_BASELINE_RANK", "global_market_regime_adjusted_score_used", "research_only"])
    write_csv(PERF, perf_rows, ["context_label", "forward_return_window", "rank_type", "observation_count", "top5_mean_return", "top5_median_return", "top10_mean_return", "top10_median_return", "top20_mean_return", "top20_median_return", "top_quintile_mean_return", "top_quintile_median_return", "hit_rate", "top_minus_bottom_spread", "top_minus_universe_spread", "rank_monotonicity_score", "sample_adequacy", "rank_turnover_vs_global_alpha_only", "global_market_regime_adjusted_score_used", "research_only"])
    write_csv(STABLE, stable_rows, ["context_label", "forward_return_window", "alpha_top_quintile_return", "risk_gated_top_quintile_return", "risk_gate_minus_alpha", "signals_materially_stronger_in_stable_regime", "risk_gate_more_useful_in_unstable_regime", "sample_adequacy", "research_only"])
    write_csv(COMBO, combo_rows, ["context_combination", "forward_return_window", "observation_count", "distinct_as_of_date_count", "distinct_ticker_count", "alpha_top10_mean_return", "alpha_top20_mean_return", "risk_gated_top10_mean_return", "risk_gated_top20_mean_return", "risk_gated_minus_alpha_top20", "monotonicity_score", "sample_adequacy", "research_only"])
    write_csv(RISK, risk_rows, ["context_label", "forward_return_window", "blocked_high_rank_count", "unblocked_high_rank_count", "blocked_mean_return", "unblocked_mean_return", "missed_winner_rate", "downside_protection_rate", "risk_gate_context_classification", "research_only"])
    write_csv(STAT, stat_rows, ["context_label", "forward_return_window", "comparison_name", "paired_group_count", "mean_improvement", "t_stat", "p_value", "bootstrap_ci_low", "bootstrap_ci_high", "deterministic_seed_base", "random_trial_count", "actual_percentile_versus_random", "sample_adequacy", "research_only"])
    write_csv(GAPS, gap_rows, ["source_gap", "affected_labels", "affected_conclusions", "severity", "context_retest_can_proceed_without_it", "next_stage_must_be_data_producer", "cannot_fabricate", "research_only"])
    write_csv(DECISION, decision_rows, ["context_retest_decision", "final_status", "official_use_allowed", "official_ranking_readiness_allowed", "official_weight_update_readiness_allowed", "official_weight_update_blocked", "recommended_next_stage", "selected_recommended_next_stage", "research_only"])
    write_csv(SUMMARY, [summary], list(summary.keys()))

    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(f"""# V21.027 Market Regime Context Retest With Repaired Labels Report

## Executive summary
This research-only stage retests market regime context using V21.026 DERIVED_RESEARCH_ONLY labels. It does not create a single global market-regime-adjusted score and does not fabricate missing VIX, FOMC, CPI, NFP, or earnings-season labels.

## Final context retest decision
{retest_decision}

Final status: {final_status}

## V21.026 decision ingestion
V21.026 decision: {decision_026.get('source_contract_repair_decision', '')}. Recommended next stage: {decision_026.get('recommended_next_stage', '')}.

## Repaired label coverage audit
See V21_027_REPAIRED_LABEL_COVERAGE_AUDIT.csv.

## Context retest universe construction
The universe joins primary usable matured observations, alpha-only diagnostics, risk-gated diagnostics, repaired context labels, and forward returns. It distinguishes GLOBAL_ALPHA_ONLY_RANK, WITHIN_REPAIRED_LABEL_ALPHA_ONLY_RANK, WITHIN_REPAIRED_LABEL_RISK_GATED_RANK, and GLOBAL_BASELINE_RANK.

## Repaired-context rank bucket performance
See V21_027_REPAIRED_CONTEXT_RANK_BUCKET_PERFORMANCE.csv.

## Stable versus unstable regime test
See V21_027_STABLE_VS_UNSTABLE_REGIME_TEST.csv.

## Trend-combination context test
See V21_027_TREND_COMBINATION_CONTEXT_TEST.csv.

## Risk gate by repaired context
See V21_027_RISK_GATE_BY_REPAIRED_CONTEXT.csv.

## Statistical and random baseline retest
See V21_027_STATISTICAL_RANDOM_BASELINE_RETEST.csv. Random baseline seed base is {SEED}.

## Remaining source gap impact audit
See V21_027_REMAINING_SOURCE_GAP_IMPACT_AUDIT.csv.

## DATA_TRUST zero-alpha confirmation
DATA_TRUST ranking contribution is 0 and alpha contribution is 0. RISK and MARKET_REGIME additive alpha contribution are 0.

## Explicit blocked actions
No official ranking mutation. No official factor weight mutation. No official recommendation. No trade action. No shadow activation. No official use. No official ranking readiness. No official weight update readiness. No production readiness. No real-book readiness.

## What this stage proves
It tests whether repaired research-only trend and stability labels improve context-aware alpha-only and risk-gated diagnostics.

## What this stage still cannot prove
It cannot approve official scoring, official ranking, official weights, recommendations, trade actions, shadow activation, production use, or real-book use.

## Recommended next stage
{next_stage}
""", encoding="utf-8")

    print(f"STAGE_NAME={STAGE_NAME}")
    print(f"final_status={final_status}")
    print(f"context_retest_decision={retest_decision}")
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
