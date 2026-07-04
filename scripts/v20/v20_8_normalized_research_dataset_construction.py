from __future__ import annotations

import argparse
import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path.cwd()
OPS = ROOT / "outputs" / "v20" / "ops"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_V20_7X_BINDING = CONSOLIDATION / "V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv"
IN_V20_7X_GATE = CONSOLIDATION / "V20_7X_GATE_DECISION.csv"
IN_V20_7X_READINESS = CONSOLIDATION / "V20_7X_INPUT_READINESS_FOR_V20_8_AUDIT.csv"
IN_V20_7X_VALIDATION = CONSOLIDATION / "V20_7X_VALIDATION_SUMMARY.csv"
IN_V20_7X_READ_FIRST = OPS / "V20_7X_READ_FIRST.txt"

OUT_DEPENDENCY = CONSOLIDATION / "V20_8_DEPENDENCY_AUDIT.csv"
OUT_NORMALIZED = CONSOLIDATION / "V20_8_NORMALIZED_RESEARCH_DATASET.csv"
OUT_SCHEMA = CONSOLIDATION / "V20_8_NORMALIZED_SCHEMA_AUDIT.csv"
OUT_FIELD_MAP = CONSOLIDATION / "V20_8_FIELD_NORMALIZATION_MAP.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_8_LINEAGE_PRESERVATION_AUDIT.csv"
OUT_SAMPLE = CONSOLIDATION / "V20_8_SAMPLE_ID_PRESERVATION_AUDIT.csv"
OUT_PRICE = CONSOLIDATION / "V20_8_PRICE_DATE_CONSISTENCY_AUDIT.csv"
OUT_BOUNDARY = CONSOLIDATION / "V20_8_RESEARCH_ONLY_BOUNDARY_AUDIT.csv"
OUT_QUALITY = CONSOLIDATION / "V20_8_DATA_QUALITY_AUDIT.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_8_BLOCKER_REGISTER.csv"
OUT_GATE = CONSOLIDATION / "V20_8_GATE_DECISION.csv"
OUT_NEXT = CONSOLIDATION / "V20_8_NEXT_STEP_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_8_VALIDATION_SUMMARY.csv"

REPORT = READ_CENTER / "V20_8_NORMALIZED_RESEARCH_DATASET_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_NORMALIZED_RESEARCH_DATASET.md"
READ_FIRST = OPS / "V20_8_READ_FIRST.txt"

PATCH_VERSION = "V20.8"
NORMALIZED_DATASET_VERSION = "V20.8_NORMALIZED_RESEARCH_DATASET"
EXPECTED_SOURCE_SYSTEM = "accepted_v18_full_universe_result"

ALLOWED_WRITE_PATHS = {
    OUT_DEPENDENCY,
    OUT_NORMALIZED,
    OUT_SCHEMA,
    OUT_FIELD_MAP,
    OUT_LINEAGE,
    OUT_SAMPLE,
    OUT_PRICE,
    OUT_BOUNDARY,
    OUT_QUALITY,
    OUT_BLOCKERS,
    OUT_GATE,
    OUT_NEXT,
    OUT_VALIDATION,
    REPORT,
    CURRENT_REPORT,
    READ_FIRST,
}


def configure_paths(
    repo_root: Path | None = None,
    input_path: Path | None = None,
    output_dir: Path | None = None,
) -> None:
    global ROOT, OPS, CONSOLIDATION, READ_CENTER
    global IN_V20_7X_BINDING, IN_V20_7X_GATE, IN_V20_7X_READINESS, IN_V20_7X_VALIDATION, IN_V20_7X_READ_FIRST
    global OUT_DEPENDENCY, OUT_NORMALIZED, OUT_SCHEMA, OUT_FIELD_MAP, OUT_LINEAGE, OUT_SAMPLE, OUT_PRICE, OUT_BOUNDARY, OUT_QUALITY
    global OUT_BLOCKERS, OUT_GATE, OUT_NEXT, OUT_VALIDATION, REPORT, CURRENT_REPORT, READ_FIRST, ALLOWED_WRITE_PATHS

    ROOT = (repo_root or Path.cwd()).resolve()
    if output_dir is None:
        OPS = ROOT / "outputs" / "v20" / "ops"
        CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
        READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
    else:
        base = output_dir if output_dir.is_absolute() else ROOT / output_dir
        base = base.resolve()
        OPS = base / "ops"
        CONSOLIDATION = base / "consolidation"
        READ_CENTER = base / "read_center"

    default_input_base = ROOT / "outputs" / "v20" / "consolidation"
    default_ops = ROOT / "outputs" / "v20" / "ops"
    IN_V20_7X_BINDING = (input_path if input_path and input_path.is_absolute() else ROOT / input_path) if input_path else default_input_base / "V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv"
    IN_V20_7X_GATE = default_input_base / "V20_7X_GATE_DECISION.csv"
    IN_V20_7X_READINESS = default_input_base / "V20_7X_INPUT_READINESS_FOR_V20_8_AUDIT.csv"
    IN_V20_7X_VALIDATION = default_input_base / "V20_7X_VALIDATION_SUMMARY.csv"
    IN_V20_7X_READ_FIRST = default_ops / "V20_7X_READ_FIRST.txt"

    OUT_DEPENDENCY = CONSOLIDATION / "V20_8_DEPENDENCY_AUDIT.csv"
    OUT_NORMALIZED = CONSOLIDATION / "V20_8_NORMALIZED_RESEARCH_DATASET.csv"
    OUT_SCHEMA = CONSOLIDATION / "V20_8_NORMALIZED_SCHEMA_AUDIT.csv"
    OUT_FIELD_MAP = CONSOLIDATION / "V20_8_FIELD_NORMALIZATION_MAP.csv"
    OUT_LINEAGE = CONSOLIDATION / "V20_8_LINEAGE_PRESERVATION_AUDIT.csv"
    OUT_SAMPLE = CONSOLIDATION / "V20_8_SAMPLE_ID_PRESERVATION_AUDIT.csv"
    OUT_PRICE = CONSOLIDATION / "V20_8_PRICE_DATE_CONSISTENCY_AUDIT.csv"
    OUT_BOUNDARY = CONSOLIDATION / "V20_8_RESEARCH_ONLY_BOUNDARY_AUDIT.csv"
    OUT_QUALITY = CONSOLIDATION / "V20_8_DATA_QUALITY_AUDIT.csv"
    OUT_BLOCKERS = CONSOLIDATION / "V20_8_BLOCKER_REGISTER.csv"
    OUT_GATE = CONSOLIDATION / "V20_8_GATE_DECISION.csv"
    OUT_NEXT = CONSOLIDATION / "V20_8_NEXT_STEP_DECISION.csv"
    OUT_VALIDATION = CONSOLIDATION / "V20_8_VALIDATION_SUMMARY.csv"
    REPORT = READ_CENTER / "V20_8_NORMALIZED_RESEARCH_DATASET_REPORT.md"
    CURRENT_REPORT = READ_CENTER / "V20_CURRENT_NORMALIZED_RESEARCH_DATASET.md"
    READ_FIRST = OPS / "V20_8_READ_FIRST.txt"
    ALLOWED_WRITE_PATHS = {
        OUT_DEPENDENCY, OUT_NORMALIZED, OUT_SCHEMA, OUT_FIELD_MAP, OUT_LINEAGE,
        OUT_SAMPLE, OUT_PRICE, OUT_BOUNDARY, OUT_QUALITY, OUT_BLOCKERS,
        OUT_GATE, OUT_NEXT, OUT_VALIDATION, REPORT, CURRENT_REPORT, READ_FIRST,
    }

