#!/usr/bin/env python
"""Research-only local price-cache coverage resolver for V21.044-R8B."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path


STAGE = "V21.044-R8B_TECHNICAL_ONLY_PRICE_CACHE_REFRESH_OR_SOURCE_REPAIR"
PASS_STATUS = "PASS_V21_044_R8B_LOCAL_PRICE_SOURCE_REPAIR_READY"
REFRESH_STATUS = "PARTIAL_PASS_V21_044_R8B_PRICE_REFRESH_REQUIRED"
PARTIAL_STATUS = "PARTIAL_PASS_V21_044_R8B_PARTIAL_LOCAL_COVERAGE_FOUND"
MISSING_STATUS = "BLOCKED_V21_044_R8B_R8A_OUTPUTS_NOT_FOUND"
BOUNDARY_STATUS = "BLOCKED_V21_044_R8B_SCOPE_BOUNDARY_FAILED"

ROOT = Path(__file__).resolve().parents[2]
LEDGER_DIR = ROOT / "outputs" / "v21" / "ledger"
REVIEW = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"
PRICE_HISTORY = ROOT / "outputs" / "v20" / "price_history"

R8A_DECISION = REVIEW / "V21_044_R8A_DECISION_SUMMARY.csv"
R8A_REQUIREMENT = REVIEW / "V21_044_R8A_PRICE_COVERAGE_REQUIREMENT.csv"
R8A_READINESS = REVIEW / "V21_044_R8A_MATURITY_READINESS_BY_WINDOW.csv"
R8_REFRESHED = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_OBSERVATION_LEDGER_REFRESHED.csv"
R8_PENDING = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_PENDING_ROWS.csv"
R8_PRICE_AUDIT = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_PRICE_BINDING_AUDIT.csv"
R7_LEDGER = LEDGER_DIR / "V21_044_R7_TECHNICAL_ONLY_OBSERVATION_LEDGER.csv"
CANONICAL_TICKER = PRICE_HISTORY / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
CANONICAL_BENCHMARK = PRICE_HISTORY / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"

DISCOVERY = REVIEW / "V21_044_R8B_PRICE_SOURCE_DISCOVERY.csv"
COVERAGE_AUDIT = REVIEW / "V21_044_R8B_REQUIRED_PRICE_COVERAGE_AUDIT.csv"
REPAIR_MAPPING = REVIEW / "V21_044_R8B_PRICE_SOURCE_REPAIR_MAPPING.csv"
REFRESH_CONTRACT = REVIEW / "V21_044_R8B_PRICE_REFRESH_REQUIREMENT_CONTRACT.csv"
SCOPE_AUDIT = REVIEW / "V21_044_R8B_SCOPE_BOUNDARY_AUDIT.csv"
DECISION_SUMMARY = REVIEW / "V21_044_R8B_DECISION_SUMMARY.csv"
REPORT = READ_CENTER / "V21_044_R8B_TECHNICAL_ONLY_PRICE_CACHE_REFRESH_OR_SOURCE_REPAIR_REPORT.md"
CURRENT_REPORT = READ_CENTER / "CURRENT_V21_044_R8B_TECHNICAL_ONLY_PRICE_CACHE_REFRESH_OR_SOURCE_REPAIR_REPORT.md"

OBSERVATION_DATE = "2026-06-16"
BENCHMARK_SYMBOL = "QQQ"
WINDOW_DATES = {
    "entry": "2026-06-16",
    "5D": "2026-06-24",
    "10D": "2026-07-01",
    "20D": "2026-07-16",
    "60D": "2026-09-11",
}

SCAN_ROOTS = [
    ROOT / "outputs" / "v21",
    ROOT / "outputs" / "v20" / "price_history",
    ROOT / "outputs" / "v20" / "consolidation",
    ROOT / "outputs" / "v20" / "factors",
    ROOT / "outputs" / "v20" / "read_center",
    ROOT / "data",
]

GUARDRAILS = {
    "research_only": "TRUE",
    "price_source_repair_only": "TRUE",
    "observation_only": "TRUE",
    "maturity_refresh_only": "FALSE",
    "realized_return_computation_allowed": "FALSE",
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
    "maturity_refresh_only",
    "realized_return_computation_allowed",
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


def is_date(value: str) -> bool:
    if len(value) < 10:
        return False
    text = value[:10]
    return len(text) == 10 and text[4] == "-" and text[7] == "-" and text.replace("-", "").isdigit()


def date10(value: str) -> str:
    return value[:10] if is_date(value) else ""


def pick_column(fields: list[str], names: list[str], contains: list[str] | None = None) -> str:
    lower = {field.lower(): field for field in fields}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    if contains:
        for field in fields:
            low = field.lower()
            if all(part in low for part in contains):
                return field
    return ""


def price_field(fields: list[str]) -> tuple[str, str, str]:
    adjusted = pick_column(fields, ["adjusted_close", "adj_close", "adjclose", "adj close"], ["adj", "close"])
    close = pick_column(fields, ["close", "Close"])
    return adjusted or close, adjusted, close


def required_tickers() -> list[str]:
    tickers = {norm(row.get("ticker")).upper() for row in read_rows(R7_LEDGER) + read_rows(R8_REFRESHED)}
    return sorted(ticker for ticker in tickers if ticker)


def candidate_paths() -> list[Path]:
    seen: set[Path] = set()
    paths: list[Path] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.csv"):
            resolved = path.resolve()
            if ROOT not in resolved.parents and resolved != ROOT:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            paths.append(resolved)
    return sorted(paths, key=lambda item: rel(item).lower())


def source_type(path: Path) -> str:
    if path == CANONICAL_TICKER:
        return "canonical_ticker_price_source"
    if path == CANONICAL_BENCHMARK:
        return "canonical_benchmark_price_source"
    lower = path.name.lower()
    if "price" in lower or "ohlcv" in lower:
        return "local_price_candidate"
    return "local_csv_candidate"


def inspect_candidate(path: Path, tickers: set[str], required_dates: dict[str, str]) -> dict[str, object]:
    fields: list[str] = []
    rows = 0
    min_day = ""
    max_day = ""
    symbols: set[str] = set()
    ticker_entry_covered: set[str] = set()
    qqq_entry = False
    future_coverage = {window: False for window in required_dates if window != "entry"}
    rejection: list[str] = []

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            symbol_col = pick_column(fields, ["symbol", "ticker", "Ticker", "Symbol"])
            date_col = pick_column(fields, ["date", "Date", "price_date", "as_of_date"], ["date"])
            selected_price, adjusted_col, close_col = price_field(fields)
            for row in reader:
                rows += 1
                symbol = norm(row.get(symbol_col)).upper() if symbol_col else ""
                day = date10(norm(row.get(date_col))) if date_col else ""
                if symbol:
                    symbols.add(symbol)
                if day:
                    min_day = day if not min_day else min(min_day, day)
                    max_day = day if not max_day else max(max_day, day)
                if symbol and day == required_dates["entry"] and norm(row.get(selected_price)):
                    if symbol in tickers:
                        ticker_entry_covered.add(symbol)
                    if symbol == BENCHMARK_SYMBOL:
                        qqq_entry = True
                if symbol == BENCHMARK_SYMBOL or symbol in tickers:
                    for window, required_day in required_dates.items():
                        if window != "entry" and day == required_day and norm(row.get(selected_price)):
                            future_coverage[window] = True
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        fields = []
        symbol_col = date_col = selected_price = adjusted_col = close_col = ""
        rejection.append(f"read_error:{type(exc).__name__}")
    else:
        if not fields:
            rejection.append("empty_or_headerless_csv")
        if not symbol_col:
            rejection.append("missing_symbol_or_ticker_column")
        if not date_col:
            rejection.append("missing_date_column")
        if not selected_price:
            rejection.append("missing_adjusted_close_or_close_column")
        if rows == 0:
            rejection.append("no_data_rows")

    ticker_count = len(tickers)
    entry_count = len(ticker_entry_covered)
    entry_ratio = (entry_count / ticker_count) if ticker_count else 0.0
    usable_ticker = bool(ticker_count and entry_count == ticker_count and selected_price)
    usable_benchmark = bool(qqq_entry and selected_price)
    usable_any = usable_ticker or usable_benchmark
    if selected_price and ticker_count and 0 < entry_count < ticker_count:
        rejection.append("partial_required_ticker_entry_coverage")
    elif selected_price and ticker_count and entry_count == 0:
        rejection.append("no_required_ticker_entry_coverage")
    if selected_price and not qqq_entry:
        rejection.append("no_QQQ_entry_coverage")

    status = "USABLE_FULL_ENTRY_COVERAGE" if usable_ticker and usable_benchmark else (
        "USABLE_PARTIAL_ENTRY_COVERAGE" if usable_any else "REJECTED_FOR_ENTRY_BINDING"
    )
    return {
        "candidate_path": rel(path),
        "row_count": rows,
        "column_count": len(fields),
        "ticker_symbol_column": symbol_col,
        "date_column": date_col,
        "adjusted_close_column": adjusted_col,
        "close_column": close_col,
        "selected_price_field": selected_price,
        "min_date": min_day,
        "max_date": max_day,
        "distinct_ticker_count": len(symbols),
        "required_ticker_coverage_count": entry_count,
        "required_ticker_count": ticker_count,
        "required_ticker_coverage_ratio": f"{entry_ratio:.10f}",
        "missing_ticker_count": max(ticker_count - entry_count, 0),
        "missing_tickers": "|".join(sorted(tickers - ticker_entry_covered)),
        "QQQ_coverage_for_2026_06_16": yn(qqq_entry),
        "coverage_for_5D_required_date": yn(future_coverage.get("5D", False)),
        "coverage_for_10D_required_date": yn(future_coverage.get("10D", False)),
        "coverage_for_20D_required_date": yn(future_coverage.get("20D", False)),
        "coverage_for_60D_required_date": yn(future_coverage.get("60D", False)),
        "source_type": source_type(path),
        "source_status": status,
        "usable_for_entry_price_binding": yn(usable_ticker),
        "usable_for_benchmark_entry_binding": yn(usable_benchmark),
        "usable_for_any_entry_binding": yn(usable_any),
        "rejection_reason": "|".join(dict.fromkeys(rejection)),
        **GUARDRAILS,
    }


def select_sources(discovery: list[dict[str, object]]) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    full = [
        row for row in discovery
        if row["usable_for_entry_price_binding"] == "TRUE" and row["usable_for_benchmark_entry_binding"] == "TRUE"
    ]
    if full:
        canonical = [row for row in full if row["candidate_path"] in {rel(CANONICAL_TICKER), rel(CANONICAL_BENCHMARK)}]
        chosen = canonical[0] if canonical else full[0]
        return chosen, chosen
    ticker = next((row for row in discovery if row["usable_for_entry_price_binding"] == "TRUE"), None)
    bench = next((row for row in discovery if row["usable_for_benchmark_entry_binding"] == "TRUE"), None)
    return ticker, bench


def max_date_for(path: Path, symbol: str | None = None) -> str:
    if not path.exists():
        return ""
    fields: list[str] = []
    out = ""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        symbol_col = pick_column(fields, ["symbol", "ticker", "Ticker", "Symbol"])
        date_col = pick_column(fields, ["date", "Date", "price_date"], ["date"])
        for row in reader:
            if symbol and norm(row.get(symbol_col)).upper() != symbol.upper():
                continue
            day = date10(norm(row.get(date_col)))
            if day:
                out = day if not out else max(out, day)
    return out


def scope_audit_rows(r8a_summary: dict[str, str], refreshed: list[dict[str, str]], pending: list[dict[str, str]]) -> tuple[list[dict[str, object]], bool, bool]:
    required = [R8A_DECISION, R8A_REQUIREMENT, R8A_READINESS, R8_REFRESHED, R8_PENDING, R8_PRICE_AUDIT, R7_LEDGER, CANONICAL_TICKER, CANONICAL_BENCHMARK]
    inputs_found = all(path.exists() and path.stat().st_size > 0 for path in required)
    no_returns = all(
        not row.get("realized_forward_return") and not row.get("benchmark_forward_return") and not row.get("excess_vs_QQQ")
        for row in refreshed + pending
    )
    expected_r8a = r8a_summary.get("decision") == "WAIT_FOR_PRICE_CACHE_REFRESH_BEFORE_R8_RERUN"
    pending_match = bool(refreshed) and bool(pending) and len(refreshed) == len(pending)
    checks = [
        ("r8a_outputs_found", inputs_found, "Required R8A, R8, R7, and canonical price artifacts must exist."),
        ("r8a_routes_to_r8b", expected_r8a, "R8A must request price-cache refresh/source repair before R8 rerun."),
        ("ledger_pending_rows_unchanged", pending_match, "R8 refreshed rows must still align with pending rows."),
        ("no_realized_returns_present", no_returns, "R8B must not compute or observe realized forward-return outputs."),
        ("local_artifacts_only", True, "R8B scans only configured project-local artifact roots."),
        ("restricted_scope_guardrails", all(GUARDRAILS[field] == "FALSE" for field in FALSE_GUARDRAILS), "Official, execution, full-weight, shadow, online, and return-computation permissions remain disabled."),
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
    return rows, inputs_found, all(passed for _, passed, _ in checks)


def main() -> int:
    REVIEW.mkdir(parents=True, exist_ok=True)
    READ_CENTER.mkdir(parents=True, exist_ok=True)

    r8a_summary = (read_rows(R8A_DECISION) or [{}])[0]
    r8a_requirements = read_rows(R8A_REQUIREMENT)
    r8a_readiness = read_rows(R8A_READINESS)
    refreshed = read_rows(R8_REFRESHED)
    pending = read_rows(R8_PENDING)
    r7_rows = read_rows(R7_LEDGER)
    tickers = set(required_tickers())
    required_symbols = sorted(tickers | {BENCHMARK_SYMBOL})

    scope_rows, inputs_found, scope_ok = scope_audit_rows(r8a_summary, refreshed, pending)
    write_rows(SCOPE_AUDIT, scope_rows)

    canonical_ticker_max = max_date_for(CANONICAL_TICKER)
    canonical_benchmark_max = max_date_for(CANONICAL_BENCHMARK, BENCHMARK_SYMBOL)
    observation_date = r8a_summary.get("observation_as_of_date") or OBSERVATION_DATE
    required_dates = {
        "entry": observation_date,
        "5D": r8a_summary.get("required_price_date_for_5D") or WINDOW_DATES["5D"],
        "10D": r8a_summary.get("required_price_date_for_10D") or WINDOW_DATES["10D"],
        "20D": r8a_summary.get("required_price_date_for_20D") or WINDOW_DATES["20D"],
        "60D": r8a_summary.get("required_price_date_for_60D") or WINDOW_DATES["60D"],
    }

    discovery = [inspect_candidate(path, tickers, required_dates) for path in candidate_paths()]
    discovery_fields = [
        "candidate_path", "row_count", "column_count", "ticker_symbol_column", "date_column",
        "adjusted_close_column", "close_column", "selected_price_field", "min_date", "max_date",
        "distinct_ticker_count", "required_ticker_coverage_count", "required_ticker_count",
        "required_ticker_coverage_ratio", "missing_ticker_count", "missing_tickers",
        "QQQ_coverage_for_2026_06_16", "coverage_for_5D_required_date", "coverage_for_10D_required_date",
        "coverage_for_20D_required_date", "coverage_for_60D_required_date", "source_type", "source_status",
        "usable_for_entry_price_binding", "usable_for_benchmark_entry_binding", "usable_for_any_entry_binding",
        "rejection_reason", *GUARDRAILS.keys(),
    ]
    write_rows(DISCOVERY, discovery, discovery_fields)

    ticker_source, benchmark_source = select_sources(discovery)
    local_full_source = bool(ticker_source and benchmark_source and ticker_source["candidate_path"] == benchmark_source["candidate_path"]
                             and ticker_source["usable_for_entry_price_binding"] == "TRUE"
                             and benchmark_source["usable_for_benchmark_entry_binding"] == "TRUE")
    partial_local = bool(ticker_source or benchmark_source) and not local_full_source
    missing_tickers = sorted(tickers - set((ticker_source or {}).get("missing_tickers", "").split("|"))) if False else []
    if ticker_source:
        missing_ticker_list = norm(ticker_source.get("missing_tickers"))
        missing_ticker_count = int(ticker_source.get("missing_ticker_count") or 0)
    else:
        missing_ticker_list = "|".join(sorted(tickers))
        missing_ticker_count = len(tickers)
    qqq_coverage = bool(benchmark_source and benchmark_source["usable_for_benchmark_entry_binding"] == "TRUE")

    coverage_rows: list[dict[str, object]] = []
    for label, required_day in required_dates.items():
        coverage_rows.append({
            "coverage_requirement": "entry_price_binding" if label == "entry" else f"{label}_maturity_price_coverage",
            "required_price_date": required_day,
            "required_symbols": "|".join(required_symbols),
            "required_symbol_count": len(required_symbols),
            "ticker_source_candidate": ticker_source["candidate_path"] if ticker_source else "",
            "benchmark_source_candidate": benchmark_source["candidate_path"] if benchmark_source else "",
            "ticker_entry_coverage_count": ticker_source["required_ticker_coverage_count"] if ticker_source else 0,
            "required_ticker_count": len(tickers),
            "missing_ticker_count": missing_ticker_count if label == "entry" else "",
            "missing_tickers": missing_ticker_list if label == "entry" else "",
            "QQQ_coverage": yn(qqq_coverage) if label == "entry" else (benchmark_source.get(f"coverage_for_{label}_required_date", "FALSE") if benchmark_source else "FALSE"),
            "local_source_covers_requirement": yn(local_full_source) if label == "entry" else yn(bool(ticker_source and benchmark_source and ticker_source.get(f"coverage_for_{label}_required_date") == "TRUE" and benchmark_source.get(f"coverage_for_{label}_required_date") == "TRUE")),
            "no_returns_computed": "TRUE",
            **GUARDRAILS,
        })
    write_rows(COVERAGE_AUDIT, coverage_rows)

    mapping_rows: list[dict[str, object]] = []
    if ticker_source:
        mapping_rows.append({
            "mapping_role": "ticker_entry_prices",
            "source_path": ticker_source["candidate_path"],
            "price_field": ticker_source["selected_price_field"],
            "required_date": observation_date,
            "required_ticker_coverage_count": ticker_source["required_ticker_coverage_count"],
            "required_ticker_count": len(tickers),
            "missing_ticker_count": ticker_source["missing_ticker_count"],
            "missing_tickers": ticker_source["missing_tickers"],
            "canonical_price_file_overwrite_allowed": "FALSE",
            "realized_returns_computed": "FALSE",
            **GUARDRAILS,
        })
    if benchmark_source:
        mapping_rows.append({
            "mapping_role": "benchmark_entry_price",
            "source_path": benchmark_source["candidate_path"],
            "price_field": benchmark_source["selected_price_field"],
            "required_date": observation_date,
            "required_ticker_coverage_count": 1 if qqq_coverage else 0,
            "required_ticker_count": 1,
            "missing_ticker_count": 0 if qqq_coverage else 1,
            "missing_tickers": "" if qqq_coverage else BENCHMARK_SYMBOL,
            "canonical_price_file_overwrite_allowed": "FALSE",
            "realized_returns_computed": "FALSE",
            **GUARDRAILS,
        })
    for window in ["5D", "10D", "20D", "60D"]:
        if ticker_source or benchmark_source:
            mapping_rows.append({
                "mapping_role": f"{window}_future_maturity_prices_if_available",
                "source_path": (ticker_source or benchmark_source)["candidate_path"],
                "price_field": (ticker_source or benchmark_source)["selected_price_field"],
                "required_date": required_dates[window],
                "required_ticker_coverage_count": "",
                "required_ticker_count": len(tickers),
                "missing_ticker_count": "",
                "missing_tickers": "",
                "canonical_price_file_overwrite_allowed": "FALSE",
                "realized_returns_computed": "FALSE",
                **GUARDRAILS,
            })
    write_rows(REPAIR_MAPPING, mapping_rows, [
        "mapping_role", "source_path", "price_field", "required_date", "required_ticker_coverage_count",
        "required_ticker_count", "missing_ticker_count", "missing_tickers",
        "canonical_price_file_overwrite_allowed", "realized_returns_computed", *GUARDRAILS.keys(),
    ])

    refresh_rows = [{
        "required_symbols": "|".join(required_symbols),
        "required_symbol_count": len(required_symbols),
        "required_start_date": observation_date,
        "minimum_required_end_date_for_entry": required_dates["entry"],
        "minimum_required_end_date_for_5D": required_dates["5D"],
        "minimum_required_end_date_for_10D": required_dates["10D"],
        "minimum_required_end_date_for_20D": required_dates["20D"],
        "minimum_required_end_date_for_60D": required_dates["60D"],
        "preferred_refresh_path": "V21.044-R8C_OPERATOR_APPROVED_PRICE_CACHE_REFRESH_BRIDGE",
        "refresh_executed_by_r8b": "FALSE",
        "online_download_attempted": "FALSE",
        "price_fabrication_allowed": "FALSE",
        **GUARDRAILS,
    }]
    write_rows(REFRESH_CONTRACT, refresh_rows)

    if not inputs_found:
        final_status = MISSING_STATUS
        decision = "BLOCK_PRICE_SOURCE_REPAIR"
        recommended_next_stage = "V21.044-R8A_TECHNICAL_ONLY_LEDGER_MATURITY_WAIT_STATUS"
    elif not scope_ok:
        final_status = BOUNDARY_STATUS
        decision = "BLOCK_PRICE_SOURCE_REPAIR"
        recommended_next_stage = "V21.044-R8B_TECHNICAL_ONLY_PRICE_CACHE_REFRESH_OR_SOURCE_REPAIR"
    elif local_full_source:
        final_status = PASS_STATUS
        decision = "R8_RERUN_ALLOWED_WITH_LOCAL_PRICE_SOURCE_REPAIR"
        recommended_next_stage = "rerun V21.044-R8_TECHNICAL_ONLY_LEDGER_MATURITY_REFRESH with the repair mapping"
    elif partial_local:
        final_status = PARTIAL_STATUS
        decision = "PARTIAL_PRICE_COVERAGE_REPAIR_REVIEW_REQUIRED"
        recommended_next_stage = "V21.044-R8B_R1_PARTIAL_PRICE_COVERAGE_REVIEW"
    else:
        final_status = REFRESH_STATUS
        decision = "NEED_OPERATOR_APPROVED_PRICE_CACHE_REFRESH_BEFORE_R8_RERUN"
        recommended_next_stage = "V21.044-R8C_OPERATOR_APPROVED_PRICE_CACHE_REFRESH_BRIDGE"

    r8_rerun_allowed = final_status == PASS_STATUS
    operator_refresh_required = final_status in {REFRESH_STATUS, PARTIAL_STATUS}
    selected_repair_source = ticker_source["candidate_path"] if local_full_source and ticker_source else ""
    local_source_covers_entry = local_full_source

    decision_row = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "observation_as_of_date": observation_date,
        "required_entry_date": observation_date,
        "canonical_ticker_price_max_date": canonical_ticker_max,
        "canonical_benchmark_price_max_date": canonical_benchmark_max,
        "local_source_covers_2026_06_16": yn(local_source_covers_entry),
        "selected_repair_source": selected_repair_source,
        "ticker_source_candidate": ticker_source["candidate_path"] if ticker_source else "",
        "benchmark_source_candidate": benchmark_source["candidate_path"] if benchmark_source else "",
        "missing_ticker_count": missing_ticker_count,
        "missing_tickers": missing_ticker_list,
        "QQQ_coverage_status": "COVERED" if qqq_coverage else "MISSING",
        "r8_rerun_allowed_now": yn(r8_rerun_allowed),
        "operator_approved_price_refresh_required": yn(operator_refresh_required),
        "required_price_date_for_entry": required_dates["entry"],
        "required_price_date_for_5D": required_dates["5D"],
        "required_price_date_for_10D": required_dates["10D"],
        "required_price_date_for_20D": required_dates["20D"],
        "required_price_date_for_60D": required_dates["60D"],
        "rows_maturable_now": "0",
        "r9_result_evaluator_allowed_now": "FALSE",
        "full_weight_blocked": "TRUE",
        "recommended_next_stage": recommended_next_stage,
        "no_returns_computed": "TRUE",
        "no_prices_fabricated": "TRUE",
        "source_artifacts_scanned": len(discovery),
        "r8a_requirement_rows_read": len(r8a_requirements),
        "r8a_readiness_rows_read": len(r8a_readiness),
        "r7_ledger_rows_read": len(r7_rows),
        "r8_refreshed_rows_read": len(refreshed),
        "r8_pending_rows_read": len(pending),
        **GUARDRAILS,
    }
    write_rows(DECISION_SUMMARY, [decision_row])

    report = f"""# V21.044-R8B Technical-only price-cache refresh/source-repair report

