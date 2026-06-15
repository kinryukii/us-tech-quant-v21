from __future__ import annotations

import csv
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "outputs" / "v20" / "ops"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

V20_5_READ_FIRST = ROOT / "outputs" / "v20" / "ops" / "V20_5_READ_FIRST.txt"
V20_5_VALIDATION = ROOT / "outputs" / "v20" / "consolidation" / "V20_5_VALIDATION_SUMMARY.csv"
V20_5_SOURCE_REGISTRY = ROOT / "outputs" / "v20" / "consolidation" / "V20_5_SOURCE_ARTIFACT_REGISTRY.csv"

V20_6_READ_FIRST = ROOT / "outputs" / "v20" / "ops" / "V20_6_READ_FIRST.txt"
V20_6_VALIDATION = ROOT / "outputs" / "v20" / "consolidation" / "V20_6_VALIDATION_SUMMARY.csv"
V20_6_SOURCE_HASH_LEDGER = ROOT / "outputs" / "v20" / "consolidation" / "V20_6_SOURCE_HASH_LEDGER.csv"
V20_6_INPUT_HASH_LEDGER = ROOT / "outputs" / "v20" / "consolidation" / "V20_6_INPUT_HASH_LEDGER.csv"
V20_6_VERSION_BINDING_LEDGER = ROOT / "outputs" / "v20" / "consolidation" / "V20_6_VERSION_BINDING_LEDGER.csv"
V20_6_HASH_RUN_ID_PAIRING = ROOT / "outputs" / "v20" / "consolidation" / "V20_6_HASH_RUN_ID_PAIRING.csv"

STALE_DATA_AUDIT_PATH = CONSOLIDATION / "V20_7_STALE_DATA_AUDIT.csv"
LEAKAGE_RISK_AUDIT_PATH = CONSOLIDATION / "V20_7_LEAKAGE_RISK_AUDIT.csv"
PIT_AUDIT_PATH = CONSOLIDATION / "V20_7_POINT_IN_TIME_AVAILABILITY_AUDIT.csv"
DATE_COVERAGE_AUDIT_PATH = CONSOLIDATION / "V20_7_DATE_FIELD_COVERAGE_AUDIT.csv"
OUTCOME_WINDOW_READINESS_PATH = CONSOLIDATION / "V20_7_OUTCOME_WINDOW_READINESS_AUDIT.csv"
BENCHMARK_WINDOW_READINESS_PATH = CONSOLIDATION / "V20_7_BENCHMARK_WINDOW_READINESS_AUDIT.csv"
SAMPLE_METADATA_READINESS_PATH = CONSOLIDATION / "V20_7_SAMPLE_METADATA_READINESS_AUDIT.csv"
SOURCE_GATE_DECISION_PATH = CONSOLIDATION / "V20_7_SOURCE_GATE_DECISION.csv"
NORMALIZED_DATA_GATE_PATH = CONSOLIDATION / "V20_7_NORMALIZED_DATA_READINESS_GATE.csv"
BLOCKER_REGISTER_PATH = CONSOLIDATION / "V20_7_STALE_LEAKAGE_PIT_BLOCKER_REGISTER.csv"
NEXT_REQUIREMENTS_PATH = CONSOLIDATION / "V20_7_NEXT_NORMALIZED_DATA_REQUIREMENTS.csv"
VALIDATION_PATH = CONSOLIDATION / "V20_7_VALIDATION_SUMMARY.csv"
REPORT_PATH = READ_CENTER / "V20_7_STALE_LEAKAGE_PIT_GATE_REPORT.md"
CURRENT_ALIAS_PATH = READ_CENTER / "V20_CURRENT_STALE_LEAKAGE_PIT_STATUS.md"
READ_FIRST_PATH = OPS / "V20_7_READ_FIRST.txt"

DATE_FIELD_PATTERN = re.compile(
    r"(?:^|_)(date|timestamp|as_of|asof|publication|published|availability|observation)(?:_|$)",
    re.IGNORECASE,
)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def tf(value: bool) -> str:
    return "TRUE" if bool(value) else "FALSE"


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def read_kv(text: str | None) -> dict[str, str]:
    data: dict[str, str] = {}
    if not text:
        return data
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))
    except Exception:
        return []


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def canonical_path_to_path(canonical_path: str) -> Path | None:
    if not canonical_path or canonical_path == "MISSING":
        return None
    return ROOT / canonical_path.replace("/", "\\")


def source_registry_rows() -> list[dict[str, str]]:
    return read_csv_rows(V20_5_SOURCE_REGISTRY)


def detect_date_fields(path: Path) -> list[str]:
    if not path.exists() or path.suffix.lower() not in {".csv", ".tsv"}:
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            headers = next(reader, [])
    except Exception:
        return []
    return [h for h in headers if DATE_FIELD_PATTERN.search(h)]


def last_nonempty_value(path: Path, field_name: str) -> str:
    if not path.exists() or path.suffix.lower() not in {".csv", ".tsv"}:
        return "NONE_DETECTED"
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
    except Exception:
        return "NONE_DETECTED"
    for row in reversed(rows):
        value = (row.get(field_name) or "").strip()
        if value:
            return value
    return "NONE_DETECTED"


