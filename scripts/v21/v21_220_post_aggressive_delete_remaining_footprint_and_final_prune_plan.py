#!/usr/bin/env python
"""V21.220 remaining footprint attribution and final prune plan.

Audit-only. Produces the next approval-gated final prune plan after V21.219.
No deletion, compression, movement, price refresh, canonical mutation, OpenD
connection, adoption change, or broker action is performed.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOT = Path(r"D:\us-tech-quant")
STAGE = "V21.220_POST_AGGRESSIVE_DELETE_REMAINING_FOOTPRINT_AND_FINAL_PRUNE_PLAN"
OUT_REL = Path("outputs/v21/V21.220_POST_AGGRESSIVE_DELETE_REMAINING_FOOTPRINT_AND_FINAL_PRUNE_PLAN")
TARGET_REPO_SIZE_BYTES = 1_000_000_000
WARNING_THRESHOLD_BYTES = 1_200_000_000
APPROVAL_PHRASE = "APPROVE_V21_221_FINAL_PRUNE_TO_1GB_TARGET"
PROTECTED_REQUIRED = [
    ".venv",
    "scripts",
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
    "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
    "outputs/v21/V21.219_DELETE_ARCHIVE_AND_HISTORICAL_OUTPUTS_AFTER_APPROVAL",
    "outputs/v21/V21.220_POST_AGGRESSIVE_DELETE_REMAINING_FOOTPRINT_AND_FINAL_PRUNE_PLAN",
]
HARD_KEEP_PREFIXES = ["V21.197", "V21.199", "V21.201", "V21.219", "V21.220"]
CURRENT_TOKENS = ["latest", "current_chain", "trade_plan", "ledger", "ranking", "canonical", "price_history", "ohlcv", "kline", "protected"]
DRAM_ABCDE_MOOMOO_TOKENS = ["dram", "abcde", "moomoo"]
SUMMARY_FIELDS = ["path", "size_bytes", "file_count", "directory_count"]
STAGE_SIZE_FIELDS = ["stage_dir", "source_path", "recursive_size_bytes", "file_count", "directory_count", "latest_modified_time"]
PLAN_FIELDS = [
    "candidate_path", "candidate_type", "recursive_size_bytes", "file_count", "directory_count",
    "latest_modified_time", "deletion_reason", "current_chain_overlap_flag",
    "protected_overlap_flag", "canonical_overlap_flag", "scripts_overlap_flag",
    "approval_required", "deletion_allowed_in_this_run", "proposed_next_stage",
    "blocker_reasons", "rationale",
]
PRESENCE_FIELDS = ["protected_key", "expected_path", "exact_exists", "alias_discovery_attempted", "alias_candidate_count", "resolved_exists", "resolved_protected_path", "resolution_method", "warning_reason"]
APPROVAL_FIELDS = ["required_manual_approval_phrase", "approval_required", "deletion_allowed_in_this_run", "rationale"]
PROJECTION_FIELDS = ["repo_total_size_bytes_now", "target_repo_size_bytes", "warning_threshold_bytes", "projected_savings_bytes", "projected_repo_size_after_final_prune", "target_1gb_reachable_flag"]


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
    size = 0
    mtimes = []
    for file in files:
        try:
            stat = file.stat()
            size += stat.st_size
            mtimes.append(stat.st_mtime)
        except OSError:
            pass
    if path.exists():
        try:
            mtimes.append(path.stat().st_mtime)
        except OSError:
            pass
    latest = datetime.fromtimestamp(max(mtimes), timezone.utc).replace(microsecond=0).isoformat() if mtimes else ""
    return size, len(files), len(dirs), latest


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
        rows.append({"protected_key": Path(item).name, "expected_path": item, "exact_exists": exact, "alias_discovery_attempted": attempted, "alias_candidate_count": len(candidates), "resolved_exists": bool(resolved and resolved.exists()), "resolved_protected_path": rel(resolved, root) if resolved else "", "resolution_method": method, "warning_reason": warning})
    return rows


def protected_rels(presence: list[dict[str, Any]]) -> set[str]:
    values = {row["resolved_protected_path"] for row in presence if row.get("resolved_protected_path")}
    values.update([".venv", "scripts", "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"])
    return values


def overlaps(path_rel: str, keep: set[str]) -> bool:
    return any(path_rel == k or path_rel.startswith(k + "/") or k.startswith(path_rel + "/") for k in keep if k)


def current_chain_like(path: Path) -> bool:
    name = path.name.lower()
    if any(path.name.startswith(prefix) for prefix in HARD_KEEP_PREFIXES):
        return True
    if any(token in name for token in CURRENT_TOKENS):
        return True
    if any(token in name for token in DRAM_ABCDE_MOOMOO_TOKENS):
        return True
    return False


def plan_row(path: Path, root: Path, ctype: str, reason: str, keep: set[str], next_stage: str = "V21.221_FINAL_PRUNE_TO_1GB_TARGET") -> dict[str, Any]:
    path_rel = rel(path, root)
    size, fc, dc, latest = metrics(path)
    protected = overlaps(path_rel, keep)
    scripts = path_rel == "scripts" or path_rel.startswith("scripts/")
    canonical = any(token in path_rel.lower() for token in ["canonical", "price_history", "ohlcv"])
    current = current_chain_like(path)
    blockers = []
    if protected:
        blockers.append("PROTECTED_PATH_OVERLAP")
    if scripts:
        blockers.append("SCRIPTS_OVERLAP")
    if canonical:
        blockers.append("CANONICAL_OVERLAP")
    if current:
        blockers.append("CURRENT_CHAIN_OVERLAP")
    allowed_candidate = not blockers
    return {
        "candidate_path": path_rel,
        "candidate_type": ctype if allowed_candidate else "NOT_CANDIDATE_PROTECTED",
        "recursive_size_bytes": size,
        "file_count": fc,
        "directory_count": dc,
        "latest_modified_time": latest,
        "deletion_reason": reason,
        "current_chain_overlap_flag": current,
        "protected_overlap_flag": protected,
        "canonical_overlap_flag": canonical,
        "scripts_overlap_flag": scripts,
        "approval_required": True,
        "deletion_allowed_in_this_run": False,
        "proposed_next_stage": next_stage,
        "blocker_reasons": "|".join(blockers),
        "rationale": "Final prune candidate only; deletion requires V21.221 approval." if allowed_candidate else "Hard keep/protected overlap blocks candidate.",
    }


def stage_size_rows(root: Path) -> list[dict[str, Any]]:
    out21 = root / "outputs/v21"
    rows = []
    if out21.exists():
        for stage in sorted([p for p in out21.iterdir() if p.is_dir()], key=lambda p: p.name):
            size, fc, dc, latest = metrics(stage)
            rows.append({"stage_dir": stage.name, "source_path": rel(stage, root), "recursive_size_bytes": size, "file_count": fc, "directory_count": dc, "latest_modified_time": latest})
    return rows


def build_candidates(root: Path, keep: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    out21 = root / "outputs/v21"
    v177 = out21 / "V21.177_R1A_STALENESS_SEMANTIC_REPAIR"
    if v177.exists():
        files = iter_files(v177)
        cache_only = all(any(token in rel(f, v177).lower() for token in ["pytest_tmp", "cache", "tmp", "__pycache__"]) for f in files) or any("pytest_tmp" in p.name.lower() for p in iter_dirs(v177))
        ctype = "FAILED_DELETE_RETRY_CACHE_RESIDUE" if cache_only and not current_chain_like(v177) else "MANUAL_REVIEW_REQUIRED"
        rows.append(plan_row(v177, root, ctype, "Retry V21.219 failed delete if only pytest/cache/temp residue.", keep))

    state = root / "state"
    if state.exists():
        for child in sorted(state.iterdir(), key=lambda p: p.name):
            if any(token in child.name.lower() for token in ["cache", "tmp", "temp", "checkpoint", "pytest"]):
                rows.append(plan_row(child, root, "NON_CURRENT_STATE_CACHE", "Delete non-current state/cache residue.", keep))

    alt = root / ".venv_moomoo_py312"
    if alt.exists():
        rows.append(plan_row(alt, root, "ALT_VENV_RETIREMENT_REVIEW", "Alternate venv remains a review candidate, blocked until Moomoo import readiness is clean.", keep))

    if out21.exists():
        for stage in sorted([p for p in out21.iterdir() if p.is_dir()], key=lambda p: p.name):
            if stage.name == "V21.177_R1A_STALENESS_SEMANTIC_REPAIR":
                continue
            if stage.name.startswith("V21.219") or stage.name.startswith("V21.220"):
                continue
            if any(stage.name.startswith(f"V21.{n}") for n in range(202, 219)):
                rows.append(plan_row(stage, root, "OLD_CLEANUP_PROOF_COMPACT_OR_DELETE", "Older cleanup proof output can be compacted/deleted after retaining latest proof summary.", keep))
            elif not current_chain_like(stage):
                rows.append(plan_row(stage, root, "NON_CURRENT_OUTPUTS_V21_RESIDUAL", "Remaining non-current outputs/v21 residual.", keep))

    for cache in sorted([p for p in root.rglob("__pycache__") if ".venv" not in rel(p, root).lower()], key=lambda p: p.as_posix()):
        rows.append(plan_row(cache, root, "LOW_VALUE_CACHE", "Residual cache directory.", keep))
    for cache in [root / ".pytest_cache", root / ".mypy_cache", root / ".ruff_cache"]:
        if cache.exists():
            rows.append(plan_row(cache, root, "LOW_VALUE_CACHE", "Residual cache directory.", keep))
    return rows


def top_level_rows(root: Path) -> list[dict[str, Any]]:
    rows = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        size, fc, dc, _latest = metrics(child)
        rows.append({"path": rel(child, root), "size_bytes": size, "file_count": fc, "directory_count": dc})
    return sorted(rows, key=lambda r: int(r["size_bytes"]), reverse=True)


def largest_dirs(root: Path, limit: int = 100) -> list[dict[str, Any]]:
    dirs = [root] + iter_dirs(root)
    rows = []
    for d in dirs:
        if ".venv" in rel(d, root).lower() and rel(d, root).lower() != ".venv" and rel(d, root).lower() != ".venv_moomoo_py312":
            continue
        size, fc, dc, _latest = metrics(d)
        rows.append({"path": rel(d, root), "size_bytes": size, "file_count": fc, "directory_count": dc})
    return sorted(rows, key=lambda r: int(r["size_bytes"]), reverse=True)[:limit]


def largest_files(root: Path, limit: int = 100) -> list[dict[str, Any]]:
    rows = []
    for f in iter_files(root):
        try:
            size = f.stat().st_size
        except OSError:
            continue
        rows.append({"path": rel(f, root), "size_bytes": size, "file_count": 1, "directory_count": 0})
    return sorted(rows, key=lambda r: int(r["size_bytes"]), reverse=True)[:limit]


def policy_flags() -> dict[str, Any]:
    return {
        "research_only": True, "audit_only": True, "dry_run": True, "aggressive_storage_cleanup": True,
        "deletion_performed": False, "compression_performed": False, "archive_movement_performed": False,
        "price_refresh_performed": False, "canonical_mutation_performed": False,
        "moomoo_broker_connection_performed": False, "broker_action_allowed": False,
        "official_adoption_allowed": False, "protected_outputs_modified": False,
    }


def summarize(root: Path, candidates: list[dict[str, Any]], missing_count: int) -> dict[str, Any]:
    repo_size = metrics(root)[0]
    outputs_size = metrics(root / "outputs/v21")[0]
    state_size = metrics(root / "state")[0]
    venv_size = metrics(root / ".venv")[0]
    alt_size = metrics(root / ".venv_moomoo_py312")[0]
    scripts_size = metrics(root / "scripts")[0]
    allowed = [r for r in candidates if not r["blocker_reasons"]]
    savings = sum(int(r["recursive_size_bytes"]) for r in allowed if r["candidate_type"] != "ALT_VENV_RETIREMENT_REVIEW")
    alt_candidate = sum(int(r["recursive_size_bytes"]) for r in allowed if r["candidate_type"] == "ALT_VENV_RETIREMENT_REVIEW")
    projected = max(0, repo_size - savings)
    if missing_count:
        status = "FAIL_V21_220_PROTECTED_PATH_MISSING"
        decision = "FINAL_PRUNE_PLAN_FAILED_PROTECTED_PATH_MISSING"
    elif projected > TARGET_REPO_SIZE_BYTES:
        status = "WARN_V21_220_1GB_TARGET_STILL_NOT_REACHABLE"
        decision = "FINAL_PRUNE_PLAN_READY_BUT_1GB_NOT_REACHABLE"
    else:
        status = "PASS_V21_220_FINAL_PRUNE_PLAN_READY"
        decision = "FINAL_PRUNE_PLAN_READY_APPROVAL_REQUIRED"
    return {
        "stage": STAGE,
        "repo_total_size_bytes_now": repo_size,
        "outputs_v21_size_bytes_now": outputs_size,
        "state_size_bytes_now": state_size,
        "venv_size_bytes_now": venv_size,
        "alt_venv_size_bytes_now": alt_size,
        "scripts_size_bytes_now": scripts_size,
        "target_repo_size_bytes": TARGET_REPO_SIZE_BYTES,
        "final_prune_candidate_count": len(allowed),
        "final_prune_candidate_size_bytes": sum(int(r["recursive_size_bytes"]) for r in allowed),
        "projected_savings_bytes": savings,
        "projected_repo_size_after_final_prune": projected,
        "target_1gb_reachable_flag": projected <= TARGET_REPO_SIZE_BYTES,
        "failed_delete_retry_candidate_count": sum(1 for r in allowed if r["candidate_type"] == "FAILED_DELETE_RETRY_CACHE_RESIDUE"),
        "state_cache_candidate_size_bytes": sum(int(r["recursive_size_bytes"]) for r in allowed if r["candidate_type"] == "NON_CURRENT_STATE_CACHE"),
        "old_cleanup_proof_candidate_size_bytes": sum(int(r["recursive_size_bytes"]) for r in allowed if r["candidate_type"] == "OLD_CLEANUP_PROOF_COMPACT_OR_DELETE"),
        "non_current_outputs_residual_size_bytes": sum(int(r["recursive_size_bytes"]) for r in allowed if r["candidate_type"] == "NON_CURRENT_OUTPUTS_V21_RESIDUAL"),
        "alt_venv_candidate_size_bytes": alt_candidate,
        "protected_path_missing_count": missing_count,
        "deletion_allowed_in_this_run": False,
        "required_manual_approval_phrase": APPROVAL_PHRASE,
        "final_status": status,
        "final_decision": decision,
        **policy_flags(),
    }


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"repo_total_size_bytes_now={summary['repo_total_size_bytes_now']}",
        f"projected_savings_bytes={summary['projected_savings_bytes']}",
        f"projected_repo_size_after_final_prune={summary['projected_repo_size_after_final_prune']}",
        f"required_manual_approval_phrase={summary['required_manual_approval_phrase']}",
        "deletion_allowed_in_this_run=false",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(repo_root: Path = DEFAULT_ROOT, out_dir: Path | None = None, simulate_exception: bool = False) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if simulate_exception:
            raise RuntimeError("simulated V21.220 failure")
        presence = protected_presence(root)
        missing = [r for r in presence if not str_bool(r["resolved_exists"])]
        keep = protected_rels(presence)
        candidates = build_candidates(root, keep)
        summary = summarize(root, candidates, len(missing))
        write_csv(output / "remaining_repo_top_level_size.csv", top_level_rows(root), SUMMARY_FIELDS)
        write_csv(output / "remaining_largest_directories.csv", largest_dirs(root), SUMMARY_FIELDS)
        write_csv(output / "remaining_largest_files.csv", largest_files(root), SUMMARY_FIELDS)
        write_csv(output / "remaining_outputs_v21_stage_size.csv", stage_size_rows(root), STAGE_SIZE_FIELDS)
        write_csv(output / "final_prune_candidate_plan.csv", candidates, PLAN_FIELDS)
        write_csv(output / "current_chain_minimal_keep_manifest.csv", [r for r in candidates if r["current_chain_overlap_flag"] or r["protected_overlap_flag"]], PLAN_FIELDS)
        write_csv(output / "non_current_state_cache_prune_plan.csv", [r for r in candidates if r["candidate_type"] == "NON_CURRENT_STATE_CACHE"], PLAN_FIELDS)
        write_csv(output / "failed_delete_retry_plan.csv", [r for r in candidates if r["candidate_type"] == "FAILED_DELETE_RETRY_CACHE_RESIDUE"], PLAN_FIELDS)
        write_csv(output / "proof_chain_compaction_plan.csv", [r for r in candidates if r["candidate_type"] == "OLD_CLEANUP_PROOF_COMPACT_OR_DELETE"], PLAN_FIELDS)
        write_csv(output / "projected_repo_size_after_final_prune.csv", [{"repo_total_size_bytes_now": summary["repo_total_size_bytes_now"], "target_repo_size_bytes": TARGET_REPO_SIZE_BYTES, "warning_threshold_bytes": WARNING_THRESHOLD_BYTES, "projected_savings_bytes": summary["projected_savings_bytes"], "projected_repo_size_after_final_prune": summary["projected_repo_size_after_final_prune"], "target_1gb_reachable_flag": summary["target_1gb_reachable_flag"]}], PROJECTION_FIELDS)
        write_csv(output / "protected_path_presence_check.csv", presence, PRESENCE_FIELDS)
        write_csv(output / "manual_approval_checklist.csv", [{"required_manual_approval_phrase": APPROVAL_PHRASE, "approval_required": True, "deletion_allowed_in_this_run": False, "rationale": "V21.220 is audit-only; V21.221 requires approval."}], APPROVAL_FIELDS)
        write_json(output / "v21_220_summary.json", summary)
        write_report(output / "V21.220_post_aggressive_delete_remaining_footprint_report.txt", summary)
    except Exception as exc:
        summary = {"stage": STAGE, "final_status": "FAIL_V21_220_FINAL_PRUNE_PLAN_EXCEPTION", "final_decision": "FINAL_PRUNE_PLAN_FAILED", "error_type": type(exc).__name__, "error_message": str(exc), **policy_flags()}
        write_json(output / "v21_220_summary.json", summary)
        (output / "V21.220_post_aggressive_delete_remaining_footprint_report.txt").write_text(f"{STAGE}\nfinal_status={summary['final_status']}\nfinal_decision={summary['final_decision']}\nerror={summary['error_type']}: {summary['error_message']}\n", encoding="utf-8")
    for key in ["final_status", "final_decision", "repo_total_size_bytes_now", "projected_repo_size_after_final_prune", "projected_savings_bytes"]:
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
