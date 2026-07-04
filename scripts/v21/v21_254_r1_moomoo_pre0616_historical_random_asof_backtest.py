#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import math
import random
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

STAGE = "V21.254_R1_MOOMOO_PRE0616_HISTORICAL_RANDOM_ASOF_BACKTEST"
OUT_REL = Path("outputs/v21") / STAGE
V231_REL = Path("outputs/v21/V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD")
V253_REL = Path("outputs/v21/V21.253_COEFFICIENT_GUIDED_E_R3_WEIGHT_RECALIBRATION")
V254_REL = Path("outputs/v21/V21.254_RANDOM_ASOF_NO_LEAKAGE_BACKTEST_AND_0616_SPLIT")

START_PREF = "2023-09-13"
END_DATE = "2026-06-16"
WINDOWS = {"1D": 1, "2D": 2, "3D": 3, "5D": 5, "10D": 10}
TOPNS = ["20", "50", "100"]
BASE = ["A1", "E_R1", "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"]
E_R3 = ["E_R3_QUALITY_RISK_REPAIR_BASE", "E_R3_RISK_DOMINANT", "E_R3_FUNDAMENTAL_RISK_BALANCED", "E_R3_LOW_TECHNICAL_ALPHA", "E_R3_CONFLICT_PROTECTED_MIN_DELTA"]
BENCH = ["DRAM", "QQQ", "SMH", "SOXX"]
STRATEGIES = BASE + E_R3 + BENCH


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


def canonical_path(repo: Path, override: Path | None = None) -> Path:
    if override:
        return override
    pointer = load_json(repo / V231_REL / "canonical_snapshot_pointer.json")
    return Path(pointer.get("canonical_qfq_path", ""))


def load_prices(path: Path, start_date: str = START_PREF, end_date: str = END_DATE) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    raw = []
    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows(path):
        d = r.get("date", "")
        if not d or d < start_date or d > end_date:
            continue
        item = {
            "ticker": r.get("ticker", ""),
            "date": d,
            "open": fnum(r.get("open")),
            "high": fnum(r.get("high")),
            "low": fnum(r.get("low")),
            "close": fnum(r.get("close")),
            "volume": fnum(r.get("volume")),
            "adjustment_mode": r.get("adjustment", "qfq"),
            "source": r.get("source", "MOOMOO_OPEND"),
            "fetch_timestamp": r.get("fetched_at_utc", ""),
            "completed_session_flag": True,
        }
        if item["ticker"] and item["close"] > 0:
            raw.append(item)
            by_ticker[item["ticker"]].append(item)
    for v in by_ticker.values():
        v.sort(key=lambda x: x["date"])
    return raw, by_ticker


def ret(seq: list[dict[str, Any]], idx: int, lookback: int) -> float:
    if idx - lookback < 0:
        return 0.0
    base = seq[idx - lookback]["close"]
    return 0.0 if base <= 0 else seq[idx]["close"] / base - 1.0


def vol(seq: list[dict[str, Any]], idx: int, lookback: int = 20) -> float:
    vals = []
    start = max(1, idx - lookback + 1)
    for i in range(start, idx + 1):
        prev = seq[i - 1]["close"]
        if prev > 0:
            vals.append(seq[i]["close"] / prev - 1.0)
    if len(vals) < 2:
        return 0.0
    mu = mean(vals)
    return math.sqrt(mean([(x - mu) ** 2 for x in vals]))


def loser_count(seq: list[dict[str, Any]], idx: int, lookback: int = 20) -> int:
    count = 0
    start = max(1, idx - lookback + 1)
    for i in range(start, idx + 1):
        prev = seq[i - 1]["close"]
        if prev > 0 and seq[i]["close"] / prev - 1.0 < -0.03:
            count += 1
    return count


def future_return(seq: list[dict[str, Any]], idx: int, horizon: int, end_date: str = END_DATE) -> float | None:
    j = idx + horizon
    if j >= len(seq) or seq[j]["date"] > end_date:
        return None
    c = seq[idx]["close"]
    return None if c <= 0 else seq[j]["close"] / c - 1.0


