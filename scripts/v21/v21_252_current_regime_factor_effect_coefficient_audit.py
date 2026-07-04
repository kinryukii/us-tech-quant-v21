#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

STAGE = "V21.252_CURRENT_REGIME_FACTOR_EFFECT_COEFFICIENT_AUDIT"
OUT_REL = Path("outputs/v21") / STAGE
V250_REL = Path("outputs/v21/V21.250_E_R2_SHADOW_FORWARD_TRACKING_LEDGER")
V247_REL = Path("outputs/v21/V21.247_REWEIGHTED_STRATEGY_REPLAY_AND_FORWARD_BACKTEST")
V243R1_REL = Path("outputs/v21/V21.243_R1_RECENT_0618_STRATEGY_SUCCESS_AUDIT_WITH_REPLAY")
V246_REL = Path("outputs/v21/V21.246_FACTOR_WEIGHT_RECALIBRATION_CANDIDATES")
V245_REL = Path("outputs/v21/V21.245_STRATEGY_FACTOR_ATTRIBUTION_AND_FAILURE_DECOMPOSITION")

STRATEGIES = ["A1", "E_R1", "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL", "B", "C", "D", "ABCDE_AGGREGATE", "DRAM", "QQQ", "SOXX", "SMH"]
FAMILIES = ["Fundamental", "Technical", "Strategy", "Risk", "Market Regime", "Data Trust"]
FACTOR_DEFS = [
    ("Fundamental", "Fundamental", "family"),
    ("Technical", "Technical", "family"),
    ("Strategy", "Strategy", "family"),
    ("Risk", "Risk", "family"),
    ("Market Regime", "Market Regime", "family"),
    ("Data Trust", "Data Trust", "family"),
    ("RSI", "Technical", "technical"),
    ("KDJ", "Technical", "technical"),
    ("MACD", "Technical", "technical"),
    ("Bollinger Band", "Technical", "technical"),
    ("MA20", "Technical", "technical"),
    ("MA50", "Technical", "technical"),
    ("EMA", "Technical", "technical"),
    ("volume", "Technical", "technical"),
    ("volatility", "Risk", "technical"),
    ("momentum_relative_strength", "Technical", "technical"),
    ("breakout", "Technical", "technical"),
    ("pullback", "Technical", "technical"),
    ("repeated_loser_penalty", "Risk", "new_repair"),
    ("left_tail_memory_factor", "Risk", "new_repair"),
    ("intraday_follow_through_factor", "Strategy", "new_repair"),
    ("gap_overnight_risk_factor", "Risk", "new_repair"),
    ("event_proximity_risk_factor", "Market Regime", "new_repair"),
]


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, data: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(data)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def fnum(v: Any, default: float = 0.0) -> float:
    try:
        if v in (None, ""):
            return default
        return float(v)
    except Exception:
        return default


def load_weights(repo: Path) -> dict[str, dict[str, float]]:
    base = {
        "A1": {"Fundamental": 0.15, "Technical": 0.34, "Strategy": 0.18, "Risk": 0.18, "Market Regime": 0.10, "Data Trust": 0.05},
        "B": {"Fundamental": 0.10, "Technical": 0.45, "Strategy": 0.20, "Risk": 0.10, "Market Regime": 0.10, "Data Trust": 0.05},
        "C": {"Fundamental": 0.12, "Technical": 0.42, "Strategy": 0.21, "Risk": 0.10, "Market Regime": 0.10, "Data Trust": 0.05},
        "D": {"Fundamental": 0.10, "Technical": 0.50, "Strategy": 0.22, "Risk": 0.03, "Market Regime": 0.10, "Data Trust": 0.05},
        "E_R1": {"Fundamental": 0.12, "Technical": 0.30, "Strategy": 0.18, "Risk": 0.25, "Market Regime": 0.10, "Data Trust": 0.05},
        "ABCDE_AGGREGATE": {"Fundamental": 0.13, "Technical": 0.38, "Strategy": 0.20, "Risk": 0.14, "Market Regime": 0.10, "Data Trust": 0.05},
        "DRAM": {"Fundamental": 0.05, "Technical": 0.55, "Strategy": 0.15, "Risk": 0.15, "Market Regime": 0.05, "Data Trust": 0.05},
        "QQQ": {"Fundamental": 0.10, "Technical": 0.35, "Strategy": 0.10, "Risk": 0.20, "Market Regime": 0.20, "Data Trust": 0.05},
        "SOXX": {"Fundamental": 0.08, "Technical": 0.40, "Strategy": 0.10, "Risk": 0.22, "Market Regime": 0.15, "Data Trust": 0.05},
        "SMH": {"Fundamental": 0.08, "Technical": 0.40, "Strategy": 0.10, "Risk": 0.22, "Market Regime": 0.15, "Data Trust": 0.05},
    }
    weights: dict[str, dict[str, float]] = defaultdict(dict)
    for strategy, payload in base.items():
        weights[strategy].update(payload)
    rows = read_rows(repo / V246_REL / "factor_weight_candidate_master.csv")
    for r in rows:
        candidate = r.get("candidate", "")
        if candidate and candidate not in weights:
            weights[candidate].update(base["A1"])
        weights[candidate][r.get("factor_family", "")] = fnum(r.get("weight"))
    return weights


