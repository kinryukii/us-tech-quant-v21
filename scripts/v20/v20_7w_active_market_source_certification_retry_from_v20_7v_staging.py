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

IN_STAGING = CONSOLIDATION / "V20_7V_ACTIVE_MARKET_SOURCE_STAGING.csv"
IN_VALIDATION = CONSOLIDATION / "V20_7V_VALIDATION_SUMMARY.csv"
IN_NEXT = CONSOLIDATION / "V20_7V_NEXT_STEP_DECISION.csv"
IN_READ_FIRST = OPS / "V20_7V_READ_FIRST.txt"

OUT_DEPENDENCY = CONSOLIDATION / "V20_7W_DEPENDENCY_AUDIT.csv"
OUT_CERTIFICATION = CONSOLIDATION / "V20_7W_ACTIVE_MARKET_SOURCE_CERTIFICATION.csv"
OUT_FIELD = CONSOLIDATION / "V20_7W_FIELD_CONTRACT_AUDIT.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_7W_LINEAGE_CONTRACT_AUDIT.csv"
OUT_DATE = CONSOLIDATION / "V20_7W_DATE_PIT_STALE_LEAKAGE_AUDIT.csv"
OUT_PRICE = CONSOLIDATION / "V20_7W_PRICE_TICKER_VALIDATION_AUDIT.csv"
OUT_SAMPLE = CONSOLIDATION / "V20_7W_SAMPLE_ID_CERTIFICATION_AUDIT.csv"
OUT_SEPARATION = CONSOLIDATION / "V20_7W_SOURCE_SEPARATION_AUDIT.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_7W_BLOCKER_REGISTER.csv"
OUT_GATE = CONSOLIDATION / "V20_7W_GATE_DECISION.csv"
OUT_NEXT = CONSOLIDATION / "V20_7W_NEXT_STEP_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_7W_VALIDATION_SUMMARY.csv"

REPORT = READ_CENTER / "V20_7W_ACTIVE_MARKET_SOURCE_CERTIFICATION_RETRY_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_ACTIVE_MARKET_SOURCE_CERTIFICATION.md"
READ_FIRST = OPS / "V20_7W_READ_FIRST.txt"

PATCH_VERSION = "V20.7W"
EXPECTED_SOURCE_SYSTEM = "accepted_v18_full_universe_result"
EXPECTED_STAGING_SOURCE = "V20_7V"

SAFETY_FLAGS = {
    "REPORTING_ONLY": "TRUE",
    "CERTIFICATION_RETRY_ONLY": "TRUE",
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
}


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean(value: object) -> str:
    return str(value or "").strip()


def upper(value: object) -> str:
    return clean(value).upper()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


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


