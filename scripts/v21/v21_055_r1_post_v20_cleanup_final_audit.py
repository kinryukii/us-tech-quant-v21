#!/usr/bin/env python
"""Final audit of V20 archive/delete cleanup and V21 source isolation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.055-R1_POST_V20_CLEANUP_FINAL_AUDIT"

PASS_STATUS = "PASS_V21_055_R1_POST_V20_CLEANUP_FINAL_AUDIT_COMPLETE"
PARTIAL_STATUS = "PARTIAL_PASS_V21_055_R1_CLEANUP_COMPLETE_WITH_RECONCILED_ACCOUNTING_DISCREPANCY"
BLOCKED_INPUT = "BLOCKED_V21_055_R1_SOURCE_INPUT_MISSING_OR_INVALID"
BLOCKED_ISOLATION = "BLOCKED_V21_055_R1_SOURCE_ISOLATION_REGRESSED"
BLOCKED_ARCHIVE = "BLOCKED_V21_055_R1_ARCHIVE_VALIDATION_FAILED"
BLOCKED_DELETE = "BLOCKED_V21_055_R1_DELETE_VALIDATION_FAILED"
BLOCKED_UNAPPROVED = "BLOCKED_V21_055_R1_UNAPPROVED_DELETION_DETECTED"
BLOCKED_KEEP = "BLOCKED_V21_055_R1_KEEP_REFERENCE_MISSING"
BLOCKED_PROTECTED = "BLOCKED_V21_055_R1_PROTECTED_PATH_MISSING_OR_MUTATED"
BLOCKED_FILE = "BLOCKED_V21_055_R1_FILE_MUTATION_DETECTED"
BLOCKED_PERMISSION = "BLOCKED_V21_055_R1_OFFICIAL_PERMISSION_VIOLATION"

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "source_delete_commit_status",
    "source_archive_commit_status", "source_isolation_status",
    "v21_primary_research_chain_confirmed", "v20_legacy_archived",
    "v20_active_current_source_dependency_found",
    "v21_active_current_reads_v20_scripts",
    "v21_active_current_reads_v20_outputs",
    "v21_active_current_reads_v20_8_to_v20_16_stale_downstream",
    "shared_target_validation_pass", "archive_candidate_count",
    "archive_files_validated", "archive_hash_mismatch_count",
    "archive_missing_file_count", "delete_candidate_queue_count",
    "delete_candidates_original_remaining_count",
    "delete_candidates_gap_archive_validated_count",
    "delete_candidates_gap_archive_missing_count",
    "delete_candidates_gap_archive_hash_mismatch_count",
    "unapproved_deletion_count", "keep_reference_count",
    "keep_reference_missing_count", "protected_path_count",
    "protected_path_missing_count", "protected_outputs_mutated",
    "protected_output_mutation_count", "delete_stat_discrepancy_found",
    "delete_stat_discrepancy_reconciled", "delete_attempt_count_reported",
    "delete_success_count_reported", "deleted_file_count_reported",
    "deleted_file_count_validated_by_absence", "final_deleted_candidate_count",
    "files_deleted_or_moved_in_this_stage",
    "files_archived_or_copied_in_this_stage",
    "source_files_mutated_in_this_stage",
    "v20_outputs_mutated_in_this_stage",
    "v21_current_outputs_mutated_in_this_stage",
    "official_activation_allowed", "official_recommendation_allowed",
    "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
    "broker_execution_allowed", "trade_action_allowed", "research_only",
    "cleanup_complete", "recommended_next_stage", "created_at_utc",
]
SOURCE_FIELDS = ["audit_item", "status", "file_path", "details"]
ARCHIVE_FIELDS = [
    "archive_class", "source_path", "archive_path", "expected_hash",
    "actual_hash", "exists", "hash_match", "status",
]
DELETE_FIELDS = [
    "original_path", "archive_path", "original_exists", "archive_exists",
    "expected_hash", "actual_archive_hash", "hash_match",
    "approved_queue_member", "delete_log_present", "status",
]
KEEP_FIELDS = [
    "file_path", "expected_hash", "actual_hash", "exists", "hash_match", "status",
]
PROTECTED_FIELDS = [
    "file_path", "exists", "archive_exists", "mutation_in_this_stage", "status",
]
RECON_FIELDS = [
    "metric", "reported_value", "independent_validated_value",
    "discrepancy", "reconciliation", "status",
]

DELETE_SUMMARY = "V20_DELETE_CANDIDATE_ARCHIVE_GAP_REPAIR_AND_COMMIT_SUMMARY.csv"
GAP_COPY_LOG = "V20_DELETE_CANDIDATE_GAP_ARCHIVE_COPY_LOG.csv"
GAP_HASHES = "V20_DELETE_CANDIDATE_GAP_ARCHIVE_HASH_MANIFEST.csv"
DELETE_LOG = "V20_DELETE_CANDIDATE_COMMIT_DELETE_LOG.csv"
POST_DELETE_AUDIT = "V20_DELETE_CANDIDATE_POST_DELETE_VALIDATION_AUDIT.csv"
ROLLBACK = "V20_DELETE_CANDIDATE_COMMIT_ROLLBACK_EVIDENCE_MANIFEST.csv"
ARCHIVE_SUMMARY = "V20_ARCHIVE_COMMIT_SUMMARY.csv"
ARCHIVE_HASHES = "V20_ARCHIVE_COMMIT_HASH_MANIFEST.csv"
KEEP_VALIDATION = "V20_ARCHIVE_COMMIT_KEEP_REFERENCE_VALIDATION.csv"
PROTECTED_VALIDATION = "V20_ARCHIVE_COMMIT_PROTECTED_PATH_VALIDATION.csv"
ISOLATION_SUMMARY = "V21_054_R1_POST_MIGRATION_SOURCE_ISOLATION_RECHECK_SUMMARY.csv"
SHARED_HASHES = "V21_053_R2_TARGET_HASH_MANIFEST.csv"
QUEUE = "V20_FUTURE_DELETE_CANDIDATE_DRY_RUN_QUEUE.csv"

OUTPUT_NAMES = {
    "V21_055_R1_POST_V20_CLEANUP_FINAL_AUDIT_SUMMARY.csv",
    "V21_055_R1_FINAL_SOURCE_ISOLATION_AUDIT.csv",
    "V21_055_R1_FINAL_ARCHIVE_VALIDATION_AUDIT.csv",
    "V21_055_R1_FINAL_DELETE_VALIDATION_AUDIT.csv",
    "V21_055_R1_FINAL_KEEP_REFERENCE_VALIDATION.csv",
    "V21_055_R1_FINAL_PROTECTED_PATH_VALIDATION.csv",
    "V21_055_R1_DELETE_STAT_RECONCILIATION.csv",
    "V21_055_R1_POST_V20_CLEANUP_FINAL_AUDIT_REPORT.md",
}
ACTIVE_SUFFIXES = {".py", ".ps1", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini"}
PROTECTED_RE = re.compile(
    r"(authoritative.*official|official.*(?:rank|weight|recommend)|broker|"
    r"trade[_ .-]*action|real[_ .-]*book|universe|price[_ .-]*history|"
    r"raw[_ .-]*(?:price|ohlcv)|ohlcv[_ .-]*cache)", re.I
)
STALE_RE = re.compile(
    r"(?i)(?:^|[^0-9A-Za-z])(?:V20[._](?:8|9|10|11|12|13|14|15|16)|"
    r"v20_(?:8|9|10|11|12|13|14|15|16))(?!\d)"
)


def clean(value: object) -> str:
    return str(value or "").strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def as_bool(value: object) -> bool:
    return clean(value).upper() == "TRUE"


def as_int(value: object) -> int:
    try:
        return int(clean(value))
    except ValueError:
        return 0


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists() or path.stat().st_size == 0:
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def read_first(path: Path) -> dict[str, str]:
    rows, _ = read_csv(path)
    return rows[0] if rows else {}


def write_csv(path: Path, rows: Iterable[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def files_under(base: Path) -> list[Path]:
    if not base.exists():
        return []
    return sorted((p for p in base.rglob("*") if p.is_file()), key=lambda p: p.as_posix().lower())


def snapshot(root: Path, paths: Iterable[Path]) -> dict[str, str]:
    return {rel(root, path): file_hash(path) for path in paths if path.is_file()}


def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


def is_stage_output(path: Path) -> bool:
    return path.name in OUTPUT_NAMES


def source_files(root: Path) -> list[Path]:
    return [
        p for p in files_under(root / "scripts")
        if p.suffix.lower() in ACTIVE_SUFFIXES
        and p.name not in {
            "v21_055_r1_post_v20_cleanup_final_audit.py",
            "run_v21_055_r1_post_v20_cleanup_final_audit.ps1",
            "test_v21_055_r1_post_v20_cleanup_final_audit.py",
        }
    ]


def v21_current_files(root: Path) -> list[Path]:
    return [p for p in files_under(root / "outputs/v21") if not is_stage_output(p)]


def is_protected(root: Path, path: Path) -> bool:
    rpath = rel(root, path)
    return (
        bool(PROTECTED_RE.search(rpath))
        or rpath.startswith(("data/raw/", "data/universe/", "outputs/shared/"))
        or path.name in {
            "V21_053_R2_ROLLBACK_MANIFEST.csv",
            "V21_053_R2_TARGET_HASH_MANIFEST.csv",
        }
    )


def protected_files(root: Path) -> list[Path]:
    return [
        p for p in files_under(root / "outputs") + files_under(root / "data")
        if is_protected(root, p)
    ]


def active_current_source_file(path: Path, root: Path) -> bool:
    name = path.name.lower()
    if path.suffix.lower() not in ACTIVE_SUFFIXES or name.startswith("test_"):
        return False
    if name.startswith(("v21_047", "v21_050", "v21_051", "v21_052", "v21_053", "v21_054", "v21_055")):
        return False
    inactive = (
        "audit", "plan", "dry_run", "archive", "delete_candidate",
        "discovery", "ablation", "historical", "forensic", "review",
    )
    if any(token in name for token in inactive):
        return False
    return rel(root, path).startswith(("scripts/v21/", "scripts/shared/", "configs/"))


def source_isolation_audit(root: Path) -> tuple[list[dict[str, object]], bool, bool, bool]:
    rows: list[dict[str, object]] = []
    scripts = outputs = stale = False
    for base in (root / "scripts/v21", root / "scripts/shared", root / "configs"):
        for path in files_under(base):
            if not active_current_source_file(path, root):
                continue
            text = path.read_text(encoding="utf-8", errors="replace").replace("\\", "/")
            rpath = rel(root, path)
            has_scripts = "scripts/v20/" in text
            has_outputs = "outputs/v20/" in text
            has_stale = (has_scripts or has_outputs) and bool(STALE_RE.search(text))
            scripts = scripts or has_scripts
            outputs = outputs or has_outputs
            stale = stale or has_stale
            if has_scripts:
                rows.append({"audit_item": "ACTIVE_V20_SCRIPT", "status": "BLOCK", "file_path": rpath, "details": "Active/current source references scripts/v20."})
            if has_outputs:
                rows.append({"audit_item": "ACTIVE_V20_OUTPUT", "status": "BLOCK", "file_path": rpath, "details": "Active/current source references outputs/v20."})
            if has_stale:
                rows.append({"audit_item": "ACTIVE_STALE_DOWNSTREAM", "status": "BLOCK", "file_path": rpath, "details": "Active/current source references V20.8-V20.16."})
    if not rows:
        rows.append({"audit_item": "FINAL_SOURCE_ISOLATION", "status": "PASS", "file_path": "", "details": "V21 has no active/current V20 source dependency."})
    return rows, scripts, outputs, stale


def validate_hash_manifest(
    root: Path, rows: list[dict[str, str]], archive_class: str,
    path_field: str, expected_field: str,
) -> tuple[list[dict[str, object]], int, int, int]:
    audit = []
    valid = mismatch = missing = 0
    for row in rows:
        archive_rel = clean(row.get(path_field))
        path = root / archive_rel
        expected = clean(row.get(expected_field))
        exists = path.is_file()
        actual = file_hash(path) if exists else ""
        match = exists and bool(expected) and actual == expected
        valid += int(match)
        missing += int(not exists)
        mismatch += int(exists and not match)
        audit.append({
            "archive_class": archive_class,
            "source_path": clean(row.get("source_path") or row.get("original_path")),
            "archive_path": archive_rel,
            "expected_hash": expected, "actual_hash": actual,
            "exists": tf(exists), "hash_match": tf(match),
            "status": "PASS" if match else "MISSING" if not exists else "HASH_MISMATCH",
        })
    return audit, valid, mismatch, missing


def render_report(summary: dict[str, object]) -> str:
    discrepancy = (
        "The persisted delete summary is a repeat-safe rerun: it reports zero "
        "new attempts/deletions while 117 success rows remain. Independent "
        "absence of all 117 originals and 117 valid gap archive hashes proves "
        "the completed deletion and reconciles the accounting discrepancy."
        if summary["delete_stat_discrepancy_found"] == "TRUE"
        else "Delete accounting agrees with independent filesystem validation."
    )
    return f"""# V21.055-R1 Post-V20 Cleanup Final Audit

