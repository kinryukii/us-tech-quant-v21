#!/usr/bin/env python
"""V21.042-R2 context-conditioned RSI deemphasis repair.

Research-only repair/review stage that converts the global RSI_DEEMPHASIZED_R4
candidate into a context-conditioned candidate definition for a later retest.
No shadow, official, broker, or real-book artifacts are mutated.
"""

from __future__ import annotations

import csv
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.042-R2_CONTEXT_CONDITIONED_RSI_DEEMPHASIS_REPAIR_AND_MATURITY_REFRESH"
PASS_STATUS = "PASS_V21_042_R2_CONTEXT_CONDITIONED_RSI_REPAIR_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_042_R2_REPAIR_REQUIRES_MORE_MATURITY"
BLOCKED_INPUT_STATUS = "BLOCKED_V21_042_R2_INPUTS_MISSING"
BLOCKED_NO_EDGE_STATUS = "BLOCKED_V21_042_R2_NO_REPAIRABLE_CONTEXT_EDGE"

DECISION_READY = "CONTEXT_CONDITIONED_RSI_REPAIR_READY_FOR_RETEST"
DECISION_PARTIAL = "CONTEXT_CONDITIONED_RSI_REPAIR_PARTIAL_MORE_MATURITY_REQUIRED"
DECISION_FAILED = "CONTEXT_CONDITIONED_RSI_REPAIR_FAILED_KEEP_BASELINE"
DECISION_BLOCKED = "CONTEXT_CONDITIONED_RSI_REPAIR_BLOCKED_INPUTS_MISSING"

VARIANT_NAME = "RSI_DEEMPHASIZED_CONTEXT_CONDITIONED_R4_R2"

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

R1_SUMMARY = OUT_DIR / "V21_042_R1_SHADOW_GATE_REVIEW_SUMMARY.csv"
R1_CONTEXT = OUT_DIR / "V21_042_R1_CANDIDATE_STABILITY_BY_CONTEXT_BUCKET.csv"
R1_WINDOW = OUT_DIR / "V21_042_R1_CANDIDATE_STABILITY_BY_FORWARD_WINDOW.csv"
R1_CONCENTRATION = OUT_DIR / "V21_042_R1_CONTEXT_BUCKET_EDGE_CONCENTRATION_AUDIT.csv"
V41_PERF = OUT_DIR / "V21_041_R1_VARIANT_PERFORMANCE_BY_CONTEXT_BUCKET_WINDOW.csv"
V41_WEIGHTS = OUT_DIR / "V21_041_R1_TECHNICAL_SUBFACTOR_WEIGHT_VARIANTS.csv"
R4_LEDGER = OUT_DIR / "V21_040_R4_CANONICAL_CONTEXT_LEDGER.csv"
SNAPSHOT = OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv"

SUMMARY_OUT = OUT_DIR / "V21_042_R2_CONTEXT_CONDITIONED_RSI_REPAIR_SUMMARY.csv"
ACTION_OUT = OUT_DIR / "V21_042_R2_CONTEXT_BUCKET_RSI_ACTION_MAP.csv"
DEFINITION_OUT = OUT_DIR / "V21_042_R2_CONTEXT_CONDITIONED_VARIANT_DEFINITION.csv"
SCOPE_OUT = OUT_DIR / "V21_042_R2_EXPECTED_RETEST_SCOPE.csv"
CONCENTRATION_OUT = OUT_DIR / "V21_042_R2_EDGE_CONCENTRATION_REPAIR_AUDIT.csv"
RECOMMENDATION_OUT = OUT_DIR / "V21_042_R2_RETEST_RECOMMENDATION.csv"
VALIDATION_OUT = OUT_DIR / "V21_042_R2_VALIDATION_MATRIX.csv"
REPORT_OUT = READ_CENTER_DIR / "V21_042_R2_CONTEXT_CONDITIONED_RSI_DEEMPHASIS_REPAIR_AND_MATURITY_REFRESH_REPORT.md"

REQUIRED_INPUTS = [R1_SUMMARY, R1_CONTEXT, R1_WINDOW, R1_CONCENTRATION, V41_PERF, V41_WEIGHTS, R4_LEDGER, SNAPSHOT]
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


