#!/usr/bin/env python
"""Append the current Technical-only Top20/Top50 observation set to a ledger.

This stage is local-artifact-only and research/observation-only. It does not
create or interpret a full-weight result.
"""

from __future__ import annotations

import csv
import hashlib
import math
from datetime import date, datetime, timedelta
from pathlib import Path


STAGE = "V21.044-R7_TECHNICAL_ONLY_CURRENT_DAILY_OBSERVATION_LEDGER_APPEND"
PASS_STATUS = "PASS_V21_044_R7_TECHNICAL_ONLY_OBSERVATION_LEDGER_APPENDED"
PRICE_WARNING_STATUS = "PARTIAL_PASS_V21_044_R7_TECHNICAL_ONLY_OBSERVATION_LEDGER_APPENDED_WITH_PRICE_WARNINGS"
DUPLICATE_STATUS = "PARTIAL_PASS_V21_044_R7_NO_NEW_ROWS_DUPLICATE_OBSERVATION_DATE"
GATE_BLOCKED = "BLOCKED_V21_044_R7_R6_CONTINUITY_GATE_NOT_READY"
SOURCE_BLOCKED = "BLOCKED_V21_044_R7_CURRENT_TECHNICAL_SOURCE_NOT_FOUND"
BOUNDARY_BLOCKED = "BLOCKED_V21_044_R7_OBSERVATION_SCOPE_BOUNDARY_FAILED"

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "outputs" / "v21" / "review"
FACTORS = ROOT / "outputs" / "v21" / "factors"
LEDGER_DIR = ROOT / "outputs" / "v21" / "ledger"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"
PRICE_DIR = ROOT / "outputs" / "v20" / "price_history"

R6_DECISION = REVIEW / "V21_044_R6_CONTINUITY_GATE_DECISION_SUMMARY.csv"
R6_CONTRACT = REVIEW / "V21_044_R6_NEXT_OBSERVATION_CONTRACT.csv"
R4_PANEL = REVIEW / "V21_044_R4_TECHNICAL_ONLY_HISTORICAL_SCORE_PANEL.csv"
RAW_TECHNICAL = FACTORS / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv"
QQQ_PRICES = PRICE_DIR / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"
TICKER_PRICES = PRICE_DIR / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"

LEDGER = LEDGER_DIR / "V21_044_R7_TECHNICAL_ONLY_OBSERVATION_LEDGER.csv"
APPEND = LEDGER_DIR / "V21_044_R7_CURRENT_TECHNICAL_ONLY_OBSERVATION_APPEND.csv"
INTEGRITY = LEDGER_DIR / "V21_044_R7_TECHNICAL_ONLY_LEDGER_INTEGRITY_AUDIT.csv"
MATURITY = LEDGER_DIR / "V21_044_R7_TECHNICAL_ONLY_MATURITY_SCHEDULE.csv"
SOURCE_AUDIT = REVIEW / "V21_044_R7_CURRENT_TECHNICAL_SOURCE_AUDIT.csv"
BOUNDARY_AUDIT = REVIEW / "V21_044_R7_OBSERVATION_SCOPE_BOUNDARY_AUDIT.csv"
DECISION = REVIEW / "V21_044_R7_OBSERVATION_DECISION_SUMMARY.csv"
REPORT = READ_CENTER / "V21_044_R7_TECHNICAL_ONLY_CURRENT_DAILY_OBSERVATION_LEDGER_APPEND_REPORT.md"
CURRENT_REPORT = READ_CENTER / "CURRENT_V21_044_R7_TECHNICAL_ONLY_CURRENT_DAILY_OBSERVATION_LEDGER_APPEND_REPORT.md"

WINDOWS = (("5D", 5), ("10D", 10), ("20D", 20), ("60D", 60))
BUCKETS = (("Top20", 20), ("Top50", 50))
CANONICAL_SOURCE = "V21.044-R5_R5A_R6"
STREAM = "TECHNICAL_ONLY_CANONICAL_CONSERVATIVE"

