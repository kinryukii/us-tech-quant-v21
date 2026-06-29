#!/usr/bin/env python
"""Research-only soft combined-filter threshold relaxation dry-run for V21.045-R3."""

from __future__ import annotations

import csv
import math
import shutil
import statistics
from collections import Counter, defaultdict
from pathlib import Path


STAGE = "V21.045-R3_SOFT_COMBINED_FILTER_THRESHOLD_RELAXATION_DRY_RUN"
PASS_STATUS = "PASS_V21_045_R3_SOFT_FILTER_RELAXATION_DRY_RUN_READY"
WARN_STATUS = "PARTIAL_PASS_V21_045_R3_SOFT_FILTER_RELAXATION_WITH_WARNINGS"
COLUMN_STATUS = "PARTIAL_PASS_V21_045_R3_COLUMN_LIMITED"
INPUT_BLOCKED = "BLOCKED_V21_045_R3_R1_R2_OUTPUTS_NOT_READY"
SCOPE_BLOCKED = "BLOCKED_V21_045_R3_SCOPE_BOUNDARY_FAILED"

ROOT = Path(__file__).resolve().parents[2]
OPT = ROOT / "outputs" / "v21" / "optimization"
REVIEW = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"
BACKTEST = ROOT / "outputs" / "v21" / "backtest"
FACTORS = ROOT / "outputs" / "v21" / "factors"
PRICE_HISTORY = ROOT / "outputs" / "v20" / "price_history"

R1_COLS = OPT / "V21_045_R1_FILTER_COLUMN_AVAILABILITY_AUDIT.csv"
R1_REGISTER = OPT / "V21_045_R1_FILTER_VARIANT_DEFINITION_REGISTER.csv"
R1_PANEL = OPT / "V21_045_R1_FILTERED_REBACKTEST_PANEL.csv"
R1_SUMMARY = OPT / "V21_045_R1_FILTER_VARIANT_WINDOW_SUMMARY.csv"
R1_HIT = OPT / "V21_045_R1_FILTER_HIT_RATE_AND_PAYOFF_AUDIT.csv"
R1_DOWN = OPT / "V21_045_R1_FILTER_DOWNSIDE_AUDIT.csv"
R1_ATTR = OPT / "V21_045_R1_FILTER_SAMPLE_ATTRITION_AUDIT.csv"
R1_DECISION = OPT / "V21_045_R1_FILTER_OPTIMIZATION_DECISION_SUMMARY.csv"
R2_DECISION = REVIEW / "V21_045_R2_FILTER_REVIEW_DECISION_SUMMARY.csv"
R2_ATTR = REVIEW / "V21_045_R2_SAMPLE_ATTRITION_USABILITY_AUDIT.csv"
R2_CONC = REVIEW / "V21_045_R2_CONCENTRATION_AUDIT.csv"
R2_PAYOFF = REVIEW / "V21_045_R2_PAYOFF_DOWNSIDE_AUDIT.csv"
R5_PANEL = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_REBACKTEST_PANEL.csv"
R5_SUMMARY = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_VARIANT_WINDOW_SUMMARY.csv"
R5_QQQ = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_QQQ_BENCHMARK_COMPARISON.csv"
R6_DECISION = REVIEW / "V21_044_R6_CONTINUITY_GATE_DECISION_SUMMARY.csv"
TICKER_PRICES = PRICE_HISTORY / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
BENCHMARK_PRICES = PRICE_HISTORY / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"
TECH_SNAPSHOT = FACTORS / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv"

VARIANT_REGISTER = OPT / "V21_045_R3_SOFT_FILTER_VARIANT_REGISTER.csv"
COL_AUDIT = OPT / "V21_045_R3_SOFT_FILTER_COLUMN_AVAILABILITY_AUDIT.csv"
PANEL_OUT = OPT / "V21_045_R3_SOFT_FILTER_REBACKTEST_PANEL.csv"
SUMMARY_OUT = OPT / "V21_045_R3_SOFT_FILTER_VARIANT_WINDOW_SUMMARY.csv"
HIT_EXCESS_OUT = OPT / "V21_045_R3_SOFT_FILTER_HIT_RATE_EXCESS_COMPARISON.csv"
ATTRITION_OUT = OPT / "V21_045_R3_SOFT_FILTER_ATTRITION_USABILITY_AUDIT.csv"
CONC_OUT = OPT / "V21_045_R3_SOFT_FILTER_CONCENTRATION_AUDIT.csv"
PAYOFF_OUT = OPT / "V21_045_R3_SOFT_FILTER_PAYOFF_DOWNSIDE_AUDIT.csv"
DECISION_OUT = OPT / "V21_045_R3_SOFT_FILTER_DECISION_SUMMARY.csv"
REPORT = READ_CENTER / "V21_045_R3_SOFT_COMBINED_FILTER_THRESHOLD_RELAXATION_DRY_RUN_REPORT.md"
CURRENT_REPORT = READ_CENTER / "CURRENT_V21_045_R3_SOFT_COMBINED_FILTER_THRESHOLD_RELAXATION_DRY_RUN_REPORT.md"

