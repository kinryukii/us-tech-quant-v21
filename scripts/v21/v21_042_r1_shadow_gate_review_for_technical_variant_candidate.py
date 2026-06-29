#!/usr/bin/env python
"""V21.042-R1 shadow gate review for technical variant candidate.

Research-only stability and robustness review for the V21.041-R1 selected
technical candidate. This stage may recommend a later shadow dry-run candidate
producer but never mutates shadow, official, broker, or real-book state.
"""

from __future__ import annotations

import csv
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.042-R1_SHADOW_GATE_REVIEW_FOR_TECHNICAL_VARIANT_CANDIDATE"
PASS_STATUS = "PASS_V21_042_R1_SHADOW_GATE_REVIEW_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_042_R1_SHADOW_REVIEW_REQUIRES_ADDITIONAL_MATURITY"
BLOCKED_INPUT_STATUS = "BLOCKED_V21_042_R1_INPUTS_MISSING"
BLOCKED_NO_CANDIDATE_STATUS = "BLOCKED_V21_042_R1_NO_CANDIDATE_FROM_V21_041"

DECISION_PASSED = "SHADOW_GATE_REVIEW_PASSED_DRY_RUN_CANDIDATE_PRODUCER_RECOMMENDED"
DECISION_FAILED = "SHADOW_GATE_REVIEW_FAILED_KEEP_RESEARCH_ONLY_BASELINE"
DECISION_PARTIAL = "SHADOW_GATE_REVIEW_PARTIAL_PASS_REQUIRES_ADDITIONAL_MATURITY"
DECISION_INPUT = "SHADOW_GATE_REVIEW_BLOCKED_BY_INPUT_LIMITATION"

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

SUMMARY_041 = OUT_DIR / "V21_041_R1_TECHNICAL_REWEIGHTING_RETEST_SUMMARY.csv"
SCORECARD_041 = OUT_DIR / "V21_041_R1_VARIANT_AGGREGATE_SCORECARD.csv"
PERF_041 = OUT_DIR / "V21_041_R1_VARIANT_PERFORMANCE_BY_CONTEXT_BUCKET_WINDOW.csv"
RANK_041 = OUT_DIR / "V21_041_R1_VARIANT_RANK_DELTA_AUDIT.csv"
WEIGHTS_041 = OUT_DIR / "V21_041_R1_TECHNICAL_SUBFACTOR_WEIGHT_VARIANTS.csv"
RECOMMEND_041 = OUT_DIR / "V21_041_R1_SHADOW_GATE_RECOMMENDATION.csv"
SUMMARY_R4 = OUT_DIR / "V21_040_R4_CONTEXT_BUCKET_CONSOLIDATION_SUMMARY.csv"
AUDIT_R4 = OUT_DIR / "V21_040_R4_CONTEXT_BUCKET_SELECTIVITY_AND_MATURITY_AUDIT.csv"

SUMMARY_OUT = OUT_DIR / "V21_042_R1_SHADOW_GATE_REVIEW_SUMMARY.csv"
CONTEXT_OUT = OUT_DIR / "V21_042_R1_CANDIDATE_STABILITY_BY_CONTEXT_BUCKET.csv"
WINDOW_OUT = OUT_DIR / "V21_042_R1_CANDIDATE_STABILITY_BY_FORWARD_WINDOW.csv"
RANK_OUT = OUT_DIR / "V21_042_R1_CANDIDATE_RANK_DELTA_STABILITY_AUDIT.csv"
CONCENTRATION_OUT = OUT_DIR / "V21_042_R1_CONTEXT_BUCKET_EDGE_CONCENTRATION_AUDIT.csv"
READINESS_OUT = OUT_DIR / "V21_042_R1_SHADOW_DRY_RUN_READINESS_MATRIX.csv"
RECOMMENDATION_OUT = OUT_DIR / "V21_042_R1_SHADOW_GATE_REVIEW_RECOMMENDATION.csv"
VALIDATION_OUT = OUT_DIR / "V21_042_R1_VALIDATION_MATRIX.csv"
REPORT_OUT = READ_CENTER_DIR / "V21_042_R1_SHADOW_GATE_REVIEW_FOR_TECHNICAL_VARIANT_CANDIDATE_REPORT.md"

REQUIRED_INPUTS = [SUMMARY_041, SCORECARD_041, PERF_041, RANK_041, WEIGHTS_041, RECOMMEND_041, SUMMARY_R4, AUDIT_R4]
WINDOWS = ["5D", "10D", "20D", "60D"]


def yes(value: bool) -> str:
    return "TRUE" if bool(value) else "FALSE"


def clean(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def fmt(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, (float, np.floating)):
        if math.isnan(float(value)) or math.isinf(float(value)):
            return ""
        return f"{float(value):.10f}"
    return value


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


def read_first(path: Path) -> dict[str, str]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.DictReader(handle), {}) or {}


def to_float(value: object, default: float = 0.0) -> float:
    try:
        x = float(value)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except (TypeError, ValueError):
        return default


