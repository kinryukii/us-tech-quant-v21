#!/usr/bin/env python
"""V21.221 minimal current-chain keepset and repo-body prune plan.

Audit-only. Changes planning policy from broad proof/history retention to a
minimal next-daily-chain keepset. No deletion, compression, movement, price
refresh, canonical mutation, OpenD connection, adoption change, or broker action
is performed.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOT = Path(r"D:\us-tech-quant")
STAGE = "V21.221_MINIMAL_CURRENT_CHAIN_KEEPSET_AND_REPO_BODY_PRUNE_PLAN"
OUT_REL = Path("outputs/v21/V21.221_MINIMAL_CURRENT_CHAIN_KEEPSET_AND_REPO_BODY_PRUNE_PLAN")
TARGET_REPO_SIZE_BYTES = 1_000_000_000
WARNING_THRESHOLD_BYTES = 1_200_000_000
APPROVAL_PHRASE = "APPROVE_V21_222_MINIMAL_KEEPSET_PRUNE"
HARD_KEEP_REQUIRED = [
    ".venv",
    "scripts",
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
    "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
    "outputs/v21/V21.221_MINIMAL_CURRENT_CHAIN_KEEPSET_AND_REPO_BODY_PRUNE_PLAN",
]
HARD_KEEP_PREFIXES = ["V21.197", "V21.199", "V21.201", "V21.221"]
CURRENT_REQUIRED_TOKENS = ["latest", "current_chain", "trade_plan", "ledger", "ranking"]
CURRENT_STAGE_TOKENS = ["dram", "abcde", "moomoo"]
PLAN_FIELDS = [
    "candidate_path", "candidate_type", "recursive_size_bytes", "file_count", "directory_count",
    "latest_modified_time", "keep_or_delete_decision", "deletion_reason",
    "estimated_savings_bytes", "hard_keep_overlap_flag", "current_chain_required_flag",
    "canonical_overlap_flag", "scripts_overlap_flag", "approval_required",
    "deletion_allowed_in_this_run", "proposed_execution_stage", "blocker_reasons",
    "rationale",
]
KEEP_FIELDS = ["keep_path", "keep_type", "recursive_size_bytes", "file_count", "directory_count", "rationale"]
PRESENCE_FIELDS = ["protected_key", "expected_path", "exact_exists", "alias_discovery_attempted", "alias_candidate_count", "resolved_exists", "resolved_protected_path", "resolution_method", "warning_reason"]
PROJECTION_FIELDS = ["repo_total_size_bytes_now", "target_repo_size_bytes", "warning_threshold_bytes", "prune_candidate_size_bytes", "projected_repo_size_after_minimal_keepset_prune", "target_1gb_reachable_flag", "target_1_2gb_reachable_flag"]
APPROVAL_FIELDS = ["required_manual_approval_phrase", "approval_required", "deletion_allowed_in_this_run", "rationale"]


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


def hard_keep_presence(root: Path) -> list[dict[str, Any]]:
    out21 = root / "outputs/v21"
    rows = []
    for item in HARD_KEEP_REQUIRED:
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


def hard_keep_rels(presence: list[dict[str, Any]]) -> set[str]:
    values = {row["resolved_protected_path"] for row in presence if row.get("resolved_protected_path")}
    values.update([".venv", "scripts", "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"])
    return values


def overlaps(path_rel: str, keeps: set[str]) -> bool:
    return any(path_rel == keep or path_rel.startswith(keep + "/") or keep.startswith(path_rel + "/") for keep in keeps if keep)


def current_chain_required(path: Path) -> bool:
    name = path.name.lower()
    if any(path.name.startswith(prefix) for prefix in HARD_KEEP_PREFIXES):
        return True
    if any(token in name for token in CURRENT_REQUIRED_TOKENS):
        return True
    # Keep only explicit current/latest/required DRAM/ABCDE/Moomoo outputs. Older
    # diagnosis/repair proof stages containing these words are prune candidates.
    if any(token in name for token in CURRENT_STAGE_TOKENS) and any(token in name for token in ["current", "latest", "daily", "plan", "r4"]):
        return True
    return False


def row_for(path: Path, root: Path, keeps: set[str], decision: str, ctype: str, reason: str) -> dict[str, Any]:
    path_rel = rel(path, root)
    size, fc, dc, latest = metrics(path)
    hard = overlaps(path_rel, keeps)
    scripts = path_rel == "scripts" or path_rel.startswith("scripts/")
    canonical = any(token in path_rel.lower() for token in ["canonical", "price_history", "ohlcv"])
    current = current_chain_required(path)
    blockers = []
    if hard:
        blockers.append("HARD_KEEP_OVERLAP")
    if scripts:
        blockers.append("SCRIPTS_OVERLAP")
    if canonical:
        blockers.append("CANONICAL_OVERLAP")
    if current and decision != "KEEP_MINIMAL_CURRENT_CHAIN":
        blockers.append("CURRENT_CHAIN_REQUIRED")
    delete_decision = decision
    if blockers:
        delete_decision = "KEEP_MINIMAL_CURRENT_CHAIN" if current or hard else "NOT_APPLICABLE"
        ctype = "NOT_APPLICABLE"
    savings = size if delete_decision.startswith("DELETE") else 0
    return {
        "candidate_path": path_rel,
        "candidate_type": ctype,
        "recursive_size_bytes": size,
        "file_count": fc,
        "directory_count": dc,
        "latest_modified_time": latest,
        "keep_or_delete_decision": delete_decision,
        "deletion_reason": reason,
        "estimated_savings_bytes": savings,
        "hard_keep_overlap_flag": hard,
        "current_chain_required_flag": current,
        "canonical_overlap_flag": canonical,
        "scripts_overlap_flag": scripts,
        "approval_required": True,
        "deletion_allowed_in_this_run": False,
        "proposed_execution_stage": "V21.222_MINIMAL_KEEPSET_PRUNE_AFTER_APPROVAL",
        "blocker_reasons": "|".join(blockers),
        "rationale": "Minimal keepset prune candidate; deletion requires V21.222 approval." if not blockers else "Hard keep/current-chain path retained.",
    }


def build_plan(root: Path, keeps: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    keep_rows: list[dict[str, Any]] = []
    for keep in sorted(keeps):
        p = root / keep
        size, fc, dc, _latest = metrics(p)
        keep_rows.append({"keep_path": keep, "keep_type": "MINIMAL_HARD_KEEP", "recursive_size_bytes": size, "file_count": fc, "directory_count": dc, "rationale": "Required to run next daily chain or source code/config."})

    out21 = root / "outputs/v21"
    if out21.exists():
        for stage in sorted([p for p in out21.iterdir() if p.is_dir()], key=lambda p: p.name):
            if current_chain_required(stage) or overlaps(rel(stage, root), keeps):
                rows.append(row_for(stage, root, keeps, "KEEP_MINIMAL_CURRENT_CHAIN", "NOT_APPLICABLE", "Minimal current-chain hard keep."))
            elif any(stage.name.startswith(f"V21.{n}") for n in range(202, 221)):
                rows.append(row_for(stage, root, keeps, "DELETE_OLD_CLEANUP_PROOF", "OLD_CLEANUP_PROOF", "Delete local cleanup proof under minimal repo-body policy."))
            else:
                rows.append(row_for(stage, root, keeps, "DELETE_HISTORICAL_OUTPUT", "HISTORICAL_OUTPUT", "Delete historical outputs/v21 residual under minimal repo-body policy."))

    state = root / "state"
    if state.exists():
        for child in sorted(state.iterdir(), key=lambda p: p.name):
            if any(token in child.name.lower() for token in ["cache", "tmp", "temp", "checkpoint", "pytest"]):
                rows.append(row_for(child, root, keeps, "DELETE_NON_CURRENT_STATE_CACHE", "NON_CURRENT_STATE_CACHE", "Delete non-current state/cache."))

    alt = root / ".venv_moomoo_py312"
    if alt.exists():
        row = row_for(alt, root, keeps, "RETAIN_FOR_SEPARATE_ALT_VENV_REVIEW", "ALT_VENV_RETIREMENT_REVIEW", "Separate review after Moomoo permission readiness fix.")
        row["estimated_savings_bytes"] = 0
        row["blocker_reasons"] = "CURRENT_MOOMOO_PERMISSION_READINESS_ISSUE"
        rows.append(row)

    return rows, keep_rows


def policy_flags() -> dict[str, Any]:
    return {
        "research_only": True, "audit_only": True, "dry_run": True, "aggressive_storage_cleanup": True,
        "local_history_delete_policy_enabled": True, "deletion_performed": False, "compression_performed": False,
        "archive_movement_performed": False, "price_refresh_performed": False, "canonical_mutation_performed": False,
        "moomoo_broker_connection_performed": False, "broker_action_allowed": False,
        "official_adoption_allowed": False, "protected_outputs_modified": False,
    }


def summarize(root: Path, rows: list[dict[str, Any]], keep_rows: list[dict[str, Any]], missing_count: int) -> dict[str, Any]:
    repo_size = metrics(root)[0]
    outputs_size = metrics(root / "outputs/v21")[0]
    state_size = metrics(root / "state")[0]
    venv_size = metrics(root / ".venv")[0]
    alt_size = metrics(root / ".venv_moomoo_py312")[0]
    candidates = [r for r in rows if str(r["keep_or_delete_decision"]).startswith("DELETE")]
    savings = sum(int(r["estimated_savings_bytes"]) for r in candidates)
    projected = max(0, repo_size - savings)
    if missing_count:
        status = "FAIL_V21_221_HARD_KEEP_PATH_MISSING"
        decision = "MINIMAL_KEEPSET_PRUNE_FAILED_HARD_KEEP_MISSING"
    elif projected > TARGET_REPO_SIZE_BYTES:
        status = "WARN_V21_221_1GB_TARGET_NOT_REACHABLE_WITHOUT_ALT_VENV_OR_VENV_CHANGES"
        decision = "MINIMAL_KEEPSET_PRUNE_PLAN_READY_BUT_1GB_NEEDS_ENV_OR_MORE_DELETION"
    else:
        status = "PASS_V21_221_MINIMAL_KEEPSET_PRUNE_PLAN_READY"
        decision = "MINIMAL_KEEPSET_PRUNE_PLAN_READY_APPROVAL_REQUIRED"
    return {
        "stage": STAGE,
        "repo_total_size_bytes_now": repo_size,
        "outputs_v21_size_bytes_now": outputs_size,
        "state_size_bytes_now": state_size,
        "venv_size_bytes_now": venv_size,
        "alt_venv_size_bytes_now": alt_size,
        "minimal_keepset_size_bytes": sum(int(r["recursive_size_bytes"]) for r in keep_rows),
        "prune_candidate_count": len(candidates),
        "prune_candidate_size_bytes": sum(int(r["recursive_size_bytes"]) for r in candidates),
        "projected_repo_size_after_minimal_keepset_prune": projected,
        "target_1gb_reachable_flag": projected <= TARGET_REPO_SIZE_BYTES,
        "target_1_2gb_reachable_flag": projected <= WARNING_THRESHOLD_BYTES,
        "hard_keep_count": len(keep_rows),
        "delete_historical_output_count": sum(1 for r in candidates if r["keep_or_delete_decision"] == "DELETE_HISTORICAL_OUTPUT"),
        "delete_old_cleanup_proof_count": sum(1 for r in candidates if r["keep_or_delete_decision"] == "DELETE_OLD_CLEANUP_PROOF"),
        "delete_non_current_state_cache_count": sum(1 for r in candidates if r["keep_or_delete_decision"] == "DELETE_NON_CURRENT_STATE_CACHE"),
        "alt_venv_separate_review_size_bytes": alt_size,
        "deletion_allowed_in_this_run": False,
        "required_manual_approval_phrase": APPROVAL_PHRASE,
        "protected_path_missing_count": missing_count,
        "final_status": status,
        "final_decision": decision,
        **policy_flags(),
    }


def projection_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"repo_total_size_bytes_now": summary["repo_total_size_bytes_now"], "target_repo_size_bytes": TARGET_REPO_SIZE_BYTES, "warning_threshold_bytes": WARNING_THRESHOLD_BYTES, "prune_candidate_size_bytes": summary["prune_candidate_size_bytes"], "projected_repo_size_after_minimal_keepset_prune": summary["projected_repo_size_after_minimal_keepset_prune"], "target_1gb_reachable_flag": summary["target_1gb_reachable_flag"], "target_1_2gb_reachable_flag": summary["target_1_2gb_reachable_flag"]}]


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"repo_total_size_bytes_now={summary['repo_total_size_bytes_now']}",
        f"prune_candidate_size_bytes={summary['prune_candidate_size_bytes']}",
        f"projected_repo_size_after_minimal_keepset_prune={summary['projected_repo_size_after_minimal_keepset_prune']}",
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
            raise RuntimeError("simulated V21.221 failure")
        presence = hard_keep_presence(root)
        missing = [row for row in presence if not str_bool(row["resolved_exists"])]
        rows, keep_rows = build_plan(root, hard_keep_rels(presence))
        summary = summarize(root, rows, keep_rows, len(missing))
        write_csv(output / "minimal_current_chain_keepset_manifest.csv", keep_rows, KEEP_FIELDS)
        write_csv(output / "repo_body_prune_candidate_plan.csv", rows, PLAN_FIELDS)
        write_csv(output / "outputs_v21_keep_delete_decision.csv", [r for r in rows if r["candidate_path"].startswith("outputs/v21/")], PLAN_FIELDS)
        write_csv(output / "state_keep_delete_decision.csv", [r for r in rows if r["candidate_path"].startswith("state/")], PLAN_FIELDS)
        write_csv(output / "cleanup_proof_chain_prune_plan.csv", [r for r in rows if r["keep_or_delete_decision"] == "DELETE_OLD_CLEANUP_PROOF"], PLAN_FIELDS)
        write_csv(output / "projected_repo_size_after_minimal_keepset_prune.csv", projection_rows(summary), ["repo_total_size_bytes_now", "target_repo_size_bytes", "warning_threshold_bytes", "prune_candidate_size_bytes", "projected_repo_size_after_minimal_keepset_prune", "target_1gb_reachable_flag", "target_1_2gb_reachable_flag"])
        write_csv(output / "protected_path_presence_check.csv", presence, PRESENCE_FIELDS)
        write_csv(output / "manual_approval_checklist.csv", [{"required_manual_approval_phrase": APPROVAL_PHRASE, "approval_required": True, "deletion_allowed_in_this_run": False, "rationale": "V21.221 is plan-only; V21.222 requires approval."}], ["required_manual_approval_phrase", "approval_required", "deletion_allowed_in_this_run", "rationale"])
        write_json(output / "v21_221_summary.json", summary)
        write_report(output / "V21.221_minimal_current_chain_keepset_and_repo_body_prune_plan_report.txt", summary)
    except Exception as exc:
        summary = {"stage": STAGE, "final_status": "FAIL_V21_221_MINIMAL_KEEPSET_PLAN_EXCEPTION", "final_decision": "MINIMAL_KEEPSET_PRUNE_PLAN_FAILED", "error_type": type(exc).__name__, "error_message": str(exc), **policy_flags()}
        write_json(output / "v21_221_summary.json", summary)
        (output / "V21.221_minimal_current_chain_keepset_and_repo_body_prune_plan_report.txt").write_text(f"{STAGE}\nfinal_status={summary['final_status']}\nfinal_decision={summary['final_decision']}\nerror={summary['error_type']}: {summary['error_message']}\n", encoding="utf-8")
    for key in ["final_status", "final_decision", "repo_total_size_bytes_now", "projected_repo_size_after_minimal_keepset_prune", "prune_candidate_size_bytes"]:
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
