from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "outputs" / "v20" / "ops"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

V20_5_READ_FIRST = OPS / "V20_5_READ_FIRST.txt"
V20_5_SOURCE_REGISTRY = CONSOLIDATION / "V20_5_SOURCE_ARTIFACT_REGISTRY.csv"
V20_6_READ_FIRST = OPS / "V20_6_READ_FIRST.txt"
V20_6_SOURCE_HASH_LEDGER = CONSOLIDATION / "V20_6_SOURCE_HASH_LEDGER.csv"
V20_6_HASH_RUN_ID_PAIRING = CONSOLIDATION / "V20_6_HASH_RUN_ID_PAIRING.csv"
V20_6_VERSION_BINDING_LEDGER = CONSOLIDATION / "V20_6_VERSION_BINDING_LEDGER.csv"
V20_7R_READ_FIRST = OPS / "V20_7R_READ_FIRST.txt"
V20_7S_READ_FIRST = OPS / "V20_7S_READ_FIRST.txt"
V20_7S_ENTRY_GATE = CONSOLIDATION / "V20_7S_ENTRY_GATE_DECISION.csv"

OUT_DISCOVERY = CONSOLIDATION / "V20_7T_ACTIVE_MARKET_INPUT_DISCOVERY.csv"
OUT_REGISTRATION = CONSOLIDATION / "V20_7T_ACTIVE_MARKET_INPUT_REGISTRATION.csv"
OUT_FIELD_CONTRACT = CONSOLIDATION / "V20_7T_ACTIVE_MARKET_INPUT_FIELD_CONTRACT.csv"
OUT_TEMPLATE = CONSOLIDATION / "V20_7T_ACTIVE_MARKET_INPUT_TEMPLATE.csv"
OUT_HASH_RUN_REQ = CONSOLIDATION / "V20_7T_ACTIVE_MARKET_INPUT_HASH_RUN_REQUIREMENTS.csv"
OUT_SAMPLE_CONTRACT = CONSOLIDATION / "V20_7T_ACTIVE_MARKET_INPUT_SAMPLE_ID_CONTRACT.csv"
OUT_SEPARATION_CONTRACT = CONSOLIDATION / "V20_7T_SIGNAL_OUTCOME_SEPARATION_CONTRACT.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_7T_REGISTRATION_BLOCKER_REGISTER.csv"
OUT_NEXT_REQ = CONSOLIDATION / "V20_7T_NEXT_CERTIFICATION_REQUIREMENTS.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_7T_VALIDATION_SUMMARY.csv"

REPORT = READ_CENTER / "V20_7T_ACTIVE_MARKET_DATA_INPUT_STAGING_REPORT.md"
CURRENT_STATUS = READ_CENTER / "V20_CURRENT_ACTIVE_MARKET_INPUT_STAGING_STATUS.md"
READ_FIRST = OPS / "V20_7T_READ_FIRST.txt"

MARKET_ALIAS_TERMS = ("candidate", "ranked", "top", "price", "market")
TICKER_FIELDS = ("ticker", "symbol")
OBS_FIELDS = ("observation_date", "signal_date", "as_of_date", "run_date")
PRICE_FIELDS = ("price_date", "latest_price_date", "date")
CLOSE_FIELDS = ("latest_close", "close")
AVAILABILITY_FIELDS = ("availability_date", "created_at", "created_at_utc", "run_timestamp", "publication_date")


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


def has_any(blob: str, terms: tuple[str, ...]) -> bool:
    lower = blob.lower()
    return any(term in lower for term in terms)


def first_match(headers: set[str], options: tuple[str, ...]) -> str:
    for option in options:
        if option in headers:
            return option
    return ""


def csv_headers(path: Path) -> set[str]:
    rows = read_csv_rows(path)
    if not rows:
        return set()
    return {key.strip() for key in rows[0].keys()}


def source_header_fields(canonical_path: str) -> set[str]:
    path = ROOT / canonical_path
    if not path.exists() or path.suffix.lower() != ".csv":
        return set()
    return csv_headers(path)