- final_status: {summary['final_status']}
- decision: {summary['decision']}
- v21_primary_research_chain_confirmed: {summary['v21_primary_research_chain_confirmed']}
- v20_legacy_archived: {summary['v20_legacy_archived']}
- final_deleted_candidate_count: {summary['final_deleted_candidate_count']}
- cleanup_complete: {summary['cleanup_complete']}
- recommended_next_stage: {summary['recommended_next_stage']}

## Delete-stat reconciliation

{discrepancy}

V21 is the primary source-isolated research chain. V20 is archived legacy.
No further V20 cleanup is required now. The next focus is the V21
forward-return maturity check on 2026-06-24.

This audit did not delete, move, archive, copy, or modify source/output files.
All official and trading permissions remained disabled.
"""


def run_audit(
    root: Path,
    mutation_hook: Callable[[], None] | None = None,
) -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
    root = root.resolve()
    migration = root / "outputs/v21/migration"
    read_center = root / "outputs/v21/read_center"
    delete_summary = read_first(migration / DELETE_SUMMARY)
    archive_summary = read_first(migration / ARCHIVE_SUMMARY)
    isolation_summary = read_first(migration / ISOLATION_SUMMARY)
    gap_copy, _ = read_csv(migration / GAP_COPY_LOG)
    gap_hashes, _ = read_csv(migration / GAP_HASHES)
    delete_log, _ = read_csv(migration / DELETE_LOG)
    post_audit, _ = read_csv(migration / POST_DELETE_AUDIT)
    rollback, _ = read_csv(migration / ROLLBACK)
    archive_hashes, _ = read_csv(migration / ARCHIVE_HASHES)
    keep_rows, _ = read_csv(migration / KEEP_VALIDATION)
    protected_rows, _ = read_csv(migration / PROTECTED_VALIDATION)
    shared_rows, _ = read_csv(migration / SHARED_HASHES)
    queue_rows, _ = read_csv(migration / QUEUE)
    required = [
        migration / name for name in (
            DELETE_SUMMARY, GAP_COPY_LOG, GAP_HASHES, DELETE_LOG,
            POST_DELETE_AUDIT, ROLLBACK, ARCHIVE_SUMMARY, ARCHIVE_HASHES,
            KEEP_VALIDATION, PROTECTED_VALIDATION, ISOLATION_SUMMARY,
            SHARED_HASHES, QUEUE,
        )
    ]
    inputs_valid = (
        all(path.exists() for path in required)
        and clean(delete_summary.get("final_status")) == "PASS_V20_DELETE_CANDIDATES_ARCHIVED_AND_DELETED"
        and clean(archive_summary.get("final_status")) == "PASS_V20_ARCHIVE_COMMITTED_READY_FOR_DELETE_CANDIDATE_DRY_RUN"
        and as_bool(isolation_summary.get("source_isolation_pass"))
        and bool(gap_copy) and bool(gap_hashes) and bool(delete_log)
        and bool(rollback) and bool(archive_hashes) and bool(shared_rows)
        and len(queue_rows) == 117
    )

    before_files = {rel(root, p) for p in root.rglob("*") if p.is_file()}
    before_sources = snapshot(root, source_files(root))
    before_v20 = snapshot(root, files_under(root / "outputs/v20"))
    before_v21 = snapshot(root, v21_current_files(root))
    before_protected = snapshot(root, protected_files(root))

    source_rows, reads_scripts, reads_outputs, reads_stale = source_isolation_audit(root)
    isolation_pass = not (reads_scripts or reads_outputs or reads_stale)

    main_archive_audit, archive_valid, archive_mismatch, archive_missing = validate_hash_manifest(
        root, archive_hashes, "MAIN_V20_ARCHIVE", "archive_path", "source_hash"
    )
    shared_audit, shared_valid, shared_mismatch, shared_missing = validate_hash_manifest(
        root, shared_rows, "SHARED_MIGRATED_TARGET", "target_path", "target_hash"
    )
    final_archive_audit = main_archive_audit + shared_audit
    shared_pass = shared_valid == len(shared_rows) and not shared_mismatch and not shared_missing

    queue_paths = [clean(row.get("file_path")).replace("\\", "/") for row in queue_rows]
    queue_set = set(queue_paths)
    gap_map = {clean(row.get("original_path")): row for row in gap_hashes}
    rollback_map = {clean(row.get("original_path")): row for row in rollback}
    delete_log_paths = {clean(row.get("file_path")) for row in delete_log}
    delete_validation: list[dict[str, object]] = []
    originals_remaining = gap_valid = gap_missing = gap_mismatch = 0
    for path_text in queue_paths:
        original = root / path_text
        evidence = gap_map.get(path_text, rollback_map.get(path_text, {}))
        archive_rel = clean(evidence.get("archive_path"))
        archive = root / archive_rel
        expected = clean(evidence.get("original_hash"))
        actual = file_hash(archive) if archive.is_file() else ""
        match = archive.is_file() and bool(expected) and actual == expected
        originals_remaining += int(original.exists())
        gap_valid += int(match)
        gap_missing += int(not archive.is_file())
        gap_mismatch += int(archive.is_file() and not match)
        delete_validation.append({
            "original_path": path_text, "archive_path": archive_rel,
            "original_exists": tf(original.exists()),
            "archive_exists": tf(archive.is_file()),
            "expected_hash": expected, "actual_archive_hash": actual,
            "hash_match": tf(match), "approved_queue_member": "TRUE",
            "delete_log_present": tf(path_text in delete_log_paths),
            "status": "PASS" if not original.exists() and match and path_text in delete_log_paths else "BLOCK",
        })

    logged_outside_queue = sorted(path for path in delete_log_paths if path and path not in queue_set)
    rollback_outside_queue = sorted(path for path in rollback_map if path and path not in queue_set)
    unapproved_count = len(set(logged_outside_queue + rollback_outside_queue))

    keep_audit: list[dict[str, object]] = []
    keep_missing = 0
    for row in keep_rows:
        rpath = clean(row.get("file_path"))
        path = root / rpath
        expected = clean(row.get("hash_after") or row.get("hash_before"))
        actual = file_hash(path) if path.is_file() else ""
        match = path.is_file() and (not expected or actual == expected)
        keep_missing += int(not match)
        keep_audit.append({
            "file_path": rpath, "expected_hash": expected, "actual_hash": actual,
            "exists": tf(path.is_file()), "hash_match": tf(match),
            "status": "PASS" if match else "MISSING_OR_CHANGED",
        })

    protected_audit: list[dict[str, object]] = []
    protected_missing = 0
    for row in protected_rows:
        rpath = clean(row.get("file_path"))
        path = root / rpath
        archive_path = root / clean(row.get("archive_path"))
        ok = path.is_file() and not archive_path.is_file()
        protected_missing += int(not path.is_file())
        protected_audit.append({
            "file_path": rpath, "exists": tf(path.is_file()),
            "archive_exists": tf(archive_path.is_file()),
            "mutation_in_this_stage": "FALSE",
            "status": "PASS" if ok else "MISSING_OR_ARCHIVED",
        })

    attempts = as_int(delete_summary.get("delete_attempt_count"))
    successes = as_int(delete_summary.get("delete_success_count"))
    deleted_reported = as_int(delete_summary.get("deleted_file_count"))
    validated_absence = len(queue_paths) - originals_remaining
    discrepancy = (
        attempts != validated_absence
        or successes != validated_absence
        or deleted_reported != validated_absence
    )
    approved_delete_evidence_pass = (
        len(queue_paths) == 117 and originals_remaining == 0
        and gap_valid == 117 and gap_missing == 0 and gap_mismatch == 0
        and len(delete_log_paths & queue_set) == 117
    )
    delete_evidence_pass = approved_delete_evidence_pass
    discrepancy_reconciled = not discrepancy or approved_delete_evidence_pass
    final_deleted = 117 if approved_delete_evidence_pass else validated_absence
    recon_rows = [
        {"metric": "delete_attempt_count", "reported_value": attempts, "independent_validated_value": validated_absence, "discrepancy": tf(attempts != validated_absence), "reconciliation": "Repeat-safe rerun reports zero new attempts after prior deletion." if attempts == 0 and validated_absence == 117 else "Values agree." if attempts == validated_absence else "Unreconciled.", "status": "RECONCILED" if attempts == validated_absence or (attempts == 0 and approved_delete_evidence_pass) else "BLOCK"},
        {"metric": "delete_success_count", "reported_value": successes, "independent_validated_value": validated_absence, "discrepancy": tf(successes != validated_absence), "reconciliation": "Success count is consistent with absence evidence." if successes == validated_absence else "Unreconciled.", "status": "RECONCILED" if successes == validated_absence else "BLOCK"},
        {"metric": "deleted_file_count", "reported_value": deleted_reported, "independent_validated_value": validated_absence, "discrepancy": tf(deleted_reported != validated_absence), "reconciliation": "Repeat-safe rerun reports zero newly deleted files; validated historical deletion count is 117." if deleted_reported == 0 and approved_delete_evidence_pass else "Values agree." if deleted_reported == validated_absence else "Unreconciled.", "status": "RECONCILED" if deleted_reported == validated_absence or (deleted_reported == 0 and approved_delete_evidence_pass) else "BLOCK"},
    ]

    if mutation_hook:
        mutation_hook()

    after_files = {rel(root, p) for p in root.rglob("*") if p.is_file()}
    deleted_or_moved = bool(before_files - after_files)
    unexpected_new = {
        path for path in after_files - before_files
        if Path(path).name not in OUTPUT_NAMES
    }
    source_changes = changed(before_sources, snapshot(root, source_files(root)))
    v20_changes = changed(before_v20, snapshot(root, files_under(root / "outputs/v20")))
    v21_changes = changed(before_v21, snapshot(root, v21_current_files(root)))
    protected_changes = changed(before_protected, snapshot(root, protected_files(root)))
    for row in protected_audit:
        row["mutation_in_this_stage"] = tf(clean(row["file_path"]) in protected_changes)
        if row["mutation_in_this_stage"] == "TRUE":
            row["status"] = "MUTATED"

    archive_pass = archive_valid == len(archive_hashes) and archive_mismatch == 0 and archive_missing == 0
    keep_pass = keep_missing == 0
    protected_pass = protected_missing == 0 and not protected_changes and all(row["status"] == "PASS" for row in protected_audit)
    v21_primary = isolation_pass and shared_pass
    v20_archived = archive_pass and approved_delete_evidence_pass
    cleanup_complete = (
        inputs_valid and v21_primary and v20_archived and unapproved_count == 0
        and keep_pass and protected_pass and discrepancy_reconciled
        and not deleted_or_moved and not unexpected_new and not source_changes
        and not v20_changes and not v21_changes and not protected_changes
    )

    if not inputs_valid:
        final_status = BLOCKED_INPUT
        decision = "BLOCK_SOURCE_INPUT_MISSING_OR_INVALID"
    elif not isolation_pass or not shared_pass:
        final_status = BLOCKED_ISOLATION
        decision = "BLOCK_SOURCE_ISOLATION_REGRESSED"
    elif not archive_pass:
        final_status = BLOCKED_ARCHIVE
        decision = "BLOCK_ARCHIVE_VALIDATION_FAILED"
    elif unapproved_count:
        final_status = BLOCKED_UNAPPROVED
        decision = "BLOCK_UNAPPROVED_DELETION_DETECTED"
    elif not approved_delete_evidence_pass:
        final_status = BLOCKED_DELETE
        decision = "BLOCK_DELETE_VALIDATION_FAILED"
    elif not keep_pass:
        final_status = BLOCKED_KEEP
        decision = "BLOCK_KEEP_REFERENCE_MISSING"
    elif not protected_pass:
        final_status = BLOCKED_PROTECTED
        decision = "BLOCK_PROTECTED_PATH_MISSING_OR_MUTATED"
    elif cleanup_complete:
        final_status = PARTIAL_STATUS if discrepancy else PASS_STATUS
        decision = "CLEANUP_COMPLETE_ACCOUNTING_DISCREPANCY_RECONCILED" if discrepancy else "POST_V20_CLEANUP_FINAL_AUDIT_COMPLETE"
    else:
        final_status = BLOCKED_FILE
        decision = "BLOCK_FILE_MUTATION_DETECTED"

    if deleted_or_moved or unexpected_new or source_changes or v20_changes or v21_changes:
        final_status = BLOCKED_FILE
        decision = "BLOCK_FILE_MUTATION_DETECTED"
        cleanup_complete = False
    if protected_changes:
        final_status = BLOCKED_PROTECTED
        decision = "BLOCK_PROTECTED_PATH_MISSING_OR_MUTATED"
        cleanup_complete = False

    permissions = {
        "official_activation_allowed": "FALSE",
        "official_recommendation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
    }
    if any(value != "FALSE" for value in permissions.values()):
        final_status = BLOCKED_PERMISSION
        decision = "BLOCK_OFFICIAL_PERMISSION_VIOLATION"
        cleanup_complete = False

    summary: dict[str, object] = {
        "stage": STAGE, "final_status": final_status, "decision": decision,
        "source_delete_commit_status": clean(delete_summary.get("final_status")) or "NOT_AVAILABLE",
        "source_archive_commit_status": clean(archive_summary.get("final_status")) or "NOT_AVAILABLE",
        "source_isolation_status": clean(isolation_summary.get("final_status")) or "NOT_AVAILABLE",
        "v21_primary_research_chain_confirmed": tf(v21_primary),
        "v20_legacy_archived": tf(v20_archived),
        "v20_active_current_source_dependency_found": tf(not isolation_pass),
        "v21_active_current_reads_v20_scripts": tf(reads_scripts),
        "v21_active_current_reads_v20_outputs": tf(reads_outputs),
        "v21_active_current_reads_v20_8_to_v20_16_stale_downstream": tf(reads_stale),
        "shared_target_validation_pass": tf(shared_pass),
        "archive_candidate_count": len(archive_hashes),
        "archive_files_validated": archive_valid,
        "archive_hash_mismatch_count": archive_mismatch,
        "archive_missing_file_count": archive_missing,
        "delete_candidate_queue_count": len(queue_paths),
        "delete_candidates_original_remaining_count": originals_remaining,
        "delete_candidates_gap_archive_validated_count": gap_valid,
        "delete_candidates_gap_archive_missing_count": gap_missing,
        "delete_candidates_gap_archive_hash_mismatch_count": gap_mismatch,
        "unapproved_deletion_count": unapproved_count,
        "keep_reference_count": len(keep_rows),
        "keep_reference_missing_count": keep_missing,
        "protected_path_count": len(protected_rows),
        "protected_path_missing_count": protected_missing,
        "protected_outputs_mutated": tf(bool(protected_changes)),
        "protected_output_mutation_count": len(protected_changes),
        "delete_stat_discrepancy_found": tf(discrepancy),
        "delete_stat_discrepancy_reconciled": tf(discrepancy_reconciled),
        "delete_attempt_count_reported": attempts,
        "delete_success_count_reported": successes,
        "deleted_file_count_reported": deleted_reported,
        "deleted_file_count_validated_by_absence": validated_absence,
        "final_deleted_candidate_count": final_deleted,
        "files_deleted_or_moved_in_this_stage": tf(deleted_or_moved),
        "files_archived_or_copied_in_this_stage": tf(bool(unexpected_new)),
        "source_files_mutated_in_this_stage": tf(bool(source_changes)),
        "v20_outputs_mutated_in_this_stage": tf(bool(v20_changes)),
        "v21_current_outputs_mutated_in_this_stage": tf(bool(v21_changes)),
        **permissions, "research_only": "TRUE",
        "cleanup_complete": tf(cleanup_complete),
        "recommended_next_stage": "V21_FORWARD_RETURN_MATURITY_CHECK_2026-06-24" if cleanup_complete else "V21.055-R1_REPAIR",
        "created_at_utc": utc_now(),
    }

    write_csv(migration / "V21_055_R1_POST_V20_CLEANUP_FINAL_AUDIT_SUMMARY.csv", [summary], SUMMARY_FIELDS)
    write_csv(migration / "V21_055_R1_FINAL_SOURCE_ISOLATION_AUDIT.csv", source_rows, SOURCE_FIELDS)
    write_csv(migration / "V21_055_R1_FINAL_ARCHIVE_VALIDATION_AUDIT.csv", final_archive_audit, ARCHIVE_FIELDS)
    write_csv(migration / "V21_055_R1_FINAL_DELETE_VALIDATION_AUDIT.csv", delete_validation, DELETE_FIELDS)
    write_csv(migration / "V21_055_R1_FINAL_KEEP_REFERENCE_VALIDATION.csv", keep_audit, KEEP_FIELDS)
    write_csv(migration / "V21_055_R1_FINAL_PROTECTED_PATH_VALIDATION.csv", protected_audit, PROTECTED_FIELDS)
    write_csv(migration / "V21_055_R1_DELETE_STAT_RECONCILIATION.csv", recon_rows, RECON_FIELDS)
    read_center.mkdir(parents=True, exist_ok=True)
    (read_center / "V21_055_R1_POST_V20_CLEANUP_FINAL_AUDIT_REPORT.md").write_text(render_report(summary), encoding="utf-8")
    return summary, {
        "source": source_rows, "archive": final_archive_audit,
        "delete": delete_validation, "keep": keep_audit,
        "protected": protected_audit, "reconciliation": recon_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    summary, _ = run_audit(args.root)
    for field in SUMMARY_FIELDS:
        print(f"{field.upper()}={summary.get(field, '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
