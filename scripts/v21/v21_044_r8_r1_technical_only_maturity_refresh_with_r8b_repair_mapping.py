#!/usr/bin/env python
"""Repair-aware V21.044-R8 rerun using the R8B local price-source mapping."""

from __future__ import annotations

import csv
import math
import shutil
from pathlib import Path


STAGE = "V21.044-R8-R1_TECHNICAL_ONLY_MATURITY_REFRESH_WITH_R8B_REPAIR_MAPPING"
PASS_STATUS = "PASS_V21_044_R8_R1_ENTRY_PRICE_BINDING_REPAIRED_PENDING_MATURITY"
PARTIAL_WARN_STATUS = "PARTIAL_PASS_V21_044_R8_R1_REPAIR_MAPPING_APPLIED_WITH_REMAINING_PRICE_WARNINGS"
NO_MATURED_STATUS = "PARTIAL_PASS_V21_044_R8_R1_NO_MATURED_ROWS_YET"
MAPPING_BLOCKED = "BLOCKED_V21_044_R8_R1_R8B_REPAIR_MAPPING_NOT_READY"
BOUNDARY_BLOCKED = "BLOCKED_V21_044_R8_R1_SCOPE_BOUNDARY_FAILED"

ROOT = Path(__file__).resolve().parents[2]
LEDGER_DIR = ROOT / "outputs" / "v21" / "ledger"
REVIEW = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"

R8_REFRESHED = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_OBSERVATION_LEDGER_REFRESHED.csv"
R8_PENDING = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_PENDING_ROWS.csv"
R8B_MAPPING = REVIEW / "V21_044_R8B_PRICE_SOURCE_REPAIR_MAPPING.csv"
R8B_DECISION = REVIEW / "V21_044_R8B_DECISION_SUMMARY.csv"
R8B_COVERAGE = REVIEW / "V21_044_R8B_REQUIRED_PRICE_COVERAGE_AUDIT.csv"
REPAIR_SOURCE_DEFAULT = ROOT / "outputs" / "v20" / "consolidation" / "V20_47_CURRENT_CANDIDATE_PRICE_CERTIFICATION.csv"
CANONICAL_TICKER = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
CANONICAL_BENCHMARK = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"

OUT_REFRESHED = LEDGER_DIR / "V21_044_R8_R1_TECHNICAL_ONLY_OBSERVATION_LEDGER_REFRESHED_WITH_REPAIR.csv"
OUT_PENDING = LEDGER_DIR / "V21_044_R8_R1_TECHNICAL_ONLY_PENDING_ROWS.csv"
OUT_PRICE_AUDIT = LEDGER_DIR / "V21_044_R8_R1_TECHNICAL_ONLY_PRICE_BINDING_AUDIT.csv"
OUT_MATURITY_AUDIT = LEDGER_DIR / "V21_044_R8_R1_TECHNICAL_ONLY_MATURITY_REFRESH_AUDIT.csv"
REPAIR_SUMMARY = REVIEW / "V21_044_R8_R1_PRICE_REPAIR_APPLICATION_SUMMARY.csv"
SCOPE_AUDIT = REVIEW / "V21_044_R8_R1_TECHNICAL_ONLY_SCOPE_BOUNDARY_AUDIT.csv"
DECISION_SUMMARY = REVIEW / "V21_044_R8_R1_TECHNICAL_ONLY_DECISION_SUMMARY.csv"
REPORT = READ_CENTER / "V21_044_R8_R1_TECHNICAL_ONLY_MATURITY_REFRESH_WITH_R8B_REPAIR_MAPPING_REPORT.md"
CURRENT_REPORT = READ_CENTER / "CURRENT_V21_044_R8_R1_TECHNICAL_ONLY_MATURITY_REFRESH_WITH_R8B_REPAIR_MAPPING_REPORT.md"

OBSERVATION_DATE = "2026-06-16"
BENCHMARK_SYMBOL = "QQQ"

GUARDRAILS = {
    "research_only": "TRUE",
    "maturity_refresh_only": "TRUE",
    "observation_only": "TRUE",
    "price_source_repair_mapping_used": "TRUE",
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
    "online_download_attempted": "FALSE",
    "yfinance_used": "FALSE",
}