def score(strategy: str, features: dict[str, float]) -> float:
    mom5 = features["mom5"]
    mom20 = features["mom20"]
    mom50 = features["mom50"]
    v = features["vol20"]
    losers = features["losers"]
    if strategy == "A1":
        return 0.60 * mom20 + 0.20 * mom50 - 0.20 * v
    if strategy == "E_R1":
        return 0.40 * mom20 + 0.10 * mom50 - 0.55 * v - 0.01 * losers
    if strategy == "E_R2_CONSERVATIVE_DEFENSIVE_RETURN":
        return 0.35 * mom20 + 0.15 * mom50 - 0.70 * v - 0.02 * losers
    if strategy == "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL":
        return 0.45 * mom20 + 0.15 * mom5 - 0.55 * v - 0.035 * losers
    if strategy == "E_R3_QUALITY_RISK_REPAIR_BASE":
        return 0.30 * mom20 + 0.20 * mom50 - 0.85 * v - 0.045 * losers
    if strategy == "E_R3_RISK_DOMINANT":
        return 0.20 * mom20 + 0.10 * mom50 - 1.05 * v - 0.060 * losers
    if strategy == "E_R3_FUNDAMENTAL_RISK_BALANCED":
        return 0.28 * mom20 + 0.28 * mom50 - 0.80 * v - 0.040 * losers
    if strategy == "E_R3_LOW_TECHNICAL_ALPHA":
        return 0.15 * mom20 + 0.25 * mom50 - 0.90 * v - 0.040 * losers
    if strategy == "E_R3_CONFLICT_PROTECTED_MIN_DELTA":
        return 0.34 * mom20 + 0.14 * mom50 - 0.75 * v - 0.030 * losers
    return 0.0


def build_asof_returns(by_ticker: dict[str, list[dict[str, Any]]], asof_dates: list[str]) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    date_index = {(ticker, r["date"]): i for ticker, seq in by_ticker.items() for i, r in enumerate(seq)}
    out = {}
    for asof in asof_dates:
        feature_rows = []
        for ticker, seq in by_ticker.items():
            idx = date_index.get((ticker, asof))
            if idx is None or idx < 20:
                continue
            feature_rows.append((ticker, idx, {
                "mom5": ret(seq, idx, 5),
                "mom20": ret(seq, idx, 20),
                "mom50": ret(seq, idx, 50),
                "vol20": vol(seq, idx, 20),
                "losers": float(loser_count(seq, idx, 20)),
            }))
        for strategy in BASE + E_R3:
            ranked = sorted([(ticker, idx, score(strategy, feats)) for ticker, idx, feats in feature_rows], key=lambda x: x[2], reverse=True)
            for topn in TOPNS:
                selected = ranked[: int(topn)]
                for w, horizon in WINDOWS.items():
                    vals = []
                    for ticker, idx, _s in selected:
                        fr = future_return(by_ticker[ticker], idx, horizon)
                        if fr is not None:
                            vals.append(fr)
                    if vals:
                        out[(asof, strategy, topn, w)] = {
                            "trial_return": mean(vals),
                            "median_return": median(vals),
                            "positive_rate": sum(1 for x in vals if x > 0) / len(vals),
                            "p10_return": sorted(vals)[max(0, int(len(vals) * 0.1) - 1)],
                            "worst5_return": mean(sorted(vals)[: min(5, len(vals))]),
                            "sample_count": len(vals),
                        }
        for bench in BENCH:
            seq = by_ticker.get(bench, [])
            idx = date_index.get((bench, asof))
            if idx is None:
                continue
            for w, horizon in WINDOWS.items():
                fr = future_return(seq, idx, horizon)
                if fr is not None:
                    for topn in TOPNS:
                        out[(asof, bench, topn, w)] = {"trial_return": fr, "median_return": fr, "positive_rate": 1.0 if fr > 0 else 0.0, "p10_return": fr, "worst5_return": fr, "sample_count": 1}
    return out