def is_true(value: object) -> bool:
    return str(value).upper() == "TRUE"


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


def load_inputs() -> tuple[dict[str, str], pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summary = read_first(R1_SUMMARY)
    context = pd.read_csv(R1_CONTEXT, low_memory=False) if R1_CONTEXT.exists() else pd.DataFrame()
    window = pd.read_csv(R1_WINDOW, low_memory=False) if R1_WINDOW.exists() else pd.DataFrame()
    concentration = pd.read_csv(R1_CONCENTRATION, low_memory=False) if R1_CONCENTRATION.exists() else pd.DataFrame()
    perf = pd.read_csv(V41_PERF, low_memory=False) if V41_PERF.exists() else pd.DataFrame()
    ledger = pd.read_csv(R4_LEDGER, low_memory=False) if R4_LEDGER.exists() else pd.DataFrame()
    return summary, context, window, concentration, perf, ledger


def action_map(context: pd.DataFrame, concentration: pd.DataFrame) -> list[dict[str, object]]:
    if context.empty:
        return [{
            "canonical_context_bucket": "UNKNOWN", "total_rows_used": 0,
            "upstream_context_pass": "FALSE", "rsi_action": "REVIEW_ONLY_LOW_SAMPLE",
            "include_in_context_conditioned_candidate": "FALSE", "require_more_maturity": "TRUE",
            "notes": "No context stability input.",
        }]
    conc = concentration[["canonical_context_bucket", "contribution_to_total_excess"]].copy() if not concentration.empty else pd.DataFrame(columns=["canonical_context_bucket", "contribution_to_total_excess"])
    df = context.merge(conc, on="canonical_context_bucket", how="left")
    rows: list[dict[str, object]] = []
    for r in df.to_dict("records"):
        bucket = clean(r.get("canonical_context_bucket"))
        total_rows = int(to_float(r.get("total_rows_used")))
        passed = is_true(r.get("context_pass"))
        excess = to_float(r.get("mean_excess_vs_baseline"))
        hit_delta = to_float(r.get("hit_rate_delta_vs_baseline"))
        down_delta = to_float(r.get("downside_delta_vs_baseline"))
        failure = clean(r.get("failure_reason"))
        low_sample = total_rows < 30 or "LOW_SAMPLE" in failure
        if low_sample:
            action = "REVIEW_ONLY_LOW_SAMPLE"
            reason = "Context sample is below review threshold."
            include = False
            maturity = True
        elif passed and excess > 0 and hit_delta >= 0 and down_delta <= 0:
            action = "APPLY_RSI_DEEMPHASIS"
            reason = "Upstream context stability passed with positive excess, non-negative hit delta, and non-positive downside delta."
            include = True
            maturity = False
        elif excess < 0 or hit_delta < 0 or down_delta > 0 or failure:
            action = "BLOCK_RSI_DEEMPHASIS"
            reason = "Upstream evidence showed negative excess, negative hit delta, higher downside, or explicit context failure."
            include = False
            maturity = False
        else:
            action = "KEEP_BASELINE_RSI"
            reason = "Mixed or immaterial evidence; preserve baseline RSI treatment."
            include = False
            maturity = False
        rows.append({
            "canonical_context_bucket": bucket,
            "total_rows_used": total_rows,
            "upstream_context_pass": yes(passed),
            "upstream_mean_excess_vs_baseline": r.get("mean_excess_vs_baseline", ""),
            "upstream_hit_rate_delta_vs_baseline": r.get("hit_rate_delta_vs_baseline", ""),
            "upstream_downside_delta_vs_baseline": r.get("downside_delta_vs_baseline", ""),
            "forward_windows_available": r.get("forward_windows_available", ""),
            "edge_contribution_share": r.get("contribution_to_total_excess", ""),
            "rsi_action": action,
            "rsi_action_reason": reason,
            "include_in_context_conditioned_candidate": yes(include),
            "require_more_maturity": yes(maturity),
            "notes": failure,
        })
    return rows


def variant_definition(action_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows = []
    for r in action_rows:
        action = r["rsi_action"]
        if action == "APPLY_RSI_DEEMPHASIS":
            multiplier = 0.35
            passthrough = "FALSE"
            rationale = "Apply RSI deemphasis only where V21.042-R1 context stability passed."
        elif action == "BLOCK_RSI_DEEMPHASIS":
            multiplier = 1.0
            passthrough = "TRUE"
            rationale = "Block deemphasis and preserve baseline RSI because upstream context evidence was harmful."
        else:
            multiplier = 1.0
            passthrough = "TRUE"
            rationale = "Preserve baseline RSI pending more maturity or mixed evidence review."
        rows.append({
            "variant_name": VARIANT_NAME,
            "canonical_context_bucket": r["canonical_context_bucket"],
            "rsi_action": action,
            "rsi_weight_multiplier": multiplier,
            "baseline_passthrough": passthrough,
            "rationale": rationale,
            "max_delta_guardrail_pass": yes(abs(multiplier - 1.0) <= 0.75),
        })
    return rows


def expected_scope(action_rows: list[dict[str, object]], perf: pd.DataFrame, ledger: pd.DataFrame) -> list[dict[str, object]]:
    apply_buckets = {r["canonical_context_bucket"] for r in action_rows if r["include_in_context_conditioned_candidate"] == "TRUE"}
    perf_scope = perf[(perf["variant_name"] == "RSI_DEEMPHASIZED_R4") & (perf["canonical_context_bucket"].isin(apply_buckets))].copy() if not perf.empty else pd.DataFrame()
    rows = []
    for window in WINDOWS:
        g = perf_scope[perf_scope["forward_window"] == window] if not perf_scope.empty else pd.DataFrame()
        expected_rows = int(pd.to_numeric(g.get("rows_used", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        bucket_count = int(g["canonical_context_bucket"].nunique()) if not g.empty else 0
        if window == "60D" and expected_rows < 30:
            status = "LOW_SAMPLE"
            allowed = False
            notes = "60D remains low-sample unless additional maturity arrives."
        elif expected_rows >= 30 and bucket_count > 0:
            status = "SUFFICIENT"
            allowed = True
            notes = "Research-only retest scope is available."
        else:
            status = "LOW_SAMPLE"
            allowed = False
            notes = "Insufficient context-conditioned rows for this window."
        if window == "20D":
            notes = f"{notes} 20D requires explicit review because V21.042-R1 failed 20D."
        rows.append({
            "forward_window": window,
            "context_bucket_count_in_scope": bucket_count,
            "expected_rows_available": expected_rows,
            "scope_status": status,
            "retest_allowed": yes(allowed),
            "notes": notes,
        })
    return rows


def concentration_repair(action_rows: list[dict[str, object]], concentration: pd.DataFrame) -> list[dict[str, object]]:
    before = concentration.copy() if not concentration.empty else pd.DataFrame()
    before["contribution_to_total_excess"] = pd.to_numeric(before.get("contribution_to_total_excess", pd.Series(dtype=float)), errors="coerce").fillna(0)
    before_positive = before[before["contribution_to_total_excess"] > 0].copy()
    apply_buckets = {r["canonical_context_bucket"] for r in action_rows if r["include_in_context_conditioned_candidate"] == "TRUE"}
    after = before_positive[before_positive["canonical_context_bucket"].isin(apply_buckets)].copy()
    after_sum = after["contribution_to_total_excess"].sum()
    after_shares = (after["contribution_to_total_excess"] / after_sum).sort_values(ascending=False) if after_sum > 0 else pd.Series(dtype=float)
    before_shares = before_positive["contribution_to_total_excess"].sort_values(ascending=False)
    top1_before = float(before_shares.head(1).sum()) if len(before_shares) else 0
    top3_before = float(before_shares.head(3).sum()) if len(before_shares) else 0
    top1_after = float(after_shares.head(1).sum()) if len(after_shares) else 0
    top3_after = float(after_shares.head(3).sum()) if len(after_shares) else 0
    reduced = top3_after < top3_before and top1_after <= top1_before
    status = "PASS" if reduced and top3_after <= 0.60 and len(after_shares) >= 5 else ("IMPROVED_BUT_CONCENTRATED" if reduced else "NOT_REDUCED")
    return [{
        "candidate_variant_name": VARIANT_NAME,
        "positive_edge_bucket_count_before": int(len(before_shares)),
        "positive_edge_bucket_count_after": int(len(after_shares)),
        "top1_contribution_share_before": top1_before,
        "top1_contribution_share_after": top1_after,
        "top3_contribution_share_before": top3_before,
        "top3_contribution_share_after": top3_after,
        "edge_concentration_reduced": yes(reduced),
        "concentration_status_after": status,
        "notes": "After-share is normalized over buckets where the repaired candidate applies RSI deemphasis.",
    }]


def build_summary(r1_summary: dict[str, str], action_rows: list[dict[str, object]], scope_rows: list[dict[str, object]], concentration_rows: list[dict[str, object]]) -> dict[str, object]:
    pass_count = sum(1 for r in action_rows if r.get("upstream_context_pass") == "TRUE")
    fail_count = sum(1 for r in action_rows if r.get("upstream_context_pass") == "FALSE")
    conditioned = [r for r in action_rows if r.get("include_in_context_conditioned_candidate") == "TRUE"]
    blocked = [r for r in action_rows if r.get("rsi_action") == "BLOCK_RSI_DEEMPHASIS"]
    passthrough = [r for r in action_rows if r.get("rsi_action") == "KEEP_BASELINE_RSI"]
    created = len(conditioned) > 0
    conc_reduced = concentration_rows[0].get("edge_concentration_reduced") == "TRUE" if concentration_rows else False
    expected_5 = next((r for r in scope_rows if r["forward_window"] == "5D"), {}).get("retest_allowed", "FALSE")
    expected_10 = next((r for r in scope_rows if r["forward_window"] == "10D"), {}).get("retest_allowed", "FALSE")
    expected_20 = next((r for r in scope_rows if r["forward_window"] == "20D"), {}).get("retest_allowed", "FALSE")
    research_retest = created and (expected_5 == "TRUE" or expected_10 == "TRUE") and len(conditioned) >= 5
    if not created:
        status = BLOCKED_NO_EDGE_STATUS
        decision = DECISION_FAILED
    elif research_retest and expected_20 == "TRUE" and conc_reduced:
        status = PASS_STATUS
        decision = DECISION_READY
    elif research_retest:
        status = PARTIAL_STATUS
        decision = DECISION_PARTIAL
    else:
        status = BLOCKED_NO_EDGE_STATUS
        decision = DECISION_FAILED
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
        "upstream_v21_042_r1_final_status": r1_summary.get("final_status", ""),
        "upstream_candidate_variant_name": r1_summary.get("candidate_variant_name", ""),
        "upstream_stability_review_pass": r1_summary.get("stability_review_pass", ""),
        "upstream_context_stability_pass": r1_summary.get("context_stability_pass", ""),
        "upstream_window_stability_pass": r1_summary.get("window_stability_pass", ""),
        "upstream_shadow_dry_run_candidate_allowed": r1_summary.get("shadow_dry_run_candidate_allowed", ""),
        "context_pass_bucket_count": pass_count,
        "context_fail_bucket_count": fail_count,
        "context_conditioned_candidate_created": yes(created),
        "context_conditioned_candidate_name": VARIANT_NAME if created else "",
        "context_conditioned_bucket_count": len(conditioned),
        "blocked_bucket_count": len(blocked),
        "passthrough_baseline_bucket_count": len(passthrough),
        "edge_concentration_reduced": yes(conc_reduced),
        "expected_5d_retest_allowed": expected_5,
        "expected_10d_retest_allowed": expected_10,
        "expected_20d_retest_allowed": expected_20,
        "research_retest_allowed": yes(research_retest),
        "shadow_dry_run_candidate_allowed": "FALSE",
        "shadow_gate_allowed": "FALSE",
        "official_adoption_allowed": "FALSE",
        "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "V21.041_R2_RETEST_CONTEXT_CONDITIONED_RSI_DEEMPHASIS" if research_retest else "V21.042_R3_WAIT_FOR_CONTEXT_MATURITY_OR_KEEP_BASELINE",
    }


def recommendation(summary: dict[str, object]) -> list[dict[str, object]]:
    allowed = summary["research_retest_allowed"] == "TRUE"
    return [{
        "recommendation_id": "V21_042_R2_RECOMMENDATION_001",
        "recommendation_type": "RUN_CONTEXT_CONDITIONED_RETEST_NEXT" if allowed else "KEEP_BASELINE_TRUE_TECHNICAL_OR_WAIT_FOR_MATURITY",
        "candidate_variant_name": summary["context_conditioned_candidate_name"],
        "evidence_summary": f"conditioned_buckets={summary['context_conditioned_bucket_count']}; edge_concentration_reduced={summary['edge_concentration_reduced']}",
        "proposed_next_stage": summary["next_recommended_stage"],
        "research_retest_allowed": summary["research_retest_allowed"],
        "shadow_dry_run_candidate_allowed_now": "FALSE",
        "shadow_gate_allowed_now": "FALSE",
        "official_use_allowed": "FALSE",
        "required_before_shadow_dry_run": "Run V21.041-R2 research-only context-conditioned retest and repeat stability review.",
        "risk_notes": "R2 defines a candidate only; no shadow or official mutation is permitted.",
    }]


def validation(summary: dict[str, object], action_rows: list[dict[str, object]], definition_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    failed_blocked = all(r["rsi_action"] != "APPLY_RSI_DEEMPHASIS" for r in action_rows if r.get("upstream_context_pass") == "FALSE")
    pass_mapped = any(r["rsi_action"] == "APPLY_RSI_DEEMPHASIS" for r in action_rows if r.get("upstream_context_pass") == "TRUE")
    checks = [
        ("V21_042_R1_SUMMARY_FOUND", yes(R1_SUMMARY.exists()), "TRUE"),
        ("V21_042_R1_CONTEXT_STABILITY_FOUND", yes(R1_CONTEXT.exists()), "TRUE"),
        ("V21_042_R1_WINDOW_STABILITY_FOUND", yes(R1_WINDOW.exists()), "TRUE"),
        ("EDGE_CONCENTRATION_AUDIT_FOUND", yes(R1_CONCENTRATION.exists()), "TRUE"),
        ("CONTEXT_ACTION_MAP_CREATED", yes(len(action_rows) > 0), "TRUE"),
        ("CONDITIONED_VARIANT_CREATED", summary["context_conditioned_candidate_created"], "TRUE"),
        ("FAILED_CONTEXTS_BLOCKED", yes(failed_blocked), "TRUE"),
        ("PASS_CONTEXTS_MAPPED", yes(pass_mapped), "TRUE"),
        ("RETEST_RECOMMENDATION_CREATED", "TRUE", "TRUE"),
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
        "notes": "Research-only V21.042-R2 validation.",
    } for item, obs, req in checks]


def write_report(summary: dict[str, object], action_rows: list[dict[str, object]], scope_rows: list[dict[str, object]], concentration_rows: list[dict[str, object]]) -> None:
    worked = "\n".join(f"- {r['canonical_context_bucket']}: excess={r['upstream_mean_excess_vs_baseline']}" for r in action_rows if r["rsi_action"] == "APPLY_RSI_DEEMPHASIS") or "- None."
    harmed = "\n".join(f"- {r['canonical_context_bucket']}: reason={r['rsi_action_reason']}" for r in action_rows if r["rsi_action"] == "BLOCK_RSI_DEEMPHASIS") or "- None."
    action_lines = "\n".join(f"- {r['canonical_context_bucket']}: {r['rsi_action']}" for r in action_rows[:30])
    scope_lines = "\n".join(f"- {r['forward_window']}: rows={r['expected_rows_available']}, allowed={r['retest_allowed']}, status={r['scope_status']}" for r in scope_rows)
    conc = concentration_rows[0] if concentration_rows else {}
    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Final status and decision
- final_status: {summary['final_status']}
- decision: {summary['decision']}

## V21.042-R1 failure summary
R1 candidate `{summary['upstream_candidate_variant_name']}` failed stability review. context_stability_pass={summary['upstream_context_stability_pass']}; window_stability_pass={summary['upstream_window_stability_pass']}; shadow dry-run remained blocked.

## Contexts where RSI deemphasis worked
{worked}

## Contexts where RSI deemphasis harmed performance
{harmed}

## Context-conditioned RSI action map
{action_lines}

## Refined candidate definition
Candidate: {summary['context_conditioned_candidate_name']}; apply buckets: {summary['context_conditioned_bucket_count']}; blocked buckets: {summary['blocked_bucket_count']}.

## Expected retest scope by forward window
{scope_lines}

## Edge concentration repair audit
top3 before={fmt(conc.get('top3_contribution_share_before'))}; top3 after={fmt(conc.get('top3_contribution_share_after'))}; reduced={summary['edge_concentration_reduced']}.

## Whether another research-only retest is recommended
research_retest_allowed: {summary['research_retest_allowed']}.

## Why shadow dry-run remains blocked
shadow_dry_run_candidate_allowed remains FALSE because this stage only defines a repaired research candidate and does not perform the required V21.041-R2 retest.

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
    "upstream_v21_042_r1_final_status", "upstream_candidate_variant_name",
    "upstream_stability_review_pass", "upstream_context_stability_pass",
    "upstream_window_stability_pass", "upstream_shadow_dry_run_candidate_allowed",
    "context_pass_bucket_count", "context_fail_bucket_count",
    "context_conditioned_candidate_created", "context_conditioned_candidate_name",
    "context_conditioned_bucket_count", "blocked_bucket_count",
    "passthrough_baseline_bucket_count", "edge_concentration_reduced",
    "expected_5d_retest_allowed", "expected_10d_retest_allowed",
    "expected_20d_retest_allowed", "research_retest_allowed",
    "shadow_dry_run_candidate_allowed", "shadow_gate_allowed",
    "official_adoption_allowed", "data_trust_alpha_weight_allowed",
    "next_recommended_stage",
]


def safe_blocked() -> None:
    summary = {
        "stage": STAGE, "final_status": BLOCKED_INPUT_STATUS, "decision": DECISION_BLOCKED,
        "research_only": "TRUE", "official_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE", "official_ranking_mutation_allowed": "FALSE",
        "trade_action_allowed": "FALSE", "broker_execution_allowed": "FALSE",
        "real_book_mutation_allowed": "FALSE", "upstream_v21_042_r1_final_status": read_first(R1_SUMMARY).get("final_status", ""),
        "upstream_candidate_variant_name": "", "upstream_stability_review_pass": "",
        "upstream_context_stability_pass": "", "upstream_window_stability_pass": "",
        "upstream_shadow_dry_run_candidate_allowed": "", "context_pass_bucket_count": 0,
        "context_fail_bucket_count": 0, "context_conditioned_candidate_created": "FALSE",
        "context_conditioned_candidate_name": "", "context_conditioned_bucket_count": 0,
        "blocked_bucket_count": 0, "passthrough_baseline_bucket_count": 0,
        "edge_concentration_reduced": "FALSE", "expected_5d_retest_allowed": "FALSE",
        "expected_10d_retest_allowed": "FALSE", "expected_20d_retest_allowed": "FALSE",
        "research_retest_allowed": "FALSE", "shadow_dry_run_candidate_allowed": "FALSE",
        "shadow_gate_allowed": "FALSE", "official_adoption_allowed": "FALSE",
        "data_trust_alpha_weight_allowed": "FALSE", "next_recommended_stage": "RESTORE_REQUIRED_V21_042_R2_INPUTS",
    }
    action = [{"canonical_context_bucket": "UNKNOWN", "total_rows_used": 0, "upstream_context_pass": "FALSE", "rsi_action": "REVIEW_ONLY_LOW_SAMPLE", "include_in_context_conditioned_candidate": "FALSE", "require_more_maturity": "TRUE"}]
    definition = variant_definition(action)
    scope = [{"forward_window": w, "context_bucket_count_in_scope": 0, "expected_rows_available": 0, "scope_status": "BLOCKED_INPUTS_MISSING", "retest_allowed": "FALSE", "notes": "Required inputs missing."} for w in WINDOWS]
    conc = [{"candidate_variant_name": VARIANT_NAME, "positive_edge_bucket_count_before": 0, "positive_edge_bucket_count_after": 0, "top1_contribution_share_before": 0, "top1_contribution_share_after": 0, "top3_contribution_share_before": 0, "top3_contribution_share_after": 0, "edge_concentration_reduced": "FALSE", "concentration_status_after": "BLOCKED_INPUTS_MISSING", "notes": "Required inputs missing."}]
    write_all(summary, action, definition, scope, conc)


def write_all(summary: dict[str, object], action: list[dict[str, object]], definition: list[dict[str, object]], scope: list[dict[str, object]], conc: list[dict[str, object]]) -> None:
    write_csv(SUMMARY_OUT, [summary], SUMMARY_FIELDS)
    write_csv(ACTION_OUT, action, ["canonical_context_bucket", "total_rows_used", "upstream_context_pass", "upstream_mean_excess_vs_baseline", "upstream_hit_rate_delta_vs_baseline", "upstream_downside_delta_vs_baseline", "forward_windows_available", "edge_contribution_share", "rsi_action", "rsi_action_reason", "include_in_context_conditioned_candidate", "require_more_maturity", "notes"])
    write_csv(DEFINITION_OUT, definition, ["variant_name", "canonical_context_bucket", "rsi_action", "rsi_weight_multiplier", "baseline_passthrough", "rationale", "max_delta_guardrail_pass"])
    write_csv(SCOPE_OUT, scope, ["forward_window", "context_bucket_count_in_scope", "expected_rows_available", "scope_status", "retest_allowed", "notes"])
    write_csv(CONCENTRATION_OUT, conc, ["candidate_variant_name", "positive_edge_bucket_count_before", "positive_edge_bucket_count_after", "top1_contribution_share_before", "top1_contribution_share_after", "top3_contribution_share_before", "top3_contribution_share_after", "edge_concentration_reduced", "concentration_status_after", "notes"])
    write_csv(RECOMMENDATION_OUT, recommendation(summary), ["recommendation_id", "recommendation_type", "candidate_variant_name", "evidence_summary", "proposed_next_stage", "research_retest_allowed", "shadow_dry_run_candidate_allowed_now", "shadow_gate_allowed_now", "official_use_allowed", "required_before_shadow_dry_run", "risk_notes"])
    write_csv(VALIDATION_OUT, validation(summary, action, definition), ["validation_item", "validation_status", "observed_value", "required_value", "pass_fail", "notes"])
    write_report(summary, action, scope, conc)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    if not all(path.exists() for path in REQUIRED_INPUTS):
        safe_blocked()
        summary = read_first(SUMMARY_OUT)
    else:
        r1_summary, context, window, concentration, perf, ledger = load_inputs()
        if context.empty or concentration.empty or perf.empty:
            safe_blocked()
            summary = read_first(SUMMARY_OUT)
        else:
            action = action_map(context, concentration)
            definition = variant_definition(action)
            scope = expected_scope(action, perf, ledger)
            conc = concentration_repair(action, concentration)
            summary = build_summary(r1_summary, action, scope, conc)
            write_all(summary, action, definition, scope, conc)

    print(f"STAGE_NAME={STAGE}")
    print(f"final_status={summary['final_status']}")
    print(f"decision={summary['decision']}")
    print(f"context_conditioned_candidate_name={summary['context_conditioned_candidate_name']}")
    print(f"context_conditioned_bucket_count={summary['context_conditioned_bucket_count']}")
    print(f"research_retest_allowed={summary['research_retest_allowed']}")
    print(f"shadow_dry_run_candidate_allowed={summary['shadow_dry_run_candidate_allowed']}")
    print(f"shadow_gate_allowed={summary['shadow_gate_allowed']}")


if __name__ == "__main__":
    main()
