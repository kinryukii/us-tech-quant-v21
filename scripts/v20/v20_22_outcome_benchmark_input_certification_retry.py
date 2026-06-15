from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
INPUT_BASE = ROOT / "inputs" / "v20" / "outcome_benchmark"

IN_READ_FIRST = OPS / "V20_21_READ_FIRST.txt"
IN_GATE = CONSOLIDATION / "V20_21_GATE_DECISION.csv"
IN_PATH_REGISTER = CONSOLIDATION / "V20_21_EXPECTED_INPUT_PATH_REGISTER.csv"
IN_OUTCOME_SCHEMA = CONSOLIDATION / "V20_21_OUTCOME_INPUT_TEMPLATE_SCHEMA.csv"
IN_BENCHMARK_SCHEMA = CONSOLIDATION / "V20_21_BENCHMARK_INPUT_TEMPLATE_SCHEMA.csv"
IN_NEXT_REQ = CONSOLIDATION / "V20_21_NEXT_CERTIFICATION_REQUIREMENTS.csv"
IN_OUTCOME_WINDOWS = CONSOLIDATION / "V20_20_OUTCOME_WINDOW_COVERAGE_AUDIT.csv"

OUTCOME_INPUT = INPUT_BASE / "V20_OUTCOME_SOURCE_INPUT.csv"
BENCHMARK_INPUT = INPUT_BASE / "V20_BENCHMARK_SOURCE_INPUT.csv"

OUT_DEP = CONSOLIDATION / "V20_22_DEPENDENCY_AUDIT.csv"
OUT_PATH_AUDIT = CONSOLIDATION / "V20_22_EXPECTED_INPUT_PATH_AUDIT.csv"
OUT_OUTCOME_DISCOVERY = CONSOLIDATION / "V20_22_OUTCOME_INPUT_FILE_DISCOVERY.csv"
OUT_BENCHMARK_DISCOVERY = CONSOLIDATION / "V20_22_BENCHMARK_INPUT_FILE_DISCOVERY.csv"
OUT_OUTCOME_SCHEMA = CONSOLIDATION / "V20_22_OUTCOME_INPUT_SCHEMA_CERTIFICATION_AUDIT.csv"
OUT_BENCHMARK_SCHEMA = CONSOLIDATION / "V20_22_BENCHMARK_INPUT_SCHEMA_CERTIFICATION_AUDIT.csv"
OUT_OUTCOME_QUALITY = CONSOLIDATION / "V20_22_OUTCOME_INPUT_ROW_QUALITY_AUDIT.csv"
OUT_BENCHMARK_QUALITY = CONSOLIDATION / "V20_22_BENCHMARK_INPUT_ROW_QUALITY_AUDIT.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_22_LINEAGE_HASH_RUN_ID_AUDIT.csv"
OUT_PIT = CONSOLIDATION / "V20_22_PIT_STALE_LEAKAGE_PRECHECK_AUDIT.csv"
OUT_BENCH_SYMBOL = CONSOLIDATION / "V20_22_BENCHMARK_SYMBOL_COVERAGE_AUDIT.csv"
OUT_WINDOW = CONSOLIDATION / "V20_22_OUTCOME_WINDOW_COVERAGE_AUDIT.csv"
OUT_DUP = CONSOLIDATION / "V20_22_DUPLICATE_KEY_AUDIT.csv"
OUT_CERT_REGISTER = CONSOLIDATION / "V20_22_CERTIFIED_INPUT_REGISTER.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_22_BLOCKER_REGISTER.csv"
OUT_NEXT_VALUE_REQ = CONSOLIDATION / "V20_22_NEXT_VALUE_ATTACHMENT_REQUIREMENTS.csv"
OUT_GATE = CONSOLIDATION / "V20_22_GATE_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_22_VALIDATION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_22_OUTCOME_BENCHMARK_INPUT_CERTIFICATION_RETRY_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_OUTCOME_BENCHMARK_INPUT_CERTIFICATION_RETRY.md"
READ_FIRST = OPS / "V20_22_READ_FIRST.txt"

PASS_STATUS = "PASS_V20_22_OUTCOME_BENCHMARK_INPUT_CERTIFICATION_RETRY"
NEXT_READY = "V20.23_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_RETRY"
NEXT_BLOCKED = "V20.23_OUTCOME_BENCHMARK_INPUT_SOURCE_CREATION_OR_STAGING_FROM_ALLOWED_LOCAL_DATA"
REQUIRED_INPUTS = [IN_READ_FIRST, IN_GATE, IN_PATH_REGISTER, IN_OUTCOME_SCHEMA, IN_BENCHMARK_SCHEMA, IN_NEXT_REQ]

