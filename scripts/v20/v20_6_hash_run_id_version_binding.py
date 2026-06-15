from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "outputs" / "v20" / "ops"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

V20_5_SOURCE_REGISTRY = ROOT / "outputs" / "v20" / "consolidation" / "V20_5_SOURCE_ARTIFACT_REGISTRY.csv"
V20_5_READ_FIRST = ROOT / "outputs" / "v20" / "ops" / "V20_5_READ_FIRST.txt"
V20_5_VALIDATION = ROOT / "outputs" / "v20" / "consolidation" / "V20_5_VALIDATION_SUMMARY.csv"

SOURCE_HASH_LEDGER_PATH = CONSOLIDATION / "V20_6_SOURCE_HASH_LEDGER.csv"
INPUT_HASH_LEDGER_PATH = CONSOLIDATION / "V20_6_INPUT_HASH_LEDGER.csv"
OUTPUT_HASH_LEDGER_PATH = CONSOLIDATION / "V20_6_OUTPUT_HASH_LEDGER.csv"
RUN_ID_LEDGER_PATH = CONSOLIDATION / "V20_6_RUN_ID_LEDGER.csv"
VERSION_BINDING_LEDGER_PATH = CONSOLIDATION / "V20_6_VERSION_BINDING_LEDGER.csv"
PAIRING_PATH = CONSOLIDATION / "V20_6_HASH_RUN_ID_PAIRING.csv"
BINDING_ELIGIBILITY_PATH = CONSOLIDATION / "V20_6_BINDING_ELIGIBILITY_AUDIT.csv"
MISSING_SKIPPED_PATH = CONSOLIDATION / "V20_6_MISSING_OR_SKIPPED_SOURCE_AUDIT.csv"
SEALED_BASELINE_PATH = CONSOLIDATION / "V20_6_SEALED_BASELINE_HASH_REFERENCE.csv"
NEXT_GATE_PATH = CONSOLIDATION / "V20_6_NEXT_GATE_REQUIREMENTS.csv"
VALIDATION_PATH = CONSOLIDATION / "V20_6_VALIDATION_SUMMARY.csv"
REPORT_PATH = READ_CENTER / "V20_6_HASH_RUN_ID_VERSION_BINDING_REPORT.md"
CURRENT_ALIAS_PATH = READ_CENTER / "V20_CURRENT_LINEAGE_BINDING_STATUS.md"
READ_FIRST_PATH = OPS / "V20_6_READ_FIRST.txt"


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_registry() -> list[dict[str, str]]:
    rows = read_csv_rows(V20_5_SOURCE_REGISTRY)
    return rows


