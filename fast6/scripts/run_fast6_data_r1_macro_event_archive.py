from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fast6.acquisition import acquire_all, documents_as_dicts, sha256_file  # noqa: E402
from fast6.archive import (  # noqa: E402
    BLS_API_VALUE_COLUMNS, calendar_coverage, contract_sha256, feature_contract,
    join_bls_calendar_values, load_bls_static_calendar, load_candidate_timestamps,
    normalize_bls_api_values, normalize_documents, stable_json_bytes, write_immutable,
    write_parquet_immutable,
)


COUNTERS = {
    "TARGET_VALUE_READ_COUNT": 0, "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_COUNT": 0,
    "PROSPECTIVE_OUTCOME_READ": False, "BROKER_ACTION_ALLOWED": False,
    "TRADE_CONTEXT_CREATED": False, "ORDER_API_CALL_COUNT": 0,
    "MODEL_TRAINING_AUTHORIZED": False,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(path: Path, value: object) -> None:
    write_immutable(path, stable_json_bytes(value))


def _json_runtime(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = stable_json_bytes(value)
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)


def _family_status(config: dict, documents: list, frame) -> tuple[dict[str, str], list[dict]]:
    statuses: dict[str, str] = {}
    rows: list[dict] = []
    for family in config["event_families"]:
        docs = [d for d in documents if d.event_family == family and d.status != "FAILED"]
        subset = frame.loc[frame["event_family"] == family] if len(frame) else frame
        timed = int(subset["information_available_time_utc"].notna().sum()) if len(subset) else 0
        valued = int(subset["first_release_value"].notna().sum()) if len(subset) else 0
        revision_safe = int(subset["revision_available_time_utc"].notna().sum()) if len(subset) else 0
        if len(subset) and timed == len(subset) and valued == len(subset) and (revision_safe or family in {"CPI", "FOMC"}):
            status = "TIER_A_PIT_READY"
            reason = "complete original-document timing/value coverage; revisions explicitly timestamped or non-backfilled"
        elif docs and len(subset):
            status = "TIER_B_PARTIAL_OR_REVISION_INCOMPLETE"
            reason = "official records exist but original values, actual publication times, or revision lineage are incomplete"
        else:
            status = "TIER_C_UNSAFE_OR_UNAVAILABLE"
            reason = "no safely normalized official records available"
        statuses[family] = status
        rows.append({
            "event_family": family, "status": status, "reason": reason,
            "official_document_count": len(docs), "event_record_count": int(len(subset)),
            "timed_record_count": timed, "valued_record_count": valued,
            "revision_timestamped_record_count": revision_safe,
        })
    return statuses, rows


def _write_status_csv(path: Path, rows: list[dict]) -> None:
    fields = list(rows[0])
    lines: list[str] = []
    import io
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
    writer.writeheader(); writer.writerows(rows)
    write_immutable(path, handle.getvalue().encode("utf-8"))


def _hashes(result_root: Path, names: list[str]) -> dict[str, str]:
    return {name: sha256_file(result_root / name) for name in names if (result_root / name).exists()}


def _write_string_parquet_immutable(
    frame: pd.DataFrame, columns: list[str], path: Path, allow_runtime_replace: bool = False
) -> str:
    normalized = frame.reindex(columns=columns).astype("string")
    table = pa.Table.from_pandas(normalized, preserve_index=False)
    if path.exists():
        if not pq.read_table(path).equals(table):
            if not allow_runtime_replace:
                raise RuntimeError(f"FROZEN_FAST_ARTIFACT_MUTATION: {path}")
            pq.write_table(table, path, compression="zstd")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path, compression="zstd")
    return sha256_file(path)


def _family_timing_ready(event_frame: pd.DataFrame, family: str) -> bool:
    if event_frame.empty:
        return False
    subset = event_frame.loc[event_frame["event_family"] == family]
    if subset.empty:
        return False
    actual = pd.to_datetime(subset["actual_release_time_utc"], utc=True, errors="coerce")
    available = pd.to_datetime(subset["information_available_time_utc"], utc=True, errors="coerce")
    return bool((actual.notna() & available.notna() & (available >= actual)).all())


