#!/usr/bin/env python
"""Refresh maturity and local price bindings for the V21.044-R7 ledger."""

from __future__ import annotations

import csv
import math
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path


STAGE = "V21.044-R8_TECHNICAL_ONLY_LEDGER_MATURITY_REFRESH"
PASS_STATUS = "PASS_V21_044_R8_TECHNICAL_ONLY_MATURITY_REFRESH_READY"
PENDING_STATUS = "PARTIAL_PASS_V21_044_R8_NO_MATURED_ROWS_YET"
PRICE_WARNING_STATUS = "PARTIAL_PASS_V21_044_R8_MATURITY_REFRESH_WITH_PRICE_MISSING"
LEDGER_BLOCKED = "BLOCKED_V21_044_R8_R7_LEDGER_NOT_FOUND"
PRICE_BLOCKED = "BLOCKED_V21_044_R8_PRICE_SOURCES_NOT_FOUND"
BOUNDARY_BLOCKED = "BLOCKED_V21_044_R8_SCOPE_BOUNDARY_FAILED"

ROOT = Path(__file__).resolve().parents[2]
LEDGER_DIR = ROOT / "outputs" / "v21" / "ledger"
REVIEW = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"
PRICE_DIR = ROOT / "outputs" / "v20" / "price_history"

R7_LEDGER = LEDGER_DIR / "V21_044_R7_TECHNICAL_ONLY_OBSERVATION_LEDGER.csv"
R7_SCHEDULE = LEDGER_DIR / "V21_044_R7_TECHNICAL_ONLY_MATURITY_SCHEDULE.csv"
R7_INTEGRITY = LEDGER_DIR / "V21_044_R7_TECHNICAL_ONLY_LEDGER_INTEGRITY_AUDIT.csv"
R7_DECISION = REVIEW / "V21_044_R7_OBSERVATION_DECISION_SUMMARY.csv"
R7_BOUNDARY = REVIEW / "V21_044_R7_OBSERVATION_SCOPE_BOUNDARY_AUDIT.csv"
TICKER_PRICES = PRICE_DIR / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
BENCHMARK_PRICES = PRICE_DIR / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"

REFRESHED = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_OBSERVATION_LEDGER_REFRESHED.csv"
MATURED = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_MATURED_RESULTS.csv"
PENDING = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_PENDING_ROWS.csv"
PRICE_AUDIT = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_PRICE_BINDING_AUDIT.csv"
MATURITY_AUDIT = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_MATURITY_REFRESH_AUDIT.csv"
BUCKET_SUMMARY = REVIEW / "V21_044_R8_TECHNICAL_ONLY_MATURITY_SUMMARY_BY_BUCKET_WINDOW.csv"
REPAIR_SUMMARY = REVIEW / "V21_044_R8_TECHNICAL_ONLY_PRICE_WARNING_REPAIR_SUMMARY.csv"
SCOPE_AUDIT = REVIEW / "V21_044_R8_TECHNICAL_ONLY_SCOPE_BOUNDARY_AUDIT.csv"
DECISION = REVIEW / "V21_044_R8_TECHNICAL_ONLY_DECISION_SUMMARY.csv"
REPORT = READ_CENTER / "V21_044_R8_TECHNICAL_ONLY_LEDGER_MATURITY_REFRESH_REPORT.md"
CURRENT_REPORT = READ_CENTER / "CURRENT_V21_044_R8_TECHNICAL_ONLY_LEDGER_MATURITY_REFRESH_REPORT.md"

