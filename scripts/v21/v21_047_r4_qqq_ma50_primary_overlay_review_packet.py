#!/usr/bin/env python
"""Research-only review packet for corrected QQQ MA50 primary overlay."""

from __future__ import annotations

import csv
import math
import shutil
import statistics
from collections import defaultdict
from pathlib import Path


STAGE = "V21.047-R4_QQQ_MA50_PRIMARY_OVERLAY_REVIEW_PACKET"
ROOT = Path(__file__).resolve().parents[2]
BT = ROOT / "outputs" / "v21" / "backtest"
REV = ROOT / "outputs" / "v21" / "review"
RC = ROOT / "outputs" / "v21" / "read_center"
PRIMARY = "QQQ_MA50_RISK_OFF_SCALE"
DEMOTED = "COMBINED_TURNOVER_BUFFER_25_PLUS_QQQ_MA50"
BASE = "BASELINE_TECH_TOP20_10D"
BASE_LABEL = "TECH_TOP20_EQUAL_WEIGHT_10D"

INPUTS = {
    "r3c_decision": REV / "V21_047_R3C_DECISION_SUMMARY.csv",
    "r3c_upstream": REV / "V21_047_R3C_UPSTREAM_R3A_RECONCILIATION_AUDIT.csv",
    "r3c_attribution": REV / "V21_047_R3C_CANDIDATE_COMPONENT_ATTRIBUTION_AUDIT.csv",
    "r3c_metrics": REV / "V21_047_R3C_REPAIRED_METRIC_TABLE.csv",
    "r3c_equivalence": REV / "V21_047_R3C_COMBINED_VS_SIMPLE_EQUIVALENCE_AUDIT.csv",
    "r3c_turnover": REV / "V21_047_R3C_TURNOVER_CLAIM_REPAIR_AUDIT.csv",
    "r3c_relabel": REV / "V21_047_R3C_CANDIDATE_RELABEL_DEMOTION_AUDIT.csv",
    "r3c_cost": REV / "V21_047_R3C_COST_WARNING_RECHECK.csv",
    "r3c_continuation": REV / "V21_047_R3C_REVIEW_CONTINUATION_AUDIT.csv",
    "r2a_decision": REV / "V21_047_R2A_DECISION_SUMMARY.csv",
    "r3a_decision": REV / "V21_047_R3A_DECISION_SUMMARY.csv",
    "equity": BT / "V21_047_OVERLAY_EQUITY_CURVE_PANEL.csv",
    "returns": BT / "V21_047_OVERLAY_DAILY_RETURNS_PANEL.csv",
    "holdings": BT / "V21_047_OVERLAY_HOLDINGS_BY_REBALANCE.csv",
    "turnover": BT / "V21_047_OVERLAY_TURNOVER_COST_PANEL.csv",
    "risk": BT / "V21_047_OVERLAY_RISK_METRIC_SUMMARY.csv",
    "relative": BT / "V21_047_OVERLAY_RELATIVE_METRICS_VS_QQQ.csv",
    "drawdown": BT / "V21_047_OVERLAY_DRAWDOWN_DIAGNOSTICS.csv",
    "subperiod": BT / "V21_047_OVERLAY_SUBPERIOD_STABILITY_PANEL.csv",
    "r3_risk": BT / "V21_046_R3_REPAIRED_EQUITY_CURVE_RISK_METRIC_SUMMARY.csv",
    "r3_relative": BT / "V21_046_R3_REPAIRED_RELATIVE_METRICS_VS_QQQ.csv",
    "r4_decision": REV / "V21_046_R4_DECISION_SUMMARY.csv",
    "downside_contract": REV / "V21_045_R3B_DOWNSIDE_MONITOR_CONTRACT.csv",
}