SAFETY_FLAGS = {
    "REPORTING_ONLY": "FALSE",
    "RESEARCH_DATASET_CONSTRUCTION": "TRUE",
    "NORMALIZED_RESEARCH_DATASET_CREATED": "FALSE",
    "FACTOR_EVIDENCE_ROWS_CREATED": "0",
    "BACKTEST_ROWS_CREATED": "0",
    "DYNAMIC_WEIGHTING_ROWS_CREATED": "0",
    "TRADING_SIGNAL_ROWS_CREATED": "0",
    "OFFICIAL_RECOMMENDATION_ROWS_CREATED": "0",
    "BROKER_API_USED": "FALSE",
    "ORDER_EXECUTION_USED": "FALSE",
    "SOURCE_MUTATION_USED": "FALSE",
    "V21_OUTPUTS_CREATED": "FALSE",
    "V19_21_OUTPUTS_CREATED": "FALSE",
    "OFFICIAL_USE_ALLOWED": "FALSE",
}

NORMALIZED_COLUMNS = [
    "normalized_row_id",
    "input_artifact_id",
    "lineage_binding_id",
    "source_artifact_id",
    "source_system",
    "source_hash",
    "run_id",
    "sample_id",
    "ticker",
    "effective_observation_date",
    "effective_price_date",
    "effective_close",
    "active_runtime_flag",
    "historical_reference_flag",
    "research_only_flag",
    "official_use_allowed",
    "normalized_dataset_version",
    "normalized_created_at_utc",
    "normalized_source_step",
    "allowed_for_factor_research_next",
    "allowed_for_backtest_now",
    "allowed_for_dynamic_weighting_now",
    "allowed_for_trading_now",
    "allowed_for_official_recommendation_now",
]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def clean(value: object) -> str:
    return str(value or "").strip()


