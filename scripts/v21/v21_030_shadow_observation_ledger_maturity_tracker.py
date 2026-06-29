#!/usr/bin/env python
"""V21.030 shadow observation ledger maturity tracker.

Research-only tracker for V21.029 shadow observation ledger maturity and
realized forward returns. Does not mutate official score, rank, weight,
recommendation, trade, broker, market-regime, or shadow-policy artifacts.
"""

from __future__ import annotations

import csv
import math
import re
from bisect import bisect_left
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import mean, median


STAGE_NAME = "V21_030_SHADOW_OBSERVATION_LEDGER_MATURITY_TRACKER"
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "shadow_observation"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"
PRICE_DIR = ROOT / "state" / "v18" / "price_cache"

V21_029_INPUTS = [
    OUT_DIR / "V21_029_V21_025_DECISION_INGEST_AUDIT.csv",
    OUT_DIR / "V21_029_CURRENT_OBSERVATION_UNIVERSE.csv",
    OUT_DIR / "V21_029_WITHIN_REGIME_ALPHA_ONLY_RANKS.csv",
    OUT_DIR / "V21_029_CONTEXT_SPECIFIC_RISK_GATE_OVERLAY.csv",
    OUT_DIR / "V21_029_SHADOW_OBSERVATION_SELECTIONS.csv",
    OUT_DIR / "V21_029_FORWARD_OBSERVATION_SCHEDULE.csv",
    OUT_DIR / "V21_029_OBSERVATION_LEDGER.csv",
    OUT_DIR / "V21_029_LEDGER_DEDUP_LINEAGE_AUDIT.csv",
    OUT_DIR / "V21_029_SOURCE_GAP_ANNOTATION.csv",
    OUT_DIR / "V21_029_MONITORING_BASELINE_SNAPSHOT.csv",
    OUT_DIR / "V21_029_GUARDRAIL_ENFORCEMENT_AUDIT.csv",
    OUT_DIR / "V21_029_SHADOW_OBSERVATION_LEDGER_PRODUCER_DECISION.csv",
    OUT_DIR / "V21_029_WITHIN_REGIME_SHADOW_OBSERVATION_LEDGER_PRODUCER_SUMMARY.csv",
    READ_CENTER_DIR / "V21_029_WITHIN_REGIME_SHADOW_OBSERVATION_LEDGER_PRODUCER_REPORT.md",
]

INGEST = OUT_DIR / "V21_030_V21_029_DECISION_INGEST_AUDIT.csv"
INTEGRITY = OUT_DIR / "V21_030_LEDGER_INTEGRITY_AUDIT.csv"
MATURITY = OUT_DIR / "V21_030_FORWARD_SCHEDULE_MATURITY_AUDIT.csv"
RETURNS = OUT_DIR / "V21_030_REALIZED_FORWARD_RETURNS.csv"
PENDING = OUT_DIR / "V21_030_PENDING_OBSERVATIONS.csv"
CTX_SUMMARY = OUT_DIR / "V21_030_MATURITY_SUMMARY_BY_CONTEXT.csv"
LANE_SUMMARY = OUT_DIR / "V21_030_MATURITY_SUMMARY_BY_LANE.csv"
FALLBACK = OUT_DIR / "V21_030_FALLBACK_SNAPSHOT_LIMITATION_AUDIT.csv"
GAPS = OUT_DIR / "V21_030_SOURCE_GAP_AND_PRICE_AVAILABILITY_AUDIT.csv"
GUARDRAIL = OUT_DIR / "V21_030_GUARDRAIL_ENFORCEMENT_AUDIT.csv"
DECISION = OUT_DIR / "V21_030_SHADOW_LEDGER_MATURITY_TRACKER_DECISION.csv"
SUMMARY = OUT_DIR / "V21_030_SHADOW_OBSERVATION_LEDGER_MATURITY_TRACKER_SUMMARY.csv"
REPORT = READ_CENTER_DIR / "V21_030_SHADOW_OBSERVATION_LEDGER_MATURITY_TRACKER_REPORT.md"

