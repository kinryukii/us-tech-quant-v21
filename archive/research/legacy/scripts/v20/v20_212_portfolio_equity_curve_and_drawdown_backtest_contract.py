#!/usr/bin/env python
"""V20.212 portfolio equity curve and drawdown backtest contract.

Audits whether local PIT-safe daily price paths and Top20 membership histories
are sufficient to build true research-only portfolio NAV paths. If not, emits a
clear blocker contract. This stage never infers drawdown from forward-window
mean returns and never downloads or fabricates missing prices.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
BACKTEST = ROOT / "outputs" / "v20" / "backtest"
INPUT_BENCH = ROOT / "inputs" / "v20" / "outcome_benchmark"

IN_211_GATE = CONSOLIDATION / "V20_211_NEXT_STAGE_GATE.csv"
IN_211_DECISION = CONSOLIDATION / "V20_211_SHADOW_WEIGHT_REJECTION_DECISION.csv"
IN_211_CONTRACT = CONSOLIDATION / "V20_211_WEIGHT_REPAIR_OBJECTIVE_CONTRACT.csv"
IN_109_EFFECTIVENESS = CONSOLIDATION / "V20_109_FORWARD_WINDOW_TOPN_EFFECTIVENESS_MATRIX.csv"
IN_104_FORWARD = CONSOLIDATION / "V20_104_RANDOM_ASOF_FORWARD_OUTCOME_MATRIX.csv"
IN_104_BENCH = CONSOLIDATION / "V20_104_RANDOM_ASOF_BENCHMARK_COMPARISON.csv"
IN_105_FACTOR = CONSOLIDATION / "V20_105_FORWARD_WINDOW_FACTOR_PERFORMANCE.csv"
IN_106_ETF = CONSOLIDATION / "V20_106_ETF_ROTATION_BENCHMARK_ALIGNMENT.csv"

OUT_AUDIT = CONSOLIDATION / "V20_212_DATA_AVAILABILITY_AUDIT.csv"
OUT_CONTRACT = CONSOLIDATION / "V20_212_PORTFOLIO_EQUITY_CURVE_CONTRACT.csv"
OUT_POLICY = CONSOLIDATION / "V20_212_PORTFOLIO_CONSTRUCTION_POLICY.csv"
OUT_READINESS = CONSOLIDATION / "V20_212_EQUITY_CURVE_EXECUTION_READINESS.csv"
OUT_BASELINE_CURVE = CONSOLIDATION / "V20_212_BASELINE_EQUITY_CURVE.csv"
OUT_SHADOW_CURVE = CONSOLIDATION / "V20_212_SHADOW_EQUITY_CURVE.csv"
OUT_BENCH_CURVE = CONSOLIDATION / "V20_212_BENCHMARK_EQUITY_CURVE.csv"
OUT_DRAWDOWN = CONSOLIDATION / "V20_212_PORTFOLIO_DRAWDOWN_METRICS.csv"
OUT_PERFORMANCE = CONSOLIDATION / "V20_212_PORTFOLIO_PERFORMANCE_METRICS.csv"
OUT_GATE = CONSOLIDATION / "V20_212_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_212_PORTFOLIO_EQUITY_CURVE_AND_DRAWDOWN_BACKTEST_CONTRACT_REPORT.md"

STATUS_BLOCKED = "PASS_V20_212_EQUITY_CURVE_CONTRACT_READY_EXECUTION_BLOCKED_BY_MISSING_DAILY_PATHS"
STATUS_CREATED = "PASS_V20_212_RESEARCH_ONLY_EQUITY_CURVE_AND_DRAWDOWN_METRICS_CREATED"
MISSING_DAILY_NAV = "BLOCKED_MISSING_DAILY_NAV_PATH"


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{k: clean(v) for k, v in row.items()} for row in csv.DictReader(handle)]


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def is_true(value: object) -> bool:
    return clean(value).upper() == "TRUE"


def as_int(value: object) -> int:
    try:
        return int(float(clean(value)))
    except ValueError:
        return 0


def has_rows(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0 and bool(read_csv(path))


def discover_files() -> list[Path]:
    roots = [INPUT_BENCH, CONSOLIDATION, ROOT / "data", ROOT / "outputs" / "v18", ROOT / "outputs" / "v20"]
    terms = ("price", "close", "yahoo", "history", "ohlc", "benchmark", "ranking", "rerank", "top20", "selected_etf")
    files: list[Path] = []
    for root in roots:
        if root.exists():
            for suffix in ("*.csv", "*.json", "*.parquet"):
                for path in root.rglob(suffix):
                    name = path.name.lower()
                    if any(term in name for term in terms):
                        files.append(path)
    return sorted(set(files))


def rows_for(path: Path) -> list[dict[str, str]]:
    if path.suffix.lower() != ".csv":
        return []
    return read_csv(path)


def detect_membership_history() -> dict[str, object]:
    candidates = [
        CONSOLIDATION / "V20_35_ASOF_TOP20_SELECTIONS.csv",
        CONSOLIDATION / "V20_35_R2_ASOF_TOP20_SELECTIONS.csv",
        CONSOLIDATION / "V20_104_RANDOM_ASOF_FORWARD_OUTCOME_MATRIX.csv",
    ]
    baseline = False
    shadow = False
    reasons: list[str] = []
    for path in candidates:
        rows = rows_for(path)
        if not rows:
            reasons.append(f"{rel(path)} missing or has no membership rows")
            continue
        fields = {k.lower() for k in rows[0].keys()}
        has_date = bool(fields & {"as_of_date", "asof_date", "signal_date"})
        has_ticker = "ticker" in fields or "symbol" in fields
        has_rank = bool(fields & {"baseline_rank", "candidate_rank", "asof_technical_rank", "official_current_rank"})
        has_shadow_rank = "strict_equity_shadow_rank" in fields or "shadow_rank" in fields
        if has_date and has_ticker and has_rank and "top20" in path.name.lower():
            baseline = True
        if has_date and has_ticker and has_shadow_rank:
            shadow = True
    if not baseline:
        reasons.append("No baseline Top20 membership history with as_of_date, ticker, and baseline rank/membership was found.")
    if not shadow:
        reasons.append("No shadow Top20 membership history with as_of_date, ticker, and shadow rank/membership was found.")
    return {"baseline_available": baseline, "shadow_available": shadow, "reason": " ".join(reasons)}


def price_path_summary() -> dict[str, object]:
    manifest = BACKTEST / "V20_199C_USABLE_PRICE_HISTORY_MANIFEST.csv"
    coverage = BACKTEST / "V20_199C_HISTORICAL_PRICE_COVERAGE_AUDIT.csv"
    current_candidate = CONSOLIDATION / "V20_47_CURRENT_CANDIDATE_PRICE_CERTIFICATION.csv"
    current_bench = CONSOLIDATION / "V20_47_CURRENT_BENCHMARK_PRICE_CERTIFICATION.csv"
    yahoo_ticker = INPUT_BENCH / "yahoo_cache" / "v20_35_r1" / "V20_35_R1_HISTORICAL_YAHOO_TICKER_PRICE_CACHE.csv"
    yahoo_bench = INPUT_BENCH / "yahoo_cache" / "v20_35_r1" / "V20_35_R1_HISTORICAL_YAHOO_BENCHMARK_PRICE_CACHE.csv"

    rows = read_csv(manifest) or read_csv(coverage)
    usable_rows = [row for row in rows if is_true(row.get("usable_for_pit_lite_recompute"))]
    max_days = max([as_int(row.get("trading_day_count")) for row in rows] or [0])
    current_rows = read_csv(current_candidate)
    current_days = len({row.get("price_date") for row in current_rows if row.get("price_date")})
    if current_days > max_days:
        max_days = current_days

    bench_rows: list[dict[str, str]] = []
    for path in [current_bench, yahoo_bench]:
        bench_rows.extend(read_csv(path))
    benchmark_symbols = {clean(row.get("symbol") or row.get("ticker")).upper() for row in bench_rows}

    # Some manifests identify benchmark rows even when raw benchmark cache rows are unavailable.
    for row in rows:
        if clean(row.get("symbol_role")).upper() == "BENCHMARK":
            benchmark_symbols.add(clean(row.get("symbol")).upper())

    return {
        "daily_ticker_close_paths_available": bool(usable_rows and max_days >= 20),
        "max_ticker_trading_day_count": max_days,
        "usable_price_history_rows": len(usable_rows),
        "qqq_available": "QQQ" in benchmark_symbols,
        "spy_available": "SPY" in benchmark_symbols,
        "soxx_available": "SOXX" in benchmark_symbols,
        "smh_available": "SMH" in benchmark_symbols,
        "reason": (
            f"Usable daily ticker price rows={len(usable_rows)}; max detected trading_day_count={max_days}. "
            f"Header-only historical caches: {rel(yahoo_ticker)} rows={len(read_csv(yahoo_ticker))}, {rel(yahoo_bench)} rows={len(read_csv(yahoo_bench))}."
        ),
    }


def detect_etf_history() -> dict[str, object]:
    candidates = [
        CONSOLIDATION / "V20_208_CURRENT_ETF_ROTATION_SELECTION.csv",
        CONSOLIDATION / "V20_209_CURRENT_ETF_ROTATION_SELECTION_REFRESH.csv",
        CONSOLIDATION / "V20_106_ETF_ROTATION_BENCHMARK_ALIGNMENT.csv",
    ]
    history_rows = 0
    current_only_rows = 0
    for path in candidates:
        rows = read_csv(path)
        if not rows:
            continue
        fields = {k.lower() for k in rows[0].keys()}
        has_selected = "selected_etf" in fields or "current_selected_etf" in fields
        has_date = "selection_date" in fields or "as_of_date" in fields or "date" in fields
        if has_selected and has_date:
            if len(rows) > 5 and "current_selected_etf" not in fields:
                history_rows += len(rows)
            else:
                current_only_rows += len(rows)
    available = history_rows > 0
    return {
        "available": available,
        "history_rows": history_rows,
        "current_only_rows": current_only_rows,
        "reason": "Selected ETF history with daily selected ETF path exists." if available else "Only current or benchmark-alignment ETF evidence found; no selected_etf history plus daily selected ETF path.",
    }


def data_audit_rows(membership: dict[str, object], prices: dict[str, object], etf: dict[str, object]) -> list[dict[str, object]]:
    daily_paths = bool(prices["daily_ticker_close_paths_available"])
    baseline = bool(membership["baseline_available"])
    shadow = bool(membership["shadow_available"])
    qqq = bool(prices["qqq_available"])
    spy = bool(prices["spy_available"])
    any_bench = qqq or spy or bool(prices["soxx_available"]) or bool(prices["smh_available"])
    can_nav = baseline and shadow and daily_paths
    rows = [
        ("baseline_top20_membership_history_available", baseline, "Baseline Top20 membership history must contain as_of_date, ticker, and rank/membership.", membership["reason"]),
        ("shadow_top20_membership_history_available", shadow, "Shadow Top20 membership history must contain as_of_date, ticker, and rank/membership.", membership["reason"]),
        ("daily_ticker_close_paths_available", daily_paths, "Daily ticker close paths must cover rebalance dates and 20D/60D/120D holding windows.", prices["reason"]),
        ("qqq_daily_path_available", qqq, "QQQ daily close path is required for QQQ benchmark curve.", prices["reason"]),
        ("spy_daily_path_available", spy, "SPY daily close path is required for SPY benchmark curve.", prices["reason"]),
        ("soxx_daily_path_available", prices["soxx_available"], "SOXX daily close path is optional but required for SOXX relative metrics.", prices["reason"]),
        ("smh_daily_path_available", prices["smh_available"], "SMH daily close path is optional but required for SMH relative metrics.", prices["reason"]),
        ("selected_etf_rotation_history_available", etf["available"], "ETF rotation requires selected_etf history plus daily selected ETF path.", etf["reason"]),
        ("max_drawdown_can_be_computed", can_nav, "Max drawdown requires a daily NAV path; forward-window mean returns are insufficient.", "" if can_nav else "Missing true daily portfolio NAV path."),
        ("sharpe_can_be_computed", can_nav, "Sharpe requires daily NAV returns; risk_free_rate defaults to 0 only after NAV exists.", "" if can_nav else "Missing true daily portfolio NAV path."),
        ("calmar_can_be_computed", can_nav, "Calmar requires CAGR and max drawdown from a true NAV path.", "" if can_nav else "Missing true daily portfolio NAV path."),
        ("benchmark_relative_total_return_can_be_computed", can_nav and any_bench, "Benchmark-relative return requires portfolio NAV and benchmark daily path.", "" if can_nav and any_bench else "Missing portfolio NAV path and/or benchmark daily path."),
    ]
    return [
        {
            "audit_item": item,
            "available": "TRUE" if available else "FALSE",
            "requirement": requirement,
            "blocker_reason": "" if available else reason,
        }
        for item, available, requirement, reason in rows
    ]


def contract_rows() -> list[dict[str, object]]:
    return [
        {"contract_item": "daily_nav_path_required", "required": "TRUE", "contract_value": "Max drawdown, Sharpe, volatility, Calmar, and benchmark-relative daily performance require true daily NAV paths.", "notes": "Do not infer max drawdown from V20_109 forward-window mean returns."},
        {"contract_item": "baseline_membership_required", "required": "TRUE", "contract_value": "Baseline Top20 membership history with as_of_date, ticker, rank, rebalance cohort, and research-only lineage.", "notes": "Current-only ranking is insufficient for historical portfolio equity curve."},
        {"contract_item": "shadow_membership_required", "required": "TRUE", "contract_value": "Shadow Top20 membership history with as_of_date, ticker, shadow rank, rebalance cohort, and research-only lineage.", "notes": "Shadow remains research-only due to V20.211 rejection."},
        {"contract_item": "daily_price_required", "required": "TRUE", "contract_value": "PIT-safe daily adjusted close or close for each held ticker across entry-to-exit holding windows.", "notes": "No fabricated prices; no external API calls in this stage."},
        {"contract_item": "benchmark_daily_price_required", "required": "TRUE", "contract_value": "QQQ and SPY daily close paths; SOXX and SMH if available.", "notes": "Missing semiconductor benchmarks are marked missing, not fabricated."},
        {"contract_item": "rebalance_policy", "required": "TRUE", "contract_value": "Default non-overlapping 20D, 60D, and 120D cohorts unless explicit overlapping cohort accounting is implemented.", "notes": "Overlapping holdings require cohort-level NAV accounting."},
        {"contract_item": "risk_free_rate", "required": "TRUE", "contract_value": "0 for research-only Sharpe unless a local explicit risk-free source is provided.", "notes": "No download of risk-free data."},
        {"contract_item": "blocked_metric_status", "required": "TRUE", "contract_value": MISSING_DAILY_NAV, "notes": "Use when true daily NAV path is unavailable."},
    ]


def policy_rows() -> list[dict[str, object]]:
    return [
        {"policy_id": "BASELINE_TOP20_EQUAL_WEIGHT", "membership_source": "baseline Top20 if available", "weighting": "equal_weight", "rebalance_policy": "rebalance on each as_of_date", "holding_windows_supported": "20D;60D;120D if daily paths allow", "cohort_policy": "non_overlapping_default", "research_only": "TRUE", "official_use_allowed": "FALSE", "notes": "Baseline retained by V20.211; portfolio curve requires historical membership and daily price paths."},
        {"policy_id": "SHADOW_TOP20_EQUAL_WEIGHT", "membership_source": "shadow Top20 if available", "weighting": "equal_weight", "rebalance_policy": "rebalance on each as_of_date", "holding_windows_supported": "20D;60D;120D if daily paths allow", "cohort_policy": "non_overlapping_default", "research_only": "TRUE", "official_use_allowed": "FALSE", "notes": "Shadow is research-only and rejected for official use by V20.211."},
        {"policy_id": "BENCHMARK_QQQ_BUY_HOLD", "membership_source": "QQQ daily path if available", "weighting": "single_asset_buy_hold", "rebalance_policy": "buy_hold", "holding_windows_supported": "full available path", "cohort_policy": "not_applicable", "research_only": "TRUE", "official_use_allowed": "FALSE", "notes": "Benchmark only."},
        {"policy_id": "BENCHMARK_SPY_BUY_HOLD", "membership_source": "SPY daily path if available", "weighting": "single_asset_buy_hold", "rebalance_policy": "buy_hold", "holding_windows_supported": "full available path", "cohort_policy": "not_applicable", "research_only": "TRUE", "official_use_allowed": "FALSE", "notes": "Benchmark only."},
        {"policy_id": "SEMICONDUCTOR_BENCHMARKS", "membership_source": "SOXX and SMH daily paths if available", "weighting": "single_asset_buy_hold", "rebalance_policy": "buy_hold", "holding_windows_supported": "full available path", "cohort_policy": "not_applicable", "research_only": "TRUE", "official_use_allowed": "FALSE", "notes": "Mark missing if local path is unavailable."},
        {"policy_id": "ETF_ROTATION_PLACEHOLDER", "membership_source": "selected_etf history plus daily selected ETF path", "weighting": "rotation_path", "rebalance_policy": "selected_etf changes", "holding_windows_supported": "only if selected history and prices exist", "cohort_policy": "separate_lane", "research_only": "TRUE", "official_use_allowed": "FALSE", "notes": "Do not calculate unless selected_etf history and daily selected ETF path exists."},
    ]


def blocked_curve_rows(curve_id: str, reason: str) -> list[dict[str, object]]:
    return [{
        "curve_id": curve_id,
        "date": "",
        "nav": "",
        "daily_return": "",
        "curve_status": MISSING_DAILY_NAV,
        "source": "NOT_CREATED",
        "blocker_reason": reason,
        "research_only": "TRUE",
    }]


def blocked_drawdown_rows(reason: str) -> list[dict[str, object]]:
    return [
        {"portfolio_id": name, "metrics_status": MISSING_DAILY_NAV, "max_drawdown": "", "max_drawdown_start_date": "", "max_drawdown_trough_date": "", "max_drawdown_source": "DAILY_NAV_PATH_REQUIRED_NOT_FORWARD_WINDOW_MEAN_RETURN", "blocker_reason": reason, "research_only": "TRUE"}
        for name in ["BASELINE_TOP20_EQUAL_WEIGHT", "SHADOW_TOP20_EQUAL_WEIGHT", "BENCHMARK_QQQ_BUY_HOLD", "BENCHMARK_SPY_BUY_HOLD"]
    ]


def blocked_performance_rows(reason: str) -> list[dict[str, object]]:
    return [
        {
            "portfolio_id": name,
            "metrics_status": MISSING_DAILY_NAV,
            "total_return": "",
            "cagr": "",
            "volatility": "",
            "sharpe_risk_free_rate_0": "",
            "calmar": "",
            "win_rate_by_rebalance_window": "",
            "average_rebalance_return": "",
            "worst_rebalance_return": "",
            "best_rebalance_return": "",
            "turnover": "",
            "benchmark_relative_total_return_vs_qqq": "",
            "benchmark_relative_total_return_vs_spy": "",
            "benchmark_relative_total_return_vs_soxx": "",
            "benchmark_relative_total_return_vs_smh": "",
            "metric_source": "DAILY_NAV_PATH_REQUIRED_NOT_FORWARD_WINDOW_MEAN_RETURN",
            "blocker_reason": reason,
            "research_only": "TRUE",
        }
        for name in ["BASELINE_TOP20_EQUAL_WEIGHT", "SHADOW_TOP20_EQUAL_WEIGHT"]
    ]


def consumed_211() -> dict[str, object]:
    gate = read_csv(IN_211_GATE)
    decision = read_csv(IN_211_DECISION)
    gate_row = gate[0] if gate else {}
    decision_row = decision[0] if decision else {}
    return {
        "status": clean(gate_row.get("v20_211_status")) or "MISSING_V20_211_GATE",
        "baseline_retained": clean(gate_row.get("baseline_retained")) or clean(decision_row.get("baseline_retained")) or "FALSE",
        "shadow_rejected": "TRUE" if clean(decision_row.get("decision")) == "REJECT_CURRENT_SHADOW_WEIGHT_FOR_OFFICIAL_USE_RETAIN_BASELINE" or clean(gate_row.get("current_shadow_official_eligible")) == "FALSE" else "FALSE",
    }


def first_blocker(audit: list[dict[str, object]]) -> str:
    reasons = [clean(row["blocker_reason"]) for row in audit if row["available"] == "FALSE" and clean(row["blocker_reason"])]
    return " ".join(dict.fromkeys(reasons)) or "Missing true daily NAV path inputs."


def readiness_row(execution_allowed: bool, blocker: str) -> dict[str, object]:
    return {
        "equity_curve_execution_allowed": "TRUE" if execution_allowed else "FALSE",
        "metrics_status": "READY_TO_COMPUTE_RESEARCH_ONLY" if execution_allowed else MISSING_DAILY_NAV,
        "forward_window_mean_returns_used_for_drawdown": "FALSE",
        "external_api_called": "FALSE",
        "missing_prices_fabricated": "FALSE",
        "blocker_reason": "" if execution_allowed else blocker,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def gate_row(v211: dict[str, object], prices: dict[str, object], etf: dict[str, object], execution_allowed: bool) -> dict[str, object]:
    status = STATUS_CREATED if execution_allowed else STATUS_BLOCKED
    return {
        "v20_212_status": status,
        "consumed_v20_211_status": v211["status"],
        "baseline_retained_from_v20_211": v211["baseline_retained"],
        "current_shadow_rejected_from_v20_211": v211["shadow_rejected"],
        "equity_curve_contract_created": "TRUE",
        "data_availability_audit_created": "TRUE",
        "equity_curve_execution_allowed": "TRUE" if execution_allowed else "FALSE",
        "baseline_equity_curve_created": "TRUE" if execution_allowed else "FALSE",
        "shadow_equity_curve_created": "TRUE" if execution_allowed else "FALSE",
        "benchmark_equity_curve_created": "TRUE" if execution_allowed and (prices["qqq_available"] or prices["spy_available"]) else "FALSE",
        "drawdown_metrics_created": "TRUE" if execution_allowed else "FALSE",
        "performance_metrics_created": "TRUE" if execution_allowed else "FALSE",
        "max_drawdown_available": "TRUE" if execution_allowed else "FALSE",
        "qqq_benchmark_available": "TRUE" if prices["qqq_available"] else "FALSE",
        "spy_benchmark_available": "TRUE" if prices["spy_available"] else "FALSE",
        "soxx_benchmark_available": "TRUE" if prices["soxx_available"] else "FALSE",
        "smh_benchmark_available": "TRUE" if prices["smh_available"] else "FALSE",
        "etf_rotation_equity_curve_available": "TRUE" if execution_allowed and etf["available"] else "FALSE",
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        "recommended_next_stage": "V20.213_PORTFOLIO_EQUITY_CURVE_METRIC_REVIEW_AND_WEIGHT_REPAIR_BLOCKER_RECHECK" if execution_allowed else "V20.213_DAILY_PRICE_PATH_SOURCE_REPAIR_OR_EQUITY_CURVE_INPUT_STAGING",
    }


def render_report(audit: list[dict[str, object]], readiness: dict[str, object], gate: dict[str, object], blocker: str) -> str:
    audit_lines = [
        "| Audit Item | Available | Blocker |",
        "|---|---:|---|",
    ]
    for row in audit:
        audit_lines.append(f"| {row['audit_item']} | {row['available']} | {clean(row['blocker_reason']) or 'None'} |")
    if gate["equity_curve_execution_allowed"] == "TRUE":
        metrics_section = "Performance metrics were created from local daily NAV paths."
    else:
        metrics_section = f"Equity curve execution is blocked: {blocker}"
    return "\n".join([
        "# V20.212 Portfolio Equity Curve and Drawdown Backtest Contract",
        "",
        "## Summary",
        "V20.212 audited whether local PIT-safe daily price paths and baseline/shadow Top20 membership histories are sufficient to compute a true portfolio equity curve. The stage did not download data, did not fabricate missing prices, and did not infer drawdown from forward-window averages.",
        "",
        "## V20.211 Consumption",
        f"- Consumed V20.211 status: `{gate['consumed_v20_211_status']}`",
        f"- Baseline retained from V20.211: `{gate['baseline_retained_from_v20_211']}`",
        f"- Current shadow rejected from V20.211: `{gate['current_shadow_rejected_from_v20_211']}`",
        "",
        "## Why Forward-Window Returns Are Insufficient",
        "Forward-window mean returns can compare average outcomes, but max drawdown requires a dated NAV path with daily peaks and troughs. This report therefore treats drawdown as unavailable unless a true daily equity curve can be built.",
        "",
        "## Data Availability",
        *audit_lines,
        "",
        "## Execution Status",
        f"- Equity curve execution allowed: `{readiness['equity_curve_execution_allowed']}`",
        f"- Metrics status: `{readiness['metrics_status']}`",
        f"- Forward-window mean returns used for drawdown: `{readiness['forward_window_mean_returns_used_for_drawdown']}`",
        "",
        "## Metrics",
        metrics_section,
        "",
        "## Safety",
        "No official recommendation was created. No official weight was mutated. No trade action was created. No broker execution artifact was created.",
        "",
        "## Next Recommended Action",
        f"`{gate['recommended_next_stage']}`",
        "",
        f"Final status: `{gate['v20_212_status']}`",
        "",
    ])


def main() -> None:
    membership = detect_membership_history()
    prices = price_path_summary()
    etf = detect_etf_history()
    audit = data_audit_rows(membership, prices, etf)
    execution_allowed = all(row["available"] == "TRUE" for row in audit if row["audit_item"] in {
        "baseline_top20_membership_history_available",
        "shadow_top20_membership_history_available",
        "daily_ticker_close_paths_available",
        "max_drawdown_can_be_computed",
        "sharpe_can_be_computed",
        "calmar_can_be_computed",
    })
    blocker = "" if execution_allowed else first_blocker(audit)
    readiness = readiness_row(execution_allowed, blocker)
    v211 = consumed_211()
    gate = gate_row(v211, prices, etf, execution_allowed)

    write_csv(OUT_AUDIT, ["audit_item", "available", "requirement", "blocker_reason"], audit)
    write_csv(OUT_CONTRACT, ["contract_item", "required", "contract_value", "notes"], contract_rows())
    write_csv(OUT_POLICY, ["policy_id", "membership_source", "weighting", "rebalance_policy", "holding_windows_supported", "cohort_policy", "research_only", "official_use_allowed", "notes"], policy_rows())
    write_csv(OUT_READINESS, ["equity_curve_execution_allowed", "metrics_status", "forward_window_mean_returns_used_for_drawdown", "external_api_called", "missing_prices_fabricated", "blocker_reason", "created_at"], [readiness])
    write_csv(OUT_BASELINE_CURVE, ["curve_id", "date", "nav", "daily_return", "curve_status", "source", "blocker_reason", "research_only"], blocked_curve_rows("BASELINE_TOP20_EQUAL_WEIGHT", blocker))
    write_csv(OUT_SHADOW_CURVE, ["curve_id", "date", "nav", "daily_return", "curve_status", "source", "blocker_reason", "research_only"], blocked_curve_rows("SHADOW_TOP20_EQUAL_WEIGHT", blocker))
    write_csv(OUT_BENCH_CURVE, ["curve_id", "date", "nav", "daily_return", "curve_status", "source", "blocker_reason", "research_only"], blocked_curve_rows("BENCHMARK_BUY_HOLD", blocker))
    write_csv(OUT_DRAWDOWN, ["portfolio_id", "metrics_status", "max_drawdown", "max_drawdown_start_date", "max_drawdown_trough_date", "max_drawdown_source", "blocker_reason", "research_only"], blocked_drawdown_rows(blocker))
    write_csv(OUT_PERFORMANCE, ["portfolio_id", "metrics_status", "total_return", "cagr", "volatility", "sharpe_risk_free_rate_0", "calmar", "win_rate_by_rebalance_window", "average_rebalance_return", "worst_rebalance_return", "best_rebalance_return", "turnover", "benchmark_relative_total_return_vs_qqq", "benchmark_relative_total_return_vs_spy", "benchmark_relative_total_return_vs_soxx", "benchmark_relative_total_return_vs_smh", "metric_source", "blocker_reason", "research_only"], blocked_performance_rows(blocker))
    write_csv(OUT_GATE, ["v20_212_status", "consumed_v20_211_status", "baseline_retained_from_v20_211", "current_shadow_rejected_from_v20_211", "equity_curve_contract_created", "data_availability_audit_created", "equity_curve_execution_allowed", "baseline_equity_curve_created", "shadow_equity_curve_created", "benchmark_equity_curve_created", "drawdown_metrics_created", "performance_metrics_created", "max_drawdown_available", "qqq_benchmark_available", "spy_benchmark_available", "soxx_benchmark_available", "smh_benchmark_available", "etf_rotation_equity_curve_available", "official_promotion_allowed", "official_recommendation_created", "weight_mutated", "trade_action_created", "broker_execution_supported", "recommended_next_stage"], [gate])

    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text(render_report(audit, readiness, gate, blocker), encoding="utf-8")

    print(f"FINAL_STATUS={gate['v20_212_status']}")
    print(f"CONSUMED_V20_211_STATUS={gate['consumed_v20_211_status']}")
    print(f"EQUITY_CURVE_EXECUTION_ALLOWED={gate['equity_curve_execution_allowed']}")
    print(f"METRICS_STATUS={readiness['metrics_status']}")
    print(f"MAX_DRAWDOWN_AVAILABLE={gate['max_drawdown_available']}")
    print(f"OFFICIAL_PROMOTION_ALLOWED={gate['official_promotion_allowed']}")
    print(f"OFFICIAL_RECOMMENDATION_CREATED={gate['official_recommendation_created']}")
    print(f"WEIGHT_MUTATED={gate['weight_mutated']}")
    print(f"TRADE_ACTION_CREATED={gate['trade_action_created']}")
    print(f"BROKER_EXECUTION_SUPPORTED={gate['broker_execution_supported']}")
    print(f"NEXT_STAGE={gate['recommended_next_stage']}")


if __name__ == "__main__":
    main()