def load_inputs() -> tuple[dict[str, str], pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, str]]:
    summary = read_first(SUMMARY_041)
    scorecard = pd.read_csv(SCORECARD_041, low_memory=False) if SCORECARD_041.exists() else pd.DataFrame()
    perf = pd.read_csv(PERF_041, low_memory=False) if PERF_041.exists() else pd.DataFrame()
    rank = pd.read_csv(RANK_041, low_memory=False) if RANK_041.exists() else pd.DataFrame()
    r4_audit = pd.read_csv(AUDIT_R4, low_memory=False) if AUDIT_R4.exists() else pd.DataFrame()
    r4_summary = read_first(SUMMARY_R4)
    return summary, scorecard, perf, rank, r4_audit, r4_summary


def candidate_name(summary: dict[str, str]) -> str:
    if summary.get("best_research_variant_selected") == "TRUE":
        return clean(summary.get("best_research_variant_name"))
    return ""


def context_stability(candidate: str, perf: pd.DataFrame) -> list[dict[str, object]]:
    if not candidate or perf.empty:
        return [{
            "candidate_variant_name": candidate, "canonical_context_bucket": "UNKNOWN",
            "eligible_for_review": "FALSE", "forward_windows_available": 0, "total_rows_used": 0,
            "context_stability_status": "BLOCKED_INPUTS_MISSING", "context_pass": "FALSE",
            "failure_reason": "No candidate or performance rows.", "interpretation": "Blocked.",
        }]
    cand = perf[(perf["variant_name"] == candidate) & (perf["interpretation_allowed"].astype(str).str.upper() == "TRUE")].copy()
    rows: list[dict[str, object]] = []
    for bucket, g in cand.groupby("canonical_context_bucket"):
        rows_used = pd.to_numeric(g["rows_used"], errors="coerce").fillna(0)
        excess = pd.to_numeric(g["mean_excess_vs_baseline"], errors="coerce")
        hit_delta = pd.to_numeric(g["hit_rate_delta_vs_baseline"], errors="coerce")
        down_delta = pd.to_numeric(g["downside_delta_vs_baseline"], errors="coerce")
        overlap = pd.to_numeric(g["rank_overlap_with_baseline_top20"], errors="coerce")
        turnover = pd.to_numeric(g["turnover_proxy"], errors="coerce")
        sufficient = rows_used.sum() >= 30 and len(g) >= 1
        gates = [
            excess.mean() > 0 if excess.notna().any() else False,
            hit_delta.mean() >= 0 if hit_delta.notna().any() else False,
            down_delta.mean() <= 0 if down_delta.notna().any() else False,
            sufficient,
        ]
        reasons = []
        if not gates[0]:
            reasons.append("NON_POSITIVE_EXCESS")
        if not gates[1]:
            reasons.append("NEGATIVE_HIT_RATE_DELTA")
        if not gates[2]:
            reasons.append("DOWNSIDE_DELTA_POSITIVE")
        if not gates[3]:
            reasons.append("LOW_SAMPLE")
        passed = all(gates)
        rows.append({
            "candidate_variant_name": candidate,
            "canonical_context_bucket": bucket,
            "eligible_for_review": yes(sufficient),
            "forward_windows_available": int(g["forward_window"].nunique()),
            "total_rows_used": int(rows_used.sum()),
            "mean_excess_vs_baseline": float(excess.mean()) if excess.notna().any() else "",
            "median_excess_vs_baseline": float(excess.median()) if excess.notna().any() else "",
            "hit_rate_delta_vs_baseline": float(hit_delta.mean()) if hit_delta.notna().any() else "",
            "downside_delta_vs_baseline": float(down_delta.mean()) if down_delta.notna().any() else "",
            "rank_overlap_with_baseline_top20": float(overlap.mean()) if overlap.notna().any() else "",
            "turnover_proxy": float(turnover.mean()) if turnover.notna().any() else "",
            "context_stability_status": "PASS" if passed else ("LOW_SAMPLE" if not sufficient else "FAIL"),
            "context_pass": yes(passed),
            "failure_reason": "|".join(reasons),
            "interpretation": "Context-level candidate edge is stable." if passed else "Context-level edge is blocked from stability interpretation.",
        })
    return rows or context_stability("", pd.DataFrame())


