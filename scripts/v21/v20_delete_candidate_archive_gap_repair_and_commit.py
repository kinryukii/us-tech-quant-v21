#!/usr/bin/env python
"""Archive and delete only the exact V20 future-delete candidate queue."""

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
STAGE = "V20_DELETE_CANDIDATE_ARCHIVE_GAP_REPAIR_AND_COMMIT"
GAP_ARCHIVE_ROOT_REL = "archive/v20_legacy_archive/delete_candidate_gap_repair"
EXPECTED_QUEUE_COUNT = 117

PASS_STATUS = "PASS_V20_DELETE_CANDIDATES_ARCHIVED_AND_DELETED"
PARTIAL_STATUS = "PARTIAL_PASS_V20_DELETE_CANDIDATES_ARCHIVED_DELETE_PARTIAL"
BLOCKED_INPUT = "BLOCKED_V20_DELETE_CANDIDATE_COMMIT_SOURCE_INPUT_MISSING_OR_INVALID"
BLOCKED_OVERLAP = "BLOCKED_V20_DELETE_CANDIDATE_COMMIT_KEEP_OR_PROTECTED_OVERLAP"
BLOCKED_ACTIVE = "BLOCKED_V20_DELETE_CANDIDATE_COMMIT_ACTIVE_V21_DEPENDENCY_FOUND"
BLOCKED_ARCHIVE = "BLOCKED_V20_DELETE_CANDIDATE_COMMIT_ARCHIVE_GAP_VALIDATION_FAILED"
BLOCKED_ISOLATION = "BLOCKED_V20_DELETE_CANDIDATE_COMMIT_SOURCE_ISOLATION_REGRESSED_BEFORE_DELETE"
BLOCKED_DELETE = "BLOCKED_V20_DELETE_CANDIDATE_COMMIT_DELETE_FAILURE"
BLOCKED_POST = "BLOCKED_V20_DELETE_CANDIDATE_COMMIT_POST_DELETE_VALIDATION_FAILED"
BLOCKED_V20 = "BLOCKED_V20_DELETE_CANDIDATE_COMMIT_V20_OUTPUT_MUTATION_DETECTED"
BLOCKED_V21 = "BLOCKED_V20_DELETE_CANDIDATE_COMMIT_V21_CURRENT_OUTPUT_MUTATION_DETECTED"
BLOCKED_PROTECTED = "BLOCKED_V20_DELETE_CANDIDATE_COMMIT_PROTECTED_OUTPUT_MUTATION_DETECTED"
BLOCKED_PERMISSION = "BLOCKED_V20_DELETE_CANDIDATE_COMMIT_OFFICIAL_PERMISSION_VIOLATION"

SUMMARY_FIELDS = [
    "stage", "final_status", "decision",
    "source_delete_candidate_dry_run_status", "source_archive_commit_status",
    "candidate_queue_count", "gap_archive_root",
    "gap_archive_copy_attempt_count", "gap_archive_copy_success_count",
    "gap_archive_copy_failure_count", "gap_archive_hash_validated_count",
    "gap_archive_hash_mismatch_count", "missing_gap_archive_copy_count",
    "keep_reference_overlap_count", "protected_overlap_count",
    "active_v21_dependency_overlap_count",
    "unsafe_delete_candidate_count_before_commit", "delete_commit_allowed",
    "delete_attempt_count", "delete_success_count", "delete_failure_count",
    "deleted_file_count", "deleted_size_mb", "files_deleted_or_moved",
    "files_archived_or_copied", "source_files_mutated",
    "v20_outputs_mutated", "v21_current_outputs_mutated",
    "protected_outputs_mutated", "protected_output_mutation_count",
    "v21_active_current_reads_v20_scripts_before_delete",
    "v21_active_current_reads_v20_outputs_before_delete",
    "v21_active_current_reads_v20_8_to_v20_16_stale_downstream_before_delete",
    "source_isolation_pass_before_delete",
    "v21_active_current_reads_v20_scripts_after_delete",
    "v21_active_current_reads_v20_outputs_after_delete",
    "v21_active_current_reads_v20_8_to_v20_16_stale_downstream_after_delete",
    "source_isolation_pass_after_delete", "archive_gap_repair_validated",
    "post_delete_validation_pass", "official_activation_allowed",
    "official_recommendation_allowed", "official_ranking_mutation_allowed",
    "official_weight_mutation_allowed", "broker_execution_allowed",
    "trade_action_allowed", "research_only", "recommended_next_stage",
    "created_at_utc",
]
COPY_FIELDS = [
    "source_path", "archive_path", "source_exists_before", "source_size_bytes",
    "source_hash", "archive_preexisting", "archive_size_bytes", "archive_hash",
    "copy_status", "error",
]
HASH_FIELDS = [
    "original_path", "archive_path", "original_hash", "archive_hash",
    "hash_match", "archive_exists", "validation_status",
]
DELETE_FIELDS = [
    "file_path", "approved_queue_member", "archive_validated",
    "existed_before_delete", "delete_attempted", "delete_success",
    "exists_after_delete", "size_bytes", "delete_status", "error",
]
AUDIT_FIELDS = ["validation_item", "status", "count", "details"]
ROLLBACK_FIELDS = [
    "original_path", "archive_path", "original_hash", "archive_hash",
    "delete_status", "restore_instruction",
]