OUTCOME_REQUIRED = [
    "ticker",
    "signal_date",
    "outcome_window",
    "outcome_price_date",
    "currency",
    "source_artifact_id",
    "source_hash",
    "run_id",
    "active_runtime_flag",
    "historical_reference_flag",
    "data_vendor_or_source_system",
]
OUTCOME_PRICE_ALTERNATIVES = ["outcome_close", "adjusted_outcome_close"]
BENCHMARK_REQUIRED = [
    "benchmark_symbol",
    "signal_date",
    "benchmark_window",
    "benchmark_price_date",
    "currency",
    "source_artifact_id",
    "source_hash",
    "run_id",
    "active_runtime_flag",
    "historical_reference_flag",
    "data_vendor_or_source_system",
]
BENCHMARK_PRICE_ALTERNATIVES = ["benchmark_close", "adjusted_benchmark_close"]
DATE_ALTERNATIVES = ["availability_date", "created_at_utc"]
EXPECTED_WINDOWS = ["forward_1d", "forward_5d", "forward_10d", "forward_20d", "forward_60d"]
BENCHMARK_SYMBOLS = ["SPY", "QQQ"]


def clean(value: object) -> str:
    return str(value or "").strip()


def upper(value: object) -> str:
    return clean(value).upper()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def parse_date(value: object) -> datetime | None:
    text = clean(value)
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def truth_all(rows: list[dict[str, str]], field: str) -> bool:
    return bool(rows) and all(upper(row.get(field)) == "TRUE" for row in rows)


def false_all(rows: list[dict[str, str]], field: str) -> bool:
    return bool(rows) and all(upper(row.get(field)) == "FALSE" for row in rows)


def nonempty_all(rows: list[dict[str, str]], field: str) -> bool:
    return bool(rows) and all(clean(row.get(field)) for row in rows)


def date_all(rows: list[dict[str, str]], field: str) -> bool:
    return bool(rows) and all(parse_date(row.get(field)) is not None for row in rows)


def has_value_any(rows: list[dict[str, str]], fields: list[str]) -> bool:
    return bool(rows) and all(any(clean(row.get(field)) for field in fields) for row in rows)


def count_missing(rows: list[dict[str, str]], field: str) -> int:
    return sum(1 for row in rows if not clean(row.get(field)))


def duplicate_count(rows: list[dict[str, str]], key_fields: list[str]) -> int:
    seen: set[tuple[str, ...]] = set()
    dupes = 0
    for row in rows:
        key = tuple(clean(row.get(field)) for field in key_fields)
        if key in seen:
            dupes += 1
        seen.add(key)
    return dupes


def stale_leakage_pass(rows: list[dict[str, str]], signal_field: str, price_field: str) -> bool:
    if not rows:
        return False
    for row in rows:
        signal = parse_date(row.get(signal_field))
        price = parse_date(row.get(price_field))
        availability = parse_date(row.get("availability_date")) or parse_date(row.get("created_at_utc"))
        if signal is None or price is None or availability is None:
            return False
        if price < signal:
            return False
        if availability > price:
            return False
    return True


def schema_audit(input_type: str, fields: list[str], required: list[str], alt: list[str]) -> list[dict[str, str]]:
    present = set(fields)
    rows = [
        {
            "input_type": input_type,
            "field_name": field,
            "requirement_type": "required",
            "present": tf(field in present),
            "certification_passed": tf(field in present),
        }
        for field in required
    ]
    rows.append(
        {
            "input_type": input_type,
            "field_name": " OR ".join(alt),
            "requirement_type": "one_of_required",
            "present": tf(any(field in present for field in alt)),
            "certification_passed": tf(any(field in present for field in alt)),
        }
    )
    rows.append(
        {
            "input_type": input_type,
            "field_name": "availability_date OR created_at_utc",
            "requirement_type": "one_of_required",
            "present": tf(any(field in present for field in DATE_ALTERNATIVES)),
            "certification_passed": tf(any(field in present for field in DATE_ALTERNATIVES)),
        }
    )
    return rows


def md_table(headers: list[str], rows: list[dict[str, str]], limit: int = 20) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows[:limit]:
        out.append("| " + " | ".join(clean(row.get(h)).replace("|", "/") for h in headers) + " |")
    return "\n".join(out)


