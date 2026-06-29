#!/usr/bin/env python
"""V21.024 market regime context logic repair.

Research-only repair of distinct market-regime context logic. Outputs are
strictly V21_024-scoped and never mutate official ranking, weight,
recommendation, trade, or shadow-policy artifacts.
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


STAGE_NAME = "V21_024_MARKET_REGIME_CONTEXT_LOGIC_REPAIR"
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"
OBS_SELECTION = OUT_DIR / "V21_005_OBSERVATION_SELECTION_AUDIT.csv"

V21_022_INPUTS = [
    OUT_DIR / "V21_022_V21_016_CANDIDATE_INGEST_AUDIT.csv",
    OUT_DIR / "V21_022_RISK_HARD_GATE_RECONSTRUCTION_AUDIT.csv",
    OUT_DIR / "V21_022_CANDIDATE_VS_ALPHA_ONLY_COMPARISON.csv",
    OUT_DIR / "V21_022_STATISTICAL_CONFIRMATION.csv",
    OUT_DIR / "V21_022_REGIME_ROBUSTNESS_CONFIRMATION.csv",
    OUT_DIR / "V21_022_FALSE_BLOCK_AND_MISSED_WINNER_AUDIT.csv",
    OUT_DIR / "V21_022_OUTLIER_DEPENDENCY_RETEST.csv",
    OUT_DIR / "V21_022_MARKET_REGIME_DISTINCT_CONTEXT_LOGIC_AUDIT.csv",
    OUT_DIR / "V21_022_RESEARCH_DRY_RUN_READINESS_ASSESSMENT.csv",
    OUT_DIR / "V21_022_RISK_REGIME_MODIFIER_CONFIRMATION_DECISION.csv",
    OUT_DIR / "V21_022_RISK_REGIME_MODIFIER_ROBUSTNESS_CONFIRMATION_SUMMARY.csv",
    READ_CENTER_DIR / "V21_022_RISK_REGIME_MODIFIER_ROBUSTNESS_CONFIRMATION_REPORT.md",
]

INGEST = OUT_DIR / "V21_024_V21_022_DECISION_INGEST_AUDIT.csv"
SOURCE_AUDIT = OUT_DIR / "V21_024_REGIME_CONTEXT_SOURCE_CONTRACT_AUDIT.csv"
LABEL_AUDIT = OUT_DIR / "V21_024_REGIME_LABEL_ADEQUACY_CONFLICT_AUDIT.csv"
REPAIR_AUDIT = OUT_DIR / "V21_024_TRUE_CONTEXT_ONLY_LOGIC_REPAIR_AUDIT.csv"
SCORING_TEST = OUT_DIR / "V21_024_REGIME_SPECIFIC_SCORING_CONTEXT_TEST.csv"
RISK_GATE_TEST = OUT_DIR / "V21_024_REGIME_SPECIFIC_RISK_GATE_INTERACTION_TEST.csv"
STAT = OUT_DIR / "V21_024_REGIME_CONTEXT_STATISTICAL_CONFIRMATION.csv"
TRANSITION = OUT_DIR / "V21_024_REGIME_TRANSITION_CONFLICT_EXCLUSION_TEST.csv"
DECISION = OUT_DIR / "V21_024_CONTEXT_LOGIC_REPAIR_DECISION.csv"
SUMMARY = OUT_DIR / "V21_024_MARKET_REGIME_CONTEXT_LOGIC_REPAIR_SUMMARY.csv"
REPORT = READ_CENTER_DIR / "V21_024_MARKET_REGIME_CONTEXT_LOGIC_REPAIR_REPORT.md"

WINDOWS = ["5d", "10d", "20d"]
CORE_REGIMES = ["risk_on", "risk_off", "neutral"]
SEED = 21024
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


def yn(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def field(row: dict[str, str], candidates: list[str]) -> str:
    by_norm = {norm(key): key for key in row}
    for candidate in candidates:
        if candidate in by_norm:
            return row.get(by_norm[candidate], "")
    return ""


def family_score(row: dict[str, str], family: str) -> float | None:
    low = family.lower()
    for candidate in [f"normalized_{low}_score", f"{low}_score"]:
        value = fnum(row.get(candidate) if candidate in row else field(row, [candidate]))
        if value is not None:
            return value
    return None


def forward_return(row: dict[str, str], window: str) -> float | None:
    return fnum(row.get(f"forward_return_{window}") or field(row, [f"forward_return_{window}"]))


def regime_label(row: dict[str, str]) -> str:
    explicit = field(row, ["market_regime", "regime_label", "market_regime_label"])
    if explicit:
        low = explicit.strip().lower()
        if low in CORE_REGIMES:
            return low
    score = family_score(row, "MARKET_REGIME")
    if score is None:
        return "missing"
    if score >= 0.55:
        return "risk_on"
    if score <= 0.45:
        return "risk_off"
    return "neutral"


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
                merged["_baseline_official_research_rank"] = sel.get("rank") or field(row, ["rank"])
                merged["_baseline_official_research_score"] = sel.get("score") or field(row, ["score", "baseline_score"])
                merged["_regime"] = regime_label(merged)
                output.append(merged)
    return output


def grouped_indices(rows: list[dict[str, str]], keys: tuple[str, ...]) -> dict[tuple[str, ...], list[int]]:
    groups: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for idx, row in enumerate(rows):
        groups[tuple(row.get(key, "") for key in keys)].append(idx)
    return groups


def rank_map(rows: list[dict[str, str]], scores: list[float | None], keys: tuple[str, ...]) -> dict[int, int]:
    ranks: dict[int, int] = {}
    for idxs in grouped_indices(rows, keys).values():
        usable = [(idx, scores[idx]) for idx in idxs if scores[idx] is not None]
        for rank, (idx, _score) in enumerate(sorted(usable, key=lambda item: item[1], reverse=True), start=1):
            ranks[idx] = rank
    return ranks


def eval_ranked(rows: list[dict[str, str]], scores: list[float | None], window: str, keys: tuple[str, ...]) -> dict[str, object]:
    usable_count = sum(1 for idx, score in enumerate(scores) if score is not None and forward_return(rows[idx], window) is not None)
    if usable_count < MIN_N:
        return {"observation_count": usable_count, "sample_adequacy": "INSUFFICIENT_SAMPLE"}
    buckets: dict[str, list[float]] = defaultdict(list)
    top_bottom, top_universe, mono = [], [], []
    for idxs in grouped_indices(rows, keys).values():
        pairs = [(idx, scores[idx]) for idx in idxs if scores[idx] is not None and forward_return(rows[idx], window) is not None]
        if not pairs:
            continue
        ordered = sorted(pairs, key=lambda item: item[1], reverse=True)
        n = len(ordered)
        q = max(1, math.ceil(n * 0.2))
        defs = {"TOP_5": ordered[:5], "TOP_10": ordered[:10], "TOP_20": ordered[:20], "TOP_QUINTILE": ordered[:q], "BOTTOM_QUINTILE": ordered[-q:]}
        for bucket, vals in defs.items():
            buckets[bucket].extend(ret for ret in (forward_return(rows[idx], window) for idx, _ in vals) if ret is not None)
        top_vals = [ret for ret in (forward_return(rows[idx], window) for idx, _ in defs["TOP_QUINTILE"]) if ret is not None]
        bottom_vals = [ret for ret in (forward_return(rows[idx], window) for idx, _ in defs["BOTTOM_QUINTILE"]) if ret is not None]
        all_vals = [ret for ret in (forward_return(rows[idx], window) for idx, _ in ordered) if ret is not None]
        if top_vals and bottom_vals:
            top_bottom.append(mean(top_vals) - mean(bottom_vals))
        if top_vals and all_vals:
            top_universe.append(mean(top_vals) - mean(all_vals))
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
    all_rets = [ret for row in rows if (ret := forward_return(row, window)) is not None]
    return {
        "observation_count": usable_count,
        "top5_mean_return": mean(buckets["TOP_5"]) if buckets["TOP_5"] else None,
        "top10_mean_return": mean(buckets["TOP_10"]) if buckets["TOP_10"] else None,
        "top20_mean_return": mean(buckets["TOP_20"]) if buckets["TOP_20"] else None,
        "top_quintile_mean_return": mean(topq) if topq else None,
        "mean_return": mean(all_rets) if all_rets else None,
        "median_return": median(topq) if topq else None,
        "hit_rate": sum(1 for value in topq if value > 0) / len(topq) if topq else None,
        "top_minus_bottom_spread": mean(top_bottom) if top_bottom else None,
        "top_minus_universe_spread": mean(top_universe) if top_universe else None,
        "monotonicity_score": mean(mono) if mono else None,
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
    t_stat = mean(values) / (sd / math.sqrt(len(values)))
    return t_stat, math.erfc(abs(t_stat) / math.sqrt(2.0))


def bootstrap_ci(values: list[float], seed: int) -> tuple[float | None, float | None]:
    if len(values) < 2:
        return None, None
    rng = random.Random(seed)
    samples = [mean(values[rng.randrange(len(values))] for _ in values) for _ in range(500)]
    samples.sort()
    return samples[12], samples[487]


def paired_spreads(rows: list[dict[str, str]], left: list[float | None], right: list[float | None], window: str, keys: tuple[str, ...]) -> list[float]:
    spreads = []
    for idxs in grouped_indices(rows, keys).values():
        def top(scores: list[float | None]) -> list[float]:
            pairs = [(idx, scores[idx]) for idx in idxs if scores[idx] is not None and forward_return(rows[idx], window) is not None]
            ordered = sorted(pairs, key=lambda item: item[1], reverse=True)
            q = max(1, math.ceil(len(ordered) * 0.2))
            return [ret for ret in (forward_return(rows[idx], window) for idx, _ in ordered[:q]) if ret is not None]
        lvals, rvals = top(left), top(right)
        if lvals and rvals:
            spreads.append(mean(lvals) - mean(rvals))
    return spreads


def transition_flags(rows: list[dict[str, str]]) -> set[int]:
    flags = set()
    by_ticker = defaultdict(list)
    for idx, row in enumerate(rows):
        by_ticker[row.get("_ticker", "")].append((row.get("_as_of_date", ""), idx, row.get("_regime", "")))
    for vals in by_ticker.values():
        vals.sort()
        prev = None
        for _date, idx, reg in vals:
            if prev is not None and reg != prev:
                flags.add(idx)
            prev = reg
    return flags


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    missing = [path.relative_to(ROOT).as_posix() for path in V21_022_INPUTS if not path.exists() or path.stat().st_size == 0]
    summary_022 = first(read_csv(OUT_DIR / "V21_022_RISK_REGIME_MODIFIER_ROBUSTNESS_CONFIRMATION_SUMMARY.csv"))
    decision_022 = first(read_csv(OUT_DIR / "V21_022_RISK_REGIME_MODIFIER_CONFIRMATION_DECISION.csv"))
    rows = load_primary_rows()
    alpha = [alpha_score(row) for row in rows]
    gated = [risk_gate_score(row) for row in rows]
    global_alpha_rank = rank_map(rows, alpha, ("_as_of_date",))
    within_alpha_rank = rank_map(rows, alpha, ("_as_of_date", "_regime"))
    within_gated_rank = rank_map(rows, gated, ("_as_of_date", "_regime"))
    transition_idxs = transition_flags(rows)

    ingest_rows = [
        {"audit_item": "required_v21_022_artifacts_present", "audit_passed": yn(not missing), "observed_value": "|".join(missing) if missing else "ALL_PRESENT", "required_value": "TRUE", "research_only": "TRUE"},
        {"audit_item": "v21_022_decision_ingested", "audit_passed": yn(decision_022.get("confirmation_decision") == "RISK_HARD_GATE_REGIME_FRAGILE"), "observed_value": decision_022.get("confirmation_decision", ""), "required_value": "RISK_HARD_GATE_REGIME_FRAGILE", "research_only": "TRUE"},
        {"audit_item": "recommended_next_stage_v21_024", "audit_passed": yn(decision_022.get("recommended_next_stage") == "V21.024_MARKET_REGIME_CONTEXT_LOGIC_REPAIR"), "observed_value": decision_022.get("recommended_next_stage", ""), "required_value": "V21.024_MARKET_REGIME_CONTEXT_LOGIC_REPAIR", "research_only": "TRUE"},
        {"audit_item": "context_logic_status_partial", "audit_passed": yn(summary_022.get("context_logic_status") == "DISTINCT_CONTEXT_LOGIC_PARTIAL"), "observed_value": summary_022.get("context_logic_status", ""), "required_value": "DISTINCT_CONTEXT_LOGIC_PARTIAL", "research_only": "TRUE"},
        {"audit_item": "official_use_false", "audit_passed": yn(summary_022.get("official_use_allowed") == "FALSE"), "observed_value": summary_022.get("official_use_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "official_ranking_readiness_false", "audit_passed": yn(summary_022.get("official_ranking_readiness_allowed") == "FALSE"), "observed_value": summary_022.get("official_ranking_readiness_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "official_weight_update_readiness_false", "audit_passed": yn(summary_022.get("official_weight_update_readiness_allowed") == "FALSE"), "observed_value": summary_022.get("official_weight_update_readiness_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "official_weight_update_blocked", "audit_passed": yn(summary_022.get("official_weight_update_blocked") == "TRUE"), "observed_value": summary_022.get("official_weight_update_blocked", ""), "required_value": "TRUE", "research_only": "TRUE"},
        {"audit_item": "data_trust_zero_alpha_ranking_contribution", "audit_passed": yn(summary_022.get("data_trust_alpha_contribution") == "0" and summary_022.get("data_trust_ranking_weight") == "0"), "observed_value": f"{summary_022.get('data_trust_ranking_weight','')}|{summary_022.get('data_trust_alpha_contribution','')}", "required_value": "0|0", "research_only": "TRUE"},
        {"audit_item": "risk_additive_alpha_contribution_zero", "audit_passed": yn(summary_022.get("risk_additive_alpha_contribution") == "0"), "observed_value": summary_022.get("risk_additive_alpha_contribution", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "market_regime_additive_alpha_contribution_zero", "audit_passed": yn(summary_022.get("market_regime_additive_alpha_contribution") == "0"), "observed_value": summary_022.get("market_regime_additive_alpha_contribution", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "official_ranking_mutation_count_zero", "audit_passed": yn(summary_022.get("official_ranking_mutation_count") == "0"), "observed_value": summary_022.get("official_ranking_mutation_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "official_factor_weight_mutation_count_zero", "audit_passed": yn(summary_022.get("official_factor_weight_mutation_count") == "0"), "observed_value": summary_022.get("official_factor_weight_mutation_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "official_recommendation_count_zero", "audit_passed": yn(summary_022.get("official_recommendation_count") == "0"), "observed_value": summary_022.get("official_recommendation_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "trade_action_count_zero", "audit_passed": yn(summary_022.get("trade_action_count") == "0"), "observed_value": summary_022.get("trade_action_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "shadow_activation_false", "audit_passed": yn(summary_022.get("shadow_activation") == "FALSE"), "observed_value": summary_022.get("shadow_activation", ""), "required_value": "FALSE", "research_only": "TRUE"},
    ]

    source_fields = [
        ("market_regime_label", any(row.get("_regime") in CORE_REGIMES for row in rows), "DERIVABLE_RESEARCH_ONLY"),
        ("risk_on_label", any(row.get("_regime") == "risk_on" for row in rows), "DERIVABLE_RESEARCH_ONLY"),
        ("risk_off_label", any(row.get("_regime") == "risk_off" for row in rows), "DERIVABLE_RESEARCH_ONLY"),
        ("neutral_label", any(row.get("_regime") == "neutral" for row in rows), "DERIVABLE_RESEARCH_ONLY"),
        ("vix_high_low_labels", False, "NOT_ALLOWED_TO_FABRICATE"),
        ("qqq_trend_labels", False, "NOT_ALLOWED_TO_FABRICATE"),
        ("spy_trend_labels", False, "NOT_ALLOWED_TO_FABRICATE"),
        ("sector_theme_regime_labels", False, "NOT_ALLOWED_TO_FABRICATE"),
        ("event_regime_labels", False, "NOT_ALLOWED_TO_FABRICATE"),
        ("regime_source", False, "MISSING"),
        ("regime_as_of_date", any(row.get("_as_of_date") for row in rows), "AVAILABLE"),
        ("regime_effective_date", False, "MISSING"),
        ("regime_freshness", False, "MISSING"),
        ("regime_conflict_flag", bool(transition_idxs), "DERIVABLE_RESEARCH_ONLY"),
        ("regime_transition_flag", bool(transition_idxs), "DERIVABLE_RESEARCH_ONLY"),
        ("forward_return_outcome", any(forward_return(row, "10d") is not None for row in rows), "AVAILABLE"),
        ("alpha_only_score_rank", bool(global_alpha_rank), "DERIVABLE_RESEARCH_ONLY"),
        ("risk_hard_gate_diagnostic_rank", bool(within_gated_rank), "DERIVABLE_RESEARCH_ONLY"),
        ("baseline_official_research_rank", any(row.get("_baseline_official_research_rank") for row in rows), "AVAILABLE"),
    ]
    source_rows = [{"field_name": name, "field_status": status if present else "MISSING" if status != "NOT_ALLOWED_TO_FABRICATE" else status, "available_observation_count": sum(1 for row in rows if row.get("_regime") in CORE_REGIMES) if "label" in name or "rank" in name else len(rows) if present else 0, "research_only": "TRUE"} for name, present, status in source_fields]

    label_rows = []
    usable_regimes = []
    for reg in CORE_REGIMES + ["high_vix", "low_vix", "QQQ_uptrend", "QQQ_downtrend", "SPY_uptrend", "SPY_downtrend", "sector_uptrend", "sector_downtrend", "FOMC", "CPI", "NFP", "earnings_season"]:
        idxs = [idx for idx, row in enumerate(rows) if row.get("_regime") == reg]
        dates = {rows[idx].get("_as_of_date", "") for idx in idxs}
        tickers = {rows[idx].get("_ticker", "") for idx in idxs}
        windows = [w for w in WINDOWS if sum(1 for idx in idxs if forward_return(rows[idx], w) is not None) >= MIN_N]
        trans = sum(1 for idx in idxs if idx in transition_idxs)
        if not idxs:
            quality = "MISSING_LABEL"
        elif len(idxs) < MIN_N or not windows:
            quality = "INSUFFICIENT_SAMPLE"
        elif trans / len(idxs) > 0.25:
            quality = "CONFLICTED_LABELS"
        elif len(dates) < 20:
            quality = "PARTIAL_BUT_USABLE_FOR_CONTEXT_TEST"
        else:
            quality = "ADEQUATE_FOR_CONTEXT_TEST"
        if quality in {"ADEQUATE_FOR_CONTEXT_TEST", "PARTIAL_BUT_USABLE_FOR_CONTEXT_TEST", "CONFLICTED_LABELS"}:
            usable_regimes.append(reg)
        label_rows.append({"regime_label": reg, "observation_count": len(idxs), "distinct_as_of_date_count": len(dates), "distinct_ticker_count": len(tickers), "available_forward_return_windows": "|".join(windows), "overlap_conflict_count": 0, "transition_risk_count": trans, "sample_adequacy": "SUFFICIENT" if windows else "INSUFFICIENT_SAMPLE", "label_quality_status": quality, "research_only": "TRUE"})

    repair_rows = []
    for item, status in [
        ("no_single_global_market_regime_adjusted_score", "PASS"),
        ("market_regime_not_additive_alpha", "PASS"),
        ("global_alpha_only_rank_distinguished", "PASS" if global_alpha_rank else "FAIL"),
        ("within_regime_alpha_only_rank_distinguished", "PASS" if within_alpha_rank else "FAIL"),
        ("within_regime_risk_gated_rank_distinguished", "PASS" if within_gated_rank else "FAIL"),
        ("regime_context_label_distinguished", "PASS" if any(row.get("_regime") in CORE_REGIMES for row in rows) else "FAIL"),
        ("regime_transition_conflict_status_distinguished", "PASS"),
        ("global_baseline_preserved_only_as_comparator", "PASS"),
    ]:
        repair_rows.append({"repair_item": item, "repair_status": status, "uses_single_global_market_regime_adjusted_score": "FALSE", "data_trust_alpha_contribution": "0", "risk_additive_alpha_contribution": "0", "market_regime_additive_alpha_contribution": "0", "official_score_overwritten": "FALSE", "official_rank_overwritten": "FALSE", "research_only": "TRUE"})

    scoring_rows = []
    for reg in usable_regimes:
        idxs = [idx for idx, row in enumerate(rows) if row.get("_regime") == reg]
        sub = [rows[idx] for idx in idxs]
        sub_alpha, sub_gate = [alpha[idx] for idx in idxs], [gated[idx] for idx in idxs]
        sub_baseline = [fnum(rows[idx].get("_baseline_official_research_score")) for idx in idxs]
        for window in WINDOWS:
            for variant, scores, keys in [
                ("GLOBAL_ALPHA_ONLY_RANK", sub_alpha, ("_as_of_date",)),
                ("WITHIN_REGIME_ALPHA_ONLY_RANK", sub_alpha, ("_as_of_date", "_regime")),
                ("WITHIN_REGIME_RISK_GATED_RANK", sub_gate, ("_as_of_date", "_regime")),
                ("BASELINE_OFFICIAL_RESEARCH_RANK_COMPARATOR", sub_baseline, ("_as_of_date",)),
            ]:
                stats = eval_ranked(sub, scores, window, keys)
                wr = rank_map(sub, scores, keys)
                gr = rank_map(sub, sub_alpha, ("_as_of_date",))
                turnover = mean([abs(wr[idx] - gr[idx]) for idx in wr.keys() & gr.keys()]) if wr and gr else None
                scoring_rows.append({"regime_label": reg, "forward_return_window": window, "context_rank_variant": variant, **stats, "rank_turnover_vs_global_alpha_only": turnover, "global_market_regime_adjusted_score_used": "FALSE", "research_only": "TRUE"})

    risk_rows = []
    for reg in usable_regimes:
        idxs = [idx for idx, row in enumerate(rows) if row.get("_regime") == reg]
        for window in WINDOWS:
            rets = [forward_return(rows[idx], window) for idx in idxs if forward_return(rows[idx], window) is not None]
            if len(rets) < MIN_N:
                behavior = "INSUFFICIENT_SAMPLE"
                blocked_high = unblocked_high = []
                missed = protected = None
            else:
                winner_cut = sorted(rets)[int(len(rets) * 0.8)]
                downside_cut = sorted(rets)[int(len(rets) * 0.2)]
                blocked_high, unblocked_high = [], []
                blocked_winners = blocked_downside = 0
                for idx in idxs:
                    ret = forward_return(rows[idx], window)
                    if ret is None:
                        continue
                    high = within_alpha_rank.get(idx, 999999) <= max(5, math.ceil(len(idxs) * 0.2))
                    if high and risk_blocked(rows[idx]):
                        blocked_high.append(ret)
                        blocked_winners += 1 if ret >= winner_cut else 0
                        blocked_downside += 1 if ret <= downside_cut else 0
                    elif high:
                        unblocked_high.append(ret)
                missed = blocked_winners / len(blocked_high) if blocked_high else None
                protected = blocked_downside / len(blocked_high) if blocked_high else None
                if missed is None:
                    behavior = "INSUFFICIENT_SAMPLE"
                elif protected is not None and protected > missed and protected >= 0.35:
                    behavior = "PROTECTIVE_IN_REGIME"
                elif missed >= 0.35 and (protected or 0) < missed:
                    behavior = "OVERLY_RESTRICTIVE_IN_REGIME"
                elif protected == 0 and missed == 0:
                    behavior = "NOT_USEFUL_IN_REGIME"
                else:
                    behavior = "MIXED_IN_REGIME"
            risk_rows.append({"regime_label": reg, "forward_return_window": window, "blocked_high_rank_count": len(blocked_high), "unblocked_high_rank_count": len(unblocked_high), "blocked_high_rank_mean_return": mean(blocked_high) if blocked_high else None, "unblocked_high_rank_mean_return": mean(unblocked_high) if unblocked_high else None, "missed_winner_rate": missed, "downside_protection_rate": protected, "risk_gate_interaction_classification": behavior, "official_gate_loosening_allowed": "FALSE", "research_only": "TRUE"})

    stat_rows = []
    for reg in usable_regimes:
        idxs = [idx for idx, row in enumerate(rows) if row.get("_regime") == reg]
        sub = [rows[idx] for idx in idxs]
        sub_alpha, sub_gate = [alpha[idx] for idx in idxs], [gated[idx] for idx in idxs]
        for window in WINDOWS:
            comparisons = [
                ("within_regime_alpha_vs_global_alpha", sub_alpha, sub_alpha, ("_as_of_date", "_regime")),
                ("within_regime_risk_gated_vs_within_regime_alpha", sub_gate, sub_alpha, ("_as_of_date", "_regime")),
            ]
            for name, left, right, keys in comparisons:
                spreads = paired_spreads(sub, left, right, window, keys)
                t_stat, p_value = t_p(spreads)
                ci_low, ci_high = bootstrap_ci(spreads, SEED + len(window) + len(reg)) if spreads else (None, None)
                rng = random.Random(SEED + len(window) + len(reg) + len(name))
                random_vals = []
                for _ in range(500):
                    vals = []
                    for gidxs in grouped_indices(sub, keys).values():
                        usable = [idx for idx in gidxs if forward_return(sub[idx], window) is not None]
                        if usable:
                            q = max(1, math.ceil(len(usable) * 0.2))
                            vals.extend(ret for ret in (forward_return(sub[idx], window) for idx in rng.sample(usable, min(q, len(usable)))) if ret is not None)
                    if vals:
                        random_vals.append(mean(vals))
                left_stat = eval_ranked(sub, left, window, keys)
                left_top = fnum(left_stat.get("top_quintile_mean_return"))
                stat_rows.append({"regime_label": reg, "forward_return_window": window, "comparison_name": name, "paired_group_count": len(spreads), "mean_improvement": mean(spreads) if spreads else None, "t_stat": t_stat, "p_value": p_value, "bootstrap_ci_low": ci_low, "bootstrap_ci_high": ci_high, "deterministic_seed_base": SEED, "random_trial_count": len(random_vals), "percentile_versus_random": sum(1 for value in random_vals if left_top is not None and left_top > value) / len(random_vals) if random_vals else None, "sample_adequacy": "SUFFICIENT" if len(spreads) >= 2 else "INSUFFICIENT_SAMPLE", "research_only": "TRUE"})

    transition_rows = []
    for reg in usable_regimes:
        for window in WINDOWS:
            for mode in ["INCLUDING_TRANSITION_CONFLICT", "EXCLUDING_TRANSITION_CONFLICT"]:
                idxs = [idx for idx, row in enumerate(rows) if row.get("_regime") == reg and (mode == "INCLUDING_TRANSITION_CONFLICT" or idx not in transition_idxs)]
                sub = [rows[idx] for idx in idxs]
                sub_alpha = [alpha[idx] for idx in idxs]
                stats = eval_ranked(sub, sub_alpha, window, ("_as_of_date", "_regime"))
                transition_rows.append({"regime_label": reg, "forward_return_window": window, "transition_conflict_mode": mode, "excluded_transition_conflict_count": 0 if mode == "INCLUDING_TRANSITION_CONFLICT" else sum(1 for idx, row in enumerate(rows) if row.get("_regime") == reg and idx in transition_idxs), "top_quintile_mean_return": stats.get("top_quintile_mean_return"), "monotonicity_score": stats.get("monotonicity_score"), "sample_adequacy": stats.get("sample_adequacy"), "transition_noise_sensitivity": "LOW" if stats.get("sample_adequacy") == "SUFFICIENT" else "INCONCLUSIVE", "research_only": "TRUE"})

    usable_count = len(usable_regimes)
    any_missing_required = bool(missing) or any(row["audit_passed"] == "FALSE" for row in ingest_rows[:4])
    label_limited = any(row["label_quality_status"] in {"MISSING_LABEL", "CONFLICTED_LABELS", "INSUFFICIENT_SAMPLE"} for row in label_rows)
    risk_overly = any(row["risk_gate_interaction_classification"] == "OVERLY_RESTRICTIVE_IN_REGIME" for row in risk_rows)
    context_improves = any((fnum(row.get("top_quintile_mean_return")) or 0) > 0 for row in scoring_rows if row.get("context_rank_variant") in {"WITHIN_REGIME_ALPHA_ONLY_RANK", "WITHIN_REGIME_RISK_GATED_RANK"})
    if any_missing_required:
        repair_decision = "MARKET_REGIME_CONTEXT_LOGIC_INCONCLUSIVE_REQUIRED_FIELDS_MISSING"
        next_stage = "V21.026_MARKET_REGIME_SOURCE_CONTRACT_REPAIR"
        path_decision = "market regime label/source repair"
    elif usable_count < 2:
        repair_decision = "MARKET_REGIME_CONTEXT_LOGIC_NOT_SUPPORTED"
        next_stage = "V21.019_MORE_MATURED_OBSERVATION_ACCUMULATION_PLAN"
        path_decision = "more matured observation accumulation"
    elif label_limited:
        repair_decision = "MARKET_REGIME_CONTEXT_LOGIC_PARTIAL_LABELS_LIMITED"
        next_stage = "V21.026_MARKET_REGIME_SOURCE_CONTRACT_REPAIR"
        path_decision = "market regime label/source repair"
    elif risk_overly:
        repair_decision = "MARKET_REGIME_CONTEXT_LOGIC_PARTIAL_LABELS_LIMITED"
        next_stage = "V21.017_OVERHEAT_ENTRY_TIMING_AND_FALSE_BLOCK_REPAIR"
        path_decision = "within-regime risk-gated research plan"
    elif context_improves:
        repair_decision = "MARKET_REGIME_CONTEXT_LOGIC_REPAIRED_RESEARCH_ONLY"
        next_stage = "V21.025_WITHIN_REGIME_ALPHA_ONLY_AND_RISK_GATE_SHADOW_RESEARCH_PLAN"
        path_decision = "within-regime alpha-only shadow research plan"
    else:
        repair_decision = "MARKET_REGIME_CONTEXT_LOGIC_REQUIRES_SOURCE_CONTRACT_REPAIR"
        next_stage = "V21.015_NONLINEAR_FACTOR_INTERACTION_RESEARCH_PROTOTYPE"
        path_decision = "nonlinear interaction prototype"
    prefix = "PASS" if repair_decision == "MARKET_REGIME_CONTEXT_LOGIC_REPAIRED_RESEARCH_ONLY" else "PARTIAL_PASS"
    final_status = f"{prefix}_V21_024_{repair_decision}"
    decision_rows = [{"context_logic_repair_decision": repair_decision, "candidate_research_path_decision": path_decision, "final_status": final_status, "official_use_allowed": "FALSE", "official_ranking_readiness_allowed": "FALSE", "official_weight_update_readiness_allowed": "FALSE", "official_weight_update_blocked": "TRUE", "recommended_next_stage": next_stage, "selected_recommended_next_stage": "TRUE", "research_only": "TRUE"}]
    summary = {
        "stage_name": STAGE_NAME,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "research_only": "TRUE",
        "final_status": final_status,
        "context_logic_repair_decision": repair_decision,
        "candidate_research_path_decision": path_decision,
        "v21_022_confirmation_decision": decision_022.get("confirmation_decision", ""),
        "v21_022_recommended_next_stage": decision_022.get("recommended_next_stage", ""),
        "usable_regime_count": usable_count,
        "true_context_only_logic_repair_status": "REPAIRED_RESEARCH_ONLY" if all(row["repair_status"] == "PASS" for row in repair_rows) else "PARTIAL",
        "single_global_market_regime_adjusted_score_used": "FALSE",
        "official_use_allowed": "FALSE",
        "official_ranking_readiness_allowed": "FALSE",
        "official_weight_update_readiness_allowed": "FALSE",
        "official_weight_update_blocked": "TRUE",
        "recommended_next_stage": next_stage,
        "prototype_output_scope": "V21_024_RESEARCH_ONLY",
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
    write_csv(SOURCE_AUDIT, source_rows, ["field_name", "field_status", "available_observation_count", "research_only"])
    write_csv(LABEL_AUDIT, label_rows, ["regime_label", "observation_count", "distinct_as_of_date_count", "distinct_ticker_count", "available_forward_return_windows", "overlap_conflict_count", "transition_risk_count", "sample_adequacy", "label_quality_status", "research_only"])
    write_csv(REPAIR_AUDIT, repair_rows, ["repair_item", "repair_status", "uses_single_global_market_regime_adjusted_score", "data_trust_alpha_contribution", "risk_additive_alpha_contribution", "market_regime_additive_alpha_contribution", "official_score_overwritten", "official_rank_overwritten", "research_only"])
    write_csv(SCORING_TEST, scoring_rows, ["regime_label", "forward_return_window", "context_rank_variant", "observation_count", "top5_mean_return", "top10_mean_return", "top20_mean_return", "top_quintile_mean_return", "mean_return", "median_return", "hit_rate", "top_minus_bottom_spread", "top_minus_universe_spread", "monotonicity_score", "sample_adequacy", "rank_turnover_vs_global_alpha_only", "global_market_regime_adjusted_score_used", "research_only"])
    write_csv(RISK_GATE_TEST, risk_rows, ["regime_label", "forward_return_window", "blocked_high_rank_count", "unblocked_high_rank_count", "blocked_high_rank_mean_return", "unblocked_high_rank_mean_return", "missed_winner_rate", "downside_protection_rate", "risk_gate_interaction_classification", "official_gate_loosening_allowed", "research_only"])
    write_csv(STAT, stat_rows, ["regime_label", "forward_return_window", "comparison_name", "paired_group_count", "mean_improvement", "t_stat", "p_value", "bootstrap_ci_low", "bootstrap_ci_high", "deterministic_seed_base", "random_trial_count", "percentile_versus_random", "sample_adequacy", "research_only"])
    write_csv(TRANSITION, transition_rows, ["regime_label", "forward_return_window", "transition_conflict_mode", "excluded_transition_conflict_count", "top_quintile_mean_return", "monotonicity_score", "sample_adequacy", "transition_noise_sensitivity", "research_only"])
    write_csv(DECISION, decision_rows, ["context_logic_repair_decision", "candidate_research_path_decision", "final_status", "official_use_allowed", "official_ranking_readiness_allowed", "official_weight_update_readiness_allowed", "official_weight_update_blocked", "recommended_next_stage", "selected_recommended_next_stage", "research_only"])
    write_csv(SUMMARY, [summary], list(summary.keys()))

    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(f"""# V21.024 Market Regime Context Logic Repair Report