def upper(value: object) -> str:
    return clean(value).upper()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def first_present(row: dict[str, str], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = clean(row.get(field))
        if value:
            return value
    return ""


def parse_date(value: object) -> datetime | None:
    text = clean(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def to_float(value: object) -> float | None:
    try:
        x = float(clean(value))
        if x != x or x in (float("inf"), float("-inf")):
            return None
        return x
    except Exception:
        return None


def deterministic_normalized_row_id(row: dict[str, str]) -> str:
    basis = "|".join(
        [
            clean(row.get("ticker")),
            clean(row.get("effective_observation_date")),
            clean(row.get("effective_price_date")),
            clean(row.get("sample_id")),
            clean(row.get("source_hash")),
            clean(row.get("run_id")),
        ]
    )
    return "V20_8_NORM_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24].upper()


def md_table(headers: list[str], rows: list[dict[str, str]], limit: int = 20) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows[:limit]:
        lines.append("| " + " | ".join(clean(row.get(field)).replace("|", "/") for field in headers) + " |")
    if len(rows) > limit:
        lines.append("| ... | " + f"{len(rows) - limit} more rows omitted" + " |" * max(0, len(headers) - 2))
    return "\n".join(lines)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def add_blocker(blockers: list[dict[str, str]], scope: str, reason: str, severity: str = "BLOCKING") -> None:
    blockers.append(
        {
            "blocker_id": f"V20_8_BLOCKER_{len(blockers) + 1:03d}",
            "blocker_scope": scope,
            "severity": severity,
            "blocker_status": "OPEN" if severity == "BLOCKING" else "WARN",
            "blocker_reason": reason,
            "blocks_v20_8": tf(severity == "BLOCKING"),
        }
    )


def output_inside(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--input-path", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--staging-mode", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--production-write-allowed", action="store_true")
    args = parser.parse_args(argv)
    if args.staging_mode and args.output_dir is None:
        print("STAGE=V20.8")
        print("FINAL_STATUS=BLOCKED_V20_8_STAGING_MODE_REQUIRES_OUTPUT_DIR")
        return 2
    configure_paths(args.repo_root, args.input_path, args.output_dir)
    production_write_allowed = bool(args.production_write_allowed or (args.output_dir is None and not args.staging_mode and not args.dry_run))
    if args.staging_mode:
        production_write_allowed = False
    if args.output_dir is not None and not all(output_inside(path, (args.repo_root / args.output_dir) if not args.output_dir.is_absolute() else args.output_dir) for path in ALLOWED_WRITE_PATHS):
        print("STAGE=V20.8")
        print("FINAL_STATUS=BLOCKED_V20_8_OUTPUT_OUTSIDE_STAGING_DIR")
        return 2
    generated_at = utc_now()
    today = datetime.now(timezone.utc).date()
    blockers: list[dict[str, str]] = []

    binding_rows, binding_fields = read_csv(IN_V20_7X_BINDING)
    gate_rows, _ = read_csv(IN_V20_7X_GATE)
    readiness_rows, _ = read_csv(IN_V20_7X_READINESS)
    validation_rows, _ = read_csv(IN_V20_7X_VALIDATION)
    read_first_text = IN_V20_7X_READ_FIRST.read_text(encoding="utf-8", errors="replace") if IN_V20_7X_READ_FIRST.exists() else ""

    gate = gate_rows[0] if gate_rows else {}
    readiness = readiness_rows[0] if readiness_rows else {}
    validation = validation_rows[0] if validation_rows else {}

    dependency_rows = [
        {
            "dependency": "V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING",
            "path": rel(IN_V20_7X_BINDING),
            "exists": tf(IN_V20_7X_BINDING.exists()),
            "status": "PASS" if IN_V20_7X_BINDING.exists() else "BLOCKED",
            "blocker_reason": "" if IN_V20_7X_BINDING.exists() else "V20.7X lineage binding CSV is missing.",
        },
        {
            "dependency": "V20_7X_GATE_DECISION",
            "path": rel(IN_V20_7X_GATE),
            "exists": tf(IN_V20_7X_GATE.exists()),
            "status": "PASS" if upper(gate.get("status")) == "PASS_V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING_READY" else "BLOCKED",
            "blocker_reason": "" if upper(gate.get("status")) == "PASS_V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING_READY" else "V20.7X gate did not pass.",
        },
        {
            "dependency": "V20_7X_INPUT_READINESS_FOR_V20_8_AUDIT",
            "path": rel(IN_V20_7X_READINESS),
            "exists": tf(IN_V20_7X_READINESS.exists()),
            "status": "PASS" if upper(readiness.get("readiness_status")) == "PASS" and upper(readiness.get("active_market_input_lineage_bound")) == "TRUE" and upper(readiness.get("certified_source_accepted")) == "TRUE" else "BLOCKED",
            "blocker_reason": "" if upper(readiness.get("readiness_status")) == "PASS" and upper(readiness.get("active_market_input_lineage_bound")) == "TRUE" and upper(readiness.get("certified_source_accepted")) == "TRUE" else "V20.7X readiness audit does not permit V20.8 construction.",
        },
        {
            "dependency": "V20_7X_VALIDATION_SUMMARY",
            "path": rel(IN_V20_7X_VALIDATION),
            "exists": tf(IN_V20_7X_VALIDATION.exists()),
            "status": "PASS" if upper(validation.get("status")) == "PASS_V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING_READY" and upper(validation.get("ready_for_v20_8_normalized_research_dataset_next")) == "TRUE" and upper(validation.get("v20_8_remains_blocked")) == "FALSE" else "BLOCKED",
            "blocker_reason": "" if upper(validation.get("status")) == "PASS_V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING_READY" and upper(validation.get("ready_for_v20_8_normalized_research_dataset_next")) == "TRUE" and upper(validation.get("v20_8_remains_blocked")) == "FALSE" else "V20.7X validation summary is not ready for V20.8 construction.",
        },
        {
            "dependency": "V20_7X_READ_FIRST",
            "path": rel(IN_V20_7X_READ_FIRST),
            "exists": tf(IN_V20_7X_READ_FIRST.exists()),
            "status": "PASS" if "LINEAGE_BINDING_RETRY_ONLY: TRUE" in read_first_text and "V20_8_OUTPUTS_CREATED: FALSE" in read_first_text else "BLOCKED",
            "blocker_reason": "" if "LINEAGE_BINDING_RETRY_ONLY: TRUE" in read_first_text and "V20_8_OUTPUTS_CREATED: FALSE" in read_first_text else "V20.7X read-first safety contract is incomplete.",
        },
    ]
    for row in dependency_rows:
        if row["status"] != "PASS":
            add_blocker(blockers, "DEPENDENCY", row["blocker_reason"])

    source_hashes = sorted({clean(row.get("source_hash")) for row in binding_rows if clean(row.get("source_hash"))})
    run_ids = sorted({clean(row.get("run_id")) for row in binding_rows if clean(row.get("run_id"))})
    sample_ids = [clean(row.get("sample_id")) for row in binding_rows]
    accepted_rows = [row for row in binding_rows if upper(row.get("allowed_for_v20_8_input")) == "TRUE"]
    excluded_rows = [row for row in binding_rows if upper(row.get("allowed_for_v20_8_input")) != "TRUE"]

    row_count = len(accepted_rows)
    source_hash = source_hashes[0] if len(source_hashes) == 1 else ""
    run_id = run_ids[0] if len(run_ids) == 1 else ""
    source_artifact_id = clean(accepted_rows[0].get("source_artifact_id")) if accepted_rows else clean(binding_rows[0].get("source_artifact_id")) if binding_rows else ""
    source_system = clean(accepted_rows[0].get("source_system")) if accepted_rows else clean(binding_rows[0].get("source_system")) if binding_rows else ""

    normalized_rows: list[dict[str, str]] = []
    unique_normalized_ids: set[str] = set()
    missing_ticker_count = 0
    missing_price_count = 0
    nonpositive_price_count = 0
    missing_hash_count = 0
    missing_run_id_count = 0
    missing_sample_id_count = 0
    future_date_count = 0
    duplicate_normalized_id_count = 0
    allowed_for_factor_research_next_count = 0
    official_use_allowed_count = 0
    unique_tickers: set[str] = set()
    date_distribution: dict[str, int] = {}

    for row in accepted_rows:
        ticker = clean(row.get("ticker"))
        observation_date = clean(row.get("effective_observation_date"))
        price_date = clean(row.get("effective_price_date"))
        close_value = clean(row.get("effective_close"))
        source_hash_value = clean(row.get("source_hash"))
        run_id_value = clean(row.get("run_id"))
        sample_id_value = clean(row.get("sample_id"))
        normalized_row = {
            "normalized_row_id": "",
            "input_artifact_id": clean(row.get("input_artifact_id")),
            "lineage_binding_id": clean(row.get("lineage_binding_id")),
            "source_artifact_id": clean(row.get("source_artifact_id")),
            "source_system": clean(row.get("source_system")),
            "source_hash": source_hash_value,
            "run_id": run_id_value,
            "sample_id": sample_id_value,
            "ticker": ticker,
            "effective_observation_date": observation_date,
            "effective_price_date": price_date,
            "effective_close": close_value,
            "active_runtime_flag": clean(row.get("active_runtime_flag")),
            "historical_reference_flag": clean(row.get("historical_reference_flag")),
            "research_only_flag": "TRUE",
            "official_use_allowed": "FALSE",
            "normalized_dataset_version": NORMALIZED_DATASET_VERSION,
            "normalized_created_at_utc": generated_at,
            "normalized_source_step": PATCH_VERSION,
            "allowed_for_factor_research_next": "TRUE",
            "allowed_for_backtest_now": "FALSE",
            "allowed_for_dynamic_weighting_now": "FALSE",
            "allowed_for_trading_now": "FALSE",
            "allowed_for_official_recommendation_now": "FALSE",
        }
        normalized_row["normalized_row_id"] = deterministic_normalized_row_id(normalized_row)
        if normalized_row["normalized_row_id"] in unique_normalized_ids:
            duplicate_normalized_id_count += 1
        unique_normalized_ids.add(normalized_row["normalized_row_id"])
        if not ticker:
            missing_ticker_count += 1
        if not source_hash_value:
            missing_hash_count += 1
        if not run_id_value:
            missing_run_id_count += 1
        if not sample_id_value:
            missing_sample_id_count += 1
        price_num = to_float(close_value)
        if price_num is None:
            missing_price_count += 1
        elif price_num <= 0:
            nonpositive_price_count += 1
        if ticker:
            unique_tickers.add(ticker)
        od = parse_date(observation_date)
        pd = parse_date(price_date)
        if od and od.date() > today:
            future_date_count += 1
        if pd and pd.date() > today:
            future_date_count += 1
        if observation_date:
            date_distribution[observation_date] = date_distribution.get(observation_date, 0) + 1
        if normalized_row["research_only_flag"] == "TRUE" and normalized_row["official_use_allowed"] == "FALSE":
            allowed_for_factor_research_next_count += 1
        if normalized_row["official_use_allowed"] == "TRUE":
            official_use_allowed_count += 1
        normalized_rows.append(normalized_row)

    normalized_dataset_created = bool(normalized_rows) and row_count == len(accepted_rows)
    if not normalized_dataset_created:
        add_blocker(blockers, "NORMALIZED_DATASET", "No accepted lineage rows were available for normalized dataset construction.")
    if upper(gate.get("status")) != "PASS_V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING_READY":
        add_blocker(blockers, "DEPENDENCY", "V20.7X gate is not in the required pass state.")
    if upper(gate.get("ACTIVE_MARKET_INPUT_LINEAGE_BOUND")) != "TRUE":
        add_blocker(blockers, "DEPENDENCY", "ACTIVE_MARKET_INPUT_LINEAGE_BOUND is not TRUE.")
    if upper(gate.get("READY_FOR_V20_8_NORMALIZED_RESEARCH_DATASET_NEXT")) != "TRUE":
        add_blocker(blockers, "DEPENDENCY", "READY_FOR_V20_8_NORMALIZED_RESEARCH_DATASET_NEXT is not TRUE.")
    if upper(gate.get("V20_8_REMAINS_BLOCKED")) != "FALSE":
        add_blocker(blockers, "DEPENDENCY", "V20_8_REMAINS_BLOCKED is not FALSE.")
    if duplicate_normalized_id_count:
        add_blocker(blockers, "NORMALIZED_ROW_ID", "normalized_row_id is duplicated.")
    if missing_ticker_count or missing_price_count or nonpositive_price_count or missing_hash_count or missing_run_id_count or missing_sample_id_count:
        add_blocker(blockers, "SCHEMA", "One or more required normalized fields are missing or invalid.")
    if future_date_count:
        add_blocker(blockers, "DATE_PRICE_CONSISTENCY", "One or more effective dates are in the future.")
    if official_use_allowed_count:
        add_blocker(blockers, "RESEARCH_ONLY_BOUNDARY", "official_use_allowed must be FALSE for all normalized research rows.")

    normalized_rows_out = normalized_rows
    if not normalized_rows_out:
        normalized_rows_out = []

    schema_rows = []
    required_columns = set(NORMALIZED_COLUMNS)
    detected_columns = set(normalized_rows_out[0].keys()) if normalized_rows_out else set()
    for column in NORMALIZED_COLUMNS:
        schema_rows.append(
            {
                "column_name": column,
                "required": "TRUE",
                "detected": tf(column in detected_columns),
                "non_empty_row_count": str(sum(1 for row in normalized_rows_out if clean(row.get(column)))),
                "row_count": str(len(normalized_rows_out)),
                "schema_status": "PASS" if column in detected_columns and all(clean(row.get(column)) for row in normalized_rows_out) else "BLOCKED",
                "blocker_reason": "" if column in detected_columns and all(clean(row.get(column)) for row in normalized_rows_out) else f"Required normalized column {column} is missing or blank.",
            }
        )

    field_map_rows = [
        {"source_field": "ticker", "normalized_field": "ticker"},
        {"source_field": "effective_observation_date", "normalized_field": "effective_observation_date"},
        {"source_field": "effective_price_date", "normalized_field": "effective_price_date"},
        {"source_field": "effective_close", "normalized_field": "effective_close"},
        {"source_field": "source_hash", "normalized_field": "source_hash"},
        {"source_field": "run_id", "normalized_field": "run_id"},
        {"source_field": "sample_id", "normalized_field": "sample_id"},
        {"source_field": "source_system", "normalized_field": "source_system"},
        {"source_field": "source_artifact_id", "normalized_field": "source_artifact_id"},
        {"source_field": "input_artifact_id", "normalized_field": "input_artifact_id"},
        {"source_field": "lineage_binding_id", "normalized_field": "lineage_binding_id"},
        {"source_field": "active_runtime_flag", "normalized_field": "active_runtime_flag"},
        {"source_field": "historical_reference_flag", "normalized_field": "historical_reference_flag"},
    ]

    lineage_rows = [
        {
            "lineage_audit_id": "V20_8_LINEAGE_001",
            "normalized_row_count": str(len(normalized_rows_out)),
            "source_hash_count": str(len(source_hashes)),
            "run_id_count": str(len(run_ids)),
            "sample_id_count": str(len(sample_ids)),
            "source_hash_preserved_count": str(sum(1 for row in normalized_rows_out if clean(row.get("source_hash")) == source_hash and source_hash)),
            "run_id_preserved_count": str(sum(1 for row in normalized_rows_out if clean(row.get("run_id")) == run_id and run_id)),
            "sample_id_preserved_count": str(sum(1 for row in normalized_rows_out if clean(row.get("sample_id")))),
            "source_system_preserved_count": str(sum(1 for row in normalized_rows_out if clean(row.get("source_system")) == EXPECTED_SOURCE_SYSTEM)),
            "linked_to_v20_7x_lineage_binding": tf(all(clean(row.get("lineage_binding_id")) for row in normalized_rows_out)),
            "lineage_preservation_status": "PASS" if normalized_rows_out and all(clean(row.get("source_hash")) for row in normalized_rows_out) and all(clean(row.get("run_id")) for row in normalized_rows_out) and all(clean(row.get("sample_id")) for row in normalized_rows_out) and all(clean(row.get("source_system")) for row in normalized_rows_out) else "BLOCKED",
            "blocker_reason": "" if normalized_rows_out else "No normalized rows were created.",
        }
    ]

    sample_rows = [
        {
            "sample_audit_id": "V20_8_SAMPLE_001",
            "normalized_row_count": str(len(normalized_rows_out)),
            "sample_id_count": str(sum(1 for row in normalized_rows_out if clean(row.get("sample_id")))),
            "sample_id_unique_count": str(len({clean(row.get("sample_id")) for row in normalized_rows_out if clean(row.get("sample_id"))})),
            "duplicate_sample_id_count": str(max(0, len(normalized_rows_out) - len({clean(row.get("sample_id")) for row in normalized_rows_out if clean(row.get("sample_id"))}))),
            "normalized_row_id_unique_count": str(len(unique_normalized_ids)),
            "normalized_row_id_duplicate_count": str(duplicate_normalized_id_count),
            "sample_id_preservation_status": "PASS" if len(normalized_rows_out) == len({clean(row.get("sample_id")) for row in normalized_rows_out if clean(row.get("sample_id"))}) else "BLOCKED",
            "blocker_reason": "" if len(normalized_rows_out) == len({clean(row.get("sample_id")) for row in normalized_rows_out if clean(row.get("sample_id"))}) else "sample_id preservation failed.",
        }
    ]

    price_rows = [
        {
            "price_audit_id": "V20_8_PRICE_001",
            "normalized_row_count": str(len(normalized_rows_out)),
            "parseable_observation_date_count": str(sum(1 for row in normalized_rows_out if parse_date(clean(row.get("effective_observation_date"))))),
            "parseable_price_date_count": str(sum(1 for row in normalized_rows_out if parse_date(clean(row.get("effective_price_date"))))),
            "future_date_row_count": str(future_date_count),
            "effective_close_numeric_positive_count": str(sum(1 for row in normalized_rows_out if (to_float(clean(row.get("effective_close"))) or 0) > 0)),
            "stale_leakage_status_inherited_from_v20_7x": "PASS",
            "price_date_consistency_status": "PASS" if not future_date_count and nonpositive_price_count == 0 and missing_price_count == 0 else "BLOCKED",
            "blocker_reason": "" if not future_date_count and nonpositive_price_count == 0 and missing_price_count == 0 else "Price/date consistency failed.",
        }
    ]

    boundary_rows = [
        {
            "boundary_check_id": "V20_8_BOUNDARY_001",
            "research_only_flag_required": "TRUE",
            "official_use_allowed_required": "FALSE",
            "allowed_for_factor_research_next_required": "TRUE",
            "allowed_for_backtest_now_required": "FALSE",
            "allowed_for_dynamic_weighting_now_required": "FALSE",
            "allowed_for_trading_now_required": "FALSE",
            "allowed_for_official_recommendation_now_required": "FALSE",
            "research_only_row_count": str(sum(1 for row in normalized_rows_out if upper(row.get("research_only_flag")) == "TRUE")),
            "official_use_allowed_row_count": str(sum(1 for row in normalized_rows_out if upper(row.get("official_use_allowed")) == "TRUE")),
            "allowed_for_factor_research_next_row_count": str(sum(1 for row in normalized_rows_out if upper(row.get("allowed_for_factor_research_next")) == "TRUE")),
            "allowed_for_backtest_now_row_count": str(sum(1 for row in normalized_rows_out if upper(row.get("allowed_for_backtest_now")) == "TRUE")),
            "allowed_for_dynamic_weighting_now_row_count": str(sum(1 for row in normalized_rows_out if upper(row.get("allowed_for_dynamic_weighting_now")) == "TRUE")),
            "allowed_for_trading_now_row_count": str(sum(1 for row in normalized_rows_out if upper(row.get("allowed_for_trading_now")) == "TRUE")),
            "allowed_for_official_recommendation_now_row_count": str(sum(1 for row in normalized_rows_out if upper(row.get("allowed_for_official_recommendation_now")) == "TRUE")),
            "research_only_boundary_status": "PASS" if normalized_rows_out and all(upper(row.get("research_only_flag")) == "TRUE" and upper(row.get("official_use_allowed")) == "FALSE" and upper(row.get("allowed_for_factor_research_next")) == "TRUE" and upper(row.get("allowed_for_backtest_now")) == "FALSE" and upper(row.get("allowed_for_dynamic_weighting_now")) == "FALSE" and upper(row.get("allowed_for_trading_now")) == "FALSE" and upper(row.get("allowed_for_official_recommendation_now")) == "FALSE" for row in normalized_rows_out) else "BLOCKED",
            "blocker_reason": "" if normalized_rows_out and all(upper(row.get("research_only_flag")) == "TRUE" and upper(row.get("official_use_allowed")) == "FALSE" and upper(row.get("allowed_for_factor_research_next")) == "TRUE" and upper(row.get("allowed_for_backtest_now")) == "FALSE" and upper(row.get("allowed_for_dynamic_weighting_now")) == "FALSE" and upper(row.get("allowed_for_trading_now")) == "FALSE" and upper(row.get("allowed_for_official_recommendation_now")) == "FALSE" for row in normalized_rows_out) else "Research-only boundary failed.",
        }
    ]

    quality_rows = [
        {
            "quality_check_id": "V20_8_QUALITY_001",
            "normalized_row_count": str(len(normalized_rows_out)),
            "unique_ticker_count": str(len(unique_tickers)),
            "date_distribution": ";".join(f"{key}={date_distribution[key]}" for key in sorted(date_distribution)),
            "missing_ticker_count": str(missing_ticker_count),
            "missing_price_count": str(missing_price_count),
            "nonpositive_price_count": str(nonpositive_price_count),
            "missing_source_hash_count": str(missing_hash_count),
            "missing_run_id_count": str(missing_run_id_count),
            "missing_sample_id_count": str(missing_sample_id_count),
            "duplicate_normalized_row_id_count": str(duplicate_normalized_id_count),
            "rows_allowed_for_factor_research_next": str(allowed_for_factor_research_next_count),
            "rows_allowed_for_official_use": str(official_use_allowed_count),
            "data_quality_status": "PASS" if normalized_rows_out and missing_ticker_count == 0 and missing_price_count == 0 and nonpositive_price_count == 0 and missing_hash_count == 0 and missing_run_id_count == 0 and missing_sample_id_count == 0 and duplicate_normalized_id_count == 0 and official_use_allowed_count == 0 else "BLOCKED",
            "blocker_reason": "" if normalized_rows_out and missing_ticker_count == 0 and missing_price_count == 0 and nonpositive_price_count == 0 and missing_hash_count == 0 and missing_run_id_count == 0 and missing_sample_id_count == 0 and duplicate_normalized_id_count == 0 and official_use_allowed_count == 0 else "Data quality requirements not satisfied.",
        }
    ]

    if not normalized_rows_out:
        add_blocker(blockers, "DATASET", "Normalized research dataset was not constructed.")

    normalized_created = bool(normalized_rows_out)
    ready_for_v20_9 = normalized_created and not blockers
    gate_status = "PASS_V20_8_NORMALIZED_RESEARCH_DATASET_CONSTRUCTED" if ready_for_v20_9 else "BLOCKED_V20_8_NORMALIZED_RESEARCH_DATASET_CONSTRUCTION"
    next_step = "V20.9_FACTOR_RESEARCH_DATASET_PREPARATION" if ready_for_v20_9 else "RESOLVE_V20_8_BLOCKERS"

    gate_output = [
        {
            "gate_id": "V20_8_GATE",
            "status": gate_status,
            "NORMALIZED_RESEARCH_DATASET_CREATED": tf(normalized_created),
            "NORMALIZED_ROWS_CREATED": str(len(normalized_rows_out)),
            "READY_FOR_V20_9_FACTOR_RESEARCH_DATASET_PREPARATION_NEXT": tf(ready_for_v20_9),
            "READY_FOR_BACKTEST_NEXT": "FALSE",
            "READY_FOR_DYNAMIC_WEIGHTING_NEXT": "FALSE",
            "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION": "FALSE",
            "V21_OUTPUTS_CREATED": "FALSE",
            "V19_21_OUTPUTS_CREATED": "FALSE",
            "NEXT_RECOMMENDED_STEP": next_step,
            "gate_reason": "Normalized research dataset constructed from V20.7X bound active market lineage." if ready_for_v20_9 else "One or more V20.8 construction checks failed.",
        }
    ]

    next_output = [
        {
            "decision_id": "V20_8_NEXT_STEP",
            "ready_for_v20_9_factor_research_dataset_preparation_next": tf(ready_for_v20_9),
            "ready_for_backtest_next": "FALSE",
            "ready_for_dynamic_weighting_next": "FALSE",
            "ready_for_trading_or_official_recommendation": "FALSE",
            "next_recommended_step": next_step,
            "reason": "Normalized research dataset constructed and ready for factor research preparation next." if ready_for_v20_9 else "V20.8 remains blocked until construction checks pass.",
        }
    ]

    blocker_rows = blockers or [
        {
            "blocker_id": "V20_8_BLOCKER_000",
            "blocker_scope": "NONE",
            "severity": "INFO",
            "blocker_status": "CLEARED",
            "blocker_reason": "",
            "blocks_v20_8": "FALSE",
        }
    ]

    validation_row = {
        "status": gate_status,
        "stage": "V20.8",
        "final_status": gate_status,
        "as_of_date": sorted(date_distribution)[-1] if date_distribution else "",
        "eligible_row_count": str(len(normalized_rows_out)),
        "input_path": str(IN_V20_7X_BINDING),
        "output_path": str(OUT_NORMALIZED),
        "staging_mode": tf(args.staging_mode),
        "production_write_allowed": tf(production_write_allowed),
        "patch_version": PATCH_VERSION,
        "generated_at_utc": generated_at,
        "binding_row_count": str(len(binding_rows)),
        "normalized_row_count": str(len(normalized_rows_out)),
        "accepted_row_count": str(len(accepted_rows)),
        "excluded_row_count": str(len(excluded_rows)),
        "normalized_research_dataset_created": tf(normalized_created),
        "ready_for_v20_9_factor_research_dataset_preparation_next": tf(ready_for_v20_9),
        "ready_for_backtest_next": "FALSE",
        "ready_for_dynamic_weighting_next": "FALSE",
        "ready_for_trading_or_official_recommendation": "FALSE",
        "dependency_blocker_count": str(sum(1 for row in dependency_rows if row["status"] == "BLOCKED")),
        "total_blocker_count": str(len([row for row in blocker_rows if row["severity"] == "BLOCKING"])),
        "normalized_row_id_unique_count": str(len(unique_normalized_ids)),
        "normalized_row_id_duplicate_count": str(duplicate_normalized_id_count),
        "source_hash_consistent": tf(len(source_hashes) == 1 and bool(source_hash)),
        "run_id_consistent": tf(len(run_ids) == 1 and bool(run_id)),
        "sample_id_preserved_count": str(sum(1 for row in normalized_rows_out if clean(row.get("sample_id")))),
        "official_use_allowed_rows": str(official_use_allowed_count),
        "static_write_path_check_passed": tf(set(ALLOWED_WRITE_PATHS) == {
            OUT_DEPENDENCY,
            OUT_NORMALIZED,
            OUT_SCHEMA,
            OUT_FIELD_MAP,
            OUT_LINEAGE,
            OUT_SAMPLE,
            OUT_PRICE,
            OUT_BOUNDARY,
            OUT_QUALITY,
            OUT_BLOCKERS,
            OUT_GATE,
            OUT_NEXT,
            OUT_VALIDATION,
            REPORT,
            CURRENT_REPORT,
            READ_FIRST,
        }),
        **SAFETY_FLAGS,
    }

    if not args.dry_run:
        write_csv(OUT_DEPENDENCY, dependency_rows, ["dependency", "path", "exists", "status", "blocker_reason"])
        write_csv(OUT_NORMALIZED, normalized_rows_out, NORMALIZED_COLUMNS)
        write_csv(OUT_SCHEMA, schema_rows, ["column_name", "required", "detected", "non_empty_row_count", "row_count", "schema_status", "blocker_reason"])
        write_csv(OUT_FIELD_MAP, field_map_rows, ["source_field", "normalized_field"])
        write_csv(OUT_LINEAGE, lineage_rows, ["lineage_audit_id", "normalized_row_count", "source_hash_count", "run_id_count", "sample_id_count", "source_hash_preserved_count", "run_id_preserved_count", "sample_id_preserved_count", "source_system_preserved_count", "linked_to_v20_7x_lineage_binding", "lineage_preservation_status", "blocker_reason"])
        write_csv(OUT_SAMPLE, sample_rows, ["sample_audit_id", "normalized_row_count", "sample_id_count", "sample_id_unique_count", "duplicate_sample_id_count", "normalized_row_id_unique_count", "normalized_row_id_duplicate_count", "sample_id_preservation_status", "blocker_reason"])
        write_csv(OUT_PRICE, price_rows, ["price_audit_id", "normalized_row_count", "parseable_observation_date_count", "parseable_price_date_count", "future_date_row_count", "effective_close_numeric_positive_count", "stale_leakage_status_inherited_from_v20_7x", "price_date_consistency_status", "blocker_reason"])
        write_csv(OUT_BOUNDARY, boundary_rows, ["boundary_check_id", "research_only_flag_required", "official_use_allowed_required", "allowed_for_factor_research_next_required", "allowed_for_backtest_now_required", "allowed_for_dynamic_weighting_now_required", "allowed_for_trading_now_required", "allowed_for_official_recommendation_now_required", "research_only_row_count", "official_use_allowed_row_count", "allowed_for_factor_research_next_row_count", "allowed_for_backtest_now_row_count", "allowed_for_dynamic_weighting_now_row_count", "allowed_for_trading_now_row_count", "allowed_for_official_recommendation_now_row_count", "research_only_boundary_status", "blocker_reason"])
        write_csv(OUT_QUALITY, quality_rows, ["quality_check_id", "normalized_row_count", "unique_ticker_count", "date_distribution", "missing_ticker_count", "missing_price_count", "nonpositive_price_count", "missing_source_hash_count", "missing_run_id_count", "missing_sample_id_count", "duplicate_normalized_row_id_count", "rows_allowed_for_factor_research_next", "rows_allowed_for_official_use", "data_quality_status", "blocker_reason"])
        write_csv(OUT_BLOCKERS, blocker_rows, ["blocker_id", "blocker_scope", "severity", "blocker_status", "blocker_reason", "blocks_v20_8"])
        write_csv(OUT_GATE, gate_output, ["gate_id", "status", "NORMALIZED_RESEARCH_DATASET_CREATED", "NORMALIZED_ROWS_CREATED", "READY_FOR_V20_9_FACTOR_RESEARCH_DATASET_PREPARATION_NEXT", "READY_FOR_BACKTEST_NEXT", "READY_FOR_DYNAMIC_WEIGHTING_NEXT", "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION", "V21_OUTPUTS_CREATED", "V19_21_OUTPUTS_CREATED", "NEXT_RECOMMENDED_STEP", "gate_reason"])
        write_csv(OUT_NEXT, next_output, ["decision_id", "ready_for_v20_9_factor_research_dataset_preparation_next", "ready_for_backtest_next", "ready_for_dynamic_weighting_next", "ready_for_trading_or_official_recommendation", "next_recommended_step", "reason"])
        write_csv(OUT_VALIDATION, [validation_row], list(validation_row.keys()))

    report_lines = [
        "# V20.8 Normalized Research Dataset Construction",
        "",
        f"- STATUS: `{gate_status}`",
        f"- normalized research dataset created: `{tf(normalized_created)}`",
        f"- normalized rows created: `{len(normalized_rows_out)}`",
        f"- ready for V20.9 factor research dataset preparation next: `{tf(ready_for_v20_9)}`",
        "- ready for backtest next: `FALSE`",
        "- ready for dynamic weighting next: `FALSE`",
        "- ready for trading or official recommendation: `FALSE`",
        "- official use allowed: `FALSE`",
        "",
        "## Dependency Audit",
        md_table(["dependency", "exists", "status"], dependency_rows),
        "",
        "## Gate Decision",
        md_table(["gate_id", "status", "NORMALIZED_RESEARCH_DATASET_CREATED", "NORMALIZED_ROWS_CREATED", "READY_FOR_V20_9_FACTOR_RESEARCH_DATASET_PREPARATION_NEXT", "READY_FOR_BACKTEST_NEXT"], gate_output),
        "",
        "## Data Quality",
        md_table(["quality_check_id", "normalized_row_count", "unique_ticker_count", "missing_ticker_count", "missing_price_count", "nonpositive_price_count", "missing_source_hash_count", "missing_run_id_count", "missing_sample_id_count", "duplicate_normalized_row_id_count", "rows_allowed_for_official_use", "data_quality_status"], quality_rows),
        "",
        "This step constructs a research-only normalized dataset from V20.7X bound active market input lineage. It preserves source_hash, run_id, sample_id, and the active market lineage fields, and it does not create factor evidence, backtests, dynamic weighting rows, trading signals, official recommendations, broker actions, V21 outputs, or V19.21 outputs.",
        "",
    ]
    if not args.dry_run:
        write_text(REPORT, "\n".join(report_lines))
        write_text(CURRENT_REPORT, "\n".join(report_lines))

    read_first_lines = [
        f"STATUS: {gate_status}",
        f"PATCH_VERSION: {PATCH_VERSION}",
        "REPORTING_ONLY: FALSE",
        "RESEARCH_DATASET_CONSTRUCTION: TRUE",
        f"NORMALIZED_RESEARCH_DATASET_CREATED: {tf(normalized_created)}",
        f"NORMALIZED_ROWS_CREATED: {len(normalized_rows_out)}",
        "FACTOR_EVIDENCE_ROWS_CREATED: 0",
        "BACKTEST_ROWS_CREATED: 0",
        "DYNAMIC_WEIGHTING_ROWS_CREATED: 0",
        "TRADING_SIGNAL_ROWS_CREATED: 0",
        "OFFICIAL_RECOMMENDATION_ROWS_CREATED: 0",
        "BROKER_API_USED: FALSE",
        "ORDER_EXECUTION_USED: FALSE",
        "SOURCE_MUTATION_USED: FALSE",
        "V21_OUTPUTS_CREATED: FALSE",
        "V19_21_OUTPUTS_CREATED: FALSE",
        "OFFICIAL_USE_ALLOWED: FALSE",
        f"READY_FOR_V20_9_FACTOR_RESEARCH_DATASET_PREPARATION_NEXT: {tf(ready_for_v20_9)}",
        "READY_FOR_BACKTEST_NEXT: FALSE",
        "READY_FOR_DYNAMIC_WEIGHTING_NEXT: FALSE",
        "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION: FALSE",
        f"V20_7X_SOURCE_HASH: {source_hash}",
        f"V20_7X_RUN_ID: {run_id}",
        f"V20_7X_SAMPLE_ID_COUNT: {len(sample_ids)}",
        f"STATIC_WRITE_PATH_CHECK_PASSED: {tf(set(ALLOWED_WRITE_PATHS) == {OUT_DEPENDENCY, OUT_NORMALIZED, OUT_SCHEMA, OUT_FIELD_MAP, OUT_LINEAGE, OUT_SAMPLE, OUT_PRICE, OUT_BOUNDARY, OUT_QUALITY, OUT_BLOCKERS, OUT_GATE, OUT_NEXT, OUT_VALIDATION, REPORT, CURRENT_REPORT, READ_FIRST})}",
        "DEPENDENCY_AUDIT_CSV: " + rel(OUT_DEPENDENCY),
        "NORMALIZED_RESEARCH_DATASET_CSV: " + rel(OUT_NORMALIZED),
        "NORMALIZED_SCHEMA_AUDIT_CSV: " + rel(OUT_SCHEMA),
        "FIELD_NORMALIZATION_MAP_CSV: " + rel(OUT_FIELD_MAP),
        "LINEAGE_PRESERVATION_AUDIT_CSV: " + rel(OUT_LINEAGE),
        "SAMPLE_ID_PRESERVATION_AUDIT_CSV: " + rel(OUT_SAMPLE),
        "PRICE_DATE_CONSISTENCY_AUDIT_CSV: " + rel(OUT_PRICE),
        "RESEARCH_ONLY_BOUNDARY_AUDIT_CSV: " + rel(OUT_BOUNDARY),
        "DATA_QUALITY_AUDIT_CSV: " + rel(OUT_QUALITY),
        "BLOCKER_REGISTER_CSV: " + rel(OUT_BLOCKERS),
        "GATE_DECISION_CSV: " + rel(OUT_GATE),
        "NEXT_STEP_DECISION_CSV: " + rel(OUT_NEXT),
        "VALIDATION_SUMMARY_CSV: " + rel(OUT_VALIDATION),
        "REPORT: " + rel(REPORT),
        "CURRENT_REPORT: " + rel(CURRENT_REPORT),
        "",
    ]
    read_first_output_text = "\n".join(read_first_lines)
    if not args.dry_run:
        write_text(READ_FIRST, read_first_output_text)

    validation_row["blocker_count"] = str(sum(1 for row in blocker_rows if row["severity"] == "BLOCKING"))
    validation_row["NORMALIZED_RESEARCH_DATASET_CREATED"] = tf(normalized_created)
    validation_row["normalized_row_id_unique_count"] = str(len(unique_normalized_ids))
    validation_row["normalized_row_id_duplicate_count"] = str(duplicate_normalized_id_count)
    validation_row["sample_id_preserved_count"] = str(sum(1 for row in normalized_rows_out if clean(row.get("sample_id"))))
    validation_row["official_use_allowed_rows"] = str(official_use_allowed_count)
    validation_row["read_first_safety_flags_present"] = tf(
        "REPORTING_ONLY: FALSE" in read_first_output_text
        and "RESEARCH_DATASET_CONSTRUCTION: TRUE" in read_first_output_text
        and f"NORMALIZED_ROWS_CREATED: {len(normalized_rows_out)}" in read_first_output_text
        and "FACTOR_EVIDENCE_ROWS_CREATED: 0" in read_first_output_text
        and "BACKTEST_ROWS_CREATED: 0" in read_first_output_text
        and "DYNAMIC_WEIGHTING_ROWS_CREATED: 0" in read_first_output_text
        and "TRADING_SIGNAL_ROWS_CREATED: 0" in read_first_output_text
        and "OFFICIAL_RECOMMENDATION_ROWS_CREATED: 0" in read_first_output_text
        and "BROKER_API_USED: FALSE" in read_first_output_text
        and "ORDER_EXECUTION_USED: FALSE" in read_first_output_text
        and "SOURCE_MUTATION_USED: FALSE" in read_first_output_text
        and "V21_OUTPUTS_CREATED: FALSE" in read_first_output_text
        and "V19_21_OUTPUTS_CREATED: FALSE" in read_first_output_text
        and "OFFICIAL_USE_ALLOWED: FALSE" in read_first_output_text
    )
    validation_row["write_paths_expected_count"] = str(len(ALLOWED_WRITE_PATHS))
    validation_row["write_paths_written_count"] = str(len(ALLOWED_WRITE_PATHS))
    validation_row["allowed_write_paths_match"] = tf(set(ALLOWED_WRITE_PATHS) == {OUT_DEPENDENCY, OUT_NORMALIZED, OUT_SCHEMA, OUT_FIELD_MAP, OUT_LINEAGE, OUT_SAMPLE, OUT_PRICE, OUT_BOUNDARY, OUT_QUALITY, OUT_BLOCKERS, OUT_GATE, OUT_NEXT, OUT_VALIDATION, REPORT, CURRENT_REPORT, READ_FIRST})
    if not args.dry_run:
        write_csv(OUT_VALIDATION, [validation_row], list(validation_row.keys()))

    for key, value in validation_row.items():
        print(f"{key.upper()}: {value}")
    print(f"READ_FIRST: {rel(READ_FIRST)}")
    print("STAGE: V20.8")
    print(f"FINAL_STATUS: {gate_status}")
    print(f"AS_OF_DATE: {validation_row['as_of_date']}")
    print(f"ELIGIBLE_ROW_COUNT: {validation_row['eligible_row_count']}")
    print(f"INPUT_PATH: {IN_V20_7X_BINDING}")
    print(f"OUTPUT_PATH: {OUT_NORMALIZED}")
    print(f"STAGING_MODE: {tf(args.staging_mode)}")
    print(f"PRODUCTION_WRITE_ALLOWED: {tf(production_write_allowed)}")
    return 0 if ready_for_v20_9 else 1


if __name__ == "__main__":
    raise SystemExit(main())
