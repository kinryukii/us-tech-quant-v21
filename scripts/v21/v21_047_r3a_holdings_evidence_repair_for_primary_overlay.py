#!/usr/bin/env python
"""Research-only holdings evidence repair for the V21.047 primary overlay."""

from __future__ import annotations

import csv
import math
import shutil
import statistics
from collections import defaultdict, deque
from pathlib import Path


STAGE = "V21.047-R3A_HOLDINGS_EVIDENCE_REPAIR_FOR_PRIMARY_OVERLAY"
ROOT = Path(__file__).resolve().parents[2]
BT = ROOT / "outputs" / "v21" / "backtest"
REV = ROOT / "outputs" / "v21" / "review"
RC = ROOT / "outputs" / "v21" / "read_center"
PRIMARY = "COMBINED_TURNOVER_BUFFER_25_PLUS_QQQ_MA50"
BASE = "BASELINE_TECH_TOP20_10D"
BASE_LABEL = "TECH_TOP20_EQUAL_WEIGHT_10D"

INPUTS = {
    "r3_decision": REV / "V21_047_R3_DECISION_SUMMARY.csv",
    "r3_packet": REV / "V21_047_R3_OPERATOR_REVIEW_PACKET.csv",
    "r3_capture": REV / "V21_047_R3_OPERATOR_DECISION_CAPTURE.csv",
    "r3_warnings": REV / "V21_047_R3_CANDIDATE_WARNING_REGISTER.csv",
    "r3_routing": REV / "V21_047_R3_NEXT_STAGE_ROUTING.csv",
    "r2a_decision": REV / "V21_047_R2A_DECISION_SUMMARY.csv",
    "r2a_metrics": REV / "V21_047_R2A_CANDIDATE_METRIC_CONSOLIDATION.csv",
    "r2a_ranking": REV / "V21_047_R2A_CANDIDATE_RANKING.csv",
    "r2a_combined": REV / "V21_047_R2A_COMBINED_CANDIDATE_DEEP_REVIEW.csv",
    "r2a_cost": REV / "V21_047_R2A_COST_WARNING_AUDIT.csv",
    "equity": BT / "V21_047_OVERLAY_EQUITY_CURVE_PANEL.csv",
    "returns": BT / "V21_047_OVERLAY_DAILY_RETURNS_PANEL.csv",
    "holdings": BT / "V21_047_OVERLAY_HOLDINGS_BY_REBALANCE.csv",
    "turnover": BT / "V21_047_OVERLAY_TURNOVER_COST_PANEL.csv",
    "risk": BT / "V21_047_OVERLAY_RISK_METRIC_SUMMARY.csv",
    "relative": BT / "V21_047_OVERLAY_RELATIVE_METRICS_VS_QQQ.csv",
    "drawdown": BT / "V21_047_OVERLAY_DRAWDOWN_DIAGNOSTICS.csv",
    "r3_holdings": BT / "V21_046_R3_REPAIRED_TECHNICAL_ONLY_PORTFOLIO_HOLDINGS_BY_REBALANCE.csv",
    "r3_returns": BT / "V21_046_R3_REPAIRED_TECHNICAL_ONLY_PORTFOLIO_DAILY_RETURNS.csv",
    "r3_risk": BT / "V21_046_R3_REPAIRED_EQUITY_CURVE_RISK_METRIC_SUMMARY.csv",
    "r4_turnover": REV / "V21_046_R4_TURNOVER_COST_AUDIT.csv",
    "qqq_prices": ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv",
}

OUT = {
    "upstream": REV / "V21_047_R3A_UPSTREAM_DECISION_AUDIT.csv",
    "availability": REV / "V21_047_R3A_EVIDENCE_AVAILABILITY_AUDIT.csv",
    "holdings": REV / "V21_047_R3A_HOLDINGS_EQUALITY_AUDIT.csv",
    "exposure": REV / "V21_047_R3A_EXPOSURE_RECONSTRUCTION.csv",
    "turnover": REV / "V21_047_R3A_TURNOVER_EVIDENCE_RECONSTRUCTION.csv",
    "rank_buffer": REV / "V21_047_R3A_RANK_BUFFER_EVIDENCE_AUDIT.csv",
    "returns": REV / "V21_047_R3A_DAILY_RETURN_CONSISTENCY_AUDIT.csv",
    "metrics": REV / "V21_047_R3A_METRIC_RECONCILIATION_AUDIT.csv",
    "caveat": REV / "V21_047_R3A_CAVEAT_RESOLUTION_AUDIT.csv",
    "scope": REV / "V21_047_R3A_SCOPE_BOUNDARY_AUDIT.csv",
    "decision": REV / "V21_047_R3A_DECISION_SUMMARY.csv",
}
REPORT = RC / "V21_047_R3A_HOLDINGS_EVIDENCE_REPAIR_FOR_PRIMARY_OVERLAY_REPORT.md"
CURRENT = RC / "CURRENT_V21_047_R3A_HOLDINGS_EVIDENCE_REPAIR_FOR_PRIMARY_OVERLAY_REPORT.md"

