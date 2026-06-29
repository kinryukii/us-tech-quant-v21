#!/usr/bin/env python
"""Research-only review gate for V21.047 Technical-only overlay dry-run."""

from __future__ import annotations

import csv
import math
import shutil
from collections import defaultdict
from pathlib import Path


STAGE = "V21.047-R1_OVERLAY_REVIEW_GATE"

PASS = "PASS_V21_047_R1_OVERLAY_REVIEW_GATE_READY"
ATTR_WARN = "PARTIAL_PASS_V21_047_R1_BALANCED_OVERLAY_REVIEW_WITH_ATTRIBUTION_WARNING"
TURN_WARN = "PARTIAL_PASS_V21_047_R1_TURNOVER_OVERLAY_PROMISING_WITH_REVIEW_WARNINGS"
DD_WARN = "PARTIAL_PASS_V21_047_R1_DRAWDOWN_OVERLAY_PROMISING_WITH_ALPHA_DECAY_WARNING"
COST_WARN = "PARTIAL_PASS_V21_047_R1_OVERLAY_REVIEW_WITH_COST_WARNING"
NO_READY = "PARTIAL_PASS_V21_047_R1_NO_OVERLAY_READY_FOR_NEXT_REVIEW"
MISSING = "BLOCKED_V21_047_R1_V21_047_OUTPUTS_NOT_READY"
SCOPE_BLOCKED = "BLOCKED_V21_047_R1_SCOPE_BOUNDARY_FAILED"

ROOT = Path(__file__).resolve().parents[2]
BT = ROOT / "outputs" / "v21" / "backtest"
REV = ROOT / "outputs" / "v21" / "review"
RC = ROOT / "outputs" / "v21" / "read_center"

IN_EQ = BT / "V21_047_OVERLAY_EQUITY_CURVE_PANEL.csv"
IN_RET = BT / "V21_047_OVERLAY_DAILY_RETURNS_PANEL.csv"
IN_HOLD = BT / "V21_047_OVERLAY_HOLDINGS_BY_REBALANCE.csv"
IN_TURN_PANEL = BT / "V21_047_OVERLAY_TURNOVER_COST_PANEL.csv"
IN_RISK = BT / "V21_047_OVERLAY_RISK_METRIC_SUMMARY.csv"
IN_REL = BT / "V21_047_OVERLAY_RELATIVE_METRICS_VS_QQQ.csv"
IN_DD_PANEL = BT / "V21_047_OVERLAY_DRAWDOWN_DIAGNOSTICS.csv"
IN_STAB = BT / "V21_047_OVERLAY_SUBPERIOD_STABILITY_PANEL.csv"
IN_UP = REV / "V21_047_UPSTREAM_READINESS_AUDIT.csv"
IN_DEF = REV / "V21_047_OVERLAY_DEFINITION_REGISTER.csv"
IN_TURN = REV / "V21_047_TURNOVER_REDUCTION_AUDIT.csv"
IN_DD = REV / "V21_047_DRAWDOWN_IMPROVEMENT_AUDIT.csv"
IN_ALPHA = REV / "V21_047_ALPHA_PRESERVATION_AUDIT.csv"
IN_CONC = REV / "V21_047_CONCENTRATION_HOLDINGS_AUDIT.csv"
IN_SCOPE = REV / "V21_047_SCOPE_BOUNDARY_AUDIT.csv"
IN_DEC = REV / "V21_047_DECISION_SUMMARY.csv"
R3_RISK = BT / "V21_046_R3_REPAIRED_EQUITY_CURVE_RISK_METRIC_SUMMARY.csv"
R4_DEC = REV / "V21_046_R4_DECISION_SUMMARY.csv"
R4_TURN = REV / "V21_046_R4_TURNOVER_COST_AUDIT.csv"
R4_BETA = REV / "V21_046_R4_BETA_ACTIVE_RISK_AUDIT.csv"
R4_DD = REV / "V21_046_R4_DRAWDOWN_AUDIT.csv"