WINDOWS = ["5D", "10D", "20D", "60D"]
BUCKETS = [("Top20", 20), ("Top50", 50)]
MODES = ["strict_no_refill", "filter_then_refill_from_next_ranked_names", "penalty_rerank"]

GUARDRAILS = {
    "research_only": "TRUE",
    "soft_filter_relaxation_dry_run_only": "TRUE",
    "filter_adoption_allowed": "FALSE",
    "technical_only_filter_overlay": "TRUE",
    "full_weight_result_available": "FALSE",
    "full_weight_rebacktest_allowed_now": "FALSE",
    "official_adoption_allowed": "FALSE",
    "official_weight_mutation": "FALSE",
    "official_ranking_mutation": "FALSE",
    "official_recommendation_allowed": "FALSE",
    "real_book_action_allowed": "FALSE",
    "broker_execution_allowed": "FALSE",
    "trade_action_allowed": "FALSE",
    "shadow_gate_allowed": "FALSE",
    "shadow_adoption_allowed": "FALSE",
}
FALSE_GUARDRAILS = [
    "filter_adoption_allowed", "full_weight_result_available", "full_weight_rebacktest_allowed_now",
    "official_adoption_allowed", "official_weight_mutation", "official_ranking_mutation",
    "official_recommendation_allowed", "real_book_action_allowed", "broker_execution_allowed",
    "trade_action_allowed", "shadow_gate_allowed", "shadow_adoption_allowed",
]


def yn(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: "" if row.get(field) is None else row.get(field, "") for field in fields})


def num(value: object) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.10f}"


def mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def pctile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return values[min(max(int(math.floor((len(values) - 1) * q)), 0), len(values) - 1)]


def load_tech() -> tuple[dict[tuple[str, str], dict[str, str]], list[str]]:
    rows = read_rows(TECH_SNAPSHOT)
    if not rows:
        return {}, []
    return {(r.get("as_of_date", ""), r.get("ticker", "")): r for r in rows}, list(rows[0].keys())


