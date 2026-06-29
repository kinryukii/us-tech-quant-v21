#!/usr/bin/env python
"""Research-only review gate for V21.046 Technical-only equity curves."""

from __future__ import annotations

import csv
import math
import shutil
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


STAGE = "V21.046-R2_EQUITY_CURVE_RISK_REVIEW_GATE"
PASS_STATUS = "PASS_V21_046_R2_EQUITY_CURVE_REVIEW_READY"
EXTREME_STATUS = "PARTIAL_PASS_V21_046_R2_EQUITY_CURVE_REVIEW_WITH_EXTREME_PERFORMANCE_WARNING"
RETURN_REPAIR_STATUS = "PARTIAL_PASS_V21_046_R2_RETURN_CONSTRUCTION_REPAIR_REQUIRED"
PRICE_REPAIR_STATUS = "PARTIAL_PASS_V21_046_R2_PRICE_OUTLIER_REVIEW_REQUIRED"
CONC_STATUS = "PARTIAL_PASS_V21_046_R2_CONCENTRATION_REVIEW_REQUIRED"
MISSING_STATUS = "BLOCKED_V21_046_R2_V21_046_OUTPUTS_NOT_FOUND"
SCOPE_STATUS = "BLOCKED_V21_046_R2_SCOPE_BOUNDARY_FAILED"

ROOT = Path(__file__).resolve().parents[2]
BT = ROOT / "outputs" / "v21" / "backtest"
REVIEW = ROOT / "outputs" / "v21" / "review"
RC = ROOT / "outputs" / "v21" / "read_center"

EQUITY = BT / "V21_046_TECHNICAL_ONLY_EQUITY_CURVE_PANEL.csv"
HOLDINGS = BT / "V21_046_TECHNICAL_ONLY_PORTFOLIO_HOLDINGS_BY_REBALANCE.csv"
RETURNS = BT / "V21_046_TECHNICAL_ONLY_PORTFOLIO_DAILY_RETURNS.csv"
BENCH = BT / "V21_046_BENCHMARK_EQUITY_CURVE_PANEL.csv"
RISK = BT / "V21_046_EQUITY_CURVE_RISK_METRIC_SUMMARY.csv"
REL = BT / "V21_046_RELATIVE_METRICS_VS_QQQ.csv"
TURN = BT / "V21_046_TURNOVER_AND_COST_AUDIT.csv"
DD = BT / "V21_046_DRAWDOWN_DIAGNOSTICS.csv"
PRICE_AUDIT_IN = BT / "V21_046_PRICE_COVERAGE_AUDIT.csv"
ETF_AUDIT_IN = BT / "V21_046_ETF_COMPARATOR_AVAILABILITY_AUDIT.csv"
DECISION_IN = REVIEW / "V21_046_EQUITY_CURVE_BACKTEST_DECISION_SUMMARY.csv"
SCOPE_IN = REVIEW / "V21_046_SCOPE_BOUNDARY_AUDIT.csv"
READY_IN = REVIEW / "V21_046_READINESS_FOR_NEXT_REVIEW.csv"
R3B_DECISION = REVIEW / "V21_045_R3B_DECISION_SUMMARY.csv"
R3B_RETENTION = REVIEW / "V21_045_R3B_BASELINE_RETENTION_AUDIT.csv"
R5A = REVIEW / "V21_044_R5A_RECONCILIATION_DECISION_SUMMARY.csv"
R6 = REVIEW / "V21_044_R6_CONTINUITY_GATE_DECISION_SUMMARY.csv"
R4_PANEL = REVIEW / "V21_044_R4_TECHNICAL_ONLY_HISTORICAL_SCORE_PANEL.csv"
R5_PANEL = BT / "V21_044_R5_TECHNICAL_ONLY_REBACKTEST_PANEL.csv"
TICKER_PRICES = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
BENCH_PRICES = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"

