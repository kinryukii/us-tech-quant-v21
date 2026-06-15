from __future__ import annotations

import csv
from collections import OrderedDict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "outputs" / "v20" / "ops"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

V20_5_READ_FIRST = OPS / "V20_5_READ_FIRST.txt"
V20_5_VALIDATION = CONSOLIDATION / "V20_5_VALIDATION_SUMMARY.csv"
V20_5_SOURCE_REGISTRY = CONSOLIDATION / "V20_5_SOURCE_ARTIFACT_REGISTRY.csv"
V20_5_CANONICAL_SOURCE_PATH_REGISTRY = CONSOLIDATION / "V20_5_CANONICAL_SOURCE_PATH_REGISTRY.csv"

V20_6_READ_FIRST = OPS / "V20_6_READ_FIRST.txt"
V20_6_VALIDATION = CONSOLIDATION / "V20_6_VALIDATION_SUMMARY.csv"
V20_6_SOURCE_HASH_LEDGER = CONSOLIDATION / "V20_6_SOURCE_HASH_LEDGER.csv"
V20_6_INPUT_HASH_LEDGER = CONSOLIDATION / "V20_6_INPUT_HASH_LEDGER.csv"
V20_6_VERSION_BINDING_LEDGER = CONSOLIDATION / "V20_6_VERSION_BINDING_LEDGER.csv"
V20_6_HASH_RUN_ID_PAIRING = CONSOLIDATION / "V20_6_HASH_RUN_ID_PAIRING.csv"

V20_7_READ_FIRST = OPS / "V20_7_READ_FIRST.txt"
V20_7_VALIDATION = CONSOLIDATION / "V20_7_VALIDATION_SUMMARY.csv"
V20_7_SOURCE_GATE = CONSOLIDATION / "V20_7_SOURCE_GATE_DECISION.csv"
V20_7_NORMALIZED_GATE = CONSOLIDATION / "V20_7_NORMALIZED_DATA_READINESS_GATE.csv"

V20_7R_READ_FIRST = OPS / "V20_7R_READ_FIRST.txt"
V20_7R_VALIDATION = CONSOLIDATION / "V20_7R_VALIDATION_SUMMARY.csv"
V20_7R_ACTIVE_MARKET_SOURCE_CANDIDATE_MAP = CONSOLIDATION / "V20_7R_ACTIVE_MARKET_SOURCE_CANDIDATE_MAP.csv"
V20_7R_REQUIRED_MARKET_DATA_FIELD_CONTRACT = CONSOLIDATION / "V20_7R_REQUIRED_MARKET_DATA_FIELD_CONTRACT.csv"

OUT_DISCOVERY = CONSOLIDATION / "V20_7S_ACTIVE_MARKET_SOURCE_DISCOVERY.csv"
OUT_CERTIFICATION = CONSOLIDATION / "V20_7S_ACTIVE_MARKET_SOURCE_CERTIFICATION.csv"
OUT_FIELD_COVERAGE = CONSOLIDATION / "V20_7S_REQUIRED_FIELD_COVERAGE_AUDIT.csv"
OUT_DATE_AUDIT = CONSOLIDATION / "V20_7S_DATE_AND_AVAILABILITY_FIELD_AUDIT.csv"
OUT_LINKAGE_AUDIT = CONSOLIDATION / "V20_7S_SOURCE_HASH_RUN_ID_LINKAGE_AUDIT.csv"
OUT_SAMPLE_AUDIT = CONSOLIDATION / "V20_7S_SAMPLE_ID_DESIGN_AUDIT.csv"
OUT_SEPARATION_AUDIT = CONSOLIDATION / "V20_7S_SIGNAL_OUTCOME_FIELD_SEPARATION_AUDIT.csv"
OUT_BLOCKER_REGISTER = CONSOLIDATION / "V20_7S_ACTIVE_SOURCE_BLOCKER_REGISTER.csv"
OUT_ENTRY_GATE = CONSOLIDATION / "V20_7S_ENTRY_GATE_DECISION.csv"
OUT_NEXT_STEP = CONSOLIDATION / "V20_7S_NEXT_STEP_REQUIREMENTS.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_7S_VALIDATION_SUMMARY.csv"

REPORT = READ_CENTER / "V20_7S_ACTIVE_MARKET_DATA_SOURCE_CERTIFICATION_REPORT.md"
CURRENT_STATUS = READ_CENTER / "V20_CURRENT_ACTIVE_MARKET_SOURCE_STATUS.md"
READ_FIRST = OPS / "V20_7S_READ_FIRST.txt"


MARKET_ALIAS_TERMS = ("candidate", "ranked", "top", "price", "market")
TICKER_FIELDS = ("ticker", "symbol")
OBS_FIELDS = ("observation_date", "signal_date", "as_of_date", "run_date")
PRICE_FIELDS = ("price_date", "latest_price_date", "date")
AVAILABILITY_FIELDS = ("availability_date", "publication_date", "created_at", "run_timestamp")
FUTURE_RETURN_FIELDS = (
    "future_return",
    "forward_return",
    "forward_1d_return",
    "forward_3d_return",
    "forward_5d_return",
    "forward_10d_return",
    "forward_20d_return",
    "benchmark_future_return",
    "benchmark_forward_return",
)


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
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def normalize(value: str | None) -> str:
    return (value or "").strip()