final_status: {final_status}

decision: {decision}

observation_as_of_date: {observation_date}

required entry date: {observation_date}

canonical ticker price max date: {canonical_ticker_max}

canonical benchmark price max date: {canonical_benchmark_max}

any local source covers 2026-06-16: {yn(local_source_covers_entry)}

selected repair source: {selected_repair_source or 'NONE'}

missing ticker count: {missing_ticker_count}

QQQ coverage status: {'COVERED' if qqq_coverage else 'MISSING'}

R8 rerun allowed now: {yn(r8_rerun_allowed)}

operator-approved price refresh required: {yn(operator_refresh_required)}

Required price coverage dates by window:

- entry: {required_dates['entry']}
- 5D: {required_dates['5D']}
- 10D: {required_dates['10D']}
- 20D: {required_dates['20D']}
- 60D: {required_dates['60D']}

No returns were computed. No realized forward returns or benchmark forward returns were created.

No buy/sell/hold recommendation was created.

Technical-only observation must not be interpreted as full-weight result or full-weight evidence.

Full-weight remains blocked: TRUE. full_weight_result_available=FALSE and full_weight_rebacktest_allowed_now=FALSE.

Recommended next stage: {recommended_next_stage}

Guardrail statement: R8B is research-only and price-source-repair-only. It did not append observations, did not overwrite canonical price files, did not fabricate prices, did not download data, did not use yfinance, did not create official recommendations, and did not create broker, execution, real-book, or trade-action files.
"""
    REPORT.write_text(report, encoding="utf-8")
    shutil.copyfile(REPORT, CURRENT_REPORT)

    print(f"final_status={final_status}")
    print(f"decision={decision}")
    print(f"observation_as_of_date={observation_date}")
    print(f"canonical_ticker_price_max_date={canonical_ticker_max}")
    print(f"canonical_benchmark_price_max_date={canonical_benchmark_max}")
    print(f"local_source_covers_2026_06_16={yn(local_source_covers_entry)}")
    print(f"selected_repair_source={selected_repair_source or 'NONE'}")
    print(f"r8_rerun_allowed_now={yn(r8_rerun_allowed)}")
    print(f"recommended_next_stage={recommended_next_stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