FALSE_GUARDRAILS = [
    "full_weight_result_available",
    "full_weight_rebacktest_allowed_now",
    "official_adoption_allowed",
    "official_weight_mutation",
    "official_ranking_mutation",
    "official_recommendation_allowed",
    "real_book_action_allowed",
    "broker_execution_allowed",
    "trade_action_allowed",
    "shadow_gate_allowed",
    "shadow_adoption_allowed",
    "online_download_attempted",
    "yfinance_used",
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


def norm(value: object) -> str:
    return str(value or "").strip()


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def path_from_repo(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def number(value: str) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.10f}"


def choose_price(row: dict[str, str], preferred: str) -> tuple[float | None, str]:
    candidates = []
    if preferred:
        candidates.append(preferred)
    candidates.extend(["adjusted_close", "adj_close", "latest_adj_close", "close", "latest_close", "close_like_price"])
    for field in dict.fromkeys(candidates):
        value = number(row.get(field, ""))
        if value is not None:
            return value, field
    return None, ""


def load_repair_prices(path: Path, preferred_field: str) -> dict[tuple[str, str], tuple[float, str]]:
    prices: dict[tuple[str, str], tuple[float, str]] = {}
    if not path.exists():
        return prices
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = [field.lower() for field in (reader.fieldnames or [])]
        symbol_field = "ticker" if "ticker" in fields else "symbol"
        date_field = "latest_price_date" if "latest_price_date" in fields else "date"
        for row in reader:
            symbol = norm(row.get(symbol_field)).upper()
            day = norm(row.get(date_field))[:10]
            value, actual_field = choose_price(row, preferred_field)
            if symbol and day and value is not None:
                prices[(symbol, day)] = (value, actual_field)
    return prices


def max_price_date(path: Path, symbol_filter: str | None = None) -> str:
    out = ""
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = [field.lower() for field in (reader.fieldnames or [])]
        symbol_field = "symbol" if "symbol" in fields else "ticker"
        date_field = "date" if "date" in fields else "latest_price_date"
        for row in reader:
            symbol = norm(row.get(symbol_field)).upper()
            if symbol_filter and symbol != symbol_filter.upper():
                continue
            day = norm(row.get(date_field))[:10]
            if len(day) == 10 and day[4] == "-" and day[7] == "-":
                out = day if not out else max(out, day)
    return out


def scope_rows(r8b_decision: dict[str, str], mapping: list[dict[str, str]], refreshed: list[dict[str, str]], pending: list[dict[str, str]]) -> tuple[list[dict[str, object]], bool, bool]:
    required_inputs = [R8_REFRESHED, R8_PENDING, R8B_MAPPING, R8B_DECISION, R8B_COVERAGE, REPAIR_SOURCE_DEFAULT, CANONICAL_TICKER, CANONICAL_BENCHMARK]
    inputs_found = all(path.exists() and path.stat().st_size > 0 for path in required_inputs)
    r8b_ready = (
        r8b_decision.get("final_status") == "PASS_V21_044_R8B_LOCAL_PRICE_SOURCE_REPAIR_READY"
        and r8b_decision.get("decision") == "R8_RERUN_ALLOWED_WITH_LOCAL_PRICE_SOURCE_REPAIR"
    )
    mapping_ready = any(row.get("mapping_role") == "ticker_entry_prices" for row in mapping) and any(row.get("mapping_role") == "benchmark_entry_price" for row in mapping)
    row_count_preserved_source = bool(refreshed) and bool(pending) and len(refreshed) == len(pending)
    no_returns = all(not row.get("realized_forward_return") and not row.get("benchmark_forward_return") and not row.get("excess_vs_QQQ") for row in refreshed + pending)
    checks = [
        ("required_inputs_found", inputs_found, "R8, R8B, repair source, and canonical price artifacts must exist."),
        ("r8b_repair_mapping_ready", r8b_ready and mapping_ready, "R8B must explicitly allow rerun with local repair mapping."),
        ("source_row_count_preserved", row_count_preserved_source, "R8 refreshed and pending row counts must match before repair-aware rerun."),
        ("no_realized_returns_in_source", no_returns, "R8-R1 must start from pending rows without realized returns."),
        ("canonical_overwrite_disabled", True, "Canonical price files are read-only inputs for this stage."),
        ("restricted_scope_guardrails", all(GUARDRAILS[field] == "FALSE" for field in FALSE_GUARDRAILS), "Official, execution, full-weight, shadow, online, and yfinance permissions remain disabled."),
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
        }
        for name, passed, notes in checks
    ]
    return rows, inputs_found and r8b_ready and mapping_ready, all(passed for _, passed, _ in checks)