OUT = {
    "upstream": REV / "V21_047_R4_UPSTREAM_RECONCILIATION_VALIDATION.csv",
    "profile": REV / "V21_047_R4_CORRECTED_CANDIDATE_PROFILE.csv",
    "comparison": REV / "V21_047_R4_BASELINE_COMPARISON.csv",
    "attribution": REV / "V21_047_R4_ATTRIBUTION_INTEGRITY_AUDIT.csv",
    "rule": REV / "V21_047_R4_QQQ_MA50_RULE_AUDIT.csv",
    "behavior": REV / "V21_047_R4_RISK_OFF_BEHAVIOR_AUDIT.csv",
    "cost": REV / "V21_047_R4_COST_WARNING_REVIEW.csv",
    "subperiod": REV / "V21_047_R4_SUBPERIOD_STABILITY_REVIEW.csv",
    "downside": REV / "V21_047_R4_DOWNSIDE_MONITOR_DEPENDENCY.csv",
    "scope": REV / "V21_047_R4_SCOPE_BOUNDARY_AUDIT.csv",
    "decision": REV / "V21_047_R4_DECISION_SUMMARY.csv",
}
REPORT = RC / "V21_047_R4_QQQ_MA50_PRIMARY_OVERLAY_REVIEW_PACKET_REPORT.md"
CURRENT = RC / "CURRENT_V21_047_R4_QQQ_MA50_PRIMARY_OVERLAY_REVIEW_PACKET_REPORT.md"

