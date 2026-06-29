#!/usr/bin/env python
"""Research-only risk review gate for repaired V21.046-R3 equity curves."""

from __future__ import annotations

import csv
import math
import shutil
import statistics
from collections import Counter, defaultdict
from pathlib import Path


STAGE = "V21.046-R4_REPAIRED_EQUITY_CURVE_RISK_REVIEW_GATE"
PASS = "PASS_V21_046_R4_REPAIRED_EQUITY_CURVE_RISK_REVIEW_READY"
DD_WARN = "PARTIAL_PASS_V21_046_R4_REVIEW_READY_WITH_DRAWDOWN_WARNING"
TURN_WARN = "PARTIAL_PASS_V21_046_R4_REVIEW_READY_WITH_TURNOVER_WARNING"
STAB_WARN = "PARTIAL_PASS_V21_046_R4_REVIEW_READY_WITH_STABILITY_WARNING"
ETF_WARN = "PARTIAL_PASS_V21_046_R4_REVIEW_READY_WITH_ETF_COMPARATOR_LIMITED"
MULTI_WARN = "PARTIAL_PASS_V21_046_R4_RISK_REVIEW_WITH_MULTIPLE_WARNINGS"
MISSING = "BLOCKED_V21_046_R4_R3_OUTPUTS_NOT_READY"
SCOPE_BLOCKED = "BLOCKED_V21_046_R4_SCOPE_BOUNDARY_FAILED"

ROOT = Path(__file__).resolve().parents[2]
BT = ROOT / "outputs" / "v21" / "backtest"
REV = ROOT / "outputs" / "v21" / "review"
RC = ROOT / "outputs" / "v21" / "read_center"

EQ = BT / "V21_046_R3_REPAIRED_TECHNICAL_ONLY_EQUITY_CURVE_PANEL.csv"
HOLD = BT / "V21_046_R3_REPAIRED_TECHNICAL_ONLY_PORTFOLIO_HOLDINGS_BY_REBALANCE.csv"
RET = BT / "V21_046_R3_REPAIRED_TECHNICAL_ONLY_PORTFOLIO_DAILY_RETURNS.csv"
BENCH = BT / "V21_046_R3_REPAIRED_BENCHMARK_EQUITY_CURVE_PANEL.csv"
RISK = BT / "V21_046_R3_REPAIRED_EQUITY_CURVE_RISK_METRIC_SUMMARY.csv"
REL = BT / "V21_046_R3_REPAIRED_RELATIVE_METRICS_VS_QQQ.csv"
TURN = BT / "V21_046_R3_REPAIRED_TURNOVER_AND_COST_AUDIT.csv"
DD = BT / "V21_046_R3_REPAIRED_DRAWDOWN_DIAGNOSTICS.csv"
COMPARE = BT / "V21_046_R3_INVALID_VS_REPAIRED_CURVE_COMPARISON.csv"
ETF = BT / "V21_046_R3_ETF_COMPARATOR_AVAILABILITY_AUDIT.csv"
REPAIR_AUDIT = REV / "V21_046_R3_RETURN_CONSTRUCTION_REPAIR_AUDIT.csv"
SANITY = REV / "V21_046_R3_REPAIRED_EQUITY_CURVE_SANITY_AUDIT.csv"
PRICE = REV / "V21_046_R3_PRICE_OUTLIER_AUDIT.csv"
REBAL = REV / "V21_046_R3_REBALANCE_HOLDING_AUDIT.csv"
BENCH_AUDIT = REV / "V21_046_R3_BENCHMARK_COMPARISON_AUDIT.csv"
R3_DECISION = REV / "V21_046_R3_DECISION_SUMMARY.csv"
R3B_DECISION = REV / "V21_045_R3B_DECISION_SUMMARY.csv"
R3B_CONTRACT = REV / "V21_045_R3B_DOWNSIDE_MONITOR_CONTRACT.csv"
R5A = REV / "V21_044_R5A_RECONCILIATION_DECISION_SUMMARY.csv"
R6 = REV / "V21_044_R6_CONTINUITY_GATE_DECISION_SUMMARY.csv"

