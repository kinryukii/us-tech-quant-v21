#!/usr/bin/env python
"""Research-only Technical-only equity curve and risk metric backtest."""

from __future__ import annotations

import csv
import math
import shutil
import statistics
from collections import defaultdict
from pathlib import Path


STAGE = "V21.046_TECHNICAL_ONLY_CONTINUOUS_EQUITY_CURVE_AND_RISK_METRIC_BACKTEST"
PASS_STATUS = "PASS_V21_046_EQUITY_CURVE_RISK_BACKTEST_READY"
ETF_LIMITED_STATUS = "PARTIAL_PASS_V21_046_EQUITY_CURVE_READY_ETF_COMPARATOR_DATA_LIMITED"
PRICE_WARN_STATUS = "PARTIAL_PASS_V21_046_RISK_BACKTEST_WITH_PRICE_MISSING_WARNINGS"
PANEL_BLOCKED = "BLOCKED_V21_046_TECHNICAL_PANEL_NOT_FOUND"
PRICE_BLOCKED = "BLOCKED_V21_046_PRICE_SOURCE_NOT_FOUND"
SCOPE_BLOCKED = "BLOCKED_V21_046_SCOPE_BOUNDARY_FAILED"

ROOT = Path(__file__).resolve().parents[2]
BACKTEST = ROOT / "outputs" / "v21" / "backtest"
REVIEW = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"
PRICE_DIR = ROOT / "outputs" / "v20" / "price_history"
V20_CONS = ROOT / "outputs" / "v20" / "consolidation"
V20_READ = ROOT / "outputs" / "v20" / "read_center"

R3B_DECISION = REVIEW / "V21_045_R3B_DECISION_SUMMARY.csv"
R3B_RETENTION = REVIEW / "V21_045_R3B_BASELINE_RETENTION_AUDIT.csv"
R3B_CONTRACT = REVIEW / "V21_045_R3B_DOWNSIDE_MONITOR_CONTRACT.csv"
R5_PANEL = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_REBACKTEST_PANEL.csv"
R5_SUMMARY = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_VARIANT_WINDOW_SUMMARY.csv"
R5_QQQ = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_QQQ_BENCHMARK_COMPARISON.csv"
R5A = REVIEW / "V21_044_R5A_RECONCILIATION_DECISION_SUMMARY.csv"
R6 = REVIEW / "V21_044_R6_CONTINUITY_GATE_DECISION_SUMMARY.csv"
R4_PANEL = REVIEW / "V21_044_R4_TECHNICAL_ONLY_HISTORICAL_SCORE_PANEL.csv"
TICKER_PRICES = PRICE_DIR / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
BENCH_PRICES = PRICE_DIR / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"

