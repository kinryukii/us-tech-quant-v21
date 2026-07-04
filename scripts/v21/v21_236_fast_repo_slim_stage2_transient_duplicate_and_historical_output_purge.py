#!/usr/bin/env python
"""V21.236 fast repo slim stage 2.

Deletes only verified-safe repo files. External archive/cache/quarantine roots
are never deleted from; archive-root is written only for verified archive-move
copies in this stage.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


STAGE = "V21.236_FAST_REPO_SLIM_STAGE2_TRANSIENT_DUPLICATE_AND_HISTORICAL_OUTPUT_PURGE"
OUT_REL = Path("outputs/v21") / STAGE
ARCHIVE_STAGE = "V21.236_FAST_REPO_SLIM_STAGE2"
PASS_STATUS = "PASS_V21_236_FAST_REPO_SLIM_STAGE2_TARGET_MET"
WARN_STATUS = "WARN_V21_236_FAST_REPO_SLIM_STAGE2_DONE_TARGET_NOT_MET"
FAIL_STATUS = "FAIL_V21_236_FAST_REPO_SLIM_STAGE2_ERROR"
DECISION = "FAST_REPO_SLIM_STAGE2_COMPLETE_REVIEW_BLOCKERS"
TRANSIENT_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".ipynb_checkpoints", ".hypothesis", "htmlcov"}
TRANSIENT_SUFFIXES = {".pyc", ".pyo", ".tmp", ".temp", ".bak", ".orig"}
TRANSIENT_NAMES = {".coverage", "Thumbs.db", "desktop.ini", ".DS_Store"}
HIST_EXTS = {".csv", ".json", ".txt", ".parquet", ".feather", ".pkl", ".pickle", ".xlsx", ".html", ".log"}
PROTECTED_DIR_PREFIXES = (
    "outputs/v21/V21.197", "outputs/v21/V21.198", "outputs/v21/V21.199", "outputs/v21/V21.201",
    "outputs/v21/V21.223", "outputs/v21/V21.231", "outputs/v21/V21.232", "outputs/v21/V21.233",
    "outputs/v21/V21.234", "outputs/v21/V21.235", "outputs/v21/V21.236",
)


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


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return path.as_posix().replace("\\", "/")


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def iter_repo_files(root: Path) -> list[Path]:
    skip = {".git", ".venv", ".venv_moomoo_py312"}
    files: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in skip for part in p.parts):
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
    rows = []
    for p in iter_repo_files(root):
        try:
            rows.append({"path": str(p), "relative_path": rel(p, root), "size_bytes": p.stat().st_size, "size_mb": round(p.stat().st_size / 1024 / 1024, 3)})
        except OSError:
            pass
    return sorted(rows, key=lambda r: int(r["size_bytes"]), reverse=True)[:n]


def is_recent(path: Path, cutoff_seconds: int = 48 * 3600) -> bool:
    try:
        return time.time() - path.stat().st_mtime < cutoff_seconds
    except OSError:
        return True


def is_transient(path: Path) -> bool:
    name = path.name
    parts = set(path.parts)
    return (
        bool(parts & TRANSIENT_DIRS)
        or path.suffix.lower() in TRANSIENT_SUFFIXES
        or name in TRANSIENT_NAMES
        or name.endswith("~")
        or name.startswith(".coverage.")
    )


def protected_reason(path: Path, repo_root: Path) -> str:
    r = rel(path, repo_root)
    rl = r.lower()
    if rl.startswith(".git/") or rl.startswith(".venv/") or rl.startswith(".venv_moomoo_py312/"):
        return "PROTECTED_ENV_OR_GIT"
    if rl.startswith("scripts/") and not is_transient(path):
        return "SOURCE_CODE_PROTECTED"
    if rl.startswith("config/v21/"):
        return "ACTIVE_POLICY_CONFIG_PROTECTED"
    for prefix in PROTECTED_DIR_PREFIXES:
        if r.startswith(prefix):
            return "ACTIVE_OR_LATEST_OUTPUT_PROTECTED"
    if is_recent(path):
        return "MODIFIED_WITHIN_LAST_48_HOURS"
    if "protected" in rl or "active_chain" in rl or "paused_review" in rl or "user_review" in rl:
        return "EXPLICIT_PROTECTED_MARKER"
    return ""


def trusted_external_roots(archive_root: Path, cache_root: Path) -> list[Path]:
    return [archive_root, cache_root]


def build_external_size_index(roots: list[Path]) -> dict[int, list[Path]]:
    index: dict[int, list[Path]] = {}
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.is_file():
                try:
                    index.setdefault(p.stat().st_size, []).append(p)
                except OSError:
                    pass
    return index


def find_verified_duplicate(path: Path, index: dict[int, list[Path]]) -> tuple[Path | None, str]:
    try:
        size = path.stat().st_size
        src_hash = sha256_file(path)
    except OSError:
        return None, ""
    for other in index.get(size, []):
        try:
            if sha256_file(other) == src_hash:
                return other, src_hash
        except OSError:
            continue
    return None, src_hash


def delete_file(path: Path, execute: bool) -> tuple[bool, str]:
    if not execute:
        return False, "dry-run"
    try:
        path.unlink()
        return True, ""
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def copy_verify_then_delete(src: Path, dst: Path, execute: bool) -> tuple[bool, str, str]:
    try:
        src_hash = sha256_file(src)
        if not execute:
            return False, src_hash, "dry-run"
        if execute:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        if not dst.exists():
            return False, src_hash, "archive copy missing after copy"
        if dst.stat().st_size != src.stat().st_size:
            return False, src_hash, "archive copy size mismatch"
        if sha256_file(dst) != src_hash:
            return False, src_hash, "archive copy sha256 mismatch"
        if execute:
            src.unlink()
        return True, src_hash, ""
    except Exception as exc:
        return False, "", f"{type(exc).__name__}: {exc}"


def add_skip(skipped: list[dict[str, Any]], path: Path, repo_root: Path, reason: str) -> None:
    size = path.stat().st_size if path.exists() and path.is_file() else 0
    skipped.append({"path": str(path), "relative_path": rel(path, repo_root), "size_bytes": size, "blocker_type": reason, "notes": "skipped conservatively"})


def phase_transient(files: list[Path], repo_root: Path, execute: bool, allowed: bool, skipped: list[dict[str, Any]], errors: list[str]) -> list[dict[str, Any]]:
    rows = []
    if not allowed:
        return rows
    for p in files:
        if not is_transient(p):
            continue
        reason = protected_reason(p, repo_root)
        if reason and reason != "MODIFIED_WITHIN_LAST_48_HOURS":
            add_skip(skipped, p, repo_root, reason)
            continue
        size = p.stat().st_size
        digest = sha256_file(p)
        deleted, err = delete_file(p, execute)
        if err and err != "dry-run":
            errors.append(err)
        rows.append({"path": str(p), "relative_path": rel(p, repo_root), "size_bytes": size, "sha256": digest, "deleted": deleted, "dry_run": not execute, "error": err})
    return rows


def phase_duplicates(files: list[Path], repo_root: Path, archive_root: Path, cache_root: Path, quarantine_root: Path, execute: bool, allowed: bool, skipped: list[dict[str, Any]], errors: list[str]) -> list[dict[str, Any]]:
    rows = []
    if not allowed:
        return rows
    index = build_external_size_index(trusted_external_roots(archive_root, cache_root))
    for p in files:
        if not p.exists() or not p.is_file() or is_transient(p):
            continue
        reason = protected_reason(p, repo_root)
        if reason:
            add_skip(skipped, p, repo_root, reason)
            continue
        dup, digest = find_verified_duplicate(p, index)
        if dup is None:
            if is_within(p, quarantine_root):
                add_skip(skipped, p, repo_root, "QUARANTINE_NOT_TRUSTED")
            continue
        size = p.stat().st_size
        deleted, err = delete_file(p, execute)
        if err and err != "dry-run":
            errors.append(err)
        rows.append({"path": str(p), "relative_path": rel(p, repo_root), "size_bytes": size, "sha256": digest, "verified_duplicate_path": str(dup), "deleted": deleted, "dry_run": not execute, "error": err})
    return rows


def historical_candidate(path: Path, repo_root: Path) -> bool:
    r = rel(path, repo_root)
    if not (r.startswith("outputs/v21/") or r.startswith("reports/") or r.startswith("artifacts/") or r.startswith("temp") or r.startswith("tmp")):
        return False
    try:
        return path.suffix.lower() in HIST_EXTS and path.stat().st_size > 5 * 1024 * 1024
    except OSError:
        return False


def phase_archive_move(files: list[Path], repo_root: Path, archive_root: Path, execute: bool, allowed: bool, skipped: list[dict[str, Any]], errors: list[str]) -> list[dict[str, Any]]:
    rows = []
    if not allowed:
        return rows
    stage_root = archive_root / ARCHIVE_STAGE
    for p in files:
        if not p.exists() or not p.is_file() or not historical_candidate(p, repo_root):
            continue
        reason = protected_reason(p, repo_root)
        if reason:
            add_skip(skipped, p, repo_root, reason)
            continue
        dst = stage_root / rel(p, repo_root)
        size = p.stat().st_size
        ok, digest, err = copy_verify_then_delete(p, dst, execute)
        if err and err != "dry-run":
            errors.append(err)
        rows.append({"source_path": str(p), "relative_path": rel(p, repo_root), "archive_path": str(dst), "size_bytes": size, "sha256": digest, "copy_verified": ok, "source_deleted": ok and execute, "dry_run": not execute, "error": err})
    return rows


def remove_empty_dirs(repo_root: Path, execute: bool) -> int:
    if not execute:
        return 0
    deleted = 0
    for d in sorted([p for p in repo_root.rglob("*") if p.is_dir()], key=lambda p: len(p.parts), reverse=True):
        if any(part in {".git", ".venv", ".venv_moomoo_py312"} for part in d.parts):
            continue
        if protected_reason(d, repo_root):
            continue
        try:
            if not any(d.iterdir()):
                d.rmdir()
                deleted += 1
        except OSError:
            pass
    return deleted


def run(
    repo_root: Path,
    archive_root: Path,
    cache_root: Path,
    quarantine_root: Path,
    output_dir: Path,
    execute: bool,
    min_target_mb: float,
    top_size_count: int,
    allow_transient_delete: bool,
    allow_verified_duplicate_delete: bool,
    allow_archive_move: bool,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    archive_root = archive_root.resolve()
    cache_root = cache_root.resolve()
    quarantine_root = quarantine_root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    before_bytes, before_count = repo_stats(repo_root)
    top_before_rows = top_size(repo_root, top_size_count)
    files = iter_repo_files(repo_root)
    skipped: list[dict[str, Any]] = []
    errors: list[str] = []
    transient = phase_transient(files, repo_root, execute, allow_transient_delete, skipped, errors)
    files = iter_repo_files(repo_root)
    duplicates = phase_duplicates(files, repo_root, archive_root, cache_root, quarantine_root, execute, allow_verified_duplicate_delete, skipped, errors)
    files = iter_repo_files(repo_root)
    moved = phase_archive_move(files, repo_root, archive_root, execute, allow_archive_move, skipped, errors)
    empty_dirs = remove_empty_dirs(repo_root, execute)
    after_bytes, after_count = repo_stats(repo_root)
    top_after_rows = top_size(repo_root, top_size_count)
    write_csv(output_dir / "v21_236_top_size_before.csv", top_before_rows, ["path", "relative_path", "size_bytes", "size_mb"])
    write_csv(output_dir / "v21_236_top_size_after.csv", top_after_rows, ["path", "relative_path", "size_bytes", "size_mb"])
    write_csv(output_dir / "v21_236_deleted_transient_manifest.csv", transient, ["path", "relative_path", "size_bytes", "sha256", "deleted", "dry_run", "error"])
    write_csv(output_dir / "v21_236_deleted_verified_duplicates_manifest.csv", duplicates, ["path", "relative_path", "size_bytes", "sha256", "verified_duplicate_path", "deleted", "dry_run", "error"])
    write_csv(output_dir / "v21_236_archived_moved_manifest.csv", moved, ["source_path", "relative_path", "archive_path", "size_bytes", "sha256", "copy_verified", "source_deleted", "dry_run", "error"])
    write_csv(output_dir / "v21_236_skipped_blockers.csv", skipped, ["path", "relative_path", "size_bytes", "blocker_type", "notes"])
    reduced = before_bytes - after_bytes
    target_met = reduced >= min_target_mb * 1024 * 1024
    error_count = len(errors)
    final_status = FAIL_STATUS if error_count else PASS_STATUS if target_met else WARN_STATUS
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
        "transient_deleted_count": sum(1 for r in transient if r["deleted"]),
        "transient_deleted_bytes": sum(int(r["size_bytes"]) for r in transient if r["deleted"]),
        "verified_duplicate_deleted_count": sum(1 for r in duplicates if r["deleted"]),
        "verified_duplicate_deleted_bytes": sum(int(r["size_bytes"]) for r in duplicates if r["deleted"]),
        "archive_moved_count": sum(1 for r in moved if r["source_deleted"]),
        "archive_moved_bytes": sum(int(r["size_bytes"]) for r in moved if r["source_deleted"]),
        "skipped_count": len(skipped),
        "protected_skipped_count": sum(1 for r in skipped if "PROTECTED" in r["blocker_type"]),
        "active_chain_skipped_count": sum(1 for r in skipped if "ACTIVE" in r["blocker_type"] or "SOURCE_CODE" in r["blocker_type"]),
        "recent_file_skipped_count": sum(1 for r in skipped if "48_HOURS" in r["blocker_type"]),
        "error_count": error_count,
        "warning_count": len(skipped),
        "min_target_mb": min_target_mb,
        "target_met": target_met,
        "protected_outputs_modified": False,
        "external_archive_deleted": False,
        "external_cache_deleted": False,
        "external_quarantine_deleted": False,
        "market_data_fetch_performed": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
    }
    write_json(output_dir / "v21_236_summary.json", summary)
    report = "\n".join([
        STAGE,
        f"final_status={final_status}",
        f"final_decision={DECISION}",
        f"repo_size_reduced_mb={summary['repo_size_reduced_mb']}",
        f"repo_file_count_reduced={summary['repo_file_count_reduced']}",
        f"transient_deleted_count={summary['transient_deleted_count']}",
        f"verified_duplicate_deleted_count={summary['verified_duplicate_deleted_count']}",
        f"archive_moved_count={summary['archive_moved_count']}",
        "market_data_fetch_performed=False",
        "broker_action_allowed=False",
        "official_adoption_allowed=False",
    ]) + "\n"
    (output_dir / "V21.236_fast_repo_slim_stage2_report.txt").write_text(report, encoding="utf-8")
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
    parser.add_argument("--min-target-mb", type=float, default=500.0)
    parser.add_argument("--top-size", type=int, default=300)
    parser.add_argument("--allow-transient-delete", action="store_true", default=False)
    parser.add_argument("--allow-verified-duplicate-delete", action="store_true", default=False)
    parser.add_argument("--allow-archive-move", action="store_true", default=False)
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
        allow_transient_delete=args.allow_transient_delete,
        allow_verified_duplicate_delete=args.allow_verified_duplicate_delete,
        allow_archive_move=args.allow_archive_move,
    )
    print(str(out / "v21_236_summary.json"))
    return 1 if summary["final_status"] == FAIL_STATUS else 0


if __name__ == "__main__":
    raise SystemExit(main())