DRY_SUMMARY = "V20_DELETE_CANDIDATE_DRY_RUN_SUMMARY.csv"
QUEUE = "V20_FUTURE_DELETE_CANDIDATE_DRY_RUN_QUEUE.csv"
KEEP = "V20_KEEP_ACTIVE_OR_REFERENCE_MANIFEST.csv"
PROTECTED = "V20_PROTECTED_NEVER_ARCHIVE_MANIFEST.csv"
ARCHIVE_SUMMARY = "V20_ARCHIVE_COMMIT_SUMMARY.csv"
ARCHIVE_HASHES = "V20_ARCHIVE_COMMIT_HASH_MANIFEST.csv"
ISOLATION_SUMMARY = "V21_054_R1_POST_MIGRATION_SOURCE_ISOLATION_RECHECK_SUMMARY.csv"

OUTPUT_NAMES = {
    "V20_DELETE_CANDIDATE_ARCHIVE_GAP_REPAIR_AND_COMMIT_SUMMARY.csv",
    "V20_DELETE_CANDIDATE_GAP_ARCHIVE_COPY_LOG.csv",
    "V20_DELETE_CANDIDATE_GAP_ARCHIVE_HASH_MANIFEST.csv",
    "V20_DELETE_CANDIDATE_COMMIT_DELETE_LOG.csv",
    "V20_DELETE_CANDIDATE_POST_DELETE_VALIDATION_AUDIT.csv",
    "V20_DELETE_CANDIDATE_COMMIT_ROLLBACK_EVIDENCE_MANIFEST.csv",
    "V20_DELETE_CANDIDATE_ARCHIVE_GAP_REPAIR_AND_COMMIT_REPORT.md",
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


def safe_queue_path(value: str) -> bool:
    path = Path(value.replace("\\", "/"))
    normalized = path.as_posix()
    return (
        bool(value) and not path.is_absolute() and ".." not in path.parts
        and normalized.startswith(("scripts/v20/", "outputs/v20/"))
    )


def is_stage_output(path: Path) -> bool:
    return path.name in OUTPUT_NAMES


def source_files(root: Path, queue_paths: set[str]) -> list[Path]:
    return [
        path for path in files_under(root / "scripts")
        if path.suffix.lower() in ACTIVE_SUFFIXES
        and rel(root, path) not in queue_paths
        and path.name not in {
            "v20_delete_candidate_archive_gap_repair_and_commit.py",
            "run_v20_delete_candidate_archive_gap_repair_and_commit.ps1",
            "test_v20_delete_candidate_archive_gap_repair_and_commit.py",
        }
    ]


def v20_non_candidate_files(root: Path, queue_paths: set[str]) -> list[Path]:
    return [path for path in files_under(root / "outputs/v20") if rel(root, path) not in queue_paths]


def v21_current_files(root: Path) -> list[Path]:
    return [path for path in files_under(root / "outputs/v21") if not is_stage_output(path)]


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


def valid_dry_summary(row: dict[str, str]) -> bool:
    return (
        clean(row.get("final_status"))
        == "BLOCKED_V20_DELETE_CANDIDATE_DRY_RUN_ARCHIVE_VALIDATION_FAILED"
        and as_int(row.get("candidate_queue_count")) == EXPECTED_QUEUE_COUNT
        and as_int(row.get("missing_archive_for_deletion_candidate_count")) == EXPECTED_QUEUE_COUNT
        and as_int(row.get("keep_reference_overlap_count")) == 0
        and as_int(row.get("protected_overlap_count")) == 0
        and as_int(row.get("active_v21_dependency_overlap_count")) == 0
        and as_bool(row.get("source_isolation_pass"))
        and not as_bool(row.get("v20_outputs_mutated"))
        and not as_bool(row.get("v21_current_outputs_mutated"))
        and not as_bool(row.get("protected_outputs_mutated"))
    )


def valid_archive_summary(row: dict[str, str]) -> bool:
    return (
        clean(row.get("final_status"))
        == "PASS_V20_ARCHIVE_COMMITTED_READY_FOR_DELETE_CANDIDATE_DRY_RUN"
        and as_bool(row.get("source_isolation_pass_after_archive"))
        and as_int(row.get("protected_path_archived_count")) == 0
        and as_int(row.get("archive_hash_mismatch_count")) == 0
        and as_int(row.get("missing_archive_copy_count")) == 0
    )


def active_current_source_file(path: Path, root: Path) -> bool:
    name = path.name.lower()
    if path.suffix.lower() not in ACTIVE_SUFFIXES or name.startswith("test_"):
        return False
    if name.startswith(("v21_047", "v21_050", "v21_051", "v21_052", "v21_053", "v21_054")):
        return False
    inactive = (
        "audit", "plan", "dry_run", "archive", "delete_candidate",
        "discovery", "ablation", "historical", "forensic", "review",
    )
    if any(token in name for token in inactive):
        return False
    return rel(root, path).startswith(("scripts/v21/", "scripts/shared/", "configs/"))


def isolation_scan(
    root: Path, queue_paths: set[str],
) -> tuple[dict[str, list[str]], bool, bool, bool]:
    overlaps = {path: [] for path in queue_paths}
    script_read = False
    output_read = False
    stale_read = False
    for base in (root / "scripts/v21", root / "scripts/shared", root / "configs"):
        for path in files_under(base):
            if not active_current_source_file(path, root):
                continue
            text = path.read_text(encoding="utf-8", errors="replace").replace("\\", "/")
            rpath = rel(root, path)
            has_script = "scripts/v20/" in text
            has_output = "outputs/v20/" in text
            script_read = script_read or has_script
            output_read = output_read or has_output
            stale_read = stale_read or ((has_script or has_output) and bool(STALE_RE.search(text)))
            for candidate in queue_paths:
                if candidate in text:
                    overlaps[candidate].append(rpath)
    return overlaps, script_read, output_read, stale_read


def archive_candidates(
    root: Path, queue_paths: list[str], prior_hashes: dict[str, dict[str, str]],
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, str], dict[str, int]]:
    gap_root = root / GAP_ARCHIVE_ROOT_REL
    copy_logs: list[dict[str, object]] = []
    hash_rows: list[dict[str, object]] = []
    original_hashes: dict[str, str] = {}
    original_sizes: dict[str, int] = {}
    for rpath in queue_paths:
        source = root / rpath
        target = gap_root / rpath
        prior = prior_hashes.get(rpath, {})
        prior_hash = clean(prior.get("original_hash"))
        exists = source.is_file()
        source_hash = file_hash(source) if exists else prior_hash
        source_size = source.stat().st_size if exists else 0
        preexisting = target.is_file()
        archive_hash = file_hash(target) if preexisting else ""
        status = "NOT_ATTEMPTED"
        error = ""
        try:
            if not safe_queue_path(rpath):
                status = "UNSAFE_PATH"
                error = "Path is outside approved V20 queue boundaries."
            elif not exists:
                if preexisting and prior_hash and archive_hash == prior_hash:
                    status = "SOURCE_ALREADY_DELETED_ARCHIVE_VALIDATED"
                else:
                    status = "SOURCE_MISSING_NO_VALIDATED_ARCHIVE"
                    error = "Source missing and no prior validated archive evidence."
            elif preexisting:
                status = "ALREADY_ARCHIVED_HASH_MATCH" if archive_hash == source_hash else "PREEXISTING_ARCHIVE_CONFLICT"
                if archive_hash != source_hash:
                    error = "Existing gap archive hash differs; not overwritten."
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                archive_hash = file_hash(target)
                status = "COPIED" if archive_hash == source_hash else "COPIED_HASH_MISMATCH"
        except Exception as exc:  # pragma: no cover
            status = "COPY_FAILED"
            error = str(exc)
        archive_size = target.stat().st_size if target.is_file() else 0
        valid = bool(source_hash) and target.is_file() and archive_hash == source_hash
        original_hashes[rpath] = source_hash
        original_sizes[rpath] = source_size
        copy_logs.append({
            "source_path": rpath,
            "archive_path": f"{GAP_ARCHIVE_ROOT_REL}/{rpath}",
            "source_exists_before": tf(exists),
            "source_size_bytes": source_size,
            "source_hash": source_hash,
            "archive_preexisting": tf(preexisting),
            "archive_size_bytes": archive_size,
            "archive_hash": archive_hash,
            "copy_status": status,
            "error": error,
        })
        hash_rows.append({
            "original_path": rpath,
            "archive_path": f"{GAP_ARCHIVE_ROOT_REL}/{rpath}",
            "original_hash": source_hash,
            "archive_hash": archive_hash,
            "hash_match": tf(valid),
            "archive_exists": tf(target.is_file()),
            "validation_status": "PASS" if valid else "MISSING_ARCHIVE" if not target.is_file() else "HASH_MISMATCH",
        })
    return copy_logs, hash_rows, original_hashes, original_sizes


