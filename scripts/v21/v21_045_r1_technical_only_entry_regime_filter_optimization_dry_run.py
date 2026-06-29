#!/usr/bin/env python
"""Research-only Technical-only entry/regime filter optimization dry-run."""

from __future__ import annotations

import csv
import math
import shutil
import statistics
from collections import defaultdict
from pathlib import Path


STAGE = "V21.045-R1_TECHNICAL_ONLY_ENTRY_REGIME_FILTER_OPTIMIZATION_DRY_RUN"
PASS_STATUS = "PASS_V21_045_R1_FILTER_OPTIMIZATION_DRY_RUN_READY"
COLUMN_LIMITED_STATUS = "PARTIAL_PASS_V21_045_R1_FILTER_OPTIMIZATION_COLUMN_LIMITED"
WARN_STATUS = "PARTIAL_PASS_V21_045_R1_FILTER_OPTIMIZATION_WITH_WARNINGS"
BASELINE_BLOCKED = "BLOCKED_V21_045_R1_CANONICAL_TECHNICAL_BASELINE_NOT_FOUND"
PRICE_BLOCKED = "BLOCKED_V21_045_R1_PRICE_OR_BENCHMARK_SOURCE_NOT_FOUND"
SCOPE_BLOCKED = "BLOCKED_V21_045_R1_SCOPE_BOUNDARY_FAILED"

ROOT = Path(__file__).resolve().parents[2]
BACKTEST = ROOT / "outputs" / "v21" / "backtest"
REVIEW = ROOT / "outputs" / "v21" / "review"
FACTORS = ROOT / "outputs" / "v21" / "factors"
OPT = ROOT / "outputs" / "v21" / "optimization"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"
PRICE_HISTORY = ROOT / "outputs" / "v20" / "price_history"

R5_PANEL = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_REBACKTEST_PANEL.csv"
R5_SUMMARY = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_VARIANT_WINDOW_SUMMARY.csv"
R5_QQQ = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_QQQ_BENCHMARK_COMPARISON.csv"
R5A_DECISION = REVIEW / "V21_044_R5A_RECONCILIATION_DECISION_SUMMARY.csv"
R6_DECISION = REVIEW / "V21_044_R6_CONTINUITY_GATE_DECISION_SUMMARY.csv"
R4_SCORE_PANEL = REVIEW / "V21_044_R4_TECHNICAL_ONLY_HISTORICAL_SCORE_PANEL.csv"
TICKER_PRICES = PRICE_HISTORY / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
BENCHMARK_PRICES = PRICE_HISTORY / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"
TECH_SNAPSHOT = FACTORS / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv"

COL_AUDIT = OPT / "V21_045_R1_FILTER_COLUMN_AVAILABILITY_AUDIT.csv"
VARIANT_REGISTER = OPT / "V21_045_R1_FILTER_VARIANT_DEFINITION_REGISTER.csv"
FILTERED_PANEL = OPT / "V21_045_R1_FILTERED_REBACKTEST_PANEL.csv"
WINDOW_SUMMARY = OPT / "V21_045_R1_FILTER_VARIANT_WINDOW_SUMMARY.csv"
HIT_PAYOFF = OPT / "V21_045_R1_FILTER_HIT_RATE_AND_PAYOFF_AUDIT.csv"
DOWNSIDE = OPT / "V21_045_R1_FILTER_DOWNSIDE_AUDIT.csv"
ATTRITION = OPT / "V21_045_R1_FILTER_SAMPLE_ATTRITION_AUDIT.csv"
DECISION_SUMMARY = OPT / "V21_045_R1_FILTER_OPTIMIZATION_DECISION_SUMMARY.csv"
REPORT = READ_CENTER / "V21_045_R1_TECHNICAL_ONLY_ENTRY_REGIME_FILTER_OPTIMIZATION_DRY_RUN_REPORT.md"
CURRENT_REPORT = READ_CENTER / "CURRENT_V21_045_R1_TECHNICAL_ONLY_ENTRY_REGIME_FILTER_OPTIMIZATION_DRY_RUN_REPORT.md"

WINDOWS = ["5D", "10D", "20D", "60D"]
BUCKETS = [("Top20", 20), ("Top50", 50)]
REFILL_MODES = ["strict_filter_no_refill", "filter_then_refill_from_next_ranked_names"]

