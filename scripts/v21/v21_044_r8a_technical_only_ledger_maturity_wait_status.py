#!/usr/bin/env python
"""Research-only wait-status report for V21.044-R8 Technical-only ledger maturity."""

from __future__ import annotations

import csv
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path


STAGE = "V21.044-R8A_TECHNICAL_ONLY_LEDGER_MATURITY_WAIT_STATUS"
PASS_STATUS = "PASS_V21_044_R8A_WAIT_STATUS_READY"
WAIT_STATUS = "PARTIAL_PASS_V21_044_R8A_WAITING_FOR_PRICE_CACHE_REFRESH"
ENTRY_MISSING_STATUS = "PARTIAL_PASS_V21_044_R8A_ENTRY_DATE_PRICE_NOT_AVAILABLE"
MISSING_STATUS = "BLOCKED_V21_044_R8A_R8_OUTPUTS_NOT_FOUND"
BOUNDARY_STATUS = "BLOCKED_V21_044_R8A_SCOPE_BOUNDARY_FAILED"

ROOT = Path(__file__).resolve().parents[2]
LEDGER_DIR = ROOT / "outputs" / "v21" / "ledger"
REVIEW = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"
PRICE_DIR = ROOT / "outputs" / "v20" / "price_history"

REFRESHED = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_OBSERVATION_LEDGER_REFRESHED.csv"
PENDING = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_PENDING_ROWS.csv"
PRICE_AUDIT = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_PRICE_BINDING_AUDIT.csv"
MATURITY_AUDIT = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_MATURITY_REFRESH_AUDIT.csv"
R8_DECISION = REVIEW / "V21_044_R8_TECHNICAL_ONLY_DECISION_SUMMARY.csv"
REPAIR_SUMMARY = REVIEW / "V21_044_R8_TECHNICAL_ONLY_PRICE_WARNING_REPAIR_SUMMARY.csv"
TICKER_PRICES = PRICE_DIR / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
BENCHMARK_PRICES = PRICE_DIR / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"

WAIT_SUMMARY = REVIEW / "V21_044_R8A_WAIT_STATUS_SUMMARY.csv"
PRICE_REQUIREMENT = REVIEW / "V21_044_R8A_PRICE_COVERAGE_REQUIREMENT.csv"
READINESS = REVIEW / "V21_044_R8A_MATURITY_READINESS_BY_WINDOW.csv"
SCOPE_AUDIT = REVIEW / "V21_044_R8A_SCOPE_BOUNDARY_AUDIT.csv"
DECISION_SUMMARY = REVIEW / "V21_044_R8A_DECISION_SUMMARY.csv"
REPORT = READ_CENTER / "V21_044_R8A_TECHNICAL_ONLY_LEDGER_MATURITY_WAIT_STATUS_REPORT.md"
CURRENT_REPORT = READ_CENTER / "CURRENT_V21_044_R8A_TECHNICAL_ONLY_LEDGER_MATURITY_WAIT_STATUS_REPORT.md"

GUARDRAILS = {
    "research_only": "TRUE",
    "wait_status_only": "TRUE",
    "maturity_refresh_only": "FALSE",
    "observation_only": "TRUE",
    "technical_only_observation": "TRUE",
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
}

FALSE_GUARDRAILS = [
    "full_weight_result_available", "full_weight_rebacktest_allowed_now",
    "official_adoption_allowed", "official_weight_mutation", "official_ranking_mutation",
    "official_recommendation_allowed", "real_book_action_allowed", "broker_execution_allowed",
    "trade_action_allowed", "shadow_gate_allowed", "shadow_adoption_allowed",
]


def yn(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: "" if row.get(field) is None else row.get(field, "") for field in fields})


def valid_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except (TypeError, ValueError):
        return False


def max_price_date(path: Path, symbol_filter: str | None = None) -> tuple[str, set[str]]:
    max_day = ""
    dates: set[str] = set()
    if not path.exists():
        return max_day, dates
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            symbol = row.get("symbol", "").upper().strip()
            day = row.get("date", "")
            if symbol_filter and symbol != symbol_filter.upper():
                continue
            if valid_date(day):
                dates.add(day)
                max_day = max(max_day, day)
    return max_day, dates


