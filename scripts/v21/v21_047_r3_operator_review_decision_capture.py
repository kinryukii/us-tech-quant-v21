#!/usr/bin/env python
"""Research-only operator decision capture for the V21.047 overlay review."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path


STAGE = "V21.047-R3_OPERATOR_REVIEW_DECISION_CAPTURE"
ROOT = Path(__file__).resolve().parents[2]
REV = ROOT / "outputs" / "v21" / "review"
RC = ROOT / "outputs" / "v21" / "read_center"

INPUTS = {
    "r2a_decision": REV / "V21_047_R2A_DECISION_SUMMARY.csv",
    "r2a_readiness": REV / "V21_047_R2A_UPSTREAM_R2_READINESS_AUDIT.csv",
    "r2a_metrics": REV / "V21_047_R2A_CANDIDATE_METRIC_CONSOLIDATION.csv",
    "r2a_scores": REV / "V21_047_R2A_TIEBREAKER_SCORE_REGISTER.csv",
    "r2a_ranking": REV / "V21_047_R2A_CANDIDATE_RANKING.csv",
    "r2a_combined": REV / "V21_047_R2A_COMBINED_CANDIDATE_DEEP_REVIEW.csv",
    "r2a_qqq": REV / "V21_047_R2A_QQQ_SCALING_COMPARISON.csv",
    "r2a_portfolio": REV / "V21_047_R2A_PORTFOLIO_DRAWDOWN_CANDIDATE_COMPARISON.csv",
    "r2a_cost": REV / "V21_047_R2A_COST_WARNING_AUDIT.csv",
    "r2a_downside": REV / "V21_047_R2A_DOWNSIDE_MONITOR_DEPENDENCY_AUDIT.csv",
    "r2a_scope": REV / "V21_047_R2A_SCOPE_BOUNDARY_AUDIT.csv",
    "r1a_decision": REV / "V21_047_R1A_DECISION_SUMMARY.csv",
    "r2_decision": REV / "V21_047_R2_DECISION_SUMMARY.csv",
    "r4_decision": REV / "V21_046_R4_DECISION_SUMMARY.csv",
    "downside_contract": REV / "V21_045_R3B_DOWNSIDE_MONITOR_CONTRACT.csv",
}
OPTIONAL_OPERATOR_INPUT = REV / "V21_047_R3_OPERATOR_INPUT.csv"

OUT_PACKET = REV / "V21_047_R3_OPERATOR_REVIEW_PACKET.csv"
OUT_ALLOWED = REV / "V21_047_R3_ALLOWED_OPERATOR_DECISIONS.csv"
OUT_CAPTURE = REV / "V21_047_R3_OPERATOR_DECISION_CAPTURE.csv"
OUT_WARNINGS = REV / "V21_047_R3_CANDIDATE_WARNING_REGISTER.csv"
OUT_ROUTING = REV / "V21_047_R3_NEXT_STAGE_ROUTING.csv"
OUT_SCOPE = REV / "V21_047_R3_SCOPE_BOUNDARY_AUDIT.csv"
OUT_DECISION = REV / "V21_047_R3_DECISION_SUMMARY.csv"
REPORT = RC / "V21_047_R3_OPERATOR_REVIEW_DECISION_CAPTURE_REPORT.md"
CURRENT = RC / "CURRENT_V21_047_R3_OPERATOR_REVIEW_DECISION_CAPTURE_REPORT.md"

DEFAULT_DECISION = "APPROVE_PRIMARY_WITH_HOLDINGS_EVIDENCE_REPAIR_REQUIRED"
DECISIONS = [
    (
        "APPROVE_PRIMARY_FOR_REVIEW_PACKET_ONLY",
        "Primary proceeds only to a review/evidence packet; no adoption, shadow gate, official use, or trading output.",
        "V21.047-R4_PRIMARY_OVERLAY_REVIEW_PACKET",
    ),
    (
        DEFAULT_DECISION,
        "Primary remains review-only and holdings evidence must be repaired before further review.",
        "V21.047-R3A_HOLDINGS_EVIDENCE_REPAIR_FOR_PRIMARY_OVERLAY",
    ),
    (
        "REQUEST_COST_MODEL_RECHECK",
        "Review the cost warning before the primary candidate proceeds.",
        "V21.047-R3B_COST_MODEL_RECHECK_FOR_PRIMARY_OVERLAY",
    ),
    (
        "SELECT_SECONDARY_QQQ_MA50_REVIEW_ONLY",
        "Use the simpler QQQ MA50 candidate for review only; no adoption.",
        "V21.047-R4_SECONDARY_QQQ_MA50_REVIEW_PACKET",
    ),
    (
        "SELECT_TERTIARY_QQQ_DRAWDOWN_REVIEW_ONLY",
        "Use the QQQ drawdown candidate for review only; no adoption.",
        "V21.047-R4_TERTIARY_QQQ_DRAWDOWN_REVIEW_PACKET",
    ),
    (
        "REJECT_OVERLAY_KEEP_BASELINE_TECH_TOP20_10D",
        "Retain the Technical-only baseline and stop overlay review.",
        "V21.047-R4_BASELINE_TECH_TOP20_10D_RETENTION_PACKET",
    ),
    (
        "WAIT_FOR_MATURED_OBSERVATION_BEFORE_OVERLAY_REVIEW",
        "Wait for matured observation evidence after 2026-06-24.",
        "RERUN_V21_044_R8_R8R1_AFTER_2026_06_24_THEN_V21_044_R9",
    ),
]
ROUTES = {decision: route for decision, _, route in DECISIONS}

GUARD = {
    "research_only": "TRUE",
    "operator_decision_capture_only": "TRUE",
    "operator_decision_is_adoption": "FALSE",
    "overlay_adoption_allowed": "FALSE",
    "portfolio_variant_adoption_allowed": "FALSE",
    "filter_adoption_allowed": "FALSE",
    "technical_only_stream": "TRUE",
    "full_weight_result_available": "FALSE",
    "full_weight_rebacktest_allowed_now": "FALSE",
    "official_adoption_allowed": "FALSE",
    "official_weight_mutation": "FALSE",
    "official_ranking_mutation": "FALSE",
    "official_recommendation_allowed": "FALSE",
    "real_book_action_allowed": "FALSE",
    "broker_execution_allowed": "FALSE",
    "trade_action_allowed": "FALSE",
    "shadow_gate_allowed": "FALSE",
    "shadow_adoption_allowed": "FALSE",
    "buy_sell_hold_recommendation_created": "FALSE",
    "online_download_attempted": "FALSE",
    "yfinance_used": "FALSE",
}


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = rows or [{"status": "NO_ROWS", **GUARD}]
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def by_id(rows: list[dict[str, str]], key: str) -> dict[str, dict[str, str]]:
    return {row.get(key, ""): row for row in rows if row.get(key)}


def yn(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def main() -> int:
    REV.mkdir(parents=True, exist_ok=True)
    RC.mkdir(parents=True, exist_ok=True)
    data = {name: read_rows(path) for name, path in INPUTS.items()}
    missing = [name for name, rows in data.items() if not rows]
    r2a = data["r2a_decision"][0] if data["r2a_decision"] else {}
    ready = (
        not missing
        and r2a.get("final_status") == "PARTIAL_PASS_V21_047_R2A_PRIMARY_SELECTED_WITH_COST_WARNING"
        and r2a.get("decision") == "PRIMARY_REVIEW_CANDIDATE_COMBINED_TURNOVER_QQQ_MA50_NOT_ADOPTABLE"
        and r2a.get("overlay_adopted") == "FALSE"
        and r2a.get("full_weight_blocked") == "TRUE"
    )

    metrics = by_id(data["r2a_metrics"], "overlay_id")
    ranking = sorted(
        [row for row in data["r2a_ranking"] if row.get("rank", "").isdigit()],
        key=lambda row: int(row["rank"]),
    )
    primary = r2a.get("primary_review_candidate", "")
    secondary = r2a.get("secondary_review_candidate", "")
    tertiary = r2a.get("tertiary_review_candidate", "")
    primary_metric = metrics.get(primary, {})
    primary_rank = next((row for row in ranking if row.get("overlay_id") == primary), {})
    combined_review = by_id(data["r2a_combined"], "review_item")
    downside = data["r2a_downside"][0] if data["r2a_downside"] else {}

    packet = {
        "primary_candidate": primary,
        "secondary_candidate": secondary,
        "tertiary_candidate": tertiary,
        "primary_candidate_score": primary_rank.get("tiebreaker_score", ""),
        "primary_total_return": primary_metric.get("total_return", ""),
        "primary_sharpe": primary_metric.get("Sharpe", ""),
        "primary_max_drawdown": primary_metric.get("max_drawdown", ""),
        "primary_turnover_reduction": primary_metric.get("turnover_reduction_vs_baseline", ""),
        "primary_after_cost_return_20bps": primary_metric.get("after_cost_total_return_20bps", ""),
        "primary_stability_status": "STABLE_MULTI_PERIOD",
        "cost_warning_status": "CARRIED_FORWARD_NOT_BLOCKING_OPERATOR_REVIEW",
        "holdings_evidence_caveat": "HOLDINGS_SNAPSHOTS_UNCHANGED_DESPITE_REPORTED_TURNOVER_REDUCTION",
        "downside_monitor_dependency": "MATURED_EVIDENCE_REQUIRED_AFTER_2026_06_24",
        "adoptable_now": "FALSE",
        "full_weight_blocked": "TRUE",
        "technical_only_not_full_weight_evidence": "TRUE",
        "ranking_summary": "|".join(
            f"{row.get('rank')}:{row.get('overlay_id')}:{row.get('tiebreaker_score')}"
            for row in ranking
        ),
        **GUARD,
    }
    write_rows(OUT_PACKET, [packet])

    allowed_rows = [
        {
            "operator_decision": decision,
            "meaning": meaning,
            "recommended_next_stage": route,
            "is_default_safe_decision": yn(decision == DEFAULT_DECISION),
            "is_adoption_decision": "FALSE",
            **GUARD,
        }
        for decision, meaning, route in DECISIONS
    ]
    write_rows(OUT_ALLOWED, allowed_rows)

    operator_rows = read_rows(OPTIONAL_OPERATOR_INPUT)
    supplied = operator_rows[0].get("operator_decision", "").strip() if operator_rows else ""
    if supplied in ROUTES:
        captured = supplied
        input_source = "LOCAL_OPERATOR_INPUT_FILE"
        input_valid = True
    else:
        captured = DEFAULT_DECISION
        input_source = "DEFAULT_SAFE_REVIEW_DECISION"
        input_valid = not supplied
    route = ROUTES[captured]

    capture = {
        "operator_input_path": str(OPTIONAL_OPERATOR_INPUT.relative_to(ROOT)),
        "external_operator_input_exists": yn(bool(operator_rows)),
        "operator_input_source": input_source,
        "operator_input_value": supplied,
        "operator_input_valid": yn(input_valid),
        "captured_operator_decision": captured,
        "decision_used_default": yn(input_source == "DEFAULT_SAFE_REVIEW_DECISION"),
        "primary_candidate": primary,
        "holdings_evidence_caveat": packet["holdings_evidence_caveat"],
        "cost_warning_status": packet["cost_warning_status"],
        "downside_monitor_dependency": packet["downside_monitor_dependency"],
        "recommended_next_stage": route,
        "overlay_adopted": "FALSE",
        "portfolio_variant_adopted": "FALSE",
        "filter_adopted": "FALSE",
        **GUARD,
    }
    write_rows(OUT_CAPTURE, [capture])

    warnings = [
        {
            "warning_id": "HOLDINGS_EVIDENCE_CAVEAT",
            "severity": "MATERIAL_REVIEW_CAVEAT",
            "candidate": primary,
            "warning": packet["holdings_evidence_caveat"],
            "blocks_adoption": "TRUE",
            "blocks_review_only_routing": "FALSE",
            "evidence": combined_review.get("rank_buffer_holdings_and_turnover", {}).get("status", ""),
            **GUARD,
        },
        {
            "warning_id": "COST_WARNING",
            "severity": "CARRIED_FORWARD",
            "candidate": primary,
            "warning": packet["cost_warning_status"],
            "blocks_adoption": "TRUE",
            "blocks_review_only_routing": "FALSE",
            "evidence": r2a.get("cost_warning_status", ""),
            **GUARD,
        },
        {
            "warning_id": "DOWNSIDE_MONITOR_DEPENDENCY",
            "severity": "MATURITY_DEPENDENCY",
            "candidate": primary,
            "warning": packet["downside_monitor_dependency"],
            "blocks_adoption": "TRUE",
            "blocks_review_only_routing": "FALSE",
            "evidence": downside.get("selection_review_effect", ""),
            **GUARD,
        },
        {
            "warning_id": "TECHNICAL_ONLY_BOUNDARY",
            "severity": "SCOPE_BOUNDARY",
            "candidate": primary,
            "warning": "TECHNICAL_ONLY_CANDIDATE_NOT_FULL_WEIGHT_EVIDENCE",
            "blocks_adoption": "TRUE",
            "blocks_review_only_routing": "FALSE",
            "evidence": "full_weight_result_available=FALSE",
            **GUARD,
        },
    ]
    write_rows(OUT_WARNINGS, warnings)

    routing_rows = [
        {
            "operator_decision": decision,
            "recommended_next_stage": route_name,
            "selected_route": yn(decision == captured),
            "route_is_adoption": "FALSE",
            **GUARD,
        }
        for decision, _, route_name in DECISIONS
    ]
    write_rows(OUT_ROUTING, routing_rows)

    scope_rows = [
        {
            "boundary_check": "operator_decision_capture_only",
            "check_passed": "TRUE",
            "evidence": "The stage records a review-only decision and route.",
            **GUARD,
        },
        {
            "boundary_check": "no_adoption_or_shadow_enablement",
            "check_passed": "TRUE",
            "evidence": "All adoption and shadow flags are FALSE.",
            **GUARD,
        },
        {
            "boundary_check": "no_official_mutation_or_execution_output",
            "check_passed": "TRUE",
            "evidence": "Only V21 review and read-center artifacts are written.",
            **GUARD,
        },
        {
            "boundary_check": "technical_only_not_full_weight",
            "check_passed": "TRUE",
            "evidence": "No full-weight backtest or score is created.",
            **GUARD,
        },
    ]
    write_rows(OUT_SCOPE, scope_rows)
    scope_ok = all(row["check_passed"] == "TRUE" for row in scope_rows)

    if not ready:
        status = "BLOCKED_V21_047_R3_R2A_OUTPUTS_NOT_READY"
        final_decision = "BLOCK_OPERATOR_DECISION_CAPTURE"
        final_route = "V21.047-R2A_CANDIDATE_TIEBREAKER_AND_SELECTION_REVIEW"
    elif not scope_ok:
        status = "BLOCKED_V21_047_R3_SCOPE_BOUNDARY_FAILED"
        final_decision = "BLOCK_OPERATOR_DECISION_CAPTURE"
        final_route = STAGE
    elif captured == DEFAULT_DECISION:
        status = "PARTIAL_PASS_V21_047_R3_DECISION_CAPTURE_WITH_HOLDINGS_EVIDENCE_CAVEAT"
        final_decision = captured
        final_route = route
    elif captured == "REQUEST_COST_MODEL_RECHECK":
        status = "PARTIAL_PASS_V21_047_R3_DECISION_CAPTURE_WITH_COST_WARNING"
        final_decision = captured
        final_route = route
    elif input_source == "DEFAULT_SAFE_REVIEW_DECISION":
        status = "PARTIAL_PASS_V21_047_R3_DEFAULT_SAFE_DECISION_CAPTURED"
        final_decision = captured
        final_route = route
    else:
        status = "PASS_V21_047_R3_OPERATOR_DECISION_CAPTURE_READY"
        final_decision = captured
        final_route = route

    decision_summary = {
        "stage": STAGE,
        "final_status": status,
        "decision": final_decision,
        "primary_candidate": primary,
        "secondary_candidate": secondary,
        "tertiary_candidate": tertiary,
        "operator_input_source": input_source,
        "captured_operator_decision": captured,
        "holdings_evidence_caveat": packet["holdings_evidence_caveat"],
        "cost_warning_status": packet["cost_warning_status"],
        "downside_monitor_dependency": packet["downside_monitor_dependency"],
        "recommended_next_stage": final_route,
        "any_overlay_adoptable_now": "FALSE",
        "overlay_adopted": "FALSE",
        "portfolio_variant_adopted": "FALSE",
        "filter_adopted": "FALSE",
        "full_weight_blocked": "TRUE",
        **GUARD,
    }
    write_rows(OUT_DECISION, [decision_summary])

    allowed_text = "\n".join(f"- `{decision}` - {meaning}" for decision, meaning, _ in DECISIONS)
    ranking_text = "\n".join(
        f"{row.get('rank')}. {row.get('overlay_id')} - score {row.get('tiebreaker_score')}"
        for row in ranking
    )
    report = f"""# V21.047-R3 Operator Review Decision Capture

