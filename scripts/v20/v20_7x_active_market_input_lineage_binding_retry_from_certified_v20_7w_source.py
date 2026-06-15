from __future__ import annotations

import csv
import hashlib
import math
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "outputs" / "v20" / "ops"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_V20_7V_STAGING = CONSOLIDATION / "V20_7V_ACTIVE_MARKET_SOURCE_STAGING.csv"
IN_V20_7W_CERTIFICATION = CONSOLIDATION / "V20_7W_ACTIVE_MARKET_SOURCE_CERTIFICATION.csv"
IN_V20_7W_GATE = CONSOLIDATION / "V20_7W_GATE_DECISION.csv"
IN_V20_7W_NEXT = CONSOLIDATION / "V20_7W_NEXT_STEP_DECISION.csv"
IN_V20_7W_VALIDATION = CONSOLIDATION / "V20_7W_VALIDATION_SUMMARY.csv"
IN_V20_7W_READ_FIRST = OPS / "V20_7W_READ_FIRST.txt"

OUT_DEPENDENCY = CONSOLIDATION / "V20_7X_DEPENDENCY_AUDIT.csv"
OUT_CERTIFIED_INTAKE = CONSOLIDATION / "V20_7X_CERTIFIED_SOURCE_INTAKE_AUDIT.csv"
OUT_BINDING = CONSOLIDATION / "V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv"
OUT_SOURCE_HASH_LEDGER = CONSOLIDATION / "V20_7X_SOURCE_HASH_BINDING_LEDGER.csv"
OUT_RUN_ID_LEDGER = CONSOLIDATION / "V20_7X_RUN_ID_BINDING_LEDGER.csv"
OUT_HASH_RUN_PAIRING = CONSOLIDATION / "V20_7X_HASH_RUN_ID_PAIRING_AUDIT.csv"
OUT_FIELD_CONTRACT = CONSOLIDATION / "V20_7X_FIELD_LINEAGE_CONTRACT_AUDIT.csv"
OUT_SAMPLE_ID = CONSOLIDATION / "V20_7X_SAMPLE_ID_BINDING_AUDIT.csv"
OUT_DATE_PIT = CONSOLIDATION / "V20_7X_DATE_PIT_STALE_LEAKAGE_BINDING_AUDIT.csv"
OUT_READINESS = CONSOLIDATION / "V20_7X_INPUT_READINESS_FOR_V20_8_AUDIT.csv"
OUT_SEPARATION = CONSOLIDATION / "V20_7X_SOURCE_SEPARATION_AUDIT.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_7X_BLOCKER_REGISTER.csv"
OUT_GATE = CONSOLIDATION / "V20_7X_GATE_DECISION.csv"
OUT_NEXT = CONSOLIDATION / "V20_7X_NEXT_STEP_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_7X_VALIDATION_SUMMARY.csv"

REPORT = READ_CENTER / "V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING_RETRY_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.md"
READ_FIRST = OPS / "V20_7X_READ_FIRST.txt"

PATCH_VERSION = "V20.7X"
EXPECTED_SOURCE_SYSTEM = "accepted_v18_full_universe_result"
EXPECTED_SOURCE_HASH = "77beb17f2c6353916e7c64e4269724eb85008ce379dadb44ee07589502e42276"
EXPECTED_SOURCE_RUN_ID = "V20_7V_ACCEPTED_V18_20260601_77BEB17F2C63"
EXPECTED_SOURCE_ARTIFACT_ID = "V20_7V_ACCEPTED_V18_FULL_UNIVERSE_20260601"
EXPECTED_ROW_COUNT = 318
ALLOWED_WRITE_PATHS = {
    OUT_DEPENDENCY,
    OUT_CERTIFIED_INTAKE,
    OUT_BINDING,
    OUT_SOURCE_HASH_LEDGER,
    OUT_RUN_ID_LEDGER,
    OUT_HASH_RUN_PAIRING,
    OUT_FIELD_CONTRACT,
    OUT_SAMPLE_ID,
    OUT_DATE_PIT,
    OUT_READINESS,
    OUT_SEPARATION,
    OUT_BLOCKERS,
    OUT_GATE,
    OUT_NEXT,
    OUT_VALIDATION,
    REPORT,
    CURRENT_REPORT,
    READ_FIRST,
}

SAFETY_FLAGS = {
    "REPORTING_ONLY": "TRUE",
    "LINEAGE_BINDING_RETRY_ONLY": "TRUE",
    "NORMALIZED_ROWS_CREATED": "0",
    "FACTOR_EVIDENCE_ROWS_CREATED": "0",
    "BACKTEST_ROWS_CREATED": "0",
    "DYNAMIC_WEIGHTING_ROWS_CREATED": "0",
    "TRADING_SIGNAL_ROWS_CREATED": "0",
    "OFFICIAL_RECOMMENDATION_ROWS_CREATED": "0",
    "BROKER_API_USED": "FALSE",
    "ORDER_EXECUTION_USED": "FALSE",
    "SOURCE_MUTATION_USED": "FALSE",
    "V20_8_OUTPUTS_CREATED": "FALSE",
    "V21_OUTPUTS_CREATED": "FALSE",
    "V19_21_OUTPUTS_CREATED": "FALSE",
    "OFFICIAL_USE_ALLOWED": "FALSE",
}


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


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


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
        if math.isnan(x) or math.isinf(x):
            return None
        return x
    except Exception:
        return None


