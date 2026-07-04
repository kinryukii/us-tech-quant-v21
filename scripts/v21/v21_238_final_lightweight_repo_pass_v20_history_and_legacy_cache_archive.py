#!/usr/bin/env python
"""V21.238 final lightweight repo pass for V20 history and legacy cache files."""

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


STAGE = "V21.238_FINAL_LIGHTWEIGHT_REPO_PASS_V20_HISTORY_AND_LEGACY_CACHE_ARCHIVE"
OUT_REL = Path("outputs/v21") / STAGE
ARCHIVE_STAGE = STAGE
PASS_STATUS = "PASS_V21_238_FINAL_LIGHTWEIGHT_REPO_TARGET_MET"
WARN_STATUS = "WARN_V21_238_FINAL_LIGHTWEIGHT_REPO_DONE_TARGET_NOT_MET"
FAIL_STATUS = "FAIL_V21_238_FINAL_LIGHTWEIGHT_REPO_ERROR"
DECISION = "FINAL_LIGHTWEIGHT_REPO_PASS_COMPLETE"
PROTECTED_PARTS = {".git", ".venv", ".venv_moomoo_py312"}
EXTRA_INVENTORY_REL = {
    "outputs/v21/V21.229_MOOMOO_ONLY_DATA_SOURCE_POLICY_GATE/yahoo_string_inventory.csv",
    "outputs/v21/V21.229_MOOMOO_ONLY_DATA_SOURCE_POLICY_GATE/yfinance_usage_inventory.csv",
}
V20_HISTORY_DIRS = (
    Path("outputs/v20/backtest"),
    Path("outputs/v20/consolidation"),
)
LEGACY_CACHE_DIR = Path("state/v18/price_cache")
PROTECTED_LARGE_REL = {
    "inputs/v21/historical_ohlcv_cache/V21_037_R1_HISTORICAL_OHLCV_CACHE.csv",
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV_RAW_TRADE_PLAN.csv",
}
ACTIVE_REF_DIRS = (
    "V21.197",
    "V21.198",
    "V21.199",
    "V21.201",
    "V21.223",
    "V21.236",
    "V21.237",
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
    if r in PROTECTED_LARGE_REL:
        return "PROTECTED_ACTIVE_CANONICAL_OR_HISTORICAL_OHLCV"
    if r.startswith("outputs/v20/price_history/"):
        return "PRICE_HISTORY_CANONICAL_PROTECTED"
    if r.startswith("outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/canonical_backups/"):
        return "V21_237_RETAINED_CANONICAL_BACKUP_PROTECTED"
    if r.startswith("outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/moomoo_daily_ohlcv_"):
        return "MOOMOO_DAILY_OHLCV_OUTPUT_PROTECTED"
    if "pointer" in rl or "registry" in rl:
        return "POINTER_OR_REGISTRY_PROTECTED"
    return ""


def add_skip(skipped: list[dict[str, Any]], path: Path, repo_root: Path, reason: str, phase: str) -> None:
    size = path.stat().st_size if path.exists() and path.is_file() else 0
    skipped.append({"path": str(path), "relative_path": rel(path, repo_root), "size_bytes": size, "blocker_type": reason, "phase": phase, "notes": "skipped conservatively"})


def load_active_reference_text(repo_root: Path) -> str:
    output_root = repo_root / "outputs" / "v21"
    chunks: list[str] = []
    if not output_root.exists():
        return ""
    for child in output_root.iterdir():
        if not child.is_dir() or not any(child.name.startswith(prefix) for prefix in ACTIVE_REF_DIRS):
            continue
        for p in child.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in {".json", ".csv", ".txt"}:
                continue
            name = p.name.lower()
            if not any(token in name for token in ("summary", "manifest", "pointer")):
                continue
            try:
                if p.stat().st_size > 20 * 1024 * 1024:
                    continue
                chunks.append(p.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
    return "\n".join(chunks)


def is_active_referenced(path: Path, repo_root: Path, ref_text: str) -> bool:
    r = rel(path, repo_root)
    return bool(ref_text and (r in ref_text or str(path) in ref_text))


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
        row["decompressed_sha256_verified"] = gzip_decompressed_sha256(archive_path) == source_hash
        if not row["decompressed_sha256_verified"]:
            row["error"] = "gzip decompressed sha256 mismatch"
            return row
        src.unlink()
        row["deleted_from_repo"] = True
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
    return row


def phase_extra_inventory(repo_root: Path, archive_root: Path, execute: bool, allowed: bool, ref_text: str, skipped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not allowed:
        return rows
    for r in sorted(EXTRA_INVENTORY_REL):
        p = repo_root / r
        if not p.exists():
            continue
        reason = protected_reason(p, repo_root)
        if reason:
            add_skip(skipped, p, repo_root, reason, "v21_229_extra_inventory")
            continue
        if is_active_referenced(p, repo_root, ref_text):
            add_skip(skipped, p, repo_root, "ACTIVE_MANIFEST_REFERENCE", "v21_229_extra_inventory")
            continue
        rows.append(archive_gzip_verify_delete(p, repo_root, archive_root, execute))
    return rows


def phase_v20_history(repo_root: Path, archive_root: Path, execute: bool, allowed: bool, min_mb: float, ref_text: str, skipped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not allowed:
        return rows
    cutoff = min_mb * 1024 * 1024
    for directory in V20_HISTORY_DIRS:
        full_dir = repo_root / directory
        if not full_dir.exists():
            continue
        for p in sorted(full_dir.glob("*.csv")):
            if p.stat().st_size < cutoff:
                continue
            reason = protected_reason(p, repo_root)
            if reason:
                add_skip(skipped, p, repo_root, reason, "v20_history")
                continue
            if is_active_referenced(p, repo_root, ref_text):
                add_skip(skipped, p, repo_root, "ACTIVE_MANIFEST_REFERENCE", "v20_history")
                continue
            rows.append(archive_gzip_verify_delete(p, repo_root, archive_root, execute))
    return rows


def phase_legacy_cache(repo_root: Path, archive_root: Path, execute: bool, allowed: bool, min_mb: float, ref_text: str, skipped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not allowed:
        return rows
    full_dir = repo_root / LEGACY_CACHE_DIR
    if not full_dir.exists():
        return rows
    cutoff = min_mb * 1024 * 1024
    for p in sorted(full_dir.glob("*.csv")):
        if p.stat().st_size < cutoff:
            continue
        reason = protected_reason(p, repo_root)
        if reason:
            add_skip(skipped, p, repo_root, reason, "legacy_state_cache")
            continue
        if is_active_referenced(p, repo_root, ref_text):
            add_skip(skipped, p, repo_root, "ACTIVE_MANIFEST_REFERENCE", "legacy_state_cache")
            continue
        rows.append(archive_gzip_verify_delete(p, repo_root, archive_root, execute))
    return rows


def protected_large_audit(repo_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    candidates = [repo_root / r for r in sorted(PROTECTED_LARGE_REL)]
    candidates.extend(sorted((repo_root / "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/canonical_backups").glob("*.csv")))
    candidates.extend(sorted((repo_root / "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME").glob("moomoo_daily_ohlcv_*.csv")))
    seen: set[str] = set()
    for p in candidates:
        key = str(p)
        if key in seen or not p.exists() or not p.is_file():
            continue
        seen.add(key)
        rows.append({"path": str(p), "relative_path": rel(p, repo_root), "size_bytes": p.stat().st_size, "protected_reason": protected_reason(p, repo_root) or "EXPLICIT_PROTECTED_LARGE_FILE", "notes": "audit only; not archived in V21.238"})
    return rows


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
    allow_v21_229_extra_inventory_archive: bool,
    allow_v20_history_archive: bool,
    allow_legacy_state_cache_archive: bool,
    legacy_cache_min_mb: float,
    v20_history_min_mb: float,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    archive_root = archive_root.resolve()
    cache_root = cache_root.resolve()
    quarantine_root = quarantine_root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    before_bytes, before_count = repo_stats(repo_root)
    top_before = top_size(repo_root, top_size_count)
    ref_text = load_active_reference_text(repo_root)
    skipped: list[dict[str, Any]] = []
    inventory_rows = phase_extra_inventory(repo_root, archive_root, execute, allow_v21_229_extra_inventory_archive, ref_text, skipped)
    v20_rows = phase_v20_history(repo_root, archive_root, execute, allow_v20_history_archive, v20_history_min_mb, ref_text, skipped)
    legacy_rows = phase_legacy_cache(repo_root, archive_root, execute, allow_legacy_state_cache_archive, legacy_cache_min_mb, ref_text, skipped)
    protected_rows = protected_large_audit(repo_root)
    after_bytes, after_count = repo_stats(repo_root)
    top_after = top_size(repo_root, top_size_count)

    manifest_fields = ["relative_path", "original_size_bytes", "original_sha256", "archive_gzip_path", "archive_gzip_size_bytes", "archive_gzip_sha256", "decompressed_sha256_verified", "deleted_from_repo", "dry_run", "error"]
    write_csv(output_dir / "v21_238_v21_229_extra_inventory_archived_manifest.csv", inventory_rows, manifest_fields)
    write_csv(output_dir / "v21_238_v20_history_archived_manifest.csv", v20_rows, manifest_fields)
    write_csv(output_dir / "v21_238_legacy_state_cache_archived_manifest.csv", legacy_rows, manifest_fields)
    write_csv(output_dir / "v21_238_skipped_blockers.csv", skipped, ["path", "relative_path", "size_bytes", "blocker_type", "phase", "notes"])
    write_csv(output_dir / "v21_238_protected_large_files_audit.csv", protected_rows, ["path", "relative_path", "size_bytes", "protected_reason", "notes"])
    write_csv(output_dir / "v21_238_top_size_before.csv", top_before, ["path", "relative_path", "size_bytes", "size_mb"])
    write_csv(output_dir / "v21_238_top_size_after.csv", top_after, ["path", "relative_path", "size_bytes", "size_mb"])
    pointers = pointer_rows(inventory_rows, v20_rows, legacy_rows)
    write_json(output_dir / "v21_238_pointer_manifest.json", {"policy_version": "V21.238", "created_at_utc": utc_now(), "archive_stage_root": str(archive_root / ARCHIVE_STAGE), "pointers": pointers})

    all_rows = inventory_rows + v20_rows + legacy_rows
    verification_failed_count = sum(1 for r in all_rows if r.get("error") or (execute and not r.get("decompressed_sha256_verified")))
    deleted_without_verify = sum(1 for r in all_rows if r.get("deleted_from_repo") and not r.get("decompressed_sha256_verified"))
    error_count = verification_failed_count + deleted_without_verify
    deleted_inventory = [r for r in inventory_rows if r.get("deleted_from_repo")]
    deleted_v20 = [r for r in v20_rows if r.get("deleted_from_repo")]
    deleted_legacy = [r for r in legacy_rows if r.get("deleted_from_repo")]
    deleted_rows = deleted_inventory + deleted_v20 + deleted_legacy
    original_removed = sum(int(r["original_size_bytes"]) for r in deleted_rows)
    gzip_added = sum(int(r["archive_gzip_size_bytes"]) for r in deleted_rows)
    reduced = before_bytes - after_bytes
    target_met = reduced >= min_target_mb * 1024 * 1024
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
        "v21_229_extra_inventory_archived_count": len(deleted_inventory),
        "v21_229_extra_inventory_original_bytes": sum(int(r["original_size_bytes"]) for r in deleted_inventory),
        "v21_229_extra_inventory_gzip_bytes": sum(int(r["archive_gzip_size_bytes"]) for r in deleted_inventory),
        "v20_history_archived_count": len(deleted_v20),
        "v20_history_original_bytes": sum(int(r["original_size_bytes"]) for r in deleted_v20),
        "v20_history_gzip_bytes": sum(int(r["archive_gzip_size_bytes"]) for r in deleted_v20),
        "legacy_state_cache_archived_count": len(deleted_legacy),
        "legacy_state_cache_original_bytes": sum(int(r["original_size_bytes"]) for r in deleted_legacy),
        "legacy_state_cache_gzip_bytes": sum(int(r["archive_gzip_size_bytes"]) for r in deleted_legacy),
        "total_original_bytes_removed_from_repo": original_removed,
        "total_gzip_bytes_added_to_archive": gzip_added,
        "estimated_net_disk_reduction_bytes": original_removed - gzip_added,
        "estimated_net_disk_reduction_mb": round((original_removed - gzip_added) / 1024 / 1024, 3),
        "protected_large_file_count": len(protected_rows),
        "protected_large_file_bytes": sum(int(r["size_bytes"]) for r in protected_rows),
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
    write_json(output_dir / "v21_238_summary.json", summary)
    report = "\n".join([
        STAGE,
        f"final_status={final_status}",
        f"final_decision={DECISION}",
        f"repo_size_reduced_mb={summary['repo_size_reduced_mb']}",
        f"v21_229_extra_inventory_archived_count={summary['v21_229_extra_inventory_archived_count']}",
        f"v20_history_archived_count={summary['v20_history_archived_count']}",
        f"legacy_state_cache_archived_count={summary['legacy_state_cache_archived_count']}",
        f"estimated_net_disk_reduction_mb={summary['estimated_net_disk_reduction_mb']}",
        "market_data_fetch_performed=False",
        "broker_action_allowed=False",
        "official_adoption_allowed=False",
    ]) + "\n"
    (output_dir / "V21.238_final_lightweight_repo_pass_report.txt").write_text(report, encoding="utf-8")
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
    parser.add_argument("--min-target-mb", type=float, default=150.0)
    parser.add_argument("--top-size", type=int, default=300)
    parser.add_argument("--allow-v21-229-extra-inventory-archive", action="store_true", default=False)
    parser.add_argument("--allow-v20-history-archive", action="store_true", default=False)
    parser.add_argument("--allow-legacy-state-cache-archive", action="store_true", default=False)
    parser.add_argument("--legacy-cache-min-mb", type=float, default=1.0)
    parser.add_argument("--v20-history-min-mb", type=float, default=3.0)
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
        allow_v21_229_extra_inventory_archive=args.allow_v21_229_extra_inventory_archive,
        allow_v20_history_archive=args.allow_v20_history_archive,
        allow_legacy_state_cache_archive=args.allow_legacy_state_cache_archive,
        legacy_cache_min_mb=args.legacy_cache_min_mb,
        v20_history_min_mb=args.v20_history_min_mb,
    )
    print(str(out / "v21_238_summary.json"))
    return 1 if summary["final_status"] == FAIL_STATUS else 0


if __name__ == "__main__":
    raise SystemExit(main())