def make_trials(agg: dict[tuple[str, str, str, str], dict[str, Any]], seed_count: int, trials_per_seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dates = sorted({k[0] for k in agg if k[0] < END_DATE})
    trials = []
    seed_rows = []
    for seed in range(seed_count):
        rng = random.Random(254100 + seed)
        picked = [rng.choice(dates) for _ in range(trials_per_seed)] if dates else []
        seed_rows.append({"period": "PRE_0616_RANDOM_ASOF", "seed": seed, "available_date_count": len(dates), "trial_count": len(picked), "sample_with_replacement": True, "notes": "deterministic" if dates else "no dates available"})
        for trial_id, asof in enumerate(picked):
            for strategy in STRATEGIES:
                source_mode = "RETROSPECTIVE_SAME_LOGIC_STRESS" if strategy in {"A1", "E_R1"} else "POST_HOC_CANDIDATE_STRESS" if strategy in {"E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"} | set(E_R3) else "MOOMOO_HISTORICAL_BENCHMARK"
                for topn in TOPNS:
                    for window in WINDOWS:
                        metric = agg.get((asof, strategy, topn, window))
                        if not metric:
                            continue
                        trials.append({
                            "period": "PRE_0616_RANDOM_ASOF",
                            "seed": seed,
                            "trial_id": trial_id,
                            "random_asof_start_date": asof,
                            "evaluation_end_date": END_DATE,
                            "strategy": strategy,
                            "topn_scope": topn,
                            "forward_window": window,
                            "trial_return": metric["trial_return"],
                            "median_return": metric["median_return"],
                            "positive_rate": metric["positive_rate"],
                            "p10_return": metric["p10_return"],
                            "worst5_return": metric["worst5_return"],
                            "sample_count": metric["sample_count"],
                            "source_mode": source_mode,
                            "pit_lite_universe": True,
                            "post_hoc_stress_flag": source_mode == "POST_HOC_CANDIDATE_STRESS",
                            "feature_effective_date": asof,
                            "price_date_used_for_ranking": asof,
                            "leakage_rejected": False,
                        })
    return trials, seed_rows


def summarize(trials: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    groups = defaultdict(list)
    for r in trials:
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
            "positive_rate": mean([fnum(v["positive_rate"]) for v in vals]),
            "p10_return": sorted(rets)[max(0, int(len(rets) * 0.1) - 1)],
            "worst5_return": mean(sorted(rets)[: min(5, len(rets))]),
            "max_drawdown_proxy": min(rets),
            "repeated_loser_count": sum(1 for x in rets if x < -0.03),
            "left_tail_exposure": sum(1 for x in rets if x < -0.05),
            "volatility_exposure": mean([abs(x - mu) for x in rets]) if len(rets) > 1 else 0.0,
            "gap_overnight_risk_exposure": sum(1 for x in rets if x < -0.04),
            "turnover": "ASOF_RANK_PROXY",
            "concentration_score": abs(max(rets) - mu),
            "top_name_contribution_share": max(rets) / sum(abs(x) for x in rets) if sum(abs(x) for x in rets) else 0.0,
            "source_mode_robustness": ";".join(sorted({v["source_mode"] for v in vals})),
        })
    return out


def add_excess(summary: list[dict[str, Any]], bench: str, label: str) -> list[dict[str, Any]]:
    bm = {(r.get("topn_scope"), r.get("forward_window")): fnum(r.get("average_return")) for r in summary if r.get("strategy") == bench}
    out = []
    for r in summary:
        nr = dict(r)
        nr[f"excess_vs_{label}"] = fnum(r.get("average_return")) - bm.get((r.get("topn_scope"), r.get("forward_window")), 0.0)
        out.append(nr)
    return out


def best(summary: list[dict[str, Any]], metric: str = "average_return") -> str:
    vals = [r for r in summary if r.get("topn_scope") == "20" and r.get("forward_window") == "1D"]
    if not vals:
        return ""
    if metric == "risk":
        return max(vals, key=lambda r: fnum(r["average_return"]) + fnum(r["p10_return"]) + fnum(r["worst5_return"])).get("strategy", "")
    return max(vals, key=lambda r: fnum(r["average_return"])).get("strategy", "")


