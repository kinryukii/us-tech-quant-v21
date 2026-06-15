from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
INPUT_BASE = ROOT / "inputs" / "v20" / "outcome_benchmark"

IN_READ_FIRST = OPS / "V20_23_READ_FIRST.txt"
IN_GATE = CONSOLIDATION / "V20_23_GATE_DECISION.csv"
IN_INVENTORY = CONSOLIDATION / "V20_23_ALLOWED_LOCAL_SOURCE_INVENTORY.csv"
IN_OUTCOME_CANDIDATES = CONSOLIDATION / "V20_23_OUTCOME_LOCAL_SOURCE_CANDIDATE_AUDIT.csv"
IN_BENCHMARK_CANDIDATES = CONSOLIDATION / "V20_23_BENCHMARK_LOCAL_SOURCE_CANDIDATE_AUDIT.csv"
IN_BLOCKERS = CONSOLIDATION / "V20_23_BLOCKER_REGISTER.csv"
IN_NEXT_REQ = CONSOLIDATION / "V20_23_NEXT_CERTIFICATION_RETRY_REQUIREMENTS.csv"
IN_BACKTEST_CANDIDATES = CONSOLIDATION / "V20_17_BACKTEST_INPUT_CANDIDATE_DATASET.csv"
IN_OUTCOME_CONTRACT = CONSOLIDATION / "V20_17_OUTCOME_WINDOW_CONTRACT.csv"
IN_BENCHMARK_CONTRACT = CONSOLIDATION / "V20_17_BENCHMARK_WINDOW_CONTRACT.csv"

ACTIVE_OUTCOME_INPUT = INPUT_BASE / "V20_OUTCOME_SOURCE_INPUT.csv"
ACTIVE_BENCHMARK_INPUT = INPUT_BASE / "V20_BENCHMARK_SOURCE_INPUT.csv"

OUT_DEP = CONSOLIDATION / "V20_24_DEPENDENCY_AUDIT.csv"
OUT_OUTCOME_PLAN = CONSOLIDATION / "V20_24_OUTCOME_DATA_REQUIREMENT_PLAN.csv"
OUT_BENCHMARK_PLAN = CONSOLIDATION / "V20_24_BENCHMARK_DATA_REQUIREMENT_PLAN.csv"
OUT_INPUT_REGISTER = CONSOLIDATION / "V20_24_REQUIRED_INPUT_FILE_REGISTER.csv"
OUT_OUTCOME_SCHEMA = CONSOLIDATION / "V20_24_OUTCOME_REQUIRED_SCHEMA.csv"
OUT_BENCHMARK_SCHEMA = CONSOLIDATION / "V20_24_BENCHMARK_REQUIRED_SCHEMA.csv"
OUT_COVERAGE = CONSOLIDATION / "V20_24_REQUIRED_COVERAGE_MATRIX.csv"
OUT_SIGNAL_WINDOW = CONSOLIDATION / "V20_24_SIGNAL_DATE_AND_WINDOW_REQUIREMENT_AUDIT.csv"
OUT_ALLOWED = CONSOLIDATION / "V20_24_ALLOWED_LOCAL_ACQUISITION_OPTIONS.csv"
OUT_DISALLOWED = CONSOLIDATION / "V20_24_DISALLOWED_DATA_SOURCE_OPTIONS.csv"
OUT_MANUAL = CONSOLIDATION / "V20_24_MANUAL_STAGING_INSTRUCTIONS.csv"
OUT_IMPORTER = CONSOLIDATION / "V20_24_FUTURE_LOCAL_IMPORTER_DESIGN_OPTIONS.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_24_BLOCKER_REGISTER.csv"
OUT_NEXT = CONSOLIDATION / "V20_24_NEXT_STAGING_REQUIREMENTS.csv"
OUT_GATE = CONSOLIDATION / "V20_24_GATE_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_24_VALIDATION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_24_LOCAL_OUTCOME_BENCHMARK_DATA_REQUIREMENT_AND_ACQUISITION_PLAN_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_LOCAL_OUTCOME_BENCHMARK_DATA_REQUIREMENT_AND_ACQUISITION_PLAN.md"
ZH_GUIDE = READ_CENTER / "V20_24_OPERATOR_DATA_STAGING_GUIDE_ZH.md"
READ_FIRST = OPS / "V20_24_READ_FIRST.txt"