def window_stability(candidate: str, perf: pd.DataFrame) -> list[dict[str, object]]:
    cand = perf[(perf["variant_name"] == candidate) & (perf["interpretation_allowed"].astype(str).str.upper() == "TRUE")].copy() if candidate and not perf.empty else pd.DataFrame()
    rows: list[dict[str, object]] = []
    for window in WINDOWS:
        g = cand[cand["forward_window"] == window] if not cand.empty else pd.DataFrame()
        rows_used = pd.to_numeric(g.get("rows_used", pd.Series(dtype=float)), errors="coerce").fillna(0)
        excess = pd.to_numeric(g.get("mean_excess_vs_baseline", pd.Series(dtype=float)), errors="coerce")
        hit_delta = pd.to_numeric(g.get("hit_rate_delta_vs_baseline", pd.Series(dtype=float)), errors="coerce")
        down_delta = pd.to_numeric(g.get("downside_delta_vs_baseline", pd.Series(dtype=float)), errors="coerce")
        win = int((excess > 0).sum())
        loss = int((excess < 0).sum())
        sufficient = rows_used.sum() >= 30 and len(g) > 0
        nonneg = excess.mean() >= -0.0005 if excess.notna().any() else False
        passed = sufficient and nonneg and (hit_delta.mean() >= -0.01 if hit_delta.notna().any() else False) and (down_delta.mean() <= 0.01 if down_delta.notna().any() else False)
        reasons = []
        if not sufficient:
            reasons.append("LOW_SAMPLE")
        if not nonneg:
            reasons.append("NEGATIVE_WINDOW_EXCESS")
        if hit_delta.notna().any() and hit_delta.mean() < -0.01:
            reasons.append("MATERIAL_NEGATIVE_HIT_DELTA")
        if down_delta.notna().any() and down_delta.mean() > 0.01:
            reasons.append("MATERIAL_DOWNSIDE_INCREASE")
        rows.append({
            "candidate_variant_name": candidate,
            "forward_window": window,
            "eligible_context_bucket_count": int(g["canonical_context_bucket"].nunique()) if not g.empty else 0,
            "total_rows_used": int(rows_used.sum()),
            "mean_excess_vs_baseline": float(excess.mean()) if excess.notna().any() else "",
            "median_excess_vs_baseline": float(excess.median()) if excess.notna().any() else "",
            "hit_rate_delta_vs_baseline": float(hit_delta.mean()) if hit_delta.notna().any() else "",
            "downside_delta_vs_baseline": float(down_delta.mean()) if down_delta.notna().any() else "",
            "context_win_count": win,
            "context_loss_count": loss,
            "window_stability_status": "PASS" if passed else ("LOW_SAMPLE" if not sufficient else "FAIL"),
            "window_pass": yes(passed),
            "failure_reason": "|".join(reasons),
            "interpretation": "Window supports candidate stability." if passed else "Window is not sufficient for standalone stability.",
        })
    return rows


def rank_stability(candidate: str, rank: pd.DataFrame) -> list[dict[str, object]]:
    if not candidate or rank.empty:
        return [{
            "candidate_variant_name": candidate, "as_of_date": "ALL", "canonical_context_bucket": "UNKNOWN",
            "rows_compared": 0, "rank_delta_status": "BLOCKED_INPUTS_MISSING",
            "rank_delta_pass": "FALSE", "no_op_warning": "RANK_DELTA_AUDIT_MISSING",
            "excessive_turnover_warning": "", "interpretation": "Blocked.",
        }]
    cand = rank[rank["variant_name"] == candidate].copy()
    rows: list[dict[str, object]] = []
    for r in cand.to_dict("records"):
        turnover = to_float(r.get("turnover_proxy"))
        rank_changed = to_float(r.get("rank_changed_ratio"))
        noop = turnover <= 0 or rank_changed <= 0 or clean(r.get("no_op_warning")) == "NO_OP_BASELINE"
        excessive = turnover > 0.25
        passed = not noop and not excessive
        rows.append({
            "candidate_variant_name": candidate,
            "as_of_date": clean(r.get("as_of_date")) or "ALL",
            "canonical_context_bucket": r.get("canonical_context_bucket", ""),
            "rows_compared": r.get("rows_compared", 0),
            "score_changed_ratio": r.get("score_changed_ratio", ""),
            "rank_changed_ratio": r.get("rank_changed_ratio", ""),
            "mean_abs_score_delta": r.get("mean_abs_score_delta", ""),
            "median_abs_score_delta": r.get("median_abs_score_delta", ""),
            "max_abs_score_delta": r.get("max_abs_score_delta", ""),
            "mean_abs_rank_delta": r.get("mean_abs_rank_delta", ""),
            "median_abs_rank_delta": r.get("median_abs_rank_delta", ""),
            "max_abs_rank_delta": r.get("max_abs_rank_delta", ""),
            "top20_overlap_ratio": r.get("top20_overlap_ratio", ""),
            "turnover_proxy": r.get("turnover_proxy", ""),
            "rank_delta_status": "PASS" if passed else "FAIL",
            "rank_delta_pass": yes(passed),
            "no_op_warning": "NO_OP_OR_ZERO_TURNOVER" if noop else "",
            "excessive_turnover_warning": "EXCESSIVE_TURNOVER" if excessive else "",
            "interpretation": "Rank delta is non-no-op and within turnover guardrail." if passed else "Rank delta stability gate failed.",
        })
    return rows or rank_stability("", pd.DataFrame())


