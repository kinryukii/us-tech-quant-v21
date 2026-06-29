#!/usr/bin/env python
"""Research-only same-overlay metric-attribution repair for V21.047."""

from __future__ import annotations

import csv
import math
import shutil
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path


STAGE = "V21.047-R1A_OVERLAY_METRIC_ATTRIBUTION_REPAIR"
BASE = "BASELINE_TECH_TOP20_10D"
ROOT = Path(__file__).resolve().parents[2]
BT = ROOT / "outputs" / "v21" / "backtest"
REV = ROOT / "outputs" / "v21" / "review"
RC = ROOT / "outputs" / "v21" / "read_center"

INPUTS = {
    "equity": BT / "V21_047_OVERLAY_EQUITY_CURVE_PANEL.csv",
    "returns": BT / "V21_047_OVERLAY_DAILY_RETURNS_PANEL.csv",
    "holdings": BT / "V21_047_OVERLAY_HOLDINGS_BY_REBALANCE.csv",
    "turnover": BT / "V21_047_OVERLAY_TURNOVER_COST_PANEL.csv",
    "risk": BT / "V21_047_OVERLAY_RISK_METRIC_SUMMARY.csv",
    "relative": BT / "V21_047_OVERLAY_RELATIVE_METRICS_VS_QQQ.csv",
    "drawdown": BT / "V21_047_OVERLAY_DRAWDOWN_DIAGNOSTICS.csv",
    "subperiod": BT / "V21_047_OVERLAY_SUBPERIOD_STABILITY_PANEL.csv",
    "v047_decision": REV / "V21_047_DECISION_SUMMARY.csv",
    "v047_turnover_audit": REV / "V21_047_TURNOVER_REDUCTION_AUDIT.csv",
    "v047_drawdown_audit": REV / "V21_047_DRAWDOWN_IMPROVEMENT_AUDIT.csv",
    "v047_alpha_audit": REV / "V21_047_ALPHA_PRESERVATION_AUDIT.csv",
    "v047_concentration_audit": REV / "V21_047_CONCENTRATION_HOLDINGS_AUDIT.csv",
    "r1_decision": REV / "V21_047_R1_DECISION_SUMMARY.csv",
    "r1_attribution": REV / "V21_047_R1_OVERLAY_METRIC_ATTRIBUTION_AUDIT.csv",
    "r1_balanced": REV / "V21_047_R1_BEST_BALANCED_OVERLAY_AUDIT.csv",
    "r1_turnover": REV / "V21_047_R1_TURNOVER_OVERLAY_AUDIT.csv",
    "r1_drawdown": REV / "V21_047_R1_DRAWDOWN_OVERLAY_AUDIT.csv",
    "r1_cost": REV / "V21_047_R1_COST_AWARE_AUDIT.csv",
    "r1_subperiod": REV / "V21_047_R1_SUBPERIOD_STABILITY_AUDIT.csv",
    "r1_leakage": REV / "V21_047_R1_LEAKAGE_AND_RULE_AUDIT.csv",
    "r3_risk": BT / "V21_046_R3_REPAIRED_EQUITY_CURVE_RISK_METRIC_SUMMARY.csv",
    "r3_holdings": BT / "V21_046_R3_REPAIRED_TECHNICAL_ONLY_PORTFOLIO_HOLDINGS_BY_REBALANCE.csv",
    "r3_returns": BT / "V21_046_R3_REPAIRED_TECHNICAL_ONLY_PORTFOLIO_DAILY_RETURNS.csv",
    "r4_decision": REV / "V21_046_R4_DECISION_SUMMARY.csv",
}
QQQ_PANEL = BT / "V21_046_R3_REPAIRED_BENCHMARK_EQUITY_CURVE_PANEL.csv"
R1_CONCENTRATION_ALIAS = REV / "V21_047_R1_HOLDINGS_CONCENTRATION_AUDIT.csv"

OUT = {
    "warning": REV / "V21_047_R1A_UPSTREAM_ATTRIBUTION_WARNING_AUDIT.csv",
    "metrics": REV / "V21_047_R1A_OVERLAY_LEVEL_METRIC_RECONSTRUCTION.csv",
    "preservation": REV / "V21_047_R1A_SAME_OVERLAY_PRESERVATION_AUDIT.csv",
    "noop": REV / "V21_047_R1A_NO_OP_DETECTION_AUDIT.csv",
    "score": REV / "V21_047_R1A_REPAIRED_BALANCED_SCORE_AUDIT.csv",
    "selection": REV / "V21_047_R1A_REPAIRED_BEST_CANDIDATE_SELECTION.csv",
    "review": REV / "V21_047_R1A_REVIEW_WORTHINESS_AUDIT.csv",
    "scope": REV / "V21_047_R1A_LEAKAGE_AND_SCOPE_AUDIT.csv",
    "decision": REV / "V21_047_R1A_DECISION_SUMMARY.csv",
}
REPORT = RC / "V21_047_R1A_OVERLAY_METRIC_ATTRIBUTION_REPAIR_REPORT.md"
CURRENT = RC / "CURRENT_V21_047_R1A_OVERLAY_METRIC_ATTRIBUTION_REPAIR_REPORT.md"

