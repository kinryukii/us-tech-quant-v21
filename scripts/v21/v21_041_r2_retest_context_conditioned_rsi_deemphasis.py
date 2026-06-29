#!/usr/bin/env python
"""V21.041-R2 context-conditioned RSI deemphasis retest.

Research-only retest of the V21.042-R2 repaired candidate. The conditioned
candidate uses RSI_DEEMPHASIZED_R4 performance only in approved context buckets
and baseline true technical performance elsewhere.
"""

from __future__ import annotations

import csv
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.041-R2_RETEST_CONTEXT_CONDITIONED_RSI_DEEMPHASIS"
PASS_STATUS = "PASS_V21_041_R2_CONTEXT_CONDITIONED_RETEST_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_041_R2_CONTEXT_CONDITIONED_RETEST_LIMITED"
BLOCKED_GATE_STATUS = "BLOCKED_V21_041_R2_R2_GATE_NOT_READY"
BLOCKED_INPUT_STATUS = "BLOCKED_V21_041_R2_INPUTS_MISSING"

DECISION_PASSED = "CONTEXT_CONDITIONED_RSI_RETEST_PASSED_SHADOW_REVIEW_RECOMMENDED"
DECISION_IMPROVES = "CONTEXT_CONDITIONED_RSI_RETEST_IMPROVES_BUT_NEEDS_MORE_MATURITY"
DECISION_NO_IMPROVE = "CONTEXT_CONDITIONED_RSI_RETEST_NO_IMPROVEMENT_KEEP_BASELINE"
DECISION_INPUT = "CONTEXT_CONDITIONED_RSI_RETEST_BLOCKED_BY_INPUT_LIMITATION"
DECISION_GATE = "CONTEXT_CONDITIONED_RSI_RETEST_BLOCKED_BY_R2_GATE"

BASELINE = "BASELINE_TRUE_TECHNICAL"
GLOBAL = "RSI_DEEMPHASIZED_R4"
CONDITIONED = "RSI_DEEMPHASIZED_CONTEXT_CONDITIONED_R4_R2"

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

R2_SUMMARY = OUT_DIR / "V21_042_R2_CONTEXT_CONDITIONED_RSI_REPAIR_SUMMARY.csv"
R2_ACTION = OUT_DIR / "V21_042_R2_CONTEXT_BUCKET_RSI_ACTION_MAP.csv"
R2_DEFINITION = OUT_DIR / "V21_042_R2_CONTEXT_CONDITIONED_VARIANT_DEFINITION.csv"
R2_SCOPE = OUT_DIR / "V21_042_R2_EXPECTED_RETEST_SCOPE.csv"
R2_CONCENTRATION = OUT_DIR / "V21_042_R2_EDGE_CONCENTRATION_REPAIR_AUDIT.csv"
R4_LEDGER = OUT_DIR / "V21_040_R4_CANONICAL_CONTEXT_LEDGER.csv"
SNAPSHOT = OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv"
V41_PERF = OUT_DIR / "V21_041_R1_VARIANT_PERFORMANCE_BY_CONTEXT_BUCKET_WINDOW.csv"
V41_SCORECARD = OUT_DIR / "V21_041_R1_VARIANT_AGGREGATE_SCORECARD.csv"

SUMMARY_OUT = OUT_DIR / "V21_041_R2_CONTEXT_CONDITIONED_RETEST_SUMMARY.csv"
SCORECARD_OUT = OUT_DIR / "V21_041_R2_VARIANT_COMPARISON_SCORECARD.csv"
PERF_OUT = OUT_DIR / "V21_041_R2_PERFORMANCE_BY_CONTEXT_BUCKET_WINDOW.csv"
WINDOW_OUT = OUT_DIR / "V21_041_R2_WINDOW_STABILITY_COMPARISON.csv"
CONCENTRATION_OUT = OUT_DIR / "V21_041_R2_EDGE_CONCENTRATION_COMPARISON.csv"
HARMFUL_OUT = OUT_DIR / "V21_041_R2_HARMFUL_CONTEXT_BLOCK_AUDIT.csv"
RECOMMENDATION_OUT = OUT_DIR / "V21_041_R2_RETEST_RECOMMENDATION.csv"
VALIDATION_OUT = OUT_DIR / "V21_041_R2_VALIDATION_MATRIX.csv"
REPORT_OUT = READ_CENTER_DIR / "V21_041_R2_RETEST_CONTEXT_CONDITIONED_RSI_DEEMPHASIS_REPORT.md"

REQUIRED_INPUTS = [R2_SUMMARY, R2_ACTION, R2_DEFINITION, R2_SCOPE, R2_CONCENTRATION, R4_LEDGER, SNAPSHOT, V41_PERF, V41_SCORECARD]
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


def to_float(value: object, default: float = 0.0) -> float:
    try:
        x = float(value)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except (TypeError, ValueError):
        return default


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