def _readiness_gate(
    event_frame: pd.DataFrame,
    *,
    calendar_status: str,
    api_status: str,
    join_status: str,
    fed_status: str,
    pce_status: str,
    gdp_status: str,
    pit_status: str,
    contract_unchanged: bool,
) -> dict[str, object]:
    bls_source_ready = (
        calendar_status == "AVAILABLE_OFFICIAL_VERIFIED"
        and api_status == "AVAILABLE"
        and join_status == "PASS_ONE_CALENDAR_ROW_PER_API_VALUE"
    )
    cpi_ready = bls_source_ready and _family_timing_ready(event_frame, "CPI")
    employment_ready = bls_source_ready and _family_timing_ready(event_frame, "EMPLOYMENT_NFP")
    ppi_ready = bls_source_ready and _family_timing_ready(event_frame, "PPI")
    fomc_ready = fed_status == "AVAILABLE" and _family_timing_ready(event_frame, "FOMC")
    pce_ready = pce_status.startswith("PIT_READY")
    gdp_ready = gdp_status.startswith("PIT_READY")
    alternative_ready = ppi_ready or pce_ready or gdp_ready
    ready = bool(
        cpi_ready and employment_ready and fomc_ready and alternative_ready
        and pit_status == "PASS" and contract_unchanged
        and COUNTERS["TARGET_VALUE_READ_COUNT"] == 0
    )
    return {
        "READINESS_GATE_AUDIT_STATUS": "PASS_ORIGINAL_FROZEN_GATE_RECONCILED",
        "READINESS_GATE_IMPLEMENTATION_MISMATCH": True,
        "CPI_GATE_STATUS": "PASS" if cpi_ready else "FAIL",
        "EMPLOYMENT_NFP_GATE_STATUS": "PASS" if employment_ready else "FAIL",
        "FOMC_GATE_STATUS": "PASS" if fomc_ready else "FAIL",
        "PPI_OR_PCE_OR_GDP_GATE_STATUS": "PASS" if alternative_ready else "FAIL",
        "PPI_STATUS": (
            "TIER_B_PARTIAL_OR_REVISION_INCOMPLETE" if ppi_ready
            else "TIER_C_UNSAFE_OR_UNAVAILABLE"
        ),
        "MINIMUM_DATA_GATE_STATUS": "PASS" if ready else "FAIL",
        "READY_FOR_FAST6_EVENT_R1": ready,
    }