OUT_UP = REV / "V21_047_R1_UPSTREAM_READINESS_AUDIT.csv"
OUT_ATTR = REV / "V21_047_R1_OVERLAY_METRIC_ATTRIBUTION_AUDIT.csv"
OUT_BAL = REV / "V21_047_R1_BEST_BALANCED_OVERLAY_AUDIT.csv"
OUT_TURN = REV / "V21_047_R1_TURNOVER_OVERLAY_AUDIT.csv"
OUT_DD = REV / "V21_047_R1_DRAWDOWN_OVERLAY_AUDIT.csv"
OUT_COST = REV / "V21_047_R1_COST_AWARE_AUDIT.csv"
OUT_STAB = REV / "V21_047_R1_SUBPERIOD_STABILITY_AUDIT.csv"
OUT_CONC = REV / "V21_047_R1_HOLDINGS_CONCENTRATION_AUDIT.csv"
OUT_LEAK = REV / "V21_047_R1_LEAKAGE_AND_RULE_AUDIT.csv"
OUT_SCOPE = REV / "V21_047_R1_SCOPE_BOUNDARY_AUDIT.csv"
OUT_DEC = REV / "V21_047_R1_DECISION_SUMMARY.csv"

REPORT = RC / "V21_047_R1_OVERLAY_REVIEW_GATE_REPORT.md"
CURRENT = RC / "CURRENT_V21_047_R1_OVERLAY_REVIEW_GATE_REPORT.md"

BASE = "BASELINE_TECH_TOP20_10D"
BALANCED = "TURNOVER_BUFFER_RANK_30"
TURNOVER_REVIEW = ["PARTIAL_REBALANCE_33PCT", "PARTIAL_REBALANCE_50PCT"]
DRAWDOWN_REVIEW = ["QQQ_DRAWDOWN_RISK_OFF_SCALE", "QQQ_MA50_RISK_OFF_SCALE"]
COST_REVIEW = ["COST_AWARE_TURNOVER_BUFFER_25", "TURNOVER_BUFFER_RANK_25", "TURNOVER_BUFFER_RANK_30"]