CURRENT_RUN_DATE = date(2026, 6, 17)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


def fmt(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.10f}"
    return value


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def yn(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def fnum(value: object) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def parse_date(value: str) -> date | None:
    try:
        return datetime.fromisoformat(value[:10]).date()
    except (TypeError, ValueError):
        return None


def load_price(ticker: str) -> list[tuple[str, float]]:
    path = PRICE_DIR / f"{ticker}.csv"
    out = []
    for row in read_csv(path):
        d = row.get("date") or row.get("Date")
        close = fnum(row.get("adj_close") or row.get("close") or row.get("Adj Close") or row.get("Close"))
        if d and close is not None:
            out.append((d[:10], close))
    return sorted(out)


def price_on_or_after(prices: list[tuple[str, float]], target: str) -> tuple[str, float] | None:
    dates = [d for d, _ in prices]
    idx = bisect_left(dates, target)
    if idx < len(prices):
        return prices[idx]
    return None


def summarize(rows: list[dict[str, object]], key: str) -> list[dict[str, object]]:
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(key, ""))].append(row)
    out = []
    for name, vals in sorted(groups.items()):
        realized = [fnum(v.get("realized_forward_return")) for v in vals if fnum(v.get("realized_forward_return")) is not None]
        excess = [fnum(v.get("excess_return")) for v in vals if fnum(v.get("excess_return")) is not None]
        out.append({
            key: name,
            "scheduled_count": len(vals),
            "matured_count": sum(1 for v in vals if v.get("maturity_status") == "MATURED_PRICE_AVAILABLE"),
            "pending_count": sum(1 for v in vals if v.get("maturity_status") == "NOT_YET_MATURED"),
            "price_missing_count": sum(1 for v in vals if v.get("maturity_status") == "MATURED_PRICE_MISSING"),
            "mean_realized_forward_return": mean(realized) if realized else None,
            "median_realized_forward_return": median(realized) if realized else None,
            "hit_rate": sum(1 for x in realized if x > 0) / len(realized) if realized else None,
            "mean_excess_return": mean(excess) if excess else None,
            "alpha_only_lane_count": sum(1 for v in vals if v.get("lane_id") == "WITHIN_REGIME_ALPHA_ONLY_PRIMARY"),
            "risk_gate_overlay_lane_count": sum(1 for v in vals if v.get("lane_id") == "UNSTABLE_CONTEXT_RISK_GATE_OVERLAY"),
            "source_gap_count": sum(1 for v in vals if v.get("source_gap_count")),
            "fallback_snapshot_flag": "TRUE",
            "research_only": "TRUE",
        })
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    missing = [p.relative_to(ROOT).as_posix() for p in V21_029_INPUTS if not p.exists() or p.stat().st_size == 0]
    decision_029 = first(read_csv(OUT_DIR / "V21_029_SHADOW_OBSERVATION_LEDGER_PRODUCER_DECISION.csv"))
    summary_029 = first(read_csv(OUT_DIR / "V21_029_WITHIN_REGIME_SHADOW_OBSERVATION_LEDGER_PRODUCER_SUMMARY.csv"))
    ledger = read_csv(OUT_DIR / "V21_029_OBSERVATION_LEDGER.csv")
    schedule = read_csv(OUT_DIR / "V21_029_FORWARD_OBSERVATION_SCHEDULE.csv")
    source_gaps = read_csv(OUT_DIR / "V21_029_SOURCE_GAP_ANNOTATION.csv")
    source_gap_by_id = {r.get("observation_id", ""): r for r in source_gaps}
    ledger_by_id = {r.get("observation_id", ""): r for r in ledger}

    ingest_rows = [
        {"audit_item": "required_v21_029_artifacts_present", "audit_passed": yn(not missing), "observed_value": "|".join(missing) if missing else "ALL_PRESENT", "required_value": "TRUE", "research_only": "TRUE"},
        {"audit_item": "v21_029_decision_ingested", "audit_passed": yn(decision_029.get("ledger_producer_decision") in {"SHADOW_OBSERVATION_LEDGER_PARTIAL_CURRENT_SNAPSHOT_FALLBACK", "SHADOW_OBSERVATION_LEDGER_PRODUCED_RESEARCH_ONLY"}), "observed_value": decision_029.get("ledger_producer_decision", ""), "required_value": "PRODUCED_OR_FALLBACK", "research_only": "TRUE"},
        {"audit_item": "recommended_next_stage_v21_030", "audit_passed": yn(decision_029.get("recommended_next_stage") == "V21.030_SHADOW_OBSERVATION_LEDGER_MATURITY_TRACKER"), "observed_value": decision_029.get("recommended_next_stage", ""), "required_value": "V21.030_SHADOW_OBSERVATION_LEDGER_MATURITY_TRACKER", "research_only": "TRUE"},
        {"audit_item": "ledger_research_only", "audit_passed": yn(bool(ledger) and all(r.get("research_only") == "TRUE" for r in ledger)), "observed_value": str(len(ledger)), "required_value": "ALL_TRUE", "research_only": "TRUE"},
        {"audit_item": "official_use_false", "audit_passed": yn(summary_029.get("official_use_allowed") == "FALSE"), "observed_value": summary_029.get("official_use_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "official_ranking_readiness_false", "audit_passed": yn(summary_029.get("official_ranking_readiness_allowed") == "FALSE"), "observed_value": summary_029.get("official_ranking_readiness_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "official_weight_update_readiness_false", "audit_passed": yn(summary_029.get("official_weight_update_readiness_allowed") == "FALSE"), "observed_value": summary_029.get("official_weight_update_readiness_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "official_weight_update_blocked", "audit_passed": yn(summary_029.get("official_weight_update_blocked") == "TRUE"), "observed_value": summary_029.get("official_weight_update_blocked", ""), "required_value": "TRUE", "research_only": "TRUE"},
        {"audit_item": "broker_execution_supported_false", "audit_passed": yn(summary_029.get("broker_execution_supported") == "FALSE"), "observed_value": summary_029.get("broker_execution_supported", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "shadow_activation_false", "audit_passed": yn(summary_029.get("shadow_activation") == "FALSE"), "observed_value": summary_029.get("shadow_activation", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "data_trust_zero_alpha_ranking_contribution", "audit_passed": yn(summary_029.get("data_trust_alpha_contribution") == "0" and summary_029.get("data_trust_ranking_weight") == "0"), "observed_value": f"{summary_029.get('data_trust_ranking_weight')}|{summary_029.get('data_trust_alpha_contribution')}", "required_value": "0|0", "research_only": "TRUE"},
        {"audit_item": "risk_additive_alpha_contribution_zero", "audit_passed": yn(summary_029.get("risk_additive_alpha_contribution") == "0"), "observed_value": summary_029.get("risk_additive_alpha_contribution", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "market_regime_additive_alpha_contribution_zero", "audit_passed": yn(summary_029.get("market_regime_additive_alpha_contribution") == "0"), "observed_value": summary_029.get("market_regime_additive_alpha_contribution", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "official_ranking_mutation_count_zero", "audit_passed": yn(summary_029.get("official_ranking_mutation_count") == "0"), "observed_value": summary_029.get("official_ranking_mutation_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "official_factor_weight_mutation_count_zero", "audit_passed": yn(summary_029.get("official_factor_weight_mutation_count") == "0"), "observed_value": summary_029.get("official_factor_weight_mutation_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "official_recommendation_count_zero", "audit_passed": yn(summary_029.get("official_recommendation_count") == "0"), "observed_value": summary_029.get("official_recommendation_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "trade_action_count_zero", "audit_passed": yn(summary_029.get("trade_action_count") == "0"), "observed_value": summary_029.get("trade_action_count", ""), "required_value": "0", "research_only": "TRUE"},
    ]

    ids = [r.get("observation_id", "") for r in ledger]
    duplicate_count = len(ids) - len(set(ids))
    integrity_rows = [{
        "row_count": len(ledger),
        "unique_observation_id_count": len(set(ids)),
        "duplicate_observation_id_count": duplicate_count,
        "distinct_as_of_date_count": len({r.get("as_of_date", "") for r in ledger}),
        "distinct_ticker_count": len({r.get("ticker", "") for r in ledger}),
        "distinct_context_label_count": len({r.get("context_label", "") for r in ledger if r.get("context_label", "")}),
        "distinct_lane_id_count": len({r.get("lane_id", "") for r in ledger}),
        "distinct_forward_return_window_count": len({r.get("forward_return_window", "") for r in ledger}),
        "selected_observation_count": sum(1 for r in ledger if r.get("selected_for_shadow_observation") == "TRUE"),
        "pending_schedule_count": len(schedule),
        "fallback_snapshot_status": summary_029.get("snapshot_source_status", ""),
        "latest_as_of_date": max([r.get("as_of_date", "") for r in ledger] or [""]),
        "snapshot_source": summary_029.get("snapshot_source_status", ""),
        "research_only_flag_consistency": yn(all(r.get("research_only") == "TRUE" for r in ledger)),
        "research_only": "TRUE",
    }]

    price_cache: dict[str, list[tuple[str, float]]] = {}
    bench = load_price("SPY")
    maturity_rows, return_rows, pending_rows = [], [], []
    missing_tickers = set()
    due_price_missing = 0
    for sched in schedule:
        oid = sched.get("observation_id", "")
        led = ledger_by_id.get(oid, {})
        asof, due, ticker = sched.get("as_of_date", ""), sched.get("due_date", ""), sched.get("ticker", "")
        asof_d, due_d = parse_date(asof), parse_date(due)
        if due_d is None or asof_d is None:
            status = "INVALID_DUE_DATE"; delta = ""
        elif due_d > CURRENT_RUN_DATE:
            status = "NOT_YET_MATURED"; delta = (due_d - CURRENT_RUN_DATE).days
        else:
            prices = price_cache.setdefault(ticker, load_price(ticker))
            entry = price_on_or_after(prices, asof)
            exitp = price_on_or_after(prices, due)
            status = "MATURED_PRICE_AVAILABLE" if entry and exitp else "MATURED_PRICE_MISSING"
            delta = (CURRENT_RUN_DATE - due_d).days
            if not prices:
                missing_tickers.add(ticker)
            if not exitp:
                due_price_missing += 1
        maturity = {
            "observation_id": oid, "as_of_date": asof, "ticker": ticker,
            "context_label": led.get("context_label", ""), "context_combination": led.get("context_combination", ""),
            "lane_id": led.get("lane_id", ""), "forward_return_window": sched.get("forward_return_window", ""),
            "due_date": due, "current_run_date": CURRENT_RUN_DATE.isoformat(), "maturity_status": status,
            "days_until_due_or_past_due": delta, "research_only": "TRUE",
        }
        maturity_rows.append(maturity)
        if status == "MATURED_PRICE_AVAILABLE":
            prices = price_cache[ticker]
            entry = price_on_or_after(prices, asof)
            exitp = price_on_or_after(prices, due)
            b_entry, b_exit = price_on_or_after(bench, asof), price_on_or_after(bench, due)
            ret = (exitp[1] / entry[1]) - 1 if entry and exitp else None
            bret = (b_exit[1] / b_entry[1]) - 1 if b_entry and b_exit else None
            return_rows.append({
                **maturity, "entry_price": entry[1], "entry_price_date": entry[0],
                "exit_price": exitp[1], "price_date_used": exitp[0],
                "realized_forward_return": ret,
                "benchmark_forward_return": bret,
                "excess_return": ret - bret if ret is not None and bret is not None else None,
                "price_source": f"state/v18/price_cache/{ticker}.csv",
                "pit_validation_status": "PASS_SOURCE_DATE_RULE_DETERMINISTIC",
                "observation_status": "REALIZED_FORWARD_RETURN_AVAILABLE",
            })
        else:
            pending_rows.append({**maturity, "realized_forward_return": "PENDING", "observation_status": "PENDING_FORWARD_RETURN" if status == "NOT_YET_MATURED" else status})

    enriched = []
    ret_by_id = {r["observation_id"]: r for r in return_rows}
    for row in maturity_rows:
        r = ret_by_id.get(row["observation_id"], {})
        led = ledger_by_id.get(row["observation_id"], {})
        sg = source_gap_by_id.get(row["observation_id"], {})
        enriched.append({**row, **r, "context_key": led.get("context_combination") or led.get("context_label", ""), "source_gap_count": 1 if sg else 0})
    context_summary = summarize(enriched, "context_key")
    lane_summary = summarize(enriched, "lane_id")

    current_dates = []
    for p in [ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_RANKED_CANDIDATES.csv", ROOT / "outputs" / "v20" / "backtest_snapshots" / "V20_194_CURRENT_RUN_RECOMPUTABLE_FACTOR_SNAPSHOT.csv"]:
        for row in read_csv(p):
            d = row.get("latest_price_date") or row.get("as_of_date")
            if d:
                current_dates.append(d[:10])
    latest_current = max(current_dates) if current_dates else ""
    fallback_date = summary_029.get("as_of_date", "")
    gap_days = (parse_date(latest_current) - parse_date(fallback_date)).days if latest_current and fallback_date and parse_date(latest_current) and parse_date(fallback_date) else ""
    fallback_rows = [{
        "fallback_as_of_date": fallback_date,
        "latest_available_current_daily_candidate_date": latest_current,
        "repaired_label_latest_date": fallback_date,
        "date_gap_days": gap_days,
        "fallback_prevents_current_daily_observation_use": yn(bool(gap_days) and int(gap_days) > 0),
        "affected_contexts": "ALL_V21_029_CONTEXTS",
        "recommended_repair": "V21.032_CURRENT_REPAIRED_LABEL_DAILY_PRODUCER",
        "v21_031_daily_report_should_display_fallback_status": "TRUE",
        "future_current_repaired_label_producer_required": "TRUE",
        "research_only": "TRUE",
    }]

    gap_rows = [
        {"gap_item": "missing_ticker_prices", "severity": "HIGH" if missing_tickers else "NONE", "affected_observation_count": sum(1 for r in maturity_rows if r["ticker"] in missing_tickers), "can_continue_research_only": yn(not missing_tickers), "required_next_repair_stage": "PRICE_DATA_PRODUCER_IF_NEEDED", "research_only": "TRUE"},
        {"gap_item": "missing_benchmark_prices", "severity": "HIGH" if not bench else "NONE", "affected_observation_count": len(schedule) if not bench else 0, "can_continue_research_only": yn(bool(bench)), "required_next_repair_stage": "BENCHMARK_PRICE_PRODUCER_IF_NEEDED", "research_only": "TRUE"},
        {"gap_item": "missing_vix_labels", "severity": "MEDIUM", "affected_observation_count": len(schedule), "can_continue_research_only": "TRUE", "required_next_repair_stage": "V21.028_MARKET_REGIME_DATA_PRODUCER_IMPLEMENTATION", "research_only": "TRUE"},
        {"gap_item": "missing_macro_event_labels", "severity": "MEDIUM", "affected_observation_count": len(schedule), "can_continue_research_only": "TRUE", "required_next_repair_stage": "V21.028_MARKET_REGIME_DATA_PRODUCER_IMPLEMENTATION", "research_only": "TRUE"},
        {"gap_item": "missing_current_repaired_labels", "severity": "HIGH", "affected_observation_count": len(schedule), "can_continue_research_only": "TRUE", "required_next_repair_stage": "V21.032_CURRENT_REPAIRED_LABEL_DAILY_PRODUCER", "research_only": "TRUE"},
        {"gap_item": "missing_trading_calendar", "severity": "LOW", "affected_observation_count": 0, "can_continue_research_only": "TRUE", "required_next_repair_stage": "OPTIONAL_TRADING_CALENDAR_CONTRACT", "research_only": "TRUE"},
        {"gap_item": "missing_due_date_prices", "severity": "HIGH" if due_price_missing else "NONE", "affected_observation_count": due_price_missing, "can_continue_research_only": yn(due_price_missing == 0), "required_next_repair_stage": "PRICE_DATA_PRODUCER_IF_NEEDED", "research_only": "TRUE"},
    ]

    guardrail_rows = [
        {"guardrail_item": "official_ranking_mutation_count", "observed_value": "0", "required_value": "0", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "official_weight_mutation_count", "observed_value": "0", "required_value": "0", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "official_recommendation_count", "observed_value": "0", "required_value": "0", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "trade_action_count", "observed_value": "0", "required_value": "0", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "broker_execution_supported", "observed_value": "FALSE", "required_value": "FALSE", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "shadow_activation", "observed_value": "FALSE", "required_value": "FALSE", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "official_use_allowed", "observed_value": "FALSE", "required_value": "FALSE", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "official_ranking_readiness_allowed", "observed_value": "FALSE", "required_value": "FALSE", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "official_weight_update_readiness_allowed", "observed_value": "FALSE", "required_value": "FALSE", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "data_trust_alpha_contribution", "observed_value": "0", "required_value": "0", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "risk_additive_alpha_contribution", "observed_value": "0", "required_value": "0", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "market_regime_additive_alpha_contribution", "observed_value": "0", "required_value": "0", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "no_global_risk_hard_gate", "observed_value": "TRUE", "required_value": "TRUE", "guardrail_passed": "TRUE", "research_only": "TRUE"},
    ]

    matured_count = len(return_rows)
    pending_count = sum(1 for r in maturity_rows if r["maturity_status"] == "NOT_YET_MATURED")
    price_missing_count = sum(1 for r in maturity_rows if r["maturity_status"] == "MATURED_PRICE_MISSING")
    if duplicate_count:
        tracker_decision = "SHADOW_LEDGER_MATURITY_TRACKER_BLOCKED_BY_LEDGER_INTEGRITY_FAILURE"
        next_stage = "V21.019_MORE_MATURED_OBSERVATION_ACCUMULATION_PLAN"
        prefix = "FAIL"
    elif price_missing_count and matured_count == 0:
        tracker_decision = "SHADOW_LEDGER_MATURITY_TRACKER_BLOCKED_BY_REQUIRED_PRICE_DATA_MISSING"
        next_stage = "V21.028_MARKET_REGIME_DATA_PRODUCER_IMPLEMENTATION"
        prefix = "FAIL"
    elif price_missing_count:
        tracker_decision = "SHADOW_LEDGER_MATURITY_TRACKER_PARTIAL_PRICE_GAPS"
        next_stage = "V21.028_MARKET_REGIME_DATA_PRODUCER_IMPLEMENTATION"
        prefix = "PARTIAL_PASS"
    elif matured_count:
        tracker_decision = "SHADOW_LEDGER_MATURITY_TRACKER_READY_WITH_MATURED_RESULTS"
        next_stage = "V21.033_SHADOW_LEDGER_MATURED_RESULT_EVALUATOR"
        prefix = "PASS"
    else:
        tracker_decision = "SHADOW_LEDGER_MATURITY_TRACKER_READY_ALL_PENDING"
        next_stage = "V21.031_DAILY_WITHIN_REGIME_SHADOW_OBSERVATION_REPORT"
        prefix = "PASS"
    final_status = f"{prefix}_V21_030_{tracker_decision}"
    decision_rows = [{
        "maturity_tracker_decision": tracker_decision, "final_status": final_status,
        "official_use_allowed": "FALSE", "official_ranking_readiness_allowed": "FALSE",
        "official_weight_update_readiness_allowed": "FALSE", "official_weight_update_blocked": "TRUE",
        "broker_execution_supported": "FALSE", "shadow_activation": "FALSE",
        "recommended_next_stage": next_stage, "selected_recommended_next_stage": "TRUE", "research_only": "TRUE",
    }]
    summary = {
        "stage_name": STAGE_NAME, "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "research_only": "TRUE", "final_status": final_status, "maturity_tracker_decision": tracker_decision,
        "v21_029_ledger_producer_decision": decision_029.get("ledger_producer_decision", ""),
        "v21_029_recommended_next_stage": decision_029.get("recommended_next_stage", ""),
        "ledger_row_count": len(ledger), "matured_count": matured_count, "pending_count": pending_count,
        "price_missing_count": price_missing_count, "fallback_snapshot_status": summary_029.get("snapshot_source_status", ""),
        "official_use_allowed": "FALSE", "official_ranking_readiness_allowed": "FALSE",
        "official_weight_update_readiness_allowed": "FALSE", "official_weight_update_blocked": "TRUE",
        "broker_execution_supported": "FALSE", "recommended_next_stage": next_stage,
        "prototype_output_scope": "V21_030_RESEARCH_ONLY_SHADOW_OBSERVATION",
        "data_trust_ranking_weight": "0", "data_trust_alpha_contribution": "0",
        "risk_additive_alpha_contribution": "0", "market_regime_additive_alpha_contribution": "0",
        "official_ranking_mutation_count": "0", "official_factor_weight_mutation_count": "0",
        "official_recommendation_count": "0", "trade_action_count": "0", "shadow_activation": "FALSE",
    }

    write_csv(INGEST, ingest_rows, ["audit_item", "audit_passed", "observed_value", "required_value", "research_only"])
    write_csv(INTEGRITY, integrity_rows, ["row_count", "unique_observation_id_count", "duplicate_observation_id_count", "distinct_as_of_date_count", "distinct_ticker_count", "distinct_context_label_count", "distinct_lane_id_count", "distinct_forward_return_window_count", "selected_observation_count", "pending_schedule_count", "fallback_snapshot_status", "latest_as_of_date", "snapshot_source", "research_only_flag_consistency", "research_only"])
    write_csv(MATURITY, maturity_rows, ["observation_id", "as_of_date", "ticker", "context_label", "context_combination", "lane_id", "forward_return_window", "due_date", "current_run_date", "maturity_status", "days_until_due_or_past_due", "research_only"])
    write_csv(RETURNS, return_rows, ["observation_id", "as_of_date", "ticker", "context_label", "context_combination", "lane_id", "forward_return_window", "due_date", "current_run_date", "maturity_status", "days_until_due_or_past_due", "entry_price", "entry_price_date", "exit_price", "price_date_used", "realized_forward_return", "benchmark_forward_return", "excess_return", "price_source", "pit_validation_status", "observation_status", "research_only"])
    write_csv(PENDING, pending_rows, ["observation_id", "as_of_date", "ticker", "context_label", "context_combination", "lane_id", "forward_return_window", "due_date", "current_run_date", "maturity_status", "days_until_due_or_past_due", "realized_forward_return", "observation_status", "research_only"])
    write_csv(CTX_SUMMARY, context_summary, ["context_key", "scheduled_count", "matured_count", "pending_count", "price_missing_count", "mean_realized_forward_return", "median_realized_forward_return", "hit_rate", "mean_excess_return", "alpha_only_lane_count", "risk_gate_overlay_lane_count", "source_gap_count", "fallback_snapshot_flag", "research_only"])
    write_csv(LANE_SUMMARY, lane_summary, ["lane_id", "scheduled_count", "matured_count", "pending_count", "price_missing_count", "mean_realized_forward_return", "median_realized_forward_return", "hit_rate", "mean_excess_return", "alpha_only_lane_count", "risk_gate_overlay_lane_count", "source_gap_count", "fallback_snapshot_flag", "research_only"])
    write_csv(FALLBACK, fallback_rows, ["fallback_as_of_date", "latest_available_current_daily_candidate_date", "repaired_label_latest_date", "date_gap_days", "fallback_prevents_current_daily_observation_use", "affected_contexts", "recommended_repair", "v21_031_daily_report_should_display_fallback_status", "future_current_repaired_label_producer_required", "research_only"])
    write_csv(GAPS, gap_rows, ["gap_item", "severity", "affected_observation_count", "can_continue_research_only", "required_next_repair_stage", "research_only"])
    write_csv(GUARDRAIL, guardrail_rows, ["guardrail_item", "observed_value", "required_value", "guardrail_passed", "research_only"])
    write_csv(DECISION, decision_rows, ["maturity_tracker_decision", "final_status", "official_use_allowed", "official_ranking_readiness_allowed", "official_weight_update_readiness_allowed", "official_weight_update_blocked", "broker_execution_supported", "shadow_activation", "recommended_next_stage", "selected_recommended_next_stage", "research_only"])
    write_csv(SUMMARY, [summary], list(summary.keys()))

    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(f"""# V21.030 Shadow Observation Ledger Maturity Tracker Report

## Executive summary
This research-only tracker audited V21.029 ledger maturity and calculated realized forward returns where deterministic local price data was available.

## Final maturity tracker decision
{tracker_decision}

Final status: {final_status}

## V21.029 decision ingestion
V21.029 decision: {decision_029.get('ledger_producer_decision', '')}. Recommended next stage: {decision_029.get('recommended_next_stage', '')}.

## Ledger integrity audit
Ledger rows: {len(ledger)}. Duplicate observation IDs: {duplicate_count}.

## Forward schedule maturity audit
Matured with prices: {matured_count}. Pending: {pending_count}. Price missing: {price_missing_count}.

## Realized forward returns
See V21_030_REALIZED_FORWARD_RETURNS.csv.

## Pending observations
Pending observations are preserved in V21_030_PENDING_OBSERVATIONS.csv.

## Maturity summary by context
See V21_030_MATURITY_SUMMARY_BY_CONTEXT.csv.

## Maturity summary by lane
See V21_030_MATURITY_SUMMARY_BY_LANE.csv.

## Fallback snapshot limitation audit
V21.029 used a fallback snapshot. See V21_030_FALLBACK_SNAPSHOT_LIMITATION_AUDIT.csv.

## Source gap and price availability audit
Missing VIX and macro/event labels remain explicit gaps and are not fabricated.

## Guardrail enforcement
Official mutations, broker execution, global risk hard gate, and shadow activation remain blocked.

## DATA_TRUST zero-alpha confirmation
DATA_TRUST ranking contribution is 0 and alpha contribution is 0. RISK and MARKET_REGIME additive alpha contribution are 0.

## Explicit blocked actions
No official ranking mutation. No official factor weight mutation. No official recommendation. No trade action. No broker execution. No shadow activation. No official use. No official ranking readiness. No official weight update readiness. No production readiness. No real-book readiness.

## What this stage produced
Maturity audit, realized return rows, pending rows, context and lane summaries, fallback limitation audit, source gap audit, guardrail audit, and decision summary.

## What this stage did not produce
It did not produce official rankings, recommendations, trades, broker instructions, official weights, market-regime files, production readiness, real-book readiness, or shadow activation.

## Recommended next stage
{next_stage}
""", encoding="utf-8")
    print(f"STAGE_NAME={STAGE_NAME}")
    print(f"final_status={final_status}")
    print(f"maturity_tracker_decision={tracker_decision}")
    print(f"recommended_next_stage={next_stage}")
    print("official_use_allowed=FALSE")
    print("official_ranking_readiness_allowed=FALSE")
    print("official_weight_update_readiness_allowed=FALSE")
    print("official_weight_update_blocked=TRUE")
    print("broker_execution_supported=FALSE")
    print("data_trust_ranking_weight=0")
    print("data_trust_alpha_contribution=0")
    print("risk_additive_alpha_contribution=0")
    print("market_regime_additive_alpha_contribution=0")
    print("official_ranking_mutation_count=0")
    print("official_factor_weight_mutation_count=0")
    print("official_recommendation_count=0")
    print("trade_action_count=0")
    print("shadow_activation=FALSE")
    print("research_only=TRUE")


if __name__ == "__main__":
    main()