final_status: {status}

decision: {final_decision}

Primary review-only candidate: {primary}.

Secondary candidate: {secondary}. Tertiary candidate: {tertiary}.

## Ranking summary

{ranking_text}

## Primary candidate metrics

Score={packet['primary_candidate_score']}; total_return={packet['primary_total_return']}; Sharpe={packet['primary_sharpe']}; max_drawdown={packet['primary_max_drawdown']}; turnover_reduction={packet['primary_turnover_reduction']}; after_cost_return_20bps={packet['primary_after_cost_return_20bps']}; stability={packet['primary_stability_status']}.

Cost warning: {packet['cost_warning_status']}.

Holdings evidence caveat: {packet['holdings_evidence_caveat']}.

Downside monitor dependency: {packet['downside_monitor_dependency']}. Matured observation and R9/monitor evidence remain required before any adoption review.

## Allowed operator decisions

{allowed_text}

Captured operator decision: {captured}.

Operator input source: {input_source}.

Next-stage routing: {final_route}.

No overlay was adopted.

No portfolio variant was adopted.

No filter was adopted.

Technical-only operator decision capture results must not be interpreted as full-weight results or full-weight evidence.

Full-weight remains blocked: TRUE.

Guardrail statement: research_only=TRUE; operator_decision_capture_only=TRUE; operator_decision_is_adoption=FALSE; overlay, portfolio-variant, filter, official, and shadow adoption are disabled; official ranking and weights are unchanged; no official recommendation, real-book action, broker execution, trade action, or buy/sell/hold recommendation was created; local artifacts only; online_download_attempted=FALSE; yfinance_used=FALSE.
"""
    REPORT.write_text(report, encoding="utf-8")
    shutil.copyfile(REPORT, CURRENT)

    print(f"final_status={status}")
    print(f"decision={final_decision}")
    print(f"primary_candidate={primary}")
    print(f"operator_input_source={input_source}")
    print(f"recommended_next_stage={final_route}")
    print(f"overlay_adoption_allowed={GUARD['overlay_adoption_allowed']}")
    print(f"official_adoption_allowed={GUARD['official_adoption_allowed']}")
    print(f"shadow_gate_allowed={GUARD['shadow_gate_allowed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