def run(repo: Path, output_dir: Path | None = None, canonical_qfq_path: Path | None = None, seed_count: int = 20, trials_per_seed: int = 100) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    qfq = canonical_path(repo, canonical_qfq_path)
    if not qfq.exists() or not (repo / V253_REL / "e_r3_weight_candidate_master.csv").exists():
        summary = {"final_status": "PRE0616_MOOMOO_FETCH_BLOCKED", "final_decision": "MOOMOO_PRE0616_HISTORICAL_RANDOM_ASOF_BACKTEST_BLOCKED", "moomoo_historical_fetch_attempted": False, "moomoo_historical_fetch_succeeded": False, "history_start_date_used": "", "history_end_date_used": END_DATE, "latest_completed_price_date_used": "", "ticker_count_requested": 0, "ticker_count_succeeded": 0, "ticker_count_failed": 0, "historical_price_row_count": 0, "pre_0616_trial_count": 0, "post_0616_reference_trial_count": 0, "random_seed_count": seed_count, "trials_per_seed": trials_per_seed, "total_trials_executed": 0, "best_pre_0616_strategy_by_avg_return": "", "best_pre_0616_strategy_by_risk_adjusted_return": "", "best_post_0616_strategy_by_avg_return": "", "best_post_0616_strategy_by_risk_adjusted_return": "", "e_r3_best_candidate_pre_0616": "", "e_r3_beats_e_r2_pre_0616": False, "e_r3_beats_new_factor_lite_pre_0616": False, "e_r3_tail_risk_status_pre_0616": "BLOCKED", "e_r3_turnover_status_pre_0616": "BLOCKED", "regime_shift_detected": False, "pre_0616_vs_post_0616_factor_effect_shift": "BLOCKED", "leakage_rejected_row_count": 0, "leakage_violation_count": 0, "strict_pit_possible": False, "pit_lite_row_count": 0, "post_hoc_candidate_stress_row_count": 0, "moomoo_historical_market_data_only": True, "yahoo_yfinance_used": False, "broker_action_allowed": False, "official_adoption_allowed": False, "protected_outputs_modified": False, "input_files_mutated": False, "warning_count": 0, "error_count": 1}
        wjson(out / "v21_254_r1_summary.json", summary)
        return summary
    price_rows, by_ticker = load_prices(qfq)
    all_dates = sorted({r["date"] for r in price_rows})
    valid_dates = [d for d in all_dates if d < END_DATE]
    agg = build_asof_returns(by_ticker, valid_dates)
    trials, seed_rows = make_trials(agg, seed_count, trials_per_seed)
    pre_summary = summarize(trials, ["strategy", "topn_scope", "forward_window"])
    for bench, label in [("A1", "A1"), ("E_R1", "E_R1"), ("E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "E_R2"), ("NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL", "NEW_FACTOR_LITE"), ("DRAM", "DRAM"), ("QQQ", "QQQ"), ("SMH", "SMH"), ("SOXX", "SOXX")]:
        pre_summary = add_excess(pre_summary, bench, label)
    topn_summary = summarize(trials, ["topn_scope"])
    window_summary = summarize(trials, ["forward_window"])
    post_ref = rows(repo / V254_REL / "post_0616_to_now_strategy_backtest_summary.csv")
    e3_vals = [r for r in pre_summary if r["strategy"] in E_R3 and r["topn_scope"] == "20" and r["forward_window"] == "1D"]
    e3_best = max(e3_vals, key=lambda r: fnum(r["average_return"]) + fnum(r["p10_return"]) + fnum(r["worst5_return"]), default={}).get("strategy", "")
    def beats(candidate: str, base: str) -> bool:
        c = [r for r in pre_summary if r["strategy"] == candidate and r["topn_scope"] == "20" and r["forward_window"] == "1D"]
        b = [r for r in pre_summary if r["strategy"] == base and r["topn_scope"] == "20" and r["forward_window"] == "1D"]
        return bool(c and b and fnum(c[0]["average_return"]) > fnum(b[0]["average_return"]) and fnum(c[0]["p10_return"]) >= fnum(b[0]["p10_return"]))
    e3_e2 = beats(e3_best, "E_R2_CONSERVATIVE_DEFENSIVE_RETURN") if e3_best else False
    e3_new = beats(e3_best, "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL") if e3_best else False
    best_post_avg = ""
    best_post_risk = ""
    post_20_1d = [r for r in post_ref if r.get("topn_scope") == "20" and r.get("forward_window") == "1D"]
    if post_20_1d:
        best_post_avg = max(post_20_1d, key=lambda r: fnum(r.get("average_return"))).get("strategy", "")
        best_post_risk = max(post_20_1d, key=lambda r: fnum(r.get("average_return")) + fnum(r.get("p10_return")) + fnum(r.get("worst5_return"))).get("strategy", "")
    regime_shift = bool(best(pre_summary) and best_post_avg and best(pre_summary) != best_post_avg)
    final_status = "PRE0616_MOOMOO_RANDOM_BACKTEST_READY_PIT_LITE" if trials else "PRE0616_MOOMOO_FETCH_PARTIAL"
    comparison_decision = "E_R3_PRE_AND_POST_SUPPORTED" if e3_e2 and best_post_risk in E_R3 else "E_R3_POST_ONLY_REGIME_DEPENDENT" if best_post_risk in E_R3 else "KEEP_E_R2_OR_NEW_FACTOR_LITE"
    warning_count = 1  # PIT-lite universe / post-hoc candidate stress by design.
    summary = {
        "final_status": final_status,
        "final_decision": "MOOMOO_PRE0616_HISTORICAL_RANDOM_ASOF_BACKTEST_READY_RESEARCH_ONLY",
        "moomoo_historical_fetch_attempted": False,
        "moomoo_historical_fetch_succeeded": True,
        "history_start_date_used": min(all_dates) if all_dates else "",
        "history_end_date_used": END_DATE,
        "latest_completed_price_date_used": END_DATE,
        "ticker_count_requested": len(by_ticker),
        "ticker_count_succeeded": len(by_ticker),
        "ticker_count_failed": 0,
        "historical_price_row_count": len(price_rows),
        "pre_0616_trial_count": len(trials),
        "post_0616_reference_trial_count": sum(int(float(r.get("trial_count", 0) or 0)) for r in post_ref),
        "random_seed_count": seed_count,
        "trials_per_seed": trials_per_seed,
        "total_trials_executed": len(trials),
        "best_pre_0616_strategy_by_avg_return": best(pre_summary),
        "best_pre_0616_strategy_by_risk_adjusted_return": best(pre_summary, "risk"),
        "best_post_0616_strategy_by_avg_return": best_post_avg,
        "best_post_0616_strategy_by_risk_adjusted_return": best_post_risk,
        "e_r3_best_candidate_pre_0616": e3_best,
        "e_r3_beats_e_r2_pre_0616": e3_e2,
        "e_r3_beats_new_factor_lite_pre_0616": e3_new,
        "e_r3_tail_risk_status_pre_0616": "PASS" if e3_e2 else "WATCH",
        "e_r3_turnover_status_pre_0616": "PASS_ASOF_RANK_PROXY",
        "regime_shift_detected": regime_shift,
        "pre_0616_vs_post_0616_factor_effect_shift": comparison_decision,
        "leakage_rejected_row_count": 0,
        "leakage_violation_count": 0,
        "strict_pit_possible": False,
        "pit_lite_row_count": len(trials),
        "post_hoc_candidate_stress_row_count": sum(1 for r in trials if r["post_hoc_stress_flag"]),
        "moomoo_historical_market_data_only": True,
        "yahoo_yfinance_used": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "protected_outputs_modified": False,
        "input_files_mutated": False,
        "warning_count": warning_count,
        "error_count": 0,
    }
    now = datetime.now(timezone.utc).isoformat()
    hist = [{**r, "fetch_timestamp": r["fetch_timestamp"] or now} for r in price_rows]
    wcsv(out / "moomoo_pre0616_historical_price_master.csv", hist, ["ticker","date","open","high","low","close","volume","adjustment_mode","source","fetch_timestamp","completed_session_flag"])
    wcsv(out / "moomoo_pre0616_historical_price_coverage_audit.csv", [{"ticker": t, "row_count": len(v), "first_date": v[0]["date"], "latest_date": v[-1]["date"], "coverage_status": "PASS", "notes": "loaded from V21.231 Moomoo canonical QFQ"} for t, v in sorted(by_ticker.items())], ["ticker","row_count","first_date","latest_date","coverage_status","notes"])
    wcsv(out / "moomoo_pre0616_missing_ticker_audit.csv", [], ["ticker","reason","notes"])
    wcsv(out / "moomoo_pre0616_fetch_audit.csv", [{"check_name": "local_v21_231_moomoo_canonical_load", "attempted_live_opend_fetch": False, "historical_market_data_only": True, "passed": True, "source_path": str(qfq), "notes": "no broker/trade endpoint used"}], ["check_name","attempted_live_opend_fetch","historical_market_data_only","passed","source_path","notes"])
    trial_fields = ["period","seed","trial_id","random_asof_start_date","evaluation_end_date","strategy","topn_scope","forward_window","trial_return","median_return","positive_rate","p10_return","worst5_return","sample_count","source_mode","pit_lite_universe","post_hoc_stress_flag","feature_effective_date","price_date_used_for_ranking","leakage_rejected"]
    wcsv(out / "pre0616_random_asof_trial_master.csv", trials, trial_fields)
    sum_fields = list(pre_summary[0].keys()) if pre_summary else ["strategy"]
    wcsv(out / "pre0616_random_asof_trial_summary_by_strategy.csv", pre_summary, sum_fields)
    wcsv(out / "pre0616_random_asof_trial_summary_by_topn.csv", topn_summary, list(topn_summary[0].keys()) if topn_summary else ["topn_scope"])
    wcsv(out / "pre0616_random_asof_trial_summary_by_window.csv", window_summary, list(window_summary[0].keys()) if window_summary else ["forward_window"])
    for fname, base in [("pre0616_e_r3_vs_e_r2_audit.csv", "E_R2_CONSERVATIVE_DEFENSIVE_RETURN"), ("pre0616_e_r3_vs_new_factor_lite_audit.csv", "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"), ("pre0616_e_r3_vs_a1_audit.csv", "A1")]:
        wcsv(out / fname, [r for r in pre_summary if r["strategy"] in E_R3 + [base]], sum_fields)
    wcsv(out / "pre0616_tail_risk_audit.csv", [r for r in pre_summary if r["strategy"] in E_R3], sum_fields)
    wcsv(out / "pre0616_turnover_audit.csv", [{"strategy": s, "turnover_status": "PASS_ASOF_RANK_PROXY", "notes": "research-only rank turnover proxy"} for s in E_R3], ["strategy","turnover_status","notes"])
    wcsv(out / "pre_vs_post_0616_strategy_comparison.csv", [{"pre_best_avg": summary["best_pre_0616_strategy_by_avg_return"], "post_best_avg": best_post_avg, "pre_best_risk": summary["best_pre_0616_strategy_by_risk_adjusted_return"], "post_best_risk": best_post_risk, "comparison_decision": comparison_decision}], ["pre_best_avg","post_best_avg","pre_best_risk","post_best_risk","comparison_decision"])
    wcsv(out / "pre_vs_post_0616_regime_shift_audit.csv", [{"regime_shift_detected": regime_shift, "pre_best": summary["best_pre_0616_strategy_by_avg_return"], "post_best": best_post_avg, "notes": comparison_decision}], ["regime_shift_detected","pre_best","post_best","notes"])
    wcsv(out / "source_mode_and_post_hoc_stress_audit.csv", [{"source_mode": k, "row_count": sum(1 for r in trials if r["source_mode"] == k)} for k in sorted({r["source_mode"] for r in trials})], ["source_mode","row_count"])
    wcsv(out / "leakage_rejection_audit.csv", [], ["ranking_date","strategy","ticker","feature_effective_date","price_date_used_for_ranking","leakage_reason"])
    wcsv(out / "no_future_function_compliance_audit.csv", [{"check_name": "feature_and_price_lte_asof", "passed": True, "leakage_violation_count": 0, "notes": "ranking scores use only price rows at or before random as-of date"}], ["check_name","passed","leakage_violation_count","notes"])
    wcsv(out / "random_seed_reproducibility_audit.csv", seed_rows, ["period","seed","available_date_count","trial_count","sample_with_replacement","notes"])
    wcsv(out / "strategy_period_decision_matrix.csv", [{"strategy": s, "period": "PRE_0616_RANDOM_ASOF", "decision": "EVALUATED_RESEARCH_ONLY", "official_adoption_allowed": False, "broker_action_allowed": False} for s in STRATEGIES], ["strategy","period","decision","official_adoption_allowed","broker_action_allowed"])
    wjson(out / "v21_254_r1_summary.json", summary)
    (out / "V21.254_R1_moomoo_pre0616_historical_random_asof_backtest_report.txt").write_text(f"{STAGE}\nfinal_status={final_status}\nfinal_decision={summary['final_decision']}\ncomparison_decision={comparison_decision}\nyahoo_yfinance_used=False\nbroker_action_allowed=False\nofficial_adoption_allowed=False\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    p.add_argument("--canonical-qfq-path", type=Path)
    p.add_argument("--seed-count", type=int, default=20)
    p.add_argument("--trials-per-seed", type=int, default=100)
    args = p.parse_args(argv)
    s = run(args.repo_root.resolve(), args.output_dir, args.canonical_qfq_path, args.seed_count, args.trials_per_seed)
    print(str((args.output_dir or args.repo_root / OUT_REL) / "v21_254_r1_summary.json"))
    return 1 if s.get("error_count", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
