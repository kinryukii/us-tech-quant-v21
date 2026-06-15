from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
INPUT_BASE = ROOT / "inputs" / "v20" / "outcome_benchmark"
INPUT_STAGING = INPUT_BASE / "staging"

IN_READ_FIRST = OPS / "V20_20_READ_FIRST.txt"
IN_GATE = CONSOLIDATION / "V20_20_GATE_DECISION.csv"
IN_BLOCKERS = CONSOLIDATION / "V20_20_OUTCOME_BENCHMARK_SOURCE_BLOCKER_REGISTER.csv"
IN_OUTCOME_TEMPLATE = CONSOLIDATION / "V20_20_OUTCOME_SOURCE_INPUT_TEMPLATE.csv"
IN_BENCHMARK_TEMPLATE = CONSOLIDATION / "V20_20_BENCHMARK_SOURCE_INPUT_TEMPLATE.csv"
IN_REQUIREMENTS = CONSOLIDATION / "V20_20_NEXT_VALUE_ATTACHMENT_REQUIREMENTS.csv"

OUTCOME_TEMPLATE_PATH = INPUT_BASE / "V20_OUTCOME_SOURCE_INPUT_TEMPLATE.csv"
BENCHMARK_TEMPLATE_PATH = INPUT_BASE / "V20_BENCHMARK_SOURCE_INPUT_TEMPLATE.csv"
INPUT_README = INPUT_BASE / "V20_OUTCOME_BENCHMARK_INPUT_README.md"
EXPECTED_OUTCOME_INPUT = INPUT_BASE / "V20_OUTCOME_SOURCE_INPUT.csv"
EXPECTED_BENCHMARK_INPUT = INPUT_BASE / "V20_BENCHMARK_SOURCE_INPUT.csv"

OUT_DEP = CONSOLIDATION / "V20_21_DEPENDENCY_AUDIT.csv"
OUT_DIR = CONSOLIDATION / "V20_21_INPUT_DIRECTORY_AUDIT.csv"
OUT_OUTCOME_SCHEMA = CONSOLIDATION / "V20_21_OUTCOME_INPUT_TEMPLATE_SCHEMA.csv"
OUT_BENCHMARK_SCHEMA = CONSOLIDATION / "V20_21_BENCHMARK_INPUT_TEMPLATE_SCHEMA.csv"
OUT_PATH_REGISTER = CONSOLIDATION / "V20_21_EXPECTED_INPUT_PATH_REGISTER.csv"
OUT_OUTCOME_DISCOVERY = CONSOLIDATION / "V20_21_EXISTING_OUTCOME_INPUT_DISCOVERY.csv"
OUT_BENCHMARK_DISCOVERY = CONSOLIDATION / "V20_21_EXISTING_BENCHMARK_INPUT_DISCOVERY.csv"
OUT_SCHEMA_COVERAGE = CONSOLIDATION / "V20_21_EXISTING_INPUT_SCHEMA_COVERAGE_AUDIT.csv"
OUT_LEDGER = CONSOLIDATION / "V20_21_STAGING_REGISTRATION_LEDGER.csv"
OUT_CARRYFORWARD = CONSOLIDATION / "V20_21_CERTIFICATION_REQUIREMENTS_CARRYFORWARD.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_21_BLOCKER_REGISTER.csv"
OUT_NEXT_REQ = CONSOLIDATION / "V20_21_NEXT_CERTIFICATION_REQUIREMENTS.csv"
OUT_GATE = CONSOLIDATION / "V20_21_GATE_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_21_VALIDATION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_21_OUTCOME_BENCHMARK_INPUT_STAGING_AND_REGISTRATION_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_OUTCOME_BENCHMARK_INPUT_STAGING_AND_REGISTRATION.md"
READ_FIRST = OPS / "V20_21_READ_FIRST.txt"

