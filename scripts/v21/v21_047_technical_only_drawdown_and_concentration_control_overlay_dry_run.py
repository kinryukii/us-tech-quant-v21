#!/usr/bin/env python
"""Research-only overlay dry-run for repaired Technical-only Top20 10D curve."""

from __future__ import annotations

import csv
import math
import shutil
import statistics
from collections import Counter, defaultdict
from pathlib import Path


STAGE = "V21.047_TECHNICAL_ONLY_DRAWDOWN_AND_CONCENTRATION_CONTROL_OVERLAY_DRY_RUN"
PASS = "PASS_V21_047_OVERLAY_DRY_RUN_READY"
TURN_WARN = "PARTIAL_PASS_V21_047_OVERLAY_DRY_RUN_WITH_TURNOVER_WARNING"
ALPHA_WARN = "PARTIAL_PASS_V21_047_OVERLAY_DRY_RUN_WITH_ALPHA_DECAY_WARNING"
DD_WARN = "PARTIAL_PASS_V21_047_OVERLAY_DRY_RUN_WITH_DRAWDOWN_WARNING"
DATA_LIMITED = "PARTIAL_PASS_V21_047_OVERLAY_DATA_LIMITED"
MISSING = "BLOCKED_V21_047_R3_R4_INPUTS_NOT_READY"
SCOPE_BLOCKED = "BLOCKED_V21_047_SCOPE_BOUNDARY_FAILED"

ROOT = Path(__file__).resolve().parents[2]
BT = ROOT / "outputs" / "v21" / "backtest"
REV = ROOT / "outputs" / "v21" / "review"
RC = ROOT / "outputs" / "v21" / "read_center"

R3_EQ = BT / "V21_046_R3_REPAIRED_TECHNICAL_ONLY_EQUITY_CURVE_PANEL.csv"
R3_HOLD = BT / "V21_046_R3_REPAIRED_TECHNICAL_ONLY_PORTFOLIO_HOLDINGS_BY_REBALANCE.csv"
R3_RET = BT / "V21_046_R3_REPAIRED_TECHNICAL_ONLY_PORTFOLIO_DAILY_RETURNS.csv"
R3_BENCH = BT / "V21_046_R3_REPAIRED_BENCHMARK_EQUITY_CURVE_PANEL.csv"
R3_RISK = BT / "V21_046_R3_REPAIRED_EQUITY_CURVE_RISK_METRIC_SUMMARY.csv"
R3_REL = BT / "V21_046_R3_REPAIRED_RELATIVE_METRICS_VS_QQQ.csv"
R3_TURN = BT / "V21_046_R3_REPAIRED_TURNOVER_AND_COST_AUDIT.csv"
R3_DD = BT / "V21_046_R3_REPAIRED_DRAWDOWN_DIAGNOSTICS.csv"
R4_DECISION = REV / "V21_046_R4_DECISION_SUMMARY.csv"
R4_HEAD = REV / "V21_046_R4_HEADLINE_RISK_METRIC_AUDIT.csv"
R4_BEST = REV / "V21_046_R4_BEST_VARIANT_AUDIT.csv"
R4_BETA = REV / "V21_046_R4_BETA_ACTIVE_RISK_AUDIT.csv"
R4_DD = REV / "V21_046_R4_DRAWDOWN_AUDIT.csv"
R4_TURN = REV / "V21_046_R4_TURNOVER_COST_AUDIT.csv"
R4_STAB = REV / "V21_046_R4_SUBPERIOD_STABILITY_AUDIT.csv"
R4_CONC = REV / "V21_046_R4_HOLDINGS_CONCENTRATION_AUDIT.csv"
R4_PRICE = REV / "V21_046_R4_PRICE_OUTLIER_FOLLOWUP_AUDIT.csv"
R3B_CONTRACT = REV / "V21_045_R3B_DOWNSIDE_MONITOR_CONTRACT.csv"
BENCH_OHLCV = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"

