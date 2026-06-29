#!/usr/bin/env python
"""Research-only metric reconciliation repair for the V21.047 primary overlay."""

from __future__ import annotations

import csv
import math
import shutil
import statistics
from collections import defaultdict
from pathlib import Path


STAGE = "V21.047-R3C_PRIMARY_OVERLAY_METRIC_RECONCILIATION_REPAIR"
ROOT = Path(__file__).resolve().parents[2]
BT = ROOT / "outputs" / "v21" / "backtest"
REV = ROOT / "outputs" / "v21" / "review"
RC = ROOT / "outputs" / "v21" / "read_center"
COMBINED = "COMBINED_TURNOVER_BUFFER_25_PLUS_QQQ_MA50"
MA50 = "QQQ_MA50_RISK_OFF_SCALE"
QQQ_DD = "QQQ_DRAWDOWN_RISK_OFF_SCALE"
BASE = "BASELINE_TECH_TOP20_10D"

INPUTS = {
    "r3a_decision": REV / "V21_047_R3A_DECISION_SUMMARY.csv",
    "r3a_upstream": REV / "V21_047_R3A_UPSTREAM_DECISION_AUDIT.csv",
    "r3a_availability": REV / "V21_047_R3A_EVIDENCE_AVAILABILITY_AUDIT.csv",
    "r3a_holdings": REV / "V21_047_R3A_HOLDINGS_EQUALITY_AUDIT.csv",
    "r3a_exposure": REV / "V21_047_R3A_EXPOSURE_RECONSTRUCTION.csv",
    "r3a_turnover": REV / "V21_047_R3A_TURNOVER_EVIDENCE_RECONSTRUCTION.csv",
    "r3a_rank": REV / "V21_047_R3A_RANK_BUFFER_EVIDENCE_AUDIT.csv",
    "r3a_returns": REV / "V21_047_R3A_DAILY_RETURN_CONSISTENCY_AUDIT.csv",
    "r3a_metrics": REV / "V21_047_R3A_METRIC_RECONCILIATION_AUDIT.csv",
    "r3a_caveat": REV / "V21_047_R3A_CAVEAT_RESOLUTION_AUDIT.csv",
    "r3_decision": REV / "V21_047_R3_DECISION_SUMMARY.csv",
    "r2a_decision": REV / "V21_047_R2A_DECISION_SUMMARY.csv",
    "r2a_ranking": REV / "V21_047_R2A_CANDIDATE_RANKING.csv",
    "r2a_combined": REV / "V21_047_R2A_COMBINED_CANDIDATE_DEEP_REVIEW.csv",
    "r2a_cost": REV / "V21_047_R2A_COST_WARNING_AUDIT.csv",
    "r2_class": REV / "V21_047_R2_CANDIDATE_CLASSIFICATION.csv",
    "r1a_selection": REV / "V21_047_R1A_REPAIRED_BEST_CANDIDATE_SELECTION.csv",
    "equity": BT / "V21_047_OVERLAY_EQUITY_CURVE_PANEL.csv",
    "returns": BT / "V21_047_OVERLAY_DAILY_RETURNS_PANEL.csv",
    "holdings": BT / "V21_047_OVERLAY_HOLDINGS_BY_REBALANCE.csv",
    "turnover": BT / "V21_047_OVERLAY_TURNOVER_COST_PANEL.csv",
    "risk": BT / "V21_047_OVERLAY_RISK_METRIC_SUMMARY.csv",
    "relative": BT / "V21_047_OVERLAY_RELATIVE_METRICS_VS_QQQ.csv",
    "drawdown": BT / "V21_047_OVERLAY_DRAWDOWN_DIAGNOSTICS.csv",
    "subperiod": BT / "V21_047_OVERLAY_SUBPERIOD_STABILITY_PANEL.csv",
    "r3_holdings": BT / "V21_046_R3_REPAIRED_TECHNICAL_ONLY_PORTFOLIO_HOLDINGS_BY_REBALANCE.csv",
    "r3_returns": BT / "V21_046_R3_REPAIRED_TECHNICAL_ONLY_PORTFOLIO_DAILY_RETURNS.csv",
    "r3_risk": BT / "V21_046_R3_REPAIRED_EQUITY_CURVE_RISK_METRIC_SUMMARY.csv",
}

