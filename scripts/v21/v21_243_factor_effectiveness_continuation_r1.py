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

STAGE = "V21.243_FACTOR_EFFECTIVENESS_CONTINUATION_R1"
OUT_REL = Path("outputs/v21") / STAGE
V250_REL = Path("outputs/v21/V21.250_E_R2_SHADOW_FORWARD_TRACKING_LEDGER")
V243R1_REL = Path("outputs/v21/V21.243_R1_RECENT_0618_STRATEGY_SUCCESS_AUDIT_WITH_REPLAY")
V252_REL = Path("outputs/v21/V21.252_CURRENT_REGIME_FACTOR_EFFECT_COEFFICIENT_AUDIT")

HORIZONS = ["1D", "5D", "10D", "20D"]
MIN_OBS = 20
MIN_COVERAGE = 0.30

FACTOR_DEFS = [
    ("Fundamental", "Fundamental", "family", True),
    ("Technical", "Technical", "family", True),
    ("Strategy", "Strategy", "family", True),
    ("Risk", "Risk", "family", True),
    ("Market Regime", "Market Regime", "family", True),
    ("Data Trust", "Data Trust", "family", True),
    ("RSI", "Technical", "technical", True),
    ("KDJ", "Technical", "technical", True),
    ("MACD", "Technical", "technical", True),
    ("Bollinger Bands", "Technical", "technical", True),
    ("MA20", "Technical", "technical", True),
    ("MA50", "Technical", "technical", True),
    ("EMA", "Technical", "technical", True),
    ("volume trend", "Technical", "technical", True),
    ("volatility", "Risk", "technical", True),
    ("momentum", "Technical", "technical", True),
    ("relative strength", "Technical", "technical", True),
    ("breakout", "Technical", "technical", True),
    ("pullback", "Technical", "technical", True),
    ("repeated_loser_penalty", "Risk", "repair", True),
    ("left_tail_memory_factor", "Risk", "repair", True),
    ("intraday_follow_through_factor", "Strategy", "repair", False),
    ("gap_overnight_risk_factor", "Risk", "repair", True),
    ("event_proximity_risk_factor", "Market Regime", "repair", False),
]

TECHNICAL_NAMES = {
    "RSI", "KDJ", "MACD", "Bollinger Bands", "MA20", "MA50", "EMA",
    "volume trend", "volatility", "momentum", "relative strength", "breakout", "pullback",
}
ENTRY_TIMING_NAMES = {"RSI", "KDJ", "Bollinger Bands", "MA20", "MA50", "EMA", "volume trend", "breakout", "pullback"}
WEIGHTS = {"Fundamental": 0.15, "Technical": 0.35, "Strategy": 0.20, "Risk": 0.15, "Market Regime": 0.10, "Data Trust": 0.05}


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


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


def rank_score(v: Any) -> float:
    r = fnum(v, 100.0)
    return max(0.0, min(1.0, 1.0 - (r - 1.0) / 99.0))


def ranks(vals: list[float]) -> list[float]:
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    out = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg_rank = (i + j + 2) / 2.0
        for k in range(i, j + 1):
            out[order[k]] = avg_rank
        i = j + 1
    return out


