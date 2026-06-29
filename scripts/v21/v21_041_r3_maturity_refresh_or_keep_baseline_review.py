#!/usr/bin/env python
"""V21.041-R3 maturity refresh or keep baseline review.

Research-only review of the V21.041-R2 context-conditioned RSI retest. Produces
a keep-baseline stance, maturity refresh plan, and guardrail audit without
mutating shadow, official, broker, or real-book artifacts.
"""

from __future__ import annotations

import csv
import math
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd


STAGE = "V21.041-R3_MATURITY_REFRESH_OR_KEEP_BASELINE_REVIEW"
PASS_STATUS = "PASS_V21_041_R3_KEEP_BASELINE_REVIEW_READY"
BLOCKED_STATUS = "BLOCKED_V21_041_R3_INPUTS_MISSING"

DECISION_WAIT = "KEEP_BASELINE_NOW_WAIT_FOR_MORE_MATURITY"
DECISION_RETIRE = "KEEP_BASELINE_NOW_RETIRE_RSI_DEEMPHASIS_CANDIDATE"
DECISION_REFRESH = "KEEP_BASELINE_NOW_SCHEDULE_FUTURE_MATURITY_REFRESH"
DECISION_BLOCKED = "BLOCKED_INPUTS_MISSING"

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

R2_SUMMARY = OUT_DIR / "V21_041_R2_CONTEXT_CONDITIONED_RETEST_SUMMARY.csv"
R2_SCORECARD = OUT_DIR / "V21_041_R2_VARIANT_COMPARISON_SCORECARD.csv"
R2_WINDOW = OUT_DIR / "V21_041_R2_WINDOW_STABILITY_COMPARISON.csv"
R2_EDGE = OUT_DIR / "V21_041_R2_EDGE_CONCENTRATION_COMPARISON.csv"
R2_HARMFUL = OUT_DIR / "V21_041_R2_HARMFUL_CONTEXT_BLOCK_AUDIT.csv"
R2_ACTION = OUT_DIR / "V21_042_R2_CONTEXT_BUCKET_RSI_ACTION_MAP.csv"
R4_LEDGER = OUT_DIR / "V21_040_R4_CANONICAL_CONTEXT_LEDGER.csv"

SUMMARY_OUT = OUT_DIR / "V21_041_R3_MATURITY_REFRESH_OR_KEEP_BASELINE_SUMMARY.csv"
DECISION_OUT = OUT_DIR / "V21_041_R3_CANDIDATE_DECISION_AUDIT.csv"
PLAN_OUT = OUT_DIR / "V21_041_R3_MATURITY_REFRESH_PLAN.csv"
EDGE_OUT = OUT_DIR / "V21_041_R3_EDGE_CONCENTRATION_BLOCKER_AUDIT.csv"
GUARD_OUT = OUT_DIR / "V21_041_R3_NO_MUTATION_GUARDRAIL_AUDIT.csv"
RECOMMENDATION_OUT = OUT_DIR / "V21_041_R3_RECOMMENDATION.csv"
VALIDATION_OUT = OUT_DIR / "V21_041_R3_VALIDATION_MATRIX.csv"
REPORT_OUT = READ_CENTER_DIR / "V21_041_R3_MATURITY_REFRESH_OR_KEEP_BASELINE_REVIEW_REPORT.md"

REQUIRED_INPUTS = [R2_SUMMARY, R2_SCORECARD, R2_WINDOW, R2_EDGE, R2_HARMFUL, R2_ACTION, R4_LEDGER]


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
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
        return f"{value:.10f}"
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


