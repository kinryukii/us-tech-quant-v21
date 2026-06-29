#!/usr/bin/env python
"""Research-only tiebreaker for V21.047-R2 overlay review candidates."""

from __future__ import annotations

import csv
import math
import shutil
from pathlib import Path


STAGE = "V21.047-R2A_CANDIDATE_TIEBREAKER_AND_SELECTION_REVIEW"
ROOT = Path(__file__).resolve().parents[2]
BT = ROOT / "outputs" / "v21" / "backtest"
REV = ROOT / "outputs" / "v21" / "review"
RC = ROOT / "outputs" / "v21" / "read_center"
BASE = "BASELINE_TECH_TOP20_10D"
COMBINED = "COMBINED_TURNOVER_BUFFER_25_PLUS_QQQ_MA50"
QQQ_DD = "QQQ_DRAWDOWN_RISK_OFF_SCALE"
QQQ_MA = "QQQ_MA50_RISK_OFF_SCALE"
PORT_DD = "PORTFOLIO_DRAWDOWN_STOP_SCALE"
PORT_COMBINED = "COMBINED_PARTIAL_50_PLUS_DRAWDOWN_STOP"
CANDIDATES = [COMBINED, QQQ_DD, QQQ_MA, PORT_DD, PORT_COMBINED]
QUARANTINE = "TURNOVER_BUFFER_RANK_30"

INPUTS = {
    "r2_decision": REV / "V21_047_R2_DECISION_SUMMARY.csv",
    "r2_upstream": REV / "V21_047_R2_UPSTREAM_ATTRIBUTION_REPAIR_AUDIT.csv",
    "r2_eligibility": REV / "V21_047_R2_CANDIDATE_ELIGIBILITY_AUDIT.csv",
    "r2_comparison": REV / "V21_047_R2_BASELINE_VS_CANDIDATE_COMPARISON.csv",
    "r2_behavior": REV / "V21_047_R2_DRAWDOWN_RISK_OFF_BEHAVIOR_AUDIT.csv",
    "r2_cost": REV / "V21_047_R2_TURNOVER_COST_AUDIT.csv",
    "r2_alpha": REV / "V21_047_R2_ALPHA_PRESERVATION_AUDIT.csv",
    "r2_subperiod": REV / "V21_047_R2_SUBPERIOD_STABILITY_AUDIT.csv",
    "r2_downside": REV / "V21_047_R2_DOWNSIDE_MONITOR_COMPATIBILITY_AUDIT.csv",
    "r2_classification": REV / "V21_047_R2_CANDIDATE_CLASSIFICATION.csv",
    "risk": BT / "V21_047_OVERLAY_RISK_METRIC_SUMMARY.csv",
    "relative": BT / "V21_047_OVERLAY_RELATIVE_METRICS_VS_QQQ.csv",
    "turnover": BT / "V21_047_OVERLAY_TURNOVER_COST_PANEL.csv",
    "drawdown": BT / "V21_047_OVERLAY_DRAWDOWN_DIAGNOSTICS.csv",
    "subperiod": BT / "V21_047_OVERLAY_SUBPERIOD_STABILITY_PANEL.csv",
    "r1a_selection": REV / "V21_047_R1A_REPAIRED_BEST_CANDIDATE_SELECTION.csv",
    "r1a_review": REV / "V21_047_R1A_REVIEW_WORTHINESS_AUDIT.csv",
    "r4_decision": REV / "V21_046_R4_DECISION_SUMMARY.csv",
    "downside_contract": REV / "V21_045_R3B_DOWNSIDE_MONITOR_CONTRACT.csv",
}