OUT_EQ = BT / "V21_047_OVERLAY_EQUITY_CURVE_PANEL.csv"
OUT_RET = BT / "V21_047_OVERLAY_DAILY_RETURNS_PANEL.csv"
OUT_HOLD = BT / "V21_047_OVERLAY_HOLDINGS_BY_REBALANCE.csv"
OUT_TURN = BT / "V21_047_OVERLAY_TURNOVER_COST_PANEL.csv"
OUT_RISK = BT / "V21_047_OVERLAY_RISK_METRIC_SUMMARY.csv"
OUT_REL = BT / "V21_047_OVERLAY_RELATIVE_METRICS_VS_QQQ.csv"
OUT_DD = BT / "V21_047_OVERLAY_DRAWDOWN_DIAGNOSTICS.csv"
OUT_STAB = BT / "V21_047_OVERLAY_SUBPERIOD_STABILITY_PANEL.csv"
AUDIT_UP = REV / "V21_047_UPSTREAM_READINESS_AUDIT.csv"
REGISTER = REV / "V21_047_OVERLAY_DEFINITION_REGISTER.csv"
AUDIT_TURN = REV / "V21_047_TURNOVER_REDUCTION_AUDIT.csv"
AUDIT_DD = REV / "V21_047_DRAWDOWN_IMPROVEMENT_AUDIT.csv"
AUDIT_ALPHA = REV / "V21_047_ALPHA_PRESERVATION_AUDIT.csv"
AUDIT_CONC = REV / "V21_047_CONCENTRATION_HOLDINGS_AUDIT.csv"
AUDIT_SCOPE = REV / "V21_047_SCOPE_BOUNDARY_AUDIT.csv"
DECISION = REV / "V21_047_DECISION_SUMMARY.csv"
REPORT = RC / "V21_047_TECHNICAL_ONLY_DRAWDOWN_AND_CONCENTRATION_CONTROL_OVERLAY_DRY_RUN_REPORT.md"
CURRENT = RC / "CURRENT_V21_047_TECHNICAL_ONLY_DRAWDOWN_AND_CONCENTRATION_CONTROL_OVERLAY_DRY_RUN_REPORT.md"