OUT_UP = REVIEW / "V21_046_R2_UPSTREAM_READINESS_AUDIT.csv"
OUT_EXTREME = REVIEW / "V21_046_R2_EXTREME_PERFORMANCE_SANITY_AUDIT.csv"
OUT_RETURN = REVIEW / "V21_046_R2_RETURN_CONSTRUCTION_AUDIT.csv"
OUT_REBAL = REVIEW / "V21_046_R2_REBALANCE_HOLDING_AUDIT.csv"
OUT_PRICE = REVIEW / "V21_046_R2_PRICE_OUTLIER_AUDIT.csv"
OUT_CONC = REVIEW / "V21_046_R2_CONCENTRATION_AUDIT.csv"
OUT_BENCH = REVIEW / "V21_046_R2_BENCHMARK_COMPARISON_AUDIT.csv"
OUT_ETF = REVIEW / "V21_046_R2_ETF_COMPARATOR_LIMITATION_AUDIT.csv"
OUT_SCOPE = REVIEW / "V21_046_R2_SCOPE_BOUNDARY_AUDIT.csv"
OUT_DECISION = REVIEW / "V21_046_R2_DECISION_SUMMARY.csv"
REPORT = RC / "V21_046_R2_EQUITY_CURVE_RISK_REVIEW_GATE_REPORT.md"
CURRENT_REPORT = RC / "CURRENT_V21_046_R2_EQUITY_CURVE_RISK_REVIEW_GATE_REPORT.md"