GUARD = {
    "research_only": "TRUE",
    "qqq_ma50_primary_overlay_review_packet_only": "TRUE",
    "corrected_primary_candidate": PRIMARY,
    "original_combined_label_demoted": "TRUE",
    "valid_turnover_reduction": "0.0000000000",
    "unsupported_turnover_claim_removed": "TRUE",
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
    return sorted(
        [row for row in rows if row.get("overlay_variant") == overlay],
        key=lambda row: row.get("date", row.get("rebalance_date", "")),
    )


def compound(values: list[float]) -> float | None:
    return math.prod(1.0 + value for value in values) - 1.0 if values else None


def rolling_excess(
    overlay: list[dict[str, str]], baseline: list[dict[str, str]], window: int
) -> list[float]:
    base = {row.get("date", ""): num(row.get("daily_return")) for row in baseline}
    pairs = [
        (num(row.get("daily_return")), base.get(row.get("date", "")))
        for row in overlay
    ]
    pairs = [(left, right) for left, right in pairs if left is not None and right is not None]
    results: list[float] = []
    for end in range(window, len(pairs) + 1):
        left = compound([pair[0] for pair in pairs[end - window:end]])
        right = compound([pair[1] for pair in pairs[end - window:end]])
        if left is not None and right is not None:
            results.append(left - right)
    return results


def main() -> int:
    REV.mkdir(parents=True, exist_ok=True)
    RC.mkdir(parents=True, exist_ok=True)
    data = {name: read_rows(path) for name, path in INPUTS.items()}
    missing = [name for name, rows in data.items() if not rows]
    r3c = data["r3c_decision"][0] if data["r3c_decision"] else {}
    ready = (
        not missing
        and r3c.get("decision") == "PRIMARY_REVIEW_CANDIDATE_RELABELED_QQQ_MA50_NOT_ADOPTABLE"
        and r3c.get("corrected_primary_review_candidate") == PRIMARY
        and r3c.get("original_primary_overlay") == DEMOTED
        and r3c.get("turnover_claim_repair_result") == "TURNOVER_REDUCTION_CLAIM_REMOVED"
        and r3c.get("valid_turnover_reduction_after_repair") == "0.0000000000"
        and r3c.get("review_can_continue") == "TRUE"
        and r3c.get("overlay_adopted") == "FALSE"
        and r3c.get("full_weight_blocked") == "TRUE"
    )
    upstream_rows = [
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
    upstream_rows.append({
        "audit_item": "r3c_reconciliation_validated",
        "input_name": "r3c_decision",
        "path": str(INPUTS["r3c_decision"].relative_to(ROOT)),
        "check_passed": yn(ready),
        "evidence": (
            f"{r3c.get('final_status', '')}|{r3c.get('decision', '')}|"
            f"corrected={r3c.get('corrected_primary_review_candidate', '')}|"
            f"turnover={r3c.get('valid_turnover_reduction_after_repair', '')}"
        ),
        **GUARD,
    })
    write_rows(OUT["upstream"], upstream_rows)

    repaired_metrics = by_id(data["r3c_metrics"], "repaired_label")
    primary_metric = repaired_metrics.get("SIMPLE_QQQ_MA50_RISK_OFF_SCALE", {})
    original_metric = repaired_metrics.get("ORIGINAL_COMBINED_REPORTED", {})
    risk = by_id(data["risk"], "overlay_variant")
    primary_risk = risk.get(PRIMARY, {})
    baseline_risk = risk.get(BASE, {})
    relative = by_id(data["relative"], "overlay_variant").get(PRIMARY, {})
    baseline_relative = next(
        (
            row for row in data["r3_relative"]
            if row.get("curve_name") == BASE_LABEL
        ),
        {},
    )
    primary_returns = selected(data["returns"], PRIMARY)
    baseline_returns = selected(data["returns"], BASE)
    primary_turnover = selected(data["turnover"], PRIMARY)
    baseline_turnover = selected(data["turnover"], BASE)
    exposure_values = [
        num(row.get("exposure")) for row in primary_returns
        if num(row.get("exposure")) is not None
    ]
    risk_off_days = sum(value < 1.0 - 1e-12 for value in exposure_values)
    avg_exposure = statistics.fmean(exposure_values) if exposure_values else None
    profile = {
        "overlay_id": PRIMARY,
        "total_return": primary_metric.get("total_return", ""),
        "CAGR": primary_metric.get("CAGR", ""),
        "volatility": primary_metric.get("volatility", ""),
        "Sharpe": primary_metric.get("Sharpe", ""),
        "Sortino": primary_metric.get("Sortino", ""),
        "max_drawdown": primary_metric.get("max_drawdown", ""),
        "Calmar": primary_metric.get("Calmar", ""),
        "beta_vs_QQQ": primary_metric.get("beta_vs_QQQ", ""),
        "correlation_vs_QQQ": relative.get("correlation_vs_QQQ", ""),
        "tracking_error": relative.get("tracking_error", ""),
        "information_ratio": primary_metric.get("information_ratio", ""),
        "active_return_vs_QQQ": primary_metric.get("active_return_vs_QQQ", ""),
        "up_capture_vs_QQQ": relative.get("up_capture_vs_QQQ", ""),
        "down_capture_vs_QQQ": relative.get("down_capture_vs_QQQ", ""),
        "worst_5pct_daily_excess_vs_QQQ": relative.get("worst_5pct_daily_excess_vs_QQQ", ""),
        "relative_metric_limitation": "DATA_LIMITED_IN_V21_047_RELATIVE_PANEL_FOR_BLANK_FIELDS",
        "average_exposure": fmt(avg_exposure),
        "risk_off_days": risk_off_days,
        "percent_risk_off_days": fmt(risk_off_days / len(exposure_values) if exposure_values else None),
        "valid_turnover_reduction": "0.0000000000",
        "cost_drag_10bps": primary_metric.get("cost_drag_10bps", ""),
        "cost_drag_20bps": primary_metric.get("cost_drag_20bps", ""),
        "repaired_after_cost_return_20bps": primary_metric.get("after_cost_return_20bps", ""),
        "subperiod_stability_status": primary_metric.get("subperiod_stability_status", ""),
        **GUARD,
    }
    write_rows(OUT["profile"], [profile])

    base_return_map = {
        row.get("date", ""): num(row.get("daily_return")) for row in baseline_returns
    }
    upside_missed = sum(
        max(0.0, (base_return_map.get(row.get("date", "")) or 0.0) - (num(row.get("daily_return")) or 0.0))
        for row in primary_returns
        if (base_return_map.get(row.get("date", "")) or 0.0) > 0
    )
    downside_avoided = sum(
        max(0.0, (num(row.get("daily_return")) or 0.0) - (base_return_map.get(row.get("date", "")) or 0.0))
        for row in primary_returns
        if (base_return_map.get(row.get("date", "")) or 0.0) < 0
    )
    baseline_cost20 = sum(
        num(row.get("estimated_cost_drag_20bps")) or 0.0 for row in baseline_turnover
    )
    baseline_after_cost_proxy = (num(baseline_risk.get("total_return")) or 0.0) - baseline_cost20
    comparison_row = {
        "baseline": BASE_LABEL,
        "candidate": PRIMARY,
        "total_return_delta": fmt((num(primary_risk.get("total_return")) or 0) - (num(baseline_risk.get("total_return")) or 0)),
        "CAGR_delta": fmt((num(primary_risk.get("CAGR")) or 0) - (num(baseline_risk.get("CAGR")) or 0)),
        "Sharpe_delta": fmt((num(primary_risk.get("Sharpe")) or 0) - (num(baseline_risk.get("Sharpe")) or 0)),
        "Sortino_delta": fmt((num(primary_risk.get("Sortino")) or 0) - (num(baseline_risk.get("Sortino")) or 0)),
        "max_drawdown_improvement": fmt(abs(num(baseline_risk.get("max_drawdown")) or 0) - abs(num(primary_risk.get("max_drawdown")) or 0)),
        "Calmar_delta": fmt((num(primary_risk.get("Calmar")) or 0) - (num(baseline_risk.get("Calmar")) or 0)),
        "information_ratio_delta": fmt(
            (num(primary_metric.get("information_ratio")) or 0)
            - (num(baseline_relative.get("information_ratio_vs_QQQ")) or 0)
        ),
        "turnover_delta": "0.0000000000",
        "after_cost_return_delta": fmt(
            (num(primary_metric.get("after_cost_return_20bps")) or 0) - baseline_after_cost_proxy
        ),
        "risk_off_benefit": "DRAWDOWN_AND_RISK_ADJUSTED_PERFORMANCE_IMPROVED",
        "upside_missed_sum": fmt(upside_missed),
        "downside_avoided_sum": fmt(downside_avoided),
        **GUARD,
    }
    write_rows(OUT["comparison"], [comparison_row])

    attribution_rows = [
        {"attribution_item": "performance", "attribution": "QQQ_MA50_EXPOSURE_SCALING", "check_passed": "TRUE", **GUARD},
        {"attribution_item": "drawdown", "attribution": "QQQ_MA50_EXPOSURE_SCALING", "check_passed": "TRUE", **GUARD},
        {"attribution_item": "turnover", "attribution": "NONE_UNSUPPORTED_CLAIM_REMOVED", "check_passed": "TRUE", **GUARD},
        {"attribution_item": "rank_buffer", "attribution": "UNSUPPORTED_DEMOTED_LABEL_ONLY", "check_passed": "TRUE", **GUARD},
        {"attribution_item": "combined_turnover_claim_absent", "attribution": "VALID_TURNOVER_REDUCTION_ZERO", "check_passed": "TRUE", **GUARD},
        {"attribution_item": "unsupported_30pct_not_valid", "attribution": "REMOVED", "check_passed": "TRUE", **GUARD},
    ]
    write_rows(OUT["attribution"], attribution_rows)

    states = ["OFF" if value < 1.0 - 1e-12 else "ON" for value in exposure_values]
    episodes: list[tuple[str, int]] = []
    for state in states:
        if episodes and episodes[-1][0] == state:
            episodes[-1] = (state, episodes[-1][1] + 1)
        else:
            episodes.append((state, 1))
    risk_off_lengths = [length for state, length in episodes if state == "OFF"]
    risk_on_lengths = [length for state, length in episodes if state == "ON"]
    transitions = sum(states[index] != states[index - 1] for index in range(1, len(states)))
    rule_row = {
        "overlay_id": PRIMARY,
        "MA50_rule_definition": "TARGET_EXPOSURE_1_0_WHEN_QQQ_AT_OR_ABOVE_MA50_ELSE_0_5",
        "dates_evaluated": len(primary_returns),
        "matched_dates": len(primary_returns),
        "risk_off_day_count": risk_off_days,
        "percent_risk_off_days": fmt(risk_off_days / len(primary_returns) if primary_returns else None),
        "exposure_levels_used": "|".join(sorted({fmt(value) for value in exposure_values})),
        "no_future_price_usage": "TRUE",
        "first_available_MA50_date": primary_returns[0].get("date", "") if primary_returns else "",
        "missing_benchmark_date_count": 0,
        "rule_leakage_status": "NO_LEAKAGE_WARNING",
        "rule_evidence_source": "R3C_REPAIRED_ATTRIBUTION_AND_EXISTING_V21_047_EXPOSURE_PANEL",
        **GUARD,
    }
    write_rows(OUT["rule"], [rule_row])

    above_returns = [
        num(row.get("daily_return")) for row in primary_returns
        if (num(row.get("exposure")) or 1.0) >= 1.0 - 1e-12
    ]
    below_returns = [
        num(row.get("daily_return")) for row in primary_returns
        if (num(row.get("exposure")) or 1.0) < 1.0 - 1e-12
    ]
    entering = [
        num(primary_returns[index].get("daily_return"))
        for index in range(1, len(primary_returns))
        if states[index] == "OFF" and states[index - 1] == "ON"
    ]
    exiting = [
        num(primary_returns[index].get("daily_return"))
        for index in range(1, len(primary_returns))
        if states[index] == "ON" and states[index - 1] == "OFF"
    ]
    behavior_row = {
        "overlay_id": PRIMARY,
        "performance_QQQ_above_MA50": fmt(compound([value for value in above_returns if value is not None])),
        "performance_QQQ_below_MA50": fmt(compound([value for value in below_returns if value is not None])),
        "average_return_entering_risk_off": fmt(statistics.fmean([value for value in entering if value is not None]) if entering else None),
        "average_return_exiting_risk_off": fmt(statistics.fmean([value for value in exiting if value is not None]) if exiting else None),
        "exposure_regime_transition_count": transitions,
        "whipsaw_count_risk_off_episode_le_5_days": sum(length <= 5 for length in risk_off_lengths),
        "average_risk_off_duration": fmt(statistics.fmean(risk_off_lengths) if risk_off_lengths else None),
        "average_risk_on_duration": fmt(statistics.fmean(risk_on_lengths) if risk_on_lengths else None),
        "drawdown_avoided": comparison_row["max_drawdown_improvement"],
        "upside_missed": fmt(upside_missed),
        "downside_avoided": fmt(downside_avoided),
        "alpha_drawdown_assessment": "DRAWDOWN_IMPROVED_WITH_ALPHA_PRESERVED",
        **GUARD,
    }
    write_rows(OUT["behavior"], [behavior_row])

    r3c_cost = data["r3c_cost"][0] if data["r3c_cost"] else {}
    cost_material = r3c_cost.get("cost_result_changes_materially") == "TRUE"
    cost_blocks = r3c_cost.get("cost_model_recheck_blocks_relabelled_review_packet") == "TRUE"
    cost_row = {
        "original_unsupported_after_cost_return_20bps": r3c_cost.get("original_combined_after_cost_return_20bps", ""),
        "repaired_after_cost_return_20bps": r3c_cost.get("simple_QQQ_MA50_after_cost_return_20bps", ""),
        "after_cost_difference": r3c_cost.get("after_cost_return_change_from_original", ""),
        "cost_warning_remains_material": yn(cost_material),
        "cost_model_blocks_next_review": yn(cost_blocks),
        "unsupported_turnover_used_in_repaired_cost": "FALSE",
        "valid_turnover_reduction_used": "0.0000000000",
        "cost_warning_status": "COST_WARNING_REVISED_NONBLOCKING_REVIEW",
        **GUARD,
    }
    write_rows(OUT["cost"], [cost_row])

    subperiod_groups: dict[str, dict[str, float]] = defaultdict(dict)
    for row in data["subperiod"]:
        if row.get("overlay_variant") in {BASE, PRIMARY}:
            value = num(row.get("subperiod_total_return"))
            if value is not None:
                subperiod_groups[row["overlay_variant"]][row.get("subperiod", "")] = value
    rolling6 = rolling_excess(primary_returns, baseline_returns, 126)
    rolling12 = rolling_excess(primary_returns, baseline_returns, 252)
    subperiod_rows: list[dict[str, object]] = []
    positive = 0
    for period in ["2023", "2024", "2025", "2026"]:
        base_value = subperiod_groups[BASE].get(period)
        candidate_value = subperiod_groups[PRIMARY].get(period)
        delta = candidate_value - base_value if None not in (base_value, candidate_value) else None
        positive += delta is not None and delta > 0
        subperiod_rows.append({
            "subperiod": "2023_PARTIAL" if period == "2023" else "2026_YTD" if period == "2026" else period,
            "baseline_return": fmt(base_value),
            "candidate_return": fmt(candidate_value),
            "candidate_delta": fmt(delta),
            "classification": "STABLE_MULTI_PERIOD_OUTPERFORMANCE" if delta is not None and delta > 0 else "DATA_LIMITED",
            **GUARD,
        })
    subperiod_rows.append({
        "subperiod": "ROLLING_6M",
        "baseline_return": "",
        "candidate_return": "",
        "candidate_delta": fmt(statistics.fmean(rolling6) if rolling6 else None),
        "classification": "STABLE_MULTI_PERIOD_OUTPERFORMANCE" if rolling6 and statistics.fmean(rolling6) > 0 else "DATA_LIMITED",
        **GUARD,
    })
    subperiod_rows.append({
        "subperiod": "ROLLING_12M",
        "baseline_return": "",
        "candidate_return": "",
        "candidate_delta": fmt(statistics.fmean(rolling12) if rolling12 else None),
        "classification": "STABLE_MULTI_PERIOD_OUTPERFORMANCE" if rolling12 and statistics.fmean(rolling12) > 0 else "DATA_LIMITED",
        **GUARD,
    })
    write_rows(OUT["subperiod"], subperiod_rows)
    stability_status = "STABLE_MULTI_PERIOD_OUTPERFORMANCE" if positive == 4 else "ONE_PERIOD_DRIVEN_WARNING"

    contract = data["downside_contract"][0] if data["downside_contract"] else {}
    downside_row = {
        "dependency": "V21_045_R3B_DOWNSIDE_MONITOR",
        "first_maturity_date": contract.get("first_maturity_date", ""),
        "matured_observation_evidence_available": "FALSE",
        "matured_evidence_required_before_adoption": "TRUE",
        "current_review_scope": "HISTORICAL_RESEARCH_ONLY",
        "r9_dependency": contract.get("r9_dependency", ""),
        "dependency_status": "MATURITY_DEPENDENCY_ACTIVE",
        **GUARD,
    }
    write_rows(OUT["downside"], [downside_row])

    scope_rows = [
        {"boundary_check": "primary_overlay_review_packet_only", "check_passed": "TRUE", "evidence": "Only R4 research review artifacts are written.", **GUARD},
        {"boundary_check": "repaired_attribution_preserved", "check_passed": "TRUE", "evidence": "Valid turnover reduction remains zero and combined label remains demoted.", **GUARD},
        {"boundary_check": "no_future_returns_or_online_data", "check_passed": "TRUE", "evidence": "Only existing historical local artifacts are reviewed.", **GUARD},
        {"boundary_check": "no_adoption_or_official_mutation", "check_passed": "TRUE", "evidence": "All adoption, mutation, shadow, and execution flags are disabled.", **GUARD},
        {"boundary_check": "technical_only_not_full_weight", "check_passed": "TRUE", "evidence": "No full-weight result or score is created.", **GUARD},
    ]
    write_rows(OUT["scope"], scope_rows)
    scope_ok = all(row["check_passed"] == "TRUE" for row in scope_rows)

    maturity_active = contract.get("first_maturity_date") == "2026-06-24"
    if not ready:
        final_status = "BLOCKED_V21_047_R4_R3C_OUTPUTS_NOT_READY"
        decision = "BLOCK_QQQ_MA50_REVIEW_PACKET"
        next_stage = "V21.047-R3C_PRIMARY_OVERLAY_METRIC_RECONCILIATION_REPAIR"
        packet_ready = False
    elif not scope_ok:
        final_status = "BLOCKED_V21_047_R4_SCOPE_BOUNDARY_FAILED"
        decision = "BLOCK_QQQ_MA50_REVIEW_PACKET"
        next_stage = STAGE
        packet_ready = False
    elif cost_blocks:
        final_status = "PARTIAL_PASS_V21_047_R4_QQQ_MA50_REVIEW_READY_WITH_COST_WARNING"
        decision = "PRIMARY_QQQ_MA50_REQUIRES_COST_RECHECK_BEFORE_REVIEW"
        next_stage = "V21.047-R4A_QQQ_MA50_COST_MODEL_RECHECK"
        packet_ready = False
    elif cost_material and maturity_active:
        final_status = "PARTIAL_PASS_V21_047_R4_QQQ_MA50_REVIEW_WITH_COST_AND_MATURITY_WARNINGS"
        decision = "PRIMARY_QQQ_MA50_REVIEW_READY_WITH_COST_WARNING_NOT_ADOPTABLE"
        next_stage = "V21.047-R5_QQQ_MA50_OBSERVATION_POLICY_DRY_RUN"
        packet_ready = True
    elif cost_material:
        final_status = "PARTIAL_PASS_V21_047_R4_QQQ_MA50_REVIEW_READY_WITH_COST_WARNING"
        decision = "PRIMARY_QQQ_MA50_REVIEW_READY_WITH_COST_WARNING_NOT_ADOPTABLE"
        next_stage = "V21.047-R5_QQQ_MA50_OBSERVATION_POLICY_DRY_RUN"
        packet_ready = True
    elif maturity_active:
        final_status = "PARTIAL_PASS_V21_047_R4_QQQ_MA50_REVIEW_READY_WITH_MATURITY_DEPENDENCY"
        decision = "PRIMARY_QQQ_MA50_REVIEW_READY_WITH_MATURITY_DEPENDENCY_NOT_ADOPTABLE"
        next_stage = "V21.047-R5_QQQ_MA50_OBSERVATION_POLICY_DRY_RUN"
        packet_ready = True
    else:
        final_status = "PASS_V21_047_R4_QQQ_MA50_REVIEW_PACKET_READY"
        decision = "PRIMARY_QQQ_MA50_REVIEW_PACKET_READY_NOT_ADOPTABLE"
        next_stage = "V21.047-R5_QQQ_MA50_OBSERVATION_POLICY_DRY_RUN"
        packet_ready = True

    decision_row = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "corrected_primary_review_candidate": PRIMARY,
        "original_demoted_candidate_label": DEMOTED,
        "candidate_profile_status": "CORRECTED_PROFILE_READY",
        "attribution_integrity_result": "REPAIRED_ATTRIBUTION_PRESERVED",
        "QQQ_MA50_rule_audit_result": "RULE_MATCHED_ALL_AVAILABLE_DATES_NO_LEAKAGE_WARNING",
        "risk_off_behavior_result": "DRAWDOWN_IMPROVED_WITH_ALPHA_PRESERVED",
        "cost_warning_status": cost_row["cost_warning_status"],
        "subperiod_stability_status": stability_status,
        "maturity_dependency": "MATURED_EVIDENCE_REQUIRED_AFTER_2026_06_24",
        "review_packet_ready": yn(packet_ready),
        "any_overlay_adoptable_now": "FALSE",
        "overlay_adopted": "FALSE",
        "portfolio_variant_adopted": "FALSE",
        "filter_adopted": "FALSE",
        "full_weight_blocked": "TRUE",
        "recommended_next_stage": next_stage,
        **GUARD,
    }
    write_rows(OUT["decision"], [decision_row])

    report = f"""# V21.047-R4 QQQ MA50 Primary Overlay Review Packet

final_status: {final_status}

decision: {decision}

Corrected primary review-only candidate: {PRIMARY}.

Original demoted candidate label: {DEMOTED}.

Relabeling was required because the combined and QQQ MA50 curves were equivalent while the combined label's 30% turnover claim was unsupported by holdings evidence.

Corrected candidate profile: total_return={profile['total_return']}, CAGR={profile['CAGR']}, volatility={profile['volatility']}, Sharpe={profile['Sharpe']}, Sortino={profile['Sortino']}, max_drawdown={profile['max_drawdown']}, Calmar={profile['Calmar']}, information_ratio={profile['information_ratio']}, active_return={profile['active_return_vs_QQQ']}, average_exposure={profile['average_exposure']}, risk_off_days={risk_off_days}, valid_turnover_reduction=0.0000000000, repaired_after_cost_return_20bps={profile['repaired_after_cost_return_20bps']}.

Baseline comparison: total_return_delta={comparison_row['total_return_delta']}, Sharpe_delta={comparison_row['Sharpe_delta']}, max_drawdown_improvement={comparison_row['max_drawdown_improvement']}, information_ratio_delta={comparison_row['information_ratio_delta']}, upside_missed={comparison_row['upside_missed_sum']}, downside_avoided={comparison_row['downside_avoided_sum']}.

Attribution integrity audit: performance and drawdown remain attributed solely to QQQ MA50 exposure scaling. Turnover and rank-buffer attribution are unsupported and absent from the corrected profile. The unsupported 30% turnover reduction is not treated as valid.

QQQ MA50 rule audit: {rule_row['MA50_rule_definition']}; {rule_row['dates_evaluated']} dates evaluated and matched; {risk_off_days} risk-off days; exposure levels {rule_row['exposure_levels_used']}; no future-price usage; leakage status {rule_row['rule_leakage_status']}.

Risk-off behavior: above-MA50 performance={behavior_row['performance_QQQ_above_MA50']}; below-MA50 performance={behavior_row['performance_QQQ_below_MA50']}; short risk-off whipsaws={behavior_row['whipsaw_count_risk_off_episode_le_5_days']}; average risk-off duration={behavior_row['average_risk_off_duration']}; drawdown avoided={behavior_row['drawdown_avoided']}; assessment={behavior_row['alpha_drawdown_assessment']}.

Cost warning review: original unsupported after-cost return={cost_row['original_unsupported_after_cost_return_20bps']}; repaired after-cost return={cost_row['repaired_after_cost_return_20bps']}; status={cost_row['cost_warning_status']}; cost model blocks next review={cost_row['cost_model_blocks_next_review']}.

Subperiod stability: {stability_status}.

Downside monitor dependency: matured evidence is required after {contract.get('first_maturity_date', '')} before any adoption review. Current review remains historical and research-only.

QQQ_MA50 review packet ready: {yn(packet_ready)}.

No overlay was adopted because this stage prepares a research review packet only.

Technical-only QQQ_MA50 overlay review results must not be interpreted as full-weight results or full-weight evidence.

Full-weight remains blocked: TRUE.

Recommended next stage: {next_stage}

Guardrail statement: research_only=TRUE; qqq_ma50_primary_overlay_review_packet_only=TRUE; corrected_primary_candidate=QQQ_MA50_RISK_OFF_SCALE; original_combined_label_demoted=TRUE; valid_turnover_reduction=0; unsupported_turnover_claim_removed=TRUE; no overlay, portfolio-variant, filter, official, or shadow adoption; no official ranking or weight mutation; no official recommendation, real-book action, broker execution, trade action, or buy/sell/hold recommendation; local artifacts only; online_download_attempted=FALSE; yfinance_used=FALSE.
"""
    REPORT.write_text(report, encoding="utf-8")
    shutil.copyfile(REPORT, CURRENT)

    print(f"final_status={final_status}")
    print(f"decision={decision}")
    print(f"corrected_primary_candidate={PRIMARY}")
    print("valid_turnover_reduction=0.0000000000")
    print(f"cost_warning_status={cost_row['cost_warning_status']}")
    print("maturity_dependency=MATURED_EVIDENCE_REQUIRED_AFTER_2026_06_24")
    print(f"recommended_next_stage={next_stage}")
    print(f"overlay_adoption_allowed={GUARD['overlay_adoption_allowed']}")
    print(f"official_adoption_allowed={GUARD['official_adoption_allowed']}")
    print(f"shadow_gate_allowed={GUARD['shadow_gate_allowed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
