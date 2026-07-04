#!/usr/bin/env python
"""V21.239 total disk footprint governance across repo/archive/cache/quarantine."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


STAGE = "V21.239_TOTAL_DISK_FOOTPRINT_GOVERNANCE"
OUT_REL = Path("outputs/v21") / STAGE
PASS_STATUS = "PASS_V21_239_TOTAL_DISK_FOOTPRINT_TARGET_MET"
WARN_STATUS = "WARN_V21_239_TOTAL_DISK_FOOTPRINT_DONE_TARGET_NOT_MET"
FAIL_STATUS = "FAIL_V21_239_TOTAL_DISK_FOOTPRINT_ERROR"
DECISION = "TOTAL_DISK_FOOTPRINT_GOVERNANCE_COMPLETE"
COMPRESS_EXTS = {".csv", ".json", ".txt", ".log", ".html", ".xlsx", ".parquet", ".pkl", ".pickle"}
COMPRESSED_EXTS = {".gz", ".zip", ".7z", ".zst", ".br"}
TRANSIENT_NAMES = {".pytest_cache", "__pycache__", "tmp", "selftest"}
TRANSIENT_SUFFIXES = {".tmp", ".temp", ".bak", ".pyc"}
PROTECTED_REPO_PARTS = {".git", ".venv", ".venv_moomoo_py312"}


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


def safe_iter(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return list(root.rglob("*"))


def file_list(root: Path, protect_repo: bool = False) -> list[Path]:
    files: list[Path] = []
    for p in safe_iter(root):
        if not p.is_file():
            continue
        if protect_repo and any(part in PROTECTED_REPO_PARTS for part in p.parts):
            continue
        files.append(p)
    return files


def footprint(root: Path, name: str, protect_repo: bool = False) -> dict[str, Any]:
    size = 0
    files = 0
    dirs = 0
    for p in safe_iter(root):
        try:
            if p.is_file():
                if protect_repo and any(part in PROTECTED_REPO_PARTS for part in p.parts):
                    continue
                size += p.stat().st_size
                files += 1
            elif p.is_dir():
                dirs += 1
        except OSError:
            continue
    return {"root_name": name, "root_path": str(root), "size_bytes": size, "file_count": files, "dir_count": dirs}


def top_size_for_root(root: Path, name: str, n: int, protect_repo: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for p in file_list(root, protect_repo):
        try:
            size = p.stat().st_size
        except OSError:
            continue
        rows.append({"root_name": name, "path": str(p), "relative_path": rel(p, root), "size_bytes": size, "size_mb": round(size / 1024 / 1024, 3)})
    return sorted(rows, key=lambda r: int(r["size_bytes"]), reverse=True)[:n]


def four_root_rows(repo: Path, archive: Path, cache: Path, quarantine: Path) -> list[dict[str, Any]]:
    return [
        footprint(repo, "repo", True),
        footprint(archive, "archive"),
        footprint(cache, "cache"),
        footprint(quarantine, "quarantine"),
    ]


def totals(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "size": sum(int(r["size_bytes"]) for r in rows),
        "files": sum(int(r["file_count"]) for r in rows),
        "dirs": sum(int(r["dir_count"]) for r in rows),
    }


def is_manifest_like(path: Path) -> bool:
    name = path.name.lower()
    return any(token in name for token in ("manifest", "pointer", "summary", "report", "registry", ".sha256", "policy"))


def is_recent(path: Path, seconds: int) -> bool:
    try:
        return time.time() - path.stat().st_mtime < seconds
    except OSError:
        return True


def archive_compress_candidate(path: Path, archive_root: Path, min_bytes: int) -> tuple[bool, str]:
    if not path.is_file():
        return False, "NOT_FILE"
    if path.suffix.lower() in COMPRESSED_EXTS:
        return False, "ALREADY_COMPRESSED"
    if path.suffix.lower() not in COMPRESS_EXTS:
        return False, "EXTENSION_NOT_TARGETED"
    if path.stat().st_size < min_bytes:
        return False, "BELOW_SIZE_THRESHOLD"
    if is_manifest_like(path):
        return False, "PROTECTED_POINTER_OR_MANIFEST"
    r = rel(path, archive_root)
    if is_recent(path, 24 * 3600) and not r.startswith("V21.236_FAST_REPO_SLIM_STAGE2"):
        return False, "RECENT_FILE"
    return True, ""


def gzip_verify_delete(src: Path, execute: bool) -> dict[str, Any]:
    original_size = src.stat().st_size
    original_hash = sha256_file(src)
    gzip_path = Path(str(src) + ".gz")
    row: dict[str, Any] = {
        "source_path": str(src),
        "original_size_bytes": original_size,
        "original_sha256": original_hash,
        "gzip_path": str(gzip_path),
        "gzip_size_bytes": 0,
        "gzip_sha256": "",
        "decompressed_sha256_verified": False,
        "deleted_original": False,
        "dry_run": not execute,
        "error": "",
    }
    if not execute:
        return row
    try:
        with src.open("rb") as in_handle, gzip.open(gzip_path, "wb", compresslevel=6) as out_handle:
            shutil.copyfileobj(in_handle, out_handle, length=1024 * 1024)
        if not gzip_path.exists() or gzip_path.stat().st_size <= 0:
            row["error"] = "gzip archive missing or empty"
            return row
        row["gzip_size_bytes"] = gzip_path.stat().st_size
        row["gzip_sha256"] = sha256_file(gzip_path)
        row["decompressed_sha256_verified"] = gzip_decompressed_sha256(gzip_path) == original_hash
        if not row["decompressed_sha256_verified"]:
            row["error"] = "gzip decompressed sha256 mismatch"
            return row
        src.unlink()
        row["deleted_original"] = True
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
    return row


def add_skip(skipped: list[dict[str, Any]], root_name: str, path: Path, root: Path, reason: str, phase: str) -> None:
    size = path.stat().st_size if path.exists() and path.is_file() else 0
    skipped.append({"root_name": root_name, "path": str(path), "relative_path": rel(path, root), "size_bytes": size, "blocker_type": reason, "phase": phase, "notes": "skipped conservatively"})


def phase_archive_compress(archive_root: Path, execute: bool, allowed: bool, min_mb: float, skipped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not allowed or not archive_root.exists():
        return rows
    min_bytes = int(min_mb * 1024 * 1024)
    candidates = []
    for p in file_list(archive_root):
        ok, reason = archive_compress_candidate(p, archive_root, min_bytes)
        if ok:
            candidates.append(p)
        elif p.is_file() and p.stat().st_size >= min_bytes and reason not in {"BELOW_SIZE_THRESHOLD", "EXTENSION_NOT_TARGETED", "ALREADY_COMPRESSED"}:
            add_skip(skipped, "archive", p, archive_root, reason, "archive_compress")
    for p in sorted(candidates, key=lambda x: (0 if rel(x, archive_root).startswith("V21.236_FAST_REPO_SLIM_STAGE2") else 1, -x.stat().st_size)):
        rows.append(gzip_verify_delete(p, execute))
    return rows


def load_pointer_text(repo_root: Path, archive_root: Path) -> str:
    chunks: list[str] = []
    for root in (repo_root / "outputs" / "v21", archive_root):
        if not root.exists():
            continue
        for p in root.rglob("*pointer*.json"):
            try:
                if p.stat().st_size <= 20 * 1024 * 1024:
                    chunks.append(p.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
    return "\n".join(chunks)


def duplicate_protected(path: Path) -> bool:
    return is_manifest_like(path) or path.suffix.lower() == ".sha256"


def archive_preference(path: Path, pointer_text: str) -> tuple[int, int, int, int]:
    p = str(path)
    compressed = 0 if path.suffix.lower() == ".gz" else 1
    referenced = 0 if pointer_text and p in pointer_text else 1
    newest = 0 if any(token in p for token in ("V21.239", "V21.238", "V21.237")) else 1
    return (compressed, referenced, newest, len(p))


def phase_archive_duplicates(archive_root: Path, repo_root: Path, execute: bool, allowed: bool, skipped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not allowed or not archive_root.exists():
        return rows
    pointer_text = load_pointer_text(repo_root, archive_root)
    groups: dict[tuple[int, str], list[Path]] = {}
    for p in file_list(archive_root):
        if duplicate_protected(p):
            continue
        try:
            groups.setdefault((p.stat().st_size, sha256_file(p)), []).append(p)
        except OSError:
            continue
    for (_size, digest), paths in groups.items():
        if len(paths) < 2:
            continue
        retain = sorted(paths, key=lambda p: archive_preference(p, pointer_text))[0]
        for p in paths:
            if p == retain:
                continue
            size = p.stat().st_size
            row = {"deleted_path": str(p), "deleted_relative_path": rel(p, archive_root), "retained_path": str(retain), "sha256": digest, "size_bytes": size, "deleted": False, "dry_run": not execute, "error": ""}
            if execute:
                try:
                    p.unlink()
                    row["deleted"] = True
                except Exception as exc:
                    row["error"] = f"{type(exc).__name__}: {exc}"
            rows.append(row)
    return rows


def trusted_index(repo_root: Path, archive_root: Path) -> dict[int, list[Path]]:
    index: dict[int, list[Path]] = {}
    for root, protect in ((repo_root, True), (archive_root, False)):
        for p in file_list(root, protect):
            try:
                index.setdefault(p.stat().st_size, []).append(p)
            except OSError:
                continue
    return index


def find_exact_trusted_copy(path: Path, index: dict[int, list[Path]]) -> tuple[Path | None, str]:
    try:
        size = path.stat().st_size
        digest = sha256_file(path)
    except OSError:
        return None, ""
    for other in index.get(size, []):
        try:
            if other.resolve() != path.resolve() and sha256_file(other) == digest:
                return other, digest
        except OSError:
            continue
    return None, digest


def find_gzip_decompressed_copy(path: Path, archive_root: Path, digest: str) -> Path | None:
    if not archive_root.exists():
        return None
    for gz in archive_root.rglob("*.gz"):
        try:
            if gzip_decompressed_sha256(gz) == digest:
                return gz
        except Exception:
            continue
    return None


def phase_quarantine(quarantine_root: Path, repo_root: Path, archive_root: Path, execute: bool, allowed: bool, retention_days: int, skipped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not allowed or not quarantine_root.exists():
        return rows
    index = trusted_index(repo_root, archive_root)
    for p in file_list(quarantine_root):
        copy_path, digest = find_exact_trusted_copy(p, index)
        trusted_path = copy_path
        trusted_type = "exact_size_sha256"
        if trusted_path is None:
            trusted_path = find_gzip_decompressed_copy(p, archive_root, digest)
            trusted_type = "gzip_decompressed_sha256" if trusted_path else ""
        if trusted_path is None:
            add_skip(skipped, "quarantine", p, quarantine_root, "UNIQUE_QUARANTINE_NO_TRUSTED_COPY", "quarantine_verified_delete")
            continue
        if is_recent(p, retention_days * 24 * 3600) and "quarantine" not in str(p).lower():
            add_skip(skipped, "quarantine", p, quarantine_root, "RECENT_FILE", "quarantine_verified_delete")
            continue
        size = p.stat().st_size
        row = {"path": str(p), "relative_path": rel(p, quarantine_root), "size_bytes": size, "sha256": digest, "trusted_retained_copy_path": str(trusted_path), "trusted_copy_type": trusted_type, "deleted": False, "dry_run": not execute, "error": ""}
        if execute:
            try:
                p.unlink()
                row["deleted"] = True
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
    return rows


def cache_protected(path: Path) -> bool:
    name = path.name.lower()
    return any(token in name for token in ("registry", "pointer", "manifest", "retention", "policy", "index")) or "canonical" in str(path).lower()


def cache_transient(path: Path, cache_root: Path) -> bool:
    r = rel(path, cache_root).lower()
    return r.startswith("tmp/") or r.startswith("selftest/") or any(part in TRANSIENT_NAMES for part in path.parts) or path.suffix.lower() in TRANSIENT_SUFFIXES


def phase_cache(cache_root: Path, execute: bool, allowed: bool, retention_days: int, skipped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not allowed or not cache_root.exists():
        return rows
    for p in file_list(cache_root):
        if cache_protected(p):
            add_skip(skipped, "cache", p, cache_root, "CACHE_ACTIVE_OR_REGISTRY", "cache_retention_delete")
            continue
        if not cache_transient(p, cache_root):
            continue
        if not (rel(p, cache_root).lower().startswith(("tmp/", "selftest/")) or is_recent(p, retention_days * 24 * 3600) is False or path_suffix_transient(p)):
            add_skip(skipped, "cache", p, cache_root, "RECENT_FILE", "cache_retention_delete")
            continue
        size = p.stat().st_size
        digest = sha256_file(p)
        row = {"path": str(p), "relative_path": rel(p, cache_root), "size_bytes": size, "sha256": digest, "deleted": False, "dry_run": not execute, "error": ""}
        if execute:
            try:
                p.unlink()
                row["deleted"] = True
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
    return rows


def path_suffix_transient(path: Path) -> bool:
    return path.suffix.lower() in TRANSIENT_SUFFIXES or path.name in {".pytest_cache"}


def classify_blocker(root_name: str, path: Path) -> str:
    s = str(path).lower()
    name = path.name.lower()
    if root_name == "repo" and ("canonical" in s or "price_history" in s or "snapshot" in s):
        return "ACTIVE_CANONICAL_LINEAGE"
    if is_manifest_like(path):
        return "PROTECTED_POINTER_OR_MANIFEST"
    if root_name == "archive":
        return "UNIQUE_ARCHIVE_COPY"
    if root_name == "quarantine":
        return "UNIQUE_QUARANTINE_NO_TRUSTED_COPY"
    if root_name == "cache" and (cache_protected(path) or "canonical" in s):
        return "CACHE_ACTIVE_OR_REGISTRY"
    if is_recent(path, 24 * 3600):
        return "RECENT_FILE"
    if root_name == "repo" and ("scripts" in path.parts or "config" in path.parts or any(part in PROTECTED_REPO_PARTS for part in path.parts)):
        return "SOURCE_OR_CONFIG_PROTECTED"
    return "UNKNOWN_SKIP"


def combined_top(repo: Path, archive: Path, cache: Path, quarantine: Path, n: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for root_name, root, protect in (("repo", repo, True), ("archive", archive, False), ("cache", cache, False), ("quarantine", quarantine, False)):
        for row in top_size_for_root(root, root_name, n, protect):
            rows.append(row)
    return sorted(rows, key=lambda r: int(r["size_bytes"]), reverse=True)[:n]


def remaining_blockers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        p = Path(row["path"])
        out.append({**row, "blocker_class": classify_blocker(str(row["root_name"]), p)})
    return out


def run(
    repo_root: Path,
    archive_root: Path,
    cache_root: Path,
    quarantine_root: Path,
    output_dir: Path,
    execute: bool,
    min_target_mb: float,
    top_size_count: int,
    allow_archive_compress: bool,
    allow_archive_duplicate_delete: bool,
    allow_quarantine_verified_delete: bool,
    allow_cache_retention_delete: bool,
    archive_compress_min_mb: float,
    cache_retention_days: int,
    quarantine_retention_days: int,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    archive_root = archive_root.resolve()
    cache_root = cache_root.resolve()
    quarantine_root = quarantine_root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    before_rows = four_root_rows(repo_root, archive_root, cache_root, quarantine_root)
    before_total = totals(before_rows)
    top_before = combined_top(repo_root, archive_root, cache_root, quarantine_root, top_size_count)
    skipped: list[dict[str, Any]] = []
    compressed = phase_archive_compress(archive_root, execute, allow_archive_compress, archive_compress_min_mb, skipped)
    duplicates = phase_archive_duplicates(archive_root, repo_root, execute, allow_archive_duplicate_delete, skipped)
    quarantine_deleted = phase_quarantine(quarantine_root, repo_root, archive_root, execute, allow_quarantine_verified_delete, quarantine_retention_days, skipped)
    cache_deleted = phase_cache(cache_root, execute, allow_cache_retention_delete, cache_retention_days, skipped)
    after_rows = four_root_rows(repo_root, archive_root, cache_root, quarantine_root)
    after_total = totals(after_rows)
    top_after = combined_top(repo_root, archive_root, cache_root, quarantine_root, top_size_count)
    blockers = remaining_blockers(top_after)

    write_csv(output_dir / "v21_239_four_root_footprint_before.csv", before_rows, ["root_name", "root_path", "size_bytes", "file_count", "dir_count"])
    write_csv(output_dir / "v21_239_four_root_footprint_after.csv", after_rows, ["root_name", "root_path", "size_bytes", "file_count", "dir_count"])
    write_csv(output_dir / "v21_239_combined_top_size_before.csv", top_before, ["root_name", "path", "relative_path", "size_bytes", "size_mb"])
    write_csv(output_dir / "v21_239_combined_top_size_after.csv", top_after, ["root_name", "path", "relative_path", "size_bytes", "size_mb"])
    write_csv(output_dir / "v21_239_archive_compressed_manifest.csv", compressed, ["source_path", "original_size_bytes", "original_sha256", "gzip_path", "gzip_size_bytes", "gzip_sha256", "decompressed_sha256_verified", "deleted_original", "dry_run", "error"])
    write_csv(output_dir / "v21_239_archive_duplicate_deleted_manifest.csv", duplicates, ["deleted_path", "deleted_relative_path", "retained_path", "sha256", "size_bytes", "deleted", "dry_run", "error"])
    write_csv(output_dir / "v21_239_quarantine_verified_deleted_manifest.csv", quarantine_deleted, ["path", "relative_path", "size_bytes", "sha256", "trusted_retained_copy_path", "trusted_copy_type", "deleted", "dry_run", "error"])
    write_csv(output_dir / "v21_239_cache_retention_deleted_manifest.csv", cache_deleted, ["path", "relative_path", "size_bytes", "sha256", "deleted", "dry_run", "error"])
    write_csv(output_dir / "v21_239_skipped_blockers.csv", skipped, ["root_name", "path", "relative_path", "size_bytes", "blocker_type", "phase", "notes"])
    write_csv(output_dir / "v21_239_remaining_blockers_by_bytes.csv", blockers, ["root_name", "path", "relative_path", "size_bytes", "size_mb", "blocker_class"])
    pointers = [{"source_path": r["source_path"], "source_sha256": r["original_sha256"], "gzip_path": r["gzip_path"], "gzip_sha256": r["gzip_sha256"]} for r in compressed if r.get("deleted_original") or r.get("dry_run")]
    write_json(output_dir / "v21_239_pointer_manifest.json", {"policy_version": "V21.239", "created_at_utc": utc_now(), "compressed_archive_pointers": pointers})

    verification_failed = sum(1 for r in compressed if r.get("error") or (execute and not r.get("decompressed_sha256_verified")))
    deletion_errors = sum(1 for group in (duplicates, quarantine_deleted, cache_deleted) for r in group if r.get("error"))
    error_count = verification_failed + deletion_errors
    total_reduced = before_total["size"] - after_total["size"]
    target_met = total_reduced >= min_target_mb * 1024 * 1024
    final_status = FAIL_STATUS if error_count else PASS_STATUS if target_met else WARN_STATUS

    by_root_before = {r["root_name"]: r for r in before_rows}
    by_root_after = {r["root_name"]: r for r in after_rows}
    compressed_done = [r for r in compressed if r.get("deleted_original")]
    duplicate_done = [r for r in duplicates if r.get("deleted")]
    quarantine_done = [r for r in quarantine_deleted if r.get("deleted")]
    cache_done = [r for r in cache_deleted if r.get("deleted")]
    summary = {
        "final_status": final_status,
        "final_decision": DECISION,
        "repo_root": str(repo_root),
        "archive_root": str(archive_root),
        "cache_root": str(cache_root),
        "quarantine_root": str(quarantine_root),
        "execute_mode": execute,
        "repo_size_before_bytes": by_root_before["repo"]["size_bytes"],
        "repo_size_after_bytes": by_root_after["repo"]["size_bytes"],
        "archive_size_before_bytes": by_root_before["archive"]["size_bytes"],
        "archive_size_after_bytes": by_root_after["archive"]["size_bytes"],
        "cache_size_before_bytes": by_root_before["cache"]["size_bytes"],
        "cache_size_after_bytes": by_root_after["cache"]["size_bytes"],
        "quarantine_size_before_bytes": by_root_before["quarantine"]["size_bytes"],
        "quarantine_size_after_bytes": by_root_after["quarantine"]["size_bytes"],
        "total_size_before_bytes": before_total["size"],
        "total_size_after_bytes": after_total["size"],
        "total_size_reduced_bytes": total_reduced,
        "total_size_reduced_mb": round(total_reduced / 1024 / 1024, 3),
        "repo_file_count_before": by_root_before["repo"]["file_count"],
        "repo_file_count_after": by_root_after["repo"]["file_count"],
        "archive_file_count_before": by_root_before["archive"]["file_count"],
        "archive_file_count_after": by_root_after["archive"]["file_count"],
        "cache_file_count_before": by_root_before["cache"]["file_count"],
        "cache_file_count_after": by_root_after["cache"]["file_count"],
        "quarantine_file_count_before": by_root_before["quarantine"]["file_count"],
        "quarantine_file_count_after": by_root_after["quarantine"]["file_count"],
        "total_file_count_before": before_total["files"],
        "total_file_count_after": after_total["files"],
        "total_file_count_reduced": before_total["files"] - after_total["files"],
        "archive_compressed_count": len(compressed_done),
        "archive_original_bytes_compressed": sum(int(r["original_size_bytes"]) for r in compressed_done),
        "archive_gzip_bytes_created": sum(int(r["gzip_size_bytes"]) for r in compressed_done),
        "archive_compression_net_reduction_bytes": sum(int(r["original_size_bytes"]) - int(r["gzip_size_bytes"]) for r in compressed_done),
        "archive_duplicate_deleted_count": len(duplicate_done),
        "archive_duplicate_deleted_bytes": sum(int(r["size_bytes"]) for r in duplicate_done),
        "quarantine_verified_deleted_count": len(quarantine_done),
        "quarantine_verified_deleted_bytes": sum(int(r["size_bytes"]) for r in quarantine_done),
        "cache_retention_deleted_count": len(cache_done),
        "cache_retention_deleted_bytes": sum(int(r["size_bytes"]) for r in cache_done),
        "skipped_count": len(skipped),
        "protected_skipped_count": sum(1 for r in skipped if "PROTECTED" in r["blocker_type"]),
        "unique_copy_skipped_count": sum(1 for r in skipped if "UNIQUE" in r["blocker_type"]),
        "recent_file_skipped_count": sum(1 for r in skipped if "RECENT" in r["blocker_type"]),
        "verification_failed_count": verification_failed,
        "error_count": error_count,
        "warning_count": len(skipped),
        "min_target_mb": min_target_mb,
        "target_met": target_met,
        "repo_active_files_modified": False,
        "active_canonical_file_modified": False,
        "market_data_fetch_performed": False,
        "yahoo_yfinance_used": False,
        "moomoo_futu_used": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
    }
    write_json(output_dir / "v21_239_summary.json", summary)
    report = "\n".join([
        STAGE,
        f"final_status={final_status}",
        f"final_decision={DECISION}",
        f"total_size_reduced_mb={summary['total_size_reduced_mb']}",
        f"archive_compressed_count={summary['archive_compressed_count']}",
        f"archive_duplicate_deleted_count={summary['archive_duplicate_deleted_count']}",
        f"quarantine_verified_deleted_count={summary['quarantine_verified_deleted_count']}",
        f"cache_retention_deleted_count={summary['cache_retention_deleted_count']}",
        "market_data_fetch_performed=False",
        "broker_action_allowed=False",
        "official_adoption_allowed=False",
    ]) + "\n"
    (output_dir / "V21.239_total_disk_footprint_governance_report.txt").write_text(report, encoding="utf-8")
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
    parser.add_argument("--min-target-mb", type=float, default=300.0)
    parser.add_argument("--top-size", type=int, default=500)
    parser.add_argument("--allow-archive-compress", action="store_true", default=False)
    parser.add_argument("--allow-archive-duplicate-delete", action="store_true", default=False)
    parser.add_argument("--allow-quarantine-verified-delete", action="store_true", default=False)
    parser.add_argument("--allow-cache-retention-delete", action="store_true", default=False)
    parser.add_argument("--archive-compress-min-mb", type=float, default=5.0)
    parser.add_argument("--cache-retention-days", type=int, default=14)
    parser.add_argument("--quarantine-retention-days", type=int, default=7)
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
        allow_archive_compress=args.allow_archive_compress,
        allow_archive_duplicate_delete=args.allow_archive_duplicate_delete,
        allow_quarantine_verified_delete=args.allow_quarantine_verified_delete,
        allow_cache_retention_delete=args.allow_cache_retention_delete,
        archive_compress_min_mb=args.archive_compress_min_mb,
        cache_retention_days=args.cache_retention_days,
        quarantine_retention_days=args.quarantine_retention_days,
    )
    print(str(out / "v21_239_summary.json"))
    return 1 if summary["final_status"] == FAIL_STATUS else 0


if __name__ == "__main__":
    raise SystemExit(main())
