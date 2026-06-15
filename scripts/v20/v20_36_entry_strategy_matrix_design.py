from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
RANDOM_ASOF = ROOT / "inputs" / "v20" / "random_asof"

IN_R2_NEXT = CONSOLIDATION / "V20_35_R2_NEXT_STEP_DECISION_SUMMARY.csv"
IN_R2_DECISION = CONSOLIDATION / "V20_35_R2_RANDOM_ASOF_BACKTEST_DECISION.csv"
IN_R2_TOP20 = CONSOLIDATION / "V20_35_R2_ASOF_TOP20_SELECTIONS.csv"
IN_R2_TOP50 = CONSOLIDATION / "V20_35_R2_ASOF_TOP50_SELECTIONS.csv"
IN_R2_TOP100 = CONSOLIDATION / "V20_35_R2_ASOF_TOP100_SELECTIONS.csv"
IN_R2_RANKING = CONSOLIDATION / "V20_35_R2_ASOF_TECHNICAL_SCORE_AND_RANKING.csv"
IN_R2_FACTOR = CONSOLIDATION / "V20_35_R2_ASOF_TECHNICAL_FACTOR_RECOMPUTE_MATRIX.csv"
IN_R2_ATTACH = CONSOLIDATION / "V20_35_R2_FORWARD_OUTCOME_ATTACHMENT.csv"
IN_R2_RETURNS = CONSOLIDATION / "V20_35_R2_EXPLORATORY_ROW_LEVEL_RETURNS.csv"
IN_R2_PIT = CONSOLIDATION / "V20_35_R2_STALE_LEAKAGE_PIT_GATE.csv"
IN_TICKER_PRICE = RANDOM_ASOF / "V20_RANDOM_ASOF_HISTORICAL_TICKER_PRICE_INPUT.csv"
IN_BENCH_PRICE = RANDOM_ASOF / "V20_RANDOM_ASOF_HISTORICAL_BENCHMARK_PRICE_INPUT.csv"
IN_BLOCKED_NON_PIT = CONSOLIDATION / "V20_34_RANDOM_ASOF_BLOCKED_NON_PIT_FACTOR_REGISTER.csv"
IN_QUARANTINE = CONSOLIDATION / "V20_34_QUARANTINE_DECISION_REGISTER.csv"

OUT_GATE = CONSOLIDATION / "V20_36_V20_35_R2_GATE_REVIEW.csv"
OUT_MASTER = CONSOLIDATION / "V20_36_ENTRY_STRATEGY_MASTER_MATRIX.csv"
OUT_FIELDS = CONSOLIDATION / "V20_36_ENTRY_STRATEGY_FIELD_REQUIREMENTS.csv"
OUT_ASSUMPTIONS = CONSOLIDATION / "V20_36_ENTRY_STRATEGY_EXECUTION_ASSUMPTIONS.csv"
OUT_INVALID = CONSOLIDATION / "V20_36_ENTRY_STRATEGY_INVALIDATION_RULES.csv"
OUT_READINESS = CONSOLIDATION / "V20_36_ENTRY_STRATEGY_READINESS_AUDIT.csv"
OUT_NO_FILL = CONSOLIDATION / "V20_36_ENTRY_STRATEGY_NO_FILL_POLICY_MATRIX.csv"
OUT_RISK = CONSOLIDATION / "V20_36_ENTRY_STRATEGY_RISK_FILTER_MATRIX.csv"
OUT_STAGE = CONSOLIDATION / "V20_36_ENTRY_STRATEGY_STAGE_AND_TRANCHE_MATRIX.csv"
OUT_BLOCKED = CONSOLIDATION / "V20_36_BLOCKED_NON_PIT_ENTRY_DEPENDENCY_REGISTER.csv"
OUT_PLAN = CONSOLIDATION / "V20_36_V20_37_EXECUTION_PLAN.csv"
OUT_NEXT = CONSOLIDATION / "V20_36_NEXT_STEP_DECISION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_36_ENTRY_STRATEGY_MATRIX_DESIGN_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_ENTRY_STRATEGY_MATRIX_DESIGN.md"
READ_FIRST = OPS / "V20_36_READ_FIRST.txt"

STAGE_NAME = "V20.36_ENTRY_STRATEGY_MATRIX_DESIGN"
PASS_STATUS = "PASS_V20_36_ENTRY_STRATEGY_MATRIX_DESIGN"
BLOCKED_STATUS = "BLOCKED_V20_36_ENTRY_STRATEGY_MATRIX_DESIGN"