GUARDRAILS = {
    "research_only": "TRUE",
    "maturity_refresh_only": "TRUE",
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

REFRESH_FIELDS = [
    "observation_id", "observation_as_of_date", "ticker", "bucket", "bucket_rank",
    "technical_only_score", "technical_only_rank", "family", "research_stream",
    "canonical_source", "source_file", "entry_price", "entry_price_date",
    "entry_price_source", "entry_price_binding_status", "benchmark_symbol",
    "benchmark_entry_price", "benchmark_entry_date", "benchmark_price_source",
    "benchmark_entry_binding_status", "forward_window", "scheduled_maturity_date",
    "maturity_schedule_method", "ticker_forward_price", "ticker_forward_price_date",
    "ticker_forward_price_source", "benchmark_forward_price",
    "benchmark_forward_price_date", "benchmark_forward_price_source",
    "maturity_status", "realized_forward_return", "benchmark_forward_return",
    "excess_vs_QQQ", "weak_hit_rate_warning", *GUARDRAILS.keys(),
]

PRICE_AUDIT_FIELDS = [
    "observation_id", "observation_as_of_date", "ticker", "bucket", "forward_window",
    "scheduled_maturity_date", "ticker_entry_binding_status", "ticker_entry_price_date",
    "ticker_entry_price", "benchmark_entry_binding_status", "benchmark_entry_price_date",
    "benchmark_entry_price", "ticker_forward_binding_status", "ticker_forward_price_date",
    "ticker_forward_price", "benchmark_forward_binding_status",
    "benchmark_forward_price_date", "benchmark_forward_price",
    "price_warning_count_before", "price_warning_count_after", "price_warning_repaired_count",
    "maturity_status", *GUARDRAILS.keys(),
]


def yn(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def first_row(path: Path) -> dict[str, str]:
    rows = read_rows(path)
    return rows[0] if rows else {}


def write_rows(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: "" if row.get(field) is None else row.get(field, "") for field in fields})


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def valid_number(value: str) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) and result > 0 else None
    except (TypeError, ValueError):
        return None


def fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.10f}"


def valid_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except (TypeError, ValueError):
        return False


def price_value(row: dict[str, str]) -> float | None:
    return valid_number(row.get("adjusted_close", "")) or valid_number(row.get("close", ""))


def load_prices(path: Path, symbol_filter: str | None = None) -> tuple[dict[str, dict[str, tuple[float, str]]], str]:
    prices: dict[str, dict[str, tuple[float, str]]] = defaultdict(dict)
    max_date = ""
    if not path.exists():
        return prices, max_date
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            symbol = row.get("symbol", "").upper().strip()
            day = row.get("date", "")
            value = price_value(row)
            if symbol_filter and symbol != symbol_filter:
                continue
            if symbol and valid_date(day) and value is not None:
                prices[symbol][day] = (value, relative(path))
                max_date = max(max_date, day)
    return prices, max_date


def bind_exact(prices: dict[str, tuple[float, str]], day: str) -> tuple[float | None, str, str, str]:
    bound = prices.get(day)
    if bound:
        return bound[0], day, bound[1], "EXACT_DATE_LOCAL_PRICE"
    return None, "", "", "LOCAL_PRICE_NOT_AVAILABLE"


def bind_ticker_entry(prices: dict[str, tuple[float, str]], day: str) -> tuple[float | None, str, str, str]:
    exact = prices.get(day)
    if exact:
        return exact[0], day, exact[1], "EXACT_DATE_LOCAL_PRICE"
    next_dates = sorted(candidate for candidate in prices if candidate > day)
    if next_dates:
        aligned = next_dates[0]
        value, source = prices[aligned]
        return value, aligned, source, "ENTRY_DATE_ALIGNED_TO_NEXT_TRADING_DAY"
    return None, "", "", "LOCAL_PRICE_NOT_AVAILABLE"


def inherited_or_bound(
    row: dict[str, str],
    price_field: str,
    date_field: str,
    source_field: str,
    binding: tuple[float | None, str, str, str],
) -> tuple[float | None, str, str, str]:
    inherited = valid_number(row.get(price_field, ""))
    inherited_date = row.get(date_field, "")
    if inherited is not None and valid_date(inherited_date):
        return inherited, inherited_date, row.get(source_field, ""), "PRESERVED_VALID_R7_BINDING"
    return binding


def mean(values: list[float]) -> str:
    return fmt(statistics.fmean(values)) if values else ""


def median(values: list[float]) -> str:
    return fmt(statistics.median(values)) if values else ""