GUARDRAILS = {
    "research_only": "TRUE",
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

LEDGER_FIELDS = [
    "observation_id", "observation_as_of_date", "ticker", "bucket", "bucket_rank",
    "technical_only_score", "technical_only_rank", "family", "research_stream",
    "canonical_source", "source_file", "entry_price", "entry_price_date",
    "entry_price_source", "benchmark_symbol", "benchmark_entry_price",
    "benchmark_entry_date", "benchmark_price_source", "forward_window",
    "scheduled_maturity_date", "maturity_schedule_method", "maturity_status",
    "realized_forward_return", "benchmark_forward_return", "excess_vs_QQQ",
    "weak_hit_rate_warning", *GUARDRAILS.keys(),
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


def parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def parse_number(value: str) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def number_text(value: float | None) -> str:
    return "" if value is None else f"{value:.10f}"


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    current = date(year, month, 1)
    current += timedelta(days=(weekday - current.weekday()) % 7)
    return current + timedelta(days=7 * (n - 1))


def last_weekday(year: int, month: int, weekday: int) -> date:
    current = date(year + (month == 12), 1 if month == 12 else month + 1, 1) - timedelta(days=1)
    return current - timedelta(days=(current.weekday() - weekday) % 7)


def easter_sunday(year: int) -> date:
    # Anonymous Gregorian algorithm.
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def observed_fixed_holiday(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def market_holidays(year: int) -> set[date]:
    return {
        observed_fixed_holiday(date(year, 1, 1)),
        nth_weekday(year, 1, 0, 3),       # Martin Luther King Jr. Day
        nth_weekday(year, 2, 0, 3),       # Washington's Birthday
        easter_sunday(year) - timedelta(days=2),
        last_weekday(year, 5, 0),         # Memorial Day
        observed_fixed_holiday(date(year, 6, 19)),
        observed_fixed_holiday(date(year, 7, 4)),
        nth_weekday(year, 9, 0, 1),       # Labor Day
        nth_weekday(year, 11, 3, 4),      # Thanksgiving
        observed_fixed_holiday(date(year, 12, 25)),
    }


def projected_sessions(after: date, count: int) -> list[date]:
    sessions: list[date] = []
    current = after
    while len(sessions) < count:
        current += timedelta(days=1)
        if current.weekday() < 5 and current not in market_holidays(current.year):
            sessions.append(current)
    return sessions


def load_qqq_calendar_and_price() -> tuple[list[date], dict[str, tuple[str, str]]]:
    dates: set[date] = set()
    price: dict[str, tuple[str, str]] = {}
    for row in read_rows(QQQ_PRICES):
        if row.get("symbol", "").upper() != "QQQ":
            continue
        parsed = parse_date(row.get("date", ""))
        if parsed:
            dates.add(parsed)
        close = row.get("adjusted_close") or row.get("close", "")
        if parsed and parse_number(close) is not None:
            price[parsed.isoformat()] = (close, relative(QQQ_PRICES))
    return sorted(dates), price


def maturity_date(as_of: date, sessions: list[date], window: int) -> tuple[str, str]:
    future = [day for day in sessions if day > as_of]
    if len(future) >= window:
        return future[window - 1].isoformat(), "LOCAL_QQQ_OBSERVED_TRADING_DATES"
    anchor = future[-1] if future else as_of
    extension = projected_sessions(anchor, window - len(future))
    combined = future + extension
    return combined[window - 1].isoformat(), "LOCAL_QQQ_TRADING_CALENDAR_WITH_MARKET_HOLIDAY_PROJECTION"


def latest_valid_technical_rows() -> tuple[list[dict[str, str]], list[dict[str, object]], str]:
    audit: list[dict[str, object]] = []
    if not R4_PANEL.exists():
        audit.append({
            "candidate_file": relative(R4_PANEL), "candidate_status": "REJECTED_NOT_FOUND",
            "embedded_latest_date": "", "latest_valid_row_count": 0,
            "has_ticker": "FALSE", "has_explicit_date": "FALSE", "has_technical_score": "FALSE",
            "has_technical_rank": "FALSE", "forbidden_score_field_used": "FALSE",
            "selected": "FALSE", "notes": "Required R4 panel is absent.",
        })
        return [], audit, ""

    latest = ""
    latest_rows: list[dict[str, str]] = []
    with R4_PANEL.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        required = {"as_of_date", "ticker", "technical_only_score", "technical_only_rank"}
        schema_ok = required.issubset(fields)
        for row in reader:
            if not schema_ok:
                break
            day = row.get("as_of_date", "")
            score = parse_number(row.get("technical_only_score", ""))
            rank = parse_number(row.get("technical_only_rank", ""))
            valid = (
                parse_date(day) is not None
                and bool(row.get("ticker", "").strip())
                and score is not None and rank is not None
                and row.get("family", "").upper() == "TECHNICAL"
                and row.get("point_in_time_safe", "").upper() == "TRUE"
                and not row.get("leakage_violation_reason", "").strip()
                and row.get("full_weight_score_allowed", "").upper() != "TRUE"
            )
            if not valid:
                continue
            if day > latest:
                latest = day
                latest_rows = [row]
            elif day == latest:
                latest_rows.append(row)
    unique_tickers = len({row.get("ticker", "").upper() for row in latest_rows})
    selected = bool(latest and unique_tickers >= 50)
    audit.append({
        "candidate_file": relative(R4_PANEL),
        "candidate_status": "SELECTED_EXPLICIT_TECHNICAL_ONLY_SCORE_AND_RANK" if selected else "REJECTED_NO_VALID_CURRENT_TOP50",
        "embedded_latest_date": latest, "latest_valid_row_count": len(latest_rows),
        "has_ticker": yn("ticker" in fields), "has_explicit_date": yn("as_of_date" in fields),
        "has_technical_score": yn("technical_only_score" in fields),
        "has_technical_rank": yn("technical_only_rank" in fields),
        "forbidden_score_field_used": "FALSE", "selected": yn(selected),
        "notes": "Rank is explicit in R4 and lineage points to V21_038_R1; full-weight guardrail metadata is not used as a score.",
    })

    raw_fields: set[str] = set()
    raw_latest = ""
    if RAW_TECHNICAL.exists():
        with RAW_TECHNICAL.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            raw_fields = set(reader.fieldnames or [])
            for row in reader:
                raw_latest = max(raw_latest, row.get("as_of_date", ""))
    audit.append({
        "candidate_file": relative(RAW_TECHNICAL),
        "candidate_status": "NOT_SELECTED_RANK_NOT_EXPLICIT" if RAW_TECHNICAL.exists() else "REJECTED_NOT_FOUND",
        "embedded_latest_date": raw_latest, "latest_valid_row_count": "",
        "has_ticker": yn("ticker" in raw_fields), "has_explicit_date": yn("as_of_date" in raw_fields),
        "has_technical_score": yn("technical_score_normalized" in raw_fields),
        "has_technical_rank": "FALSE", "forbidden_score_field_used": "FALSE",
        "selected": "FALSE", "notes": "Valid score lineage candidate, but direct selection requires an explicit rank.",
    })
    return (latest_rows if selected else []), audit, latest


def r6_gate_ready() -> tuple[bool, dict[str, str], list[dict[str, str]]]:
    decision = first_row(R6_DECISION)
    contract = read_rows(R6_CONTRACT)
    required_contract = {
        "score_scope": "CURRENT_DAILY_TECHNICAL_ONLY_SCORE_AND_RANK",
        "observation_sets": "TOP20|TOP50",
        "forward_windows": "5D|10D|20D|60D",
        "benchmark": "QQQ_LOCAL_CACHED_PRICES",
    }
    contract_map = {row.get("contract_item", ""): row.get("contract_value", "") for row in contract}
    ready = (
        decision.get("final_status") == "PARTIAL_PASS_V21_044_R6_TECHNICAL_ONLY_CONTINUITY_WITH_WARNINGS"
        and decision.get("decision") == "ALLOW_TECHNICAL_ONLY_OBSERVATION_WITH_WEAK_HIT_RATE_WARNING"
        and decision.get("technical_only_shadow_observation_continuity_allowed") == "TRUE"
        and decision.get("full_weight_rebacktest_allowed_now") == "FALSE"
        and decision.get("full_weight_result_available") == "FALSE"
        and all(contract_map.get(key) == value for key, value in required_contract.items())
    )
    return ready, decision, contract


def ticker_entry_prices(as_of: str, tickers: set[str]) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    if not TICKER_PRICES.exists():
        return result
    with TICKER_PRICES.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            ticker = row.get("symbol", "").upper()
            if ticker in tickers and row.get("date") == as_of:
                close = row.get("adjusted_close") or row.get("close", "")
                if parse_number(close) is not None:
                    result[ticker] = (close, relative(TICKER_PRICES))
    return result


def observation_id(as_of: str, ticker: str, bucket: str, window: str) -> str:
    key = f"{as_of}|{ticker}|{bucket}|{window}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"V21_044_R7::{as_of}::{ticker}::{bucket}::{window}::{digest}"


def scope_boundary_rows(gate_ready: bool, source_ready: bool, rows: list[dict[str, str]]) -> tuple[list[dict[str, object]], bool]:
    checks = [
        ("r6_continuity_gate_ready", gate_ready, "R6 permits Technical-only observation continuity."),
        ("current_source_ready", source_ready, "Current source has explicit date, ticker, Technical-only score, and rank."),
        ("family_is_technical", bool(rows) and all(row.get("family", "").upper() == "TECHNICAL" for row in rows), "Only Technical family rows are eligible."),
        ("point_in_time_safe", bool(rows) and all(row.get("point_in_time_safe", "").upper() == "TRUE" for row in rows), "Selected rows must be point-in-time safe."),
        ("no_leakage_reason", bool(rows) and all(not row.get("leakage_violation_reason", "").strip() for row in rows), "Forward-return or leakage rows are excluded."),
        ("full_weight_score_not_allowed", bool(rows) and all(row.get("full_weight_score_allowed", "").upper() != "TRUE" for row in rows), "Full-weight score remains unavailable."),
        ("top50_coverage", len({row.get("ticker", "").upper() for row in rows}) >= 50, "At least 50 unique current tickers are required."),
    ]
    output = [{
        "boundary_check": name, "required_value": "TRUE", "observed_value": yn(passed),
        "check_passed": yn(passed), "blocking": "TRUE", "notes": notes, **GUARDRAILS,
    } for name, passed, notes in checks]
    return output, all(passed for _, passed, _ in checks)


def main() -> int:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW.mkdir(parents=True, exist_ok=True)
    READ_CENTER.mkdir(parents=True, exist_ok=True)

    gate_ready, r6, _ = r6_gate_ready()
    current_rows, source_audit, as_of = latest_valid_technical_rows()
    source_ready = bool(current_rows and as_of)
    boundary_rows, boundary_ok = scope_boundary_rows(gate_ready, source_ready, current_rows)

    source_fields = [
        "candidate_file", "candidate_status", "embedded_latest_date", "latest_valid_row_count",
        "has_ticker", "has_explicit_date", "has_technical_score", "has_technical_rank",
        "forbidden_score_field_used", "selected", "notes",
    ]
    write_rows(SOURCE_AUDIT, source_audit, source_fields)
    write_rows(BOUNDARY_AUDIT, boundary_rows, list(boundary_rows[0].keys()))

    prior = read_rows(LEDGER)
    prior_count = len(prior)
    append_rows: list[dict[str, str]] = []
    duplicate_skipped = 0
    price_warning_count = 0
    top20_count = 0
    top50_count = 0
    selected_source = relative(R4_PANEL) if source_ready else ""

    if not gate_ready:
        final_status = GATE_BLOCKED
        decision = "R6_CONTINUITY_GATE_REPAIR_REQUIRED"
        recommended_next_stage = "V21.044-R6_TECHNICAL_ONLY_SHADOW_OBSERVATION_CONTINUITY_GATE"
    elif not source_ready:
        final_status = SOURCE_BLOCKED
        decision = "CURRENT_TECHNICAL_SOURCE_REPAIR_REQUIRED"
        recommended_next_stage = "V21.044-R7_CURRENT_TECHNICAL_SOURCE_REPAIR"
    elif not boundary_ok:
        final_status = BOUNDARY_BLOCKED
        decision = "TECHNICAL_ONLY_OBSERVATION_SCOPE_REPAIR_REQUIRED"
        recommended_next_stage = "V21.044-R7_OBSERVATION_SCOPE_BOUNDARY_REPAIR"
    else:
        ranked = sorted(
            current_rows,
            key=lambda row: (parse_number(row.get("technical_only_rank", "")) or float("inf"), row.get("ticker", "")),
        )
        unique: list[dict[str, str]] = []
        seen_tickers: set[str] = set()
        for row in ranked:
            ticker = row.get("ticker", "").upper().strip()
            if ticker and ticker not in seen_tickers:
                unique.append(row)
                seen_tickers.add(ticker)
        top20_count = len(unique[:20])
        top50_count = len(unique[:50])

        qqq_sessions, qqq_price_map = load_qqq_calendar_and_price()
        ticker_prices = ticker_entry_prices(as_of, {row.get("ticker", "").upper() for row in unique[:50]})
        as_of_date = parse_date(as_of)
        existing_keys = {
            (row.get("observation_as_of_date", ""), row.get("ticker", ""), row.get("bucket", ""), row.get("forward_window", ""))
            for row in prior
        }
        for bucket, size in BUCKETS:
            for bucket_rank, row in enumerate(unique[:size], start=1):
                ticker = row.get("ticker", "").upper()
                entry = ticker_prices.get(ticker)
                benchmark = qqq_price_map.get(as_of)
                for window, days in WINDOWS:
                    key = (as_of, ticker, bucket, window)
                    if key in existing_keys:
                        duplicate_skipped += 1
                        continue
                    due, method = maturity_date(as_of_date, qqq_sessions, days)  # type: ignore[arg-type]
                    if entry is None:
                        price_warning_count += 1
                    if benchmark is None:
                        price_warning_count += 1
                    append_rows.append({
                        "observation_id": observation_id(as_of, ticker, bucket, window),
                        "observation_as_of_date": as_of,
                        "ticker": ticker,
                        "bucket": bucket,
                        "bucket_rank": str(bucket_rank),
                        "technical_only_score": number_text(parse_number(row.get("technical_only_score", ""))),
                        "technical_only_rank": number_text(parse_number(row.get("technical_only_rank", ""))),
                        "family": "Technical",
                        "research_stream": STREAM,
                        "canonical_source": CANONICAL_SOURCE,
                        "source_file": selected_source,
                        "entry_price": entry[0] if entry else "",
                        "entry_price_date": as_of if entry else "",
                        "entry_price_source": entry[1] if entry else "",
                        "benchmark_symbol": "QQQ",
                        "benchmark_entry_price": benchmark[0] if benchmark else "",
                        "benchmark_entry_date": as_of if benchmark else "",
                        "benchmark_price_source": benchmark[1] if benchmark else "",
                        "forward_window": window,
                        "scheduled_maturity_date": due,
                        "maturity_schedule_method": method,
                        "maturity_status": "PENDING",
                        "realized_forward_return": "",
                        "benchmark_forward_return": "",
                        "excess_vs_QQQ": "",
                        "weak_hit_rate_warning": "TRUE",
                        **GUARDRAILS,
                    })
                    existing_keys.add(key)

        if not append_rows:
            final_status = DUPLICATE_STATUS
            decision = "NO_NEW_ROWS_CURRENT_OBSERVATION_ALREADY_PRESENT"
            recommended_next_stage = "V21.044-R8_TECHNICAL_ONLY_LEDGER_MATURITY_REFRESH"
        elif price_warning_count:
            final_status = PRICE_WARNING_STATUS
            decision = "TECHNICAL_ONLY_OBSERVATIONS_APPENDED_PENDING_LOCAL_PRICE_BACKFILL"
            recommended_next_stage = "V21.044-R8_TECHNICAL_ONLY_LEDGER_MATURITY_REFRESH"
        else:
            final_status = PASS_STATUS
            decision = "TECHNICAL_ONLY_OBSERVATIONS_APPENDED_FOR_MATURITY_TRACKING"
            recommended_next_stage = "V21.044-R8_TECHNICAL_ONLY_LEDGER_MATURITY_REFRESH"

    combined = prior + append_rows
    price_warning_count = sum(
        (1 if not row.get("entry_price", "") else 0)
        + (1 if not row.get("benchmark_entry_price", "") else 0)
        for row in combined
        if row.get("observation_as_of_date", "") == as_of
    )
    write_rows(LEDGER, combined, LEDGER_FIELDS)
    write_rows(APPEND, append_rows, LEDGER_FIELDS)

    ids = [row.get("observation_id", "") for row in combined]
    keys = [
        (row.get("observation_as_of_date", ""), row.get("ticker", ""), row.get("bucket", ""), row.get("forward_window", ""))
        for row in combined
    ]
    integrity_rows = [
        {
            "audit_check": "prior_ledger_rows_preserved", "expected_value": str(prior_count),
            "observed_value": str(sum(1 for row in combined if row.get("observation_id") in {p.get("observation_id") for p in prior})),
            "check_passed": yn(all(row in combined for row in prior)), "notes": "Existing rows are retained unchanged.",
        },
        {
            "audit_check": "observation_id_unique", "expected_value": "0_DUPLICATES",
            "observed_value": str(len(ids) - len(set(ids))),
            "check_passed": yn(len(ids) == len(set(ids))), "notes": "",
        },
        {
            "audit_check": "natural_key_unique", "expected_value": "0_DUPLICATES",
            "observed_value": str(len(keys) - len(set(keys))),
            "check_passed": yn(len(keys) == len(set(keys))), "notes": "Date+ticker+bucket+window.",
        },
        {
            "audit_check": "pending_returns_blank", "expected_value": "TRUE",
            "observed_value": yn(all(
                row.get("realized_forward_return", "") == ""
                and row.get("benchmark_forward_return", "") == ""
                and row.get("excess_vs_QQQ", "") == ""
                for row in combined if row.get("maturity_status") == "PENDING"
            )),
            "check_passed": yn(all(
                row.get("realized_forward_return", "") == ""
                and row.get("benchmark_forward_return", "") == ""
                and row.get("excess_vs_QQQ", "") == ""
                for row in combined if row.get("maturity_status") == "PENDING"
            )), "notes": "",
        },
        {
            "audit_check": "guardrails_enforced", "expected_value": "TRUE",
            "observed_value": yn(all(all(row.get(key, "") == value for key, value in GUARDRAILS.items()) for row in combined)),
            "check_passed": yn(all(all(row.get(key, "") == value for key, value in GUARDRAILS.items()) for row in combined)),
            "notes": "All ledger rows remain research-only and observation-only.",
        },
    ]
    write_rows(INTEGRITY, integrity_rows, list(integrity_rows[0].keys()))

    maturity_rows = [{
        "observation_id": row.get("observation_id", ""),
        "observation_as_of_date": row.get("observation_as_of_date", ""),
        "ticker": row.get("ticker", ""),
        "bucket": row.get("bucket", ""),
        "forward_window": row.get("forward_window", ""),
        "scheduled_maturity_date": row.get("scheduled_maturity_date", ""),
        "maturity_status": row.get("maturity_status", ""),
        "weak_hit_rate_warning": row.get("weak_hit_rate_warning", ""),
        **GUARDRAILS,
    } for row in combined]
    maturity_fields = [
        "observation_id", "observation_as_of_date", "ticker", "bucket", "forward_window",
        "scheduled_maturity_date", "maturity_status", "weak_hit_rate_warning", *GUARDRAILS.keys(),
    ]
    write_rows(MATURITY, maturity_rows, maturity_fields)

    pending_count = sum(1 for row in combined if row.get("maturity_status") == "PENDING")
    summary = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "selected_technical_source": selected_source,
        "observation_as_of_date": as_of,
        "top20_ticker_count": top20_count,
        "top50_ticker_count": top50_count,
        "append_row_count": len(append_rows),
        "duplicate_skipped_count": duplicate_skipped,
        "prior_ledger_row_count": prior_count,
        "total_ledger_row_count": len(combined),
        "pending_maturity_count": pending_count,
        "price_warning_count": price_warning_count,
        "weak_hit_rate_warning": "TRUE",
        "r6_final_status": r6.get("final_status", ""),
        "r6_decision": r6.get("decision", ""),
        "canonical_excess_vs_QQQ_5D": r6.get("canonical_excess_vs_QQQ_5D", ""),
        "canonical_excess_vs_QQQ_10D": r6.get("canonical_excess_vs_QQQ_10D", ""),
        "canonical_excess_vs_QQQ_20D": r6.get("canonical_excess_vs_QQQ_20D", ""),
        "canonical_excess_vs_QQQ_60D": r6.get("canonical_excess_vs_QQQ_60D", ""),
        "full_weight_blocked": "TRUE",
        "recommended_next_stage": recommended_next_stage,
        **GUARDRAILS,
    }
    write_rows(DECISION, [summary], list(summary.keys()))

    report = f"""# V21.044-R7 Technical-only Current Daily Observation Ledger Append

## Outcome

- Final status: {final_status}
- Decision: {decision}
- Selected Technical-only source: {selected_source or "NONE"}
- Observation as-of date: {as_of or "NONE"}
- Top20 ticker count: {top20_count}
- Top50 ticker count: {top50_count}
- Appended rows: {len(append_rows)}
- Duplicate rows skipped: {duplicate_skipped}
- Total ledger rows: {len(combined)}
- Pending maturities: {pending_count}
- Price warnings: {price_warning_count}

## Canonical Technical-only Context

The canonical QQQ excess values carried from V21.044-R6 are 5D {r6.get("canonical_excess_vs_QQQ_5D", "")}, 10D {r6.get("canonical_excess_vs_QQQ_10D", "")}, 20D {r6.get("canonical_excess_vs_QQQ_20D", "")}, and 60D {r6.get("canonical_excess_vs_QQQ_60D", "")}. The weak-hit-rate warning remains TRUE.

Technical-only observation is not full-weight evidence. Full-weight results and full-weight rebacktesting remain blocked.

## Price And Maturity Handling

Prices are read only from the local V20 canonical price artifacts. Missing same-date prices remain blank and are counted as warnings. Maturity dates follow observed local QQQ trading dates when available and use the same market-session calendar with U.S. market-holiday projection after the local cache endpoint.

## Guardrails

Research-only, observation-only, and Technical-only observation flags are TRUE. Official adoption, weight mutation, ranking mutation, official recommendation, real-book action, broker execution, trade action, shadow gate, and shadow adoption flags are FALSE.

## Recommended Next Stage

{recommended_next_stage}
"""
    REPORT.write_text(report, encoding="utf-8")
    CURRENT_REPORT.write_text(report, encoding="utf-8")

    print(f"final_status={final_status}")
    print(f"decision={decision}")
    print(f"selected_technical_source={selected_source}")
    print(f"observation_as_of_date={as_of}")
    print(f"top20_ticker_count={top20_count}")
    print(f"top50_ticker_count={top50_count}")
    print(f"append_row_count={len(append_rows)}")
    print(f"duplicate_skipped_count={duplicate_skipped}")
    print(f"total_ledger_row_count={len(combined)}")
    print(f"pending_maturity_count={pending_count}")
    print(f"price_warning_count={price_warning_count}")
    print("full_weight_blocked=TRUE")
    print(f"recommended_next_stage={recommended_next_stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