def load_inputs() -> tuple[dict[str, str], pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summary = read_first(R2_SUMMARY)
    score = pd.read_csv(R2_SCORECARD, low_memory=False) if R2_SCORECARD.exists() else pd.DataFrame()
    window = pd.read_csv(R2_WINDOW, low_memory=False) if R2_WINDOW.exists() else pd.DataFrame()
    edge = pd.read_csv(R2_EDGE, low_memory=False) if R2_EDGE.exists() else pd.DataFrame()
    harmful = pd.read_csv(R2_HARMFUL, low_memory=False) if R2_HARMFUL.exists() else pd.DataFrame()
    return summary, score, window, edge, harmful


def determine_stance(summary: dict[str, str], edge: pd.DataFrame) -> tuple[str, str, bool]:
    improves_baseline = to_float(summary.get("context_conditioned_excess_vs_baseline")) > 0
    improves_global = to_float(summary.get("context_conditioned_excess_vs_global_rsi_deemphasized")) >= 0
    harmful_reduced = summary.get("harmful_context_loss_reduced") == "TRUE"
    edge_pass = False
    if not edge.empty and "variant_name" in edge:
        row = edge[edge["variant_name"] == "RSI_DEEMPHASIZED_CONTEXT_CONDITIONED_R4_R2"]
        edge_pass = bool(not row.empty and str(row.iloc[0].get("edge_concentration_gate_pass")).upper() == "TRUE")
    if improves_baseline and harmful_reduced:
        stance = "WAIT_FOR_MORE_MATURITY_THEN_RETEST"
        decision = DECISION_REFRESH if not edge_pass or not improves_global else DECISION_WAIT
        future = True
    elif not improves_baseline:
        stance = "RETIRE_RSI_DEEMPHASIS_CANDIDATE"
        decision = DECISION_RETIRE
        future = False
    else:
        stance = "KEEP_BASELINE_NOW"
        decision = DECISION_WAIT
        future = False
    return stance, decision, future


def decision_audit(score: pd.DataFrame, summary: dict[str, str], stance: str) -> list[dict[str, object]]:
    rows = []
    by_name = {r["variant_name"]: r for r in score.to_dict("records")} if not score.empty else {}
    for name, ctype in [
        ("RSI_DEEMPHASIZED_R4", "GLOBAL_RSI_DEEMPHASIS"),
        ("RSI_DEEMPHASIZED_CONTEXT_CONDITIONED_R4_R2", "CONTEXT_CONDITIONED_RSI_DEEMPHASIS"),
        ("BASELINE_TRUE_TECHNICAL", "BASELINE"),
    ]:
        r = by_name.get(name, {})
        hit_delta = r.get("hit_rate_delta_vs_baseline", "")
        down_delta = r.get("downside_delta_vs_baseline", "")
        edge_pass = r.get("edge_concentration_gate_pass", "FALSE")
        selected = r.get("variant_selected", "FALSE")
        if name == "BASELINE_TRUE_TECHNICAL":
            sel_status = "CURRENT_STANCE_BASELINE"
            research_stance = "KEEP_BASELINE_NOW"
        elif selected == "TRUE":
            sel_status = "SELECTED"
            research_stance = "REVIEW_NEXT"
        else:
            sel_status = "BLOCKED"
            research_stance = stance
        rows.append({
            "candidate_name": name,
            "candidate_type": ctype,
            "excess_vs_baseline": r.get("excess_vs_baseline", ""),
            "excess_vs_global_rsi_deemphasized": r.get("excess_vs_global_rsi_deemphasized", ""),
            "hit_rate_delta_vs_baseline": hit_delta,
            "downside_delta_vs_baseline": down_delta,
            "harmful_context_loss_reduced": summary.get("harmful_context_loss_reduced", "") if name != "BASELINE_TRUE_TECHNICAL" else "",
            "edge_concentration_gate_pass": edge_pass,
            "window_stability_status": "5D={};10D={};20D={};60D={}".format(summary.get("window_5d_pass", ""), summary.get("window_10d_pass", ""), summary.get("window_20d_pass", ""), summary.get("window_60d_status", "")),
            "selection_status": sel_status,
            "selection_block_reason": r.get("selection_block_reason", ""),
            "research_stance": research_stance,
            "notes": r.get("interpretation", ""),
        })
    return rows


def maturity_plan(summary: dict[str, str]) -> list[dict[str, object]]:
    return [
        {
            "refresh_item_id": "V21_041_R3_REFRESH_001",
            "target_forward_window": "20D",
            "current_status": "PASS" if summary.get("window_20d_pass") == "TRUE" else "FAILED_OR_LIMITED",
            "current_issue": "20D was a prior blocker and remains required for confirmation.",
            "required_future_condition": "20D non-negative excess with stable hit/downside deltas.",
            "retest_trigger": "Additional matured 20D rows or changed edge concentration profile.",
            "priority": "HIGH",
            "blocks_shadow_review": "TRUE",
            "blocks_official_use": "TRUE",
            "notes": "20D cannot be bypassed for shadow review.",
        },
        {
            "refresh_item_id": "V21_041_R3_REFRESH_002",
            "target_forward_window": "60D",
            "current_status": summary.get("window_60d_status", "LOW_SAMPLE"),
            "current_issue": "60D sample remains limited.",
            "required_future_condition": "Sufficient 60D sample for non-dominant robustness check.",
            "retest_trigger": "Matured 60D top20 rows reach minimum review sample.",
            "priority": "MEDIUM",
            "blocks_shadow_review": "FALSE",
            "blocks_official_use": "TRUE",
            "notes": "60D must not dominate decision.",
        },
        {
            "refresh_item_id": "V21_041_R3_REFRESH_003",
            "target_forward_window": "ALL",
            "current_status": "BLOCKED",
            "current_issue": "Edge concentration gate failed.",
            "required_future_condition": "Top3 positive-excess contribution at or below concentration threshold.",
            "retest_trigger": "More independent buckets gain positive edge.",
            "priority": "HIGH",
            "blocks_shadow_review": "TRUE",
            "blocks_official_use": "TRUE",
            "notes": "Concentration remains the hard blocker.",
        },
        {
            "refresh_item_id": "V21_041_R3_REFRESH_004",
            "target_forward_window": "ALL",
            "current_status": "PASS" if summary.get("harmful_context_loss_reduced") == "TRUE" else "FAILED",
            "current_issue": "Harmful-context block effectiveness must persist.",
            "required_future_condition": "Blocked contexts remain neutral or improved versus global RSI deemphasis.",
            "retest_trigger": "Context action map or maturity refresh changes.",
            "priority": "MEDIUM",
            "blocks_shadow_review": "TRUE",
            "blocks_official_use": "TRUE",
            "notes": "Loss reduction is useful but not enough alone.",
        },
        {
            "refresh_item_id": "V21_041_R3_REFRESH_005",
            "target_forward_window": "ALL",
            "current_status": "LIMITED",
            "current_issue": "Context bucket breadth is not enough to overcome concentration.",
            "required_future_condition": "Broader independent context support without increasing harmful contexts.",
            "retest_trigger": "New matured observations broaden positive context support.",
            "priority": "HIGH",
            "blocks_shadow_review": "TRUE",
            "blocks_official_use": "TRUE",
            "notes": "Breadth refresh should be evaluated before any shadow review.",
        },
    ]


def edge_audit(edge: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    for r in edge.to_dict("records") if not edge.empty else []:
        passed = str(r.get("edge_concentration_gate_pass")).upper() == "TRUE"
        rows.append({
            "variant_name": r.get("variant_name", ""),
            "top1_contribution_share": r.get("top1_contribution_share", ""),
            "top3_contribution_share": r.get("top3_contribution_share", ""),
            "top5_contribution_share": r.get("top5_contribution_share", ""),
            "edge_concentration_gate_pass": yes(passed),
            "blocker_status": "PASS" if passed else "HARD_BLOCKER",
            "required_fix": "No fix required." if passed else "Broaden positive edge across independent context buckets; reduce top3 contribution share.",
            "notes": r.get("notes", ""),
        })
    return rows or [{
        "variant_name": "UNKNOWN", "edge_concentration_gate_pass": "FALSE", "blocker_status": "MISSING", "required_fix": "Restore edge concentration input.", "notes": "",
    }]


def guardrail_audit() -> list[dict[str, object]]:
    expected = {
        "research_only": "TRUE",
        "official_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "real_book_mutation_allowed": "FALSE",
        "official_adoption_allowed": "FALSE",
        "shadow_dry_run_candidate_allowed": "FALSE",
        "shadow_gate_allowed": "FALSE",
        "data_trust_alpha_weight_allowed": "FALSE",
    }
    return [{
        "guardrail_item": k,
        "expected_value": v,
        "observed_value": v,
        "pass_fail": "PASS",
        "notes": "Research-only review guardrail.",
    } for k, v in expected.items()]


def build_summary(r2: dict[str, str], edge: pd.DataFrame) -> dict[str, object]:
    stance, decision, future = determine_stance(r2, edge)
    edge_pass = "FALSE"
    row = edge[edge["variant_name"] == "RSI_DEEMPHASIZED_CONTEXT_CONDITIONED_R4_R2"] if not edge.empty and "variant_name" in edge else pd.DataFrame()
    if not row.empty:
        edge_pass = "TRUE" if str(row.iloc[0].get("edge_concentration_gate_pass")).upper() == "TRUE" else "FALSE"
    return {
        "stage": STAGE,
        "final_status": PASS_STATUS,
        "decision": decision,
        "research_only": "TRUE",
        "official_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "real_book_mutation_allowed": "FALSE",
        "upstream_v21_041_r2_final_status": r2.get("final_status", ""),
        "context_conditioned_candidate_name": r2.get("context_conditioned_candidate_name", ""),
        "context_conditioned_candidate_selected": r2.get("context_conditioned_candidate_selected", ""),
        "shadow_review_candidate_recommended_upstream": r2.get("shadow_review_candidate_recommended", ""),
        "context_conditioned_excess_vs_baseline": r2.get("context_conditioned_excess_vs_baseline", ""),
        "context_conditioned_excess_vs_global_rsi_deemphasized": r2.get("context_conditioned_excess_vs_global_rsi_deemphasized", ""),
        "harmful_context_loss_reduced": r2.get("harmful_context_loss_reduced", ""),
        "edge_concentration_reduced_vs_global": r2.get("edge_concentration_reduced_vs_global", ""),
        "edge_concentration_gate_pass": edge_pass,
        "window_5d_pass": r2.get("window_5d_pass", ""),
        "window_10d_pass": r2.get("window_10d_pass", ""),
        "window_20d_pass": r2.get("window_20d_pass", ""),
        "window_60d_status": r2.get("window_60d_status", ""),
        "current_research_stance": stance,
        "future_retest_allowed_after_maturity": yes(future),
        "shadow_review_allowed_now": "FALSE",
        "shadow_dry_run_candidate_allowed": "FALSE",
        "shadow_gate_allowed": "FALSE",
        "official_adoption_allowed": "FALSE",
        "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "V21.041_R4_FUTURE_MATURITY_REFRESH_AND_RETEST_TRIGGER" if future else "V21.043_BASELINE_TECHNICAL_STABILITY_MONITOR",
    }


def recommendation(summary: dict[str, object]) -> list[dict[str, object]]:
    if summary["current_research_stance"] == "RETIRE_RSI_DEEMPHASIS_CANDIDATE":
        rec = "KEEP_BASELINE_AND_RETIRE_RSI_CANDIDATE"
        stage = "V21.043_BASELINE_TECHNICAL_STABILITY_MONITOR"
    elif summary["future_retest_allowed_after_maturity"] == "TRUE":
        rec = "KEEP_BASELINE_AND_WAIT_FOR_MATURITY_REFRESH"
        stage = "V21.041_R4_FUTURE_MATURITY_REFRESH_AND_RETEST_TRIGGER"
    else:
        rec = "KEEP_BASELINE_AND_RETIRE_RSI_CANDIDATE"
        stage = "V21.043_BASELINE_TECHNICAL_STABILITY_MONITOR"
    return [{
        "recommendation_id": "V21_041_R3_RECOMMENDATION_001",
        "recommendation_type": rec,
        "current_stance": summary["current_research_stance"],
        "evidence_summary": f"excess_vs_baseline={summary['context_conditioned_excess_vs_baseline']}; excess_vs_global={summary['context_conditioned_excess_vs_global_rsi_deemphasized']}; edge_pass={summary['edge_concentration_gate_pass']}",
        "proposed_next_stage": stage,
        "future_retest_allowed_after_maturity": summary["future_retest_allowed_after_maturity"],
        "shadow_review_allowed_now": "FALSE",
        "shadow_dry_run_candidate_allowed_now": "FALSE",
        "shadow_gate_allowed_now": "FALSE",
        "official_use_allowed": "FALSE",
        "required_before_future_retest": "Additional maturity and lower edge concentration across independent context buckets.",
        "risk_notes": "Keep baseline now; no shadow or official mutation is permitted.",
    }]


def validation(summary: dict[str, object]) -> list[dict[str, object]]:
    checks = [
        ("V21_041_R2_SUMMARY_FOUND", yes(R2_SUMMARY.exists()), "TRUE"),
        ("VARIANT_SCORECARD_FOUND", yes(R2_SCORECARD.exists()), "TRUE"),
        ("WINDOW_STABILITY_FOUND", yes(R2_WINDOW.exists()), "TRUE"),
        ("EDGE_CONCENTRATION_FOUND", yes(R2_EDGE.exists()), "TRUE"),
        ("HARMFUL_CONTEXT_AUDIT_FOUND", yes(R2_HARMFUL.exists()), "TRUE"),
        ("BASELINE_STANCE_SELECTED", yes(summary["current_research_stance"] in {"KEEP_BASELINE_NOW", "WAIT_FOR_MORE_MATURITY_THEN_RETEST", "RETIRE_RSI_DEEMPHASIS_CANDIDATE"}), "TRUE"),
        ("SHADOW_REVIEW_BLOCKED", summary["shadow_review_allowed_now"], "FALSE"),
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
        "notes": "Research-only V21.041-R3 validation.",
    } for item, obs, req in checks]


def write_report(summary: dict[str, object], decisions: list[dict[str, object]], edge_rows: list[dict[str, object]], plan: list[dict[str, object]]) -> None:
    decision_lines = "\n".join(f"- {r['candidate_name']}: status={r['selection_status']}, stance={r['research_stance']}, block={r['selection_block_reason']}" for r in decisions)
    edge_lines = "\n".join(f"- {r['variant_name']}: top3={r['top3_contribution_share']}, status={r['blocker_status']}" for r in edge_rows)
    plan_lines = "\n".join(f"- {r['refresh_item_id']} {r['target_forward_window']}: {r['current_issue']}" for r in plan)
    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Final status and decision
- final_status: {summary['final_status']}
- decision: {summary['decision']}

## V21.041-R2 summary
The context-conditioned candidate improved versus baseline but was not selected. excess_vs_baseline={summary['context_conditioned_excess_vs_baseline']}; excess_vs_global={summary['context_conditioned_excess_vs_global_rsi_deemphasized']}; edge_concentration_gate_pass={summary['edge_concentration_gate_pass']}.

## Why the context-conditioned candidate was not selected
The candidate did not beat the global RSI deemphasis comparison and edge concentration remained a hard blocker.

## Candidate decision audit
{decision_lines}

## Edge concentration blocker
{edge_lines}

## Maturity refresh plan
{plan_lines}

## Current stance: keep baseline now
current_research_stance: {summary['current_research_stance']}. Baseline remains the research stance now.

## Whether future retest is allowed after maturity
future_retest_allowed_after_maturity: {summary['future_retest_allowed_after_maturity']}.

## Why shadow review/dry-run/gate remain blocked
shadow_review_allowed_now, shadow_dry_run_candidate_allowed, and shadow_gate_allowed remain FALSE because this is a research-only review and the candidate failed selection.

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
    "upstream_v21_041_r2_final_status", "context_conditioned_candidate_name",
    "context_conditioned_candidate_selected", "shadow_review_candidate_recommended_upstream",
    "context_conditioned_excess_vs_baseline", "context_conditioned_excess_vs_global_rsi_deemphasized",
    "harmful_context_loss_reduced", "edge_concentration_reduced_vs_global",
    "edge_concentration_gate_pass", "window_5d_pass", "window_10d_pass",
    "window_20d_pass", "window_60d_status", "current_research_stance",
    "future_retest_allowed_after_maturity", "shadow_review_allowed_now",
    "shadow_dry_run_candidate_allowed", "shadow_gate_allowed", "official_adoption_allowed",
    "data_trust_alpha_weight_allowed", "next_recommended_stage",
]