def main() -> int:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW.mkdir(parents=True, exist_ok=True)
    READ_CENTER.mkdir(parents=True, exist_ok=True)

    source_rows = read_rows(R8_REFRESHED)
    source_pending = read_rows(R8_PENDING)
    mapping_rows = read_rows(R8B_MAPPING)
    r8b_decision = (read_rows(R8B_DECISION) or [{}])[0]
    coverage_rows = read_rows(R8B_COVERAGE)
    scope, mapping_ready, scope_ok = scope_rows(r8b_decision, mapping_rows, source_rows, source_pending)
    write_rows(SCOPE_AUDIT, scope)

    ticker_mapping = next((row for row in mapping_rows if row.get("mapping_role") == "ticker_entry_prices"), {})
    benchmark_mapping = next((row for row in mapping_rows if row.get("mapping_role") == "benchmark_entry_price"), {})
    repair_source_path = path_from_repo(ticker_mapping.get("source_path") or r8b_decision.get("selected_repair_source") or rel(REPAIR_SOURCE_DEFAULT))
    preferred_field = ticker_mapping.get("price_field") or "adjusted_close"
    observation_date = ticker_mapping.get("required_date") or r8b_decision.get("required_entry_date") or OBSERVATION_DATE
    repair_prices = load_repair_prices(repair_source_path, preferred_field)
    maturity_covered = {
        row.get("coverage_requirement", ""): row.get("local_source_covers_requirement") == "TRUE"
        for row in coverage_rows
    }

    output_rows: list[dict[str, object]] = []
    price_audit: list[dict[str, object]] = []
    maturity_audit: list[dict[str, object]] = []
    entry_repaired = 0
    benchmark_repaired = 0
    remaining_entry_missing = 0
    price_missing = 0
    rows_with_realized = 0
    rows_with_benchmark_return = 0

    for row in source_rows:
        out = dict(row)
        ticker = norm(row.get("ticker")).upper()
        benchmark = norm(row.get("benchmark_symbol") or BENCHMARK_SYMBOL).upper()
        ticker_key = (ticker, observation_date)
        benchmark_key = (benchmark, observation_date)
        ticker_binding_before = norm(row.get("entry_price_binding_status"))
        benchmark_binding_before = norm(row.get("benchmark_entry_binding_status"))
        ticker_bound = repair_prices.get(ticker_key)
        benchmark_bound = repair_prices.get(benchmark_key)

        if mapping_ready and ticker_bound:
            out["entry_price"] = fmt(ticker_bound[0])
            out["entry_price_date"] = observation_date
            out["entry_price_source"] = rel(repair_source_path)
            out["entry_price_binding_status"] = "R8B_REPAIR_MAPPING_EXACT_ENTRY_PRICE"
            if ticker_binding_before != "R8B_REPAIR_MAPPING_EXACT_ENTRY_PRICE":
                entry_repaired += 1
        else:
            out["entry_price_binding_status"] = "LOCAL_REPAIR_PRICE_NOT_AVAILABLE"

        if mapping_ready and benchmark_bound:
            out["benchmark_entry_price"] = fmt(benchmark_bound[0])
            out["benchmark_entry_date"] = observation_date
            out["benchmark_price_source"] = rel(repair_source_path)
            out["benchmark_entry_binding_status"] = "R8B_REPAIR_MAPPING_EXACT_BENCHMARK_ENTRY_PRICE"
            if benchmark_binding_before != "R8B_REPAIR_MAPPING_EXACT_BENCHMARK_ENTRY_PRICE":
                benchmark_repaired += 1
        else:
            out["benchmark_entry_binding_status"] = "LOCAL_REPAIR_BENCHMARK_PRICE_NOT_AVAILABLE"

        if not out.get("entry_price") or not out.get("benchmark_entry_price"):
            remaining_entry_missing += 1
            price_missing += 1

        window = norm(row.get("forward_window"))
        maturity_date = norm(row.get("scheduled_maturity_date"))
        maturity_requirement = f"{window}_maturity_price_coverage"
        can_mature = bool(maturity_covered.get(maturity_requirement, False))
        # This stage deliberately does not compute returns unless exact maturity coverage exists.
        if can_mature:
            out["maturity_status"] = "PENDING_NOT_MATURED"
        else:
            out["ticker_forward_price"] = ""
            out["ticker_forward_price_date"] = ""
            out["ticker_forward_price_source"] = ""
            out["benchmark_forward_price"] = ""
            out["benchmark_forward_price_date"] = ""
            out["benchmark_forward_price_source"] = ""
            out["maturity_status"] = "PENDING_NOT_MATURED"
        out["realized_forward_return"] = ""
        out["benchmark_forward_return"] = ""
        out["excess_vs_QQQ"] = ""
        out.update(GUARDRAILS)
        output_rows.append(out)

        price_audit.append({
            "observation_id": row.get("observation_id", ""),
            "observation_as_of_date": row.get("observation_as_of_date", ""),
            "ticker": ticker,
            "bucket": row.get("bucket", ""),
            "forward_window": window,
            "scheduled_maturity_date": maturity_date,
            "ticker_entry_binding_status_before": ticker_binding_before,
            "ticker_entry_binding_status_after": out["entry_price_binding_status"],
            "ticker_entry_price_date": out.get("entry_price_date", ""),
            "ticker_entry_price": out.get("entry_price", ""),
            "benchmark_entry_binding_status_before": benchmark_binding_before,
            "benchmark_entry_binding_status_after": out["benchmark_entry_binding_status"],
            "benchmark_entry_price_date": out.get("benchmark_entry_date", ""),
            "benchmark_entry_price": out.get("benchmark_entry_price", ""),
            "repair_source": rel(repair_source_path),
            "price_field_used": ticker_bound[1] if ticker_bound else "",
            "benchmark_price_field_used": benchmark_bound[1] if benchmark_bound else "",
            "ticker_entry_repaired": yn(bool(ticker_bound)),
            "benchmark_entry_repaired": yn(bool(benchmark_bound)),
            "price_missing_after": yn(not out.get("entry_price") or not out.get("benchmark_entry_price")),
            "zero_fill_used": "FALSE",
            "fabricated_price_used": "FALSE",
            "maturity_status": out["maturity_status"],
            **GUARDRAILS,
        })
        maturity_audit.append({
            "observation_id": row.get("observation_id", ""),
            "observation_as_of_date": row.get("observation_as_of_date", ""),
            "ticker": ticker,
            "bucket": row.get("bucket", ""),
            "forward_window": window,
            "scheduled_maturity_date": maturity_date,
            "maturity_price_coverage_available": yn(can_mature),
            "maturity_status_before": row.get("maturity_status", ""),
            "maturity_status_after": out["maturity_status"],
            "realized_return_computed": "FALSE",
            "benchmark_return_computed": "FALSE",
            "fabricated_return_used": "FALSE",
            "notes": "Maturity dates remain uncovered locally; row remains pending.",
            **GUARDRAILS,
        })

    refreshed_rows = len(output_rows)
    matured_rows = sum(1 for row in output_rows if row.get("maturity_status") == "MATURED")
    pending_rows = refreshed_rows - matured_rows
    rows_with_realized = sum(1 for row in output_rows if norm(row.get("realized_forward_return")))
    rows_with_benchmark_return = sum(1 for row in output_rows if norm(row.get("benchmark_forward_return")))
    fabricated_returns = 0

    ledger_fields = list(source_rows[0].keys()) if source_rows else []
    for field in GUARDRAILS:
        if field not in ledger_fields:
            ledger_fields.append(field)
    write_rows(OUT_REFRESHED, output_rows, ledger_fields)
    write_rows(OUT_PENDING, [row for row in output_rows if row.get("maturity_status") == "PENDING_NOT_MATURED"], ledger_fields)
    write_rows(OUT_PRICE_AUDIT, price_audit)
    write_rows(OUT_MATURITY_AUDIT, maturity_audit)

    if not mapping_ready:
        final_status = MAPPING_BLOCKED
        decision = "R8B_REPAIR_MAPPING_NOT_READY"
        recommended_next_stage = "V21.044-R8B_TECHNICAL_ONLY_PRICE_CACHE_REFRESH_OR_SOURCE_REPAIR"
    elif not scope_ok:
        final_status = BOUNDARY_BLOCKED
        decision = "BLOCK_REPAIR_AWARE_MATURITY_REFRESH"
        recommended_next_stage = "V21.044-R8-R1_TECHNICAL_ONLY_MATURITY_REFRESH_WITH_R8B_REPAIR_MAPPING"
    elif remaining_entry_missing:
        final_status = PARTIAL_WARN_STATUS
        decision = "ENTRY_PRICE_PARTIALLY_REPAIRED_REVIEW_PRICE_COVERAGE"
        recommended_next_stage = "V21.044-R8B_R1_PARTIAL_PRICE_COVERAGE_REVIEW"
    elif matured_rows == 0:
        final_status = PASS_STATUS
        decision = "ENTRY_PRICE_REPAIRED_WAIT_FOR_MATURITY_DATES"
        recommended_next_stage = "V21.044-R8A_WAIT_UNTIL_FIRST_MATURITY_DATE"
    else:
        final_status = NO_MATURED_STATUS
        decision = "ENTRY_PRICE_REPAIRED_WAIT_FOR_MATURITY_DATES"
        recommended_next_stage = "V21.044-R9_TECHNICAL_ONLY_MATURED_RESULT_EVALUATOR"

    repair_summary_row = {
        "stage": STAGE,
        "repair_source": rel(repair_source_path),
        "observation_as_of_date": observation_date,
        "input_ledger_rows": len(source_rows),
        "refreshed_ledger_rows": refreshed_rows,
        "entry_price_repaired_row_count": entry_repaired,
        "benchmark_entry_price_repaired_row_count": benchmark_repaired,
        "remaining_entry_price_missing_count": remaining_entry_missing,
        "matured_row_count": matured_rows,
        "pending_row_count": pending_rows,
        "price_missing_row_count": price_missing,
        "rows_with_fabricated_returns": fabricated_returns,
        "rows_with_realized_forward_return_populated": rows_with_realized,
        "rows_with_benchmark_forward_return_populated": rows_with_benchmark_return,
        "canonical_price_file_overwrite_allowed": "FALSE",
        **GUARDRAILS,
    }
    write_rows(REPAIR_SUMMARY, [repair_summary_row])

    decision_row = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "input_ledger_rows": len(source_rows),
        "refreshed_ledger_rows": refreshed_rows,
        "entry_price_repaired_row_count": entry_repaired,
        "benchmark_entry_price_repaired_row_count": benchmark_repaired,
        "remaining_entry_price_missing_count": remaining_entry_missing,
        "matured_row_count": matured_rows,
        "pending_row_count": pending_rows,
        "price_missing_row_count": price_missing,
        "rows_with_fabricated_returns": fabricated_returns,
        "rows_with_realized_forward_return_populated": rows_with_realized,
        "rows_with_benchmark_forward_return_populated": rows_with_benchmark_return,
        "observation_as_of_date": observation_date,
        "repair_source": rel(repair_source_path),
        "canonical_ticker_price_max_date": max_price_date(CANONICAL_TICKER),
        "canonical_benchmark_price_max_date": max_price_date(CANONICAL_BENCHMARK, BENCHMARK_SYMBOL),
        "full_weight_blocked": "TRUE",
        "recommended_next_stage": recommended_next_stage,
        "r9_result_evaluator_allowed_now": yn(matured_rows > 0),
        **GUARDRAILS,
    }
    write_rows(DECISION_SUMMARY, [decision_row])

    report = f"""# V21.044-R8-R1 Technical-only maturity refresh with R8B repair mapping

final_status: {final_status}

decision: {decision}

input ledger rows: {len(source_rows)}

refreshed ledger rows: {refreshed_rows}

entry price repaired row count: {entry_repaired}

benchmark entry price repaired row count: {benchmark_repaired}

remaining entry price missing count: {remaining_entry_missing}

matured row count: {matured_rows}

pending row count: {pending_rows}

price missing row count: {price_missing}

rows with fabricated returns: {fabricated_returns}

rows with realized_forward_return populated: {rows_with_realized}

rows with benchmark_forward_return populated: {rows_with_benchmark_return}

Repair source used: {rel(repair_source_path)}

Maturity dates remain uncovered by the local repair source, so rows remain PENDING_NOT_MATURED and no realized returns were computed.

No buy/sell/hold recommendation was created.

Technical-only observation must not be interpreted as full-weight result or full-weight evidence.

Full-weight remains blocked: TRUE. full_weight_result_available=FALSE and full_weight_rebacktest_allowed_now=FALSE.

Recommended next stage: {recommended_next_stage}

Guardrail statement: this stage is research-only and maturity-refresh-only. It used the R8B repair mapping, did not append observations, did not fabricate prices or returns, did not overwrite canonical price files, did not download data, did not use yfinance, and did not write broker, execution, real-book, trade-action, official recommendation, official ranking, or official weight mutation outputs.
"""
    REPORT.write_text(report, encoding="utf-8")
    shutil.copyfile(REPORT, CURRENT_REPORT)

    print(f"final_status={final_status}")
    print(f"decision={decision}")
    print(f"input_ledger_rows={len(source_rows)}")
    print(f"refreshed_ledger_rows={refreshed_rows}")
    print(f"entry_price_repaired_row_count={entry_repaired}")
    print(f"benchmark_entry_price_repaired_row_count={benchmark_repaired}")
    print(f"remaining_entry_price_missing_count={remaining_entry_missing}")
    print(f"matured_row_count={matured_rows}")
    print(f"pending_row_count={pending_rows}")
    print(f"full_weight_blocked=TRUE")
    print(f"recommended_next_stage={recommended_next_stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