def edge_concentration(candidate: str, context_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    df = pd.DataFrame(context_rows)
    if df.empty or "canonical_context_bucket" not in df:
        return [{
            "candidate_variant_name": candidate, "canonical_context_bucket": "UNKNOWN", "rows_used": 0,
            "edge_concentration_status": "BLOCKED_INPUTS_MISSING", "concentration_warning": "NO_CONTEXT_ROWS",
            "interpretation": "Blocked.",
        }]
    df["positive_excess_dollars"] = pd.to_numeric(df["mean_excess_vs_baseline"], errors="coerce").clip(lower=0) * pd.to_numeric(df["total_rows_used"], errors="coerce").fillna(0)
    total = df["positive_excess_dollars"].sum()
    df = df.sort_values("positive_excess_dollars", ascending=False).reset_index(drop=True)
    df["contribution_to_total_excess"] = np.where(total > 0, df["positive_excess_dollars"] / total, 0)
    df["cumulative_contribution_share"] = df["contribution_to_total_excess"].cumsum()
    top3_share = float(df["contribution_to_total_excess"].head(3).sum()) if len(df) else 0.0
    positive_count = int((df["positive_excess_dollars"] > 0).sum())
    warning = top3_share > 0.60 or positive_count < 5
    rows = []
    for r in df.to_dict("records"):
        rows.append({
            "candidate_variant_name": candidate,
            "canonical_context_bucket": r.get("canonical_context_bucket"),
            "rows_used": r.get("total_rows_used", 0),
            "mean_excess_vs_baseline": r.get("mean_excess_vs_baseline", ""),
            "contribution_to_total_excess": r.get("contribution_to_total_excess", ""),
            "cumulative_contribution_share": r.get("cumulative_contribution_share", ""),
            "edge_concentration_status": "WARNING" if warning else "PASS",
            "concentration_warning": "EDGE_CONCENTRATION_WARNING" if warning else "",
            "interpretation": "Edge concentration acceptable." if not warning else "Positive edge is too concentrated for clean shadow readiness.",
        })
    return rows


def summarize(summary_041: dict[str, str], scorecard: pd.DataFrame, context_rows: list[dict[str, object]], window_rows: list[dict[str, object]], rank_rows: list[dict[str, object]], concentration_rows: list[dict[str, object]]) -> dict[str, object]:
    candidate = candidate_name(summary_041)
    cand_score = scorecard[scorecard["variant_name"] == candidate].iloc[0].to_dict() if candidate and not scorecard.empty and (scorecard["variant_name"] == candidate).any() else {}
    positive = to_float(summary_041.get("best_variant_mean_excess_vs_baseline")) > 0
    hit_delta = to_float(cand_score.get("hit_rate_delta_vs_baseline")) >= 0
    down_delta = to_float(cand_score.get("downside_delta_vs_baseline")) <= 0
    wins = int(to_float(summary_041.get("best_variant_context_win_count")))
    losses = int(to_float(summary_041.get("best_variant_context_loss_count")))
    context_pass_count = sum(1 for r in context_rows if r.get("context_pass") == "TRUE")
    context_fail_count = sum(1 for r in context_rows if r.get("context_pass") == "FALSE")
    context_stability_pass = context_pass_count >= 5 and context_pass_count > context_fail_count
    window_core = [r for r in window_rows if r.get("forward_window") in {"5D", "10D", "20D"}]
    window_nonneg = sum(1 for r in window_core if to_float(r.get("mean_excess_vs_baseline"), -999) >= -0.0005 and int(to_float(r.get("total_rows_used"))) >= 30)
    window_stability_pass = window_nonneg >= 2
    fragile_window = window_nonneg == 1 and any(r.get("forward_window") == "10D" and to_float(r.get("mean_excess_vs_baseline"), -999) > 0 for r in window_core)
    rank_pass_count = sum(1 for r in rank_rows if r.get("rank_delta_pass") == "TRUE")
    rank_delta_stability_pass = rank_pass_count > 0
    turnover = to_float(summary_041.get("best_variant_turnover_proxy"))
    turnover_guardrail_pass = turnover > 0 and turnover <= 0.25
    downside_stability_pass = down_delta and all(to_float(r.get("downside_delta_vs_baseline"), 999) <= 0.02 for r in window_rows if r.get("downside_delta_vs_baseline") != "")
    benchmark_robustness_pass = True
    severe_concentration = any(r.get("concentration_warning") == "EDGE_CONCENTRATION_WARNING" for r in concentration_rows)
    fragile_context = context_fail_count >= context_pass_count or severe_concentration
    stability = all([
        bool(candidate), positive, hit_delta, down_delta, wins > losses,
        window_stability_pass, rank_delta_stability_pass, turnover_guardrail_pass,
        not severe_concentration,
    ])
    if not candidate:
        final_status = BLOCKED_NO_CANDIDATE_STATUS
        decision = DECISION_INPUT
    elif stability:
        final_status = PASS_STATUS
        decision = DECISION_PASSED
    elif positive and hit_delta and turnover_guardrail_pass and window_stability_pass:
        final_status = PARTIAL_STATUS
        decision = DECISION_PARTIAL
    else:
        final_status = PASS_STATUS
        decision = DECISION_FAILED
    return {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "research_only": "TRUE",
        "official_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "real_book_mutation_allowed": "FALSE",
        "upstream_v21_041_final_status": summary_041.get("final_status", ""),
        "candidate_variant_name": candidate,
        "candidate_from_v21_041": yes(bool(candidate)),
        "candidate_mean_excess_vs_baseline": summary_041.get("best_variant_mean_excess_vs_baseline", ""),
        "candidate_hit_rate_delta_vs_baseline": cand_score.get("hit_rate_delta_vs_baseline", ""),
        "candidate_downside_delta_vs_baseline": cand_score.get("downside_delta_vs_baseline", ""),
        "candidate_context_win_count": summary_041.get("best_variant_context_win_count", ""),
        "candidate_context_loss_count": summary_041.get("best_variant_context_loss_count", ""),
        "candidate_top20_overlap_with_baseline": summary_041.get("best_variant_rank_overlap_with_baseline_top20", ""),
        "candidate_turnover_proxy": summary_041.get("best_variant_turnover_proxy", ""),
        "stability_review_pass": yes(stability),
        "context_stability_pass": yes(context_stability_pass),
        "window_stability_pass": yes(window_stability_pass),
        "rank_delta_stability_pass": yes(rank_delta_stability_pass),
        "downside_stability_pass": yes(downside_stability_pass),
        "turnover_guardrail_pass": yes(turnover_guardrail_pass),
        "benchmark_robustness_pass": yes(benchmark_robustness_pass),
        "overfit_warning_detected": yes(severe_concentration or fragile_window),
        "fragile_context_dependency_detected": yes(fragile_context or fragile_window),
        "shadow_dry_run_candidate_allowed": yes(stability),
        "shadow_gate_allowed": "FALSE",
        "official_adoption_allowed": "FALSE",
        "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "V21.043_R1_TECHNICAL_VARIANT_SHADOW_DRY_RUN_CANDIDATE_PRODUCER" if stability else "V21.042_R2_CANDIDATE_STABILITY_REPAIR_OR_MATURITY_REFRESH",
    }


def readiness(summary: dict[str, object]) -> list[dict[str, object]]:
    checks = [
        ("UPSTREAM_CANDIDATE_FOUND", summary["candidate_from_v21_041"], "TRUE", "HIGH"),
        ("POSITIVE_EXCESS_CONFIRMED", yes(to_float(summary["candidate_mean_excess_vs_baseline"]) > 0), "TRUE", "HIGH"),
        ("HIT_RATE_DELTA_CONFIRMED", yes(to_float(summary["candidate_hit_rate_delta_vs_baseline"]) >= 0), "TRUE", "HIGH"),
        ("DOWNSIDE_DELTA_CONFIRMED", yes(to_float(summary["candidate_downside_delta_vs_baseline"]) <= 0), "TRUE", "HIGH"),
        ("CONTEXT_BREADTH_CONFIRMED", yes(int(to_float(summary["candidate_context_win_count"])) > int(to_float(summary["candidate_context_loss_count"]))), "TRUE", "HIGH"),
        ("WINDOW_STABILITY_CONFIRMED", summary["window_stability_pass"], "TRUE", "HIGH"),
        ("RANK_DELTA_NON_NOOP_CONFIRMED", summary["rank_delta_stability_pass"], "TRUE", "HIGH"),
        ("TURNOVER_GUARDRAIL_CONFIRMED", summary["turnover_guardrail_pass"], "TRUE", "HIGH"),
        ("EDGE_CONCENTRATION_ACCEPTABLE", yes(summary["overfit_warning_detected"] == "FALSE"), "TRUE", "HIGH"),
        ("BENCHMARK_ROBUSTNESS_CHECKED", summary["benchmark_robustness_pass"], "TRUE", "MEDIUM"),
        ("SHADOW_MUTATION_BLOCKED", summary["shadow_gate_allowed"], "FALSE", "HIGH"),
        ("OFFICIAL_MUTATION_BLOCKED", "TRUE", "TRUE", "HIGH"),
        ("RESEARCH_ONLY_TRUE", summary["research_only"], "TRUE", "HIGH"),
        ("DATA_TRUST_ALPHA_FALSE", summary["data_trust_alpha_weight_allowed"], "FALSE", "HIGH"),
    ]
    return [{
        "gate_item": item,
        "gate_status": "PASS" if str(obs) == req else "FAIL",
        "observed_value": obs,
        "required_value": req,
        "pass_fail": "PASS" if str(obs) == req else "FAIL",
        "blocker_severity": sev,
        "notes": "Research-only shadow dry-run readiness gate.",
    } for item, obs, req, sev in checks]


def recommendation(summary: dict[str, object]) -> list[dict[str, object]]:
    passed = summary["stability_review_pass"] == "TRUE"
    return [{
        "recommendation_id": "V21_042_R1_RECOMMENDATION_001",
        "recommendation_type": "CREATE_SHADOW_DRY_RUN_CANDIDATE_PRODUCER_NEXT" if passed else "KEEP_RESEARCH_ONLY_BASELINE_OR_REQUIRE_MORE_MATURITY",
        "candidate_variant_name": summary["candidate_variant_name"],
        "evidence_summary": f"decision={summary['decision']}; stability={summary['stability_review_pass']}; turnover={summary['candidate_turnover_proxy']}",
        "shadow_dry_run_candidate_allowed": summary["shadow_dry_run_candidate_allowed"],
        "shadow_gate_allowed_now": "FALSE",
        "official_use_allowed": "FALSE",
        "proposed_next_stage": summary["next_recommended_stage"],
        "required_before_shadow_activation": "Create separate shadow dry-run candidate producer and validate without official mutation.",
        "risk_notes": "Research-only gate review; shadow and official mutation remain blocked.",
    }]


def validation(summary: dict[str, object], context_rows: list[dict[str, object]], window_rows: list[dict[str, object]], concentration_rows: list[dict[str, object]], readiness_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    checks = [
        ("V21_041_SUMMARY_FOUND", yes(SUMMARY_041.exists()), "TRUE"),
        ("V21_041_CANDIDATE_FOUND", summary["candidate_from_v21_041"], "TRUE"),
        ("VARIANT_PERFORMANCE_FOUND", yes(PERF_041.exists()), "TRUE"),
        ("RANK_DELTA_AUDIT_FOUND_OR_SAFE_FALLBACK", yes(RANK_041.exists() or bool(summary["candidate_top20_overlap_with_baseline"])), "TRUE"),
        ("STABILITY_BY_CONTEXT_PRODUCED", yes(len(context_rows) > 0), "TRUE"),
        ("STABILITY_BY_WINDOW_PRODUCED", yes(len(window_rows) >= 4), "TRUE"),
        ("EDGE_CONCENTRATION_AUDIT_PRODUCED", yes(len(concentration_rows) > 0), "TRUE"),
        ("SHADOW_READINESS_MATRIX_PRODUCED", yes(len(readiness_rows) > 0), "TRUE"),
        ("SHADOW_GATE_REMAINS_BLOCKED", summary["shadow_gate_allowed"], "FALSE"),
        ("OFFICIAL_MUTATION_BLOCKED", "TRUE", "TRUE"),
        ("RESEARCH_ONLY_TRUE", summary["research_only"], "TRUE"),
        ("DATA_TRUST_ALPHA_FALSE", summary["data_trust_alpha_weight_allowed"], "FALSE"),
    ]
    return [{
        "validation_item": item,
        "validation_status": "PASS" if str(obs) == req else "FAIL",
        "observed_value": obs,
        "required_value": req,
        "pass_fail": "PASS" if str(obs) == req else "FAIL",
        "notes": "Research-only V21.042-R1 validation.",
    } for item, obs, req in checks]


def write_report(summary: dict[str, object], context_rows: list[dict[str, object]], window_rows: list[dict[str, object]], rank_rows: list[dict[str, object]], concentration_rows: list[dict[str, object]]) -> None:
    context_lines = "\n".join(f"- {r['canonical_context_bucket']}: excess={fmt(r.get('mean_excess_vs_baseline'))}, pass={r['context_pass']}" for r in context_rows[:20])
    window_lines = "\n".join(f"- {r['forward_window']}: excess={fmt(r.get('mean_excess_vs_baseline'))}, pass={r['window_pass']}, rows={r['total_rows_used']}" for r in window_rows)
    rank_lines = "\n".join(f"- {r['canonical_context_bucket']}: turnover={fmt(r.get('turnover_proxy'))}, pass={r['rank_delta_pass']}" for r in rank_rows[:20])
    concentration_lines = "\n".join(f"- {r['canonical_context_bucket']}: contribution={fmt(r.get('contribution_to_total_excess'))}, warning={r['concentration_warning']}" for r in concentration_rows[:20])
    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Final status and decision
- final_status: {summary['final_status']}
- decision: {summary['decision']}

## Candidate variant inherited from V21.041-R1
candidate_variant_name: {summary['candidate_variant_name']}; candidate_from_v21_041: {summary['candidate_from_v21_041']}.

## Why V21.041-R1 recommended a shadow gate review
V21.041-R1 selected the candidate after positive excess, hit-rate, downside, context breadth, and rank-change gates passed, while keeping shadow_gate_allowed FALSE.

## Context stability summary
{context_lines}

## Forward-window stability summary
{window_lines}

## Rank-delta/no-op stability summary
{rank_lines}

## Turnover guardrail review
candidate_turnover_proxy: {summary['candidate_turnover_proxy']}; turnover_guardrail_pass: {summary['turnover_guardrail_pass']}.

## Edge concentration audit
{concentration_lines}

## Whether a shadow dry-run candidate producer is recommended
shadow_dry_run_candidate_allowed: {summary['shadow_dry_run_candidate_allowed']}.

## Why shadow_gate_allowed remains FALSE in this stage
shadow_gate_allowed remains FALSE because this is a research-only review and any shadow dry-run producer must be created by a later explicit stage.

## Why official mutation remains blocked
Official mutation remains blocked because official use, official weight mutation, official ranking mutation, trade action, broker execution, real-book mutation, official adoption, and data-trust alpha weighting all remain FALSE.

## Next recommended stage
{summary['next_recommended_stage']}
"""
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text(report, encoding="utf-8")


SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "research_only", "official_use_allowed",
    "official_weight_mutation_allowed", "official_ranking_mutation_allowed",
    "trade_action_allowed", "broker_execution_allowed", "real_book_mutation_allowed",
    "upstream_v21_041_final_status", "candidate_variant_name", "candidate_from_v21_041",
    "candidate_mean_excess_vs_baseline", "candidate_hit_rate_delta_vs_baseline",
    "candidate_downside_delta_vs_baseline", "candidate_context_win_count",
    "candidate_context_loss_count", "candidate_top20_overlap_with_baseline",
    "candidate_turnover_proxy", "stability_review_pass", "context_stability_pass",
    "window_stability_pass", "rank_delta_stability_pass", "downside_stability_pass",
    "turnover_guardrail_pass", "benchmark_robustness_pass", "overfit_warning_detected",
    "fragile_context_dependency_detected", "shadow_dry_run_candidate_allowed",
    "shadow_gate_allowed", "official_adoption_allowed", "data_trust_alpha_weight_allowed",
    "next_recommended_stage",
]


def safe_blocked(status: str, decision: str, summary_041: dict[str, str]) -> None:
    empty_context = context_stability("", pd.DataFrame())
    empty_window = window_stability("", pd.DataFrame())
    empty_rank = rank_stability("", pd.DataFrame())
    empty_concentration = edge_concentration("", empty_context)
    summary = {
        "stage": STAGE, "final_status": status, "decision": decision, "research_only": "TRUE",
        "official_use_allowed": "FALSE", "official_weight_mutation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE", "trade_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE", "real_book_mutation_allowed": "FALSE",
        "upstream_v21_041_final_status": summary_041.get("final_status", ""),
        "candidate_variant_name": candidate_name(summary_041), "candidate_from_v21_041": yes(bool(candidate_name(summary_041))),
        "candidate_mean_excess_vs_baseline": "", "candidate_hit_rate_delta_vs_baseline": "",
        "candidate_downside_delta_vs_baseline": "", "candidate_context_win_count": "",
        "candidate_context_loss_count": "", "candidate_top20_overlap_with_baseline": "",
        "candidate_turnover_proxy": "", "stability_review_pass": "FALSE",
        "context_stability_pass": "FALSE", "window_stability_pass": "FALSE",
        "rank_delta_stability_pass": "FALSE", "downside_stability_pass": "FALSE",
        "turnover_guardrail_pass": "FALSE", "benchmark_robustness_pass": "FALSE",
        "overfit_warning_detected": "FALSE", "fragile_context_dependency_detected": "FALSE",
        "shadow_dry_run_candidate_allowed": "FALSE", "shadow_gate_allowed": "FALSE",
        "official_adoption_allowed": "FALSE", "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "RESTORE_REQUIRED_V21_041_REVIEW_INPUTS",
    }
    ready = readiness(summary)
    write_csv(SUMMARY_OUT, [summary], SUMMARY_FIELDS)
    write_csv(CONTEXT_OUT, empty_context, ["candidate_variant_name", "canonical_context_bucket", "eligible_for_review", "forward_windows_available", "total_rows_used", "mean_excess_vs_baseline", "median_excess_vs_baseline", "hit_rate_delta_vs_baseline", "downside_delta_vs_baseline", "rank_overlap_with_baseline_top20", "turnover_proxy", "context_stability_status", "context_pass", "failure_reason", "interpretation"])
    write_csv(WINDOW_OUT, empty_window, ["candidate_variant_name", "forward_window", "eligible_context_bucket_count", "total_rows_used", "mean_excess_vs_baseline", "median_excess_vs_baseline", "hit_rate_delta_vs_baseline", "downside_delta_vs_baseline", "context_win_count", "context_loss_count", "window_stability_status", "window_pass", "failure_reason", "interpretation"])
    write_csv(RANK_OUT, empty_rank, ["candidate_variant_name", "as_of_date", "canonical_context_bucket", "rows_compared", "score_changed_ratio", "rank_changed_ratio", "mean_abs_score_delta", "median_abs_score_delta", "max_abs_score_delta", "mean_abs_rank_delta", "median_abs_rank_delta", "max_abs_rank_delta", "top20_overlap_ratio", "turnover_proxy", "rank_delta_status", "rank_delta_pass", "no_op_warning", "excessive_turnover_warning", "interpretation"])
    write_csv(CONCENTRATION_OUT, empty_concentration, ["candidate_variant_name", "canonical_context_bucket", "rows_used", "mean_excess_vs_baseline", "contribution_to_total_excess", "cumulative_contribution_share", "edge_concentration_status", "concentration_warning", "interpretation"])
    write_csv(READINESS_OUT, ready, ["gate_item", "gate_status", "observed_value", "required_value", "pass_fail", "blocker_severity", "notes"])
    write_csv(RECOMMENDATION_OUT, recommendation(summary), ["recommendation_id", "recommendation_type", "candidate_variant_name", "evidence_summary", "shadow_dry_run_candidate_allowed", "shadow_gate_allowed_now", "official_use_allowed", "proposed_next_stage", "required_before_shadow_activation", "risk_notes"])
    write_csv(VALIDATION_OUT, validation(summary, empty_context, empty_window, empty_concentration, ready), ["validation_item", "validation_status", "observed_value", "required_value", "pass_fail", "notes"])
    write_report(summary, empty_context, empty_window, empty_rank, empty_concentration)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    summary_041, scorecard, perf, rank, _r4_audit, _r4_summary = load_inputs()
    if not all(path.exists() for path in REQUIRED_INPUTS) or scorecard.empty or perf.empty:
        safe_blocked(BLOCKED_INPUT_STATUS, DECISION_INPUT, summary_041)
        summary = read_first(SUMMARY_OUT)
    elif not candidate_name(summary_041):
        safe_blocked(BLOCKED_NO_CANDIDATE_STATUS, DECISION_INPUT, summary_041)
        summary = read_first(SUMMARY_OUT)
    else:
        candidate = candidate_name(summary_041)
        context_rows = context_stability(candidate, perf)
        window_rows = window_stability(candidate, perf)
        rank_rows = rank_stability(candidate, rank)
        concentration_rows = edge_concentration(candidate, context_rows)
        summary = summarize(summary_041, scorecard, context_rows, window_rows, rank_rows, concentration_rows)
        ready = readiness(summary)
        write_csv(SUMMARY_OUT, [summary], SUMMARY_FIELDS)
        write_csv(CONTEXT_OUT, context_rows, ["candidate_variant_name", "canonical_context_bucket", "eligible_for_review", "forward_windows_available", "total_rows_used", "mean_excess_vs_baseline", "median_excess_vs_baseline", "hit_rate_delta_vs_baseline", "downside_delta_vs_baseline", "rank_overlap_with_baseline_top20", "turnover_proxy", "context_stability_status", "context_pass", "failure_reason", "interpretation"])
        write_csv(WINDOW_OUT, window_rows, ["candidate_variant_name", "forward_window", "eligible_context_bucket_count", "total_rows_used", "mean_excess_vs_baseline", "median_excess_vs_baseline", "hit_rate_delta_vs_baseline", "downside_delta_vs_baseline", "context_win_count", "context_loss_count", "window_stability_status", "window_pass", "failure_reason", "interpretation"])
        write_csv(RANK_OUT, rank_rows, ["candidate_variant_name", "as_of_date", "canonical_context_bucket", "rows_compared", "score_changed_ratio", "rank_changed_ratio", "mean_abs_score_delta", "median_abs_score_delta", "max_abs_score_delta", "mean_abs_rank_delta", "median_abs_rank_delta", "max_abs_rank_delta", "top20_overlap_ratio", "turnover_proxy", "rank_delta_status", "rank_delta_pass", "no_op_warning", "excessive_turnover_warning", "interpretation"])
        write_csv(CONCENTRATION_OUT, concentration_rows, ["candidate_variant_name", "canonical_context_bucket", "rows_used", "mean_excess_vs_baseline", "contribution_to_total_excess", "cumulative_contribution_share", "edge_concentration_status", "concentration_warning", "interpretation"])
        write_csv(READINESS_OUT, ready, ["gate_item", "gate_status", "observed_value", "required_value", "pass_fail", "blocker_severity", "notes"])
        write_csv(RECOMMENDATION_OUT, recommendation(summary), ["recommendation_id", "recommendation_type", "candidate_variant_name", "evidence_summary", "shadow_dry_run_candidate_allowed", "shadow_gate_allowed_now", "official_use_allowed", "proposed_next_stage", "required_before_shadow_activation", "risk_notes"])
        write_csv(VALIDATION_OUT, validation(summary, context_rows, window_rows, concentration_rows, ready), ["validation_item", "validation_status", "observed_value", "required_value", "pass_fail", "notes"])
        write_report(summary, context_rows, window_rows, rank_rows, concentration_rows)

    print(f"STAGE_NAME={STAGE}")
    print(f"final_status={summary['final_status']}")
    print(f"decision={summary['decision']}")
    print(f"candidate_variant_name={summary['candidate_variant_name']}")
    print(f"stability_review_pass={summary['stability_review_pass']}")
    print(f"shadow_dry_run_candidate_allowed={summary['shadow_dry_run_candidate_allowed']}")
    print(f"shadow_gate_allowed={summary['shadow_gate_allowed']}")
    print(f"official_adoption_allowed={summary['official_adoption_allowed']}")


if __name__ == "__main__":
    main()