def clean(value: object) -> str:
    return str(value or "").strip()


def upper(value: object) -> str:
    return clean(value).upper()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def as_int(value: object) -> int:
    try:
        return int(float(clean(value)))
    except ValueError:
        return 0


def has_fields(fields: list[str], required: str) -> bool:
    if not required or required == "none":
        return True
    available = set(fields)
    for field in required.split("|"):
        if field and field not in available:
            return False
    return True


def strategy_rows() -> list[dict[str, object]]:
    base = [
        ("SIGNAL_CLOSE_BUY", "Signal Close Buy", "immediate", "signal_date close available", 0, "close|adjusted_close", "none", "none", "none", "signal close", "no_fill_if_signal_close_missing", "preserve no-fill", "none", "none", "entry uses signal_date close; future V20.37 returns from actual entry date", False, False, True, ""),
        ("NEXT_OPEN_BUY", "Next Open Buy", "immediate", "next trading day open available", 1, "open", "none", "none", "benchmark close", "open required unless fallback enabled", "no_fill_if_next_open_missing", "preserve no-fill", "gap threshold audit", "none", "entry uses next trading day open", False, False, True, ""),
        ("NEXT_CLOSE_BUY", "Next Close Buy", "immediate", "next trading day close available", 1, "close|adjusted_close", "none", "none", "benchmark close", "next close", "no_fill_if_next_close_missing", "preserve no-fill", "none", "none", "entry uses next trading day close", False, False, True, ""),
        ("DELAYED_CLOSE_2D_BUY", "Delayed Close 2D Buy", "immediate", "second trading day close available", 2, "close|adjusted_close", "none", "none", "benchmark close", "2d close", "no_fill_if_2d_close_missing", "preserve no-fill", "none", "none", "entry uses close two trading days after signal", False, False, True, ""),
        ("MA10_PULLBACK_BUY", "MA10 Pullback Buy", "pullback", "post-signal low/close touches MA10 band", 5, "low|close|adjusted_close", "none", "ma10_position", "benchmark close", "no fallback to current factors", "invalidate if MA10 unavailable as-of signal", "preserve no-fill", "gap threshold audit", "volatility threshold audit", "first valid touch inside entry window", False, False, True, ""),
        ("MA20_PULLBACK_BUY", "MA20 Pullback Buy", "pullback", "post-signal low/close touches MA20 band", 10, "low|close|adjusted_close", "none", "ma20_position", "benchmark close", "no fallback to current factors", "invalidate if MA20 unavailable as-of signal", "preserve no-fill", "gap threshold audit", "volatility threshold audit", "first valid touch inside entry window", False, False, True, ""),
        ("LIMIT_PULLBACK_1PCT_BUY", "Limit Pullback 1Pct Buy", "pullback", "post-signal price pulls back at least 1 percent", 5, "low|close|adjusted_close", "none", "none", "benchmark close", "signal close reference required", "no fill if threshold not touched", "preserve no-fill", "none", "none", "first threshold touch inside entry window", False, False, True, ""),
        ("LIMIT_PULLBACK_2PCT_BUY", "Limit Pullback 2Pct Buy", "pullback", "post-signal price pulls back at least 2 percent", 10, "low|close|adjusted_close", "none", "none", "benchmark close", "signal close reference required", "no fill if threshold not touched", "preserve no-fill", "none", "none", "first threshold touch inside entry window", False, False, True, ""),
        ("ATR_PULLBACK_BUY", "ATR Pullback Buy", "pullback", "pullback by ATR-like volatility proxy", 10, "high|low|close|adjusted_close", "none", "volatility_20d", "benchmark close", "use volatility_20d proxy only", "block if volatility proxy unavailable", "preserve no-fill", "none", "high volatility threshold audit", "first volatility-scaled pullback touch", False, False, True, ""),
        ("BREAKOUT_CONFIRMATION_BUY", "Breakout Confirmation Buy", "breakout_confirmation", "post-signal price exceeds prior 20d high or breakout level", 10, "high|close|adjusted_close", "none", "breakout_20d", "benchmark close", "no fallback to current levels", "block if prior high proxy unavailable", "preserve no-fill", "gap threshold audit", "none", "first confirmed breakout close/touch", False, False, True, ""),
        ("VOLUME_CONFIRMATION_BUY", "Volume Confirmation Buy", "breakout_confirmation", "advance or breakout with volume confirmation", 10, "high|close|adjusted_close", "volume", "volume_trend_20d", "benchmark close", "volume required", "block if volume unavailable", "preserve no-fill", "gap threshold audit", "none", "first confirmation with volume filter", False, False, True, ""),
        ("MOMENTUM_CONTINUATION_BUY", "Momentum Continuation Buy", "breakout_confirmation", "price remains above MA10/MA20 with positive momentum", 5, "close|adjusted_close", "none", "momentum_10d|ma10_position|ma20_position", "benchmark close", "no fallback to non-PIT factors", "block if momentum or MA fields unavailable", "preserve no-fill", "none", "benchmark trend audit optional", "first continuation-eligible close", False, False, True, ""),
        ("GAP_UP_FILTERED_BUY", "Gap Up Filtered Buy", "risk_filtered", "next entry price passes gap-up threshold", 1, "open|close|adjusted_close", "none", "none", "benchmark close", "delay or no-fill on excessive gap", "invalidate if entry gap cannot be measured", "preserve no-fill", "avoid if next entry price gaps above threshold", "none", "entry after gap filter passes", False, False, True, ""),
        ("HIGH_VOLATILITY_FILTERED_BUY", "High Volatility Filtered Buy", "risk_filtered", "volatility below threshold before entry", 1, "close|adjusted_close", "none", "volatility_20d", "benchmark close", "volatility field required", "block if volatility unavailable", "preserve no-fill", "none", "avoid if volatility exceeds threshold", "entry only when volatility filter passes", False, False, True, ""),
        ("BENCHMARK_RISK_FILTERED_BUY", "Benchmark Risk Filtered Buy", "risk_filtered", "SPY/QQQ short-term trend condition passes", 1, "close|adjusted_close", "none", "none", "benchmark close|benchmark adjusted_close", "benchmark trend required", "block if benchmark fields unavailable", "preserve no-fill", "none", "avoid if SPY/QQQ trend fails", "entry only when benchmark filter passes", False, False, True, ""),
        ("EARNINGS_BLACKOUT_PLACEHOLDER", "Earnings Blackout Placeholder", "risk_filtered", "placeholder blocked until PIT earnings calendar exists", 0, "close|adjusted_close", "none", "PIT_EARNINGS_CALENDAR", "benchmark close", "no fallback", "blocked until PIT earnings calendar exists", "preserve no-fill", "none", "earnings blackout placeholder", "design-only placeholder", False, False, False, "PIT earnings calendar is not available."),
        ("TWO_STAGE_ENTRY", "Two Stage Entry", "staged", "immediate tranche plus pullback tranche", 5, "low|close|adjusted_close", "none", "ma10_position|pullback_quality", "benchmark close", "stage 2 no-fill allowed", "block if stage dates invalid", "preserve partial/no-fill rows", "gap threshold audit", "volatility threshold audit", "two tranches: signal/next close plus pullback", True, True, True, ""),
        ("THREE_STAGE_ENTRY", "Three Stage Entry", "staged", "immediate plus MA10 and MA20/pullback tranches", 10, "low|close|adjusted_close", "none", "ma10_position|ma20_position|pullback_quality", "benchmark close", "later stages no-fill allowed", "block if stage dates invalid", "preserve partial/no-fill rows", "gap threshold audit", "volatility threshold audit", "three tranches: immediate plus MA10/MA20 or pullback", True, True, True, ""),
    ]
    rows = []
    for item in base:
        rows.append({
            "strategy_id": item[0], "strategy_name": item[1], "strategy_family": item[2],
            "entry_trigger": item[3], "entry_window_trading_days": item[4],
            "required_price_fields": item[5], "required_volume_fields": item[6],
            "required_factor_fields": item[7], "benchmark_required_fields": item[8],
            "fallback_policy": item[9], "invalidation_policy": item[10],
            "no_fill_policy": item[11], "gap_filter_policy": item[12],
            "risk_filter_policy": item[13], "expected_future_backtest_price_policy": item[14],
            "partial_fill_simulation_allowed": tf(bool(item[15])),
            "staged_entry_allowed": tf(bool(item[16])),
            "eligible_for_v20_37_execution": tf(bool(item[17])),
            "ineligible_reason": item[18],
        })
    return rows


