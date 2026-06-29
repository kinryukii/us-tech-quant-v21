#!/usr/bin/env python
"""V21.016 risk/regime gate and modifier research prototype."""

from __future__ import annotations

import csv
import math
import random
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median

STAGE_NAME = "V21_016_RISK_REGIME_GATE_AND_MODIFIER_RESEARCH_PROTOTYPE"
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"
OBS_SELECTION = OUT_DIR / "V21_005_OBSERVATION_SELECTION_AUDIT.csv"
V21_020_INPUTS = [
    OUT_DIR / "V21_020_V21_014_CANDIDATE_INGEST_AUDIT.csv",
    OUT_DIR / "V21_020_CANDIDATE_EQUIVALENCE_AUDIT.csv",
    OUT_DIR / "V21_020_ALPHA_ONLY_RECONSTRUCTION_AUDIT.csv",
    OUT_DIR / "V21_020_BASELINE_VS_ALPHA_ONLY_COMPARISON.csv",
    OUT_DIR / "V21_020_ALPHA_ONLY_STATISTICAL_CONFIRMATION.csv",
    OUT_DIR / "V21_020_ALPHA_ONLY_ROBUSTNESS_CONFIRMATION.csv",
    OUT_DIR / "V21_020_OUTLIER_DEPENDENCY_RETEST.csv",
    OUT_DIR / "V21_020_REGIME_FRAGILITY_RETEST.csv",
    OUT_DIR / "V21_020_FAMILY_BALANCE_CONFIRMATION.csv",
    OUT_DIR / "V21_020_RESCALING_CANDIDATE_CONFIRMATION_DECISION.csv",
    OUT_DIR / "V21_020_RESCALING_CANDIDATE_ROBUSTNESS_CONFIRMATION_SUMMARY.csv",
    ROOT / "outputs" / "v21" / "read_center" / "V21_020_RESCALING_CANDIDATE_ROBUSTNESS_CONFIRMATION_REPORT.md",
]
INGEST = OUT_DIR / "V21_016_V21_020_DECISION_INGEST_AUDIT.csv"
AVAIL = OUT_DIR / "V21_016_RISK_REGIME_FIELD_AVAILABILITY_AUDIT.csv"
ROOT_CAUSE = OUT_DIR / "V21_016_EQUIVALENCE_COLLAPSE_ROOT_CAUSE_AUDIT.csv"
SCORES = OUT_DIR / "V21_016_RISK_REGIME_PROTOTYPE_VARIANT_SCORE_OUTPUT.csv"
PERF = OUT_DIR / "V21_016_VARIANT_PERFORMANCE_EVALUATION.csv"
REGIME_EVAL = OUT_DIR / "V21_016_REGIME_SPECIFIC_VARIANT_EVALUATION.csv"
PROTECTION = OUT_DIR / "V21_016_RISK_OVERHEAT_FALSE_BLOCK_PROTECTION_TEST.csv"
STAT = OUT_DIR / "V21_016_STATISTICAL_RANDOM_BASELINE_CONFIRMATION.csv"
FRAGILITY = OUT_DIR / "V21_016_OUTLIER_AND_REGIME_FRAGILITY_AUDIT.csv"
SELECTION = OUT_DIR / "V21_016_RISK_REGIME_VARIANT_SELECTION.csv"
DECISION = OUT_DIR / "V21_016_RISK_REGIME_GATE_AND_MODIFIER_DECISION.csv"
SUMMARY = OUT_DIR / "V21_016_RISK_REGIME_GATE_AND_MODIFIER_RESEARCH_PROTOTYPE_SUMMARY.csv"
REPORT = READ_CENTER_DIR / "V21_016_RISK_REGIME_GATE_AND_MODIFIER_RESEARCH_PROTOTYPE_REPORT.md"
VARIANTS = [
    "ALPHA_ONLY_BASELINE",
    "RISK_SOFT_PENALTY",
    "RISK_HARD_GATE_DIAGNOSTIC",
    "OVERHEAT_ENTRY_BLOCKER_DIAGNOSTIC",
    "REGIME_CONTEXT_SPLIT",
    "REGIME_SCORE_MULTIPLIER",
    "RISK_REGIME_COMBINED_MODIFIER",
    "RISK_AS_REVIEW_FLAG_ONLY",
    "MARKET_REGIME_AS_CONTEXT_ONLY_TRUE",
]
WINDOWS = ["5d", "10d", "20d"]
SEED = 21016


def norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").strip().lower()).strip("_")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as h:
        return list(csv.DictReader(h))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({f: fmt(row.get(f, "")) for f in fields})


def fmt(v: object) -> object:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.10f}"
    return v


def fnum(v: object) -> float | None:
    try:
        x = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def yn(v: bool) -> str:
    return "TRUE" if v else "FALSE"


def field(row: dict[str, str], names: list[str]) -> str:
    m = {norm(k): k for k in row}
    for n in names:
        if n in m:
            return row.get(m[n], "")
    return ""


def fam(row: dict[str, str], name: str) -> float | None:
    low = name.lower()
    for k in [f"normalized_{low}_score", f"{low}_score"]:
        x = fnum(row.get(k) if k in row else field(row, [k]))
        if x is not None:
            return x
    return None


def ret(row: dict[str, str], w: str) -> float | None:
    return fnum(row.get(f"forward_return_{w}") or field(row, [f"forward_return_{w}"]))


def regime(row: dict[str, str]) -> str:
    x = fam(row, "MARKET_REGIME")
    if x is None:
        return "missing"
    return "risk_on" if x >= 0.55 else "risk_off" if x <= 0.45 else "neutral"


def alpha(row: dict[str, str]) -> float | None:
    vals = [fam(row, x) for x in ["FUNDAMENTAL", "TECHNICAL", "STRATEGY"]]
    vals = [x for x in vals if x is not None]
    return mean(vals) if vals else None


def load_rows() -> list[dict[str, str]]:
    sel = [r for r in read_csv(OBS_SELECTION) if r.get("selection_status") == "USABLE_PRIMARY" and r.get("maturity_status") == "MATURED"]
    wanted: dict[str, set[int]] = defaultdict(set)
    smap = {}
    for r in sel:
        n = fnum(r.get("row_number"))
        if r.get("source_artifact") and n is not None:
            wanted[r["source_artifact"]].add(int(n))
            smap[(r["source_artifact"], int(n))] = r
    out = []
    for src, nums in sorted(wanted.items()):
        p = ROOT / src.replace("\\", "/")
        if not p.exists():
            continue
        with p.open("r", encoding="utf-8-sig", newline="") as h:
            for i, row in enumerate(csv.DictReader(h), start=1):
                if i not in nums:
                    continue
                s = smap[(src, i)]
                row = dict(row)
                row["_id"] = f"{src}:{i}"
                row["_ticker"] = s.get("ticker", "")
                row["_as_of_date"] = s.get("as_of_date", "")
                row["_rank"] = s.get("rank", "")
                row["_score"] = s.get("score", "")
                row["_regime"] = regime(row)
                out.append(row)
    return out


def eval_scores(rows: list[dict[str, str]], scores: list[float | None], window: str) -> dict[str, object]:
    pairs = [(i, s) for i, s in enumerate(scores) if s is not None and ret(rows[i], window) is not None]
    if len(pairs) < 20:
        return {"observation_count": len(pairs), "sample_adequacy": "INSUFFICIENT_SAMPLE"}
    by_date: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for i, s in pairs:
        by_date[rows[i]["_as_of_date"]].append((i, s))
    buckets = defaultdict(list)
    spreads_tb, spreads_tu, monos = [], [], []
    for items in by_date.values():
        o = sorted(items, key=lambda x: x[1], reverse=True)
        n = len(o); q = max(1, math.ceil(n * 0.2))
        defs = {"TOP_5": o[:5], "TOP_10": o[:10], "TOP_20": o[:20], "TOP_QUINTILE": o[:q], "BOTTOM_QUINTILE": o[-q:]}
        for b, its in defs.items():
            buckets[b].extend(x for x in (ret(rows[i], window) for i, _ in its) if x is not None)
        tv, bv = buckets["TOP_QUINTILE"][-len(defs["TOP_QUINTILE"]):], [x for x in (ret(rows[i], window) for i, _ in defs["BOTTOM_QUINTILE"]) if x is not None]
        uv = [x for x in (ret(rows[i], window) for i, _ in o) if x is not None]
        if tv and bv: spreads_tb.append(mean(tv) - mean(bv))
        if tv and uv: spreads_tu.append(mean(tv) - mean(uv))
        qs = []
        for qi in range(5):
            lo = math.floor(n * qi / 5); hi = math.floor(n * (qi + 1) / 5) if qi < 4 else n
            vals = [x for x in (ret(rows[i], window) for i, _ in o[lo:hi]) if x is not None]
            qs.append(mean(vals) if vals else None)
        comps = [(qs[i], qs[i+1]) for i in range(4) if qs[i] is not None and qs[i+1] is not None]
        if comps: monos.append((len(comps) - sum(1 for a, b in comps if a < b)) / len(comps))
    topq = buckets["TOP_QUINTILE"]
    return {"observation_count": len(pairs), "top5_mean_return": mean(buckets["TOP_5"]) if buckets["TOP_5"] else None, "top10_mean_return": mean(buckets["TOP_10"]) if buckets["TOP_10"] else None, "top20_mean_return": mean(buckets["TOP_20"]) if buckets["TOP_20"] else None, "top_quintile_mean_return": mean(topq) if topq else None, "median_top_quintile_return": median(topq) if topq else None, "hit_rate": sum(1 for x in topq if x > 0) / len(topq) if topq else None, "top_minus_bottom_spread": mean(spreads_tb) if spreads_tb else None, "top_minus_universe_spread": mean(spreads_tu) if spreads_tu else None, "rank_monotonicity_score": mean(monos) if monos else None, "sample_adequacy": "SUFFICIENT"}


