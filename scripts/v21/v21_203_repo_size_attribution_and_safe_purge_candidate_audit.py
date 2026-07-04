#!/usr/bin/env python
"""V21.203 repo size attribution and safe purge candidate audit.

Audit-only: no deletion, movement, compression, price refresh, adoption, or
broker action. The only writes are this stage's own output artifacts.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOT = Path(r"D:\us-tech-quant")
STAGE = "V21.203_REPO_SIZE_ATTRIBUTION_AND_SAFE_PURGE_CANDIDATE_AUDIT"
OUT_REL = Path("outputs/v21/V21.203_REPO_SIZE_ATTRIBUTION_AND_SAFE_PURGE_CANDIDATE_AUDIT")
PROTECTED_REQUIRED = [
    ".venv",
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
    "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "outputs/v21/V21.201_DRAM_MOOMOO_R4_PLAN_READY",
    "outputs/v21/V21.202_REPO_SAFE_CLEANUP_AUDIT_AND_CACHE_PURGE",
]
PROTECTED_PREFIXES = [
    ".venv",
    "data",
    "outputs/v20/price_history",
    "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "outputs/v21/V21.201_DRAM_MOOMOO_R4_PLAN_READY",
    "outputs/v21/V21.202_REPO_SAFE_CLEANUP_AUDIT_AND_CACHE_PURGE",
    "outputs/v21/FULL_SYSTEM_LATEST_RERUN",
]
PROTECTED_TOKENS = [
    "trade plan",
    "trade_plan",
    "canonical",
    "ledger",
    "ranking",
    "summary",
    "report",
    "price_history",
    "ohlcv",
    "kline",
    "moomoo",
    "abcde",
    "dram",
    "protected",
]
TOP_FIELDS = ["path", "size_bytes", "size_mb", "file_count", "dir_count", "latest_modified_utc"]
FILE_FIELDS = ["path", "size_bytes", "size_mb", "latest_modified_utc"]
STAGE_FIELDS = ["stage_name", "path", "size_bytes", "size_mb", "file_count", "dir_count", "latest_modified_utc", "protected_status"]
PURGE_FIELDS = ["path", "candidate_type", "size_bytes", "file_count", "protected_status", "audit_action", "reason"]
PRESENCE_FIELDS = [
    "protected_key",
    "expected_path",
    "exact_exists",
    "alias_discovery_attempted",
    "alias_candidate_count",
    "resolved_exists",
    "resolved_protected_path",
    "resolution_method",
    "warning_reason",
    "size_bytes",
    "file_count",
    "alias_candidates",
]


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/")


def norm_rel(path: Path, root: Path) -> str:
    return rel(path, root).lower()


def utc_mtime(path: Path) -> str:
    try:
        ts = path.stat().st_mtime
    except OSError:
        return ""
    return datetime.fromtimestamp(ts, timezone.utc).replace(microsecond=0).isoformat()


def tree_metrics(path: Path) -> tuple[int, int, int, str]:
    if not path.exists():
        return 0, 0, 0, ""
    if path.is_file():
        try:
            return path.stat().st_size, 1, 0, utc_mtime(path)
        except OSError:
            return 0, 0, 0, ""
    size = 0
    files = 0
    dirs = 0
    latest = 0.0
    try:
        for child in path.rglob("*"):
            try:
                stat = child.stat()
                latest = max(latest, stat.st_mtime)
                if child.is_file():
                    size += stat.st_size
                    files += 1
                elif child.is_dir():
                    dirs += 1
            except OSError:
                continue
    except OSError:
        pass
    latest_str = datetime.fromtimestamp(latest, timezone.utc).replace(microsecond=0).isoformat() if latest else ""
    return size, files, dirs, latest_str


def bytes_mb(size: int) -> float:
    return round(size / 1024 / 1024, 3)


def is_cache_or_temp_path(path: Path) -> bool:
    name = path.name.lower()
    if name in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".ipynb_checkpoints"}:
        return True
    if name == "pytest_tmp" or name.startswith("pytest_tmp_"):
        return True
    if "pytest" in name and "tmp" in name and path.is_dir():
        return True
    return False


def is_zero_byte_orphan_temp(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.suffix.lower() not in {".tmp", ".temp"}:
        return False
    try:
        return path.stat().st_size == 0
    except OSError:
        return False


def is_protected_path(path: Path, root: Path) -> tuple[bool, str]:
    r = norm_rel(path, root)
    name = path.name.lower()
    for prefix in PROTECTED_PREFIXES:
        p = prefix.lower()
        if r == p or r.startswith(p + "/") or r.startswith(p):
            return True, f"protected_prefix:{prefix}"
    if any(token in name for token in PROTECTED_TOKENS) and not is_cache_or_temp_path(path):
        return True, "protected_name_token"
    return False, ""


def repo_totals(root: Path) -> dict[str, Any]:
    total = 0
    files = 0
    dirs = 0
    for child in root.rglob("*"):
        try:
            if child.is_file():
                total += child.stat().st_size
                files += 1
            elif child.is_dir():
                dirs += 1
        except OSError:
            continue
    return {"total_size_bytes": total, "total_file_count": files, "total_directory_count": dirs}


def top_level_summary(root: Path) -> list[dict[str, Any]]:
    rows = []
    for child in root.iterdir():
        size, files, dirs, latest = tree_metrics(child)
        rows.append({
            "path": rel(child, root),
            "size_bytes": size,
            "size_mb": bytes_mb(size),
            "file_count": files,
            "dir_count": dirs,
            "latest_modified_utc": latest,
        })
    return sorted(rows, key=lambda r: int(r["size_bytes"]), reverse=True)


def largest_directories(root: Path, limit: int = 200) -> list[dict[str, Any]]:
    rows = []
    for child in root.rglob("*"):
        try:
            if child.is_dir():
                size, files, dirs, latest = tree_metrics(child)
                rows.append({
                    "path": rel(child, root),
                    "size_bytes": size,
                    "size_mb": bytes_mb(size),
                    "file_count": files,
                    "dir_count": dirs,
                    "latest_modified_utc": latest,
                })
        except OSError:
            continue
    return sorted(rows, key=lambda r: int(r["size_bytes"]), reverse=True)[:limit]


def largest_files(root: Path, limit: int = 200) -> list[dict[str, Any]]:
    rows = []
    for child in root.rglob("*"):
        try:
            if child.is_file():
                size = child.stat().st_size
                rows.append({
                    "path": rel(child, root),
                    "size_bytes": size,
                    "size_mb": bytes_mb(size),
                    "latest_modified_utc": utc_mtime(child),
                })
        except OSError:
            continue
    return sorted(rows, key=lambda r: int(r["size_bytes"]), reverse=True)[:limit]


def outputs_v21_stage_summary(root: Path) -> list[dict[str, Any]]:
    out21 = root / "outputs/v21"
    rows = []
    if not out21.exists():
        return rows
    for child in out21.iterdir():
        if not child.is_dir():
            continue
        protected, reason = is_protected_path(child, root)
        size, files, dirs, latest = tree_metrics(child)
        rows.append({
            "stage_name": child.name,
            "path": rel(child, root),
            "size_bytes": size,
            "size_mb": bytes_mb(size),
            "file_count": files,
            "dir_count": dirs,
            "latest_modified_utc": latest,
            "protected_status": reason if protected else "not_protected",
        })
    return sorted(rows, key=lambda r: int(r["size_bytes"]), reverse=True)


def candidate_type(path: Path) -> str | None:
    name = path.name.lower()
    if name == "__pycache__":
        return "__pycache__"
    if name == ".pytest_cache":
        return ".pytest_cache"
    if name == ".mypy_cache":
        return ".mypy_cache"
    if name == ".ruff_cache":
        return ".ruff_cache"
    if name == ".ipynb_checkpoints":
        return ".ipynb_checkpoints"
    if name == "pytest_tmp" or name.startswith("pytest_tmp_"):
        return "pytest_tmp"
    if "pytest" in name and "tmp" in name and path.is_dir():
        return "explicit_pytest_tmp_named_dir"
    if is_zero_byte_orphan_temp(path):
        return "zero_byte_orphan_temp_file"
    return None


def safe_purge_candidate_audit(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in root.rglob("*"):
        try:
            ctype = candidate_type(path)
        except OSError:
            continue
        if not ctype:
            continue
        protected, reason = is_protected_path(path, root)
        if protected:
            continue
        if norm_rel(path, root) == ".venv" or norm_rel(path, root).startswith(".venv/"):
            continue
        size, files, _dirs, _latest = tree_metrics(path)
        rows.append({
            "path": rel(path, root),
            "candidate_type": ctype,
            "size_bytes": size,
            "file_count": files,
            "protected_status": "not_protected",
            "audit_action": "AUDIT_ONLY_NO_DELETE",
            "reason": "clearly_disposable_cache_or_temp_artifact",
        })
    return sorted(rows, key=lambda r: int(r["size_bytes"]), reverse=True)


def protected_presence(root: Path) -> list[dict[str, Any]]:
    rows = []
    for item in PROTECTED_REQUIRED:
        path = root / item
        exact_exists = path.exists()
        alias_attempted = False
        candidates: list[Path] = []
        resolved = path if exact_exists else None
        method = "EXACT_PATH" if exact_exists else "UNRESOLVED"
        warning = "" if exact_exists else "EXPECTED_PATH_MISSING"
        if not exact_exists and item.startswith("outputs/v21/V21."):
            alias_attempted = True
            stage_id = Path(item).name.split("_", 1)[0]
            candidates = protected_alias_candidates(root, stage_id)
            if candidates:
                resolved = newest_path(candidates)
                method = "ALIAS_DISCOVERY_NEWEST_MODIFIED"
                warning = ""
        size, files, _dirs, _latest = tree_metrics(resolved) if resolved else (0, 0, 0, "")
        rows.append({
            "protected_key": Path(item).name,
            "expected_path": item,
            "exact_exists": exact_exists,
            "alias_discovery_attempted": alias_attempted,
            "alias_candidate_count": len(candidates),
            "resolved_exists": bool(resolved and resolved.exists()),
            "resolved_protected_path": rel(resolved, root) if resolved else "",
            "resolution_method": method,
            "warning_reason": warning,
            "size_bytes": size,
            "file_count": files,
            "alias_candidates": "|".join(rel(candidate, root) for candidate in candidates),
        })
    return rows


def protected_alias_candidates(root: Path, stage_id: str) -> list[Path]:
    out21 = root / "outputs/v21"
    if not out21.exists():
        return []
    candidates: list[Path] = []
    for child in out21.iterdir():
        if not child.is_dir() or not child.name.startswith(stage_id):
            continue
        if stage_id == "V21.201" and not v21_201_alias_is_current_chain(child):
            continue
        candidates.append(child)
    return sorted(candidates, key=lambda path: rel(path, root))


def v21_201_alias_is_current_chain(path: Path) -> bool:
    tokens = {"dram", "moomoo", "plan", "r4", "daily"}
    name = path.name.lower()
    if any(token in name for token in tokens):
        return True
    try:
        for child in path.rglob("*"):
            text = child.name.lower()
            if any(token in text for token in tokens):
                return True
    except OSError:
        return False
    return False


def newest_path(paths: list[Path]) -> Path:
    return max(paths, key=lambda path: path.stat().st_mtime if path.exists() else 0.0)


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


def write_report(path: Path, summary: dict[str, Any], top: list[dict[str, Any]], stages: list[dict[str, Any]], candidates: list[dict[str, Any]], presence: list[dict[str, Any]]) -> None:
    missing = [row for row in presence if not row["resolved_exists"]]
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"repo_total_size_bytes={summary['repo_total_size_bytes']}",
        f"repo_total_file_count={summary['repo_total_file_count']}",
        f"repo_total_directory_count={summary['repo_total_directory_count']}",
        f"safe_purge_candidate_count={summary['safe_purge_candidate_count']}",
        f"protected_missing_expected_count={summary['protected_missing_expected_count']}",
        f"protected_missing_after_alias_resolution_count={summary['protected_missing_after_alias_resolution_count']}",
        f"protected_alias_resolved_count={summary['protected_alias_resolved_count']}",
        "research_only=true",
        "mutation_allowed=false",
        "deletion_performed=false",
        "broker_action_allowed=false",
        "official_adoption_allowed=false",
        "protected_outputs_modified=false",
        "",
        "top_level_size_summary:",
    ]
    lines.extend([f"- {row['path']} size_bytes={row['size_bytes']} files={row['file_count']}" for row in top[:20]])
    lines.extend(["", "largest_outputs_v21_stages:"])
    lines.extend([f"- {row['stage_name']} size_bytes={row['size_bytes']} files={row['file_count']} protected={row['protected_status']}" for row in stages[:20]])
    lines.extend(["", "safe_purge_candidate_preview:"])
    lines.extend([f"- {row['path']} type={row['candidate_type']} size_bytes={row['size_bytes']}" for row in candidates[:20]])
    lines.extend(["", "protected_path_presence:"])
    lines.extend([f"- {row['expected_path']} exact_exists={row['exact_exists']} resolved_exists={row['resolved_exists']} resolved={row['resolved_protected_path']} method={row['resolution_method']}" for row in presence])
    if missing:
        lines.extend(["", "missing_protected_paths:"])
        lines.extend([f"- {row['expected_path']}" for row in missing])
    lines.append("")
    lines.append("next_recommended_action=Review safe_purge_candidate_audit.csv and archive strategy separately; no mutation was performed by V21.203.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(repo_root: Path = DEFAULT_ROOT, out_dir: Path | None = None, simulate_exception: bool = False) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if simulate_exception:
            raise RuntimeError("simulated audit failure")
        if not root.exists() or not root.is_dir():
            raise RuntimeError(f"invalid repo root: {root}")
        totals = repo_totals(root)
        top_rows = top_level_summary(root)
        dir_rows = largest_directories(root)
        file_rows = largest_files(root)
        stage_rows = outputs_v21_stage_summary(root)
        candidate_rows = safe_purge_candidate_audit(root)
        presence_rows = protected_presence(root)
        missing_expected = [row for row in presence_rows if not row["exact_exists"]]
        missing_after_alias = [row for row in presence_rows if not row["resolved_exists"]]
        alias_resolved = [row for row in presence_rows if not row["exact_exists"] and row["resolved_exists"]]
        if missing_after_alias:
            final_status = "WARN_V21_203_PROTECTED_PATH_MISSING"
            final_decision = "REPO_SIZE_ATTRIBUTION_WARN_PROTECTED_PATH_MISSING"
        else:
            final_status = "PASS_V21_203_REPO_SIZE_ATTRIBUTION_READY"
            final_decision = "REPO_SIZE_ATTRIBUTION_READY_NO_MUTATION"
        summary = {
            "stage": STAGE,
            "final_status": final_status,
            "final_decision": final_decision,
            "repo_root": str(root),
            "repo_total_size_bytes": int(totals["total_size_bytes"]),
            "repo_total_file_count": int(totals["total_file_count"]),
            "repo_total_directory_count": int(totals["total_directory_count"]),
            "top_level_entry_count": len(top_rows),
            "largest_directory_rows": len(dir_rows),
            "largest_file_rows": len(file_rows),
            "outputs_v21_stage_count": len(stage_rows),
            "safe_purge_candidate_count": len(candidate_rows),
            "safe_purge_candidate_size_bytes": sum(int(row["size_bytes"]) for row in candidate_rows),
            "protected_missing_count": len(missing_after_alias),
            "protected_missing_expected_count": len(missing_expected),
            "protected_missing_after_alias_resolution_count": len(missing_after_alias),
            "protected_alias_resolved_count": len(alias_resolved),
            "protected_alias_resolution_used": bool(alias_resolved),
            "research_only": True,
            "mutation_allowed": False,
            "deletion_performed": False,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "protected_outputs_modified": False,
        }
        write_csv(output / "repo_top_level_size_summary.csv", top_rows, TOP_FIELDS)
        write_csv(output / "repo_largest_directories.csv", dir_rows, TOP_FIELDS)
        write_csv(output / "repo_largest_files.csv", file_rows, FILE_FIELDS)
        write_csv(output / "outputs_v21_stage_size_summary.csv", stage_rows, STAGE_FIELDS)
        write_csv(output / "safe_purge_candidate_audit.csv", candidate_rows, PURGE_FIELDS)
        write_csv(output / "protected_path_presence_check.csv", presence_rows, PRESENCE_FIELDS)
        write_json(output / "v21_203_summary.json", summary)
        write_report(output / "V21.203_repo_size_attribution_report.txt", summary, top_rows, stage_rows, candidate_rows, presence_rows)
    except Exception as exc:
        summary = {
            "stage": STAGE,
            "final_status": "FAIL_V21_203_AUDIT_EXCEPTION",
            "final_decision": "REPO_SIZE_ATTRIBUTION_FAILED",
            "repo_root": str(root),
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "research_only": True,
            "mutation_allowed": False,
            "deletion_performed": False,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "protected_outputs_modified": False,
        }
        write_json(output / "v21_203_summary.json", summary)
        (output / "V21.203_repo_size_attribution_report.txt").write_text(
            "\n".join([STAGE, f"final_status={summary['final_status']}", f"final_decision={summary['final_decision']}", f"error={summary['error_type']}: {summary['error_message']}"]) + "\n",
            encoding="utf-8",
        )
    for key in ["final_status", "final_decision", "safe_purge_candidate_count", "protected_missing_after_alias_resolution_count", "deletion_performed", "broker_action_allowed"]:
        if key in summary:
            print(f"{key}={summary[key]}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", default=str(DEFAULT_ROOT))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(Path(args.repo_root))
    return 0 if str(summary["final_status"]).startswith(("PASS", "WARN")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
