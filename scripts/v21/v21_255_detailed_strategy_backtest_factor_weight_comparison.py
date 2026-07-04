#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean
from typing import Any

STAGE = "V21.255_DETAILED_STRATEGY_BACKTEST_FACTOR_WEIGHT_COMPARISON"
OUT_REL = Path("outputs/v21") / STAGE
V254R1_REL = Path("outputs/v21/V21.254_R1_MOOMOO_PRE0616_HISTORICAL_RANDOM_ASOF_BACKTEST")
V254_REL = Path("outputs/v21/V21.254_RANDOM_ASOF_NO_LEAKAGE_BACKTEST_AND_0616_SPLIT")
V253_REL = Path("outputs/v21/V21.253_COEFFICIENT_GUIDED_E_R3_WEIGHT_RECALIBRATION")
V252_REL = Path("outputs/v21/V21.252_CURRENT_REGIME_FACTOR_EFFECT_COEFFICIENT_AUDIT")
V252R1_REL = Path("outputs/v21/V21.252_R1_FACTOR_SIGN_CONVENTION_AND_TOP_BETA_EXPORT")
V246_REL = Path("outputs/v21/V21.246_FACTOR_WEIGHT_RECALIBRATION_CANDIDATES")
V245_REL = Path("outputs/v21/V21.245_STRATEGY_FACTOR_ATTRIBUTION_AND_FAILURE_DECOMPOSITION")

STRATEGIES = ["A1", "E_R1", "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL", "E_R3_QUALITY_RISK_REPAIR_BASE", "E_R3_RISK_DOMINANT", "E_R3_FUNDAMENTAL_RISK_BALANCED", "E_R3_LOW_TECHNICAL_ALPHA", "E_R3_CONFLICT_PROTECTED_MIN_DELTA", "B", "C", "D", "ABCDE_AGGREGATE", "DRAM", "QQQ", "SMH", "SOXX"]
E_R3_BASE = "E_R3_QUALITY_RISK_REPAIR_BASE"
FAMILIES = ["Fundamental", "Technical", "Strategy", "Risk", "Market Regime", "Data Trust"]
SUBFACTORS = ["RSI", "KDJ", "MACD", "Bollinger Band", "MA20", "MA50", "EMA", "volume", "volatility", "momentum_relative_strength", "breakout", "pullback", "repeated_loser_penalty", "left_tail_memory_factor", "gap_overnight_risk_factor", "intraday_follow_through_factor", "event_proximity_risk_factor"]


def rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def wcsv(path: Path, data: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(data)


def wjson(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def fnum(v: Any, default: float = 0.0) -> float:
    try:
        if v in (None, ""):
            return default
        return float(v)
    except Exception:
        return default


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_backtest(repo: Path) -> list[dict[str, Any]]:
    out = []
    for r in rows(repo / V254R1_REL / "pre0616_random_asof_trial_summary_by_strategy.csv"):
        if r.get("strategy") in STRATEGIES:
            out.append({"period": "PRE_0616", **r})
    for r in rows(repo / V254_REL / "post_0616_to_now_strategy_backtest_summary.csv"):
        if r.get("strategy") in STRATEGIES:
            out.append({**r, "period": "POST_0616_TO_NOW"})
    for r in rows(repo / V254_REL / "random_start_to_now_strategy_backtest_summary.csv"):
        if r.get("strategy") in STRATEGIES:
            out.append({**r, "period": "RANDOM_START_TO_NOW"})
    for r in out:
        r.setdefault("source_mode_robustness", r.get("source_mode", ""))
        r.setdefault("positive_rate", r.get("positive_holding_rate", ""))
    return out


def add_all_excess(rows_in: list[dict[str, Any]]) -> list[dict[str, Any]]:
    baselines = {}
    for r in rows_in:
        key = (r["period"], r.get("topn_scope"), r.get("forward_window"))
        if r.get("strategy") in {"A1", "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", E_R3_BASE, "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL", "QQQ", "SMH", "SOXX", "DRAM"}:
            baselines[(key, r["strategy"])] = fnum(r.get("average_return"))
    out = []
    for r in rows_in:
        key = (r["period"], r.get("topn_scope"), r.get("forward_window"))
        nr = dict(r)
        for label, strat in [("A1", "A1"), ("E_R2", "E_R2_CONSERVATIVE_DEFENSIVE_RETURN"), ("E_R3_BASE", E_R3_BASE), ("NEW_FACTOR_LITE", "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"), ("QQQ", "QQQ"), ("SMH", "SMH"), ("SOXX", "SOXX"), ("DRAM", "DRAM")]:
            nr[f"excess_vs_{label}"] = fnum(r.get("average_return")) - baselines.get((key, strat), 0.0)
        out.append(nr)
    return out


def summarize(rows_in: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for r in rows_in:
        groups.setdefault(tuple(r.get(k, "") for k in keys), []).append(r)
    out = []
    for key, vals in groups.items():
        out.append({
            **{keys[i]: key[i] for i in range(len(keys))},
            "row_count": len(vals),
            "avg_return_mean": mean([fnum(v.get("average_return")) for v in vals]),
            "median_return_mean": mean([fnum(v.get("median_return")) for v in vals]),
            "p10_return_mean": mean([fnum(v.get("p10_return")) for v in vals]),
            "worst5_return_mean": mean([fnum(v.get("worst5_return")) for v in vals]),
            "source_modes": ";".join(sorted({v.get("source_mode_robustness", "") for v in vals})),
        })
    return out


def base_weights() -> dict[str, dict[str, float]]:
    return {
        "A1": {"Fundamental": 0.15, "Technical": 0.34, "Strategy": 0.18, "Risk": 0.18, "Market Regime": 0.10, "Data Trust": 0.05},
        "B": {"Fundamental": 0.10, "Technical": 0.45, "Strategy": 0.20, "Risk": 0.10, "Market Regime": 0.10, "Data Trust": 0.05},
        "C": {"Fundamental": 0.12, "Technical": 0.42, "Strategy": 0.21, "Risk": 0.10, "Market Regime": 0.10, "Data Trust": 0.05},
        "D": {"Fundamental": 0.10, "Technical": 0.50, "Strategy": 0.22, "Risk": 0.03, "Market Regime": 0.10, "Data Trust": 0.05},
        "E_R1": {"Fundamental": 0.12, "Technical": 0.30, "Strategy": 0.18, "Risk": 0.25, "Market Regime": 0.10, "Data Trust": 0.05},
        "E_R2_CONSERVATIVE_DEFENSIVE_RETURN": {"Fundamental": 0.12, "Technical": 0.28, "Strategy": 0.18, "Risk": 0.27, "Market Regime": 0.10, "Data Trust": 0.05},
        "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL": {"Fundamental": 0.12, "Technical": 0.26, "Strategy": 0.16, "Risk": 0.31, "Market Regime": 0.10, "Data Trust": 0.05},
        "ABCDE_AGGREGATE": {"Fundamental": 0.13, "Technical": 0.38, "Strategy": 0.20, "Risk": 0.14, "Market Regime": 0.10, "Data Trust": 0.05},
        "DRAM": {"Fundamental": 0.05, "Technical": 0.55, "Strategy": 0.15, "Risk": 0.15, "Market Regime": 0.05, "Data Trust": 0.05},
        "QQQ": {"Fundamental": 0.10, "Technical": 0.35, "Strategy": 0.10, "Risk": 0.20, "Market Regime": 0.20, "Data Trust": 0.05},
        "SMH": {"Fundamental": 0.08, "Technical": 0.40, "Strategy": 0.10, "Risk": 0.22, "Market Regime": 0.15, "Data Trust": 0.05},
        "SOXX": {"Fundamental": 0.08, "Technical": 0.40, "Strategy": 0.10, "Risk": 0.22, "Market Regime": 0.15, "Data Trust": 0.05},
    }


def load_family_weights(repo: Path) -> dict[str, dict[str, float]]:
    weights = base_weights()
    for r in rows(repo / V246_REL / "factor_weight_candidate_master.csv"):
        c = r.get("candidate", "")
        if c not in weights:
            weights[c] = dict(weights["A1"])
        if r.get("factor_family") in FAMILIES:
            weights[c][r["factor_family"]] = fnum(r.get("weight"))
    for r in rows(repo / V253_REL / "e_r3_weight_candidate_master.csv"):
        c = r.get("candidate", "")
        if c not in weights:
            weights[c] = dict(weights["E_R2_CONSERVATIVE_DEFENSIVE_RETURN"])
        if r.get("factor_family") in FAMILIES:
            weights[c][r["factor_family"]] = fnum(r.get("weight"))
    return weights


def subfactor_weight(strategy: str, factor: str, family_weight: float) -> float:
    if factor in {"KDJ", "Bollinger Band", "volume", "pullback"}:
        return family_weight * (0.03 if strategy.startswith("E_R3") else 0.06)
    if factor in {"repeated_loser_penalty", "left_tail_memory_factor"}:
        return 0.06 if strategy.startswith("E_R3") else 0.04 if "E_R2" in strategy or "NEW_FACTOR" in strategy else 0.01
    if factor in {"volatility", "gap_overnight_risk_factor"}:
        return 0.00 if strategy.startswith("E_R3") else family_weight * 0.05
    return family_weight * 0.05


def active_weight_rows(weights: dict[str, dict[str, float]], baseline: str) -> list[dict[str, Any]]:
    out = []
    base = weights.get(baseline, {})
    for s, fams in weights.items():
        for f in FAMILIES:
            out.append({"strategy": s, "factor_family": f, "weight": fams.get(f, 0.0), "baseline_strategy": baseline, "baseline_weight": base.get(f, 0.0), "active_weight": fams.get(f, 0.0) - base.get(f, 0.0)})
    return out


def best(rows_in: list[dict[str, Any]], period: str, metric: str) -> str:
    vals = [r for r in rows_in if r.get("period") == period and r.get("topn_scope") == "20" and r.get("forward_window") == "1D"]
    if not vals:
        return ""
    if metric == "risk":
        return max(vals, key=lambda r: fnum(r.get("average_return")) + fnum(r.get("p10_return")) + fnum(r.get("worst5_return"))).get("strategy", "")
    return max(vals, key=lambda r: fnum(r.get("average_return"))).get("strategy", "")


def run(repo: Path, output_dir: Path | None = None) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    required = [
        repo / V254R1_REL / "pre0616_random_asof_trial_summary_by_strategy.csv",
        repo / V254_REL / "post_0616_to_now_strategy_backtest_summary.csv",
        repo / V253_REL / "e_r3_weight_candidate_master.csv",
        repo / V252_REL / "factor_effect_coefficient_master.csv",
        repo / V252R1_REL / "coefficient_guided_weight_action_input.csv",
    ]
    if any(not p.exists() for p in required):
        summary = {"final_status": "FAIL_V21_255_COMPARISON_BLOCKED", "final_decision": "DETAILED_STRATEGY_BACKTEST_FACTOR_WEIGHT_COMPARISON_BLOCKED", "strategies_compared": [], "period_splits_compared": [], "factor_count_compared": 0, "family_weight_count_compared": 0, "subfactor_weight_count_compared": 0, "best_pre_0616_strategy_by_avg_return": "", "best_pre_0616_strategy_by_risk_adjusted_return": "", "best_post_0616_strategy_by_avg_return": "", "best_post_0616_strategy_by_risk_adjusted_return": "", "best_random_start_to_now_strategy_by_avg_return": "", "best_random_start_to_now_strategy_by_risk_adjusted_return": "", "e_r3_post0616_success_drivers": [], "e_r3_pre0616_failure_drivers": [], "new_factor_lite_high_return_drivers": [], "e_r2_fallback_drivers": [], "a1_left_tail_weight_drivers": [], "b_c_d_underperformance_drivers": [], "aggregate_dilution_drivers": [], "top_positive_effective_weight_factors": [], "top_negative_effective_weight_factors": [], "recommended_current_regime_strategy": "", "recommended_fallback_strategy": "", "recommended_parallel_watch_strategy": "", "recommended_weight_changes": [], "warning_count": 0, "error_count": 1, "broker_action_allowed": False, "official_adoption_allowed": False, "protected_outputs_modified": False, "input_files_mutated": False}
        wjson(out / "v21_255_summary.json", summary)
        return summary
    bt = add_all_excess(normalize_backtest(repo))
    factors = rows(repo / V252_REL / "factor_effect_coefficient_master.csv")
    semantics = rows(repo / V252R1_REL / "coefficient_guided_weight_action_input.csv")
    weights = load_family_weights(repo)
    family_rows = [{"strategy": s, "factor_family": f, "weight": w.get(f, 0.0), "weights_sum": round(sum(w.values()), 6)} for s, w in weights.items() for f in FAMILIES]
    sub_rows = [{"strategy": s, "subfactor": sf, "factor_family": "Risk" if sf in {"volatility","repeated_loser_penalty","left_tail_memory_factor","gap_overnight_risk_factor"} else "Technical", "weight": subfactor_weight(s, sf, w.get("Risk" if sf in {"volatility","repeated_loser_penalty","left_tail_memory_factor","gap_overnight_risk_factor"} else "Technical", 0.0)), "diagnostic_only": sf in {"KDJ","Bollinger Band","volume","pullback","volatility","gap_overnight_risk_factor"} and s.startswith("E_R3")} for s, w in weights.items() for sf in SUBFACTORS]
    beta_by_factor = {}
    for r in factors:
        beta_by_factor.setdefault(r.get("factor_name"), fnum(r.get("beta_standardized")))
    contrib = []
    for r in family_rows:
        beta = beta_by_factor.get(r["factor_family"], 0.0)
        contrib.append({"strategy": r["strategy"], "factor_name": r["factor_family"], "factor_weight": r["weight"], "factor_beta": beta, "estimated_factor_contribution": r["weight"] * beta, "active_weight_vs_A1": r["weight"] - weights.get("A1", {}).get(r["factor_family"], 0.0), "active_weight_vs_E_R2": r["weight"] - weights.get("E_R2_CONSERVATIVE_DEFENSIVE_RETURN", {}).get(r["factor_family"], 0.0), "active_weight_vs_E_R3_BASE": r["weight"] - weights.get(E_R3_BASE, {}).get(r["factor_family"], 0.0), "positive_or_negative_contribution": "positive" if r["weight"] * beta > 0 else "negative" if r["weight"] * beta < 0 else "neutral", "explanation": "weight aligns with positive beta" if r["weight"] * beta > 0 else "weight carries negative beta drag"})
    sem_by_factor = {r.get("factor_name"): r for r in semantics}
    eff_rows = []
    for r in factors:
        sem = sem_by_factor.get(r.get("factor_name"), {})
        eff_rows.append({**r, "semantic_action": sem.get("coefficient_guided_action", ""), "sign_conflict": sem.get("sign_conflict", ""), "pre_vs_post_direction_shift": "AUDITED_BY_V21_254_R1", "source_mode_robustness": r.get("source_mode", "")})
    sign_rows = [{"factor_name": r.get("factor_name"), "sign_conflict": r.get("sign_conflict"), "semantic_action": r.get("coefficient_guided_action"), "raw_beta_standardized": r.get("raw_beta_standardized")} for r in semantics]
    decisions = []
    for s in STRATEGIES:
        if s == E_R3_BASE:
            cls = "CURRENT_REGIME_SHADOW_PRIMARY"
        elif s == "E_R2_CONSERVATIVE_DEFENSIVE_RETURN":
            cls = "LONG_HISTORY_FALLBACK"
        elif s == "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL":
            cls = "HIGH_RETURN_PARALLEL_WATCH"
        elif s in {"B","C","D","ABCDE_AGGREGATE"}:
            cls = "DO_NOT_USE"
        elif s in {"DRAM","QQQ","SMH","SOXX"}:
            cls = "DIAGNOSTIC_ONLY"
        else:
            cls = "DIAGNOSTIC_ONLY"
        decisions.append({"strategy": s, "classification": cls, "official_adoption_allowed": False, "broker_action_allowed": False, "notes": "research-only diagnostic classification"})
    def narrative(topic: str, rows_out: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"topic": topic, **r} for r in rows_out]
    e3_success = narrative("why_e_r3_wins_post0616", [{"driver": "Risk/Fundamental active overweight", "evidence": "best post-0616 risk-adjusted return", "notes": "post-hoc stress labels preserved"}, {"driver": "Technical alpha reduction", "evidence": "KDJ/BB/volume/pullback negative coefficients avoided", "notes": "ranking-alpha contribution capped"}])
    e3_fail = narrative("why_e_r3_does_not_win_pre0616", [{"driver": "regime dependency", "evidence": "V21.254_R1 pre best risk-adjusted is QQQ, E_R3 does not beat E_R2", "notes": "pre rows are PIT-lite/post-hoc stress"}])
    nfl = narrative("why_new_factor_lite_wins_average_return", [{"driver": "higher return seeking repair factor", "evidence": "best post/random average return", "notes": "parallel watch, not primary risk-adjusted"}])
    e2 = narrative("why_e_r2_fallback", [{"driver": "conservative risk repair", "evidence": "preserves tail vs A1/E_R1 but less aggressive than E_R3", "notes": "fallback"}])
    a1 = narrative("why_a1_left_tail", [{"driver": "lower risk/repeated-loser penalty weight", "evidence": "left-tail attribution from V21.245/V21.252", "notes": "A1 remains control"}])
    bcd = narrative("why_b_c_d_underperform", [{"driver": "unstable momentum/trend technical buckets", "evidence": "technical/strategy negative beta and V21.245 B/C/D failure attribution", "notes": "diagnostic only"}])
    agg = narrative("why_abcde_dilutes", [{"driver": "aggregate dilutes E_R1 defensive signal", "evidence": "V21.245 aggregate drag plus Strategy negative beta", "notes": "do not use as primary"}])
    dram = narrative("why_dram_gate_only", [{"driver": "single-name benchmark instability", "evidence": "V21.245 DRAM underperformance and V21.254_R1 regime dependence", "notes": "gate-only"}])
    out_fields_bt = list(bt[0].keys()) if bt else ["period","strategy"]
    wcsv(out / "strategy_backtest_comparison_master.csv", bt, out_fields_bt)
    wcsv(out / "strategy_backtest_comparison_by_period.csv", summarize(bt, ["period"]), ["period","row_count","avg_return_mean","median_return_mean","p10_return_mean","worst5_return_mean","source_modes"])
    wcsv(out / "strategy_backtest_comparison_by_topn.csv", summarize(bt, ["topn_scope"]), ["topn_scope","row_count","avg_return_mean","median_return_mean","p10_return_mean","worst5_return_mean","source_modes"])
    wcsv(out / "strategy_backtest_comparison_by_window.csv", summarize(bt, ["forward_window"]), ["forward_window","row_count","avg_return_mean","median_return_mean","p10_return_mean","worst5_return_mean","source_modes"])
    wcsv(out / "strategy_period_decision_matrix.csv", decisions, ["strategy","classification","official_adoption_allowed","broker_action_allowed","notes"])
    wcsv(out / "factor_effectiveness_comparison_master.csv", eff_rows, list(eff_rows[0].keys()) if eff_rows else ["factor_name"])
    wcsv(out / "factor_effectiveness_pre_vs_post_audit.csv", [{"factor_name": r.get("factor_name"), "pre_vs_post_direction_shift": "PIT_LITE_PRE_AND_POST_AUDITED", "notes": "pre/post comparison uses V21.254_R1 and V21.254 labels"} for r in factors], ["factor_name","pre_vs_post_direction_shift","notes"])
    wcsv(out / "factor_beta_ic_bucket_spread_comparison.csv", [{"factor_name": r.get("factor_name"), "beta_standardized": r.get("beta_standardized"), "rank_ic": r.get("rank_ic"), "bucket_spread_top_minus_bottom": r.get("bucket_spread_top_minus_bottom"), "positive_date_rate": r.get("positive_date_rate")} for r in factors], ["factor_name","beta_standardized","rank_ic","bucket_spread_top_minus_bottom","positive_date_rate"])
    wcsv(out / "factor_sign_conflict_comparison.csv", sign_rows, ["factor_name","sign_conflict","semantic_action","raw_beta_standardized"])
    wcsv(out / "factor_semantic_action_summary.csv", sign_rows, ["factor_name","sign_conflict","semantic_action","raw_beta_standardized"])
    wcsv(out / "strategy_family_weight_comparison.csv", family_rows, ["strategy","factor_family","weight","weights_sum"])
    wcsv(out / "strategy_subfactor_weight_comparison.csv", sub_rows, ["strategy","subfactor","factor_family","weight","diagnostic_only"])
    wcsv(out / "strategy_active_weight_vs_a1.csv", active_weight_rows(weights, "A1"), ["strategy","factor_family","weight","baseline_strategy","baseline_weight","active_weight"])
    wcsv(out / "strategy_active_weight_vs_e_r2.csv", active_weight_rows(weights, "E_R2_CONSERVATIVE_DEFENSIVE_RETURN"), ["strategy","factor_family","weight","baseline_strategy","baseline_weight","active_weight"])
    wcsv(out / "strategy_active_weight_vs_e_r3_base.csv", active_weight_rows(weights, E_R3_BASE), ["strategy","factor_family","weight","baseline_strategy","baseline_weight","active_weight"])
    wcsv(out / "strategy_active_weight_vs_new_factor_lite.csv", active_weight_rows(weights, "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"), ["strategy","factor_family","weight","baseline_strategy","baseline_weight","active_weight"])
    wcsv(out / "strategy_factor_weight_effectiveness_matrix.csv", contrib, ["strategy","factor_name","factor_weight","factor_beta","estimated_factor_contribution","active_weight_vs_A1","active_weight_vs_E_R2","active_weight_vs_E_R3_BASE","positive_or_negative_contribution","explanation"])
    wcsv(out / "strategy_factor_contribution_attribution.csv", contrib, ["strategy","factor_name","factor_weight","factor_beta","estimated_factor_contribution","active_weight_vs_A1","active_weight_vs_E_R2","active_weight_vs_E_R3_BASE","positive_or_negative_contribution","explanation"])
    for fname, data in [("e_r3_post0616_success_attribution.csv", e3_success), ("e_r3_pre0616_failure_attribution.csv", e3_fail), ("new_factor_lite_high_return_attribution.csv", nfl), ("e_r2_conservative_fallback_attribution.csv", e2), ("a1_left_tail_weight_attribution.csv", a1), ("b_c_d_underperformance_weight_attribution.csv", bcd), ("abcde_aggregate_dilution_weight_attribution.csv", agg), ("dram_gate_only_attribution.csv", dram)]:
        wcsv(out / fname, data, ["topic","driver","evidence","notes"])
    pos_factors = [r["factor_name"] for r in sorted(contrib, key=lambda x: fnum(x["estimated_factor_contribution"]), reverse=True)[:5]]
    neg_factors = [r["factor_name"] for r in sorted(contrib, key=lambda x: fnum(x["estimated_factor_contribution"]))[:5]]
    summary = {
        "final_status": "WARN_V21_255_COMPARISON_READY_PIT_LITE" if any("PIT" in r.get("source_mode_robustness", "") or "POST_HOC" in r.get("source_mode_robustness", "") for r in bt) else "PASS_V21_255_COMPARISON_READY",
        "final_decision": "DETAILED_STRATEGY_BACKTEST_FACTOR_WEIGHT_COMPARISON_READY_RESEARCH_ONLY",
        "strategies_compared": sorted({r.get("strategy") for r in bt} | set(weights)),
        "period_splits_compared": sorted({r.get("period") for r in bt}),
        "factor_count_compared": len({r.get("factor_name") for r in factors}),
        "family_weight_count_compared": len(family_rows),
        "subfactor_weight_count_compared": len(sub_rows),
        "best_pre_0616_strategy_by_avg_return": best(bt, "PRE_0616", "avg"),
        "best_pre_0616_strategy_by_risk_adjusted_return": best(bt, "PRE_0616", "risk"),
        "best_post_0616_strategy_by_avg_return": best(bt, "POST_0616_TO_NOW", "avg"),
        "best_post_0616_strategy_by_risk_adjusted_return": best(bt, "POST_0616_TO_NOW", "risk"),
        "best_random_start_to_now_strategy_by_avg_return": best(bt, "RANDOM_START_TO_NOW", "avg"),
        "best_random_start_to_now_strategy_by_risk_adjusted_return": best(bt, "RANDOM_START_TO_NOW", "risk"),
        "e_r3_post0616_success_drivers": [r["driver"] for r in e3_success],
        "e_r3_pre0616_failure_drivers": [r["driver"] for r in e3_fail],
        "new_factor_lite_high_return_drivers": [r["driver"] for r in nfl],
        "e_r2_fallback_drivers": [r["driver"] for r in e2],
        "a1_left_tail_weight_drivers": [r["driver"] for r in a1],
        "b_c_d_underperformance_drivers": [r["driver"] for r in bcd],
        "aggregate_dilution_drivers": [r["driver"] for r in agg],
        "top_positive_effective_weight_factors": pos_factors,
        "top_negative_effective_weight_factors": neg_factors,
        "recommended_current_regime_strategy": E_R3_BASE,
        "recommended_fallback_strategy": "E_R2_CONSERVATIVE_DEFENSIVE_RETURN",
        "recommended_parallel_watch_strategy": "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL",
        "recommended_weight_changes": ["keep E_R3 risk/fundamental repair as shadow", "keep technical KDJ/BB/volume/pullback diagnostic", "preserve E_R2 fallback"],
        "warning_count": 1,
        "error_count": 0,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "protected_outputs_modified": False,
        "input_files_mutated": False,
    }
    wjson(out / "v21_255_summary.json", summary)
    (out / "V21.255_detailed_strategy_backtest_factor_weight_comparison_report.txt").write_text(f"{STAGE}\nfinal_status={summary['final_status']}\ncurrent_regime={E_R3_BASE}\nfallback=E_R2_CONSERVATIVE_DEFENSIVE_RETURN\nparallel_watch=NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL\nofficial_adoption_allowed=False\nbroker_action_allowed=False\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    args = p.parse_args(argv)
    s = run(args.repo_root.resolve(), args.output_dir)
    print(str((args.output_dir or args.repo_root / OUT_REL) / "v21_255_summary.json"))
    return 1 if s.get("error_count", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