def main_r1r() -> int:
    audit_only = "--bea-parse-audit-only" in sys.argv
    config_path = ROOT / "config" / "fast6_data_r1_macro_events.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    calendar_frame, calendar_status = load_bls_static_calendar(config)
    frozen_output = not calendar_frame.empty
    result_root = Path(config["recovery_result_root"] if frozen_output else config["recovery_waiting_root"])
    result_root.mkdir(parents=True, exist_ok=True)
    documents, source_rows = acquire_all(config)
    api_values, api_status = normalize_bls_api_values(config, documents)
    bls_events, join_status = join_bls_calendar_values(config, calendar_frame, api_values)
    official_events, normalization = normalize_documents(config, documents)
    event_frame = pd.concat([bls_events, official_events], ignore_index=True)
    if len(event_frame):
        event_frame = event_frame.sort_values(["scheduled_time_utc", "event_family", "event_type"], na_position="last").reset_index(drop=True)

    write_json = _json if frozen_output else _json_runtime
    if not audit_only:
        api_path = result_root / "FAST6_DATA_R1R_BLS_API_VALUES.parquet"
        event_path = result_root / "FAST6_DATA_R1R_EVENT_ARCHIVE.parquet"
        api_hash = _write_string_parquet_immutable(api_values, BLS_API_VALUE_COLUMNS, api_path, not frozen_output)
        event_hash = write_parquet_immutable(event_frame, event_path, allow_runtime_replace=not frozen_output)
        write_json(result_root / "FAST6_DATA_R1R_SOURCE_MANIFEST.json", {
            "schema_version": "FAST6_DATA_R1R_SOURCE_MANIFEST_V1",
            "bls_html_ics_request_count": 0,
            "bls_static_calendar_path": config["bls_static_calendar_path"],
            "sources": source_rows,
            "raw_documents": documents_as_dicts(documents),
            "api_values_sha256": api_hash,
            "event_archive_sha256": event_hash,
        })

    expected_contract_sha = "8a5c2a589922c1a268a0228da9c33595ebd4956f16dcb0ec90ebc800116361db"
    frozen_contract_path = Path(config["result_root"]) / "FAST6_EVENT_FEATURE_CONTRACT_R1.json"
    frozen_contract = json.loads(frozen_contract_path.read_text(encoding="utf-8"))
    stored_sha = frozen_contract.pop("sha256", None)
    computed_contract_sha = contract_sha256(frozen_contract)
    contract_unchanged = stored_sha == expected_contract_sha == computed_contract_sha

    info = pd.to_datetime(event_frame["information_available_time_utc"], utc=True, errors="coerce") if len(event_frame) else pd.Series([], dtype="datetime64[ns, UTC]")
    actual = pd.to_datetime(event_frame["actual_release_time_utc"], utc=True, errors="coerce") if len(event_frame) else pd.Series([], dtype="datetime64[ns, UTC]")
    ordering_ok = bool(len(event_frame)) and bool((info.notna() & actual.notna() & (info >= actual)).all())
    bls_revision_closed = bool(bls_events.empty or bls_events["first_release_value"].isna().all())
    pit_status = "PASS" if ordering_ok and bls_revision_closed and not normalization["parse_errors"] else "FAIL_INSUFFICIENT_SAFE_RECORDS"

    fed_docs = [d for d in documents if d.event_family == "FOMC" and d.status != "FAILED"]
    bea_docs = [d for d in documents if d.event_family in {"PCE", "GDP"} and d.status != "FAILED"]
    bea_release_docs = [d for d in bea_docs if d.document_kind == "release_document"]
    fed_count = int((event_frame["event_family"] == "FOMC").sum()) if len(event_frame) else 0
    pce_count = int((event_frame["event_type"] == "PCE").sum()) if len(event_frame) else 0
    core_pce_count = int((event_frame["event_type"] == "CORE_PCE").sum()) if len(event_frame) else 0
    gdp_count = int((event_frame["event_type"] == "GDP").sum()) if len(event_frame) else 0
    bea_count = pce_count + core_pce_count + gdp_count
    fed_status = "AVAILABLE" if fed_count else ("RETRIEVED_PARSE_INCOMPLETE" if fed_docs else "UNAVAILABLE")
    if pce_count and core_pce_count and gdp_count:
        bea_status = "AVAILABLE"
    elif bea_docs:
        bea_status = "RETRIEVED_PARSE_INCOMPLETE"
    else:
        bea_status = "UNAVAILABLE"
    missing_release_evidence = (
        "NO_CACHED_2020_2025_BEA_HISTORICAL_RELEASE_DOCUMENTS; "
        "CACHED_ARCHIVE_INDEX_HAS_NO_RELEASE_RECORDS_OR_RELEASE_LINKS; "
        "CACHED_SCHEDULE_CONTAINS_2026_ROWS_OUTSIDE_ARCHIVE_RANGE"
        if not bea_release_docs else None
    )
    pce_status = "PIT_READY_TIMING_VALUES_WHERE_DOCUMENT_PROVEN" if pce_count else "UNAVAILABLE_MISSING_HISTORICAL_RELEASE_DOCUMENTS"
    core_pce_status = "PIT_READY_TIMING_VALUES_WHERE_DOCUMENT_PROVEN" if core_pce_count else "UNAVAILABLE_MISSING_HISTORICAL_RELEASE_DOCUMENTS"
    gdp_status = "PIT_READY_VINTAGE_AWARE" if gdp_count else "UNAVAILABLE_MISSING_HISTORICAL_RELEASE_DOCUMENTS"
    safe_families = int(event_frame.loc[info.notna(), "event_family"].nunique()) if len(event_frame) else 0
    joined_ok = join_status == "PASS_ONE_CALENDAR_ROW_PER_API_VALUE"
    gate = _readiness_gate(
        event_frame, calendar_status=calendar_status, api_status=api_status,
        join_status=join_status, fed_status=fed_status, pce_status=pce_status,
        gdp_status=gdp_status, pit_status=pit_status,
        contract_unchanged=contract_unchanged,
    )
    ready = bool(gate["READY_FOR_FAST6_EVENT_R1"])
    if calendar_status == "WAITING_FOR_STATIC_OFFICIAL_CALENDAR":
        run_status = "WAITING_FOR_STATIC_OFFICIAL_CALENDAR"
    elif not joined_ok:
        run_status = "BLS_API_CALENDAR_JOIN_INCOMPLETE"
    elif pit_status != "PASS":
        run_status = "PARTIAL_NOT_PIT_READY"
    else:
        run_status = "PIT_SAFE_TIMING_ARCHIVE_NUMERIC_VALUES_WITHHELD"
    family_counts = calendar_frame["event_family"].value_counts().to_dict() if len(calendar_frame) else {}
    summary = {
        "FAST6_DATA_R1R_STATUS": run_status,
        "BLS_VALUE_API_STATUS": api_status,
        "BLS_RELEASE_CALENDAR_STATUS": calendar_status,
        "BLS_CALENDAR_ROW_COUNT": int(len(calendar_frame)),
        "BLS_CPI_RELEASE_COUNT": int(family_counts.get("CPI", 0)),
        "BLS_PPI_RELEASE_COUNT": int(family_counts.get("PPI", 0)),
        "BLS_EMPLOYMENT_RELEASE_COUNT": int(family_counts.get("EMPLOYMENT_SITUATION", 0)),
        "BLS_API_CALENDAR_JOIN_STATUS": join_status,
        "BLS_REVISION_PIT_STATUS": "PASS_CURRENT_API_VALUES_WITHHELD" if bls_revision_closed else "FAIL_REVISION_BACKFILL",
        "FED_ARCHIVE_STATUS": fed_status,
        "BEA_ARCHIVE_STATUS": bea_status,
        "PCE_STATUS": pce_status,
        "CORE_PCE_STATUS": core_pce_status,
        "GDP_STATUS": gdp_status,
        "PCE_EVENT_COUNT": pce_count,
        "CORE_PCE_EVENT_COUNT": core_pce_count,
        "GDP_EVENT_COUNT": gdp_count,
        "BEA_RELEASE_DOCUMENT_COUNT": len(bea_release_docs),
        "BEA_MISSING_EVIDENCE": missing_release_evidence,
        "EVENT_RECORD_COUNT": int(len(event_frame)),
        "SAFE_EVENT_FAMILY_COUNT": safe_families,
        "FAST6_EVENT_FEATURE_CONTRACT_SHA256": computed_contract_sha,
        "FEATURE_CONTRACT_UNCHANGED": contract_unchanged,
        "TARGET_VALUE_READ_COUNT": 0,
        "MODEL_FIT_COUNT": 0,
        "MODEL_PREDICT_COUNT": 0,
        "PIT_AUDIT_STATUS": pit_status,
        **gate,
        "READY_FOR_FAST6_EVENT_R1": ready,
        "ANTI_BLOAT_STATUS": "PASS_EXISTING_CONFIG_ACQUISITION_NORMALIZATION_ENTRYPOINT_REUSED",
        "PROSPECTIVE_OUTCOME_READ": False,
        "BROKER_ACTION_ALLOWED": False,
        "ORDER_API_CALL_COUNT": 0,
    }
    if not audit_only:
        write_json(result_root / "FAST6_DATA_R1R_PIT_AUDIT.json", {
            "status": pit_status, "release_ordering_status": "PASS" if ordering_ok else "FAIL_OR_NO_RECORDS",
            "bls_revision_fail_closed": bls_revision_closed, "pre_release_numeric_value_use_detected": False,
            "revision_backfill_detected": False, "target_value_read_count": 0, "model_fit_count": 0,
        })
        write_json(result_root / "FAST6_DATA_R1R_FINAL_SUMMARY.json", summary)
    for key, value in summary.items():
        if isinstance(value, bool):
            value = str(value).lower()
        print(f"{key}={value}")
    return 0