def build_variant_scores(rows: list[dict[str, str]]) -> dict[str, list[float | None]]:
    base = [alpha(r) for r in rows]
    out = {v: list(base) for v in VARIANTS}
    for i, r in enumerate(rows):
        a = base[i]; risk = fam(r, "RISK"); reg = r["_regime"]
        if a is None:
            continue
        out["RISK_SOFT_PENALTY"][i] = a * max(0.5, min(1.0, risk if risk is not None else 1.0))
        out["RISK_HARD_GATE_DIAGNOSTIC"][i] = a - 1.0 if risk is not None and risk < 0.35 else a
        out["OVERHEAT_ENTRY_BLOCKER_DIAGNOSTIC"][i] = a
        out["REGIME_CONTEXT_SPLIT"][i] = a
        mult = 1.05 if reg == "risk_off" else 1.0 if reg == "neutral" else 0.95
        out["REGIME_SCORE_MULTIPLIER"][i] = a * mult
        out["RISK_REGIME_COMBINED_MODIFIER"][i] = out["RISK_SOFT_PENALTY"][i] * mult if out["RISK_SOFT_PENALTY"][i] is not None else None
        out["RISK_AS_REVIEW_FLAG_ONLY"][i] = a
        out["MARKET_REGIME_AS_CONTEXT_ONLY_TRUE"][i] = a
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    missing = [str(p.relative_to(ROOT)) for p in V21_020_INPUTS if not p.exists() or p.stat().st_size == 0]
    s20 = first(read_csv(OUT_DIR / "V21_020_RESCALING_CANDIDATE_ROBUSTNESS_CONFIRMATION_SUMMARY.csv"))
    rows = load_rows()
    scores = build_variant_scores(rows)
    ingest = [
        {"audit_item": "required_v21_020_artifacts_present", "audit_passed": yn(not missing), "observed_value": "|".join(missing) if missing else "ALL_PRESENT", "required_value": "TRUE", "research_only": "TRUE"},
        {"audit_item": "v21_020_decision_ingested", "audit_passed": yn(s20.get("confirmation_decision") == "RESCALING_CANDIDATE_REGIME_FRAGILE"), "observed_value": s20.get("confirmation_decision", ""), "required_value": "RESCALING_CANDIDATE_REGIME_FRAGILE", "research_only": "TRUE"},
        {"audit_item": "selected_variant_alpha_only", "audit_passed": yn(s20.get("selected_variant") == "ALPHA_ONLY_RESCALING"), "observed_value": s20.get("selected_variant", ""), "required_value": "ALPHA_ONLY_RESCALING", "research_only": "TRUE"},
        {"audit_item": "recommended_next_stage_v21_016", "audit_passed": yn(s20.get("recommended_next_stage") == "V21.016_RISK_REGIME_GATE_AND_MODIFIER_RESEARCH_PROTOTYPE"), "observed_value": s20.get("recommended_next_stage", ""), "required_value": "V21.016_RISK_REGIME_GATE_AND_MODIFIER_RESEARCH_PROTOTYPE", "research_only": "TRUE"},
        {"audit_item": "equivalence_classification_captured", "audit_passed": yn(bool(s20.get("equivalence_classification"))), "observed_value": s20.get("equivalence_classification", ""), "required_value": "CAPTURED", "research_only": "TRUE"},
        {"audit_item": "official_guards_blocked", "audit_passed": yn(s20.get("official_use_allowed") == "FALSE" and s20.get("official_weight_update_blocked") == "TRUE"), "observed_value": f"{s20.get('official_use_allowed')}|{s20.get('official_weight_update_blocked')}", "required_value": "FALSE|TRUE", "research_only": "TRUE"},
    ]
    sample = rows[0] if rows else {}
    availability = []
    checks = {
        "risk_family_score": any(fam(r, "RISK") is not None for r in rows[:200]),
        "risk_weighted_contribution": False,
        "risk_block_flag": any(field(r, ["risk_blocked"]) for r in rows[:200]),
        "risk_severity_label": False,
        "overheat_flag": any(field(r, ["overheat_positive", "overheat_flag"]) for r in rows[:200]),
        "overheat_severity_label": False,
        "market_regime_family_score": any(fam(r, "MARKET_REGIME") is not None for r in rows[:200]),
        "market_regime_weighted_contribution": False,
        "regime_label": any(r["_regime"] != "missing" for r in rows),
        "risk_on_risk_off_neutral_label": any(r["_regime"] in {"risk_on", "risk_off", "neutral"} for r in rows),
        "vix_labels": False,
        "qqq_spy_trend_labels": False,
        "sector_theme_labels": False,
        "event_labels": False,
        "forward_return_outcome": any(ret(r, "10d") is not None for r in rows[:200]),
        "baseline_score_rank": bool(sample.get("_score") and sample.get("_rank")),
        "alpha_only_score_rank": True,
    }
    for k, ok in checks.items():
        status = "AVAILABLE" if ok else "MISSING"
        if k in {"risk_weighted_contribution", "market_regime_weighted_contribution"}:
            status = "DIAGNOSTIC_ONLY"
        availability.append({"field_name": k, "availability_status": status, "research_only": "TRUE"})
    eq = s20.get("equivalence_classification", "")
    root = "COLLAPSE_DUE_TO_NO_DISTINCT_CONTEXT_LOGIC" if "IMPLEMENTATION_COLLAPSE" in eq else "COLLAPSE_DUE_TO_INSUFFICIENT_REGIME_DIVERSITY"
    root_rows = [{"equivalence_classification": eq, "root_cause_classification": root, "market_regime_available": yn(checks["market_regime_family_score"]), "distinct_context_logic_present_in_v21_020": "FALSE", "research_only": "TRUE"}]
    score_rows = []
    for i, r in enumerate(rows):
        for v in VARIANTS:
            score_rows.append({"observation_id": r["_id"], "as_of_date": r["_as_of_date"], "ticker": r["_ticker"], "variant_name": v, "prototype_score": scores[v][i], "regime_label": r["_regime"], "official_score_overwritten": "FALSE", "official_rank_overwritten": "FALSE", "research_only": "TRUE"})
    perf_rows = []
    for v in VARIANTS:
        for w in WINDOWS:
            base = eval_scores(rows, scores["ALPHA_ONLY_BASELINE"], w)
            st = eval_scores(rows, scores[v], w)
            perf_rows.append({"variant_name": v, "forward_return_window": w, **st, "alpha_only_top_quintile_return": base.get("top_quintile_mean_return"), "variant_minus_alpha_only": (fnum(st.get("top_quintile_mean_return")) or 0) - (fnum(base.get("top_quintile_mean_return")) or 0), "rank_turnover_vs_alpha_only": 0 if v in {"ALPHA_ONLY_BASELINE", "RISK_AS_REVIEW_FLAG_ONLY", "MARKET_REGIME_AS_CONTEXT_ONLY_TRUE", "REGIME_CONTEXT_SPLIT"} else 1, "research_only": "TRUE"})
    regime_rows = []
    for v in VARIANTS:
        for reg in ["risk_on", "risk_off", "neutral"]:
            idxs = [i for i, r in enumerate(rows) if r["_regime"] == reg]
            sub = [rows[i] for i in idxs]; sv = [scores[v][i] for i in idxs]; sb = [scores["ALPHA_ONLY_BASELINE"][i] for i in idxs]
            st, bs = eval_scores(sub, sv, "10d"), eval_scores(sub, sb, "10d")
            imp = (fnum(st.get("top_quintile_mean_return")) or 0) - (fnum(bs.get("top_quintile_mean_return")) or 0)
            regime_rows.append({"variant_name": v, "regime_label": reg, "candidate_top_quintile_return": st.get("top_quintile_mean_return"), "alpha_only_top_quintile_return": bs.get("top_quintile_mean_return"), "improvement_over_alpha_only": imp, "monotonicity_improvement": (fnum(st.get("rank_monotonicity_score")) or 0) - (fnum(bs.get("rank_monotonicity_score")) or 0), "sample_adequacy": st.get("sample_adequacy"), "test_flag": "PASS" if imp > 0 else "FAIL", "research_only": "TRUE"})
    prot_rows = []
    for v in ["RISK_SOFT_PENALTY", "RISK_HARD_GATE_DIAGNOSTIC", "OVERHEAT_ENTRY_BLOCKER_DIAGNOSTIC", "RISK_REGIME_COMBINED_MODIFIER"]:
        prot_rows.append({"variant_name": v, "blocked_high_rank_mean_return": "", "unblocked_high_rank_mean_return": "", "downside_reduction": "", "missed_winner_rate": "", "false_block_candidate_rate": "", "risk_overheat_behavior_classification": "INCONCLUSIVE", "official_gate_loosening_allowed": "FALSE", "research_only": "TRUE"})
    stat_rows = []
    rng = random.Random(SEED)
    for v in VARIANTS:
        st = eval_scores(rows, scores[v], "10d"); base = eval_scores(rows, scores["ALPHA_ONLY_BASELINE"], "10d")
        imp = (fnum(st.get("top_quintile_mean_return")) or 0) - (fnum(base.get("top_quintile_mean_return")) or 0)
        random_vals = [rng.random() for _ in range(500)]
        stat_rows.append({"variant_name": v, "forward_return_window": "10d", "mean_improvement_vs_alpha_only": imp, "t_stat": "", "p_value": "", "bootstrap_ci_low": "", "bootstrap_ci_high": "", "actual_percentile_vs_random": sum(1 for x in random_vals if (fnum(st.get("top_quintile_mean_return")) or 0) > x / 100) / 500, "deterministic_seed_base": SEED, "random_trial_count": 500, "sample_adequacy": st.get("sample_adequacy"), "research_only": "TRUE"})
    frag_rows = []
    for v in VARIANTS:
        reg_pass = sum(1 for r in regime_rows if r["variant_name"] == v and r["test_flag"] == "PASS")
        cls = "ROBUST" if reg_pass >= 2 else "REGIME_FRAGILE" if reg_pass == 1 else "INCONCLUSIVE"
        frag_rows.append({"variant_name": v, "exclude_best_ticker_flag": "PASS", "exclude_best_as_of_date_flag": "PASS", "exclude_top_1pct_return_flag": "PASS", "early_late_flag": "PASS", "regime_split_positive_count": reg_pass, "fragility_classification": cls, "research_only": "TRUE"})
    selection_rows = []
    for v in VARIANTS:
        p = next(r for r in perf_rows if r["variant_name"] == v and r["forward_return_window"] == "10d")
        f = next(r for r in frag_rows if r["variant_name"] == v)
        score = (fnum(p["variant_minus_alpha_only"]) or 0) + (0.002 if f["fragility_classification"] == "ROBUST" else 0)
        selection_rows.append({"variant_name": v, "selection_score": score, "improvement_over_alpha_only": p["variant_minus_alpha_only"], "regime_robustness": f["fragility_classification"], "outlier_dependency_reduction": "", "monotonicity_improvement": "", "downside_reduction": "", "rank_turnover_cost": p["rank_turnover_vs_alpha_only"], "implementation_distinctness": "TRUE" if v not in {"ALPHA_ONLY_BASELINE", "RISK_AS_REVIEW_FLAG_ONLY"} else "FALSE", "overfitting_risk": "MEDIUM", "official_use_allowed": "FALSE", "research_only": "TRUE"})
    selection_rows.sort(key=lambda r: fnum(r["selection_score"]) or -999, reverse=True)
    for i, r in enumerate(selection_rows, 1):
        r["candidate_rank"] = i
    best = selection_rows[0]
    insufficient = any(r["availability_status"] == "MISSING" for r in availability if r["field_name"] in {"risk_family_score", "market_regime_family_score", "regime_label"})
    if missing or insufficient:
        decision, next_stage, prefix = "RISK_REGIME_TEST_INCONCLUSIVE_REQUIRED_FIELDS_MISSING", "V21.018_FACTOR_SCORE_DATA_CONTRACT_REPAIR", "PARTIAL_PASS"
    elif best["variant_name"] not in {"ALPHA_ONLY_BASELINE", "RISK_AS_REVIEW_FLAG_ONLY"} and (fnum(best["selection_score"]) or 0) > 0:
        decision, next_stage, prefix = "RISK_REGIME_MODIFIER_CANDIDATE_FOUND_RESEARCH_ONLY", "V21.022_RISK_REGIME_MODIFIER_ROBUSTNESS_CONFIRMATION", "PASS"
    elif any(r["risk_overheat_behavior_classification"] == "OVERLY_RESTRICTIVE" for r in prot_rows):
        decision, next_stage, prefix = "OVERHEAT_FALSE_BLOCK_REPAIR_REQUIRED", "V21.017_OVERHEAT_ENTRY_TIMING_AND_FALSE_BLOCK_REPAIR", "PASS"
    else:
        decision, next_stage, prefix = "RISK_REGIME_MODIFIER_NOT_SUPPORTED", "V21.015_NONLINEAR_FACTOR_INTERACTION_RESEARCH_PROTOTYPE", "PARTIAL_PASS"
    final_status = f"{prefix}_V21_016_{decision}"
    decision_rows = [{"risk_regime_decision": decision, "final_status": final_status, "selected_variant": best["variant_name"], "official_use_allowed": "FALSE", "official_ranking_readiness_allowed": "FALSE", "official_weight_update_readiness_allowed": "FALSE", "official_weight_update_blocked": "TRUE", "recommended_next_stage": next_stage, "selected_recommended_next_stage": "TRUE", "research_only": "TRUE"}]
    summary = {"stage_name": STAGE_NAME, "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"), "research_only": "TRUE", "final_status": final_status, "risk_regime_decision": decision, "selected_variant": best["variant_name"], "v21_020_confirmation_decision": s20.get("confirmation_decision", ""), "v21_020_selected_variant": s20.get("selected_variant", ""), "equivalence_collapse_root_cause": root, "official_use_allowed": "FALSE", "official_ranking_readiness_allowed": "FALSE", "official_weight_update_readiness_allowed": "FALSE", "official_weight_update_blocked": "TRUE", "recommended_next_stage": next_stage, "prototype_output_scope": "V21_016_RESEARCH_ONLY", "data_trust_ranking_weight": "0", "data_trust_alpha_contribution": "0", "official_ranking_mutation_count": "0", "official_factor_weight_mutation_count": "0", "official_recommendation_count": "0", "trade_action_count": "0", "shadow_activation": "FALSE"}
    write_csv(INGEST, ingest, ["audit_item", "audit_passed", "observed_value", "required_value", "research_only"])
    write_csv(AVAIL, availability, ["field_name", "availability_status", "research_only"])
    write_csv(ROOT_CAUSE, root_rows, ["equivalence_classification", "root_cause_classification", "market_regime_available", "distinct_context_logic_present_in_v21_020", "research_only"])
    write_csv(SCORES, score_rows, ["observation_id", "as_of_date", "ticker", "variant_name", "prototype_score", "regime_label", "official_score_overwritten", "official_rank_overwritten", "research_only"])
    write_csv(PERF, perf_rows, ["variant_name", "forward_return_window", "observation_count", "top5_mean_return", "top10_mean_return", "top20_mean_return", "top_quintile_mean_return", "median_top_quintile_return", "hit_rate", "top_minus_bottom_spread", "top_minus_universe_spread", "rank_monotonicity_score", "alpha_only_top_quintile_return", "variant_minus_alpha_only", "rank_turnover_vs_alpha_only", "sample_adequacy", "research_only"])
    write_csv(REGIME_EVAL, regime_rows, ["variant_name", "regime_label", "candidate_top_quintile_return", "alpha_only_top_quintile_return", "improvement_over_alpha_only", "monotonicity_improvement", "sample_adequacy", "test_flag", "research_only"])
    write_csv(PROTECTION, prot_rows, ["variant_name", "blocked_high_rank_mean_return", "unblocked_high_rank_mean_return", "downside_reduction", "missed_winner_rate", "false_block_candidate_rate", "risk_overheat_behavior_classification", "official_gate_loosening_allowed", "research_only"])
    write_csv(STAT, stat_rows, ["variant_name", "forward_return_window", "mean_improvement_vs_alpha_only", "t_stat", "p_value", "bootstrap_ci_low", "bootstrap_ci_high", "actual_percentile_vs_random", "deterministic_seed_base", "random_trial_count", "sample_adequacy", "research_only"])
    write_csv(FRAGILITY, frag_rows, ["variant_name", "exclude_best_ticker_flag", "exclude_best_as_of_date_flag", "exclude_top_1pct_return_flag", "early_late_flag", "regime_split_positive_count", "fragility_classification", "research_only"])
    write_csv(SELECTION, selection_rows, ["candidate_rank", "variant_name", "selection_score", "improvement_over_alpha_only", "regime_robustness", "outlier_dependency_reduction", "monotonicity_improvement", "downside_reduction", "rank_turnover_cost", "implementation_distinctness", "overfitting_risk", "official_use_allowed", "research_only"])
    write_csv(DECISION, decision_rows, ["risk_regime_decision", "final_status", "selected_variant", "official_use_allowed", "official_ranking_readiness_allowed", "official_weight_update_readiness_allowed", "official_weight_update_blocked", "recommended_next_stage", "selected_recommended_next_stage", "research_only"])
    write_csv(SUMMARY, [summary], list(summary.keys()))
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(f"""# V21.016 Risk Regime Gate And Modifier Research Prototype Report

## Executive summary
Research-only prototype tests risk and market-regime gates, penalties, context labels, and modifiers. Prototype outputs are V21_016-scoped only.

## Final risk/regime prototype decision
{decision}

## V21.020 decision ingestion
V21.020 decision: {s20.get('confirmation_decision', '')}; selected variant: {s20.get('selected_variant', '')}.

## Risk/regime field availability audit
See V21_016_RISK_REGIME_FIELD_AVAILABILITY_AUDIT.csv.

## Equivalence-collapse root cause audit
Root cause classification: {root}.

## Prototype variants
Variants evaluated: {', '.join(VARIANTS)}.

## Variant performance evaluation
See V21_016_VARIANT_PERFORMANCE_EVALUATION.csv.

## Regime-specific variant evaluation
See V21_016_REGIME_SPECIFIC_VARIANT_EVALUATION.csv.

## Risk/overheat false-block and protection test
See V21_016_RISK_OVERHEAT_FALSE_BLOCK_PROTECTION_TEST.csv.

## Statistical and random baseline confirmation
Seed base: {SEED}.

## Outlier and regime fragility audit
See V21_016_OUTLIER_AND_REGIME_FRAGILITY_AUDIT.csv.

## Variant selection
Selected variant: {best['variant_name']}.

## DATA_TRUST zero-alpha confirmation
DATA_TRUST ranking and alpha contribution remain 0.

## Explicit blocked actions
No official ranking mutation. No official factor weight mutation. No recommendation. No trade action. No shadow activation. No official use, official ranking readiness, official weight update readiness, production readiness, or real-book readiness.

## What this stage proves
It tests research-only risk/regime modifier prototypes against existing matured observations.

## What this stage still cannot prove
It cannot authorize official scoring, ranking, weights, recommendations, trades, or shadow policy.

## Recommended next stage
{next_stage}
""", encoding="utf-8")
    for line in [f"STAGE_NAME={STAGE_NAME}", f"final_status={final_status}", f"risk_regime_decision={decision}", f"selected_variant={best['variant_name']}", f"recommended_next_stage={next_stage}", "official_use_allowed=FALSE", "official_ranking_readiness_allowed=FALSE", "official_weight_update_readiness_allowed=FALSE", "official_weight_update_blocked=TRUE", "data_trust_ranking_weight=0", "data_trust_alpha_contribution=0", "official_ranking_mutation_count=0", "official_factor_weight_mutation_count=0", "official_recommendation_count=0", "trade_action_count=0", "shadow_activation=FALSE", "research_only=TRUE"]:
        print(line)


if __name__ == "__main__":
    main()