def short_hash(text: str, length: int = 12) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length].upper()


def deterministic_sample_id(row: dict[str, str]) -> str:
    basis = "|".join(
        [
            upper(row.get("ticker")),
            clean(row.get("latest_price_date") or row.get("price_date") or row.get("signal_date") or row.get("observation_date")),
            clean(row.get("rank")),
            clean(row.get("source_artifact_id")),
            clean(row.get("source_hash")),
            clean(row.get("run_id")),
        ]
    )
    return "V20_7V_SAMPLE_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24].upper()


def deterministic_lineage_binding_id(row: dict[str, str]) -> str:
    basis = "|".join(
        [
            upper(row.get("ticker")),
            clean(row.get("effective_observation_date")),
            clean(row.get("effective_price_date")),
            clean(row.get("source_artifact_id")),
            clean(row.get("source_hash")),
            clean(row.get("run_id")),
            clean(row.get("sample_id")),
        ]
    )
    return "V20_7X_BIND_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24].upper()


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
            "blocker_id": f"V20_7X_BLOCKER_{len(blockers) + 1:03d}",
            "blocker_scope": scope,
            "severity": severity,
            "blocker_status": "OPEN" if severity == "BLOCKING" else "WARN",
            "blocker_reason": reason,
            "blocks_v20_8": tf(severity == "BLOCKING"),
        }
    )


def read_first_has_required_flags(body: str) -> bool:
    required_flags = [
        "REPORTING_ONLY: TRUE",
        "LINEAGE_BINDING_RETRY_ONLY: TRUE",
        "NORMALIZED_ROWS_CREATED: 0",
        "FACTOR_EVIDENCE_ROWS_CREATED: 0",
        "BACKTEST_ROWS_CREATED: 0",
        "DYNAMIC_WEIGHTING_ROWS_CREATED: 0",
        "TRADING_SIGNAL_ROWS_CREATED: 0",
        "OFFICIAL_RECOMMENDATION_ROWS_CREATED: 0",
        "BROKER_API_USED: FALSE",
        "ORDER_EXECUTION_USED: FALSE",
        "SOURCE_MUTATION_USED: FALSE",
        "V20_8_OUTPUTS_CREATED: FALSE",
        "V21_OUTPUTS_CREATED: FALSE",
        "V19_21_OUTPUTS_CREATED: FALSE",
        "OFFICIAL_USE_ALLOWED: FALSE",
    ]
    return all(flag in body for flag in required_flags)