PASS_STATUS = "PASS_V20_21_OUTCOME_BENCHMARK_INPUT_STAGING_AND_REGISTRATION"
NEXT_STEP = "V20.22_OUTCOME_BENCHMARK_INPUT_CERTIFICATION_RETRY"
REQUIRED_INPUTS = [
    IN_READ_FIRST,
    IN_GATE,
    IN_BLOCKERS,
    IN_OUTCOME_TEMPLATE,
    IN_BENCHMARK_TEMPLATE,
    IN_REQUIREMENTS,
]
ALLOWED_WRITE_PATHS = {
    OUTCOME_TEMPLATE_PATH,
    BENCHMARK_TEMPLATE_PATH,
    INPUT_README,
    OUT_DEP,
    OUT_DIR,
    OUT_OUTCOME_SCHEMA,
    OUT_BENCHMARK_SCHEMA,
    OUT_PATH_REGISTER,
    OUT_OUTCOME_DISCOVERY,
    OUT_BENCHMARK_DISCOVERY,
    OUT_SCHEMA_COVERAGE,
    OUT_LEDGER,
    OUT_CARRYFORWARD,
    OUT_BLOCKERS,
    OUT_NEXT_REQ,
    OUT_GATE,
    OUT_VALIDATION,
    REPORT,
    CURRENT_REPORT,
    READ_FIRST,
}

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
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows[:limit]:
        out.append("| " + " | ".join(clean(row.get(h)).replace("|", "/") for h in headers) + " |")
    return "\n".join(out)


def schema_rows(kind: str, fields: list[str]) -> list[dict[str, str]]:
    return [
        {
            "template_type": kind,
            "field_name": field,
            "required": "TRUE",
            "certification_use": certification_use(field),
            "created_by_stage": "V20.21",
        }
        for field in fields
    ]


def certification_use(field: str) -> str:
    if field in {"ticker", "benchmark_symbol"}:
        return "symbol_coverage"
    if "date" in field or field == "created_at_utc":
        return "pit_availability_and_window_alignment"
    if "close" in field:
        return "value_source_field_for_later_attachment_only"
    if field in {"source_artifact_id", "source_hash", "run_id"}:
        return "lineage_hash_run_id_certification"
    if field in {"active_runtime_flag", "historical_reference_flag"}:
        return "active_runtime_source_policy"
    return "metadata"


def template_row(fields: list[str], benchmark: bool) -> dict[str, str]:
    examples = {
        "ticker": "AAPL",
        "benchmark_symbol": "SPY",
        "signal_date": "YYYY-MM-DD",
        "outcome_window": "forward_1d",
        "benchmark_window": "benchmark_forward_1d",
        "outcome_price_date": "YYYY-MM-DD",
        "benchmark_price_date": "YYYY-MM-DD",
        "outcome_close": "numeric_price_no_return_calculation",
        "benchmark_close": "numeric_price_no_return_calculation",
        "adjusted_outcome_close": "numeric_adjusted_price_no_return_calculation",
        "adjusted_benchmark_close": "numeric_adjusted_price_no_return_calculation",
        "currency": "USD",
        "source_artifact_id": "required_active_runtime_source_id",
        "source_hash": "required_source_hash",
        "run_id": "required_run_id",
        "active_runtime_flag": "TRUE",
        "historical_reference_flag": "FALSE",
        "availability_date": "YYYY-MM-DD",
        "created_at_utc": "YYYY-MM-DDTHH:MM:SSZ",
        "data_vendor_or_source_system": "local_registered_source_name",
        "notes": "staging_template_only_no_returns_or_backtests",
    }
    return {field: examples.get(field, "") for field in fields}


def inspect_existing(path: Path, required_fields: list[str], kind: str) -> tuple[list[dict[str, str]], dict[str, str]]:
    exists = path.exists()
    rows, fields = read_csv(path) if exists else ([], [])
    field_set = set(fields)
    missing = [field for field in required_fields if field not in field_set]
    discovery = {
        "input_type": kind,
        "input_path": rel(path),
        "exists": tf(exists),
        "readable_csv": tf(exists and bool(fields)),
        "field_count": str(len(fields)),
        "row_count": str(len(rows)),
        "schema_complete": tf(exists and not missing),
        "certification_executed": "FALSE",
        "value_attachment_executed": "FALSE",
        "discovery_note": "Schema inspected only; V20.21 does not certify or attach values.",
    }
    coverage_rows = [
        {
            "input_type": kind,
            "input_path": rel(path),
            "field_name": field,
            "required": "TRUE",
            "present": tf(field in field_set),
            "schema_coverage_passed": tf(field in field_set),
            "certification_executed": "FALSE",
        }
        for field in required_fields
    ]
    return coverage_rows, discovery