def scope_checks(
    ledger: list[dict[str, str]],
    schedule: list[dict[str, str]],
    integrity: list[dict[str, str]],
    r7_decision: dict[str, str],
    r7_boundary: list[dict[str, str]],
) -> tuple[list[dict[str, object]], bool]:
    ids = [row.get("observation_id", "") for row in ledger]
    natural_keys = [
        (row.get("observation_as_of_date", ""), row.get("ticker", ""), row.get("bucket", ""), row.get("forward_window", ""))
        for row in ledger
    ]
    schedule_ids = {row.get("observation_id", "") for row in schedule}
    r7_false = [
        "full_weight_result_available", "full_weight_rebacktest_allowed_now",
        "official_adoption_allowed", "official_weight_mutation", "official_ranking_mutation",
        "official_recommendation_allowed", "real_book_action_allowed", "broker_execution_allowed",
        "trade_action_allowed", "shadow_gate_allowed", "shadow_adoption_allowed",
    ]
    checks = [
        ("r7_ledger_nonempty", bool(ledger), str(len(ledger)), "R7 ledger must contain observations."),
        ("r7_schedule_covers_ledger", bool(ledger) and set(ids) == schedule_ids, f"{len(schedule_ids)}/{len(ids)}", "Schedule IDs must exactly match ledger IDs."),
        ("r7_integrity_passed", bool(integrity) and all(row.get("check_passed") == "TRUE" for row in integrity), "", "Every R7 integrity check must pass."),
        ("r7_boundary_passed", bool(r7_boundary) and all(row.get("check_passed") == "TRUE" for row in r7_boundary), "", "Every R7 scope boundary check must pass."),
        ("r7_next_stage_is_r8", r7_decision.get("recommended_next_stage") == STAGE, r7_decision.get("recommended_next_stage", ""), "R7 must route to R8."),
        ("observation_ids_unique", len(ids) == len(set(ids)) and all(ids), str(len(ids) - len(set(ids))), "No duplicate observation IDs."),
        ("natural_keys_unique", len(natural_keys) == len(set(natural_keys)), str(len(natural_keys) - len(set(natural_keys))), "No appended or duplicate observations."),
        ("technical_family_only", bool(ledger) and all(row.get("family", "").upper() == "TECHNICAL" for row in ledger), "", "Only Technical observations are in scope."),
        ("r7_positive_guardrails", bool(ledger) and all(row.get("research_only") == "TRUE" and row.get("observation_only") == "TRUE" and row.get("technical_only_observation") == "TRUE" for row in ledger), "", "Research and observation guardrails must be present."),
        ("r7_restricted_guardrails", bool(ledger) and all(all(row.get(field) == "FALSE" for field in r7_false) for row in ledger), "", "All official, full-weight, shadow, and execution permissions remain disabled."),
    ]
    rows = [{
        "boundary_check": name, "required_value": "TRUE", "observed_value": observed or yn(passed),
        "check_passed": yn(passed), "blocking": "TRUE", "notes": notes, **GUARDRAILS,
    } for name, passed, observed, notes in checks]
    return rows, all(passed for _, passed, _, _ in checks)