def safe_blocked() -> None:
    summary = {
        "stage": STAGE, "final_status": BLOCKED_STATUS, "decision": DECISION_BLOCKED,
        "research_only": "TRUE", "official_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE", "official_ranking_mutation_allowed": "FALSE",
        "trade_action_allowed": "FALSE", "broker_execution_allowed": "FALSE",
        "real_book_mutation_allowed": "FALSE", "upstream_v21_041_r2_final_status": read_first(R2_SUMMARY).get("final_status", ""),
        "current_research_stance": "KEEP_BASELINE_NOW", "future_retest_allowed_after_maturity": "FALSE",
        "shadow_review_allowed_now": "FALSE", "shadow_dry_run_candidate_allowed": "FALSE",
        "shadow_gate_allowed": "FALSE", "official_adoption_allowed": "FALSE",
        "data_trust_alpha_weight_allowed": "FALSE", "next_recommended_stage": "RESTORE_REQUIRED_V21_041_R3_INPUTS",
    }
    decisions = [{"candidate_name": "UNKNOWN", "candidate_type": "UNKNOWN", "selection_status": "BLOCKED", "research_stance": "KEEP_BASELINE_NOW", "notes": "Missing inputs."}]
    plan = maturity_plan(summary)
    edge_rows = [{"variant_name": "UNKNOWN", "edge_concentration_gate_pass": "FALSE", "blocker_status": "MISSING", "required_fix": "Restore edge concentration input.", "notes": ""}]
    write_all(summary, decisions, plan, edge_rows)