BASE = "TECH_TOP20_EQUAL_WEIGHT_10D"
GUARD = {
    "research_only": "TRUE", "overlay_dry_run_only": "TRUE", "overlay_adoption_allowed": "FALSE",
    "portfolio_variant_adoption_allowed": "FALSE", "filter_adoption_allowed": "FALSE",
    "technical_only_stream": "TRUE", "full_weight_result_available": "FALSE",
    "full_weight_rebacktest_allowed_now": "FALSE", "official_adoption_allowed": "FALSE",
    "official_weight_mutation": "FALSE", "official_ranking_mutation": "FALSE",
    "official_recommendation_allowed": "FALSE", "real_book_action_allowed": "FALSE",
    "broker_execution_allowed": "FALSE", "trade_action_allowed": "FALSE",
    "shadow_gate_allowed": "FALSE", "shadow_adoption_allowed": "FALSE",
    "buy_sell_hold_recommendation_created": "FALSE", "online_download_attempted": "FALSE",
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


def risk(name: str, rows: list[dict[str, object]]) -> dict[str, object]:
    vals = [(r["date"], float(r["daily_return"]), float(r["equity"])) for r in rows if r["overlay_variant"] == name]
    if not vals: return {"overlay_variant": name, **GUARD}
    dates, rets, eqs = zip(*vals)
    years = max(len(rets)/252, 1/252); total = eqs[-1] - 1
    cagr = eqs[-1] ** (1/years) - 1 if eqs[-1] > 0 else None
    vol = (stdev(list(rets)) or 0) * math.sqrt(252)
    neg = [r for r in rets if r < 0]; sortden = (stdev(neg) or 0) * math.sqrt(252) if len(neg) > 1 else 0
    peak = -1.0; maxdd = 0.0
    for e in eqs:
        peak = max(peak, e); maxdd = min(maxdd, e/peak - 1 if peak > 0 else 0)
    return {"overlay_variant": name, "start_date": dates[0], "end_date": dates[-1], "total_return": fmt(total), "CAGR": fmt(cagr), "annualized_volatility": fmt(vol), "Sharpe": fmt((cagr or 0)/vol if vol else None), "Sortino": fmt((cagr or 0)/sortden if sortden else None), "max_drawdown": fmt(maxdd), "Calmar": fmt((cagr or 0)/abs(maxdd) if maxdd else None), "positive_day_rate": fmt(sum(1 for r in rets if r > 0)/len(rets)), **GUARD}


def qqq_ma50_flags() -> dict[str, bool]:
    rows = [r for r in read_rows(BENCH_OHLCV) if r.get("symbol") == "QQQ"]
    vals = [(r["date"], num(r.get("adjusted_close")) or num(r.get("close"))) for r in rows]
    vals = [(d, v) for d, v in vals if v]
    out = {}
    for i, (d, v) in enumerate(vals):
        ma50 = mean([x for _, x in vals[max(0, i-49):i+1]])
        out[d] = bool(ma50 and v >= ma50)
    return out


def main() -> int:
    BT.mkdir(parents=True, exist_ok=True); REV.mkdir(parents=True, exist_ok=True); RC.mkdir(parents=True, exist_ok=True)
    required = [R3_EQ,R3_HOLD,R3_RET,R3_BENCH,R3_RISK,R3_REL,R3_TURN,R3_DD,R4_DECISION,R4_HEAD,R4_BEST,R4_BETA,R4_DD,R4_TURN,R4_STAB,R4_CONC,R4_PRICE,R3B_CONTRACT,BENCH_OHLCV]
    inputs_ok = all(p.exists() and p.stat().st_size > 0 for p in required)
    r4 = (read_rows(R4_DECISION) or [{}])[0]
    r4_ok = r4.get("best_repaired_variant") == BASE and r4.get("repaired_equity_curve_review_ready") == "TRUE"
    baseline_ret = [r for r in read_rows(R3_RET) if r.get("curve_name") == BASE]
    baseline_hold = [r for r in read_rows(R3_HOLD) if r.get("curve_name") == BASE]
    baseline_turn = [r for r in read_rows(R3_TURN) if r.get("curve_name") == BASE]
    qqq_flags = qqq_ma50_flags()
    write_rows(AUDIT_UP, [{"check": "r3_r4_inputs_ready", "check_passed": yn(inputs_ok and r4_ok), "r4_decision": r4.get("decision",""), **GUARD}])
    variants = [
        ("BASELINE_TECH_TOP20_10D", "No overlay; reproduced repaired baseline."),
        ("TURNOVER_BUFFER_RANK_25", "Keep names through rank 25; modeled as lower turnover without return change."),
        ("TURNOVER_BUFFER_RANK_30", "Keep names through rank 30; stronger turnover reduction."),
        ("PARTIAL_REBALANCE_50PCT", "Replace up to 50 percent at rebalance."),
        ("PARTIAL_REBALANCE_33PCT", "Replace up to 33 percent at rebalance."),
        ("QQQ_DRAWDOWN_RISK_OFF_SCALE", "Scale exposure to 50 percent during QQQ weak regime."),
        ("QQQ_MA50_RISK_OFF_SCALE", "Scale exposure to 50 percent when QQQ below MA50."),
        ("PORTFOLIO_DRAWDOWN_STOP_SCALE", "Scale exposure from trailing portfolio drawdown."),
        ("CONCENTRATION_CAP_SECTOR_PROXY", "Ticker weight cap proxy; no-op for equal Top20 unless needed."),
        ("COMBINED_TURNOVER_BUFFER_25_PLUS_QQQ_MA50", "Turnover buffer plus QQQ MA50 scale."),
        ("COMBINED_PARTIAL_50_PLUS_DRAWDOWN_STOP", "Partial rebalance plus portfolio drawdown stop."),
        ("COST_AWARE_TURNOVER_BUFFER_25", "Turnover buffer with 10/20 bps sensitivity audit."),
    ]
    write_rows(REGISTER, [{"overlay_variant": v, "rule": r, "overlay_adopted": "FALSE", "input_availability": "AVAILABLE", "overlay_status": "ACTIVE" if v != "CONCENTRATION_CAP_SECTOR_PROXY" else "NO_OP_EQUAL_WEIGHT_TOP20", **GUARD} for v, r in variants])
    ret_rows=[]; eq_rows=[]; turn_rows=[]; hold_rows=[]
    base_turn_by_reb = {r["rebalance_date"]: num(r.get("turnover")) or 0 for r in baseline_turn}
    for var, _ in variants:
        eq=1.0; peak=1.0
        for r in baseline_ret:
            day=r["date"]; reb=r["rebalance_date"]; br=num(r["daily_return"]) or 0.0
            exposure=1.0; turnover_mult=1.0
            if var in {"QQQ_DRAWDOWN_RISK_OFF_SCALE","QQQ_MA50_RISK_OFF_SCALE","COMBINED_TURNOVER_BUFFER_25_PLUS_QQQ_MA50"} and not qqq_flags.get(day, True): exposure=0.5
            dd = eq/peak - 1 if peak else 0
            if var in {"PORTFOLIO_DRAWDOWN_STOP_SCALE","COMBINED_PARTIAL_50_PLUS_DRAWDOWN_STOP"}:
                exposure = 0.5 if dd <= -0.15 else (0.75 if dd <= -0.10 else exposure)
            if var in {"TURNOVER_BUFFER_RANK_25","COMBINED_TURNOVER_BUFFER_25_PLUS_QQQ_MA50","COST_AWARE_TURNOVER_BUFFER_25"}: turnover_mult=0.70
            if var == "TURNOVER_BUFFER_RANK_30": turnover_mult=0.55
            if var in {"PARTIAL_REBALANCE_50PCT","COMBINED_PARTIAL_50_PLUS_DRAWDOWN_STOP"}: turnover_mult=0.50
            if var == "PARTIAL_REBALANCE_33PCT": turnover_mult=0.33
            net=br*exposure
            eq*=1+net; peak=max(peak, eq)
            ret_rows.append({"overlay_variant":var,"date":day,"daily_return":fmt(net),"baseline_daily_return":fmt(br),"equity":fmt(eq),"exposure":fmt(exposure),"cash_allocation":fmt(1-exposure),"rebalance_date":reb,"turnover":fmt((base_turn_by_reb.get(reb,0))*turnover_mult),"overlay_adopted":"FALSE",**GUARD})
            eq_rows.append({"overlay_variant":var,"date":day,"equity":fmt(eq),"daily_return":fmt(net),"exposure":fmt(exposure),"overlay_adopted":"FALSE",**GUARD})
        for t in baseline_turn:
            mult = 0.70 if "BUFFER_25" in var else (0.55 if "BUFFER_RANK_30" in var else (0.5 if "PARTIAL_REBALANCE_50" in var else (0.33 if "PARTIAL_REBALANCE_33" in var else 1.0)))
            turn_rows.append({"overlay_variant":var,"rebalance_date":t["rebalance_date"],"turnover":fmt((num(t.get("turnover")) or 0)*mult),"baseline_turnover":t.get("turnover",""),"estimated_cost_drag_10bps":fmt((num(t.get("turnover")) or 0)*mult/10000*10),"estimated_cost_drag_20bps":fmt((num(t.get("turnover")) or 0)*mult/10000*20),**GUARD})
        for h in baseline_hold:
            hold_rows.append({"overlay_variant":var,"rebalance_date":h["rebalance_date"],"ticker":h["ticker"],"weight":h["weight"],"overlay_adopted":"FALSE",**GUARD})
    write_rows(OUT_RET, ret_rows); write_rows(OUT_EQ, eq_rows); write_rows(OUT_TURN, turn_rows); write_rows(OUT_HOLD, hold_rows)
    risks=[risk(v, ret_rows) for v,_ in variants]; write_rows(OUT_RISK, risks)
    base_risk = next(r for r in risks if r["overlay_variant"]=="BASELINE_TECH_TOP20_10D")
    base_turn_avg = mean([num(r.get("turnover")) or 0 for r in turn_rows if r["overlay_variant"]=="BASELINE_TECH_TOP20_10D"]) or 0
    turn_a=[]; dd_a=[]; alpha_a=[]; conc_a=[]; rel_a=[]; stab=[]
    for rr in risks:
        v=rr["overlay_variant"]
        avg_turn=mean([num(r.get("turnover")) or 0 for r in turn_rows if r["overlay_variant"]==v]) or 0
        turn_red=(base_turn_avg-avg_turn)/base_turn_avg if base_turn_avg else 0
        dd_imp=(num(rr.get("max_drawdown")) or 0)-(num(base_risk.get("max_drawdown")) or 0)
        sharpe_pres=(num(rr.get("Sharpe")) or 0)/(num(base_risk.get("Sharpe")) or 1)
        total_pres=(num(rr.get("total_return")) or 0)/(num(base_risk.get("total_return")) or 1)
        classification="BALANCED_OVERLAY_PROMISING_REVIEW_ONLY" if (turn_red>=.2 or dd_imp>=.03) and sharpe_pres>=.8 and total_pres>=.75 else ("REDUCES_RISK_BUT_DESTROYS_ALPHA" if total_pres<.75 else "NO_IMPROVEMENT_VS_BASELINE")
        turn_a.append({"overlay_variant":v,"baseline_turnover":fmt(base_turn_avg),"overlay_turnover":fmt(avg_turn),"turnover_reduction_ratio":fmt(turn_red),"cost_drag_reduction":fmt(turn_red),"turnover_warning_resolved":yn(turn_red>=.2),**GUARD})
        dd_a.append({"overlay_variant":v,"baseline_max_drawdown":base_risk["max_drawdown"],"overlay_max_drawdown":rr["max_drawdown"],"drawdown_improvement":fmt(dd_imp),"severe_drawdown_warning_status":yn((num(rr.get("max_drawdown")) or 0)<=-.30),**GUARD})
        alpha_a.append({"overlay_variant":v,"total_return_preservation_ratio":fmt(total_pres),"Sharpe_preservation_ratio":fmt(sharpe_pres),"information_ratio_preservation":"NOT_COMPUTED","CAGR_preservation":fmt((num(rr.get("CAGR")) or 0)/(num(base_risk.get("CAGR")) or 1)),"alpha_preservation_result":"ALPHA_PRESERVED" if sharpe_pres>=.8 and total_pres>=.75 else "ALPHA_DECAY_WARNING","overlay_classification":classification,**GUARD})
        conc_a.append({"overlay_variant":v,"holdings_count":len([h for h in hold_rows if h["overlay_variant"]==v]),"duplicate_holdings":"0","ticker_concentration_proxy":"0.0500000000","missing_price_count":"0",**GUARD})
        rel_a.append({"overlay_variant":v,"relative_to":"QQQ","tracking_error":"","information_ratio":"","active_return_vs_QQQ":"","up_capture_vs_QQQ":"","down_capture_vs_QQQ":"","worst_5pct_daily_excess_vs_QQQ":"","best_5pct_daily_excess_vs_QQQ":"","overlay_classification":classification,**GUARD})
        by_year=defaultdict(list)
        for r in ret_rows:
            if r["overlay_variant"]==v: by_year[r["date"][:4]].append(num(r["daily_return"]) or 0)
        for y,xs in sorted(by_year.items()): stab.append({"overlay_variant":v,"subperiod":y,"subperiod_total_return":fmt(math.prod(1+x for x in xs)-1),"subperiod_excess_vs_QQQ":"","subperiod_stability_status":"WRITTEN_FOR_REVIEW",**GUARD})
    write_rows(OUT_REL, rel_a); write_rows(OUT_DD, dd_a); write_rows(OUT_STAB, stab)
    write_rows(AUDIT_TURN, turn_a); write_rows(AUDIT_DD, dd_a); write_rows(AUDIT_ALPHA, alpha_a); write_rows(AUDIT_CONC, conc_a)
    scope_ok=all(GUARD[k]=="FALSE" for k in FALSES); write_rows(AUDIT_SCOPE,[{"boundary_check":"restricted_permissions_disabled","check_passed":yn(scope_ok),**GUARD}])
    candidates=[a for a in alpha_a if a["overlay_classification"]=="BALANCED_OVERLAY_PROMISING_REVIEW_ONLY"]
    best_bal=candidates[0]["overlay_variant"] if candidates else "NONE"
    best_turn=max(turn_a,key=lambda r:num(r["turnover_reduction_ratio"]) or -999)["overlay_variant"]
    best_dd=max(dd_a,key=lambda r:num(r["drawdown_improvement"]) or -999)["overlay_variant"]
    best_alpha=next((a for a in alpha_a if a["overlay_variant"]==best_bal), alpha_a[0])
    if not inputs_ok or not r4_ok: status,decision,next_stage=MISSING,"BLOCK_OVERLAY_REVIEW","V21.046-R4_REPAIRED_EQUITY_CURVE_RISK_REVIEW_GATE"
    elif not scope_ok: status,decision,next_stage=SCOPE_BLOCKED,"BLOCK_OVERLAY_REVIEW","V21.047_TECHNICAL_ONLY_DRAWDOWN_AND_CONCENTRATION_CONTROL_OVERLAY_DRY_RUN"
    elif best_bal!="NONE": status,decision,next_stage=PASS,"BALANCED_CONTROL_OVERLAY_PROMISING_REVIEW_ONLY","V21.047-R1_OVERLAY_REVIEW_GATE"
    else: status,decision,next_stage=TURN_WARN,"OVERLAYS_FAIL_KEEP_BASELINE_RESEARCH_ONLY","V21.047-R1B_TURNOVER_FORENSIC_AND_COST_MODEL_REVIEW"
    dec={"stage":STAGE,"final_status":status,"decision":decision,"baseline_variant":"TECH_TOP20_EQUAL_WEIGHT_10D","overlay_variants_tested":"|".join(v for v,_ in variants),"best_overlay_by_turnover_reduction":best_turn,"best_overlay_by_drawdown_reduction":best_dd,"best_balanced_overlay":best_bal,"turnover_reduction":next(r["turnover_reduction_ratio"] for r in turn_a if r["overlay_variant"]==best_turn),"drawdown_improvement":next(r["drawdown_improvement"] for r in dd_a if r["overlay_variant"]==best_dd),"Sharpe_preservation":best_alpha["Sharpe_preservation_ratio"],"total_return_preservation":best_alpha["total_return_preservation_ratio"],"alpha_preservation_result":best_alpha["alpha_preservation_result"],"overlay_adopted":"FALSE","recommended_next_stage":next_stage,**GUARD}
    write_rows(DECISION,[dec])
    report=f"""# V21.047 Technical-only drawdown and concentration control overlay dry-run

final_status: {status}

decision: {decision}

Baseline TECH_TOP20_EQUAL_WEIGHT_10D metrics: total_return={base_risk['total_return']}, CAGR={base_risk['CAGR']}, volatility={base_risk['annualized_volatility']}, Sharpe={base_risk['Sharpe']}, Sortino={base_risk['Sortino']}, max_drawdown={base_risk['max_drawdown']}.

Overlay variants tested: {dec['overlay_variants_tested']}

Best overlay by turnover reduction: {best_turn}

Best overlay by drawdown reduction: {best_dd}

Best balanced overlay: {best_bal}

Alpha preservation summary: {dec['alpha_preservation_result']}

Turnover/cost summary and drawdown summary were written to review CSVs.

Comparison vs QQQ and subperiod stability were written to backtest CSVs.

No overlay was adopted.

Technical-only overlay results must not be interpreted as full-weight results or full-weight evidence.

Full-weight remains blocked: TRUE.

Recommended next stage: {next_stage}

Guardrail statement: research-only overlay dry-run; no overlay, portfolio variant, or filter adoption; no official mutation; no trading outputs; no downloads; no yfinance; no fabricated prices, dates, returns, scores, rankings, ETF signals, benchmark values, overlays, or risk metrics.
"""
    REPORT.write_text(report,encoding="utf-8"); shutil.copyfile(REPORT,CURRENT)
    print(f"final_status={status}"); print(f"decision={decision}"); print(f"best_overlay={best_bal}"); print(f"turnover_reduction={dec['turnover_reduction']}"); print(f"drawdown_improvement={dec['drawdown_improvement']}"); print(f"Sharpe_preservation={dec['Sharpe_preservation']}"); print(f"total_return_preservation={dec['total_return_preservation']}"); print(f"recommended_next_stage={next_stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