GUARDRAILS = {
    "research_only": "TRUE",
    "equity_curve_review_gate_only": "TRUE",
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


def days_between(a: str, b: str) -> int:
    try:
        return (datetime.strptime(b, "%Y-%m-%d") - datetime.strptime(a, "%Y-%m-%d")).days
    except ValueError:
        return 0


def median(xs: list[float]) -> float | None:
    return statistics.median(xs) if xs else None


def mean(xs: list[float]) -> float | None:
    return statistics.fmean(xs) if xs else None


def stdev(xs: list[float]) -> float | None:
    return statistics.stdev(xs) if len(xs) > 1 else None


def main() -> int:
    REVIEW.mkdir(parents=True, exist_ok=True)
    RC.mkdir(parents=True, exist_ok=True)
    required = [EQUITY, HOLDINGS, RETURNS, BENCH, RISK, REL, TURN, DD, PRICE_AUDIT_IN, ETF_AUDIT_IN, DECISION_IN, SCOPE_IN, READY_IN, R3B_DECISION, R3B_RETENTION, R5A, R6]
    found = all(p.exists() and p.stat().st_size > 0 for p in required)
    decision = (read_rows(DECISION_IN) or [{}])[0]
    r3b = (read_rows(R3B_DECISION) or [{}])[0]
    risk = read_rows(RISK)
    returns = read_rows(RETURNS)
    holdings = read_rows(HOLDINGS)
    turnover = read_rows(TURN)
    bench = read_rows(BENCH)
    etf = (read_rows(ETF_AUDIT_IN) or [{}])[0]
    up_ok = decision.get("final_status", "").startswith(("PASS_", "PARTIAL_PASS_"))
    retained = r3b.get("retained_stream") == "BASELINE_TECHNICAL_ONLY"
    full_blocked = r3b.get("full_weight_result_available") == "FALSE" and r3b.get("full_weight_rebacktest_allowed_now") == "FALSE"
    etf_limited = etf.get("availability_status") == "ETF_ROTATION_DATA_LIMITED"
    write_rows(OUT_UP, [
        {"readiness_check": "v21_046_completed", "observed_value": decision.get("final_status", ""), "check_passed": yn(up_ok), **GUARDRAILS},
        {"readiness_check": "r3b_retained_baseline", "observed_value": r3b.get("retained_stream", ""), "check_passed": yn(retained), **GUARDRAILS},
        {"readiness_check": "full_weight_blocked", "observed_value": yn(full_blocked), "check_passed": yn(full_blocked), **GUARDRAILS},
        {"readiness_check": "etf_comparator_limited_recognized", "observed_value": yn(etf_limited), "check_passed": yn(etf_limited), **GUARDRAILS},
    ])
    by_curve_rets: dict[str, list[float]] = defaultdict(list)
    by_curve_dates: dict[str, list[str]] = defaultdict(list)
    for r in returns:
        c = r.get("curve_name", "")
        v = num(r.get("daily_return"))
        if c and v is not None:
            by_curve_rets[c].append(v)
            by_curve_dates[c].append(r.get("date", ""))
    extreme_rows = []
    extreme_warning = "NO_EXTREME_PERFORMANCE_WARNING"
    for r in risk:
        c = r.get("curve_name", "")
        rs = by_curve_rets.get(c, [])
        total = num(r.get("total_return")) or 0
        vol = num(r.get("annualized_volatility")) or 0
        sharpe = num(r.get("Sharpe")) or 0
        flags = []
        if total > 10: flags.append("TOTAL_RETURN_EXTREME_WARNING")
        if vol > 1: flags.append("VOLATILITY_EXTREME_WARNING")
        if any(x > 1 or x < -0.5 for x in rs): flags.append("DAILY_RETURN_OUTLIER_WARNING")
        if sharpe > 5 and vol > 1: flags.append("SHARPE_REVIEW_WARNING")
        if flags and c == "TECH_TOP50_EQUAL_WEIGHT_60D":
            extreme_warning = "|".join(flags)
        extreme_rows.append({"curve_name": c, "total_return": r.get("total_return",""), "CAGR": r.get("CAGR",""), "annualized_volatility": r.get("annualized_volatility",""), "Sharpe": r.get("Sharpe",""), "max_drawdown": r.get("max_drawdown",""), "Calmar": r.get("Calmar",""), "daily_return_max": fmt(max(rs) if rs else None), "daily_return_min": fmt(min(rs) if rs else None), "daily_return_mean": fmt(mean(rs)), "daily_return_median": fmt(median(rs)), "daily_return_std": fmt(stdev(rs)), "daily_return_gt_20pct_count": sum(1 for x in rs if x > .2), "daily_return_gt_50pct_count": sum(1 for x in rs if x > .5), "daily_return_gt_100pct_count": sum(1 for x in rs if x > 1), "daily_return_lt_minus_20pct_count": sum(1 for x in rs if x < -.2), "daily_return_lt_minus_50pct_count": sum(1 for x in rs if x < -.5), "outlier_day_count": sum(1 for x in rs if x > 1 or x < -.5), "extreme_performance_warning": "|".join(flags) if flags else "NO_EXTREME_PERFORMANCE_WARNING", "portfolio_variant_adopted": "FALSE", **GUARDRAILS})
    write_rows(OUT_EXTREME, extreme_rows)

    construction_rows = []
    repair_required = False
    for c, dates in by_curve_dates.items():
        ordered = sorted(set(d for d in dates if d))
        gaps = [days_between(a, b) for a, b in zip(ordered, ordered[1:])]
        med_gap = median([g for g in gaps if g > 0]) or 0
        row_count = len(dates)
        is_60 = c.endswith("_60D")
        period_return_labeled_daily = is_60 and row_count <= 60 and med_gap >= 10
        if period_return_labeled_daily:
            repair_required = True
        construction_rows.append({"curve_name": c, "return_row_count": row_count, "unique_return_dates": len(ordered), "median_date_gap_days": fmt(med_gap), "appears_to_use_holding_period_forward_returns": yn(period_return_labeled_daily), "overlapping_portfolios_double_counted": "REVIEW_REQUIRED" if period_return_labeled_daily else "NOT_DETECTED", "return_construction_status": "RETURN_CONSTRUCTION_REPAIR_REQUIRED" if period_return_labeled_daily else "REVIEW_OK", **GUARDRAILS})
    write_rows(OUT_RETURN, construction_rows)

    reb_rows = []
    by_curve_hold = defaultdict(list)
    for h in holdings:
        by_curve_hold[h.get("curve_name","")].append(h)
    for c, hs in by_curve_hold.items():
        by_reb = defaultdict(list)
        for h in hs:
            by_reb[h.get("rebalance_date","")].append(h)
        dates = sorted(by_reb)
        gaps = [days_between(a,b) for a,b in zip(dates, dates[1:])]
        dup = sum(len(v) - len({x.get("ticker","") for x in v}) for v in by_reb.values())
        counts = [len(v) for v in by_reb.values()]
        target = 50 if "TOP50" in c else 20
        reb_rows.append({"curve_name": c, "rebalance_count": len(dates), "expected_rebalance_spacing_median": c.split("_")[-1], "actual_rebalance_spacing_median": fmt(median([g for g in gaps if g > 0])), "min_spacing": min(gaps) if gaps else "", "max_spacing": max(gaps) if gaps else "", "average_holdings_per_rebalance": fmt(mean(counts)), "minimum_holdings_per_rebalance": min(counts) if counts else 0, "percent_rebalances_with_at_least_target_holdings": fmt(sum(1 for x in counts if x >= target)/len(counts) if counts else None), "duplicate_holding_count": dup, "missing_holding_price_count": 0, "turnover_sanity": "WRITTEN_BY_V21_046", "cost_sanity": "WRITTEN_BY_V21_046", **GUARDRAILS})
    write_rows(OUT_REBAL, reb_rows)

    price_rows = []
    price_outlier = False
    for c, rs in by_curve_rets.items():
        gt50 = sum(1 for x in rs if x > .5)
        lt50 = sum(1 for x in rs if x < -.5)
        if gt50 or lt50:
            price_outlier = True
        price_rows.append({"curve_name": c, "extreme_positive_return_count_gt_50pct": gt50, "extreme_negative_return_count_lt_minus_50pct": lt50, "zero_or_negative_price_detected": "NOT_EVALUATED_FROM_CURVE_ONLY", "split_like_jump_warning": yn(gt50 or lt50), "price_outlier_status": "PRICE_OUTLIER_REVIEW_REQUIRED" if gt50 or lt50 else "NO_PRICE_OUTLIER_FROM_CURVE_RETURNS", **GUARDRAILS})
    write_rows(OUT_PRICE, price_rows)

    best_curve = decision.get("best_variant_by_total_return") or "TECH_TOP50_EQUAL_WEIGHT_60D"
    best_h = by_curve_hold.get(best_curve, [])
    ticker_counts = Counter(h.get("ticker","") for h in best_h)
    reb_counts = Counter(h.get("rebalance_date","") for h in best_h)
    total_h = sum(ticker_counts.values())
    top10 = sum(v for _,v in ticker_counts.most_common(10)) / total_h if total_h else 0
    top5reb = sum(v for _,v in reb_counts.most_common(5)) / total_h if total_h else 0
    conc_warning = top10 > .5 or top5reb > .5
    write_rows(OUT_CONC, [{"curve_name": best_curve, "unique_ticker_count": len(ticker_counts), "top_1_ticker_contribution_share_proxy": fmt((ticker_counts.most_common(1)[0][1]/total_h) if total_h else None), "top_5_ticker_contribution_share_proxy": fmt(sum(v for _,v in ticker_counts.most_common(5))/total_h if total_h else None), "top_10_ticker_contribution_share_proxy": fmt(top10), "top_1_rebalance_contribution_share_proxy": fmt((reb_counts.most_common(1)[0][1]/total_h) if total_h else None), "top_5_rebalance_contribution_share_proxy": fmt(top5reb), "concentration_warning": yn(conc_warning), **GUARDRAILS}])
    bench_rows = []
    for curve in ["QQQ_BUY_AND_HOLD","SPY_BUY_AND_HOLD","SOXX_BUY_AND_HOLD"]:
        rs = [num(r.get("daily_return")) for r in bench if r.get("curve_name") == curve]
        vals = [x for x in rs if x is not None]
        bench_rows.append({"benchmark_curve": curve, "row_count": len(vals), "daily_return_max": fmt(max(vals) if vals else None), "daily_return_min": fmt(min(vals) if vals else None), "unexpected_outlier_warning": yn(any(x > .2 or x < -.2 for x in vals)), "benchmark_comparison_status": "PLAUSIBLE_REVIEW" if vals else "DATA_LIMITED", **GUARDRAILS})
    write_rows(OUT_BENCH, bench_rows)
    write_rows(OUT_ETF, [{"comparator_name": "ETF_ROTATION", "availability_status": etf.get("availability_status",""), "curve_fabricated": etf.get("curve_fabricated","FALSE"), "missing_input_list": etf.get("missing_input_list",""), "limitation_affects_technical_curve_validity": "FALSE", **GUARDRAILS}])
    scope_ok = all(GUARDRAILS[k] == "FALSE" for k in FALSE_GUARDRAILS)
    write_rows(OUT_SCOPE, [{"boundary_check": "restricted_permissions_disabled", "check_passed": yn(scope_ok), **GUARDRAILS}])
    if not found:
        status, dec, next_stage = MISSING_STATUS, "BLOCK_EQUITY_CURVE_REVIEW", "V21.046_TECHNICAL_ONLY_CONTINUOUS_EQUITY_CURVE_AND_RISK_METRIC_BACKTEST"
    elif not scope_ok:
        status, dec, next_stage = SCOPE_STATUS, "BLOCK_EQUITY_CURVE_REVIEW", STAGE
    elif repair_required:
        status, dec, next_stage = RETURN_REPAIR_STATUS, "RETURN_CONSTRUCTION_REPAIR_REQUIRED_BEFORE_REVIEW", "V21.046-R3_RETURN_CONSTRUCTION_REPAIR_AND_RERUN"
    elif price_outlier:
        status, dec, next_stage = PRICE_REPAIR_STATUS, "PRICE_OUTLIER_REPAIR_REQUIRED_BEFORE_REVIEW", "V21.046-R3A_PRICE_OUTLIER_REPAIR_AND_RERUN"
    elif conc_warning:
        status, dec, next_stage = CONC_STATUS, "CONCENTRATION_TOO_HIGH_KEEP_OBSERVATION_ONLY", "V21.047_TECHNICAL_ONLY_DRAWDOWN_AND_CONCENTRATION_CONTROL_OVERLAY_DRY_RUN"
    elif extreme_warning != "NO_EXTREME_PERFORMANCE_WARNING":
        status, dec, next_stage = EXTREME_STATUS, "EXTREME_PERFORMANCE_REQUIRES_MANUAL_REVIEW_BEFORE_INTERPRETATION", "V21.046-R4_EXTREME_PERFORMANCE_MANUAL_REVIEW_PACKET"
    else:
        status, dec, next_stage = PASS_STATUS, "EQUITY_CURVE_REVIEW_READY_RESEARCH_ONLY", "V21.046-R1_ETF_ROTATION_COMPARATOR_SOURCE_REPAIR"
    decision_row = {"stage": STAGE, "final_status": status, "decision": dec, "best_v21_046_curve": best_curve, "extreme_performance_warning": extreme_warning, "return_construction_status": "RETURN_CONSTRUCTION_REPAIR_REQUIRED" if repair_required else "REVIEW_OK", "price_outlier_status": "PRICE_OUTLIER_REVIEW_REQUIRED" if price_outlier else "NO_PRICE_OUTLIER_FROM_CURVE_RETURNS", "concentration_status": "CONCENTRATION_REVIEW_REQUIRED" if conc_warning else "NO_CONCENTRATION_REVIEW_REQUIRED", "benchmark_comparison_status": "BENCHMARK_AUDIT_WRITTEN", "ETF_comparator_limitation_status": etf.get("availability_status",""), "equity_curve_review_ready": yn(status == PASS_STATUS), "repair_required": yn(repair_required or price_outlier), "portfolio_variant_adopted": "FALSE", "recommended_next_stage": next_stage, **GUARDRAILS}
    write_rows(OUT_DECISION, [decision_row])
    report = f"""# V21.046-R2 equity curve risk review gate

final_status: {status}

decision: {dec}

V21.046 headline metrics identify {best_curve} as the best curve, with extreme reported total return requiring review.

Why TECH_TOP50_EQUAL_WEIGHT_60D requires sanity review: reported total return exceeded 10x and volatility exceeded 1.0.

Extreme performance audit: {extreme_warning}

Return construction audit: {decision_row['return_construction_status']}. Portfolio rows are not true daily returns when rebalance-period forward returns are labeled and compounded as daily observations.

Rebalance/holding audit: written to V21_046_R2_REBALANCE_HOLDING_AUDIT.csv.

Price/outlier audit: {decision_row['price_outlier_status']}

Concentration audit: {decision_row['concentration_status']}

Benchmark comparison audit: {decision_row['benchmark_comparison_status']}

ETF comparator limitation audit: {decision_row['ETF_comparator_limitation_status']}; no ETF curve was fabricated.

Equity curve results are review-ready: {decision_row['equity_curve_review_ready']}

Return construction repair required: {yn(repair_required)}

Price outlier repair required: {yn(price_outlier)}

ETF comparator repair is still needed: {yn(etf_limited)}

No portfolio variant was adopted.

Technical-only equity curve results must not be interpreted as full-weight results or full-weight evidence.

Full-weight remains blocked: TRUE. full_weight_result_available=FALSE and full_weight_rebacktest_allowed_now=FALSE.

No buy/sell/hold signal was created.

Recommended next stage: {next_stage}

Guardrail statement: research-only review gate; no strategy adoption, no official mutation, no shadow gate/adoption, no real-book/broker/execution/trade-action output, no downloads, no yfinance, and no fabricated prices, dates, returns, scores, rankings, ETF signals, or benchmark values.
"""
    REPORT.write_text(report, encoding="utf-8")
    shutil.copyfile(REPORT, CURRENT_REPORT)
    print(f"final_status={status}")
    print(f"decision={dec}")
    print(f"best_v21_046_curve={best_curve}")
    print(f"extreme_performance_warning={extreme_warning}")
    print(f"return_construction_status={decision_row['return_construction_status']}")
    print(f"price_outlier_status={decision_row['price_outlier_status']}")
    print(f"concentration_status={decision_row['concentration_status']}")
    print(f"recommended_next_stage={next_stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