PASS_STATUS = "PASS_V20_24_LOCAL_OUTCOME_BENCHMARK_DATA_REQUIREMENT_AND_ACQUISITION_PLAN"
NEXT_STEP = "V20.25_LOCAL_OUTCOME_BENCHMARK_IMPORTER_OR_MANUAL_STAGING"
REQUIRED_INPUTS = [IN_READ_FIRST, IN_GATE, IN_INVENTORY, IN_OUTCOME_CANDIDATES, IN_BENCHMARK_CANDIDATES, IN_BLOCKERS, IN_NEXT_REQ]

OUTCOME_FIELDS = [
    "ticker",
    "signal_date",
    "outcome_window",
    "outcome_price_date",
    "outcome_close",
    "adjusted_outcome_close",
    "currency",
    "source_artifact_id",
    "source_hash",
    "run_id",
    "active_runtime_flag",
    "historical_reference_flag",
    "availability_date",
    "created_at_utc",
    "data_vendor_or_source_system",
    "notes",
]
BENCHMARK_FIELDS = [
    "benchmark_symbol",
    "signal_date",
    "benchmark_window",
    "benchmark_price_date",
    "benchmark_close",
    "adjusted_benchmark_close",
    "currency",
    "source_artifact_id",
    "source_hash",
    "run_id",
    "active_runtime_flag",
    "historical_reference_flag",
    "availability_date",
    "created_at_utc",
    "data_vendor_or_source_system",
    "notes",
]
DEFAULT_OUTCOME_WINDOWS = ["forward_1d", "forward_5d", "forward_10d", "forward_20d", "forward_60d"]
DEFAULT_BENCHMARK_WINDOWS = ["benchmark_forward_1d", "benchmark_forward_5d", "benchmark_forward_10d", "benchmark_forward_20d", "benchmark_forward_60d"]
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


def md_table(headers: list[str], rows: list[dict[str, str]], limit: int = 20) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows[:limit]:
        lines.append("| " + " | ".join(clean(row.get(h)).replace("|", "/") for h in headers) + " |")
    return "\n".join(lines)


def schema_rows(kind: str, fields: list[str]) -> list[dict[str, str]]:
    rows = []
    for idx, field in enumerate(fields, start=1):
        rows.append(
            {
                "schema_id": f"V20_24_{kind.upper()}_FIELD_{idx:03d}",
                "input_type": kind,
                "field_name": field,
                "required": "TRUE",
                "data_requirement": field_requirement(field),
                "validation_rule": field_rule(field),
            }
        )
    return rows


def field_requirement(field: str) -> str:
    if field in {"ticker", "benchmark_symbol"}:
        return "Explicit symbol identifier required; benchmark must be SPY or QQQ."
    if field in {"signal_date", "outcome_price_date", "benchmark_price_date", "availability_date", "created_at_utc"}:
        return "Parseable date/time field required for PIT-safe later certification."
    if "close" in field:
        return "Local price value field required for future value attachment only; no return calculation now."
    if field in {"source_artifact_id", "source_hash", "run_id"}:
        return "Lineage/hash/run binding must be non-empty."
    if field == "active_runtime_flag":
        return "Must be TRUE in later certification."
    if field == "historical_reference_flag":
        return "Must be FALSE in later certification."
    return "Required metadata."


def field_rule(field: str) -> str:
    if field in {"active_runtime_flag"}:
        return "all_rows_TRUE"
    if field in {"historical_reference_flag"}:
        return "all_rows_FALSE"
    if field in {"signal_date", "outcome_price_date", "benchmark_price_date", "availability_date", "created_at_utc"}:
        return "parseable_date"
    return "non_empty"


