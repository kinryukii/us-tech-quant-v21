#!/usr/bin/env python
"""Freeze the active V21 forward-observation ledger as an immutable A0 control."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


STAGE_ID = "V21.056-R1"
FROZEN_VERSION_ID = "A0_CURRENT_TESTING_LOCKED"
PASS_STATUS = "PASS_V21_056_R1_A0_CURRENT_TESTING_VERSION_FROZEN"
PARTIAL_STATUS = "PARTIAL_PASS_V21_056_R1_A0_FROZEN_WITH_SCHEMA_WARN"
BLOCKED_STATUS = "BLOCKED_V21_056_R1_A0_CURRENT_TESTING_LEDGER_NOT_FOUND"
FAIL_STATUS = "FAIL_V21_056_R1_FORBIDDEN_MUTATION_DETECTED"

PASS_DECISION = "A0_CURRENT_TESTING_LOCKED_READY_FOR_ABCD_EXPERIMENTS"
PARTIAL_DECISION = "A0_CURRENT_TESTING_LOCKED_WITH_SCHEMA_WARN_REVIEW_BEFORE_ABCD"
BLOCKED_DECISION = "LOCATE_CURRENT_TESTING_LEDGER_BEFORE_MOMENTUM_EXPERIMENTS"
FAIL_DECISION = "STOP_AND_RESTORE_FORBIDDEN_MUTATION"

OUTPUT_DIR_REL = Path("outputs/v21/experiments/version_control")
SNAPSHOT_NAME = "V21_056_R1_A0_LEDGER_SNAPSHOT.csv"
CANDIDATE_AUDIT_NAME = "V21_056_R1_A0_LEDGER_CANDIDATE_AUDIT.csv"
MANIFEST_NAME = "V21_056_R1_A0_CURRENT_TESTING_LOCKED_MANIFEST.json"
HASH_AUDIT_NAME = "V21_056_R1_A0_FILE_HASH_AUDIT.csv"
IMMUTABILITY_AUDIT_NAME = "V21_056_R1_A0_IMMUTABILITY_AUDIT.csv"
SUMMARY_NAME = "V21_056_R1_SUMMARY.json"

IMMUTABLE_RULES = [
    "A0_CURRENT_TESTING_LOCKED must not be overwritten.",
    "Existing A0 observation rows must not be recomputed.",
    "Existing A0 observation_id values must not be changed.",
    "Existing A0 as_of_date rows must not be re-ranked.",
    "Existing A0 universe membership must not be changed.",
    "A0 may only be used as a frozen forward-observation control.",
    "Future stages may fill matured returns only into separate maturity result outputs unless explicitly designed to append non-mutating maturity fields.",
    "New momentum/ETF variants must be recorded separately and must not merge into A0.",
]

FIELD_ALIASES = {
    "observation_id": ("observation_id",),
    "as_of_date": ("as_of_date", "observation_as_of_date"),
    "ticker": ("ticker", "symbol"),
    "rank": ("rank", "technical_only_rank", "bucket_rank", "global_alpha_only_rank"),
    "forward_window": ("forward_window", "forward_return_window"),
    "scheduled_maturity_date": ("scheduled_maturity_date", "maturity_date", "due_date"),
    "maturity_status": ("maturity_status", "observation_status"),
    "realized_forward_return": ("realized_forward_return",),
    "version_id": ("version_id", "producer_version"),
    "variant_id": ("variant_id", "variant_name", "lane_id", "research_stream"),
    "research_only": ("research_only",),
}
REQUIRED_SCHEMA_CONCEPTS = tuple(FIELD_ALIASES)

CANDIDATE_FIELDS = [
    "candidate_path", "selected", "score", "row_count", "size_bytes",
    "last_modified_utc", "matched_schema_fields", "missing_schema_fields",
    "column_count", "selection_reason",
]
HASH_FIELDS = [
    "file_role", "file_path", "exists", "sha256", "size_bytes",
    "row_count_if_csv", "last_modified_utc",
]
IMMUTABILITY_FIELDS = ["check_name", "status", "details"]


def utc_iso(timestamp: float | None = None) -> str:
    value = datetime.fromtimestamp(timestamp, timezone.utc) if timestamp is not None else datetime.now(timezone.utc)
    return value.replace(microsecond=0).isoformat()


def rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_header(path: Path) -> list[str]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [str(value or "").strip() for value in next(csv.reader(handle), [])]
    except (OSError, UnicodeError, csv.Error):
        return []


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            return [dict(row) for row in reader], fields
    except (OSError, UnicodeError, csv.Error):
        return [], []


def csv_row_count(path: Path) -> int | None:
    if path.suffix.lower() != ".csv" or not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            next(reader, None)
            return sum(1 for _ in reader)
    except (OSError, UnicodeError, csv.Error):
        return None


def write_csv(path: Path, rows: Iterable[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")


def concept_columns(columns: Iterable[str]) -> dict[str, str]:
    lookup = {column.strip().lower(): column for column in columns}
    return {
        concept: next((lookup[alias] for alias in aliases if alias in lookup), "")
        for concept, aliases in FIELD_ALIASES.items()
    }


def candidate_score(path: Path, columns: list[str]) -> tuple[int, list[str], list[str]]:
    found = concept_columns(columns)
    matched = [name for name, column in found.items() if column]
    missing = [name for name, column in found.items() if not column]
    weights = {
        "observation_id": 25, "as_of_date": 20, "ticker": 15, "rank": 5,
        "forward_window": 10, "scheduled_maturity_date": 5, "maturity_status": 10,
        "realized_forward_return": 5, "version_id": 2, "variant_id": 2,
        "research_only": 5,
    }
    score = sum(weights[name] for name in matched)
    text = path.as_posix().lower()
    name = path.name.lower()
    bonuses = (
        ("current", 20), ("daily", 15), ("observation_ledger", 15),
        ("maturity_status_ledger", 10), ("shadow_observation", 5),
    )
    penalties = (
        ("audit", -45), ("summary", -40), ("spec", -40), ("schedule", -15),
        ("pending", -20), ("matured_results", -20), ("/backtest/", -30),
        ("/factor_backtest/", -30), ("/audit/", -30), ("/context/", -8),
    )
    for token, value in bonuses:
        if token in text:
            score += value
    for token, value in penalties:
        if token in text:
            score += value
    if "ledger" not in name and "observation" not in name:
        score -= 20
    return score, matched, missing


def find_candidates(root: Path) -> list[dict[str, object]]:
    base = root / "outputs/v21"
    candidates: list[dict[str, object]] = []
    excluded_path_tokens = (
        "/archive/", "/backup/", "/rollback/", "/staging/", "/tmp/",
        "/modified_outputs_copy/", "/manual_latest_data_", "/manual_current_",
        "/migration/",
    )
    if not base.exists():
        return candidates
    for path in base.rglob("*.csv"):
        normalized = "/" + rel(root, path).lower().replace("\\", "/") + "/"
        if (
            OUTPUT_DIR_REL.as_posix() in normalized
            or any(token in normalized for token in excluded_path_tokens)
        ):
            continue
        columns = read_header(path)
        found = concept_columns(columns)
        if not (found["observation_id"] and found["as_of_date"] and found["ticker"]):
            continue
        if "ledger" not in path.name.lower() and "observation" not in path.name.lower():
            continue
        score, matched, missing = candidate_score(path, columns)
        stat = path.stat()
        candidates.append({
            "path": path,
            "candidate_path": rel(root, path),
            "selected": "FALSE",
            "score": score,
            "row_count": csv_row_count(path),
            "size_bytes": stat.st_size,
            "last_modified_utc": utc_iso(stat.st_mtime),
            "matched_schema_fields": "|".join(matched),
            "missing_schema_fields": "|".join(missing),
            "column_count": len(columns),
            "selection_reason": "",
            "_mtime": stat.st_mtime,
        })
    candidates.sort(key=lambda item: (-int(item["score"]), -float(item["_mtime"]), str(item["candidate_path"])))
    if candidates:
        candidates[0]["selected"] = "TRUE"
        candidates[0]["selection_reason"] = "HIGHEST_ACTIVE_CURRENT_TESTING_LEDGER_SCORE"
        for item in candidates[1:]:
            item["selection_reason"] = "NOT_SELECTED_LOWER_CANDIDATE_SCORE_OR_RECENCY"
    return candidates


def protected_files(root: Path) -> dict[str, dict[str, str]]:
    groups = {"official_ranking": {}, "official_weights": {}, "real_book": {}, "broker": {}}
    search_roots = [root / "outputs", root / "data"]
    for base in search_roots:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or OUTPUT_DIR_REL.as_posix() in path.as_posix().replace("\\", "/"):
                continue
            text = rel(root, path).lower().replace("-", "_").replace(" ", "_")
            group = ""
            if "broker" in text:
                group = "broker"
            elif "real_book" in text or "realbook" in text:
                group = "real_book"
            elif "official" in text and ("weight" in text or "allocation" in text):
                group = "official_weights"
            elif "official" in text and ("rank" in text or "recommend" in text):
                group = "official_ranking"
            if group:
                groups[group][rel(root, path)] = sha256(path)
    return groups


def group_changes(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))


def related_files(root: Path, source: Path | None) -> list[Path]:
    if source is None:
        return []
    related: list[Path] = []
    source_tokens = source.stem.upper().split("_")
    version_prefixes = {"_".join(source_tokens[:index]) for index in (2, 3) if len(source_tokens) >= index}
    for path in source.parent.iterdir():
        if not path.is_file() or path == source:
            continue
        upper = path.name.upper()
        role_token = any(token in upper for token in ("SUMMARY", "CONFIG", "MANIFEST", "INTEGRITY"))
        lineage_token = any(prefix in upper for prefix in version_prefixes) or "CURRENT_DAILY" in upper
        if role_token and lineage_token:
            related.append(path)
    return sorted(related, key=lambda path: path.name)[:20]


def values(rows: list[dict[str, str]], column: str) -> list[str]:
    if not column:
        return []
    return [str(row.get(column, "") or "").strip() for row in rows]


def sorted_distinct(items: Iterable[str]) -> list[str]:
    return sorted({item for item in items if item})


def file_audit_row(root: Path, role: str, path: Path) -> dict[str, object]:
    exists = path.exists() and path.is_file()
    stat = path.stat() if exists else None
    return {
        "file_role": role,
        "file_path": rel(root, path) if path.is_absolute() and path.exists() else path.as_posix(),
        "exists": exists,
        "sha256": sha256(path) if exists else "",
        "size_bytes": stat.st_size if stat else "",
        "row_count_if_csv": csv_row_count(path) if exists else "",
        "last_modified_utc": utc_iso(stat.st_mtime) if stat else "",
    }


def run_stage(root: Path) -> dict[str, object]:
    root = root.resolve()
    output_dir = root / OUTPUT_DIR_REL
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = output_dir / SNAPSHOT_NAME
    manifest_path = output_dir / MANIFEST_NAME
    before = protected_files(root)

    candidates = find_candidates(root)
    selected = candidates[0] if candidates else None
    source_path = Path(selected["path"]) if selected else None
    lock_conflict = False
    existing_manifest: dict[str, object] | None = None
    existing_lock = False
    if manifest_path.exists():
        try:
            existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            lock_conflict = True
        existing_lock = bool(
            existing_manifest
            and existing_manifest.get("source_ledger_path")
            and existing_manifest.get("snapshot_ledger_sha256")
            and snapshot_path.is_file()
        )
        if existing_lock and existing_manifest:
            locked_source = root / str(existing_manifest.get("source_ledger_path", ""))
            if locked_source.is_file():
                source_path = locked_source
                for item in candidates:
                    item["selected"] = "TRUE" if Path(item["path"]).resolve() == source_path.resolve() else "FALSE"
                    item["selection_reason"] = (
                        "EXISTING_A0_LOCK_REUSED_WITHOUT_OVERWRITE"
                        if item["selected"] == "TRUE"
                        else "NOT_SELECTED_EXISTING_A0_LOCK_CONTROLS"
                    )
                selected = next((item for item in candidates if item["selected"] == "TRUE"), selected)
            else:
                lock_conflict = True

    candidate_rows = [{field: item.get(field, "") for field in CANDIDATE_FIELDS} for item in candidates]
    write_csv(output_dir / CANDIDATE_AUDIT_NAME, candidate_rows, CANDIDATE_FIELDS)

    snapshot_written = False
    if source_path and source_path.is_file():
        if snapshot_path.exists():
            if existing_lock and existing_manifest:
                expected_snapshot_hash = str(existing_manifest.get("snapshot_ledger_sha256", ""))
                if not expected_snapshot_hash or sha256(snapshot_path) != expected_snapshot_hash:
                    lock_conflict = True
            elif sha256(snapshot_path) != sha256(source_path):
                lock_conflict = True
        else:
            shutil.copyfile(source_path, snapshot_path)
            snapshot_written = True

    rows: list[dict[str, str]] = []
    columns: list[str] = []
    if source_path and source_path.is_file():
        rows, columns = read_csv(source_path)
    mapped = concept_columns(columns)
    source_count = len(rows) if source_path and source_path.is_file() else 0
    snapshot_count = csv_row_count(snapshot_path) if snapshot_path.exists() else 0
    observation_ids = values(rows, mapped["observation_id"])
    id_counts = Counter(value for value in observation_ids if value)
    duplicate_count = sum(count - 1 for count in id_counts.values() if count > 1)
    as_of_dates = sorted_distinct(values(rows, mapped["as_of_date"]))
    maturity_counts = Counter(value or "BLANK" for value in values(rows, mapped["maturity_status"]))
    matched_schema = [name for name, column in mapped.items() if column]
    missing_schema = [name for name in REQUIRED_SCHEMA_CONCEPTS if not mapped[name]]
    source_hash = sha256(source_path) if source_path and source_path.is_file() else ""
    snapshot_hash = sha256(snapshot_path) if snapshot_path.exists() else ""

    manifest: dict[str, object] = {
        "stage_id": STAGE_ID,
        "frozen_version_id": FROZEN_VERSION_ID,
        "source_ledger_path": rel(root, source_path) if source_path and source_path.is_file() else None,
        "snapshot_ledger_path": rel(root, snapshot_path) if snapshot_path.exists() else None,
        "source_ledger_sha256": source_hash or None,
        "snapshot_ledger_sha256": snapshot_hash or None,
        "source_row_count": source_count,
        "snapshot_row_count": snapshot_count,
        "unique_observation_id_count": len(id_counts),
        "duplicate_observation_id_count": duplicate_count,
        "distinct_as_of_date_count": len(as_of_dates),
        "min_as_of_date": as_of_dates[0] if as_of_dates else None,
        "max_as_of_date": as_of_dates[-1] if as_of_dates else None,
        "forward_windows": sorted_distinct(values(rows, mapped["forward_window"])),
        "maturity_status_counts": dict(sorted(maturity_counts.items())),
        "detected_version_ids": sorted_distinct(values(rows, mapped["version_id"])),
        "detected_variant_ids": sorted_distinct(values(rows, mapped["variant_id"])),
        "research_only": True,
        "official_use_allowed": False,
        "production_adoption_allowed": False,
        "real_book_mutation_allowed": False,
        "broker_execution_allowed": False,
        "immutable_rules": IMMUTABLE_RULES,
        "schema_fields_detected": matched_schema,
        "schema_fields_missing": missing_schema,
        "created_at_utc": utc_iso(),
    }
    if not existing_lock and not lock_conflict:
        write_json(manifest_path, manifest)
    elif existing_lock and existing_manifest is not None:
        immutable_keys = (
            "stage_id", "frozen_version_id", "source_ledger_path", "snapshot_ledger_path",
            "source_ledger_sha256", "snapshot_ledger_sha256", "source_row_count",
            "snapshot_row_count", "unique_observation_id_count",
            "duplicate_observation_id_count", "distinct_as_of_date_count",
            "min_as_of_date", "max_as_of_date",
        )
        if any(existing_manifest.get(key) != manifest.get(key) for key in immutable_keys):
            lock_conflict = True
        manifest = existing_manifest

    hash_rows: list[dict[str, object]] = []
    if source_path:
        hash_rows.append(file_audit_row(root, "selected_a0_ledger_source", source_path))
    hash_rows.append(file_audit_row(root, "a0_ledger_snapshot", snapshot_path))
    for path in related_files(root, source_path):
        hash_rows.append(file_audit_row(root, "related_current_testing_artifact", path))
    hash_rows.append(file_audit_row(root, "a0_locked_manifest", manifest_path))
    write_csv(output_dir / HASH_AUDIT_NAME, hash_rows, HASH_FIELDS)

    after = protected_files(root)
    official_rank_changes = group_changes(before["official_ranking"], after["official_ranking"])
    official_weight_changes = group_changes(before["official_weights"], after["official_weights"])
    real_book_changes = group_changes(before["real_book"], after["real_book"])
    broker_changes = group_changes(before["broker"], after["broker"])
    official_mutation = bool(official_rank_changes or official_weight_changes)
    real_book_mutation = bool(real_book_changes)
    broker_mutation = bool(broker_changes)
    forbidden_mutation = official_mutation or real_book_mutation or broker_mutation or lock_conflict
    source_found = bool(source_path and source_path.is_file())
    row_match = source_found and snapshot_path.exists() and source_count == snapshot_count
    hash_match = source_found and snapshot_path.exists() and source_hash == snapshot_hash

    if forbidden_mutation:
        final_status, decision = FAIL_STATUS, FAIL_DECISION
    elif not source_found:
        final_status, decision = BLOCKED_STATUS, BLOCKED_DECISION
    elif missing_schema:
        final_status, decision = PARTIAL_STATUS, PARTIAL_DECISION
    else:
        final_status, decision = PASS_STATUS, PASS_DECISION

    checks = [
        ("source_ledger_found", "PASS" if source_found else "FAIL", rel(root, source_path) if source_found else "No qualifying current testing ledger found."),
        ("snapshot_written", "PASS" if snapshot_path.exists() else "FAIL", "Created exact-byte snapshot." if snapshot_written else "Existing immutable snapshot validated." if snapshot_path.exists() else "Snapshot not written."),
        ("source_snapshot_row_count_match", "PASS" if row_match else "FAIL", f"source={source_count}; snapshot={snapshot_count}"),
        ("source_snapshot_hash_match_or_expected_copy_hash_recorded", "PASS" if hash_match else "FAIL", f"source_sha256={source_hash}; snapshot_sha256={snapshot_hash}"),
        ("observation_id_unique_or_duplicates_reported", "PASS", f"unique={len(id_counts)}; duplicate_count={duplicate_count}"),
        ("official_ranking_not_mutated", "PASS" if not official_rank_changes else "FAIL", "|".join(official_rank_changes) or "No hash changes detected."),
        ("official_weights_not_mutated", "PASS" if not official_weight_changes else "FAIL", "|".join(official_weight_changes) or "No hash changes detected."),
        ("real_book_not_mutated", "PASS" if not real_book_changes else "FAIL", "|".join(real_book_changes) or "No hash changes detected."),
        ("broker_files_not_mutated", "PASS" if not broker_changes else "FAIL", "|".join(broker_changes) or "No hash changes detected."),
        ("output_confined_to_version_control_dir", "PASS", OUTPUT_DIR_REL.as_posix()),
        ("research_only_true", "PASS", "research_only=TRUE"),
    ]
    if lock_conflict:
        checks.append(("existing_a0_lock_not_overwritten", "FAIL", "Existing A0 manifest or snapshot conflicts with the selected source; immutable files were not overwritten."))
    write_csv(
        output_dir / IMMUTABILITY_AUDIT_NAME,
        ({"check_name": name, "status": status, "details": details} for name, status, details in checks),
        IMMUTABILITY_FIELDS,
    )

    summary: dict[str, object] = {
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "stage_id": STAGE_ID,
        "frozen_version_id": FROZEN_VERSION_ID,
        "source_ledger_found": source_found,
        "source_ledger_path": rel(root, source_path) if source_found else None,
        "snapshot_ledger_path": rel(root, snapshot_path) if snapshot_path.exists() else None,
        "source_row_count": source_count,
        "snapshot_row_count": snapshot_count,
        "duplicate_observation_id_count": duplicate_count,
        "distinct_as_of_date_count": len(as_of_dates),
        "min_as_of_date": as_of_dates[0] if as_of_dates else None,
        "max_as_of_date": as_of_dates[-1] if as_of_dates else None,
        "official_mutation_detected": official_mutation,
        "real_book_mutation_detected": real_book_mutation,
        "broker_mutation_detected": broker_mutation,
        "research_only": True,
        "official_use_allowed": False,
        "production_adoption_allowed": False,
        "real_book_mutation_allowed": False,
        "broker_execution_allowed": False,
        "next_recommended_stage": (
            "V21_ABCD_EXPERIMENT_DESIGN_USING_A0_FROZEN_CONTROL"
            if final_status == PASS_STATUS
            else "REVIEW_A0_SCHEMA_GAPS_BEFORE_V21_ABCD_EXPERIMENTS"
            if final_status == PARTIAL_STATUS
            else "LOCATE_AND_VALIDATE_CURRENT_V21_TESTING_LEDGER"
            if final_status == BLOCKED_STATUS
            else "RESTORE_FORBIDDEN_MUTATION_AND_REVALIDATE_A0_LOCK"
        ),
    }
    write_json(output_dir / SUMMARY_NAME, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    summary = run_stage(args.root)
    print(json.dumps(summary, indent=2))
    return 1 if summary["FINAL_STATUS"] in {FAIL_STATUS, BLOCKED_STATUS} else 0


if __name__ == "__main__":
    raise SystemExit(main())