def is_current_market_like(row: dict[str, str]) -> bool:
    blob = " ".join([norm(row.get("source_name")), norm(row.get("source_category")), norm(row.get("canonical_path"))])
    return has_any(blob, MARKET_ALIAS_TERMS)


def source_hash_map(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {norm(row.get("source_artifact_id")): row for row in rows if norm(row.get("source_artifact_id"))}


def pairing_map(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {norm(row.get("source_artifact_id")): row for row in rows if norm(row.get("source_artifact_id"))}


def build_discovery_rows(
    registry_rows: list[dict[str, str]],
    source_hash_rows: list[dict[str, str]],
    pairing_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    source_hash_index = source_hash_map(source_hash_rows)
    pairing_index = pairing_map(pairing_rows)
    rows: list[dict[str, str]] = []

    for row in registry_rows:
        source_id = norm(row.get("source_artifact_id"))
        if not source_id or not is_current_market_like(row):
            continue
        sealed_baseline = norm(row.get("sealed_baseline")).upper() == "TRUE"
        active_runtime_flag = norm(row.get("current_runtime_source")).upper() == "TRUE"
        historical_reference_flag = sealed_baseline
        canonical_path = norm(row.get("canonical_path"))
        headers = source_header_fields(canonical_path)
        file_exists_now = (ROOT / canonical_path).exists()
        source_hash_linked = source_id in source_hash_index
        run_id_linked = source_id in pairing_index
        ticker_present = bool(first_match(headers, TICKER_FIELDS))
        obs_present = bool(first_match(headers, OBS_FIELDS))
        price_present = bool(first_match(headers, PRICE_FIELDS))
        close_present = bool(first_match(headers, CLOSE_FIELDS))
        availability_present = bool(first_match(headers, AVAILABILITY_FIELDS))
        has_market_input_fields = ticker_present or obs_present or price_present or close_present
        candidate_for_certification = (
            active_runtime_flag
            and not historical_reference_flag
            and has_market_input_fields
            and source_hash_linked
            and run_id_linked
            and availability_present
        )
        if historical_reference_flag:
            blocker_reason = "Sealed historical baseline remains reference-only."
        elif not has_market_input_fields:
            blocker_reason = "Current runtime alias exists, but it is template-only and lacks required market-input fields."
        elif not source_hash_linked or not run_id_linked:
            blocker_reason = "Market-like fields exist, but V20.6 lineage rebinding is missing."
        elif not availability_present:
            blocker_reason = "Market-like fields and lineage exist, but PIT freshness metadata is missing."
        elif candidate_for_certification:
            blocker_reason = ""
        else:
            blocker_reason = "Current runtime alias is not yet stageable as an active market input."

        discovered_from = "V20_5_SOURCE_ARTIFACT_REGISTRY + V20_6_SOURCE_HASH_LEDGER"
        if source_id in pairing_index:
            discovered_from += " + V20_6_HASH_RUN_ID_PAIRING"

        rows.append(
            {
                "discovery_id": f"DISC-{source_id}",
                "source_artifact_id": source_id,
                "source_name": norm(row.get("source_name")),
                "source_category": norm(row.get("source_category")),
                "canonical_path": canonical_path,
                "path_exists_now": tf(file_exists_now),
                "discovered_from": discovered_from,
                "sealed_baseline": tf(sealed_baseline),
                "historical_reference_flag": tf(historical_reference_flag),
                "active_runtime_flag": tf(active_runtime_flag),
                "candidate_market_input_source": tf(has_market_input_fields and active_runtime_flag and not historical_reference_flag),
                "staging_candidate": tf(candidate_for_certification),
                "blocker_reason": blocker_reason,
                "_ticker_present": tf(ticker_present),
                "_observation_present": tf(obs_present),
                "_price_present": tf(price_present),
                "_close_present": tf(close_present),
                "_availability_present": tf(availability_present),
                "_source_hash_linked": tf(source_hash_linked),
                "_run_id_linked": tf(run_id_linked),
                "_candidate_for_certification": tf(candidate_for_certification),
            }
        )
    return rows


def build_registration_rows(discovery_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for discovery in discovery_rows:
        ready = discovery["_candidate_for_certification"] == "TRUE"
        needs_lineage_rebinding = (
            discovery["active_runtime_flag"] == "TRUE"
            and discovery["historical_reference_flag"] == "FALSE"
            and discovery["_ticker_present"] == "TRUE"
            and discovery["_observation_present"] == "TRUE"
            and discovery["_price_present"] == "TRUE"
            and discovery["_close_present"] == "TRUE"
            and (discovery["_source_hash_linked"] != "TRUE" or discovery["_run_id_linked"] != "TRUE")
        )
        needs_freshness = (
            discovery["active_runtime_flag"] == "TRUE"
            and discovery["historical_reference_flag"] == "FALSE"
            and discovery["_ticker_present"] == "TRUE"
            and discovery["_observation_present"] == "TRUE"
            and discovery["_price_present"] == "TRUE"
            and discovery["_close_present"] == "TRUE"
            and discovery["_source_hash_linked"] == "TRUE"
            and discovery["_run_id_linked"] == "TRUE"
            and discovery["_availability_present"] != "TRUE"
        )
        if ready:
            status = "CANDIDATE_FOR_CERTIFICATION"
            blocker_reason = "All minimum input and lineage requirements are staged."
        elif discovery["historical_reference_flag"] == "TRUE":
            status = "BLOCKED_REFERENCE_ONLY"
            blocker_reason = "Historical reference cannot be staged as an active market input."
        elif discovery["_ticker_present"] != "TRUE" and discovery["_observation_present"] != "TRUE":
            status = "BLOCKED_TEMPLATE_ONLY"
            blocker_reason = "Template-only alias lacks ticker, observation/signal date, price date, and close fields."
        elif needs_lineage_rebinding:
            status = "NEEDS_LINEAGE_REBINDING"
            blocker_reason = "Market-input fields exist, but source_hash/run_id linkage is incomplete."
        elif needs_freshness:
            status = "NEEDS_PIT_FRESHNESS_CERTIFICATION"
            blocker_reason = "Market-input fields and lineage exist, but freshness metadata is missing."
        else:
            status = "BLOCKED_TEMPLATE_ONLY"
            blocker_reason = "Current runtime alias is not yet a certifiable active market input."

        rows.append(
            {
                "registration_id": f"REG-{discovery['source_artifact_id']}",
                "source_artifact_id": discovery["source_artifact_id"],
                "canonical_path": discovery["canonical_path"],
                "source_category": discovery["source_category"],
                "active_runtime_flag": discovery["active_runtime_flag"],
                "historical_reference_flag": discovery["historical_reference_flag"],
                "ticker_field_present": discovery["_ticker_present"],
                "observation_or_signal_date_field_present": discovery["_observation_present"],
                "price_or_latest_price_date_field_present": discovery["_price_present"],
                "latest_close_or_close_present": discovery["_close_present"],
                "availability_date_or_created_at_present": discovery["_availability_present"],
                "source_hash_linked": discovery["_source_hash_linked"],
                "run_id_linked": discovery["_run_id_linked"],
                "sample_id_ready": tf(ready),
                "candidate_for_certification": tf(ready),
                "needs_lineage_rebinding": tf(needs_lineage_rebinding),
                "needs_pit_freshness_certification": tf(needs_freshness),
                "active_market_input_ready": tf(ready),
                "registration_status": status,
                "blocker_reason": blocker_reason,
            }
        )
    return rows


def build_field_contract_rows() -> list[dict[str, str]]:
    rows = []
    entries = [
        ("MIN-01", "minimum_input", "ticker", "ticker;symbol", "required", "BLOCKED", "Ticker is required before active market input staging."),
        ("MIN-02", "minimum_input", "observation_or_signal_date", "observation_date;signal_date;as_of_date;run_date", "required", "BLOCKED", "Observation or signal date is required."),
        ("MIN-03", "minimum_input", "price_or_latest_price_date", "price_date;latest_price_date", "required", "BLOCKED", "Price-date coverage is required."),
        ("MIN-04", "minimum_input", "latest_close_or_close", "latest_close;close", "required", "BLOCKED", "Latest close or close is required."),
        ("MIN-05", "minimum_input", "source_artifact_id", "source_artifact_id", "required", "BLOCKED", "Source artifact identity is required."),
        ("MIN-06", "minimum_input", "source_hash", "source_hash", "required", "BLOCKED", "Source hash from V20.6 is required."),
        ("MIN-07", "minimum_input", "run_id", "run_id", "required", "BLOCKED", "Run ID from V20.6 is required."),
        ("MIN-08", "minimum_input", "active_runtime_flag", "active_runtime_flag", "required", "BLOCKED", "Active runtime flag must be TRUE."),
        ("MIN-09", "minimum_input", "historical_reference_flag", "historical_reference_flag", "required", "BLOCKED", "Historical reference flag must be FALSE for active inputs."),
        ("MIN-10", "minimum_input", "sample_id_or_components", "sample_id;sample_id_components", "required", "BLOCKED", "Sample identity contract is required."),
        ("FRSH-01", "freshness", "availability_date", "availability_date;created_at;created_at_utc;run_timestamp;publication_date", "required_before_retry", "BLOCKED", "PIT freshness metadata is required before certification retry."),
    ]
    for contract_id, contract_group, required_field_name, accepted_field_names, required_now, current_status, blocker_reason in entries:
        rows.append(
            {
                "contract_id": contract_id,
                "contract_group": contract_group,
                "required_field_name": required_field_name,
                "accepted_field_names": accepted_field_names,
                "required_now": required_now,
                "current_status": current_status,
                "blocker_reason": blocker_reason,
            }
        )
    return rows


def build_template_rows() -> list[dict[str, str]]:
    return [
        {
            "ticker": "TICKER_PLACEHOLDER",
            "company_name_optional": "OPTIONAL",
            "observation_date": "YYYY-MM-DD",
            "signal_date": "",
            "price_date": "",
            "latest_price_date": "YYYY-MM-DD",
            "latest_close": "0.00",
            "source_artifact_id": "NEW_ACTIVE_RUNTIME_SOURCE",
            "source_hash": "SOURCE_HASH_FROM_V20_6",
            "run_id": "V20.6-RUN-001",
            "sample_id": "ticker|observation_date|source_artifact_id|source_hash|run_id",
            "active_runtime_flag": "TRUE",
            "historical_reference_flag": "FALSE",
            "signal_side_allowed_fields": "ticker;observation_date;signal_date;price_date;latest_price_date;latest_close;availability_date;created_at_utc",
            "outcome_side_blocked_fields": "future_return;forward_return;benchmark_future_return;forward_1d_return;forward_3d_return;forward_5d_return;forward_10d_return;forward_20d_return",
            "availability_date": "availability_date_required_or_created_at_utc",
            "created_at_utc": "created_at_utc_placeholder",
        }
    ]


def build_hash_run_requirements_rows(discovery_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for discovery in discovery_rows:
        rows.extend(
            [
                {
                    "requirement_id": f"HR-{discovery['source_artifact_id']}-01",
                    "source_artifact_id": discovery["source_artifact_id"],
                    "requirement_name": "source_hash linkage",
                    "required_field_name": "source_hash",
                    "accepted_sources": "V20.6_SOURCE_HASH_LEDGER",
                    "status": "SATISFIED" if discovery["_source_hash_linked"] == "TRUE" else "BLOCKED",
                    "blocker_reason": "" if discovery["_source_hash_linked"] == "TRUE" else "Source hash linkage is missing.",
                },
                {
                    "requirement_id": f"HR-{discovery['source_artifact_id']}-02",
                    "source_artifact_id": discovery["source_artifact_id"],
                    "requirement_name": "run_id linkage",
                    "required_field_name": "run_id",
                    "accepted_sources": "V20.6_HASH_RUN_ID_PAIRING",
                    "status": "SATISFIED" if discovery["_run_id_linked"] == "TRUE" else "BLOCKED",
                    "blocker_reason": "" if discovery["_run_id_linked"] == "TRUE" else "Run ID linkage is missing.",
                },
                {
                    "requirement_id": f"HR-{discovery['source_artifact_id']}-03",
                    "source_artifact_id": discovery["source_artifact_id"],
                    "requirement_name": "version binding support",
                    "required_field_name": "version_binding",
                    "accepted_sources": "V20.6_VERSION_BINDING_LEDGER",
                    "status": "SATISFIED" if read_csv_rows(V20_6_VERSION_BINDING_LEDGER) else "BLOCKED",
                    "blocker_reason": "" if read_csv_rows(V20_6_VERSION_BINDING_LEDGER) else "Version binding ledger is unavailable.",
                },
            ]
        )
    return rows


def build_sample_contract_rows(discovery_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for discovery in discovery_rows:
        sample_ready = (
            discovery["_ticker_present"] == "TRUE"
            and discovery["_observation_present"] == "TRUE"
            and discovery["_source_hash_linked"] == "TRUE"
            and discovery["_run_id_linked"] == "TRUE"
        )
        rows.append(
            {
                "contract_id": f"SAMPLE-{discovery['source_artifact_id']}",
                "source_artifact_id": discovery["source_artifact_id"],
                "sample_id_components": "ticker;observation_date;source_artifact_id;source_hash;run_id",
                "includes_ticker": discovery["_ticker_present"],
                "includes_observation_date": discovery["_observation_present"],
                "includes_source_artifact_id": "TRUE",
                "includes_source_hash": discovery["_source_hash_linked"],
                "includes_run_id": discovery["_run_id_linked"],
                "sample_id_ready": tf(sample_ready),
                "blocker_reason": "" if sample_ready else "Sample ID cannot be staged until the minimum market input fields exist.",
            }
        )
    return rows


def build_separation_rows(discovery_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for discovery in discovery_rows:
        headers = source_header_fields(discovery["canonical_path"])
        signal_fields = [f for f in ("ticker", "observation_date", "signal_date", "price_date", "latest_price_date", "latest_close") if f in headers]
        outcome_fields = [f for f in ("future_return", "forward_return", "benchmark_future_return", "forward_1d_return", "forward_3d_return", "forward_5d_return", "forward_10d_return", "forward_20d_return") if f in headers]
        if outcome_fields:
            status = "BLOCKED"
            blocker_reason = "Outcome-side future-return fields are not allowed in the input staging layer."
        elif signal_fields:
            status = "SEPARATED"
            blocker_reason = ""
        else:
            status = "TEMPLATE_ONLY"
            blocker_reason = "Template-only alias has no market-input columns to separate."
        rows.append(
            {
                "contract_id": f"SEP-{discovery['source_artifact_id']}",
                "source_artifact_id": discovery["source_artifact_id"],
                "signal_side_allowed_fields": "ticker;observation_date;signal_date;price_date;latest_price_date;latest_close;availability_date;created_at_utc",
                "outcome_side_blocked_fields": "future_return;forward_return;benchmark_future_return;forward_1d_return;forward_3d_return;forward_5d_return;forward_10d_return;forward_20d_return",
                "signal_side_fields_detected": ";".join(signal_fields),
                "outcome_side_fields_detected": ";".join(outcome_fields),
                "separation_status": status,
                "blocker_reason": blocker_reason,
            }
        )
    return rows


def build_blocker_rows(registration_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for row in registration_rows:
        rows.append(
            {
                "blocker_id": f"BLK-{row['source_artifact_id']}",
                "source_artifact_id": row["source_artifact_id"],
                "blocker_class": row["registration_status"],
                "blocker_status": "BLOCKED" if row["active_market_input_ready"] != "TRUE" else "CLEARED",
                "blocker_reason": row["blocker_reason"],
            }
        )
    return rows


def build_next_requirements_rows(active_market_input_ready: bool, discovery_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    if active_market_input_ready:
        return [
            {
                "requirement_id": "NEXT-01",
                "requirement_name": "Retry V20.7S active market source certification",
                "source_of_truth": "V20.7T staging",
                "current_status": "READY",
                "blocker_reason": "Active market input is staged and linked.",
            }
        ]
    missing = discovery_rows[0] if discovery_rows else None
    blocker = "No active runtime market-input source exists."
    if missing:
        blocker = (
            f"Provide a non-historical CSV with ticker, observation_date or signal_date, price_date or latest_price_date, "
            f"latest_close or close, source_artifact_id, source_hash, run_id, active_runtime_flag=TRUE, "
            f"historical_reference_flag=FALSE, sample_id or sample_id_components, availability_date or created_at_utc. "
            f"Current alias discovered: {missing['source_name']} ({missing['canonical_path']}) is template-only."
        )
    return [
        {
            "requirement_id": "REQ-01",
            "requirement_name": "Provide an active runtime market-input file",
            "source_of_truth": "V20.7T discovery",
            "current_status": "BLOCKED",
            "blocker_reason": blocker,
        },
        {
            "requirement_id": "REQ-02",
            "requirement_name": "Bind source_hash and run_id through V20.6 lineage ledgers",
            "source_of_truth": "V20.6 lineage",
            "current_status": "BLOCKED",
            "blocker_reason": "Existing current alias is template-only; a real market-input file is still required.",
        },
        {
            "requirement_id": "REQ-03",
            "requirement_name": "Retry V20.7S only after staging is complete",
            "source_of_truth": "V20.7S entry gate",
            "current_status": "BLOCKED",
            "blocker_reason": "ACTIVE_MARKET_INPUT_READY is FALSE.",
        },
    ]


def build_validation_summary(
    discovery_rows: list[dict[str, str]],
    registration_rows: list[dict[str, str]],
    active_market_input_ready: bool,
    dependency_ok: bool,
) -> list[dict[str, str]]:
    return [
        {
            "required_outputs_created": "10",
            "v20_7r_dependency_detected": tf(bool(read_text(V20_7R_READ_FIRST))),
            "v20_7s_dependency_detected": tf(bool(read_text(V20_7S_READ_FIRST))),
            "v20_7s_dependency_accepted": tf(dependency_ok),
            "active_market_input_staging_created": "TRUE",
            "discovered_source_rows": str(len(discovery_rows)),
            "registration_rows": str(len(registration_rows)),
            "active_market_input_ready": tf(active_market_input_ready),
            "ready_for_active_market_source_certification_retry_next": tf(active_market_input_ready),
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
    ]


def build_read_first(active_market_input_ready: bool, dependency_ok: bool) -> str:
    return "\n".join(
        [
            "STATUS: WARN",
            "PATCH_NAME: V20.7T_ACTIVE_MARKET_DATA_INPUT_STAGING_AND_REGISTRATION",
            "REPORTING_ONLY: TRUE",
            "ACTIVE_MARKET_INPUT_STAGING_ONLY: TRUE",
            "ACTIVE_MARKET_INPUT_STAGING_CREATED: TRUE",
            "ACTIVE_MARKET_DATA_CERTIFIED: FALSE",
            f"ACTIVE_MARKET_INPUT_READY: {tf(active_market_input_ready)}",
            f"READY_FOR_ACTIVE_MARKET_SOURCE_CERTIFICATION_RETRY_NEXT: {tf(active_market_input_ready)}",
            "READY_FOR_STALE_LEAKAGE_PIT_RETRY_NEXT: FALSE",
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
            f"V20_7S_DEPENDENCY_ACCEPTED: {tf(dependency_ok)}",
            "NEXT_RECOMMENDED_ACTION: "
            + (
                "V20.7S_RETRY_ACTIVE_MARKET_DATA_SOURCE_CERTIFICATION"
                if active_market_input_ready
                else "PROVIDE_A_NON_HISTORICAL_ACTIVE_MARKET_INPUT_FILE_WITH_REQUIRED_FIELDS"
            ),
        ]
    )


def build_report(
    discovery_rows: list[dict[str, str]],
    registration_rows: list[dict[str, str]],
    active_market_input_ready: bool,
    dependency_ok: bool,
) -> str:
    lines = [
        "# V20.7T Active Market Data Input Staging and Registration",
        "",
        f"- V20.7S dependency detected and accepted: {'TRUE' if dependency_ok else 'FALSE'}",
        f"- Discovered source count: {len(discovery_rows)}",
        f"- Active market input ready: {'TRUE' if active_market_input_ready else 'FALSE'}",
        f"- V20.8 remains blocked: TRUE",
        "",
        "## Decision",
        "",
        "- This step only stages input contracts and registration metadata.",
        "- It does not create normalized research rows, factor evidence, backtests, dynamic weighting, or official recommendations.",
        "",
        "## Discovery",
        "",
        "| source_artifact_id | source_name | active_runtime | historical_reference | candidate_for_certification | registration_status | blocker |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for discovery in discovery_rows:
        reg = next(item for item in registration_rows if item["source_artifact_id"] == discovery["source_artifact_id"])
        lines.append(
            f"| {discovery['source_artifact_id']} | {discovery['source_name']} | {discovery['active_runtime_flag']} | {discovery['historical_reference_flag']} | {reg['candidate_for_certification']} | {reg['registration_status']} | {reg['blocker_reason']} |"
        )
    lines.extend(
        [
            "",
            "## Next Step",
            "",
            "- Provide a non-historical runtime market-input CSV with the minimum fields listed in the staged contract, then rerun V20.7S.",
            "- Sealed V18/V19 baselines remain reference-only.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_current_status(discovery_rows: list[dict[str, str]], registration_rows: list[dict[str, str]], active_market_input_ready: bool) -> str:
    ready_count = sum(1 for row in registration_rows if row["active_market_input_ready"] == "TRUE")
    return "\n".join(
        [
            "# V20 Current Active Market Input Staging Status",
            "",
            f"- Active market input ready: {'TRUE' if active_market_input_ready else 'FALSE'}",
            f"- Discovered source count: {len(discovery_rows)}",
            f"- Ready-for-certification count: {ready_count}",
            f"- Recommended next step: {'V20.7S_RETRY_ACTIVE_MARKET_DATA_SOURCE_CERTIFICATION' if active_market_input_ready else 'PROVIDE_A_NON_HISTORICAL_ACTIVE_MARKET_INPUT_FILE_WITH_REQUIRED_FIELDS'}",
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
    source_hash_rows = read_csv_rows(V20_6_SOURCE_HASH_LEDGER)
    pairing_rows = read_csv_rows(V20_6_HASH_RUN_ID_PAIRING)

    v20_7s_entry = read_csv_rows(V20_7S_ENTRY_GATE)
    dependency_ok = "DEPENDENCY_ACCEPTED: TRUE" in read_text(V20_7S_READ_FIRST) or (
        bool(v20_7s_entry) and norm(v20_7s_entry[0].get("v20_7_dependency_accepted")).upper() == "TRUE"
    )

    discovery_rows = build_discovery_rows(registry_rows, source_hash_rows, pairing_rows)
    registration_rows = build_registration_rows(discovery_rows)
    field_contract_rows = build_field_contract_rows()
    template_rows = build_template_rows()
    hash_run_rows = build_hash_run_requirements_rows(discovery_rows)
    sample_contract_rows = build_sample_contract_rows(discovery_rows)
    separation_rows = build_separation_rows(discovery_rows)
    blocker_rows = build_blocker_rows(registration_rows)
    active_market_input_ready = any(row["active_market_input_ready"] == "TRUE" for row in registration_rows)
    next_req_rows = build_next_requirements_rows(active_market_input_ready, discovery_rows)
    validation_rows = build_validation_summary(discovery_rows, registration_rows, active_market_input_ready, dependency_ok)

    discovery_out = [{k: v for k, v in row.items() if not k.startswith("_")} for row in discovery_rows]

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
            "candidate_market_input_source",
            "staging_candidate",
            "blocker_reason",
        ],
    )
    write_csv(
        OUT_REGISTRATION,
        registration_rows,
        [
            "registration_id",
            "source_artifact_id",
            "canonical_path",
            "source_category",
            "active_runtime_flag",
            "historical_reference_flag",
            "ticker_field_present",
            "observation_or_signal_date_field_present",
            "price_or_latest_price_date_field_present",
            "latest_close_or_close_present",
            "availability_date_or_created_at_present",
            "source_hash_linked",
            "run_id_linked",
            "sample_id_ready",
            "candidate_for_certification",
            "needs_lineage_rebinding",
            "needs_pit_freshness_certification",
            "active_market_input_ready",
            "registration_status",
            "blocker_reason",
        ],
    )
    write_csv(
        OUT_FIELD_CONTRACT,
        field_contract_rows,
        ["contract_id", "contract_group", "required_field_name", "accepted_field_names", "required_now", "current_status", "blocker_reason"],
    )
    write_csv(
        OUT_TEMPLATE,
        template_rows,
        [
            "ticker",
            "company_name_optional",
            "observation_date",
            "signal_date",
            "price_date",
            "latest_price_date",
            "latest_close",
            "source_artifact_id",
            "source_hash",
            "run_id",
            "sample_id",
            "active_runtime_flag",
            "historical_reference_flag",
            "signal_side_allowed_fields",
            "outcome_side_blocked_fields",
            "availability_date",
            "created_at_utc",
        ],
    )
    write_csv(
        OUT_HASH_RUN_REQ,
        hash_run_rows,
        ["requirement_id", "source_artifact_id", "requirement_name", "required_field_name", "accepted_sources", "status", "blocker_reason"],
    )
    write_csv(
        OUT_SAMPLE_CONTRACT,
        sample_contract_rows,
        ["contract_id", "source_artifact_id", "sample_id_components", "includes_ticker", "includes_observation_date", "includes_source_artifact_id", "includes_source_hash", "includes_run_id", "sample_id_ready", "blocker_reason"],
    )
    write_csv(
        OUT_SEPARATION_CONTRACT,
        separation_rows,
        ["contract_id", "source_artifact_id", "signal_side_allowed_fields", "outcome_side_blocked_fields", "signal_side_fields_detected", "outcome_side_fields_detected", "separation_status", "blocker_reason"],
    )
    write_csv(
        OUT_BLOCKERS,
        blocker_rows,
        ["blocker_id", "source_artifact_id", "blocker_class", "blocker_status", "blocker_reason"],
    )
    write_csv(
        OUT_NEXT_REQ,
        next_req_rows,
        list(next_req_rows[0].keys()) if next_req_rows else ["requirement_id", "requirement_name", "source_of_truth", "current_status", "blocker_reason"],
    )
    write_csv(OUT_VALIDATION, validation_rows, list(validation_rows[0].keys()))

    report_text = build_report(discovery_out, registration_rows, active_market_input_ready, dependency_ok)
    status_text = build_current_status(discovery_out, registration_rows, active_market_input_ready)
    read_first_text = build_read_first(active_market_input_ready, dependency_ok)

    write_text(REPORT, report_text)
    write_text(CURRENT_STATUS, status_text)
    write_text(READ_FIRST, read_first_text)


if __name__ == "__main__":
    main()