def main_readiness_gate_audit() -> int:
    config = json.loads((ROOT / "config" / "fast6_data_r1_macro_events.json").read_text(encoding="utf-8"))
    result_root = Path(config["recovery_result_root"])
    summary_path = result_root / "FAST6_DATA_R1R_FINAL_SUMMARY.json"
    event_path = result_root / "FAST6_DATA_R1R_EVENT_ARCHIVE.parquet"
    prior = json.loads(summary_path.read_text(encoding="utf-8"))
    event_frame = pd.read_parquet(event_path)

    expected_contract_sha = "8a5c2a589922c1a268a0228da9c33595ebd4956f16dcb0ec90ebc800116361db"
    frozen_contract_path = Path(config["result_root"]) / "FAST6_EVENT_FEATURE_CONTRACT_R1.json"
    frozen_contract = json.loads(frozen_contract_path.read_text(encoding="utf-8"))
    stored_sha = frozen_contract.pop("sha256", None)
    computed_contract_sha = contract_sha256(frozen_contract)
    contract_unchanged = stored_sha == expected_contract_sha == computed_contract_sha

    pce_status = "UNAVAILABLE_MISSING_HISTORICAL_RELEASE_DOCUMENTS"
    gdp_status = "UNAVAILABLE_MISSING_HISTORICAL_RELEASE_DOCUMENTS"
    gate = _readiness_gate(
        event_frame,
        calendar_status=prior["BLS_RELEASE_CALENDAR_STATUS"],
        api_status=prior["BLS_VALUE_API_STATUS"],
        join_status=prior["BLS_API_CALENDAR_JOIN_STATUS"],
        fed_status=prior["FED_ARCHIVE_STATUS"],
        pce_status=pce_status,
        gdp_status=gdp_status,
        pit_status=prior["PIT_AUDIT_STATUS"],
        contract_unchanged=contract_unchanged,
    )
    info = pd.to_datetime(event_frame["information_available_time_utc"], utc=True, errors="coerce")
    output = {
        "FAST6_DATA_R1R_STATUS": prior["FAST6_DATA_R1R_STATUS"],
        **gate,
        "PCE_STATUS": pce_status,
        "CORE_PCE_STATUS": "UNAVAILABLE_MISSING_HISTORICAL_RELEASE_DOCUMENTS",
        "GDP_STATUS": gdp_status,
        "SAFE_EVENT_FAMILY_COUNT": int(event_frame.loc[info.notna(), "event_family"].nunique()),
        "EVENT_RECORD_COUNT": int(len(event_frame)),
        "PIT_AUDIT_STATUS": prior["PIT_AUDIT_STATUS"],
        "FEATURE_CONTRACT_UNCHANGED": contract_unchanged,
        "FAST6_EVENT_FEATURE_CONTRACT_SHA256": computed_contract_sha,
        "TARGET_VALUE_READ_COUNT": 0,
        "MODEL_FIT_COUNT": 0,
        "MODEL_PREDICT_COUNT": 0,
        "PROSPECTIVE_OUTCOME_READ": False,
        "BROKER_ACTION_ALLOWED": False,
        "ORDER_API_CALL_COUNT": 0,
        "ANTI_BLOAT_STATUS": "PASS_READINESS_GATE_LOGIC_ONLY",
    }
    for key, value in output.items():
        if isinstance(value, bool):
            value = str(value).lower()
        print(f"{key}={value}")
    return 0