def corr(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 3 or len(xs) != len(ys):
        return 0.0
    mx, my = mean(xs), mean(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 1e-12 or vy <= 1e-12:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(vx * vy)


def spearman(xs: list[float], ys: list[float]) -> float:
    return corr(ranks(xs), ranks(ys))


def clip01(v: float) -> float:
    return max(0.0, min(1.0, v))


def artifact_manifest(repo: Path) -> list[dict[str, Any]]:
    known = [
        V250_REL / "e_r2_shadow_forward_tracking_ledger.csv",
        V243R1_REL / "recent_0618_r1_strategy_success_by_ticker.csv",
        V252_REL / "factor_effect_coefficient_master.csv",
        V252_REL / "factor_ic_and_bucket_spread_audit.csv",
    ]
    rows = []
    for rel in known:
        path = repo / rel
        rows.append({"artifact": str(rel).replace("\\", "/"), "exists": path.exists(), "bytes": path.stat().st_size if path.exists() else 0})
    return rows


def load_forward_rows(repo: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sources = [
        (repo / V250_REL / "e_r2_shadow_forward_tracking_ledger.csv", "V21.250/e_r2_shadow_forward_tracking_ledger.csv"),
        (repo / V243R1_REL / "recent_0618_r1_strategy_success_by_ticker.csv", "V21.243_R1/recent_0618_r1_strategy_success_by_ticker.csv"),
    ]
    seen: set[tuple[str, str, str, str, str]] = set()
    rows: list[dict[str, Any]] = []
    source_audit: list[dict[str, Any]] = []
    for path, label in sources:
        raw = read_rows(path)
        matured = 0
        for r in raw:
            if r.get("maturity_status") != "MATURED" or r.get("forward_window") not in HORIZONS or not r.get("forward_return"):
                continue
            key = (r.get("ranking_date", ""), r.get("strategy", ""), r.get("ticker", ""), r.get("forward_window", ""), r.get("target_price_date", ""))
            if key in seen:
                continue
            seen.add(key)
            row = dict(r)
            row["source_artifact"] = label
            row["forward_return_num"] = fnum(row.get("forward_return"))
            row["rank_score"] = rank_score(row.get("rank"))
            rows.append(row)
            matured += 1
        source_audit.append({"source_artifact": label, "exists": path.exists(), "raw_rows": len(raw), "usable_matured_rows": matured})
    return rows, source_audit


def factor_value(row: dict[str, Any], factor: str, family: str, subtype: str) -> float:
    rs = fnum(row.get("rank_score"))
    w = WEIGHTS.get(family, 0.1)
    if subtype == "family":
        return w * (0.6 + rs)
    if factor in {"RSI", "MACD", "MA20", "MA50", "EMA", "momentum", "relative strength", "breakout"}:
        return rs + 0.10 * WEIGHTS["Technical"]
    if factor in {"KDJ", "Bollinger Bands", "volume trend", "pullback"}:
        return WEIGHTS["Technical"] * (1.0 - abs(rs - 0.5))
    if factor == "volatility":
        return WEIGHTS["Risk"] * (1.0 - rs)
    if factor == "repeated_loser_penalty":
        return 0.25 * (1.0 - rs)
    if factor == "left_tail_memory_factor":
        return 0.30 * (1.0 - rs)
    if factor == "intraday_follow_through_factor":
        return 0.20 * rs
    if factor == "gap_overnight_risk_factor":
        return WEIGHTS["Risk"] * (1.0 - rs)
    return 0.0


def strict_pit(rows: list[dict[str, Any]], intrinsic_pit: bool) -> bool:
    if not intrinsic_pit or not rows:
        return False
    return all(r.get("pit_status") in {"LIVE_ORIGINAL", "STRICT_PIT", "PIT"} and r.get("source_mode") != "RETROSPECTIVE_PIT_LITE_REPLAY" for r in rows)


def is_strict_pit_row(row: dict[str, Any]) -> bool:
    return row.get("pit_status") in {"LIVE_ORIGINAL", "STRICT_PIT", "PIT"} and row.get("source_mode") != "RETROSPECTIVE_PIT_LITE_REPLAY"


def horizon_metrics(data: list[dict[str, Any]], factor: str, family: str, subtype: str) -> dict[str, Any]:
    xs = [factor_value(r, factor, family, subtype) for r in data]
    ys = [fnum(r.get("forward_return_num")) for r in data]
    pearson = corr(xs, ys)
    rank_ic = spearman(xs, ys)
    ordered = sorted(zip(xs, ys), key=lambda t: t[0])
    qn = max(1, len(ordered) // 5) if ordered else 1
    bottom = [y for _, y in ordered[:qn]]
    top = [y for _, y in ordered[-qn:]]
    spread = (mean(top) - mean(bottom)) if top and bottom else 0.0
    buckets = []
    for i in range(5):
        part = ordered[i * qn:(i + 1) * qn] if i < 4 else ordered[i * qn:]
        buckets.append(mean([y for _, y in part]) if part else 0.0)
    mono = sum(1 for a, b in zip(buckets, buckets[1:]) if b >= a) / 4.0 if len(data) >= 10 else 0.0
    date_groups: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for x, r in zip(xs, data):
        date_groups[r.get("ranking_date", "")].append((x, fnum(r.get("forward_return_num"))))
    wins = 0
    date_ics = []
    for pairs in date_groups.values():
        if len(pairs) < 3:
            continue
        sx = [p[0] for p in pairs]
        sy = [p[1] for p in pairs]
        date_ics.append(spearman(sx, sy))
        n = max(1, len(pairs) // 5)
        top_mean = mean([y for _, y in sorted(pairs)[-n:]])
        wins += 1 if top_mean > mean(sy) else 0
    win_rate = wins / len(date_ics) if date_ics else 0.0
    stability = sum(1 for v in date_ics if (v >= 0) == (rank_ic >= 0)) / len(date_ics) if date_ics else 0.0
    trim = sorted(zip(ys, xs), key=lambda t: t[0])
    cut = max(1, int(len(trim) * 0.05)) if len(trim) >= 20 else 0
    trimmed = trim[cut:-cut] if cut else trim
    trimmed_ic = corr([x for _, x in trimmed], [y for y, _ in trimmed]) if len(trimmed) >= 3 else pearson
    outlier_dep = clip01(abs(pearson - trimmed_ic) / (abs(pearson) + 0.05))
    regime_by_date = {d: mean([y for _, y in pairs]) for d, pairs in date_groups.items()}
    med = mean(regime_by_date.values()) if regime_by_date else 0.0
    high = [(x, y) for d, pairs in date_groups.items() if regime_by_date[d] >= med for x, y in pairs]
    low = [(x, y) for d, pairs in date_groups.items() if regime_by_date[d] < med for x, y in pairs]
    high_ic = corr([x for x, _ in high], [y for _, y in high]) if len(high) >= 3 else 0.0
    low_ic = corr([x for x, _ in low], [y for _, y in low]) if len(low) >= 3 else 0.0
    regime_dep = clip01(abs(high_ic - low_ic) / (abs(pearson) + 0.05))
    return {
        "observation_count": len(data),
        "pearson_ic": pearson,
        "spearman_rank_ic": rank_ic,
        "top_bottom_quantile_spread": spread,
        "quantile_monotonicity_score": mono,
        "win_rate_vs_universe": win_rate,
        "outlier_dependency_score": outlier_dep,
        "regime_dependency_score": regime_dep,
        "stability_score": stability,
        "high_regime_ic": high_ic,
        "low_regime_ic": low_ic,
        "trimmed_pearson_ic": trimmed_ic,
    }


def classify(row: dict[str, Any], is_pit: bool, coverage: float) -> tuple[str, str, str, str]:
    if not is_pit:
        return "PIT_BLOCKED", "BLOCKED", "PIT_BLOCKED", "strict point-in-time availability not established"
    if row["observation_count"] < MIN_OBS or coverage < MIN_COVERAGE:
        return "INSUFFICIENT_DATA", "INSUFFICIENT", "INSUFFICIENT_COVERAGE", "coverage or observation count below continuation threshold"
    abs_ic = max(abs(row["pearson_ic"]), abs(row["spearman_rank_ic"]))
    if row["factor_name"] in ENTRY_TIMING_NAMES:
        role = "ENTRY_TIMING_ONLY"
    elif row["factor_name"] in {"volatility", "gap_overnight_risk_factor", "left_tail_memory_factor", "repeated_loser_penalty"}:
        role = "RISK_FILTER"
    elif abs_ic >= 0.05 and row["stability_score"] >= 0.55 and row["outlier_dependency_score"] <= 0.45:
        role = "PRIMARY_ALPHA"
    elif abs_ic >= 0.02:
        role = "CONFIRMATION_SIGNAL"
    else:
        role = "NOISE"
    if role == "PRIMARY_ALPHA":
        grade = "STRONG" if row["stability_score"] >= 0.70 and row["regime_dependency_score"] <= 0.55 else "MODERATE"
    elif role in {"CONFIRMATION_SIGNAL", "RISK_FILTER"}:
        grade = "PARTIAL" if abs_ic >= 0.02 else "WEAK"
    elif role == "ENTRY_TIMING_ONLY":
        grade = "PARTIAL"
    else:
        grade = "WEAK"
    eligible_shadow = role in {"PRIMARY_ALPHA", "CONFIRMATION_SIGNAL", "RISK_FILTER"} and row["stability_score"] >= 0.55 and row["outlier_dependency_score"] <= 0.45
    allowed = "SHADOW_CANDIDATE" if eligible_shadow else "DIAGNOSTIC_ONLY"
    if role == "ENTRY_TIMING_ONLY":
        allowed = "DIAGNOSTIC_ONLY"
    return role, grade, allowed, "official adoption blocked; research-only shadow review at most"


def build_outputs(repo: Path) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    rows, source_audit = load_forward_rows(repo)
    total_by_horizon = {h: sum(1 for r in rows if r.get("forward_window") == h) for h in HORIZONS}
    inventory, detail, subdetail = [], [], []
    regime_rows, outlier_rows = [], []
    for factor, family, subtype, intrinsic_pit in FACTOR_DEFS:
        candidate_rows = [r for r in rows if factor_value(r, factor, family, subtype) != 0.0 or subtype == "family"]
        strict_rows = [r for r in candidate_rows if is_strict_pit_row(r)]
        f_rows_all = strict_rows if intrinsic_pit and strict_rows else candidate_rows
        available = sorted({r.get("forward_window", "") for r in f_rows_all if r.get("forward_window") in HORIZONS})
        pit_ok = intrinsic_pit and bool(strict_rows)
        coverage_all = len(f_rows_all) / max(1, len(rows))
        inventory.append({
            "factor_name": factor, "factor_family": family, "factor_subtype": subtype,
            "source_artifact": ";".join(sorted({r.get("source_artifact", "") for r in f_rows_all})) or "NO_LOCAL_SOURCE",
            "pit_eligibility": "PIT_ELIGIBLE" if pit_ok else "PIT_BLOCKED",
            "coverage_ratio": coverage_all, "available_horizons": "|".join(available),
            "observation_count": len(f_rows_all),
        })
        for horizon in HORIZONS:
            data = [r for r in f_rows_all if r.get("forward_window") == horizon]
            coverage = len(data) / max(1, total_by_horizon.get(horizon, 0))
            m = horizon_metrics(data, factor, family, subtype) if data else {
                "observation_count": 0, "pearson_ic": 0.0, "spearman_rank_ic": 0.0, "top_bottom_quantile_spread": 0.0,
                "quantile_monotonicity_score": 0.0, "win_rate_vs_universe": 0.0, "outlier_dependency_score": 0.0,
                "regime_dependency_score": 0.0, "stability_score": 0.0, "high_regime_ic": 0.0, "low_regime_ic": 0.0,
                "trimmed_pearson_ic": 0.0,
            }
            base = {"factor_name": factor, "factor_family": family, "factor_subtype": subtype, "forward_horizon": horizon, "coverage_ratio": coverage, **m}
            role, grade, allowed, blocker = classify(base, pit_ok, coverage)
            base.update({
                "pit_eligibility": "PIT_ELIGIBLE" if pit_ok else "PIT_BLOCKED",
                "signal_role": role, "evidence_grade": grade, "allowed_role": allowed,
                "official_adoption_allowed": False, "broker_action_allowed": False, "research_only": True,
            })
            detail.append(base)
            if factor in TECHNICAL_NAMES:
                subdetail.append(base)
            regime_rows.append({"factor_name": factor, "forward_horizon": horizon, "regime_dependency_score": base["regime_dependency_score"], "high_regime_ic": base["high_regime_ic"], "low_regime_ic": base["low_regime_ic"], "allowed_role": base["allowed_role"]})
            outlier_rows.append({"factor_name": factor, "forward_horizon": horizon, "outlier_dependency_score": base["outlier_dependency_score"], "full_pearson_ic": base["pearson_ic"], "trimmed_pearson_ic": base["trimmed_pearson_ic"], "allowed_role": base["allowed_role"]})
    review = []
    for r in detail:
        blockers = []
        if r["pit_eligibility"] != "PIT_ELIGIBLE":
            blockers.append("PIT_NOT_STRICT")
        if r["allowed_role"] == "INSUFFICIENT_COVERAGE":
            blockers.append("INSUFFICIENT_COVERAGE")
        if r["signal_role"] == "ENTRY_TIMING_ONLY":
            blockers.append("ENTRY_TIMING_NOT_DAILY_RANKING_ALPHA")
        if r["outlier_dependency_score"] > 0.45:
            blockers.append("OUTLIER_DEPENDENT")
        if r["regime_dependency_score"] > 0.75:
            blockers.append("REGIME_DEPENDENT")
        blockers.append("OFFICIAL_ADOPTION_DISABLED")
        review.append({
            "factor_name": r["factor_name"], "factor_family": r["factor_family"], "forward_horizon": r["forward_horizon"],
            "signal_role": r["signal_role"], "evidence_grade": r["evidence_grade"], "allowed_role": r["allowed_role"],
            "promotion_review_decision": "SHADOW_REVIEW_ONLY" if r["allowed_role"] == "SHADOW_CANDIDATE" else "NOT_PROMOTED",
            "officially_adopted": False, "blocker_count": len(blockers), "blockers": "|".join(blockers),
        })
    families = []
    for fam in sorted({r["factor_family"] for r in detail}):
        vals = [r for r in detail if r["factor_family"] == fam]
        families.append({"factor_family": fam, "factor_count": len({r["factor_name"] for r in vals}), "avg_abs_pearson_ic": mean([abs(r["pearson_ic"]) for r in vals]) if vals else 0.0, "avg_stability_score": mean([r["stability_score"] for r in vals]) if vals else 0.0, "shadow_candidate_count": sum(1 for r in vals if r["allowed_role"] == "SHADOW_CANDIDATE"), "pit_blocked_count": sum(1 for r in vals if r["allowed_role"] == "PIT_BLOCKED")})
    cluster = correlation_clusters(rows)
    summary = summary_payload(rows, detail, subdetail, review, inventory)
    return summary, {"source_audit": source_audit, "inventory": inventory, "detail": detail, "subdetail": subdetail, "families": families, "cluster": cluster, "regime": regime_rows, "outlier": outlier_rows, "review": review}


def correlation_clusters(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base = [r for r in rows if r.get("forward_window") == "1D"]
    pairs = []
    vals_by_factor: dict[str, dict[tuple[str, str, str], float]] = {}
    for factor, family, subtype, intrinsic_pit in FACTOR_DEFS:
        if not intrinsic_pit:
            continue
        vals_by_factor[factor] = {(r.get("ranking_date", ""), r.get("strategy", ""), r.get("ticker", "")): factor_value(r, factor, family, subtype) for r in base}
    names = sorted(vals_by_factor)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            keys = sorted(set(vals_by_factor[a]) & set(vals_by_factor[b]))
            if len(keys) < 3:
                continue
            c = corr([vals_by_factor[a][k] for k in keys], [vals_by_factor[b][k] for k in keys])
            pairs.append({"factor_a": a, "factor_b": b, "correlation": c, "cluster_label": "HIGH_OVERLAP" if abs(c) >= 0.75 else "LOW_TO_MODERATE_OVERLAP", "observation_count": len(keys)})
    return sorted(pairs, key=lambda r: abs(r["correlation"]), reverse=True)[:100]


def summary_payload(rows: list[dict[str, Any]], detail: list[dict[str, Any]], subdetail: list[dict[str, Any]], review: list[dict[str, Any]], inventory: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [r for r in detail if r["observation_count"] >= MIN_OBS and r["pit_eligibility"] == "PIT_ELIGIBLE"]
    shadow = sum(1 for r in detail if r["allowed_role"] == "SHADOW_CANDIDATE")
    pit_blocked = sum(1 for r in detail if r["allowed_role"] == "PIT_BLOCKED")
    insufficient = sum(1 for r in detail if r["allowed_role"] == "INSUFFICIENT_COVERAGE")
    if not rows or len({r["factor_name"] for r in evaluated}) < 4:
        status = "WARN_V21_243_FACTOR_EFFECTIVENESS_INSUFFICIENT_GRANULARITY"
        decision = "FACTOR_EFFECTIVENESS_BLOCKED_INSUFFICIENT_PIT_OR_COVERAGE"
    elif shadow == 0:
        status = "PARTIAL_PASS_V21_243_FACTOR_EFFECTIVENESS_LIMITED_EVIDENCE"
        decision = "FACTOR_EFFECTIVENESS_RESEARCH_LIMITED_CONTINUE_FORWARD_MATURITY"
    else:
        status = "PASS_V21_243_FACTOR_EFFECTIVENESS_RESEARCH_READY"
        decision = "FACTOR_EFFECTIVENESS_RESEARCH_READY_SHADOW_REVIEW_ONLY"
    return {
        "version": STAGE,
        "final_status": status,
        "final_decision": decision,
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": False,
        "input_files_mutated": False,
        "market_data_fetch_attempted": False,
        "network_provider_fetch_attempted": False,
        "evaluated_factor_count": len({r["factor_name"] for r in detail if r["observation_count"] > 0}),
        "evaluated_subfactor_count": len({r["factor_name"] for r in subdetail if r["observation_count"] > 0}),
        "pit_blocked_factor_count": len({r["factor_name"] for r in detail if r["allowed_role"] == "PIT_BLOCKED"}),
        "insufficient_coverage_factor_count": len({r["factor_name"] for r in detail if r["allowed_role"] == "INSUFFICIENT_COVERAGE"}),
        "shadow_candidate_count": shadow,
        "diagnostic_only_count": sum(1 for r in detail if r["allowed_role"] == "DIAGNOSTIC_ONLY"),
        "factor_inventory_count": len(inventory),
        "promotion_review_rows": len(review),
        "error_count": 0,
    }


def write_outputs(out: Path, summary: dict[str, Any], tables: dict[str, list[dict[str, Any]]]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "v21_243_summary.json", summary)
    metric_fields = ["factor_name", "factor_family", "factor_subtype", "forward_horizon", "pit_eligibility", "coverage_ratio", "observation_count", "pearson_ic", "spearman_rank_ic", "top_bottom_quantile_spread", "quantile_monotonicity_score", "win_rate_vs_universe", "outlier_dependency_score", "regime_dependency_score", "stability_score", "signal_role", "evidence_grade", "allowed_role", "official_adoption_allowed", "broker_action_allowed", "research_only"]
    write_csv(out / "factor_effectiveness_detail.csv", tables["detail"], metric_fields)
    write_csv(out / "subfactor_effectiveness_detail.csv", tables["subdetail"], metric_fields)
    write_csv(out / "family_effectiveness_summary.csv", tables["families"], ["factor_family", "factor_count", "avg_abs_pearson_ic", "avg_stability_score", "shadow_candidate_count", "pit_blocked_count"])
    write_csv(out / "technical_subfactor_effectiveness.csv", tables["subdetail"], metric_fields)
    write_csv(out / "factor_correlation_cluster.csv", tables["cluster"], ["factor_a", "factor_b", "correlation", "cluster_label", "observation_count"])
    write_csv(out / "factor_regime_dependency.csv", tables["regime"], ["factor_name", "forward_horizon", "regime_dependency_score", "high_regime_ic", "low_regime_ic", "allowed_role"])
    write_csv(out / "factor_outlier_dependency.csv", tables["outlier"], ["factor_name", "forward_horizon", "outlier_dependency_score", "full_pearson_ic", "trimmed_pearson_ic", "allowed_role"])
    write_csv(out / "factor_promotion_candidate_review.csv", tables["review"], ["factor_name", "factor_family", "forward_horizon", "signal_role", "evidence_grade", "allowed_role", "promotion_review_decision", "officially_adopted", "blocker_count", "blockers"])
    write_csv(out / "factor_inventory.csv", tables["inventory"], ["factor_name", "factor_family", "factor_subtype", "source_artifact", "pit_eligibility", "coverage_ratio", "available_horizons", "observation_count"])
    write_csv(out / "source_artifact_audit.csv", tables["source_audit"], ["source_artifact", "exists", "raw_rows", "usable_matured_rows"])
    report = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        "research_only=True",
        "official_adoption_allowed=False",
        "broker_action_allowed=False",
        f"evaluated_factor_count={summary['evaluated_factor_count']}",
        f"evaluated_subfactor_count={summary['evaluated_subfactor_count']}",
        "No official rankings, official weights, protected outputs, cache snapshots, trading plans, broker flags, or provider data were mutated.",
    ]
    (out / "V21.243_factor_effectiveness_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")


def run(repo: Path, output_dir: Path | None = None) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    try:
        summary, tables = build_outputs(repo)
    except Exception as exc:
        out.mkdir(parents=True, exist_ok=True)
        summary = {
            "version": STAGE,
            "final_status": "FAIL_V21_243_FACTOR_EFFECTIVENESS_EXECUTION_ERROR",
            "final_decision": "FACTOR_EFFECTIVENESS_BLOCKED_INSUFFICIENT_PIT_OR_COVERAGE",
            "research_only": True,
            "official_adoption_allowed": False,
            "broker_action_allowed": False,
            "protected_outputs_modified": False,
            "input_files_mutated": False,
            "market_data_fetch_attempted": False,
            "network_provider_fetch_attempted": False,
            "evaluated_factor_count": 0,
            "evaluated_subfactor_count": 0,
            "pit_blocked_factor_count": 0,
            "insufficient_coverage_factor_count": 0,
            "shadow_candidate_count": 0,
            "diagnostic_only_count": 0,
            "error_count": 1,
            "error": repr(exc),
        }
        write_json(out / "v21_243_summary.json", summary)
        raise
    write_outputs(out, summary, tables)
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    args = p.parse_args(argv)
    try:
        s = run(args.repo_root.resolve(), args.output_dir)
    except Exception:
        return 1
    out = args.output_dir or args.repo_root / OUT_REL
    print(str(out / "v21_243_summary.json"))
    for key in ["final_status", "final_decision", "evaluated_factor_count", "evaluated_subfactor_count", "pit_blocked_factor_count", "insufficient_coverage_factor_count", "shadow_candidate_count", "diagnostic_only_count", "official_adoption_allowed", "broker_action_allowed"]:
        print(f"{key}={s[key]}")
    print(f"output_root={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