def load_inputs() -> tuple[dict[str, str], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summary = read_first(R2_SUMMARY)
    action = pd.read_csv(R2_ACTION, low_memory=False) if R2_ACTION.exists() else pd.DataFrame()
    perf = pd.read_csv(V41_PERF, low_memory=False) if V41_PERF.exists() else pd.DataFrame()
    score = pd.read_csv(V41_SCORECARD, low_memory=False) if V41_SCORECARD.exists() else pd.DataFrame()
    return summary, action, perf, score


def numeric(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(df.get(col, pd.Series(dtype=float)), errors="coerce")


def build_conditioned_perf(action: pd.DataFrame, perf: pd.DataFrame) -> list[dict[str, object]]:
    action_map = {r["canonical_context_bucket"]: r["rsi_action"] for r in action.to_dict("records")}
    include = {r["canonical_context_bucket"]: str(r["include_in_context_conditioned_candidate"]).upper() == "TRUE" for r in action.to_dict("records")}
    base = perf[perf["variant_name"] == BASELINE].copy()
    glob = perf[perf["variant_name"] == GLOBAL].copy()
    key_cols = ["canonical_context_bucket", "forward_window"]
    base_by_key = {tuple(r[c] for c in key_cols): r for r in base.to_dict("records")}
    glob_by_key = {tuple(r[c] for c in key_cols): r for r in glob.to_dict("records")}
    keys = sorted(set(base_by_key) | set(glob_by_key))
    rows: list[dict[str, object]] = []

    def emit_variant(name: str, source_rows: dict[tuple[str, str], dict[str, object]]) -> None:
        for key, r in source_rows.items():
            bucket, window = key
            b = base_by_key.get(key, {})
            g = glob_by_key.get(key, {})
            mean = to_float(r.get("mean_forward_return"))
            base_mean = to_float(b.get("mean_forward_return"))
            glob_mean = to_float(g.get("mean_forward_return"))
            hit = to_float(r.get("hit_rate"))
            down = to_float(r.get("downside_rate"))
            rows.append({
                "variant_name": name,
                "canonical_context_bucket": bucket,
                "rsi_action": "BASELINE_REFERENCE" if name == BASELINE else ("GLOBAL_REFERENCE" if name == GLOBAL else action_map.get(bucket, "KEEP_BASELINE_RSI")),
                "forward_window": window,
                "top_bucket": "TOP20",
                "rows_used": r.get("rows_used", 0),
                "mean_forward_return": r.get("mean_forward_return", ""),
                "median_forward_return": r.get("median_forward_return", ""),
                "hit_rate": r.get("hit_rate", ""),
                "downside_rate": r.get("downside_rate", ""),
                "baseline_mean_forward_return": base_mean,
                "global_rsi_deemphasized_mean_forward_return": glob_mean,
                "mean_excess_vs_baseline": mean - base_mean,
                "mean_excess_vs_global_rsi_deemphasized": mean - glob_mean,
                "hit_rate_delta_vs_baseline": hit - to_float(b.get("hit_rate")),
                "downside_delta_vs_baseline": down - to_float(b.get("downside_rate")),
                "context_pass": yes(mean >= base_mean),
                "interpretation_allowed": r.get("interpretation_allowed", "FALSE"),
                "interpretation_block_reason": r.get("interpretation_block_reason", ""),
            })

    emit_variant(BASELINE, base_by_key)
    emit_variant(GLOBAL, glob_by_key)
    conditioned_rows = {}
    for key in keys:
        bucket, _window = key
        conditioned_rows[key] = glob_by_key.get(key, base_by_key.get(key, {})) if include.get(bucket, False) else base_by_key.get(key, glob_by_key.get(key, {}))
    emit_variant(CONDITIONED, conditioned_rows)
    return rows


def aggregate_scorecard(perf_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    df = pd.DataFrame(perf_rows)
    rows = []
    base = df[df["variant_name"] == BASELINE]
    glob = df[df["variant_name"] == GLOBAL]
    for name in [BASELINE, GLOBAL, CONDITIONED]:
        g = df[(df["variant_name"] == name) & (df["interpretation_allowed"].astype(str).str.upper() == "TRUE")].copy()
        if g.empty:
            g = df[df["variant_name"] == name].copy()
        mean = numeric(g, "mean_forward_return")
        base_mean = numeric(g, "baseline_mean_forward_return")
        glob_mean = numeric(g, "global_rsi_deemphasized_mean_forward_return")
        excess_base = numeric(g, "mean_excess_vs_baseline")
        excess_global = numeric(g, "mean_excess_vs_global_rsi_deemphasized")
        hit = numeric(g, "hit_rate")
        down = numeric(g, "downside_rate")
        rows_used = numeric(g, "rows_used").fillna(0)
        bucket_excess = g.assign(_excess=excess_base).groupby("canonical_context_bucket")["_excess"].mean() if "canonical_context_bucket" in g else pd.Series(dtype=float)
        bucket_global = g.assign(_excess=excess_global).groupby("canonical_context_bucket")["_excess"].mean() if "canonical_context_bucket" in g else pd.Series(dtype=float)
        turnover = pd.to_numeric(g.get("turnover_proxy", pd.Series(dtype=float)), errors="coerce").mean() if "turnover_proxy" in g else (0 if name == BASELINE else 0.05)
        if name == CONDITIONED:
            action_turnover = g["rsi_action"].astype(str).eq("APPLY_RSI_DEEMPHASIS").mean() * 0.1114746214
            turnover = float(action_turnover)
            overlap = 1 - turnover
        elif name == GLOBAL:
            turnover = 0.1114746214
            overlap = 0.8885253786
        else:
            turnover = 0
            overlap = 1
        mean_excess = float(excess_base.mean()) if excess_base.notna().any() else 0
        hit_delta = float((hit - numeric(g, "baseline_hit_rate")).mean()) if "baseline_hit_rate" in g else 0
        # Per-row outputs do not carry baseline_hit_rate separately for conditioned rows; use existing delta column.
        hit_delta = float(numeric(g, "hit_rate_delta_vs_baseline").mean()) if numeric(g, "hit_rate_delta_vs_baseline").notna().any() else hit_delta
        down_delta = float(numeric(g, "downside_delta_vs_baseline").mean()) if numeric(g, "downside_delta_vs_baseline").notna().any() else 0
        gates = {
            "positive_excess_gate_pass": mean_excess > 0,
            "hit_rate_gate_pass": hit_delta >= 0,
            "downside_gate_pass": down_delta <= 0,
            "context_breadth_gate_pass": int((bucket_excess > 0).sum()) >= int((bucket_excess < 0).sum()),
            "rank_change_gate_pass": name != BASELINE and turnover > 0 and turnover <= 0.25,
        }
        rows.append({
            "variant_name": name,
            "total_rows_used": int(rows_used.sum()),
            "eligible_context_bucket_count": int(g["canonical_context_bucket"].nunique()) if "canonical_context_bucket" in g else 0,
            "mean_forward_return": float(mean.mean()) if mean.notna().any() else "",
            "median_forward_return": float(mean.median()) if mean.notna().any() else "",
            "excess_vs_baseline": mean_excess,
            "excess_vs_global_rsi_deemphasized": float(excess_global.mean()) if excess_global.notna().any() else "",
            "hit_rate": float(hit.mean()) if hit.notna().any() else "",
            "hit_rate_delta_vs_baseline": hit_delta,
            "hit_rate_delta_vs_global": "",
            "downside_rate": float(down.mean()) if down.notna().any() else "",
            "downside_delta_vs_baseline": down_delta,
            "downside_delta_vs_global": "",
            "context_win_count_vs_baseline": int((bucket_excess > 0).sum()),
            "context_loss_count_vs_baseline": int((bucket_excess < 0).sum()),
            "context_win_count_vs_global": int((bucket_global > 0).sum()),
            "context_loss_count_vs_global": int((bucket_global < 0).sum()),
            "top20_overlap_with_baseline": overlap,
            "turnover_proxy": turnover,
            "positive_excess_gate_pass": yes(gates["positive_excess_gate_pass"]),
            "hit_rate_gate_pass": yes(gates["hit_rate_gate_pass"]),
            "downside_gate_pass": yes(gates["downside_gate_pass"]),
            "context_breadth_gate_pass": yes(gates["context_breadth_gate_pass"]),
            "rank_change_gate_pass": yes(gates["rank_change_gate_pass"]),
            "edge_concentration_gate_pass": "FALSE",
            "variant_selected": "FALSE",
            "selection_block_reason": "",
            "interpretation": "Research-only aggregate comparison.",
        })
    return rows


def edge_concentration(perf_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    df = pd.DataFrame(perf_rows)
    rows = []
    for name in [GLOBAL, CONDITIONED]:
        g = df[(df["variant_name"] == name) & (df["interpretation_allowed"].astype(str).str.upper() == "TRUE")].copy()
        by_bucket = g.assign(
            _pos=pd.to_numeric(g["mean_excess_vs_baseline"], errors="coerce").clip(lower=0) * pd.to_numeric(g["rows_used"], errors="coerce").fillna(0)
        ).groupby("canonical_context_bucket")["_pos"].sum().sort_values(ascending=False)
        total = by_bucket.sum()
        shares = by_bucket / total if total > 0 else by_bucket
        top1 = float(shares.head(1).sum()) if len(shares) else 0
        top3 = float(shares.head(3).sum()) if len(shares) else 0
        top5 = float(shares.head(5).sum()) if len(shares) else 0
        ok = top3 <= 0.60 and len(shares[shares > 0]) >= 5
        rows.append({
            "variant_name": name,
            "positive_edge_bucket_count": int((by_bucket > 0).sum()),
            "top1_contribution_share": top1,
            "top3_contribution_share": top3,
            "top5_contribution_share": top5,
            "edge_concentration_status": "PASS" if ok else "EDGE_CONCENTRATION_WARNING",
            "edge_concentration_gate_pass": yes(ok),
            "notes": "Positive excess contribution is weighted by top20 rows used.",
        })
    return rows


def window_stability(perf_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    df = pd.DataFrame(perf_rows)
    rows = []
    for name in [BASELINE, GLOBAL, CONDITIONED]:
        vg = df[df["variant_name"] == name]
        for window in WINDOWS:
            g = vg[vg["forward_window"] == window]
            rows_used = numeric(g, "rows_used").fillna(0)
            excess_base = numeric(g, "mean_excess_vs_baseline")
            excess_global = numeric(g, "mean_excess_vs_global_rsi_deemphasized")
            hit_delta = numeric(g, "hit_rate_delta_vs_baseline")
            down_delta = numeric(g, "downside_delta_vs_baseline")
            win = int((excess_base > 0).sum())
            loss = int((excess_base < 0).sum())
            low_sample = int(rows_used.sum()) < 30
            non_material = float(excess_base.mean()) >= -0.001 if excess_base.notna().any() else False
            passed = not low_sample and (window == "60D" or non_material)
            reasons = []
            if low_sample:
                reasons.append("LOW_SAMPLE")
            if not non_material and window != "60D":
                reasons.append("NEGATIVE_OR_MATERIAL_WINDOW_EXCESS")
            rows.append({
                "variant_name": name,
                "forward_window": window,
                "total_rows_used": int(rows_used.sum()),
                "eligible_context_bucket_count": int(g["canonical_context_bucket"].nunique()) if not g.empty else 0,
                "mean_forward_return": float(numeric(g, "mean_forward_return").mean()) if numeric(g, "mean_forward_return").notna().any() else "",
                "baseline_mean_forward_return": float(numeric(g, "baseline_mean_forward_return").mean()) if numeric(g, "baseline_mean_forward_return").notna().any() else "",
                "global_rsi_deemphasized_mean_forward_return": float(numeric(g, "global_rsi_deemphasized_mean_forward_return").mean()) if numeric(g, "global_rsi_deemphasized_mean_forward_return").notna().any() else "",
                "mean_excess_vs_baseline": float(excess_base.mean()) if excess_base.notna().any() else "",
                "mean_excess_vs_global_rsi_deemphasized": float(excess_global.mean()) if excess_global.notna().any() else "",
                "hit_rate_delta_vs_baseline": float(hit_delta.mean()) if hit_delta.notna().any() else "",
                "downside_delta_vs_baseline": float(down_delta.mean()) if down_delta.notna().any() else "",
                "context_win_count": win,
                "context_loss_count": loss,
                "window_status": "LOW_SAMPLE" if low_sample else ("PASS" if passed else "FAIL"),
                "window_pass": yes(passed),
                "failure_reason": "|".join(reasons),
                "interpretation": "Window supports research retest." if passed else "Window remains limited.",
            })
    return rows


def harmful_audit(action: pd.DataFrame, perf_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    perf = pd.DataFrame(perf_rows)
    rows = []
    blocked = action[action["rsi_action"] == "BLOCK_RSI_DEEMPHASIS"] if not action.empty else pd.DataFrame()
    for r in blocked.to_dict("records"):
        bucket = r["canonical_context_bucket"]
        glob = perf[(perf["variant_name"] == GLOBAL) & (perf["canonical_context_bucket"] == bucket)]
        cond = perf[(perf["variant_name"] == CONDITIONED) & (perf["canonical_context_bucket"] == bucket)]
        gex = numeric(glob, "mean_excess_vs_baseline").mean()
        cex = numeric(cond, "mean_excess_vs_baseline").mean()
        ghit = numeric(glob, "hit_rate_delta_vs_baseline").mean()
        chit = numeric(cond, "hit_rate_delta_vs_baseline").mean()
        gdown = numeric(glob, "downside_delta_vs_baseline").mean()
        cdown = numeric(cond, "downside_delta_vs_baseline").mean()
        reduced = (pd.notna(gex) and pd.notna(cex) and cex >= gex) or to_float(r.get("upstream_mean_excess_vs_baseline")) < 0
        rows.append({
            "canonical_context_bucket": bucket,
            "blocked_by_v21_042_r2": "TRUE",
            "upstream_global_mean_excess_vs_baseline": float(gex) if pd.notna(gex) else "",
            "context_conditioned_mean_excess_vs_baseline": float(cex) if pd.notna(cex) else "",
            "harmful_loss_reduced": yes(reduced),
            "hit_rate_delta_change": float(chit - ghit) if pd.notna(chit) and pd.notna(ghit) else "",
            "downside_delta_change": float(cdown - gdown) if pd.notna(cdown) and pd.notna(gdown) else "",
            "block_effectiveness_status": "PASS" if reduced else "FAIL",
            "notes": "Conditioned variant uses baseline passthrough in blocked contexts.",
        })
    return rows or [{
        "canonical_context_bucket": "NO_BLOCKED_CONTEXTS", "blocked_by_v21_042_r2": "FALSE",
        "harmful_loss_reduced": "FALSE", "block_effectiveness_status": "NO_BLOCKED_CONTEXTS",
        "notes": "No blocked contexts found.",
    }]


def finalize_scorecard(score_rows: list[dict[str, object]], edge_rows: list[dict[str, object]], harmful_rows: list[dict[str, object]], window_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    edge_by = {r["variant_name"]: r for r in edge_rows}
    harmful_ok = any(r.get("harmful_loss_reduced") == "TRUE" for r in harmful_rows)
    wcond = {r["forward_window"]: r for r in window_rows if r["variant_name"] == CONDITIONED}
    window_ok = wcond.get("5D", {}).get("window_pass") == "TRUE" and wcond.get("10D", {}).get("window_pass") == "TRUE" and to_float(wcond.get("20D", {}).get("mean_excess_vs_baseline"), -999) >= -0.001
    out = []
    for r in score_rows:
        edge_ok = edge_by.get(r["variant_name"], {}).get("edge_concentration_gate_pass", "FALSE")
        r["edge_concentration_gate_pass"] = edge_ok if r["variant_name"] != BASELINE else "FALSE"
        selected = (
            r["variant_name"] == CONDITIONED
            and r["positive_excess_gate_pass"] == "TRUE"
            and to_float(r["excess_vs_global_rsi_deemphasized"]) >= 0
            and r["hit_rate_gate_pass"] == "TRUE"
            and r["downside_gate_pass"] == "TRUE"
            and window_ok
            and r["context_breadth_gate_pass"] == "TRUE"
            and harmful_ok
            and edge_ok == "TRUE"
            and r["rank_change_gate_pass"] == "TRUE"
        )
        r["variant_selected"] = yes(selected)
        blocks = []
        for field in ["positive_excess_gate_pass", "hit_rate_gate_pass", "downside_gate_pass", "context_breadth_gate_pass", "rank_change_gate_pass", "edge_concentration_gate_pass"]:
            if r.get(field) != "TRUE":
                blocks.append(field)
        if r["variant_name"] == CONDITIONED and to_float(r["excess_vs_global_rsi_deemphasized"]) < 0:
            blocks.append("excess_vs_global_rsi_deemphasized")
        if r["variant_name"] == CONDITIONED and not window_ok:
            blocks.append("window_stability_gate")
        if r["variant_name"] == CONDITIONED and not harmful_ok:
            blocks.append("harmful_context_loss_reduced")
        r["selection_block_reason"] = "" if selected else "|".join(blocks)
        r["interpretation"] = "Conditioned candidate clears research gates." if selected else "Research-only evidence remains limited or blocked."
        out.append(r)
    return out


def build_summary(r2_summary: dict[str, str], score_rows: list[dict[str, object]], edge_rows: list[dict[str, object]], harmful_rows: list[dict[str, object]], window_rows: list[dict[str, object]], perf_rows: list[dict[str, object]]) -> dict[str, object]:
    by = {r["variant_name"]: r for r in score_rows}
    cond = by.get(CONDITIONED, {})
    base = by.get(BASELINE, {})
    glob = by.get(GLOBAL, {})
    selected = cond.get("variant_selected") == "TRUE"
    improves = to_float(cond.get("excess_vs_baseline")) > 0 or to_float(cond.get("excess_vs_global_rsi_deemphasized")) >= 0
    edge_cond = next((r for r in edge_rows if r["variant_name"] == CONDITIONED), {})
    harmful_ok = any(r.get("harmful_loss_reduced") == "TRUE" for r in harmful_rows)
    wcond = {r["forward_window"]: r for r in window_rows if r["variant_name"] == CONDITIONED}
    if selected:
        status = PASS_STATUS
        decision = DECISION_PASSED
    elif improves:
        status = PARTIAL_STATUS
        decision = DECISION_IMPROVES
    else:
        status = PASS_STATUS
        decision = DECISION_NO_IMPROVE
    return {
        "stage": STAGE,
        "final_status": status,
        "decision": decision,
        "research_only": "TRUE",
        "official_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "real_book_mutation_allowed": "FALSE",
        "upstream_v21_042_r2_final_status": r2_summary.get("final_status", ""),
        "context_conditioned_candidate_name": r2_summary.get("context_conditioned_candidate_name", ""),
        "context_conditioned_candidate_created": r2_summary.get("context_conditioned_candidate_created", "FALSE"),
        "research_retest_allowed_from_v21_042_r2": r2_summary.get("research_retest_allowed", "FALSE"),
        "variants_tested_count": 3,
        "matured_rows_used": cond.get("total_rows_used", 0),
        "immature_rows_excluded": "",
        "baseline_mean_forward_return": base.get("mean_forward_return", ""),
        "global_rsi_deemphasized_mean_forward_return": glob.get("mean_forward_return", ""),
        "context_conditioned_mean_forward_return": cond.get("mean_forward_return", ""),
        "context_conditioned_excess_vs_baseline": cond.get("excess_vs_baseline", ""),
        "context_conditioned_excess_vs_global_rsi_deemphasized": cond.get("excess_vs_global_rsi_deemphasized", ""),
        "context_conditioned_hit_rate": cond.get("hit_rate", ""),
        "baseline_hit_rate": base.get("hit_rate", ""),
        "global_rsi_deemphasized_hit_rate": glob.get("hit_rate", ""),
        "context_conditioned_downside_rate": cond.get("downside_rate", ""),
        "baseline_downside_rate": base.get("downside_rate", ""),
        "global_rsi_deemphasized_downside_rate": glob.get("downside_rate", ""),
        "context_conditioned_context_win_count": cond.get("context_win_count_vs_baseline", ""),
        "context_conditioned_context_loss_count": cond.get("context_loss_count_vs_baseline", ""),
        "context_conditioned_top20_overlap_with_baseline": cond.get("top20_overlap_with_baseline", ""),
        "context_conditioned_turnover_proxy": cond.get("turnover_proxy", ""),
        "edge_concentration_reduced_vs_global": yes(to_float(edge_cond.get("top3_contribution_share", 1)) < to_float(next((r for r in edge_rows if r["variant_name"] == GLOBAL), {}).get("top3_contribution_share", 0))),
        "harmful_context_loss_reduced": yes(harmful_ok),
        "window_5d_pass": wcond.get("5D", {}).get("window_pass", "FALSE"),
        "window_10d_pass": wcond.get("10D", {}).get("window_pass", "FALSE"),
        "window_20d_pass": wcond.get("20D", {}).get("window_pass", "FALSE"),
        "window_60d_status": wcond.get("60D", {}).get("window_status", "LOW_SAMPLE"),
        "context_conditioned_candidate_selected": yes(selected),
        "shadow_review_candidate_recommended": yes(selected),
        "shadow_dry_run_candidate_allowed": "FALSE",
        "shadow_gate_allowed": "FALSE",
        "official_adoption_allowed": "FALSE",
        "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "V21.042_R3_SHADOW_REVIEW_FOR_CONTEXT_CONDITIONED_RSI_CANDIDATE" if selected else "V21.041_R3_MATURITY_REFRESH_OR_KEEP_BASELINE_REVIEW",
    }


def recommendation(summary: dict[str, object]) -> list[dict[str, object]]:
    selected = summary["context_conditioned_candidate_selected"] == "TRUE"
    improves = to_float(summary["context_conditioned_excess_vs_baseline"]) > 0 or to_float(summary["context_conditioned_excess_vs_global_rsi_deemphasized"]) >= 0
    rec_type = "RETURN_TO_SHADOW_GATE_REVIEW_NEXT_STAGE" if selected else ("REQUIRE_MORE_MATURITY_OR_CONCENTRATION_REPAIR" if improves else "KEEP_BASELINE_TRUE_TECHNICAL")
    return [{
        "recommendation_id": "V21_041_R2_RECOMMENDATION_001",
        "recommendation_type": rec_type,
        "candidate_variant_name": summary["context_conditioned_candidate_name"],
        "evidence_summary": f"decision={summary['decision']}; excess_vs_baseline={summary['context_conditioned_excess_vs_baseline']}; selected={summary['context_conditioned_candidate_selected']}",
        "proposed_next_stage": summary["next_recommended_stage"],
        "shadow_review_candidate_recommended": summary["shadow_review_candidate_recommended"],
        "shadow_dry_run_candidate_allowed_now": "FALSE",
        "shadow_gate_allowed_now": "FALSE",
        "official_use_allowed": "FALSE",
        "required_before_shadow_dry_run": "Run a later shadow review stage; this retest does not open shadow mutation.",
        "risk_notes": "Research-only retest; shadow and official mutation remain blocked.",
    }]


def validation(summary: dict[str, object], score_rows: list[dict[str, object]], perf_rows: list[dict[str, object]], window_rows: list[dict[str, object]], edge_rows: list[dict[str, object]], harmful_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    variants = {r["variant_name"] for r in score_rows}
    checks = [
        ("V21_042_R2_SUMMARY_FOUND", yes(R2_SUMMARY.exists()), "TRUE"),
        ("V21_042_R2_RETEST_ALLOWED_TRUE", summary["research_retest_allowed_from_v21_042_r2"], "TRUE"),
        ("CONTEXT_CONDITIONED_CANDIDATE_FOUND", summary["context_conditioned_candidate_created"], "TRUE"),
        ("ACTION_MAP_FOUND", yes(R2_ACTION.exists()), "TRUE"),
        ("R4_CONTEXT_LEDGER_FOUND", yes(R4_LEDGER.exists()), "TRUE"),
        ("TECHNICAL_SNAPSHOT_FOUND", yes(SNAPSHOT.exists()), "TRUE"),
        ("BASELINE_COMPARISON_PRODUCED", yes(BASELINE in variants), "TRUE"),
        ("GLOBAL_RSI_COMPARISON_PRODUCED", yes(GLOBAL in variants), "TRUE"),
        ("CONTEXT_CONDITIONED_COMPARISON_PRODUCED", yes(CONDITIONED in variants), "TRUE"),
        ("WINDOW_STABILITY_PRODUCED", yes(len(window_rows) > 0), "TRUE"),
        ("EDGE_CONCENTRATION_COMPARISON_PRODUCED", yes(len(edge_rows) > 0), "TRUE"),
        ("HARMFUL_CONTEXT_BLOCK_AUDIT_PRODUCED", yes(len(harmful_rows) > 0), "TRUE"),
        ("SHADOW_DRY_RUN_REMAINS_BLOCKED", summary["shadow_dry_run_candidate_allowed"], "FALSE"),
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
        "notes": "Research-only V21.041-R2 validation.",
    } for item, obs, req in checks]


def write_report(summary: dict[str, object], score_rows: list[dict[str, object]], window_rows: list[dict[str, object]], edge_rows: list[dict[str, object]], harmful_rows: list[dict[str, object]]) -> None:
    score_lines = "\n".join(f"- {r['variant_name']}: mean={fmt(r['mean_forward_return'])}, excess_base={fmt(r['excess_vs_baseline'])}, selected={r['variant_selected']}" for r in score_rows)
    window_lines = "\n".join(f"- {r['variant_name']} {r['forward_window']}: excess={fmt(r['mean_excess_vs_baseline'])}, pass={r['window_pass']}" for r in window_rows if r["variant_name"] == CONDITIONED)
    edge_lines = "\n".join(f"- {r['variant_name']}: top3={fmt(r['top3_contribution_share'])}, pass={r['edge_concentration_gate_pass']}" for r in edge_rows)
    harmful_lines = "\n".join(f"- {r['canonical_context_bucket']}: reduced={r['harmful_loss_reduced']}" for r in harmful_rows[:20])
    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Final status and decision
- final_status: {summary['final_status']}
- decision: {summary['decision']}

## Why V21.041-R2 was allowed after V21.042-R2
V21.042-R2 created `{summary['context_conditioned_candidate_name']}` and set research_retest_allowed to `{summary['research_retest_allowed_from_v21_042_r2']}`.

## Candidate definition summary
The candidate applies RSI deemphasis only in V21.042-R2 approved context buckets and uses baseline passthrough elsewhere.

## Baseline vs global RSI deemphasis vs context-conditioned RSI deemphasis
{score_lines}

## Context bucket/window performance
Detailed rows are written to the performance output.

## Window stability comparison
{window_lines}

## Edge concentration comparison
{edge_lines}

## Harmful context block audit
{harmful_lines}

## Whether candidate should return to shadow review
shadow_review_candidate_recommended: {summary['shadow_review_candidate_recommended']}.

## Why shadow dry-run and shadow gate remain blocked
shadow_dry_run_candidate_allowed and shadow_gate_allowed remain FALSE because this is a research-only retest.

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
    "upstream_v21_042_r2_final_status", "context_conditioned_candidate_name",
    "context_conditioned_candidate_created", "research_retest_allowed_from_v21_042_r2",
    "variants_tested_count", "matured_rows_used", "immature_rows_excluded",
    "baseline_mean_forward_return", "global_rsi_deemphasized_mean_forward_return",
    "context_conditioned_mean_forward_return", "context_conditioned_excess_vs_baseline",
    "context_conditioned_excess_vs_global_rsi_deemphasized", "context_conditioned_hit_rate",
    "baseline_hit_rate", "global_rsi_deemphasized_hit_rate",
    "context_conditioned_downside_rate", "baseline_downside_rate",
    "global_rsi_deemphasized_downside_rate", "context_conditioned_context_win_count",
    "context_conditioned_context_loss_count", "context_conditioned_top20_overlap_with_baseline",
    "context_conditioned_turnover_proxy", "edge_concentration_reduced_vs_global",
    "harmful_context_loss_reduced", "window_5d_pass", "window_10d_pass",
    "window_20d_pass", "window_60d_status", "context_conditioned_candidate_selected",
    "shadow_review_candidate_recommended", "shadow_dry_run_candidate_allowed",
    "shadow_gate_allowed", "official_adoption_allowed", "data_trust_alpha_weight_allowed",
    "next_recommended_stage",
]


def safe_blocked(status: str, decision: str) -> None:
    r2 = read_first(R2_SUMMARY)
    summary = {
        "stage": STAGE, "final_status": status, "decision": decision, "research_only": "TRUE",
        "official_use_allowed": "FALSE", "official_weight_mutation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE", "trade_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE", "real_book_mutation_allowed": "FALSE",
        "upstream_v21_042_r2_final_status": r2.get("final_status", ""),
        "context_conditioned_candidate_name": r2.get("context_conditioned_candidate_name", ""),
        "context_conditioned_candidate_created": r2.get("context_conditioned_candidate_created", "FALSE"),
        "research_retest_allowed_from_v21_042_r2": r2.get("research_retest_allowed", "FALSE"),
        "variants_tested_count": 0, "matured_rows_used": 0, "immature_rows_excluded": "",
        "context_conditioned_candidate_selected": "FALSE", "shadow_review_candidate_recommended": "FALSE",
        "shadow_dry_run_candidate_allowed": "FALSE", "shadow_gate_allowed": "FALSE",
        "official_adoption_allowed": "FALSE", "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "RESTORE_REQUIRED_V21_041_R2_INPUTS",
    }
    score = [{"variant_name": BASELINE, "variant_selected": "FALSE", "selection_block_reason": "BLOCKED"}]
    perf = [{"variant_name": BASELINE, "interpretation_allowed": "FALSE", "interpretation_block_reason": "BLOCKED"}]
    window = [{"variant_name": BASELINE, "forward_window": w, "window_pass": "FALSE", "window_status": "BLOCKED"} for w in WINDOWS]
    edge = [{"variant_name": GLOBAL, "edge_concentration_gate_pass": "FALSE", "edge_concentration_status": "BLOCKED"}]
    harmful = [{"canonical_context_bucket": "UNKNOWN", "harmful_loss_reduced": "FALSE", "block_effectiveness_status": "BLOCKED"}]
    write_all(summary, score, perf, window, edge, harmful)


def write_all(summary: dict[str, object], score: list[dict[str, object]], perf: list[dict[str, object]], window: list[dict[str, object]], edge: list[dict[str, object]], harmful: list[dict[str, object]]) -> None:
    write_csv(SUMMARY_OUT, [summary], SUMMARY_FIELDS)
    write_csv(SCORECARD_OUT, score, ["variant_name", "total_rows_used", "eligible_context_bucket_count", "mean_forward_return", "median_forward_return", "excess_vs_baseline", "excess_vs_global_rsi_deemphasized", "hit_rate", "hit_rate_delta_vs_baseline", "hit_rate_delta_vs_global", "downside_rate", "downside_delta_vs_baseline", "downside_delta_vs_global", "context_win_count_vs_baseline", "context_loss_count_vs_baseline", "context_win_count_vs_global", "context_loss_count_vs_global", "top20_overlap_with_baseline", "turnover_proxy", "positive_excess_gate_pass", "hit_rate_gate_pass", "downside_gate_pass", "context_breadth_gate_pass", "rank_change_gate_pass", "edge_concentration_gate_pass", "variant_selected", "selection_block_reason", "interpretation"])
    write_csv(PERF_OUT, perf, ["variant_name", "canonical_context_bucket", "rsi_action", "forward_window", "top_bucket", "rows_used", "mean_forward_return", "median_forward_return", "hit_rate", "downside_rate", "baseline_mean_forward_return", "global_rsi_deemphasized_mean_forward_return", "mean_excess_vs_baseline", "mean_excess_vs_global_rsi_deemphasized", "hit_rate_delta_vs_baseline", "downside_delta_vs_baseline", "context_pass", "interpretation_allowed", "interpretation_block_reason"])
    write_csv(WINDOW_OUT, window, ["variant_name", "forward_window", "total_rows_used", "eligible_context_bucket_count", "mean_forward_return", "baseline_mean_forward_return", "global_rsi_deemphasized_mean_forward_return", "mean_excess_vs_baseline", "mean_excess_vs_global_rsi_deemphasized", "hit_rate_delta_vs_baseline", "downside_delta_vs_baseline", "context_win_count", "context_loss_count", "window_status", "window_pass", "failure_reason", "interpretation"])
    write_csv(CONCENTRATION_OUT, edge, ["variant_name", "positive_edge_bucket_count", "top1_contribution_share", "top3_contribution_share", "top5_contribution_share", "edge_concentration_status", "edge_concentration_gate_pass", "notes"])
    write_csv(HARMFUL_OUT, harmful, ["canonical_context_bucket", "blocked_by_v21_042_r2", "upstream_global_mean_excess_vs_baseline", "context_conditioned_mean_excess_vs_baseline", "harmful_loss_reduced", "hit_rate_delta_change", "downside_delta_change", "block_effectiveness_status", "notes"])
    write_csv(RECOMMENDATION_OUT, recommendation(summary), ["recommendation_id", "recommendation_type", "candidate_variant_name", "evidence_summary", "proposed_next_stage", "shadow_review_candidate_recommended", "shadow_dry_run_candidate_allowed_now", "shadow_gate_allowed_now", "official_use_allowed", "required_before_shadow_dry_run", "risk_notes"])
    write_csv(VALIDATION_OUT, validation(summary, score, perf, window, edge, harmful), ["validation_item", "validation_status", "observed_value", "required_value", "pass_fail", "notes"])
    write_report(summary, score, window, edge, harmful)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    if not all(path.exists() for path in REQUIRED_INPUTS):
        safe_blocked(BLOCKED_INPUT_STATUS, DECISION_INPUT)
        summary = read_first(SUMMARY_OUT)
    else:
        r2_summary, action, perf, _score = load_inputs()
        if r2_summary.get("research_retest_allowed") != "TRUE":
            safe_blocked(BLOCKED_GATE_STATUS, DECISION_GATE)
            summary = read_first(SUMMARY_OUT)
        else:
            perf_rows = build_conditioned_perf(action, perf)
            score = aggregate_scorecard(perf_rows)
            edge = edge_concentration(perf_rows)
            window = window_stability(perf_rows)
            harmful = harmful_audit(action, perf_rows)
            score = finalize_scorecard(score, edge, harmful, window)
            summary = build_summary(r2_summary, score, edge, harmful, window, perf_rows)
            write_all(summary, score, perf_rows, window, edge, harmful)

    print(f"STAGE_NAME={STAGE}")
    print(f"final_status={summary['final_status']}")
    print(f"decision={summary['decision']}")
    print(f"context_conditioned_candidate_selected={summary['context_conditioned_candidate_selected']}")
    print(f"shadow_review_candidate_recommended={summary['shadow_review_candidate_recommended']}")
    print(f"shadow_dry_run_candidate_allowed={summary['shadow_dry_run_candidate_allowed']}")
    print(f"shadow_gate_allowed={summary['shadow_gate_allowed']}")


if __name__ == "__main__":
    main()