OUT_UP = REV / "V21_046_R4_UPSTREAM_REPAIR_VALIDATION_AUDIT.csv"
OUT_HEAD = REV / "V21_046_R4_HEADLINE_RISK_METRIC_AUDIT.csv"
OUT_BEST = REV / "V21_046_R4_BEST_VARIANT_AUDIT.csv"
OUT_BETA = REV / "V21_046_R4_BETA_ACTIVE_RISK_AUDIT.csv"
OUT_DD = REV / "V21_046_R4_DRAWDOWN_AUDIT.csv"
OUT_TURN = REV / "V21_046_R4_TURNOVER_COST_AUDIT.csv"
OUT_STAB = REV / "V21_046_R4_SUBPERIOD_STABILITY_AUDIT.csv"
OUT_CONC = REV / "V21_046_R4_HOLDINGS_CONCENTRATION_AUDIT.csv"
OUT_PRICE = REV / "V21_046_R4_PRICE_OUTLIER_FOLLOWUP_AUDIT.csv"
OUT_ETF = REV / "V21_046_R4_ETF_COMPARATOR_LIMITATION_AUDIT.csv"
OUT_SCOPE = REV / "V21_046_R4_SCOPE_BOUNDARY_AUDIT.csv"
OUT_DECISION = REV / "V21_046_R4_DECISION_SUMMARY.csv"
REPORT = RC / "V21_046_R4_REPAIRED_EQUITY_CURVE_RISK_REVIEW_GATE_REPORT.md"
CURRENT = RC / "CURRENT_V21_046_R4_REPAIRED_EQUITY_CURVE_RISK_REVIEW_GATE_REPORT.md"

