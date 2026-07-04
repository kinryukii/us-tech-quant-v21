#!/usr/bin/env python
"""V21.237 targeted compressed archive move for known repo size blockers."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


STAGE = "V21.237_RECENT_BLOCKER_REVIEW_AND_COMPRESSED_ARCHIVE_MOVE"
OUT_REL = Path("outputs/v21") / STAGE
ARCHIVE_STAGE = STAGE
PASS_STATUS = "PASS_V21_237_RECENT_BLOCKER_COMPRESSED_ARCHIVE_TARGET_MET"
WARN_STATUS = "WARN_V21_237_RECENT_BLOCKER_COMPRESSED_ARCHIVE_DONE_TARGET_NOT_MET"
FAIL_STATUS = "FAIL_V21_237_RECENT_BLOCKER_COMPRESSED_ARCHIVE_ERROR"
DECISION = "RECENT_BLOCKER_COMPRESSED_ARCHIVE_MOVE_COMPLETE"
AUDIT_DIRS = (
    Path("outputs/v21/V21.229_R1_ACTIVE_DATA_SOURCE_BLOCKER_TRIAGE_AND_ENFORCEMENT"),
    Path("outputs/v21/V21.229_MOOMOO_ONLY_DATA_SOURCE_POLICY_GATE"),
)
BACKUP_DIR = Path("outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/canonical_backups")
MIN_AUDIT_BYTES = 50 * 1024 * 1024
PROTECTED_PARTS = {".git", ".venv", ".venv_moomoo_py312"}


def default_repo_root() -> Path:
    return Path(r"D:\us-tech-quant")


def default_archive_root() -> Path:
    return Path(r"D:\us-tech-quant-archive")


def default_cache_root() -> Path:
    return Path(r"D:\us-tech-quant-cache")


def default_quarantine_root() -> Path:
    return Path(r"D:\us-tech-quant-quarantine")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def gzip_decompressed_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with gzip.open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return path.as_posix().replace("\\", "/")


def iter_repo_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in PROTECTED_PARTS for part in p.parts):
            continue
        files.append(p)
    return files


def repo_stats(root: Path) -> tuple[int, int]:
    total = 0
    count = 0
    for p in iter_repo_files(root):
        try:
            total += p.stat().st_size
            count += 1
        except OSError:
            pass
    return total, count


def top_size(root: Path, n: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for p in iter_repo_files(root):
        try:
            size = p.stat().st_size
        except OSError:
            continue
        rows.append({"path": str(p), "relative_path": rel(p, root), "size_bytes": size, "size_mb": round(size / 1024 / 1024, 3)})
    return sorted(rows, key=lambda r: int(r["size_bytes"]), reverse=True)[:n]


def protected_reason(path: Path, repo_root: Path) -> str:
    r = rel(path, repo_root)
    rl = r.lower()
    if any(part in PROTECTED_PARTS for part in path.parts):
        return "PROTECTED_ENV_OR_GIT"
    if rl.startswith("scripts/"):
        return "SOURCE_CODE_PROTECTED"
    if rl.startswith("config/"):
        return "CONFIG_PROTECTED"
    if "canonical_price" in rl and not r.startswith(BACKUP_DIR.as_posix() + "/"):
        return "ACTIVE_CANONICAL_PRICE_PROTECTED"
    if "pointer" in rl or "registry" in rl:
        return "POINTER_OR_REGISTRY_PROTECTED"
    if r.startswith("outputs/v21/V21.231") or r.startswith("outputs/v21/V21.232") or r.startswith("outputs/v21/V21.233") or r.startswith("outputs/v21/V21.234") or r.startswith("outputs/v21/V21.235") or r.startswith("outputs/v21/V21.236") or r.startswith("outputs/v21/V21.237"):
        return "LATEST_ACTIVE_CHAIN_OUTPUT_PROTECTED"
    return ""


def add_skip(skipped: list[dict[str, Any]], path: Path, repo_root: Path, reason: str, phase: str) -> None:
    size = path.stat().st_size if path.exists() and path.is_file() else 0
    skipped.append({"path": str(path), "relative_path": rel(path, repo_root), "size_bytes": size, "blocker_type": reason, "phase": phase, "notes": "skipped conservatively"})


def is_audit_candidate(path: Path, repo_root: Path) -> bool:
    r = Path(rel(path, repo_root))
    return any(r.parent == d for d in AUDIT_DIRS) and path.suffix.lower() == ".csv" and path.stat().st_size >= MIN_AUDIT_BYTES


def archive_gzip_verify_delete(src: Path, repo_root: Path, archive_root: Path, execute: bool) -> dict[str, Any]:
    source_size = src.stat().st_size
    source_hash = sha256_file(src)
    archive_path = archive_root / ARCHIVE_STAGE / (rel(src, repo_root) + ".gz")
    row: dict[str, Any] = {
        "relative_path": rel(src, repo_root),
        "original_size_bytes": source_size,
        "original_sha256": source_hash,
        "archive_gzip_path": str(archive_path),
        "archive_gzip_size_bytes": 0,
        "archive_gzip_sha256": "",
        "decompressed_sha256_verified": False,
        "deleted_from_repo": False,
        "dry_run": not execute,
        "error": "",
    }
    if not execute:
        return row
    try:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with src.open("rb") as in_handle, gzip.open(archive_path, "wb", compresslevel=6) as out_handle:
            shutil.copyfileobj(in_handle, out_handle, length=1024 * 1024)
        if not archive_path.exists() or archive_path.stat().st_size <= 0:
            row["error"] = "gzip archive missing or empty"
            return row
        row["archive_gzip_size_bytes"] = archive_path.stat().st_size
        row["archive_gzip_sha256"] = sha256_file(archive_path)
        decompressed_hash = gzip_decompressed_sha256(archive_path)
        row["decompressed_sha256_verified"] = decompressed_hash == source_hash
        if not row["decompressed_sha256_verified"]:
            row["error"] = "gzip decompressed sha256 mismatch"
            return row
        src.unlink()
        row["deleted_from_repo"] = True
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
    return row


def phase_recent_audit(repo_root: Path, archive_root: Path, execute: bool, allowed: bool, skipped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not allowed:
        return rows
    for directory in AUDIT_DIRS:
        full_dir = repo_root / directory
        if not full_dir.exists():
            continue
        for p in sorted(full_dir.glob("*.csv")):
            try:
                if not is_audit_candidate(p, repo_root):
                    continue
            except OSError:
                continue
            reason = protected_reason(p, repo_root)
            if reason:
                add_skip(skipped, p, repo_root, reason, "recent_audit")
                continue
            rows.append(archive_gzip_verify_delete(p, repo_root, archive_root, execute))
    return rows


def phase_canonical_backups(repo_root: Path, archive_root: Path, execute: bool, allowed: bool, retain_count: int, skipped: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    moved: list[dict[str, Any]] = []
    retained: list[dict[str, Any]] = []
    if not allowed:
        return moved, retained
    backup_dir = repo_root / BACKUP_DIR
    if not backup_dir.exists():
        return moved, retained
    candidates = sorted(backup_dir.glob("*.csv"), key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    retain = set(candidates[: max(retain_count, 0)])
    for p in candidates:
        size = p.stat().st_size
        if p in retain:
            retained.append({"relative_path": rel(p, repo_root), "size_bytes": size, "last_modified_utc": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(), "retention_reason": "newest_retained_backup"})
            continue
        reason = protected_reason(p, repo_root)
        if reason and reason != "ACTIVE_CANONICAL_PRICE_PROTECTED":
            add_skip(skipped, p, repo_root, reason, "canonical_backup")
            continue
        moved.append(archive_gzip_verify_delete(p, repo_root, archive_root, execute))
    return moved, retained


def pointer_rows(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in groups:
        for row in group:
            if row.get("deleted_from_repo") or row.get("dry_run"):
                rows.append({
                    "relative_path": row["relative_path"],
                    "original_sha256": row["original_sha256"],
                    "original_size_bytes": row["original_size_bytes"],
                    "archive_gzip_path": row["archive_gzip_path"],
                    "archive_gzip_sha256": row["archive_gzip_sha256"],
                    "archive_gzip_size_bytes": row["archive_gzip_size_bytes"],
                })
    return rows


def run(
    repo_root: Path,
    archive_root: Path,
    cache_root: Path,
    quarantine_root: Path,
    output_dir: Path,
    execute: bool,
    min_target_mb: float,
    top_size_count: int,
    allow_recent_audit_csv_archive: bool,
    allow_canonical_backup_prune: bool,
    canonical_backup_retain_count: int,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    archive_root = archive_root.resolve()
    cache_root = cache_root.resolve()
    quarantine_root = quarantine_root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    before_bytes, before_count = repo_stats(repo_root)
    top_before = top_size(repo_root, top_size_count)
    skipped: list[dict[str, Any]] = []
    audit_rows = phase_recent_audit(repo_root, archive_root, execute, allow_recent_audit_csv_archive, skipped)
    backup_rows, retained_rows = phase_canonical_backups(repo_root, archive_root, execute, allow_canonical_backup_prune, canonical_backup_retain_count, skipped)
    after_bytes, after_count = repo_stats(repo_root)
    top_after = top_size(repo_root, top_size_count)

    manifest_fields = ["relative_path", "original_size_bytes", "original_sha256", "archive_gzip_path", "archive_gzip_size_bytes", "archive_gzip_sha256", "decompressed_sha256_verified", "deleted_from_repo", "dry_run", "error"]
    write_csv(output_dir / "v21_237_recent_audit_csv_archived_manifest.csv", audit_rows, manifest_fields)
    write_csv(output_dir / "v21_237_canonical_backup_archived_manifest.csv", backup_rows, manifest_fields)
    write_csv(output_dir / "v21_237_retained_canonical_backups.csv", retained_rows, ["relative_path", "size_bytes", "last_modified_utc", "retention_reason"])
    write_csv(output_dir / "v21_237_skipped_blockers.csv", skipped, ["path", "relative_path", "size_bytes", "blocker_type", "phase", "notes"])
    write_csv(output_dir / "v21_237_top_size_before.csv", top_before, ["path", "relative_path", "size_bytes", "size_mb"])
    write_csv(output_dir / "v21_237_top_size_after.csv", top_after, ["path", "relative_path", "size_bytes", "size_mb"])
    pointers = pointer_rows(audit_rows, backup_rows)
    pointer_payload = {"policy_version": "V21.237", "created_at_utc": utc_now(), "archive_stage_root": str(archive_root / ARCHIVE_STAGE), "pointers": pointers}
    write_json(output_dir / "v21_237_pointer_manifest.json", pointer_payload)

    verification_failed_count = sum(1 for r in audit_rows + backup_rows if r.get("error") or (execute and not r.get("decompressed_sha256_verified")))
    deleted_without_verify = sum(1 for r in audit_rows + backup_rows if r.get("deleted_from_repo") and not r.get("decompressed_sha256_verified"))
    error_count = verification_failed_count + deleted_without_verify
    reduced = before_bytes - after_bytes
    target_met = reduced >= min_target_mb * 1024 * 1024
    final_status = FAIL_STATUS if error_count else PASS_STATUS if target_met else WARN_STATUS
    audit_deleted = [r for r in audit_rows if r.get("deleted_from_repo")]
    backup_deleted = [r for r in backup_rows if r.get("deleted_from_repo")]
    original_removed = sum(int(r["original_size_bytes"]) for r in audit_deleted + backup_deleted)
    gzip_added = sum(int(r["archive_gzip_size_bytes"]) for r in audit_deleted + backup_deleted)
    summary = {
        "final_status": final_status,
        "final_decision": DECISION,
        "repo_root": str(repo_root),
        "archive_root": str(archive_root),
        "cache_root": str(cache_root),
        "quarantine_root": str(quarantine_root),
        "execute_mode": execute,
        "repo_size_before_bytes": before_bytes,
        "repo_size_after_bytes": after_bytes,
        "repo_size_reduced_bytes": reduced,
        "repo_size_reduced_mb": round(reduced / 1024 / 1024, 3),
        "repo_file_count_before": before_count,
        "repo_file_count_after": after_count,
        "repo_file_count_reduced": before_count - after_count,
        "recent_audit_csv_archived_count": len(audit_deleted),
        "recent_audit_csv_archived_original_bytes": sum(int(r["original_size_bytes"]) for r in audit_deleted),
        "recent_audit_csv_archive_gzip_bytes": sum(int(r["archive_gzip_size_bytes"]) for r in audit_deleted),
        "canonical_backup_archived_count": len(backup_deleted),
        "canonical_backup_archived_original_bytes": sum(int(r["original_size_bytes"]) for r in backup_deleted),
        "canonical_backup_archive_gzip_bytes": sum(int(r["archive_gzip_size_bytes"]) for r in backup_deleted),
        "canonical_backup_retained_count": len(retained_rows),
        "total_original_bytes_removed_from_repo": original_removed,
        "total_gzip_bytes_added_to_archive": gzip_added,
        "estimated_net_disk_reduction_bytes": original_removed - gzip_added,
        "estimated_net_disk_reduction_mb": round((original_removed - gzip_added) / 1024 / 1024, 3),
        "skipped_count": len(skipped),
        "protected_skipped_count": sum(1 for r in skipped if "PROTECTED" in r["blocker_type"]),
        "active_chain_skipped_count": sum(1 for r in skipped if "ACTIVE" in r["blocker_type"]),
        "verification_failed_count": verification_failed_count,
        "error_count": error_count,
        "warning_count": len(skipped),
        "min_target_mb": min_target_mb,
        "target_met": target_met,
        "protected_outputs_modified": False,
        "canonical_active_file_modified": False,
        "external_archive_deleted": False,
        "external_cache_deleted": False,
        "external_quarantine_deleted": False,
        "market_data_fetch_performed": False,
        "yahoo_yfinance_used": False,
        "moomoo_futu_used": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
    }
    write_json(output_dir / "v21_237_summary.json", summary)
    report = "\n".join([
        STAGE,
        f"final_status={final_status}",
        f"final_decision={DECISION}",
        f"repo_size_reduced_mb={summary['repo_size_reduced_mb']}",
        f"recent_audit_csv_archived_count={summary['recent_audit_csv_archived_count']}",
        f"canonical_backup_archived_count={summary['canonical_backup_archived_count']}",
        f"estimated_net_disk_reduction_mb={summary['estimated_net_disk_reduction_mb']}",
        "market_data_fetch_performed=False",
        "broker_action_allowed=False",
        "official_adoption_allowed=False",
    ]) + "\n"
    (output_dir / "V21.237_recent_blocker_review_and_compressed_archive_move_report.txt").write_text(report, encoding="utf-8")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", type=Path, default=default_repo_root())
    parser.add_argument("--archive-root", type=Path, default=default_archive_root())
    parser.add_argument("--cache-root", type=Path, default=default_cache_root())
    parser.add_argument("--quarantine-root", type=Path, default=default_quarantine_root())
    parser.add_argument("--output-dir", type=Path, default=None)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", default=False)
    mode.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--min-target-mb", type=float, default=400.0)
    parser.add_argument("--top-size", type=int, default=300)
    parser.add_argument("--allow-recent-audit-csv-archive", action="store_true", default=False)
    parser.add_argument("--allow-canonical-backup-prune", action="store_true", default=False)
    parser.add_argument("--canonical-backup-retain-count", type=int, default=2)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    out = args.output_dir or (repo_root / OUT_REL)
    summary = run(
        repo_root=repo_root,
        archive_root=args.archive_root,
        cache_root=args.cache_root,
        quarantine_root=args.quarantine_root,
        output_dir=out,
        execute=args.execute and not args.dry_run,
        min_target_mb=args.min_target_mb,
        top_size_count=args.top_size,
        allow_recent_audit_csv_archive=args.allow_recent_audit_csv_archive,
        allow_canonical_backup_prune=args.allow_canonical_backup_prune,
        canonical_backup_retain_count=args.canonical_backup_retain_count,
    )
    print(str(out / "v21_237_summary.json"))
    return 1 if summary["final_status"] == FAIL_STATUS else 0


if __name__ == "__main__":
    raise SystemExit(main())