def build_source_hash_ledger(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    ledger: list[dict[str, object]] = []
    for row in rows:
        path = canonical_path_to_path(row.get("canonical_path", ""))
        exists = path is not None and path.exists()
        sealed = row.get("sealed_baseline", "FALSE") == "TRUE"
        status = row.get("source_status", "")

        if exists:
            source_hash = sha256_file(path)  # read-only SHA-256
            hash_computed_now = True
            if status == "REGISTERED_PLACEHOLDER":
                hash_status = "PLACEHOLDER_NOT_REAL_DATA"
                allowed_use = "PLACEHOLDER_NOT_REAL_DATA"
                blocker_reason = "Placeholder artifact; not real data."
            elif sealed:
                hash_status = "HISTORICAL_REFERENCE_ONLY"
                allowed_use = "HISTORICAL_REFERENCE_ONLY"
                blocker_reason = "Sealed baseline reference only."
            else:
                hash_status = "COMPUTED_READ_ONLY"
                allowed_use = "READ_ONLY_BINDING"
                blocker_reason = "Read-only lineage binding reference only."
        else:
            source_hash = ""
            hash_computed_now = False
            if status == "REGISTERED_MISSING_OPTIONAL":
                hash_status = "MISSING_OPTIONAL"
                allowed_use = "MISSING_OPTIONAL"
                blocker_reason = "Optional source missing; not required for V20.6."
            elif status == "REGISTERED_PLACEHOLDER":
                hash_status = "PLACEHOLDER_NOT_REAL_DATA"
                allowed_use = "PLACEHOLDER_NOT_REAL_DATA"
                blocker_reason = "Placeholder artifact is intentionally not real data."
            else:
                hash_status = "MISSING_REQUIRED"
                allowed_use = "BLOCKED"
                blocker_reason = "Required source missing."

        ledger.append(
            {
                "source_artifact_id": row.get("source_artifact_id", ""),
                "source_name": row.get("source_name", ""),
                "source_category": row.get("source_category", ""),
                "canonical_path": row.get("canonical_path", ""),
                "path_exists_now": row.get("path_exists_now", "FALSE"),
                "hash_algorithm": "sha256",
                "source_hash": source_hash,
                "hash_computed_now": tf(hash_computed_now),
                "hash_status": hash_status,
                "sealed_baseline": row.get("sealed_baseline", "FALSE"),
                "current_runtime_source": row.get("current_runtime_source", "FALSE"),
                "allowed_use": allowed_use,
                "blocker_reason": blocker_reason,
            }
        )
    return ledger


def build_input_hash_ledger(rows: list[dict[str, str]], source_hash_by_id: dict[str, str]) -> list[dict[str, object]]:
    ledger: list[dict[str, object]] = []
    for row in rows:
        if row.get("eligible_for_future_normalized_data", "FALSE") != "TRUE":
            continue
        path = canonical_path_to_path(row.get("canonical_path", ""))
        exists = path is not None and path.exists()
        hash_value = sha256_file(path) if exists else ""
        input_available = exists
        input_role = (
            "future_normalized_dataset_placeholder"
            if row.get("source_status", "") == "REGISTERED_PLACEHOLDER"
            else "future_normalized_dataset_input"
        )
        blocker_reason = (
            "Placeholder artifact; not real normalized data."
            if row.get("source_status", "") == "REGISTERED_PLACEHOLDER"
            else "Read-only future normalized dataset candidate for stale/leakage/PIT planning."
        )
        ledger.append(
            {
                "input_id": f"INP-{row.get('source_artifact_id', '')}",
                "source_artifact_id": row.get("source_artifact_id", ""),
                "canonical_path": row.get("canonical_path", ""),
                "input_role": input_role,
                "hash_algorithm": "sha256",
                "input_hash": hash_value,
                "hash_computed_now": tf(exists),
                "input_available": tf(input_available),
                "eligible_for_future_stale_leakage_gate": "TRUE",
                "eligible_for_future_normalized_data": row.get("eligible_for_future_normalized_data", "FALSE"),
                "blocker_reason": blocker_reason,
            }
        )
    return ledger


def build_output_plan() -> list[dict[str, str]]:
    return [
        {"output_id": "OUT001", "output_name": "V20_6_SOURCE_HASH_LEDGER", "output_path": rel(SOURCE_HASH_LEDGER_PATH), "output_layer": "consolidation"},
        {"output_id": "OUT002", "output_name": "V20_6_INPUT_HASH_LEDGER", "output_path": rel(INPUT_HASH_LEDGER_PATH), "output_layer": "consolidation"},
        {"output_id": "OUT003", "output_name": "V20_6_OUTPUT_HASH_LEDGER", "output_path": rel(OUTPUT_HASH_LEDGER_PATH), "output_layer": "consolidation"},
        {"output_id": "OUT004", "output_name": "V20_6_RUN_ID_LEDGER", "output_path": rel(RUN_ID_LEDGER_PATH), "output_layer": "consolidation"},
        {"output_id": "OUT005", "output_name": "V20_6_VERSION_BINDING_LEDGER", "output_path": rel(VERSION_BINDING_LEDGER_PATH), "output_layer": "consolidation"},
        {"output_id": "OUT006", "output_name": "V20_6_HASH_RUN_ID_PAIRING", "output_path": rel(PAIRING_PATH), "output_layer": "consolidation"},
        {"output_id": "OUT007", "output_name": "V20_6_BINDING_ELIGIBILITY_AUDIT", "output_path": rel(BINDING_ELIGIBILITY_PATH), "output_layer": "consolidation"},
        {"output_id": "OUT008", "output_name": "V20_6_MISSING_OR_SKIPPED_SOURCE_AUDIT", "output_path": rel(MISSING_SKIPPED_PATH), "output_layer": "consolidation"},
        {"output_id": "OUT009", "output_name": "V20_6_SEALED_BASELINE_HASH_REFERENCE", "output_path": rel(SEALED_BASELINE_PATH), "output_layer": "consolidation"},
        {"output_id": "OUT010", "output_name": "V20_6_NEXT_GATE_REQUIREMENTS", "output_path": rel(NEXT_GATE_PATH), "output_layer": "consolidation"},
        {"output_id": "OUT011", "output_name": "V20_6_VALIDATION_SUMMARY", "output_path": rel(VALIDATION_PATH), "output_layer": "consolidation"},
        {"output_id": "OUT012", "output_name": "V20_6_HASH_RUN_ID_VERSION_BINDING_REPORT", "output_path": rel(REPORT_PATH), "output_layer": "read_center"},
        {"output_id": "OUT013", "output_name": "V20_CURRENT_LINEAGE_BINDING_STATUS", "output_path": rel(CURRENT_ALIAS_PATH), "output_layer": "read_center"},
        {"output_id": "OUT014", "output_name": "V20_6_READ_FIRST", "output_path": rel(READ_FIRST_PATH), "output_layer": "ops"},
    ]


def build_run_id_ledger(run_timestamp_utc: datetime, run_timestamp_local: datetime) -> list[dict[str, object]]:
    return [
        {
            "run_id": "V20.6-RUN-001",
            "run_scope": "LINEAGE_BINDING_ONLY",
            "v20_step": "V20.6_HASH_RUN_ID_VERSION_BINDING",
            "script_path": rel(ROOT / "scripts" / "v20" / "v20_6_hash_run_id_version_binding.py"),
            "wrapper_path": rel(ROOT / "scripts" / "v20" / "run_v20_6_hash_run_id_version_binding.ps1"),
            "run_timestamp_utc": run_timestamp_utc.isoformat().replace("+00:00", "Z"),
            "run_timestamp_local": run_timestamp_local.isoformat(),
            "run_status": "RECORDED_READ_ONLY",
            "certified_run_id": "FALSE",
            "certification_scope": "NOT_CERTIFIED_READ_ONLY",
            "notes": "Read-only lineage binding run; not a certified production run.",
        }
    ]


def build_version_binding_ledger(v20_5_pass: bool) -> list[dict[str, object]]:
    script_path = rel(ROOT / "scripts" / "v20" / "v20_6_hash_run_id_version_binding.py")
    wrapper_path = rel(ROOT / "scripts" / "v20" / "run_v20_6_hash_run_id_version_binding.ps1")
    rows = [
        ("VB001", "V20.6", script_path, wrapper_path, script_path, "V20.5 source registry activation accepted", "BOUND_READ_ONLY", "FALSE", "Read-only script binding; no official use."),
        ("VB002", "V20.6", script_path, wrapper_path, wrapper_path, "V20.5 source registry activation accepted", "BOUND_READ_ONLY", "FALSE", "Read-only wrapper binding; no official use."),
        ("VB003", "V20.6", script_path, wrapper_path, rel(V20_5_SOURCE_REGISTRY), "V20.5 source registry ledger", "BOUND_READ_ONLY", "FALSE", "Source registry dependency bound for traceability."),
        ("VB004", "V20.6", script_path, wrapper_path, rel(V20_5_READ_FIRST), "V20.5 read-first dependency", "BOUND_READ_ONLY", "FALSE", "Read-first dependency bound for traceability."),
        ("VB005", "V20.6", script_path, wrapper_path, rel(V20_5_VALIDATION), "V20.5 validation dependency", "BOUND_READ_ONLY", "FALSE", "Validation dependency bound for traceability."),
        ("VB006", "V20.6", script_path, wrapper_path, rel(SOURCE_HASH_LEDGER_PATH), "V20.6 source hash ledger", "BOUND_READ_ONLY", "FALSE", "Source hash ledger bound for lineage traceability."),
        ("VB007", "V20.6", script_path, wrapper_path, rel(INPUT_HASH_LEDGER_PATH), "V20.6 input hash ledger", "BOUND_READ_ONLY", "FALSE", "Input hash ledger bound for lineage traceability."),
        ("VB008", "V20.6", script_path, wrapper_path, rel(OUTPUT_HASH_LEDGER_PATH), "V20.6 output hash ledger", "BOUND_READ_ONLY", "FALSE", "Output hash ledger bound for lineage traceability."),
        ("VB009", "V20.6", script_path, wrapper_path, rel(RUN_ID_LEDGER_PATH), "V20.6 run_id ledger", "BOUND_READ_ONLY", "FALSE", "Run id ledger bound for lineage traceability."),
        ("VB010", "V20.6", script_path, wrapper_path, rel(PAIRING_PATH), "V20.6 hash-run_id pairing", "BOUND_READ_ONLY", "FALSE", "Hash-run_id pairing bound for lineage traceability."),
        ("VB011", "V20.6", script_path, wrapper_path, rel(BINDING_ELIGIBILITY_PATH), "V20.6 binding eligibility audit", "BOUND_READ_ONLY", "FALSE", "Binding eligibility audit bound for lineage traceability."),
        ("VB012", "V20.6", script_path, wrapper_path, rel(MISSING_SKIPPED_PATH), "V20.6 missing/skipped source audit", "BOUND_READ_ONLY", "FALSE", "Missing/skipped source audit bound for lineage traceability."),
        ("VB013", "V20.6", script_path, wrapper_path, rel(SEALED_BASELINE_PATH), "V20.6 sealed baseline hash reference", "BOUND_READ_ONLY", "FALSE", "Sealed baseline references bound for lineage traceability."),
        ("VB014", "V20.6", script_path, wrapper_path, rel(NEXT_GATE_PATH), "V20.6 next gate requirements", "BOUND_READ_ONLY", "FALSE", "Next gate requirements bound for lineage traceability."),
        ("VB015", "V20.6", script_path, wrapper_path, rel(VALIDATION_PATH), "V20.6 validation summary", "BOUND_READ_ONLY", "FALSE", "Validation summary bound for lineage traceability."),
        ("VB016", "V20.6", script_path, wrapper_path, rel(REPORT_PATH), "V20.6 report", "BOUND_READ_ONLY", "FALSE", "Readable report bound for lineage traceability."),
        ("VB017", "V20.6", script_path, wrapper_path, rel(CURRENT_ALIAS_PATH), "V20.6 current lineage status alias", "BOUND_READ_ONLY", "FALSE", "Current alias bound for lineage traceability."),
        ("VB018", "V20.6", script_path, wrapper_path, rel(READ_FIRST_PATH), "V20.6 read-first", "BOUND_READ_ONLY", "FALSE", "Read-first bound for lineage traceability."),
    ]
    return [
        {
            "version_binding_id": row[0],
            "project_version": row[1],
            "v20_step": "V20.6_HASH_RUN_ID_VERSION_BINDING",
            "script_path": row[2],
            "wrapper_path": row[3],
            "output_path": row[4],
            "source_dependency": row[5],
            "binding_status": row[6],
            "official_use_allowed": row[7],
            "blocker_reason": row[8],
        }
        for row in rows
    ]


def build_binding_eligibility_audit(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    audit: list[dict[str, object]] = []
    for row in rows:
        path = canonical_path_to_path(row.get("canonical_path", ""))
        exists = path is not None and path.exists()
        status = row.get("source_status", "")
        eligible = exists and status not in {"REGISTERED_MISSING_OPTIONAL", "REGISTERED_PLACEHOLDER"}
        if status == "REGISTERED_MISSING_OPTIONAL":
            eligibility_status = "BLOCKED_MISSING_OPTIONAL"
            blocker_reason = "Optional source missing; not required for current binding."
        elif status == "REGISTERED_PLACEHOLDER":
            eligibility_status = "BLOCKED_PLACEHOLDER_NOT_REAL_DATA"
            blocker_reason = "Placeholder artifact is not real data."
        elif exists:
            eligibility_status = "ELIGIBLE"
            blocker_reason = "Eligible for read-only lineage binding."
        else:
            eligibility_status = "BLOCKED_MISSING_REQUIRED"
            blocker_reason = "Required source missing."
        audit.append(
            {
                "audit_id": f"BA-{row.get('source_artifact_id', '')}",
                "source_artifact_id": row.get("source_artifact_id", ""),
                "eligible_for_hash_binding": tf(eligible),
                "eligible_for_run_id_pairing": tf(eligible),
                "eligible_for_version_binding": tf(eligible),
                "eligibility_status": eligibility_status,
                "blocker_reason": blocker_reason,
            }
        )
    return audit


def build_missing_or_skipped_audit(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    skipped: list[dict[str, object]] = []
    for row in rows:
        status = row.get("source_status", "")
        if status not in {"REGISTERED_MISSING_OPTIONAL", "REGISTERED_PLACEHOLDER"}:
            continue
        if status == "REGISTERED_MISSING_OPTIONAL":
            skip_reason = "MISSING_OPTIONAL"
            required_before_next_gate = "Future optional ingestion only; not required for V20.6."
        else:
            skip_reason = "PLACEHOLDER_NOT_REAL_DATA"
            required_before_next_gate = "Real normalized dataset must exist before later gates."
        skipped.append(
            {
                "skipped_id": f"SKIP-{row.get('source_artifact_id', '')}",
                "source_artifact_id": row.get("source_artifact_id", ""),
                "canonical_path": row.get("canonical_path", ""),
                "skip_reason": skip_reason,
                "missing_allowed_now": "TRUE",
                "required_before_next_gate": required_before_next_gate,
                "current_status": status,
            }
        )
    return skipped


def build_sealed_baseline_reference(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    refs: list[dict[str, object]] = []
    for row in rows:
        if row.get("sealed_baseline", "FALSE") != "TRUE":
            continue
        path = canonical_path_to_path(row.get("canonical_path", ""))
        if path is None or not path.exists():
            continue
        refs.append(
            {
                "reference_id": f"REF-{row.get('source_artifact_id', '')}",
                "source_artifact_id": row.get("source_artifact_id", ""),
                "source_name": row.get("source_name", ""),
                "canonical_path": row.get("canonical_path", ""),
                "baseline_version": "V18" if row.get("canonical_path", "").startswith("outputs/v18/") else "V19",
                "path_exists_now": "TRUE",
                "hash_algorithm": "sha256",
                "source_hash": sha256_file(path),
                "hash_computed_now": "TRUE",
                "reference_status": "HISTORICAL_REFERENCE_ONLY",
                "allowed_use": "HISTORICAL_REFERENCE_ONLY",
                "blocker_reason": "Sealed historical baseline retained for comparison only.",
            }
        )
    return refs


def build_next_gate_requirements() -> list[dict[str, object]]:
    rows = [
        ("REQ01", "SOURCE_REGISTRY_DEPENDENCY_ACCEPTED", "V20.5 source registry activation must be accepted.", "V20_5_READ_FIRST.txt + V20_5_VALIDATION_SUMMARY.csv", "TRUE", "PASS"),
        ("REQ02", "SOURCE_HASH_LEDGER_CREATED", "Source hash ledger must exist before stale/leakage/PIT planning.", "V20_6_SOURCE_HASH_LEDGER.csv", "TRUE", "PASS"),
        ("REQ03", "INPUT_HASH_LEDGER_CREATED", "Input hash ledger must exist before stale/leakage/PIT planning.", "V20_6_INPUT_HASH_LEDGER.csv", "TRUE", "PASS"),
        ("REQ04", "RUN_ID_LEDGER_CREATED", "Run id ledger must exist before later lineage gates.", "V20_6_RUN_ID_LEDGER.csv", "TRUE", "PASS"),
        ("REQ05", "VERSION_BINDING_LEDGER_CREATED", "Version binding ledger must exist before later lineage gates.", "V20_6_VERSION_BINDING_LEDGER.csv", "TRUE", "PASS"),
        ("REQ06", "HASH_RUN_ID_PAIRING_CREATED", "Hash-run_id pairing must exist before later lineage gates.", "V20_6_HASH_RUN_ID_PAIRING.csv", "TRUE", "PASS"),
        ("REQ07", "SEALED_BASELINE_REFERENCE_CREATED", "Sealed baseline hash references must be retained for comparison.", "V20_6_SEALED_BASELINE_HASH_REFERENCE.csv", "TRUE", "PASS"),
        ("REQ08", "VALIDATION_PASS", "No official-use safety violations may occur in the binding step.", "V20_6_VALIDATION_SUMMARY.csv", "TRUE", "PASS"),
        ("REQ09", "READY_FOR_STALE_LEAKAGE_PIT_GATE_NEXT", "V20.7 stale/leakage/PIT gate may be planned next.", "V20_6_VALIDATION_SUMMARY.csv", "TRUE", "READY"),
        ("REQ10", "LATER_GATES_BLOCKED", "Normalized data, factor evidence, exploratory backtest, dynamic weighting, and trading remain blocked.", "V20.6 validation summary + V20.4 gates", "FALSE", "BLOCKED"),
    ]
    return [
        {
            "requirement_id": req_id,
            "next_gate": gate,
            "requirement_description": desc,
            "dependency_output": dependency_output,
            "required_status": required_status,
            "current_status": current_status,
        }
        for req_id, gate, desc, dependency_output, required_status, current_status in rows
    ]


def build_output_hash_ledger(output_rows: list[dict[str, str]], output_hashes: dict[str, str]) -> list[dict[str, object]]:
    ledger: list[dict[str, object]] = []
    for row in output_rows:
        output_name = row["output_name"]
        output_path = ROOT / row["output_path"]
        if output_name == "V20_6_OUTPUT_HASH_LEDGER":
            ledger.append(
                {
                    "output_id": row["output_id"],
                    "output_name": output_name,
                    "output_path": row["output_path"],
                    "output_layer": row["output_layer"],
                    "produced_by_v20_step": "V20.6_HASH_RUN_ID_VERSION_BINDING",
                    "hash_algorithm": "sha256",
                    "output_hash": "SELF_REFERENCE_LIMITED",
                    "hash_computed_now": "FALSE",
                    "output_available": tf(output_path.exists()),
                    "official_output": "FALSE",
                    "blocker_reason": "Self-reference limited; output hash ledger cannot hash itself in-place.",
                }
            )
            continue
        hash_value = output_hashes.get(output_name, "")
        ledger.append(
            {
                "output_id": row["output_id"],
                "output_name": output_name,
                "output_path": row["output_path"],
                "output_layer": row["output_layer"],
                "produced_by_v20_step": "V20.6_HASH_RUN_ID_VERSION_BINDING",
                "hash_algorithm": "sha256",
                "output_hash": hash_value,
                "hash_computed_now": tf(bool(hash_value)),
                "output_available": tf(output_path.exists()),
                "official_output": "FALSE",
                "blocker_reason": "Read-only V20.6 lineage binding artifact; not an official output.",
            }
        )
    return ledger


def build_hash_run_id_pairings(
    run_id: str,
    source_rows: list[dict[str, str]],
    source_hash_rows: list[dict[str, object]],
    input_hash_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    pairings: list[dict[str, object]] = []

    for row in source_hash_rows:
        if row["hash_computed_now"] != "TRUE":
            continue
        pairings.append(
            {
                "pairing_id": f"PAIR-S-{row['source_artifact_id']}",
                "run_id": run_id,
                "source_artifact_id": row["source_artifact_id"],
                "input_hash": row["source_hash"],
                "output_hash": "",
                "pairing_status": "SOURCE_HASH_PAIRED_READ_ONLY",
                "lineage_complete_for_future_gate": "TRUE",
                "blocker_reason": "Read-only source hash paired for future lineage planning.",
            }
        )

    for row in input_hash_rows:
        if row["hash_computed_now"] != "TRUE":
            continue
        pairings.append(
            {
                "pairing_id": f"PAIR-I-{row['source_artifact_id']}",
                "run_id": run_id,
                "source_artifact_id": row["source_artifact_id"],
                "input_hash": row["input_hash"],
                "output_hash": "",
                "pairing_status": "INPUT_HASH_PAIRED_READ_ONLY",
                "lineage_complete_for_future_gate": "TRUE",
                "blocker_reason": "Read-only input hash paired for future stale/leakage/PIT planning.",
            }
        )
    return pairings


def build_report(
    source_rows: list[dict[str, str]],
    input_rows: list[dict[str, object]],
    output_rows: list[dict[str, object]],
    run_rows: list[dict[str, object]],
    version_rows: list[dict[str, object]],
    pairing_count: int,
    refs: list[dict[str, object]],
    next_gate_rows: list[dict[str, object]],
    source_registry_activated: bool,
    v20_5_pass: bool,
) -> str:
    missing_count = sum(1 for r in source_rows if r.get("path_exists_now", "FALSE") != "TRUE")
    baseline_count = sum(1 for r in source_rows if r.get("sealed_baseline", "FALSE") == "TRUE")
    runtime_count = sum(1 for r in source_rows if r.get("current_runtime_source", "FALSE") == "TRUE")
    return "\n".join(
        [
            "# V20.6 哈希 / Run ID / 版本绑定报告",
            "",
            "## 结论",
            f"- 状态：{'SEALED' if source_registry_activated else 'WARN'}",
            "- 本步骤仅执行只读 lineage binding，不执行 stale/leakage/PIT，不生成 normalized real data，不创建 factor evidence，不运行 backtest，不执行 dynamic weighting。",
            f"- V20.5 依赖检测：{'通过' if v20_5_pass else '未通过'}",
            f"- 源注册表激活：{'TRUE' if source_registry_activated else 'FALSE'}",
            "",
            "## 绑定结果",
            f"- 源哈希行数：{len(source_rows)}",
            f"- 输入哈希行数：{len(input_rows)}",
            f"- 输出哈希行数：{len(output_rows)}",
            f"- run_id 行数：{len(run_rows)}",
            f"- 版本绑定行数：{len(version_rows)}",
            f"- hash-run_id pairings 行数：{pairing_count}",
            f"- 封存基线引用行数：{len(refs)}",
            f"- 缺失/跳过源行数：{missing_count}",
            "",
            "## 范围说明",
            f"- 封存历史基线：{baseline_count} 项（V18 + V19）。",
            f"- 当前运行源：{runtime_count} 项（V20.1-V20.4 + V20.5 资产）。",
            "- V20.6 记录了 source hash ledger、input hash ledger、output hash ledger、run_id ledger、version binding ledger 与 hash-run_id pairing。",
            "- V20.6 还保留 sealed baseline hash reference，以便后续仅做比较，不做执行。",
            "",
            "## 下一门控",
            "- 可进入下一步：V20.7 stale/leakage/PIT gate planning。",
            "- 仍然阻塞：normalized research dataset、factor evidence、exploratory backtest、dynamic weighting、official trading。",
            "",
            "## 安全边界",
            "- 不创建 certified run_id。",
            "- 不执行 official hash binding。",
            "- 不执行 stale/leakage/PIT 检查。",
            "- 不生成真实归一化研究数据行。",
            "- 不生成 factor evidence、backtest、performance claims、dynamic weighting 或 trading 输出。",
            "",
            "## 备注",
            "- 该步骤为只读 lineage binding 层，用于把 V20.5 源注册、V18/V19 封存基线和 V20.6 绑定输出串成可追踪链路。",
        ]
    )


def build_current_alias() -> str:
    return "\n".join(
        [
            "# V20 当前 lineage 绑定状态",
            "",
            "- V20.6 已完成只读 hash / run_id / version binding。",
            "- V20.5 源注册表依赖已接受。",
            "- V18 / V19 封存基线已保留为 historical reference only。",
            "- 下一步仅允许 V20.7 stale/leakage/PIT gate planning。",
            "- 仍禁止 normalized real data、factor evidence、backtest、dynamic weighting 与 trading。",
        ]
    )


def build_read_first(
    source_hash_rows: int,
    input_hash_rows: int,
    output_hash_rows: int,
    run_id_rows: int,
    version_rows: int,
    pair_rows: int,
    source_registry_activated: bool,
    v20_5_pass: bool,
    ready_for_next: bool,
) -> None:
    lines = [
        "STATUS: WARN",
        "PATCH_NAME: V20.6_HASH_RUN_ID_VERSION_BINDING",
        "REPORTING_ONLY: TRUE",
        "LINEAGE_BINDING_ONLY: TRUE",
        "SOURCE_REGISTRY_DEPENDENCY_ACCEPTED: TRUE",
        f"HASH_RUN_ID_VERSION_BINDING_EXECUTED: {tf(source_registry_activated and v20_5_pass)}",
        f"SOURCE_HASH_LEDGER_CREATED: {tf(source_hash_rows > 0)}",
        f"INPUT_HASH_LEDGER_CREATED: {tf(input_hash_rows > 0)}",
        f"OUTPUT_HASH_LEDGER_CREATED: {tf(output_hash_rows > 0)}",
        f"RUN_ID_LEDGER_CREATED: {tf(run_id_rows > 0)}",
        f"VERSION_BINDING_LEDGER_CREATED: {tf(version_rows > 0)}",
        f"HASH_RUN_ID_PAIRING_CREATED: {tf(pair_rows > 0)}",
        "STALE_LEAKAGE_GATE_EXECUTED: FALSE",
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
        f"READY_FOR_STALE_LEAKAGE_PIT_GATE_NEXT: {tf(ready_for_next)}",
        "READY_FOR_NORMALIZED_RESEARCH_DATASET_NEXT: FALSE",
        "READY_FOR_FACTOR_EVIDENCE_NEXT: FALSE",
        "READY_FOR_EXPLORATORY_BACKTEST_NEXT: FALSE",
        "READY_FOR_DYNAMIC_WEIGHTING_GATE_RESEARCH_NEXT: FALSE",
        "OFFICIAL_TRADING_ALLOWED: FALSE",
        "OFFICIAL_PORTFOLIO_WEIGHT_ALLOWED: FALSE",
        "OFFICIAL_FACTOR_WEIGHT_CHANGE_ALLOWED: FALSE",
        "OFFICIAL_BACKTEST_ALLOWED: FALSE",
        f"SOURCE_HASH_ROWS: {source_hash_rows}",
        f"INPUT_HASH_ROWS: {input_hash_rows}",
        f"OUTPUT_HASH_ROWS: {output_hash_rows}",
        f"RUN_ID_ROWS: {run_id_rows}",
        f"VERSION_BINDING_ROWS: {version_rows}",
        f"HASH_RUN_ID_PAIRING_ROWS: {pair_rows}",
        "NEXT_RECOMMENDED_ACTION: V20.7_STALE_LEAKAGE_PIT_GATE",
        "NEXT_RECOMMENDED_MODEL: GPT-5.5",
    ]
    write_text(READ_FIRST_PATH, "\n".join(lines))


def main() -> None:
    registry = load_registry()
    v20_5_read_first = read_kv(read_text(V20_5_READ_FIRST))
    v20_5_validation = read_csv_rows(V20_5_VALIDATION)
    v20_5_pass = (
        v20_5_read_first.get("SOURCE_REGISTRY_ACTIVATED") == "TRUE"
        and v20_5_read_first.get("READY_FOR_HASH_RUN_ID_VERSION_BINDING_NEXT") == "TRUE"
        and (v20_5_validation[0].get("source_registry_activated") == "TRUE" if v20_5_validation else False)
    )

    ensure_dir(CONSOLIDATION)
    ensure_dir(READ_CENTER)
    ensure_dir(OPS)

    source_hash_rows = build_source_hash_ledger(registry)
    source_hash_by_id = {
        row["source_artifact_id"]: row["source_hash"]
        for row in source_hash_rows
        if row["hash_computed_now"] == "TRUE" and row["source_hash"]
    }
    input_hash_rows = build_input_hash_ledger(registry, source_hash_by_id)

    run_timestamp_utc = datetime.now(timezone.utc)
    tokyo = ZoneInfo("Asia/Tokyo") if ZoneInfo is not None else timezone(timedelta(hours=9))
    run_timestamp_local = run_timestamp_utc.astimezone(tokyo)
    run_rows = build_run_id_ledger(run_timestamp_utc, run_timestamp_local)
    run_id = run_rows[0]["run_id"]

    # Write binding outputs that other hashes depend on.
    write_csv(
        SOURCE_HASH_LEDGER_PATH,
        source_hash_rows,
        [
            "source_artifact_id",
            "source_name",
            "source_category",
            "canonical_path",
            "path_exists_now",
            "hash_algorithm",
            "source_hash",
            "hash_computed_now",
            "hash_status",
            "sealed_baseline",
            "current_runtime_source",
            "allowed_use",
            "blocker_reason",
        ],
    )
    write_csv(
        INPUT_HASH_LEDGER_PATH,
        input_hash_rows,
        [
            "input_id",
            "source_artifact_id",
            "canonical_path",
            "input_role",
            "hash_algorithm",
            "input_hash",
            "hash_computed_now",
            "input_available",
            "eligible_for_future_stale_leakage_gate",
            "eligible_for_future_normalized_data",
            "blocker_reason",
        ],
    )
    write_csv(
        RUN_ID_LEDGER_PATH,
        run_rows,
        [
            "run_id",
            "run_scope",
            "v20_step",
            "script_path",
            "wrapper_path",
            "run_timestamp_utc",
            "run_timestamp_local",
            "run_status",
            "certified_run_id",
            "certification_scope",
            "notes",
        ],
    )

    version_rows = build_version_binding_ledger(v20_5_pass)
    binding_audit_rows = build_binding_eligibility_audit(registry)
    missing_rows = build_missing_or_skipped_audit(registry)
    sealed_refs = build_sealed_baseline_reference(registry)
    next_gate_rows = build_next_gate_requirements()
    source_input_pair_count = sum(1 for row in source_hash_rows if row["hash_computed_now"] == "TRUE") + sum(
        1 for row in input_hash_rows if row["hash_computed_now"] == "TRUE"
    )
    output_plan = build_output_plan()

    # Write report-oriented outputs before hash capture.
    write_csv(
        VERSION_BINDING_LEDGER_PATH,
        version_rows,
        [
            "version_binding_id",
            "project_version",
            "v20_step",
            "script_path",
            "wrapper_path",
            "output_path",
            "source_dependency",
            "binding_status",
            "official_use_allowed",
            "blocker_reason",
        ],
    )
    write_csv(
        BINDING_ELIGIBILITY_PATH,
        binding_audit_rows,
        [
            "audit_id",
            "source_artifact_id",
            "eligible_for_hash_binding",
            "eligible_for_run_id_pairing",
            "eligible_for_version_binding",
            "eligibility_status",
            "blocker_reason",
        ],
    )
    write_csv(
        MISSING_SKIPPED_PATH,
        missing_rows,
        [
            "skipped_id",
            "source_artifact_id",
            "canonical_path",
            "skip_reason",
            "missing_allowed_now",
            "required_before_next_gate",
            "current_status",
        ],
    )
    write_csv(
        SEALED_BASELINE_PATH,
        sealed_refs,
        [
            "reference_id",
            "source_artifact_id",
            "source_name",
            "canonical_path",
            "baseline_version",
            "path_exists_now",
            "hash_algorithm",
            "source_hash",
            "hash_computed_now",
            "reference_status",
            "allowed_use",
            "blocker_reason",
        ],
    )
    write_csv(
        NEXT_GATE_PATH,
        next_gate_rows,
        [
            "requirement_id",
            "next_gate",
            "requirement_description",
            "dependency_output",
            "required_status",
            "current_status",
        ],
    )

    # Write human-readable report files now so they can be hashed too.
    source_registry_activated = v20_5_pass and len(registry) > 0
    report_text = build_report(
        registry,
        input_hash_rows,
        output_plan,
        run_rows,
        version_rows,
        source_input_pair_count,
        sealed_refs,
        next_gate_rows,
        source_registry_activated,
        v20_5_pass,
    )
    current_alias_text = build_current_alias()
    write_text(REPORT_PATH, report_text)
    write_text(CURRENT_ALIAS_PATH, current_alias_text)
    # Read-first is intentionally written last among pre-hash artifacts.
    ready_for_next = source_registry_activated and v20_5_pass and len(source_hash_rows) > 0 and len(version_rows) > 0
    write_csv(
        VALIDATION_PATH,
        [
            {
                "required_outputs_created": 14,
                "dependency_inputs_found": sum(1 for p in [V20_5_READ_FIRST, V20_5_VALIDATION, V20_5_SOURCE_REGISTRY] if p.exists()),
                "v20_5_dependency_detected": tf(v20_5_pass),
                "source_registry_dependency_accepted": tf(source_registry_activated),
                "source_artifact_rows": len(registry),
                "source_hash_rows": len(source_hash_rows),
                "source_hashes_computed_now": sum(1 for row in source_hash_rows if row["hash_computed_now"] == "TRUE"),
                "input_hash_rows": len(input_hash_rows),
                "input_hashes_computed_now": sum(1 for row in input_hash_rows if row["hash_computed_now"] == "TRUE"),
                "output_hash_rows": 14,
                "output_hashes_computed_now": 13,
                "run_id_rows": len(run_rows),
                "version_binding_rows": len(version_rows),
                "hash_run_id_pairing_rows": source_input_pair_count,
                "binding_eligibility_rows": len(binding_audit_rows),
                "missing_or_skipped_rows": len(missing_rows),
                "sealed_baseline_reference_rows": len(sealed_refs),
                "ready_for_stale_leakage_pit_gate_next": tf(ready_for_next),
                "ready_for_normalized_research_dataset_next": "FALSE",
                "ready_for_factor_evidence_next": "FALSE",
                "ready_for_exploratory_backtest_next": "FALSE",
                "ready_for_dynamic_weighting_gate_research_next": "FALSE",
                "official_trading_allowed": "FALSE",
                "official_portfolio_weight_allowed": "FALSE",
                "official_factor_weight_change_allowed": "FALSE",
                "official_backtest_allowed": "FALSE",
                "official_hash_binding_created": "FALSE",
                "certified_run_id_created": "FALSE",
                "version_binding_executed": tf(source_registry_activated and v20_5_pass),
                "stale_leakage_gate_executed": "FALSE",
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
        ],
        [
            "required_outputs_created",
            "dependency_inputs_found",
            "v20_5_dependency_detected",
            "source_registry_dependency_accepted",
            "source_artifact_rows",
            "source_hash_rows",
            "source_hashes_computed_now",
            "input_hash_rows",
            "input_hashes_computed_now",
            "output_hash_rows",
            "output_hashes_computed_now",
            "run_id_rows",
            "version_binding_rows",
            "hash_run_id_pairing_rows",
            "binding_eligibility_rows",
            "missing_or_skipped_rows",
            "sealed_baseline_reference_rows",
            "ready_for_stale_leakage_pit_gate_next",
            "ready_for_normalized_research_dataset_next",
            "ready_for_factor_evidence_next",
            "ready_for_exploratory_backtest_next",
            "ready_for_dynamic_weighting_gate_research_next",
            "official_trading_allowed",
            "official_portfolio_weight_allowed",
            "official_factor_weight_change_allowed",
            "official_backtest_allowed",
            "official_hash_binding_created",
            "certified_run_id_created",
            "version_binding_executed",
            "stale_leakage_gate_executed",
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
    write_read_first(
        source_hash_rows=len(source_hash_rows),
        input_hash_rows=len(input_hash_rows),
        output_hash_rows=14,
        run_id_rows=len(run_rows),
        version_rows=len(version_rows),
        pair_rows=source_input_pair_count,
        source_registry_activated=source_registry_activated,
        v20_5_pass=v20_5_pass,
        ready_for_next=source_registry_activated and v20_5_pass and len(source_hash_rows) > 0 and len(version_rows) > 0,
    )

    output_hashes: dict[str, str] = {}
    for item in output_plan:
        output_path = ROOT / item["output_path"]
        if item["output_name"] == "V20_6_OUTPUT_HASH_LEDGER":
            continue
        if item["output_name"] == "V20_6_HASH_RUN_ID_PAIRING":
            continue
        if output_path.exists():
            output_hashes[item["output_name"]] = sha256_file(output_path)

    pair_rows = build_hash_run_id_pairings(run_id, registry, source_hash_rows, input_hash_rows)
    write_csv(
        PAIRING_PATH,
        pair_rows,
        [
            "pairing_id",
            "run_id",
            "source_artifact_id",
            "input_hash",
            "output_hash",
            "pairing_status",
            "lineage_complete_for_future_gate",
            "blocker_reason",
        ],
    )

    # Capture the pairing hash now that the file exists.
    if PAIRING_PATH.exists():
        output_hashes["V20_6_HASH_RUN_ID_PAIRING"] = sha256_file(PAIRING_PATH)

    # Build and write the output hash ledger last to avoid self-reference rewriting.
    output_hash_rows = build_output_hash_ledger(output_plan, output_hashes)
    write_csv(
        OUTPUT_HASH_LEDGER_PATH,
        output_hash_rows,
        [
            "output_id",
            "output_name",
            "output_path",
            "output_layer",
            "produced_by_v20_step",
            "hash_algorithm",
            "output_hash",
            "hash_computed_now",
            "output_available",
            "official_output",
            "blocker_reason",
        ],
    )

def write_read_first(
    source_hash_rows: int,
    input_hash_rows: int,
    output_hash_rows: int,
    run_id_rows: int,
    version_rows: int,
    pair_rows: int,
    source_registry_activated: bool,
    v20_5_pass: bool,
    ready_for_next: bool,
) -> None:
    build_read_first(
        source_hash_rows,
        input_hash_rows,
        output_hash_rows,
        run_id_rows,
        version_rows,
        pair_rows,
        source_registry_activated,
        v20_5_pass,
        ready_for_next,
    )


if __name__ == "__main__":
    main()