def parse_date(value: object) -> datetime | None:
    text = clean(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S+00:00"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
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


def first_present(row: dict[str, str], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = clean(row.get(field))
        if value:
            return value
    return ""


def short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def deterministic_sample_id(row: dict[str, str]) -> str:
    basis = "|".join([
        upper(row.get("ticker")),
        clean(row.get("latest_price_date") or row.get("price_date") or row.get("signal_date") or row.get("observation_date")),
        clean(row.get("rank")),
        clean(row.get("source_artifact_id")),
        clean(row.get("source_hash")),
        clean(row.get("run_id")),
    ])
    return "V20_7V_SAMPLE_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24].upper()


def date_dist(rows: list[dict[str, str]], field: str) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        value = clean(row.get(field))
        counts[value] = counts.get(value, 0) + 1
    return ";".join(f"{key}={counts[key]}" for key in sorted(counts))


def add_blocker(blockers: list[dict[str, str]], scope: str, reason: str, severity: str = "BLOCKING") -> None:
    blockers.append({
        "blocker_id": f"V20_7W_BLOCKER_{len(blockers) + 1:03d}",
        "blocker_scope": scope,
        "severity": severity,
        "blocker_status": "OPEN",
        "blocker_reason": reason,
        "blocks_certification": tf(severity == "BLOCKING"),
        "blocks_v20_7u_retry": tf(severity == "BLOCKING"),
        "blocks_v20_8": "TRUE",
    })


def md_table(fields: list[str], rows: list[dict[str, str]], limit: int = 20) -> str:
    lines = ["| " + " | ".join(fields) + " |", "| " + " | ".join(["---"] * len(fields)) + " |"]
    for row in rows[:limit]:
        lines.append("| " + " | ".join(clean(row.get(field)).replace("|", "/") for field in fields) + " |")
    if len(rows) > limit:
        lines.append("| ... | " + f"{len(rows) - limit} more rows omitted" + " |" * max(0, len(fields) - 2))
    return "\n".join(lines)


def main() -> int:
    generated_at = now_utc()
    today = datetime.now(timezone.utc).date()
    staging_rows, staging_fields = read_csv(IN_STAGING)
    validation_rows, _ = read_csv(IN_VALIDATION)
    next_rows, _ = read_csv(IN_NEXT)
    read_first_text = read_text(IN_READ_FIRST)
    blockers: list[dict[str, str]] = []

    validation = validation_rows[0] if validation_rows else {}
    next_decision = next_rows[0] if next_rows else {}
    v7v_retry_allowed = upper(validation.get("v20_7s_certification_retry_allowed_next")) == "TRUE" or upper(next_decision.get("v20_7s_certification_retry_allowed_next")) == "TRUE"

    dependency_rows = [
        {"dependency": "V20_7V_ACTIVE_MARKET_SOURCE_STAGING", "path": rel(IN_STAGING), "exists": tf(IN_STAGING.exists()), "status": "PASS" if IN_STAGING.exists() else "BLOCKED"},
        {"dependency": "V20_7V_VALIDATION_SUMMARY", "path": rel(IN_VALIDATION), "exists": tf(IN_VALIDATION.exists()), "status": "PASS" if IN_VALIDATION.exists() else "BLOCKED"},
        {"dependency": "V20_7V_NEXT_STEP_DECISION", "path": rel(IN_NEXT), "exists": tf(IN_NEXT.exists()), "status": "PASS" if IN_NEXT.exists() else "BLOCKED"},
        {"dependency": "V20_7V_READ_FIRST", "path": rel(IN_READ_FIRST), "exists": tf(IN_READ_FIRST.exists()), "status": "PASS" if IN_READ_FIRST.exists() else "BLOCKED"},
        {"dependency": "V20_7V_ALLOWED_CERTIFICATION_RETRY_NEXT", "path": rel(IN_VALIDATION), "exists": tf(bool(validation_rows or next_rows)), "status": "PASS" if v7v_retry_allowed else "BLOCKED"},
    ]
    for row in dependency_rows:
        if row["status"] != "PASS":
            add_blocker(blockers, "DEPENDENCY", f"Dependency failed: {row['dependency']}.")

    semantic_groups = [
        ("ticker", ("ticker",), True),
        ("observation_or_signal_date", ("observation_date", "signal_date"), True),
        ("price_or_latest_price_date", ("price_date", "latest_price_date"), True),
        ("latest_close_or_close", ("latest_close", "close"), True),
        ("active_runtime_flag", ("active_runtime_flag",), True),
        ("historical_reference_flag", ("historical_reference_flag",), True),
        ("source_system_or_artifact_id", ("source_system", "source_artifact_id"), True),
        ("source_hash", ("source_hash",), True),
        ("run_id", ("run_id",), True),
        ("sample_id", ("sample_id",), True),
        ("rank", ("rank",), False),
        ("composite_candidate_score", ("composite_candidate_score",), False),
        ("factor_score", ("factor_score",), False),
        ("technical_score", ("technical_score",), False),
        ("price_data_source", ("price_data_source",), False),
        ("primary_score_source_files", ("primary_score_source_files",), False),
    ]
    staging_field_set = set(staging_fields)
    field_rows: list[dict[str, str]] = []
    for semantic, fields, required in semantic_groups:
        detected = [field for field in fields if field in staging_field_set]
        non_empty = 0
        if detected:
            non_empty = sum(1 for row in staging_rows if first_present(row, fields))
        status = "PASS"
        reason = ""
        if required and (not detected or non_empty != len(staging_rows) or not staging_rows):
            status = "BLOCKED"
            reason = f"Required semantic field group {semantic} missing or incomplete."
            add_blocker(blockers, "FIELD_CONTRACT", reason)
        elif not required and (not detected or non_empty == 0):
            status = "WARN_NOT_BLOCKING"
            reason = "Optional field absent or blank; does not block V20.7W certification retry."
        field_rows.append({
            "semantic_field": semantic,
            "accepted_fields": ";".join(fields),
            "required": tf(required),
            "detected_fields": ";".join(detected),
            "non_empty_row_count": str(non_empty),
            "row_count": str(len(staging_rows)),
            "field_contract_status": status,
            "blocker_reason": reason,
        })

    source_hashes = sorted({clean(row.get("source_hash")) for row in staging_rows if clean(row.get("source_hash"))})
    run_ids = sorted({clean(row.get("run_id")) for row in staging_rows if clean(row.get("run_id"))})
    source_systems = sorted({clean(row.get("source_system")) for row in staging_rows if clean(row.get("source_system"))})
    source_artifacts = sorted({clean(row.get("source_artifact_id")) for row in staging_rows if clean(row.get("source_artifact_id"))})
    source_paths = sorted({clean(row.get("source_path")) for row in staging_rows if clean(row.get("source_path"))})
    manual_override_detected = any("manual" in " ".join(row.values()).lower() and "override" in " ".join(row.values()).lower() for row in staging_rows)
    broker_order_field_detected = any(any(term in field.lower() for term in ("broker", "order", "execution_order")) for field in staging_fields)
    lineage_ok = (
        bool(staging_rows)
        and len(source_hashes) == 1
        and len(run_ids) == 1
        and EXPECTED_SOURCE_SYSTEM in source_systems
        and not manual_override_detected
        and not broker_order_field_detected
        and any("V18_CURRENT_FULL_RANKED_CANDIDATES.csv" in p for p in source_paths)
    )
    if not lineage_ok:
        add_blocker(blockers, "LINEAGE_CONTRACT", "Lineage metadata is missing, inconsistent, manual override flagged, or broker/order fields are present.")
    lineage_rows = [{
        "lineage_check_id": "LINEAGE-001",
        "source_hash_count": str(len(source_hashes)),
        "source_hash": source_hashes[0] if len(source_hashes) == 1 else ";".join(source_hashes),
        "run_id_count": str(len(run_ids)),
        "run_id": run_ids[0] if len(run_ids) == 1 else ";".join(run_ids),
        "source_systems": ";".join(source_systems),
        "source_artifact_ids": ";".join(source_artifacts),
        "source_paths": ";".join(source_paths),
        "points_to_v20_7v_staging": "TRUE",
        "points_to_accepted_v18_full_universe": tf(any("V18_CURRENT_FULL_RANKED_CANDIDATES.csv" in p for p in source_paths)),
        "manual_ticker_override_detected": tf(manual_override_detected),
        "broker_or_order_field_detected": tf(broker_order_field_detected),
        "lineage_contract_status": "PASS" if lineage_ok else "BLOCKED",
    }]

    parseable_date_rows = 0
    future_date_rows = 0
    availability_missing = 0
    date_issue_rows: list[str] = []
    for row in staging_rows:
        row_dates = [parse_date(first_present(row, ("observation_date", "signal_date"))), parse_date(first_present(row, ("price_date", "latest_price_date")))]
        availability = parse_date(first_present(row, ("availability_date", "created_at_utc")))
        if all(row_dates):
            parseable_date_rows += 1
        else:
            date_issue_rows.append(clean(row.get("ticker")))
        if any(dt and dt.date() > today for dt in row_dates + [availability]):
            future_date_rows += 1
        if availability is None:
            availability_missing += 1
    latest_date_distribution = date_dist(staging_rows, "latest_price_date")
    date_status = "PASS"
    date_reason = ""
    if parseable_date_rows != len(staging_rows) or future_date_rows:
        date_status = "BLOCKED"
        date_reason = "Date parse/future-date requirement failed."
        add_blocker(blockers, "DATE_PIT_STALE_LEAKAGE", date_reason)
    elif availability_missing:
        date_status = "WARN_NOT_BLOCKING"
        date_reason = "Availability timestamp missing for some rows; lineage/sample/run/hash are present."
    date_rows = [{
        "date_check_id": "DATE-001",
        "row_count": str(len(staging_rows)),
        "parseable_date_row_count": str(parseable_date_rows),
        "future_date_row_count": str(future_date_rows),
        "availability_missing_row_count": str(availability_missing),
        "latest_price_date_distribution": latest_date_distribution,
        "date_pit_stale_leakage_status": date_status,
        "blocker_reason": date_reason,
    }]

    duplicate_keys: dict[str, int] = {}
    ticker_blank = 0
    close_invalid = 0
    close_nonpositive = 0
    for row in staging_rows:
        ticker = upper(row.get("ticker"))
        date = first_present(row, ("latest_price_date", "price_date", "signal_date", "observation_date"))
        duplicate_keys[f"{ticker}|{date}"] = duplicate_keys.get(f"{ticker}|{date}", 0) + 1
        if not ticker:
            ticker_blank += 1
        close = to_float(first_present(row, ("latest_close", "close")))
        if close is None:
            close_invalid += 1
        elif close <= 0:
            close_nonpositive += 1
    duplicate_count = sum(1 for count in duplicate_keys.values() if count > 1)
    price_ok = bool(staging_rows) and ticker_blank == 0 and close_invalid == 0 and close_nonpositive == 0
    if not price_ok:
        add_blocker(blockers, "PRICE_TICKER_VALIDATION", "Ticker/close validation failed.")
    price_rows = [{
        "price_ticker_check_id": "PRICE-001",
        "row_count": str(len(staging_rows)),
        "ticker_blank_row_count": str(ticker_blank),
        "latest_close_invalid_row_count": str(close_invalid),
        "latest_close_nonpositive_row_count": str(close_nonpositive),
        "duplicate_ticker_date_key_count": str(duplicate_count),
        "duplicate_ticker_date_status": "WARN_DUPLICATES_AUDITED_NOT_DELETED" if duplicate_count else "PASS",
        "price_ticker_validation_status": "PASS" if price_ok else "BLOCKED",
    }]

    sample_ids = [clean(row.get("sample_id")) for row in staging_rows]
    deterministic_mismatch = [clean(row.get("ticker")) for row in staging_rows if clean(row.get("sample_id")) != deterministic_sample_id(row)]
    sample_ok = bool(staging_rows) and all(sample_ids) and len(sample_ids) == len(set(sample_ids)) and not deterministic_mismatch
    if not sample_ok:
        add_blocker(blockers, "SAMPLE_ID_CERTIFICATION", "sample_id is missing, duplicated, or not deterministic.")
    sample_rows = [{
        "sample_check_id": "SAMPLE-001",
        "sample_id_present_count": str(sum(1 for x in sample_ids if x)),
        "sample_id_unique_count": str(len(set(sample_ids))),
        "row_count": str(len(staging_rows)),
        "deterministic_rule": "V20_7V_SAMPLE_sha256(ticker|date|rank|source_artifact_id|source_hash|run_id)[0:24]",
        "deterministic_mismatch_count": str(len(deterministic_mismatch)),
        "deterministic_mismatch_tickers": ";".join(deterministic_mismatch[:50]),
        "sample_id_certification_status": "PASS" if sample_ok else "BLOCKED",
    }]

    active_false = sum(1 for row in staging_rows if upper(row.get("active_runtime_flag")) != "TRUE")
    historical_true = sum(1 for row in staging_rows if upper(row.get("historical_reference_flag")) != "FALSE")
    source_separation_ok = bool(staging_rows) and active_false == 0 and historical_true == 0
    if not source_separation_ok:
        add_blocker(blockers, "SOURCE_SEPARATION", "Active/historical source separation flags failed.")
    separation_rows = [{
        "separation_check_id": "SEPARATION-001",
        "active_runtime_flag_not_true_count": str(active_false),
        "historical_reference_flag_not_false_count": str(historical_true),
        "v18_source_mutated": "FALSE",
        "official_trading_backtest_dynamic_use_allowed": "FALSE",
        "source_separation_status": "PASS" if source_separation_ok else "BLOCKED",
    }]

    blocking_count = sum(1 for row in blockers if row["severity"] == "BLOCKING")
    certified = blocking_count == 0
    status = "PASS_V20_7W_ACTIVE_MARKET_SOURCE_CERTIFICATION_READY" if certified else "BLOCKED_V20_7W_ACTIVE_MARKET_SOURCE_CERTIFICATION"
    cert_rows = [{
        "source_artifact_id": source_artifacts[0] if len(source_artifacts) == 1 else "",
        "source_system": source_systems[0] if len(source_systems) == 1 else "",
        "source_hash": source_hashes[0] if len(source_hashes) == 1 else "",
        "run_id": run_ids[0] if len(run_ids) == 1 else "",
        "row_count": str(len(staging_rows)),
        "certified_active_market_source": tf(certified),
        "certification_status": status,
        "blocker_count": str(blocking_count),
        "certification_notes": "Certified for V20.7U lineage-binding retry only; V20.8 remains blocked.",
    }]
    gate_rows = [{
        "gate_id": "V20_7W_GATE",
        "status": status,
        "CERTIFIED_ACTIVE_MARKET_SOURCE": tf(certified),
        "READY_FOR_V20_7U_LINEAGE_BINDING_RETRY_NEXT": tf(certified),
        "READY_FOR_V20_8_NORMALIZED_RESEARCH_DATASET_NEXT": "FALSE",
        "V20_8_REMAINS_BLOCKED": "TRUE",
        "gate_reason": "Lineage binding retry has not passed after certification." if certified else "Required V20.7W checks failed.",
    }]
    next_rows_out = [{
        "decision_id": "V20_7W_NEXT_STEP",
        "ready_for_v20_7u_lineage_binding_retry_next": tf(certified),
        "ready_for_v20_8_normalized_research_dataset_next": "FALSE",
        "v20_8_remains_blocked": "TRUE",
        "next_recommended_step": "RUN_V20_7U_LINEAGE_BINDING_RETRY" if certified else "RESOLVE_V20_7W_BLOCKERS",
        "reason": "V20.8 remains blocked until V20.7U lineage binding retry passes after certification.",
    }]
    validation_out = [{
        "status": status,
        "patch_version": PATCH_VERSION,
        "generated_at_utc": generated_at,
        "staging_row_count": str(len(staging_rows)),
        "certified_active_market_source": tf(certified),
        "ready_for_v20_7u_lineage_binding_retry_next": tf(certified),
        "ready_for_v20_8_normalized_research_dataset_next": "FALSE",
        "v20_8_remains_blocked": "TRUE",
        "dependency_blocker_count": str(sum(1 for b in blockers if b["blocker_scope"] == "DEPENDENCY")),
        "total_blocker_count": str(blocking_count),
        **SAFETY_FLAGS,
    }]

    write_csv(OUT_DEPENDENCY, dependency_rows, ["dependency", "path", "exists", "status"])
    write_csv(OUT_CERTIFICATION, cert_rows, list(cert_rows[0].keys()))
    write_csv(OUT_FIELD, field_rows, ["semantic_field", "accepted_fields", "required", "detected_fields", "non_empty_row_count", "row_count", "field_contract_status", "blocker_reason"])
    write_csv(OUT_LINEAGE, lineage_rows, list(lineage_rows[0].keys()))
    write_csv(OUT_DATE, date_rows, list(date_rows[0].keys()))
    write_csv(OUT_PRICE, price_rows, list(price_rows[0].keys()))
    write_csv(OUT_SAMPLE, sample_rows, list(sample_rows[0].keys()))
    write_csv(OUT_SEPARATION, separation_rows, list(separation_rows[0].keys()))
    write_csv(OUT_BLOCKERS, blockers, ["blocker_id", "blocker_scope", "severity", "blocker_status", "blocker_reason", "blocks_certification", "blocks_v20_7u_retry", "blocks_v20_8"])
    write_csv(OUT_GATE, gate_rows, list(gate_rows[0].keys()))
    write_csv(OUT_NEXT, next_rows_out, list(next_rows_out[0].keys()))
    write_csv(OUT_VALIDATION, validation_out, list(validation_out[0].keys()))

    report = "\n".join([
        "# V20.7W Active Market Source Certification Retry",
        "",
        f"- STATUS: `{status}`",
        f"- staged rows: `{len(staging_rows)}`",
        f"- certified active market source: `{tf(certified)}`",
        f"- ready for V20.7U lineage-binding retry next: `{tf(certified)}`",
        "- ready for V20.8 normalized research dataset next: `FALSE`",
        "- V20.8 remains blocked: `TRUE`",
        "",
        "## Dependency Audit",
        md_table(["dependency", "exists", "status"], dependency_rows),
        "",
        "## Certification",
        md_table(["source_artifact_id", "source_system", "row_count", "certified_active_market_source", "certification_status", "blocker_count"], cert_rows),
        "",
        "## Safety Flags",
        md_table(["flag", "value"], [{"flag": k, "value": v} for k, v in SAFETY_FLAGS.items()], limit=20),
        "",
        "## Blockers",
        md_table(["blocker_id", "blocker_scope", "severity", "blocker_reason"], blockers, limit=20) if blockers else "No certification blockers.",
        "",
        "This retry certifies only the staged active market source candidate for the next V20.7U lineage-binding retry. It does not create normalized rows, factor evidence, backtests, dynamic weighting rows, trading signals, official recommendations, broker API calls, orders, V20.8 outputs, V21 outputs, or V19.21 outputs.",
        "",
    ])
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)

    read_first_lines = [
        f"STATUS: {status}",
        f"PATCH_VERSION: {PATCH_VERSION}",
        f"STAGING_ROW_COUNT: {len(staging_rows)}",
        f"CERTIFIED_ACTIVE_MARKET_SOURCE: {tf(certified)}",
        f"READY_FOR_V20_7U_LINEAGE_BINDING_RETRY_NEXT: {tf(certified)}",
        "READY_FOR_V20_8_NORMALIZED_RESEARCH_DATASET_NEXT: FALSE",
        "V20_8_REMAINS_BLOCKED: TRUE",
        "V20_8_BLOCK_REASON: Lineage binding retry has not passed after certification.",
    ]
    read_first_lines.extend(f"{key}: {value}" for key, value in SAFETY_FLAGS.items())
    read_first_lines.extend([
        f"DEPENDENCY_AUDIT_CSV: {rel(OUT_DEPENDENCY)}",
        f"CERTIFICATION_CSV: {rel(OUT_CERTIFICATION)}",
        f"FIELD_CONTRACT_AUDIT_CSV: {rel(OUT_FIELD)}",
        f"LINEAGE_CONTRACT_AUDIT_CSV: {rel(OUT_LINEAGE)}",
        f"DATE_PIT_STALE_LEAKAGE_AUDIT_CSV: {rel(OUT_DATE)}",
        f"PRICE_TICKER_VALIDATION_AUDIT_CSV: {rel(OUT_PRICE)}",
        f"SAMPLE_ID_CERTIFICATION_AUDIT_CSV: {rel(OUT_SAMPLE)}",
        f"SOURCE_SEPARATION_AUDIT_CSV: {rel(OUT_SEPARATION)}",
        f"BLOCKER_REGISTER_CSV: {rel(OUT_BLOCKERS)}",
        f"GATE_DECISION_CSV: {rel(OUT_GATE)}",
        f"NEXT_STEP_DECISION_CSV: {rel(OUT_NEXT)}",
        f"VALIDATION_SUMMARY_CSV: {rel(OUT_VALIDATION)}",
        f"REPORT: {rel(REPORT)}",
        f"CURRENT_REPORT: {rel(CURRENT_REPORT)}",
        "",
    ])
    write_text(READ_FIRST, "\n".join(read_first_lines))

    for key, value in validation_out[0].items():
        print(f"{key.upper()}: {value}")
    print(f"READ_FIRST: {READ_FIRST}")
    return 0 if certified else 1


if __name__ == "__main__":
    raise SystemExit(main())