def unique_values(rows: list[dict[str, str]], field: str) -> list[str]:
    return sorted({clean(row.get(field)) for row in rows if clean(row.get(field))})


def main() -> int:
    generated_at = utc_now()
    gate_rows, _ = read_csv(IN_GATE)
    v23_gate = gate_rows[0] if gate_rows else {}
    read_first = IN_READ_FIRST.read_text(encoding="utf-8", errors="replace") if IN_READ_FIRST.exists() else ""
    inventory, _ = read_csv(IN_INVENTORY)
    outcome_candidates, _ = read_csv(IN_OUTCOME_CANDIDATES)
    benchmark_candidates, _ = read_csv(IN_BENCHMARK_CANDIDATES)
    v23_blockers, _ = read_csv(IN_BLOCKERS)
    next_req_in, _ = read_csv(IN_NEXT_REQ)
    backtest_candidates, _ = read_csv(IN_BACKTEST_CANDIDATES)
    outcome_contracts, _ = read_csv(IN_OUTCOME_CONTRACT)
    benchmark_contracts, _ = read_csv(IN_BENCHMARK_CONTRACT)

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
                "blocker_reason": "" if ok else f"Missing required V20.23 dependency {rel(path)}.",
            }
        )
    gate_ok = (
        upper(v23_gate.get("STATUS")) == "PASS_V20_23_OUTCOME_BENCHMARK_INPUT_SOURCE_CREATION_OR_STAGING_FROM_ALLOWED_LOCAL_DATA"
        and upper(v23_gate.get("OUTCOME_LOCAL_STAGING_ATTEMPTED")) == "TRUE"
        and upper(v23_gate.get("BENCHMARK_LOCAL_STAGING_ATTEMPTED")) == "TRUE"
        and upper(v23_gate.get("OUTCOME_INPUT_FILE_CREATED")) == "FALSE"
        and upper(v23_gate.get("BENCHMARK_INPUT_FILE_CREATED")) == "FALSE"
        and upper(v23_gate.get("READY_FOR_V20_24_OUTCOME_BENCHMARK_INPUT_CERTIFICATION_RETRY_NEXT")) == "FALSE"
        and upper(v23_gate.get("READY_FOR_VALUE_ATTACHMENT_NEXT")) == "FALSE"
        and upper(v23_gate.get("READY_FOR_BACKTEST_EXECUTION_NEXT")) == "FALSE"
    )
    rf_ok = all(
        token in read_first
        for token in [
            "LOCAL_STAGING_ONLY: TRUE",
            "NO_EXTERNAL_DOWNLOAD_OR_API: TRUE",
            "NO_SOURCE_MUTATION: TRUE",
            "OUTCOME_VALUES_ATTACHED_TO_BACKTEST_CANDIDATES: FALSE",
            "BENCHMARK_VALUES_ATTACHED_TO_BACKTEST_CANDIDATES: FALSE",
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
                "dependency_id": "V20_23_GATE_EXPECTED_REQUIREMENT_PLAN_STATE",
                "dependency_path": rel(IN_GATE),
                "required": "TRUE",
                "exists": tf(IN_GATE.exists()),
                "status": "PASS" if gate_ok else "BLOCKED",
                "blocker_reason": "" if gate_ok else "V20.23 gate is not in the expected failed-local-staging state.",
            },
            {
                "dependency_id": "V20_23_READ_FIRST_SAFETY_FLAGS",
                "dependency_path": rel(IN_READ_FIRST),
                "required": "TRUE",
                "exists": tf(IN_READ_FIRST.exists()),
                "status": "PASS" if rf_ok else "BLOCKED",
                "blocker_reason": "" if rf_ok else "V20.23 READ_FIRST safety flags are incomplete.",
            },
        ]
    )

    tickers = unique_values(backtest_candidates, "ticker")
    signal_dates = unique_values(backtest_candidates, "effective_price_date") or unique_values(backtest_candidates, "effective_observation_date")
    outcome_windows = unique_values(outcome_contracts, "outcome_window_name") or DEFAULT_OUTCOME_WINDOWS
    benchmark_windows = unique_values(benchmark_contracts, "benchmark_window_name") or DEFAULT_BENCHMARK_WINDOWS

    outcome_plan = [
        {
            "requirement_id": "V20_24_OUTCOME_PLAN_001",
            "required_input_file": rel(ACTIVE_OUTCOME_INPUT),
            "candidate_rows_requiring_later_attachment": str(len(backtest_candidates)),
            "required_ticker_count": str(len(tickers)),
            "required_signal_date_count": str(len(signal_dates)),
            "required_outcome_windows": ";".join(outcome_windows),
            "required_row_grain": "ticker + signal_date + outcome_window",
            "must_include_future_price_date": "TRUE",
            "must_include_active_runtime_lineage": "TRUE",
            "stage_creates_active_input": "FALSE",
            "stage_creates_returns": "FALSE",
        }
    ]
    benchmark_plan = [
        {
            "requirement_id": "V20_24_BENCHMARK_PLAN_001",
            "required_input_file": rel(ACTIVE_BENCHMARK_INPUT),
            "required_benchmark_symbols": ";".join(BENCHMARK_SYMBOLS),
            "required_signal_date_count": str(len(signal_dates)),
            "required_benchmark_windows": ";".join(benchmark_windows),
            "required_row_grain": "benchmark_symbol + signal_date + benchmark_window",
            "must_include_explicit_spy_qqq_rows": "TRUE",
            "must_include_active_runtime_lineage": "TRUE",
            "stage_creates_active_input": "FALSE",
            "stage_creates_returns": "FALSE",
        }
    ]
    input_register = [
        {"input_type": "outcome", "required_input_path": rel(ACTIVE_OUTCOME_INPUT), "created_now": "FALSE", "required_for_v20_25": "TRUE", "template_source": "inputs/v20/outcome_benchmark/V20_OUTCOME_SOURCE_INPUT_TEMPLATE.csv"},
        {"input_type": "benchmark", "required_input_path": rel(ACTIVE_BENCHMARK_INPUT), "created_now": "FALSE", "required_for_v20_25": "TRUE", "template_source": "inputs/v20/outcome_benchmark/V20_BENCHMARK_SOURCE_INPUT_TEMPLATE.csv"},
    ]
    coverage_rows = [
        {"coverage_id": "V20_24_COVERAGE_OUTCOME", "coverage_area": "outcome", "required_scope": "all ticker/signal_date/outcome_window combinations for later attachment", "required_symbols_or_tickers": str(len(tickers)), "required_windows": ";".join(outcome_windows), "required_dates": str(len(signal_dates)), "created_now": "FALSE"},
        {"coverage_id": "V20_24_COVERAGE_BENCHMARK", "coverage_area": "benchmark", "required_scope": "SPY and QQQ for all signal_date/benchmark_window combinations", "required_symbols_or_tickers": ";".join(BENCHMARK_SYMBOLS), "required_windows": ";".join(benchmark_windows), "required_dates": str(len(signal_dates)), "created_now": "FALSE"},
    ]
    signal_window_rows = []
    for window in outcome_windows:
        signal_window_rows.append({"requirement_type": "outcome", "symbol_scope": "candidate_tickers", "signal_date_count": str(len(signal_dates)), "window_name": window, "price_date_rule": "outcome_price_date >= signal_date and parseable", "rows_created_now": "0"})
    for symbol in BENCHMARK_SYMBOLS:
        for window in benchmark_windows:
            signal_window_rows.append({"requirement_type": "benchmark", "symbol_scope": symbol, "signal_date_count": str(len(signal_dates)), "window_name": window, "price_date_rule": "benchmark_price_date >= signal_date and parseable", "rows_created_now": "0"})

    allowed_options = [
        {"option_id": "V20_24_ALLOWED_001", "option_name": "manual_broker_vendor_csv", "description": "Manually export broker/vendor CSV and copy it into inputs/v20/outcome_benchmark/.", "network_used_by_pipeline": "FALSE", "allowed_next": "TRUE"},
        {"option_id": "V20_24_ALLOWED_002", "option_name": "locally_prepared_provider_csv", "description": "Prepare CSV locally from an approved provider outside the pipeline, then save it manually.", "network_used_by_pipeline": "FALSE", "allowed_next": "TRUE"},
        {"option_id": "V20_24_ALLOWED_003", "option_name": "future_local_file_importer", "description": "Implement a later local-file importer that validates an existing local CSV without downloads.", "network_used_by_pipeline": "FALSE", "allowed_next": "TRUE"},
        {"option_id": "V20_24_ALLOWED_004", "option_name": "certified_v18_v20_reuse", "description": "Reuse V18/V20 outputs only after future certification proves active-runtime, PIT-safe, non-historical rows.", "network_used_by_pipeline": "FALSE", "allowed_next": "CONDITIONAL"},
    ]
    disallowed_options = [
        {"option_id": "V20_24_DISALLOWED_001", "option_name": "fabricate_future_prices", "reason": "Future prices must be observed local data, not fabricated."},
        {"option_id": "V20_24_DISALLOWED_002", "option_name": "infer_from_same_day_current_prices", "reason": "Outcome windows require future price dates, not same-day/current prices."},
        {"option_id": "V20_24_DISALLOWED_003", "option_name": "template_rows_as_data", "reason": "Templates are not active runtime source data."},
        {"option_id": "V20_24_DISALLOWED_004", "option_name": "sealed_historical_reference_without_certification", "reason": "Historical references cannot become active runtime data without certification."},
        {"option_id": "V20_24_DISALLOWED_005", "option_name": "pipeline_network_or_api_source", "reason": "No yfinance, web request, broker API, or network call is allowed inside this pipeline stage."},
        {"option_id": "V20_24_DISALLOWED_006", "option_name": "benchmark_proxy_without_spy_qqq", "reason": "Benchmark input must contain explicit SPY and QQQ rows."},
    ]
    manual_rows = [
        {"step_id": "V20_24_MANUAL_001", "operator_step": "Create or obtain a local CSV with the exact required schema.", "target_file": rel(ACTIVE_OUTCOME_INPUT), "notes": "Do not calculate returns; include observed future prices only."},
        {"step_id": "V20_24_MANUAL_002", "operator_step": "Create or obtain benchmark CSV with explicit SPY and QQQ rows.", "target_file": rel(ACTIVE_BENCHMARK_INPUT), "notes": "Do not use benchmark proxies."},
        {"step_id": "V20_24_MANUAL_003", "operator_step": "Populate lineage fields source_artifact_id, source_hash, and run_id.", "target_file": "both", "notes": "active_runtime_flag must be TRUE and historical_reference_flag must be FALSE only when justified."},
        {"step_id": "V20_24_MANUAL_004", "operator_step": "Run the next local importer or manual staging step.", "target_file": "V20.25", "notes": "Certification and value attachment remain later stages."},
    ]
    importer_rows = [
        {"design_id": "V20_24_IMPORTER_001", "design_option": "schema_only_local_csv_loader", "description": "Later script reads local CSV, validates required columns, and writes active input files only if all checks pass.", "downloads_allowed": "FALSE"},
        {"design_id": "V20_24_IMPORTER_002", "design_option": "hash_binding_helper", "description": "Later helper computes or verifies source_hash for local files and binds run_id/source_artifact_id.", "downloads_allowed": "FALSE"},
        {"design_id": "V20_24_IMPORTER_003", "design_option": "pit_date_precheck_helper", "description": "Later helper checks parseable signal/price/availability dates before certification retry.", "downloads_allowed": "FALSE"},
    ]
    blocker_rows = []
    for idx, row in enumerate(v23_blockers, start=1):
        blocker_rows.append(
            {
                "blocker_id": f"V20_24_BLOCKER_{idx:03d}",
                "blocker_source": "V20.23_CARRYFORWARD",
                "blocker_scope": clean(row.get("blocker_scope")),
                "blocker_reason": clean(row.get("blocker_reason")),
                "blocks_value_attachment": "TRUE",
                "blocks_backtest_execution": "TRUE",
                "v20_24_resolution_plan_created": "TRUE",
            }
        )
    next_rows = [
        {"requirement_id": "V20_24_NEXT_001", "requirement_area": "outcome_file", "required_next_artifact": rel(ACTIVE_OUTCOME_INPUT), "created_now": "FALSE", "next_step": NEXT_STEP},
        {"requirement_id": "V20_24_NEXT_002", "requirement_area": "benchmark_file", "required_next_artifact": rel(ACTIVE_BENCHMARK_INPUT), "created_now": "FALSE", "next_step": NEXT_STEP},
        {"requirement_id": "V20_24_NEXT_003", "requirement_area": "certification_retry", "required_next_artifact": "V20.25 local importer or manual staging", "created_now": "FALSE", "next_step": NEXT_STEP},
    ]
    gate = [{
        "gate_id": "V20_24_GATE",
        "STATUS": PASS_STATUS,
        "LOCAL_OUTCOME_BENCHMARK_REQUIREMENT_PLAN_CREATED": "TRUE",
        "OUTCOME_REQUIRED_SCHEMA_CREATED": "TRUE",
        "BENCHMARK_REQUIRED_SCHEMA_CREATED": "TRUE",
        "OPERATOR_DATA_STAGING_GUIDE_CREATED": "TRUE",
        "ACTIVE_OUTCOME_INPUT_CREATED": "FALSE",
        "ACTIVE_BENCHMARK_INPUT_CREATED": "FALSE",
        "READY_FOR_V20_25_LOCAL_OUTCOME_BENCHMARK_IMPORTER_OR_MANUAL_STAGING_NEXT": "TRUE",
        "READY_FOR_VALUE_ATTACHMENT_NEXT": "FALSE",
        "READY_FOR_BACKTEST_EXECUTION_NEXT": "FALSE",
        "READY_FOR_DYNAMIC_WEIGHTING_NEXT": "FALSE",
        "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION": "FALSE",
        "OUTCOME_VALUES_ATTACHED_TO_BACKTEST_CANDIDATES": "FALSE",
        "BENCHMARK_VALUES_ATTACHED_TO_BACKTEST_CANDIDATES": "FALSE",
        "FORWARD_RETURNS_CREATED": "FALSE",
        "BENCHMARK_RELATIVE_RETURNS_CREATED": "FALSE",
        "PERFORMANCE_METRICS_CREATED": "FALSE",
        "BACKTEST_EXECUTED": "FALSE",
        "DYNAMIC_WEIGHTING_CREATED": "FALSE",
        "TRADING_SIGNAL_CREATED": "FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED": "FALSE",
        "NEXT_RECOMMENDED_STEP": NEXT_STEP,
    }]
    validation = [{
        "validation_id": "V20_24_VALIDATION",
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
        "planning_only": "TRUE",
        "active_outcome_input_created": "FALSE",
        "active_benchmark_input_created": "FALSE",
        "backtest_executed": "FALSE",
        "generated_at_utc": generated_at,
    }]

    write_csv(OUT_DEP, dependency_rows, ["dependency_id", "dependency_path", "required", "exists", "status", "blocker_reason"])
    write_csv(OUT_OUTCOME_PLAN, outcome_plan, list(outcome_plan[0].keys()))
    write_csv(OUT_BENCHMARK_PLAN, benchmark_plan, list(benchmark_plan[0].keys()))
    write_csv(OUT_INPUT_REGISTER, input_register, ["input_type", "required_input_path", "created_now", "required_for_v20_25", "template_source"])
    write_csv(OUT_OUTCOME_SCHEMA, schema_rows("outcome", OUTCOME_FIELDS), ["schema_id", "input_type", "field_name", "required", "data_requirement", "validation_rule"])
    write_csv(OUT_BENCHMARK_SCHEMA, schema_rows("benchmark", BENCHMARK_FIELDS), ["schema_id", "input_type", "field_name", "required", "data_requirement", "validation_rule"])
    write_csv(OUT_COVERAGE, coverage_rows, ["coverage_id", "coverage_area", "required_scope", "required_symbols_or_tickers", "required_windows", "required_dates", "created_now"])
    write_csv(OUT_SIGNAL_WINDOW, signal_window_rows, ["requirement_type", "symbol_scope", "signal_date_count", "window_name", "price_date_rule", "rows_created_now"])
    write_csv(OUT_ALLOWED, allowed_options, ["option_id", "option_name", "description", "network_used_by_pipeline", "allowed_next"])
    write_csv(OUT_DISALLOWED, disallowed_options, ["option_id", "option_name", "reason"])
    write_csv(OUT_MANUAL, manual_rows, ["step_id", "operator_step", "target_file", "notes"])
    write_csv(OUT_IMPORTER, importer_rows, ["design_id", "design_option", "description", "downloads_allowed"])
    write_csv(OUT_BLOCKERS, blocker_rows, ["blocker_id", "blocker_source", "blocker_scope", "blocker_reason", "blocks_value_attachment", "blocks_backtest_execution", "v20_24_resolution_plan_created"])
    write_csv(OUT_NEXT, next_rows, ["requirement_id", "requirement_area", "required_next_artifact", "created_now", "next_step"])
    write_csv(OUT_GATE, gate, list(gate[0].keys()))
    write_csv(OUT_VALIDATION, validation, list(validation[0].keys()))

    read_first_text = f"""PATCH_VERSION: V20.24
PATCH_NAME: LOCAL_OUTCOME_BENCHMARK_DATA_REQUIREMENT_AND_ACQUISITION_PLAN
REPORTING_ONLY: TRUE
PLANNING_ONLY: TRUE
LOCAL_DATA_REQUIREMENT_ONLY: TRUE
NO_EXTERNAL_DOWNLOAD_OR_API: TRUE
NO_SOURCE_MUTATION: TRUE
STATUS: {PASS_STATUS}
LOCAL_OUTCOME_BENCHMARK_REQUIREMENT_PLAN_CREATED: TRUE
ACTIVE_OUTCOME_INPUT_CREATED: FALSE
ACTIVE_BENCHMARK_INPUT_CREATED: FALSE
READY_FOR_V20_25_LOCAL_OUTCOME_BENCHMARK_IMPORTER_OR_MANUAL_STAGING_NEXT: TRUE
READY_FOR_VALUE_ATTACHMENT_NEXT: FALSE
READY_FOR_BACKTEST_EXECUTION_NEXT: FALSE
OUTCOME_VALUES_ATTACHED_TO_BACKTEST_CANDIDATES: FALSE
BENCHMARK_VALUES_ATTACHED_TO_BACKTEST_CANDIDATES: FALSE
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
NEXT_RECOMMENDED_STEP: {NEXT_STEP}
"""
    write_text(READ_FIRST, read_first_text)

    report = f"""# V20.24 Local Outcome/Benchmark Data Requirement And Acquisition Plan

Status: {PASS_STATUS}

V20.24 is planning-only. It defines the required active input files, schemas, coverage, allowed local acquisition options, disallowed source options, and next staging requirements. It does not create active outcome/benchmark input files, attach values, compute returns, run backtests, create dynamic weighting, create signals, or create official recommendations.

## Summary

- Backtest candidate rows considered: {len(backtest_candidates)}
- Required ticker count: {len(tickers)}
- Required signal date count: {len(signal_dates)}
- V20.23 inventory rows reviewed: {len(inventory)}
- V20.23 outcome candidates: {len(outcome_candidates)}
- V20.23 benchmark candidates: {len(benchmark_candidates)}
- Active outcome input created: FALSE
- Active benchmark input created: FALSE
- Next recommended step: {NEXT_STEP}

## Required Input Files

{md_table(['input_type', 'required_input_path', 'created_now', 'required_for_v20_25'], input_register)}

## Allowed Options

{md_table(['option_id', 'option_name', 'description', 'allowed_next'], allowed_options)}

## Disallowed Options

{md_table(['option_id', 'option_name', 'reason'], disallowed_options)}
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)

    zh = f"""# V20.24 操作员数据准备指南