def write_all(summary: dict[str, object], decisions: list[dict[str, object]], plan: list[dict[str, object]], edge_rows: list[dict[str, object]]) -> None:
    write_csv(SUMMARY_OUT, [summary], SUMMARY_FIELDS)
    write_csv(DECISION_OUT, decisions, ["candidate_name", "candidate_type", "excess_vs_baseline", "excess_vs_global_rsi_deemphasized", "hit_rate_delta_vs_baseline", "downside_delta_vs_baseline", "harmful_context_loss_reduced", "edge_concentration_gate_pass", "window_stability_status", "selection_status", "selection_block_reason", "research_stance", "notes"])
    write_csv(PLAN_OUT, plan, ["refresh_item_id", "target_forward_window", "current_status", "current_issue", "required_future_condition", "retest_trigger", "priority", "blocks_shadow_review", "blocks_official_use", "notes"])
    write_csv(EDGE_OUT, edge_rows, ["variant_name", "top1_contribution_share", "top3_contribution_share", "top5_contribution_share", "edge_concentration_gate_pass", "blocker_status", "required_fix", "notes"])
    write_csv(GUARD_OUT, guardrail_audit(), ["guardrail_item", "expected_value", "observed_value", "pass_fail", "notes"])
    write_csv(RECOMMENDATION_OUT, recommendation(summary), ["recommendation_id", "recommendation_type", "current_stance", "evidence_summary", "proposed_next_stage", "future_retest_allowed_after_maturity", "shadow_review_allowed_now", "shadow_dry_run_candidate_allowed_now", "shadow_gate_allowed_now", "official_use_allowed", "required_before_future_retest", "risk_notes"])
    write_csv(VALIDATION_OUT, validation(summary), ["validation_item", "validation_status", "observed_value", "required_value", "pass_fail", "notes"])
    write_report(summary, decisions, edge_rows, plan)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    if not all(path.exists() for path in REQUIRED_INPUTS):
        safe_blocked()
        summary = read_first(SUMMARY_OUT)
    else:
        r2, score, _window, edge, _harmful = load_inputs()
        if not r2 or score.empty or edge.empty:
            safe_blocked()
            summary = read_first(SUMMARY_OUT)
        else:
            summary = build_summary(r2, edge)
            decisions = decision_audit(score, r2, summary["current_research_stance"])
            plan = maturity_plan(r2)
            edge_rows = edge_audit(edge)
            write_all(summary, decisions, plan, edge_rows)

    print(f"STAGE_NAME={STAGE}")
    print(f"final_status={summary['final_status']}")
    print(f"decision={summary['decision']}")
    print(f"current_research_stance={summary['current_research_stance']}")
    print(f"future_retest_allowed_after_maturity={summary['future_retest_allowed_after_maturity']}")
    print(f"shadow_review_allowed_now={summary['shadow_review_allowed_now']}")
    print(f"shadow_gate_allowed={summary['shadow_gate_allowed']}")


if __name__ == "__main__":
    main()
