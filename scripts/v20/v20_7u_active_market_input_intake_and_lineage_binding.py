from __future__ import annotations

import csv
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = ROOT / "inputs" / "v20" / "active_market" / "V20_ACTIVE_MARKET_INPUT.csv"

OPS = ROOT / "outputs" / "v20" / "ops"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

V20_7S_VALIDATION = CONSOLIDATION / "V20_7S_VALIDATION_SUMMARY.csv"
V20_7S_READ_FIRST = OPS / "V20_7S_READ_FIRST.txt"
V20_7T_VALIDATION = CONSOLIDATION / "V20_7T_VALIDATION_SUMMARY.csv"
V20_7T_READ_FIRST = OPS / "V20_7T_READ_FIRST.txt"

OUT_DISCOVERY = CONSOLIDATION / "V20_7U_ACTIVE_MARKET_INPUT_DISCOVERY.csv"
OUT_FIELD_VALIDATION = CONSOLIDATION / "V20_7U_ACTIVE_MARKET_INPUT_FIELD_VALIDATION.csv"
OUT_LINEAGE_BINDING = CONSOLIDATION / "V20_7U_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv"
OUT_SAMPLE_LEDGER = CONSOLIDATION / "V20_7U_ACTIVE_MARKET_INPUT_SAMPLE_ID_LEDGER.csv"
OUT_MANIFEST = CONSOLIDATION / "V20_7U_ACTIVE_MARKET_INPUT_REGISTERED_MANIFEST.csv"
OUT_TEMPLATE = CONSOLIDATION / "V20_7U_ACTIVE_MARKET_INPUT_TEMPLATE.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_7U_INTAKE_BLOCKER_REGISTER.csv"
OUT_NEXT = CONSOLIDATION / "V20_7U_NEXT_CERTIFICATION_RETRY_REQUIREMENTS.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_7U_VALIDATION_SUMMARY.csv"

REPORT = READ_CENTER / "V20_7U_ACTIVE_MARKET_INPUT_INTAKE_REPORT.md"
CURRENT_STATUS = READ_CENTER / "V20_CURRENT_ACTIVE_MARKET_INPUT_INTAKE_STATUS.md"
READ_FIRST = OPS / "V20_7U_READ_FIRST.txt"

INPUT_REQUIRED_FIELDS = {
    "ticker": ("ticker",),
    "observation_or_signal_date": ("observation_date", "signal_date"),
    "price_date": ("price_date", "latest_price_date"),
    "latest_close": ("latest_close", "close"),
    "active_runtime_flag": ("active_runtime_flag",),
    "historical_reference_flag": ("historical_reference_flag",),
    "availability_or_created_at_utc": ("availability_date", "created_at_utc"),
}

OUTPUT_FIELD_NAMES = [
    "ticker",
    "observation_date",
    "signal_date",
    "price_date",
    "latest_price_date",
    "latest_close",
    "close",
    "active_runtime_flag",
    "historical_reference_flag",
    "availability_date",
    "created_at_utc",
    "company_name",
    "source_artifact_id",
    "source_hash",
    "run_id",
    "sample_id",
]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def tf(value: bool) -> str:
    return "TRUE" if bool(value) else "FALSE"


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))
    except Exception:
        return []


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def norm(value: str | None) -> str:
    return (value or "").strip()


def first_present(row: dict[str, str], options: tuple[str, ...]) -> str:
    for option in options:
        value = norm(row.get(option))
        if value:
            return value
    return ""


def first_header(headers: set[str], options: tuple[str, ...]) -> str:
    for option in options:
        if option in headers:
            return option
    return ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_date_token(value: str) -> str:
    value = norm(value)
    if not value:
        return ""
    candidate = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(candidate)
        return dt.strftime("%Y%m%d")
    except Exception:
        pass
    digits = re.sub(r"[^0-9]", "", value)
    if len(digits) >= 8:
        return digits[:8]
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value)
    return cleaned.upper()