def load_series(path: Path, symbol: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in read_rows(path):
        if (row.get("symbol") or row.get("ticker") or "").upper() != symbol.upper():
            continue
        value = num(row.get("adjusted_close")) or num(row.get("close"))
        if row.get("date") and value is not None:
            out[row["date"]] = value
    return dict(sorted(out.items()))


def regime(series: dict[str, float]) -> dict[str, dict[str, bool]]:
    dates = list(series)
    vals = [series[d] for d in dates]
    out: dict[str, dict[str, bool]] = {}
    for i, day in enumerate(dates):
        ma20 = mean(vals[max(0, i - 19): i + 1])
        ma50 = mean(vals[max(0, i - 49): i + 1])
        ma20_prior = mean(vals[max(0, i - 24): max(0, i - 4)]) if i >= 23 else None
        out[day] = {
            "supportive": bool(ma20 and ma50 and vals[i] > ma20 and vals[i] > ma50 and ma20_prior and ma20 > ma20_prior),
            "above_ma20": bool(ma20 and vals[i] > ma20),
            "above_ma50": bool(ma50 and vals[i] > ma50),
        }
    return out


def baseline(summary_rows: list[dict[str, str]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for row in summary_rows:
        w = row.get("forward_return_window", "")
        if w in WINDOWS:
            out[w] = {
                "hit": num(row.get("top20_hit_rate_vs_QQQ")) or 0.0,
                "excess": num(row.get("top20_excess_vs_QQQ")) or 0.0,
            }
    return out


def tech_flags(row: dict[str, str]) -> dict[str, bool | float]:
    rsi = num(row.get("rsi_14"))
    kdj = num(row.get("kdj_j"))
    ma20d = num(row.get("ma20_distance"))
    ma50d = num(row.get("ma50_distance"))
    close = num(row.get("close"))
    ma20 = num(row.get("ma20"))
    ma50 = num(row.get("ma50"))
    bbpos = num(row.get("bb_position"))
    momentum5 = num(row.get("momentum_5"))
    extreme = any([
        rsi is not None and rsi >= 80,
        kdj is not None and kdj >= 110,
        ma20d is not None and ma20d > 0.18,
        ma50d is not None and ma50d > 0.30,
        bbpos is not None and bbpos > 1.25,
        momentum5 is not None and momentum5 > 0.20,
    ])
    light_ext = any([
        ma20d is not None and ma20d > 0.16,
        ma50d is not None and ma50d > 0.28,
    ])
    original_overheat = any([
        rsi is not None and rsi >= 70,
        kdj is not None and kdj >= 90,
        ma20d is not None and ma20d > 0.10,
        ma50d is not None and ma50d > 0.18,
        bbpos is not None and bbpos > 1.0,
        momentum5 is not None and momentum5 > 0.12,
    ])
    healthy = bool(close is not None and ma20 is not None and ma50 is not None and close > ma20 and ma20 > ma50 and ma20d is not None and -0.03 <= ma20d <= 0.08)
    strong_trend = bool(close is not None and ma20 is not None and ma50 is not None and close > ma20 and ma20 > ma50 and not extreme)
    penalty = (0.08 if extreme else 0.0) + (0.04 if light_ext else 0.0)
    return {"extreme": extreme, "light_ext": light_ext, "original_overheat": original_overheat, "healthy": healthy, "strong_trend": strong_trend, "penalty": penalty}


def passes(variant: str, asof: str, tech: dict[str, str], qqq: dict[str, dict[str, bool]]) -> bool:
    q = qqq.get(asof, {})
    supportive = bool(q.get("supportive"))
    f = tech_flags(tech)
    if variant == "BASELINE_TECHNICAL_ONLY":
        return True
    if variant == "COMBINED_CONSERVATIVE_ORIGINAL":
        return supportive and not bool(f["original_overheat"]) and bool(f["healthy"])
    if variant == "SOFT_COMBINED_V1_REGIME_ONLY_PLUS_LIGHT_OVERHEAT":
        return supportive and not bool(f["extreme"])
    if variant == "SOFT_COMBINED_V2_REGIME_PLUS_NO_EXTREME_EXTENSION":
        return supportive and not bool(f["light_ext"])
    if variant == "SOFT_COMBINED_V3_PULLBACK_OR_TREND":
        return supportive and (bool(f["healthy"]) or bool(f["strong_trend"]))
    if variant == "SOFT_COMBINED_V4_QQQ_REGIME_WITH_REFILL":
        return supportive
    if variant == "SOFT_COMBINED_V5_OVERHEAT_ONLY_LIGHT":
        return not bool(f["extreme"])
    if variant == "SOFT_COMBINED_V6_WATCHLIST_SCORE_NOT_BINARY_BLOCK":
        return True
    return False


def variant_rows(fields: list[str], qqq_available: bool) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    defs = [
        ("BASELINE_TECHNICAL_ONLY", "No filter.", "AVAILABLE"),
        ("COMBINED_CONSERVATIVE_ORIGINAL", "R1 combined filter reproduced for comparison.", "AVAILABLE" if qqq_available else "COLUMN_LIMITED"),
        ("SOFT_COMBINED_V1_REGIME_ONLY_PLUS_LIGHT_OVERHEAT", "QQQ supportive plus extreme-only overheat exclusion.", "AVAILABLE" if qqq_available else "COLUMN_LIMITED"),
        ("SOFT_COMBINED_V2_REGIME_PLUS_NO_EXTREME_EXTENSION", "QQQ supportive plus extreme MA distance exclusion.", "AVAILABLE" if qqq_available else "COLUMN_LIMITED"),
        ("SOFT_COMBINED_V3_PULLBACK_OR_TREND", "QQQ supportive and either healthy pullback or strong trend.", "AVAILABLE" if qqq_available else "COLUMN_LIMITED"),
        ("SOFT_COMBINED_V4_QQQ_REGIME_WITH_REFILL", "QQQ regime filter with refill comparison.", "AVAILABLE" if qqq_available else "COLUMN_LIMITED"),
        ("SOFT_COMBINED_V5_OVERHEAT_ONLY_LIGHT", "Extreme overheat exclusion only.", "AVAILABLE"),
        ("SOFT_COMBINED_V6_WATCHLIST_SCORE_NOT_BINARY_BLOCK", "Predefined penalty rerank by technical score minus overheat/regime penalties.", "AVAILABLE" if "technical_score_normalized" in fields else "COLUMN_LIMITED"),
    ]
    register = [{"filter_variant": n, "definition": d, "variant_status": s, "filter_adopted": "FALSE", "refill_modes_tested": "|".join(MODES), **GUARDRAILS} for n, d, s in defs]
    needed = ["rsi_14", "kdj_j", "ma20_distance", "ma50_distance", "close", "ma20", "ma50", "bb_position", "momentum_5", "technical_score_normalized"]
    available = [c for c in needed if c in fields]
    missing = [c for c in needed if c not in fields]
    col_audit = [{
        "source_artifact": str(TECH_SNAPSHOT.relative_to(ROOT)).replace("\\", "/"),
        "available_columns": "|".join(available),
        "missing_columns": "|".join(missing),
        "qqq_regime_source_available": yn(qqq_available),
        "column_status": "AVAILABLE" if not missing and qqq_available else "COLUMN_LIMITED",
        **GUARDRAILS,
    }]
    return register, col_audit


def evaluate(panel: list[dict[str, str]], tech: dict[tuple[str, str], dict[str, str]], qqq: dict[str, dict[str, bool]], variants: list[str], base: dict[str, dict[str, float]]) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in panel:
        if row.get("included_in_performance_aggregation") == "TRUE" and row.get("forward_return_window") in WINDOWS:
            grouped[(row["forward_return_window"], row["as_of_date"])].append(row)
    panel_out: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    comparisons: list[dict[str, object]] = []
    attrition_rows: list[dict[str, object]] = []
    conc_rows: list[dict[str, object]] = []
    payoff_rows: list[dict[str, object]] = []
    for variant in variants:
        for mode in MODES:
            if mode == "penalty_rerank" and variant != "SOFT_COMBINED_V6_WATCHLIST_SCORE_NOT_BINARY_BLOCK":
                continue
            for bucket, limit in BUCKETS:
                selected_by_window: dict[str, list[dict[str, str]]] = defaultdict(list)
                baseline_count: Counter[str] = Counter()
                selected_counts: dict[str, list[int]] = defaultdict(list)
                for (window, asof), rows in grouped.items():
                    ranked = sorted(rows, key=lambda r: num(r.get("technical_only_rank")) or 999999)
                    base_slice = ranked[:limit]
                    baseline_count[window] += len(base_slice)
                    if mode == "penalty_rerank":
                        def adjusted(row: dict[str, str]) -> float:
                            t = tech.get((asof, row.get("ticker", "")), {})
                            score = num(t.get("technical_score_normalized")) or num(row.get("technical_only_score")) or 0.0
                            penalty = float(tech_flags(t)["penalty"])
                            if not qqq.get(asof, {}).get("supportive"):
                                penalty += 0.04
                            return -(score - penalty)
                        chosen = sorted(ranked, key=adjusted)[:limit]
                    else:
                        chosen = [r for r in base_slice if passes(variant, asof, tech.get((asof, r.get("ticker", "")), {}), qqq)]
                        if mode == "filter_then_refill_from_next_ranked_names" and len(chosen) < limit:
                            chosen_ids = {id(r) for r in chosen}
                            for r in ranked[limit:]:
                                if id(r) in chosen_ids:
                                    continue
                                if passes(variant, asof, tech.get((asof, r.get("ticker", "")), {}), qqq):
                                    chosen.append(r)
                                if len(chosen) >= limit:
                                    break
                    selected_counts[window].append(len(chosen))
                    for r in chosen:
                        selected_by_window[window].append(r)
                        fwd = num(r.get("realized_forward_return"))
                        bench = num(r.get("benchmark_forward_return"))
                        excess = fwd - bench if fwd is not None and bench is not None else None
                        panel_out.append({
                            "filter_variant": variant, "bucket": bucket, "refill_mode": mode,
                            "as_of_date": asof, "ticker": r.get("ticker", ""), "forward_return_window": window,
                            "realized_forward_return": r.get("realized_forward_return", ""),
                            "benchmark_forward_return": r.get("benchmark_forward_return", ""),
                            "excess_vs_QQQ": fmt(excess), "filter_adopted": "FALSE",
                            "point_in_time_safe": r.get("point_in_time_safe", ""),
                            "leakage_violation_reason": r.get("leakage_violation_reason", ""),
                            **GUARDRAILS,
                        })
                for window in WINDOWS:
                    rows = selected_by_window[window]
                    paired = []
                    for r in rows:
                        a, b = num(r.get("realized_forward_return")), num(r.get("benchmark_forward_return"))
                        if a is not None and b is not None:
                            paired.append((a, b))
                    excesses = [a - b for a, b in paired]
                    wins = [x for x in excesses if x > 0]
                    losses = [x for x in excesses if x < 0]
                    asof_counter = Counter(r.get("as_of_date", "") for r in rows)
                    ticker_counter = Counter(r.get("ticker", "") for r in rows)
                    selected = len(rows)
                    total = baseline_count[window]
                    attr = 1.0 - selected / total if total else 0.0
                    hit = len(wins) / len(excesses) if excesses else None
                    ex = mean(excesses)
                    base_hit, base_ex = base.get(window, {}).get("hit", 0.0), base.get(window, {}).get("excess", 0.0)
                    payoff = (mean(wins) / abs(mean(losses))) if wins and losses and mean(losses) else None
                    top10_share = sum(c for _, c in ticker_counter.most_common(10)) / selected if selected else 0.0
                    top5_asof = sum(c for _, c in asof_counter.most_common(5)) / selected if selected else 0.0
                    conc_warn = top10_share > 0.50 or top5_asof > 0.50
                    attr_warn = "EXTREME_ATTRITION_WARNING" if attr > 0.98 else ("SEVERE_ATTRITION_WARNING" if attr > 0.90 else ("HIGH_ATTRITION_WARNING" if attr > 0.60 else "NO_ATTRITION_WARNING"))
                    leak = sum(1 for r in rows if r.get("point_in_time_safe") != "TRUE" or r.get("leakage_violation_reason"))
                    common = {
                        "filter_variant": variant, "bucket": bucket, "refill_mode": mode, "forward_return_window": window,
                        "sampled_asof_count": len(selected_counts[window]), "eligible_asof_count": len(asof_counter),
                        "baseline_sample_count": total, "candidate_sample_count": selected,
                        "average_names_per_asof": fmt(mean(selected_counts[window])), "min_names_per_asof": min(selected_counts[window]) if selected_counts[window] else 0,
                        "percent_asof_with_at_least_20_names": fmt(sum(1 for c in selected_counts[window] if c >= 20) / len(selected_counts[window]) if selected_counts[window] else 0),
                        "percent_asof_with_at_least_10_names": fmt(sum(1 for c in selected_counts[window] if c >= 10) / len(selected_counts[window]) if selected_counts[window] else 0),
                        "sample_attrition_rate": fmt(attr), "unique_asof_count": len(asof_counter), "unique_ticker_count": len(ticker_counter),
                        "mean_forward_return": fmt(mean([a for a, _ in paired])), "median_forward_return": fmt(median([a for a, _ in paired])),
                        "mean_QQQ_return": fmt(mean([b for _, b in paired])), "median_QQQ_return": fmt(median([b for _, b in paired])),
                        "mean_excess_vs_QQQ": fmt(ex), "median_excess_vs_QQQ": fmt(median(excesses)),
                        "hit_rate_vs_QQQ": fmt(hit), "hit_rate_improvement_vs_baseline": fmt((hit or 0.0) - base_hit),
                        "excess_change_vs_baseline": fmt((ex or 0.0) - base_ex), "positive_return_rate": fmt(sum(1 for a, _ in paired if a > 0) / len(paired) if paired else None),
                        "average_win_vs_QQQ": fmt(mean(wins)), "average_loss_vs_QQQ": fmt(mean(losses)), "payoff_ratio_vs_QQQ": fmt(payoff),
                        "downside_capture_vs_QQQ": "", "worst_5pct_excess_vs_QQQ": fmt(pctile(excesses, 0.05)), "best_5pct_excess_vs_QQQ": fmt(pctile(excesses, 0.95)),
                        "concentration_warning": yn(conc_warn), "attrition_warning": attr_warn,
                        "leakage_violation_count": leak, "price_missing_count": sum(1 for r in rows if r.get("price_alignment_status") != "AVAILABLE"),
                        "benchmark_missing_count": sum(1 for r in rows if r.get("benchmark_alignment_status") != "AVAILABLE"),
                        "filter_adopted": "FALSE", **GUARDRAILS,
                    }
                    summaries.append(common)
                    comparisons.append({k: common[k] for k in ["filter_variant", "bucket", "refill_mode", "forward_return_window", "hit_rate_vs_QQQ", "hit_rate_improvement_vs_baseline", "mean_excess_vs_QQQ", "excess_change_vs_baseline", "filter_adopted", *GUARDRAILS.keys()]})
                    attrition_rows.append({k: common[k] for k in ["filter_variant", "bucket", "refill_mode", "forward_return_window", "baseline_sample_count", "candidate_sample_count", "average_names_per_asof", "min_names_per_asof", "percent_asof_with_at_least_20_names", "percent_asof_with_at_least_10_names", "sample_attrition_rate", "attrition_warning", "filter_adopted", *GUARDRAILS.keys()]})
                    conc_rows.append({"filter_variant": variant, "bucket": bucket, "refill_mode": mode, "forward_return_window": window, "unique_asof_count": len(asof_counter), "unique_ticker_count": len(ticker_counter), "top_5_asof_contribution_share": fmt(top5_asof), "top_10_ticker_contribution_share": fmt(top10_share), "concentration_warning": yn(conc_warn), "filter_adopted": "FALSE", **GUARDRAILS})
                    payoff_rows.append({"filter_variant": variant, "bucket": bucket, "refill_mode": mode, "forward_return_window": window, "average_win_vs_QQQ": fmt(mean(wins)), "average_loss_vs_QQQ": fmt(mean(losses)), "payoff_ratio_vs_QQQ": fmt(payoff), "worst_5pct_excess_vs_QQQ": fmt(pctile(excesses, 0.05)), "best_5pct_excess_vs_QQQ": fmt(pctile(excesses, 0.95)), "payoff_downside_warning": yn((payoff or 0.0) < 1.0), "filter_adopted": "FALSE", **GUARDRAILS})
    return panel_out, summaries, comparisons, attrition_rows, conc_rows, payoff_rows


def classify(rows: list[dict[str, object]], base: dict[str, dict[str, float]]) -> tuple[str, str, dict[str, object]]:
    best: dict[str, object] = {}
    best_score = -999.0
    variants = sorted({r["filter_variant"] for r in rows if r["filter_variant"] not in {"BASELINE_TECHNICAL_ONLY", "COMBINED_CONSERVATIVE_ORIGINAL"} and r["bucket"] == "Top20"})
    for variant in variants:
        mode_rows = [r for r in rows if r["filter_variant"] == variant and r["bucket"] == "Top20"]
        for mode in sorted({r["refill_mode"] for r in mode_rows}):
            ws = [r for r in mode_rows if r["refill_mode"] == mode]
            if len(ws) < 4:
                continue
            hit_improved = sum(1 for r in ws if (num(r["hit_rate_improvement_vs_baseline"]) or 0) > 0)
            short_ok = all((num(r["hit_rate_improvement_vs_baseline"]) or 0) >= 0.03 for r in ws if r["forward_return_window"] in {"5D", "10D"})
            positive_excess = sum(1 for r in ws if (num(r["mean_excess_vs_QQQ"]) or 0) > 0)
            max_attr = max(num(r["sample_attrition_rate"]) or 0 for r in ws)
            leaks = sum(int(r["leakage_violation_count"]) for r in ws)
            conc = any(r["concentration_warning"] == "TRUE" for r in ws)
            long_damage = any(
                r["forward_return_window"] in {"20D", "60D"}
                and (num(r["excess_change_vs_baseline"]) or 0) < 0
                and abs(num(r["excess_change_vs_baseline"]) or 0) / abs(base.get(str(r["forward_return_window"]), {}).get("excess", 1.0)) > 0.35
                for r in ws
            )
            payoff_bad = sum(1 for r in ws if (num(r["payoff_ratio_vs_QQQ"]) or 0) < 1.0)
            if max_attr < 0.80 and hit_improved >= 2 and short_ok and positive_excess >= 3 and not long_damage and not conc and leaks == 0 and payoff_bad <= 2:
                cls = "BALANCED_PROMISING_REVIEW_ONLY"
            elif hit_improved >= 2 and max_attr >= 0.80:
                cls = "HIT_RATE_IMPROVES_BUT_ATTRITION_HIGH"
            elif hit_improved >= 2 and long_damage:
                cls = "DAMAGES_RIGHT_TAIL_TOO_MUCH"
            elif hit_improved >= 2:
                cls = "SHORT_WINDOW_ONLY_FILTER"
            else:
                cls = "NO_IMPROVEMENT_VS_BASELINE"
            score = sum(num(r["hit_rate_improvement_vs_baseline"]) or 0 for r in ws) - max_attr - (0.25 if long_damage else 0) - (0.20 if conc else 0)
            candidate = {"filter_variant": variant, "refill_mode": mode, "classification": cls, "max_attrition": max_attr, "hit_improved": hit_improved, "positive_excess": positive_excess, "long_damage": long_damage, "concentration": conc}
            if score > best_score:
                best_score = score
                best = candidate
    return str(best.get("classification", "NO_IMPROVEMENT_VS_BASELINE")), str(best.get("filter_variant", "NONE")), best


def main() -> int:
    OPT.mkdir(parents=True, exist_ok=True)
    READ_CENTER.mkdir(parents=True, exist_ok=True)
    required = [R1_COLS, R1_REGISTER, R1_PANEL, R1_SUMMARY, R1_HIT, R1_DOWN, R1_ATTR, R1_DECISION, R2_DECISION, R2_ATTR, R2_CONC, R2_PAYOFF, R5_PANEL, R5_SUMMARY, R5_QQQ, R6_DECISION, TICKER_PRICES, BENCHMARK_PRICES]
    inputs_ready = all(p.exists() and p.stat().st_size > 0 for p in required)
    r2 = (read_rows(R2_DECISION) or [{}])[0]
    r1 = (read_rows(R1_DECISION) or [{}])[0]
    panel = read_rows(R5_PANEL)
    base = baseline(read_rows(R5_SUMMARY))
    tech, tech_fields = load_tech()
    qqq = regime(load_series(BENCHMARK_PRICES, "QQQ"))
    register, col_audit = variant_rows(tech_fields, bool(qqq))
    write_rows(VARIANT_REGISTER, register)
    write_rows(COL_AUDIT, col_audit)
    if inputs_ready and panel and base:
        panel_out, summaries, comparisons, attr, conc, payoff = evaluate(panel, tech, qqq, [r["filter_variant"] for r in register], base)
    else:
        panel_out, summaries, comparisons, attr, conc, payoff = [], [], [], [], [], []
    write_rows(PANEL_OUT, panel_out)
    write_rows(SUMMARY_OUT, summaries)
    write_rows(HIT_EXCESS_OUT, comparisons)
    write_rows(ATTRITION_OUT, attr)
    write_rows(CONC_OUT, conc)
    write_rows(PAYOFF_OUT, payoff)

    classification, best_filter, best = classify(summaries, base)
    column_limited = any(r["variant_status"] == "COLUMN_LIMITED" for r in register)
    scope_ok = all(GUARDRAILS[f] == "FALSE" for f in FALSE_GUARDRAILS)
    if not inputs_ready or r2.get("recommended_next_stage") != STAGE:
        final_status, decision, next_stage = INPUT_BLOCKED, "NO_SOFT_FILTER_BEATS_BASELINE_KEEP_TECHNICAL_ONLY", "V21.045-R2_TECHNICAL_ONLY_FILTER_REVIEW_GATE"
    elif not scope_ok:
        final_status, decision, next_stage = SCOPE_BLOCKED, "NO_SOFT_FILTER_BEATS_BASELINE_KEEP_TECHNICAL_ONLY", STAGE
    elif classification == "BALANCED_PROMISING_REVIEW_ONLY":
        final_status, decision, next_stage = PASS_STATUS, "SOFT_FILTER_BALANCED_CANDIDATE_FOUND_REVIEW_ONLY", "V21.045-R4_SOFT_FILTER_REVIEW_GATE"
    elif classification == "HIT_RATE_IMPROVES_BUT_ATTRITION_HIGH":
        final_status, decision, next_stage = WARN_STATUS, "SOFT_FILTER_IMPROVES_HIT_RATE_BUT_STILL_TOO_CONCENTRATED", "V21.045-R3A_SHORT_WINDOW_FILTER_REVIEW"
    elif classification in {"DAMAGES_RIGHT_TAIL_TOO_MUCH", "SHORT_WINDOW_ONLY_FILTER"}:
        final_status, decision, next_stage = WARN_STATUS, "SOFT_FILTER_REDUCES_ATTRITION_BUT_LOSES_EDGE", "V21.045-R3A_SHORT_WINDOW_FILTER_REVIEW"
    elif column_limited:
        final_status, decision, next_stage = COLUMN_STATUS, "RUN_FILTER_COLUMN_SOURCE_REPAIR", "V21.045-R1A_TECHNICAL_FILTER_COLUMN_SOURCE_REPAIR"
    else:
        final_status, decision, next_stage = WARN_STATUS, "NO_SOFT_FILTER_BEATS_BASELINE_KEEP_TECHNICAL_ONLY", "V21.045-R3B_BASELINE_TECHNICAL_RETENTION_WITH_DOWNSIDE_MONITOR"

    best_rows = [r for r in summaries if r.get("filter_variant") == best_filter and r.get("bucket") == "Top20" and r.get("refill_mode") == best.get("refill_mode")]
    hit_summary = "|".join(f"{r['forward_return_window']}:{float(r['hit_rate_improvement_vs_baseline']):+.4f}" for r in best_rows) if best_rows else "NONE"
    excess_summary = "|".join(f"{r['forward_return_window']}:{float(r['excess_change_vs_baseline']):+.4f}" for r in best_rows) if best_rows else "NONE"
    max_attr = max((num(r["sample_attrition_rate"]) or 0 for r in best_rows), default=0.0)
    original_attr = r2.get("max_sample_attrition_rate", "")
    concentration_result = "CONCENTRATION_WARNING" if any(r.get("concentration_warning") == "TRUE" for r in best_rows) else "NO_SEVERE_CONCENTRATION_WARNING"
    payoff_result = "PAYOFF_DOWNSIDE_WARNING" if any((num(r.get("payoff_ratio_vs_QQQ")) or 0) < 1.0 for r in best_rows) else "PAYOFF_ACCEPTABLE"
    balanced = classification == "BALANCED_PROMISING_REVIEW_ONLY"
    decision_row = {
        "stage": STAGE, "final_status": final_status, "decision": decision,
        "r1_status": r1.get("final_status", ""), "r2_status": r2.get("final_status", ""),
        "r2_not_adoptable_reason": "EXTREME_ATTRITION_CONCENTRATION_PAYOFF_WARNING",
        "soft_variants_tested": "|".join(r["filter_variant"] for r in register),
        "best_soft_filter_candidate": best_filter, "best_refill_mode": best.get("refill_mode", ""),
        "best_candidate_classification": classification,
        "hit_rate_improvement_vs_baseline": hit_summary,
        "excess_preservation_degradation_vs_baseline": excess_summary,
        "attrition_comparison_vs_original_combined_filter": f"original_max={original_attr}|soft_max={fmt(max_attr)}",
        "concentration_audit_result": concentration_result,
        "payoff_downside_result": payoff_result,
        "balanced_candidate_found": yn(balanced),
        "filter_adopted": "FALSE",
        "recommended_next_stage": next_stage,
        "online_download_attempted": "FALSE", "yfinance_used": "FALSE",
        **GUARDRAILS,
    }
    write_rows(DECISION_OUT, [decision_row])

    baseline_text = "\n".join(f"- {w}: excess {fmt(base.get(w, {}).get('excess'))}, hit rate {fmt(base.get(w, {}).get('hit'))}" for w in WINDOWS)
    report = f"""# V21.045-R3 soft combined filter threshold relaxation dry-run

final_status: {final_status}

decision: {decision}

why R2 filter was not adoptable: extreme attrition, concentration warning, payoff warning, and 60D degradation risk.

Baseline canonical R5 results:

{baseline_text}

Soft variants tested: {decision_row['soft_variants_tested']}

Best soft filter candidate: {best_filter}

Hit-rate improvement vs baseline: {hit_summary}

Excess preservation vs baseline: {excess_summary}

Attrition comparison vs original combined filter: {decision_row['attrition_comparison_vs_original_combined_filter']}

Concentration comparison: {concentration_result}

Payoff/downside comparison: {payoff_result}

Balanced candidate found: {yn(balanced)}

Any filter remains review-only: TRUE

No filter was adopted.

Technical-only soft filter results must not be interpreted as full-weight results or full-weight evidence.

Full-weight remains blocked: TRUE. full_weight_result_available=FALSE and full_weight_rebacktest_allowed_now=FALSE.

Recommended next stage: {next_stage}

Guardrail statement: this stage is research-only and soft-filter-relaxation-dry-run-only. It used only predefined registered variants, did not adopt a filter, did not mutate official ranking or weights, did not create official recommendations, did not enable official or shadow adoption, did not enable a shadow gate, did not run a full-weight backtest, did not write real-book, broker, execution, or trade-action files, did not download data, did not use yfinance, and did not fabricate scores, dates, returns, filter flags, or family labels.
"""
    REPORT.write_text(report, encoding="utf-8")
    shutil.copyfile(REPORT, CURRENT_REPORT)

    print(f"final_status={final_status}")
    print(f"decision={decision}")
    print(f"best_soft_filter_candidate={best_filter}")
    print(f"attrition_summary={decision_row['attrition_comparison_vs_original_combined_filter']}")
    print(f"recommended_next_stage={next_stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