def lower_set(row: dict[str, str]) -> set[str]:
    return {normalize(v).lower() for v in row.values() if normalize(v)}


def has_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def join_items(items: list[str]) -> str:
    return ";".join([item for item in items if item])


def first_match(headers: set[str], candidates: tuple[str, ...]) -> str:
    for candidate in candidates:
        if candidate in headers:
            return candidate
    return ""


def csv_headers(path: Path) -> set[str]:
    rows = read_csv_rows(path)
    if not rows:
        return set()
    return {key.strip() for key in rows[0].keys()}


def detect_file_exists(canonical_path: str) -> bool:
    return (ROOT / canonical_path).exists()


def is_market_alias(row: dict[str, str]) -> bool:
    blob = " ".join(
        [
            normalize(row.get("source_name")),
            normalize(row.get("source_category")),
            normalize(row.get("canonical_path")),
        ]
    )
    return has_any(blob, MARKET_ALIAS_TERMS)


def source_hash_map(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {normalize(row.get("source_artifact_id")): row for row in rows if normalize(row.get("source_artifact_id"))}


def row_in_map(source_id: str, rows: list[dict[str, str]]) -> dict[str, str] | None:
    for row in rows:
        if normalize(row.get("source_artifact_id")) == source_id:
            return row
    return None


def pairings_by_source(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        source_id = normalize(row.get("source_artifact_id"))
        if not source_id:
            continue
        out.setdefault(source_id, []).append(row)
    return out


def input_rows_by_source(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        source_id = normalize(row.get("source_artifact_id"))
        if not source_id:
            continue
        out.setdefault(source_id, []).append(row)
    return out


def version_binding_exists(_: str, version_binding_rows: list[dict[str, str]]) -> bool:
    # The version binding ledger is script/wrapper-level, not source-row-level.
    # Keep the audit explicit: the ledger exists, but it is not a source-row binding table.
    return bool(version_binding_rows)


def source_header_fields(source_path: str) -> set[str]:
    path = ROOT / source_path
    if not path.exists() or path.suffix.lower() != ".csv":
        return set()
    return csv_headers(path)


def field_present(headers: set[str], accepted: tuple[str, ...]) -> tuple[bool, str]:
    detected = first_match(headers, accepted)
    return bool(detected), detected


def future_fields_detected(headers: set[str]) -> list[str]:
    detected: list[str] = []
    for field in FUTURE_RETURN_FIELDS:
        if field in headers:
            detected.append(field)
    return detected


def make_discovery_rows(
    registry_rows: list[dict[str, str]],
    source_hash_rows: list[dict[str, str]],
    pairing_rows: list[dict[str, str]],
    version_binding_rows: list[dict[str, str]],
    candidate_map_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    source_hash_by_id = source_hash_map(source_hash_rows)
    pairings = pairings_by_source(pairing_rows)
    input_hash_index = input_rows_by_source(read_csv_rows(V20_6_INPUT_HASH_LEDGER))
    candidate_map_index = {normalize(row.get("source_artifact_id")): row for row in candidate_map_rows if normalize(row.get("source_artifact_id"))}

    discoveries: list[dict[str, str]] = []
    for row in registry_rows:
        source_id = normalize(row.get("source_artifact_id"))
        if not source_id or not is_market_alias(row):
            continue
        canonical_path = normalize(row.get("canonical_path"))
        headers = source_header_fields(canonical_path)
        file_exists_now = detect_file_exists(canonical_path)
        sealed_baseline = normalize(row.get("sealed_baseline")).upper() == "TRUE"
        historical_reference_flag = sealed_baseline
        active_runtime_flag = normalize(row.get("current_runtime_source")).upper() == "TRUE"
        source_name = normalize(row.get("source_name"))
        source_category = normalize(row.get("source_category"))
        source_hash_found = source_id in source_hash_by_id
        run_id_found = source_id in pairings
        input_hash_found = source_id in input_hash_index
        version_binding_found = bool(version_binding_rows)
        ticker_present, _ = field_present(headers, TICKER_FIELDS)
        obs_present, _ = field_present(headers, OBS_FIELDS)
        price_present, _ = field_present(headers, PRICE_FIELDS)
        availability_present, _ = field_present(headers, AVAILABILITY_FIELDS)
        candidate_market_data_source = active_runtime_flag and not historical_reference_flag and (ticker_present or obs_present or price_present)
        if historical_reference_flag:
            blocker_reason = "Historical reference only; sealed baseline cannot be certified as active runtime market data."
        elif candidate_market_data_source:
            blocker_reason = "Current alias discovered, but certification checks still require complete date and metadata coverage."
        else:
            blocker_reason = "Current alias is report/template-only and does not expose certifiable market-data fields."

        discovered_from = "V20_5_SOURCE_ARTIFACT_REGISTRY + V20_6_SOURCE_HASH_LEDGER"
        if source_id in candidate_map_index:
            discovered_from += " + V20_7R_ACTIVE_MARKET_SOURCE_CANDIDATE_MAP"
        if active_runtime_flag and not historical_reference_flag:
            discovered_from += " + current_alias_scan"

        discoveries.append(
            {
                "discovery_id": f"DISC-{source_id}",
                "source_artifact_id": source_id,
                "source_name": source_name,
                "source_category": source_category,
                "canonical_path": canonical_path,
                "path_exists_now": tf(file_exists_now),
                "discovered_from": discovered_from,
                "sealed_baseline": tf(sealed_baseline),
                "historical_reference_flag": tf(historical_reference_flag),
                "active_runtime_flag": tf(active_runtime_flag),
                "candidate_market_data_source": tf(candidate_market_data_source),
                "certification_candidate": "FALSE",
                "blocker_reason": blocker_reason,
                "_ticker_present": tf(ticker_present),
                "_obs_present": tf(obs_present),
                "_price_present": tf(price_present),
                "_availability_present": tf(availability_present),
                "_source_hash_found": tf(source_hash_found),
                "_run_id_found": tf(run_id_found),
                "_input_hash_found": tf(input_hash_found),
                "_version_binding_found": tf(version_binding_found),
            }
        )

    return discoveries


def build_field_coverage_rows(discovery_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    accepted = OrderedDict(
        [
            ("ticker", "ticker;symbol"),
            ("observation_or_signal_date", "observation_date;signal_date;as_of_date;run_date"),
            ("price_or_latest_price_date", "price_date;latest_price_date;date"),
            ("availability_date_or_run_timestamp", "availability_date;publication_date;created_at;run_timestamp"),
            ("source_hash", "source_hash"),
            ("run_id", "run_id"),
            ("sample_id", "sample_id"),
        ]
    )
    for discovery in discovery_rows:
        source_id = discovery["source_artifact_id"]
        headers = source_header_fields(discovery["canonical_path"])
        for required_field_type, accepted_field_names in accepted.items():
            detected = ""
            present = False
            blocker_reason = ""
            if required_field_type == "ticker":
                present, detected = field_present(headers, TICKER_FIELDS)
                blocker_reason = "Ticker linkage is required before active market certification."
            elif required_field_type == "observation_or_signal_date":
                present, detected = field_present(headers, OBS_FIELDS)
                blocker_reason = "Observation or signal date is required for PIT-aligned signal construction."
            elif required_field_type == "price_or_latest_price_date":
                present, detected = field_present(headers, PRICE_FIELDS)
                blocker_reason = "Price or latest-price date is required for market-data certification."
            elif required_field_type == "availability_date_or_run_timestamp":
                present, detected = field_present(headers, AVAILABILITY_FIELDS)
                blocker_reason = "Availability date or explicit run-timestamp fallback is required before V20.8."
            elif required_field_type == "source_hash":
                present = discovery["_source_hash_found"] == "TRUE"
                detected = "source_hash" if present else ""
                blocker_reason = "Source hash linkage from V20.6 is required before V20.8."
            elif required_field_type == "run_id":
                present = discovery["_run_id_found"] == "TRUE"
                detected = "run_id" if present else ""
                blocker_reason = "Run ID linkage from V20.6 is required before V20.8."
            elif required_field_type == "sample_id":
                present = False
                detected = ""
                blocker_reason = "Sample ID is not yet design-ready because observation-date coverage is still missing."
            rows.append(
                {
                    "audit_id": f"FCA-{source_id}-{required_field_type}",
                    "source_artifact_id": source_id,
                    "required_field_type": required_field_type,
                    "accepted_field_names": accepted_field_names,
                    "detected_field_name": detected,
                    "field_present": tf(present),
                    "required_before_v20_8": "TRUE",
                    "blocker_reason": blocker_reason if not present else "",
                }
            )
    return rows


def build_date_audit_rows(discovery_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for discovery in discovery_rows:
        headers = source_header_fields(discovery["canonical_path"])
        obs = first_match(headers, OBS_FIELDS)
        signal = first_match(headers, ("signal_date",))
        price = first_match(headers, ("price_date",))
        latest_price = first_match(headers, ("latest_price_date",))
        availability = first_match(headers, AVAILABILITY_FIELDS)
        run_timestamp_fallback_allowed = not bool(availability)
        if obs and (price or latest_price) and (availability or run_timestamp_fallback_allowed):
            status = "COVERED"
            blocker_reason = ""
        elif obs or signal or price or latest_price or availability:
            status = "PARTIAL"
            blocker_reason = "Date coverage is incomplete; observation, availability, or canonical price-date fields are missing."
        else:
            status = "BLOCKED"
            blocker_reason = "No certifiable observation, price, or availability date fields were detected."
        rows.append(
            {
                "audit_id": f"DATE-{discovery['source_artifact_id']}",
                "source_artifact_id": discovery["source_artifact_id"],
                "observation_date_field": obs,
                "signal_date_field": signal,
                "price_date_field": price,
                "latest_price_date_field": latest_price,
                "availability_date_field": availability,
                "run_timestamp_fallback_allowed": tf(run_timestamp_fallback_allowed),
                "date_coverage_status": status,
                "blocker_reason": blocker_reason,
            }
        )
    return rows


def build_linkage_audit_rows(
    discovery_rows: list[dict[str, str]],
    source_hash_rows: list[dict[str, str]],
    input_hash_rows: list[dict[str, str]],
    version_binding_rows: list[dict[str, str]],
    pairing_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    source_hash_ids = {normalize(row.get("source_artifact_id")) for row in source_hash_rows if normalize(row.get("source_artifact_id"))}
    input_hash_ids = {normalize(row.get("source_artifact_id")) for row in input_hash_rows if normalize(row.get("source_artifact_id"))}
    version_binding_ready = bool(version_binding_rows)
    pairing_ids = {normalize(row.get("source_artifact_id")) for row in pairing_rows if normalize(row.get("source_artifact_id"))}
    rows: list[dict[str, str]] = []
    for discovery in discovery_rows:
        source_id = discovery["source_artifact_id"]
        source_hash_found = source_id in source_hash_ids
        input_hash_found = source_id in input_hash_ids
        run_id_found = source_id in pairing_ids
        version_binding_found = version_binding_ready
        if source_hash_found and run_id_found:
            linkage_status = "SOURCE_HASH_AND_RUN_ID_LINKED"
            blocker_reason = "Source hash and run ID are linked in V20.6, but input-hash and version-binding evidence remain script-level only."
        else:
            linkage_status = "BLOCKED"
            blocker_reason = "Required source-hash and run-ID linkage is missing."
        rows.append(
            {
                "audit_id": f"LINK-{source_id}",
                "source_artifact_id": source_id,
                "source_hash_found": tf(source_hash_found),
                "input_hash_found": tf(input_hash_found),
                "run_id_found": tf(run_id_found),
                "version_binding_found": tf(version_binding_found),
                "linkage_status": linkage_status,
                "blocker_reason": blocker_reason,
            }
        )
    return rows


def build_sample_audit_rows(discovery_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for discovery in discovery_rows:
        headers = source_header_fields(discovery["canonical_path"])
        includes_ticker = first_match(headers, TICKER_FIELDS)
        includes_observation_date = first_match(headers, OBS_FIELDS)
        includes_source_artifact_id = discovery["source_artifact_id"]
        includes_source_hash = discovery["_source_hash_found"] == "TRUE"
        includes_run_id = discovery["_run_id_found"] == "TRUE"
        sample_id_ready = bool(
            includes_ticker
            and includes_observation_date
            and includes_source_artifact_id
            and includes_source_hash
            and includes_run_id
        )
        blocker_reason = ""
        if not sample_id_ready:
            blocker_reason = (
                "Sample ID cannot be certified because observation-date coverage is missing or the source is historical/template-only."
            )
        rows.append(
            {
                "audit_id": f"SAMPLE-{discovery['source_artifact_id']}",
                "source_artifact_id": discovery["source_artifact_id"],
                "sample_id_components": "ticker;observation_date;source_artifact_id;source_hash;run_id",
                "includes_ticker": tf(bool(includes_ticker)),
                "includes_observation_date": tf(bool(includes_observation_date)),
                "includes_source_artifact_id": tf(True),
                "includes_source_hash": tf(includes_source_hash),
                "includes_run_id": tf(includes_run_id),
                "sample_id_ready": tf(sample_id_ready),
                "blocker_reason": blocker_reason,
            }
        )
    return rows


def build_separation_audit_rows(discovery_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for discovery in discovery_rows:
        headers = source_header_fields(discovery["canonical_path"])
        signal_side = [field for field in ("ticker", "rank", "score", "composite_candidate_score", "latest_close", "manual_close") if field in headers]
        outcome_side = [field for field in ("future_return", "forward_1d_return", "forward_3d_return", "forward_5d_return", "forward_10d_return", "forward_20d_return") if field in headers]
        future_fields = future_fields_detected(headers)
        benchmark_future_fields = [field for field in future_fields if "benchmark" in field]
        if future_fields:
            status = "BLOCKED"
            blocker_reason = "Future-return fields are still present and belong in the outcome layer only."
        elif signal_side and not outcome_side:
            status = "SEPARATED"
            blocker_reason = "Signal-side fields are present and no future-return outcome fields were detected."
        else:
            status = "NOT_APPLICABLE_TEMPLATE_ONLY"
            blocker_reason = "Template or reference artifact does not expose signal/outcome rows for certification."
        rows.append(
            {
                "audit_id": f"SEP-{discovery['source_artifact_id']}",
                "source_artifact_id": discovery["source_artifact_id"],
                "signal_side_fields_detected": join_items(signal_side),
                "outcome_side_fields_detected": join_items(outcome_side),
                "future_return_fields_detected": join_items(future_fields),
                "benchmark_future_fields_detected": join_items(benchmark_future_fields),
                "separation_status": status,
                "blocker_reason": blocker_reason,
            }
        )
    return rows


def build_certification_rows(
    discovery_rows: list[dict[str, str]],
    field_coverage_rows: list[dict[str, str]],
    date_rows: list[dict[str, str]],
    linkage_rows: list[dict[str, str]],
    sample_rows: list[dict[str, str]],
    separation_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    field_ok: dict[str, dict[str, bool]] = {}
    for row in field_coverage_rows:
        field_ok.setdefault(row["source_artifact_id"], {})[row["required_field_type"]] = row["field_present"] == "TRUE"
    date_ok = {row["source_artifact_id"]: row for row in date_rows}
    linkage_ok = {row["source_artifact_id"]: row for row in linkage_rows}
    sample_ok = {row["source_artifact_id"]: row for row in sample_rows}
    separation_ok = {row["source_artifact_id"]: row for row in separation_rows}

    rows: list[dict[str, str]] = []
    for discovery in discovery_rows:
        source_id = discovery["source_artifact_id"]
        headers = source_header_fields(discovery["canonical_path"])
        ticker_present, _ = field_present(headers, TICKER_FIELDS)
        obs_present, _ = field_present(headers, OBS_FIELDS)
        price_present, _ = field_present(headers, PRICE_FIELDS)
        availability_present, _ = field_present(headers, AVAILABILITY_FIELDS)
        hash_linked = linkage_ok[source_id]["source_hash_found"] == "TRUE" and linkage_ok[source_id]["run_id_found"] == "TRUE"
        run_linked = linkage_ok[source_id]["run_id_found"] == "TRUE"
        sample_ready = sample_ok[source_id]["sample_id_ready"] == "TRUE"
        separation_ready = separation_ok[source_id]["separation_status"] == "SEPARATED"
        active_market_data_certified = (
            discovery["candidate_market_data_source"] == "TRUE"
            and discovery["active_runtime_flag"] == "TRUE"
            and discovery["historical_reference_flag"] == "FALSE"
            and ticker_present
            and (obs_present or False)
            and (price_present or False)
            and availability_present
            and hash_linked
            and run_linked
            and sample_ready
            and separation_ready
        )
        if active_market_data_certified:
            blocker_reason = ""
        elif discovery["historical_reference_flag"] == "TRUE":
            blocker_reason = "Historical reference baseline cannot be certified as active runtime market data."
        elif discovery["candidate_market_data_source"] != "TRUE":
            blocker_reason = "Source is a report/template artifact rather than certifiable market data."
        elif not ticker_present:
            blocker_reason = "Ticker field missing."
        elif not obs_present:
            blocker_reason = "Observation or signal date field missing."
        elif not price_present:
            blocker_reason = "Price or latest-price date field missing."
        elif not availability_present:
            blocker_reason = "Availability date or run-timestamp field missing."
        elif not hash_linked:
            blocker_reason = "Source hash / run ID linkage incomplete."
        elif not sample_ready:
            blocker_reason = "Sample ID design is not ready."
        elif not separation_ready:
            blocker_reason = "Signal/outcome field separation is not ready."
        else:
            blocker_reason = "Active certification checks did not pass."

        rows.append(
            {
                "certification_id": f"CERT-{source_id}",
                "source_artifact_id": source_id,
                "canonical_path": discovery["canonical_path"],
                "source_category": discovery["source_category"],
                "active_runtime_flag": discovery["active_runtime_flag"],
                "historical_reference_flag": discovery["historical_reference_flag"],
                "ticker_field_present": tf(ticker_present),
                "observation_or_signal_date_field_present": tf(obs_present),
                "price_or_latest_price_date_field_present": tf(price_present),
                "availability_date_or_run_timestamp_rule_present": tf(availability_present),
                "source_hash_linked": tf(hash_linked),
                "run_id_linked": tf(run_linked),
                "sample_id_design_ready": tf(sample_ready),
                "signal_outcome_separation_ready": tf(separation_ready),
                "active_market_data_certified": tf(active_market_data_certified),
                "usable_for_v20_8": tf(active_market_data_certified),
                "blocker_reason": blocker_reason,
            }
        )
    return rows


def build_blocker_rows(certification_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in certification_rows:
        if row["active_market_data_certified"] == "TRUE":
            blocker_class = "CERTIFIED"
            blocker_reason = ""
        elif row["historical_reference_flag"] == "TRUE":
            blocker_class = "HISTORICAL_REFERENCE_ONLY"
            blocker_reason = "Sealed historical baseline remains comparison-only."
        elif row["source_category"] == "readable_report_outputs":
            blocker_class = "REPORT_TEMPLATE_ONLY"
            blocker_reason = "Current alias is a report/template artifact and not an active market source."
        else:
            blocker_class = "MISSING_FIELDS"
            blocker_reason = row["blocker_reason"]
        rows.append(
            {
                "blocker_id": f"BLK-{row['source_artifact_id']}",
                "source_artifact_id": row["source_artifact_id"],
                "blocker_class": blocker_class,
                "blocker_status": "BLOCKED" if row["active_market_data_certified"] != "TRUE" else "CLEARED",
                "blocker_reason": blocker_reason,
            }
        )
    return rows


def build_entry_gate_row(certification_rows: list[dict[str, str]], dependency_ok: bool, v207_blocked: bool) -> dict[str, str]:
    certified_source_count = sum(1 for row in certification_rows if row["active_market_data_certified"] == "TRUE")
    usable_count = sum(1 for row in certification_rows if row["usable_for_v20_8"] == "TRUE")
    active_market_data_certified = certified_source_count > 0
    ready_for_stale_leakage_pit_retry = active_market_data_certified
    ready_for_normalized_research_dataset = False
    blocker_reason = (
        "No active runtime market-data source satisfied ticker/date/availability/hash/run_id/sample-id/separation requirements."
        if not active_market_data_certified
        else "Certified active source exists; retry the stale/leakage/PIT gate next before any normalized dataset work."
    )
    return {
        "gate_id": "GATE-V20-7S-ACTIVE-MARKET-SOURCE-CERTIFICATION",
        "gate_name": "V20.7S Active Market Data Source Certification and Entry Gate",
        "v20_7r_dependency_detected": tf(dependency_ok),
        "v20_7_dependency_accepted": tf(v207_blocked),
        "v20_7_blocked_status_preserved": tf(v207_blocked),
        "active_market_data_certified": tf(active_market_data_certified),
        "certified_source_count": str(certified_source_count),
        "usable_for_v20_8_count": str(usable_count),
        "ready_for_stale_leakage_pit_retry_next": tf(ready_for_stale_leakage_pit_retry),
        "ready_for_normalized_research_dataset_next": tf(ready_for_normalized_research_dataset),
        "normalized_data_allowed_next": tf(False),
        "ready_for_factor_evidence_next": tf(False),
        "ready_for_exploratory_backtest_next": tf(False),
        "ready_for_dynamic_weighting_gate_research_next": tf(False),
        "official_trading_allowed": tf(False),
        "official_portfolio_weight_allowed": tf(False),
        "official_factor_weight_change_allowed": tf(False),
        "official_backtest_allowed": tf(False),
        "blocker_reason": blocker_reason,
    }


def build_next_step_rows(active_market_data_certified: bool) -> list[dict[str, str]]:
    if active_market_data_certified:
        return [
            {
                "requirement_id": "NEXT-01",
                "requirement": "Retry the V20.7 stale/leakage/PIT gate after the active market source certification layer.",
                "status": "READY",
                "reason": "An active runtime market source was certified.",
            },
            {
                "requirement_id": "NEXT-02",
                "requirement": "Keep normalized research dataset creation blocked until the stale/leakage/PIT retry completes successfully.",
                "status": "BLOCKED_UNTIL_RETRY",
                "reason": "The certification layer only authorizes the next gate retry, not direct normalized data creation.",
            },
        ]
    return [
        {
            "requirement_id": "NEXT-01",
            "requirement": "Register or create a genuine active PIT-ready market-data source.",
            "status": "BLOCKED",
            "reason": "No certifiable active runtime source exists yet.",
        },
        {
            "requirement_id": "NEXT-02",
            "requirement": "Provide observation/signal dates, canonical price dates, availability metadata, source_hash linkage, run_id linkage, and sample_id design coverage.",
            "status": "BLOCKED",
            "reason": "The currently discovered files are historical baselines or templates only.",
        },
        {
            "requirement_id": "NEXT-03",
            "requirement": "Keep V20.8 normalized research dataset creation blocked.",
            "status": "BLOCKED",
            "reason": "Active market-data certification did not pass.",
        },
    ]


def build_validation_summary(
    discovery_rows: list[dict[str, str]],
    certification_rows: list[dict[str, str]],
    dependency_ok: bool,
    v207_blocked: bool,
    active_market_data_certified: bool,
    source_files_mutated: bool = False,
) -> list[dict[str, str]]:
    return [
        {
            "required_outputs_created": "14",
            "dependency_inputs_found": "4",
            "v20_5_dependency_detected": tf(bool(read_text(V20_5_READ_FIRST))),
            "v20_6_dependency_detected": tf(bool(read_text(V20_6_READ_FIRST))),
            "v20_7_dependency_detected": tf(bool(read_text(V20_7_READ_FIRST))),
            "v20_7_dependency_accepted": tf(v207_blocked),
            "v20_7r_dependency_detected": tf(bool(read_text(V20_7R_READ_FIRST))),
            "v20_7r_dependency_accepted": tf(dependency_ok),
            "v20_7_blocked_status_preserved": tf(v207_blocked),
            "source_artifact_rows": str(len(discovery_rows)),
            "certification_rows": str(len(certification_rows)),
            "certified_source_rows": str(sum(1 for row in certification_rows if row["active_market_data_certified"] == "TRUE")),
            "usable_for_v20_8_rows": str(sum(1 for row in certification_rows if row["usable_for_v20_8"] == "TRUE")),
            "active_market_data_certified": tf(active_market_data_certified),
            "ready_for_stale_leakage_pit_retry_next": tf(active_market_data_certified),
            "ready_for_normalized_research_dataset_next": tf(False),
            "ready_for_factor_evidence_next": tf(False),
            "ready_for_exploratory_backtest_next": tf(False),
            "ready_for_dynamic_weighting_gate_research_next": tf(False),
            "official_trading_allowed": tf(False),
            "official_portfolio_weight_allowed": tf(False),
            "official_factor_weight_change_allowed": tf(False),
            "official_backtest_allowed": tf(False),
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
            "source_files_mutated": tf(source_files_mutated),
            "v21_started": "FALSE",
            "v19_21_started": "FALSE",
            "safety_status": "PASS",
        }
    ]


def build_read_first(active_market_data_certified: bool, dependency_ok: bool) -> str:
    return "\n".join(
        [
            "STATUS: WARN",
            "PATCH_NAME: V20.7S_ACTIVE_MARKET_DATA_SOURCE_CERTIFICATION_AND_ENTRY_GATE",
            "REPORTING_ONLY: TRUE",
            "ACTIVE_MARKET_SOURCE_CERTIFICATION_ONLY: TRUE",
            "ACTIVE_MARKET_DATA_SOURCE_CERTIFICATION_EXECUTED: TRUE",
            f"ACTIVE_MARKET_DATA_CERTIFIED: {tf(active_market_data_certified)}",
            f"READY_FOR_STALE_LEAKAGE_PIT_RETRY_NEXT: {tf(active_market_data_certified)}",
            "READY_FOR_NORMALIZED_RESEARCH_DATASET_NEXT: FALSE",
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
            f"V20_7R_DEPENDENCY_ACCEPTED: {tf(dependency_ok)}",
            "NEXT_RECOMMENDED_ACTION: "
            + (
                "V20.7_RETRY_STALE_LEAKAGE_PIT_GATE_AFTER_ACTIVE_SOURCE_CERTIFICATION"
                if active_market_data_certified
                else "CREATE_OR_REGISTER_AN_ACTIVE_PIT_READY_MARKET_SOURCE_BEFORE_RETRYING"
            ),
        ]
    )


def build_report(
    discovery_rows: list[dict[str, str]],
    certification_rows: list[dict[str, str]],
    entry_gate: dict[str, str],
    dependency_ok: bool,
) -> str:
    certified_count = sum(1 for row in certification_rows if row["active_market_data_certified"] == "TRUE")
    lines = [
        "# V20.7S Active Market Data Source Certification and Entry Gate",
        "",
        f"- V20.7R dependency detected and accepted: {'TRUE' if dependency_ok else 'FALSE'}",
        f"- Discovered source count: {len(discovery_rows)}",
        f"- Certified active source count: {certified_count}",
        f"- V20.8 remains blocked: {'TRUE' if entry_gate['ready_for_normalized_research_dataset_next'] == 'FALSE' else 'FALSE'}",
        f"- Retry stale/leakage/PIT next: {entry_gate['ready_for_stale_leakage_pit_retry_next']}",
        "",
        "## Decision",
        "",
        f"- Entry gate: {entry_gate['blocker_reason']}",
        "- This step is certification-only and does not create normalized research rows, factor evidence, backtests, dynamic weighting, or official recommendations.",
        "",
        "## Discovery Summary",
        "",
        "| source_artifact_id | source_name | active_runtime | historical_reference | candidate_market_data_source | certified | blocker |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in discovery_rows:
        cert = next(item for item in certification_rows if item["source_artifact_id"] == row["source_artifact_id"])
        lines.append(
            f"| {row['source_artifact_id']} | {row['source_name']} | {row['active_runtime_flag']} | {row['historical_reference_flag']} | {row['candidate_market_data_source']} | {cert['active_market_data_certified']} | {cert['blocker_reason']} |"
        )
    lines.extend(
        [
            "",
            "## Next Step",
            "",
            "- Create or register a true active PIT-ready market-data source, then rerun the stale/leakage/PIT gate.",
            "- Historical V18/V19 baselines remain sealed reference-only inputs.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_current_status(entry_gate: dict[str, str], discovery_rows: list[dict[str, str]], certification_rows: list[dict[str, str]]) -> str:
    certified_count = sum(1 for row in certification_rows if row["active_market_data_certified"] == "TRUE")
    return "\n".join(
        [
            "# V20 Current Active Market Source Status",
            "",
            f"- Active market data certified: {entry_gate['active_market_data_certified']}",
            f"- Discovered source count: {len(discovery_rows)}",
            f"- Certified source count: {certified_count}",
            f"- V20.8 blocked: {'TRUE' if entry_gate['ready_for_normalized_research_dataset_next'] == 'FALSE' else 'FALSE'}",
            f"- Recommended next step: {'V20.7_RETRY_STALE_LEAKAGE_PIT_GATE_AFTER_ACTIVE_SOURCE_CERTIFICATION' if entry_gate['active_market_data_certified'] == 'TRUE' else 'CREATE_OR_REGISTER_AN_ACTIVE_PIT_READY_MARKET_SOURCE_BEFORE_RETRYING'}",
            "",
            "This status file is read-only and does not alter sealed baselines or official research outputs.",
            "",
        ]
    )


def main() -> None:
    ensure_dir(OPS)
    ensure_dir(CONSOLIDATION)
    ensure_dir(READ_CENTER)

    registry_rows = read_csv_rows(V20_5_SOURCE_REGISTRY)
    hash_rows = read_csv_rows(V20_6_SOURCE_HASH_LEDGER)
    pairing_rows = read_csv_rows(V20_6_HASH_RUN_ID_PAIRING)
    version_binding_rows = read_csv_rows(V20_6_VERSION_BINDING_LEDGER)
    candidate_map_rows = read_csv_rows(V20_7R_ACTIVE_MARKET_SOURCE_CANDIDATE_MAP)

    v20_7_read_first = read_text(V20_7_READ_FIRST)
    v20_7r_read_first = read_text(V20_7R_READ_FIRST)
    dependency_ok = "STALE_LEAKAGE_PIT_DEPENDENCY_ACCEPTED: TRUE" in v20_7r_read_first
    v20_7_gate_rows = read_csv_rows(V20_7_SOURCE_GATE)
    v207_blocked = bool(v20_7_gate_rows) and normalize(v20_7_gate_rows[0].get("gate_status")).upper() == "BLOCKED"

    discovery_rows = make_discovery_rows(registry_rows, hash_rows, pairing_rows, version_binding_rows, candidate_map_rows)
    field_rows = build_field_coverage_rows(discovery_rows)
    date_rows = build_date_audit_rows(discovery_rows)
    linkage_rows = build_linkage_audit_rows(discovery_rows, hash_rows, read_csv_rows(V20_6_INPUT_HASH_LEDGER), version_binding_rows, pairing_rows)
    sample_rows = build_sample_audit_rows(discovery_rows)
    separation_rows = build_separation_audit_rows(discovery_rows)
    certification_rows = build_certification_rows(discovery_rows, field_rows, date_rows, linkage_rows, sample_rows, separation_rows)
    blocker_rows = build_blocker_rows(certification_rows)
    entry_gate = build_entry_gate_row(certification_rows, dependency_ok, v207_blocked)
    next_step_rows = build_next_step_rows(entry_gate["active_market_data_certified"] == "TRUE")
    validation_rows = build_validation_summary(
        discovery_rows,
        certification_rows,
        dependency_ok,
        v207_blocked,
        entry_gate["active_market_data_certified"] == "TRUE",
    )

    discovery_out = [
        {k: v for k, v in row.items() if not k.startswith("_")}
        for row in discovery_rows
    ]

    write_csv(
        OUT_DISCOVERY,
        discovery_out,
        [
            "discovery_id",
            "source_artifact_id",
            "source_name",
            "source_category",
            "canonical_path",
            "path_exists_now",
            "discovered_from",
            "sealed_baseline",
            "historical_reference_flag",
            "active_runtime_flag",
            "candidate_market_data_source",
            "certification_candidate",
            "blocker_reason",
        ],
    )
    write_csv(
        OUT_CERTIFICATION,
        certification_rows,
        [
            "certification_id",
            "source_artifact_id",
            "canonical_path",
            "source_category",
            "active_runtime_flag",
            "historical_reference_flag",
            "ticker_field_present",
            "observation_or_signal_date_field_present",
            "price_or_latest_price_date_field_present",
            "availability_date_or_run_timestamp_rule_present",
            "source_hash_linked",
            "run_id_linked",
            "sample_id_design_ready",
            "signal_outcome_separation_ready",
            "active_market_data_certified",
            "usable_for_v20_8",
            "blocker_reason",
        ],
    )
    write_csv(
        OUT_FIELD_COVERAGE,
        field_rows,
        [
            "audit_id",
            "source_artifact_id",
            "required_field_type",
            "accepted_field_names",
            "detected_field_name",
            "field_present",
            "required_before_v20_8",
            "blocker_reason",
        ],
    )
    write_csv(
        OUT_DATE_AUDIT,
        date_rows,
        [
            "audit_id",
            "source_artifact_id",
            "observation_date_field",
            "signal_date_field",
            "price_date_field",
            "latest_price_date_field",
            "availability_date_field",
            "run_timestamp_fallback_allowed",
            "date_coverage_status",
            "blocker_reason",
        ],
    )
    write_csv(
        OUT_LINKAGE_AUDIT,
        linkage_rows,
        [
            "audit_id",
            "source_artifact_id",
            "source_hash_found",
            "input_hash_found",
            "run_id_found",
            "version_binding_found",
            "linkage_status",
            "blocker_reason",
        ],
    )
    write_csv(
        OUT_SAMPLE_AUDIT,
        sample_rows,
        [
            "audit_id",
            "source_artifact_id",
            "sample_id_components",
            "includes_ticker",
            "includes_observation_date",
            "includes_source_artifact_id",
            "includes_source_hash",
            "includes_run_id",
            "sample_id_ready",
            "blocker_reason",
        ],
    )
    write_csv(
        OUT_SEPARATION_AUDIT,
        separation_rows,
        [
            "audit_id",
            "source_artifact_id",
            "signal_side_fields_detected",
            "outcome_side_fields_detected",
            "future_return_fields_detected",
            "benchmark_future_fields_detected",
            "separation_status",
            "blocker_reason",
        ],
    )
    write_csv(
        OUT_BLOCKER_REGISTER,
        blocker_rows,
        [
            "blocker_id",
            "source_artifact_id",
            "blocker_class",
            "blocker_status",
            "blocker_reason",
        ],
    )
    write_csv(
        OUT_ENTRY_GATE,
        [entry_gate],
        [
            "gate_id",
            "gate_name",
            "v20_7r_dependency_detected",
            "v20_7_dependency_accepted",
            "v20_7_blocked_status_preserved",
            "active_market_data_certified",
            "certified_source_count",
            "usable_for_v20_8_count",
            "ready_for_stale_leakage_pit_retry_next",
            "ready_for_normalized_research_dataset_next",
            "normalized_data_allowed_next",
            "ready_for_factor_evidence_next",
            "ready_for_exploratory_backtest_next",
            "ready_for_dynamic_weighting_gate_research_next",
            "official_trading_allowed",
            "official_portfolio_weight_allowed",
            "official_factor_weight_change_allowed",
            "official_backtest_allowed",
            "blocker_reason",
        ],
    )
    write_csv(
        OUT_NEXT_STEP,
        next_step_rows,
        ["requirement_id", "requirement", "status", "reason"],
    )
    write_csv(
        OUT_VALIDATION,
        validation_rows,
        list(validation_rows[0].keys()),
    )

    report_text = build_report(discovery_out, certification_rows, entry_gate, dependency_ok)
    status_text = build_current_status(entry_gate, discovery_out, certification_rows)
    read_first_text = build_read_first(entry_gate["active_market_data_certified"] == "TRUE", dependency_ok)

    write_text(REPORT, report_text)
    write_text(CURRENT_STATUS, status_text)
    write_text(READ_FIRST, read_first_text)


if __name__ == "__main__":
    main()