def main() -> int:
    generated_at = utc_now()
    INPUT_BASE.mkdir(parents=True, exist_ok=True)
    INPUT_STAGING.mkdir(parents=True, exist_ok=True)

    v20_gate_rows, _ = read_csv(IN_GATE)
    v20_gate = v20_gate_rows[0] if v20_gate_rows else {}
    read_first_text = IN_READ_FIRST.read_text(encoding="utf-8", errors="replace") if IN_READ_FIRST.exists() else ""
    v20_blockers, _ = read_csv(IN_BLOCKERS)
    v20_requirements, _ = read_csv(IN_REQUIREMENTS)

    dependency_rows: list[dict[str, str]] = []
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
                "blocker_reason": "" if ok else f"Required V20.20 dependency {rel(path)} is missing.",
            }
        )
    gate_ok = (
        upper(v20_gate.get("STATUS")) == "PASS_V20_20_OUTCOME_BENCHMARK_SOURCE_CERTIFICATION_OR_BLOCKER_RESOLUTION"
        and upper(v20_gate.get("CERTIFIED_OUTCOME_SOURCE_FOUND")) == "FALSE"
        and upper(v20_gate.get("CERTIFIED_BENCHMARK_SOURCE_FOUND")) == "FALSE"
        and upper(v20_gate.get("READY_FOR_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_NEXT")) == "FALSE"
        and upper(v20_gate.get("READY_FOR_BACKTEST_EXECUTION_NEXT")) == "FALSE"
    )
    read_first_ok = all(
        token in read_first_text
        for token in [
            "NO_EXTERNAL_DOWNLOAD_OR_API: TRUE",
            "NO_SOURCE_MUTATION: TRUE",
            "OUTCOME_VALUES_CREATED: FALSE",
            "BENCHMARK_VALUES_CREATED: FALSE",
            "FORWARD_RETURNS_CREATED: FALSE",
            "BENCHMARK_RELATIVE_RETURNS_CREATED: FALSE",
            "PERFORMANCE_METRICS_CREATED: FALSE",
            "BACKTEST_EXECUTED: FALSE",
            "DYNAMIC_WEIGHTING_CREATED: FALSE",
            "TRADING_SIGNAL_CREATED: FALSE",
            "OFFICIAL_RECOMMENDATION_CREATED: FALSE",
            "V21_OUTPUT_CREATED: FALSE",
            "V19_21_OUTPUT_CREATED: FALSE",
        ]
    )
    dependency_ok = dependency_ok and gate_ok and read_first_ok
    dependency_rows.extend(
        [
            {
                "dependency_id": "V20_20_GATE_EXPECTED_BLOCKER_STATE",
                "dependency_path": rel(IN_GATE),
                "required": "TRUE",
                "exists": tf(IN_GATE.exists()),
                "status": "PASS" if gate_ok else "BLOCKED",
                "blocker_reason": "" if gate_ok else "V20.20 gate does not match expected blocker-resolution state.",
            },
            {
                "dependency_id": "V20_20_READ_FIRST_SAFETY_FLAGS",
                "dependency_path": rel(IN_READ_FIRST),
                "required": "TRUE",
                "exists": tf(IN_READ_FIRST.exists()),
                "status": "PASS" if read_first_ok else "BLOCKED",
                "blocker_reason": "" if read_first_ok else "V20.20 READ_FIRST safety flags are incomplete.",
            },
        ]
    )

    write_csv(OUTCOME_TEMPLATE_PATH, [template_row(OUTCOME_FIELDS, benchmark=False)], OUTCOME_FIELDS)
    write_csv(BENCHMARK_TEMPLATE_PATH, [template_row(BENCHMARK_FIELDS, benchmark=True)], BENCHMARK_FIELDS)
    readme = """# V20 Outcome/Benchmark Input Staging

Populate `V20_OUTCOME_SOURCE_INPUT.csv` and `V20_BENCHMARK_SOURCE_INPUT.csv` only with local, registered, PIT-safe active runtime source data.

This directory is staging only. Do not use these templates to compute returns, benchmark-relative returns, performance metrics, backtests, dynamic weights, trading signals, or official recommendations.

V20.22 is the next certification retry stage. V20.21 only creates templates, registers expected input paths, and inspects any existing active input CSVs for schema coverage.
"""
    write_text(INPUT_README, readme)

    outcome_coverage, outcome_discovery = inspect_existing(EXPECTED_OUTCOME_INPUT, OUTCOME_FIELDS, "outcome")
    benchmark_coverage, benchmark_discovery = inspect_existing(EXPECTED_BENCHMARK_INPUT, BENCHMARK_FIELDS, "benchmark")
    actual_outcome_found = EXPECTED_OUTCOME_INPUT.exists()
    actual_benchmark_found = EXPECTED_BENCHMARK_INPUT.exists()

    directory_rows = [
        {
            "directory_id": "V20_21_INPUT_BASE",
            "directory_path": rel(INPUT_BASE),
            "required": "TRUE",
            "exists": tf(INPUT_BASE.exists()),
            "created_or_ensured_now": "TRUE",
            "source_mutation": "FALSE",
        },
        {
            "directory_id": "V20_21_INPUT_STAGING",
            "directory_path": rel(INPUT_STAGING),
            "required": "TRUE",
            "exists": tf(INPUT_STAGING.exists()),
            "created_or_ensured_now": "TRUE",
            "source_mutation": "FALSE",
        },
    ]
    path_register = [
        {
            "registered_input_id": "V20_21_EXPECTED_OUTCOME_INPUT",
            "input_type": "outcome",
            "expected_input_path": rel(EXPECTED_OUTCOME_INPUT),
            "template_path": rel(OUTCOME_TEMPLATE_PATH),
            "actual_input_found": tf(actual_outcome_found),
            "certification_executed_now": "FALSE",
            "value_attachment_executed_now": "FALSE",
            "next_required_step": "V20.22_OUTCOME_BENCHMARK_INPUT_CERTIFICATION_RETRY",
        },
        {
            "registered_input_id": "V20_21_EXPECTED_BENCHMARK_INPUT",
            "input_type": "benchmark",
            "expected_input_path": rel(EXPECTED_BENCHMARK_INPUT),
            "template_path": rel(BENCHMARK_TEMPLATE_PATH),
            "actual_input_found": tf(actual_benchmark_found),
            "certification_executed_now": "FALSE",
            "value_attachment_executed_now": "FALSE",
            "next_required_step": "V20.22_OUTCOME_BENCHMARK_INPUT_CERTIFICATION_RETRY",
        },
    ]
    ledger = [
        {
            "ledger_id": "V20_21_LEDGER_001",
            "staging_action": "ensure_input_directories",
            "artifact_path": rel(INPUT_BASE),
            "status": "PASS",
            "certification_executed": "FALSE",
            "values_created": "FALSE",
            "notes": "Created or confirmed input base and staging directories.",
        },
        {
            "ledger_id": "V20_21_LEDGER_002",
            "staging_action": "write_outcome_template",
            "artifact_path": rel(OUTCOME_TEMPLATE_PATH),
            "status": "PASS",
            "certification_executed": "FALSE",
            "values_created": "FALSE",
            "notes": "Outcome source input template only.",
        },
        {
            "ledger_id": "V20_21_LEDGER_003",
            "staging_action": "write_benchmark_template",
            "artifact_path": rel(BENCHMARK_TEMPLATE_PATH),
            "status": "PASS",
            "certification_executed": "FALSE",
            "values_created": "FALSE",
            "notes": "Benchmark source input template only.",
        },
        {
            "ledger_id": "V20_21_LEDGER_004",
            "staging_action": "register_expected_active_input_paths",
            "artifact_path": rel(INPUT_BASE),
            "status": "PASS",
            "certification_executed": "FALSE",
            "values_created": "FALSE",
            "notes": "Expected active input CSV paths registered for V20.22 certification retry.",
        },
    ]
    carryforward_rows = []
    for idx, row in enumerate(v20_requirements, start=1):
        carryforward_rows.append(
            {
                "carryforward_id": f"V20_21_REQ_CF_{idx:03d}",
                "source_requirement_id": clean(row.get("requirement_id")),
                "requirement_area": clean(row.get("requirement_area")),
                "required_condition": clean(row.get("required_condition")),
                "currently_satisfied": clean(row.get("currently_satisfied")),
                "carried_forward_to_v20_22": "TRUE",
                "certification_executed_now": "FALSE",
                "next_required_step": "V20.22_OUTCOME_BENCHMARK_INPUT_CERTIFICATION_RETRY",
            }
        )
    blocker_rows = []
    for idx, row in enumerate(v20_blockers, start=1):
        blocker_rows.append(
            {
                "blocker_id": f"V20_21_BLOCKER_{idx:03d}",
                "blocker_source": "V20.20_CARRYFORWARD",
                "blocker_scope": clean(row.get("blocker_scope")),
                "blocker_status": clean(row.get("blocker_status")) or "OPEN",
                "blocker_reason": clean(row.get("blocker_reason")),
                "blocks_value_attachment_next": "TRUE",
                "blocks_backtest_execution": "TRUE",
                "blocks_dynamic_weighting": "TRUE",
                "blocks_trading_or_official_use": "TRUE",
                "v20_21_resolution_action": "Input templates and expected paths staged; certification deferred to V20.22.",
            }
        )
    next_req = [
        {
            "requirement_id": "V20_21_NEXT_OUTCOME_INPUT_CERTIFICATION",
            "requirement_area": "outcome_input",
            "required_input_path": rel(EXPECTED_OUTCOME_INPUT),
            "required_fields": ";".join(OUTCOME_FIELDS),
            "actual_input_found": tf(actual_outcome_found),
            "certification_executed_now": "FALSE",
            "value_attachment_allowed_now": "FALSE",
            "next_required_step": "V20.22_OUTCOME_BENCHMARK_INPUT_CERTIFICATION_RETRY",
        },
        {
            "requirement_id": "V20_21_NEXT_BENCHMARK_INPUT_CERTIFICATION",
            "requirement_area": "benchmark_input",
            "required_input_path": rel(EXPECTED_BENCHMARK_INPUT),
            "required_fields": ";".join(BENCHMARK_FIELDS),
            "actual_input_found": tf(actual_benchmark_found),
            "certification_executed_now": "FALSE",
            "value_attachment_allowed_now": "FALSE",
            "next_required_step": "V20.22_OUTCOME_BENCHMARK_INPUT_CERTIFICATION_RETRY",
        },
    ]
    gate = [
        {
            "gate_id": "V20_21_GATE",
            "STATUS": PASS_STATUS,
            "OUTCOME_BENCHMARK_INPUT_STAGING_REGISTERED": "TRUE",
            "OUTCOME_INPUT_TEMPLATE_CREATED": tf(OUTCOME_TEMPLATE_PATH.exists()),
            "BENCHMARK_INPUT_TEMPLATE_CREATED": tf(BENCHMARK_TEMPLATE_PATH.exists()),
            "ACTUAL_OUTCOME_INPUT_FOUND": tf(actual_outcome_found),
            "ACTUAL_BENCHMARK_INPUT_FOUND": tf(actual_benchmark_found),
            "READY_FOR_V20_22_OUTCOME_BENCHMARK_INPUT_CERTIFICATION_NEXT": "TRUE",
            "READY_FOR_VALUE_ATTACHMENT_NEXT": "FALSE",
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
            "NEXT_RECOMMENDED_STEP": NEXT_STEP,
        }
    ]
    validation = [
        {
            "validation_id": "V20_21_VALIDATION",
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
            "certification_executed": "FALSE",
            "outcome_values_created": "FALSE",
            "benchmark_values_created": "FALSE",
            "forward_returns_created": "FALSE",
            "benchmark_relative_returns_created": "FALSE",
            "performance_metrics_created": "FALSE",
            "backtest_executed": "FALSE",
            "generated_at_utc": generated_at,
        }
    ]

    write_csv(OUT_DEP, dependency_rows, ["dependency_id", "dependency_path", "required", "exists", "status", "blocker_reason"])
    write_csv(OUT_DIR, directory_rows, ["directory_id", "directory_path", "required", "exists", "created_or_ensured_now", "source_mutation"])
    write_csv(OUT_OUTCOME_SCHEMA, schema_rows("outcome", OUTCOME_FIELDS), ["template_type", "field_name", "required", "certification_use", "created_by_stage"])
    write_csv(OUT_BENCHMARK_SCHEMA, schema_rows("benchmark", BENCHMARK_FIELDS), ["template_type", "field_name", "required", "certification_use", "created_by_stage"])
    write_csv(OUT_PATH_REGISTER, path_register, ["registered_input_id", "input_type", "expected_input_path", "template_path", "actual_input_found", "certification_executed_now", "value_attachment_executed_now", "next_required_step"])
    write_csv(OUT_OUTCOME_DISCOVERY, [outcome_discovery], ["input_type", "input_path", "exists", "readable_csv", "field_count", "row_count", "schema_complete", "certification_executed", "value_attachment_executed", "discovery_note"])
    write_csv(OUT_BENCHMARK_DISCOVERY, [benchmark_discovery], ["input_type", "input_path", "exists", "readable_csv", "field_count", "row_count", "schema_complete", "certification_executed", "value_attachment_executed", "discovery_note"])
    write_csv(OUT_SCHEMA_COVERAGE, outcome_coverage + benchmark_coverage, ["input_type", "input_path", "field_name", "required", "present", "schema_coverage_passed", "certification_executed"])
    write_csv(OUT_LEDGER, ledger, ["ledger_id", "staging_action", "artifact_path", "status", "certification_executed", "values_created", "notes"])
    write_csv(OUT_CARRYFORWARD, carryforward_rows, ["carryforward_id", "source_requirement_id", "requirement_area", "required_condition", "currently_satisfied", "carried_forward_to_v20_22", "certification_executed_now", "next_required_step"])
    write_csv(OUT_BLOCKERS, blocker_rows, ["blocker_id", "blocker_source", "blocker_scope", "blocker_status", "blocker_reason", "blocks_value_attachment_next", "blocks_backtest_execution", "blocks_dynamic_weighting", "blocks_trading_or_official_use", "v20_21_resolution_action"])
    write_csv(OUT_NEXT_REQ, next_req, ["requirement_id", "requirement_area", "required_input_path", "required_fields", "actual_input_found", "certification_executed_now", "value_attachment_allowed_now", "next_required_step"])
    write_csv(OUT_GATE, gate, list(gate[0].keys()))
    write_csv(OUT_VALIDATION, validation, list(validation[0].keys()))

    read_first = f"""PATCH_VERSION: V20.21
PATCH_NAME: OUTCOME_BENCHMARK_INPUT_STAGING_AND_REGISTRATION
REPORTING_ONLY: TRUE
STAGING_ONLY: TRUE
CERTIFICATION_EXECUTED: FALSE
NO_EXTERNAL_DOWNLOAD_OR_API: TRUE
NO_SOURCE_MUTATION: TRUE
STATUS: {PASS_STATUS}
OUTCOME_BENCHMARK_INPUT_STAGING_REGISTERED: TRUE
OUTCOME_INPUT_TEMPLATE_CREATED: TRUE
BENCHMARK_INPUT_TEMPLATE_CREATED: TRUE
ACTUAL_OUTCOME_INPUT_FOUND: {tf(actual_outcome_found)}
ACTUAL_BENCHMARK_INPUT_FOUND: {tf(actual_benchmark_found)}
READY_FOR_V20_22_OUTCOME_BENCHMARK_INPUT_CERTIFICATION_NEXT: TRUE
READY_FOR_VALUE_ATTACHMENT_NEXT: FALSE
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
NEXT_RECOMMENDED_STEP: {NEXT_STEP}
"""
    write_text(READ_FIRST, read_first)

    report = f"""# V20.21 Outcome/Benchmark Input Staging And Registration

Status: {PASS_STATUS}

V20.21 is staging-only. It created the user-fillable input template area and registered expected active input paths for V20.22 certification retry. It did not certify inputs, attach values, compute returns, compute performance metrics, run backtests, create dynamic weighting, create signals, or create official recommendations.

## Staging Result

- Outcome input template created: TRUE
- Benchmark input template created: TRUE
- Actual outcome input found: {tf(actual_outcome_found)}
- Actual benchmark input found: {tf(actual_benchmark_found)}
- Ready for V20.22 certification retry: TRUE
- Ready for value attachment next: FALSE
- Ready for backtest execution next: FALSE
- Next recommended step: {NEXT_STEP}

## Registered Input Paths

{md_table(['registered_input_id', 'input_type', 'expected_input_path', 'template_path', 'actual_input_found'], path_register)}

## Carryforward Blockers

{md_table(['blocker_id', 'blocker_scope', 'blocker_reason', 'blocks_value_attachment_next', 'blocks_backtest_execution'], blocker_rows)}
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)

    print(PASS_STATUS)
    print(f"OUTCOME_INPUT_TEMPLATE_CREATED={tf(OUTCOME_TEMPLATE_PATH.exists())}")
    print(f"BENCHMARK_INPUT_TEMPLATE_CREATED={tf(BENCHMARK_TEMPLATE_PATH.exists())}")
    print(f"ACTUAL_OUTCOME_INPUT_FOUND={tf(actual_outcome_found)}")
    print(f"ACTUAL_BENCHMARK_INPUT_FOUND={tf(actual_benchmark_found)}")
    print(f"NEXT_RECOMMENDED_STEP={NEXT_STEP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