def delete_candidates(
    root: Path,
    queue_paths: list[str],
    validated_paths: set[str],
    original_sizes: dict[str, int],
) -> list[dict[str, object]]:
    logs: list[dict[str, object]] = []
    for rpath in queue_paths:
        path = root / rpath
        existed = path.is_file()
        attempted = existed and rpath in validated_paths
        success = False
        error = ""
        status = "NOT_ATTEMPTED"
        try:
            if rpath not in validated_paths:
                status = "BLOCKED_NOT_ARCHIVE_VALIDATED"
            elif not existed:
                status = "ALREADY_DELETED_REPEAT_SAFE"
                success = True
            else:
                path.unlink()
                success = not path.exists()
                status = "DELETED" if success else "DELETE_FAILED_STILL_EXISTS"
        except Exception as exc:  # pragma: no cover
            status = "DELETE_FAILED"
            error = str(exc)
        logs.append({
            "file_path": rpath,
            "approved_queue_member": "TRUE",
            "archive_validated": tf(rpath in validated_paths),
            "existed_before_delete": tf(existed),
            "delete_attempted": tf(attempted),
            "delete_success": tf(success),
            "exists_after_delete": tf(path.exists()),
            "size_bytes": original_sizes.get(rpath, 0),
            "delete_status": status,
            "error": error,
        })
    return logs


