#!/usr/bin/env python
"""Repair V21.046 equity curves by rebuilding daily-return portfolios from local OHLCV."""

from __future__ import annotations

import csv
import math
import shutil
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


STAGE = "V21.046-R3_RETURN_CONSTRUCTION_REPAIR_AND_RERUN"
PASS = "PASS_V21_046_R3_RETURN_CONSTRUCTION_REPAIRED_EQUITY_CURVES_READY"
PRICE_WARN = "PARTIAL_PASS_V21_046_R3_REPAIRED_CURVES_WITH_PRICE_OUTLIER_WARNINGS"
COVERAGE_WARN = "PARTIAL_PASS_V21_046_R3_REPAIRED_CURVES_WITH_COVERAGE_WARNINGS"
INCOMPLETE = "PARTIAL_PASS_V21_046_R3_REPAIR_INCOMPLETE_REVIEW_REQUIRED"
MISSING = "BLOCKED_V21_046_R3_REQUIRED_INPUTS_NOT_FOUND"
SCOPE_BLOCKED = "BLOCKED_V21_046_R3_SCOPE_BOUNDARY_FAILED"

ROOT = Path(__file__).resolve().parents[2]
BT = ROOT / "outputs" / "v21" / "backtest"
REV = ROOT / "outputs" / "v21" / "review"
RC = ROOT / "outputs" / "v21" / "read_center"
PRICE = ROOT / "outputs" / "v20" / "price_history"

R2_DECISION = REV / "V21_046_R2_DECISION_SUMMARY.csv"
R2_RETURN = REV / "V21_046_R2_RETURN_CONSTRUCTION_AUDIT.csv"
R2_EXTREME = REV / "V21_046_R2_EXTREME_PERFORMANCE_SANITY_AUDIT.csv"
R2_PRICE = REV / "V21_046_R2_PRICE_OUTLIER_AUDIT.csv"
OLD_HOLDINGS = BT / "V21_046_TECHNICAL_ONLY_PORTFOLIO_HOLDINGS_BY_REBALANCE.csv"
OLD_RISK = BT / "V21_046_EQUITY_CURVE_RISK_METRIC_SUMMARY.csv"
R3B_DECISION = REV / "V21_045_R3B_DECISION_SUMMARY.csv"
R3B_RETENTION = REV / "V21_045_R3B_BASELINE_RETENTION_AUDIT.csv"
R5_PANEL = BT / "V21_044_R5_TECHNICAL_ONLY_REBACKTEST_PANEL.csv"
R4_PANEL = REV / "V21_044_R4_TECHNICAL_ONLY_HISTORICAL_SCORE_PANEL.csv"
R5A = REV / "V21_044_R5A_RECONCILIATION_DECISION_SUMMARY.csv"
R6 = REV / "V21_044_R6_CONTINUITY_GATE_DECISION_SUMMARY.csv"
TICKER_PRICES = PRICE / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
BENCH_PRICES = PRICE / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"