def main() -> int:
    run_at = now_utc()
    r2_next, _ = read_csv(IN_R2_NEXT)
    r2_decision, _ = read_csv(IN_R2_DECISION)
    top20, _ = read_csv(IN_R2_TOP20)
    top50, _ = read_csv(IN_R2_TOP50)
    top100, _ = read_csv(IN_R2_TOP100)
    ranking, ranking_fields = read_csv(IN_R2_RANKING)
    factors, factor_fields = read_csv(IN_R2_FACTOR)
    attach, _ = read_csv(IN_R2_ATTACH)
    returns, _ = read_csv(IN_R2_RETURNS)
    pit_rows, _ = read_csv(IN_R2_PIT)
    ticker_price, price_fields = read_csv(IN_TICKER_PRICE)
    bench_price, bench_fields = read_csv(IN_BENCH_PRICE)
    blocked_non_pit, _ = read_csv(IN_BLOCKED_NON_PIT)
    quarantine, _ = read_csv(IN_QUARANTINE)

    n = r2_next[0] if r2_next else {}
    d = r2_decision[0] if r2_decision else {}
    gate_ready = (
        upper(n.get("READY_FOR_V20_36_ENTRY_STRATEGY_MATRIX_DESIGN")) == "TRUE"
        and upper(n.get("CURRENT_TOP20_LEAKAGE_DETECTED")) == "FALSE"
        and as_int(n.get("LEAKAGE_BLOCKER_COUNT")) == 0
        and as_int(n.get("FORMULA_MISMATCH_COUNT")) == 0
        and as_int(n.get("FORWARD_RETURN_ROWS_CREATED")) > 0
        and upper(d.get("ready_for_v20_36_entry_strategy_matrix_design")) == "TRUE"
    )
    gate_review = [{
        "gate_check": "V20_35_R2_READY_FOR_V20_36",
        "ready_for_v20_36_entry_strategy_matrix_design": clean(n.get("READY_FOR_V20_36_ENTRY_STRATEGY_MATRIX_DESIGN")),
        "current_top20_leakage_detected": clean(n.get("CURRENT_TOP20_LEAKAGE_DETECTED")),
        "leakage_blocker_count": clean(n.get("LEAKAGE_BLOCKER_COUNT")),
        "formula_mismatch_count": clean(n.get("FORMULA_MISMATCH_COUNT")),
        "forward_return_rows_created": clean(n.get("FORWARD_RETURN_ROWS_CREATED")),
        "gate_ready": tf(gate_ready),
        "review_status": "PASS" if gate_ready else "BLOCKED",
    }]

    strategies = strategy_rows()
    price_available = set(price_fields)
    factor_available = set(factor_fields)
    bench_available = set(bench_fields)
    volume_available = "volume" in price_available
    benchmark_available = bool(bench_price) and {"SPY", "QQQ"} <= {clean(row.get("symbol")) for row in bench_price}
    sample_rows = len(top20) + len(top50) + len(top100)

    readiness_rows = []
    field_rows = []
    no_fill_rows = []
    risk_rows = []
    stage_rows = []
    for s in strategies:
        factor_req = clean(s["required_factor_fields"])
        non_pit_required = "PIT_EARNINGS" in factor_req or "fundamental" in factor_req.lower() or "valuation" in factor_req.lower() or "analyst" in factor_req.lower() or "narrative" in factor_req.lower()
        price_ok = has_fields(price_fields, clean(s["required_price_fields"]).replace("adjusted_close", "adjusted_close"))
        volume_ok = True if clean(s["required_volume_fields"]) == "none" else volume_available
        factor_ok = True if factor_req == "none" else has_fields(factor_fields, factor_req)
        benchmark_ok = benchmark_available
        if non_pit_required:
            status = "DESIGN_ONLY_PLACEHOLDER"
            reason = "Blocked non-PIT dependency or placeholder dependency."
        elif not price_ok or not volume_ok or not factor_ok or not benchmark_ok:
            status = "BLOCKED_MISSING_FIELDS"
            reason = "Required price, volume, factor, or benchmark field is unavailable."
        elif clean(s["strategy_family"]) in {"pullback", "breakout_confirmation", "risk_filtered", "staged"}:
            status = "READY_WITH_LIMITATIONS"
            reason = "Future V20.37 must preserve no-fill rows and compute actual entry-date aligned benchmarks."
        else:
            status = "READY_FOR_V20_37"
            reason = ""
        readiness_rows.append({
            "strategy_id": s["strategy_id"],
            "price_field_availability": tf(price_ok),
            "volume_availability": tf(volume_ok),
            "factor_field_availability": tf(factor_ok),
            "benchmark_availability": tf(benchmark_ok),
            "signal_date_and_forward_window_availability": tf(bool(attach) and bool(returns)),
            "expected_executable_row_count_estimate": 0 if status in {"BLOCKED_MISSING_FIELDS", "DESIGN_ONLY_PLACEHOLDER"} else sample_rows,
            "expected_no_fill_risk_level": "LOW" if clean(s["strategy_family"]) == "immediate" else ("HIGH" if status == "DESIGN_ONLY_PLACEHOLDER" else "MEDIUM"),
            "readiness_status": status,
            "readiness_reason": reason,
        })
        field_rows.append({
            "strategy_id": s["strategy_id"],
            "required_price_fields": s["required_price_fields"],
            "required_volume_fields": s["required_volume_fields"],
            "required_factor_fields": s["required_factor_fields"],
            "benchmark_required_fields": s["benchmark_required_fields"],
            "price_fields_available": tf(price_ok),
            "volume_fields_available": tf(volume_ok),
            "factor_fields_available": tf(factor_ok),
            "benchmark_fields_available": tf(benchmark_ok),
        })
        no_fill_rows.append({
            "strategy_id": s["strategy_id"],
            "no_fill_policy": s["no_fill_policy"],
            "preserve_no_fill_rows_for_opportunity_cost": "TRUE",
            "fallback_policy": s["fallback_policy"],
        })
        risk_rows.append({
            "strategy_id": s["strategy_id"],
            "gap_filter_policy": s["gap_filter_policy"],
            "risk_filter_policy": s["risk_filter_policy"],
            "benchmark_risk_filter_required": tf(s["strategy_id"] == "BENCHMARK_RISK_FILTERED_BUY"),
            "earnings_blackout_pit_dependency_required": tf(s["strategy_id"] == "EARNINGS_BLACKOUT_PLACEHOLDER"),
        })
        stage_rows.append({
            "strategy_id": s["strategy_id"],
            "staged_entry_allowed": s["staged_entry_allowed"],
            "partial_fill_simulation_allowed": s["partial_fill_simulation_allowed"],
            "tranche_count": 3 if s["strategy_id"] == "THREE_STAGE_ENTRY" else (2 if s["strategy_id"] == "TWO_STAGE_ENTRY" else 1),
            "stage_policy": s["expected_future_backtest_price_policy"],
        })

    assumptions = [
        {"assumption_id": "ENTRY_PRICE_HIERARCHY", "assumption_text": "NEXT_OPEN uses explicit open price; close fallback is allowed only when the strategy fallback policy permits it; otherwise preserve no-fill."},
        {"assumption_id": "ENTRY_WINDOWS", "assumption_text": "Immediate entries use 0 to 1 trading day; pullback and breakout entries use configurable 3, 5, or 10 trading-day windows."},
        {"assumption_id": "OUTCOME_WINDOWS_AFTER_ENTRY", "assumption_text": "Future V20.37 outcome windows are forward_1d, forward_3d, forward_5d, forward_10d, and forward_20d after actual entry date."},
        {"assumption_id": "BENCHMARK_ALIGNMENT", "assumption_text": "Benchmark entry and outcome dates must align to actual entry date and actual outcome date, not merely signal_date."},
        {"assumption_id": "NO_FILL_RETENTION", "assumption_text": "No-fill rows must be preserved for fill-rate and opportunity-cost analysis."},
        {"assumption_id": "NO_RETURNS_IN_V20_36", "assumption_text": "V20.36 defines contracts only and does not execute entry strategy returns."},
    ]
    invalid = [
        ("FACTOR_INPUT_AFTER_SIGNAL_DATE", "Block if max factor input date would exceed signal_date."),
        ("ENTRY_DATE_BEFORE_SIGNAL_DATE", "Block if entry date is before signal_date."),
        ("OUTCOME_DATE_NOT_AFTER_ENTRY_DATE", "Block if outcome date is not after actual entry date."),
        ("BENCHMARK_DATE_MISMATCH", "Block if SPY/QQQ dates do not align with entry and outcome dates."),
        ("NON_PIT_FACTOR_REQUIRED", "Block if non-PIT factors are required by an executable strategy."),
        ("CURRENT_TOP20_OR_RANKING_REFERENCE", "Block if current Top20 or current ranking snapshots are referenced."),
        ("MISSING_OHLCV_FIELD", "No-fill or mark strategy ineligible depending on strategy field contract."),
        ("EARNINGS_BLACKOUT_PLACEHOLDER", "Blocked until a point-in-time earnings calendar exists."),
    ]
    invalid_rows = [{"rule_id": rule, "rule_text": text, "severity": "BLOCKER"} for rule, text in invalid]

    blocked_rows = []
    for row in blocked_non_pit:
        blocked_rows.append({
            "blocked_dependency": clean(row.get("blocked_factor_group")),
            "blocked_for_v20_36_executable_entry_strategy": "TRUE",
            "reason": clean(row.get("block_reason")),
            "current_top20_or_current_ranking_used": "FALSE",
        })
    blocked_rows.append({
        "blocked_dependency": "PIT_EARNINGS_CALENDAR_FOR_EARNINGS_BLACKOUT_PLACEHOLDER",
        "blocked_for_v20_36_executable_entry_strategy": "TRUE",
        "reason": "Earnings blackout is design-only until a point-in-time earnings calendar exists.",
        "current_top20_or_current_ranking_used": "FALSE",
    })

    plan_rows = [
        {"plan_step": "V20_37_SCOPE", "plan_text": "Backtest each eligible entry strategy against V20.35-R2 Top20, Top50, and Top100 samples."},
        {"plan_step": "ACTUAL_ENTRY_DATE_RETURNS", "plan_text": "Compute returns from actual entry date for delayed, pullback, breakout, and staged fills."},
        {"plan_step": "BENCHMARK_ALIGNMENT", "plan_text": "Compare actual entry/outcome-date aligned SPY and QQQ benchmark-relative returns."},
        {"plan_step": "FILL_RATE_ANALYSIS", "plan_text": "Report fill rate, no-fill rate, average return, median return, benchmark-relative return, win rate, extreme return count, and formula mismatch count."},
        {"plan_step": "BOUNDARIES", "plan_text": "Do not compute portfolio-level metrics, official recommendations, dynamic weighting, or official trading outputs in V20.37."},
    ]

    ready_count = sum(1 for row in readiness_rows if row["readiness_status"] == "READY_FOR_V20_37")
    limited_count = sum(1 for row in readiness_rows if row["readiness_status"] == "READY_WITH_LIMITATIONS")
    placeholder_count = sum(1 for row in readiness_rows if row["readiness_status"] == "DESIGN_ONLY_PLACEHOLDER")
    blocked_count = sum(1 for row in readiness_rows if str(row["readiness_status"]).startswith("BLOCKED"))
    ready_v20_37 = gate_ready and (ready_count + limited_count) > 0
    status = PASS_STATUS if gate_ready else BLOCKED_STATUS

    next_rows = [{
        "STAGE_NAME": STAGE_NAME,
        "STATUS": status,
        "V20_35_R2_GATE_READY": tf(gate_ready),
        "ENTRY_STRATEGY_COUNT": len(strategies),
        "READY_ENTRY_STRATEGY_COUNT": ready_count,
        "READY_WITH_LIMITATIONS_STRATEGY_COUNT": limited_count,
        "BLOCKED_STRATEGY_COUNT": blocked_count,
        "DESIGN_ONLY_PLACEHOLDER_STRATEGY_COUNT": placeholder_count,
        "NON_PIT_BLOCKED_DEPENDENCY_COUNT": len(blocked_rows),
        "IMMEDIATE_ENTRY_STRATEGY_COUNT": sum(1 for s in strategies if s["strategy_family"] == "immediate"),
        "PULLBACK_ENTRY_STRATEGY_COUNT": sum(1 for s in strategies if s["strategy_family"] == "pullback"),
        "BREAKOUT_CONFIRMATION_ENTRY_STRATEGY_COUNT": sum(1 for s in strategies if s["strategy_family"] == "breakout_confirmation"),
        "RISK_FILTERED_ENTRY_STRATEGY_COUNT": sum(1 for s in strategies if s["strategy_family"] == "risk_filtered"),
        "STAGED_ENTRY_STRATEGY_COUNT": sum(1 for s in strategies if s["strategy_family"] == "staged"),
        "READY_FOR_V20_37_ENTRY_STRATEGY_BACKTEST_EXECUTION": tf(ready_v20_37),
        "READY_FOR_FACTOR_EFFECTIVENESS_ABLATION_AUDIT": tf(gate_ready),
        "READY_FOR_SHADOW_DYNAMIC_WEIGHTING": "FALSE",
        "READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION": "FALSE",
        "NEXT_RECOMMENDED_STEP": "V20.37_ENTRY_STRATEGY_BACKTEST_EXECUTION" if ready_v20_37 else "V20.36_ENTRY_STRATEGY_DESIGN_BLOCKER_RESOLUTION",
    }]
    decision_fields = {
        "v20_35_r2_gate_ready": tf(gate_ready),
        "entry_strategy_matrix_created": "TRUE",
        "entry_strategy_execution_assumptions_created": "TRUE",
        "entry_strategy_readiness_audit_created": "TRUE",
        "ready_for_v20_37_entry_strategy_backtest_execution": tf(ready_v20_37),
        "ready_for_v20_38_factor_effectiveness_ablation_audit": tf(gate_ready),
        "ready_for_shadow_dynamic_weighting": "FALSE",
        "ready_for_portfolio_level_backtest": "FALSE",
        "ready_for_official_trading_or_recommendation": "FALSE",
    }
    next_rows[0].update({k.upper(): v for k, v in decision_fields.items()})

    write_csv(OUT_GATE, gate_review, ["gate_check", "ready_for_v20_36_entry_strategy_matrix_design", "current_top20_leakage_detected", "leakage_blocker_count", "formula_mismatch_count", "forward_return_rows_created", "gate_ready", "review_status"])
    write_csv(OUT_MASTER, strategies, ["strategy_id", "strategy_name", "strategy_family", "entry_trigger", "entry_window_trading_days", "required_price_fields", "required_volume_fields", "required_factor_fields", "benchmark_required_fields", "fallback_policy", "invalidation_policy", "no_fill_policy", "gap_filter_policy", "risk_filter_policy", "expected_future_backtest_price_policy", "partial_fill_simulation_allowed", "staged_entry_allowed", "eligible_for_v20_37_execution", "ineligible_reason"])
    write_csv(OUT_FIELDS, field_rows, ["strategy_id", "required_price_fields", "required_volume_fields", "required_factor_fields", "benchmark_required_fields", "price_fields_available", "volume_fields_available", "factor_fields_available", "benchmark_fields_available"])
    write_csv(OUT_ASSUMPTIONS, assumptions, ["assumption_id", "assumption_text"])
    write_csv(OUT_INVALID, invalid_rows, ["rule_id", "rule_text", "severity"])
    write_csv(OUT_READINESS, readiness_rows, ["strategy_id", "price_field_availability", "volume_availability", "factor_field_availability", "benchmark_availability", "signal_date_and_forward_window_availability", "expected_executable_row_count_estimate", "expected_no_fill_risk_level", "readiness_status", "readiness_reason"])
    write_csv(OUT_NO_FILL, no_fill_rows, ["strategy_id", "no_fill_policy", "preserve_no_fill_rows_for_opportunity_cost", "fallback_policy"])
    write_csv(OUT_RISK, risk_rows, ["strategy_id", "gap_filter_policy", "risk_filter_policy", "benchmark_risk_filter_required", "earnings_blackout_pit_dependency_required"])
    write_csv(OUT_STAGE, stage_rows, ["strategy_id", "staged_entry_allowed", "partial_fill_simulation_allowed", "tranche_count", "stage_policy"])
    write_csv(OUT_BLOCKED, blocked_rows, ["blocked_dependency", "blocked_for_v20_36_executable_entry_strategy", "reason", "current_top20_or_current_ranking_used"])
    write_csv(OUT_PLAN, plan_rows, ["plan_step", "plan_text"])
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))

    report = f"""# V20.36 Entry Strategy Matrix Design

Status: {status}

Design only: TRUE
Entry strategy backtest executed: FALSE
Returns created: FALSE

V20.35-R2 gate ready: {tf(gate_ready)}
Entry strategies defined: {len(strategies)}
Ready strategies: {ready_count}
Ready with limitations: {limited_count}
Design-only placeholders: {placeholder_count}

V20.36 created entry strategy contracts and readiness audits only. It did not execute entry strategy returns, create trading signals, create official recommendations, mutate official rankings or factor weights, produce portfolio metrics, create equity curves, start dynamic weighting, use current Top20 snapshots, or include non-PIT factors in executable entry strategies.
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    read_first = f"""STAGE_NAME: {STAGE_NAME}
STATUS: {status}
DESIGN_ONLY: TRUE
ENTRY_STRATEGY_BACKTEST_EXECUTED: FALSE
RETURNS_CREATED: FALSE
BENCHMARK_RELATIVE_RETURNS_CREATED: FALSE
OFFICIAL_RECOMMENDATION_CREATED: FALSE
TRADING_SIGNAL_CREATED: FALSE
BROKER_ORDER_EXECUTION_CODE_CREATED: FALSE
OFFICIAL_RANKING_MUTATED: FALSE
OFFICIAL_FACTOR_WEIGHTS_MUTATED: FALSE
DYNAMIC_WEIGHTING_STARTED: FALSE
PORTFOLIO_BACKTEST_CREATED: FALSE
EQUITY_CURVE_CREATED: FALSE
PERFORMANCE_CLAIMS_CREATED: FALSE
CURRENT_TOP20_USED_FOR_HISTORICAL_BACKTEST: FALSE
NON_PIT_FACTORS_EXCLUDED: TRUE
V21_OUTPUTS_CREATED: FALSE
V19_21_OUTPUTS_CREATED: FALSE
V20_35_R2_GATE_READY: {tf(gate_ready)}
ENTRY_STRATEGY_COUNT: {len(strategies)}
READY_FOR_V20_37_ENTRY_STRATEGY_BACKTEST_EXECUTION: {tf(ready_v20_37)}
READY_FOR_SHADOW_DYNAMIC_WEIGHTING: FALSE
READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION: FALSE
"""
    write_text(READ_FIRST, read_first)

    required = [OUT_GATE, OUT_MASTER, OUT_FIELDS, OUT_ASSUMPTIONS, OUT_INVALID, OUT_READINESS, OUT_NO_FILL, OUT_RISK, OUT_STAGE, OUT_BLOCKED, OUT_PLAN, OUT_NEXT, REPORT, CURRENT_REPORT, READ_FIRST]
    missing = [path for path in required if not path.exists()]
    if missing:
        raise RuntimeError("Missing V20.36 outputs: " + ", ".join(rel(path) for path in missing))

    print(f"STATUS={status}")
    print("FILES_CHANGED=scripts/v20/v20_36_entry_strategy_matrix_design.py;scripts/v20/run_v20_36_entry_strategy_matrix_design.ps1")
    print("OUTPUTS_CREATED=" + ";".join(rel(path) for path in required))
    print(f"V20_35_R2_GATE_READY={tf(gate_ready)}")
    print(f"ENTRY_STRATEGY_COUNT={len(strategies)}")
    print(f"READY_ENTRY_STRATEGY_COUNT={ready_count}")
    print(f"READY_WITH_LIMITATIONS_STRATEGY_COUNT={limited_count}")
    print(f"BLOCKED_STRATEGY_COUNT={blocked_count}")
    print(f"DESIGN_ONLY_PLACEHOLDER_STRATEGY_COUNT={placeholder_count}")
    print(f"NON_PIT_BLOCKED_DEPENDENCY_COUNT={len(blocked_rows)}")
    print(f"IMMEDIATE_ENTRY_STRATEGY_COUNT={sum(1 for s in strategies if s['strategy_family'] == 'immediate')}")
    print(f"PULLBACK_ENTRY_STRATEGY_COUNT={sum(1 for s in strategies if s['strategy_family'] == 'pullback')}")
    print(f"BREAKOUT_CONFIRMATION_ENTRY_STRATEGY_COUNT={sum(1 for s in strategies if s['strategy_family'] == 'breakout_confirmation')}")
    print(f"RISK_FILTERED_ENTRY_STRATEGY_COUNT={sum(1 for s in strategies if s['strategy_family'] == 'risk_filtered')}")
    print(f"STAGED_ENTRY_STRATEGY_COUNT={sum(1 for s in strategies if s['strategy_family'] == 'staged')}")
    print(f"READY_FOR_V20_37_ENTRY_STRATEGY_BACKTEST_EXECUTION={tf(ready_v20_37)}")
    print(f"READY_FOR_FACTOR_EFFECTIVENESS_ABLATION_AUDIT={tf(gate_ready)}")
    print("READY_FOR_SHADOW_DYNAMIC_WEIGHTING=FALSE")
    print("READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