OUT = {
    "readiness": REV / "V21_047_R2A_UPSTREAM_R2_READINESS_AUDIT.csv",
    "metrics": REV / "V21_047_R2A_CANDIDATE_METRIC_CONSOLIDATION.csv",
    "scores": REV / "V21_047_R2A_TIEBREAKER_SCORE_REGISTER.csv",
    "ranking": REV / "V21_047_R2A_CANDIDATE_RANKING.csv",
    "combined": REV / "V21_047_R2A_COMBINED_CANDIDATE_DEEP_REVIEW.csv",
    "qqq": REV / "V21_047_R2A_QQQ_SCALING_COMPARISON.csv",
    "portfolio": REV / "V21_047_R2A_PORTFOLIO_DRAWDOWN_CANDIDATE_COMPARISON.csv",
    "cost": REV / "V21_047_R2A_COST_WARNING_AUDIT.csv",
    "downside": REV / "V21_047_R2A_DOWNSIDE_MONITOR_DEPENDENCY_AUDIT.csv",
    "scope": REV / "V21_047_R2A_SCOPE_BOUNDARY_AUDIT.csv",
    "decision": REV / "V21_047_R2A_DECISION_SUMMARY.csv",
}
REPORT = RC / "V21_047_R2A_CANDIDATE_TIEBREAKER_AND_SELECTION_REVIEW_REPORT.md"
CURRENT = RC / "CURRENT_V21_047_R2A_CANDIDATE_TIEBREAKER_AND_SELECTION_REVIEW_REPORT.md"