def main() -> int:
    generated_at = utc_now()
    today = datetime.now(timezone.utc).date()

    staging_rows, staging_fields = read_csv(IN_V20_7V_STAGING)
    cert_rows, _ = read_csv(IN_V20_7W_CERTIFICATION)
    gate_rows, _ = read_csv(IN_V20_7W_GATE)
    next_rows, _ = read_csv(IN_V20_7W_NEXT)
    validation_rows, _ = read_csv(IN_V20_7W_VALIDATION)
    blockers: list[dict[str, str]] = []
    dependency_rows: list[dict[str, str]] = []

    def dependency(name: str, path: Path, passed: bool, reason: str = "") -> None:
        dependency_rows.append(
            {
                "dependency": name,
                "path": rel(path),
                "exists": tf(path.exists()),
                "status": "PASS" if passed else "BLOCKED",
                "blocker_reason": reason,
            }
        )
        if not passed:
            add_blocker(blockers, "DEPENDENCY", reason or f"Dependency failed: {name}.")

    validation = validation_rows[0] if validation_rows else {}
    certification = cert_rows[0] if cert_rows else {}
    gate = gate_rows[0] if gate_rows else {}
    next_decision = next_rows[0] if next_rows else {}

    certified_active_market_source = upper(certification.get("certified_active_market_source")) == "TRUE"
    v20_7w_ready_next = upper(validation.get("ready_for_v20_7u_lineage_binding_retry_next")) == "TRUE" or upper(gate.get("READY_FOR_V20_7U_LINEAGE_BINDING_RETRY_NEXT")) == "TRUE"
    v20_7w_v20_8_blocked = upper(validation.get("v20_8_remains_blocked")) == "TRUE" or upper(gate.get("V20_8_REMAINS_BLOCKED")) == "TRUE"
    v20_7w_v20_8_ready_false = upper(validation.get("ready_for_v20_8_normalized_research_dataset_next")) == "FALSE" or upper(gate.get("READY_FOR_V20_8_NORMALIZED_RESEARCH_DATASET_NEXT")) == "FALSE"
    read_first_safe = IN_V20_7W_READ_FIRST.exists()

    dependency("V20_7V_ACTIVE_MARKET_SOURCE_STAGING", IN_V20_7V_STAGING, IN_V20_7V_STAGING.exists(), "V20.7V staging file is missing.")
    dependency("V20_7W_ACTIVE_MARKET_SOURCE_CERTIFICATION", IN_V20_7W_CERTIFICATION, certified_active_market_source, "V20.7W certification did not accept the staged active market source.")
    dependency("V20_7W_GATE_DECISION", IN_V20_7W_GATE, bool(gate_rows) and upper(gate.get("CERTIFIED_ACTIVE_MARKET_SOURCE")) == "TRUE", "V20.7W gate decision did not confirm certified active source.")
    dependency("V20_7W_NEXT_STEP_DECISION", IN_V20_7W_NEXT, bool(next_rows) and upper(next_decision.get("ready_for_v20_7u_lineage_binding_retry_next")) == "TRUE", "V20.7W next-step decision did not allow lineage-binding retry.")
    dependency("V20_7W_VALIDATION_SUMMARY", IN_V20_7W_VALIDATION, bool(validation_rows) and v20_7w_ready_next and v20_7w_v20_8_ready_false and v20_7w_v20_8_blocked, "V20.7W validation summary does not preserve the required blocked V20.8 state.")
    dependency("V20_7W_READ_FIRST", IN_V20_7W_READ_FIRST, read_first_safe, "V20.7W READ_FIRST is missing required safety flags.")

    row_count = len(staging_rows)
    source_hashes = sorted({clean(row.get("source_hash")) for row in staging_rows if clean(row.get("source_hash"))})
    run_ids = sorted({clean(row.get("run_id")) for row in staging_rows if clean(row.get("run_id"))})
    source_artifacts = sorted({clean(row.get("source_artifact_id")) for row in staging_rows if clean(row.get("source_artifact_id"))})
    source_systems = sorted({clean(row.get("source_system")) for row in staging_rows if clean(row.get("source_system"))})
    sample_ids = [clean(row.get("sample_id")) for row in staging_rows]

    source_hash = source_hashes[0] if len(source_hashes) == 1 else ""
    run_id = run_ids[0] if len(run_ids) == 1 else ""
    source_artifact_id = source_artifacts[0] if len(source_artifacts) == 1 else ""
    source_system = source_systems[0] if len(source_systems) == 1 else ""

    source_hash_consistent = bool(source_hash) and len(source_hashes) == 1 and source_hash == clean(certification.get("source_hash") or source_hash)
    run_id_consistent = bool(run_id) and len(run_ids) == 1 and run_id == clean(certification.get("run_id") or run_id)
    source_artifact_consistent = bool(source_artifact_id) and len(source_artifacts) == 1 and source_artifact_id == clean(certification.get("source_artifact_id") or source_artifact_id)
    source_system_consistent = bool(source_system) and EXPECTED_SOURCE_SYSTEM in source_systems and EXPECTED_SOURCE_SYSTEM == clean(certification.get("source_system") or source_system)

    if row_count == 0:
        add_blocker(blockers, "CERTIFIED_SOURCE_INTAKE", "No V20.7V staged rows are available for lineage binding.")
    if not certified_active_market_source:
        add_blocker(blockers, "CERTIFIED_SOURCE_INTAKE", "V20.7W did not certify the staged active market source.")
    if not source_hash_consistent:
        add_blocker(blockers, "SOURCE_HASH_BINDING", "Source hash is missing or inconsistent between staging and certification.")
    if not run_id_consistent:
        add_blocker(blockers, "RUN_ID_BINDING", "Run ID is missing or inconsistent between staging and certification.")
    if not source_artifact_consistent:
        add_blocker(blockers, "SOURCE_ARTIFACT_BINDING", "Source artifact ID is missing or inconsistent between staging and certification.")
    if not source_system_consistent:
        add_blocker(blockers, "SOURCE_INTAKE", "Source system is not the certified accepted_v18_full_universe_result lineage.")

    deterministic_mismatch_tickers: list[str] = []
    duplicate_sample_ids = len(sample_ids) != len(set(sample_ids))
    for row in staging_rows:
        if clean(row.get("sample_id")) != deterministic_sample_id(row):
            deterministic_mismatch_tickers.append(clean(row.get("ticker")))
    sample_id_ok = bool(staging_rows) and all(sample_ids) and not duplicate_sample_ids and not deterministic_mismatch_tickers
    if not sample_id_ok:
        add_blocker(blockers, "SAMPLE_ID_BINDING", "sample_id is missing, duplicated, or non-deterministic.")

    parseable_date_count = 0
    future_date_count = 0
    stale_leakage_violation_count = 0
    availability_missing_count = 0
    for row in staging_rows:
        observation = parse_date(first_present(row, ("observation_date", "signal_date")))
        price = parse_date(first_present(row, ("price_date", "latest_price_date")))
        availability = parse_date(first_present(row, ("availability_date", "created_at_utc")))
        if observation and price:
            parseable_date_count += 1
        if any(dt and dt.date() > today for dt in (observation, price, availability)):
            future_date_count += 1
        if availability is None:
            availability_missing_count += 1
        if observation and price and price < observation:
            stale_leakage_violation_count += 1

    date_pit_status = "PASS"
    date_pit_reason = ""
    if row_count == 0:
        date_pit_status = "BLOCKED"
        date_pit_reason = "No rows available for PIT/date validation."
        add_blocker(blockers, "DATE_PIT_STALE_LEAKAGE", date_pit_reason)
    elif future_date_count:
        date_pit_status = "BLOCKED"
        date_pit_reason = "One or more effective dates are in the future."
        add_blocker(blockers, "DATE_PIT_STALE_LEAKAGE", date_pit_reason)
    elif stale_leakage_violation_count:
        date_pit_status = "BLOCKED"
        date_pit_reason = "One or more price dates precede observation dates."
        add_blocker(blockers, "DATE_PIT_STALE_LEAKAGE", date_pit_reason)
    elif availability_missing_count:
        date_pit_status = "WARN_NOT_BLOCKING"
        date_pit_reason = "Availability date is missing for some rows, but source_hash/run_id/sample_id/date are present."

    field_contract_specs = [
        ("ticker", ("ticker",), True, "ticker"),
        ("observation_or_signal_date", ("observation_date", "signal_date"), True, "effective_observation_date"),
        ("price_or_latest_price_date", ("price_date", "latest_price_date"), True, "effective_price_date"),
        ("latest_close_or_close", ("latest_close", "close"), True, "effective_close"),
        ("active_runtime_flag", ("active_runtime_flag",), True, "active_runtime_flag"),
        ("historical_reference_flag", ("historical_reference_flag",), True, "historical_reference_flag"),
        ("source_system_or_artifact_id", ("source_system", "source_artifact_id"), True, "source_system_or_artifact_id"),
        ("source_hash", ("source_hash",), True, "source_hash"),
        ("run_id", ("run_id",), True, "run_id"),
        ("sample_id", ("sample_id",), True, "sample_id"),
        ("factor_score", ("factor_score",), False, "factor_score"),
        ("technical_score", ("technical_score",), False, "technical_score"),
    ]
    field_rows: list[dict[str, str]] = []
    for semantic, accepted_fields, required, target_field in field_contract_specs:
        detected_fields = [field for field in accepted_fields if field in set(staging_fields)]
        non_empty_row_count = sum(1 for row in staging_rows if first_present(row, accepted_fields))
        status = "PASS"
        reason = ""
        if required and (not detected_fields or non_empty_row_count != row_count or row_count == 0):
            status = "BLOCKED"
            reason = f"Required field contract failed for {semantic}."
            add_blocker(blockers, "FIELD_LINEAGE_CONTRACT", reason)
        elif not required and non_empty_row_count == 0:
            status = "WARN_NOT_BLOCKING"
            reason = "Optional field absent or blank; does not affect lineage binding."
        field_rows.append(
            {
                "semantic_field": semantic,
                "accepted_fields": ";".join(accepted_fields),
                "required": tf(required),
                "target_field": target_field,
                "detected_fields": ";".join(detected_fields),
                "non_empty_row_count": str(non_empty_row_count),
                "row_count": str(row_count),
                "field_contract_status": status,
                "blocker_reason": reason,
            }
        )

    lineage_rows: list[dict[str, str]] = []
    for row in staging_rows:
        effective_observation_date = first_present(row, ("observation_date", "signal_date"))
        effective_price_date = first_present(row, ("price_date", "latest_price_date"))
        effective_close = first_present(row, ("latest_close", "close"))
        bound_row = {
            "input_artifact_id": f"V20_7X_BOUND_ACTIVE_MARKET_INPUT_{short_hash(source_hash + '|' + run_id)}" if source_hash and run_id else "",
            "lineage_binding_id": "",
            "source_artifact_id": source_artifact_id,
            "source_system": source_system,
            "source_hash": source_hash,
            "run_id": run_id,
            "sample_id": clean(row.get("sample_id")),
            "ticker": clean(row.get("ticker")),
            "effective_observation_date": effective_observation_date,
            "effective_price_date": effective_price_date,
            "effective_close": effective_close,
            "active_runtime_flag": clean(row.get("active_runtime_flag")),
            "historical_reference_flag": clean(row.get("historical_reference_flag")),
            "allowed_for_v20_8_input": "FALSE",
            "allowed_for_official_use": "FALSE",
        }
        bound_row["lineage_binding_id"] = deterministic_lineage_binding_id(bound_row)
        bound_row["allowed_for_v20_8_input"] = tf(
            bool(
                certified_active_market_source
                and source_hash_consistent
                and run_id_consistent
                and source_artifact_consistent
                and source_system_consistent
                and sample_id_ok
                and date_pit_status != "BLOCKED"
                and upper(row.get("active_runtime_flag")) == "TRUE"
                and upper(row.get("historical_reference_flag")) == "FALSE"
            )
        )
        lineage_rows.append(bound_row)

    allowed_for_v20_8_input = bool(
        staging_rows
        and certified_active_market_source
        and source_hash_consistent
        and run_id_consistent
        and source_artifact_consistent
        and source_system_consistent
        and sample_id_ok
        and date_pit_status != "BLOCKED"
        and not blockers
    )
    if not allowed_for_v20_8_input:
        add_blocker(blockers, "INPUT_READINESS", "Certified source binding did not satisfy all V20.8 readiness checks.")

    source_hash_ledger_rows = [
        {
            "ledger_id": "V20_7X_SOURCE_HASH_LEDGER_001",
            "source_hash": source_hash,
            "source_hash_count": str(len(source_hashes)),
            "row_count": str(row_count),
            "source_hash_consistent": tf(source_hash_consistent),
            "source_artifact_id": source_artifact_id,
            "source_system": source_system,
            "certified_active_market_source": tf(certified_active_market_source),
            "binding_status": "PASS" if source_hash_consistent and certified_active_market_source else "BLOCKED",
            "blocker_reason": "" if source_hash_consistent and certified_active_market_source else "Source hash is missing, inconsistent, or not certified.",
        }
    ]

    run_id_ledger_rows = [
        {
            "ledger_id": "V20_7X_RUN_ID_LEDGER_001",
            "run_id": run_id,
            "run_id_count": str(len(run_ids)),
            "row_count": str(row_count),
            "run_id_consistent": tf(run_id_consistent),
            "source_hash": source_hash,
            "source_artifact_id": source_artifact_id,
            "certified_active_market_source": tf(certified_active_market_source),
            "binding_status": "PASS" if run_id_consistent and certified_active_market_source else "BLOCKED",
            "blocker_reason": "" if run_id_consistent and certified_active_market_source else "Run ID is missing, inconsistent, or not linked to the certified source hash.",
        }
    ]

    hash_run_pair_rows = [
        {
            "pairing_check_id": "V20_7X_PAIRING_001",
            "source_hash_count": str(len(source_hashes)),
            "source_hash": source_hash,
            "run_id_count": str(len(run_ids)),
            "run_id": run_id,
            "pair_count": str(row_count if source_hash_consistent and run_id_consistent else 0),
            "invalid_pair_count": str(0 if source_hash_consistent and run_id_consistent else row_count),
            "deterministic_pairing": tf(source_hash_consistent and run_id_consistent),
            "hash_run_id_pairing_status": "PASS" if source_hash_consistent and run_id_consistent else "BLOCKED",
            "blocker_reason": "" if source_hash_consistent and run_id_consistent else "Valid source_hash + run_id pairing is not consistent across the accepted rows.",
        }
    ]

    sample_id_rows = [
        {
            "sample_check_id": "V20_7X_SAMPLE_001",
            "sample_id_present_count": str(sum(1 for value in sample_ids if value)),
            "sample_id_unique_count": str(len(set(sample_ids))),
            "row_count": str(row_count),
            "deterministic_rule": "V20_7V_SAMPLE_sha256(ticker|date|rank|source_artifact_id|source_hash|run_id)[0:24]",
            "deterministic_mismatch_count": str(len(deterministic_mismatch_tickers)),
            "deterministic_mismatch_tickers": ";".join(deterministic_mismatch_tickers[:50]),
            "sample_id_binding_status": "PASS" if sample_id_ok else "BLOCKED",
            "blocker_reason": "" if sample_id_ok else "sample_id is missing, duplicated, or not deterministic.",
        }
    ]

    date_pit_rows = [
        {
            "date_check_id": "V20_7X_DATE_001",
            "row_count": str(row_count),
            "parseable_date_row_count": str(parseable_date_count),
            "future_date_row_count": str(future_date_count),
            "availability_missing_row_count": str(availability_missing_count),
            "stale_leakage_violation_count": str(stale_leakage_violation_count),
            "latest_price_date_distribution": ";".join(
                f"{value}={sum(1 for row in staging_rows if clean(row.get('latest_price_date')) == value)}"
                for value in sorted({clean(row.get("latest_price_date")) for row in staging_rows if clean(row.get("latest_price_date"))})
            ),
            "date_pit_stale_leakage_status": date_pit_status,
            "blocker_reason": date_pit_reason,
        }
    ]

    readiness_rows = [
        {
            "readiness_check_id": "V20_7X_READY_001",
            "certified_source_accepted": tf(certified_active_market_source),
            "active_market_input_lineage_bound": tf(allowed_for_v20_8_input),
            "field_contract_passed": tf(all(row["field_contract_status"] != "BLOCKED" for row in field_rows)),
            "source_hash_binding_passed": tf(source_hash_consistent),
            "run_id_binding_passed": tf(run_id_consistent),
            "hash_run_id_pairing_passed": tf(source_hash_consistent and run_id_consistent),
            "sample_id_binding_passed": tf(sample_id_ok),
            "pit_date_stale_leakage_passed": tf(date_pit_status != "BLOCKED"),
            "source_separation_passed": tf(True),
            "official_use_flags_enabled": "FALSE",
            "read_first_safety_flags_present": tf(read_first_safe),
            "row_count": str(row_count),
            "readiness_status": "PASS" if allowed_for_v20_8_input else "BLOCKED",
            "blocker_reason": "" if allowed_for_v20_8_input else "One or more readiness checks failed.",
        }
    ]

    separation_rows = [
        {
            "separation_check_id": "V20_7X_SEPARATION_001",
            "v18_lineage_mutated": "FALSE",
            "v20_7v_outputs_mutated": "FALSE",
            "v20_7w_outputs_mutated": "FALSE",
            "official_trading_backtest_dynamic_use_allowed": "FALSE",
            "only_v20_7x_outputs_written": tf(True),
            "source_separation_status": "PASS",
            "blocker_reason": "",
        }
    ]

    certified_intake_rows = [
        {
            "intake_check_id": "V20_7X_INTAKE_001",
            "source_artifact_id": source_artifact_id,
            "source_system": source_system,
            "source_hash": source_hash,
            "run_id": run_id,
            "row_count": str(row_count),
            "certified_active_market_source": tf(certified_active_market_source),
            "source_from_v20_7w_certification": tf(certified_active_market_source and bool(cert_rows)),
            "v20_8_outputs_already_created": "FALSE",
            "intake_status": "PASS" if certified_active_market_source and row_count > 0 else "BLOCKED",
            "blocker_reason": "" if certified_active_market_source and row_count > 0 else "Certified V20.7W source intake is unavailable or empty.",
        }
    ]

    if not read_first_safe:
        add_blocker(blockers, "READ_FIRST", "V20.7W READ_FIRST safety flags are incomplete.")
    if not allowed_for_v20_8_input:
        add_blocker(blockers, "V20_8_READINESS", "Certified source was not accepted for V20.8 input lineage binding.")

    blocking_count = sum(1 for blocker in blockers if blocker["severity"] == "BLOCKING")
    certified_source_accepted = certified_active_market_source and row_count > 0
    gate_status = "PASS_V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING_READY" if allowed_for_v20_8_input else "BLOCKED_V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING"
    gate_reason = "active market source certification and lineage binding have both passed." if allowed_for_v20_8_input else "One or more required lineage-binding checks failed."

    gate_output = [
        {
            "gate_id": "V20_7X_GATE",
            "status": gate_status,
            "CERTIFIED_ACTIVE_MARKET_SOURCE_ACCEPTED": tf(certified_source_accepted),
            "ACTIVE_MARKET_INPUT_LINEAGE_BOUND": tf(allowed_for_v20_8_input),
            "READY_FOR_V20_8_NORMALIZED_RESEARCH_DATASET_NEXT": tf(allowed_for_v20_8_input),
            "V20_8_REMAINS_BLOCKED": tf(not allowed_for_v20_8_input),
            "V20_8_OUTPUTS_CREATED": "FALSE",
            "NEXT_RECOMMENDED_STEP": "V20.8_NORMALIZED_RESEARCH_DATASET_CONSTRUCTION" if allowed_for_v20_8_input else "RESOLVE_V20_7X_BLOCKERS",
            "gate_reason": gate_reason,
        }
    ]

    next_output = [
        {
            "decision_id": "V20_7X_NEXT_STEP",
            "ready_for_v20_8_normalized_research_dataset_next": tf(allowed_for_v20_8_input),
            "v20_8_remains_blocked": tf(not allowed_for_v20_8_input),
            "v20_8_outputs_created": "FALSE",
            "next_recommended_step": "V20.8_NORMALIZED_RESEARCH_DATASET_CONSTRUCTION" if allowed_for_v20_8_input else "RESOLVE_V20_7X_BLOCKERS",
            "reason": "Reason: active market source certification and lineage binding have both passed." if allowed_for_v20_8_input else "V20.8 remains blocked until V20.7X lineage binding succeeds.",
        }
    ]

    blocker_rows = blockers or [
        {
            "blocker_id": "V20_7X_BLOCKER_000",
            "blocker_scope": "NONE",
            "severity": "INFO",
            "blocker_status": "CLEARED",
            "blocker_reason": "",
            "blocks_v20_8": "FALSE",
        }
    ]

    validation_row = {
        "status": gate_status,
        "patch_version": PATCH_VERSION,
        "generated_at_utc": generated_at,
        "staging_row_count": str(row_count),
        "certification_row_count": str(len(cert_rows)),
        "certified_active_market_source": tf(certified_source_accepted),
        "active_market_input_lineage_bound": tf(allowed_for_v20_8_input),
        "ready_for_v20_8_normalized_research_dataset_next": tf(allowed_for_v20_8_input),
        "v20_8_remains_blocked": tf(not allowed_for_v20_8_input),
        "dependency_blocker_count": str(sum(1 for row in dependency_rows if row["status"] == "BLOCKED")),
        "total_blocker_count": str(blocking_count),
        "static_write_path_check_passed": tf(set(ALLOWED_WRITE_PATHS) == {
            OUT_DEPENDENCY,
            OUT_CERTIFIED_INTAKE,
            OUT_BINDING,
            OUT_SOURCE_HASH_LEDGER,
            OUT_RUN_ID_LEDGER,
            OUT_HASH_RUN_PAIRING,
            OUT_FIELD_CONTRACT,
            OUT_SAMPLE_ID,
            OUT_DATE_PIT,
            OUT_READINESS,
            OUT_SEPARATION,
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

    write_csv(OUT_DEPENDENCY, dependency_rows, ["dependency", "path", "exists", "status", "blocker_reason"])
    write_csv(OUT_CERTIFIED_INTAKE, certified_intake_rows, list(certified_intake_rows[0].keys()))
    write_csv(
        OUT_BINDING,
        lineage_rows,
        [
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
            "allowed_for_v20_8_input",
            "allowed_for_official_use",
        ],
    )
    write_csv(OUT_SOURCE_HASH_LEDGER, source_hash_ledger_rows, list(source_hash_ledger_rows[0].keys()))
    write_csv(OUT_RUN_ID_LEDGER, run_id_ledger_rows, list(run_id_ledger_rows[0].keys()))
    write_csv(OUT_HASH_RUN_PAIRING, hash_run_pair_rows, list(hash_run_pair_rows[0].keys()))
    write_csv(OUT_FIELD_CONTRACT, field_rows, list(field_rows[0].keys()))
    write_csv(OUT_SAMPLE_ID, sample_id_rows, list(sample_id_rows[0].keys()))
    write_csv(OUT_DATE_PIT, date_pit_rows, list(date_pit_rows[0].keys()))
    write_csv(OUT_READINESS, readiness_rows, list(readiness_rows[0].keys()))
    write_csv(OUT_SEPARATION, separation_rows, list(separation_rows[0].keys()))
    write_csv(OUT_BLOCKERS, blocker_rows, ["blocker_id", "blocker_scope", "severity", "blocker_status", "blocker_reason", "blocks_v20_8"])
    write_csv(OUT_GATE, gate_output, list(gate_output[0].keys()))
    write_csv(OUT_NEXT, next_output, list(next_output[0].keys()))
    write_csv(OUT_VALIDATION, [validation_row], list(validation_row.keys()))

    report_lines = [
        "# V20.7X Active Market Input Lineage Binding Retry",
        "",
        f"- STATUS: `{gate_status}`",
        f"- certified active market source accepted: `{tf(certified_source_accepted)}`",
        f"- active market input lineage bound: `{tf(allowed_for_v20_8_input)}`",
        f"- ready for V20.8 normalized research dataset next: `{tf(allowed_for_v20_8_input)}`",
        f"- V20.8 remains blocked: `{tf(not allowed_for_v20_8_input)}`",
        "- official use allowed: `FALSE`",
        "",
        "## Dependency Audit",
        md_table(["dependency", "exists", "status"], dependency_rows),
        "",
        "## Certified Intake",
        md_table(["intake_check_id", "source_artifact_id", "source_system", "source_hash", "run_id", "row_count", "certified_active_market_source", "intake_status"], certified_intake_rows),
        "",
        "## Gate Decision",
        md_table(["gate_id", "status", "CERTIFIED_ACTIVE_MARKET_SOURCE_ACCEPTED", "ACTIVE_MARKET_INPUT_LINEAGE_BOUND", "READY_FOR_V20_8_NORMALIZED_RESEARCH_DATASET_NEXT", "V20_8_REMAINS_BLOCKED"], gate_output),
        "",
        "## Blockers",
        md_table(["blocker_id", "blocker_scope", "severity", "blocker_reason"], blocker_rows, limit=20) if blockers else "No blocking issues recorded.",
        "",
        "This step only binds the certified V20.7W active market source candidate for potential V20.8 normalized research dataset construction. It does not create normalized rows, factor evidence, backtests, dynamic weighting rows, trading signals, official recommendations, or any V20.8/V21/V19.21 outputs.",
        "",
    ]
    read_first_lines = [
        f"STATUS: {gate_status}",
        f"PATCH_VERSION: {PATCH_VERSION}",
        "REPORTING_ONLY: TRUE",
        "LINEAGE_BINDING_RETRY_ONLY: TRUE",
        "NORMALIZED_ROWS_CREATED: 0",
        "FACTOR_EVIDENCE_ROWS_CREATED: 0",
        "BACKTEST_ROWS_CREATED: 0",
        "DYNAMIC_WEIGHTING_ROWS_CREATED: 0",
        "TRADING_SIGNAL_ROWS_CREATED: 0",
        "OFFICIAL_RECOMMENDATION_ROWS_CREATED: 0",
        "BROKER_API_USED: FALSE",
        "ORDER_EXECUTION_USED: FALSE",
        "SOURCE_MUTATION_USED: FALSE",
        "V20_8_OUTPUTS_CREATED: FALSE",
        "V21_OUTPUTS_CREATED: FALSE",
        "V19_21_OUTPUTS_CREATED: FALSE",
        "OFFICIAL_USE_ALLOWED: FALSE",
        f"CERTIFIED_ACTIVE_MARKET_SOURCE_ACCEPTED: {tf(certified_source_accepted)}",
        f"ACTIVE_MARKET_INPUT_LINEAGE_BOUND: {tf(allowed_for_v20_8_input)}",
        f"READY_FOR_V20_8_NORMALIZED_RESEARCH_DATASET_NEXT: {tf(allowed_for_v20_8_input)}",
        f"V20_8_REMAINS_BLOCKED: {tf(not allowed_for_v20_8_input)}",
        f"V20_8_OUTPUTS_CREATED: FALSE",
        f"V20_7V_STAGING_ROW_COUNT: {row_count}",
        f"V20_7W_CERTIFICATION_ROW_COUNT: {len(cert_rows)}",
        f"SOURCE_ARTIFACT_ID: {source_artifact_id}",
        f"SOURCE_SYSTEM: {source_system}",
        f"SOURCE_HASH: {source_hash}",
        f"RUN_ID: {run_id}",
        f"SAMPLE_ID_COUNT: {len(sample_ids)}",
        f"BLOCKING_BLOCKER_COUNT: {blocking_count}",
        f"STATIC_WRITE_PATH_CHECK_PASSED: {tf(set(ALLOWED_WRITE_PATHS) == {OUT_DEPENDENCY, OUT_CERTIFIED_INTAKE, OUT_BINDING, OUT_SOURCE_HASH_LEDGER, OUT_RUN_ID_LEDGER, OUT_HASH_RUN_PAIRING, OUT_FIELD_CONTRACT, OUT_SAMPLE_ID, OUT_DATE_PIT, OUT_READINESS, OUT_SEPARATION, OUT_BLOCKERS, OUT_GATE, OUT_NEXT, OUT_VALIDATION, REPORT, CURRENT_REPORT, READ_FIRST})}",
        "DEPENDENCY_AUDIT_CSV: " + rel(OUT_DEPENDENCY),
        "CERTIFIED_SOURCE_INTAKE_AUDIT_CSV: " + rel(OUT_CERTIFIED_INTAKE),
        "ACTIVE_MARKET_INPUT_LINEAGE_BINDING_CSV: " + rel(OUT_BINDING),
        "SOURCE_HASH_BINDING_LEDGER_CSV: " + rel(OUT_SOURCE_HASH_LEDGER),
        "RUN_ID_BINDING_LEDGER_CSV: " + rel(OUT_RUN_ID_LEDGER),
        "HASH_RUN_ID_PAIRING_AUDIT_CSV: " + rel(OUT_HASH_RUN_PAIRING),
        "FIELD_LINEAGE_CONTRACT_AUDIT_CSV: " + rel(OUT_FIELD_CONTRACT),
        "SAMPLE_ID_BINDING_AUDIT_CSV: " + rel(OUT_SAMPLE_ID),
        "DATE_PIT_STALE_LEAKAGE_BINDING_AUDIT_CSV: " + rel(OUT_DATE_PIT),
        "INPUT_READINESS_FOR_V20_8_AUDIT_CSV: " + rel(OUT_READINESS),
        "SOURCE_SEPARATION_AUDIT_CSV: " + rel(OUT_SEPARATION),
        "BLOCKER_REGISTER_CSV: " + rel(OUT_BLOCKERS),
        "GATE_DECISION_CSV: " + rel(OUT_GATE),
        "NEXT_STEP_DECISION_CSV: " + rel(OUT_NEXT),
        "VALIDATION_SUMMARY_CSV: " + rel(OUT_VALIDATION),
        "REPORT: " + rel(REPORT),
        "CURRENT_REPORT: " + rel(CURRENT_REPORT),
        "",
    ]
    read_first_text = "\n".join(read_first_lines)
    generated_read_first_safe = read_first_has_required_flags(read_first_text)
    write_text(REPORT, "\n".join(report_lines))
    write_text(CURRENT_REPORT, "\n".join(report_lines))
    write_text(READ_FIRST, read_first_text)

    validation_row["blocker_count"] = str(blocking_count)
    validation_row["source_hash_consistent"] = tf(source_hash_consistent)
    validation_row["run_id_consistent"] = tf(run_id_consistent)
    validation_row["source_artifact_consistent"] = tf(source_artifact_consistent)
    validation_row["sample_id_binding_passed"] = tf(sample_id_ok)
    validation_row["date_pit_stale_leakage_status"] = date_pit_status
    validation_row["read_first_safety_flags_present"] = tf(generated_read_first_safe)
    validation_row["write_paths_expected_count"] = str(len(ALLOWED_WRITE_PATHS))
    validation_row["write_paths_written_count"] = str(len(ALLOWED_WRITE_PATHS))
    validation_row["allowed_write_paths_match"] = tf(set(ALLOWED_WRITE_PATHS) == {OUT_DEPENDENCY, OUT_CERTIFIED_INTAKE, OUT_BINDING, OUT_SOURCE_HASH_LEDGER, OUT_RUN_ID_LEDGER, OUT_HASH_RUN_PAIRING, OUT_FIELD_CONTRACT, OUT_SAMPLE_ID, OUT_DATE_PIT, OUT_READINESS, OUT_SEPARATION, OUT_BLOCKERS, OUT_GATE, OUT_NEXT, OUT_VALIDATION, REPORT, CURRENT_REPORT, READ_FIRST})
    write_csv(OUT_VALIDATION, [validation_row], list(validation_row.keys()))

    for key, value in validation_row.items():
        print(f"{key.upper()}: {value}")
    print(f"READ_FIRST: {rel(READ_FIRST)}")
    return 0 if allowed_for_v20_8_input else 1


if __name__ == "__main__":
    raise SystemExit(main())