def int_value(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def first_row(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def scope_rows(
    refreshed: list[dict[str, str]],
    pending: list[dict[str, str]],
    price_audit: list[dict[str, str]],
    maturity_audit: list[dict[str, str]],
    r8_decision: dict[str, str],
    repair_summary: list[dict[str, str]],
) -> tuple[list[dict[str, object]], bool]:
    r8_inputs_found = all(path.exists() and path.stat().st_size > 0 for path in [
        REFRESHED, PENDING, PRICE_AUDIT, MATURITY_AUDIT, R8_DECISION, REPAIR_SUMMARY, TICKER_PRICES, BENCHMARK_PRICES,
    ])
    refreshed_ids = [row.get("observation_id", "") for row in refreshed]
    pending_ids = [row.get("observation_id", "") for row in pending]
    checks = [
        ("r8_outputs_found", r8_inputs_found, "Required R8 and local price-cache artifacts must exist."),
        ("r8_completed_no_matured_rows", r8_decision.get("final_status") == "PARTIAL_PASS_V21_044_R8_NO_MATURED_ROWS_YET" and int_value(r8_decision.get("matured_row_count", "")) == 0, "R8 must have completed with zero matured rows."),
        ("r8_recommended_r8a", r8_decision.get("recommended_next_stage") == STAGE, "R8 must route to this R8A wait-status stage."),
        ("pending_rows_match_refreshed", bool(refreshed) and len(refreshed) == len(pending) and set(refreshed_ids) == set(pending_ids), "All refreshed rows must remain pending."),
        ("maturity_audit_covers_refreshed", bool(refreshed) and len(maturity_audit) == len(refreshed), "R8 maturity audit must cover all refreshed rows."),
        ("price_audit_covers_refreshed", bool(refreshed) and len(price_audit) == len(refreshed), "R8 price audit must cover all refreshed rows."),
        ("no_realized_returns_fabricated", all(not row.get("realized_forward_return") and not row.get("benchmark_forward_return") and not row.get("excess_vs_QQQ") for row in refreshed), "Pending rows must not contain realized returns."),
        ("positive_wait_guardrails", True, "R8A writes research-only wait-status guardrails."),
        ("restricted_scope_guardrails", all(value == "FALSE" for value in (GUARDRAILS[field] for field in FALSE_GUARDRAILS)), "Official, execution, full-weight, and shadow permissions remain disabled."),
    ]
    rows = [
        {
            "boundary_check": name,
            "required_value": "TRUE",
            "observed_value": yn(passed),
            "check_passed": yn(passed),
            "blocking": "TRUE",
            "notes": notes,
            **GUARDRAILS,
            "r9_result_evaluator_allowed_now": "FALSE",
        }
        for name, passed, notes in checks
    ]
    return rows, all(passed for _, passed, _ in checks)


def unique_dates(rows: list[dict[str, str]], field: str) -> list[str]:
    return sorted({row.get(field, "") for row in rows if valid_date(row.get(field, ""))})


def main() -> int:
    REVIEW.mkdir(parents=True, exist_ok=True)
    READ_CENTER.mkdir(parents=True, exist_ok=True)

    refreshed = read_rows(REFRESHED)
    pending = read_rows(PENDING)
    price_audit = read_rows(PRICE_AUDIT)
    maturity_audit = read_rows(MATURITY_AUDIT)
    r8_decision_rows = read_rows(R8_DECISION)
    repair_summary = read_rows(REPAIR_SUMMARY)
    r8_decision = first_row(r8_decision_rows)
    ticker_max, ticker_dates = max_price_date(TICKER_PRICES)
    benchmark_max, benchmark_dates = max_price_date(BENCHMARK_PRICES, "QQQ")

    missing_inputs = not all(path.exists() and path.stat().st_size > 0 for path in [
        REFRESHED, PENDING, PRICE_AUDIT, MATURITY_AUDIT, R8_DECISION, REPAIR_SUMMARY, TICKER_PRICES, BENCHMARK_PRICES,
    ])
    audit_rows, scope_ok = scope_rows(refreshed, pending, price_audit, maturity_audit, r8_decision, repair_summary)
    write_rows(SCOPE_AUDIT, audit_rows)

    observation_dates = unique_dates(refreshed, "observation_as_of_date")
    observation_as_of_date = observation_dates[-1] if observation_dates else ""
    entry_date_required = observation_as_of_date
    entry_price_bindable_now = bool(entry_date_required and ticker_max >= entry_date_required)
    benchmark_entry_bindable_now = bool(entry_date_required and benchmark_max >= entry_date_required and entry_date_required in benchmark_dates)

    by_window: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in pending:
        by_window[row.get("forward_window", "")].append(row)
    required_by_window: dict[str, str] = {}
    for window in ["5D", "10D", "20D", "60D"]:
        dates = unique_dates(by_window.get(window, []), "scheduled_maturity_date")
        required_by_window[window] = dates[0] if dates else ""

    earliest_maturity = min((date for date in required_by_window.values() if date), default="")
    rows_maturable_now = sum(
        1
        for row in pending
        if entry_price_bindable_now
        and benchmark_entry_bindable_now
        and valid_date(row.get("scheduled_maturity_date", ""))
        and ticker_max >= row["scheduled_maturity_date"]
        and benchmark_max >= row["scheduled_maturity_date"]
    )
    rows_waiting = len(pending) - rows_maturable_now
    price_cache_refresh_required = not (entry_price_bindable_now and benchmark_entry_bindable_now) or rows_waiting > 0
    maturity_windows_pending = "|".join(window for window in ["5D", "10D", "20D", "60D"] if by_window.get(window))

    if missing_inputs:
        final_status = MISSING_STATUS
        decision = "REPAIR_PRICE_CACHE_BEFORE_NEXT_MATURITY_REFRESH"
        recommended_next_stage = "V21.044-R8_TECHNICAL_ONLY_LEDGER_MATURITY_REFRESH"
        maturity_wait_status = "R8_OUTPUTS_NOT_FOUND"
    elif not scope_ok:
        final_status = BOUNDARY_STATUS
        decision = "REPAIR_PRICE_CACHE_BEFORE_NEXT_MATURITY_REFRESH"
        recommended_next_stage = "V21.044-R8A_TECHNICAL_ONLY_LEDGER_MATURITY_WAIT_STATUS"
        maturity_wait_status = "SCOPE_BOUNDARY_FAILED"
    elif rows_maturable_now > 0:
        final_status = PASS_STATUS
        decision = "R8_RERUN_CAN_NOW_MATURE_ROWS"
        recommended_next_stage = "rerun V21.044-R8_TECHNICAL_ONLY_LEDGER_MATURITY_REFRESH"
        maturity_wait_status = "LOCAL_PRICE_COVERAGE_CAN_MATURE_ROWS"
    elif not entry_price_bindable_now or not benchmark_entry_bindable_now:
        final_status = ENTRY_MISSING_STATUS
        decision = "WAIT_FOR_PRICE_CACHE_REFRESH_BEFORE_R8_RERUN"
        recommended_next_stage = "V21.044-R8B_TECHNICAL_ONLY_PRICE_CACHE_REFRESH_OR_SOURCE_REPAIR"
        maturity_wait_status = "WAIT_FOR_PRICE_CACHE_REFRESH_OR_FUTURE_TRADING_DATES"
    elif earliest_maturity and (ticker_max < earliest_maturity or benchmark_max < earliest_maturity):
        final_status = WAIT_STATUS
        decision = "WAIT_FOR_MATURITY_DATE_BEFORE_R8_RERUN"
        recommended_next_stage = "V21.044-R8A_WAIT_UNTIL_FIRST_MATURITY_DATE"
        maturity_wait_status = "WAIT_FOR_PRICE_CACHE_REFRESH_OR_FUTURE_TRADING_DATES"
    else:
        final_status = WAIT_STATUS
        decision = "R9_NOT_ALLOWED_NO_MATURED_ROWS"
        recommended_next_stage = "V21.044-R8A_TECHNICAL_ONLY_LEDGER_MATURITY_WAIT_STATUS"
        maturity_wait_status = "WAIT_FOR_PRICE_CACHE_REFRESH_OR_FUTURE_TRADING_DATES"

    matured_rows = int_value(r8_decision.get("matured_row_count", ""))
    r9_allowed = matured_rows > 0
    common_metrics = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "input_ledger_rows": len(refreshed) or int_value(r8_decision.get("input_ledger_row_count", "")),
        "pending_rows": len(pending),
        "matured_rows": matured_rows,
        "price_missing_rows": int_value(r8_decision.get("price_missing_row_count", "")),
        "observation_as_of_date": observation_as_of_date,
        "max_ticker_price_date": ticker_max,
        "max_benchmark_price_date": benchmark_max,
        "entry_price_bindable_now": yn(entry_price_bindable_now),
        "benchmark_entry_price_bindable_now": yn(benchmark_entry_bindable_now),
        "earliest_scheduled_maturity_date": earliest_maturity,
        "maturity_windows_pending": maturity_windows_pending,
        "required_price_date_for_5D": required_by_window["5D"],
        "required_price_date_for_10D": required_by_window["10D"],
        "required_price_date_for_20D": required_by_window["20D"],
        "required_price_date_for_60D": required_by_window["60D"],
        "rows_maturable_now": rows_maturable_now,
        "rows_waiting_for_future_price_coverage": rows_waiting,
        "price_cache_refresh_required": yn(price_cache_refresh_required),
        "maturity_wait_status": maturity_wait_status,
        "r8_should_be_rerun_now": yn(rows_maturable_now > 0),
        "r9_result_evaluator_allowed_now": yn(r9_allowed),
        "full_weight_blocked": "TRUE",
        "recommended_next_stage": recommended_next_stage,
        **GUARDRAILS,
    }
    write_rows(WAIT_SUMMARY, [common_metrics])

    requirement_rows = [
        {
            "coverage_requirement": "entry_price_binding",
            "required_price_date": entry_date_required,
            "ticker_cache_covers_required_date": yn(bool(entry_date_required and ticker_max >= entry_date_required)),
            "benchmark_cache_covers_required_date": yn(bool(entry_date_required and benchmark_max >= entry_date_required)),
            "rows_dependent": len(refreshed),
            "notes": "Observation entry date must be available locally before entry prices can be bound.",
            **GUARDRAILS,
            "r9_result_evaluator_allowed_now": yn(r9_allowed),
        }
    ]
    for window in ["5D", "10D", "20D", "60D"]:
        req = required_by_window[window]
        requirement_rows.append({
            "coverage_requirement": f"{window}_maturity",
            "required_price_date": req,
            "ticker_cache_covers_required_date": yn(bool(req and ticker_max >= req)),
            "benchmark_cache_covers_required_date": yn(bool(req and benchmark_max >= req)),
            "rows_dependent": len(by_window.get(window, [])),
            "notes": "Forward maturity requires local ticker and QQQ prices through the scheduled QQQ-calendar maturity date.",
            **GUARDRAILS,
            "r9_result_evaluator_allowed_now": yn(r9_allowed),
        })
    write_rows(PRICE_REQUIREMENT, requirement_rows)

    readiness_rows = []
    for window in ["5D", "10D", "20D", "60D"]:
        req = required_by_window[window]
        window_rows = by_window.get(window, [])
        window_maturable = sum(
            1 for row in window_rows
            if entry_price_bindable_now and benchmark_entry_bindable_now and req and ticker_max >= req and benchmark_max >= req
        )
        readiness_rows.append({
            "forward_window": window,
            "pending_rows": len(window_rows),
            "required_price_date": req,
            "ticker_cache_ready": yn(bool(req and ticker_max >= req)),
            "benchmark_cache_ready": yn(bool(req and benchmark_max >= req)),
            "entry_price_bindable_now": yn(entry_price_bindable_now),
            "benchmark_entry_price_bindable_now": yn(benchmark_entry_bindable_now),
            "rows_maturable_now": window_maturable,
            "readiness_status": "READY_FOR_R8_RERUN" if window_maturable else "WAITING_FOR_PRICE_CACHE_REFRESH_OR_FUTURE_TRADING_DATES",
            **GUARDRAILS,
            "r9_result_evaluator_allowed_now": yn(r9_allowed),
        })
    write_rows(READINESS, readiness_rows)
    write_rows(DECISION_SUMMARY, [common_metrics])

    report = f"""# {STAGE}

- final_status: {final_status}
- decision: {decision}
- observation_as_of_date: {observation_as_of_date}
- max local ticker price date: {ticker_max}
- max benchmark price date: {benchmark_max}
- entry price can be bound now: {yn(entry_price_bindable_now)}
- benchmark entry price can be bound now: {yn(benchmark_entry_bindable_now)}
- rows maturable now: {rows_maturable_now}
- R8 should be rerun now: {yn(rows_maturable_now > 0)}
- R9 is allowed now: {yn(r9_allowed)}
- recommended next stage: {recommended_next_stage}

## Why R8 had no matured rows

R8 completed with {matured_rows} matured rows and {len(pending)} pending rows. The local ticker and QQQ benchmark price caches currently end at {ticker_max} and {benchmark_max}, while the observation entry date is {observation_as_of_date}. Because local price coverage does not cover the observation entry date, entry prices cannot be bound from local artifacts yet. No future-window maturity evaluation can be completed until entry coverage and the scheduled maturity-date coverage are both available.

## Required price coverage dates by window

- entry price binding: {entry_date_required}
- 5D maturity: {required_by_window['5D']}
- 10D maturity: {required_by_window['10D']}
- 20D maturity: {required_by_window['20D']}
- 60D maturity: {required_by_window['60D']}

## Scope and guardrails

This is a research-only wait-status report. It did not append new observation rows, did not backfill missing prices, did not compute fabricated realized returns, and did not run a full-weight backtest. Full-weight remains blocked: TRUE.

No buy/sell/hold recommendation was created. Technical-only observation must not be interpreted as full-weight result.

Official adoption, official recommendation creation, official ranking mutation, official weight mutation, real-book action, broker execution, trade action, shadow gate, and shadow adoption remain disabled.
"""
    REPORT.write_text(report, encoding="utf-8")
    shutil.copyfile(REPORT, CURRENT_REPORT)

    print(f"final_status={final_status}")
    print(f"decision={decision}")
    print(f"observation_as_of_date={observation_as_of_date}")
    print(f"max_ticker_price_date={ticker_max}")
    print(f"max_benchmark_price_date={benchmark_max}")
    print(f"rows_maturable_now={rows_maturable_now}")
    print(f"recommended_next_stage={recommended_next_stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
