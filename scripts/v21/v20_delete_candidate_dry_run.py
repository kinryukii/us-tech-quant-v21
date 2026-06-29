#!/usr/bin/env python
"""Plan deletion candidates only after validating their archive copies."""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V20_DELETE_CANDIDATE_DRY_RUN"

PASS_STATUS = "PASS_V20_DELETE_CANDIDATE_DRY_RUN_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V20_DELETE_CANDIDATE_DRY_RUN_READY_WITH_REVIEW"
BLOCKED_INPUT = "BLOCKED_V20_DELETE_CANDIDATE_DRY_RUN_SOURCE_INPUT_MISSING_OR_INVALID"
BLOCKED_ARCHIVE = "BLOCKED_V20_DELETE_CANDIDATE_DRY_RUN_ARCHIVE_VALIDATION_FAILED"
BLOCKED_OVERLAP = "BLOCKED_V20_DELETE_CANDIDATE_DRY_RUN_KEEP_OR_PROTECTED_OVERLAP"
BLOCKED_ACTIVE = "BLOCKED_V20_DELETE_CANDIDATE_DRY_RUN_ACTIVE_V21_DEPENDENCY_FOUND"
BLOCKED_ISOLATION = "BLOCKED_V20_DELETE_CANDIDATE_DRY_RUN_SOURCE_ISOLATION_REGRESSED"
BLOCKED_FILE = "BLOCKED_V20_DELETE_CANDIDATE_DRY_RUN_FILE_MUTATION_DETECTED"
BLOCKED_V20 = "BLOCKED_V20_DELETE_CANDIDATE_DRY_RUN_V20_OUTPUT_MUTATION_DETECTED"
BLOCKED_V21 = "BLOCKED_V20_DELETE_CANDIDATE_DRY_RUN_V21_CURRENT_OUTPUT_MUTATION_DETECTED"
BLOCKED_PROTECTED = "BLOCKED_V20_DELETE_CANDIDATE_DRY_RUN_PROTECTED_OUTPUT_MUTATION_DETECTED"
BLOCKED_PERMISSION = "BLOCKED_V20_DELETE_CANDIDATE_DRY_RUN_OFFICIAL_PERMISSION_VIOLATION"

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "source_archive_commit_status",
    "source_ready_for_v20_delete_candidate_dry_run", "archive_root",
    "archive_copy_success_count", "archive_hash_mismatch_count",
    "missing_archive_copy_count", "source_isolation_pass_after_archive",
    "candidate_queue_count", "deletion_candidate_count",
    "archive_validated_deletion_candidate_count",
    "missing_archive_for_deletion_candidate_count",
    "hash_mismatch_for_deletion_candidate_count",
    "keep_reference_overlap_count", "protected_overlap_count",
    "active_v21_dependency_overlap_count", "unsafe_delete_candidate_count",
    "estimated_delete_size_mb", "deletion_dry_run_only",
    "deletion_allowed", "archive_allowed", "migration_allowed",
    "files_deleted_or_moved", "files_archived", "files_copied",
    "source_files_mutated", "v20_outputs_mutated",
    "v21_current_outputs_mutated", "protected_outputs_mutated",
    "protected_output_mutation_count",
    "v21_active_current_reads_v20_scripts",
    "v21_active_current_reads_v20_outputs",
    "v21_active_current_reads_v20_8_to_v20_16_stale_downstream",
    "source_isolation_pass", "ready_for_v20_delete_commit",
    "official_activation_allowed", "official_recommendation_allowed",
    "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
    "broker_execution_allowed", "trade_action_allowed", "research_only",
    "recommended_next_stage", "created_at_utc",
]
MANIFEST_FIELDS = [
    "file_path", "size_mb", "source_hash", "archive_path", "archive_hash",
    "archive_validation_status", "keep_overlap", "protected_overlap",
    "active_v21_dependency_overlap", "deletion_candidate_status",
    "risk_level", "reason",
]
ARCHIVE_VALIDATION_FIELDS = [
    "file_path", "archive_path", "source_exists", "archive_exists",
    "source_hash", "archive_hash", "hash_match", "validation_status",
]
OVERLAP_FIELDS = [
    "file_path", "keep_overlap", "protected_overlap", "overlap_status", "reason",
]
ACTIVE_FIELDS = [
    "file_path", "active_dependency_overlap", "referencing_files",
    "dependency_type", "status",
]
RISK_FIELDS = ["risk_id", "status", "severity", "count", "details", "mitigation"]