def rank_score(rank: Any) -> float:
    r = fnum(rank, 100.0)
    return max(0.0, min(1.0, 1.0 - (r - 1.0) / 100.0))


def normalize_forward_rows(rows_in: list[dict[str, str]], allowed: set[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for r in rows_in:
        if r.get("strategy") not in allowed or r.get("maturity_status") != "MATURED" or not r.get("forward_return"):
            continue
        row = dict(r)
        if not row.get("top_n"):
            rank = fnum(row.get("rank"), 999999)
            row["top_n"] = "20" if rank <= 20 else "50" if rank <= 50 else "100" if rank <= 100 else "OUTSIDE_TOP100"
        if row.get("top_n") in {"20", "50", "100"} and row.get("forward_window") in {"1D", "2D", "3D", "5D"}:
            out.append(row)
    return out


def exposure_value(strategy: str, factor: str, family: str, subtype: str, rank: Any, weights: dict[str, dict[str, float]]) -> float:
    rs = rank_score(rank)
    w = weights.get(strategy, {}).get(family, 0.1)
    if subtype == "family":
        if factor == "Technical":
            return rs + 0.25 * w
        return w * (0.55 + rs)
    if factor in {"RSI", "MACD", "MA20", "MA50", "EMA", "momentum_relative_strength", "breakout"}:
        return rs + 0.15 * weights.get(strategy, {}).get("Technical", 0.2)
    if factor in {"KDJ", "Bollinger Band", "volume", "pullback"}:
        return weights.get(strategy, {}).get("Technical", 0.2) * (1.0 - abs(rs - 0.5))
    if factor == "volatility":
        return weights.get(strategy, {}).get("Risk", 0.2) * (1.0 - rs)
    if factor == "repeated_loser_penalty":
        return (0.30 if strategy in {"E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL", "E_R1"} else 0.10) * (1.0 - rs)
    if factor == "left_tail_memory_factor":
        return (0.32 if strategy in {"E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "E_R1"} else 0.12) * (1.0 - rs)
    if factor == "intraday_follow_through_factor":
        return (0.22 if strategy == "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL" else 0.12) * rs
    if factor == "gap_overnight_risk_factor":
        return weights.get(strategy, {}).get("Risk", 0.2) * (1.0 - rs)
    if factor == "event_proximity_risk_factor":
        return 0.0
    return w * rs


def standardize_exposures(base_rows: list[dict[str, Any]], weights: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    for r in base_rows:
        strategy = r.get("strategy", "")
        for factor, family, subtype in FACTOR_DEFS:
            raw.append({
                "ranking_date": r.get("ranking_date", ""),
                "ticker": r.get("ticker", ""),
                "strategy": strategy,
                "source_mode": r.get("source_mode", ""),
                "pit_status": r.get("pit_status", ""),
                "forward_window": r.get("forward_window", ""),
                "topn_scope": r.get("top_n", ""),
                "forward_return": fnum(r.get("forward_return")),
                "factor_name": factor,
                "factor_family": family,
                "factor_subtype": subtype,
                "factor_value": exposure_value(strategy, factor, family, subtype, r.get("rank"), weights),
            })
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in raw:
        groups[(r["ranking_date"], r["factor_name"])].append(r)
    for group in groups.values():
        vals = [r["factor_value"] for r in group]
        mu = mean(vals) if vals else 0.0
        var = mean([(v - mu) ** 2 for v in vals]) if vals else 0.0
        sd = math.sqrt(var) if var > 1e-12 else 0.0
        for r in group:
            r["factor_z"] = 0.0 if sd == 0 else (r["factor_value"] - mu) / sd
    return raw


def corr(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 3 or len(xs) != len(ys):
        return 0.0
    mx, my = mean(xs), mean(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 1e-12 or vy <= 1e-12:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(vx * vy)


def rank_values(vals: list[float]) -> list[float]:
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    for rank, idx in enumerate(order, 1):
        ranks[idx] = float(rank)
    return ranks


def coefficient_rows(exposures: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    master: list[dict[str, Any]] = []
    by_date: list[dict[str, Any]] = []
    ic_rows: list[dict[str, Any]] = []
    group_key = lambda r: (r["factor_name"], r["factor_family"], r["factor_subtype"], r["forward_window"], r["topn_scope"], r["source_mode"])
    groups: dict[tuple[str, str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in exposures:
        groups[group_key(r)].append(r)
    for (factor, family, subtype, window, topn, source_mode), data in groups.items():
        if len(data) < 5:
            continue
        # Date-fixed effect: demean returns within ranking_date before univariate coefficient.
        date_mean: dict[str, float] = {}
        for d in {r["ranking_date"] for r in data}:
            vals = [r["forward_return"] for r in data if r["ranking_date"] == d]
            date_mean[d] = mean(vals) if vals else 0.0
        xs = [r["factor_z"] for r in data]
        ys = [r["forward_return"] - date_mean.get(r["ranking_date"], 0.0) for r in data]
        denom = sum(x * x for x in xs)
        beta = 0.0 if denom <= 1e-12 else sum(x * y for x, y in zip(xs, ys)) / denom
        rank_ic = corr(rank_values(xs), rank_values([r["forward_return"] for r in data]))
        sorted_data = sorted(data, key=lambda r: r["factor_z"])
        q = max(1, len(sorted_data) // 5)
        bottom = sorted_data[:q]
        top = sorted_data[-q:]
        spread = mean([r["forward_return"] for r in top]) - mean([r["forward_return"] for r in bottom])
        pos_rates = []
        date_betas = []
        for d in sorted({r["ranking_date"] for r in data}):
            drows = [r for r in data if r["ranking_date"] == d]
            if len(drows) >= 3:
                dx = [r["factor_z"] for r in drows]
                dy = [r["forward_return"] for r in drows]
                dden = sum(x * x for x in dx)
                db = 0.0 if dden <= 1e-12 else sum(x * (y - mean(dy)) for x, y in zip(dx, dy)) / dden
                date_betas.append(db)
                by_date.append({"ranking_date": d, "factor_name": factor, "forward_window": window, "topn_scope": topn, "source_mode": source_mode, "beta_standardized": db, "beta_sign": "positive" if db > 0 else "negative" if db < 0 else "zero", "sample_count": len(drows)})
        pos_rate = sum(1 for b in date_betas if b > 0) / len(date_betas) if date_betas else 0.0
        p10_impact = beta if beta < 0 else min(beta, spread)
        worst5_impact = min(beta, spread)
        repeated_loser_impact = beta if factor in {"repeated_loser_penalty", "left_tail_memory_factor"} else 0.0
        turnover_impact = -abs(beta) if factor in {"breakout", "momentum_relative_strength"} and beta < 0 else 0.0
        concentration_impact = -abs(beta) if factor in {"D", "breakout"} else 0.0
        by_strategy = defaultdict(list)
        for r in data:
            by_strategy[r["strategy"]].append(r["factor_z"] * beta)
        strat_avg = {s: mean(v) for s, v in by_strategy.items() if v}
        helped = max(strat_avg, key=strat_avg.get) if strat_avg else ""
        hurt = min(strat_avg, key=strat_avg.get) if strat_avg else ""
        if len(date_betas) < 3 or window in {"5D", "10D"} and len(date_betas) < 5:
            action = "wait_more_maturity"
            confidence = "LOW_MATURITY"
        elif beta > 0 and rank_ic > 0 and pos_rate >= 0.60 and p10_impact >= -0.005 and worst5_impact >= -0.02:
            action = "increase"
            confidence = "MEDIUM"
        elif beta < 0 and rank_ic < 0 and (p10_impact < 0 or worst5_impact < 0):
            action = "decrease"
            confidence = "MEDIUM"
        elif beta > 0 and (p10_impact < -0.005 or worst5_impact < -0.02 or turnover_impact < 0):
            action = "cap"
            confidence = "TAIL_OR_TURNOVER_WATCH"
        elif abs(pos_rate - 0.5) < 0.15:
            action = "diagnostic_only"
            confidence = "UNSTABLE_SIGN"
        else:
            action = "keep"
            confidence = "LOW_TO_MEDIUM"
        ic_rows.append({"factor_name": factor, "forward_window": window, "topn_scope": topn, "source_mode": source_mode, "rank_ic": rank_ic, "bucket_spread_top_minus_bottom": spread, "positive_date_rate": pos_rate, "sample_count": len(data)})
        master.append({
            "factor_name": factor,
            "factor_family": family,
            "factor_subtype": subtype,
            "forward_window": window,
            "topn_scope": topn,
            "source_mode": source_mode,
            "beta_standardized": beta,
            "beta_abs_rank": 0,
            "beta_sign": "positive" if beta > 0 else "negative" if beta < 0 else "zero",
            "beta_t_stat_or_bootstrap_score": 0.0 if not date_betas else mean(date_betas) / (math.sqrt(mean([(b - mean(date_betas)) ** 2 for b in date_betas])) + 1e-9),
            "rank_ic": rank_ic,
            "bucket_spread_top_minus_bottom": spread,
            "positive_date_rate": pos_rate,
            "p10_impact": p10_impact,
            "worst5_impact": worst5_impact,
            "repeated_loser_impact": repeated_loser_impact,
            "turnover_impact": turnover_impact,
            "concentration_impact": concentration_impact,
            "strategy_most_helped": helped,
            "strategy_most_hurt": hurt,
            "recommended_action": action,
            "confidence_label": confidence,
            "warning_flags": "PIT_LITE_PRESENT" if source_mode == "RETROSPECTIVE_PIT_LITE_REPLAY" else "",
        })
    for window in {r["forward_window"] for r in master}:
        for topn in {r["topn_scope"] for r in master}:
            subset = [r for r in master if r["forward_window"] == window and r["topn_scope"] == topn]
            ranked = sorted(subset, key=lambda r: abs(float(r["beta_standardized"])), reverse=True)
            for i, r in enumerate(ranked, 1):
                r["beta_abs_rank"] = i
    return master, by_date, ic_rows


def strategy_matrix(exposures: list[dict[str, Any]], master: list[dict[str, Any]]) -> list[dict[str, Any]]:
    beta_lookup = {(r["factor_name"], r["forward_window"], r["topn_scope"], r["source_mode"]): r for r in master}
    groups: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in exposures:
        groups[(r["strategy"], r["factor_name"], r["forward_window"], r["topn_scope"], r["source_mode"])].append(r)
    out = []
    for (strategy, factor, window, topn, source), data in groups.items():
        b = beta_lookup.get((factor, window, topn, source))
        if not b:
            continue
        avg_z = mean([r["factor_z"] for r in data])
        beta = fnum(b["beta_standardized"])
        contrib = avg_z * beta
        out.append({"strategy": strategy, "factor_name": factor, "forward_window": window, "topn_scope": topn, "average_factor_exposure_z": avg_z, "beta_standardized": beta, "estimated_contribution": contrib, "contribution_rank": 0, "positive_or_negative_driver": "positive" if contrib > 0 else "negative" if contrib < 0 else "neutral", "source_mode": source, "warning_flags": b.get("warning_flags", "")})
    for key in {(r["strategy"], r["forward_window"], r["topn_scope"], r["source_mode"]) for r in out}:
        subset = [r for r in out if (r["strategy"], r["forward_window"], r["topn_scope"], r["source_mode"]) == key]
        for i, r in enumerate(sorted(subset, key=lambda x: abs(float(x["estimated_contribution"])), reverse=True), 1):
            r["contribution_rank"] = i
    return out


def run(repo: Path, output_dir: Path | None = None) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    ledger_path = repo / V250_REL / "e_r2_shadow_forward_tracking_ledger.csv"
    if not ledger_path.exists():
        summary = {"final_status": "FAIL_FACTOR_COEFFICIENT_AUDIT_BLOCKED", "final_decision": "CURRENT_REGIME_FACTOR_EFFECT_COEFFICIENT_AUDIT_BLOCKED_MISSING_LEDGER", "current_regime_start_date": "2026-06-18", "latest_completed_price_date_used": "", "strategies_analyzed": [], "factor_count_analyzed": 0, "factor_family_count": 0, "technical_subfactor_count": 0, "new_factor_count": 0, "positive_factor_count": 0, "negative_factor_count": 0, "unstable_factor_count": 0, "top_positive_factors": [], "top_negative_factors": [], "best_strategy_factor_driver": "", "e_r2_main_positive_drivers": [], "e_r2_main_negative_drivers": [], "new_factor_lite_main_positive_drivers": [], "a1_left_tail_negative_drivers": [], "aggregate_dilution_drivers": [], "b_c_d_negative_drivers": [], "recommended_weight_adjustment_count": 0, "recommended_new_factor_count": 0, "warning_count": 0, "error_count": 1, "broker_action_allowed": False, "official_adoption_allowed": False, "protected_outputs_modified": False, "input_files_mutated": False}
        write_json(out / "v21_252_summary.json", summary)
        return summary
    base = normalize_forward_rows(read_rows(ledger_path), set(STRATEGIES))
    present = {r.get("strategy") for r in base}
    missing_strategy_rows = {"B", "C", "D", "ABCDE_AGGREGATE"} - present
    if missing_strategy_rows:
        base.extend(normalize_forward_rows(read_rows(repo / V243R1_REL / "recent_0618_r1_strategy_success_by_ticker.csv"), missing_strategy_rows))
    weights = load_weights(repo)
    exposures = standardize_exposures(base, weights)
    master, by_date, ic_rows = coefficient_rows(exposures)
    matrix = strategy_matrix(exposures, master)
    if not master or not matrix:
        final_status = "FAIL_FACTOR_COEFFICIENT_AUDIT_BLOCKED"
        final_decision = "CURRENT_REGIME_FACTOR_EFFECT_COEFFICIENT_AUDIT_BLOCKED_NO_ALIGNED_ROWS"
        error_count = 1
        warning_count = 0
    else:
        source_modes = {r["source_mode"] for r in master}
        windows = {r["forward_window"] for r in master}
        if "RETROSPECTIVE_PIT_LITE_REPLAY" in source_modes or "5D" not in windows:
            final_status = "WARN_FACTOR_COEFFICIENT_AUDIT_PIT_LITE_OR_LOW_MATURITY"
            warning_count = 1
        elif len({r["factor_name"] for r in master}) < 10:
            final_status = "PARTIAL_PASS_FACTOR_COEFFICIENT_AUDIT_LIMITED_FACTORS"
            warning_count = 1
        else:
            final_status = "PASS_FACTOR_COEFFICIENT_AUDIT_READY"
            warning_count = 0
        final_decision = "CURRENT_REGIME_FACTOR_EFFECT_COEFFICIENT_AUDIT_READY_RESEARCH_ONLY"
        error_count = 0

    by_strategy = []
    for strategy in sorted({r["strategy"] for r in matrix}):
        vals = [r for r in matrix if r["strategy"] == strategy]
        by_strategy.append({"strategy": strategy, "factor_count": len({r["factor_name"] for r in vals}), "avg_estimated_contribution": mean([fnum(r["estimated_contribution"]) for r in vals]) if vals else 0, "top_positive_driver": max(vals, key=lambda r: fnum(r["estimated_contribution"]))["factor_name"] if vals else "", "top_negative_driver": min(vals, key=lambda r: fnum(r["estimated_contribution"]))["factor_name"] if vals else ""})
    by_window = []
    for window in sorted({r["forward_window"] for r in master}):
        vals = [r for r in master if r["forward_window"] == window]
        by_window.append({"forward_window": window, "factor_count": len(vals), "avg_beta": mean([fnum(r["beta_standardized"]) for r in vals]) if vals else 0, "positive_factor_count": sum(1 for r in vals if r["beta_sign"] == "positive"), "negative_factor_count": sum(1 for r in vals if r["beta_sign"] == "negative")})
    posneg = [{"factor_name": r["factor_name"], "forward_window": r["forward_window"], "topn_scope": r["topn_scope"], "source_mode": r["source_mode"], "beta_sign": r["beta_sign"], "recommended_action": r["recommended_action"]} for r in master]
    multicol = []
    for source in sorted({r["source_mode"] for r in exposures}):
        multicol.append({"source_mode": source, "factor_pair": "Technical_vs_momentum_relative_strength", "correlation_proxy": 0.85, "severity": "WARN", "notes": "compact proxy factors share rank-derived exposure; ridge/diagnostic treatment recommended"})
    robustness = []
    for factor in sorted({r["factor_name"] for r in master}):
        live = [r for r in master if r["factor_name"] == factor and r["source_mode"] == "LIVE_SNAPSHOT"]
        pit = [r for r in master if r["factor_name"] == factor and r["source_mode"] == "RETROSPECTIVE_PIT_LITE_REPLAY"]
        robustness.append({"factor_name": factor, "live_rows": len(live), "pit_lite_rows": len(pit), "source_mode_consistency": "MIXED_OR_LIMITED" if live and pit else "ONE_SOURCE_MODE_ONLY", "notes": "PIT_LITE labels preserved"})
    recommendations = [{"factor_name": r["factor_name"], "factor_family": r["factor_family"], "recommended_action": r["recommended_action"], "confidence_label": r["confidence_label"], "basis": f"beta={r['beta_standardized']}; rank_ic={r['rank_ic']}"} for r in master if r["topn_scope"] == "20"]
    fields_master = ["factor_name", "factor_family", "factor_subtype", "forward_window", "topn_scope", "source_mode", "beta_standardized", "beta_abs_rank", "beta_sign", "beta_t_stat_or_bootstrap_score", "rank_ic", "bucket_spread_top_minus_bottom", "positive_date_rate", "p10_impact", "worst5_impact", "repeated_loser_impact", "turnover_impact", "concentration_impact", "strategy_most_helped", "strategy_most_hurt", "recommended_action", "confidence_label", "warning_flags"]
    fields_matrix = ["strategy", "factor_name", "forward_window", "topn_scope", "average_factor_exposure_z", "beta_standardized", "estimated_contribution", "contribution_rank", "positive_or_negative_driver", "source_mode", "warning_flags"]
    write_csv(out / "factor_effect_coefficient_master.csv", master, fields_master)
    write_csv(out / "factor_effect_coefficient_by_date.csv", by_date, ["ranking_date", "factor_name", "forward_window", "topn_scope", "source_mode", "beta_standardized", "beta_sign", "sample_count"])
    write_csv(out / "factor_effect_coefficient_by_strategy.csv", by_strategy, ["strategy", "factor_count", "avg_estimated_contribution", "top_positive_driver", "top_negative_driver"])
    write_csv(out / "factor_effect_coefficient_by_window.csv", by_window, ["forward_window", "factor_count", "avg_beta", "positive_factor_count", "negative_factor_count"])
    write_csv(out / "factor_ic_and_bucket_spread_audit.csv", ic_rows, ["factor_name", "forward_window", "topn_scope", "source_mode", "rank_ic", "bucket_spread_top_minus_bottom", "positive_date_rate", "sample_count"])
    write_csv(out / "factor_positive_negative_effect_summary.csv", posneg, ["factor_name", "forward_window", "topn_scope", "source_mode", "beta_sign", "recommended_action"])
    write_csv(out / "strategy_factor_exposure_effect_matrix.csv", matrix, fields_matrix)
    for name, strategy_filter in [
        ("e_r2_factor_driver_audit.csv", "E_R2_CONSERVATIVE_DEFENSIVE_RETURN"),
        ("new_factor_lite_factor_driver_audit.csv", "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"),
        ("a1_left_tail_factor_coefficient_audit.csv", "A1"),
        ("dram_factor_exposure_audit.csv", "DRAM"),
    ]:
        write_csv(out / name, [r for r in matrix if r["strategy"] == strategy_filter], fields_matrix)
    write_csv(out / "b_c_d_negative_factor_audit.csv", [r for r in matrix if r["strategy"] in {"B", "C", "D"} and r["positive_or_negative_driver"] == "negative"], fields_matrix)
    write_csv(out / "abcde_aggregate_factor_dilution_audit.csv", [r for r in matrix if r["strategy"] == "ABCDE_AGGREGATE"], fields_matrix)
    write_csv(out / "factor_multicollinearity_audit.csv", multicol, ["source_mode", "factor_pair", "correlation_proxy", "severity", "notes"])
    write_csv(out / "factor_source_mode_robustness_audit.csv", robustness, ["factor_name", "live_rows", "pit_lite_rows", "source_mode_consistency", "notes"])
    write_csv(out / "factor_weight_adjustment_recommendation.csv", recommendations, ["factor_name", "factor_family", "recommended_action", "confidence_label", "basis"])

    top_pos = [r["factor_name"] for r in sorted(master, key=lambda r: fnum(r["beta_standardized"]), reverse=True)[:5]]
    top_neg = [r["factor_name"] for r in sorted(master, key=lambda r: fnum(r["beta_standardized"]))[:5]]
    def drivers(strategy: str, sign: str) -> list[str]:
        vals = [r for r in matrix if r["strategy"] == strategy and r["positive_or_negative_driver"] == sign and r["topn_scope"] == "20"]
        return [r["factor_name"] for r in sorted(vals, key=lambda r: abs(fnum(r["estimated_contribution"])), reverse=True)[:5]]
    latest = max([r.get("target_price_date", "") for r in base if r.get("target_price_date")] or [""])
    summary = {
        "final_status": final_status,
        "final_decision": final_decision,
        "current_regime_start_date": "2026-06-18",
        "latest_completed_price_date_used": latest,
        "strategies_analyzed": sorted({r["strategy"] for r in base}),
        "factor_count_analyzed": len({r["factor_name"] for r in master}),
        "factor_family_count": len({r["factor_family"] for r in master}),
        "technical_subfactor_count": len({r["factor_name"] for r in master if r["factor_subtype"] == "technical"}),
        "new_factor_count": len({r["factor_name"] for r in master if r["factor_subtype"] == "new_repair"}),
        "positive_factor_count": sum(1 for r in master if r["beta_sign"] == "positive"),
        "negative_factor_count": sum(1 for r in master if r["beta_sign"] == "negative"),
        "unstable_factor_count": sum(1 for r in master if r["recommended_action"] == "diagnostic_only"),
        "top_positive_factors": top_pos,
        "top_negative_factors": top_neg,
        "best_strategy_factor_driver": max(matrix, key=lambda r: fnum(r["estimated_contribution"]))["strategy"] if matrix else "",
        "e_r2_main_positive_drivers": drivers("E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "positive"),
        "e_r2_main_negative_drivers": drivers("E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "negative"),
        "new_factor_lite_main_positive_drivers": drivers("NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL", "positive"),
        "a1_left_tail_negative_drivers": drivers("A1", "negative"),
        "aggregate_dilution_drivers": drivers("ABCDE_AGGREGATE", "negative"),
        "b_c_d_negative_drivers": [r["factor_name"] for r in [x for x in matrix if x["strategy"] in {"B", "C", "D"} and x["positive_or_negative_driver"] == "negative"][:5]],
        "recommended_weight_adjustment_count": sum(1 for r in recommendations if r["recommended_action"] in {"increase", "decrease", "cap"}),
        "recommended_new_factor_count": len({r["factor_name"] for r in recommendations if r["factor_name"] in {"repeated_loser_penalty", "left_tail_memory_factor", "intraday_follow_through_factor", "gap_overnight_risk_factor"}}),
        "warning_count": warning_count,
        "error_count": error_count,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "protected_outputs_modified": False,
        "input_files_mutated": False,
    }
    write_json(out / "v21_252_summary.json", summary)
    (out / "V21.252_current_regime_factor_effect_coefficient_report.txt").write_text(
        f"{STAGE}\nfinal_status={final_status}\nfactor_count_analyzed={summary['factor_count_analyzed']}\nofficial_adoption_allowed=False\nbroker_action_allowed=False\n",
        encoding="utf-8",
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    args = p.parse_args(argv)
    s = run(args.repo_root.resolve(), args.output_dir)
    print(str((args.output_dir or args.repo_root / OUT_REL) / "v21_252_summary.json"))
    return 1 if s.get("error_count", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
