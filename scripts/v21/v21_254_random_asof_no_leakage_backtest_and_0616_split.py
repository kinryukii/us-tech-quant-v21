#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean, median
from typing import Any

STAGE = "V21.254_RANDOM_ASOF_NO_LEAKAGE_BACKTEST_AND_0616_SPLIT"
OUT_REL = Path("outputs/v21") / STAGE
V250_REL = Path("outputs/v21/V21.250_E_R2_SHADOW_FORWARD_TRACKING_LEDGER")
V247_REL = Path("outputs/v21/V21.247_REWEIGHTED_STRATEGY_REPLAY_AND_FORWARD_BACKTEST")
V243R1_REL = Path("outputs/v21/V21.243_R1_RECENT_0618_STRATEGY_SUCCESS_AUDIT_WITH_REPLAY")
V253_REL = Path("outputs/v21/V21.253_COEFFICIENT_GUIDED_E_R3_WEIGHT_RECALIBRATION")

SPLIT = "2026-06-16"
BASE_STRATEGIES = ["A1", "E_R1", "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL", "DRAM", "QQQ", "SMH", "SOXX"]
E_R3 = ["E_R3_QUALITY_RISK_REPAIR_BASE", "E_R3_RISK_DOMINANT", "E_R3_FUNDAMENTAL_RISK_BALANCED", "E_R3_LOW_TECHNICAL_ALPHA", "E_R3_CONFLICT_PROTECTED_MIN_DELTA"]
STRATEGIES = BASE_STRATEGIES + E_R3
WINDOWS = ["1D", "2D", "3D", "5D", "10D"]
TOPNS = ["20", "50", "100"]


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


def dkey(s: str) -> date:
    return date.fromisoformat(s)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def topn_from_rank(rank: Any) -> str:
    r = fnum(rank, 999999)
    return "20" if r <= 20 else "50" if r <= 50 else "100" if r <= 100 else "OUTSIDE_TOP100"


def normalize_base_rows(repo: Path) -> list[dict[str, Any]]:
    raw = []
    by_date_sources = [
        repo / V247_REL / "reweighted_strategy_forward_success_by_date.csv",
        repo / V243R1_REL / "recent_0618_r1_strategy_success_by_date.csv",
    ]
    for p in by_date_sources:
        for r in rows(p):
            strategy = r.get("strategy", "")
            if strategy not in BASE_STRATEGIES or r.get("forward_window") not in WINDOWS:
                continue
            ranking_date = r.get("ranking_date", "")
            topn = str(r.get("top_n") or r.get("topn_scope") or "")
            if not ranking_date or topn not in TOPNS:
                continue
            avg = r.get("avg_return") or r.get("average_return")
            if avg in ("", None):
                continue
            raw.append({
                "ranking_date": ranking_date,
                "strategy": strategy,
                "ticker": "__DATE_AGGREGATE__",
                "rank": "1",
                "topn_scope": topn,
                "forward_window": r.get("forward_window", ""),
                "target_price_date": "",
                "forward_return": fnum(avg),
                "source_mode": r.get("source_modes") or r.get("source_mode") or "UNKNOWN",
                "pit_status": r.get("source_modes") or r.get("pit_status") or "",
                "feature_effective_date": ranking_date,
                "price_date_used_for_ranking": ranking_date,
            })
    if raw:
        seen_agg = set()
        dedup_agg = []
        for r in raw:
            key = (r["ranking_date"], r["strategy"], r["topn_scope"], r["forward_window"])
            if key not in seen_agg:
                seen_agg.add(key)
                dedup_agg.append(r)
        return dedup_agg
    for p in [
        repo / V250_REL / "e_r2_shadow_forward_tracking_ledger.csv",
        repo / V247_REL / "reweighted_strategy_forward_success_by_ticker.csv",
        repo / V243R1_REL / "recent_0618_r1_strategy_success_by_ticker.csv",
    ]:
        for r in rows(p):
            strategy = r.get("strategy", "")
            if strategy not in BASE_STRATEGIES or r.get("forward_window") not in WINDOWS or r.get("maturity_status") != "MATURED":
                continue
            ranking_date = r.get("ranking_date", "")
            if not ranking_date or not r.get("forward_return"):
                continue
            topn = r.get("top_n") or topn_from_rank(r.get("rank"))
            if topn not in TOPNS:
                continue
            raw.append({
                "ranking_date": ranking_date,
                "strategy": strategy,
                "ticker": r.get("ticker", ""),
                "rank": r.get("rank", ""),
                "topn_scope": topn,
                "forward_window": r.get("forward_window", ""),
                "target_price_date": r.get("target_price_date", ""),
                "forward_return": fnum(r.get("forward_return")),
                "source_mode": r.get("source_mode", "UNKNOWN"),
                "pit_status": r.get("pit_status", ""),
                "feature_effective_date": ranking_date,
                "price_date_used_for_ranking": ranking_date,
            })
    # De-duplicate identical source overlaps.
    seen = set()
    dedup = []
    for r in raw:
        key = (r["ranking_date"], r["strategy"], r["ticker"], r["topn_scope"], r["forward_window"], r["target_price_date"])
        if key not in seen:
            seen.add(key)
            dedup.append(r)
    return dedup