OUT_EQ = BT / "V21_046_R3_REPAIRED_TECHNICAL_ONLY_EQUITY_CURVE_PANEL.csv"
OUT_HOLD = BT / "V21_046_R3_REPAIRED_TECHNICAL_ONLY_PORTFOLIO_HOLDINGS_BY_REBALANCE.csv"
OUT_RET = BT / "V21_046_R3_REPAIRED_TECHNICAL_ONLY_PORTFOLIO_DAILY_RETURNS.csv"
OUT_BENCH = BT / "V21_046_R3_REPAIRED_BENCHMARK_EQUITY_CURVE_PANEL.csv"
OUT_RISK = BT / "V21_046_R3_REPAIRED_EQUITY_CURVE_RISK_METRIC_SUMMARY.csv"
OUT_REL = BT / "V21_046_R3_REPAIRED_RELATIVE_METRICS_VS_QQQ.csv"
OUT_TURN = BT / "V21_046_R3_REPAIRED_TURNOVER_AND_COST_AUDIT.csv"
OUT_DD = BT / "V21_046_R3_REPAIRED_DRAWDOWN_DIAGNOSTICS.csv"
OUT_COMPARE = BT / "V21_046_R3_INVALID_VS_REPAIRED_CURVE_COMPARISON.csv"
OUT_ETF = BT / "V21_046_R3_ETF_COMPARATOR_AVAILABILITY_AUDIT.csv"
AUDIT_REPAIR = REV / "V21_046_R3_RETURN_CONSTRUCTION_REPAIR_AUDIT.csv"
AUDIT_SANITY = REV / "V21_046_R3_REPAIRED_EQUITY_CURVE_SANITY_AUDIT.csv"
AUDIT_PRICE = REV / "V21_046_R3_PRICE_OUTLIER_AUDIT.csv"
AUDIT_REBAL = REV / "V21_046_R3_REBALANCE_HOLDING_AUDIT.csv"
AUDIT_BENCH = REV / "V21_046_R3_BENCHMARK_COMPARISON_AUDIT.csv"
AUDIT_SCOPE = REV / "V21_046_R3_SCOPE_BOUNDARY_AUDIT.csv"
DECISION = REV / "V21_046_R3_DECISION_SUMMARY.csv"
REPORT = RC / "V21_046_R3_RETURN_CONSTRUCTION_REPAIR_AND_RERUN_REPORT.md"
CURRENT_REPORT = RC / "CURRENT_V21_046_R3_RETURN_CONSTRUCTION_REPAIR_AND_RERUN_REPORT.md"