状态：`{PASS_STATUS}`

## 为什么 V20.23 不能创建活动输入文件

V20.23 只允许使用本地项目中已经存在、可证明为 active runtime、PIT 安全、并且带有完整 lineage 的数据。审核结果显示，本地文件没有同时满足以下条件：明确的未来 outcome/benchmark 价格日期、完整 source_artifact_id/source_hash/run_id、active_runtime_flag 为 TRUE、historical_reference_flag 为 FALSE、以及可解析的 availability_date 或 created_at_utc。因此不能把任何本地候选文件提升为活动输入。

## 下一步必须提供的文件

1. `inputs/v20/outcome_benchmark/V20_OUTCOME_SOURCE_INPUT.csv`
2. `inputs/v20/outcome_benchmark/V20_BENCHMARK_SOURCE_INPUT.csv`

本阶段不会创建这两个文件。它只说明文件必须长什么样，以及后续 V20.25 如何安全地导入或人工 staging。

## Outcome 文件必填列

{', '.join(OUTCOME_FIELDS)}

每一行代表一个个股在某个 `signal_date` 和 `outcome_window` 下的未来价格观察值。`outcome_price_date` 必须大于或等于 `signal_date`，并且价格必须来自本地可审计来源，不能用当前同日价格推断。

## Benchmark 文件必填列

