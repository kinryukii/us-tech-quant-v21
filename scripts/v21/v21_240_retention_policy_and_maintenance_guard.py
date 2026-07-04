#!/usr/bin/env python
"""V21.240 retention policy and maintenance guard.

This stage is a maintenance guard. It audits the main repo, and only mutates
archive/cache/quarantine roots when explicit allow flags plus --execute are set.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


STAGE = "V21.240_RETENTION_POLICY_AND_MAINTENANCE_GUARD"
OUT_REL = Path("outputs/v21") / STAGE
PASS_OK = "PASS_V21_240_RETENTION_GUARD_OK"
PASS_MAINT = "PASS_V21_240_RETENTION_GUARD_MAINTENANCE_APPLIED"
WARN_BUDGET = "WARN_V21_240_RETENTION_GUARD_WARN_BUDGET"
WARN_LARGE = "WARN_V21_240_RETENTION_GUARD_REPO_LARGE_FILE_VIOLATION"
FAIL_BUDGET = "FAIL_V21_240_RETENTION_GUARD_HARD_BUDGET_BREACH"
FAIL_ERROR = "FAIL_V21_240_RETENTION_GUARD_ERROR"
DECISION = "RETENTION_POLICY_AND_MAINTENANCE_GUARD_READY_FOR_DAILY_CHAIN_USE"
COMPRESS_EXTS = {".csv", ".json", ".txt", ".log", ".html", ".xlsx", ".parquet", ".pkl", ".pickle"}
COMPRESSED_EXTS = {".gz", ".zip", ".7z", ".zst", ".br"}
PROTECTED_REPO_PARTS = {".git", ".venv", ".venv_moomoo_py312"}
TRANSIENT_SUFFIXES = {".tmp", ".temp", ".bak", ".pyc"}
PROTECTED_LINEAGE = {
    "inputs/v21/historical_ohlcv_cache/V21_037_R1_HISTORICAL_OHLCV_CACHE.csv",
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV_RAW_TRADE_PLAN.csv",
}
ACTIVE_PREFIXES = (
    "outputs/v21/V21.197", "outputs/v21/V21.198", "outputs/v21/V21.199",
    "outputs/v21/V21.201", "outputs/v21/V21.223", "outputs/v21/V21.236",
    "outputs/v21/V21.237", "outputs/v21/V21.238", "outputs/v21/V21.239",
    "outputs/v21/V21.240",
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
    files = []
    for p in safe_iter(root):
        if not p.is_file():
            continue
        if protect_repo and any(part in PROTECTED_REPO_PARTS for part in p.parts):
            continue
        files.append(p)
    return files


def footprint(root: Path, name: str, protect_repo: bool = False) -> dict[str, Any]:
    size = files = dirs = 0
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
    rows = []
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


def combined_top(repo: Path, archive: Path, cache: Path, quarantine: Path, n: int) -> list[dict[str, Any]]:
    rows = []
    for name, root, protect in (("repo", repo, True), ("archive", archive, False), ("cache", cache, False), ("quarantine", quarantine, False)):
        rows.extend(top_size_for_root(root, name, n, protect))
    return sorted(rows, key=lambda r: int(r["size_bytes"]), reverse=True)[:n]


def is_recent(path: Path, hours: float) -> bool:
    try:
        return time.time() - path.stat().st_mtime < hours * 3600
    except OSError:
        return True


def is_manifest_like(path: Path) -> bool:
    name = path.name.lower()
    return any(token in name for token in ("manifest", "pointer", "summary", "report", "registry", ".sha256", "policy"))


def budget_status(size_bytes: int, warning_mb: float, hard_mb: float) -> str:
    size_mb = size_bytes / 1024 / 1024
    if size_mb >= hard_mb:
        return "FAIL_SIZE_BUDGET"
    if size_mb >= warning_mb:
        return "WARN_SIZE_BUDGET"
    return "OK"


def build_policy(args: argparse.Namespace, repo: Path, archive: Path, cache: Path, quarantine: Path) -> dict[str, Any]:
    return {
        "policy_version": "V21.240",
        "created_at_utc": utc_now(),
        "root_paths": {"repo": str(repo), "archive": str(archive), "cache": str(cache), "quarantine": str(quarantine)},
        "budgets_mb": {
            "repo_warning": args.repo_warning_mb, "repo_hard": args.repo_hard_mb,
            "archive_warning": args.archive_warning_mb, "archive_hard": args.archive_hard_mb,
            "cache_warning": args.cache_warning_mb, "cache_hard": args.cache_hard_mb,
            "quarantine_warning": args.quarantine_warning_mb, "quarantine_hard": args.quarantine_hard_mb,
            "total_warning": args.total_warning_mb, "total_hard": args.total_hard_mb,
        },
        "retention_days": {"cache": args.cache_retention_days, "quarantine": args.quarantine_retention_days},
        "archive_compression_rules": {"min_mb": args.archive_compress_min_mb, "extensions": sorted(COMPRESS_EXTS), "skip_existing_compressed": True},
        "quarantine_verified_deletion_rules": {"trusted_sources": ["repo", "archive"], "quarantine_is_not_trusted_source": True},
        "cache_retention_rules": {"delete_transient_patterns": ["tmp/*", "selftest/*", "__pycache__", ".pytest_cache", "*.tmp", "*.temp", "*.bak", "*.pyc"]},
        "repo_large_file_governance_rules": {"warning_mb": args.repo_large_file_warning_mb, "hard_mb": args.repo_large_file_hard_mb, "audit_only": True},
        "protected_path_patterns": ["scripts/**", "config/**", ".git/**", ".venv/**", "cache/registry/**", "*pointer*", "*manifest*"],
        "active_lineage_protection_patterns": sorted(PROTECTED_LINEAGE) + list(ACTIVE_PREFIXES),
    }


def write_policy(cache_root: Path, output_dir: Path, policy: dict[str, Any], execute: bool) -> None:
    policy_path = cache_root / "retention_policy" / "v21_240_retention_policy.json"
    if execute:
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        if policy_path.exists():
            backup = policy_path.with_name(f"v21_240_retention_policy.backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json")
            shutil.copy2(policy_path, backup)
        write_json(policy_path, policy)
    write_json(output_dir / "v21_240_retention_policy_snapshot.json", policy)


def load_pointer_governance(repo_root: Path) -> str:
    chunks = []
    for stage in ("V21.236", "V21.237", "V21.238", "V21.239", "V21.240"):
        root = repo_root / "outputs" / "v21"
        if not root.exists():
            continue
        for d in root.iterdir():
            if d.is_dir() and d.name.startswith(stage):
                for p in d.rglob("*pointer*.json"):
                    try:
                        chunks.append(p.read_text(encoding="utf-8", errors="ignore"))
                    except OSError:
                        pass
    return "\n".join(chunks)


def repo_classification(path: Path, repo_root: Path, pointer_text: str, recent_hours: float) -> tuple[str, bool]:
    r = rel(path, repo_root)
    if any(part in PROTECTED_REPO_PARTS for part in path.parts) or r.startswith("scripts/") or r.startswith("config/"):
        return "SOURCE_OR_CONFIG_PROTECTED", False
    if r in PROTECTED_LINEAGE or r.startswith("outputs/v20/price_history/") or r.startswith("outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/canonical_backups/") or r.startswith("outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/moomoo_daily_ohlcv_"):
        return "ACTIVE_CANONICAL_LINEAGE", False
    if r.startswith("outputs/v21/V21.232"):
        return "CURRENT_DRAM_OUTPUT", False
    if r.startswith("outputs/v21/V21.233"):
        return "CURRENT_ABCDE_OUTPUT", False
    if r.startswith("outputs/v21/V21.234") or r.startswith("outputs/v21/V21.240"):
        return "CURRENT_DAILY_CHAIN_OUTPUT", False
    if is_manifest_like(path):
        return "PROTECTED_POINTER_OR_MANIFEST", False
    if r in pointer_text or str(path) in pointer_text or path.with_suffix(path.suffix + ".sha256").exists() or Path(str(path) + ".pointer.json").exists():
        return "ALLOWED_LARGE_REPO_FILE", False
    if is_recent(path, recent_hours):
        return "RECENT_UNCLASSIFIED_LARGE_FILE", True
    return "NEEDS_ARCHIVE_POINTER_GOVERNANCE", True


def repo_large_file_audit(repo_root: Path, warning_mb: float, hard_mb: float, recent_hours: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pointer_text = load_pointer_governance(repo_root)
    rows = []
    violations = []
    warn_bytes = int(warning_mb * 1024 * 1024)
    hard_bytes = int(hard_mb * 1024 * 1024)
    for p in file_list(repo_root, True):
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size < warn_bytes:
            continue
        cls, violation = repo_classification(p, repo_root, pointer_text, recent_hours)
        hard = size >= hard_bytes
        row = {
            "path": str(p), "relative_path": rel(p, repo_root), "size_bytes": size,
            "size_mb": round(size / 1024 / 1024, 3), "classification": cls,
            "hard_threshold": hard, "guard_violation": violation and hard,
            "notes": "repo audit only; no repo deletion in V21.240",
        }
        rows.append(row)
        if row["guard_violation"]:
            violations.append({"path": str(p), "relative_path": row["relative_path"], "size_bytes": size, "violation_type": cls, "severity": "WARN", "notes": "large repo file lacks archive/pointer governance"})
    return rows, violations


def gzip_verify_delete(src: Path, execute: bool) -> dict[str, Any]:
    original_size = src.stat().st_size
    original_hash = sha256_file(src)
    gzip_path = Path(str(src) + ".gz")
    row = {
        "source_path": str(src), "original_size_bytes": original_size, "original_sha256": original_hash,
        "gzip_path": str(gzip_path), "gzip_size_bytes": 0, "gzip_sha256": "",
        "decompressed_sha256_verified": False, "deleted_original": False, "dry_run": not execute, "error": "",
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


def archive_compress_candidate(path: Path, min_bytes: int, recent_hours: float) -> tuple[bool, str]:
    if path.suffix.lower() in COMPRESSED_EXTS:
        return False, "ALREADY_COMPRESSED"
    if path.suffix.lower() not in COMPRESS_EXTS:
        return False, "EXTENSION_NOT_TARGETED"
    if path.stat().st_size < min_bytes:
        return False, "BELOW_SIZE_THRESHOLD"
    if is_manifest_like(path) and path.stat().st_size < 50 * 1024 * 1024:
        return False, "PROTECTED_POINTER_OR_MANIFEST"
    if is_recent(path, recent_hours):
        return False, "RECENT_FILE"
    return True, ""


def phase_archive_compress(archive_root: Path, execute: bool, allowed: bool, min_mb: float, recent_hours: float, skipped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    if not allowed or not archive_root.exists():
        return rows
    min_bytes = int(min_mb * 1024 * 1024)
    for p in file_list(archive_root):
        ok, reason = archive_compress_candidate(p, min_bytes, recent_hours)
        if ok:
            rows.append(gzip_verify_delete(p, execute))
        elif p.is_file() and p.stat().st_size >= min_bytes and reason not in {"BELOW_SIZE_THRESHOLD", "EXTENSION_NOT_TARGETED", "ALREADY_COMPRESSED"}:
            add_skip(skipped, "archive", p, archive_root, reason, "archive_compress")
    return rows


def load_pointer_text(repo_root: Path, archive_root: Path) -> str:
    chunks = []
    for root in (repo_root / "outputs" / "v21", archive_root):
        if not root.exists():
            continue
        for p in root.rglob("*pointer*.json"):
            try:
                if p.stat().st_size <= 20 * 1024 * 1024:
                    chunks.append(p.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                pass
    return "\n".join(chunks)


def duplicate_key(path: Path) -> tuple[str, str] | None:
    try:
        if path.suffix.lower() == ".gz":
            return ("content", gzip_decompressed_sha256(path))
        return ("content", sha256_file(path))
    except Exception:
        return None


def duplicate_preference(path: Path, pointer_text: str) -> tuple[int, int, int, int, int]:
    s = str(path)
    return (
        0 if pointer_text and s in pointer_text else 1,
        0 if path.suffix.lower() == ".gz" else 1,
        0 if ("V21.240" in s or "V21.239" in s) else 1,
        0 if "protected_evidence" in s else 1,
        len(s),
    )


def phase_archive_duplicates(archive_root: Path, repo_root: Path, execute: bool, allowed: bool) -> list[dict[str, Any]]:
    rows = []
    if not allowed or not archive_root.exists():
        return rows
    pointer_text = load_pointer_text(repo_root, archive_root)
    groups: dict[tuple[str, str], list[Path]] = {}
    for p in file_list(archive_root):
        if is_manifest_like(p):
            continue
        key = duplicate_key(p)
        if key:
            groups.setdefault(key, []).append(p)
    for (_kind, digest), paths in groups.items():
        if len(paths) < 2:
            continue
        retain = sorted(paths, key=lambda p: duplicate_preference(p, pointer_text))[0]
        for p in paths:
            if p == retain:
                continue
            row = {"deleted_path": str(p), "deleted_relative_path": rel(p, archive_root), "retained_path": str(retain), "sha256_or_decompressed_sha256": digest, "size_bytes": p.stat().st_size, "deleted": False, "dry_run": not execute, "error": ""}
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
                pass
    return index


def find_exact_copy(path: Path, index: dict[int, list[Path]]) -> tuple[Path | None, str]:
    digest = sha256_file(path)
    for other in index.get(path.stat().st_size, []):
        try:
            if other.resolve() != path.resolve() and sha256_file(other) == digest:
                return other, digest
        except OSError:
            pass
    return None, digest


def find_gzip_copy(digest: str, archive_root: Path) -> Path | None:
    for gz in archive_root.rglob("*.gz") if archive_root.exists() else []:
        try:
            if gzip_decompressed_sha256(gz) == digest:
                return gz
        except Exception:
            pass
    return None


def phase_quarantine(quarantine_root: Path, repo_root: Path, archive_root: Path, execute: bool, allowed: bool, retention_days: int, skipped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    if not allowed or not quarantine_root.exists():
        return rows
    index = trusted_index(repo_root, archive_root)
    for p in file_list(quarantine_root):
        if is_manifest_like(p):
            add_skip(skipped, "quarantine", p, quarantine_root, "PROTECTED_POINTER_OR_MANIFEST", "quarantine_verified_delete")
            continue
        trusted, digest = find_exact_copy(p, index)
        trusted_type = "exact_size_sha256"
        if not trusted:
            trusted = find_gzip_copy(digest, archive_root)
            trusted_type = "gzip_decompressed_sha256" if trusted else ""
        if not trusted:
            add_skip(skipped, "quarantine", p, quarantine_root, "UNIQUE_QUARANTINE_NO_TRUSTED_COPY", "quarantine_verified_delete")
            continue
        if is_recent(p, retention_days * 24) and "quarantine" not in str(p).lower():
            add_skip(skipped, "quarantine", p, quarantine_root, "RECENT_FILE", "quarantine_verified_delete")
            continue
        row = {"path": str(p), "relative_path": rel(p, quarantine_root), "size_bytes": p.stat().st_size, "sha256": digest, "trusted_retained_copy_path": str(trusted), "trusted_copy_type": trusted_type, "deleted": False, "dry_run": not execute, "error": ""}
        if execute:
            try:
                p.unlink()
                row["deleted"] = True
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
    return rows


def cache_protected(path: Path) -> bool:
    s = str(path).lower()
    name = path.name.lower()
    return any(token in name for token in ("registry", "pointer", "manifest", "retention", "policy", "index")) or "canonical" in s or "canonical_moomoo_ohlcv_daily_qfq.csv" in s or "canonical_moomoo_ohlcv_daily_raw.csv" in s


def cache_transient(path: Path, cache_root: Path) -> bool:
    r = rel(path, cache_root).lower()
    return r.startswith("tmp/") or r.startswith("selftest/") or "__pycache__" in path.parts or ".pytest_cache" in path.parts or path.suffix.lower() in TRANSIENT_SUFFIXES or "transient" in r or "expired" in r or "reproducible" in r


def phase_cache(cache_root: Path, execute: bool, allowed: bool, retention_days: int, skipped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    if not allowed or not cache_root.exists():
        return rows
    for p in file_list(cache_root):
        if cache_protected(p):
            add_skip(skipped, "cache", p, cache_root, "CACHE_ACTIVE_OR_REGISTRY", "cache_retention_delete")
            continue
        if not cache_transient(p, cache_root):
            continue
        r = rel(p, cache_root).lower()
        if not (r.startswith("tmp/") or r.startswith("selftest/") or path_suffix_transient(p) or not is_recent(p, retention_days * 24)):
            add_skip(skipped, "cache", p, cache_root, "RECENT_FILE", "cache_retention_delete")
            continue
        row = {"path": str(p), "relative_path": rel(p, cache_root), "size_bytes": p.stat().st_size, "sha256": sha256_file(p), "deleted": False, "dry_run": not execute, "error": ""}
        if execute:
            try:
                p.unlink()
                row["deleted"] = True
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
    return rows


def path_suffix_transient(path: Path) -> bool:
    return path.suffix.lower() in TRANSIENT_SUFFIXES


def blocker_class(root_name: str, path: Path) -> str:
    s = str(path).lower()
    if root_name == "repo":
        if "canonical" in s or "price_history" in s:
            return "ACTIVE_CANONICAL_LINEAGE"
        if is_manifest_like(path):
            return "PROTECTED_POINTER_OR_MANIFEST"
        if "scripts" in path.parts or "config" in path.parts or any(part in PROTECTED_REPO_PARTS for part in path.parts):
            return "SOURCE_OR_CONFIG_PROTECTED"
    if root_name == "cache" and cache_protected(path):
        return "CACHE_ACTIVE_OR_REGISTRY"
    if root_name == "quarantine":
        return "UNIQUE_QUARANTINE_NO_TRUSTED_COPY"
    if root_name == "archive":
        return "UNIQUE_ARCHIVE_COPY"
    return "UNKNOWN_SKIP"


def remaining_blockers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        out.append({**row, "blocker_class": blocker_class(row["root_name"], Path(row["path"]))})
    return out


def run(
    repo_root: Path,
    archive_root: Path,
    cache_root: Path,
    quarantine_root: Path,
    output_dir: Path,
    execute: bool,
    audit_only: bool,
    top_size_count: int,
    budgets: dict[str, float],
    allow_archive_compress: bool,
    allow_archive_duplicate_delete: bool,
    allow_quarantine_verified_delete: bool,
    allow_cache_retention_delete: bool,
    archive_compress_min_mb: float,
    repo_large_file_warning_mb: float,
    repo_large_file_hard_mb: float,
    cache_retention_days: int,
    quarantine_retention_days: int,
    recent_file_protection_hours: float,
    policy_args: argparse.Namespace | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    archive_root = archive_root.resolve()
    cache_root = cache_root.resolve()
    quarantine_root = quarantine_root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if policy_args is None:
        policy_args = argparse.Namespace(**budgets, archive_compress_min_mb=archive_compress_min_mb, repo_large_file_warning_mb=repo_large_file_warning_mb, repo_large_file_hard_mb=repo_large_file_hard_mb, cache_retention_days=cache_retention_days, quarantine_retention_days=quarantine_retention_days)
    before_rows = four_root_rows(repo_root, archive_root, cache_root, quarantine_root)
    before_total = totals(before_rows)
    top_before = combined_top(repo_root, archive_root, cache_root, quarantine_root, top_size_count)
    write_policy(cache_root, output_dir, build_policy(policy_args, repo_root, archive_root, cache_root, quarantine_root), execute)

    repo_audit, violations = repo_large_file_audit(repo_root, repo_large_file_warning_mb, repo_large_file_hard_mb, recent_file_protection_hours)
    skipped: list[dict[str, Any]] = []
    mutating = execute and not audit_only
    compressed = phase_archive_compress(archive_root, mutating, allow_archive_compress, archive_compress_min_mb, recent_file_protection_hours, skipped)
    duplicates = phase_archive_duplicates(archive_root, repo_root, mutating, allow_archive_duplicate_delete)
    quarantine_rows = phase_quarantine(quarantine_root, repo_root, archive_root, mutating, allow_quarantine_verified_delete, quarantine_retention_days, skipped)
    cache_rows = phase_cache(cache_root, mutating, allow_cache_retention_delete, cache_retention_days, skipped)

    after_rows = four_root_rows(repo_root, archive_root, cache_root, quarantine_root)
    after_total = totals(after_rows)
    top_after = combined_top(repo_root, archive_root, cache_root, quarantine_root, top_size_count)
    blockers = remaining_blockers(top_after)

    fields_root = ["root_name", "root_path", "size_bytes", "file_count", "dir_count"]
    write_csv(output_dir / "v21_240_four_root_footprint_before.csv", before_rows, fields_root)
    write_csv(output_dir / "v21_240_four_root_footprint_after.csv", after_rows, fields_root)
    write_csv(output_dir / "v21_240_combined_top_size_before.csv", top_before, ["root_name", "path", "relative_path", "size_bytes", "size_mb"])
    write_csv(output_dir / "v21_240_combined_top_size_after.csv", top_after, ["root_name", "path", "relative_path", "size_bytes", "size_mb"])
    write_csv(output_dir / "v21_240_repo_large_file_governance_audit.csv", repo_audit, ["path", "relative_path", "size_bytes", "size_mb", "classification", "hard_threshold", "guard_violation", "notes"])
    write_csv(output_dir / "v21_240_guard_violations.csv", violations, ["path", "relative_path", "size_bytes", "violation_type", "severity", "notes"])
    write_csv(output_dir / "v21_240_archive_compressed_manifest.csv", compressed, ["source_path", "original_size_bytes", "original_sha256", "gzip_path", "gzip_size_bytes", "gzip_sha256", "decompressed_sha256_verified", "deleted_original", "dry_run", "error"])
    write_csv(output_dir / "v21_240_archive_duplicate_deleted_manifest.csv", duplicates, ["deleted_path", "deleted_relative_path", "retained_path", "sha256_or_decompressed_sha256", "size_bytes", "deleted", "dry_run", "error"])
    write_csv(output_dir / "v21_240_quarantine_verified_deleted_manifest.csv", quarantine_rows, ["path", "relative_path", "size_bytes", "sha256", "trusted_retained_copy_path", "trusted_copy_type", "deleted", "dry_run", "error"])
    write_csv(output_dir / "v21_240_cache_retention_deleted_manifest.csv", cache_rows, ["path", "relative_path", "size_bytes", "sha256", "deleted", "dry_run", "error"])
    write_csv(output_dir / "v21_240_skipped_blockers.csv", skipped, ["root_name", "path", "relative_path", "size_bytes", "blocker_type", "phase", "notes"])
    write_csv(output_dir / "v21_240_remaining_blockers_by_bytes.csv", blockers, ["root_name", "path", "relative_path", "size_bytes", "size_mb", "blocker_class"])
    pointers = [{"source_path": r["source_path"], "source_sha256": r["original_sha256"], "gzip_path": r["gzip_path"], "gzip_sha256": r["gzip_sha256"]} for r in compressed if r.get("deleted_original") or r.get("dry_run")]
    write_json(output_dir / "v21_240_pointer_manifest.json", {"policy_version": "V21.240", "created_at_utc": utc_now(), "compressed_archive_pointers": pointers})

    by_before = {r["root_name"]: r for r in before_rows}
    by_after = {r["root_name"]: r for r in after_rows}
    repo_status = budget_status(by_after["repo"]["size_bytes"], budgets["repo_warning_mb"], budgets["repo_hard_mb"])
    archive_status = budget_status(by_after["archive"]["size_bytes"], budgets["archive_warning_mb"], budgets["archive_hard_mb"])
    cache_status = budget_status(by_after["cache"]["size_bytes"], budgets["cache_warning_mb"], budgets["cache_hard_mb"])
    quarantine_status = budget_status(by_after["quarantine"]["size_bytes"], budgets["quarantine_warning_mb"], budgets["quarantine_hard_mb"])
    total_status = budget_status(after_total["size"], budgets["total_warning_mb"], budgets["total_hard_mb"])
    verification_failed = sum(1 for r in compressed if r.get("error") or (mutating and not r.get("decompressed_sha256_verified")))
    deletion_errors = sum(1 for group in (duplicates, quarantine_rows, cache_rows) for r in group if r.get("error"))
    error_count = verification_failed + deletion_errors
    hard_breach = any(s == "FAIL_SIZE_BUDGET" for s in (repo_status, archive_status, cache_status, quarantine_status, total_status))
    warn_breach = any(s == "WARN_SIZE_BUDGET" for s in (repo_status, archive_status, cache_status, quarantine_status, total_status))
    total_reduced = before_total["size"] - after_total["size"]
    if error_count:
        final_status = FAIL_ERROR
    elif hard_breach:
        final_status = FAIL_BUDGET
    elif violations:
        final_status = WARN_LARGE
    elif total_reduced > 0 and not warn_breach:
        final_status = PASS_MAINT
    elif warn_breach:
        final_status = WARN_BUDGET
    else:
        final_status = PASS_OK
    compressed_done = [r for r in compressed if r.get("deleted_original")]
    duplicate_done = [r for r in duplicates if r.get("deleted")]
    quarantine_done = [r for r in quarantine_rows if r.get("deleted")]
    cache_done = [r for r in cache_rows if r.get("deleted")]
    summary = {
        "final_status": final_status,
        "final_decision": DECISION,
        "repo_root": str(repo_root), "archive_root": str(archive_root), "cache_root": str(cache_root), "quarantine_root": str(quarantine_root),
        "execute_mode": execute, "audit_only": audit_only,
        "repo_size_before_bytes": by_before["repo"]["size_bytes"], "repo_size_after_bytes": by_after["repo"]["size_bytes"],
        "archive_size_before_bytes": by_before["archive"]["size_bytes"], "archive_size_after_bytes": by_after["archive"]["size_bytes"],
        "cache_size_before_bytes": by_before["cache"]["size_bytes"], "cache_size_after_bytes": by_after["cache"]["size_bytes"],
        "quarantine_size_before_bytes": by_before["quarantine"]["size_bytes"], "quarantine_size_after_bytes": by_after["quarantine"]["size_bytes"],
        "total_size_before_bytes": before_total["size"], "total_size_after_bytes": after_total["size"],
        "total_size_reduced_bytes": total_reduced, "total_size_reduced_mb": round(total_reduced / 1024 / 1024, 3),
        "repo_file_count_before": by_before["repo"]["file_count"], "repo_file_count_after": by_after["repo"]["file_count"],
        "archive_file_count_before": by_before["archive"]["file_count"], "archive_file_count_after": by_after["archive"]["file_count"],
        "cache_file_count_before": by_before["cache"]["file_count"], "cache_file_count_after": by_after["cache"]["file_count"],
        "quarantine_file_count_before": by_before["quarantine"]["file_count"], "quarantine_file_count_after": by_after["quarantine"]["file_count"],
        "total_file_count_before": before_total["files"], "total_file_count_after": after_total["files"],
        "repo_budget_status": repo_status, "archive_budget_status": archive_status, "cache_budget_status": cache_status, "quarantine_budget_status": quarantine_status, "total_budget_status": total_status,
        "guard_violation_count": len(violations),
        "repo_large_file_warning_count": len(repo_audit),
        "repo_large_file_hard_count": sum(1 for r in repo_audit if r["hard_threshold"]),
        "repo_unclassified_large_file_count": sum(1 for r in repo_audit if r["classification"] in {"NEEDS_ARCHIVE_POINTER_GOVERNANCE", "RECENT_UNCLASSIFIED_LARGE_FILE"}),
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
        "warning_count": len(skipped) + len(violations) + (1 if warn_breach else 0),
        "repo_active_files_modified": False, "active_canonical_file_modified": False,
        "market_data_fetch_performed": False, "yahoo_yfinance_used": False, "moomoo_futu_used": False,
        "broker_action_allowed": False, "official_adoption_allowed": False,
    }
    write_json(output_dir / "v21_240_summary.json", summary)
    report = "\n".join([
        STAGE,
        f"final_status={final_status}",
        f"final_decision={DECISION}",
        f"repo_budget_status={repo_status}",
        f"archive_budget_status={archive_status}",
        f"cache_budget_status={cache_status}",
        f"quarantine_budget_status={quarantine_status}",
        f"total_budget_status={total_status}",
        f"guard_violation_count={len(violations)}",
        "market_data_fetch_performed=False",
        "broker_action_allowed=False",
        "official_adoption_allowed=False",
    ]) + "\n"
    (output_dir / "V21.240_retention_policy_and_maintenance_guard_report.txt").write_text(report, encoding="utf-8")
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
    parser.add_argument("--audit-only", action="store_true", default=False)
    parser.add_argument("--top-size", type=int, default=500)
    for name, default in [
        ("repo-warning-mb", 800), ("repo-hard-mb", 1000), ("total-warning-mb", 2000), ("total-hard-mb", 2500),
        ("archive-warning-mb", 800), ("archive-hard-mb", 1200), ("cache-warning-mb", 700), ("cache-hard-mb", 1000),
        ("quarantine-warning-mb", 100), ("quarantine-hard-mb", 300),
        ("archive-compress-min-mb", 5), ("repo-large-file-warning-mb", 10), ("repo-large-file-hard-mb", 50),
    ]:
        parser.add_argument("--" + name, dest=name.replace("-", "_"), type=float, default=float(default))
    parser.add_argument("--allow-archive-compress", action="store_true", default=False)
    parser.add_argument("--allow-archive-duplicate-delete", action="store_true", default=False)
    parser.add_argument("--allow-quarantine-verified-delete", action="store_true", default=False)
    parser.add_argument("--allow-cache-retention-delete", action="store_true", default=False)
    parser.add_argument("--cache-retention-days", type=int, default=14)
    parser.add_argument("--quarantine-retention-days", type=int, default=7)
    parser.add_argument("--recent-file-protection-hours", type=float, default=24)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    out = args.output_dir or (repo_root / OUT_REL)
    budgets = {
        "repo_warning_mb": args.repo_warning_mb, "repo_hard_mb": args.repo_hard_mb,
        "archive_warning_mb": args.archive_warning_mb, "archive_hard_mb": args.archive_hard_mb,
        "cache_warning_mb": args.cache_warning_mb, "cache_hard_mb": args.cache_hard_mb,
        "quarantine_warning_mb": args.quarantine_warning_mb, "quarantine_hard_mb": args.quarantine_hard_mb,
        "total_warning_mb": args.total_warning_mb, "total_hard_mb": args.total_hard_mb,
    }
    summary = run(
        repo_root=repo_root, archive_root=args.archive_root, cache_root=args.cache_root, quarantine_root=args.quarantine_root,
        output_dir=out, execute=args.execute and not args.dry_run, audit_only=args.audit_only, top_size_count=args.top_size,
        budgets=budgets, allow_archive_compress=args.allow_archive_compress, allow_archive_duplicate_delete=args.allow_archive_duplicate_delete,
        allow_quarantine_verified_delete=args.allow_quarantine_verified_delete, allow_cache_retention_delete=args.allow_cache_retention_delete,
        archive_compress_min_mb=args.archive_compress_min_mb, repo_large_file_warning_mb=args.repo_large_file_warning_mb,
        repo_large_file_hard_mb=args.repo_large_file_hard_mb, cache_retention_days=args.cache_retention_days,
        quarantine_retention_days=args.quarantine_retention_days, recent_file_protection_hours=args.recent_file_protection_hours,
        policy_args=args,
    )
    print(str(out / "v21_240_summary.json"))
    return 1 if summary["final_status"].startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
