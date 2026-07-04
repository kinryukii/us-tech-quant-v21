#!/usr/bin/env python
"""V21.202 safe repo cleanup audit and cache purge.

Default behavior is dry-run. Execute mode only removes Python/pytest caches and
pytest temp files explicitly allowed by the stage contract.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOT = Path(r"D:\us-tech-quant")
STAGE = "V21.202_REPO_SAFE_CLEANUP_AUDIT_AND_CACHE_PURGE"
OUT_REL = Path("outputs/v21/V21.202_REPO_SAFE_CLEANUP_AUDIT_AND_CACHE_PURGE")
PROTECTED_PREFIXES = [
    ".venv",
    "data",
    "outputs/v20/price_history",
    "outputs/v21/V21.197",
    "outputs/v21/V21.198",
    "outputs/v21/V21.199",
    "outputs/v21/V21.201",
    "outputs/v21/FULL_SYSTEM_LATEST_RERUN",
    "scripts/v21/v21_197",
    "scripts/v21/v21_198",
    "scripts/v21/v21_199",
    "scripts/v21/v21_201",
    "scripts/v21/run_daily",
]
PROTECTED_SCRIPT_NAME_TOKENS = ["moomoo", "dram", "abcde"]
PROTECTED_NAME_TOKENS = ["canonical_historical_ohlcv", "canonical_price", "broker"]
PROTECTED_NAME_TOKENS_WITH_CACHE_EXCEPTION = ["moomoo"]
SAFE_DIR_NAMES = {"__pycache__": "__pycache_dir", ".pytest_cache": "pytest_cache_dir"}
SIZE_FIELDS = ["scope", "path", "size_bytes", "size_mb", "size_gb", "file_count"]
SAFE_FIELDS = ["path", "candidate_type", "size_bytes", "file_count", "protected_status", "delete_allowed", "reason"]
LOG_FIELDS = ["path", "candidate_type", "operation", "size_bytes", "file_count", "status", "reason"]
DENIED_FIELDS = ["path", "operation", "error_type", "error_message", "attempted_execute", "recommended_manual_fix"]
ARCHIVE_FIELDS = ["path", "size_bytes", "file_count", "suggested_action", "archive_priority", "reason"]
PROTECTED_FIELDS = ["path", "protection_reason", "exists", "size_bytes", "file_count"]


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/")


def norm_rel(path: Path, root: Path) -> str:
    return rel(path, root).lower()


def is_relative_to_path(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def within_venv(path: Path, root: Path) -> bool:
    return norm_rel(path, root) == ".venv" or norm_rel(path, root).startswith(".venv/")


def is_cache_artifact(path: Path) -> bool:
    name = path.name.lower()
    return name in SAFE_DIR_NAMES or name.startswith("pytest_tmp") or path.suffix.lower() in {".pyc", ".pyo"}


def is_protected_path(path: Path, root: Path) -> tuple[bool, str]:
    r = norm_rel(path, root)
    name = path.name.lower()
    for prefix in PROTECTED_PREFIXES:
        p = prefix.lower()
        wildcard_prefix = any(p.endswith(token) for token in ["v21.197", "v21.198", "v21.199", "v21.201", "full_system_latest_rerun", "v21_197", "v21_198", "v21_199", "v21_201", "run_daily"])
        if r == p or r.startswith(p + "/") or (wildcard_prefix and r.startswith(p)):
            return True, f"protected_prefix:{prefix}"
    if r.startswith("scripts/v21/") and any(token in name for token in PROTECTED_SCRIPT_NAME_TOKENS):
        return True, "protected_current_chain_script_name"
    if any(token in name for token in PROTECTED_NAME_TOKENS):
        return True, "protected_name_token"
    if any(token in name for token in PROTECTED_NAME_TOKENS_WITH_CACHE_EXCEPTION) and not is_cache_artifact(path):
        return True, "protected_moomoo_name"
    return False, ""


def file_stat(path: Path) -> tuple[int, int]:
    try:
        if path.is_file():
            return path.stat().st_size, 1
    except OSError:
        return 0, 0
    return 0, 0


def tree_size(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    if path.is_file():
        return file_stat(path)
    total = 0
    count = 0
    try:
        iterator = path.rglob("*")
        for child in iterator:
            try:
                if child.is_file():
                    total += child.stat().st_size
                    count += 1
            except OSError:
                continue
    except OSError:
        return total, count
    return total, count


def size_row(scope: str, path: Path, root: Path) -> dict[str, Any]:
    size, files = tree_size(path)
    return {
        "scope": scope,
        "path": rel(path, root),
        "size_bytes": size,
        "size_mb": round(size / 1024 / 1024, 3),
        "size_gb": round(size / 1024 / 1024 / 1024, 6),
        "file_count": files,
    }


def repo_total(root: Path, include_venv: bool) -> tuple[int, int]:
    total = 0
    count = 0
    for child in root.rglob("*"):
        try:
            if not include_venv and within_venv(child, root):
                continue
            if child.is_file():
                total += child.stat().st_size
                count += 1
        except OSError:
            continue
    return total, count


def repo_size_summary(root: Path, include_venv: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total, files = repo_total(root, include_venv)
    rows.append({
        "scope": "repo_root_total_excluding_venv" if not include_venv else "repo_root_total_including_venv",
        "path": ".",
        "size_bytes": total,
        "size_mb": round(total / 1024 / 1024, 3),
        "size_gb": round(total / 1024 / 1024 / 1024, 6),
        "file_count": files,
    })
    for scope, sub in [
        (".venv", ".venv"),
        ("outputs", "outputs"),
        ("outputs/v20", "outputs/v20"),
        ("outputs/v21", "outputs/v21"),
        ("scripts", "scripts"),
        ("scripts/v21", "scripts/v21"),
        ("data", "data"),
        (".pytest_cache", ".pytest_cache"),
    ]:
        rows.append(size_row(scope, root / sub, root))
    out21 = root / "outputs/v21"
    if out21.exists():
        for child in sorted([p for p in out21.iterdir() if p.is_dir()], key=lambda p: tree_size(p)[0], reverse=True):
            rows.append(size_row("outputs/v21_child", child, root))
    return rows


def candidate_type(path: Path, root: Path) -> str | None:
    name = path.name
    lower = name.lower()
    if path.is_dir():
        if lower in SAFE_DIR_NAMES:
            return SAFE_DIR_NAMES[lower]
        if lower == "pytest_tmp" or lower.startswith("pytest_tmp_"):
            return "pytest_tmp_dir"
        return None
    suffix = path.suffix.lower()
    if suffix == ".pyc":
        return "pyc_file"
    if suffix == ".pyo":
        return "pyo_file"
    if suffix == ".tmp" and is_pytest_tmp_under_outputs_v21(path, root):
        return "tmp_file_inside_pytest_tmp"
    return None


def is_pytest_tmp_under_outputs_v21(path: Path, root: Path) -> bool:
    try:
        parts = path.resolve().relative_to((root / "outputs/v21").resolve()).parts
    except ValueError:
        return False
    return any(part == "pytest_tmp" or part.startswith("pytest_tmp_") for part in parts)


def safe_delete_candidates(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in root.rglob("*"):
        try:
            ctype = candidate_type(path, root)
        except OSError:
            continue
        if not ctype:
            continue
        protected, reason = is_protected_path(path, root)
        size, files = tree_size(path)
        allowed = not within_venv(path, root)
        if ctype == "tmp_file_inside_pytest_tmp":
            allowed = allowed and is_pytest_tmp_under_outputs_v21(path, root)
        if protected and not is_cache_artifact(path):
            allowed = False
        if protected and is_cache_artifact(path) and not within_venv(path, root):
            allowed = True
        rows.append({
            "path": rel(path, root),
            "candidate_type": ctype,
            "size_bytes": size,
            "file_count": files,
            "protected_status": reason if protected else "not_protected",
            "delete_allowed": bool(allowed),
            "reason": "SAFE_CACHE_TEMP_DELETE_ALLOWED" if allowed else "BLOCKED_BY_PROTECTION_OR_SCOPE",
        })
    return sorted(rows, key=lambda r: (not bool(r["delete_allowed"]), str(r["path"])))


def ensure_delete_allowed(candidate: dict[str, Any], root: Path) -> None:
    path = root / str(candidate["path"])
    protected, reason = is_protected_path(path, root)
    if protected and not is_cache_artifact(path):
        raise RuntimeError(f"protected path deletion attempt blocked: {candidate['path']} ({reason})")
    if not bool(candidate.get("delete_allowed")):
        raise RuntimeError(f"delete not allowed: {candidate['path']}")
    if within_venv(path, root):
        raise RuntimeError(f".venv deletion attempt blocked: {candidate['path']}")


def delete_candidate(candidate: dict[str, Any], root: Path, execute: bool) -> tuple[dict[str, Any], dict[str, Any] | None]:
    path = root / str(candidate["path"])
    ensure_delete_allowed(candidate, root)
    op = "delete_dir" if path.is_dir() else "delete_file"
    if not execute:
        return {
            "path": candidate["path"],
            "candidate_type": candidate["candidate_type"],
            "operation": op,
            "size_bytes": candidate["size_bytes"],
            "file_count": candidate["file_count"],
            "status": "DRY_RUN_SKIPPED",
            "reason": "execute_false",
        }, None
    if not path.exists():
        return {
            "path": candidate["path"],
            "candidate_type": candidate["candidate_type"],
            "operation": op,
            "size_bytes": candidate["size_bytes"],
            "file_count": candidate["file_count"],
            "status": "SKIPPED_ALREADY_REMOVED",
            "reason": "path_missing",
        }, None
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return {
            "path": candidate["path"],
            "candidate_type": candidate["candidate_type"],
            "operation": op,
            "size_bytes": candidate["size_bytes"],
            "file_count": candidate["file_count"],
            "status": "DELETED",
            "reason": "safe_cache_temp_purge",
        }, None
    except (PermissionError, OSError) as exc:
        denied = {
            "path": candidate["path"],
            "operation": op,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "attempted_execute": bool(execute),
            "recommended_manual_fix": "Close processes holding the file or remove manually after verifying it is cache/temp only.",
        }
        log = {
            "path": candidate["path"],
            "candidate_type": candidate["candidate_type"],
            "operation": op,
            "size_bytes": candidate["size_bytes"],
            "file_count": candidate["file_count"],
            "status": "ACCESS_DENIED_SKIPPED",
            "reason": type(exc).__name__,
        }
        return log, denied


def execute_deletions(candidates: list[dict[str, Any]], root: Path, execute: bool, max_delete_gb: float | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    allowed = [c for c in candidates if bool(c["delete_allowed"])]
    total = sum(int(c["size_bytes"]) for c in allowed)
    if execute and max_delete_gb is not None and total > max_delete_gb * 1024 * 1024 * 1024:
        raise RuntimeError("safe delete candidate size exceeds --max-delete-gb")
    logs: list[dict[str, Any]] = []
    denied: list[dict[str, Any]] = []
    for candidate in sorted(allowed, key=lambda c: (str(c["candidate_type"]).endswith("_file"), str(c["path"]).count("/"))):
        log, access = delete_candidate(candidate, root, execute)
        logs.append(log)
        if access:
            denied.append(access)
    return logs, denied


def archive_candidates(root: Path) -> list[dict[str, Any]]:
    out21 = root / "outputs/v21"
    rows: list[dict[str, Any]] = []
    if not out21.exists():
        return rows
    for child in out21.iterdir():
        if not child.is_dir() or not child.name.startswith("V21."):
            continue
        protected, reason = is_protected_path(child, root)
        if protected:
            continue
        size, files = tree_size(child)
        priority = "HIGH" if size >= 1024 * 1024 * 1024 or files >= 5000 else "MEDIUM" if size >= 100 * 1024 * 1024 or files >= 500 else "LOW"
        rows.append({
            "path": rel(child, root),
            "size_bytes": size,
            "file_count": files,
            "suggested_action": "ARCHIVE_ONLY_DO_NOT_DELETE",
            "archive_priority": priority,
            "reason": "unprotected_historical_v21_research_output_not_current_chain",
        })
    return sorted(rows, key=lambda r: int(r["size_bytes"]), reverse=True)


def protected_manifest(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    probes = [root / p for p in PROTECTED_PREFIXES]
    probes.extend(root.glob("scripts/v21/*moomoo*"))
    probes.extend(root.glob("scripts/v21/*dram*"))
    probes.extend(root.glob("scripts/v21/*abcde*"))
    for path in root.rglob("*"):
        name = path.name.lower()
        if any(token in name for token in PROTECTED_NAME_TOKENS + PROTECTED_NAME_TOKENS_WITH_CACHE_EXCEPTION):
            probes.append(path)
    for path in probes:
        key = rel(path, root)
        if key in seen:
            continue
        seen.add(key)
        protected, reason = is_protected_path(path, root)
        size, files = tree_size(path)
        rows.append({
            "path": key,
            "protection_reason": reason or "protected_pattern_probe",
            "exists": path.exists(),
            "size_bytes": size,
            "file_count": files,
        })
    return sorted(rows, key=lambda r: str(r["path"]))


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


def write_report(path: Path, summary: dict[str, Any], size_rows: list[dict[str, Any]], candidates: list[dict[str, Any]], archive: list[dict[str, Any]], manifest: list[dict[str, Any]]) -> None:
    top = [r for r in size_rows if r["scope"] == "outputs/v21_child"][:20]
    protected_current = [r for r in manifest if any(token in str(r["path"]) for token in ["V21.197", "V21.198", "V21.199", "V21.201"])]
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"repo_total_size_before_cleanup_bytes={summary['repo_total_size_before_cleanup_bytes']}",
        f"safe_delete_candidate_total_size_bytes={summary['delete_allowed_size_bytes']}",
        f"safe_delete_candidate_total_count={summary['delete_allowed_total']}",
        f"deleted_total_size_bytes={summary['deleted_size_bytes']}",
        f"skipped_access_denied_count={summary['access_denied_total']}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "",
        "top_20_largest_outputs_v21_directories:",
    ]
    lines.extend([f"- {r['path']} size_bytes={r['size_bytes']} file_count={r['file_count']}" for r in top])
    lines.extend(["", "protected_current_chain_summary:"])
    lines.extend([f"- {r['path']} exists={r['exists']} size_bytes={r['size_bytes']} reason={r['protection_reason']}" for r in protected_current[:40]])
    lines.extend([
        "",
        f"archive_candidate_count={len(archive)}",
        f"safe_candidate_count={len(candidates)}",
        "next_recommended_action=Review cleanup_archive_candidates.csv and archive manually; do not delete protected current-chain outputs.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(repo_root: Path = DEFAULT_ROOT, execute: bool = False, include_venv: bool = False, max_delete_gb: float | None = None) -> dict[str, Any]:
    root = repo_root.resolve()
    if not root.exists() or not root.is_dir():
        raise RuntimeError(f"invalid repo root: {root}")
    out_dir = root / OUT_REL
    out_dir.mkdir(parents=True, exist_ok=True)
    size_rows = repo_size_summary(root, include_venv=include_venv)
    candidates = safe_delete_candidates(root)
    archive = archive_candidates(root)
    manifest = protected_manifest(root)
    logs, denied = execute_deletions(candidates, root, execute=execute, max_delete_gb=max_delete_gb)
    allowed = [c for c in candidates if bool(c["delete_allowed"])]
    deleted = [row for row in logs if row["status"] == "DELETED"]
    repo_total = next((r for r in size_rows if r["path"] == "."), {"size_bytes": 0, "file_count": 0})
    if not execute:
        final_status = "PASS_V21_202_DRY_RUN_CLEANUP_PLAN_READY"
        final_decision = "REVIEW_PLAN_BEFORE_OPTIONAL_CACHE_PURGE"
    elif denied:
        final_status = "WARN_V21_202_CACHE_PURGE_PARTIAL_ACCESS_DENIED"
        final_decision = "CACHE_PURGE_EXECUTED_WITH_ACCESS_DENIED_SKIPS"
    else:
        final_status = "PASS_V21_202_CACHE_PURGE_EXECUTED_WITH_AUDIT"
        final_decision = "CACHE_PURGE_EXECUTED_RESEARCH_INFRA_ONLY"
    summary = {
        "stage": STAGE,
        "final_status": final_status,
        "final_decision": final_decision,
        "repo_root": str(root),
        "execute": bool(execute),
        "include_venv": bool(include_venv),
        "repo_total_size_before_cleanup_bytes": int(repo_total["size_bytes"]),
        "repo_total_file_count_before_cleanup": int(repo_total["file_count"]),
        "safe_delete_candidate_total": len(candidates),
        "delete_allowed_total": len(allowed),
        "delete_allowed_size_bytes": sum(int(c["size_bytes"]) for c in allowed),
        "deleted_total": len(deleted),
        "deleted_size_bytes": sum(int(c["size_bytes"]) for c in deleted),
        "access_denied_total": len(denied),
        "archive_candidate_total": len(archive),
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
    }
    write_csv(out_dir / "repo_size_summary.csv", size_rows, SIZE_FIELDS)
    write_csv(out_dir / "cleanup_safe_delete_candidates.csv", candidates, SAFE_FIELDS)
    write_csv(out_dir / "cleanup_deleted_or_skipped_log.csv", logs, LOG_FIELDS)
    write_csv(out_dir / "cleanup_access_denied_log.csv", denied, DENIED_FIELDS)
    write_csv(out_dir / "cleanup_archive_candidates.csv", archive, ARCHIVE_FIELDS)
    write_csv(out_dir / "cleanup_protected_manifest.csv", manifest, PROTECTED_FIELDS)
    write_json(out_dir / "v21_202_summary.json", summary)
    write_report(out_dir / "V21.202_repo_safe_cleanup_report.txt", summary, size_rows, candidates, archive, manifest)
    for key in ["final_status", "final_decision", "execute", "delete_allowed_total", "deleted_total", "access_denied_total", "broker_action_allowed"]:
        print(f"{key}={summary[key]}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", default=str(DEFAULT_ROOT))
    parser.add_argument("--execute", action="store_true", default=False)
    parser.add_argument("--include-venv", action="store_true", default=False)
    parser.add_argument("--max-delete-gb", type=float, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = run(Path(args.repo_root), execute=args.execute, include_venv=args.include_venv, max_delete_gb=args.max_delete_gb)
    except Exception as exc:
        print(f"final_status=FAIL_V21_202_IMPLEMENTATION_FAILURE")
        print(f"error={type(exc).__name__}: {exc}")
        return 1
    return 0 if str(summary["final_status"]).startswith(("PASS", "WARN")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