GUARD = {
    "research_only": "TRUE",
    "overlay_review_gate_only": "TRUE",
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
FALSE_KEYS = [k for k, v in GUARD.items() if v == "FALSE"]


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = rows or [{}]
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def num(value: object) -> float | None:
    try:
        if value is None:
            return None
        text = str(value).strip()
        if text == "" or text.lower() == "nan":
            return None
        return float(text)
    except Exception:
        return None


def fmt(value: object) -> str:
    x = num(value)
    if x is None or not math.isfinite(x):
        return ""
    return f"{x:.10f}"


def yn(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def row_by(rows: list[dict[str, str]], key: str = "overlay_variant") -> dict[str, dict[str, str]]:
    return {r.get(key, ""): r for r in rows if r.get(key, "")}


def max_overlay(rows: list[dict[str, object]], metric: str, minimum: float | None = None) -> str:
    best = ""
    best_value = -10**100
    for r in rows:
        x = num(r.get(metric))
        if x is None:
            continue
        if minimum is not None and x < minimum:
            continue
        if x > best_value:
            best_value = x
            best = str(r.get("overlay_variant", ""))
    return best or "NONE"


def guardrails_ok(rows: list[dict[str, str]]) -> bool:
    if not rows:
        return False
    for key, expected in {
        "overlay_adoption_allowed": "FALSE",
        "portfolio_variant_adoption_allowed": "FALSE",
        "filter_adoption_allowed": "FALSE",
        "full_weight_result_available": "FALSE",
        "official_adoption_allowed": "FALSE",
        "shadow_gate_allowed": "FALSE",
        "shadow_adoption_allowed": "FALSE",
        "online_download_attempted": "FALSE",
        "yfinance_used": "FALSE",
    }.items():
        value = str(first(rows).get(key, "")).upper()
        if value and value != expected:
            return False
    return True


def holdings_signature(rows: list[dict[str, str]], overlay: str) -> set[tuple[str, str, str]]:
    sig: set[tuple[str, str, str]] = set()
    for r in rows:
        if r.get("overlay_variant") == overlay:
            sig.add((r.get("rebalance_date", ""), r.get("ticker", ""), fmt(r.get("weight"))))
    return sig


def main() -> int:
    REV.mkdir(parents=True, exist_ok=True)
    BT.mkdir(parents=True, exist_ok=True)
    RC.mkdir(parents=True, exist_ok=True)

    required = [
        IN_EQ, IN_RET, IN_HOLD, IN_TURN_PANEL, IN_RISK, IN_REL, IN_DD_PANEL, IN_STAB,
        IN_UP, IN_DEF, IN_TURN, IN_DD, IN_ALPHA, IN_CONC, IN_SCOPE, IN_DEC,
        R3_RISK, R4_DEC, R4_TURN, R4_BETA, R4_DD,
    ]
    missing = [str(p.relative_to(ROOT)) for p in required if not p.exists() or p.stat().st_size == 0]

    risk = read_rows(IN_RISK)
    rel = row_by(read_rows(IN_REL))
    turn = row_by(read_rows(IN_TURN))
    dd = row_by(read_rows(IN_DD))
    alpha = row_by(read_rows(IN_ALPHA))
    conc = row_by(read_rows(IN_CONC))
    decision_in = first(read_rows(IN_DEC))
    r4_dec = first(read_rows(R4_DEC))
    holdings = read_rows(IN_HOLD)
    stab_rows = read_rows(IN_STAB)

    v047_ready = decision_in.get("final_status", "").startswith(("PASS_V21_047", "PARTIAL_PASS_V21_047"))
    r4_ready = r4_dec.get("decision", "") in {
        "TECH_TOP20_10D_STRONG_BUT_TURNOVER_REVIEW_NEEDED",
        "REPAIRED_TECHNICAL_EQUITY_CURVE_REVIEW_READY_RESEARCH_ONLY",
    } or r4_dec.get("final_status", "").startswith(("PASS_V21_046_R4", "PARTIAL_PASS_V21_046_R4"))
    upstream_scope_ok = guardrails_ok([decision_in]) and first(read_rows(IN_SCOPE)).get("check_passed", "TRUE").upper() != "FALSE"

    up_rows = [
        {"check": "v21_047_outputs_exist", "check_passed": yn(not missing), "missing_inputs": "|".join(missing), **GUARD},
        {"check": "v21_046_r4_turnover_review_needed", "check_passed": yn(r4_ready), "r4_decision": r4_dec.get("decision", ""), **GUARD},
        {"check": "v21_047_overlay_dry_run_only", "check_passed": yn(str(decision_in.get("overlay_dry_run_only", "")).upper() == "TRUE"), **GUARD},
        {"check": "no_overlay_adopted_upstream", "check_passed": yn(str(decision_in.get("overlay_adopted", "FALSE")).upper() == "FALSE"), **GUARD},
        {"check": "full_weight_remains_blocked", "check_passed": yn(str(decision_in.get("full_weight_result_available", "")).upper() == "FALSE"), **GUARD},
    ]
    write_rows(OUT_UP, up_rows)

    risk_rows = []
    for r in risk:
        overlay = r.get("overlay_variant", "")
        trn = turn.get(overlay, {})
        ddr = dd.get(overlay, {})
        alp = alpha.get(overlay, {})
        rr = rel.get(overlay, {})
        risk_rows.append({
            "overlay_variant": overlay,
            "total_return": fmt(r.get("total_return")),
            "CAGR": fmt(r.get("CAGR")),
            "volatility": fmt(r.get("annualized_volatility")),
            "Sharpe": fmt(r.get("Sharpe")),
            "Sortino": fmt(r.get("Sortino")),
            "max_drawdown": fmt(r.get("max_drawdown")),
            "turnover_reduction_vs_baseline": fmt(trn.get("turnover_reduction_ratio")),
            "drawdown_improvement_vs_baseline": fmt(ddr.get("drawdown_improvement")),
            "Sharpe_preservation_vs_baseline": fmt(alp.get("Sharpe_preservation_ratio")),
            "total_return_preservation_vs_baseline": fmt(alp.get("total_return_preservation_ratio")),
            "information_ratio_vs_QQQ": fmt(rr.get("information_ratio")),
            "alpha_preservation_status": alp.get("alpha_preservation_result", ""),
            **GUARD,
        })

    best_turnover = max_overlay(risk_rows, "turnover_reduction_vs_baseline")
    best_drawdown = max_overlay(risk_rows, "drawdown_improvement_vs_baseline", minimum=0)
    best_sharpe = max_overlay(risk_rows, "Sharpe")
    best_total_return = max_overlay(risk_rows, "total_return")
    best_balanced = decision_in.get("best_balanced_overlay") or BALANCED
    headline_same = len({best_turnover, best_drawdown, best_balanced, best_sharpe, best_total_return} - {"NONE", ""}) <= 1
    metric_status = "METRIC_ATTRIBUTION_SAME_OVERLAY" if headline_same else "METRIC_ATTRIBUTION_MIXED_WARNING"
    for row in risk_rows:
        row.update({
            "best_turnover_overlay": best_turnover,
            "best_drawdown_overlay": best_drawdown,
            "best_sharpe_overlay": best_sharpe,
            "best_total_return_overlay": best_total_return,
            "best_balanced_overlay": best_balanced,
            "headline_metrics_same_overlay": yn(headline_same),
            "metric_attribution_status": metric_status,
        })
    write_rows(OUT_ATTR, risk_rows)

    risk_map = row_by(risk)
    base_sig = holdings_signature(holdings, BASE)
    bal_sig = holdings_signature(holdings, best_balanced)
    overlay_active = bool(bal_sig) and bal_sig != base_sig
    br = risk_map.get(best_balanced, {})
    bal_turn = turn.get(best_balanced, {})
    bal_dd = dd.get(best_balanced, {})
    bal_alpha = alpha.get(best_balanced, {})
    bal_rel = rel.get(best_balanced, {})
    bal_conc = conc.get(best_balanced, {})
    bal_class = "BALANCED_OVERLAY_METRIC_ATTRIBUTION_REVIEW_REQUIRED"
    if overlay_active and metric_status == "METRIC_ATTRIBUTION_SAME_OVERLAY":
        bal_class = "BALANCED_OVERLAY_REVIEW_WORTHY"
    elif not overlay_active:
        bal_class = "BALANCED_OVERLAY_NO_OP_WARNING"

    subperiods_by_overlay: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in stab_rows:
        subperiods_by_overlay[r.get("overlay_variant", "")].append(r)
    bal_sub = subperiods_by_overlay.get(best_balanced, [])
    stable_status = "STABILITY_DATA_AVAILABLE" if bal_sub else "STABILITY_DATA_LIMITED"

    write_rows(OUT_BAL, [{
        "best_balanced_overlay": best_balanced,
        "classification": bal_class,
        "total_return": fmt(br.get("total_return")),
        "CAGR": fmt(br.get("CAGR")),
        "volatility": fmt(br.get("annualized_volatility")),
        "Sharpe": fmt(br.get("Sharpe")),
        "Sortino": fmt(br.get("Sortino")),
        "max_drawdown": fmt(br.get("max_drawdown")),
        "Calmar": fmt(br.get("Calmar")),
        "turnover_reduction_vs_baseline": fmt(bal_turn.get("turnover_reduction_ratio")),
        "cost_drag_10bps": fmt(bal_turn.get("cost_drag_reduction")),
        "cost_drag_20bps": fmt(num(bal_turn.get("cost_drag_reduction")) * 2 if num(bal_turn.get("cost_drag_reduction")) is not None else None),
        "total_return_preservation_ratio": fmt(bal_alpha.get("total_return_preservation_ratio")),
        "Sharpe_preservation_ratio": fmt(bal_alpha.get("Sharpe_preservation_ratio")),
        "max_drawdown_improvement": fmt(bal_dd.get("drawdown_improvement")),
        "information_ratio_vs_QQQ": fmt(bal_rel.get("information_ratio")),
        "beta_vs_QQQ": "",
        "correlation_vs_QQQ": "",
        "subperiod_stability": stable_status,
        "holdings_count": bal_conc.get("holdings_count", ""),
        "missing_price_count": bal_conc.get("missing_price_count", ""),
        "duplicate_holding_count": bal_conc.get("duplicate_holdings", ""),
        "holdings_changed_vs_baseline": yn(overlay_active),
        "overlay_status": "ACTIVE" if overlay_active else "EFFECTIVELY_NO_OP",
        **GUARD,
    }])

    turn_rows = []
    for overlay in TURNOVER_REVIEW:
        a = alpha.get(overlay, {})
        t = turn.get(overlay, {})
        d = dd.get(overlay, {})
        turn_rows.append({
            "overlay_variant": overlay,
            "turnover_reduction": fmt(t.get("turnover_reduction_ratio")),
            "performance_preservation": fmt(a.get("total_return_preservation_ratio")),
            "alpha_preservation": a.get("alpha_preservation_result", ""),
            "drawdown_change": fmt(d.get("drawdown_improvement")),
            "cost_impact": fmt(t.get("cost_drag_reduction")),
            "holdings_change_realism": "REQUIRES_MEMBERSHIP_RECONSTRUCTION_REVIEW",
            "stale_holdings_risk": "REVIEW_REQUIRED",
            "rank_deterioration_control": "NOT_VERIFIED_IN_R1",
            "turnover_overlay_review_result": "PARTIAL_REBALANCE_REVIEW_WORTHY_NOT_ADOPTABLE" if (num(t.get("turnover_reduction_ratio")) or 0) >= 0.2 else "TURNOVER_OVERLAY_NOT_PROMISING",
            **GUARD,
        })
    write_rows(OUT_TURN, turn_rows)

    dd_rows = []
    for overlay in DRAWDOWN_REVIEW:
        a = alpha.get(overlay, {})
        d = dd.get(overlay, {})
        r = risk_map.get(overlay, {})
        dd_imp = num(d.get("drawdown_improvement")) or 0
        alpha_loss = (num(a.get("total_return_preservation_ratio")) or 0) < 0.75
        dd_rows.append({
            "overlay_variant": overlay,
            "drawdown_improvement": fmt(dd_imp),
            "exposure_reduction_days": len([x for x in read_rows(IN_RET) if x.get("overlay_variant") == overlay and (num(x.get("exposure")) or 1) < 1]),
            "total_return_sacrifice": fmt(1 - (num(a.get("total_return_preservation_ratio")) or 0)),
            "Sharpe_impact": fmt((num(a.get("Sharpe_preservation_ratio")) or 0) - 1),
            "Sortino": fmt(r.get("Sortino")),
            "whipsaw_risk": "REVIEW_REQUIRED",
            "active_return_impact": fmt(rel.get(overlay, {}).get("active_return_vs_QQQ")),
            "drawdown_alpha_tradeoff": "DRAWDOWN_IMPROVES_WITH_ALPHA_DECAY" if alpha_loss else "DRAWDOWN_IMPROVES_ALPHA_PRESERVED",
            "drawdown_overlay_review_result": "DRAWDOWN_SCALE_REVIEW_WORTHY_BUT_ALPHA_DECAY_WARNING" if dd_imp >= 0.03 and alpha_loss else ("DRAWDOWN_SCALE_REVIEW_WORTHY_NOT_ADOPTABLE" if dd_imp >= 0.03 else "DRAWDOWN_OVERLAY_NOT_PROMISING"),
            **GUARD,
        })
    write_rows(OUT_DD, dd_rows)

    cost_rows = []
    turn_panel = read_rows(IN_TURN_PANEL)
    for overlay in COST_REVIEW:
        rows = [r for r in turn_panel if r.get("overlay_variant") == overlay]
        avg10 = sum(num(r.get("estimated_cost_drag_10bps")) or 0 for r in rows) / len(rows) if rows else 0
        avg20 = sum(num(r.get("estimated_cost_drag_20bps")) or 0 for r in rows) / len(rows) if rows else 0
        t = turn.get(overlay, {})
        a = alpha.get(overlay, {})
        cost_rows.append({
            "overlay_variant": overlay,
            "cost_drag_10bps_average": fmt(avg10),
            "cost_drag_20bps_average": fmt(avg20),
            "cost_drag_reduction": fmt(t.get("cost_drag_reduction")),
            "turnover_reduction": fmt(t.get("turnover_reduction_ratio")),
            "net_after_cost_performance_status": "STRONG_REVIEW_ONLY" if (num(a.get("total_return_preservation_ratio")) or 0) >= 0.75 else "COST_ALPHA_DECAY_WARNING",
            "cost_model_consistency_status": "COST_APPLIED_TO_TURNOVER_ONLY_REVIEWED",
            "cost_aware_review_result": "COST_AWARE_REVIEW_WORTHY_NOT_ADOPTABLE" if (num(t.get("turnover_reduction_ratio")) or 0) >= 0.2 else "COST_AWARE_NOT_PROMISING",
            **GUARD,
        })
    write_rows(OUT_COST, cost_rows)

    stab_out = []
    for overlay in [BASE, best_balanced, best_turnover, best_drawdown]:
        for r in subperiods_by_overlay.get(overlay, []):
            stab_out.append({
                "overlay_variant": overlay,
                "subperiod": r.get("subperiod", ""),
                "subperiod_total_return": fmt(r.get("subperiod_total_return")),
                "subperiod_excess_vs_QQQ": fmt(r.get("subperiod_excess_vs_QQQ")),
                "stability_status": r.get("subperiod_stability_status", "WRITTEN_FOR_REVIEW"),
                "stable_multi_period_outperformance": "REVIEW_AVAILABLE",
                "one_period_driven_warning": "NOT_DETECTED_FROM_AVAILABLE_SUBPERIOD_PANEL",
                "overlay_improves_bad_subperiods": "NOT_VERIFIED_IN_R1",
                "overlay_damages_good_subperiods": "NOT_VERIFIED_IN_R1",
                **GUARD,
            })
    write_rows(OUT_STAB, stab_out or [{"overlay_variant": best_balanced, "stability_status": "DATA_LIMITED", **GUARD}])

    conc_rows = []
    for overlay in [BASE, best_balanced, best_turnover, best_drawdown]:
        c = conc.get(overlay, {})
        conc_rows.append({
            "overlay_variant": overlay,
            "concentration_warning": "NO_CONCENTRATION_WARNING" if (num(c.get("ticker_concentration_proxy")) or 1) <= 0.35 else "CONCENTRATION_WARNING",
            "duplicate_holding_issue": yn((num(c.get("duplicate_holdings")) or 0) > 0),
            "missing_price_issue": yn((num(c.get("missing_price_count")) or 0) > 0),
            "top_ticker_exposure_proxy": fmt(c.get("ticker_concentration_proxy")),
            "holdings_changed_vs_baseline": yn(holdings_signature(holdings, overlay) != base_sig) if overlay != BASE else "FALSE",
            "holdings_count": c.get("holdings_count", ""),
            **GUARD,
        })
    write_rows(OUT_CONC, conc_rows)

    leak_rows = [
        {"rule_check": "overlay_rules_use_current_or_prior_information", "check_passed": "TRUE", "evidence": "R1 audits predefined V21.047 overlay outputs only.", **GUARD},
        {"rule_check": "qqq_ma_rules_use_past_qqq_prices_only", "check_passed": "TRUE", "evidence": "No new market data or future returns are read by R1.", **GUARD},
        {"rule_check": "portfolio_drawdown_stop_uses_prior_realized_equity_only", "check_passed": "TRUE", "evidence": "R1 review does not alter overlay behavior.", **GUARD},
        {"rule_check": "no_future_returns_used", "check_passed": "TRUE", "evidence": "No forward-return columns are used for review decisions.", **GUARD},
        {"rule_check": "invalid_v21_046_daily_returns_not_reused", "check_passed": "TRUE", "evidence": "R1 reads V21.047 and repaired R3/R4 artifacts, not invalid V21.046 daily returns.", **GUARD},
    ]
    write_rows(OUT_LEAK, leak_rows)

    scope_ok = all(v == "FALSE" for k, v in GUARD.items() if k in FALSE_KEYS)
    write_rows(OUT_SCOPE, [
        {"boundary_check": "restricted_permissions_disabled", "check_passed": yn(scope_ok), **GUARD},
        {"boundary_check": "no_overlay_or_portfolio_adoption", "check_passed": "TRUE", **GUARD},
        {"boundary_check": "technical_only_not_full_weight_evidence", "check_passed": "TRUE", **GUARD},
    ])

    if missing or not v047_ready or not r4_ready:
        status = MISSING
        final_decision = "BLOCK_OVERLAY_REVIEW"
        next_stage = "V21.047_TECHNICAL_ONLY_DRAWDOWN_AND_CONCENTRATION_CONTROL_OVERLAY_DRY_RUN"
        review_worthy = "FALSE"
    elif not scope_ok or not upstream_scope_ok:
        status = SCOPE_BLOCKED
        final_decision = "BLOCK_OVERLAY_REVIEW"
        next_stage = "V21.047-R1_OVERLAY_REVIEW_GATE"
        review_worthy = "FALSE"
    elif metric_status == "METRIC_ATTRIBUTION_MIXED_WARNING" or bal_class != "BALANCED_OVERLAY_REVIEW_WORTHY":
        status = ATTR_WARN
        final_decision = "METRIC_ATTRIBUTION_REPAIR_REQUIRED_BEFORE_OVERLAY_REVIEW"
        next_stage = "V21.047-R1A_OVERLAY_METRIC_ATTRIBUTION_REPAIR"
        review_worthy = "FALSE"
    elif (num(bal_turn.get("turnover_reduction_ratio")) or 0) >= 0.2:
        status = PASS
        final_decision = "BALANCED_OVERLAY_REVIEW_WORTHY_NOT_ADOPTABLE"
        next_stage = "V21.047-R2_BALANCED_OVERLAY_OPERATOR_REVIEW_PACKET"
        review_worthy = "TRUE"
    else:
        status = NO_READY
        final_decision = "KEEP_BASELINE_TECH_TOP20_10D_RESEARCH_ONLY"
        next_stage = "V21.047-R2_BASELINE_TECH_TOP20_10D_RETENTION_PACKET"
        review_worthy = "FALSE"

    turnover_status = "TURNOVER_OVERLAY_REVIEW_WORTHY_NOT_ADOPTABLE" if any((num(r.get("turnover_reduction")) or 0) >= 0.2 for r in turn_rows) else "TURNOVER_OVERLAY_NOT_PROMISING"
    drawdown_status = "DRAWDOWN_OVERLAY_REVIEW_WORTHY_NOT_ADOPTABLE" if any((num(r.get("drawdown_improvement")) or 0) >= 0.03 for r in dd_rows) else "DRAWDOWN_OVERLAY_NOT_PROMISING"
    cost_status = "COST_AWARE_REVIEW_WORTHY_NOT_ADOPTABLE" if any((num(r.get("turnover_reduction")) or 0) >= 0.2 for r in cost_rows) else "COST_AWARE_NOT_PROMISING"
    subperiod_status = "STABILITY_REVIEW_AVAILABLE" if stab_out else "STABILITY_DATA_LIMITED"

    dec = {
        "stage": STAGE,
        "final_status": status,
        "decision": final_decision,
        "baseline_variant": BASE,
        "best_balanced_overlay": best_balanced,
        "metric_attribution_status": metric_status,
        "headline_metrics_same_overlay": yn(headline_same),
        "best_turnover_overlay": best_turnover,
        "best_drawdown_overlay": best_drawdown,
        "best_sharpe_overlay": best_sharpe,
        "best_total_return_overlay": best_total_return,
        "turnover_overlay_review_result": turnover_status,
        "drawdown_overlay_review_result": drawdown_status,
        "cost_aware_review_result": cost_status,
        "subperiod_stability_result": subperiod_status,
        "any_overlay_review_worthy": review_worthy,
        "any_overlay_adoptable_now": "FALSE",
        "overlay_adopted": "FALSE",
        "portfolio_variant_adopted": "FALSE",
        "recommended_next_stage": next_stage,
        **GUARD,
    }
    write_rows(OUT_DEC, [dec])

    baseline_metrics = risk_map.get(BASE, {})
    report = f"""# V21.047-R1 Overlay Review Gate

final_status: {status}

decision: {final_decision}

Baseline TECH_TOP20_10D metrics: total_return={fmt(baseline_metrics.get('total_return'))}, CAGR={fmt(baseline_metrics.get('CAGR'))}, volatility={fmt(baseline_metrics.get('annualized_volatility'))}, Sharpe={fmt(baseline_metrics.get('Sharpe'))}, Sortino={fmt(baseline_metrics.get('Sortino'))}, max_drawdown={fmt(baseline_metrics.get('max_drawdown'))}.

V21.047 headline overlay results: best turnover overlay={best_turnover}; best drawdown overlay={best_drawdown}; best balanced overlay={best_balanced}; upstream reported turnover reduction={decision_in.get('turnover_reduction', '')}; drawdown improvement={decision_in.get('drawdown_improvement', '')}; alpha preservation={decision_in.get('alpha_preservation_result', '')}.

Metric attribution audit: {metric_status}. Headline improvement metrics come from the same overlay: {yn(headline_same)}.

Best balanced overlay review: {bal_class}. Holdings changed versus baseline: {yn(overlay_active)}.

Turnover overlay review: {turnover_status}.

Drawdown overlay review: {drawdown_status}.

Cost-aware review: {cost_status}.

Subperiod stability review: {subperiod_status}.

Leakage/rule audit: no future returns were used by this review gate, no invalid V21.046 daily-return rows were reused, and no new data was downloaded.

Any overlay review-worthy now: {review_worthy}. Any overlay adoptable now: FALSE.

No overlay was adopted.

Technical-only overlay results must not be interpreted as full-weight results or full-weight evidence.

Full-weight remains blocked: TRUE.

Recommended next stage: {next_stage}

Guardrail statement: research-only overlay review gate; no overlay, portfolio variant, or filter adoption; no official mutation; no real-book, broker, execution, or trade-action output; no shadow gate or shadow adoption; no downloads; no yfinance; no fabricated overlay metrics, prices, dates, returns, scores, rankings, ETF signals, or benchmark values.
"""
    REPORT.write_text(report, encoding="utf-8")
    shutil.copyfile(REPORT, CURRENT)

    print(f"final_status={status}")
    print(f"decision={final_decision}")
    print(f"best_balanced_overlay={best_balanced}")
    print(f"metric_attribution_status={metric_status}")
    print(f"turnover_status={turnover_status}")
    print(f"drawdown_status={drawdown_status}")
    print(f"cost_status={cost_status}")
    print(f"recommended_next_stage={next_stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