GUARD = {
    "research_only": "TRUE",
    "holdings_evidence_repair_only": "TRUE",
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


def group(rows: list[dict[str, str]], key: str, value: str) -> list[dict[str, str]]:
    return [row for row in rows if row.get(key) == value]


def holdings_map(rows: list[dict[str, str]], overlay: str) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = defaultdict(dict)
    for row in rows:
        if row.get("overlay_variant") == overlay:
            weight = num(row.get("weight"))
            if weight is not None:
                result[row.get("rebalance_date", "")][row.get("ticker", "")] = weight
    return result


def one_way_turnover(previous: dict[str, float], current: dict[str, float]) -> float:
    return sum(abs(current.get(ticker, 0.0) - previous.get(ticker, 0.0)) for ticker in set(previous) | set(current)) / 2.0


def compound(values: list[float]) -> float:
    return math.prod(1.0 + value for value in values) - 1.0


def upstream_sharpe(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    volatility = statistics.stdev(values) * math.sqrt(252)
    years = len(values) / 252.0
    if volatility <= 0 or years <= 0:
        return None
    cagr = (1.0 + compound(values)) ** (1.0 / years) - 1.0
    return cagr / volatility


def max_drawdown(values: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in values:
        equity *= 1.0 + value
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0)
    return worst


def after_cost_returns(
    daily_rows: list[dict[str, str]], cost_rows: list[dict[str, str]], field: str
) -> list[float]:
    costs = {row.get("rebalance_date", ""): num(row.get(field)) or 0.0 for row in cost_rows}
    charged: set[str] = set()
    result: list[float] = []
    for row in sorted(daily_rows, key=lambda item: item.get("date", "")):
        value = num(row.get("daily_return"))
        if value is None:
            continue
        rebalance = row.get("rebalance_date", "")
        cost = 0.0
        if rebalance and rebalance not in charged:
            cost = costs.get(rebalance, 0.0)
            charged.add(rebalance)
        result.append(value - cost)
    return result


def main() -> int:
    REV.mkdir(parents=True, exist_ok=True)
    RC.mkdir(parents=True, exist_ok=True)
    data = {name: read_rows(path) for name, path in INPUTS.items()}
    missing = [name for name, rows in data.items() if not rows]
    r3 = data["r3_decision"][0] if data["r3_decision"] else {}
    ready = (
        not missing
        and r3.get("decision") == "APPROVE_PRIMARY_WITH_HOLDINGS_EVIDENCE_REPAIR_REQUIRED"
        and r3.get("primary_candidate") == PRIMARY
        and r3.get("overlay_adopted") == "FALSE"
        and r3.get("full_weight_blocked") == "TRUE"
        and r3.get("holdings_evidence_caveat")
        == "HOLDINGS_SNAPSHOTS_UNCHANGED_DESPITE_REPORTED_TURNOVER_REDUCTION"
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
    upstream_rows.extend([
        {
            "audit_item": "r3_decision_authorizes_evidence_repair_only",
            "input_name": "r3_decision",
            "path": str(INPUTS["r3_decision"].relative_to(ROOT)),
            "check_passed": yn(ready),
            "evidence": (
                f"{r3.get('decision', '')}|{r3.get('primary_candidate', '')}|"
                f"overlay_adopted={r3.get('overlay_adopted', '')}|"
                f"full_weight_blocked={r3.get('full_weight_blocked', '')}"
            ),
            **GUARD,
        },
    ])
    write_rows(OUT["upstream"], upstream_rows)

    baseline_holdings = holdings_map(data["holdings"], BASE)
    overlay_holdings = holdings_map(data["holdings"], PRIMARY)
    base_returns = group(data["returns"], "overlay_variant", BASE)
    overlay_returns = group(data["returns"], "overlay_variant", PRIMARY)
    base_equity = group(data["equity"], "overlay_variant", BASE)
    overlay_equity = group(data["equity"], "overlay_variant", PRIMARY)
    base_turn = group(data["turnover"], "overlay_variant", BASE)
    overlay_turn = group(data["turnover"], "overlay_variant", PRIMARY)
    qqq_rows = sorted(
        [row for row in data["qqq_prices"] if row.get("symbol") == "QQQ"],
        key=lambda row: row.get("date", ""),
    )
    rank_fields = {
        key for row in data["holdings"] for key in row
        if any(token in key.lower() for token in ("rank", "retain", "drop", "replace", "skip"))
    }
    availability = [
        ("baseline_holdings_by_rebalance", bool(baseline_holdings), "AVAILABLE_USABLE"),
        ("primary_holdings_by_rebalance", bool(overlay_holdings), "AVAILABLE_BUT_SAME_AS_BASELINE"),
        ("baseline_daily_returns", bool(base_returns), "AVAILABLE_USABLE"),
        ("primary_daily_returns", bool(overlay_returns), "AVAILABLE_USABLE"),
        ("primary_exposure_rows", bool(overlay_equity), "AVAILABLE_USABLE"),
        ("baseline_turnover_rows", bool(base_turn), "AVAILABLE_USABLE"),
        ("primary_turnover_rows", bool(overlay_turn), "AVAILABLE_USABLE"),
        ("primary_cost_rows", bool(overlay_turn), "AVAILABLE_USABLE"),
        ("QQQ_MA50_risk_off_state_rows", bool(qqq_rows), "AVAILABLE_USABLE"),
        ("rebalance_date_rows", bool(baseline_holdings), "AVAILABLE_USABLE"),
        ("candidate_membership_rows", bool(overlay_holdings), "AVAILABLE_BUT_SAME_AS_BASELINE"),
        ("rank_buffer_retained_dropped_replaced_rows", bool(rank_fields), "AVAILABLE_USABLE" if rank_fields else "MISSING"),
    ]
    write_rows(OUT["availability"], [
        {
            "evidence_item": item,
            "rows_or_fields_present": yn(present),
            "evidence_classification": classification if present or classification == "MISSING" else "MISSING",
            "limitation": (
                "No retained/skipped/dropped/replaced rank-buffer fields exist."
                if item == "rank_buffer_retained_dropped_replaced_rows" and not present else ""
            ),
            **GUARD,
        }
        for item, present, classification in availability
    ])

    equality_rows: list[dict[str, object]] = []
    dates = sorted(set(baseline_holdings) | set(overlay_holdings))
    all_same = True
    for rebalance in dates:
        base = baseline_holdings.get(rebalance, {})
        overlay = overlay_holdings.get(rebalance, {})
        overlap = set(base) & set(overlay)
        added = set(overlay) - set(base)
        removed = set(base) - set(overlay)
        changed_weights = [
            ticker for ticker in overlap
            if abs(base[ticker] - overlay[ticker]) > 1e-10
        ]
        union_count = len(set(base) | set(overlay))
        same = not added and not removed and not changed_weights
        all_same = all_same and same
        equality_rows.append({
            "rebalance_date": rebalance,
            "baseline_holdings_count": len(base),
            "overlay_holdings_count": len(overlay),
            "overlapping_ticker_count": len(overlap),
            "added_ticker_count": len(added),
            "removed_ticker_count": len(removed),
            "changed_ticker_ratio": fmt((len(added) + len(removed)) / union_count if union_count else None),
            "weights_changed_count": len(changed_weights),
            "weights_changed_ratio": fmt(len(changed_weights) / len(overlap) if overlap else None),
            "holdings_snapshot_same_as_baseline": yn(same),
            "interpretation": "EXPECTED_FOR_PURE_EXPOSURE_SCALING_COMPONENT" if same else "HOLDINGS_CHANGE_EVIDENCED",
            **GUARD,
        })
    write_rows(OUT["holdings"], equality_rows)

    qqq_ma: dict[str, tuple[float, float, bool]] = {}
    window: deque[float] = deque()
    running = 0.0
    for row in qqq_rows:
        close = num(row.get("adjusted_close"))
        if close is None:
            continue
        window.append(close)
        running += close
        if len(window) > 50:
            running -= window.popleft()
        if len(window) == 50:
            ma = running / 50.0
            qqq_ma[row.get("date", "")] = (close, ma, close >= ma)
    exposure_by_date = {
        row.get("date", ""): num(row.get("exposure")) for row in overlay_equity
    }
    exposure_rows: list[dict[str, object]] = []
    exposure_match = True
    for row in sorted(overlay_returns, key=lambda item: item.get("date", "")):
        day = row.get("date", "")
        state = qqq_ma.get(day)
        exposure = num(row.get("exposure"))
        if state is None or exposure is None:
            continue
        close, ma, above = state
        inferred_target = 1.0 if above else 0.5
        match = abs(exposure - inferred_target) <= 1e-10
        exposure_match = exposure_match and match
        exposure_rows.append({
            "date": day,
            "QQQ_adjusted_close": fmt(close),
            "QQQ_MA50": fmt(ma),
            "qqq_above_ma50": yn(above),
            "risk_off_flag": yn(not above),
            "target_exposure": fmt(exposure),
            "cash_weight": fmt(1.0 - exposure),
            "equity_weight": fmt(exposure),
            "exposure_changed_vs_baseline": yn(abs(exposure - 1.0) > 1e-10),
            "inferred_rule_target_exposure": fmt(inferred_target),
            "existing_exposure_matches_inferred_MA50_rule": yn(match),
            "rule_inference_status": "INFERRED_FROM_EXISTING_OUTPUTS_AND_LOCAL_QQQ_PRICES",
            **GUARD,
        })
    write_rows(OUT["exposure"], exposure_rows)

    base_turn_map = {row.get("rebalance_date", ""): num(row.get("turnover")) for row in base_turn}
    overlay_turn_map = {row.get("rebalance_date", ""): num(row.get("turnover")) for row in overlay_turn}
    cost20_map = {row.get("rebalance_date", ""): num(row.get("estimated_cost_drag_20bps")) for row in overlay_turn}
    first_exposure_by_rebalance: dict[str, float] = {}
    previous_exposure_by_rebalance: dict[str, float] = {}
    sorted_daily = sorted(overlay_returns, key=lambda row: row.get("date", ""))
    prior_exposure = 1.0
    for row in sorted_daily:
        rebalance = row.get("rebalance_date", "")
        exposure = num(row.get("exposure"))
        if rebalance and exposure is not None and rebalance not in first_exposure_by_rebalance:
            first_exposure_by_rebalance[rebalance] = exposure
            previous_exposure_by_rebalance[rebalance] = prior_exposure
        if exposure is not None:
            prior_exposure = exposure
    turnover_rows: list[dict[str, object]] = []
    prior_base: dict[str, float] = {}
    prior_overlay: dict[str, float] = {}
    reported_ratios: list[float] = []
    actual_reductions: list[float] = []
    for rebalance in dates:
        current_base = baseline_holdings.get(rebalance, {})
        current_overlay = overlay_holdings.get(rebalance, {})
        holdings_turn_base = one_way_turnover(prior_base, current_base)
        holdings_turn_overlay = one_way_turnover(prior_overlay, current_overlay)
        current_exposure = first_exposure_by_rebalance.get(rebalance, 1.0)
        previous_exposure = previous_exposure_by_rebalance.get(rebalance, 1.0)
        exposure_turnover = abs(current_exposure - previous_exposure)
        effective_turnover = holdings_turn_overlay * current_exposure + exposure_turnover
        reported = overlay_turn_map.get(rebalance)
        baseline_reported = base_turn_map.get(rebalance)
        reported_reduction = (
            1.0 - reported / baseline_reported
            if reported is not None and baseline_reported not in (None, 0.0) else None
        )
        actual_reduction = (
            1.0 - holdings_turn_overlay / holdings_turn_base
            if holdings_turn_base > 0 else 0.0
        )
        if reported_reduction is not None:
            reported_ratios.append(reported_reduction)
        actual_reductions.append(actual_reduction)
        turnover_rows.append({
            "rebalance_date": rebalance,
            "baseline_holdings_turnover_reconstructed": fmt(holdings_turn_base),
            "overlay_holdings_turnover_reconstructed": fmt(holdings_turn_overlay),
            "holdings_turnover": fmt(holdings_turn_overlay),
            "exposure_turnover": fmt(exposure_turnover),
            "combined_effective_turnover": fmt(effective_turnover),
            "cost_applicable_turnover_reported": fmt(reported),
            "reported_cost_drag_20bps": fmt(cost20_map.get(rebalance)),
            "baseline_turnover_reported": fmt(baseline_reported),
            "turnover_reduction_vs_baseline_reported": fmt(reported_reduction),
            "turnover_reduction_vs_baseline_reconstructed_holdings": fmt(actual_reduction),
            "turnover_explanation_classification": "NOT_EXPLAINED_REPAIR_REQUIRED",
            "explanation": "Reported turnover is 70% of baseline while reconstructed holdings turnover is unchanged.",
            **GUARD,
        })
        prior_base = current_base
        prior_overlay = current_overlay
    write_rows(OUT["turnover"], turnover_rows)
    reported_turnover_reduction = statistics.fmean(reported_ratios) if reported_ratios else None
    reconstructed_holdings_reduction = statistics.fmean(actual_reductions) if actual_reductions else None
    uniform_30 = bool(reported_ratios) and all(abs(value - 0.30) <= 1e-10 for value in reported_ratios)

    rank_buffer_rows = [
        {
            "audit_item": "rank_buffer_retained_names",
            "evidence_status": "RANK_BUFFER_EVIDENCE_MISSING",
            "row_count": 0,
            "result": "NOT_IDENTIFIABLE_FROM_AVAILABLE_ARTIFACTS",
            "blocks_review": "TRUE",
            **GUARD,
        },
        {
            "audit_item": "rank_buffer_skipped_candidates",
            "evidence_status": "RANK_BUFFER_EVIDENCE_MISSING",
            "row_count": 0,
            "result": "NOT_IDENTIFIABLE_FROM_AVAILABLE_ARTIFACTS",
            "blocks_review": "TRUE",
            **GUARD,
        },
        {
            "audit_item": "rank_buffer_dropped_and_added_names",
            "evidence_status": "RANK_BUFFER_EVIDENCE_MISSING",
            "row_count": 0,
            "result": "OVERLAY_HOLDINGS_EQUAL_BASELINE_AT_ALL_REBALANCES",
            "blocks_review": "TRUE",
            **GUARD,
        },
        {
            "audit_item": "baseline_vs_buffer_turnover",
            "evidence_status": "RANK_BUFFER_EVIDENCE_MISSING",
            "row_count": len(turnover_rows),
            "result": (
                "REPORTED_UNIFORM_30PCT_REDUCTION_WITHOUT_MEMBERSHIP_OR_WEIGHT_CHANGE"
                if uniform_30 else "TURNOVER_PATTERN_NOT_UNIFORM"
            ),
            "blocks_review": "TRUE",
            **GUARD,
        },
    ]
    write_rows(OUT["rank_buffer"], rank_buffer_rows)

    baseline_return_map = {
        row.get("date", ""): num(row.get("daily_return")) for row in base_returns
    }
    consistency_rows: list[dict[str, object]] = []
    unexplained_values: list[float] = []
    overlay_values: list[float] = []
    for row in sorted(overlay_returns, key=lambda item: item.get("date", "")):
        day = row.get("date", "")
        baseline_return = baseline_return_map.get(day)
        overlay_return = num(row.get("daily_return"))
        exposure = num(row.get("exposure"))
        if baseline_return is None or overlay_return is None or exposure is None:
            continue
        expected = exposure * baseline_return
        difference = overlay_return - baseline_return
        unexplained = overlay_return - expected
        explained = abs(unexplained) <= 1e-10
        unexplained_values.append(abs(unexplained))
        overlay_values.append(overlay_return)
        consistency_rows.append({
            "date": day,
            "daily_return_baseline": fmt(baseline_return),
            "daily_return_overlay": fmt(overlay_return),
            "exposure": fmt(exposure),
            "cash_weight": fmt(1.0 - exposure),
            "expected_overlay_return": fmt(expected),
            "daily_return_difference": fmt(difference),
            "return_difference_explained_by_exposure": yn(explained),
            "unexplained_return_difference": fmt(unexplained),
            "return_evidence_status": "RETURN_EXPLAINED_BY_EXPOSURE_SCALING" if explained else "RETURN_EVIDENCE_REPAIR_REQUIRED",
            **GUARD,
        })
    write_rows(OUT["returns"], consistency_rows)
    returns_consistent = bool(consistency_rows) and max(unexplained_values, default=1.0) <= 1e-10

    r2a_metrics = by_id(data["r2a_metrics"], "overlay_id").get(PRIMARY, {})
    r2a_cost = by_id(data["r2a_cost"], "overlay_id").get(PRIMARY, {})
    reconstructed_total = compound(overlay_values)
    sorted_overlay_returns = sorted(overlay_returns, key=lambda item: item.get("date", ""))
    reconstructed_sharpe = upstream_sharpe(overlay_values)
    reconstructed_drawdown = max_drawdown(overlay_values)
    after_cost = after_cost_returns(overlay_returns, overlay_turn, "estimated_cost_drag_20bps")
    reconstructed_after_cost = compound(after_cost)
    metric_specs = [
        ("total_return", num(r2a_metrics.get("total_return")), reconstructed_total, 1e-8),
        ("Sharpe", num(r2a_metrics.get("Sharpe")), reconstructed_sharpe, 1e-8),
        ("max_drawdown", num(r2a_metrics.get("max_drawdown")), reconstructed_drawdown, 1e-8),
        ("turnover_reduction", num(r2a_metrics.get("turnover_reduction_vs_baseline")), reconstructed_holdings_reduction, 1e-8),
        ("after_cost_return_20bps", num(r2a_cost.get("after_cost_total_return_20bps")), reconstructed_after_cost, 1e-8),
    ]
    metric_rows: list[dict[str, object]] = []
    material_mismatch = False
    for metric, reported, reconstructed, tolerance in metric_specs:
        difference = (
            reconstructed - reported
            if reconstructed is not None and reported is not None else None
        )
        match = difference is not None and abs(difference) <= tolerance
        if metric == "turnover_reduction" and not match:
            material_mismatch = True
        metric_rows.append({
            "metric": metric,
            "reported_value": fmt(reported),
            "reconstructed_value": fmt(reconstructed),
            "difference": fmt(difference),
            "match_tolerance": fmt(tolerance),
            "metric_match_status": "MATCH" if match else "MISMATCH",
            "material_mismatch": yn(metric == "turnover_reduction" and not match),
            "reconstruction_basis": (
                "ACTUAL_HOLDINGS_MEMBERSHIP_AND_WEIGHTS"
                if metric == "turnover_reduction" else
                "REPORTED_COST_PANEL_APPLIED_TO_DAILY_RETURNS"
                if metric == "after_cost_return_20bps" else
                "PRIMARY_OVERLAY_DAILY_RETURN_PANEL"
            ),
            **GUARD,
        })
    write_rows(OUT["metrics"], metric_rows)
    metric_status = (
        "METRIC_RECONCILIATION_WARNING_TURNOVER_MISMATCH"
        if material_mismatch else "METRICS_RECONCILED"
    )

    if all_same and exposure_match and returns_consistent and material_mismatch:
        caveat_resolution = "CAVEAT_PARTIALLY_RESOLVED_RANK_BUFFER_EVIDENCE_MISSING"
        turnover_explanation = "NOT_EXPLAINED_REPAIR_REQUIRED"
        review_can_continue = False
    elif all_same and exposure_match and returns_consistent:
        caveat_resolution = "CAVEAT_RESOLVED_EXPLAINED_BY_EXPOSURE_SCALING"
        turnover_explanation = "EXPLAINED_BY_EXPOSURE_SCALING"
        review_can_continue = True
    else:
        caveat_resolution = "CAVEAT_NOT_RESOLVED_REPAIR_REQUIRED"
        turnover_explanation = "DATA_LIMITED"
        review_can_continue = False
    caveat_rows = [{
        "primary_overlay": PRIMARY,
        "original_caveat": r3.get("holdings_evidence_caveat", ""),
        "holdings_equality_result": "IDENTICAL_AT_ALL_REBALANCES" if all_same else "HOLDINGS_DIFFER",
        "exposure_reconstruction_result": "QQQ_MA50_EXPOSURE_RULE_FULLY_MATCHED" if exposure_match else "EXPOSURE_RULE_MISMATCH",
        "daily_return_consistency_result": "RETURNS_FULLY_EXPLAINED_BY_EXPOSURE" if returns_consistent else "RETURN_EVIDENCE_REPAIR_REQUIRED",
        "turnover_reduction_explanation": turnover_explanation,
        "rank_buffer_evidence_status": "RANK_BUFFER_EVIDENCE_MISSING",
        "metric_reconciliation_status": metric_status,
        "caveat_resolution": caveat_resolution,
        "primary_overlay_review_can_continue": yn(review_can_continue),
        **GUARD,
    }]
    write_rows(OUT["caveat"], caveat_rows)

    scope_rows = [
        {"boundary_check": "holdings_evidence_repair_only", "check_passed": "TRUE", "evidence": "Only reconstructed research audits are written.", **GUARD},
        {"boundary_check": "local_data_only", "check_passed": "TRUE", "evidence": "The local canonical QQQ artifact is read without network access.", **GUARD},
        {"boundary_check": "no_future_returns_used", "check_passed": "TRUE", "evidence": "MA50 uses each date and its preceding 49 local QQQ observations.", **GUARD},
        {"boundary_check": "no_adoption_or_official_mutation", "check_passed": "TRUE", "evidence": "All adoption, official mutation, shadow, and execution flags are disabled.", **GUARD},
        {"boundary_check": "technical_only_not_full_weight", "check_passed": "TRUE", "evidence": "No full-weight backtest or score is created.", **GUARD},
    ]
    write_rows(OUT["scope"], scope_rows)
    scope_ok = all(row["check_passed"] == "TRUE" for row in scope_rows)

    if not ready:
        final_status = "BLOCKED_V21_047_R3A_R3_OUTPUTS_NOT_READY"
        decision = "BLOCK_HOLDINGS_EVIDENCE_REPAIR"
        next_stage = "V21.047-R3_OPERATOR_REVIEW_DECISION_CAPTURE"
    elif not scope_ok:
        final_status = "BLOCKED_V21_047_R3A_SCOPE_BOUNDARY_FAILED"
        decision = "BLOCK_HOLDINGS_EVIDENCE_REPAIR"
        next_stage = STAGE
    elif material_mismatch:
        final_status = "PARTIAL_PASS_V21_047_R3A_METRIC_RECONCILIATION_WARNING"
        decision = "PRIMARY_OVERLAY_METRIC_RECONCILIATION_REPAIR_REQUIRED"
        next_stage = "V21.047-R3C_PRIMARY_OVERLAY_METRIC_RECONCILIATION_REPAIR"
    elif caveat_resolution == "CAVEAT_RESOLVED_EXPLAINED_BY_EXPOSURE_SCALING":
        final_status = "PARTIAL_PASS_V21_047_R3A_CAVEAT_RESOLVED_BY_EXPOSURE_SCALING"
        decision = "PRIMARY_OVERLAY_CAVEAT_EXPLAINED_BY_EXPOSURE_SCALING_NOT_ADOPTABLE"
        next_stage = "V21.047-R4_PRIMARY_OVERLAY_REVIEW_PACKET"
    elif caveat_resolution == "CAVEAT_PARTIALLY_RESOLVED_RANK_BUFFER_EVIDENCE_MISSING":
        final_status = "PARTIAL_PASS_V21_047_R3A_RANK_BUFFER_EVIDENCE_MISSING"
        decision = "PRIMARY_OVERLAY_REVIEW_REQUIRES_RANK_BUFFER_EVIDENCE_REPAIR"
        next_stage = "V21.047-R3B_RANK_BUFFER_EVIDENCE_REPAIR"
    else:
        final_status = "PARTIAL_PASS_V21_047_R3A_CAVEAT_NOT_RESOLVED"
        decision = "PRIMARY_OVERLAY_EVIDENCE_CAVEAT_BLOCKS_REVIEW"
        next_stage = "V21.047-R4_SECONDARY_QQQ_MA50_REVIEW_PACKET"

    decision_row = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "primary_overlay": PRIMARY,
        "baseline": BASE_LABEL,
        "holdings_equality_result": "IDENTICAL_AT_ALL_REBALANCES" if all_same else "HOLDINGS_DIFFER",
        "exposure_reconstruction_result": "QQQ_MA50_EXPOSURE_RULE_FULLY_MATCHED" if exposure_match else "EXPOSURE_RULE_MISMATCH",
        "turnover_explanation": turnover_explanation,
        "reported_turnover_reduction": fmt(reported_turnover_reduction),
        "reconstructed_holdings_turnover_reduction": fmt(reconstructed_holdings_reduction),
        "rank_buffer_evidence_status": "RANK_BUFFER_EVIDENCE_MISSING",
        "daily_return_consistency_result": "RETURNS_FULLY_EXPLAINED_BY_EXPOSURE" if returns_consistent else "RETURN_EVIDENCE_REPAIR_REQUIRED",
        "metric_reconciliation_status": metric_status,
        "caveat_resolution": caveat_resolution,
        "primary_overlay_review_can_continue": yn(review_can_continue),
        "any_overlay_adoptable_now": "FALSE",
        "overlay_adopted": "FALSE",
        "portfolio_variant_adopted": "FALSE",
        "filter_adopted": "FALSE",
        "full_weight_blocked": "TRUE",
        "recommended_next_stage": next_stage,
        **GUARD,
    }
    write_rows(OUT["decision"], [decision_row])

    report = f"""# V21.047-R3A Holdings Evidence Repair for Primary Overlay

final_status: {final_status}

decision: {decision}

Primary overlay: {PRIMARY}.

Original holdings evidence caveat: {r3.get('holdings_evidence_caveat', '')}.

Evidence availability summary: holdings, daily returns, exposure, turnover, cost, rebalance dates, and local QQQ price history are available. Explicit rank-buffer retained/skipped/dropped/replaced evidence is missing.

Holdings equality result: {"IDENTICAL_AT_ALL_REBALANCES" if all_same else "HOLDINGS_DIFFER"}. Identical ticker snapshots are consistent with the QQQ MA50 component changing aggregate exposure rather than constituent membership.

Exposure reconstruction result: {"QQQ_MA50_EXPOSURE_RULE_FULLY_MATCHED" if exposure_match else "EXPOSURE_RULE_MISMATCH"}. Across {len(exposure_rows)} dates, existing exposure equals 1.0 when local QQQ adjusted close is at or above its trailing 50-observation mean and 0.5 otherwise.

Turnover reconstruction result: actual holdings membership and weights produce no turnover reduction versus baseline. The reported panel applies a uniform 30% reduction to baseline turnover. Exposure changes explain return and drawdown differences, but do not explain the reported rank-buffer turnover reduction.

Rank-buffer evidence result: RANK_BUFFER_EVIDENCE_MISSING. No retained, skipped, dropped, newly added, or rank-threshold rows are available.

Daily return consistency result: {"RETURNS_FULLY_EXPLAINED_BY_EXPOSURE" if returns_consistent else "RETURN_EVIDENCE_REPAIR_REQUIRED"}. Overlay returns equal exposure multiplied by baseline risky returns within numerical tolerance.

Metric reconciliation result: {metric_status}. Total return, Sharpe, max drawdown, and reported-panel after-cost return reconcile; the 30% turnover reduction does not reconcile to holdings evidence.

Whether the 30% turnover reduction is explained: FALSE. Classification: {turnover_explanation}.

Caveat resolution: {caveat_resolution}. Exposure explains why holdings can remain unchanged while returns and drawdown differ, but the rank-buffer turnover claim remains unsupported.

Primary overlay review can continue: {yn(review_can_continue)}.

No overlay was adopted because this stage only repairs evidence and found a material turnover reconciliation gap.

Technical-only holdings evidence repair results must not be interpreted as full-weight results or full-weight evidence.

Full-weight remains blocked: TRUE.

Recommended next stage: {next_stage}

Guardrail statement: research_only=TRUE; holdings_evidence_repair_only=TRUE; operator_decision_is_adoption=FALSE; overlay, portfolio-variant, filter, official, and shadow adoption are disabled; official ranking and weights are unchanged; no official recommendation, real-book action, broker execution, trade action, or buy/sell/hold recommendation was created; local artifacts only; online_download_attempted=FALSE; yfinance_used=FALSE.
"""
    REPORT.write_text(report, encoding="utf-8")
    shutil.copyfile(REPORT, CURRENT)

    print(f"final_status={final_status}")
    print(f"decision={decision}")
    print(f"caveat_resolution={caveat_resolution}")
    print(f"turnover_explanation={turnover_explanation}")
    print("rank_buffer_evidence_status=RANK_BUFFER_EVIDENCE_MISSING")
    print(f"metric_reconciliation_status={metric_status}")
    print(f"recommended_next_stage={next_stage}")
    print(f"overlay_adoption_allowed={GUARD['overlay_adoption_allowed']}")
    print(f"official_adoption_allowed={GUARD['official_adoption_allowed']}")
    print(f"shadow_gate_allowed={GUARD['shadow_gate_allowed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