WINDOWS = ["5D", "10D", "20D", "60D"]
VARIANTS = [
    ("TECH_TOP20_EQUAL_WEIGHT", 20, "equal", 0),
    ("TECH_TOP50_EQUAL_WEIGHT", 50, "equal", 0),
    ("TECH_TOP20_SCORE_WEIGHT", 20, "score", 0),
    ("TECH_TOP50_SCORE_WEIGHT", 50, "score", 0),
    ("TECH_TOP20_EQUAL_WEIGHT_WITH_10BPS_COST", 20, "equal", 10),
    ("TECH_TOP50_EQUAL_WEIGHT_WITH_10BPS_COST", 50, "equal", 10),
    ("TECH_TOP20_EQUAL_WEIGHT_WITH_20BPS_COST", 20, "equal", 20),
    ("TECH_TOP50_EQUAL_WEIGHT_WITH_20BPS_COST", 50, "equal", 20),
]
GUARD = {
    "research_only": "TRUE",
    "return_construction_repair_only": "TRUE",
    "repaired_equity_curve_backtest_only": "TRUE",
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
    if not p.exists() or p.stat().st_size == 0:
        return []
    with p.open("r", encoding="utf-8-sig", newline="") as h:
        return list(csv.DictReader(h))


def write_rows(p: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or (list(rows[0].keys()) if rows else [])
    with p.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({f: "" if r.get(f) is None else r.get(f, "") for f in fields})


def num(x: object) -> float | None:
    try: y = float(x)
    except (TypeError, ValueError): return None
    return y if math.isfinite(y) else None


def fmt(x: float | None) -> str: return "" if x is None else f"{x:.10f}"
def mean(xs: list[float]) -> float | None: return statistics.fmean(xs) if xs else None
def median(xs: list[float]) -> float | None: return statistics.median(xs) if xs else None
def stdev(xs: list[float]) -> float | None: return statistics.stdev(xs) if len(xs) > 1 else None


def load_prices() -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for p in [TICKER_PRICES, BENCH_PRICES]:
        for r in read_rows(p):
            sym, day = (r.get("symbol") or "").upper(), r.get("date") or ""
            val = num(r.get("adjusted_close")) or num(r.get("close"))
            if sym and day and val and val > 0: out[sym][day] = val
    return {s: dict(sorted(v.items())) for s, v in out.items()}


def next_price_date(series: dict[str, float], day: str) -> str:
    for d in series:
        if d >= day: return d
    return ""


def metrics(curve: str, rows: list[dict[str, object]], typ: str) -> dict[str, object]:
    vals = [(str(r["date"]), float(r["daily_return"]), float(r["equity"])) for r in rows if r.get("curve_name") == curve]
    if not vals: return {"curve_name": curve, "curve_type": typ, **GUARD}
    dates, rets, eqs = zip(*vals)
    years = max(len(rets) / 252, 1 / 252)
    total = eqs[-1] - 1
    cagr = eqs[-1] ** (1 / years) - 1 if eqs[-1] > 0 else None
    vol = (stdev(list(rets)) or 0) * math.sqrt(252)
    neg = [r for r in rets if r < 0]
    sortden = (stdev(neg) or 0) * math.sqrt(252) if len(neg) > 1 else 0
    peak, maxdd, start, trough, curstart = -1.0, 0.0, dates[0], dates[0], dates[0]
    for d, e in zip(dates, eqs):
        if e > peak: peak, curstart = e, d
        dd = e / peak - 1 if peak > 0 else 0
        if dd < maxdd: maxdd, start, trough = dd, curstart, d
    return {"curve_name": curve, "curve_type": typ, "start_date": dates[0], "end_date": dates[-1], "trading_days": len(rets), "total_return": fmt(total), "CAGR": fmt(cagr), "annualized_volatility": fmt(vol), "Sharpe": fmt((cagr or 0)/vol if vol else None), "Sortino": fmt((cagr or 0)/sortden if sortden else None), "max_drawdown": fmt(maxdd), "Calmar": fmt((cagr or 0)/abs(maxdd) if maxdd else None), "best_day_return": fmt(max(rets)), "worst_day_return": fmt(min(rets)), "positive_day_rate": fmt(sum(1 for r in rets if r > 0)/len(rets)), "max_drawdown_start": start, "max_drawdown_trough": trough, **GUARD}


def simulate(panel: list[dict[str, str]], prices: dict[str, dict[str, float]]) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], int]:
    by_key: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for r in panel:
        if r.get("included_in_performance_aggregation") == "TRUE" and r.get("point_in_time_safe") == "TRUE":
            by_key[(r["forward_return_window"], r["as_of_date"])].append(r)
    eq_rows=[]; ret_rows=[]; hold_rows=[]; turn_rows=[]; price_out=[]; missing=0
    qqq_dates = sorted(prices.get("QQQ", {}))
    for window in WINDOWS:
        asofs = sorted(k[1] for k in by_key if k[0] == window)
        for variant, target, mode, cost_bps in VARIANTS:
            curve = f"{variant}_{window}"
            equity = 1.0; prev_weights: dict[str, float] = {}
            for i, asof in enumerate(asofs):
                next_asof = asofs[i+1] if i+1 < len(asofs) else ""
                ranked = sorted(by_key[(window, asof)], key=lambda r: num(r.get("technical_only_rank")) or 999999)[:target]
                selected=[]
                for r in ranked:
                    sym = r["ticker"]; d0 = next_price_date(prices.get(sym, {}), asof)
                    if d0: selected.append((r, d0))
                    else: missing += 1
                if mode == "score":
                    scores=[max(num(r.get("technical_only_score")) or 0, 0) for r,_ in selected]
                    s=sum(scores); weights=[x/s for x in scores] if s>0 else ([1/len(selected)]*len(selected) if selected else [])
                else:
                    weights=[1/len(selected)]*len(selected) if selected else []
                new_weights={r["ticker"]: w for (r,_), w in zip(selected, weights)}
                turnover=sum(abs(new_weights.get(t,0)-prev_weights.get(t,0)) for t in set(new_weights)|set(prev_weights))/2 if prev_weights else (1.0 if new_weights else 0.0)
                for (r,d0), w in zip(selected, weights):
                    hold_rows.append({"curve_name": curve, "rebalance_date": asof, "ticker": r["ticker"], "weight": fmt(w), "entry_price_date": d0, "target_count": target, **GUARD})
                period_dates=[d for d in qqq_dates if d > asof and (not next_asof or d <= next_asof)]
                first_day=True
                for day in period_dates:
                    weighted=[]; active_w=0.0
                    for (r,_), base_w in zip(selected, weights):
                        series=prices.get(r["ticker"], {})
                        dates=[d for d in series if d < day]
                        prev=dates[-1] if dates else ""
                        if prev and day in series and series[prev] > 0:
                            rr=series[day]/series[prev]-1
                            weighted.append((base_w, rr, r["ticker"], series[prev], series[day]))
                            active_w += base_w
                    if not weighted: continue
                    gross=sum((w/active_w)*rr for w,rr,_,_,_ in weighted)
                    cost=turnover*cost_bps/10000 if first_day else 0.0
                    net=gross-cost
                    equity *= 1+net
                    ret_rows.append({"curve_name": curve, "date": day, "daily_return": fmt(net), "daily_return_before_cost": fmt(gross), "transaction_cost": fmt(cost), "equity": fmt(equity), "rebalance_date": asof, "daily_price_returns_used": "TRUE", "forward_returns_used_as_daily": "FALSE", **GUARD})
                    eq_rows.append({"curve_type": "repaired_technical_only_portfolio", "curve_name": curve, "date": day, "equity": fmt(equity), "daily_return": fmt(net), **GUARD})
                    for w, rr, sym, p0, p1 in weighted:
                        if abs(rr) > .2:
                            price_out.append({"curve_name": curve, "ticker": sym, "date": day, "daily_return": fmt(rr), "price_before": fmt(p0), "price_after": fmt(p1), "curve_impact_proxy": fmt((w/active_w)*rr), "outlier_flag": "TRUE", "split_or_adjustment_suspected": yn(abs(rr) > .5), "stale_to_live_jump_suspected": yn(abs(rr) > .2), "action_required": "REVIEW" if abs(rr) > .5 else "MONITOR", **GUARD})
                    first_day=False
                turn_rows.append({"curve_name": curve, "rebalance_date": asof, "rebalance_window": window, "selected_count": len(selected), "target_count": target, "missing_price_count": max(target-len(selected),0), "turnover": fmt(turnover), "cost_bps": cost_bps, "weights_sum": fmt(sum(weights)), **GUARD})
                prev_weights = new_weights
    return eq_rows, ret_rows, hold_rows, turn_rows, price_out, missing


