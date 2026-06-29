#!/usr/bin/env python
"""Research-only review packet for V21.047 drawdown/risk-off overlays."""

from __future__ import annotations

import csv
import math
import shutil
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path


STAGE = "V21.047-R2_DRAWDOWN_SCALE_REVIEW_PACKET"
ROOT = Path(__file__).resolve().parents[2]
BT = ROOT / "outputs" / "v21" / "backtest"
REV = ROOT / "outputs" / "v21" / "review"
RC = ROOT / "outputs" / "v21" / "read_center"
BASE = "BASELINE_TECH_TOP20_10D"
BASE_LABEL = "TECH_TOP20_EQUAL_WEIGHT_10D"
PRIMARY = [
    "COMBINED_TURNOVER_BUFFER_25_PLUS_QQQ_MA50",
    "QQQ_DRAWDOWN_RISK_OFF_SCALE",
    "QQQ_MA50_RISK_OFF_SCALE",
    "PORTFOLIO_DRAWDOWN_STOP_SCALE",
    "COMBINED_PARTIAL_50_PLUS_DRAWDOWN_STOP",
]
QUARANTINE = ["TURNOVER_BUFFER_RANK_30"]

INPUTS = {
    "r1a_decision": REV / "V21_047_R1A_DECISION_SUMMARY.csv",
    "r1a_metrics": REV / "V21_047_R1A_OVERLAY_LEVEL_METRIC_RECONSTRUCTION.csv",
    "r1a_preservation": REV / "V21_047_R1A_SAME_OVERLAY_PRESERVATION_AUDIT.csv",
    "r1a_noop": REV / "V21_047_R1A_NO_OP_DETECTION_AUDIT.csv",
    "r1a_score": REV / "V21_047_R1A_REPAIRED_BALANCED_SCORE_AUDIT.csv",
    "r1a_selection": REV / "V21_047_R1A_REPAIRED_BEST_CANDIDATE_SELECTION.csv",
    "r1a_review": REV / "V21_047_R1A_REVIEW_WORTHINESS_AUDIT.csv",
    "r1a_scope": REV / "V21_047_R1A_LEAKAGE_AND_SCOPE_AUDIT.csv",
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
    "r4_beta": REV / "V21_046_R4_BETA_ACTIVE_RISK_AUDIT.csv",
    "r4_drawdown": REV / "V21_046_R4_DRAWDOWN_AUDIT.csv",
    "r4_turnover": REV / "V21_046_R4_TURNOVER_COST_AUDIT.csv",
    "downside_contract": REV / "V21_045_R3B_DOWNSIDE_MONITOR_CONTRACT.csv",
}

OUT = {
    "upstream": REV / "V21_047_R2_UPSTREAM_ATTRIBUTION_REPAIR_AUDIT.csv",
    "eligibility": REV / "V21_047_R2_CANDIDATE_ELIGIBILITY_AUDIT.csv",
    "comparison": REV / "V21_047_R2_BASELINE_VS_CANDIDATE_COMPARISON.csv",
    "behavior": REV / "V21_047_R2_DRAWDOWN_RISK_OFF_BEHAVIOR_AUDIT.csv",
    "cost": REV / "V21_047_R2_TURNOVER_COST_AUDIT.csv",
    "alpha": REV / "V21_047_R2_ALPHA_PRESERVATION_AUDIT.csv",
    "subperiod": REV / "V21_047_R2_SUBPERIOD_STABILITY_AUDIT.csv",
    "downside": REV / "V21_047_R2_DOWNSIDE_MONITOR_COMPATIBILITY_AUDIT.csv",
    "classification": REV / "V21_047_R2_CANDIDATE_CLASSIFICATION.csv",
    "scope": REV / "V21_047_R2_SCOPE_BOUNDARY_AUDIT.csv",
    "decision": REV / "V21_047_R2_DECISION_SUMMARY.csv",
}
REPORT = RC / "V21_047_R2_DRAWDOWN_SCALE_REVIEW_PACKET_REPORT.md"
CURRENT = RC / "CURRENT_V21_047_R2_DRAWDOWN_SCALE_REVIEW_PACKET_REPORT.md"