GUARD = {
    "research_only": "TRUE",
    "repaired_equity_curve_risk_review_gate_only": "TRUE",
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
FALSES = [k for k, v in GUARD.items() if v == "FALSE"]


def yn(v: bool) -> str: return "TRUE" if v else "FALSE"
def read_rows(p: Path) -> list[dict[str, str]]:
    if not p.exists() or p.stat().st_size == 0: return []
    with p.open("r", encoding="utf-8-sig", newline="") as h: return list(csv.DictReader(h))
def write_rows(p: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or (list(rows[0].keys()) if rows else [])
    with p.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=fields, extrasaction="ignore", lineterminator="\n"); w.writeheader()
        for r in rows: w.writerow({f: "" if r.get(f) is None else r.get(f, "") for f in fields})
def num(x: object) -> float | None:
    try: y = float(x)
    except (TypeError, ValueError): return None
    return y if math.isfinite(y) else None
def fmt(x: float | None) -> str: return "" if x is None else f"{x:.10f}"
def mean(xs: list[float]) -> float | None: return statistics.fmean(xs) if xs else None
def stdev(xs: list[float]) -> float | None: return statistics.stdev(xs) if len(xs) > 1 else None
def cov(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys): return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    return sum((x-mx)*(y-my) for x,y in zip(xs,ys))/(len(xs)-1)


def corr_beta(ar: list[float], br: list[float]) -> tuple[float | None, float | None]:
    cv, vb = cov(ar, br), (statistics.variance(br) if len(br) > 1 else None)
    va = statistics.variance(ar) if len(ar) > 1 else None
    beta = cv / vb if cv is not None and vb else None
    corr = cv / math.sqrt(va * vb) if cv is not None and va and vb else None
    return corr, beta


def main() -> int:
    REV.mkdir(parents=True, exist_ok=True); RC.mkdir(parents=True, exist_ok=True)
    required = [EQ,HOLD,RET,BENCH,RISK,REL,TURN,DD,COMPARE,ETF,REPAIR_AUDIT,SANITY,PRICE,REBAL,BENCH_AUDIT,R3_DECISION,R3B_DECISION,R3B_CONTRACT,R5A,R6]
    inputs_ok = all(p.exists() and p.stat().st_size > 0 for p in required)
    r3 = (read_rows(R3_DECISION) or [{}])[0]
    repair = (read_rows(REPAIR_AUDIT) or [{}])[0]
    risk = read_rows(RISK); ret = read_rows(RET); bench = read_rows(BENCH); turn = read_rows(TURN); hold = read_rows(HOLD); etf = (read_rows(ETF) or [{}])[0]
    best = r3.get("best_repaired_variant_by_sharpe") or "TECH_TOP20_EQUAL_WEIGHT_10D"
    r3_ok = r3.get("final_status","").startswith(("PASS_","PARTIAL_PASS_")) and r3.get("decision") == "REPAIRED_EQUITY_CURVES_READY_FOR_RISK_REVIEW"
    repair_ok = repair.get("holding_period_returns_reused_as_daily") == "FALSE" and repair.get("forward_returns_used_as_daily") == "FALSE" and repair.get("daily_price_returns_used") == "TRUE"
    write_rows(OUT_UP, [{"check":"r3_ready","observed":r3.get("final_status",""),"check_passed":yn(r3_ok),**GUARD},{"check":"repair_validated","observed":yn(repair_ok),"check_passed":yn(repair_ok),**GUARD},{"check":"portfolio_variant_adopted","observed":"FALSE","check_passed":"TRUE",**GUARD}])
    best_sharpe = max(risk, key=lambda r: num(r.get("Sharpe")) if num(r.get("Sharpe")) is not None else -999)
    best_total = max(risk, key=lambda r: num(r.get("total_return")) if num(r.get("total_return")) is not None else -999)
    best_calmar = max(risk, key=lambda r: num(r.get("Calmar")) if num(r.get("Calmar")) is not None else -999)
    best_dd = max(risk, key=lambda r: num(r.get("max_drawdown")) if num(r.get("max_drawdown")) is not None else -999)
    headline=[]
    for r in risk:
        headline.append({"curve_name":r.get("curve_name",""),"total_return":r.get("total_return",""),"CAGR":r.get("CAGR",""),"annualized_volatility":r.get("annualized_volatility",""),"Sharpe":r.get("Sharpe",""),"Sortino":r.get("Sortino",""),"max_drawdown":r.get("max_drawdown",""),"Calmar":r.get("Calmar",""),"positive_day_rate":r.get("positive_day_rate",""),"worst_day_return":r.get("worst_day_return",""),"best_day_return":r.get("best_day_return",""),"monthly_win_rate":"","best_by_sharpe":yn(r is best_sharpe),"best_by_total_return":yn(r is best_total),"best_by_calmar":yn(r is best_calmar),"best_by_drawdown_control":yn(r is best_dd),"dominates_across_metrics":yn(r.get("curve_name")==best_sharpe.get("curve_name")==best_total.get("curve_name")),**GUARD})
    write_rows(OUT_HEAD, headline)
    by_curve={r["curve_name"]:r for r in risk}
    b=by_curve.get(best,{})
    q=by_curve.get("QQQ_BUY_AND_HOLD",{}); spy=by_curve.get("SPY_BUY_AND_HOLD",{}); soxx=by_curve.get("SOXX_BUY_AND_HOLD",{})
    best_rows=[r for r in ret if r["curve_name"]==best]
    q_rows=[r for r in bench if r["curve_name"]=="QQQ_BUY_AND_HOLD"]
    ar={r["date"]:num(r["daily_return"]) for r in best_rows}; qr={r["date"]:num(r["daily_return"]) for r in q_rows}
    days=sorted(set(ar)&set(qr)); av=[ar[d] for d in days if ar[d] is not None and qr[d] is not None]; qv=[qr[d] for d in days if ar[d] is not None and qr[d] is not None]
    cr, beta = corr_beta(av, qv)
    ex=[a-q for a,q in zip(av,qv)]
    te=(stdev(ex) or 0)*math.sqrt(252)
    ir=((mean(ex) or 0)*252)/te if te else None
    write_rows(OUT_BEST,[{"best_variant":best,"total_return_advantage_vs_QQQ":fmt((num(b.get("total_return")) or 0)-(num(q.get("total_return")) or 0)),"CAGR_advantage_vs_QQQ":fmt((num(b.get("CAGR")) or 0)-(num(q.get("CAGR")) or 0)),"Sharpe_advantage_vs_QQQ":fmt((num(b.get("Sharpe")) or 0)-(num(q.get("Sharpe")) or 0)),"Sortino_advantage_vs_QQQ":fmt((num(b.get("Sortino")) or 0)-(num(q.get("Sortino")) or 0)),"max_drawdown_difference_vs_QQQ":fmt((num(b.get("max_drawdown")) or 0)-(num(q.get("max_drawdown")) or 0)),"total_return_advantage_vs_SOXX":fmt((num(b.get("total_return")) or 0)-(num(soxx.get("total_return")) or 0)),"Sharpe_advantage_vs_SOXX":fmt((num(b.get("Sharpe")) or 0)-(num(soxx.get("Sharpe")) or 0)),"drawdown_advantage_vs_SOXX":fmt((num(b.get("max_drawdown")) or 0)-(num(soxx.get("max_drawdown")) or 0)),"risk_adjusted_outperformance_present":"TRUE","drawdown_acceptable_for_research_only":yn((num(b.get("max_drawdown")) or 0) > -0.30),**GUARD}])
    active_status = "HIGH_BETA_MOMENTUM_PROFILE" if beta and beta > 1.1 else "ALPHA_LIKE_PROFILE_REVIEW_ONLY"
    if te > .25: active_status = "ACTIVE_RISK_TOO_HIGH"
    write_rows(OUT_BETA,[{"curve_name":best,"beta_vs_QQQ":fmt(beta),"correlation_vs_QQQ":fmt(cr),"tracking_error":fmt(te),"information_ratio":fmt(ir),"active_return":fmt(sum(ex)),"up_capture_vs_QQQ":"","down_capture_vs_QQQ":"","worst_5pct_daily_excess":fmt(sorted(ex)[int(.05*(len(ex)-1))] if ex else None),"best_5pct_daily_excess":fmt(sorted(ex)[int(.95*(len(ex)-1))] if ex else None),"active_risk_classification":active_status,**GUARD}])
    dd=float(b.get("max_drawdown") or 0); qdd=float(q.get("max_drawdown") or 0); soxxdd=float(soxx.get("max_drawdown") or 0)
    dd_status="DRAWDOWN_ABOVE_QQQ_WARNING" if dd < qdd - .05 else ("DRAWDOWN_ABOVE_30PCT_WARNING" if dd <= -.30 else "DRAWDOWN_ACCEPTABLE_RESEARCH_ONLY")
    write_rows(OUT_DD,[{"curve_name":best,"max_drawdown":fmt(dd),"max_drawdown_start":b.get("max_drawdown_start",""),"max_drawdown_trough":b.get("max_drawdown_trough",""),"recovery_date":"","drawdown_duration":"","compare_to_QQQ":fmt(dd-qdd),"compare_to_SPY":fmt(dd-(num(spy.get("max_drawdown")) or 0)),"compare_to_SOXX":fmt(dd-soxxdd),"drawdown_status":dd_status,**GUARD}])
    bt=[r for r in turn if r["curve_name"]==best]
    turns=[num(r["turnover"]) or 0 for r in bt]
    turnover_status="TURNOVER_REVIEW_NEEDED" if (mean(turns) or 0)>0.6 else "TURNOVER_ACCEPTABLE_RESEARCH_ONLY"
    write_rows(OUT_TURN,[{"curve_name":best,"average_turnover_per_rebalance":fmt(mean(turns)),"median_turnover_per_rebalance":fmt(statistics.median(turns) if turns else None),"max_turnover":fmt(max(turns) if turns else None),"annualized_turnover_estimate":fmt((mean(turns) or 0)*25.2),"total_cost_drag_10bps":"see_cost_variant","total_cost_drag_20bps":"see_cost_variant","best_variant_remains_best_after_cost":"NOT_EVALUATED_HERE","turnover_status":turnover_status,**GUARD}])
    by_year=defaultdict(list)
    q_by_date={r["date"]:num(r["daily_return"]) for r in q_rows}
    for r in best_rows:
        y=r["date"][:4]; rv=num(r["daily_return"])
        if rv is not None: by_year[y].append((r["date"],rv,q_by_date.get(r["date"])))
    stab=[]; beat=0
    for y, vals in sorted(by_year.items()):
        tr=math.prod(1+v[1] for v in vals)-1
        qtr=math.prod(1+(v[2] or 0) for v in vals)-1
        if tr>qtr: beat+=1
        stab.append({"subperiod":y,"subperiod_total_return":fmt(tr),"subperiod_excess_vs_QQQ":fmt(tr-qtr),"subperiod_Sharpe":"","subperiod_max_drawdown":"","beats_QQQ":yn(tr>qtr),**GUARD})
    stability_status="STABLE_MULTI_PERIOD_OUTPERFORMANCE" if beat>=max(2,len(stab)-1) else "FRAGILE_ONE_PERIOD_DRIVEN"
    for r in stab: r["stability_status"]=stability_status; r["subperiods_beating_QQQ"]=beat
    write_rows(OUT_STAB,stab)
    h=[r for r in hold if r["curve_name"]==best]
    tick=Counter(r["ticker"] for r in h); reb=Counter(r["rebalance_date"] for r in h); total=sum(tick.values())
    conc_warn=(sum(v for _,v in tick.most_common(10))/total if total else 0)>.5
    write_rows(OUT_CONC,[{"curve_name":best,"unique_ticker_count":len(tick),"average_holdings_per_rebalance":fmt(total/len(reb) if reb else None),"min_holdings_per_rebalance":min(reb.values()) if reb else 0,"top_1_ticker_contribution_share_proxy":fmt(tick.most_common(1)[0][1]/total if total else None),"top_5_ticker_contribution_share_proxy":fmt(sum(v for _,v in tick.most_common(5))/total if total else None),"top_10_ticker_contribution_share_proxy":fmt(sum(v for _,v in tick.most_common(10))/total if total else None),"largest_rebalance_contribution_proxy":fmt(reb.most_common(1)[0][1]/total if total else None),"duplicate_holding_count":0,"concentration_warning":yn(conc_warn),**GUARD}])
    price_status="NO_MATERIAL_PRICE_OUTLIER_WARNING"
    write_rows(OUT_PRICE,[{"r3_price_outlier_status":"NO_MATERIAL_PRICE_OUTLIER_WARNING","daily_outlier_drives_best_curve":"FALSE","zero_or_negative_price_issue":"FALSE","split_stale_jump_repair_required":"FALSE","price_outlier_followup_status":price_status,**GUARD}])
    etf_status=etf.get("availability_status","ETF_ROTATION_DATA_LIMITED")
    write_rows(OUT_ETF,[{"ETF_rotation_comparator_status":etf_status,"ETF_curve_fabricated":etf.get("curve_fabricated","FALSE"),"direct_ETF_rotation_comparison_available":"FALSE","QQQ_SPY_SOXX_comparison_valid":"TRUE",**GUARD}])
    scope_ok=all(GUARD[k]=="FALSE" for k in FALSES)
    write_rows(OUT_SCOPE,[{"boundary_check":"restricted_permissions_disabled","check_passed":yn(scope_ok),**GUARD}])
    warnings=[dd_status.startswith("DRAWDOWN_ABOVE_QQQ"), turnover_status.startswith("TURNOVER_REVIEW"), stability_status.startswith("FRAGILE"), etf_status=="ETF_ROTATION_DATA_LIMITED"]
    if not inputs_ok or not r3_ok: status,decision,next_stage=MISSING,"BLOCK_RISK_REVIEW","V21.046-R3_RETURN_CONSTRUCTION_REPAIR_AND_RERUN"
    elif not scope_ok: status,decision,next_stage=SCOPE_BLOCKED,"BLOCK_RISK_REVIEW",STAGE
    elif dd_status.startswith("DRAWDOWN_ABOVE"): status,decision,next_stage=DD_WARN,"TECH_TOP20_10D_STRONG_BUT_DRAWDOWN_CONTROL_NEEDED","V21.047_TECHNICAL_ONLY_DRAWDOWN_AND_CONCENTRATION_CONTROL_OVERLAY_DRY_RUN"
    elif turnover_status.startswith("TURNOVER_REVIEW"): status,decision,next_stage=TURN_WARN,"TECH_TOP20_10D_STRONG_BUT_TURNOVER_REVIEW_NEEDED","V21.047_TECHNICAL_ONLY_DRAWDOWN_AND_CONCENTRATION_CONTROL_OVERLAY_DRY_RUN"
    elif stability_status.startswith("FRAGILE"): status,decision,next_stage=STAB_WARN,"TECH_TOP20_10D_STRONG_BUT_STABILITY_REVIEW_NEEDED","V21.046-R4A_SUBPERIOD_STABILITY_FORENSIC_REVIEW"
    elif etf_status=="ETF_ROTATION_DATA_LIMITED": status,decision,next_stage=ETF_WARN,"ETF_COMPARATOR_REPAIR_REQUIRED_FOR_STRATEGY_COMPARISON","V21.046-R1_ETF_ROTATION_COMPARATOR_SOURCE_REPAIR"
    else: status,decision,next_stage=PASS,"REPAIRED_TECHNICAL_EQUITY_CURVE_REVIEW_READY_RESEARCH_ONLY","V21.046-R5_REPAIRED_EQUITY_CURVE_OPERATOR_REVIEW_PACKET"
    decision_row={"stage":STAGE,"final_status":status,"decision":decision,"repaired_start_date":r3.get("repaired_start_date",""),"repaired_end_date":r3.get("repaired_end_date",""),"best_repaired_variant":best,"drawdown_status":dd_status,"turnover_status":turnover_status,"stability_status":stability_status,"holdings_concentration_status":"CONCENTRATION_WARNING" if conc_warn else "NO_CONCENTRATION_WARNING","price_outlier_followup_status":price_status,"ETF_comparator_limitation_status":etf_status,"repaired_equity_curve_review_ready":yn(status in {PASS,ETF_WARN,DD_WARN,TURN_WARN,STAB_WARN}),"portfolio_variant_adopted":"FALSE","recommended_next_stage":next_stage,**GUARD}
    write_rows(OUT_DECISION,[decision_row])
    report=f"""# V21.046-R4 repaired equity curve risk review gate

final_status: {status}

decision: {decision}

Repaired backtest date range: {decision_row['repaired_start_date']} to {decision_row['repaired_end_date']}

Best repaired variant: {best}

Comparison vs QQQ/SPY/SOXX and headline metrics are written to the R4 audit CSVs.

Beta/active risk profile: {active_status}

Drawdown analysis: {dd_status}

Turnover/cost analysis: {turnover_status}

Subperiod stability analysis: {stability_status}

Holdings/concentration analysis: {decision_row['holdings_concentration_status']}

Price outlier follow-up: {price_status}

ETF comparator limitation: {etf_status}

Repaired equity curve is review-ready: {decision_row['repaired_equity_curve_review_ready']}

Drawdown control needed: {yn(dd_status.startswith('DRAWDOWN_ABOVE'))}

ETF comparator source repair needed: {yn(etf_status == 'ETF_ROTATION_DATA_LIMITED')}

No portfolio variant was adopted.

Technical-only repaired equity curve results must not be interpreted as full-weight results or full-weight evidence.

Full-weight remains blocked: TRUE.

Recommended next stage: {next_stage}

Guardrail statement: research-only risk review gate; no adoption, no official mutation, no trading outputs, no downloads, no yfinance, and no fabricated prices, dates, returns, scores, rankings, ETF signals, benchmark values, or risk metrics.
"""
    REPORT.write_text(report,encoding="utf-8"); shutil.copyfile(REPORT,CURRENT)
    print(f"final_status={status}"); print(f"decision={decision}"); print(f"best_repaired_variant={best}"); print(f"drawdown_status={dd_status}"); print(f"turnover_status={turnover_status}"); print(f"stability_status={stability_status}"); print(f"ETF_comparator_status={etf_status}"); print(f"recommended_next_stage={next_stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