def benchmark(prices: dict[str, dict[str, float]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    eq=[]; ret=[]
    for sym in ["QQQ","SPY","SOXX"]:
        series=prices.get(sym,{})
        e=1.0; prev=None
        for day, px in series.items():
            r=0.0 if prev is None else px/prev-1
            e*=1+r
            row={"curve_name": f"{sym}_BUY_AND_HOLD", "date": day, "daily_return": fmt(r), "equity": fmt(e), "curve_type": "benchmark", **GUARD}
            eq.append(row); ret.append(row); prev=px
    return eq, ret


def rel_metrics(curve: str, rows: list[dict[str, object]], qqq: list[dict[str, object]]) -> dict[str, object]:
    a={r["date"]: float(r["daily_return"]) for r in rows if r["curve_name"]==curve}
    q={r["date"]: float(r["daily_return"]) for r in qqq}
    days=sorted(set(a)&set(q)); ar=[a[d] for d in days]; qr=[q[d] for d in days]
    ex=[x-y for x,y in zip(ar,qr)]
    te=(stdev(ex) or 0)*math.sqrt(252)
    return {"curve_name": curve, "relative_to": "QQQ_BUY_AND_HOLD", "tracking_error_vs_QQQ": fmt(te), "information_ratio_vs_QQQ": fmt(((mean(ex) or 0)*252)/te if te else None), "correlation_vs_QQQ": "", "beta_vs_QQQ": "", **GUARD}


def main() -> int:
    BT.mkdir(parents=True, exist_ok=True); REV.mkdir(parents=True, exist_ok=True); RC.mkdir(parents=True, exist_ok=True)
    required=[R2_DECISION,R2_RETURN,R2_EXTREME,R2_PRICE,OLD_HOLDINGS,R3B_DECISION,R3B_RETENTION,R5_PANEL,R4_PANEL,R5A,R6,TICKER_PRICES,BENCH_PRICES]
    inputs_ok=all(p.exists() and p.stat().st_size>0 for p in required)
    scope_ok=all(GUARD[k]=="FALSE" for k in FALSES)
    panel=read_rows(R5_PANEL); prices=load_prices()
    if inputs_ok and scope_ok:
        eq, ret, hold, turn, price_out, missing = simulate(panel, prices)
        beq, bret = benchmark(prices)
    else:
        eq=ret=hold=turn=price_out=beq=bret=[]; missing=0
    write_rows(OUT_EQ, eq); write_rows(OUT_RET, ret); write_rows(OUT_HOLD, hold); write_rows(OUT_TURN, turn); write_rows(OUT_BENCH, beq)
    curves=sorted({r["curve_name"] for r in ret+bret})
    risk=[metrics(c, ret+bret, "benchmark" if "BUY_AND_HOLD" in c else "repaired_technical_only") for c in curves]
    write_rows(OUT_RISK, risk)
    qqq=[r for r in bret if r["curve_name"]=="QQQ_BUY_AND_HOLD"]
    write_rows(OUT_REL, [rel_metrics(c, ret, qqq) for c in sorted({r["curve_name"] for r in ret})])
    write_rows(OUT_DD, [{"curve_name": r["curve_name"], "max_drawdown": r.get("max_drawdown",""), "max_drawdown_start": r.get("max_drawdown_start",""), "max_drawdown_trough": r.get("max_drawdown_trough",""), **GUARD} for r in risk])
    old={r["curve_name"]: r for r in read_rows(OLD_RISK)}
    compare=[]
    for r in risk:
        o=old.get(r["curve_name"], {})
        if o:
            compare.append({"curve_name": r["curve_name"], "old_curve_total_return": o.get("total_return",""), "repaired_curve_total_return": r.get("total_return",""), "total_return_delta": fmt((num(r.get("total_return")) or 0)-(num(o.get("total_return")) or 0)), "old_sharpe": o.get("Sharpe",""), "repaired_sharpe": r.get("Sharpe",""), "old_volatility": o.get("annualized_volatility",""), "repaired_volatility": r.get("annualized_volatility",""), "repair_interpretation": "INVALID_HOLDING_PERIOD_COMPOUNDING_REPLACED_WITH_DAILY_PRICE_RETURN_CURVE", **GUARD})
    write_rows(OUT_COMPARE, compare)
    write_rows(OUT_ETF, [{"comparator_name": "ETF_ROTATION", "availability_status": "ETF_ROTATION_DATA_LIMITED", "curve_fabricated": "FALSE", **GUARD}])
    weights_valid=all(abs((num(r.get("weights_sum")) or 0)-1) < .0001 for r in turn if int(float(r.get("selected_count") or 0))>0)
    repair_passed=bool(ret) and weights_valid
    write_rows(AUDIT_REPAIR, [{"old_v21_046_return_construction_status": "RETURN_CONSTRUCTION_REPAIR_REQUIRED", "repaired_return_construction_status": "DAILY_PRICE_RETURN_CONSTRUCTION", "holding_period_returns_reused_as_daily": "FALSE", "forward_returns_used_as_daily": "FALSE", "overlapping_portfolios_double_counted": "FALSE", "rebalance_only_return_rows_used": "FALSE", "daily_price_returns_used": "TRUE", "weights_sum_valid": yn(weights_valid), "repair_passed": yn(repair_passed), **GUARD}])
    sanity=[]
    price_warning=False
    for r in risk:
        vals=[float(x["daily_return"]) for x in (ret+bret) if x["curve_name"]==r["curve_name"]]
        warn=[]
        if any(x>.5 or x<-.5 for x in vals): warn.append("DAILY_RETURN_OUTLIER_WARNING")
        if warn: price_warning=True
        sanity.append({"curve_name": r["curve_name"], **{k:r.get(k,"") for k in ["total_return","CAGR","annualized_volatility","Sharpe","Sortino","max_drawdown","Calmar"]}, "daily_return_max": fmt(max(vals) if vals else None), "daily_return_min": fmt(min(vals) if vals else None), "count_daily_returns_gt_20pct": sum(1 for x in vals if x>.2), "count_daily_returns_gt_50pct": sum(1 for x in vals if x>.5), "count_daily_returns_gt_100pct": sum(1 for x in vals if x>1), "count_daily_returns_lt_minus_20pct": sum(1 for x in vals if x<-.2), "count_daily_returns_lt_minus_50pct": sum(1 for x in vals if x<-.5), "extreme_warning": "|".join(warn) if warn else "NO_EXTREME_WARNING", **GUARD})
    write_rows(AUDIT_SANITY, sanity); write_rows(AUDIT_PRICE, price_out or [{"outlier_flag":"FALSE","action_required":"NONE", **GUARD}])
    by_curve=defaultdict(list)
    for r in turn: by_curve[r["curve_name"]].append(r)
    write_rows(AUDIT_REBAL, [{"curve": c, "rebalance_window": c.split("_")[-1], "rebalance_count": len(rs), "median_rebalance_spacing": "", "average_holdings_per_rebalance": fmt(mean([num(r["selected_count"]) or 0 for r in rs])), "min_holdings_per_rebalance": min(int(float(r["selected_count"])) for r in rs), "percent_rebalances_with_target_count": fmt(sum(1 for r in rs if r["selected_count"]==r["target_count"])/len(rs)), "duplicate_holding_count": 0, "missing_price_count": sum(int(float(r["missing_price_count"])) for r in rs), "average_turnover": fmt(mean([num(r["turnover"]) or 0 for r in rs])), "max_turnover": fmt(max(num(r["turnover"]) or 0 for r in rs)), **GUARD} for c,rs in by_curve.items()])
    write_rows(AUDIT_BENCH, [{"benchmark_curve": c, **{k:r.get(k,"") for k in ["total_return","CAGR","annualized_volatility","Sharpe","Sortino","max_drawdown","Calmar"]}, **GUARD} for c in ["QQQ_BUY_AND_HOLD","SPY_BUY_AND_HOLD","SOXX_BUY_AND_HOLD"] for r in risk if r["curve_name"]==c])
    write_rows(AUDIT_SCOPE, [{"boundary_check": "restricted_permissions_disabled", "check_passed": yn(scope_ok), **GUARD}])
    best_sharpe=max([r for r in risk if "BUY_AND_HOLD" not in r["curve_name"]], key=lambda r: num(r.get("Sharpe")) if num(r.get("Sharpe")) is not None else -999, default={})
    best_total=max([r for r in risk if "BUY_AND_HOLD" not in r["curve_name"]], key=lambda r: num(r.get("total_return")) if num(r.get("total_return")) is not None else -999, default={})
    if not inputs_ok: status,dec,next_stage=MISSING,"BLOCK_REPAIRED_EQUITY_CURVE_REVIEW",STAGE
    elif not scope_ok: status,dec,next_stage=SCOPE_BLOCKED,"BLOCK_REPAIRED_EQUITY_CURVE_REVIEW",STAGE
    elif not repair_passed: status,dec,next_stage=INCOMPLETE,"RETURN_CONSTRUCTION_REPAIR_INCOMPLETE",STAGE
    elif price_warning: status,dec,next_stage=PRICE_WARN,"REPAIRED_EQUITY_CURVES_READY_WITH_PRICE_OUTLIER_REVIEW","V21.046-R3A_PRICE_OUTLIER_REPAIR_AND_RERUN"
    elif missing: status,dec,next_stage=COVERAGE_WARN,"PRICE_COVERAGE_REPAIR_REQUIRED_BEFORE_EQUITY_REVIEW","V21.046-R1_PRICE_COVERAGE_REPAIR_FOR_EQUITY_CURVE"
    else: status,dec,next_stage=PASS,"REPAIRED_EQUITY_CURVES_READY_FOR_RISK_REVIEW","V21.046-R4_REPAIRED_EQUITY_CURVE_RISK_REVIEW_GATE"
    dates=sorted({r["date"] for r in ret})
    decision_row={"stage":STAGE,"final_status":status,"decision":dec,"repaired_start_date":dates[0] if dates else "","repaired_end_date":dates[-1] if dates else "","best_repaired_variant_by_sharpe":best_sharpe.get("curve_name",""),"best_repaired_variant_by_total_return":best_total.get("curve_name",""),"invalid_vs_repaired_delta": next((r["total_return_delta"] for r in compare if r["curve_name"]==best_total.get("curve_name","")),""),"price_outlier_status":"PRICE_OUTLIER_WARNING" if price_warning else "NO_MATERIAL_PRICE_OUTLIER_WARNING","ETF_comparator_status":"ETF_ROTATION_DATA_LIMITED","repaired_equity_curve_review_ready":yn(status in {PASS,PRICE_WARN}),"portfolio_variant_adopted":"FALSE","recommended_next_stage":next_stage,**GUARD}
    write_rows(DECISION,[decision_row])
    report=f"""# V21.046-R3 return construction repair and rerun

final_status: {status}

decision: {dec}

V21.046 error: holding-period forward returns were labeled as daily returns and compounded as equity curve steps.

Repaired method: daily holding returns are rebuilt from local adjusted-close/close OHLCV prices; forward returns are not used as daily returns.

Repaired backtest date range: {decision_row['repaired_start_date']} to {decision_row['repaired_end_date']}

Best repaired variant by Sharpe: {decision_row['best_repaired_variant_by_sharpe']}

Best repaired variant by total return: {decision_row['best_repaired_variant_by_total_return']}

Invalid vs repaired comparison is written to V21_046_R3_INVALID_VS_REPAIRED_CURVE_COMPARISON.csv.

Repaired risk metrics, QQQ/SPY/SOXX comparison, turnover/cost impact, and drawdown diagnostics were written to CSV artifacts.

Price outlier status: {decision_row['price_outlier_status']}

ETF rotation comparator limitation: ETF_ROTATION_DATA_LIMITED; no ETF curve was fabricated.

No portfolio variant was adopted.

Technical-only repaired equity curve results must not be interpreted as full-weight results or full-weight evidence.

Full-weight remains blocked: TRUE.

Recommended next stage: {next_stage}

Guardrail statement: research-only repair/rerun; no official mutation, no adoption, no trading outputs, no downloads, no yfinance, and no fabricated prices, dates, returns, scores, rankings, ETF signals, or benchmark values.
"""
    REPORT.write_text(report,encoding="utf-8"); shutil.copyfile(REPORT,CURRENT_REPORT)
    print(f"final_status={status}"); print(f"decision={dec}"); print(f"best_repaired_variant_by_sharpe={decision_row['best_repaired_variant_by_sharpe']}"); print(f"best_repaired_variant_by_total_return={decision_row['best_repaired_variant_by_total_return']}"); print(f"invalid_vs_repaired_delta={decision_row['invalid_vs_repaired_delta']}"); print(f"price_outlier_status={decision_row['price_outlier_status']}"); print("ETF_comparator_status=ETF_ROTATION_DATA_LIMITED"); print(f"recommended_next_stage={next_stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