def render_report(summary: dict[str, object]) -> str:
    return f"""# V20 Delete Candidate Archive Gap Repair and Commit

- final_status: {summary['final_status']}
- decision: {summary['decision']}
- candidate_queue_count: {summary['candidate_queue_count']}
- gap_archive_hash_validated_count: {summary['gap_archive_hash_validated_count']}
- delete_success_count: {summary['delete_success_count']}
- deleted_file_count: {summary['deleted_file_count']}
- source_isolation_pass_before_delete: {summary['source_isolation_pass_before_delete']}
- source_isolation_pass_after_delete: {summary['source_isolation_pass_after_delete']}
- archive_gap_repair_validated: {summary['archive_gap_repair_validated']}
- post_delete_validation_pass: {summary['post_delete_validation_pass']}
- recommended_next_stage: {summary['recommended_next_stage']}

Only paths in the persisted 117-row future-delete queue were eligible. Each
path required a same-stage validated archive copy before deletion. No directory
was deleted.
"""


def run_commit(
    root: Path,
    before_delete_hook: Callable[[Path], None] | None = None,
    after_delete_hook: Callable[[Path], None] | None = None,
) -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
    root = root.resolve()
    migration = root / "outputs/v21/migration"
    read_center = root / "outputs/v21/read_center"
    dry = read_first(migration / DRY_SUMMARY)
    archive_summary = read_first(migration / ARCHIVE_SUMMARY)
    queue_rows, _ = read_csv(migration / QUEUE)
    keep_rows, _ = read_csv(migration / KEEP)
    protected_rows, _ = read_csv(migration / PROTECTED)
    archive_hash_rows, _ = read_csv(migration / ARCHIVE_HASHES)
    isolation_summary = read_first(migration / ISOLATION_SUMMARY)
    required = [
        migration / name for name in (
            DRY_SUMMARY, QUEUE, KEEP, PROTECTED, ARCHIVE_SUMMARY,
            ARCHIVE_HASHES, ISOLATION_SUMMARY,
        )
    ]
    queue_paths = [clean(row.get("file_path")).replace("\\", "/") for row in queue_rows]
    queue_set = set(queue_paths)
    unique_queue = len(queue_set) == len(queue_paths)
    inputs_valid = (
        all(path.exists() for path in required)
        and valid_dry_summary(dry)
        and valid_archive_summary(archive_summary)
        and len(queue_rows) == EXPECTED_QUEUE_COUNT
        and unique_queue
        and all(safe_queue_path(path) for path in queue_paths)
        and bool(archive_hash_rows)
        and as_bool(isolation_summary.get("source_isolation_pass"))
    )

    keep_paths = {clean(row.get("file_path")).replace("\\", "/") for row in keep_rows}
    protected_paths = {clean(row.get("file_path")).replace("\\", "/") for row in protected_rows}
    keep_overlap = queue_set & keep_paths
    protected_overlap = queue_set & protected_paths
    active_before, before_scripts, before_outputs, before_stale = isolation_scan(root, queue_set)
    active_overlap = {path for path, refs in active_before.items() if refs}
    isolation_before = not (before_scripts or before_outputs or before_stale)
    unsafe_before = len(keep_overlap | protected_overlap | active_overlap)

    before_all_files = {rel(root, p) for p in root.rglob("*") if p.is_file()}
    before_sources = snapshot(root, source_files(root, queue_set))
    before_v20_other = snapshot(root, v20_non_candidate_files(root, queue_set))
    before_v21 = snapshot(root, v21_current_files(root))
    before_protected = snapshot(root, protected_files(root))
    keep_before = snapshot(root, [root / path for path in keep_paths if (root / path).is_file()])
    protected_manifest_before = snapshot(root, [root / path for path in protected_paths if (root / path).is_file()])

    prior_rows, _ = read_csv(migration / "V20_DELETE_CANDIDATE_COMMIT_ROLLBACK_EVIDENCE_MANIFEST.csv")
    prior_hashes = {clean(row.get("original_path")): row for row in prior_rows}
    copy_logs: list[dict[str, object]] = []
    hash_rows: list[dict[str, object]] = []
    original_hashes: dict[str, str] = {}
    original_sizes: dict[str, int] = {}
    if inputs_valid and not keep_overlap and not protected_overlap and not active_overlap and isolation_before:
        copy_logs, hash_rows, original_hashes, original_sizes = archive_candidates(
            root, queue_paths, prior_hashes
        )
    if before_delete_hook:
        before_delete_hook(root / GAP_ARCHIVE_ROOT_REL)

    # Revalidate archive files after any hook and immediately before deletion.
    for row in hash_rows:
        archive = root / clean(row["archive_path"])
        archive_hash = file_hash(archive) if archive.is_file() else ""
        expected = clean(row["original_hash"])
        valid = bool(expected) and archive_hash == expected
        row["archive_hash"] = archive_hash
        row["archive_exists"] = tf(archive.is_file())
        row["hash_match"] = tf(valid)
        row["validation_status"] = "PASS" if valid else "MISSING_ARCHIVE" if not archive.is_file() else "HASH_MISMATCH"

    validated_paths = {
        clean(row["original_path"]) for row in hash_rows
        if row["validation_status"] == "PASS"
    }
    gap_validated = len(validated_paths) == EXPECTED_QUEUE_COUNT
    delete_allowed = (
        inputs_valid and not keep_overlap and not protected_overlap
        and not active_overlap and isolation_before and gap_validated
    )
    delete_logs = delete_candidates(
        root, queue_paths, validated_paths, original_sizes
    ) if delete_allowed else []
    if after_delete_hook:
        after_delete_hook(root / GAP_ARCHIVE_ROOT_REL)

    active_after, after_scripts, after_outputs, after_stale = isolation_scan(root, queue_set)
    isolation_after = not (after_scripts or after_outputs or after_stale)
    after_sources = snapshot(root, source_files(root, queue_set))
    after_v20_other = snapshot(root, v20_non_candidate_files(root, queue_set))
    after_v21 = snapshot(root, v21_current_files(root))
    after_protected = snapshot(root, protected_files(root))
    source_changes = changed(before_sources, after_sources)
    v20_other_changes = changed(before_v20_other, after_v20_other)
    v21_changes = changed(before_v21, after_v21)
    protected_changes = changed(before_protected, after_protected)
    keep_after = snapshot(root, [root / path for path in keep_paths if (root / path).is_file()])
    protected_manifest_after = snapshot(root, [root / path for path in protected_paths if (root / path).is_file()])
    keep_ok = keep_before == keep_after and len(keep_after) == len(keep_before)
    protected_manifest_ok = (
        protected_manifest_before == protected_manifest_after
        and len(protected_manifest_after) == len(protected_manifest_before)
    )

    copy_success_statuses = {
        "COPIED", "ALREADY_ARCHIVED_HASH_MATCH",
        "SOURCE_ALREADY_DELETED_ARCHIVE_VALIDATED",
    }
    copy_success = sum(1 for row in copy_logs if clean(row["copy_status"]) in copy_success_statuses)
    copy_failures = len(copy_logs) - copy_success
    hash_validated = sum(1 for row in hash_rows if row["validation_status"] == "PASS")
    hash_mismatch = sum(1 for row in hash_rows if row["validation_status"] == "HASH_MISMATCH")
    missing_archive = sum(1 for row in hash_rows if row["validation_status"] == "MISSING_ARCHIVE")
    delete_attempts = sum(1 for row in delete_logs if row["delete_attempted"] == "TRUE")
    delete_success = sum(1 for row in delete_logs if row["delete_success"] == "TRUE")
    delete_failures = sum(1 for row in delete_logs if row["delete_success"] != "TRUE")
    deleted_now = sum(1 for row in delete_logs if row["delete_status"] == "DELETED")
    deleted_size = round(
        sum(int(row["size_bytes"]) for row in delete_logs if row["delete_status"] == "DELETED")
        / (1024 * 1024), 6
    )
    originals_absent = all(not (root / path).exists() for path in queue_paths)
    archives_valid_after = all(
        (root / f"{GAP_ARCHIVE_ROOT_REL}/{path}").is_file()
        and file_hash(root / f"{GAP_ARCHIVE_ROOT_REL}/{path}") == original_hashes.get(path, clean(prior_hashes.get(path, {}).get("original_hash")))
        for path in queue_paths
    )
    post_pass = (
        delete_allowed and len(delete_logs) == EXPECTED_QUEUE_COUNT
        and delete_failures == 0 and originals_absent and archives_valid_after
        and keep_ok and protected_manifest_ok and isolation_after
        and not source_changes and not v20_other_changes
        and not v21_changes and not protected_changes
    )

    if not inputs_valid:
        final_status = BLOCKED_INPUT
        decision = "BLOCK_SOURCE_INPUT_MISSING_OR_INVALID"
    elif keep_overlap or protected_overlap:
        final_status = BLOCKED_OVERLAP
        decision = "BLOCK_KEEP_OR_PROTECTED_OVERLAP"
    elif active_overlap:
        final_status = BLOCKED_ACTIVE
        decision = "BLOCK_ACTIVE_V21_DEPENDENCY_FOUND"
    elif not isolation_before:
        final_status = BLOCKED_ISOLATION
        decision = "BLOCK_SOURCE_ISOLATION_REGRESSED_BEFORE_DELETE"
    elif not gap_validated:
        final_status = BLOCKED_ARCHIVE
        decision = "BLOCK_ARCHIVE_GAP_VALIDATION_FAILED"
    elif delete_failures:
        final_status = BLOCKED_DELETE
        decision = "BLOCK_DELETE_FAILURE"
    elif not post_pass:
        final_status = BLOCKED_POST
        decision = "BLOCK_POST_DELETE_VALIDATION_FAILED"
    else:
        final_status = PASS_STATUS
        decision = "DELETE_CANDIDATES_ARCHIVED_VALIDATED_AND_DELETED"

    if v20_other_changes or source_changes:
        final_status = BLOCKED_V20
        decision = "BLOCK_UNAPPROVED_V20_OR_SOURCE_MUTATION_DETECTED"
        post_pass = False
    if v21_changes:
        final_status = BLOCKED_V21
        decision = "BLOCK_V21_CURRENT_OUTPUT_MUTATION_DETECTED"
        post_pass = False
    if protected_changes or not protected_manifest_ok:
        final_status = BLOCKED_PROTECTED
        decision = "BLOCK_PROTECTED_OUTPUT_MUTATION_DETECTED"
        post_pass = False

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
        post_pass = False

    rollback_rows = [{
        "original_path": path,
        "archive_path": f"{GAP_ARCHIVE_ROOT_REL}/{path}",
        "original_hash": original_hashes.get(path, clean(prior_hashes.get(path, {}).get("original_hash"))),
        "archive_hash": file_hash(root / f"{GAP_ARCHIVE_ROOT_REL}/{path}") if (root / f"{GAP_ARCHIVE_ROOT_REL}/{path}").is_file() else "",
        "delete_status": next((clean(row["delete_status"]) for row in delete_logs if row["file_path"] == path), "NOT_ATTEMPTED"),
        "restore_instruction": f"Copy {GAP_ARCHIVE_ROOT_REL}/{path} to {path} and verify SHA-256.",
    } for path in queue_paths]

    after_all_files = {rel(root, p) for p in root.rglob("*") if p.is_file()}
    removed_paths = before_all_files - after_all_files
    unapproved_removed = removed_paths - queue_set
    if unapproved_removed:
        final_status = BLOCKED_POST
        decision = "BLOCK_UNAPPROVED_FILE_DELETION_DETECTED"
        post_pass = False

    audit_rows = [
        {"validation_item": "SOURCE_INPUTS", "status": "PASS" if inputs_valid else "BLOCK", "count": 0 if inputs_valid else 1, "details": "Prior dry-run and archive commit states validated."},
        {"validation_item": "EXACT_QUEUE_BOUNDARY", "status": "PASS" if len(queue_paths) == EXPECTED_QUEUE_COUNT and unique_queue else "BLOCK", "count": len(queue_paths), "details": "Exactly 117 unique approved paths required."},
        {"validation_item": "KEEP_PROTECTED_OVERLAP", "status": "PASS" if not keep_overlap and not protected_overlap else "BLOCK", "count": len(keep_overlap) + len(protected_overlap), "details": "|".join(sorted(keep_overlap | protected_overlap))},
        {"validation_item": "ACTIVE_DEPENDENCY_OVERLAP", "status": "PASS" if not active_overlap else "BLOCK", "count": len(active_overlap), "details": "|".join(sorted(active_overlap))},
        {"validation_item": "GAP_ARCHIVE_HASH_VALIDATION", "status": "PASS" if gap_validated else "BLOCK", "count": hash_validated, "details": f"{hash_validated}/{EXPECTED_QUEUE_COUNT} validated."},
        {"validation_item": "DELETE_BOUNDARY", "status": "PASS" if not unapproved_removed else "BLOCK", "count": len(unapproved_removed), "details": "|".join(sorted(unapproved_removed))},
        {"validation_item": "ORIGINALS_ABSENT", "status": "PASS" if originals_absent else "BLOCK", "count": sum(1 for path in queue_paths if (root / path).exists()), "details": "All approved originals absent after commit."},
        {"validation_item": "ARCHIVES_RETAINED", "status": "PASS" if archives_valid_after else "BLOCK", "count": hash_validated, "details": "Gap archive copies retained and hash-valid."},
        {"validation_item": "KEEP_REFERENCE_PRESERVED", "status": "PASS" if keep_ok else "BLOCK", "count": len(keep_before), "details": "Keep/reference files unchanged."},
        {"validation_item": "PROTECTED_PRESERVED", "status": "PASS" if protected_manifest_ok and not protected_changes else "BLOCK", "count": len(protected_changes), "details": "Protected files unchanged."},
        {"validation_item": "SOURCE_ISOLATION_AFTER", "status": "PASS" if isolation_after else "BLOCK", "count": 0 if isolation_after else 1, "details": "No active/current V21 V20 dependency."},
    ]

    summary: dict[str, object] = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "source_delete_candidate_dry_run_status": clean(dry.get("final_status")) or "NOT_AVAILABLE",
        "source_archive_commit_status": clean(archive_summary.get("final_status")) or "NOT_AVAILABLE",
        "candidate_queue_count": len(queue_paths),
        "gap_archive_root": GAP_ARCHIVE_ROOT_REL,
        "gap_archive_copy_attempt_count": len(copy_logs),
        "gap_archive_copy_success_count": copy_success,
        "gap_archive_copy_failure_count": copy_failures,
        "gap_archive_hash_validated_count": hash_validated,
        "gap_archive_hash_mismatch_count": hash_mismatch,
        "missing_gap_archive_copy_count": missing_archive,
        "keep_reference_overlap_count": len(keep_overlap),
        "protected_overlap_count": len(protected_overlap),
        "active_v21_dependency_overlap_count": len(active_overlap),
        "unsafe_delete_candidate_count_before_commit": unsafe_before,
        "delete_commit_allowed": tf(delete_allowed),
        "delete_attempt_count": delete_attempts,
        "delete_success_count": delete_success,
        "delete_failure_count": delete_failures,
        "deleted_file_count": deleted_now,
        "deleted_size_mb": deleted_size,
        "files_deleted_or_moved": tf(bool(removed_paths)),
        "files_archived_or_copied": tf(any(row["copy_status"] == "COPIED" for row in copy_logs)),
        "source_files_mutated": tf(bool(source_changes)),
        "v20_outputs_mutated": tf(bool(v20_other_changes)),
        "v21_current_outputs_mutated": tf(bool(v21_changes)),
        "protected_outputs_mutated": tf(bool(protected_changes) or not protected_manifest_ok),
        "protected_output_mutation_count": len(protected_changes),
        "v21_active_current_reads_v20_scripts_before_delete": tf(before_scripts),
        "v21_active_current_reads_v20_outputs_before_delete": tf(before_outputs),
        "v21_active_current_reads_v20_8_to_v20_16_stale_downstream_before_delete": tf(before_stale),
        "source_isolation_pass_before_delete": tf(isolation_before),
        "v21_active_current_reads_v20_scripts_after_delete": tf(after_scripts),
        "v21_active_current_reads_v20_outputs_after_delete": tf(after_outputs),
        "v21_active_current_reads_v20_8_to_v20_16_stale_downstream_after_delete": tf(after_stale),
        "source_isolation_pass_after_delete": tf(isolation_after),
        "archive_gap_repair_validated": tf(gap_validated),
        "post_delete_validation_pass": tf(post_pass),
        **permissions,
        "research_only": "TRUE",
        "recommended_next_stage": "V21.055-R1_POST_V20_CLEANUP_FINAL_AUDIT" if post_pass else "V20_DELETE_CANDIDATE_ARCHIVE_GAP_REPAIR_AND_COMMIT_R1A_REPAIR",
        "created_at_utc": utc_now(),
    }

    write_csv(migration / "V20_DELETE_CANDIDATE_ARCHIVE_GAP_REPAIR_AND_COMMIT_SUMMARY.csv", [summary], SUMMARY_FIELDS)
    write_csv(migration / "V20_DELETE_CANDIDATE_GAP_ARCHIVE_COPY_LOG.csv", copy_logs, COPY_FIELDS)
    write_csv(migration / "V20_DELETE_CANDIDATE_GAP_ARCHIVE_HASH_MANIFEST.csv", hash_rows, HASH_FIELDS)
    write_csv(migration / "V20_DELETE_CANDIDATE_COMMIT_DELETE_LOG.csv", delete_logs, DELETE_FIELDS)
    write_csv(migration / "V20_DELETE_CANDIDATE_POST_DELETE_VALIDATION_AUDIT.csv", audit_rows, AUDIT_FIELDS)
    write_csv(migration / "V20_DELETE_CANDIDATE_COMMIT_ROLLBACK_EVIDENCE_MANIFEST.csv", rollback_rows, ROLLBACK_FIELDS)
    read_center.mkdir(parents=True, exist_ok=True)
    (read_center / "V20_DELETE_CANDIDATE_ARCHIVE_GAP_REPAIR_AND_COMMIT_REPORT.md").write_text(render_report(summary), encoding="utf-8")
    return summary, {
        "copy": copy_logs, "hashes": hash_rows, "delete": delete_logs,
        "audit": audit_rows, "rollback": rollback_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    summary, _ = run_commit(args.root)
    for field in SUMMARY_FIELDS:
        print(f"{field.upper()}={summary.get(field, '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