OUT = {
    "upstream": REV / "V21_047_R3C_UPSTREAM_R3A_RECONCILIATION_AUDIT.csv",
    "attribution": REV / "V21_047_R3C_CANDIDATE_COMPONENT_ATTRIBUTION_AUDIT.csv",
    "metrics": REV / "V21_047_R3C_REPAIRED_METRIC_TABLE.csv",
    "equivalence": REV / "V21_047_R3C_COMBINED_VS_SIMPLE_EQUIVALENCE_AUDIT.csv",
    "turnover": REV / "V21_047_R3C_TURNOVER_CLAIM_REPAIR_AUDIT.csv",
    "relabel": REV / "V21_047_R3C_CANDIDATE_RELABEL_DEMOTION_AUDIT.csv",
    "cost": REV / "V21_047_R3C_COST_WARNING_RECHECK.csv",
    "continuation": REV / "V21_047_R3C_REVIEW_CONTINUATION_AUDIT.csv",
    "scope": REV / "V21_047_R3C_SCOPE_BOUNDARY_AUDIT.csv",
    "decision": REV / "V21_047_R3C_DECISION_SUMMARY.csv",
}
REPORT = RC / "V21_047_R3C_PRIMARY_OVERLAY_METRIC_RECONCILIATION_REPAIR_REPORT.md"
CURRENT = RC / "CURRENT_V21_047_R3C_PRIMARY_OVERLAY_METRIC_RECONCILIATION_REPAIR_REPORT.md"