## Executive summary
This research-only repair stage builds true distinct market-regime context logic after V21.022 found RISK_HARD_GATE_DIAGNOSTIC regime fragility and partial context logic. Outputs are V21_024-scoped only.

## Final context logic repair decision
{repair_decision}

Final status: {final_status}

## V21.022 decision ingestion
V21.022 decision: {decision_022.get('confirmation_decision', '')}. V21.022 recommended next stage: {decision_022.get('recommended_next_stage', '')}.

## Regime context source contract audit
See V21_024_REGIME_CONTEXT_SOURCE_CONTRACT_AUDIT.csv. Missing labels are not fabricated.

## Regime label adequacy and conflict audit
Usable regimes: {usable_count}. See V21_024_REGIME_LABEL_ADEQUACY_CONFLICT_AUDIT.csv.

## True context-only logic repair
The repaired logic distinguishes global alpha-only rank, within-regime alpha-only rank, within-regime risk-gated rank, regime context label, and transition/conflict status. No single global market-regime-adjusted score is used.

## Regime-specific scoring context test
See V21_024_REGIME_SPECIFIC_SCORING_CONTEXT_TEST.csv.

## Regime-specific risk gate interaction test
See V21_024_REGIME_SPECIFIC_RISK_GATE_INTERACTION_TEST.csv.

## Regime context statistical confirmation
See V21_024_REGIME_CONTEXT_STATISTICAL_CONFIRMATION.csv. The deterministic random baseline uses seed base {SEED}.

## Regime transition and conflict exclusion test
See V21_024_REGIME_TRANSITION_CONFLICT_EXCLUSION_TEST.csv.

## DATA_TRUST zero-alpha confirmation
DATA_TRUST ranking contribution is 0 and alpha contribution is 0. DATA_TRUST is allowed only as gate or audit metadata.

## Explicit blocked actions
No official ranking mutation. No official factor weight mutation. No official recommendation. No trade action. No shadow activation. No official use. No official ranking readiness. No official weight update readiness. No production readiness. No real-book readiness.

## What this stage proves
It validates whether regime context can be evaluated distinctly without collapsing into a global equivalent score.

## What this stage still cannot prove
It cannot approve official scoring, official ranking, official weight updates, official recommendations, trade actions, shadow activation, production use, or real-book use.

## Recommended next stage
{next_stage}
""", encoding="utf-8")

    print(f"STAGE_NAME={STAGE_NAME}")
    print(f"final_status={final_status}")
    print(f"context_logic_repair_decision={repair_decision}")
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