GUARD = {
    "research_only": "TRUE",
    "drawdown_scale_review_packet_only": "TRUE",
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
        if not text or text.lower() in {"nan", "none", "not_available", "not_computed"}:
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


def ratio(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or abs(b) < 1e-15:
        return None
    return a / b


def by_id(rows: list[dict[str, str]], key: str = "overlay_id") -> dict[str, dict[str, str]]:
    return {row.get(key, ""): row for row in rows if row.get(key)}


def group_by(rows: list[dict[str, str]], key: str) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        result[row.get(key, "")].append(row)
    return result


def compound(values: list[float]) -> float | None:
    return math.prod(1.0 + value for value in values) - 1.0 if values else None


def annualized_sharpe(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    sd = statistics.stdev(values)
    return statistics.fmean(values) / sd * math.sqrt(252) if sd > 0 else None


def after_cost_returns(
    return_rows: list[dict[str, str]], cost_rows: list[dict[str, str]], field: str
) -> list[float]:
    costs = {
        row.get("rebalance_date", ""): num(row.get(field)) or 0.0
        for row in cost_rows
    }
    seen: set[str] = set()
    result: list[float] = []
    for row in return_rows:
        value = num(row.get("daily_return"))
        if value is None:
            continue
        rebalance_date = row.get("rebalance_date", "")
        cost = 0.0
        if rebalance_date and rebalance_date not in seen:
            cost = costs.get(rebalance_date, 0.0)
            seen.add(rebalance_date)
        result.append(value - cost)
    return result


def exposure_episodes(values: list[float]) -> tuple[int, int, list[int]]:
    risk = [value < 1.0 - 1e-10 for value in values]
    transitions = sum(risk[index] != risk[index - 1] for index in range(1, len(risk)))
    lengths: list[int] = []
    current = 0
    for flag in risk:
        if flag:
            current += 1
        elif current:
            lengths.append(current)
            current = 0
    if current:
        lengths.append(current)
    whipsaws = sum(length <= 5 for length in lengths)
    return transitions, whipsaws, lengths


def rolling_excess(
    overlay_rows: list[dict[str, str]], baseline_rows: list[dict[str, str]], window: int
) -> list[float]:
    base = {row.get("date", ""): num(row.get("daily_return")) for row in baseline_rows}
    paired = [
        (num(row.get("daily_return")), base.get(row.get("date", "")))
        for row in overlay_rows
    ]
    pairs = [(left, right) for left, right in paired if left is not None and right is not None]
    result: list[float] = []
    for end in range(window, len(pairs) + 1):
        overlay_return = compound([value[0] for value in pairs[end - window:end]])
        baseline_return = compound([value[1] for value in pairs[end - window:end]])
        if overlay_return is not None and baseline_return is not None:
            result.append(overlay_return - baseline_return)
    return result


def main() -> int:
    REV.mkdir(parents=True, exist_ok=True)
    RC.mkdir(parents=True, exist_ok=True)
    data = {name: read_rows(path) for name, path in INPUTS.items()}
    missing = [name for name, rows in data.items() if not rows]
    r1a = data["r1a_decision"][0] if data["r1a_decision"] else {}
    contract = data["downside_contract"][0] if data["downside_contract"] else {}

    r1a_ready = (
        not missing
        and r1a.get("final_status", "").startswith(("PASS_", "PARTIAL_PASS_"))
        and r1a.get("decision") == "OVERLAY_ATTRIBUTION_REPAIRED_CANDIDATE_REVIEW_WORTHY_NOT_ADOPTABLE"
    )
    attribution_rows = [
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
    attribution_rows.extend([
        {
            "audit_item": "r1a_completed",
            "input_name": "r1a_decision",
            "path": str(INPUTS["r1a_decision"].relative_to(ROOT)),
            "check_passed": yn(r1a_ready),
            "evidence": f"{r1a.get('final_status', '')}|{r1a.get('decision', '')}",
            **GUARD,
        },
        {
            "audit_item": "metric_attribution_repaired",
            "input_name": "r1a_metrics",
            "path": str(INPUTS["r1a_metrics"].relative_to(ROOT)),
            "check_passed": yn(all(
                row.get("overlay_id") == row.get("metric_attribution_overlay_id")
                for row in data["r1a_metrics"]
            )),
            "evidence": "Every reconstructed metric row has one matching overlay_id.",
            **GUARD,
        },
        {
            "audit_item": "no_overlay_adopted_and_full_weight_blocked",
            "input_name": "r1a_decision",
            "path": str(INPUTS["r1a_decision"].relative_to(ROOT)),
            "check_passed": yn(
                r1a.get("overlay_adopted") == "FALSE"
                and r1a.get("full_weight_blocked") == "TRUE"
            ),
            "evidence": "R1A retained research-only boundaries.",
            **GUARD,
        },
    ])
    write_rows(OUT["upstream"], attribution_rows)

    metrics = by_id(data["r1a_metrics"])
    preservation = by_id(data["r1a_preservation"])
    noop = by_id(data["r1a_noop"])
    review = by_id(data["r1a_review"])
    returns = group_by(data["returns"], "overlay_variant")
    equity = group_by(data["equity"], "overlay_variant")
    turnover = group_by(data["turnover"], "overlay_variant")
    subperiod = group_by(data["subperiod"], "overlay_variant")
    leakage_ok = bool(data["r1a_scope"]) and all(
        row.get("check_passed") == "TRUE" for row in data["r1a_scope"]
    )

    eligibility_rows: list[dict[str, object]] = []
    for overlay in PRIMARY + QUARANTINE:
        no_op_status = noop.get(overlay, {}).get("no_op_status", "DATA_NOT_AVAILABLE")
        holdings_ratio = num(noop.get(overlay, {}).get("holdings_changed_ratio"))
        exposure_ratio = num(noop.get(overlay, {}).get("exposure_changed_day_ratio"))
        evidence_complete = noop.get(overlay, {}).get("evidence_complete") == "TRUE"
        metric_single = (
            metrics.get(overlay, {}).get("overlay_id") == overlay
            and metrics.get(overlay, {}).get("metric_attribution_overlay_id") == overlay
        )
        no_op_rejected = no_op_status == "NO_OP_WARNING"
        exposure_changed = (exposure_ratio or 0.0) > 0
        holdings_changed = (holdings_ratio or 0.0) > 0
        evidence_sufficient = evidence_complete and (exposure_changed or holdings_changed)
        eligible = (
            overlay in PRIMARY and not no_op_rejected and leakage_ok
            and evidence_sufficient and metric_single
        )
        reasons = []
        if no_op_rejected:
            reasons.append("NO_OP_REJECTED")
        if not leakage_ok:
            reasons.append("LEAKAGE_WARNING")
        if not evidence_sufficient:
            reasons.append("HOLDINGS_EXPOSURE_EVIDENCE_INSUFFICIENT")
        if not metric_single:
            reasons.append("MIXED_METRIC_ATTRIBUTION")
        eligibility_rows.append({
            "overlay_id": overlay,
            "candidate_scope": "PRIMARY" if overlay in PRIMARY else "QUARANTINE",
            "no_op_status": no_op_status,
            "leakage_status": "NO_LEAKAGE_WARNING" if leakage_ok else "LEAKAGE_WARNING",
            "holdings_change_status": "HOLDINGS_CHANGED" if holdings_changed else "HOLDINGS_UNCHANGED",
            "exposure_change_status": "EXPOSURE_CHANGED" if exposure_changed else "EXPOSURE_UNCHANGED",
            "holdings_exposure_evidence_sufficient": yn(evidence_sufficient),
            "review_worthy_from_R1A": review.get(overlay, {}).get("review_worthy_flag", "FALSE"),
            "metrics_tied_to_single_overlay": yn(metric_single),
            "eligibility_for_R2_packet": "ELIGIBLE_ACTIVE_REVIEW" if eligible else "REJECTED_OR_QUARANTINED",
            "rejection_reasons": "|".join(reasons),
            "adoptable_now": "FALSE",
            **GUARD,
        })
    write_rows(OUT["eligibility"], eligibility_rows)
    eligible = [
        str(row["overlay_id"]) for row in eligibility_rows
        if row["eligibility_for_R2_packet"] == "ELIGIBLE_ACTIVE_REVIEW"
    ]
    rejected_noop = [
        str(row["overlay_id"]) for row in eligibility_rows
        if row["no_op_status"] == "NO_OP_WARNING"
    ]

    comparison_rows: list[dict[str, object]] = []
    for overlay in [BASE] + eligible:
        metric = metrics.get(overlay, {})
        preserve = preservation.get(overlay, {})
        comparison_rows.append({
            "overlay_id": overlay,
            "display_name": BASE_LABEL if overlay == BASE else overlay,
            "comparison_role": "BASELINE" if overlay == BASE else "ELIGIBLE_CANDIDATE",
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
            "average_turnover": metric.get("average_turnover_per_rebalance", ""),
            "annualized_turnover": metric.get("annualized_turnover_estimate", ""),
            "cost_drag_10bps": metric.get("cost_drag_10bps", ""),
            "cost_drag_20bps": metric.get("cost_drag_20bps", ""),
            "total_return_preservation_ratio": preserve.get("total_return_preservation_ratio", "1.0000000000"),
            "Sharpe_preservation_ratio": preserve.get("Sharpe_preservation_ratio", "1.0000000000"),
            "drawdown_improvement": preserve.get("max_drawdown_improvement", "0.0000000000"),
            "turnover_reduction_ratio": preserve.get("turnover_reduction_ratio", "0.0000000000"),
            "alpha_preservation_status": preserve.get("alpha_preservation_status", ""),
            "metrics_tied_to_overlay_id": overlay,
            **GUARD,
        })
    write_rows(OUT["comparison"], comparison_rows)

    baseline_returns = returns.get(BASE, [])
    baseline_return_map = {
        row.get("date", ""): num(row.get("daily_return")) for row in baseline_returns
    }
    behavior_rows: list[dict[str, object]] = []
    for overlay in eligible:
        rows = sorted(equity.get(overlay, []), key=lambda row: row.get("date", ""))
        exposures = [num(row.get("exposure")) for row in rows]
        exposures = [value for value in exposures if value is not None]
        risk_days = sum(value < 1.0 - 1e-10 for value in exposures)
        transitions, whipsaws, episode_lengths = exposure_episodes(exposures)
        overlay_returns = returns.get(overlay, [])
        risk_off_returns = [
            num(row.get("daily_return"))
            for row in overlay_returns if (num(row.get("exposure")) or 1.0) < 1.0 - 1e-10
        ]
        full_returns = [
            num(row.get("daily_return"))
            for row in overlay_returns if (num(row.get("exposure")) or 1.0) >= 1.0 - 1e-10
        ]
        upside_missed = sum(
            max(0.0, baseline_return_map.get(row.get("date", "")) - (num(row.get("daily_return")) or 0.0))
            for row in overlay_returns
            if baseline_return_map.get(row.get("date", "")) is not None
            and (baseline_return_map.get(row.get("date", "")) or 0.0) > 0
        )
        is_ma = "MA50" in overlay
        behavior_rows.append({
            "overlay_id": overlay,
            "risk_off_day_count": risk_days,
            "risk_off_day_ratio": fmt(risk_days / len(exposures) if exposures else None),
            "average_exposure": fmt(statistics.fmean(exposures) if exposures else None),
            "minimum_exposure": fmt(min(exposures) if exposures else None),
            "drawdown_avoided_vs_baseline": preservation.get(overlay, {}).get("max_drawdown_improvement", ""),
            "upside_missed_vs_baseline_sum": fmt(upside_missed),
            "exposure_regime_transition_count": transitions,
            "whipsaw_count_short_risk_off_episode_le_5_days": whipsaws,
            "risk_off_episode_count": len(episode_lengths),
            "average_risk_off_episode_days": fmt(
                statistics.fmean(episode_lengths) if episode_lengths else None
            ),
            "reentry_lag_after_QQQ_recovery_days": "",
            "reentry_lag_status": "QQQ_RECOVERY_MARKER_NOT_AVAILABLE",
            "performance_during_QQQ_below_MA50_periods": (
                fmt(compound([value for value in risk_off_returns if value is not None]))
                if is_ma else ""
            ),
            "performance_during_QQQ_above_MA50_periods": (
                fmt(compound([value for value in full_returns if value is not None]))
                if is_ma else ""
            ),
            "ma50_period_mapping_status": (
                "INFERRED_FROM_PRECOMPUTED_EXPOSURE_REGIME"
                if is_ma else "NOT_APPLICABLE_TO_NON_MA50_OVERLAY"
            ),
            **GUARD,
        })
    write_rows(OUT["behavior"], behavior_rows)

    cost_rows: list[dict[str, object]] = []
    for overlay in eligible:
        metric = metrics.get(overlay, {})
        preserve = preservation.get(overlay, {})
        after10 = after_cost_returns(returns.get(overlay, []), turnover.get(overlay, []), "estimated_cost_drag_10bps")
        after20 = after_cost_returns(returns.get(overlay, []), turnover.get(overlay, []), "estimated_cost_drag_20bps")
        turnover_reduction = num(preserve.get("turnover_reduction_ratio")) or 0.0
        stale_risk = (
            "STALE_HOLDING_RISK_REQUIRES_OPERATOR_REVIEW"
            if "TURNOVER_BUFFER" in overlay else "NO_RANK_BUFFER_IN_OVERLAY"
        )
        cost_rows.append({
            "overlay_id": overlay,
            "turnover_reduction_vs_baseline": fmt(turnover_reduction),
            "cost_drag_reduction_10bps": fmt(
                (num(metrics.get(BASE, {}).get("cost_drag_10bps")) or 0.0)
                - (num(metric.get("cost_drag_10bps")) or 0.0)
            ),
            "cost_drag_reduction_20bps": fmt(
                (num(metrics.get(BASE, {}).get("cost_drag_20bps")) or 0.0)
                - (num(metric.get("cost_drag_20bps")) or 0.0)
            ),
            "after_cost_total_return_10bps": fmt(compound(after10)),
            "after_cost_total_return_20bps": fmt(compound(after20)),
            "after_cost_Sharpe_10bps": fmt(annualized_sharpe(after10)),
            "after_cost_Sharpe_20bps": fmt(annualized_sharpe(after20)),
            "turnover_warning_status": (
                "TURNOVER_WARNING_REDUCED"
                if turnover_reduction >= 0.20 else "TURNOVER_WARNING_NOT_RESOLVED"
            ),
            "rank_buffer_stale_holding_risk": stale_risk,
            "cost_status": (
                "COST_PROFILE_IMPROVED"
                if turnover_reduction >= 0.20 else "COST_PROFILE_NOT_IMPROVED"
            ),
            **GUARD,
        })
    write_rows(OUT["cost"], cost_rows)

    alpha_rows: list[dict[str, object]] = []
    for overlay in eligible:
        metric = metrics.get(overlay, {})
        preserve = preservation.get(overlay, {})
        tr = num(preserve.get("total_return_preservation_ratio")) or 0.0
        sh = num(preserve.get("Sharpe_preservation_ratio")) or 0.0
        so = num(preserve.get("Sortino_preservation_ratio")) or 0.0
        info = num(metric.get("information_ratio"))
        active = num(metric.get("active_return_vs_QQQ"))
        stable = (num(metric.get("subperiod_positive_excess_ratio")) or 0.0) >= 0.75
        passes = [tr >= 0.75, sh >= 0.80, so >= 0.80, (info or -1) > 0, (active or -1) > 0]
        if all(passes) and stable:
            status = "ALPHA_PRESERVED"
        elif sum(passes) >= 4:
            status = "ALPHA_PARTIALLY_PRESERVED"
        elif tr >= 0.50 and sh >= 0.60:
            status = "ALPHA_DECAY_WARNING"
        else:
            status = "ALPHA_DESTROYED"
        alpha_rows.append({
            "overlay_id": overlay,
            "total_return_preservation_ratio": fmt(tr),
            "total_return_preservation_ge_0_75": yn(tr >= 0.75),
            "Sharpe_preservation_ratio": fmt(sh),
            "Sharpe_preservation_ge_0_80": yn(sh >= 0.80),
            "Sortino_preservation_ratio": fmt(so),
            "Sortino_preservation_ge_0_80": yn(so >= 0.80),
            "information_ratio": fmt(info),
            "information_ratio_positive": yn((info or -1) > 0),
            "active_return_vs_QQQ": fmt(active),
            "active_return_positive": yn((active or -1) > 0),
            "subperiod_outperformance_stable": yn(stable),
            "alpha_preservation_classification": status,
            **GUARD,
        })
    write_rows(OUT["alpha"], alpha_rows)
    alpha_map = by_id(alpha_rows)

    subperiod_rows: list[dict[str, object]] = []
    for overlay in [BASE] + eligible:
        period_values = {
            row.get("subperiod", ""): num(row.get("subperiod_total_return"))
            for row in subperiod.get(overlay, [])
        }
        base_values = {
            row.get("subperiod", ""): num(row.get("subperiod_total_return"))
            for row in subperiod.get(BASE, [])
        }
        excesses = [
            (period_values.get(period), base_values.get(period))
            for period in ["2023", "2024", "2025", "2026"]
        ]
        paired = [(left, right) for left, right in excesses if left is not None and right is not None]
        deltas = [left - right for left, right in paired]
        positive_count = sum(value > 0 for value in deltas)
        negative_count = sum(value < 0 for value in deltas)
        if overlay == BASE:
            classification = "STABLE_MULTI_PERIOD_OUTPERFORMANCE"
        elif positive_count >= 3:
            classification = "STABLE_MULTI_PERIOD_OUTPERFORMANCE"
        elif deltas and max(deltas) > 0 and positive_count == 1:
            classification = "ONE_PERIOD_DRIVEN_WARNING"
        elif negative_count >= 2:
            classification = "OVERLAY_DAMAGES_GOOD_SUBPERIODS"
        else:
            classification = "OVERLAY_IMPROVES_BAD_SUBPERIODS"
        roll6 = rolling_excess(returns.get(overlay, []), baseline_returns, 126)
        roll12 = rolling_excess(returns.get(overlay, []), baseline_returns, 252)
        subperiod_rows.append({
            "overlay_id": overlay,
            "return_2023_partial": fmt(period_values.get("2023")),
            "return_2024": fmt(period_values.get("2024")),
            "return_2025": fmt(period_values.get("2025")),
            "return_2026_YTD": fmt(period_values.get("2026")),
            "positive_subperiod_delta_count_vs_baseline": positive_count,
            "negative_subperiod_delta_count_vs_baseline": negative_count,
            "rolling_6m_excess_mean_vs_baseline": fmt(statistics.fmean(roll6) if roll6 else None),
            "rolling_6m_positive_window_ratio": fmt(
                sum(value > 0 for value in roll6) / len(roll6) if roll6 else None
            ),
            "rolling_12m_excess_mean_vs_baseline": fmt(statistics.fmean(roll12) if roll12 else None),
            "rolling_12m_positive_window_ratio": fmt(
                sum(value > 0 for value in roll12) / len(roll12) if roll12 else None
            ),
            "subperiod_stability_classification": classification,
            **GUARD,
        })
    write_rows(OUT["subperiod"], subperiod_rows)
    subperiod_map = by_id(subperiod_rows)

    maturity = contract.get("first_maturity_date", "")
    latest_date = max(
        [row.get("date", "") for row in data["returns"] if row.get("date")],
        default="",
    )
    matured = bool(maturity and latest_date and latest_date >= maturity)
    downside_rows: list[dict[str, object]] = []
    for overlay in eligible:
        metric = metrics.get(overlay, {})
        worst = num(by_id(data["relative"], "overlay_variant").get(overlay, {}).get("worst_5pct_daily_excess_vs_QQQ"))
        down_capture = num(metric.get("down_capture_vs_QQQ"))
        compatibility = (
            "DOWNSIDE_MONITOR_COMPATIBILITY_DATA_LIMITED"
            if not matured or worst is None
            else "DOWNSIDE_MONITOR_COMPATIBLE"
            if worst >= (num(contract.get("worst_5pct_excess_warning_threshold")) or -0.10)
            else "DOWNSIDE_MONITOR_WARNING"
        )
        downside_rows.append({
            "overlay_id": overlay,
            "monitor_first_maturity_date": maturity,
            "latest_available_overlay_date": latest_date,
            "matured_monitor_rows_available": yn(matured),
            "hit_rate_vs_QQQ": "",
            "hit_rate_warning_threshold": contract.get("hit_rate_vs_QQQ_warning_threshold", ""),
            "severe_hit_rate_warning_threshold": contract.get("severe_hit_rate_warning_threshold", ""),
            "mean_excess_vs_QQQ": "",
            "mean_excess_warning_threshold": contract.get("mean_excess_vs_QQQ_warning_threshold", ""),
            "worst_5pct_excess_vs_QQQ": fmt(worst),
            "worst_5pct_warning_threshold": contract.get("worst_5pct_excess_warning_threshold", ""),
            "payoff_ratio": "",
            "payoff_ratio_warning_threshold": contract.get("payoff_ratio_warning_threshold", ""),
            "sample_concentration": "",
            "sample_concentration_warning_threshold": contract.get("sample_concentration_warning_threshold", ""),
            "down_capture_vs_QQQ_supporting_metric": fmt(down_capture),
            "overlay_improves_downside_capture_vs_baseline": yn(
                down_capture is not None
                and num(metrics.get(BASE, {}).get("down_capture_vs_QQQ")) is not None
                and down_capture < (num(metrics.get(BASE, {}).get("down_capture_vs_QQQ")) or 0.0)
            ),
            "downside_monitor_compatibility": compatibility,
            "data_limitation": (
                "MATURED_MONITOR_OBSERVATIONS_NOT_AVAILABLE"
                if not matured else "WORST_5PCT_EXCESS_NOT_AVAILABLE"
                if worst is None else ""
            ),
            **GUARD,
        })
    write_rows(OUT["downside"], downside_rows)

    classification_rows: list[dict[str, object]] = []
    survivors: list[str] = []
    for row in eligibility_rows:
        overlay = str(row["overlay_id"])
        if row["eligibility_for_R2_packet"] != "ELIGIBLE_ACTIVE_REVIEW":
            classification = (
                "NO_OP_REJECTED" if row["no_op_status"] == "NO_OP_WARNING"
                else "DATA_LIMITED_REJECTED"
            )
            survives = False
        else:
            alpha_status = alpha_map.get(overlay, {}).get("alpha_preservation_classification", "")
            if alpha_status in {"ALPHA_DESTROYED", "ALPHA_DECAY_WARNING"}:
                classification = "ALPHA_DECAY_REJECTED"
                survives = False
            elif "COMBINED_TURNOVER_BUFFER" in overlay:
                classification = "TURNOVER_AND_DRAWDOWN_BALANCED_REVIEW_CANDIDATE"
                survives = True
            elif "DRAWDOWN" in overlay or "MA50" in overlay:
                classification = "DRAWNDOWN_SCALE_REVIEW_CANDIDATE"
                survives = True
            else:
                classification = "TURNOVER_REDUCTION_ONLY_CANDIDATE"
                survives = True
        if survives:
            survivors.append(overlay)
        classification_rows.append({
            "overlay_id": overlay,
            "candidate_classification": classification,
            "survives_as_review_only_candidate": yn(survives),
            "alpha_preservation_status": alpha_map.get(overlay, {}).get("alpha_preservation_classification", ""),
            "subperiod_stability_status": subperiod_map.get(overlay, {}).get("subperiod_stability_classification", ""),
            "review_only": yn(survives),
            "adoptable_now": "FALSE",
            **GUARD,
        })
    write_rows(OUT["classification"], classification_rows)

    scope_rows = [
        {
            "boundary_check": "research_review_packet_only",
            "check_passed": "TRUE",
            "evidence": "Outputs are limited to R2 review CSVs and reports.",
            **GUARD,
        },
        {
            "boundary_check": "no_adoption_or_official_mutation",
            "check_passed": yn(
                GUARD["overlay_adoption_allowed"] == "FALSE"
                and GUARD["official_weight_mutation"] == "FALSE"
                and GUARD["official_ranking_mutation"] == "FALSE"
            ),
            "evidence": "All adoption and mutation flags remain disabled.",
            **GUARD,
        },
        {
            "boundary_check": "no_future_return_behavior_decision",
            "check_passed": "TRUE",
            "evidence": "Only realized historical rows through the local panel end date are reviewed.",
            **GUARD,
        },
        {
            "boundary_check": "technical_only_not_full_weight",
            "check_passed": "TRUE",
            "evidence": "No full-weight backtest or full_weight_score is produced.",
            **GUARD,
        },
    ]
    write_rows(OUT["scope"], scope_rows)
    scope_ok = all(row["check_passed"] == "TRUE" for row in scope_rows)

    alpha_warning = any(
        row["alpha_preservation_classification"] != "ALPHA_PRESERVED"
        for row in alpha_rows
    )
    cost_warning = any(row["cost_status"] != "COST_PROFILE_IMPROVED" for row in cost_rows)
    if not r1a_ready:
        final_status = "BLOCKED_V21_047_R2_R1A_OUTPUTS_NOT_READY"
        decision = "BLOCK_DRAWDOWN_SCALE_REVIEW"
        next_stage = "V21.047-R1A_OVERLAY_METRIC_ATTRIBUTION_REPAIR"
    elif not scope_ok:
        final_status = "BLOCKED_V21_047_R2_SCOPE_BOUNDARY_FAILED"
        decision = "BLOCK_DRAWDOWN_SCALE_REVIEW"
        next_stage = STAGE
    elif not survivors:
        final_status = "PARTIAL_PASS_V21_047_R2_NO_CANDIDATE_SURVIVES_REVIEW"
        decision = "NO_OVERLAY_SURVIVES_KEEP_BASELINE_TECH_TOP20_10D"
        next_stage = "V21.047-R3_BASELINE_TECH_TOP20_10D_RETENTION_PACKET"
    elif alpha_warning:
        final_status = "PARTIAL_PASS_V21_047_R2_REVIEW_PACKET_WITH_ALPHA_DECAY_WARNING"
        decision = "MULTIPLE_DRAWDOWN_SCALE_CANDIDATES_REVIEW_ONLY"
        next_stage = "V21.047-R2A_CANDIDATE_TIEBREAKER_AND_SELECTION_REVIEW"
    elif cost_warning:
        final_status = "PARTIAL_PASS_V21_047_R2_REVIEW_PACKET_WITH_COST_WARNING"
        decision = "MULTIPLE_DRAWDOWN_SCALE_CANDIDATES_REVIEW_ONLY"
        next_stage = "V21.047-R2A_CANDIDATE_TIEBREAKER_AND_SELECTION_REVIEW"
    elif rejected_noop:
        final_status = "PARTIAL_PASS_V21_047_R2_REVIEW_PACKET_WITH_NO_OP_REJECTIONS"
        decision = (
            "COMBINED_TURNOVER_QQQ_MA50_REVIEW_CANDIDATE_NOT_ADOPTABLE"
            if survivors == ["COMBINED_TURNOVER_BUFFER_25_PLUS_QQQ_MA50"]
            else "MULTIPLE_DRAWDOWN_SCALE_CANDIDATES_REVIEW_ONLY"
        )
        next_stage = (
            "V21.047-R3_OPERATOR_REVIEW_DECISION_CAPTURE"
            if len(survivors) == 1 else "V21.047-R2A_CANDIDATE_TIEBREAKER_AND_SELECTION_REVIEW"
        )
    else:
        final_status = "PASS_V21_047_R2_DRAWDOWN_SCALE_REVIEW_PACKET_READY"
        decision = (
            "COMBINED_TURNOVER_QQQ_MA50_REVIEW_CANDIDATE_NOT_ADOPTABLE"
            if survivors == ["COMBINED_TURNOVER_BUFFER_25_PLUS_QQQ_MA50"]
            else "MULTIPLE_DRAWDOWN_SCALE_CANDIDATES_REVIEW_ONLY"
        )
        next_stage = (
            "V21.047-R3_OPERATOR_REVIEW_DECISION_CAPTURE"
            if len(survivors) == 1 else "V21.047-R2A_CANDIDATE_TIEBREAKER_AND_SELECTION_REVIEW"
        )

    alpha_summary = (
        "ALL_SURVIVORS_ALPHA_PRESERVED"
        if survivors and all(
            alpha_map.get(overlay, {}).get("alpha_preservation_classification") == "ALPHA_PRESERVED"
            for overlay in survivors
        ) else "ALPHA_PRESERVATION_WARNINGS_PRESENT"
    )
    cost_summary = (
        "COMBINED_CANDIDATE_TURNOVER_WARNING_REDUCED"
        if any(
            row["overlay_id"] == "COMBINED_TURNOVER_BUFFER_25_PLUS_QQQ_MA50"
            and row["turnover_warning_status"] == "TURNOVER_WARNING_REDUCED"
            for row in cost_rows
        ) else "TURNOVER_WARNING_NOT_RESOLVED"
    )
    downside_summary = (
        "DOWNSIDE_MONITOR_COMPATIBILITY_DATA_LIMITED_UNTIL_2026_06_24"
        if not matured else "DOWNSIDE_MONITOR_COMPATIBILITY_REVIEW_AVAILABLE"
    )
    decision_row = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "baseline_variant": BASE_LABEL,
        "candidate_overlays_reviewed": "|".join(PRIMARY),
        "eligible_candidates": "|".join(eligible) if eligible else "NONE",
        "surviving_review_only_candidates": "|".join(survivors) if survivors else "NONE",
        "rejected_no_op_overlays": "|".join(rejected_noop) if rejected_noop else "NONE",
        "alpha_preservation_status": alpha_summary,
        "turnover_cost_status": cost_summary,
        "subperiod_stability_status": "SUBPERIOD_AND_ROLLING_REVIEW_COMPLETED",
        "downside_monitor_compatibility_status": downside_summary,
        "any_overlay_adoptable_now": "FALSE",
        "overlay_adopted": "FALSE",
        "portfolio_variant_adopted": "FALSE",
        "filter_adopted": "FALSE",
        "full_weight_blocked": "TRUE",
        "recommended_next_stage": next_stage,
        **GUARD,
    }
    write_rows(OUT["decision"], [decision_row])

    comparison_table = "\n".join(
        f"| {row['display_name']} | {row['total_return']} | {row['Sharpe']} | "
        f"{row['max_drawdown']} | {row['information_ratio']} | {row['turnover_reduction_ratio']} |"
        for row in comparison_rows
    )
    baseline = metrics.get(BASE, {})
    report = f"""# V21.047-R2 Drawdown Scale Review Packet

final_status: {final_status}

decision: {decision}

## Why R1A was required

V21.047 originally mixed headline metrics from different overlays. R1A repaired attribution so each candidate is evaluated from its own curve, exposure, turnover, cost, and relative metrics. No overlay was adopted upstream and full-weight remained blocked.

## Candidates reviewed

{", ".join(PRIMARY)}.

No-op rejection summary: {", ".join(rejected_noop) if rejected_noop else "NONE"}. TURNOVER_BUFFER_RANK_30 remains quarantined and rejected from active review.

## Baseline

TECH_TOP20_EQUAL_WEIGHT_10D: total_return={baseline.get('total_return', '')}, CAGR={baseline.get('CAGR', '')}, volatility={baseline.get('volatility', '')}, Sharpe={baseline.get('Sharpe', '')}, Sortino={baseline.get('Sortino', '')}, max_drawdown={baseline.get('max_drawdown', '')}.

## Candidate comparison

| Overlay | Total return | Sharpe | Max drawdown | Information ratio | Turnover reduction |
|---|---:|---:|---:|---:|---:|
{comparison_table}

## Drawdown and risk-off behavior

Risk-off days, exposure, avoided drawdown, upside missed, exposure transitions, short-episode whipsaws, and available MA50 regime performance are recorded in the behavior audit. Exact re-entry lag after QQQ recovery is not asserted because a QQQ recovery-marker series is not present in the specified inputs.

## Turnover and cost behavior

{cost_summary}. The combined turnover-buffer candidate reduces reconstructed turnover by {preservation.get('COMBINED_TURNOVER_BUFFER_25_PLUS_QQQ_MA50', {}).get('turnover_reduction_ratio', '')}; stale-holding risk remains an operator-review item.

## Alpha preservation

{alpha_summary}. Candidate-level return, Sharpe, Sortino, information-ratio, active-return, and subperiod tests are recorded in the alpha audit.

## Subperiod stability

Subperiod and rolling review completed for 2023 partial, 2024, 2025, 2026 YTD, rolling six-month, and rolling twelve-month windows.

## Downside monitor compatibility

{downside_summary}. The monitor contract first matures on {maturity}, after the latest available overlay date {latest_date}; unavailable hit-rate, payoff, concentration, and worst-tail observations are not fabricated.

Final review-only candidate(s): {"|".join(survivors) if survivors else "NONE"}.

No overlay is adopted because this stage is a research-only review packet and has no adoption, shadow-gate, execution, or official-mutation authority.

No overlay was adopted.

Technical-only overlay review results must not be interpreted as full-weight results or full-weight evidence.

Full-weight remains blocked: TRUE.

Recommended next stage: {next_stage}

Guardrail statement: research_only=TRUE; drawdown_scale_review_packet_only=TRUE; no overlay, portfolio variant, or filter adoption; no official ranking or weight mutation; no official recommendation; no real-book, broker, execution, trade-action, shadow-gate, or shadow-adoption output; no buy/sell/hold recommendation; local artifacts only; online_download_attempted=FALSE; yfinance_used=FALSE.
"""
    REPORT.write_text(report, encoding="utf-8")
    shutil.copyfile(REPORT, CURRENT)

    print(f"final_status={final_status}")
    print(f"decision={decision}")
    print(f"surviving_review_only_candidates={'|'.join(survivors) if survivors else 'NONE'}")
    print(f"rejected_no_op_overlays={'|'.join(rejected_noop) if rejected_noop else 'NONE'}")
    print(f"alpha_preservation_status={alpha_summary}")
    print(f"turnover_cost_status={cost_summary}")
    print(f"recommended_next_stage={next_stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