EQUITY_PANEL = BACKTEST / "V21_046_TECHNICAL_ONLY_EQUITY_CURVE_PANEL.csv"
HOLDINGS = BACKTEST / "V21_046_TECHNICAL_ONLY_PORTFOLIO_HOLDINGS_BY_REBALANCE.csv"
DAILY_RETURNS = BACKTEST / "V21_046_TECHNICAL_ONLY_PORTFOLIO_DAILY_RETURNS.csv"
BENCH_PANEL = BACKTEST / "V21_046_BENCHMARK_EQUITY_CURVE_PANEL.csv"
ETF_PANEL = BACKTEST / "V21_046_ETF_ROTATION_COMPARATOR_PANEL.csv"
RISK_SUMMARY = BACKTEST / "V21_046_EQUITY_CURVE_RISK_METRIC_SUMMARY.csv"
RELATIVE = BACKTEST / "V21_046_RELATIVE_METRICS_VS_QQQ.csv"
TURNOVER = BACKTEST / "V21_046_TURNOVER_AND_COST_AUDIT.csv"
DD = BACKTEST / "V21_046_DRAWDOWN_DIAGNOSTICS.csv"
PRICE_AUDIT = BACKTEST / "V21_046_PRICE_COVERAGE_AUDIT.csv"
ETF_AUDIT = BACKTEST / "V21_046_ETF_COMPARATOR_AVAILABILITY_AUDIT.csv"
DECISION = REVIEW / "V21_046_EQUITY_CURVE_BACKTEST_DECISION_SUMMARY.csv"
SCOPE = REVIEW / "V21_046_SCOPE_BOUNDARY_AUDIT.csv"
READINESS = REVIEW / "V21_046_READINESS_FOR_NEXT_REVIEW.csv"
REPORT = READ_CENTER / "V21_046_TECHNICAL_ONLY_CONTINUOUS_EQUITY_CURVE_AND_RISK_METRIC_BACKTEST_REPORT.md"
CURRENT_REPORT = READ_CENTER / "CURRENT_V21_046_TECHNICAL_ONLY_CONTINUOUS_EQUITY_CURVE_AND_RISK_METRIC_BACKTEST_REPORT.md"

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
GUARDRAILS = {
    "research_only": "TRUE",
    "equity_curve_backtest_only": "TRUE",
    "technical_only_stream": "TRUE",
    "filter_adoption_allowed": "FALSE",
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
FALSE_GUARDRAILS = [k for k, v in GUARDRAILS.items() if v == "FALSE"]


def yn(v: bool) -> str:
    return "TRUE" if v else "FALSE"


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as h:
        return list(csv.DictReader(h))


def write_rows(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or (list(rows[0].keys()) if rows else [])
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({f: "" if r.get(f) is None else r.get(f, "") for f in fields})


def num(x: object) -> float | None:
    try:
        y = float(x)
    except (TypeError, ValueError):
        return None
    return y if math.isfinite(y) else None


def fmt(x: float | None) -> str:
    return "" if x is None else f"{x:.10f}"


def mean(xs: list[float]) -> float | None:
    return statistics.fmean(xs) if xs else None


def median(xs: list[float]) -> float | None:
    return statistics.median(xs) if xs else None


def stdev(xs: list[float]) -> float | None:
    return statistics.stdev(xs) if len(xs) > 1 else None


def pctile(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(max(int((len(xs) - 1) * q), 0), len(xs) - 1)]


def load_prices() -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for p in [TICKER_PRICES, BENCH_PRICES]:
        for r in read_rows(p):
            sym = (r.get("symbol") or "").upper()
            day = r.get("date") or ""
            val = num(r.get("adjusted_close")) or num(r.get("close"))
            if sym and day and val is not None:
                out[sym][day] = val
    return {k: dict(sorted(v.items())) for k, v in out.items()}


def benchmark_curve(sym: str, prices: dict[str, dict[str, float]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    series = prices.get(sym, {})
    rows = []
    rets = []
    prev = None
    eq = 1.0
    first = None
    for day, px in series.items():
        if prev is None:
            ret = 0.0
            first = px
        else:
            ret = px / prev - 1.0
            eq *= 1.0 + ret
        rows.append({"curve_type": "benchmark", "curve_name": f"{sym}_BUY_AND_HOLD", "date": day, "equity": fmt(eq), "daily_return": fmt(ret), **GUARDRAILS})
        rets.append({"curve_name": f"{sym}_BUY_AND_HOLD", "date": day, "daily_return": ret, "equity": eq})
        prev = px
    return rows, rets


def simulate(panel: list[dict[str, str]]) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    by_key: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for r in panel:
        if r.get("included_in_performance_aggregation") == "TRUE" and r.get("point_in_time_safe") == "TRUE":
            by_key[(r["forward_return_window"], r["as_of_date"])].append(r)
    eq_rows, ret_rows, holding_rows, turnover_rows = [], [], [], []
    for window in WINDOWS:
        asofs = sorted({k[1] for k in by_key if k[0] == window})
        for variant, n, weighting, cost_bps in VARIANTS:
            eq = 1.0
            prev_holdings: set[str] = set()
            turnovers = []
            for asof in asofs:
                rows = sorted(by_key[(window, asof)], key=lambda r: num(r.get("technical_only_rank")) or 999999)[:n]
                valid = [r for r in rows if num(r.get("realized_forward_return")) is not None and num(r.get("benchmark_forward_return")) is not None]
                if weighting == "score":
                    scores = [max(num(r.get("technical_only_score")) or 0.0, 0.0) for r in valid]
                    total_score = sum(scores)
                    weights = [s / total_score for s in scores] if total_score > 0 else ([1 / len(valid)] * len(valid) if valid else [])
                else:
                    weights = [1 / len(valid)] * len(valid) if valid else []
                tickers = {r["ticker"] for r in valid}
                if prev_holdings:
                    turnover = len(tickers.symmetric_difference(prev_holdings)) / max(len(tickers.union(prev_holdings)), 1)
                else:
                    turnover = 1.0 if tickers else 0.0
                turnovers.append(turnover)
                gross = sum(w * (num(r["realized_forward_return"]) or 0.0) for w, r in zip(weights, valid))
                cost = turnover * cost_bps / 10000.0
                net = gross - cost
                eq *= 1 + net
                fwd_dates = sorted({r.get("forward_price_date", "") for r in valid if r.get("forward_price_date")})
                date = fwd_dates[-1] if fwd_dates else asof
                curve = f"{variant}_{window}"
                eq_rows.append({"curve_type": "technical_only_portfolio", "curve_name": curve, "date": date, "equity": fmt(eq), "daily_return": fmt(net), "rebalance_date": asof, **GUARDRAILS})
                ret_rows.append({"curve_name": curve, "date": date, "daily_return": fmt(net), "equity": fmt(eq), "rebalance_date": asof, "gross_period_return": fmt(gross), "transaction_cost": fmt(cost), **GUARDRAILS})
                turnover_rows.append({"curve_name": curve, "rebalance_date": asof, "selected_count": len(valid), "target_count": n, "insufficient_count": max(n - len(valid), 0), "turnover": fmt(turnover), "cost_bps": cost_bps, "cost_applied": fmt(cost), **GUARDRAILS})
                for w, r in zip(weights, valid):
                    holding_rows.append({"curve_name": curve, "rebalance_date": asof, "ticker": r["ticker"], "weight": fmt(w), "technical_only_rank": r.get("technical_only_rank", ""), "technical_only_score": r.get("technical_only_score", ""), "forward_return_window": window, **GUARDRAILS})
                prev_holdings = tickers
    return eq_rows, ret_rows, holding_rows, turnover_rows


def risk_metrics(name: str, rows: list[dict[str, object]], curve_type: str) -> dict[str, object]:
    vals = [(str(r["date"]), float(r["daily_return"]), float(r["equity"])) for r in rows if str(r.get("curve_name")) == name]
    if not vals:
        return {"curve_name": name, "curve_type": curve_type, **{k: "" for k in ["start_date","end_date","trading_days","total_return","CAGR","annualized_volatility","Sharpe","Sortino","max_drawdown","Calmar","best_day_return","worst_day_return","positive_day_rate","monthly_win_rate","average_monthly_return","worst_month_return"]}, **GUARDRAILS}
    dates, rets, eqs = zip(*vals)
    total = eqs[-1] - 1.0
    years = max(len(rets) / 252.0, 1 / 252.0)
    cagr = eqs[-1] ** (1 / years) - 1 if eqs[-1] > 0 else None
    vol = (stdev(list(rets)) or 0.0) * math.sqrt(252)
    downside = [r for r in rets if r < 0]
    sortino_den = (stdev(downside) or 0.0) * math.sqrt(252) if len(downside) > 1 else 0.0
    peak = -1.0
    maxdd = 0.0
    dd_start = dd_trough = dates[0]
    cur_start = dates[0]
    for d, e in zip(dates, eqs):
        if e > peak:
            peak = e
            cur_start = d
        ddv = e / peak - 1 if peak > 0 else 0
        if ddv < maxdd:
            maxdd = ddv
            dd_start, dd_trough = cur_start, d
    return {
        "curve_name": name, "curve_type": curve_type, "start_date": dates[0], "end_date": dates[-1], "trading_days": len(rets),
        "total_return": fmt(total), "CAGR": fmt(cagr), "annualized_volatility": fmt(vol),
        "Sharpe": fmt((cagr or 0) / vol if vol else None), "Sortino": fmt((cagr or 0) / sortino_den if sortino_den else None),
        "max_drawdown": fmt(maxdd), "Calmar": fmt((cagr or 0) / abs(maxdd) if maxdd else None),
        "best_day_return": fmt(max(rets)), "worst_day_return": fmt(min(rets)), "positive_day_rate": fmt(sum(1 for r in rets if r > 0) / len(rets)),
        "monthly_win_rate": "", "average_monthly_return": "", "worst_month_return": "",
        "max_drawdown_start": dd_start, "max_drawdown_trough": dd_trough, **GUARDRAILS,
    }


def relative_metrics(name: str, rows: list[dict[str, object]], qqq_rows: list[dict[str, object]]) -> dict[str, object]:
    a = {str(r["date"]): float(r["daily_return"]) for r in rows if str(r.get("curve_name")) == name}
    q = {str(r["date"]): float(r["daily_return"]) for r in qqq_rows}
    days = sorted(set(a) & set(q))
    ar = [a[d] for d in days]
    qr = [q[d] for d in days]
    ex = [x - y for x, y in zip(ar, qr)]
    te = (stdev(ex) or 0.0) * math.sqrt(252)
    corr = covariance(ar, qr) / math.sqrt((variance(ar) or 0) * (variance(qr) or 0)) if variance(ar) and variance(qr) else None
    beta = covariance(ar, qr) / variance(qr) if variance(qr) else None
    up_q = [i for i, r in enumerate(qr) if r > 0]
    dn_q = [i for i, r in enumerate(qr) if r < 0]
    return {"curve_name": name, "relative_to": "QQQ_BUY_AND_HOLD", "active_return": fmt(sum(ex)), "annualized_active_return": fmt((mean(ex) or 0) * 252), "tracking_error": fmt(te), "information_ratio": fmt(((mean(ex) or 0) * 252) / te if te else None), "beta_vs_QQQ": fmt(beta), "correlation_vs_QQQ": fmt(corr), "up_capture_vs_QQQ": fmt((mean([ar[i] for i in up_q]) or 0) / (mean([qr[i] for i in up_q]) or 1) if up_q else None), "down_capture_vs_QQQ": fmt((mean([ar[i] for i in dn_q]) or 0) / (mean([qr[i] for i in dn_q]) or 1) if dn_q else None), "excess_positive_day_rate": fmt(sum(1 for x in ex if x > 0) / len(ex) if ex else None), "worst_5pct_daily_excess": fmt(pctile(ex, 0.05)), "best_5pct_daily_excess": fmt(pctile(ex, 0.95)), **GUARDRAILS}


def variance(xs: list[float]) -> float | None:
    return statistics.variance(xs) if len(xs) > 1 else None


def covariance(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2 or len(xs) != len(ys):
        return 0.0
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (len(xs) - 1)


def main() -> int:
    BACKTEST.mkdir(parents=True, exist_ok=True)
    REVIEW.mkdir(parents=True, exist_ok=True)
    READ_CENTER.mkdir(parents=True, exist_ok=True)
    panel = read_rows(R5_PANEL)
    prices = load_prices()
    r3b = read_rows(R3B_DECISION)
    inputs_ok = bool(panel and r3b and read_rows(R5_SUMMARY) and read_rows(R6))
    prices_ok = bool(prices.get("QQQ"))
    scope_ok = all(GUARDRAILS[k] == "FALSE" for k in FALSE_GUARDRAILS)
    write_rows(SCOPE, [{"boundary_check": "restricted_permissions_disabled", "check_passed": yn(scope_ok), "notes": "Research-only; no official/trading/shadow/full-weight permissions.", **GUARDRAILS}])
    if inputs_ok and prices_ok:
        eq_rows, ret_rows, holding_rows, turnover_rows = simulate(panel)
    else:
        eq_rows, ret_rows, holding_rows, turnover_rows = [], [], [], []
    bench_rows, bench_ret_rows = [], []
    for sym in ["QQQ", "SPY", "SOXX"]:
        b, br = benchmark_curve(sym, prices)
        bench_rows.extend(b); bench_ret_rows.extend(br)
    write_rows(EQUITY_PANEL, eq_rows)
    write_rows(DAILY_RETURNS, ret_rows)
    write_rows(HOLDINGS, holding_rows)
    write_rows(BENCH_PANEL, bench_rows)
    etf_candidates = list(V20_CONS.glob("V20_20*.csv")) + list(V20_READ.glob("*ETF*")) + list(PRICE_DIR.glob("*ETF*"))
    etf_status = "ETF_ROTATION_DATA_LIMITED"
    write_rows(ETF_PANEL, [{"comparator_name": "ETF_ROTATION", "comparator_status": etf_status, "curve_fabricated": "FALSE", **GUARDRAILS}])
    write_rows(ETF_AUDIT, [{"comparator_name": "ETF_ROTATION", "availability_status": etf_status, "candidate_artifact_count": len(etf_candidates), "missing_input_list": "continuous_historical_selection_curve|validated_etf_price_panel", "curve_fabricated": "FALSE", **GUARDRAILS}])
    all_return_rows = ret_rows + bench_ret_rows
    curves = sorted({str(r["curve_name"]) for r in all_return_rows})
    risk = [risk_metrics(c, all_return_rows, "benchmark" if "BUY_AND_HOLD" in c else "technical_only_portfolio") for c in curves]
    write_rows(RISK_SUMMARY, risk)
    qqq_rows = [r for r in bench_ret_rows if r["curve_name"] == "QQQ_BUY_AND_HOLD"]
    rel = [relative_metrics(c, all_return_rows, qqq_rows) for c in curves if c != "QQQ_BUY_AND_HOLD" and qqq_rows]
    write_rows(RELATIVE, rel)
    write_rows(TURNOVER, turnover_rows)
    write_rows(DD, [{"curve_name": r["curve_name"], "max_drawdown": r["max_drawdown"], "max_drawdown_start": r.get("max_drawdown_start", ""), "max_drawdown_trough": r.get("max_drawdown_trough", ""), "max_drawdown_recovery_date": "", "max_drawdown_duration_days": "", "top_5_drawdown_periods": "primary_drawdown_only", **GUARDRAILS} for r in risk])
    write_rows(PRICE_AUDIT, [{"source": str(TICKER_PRICES.relative_to(ROOT)), "symbol_count": len(prices), "QQQ_available": yn(bool(prices.get("QQQ"))), "SPY_available": yn(bool(prices.get("SPY"))), "SOXX_available": yn(bool(prices.get("SOXX"))), **GUARDRAILS}])
    best_sharpe = max(risk, key=lambda r: num(r.get("Sharpe")) if num(r.get("Sharpe")) is not None else -999) if risk else {}
    best_total = max(risk, key=lambda r: num(r.get("total_return")) if num(r.get("total_return")) is not None else -999) if risk else {}
    if not inputs_ok:
        status, decision = PANEL_BLOCKED, "BLOCK_EQUITY_CURVE_REVIEW"
    elif not prices_ok:
        status, decision = PRICE_BLOCKED, "BLOCK_EQUITY_CURVE_REVIEW"
    elif not scope_ok:
        status, decision = SCOPE_BLOCKED, "BLOCK_EQUITY_CURVE_REVIEW"
    elif etf_status == "ETF_ROTATION_DATA_LIMITED":
        status, decision = ETF_LIMITED_STATUS, "ETF_ROTATION_COMPARISON_DATA_LIMITED"
    else:
        status, decision = PASS_STATUS, "TECHNICAL_ONLY_EQUITY_CURVE_REVIEW_READY"
    next_stage = "V21.046-R1_ETF_ROTATION_COMPARATOR_SOURCE_REPAIR" if etf_status == "ETF_ROTATION_DATA_LIMITED" else "V21.046-R2_EQUITY_CURVE_RISK_REVIEW_GATE"
    dates = sorted({str(r["date"]) for r in eq_rows})
    decision_row = {"stage": STAGE, "final_status": status, "decision": decision, "backtest_start_date": dates[0] if dates else "", "backtest_end_date": dates[-1] if dates else "", "portfolio_variants_tested": "|".join(v[0] for v in VARIANTS), "rebalance_frequencies_tested": "|".join(WINDOWS), "best_variant_by_sharpe": best_sharpe.get("curve_name", ""), "best_variant_by_total_return": best_total.get("curve_name", ""), "QQQ_comparison_summary": "relative_metrics_written" if rel else "QQQ_DATA_LIMITED", "SPY_SOXX_comparison_summary": f"SPY={yn(bool(prices.get('SPY')))}|SOXX={yn(bool(prices.get('SOXX')))}", "ETF_rotation_comparator_status": etf_status, "recommended_next_stage": next_stage, "online_download_attempted": "FALSE", "yfinance_used": "FALSE", **GUARDRAILS}
    write_rows(DECISION, [decision_row])
    write_rows(READINESS, [{"readiness_check": "equity_curve_review", "ready": yn(bool(eq_rows and risk)), "recommended_next_stage": next_stage, **GUARDRAILS}])
    report = f"""# V21.046 Technical-only continuous equity curve and risk metric backtest

final_status: {status}

decision: {decision}

backtest date range: {decision_row['backtest_start_date']} to {decision_row['backtest_end_date']}

portfolio variants tested: {decision_row['portfolio_variants_tested']}

rebalance frequencies tested: {decision_row['rebalance_frequencies_tested']}

benchmark availability: QQQ={yn(bool(prices.get('QQQ')))}, SPY={yn(bool(prices.get('SPY')))}, SOXX={yn(bool(prices.get('SOXX')))}

ETF rotation comparator availability: {etf_status}

Best technical-only variant by risk-adjusted metric: {decision_row['best_variant_by_sharpe']}

Best technical-only variant by total return: {decision_row['best_variant_by_total_return']}

Risk metric table, relative metrics vs QQQ, turnover/cost impact, and drawdown diagnostics were written to the V21.046 CSV artifacts.

Data limitations: ETF rotation comparator is data-limited unless a continuous historical local selection curve is repaired.

Technical-only equity curve results must not be interpreted as full-weight results or full-weight evidence.

No buy/sell/hold recommendation was created.

Full-weight remains blocked: TRUE. full_weight_result_available=FALSE and full_weight_rebacktest_allowed_now=FALSE.

Recommended next stage: {next_stage}

Guardrail statement: research-only equity-curve backtest; no official mutation, no filter adoption, no shadow gate/adoption, no real-book/broker/execution/trade-action output, no downloads, no yfinance, and no fabricated prices, returns, rankings, ETF signals, or benchmark values.
"""
    REPORT.write_text(report, encoding="utf-8")
    shutil.copyfile(REPORT, CURRENT_REPORT)
    print(f"final_status={status}")
    print(f"decision={decision}")
    print(f"best_variant_by_sharpe={decision_row['best_variant_by_sharpe']}")
    print(f"best_variant_by_total_return={decision_row['best_variant_by_total_return']}")
    print(f"QQQ_comparison_summary={decision_row['QQQ_comparison_summary']}")
    print(f"ETF_comparator_status={etf_status}")
    print(f"recommended_next_stage={next_stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