def short_hash(source_hash: str) -> str:
    return source_hash[:12] if source_hash else "NOHASH"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_stamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def compact_stamp(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def escape_md(value: str) -> str:
    return value.replace("|", "\\|")


def md_table(headers: list[str], rows: list[dict[str, str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(escape_md(row.get(h, "")) for h in headers) + " |")
    return "\n".join(lines)


def dependency_state(validation_path: Path, read_first_path: Path, dependency_key: str) -> tuple[bool, bool]:
    detected = validation_path.exists() or read_first_path.exists()
    accepted = False
    if validation_path.exists():
        rows = read_csv_rows(validation_path)
        if rows:
            row = rows[0]
            if norm(row.get("safety_status")).upper() == "PASS":
                accepted = True
            if dependency_key in row and norm(row.get(dependency_key)).upper() == "TRUE":
                accepted = accepted or True
    if read_first_path.exists():
        body = read_text(read_first_path)
        if f"{dependency_key.upper()}: TRUE" in body or "SAFETY_STATUS: PASS" in body:
            accepted = True
    return detected, accepted


def collect_headers(rows: list[dict[str, str]]) -> set[str]:
    headers: set[str] = set()
    for row in rows:
        for key in row.keys():
            headers.add((key or "").strip())
    return headers


def build_template_rows() -> list[dict[str, str]]:
    return [
        {
            "ticker": "TEMPLATE_TICKER",
            "observation_date": "YYYY-MM-DD",
            "signal_date": "",
            "price_date": "YYYY-MM-DD",
            "latest_price_date": "",
            "latest_close": "0.00",
            "close": "",
            "active_runtime_flag": "TRUE",
            "historical_reference_flag": "FALSE",
            "availability_date": "YYYY-MM-DDTHH:MM:SSZ",
            "created_at_utc": "",
            "company_name": "Example Company",
            "source_artifact_id": "V20_ACTIVE_MARKET_INPUT_YYYYMMDD",
            "source_hash": "",
            "run_id": "V20_7U_INTAKE_RUN_ID",
            "sample_id": "TEMPLATE_TICKER_YYYYMMDD_V20_ACTIVE_MARKET_INPUT_YYYYMMDD_NOHASH_V20_7U_INTAKE_RUN_ID",
        }
    ]


def build_field_validation_rows(headers: set[str], input_exists: bool, row_count: int, generated: dict[str, str], all_active: bool, all_historical_false: bool) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for idx, (field_type, accepted_fields) in enumerate(INPUT_REQUIRED_FIELDS.items(), start=1):
        detected = first_header(headers, accepted_fields)
        if field_type == "active_runtime_flag":
            field_ok = all_active
        elif field_type == "historical_reference_flag":
            field_ok = all_historical_false
        elif field_type == "observation_or_signal_date":
            field_ok = bool(first_header(headers, accepted_fields))
        else:
            field_ok = bool(detected)
        blocker = ""
        if not input_exists:
            blocker = "No active market input file exists at the configured intake path."
        elif not field_ok:
            if field_type == "active_runtime_flag":
                blocker = "active_runtime_flag must be TRUE for every certifiable row."
            elif field_type == "historical_reference_flag":
                blocker = "historical_reference_flag must be FALSE for every certifiable row."
            else:
                blocker = f"Missing required field group: {field_type}."
        rows.append(
            {
                "validation_id": f"VAL-{idx:02d}",
                "required_field_type": field_type,
                "accepted_field_names": ";".join(accepted_fields),
                "detected_field_name": detected if detected else (generated.get(field_type, "") if field_type in generated else ""),
                "field_present": tf(field_ok),
                "row_level_validity_status": "PASS" if field_ok and input_exists else "BLOCKED",
                "required_before_certification_retry": "TRUE",
                "blocker_reason": blocker,
            }
        )

    generated_specs = [
        ("source_artifact_id", "source_artifact_id"),
        ("source_hash", "source_hash"),
        ("run_id", "run_id"),
        ("sample_id", "sample_id"),
    ]
    for offset, (field_type, detected_name) in enumerate(generated_specs, start=len(rows) + 1):
        value_present = bool(norm(generated.get(field_type)))
        blocker = ""
        if not input_exists:
            blocker = "No active market input file exists; generated intake metadata is unavailable."
        elif not value_present:
            blocker = f"Unable to generate {field_type} from the current intake file."
        rows.append(
            {
                "validation_id": f"VAL-{offset:02d}",
                "required_field_type": field_type,
                "accepted_field_names": field_type,
                "detected_field_name": detected_name if value_present else "",
                "field_present": tf(value_present),
                "row_level_validity_status": "PASS" if value_present and input_exists else "BLOCKED",
                "required_before_certification_retry": "TRUE",
                "blocker_reason": blocker,
            }
        )
    return rows


def validate_input_rows(rows: list[dict[str, str]]) -> tuple[bool, bool, list[str], list[str], list[str]]:
    headers = collect_headers(rows)
    issues: list[str] = []
    missing_groups: list[str] = []
    detected_columns = sorted(headers)
    all_active = True
    all_historical_false = True
    if not rows:
        return False, False, issues, missing_groups, detected_columns

    for field_type, accepted_fields in INPUT_REQUIRED_FIELDS.items():
        if not first_header(headers, accepted_fields):
            missing_groups.append(field_type)
            issues.append(f"Missing required field group: {field_type}.")

    for row in rows:
        active = norm(row.get("active_runtime_flag")).upper()
        historical = norm(row.get("historical_reference_flag")).upper()
        if active != "TRUE":
            all_active = False
            issues.append("active_runtime_flag must be TRUE for every row.")
        if historical != "FALSE":
            all_historical_false = False
            issues.append("historical_reference_flag must be FALSE for every row.")
        if not first_present(row, INPUT_REQUIRED_FIELDS["ticker"]):
            issues.append("ticker is missing for at least one row.")
        if not first_present(row, INPUT_REQUIRED_FIELDS["observation_or_signal_date"]):
            issues.append("observation_date or signal_date is missing for at least one row.")
        if not first_present(row, INPUT_REQUIRED_FIELDS["price_date"]):
            issues.append("price_date or latest_price_date is missing for at least one row.")
        if not first_present(row, INPUT_REQUIRED_FIELDS["latest_close"]):
            issues.append("latest_close or close is missing for at least one row.")
        if not first_present(row, INPUT_REQUIRED_FIELDS["availability_or_created_at_utc"]):
            issues.append("availability_date or created_at_utc is missing for at least one row.")

    return all_active, all_historical_false, issues, missing_groups, detected_columns


def choose_source_artifact_id(rows: list[dict[str, str]]) -> str:
    for row in rows:
        token = first_present(row, INPUT_REQUIRED_FIELDS["observation_or_signal_date"])
        date_token = normalize_date_token(token)
        if date_token:
            return f"V20_ACTIVE_MARKET_INPUT_{date_token}"
    return "V20_ACTIVE_MARKET_INPUT_UNDATED"


def build_generated_values(rows: list[dict[str, str]], source_artifact_id: str, source_hash: str, run_id: str) -> list[dict[str, str]]:
    output_rows: list[dict[str, str]] = []
    for row in rows:
        ticker = first_present(row, INPUT_REQUIRED_FIELDS["ticker"]) or "UNKNOWN_TICKER"
        date_token = normalize_date_token(first_present(row, INPUT_REQUIRED_FIELDS["observation_or_signal_date"])) or "UNKNOWN_DATE"
        source_id = norm(row.get("source_artifact_id")) or source_artifact_id
        row_source_hash = norm(row.get("source_hash")) or source_hash
        row_run_id = norm(row.get("run_id")) or run_id
        sample_id = norm(row.get("sample_id"))
        if not sample_id:
            sample_id = f"{ticker}_{date_token}_{source_id}_{short_hash(row_source_hash)}_{row_run_id}"
        output_rows.append(
            {
                "ticker": ticker,
                "observation_date": first_present(row, ("observation_date",)),
                "signal_date": first_present(row, ("signal_date",)),
                "price_date": first_present(row, ("price_date",)),
                "latest_price_date": first_present(row, ("latest_price_date",)),
                "latest_close": first_present(row, ("latest_close",)),
                "close": first_present(row, ("close",)),
                "active_runtime_flag": norm(row.get("active_runtime_flag")),
                "historical_reference_flag": norm(row.get("historical_reference_flag")),
                "availability_date": first_present(row, ("availability_date",)),
                "created_at_utc": first_present(row, ("created_at_utc",)),
                "company_name": first_present(row, ("company_name",)),
                "source_artifact_id": source_id,
                "source_hash": row_source_hash,
                "run_id": row_run_id,
                "sample_id": sample_id,
            }
        )
    if not output_rows:
        output_rows.append(
            {
                "ticker": "",
                "observation_date": "",
                "signal_date": "",
                "price_date": "",
                "latest_price_date": "",
                "latest_close": "",
                "close": "",
                "active_runtime_flag": "",
                "historical_reference_flag": "",
                "availability_date": "",
                "created_at_utc": "",
                "company_name": "",
                "source_artifact_id": "",
                "source_hash": "",
                "run_id": "",
                "sample_id": "",
            }
        )
    return output_rows


def build_lineage_binding_row(
    input_exists: bool,
    ready: bool,
    source_artifact_id: str,
    source_hash: str,
    run_id: str,
    run_timestamp_utc: str,
    all_active: bool,
    all_historical_false: bool,
    blocker_reason: str,
) -> list[dict[str, str]]:
    return [
        {
            "binding_id": f"BIND-{source_artifact_id}" if source_artifact_id else "BIND-NO-INPUT",
            "input_path": str(INPUT_PATH.relative_to(ROOT)).replace("\\", "/"),
            "source_artifact_id": source_artifact_id if input_exists else "",
            "source_hash": source_hash if input_exists else "",
            "hash_algorithm": "sha256" if input_exists else "",
            "hash_computed_now": tf(input_exists),
            "run_id": run_id if input_exists else "",
            "run_timestamp_utc": run_timestamp_utc if input_exists else "",
            "active_runtime_flag_valid": tf(all_active and input_exists),
            "historical_reference_flag_valid": tf(all_historical_false and input_exists),
            "lineage_binding_status": "PASS" if ready else "BLOCKED",
            "blocker_reason": blocker_reason,
        }
    ]


def build_discovery_row(input_exists: bool, row_count: int, detected_columns: list[str], ready: bool, blocker_reason: str) -> list[dict[str, str]]:
    return [
        {
            "discovery_id": "DISC-V20-7U-INPUT",
            "input_path": str(INPUT_PATH.relative_to(ROOT)).replace("\\", "/"),
            "path_exists_now": tf(input_exists),
            "row_count": str(row_count if input_exists else 0),
            "detected_columns": ";".join(detected_columns) if input_exists else "",
            "discovered_status": "READY_FOR_RETRY_CERTIFICATION" if ready else ("INPUT_FOUND_BUT_BLOCKED" if input_exists else "INPUT_MISSING"),
            "blocker_reason": blocker_reason,
        }
    ]


def build_sample_ledger_rows(
    source_rows: list[dict[str, str]],
    generated_rows: list[dict[str, str]],
    source_artifact_id: str,
    source_hash: str,
    run_id: str,
    input_exists: bool,
    blocker_reason: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for idx, generated in enumerate(generated_rows, start=1):
        source_row = source_rows[idx - 1] if idx - 1 < len(source_rows) else {}
        sample_id = norm(generated.get("sample_id"))
        created_now = sample_id != norm(source_row.get("sample_id"))
        rows.append(
            {
                "sample_id": sample_id,
                "ticker": norm(generated.get("ticker")),
                "observation_or_signal_date": first_present(source_row, INPUT_REQUIRED_FIELDS["observation_or_signal_date"]),
                "source_artifact_id": source_artifact_id if input_exists else "",
                "source_hash": source_hash if input_exists else "",
                "run_id": run_id if input_exists else "",
                "sample_id_created_now": tf(created_now and input_exists),
                "sample_id_status": "PASS" if input_exists else "BLOCKED_NO_INPUT",
                "blocker_reason": blocker_reason if not input_exists else "",
            }
        )
    if not rows:
        rows.append(
            {
                "sample_id": "",
                "ticker": "",
                "observation_or_signal_date": "",
                "source_artifact_id": "",
                "source_hash": "",
                "run_id": "",
                "sample_id_created_now": "FALSE",
                "sample_id_status": "BLOCKED_NO_INPUT",
                "blocker_reason": blocker_reason,
            }
        )
    return rows


def build_manifest_rows(
    input_exists: bool,
    row_count: int,
    source_artifact_id: str,
    source_hash: str,
    run_id: str,
    all_active: bool,
    all_historical_false: bool,
    ready: bool,
    blocker_reason: str,
) -> list[dict[str, str]]:
    return [
        {
            "source_artifact_id": source_artifact_id if input_exists else "",
            "source_name": INPUT_PATH.name,
            "source_category": "ACTIVE_MARKET_INPUT",
            "canonical_path": str(INPUT_PATH.relative_to(ROOT)).replace("\\", "/"),
            "source_hash": source_hash if input_exists else "",
            "run_id": run_id if input_exists else "",
            "active_runtime_flag": tf(all_active and input_exists),
            "historical_reference_flag": tf(input_exists and not all_historical_false),
            "row_count": str(row_count if input_exists else 0),
            "usable_for_certification_retry": tf(ready),
            "usable_for_v20_8": "FALSE",
            "blocker_reason": blocker_reason if not ready else "",
        }
    ]


def build_blocker_rows(input_exists: bool, ready: bool, issues: list[str], blocker_reason: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if ready:
        rows.append(
            {
                "blocker_id": "BLK-V20U-000",
                "blocker_class": "NONE",
                "blocker_status": "CLEARED",
                "blocker_reason": "",
            }
        )
        return rows
    if not input_exists:
        rows.append(
            {
                "blocker_id": "BLK-V20U-001",
                "blocker_class": "MISSING_ACTIVE_RUNTIME_INPUT",
                "blocker_status": "BLOCKED",
                "blocker_reason": blocker_reason,
            }
        )
        return rows
    unique_issues = []
    seen = set()
    for issue in issues:
        if issue not in seen:
            seen.add(issue)
            unique_issues.append(issue)
    for idx, issue in enumerate(unique_issues or [blocker_reason], start=1):
        rows.append(
            {
                "blocker_id": f"BLK-V20U-{idx:03d}",
                "blocker_class": "INPUT_VALIDATION_BLOCKER",
                "blocker_status": "BLOCKED",
                "blocker_reason": issue,
            }
        )
    return rows


def build_next_requirements(input_exists: bool, ready: bool, blocker_reason: str) -> list[dict[str, str]]:
    if ready:
        return [
            {
                "requirement_id": "REQ-01",
                "requirement_name": "Retry V20.7S source certification using the registered active market input manifest",
                "source_of_truth": "V20.7U intake gate",
                "current_status": "READY_FOR_RETRY",
                "blocker_reason": "",
            },
            {
                "requirement_id": "REQ-02",
                "requirement_name": "Preserve sealed V18/V19 baselines and keep V20.8 blocked until certification succeeds",
                "source_of_truth": "V20 sealed baseline policy",
                "current_status": "READY_FOR_RETRY",
                "blocker_reason": "",
            },
        ]
    return [
        {
            "requirement_id": "REQ-01",
            "requirement_name": "Create or place a non-historical active market-input CSV at inputs/v20/active_market/V20_ACTIVE_MARKET_INPUT.csv",
            "source_of_truth": "V20.7U intake gate",
            "current_status": "BLOCKED" if not input_exists else "NEEDS_FIX",
            "blocker_reason": blocker_reason,
        },
        {
            "requirement_id": "REQ-02",
            "requirement_name": "Validate required field coverage and lineage flags before retrying V20.7S",
            "source_of_truth": "V20.7U field validation and lineage binding",
            "current_status": "BLOCKED" if not input_exists else "NEEDS_FIX",
            "blocker_reason": blocker_reason,
        },
        {
            "requirement_id": "REQ-03",
            "requirement_name": "Keep READY_FOR_STALE_LEAKAGE_PIT_RETRY_NEXT and V20.8 blocked until certification passes",
            "source_of_truth": "V20.7U gate policy",
            "current_status": "BLOCKED",
            "blocker_reason": "V20.7S retry certification has not passed.",
        },
    ]


def build_read_first(
    intake_ready: bool,
    input_exists: bool,
    row_count: int,
    t_detected: bool,
    t_accepted: bool,
    s_detected: bool,
    s_accepted: bool,
) -> str:
    lines = [
        "STATUS: WARN",
        "PATCH_NAME: V20.7U_ACTIVE_MARKET_INPUT_INTAKE_AND_LINEAGE_BINDING",
        "REPORTING_ONLY: TRUE",
        "ACTIVE_MARKET_INPUT_INTAKE_ONLY: TRUE",
        "ACTIVE_MARKET_INPUT_INTAKE_EXECUTED: TRUE",
        f"ACTIVE_MARKET_INPUT_INTAKE_READY: {tf(intake_ready)}",
        "ACTIVE_MARKET_DATA_CERTIFIED: FALSE",
        "NORMALIZED_REAL_DATA_ROWS_CREATED: 0",
        "FACTOR_EVIDENCE_CREATED: FALSE",
        "OFFICIAL_TRADING_SIGNAL_CREATED: FALSE",
        "OFFICIAL_PORTFOLIO_WEIGHT_CREATED: FALSE",
        "OFFICIAL_FACTOR_WEIGHT_CHANGED: FALSE",
        "OFFICIAL_RANKING_CHANGED: FALSE",
        "OFFICIAL_BACKTEST_CREATED: FALSE",
        "EXPLORATORY_BACKTEST_CREATED: FALSE",
        "PERFORMANCE_CLAIMS_CREATED: FALSE",
        "DYNAMIC_WEIGHTING_EXECUTED: FALSE",
        "SOURCE_FILES_MUTATED: FALSE",
        "V21_STARTED: FALSE",
        "V19_21_STARTED: FALSE",
        "OFFICIAL_USE_ALLOWED: FALSE",
        f"V20_7S_DEPENDENCY_DETECTED: {tf(s_detected)}",
        f"V20_7S_DEPENDENCY_ACCEPTED: {tf(s_accepted)}",
        f"V20_7T_DEPENDENCY_DETECTED: {tf(t_detected)}",
        f"V20_7T_DEPENDENCY_ACCEPTED: {tf(t_accepted)}",
        f"INPUT_FILE_FOUND: {tf(input_exists)}",
        f"ACTIVE_MARKET_INPUT_ROW_COUNT: {row_count}",
        "READY_FOR_ACTIVE_MARKET_SOURCE_CERTIFICATION_RETRY_NEXT: " + tf(intake_ready),
        "READY_FOR_STALE_LEAKAGE_PIT_RETRY_NEXT: FALSE",
        "READY_FOR_NORMALIZED_RESEARCH_DATASET_NEXT: FALSE",
        "READY_FOR_FACTOR_EVIDENCE_NEXT: FALSE",
        "READY_FOR_EXPLORATORY_BACKTEST_NEXT: FALSE",
        "READY_FOR_DYNAMIC_WEIGHTING_GATE_RESEARCH_NEXT: FALSE",
        "OFFICIAL_TRADING_ALLOWED: FALSE",
        "OFFICIAL_BACKTEST_ALLOWED: FALSE",
        "SAFETY_STATUS: PASS",
        "NEXT_RECOMMENDED_ACTION: "
        + (
            "V20_7S_RETRY_ACTIVE_MARKET_DATA_SOURCE_CERTIFICATION"
            if intake_ready
            else "Create inputs/v20/active_market/V20_ACTIVE_MARKET_INPUT.csv using the generated template"
        ),
    ]
    return "\n".join(lines) + "\n"


def build_report(
    t_accepted: bool,
    s_accepted: bool,
    input_exists: bool,
    row_count: int,
    intake_ready: bool,
    blocker_reason: str,
    discovery_rows: list[dict[str, str]],
    field_rows: list[dict[str, str]],
    lineage_rows: list[dict[str, str]],
    sample_rows: list[dict[str, str]],
    manifest_rows: list[dict[str, str]],
) -> str:
    lines: list[str] = []
    lines.append("# V20.7U Active Market Input Intake and Lineage Binding")
    lines.append("")
    lines.append(f"- V20.7S dependency detected and accepted: {tf(s_accepted)}")
    lines.append(f"- V20.7T dependency detected and accepted: {tf(t_accepted)}")
    lines.append(f"- Input file found: {tf(input_exists)}")
    lines.append(f"- Active market input row count: {row_count}")
    lines.append(f"- Active market input ready: {tf(intake_ready)}")
    lines.append("- V20.8 remains blocked: TRUE")
    lines.append("")
    lines.append("## Decision")
    lines.append("")
    lines.append("- This step only performs controlled intake discovery, field validation, lineage binding, and manifest registration.")
    lines.append("- It does not create normalized research rows, factor evidence, backtests, dynamic weighting, official rankings, official weights, or trading recommendations.")
    lines.append("- V18 and V19 outputs remain sealed historical baselines and are not reclassified as active runtime inputs.")
    lines.append("")
    lines.append("## Discovery")
    lines.append("")
    lines.append(md_table(["discovery_id", "input_path", "path_exists_now", "row_count", "detected_columns", "discovered_status", "blocker_reason"], discovery_rows))
    lines.append("")
    lines.append("## Field Validation")
    lines.append("")
    lines.append(md_table(["validation_id", "required_field_type", "accepted_field_names", "detected_field_name", "field_present", "row_level_validity_status", "required_before_certification_retry", "blocker_reason"], field_rows))
    lines.append("")
    lines.append("## Lineage Binding")
    lines.append("")
    lines.append(md_table(["binding_id", "input_path", "source_artifact_id", "source_hash", "hash_algorithm", "hash_computed_now", "run_id", "run_timestamp_utc", "active_runtime_flag_valid", "historical_reference_flag_valid", "lineage_binding_status", "blocker_reason"], lineage_rows))
    lines.append("")
    lines.append("## Sample ID Ledger")
    lines.append("")
    lines.append(md_table(["sample_id", "ticker", "observation_or_signal_date", "source_artifact_id", "source_hash", "run_id", "sample_id_created_now", "sample_id_status", "blocker_reason"], sample_rows))
    lines.append("")
    lines.append("## Registered Manifest")
    lines.append("")
    lines.append(md_table(["source_artifact_id", "source_name", "source_category", "canonical_path", "source_hash", "run_id", "active_runtime_flag", "historical_reference_flag", "row_count", "usable_for_certification_retry", "usable_for_v20_8", "blocker_reason"], manifest_rows))
    lines.append("")
    lines.append("## Next Step")
    lines.append("")
    if intake_ready:
        lines.append("- Retry V20.7S source certification using the registered active market input manifest.")
        lines.append("- Keep V20.8 blocked until V20.7S retry certification passes.")
    else:
        lines.append("- Create `inputs/v20/active_market/V20_ACTIVE_MARKET_INPUT.csv` from the generated template, then rerun V20.7U.")
        lines.append(f"- Blocker reason: {blocker_reason}")
    return "\n".join(lines) + "\n"


def build_current_status(input_exists: bool, row_count: int, intake_ready: bool) -> str:
    return (
        "# V20 Current Active Market Input Intake Status\n\n"
        f"- Active market input found: {tf(input_exists)}\n"
        f"- Active market input row count: {row_count}\n"
        f"- Active market input ready: {tf(intake_ready)}\n"
        f"- V20.8 blocked: TRUE\n"
        "- Recommended next step: "
        + (
            "V20_7S_RETRY_ACTIVE_MARKET_DATA_SOURCE_CERTIFICATION"
            if intake_ready
            else "Create inputs/v20/active_market/V20_ACTIVE_MARKET_INPUT.csv using the generated template"
        )
        + "\n\nThis status file is read-only and does not alter sealed baselines or official research outputs.\n"
    )


def main() -> None:
    ensure_dir(OPS)
    ensure_dir(CONSOLIDATION)
    ensure_dir(READ_CENTER)

    s_detected, s_accepted = dependency_state(V20_7S_VALIDATION, V20_7S_READ_FIRST, "v20_7r_dependency_accepted")
    t_detected, t_accepted = dependency_state(V20_7T_VALIDATION, V20_7T_READ_FIRST, "v20_7s_dependency_accepted")

    input_exists = INPUT_PATH.exists()
    rows = read_csv_rows(INPUT_PATH)
    row_count = len(rows)
    headers = collect_headers(rows)
    all_active, all_historical_false, issues, missing_groups, detected_columns = validate_input_rows(rows)

    source_artifact_id = choose_source_artifact_id(rows) if input_exists else ""
    source_hash = sha256_file(INPUT_PATH) if input_exists else ""
    now = utc_now()
    run_timestamp_utc = utc_stamp(now)
    run_id = f"V20_7U_INTAKE_{compact_stamp(now)}"

    generated_values = {
        "source_artifact_id": source_artifact_id if input_exists else "",
        "source_hash": source_hash if input_exists else "",
        "run_id": run_id if input_exists else "",
        "sample_id": "",
    }

    generated_rows = build_generated_values(rows, source_artifact_id, source_hash, run_id) if input_exists else []
    if input_exists and generated_rows:
        generated_values["sample_id"] = generated_rows[0].get("sample_id", "")
        generated_values["run_id"] = generated_rows[0].get("run_id", "")

    ready = bool(
        input_exists
        and row_count > 0
        and not missing_groups
        and all_active
        and all_historical_false
        and bool(source_artifact_id)
        and bool(source_hash)
        and bool(run_id)
        and all(norm(row.get("ticker")) for row in rows)
        and all(first_present(row, INPUT_REQUIRED_FIELDS["observation_or_signal_date"]) for row in rows)
        and all(first_present(row, INPUT_REQUIRED_FIELDS["price_date"]) for row in rows)
        and all(first_present(row, INPUT_REQUIRED_FIELDS["latest_close"]) for row in rows)
        and all(first_present(row, INPUT_REQUIRED_FIELDS["availability_or_created_at_utc"]) for row in rows)
    )

    blocker_reason = ""
    if not input_exists:
        blocker_reason = "No active market input CSV exists at the configured intake path."
    elif row_count == 0:
        blocker_reason = "The active market input file exists but contains no data rows."
    elif missing_groups:
        blocker_reason = "Missing required field group(s): " + ", ".join(missing_groups) + "."
    elif not all_active:
        blocker_reason = "active_runtime_flag must be TRUE for every certifiable row."
    elif not all_historical_false:
        blocker_reason = "historical_reference_flag must be FALSE for every certifiable row."
    elif not issues:
        blocker_reason = "The intake file did not satisfy the certification retry checks."
    else:
        blocker_reason = issues[0]

    discovery_rows = build_discovery_row(input_exists, row_count, detected_columns, ready, blocker_reason)
    field_rows = build_field_validation_rows(headers, input_exists, row_count, generated_values, all_active, all_historical_false)
    lineage_rows = build_lineage_binding_row(input_exists, ready, source_artifact_id, source_hash, run_id, run_timestamp_utc, all_active, all_historical_false, blocker_reason)
    sample_rows = build_sample_ledger_rows(rows, generated_rows, source_artifact_id, source_hash, run_id, input_exists, blocker_reason)
    manifest_rows = build_manifest_rows(input_exists, row_count, source_artifact_id, source_hash, run_id, all_active, all_historical_false, ready, blocker_reason)
    blockers = build_blocker_rows(input_exists, ready, issues, blocker_reason)
    next_rows = build_next_requirements(input_exists, ready, blocker_reason)

    write_csv(
        OUT_DISCOVERY,
        discovery_rows,
        ["discovery_id", "input_path", "path_exists_now", "row_count", "detected_columns", "discovered_status", "blocker_reason"],
    )
    write_csv(
        OUT_FIELD_VALIDATION,
        field_rows,
        ["validation_id", "required_field_type", "accepted_field_names", "detected_field_name", "field_present", "row_level_validity_status", "required_before_certification_retry", "blocker_reason"],
    )
    write_csv(
        OUT_LINEAGE_BINDING,
        lineage_rows,
        ["binding_id", "input_path", "source_artifact_id", "source_hash", "hash_algorithm", "hash_computed_now", "run_id", "run_timestamp_utc", "active_runtime_flag_valid", "historical_reference_flag_valid", "lineage_binding_status", "blocker_reason"],
    )
    write_csv(
        OUT_SAMPLE_LEDGER,
        sample_rows,
        ["sample_id", "ticker", "observation_or_signal_date", "source_artifact_id", "source_hash", "run_id", "sample_id_created_now", "sample_id_status", "blocker_reason"],
    )
    write_csv(
        OUT_MANIFEST,
        manifest_rows,
        ["source_artifact_id", "source_name", "source_category", "canonical_path", "source_hash", "run_id", "active_runtime_flag", "historical_reference_flag", "row_count", "usable_for_certification_retry", "usable_for_v20_8", "blocker_reason"],
    )
    write_csv(OUT_TEMPLATE, build_template_rows(), OUTPUT_FIELD_NAMES)
    write_csv(OUT_BLOCKERS, blockers, ["blocker_id", "blocker_class", "blocker_status", "blocker_reason"])
    write_csv(OUT_NEXT, next_rows, ["requirement_id", "requirement_name", "source_of_truth", "current_status", "blocker_reason"])

    validation_row = {
        "required_outputs_created": "12",
        "v20_7s_dependency_detected": tf(s_detected),
        "v20_7s_dependency_accepted": tf(s_accepted),
        "v20_7t_dependency_detected": tf(t_detected),
        "v20_7t_dependency_accepted": tf(t_accepted),
        "input_file_found": tf(input_exists),
        "input_row_count": str(row_count),
        "discovery_rows": str(len(discovery_rows)),
        "field_validation_rows": str(len(field_rows)),
        "lineage_binding_rows": str(len(lineage_rows)),
        "sample_id_ledger_rows": str(len(sample_rows)),
        "registered_manifest_rows": str(len(manifest_rows)),
        "blocker_rows": str(len(blockers)),
        "active_market_input_intake_executed": "TRUE",
        "active_market_input_intake_ready": tf(ready),
        "ready_for_active_market_source_certification_retry_next": tf(ready),
        "ready_for_stale_leakage_pit_retry_next": "FALSE",
        "ready_for_normalized_research_dataset_next": "FALSE",
        "ready_for_factor_evidence_next": "FALSE",
        "ready_for_exploratory_backtest_next": "FALSE",
        "ready_for_dynamic_weighting_gate_research_next": "FALSE",
        "official_trading_allowed": "FALSE",
        "official_backtest_allowed": "FALSE",
        "normalized_real_data_rows_created": "0",
        "factor_evidence_created": "FALSE",
        "official_trading_signal_created": "FALSE",
        "official_portfolio_weight_created": "FALSE",
        "official_factor_weight_changed": "FALSE",
        "official_ranking_changed": "FALSE",
        "official_backtest_created": "FALSE",
        "exploratory_backtest_created": "FALSE",
        "performance_claims_created": "FALSE",
        "dynamic_weighting_executed": "FALSE",
        "source_files_mutated": "FALSE",
        "v21_started": "FALSE",
        "v19_21_started": "FALSE",
        "safety_status": "PASS",
    }
    write_csv(
        OUT_VALIDATION,
        [validation_row],
        list(validation_row.keys()),
    )

    write_text(READ_FIRST, build_read_first(ready, input_exists, row_count, t_detected, t_accepted, s_detected, s_accepted))
    write_text(REPORT, build_report(t_accepted, s_accepted, input_exists, row_count, ready, blocker_reason, discovery_rows, field_rows, lineage_rows, sample_rows, manifest_rows))
    write_text(CURRENT_STATUS, build_current_status(input_exists, row_count, ready))


if __name__ == "__main__":
    main()
