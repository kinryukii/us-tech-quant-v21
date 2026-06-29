#!/usr/bin/env python
"""Commit the approved V20 legacy archive without moving source files."""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V20_ARCHIVE_COMMIT"
ARCHIVE_ROOT_REL = "archive/v20_legacy_archive"

PASS_STATUS = "PASS_V20_ARCHIVE_COMMITTED_READY_FOR_DELETE_CANDIDATE_DRY_RUN"
PARTIAL_STATUS = "PARTIAL_PASS_V20_ARCHIVE_COMMITTED_WITH_SKIPPED_SAFE_ENTRIES"
BLOCKED_INPUT = "BLOCKED_V20_ARCHIVE_COMMIT_SOURCE_INPUT_MISSING_OR_INVALID"
BLOCKED_UNSAFE = "BLOCKED_V20_ARCHIVE_COMMIT_UNSAFE_ARCHIVE_CANDIDATES"
BLOCKED_PROTECTED_ATTEMPT = "BLOCKED_V20_ARCHIVE_COMMIT_PROTECTED_PATH_ARCHIVE_ATTEMPT"
BLOCKED_COPY = "BLOCKED_V20_ARCHIVE_COMMIT_COPY_FAILURE"
BLOCKED_HASH = "BLOCKED_V20_ARCHIVE_COMMIT_HASH_VALIDATION_FAILED"
BLOCKED_ISOLATION = "BLOCKED_V20_ARCHIVE_COMMIT_SOURCE_ISOLATION_REGRESSED"
BLOCKED_FILE = "BLOCKED_V20_ARCHIVE_COMMIT_FILE_MUTATION_DETECTED"
BLOCKED_V20 = "BLOCKED_V20_ARCHIVE_COMMIT_V20_OUTPUT_MUTATION_DETECTED"
BLOCKED_V21 = "BLOCKED_V20_ARCHIVE_COMMIT_V21_CURRENT_OUTPUT_MUTATION_DETECTED"
BLOCKED_PROTECTED = "BLOCKED_V20_ARCHIVE_COMMIT_PROTECTED_OUTPUT_MUTATION_DETECTED"
BLOCKED_PERMISSION = "BLOCKED_V20_ARCHIVE_COMMIT_OFFICIAL_PERMISSION_VIOLATION"

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "source_archive_dry_run_status",
    "source_ready_for_v20_archive_commit", "source_isolation_pass",
    "archive_candidate_count", "archive_copy_attempt_count",
    "archive_copy_success_count", "archive_copy_failure_count",
    "archive_hash_validated_count", "archive_hash_mismatch_count",
    "missing_archive_copy_count", "keep_reference_count",
    "keep_reference_validation_pass", "protected_never_archive_count",
    "protected_path_archived_count", "protected_path_validation_pass",
    "archive_package_count", "archive_root", "archive_commit_allowed",
    "deletion_allowed", "migration_allowed", "files_deleted_or_moved",
    "source_files_mutated", "v20_outputs_mutated",
    "v21_current_outputs_mutated", "protected_outputs_mutated",
    "protected_output_mutation_count",
    "v21_active_current_reads_v20_scripts_after_archive",
    "v21_active_current_reads_v20_outputs_after_archive",
    "v21_active_current_reads_v20_8_to_v20_16_stale_downstream_after_archive",
    "source_isolation_pass_after_archive",
    "ready_for_v20_delete_candidate_dry_run",
    "official_activation_allowed", "official_recommendation_allowed",
    "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
    "broker_execution_allowed", "trade_action_allowed", "research_only",
    "recommended_next_stage", "created_at_utc",
]
COPY_FIELDS = [
    "source_path", "archive_path", "source_size_bytes", "archive_size_bytes",
    "source_hash", "archive_hash", "copy_status", "error",
]
HASH_FIELDS = [
    "source_path", "archive_path", "source_hash", "archive_hash",
    "source_size_bytes", "archive_size_bytes", "hash_match", "validation_status",
]
PACKAGE_FIELDS = [
    "package_name", "package_scope", "planned_file_count",
    "copied_file_count", "validated_file_count", "failed_file_count",
    "estimated_size_mb", "actual_size_mb", "package_reason", "package_status",
]
VALIDATION_FIELDS = ["validation_item", "status", "count", "details"]
KEEP_FIELDS = [
    "file_path", "exists_before", "exists_after", "hash_before", "hash_after",
    "unchanged", "validation_status",
]
PROTECTED_FIELDS = [
    "file_path", "archive_path", "source_exists", "archive_exists",
    "overlap_with_archive_candidate", "validation_status",
]