GUARDRAILS = {
    "research_only": "TRUE",
    "optimization_dry_run_only": "TRUE",
    "technical_only_filter_overlay": "TRUE",
    "filter_adoption_allowed": "FALSE",
    "technical_only_observation_allowed": "TRUE_INHERITED_FROM_R6_NOT_NEWLY_ADOPTED",
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
    "filter_adoption_allowed",
    "full_weight_result_available",
    "full_weight_rebacktest_allowed_now",
    "official_adoption_allowed",
    "official_weight_mutation",
    "official_ranking_mutation",
    "official_recommendation_allowed",
    "real_book_action_allowed",
    "broker_execution_allowed",
    "trade_action_allowed",
    "shadow_gate_allowed",
    "shadow_adoption_allowed",
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


def norm(value: object) -> str:
    return str(value or "").strip()


def num(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.10f}"


def mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def pctile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(max(int(math.floor((len(ordered) - 1) * p)), 0), len(ordered) - 1)
    return ordered[idx]


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    def ranks(values: list[float]) -> list[float]:
        order = sorted((value, i) for i, value in enumerate(values))
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and order[j + 1][0] == order[i][0]:
                j += 1
            rank = (i + j + 2) / 2.0
            for k in range(i, j + 1):
                out[order[k][1]] = rank
            i = j + 1
        return out
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx <= 0 or vy <= 0:
        return None
    return cov / math.sqrt(vx * vy)


def load_technical_snapshot() -> tuple[dict[tuple[str, str], dict[str, str]], list[str]]:
    rows = read_rows(TECH_SNAPSHOT)
    if not rows:
        return {}, []
    fields = list(rows[0].keys())
    out = {(row.get("as_of_date", ""), row.get("ticker", "")): row for row in rows}
    return out, fields


def load_price_series(path: Path, symbol_filter: str) -> dict[str, float]:
    rows = read_rows(path)
    series: dict[str, float] = {}
    for row in rows:
        symbol = norm(row.get("symbol")).upper()
        if symbol != symbol_filter.upper():
            continue
        value = num(row.get("adjusted_close")) or num(row.get("close"))
        day = norm(row.get("date"))
        if day and value is not None:
            series[day] = value
    return dict(sorted(series.items()))


def rolling_regime(series: dict[str, float]) -> dict[str, dict[str, bool]]:
    dates = list(series)
    values = [series[day] for day in dates]
    out: dict[str, dict[str, bool]] = {}
    for i, day in enumerate(dates):
        ma20 = mean(values[max(0, i - 19): i + 1])
        ma50 = mean(values[max(0, i - 49): i + 1])
        ma20_prior = mean(values[max(0, i - 24): max(0, i - 4)]) if i >= 23 else None
        out[day] = {
            "above_ma20": bool(ma20 is not None and values[i] > ma20),
            "above_ma50": bool(ma50 is not None and values[i] > ma50),
            "ma20_slope_positive": bool(ma20 is not None and ma20_prior is not None and ma20 > ma20_prior),
        }
    return out


def baseline_rows(summary: list[dict[str, str]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for row in summary:
        window = row.get("forward_return_window", "")
        if window in WINDOWS:
            out[window] = {
                "mean_excess_vs_QQQ": num(row.get("top20_excess_vs_QQQ")) or 0.0,
                "hit_rate_vs_QQQ": num(row.get("top20_hit_rate_vs_QQQ")) or 0.0,
                "mean_forward_return": num(row.get("top20_mean_forward_return")) or 0.0,
            }
    return out


def column_availability(fields: list[str], qqq_available: bool, soxx_available: bool) -> list[dict[str, object]]:
    requirements = {
        "OVERHEAT_EXCLUSION_FILTER": ["rsi_14", "kdj_j", "ma20_distance", "ma50_distance", "bb_position", "momentum_5"],
        "PULLBACK_HEALTHY_TREND_FILTER": ["close", "ma20", "ma50", "bb_middle_20", "ema20", "ma20_distance"],
        "QQQ_REGIME_FILTER": ["QQQ_LOCAL_PRICE_HISTORY"],
        "SOXX_CONFIRMATION_FILTER": ["SOXX_LOCAL_PRICE_HISTORY"],
        "COMBINED_CONSERVATIVE_FILTER": ["rsi_14", "kdj_j", "ma20_distance", "close", "ma20", "ma50", "QQQ_LOCAL_PRICE_HISTORY"],
        "ENTRY_FILTER_WATCHLIST_ONLY": ["rsi_14", "kdj_j", "ma20_distance"],
    }
    have = set(fields)
    rows = []
    for variant, required in requirements.items():
        available = []
        missing = []
        for col in required:
            if col == "QQQ_LOCAL_PRICE_HISTORY":
                (available if qqq_available else missing).append(col)
            elif col == "SOXX_LOCAL_PRICE_HISTORY":
                (available if soxx_available else missing).append(col)
            elif col in have:
                available.append(col)
            else:
                missing.append(col)
        rows.append({
            "filter_variant": variant,
            "required_columns_or_sources": "|".join(required),
            "available_columns_or_sources": "|".join(available),
            "missing_columns_or_sources": "|".join(missing),
            "availability_status": "AVAILABLE" if not missing else ("SOURCE_UNAVAILABLE" if variant == "SOXX_CONFIRMATION_FILTER" else "COLUMN_LIMITED"),
            **GUARDRAILS,
        })
    return rows


def variant_register(col_audit: list[dict[str, object]]) -> list[dict[str, object]]:
    status = {row["filter_variant"]: row["availability_status"] for row in col_audit}
    definitions = [
        ("BASELINE_TECHNICAL_ONLY", "No overlay; canonical R5 conservative Technical-only baseline.", "NONE", "AVAILABLE"),
        ("OVERHEAT_EXCLUSION_FILTER", "Exclude rows with predefined overheat conditions.", "rsi_14>=70 OR kdj_j>=90 OR ma20_distance>0.10 OR ma50_distance>0.18 OR bb_position>1.0 OR momentum_5>0.12", status.get("OVERHEAT_EXCLUSION_FILTER", "COLUMN_LIMITED")),
        ("PULLBACK_HEALTHY_TREND_FILTER", "Keep healthy trend rows with limited extension.", "close>ma20 AND ma20>ma50 AND -0.03<=ma20_distance<=0.08", status.get("PULLBACK_HEALTHY_TREND_FILTER", "COLUMN_LIMITED")),
        ("QQQ_REGIME_FILTER", "Allow rows only when QQQ local regime is supportive.", "QQQ adjusted_close>MA20 AND adjusted_close>MA50 AND MA20 slope positive", status.get("QQQ_REGIME_FILTER", "COLUMN_LIMITED")),
        ("SOXX_CONFIRMATION_FILTER", "Require SOXX local confirmation when available.", "SOXX adjusted_close>MA20 AND adjusted_close>MA50 AND 20D relative strength vs QQQ positive when feasible", status.get("SOXX_CONFIRMATION_FILTER", "SOURCE_UNAVAILABLE")),
        ("COMBINED_CONSERVATIVE_FILTER", "Combine QQQ regime, non-overheat, healthy pullback, and optional SOXX confirmation.", "QQQ supportive AND NOT overheat AND healthy trend/pullback AND SOXX if available", status.get("COMBINED_CONSERVATIVE_FILTER", "COLUMN_LIMITED")),
        ("ENTRY_FILTER_WATCHLIST_ONLY", "Softer watchlist overlay; Top50 retained while overextended Top20-like rows are flagged out of active observation.", "Top50 retained; active flag requires not overheated", status.get("ENTRY_FILTER_WATCHLIST_ONLY", "COLUMN_LIMITED")),
    ]
    return [
        {
            "filter_variant": name,
            "definition": definition,
            "predefined_rule": rule,
            "refill_modes_tested": "|".join(REFILL_MODES),
            "filter_adopted": "FALSE",
            "variant_status": availability,
            **GUARDRAILS,
        }
        for name, definition, rule, availability in definitions
    ]


def technical_flags(row: dict[str, str]) -> dict[str, bool]:
    rsi = num(row.get("rsi_14"))
    kdj_j = num(row.get("kdj_j"))
    ma20_dist = num(row.get("ma20_distance"))
    ma50_dist = num(row.get("ma50_distance"))
    bb_pos = num(row.get("bb_position"))
    momentum_5 = num(row.get("momentum_5"))
    close = num(row.get("close"))
    ma20 = num(row.get("ma20"))
    ma50 = num(row.get("ma50"))
    overheat = any([
        rsi is not None and rsi >= 70,
        kdj_j is not None and kdj_j >= 90,
        ma20_dist is not None and ma20_dist > 0.10,
        ma50_dist is not None and ma50_dist > 0.18,
        bb_pos is not None and bb_pos > 1.0,
        momentum_5 is not None and momentum_5 > 0.12,
    ])
    healthy = all([
        close is not None and ma20 is not None and close > ma20,
        ma20 is not None and ma50 is not None and ma20 > ma50,
        ma20_dist is not None and -0.03 <= ma20_dist <= 0.08,
    ])
    return {"not_overheat": not overheat, "healthy_pullback": healthy}


def row_passes(variant: str, row: dict[str, str], tech: dict[str, str], qqq_regime: dict[str, dict[str, bool]], soxx_regime: dict[str, dict[str, bool]]) -> bool:
    day = row.get("as_of_date", "")
    flags = technical_flags(tech)
    q = qqq_regime.get(day, {})
    s = soxx_regime.get(day, {})
    q_support = bool(q.get("above_ma20") and q.get("above_ma50") and q.get("ma20_slope_positive"))
    s_support = bool(s.get("above_ma20") and s.get("above_ma50")) if soxx_regime else True
    if variant == "BASELINE_TECHNICAL_ONLY":
        return True
    if variant == "OVERHEAT_EXCLUSION_FILTER":
        return flags["not_overheat"]
    if variant == "PULLBACK_HEALTHY_TREND_FILTER":
        return flags["healthy_pullback"]
    if variant == "QQQ_REGIME_FILTER":
        return q_support
    if variant == "SOXX_CONFIRMATION_FILTER":
        return s_support
    if variant == "COMBINED_CONSERVATIVE_FILTER":
        return q_support and flags["not_overheat"] and flags["healthy_pullback"] and s_support
    if variant == "ENTRY_FILTER_WATCHLIST_ONLY":
        return flags["not_overheat"]
    return False


def evaluate(panel: list[dict[str, str]], tech_lookup: dict[tuple[str, str], dict[str, str]], qqq_regime: dict[str, dict[str, bool]], soxx_regime: dict[str, dict[str, bool]], variants: list[str]) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    by_window_asof: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in panel:
        if row.get("included_in_performance_aggregation") == "TRUE" and row.get("forward_return_window") in WINDOWS:
            by_window_asof[(row["forward_return_window"], row["as_of_date"])].append(row)
    panel_out: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    attrition_rows: list[dict[str, object]] = []
    for variant in variants:
        for mode in REFILL_MODES:
            for bucket, limit in BUCKETS:
                selected_by_window: dict[str, list[dict[str, str]]] = defaultdict(list)
                sampled_asofs_by_window: dict[str, set[str]] = defaultdict(set)
                eligible_asofs_by_window: dict[str, set[str]] = defaultdict(set)
                total_candidates_by_window: dict[str, int] = defaultdict(int)
                selected_counts_by_window: dict[str, list[int]] = defaultdict(list)
                insufficient_by_window: dict[str, int] = defaultdict(int)
                for (window, asof), rows in by_window_asof.items():
                    ranked = sorted(rows, key=lambda r: num(r.get("technical_only_rank")) or 999999)
                    candidates = ranked[:limit]
                    total_candidates_by_window[window] += len(candidates)
                    sampled_asofs_by_window[window].add(asof)
                    passers = []
                    excluded = []
                    for candidate in candidates:
                        tech = tech_lookup.get((asof, candidate.get("ticker", "")), {})
                        passed = row_passes(variant, candidate, tech, qqq_regime, soxx_regime)
                        (passers if passed else excluded).append(candidate)
                    selected = list(passers)
                    if mode == "filter_then_refill_from_next_ranked_names" and variant not in {"BASELINE_TECHNICAL_ONLY", "ENTRY_FILTER_WATCHLIST_ONLY"} and len(selected) < limit:
                        for candidate in ranked[limit:]:
                            tech = tech_lookup.get((asof, candidate.get("ticker", "")), {})
                            if row_passes(variant, candidate, tech, qqq_regime, soxx_regime):
                                selected.append(candidate)
                            if len(selected) >= limit:
                                break
                    if selected:
                        eligible_asofs_by_window[window].add(asof)
                    if len(selected) < limit:
                        insufficient_by_window[window] += 1
                    selected_counts_by_window[window].append(len(selected))
                    for candidate in selected:
                        selected_by_window[window].append(candidate)
                        fwd = num(candidate.get("realized_forward_return"))
                        bench = num(candidate.get("benchmark_forward_return"))
                        excess = fwd - bench if fwd is not None and bench is not None else None
                        panel_out.append({
                            "filter_variant": variant,
                            "bucket": bucket,
                            "refill_mode": mode,
                            "as_of_date": asof,
                            "ticker": candidate.get("ticker", ""),
                            "technical_only_rank": candidate.get("technical_only_rank", ""),
                            "forward_return_window": window,
                            "realized_forward_return": candidate.get("realized_forward_return", ""),
                            "benchmark_forward_return": candidate.get("benchmark_forward_return", ""),
                            "excess_vs_QQQ": fmt(excess),
                            "filter_passed": "TRUE",
                            "filter_adopted": "FALSE",
                            "point_in_time_safe": candidate.get("point_in_time_safe", ""),
                            "leakage_violation_reason": candidate.get("leakage_violation_reason", ""),
                            **GUARDRAILS,
                        })
                for window in WINDOWS:
                    selected = selected_by_window[window]
                    returns = [num(row.get("realized_forward_return")) for row in selected]
                    bench_returns = [num(row.get("benchmark_forward_return")) for row in selected]
                    paired = [(a, b) for a, b in zip(returns, bench_returns) if a is not None and b is not None]
                    excesses = [a - b for a, b in paired]
                    wins = [x for x in excesses if x > 0]
                    losses = [x for x in excesses if x < 0]
                    rank_ic_values = []
                    for asof in sampled_asofs_by_window[window]:
                        asof_rows = [row for row in selected if row.get("as_of_date") == asof]
                        ranks = [num(row.get("technical_only_rank")) for row in asof_rows]
                        rets = [num(row.get("realized_forward_return")) for row in asof_rows]
                        valid = [(r, ret) for r, ret in zip(ranks, rets) if r is not None and ret is not None]
                        if len(valid) >= 3:
                            # Lower rank is better, so invert rank for positive association.
                            ic = spearman([-r for r, _ in valid], [ret for _, ret in valid])
                            if ic is not None:
                                rank_ic_values.append(ic)
                    sampled = len(sampled_asofs_by_window[window])
                    eligible = len(eligible_asofs_by_window[window])
                    total_candidates = total_candidates_by_window[window]
                    selected_count = len(selected)
                    attrition = 1.0 - (selected_count / total_candidates) if total_candidates else 0.0
                    summary = {
                        "filter_variant": variant,
                        "bucket": bucket,
                        "refill_mode": mode,
                        "forward_return_window": window,
                        "sampled_asof_count": sampled,
                        "eligible_asof_count": eligible,
                        "average_names_per_asof": fmt(mean(selected_counts_by_window[window])),
                        "sample_attrition_rate": fmt(attrition),
                        "mean_forward_return": fmt(mean([a for a, _ in paired])),
                        "median_forward_return": fmt(median([a for a, _ in paired])),
                        "mean_QQQ_return": fmt(mean([b for _, b in paired])),
                        "median_QQQ_return": fmt(median([b for _, b in paired])),
                        "mean_excess_vs_QQQ": fmt(mean(excesses)),
                        "median_excess_vs_QQQ": fmt(median(excesses)),
                        "hit_rate_vs_QQQ": fmt(len(wins) / len(excesses) if excesses else None),
                        "positive_return_rate": fmt(sum(1 for a, _ in paired if a > 0) / len(paired) if paired else None),
                        "average_win_vs_QQQ": fmt(mean(wins)),
                        "average_loss_vs_QQQ": fmt(mean(losses)),
                        "payoff_ratio_vs_QQQ": fmt((mean(wins) / abs(mean(losses))) if wins and losses and mean(losses) else None),
                        "downside_capture_vs_QQQ": fmt((abs(mean([a for a, _ in paired if a < 0])) / abs(mean([b for _, b in paired if b < 0]))) if any(a < 0 for a, _ in paired) and any(b < 0 for _, b in paired) and mean([b for _, b in paired if b < 0]) else None),
                        "worst_5pct_excess_vs_QQQ": fmt(pctile(excesses, 0.05)),
                        "best_5pct_excess_vs_QQQ": fmt(pctile(excesses, 0.95)),
                        "rank_ic_spearman_mean": fmt(mean(rank_ic_values)),
                        "rank_ic_spearman_median": fmt(median(rank_ic_values)),
                        "price_missing_count": sum(1 for row in selected if row.get("price_alignment_status") != "AVAILABLE"),
                        "benchmark_missing_count": sum(1 for row in selected if row.get("benchmark_alignment_status") != "AVAILABLE"),
                        "leakage_violation_count": sum(1 for row in selected if row.get("point_in_time_safe") != "TRUE" or row.get("leakage_violation_reason")),
                        "insufficient_count_warning": yn(insufficient_by_window[window] > 0),
                        "filter_adopted": "FALSE",
                        **GUARDRAILS,
                    }
                    summaries.append(summary)
                    attrition_rows.append({
                        "filter_variant": variant,
                        "bucket": bucket,
                        "refill_mode": mode,
                        "forward_return_window": window,
                        "total_candidate_rows": total_candidates,
                        "selected_rows": selected_count,
                        "sample_attrition_rate": fmt(attrition),
                        "attrition_warning": yn(attrition > 0.60),
                        "insufficient_asof_count": insufficient_by_window[window],
                        "filter_adopted": "FALSE",
                        **GUARDRAILS,
                    })
    return panel_out, summaries, attrition_rows


def decision_from_summaries(summaries: list[dict[str, object]], baseline: dict[str, dict[str, float]], col_limited: bool) -> tuple[str, str, str, str, dict[str, dict[str, float]]]:
    best_name = ""
    best_score = -999.0
    best_changes: dict[str, dict[str, float]] = {}
    promising = False
    for variant in sorted({row["filter_variant"] for row in summaries if row["filter_variant"] != "BASELINE_TECHNICAL_ONLY"}):
        rows = [row for row in summaries if row["filter_variant"] == variant and row["bucket"] == "Top20" and row["refill_mode"] == "strict_filter_no_refill"]
        changes: dict[str, dict[str, float]] = {}
        improved_windows = 0
        positive_excess = 0
        excessive_attrition = False
        no_leakage = True
        for row in rows:
            window = str(row["forward_return_window"])
            hit = num(row.get("hit_rate_vs_QQQ")) or 0.0
            excess = num(row.get("mean_excess_vs_QQQ")) or 0.0
            attrition = num(row.get("sample_attrition_rate")) or 0.0
            base_hit = baseline.get(window, {}).get("hit_rate_vs_QQQ", 0.0)
            base_excess = baseline.get(window, {}).get("mean_excess_vs_QQQ", 0.0)
            changes[window] = {
                "hit_rate_change": hit - base_hit,
                "excess_change": excess - base_excess,
                "payoff_ratio": num(row.get("payoff_ratio_vs_QQQ")) or 0.0,
            }
            improved_windows += 1 if hit - base_hit >= 0.02 else 0
            positive_excess += 1 if excess > 0 else 0
            excessive_attrition = excessive_attrition or attrition > 0.60
            no_leakage = no_leakage and int(row.get("leakage_violation_count") or 0) == 0
        if rows:
            score = sum(ch["hit_rate_change"] for ch in changes.values()) + 0.25 * sum(ch["excess_change"] for ch in changes.values())
            is_promising = no_leakage and not excessive_attrition and positive_excess >= 3 and (
                improved_windows >= 2 or (
                    changes.get("20D", {}).get("hit_rate_change", 0.0) > 0
                    and changes.get("60D", {}).get("hit_rate_change", 0.0) > 0
                    and changes.get("5D", {}).get("hit_rate_change", 0.0) > -0.01
                    and changes.get("10D", {}).get("hit_rate_change", 0.0) > -0.01
                )
            )
            if is_promising:
                promising = True
            if score > best_score:
                best_score = score
                best_name = variant
                best_changes = changes
    if promising:
        if "OVERHEAT" in best_name:
            decision = "OVERHEAT_FILTER_PROMISING_FOR_REVIEW_ONLY"
        elif "REGIME" in best_name:
            decision = "REGIME_FILTER_PROMISING_FOR_REVIEW_ONLY"
        else:
            decision = "ENTRY_REGIME_FILTER_PROMISING_FOR_CONTINUED_SHADOW_OBSERVATION_ONLY"
        status = COLUMN_LIMITED_STATUS if col_limited else PASS_STATUS
        next_stage = "V21.045-R2_TECHNICAL_ONLY_FILTER_REVIEW_GATE"
    else:
        decision = "KEEP_BASELINE_TECHNICAL_ONLY_AND_COLLECT_MORE_EVIDENCE" if col_limited else "FILTERS_DO_NOT_IMPROVE_CANONICAL_BASELINE"
        status = COLUMN_LIMITED_STATUS if col_limited else WARN_STATUS
        next_stage = "V21.045-R1A_TECHNICAL_FILTER_COLUMN_SOURCE_REPAIR" if col_limited else "V21.045-R1B_TECHNICAL_ONLY_BASELINE_RETENTION_AND_DOWNSIDE_REVIEW"
    return status, decision, best_name or "NONE", next_stage, best_changes


def main() -> int:
    OPT.mkdir(parents=True, exist_ok=True)
    READ_CENTER.mkdir(parents=True, exist_ok=True)

    panel = read_rows(R5_PANEL)
    r5_summary = read_rows(R5_SUMMARY)
    r5_qqq = read_rows(R5_QQQ)
    r5a = read_rows(R5A_DECISION)
    r6 = read_rows(R6_DECISION)
    r4 = read_rows(R4_SCORE_PANEL)
    tech_lookup, tech_fields = load_technical_snapshot()
    qqq_series = load_price_series(BENCHMARK_PRICES, "QQQ")
    soxx_series = load_price_series(TICKER_PRICES, "SOXX")
    qqq_regime = rolling_regime(qqq_series)
    soxx_regime = rolling_regime(soxx_series) if soxx_series else {}
    baseline = baseline_rows(r5_summary)

    baseline_found = bool(panel and r5_summary and baseline and r5a and r6 and r4)
    price_found = bool(TICKER_PRICES.exists() and BENCHMARK_PRICES.exists() and qqq_series)
    col_audit = column_availability(tech_fields, bool(qqq_series), bool(soxx_series))
    write_rows(COL_AUDIT, col_audit)
    register = variant_register(col_audit)
    write_rows(VARIANT_REGISTER, register)
    col_limited = any(row["availability_status"] in {"COLUMN_LIMITED", "SOURCE_UNAVAILABLE"} for row in col_audit)

    variants = [row["filter_variant"] for row in register]
    if baseline_found and price_found:
        filtered_panel, summaries, attrition_rows = evaluate(panel, tech_lookup, qqq_regime, soxx_regime, variants)
    else:
        filtered_panel, summaries, attrition_rows = [], [], []
    write_rows(FILTERED_PANEL, filtered_panel)
    write_rows(WINDOW_SUMMARY, summaries)
    write_rows(ATTRITION, attrition_rows)

    hit_payoff_rows = []
    downside_rows = []
    for row in summaries:
        window = str(row["forward_return_window"])
        base = baseline.get(window, {})
        hit = num(row.get("hit_rate_vs_QQQ")) or 0.0
        excess = num(row.get("mean_excess_vs_QQQ")) or 0.0
        hit_payoff_rows.append({
            "filter_variant": row["filter_variant"],
            "bucket": row["bucket"],
            "refill_mode": row["refill_mode"],
            "forward_return_window": window,
            "baseline_hit_rate_vs_QQQ": fmt(base.get("hit_rate_vs_QQQ")),
            "variant_hit_rate_vs_QQQ": row["hit_rate_vs_QQQ"],
            "hit_rate_improvement_vs_baseline": fmt(hit - base.get("hit_rate_vs_QQQ", 0.0)),
            "baseline_mean_excess_vs_QQQ": fmt(base.get("mean_excess_vs_QQQ")),
            "variant_mean_excess_vs_QQQ": row["mean_excess_vs_QQQ"],
            "excess_change_vs_baseline": fmt(excess - base.get("mean_excess_vs_QQQ", 0.0)),
            "payoff_ratio_vs_QQQ": row["payoff_ratio_vs_QQQ"],
            "filter_adopted": "FALSE",
            **GUARDRAILS,
        })
        downside_rows.append({
            "filter_variant": row["filter_variant"],
            "bucket": row["bucket"],
            "refill_mode": row["refill_mode"],
            "forward_return_window": window,
            "downside_capture_vs_QQQ": row["downside_capture_vs_QQQ"],
            "worst_5pct_excess_vs_QQQ": row["worst_5pct_excess_vs_QQQ"],
            "best_5pct_excess_vs_QQQ": row["best_5pct_excess_vs_QQQ"],
            "downside_warning": yn((num(row.get("worst_5pct_excess_vs_QQQ")) or 0.0) < -0.10),
            "filter_adopted": "FALSE",
            **GUARDRAILS,
        })
    write_rows(HIT_PAYOFF, hit_payoff_rows)
    write_rows(DOWNSIDE, downside_rows)

    if not baseline_found:
        final_status, decision, best_filter, next_stage, best_changes = BASELINE_BLOCKED, "BLOCK_FILTER_OPTIMIZATION_REVIEW", "NONE", "V21.044-R5_TECHNICAL_ONLY_REBACKTEST_PANEL_REPAIR", {}
    elif not price_found:
        final_status, decision, best_filter, next_stage, best_changes = PRICE_BLOCKED, "BLOCK_FILTER_OPTIMIZATION_REVIEW", "NONE", "V21.045-R1A_TECHNICAL_FILTER_COLUMN_SOURCE_REPAIR", {}
    elif not all(GUARDRAILS[field] == "FALSE" for field in FALSE_GUARDRAILS):
        final_status, decision, best_filter, next_stage, best_changes = SCOPE_BLOCKED, "BLOCK_FILTER_OPTIMIZATION_REVIEW", "NONE", "V21.045-R1_TECHNICAL_ONLY_ENTRY_REGIME_FILTER_OPTIMIZATION_DRY_RUN", {}
    else:
        final_status, decision, best_filter, next_stage, best_changes = decision_from_summaries(summaries, baseline, col_limited)

    hit_summary = "|".join(f"{w}:{best_changes.get(w, {}).get('hit_rate_change', 0.0):+.4f}" for w in WINDOWS) if best_changes else "NONE"
    excess_summary = "|".join(f"{w}:{best_changes.get(w, {}).get('excess_change', 0.0):+.4f}" for w in WINDOWS) if best_changes else "NONE"
    payoff_summary = "|".join(f"{w}:{best_changes.get(w, {}).get('payoff_ratio', 0.0):.4f}" for w in WINDOWS) if best_changes else "NONE"
    any_promising = "PROMISING" in decision
    attrition_warning_count = sum(1 for row in attrition_rows if row.get("attrition_warning") == "TRUE")
    downside_warning_count = sum(1 for row in downside_rows if row.get("downside_warning") == "TRUE")

    decision_row = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "baseline_source": "V21_044_R5_CANONICAL_CONSERVATIVE",
        "baseline_5D_excess_vs_QQQ": fmt(baseline.get("5D", {}).get("mean_excess_vs_QQQ")),
        "baseline_5D_hit_rate_vs_QQQ": fmt(baseline.get("5D", {}).get("hit_rate_vs_QQQ")),
        "baseline_10D_excess_vs_QQQ": fmt(baseline.get("10D", {}).get("mean_excess_vs_QQQ")),
        "baseline_10D_hit_rate_vs_QQQ": fmt(baseline.get("10D", {}).get("hit_rate_vs_QQQ")),
        "baseline_20D_excess_vs_QQQ": fmt(baseline.get("20D", {}).get("mean_excess_vs_QQQ")),
        "baseline_20D_hit_rate_vs_QQQ": fmt(baseline.get("20D", {}).get("hit_rate_vs_QQQ")),
        "baseline_60D_excess_vs_QQQ": fmt(baseline.get("60D", {}).get("mean_excess_vs_QQQ")),
        "baseline_60D_hit_rate_vs_QQQ": fmt(baseline.get("60D", {}).get("hit_rate_vs_QQQ")),
        "filter_variants_tested": "|".join(variants),
        "best_filter_candidate": best_filter,
        "best_filter_adopted": "FALSE",
        "hit_rate_improvement_summary": hit_summary,
        "excess_return_change_summary": excess_summary,
        "payoff_ratio_summary": payoff_summary,
        "downside_warning_count": downside_warning_count,
        "sample_attrition_warning_count": attrition_warning_count,
        "any_filter_promising_for_review_only": yn(any_promising),
        "recommended_next_stage": next_stage,
        "r5_panel_rows_read": len(panel),
        "r5_summary_rows_read": len(r5_summary),
        "r5_qqq_rows_read": len(r5_qqq),
        "technical_snapshot_rows_joinable": len(tech_lookup),
        "online_download_attempted": "FALSE",
        "yfinance_used": "FALSE",
        **GUARDRAILS,
    }
    write_rows(DECISION_SUMMARY, [decision_row])

    baseline_text = "\n".join(
        f"- {w}: excess {fmt(baseline.get(w, {}).get('mean_excess_vs_QQQ'))}, hit rate {fmt(baseline.get(w, {}).get('hit_rate_vs_QQQ'))}"
        for w in WINDOWS
    )
    report = f"""# V21.045-R1 Technical-only entry/regime filter optimization dry-run

final_status: {final_status}

decision: {decision}

Baseline R5 canonical results:

{baseline_text}

Available filter columns: {', '.join(tech_fields) if tech_fields else 'NONE'}

Filter variants tested: {', '.join(variants)}

Best candidate filter: {best_filter}

Hit-rate comparison vs baseline: {hit_summary}

Excess return comparison vs baseline: {excess_summary}

Payoff ratio comparison: {payoff_summary}

Downside comparison: {downside_warning_count} downside warning rows in the downside audit.

Sample attrition warnings: {attrition_warning_count}

Any filter promising for review-only: {yn(any_promising)}

No filter was adopted.

Technical-only filter results must not be interpreted as full-weight results or full-weight evidence.

Full-weight remains blocked: TRUE. full_weight_result_available=FALSE and full_weight_rebacktest_allowed_now=FALSE.

Recommended next stage: {next_stage}

Guardrail statement: this stage is research-only and optimization-dry-run-only. It used predefined thresholds only, did not change official weights or rankings, did not create official recommendations, did not enable adoption or shadow gates, did not create real-book, broker, execution, or trade-action outputs, did not run a full-weight backtest, did not materialize blocked families, did not download data, and did not use yfinance.
"""
    REPORT.write_text(report, encoding="utf-8")
    shutil.copyfile(REPORT, CURRENT_REPORT)

    print(f"final_status={final_status}")
    print(f"decision={decision}")
    print(f"best_filter_candidate={best_filter}")
    print(f"hit_rate_improvement_summary={hit_summary}")
    print(f"recommended_next_stage={next_stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
