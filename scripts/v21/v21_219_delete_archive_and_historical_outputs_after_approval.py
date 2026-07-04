#!/usr/bin/env python
"""V21.219 delete local archive and historical outputs after approval.

Aggressive repo-body shrink stage. Deletes local archive backups, old
non-current outputs/v21 stage directories, and cache/state-temp artifacts only
after exact manual approval. Protected current-chain, canonical, scripts, and
virtualenvs are hard kept.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOT = Path(r"D:\us-tech-quant")
STAGE = "V21.219_DELETE_ARCHIVE_AND_HISTORICAL_OUTPUTS_AFTER_APPROVAL"
OUT_REL = Path("outputs/v21/V21.219_DELETE_ARCHIVE_AND_HISTORICAL_OUTPUTS_AFTER_APPROVAL")
APPROVAL_PHRASE = "APPROVE_V21_219_DELETE_ARCHIVE_AND_HISTORICAL_OUTPUTS"
TARGET_REPO_SIZE_BYTES = 1_000_000_000
HARD_KEEP_OUTPUT_PREFIXES = [
    "V21.197",
    "V21.199",
    "V21.201",
    "V21.215_AGGRESSIVE_COMPACT_OUTPUT_POLICY_AND_STORAGE_BUDGET_ENFORCER",
    "V21.216_AGGRESSIVE_COMPACT_AND_DELETE_EXPANDED_OUTPUTS_AFTER_APPROVAL",
    "V21.217_GLOBAL_HISTORICAL_OUTPUT_RETENTION_PRUNE_PLAN",
    "V21.218_GLOBAL_HISTORICAL_OUTPUT_PRUNE_AFTER_APPROVAL",
    "V21.219_DELETE_ARCHIVE_AND_HISTORICAL_OUTPUTS_AFTER_APPROVAL",
]
LATEST_CURRENT_TOKENS = ["latest", "current_chain", "trade_plan", "ledger", "ranking"]
CURRENT_CHAIN_TOKENS = ["dram", "abcde", "moomoo"]
PROTECTED_REQUIRED = [
    ".venv",
    ".venv_moomoo_py312",
    "scripts",
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
    "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
    "outputs/v21/V21.215_AGGRESSIVE_COMPACT_OUTPUT_POLICY_AND_STORAGE_BUDGET_ENFORCER",
    "outputs/v21/V21.216_AGGRESSIVE_COMPACT_AND_DELETE_EXPANDED_OUTPUTS_AFTER_APPROVAL",
    "outputs/v21/V21.217_GLOBAL_HISTORICAL_OUTPUT_RETENTION_PRUNE_PLAN",
    "outputs/v21/V21.219_DELETE_ARCHIVE_AND_HISTORICAL_OUTPUTS_AFTER_APPROVAL",
]
PLAN_FIELDS = [
    "path", "path_type", "recursive_size_bytes", "file_count", "directory_count",
    "latest_modified_time", "deletion_reason", "hard_keep_overlap_flag",
    "current_chain_overlap_flag", "canonical_overlap_flag", "protected_overlap_flag",
    "deletion_allowed_after_checks",
]
KEEP_FIELDS = ["path", "keep_reason", "recursive_size_bytes", "file_count", "directory_count"]
DELETE_FIELDS = ["path", "path_type", "delete_attempted", "deleted", "deleted_size_bytes", "file_count", "directory_count", "error_type", "error_message"]
PRESENCE_FIELDS = ["protected_key", "expected_path", "exact_exists", "alias_discovery_attempted", "alias_candidate_count", "resolved_exists", "resolved_protected_path", "resolution_method", "warning_reason"]
APPROVAL_FIELDS = ["required_approval_phrase", "approval_received", "approval_valid", "deletion_allowed"]
SIZE_FIELDS = ["path", "size_bytes", "file_count", "directory_count"]
SANITY_FIELDS = ["check_name", "path", "passed", "rationale"]


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/")


def str_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


def iter_files(path: Path) -> list[Path]:
    try:
        if path.is_file():
            return [path]
        return sorted([p for p in path.rglob("*") if p.is_file()], key=lambda p: p.as_posix())
    except OSError:
        return []


def iter_dirs(path: Path) -> list[Path]:
    try:
        if path.is_dir():
            return sorted([p for p in path.rglob("*") if p.is_dir()], key=lambda p: p.as_posix())
    except OSError:
        pass
    return []


def metrics(path: Path) -> tuple[int, int, int, str]:
    files = iter_files(path) if path.exists() else []
    dirs = iter_dirs(path) if path.exists() else []
    total = 0
    mtimes = []
    for file in files:
        try:
            stat = file.stat()
            total += stat.st_size
            mtimes.append(stat.st_mtime)
        except OSError:
            pass
    if path.exists():
        try:
            mtimes.append(path.stat().st_mtime)
        except OSError:
            pass
    latest = datetime.fromtimestamp(max(mtimes), timezone.utc).replace(microsecond=0).isoformat() if mtimes else ""
    return total, len(files), len(dirs), latest


def approved(phrase: str | None) -> bool:
    return (phrase or os.environ.get("V21_219_APPROVAL_PHRASE", "")) == APPROVAL_PHRASE


def v21_201_alias_is_current_chain(path: Path) -> bool:
    tokens = {"dram", "moomoo", "plan", "r4", "daily"}
    if any(token in path.name.lower() for token in tokens):
        return True
    return any(any(token in file.name.lower() for token in tokens) for file in iter_files(path)[:50])


def protected_presence(root: Path) -> list[dict[str, Any]]:
    out21 = root / "outputs/v21"
    rows = []
    for item in PROTECTED_REQUIRED:
        expected = root / item
        exact = expected.exists()
        attempted = False
        candidates: list[Path] = []
        resolved = expected if exact else None
        method = "EXACT_PATH" if exact else "UNRESOLVED"
        warning = "" if exact else "EXPECTED_PATH_MISSING"
        if not exact and item.startswith("outputs/v21/V21.") and out21.exists():
            attempted = True
            sid = Path(item).name.split("_", 1)[0]
            candidates = [p for p in out21.iterdir() if p.is_dir() and p.name.startswith(sid) and (sid != "V21.201" or v21_201_alias_is_current_chain(p))]
            if candidates:
                resolved = max(candidates, key=lambda p: p.stat().st_mtime)
                method = "ALIAS_DISCOVERY_NEWEST_MODIFIED"
                warning = ""
        rows.append({
            "protected_key": Path(item).name,
            "expected_path": item,
            "exact_exists": exact,
            "alias_discovery_attempted": attempted,
            "alias_candidate_count": len(candidates),
            "resolved_exists": bool(resolved and resolved.exists()),
            "resolved_protected_path": rel(resolved, root) if resolved else "",
            "resolution_method": method,
            "warning_reason": warning,
        })
    return rows


def hard_keep_rel_paths(root: Path, presence: list[dict[str, Any]]) -> set[str]:
    values = {row["resolved_protected_path"] for row in presence if row.get("resolved_protected_path")}
    values.update([".venv", ".venv_moomoo_py312", "scripts", "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"])
    return values


def overlaps(path_rel: str, keep_rels: set[str]) -> bool:
    return any(path_rel == keep or path_rel.startswith(keep + "/") or keep.startswith(path_rel + "/") for keep in keep_rels if keep)


def latest_current_chain_like(path: Path) -> bool:
    text = path.name.lower()
    if any(prefix.lower() in text for prefix in HARD_KEEP_OUTPUT_PREFIXES):
        return True
    if any(token in text for token in LATEST_CURRENT_TOKENS):
        return True
    if any(token in text for token in CURRENT_CHAIN_TOKENS):
        # Current/live DRAM/ABCDE/Moomoo outputs are retained aggressively.
        return True
    return False


def candidate_row(path: Path, root: Path, reason: str, keep_rels: set[str]) -> dict[str, Any]:
    p_rel = rel(path, root)
    size, fc, dc, latest = metrics(path)
    hard = overlaps(p_rel, keep_rels)
    canonical = "canonical" in p_rel.lower() or "price_history" in p_rel.lower() or "ohlcv" in p_rel.lower()
    current = latest_current_chain_like(path)
    protected = hard or current
    return {
        "path": p_rel,
        "path_type": "file" if path.is_file() else "directory",
        "recursive_size_bytes": size,
        "file_count": fc,
        "directory_count": dc,
        "latest_modified_time": latest,
        "deletion_reason": reason,
        "hard_keep_overlap_flag": hard,
        "current_chain_overlap_flag": current,
        "canonical_overlap_flag": canonical,
        "protected_overlap_flag": protected,
        "deletion_allowed_after_checks": not (hard or current or canonical or protected),
    }


def build_plan(root: Path, presence: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    keep_rels = hard_keep_rel_paths(root, presence)
    plan: list[dict[str, Any]] = []
    keep: list[dict[str, Any]] = []

    for keep_rel in sorted(keep_rels):
        p = root / keep_rel
        size, fc, dc, _latest = metrics(p)
        keep.append({"path": keep_rel, "keep_reason": "HARD_KEEP_PROTECTED_CURRENT_CHAIN_OR_ENV", "recursive_size_bytes": size, "file_count": fc, "directory_count": dc})

    archive = root / "archive"
    if archive.exists():
        plan.append(candidate_row(archive, root, "DELETE_LOCAL_ARCHIVE_BACKUPS_APPROVED_SCOPE", keep_rels))

    out21 = root / "outputs/v21"
    if out21.exists():
        for child in sorted([p for p in out21.iterdir() if p.is_dir()], key=lambda p: p.name):
            if latest_current_chain_like(child):
                size, fc, dc, _latest = metrics(child)
                keep.append({"path": rel(child, root), "keep_reason": "CURRENT_CHAIN_OR_LATEST_OR_CLEANUP_PROOF", "recursive_size_bytes": size, "file_count": fc, "directory_count": dc})
            else:
                plan.append(candidate_row(child, root, "DELETE_NON_CURRENT_HISTORICAL_OUTPUTS_V21", keep_rels))

    state = root / "state"
    if state.exists():
        # Delete only explicit cache/temp-like state children, not broad state.
        for child in sorted(state.iterdir(), key=lambda p: p.name):
            if any(token in child.name.lower() for token in ["cache", "tmp", "temp", "checkpoint", "pytest"]):
                plan.append(candidate_row(child, root, "DELETE_NON_CURRENT_STATE_CACHE", keep_rels))
            else:
                size, fc, dc, _latest = metrics(child)
                keep.append({"path": rel(child, root), "keep_reason": "STATE_NOT_EXPLICIT_CACHE_TEMP", "recursive_size_bytes": size, "file_count": fc, "directory_count": dc})

    for root_candidate in [root / ".pytest_cache", root / ".mypy_cache", root / ".ruff_cache"]:
        if root_candidate.exists():
            plan.append(candidate_row(root_candidate, root, "DELETE_CACHE_TEMP", keep_rels))
    for cache in sorted(root.rglob("__pycache__"), key=lambda p: p.as_posix()):
        if ".venv" not in rel(cache, root).lower():
            plan.append(candidate_row(cache, root, "DELETE_CACHE_TEMP", keep_rels))
    for cache in sorted(root.rglob(".ipynb_checkpoints"), key=lambda p: p.as_posix()):
        plan.append(candidate_row(cache, root, "DELETE_CACHE_TEMP", keep_rels))
    for tmp in sorted(root.glob("pytest_tmp*"), key=lambda p: p.as_posix()):
        plan.append(candidate_row(tmp, root, "DELETE_CACHE_TEMP", keep_rels))
    if out21.exists():
        for tmp in sorted(out21.glob("pytest_tmp*"), key=lambda p: p.as_posix()):
            plan.append(candidate_row(tmp, root, "DELETE_CACHE_TEMP", keep_rels))

    return plan, keep


def delete_candidate(row: dict[str, Any], root: Path, simulate_access_denied: str | None = None) -> dict[str, Any]:
    path = root / row["path"]
    result = {
        "path": row["path"],
        "path_type": row["path_type"],
        "delete_attempted": False,
        "deleted": False,
        "deleted_size_bytes": 0,
        "file_count": row["file_count"],
        "directory_count": row["directory_count"],
        "error_type": "",
        "error_message": "",
    }
    if not str_bool(row["deletion_allowed_after_checks"]):
        result["error_type"] = "SkippedProtected"
        result["error_message"] = "deletion_allowed_after_checks=false"
        return result
    if not path.exists():
        result["deleted"] = True
        return result
    result["delete_attempted"] = True
    try:
        if simulate_access_denied and simulate_access_denied in row["path"]:
            raise PermissionError("simulated access denied")
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        result["deleted"] = not path.exists()
        result["deleted_size_bytes"] = int(row["recursive_size_bytes"]) if result["deleted"] else 0
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        result["error_message"] = str(exc)
    return result


def size_snapshot(root: Path) -> list[dict[str, Any]]:
    rows = []
    for p in [root, root / "outputs", root / "outputs/v21", root / "archive", root / "state"]:
        size, fc, dc, _latest = metrics(p)
        rows.append({"path": rel(p, root), "size_bytes": size, "file_count": fc, "directory_count": dc})
    return rows


def sanity_checks(root: Path, presence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks = []
    for row in presence:
        checks.append({"check_name": row["protected_key"], "path": row["resolved_protected_path"] or row["expected_path"], "passed": row["resolved_exists"], "rationale": "protected path must remain present"})
    archive = root / "archive"
    checks.append({"check_name": "archive_absent_allowed", "path": "archive", "passed": True, "rationale": "archive may be absent after V21.219"})
    return checks


def policy_flags(approved_ok: bool, deletion_performed: bool, archive_deleted: bool, historical_deleted: bool) -> dict[str, Any]:
    return {
        "research_only": True,
        "explicit_manual_approval_required": True,
        "explicit_manual_approval_received": approved_ok,
        "aggressive_storage_cleanup": True,
        "user_approved_deleting_local_history_and_archive": approved_ok,
        "deletion_performed": deletion_performed,
        "archive_deleted": archive_deleted,
        "historical_outputs_deleted": historical_deleted,
        "compression_performed": False,
        "price_refresh_performed": False,
        "canonical_mutation_performed": False,
        "moomoo_broker_connection_performed": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "protected_outputs_modified": False,
    }


def summarize(root: Path, before: int, plan: list[dict[str, Any]], results: list[dict[str, Any]], after_presence: list[dict[str, Any]], approved_ok: bool) -> dict[str, Any]:
    after = metrics(root)[0]
    deleted = [r for r in results if str_bool(r["deleted"]) and str_bool(r["delete_attempted"])]
    failed = [r for r in results if str_bool(r["delete_attempted"]) and not str_bool(r["deleted"])]
    skipped_protected = [r for r in plan if not str_bool(r["deletion_allowed_after_checks"])]
    missing = [r for r in after_presence if not str_bool(r["resolved_exists"])]
    archive_deleted = any(r["path"] == "archive" and str_bool(r["deleted"]) for r in results) or not (root / "archive").exists()
    historical_deleted = any(r["path"].startswith("outputs/v21/") and str_bool(r["deleted"]) for r in results)
    deleted_size = sum(int(r["deleted_size_bytes"]) for r in deleted)
    if not approved_ok:
        status = "FAIL_V21_219_MANUAL_APPROVAL_MISSING"
        decision = "HISTORICAL_ARCHIVE_DELETE_BLOCKED_MANUAL_APPROVAL_MISSING"
    elif missing:
        status = "FAIL_V21_219_PROTECTED_PATH_MISSING_AFTER"
        decision = "HISTORICAL_ARCHIVE_DELETE_FAILED_PROTECTED_PATH_MISSING"
    elif any(str_bool(r["deletion_allowed_after_checks"]) is False and (r["hard_keep_overlap_flag"] or r["current_chain_overlap_flag"] or r["canonical_overlap_flag"]) for r in plan):
        # Skipped protected overlaps are expected in the plan; not a failure unless they were allowed.
        status = ""
        decision = ""
    else:
        status = ""
        decision = ""
    if approved_ok and not status:
        if failed:
            status = "WARN_V21_219_PARTIAL_DELETE_WITH_PROTECTED_SAFE"
            decision = "HISTORICAL_ARCHIVE_DELETE_PARTIAL_PROTECTED_SAFE"
        elif after > TARGET_REPO_SIZE_BYTES:
            status = "WARN_V21_219_DELETE_COMPLETED_BUT_TARGET_1GB_NOT_REACHED"
            decision = "HISTORICAL_ARCHIVE_DELETE_COMPLETED_TARGET_NOT_REACHED"
        else:
            status = "PASS_V21_219_HISTORICAL_ARCHIVE_DELETE_COMPLETED"
            decision = "HISTORICAL_ARCHIVE_DELETE_COMPLETED_REPO_SHRUNK"
    return {
        "stage": STAGE,
        "explicit_manual_approval_required": True,
        "explicit_manual_approval_received": approved_ok,
        "repo_size_before_bytes": before,
        "repo_size_after_bytes": after,
        "deleted_path_count": len(deleted),
        "deleted_file_count": sum(int(r["file_count"]) for r in deleted),
        "deleted_directory_count": sum(int(r["directory_count"]) for r in deleted),
        "deleted_size_bytes": deleted_size,
        "failed_delete_count": len(failed),
        "skipped_protected_count": len(skipped_protected),
        "archive_deleted": archive_deleted,
        "historical_outputs_deleted_count": sum(1 for r in deleted if r["path"].startswith("outputs/v21/")),
        "state_cache_deleted_count": sum(1 for r in deleted if r["path"].startswith("state/")),
        "cache_deleted_count": sum(1 for r in deleted if "cache" in r["path"].lower() or "__pycache__" in r["path"].lower() or "pytest_tmp" in r["path"].lower()),
        "protected_path_missing_count_after": len(missing),
        "target_repo_size_bytes": TARGET_REPO_SIZE_BYTES,
        "target_1gb_reached": after <= TARGET_REPO_SIZE_BYTES,
        "final_status": status,
        "final_decision": decision,
        **policy_flags(approved_ok, bool(deleted), archive_deleted, historical_deleted),
    }


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"repo_size_before_bytes={summary['repo_size_before_bytes']}",
        f"repo_size_after_bytes={summary['repo_size_after_bytes']}",
        f"deleted_size_bytes={summary['deleted_size_bytes']}",
        f"deleted_path_count={summary['deleted_path_count']}",
        f"protected_path_missing_count_after={summary['protected_path_missing_count_after']}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_all(output: Path, approval: dict[str, Any], plan: list[dict[str, Any]], keep: list[dict[str, Any]], results: list[dict[str, Any]], snapshot: list[dict[str, Any]], presence: list[dict[str, Any]], sanity: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    write_csv(output / "manual_approval_check.csv", [approval], APPROVAL_FIELDS)
    write_csv(output / "aggressive_delete_plan.csv", plan, PLAN_FIELDS)
    write_csv(output / "protected_keep_manifest.csv", keep, KEEP_FIELDS)
    write_csv(output / "deleted_path_manifest.csv", [r for r in results if str_bool(r["deleted"])], DELETE_FIELDS)
    write_csv(output / "deletion_execution_result.csv", results, DELETE_FIELDS)
    write_csv(output / "post_delete_repo_size_snapshot.csv", snapshot, SIZE_FIELDS)
    write_csv(output / "post_delete_protected_path_presence_check.csv", presence, PRESENCE_FIELDS)
    write_csv(output / "post_delete_current_chain_sanity_check.csv", sanity, SANITY_FIELDS)
    (output / "rollback_not_available_notice.txt").write_text("V21.219 deletes local archive/history after approval. Rollback is not available from this repo; restore from external backups if needed.\n", encoding="utf-8")
    write_json(output / "v21_219_summary.json", summary)
    write_report(output / "V21.219_delete_archive_and_historical_outputs_report.txt", summary)


def run(repo_root: Path = DEFAULT_ROOT, approval_phrase: str | None = None, out_dir: Path | None = None, simulate_exception: bool = False, simulate_access_denied: str | None = None) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    ok = approved(approval_phrase)
    try:
        if simulate_exception:
            raise RuntimeError("simulated V21.219 failure")
        before = metrics(root)[0]
        pre_presence = protected_presence(root)
        plan, keep = build_plan(root, pre_presence)
        approval = {"required_approval_phrase": APPROVAL_PHRASE, "approval_received": bool(approval_phrase), "approval_valid": ok, "deletion_allowed": ok}
        if not ok:
            post_presence = protected_presence(root)
            summary = summarize(root, before, plan, [], post_presence, False)
            write_all(output, approval, plan, keep, [], size_snapshot(root), post_presence, sanity_checks(root, post_presence), summary)
            return summary
        if any(str_bool(row["deletion_allowed_after_checks"]) and (str_bool(row["hard_keep_overlap_flag"]) or str_bool(row["current_chain_overlap_flag"]) or str_bool(row["canonical_overlap_flag"]) or str_bool(row["protected_overlap_flag"])) for row in plan):
            post_presence = protected_presence(root)
            summary = summarize(root, before, plan, [], post_presence, True)
            summary["final_status"] = "FAIL_V21_219_PROTECTED_OR_CURRENT_CHAIN_BLOCKER"
            summary["final_decision"] = "HISTORICAL_ARCHIVE_DELETE_BLOCKED_PROTECTED_OR_CURRENT_CHAIN"
            write_all(output, approval, plan, keep, [], size_snapshot(root), post_presence, sanity_checks(root, post_presence), summary)
            return summary
        results = []
        for row in plan:
            if str_bool(row["deletion_allowed_after_checks"]):
                results.append(delete_candidate(row, root, simulate_access_denied))
            else:
                results.append({
                    "path": row["path"], "path_type": row["path_type"], "delete_attempted": False,
                    "deleted": False, "deleted_size_bytes": 0, "file_count": row["file_count"],
                    "directory_count": row["directory_count"], "error_type": "SkippedProtected",
                    "error_message": "deletion_allowed_after_checks=false",
                })
        post_presence = protected_presence(root)
        summary = summarize(root, before, plan, results, post_presence, True)
        write_all(output, approval, plan, keep, results, size_snapshot(root), post_presence, sanity_checks(root, post_presence), summary)
    except Exception as exc:
        summary = {
            "stage": STAGE,
            "final_status": "FAIL_V21_219_DELETE_EXCEPTION",
            "final_decision": "HISTORICAL_ARCHIVE_DELETE_FAILED",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            **policy_flags(ok, False, False, False),
        }
        write_json(output / "v21_219_summary.json", summary)
        (output / "V21.219_delete_archive_and_historical_outputs_report.txt").write_text(f"{STAGE}\nfinal_status={summary['final_status']}\nfinal_decision={summary['final_decision']}\nerror={summary['error_type']}: {summary['error_message']}\n", encoding="utf-8")
    for key in ["final_status", "final_decision", "repo_size_before_bytes", "repo_size_after_bytes", "deleted_size_bytes", "deleted_path_count"]:
        if key in summary:
            print(f"{key}={summary[key]}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", default=str(DEFAULT_ROOT))
    parser.add_argument("--approval-phrase", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(Path(args.repo_root), approval_phrase=args.approval_phrase)
    return 0 if str(summary["final_status"]).startswith(("PASS", "WARN")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