DRY_RUN_SUMMARY = "V20_ARCHIVE_DRY_RUN_SUMMARY.csv"
ARCHIVE_MANIFEST = "V20_ARCHIVE_CANDIDATE_MANIFEST.csv"
KEEP_MANIFEST = "V20_KEEP_ACTIVE_OR_REFERENCE_MANIFEST.csv"
PROTECTED_MANIFEST = "V20_PROTECTED_NEVER_ARCHIVE_MANIFEST.csv"
DELETE_QUEUE = "V20_FUTURE_DELETE_CANDIDATE_DRY_RUN_QUEUE.csv"
PACKAGE_PLAN = "V20_ARCHIVE_PACKAGE_PLAN.csv"
RISK_AUDIT = "V20_ARCHIVE_READINESS_RISK_AUDIT.csv"
ISOLATION_SUMMARY = "V21_054_R1_POST_MIGRATION_SOURCE_ISOLATION_RECHECK_SUMMARY.csv"

OUTPUT_NAMES = {
    "V20_ARCHIVE_COMMIT_SUMMARY.csv",
    "V20_ARCHIVE_COMMIT_COPY_LOG.csv",
    "V20_ARCHIVE_COMMIT_HASH_MANIFEST.csv",
    "V20_ARCHIVE_COMMIT_PACKAGE_MANIFEST.csv",
    "V20_ARCHIVE_COMMIT_VALIDATION_AUDIT.csv",
    "V20_ARCHIVE_COMMIT_KEEP_REFERENCE_VALIDATION.csv",
    "V20_ARCHIVE_COMMIT_PROTECTED_PATH_VALIDATION.csv",
    "V20_ARCHIVE_COMMIT_REPORT.md",
}
ACTIVE_SUFFIXES = {".py", ".ps1", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini"}
PROTECTED_RE = re.compile(
    r"(authoritative.*official|official.*(?:rank|weight|recommend)|"
    r"broker|trade[_ .-]*action|real[_ .-]*book|universe|price[_ .-]*history|"
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


def is_commit_output(path: Path) -> bool:
    return path.name in OUTPUT_NAMES


def source_files(root: Path) -> list[Path]:
    return [
        path for path in files_under(root / "scripts")
        if path.suffix.lower() in ACTIVE_SUFFIXES
        and path.name not in {
            "v20_archive_commit.py", "run_v20_archive_commit.ps1",
            "test_v20_archive_commit.py",
        }
    ]


def v21_current_files(root: Path) -> list[Path]:
    return [path for path in files_under(root / "outputs/v21") if not is_commit_output(path)]


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
        path for path in files_under(root / "outputs") + files_under(root / "data")
        if is_protected(root, path)
    ]


def validate_dry_run(summary: dict[str, str]) -> bool:
    return (
        clean(summary.get("final_status")) in {
            "PARTIAL_PASS_V20_ARCHIVE_DRY_RUN_READY_WITH_KEEP_REFERENCES",
            "PASS_V20_ARCHIVE_DRY_RUN_READY",
        }
        and as_bool(summary.get("ready_for_v20_archive_commit"))
        and as_int(summary.get("unsafe_archive_candidate_count")) == 0
        and as_bool(summary.get("source_isolation_pass"))
        and not as_bool(summary.get("v21_active_current_reads_v20_scripts"))
        and not as_bool(summary.get("v21_active_current_reads_v20_outputs"))
        and not as_bool(summary.get("v21_active_current_reads_v20_8_to_v20_16_stale_downstream"))
        and not as_bool(summary.get("v20_outputs_mutated"))
        and not as_bool(summary.get("v21_current_outputs_mutated"))
        and not as_bool(summary.get("protected_outputs_mutated"))
    )


def safe_relative_path(value: str) -> bool:
    path = Path(value.replace("\\", "/"))
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def active_current_source_file(path: Path, root: Path) -> bool:
    name = path.name.lower()
    if path.suffix.lower() not in ACTIVE_SUFFIXES or name.startswith("test_"):
        return False
    if name.startswith(("v21_047", "v21_050", "v21_051", "v21_052", "v21_053", "v21_054")):
        return False
    inactive = (
        "audit", "plan", "dry_run", "archive", "discovery", "ablation",
        "historical", "forensic", "review",
    )
    if any(token in name for token in inactive):
        return False
    rpath = rel(root, path)
    return rpath.startswith(("scripts/v21/", "scripts/shared/", "configs/"))


def source_isolation_audit(root: Path) -> tuple[list[dict[str, object]], bool, bool, bool]:
    rows: list[dict[str, object]] = []
    script_ref = False
    output_ref = False
    stale_ref = False
    for base in (root / "scripts/v21", root / "scripts/shared", root / "configs"):
        for path in files_under(base):
            if not active_current_source_file(path, root):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            rpath = rel(root, path)
            has_script = "scripts/v20/" in text or "scripts\\v20\\" in text
            has_output = "outputs/v20/" in text or "outputs\\v20\\" in text
            has_stale = (has_script or has_output) and bool(STALE_RE.search(text.replace("\\", "/")))
            if has_script:
                script_ref = True
                rows.append({"validation_item": "ACTIVE_V20_SCRIPT_REFERENCE", "status": "BLOCK", "count": 1, "details": rpath})
            if has_output:
                output_ref = True
                rows.append({"validation_item": "ACTIVE_V20_OUTPUT_REFERENCE", "status": "BLOCK", "count": 1, "details": rpath})
            if has_stale:
                stale_ref = True
                rows.append({"validation_item": "ACTIVE_STALE_DOWNSTREAM_REFERENCE", "status": "BLOCK", "count": 1, "details": rpath})
    if not rows:
        rows.append({"validation_item": "POST_ARCHIVE_SOURCE_ISOLATION", "status": "PASS", "count": 0, "details": "No active/current V21 dependency on V20 detected."})
    return rows, script_ref, output_ref, stale_ref


def copy_candidates(
    root: Path,
    archive_root: Path,
    candidates: list[dict[str, str]],
) -> list[dict[str, object]]:
    logs: list[dict[str, object]] = []
    for row in candidates:
        source_rel = clean(row.get("file_path")).replace("\\", "/")
        archive_rel = f"{ARCHIVE_ROOT_REL}/{source_rel}"
        source = root / source_rel
        target = archive_root / source_rel
        source_hash = file_hash(source) if source.is_file() else ""
        source_size = source.stat().st_size if source.is_file() else 0
        status = "NOT_ATTEMPTED"
        error = ""
        archive_hash = ""
        archive_size = 0
        try:
            if not safe_relative_path(source_rel):
                status = "UNSAFE_SOURCE_PATH"
                error = "Source path is not a safe repository-relative path."
            elif not source.is_file():
                status = "SOURCE_MISSING"
                error = "Archive candidate source file is missing."
            elif target.exists():
                archive_hash = file_hash(target)
                archive_size = target.stat().st_size
                if archive_hash == source_hash:
                    status = "ALREADY_ARCHIVED_HASH_MATCH"
                else:
                    status = "PREEXISTING_ARCHIVE_CONFLICT"
                    error = "Existing archive target hash differs; target was not overwritten."
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                archive_hash = file_hash(target)
                archive_size = target.stat().st_size
                status = "COPIED" if archive_hash == source_hash else "COPIED_HASH_MISMATCH"
        except Exception as exc:  # pragma: no cover - defensive logging
            status = "COPY_FAILED"
            error = str(exc)
        logs.append({
            "source_path": source_rel,
            "archive_path": archive_rel,
            "source_size_bytes": source_size,
            "archive_size_bytes": archive_size,
            "source_hash": source_hash,
            "archive_hash": archive_hash,
            "copy_status": status,
            "error": error,
        })
    return logs


def validate_hashes(root: Path, logs: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for log in logs:
        source = root / clean(log["source_path"])
        archive = root / clean(log["archive_path"])
        source_hash = file_hash(source) if source.is_file() else ""
        archive_hash = file_hash(archive) if archive.is_file() else ""
        source_size = source.stat().st_size if source.is_file() else 0
        archive_size = archive.stat().st_size if archive.is_file() else 0
        match = bool(source_hash) and source_hash == archive_hash and source_size == archive_size
        status = "PASS" if match else "MISSING_ARCHIVE_COPY" if not archive.is_file() else "HASH_MISMATCH"
        rows.append({
            "source_path": clean(log["source_path"]),
            "archive_path": clean(log["archive_path"]),
            "source_hash": source_hash,
            "archive_hash": archive_hash,
            "source_size_bytes": source_size,
            "archive_size_bytes": archive_size,
            "hash_match": tf(match),
            "validation_status": status,
        })
    return rows


def validate_keep(root: Path, rows: list[dict[str, str]], before: dict[str, str]) -> list[dict[str, object]]:
    result = []
    for row in rows:
        rpath = clean(row.get("file_path")).replace("\\", "/")
        path = root / rpath
        exists_before = rpath in before
        exists_after = path.is_file()
        hash_after = file_hash(path) if exists_after else ""
        unchanged = exists_before and exists_after and before.get(rpath) == hash_after
        result.append({
            "file_path": rpath,
            "exists_before": tf(exists_before),
            "exists_after": tf(exists_after),
            "hash_before": before.get(rpath, ""),
            "hash_after": hash_after,
            "unchanged": tf(unchanged),
            "validation_status": "PASS" if unchanged else "MISSING_OR_CHANGED",
        })
    return result


def validate_protected(
    root: Path,
    archive_root: Path,
    protected_rows: list[dict[str, str]],
    candidate_paths: set[str],
) -> list[dict[str, object]]:
    result = []
    for row in protected_rows:
        rpath = clean(row.get("file_path")).replace("\\", "/")
        source = root / rpath
        archived = archive_root / rpath
        overlap = rpath in candidate_paths
        archive_exists = archived.is_file()
        result.append({
            "file_path": rpath,
            "archive_path": f"{ARCHIVE_ROOT_REL}/{rpath}",
            "source_exists": tf(source.is_file()),
            "archive_exists": tf(archive_exists),
            "overlap_with_archive_candidate": tf(overlap),
            "validation_status": "PASS" if not overlap and not archive_exists else "PROTECTED_PATH_ARCHIVED_OR_OVERLAP",
        })
    return result


def build_packages(
    plan_rows: list[dict[str, str]],
    candidate_rows: list[dict[str, str]],
    hash_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    hash_by_source = {clean(row["source_path"]): row for row in hash_rows}
    result = []
    for plan in plan_rows:
        package = clean(plan.get("package_name"))
        members = [row for row in candidate_rows if clean(row.get("proposed_archive_package")) == package]
        validated = sum(1 for row in members if hash_by_source.get(clean(row.get("file_path")), {}).get("hash_match") == "TRUE")
        actual_bytes = sum(
            int(hash_by_source.get(clean(row.get("file_path")), {}).get("archive_size_bytes", 0))
            for row in members
        )
        result.append({
            "package_name": package,
            "package_scope": clean(plan.get("package_scope")),
            "planned_file_count": len(members),
            "copied_file_count": validated,
            "validated_file_count": validated,
            "failed_file_count": len(members) - validated,
            "estimated_size_mb": clean(plan.get("estimated_size_mb")),
            "actual_size_mb": round(actual_bytes / (1024 * 1024), 6),
            "package_reason": clean(plan.get("package_reason")),
            "package_status": "PASS" if validated == len(members) else "BLOCK",
        })
    return result


def render_report(summary: dict[str, object]) -> str:
    return f"""# V20 Archive Commit Report

- final_status: {summary['final_status']}
- decision: {summary['decision']}
- archive_candidate_count: {summary['archive_candidate_count']}
- archive_copy_success_count: {summary['archive_copy_success_count']}
- archive_hash_validated_count: {summary['archive_hash_validated_count']}
- archive_hash_mismatch_count: {summary['archive_hash_mismatch_count']}
- missing_archive_copy_count: {summary['missing_archive_copy_count']}
- keep_reference_validation_pass: {summary['keep_reference_validation_pass']}
- protected_path_validation_pass: {summary['protected_path_validation_pass']}
- source_isolation_pass_after_archive: {summary['source_isolation_pass_after_archive']}
- ready_for_v20_delete_candidate_dry_run: {summary['ready_for_v20_delete_candidate_dry_run']}
- recommended_next_stage: {summary['recommended_next_stage']}

Archive root: `{summary['archive_root']}`

The commit copied approved candidates while preserving repository-relative
paths. Original V20 files were not deleted, moved, or modified. Official and
trading permissions remained disabled.
"""


def run_archive_commit(
    root: Path,
    after_copy_hook: Callable[[Path], None] | None = None,
    mutation_hook: Callable[[], None] | None = None,
) -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
    root = root.resolve()
    migration = root / "outputs/v21/migration"
    read_center = root / "outputs/v21/read_center"
    archive_root = root / ARCHIVE_ROOT_REL

    dry_summary = read_first(migration / DRY_RUN_SUMMARY)
    candidate_rows, _ = read_csv(migration / ARCHIVE_MANIFEST)
    keep_rows, _ = read_csv(migration / KEEP_MANIFEST)
    protected_rows, _ = read_csv(migration / PROTECTED_MANIFEST)
    delete_rows, _ = read_csv(migration / DELETE_QUEUE)
    package_plan_rows, _ = read_csv(migration / PACKAGE_PLAN)
    risk_rows, _ = read_csv(migration / RISK_AUDIT)
    isolation_summary = read_first(migration / ISOLATION_SUMMARY)
    required_paths = [
        migration / name for name in (
            DRY_RUN_SUMMARY, ARCHIVE_MANIFEST, KEEP_MANIFEST,
            PROTECTED_MANIFEST, DELETE_QUEUE, PACKAGE_PLAN, RISK_AUDIT,
            ISOLATION_SUMMARY,
        )
    ]
    inputs_valid = (
        all(path.exists() for path in required_paths)
        and validate_dry_run(dry_summary)
        and bool(candidate_rows)
        and bool(package_plan_rows)
        and as_bool(isolation_summary.get("source_isolation_pass"))
        and len(candidate_rows) == as_int(dry_summary.get("archive_candidate_count"))
        and len(keep_rows) == as_int(dry_summary.get("keep_reference_count"))
        and len(protected_rows) == as_int(dry_summary.get("protected_never_archive_count"))
        and len(delete_rows) == as_int(dry_summary.get("future_delete_candidate_count"))
        and not any(clean(row.get("status")).upper() == "BLOCK" for row in risk_rows)
    )

    candidate_paths = {clean(row.get("file_path")).replace("\\", "/") for row in candidate_rows}
    protected_paths = {clean(row.get("file_path")).replace("\\", "/") for row in protected_rows}
    protected_overlap = candidate_paths & protected_paths
    unsafe_candidates = [
        row for row in candidate_rows
        if as_bool(row.get("protected_flag"))
        or as_bool(row.get("active_v21_dependency_flag"))
        or not safe_relative_path(clean(row.get("file_path")))
    ]

    before_files = {rel(root, path) for path in root.rglob("*") if path.is_file()}
    before_sources = snapshot(root, source_files(root))
    before_v20 = snapshot(root, files_under(root / "outputs/v20"))
    before_v21 = snapshot(root, v21_current_files(root))
    before_protected = snapshot(root, protected_files(root))
    keep_before = {
        clean(row.get("file_path")).replace("\\", "/"):
        file_hash(root / clean(row.get("file_path"))) if (root / clean(row.get("file_path"))).is_file() else ""
        for row in keep_rows
    }

    copy_logs: list[dict[str, object]] = []
    if inputs_valid and not unsafe_candidates and not protected_overlap:
        copy_logs = copy_candidates(root, archive_root, candidate_rows)
    if after_copy_hook:
        after_copy_hook(archive_root)
    hash_rows = validate_hashes(root, copy_logs)
    if mutation_hook:
        mutation_hook()

    keep_validation = validate_keep(root, keep_rows, keep_before)
    protected_validation = validate_protected(root, archive_root, protected_rows, candidate_paths)
    isolation_rows, reads_scripts, reads_outputs, reads_stale = source_isolation_audit(root)

    after_files = {rel(root, path) for path in root.rglob("*") if path.is_file()}
    deleted_or_moved = bool(before_files - after_files)
    allowed_new_prefix = f"{ARCHIVE_ROOT_REL}/"
    unexpected_new = {
        path for path in after_files - before_files
        if not path.startswith(allowed_new_prefix) and Path(path).name not in OUTPUT_NAMES
    }
    source_changes = changed(before_sources, snapshot(root, source_files(root)))
    v20_changes = changed(before_v20, snapshot(root, files_under(root / "outputs/v20")))
    v21_changes = changed(before_v21, snapshot(root, v21_current_files(root)))
    protected_changes = changed(before_protected, snapshot(root, protected_files(root)))

    success_statuses = {"COPIED", "ALREADY_ARCHIVED_HASH_MATCH"}
    copy_success = sum(1 for row in copy_logs if clean(row["copy_status"]) in success_statuses)
    copy_failures = len(copy_logs) - copy_success
    hash_validated = sum(1 for row in hash_rows if row["hash_match"] == "TRUE")
    hash_mismatch = sum(1 for row in hash_rows if row["validation_status"] == "HASH_MISMATCH")
    missing_archive = sum(1 for row in hash_rows if row["validation_status"] == "MISSING_ARCHIVE_COPY")
    keep_pass = len(keep_validation) == len(keep_rows) and all(row["validation_status"] == "PASS" for row in keep_validation)
    protected_archived_count = sum(1 for row in protected_validation if row["archive_exists"] == "TRUE" or row["overlap_with_archive_candidate"] == "TRUE")
    protected_pass = protected_archived_count == 0
    isolation_pass_after = not (reads_scripts or reads_outputs or reads_stale)
    package_rows = build_packages(package_plan_rows, candidate_rows, hash_rows)
    archive_package_count = len(package_rows)

    ready = (
        inputs_valid and not unsafe_candidates and not protected_overlap
        and len(copy_logs) == len(candidate_rows)
        and copy_success == len(candidate_rows)
        and copy_failures == 0 and hash_mismatch == 0 and missing_archive == 0
        and hash_validated == len(candidate_rows)
        and keep_pass and protected_pass and isolation_pass_after
        and not deleted_or_moved and not unexpected_new and not source_changes
        and not v20_changes and not v21_changes and not protected_changes
    )

    if not inputs_valid:
        final_status = BLOCKED_INPUT
        decision = "BLOCK_SOURCE_INPUT_MISSING_OR_INVALID"
    elif unsafe_candidates:
        final_status = BLOCKED_UNSAFE
        decision = "BLOCK_UNSAFE_ARCHIVE_CANDIDATES"
    elif protected_overlap or protected_archived_count:
        final_status = BLOCKED_PROTECTED_ATTEMPT
        decision = "BLOCK_PROTECTED_PATH_ARCHIVE_ATTEMPT"
    elif copy_failures or len(copy_logs) != len(candidate_rows) or missing_archive:
        final_status = BLOCKED_COPY
        decision = "BLOCK_COPY_FAILURE"
    elif hash_mismatch or hash_validated != len(candidate_rows):
        final_status = BLOCKED_HASH
        decision = "BLOCK_HASH_VALIDATION_FAILED"
    elif not isolation_pass_after:
        final_status = BLOCKED_ISOLATION
        decision = "BLOCK_SOURCE_ISOLATION_REGRESSED"
    elif ready:
        final_status = PASS_STATUS
        decision = "V20_ARCHIVE_COMMITTED_AND_VALIDATED"
    else:
        final_status = PARTIAL_STATUS
        decision = "ARCHIVE_COMMITTED_WITH_SKIPPED_SAFE_ENTRIES"

    if deleted_or_moved or unexpected_new or source_changes:
        final_status = BLOCKED_FILE
        decision = "BLOCK_FILE_MUTATION_DETECTED"
        ready = False
    if v20_changes:
        final_status = BLOCKED_V20
        decision = "BLOCK_V20_OUTPUT_MUTATION_DETECTED"
        ready = False
    if v21_changes:
        final_status = BLOCKED_V21
        decision = "BLOCK_V21_CURRENT_OUTPUT_MUTATION_DETECTED"
        ready = False
    if protected_changes:
        final_status = BLOCKED_PROTECTED
        decision = "BLOCK_PROTECTED_OUTPUT_MUTATION_DETECTED"
        ready = False

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
        ready = False

    validation_rows = [
        {"validation_item": "SOURCE_INPUTS", "status": "PASS" if inputs_valid else "BLOCK", "count": 0 if inputs_valid else 1, "details": "Dry-run state and all required manifests validated."},
        {"validation_item": "UNSAFE_CANDIDATES", "status": "PASS" if not unsafe_candidates else "BLOCK", "count": len(unsafe_candidates), "details": "No protected/active/unsafe candidate rows."},
        {"validation_item": "PROTECTED_OVERLAP", "status": "PASS" if not protected_overlap else "BLOCK", "count": len(protected_overlap), "details": "|".join(sorted(protected_overlap))},
        {"validation_item": "COPY_FAILURES", "status": "PASS" if copy_failures == 0 else "BLOCK", "count": copy_failures, "details": "Archive copy failures."},
        {"validation_item": "HASH_MISMATCHES", "status": "PASS" if hash_mismatch == 0 else "BLOCK", "count": hash_mismatch, "details": "Archive hash mismatches."},
        {"validation_item": "MISSING_ARCHIVE_COPIES", "status": "PASS" if missing_archive == 0 else "BLOCK", "count": missing_archive, "details": "Missing archive targets."},
        {"validation_item": "KEEP_REFERENCES", "status": "PASS" if keep_pass else "BLOCK", "count": sum(1 for row in keep_validation if row["validation_status"] != "PASS"), "details": "Keep/reference originals remain unchanged."},
        {"validation_item": "PROTECTED_PATHS", "status": "PASS" if protected_pass else "BLOCK", "count": protected_archived_count, "details": "Protected paths were not archived."},
        *isolation_rows,
        {"validation_item": "ORIGINAL_FILE_MUTATION", "status": "PASS" if not (deleted_or_moved or unexpected_new or source_changes or v20_changes or v21_changes or protected_changes) else "BLOCK", "count": len(source_changes) + len(v20_changes) + len(v21_changes) + len(protected_changes), "details": "Original source/output/protected files unchanged."},
    ]

    summary: dict[str, object] = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "source_archive_dry_run_status": clean(dry_summary.get("final_status")) or "NOT_AVAILABLE",
        "source_ready_for_v20_archive_commit": clean(dry_summary.get("ready_for_v20_archive_commit")) or "FALSE",
        "source_isolation_pass": clean(dry_summary.get("source_isolation_pass")) or "FALSE",
        "archive_candidate_count": len(candidate_rows),
        "archive_copy_attempt_count": len(copy_logs),
        "archive_copy_success_count": copy_success,
        "archive_copy_failure_count": copy_failures,
        "archive_hash_validated_count": hash_validated,
        "archive_hash_mismatch_count": hash_mismatch,
        "missing_archive_copy_count": missing_archive,
        "keep_reference_count": len(keep_rows),
        "keep_reference_validation_pass": tf(keep_pass),
        "protected_never_archive_count": len(protected_rows),
        "protected_path_archived_count": protected_archived_count,
        "protected_path_validation_pass": tf(protected_pass),
        "archive_package_count": archive_package_count,
        "archive_root": ARCHIVE_ROOT_REL,
        "archive_commit_allowed": "TRUE",
        "deletion_allowed": "FALSE",
        "migration_allowed": "FALSE",
        "files_deleted_or_moved": tf(deleted_or_moved),
        "source_files_mutated": tf(bool(source_changes)),
        "v20_outputs_mutated": tf(bool(v20_changes)),
        "v21_current_outputs_mutated": tf(bool(v21_changes)),
        "protected_outputs_mutated": tf(bool(protected_changes)),
        "protected_output_mutation_count": len(protected_changes),
        "v21_active_current_reads_v20_scripts_after_archive": tf(reads_scripts),
        "v21_active_current_reads_v20_outputs_after_archive": tf(reads_outputs),
        "v21_active_current_reads_v20_8_to_v20_16_stale_downstream_after_archive": tf(reads_stale),
        "source_isolation_pass_after_archive": tf(isolation_pass_after),
        "ready_for_v20_delete_candidate_dry_run": tf(ready),
        **permissions,
        "research_only": "TRUE",
        "recommended_next_stage": "V20_DELETE_CANDIDATE_DRY_RUN" if ready else "V20_ARCHIVE_COMMIT_R1A_REPAIR",
        "created_at_utc": utc_now(),
    }

    write_csv(migration / "V20_ARCHIVE_COMMIT_SUMMARY.csv", [summary], SUMMARY_FIELDS)
    write_csv(migration / "V20_ARCHIVE_COMMIT_COPY_LOG.csv", copy_logs, COPY_FIELDS)
    write_csv(migration / "V20_ARCHIVE_COMMIT_HASH_MANIFEST.csv", hash_rows, HASH_FIELDS)
    write_csv(migration / "V20_ARCHIVE_COMMIT_PACKAGE_MANIFEST.csv", package_rows, PACKAGE_FIELDS)
    write_csv(migration / "V20_ARCHIVE_COMMIT_VALIDATION_AUDIT.csv", validation_rows, VALIDATION_FIELDS)
    write_csv(migration / "V20_ARCHIVE_COMMIT_KEEP_REFERENCE_VALIDATION.csv", keep_validation, KEEP_FIELDS)
    write_csv(migration / "V20_ARCHIVE_COMMIT_PROTECTED_PATH_VALIDATION.csv", protected_validation, PROTECTED_FIELDS)
    read_center.mkdir(parents=True, exist_ok=True)
    (read_center / "V20_ARCHIVE_COMMIT_REPORT.md").write_text(render_report(summary), encoding="utf-8")
    return summary, {
        "copy_logs": copy_logs, "hashes": hash_rows, "packages": package_rows,
        "validation": validation_rows, "keep": keep_validation,
        "protected": protected_validation,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    summary, _ = run_archive_commit(args.root)
    for field in SUMMARY_FIELDS:
        print(f"{field.upper()}={summary.get(field, '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