def category_profile(category: str) -> dict[str, str]:
    profiles = {
        "current_candidate_outputs": {
            "required_date_field": "latest_price_date",
            "expected_freshness_rule": "HISTORICAL_REFERENCE_ONLY",
            "required_for_layer": "comparison_candidate_snapshot",
            "leakage_field": "latest_price_date",
            "pit_observation_field": "latest_price_date",
            "stale_status": "SEALED_BASELINE_REFERENCE",
            "stale_risk_level": "LOW_REFERENCE_ONLY",
            "leakage_risk_type": "REFERENCE_LOOKAHEAD_RISK",
            "leakage_risk_level": "MEDIUM",
            "pit_status": "REFERENCE_ONLY",
        },
        "current_ranked_candidate_outputs": {
            "required_date_field": "latest_price_date",
            "expected_freshness_rule": "HISTORICAL_REFERENCE_ONLY",
            "required_for_layer": "comparison_ranked_snapshot",
            "leakage_field": "latest_price_date",
            "pit_observation_field": "latest_price_date",
            "stale_status": "SEALED_BASELINE_REFERENCE",
            "stale_risk_level": "LOW_REFERENCE_ONLY",
            "leakage_risk_type": "REFERENCE_LOOKAHEAD_RISK",
            "leakage_risk_level": "MEDIUM",
            "pit_status": "REFERENCE_ONLY",
        },
        "current_top_candidate_outputs": {
            "required_date_field": "latest_price_date",
            "expected_freshness_rule": "HISTORICAL_REFERENCE_ONLY",
            "required_for_layer": "comparison_top_snapshot",
            "leakage_field": "latest_price_date",
            "pit_observation_field": "latest_price_date",
            "stale_status": "SEALED_BASELINE_REFERENCE",
            "stale_risk_level": "LOW_REFERENCE_ONLY",
            "leakage_risk_type": "REFERENCE_LOOKAHEAD_RISK",
            "leakage_risk_level": "MEDIUM",
            "pit_status": "REFERENCE_ONLY",
        },
        "price_data_outputs": {
            "required_date_field": "system_price_date",
            "expected_freshness_rule": "HISTORICAL_REFERENCE_ONLY",
            "required_for_layer": "comparison_price_overlay",
            "leakage_field": "system_price_date/manual_price_date",
            "pit_observation_field": "system_price_date",
            "stale_status": "SEALED_BASELINE_REFERENCE",
            "stale_risk_level": "LOW_REFERENCE_ONLY",
            "leakage_risk_type": "REFERENCE_PRICE_TIMESTAMP_RISK",
            "leakage_risk_level": "MEDIUM",
            "pit_status": "REFERENCE_ONLY",
        },
        "manual_upload_templates": {
            "required_date_field": "NONE_REQUIRED",
            "expected_freshness_rule": "OPTIONAL_NOT_REGISTERED",
            "required_for_layer": "future_manual_upload",
            "leakage_field": "NONE_DETECTED",
            "pit_observation_field": "NONE_DETECTED",
            "stale_status": "MISSING_OPTIONAL",
            "stale_risk_level": "INFO",
            "leakage_risk_type": "MISSING_OPTIONAL",
            "leakage_risk_level": "INFO",
            "pit_status": "MISSING_OPTIONAL",
        },
        "manual_upload_ledgers": {
            "required_date_field": "NONE_REQUIRED",
            "expected_freshness_rule": "OPTIONAL_NOT_REGISTERED",
            "required_for_layer": "future_manual_upload",
            "leakage_field": "NONE_DETECTED",
            "pit_observation_field": "NONE_DETECTED",
            "stale_status": "MISSING_OPTIONAL",
            "stale_risk_level": "INFO",
            "leakage_risk_type": "MISSING_OPTIONAL",
            "leakage_risk_level": "INFO",
            "pit_status": "MISSING_OPTIONAL",
        },
        "factor_registry_outputs": {
            "required_date_field": "NONE_REQUIRED",
            "expected_freshness_rule": "ARCHITECTURE_REFERENCE_ONLY",
            "required_for_layer": "architecture_factor_registry",
            "leakage_field": "NONE_DETECTED",
            "pit_observation_field": "NONE_DETECTED",
            "stale_status": "NO_DATE_FIELD_DETECTED",
            "stale_risk_level": "HIGH_BLOCKED",
            "leakage_risk_type": "NO_MARKET_DATA",
            "leakage_risk_level": "LOW",
            "pit_status": "NOT_APPLICABLE",
        },
        "strategy_registry_outputs": {
            "required_date_field": "NONE_REQUIRED",
            "expected_freshness_rule": "ARCHITECTURE_REFERENCE_ONLY",
            "required_for_layer": "architecture_strategy_registry",
            "leakage_field": "NONE_DETECTED",
            "pit_observation_field": "NONE_DETECTED",
            "stale_status": "NO_DATE_FIELD_DETECTED",
            "stale_risk_level": "HIGH_BLOCKED",
            "leakage_risk_type": "NO_MARKET_DATA",
            "leakage_risk_level": "LOW",
            "pit_status": "NOT_APPLICABLE",
        },
        "readable_report_outputs": {
            "required_date_field": "NONE_REQUIRED",
            "expected_freshness_rule": "REPORT_REFERENCE_ONLY",
            "required_for_layer": "read_center_reference",
            "leakage_field": "NONE_DETECTED",
            "pit_observation_field": "NONE_DETECTED",
            "stale_status": "NO_DATE_FIELD_DETECTED",
            "stale_risk_level": "HIGH_BLOCKED",
            "leakage_risk_type": "NO_MARKET_DATA",
            "leakage_risk_level": "LOW",
            "pit_status": "NOT_APPLICABLE",
        },
        "historical_v18_baseline_outputs": {
            "required_date_field": "HISTORICAL_REFERENCE_DATE",
            "expected_freshness_rule": "HISTORICAL_REFERENCE_ONLY",
            "required_for_layer": "historical_reference_only",
            "leakage_field": "latest_price_date_or_system_price_date",
            "pit_observation_field": "latest_price_date_or_system_price_date",
            "stale_status": "SEALED_BASELINE_REFERENCE",
            "stale_risk_level": "LOW_REFERENCE_ONLY",
            "leakage_risk_type": "REFERENCE_LOOKAHEAD_RISK",
            "leakage_risk_level": "MEDIUM",
            "pit_status": "REFERENCE_ONLY",
        },
        "historical_v19_baseline_outputs": {
            "required_date_field": "HISTORICAL_REFERENCE_DATE",
            "expected_freshness_rule": "HISTORICAL_REFERENCE_ONLY",
            "required_for_layer": "historical_reference_only",
            "leakage_field": "NONE_DETECTED",
            "pit_observation_field": "NONE_DETECTED",
            "stale_status": "SEALED_BASELINE_REFERENCE",
            "stale_risk_level": "LOW_REFERENCE_ONLY",
            "leakage_risk_type": "NO_MARKET_DATA",
            "leakage_risk_level": "LOW",
            "pit_status": "NOT_APPLICABLE",
        },
        "v20_architecture_outputs": {
            "required_date_field": "NONE_REQUIRED",
            "expected_freshness_rule": "ARCHITECTURE_REFERENCE_ONLY",
            "required_for_layer": "architecture_clarification",
            "leakage_field": "NONE_DETECTED",
            "pit_observation_field": "NONE_DETECTED",
            "stale_status": "NO_DATE_FIELD_DETECTED",
            "stale_risk_level": "HIGH_BLOCKED",
            "leakage_risk_type": "NO_MARKET_DATA",
            "leakage_risk_level": "LOW",
            "pit_status": "NOT_APPLICABLE",
        },
        "v20_read_center_outputs": {
            "required_date_field": "NONE_REQUIRED",
            "expected_freshness_rule": "READ_CENTER_REFERENCE_ONLY",
            "required_for_layer": "read_center_status",
            "leakage_field": "NONE_DETECTED",
            "pit_observation_field": "NONE_DETECTED",
            "stale_status": "NO_DATE_FIELD_DETECTED",
            "stale_risk_level": "HIGH_BLOCKED",
            "leakage_risk_type": "NO_MARKET_DATA",
            "leakage_risk_level": "LOW",
            "pit_status": "NOT_APPLICABLE",
        },
        "v20_ops_outputs": {
            "required_date_field": "NONE_REQUIRED",
            "expected_freshness_rule": "OPS_REFERENCE_ONLY",
            "required_for_layer": "ops_reference",
            "leakage_field": "NONE_DETECTED",
            "pit_observation_field": "NONE_DETECTED",
            "stale_status": "NO_DATE_FIELD_DETECTED",
            "stale_risk_level": "HIGH_BLOCKED",
            "leakage_risk_type": "NO_MARKET_DATA",
            "leakage_risk_level": "LOW",
            "pit_status": "NOT_APPLICABLE",
        },
        "future_normalized_dataset_placeholders": {
            "required_date_field": "NONE_REQUIRED",
            "expected_freshness_rule": "PLACEHOLDER_NOT_REAL_DATA",
            "required_for_layer": "future_normalized_dataset",
            "leakage_field": "NONE_DETECTED",
            "pit_observation_field": "NONE_DETECTED",
            "stale_status": "PLACEHOLDER_NOT_REAL_DATA",
            "stale_risk_level": "HIGH_BLOCKED",
            "leakage_risk_type": "PLACEHOLDER_NOT_REAL_DATA",
            "leakage_risk_level": "HIGH",
            "pit_status": "PLACEHOLDER",
        },
        "future_backtest_placeholders": {
            "required_date_field": "NONE_REQUIRED",
            "expected_freshness_rule": "PLACEHOLDER_NOT_REAL_DATA",
            "required_for_layer": "future_backtest",
            "leakage_field": "NONE_DETECTED",
            "pit_observation_field": "NONE_DETECTED",
            "stale_status": "PLACEHOLDER_NOT_REAL_DATA",
            "stale_risk_level": "HIGH_BLOCKED",
            "leakage_risk_type": "PLACEHOLDER_NOT_REAL_DATA",
            "leakage_risk_level": "HIGH",
            "pit_status": "PLACEHOLDER",
        },
    }
    return profiles.get(
        category,
        {
            "required_date_field": "NONE_REQUIRED",
            "expected_freshness_rule": "UNKNOWN",
            "required_for_layer": "unknown",
            "leakage_field": "NONE_DETECTED",
            "pit_observation_field": "NONE_DETECTED",
            "stale_status": "NO_DATE_FIELD_DETECTED",
            "stale_risk_level": "HIGH_BLOCKED",
            "leakage_risk_type": "NO_MARKET_DATA",
            "leakage_risk_level": "LOW",
            "pit_status": "NOT_APPLICABLE",
        },
    )