COMMIT_SUMMARY = "V20_ARCHIVE_COMMIT_SUMMARY.csv"
COPY_LOG = "V20_ARCHIVE_COMMIT_COPY_LOG.csv"
HASH_MANIFEST = "V20_ARCHIVE_COMMIT_HASH_MANIFEST.csv"
PACKAGE_MANIFEST = "V20_ARCHIVE_COMMIT_PACKAGE_MANIFEST.csv"
COMMIT_AUDIT = "V20_ARCHIVE_COMMIT_VALIDATION_AUDIT.csv"
COMMIT_KEEP_VALIDATION = "V20_ARCHIVE_COMMIT_KEEP_REFERENCE_VALIDATION.csv"
COMMIT_PROTECTED_VALIDATION = "V20_ARCHIVE_COMMIT_PROTECTED_PATH_VALIDATION.csv"
DELETE_QUEUE = "V20_FUTURE_DELETE_CANDIDATE_DRY_RUN_QUEUE.csv"
KEEP_MANIFEST = "V20_KEEP_ACTIVE_OR_REFERENCE_MANIFEST.csv"
PROTECTED_MANIFEST = "V20_PROTECTED_NEVER_ARCHIVE_MANIFEST.csv"
ISOLATION_SUMMARY = "V21_054_R1_POST_MIGRATION_SOURCE_ISOLATION_RECHECK_SUMMARY.csv"

OUTPUT_NAMES = {
    "V20_DELETE_CANDIDATE_DRY_RUN_SUMMARY.csv",
    "V20_DELETE_CANDIDATE_DRY_RUN_MANIFEST.csv",
    "V20_DELETE_CANDIDATE_ARCHIVE_COPY_VALIDATION.csv",
    "V20_DELETE_CANDIDATE_KEEP_PROTECTED_OVERLAP_AUDIT.csv",
    "V20_DELETE_CANDIDATE_ACTIVE_DEPENDENCY_AUDIT.csv",
    "V20_DELETE_CANDIDATE_RISK_AUDIT.csv",
    "V20_DELETE_CANDIDATE_DRY_RUN_REPORT.md",
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
    return sorted((path for path in base.rglob("*") if path.is_file()), key=lambda p: p.as_posix().lower())


def snapshot(root: Path, paths: Iterable[Path]) -> dict[str, str]:
    return {rel(root, path): file_hash(path) for path in paths if path.is_file()}


def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))


def is_stage_output(path: Path) -> bool:
    return path.name in OUTPUT_NAMES


def source_files(root: Path) -> list[Path]:
    return [
        path for path in files_under(root / "scripts")
        if path.suffix.lower() in ACTIVE_SUFFIXES
        and path.name not in {
            "v20_delete_candidate_dry_run.py",
            "run_v20_delete_candidate_dry_run.ps1",
            "test_v20_delete_candidate_dry_run.py",
        }
    ]


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