def main() -> int:
    for directory in (LEDGER_DIR, REVIEW, READ_CENTER):
        directory.mkdir(parents=True, exist_ok=True)

    ledger = read_rows(R7_LEDGER)
    schedule = read_rows(R7_SCHEDULE)
    integrity = read_rows(R7_INTEGRITY)
    r7_decision = first_row(R7_DECISION)
    r7_boundary = read_rows(R7_BOUNDARY)
    input_count = len(ledger)

    ledger_found = R7_LEDGER.exists() and bool(ledger)
    price_sources_found = (
        TICKER_PRICES.exists() and TICKER_PRICES.stat().st_size > 0
        and BENCHMARK_PRICES.exists() and BENCHMARK_PRICES.stat().st_size > 0
    )
    scope_rows, scope_ok = scope_checks(ledger, schedule, integrity, r7_decision, r7_boundary)
    write_rows(SCOPE_AUDIT, scope_rows, list(scope_rows[0].keys()))

    ticker_prices, max_ticker_date = load_prices(TICKER_PRICES) if price_sources_found else ({}, "")
    benchmark_all, max_benchmark_date = load_prices(BENCHMARK_PRICES, "QQQ") if price_sources_found else ({}, "")
    qqq_prices = benchmark_all.get("QQQ", {})

    refreshed: list[dict[str, str]] = []
    binding_audit: list[dict[str, object]] = []
    maturity_audit: list[dict[str, object]] = []

    if ledger_found and price_sources_found and scope_ok:
        for source_row in ledger:
            row = dict(source_row)
            ticker = row.get("ticker", "").upper()
            as_of = row.get("observation_as_of_date", "")
            due = row.get("scheduled_maturity_date", "")
            ticker_map = ticker_prices.get(ticker, {})

            ticker_entry = inherited_or_bound(
                row, "entry_price", "entry_price_date", "entry_price_source",
                bind_ticker_entry(ticker_map, as_of),
            )
            benchmark_entry = inherited_or_bound(
                row, "benchmark_entry_price", "benchmark_entry_date", "benchmark_price_source",
                bind_exact(qqq_prices, as_of),
            )
            ticker_forward = bind_exact(ticker_map, due)
            benchmark_forward = bind_exact(qqq_prices, due)

            matured_by_calendar = bool(max_benchmark_date and due and max_benchmark_date >= due)
            if not matured_by_calendar:
                maturity_status = "PENDING_NOT_MATURED"
                realized = benchmark_return = excess = None
            elif all(binding[0] is not None for binding in (ticker_entry, benchmark_entry, ticker_forward, benchmark_forward)):
                maturity_status = "MATURED"
                realized = ticker_forward[0] / ticker_entry[0] - 1  # type: ignore[operator]
                benchmark_return = benchmark_forward[0] / benchmark_entry[0] - 1  # type: ignore[operator]
                excess = realized - benchmark_return
            else:
                maturity_status = "PRICE_MISSING"
                realized = benchmark_return = excess = None

            warning_before = int(valid_number(source_row.get("entry_price", "")) is None) + int(valid_number(source_row.get("benchmark_entry_price", "")) is None)
            warning_after = int(ticker_entry[0] is None) + int(benchmark_entry[0] is None)
            repaired = max(0, warning_before - warning_after)

            row.update({
                "entry_price": fmt(ticker_entry[0]),
                "entry_price_date": ticker_entry[1],
                "entry_price_source": ticker_entry[2],
                "entry_price_binding_status": ticker_entry[3],
                "benchmark_symbol": "QQQ",
                "benchmark_entry_price": fmt(benchmark_entry[0]),
                "benchmark_entry_date": benchmark_entry[1],
                "benchmark_price_source": benchmark_entry[2],
                "benchmark_entry_binding_status": benchmark_entry[3],
                "ticker_forward_price": fmt(ticker_forward[0]),
                "ticker_forward_price_date": ticker_forward[1],
                "ticker_forward_price_source": ticker_forward[2],
                "benchmark_forward_price": fmt(benchmark_forward[0]),
                "benchmark_forward_price_date": benchmark_forward[1],
                "benchmark_forward_price_source": benchmark_forward[2],
                "maturity_status": maturity_status,
                "realized_forward_return": fmt(realized),
                "benchmark_forward_return": fmt(benchmark_return),
                "excess_vs_QQQ": fmt(excess),
                **GUARDRAILS,
            })
            refreshed.append(row)

            binding_audit.append({
                "observation_id": row["observation_id"], "observation_as_of_date": as_of,
                "ticker": ticker, "bucket": row.get("bucket", ""), "forward_window": row.get("forward_window", ""),
                "scheduled_maturity_date": due,
                "ticker_entry_binding_status": ticker_entry[3], "ticker_entry_price_date": ticker_entry[1],
                "ticker_entry_price": fmt(ticker_entry[0]),
                "benchmark_entry_binding_status": benchmark_entry[3], "benchmark_entry_price_date": benchmark_entry[1],
                "benchmark_entry_price": fmt(benchmark_entry[0]),
                "ticker_forward_binding_status": ticker_forward[3], "ticker_forward_price_date": ticker_forward[1],
                "ticker_forward_price": fmt(ticker_forward[0]),
                "benchmark_forward_binding_status": benchmark_forward[3],
                "benchmark_forward_price_date": benchmark_forward[1],
                "benchmark_forward_price": fmt(benchmark_forward[0]),
                "price_warning_count_before": warning_before, "price_warning_count_after": warning_after,
                "price_warning_repaired_count": repaired, "maturity_status": maturity_status, **GUARDRAILS,
            })
            maturity_audit.append({
                "observation_id": row["observation_id"], "observation_as_of_date": as_of,
                "ticker": ticker, "bucket": row.get("bucket", ""),
                "forward_window": row.get("forward_window", ""), "scheduled_maturity_date": due,
                "max_benchmark_price_date": max_benchmark_date,
                "maturity_date_reached": yn(matured_by_calendar),
                "required_entry_prices_available": yn(ticker_entry[0] is not None and benchmark_entry[0] is not None),
                "required_forward_prices_available": yn(ticker_forward[0] is not None and benchmark_forward[0] is not None),
                "maturity_status": maturity_status,
                "realized_returns_computed": yn(maturity_status == "MATURED"), **GUARDRAILS,
            })

    write_rows(REFRESHED, refreshed, REFRESH_FIELDS)
    matured_rows = [row for row in refreshed if row.get("maturity_status") == "MATURED"]
    pending_rows = [row for row in refreshed if row.get("maturity_status") != "MATURED"]
    write_rows(MATURED, matured_rows, REFRESH_FIELDS)
    write_rows(PENDING, pending_rows, REFRESH_FIELDS)
    write_rows(PRICE_AUDIT, binding_audit, PRICE_AUDIT_FIELDS)
    maturity_fields = [
        "observation_id", "observation_as_of_date", "ticker", "bucket", "forward_window",
        "scheduled_maturity_date", "max_benchmark_price_date", "maturity_date_reached",
        "required_entry_prices_available", "required_forward_prices_available",
        "maturity_status", "realized_returns_computed", *GUARDRAILS.keys(),
    ]
    write_rows(MATURITY_AUDIT, maturity_audit, maturity_fields)

    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in refreshed:
        groups[(row.get("bucket", ""), row.get("forward_window", ""))].append(row)
    summary_rows: list[dict[str, object]] = []
    for (bucket, window), rows in sorted(groups.items(), key=lambda item: (item[0][0], int(item[0][1].rstrip("D") or 0))):
        matured_group = [row for row in rows if row.get("maturity_status") == "MATURED"]
        realized = [float(row["realized_forward_return"]) for row in matured_group]
        benchmarks = [float(row["benchmark_forward_return"]) for row in matured_group]
        excesses = [float(row["excess_vs_QQQ"]) for row in matured_group]
        summary_rows.append({
            "bucket": bucket, "forward_window": window,
            "matured_row_count": len(matured_group),
            "pending_row_count": sum(row.get("maturity_status") == "PENDING_NOT_MATURED" for row in rows),
            "price_missing_count": sum(row.get("maturity_status") == "PRICE_MISSING" for row in rows),
            "mean_realized_forward_return": mean(realized),
            "median_realized_forward_return": median(realized),
            "mean_benchmark_forward_return": mean(benchmarks),
            "median_benchmark_forward_return": median(benchmarks),
            "mean_excess_vs_QQQ": mean(excesses),
            "median_excess_vs_QQQ": median(excesses),
            "hit_rate_vs_QQQ": fmt(sum(value > 0 for value in excesses) / len(excesses)) if excesses else "",
            "positive_realized_return_rate": fmt(sum(value > 0 for value in realized) / len(realized)) if realized else "",
            "weak_hit_rate_warning": "TRUE", **GUARDRAILS,
        })
    summary_fields = [
        "bucket", "forward_window", "matured_row_count", "pending_row_count",
        "price_missing_count", "mean_realized_forward_return", "median_realized_forward_return",
        "mean_benchmark_forward_return", "median_benchmark_forward_return",
        "mean_excess_vs_QQQ", "median_excess_vs_QQQ", "hit_rate_vs_QQQ",
        "positive_realized_return_rate", "weak_hit_rate_warning", *GUARDRAILS.keys(),
    ]
    write_rows(BUCKET_SUMMARY, summary_rows, summary_fields)

    warning_before_total = sum(int(row["price_warning_count_before"]) for row in binding_audit)
    warning_after_total = sum(int(row["price_warning_count_after"]) for row in binding_audit)
    warning_repaired_total = sum(int(row["price_warning_repaired_count"]) for row in binding_audit)
    if warning_before_total == 0:
        repair_result = "NO_ENTRY_PRICE_WARNINGS_PRESENT"
    elif warning_after_total == 0:
        repair_result = "ALL_ENTRY_PRICE_WARNINGS_REPAIRED_FROM_LOCAL_SOURCES"
    elif warning_repaired_total:
        repair_result = "PARTIAL_ENTRY_PRICE_WARNING_REPAIR_FROM_LOCAL_SOURCES"
    else:
        repair_result = "NO_ENTRY_PRICE_WARNINGS_REPAIRED_LOCAL_COVERAGE_NOT_AVAILABLE"
    repair_row = {
        "source_r7_price_warning_count": r7_decision.get("price_warning_count", ""),
        "audited_entry_price_warning_count_before": warning_before_total,
        "entry_price_warning_count_after": warning_after_total,
        "entry_price_warning_repaired_count": warning_repaired_total,
        "price_warning_repair_result": repair_result,
        "max_local_ticker_price_date": max_ticker_date,
        "max_benchmark_price_date": max_benchmark_date,
        "ticker_price_source": relative(TICKER_PRICES) if TICKER_PRICES.exists() else "",
        "benchmark_price_source": relative(BENCHMARK_PRICES) if BENCHMARK_PRICES.exists() else "",
        **GUARDRAILS,
    }
    write_rows(REPAIR_SUMMARY, [repair_row], list(repair_row.keys()))

    matured_count = len(matured_rows)
    pending_count = sum(row.get("maturity_status") == "PENDING_NOT_MATURED" for row in refreshed)
    price_missing_count = sum(row.get("maturity_status") == "PRICE_MISSING" for row in refreshed)
    if not ledger_found:
        final_status = LEDGER_BLOCKED
        decision_value = "BLOCK_TECHNICAL_ONLY_MATURITY_REFRESH"
        next_stage = "V21.044-R7_TECHNICAL_ONLY_CURRENT_DAILY_OBSERVATION_LEDGER_APPEND"
    elif not price_sources_found:
        final_status = PRICE_BLOCKED
        decision_value = "REPAIR_PRICE_SOURCES_BEFORE_MATURITY_REFRESH"
        next_stage = "V21.044-R8B_TECHNICAL_ONLY_PRICE_SOURCE_REPAIR"
    elif not scope_ok:
        final_status = BOUNDARY_BLOCKED
        decision_value = "BLOCK_TECHNICAL_ONLY_MATURITY_REFRESH"
        next_stage = "V21.044-R8_SCOPE_BOUNDARY_REPAIR"
    elif price_missing_count:
        final_status = PRICE_WARNING_STATUS
        decision_value = "TECHNICAL_ONLY_LEDGER_REFRESHED_WITH_PRICE_MISSING_WARNINGS"
        next_stage = "V21.044-R9_TECHNICAL_ONLY_MATURED_RESULT_EVALUATOR" if matured_count else "V21.044-R8B_TECHNICAL_ONLY_PRICE_SOURCE_REPAIR"
    elif matured_count:
        final_status = PASS_STATUS
        decision_value = "TECHNICAL_ONLY_LEDGER_REFRESHED_WITH_MATURED_RESULTS"
        next_stage = "V21.044-R9_TECHNICAL_ONLY_MATURED_RESULT_EVALUATOR"
    else:
        final_status = PENDING_STATUS
        decision_value = "TECHNICAL_ONLY_LEDGER_REFRESHED_PENDING_MATURITY"
        next_stage = "V21.044-R8A_TECHNICAL_ONLY_LEDGER_MATURITY_WAIT_STATUS"

    decision_row = {
        "stage": STAGE, "final_status": final_status, "decision": decision_value,
        "source_r7_ledger_path": relative(R7_LEDGER), "input_ledger_row_count": input_count,
        "refreshed_ledger_row_count": len(refreshed), "matured_row_count": matured_count,
        "pending_row_count": pending_count, "price_missing_row_count": price_missing_count,
        "price_warning_count_before": warning_before_total,
        "price_warning_count_after": warning_after_total,
        "price_warning_repaired_count": warning_repaired_total,
        "price_warning_repair_result": repair_result,
        "max_local_ticker_price_date": max_ticker_date,
        "max_benchmark_price_date": max_benchmark_date,
        "full_weight_blocked": "TRUE", "recommended_next_stage": next_stage, **GUARDRAILS,
    }
    write_rows(DECISION, [decision_row], list(decision_row.keys()))

    matured_table = ""
    if matured_count:
        lines = ["| Bucket | Window | Matured | Mean excess vs QQQ | Hit rate vs QQQ |", "|---|---:|---:|---:|---:|"]
        for row in summary_rows:
            if int(row["matured_row_count"]):
                lines.append(f"| {row['bucket']} | {row['forward_window']} | {row['matured_row_count']} | {row['mean_excess_vs_QQQ']} | {row['hit_rate_vs_QQQ']} |")
        matured_table = "\n".join(lines)
    else:
        matured_table = "No matured rows are available in the current local price cache."

    report = f"""# V21.044-R8 Technical-only Ledger Maturity Refresh

## Outcome

- final_status: {final_status}
- decision: {decision_value}
- source R7 ledger: {relative(R7_LEDGER)}
- input ledger row count: {input_count}
- refreshed ledger row count: {len(refreshed)}
- matured row count: {matured_count}
- pending row count: {pending_count}
- price missing row count: {price_missing_count}
- price warning repair result: {repair_result}
- max local ticker price date: {max_ticker_date or "UNAVAILABLE"}
- max benchmark price date: {max_benchmark_date or "UNAVAILABLE"}

## Maturity Summary

{matured_table}

## Price Binding Convention

Local adjusted close is preferred, with local close as fallback. Ticker entry dates may use the next locally available trading date only under the explicit `ENTRY_DATE_ALIGNED_TO_NEXT_TRADING_DAY` rule. Forward prices require the exact scheduled QQQ maturity date; neighboring dates are not substituted.

## Scope Boundary

No buy/sell/hold recommendation was created. Technical-only observation must not be interpreted as full-weight result. Full-weight results and full-weight rebacktesting remain blocked.

## Guardrails

This output is research-only, maturity-refresh-only, observation-only, and Technical-only. Official adoption, official recommendation, ranking mutation, weight mutation, real-book action, broker execution, trade action, shadow gate, and shadow adoption remain disabled.

## Recommended Next Stage

{next_stage}
"""
    REPORT.write_text(report, encoding="utf-8")
    CURRENT_REPORT.write_text(report, encoding="utf-8")

    print(f"final_status={final_status}")
    print(f"decision={decision_value}")
    print(f"input_ledger_row_count={input_count}")
    print(f"refreshed_ledger_row_count={len(refreshed)}")
    print(f"matured_row_count={matured_count}")
    print(f"pending_row_count={pending_count}")
    print(f"price_missing_row_count={price_missing_count}")
    print(f"price_warning_repair_result={repair_result}")
    print("full_weight_blocked=TRUE")
    print(f"recommended_next_stage={next_stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