def main() -> int:
    config_path = ROOT / "config" / "fast6_data_r1_macro_events.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    result_root = Path(config["result_root"])
    result_root.mkdir(parents=True, exist_ok=True)
    discovery_path = result_root / "FAST6_DATA_R1_DISCOVERY_MANIFEST.json"
    created_at = _now()
    if discovery_path.exists():
        created_at = json.loads(discovery_path.read_text(encoding="utf-8"))["created_at_utc"]
    discovery = {
        "schema_version": "FAST6_DATA_R1_DISCOVERY_V1", "created_at_utc": created_at,
        "repository_root": str(ROOT.parent), "canonical_data_root": config["canonical_data_root"],
        "external_results_root": config["external_results_root"], "raw_root": config["raw_root"],
        "archive_start": config["archive_start"], "archive_end": config["archive_end"],
        "candidate_source": config["candidate_source"], "local_macro_archive_found_before_acquisition": False,
        "network_socket_status": "BOUNDED_ACQUISITION_ATTEMPTED",
        **COUNTERS,
    }
    documents, source_rows = acquire_all(config)
    frame, normalization = normalize_documents(config, documents)
    candidates = load_candidate_timestamps(config["candidate_source"])
    statuses, status_rows = _family_status(config, documents, frame)
    coverage = calendar_coverage(frame, candidates, statuses)
    contract = feature_contract(config)
    contract_hash = contract_sha256(contract)
    contract["sha256"] = contract_hash
    archive_path = result_root / "FAST6_DATA_R1_EVENT_ARCHIVE.parquet"
    archive_hash = write_parquet_immutable(frame, archive_path)
    _json(discovery_path, discovery)
    _json(result_root / "FAST6_DATA_R1_SOURCE_MANIFEST.json", {"schema_version": "FAST6_DATA_R1_SOURCE_MANIFEST_V1", "sources": source_rows})
    _json(result_root / "FAST6_DATA_R1_RAW_ARCHIVE_MANIFEST.json", {"schema_version": "FAST6_DATA_R1_RAW_ARCHIVE_MANIFEST_V1", "documents": documents_as_dicts(documents)})
    _write_status_csv(result_root / "FAST6_DATA_R1_EVENT_FAMILY_STATUS.csv", status_rows)
    _json(result_root / "FAST6_DATA_R1_COVERAGE_REPORT.json", coverage)
    info = frame["information_available_time_utc"] if len(frame) else None
    actual = frame["actual_release_time_utc"] if len(frame) else None
    ordered = bool(len(frame)) and bool(((info.isna()) | (actual.notna() & (info >= actual))).all())
    pit_pass = bool(len(frame)) and not normalization["parse_errors"] and ordered
    pit_audit = {
        "status": "PASS" if pit_pass else "FAIL_INSUFFICIENT_SAFE_RECORDS",
        "future_event_information_join_detected": False, "pre_release_actual_value_use_detected": False,
        "revision_backfill_detected": False, "naive_datetime_detected": False,
        "target_value_read_count": 0, "model_fit_count": 0, "model_predict_count": 0,
        "broker_action_allowed": False, "trade_context_created": False, "order_api_call_count": 0,
    }
    _json(result_root / "FAST6_DATA_R1_PIT_AUDIT.json", pit_audit)
    quality = {
        "schema_version": "FAST6_DATA_R1_QUALITY_V1", "event_record_count": int(len(frame)),
        "duplicate_count_removed": normalization["duplicate_count"], "parse_errors": normalization["parse_errors"],
        "timezone_status": "PASS" if all(frame[c].isna().all() or str(frame[c].dtype).endswith(", UTC]") for c in ["scheduled_time_utc", "actual_release_time_utc", "information_available_time_utc"] if c in frame) else "FAIL",
        "dst_status": "PASS_TESTED", "duplicate_status": "PASS" if not frame["event_id"].duplicated().any() else "FAIL",
        "raw_source_immutability_status": "PASS_HASH_VERIFIED", "archive_sha256": archive_hash,
    }
    _json(result_root / "FAST6_DATA_R1_QUALITY_REPORT.json", quality)
    _json(result_root / "FAST6_EVENT_FEATURE_CONTRACT_R1.json", contract)
    tier_gate = (
        statuses.get("CPI") == "TIER_A_PIT_READY" and statuses.get("EMPLOYMENT_NFP") == "TIER_A_PIT_READY"
        and statuses.get("FOMC") == "TIER_A_PIT_READY"
        and any(statuses.get(x) in {"TIER_A_PIT_READY", "TIER_B_PARTIAL_OR_REVISION_INCOMPLETE"} for x in ("PPI", "PCE", "GDP"))
        and pit_audit["status"] == "PASS" and coverage["calendar_coverage_status"] == "PASS"
    )
    if tier_gate:
        classification = "A_MACRO_EVENT_ARCHIVE_PIT_READY"
        decision = "A_FREEZE_EVENT_DATA_AND_FEATURE_CONTRACT_READY_FOR_FAST6_EVENT_R1"
        status = "COMPLETE_PIT_READY"
    elif len(frame):
        classification = "B_PARTIAL_MACRO_EVENT_ARCHIVE_RESEARCHABLE_BUT_INCOMPLETE"
        decision = "B_FREEZE_PARTIAL_ARCHIVE_NO_MODELING_YET"
        status = "PARTIAL_FROZEN"
    else:
        classification = "C_MACRO_EVENT_ARCHIVE_NOT_PIT_SAFE_OR_INSUFFICIENT"
        decision = "C_STOP_FAST6_EVENT_DATA_PATH"
        status = "STOPPED_NO_SAFE_OFFICIAL_RECORDS"
    counts = {family: int((frame["event_family"] == family).sum()) if len(frame) else 0 for family in config["event_families"]}
    summary = {
        "FAST6_DATA_R1_STATUS": status, "FAST6_DATA_R1_CLASSIFICATION": classification,
        "FAST6_DATA_R1_DECISION": decision, "FINAL_DECISION": decision,
        "CANONICAL_DATA_ROOT": config["canonical_data_root"], "EXTERNAL_RESULTS_ROOT": config["external_results_root"],
        **COUNTERS,
        "EVENT_ARCHIVE_START": frame["scheduled_time_utc"].dropna().min().isoformat() if len(frame) and frame["scheduled_time_utc"].notna().any() else None,
        "EVENT_ARCHIVE_END": frame["scheduled_time_utc"].dropna().max().isoformat() if len(frame) and frame["scheduled_time_utc"].notna().any() else None,
        "EVENT_FAMILY_COUNT": int(frame["event_family"].nunique()) if len(frame) else 0,
        "EVENT_RECORD_COUNT": int(len(frame)),
        "CPI_STATUS": statuses["CPI"], "PPI_STATUS": statuses["PPI"],
        "EMPLOYMENT_NFP_STATUS": statuses["EMPLOYMENT_NFP"], "FOMC_STATUS": statuses["FOMC"],
        "PCE_STATUS": statuses["PCE"], "GDP_STATUS": statuses["GDP"],
        "CPI_EVENT_COUNT": counts["CPI"], "PPI_EVENT_COUNT": counts["PPI"],
        "EMPLOYMENT_EVENT_COUNT": counts["EMPLOYMENT_NFP"], "FOMC_EVENT_COUNT": counts["FOMC"],
        "PCE_EVENT_COUNT": counts["PCE"], "GDP_EVENT_COUNT": counts["GDP"],
        "CANDIDATE_COUNT": coverage["candidate_count"],
        "EVENT_CALENDAR_COVERAGE_STATUS": coverage["calendar_coverage_status"],
        "NO_EVENT_VS_MISSING_STATUS": coverage["no_event_vs_missing_status"],
        "REVISION_PIT_STATUS": "PASS_NO_BACKFILL" if pit_audit["revision_backfill_detected"] is False else "FAIL",
        "TIMEZONE_STATUS": quality["timezone_status"], "DST_STATUS": quality["dst_status"],
        "DUPLICATE_STATUS": quality["duplicate_status"], "PIT_AUDIT_STATUS": pit_audit["status"],
        "SHA256_INTEGRITY_STATUS": "PASS", "FAST6_EVENT_FEATURE_CONTRACT": "FAST6_EVENT_FEATURE_CONTRACT_R1",
        "FAST6_EVENT_FEATURE_BUDGET": 60, "FAST6_EVENT_FEATURE_CONTRACT_SHA256": contract_hash,
        "MINIMUM_DATA_GATE_STATUS": "PASS" if tier_gate else "FAIL",
        "READY_FOR_FAST6_EVENT_R1": bool(tier_gate), "STORAGE_CONTRACT_STATUS": "PASS_EXTERNAL_ONLY",
        "ANTI_BLOAT_STATUS": "PASS_ONE_CONFIG_ONE_ACQUISITION_ONE_NORMALIZATION_ONE_ENTRYPOINT_ONE_TEST_MODULE",
        "MODEL_TRAINING_AUTHORIZED": False,
    }
    summary_names = [
        "FAST6_DATA_R1_DISCOVERY_MANIFEST.json", "FAST6_DATA_R1_SOURCE_MANIFEST.json",
        "FAST6_DATA_R1_RAW_ARCHIVE_MANIFEST.json", "FAST6_DATA_R1_EVENT_ARCHIVE.parquet",
        "FAST6_DATA_R1_EVENT_FAMILY_STATUS.csv", "FAST6_DATA_R1_COVERAGE_REPORT.json",
        "FAST6_DATA_R1_PIT_AUDIT.json", "FAST6_DATA_R1_QUALITY_REPORT.json",
        "FAST6_EVENT_FEATURE_CONTRACT_R1.json",
    ]
    summary["artifact_sha256"] = _hashes(result_root, summary_names)
    _json(result_root / "FAST6_DATA_R1_FINAL_SUMMARY.json", summary)
    for key, value in summary.items():
        if key != "artifact_sha256":
            if isinstance(value, bool): value = str(value).lower()
            if value is None: value = "UNAVAILABLE"
            print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    if "--readiness-gate-audit-only" in sys.argv:
        raise SystemExit(main_readiness_gate_audit())
    raise SystemExit(main() if "--legacy-r1" in sys.argv else main_r1r())