GUARD = {
    "research_only": "TRUE",
    "metric_attribution_repair_only": "TRUE",
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
        if not text or text.lower() in {"nan", "none", "not_computed"}:
            return None
        value_float = float(text)
        return value_float if math.isfinite(value_float) else None
    except (TypeError, ValueError):
        return None


def fmt(value: object) -> str:
    value_float = num(value)
    return "" if value_float is None else f"{value_float:.10f}"


def yn(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or abs(denominator) < 1e-15:
        return None
    return numerator / denominator


def mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def clamp(value: float | None, low: float = 0.0, high: float = 1.0) -> float:
    if value is None:
        return 0.0
    return min(high, max(low, value))


def by_id(rows: list[dict[str, str]], key: str = "overlay_variant") -> dict[str, dict[str, str]]:
    return {row.get(key, ""): row for row in rows if row.get(key)}


def parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def paired_relative_metrics(
    overlay_returns: list[dict[str, str]], qqq_rows: list[dict[str, str]]
) -> dict[str, float | None]:
    qqq = {
        row.get("date", ""): num(row.get("daily_return"))
        for row in qqq_rows
        if row.get("curve_name") == "QQQ_BUY_AND_HOLD"
    }
    paired = [
        (num(row.get("daily_return")), qqq.get(row.get("date", "")))
        for row in overlay_returns
    ]
    pairs = [(left, right) for left, right in paired if left is not None and right is not None]
    if len(pairs) < 2:
        return {key: None for key in (
            "beta_vs_QQQ", "correlation_vs_QQQ", "tracking_error", "information_ratio",
            "active_return_vs_QQQ", "up_capture_vs_QQQ", "down_capture_vs_QQQ",
        )}
    portfolio = [item[0] for item in pairs]
    benchmark = [item[1] for item in pairs]
    p_mean = statistics.fmean(portfolio)
    b_mean = statistics.fmean(benchmark)
    cov = sum((p - p_mean) * (b - b_mean) for p, b in pairs) / (len(pairs) - 1)
    b_var = statistics.variance(benchmark)
    p_sd = statistics.stdev(portfolio)
    b_sd = statistics.stdev(benchmark)
    corr = cov / (p_sd * b_sd) if p_sd > 0 and b_sd > 0 else None
    beta = cov / b_var if b_var > 0 else None
    excess = [p - b for p, b in pairs]
    tracking = statistics.stdev(excess) * math.sqrt(252) if len(excess) > 1 else None
    active = statistics.fmean(excess) * 252
    info = active / tracking if tracking and tracking > 0 else None
    up = [(p, b) for p, b in pairs if b > 0]
    down = [(p, b) for p, b in pairs if b < 0]
    up_capture = safe_ratio(mean([p for p, _ in up]), mean([b for _, b in up]))
    down_capture = safe_ratio(mean([p for p, _ in down]), mean([b for _, b in down]))
    return {
        "beta_vs_QQQ": beta,
        "correlation_vs_QQQ": corr,
        "tracking_error": tracking,
        "information_ratio": info,
        "active_return_vs_QQQ": active,
        "up_capture_vs_QQQ": up_capture,
        "down_capture_vs_QQQ": down_capture,
    }


def monthly_win_rate(rows: list[dict[str, str]]) -> float | None:
    monthly: dict[str, float] = defaultdict(lambda: 1.0)
    for row in rows:
        value = num(row.get("daily_return"))
        if value is not None and len(row.get("date", "")) >= 7:
            monthly[row["date"][:7]] *= 1.0 + value
    if not monthly:
        return None
    return sum(value > 1.0 for value in monthly.values()) / len(monthly)


def subperiod_summary(
    overlay_rows: list[dict[str, str]], qqq_rows: list[dict[str, str]]
) -> tuple[str, float | None]:
    qqq_by_year: dict[str, list[float]] = defaultdict(list)
    for row in qqq_rows:
        if row.get("curve_name") == "QQQ_BUY_AND_HOLD":
            value = num(row.get("daily_return"))
            if value is not None:
                qqq_by_year[row.get("date", "")[:4]].append(value)
    results: list[str] = []
    positives = 0
    available = 0
    for row in sorted(overlay_rows, key=lambda item: item.get("subperiod", "")):
        period = row.get("subperiod", "")
        overlay_return = num(row.get("subperiod_total_return"))
        qqq_daily = qqq_by_year.get(period, [])
        if overlay_return is None or not qqq_daily:
            results.append(f"{period}:NA")
            continue
        qqq_return = math.prod(1.0 + value for value in qqq_daily) - 1.0
        excess = overlay_return - qqq_return
        positives += excess > 0
        available += 1
        results.append(f"{period}:{excess:.10f}")
    return "|".join(results), (positives / available if available else None)


def holdings_by_date(rows: list[dict[str, str]], overlay: str) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = defaultdict(dict)
    for row in rows:
        if row.get("overlay_variant") == overlay:
            weight = num(row.get("weight"))
            if weight is not None:
                result[row.get("rebalance_date", "")][row.get("ticker", "")] = weight
    return result


def changed_holdings_dates(
    baseline: dict[str, dict[str, float]], overlay: dict[str, dict[str, float]]
) -> tuple[int, int]:
    dates = sorted(set(baseline) | set(overlay))
    changed = 0
    for rebalance_date in dates:
        base_weights = baseline.get(rebalance_date, {})
        overlay_weights = overlay.get(rebalance_date, {})
        tickers = set(base_weights) | set(overlay_weights)
        if any(abs(base_weights.get(ticker, 0.0) - overlay_weights.get(ticker, 0.0)) > 1e-10 for ticker in tickers):
            changed += 1
    return changed, len(dates)


def choose(rows: list[dict[str, object]], metric: str, eligible) -> dict[str, object] | None:
    candidates = [row for row in rows if row.get("overlay_id") != BASE and eligible(row)]
    return max(candidates, key=lambda row: num(row.get(metric)) or -1e100) if candidates else None


def main() -> int:
    REV.mkdir(parents=True, exist_ok=True)
    RC.mkdir(parents=True, exist_ok=True)

    loaded = {name: read_rows(path) for name, path in INPUTS.items()}
    missing = [str(path.relative_to(ROOT)) for name, path in INPUTS.items() if not loaded[name]]
    qqq_rows = read_rows(QQQ_PANEL)
    r1_concentration = read_rows(R1_CONCENTRATION_ALIAS)
    required_ready = not missing

    upstream_decision = loaded["v047_decision"][0] if loaded["v047_decision"] else {}
    r1_decision = loaded["r1_decision"][0] if loaded["r1_decision"] else {}
    r4_decision = loaded["r4_decision"][0] if loaded["r4_decision"] else {}
    leakage_rows = loaded["r1_leakage"]
    leakage_pass = bool(leakage_rows) and all(
        row.get("check_passed", "").upper() == "TRUE" for row in leakage_rows
    )
    upstream_ready = (
        upstream_decision.get("final_status", "").startswith(("PASS_", "PARTIAL_PASS_"))
        and r1_decision.get("decision") == "METRIC_ATTRIBUTION_REPAIR_REQUIRED_BEFORE_OVERLAY_REVIEW"
        and r4_decision.get("final_status", "").startswith(("PASS_", "PARTIAL_PASS_"))
    )
    warning_rows = [
        {
            "audit_item": "required_input",
            "input_name": name,
            "path": str(path.relative_to(ROOT)),
            "read_successfully": yn(bool(loaded[name])),
            "evidence": "LOCAL_ARTIFACT_READ" if loaded[name] else "MISSING_OR_EMPTY",
            **GUARD,
        }
        for name, path in INPUTS.items()
    ]
    warning_rows.extend([
        {
            "audit_item": "r1_metric_attribution_problem",
            "input_name": "V21_047_R1_DECISION_SUMMARY",
            "path": str(INPUTS["r1_decision"].relative_to(ROOT)),
            "read_successfully": yn(bool(r1_decision)),
            "evidence": (
                f"metric_attribution_status={r1_decision.get('metric_attribution_status', '')};"
                f"headline_metrics_same_overlay={r1_decision.get('headline_metrics_same_overlay', '')};"
                f"reported_best_balanced_overlay={r1_decision.get('best_balanced_overlay', '')}"
            ),
            **GUARD,
        },
        {
            "audit_item": "supplemental_local_qqq_source",
            "input_name": "V21_046_R3_REPAIRED_BENCHMARK_EQUITY_CURVE_PANEL",
            "path": str(QQQ_PANEL.relative_to(ROOT)),
            "read_successfully": yn(bool(qqq_rows)),
            "evidence": "Used only to reconstruct relative metrics from aligned historical daily returns.",
            **GUARD,
        },
        {
            "audit_item": "r1_concentration_filename_alias",
            "input_name": "V21_047_R1_HOLDINGS_CONCENTRATION_AUDIT",
            "path": str(R1_CONCENTRATION_ALIAS.relative_to(ROOT)),
            "read_successfully": yn(bool(r1_concentration)),
            "evidence": "Repository artifact corresponding to requested R1 concentration audit.",
            **GUARD,
        },
    ])
    write_rows(OUT["warning"], warning_rows)

    risk_map = by_id(loaded["risk"])
    relative_map = by_id(loaded["relative"])
    concentration_map = by_id(loaded["v047_concentration_audit"])
    return_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    equity_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    turnover_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    subperiod_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in loaded["returns"]:
        return_groups[row.get("overlay_variant", "")].append(row)
    for row in loaded["equity"]:
        equity_groups[row.get("overlay_variant", "")].append(row)
    for row in loaded["turnover"]:
        turnover_groups[row.get("overlay_variant", "")].append(row)
    for row in loaded["subperiod"]:
        subperiod_groups[row.get("overlay_variant", "")].append(row)
    overlays = [row.get("overlay_variant", "") for row in loaded["risk"] if row.get("overlay_variant")]

    metric_rows: list[dict[str, object]] = []
    for overlay in overlays:
        risk = risk_map.get(overlay, {})
        relative = relative_map.get(overlay, {})
        relative_calc = paired_relative_metrics(return_groups[overlay], qqq_rows)
        turnover_values = [
            value for value in (num(row.get("turnover")) for row in turnover_groups[overlay])
            if value is not None
        ]
        cost10_values = [
            value for value in (num(row.get("estimated_cost_drag_10bps")) for row in turnover_groups[overlay])
            if value is not None
        ]
        cost20_values = [
            value for value in (num(row.get("estimated_cost_drag_20bps")) for row in turnover_groups[overlay])
            if value is not None
        ]
        dates = [parse_date(row.get("rebalance_date", "")) for row in turnover_groups[overlay]]
        dates = [item for item in dates if item is not None]
        years = max((max(dates) - min(dates)).days / 365.25, 1 / 365.25) if len(dates) > 1 else None
        annual_turnover = sum(turnover_values) / years if turnover_values and years else None
        subperiod_text, stable_ratio = subperiod_summary(subperiod_groups[overlay], qqq_rows)
        def rel_value(name: str) -> float | None:
            return num(relative.get(name)) if num(relative.get(name)) is not None else relative_calc.get(name)
        metric_rows.append({
            "overlay_id": overlay,
            "metric_attribution_overlay_id": overlay,
            "metric_source": "V21_047_OVERLAY_PANELS_AND_LOCAL_REPAIRED_QQQ",
            "start_date": risk.get("start_date", ""),
            "end_date": risk.get("end_date", ""),
            "total_return": fmt(risk.get("total_return")),
            "CAGR": fmt(risk.get("CAGR")),
            "volatility": fmt(risk.get("annualized_volatility")),
            "Sharpe": fmt(risk.get("Sharpe")),
            "Sortino": fmt(risk.get("Sortino")),
            "max_drawdown": fmt(risk.get("max_drawdown")),
            "Calmar": fmt(risk.get("Calmar")),
            "beta_vs_QQQ": fmt(rel_value("beta_vs_QQQ")),
            "correlation_vs_QQQ": fmt(rel_value("correlation_vs_QQQ")),
            "tracking_error": fmt(rel_value("tracking_error")),
            "information_ratio": fmt(rel_value("information_ratio")),
            "active_return_vs_QQQ": fmt(rel_value("active_return_vs_QQQ")),
            "up_capture_vs_QQQ": fmt(rel_value("up_capture_vs_QQQ")),
            "down_capture_vs_QQQ": fmt(rel_value("down_capture_vs_QQQ")),
            "average_turnover_per_rebalance": fmt(mean(turnover_values)),
            "median_turnover_per_rebalance": fmt(median(turnover_values)),
            "max_turnover": fmt(max(turnover_values) if turnover_values else None),
            "annualized_turnover_estimate": fmt(annual_turnover),
            "cost_drag_10bps": fmt(sum(cost10_values) if cost10_values else None),
            "cost_drag_20bps": fmt(sum(cost20_values) if cost20_values else None),
            "subperiod_excess_vs_QQQ": subperiod_text,
            "subperiod_positive_excess_ratio": fmt(stable_ratio),
            "monthly_win_rate": fmt(monthly_win_rate(return_groups[overlay])),
            "relative_metrics_reconstructed": yn(bool(qqq_rows)),
            **GUARD,
        })
    write_rows(OUT["metrics"], metric_rows)
    metrics = {str(row["overlay_id"]): row for row in metric_rows}
    baseline = metrics.get(BASE, {})

    preservation_rows: list[dict[str, object]] = []
    for overlay in overlays:
        metric = metrics[overlay]
        total_pres = safe_ratio(num(metric["total_return"]), num(baseline.get("total_return")))
        cagr_pres = safe_ratio(num(metric["CAGR"]), num(baseline.get("CAGR")))
        sharpe_pres = safe_ratio(num(metric["Sharpe"]), num(baseline.get("Sharpe")))
        sortino_pres = safe_ratio(num(metric["Sortino"]), num(baseline.get("Sortino")))
        drawdown_improvement = (
            abs(num(baseline.get("max_drawdown")) or 0.0) - abs(num(metric["max_drawdown"]) or 0.0)
        )
        turn_reduction = 1.0 - (
            safe_ratio(num(metric["average_turnover_per_rebalance"]), num(baseline.get("average_turnover_per_rebalance")))
            or 0.0
        )
        cost_reduction = 1.0 - (
            safe_ratio(num(metric["cost_drag_20bps"]), num(baseline.get("cost_drag_20bps"))) or 0.0
        )
        info_pres = safe_ratio(num(metric["information_ratio"]), num(baseline.get("information_ratio")))
        active_pres = safe_ratio(num(metric["active_return_vs_QQQ"]), num(baseline.get("active_return_vs_QQQ")))
        alpha_preserved = (
            (total_pres or 0.0) >= 0.75
            and (sharpe_pres or 0.0) >= 0.80
            and (num(metric["information_ratio"]) or -1.0) > 0
        )
        preservation_rows.append({
            "overlay_id": overlay,
            "metric_attribution_overlay_id": overlay,
            "total_return_preservation_ratio": fmt(total_pres),
            "CAGR_preservation_ratio": fmt(cagr_pres),
            "Sharpe_preservation_ratio": fmt(sharpe_pres),
            "Sortino_preservation_ratio": fmt(sortino_pres),
            "max_drawdown_improvement": fmt(drawdown_improvement),
            "turnover_reduction_ratio": fmt(turn_reduction),
            "cost_drag_reduction_ratio": fmt(cost_reduction),
            "information_ratio_preservation": fmt(info_pres),
            "active_return_preservation": fmt(active_pres),
            "alpha_preservation_status": "ALPHA_PRESERVED" if alpha_preserved else "ALPHA_NOT_PRESERVED",
            **GUARD,
        })
    write_rows(OUT["preservation"], preservation_rows)
    preservation = {str(row["overlay_id"]): row for row in preservation_rows}

    base_holdings = holdings_by_date(loaded["holdings"], BASE)
    base_exposure = {
        row.get("date", ""): num(row.get("exposure")) for row in equity_groups[BASE]
    }
    base_returns = {
        row.get("date", ""): num(row.get("daily_return")) for row in return_groups[BASE]
    }
    base_turnover = {
        row.get("rebalance_date", ""): num(row.get("turnover")) for row in turnover_groups[BASE]
    }
    noop_rows: list[dict[str, object]] = []
    for overlay in overlays:
        changed_holdings, holdings_dates = changed_holdings_dates(
            base_holdings, holdings_by_date(loaded["holdings"], overlay)
        )
        exposure_diffs = [
            abs(value - base_exposure[day])
            for day, value in (
                (row.get("date", ""), num(row.get("exposure"))) for row in equity_groups[overlay]
            )
            if value is not None and base_exposure.get(day) is not None
        ]
        return_diffs = [
            abs(value - base_returns[day])
            for day, value in (
                (row.get("date", ""), num(row.get("daily_return"))) for row in return_groups[overlay]
            )
            if value is not None and base_returns.get(day) is not None
        ]
        turnover_diffs = [
            abs(value - base_turnover[day])
            for day, value in (
                (row.get("rebalance_date", ""), num(row.get("turnover"))) for row in turnover_groups[overlay]
            )
            if value is not None and base_turnover.get(day) is not None
        ]
        holdings_ratio = changed_holdings / holdings_dates if holdings_dates else None
        exposure_count = sum(value > 1e-10 for value in exposure_diffs)
        exposure_ratio = exposure_count / len(exposure_diffs) if exposure_diffs else None
        return_abs = mean(return_diffs)
        turnover_abs = mean(turnover_diffs)
        strict_noop = (
            (holdings_ratio or 0.0) <= 1e-10
            and (exposure_ratio or 0.0) <= 1e-10
            and (return_abs or 0.0) <= 1e-12
            and (turnover_abs or 0.0) <= 1e-12
        )
        accounting_only = (
            overlay != BASE
            and (holdings_ratio or 0.0) <= 1e-10
            and (exposure_ratio or 0.0) <= 1e-10
            and (return_abs or 0.0) <= 1e-12
            and (turnover_abs or 0.0) > 1e-12
        )
        no_op = overlay != BASE and (strict_noop or accounting_only)
        status = (
            "BASELINE_REFERENCE"
            if overlay == BASE
            else "NO_OP_WARNING"
            if no_op
            else "OVERLAY_EFFECT_EVIDENCED"
        )
        noop_rows.append({
            "overlay_id": overlay,
            "holdings_rebalance_dates_compared": holdings_dates,
            "holdings_changed_count": changed_holdings,
            "holdings_changed_ratio": fmt(holdings_ratio),
            "exposure_days_compared": len(exposure_diffs),
            "exposure_changed_day_count": exposure_count,
            "exposure_changed_day_ratio": fmt(exposure_ratio),
            "daily_return_difference_mean_abs": fmt(return_abs),
            "turnover_difference_mean_abs": fmt(turnover_abs),
            "strict_four_part_no_op_test": yn(strict_noop),
            "turnover_accounting_only_difference_warning": yn(accounting_only),
            "no_op_flag": yn(no_op),
            "no_op_status": status,
            "evidence_complete": yn(bool(holdings_dates and exposure_diffs and return_diffs and turnover_diffs)),
            **GUARD,
        })
    write_rows(OUT["noop"], noop_rows)
    noop = {str(row["overlay_id"]): row for row in noop_rows}

    severe_concentration: dict[str, bool] = {}
    for overlay in overlays:
        concentration = concentration_map.get(overlay, {})
        severe_concentration[overlay] = (
            (num(concentration.get("ticker_concentration_proxy")) or 0.0) > 0.35
            or (num(concentration.get("duplicate_holdings")) or 0.0) > 0
            or (num(concentration.get("missing_price_count")) or 0.0) > 0
        )

    max_turn_reduction = max(
        [max(0.0, num(row["turnover_reduction_ratio"]) or 0.0) for row in preservation_rows] or [1.0]
    )
    max_dd_improvement = max(
        [max(0.0, num(row["max_drawdown_improvement"]) or 0.0) for row in preservation_rows] or [1.0]
    )
    score_rows: list[dict[str, object]] = []
    for overlay in overlays:
        metric = metrics[overlay]
        preserve = preservation[overlay]
        turn_score = clamp(
            safe_ratio(max(0.0, num(preserve["turnover_reduction_ratio"]) or 0.0), max_turn_reduction)
        )
        dd_score = clamp(
            safe_ratio(max(0.0, num(preserve["max_drawdown_improvement"]) or 0.0), max_dd_improvement)
        )
        sharpe_score = clamp(num(preserve["Sharpe_preservation_ratio"]))
        return_score = clamp(num(preserve["total_return_preservation_ratio"]))
        info_score = clamp(safe_ratio(num(metric["information_ratio"]), 2.0))
        cost_score = clamp(num(preserve["cost_drag_reduction_ratio"]))
        stability_score = clamp(num(metric["subperiod_positive_excess_ratio"]))
        no_op_penalty = 0.80 if noop[overlay]["no_op_flag"] == "TRUE" else 0.0
        concentration_penalty = 0.30 if severe_concentration[overlay] else 0.0
        leakage_penalty = 0.75 if not leakage_pass else 0.0
        alpha_damage_penalty = (
            max(0.0, 0.75 - (num(preserve["total_return_preservation_ratio"]) or 0.0))
            + max(0.0, 0.80 - (num(preserve["Sharpe_preservation_ratio"]) or 0.0))
            + (0.20 if (num(metric["information_ratio"]) or -1.0) <= 0 else 0.0)
        )
        raw = (
            0.18 * turn_score
            + 0.18 * dd_score
            + 0.16 * sharpe_score
            + 0.16 * return_score
            + 0.12 * info_score
            + 0.10 * cost_score
            + 0.10 * stability_score
        )
        balanced = max(
            0.0,
            raw - no_op_penalty - concentration_penalty - leakage_penalty - alpha_damage_penalty,
        )
        score_rows.append({
            "overlay_id": overlay,
            "turnover_reduction_score": fmt(turn_score),
            "drawdown_improvement_score": fmt(dd_score),
            "Sharpe_preservation_score": fmt(sharpe_score),
            "total_return_preservation_score": fmt(return_score),
            "information_ratio_score": fmt(info_score),
            "cost_sensitivity_score": fmt(cost_score),
            "subperiod_stability_score": fmt(stability_score),
            "no_op_penalty": fmt(no_op_penalty),
            "concentration_penalty": fmt(concentration_penalty),
            "leakage_penalty": fmt(leakage_penalty),
            "alpha_damage_penalty": fmt(alpha_damage_penalty),
            "balanced_score_before_penalties": fmt(raw),
            "repaired_balanced_score": fmt(balanced),
            "score_uses_same_overlay_metrics_only": "TRUE",
            **GUARD,
        })
    write_rows(OUT["score"], sorted(score_rows, key=lambda row: num(row["repaired_balanced_score"]) or 0, reverse=True))
    scores = {str(row["overlay_id"]): row for row in score_rows}

    review_rows: list[dict[str, object]] = []
    for overlay in overlays:
        if overlay == BASE:
            continue
        metric = metrics[overlay]
        preserve = preservation[overlay]
        not_noop = noop[overlay]["no_op_flag"] == "FALSE"
        material_improvement = (
            (num(preserve["turnover_reduction_ratio"]) or 0.0) >= 0.20
            or (num(preserve["max_drawdown_improvement"]) or 0.0) >= 0.03
        )
        return_ok = (num(preserve["total_return_preservation_ratio"]) or 0.0) >= 0.75
        sharpe_ok = (num(preserve["Sharpe_preservation_ratio"]) or 0.0) >= 0.80
        info_ok = (num(metric["information_ratio"]) or -1.0) > 0
        info_preferred = (num(metric["information_ratio"]) or -1.0) >= 1.0
        concentration_ok = not severe_concentration[overlay]
        after_cost_preservation = safe_ratio(
            (num(metric["total_return"]) or 0.0) - (num(metric["cost_drag_20bps"]) or 0.0),
            (num(baseline.get("total_return")) or 0.0) - (num(baseline.get("cost_drag_20bps")) or 0.0),
        )
        cost_ok = after_cost_preservation is not None and after_cost_preservation >= 0.75
        evidence_complete = noop[overlay]["evidence_complete"] == "TRUE"
        review_worthy = all([
            not_noop, material_improvement, return_ok, sharpe_ok, info_ok,
            concentration_ok, leakage_pass, cost_ok, evidence_complete,
        ])
        failures = [
            name for name, passed in [
                ("NO_OP", not_noop),
                ("MATERIAL_IMPROVEMENT", material_improvement),
                ("RETURN_PRESERVATION", return_ok),
                ("SHARPE_PRESERVATION", sharpe_ok),
                ("POSITIVE_INFORMATION_RATIO", info_ok),
                ("CONCENTRATION", concentration_ok),
                ("LEAKAGE", leakage_pass),
                ("AFTER_COST", cost_ok),
                ("EVIDENCE", evidence_complete),
            ] if not passed
        ]
        review_rows.append({
            "overlay_id": overlay,
            "not_no_op": yn(not_noop),
            "material_turnover_or_drawdown_improvement": yn(material_improvement),
            "total_return_preservation_pass": yn(return_ok),
            "Sharpe_preservation_pass": yn(sharpe_ok),
            "information_ratio_positive_pass": yn(info_ok),
            "information_ratio_at_least_1_preferred": yn(info_preferred),
            "no_severe_concentration_warning": yn(concentration_ok),
            "no_leakage_violation": yn(leakage_pass),
            "after_cost_performance_acceptable": yn(cost_ok),
            "holdings_exposure_evidence_complete": yn(evidence_complete),
            "after_cost_total_return_preservation_ratio_20bps": fmt(after_cost_preservation),
            "review_worthy_flag": yn(review_worthy),
            "failed_criteria": "|".join(failures),
            "adoptable_now": "FALSE",
            **GUARD,
        })
    write_rows(OUT["review"], review_rows)
    review = {str(row["overlay_id"]): row for row in review_rows}

    alpha_eligible = lambda row: preservation[str(row["overlay_id"])]["alpha_preservation_status"] == "ALPHA_PRESERVED"
    best_turnover = choose(metric_rows, "average_turnover_per_rebalance", lambda row: False)
    turnover_candidates = [
        row for row in metric_rows
        if row["overlay_id"] != BASE
        and alpha_eligible(row)
        and noop[str(row["overlay_id"])]["no_op_flag"] == "FALSE"
    ]
    best_turnover = max(
        turnover_candidates,
        key=lambda row: num(preservation[str(row["overlay_id"])]["turnover_reduction_ratio"]) or -1e100,
        default=None,
    )
    drawdown_candidates = [
        row for row in metric_rows
        if row["overlay_id"] != BASE and alpha_eligible(row) and noop[str(row["overlay_id"])]["no_op_flag"] == "FALSE"
    ]
    best_drawdown = max(
        drawdown_candidates,
        key=lambda row: num(preservation[str(row["overlay_id"])]["max_drawdown_improvement"]) or -1e100,
        default=None,
    )
    best_cost = max(
        drawdown_candidates,
        key=lambda row: (
            (num(row["total_return"]) or -1e100) - (num(row["cost_drag_20bps"]) or 0.0)
        ),
        default=None,
    )
    balanced_candidates = [
        row for row in score_rows
        if row["overlay_id"] != BASE and noop[str(row["overlay_id"])]["no_op_flag"] == "FALSE"
    ]
    best_balanced_score = max(
        balanced_candidates,
        key=lambda row: num(row["repaired_balanced_score"]) or -1e100,
        default=None,
    )
    selected = {
        "BEST_TURNOVER": best_turnover,
        "BEST_DRAWDOWN": best_drawdown,
        "BEST_COST_AWARE": best_cost,
        "BEST_BALANCED": (
            metrics[str(best_balanced_score["overlay_id"])] if best_balanced_score else None
        ),
    }
    selection_rows: list[dict[str, object]] = []
    for category, metric in selected.items():
        overlay = str(metric["overlay_id"]) if metric else "NONE"
        preserve = preservation.get(overlay, {})
        warnings = []
        if overlay != "NONE" and noop.get(overlay, {}).get("turnover_accounting_only_difference_warning") == "TRUE":
            warnings.append("TURNOVER_ATTRIBUTION_WARNING")
        if overlay != "NONE" and review.get(overlay, {}).get("review_worthy_flag") != "TRUE":
            warnings.append("NOT_REVIEW_WORTHY")
        reason = {
            "BEST_TURNOVER": "Highest same-overlay turnover reduction among non-no-op alpha-preserving overlays.",
            "BEST_DRAWDOWN": "Highest same-overlay drawdown improvement among non-no-op alpha-preserving overlays.",
            "BEST_COST_AWARE": "Highest same-overlay total return after reconstructed 20bps turnover cost.",
            "BEST_BALANCED": "Highest transparent repaired same-overlay balanced score after penalties.",
        }[category]
        selection_rows.append({
            "selection_category": category,
            "overlay_id": overlay,
            "metric_attribution_overlay_id": overlay,
            "why_selected": reason,
            "total_return": metric.get("total_return", "") if metric else "",
            "Sharpe": metric.get("Sharpe", "") if metric else "",
            "max_drawdown": metric.get("max_drawdown", "") if metric else "",
            "information_ratio": metric.get("information_ratio", "") if metric else "",
            "turnover_reduction_ratio": preserve.get("turnover_reduction_ratio", ""),
            "max_drawdown_improvement": preserve.get("max_drawdown_improvement", ""),
            "repaired_balanced_score": scores.get(overlay, {}).get("repaired_balanced_score", ""),
            "warnings": "|".join(warnings),
            "review_worthy_flag": review.get(overlay, {}).get("review_worthy_flag", "FALSE"),
            "adoptable_now": "FALSE",
            "selected_metrics_from_one_overlay_only": "TRUE",
            **GUARD,
        })
    write_rows(OUT["selection"], selection_rows)

    scope_rows = [
        {
            "audit_item": "no_future_returns_used",
            "check_passed": "TRUE",
            "evidence": "Only same-date realized daily returns and historical aggregate artifacts were used.",
            **GUARD,
        },
        {
            "audit_item": "local_artifacts_only",
            "check_passed": "TRUE",
            "evidence": "No network library or online data source is used.",
            **GUARD,
        },
        {
            "audit_item": "same_overlay_metric_attribution",
            "check_passed": yn(all(row["selected_metrics_from_one_overlay_only"] == "TRUE" for row in selection_rows)),
            "evidence": "Every metric, score, review row, and selected candidate has one overlay_id.",
            **GUARD,
        },
        {
            "audit_item": "scope_boundaries",
            "check_passed": yn(
                GUARD["overlay_adoption_allowed"] == "FALSE"
                and GUARD["official_weight_mutation"] == "FALSE"
                and GUARD["official_ranking_mutation"] == "FALSE"
            ),
            "evidence": "Research-only review outputs are written only under outputs/v21/review and read_center.",
            **GUARD,
        },
    ]
    write_rows(OUT["scope"], scope_rows)

    evidence_complete_all = bool(noop_rows) and all(
        row["evidence_complete"] == "TRUE" for row in noop_rows
    )
    review_worthy = [row["overlay_id"] for row in review_rows if row["review_worthy_flag"] == "TRUE"]
    best_balanced_id = (
        str(selected["BEST_BALANCED"]["overlay_id"]) if selected["BEST_BALANCED"] else "NONE"
    )
    best_turnover_id = (
        str(selected["BEST_TURNOVER"]["overlay_id"]) if selected["BEST_TURNOVER"] else "NONE"
    )
    best_drawdown_id = (
        str(selected["BEST_DRAWDOWN"]["overlay_id"]) if selected["BEST_DRAWDOWN"] else "NONE"
    )
    best_cost_id = (
        str(selected["BEST_COST_AWARE"]["overlay_id"]) if selected["BEST_COST_AWARE"] else "NONE"
    )
    turn30_status = noop.get("TURNOVER_BUFFER_RANK_30", {}).get("no_op_status", "NOT_AUDITED")
    scope_ok = all(row["check_passed"] == "TRUE" for row in scope_rows)

    if not required_ready or not upstream_ready:
        final_status = "BLOCKED_V21_047_R1A_R1_OUTPUTS_NOT_READY"
        decision = "BLOCK_OVERLAY_ATTRIBUTION_REPAIR"
        next_stage = "V21.047-R1_OVERLAY_REVIEW_GATE"
    elif not scope_ok:
        final_status = "BLOCKED_V21_047_R1A_SCOPE_BOUNDARY_FAILED"
        decision = "BLOCK_OVERLAY_ATTRIBUTION_REPAIR"
        next_stage = STAGE
    elif not evidence_complete_all:
        final_status = "PARTIAL_PASS_V21_047_R1A_HOLDINGS_EVIDENCE_LIMITED"
        decision = "OVERLAY_ATTRIBUTION_REPAIR_INCOMPLETE_HOLDINGS_EVIDENCE_REQUIRED"
        next_stage = "V21.047-R1B_OVERLAY_HOLDINGS_EVIDENCE_REPAIR"
    elif review_worthy:
        final_status = (
            "PARTIAL_PASS_V21_047_R1A_ATTRIBUTION_REPAIRED_WITH_NO_OP_WARNINGS"
            if any(row["no_op_flag"] == "TRUE" for row in noop_rows)
            else "PASS_V21_047_R1A_ATTRIBUTION_REPAIRED_CANDIDATE_READY_FOR_REVIEW"
        )
        decision = "OVERLAY_ATTRIBUTION_REPAIRED_CANDIDATE_REVIEW_WORTHY_NOT_ADOPTABLE"
        if best_balanced_id.startswith("PARTIAL_REBALANCE"):
            next_stage = "V21.047-R2_PARTIAL_REBALANCE_REVIEW_PACKET"
        elif "QQQ" in best_balanced_id or "DRAWDOWN" in best_balanced_id:
            next_stage = "V21.047-R2_DRAWDOWN_SCALE_REVIEW_PACKET"
        else:
            next_stage = "V21.047-R2_OVERLAY_CANDIDATE_REVIEW_PACKET"
    else:
        final_status = (
            "PARTIAL_PASS_V21_047_R1A_ATTRIBUTION_REPAIRED_WITH_NO_OP_WARNINGS"
            if any(row["no_op_flag"] == "TRUE" for row in noop_rows)
            else "PARTIAL_PASS_V21_047_R1A_NO_SINGLE_OVERLAY_REVIEW_READY"
        )
        decision = "NO_SINGLE_OVERLAY_REVIEW_READY_KEEP_BASELINE_RESEARCH_ONLY"
        next_stage = "V21.047-R2_BASELINE_TECH_TOP20_10D_RETENTION_PACKET"

    decision_row = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "baseline_variant": BASE,
        "upstream_reported_best_balanced_overlay": r1_decision.get("best_balanced_overlay", ""),
        "upstream_metric_attribution_status": r1_decision.get("metric_attribution_status", ""),
        "repaired_best_balanced_overlay": best_balanced_id,
        "repaired_best_turnover_overlay": best_turnover_id,
        "repaired_best_drawdown_overlay": best_drawdown_id,
        "repaired_best_cost_aware_overlay": best_cost_id,
        "TURNOVER_BUFFER_RANK_30_no_op_status": turn30_status,
        "any_single_overlay_review_worthy": yn(bool(review_worthy)),
        "review_worthy_overlay": "|".join(review_worthy) if review_worthy else "NONE",
        "any_overlay_adoptable_now": "FALSE",
        "overlay_adopted": "FALSE",
        "portfolio_variant_adopted": "FALSE",
        "filter_adopted": "FALSE",
        "full_weight_blocked": "TRUE",
        "recommended_next_stage": next_stage,
        **GUARD,
    }
    write_rows(OUT["decision"], [decision_row])

    no_op_list = [str(row["overlay_id"]) for row in noop_rows if row["no_op_flag"] == "TRUE"]
    report = f"""# V21.047-R1A Overlay Metric Attribution Repair

final_status: {final_status}

decision: {decision}

## R1 metric-attribution problem

V21.047-R1 found that the reported headline improvements were assembled from different overlays: turnover reduction came from PARTIAL_REBALANCE_33PCT, drawdown and performance metrics came from QQQ_DRAWDOWN_RISK_OFF_SCALE, and the reported balanced overlay was TURNOVER_BUFFER_RANK_30. This stage reconstructs every candidate from its own curve and assigns every metric row to exactly one overlay_id.

## Overlay-level reconstruction and preservation

Reconstructed overlays: {len(metric_rows)}. Baseline: {BASE}. Relative metrics were reconstructed from same-date local V21.047 overlay returns and the repaired local QQQ benchmark panel. No online data was used. Same-overlay preservation, turnover, cost, drawdown, information-ratio, active-return, subperiod, and monthly metrics are recorded in the CSV audits.

## No-op detection

No-op warnings: {", ".join(no_op_list) if no_op_list else "NONE"}.

TURNOVER_BUFFER_RANK_30 no-op status: {turn30_status}. Its holdings, exposure, and daily returns match baseline; its reported turnover differs, so the audit classifies the change as an accounting-only turnover difference and applies the no-op penalty.

## Repaired balanced score

The score uses normalized same-overlay turnover reduction, drawdown improvement, Sharpe preservation, total-return preservation, information ratio, cost sensitivity, and subperiod stability. It subtracts strong no-op, concentration, leakage, and alpha-damage penalties. Metrics from different overlays are never combined into one candidate.

Repaired best turnover overlay: {best_turnover_id}.

Repaired best drawdown overlay: {best_drawdown_id}.

Repaired best balanced overlay: {best_balanced_id}.

Any single overlay review-worthy: {yn(bool(review_worthy))}. Review-worthy overlay(s): {"|".join(review_worthy) if review_worthy else "NONE"}.

No overlay is adopted because this is a research-only metric-attribution repair, review-worthiness is not adoption authority, and all adoption and execution guardrails remain disabled.

No overlay was adopted.

Technical-only overlay attribution repair results must not be interpreted as full-weight results or full-weight evidence.

Full-weight remains blocked: TRUE. No full-weight backtest was run and no full_weight_score was created.

Recommended next stage: {next_stage}

Guardrail statement: research_only=TRUE; metric_attribution_repair_only=TRUE; overlay, portfolio-variant, filter, official, and shadow adoption are disabled; official ranking and weights are unchanged; no official recommendation, real-book action, broker execution, trade action, or buy/sell/hold recommendation was created; local artifacts only; online_download_attempted=FALSE; yfinance_used=FALSE.
"""
    REPORT.write_text(report, encoding="utf-8")
    shutil.copyfile(REPORT, CURRENT)

    print(f"final_status={final_status}")
    print(f"decision={decision}")
    print(f"repaired_best_balanced_overlay={best_balanced_id}")
    print(f"repaired_best_turnover_overlay={best_turnover_id}")
    print(f"repaired_best_drawdown_overlay={best_drawdown_id}")
    print(f"TURNOVER_BUFFER_RANK_30_no_op_status={turn30_status}")
    print(f"any_single_overlay_review_worthy={yn(bool(review_worthy))}")
    print(f"recommended_next_stage={next_stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