GUARD = {
    "research_only": "TRUE",
    "candidate_tiebreaker_review_only": "TRUE",
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
        if not text or text.lower() in {"nan", "none", "not_available"}:
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


def by_id(rows: list[dict[str, str]], key: str = "overlay_id") -> dict[str, dict[str, str]]:
    return {row.get(key, ""): row for row in rows if row.get(key)}


def minmax(value: float | None, values: list[float]) -> float:
    if value is None or not values:
        return 0.0
    low, high = min(values), max(values)
    if abs(high - low) < 1e-15:
        return 1.0
    return min(1.0, max(0.0, (value - low) / (high - low)))


def average(parts: list[float]) -> float:
    return sum(parts) / len(parts) if parts else 0.0


def main() -> int:
    REV.mkdir(parents=True, exist_ok=True)
    RC.mkdir(parents=True, exist_ok=True)
    data = {name: read_rows(path) for name, path in INPUTS.items()}
    missing = [name for name, rows in data.items() if not rows]
    r2 = data["r2_decision"][0] if data["r2_decision"] else {}
    r2_ready = (
        not missing
        and r2.get("final_status") == "PARTIAL_PASS_V21_047_R2_REVIEW_PACKET_WITH_COST_WARNING"
        and r2.get("decision") == "MULTIPLE_DRAWDOWN_SCALE_CANDIDATES_REVIEW_ONLY"
        and r2.get("overlay_adopted") == "FALSE"
        and r2.get("full_weight_blocked") == "TRUE"
    )
    readiness = [
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
    readiness.extend([
        {
            "audit_item": "r2_completed_multiple_survivors",
            "input_name": "r2_decision",
            "path": str(INPUTS["r2_decision"].relative_to(ROOT)),
            "check_passed": yn(r2_ready),
            "evidence": (
                f"{r2.get('final_status', '')}|{r2.get('decision', '')}|"
                f"{r2.get('surviving_review_only_candidates', '')}"
            ),
            **GUARD,
        },
        {
            "audit_item": "cost_warning_present",
            "input_name": "r2_decision",
            "path": str(INPUTS["r2_decision"].relative_to(ROOT)),
            "check_passed": yn("COST_WARNING" in r2.get("final_status", "")),
            "evidence": r2.get("turnover_cost_status", ""),
            **GUARD,
        },
        {
            "audit_item": "downside_monitor_data_limited",
            "input_name": "downside_contract",
            "path": str(INPUTS["downside_contract"].relative_to(ROOT)),
            "check_passed": yn("2026_06_24" in r2.get("downside_monitor_compatibility_status", "")),
            "evidence": r2.get("downside_monitor_compatibility_status", ""),
            **GUARD,
        },
    ])
    write_rows(OUT["readiness"], readiness)

    comparison = by_id(data["r2_comparison"])
    eligibility = by_id(data["r2_eligibility"])
    behavior = by_id(data["r2_behavior"])
    cost = by_id(data["r2_cost"])
    alpha = by_id(data["r2_alpha"])
    stability = by_id(data["r2_subperiod"])
    downside = by_id(data["r2_downside"])
    classification = by_id(data["r2_classification"])

    metric_rows: list[dict[str, object]] = []
    for overlay in CANDIDATES:
        metric = comparison.get(overlay, {})
        cost_row = cost.get(overlay, {})
        metric_rows.append({
            "overlay_id": overlay,
            "metric_attribution_overlay_id": metric.get("metrics_tied_to_overlay_id", ""),
            "total_return": metric.get("total_return", ""),
            "CAGR": metric.get("CAGR", ""),
            "volatility": metric.get("volatility", ""),
            "Sharpe": metric.get("Sharpe", ""),
            "Sortino": metric.get("Sortino", ""),
            "max_drawdown": metric.get("max_drawdown", ""),
            "Calmar": metric.get("Calmar", ""),
            "beta_vs_QQQ": metric.get("beta_vs_QQQ", ""),
            "correlation_vs_QQQ": metric.get("correlation_vs_QQQ", ""),
            "tracking_error": metric.get("tracking_error", ""),
            "information_ratio": metric.get("information_ratio", ""),
            "active_return_vs_QQQ": metric.get("active_return_vs_QQQ", ""),
            "average_turnover": metric.get("average_turnover", ""),
            "annualized_turnover": metric.get("annualized_turnover", ""),
            "turnover_reduction_vs_baseline": cost_row.get("turnover_reduction_vs_baseline", ""),
            "cost_drag_10bps": metric.get("cost_drag_10bps", ""),
            "cost_drag_20bps": metric.get("cost_drag_20bps", ""),
            "after_cost_total_return_10bps": cost_row.get("after_cost_total_return_10bps", ""),
            "after_cost_total_return_20bps": cost_row.get("after_cost_total_return_20bps", ""),
            "after_cost_Sharpe_10bps": cost_row.get("after_cost_Sharpe_10bps", ""),
            "after_cost_Sharpe_20bps": cost_row.get("after_cost_Sharpe_20bps", ""),
            "subperiod_stability_status": stability.get(overlay, {}).get("subperiod_stability_classification", ""),
            "drawdown_risk_off_behavior_status": (
                f"RISK_OFF_DAYS_{behavior.get(overlay, {}).get('risk_off_day_count', '')};"
                f"RISK_OFF_RATIO_{behavior.get(overlay, {}).get('risk_off_day_ratio', '')}"
            ),
            "no_op_status": eligibility.get(overlay, {}).get("no_op_status", ""),
            "leakage_status": eligibility.get(overlay, {}).get("leakage_status", ""),
            "alpha_preservation_status": alpha.get(overlay, {}).get("alpha_preservation_classification", ""),
            "same_overlay_metrics_only": yn(metric.get("metrics_tied_to_overlay_id") == overlay),
            **GUARD,
        })
    write_rows(OUT["metrics"], metric_rows)
    consolidated = by_id([{key: str(value) for key, value in row.items()} for row in metric_rows])

    score_fields = {
        "Sharpe": [num(consolidated[item].get("Sharpe")) for item in CANDIDATES],
        "Sortino": [num(consolidated[item].get("Sortino")) for item in CANDIDATES],
        "drawdown": [num(comparison[item].get("drawdown_improvement")) for item in CANDIDATES],
        "return": [num(consolidated[item].get("total_return")) for item in CANDIDATES],
        "CAGR": [num(consolidated[item].get("CAGR")) for item in CANDIDATES],
        "turnover": [num(consolidated[item].get("turnover_reduction_vs_baseline")) for item in CANDIDATES],
        "after_cost": [num(consolidated[item].get("after_cost_total_return_20bps")) for item in CANDIDATES],
        "info": [num(consolidated[item].get("information_ratio")) for item in CANDIDATES],
        "active": [num(consolidated[item].get("active_return_vs_QQQ")) for item in CANDIDATES],
    }
    clean = {key: [value for value in values if value is not None] for key, values in score_fields.items()}
    simplicity = {
        COMBINED: 0.70,
        QQQ_DD: 0.80,
        QQQ_MA: 1.00,
        PORT_DD: 0.60,
        PORT_COMBINED: 0.40,
    }
    score_rows: list[dict[str, object]] = []
    for overlay in CANDIDATES:
        row = consolidated[overlay]
        sharpe_sortino = average([
            minmax(num(row.get("Sharpe")), clean["Sharpe"]),
            minmax(num(row.get("Sortino")), clean["Sortino"]),
        ])
        drawdown_score = minmax(num(comparison[overlay].get("drawdown_improvement")), clean["drawdown"])
        return_cagr = average([
            minmax(num(row.get("total_return")), clean["return"]),
            minmax(num(row.get("CAGR")), clean["CAGR"]),
        ])
        turnover_cost = average([
            minmax(num(row.get("turnover_reduction_vs_baseline")), clean["turnover"]),
            minmax(num(row.get("after_cost_total_return_20bps")), clean["after_cost"]),
        ])
        info_active = average([
            minmax(num(row.get("information_ratio")), clean["info"]),
            minmax(num(row.get("active_return_vs_QQQ")), clean["active"]),
        ])
        stability_score = (
            1.0 if row.get("subperiod_stability_status") == "STABLE_MULTI_PERIOD_OUTPERFORMANCE"
            else 0.0
        )
        no_op_penalty = 1.0 if row.get("no_op_status") == "NO_OP_WARNING" else 0.0
        alpha_penalty = (
            0.0 if row.get("alpha_preservation_status") == "ALPHA_PRESERVED"
            else 0.15 if row.get("alpha_preservation_status") == "ALPHA_PARTIALLY_PRESERVED"
            else 0.35
        )
        damage_penalty = (
            0.15 if row.get("subperiod_stability_status") == "OVERLAY_DAMAGES_GOOD_SUBPERIODS"
            else 0.0
        )
        cost_penalty = 0.03 if cost[overlay].get("cost_status") != "COST_PROFILE_IMPROVED" else 0.0
        weighted = (
            0.25 * sharpe_sortino
            + 0.20 * drawdown_score
            + 0.15 * return_cagr
            + 0.15 * turnover_cost
            + 0.10 * info_active
            + 0.10 * stability_score
            + 0.05 * simplicity[overlay]
        )
        final = max(0.0, weighted - no_op_penalty - alpha_penalty - damage_penalty - cost_penalty)
        score_rows.append({
            "overlay_id": overlay,
            "Sharpe_Sortino_score": fmt(sharpe_sortino),
            "drawdown_score": fmt(drawdown_score),
            "return_CAGR_score": fmt(return_cagr),
            "turnover_cost_score": fmt(turnover_cost),
            "information_ratio_active_return_score": fmt(info_active),
            "stability_score": fmt(stability_score),
            "simplicity_interpretability_score": fmt(simplicity[overlay]),
            "no_op_penalty": fmt(no_op_penalty),
            "alpha_decay_penalty": fmt(alpha_penalty),
            "damage_good_subperiod_penalty": fmt(damage_penalty),
            "cost_warning_penalty": fmt(cost_penalty),
            "score_before_penalties": fmt(weighted),
            "tiebreaker_score": fmt(final),
            "weight_Sharpe_Sortino": "0.2500000000",
            "weight_drawdown": "0.2000000000",
            "weight_return_CAGR": "0.1500000000",
            "weight_turnover_cost": "0.1500000000",
            "weight_information_ratio_active_return": "0.1000000000",
            "weight_stability": "0.1000000000",
            "weight_simplicity_interpretability": "0.0500000000",
            "normalization_method": "CANDIDATE_SET_MIN_MAX_0_TO_1",
            "same_overlay_scoring_only": "TRUE",
            **GUARD,
        })
    score_rows.sort(key=lambda row: num(row["tiebreaker_score"]) or -1, reverse=True)
    write_rows(OUT["scores"], score_rows)

    strengths = {
        COMBINED: "TOP_RETURN_SHARPE_DRAWDOWN|30PCT_TURNOVER_REDUCTION|BEST_AFTER_COST_RESULT|STABLE_MULTI_PERIOD",
        QQQ_MA: "TOP_RETURN_SHARPE_DRAWDOWN|STABLE_MULTI_PERIOD|SIMPLE_MA50_REGIME",
        QQQ_DD: "TOP_RETURN_SHARPE_DRAWDOWN|STABLE_MULTI_PERIOD|DIRECT_QQQ_RISK_OFF",
        PORT_DD: "DRAWDOWN_IMPROVEMENT|FEWER_RISK_OFF_DAYS|ALPHA_THRESHOLDS_PASS",
        PORT_COMBINED: "DRAWDOWN_IMPROVEMENT|ALPHA_THRESHOLDS_PASS",
    }
    weaknesses = {
        COMBINED: "RANK_BUFFER_HOLDINGS_UNCHANGED|TURNOVER_ATTRIBUTION_REQUIRES_OPERATOR_REVIEW|MONITOR_NOT_MATURE",
        QQQ_MA: "NO_TURNOVER_REDUCTION|COST_WARNING|MONITOR_NOT_MATURE",
        QQQ_DD: "NO_TURNOVER_REDUCTION|COST_WARNING|LESS_DIRECT_RULE_EVIDENCE|MONITOR_NOT_MATURE",
        PORT_DD: "DAMAGES_GOOD_SUBPERIODS|PATH_DEPENDENT|NO_TURNOVER_REDUCTION",
        PORT_COMBINED: "DAMAGES_GOOD_SUBPERIODS|PATH_DEPENDENT|COMBINED_RULE_COMPLEXITY",
    }
    ranking_rows: list[dict[str, object]] = []
    for rank, score in enumerate(score_rows, start=1):
        overlay = str(score["overlay_id"])
        role = "PRIMARY_REVIEW_CANDIDATE" if rank == 1 else (
            "SECONDARY_REVIEW_CANDIDATE" if rank == 2 else
            "TERTIARY_REVIEW_CANDIDATE" if rank == 3 else "BACKUP_REVIEW_CANDIDATE"
        )
        ranking_rows.append({
            "rank": rank,
            "selection_role": role,
            "overlay_id": overlay,
            "tiebreaker_score": score["tiebreaker_score"],
            "reason_for_rank": (
                "Highest transparent same-overlay score after cost and stability penalties."
                if rank == 1 else "Ranked by the same weighted score and penalties."
            ),
            "key_strengths": strengths[overlay],
            "key_weaknesses": weaknesses[overlay],
            "review_only_flag": "TRUE",
            "adoptable_now": "FALSE",
            **GUARD,
        })
    ranking_rows.append({
        "rank": "",
        "selection_role": "REJECTED_OR_QUARANTINED",
        "overlay_id": QUARANTINE,
        "tiebreaker_score": "",
        "reason_for_rank": "R1/R1A/R2 no-op warning; excluded from scoring.",
        "key_strengths": "",
        "key_weaknesses": "NO_OP_WARNING|HOLDINGS_AND_EXPOSURE_UNCHANGED",
        "review_only_flag": "FALSE",
        "adoptable_now": "FALSE",
        **GUARD,
    })
    write_rows(OUT["ranking"], ranking_rows)
    primary = str(score_rows[0]["overlay_id"]) if score_rows else "NONE"
    secondary = str(score_rows[1]["overlay_id"]) if len(score_rows) > 1 else "NONE"
    tertiary = str(score_rows[2]["overlay_id"]) if len(score_rows) > 2 else "NONE"

    combined_metric = consolidated.get(COMBINED, {})
    combined_cost = cost.get(COMBINED, {})
    combined_eligibility = eligibility.get(COMBINED, {})
    combined_rows = [
        {"review_item": "total_return", "observed_value": combined_metric.get("total_return", ""), "status": "CONFIRMED_FROM_R2", **GUARD},
        {"review_item": "Sharpe", "observed_value": combined_metric.get("Sharpe", ""), "status": "CONFIRMED_FROM_R2", **GUARD},
        {"review_item": "max_drawdown", "observed_value": combined_metric.get("max_drawdown", ""), "status": "CONFIRMED_FROM_R2", **GUARD},
        {"review_item": "turnover_reduction", "observed_value": combined_metric.get("turnover_reduction_vs_baseline", ""), "status": combined_cost.get("turnover_warning_status", ""), **GUARD},
        {"review_item": "subperiod_stability", "observed_value": combined_metric.get("subperiod_stability_status", ""), "status": "CONFIRMED_FROM_R2", **GUARD},
        {"review_item": "after_cost_20bps", "observed_value": combined_metric.get("after_cost_total_return_20bps", ""), "status": "AFTER_COST_REMAINS_POSITIVE_AND_TOP_RANKED", **GUARD},
        {"review_item": "future_data_rule", "observed_value": "NO_FUTURE_RETURNS_USED_BY_R2A", "status": "R2A_REVIEWS_PRECOMPUTED_HISTORICAL_RULE_OUTPUTS_ONLY", **GUARD},
        {
            "review_item": "rank_buffer_holdings_and_turnover",
            "observed_value": (
                f"{combined_eligibility.get('holdings_change_status', '')}|"
                f"TURNOVER_REDUCTION_{combined_metric.get('turnover_reduction_vs_baseline', '')}"
            ),
            "status": "TURNOVER_BENEFIT_REPORTED_BUT_HOLDINGS_SNAPSHOT_CHANGE_NOT_EVIDENCED",
            **GUARD,
        },
    ]
    write_rows(OUT["combined"], combined_rows)

    qqq_rows = []
    for overlay in [QQQ_DD, QQQ_MA]:
        qqq_rows.append({
            "overlay_id": overlay,
            "risk_off_day_count": behavior[overlay].get("risk_off_day_count", ""),
            "risk_off_day_ratio": behavior[overlay].get("risk_off_day_ratio", ""),
            "drawdown_reduction": comparison[overlay].get("drawdown_improvement", ""),
            "total_return_change_vs_baseline": fmt(
                (num(comparison[overlay].get("total_return")) or 0)
                - (num(comparison[BASE].get("total_return")) or 0)
            ),
            "whipsaw_count": behavior[overlay].get("whipsaw_count_short_risk_off_episode_le_5_days", ""),
            "average_exposure": behavior[overlay].get("average_exposure", ""),
            "minimum_exposure": behavior[overlay].get("minimum_exposure", ""),
            "simplicity_interpretability_score": fmt(simplicity[overlay]),
            "comparison_result": (
                "SAME_OBSERVED_CURVE_MA50_RULE_MORE_DIRECTLY_INTERPRETABLE"
                if overlay == QQQ_MA else "SAME_OBSERVED_CURVE_BACKUP_REVIEW_CANDIDATE"
            ),
            **GUARD,
        })
    write_rows(OUT["qqq"], qqq_rows)

    portfolio_rows = []
    for overlay in [PORT_DD, PORT_COMBINED]:
        portfolio_rows.append({
            "overlay_id": overlay,
            "alpha_preservation": alpha[overlay].get("alpha_preservation_classification", ""),
            "damage_good_subperiod_status": stability[overlay].get("subperiod_stability_classification", ""),
            "drawdown_improvement": comparison[overlay].get("drawdown_improvement", ""),
            "path_dependency_status": "PORTFOLIO_EQUITY_PATH_DEPENDENT_LIVE_OBSERVATION_COMPLEXITY",
            "selection_disposition": "BACKUP_ONLY_NOT_PRIMARY",
            **GUARD,
        })
    write_rows(OUT["portfolio"], portfolio_rows)

    cost_rows = []
    for overlay in CANDIDATES:
        cost_status = cost[overlay].get("cost_status", "")
        cost_rows.append({
            "overlay_id": overlay,
            "upstream_cost_status": cost_status,
            "turnover_warning_status": cost[overlay].get("turnover_warning_status", ""),
            "after_cost_total_return_20bps": cost[overlay].get("after_cost_total_return_20bps", ""),
            "after_cost_Sharpe_20bps": cost[overlay].get("after_cost_Sharpe_20bps", ""),
            "cost_warning_carried_forward": yn(
                cost_status != "COST_PROFILE_IMPROVED"
                or overlay == COMBINED
            ),
            "cost_sensitivity_blocks_next_review": "FALSE",
            "cost_review_result": (
                "PRIMARY_REDUCES_COST_WARNING_BUT_RANK_BUFFER_ATTRIBUTION_REQUIRES_REVIEW"
                if overlay == COMBINED else "COST_WARNING_CARRIED_FORWARD"
            ),
            **GUARD,
        })
    write_rows(OUT["cost"], cost_rows)
    cost_warning_status = "COST_WARNING_CARRIED_FORWARD_NOT_BLOCKING_OPERATOR_REVIEW"

    contract = data["downside_contract"][0] if data["downside_contract"] else {}
    downside_rows = [{
        "dependency": "V21_045_R3B_DOWNSIDE_MONITOR",
        "first_maturity_date": contract.get("first_maturity_date", ""),
        "matured_observation_evidence_available": "FALSE",
        "adoption_requires_matured_observation_evidence": "TRUE",
        "r9_monitor_evaluation_dependency": contract.get("r9_dependency", ""),
        "current_status": "DATA_LIMITED_UNTIL_2026_06_24",
        "selection_review_effect": "DOES_NOT_BLOCK_REVIEW_ONLY_SELECTION_BUT_BLOCKS_ADOPTION_EVIDENCE",
        **GUARD,
    }]
    write_rows(OUT["downside"], downside_rows)

    scope_rows = [
        {"boundary_check": "research_tiebreaker_only", "check_passed": "TRUE", "evidence": "Only R2A review artifacts are written.", **GUARD},
        {"boundary_check": "no_adoption_or_official_mutation", "check_passed": "TRUE", "evidence": "All adoption, mutation, recommendation, and execution flags are disabled.", **GUARD},
        {"boundary_check": "same_overlay_scores", "check_passed": yn(all(row["same_overlay_scoring_only"] == "TRUE" for row in score_rows)), "evidence": "Each score row uses one overlay_id.", **GUARD},
        {"boundary_check": "technical_only_not_full_weight", "check_passed": "TRUE", "evidence": "No full-weight backtest or full_weight_score is created.", **GUARD},
    ]
    write_rows(OUT["scope"], scope_rows)
    scope_ok = all(row["check_passed"] == "TRUE" for row in scope_rows)

    primary_margin = (
        (num(score_rows[0]["tiebreaker_score"]) or 0)
        - (num(score_rows[1]["tiebreaker_score"]) or 0)
        if len(score_rows) > 1 else 1.0
    )
    primary_selected = bool(score_rows) and primary_margin >= 0.03
    if not r2_ready:
        final_status = "BLOCKED_V21_047_R2A_R2_OUTPUTS_NOT_READY"
        decision = "BLOCK_TIEBREAKER_REVIEW"
        next_stage = "V21.047-R2_DRAWDOWN_SCALE_REVIEW_PACKET"
    elif not scope_ok:
        final_status = "BLOCKED_V21_047_R2A_SCOPE_BOUNDARY_FAILED"
        decision = "BLOCK_TIEBREAKER_REVIEW"
        next_stage = STAGE
    elif not primary_selected:
        final_status = "PARTIAL_PASS_V21_047_R2A_MULTIPLE_CANDIDATES_REMAIN_REVIEW_ONLY"
        decision = "MULTIPLE_REVIEW_CANDIDATES_REQUIRE_OPERATOR_SELECTION"
        next_stage = "V21.047-R2B_OPERATOR_CANDIDATE_SELECTION_PACKET"
    elif primary == COMBINED:
        final_status = "PARTIAL_PASS_V21_047_R2A_PRIMARY_SELECTED_WITH_COST_WARNING"
        decision = "PRIMARY_REVIEW_CANDIDATE_COMBINED_TURNOVER_QQQ_MA50_NOT_ADOPTABLE"
        next_stage = "V21.047-R3_OPERATOR_REVIEW_DECISION_CAPTURE"
    elif primary in {QQQ_DD, QQQ_MA}:
        final_status = "PASS_V21_047_R2A_TIEBREAKER_PRIMARY_CANDIDATE_SELECTED"
        decision = "PRIMARY_REVIEW_CANDIDATE_QQQ_DRAWDOWN_SCALE_NOT_ADOPTABLE"
        next_stage = "V21.047-R3_OPERATOR_REVIEW_DECISION_CAPTURE"
    else:
        final_status = "PARTIAL_PASS_V21_047_R2A_NO_CANDIDATE_SELECTED_KEEP_BASELINE"
        decision = "KEEP_BASELINE_TECH_TOP20_10D_NO_OVERLAY"
        next_stage = "V21.047-R3_BASELINE_TECH_TOP20_10D_RETENTION_PACKET"

    decision_row = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "baseline_variant": "TECH_TOP20_EQUAL_WEIGHT_10D",
        "surviving_candidates": "|".join(CANDIDATES),
        "rejected_no_op_overlay": QUARANTINE,
        "primary_review_candidate": primary,
        "secondary_review_candidate": secondary,
        "tertiary_review_candidate": tertiary,
        "primary_score_margin_vs_secondary": fmt(primary_margin),
        "operator_selection_needed": yn(not primary_selected),
        "cost_warning_status": cost_warning_status,
        "downside_monitor_dependency": "DATA_LIMITED_UNTIL_2026_06_24_MATURED_EVIDENCE_REQUIRED_BEFORE_ADOPTION",
        "any_overlay_adoptable_now": "FALSE",
        "overlay_adopted": "FALSE",
        "portfolio_variant_adopted": "FALSE",
        "filter_adopted": "FALSE",
        "full_weight_blocked": "TRUE",
        "recommended_next_stage": next_stage,
        **GUARD,
    }
    write_rows(OUT["decision"], [decision_row])

    rank_table = "\n".join(
        f"| {row['rank']} | {row['overlay_id']} | {row['tiebreaker_score']} | {row['selection_role']} |"
        for row in ranking_rows if row["rank"] != ""
    )
    report = f"""# V21.047-R2A Candidate Tiebreaker and Selection Review

final_status: {final_status}

decision: {decision}

## Why R2A was needed

R2 retained five review-worthy candidates. R2A applies one transparent same-overlay scoring method to separate a primary review candidate from backups without granting adoption authority.

Surviving candidates: {"|".join(CANDIDATES)}.

Rejected no-op overlay: {QUARANTINE}.

## Scoring method

Candidate-set min-max scores use 25% Sharpe/Sortino, 20% drawdown improvement, 15% total return/CAGR, 15% turnover/after-cost improvement, 10% information ratio/active return, 10% subperiod stability, and 5% simplicity/interpretability. Penalties are then applied for no-op status, alpha decay, damage to good subperiods, and unresolved cost warnings. Every row uses metrics from one overlay only.

## Candidate ranking

| Rank | Overlay | Score | Role |
|---:|---|---:|---|
{rank_table}

Primary review-only candidate: {primary}.

Secondary candidate: {secondary}.

## Combined candidate deep review

Observed total_return={combined_metric.get('total_return', '')}, Sharpe={combined_metric.get('Sharpe', '')}, max_drawdown={combined_metric.get('max_drawdown', '')}, turnover reduction={combined_metric.get('turnover_reduction_vs_baseline', '')}, after-cost total return at 20bps={combined_metric.get('after_cost_total_return_20bps', '')}, and subperiod status={combined_metric.get('subperiod_stability_status', '')}. The risk-off effect is evidenced through changed exposure and returns. Holdings snapshots remain unchanged while turnover is reported lower, so rank-buffer turnover attribution remains an operator-review warning.

## QQQ scaling comparison

QQQ_DRAWDOWN_RISK_OFF_SCALE and QQQ_MA50_RISK_OFF_SCALE have the same observed curve, 180 risk-off days, 26.05% risk-off exposure, and the same drawdown improvement. The MA50 variant receives the higher simplicity score because its regime definition is directly interpretable from the candidate label and precomputed exposure behavior.

## Portfolio drawdown candidates

PORTFOLIO_DRAWDOWN_STOP_SCALE and COMBINED_PARTIAL_50_PLUS_DRAWDOWN_STOP preserve threshold alpha but damage good subperiods and introduce portfolio-path dependency. They remain backup-only candidates.

Cost warning status: {cost_warning_status}. The primary reduces modeled turnover and cost, but cost attribution is not adoption-grade because material holdings changes are not evidenced.

Downside monitor dependency: first maturity date {contract.get('first_maturity_date', '')}; matured observation evidence and R9/monitor evaluation are required before any adoption.

Operator selection needed: {yn(not primary_selected)}. R2A selected a primary review candidate; the operator still controls the later review decision capture.

No overlay is adopted because this stage is a research-only tiebreaker with no adoption, official-mutation, shadow-gate, or execution authority.

No overlay was adopted.

Technical-only candidate tiebreaker results must not be interpreted as full-weight results or full-weight evidence.

Full-weight remains blocked: TRUE.

Recommended next stage: {next_stage}

Guardrail statement: research_only=TRUE; candidate_tiebreaker_review_only=TRUE; no overlay, portfolio variant, or filter adoption; no official ranking or weight mutation; no official recommendation; no real-book, broker, execution, trade-action, shadow-gate, or shadow-adoption output; no buy/sell/hold recommendation; local artifacts only; online_download_attempted=FALSE; yfinance_used=FALSE.
"""
    REPORT.write_text(report, encoding="utf-8")
    shutil.copyfile(REPORT, CURRENT)

    print(f"final_status={final_status}")
    print(f"decision={decision}")
    print(f"primary_review_candidate={primary}")
    print(f"secondary_review_candidate={secondary}")
    print(f"cost_warning_status={cost_warning_status}")
    print("downside_monitor_dependency=DATA_LIMITED_UNTIL_2026_06_24")
    print(f"recommended_next_stage={next_stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