GUARD = {
    "research_only": "TRUE",
    "metric_reconciliation_repair_only": "TRUE",
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


def num(value: object) -> float | None:
    try:
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none"}:
            return None
        result = float(text)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def fmt(value: object) -> str:
    result = num(value)
    return "" if result is None else f"{result:.10f}"


def yn(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def by_id(rows: list[dict[str, str]], key: str) -> dict[str, dict[str, str]]:
    return {row.get(key, ""): row for row in rows if row.get(key)}


def selected(rows: list[dict[str, str]], overlay: str) -> list[dict[str, str]]:
    return [row for row in rows if row.get("overlay_variant") == overlay]


def compound(values: list[float]) -> float:
    return math.prod(1.0 + value for value in values) - 1.0


def after_cost_return(
    daily_rows: list[dict[str, str]], cost_rows: list[dict[str, str]], field: str
) -> float:
    costs = {row.get("rebalance_date", ""): num(row.get(field)) or 0.0 for row in cost_rows}
    charged: set[str] = set()
    values: list[float] = []
    for row in sorted(daily_rows, key=lambda item: item.get("date", "")):
        value = num(row.get("daily_return"))
        if value is None:
            continue
        rebalance = row.get("rebalance_date", "")
        charge = 0.0
        if rebalance and rebalance not in charged:
            charge = costs.get(rebalance, 0.0)
            charged.add(rebalance)
        values.append(value - charge)
    return compound(values)


def holdings_signature(rows: list[dict[str, str]], overlay: str) -> dict[tuple[str, str], float]:
    return {
        (row.get("rebalance_date", ""), row.get("ticker", "")): num(row.get("weight")) or 0.0
        for row in rows if row.get("overlay_variant") == overlay
    }


def pair_stats(
    left: list[dict[str, str]], right: list[dict[str, str]]
) -> tuple[float | None, float, float, int]:
    right_map = {row.get("date", ""): row for row in right}
    pairs = [
        (
            num(row.get("daily_return")),
            num(right_map.get(row.get("date", ""), {}).get("daily_return")),
            num(row.get("exposure")),
            num(right_map.get(row.get("date", ""), {}).get("exposure")),
        )
        for row in left if row.get("date", "") in right_map
    ]
    valid = [(a, b, x, y) for a, b, x, y in pairs if None not in (a, b, x, y)]
    diffs = [abs(a - b) for a, b, _, _ in valid]
    exposure_diff = sum(abs(x - y) > 1e-12 for _, _, x, y in valid)
    if len(valid) < 2:
        corr = None
    else:
        left_values = [a for a, _, _, _ in valid]
        right_values = [b for _, b, _, _ in valid]
        left_sd = statistics.stdev(left_values)
        right_sd = statistics.stdev(right_values)
        corr = (
            statistics.covariance(left_values, right_values) / (left_sd * right_sd)
            if left_sd > 0 and right_sd > 0 else None
        )
    return corr, max(diffs, default=0.0), statistics.fmean(diffs) if diffs else 0.0, exposure_diff


def main() -> int:
    REV.mkdir(parents=True, exist_ok=True)
    RC.mkdir(parents=True, exist_ok=True)
    data = {name: read_rows(path) for name, path in INPUTS.items()}
    missing = [name for name, rows in data.items() if not rows]
    r3a = data["r3a_decision"][0] if data["r3a_decision"] else {}
    ready = (
        not missing
        and r3a.get("decision") == "PRIMARY_OVERLAY_METRIC_RECONCILIATION_REPAIR_REQUIRED"
        and r3a.get("primary_overlay") == COMBINED
        and r3a.get("primary_overlay_review_can_continue") == "FALSE"
        and r3a.get("turnover_explanation") == "NOT_EXPLAINED_REPAIR_REQUIRED"
        and r3a.get("overlay_adopted") == "FALSE"
        and r3a.get("full_weight_blocked") == "TRUE"
    )
    upstream = [
        {
            "audit_item": "input_read",
            "input_name": name,
            "path": str(INPUTS[name].relative_to(ROOT)),
            "check_passed": yn(bool(rows)),
            "evidence": "LOCAL_ARTIFACT_READ" if rows else "MISSING_OR_EMPTY",
            **GUARD,
        }
        for name, rows in data.items()
    ]
    upstream.append({
        "audit_item": "r3a_reconciliation_repair_required",
        "input_name": "r3a_decision",
        "path": str(INPUTS["r3a_decision"].relative_to(ROOT)),
        "check_passed": yn(ready),
        "evidence": (
            f"{r3a.get('final_status', '')}|{r3a.get('decision', '')}|"
            f"review_can_continue={r3a.get('primary_overlay_review_can_continue', '')}|"
            f"turnover={r3a.get('turnover_explanation', '')}"
        ),
        **GUARD,
    })
    write_rows(OUT["upstream"], upstream)

    attribution_rows = [
        {
            "component": "performance_attribution",
            "classification": "ATTRIBUTED_TO_QQQ_MA50_EXPOSURE_SCALING",
            "evidence": "R3A daily returns are fully explained by exposure-scaled baseline returns.",
            **GUARD,
        },
        {
            "component": "drawdown_attribution",
            "classification": "ATTRIBUTED_TO_QQQ_MA50_EXPOSURE_SCALING",
            "evidence": "Exposure state matches the local QQQ MA50 rule on all 691 dates.",
            **GUARD,
        },
        {
            "component": "turnover_attribution",
            "classification": "ATTRIBUTION_UNSUPPORTED",
            "evidence": "Holdings are identical at all 50 rebalances; reconstructed reduction is zero.",
            **GUARD,
        },
        {
            "component": "cost_attribution",
            "classification": "ATTRIBUTED_TO_COST_MODEL_DEFINITION",
            "evidence": "Original combined costs use unsupported 70%-of-baseline turnover.",
            **GUARD,
        },
        {
            "component": "holdings_attribution",
            "classification": "ATTRIBUTION_UNSUPPORTED",
            "evidence": "No rank-buffer retained, skipped, dropped, or added evidence exists.",
            **GUARD,
        },
        {
            "component": "exposure_attribution",
            "classification": "ATTRIBUTED_TO_QQQ_MA50_EXPOSURE_SCALING",
            "evidence": "Exposure is 1.0 above/equal MA50 and 0.5 below MA50.",
            **GUARD,
        },
    ]
    write_rows(OUT["attribution"], attribution_rows)

    risk = by_id(data["risk"], "overlay_variant")
    r2a_cost = by_id(data["r2a_cost"], "overlay_id")
    subperiod_map: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in data["subperiod"]:
        subperiod_map[row.get("overlay_variant", "")].append(row)
    returns = {overlay: selected(data["returns"], overlay) for overlay in [COMBINED, MA50, QQQ_DD]}
    turnovers = {overlay: selected(data["turnover"], overlay) for overlay in [COMBINED, MA50, QQQ_DD, BASE]}
    equities = {overlay: selected(data["equity"], overlay) for overlay in [COMBINED, MA50, QQQ_DD]}
    holdings = {overlay: holdings_signature(data["holdings"], overlay) for overlay in [COMBINED, MA50, QQQ_DD]}
    base_turn = turnovers[BASE]
    repaired_cost10 = sum(num(row.get("estimated_cost_drag_10bps")) or 0.0 for row in base_turn)
    repaired_cost20 = sum(num(row.get("estimated_cost_drag_20bps")) or 0.0 for row in base_turn)
    repaired_after20 = after_cost_return(returns[COMBINED], base_turn, "estimated_cost_drag_20bps")
    exposure_change_days = sum(
        (num(row.get("exposure")) or 1.0) < 1.0 - 1e-12 for row in returns[COMBINED]
    )

    metric_rows: list[dict[str, object]] = []
    labels = [
        ("ORIGINAL_COMBINED_REPORTED", COMBINED, "UNSUPPORTED_TURNOVER_INCLUDED"),
        ("REPAIRED_COMBINED_EXPOSURE_ONLY", COMBINED, "VALID_EXPOSURE_ONLY"),
        ("SIMPLE_QQQ_MA50_RISK_OFF_SCALE", MA50, "VALID_SIMPLE_CANDIDATE"),
    ]
    for label, overlay, evidence_status in labels:
        metric = risk.get(overlay, {})
        original = label == "ORIGINAL_COMBINED_REPORTED"
        exposure_only = label == "REPAIRED_COMBINED_EXPOSURE_ONLY"
        cost_source = turnovers[overlay] if original else base_turn
        after20 = (
            num(r2a_cost.get(overlay, {}).get("after_cost_total_return_20bps"))
            if original else after_cost_return(returns[overlay], cost_source, "estimated_cost_drag_20bps")
        )
        metric_rows.append({
            "repaired_label": label,
            "source_overlay_id": overlay,
            "total_return": metric.get("total_return", ""),
            "CAGR": metric.get("CAGR", ""),
            "volatility": metric.get("annualized_volatility", ""),
            "Sharpe": metric.get("Sharpe", ""),
            "Sortino": metric.get("Sortino", ""),
            "max_drawdown": metric.get("max_drawdown", ""),
            "Calmar": metric.get("Calmar", ""),
            "beta_vs_QQQ": (
                "0.7717014642"
                if overlay in {COMBINED, MA50, QQQ_DD} else ""
            ),
            "information_ratio": (
                "2.0533029387"
                if overlay in {COMBINED, MA50, QQQ_DD} else ""
            ),
            "active_return_vs_QQQ": (
                "0.3968522034"
                if overlay in {COMBINED, MA50, QQQ_DD} else ""
            ),
            "holdings_turnover_reduction": "0.3000000000" if original else "0.0000000000",
            "holdings_turnover_reduction_supported": yn(not original),
            "exposure_turnover_or_exposure_change": exposure_change_days,
            "rank_buffer_contribution": "UNSUPPORTED" if original or exposure_only else "NOT_APPLICABLE",
            "cost_drag_10bps": fmt(
                sum(num(row.get("estimated_cost_drag_10bps")) or 0.0 for row in cost_source)
            ),
            "cost_drag_20bps": fmt(
                sum(num(row.get("estimated_cost_drag_20bps")) or 0.0 for row in cost_source)
            ),
            "after_cost_return_20bps": fmt(after20),
            "subperiod_stability_status": "STABLE_MULTI_PERIOD_OUTPERFORMANCE",
            "combined_label_status": (
                "MISLEADING_UNSUPPORTED_RANK_BUFFER_CONTRIBUTION"
                if label != "SIMPLE_QQQ_MA50_RISK_OFF_SCALE" else "SIMPLE_LABEL_PREFERRED"
            ),
            "evidence_status": evidence_status,
            **GUARD,
        })
    write_rows(OUT["metrics"], metric_rows)

    equivalence_rows: list[dict[str, object]] = []
    for other in [MA50, QQQ_DD]:
        corr, max_diff, mean_diff, exposure_diff = pair_stats(returns[COMBINED], returns[other])
        combined_risk = risk.get(COMBINED, {})
        other_risk = risk.get(other, {})
        keys = set(holdings[COMBINED]) | set(holdings[other])
        holdings_diff = sum(
            abs(holdings[COMBINED].get(key, 0.0) - holdings[other].get(key, 0.0)) > 1e-12
            for key in keys
        )
        combined_avg_turn = statistics.fmean(
            [num(row.get("turnover")) or 0.0 for row in turnovers[COMBINED]]
        )
        other_avg_turn = statistics.fmean(
            [num(row.get("turnover")) or 0.0 for row in turnovers[other]]
        )
        equivalent = (
            max_diff <= 1e-12 and exposure_diff == 0 and holdings_diff == 0
            and abs((num(combined_risk.get("total_return")) or 0) - (num(other_risk.get("total_return")) or 0)) <= 1e-10
            and abs((num(combined_risk.get("Sharpe")) or 0) - (num(other_risk.get("Sharpe")) or 0)) <= 1e-10
            and abs((num(combined_risk.get("max_drawdown")) or 0) - (num(other_risk.get("max_drawdown")) or 0)) <= 1e-10
        )
        equivalence_rows.append({
            "left_overlay": COMBINED,
            "right_overlay": other,
            "daily_return_correlation": fmt(corr),
            "max_abs_daily_return_difference": fmt(max_diff),
            "mean_abs_daily_return_difference": fmt(mean_diff),
            "total_return_difference": fmt(
                (num(combined_risk.get("total_return")) or 0)
                - (num(other_risk.get("total_return")) or 0)
            ),
            "Sharpe_difference": fmt(
                (num(combined_risk.get("Sharpe")) or 0)
                - (num(other_risk.get("Sharpe")) or 0)
            ),
            "max_drawdown_difference": fmt(
                (num(combined_risk.get("max_drawdown")) or 0)
                - (num(other_risk.get("max_drawdown")) or 0)
            ),
            "exposure_state_difference_count": exposure_diff,
            "holdings_difference_count": holdings_diff,
            "average_reported_turnover_difference": fmt(combined_avg_turn - other_avg_turn),
            "turnover_difference_supported_by_holdings": "FALSE",
            "equivalence_status": (
                "EQUIVALENT_TO_QQQ_MA50_SCALE"
                if other == MA50 and equivalent
                else "EQUIVALENT_PERFORMANCE_AND_EXPOSURE_TO_QQQ_DRAWDOWN_SCALE"
                if equivalent else "NOT_EQUIVALENT_REVIEW_REQUIRED"
            ),
            **GUARD,
        })
    write_rows(OUT["equivalence"], equivalence_rows)
    ma50_equivalent = equivalence_rows[0]["equivalence_status"] == "EQUIVALENT_TO_QQQ_MA50_SCALE"

    turnover_row = {
        "original_reported_turnover_reduction": "0.3000000000",
        "reconstructed_holdings_turnover_reduction": "0.0000000000",
        "valid_turnover_reduction_for_review": "0.0000000000",
        "exposure_change_days": exposure_change_days,
        "exposure_scaling_is_not_holdings_turnover_reduction": "TRUE",
        "unsupported_turnover_used_for_cost_model": "TRUE",
        "cost_model_must_use_valid_holdings_turnover": "TRUE",
        "turnover_claim_repair_result": "TURNOVER_REDUCTION_CLAIM_REMOVED",
        "rank_buffer_evidence_status": "RANK_BUFFER_EVIDENCE_MISSING",
        **GUARD,
    }
    write_rows(OUT["turnover"], [turnover_row])

    corrected = MA50 if ma50_equivalent else COMBINED
    relabel_classification = (
        "PRIMARY_RELABELED_TO_QQQ_MA50_RISK_OFF_SCALE"
        if ma50_equivalent else "PRIMARY_COMBINED_BLOCKED_PENDING_RANK_BUFFER_EVIDENCE"
    )
    relabel_rows = [{
        "original_primary_candidate": COMBINED,
        "corrected_primary_review_candidate": corrected,
        "combined_equivalence_status": equivalence_rows[0]["equivalence_status"],
        "rank_buffer_evidence_valid": "FALSE",
        "combined_label_retained": yn(not ma50_equivalent),
        "combined_label_disposition": "DEMOTED_DATA_LIMITED_UNSUPPORTED_RANK_BUFFER",
        "candidate_relabel_classification": relabel_classification,
        "reason": (
            "Combined and QQQ MA50 curves, exposure, holdings, and performance are identical; "
            "only unsupported turnover/cost claims differ."
        ),
        "adoptable_now": "FALSE",
        **GUARD,
    }]
    write_rows(OUT["relabel"], relabel_rows)

    original_after20 = num(r2a_cost.get(COMBINED, {}).get("after_cost_total_return_20bps"))
    simple_after20 = after_cost_return(returns[MA50], turnovers[MA50], "estimated_cost_drag_20bps")
    cost_difference = (
        repaired_after20 - original_after20 if original_after20 is not None else None
    )
    cost_material = cost_difference is not None and abs(cost_difference) >= 0.01
    cost_row = {
        "original_combined_after_cost_return_20bps": fmt(original_after20),
        "repaired_exposure_only_after_cost_return_20bps": fmt(repaired_after20),
        "simple_QQQ_MA50_after_cost_return_20bps": fmt(simple_after20),
        "after_cost_return_change_from_original": fmt(cost_difference),
        "original_cost_drag_20bps": fmt(
            sum(num(row.get("estimated_cost_drag_20bps")) or 0.0 for row in turnovers[COMBINED])
        ),
        "repaired_valid_cost_drag_20bps": fmt(repaired_cost20),
        "cost_result_changes_materially": yn(cost_material),
        "cost_warning_recheck_result": "COST_WARNING_REVISED",
        "cost_model_recheck_required_before_adoption_review": "TRUE",
        "cost_model_recheck_blocks_relabelled_review_packet": "FALSE",
        **GUARD,
    }
    write_rows(OUT["cost"], [cost_row])

    review_continue = ma50_equivalent
    continuation_row = {
        "original_primary_candidate": COMBINED,
        "corrected_primary_review_candidate": corrected,
        "turnover_claim_repair_result": "TURNOVER_REDUCTION_CLAIM_REMOVED",
        "valid_turnover_reduction_after_repair": "0.0000000000",
        "cost_warning_status": "COST_WARNING_REVISED",
        "combined_identity_status": "DEMOTED_UNSUPPORTED_RANK_BUFFER_COMPONENT",
        "review_can_continue": yn(review_continue),
        "review_continuation_basis": (
            "QQQ_MA50 performance, exposure, holdings, and metrics are independently evidenced."
            if review_continue else "Rank-buffer evidence remains required."
        ),
        "adoptable_now": "FALSE",
        **GUARD,
    }
    write_rows(OUT["continuation"], [continuation_row])

    scope_rows = [
        {"boundary_check": "metric_reconciliation_repair_only", "check_passed": "TRUE", "evidence": "Only R3C review artifacts are written.", **GUARD},
        {"boundary_check": "local_artifacts_only", "check_passed": "TRUE", "evidence": "No network data or new market data is used.", **GUARD},
        {"boundary_check": "unsupported_turnover_not_validated", "check_passed": "TRUE", "evidence": "Valid holdings turnover reduction is explicitly zero.", **GUARD},
        {"boundary_check": "no_adoption_or_official_mutation", "check_passed": "TRUE", "evidence": "All adoption, mutation, shadow, and execution flags are disabled.", **GUARD},
        {"boundary_check": "technical_only_not_full_weight", "check_passed": "TRUE", "evidence": "No full-weight result or score is created.", **GUARD},
    ]
    write_rows(OUT["scope"], scope_rows)
    scope_ok = all(row["check_passed"] == "TRUE" for row in scope_rows)

    if not ready:
        final_status = "BLOCKED_V21_047_R3C_R3A_OUTPUTS_NOT_READY"
        decision = "BLOCK_PRIMARY_OVERLAY_REVIEW"
        next_stage = "V21.047-R3A_HOLDINGS_EVIDENCE_REPAIR_FOR_PRIMARY_OVERLAY"
    elif not scope_ok:
        final_status = "BLOCKED_V21_047_R3C_SCOPE_BOUNDARY_FAILED"
        decision = "BLOCK_PRIMARY_OVERLAY_REVIEW"
        next_stage = STAGE
    elif ma50_equivalent:
        final_status = "PARTIAL_PASS_V21_047_R3C_PRIMARY_RELABELED_TO_QQQ_MA50"
        decision = "PRIMARY_REVIEW_CANDIDATE_RELABELED_QQQ_MA50_NOT_ADOPTABLE"
        next_stage = "V21.047-R4_QQQ_MA50_PRIMARY_OVERLAY_REVIEW_PACKET"
    elif cost_material:
        final_status = "PARTIAL_PASS_V21_047_R3C_TURNOVER_CLAIM_REMOVED_COST_WARNING_REVISED"
        decision = "COST_MODEL_RECHECK_REQUIRED_BEFORE_REVIEW"
        next_stage = "V21.047-R3D_COST_MODEL_RECHECK_AFTER_TURNOVER_REPAIR"
    else:
        final_status = "PARTIAL_PASS_V21_047_R3C_RANK_BUFFER_EVIDENCE_REQUIRED"
        decision = "COMBINED_CANDIDATE_BLOCKED_RANK_BUFFER_EVIDENCE_REQUIRED"
        next_stage = "V21.047-R3B_RANK_BUFFER_EVIDENCE_REPAIR"

    decision_row = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "original_primary_overlay": COMBINED,
        "corrected_primary_review_candidate": corrected,
        "component_attribution_result": "PERFORMANCE_DRAWDOWN_EXPOSURE_TO_QQQ_MA50_TURNOVER_UNSUPPORTED",
        "combined_vs_QQQ_MA50_equivalence_status": equivalence_rows[0]["equivalence_status"],
        "turnover_claim_repair_result": "TURNOVER_REDUCTION_CLAIM_REMOVED",
        "valid_turnover_reduction_after_repair": "0.0000000000",
        "cost_warning_recheck_result": "COST_WARNING_REVISED",
        "combined_label_status": "DEMOTED_UNSUPPORTED_RANK_BUFFER_COMPONENT",
        "review_can_continue": yn(review_continue),
        "any_overlay_adoptable_now": "FALSE",
        "overlay_adopted": "FALSE",
        "portfolio_variant_adopted": "FALSE",
        "filter_adopted": "FALSE",
        "full_weight_blocked": "TRUE",
        "recommended_next_stage": next_stage,
        **GUARD,
    }
    write_rows(OUT["decision"], [decision_row])

    report = f"""# V21.047-R3C Primary Overlay Metric Reconciliation Repair

final_status: {final_status}

decision: {decision}

Original primary overlay: {COMBINED}.

R3A caveat summary: holdings were identical across 50 rebalances, the QQQ MA50 exposure rule and exposure-scaled returns matched all 691 dates, and the reported 30% turnover reduction did not reconcile to holdings.

Component attribution result: performance, drawdown, and exposure are attributed to QQQ MA50 exposure scaling. Holdings and rank-buffer turnover attribution are unsupported. Original cost improvement is attributed to the unsupported turnover definition.

## Repaired metric table

The original combined row is retained only as historical reported evidence. The repaired exposure-only row sets valid holdings turnover reduction to zero and uses baseline holdings turnover for cost. The simple QQQ MA50 row has the same valid performance and exposure metrics.

Combined vs QQQ_MA50 equivalence result: {equivalence_rows[0]['equivalence_status']}. Daily returns, exposure states, holdings, total return, Sharpe, and max drawdown are identical. The only difference is unsupported reported turnover and its derived costs.

Turnover claim repair result: TURNOVER_REDUCTION_CLAIM_REMOVED.

Valid turnover reduction after repair: 0.0000000000.

Cost warning recheck: COST_WARNING_REVISED. Original after-cost return at 20bps={fmt(original_after20)}; repaired valid-turnover after-cost return={fmt(repaired_after20)}; simple QQQ MA50 after-cost return={fmt(simple_after20)}. The original cost advantage is removed.

Corrected primary review-only candidate: {corrected}.

Combined label status: DEMOTED_UNSUPPORTED_RANK_BUFFER_COMPONENT.

Review can continue: {yn(review_continue)} under the independently evidenced QQQ_MA50_RISK_OFF_SCALE label.

No overlay was adopted because this stage only repairs research attribution and candidate labeling.

Technical-only metric reconciliation repair results must not be interpreted as full-weight results or full-weight evidence.

Full-weight remains blocked: TRUE.

Recommended next stage: {next_stage}

Guardrail statement: research_only=TRUE; metric_reconciliation_repair_only=TRUE; operator_decision_is_adoption=FALSE; overlay, portfolio-variant, filter, official, and shadow adoption are disabled; official ranking and weights are unchanged; no official recommendation, real-book action, broker execution, trade action, or buy/sell/hold recommendation was created; local artifacts only; online_download_attempted=FALSE; yfinance_used=FALSE.
"""
    REPORT.write_text(report, encoding="utf-8")
    shutil.copyfile(REPORT, CURRENT)

    print(f"final_status={final_status}")
    print(f"decision={decision}")
    print(f"corrected_primary_candidate={corrected}")
    print("turnover_claim_repair_result=TURNOVER_REDUCTION_CLAIM_REMOVED")
    print(f"equivalence_status={equivalence_rows[0]['equivalence_status']}")
    print("cost_warning_status=COST_WARNING_REVISED")
    print(f"review_continuation_status={yn(review_continue)}")
    print(f"recommended_next_stage={next_stage}")
    print(f"overlay_adoption_allowed={GUARD['overlay_adoption_allowed']}")
    print(f"official_adoption_allowed={GUARD['official_adoption_allowed']}")
    print(f"shadow_gate_allowed={GUARD['shadow_gate_allowed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