def build_stale_audit(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    audits: list[dict[str, object]] = []
    for row in rows:
        path = canonical_path_to_path(row.get("canonical_path", ""))
        category = row.get("source_category", "")
        profile = category_profile(category)
        status = row.get("source_status", "")
        exists = path is not None and path.exists()
        date_fields = detect_date_fields(path) if path and exists else []
        date_field_detected = date_fields[0] if date_fields else "NONE_DETECTED"
        latest_available_date = last_nonempty_value(path, date_field_detected) if date_fields else "NONE_DETECTED"

        if status == "REGISTERED_MISSING_OPTIONAL":
            stale_status = "MISSING_OPTIONAL"
            stale_risk_level = "INFO"
            eligible = "FALSE"
            blocker = "Optional source missing; not required for stale/leakage/PIT gate."
        elif status == "REGISTERED_PLACEHOLDER":
            stale_status = profile["stale_status"]
            stale_risk_level = profile["stale_risk_level"]
            eligible = "FALSE"
            blocker = "Future placeholder is not real data."
        elif category in {"current_candidate_outputs", "current_ranked_candidate_outputs", "current_top_candidate_outputs", "price_data_outputs"} and exists:
            stale_status = profile["stale_status"]
            stale_risk_level = profile["stale_risk_level"]
            eligible = "FALSE"
            blocker = "Sealed baseline reference only; not an active normalized-data input."
        elif exists:
            stale_status = profile["stale_status"]
            stale_risk_level = profile["stale_risk_level"]
            eligible = "FALSE"
            blocker = "No active market-data freshness policy is available for this source class."
        else:
            stale_status = "MISSING_REQUIRED" if status != "REGISTERED_MISSING_OPTIONAL" else "MISSING_OPTIONAL"
            stale_risk_level = "HIGH_BLOCKED"
            eligible = "FALSE"
            blocker = "Source missing or not a usable normalized-data input."

        audits.append(
            {
                "audit_id": f"STALE-{row.get('source_artifact_id', '')}",
                "source_artifact_id": row.get("source_artifact_id", ""),
                "source_category": category,
                "canonical_path": row.get("canonical_path", ""),
                "date_field_detected": date_field_detected,
                "latest_available_date": latest_available_date,
                "expected_freshness_rule": profile["expected_freshness_rule"],
                "stale_status": stale_status,
                "stale_risk_level": stale_risk_level,
                "eligible_for_normalized_data": eligible,
                "blocker_reason": blocker,
            }
        )
    return audits


def build_leakage_audit(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    audits: list[dict[str, object]] = []
    for row in rows:
        path = canonical_path_to_path(row.get("canonical_path", ""))
        category = row.get("source_category", "")
        profile = category_profile(category)
        status = row.get("source_status", "")
        exists = path is not None and path.exists()
        date_fields = detect_date_fields(path) if path and exists else []
        future_field = profile["leakage_field"] if date_fields else "NONE_DETECTED"

        if status == "REGISTERED_MISSING_OPTIONAL":
            risk_type = "MISSING_OPTIONAL"
            risk_level = "INFO"
            mitigation = "No action; source is optional and absent."
        elif status == "REGISTERED_PLACEHOLDER":
            risk_type = "PLACEHOLDER_NOT_REAL_DATA"
            risk_level = "HIGH"
            mitigation = "Do not treat placeholder as real data."
        elif category in {"current_candidate_outputs", "current_ranked_candidate_outputs", "current_top_candidate_outputs", "price_data_outputs"} and exists:
            risk_type = profile["leakage_risk_type"]
            risk_level = profile["leakage_risk_level"]
            mitigation = "Keep as historical reference only; do not promote to active inputs."
        elif exists:
            risk_type = profile["leakage_risk_type"]
            risk_level = profile["leakage_risk_level"]
            mitigation = "No market-data leakage path is usable at this stage."
        else:
            risk_type = "MISSING_REQUIRED"
            risk_level = "HIGH"
            mitigation = "Source missing; cannot be evaluated for leakage use."

        audits.append(
            {
                "audit_id": f"LEAK-{row.get('source_artifact_id', '')}",
                "source_artifact_id": row.get("source_artifact_id", ""),
                "source_category": category,
                "canonical_path": row.get("canonical_path", ""),
                "potential_future_information_field": future_field,
                "leakage_risk_type": risk_type,
                "leakage_risk_level": risk_level,
                "mitigation_required": mitigation,
                "eligible_for_factor_evidence": "FALSE",
                "eligible_for_backtest": "FALSE",
                "blocker_reason": "Future-information leakage cannot be cleared in V20.7; normalized dataset is still blocked.",
            }
        )
    return audits


def build_pit_audit(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    audits: list[dict[str, object]] = []
    for row in rows:
        path = canonical_path_to_path(row.get("canonical_path", ""))
        category = row.get("source_category", "")
        profile = category_profile(category)
        status = row.get("source_status", "")
        exists = path is not None and path.exists()
        date_fields = detect_date_fields(path) if path and exists else []
        observation = profile["pit_observation_field"] if date_fields else "NONE_DETECTED"
        availability = "NONE_DETECTED"
        publication = "NONE_DETECTED"

        if status == "REGISTERED_MISSING_OPTIONAL":
            pit_status = "MISSING_OPTIONAL"
            pit_assumption = "FALSE"
            required = "FALSE"
            blocker = "Optional source missing; no PIT requirement."
        elif status == "REGISTERED_PLACEHOLDER":
            pit_status = profile["pit_status"]
            pit_assumption = "FALSE"
            required = "TRUE"
            blocker = "Placeholder data cannot be used as a PIT source."
        elif category in {"current_candidate_outputs", "current_ranked_candidate_outputs", "current_top_candidate_outputs", "price_data_outputs"} and exists:
            pit_status = "REFERENCE_ONLY_INSUFFICIENT"
            pit_assumption = "FALSE"
            required = "TRUE"
            blocker = "Observation date exists on sealed baseline files, but no availability/publication metadata supports active PIT use."
        elif exists:
            pit_status = profile["pit_status"]
            pit_assumption = "FALSE"
            required = "FALSE"
            blocker = "Source class is reference-only and not a PIT-capable market-data input."
        else:
            pit_status = "MISSING_REQUIRED"
            pit_assumption = "FALSE"
            required = "TRUE"
            blocker = "Source missing; PIT cannot be established."

        audits.append(
            {
                "audit_id": f"PIT-{row.get('source_artifact_id', '')}",
                "source_artifact_id": row.get("source_artifact_id", ""),
                "source_category": category,
                "canonical_path": row.get("canonical_path", ""),
                "observation_date_field": observation,
                "availability_date_field": availability,
                "publication_date_field": publication,
                "pit_status": pit_status,
                "pit_assumption_allowed": pit_assumption,
                "required_before_normalized_data": required,
                "blocker_reason": blocker,
            }
        )
    return audits


def build_date_coverage_audit(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    audits: list[dict[str, object]] = []
    for row in rows:
        path = canonical_path_to_path(row.get("canonical_path", ""))
        category = row.get("source_category", "")
        profile = category_profile(category)
        status = row.get("source_status", "")
        exists = path is not None and path.exists()
        date_fields = detect_date_fields(path) if path and exists else []
        required_field = profile["required_date_field"]
        detected_field = date_fields[0] if date_fields else "NONE_DETECTED"
        field_present = "TRUE" if bool(date_fields) else "FALSE"

        if status == "REGISTERED_MISSING_OPTIONAL":
            required_for_layer = profile["required_for_layer"]
            coverage_status = "NOT_REQUIRED"
            blocker = "Optional source missing; not required for normalization."
        elif status == "REGISTERED_PLACEHOLDER":
            required_for_layer = profile["required_for_layer"]
            coverage_status = "BLOCKED_PLACEHOLDER"
            blocker = "Placeholder is not real data."
        elif category in {"current_candidate_outputs", "current_ranked_candidate_outputs", "current_top_candidate_outputs", "price_data_outputs"} and exists:
            required_for_layer = profile["required_for_layer"]
            coverage_status = "PASS_REFERENCE_ONLY" if bool(date_fields) else "BLOCKED_MISSING_DATE_FIELD"
            blocker = "Sealed baseline comparison only; not an active normalized-data input."
        elif exists and profile["required_date_field"] == "NONE_REQUIRED":
            required_for_layer = profile["required_for_layer"]
            coverage_status = "NOT_REQUIRED"
            blocker = "Reference-only source class does not need a date field for the current gate."
        else:
            required_for_layer = profile["required_for_layer"]
            coverage_status = "BLOCKED_MISSING_DATE_FIELD"
            blocker = "No usable date field detected for future normalized-data use."

        audits.append(
            {
                "audit_id": f"DATE-{row.get('source_artifact_id', '')}",
                "source_artifact_id": row.get("source_artifact_id", ""),
                "canonical_path": row.get("canonical_path", ""),
                "required_date_field": required_field,
                "field_present": field_present,
                "detected_field_name": detected_field,
                "required_for_layer": required_for_layer,
                "coverage_status": coverage_status,
                "blocker_reason": blocker,
            }
        )
    return audits


def build_outcome_window_readiness() -> list[dict[str, object]]:
    windows = ["1D", "5D", "10D", "20D", "60D", "90D", "120D", "252D"]
    rows = []
    for idx, window in enumerate(windows, start=1):
        rows.append(
            {
                "audit_id": f"OUT-{idx:02d}",
                "outcome_window_id": window,
                "window_name": f"Outcome window {window}",
                "required_price_fields": "price_date, close, adjusted_close",
                "required_date_fields": "observation_date, availability_date, publication_date",
                "readiness_status": "BLOCKED_NO_NORMALIZED_DATASET",
                "allowed_for_normalized_outcome_dataset": "FALSE",
                "allowed_for_backtest": "FALSE",
                "blocker_reason": "Outcome windows remain design-only until the normalized research dataset is created.",
            }
        )
    return rows


def build_benchmark_window_readiness() -> list[dict[str, object]]:
    benchmarks = [
        ("SPY", "SPY"),
        ("QQQ", "QQQ"),
        ("XLK", "XLK"),
        ("SOXX", "SOXX"),
        ("IWM", "IWM"),
        ("CUSTOM_TECH_BENCHMARK_PLACEHOLDER", "Custom tech benchmark placeholder"),
    ]
    rows = []
    for idx, (bench_id, name) in enumerate(benchmarks, start=1):
        rows.append(
            {
                "audit_id": f"BEN-{idx:02d}",
                "benchmark_id": bench_id,
                "benchmark_name": name,
                "required_benchmark_fields": "benchmark_date, benchmark_close, benchmark_return",
                "required_date_fields": "benchmark_date, availability_date, publication_date",
                "readiness_status": "BLOCKED_NO_NORMALIZED_BENCHMARK_DATASET",
                "allowed_for_normalized_benchmark_dataset": "FALSE",
                "allowed_for_backtest": "FALSE",
                "blocker_reason": "Benchmark windows remain blocked until normalized benchmark data and PIT gating exist.",
            }
        )
    return rows


def build_sample_metadata_readiness() -> list[dict[str, object]]:
    requirements = [
        ("META01", "Universe definition", "universe_definition"),
        ("META02", "Survivorship policy", "survivorship_policy"),
        ("META03", "Liquidity filter policy", "liquidity_filter_policy"),
        ("META04", "Missing data policy", "missing_data_policy"),
        ("META05", "Event exclusion policy", "event_exclusion_policy"),
        ("META06", "Sample count threshold", "sample_count_threshold"),
    ]
    rows = []
    for idx, (req_id, name, field) in enumerate(requirements, start=1):
        rows.append(
            {
                "audit_id": f"META-{idx:02d}",
                "metadata_requirement": name,
                "required_field": field,
                "required_for_normalized_dataset": "TRUE",
                "required_for_factor_evidence": "TRUE",
                "required_for_backtest": "TRUE",
                "readiness_status": "BLOCKED_NO_CERTIFIED_SAMPLE_METADATA",
                "blocker_reason": "Sample metadata is not yet certified for normalized dataset, factor evidence, or backtest use.",
            }
        )
    return rows


def build_source_gate_decision(dep_ok: bool, normalized_ready: bool) -> list[dict[str, object]]:
    return [
        {
            "gate_id": "GATE-V20-7-SL-PIT",
            "gate_name": "V20.7 Stale / Leakage / PIT Gate",
            "dependency_output": "V20_6_READ_FIRST.txt + V20_6_VALIDATION_SUMMARY.csv + V20_6 lineage ledgers",
            "dependency_status": "PASS" if dep_ok else "BLOCKED",
            "gate_status": "PASS" if normalized_ready else "BLOCKED",
            "normalized_data_allowed_next": tf(normalized_ready),
            "factor_evidence_allowed_next": "FALSE",
            "backtest_allowed_next": "FALSE",
            "dynamic_weighting_allowed_next": "FALSE",
            "official_use_allowed": "FALSE",
            "blocker_reason": (
                "Only sealed-baseline comparison files expose date-like fields; active runtime sources are architecture/report artifacts without PIT-ready market data."
            )
            if not normalized_ready
            else "Ready for normalized dataset planning."
        }
    ]


def build_normalized_data_gate() -> list[dict[str, object]]:
    rows = [
        ("COMP01", "Sealed baseline date fields", "PASS_REFERENCE_ONLY", False, "Historical baseline candidate/price files contain date-like fields, but only as comparison references."),
        ("COMP02", "Active runtime date fields", "BLOCKED", False, "Current runtime architecture/report sources do not provide active market-data date coverage."),
        ("COMP03", "PIT publication metadata", "BLOCKED", False, "No availability/publication dates exist for active normalized-data use."),
        ("COMP04", "Leakage-safe separation", "BLOCKED", False, "Future-return and label separation is not yet established for normalized data."),
        ("COMP05", "Outcome window scaffold", "BLOCKED", False, "Outcome windows are defined only as design placeholders."),
        ("COMP06", "Benchmark window scaffold", "BLOCKED", False, "Benchmark windows are defined only as design placeholders."),
        ("COMP07", "Sample metadata certification", "BLOCKED", False, "Sample metadata is not certified."),
    ]
    return [
        {
            "gate_id": row[0],
            "required_component": row[1],
            "component_status": row[2],
            "allowed_for_v20_8_normalized_research_dataset": tf(row[3]),
            "blocker_reason": row[4],
        }
        for row in rows
    ]


def build_blocker_register() -> list[dict[str, object]]:
    blockers = [
        ("BLK01", "NO_ACTIVE_DATE_FIELDS", "V20 architecture/report sources", "normalized research dataset", "Active runtime sources do not expose market-data observation or publication fields.", "V20.8_NORMALIZED_RESEARCH_DATASET", "BLOCKED"),
        ("BLK02", "SEALED_BASELINE_REFERENCE_ONLY", "V18 candidate/price baseline sources", "normalized research dataset", "Baseline date fields exist only for comparison and not as active inputs.", "V20.8_NORMALIZED_RESEARCH_DATASET", "BLOCKED"),
        ("BLK03", "NO_PIT_PUBLICATION_METADATA", "Candidate and price baseline sources", "normalized research dataset", "No availability/publication dates exist to support PIT-aligned use.", "V20.8_NORMALIZED_RESEARCH_DATASET", "BLOCKED"),
        ("BLK04", "NO_LEAKAGE_SAFE_LABEL_BOUNDARY", "Future normalized data layer", "normalized research dataset", "Future-return labels and later-price fields remain blocked from signal-side use.", "V20.8_NORMALIZED_RESEARCH_DATASET", "BLOCKED"),
        ("BLK05", "NO_OUTCOME_WINDOW_LAYER", "Outcome windows", "normalized outcome dataset", "Outcome windows exist only as a planning scaffold.", "V20.8_NORMALIZED_RESEARCH_DATASET", "BLOCKED"),
        ("BLK06", "NO_BENCHMARK_WINDOW_LAYER", "Benchmark windows", "normalized benchmark dataset", "Benchmark windows exist only as a planning scaffold.", "V20.8_NORMALIZED_RESEARCH_DATASET", "BLOCKED"),
        ("BLK07", "NO_SAMPLE_METADATA_CERTIFICATION", "Sample metadata", "normalized research dataset", "Sample metadata policies are not certified.", "V20.8_NORMALIZED_RESEARCH_DATASET", "BLOCKED"),
        ("BLK08", "NO_REAL_NORMALIZED_DATASET", "Future placeholder sources", "normalized research dataset", "Future placeholders are not real data and cannot be promoted.", "V20.8_NORMALIZED_RESEARCH_DATASET", "BLOCKED"),
        ("BLK09", "NO_FACTOR_EVIDENCE", "Factor evidence layer", "factor evidence", "Factor evidence must wait for a normalized dataset and PIT-safe inputs.", "V20.9_FACTOR_EVIDENCE", "BLOCKED"),
        ("BLK10", "NO_EXPLORATORY_BACKTEST", "Exploratory backtest layer", "exploratory backtest", "Exploratory backtest requires normalized data, outcome windows, and benchmark windows.", "V20.10_EXPLORATORY_BACKTEST", "BLOCKED"),
        ("BLK11", "NO_DYNAMIC_WEIGHTING", "Dynamic weighting gate research", "dynamic weighting", "Dynamic weighting remains blocked until evidence and exploratory review exist.", "V20.11_DYNAMIC_WEIGHTING_GATE_RESEARCH", "BLOCKED"),
        ("BLK12", "NO_TRADING", "Official trading boundary", "official trading", "Trading remains blocked throughout the V20.7 gate.", "V20.12_TRADING_BOUNDARY", "BLOCKED"),
    ]
    return [
        {
            "blocker_id": blocker_id,
            "blocker_category": category,
            "affected_source_artifact_id": source_scope,
            "affected_future_layer": future_layer,
            "blocker_description": description,
            "required_resolution_before": required_before,
            "current_status": current_status,
        }
        for blocker_id, category, source_scope, future_layer, description, required_before, current_status in blockers
    ]


def build_next_requirements() -> list[dict[str, object]]:
    rows = [
        ("REQ01", "V20.8_NORMALIZED_RESEARCH_DATASET", "Active runtime market-data sources with date coverage and PIT metadata must exist.", "V20_7_SOURCE_GATE_DECISION.csv", "PASS", "BLOCKED"),
        ("REQ02", "V20.8_NORMALIZED_RESEARCH_DATASET", "Historical-reference-only candidate and price files must not be used as active inputs.", "V20_7_STALE_DATA_AUDIT.csv", "PASS", "BLOCKED"),
        ("REQ03", "V20.8_NORMALIZED_RESEARCH_DATASET", "Leakage-safe separation for future labels and later-price fields must be defined.", "V20_7_LEAKAGE_RISK_AUDIT.csv", "PASS", "BLOCKED"),
        ("REQ04", "V20.8_NORMALIZED_RESEARCH_DATASET", "Observation, availability, and publication-date assumptions must be resolved.", "V20_7_POINT_IN_TIME_AVAILABILITY_AUDIT.csv", "PASS", "BLOCKED"),
        ("REQ05", "V20.8_NORMALIZED_RESEARCH_DATASET", "Outcome windows must move from design-only to dataset-ready.", "V20_7_OUTCOME_WINDOW_READINESS_AUDIT.csv", "PASS", "BLOCKED"),
        ("REQ06", "V20.8_NORMALIZED_RESEARCH_DATASET", "Benchmark windows must move from design-only to dataset-ready.", "V20_7_BENCHMARK_WINDOW_READINESS_AUDIT.csv", "PASS", "BLOCKED"),
        ("REQ07", "V20.8_NORMALIZED_RESEARCH_DATASET", "Sample metadata must be certified before normalized dataset creation.", "V20_7_SAMPLE_METADATA_READINESS_AUDIT.csv", "PASS", "BLOCKED"),
        ("REQ08", "V20.8_NORMALIZED_RESEARCH_DATASET", "Future placeholders must remain placeholders and not be counted as real data.", "V20_7_SOURCE_GATE_DECISION.csv", "PASS", "BLOCKED"),
        ("REQ09", "V20.8_NORMALIZED_RESEARCH_DATASET", "Formal gate approval must be granted before the normalized dataset phase.", "V20_7_SOURCE_GATE_DECISION.csv", "PASS", "BLOCKED"),
        ("REQ10", "V20.8_NORMALIZED_RESEARCH_DATASET", "Sealed historical baselines remain comparison-only references.", "V20_7_STALE_DATA_AUDIT.csv", "PASS", "BLOCKED"),
    ]
    return [
        {
            "requirement_id": req_id,
            "required_before_v20_step": before,
            "requirement_description": desc,
            "dependency_output": dep,
            "required_status": required_status,
            "current_status": current_status,
        }
        for req_id, before, desc, dep, required_status, current_status in rows
    ]


def build_report(
    registry: list[dict[str, str]],
    stale_rows: list[dict[str, object]],
    leakage_rows: list[dict[str, object]],
    pit_rows: list[dict[str, object]],
    date_rows: list[dict[str, object]],
    outcome_rows: list[dict[str, object]],
    benchmark_rows: list[dict[str, object]],
    sample_rows: list[dict[str, object]],
    gate_row: dict[str, object],
    normalized_rows: list[dict[str, object]],
    blockers: list[dict[str, object]],
    next_rows: list[dict[str, object]],
    dependency_ok: bool,
    normalized_ready: bool,
) -> str:
    sealed_refs = sum(1 for row in registry if row.get("sealed_baseline", "FALSE") == "TRUE")
    runtime_sources = sum(1 for row in registry if row.get("current_runtime_source", "FALSE") == "TRUE")
    date_field_sources = sum(1 for row in date_rows if row.get("field_present") == "TRUE")
    ref_date_rows = sum(1 for row in date_rows if row.get("coverage_status") == "PASS_REFERENCE_ONLY")
    blocked_date_rows = len(date_rows) - ref_date_rows
    return "\n".join(
        [
            "# V20.7 慢数据 / 泄漏风险 / PIT 门控报告",
            "",
            "## 结论",
            f"- 状态：{'SEALED' if dependency_ok else 'WARN'}",
            "- 本步骤仅做 stale / leakage / point-in-time 审核，不生成标准化真实数据、不创建因子证据、不运行回测、不执行动态加权。",
            f"- V20.6 依赖：{'通过并接受' if dependency_ok else '未通过'}",
            f"- 标准化研究数据下一步允许：{'TRUE' if normalized_ready else 'FALSE'}",
            "",
            "## 审核摘要",
            f"- 审核来源总数：{len(registry)}",
            f"- stale 审核行数：{len(stale_rows)}",
            f"- leakage 审核行数：{len(leakage_rows)}",
            f"- PIT 审核行数：{len(pit_rows)}",
            f"- 日期字段覆盖审计行数：{len(date_rows)}",
            f"- outcome 窗口行数：{len(outcome_rows)}",
            f"- benchmark 窗口行数：{len(benchmark_rows)}",
            f"- sample metadata 行数：{len(sample_rows)}",
            f"- blocker register 行数：{len(blockers)}",
            f"- next requirement 行数：{len(next_rows)}",
            "",
            "## 关键判断",
            f"- 封存历史基线源：{sealed_refs} 项。",
            f"- 当前运行源：{runtime_sources} 项。",
            f"- 具有日期字段的源：{date_field_sources} 项（其中仅有封存基线比较源可见）。",
            f"- 参考性通过的日期覆盖行数：{ref_date_rows}。",
            f"- 仍被阻塞的日期覆盖行数：{blocked_date_rows}。",
            "",
            "## 为什么仍被阻塞",
            "- 只有 V18 对比候选/价格文件暴露了 `latest_price_date`、`system_price_date`、`manual_price_date` 等日期字段；它们已被封存为 historical reference only。",
            "- 当前 runtime 的 V20 架构/报告/ops/source registry 资产没有可用于标准化研究数据的活跃市场数据日期与发布/可用时间戳。",
            "- outcome windows、benchmark windows 与 sample metadata 仍然是设计层模板，不是可执行数据层。",
            "- future placeholders 明确不是 real data，不能被计入标准化数据或回测输入。",
            "",
            "## 下一步",
            "- V20.8 仍然是目标阶段，但当前尚未放行。",
            "- 在进入 V20.8 前，需要先补齐活跃源的 PIT / freshness / leakage 控制与样本元数据证书。",
            "",
            "## 安全边界",
            "- 不生成 normalized real data rows。",
            "- 不创建 factor evidence、backtest、performance claims、dynamic weighting 或 trading 输出。",
            "- 不更改官方 ranking / weights / trading decision logic。",
            "",
            "## 说明",
            "- 该门控仅评估是否具备进入标准化研究数据阶段的最小条件，不会推断缺失的未来数据。",
        ]
    )


def build_current_alias() -> str:
    return "\n".join(
        [
            "# V20 当前 stale / leakage / PIT 状态",
            "",
            "- V20.7 已执行，但门控结果为 BLOCKED。",
            "- V20.6 hash / run_id / version binding 依赖已接受。",
            "- 仅有封存历史基线候选/价格文件显示日期字段；它们仍是 reference only。",
            "- 当前 runtime 源缺少可用于标准化研究数据的活跃 PIT / freshness / leakage 组合。",
            "- 下一阶段目标仍是 V20.8，但尚未放行。",
        ]
    )


def build_validation_summary(
    stale_rows: int,
    leakage_rows: int,
    pit_rows: int,
    date_rows: int,
    outcome_rows: int,
    benchmark_rows: int,
    sample_rows: int,
    blocker_rows: int,
    next_rows: int,
    normalized_rows: list[dict[str, object]],
    source_rows: list[dict[str, str]],
    dep_ok: bool,
    normalized_ready: bool,
) -> list[dict[str, object]]:
    return [
        {
            "required_outputs_created": 15,
            "dependency_inputs_found": sum(
                1 for p in [
                    V20_6_READ_FIRST,
                    V20_6_VALIDATION,
                    V20_6_SOURCE_HASH_LEDGER,
                    V20_6_INPUT_HASH_LEDGER,
                    V20_6_VERSION_BINDING_LEDGER,
                    V20_6_HASH_RUN_ID_PAIRING,
                ]
                if p.exists()
            ),
            "v20_6_dependency_detected": tf(dep_ok),
            "hash_run_id_version_binding_dependency_accepted": tf(dep_ok),
            "source_artifact_rows": len(source_rows),
            "stale_audit_rows": stale_rows,
            "leakage_audit_rows": leakage_rows,
            "pit_audit_rows": pit_rows,
            "date_coverage_rows": date_rows,
            "outcome_window_rows": outcome_rows,
            "benchmark_window_rows": benchmark_rows,
            "sample_metadata_rows": sample_rows,
            "source_gate_rows": 1,
            "normalized_data_gate_rows": len(normalized_rows),
            "blocker_rows": blocker_rows,
            "next_requirement_rows": next_rows,
            "ready_for_normalized_research_dataset_next": tf(normalized_ready),
            "ready_for_factor_evidence_next": "FALSE",
            "ready_for_exploratory_backtest_next": "FALSE",
            "ready_for_dynamic_weighting_gate_research_next": "FALSE",
            "official_trading_allowed": "FALSE",
            "official_portfolio_weight_allowed": "FALSE",
            "official_factor_weight_change_allowed": "FALSE",
            "official_backtest_allowed": "FALSE",
            "stale_leakage_pit_gate_executed": "TRUE",
            "normalized_real_data_rows_created": 0,
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
    ]


def build_read_first(dep_ok: bool, normalized_ready: bool) -> None:
    lines = [
        "STATUS: WARN",
        "PATCH_NAME: V20.7_STALE_LEAKAGE_PIT_GATE",
        "REPORTING_ONLY: TRUE",
        "STALE_LEAKAGE_PIT_GATE_ONLY: TRUE",
        f"HASH_RUN_ID_VERSION_BINDING_DEPENDENCY_ACCEPTED: {tf(dep_ok)}",
        "STALE_LEAKAGE_PIT_GATE_EXECUTED: TRUE",
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
        "SAFETY_STATUS: PASS",
        f"READY_FOR_NORMALIZED_RESEARCH_DATASET_NEXT: {tf(normalized_ready)}",
        "READY_FOR_FACTOR_EVIDENCE_NEXT: FALSE",
        "READY_FOR_EXPLORATORY_BACKTEST_NEXT: FALSE",
        "READY_FOR_DYNAMIC_WEIGHTING_GATE_RESEARCH_NEXT: FALSE",
        "OFFICIAL_TRADING_ALLOWED: FALSE",
        "OFFICIAL_PORTFOLIO_WEIGHT_ALLOWED: FALSE",
        "OFFICIAL_FACTOR_WEIGHT_CHANGE_ALLOWED: FALSE",
        "OFFICIAL_BACKTEST_ALLOWED: FALSE",
        f"NEXT_RECOMMENDED_ACTION: {'V20.7_REVIEW_STALE_LEAKAGE_PIT_GAPS' if not normalized_ready else 'V20.8_NORMALIZED_RESEARCH_DATASET'}",
        "NEXT_RECOMMENDED_MODEL: GPT-5.5",
    ]
    write_text(READ_FIRST_PATH, "\n".join(lines))


def main() -> None:
    registry = source_registry_rows()
    v20_6_read_first = read_kv(read_text(V20_6_READ_FIRST))
    v20_6_validation_rows = read_csv_rows(V20_6_VALIDATION)
    dep_ok = (
        v20_6_read_first.get("HASH_RUN_ID_VERSION_BINDING_EXECUTED") == "TRUE"
        and v20_6_read_first.get("READY_FOR_STALE_LEAKAGE_PIT_GATE_NEXT") == "TRUE"
        and (v20_6_validation_rows[0].get("version_binding_executed") == "TRUE" if v20_6_validation_rows else False)
    )

    ensure_dir(CONSOLIDATION)
    ensure_dir(READ_CENTER)
    ensure_dir(OPS)

    stale_rows = build_stale_audit(registry)
    leakage_rows = build_leakage_audit(registry)
    pit_rows = build_pit_audit(registry)
    date_rows = build_date_coverage_audit(registry)
    outcome_rows = build_outcome_window_readiness()
    benchmark_rows = build_benchmark_window_readiness()
    sample_rows = build_sample_metadata_readiness()
    normalized_rows = build_normalized_data_gate()
    normalized_ready = False
    gate_rows = build_source_gate_decision(dep_ok, normalized_ready)
    blockers = build_blocker_register()
    next_rows = build_next_requirements()

    write_csv(
        STALE_DATA_AUDIT_PATH,
        stale_rows,
        [
            "audit_id",
            "source_artifact_id",
            "source_category",
            "canonical_path",
            "date_field_detected",
            "latest_available_date",
            "expected_freshness_rule",
            "stale_status",
            "stale_risk_level",
            "eligible_for_normalized_data",
            "blocker_reason",
        ],
    )
    write_csv(
        LEAKAGE_RISK_AUDIT_PATH,
        leakage_rows,
        [
            "audit_id",
            "source_artifact_id",
            "source_category",
            "canonical_path",
            "potential_future_information_field",
            "leakage_risk_type",
            "leakage_risk_level",
            "mitigation_required",
            "eligible_for_factor_evidence",
            "eligible_for_backtest",
            "blocker_reason",
        ],
    )
    write_csv(
        PIT_AUDIT_PATH,
        pit_rows,
        [
            "audit_id",
            "source_artifact_id",
            "source_category",
            "canonical_path",
            "observation_date_field",
            "availability_date_field",
            "publication_date_field",
            "pit_status",
            "pit_assumption_allowed",
            "required_before_normalized_data",
            "blocker_reason",
        ],
    )
    write_csv(
        DATE_COVERAGE_AUDIT_PATH,
        date_rows,
        [
            "audit_id",
            "source_artifact_id",
            "canonical_path",
            "required_date_field",
            "field_present",
            "detected_field_name",
            "required_for_layer",
            "coverage_status",
            "blocker_reason",
        ],
    )
    write_csv(
        OUTCOME_WINDOW_READINESS_PATH,
        outcome_rows,
        [
            "audit_id",
            "outcome_window_id",
            "window_name",
            "required_price_fields",
            "required_date_fields",
            "readiness_status",
            "allowed_for_normalized_outcome_dataset",
            "allowed_for_backtest",
            "blocker_reason",
        ],
    )
    write_csv(
        BENCHMARK_WINDOW_READINESS_PATH,
        benchmark_rows,
        [
            "audit_id",
            "benchmark_id",
            "benchmark_name",
            "required_benchmark_fields",
            "required_date_fields",
            "readiness_status",
            "allowed_for_normalized_benchmark_dataset",
            "allowed_for_backtest",
            "blocker_reason",
        ],
    )
    write_csv(
        SAMPLE_METADATA_READINESS_PATH,
        sample_rows,
        [
            "audit_id",
            "metadata_requirement",
            "required_field",
            "required_for_normalized_dataset",
            "required_for_factor_evidence",
            "required_for_backtest",
            "readiness_status",
            "blocker_reason",
        ],
    )
    write_csv(
        SOURCE_GATE_DECISION_PATH,
        gate_rows,
        [
            "gate_id",
            "gate_name",
            "dependency_output",
            "dependency_status",
            "gate_status",
            "normalized_data_allowed_next",
            "factor_evidence_allowed_next",
            "backtest_allowed_next",
            "dynamic_weighting_allowed_next",
            "official_use_allowed",
            "blocker_reason",
        ],
    )
    write_csv(
        NORMALIZED_DATA_GATE_PATH,
        normalized_rows,
        [
            "gate_id",
            "required_component",
            "component_status",
            "allowed_for_v20_8_normalized_research_dataset",
            "blocker_reason",
        ],
    )
    write_csv(
        BLOCKER_REGISTER_PATH,
        blockers,
        [
            "blocker_id",
            "blocker_category",
            "affected_source_artifact_id",
            "affected_future_layer",
            "blocker_description",
            "required_resolution_before",
            "current_status",
        ],
    )
    write_csv(
        NEXT_REQUIREMENTS_PATH,
        next_rows,
        [
            "requirement_id",
            "required_before_v20_step",
            "requirement_description",
            "dependency_output",
            "required_status",
            "current_status",
        ],
    )

    report_text = build_report(
        registry,
        stale_rows,
        leakage_rows,
        pit_rows,
        date_rows,
        outcome_rows,
        benchmark_rows,
        sample_rows,
        gate_rows[0],
        normalized_rows,
        blockers,
        next_rows,
        dep_ok,
        normalized_ready,
    )
    write_text(REPORT_PATH, report_text)
    write_text(CURRENT_ALIAS_PATH, build_current_alias())

    validation_rows = build_validation_summary(
        len(stale_rows),
        len(leakage_rows),
        len(pit_rows),
        len(date_rows),
        len(outcome_rows),
        len(benchmark_rows),
        len(sample_rows),
        len(blockers),
        len(next_rows),
        normalized_rows,
        registry,
        dep_ok,
        normalized_ready,
    )
    write_csv(
        VALIDATION_PATH,
        validation_rows,
        [
            "required_outputs_created",
            "dependency_inputs_found",
            "v20_6_dependency_detected",
            "hash_run_id_version_binding_dependency_accepted",
            "source_artifact_rows",
            "stale_audit_rows",
            "leakage_audit_rows",
            "pit_audit_rows",
            "date_coverage_rows",
            "outcome_window_rows",
            "benchmark_window_rows",
            "sample_metadata_rows",
            "source_gate_rows",
            "normalized_data_gate_rows",
            "blocker_rows",
            "next_requirement_rows",
            "ready_for_normalized_research_dataset_next",
            "ready_for_factor_evidence_next",
            "ready_for_exploratory_backtest_next",
            "ready_for_dynamic_weighting_gate_research_next",
            "official_trading_allowed",
            "official_portfolio_weight_allowed",
            "official_factor_weight_change_allowed",
            "official_backtest_allowed",
            "stale_leakage_pit_gate_executed",
            "normalized_real_data_rows_created",
            "factor_evidence_created",
            "official_trading_signal_created",
            "official_portfolio_weight_created",
            "official_factor_weight_changed",
            "official_ranking_changed",
            "official_backtest_created",
            "exploratory_backtest_created",
            "performance_claims_created",
            "dynamic_weighting_executed",
            "source_files_mutated",
            "v21_started",
            "v19_21_started",
            "safety_status",
        ],
    )

    build_read_first(dep_ok, normalized_ready)


if __name__ == "__main__":
    main()