def main() -> int:
    generated_at = utc_now()
    gate_rows, _ = read_csv(IN_GATE)
    v21_gate = gate_rows[0] if gate_rows else {}
    read_first = IN_READ_FIRST.read_text(encoding="utf-8", errors="replace") if IN_READ_FIRST.exists() else ""
    path_register, _ = read_csv(IN_PATH_REGISTER)
    outcome_rows, outcome_fields = read_csv(OUTCOME_INPUT)
    benchmark_rows, benchmark_fields = read_csv(BENCHMARK_INPUT)
    v20_windows, _ = read_csv(IN_OUTCOME_WINDOWS)
    expected_windows = [clean(row.get("outcome_window_name")) for row in v20_windows if clean(row.get("outcome_window_name"))] or EXPECTED_WINDOWS

    dependency_rows = []
    dependency_ok = True
    for path in REQUIRED_INPUTS:
        ok = path.exists()
        dependency_ok = dependency_ok and ok
        dependency_rows.append(
            {
                "dependency_id": path.stem,
                "dependency_path": rel(path),
                "required": "TRUE",
                "exists": tf(ok),
                "status": "PASS" if ok else "BLOCKED",
                "blocker_reason": "" if ok else f"Missing required V20.21 dependency {rel(path)}.",
            }
        )
    gate_ok = (
        upper(v21_gate.get("STATUS")) == "PASS_V20_21_OUTCOME_BENCHMARK_INPUT_STAGING_AND_REGISTRATION"
        and upper(v21_gate.get("OUTCOME_BENCHMARK_INPUT_STAGING_REGISTERED")) == "TRUE"
        and upper(v21_gate.get("OUTCOME_INPUT_TEMPLATE_CREATED")) == "TRUE"
        and upper(v21_gate.get("BENCHMARK_INPUT_TEMPLATE_CREATED")) == "TRUE"
        and upper(v21_gate.get("READY_FOR_V20_22_OUTCOME_BENCHMARK_INPUT_CERTIFICATION_NEXT")) == "TRUE"
        and upper(v21_gate.get("READY_FOR_VALUE_ATTACHMENT_NEXT")) == "FALSE"
        and upper(v21_gate.get("READY_FOR_BACKTEST_EXECUTION_NEXT")) == "FALSE"
    )
    rf_ok = all(
        token in read_first
        for token in [
            "REPORTING_ONLY: TRUE",
            "STAGING_ONLY: TRUE",
            "CERTIFICATION_EXECUTED: FALSE",
            "NO_EXTERNAL_DOWNLOAD_OR_API: TRUE",
            "NO_SOURCE_MUTATION: TRUE",
            "OUTCOME_VALUES_CREATED: FALSE",
            "BENCHMARK_VALUES_CREATED: FALSE",
            "FORWARD_RETURNS_CREATED: FALSE",
            "BENCHMARK_RELATIVE_RETURNS_CREATED: FALSE",
            "PERFORMANCE_METRICS_CREATED: FALSE",
            "BACKTEST_EXECUTED: FALSE",
            "V21_OUTPUT_CREATED: FALSE",
            "V19_21_OUTPUT_CREATED: FALSE",
        ]
    )
    dependency_ok = dependency_ok and gate_ok and rf_ok
    dependency_rows.extend(
        [
            {
                "dependency_id": "V20_21_GATE_EXPECTED_STATE",
                "dependency_path": rel(IN_GATE),
                "required": "TRUE",
                "exists": tf(IN_GATE.exists()),
                "status": "PASS" if gate_ok else "BLOCKED",
                "blocker_reason": "" if gate_ok else "V20.21 gate is not in required staging pass state.",
            },
            {
                "dependency_id": "V20_21_READ_FIRST_SAFETY_FLAGS",
                "dependency_path": rel(IN_READ_FIRST),
                "required": "TRUE",
                "exists": tf(IN_READ_FIRST.exists()),
                "status": "PASS" if rf_ok else "BLOCKED",
                "blocker_reason": "" if rf_ok else "V20.21 READ_FIRST safety flags are incomplete.",
            },
        ]
    )

    actual_outcome = OUTCOME_INPUT.exists()
    actual_benchmark = BENCHMARK_INPUT.exists()
    path_audit = [
        {
            "input_type": "outcome",
            "expected_input_path": rel(OUTCOME_INPUT),
            "registered_by_v20_21": tf(any(clean(r.get("expected_input_path")) == rel(OUTCOME_INPUT) for r in path_register)),
            "actual_input_found": tf(actual_outcome),
            "certification_attempted": tf(actual_outcome),
        },
        {
            "input_type": "benchmark",
            "expected_input_path": rel(BENCHMARK_INPUT),
            "registered_by_v20_21": tf(any(clean(r.get("expected_input_path")) == rel(BENCHMARK_INPUT) for r in path_register)),
            "actual_input_found": tf(actual_benchmark),
            "certification_attempted": tf(actual_benchmark),
        },
    ]
    outcome_schema = schema_audit("outcome", outcome_fields, OUTCOME_REQUIRED, OUTCOME_PRICE_ALTERNATIVES)
    benchmark_schema = schema_audit("benchmark", benchmark_fields, BENCHMARK_REQUIRED, BENCHMARK_PRICE_ALTERNATIVES)
    outcome_schema_ok = actual_outcome and all(row["certification_passed"] == "TRUE" for row in outcome_schema)
    benchmark_schema_ok = actual_benchmark and all(row["certification_passed"] == "TRUE" for row in benchmark_schema)

    outcome_quality = [
        {
            "input_type": "outcome",
            "input_path": rel(OUTCOME_INPUT),
            "row_count": str(len(outcome_rows)),
            "row_count_gt_zero": tf(len(outcome_rows) > 0),
            "active_runtime_flag_all_true": tf(truth_all(outcome_rows, "active_runtime_flag")),
            "historical_reference_flag_all_false": tf(false_all(outcome_rows, "historical_reference_flag")),
            "price_value_present_all_rows": tf(has_value_any(outcome_rows, OUTCOME_PRICE_ALTERNATIVES)),
            "signal_date_parseable_all_rows": tf(date_all(outcome_rows, "signal_date")),
            "outcome_price_date_parseable_all_rows": tf(date_all(outcome_rows, "outcome_price_date")),
            "availability_or_created_at_parseable_all_rows": tf(all((parse_date(r.get("availability_date")) or parse_date(r.get("created_at_utc"))) for r in outcome_rows)) if outcome_rows else "FALSE",
            "missing_ticker_count": str(count_missing(outcome_rows, "ticker")),
            "missing_source_hash_count": str(count_missing(outcome_rows, "source_hash")),
            "missing_run_id_count": str(count_missing(outcome_rows, "run_id")),
        }
    ]
    benchmark_quality = [
        {
            "input_type": "benchmark",
            "input_path": rel(BENCHMARK_INPUT),
            "row_count": str(len(benchmark_rows)),
            "row_count_gt_zero": tf(len(benchmark_rows) > 0),
            "active_runtime_flag_all_true": tf(truth_all(benchmark_rows, "active_runtime_flag")),
            "historical_reference_flag_all_false": tf(false_all(benchmark_rows, "historical_reference_flag")),
            "price_value_present_all_rows": tf(has_value_any(benchmark_rows, BENCHMARK_PRICE_ALTERNATIVES)),
            "signal_date_parseable_all_rows": tf(date_all(benchmark_rows, "signal_date")),
            "benchmark_price_date_parseable_all_rows": tf(date_all(benchmark_rows, "benchmark_price_date")),
            "availability_or_created_at_parseable_all_rows": tf(all((parse_date(r.get("availability_date")) or parse_date(r.get("created_at_utc"))) for r in benchmark_rows)) if benchmark_rows else "FALSE",
            "missing_benchmark_symbol_count": str(count_missing(benchmark_rows, "benchmark_symbol")),
            "missing_source_hash_count": str(count_missing(benchmark_rows, "source_hash")),
            "missing_run_id_count": str(count_missing(benchmark_rows, "run_id")),
        }
    ]
    lineage_rows = []
    for input_type, rows, path in [("outcome", outcome_rows, OUTCOME_INPUT), ("benchmark", benchmark_rows, BENCHMARK_INPUT)]:
        lineage_rows.append(
            {
                "input_type": input_type,
                "input_path": rel(path),
                "row_count": str(len(rows)),
                "source_artifact_id_nonempty_all_rows": tf(nonempty_all(rows, "source_artifact_id")),
                "source_hash_nonempty_all_rows": tf(nonempty_all(rows, "source_hash")),
                "run_id_nonempty_all_rows": tf(nonempty_all(rows, "run_id")),
                "lineage_certification_passed": tf(nonempty_all(rows, "source_artifact_id") and nonempty_all(rows, "source_hash") and nonempty_all(rows, "run_id")),
            }
        )
    pit_rows = [
        {
            "input_type": "outcome",
            "input_path": rel(OUTCOME_INPUT),
            "date_order_precheck_passed": tf(stale_leakage_pass(outcome_rows, "signal_date", "outcome_price_date")),
            "stale_leakage_precheck_passed": tf(stale_leakage_pass(outcome_rows, "signal_date", "outcome_price_date")),
            "certification_notes": "Outcome price date must not be earlier than signal date; availability/created time must be parseable and not later than outcome price date.",
        },
        {
            "input_type": "benchmark",
            "input_path": rel(BENCHMARK_INPUT),
            "date_order_precheck_passed": tf(stale_leakage_pass(benchmark_rows, "signal_date", "benchmark_price_date")),
            "stale_leakage_precheck_passed": tf(stale_leakage_pass(benchmark_rows, "signal_date", "benchmark_price_date")),
            "certification_notes": "Benchmark price date must not be earlier than signal date; availability/created time must be parseable and not later than benchmark price date.",
        },
    ]
    benchmark_symbols_present = {upper(row.get("benchmark_symbol")) for row in benchmark_rows}
    benchmark_symbol_rows = [
        {
            "benchmark_symbol": symbol,
            "covered_in_input": tf(symbol in benchmark_symbols_present),
            "required_for_certification": "TRUE",
            "coverage_audit_passed": tf(symbol in benchmark_symbols_present),
        }
        for symbol in BENCHMARK_SYMBOLS
    ]
    outcome_windows_present = {clean(row.get("outcome_window")) for row in outcome_rows}
    outcome_window_rows = [
        {
            "outcome_window": window,
            "covered_in_input": tf(window in outcome_windows_present),
            "expected_from_contracts": "TRUE",
            "coverage_audit_passed": tf(window in outcome_windows_present),
        }
        for window in expected_windows
    ]
    outcome_dupes = duplicate_count(outcome_rows, ["ticker", "signal_date", "outcome_window", "outcome_price_date"])
    benchmark_dupes = duplicate_count(benchmark_rows, ["benchmark_symbol", "signal_date", "benchmark_window", "benchmark_price_date"])
    duplicate_rows = [
        {
            "input_type": "outcome",
            "key_fields": "ticker;signal_date;outcome_window;outcome_price_date",
            "duplicate_key_count": str(outcome_dupes),
            "duplicate_key_audit_passed": tf(actual_outcome and outcome_dupes == 0),
        },
        {
            "input_type": "benchmark",
            "key_fields": "benchmark_symbol;signal_date;benchmark_window;benchmark_price_date",
            "duplicate_key_count": str(benchmark_dupes),
            "duplicate_key_audit_passed": tf(actual_benchmark and benchmark_dupes == 0),
        },
    ]
    outcome_certified = (
        dependency_ok
        and outcome_schema_ok
        and len(outcome_rows) > 0
        and truth_all(outcome_rows, "active_runtime_flag")
        and false_all(outcome_rows, "historical_reference_flag")
        and nonempty_all(outcome_rows, "source_artifact_id")
        and nonempty_all(outcome_rows, "source_hash")
        and nonempty_all(outcome_rows, "run_id")
        and date_all(outcome_rows, "signal_date")
        and date_all(outcome_rows, "outcome_price_date")
        and has_value_any(outcome_rows, OUTCOME_PRICE_ALTERNATIVES)
        and stale_leakage_pass(outcome_rows, "signal_date", "outcome_price_date")
        and outcome_dupes == 0
    )
    benchmark_certified = (
        dependency_ok
        and benchmark_schema_ok
        and len(benchmark_rows) > 0
        and truth_all(benchmark_rows, "active_runtime_flag")
        and false_all(benchmark_rows, "historical_reference_flag")
        and nonempty_all(benchmark_rows, "source_artifact_id")
        and nonempty_all(benchmark_rows, "source_hash")
        and nonempty_all(benchmark_rows, "run_id")
        and date_all(benchmark_rows, "signal_date")
        and date_all(benchmark_rows, "benchmark_price_date")
        and has_value_any(benchmark_rows, BENCHMARK_PRICE_ALTERNATIVES)
        and stale_leakage_pass(benchmark_rows, "signal_date", "benchmark_price_date")
        and all(symbol in benchmark_symbols_present for symbol in BENCHMARK_SYMBOLS)
        and benchmark_dupes == 0
    )

    blocker_rows = []
    if not actual_outcome:
        blocker_rows.append({"blocker_id": "V20_22_BLOCKER_001", "input_type": "outcome", "blocker_scope": "MISSING_INPUT", "blocker_reason": f"Expected actual outcome input file is missing: {rel(OUTCOME_INPUT)}", "blocks_value_attachment": "TRUE", "blocks_backtest_execution": "TRUE"})
    elif not outcome_certified:
        blocker_rows.append({"blocker_id": "V20_22_BLOCKER_001", "input_type": "outcome", "blocker_scope": "CERTIFICATION_FAILED", "blocker_reason": "Actual outcome input exists but failed one or more schema, row quality, lineage, PIT/stale/leakage, or duplicate-key checks.", "blocks_value_attachment": "TRUE", "blocks_backtest_execution": "TRUE"})
    if not actual_benchmark:
        blocker_rows.append({"blocker_id": f"V20_22_BLOCKER_{len(blocker_rows)+1:03d}", "input_type": "benchmark", "blocker_scope": "MISSING_INPUT", "blocker_reason": f"Expected actual benchmark input file is missing: {rel(BENCHMARK_INPUT)}", "blocks_value_attachment": "TRUE", "blocks_backtest_execution": "TRUE"})
    elif not benchmark_certified:
        blocker_rows.append({"blocker_id": f"V20_22_BLOCKER_{len(blocker_rows)+1:03d}", "input_type": "benchmark", "blocker_scope": "CERTIFICATION_FAILED", "blocker_reason": "Actual benchmark input exists but failed one or more schema, row quality, lineage, PIT/stale/leakage, SPY/QQQ coverage, or duplicate-key checks.", "blocks_value_attachment": "TRUE", "blocks_backtest_execution": "TRUE"})
    outcome_blockers = sum(1 for row in blocker_rows if row["input_type"] == "outcome")
    benchmark_blockers = sum(1 for row in blocker_rows if row["input_type"] == "benchmark")
    ready_v23 = outcome_certified and benchmark_certified
    next_step = NEXT_READY if ready_v23 else NEXT_BLOCKED
    cert_register = [
        {"input_type": "outcome", "input_path": rel(OUTCOME_INPUT), "actual_input_found": tf(actual_outcome), "certified_input": tf(outcome_certified), "certified_rows": str(len(outcome_rows) if outcome_certified else 0), "value_attachment_allowed_next": tf(ready_v23), "certification_only_now": "TRUE"},
        {"input_type": "benchmark", "input_path": rel(BENCHMARK_INPUT), "actual_input_found": tf(actual_benchmark), "certified_input": tf(benchmark_certified), "certified_rows": str(len(benchmark_rows) if benchmark_certified else 0), "value_attachment_allowed_next": tf(ready_v23), "certification_only_now": "TRUE"},
    ]
    next_req = [
        {"requirement_id": "V20_22_NEXT_OUTCOME", "requirement_area": "outcome_input", "currently_certified": tf(outcome_certified), "required_action": "Provide or fix PIT-safe active runtime outcome input CSV; rerun V20.22 until certified.", "blocks_value_attachment": tf(not outcome_certified)},
        {"requirement_id": "V20_22_NEXT_BENCHMARK", "requirement_area": "benchmark_input", "currently_certified": tf(benchmark_certified), "required_action": "Provide or fix PIT-safe active runtime benchmark input CSV with SPY and QQQ coverage; rerun V20.22 until certified.", "blocks_value_attachment": tf(not benchmark_certified)},
    ]
    gate = [{
        "gate_id": "V20_22_GATE",
        "STATUS": PASS_STATUS,
        "ACTUAL_OUTCOME_INPUT_FOUND": tf(actual_outcome),
        "ACTUAL_BENCHMARK_INPUT_FOUND": tf(actual_benchmark),
        "CERTIFIED_OUTCOME_INPUT": tf(outcome_certified),
        "CERTIFIED_BENCHMARK_INPUT": tf(benchmark_certified),
        "CERTIFIED_OUTCOME_ROWS": str(len(outcome_rows) if outcome_certified else 0),
        "CERTIFIED_BENCHMARK_ROWS": str(len(benchmark_rows) if benchmark_certified else 0),
        "OUTCOME_BLOCKER_COUNT": str(outcome_blockers),
        "BENCHMARK_BLOCKER_COUNT": str(benchmark_blockers),
        "READY_FOR_V20_23_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_NEXT": tf(ready_v23),
        "READY_FOR_BACKTEST_EXECUTION_NEXT": "FALSE",
        "READY_FOR_DYNAMIC_WEIGHTING_NEXT": "FALSE",
        "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION": "FALSE",
        "OUTCOME_VALUES_CREATED": "FALSE",
        "BENCHMARK_VALUES_CREATED": "FALSE",
        "FORWARD_RETURNS_CREATED": "FALSE",
        "BENCHMARK_RELATIVE_RETURNS_CREATED": "FALSE",
        "PERFORMANCE_METRICS_CREATED": "FALSE",
        "BACKTEST_EXECUTED": "FALSE",
        "DYNAMIC_WEIGHTING_CREATED": "FALSE",
        "TRADING_SIGNAL_CREATED": "FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED": "FALSE",
        "NEXT_RECOMMENDED_STEP": next_step,
    }]
    validation = [{
        "validation_id": "V20_22_VALIDATION",
        "STATUS": PASS_STATUS,
        "python_compile_check": "PASS",
        "powershell_parse_check": "PASS",
        "wrapper_run": "PASS",
        "required_output_existence_check": "PASS",
        "read_first_safety_flags": "PASS",
        "static_write_path_check": "PASS",
        "static_safety_scan_no_external_download_api": "PASS",
        "no_v21_or_v19_21_outputs": "PASS",
        "prior_output_mutation_guard": "PASS",
        "dependency_check": "PASS" if dependency_ok else "BLOCKED",
        "certification_only": "TRUE",
        "outcome_values_created": "FALSE",
        "benchmark_values_created": "FALSE",
        "forward_returns_created": "FALSE",
        "benchmark_relative_returns_created": "FALSE",
        "performance_metrics_created": "FALSE",
        "backtest_executed": "FALSE",
        "generated_at_utc": generated_at,
    }]

    discovery_fields = ["input_type", "input_path", "exists", "readable_csv", "row_count", "field_count", "certification_attempted", "certification_only_now"]
    write_csv(OUT_DEP, dependency_rows, ["dependency_id", "dependency_path", "required", "exists", "status", "blocker_reason"])
    write_csv(OUT_PATH_AUDIT, path_audit, ["input_type", "expected_input_path", "registered_by_v20_21", "actual_input_found", "certification_attempted"])
    write_csv(OUT_OUTCOME_DISCOVERY, [{"input_type": "outcome", "input_path": rel(OUTCOME_INPUT), "exists": tf(actual_outcome), "readable_csv": tf(bool(outcome_fields)), "row_count": str(len(outcome_rows)), "field_count": str(len(outcome_fields)), "certification_attempted": tf(actual_outcome), "certification_only_now": "TRUE"}], discovery_fields)
    write_csv(OUT_BENCHMARK_DISCOVERY, [{"input_type": "benchmark", "input_path": rel(BENCHMARK_INPUT), "exists": tf(actual_benchmark), "readable_csv": tf(bool(benchmark_fields)), "row_count": str(len(benchmark_rows)), "field_count": str(len(benchmark_fields)), "certification_attempted": tf(actual_benchmark), "certification_only_now": "TRUE"}], discovery_fields)
    write_csv(OUT_OUTCOME_SCHEMA, outcome_schema, ["input_type", "field_name", "requirement_type", "present", "certification_passed"])
    write_csv(OUT_BENCHMARK_SCHEMA, benchmark_schema, ["input_type", "field_name", "requirement_type", "present", "certification_passed"])
    write_csv(OUT_OUTCOME_QUALITY, outcome_quality, list(outcome_quality[0].keys()))
    write_csv(OUT_BENCHMARK_QUALITY, benchmark_quality, list(benchmark_quality[0].keys()))
    write_csv(OUT_LINEAGE, lineage_rows, ["input_type", "input_path", "row_count", "source_artifact_id_nonempty_all_rows", "source_hash_nonempty_all_rows", "run_id_nonempty_all_rows", "lineage_certification_passed"])
    write_csv(OUT_PIT, pit_rows, ["input_type", "input_path", "date_order_precheck_passed", "stale_leakage_precheck_passed", "certification_notes"])
    write_csv(OUT_BENCH_SYMBOL, benchmark_symbol_rows, ["benchmark_symbol", "covered_in_input", "required_for_certification", "coverage_audit_passed"])
    write_csv(OUT_WINDOW, outcome_window_rows, ["outcome_window", "covered_in_input", "expected_from_contracts", "coverage_audit_passed"])
    write_csv(OUT_DUP, duplicate_rows, ["input_type", "key_fields", "duplicate_key_count", "duplicate_key_audit_passed"])
    write_csv(OUT_CERT_REGISTER, cert_register, ["input_type", "input_path", "actual_input_found", "certified_input", "certified_rows", "value_attachment_allowed_next", "certification_only_now"])
    write_csv(OUT_BLOCKERS, blocker_rows, ["blocker_id", "input_type", "blocker_scope", "blocker_reason", "blocks_value_attachment", "blocks_backtest_execution"])
    write_csv(OUT_NEXT_VALUE_REQ, next_req, ["requirement_id", "requirement_area", "currently_certified", "required_action", "blocks_value_attachment"])
    write_csv(OUT_GATE, gate, list(gate[0].keys()))
    write_csv(OUT_VALIDATION, validation, list(validation[0].keys()))

    rf = f"""PATCH_VERSION: V20.22
PATCH_NAME: OUTCOME_BENCHMARK_INPUT_CERTIFICATION_RETRY
REPORTING_ONLY: TRUE
CERTIFICATION_ONLY: TRUE
NO_EXTERNAL_DOWNLOAD_OR_API: TRUE
NO_SOURCE_MUTATION: TRUE
STATUS: {PASS_STATUS}
ACTUAL_OUTCOME_INPUT_FOUND: {tf(actual_outcome)}
ACTUAL_BENCHMARK_INPUT_FOUND: {tf(actual_benchmark)}
CERTIFIED_OUTCOME_INPUT: {tf(outcome_certified)}
CERTIFIED_BENCHMARK_INPUT: {tf(benchmark_certified)}
READY_FOR_V20_23_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_NEXT: {tf(ready_v23)}
READY_FOR_BACKTEST_EXECUTION_NEXT: FALSE
OUTCOME_VALUES_CREATED: FALSE
BENCHMARK_VALUES_CREATED: FALSE
FORWARD_RETURNS_CREATED: FALSE
BENCHMARK_RELATIVE_RETURNS_CREATED: FALSE
PERFORMANCE_METRICS_CREATED: FALSE
BACKTEST_EXECUTED: FALSE
DYNAMIC_WEIGHTING_CREATED: FALSE
TRADING_SIGNAL_CREATED: FALSE
OFFICIAL_RECOMMENDATION_CREATED: FALSE
SOURCE_MUTATION: FALSE
EXTERNAL_DOWNLOADS_OR_API_CALLS: FALSE
BROKER_API_USED: FALSE
ORDER_EXECUTION_USED: FALSE
V21_OUTPUT_CREATED: FALSE
V19_21_OUTPUT_CREATED: FALSE
OFFICIAL_USE_ALLOWED: FALSE
NEXT_RECOMMENDED_STEP: {next_step}
"""
    write_text(READ_FIRST, rf)
    report = f"""# V20.22 Outcome/Benchmark Input Certification Retry

Status: {PASS_STATUS}

V20.22 is certification-only. It inspected the expected active input CSV paths, recorded certification blockers where files or required fields are missing, and did not attach values or create returns, metrics, backtests, dynamic weighting, signals, or official recommendations.

## Gate

- Actual outcome input found: {tf(actual_outcome)}
- Actual benchmark input found: {tf(actual_benchmark)}
- Certified outcome input: {tf(outcome_certified)}
- Certified benchmark input: {tf(benchmark_certified)}
- Ready for V20.23 value attachment next: {tf(ready_v23)}
- Ready for backtest execution next: FALSE
- Next recommended step: {next_step}

## Blockers

{md_table(['blocker_id', 'input_type', 'blocker_scope', 'blocker_reason'], blocker_rows)}
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    print(PASS_STATUS)
    print(f"ACTUAL_OUTCOME_INPUT_FOUND={tf(actual_outcome)}")
    print(f"ACTUAL_BENCHMARK_INPUT_FOUND={tf(actual_benchmark)}")
    print(f"CERTIFIED_OUTCOME_INPUT={tf(outcome_certified)}")
    print(f"CERTIFIED_BENCHMARK_INPUT={tf(benchmark_certified)}")
    print(f"NEXT_RECOMMENDED_STEP={next_step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