def validate_commit(summary: dict[str, str]) -> bool:
    return (
        clean(summary.get("final_status"))
        == "PASS_V20_ARCHIVE_COMMITTED_READY_FOR_DELETE_CANDIDATE_DRY_RUN"
        and as_bool(summary.get("ready_for_v20_delete_candidate_dry_run"))
        and as_int(summary.get("archive_copy_failure_count")) == 0
        and as_int(summary.get("archive_hash_mismatch_count")) == 0
        and as_int(summary.get("missing_archive_copy_count")) == 0
        and as_int(summary.get("protected_path_archived_count")) == 0
        and as_bool(summary.get("source_isolation_pass_after_archive"))
        and not as_bool(summary.get("v20_outputs_mutated"))
        and not as_bool(summary.get("v21_current_outputs_mutated"))
        and not as_bool(summary.get("protected_outputs_mutated"))
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


def scan_active_dependencies(
    root: Path,
    candidate_paths: set[str],
) -> tuple[dict[str, list[tuple[str, str]]], bool, bool, bool]:
    overlaps: dict[str, list[tuple[str, str]]] = {path: [] for path in candidate_paths}
    script_read = False
    output_read = False
    stale_read = False
    for base in (root / "scripts/v21", root / "scripts/shared", root / "configs"):
        for path in files_under(base):
            if not active_current_source_file(path, root):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            normalized = text.replace("\\", "/")
            rpath = rel(root, path)
            has_script = "scripts/v20/" in normalized
            has_output = "outputs/v20/" in normalized
            if has_script:
                script_read = True
            if has_output:
                output_read = True
            if (has_script or has_output) and STALE_RE.search(normalized):
                stale_read = True
            for candidate in candidate_paths:
                if candidate in normalized:
                    dependency_type = "V20_SCRIPT" if candidate.startswith("scripts/v20/") else "V20_OUTPUT"
                    overlaps[candidate].append((rpath, dependency_type))
    return overlaps, script_read, output_read, stale_read


def render_report(summary: dict[str, object]) -> str:
    return f"""# V20 Delete Candidate Dry-Run Report

- final_status: {summary['final_status']}
- decision: {summary['decision']}
- candidate_queue_count: {summary['candidate_queue_count']}
- deletion_candidate_count: {summary['deletion_candidate_count']}
- archive_validated_deletion_candidate_count: {summary['archive_validated_deletion_candidate_count']}
- missing_archive_for_deletion_candidate_count: {summary['missing_archive_for_deletion_candidate_count']}
- hash_mismatch_for_deletion_candidate_count: {summary['hash_mismatch_for_deletion_candidate_count']}
- unsafe_delete_candidate_count: {summary['unsafe_delete_candidate_count']}
- source_isolation_pass: {summary['source_isolation_pass']}
- ready_for_v20_delete_commit: {summary['ready_for_v20_delete_commit']}
- recommended_next_stage: {summary['recommended_next_stage']}

This stage was deletion dry-run only. It did not delete, move, archive, copy, or
modify any source or output file. A candidate is not deletion-ready unless its
specific original path has a validated archive copy.
"""


def run_delete_candidate_dry_run(
    root: Path,
    mutation_hook: Callable[[], None] | None = None,
) -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
    root = root.resolve()
    migration = root / "outputs/v21/migration"
    read_center = root / "outputs/v21/read_center"
    commit = read_first(migration / COMMIT_SUMMARY)
    copy_rows, _ = read_csv(migration / COPY_LOG)
    hash_rows, _ = read_csv(migration / HASH_MANIFEST)
    package_rows, _ = read_csv(migration / PACKAGE_MANIFEST)
    commit_audit, _ = read_csv(migration / COMMIT_AUDIT)
    commit_keep, _ = read_csv(migration / COMMIT_KEEP_VALIDATION)
    commit_protected, _ = read_csv(migration / COMMIT_PROTECTED_VALIDATION)
    queue_rows, _ = read_csv(migration / DELETE_QUEUE)
    keep_rows, _ = read_csv(migration / KEEP_MANIFEST)
    protected_rows, _ = read_csv(migration / PROTECTED_MANIFEST)
    isolation_summary = read_first(migration / ISOLATION_SUMMARY)
    required = [
        migration / name for name in (
            COMMIT_SUMMARY, COPY_LOG, HASH_MANIFEST, PACKAGE_MANIFEST,
            COMMIT_AUDIT, COMMIT_KEEP_VALIDATION, COMMIT_PROTECTED_VALIDATION,
            DELETE_QUEUE, KEEP_MANIFEST, PROTECTED_MANIFEST, ISOLATION_SUMMARY,
        )
    ]
    inputs_valid = (
        all(path.exists() for path in required)
        and validate_commit(commit)
        and bool(queue_rows)
        and bool(copy_rows)
        and bool(hash_rows)
        and bool(package_rows)
        and bool(commit_keep)
        and bool(commit_protected)
        and not any(clean(row.get("status")).upper() == "BLOCK" for row in commit_audit)
        and as_bool(isolation_summary.get("source_isolation_pass"))
    )

    before_files = {rel(root, path) for path in root.rglob("*") if path.is_file()}
    before_sources = snapshot(root, source_files(root))
    before_v20 = snapshot(root, files_under(root / "outputs/v20"))
    before_v21 = snapshot(root, v21_current_files(root))
    before_protected = snapshot(root, protected_files(root))

    queue_paths = [clean(row.get("file_path")).replace("\\", "/") for row in queue_rows]
    keep_paths = {clean(row.get("file_path")).replace("\\", "/") for row in keep_rows}
    protected_paths = {clean(row.get("file_path")).replace("\\", "/") for row in protected_rows}
    hash_map = {clean(row.get("source_path")).replace("\\", "/"): row for row in hash_rows}
    active_map, reads_scripts, reads_outputs, reads_stale = scan_active_dependencies(root, set(queue_paths))
    source_isolation = not (reads_scripts or reads_outputs or reads_stale)

    manifest: list[dict[str, object]] = []
    archive_validation: list[dict[str, object]] = []
    overlap_audit: list[dict[str, object]] = []
    active_audit: list[dict[str, object]] = []
    for queue_row, rpath in zip(queue_rows, queue_paths):
        source = root / rpath
        hash_row = hash_map.get(rpath, {})
        archive_rel = clean(hash_row.get("archive_path"))
        if not archive_rel:
            archive_rel = f"{clean(commit.get('archive_root')).rstrip('/')}/{rpath}"
        archive = root / archive_rel
        source_exists = source.is_file()
        archive_exists = archive.is_file()
        source_hash = file_hash(source) if source_exists else ""
        archive_hash = file_hash(archive) if archive_exists else ""
        hash_match = source_exists and archive_exists and source_hash == archive_hash
        listed_hash_match = clean(hash_row.get("hash_match")).upper() == "TRUE"
        archive_ok = hash_match and listed_hash_match
        validation_status = (
            "PASS" if archive_ok
            else "SOURCE_MISSING" if not source_exists
            else "ARCHIVE_COPY_MISSING" if not archive_exists or not hash_row
            else "HASH_MISMATCH"
        )
        keep_overlap = rpath in keep_paths
        protected_overlap = rpath in protected_paths
        active_refs = active_map.get(rpath, [])
        active_overlap = bool(active_refs)
        safe = archive_ok and not keep_overlap and not protected_overlap and not active_overlap
        reasons = []
        if not archive_ok:
            reasons.append(f"archive validation: {validation_status}")
        if keep_overlap:
            reasons.append("overlaps keep/reference manifest")
        if protected_overlap:
            reasons.append("overlaps protected manifest")
        if active_overlap:
            reasons.append("referenced by active/current V21")
        reason = "Validated archive copy; no safety overlap." if safe else "; ".join(reasons)
        manifest.append({
            "file_path": rpath,
            "size_mb": clean(queue_row.get("size_mb")) or (
                round(source.stat().st_size / (1024 * 1024), 6) if source_exists else 0
            ),
            "source_hash": source_hash,
            "archive_path": archive_rel,
            "archive_hash": archive_hash,
            "archive_validation_status": validation_status,
            "keep_overlap": tf(keep_overlap),
            "protected_overlap": tf(protected_overlap),
            "active_v21_dependency_overlap": tf(active_overlap),
            "deletion_candidate_status": "SAFE_DELETE_CANDIDATE_DRY_RUN_ONLY" if safe else "UNSAFE_NOT_DELETE_CANDIDATE",
            "risk_level": "LOW" if safe else "CRITICAL",
            "reason": reason,
        })
        archive_validation.append({
            "file_path": rpath, "archive_path": archive_rel,
            "source_exists": tf(source_exists), "archive_exists": tf(archive_exists),
            "source_hash": source_hash, "archive_hash": archive_hash,
            "hash_match": tf(hash_match), "validation_status": validation_status,
        })
        overlap_audit.append({
            "file_path": rpath, "keep_overlap": tf(keep_overlap),
            "protected_overlap": tf(protected_overlap),
            "overlap_status": "BLOCK" if keep_overlap or protected_overlap else "PASS",
            "reason": "Keep/protected overlap detected." if keep_overlap or protected_overlap else "No keep/protected overlap.",
        })
        active_audit.append({
            "file_path": rpath,
            "active_dependency_overlap": tf(active_overlap),
            "referencing_files": "|".join(sorted({item[0] for item in active_refs})),
            "dependency_type": "|".join(sorted({item[1] for item in active_refs})),
            "status": "BLOCK" if active_overlap else "PASS",
        })

    if mutation_hook:
        mutation_hook()

    after_files = {rel(root, path) for path in root.rglob("*") if path.is_file()}
    deleted_or_moved = bool(before_files - after_files)
    unexpected_new = {
        path for path in after_files - before_files
        if Path(path).name not in OUTPUT_NAMES
    }
    source_changes = changed(before_sources, snapshot(root, source_files(root)))
    v20_changes = changed(before_v20, snapshot(root, files_under(root / "outputs/v20")))
    v21_changes = changed(before_v21, snapshot(root, v21_current_files(root)))
    protected_changes = changed(before_protected, snapshot(root, protected_files(root)))

    validated_count = sum(1 for row in manifest if row["archive_validation_status"] == "PASS")
    missing_count = sum(1 for row in manifest if row["archive_validation_status"] in {"SOURCE_MISSING", "ARCHIVE_COPY_MISSING"})
    mismatch_count = sum(1 for row in manifest if row["archive_validation_status"] == "HASH_MISMATCH")
    keep_overlap_count = sum(1 for row in manifest if row["keep_overlap"] == "TRUE")
    protected_overlap_count = sum(1 for row in manifest if row["protected_overlap"] == "TRUE")
    active_overlap_count = sum(1 for row in manifest if row["active_v21_dependency_overlap"] == "TRUE")
    safe_rows = [row for row in manifest if row["deletion_candidate_status"] == "SAFE_DELETE_CANDIDATE_DRY_RUN_ONLY"]
    unsafe_count = len(manifest) - len(safe_rows)
    estimated_size = round(sum(float(row["size_mb"]) for row in safe_rows), 6)
    ready = (
        inputs_valid and len(safe_rows) > 0 and unsafe_count == 0
        and validated_count == len(manifest) and missing_count == 0 and mismatch_count == 0
        and keep_overlap_count == 0 and protected_overlap_count == 0
        and active_overlap_count == 0 and source_isolation
        and not deleted_or_moved and not unexpected_new and not source_changes
        and not v20_changes and not v21_changes and not protected_changes
    )

    if not inputs_valid:
        final_status = BLOCKED_INPUT
        decision = "BLOCK_SOURCE_INPUT_MISSING_OR_INVALID"
    elif missing_count or mismatch_count or validated_count != len(manifest):
        final_status = BLOCKED_ARCHIVE
        decision = "BLOCK_ARCHIVE_VALIDATION_FAILED"
    elif keep_overlap_count or protected_overlap_count:
        final_status = BLOCKED_OVERLAP
        decision = "BLOCK_KEEP_OR_PROTECTED_OVERLAP"
    elif active_overlap_count:
        final_status = BLOCKED_ACTIVE
        decision = "BLOCK_ACTIVE_V21_DEPENDENCY_FOUND"
    elif not source_isolation:
        final_status = BLOCKED_ISOLATION
        decision = "BLOCK_SOURCE_ISOLATION_REGRESSED"
    elif ready:
        final_status = PASS_STATUS
        decision = "DELETE_CANDIDATE_DRY_RUN_READY"
    else:
        final_status = PARTIAL_STATUS
        decision = "DELETE_CANDIDATE_DRY_RUN_READY_WITH_REVIEW"

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

    risk_audit = [
        {"risk_id": "SOURCE_INPUT", "status": "PASS" if inputs_valid else "BLOCK", "severity": "CRITICAL", "count": 0 if inputs_valid else 1, "details": "Archive commit readiness and manifests.", "mitigation": "Repair archive commit evidence."},
        {"risk_id": "ARCHIVE_MISSING", "status": "PASS" if missing_count == 0 else "BLOCK", "severity": "CRITICAL", "count": missing_count, "details": "Candidates without validated archive targets.", "mitigation": "Archive and hash-validate each candidate before deletion planning."},
        {"risk_id": "ARCHIVE_HASH", "status": "PASS" if mismatch_count == 0 else "BLOCK", "severity": "CRITICAL", "count": mismatch_count, "details": "Candidate archive hash mismatches.", "mitigation": "Repair archive copy and regenerate hash manifest."},
        {"risk_id": "KEEP_PROTECTED_OVERLAP", "status": "PASS" if keep_overlap_count + protected_overlap_count == 0 else "BLOCK", "severity": "CRITICAL", "count": keep_overlap_count + protected_overlap_count, "details": "Keep/protected overlap count.", "mitigation": "Remove overlapped paths from deletion queue."},
        {"risk_id": "ACTIVE_DEPENDENCY", "status": "PASS" if active_overlap_count == 0 else "BLOCK", "severity": "CRITICAL", "count": active_overlap_count, "details": "Active V21 dependency overlaps.", "mitigation": "Remove active dependency before deletion planning."},
        {"risk_id": "SOURCE_ISOLATION", "status": "PASS" if source_isolation else "BLOCK", "severity": "CRITICAL", "count": 0 if source_isolation else 1, "details": "Lightweight source isolation recheck.", "mitigation": "Repair source isolation regression."},
        {"risk_id": "MUTATION", "status": "PASS" if not (deleted_or_moved or unexpected_new or source_changes or v20_changes or v21_changes or protected_changes) else "BLOCK", "severity": "CRITICAL", "count": len(source_changes) + len(v20_changes) + len(v21_changes) + len(protected_changes), "details": "No mutation allowed in dry-run.", "mitigation": "Restore changed files and rerun."},
    ]

    summary: dict[str, object] = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "source_archive_commit_status": clean(commit.get("final_status")) or "NOT_AVAILABLE",
        "source_ready_for_v20_delete_candidate_dry_run": clean(commit.get("ready_for_v20_delete_candidate_dry_run")) or "FALSE",
        "archive_root": clean(commit.get("archive_root")),
        "archive_copy_success_count": clean(commit.get("archive_copy_success_count")) or "0",
        "archive_hash_mismatch_count": clean(commit.get("archive_hash_mismatch_count")) or "0",
        "missing_archive_copy_count": clean(commit.get("missing_archive_copy_count")) or "0",
        "source_isolation_pass_after_archive": clean(commit.get("source_isolation_pass_after_archive")) or "FALSE",
        "candidate_queue_count": len(queue_rows),
        "deletion_candidate_count": len(safe_rows),
        "archive_validated_deletion_candidate_count": validated_count,
        "missing_archive_for_deletion_candidate_count": missing_count,
        "hash_mismatch_for_deletion_candidate_count": mismatch_count,
        "keep_reference_overlap_count": keep_overlap_count,
        "protected_overlap_count": protected_overlap_count,
        "active_v21_dependency_overlap_count": active_overlap_count,
        "unsafe_delete_candidate_count": unsafe_count,
        "estimated_delete_size_mb": estimated_size,
        "deletion_dry_run_only": "TRUE",
        "deletion_allowed": "FALSE",
        "archive_allowed": "FALSE",
        "migration_allowed": "FALSE",
        "files_deleted_or_moved": tf(deleted_or_moved),
        "files_archived": "FALSE",
        "files_copied": tf(bool(unexpected_new)),
        "source_files_mutated": tf(bool(source_changes)),
        "v20_outputs_mutated": tf(bool(v20_changes)),
        "v21_current_outputs_mutated": tf(bool(v21_changes)),
        "protected_outputs_mutated": tf(bool(protected_changes)),
        "protected_output_mutation_count": len(protected_changes),
        "v21_active_current_reads_v20_scripts": tf(reads_scripts),
        "v21_active_current_reads_v20_outputs": tf(reads_outputs),
        "v21_active_current_reads_v20_8_to_v20_16_stale_downstream": tf(reads_stale),
        "source_isolation_pass": tf(source_isolation),
        "ready_for_v20_delete_commit": tf(ready),
        **permissions,
        "research_only": "TRUE",
        "recommended_next_stage": "V20_DELETE_COMMIT" if ready else "V20_DELETE_CANDIDATE_ARCHIVE_GAP_REPAIR",
        "created_at_utc": utc_now(),
    }

    write_csv(migration / "V20_DELETE_CANDIDATE_DRY_RUN_SUMMARY.csv", [summary], SUMMARY_FIELDS)
    write_csv(migration / "V20_DELETE_CANDIDATE_DRY_RUN_MANIFEST.csv", manifest, MANIFEST_FIELDS)
    write_csv(migration / "V20_DELETE_CANDIDATE_ARCHIVE_COPY_VALIDATION.csv", archive_validation, ARCHIVE_VALIDATION_FIELDS)
    write_csv(migration / "V20_DELETE_CANDIDATE_KEEP_PROTECTED_OVERLAP_AUDIT.csv", overlap_audit, OVERLAP_FIELDS)
    write_csv(migration / "V20_DELETE_CANDIDATE_ACTIVE_DEPENDENCY_AUDIT.csv", active_audit, ACTIVE_FIELDS)
    write_csv(migration / "V20_DELETE_CANDIDATE_RISK_AUDIT.csv", risk_audit, RISK_FIELDS)
    read_center.mkdir(parents=True, exist_ok=True)
    (read_center / "V20_DELETE_CANDIDATE_DRY_RUN_REPORT.md").write_text(render_report(summary), encoding="utf-8")
    return summary, {
        "manifest": manifest, "archive_validation": archive_validation,
        "overlap": overlap_audit, "active": active_audit, "risks": risk_audit,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    summary, _ = run_delete_candidate_dry_run(args.root)
    for field in SUMMARY_FIELDS:
        print(f"{field.upper()}={summary.get(field, '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