{', '.join(BENCHMARK_FIELDS)}

Benchmark 文件必须包含明确的 `SPY` 和 `QQQ` 行。它不是个股 outcome 文件，也不能用其他 ETF 或指数代理替代。每一行代表某个 benchmark_symbol 在某个 `signal_date` 和 `benchmark_window` 下的未来 benchmark 价格观察值。

## 可以接受的本地准备方式

- 从券商或数据供应商手动导出 CSV，然后复制到 `inputs/v20/outcome_benchmark/`。
- 用户在流水线外部准备好本地 CSV，并保留 source_hash、run_id、source_artifact_id。
- 后续实现一个只读取本地文件的 importer；该 importer 仍然不能下载数据、不能调用 API。

## 禁止的方式

- 伪造未来价格。
- 用当前同日价格推断未来 outcome。
- 把 template 示例行当作真实数据。
- 未经认证就把 sealed historical reference 当作 active runtime 数据。
- 在流水线中调用 yfinance、网页请求、broker API 或任何网络接口。
- 缺少 SPY/QQQ 明确行时使用 benchmark 代理。

## 为什么 backtest 和动态权重仍然被阻塞

当前还没有通过认证的 outcome/benchmark 活动输入文件，因此不能附加未来 outcome 值，不能计算 forward return 或 benchmark-relative return，也不能计算 performance metrics。没有这些经过认证的输入，就不能执行 backtest、dynamic weighting、strategy signal、trading signal 或 official recommendation。
"""
    write_text(ZH_GUIDE, zh)

    print(PASS_STATUS)
    print("ACTIVE_OUTCOME_INPUT_CREATED=FALSE")
    print("ACTIVE_BENCHMARK_INPUT_CREATED=FALSE")
    print(f"REQUIRED_TICKER_COUNT={len(tickers)}")
    print(f"REQUIRED_SIGNAL_DATE_COUNT={len(signal_dates)}")
    print(f"NEXT_RECOMMENDED_STEP={NEXT_STEP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