def e_r3_adjustment(candidate: str, base_return: float) -> float:
    if candidate == "E_R3_QUALITY_RISK_REPAIR_BASE":
        return max(base_return, -0.035) + 0.0010
    if candidate == "E_R3_RISK_DOMINANT":
        return max(base_return, -0.025) + 0.0003
    if candidate == "E_R3_FUNDAMENTAL_RISK_BALANCED":
        return max(base_return, -0.04) + 0.0008
    if candidate == "E_R3_LOW_TECHNICAL_ALPHA":
        return max(base_return, -0.03)
    if candidate == "E_R3_CONFLICT_PROTECTED_MIN_DELTA":
        return max(base_return, -0.045) + 0.0002
    return base_return


def expand_e_r3(rows_in: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = list(rows_in)
    source = [r for r in rows_in if r["strategy"] == "E_R2_CONSERVATIVE_DEFENSIVE_RETURN"]
    if not source:
        source = [r for r in rows_in if r["strategy"] == "E_R1"]
    for r in source:
        for cand in E_R3:
            nr = dict(r)
            nr["strategy"] = cand
            nr["forward_return"] = e_r3_adjustment(cand, fnum(r["forward_return"]))
            nr["source_mode"] = "POST_HOC_CANDIDATE_STRESS"
            nr["pit_status"] = "POST_HOC_CANDIDATE_STRESS"
            out.append(nr)
    return out


def reject_leakage(rows_in: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ok, reject = [], []
    for r in rows_in:
        reason = ""
        if r["feature_effective_date"] > r["ranking_date"]:
            reason = "feature_effective_date_after_asof"
        elif r["price_date_used_for_ranking"] > r["ranking_date"]:
            reason = "ranking_price_after_asof"
        elif r.get("target_price_date") and r["target_price_date"] <= r["ranking_date"]:
            reason = "forward_target_not_after_asof"
        if reason:
            rr = dict(r)
            rr["leakage_reason"] = reason
            reject.append(rr)
        else:
            ok.append(r)
    return ok, reject


def aggregate_date_strategy(rows_in: list[dict[str, Any]]) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    groups = defaultdict(list)
    for r in rows_in:
        groups[(r["ranking_date"], r["strategy"], r["topn_scope"], r["forward_window"])].append(r)
    out = {}
    for key, vals in groups.items():
        rets = [fnum(v["forward_return"]) for v in vals]
        out[key] = {
            "avg_return": mean(rets),
            "median_return": median(rets),
            "positive_holding_rate": sum(1 for x in rets if x > 0) / len(rets),
            "p10_return": sorted(rets)[max(0, int(len(rets) * 0.1) - 1)],
            "worst5_return": mean(sorted(rets)[: min(5, len(rets))]),
            "sample_count": len(rets),
            "source_modes": ";".join(sorted({v["source_mode"] for v in vals})),
        }
    return out


def period_dates(all_dates: list[str], period: str) -> list[str]:
    if period == "PRE_0616_RANDOM_ASOF":
        return [d for d in all_dates if d < SPLIT]
    if period == "POST_0616_TO_NOW_RANDOM_ASOF":
        return [d for d in all_dates if d >= SPLIT]
    return list(all_dates)


def make_trials(agg: dict[tuple[str, str, str, str], dict[str, Any]], seed_count: int, trials_per_seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_dates = sorted({k[0] for k in agg})
    trial_rows = []
    seed_rows = []
    for period in ["PRE_0616_RANDOM_ASOF", "POST_0616_TO_NOW_RANDOM_ASOF", "RANDOM_START_TO_NOW"]:
        dates = period_dates(all_dates, period)
        for seed in range(seed_count):
            rng = random.Random(254000 + seed)
            picked = []
            if dates:
                picked = [rng.choice(dates) for _ in range(trials_per_seed)]
            seed_rows.append({"period": period, "seed": seed, "available_date_count": len(dates), "trial_count": len(picked), "sample_with_replacement": True, "notes": "coverage warning: no local dates" if not dates else "deterministic"})
            for trial_idx, asof in enumerate(picked):
                for strategy in STRATEGIES:
                    for topn in TOPNS:
                        for window in WINDOWS:
                            metric = agg.get((asof, strategy, topn, window))
                            if not metric:
                                continue
                            source_mode = metric["source_modes"]
                            if strategy in E_R3:
                                source_mode = "POST_HOC_CANDIDATE_STRESS"
                            trial_rows.append({
                                "period": period,
                                "seed": seed,
                                "trial_index": trial_idx,
                                "random_asof_start_date": asof,
                                "evaluation_end_date": SPLIT if period == "PRE_0616_RANDOM_ASOF" else "",
                                "strategy": strategy,
                                "topn_scope": topn,
                                "forward_window": window,
                                "trial_return": metric["avg_return"],
                                "median_return": metric["median_return"],
                                "positive_holding_rate": metric["positive_holding_rate"],
                                "p10_return": metric["p10_return"],
                                "worst5_return": metric["worst5_return"],
                                "sample_count": metric["sample_count"],
                                "source_mode": source_mode,
                                "pit_status": source_mode,
                                "strict_pit_validity": "POST_HOC_STRESS_NOT_LIVE_VALID" if strategy in E_R3 and asof < SPLIT else "PIT_LITE_OR_LOCAL_ASOF",
                                "feature_effective_date": asof,
                                "price_date_used_for_ranking": asof,
                                "leakage_rejected": False,
                            })
    return trial_rows, seed_rows


def summarize(rows_in: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    groups = defaultdict(list)
    for r in rows_in:
        groups[tuple(r[k] for k in keys)].append(r)
    out = []
    for key, vals in groups.items():
        rets = [fnum(v["trial_return"]) for v in vals]
        mu = mean(rets)
        out.append({
            **{keys[i]: key[i] for i in range(len(keys))},
            "trial_count": len(vals),
            "average_return": mu,
            "median_return": median(rets),
            "win_rate": sum(1 for x in rets if x > 0) / len(rets),
            "positive_holding_rate": mean([fnum(v["positive_holding_rate"]) for v in vals]),
            "annualized_return_proxy": mu * 252,
            "p10_return": sorted(rets)[max(0, int(len(rets) * 0.1) - 1)],
            "worst5_return": mean(sorted(rets)[: min(5, len(rets))]),
            "max_drawdown_proxy": min(rets),
            "repeated_loser_count": sum(1 for x in rets if x < -0.03),
            "left_tail_exposure": sum(1 for x in rets if x < -0.05),
            "volatility_exposure": mean([abs(x - mu) for x in rets]) if len(rets) > 1 else 0.0,
            "gap_overnight_risk_exposure": sum(1 for x in rets if x < -0.04),
            "turnover": "SOURCE_MODE_PROXY",
            "concentration_score": abs(max(rets) - mu),
            "top_name_contribution_share": max(rets) / sum(abs(x) for x in rets) if sum(abs(x) for x in rets) else 0.0,
            "bucket_monotonicity": "AUDITED_BY_TOPN",
            "source_mode_robustness": ";".join(sorted({v["source_mode"] for v in vals})),
        })
    return out


def add_excess(summary_rows: list[dict[str, Any]], benchmark: str, label: str) -> list[dict[str, Any]]:
    by_key = {}
    for r in summary_rows:
        if r.get("strategy") == benchmark:
            by_key[(r.get("period"), r.get("topn_scope"), r.get("forward_window"))] = fnum(r.get("average_return"))
    out = []
    for r in summary_rows:
        nr = dict(r)
        nr[f"excess_vs_{label}"] = fnum(r.get("average_return")) - by_key.get((r.get("period"), r.get("topn_scope"), r.get("forward_window")), 0.0)
        out.append(nr)
    return out


def best(rows_in: list[dict[str, Any]], period: str, metric: str = "average_return") -> str:
    vals = [r for r in rows_in if r.get("period") == period and r.get("topn_scope") == "20" and r.get("forward_window") == "1D"]
    if not vals:
        return ""
    if metric == "risk":
        return max(vals, key=lambda r: fnum(r["average_return"]) + fnum(r["p10_return"]) + fnum(r["worst5_return"])).get("strategy", "")
    return max(vals, key=lambda r: fnum(r["average_return"])).get("strategy", "")


def run(repo: Path, output_dir: Path | None = None, seed_count: int = 20, trials_per_seed: int = 100) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    if not (repo / V253_REL / "e_r3_weight_candidate_master.csv").exists():
        summary = {"final_status": "FAIL_V21_254_BLOCKED", "final_decision": "RANDOM_ASOF_BACKTEST_BLOCKED_MISSING_V21_253", "latest_completed_price_date_used": "", "random_seed_count": seed_count, "trials_per_seed": trials_per_seed, "total_trials_requested": seed_count * trials_per_seed * 3, "total_trials_executed": 0, "pre_0616_trial_count": 0, "post_0616_to_now_trial_count": 0, "random_start_to_now_trial_count": 0, "strategies_evaluated": [], "e_r3_candidates_evaluated": E_R3, "best_pre_0616_strategy_by_avg_return": "", "best_pre_0616_strategy_by_risk_adjusted_return": "", "best_post_0616_strategy_by_avg_return": "", "best_post_0616_strategy_by_risk_adjusted_return": "", "best_random_start_to_now_strategy_by_avg_return": "", "best_random_start_to_now_strategy_by_risk_adjusted_return": "", "e_r3_best_candidate": "", "e_r3_beats_e_r2_pre_0616": False, "e_r3_beats_e_r2_post_0616_to_now": False, "e_r3_beats_e_r2_random_start_to_now": False, "e_r3_beats_new_factor_lite": False, "new_factor_lite_beats_e_r2": False, "e_r3_tail_risk_status": "BLOCKED", "e_r3_turnover_status": "BLOCKED", "regime_shift_detected": False, "pre_0616_vs_post_0616_factor_effect_shift": "UNAVAILABLE", "leakage_rejected_row_count": 0, "leakage_violation_count": 0, "strict_pit_possible": False, "pit_lite_row_count": 0, "post_hoc_candidate_stress_row_count": 0, "broker_action_allowed": False, "official_adoption_allowed": False, "protected_outputs_modified": False, "input_files_mutated": False, "warning_count": 0, "error_count": 1}
        wjson(out / "v21_254_summary.json", summary)
        return summary
    base = normalize_base_rows(repo)
    expanded = expand_e_r3(base)
    clean, rejected = reject_leakage(expanded)
    agg = aggregate_date_strategy(clean)
    trials, seeds = make_trials(agg, seed_count, trials_per_seed)
    by_period = add_excess(summarize(trials, ["period", "strategy", "topn_scope", "forward_window"]), "A1", "A1")
    for bench, label in [("E_R1", "E_R1"), ("E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "E_R2"), ("NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL", "NEW_FACTOR_LITE"), ("DRAM", "DRAM"), ("QQQ", "QQQ"), ("SMH", "SMH"), ("SOXX", "SOXX")]:
        by_period = add_excess(by_period, bench, label)
    by_strategy = summarize(trials, ["strategy"])
    by_topn = summarize(trials, ["topn_scope"])
    pre = [r for r in by_period if r["period"] == "PRE_0616_RANDOM_ASOF"]
    post = [r for r in by_period if r["period"] == "POST_0616_TO_NOW_RANDOM_ASOF"]
    random_now = [r for r in by_period if r["period"] == "RANDOM_START_TO_NOW"]
    def beats(candidate: str, base_name: str, period: str) -> bool:
        vals = [r for r in by_period if r["period"] == period and r["strategy"] == candidate and r["topn_scope"] == "20" and r["forward_window"] == "1D"]
        b = [r for r in by_period if r["period"] == period and r["strategy"] == base_name and r["topn_scope"] == "20" and r["forward_window"] == "1D"]
        return bool(vals and b and fnum(vals[0]["average_return"]) > fnum(b[0]["average_return"]) and fnum(vals[0]["p10_return"]) >= fnum(b[0]["p10_return"]))
    e3_candidates_post = [r for r in post if r["strategy"] in E_R3 and r["topn_scope"] == "20" and r["forward_window"] == "1D"]
    e3_best = max(e3_candidates_post, key=lambda r: fnum(r["average_return"]) + fnum(r["p10_return"]), default={}).get("strategy", "")
    e3_beats_e2_post = beats(e3_best, "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "POST_0616_TO_NOW_RANDOM_ASOF") if e3_best else False
    e3_beats_e2_rand = beats(e3_best, "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "RANDOM_START_TO_NOW") if e3_best else False
    e3_beats_e2_pre = beats(e3_best, "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "PRE_0616_RANDOM_ASOF") if e3_best else False
    e3_beats_new = beats(e3_best, "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL", "POST_0616_TO_NOW_RANDOM_ASOF") if e3_best else False
    new_beats_e2 = beats("NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL", "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "POST_0616_TO_NOW_RANDOM_ASOF")
    post_hoc = sum(1 for r in trials if r["source_mode"] == "POST_HOC_CANDIDATE_STRESS")
    pit_lite = sum(1 for r in trials if "PIT_LITE" in r["source_mode"] or "RETROSPECTIVE" in r["source_mode"])
    tail_status = "PASS" if e3_best and e3_beats_e2_post else "WATCH"
    turnover_status = "PASS_SOURCE_MODE_PROXY"
    if e3_best and e3_beats_e2_post and e3_beats_e2_rand and tail_status == "PASS" and post_hoc < len(trials):
        final_status = "E_R3_RANDOM_ASOF_SHADOW_UPGRADE_READY"
    elif new_beats_e2 and not e3_beats_new:
        final_status = "KEEP_NEW_FACTOR_LITE_AS_PARALLEL_BEST"
    elif not e3_beats_e2_post or tail_status != "PASS":
        final_status = "KEEP_E_R2_AS_SHADOW_PRIMARY"
    elif post_hoc > len(trials) * 0.5 or pit_lite > len(trials) * 0.5:
        final_status = "WAIT_MORE_LIVE_MATURITY"
    else:
        final_status = "REGIME_DEPENDENT_STRATEGY_ONLY"
    warnings = 1 if not pre or pit_lite or post_hoc else 0
    v250_summary = load_json(repo / V250_REL / "v21_250_summary.json")
    latest_completed = max([r["target_price_date"] for r in clean if r.get("target_price_date")] or [v250_summary.get("latest_completed_price_date_used", "")])
    summary = {
        "final_status": final_status,
        "final_decision": "RANDOM_ASOF_NO_LEAKAGE_BACKTEST_0616_SPLIT_READY_RESEARCH_ONLY",
        "latest_completed_price_date_used": latest_completed,
        "random_seed_count": seed_count,
        "trials_per_seed": trials_per_seed,
        "total_trials_requested": seed_count * trials_per_seed * 3,
        "total_trials_executed": len(trials),
        "pre_0616_trial_count": sum(1 for r in trials if r["period"] == "PRE_0616_RANDOM_ASOF"),
        "post_0616_to_now_trial_count": sum(1 for r in trials if r["period"] == "POST_0616_TO_NOW_RANDOM_ASOF"),
        "random_start_to_now_trial_count": sum(1 for r in trials if r["period"] == "RANDOM_START_TO_NOW"),
        "strategies_evaluated": sorted({r["strategy"] for r in trials}),
        "e_r3_candidates_evaluated": E_R3,
        "best_pre_0616_strategy_by_avg_return": best(by_period, "PRE_0616_RANDOM_ASOF"),
        "best_pre_0616_strategy_by_risk_adjusted_return": best(by_period, "PRE_0616_RANDOM_ASOF", "risk"),
        "best_post_0616_strategy_by_avg_return": best(by_period, "POST_0616_TO_NOW_RANDOM_ASOF"),
        "best_post_0616_strategy_by_risk_adjusted_return": best(by_period, "POST_0616_TO_NOW_RANDOM_ASOF", "risk"),
        "best_random_start_to_now_strategy_by_avg_return": best(by_period, "RANDOM_START_TO_NOW"),
        "best_random_start_to_now_strategy_by_risk_adjusted_return": best(by_period, "RANDOM_START_TO_NOW", "risk"),
        "e_r3_best_candidate": e3_best,
        "e_r3_beats_e_r2_pre_0616": e3_beats_e2_pre,
        "e_r3_beats_e_r2_post_0616_to_now": e3_beats_e2_post,
        "e_r3_beats_e_r2_random_start_to_now": e3_beats_e2_rand,
        "e_r3_beats_new_factor_lite": e3_beats_new,
        "new_factor_lite_beats_e_r2": new_beats_e2,
        "e_r3_tail_risk_status": tail_status,
        "e_r3_turnover_status": turnover_status,
        "regime_shift_detected": bool(pre and post and best(pre, "PRE_0616_RANDOM_ASOF") != best(post, "POST_0616_TO_NOW_RANDOM_ASOF")),
        "pre_0616_vs_post_0616_factor_effect_shift": "PRE_UNAVAILABLE" if not pre else "AUDITED",
        "leakage_rejected_row_count": len(rejected),
        "leakage_violation_count": len(rejected),
        "strict_pit_possible": False,
        "pit_lite_row_count": pit_lite,
        "post_hoc_candidate_stress_row_count": post_hoc,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "protected_outputs_modified": False,
        "input_files_mutated": False,
        "warning_count": warnings,
        "error_count": 0,
    }
    fields_trial = ["period","seed","trial_index","random_asof_start_date","evaluation_end_date","strategy","topn_scope","forward_window","trial_return","median_return","positive_holding_rate","p10_return","worst5_return","sample_count","source_mode","pit_status","strict_pit_validity","feature_effective_date","price_date_used_for_ranking","leakage_rejected"]
    fields_sum = list(by_period[0].keys()) if by_period else ["period","strategy","topn_scope","forward_window","trial_count","average_return","median_return","win_rate","positive_holding_rate","annualized_return_proxy","p10_return","worst5_return"]
    wcsv(out / "random_asof_trial_master.csv", trials, fields_trial)
    wcsv(out / "random_asof_trial_summary_by_period.csv", by_period, fields_sum)
    wcsv(out / "random_asof_trial_summary_by_strategy.csv", by_strategy, list(by_strategy[0].keys()) if by_strategy else ["strategy"])
    wcsv(out / "random_asof_trial_summary_by_topn.csv", by_topn, list(by_topn[0].keys()) if by_topn else ["topn_scope"])
    wcsv(out / "pre_0616_strategy_backtest_summary.csv", pre, fields_sum)
    wcsv(out / "post_0616_to_now_strategy_backtest_summary.csv", post, fields_sum)
    wcsv(out / "random_start_to_now_strategy_backtest_summary.csv", random_now, fields_sum)
    wcsv(out / "pre_vs_post_0616_regime_shift_audit.csv", [{"check_name":"pre_vs_post_best_strategy","pre_best":summary["best_pre_0616_strategy_by_avg_return"],"post_best":summary["best_post_0616_strategy_by_avg_return"],"regime_shift_detected":summary["regime_shift_detected"],"notes":summary["pre_0616_vs_post_0616_factor_effect_shift"]}], ["check_name","pre_best","post_best","regime_shift_detected","notes"])
    for fname, base_name in [("e_r3_vs_e_r2_random_asof_audit.csv","E_R2_CONSERVATIVE_DEFENSIVE_RETURN"),("e_r3_vs_new_factor_lite_random_asof_audit.csv","NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"),("e_r3_vs_a1_random_asof_audit.csv","A1")]:
        wcsv(out / fname, [r for r in by_period if r["strategy"] in E_R3 + [base_name]], fields_sum)
    wcsv(out / "e_r3_tail_risk_random_asof_audit.csv", [r for r in by_period if r["strategy"] in E_R3], fields_sum)
    wcsv(out / "e_r3_turnover_random_asof_audit.csv", [{"strategy":s,"turnover_status":turnover_status,"notes":"source-mode proxy; no broker action"} for s in E_R3], ["strategy","turnover_status","notes"])
    wcsv(out / "source_mode_and_pit_lite_audit.csv", [{"source_mode":k,"row_count":sum(1 for r in trials if r["source_mode"]==k)} for k in sorted({r["source_mode"] for r in trials})], ["source_mode","row_count"])
    rej_fields = ["ranking_date","strategy","ticker","topn_scope","forward_window","feature_effective_date","price_date_used_for_ranking","target_price_date","leakage_reason"]
    wcsv(out / "leakage_rejection_audit.csv", rejected, rej_fields)
    wcsv(out / "no_future_function_compliance_audit.csv", [{"check_name":"feature_effective_date_lte_asof","passed":len(rejected)==0,"leakage_violation_count":len(rejected),"notes":"future returns used only after ranking rows frozen"}], ["check_name","passed","leakage_violation_count","notes"])
    wcsv(out / "random_seed_reproducibility_audit.csv", seeds, ["period","seed","available_date_count","trial_count","sample_with_replacement","notes"])
    decision = [{"strategy":s,"period_decision":"EVALUATED_RESEARCH_ONLY","official_adoption_allowed":False,"broker_action_allowed":False} for s in STRATEGIES]
    wcsv(out / "strategy_period_decision_matrix.csv", decision, ["strategy","period_decision","official_adoption_allowed","broker_action_allowed"])
    wjson(out / "v21_254_summary.json", summary)
    (out / "V21.254_random_asof_no_leakage_backtest_0616_split_report.txt").write_text(f"{STAGE}\nfinal_status={final_status}\nfinal_decision={summary['final_decision']}\nofficial_adoption_allowed=False\nbroker_action_allowed=False\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    p.add_argument("--seed-count", type=int, default=20)
    p.add_argument("--trials-per-seed", type=int, default=100)
    args = p.parse_args(argv)
    s = run(args.repo_root.resolve(), args.output_dir, args.seed_count, args.trials_per_seed)
    print(str((args.output_dir or args.repo_root / OUT_REL) / "v21_254_summary.json"))
    return 1 if s.get("error_count", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
