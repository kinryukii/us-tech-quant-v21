#!/usr/bin/env python
"""V21.227 external cache/archive migration dry-run.

Dry-run only. Reads V21.226 plan artifacts, validates future actions, and writes
V21.227 reports under repo outputs. It does not create external roots or copy,
move, delete, overwrite, or migrate any source artifact.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable


STAGE = "V21.227_EXTERNAL_CACHE_AND_ARCHIVE_MIGRATION_DRY_RUN"
OUT_REL = Path("outputs/v21") / STAGE
V226_REL = Path("outputs/v21/V21.226_REPO_CACHE_ARCHIVE_SEPARATION_PLAN")
DEFAULT_CACHE_ROOT = Path(r"D:\us-tech-quant-cache")
DEFAULT_ARCHIVE_ROOT = Path(r"D:\us-tech-quant-archive")
DEFAULT_QUARANTINE_ROOT = Path(r"D:\us-tech-quant-quarantine")
HASH_THRESHOLD = 5_242_880
PASS_STATUS = "PASS_V21_227_EXTERNAL_MIGRATION_DRY_RUN_READY"
WARN_STATUS = "WARN_V21_227_EXTERNAL_MIGRATION_DRY_RUN_READY_WITH_USER_REVIEW_BLOCKERS"
FAIL_PLAN_STATUS = "FAIL_V21_227_EXTERNAL_MIGRATION_DRY_RUN_BLOCKED_BY_PLAN_ERRORS"
FAIL_INPUT_STATUS = "FAIL_V21_227_MISSING_V21_226_SEPARATION_PLAN_INPUTS"
FINAL_DECISION = "EXTERNAL_MIGRATION_DRY_RUN_READY_FOR_COPY_ONLY_STAGE_AFTER_REVIEW"

REQUIRED_V226 = [
    "separation_plan_master.csv",
    "repo_keep_plan.csv",
    "cache_migration_plan.csv",
    "archive_migration_plan.csv",
    "quarantine_plan.csv",
    "delete_after_verification_plan.csv",
    "user_review_required_plan.csv",
    "protected_no_action_plan.csv",
    "pointer_manifest_plan.csv",
    "directory_layout_plan.json",
    "migration_order_plan.csv",
    "storage_impact_projection.csv",
    "moomoo_only_cache_layout_plan.csv",
    "archive_layout_plan.csv",
    "repo_lightweight_output_policy.json",
    "v21_224_225_dependency_crosscheck.csv",
    "v21_226_summary.json",
]

MASTER_FIELDS = ["source_path","relative_path","planned_action_from_v21_226","dry_run_future_action","source_exists","source_size_bytes","proposed_target_path","target_root_type","target_path_valid","target_under_allowed_root","duplicate_target_path","protected_blocker","user_review_blocker","delete_blocker","yfinance_active_chain_blocker","pointer_required","sha256_required","sha256_status","sha256","dry_run_pass","reason","notes"]
CACHE_FIELDS = ["source_path","proposed_cache_path","cache_category","source_exists","active_runtime_needed","target_path_valid","sha256_status","dry_run_pass","reason"]
ARCHIVE_FIELDS = ["source_path","proposed_archive_path","archive_category","protected_evidence","user_review_required","target_path_valid","sha256_status","dry_run_pass","reason"]
QUARANTINE_FIELDS = ["source_path","proposed_quarantine_path","reason","target_path_valid","user_review_required","dry_run_pass"]
DELETE_FIELDS = ["source_path","size_bytes","reason","source_exists","required_pre_delete_checks","protected_blocker","user_review_blocker","archive_or_cache_copy_required","immediate_delete_allowed","dry_run_delete_allowed_now","dry_run_pass"]
REPO_FIELDS = ["source_path","reason","lightweight_policy","source_size_bytes","pointer_required","keep_pass","notes"]
REVIEW_FIELDS = ["source_path","project_name","reason","recommended_review_action","blocks_delete","blocks_migration","notes"]
PROTECTED_FIELDS = ["source_path","reason","protected_by","no_action_until","dry_run_pass"]
POINTER_FIELDS = ["source_path","future_repo_pointer_path","target_external_path","pointer_type","required_fields","pointer_path_valid","target_path_valid","dry_run_pass"]
COLLISION_FIELDS = ["proposed_target_path","target_root_type","planned_action_count","source_paths","collision_status","severity","notes"]
MISSING_FIELDS = ["source_path","planned_action","source_exists","severity","reason","notes"]
HASH_FIELDS = ["source_path","size_bytes","sha256_required","sha256_status","sha256","hash_skipped_reason","notes"]
ROOT_FIELDS = ["root_type","planned_root_path","exists","is_directory","will_create_in_v21_228","dry_run_created_now","notes"]
STORAGE_FIELDS = ["category","planned_file_count","planned_total_bytes","planned_total_mb","projected_repo_bytes_reducible_after_future_delete","projected_external_bytes_to_cache","projected_external_bytes_to_archive","projected_external_bytes_to_quarantine","notes"]
ORDER_FIELDS = ["step_number","future_stage","simulated_action","allowed_now","allowed_in_v21_228","allowed_in_v21_235","prerequisite","notes"]
CONSISTENCY_FIELDS = ["check_name","expected","actual","pass","severity","notes"]


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")


def as_bool(v: Any) -> bool:
    return str(v).strip().lower() in {"true", "1", "yes"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def root_type_for(action: str) -> str:
    return {
        "MOVE_TO_CACHE_PLAN": "cache",
        "MOVE_TO_ARCHIVE_PLAN": "archive",
        "QUARANTINE_PLAN": "quarantine",
    }.get(action, "")


def future_action(action: str) -> str:
    return {
        "KEEP_IN_REPO": "KEEP_IN_REPO",
        "MOVE_TO_CACHE_PLAN": "COPY_TO_CACHE_FUTURE",
        "MOVE_TO_ARCHIVE_PLAN": "COPY_TO_ARCHIVE_FUTURE",
        "QUARANTINE_PLAN": "COPY_TO_QUARANTINE_FUTURE",
        "DELETE_AFTER_VERIFICATION_PLAN": "DELETE_AFTER_VERIFICATION_FUTURE",
        "USER_REVIEW_REQUIRED": "USER_REVIEW_REQUIRED_BEFORE_ACTION",
        "PROTECTED_NO_ACTION": "PROTECTED_NO_ACTION",
        "UNKNOWN_REVIEW_REQUIRED": "UNKNOWN_REVIEW_REQUIRED",
    }.get(action, "UNKNOWN_REVIEW_REQUIRED")


def allowed_root_for(root_type: str, cache_root: Path, archive_root: Path, quarantine_root: Path) -> Path | None:
    return {"cache": cache_root, "archive": archive_root, "quarantine": quarantine_root}.get(root_type)


def target_valid(row: dict[str, str], cache_root: Path, archive_root: Path, quarantine_root: Path) -> tuple[bool, bool, str]:
    action = row.get("target_action", "")
    target = row.get("proposed_target_path", "")
    rt = root_type_for(action)
    if action not in {"MOVE_TO_CACHE_PLAN", "MOVE_TO_ARCHIVE_PLAN", "QUARANTINE_PLAN"}:
        return True, True, rt
    if not target:
        return False, False, rt
    root = allowed_root_for(rt, cache_root, archive_root, quarantine_root)
    if root is None:
        return False, False, rt
    try:
        p = Path(target)
    except Exception:
        return False, False, rt
    return True, is_relative_to(p, root), rt


def hash_status(source: Path, exists: bool, size: int, required: bool, threshold: int, hash_large: bool) -> tuple[str, str, str]:
    if not required:
        return "NOT_REQUIRED", "", ""
    if not exists:
        return "SOURCE_MISSING", "", "source missing"
    if size > threshold and not hash_large:
        return "HASH_DEFERRED_TO_COPY_ONLY_STAGE", "", "source exceeds dry-run hash threshold"
    return "HASH_COMPUTED", sha256_file(source), ""


def duplicate_targets(plan: list[dict[str, str]]) -> set[str]:
    counts: dict[str, int] = {}
    for row in plan:
        target = row.get("proposed_target_path", "")
        if target:
            counts[target.lower()] = counts.get(target.lower(), 0) + 1
    return {target for target, count in counts.items() if count > 1}


def build_master(plan: list[dict[str, str]], cache_root: Path, archive_root: Path, quarantine_root: Path, hash_threshold: int, hash_large: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    dups = duplicate_targets(plan)
    master: list[dict[str, Any]] = []
    missing_rows: list[dict[str, Any]] = []
    hash_rows: list[dict[str, Any]] = []
    for row in plan:
        action = row.get("target_action", "")
        source = Path(row.get("source_path", ""))
        exists = source.exists()
        size = source.stat().st_size if exists and source.is_file() else int(row.get("size_bytes") or 0)
        valid, under_root, rt = target_valid(row, cache_root, archive_root, quarantine_root)
        duplicate = bool(row.get("proposed_target_path")) and row.get("proposed_target_path", "").lower() in dups
        protected = as_bool(row.get("protected_by_v21_224")) or as_bool(row.get("protected_by_v21_225"))
        review = as_bool(row.get("requires_user_review"))
        delete_blocker = action == "DELETE_AFTER_VERIFICATION_PLAN" and (protected or review or as_bool(row.get("active_dependency")))
        yfin_block = as_bool(row.get("yfinance_related")) and action in {"KEEP_IN_REPO", "MOVE_TO_CACHE_PLAN"}
        required_copy = action in {"MOVE_TO_CACHE_PLAN", "MOVE_TO_ARCHIVE_PLAN", "QUARANTINE_PLAN"}
        sha_status, sha, skip = hash_status(source, exists, size, as_bool(row.get("sha256_required")), hash_threshold, hash_large)
        hard_fail = False
        if required_copy and (not exists or not valid or not under_root or duplicate):
            hard_fail = True
        if action == "DELETE_AFTER_VERIFICATION_PLAN" and protected:
            hard_fail = True
        if yfin_block:
            hard_fail = True
        passed = not hard_fail
        reason = row.get("reason", "")
        if not exists:
            severity = "ERROR" if required_copy else "WARN"
            missing_rows.append({"source_path": str(source), "planned_action": action, "source_exists": False, "severity": severity, "reason": reason, "notes": "dry-run only; no source mutation"})
        hash_rows.append({"source_path": str(source), "size_bytes": size, "sha256_required": as_bool(row.get("sha256_required")), "sha256_status": sha_status, "sha256": sha, "hash_skipped_reason": skip, "notes": "hash stored only in V21.227 output"})
        master.append({
            "source_path": str(source),
            "relative_path": row.get("relative_path", ""),
            "planned_action_from_v21_226": action,
            "dry_run_future_action": future_action(action),
            "source_exists": exists,
            "source_size_bytes": size,
            "proposed_target_path": row.get("proposed_target_path", ""),
            "target_root_type": rt,
            "target_path_valid": valid,
            "target_under_allowed_root": under_root,
            "duplicate_target_path": duplicate,
            "protected_blocker": protected and action == "DELETE_AFTER_VERIFICATION_PLAN",
            "user_review_blocker": review,
            "delete_blocker": delete_blocker,
            "yfinance_active_chain_blocker": yfin_block,
            "pointer_required": as_bool(row.get("pointer_required")),
            "sha256_required": as_bool(row.get("sha256_required")),
            "sha256_status": sha_status,
            "sha256": sha,
            "dry_run_pass": passed,
            "reason": reason,
            "notes": "dry_run_only_no_copy_move_delete",
        })
    return master, missing_rows, hash_rows


def collision_audit(master: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in master:
        target = row["proposed_target_path"]
        if target:
            groups.setdefault(target.lower(), []).append(row)
    rows = []
    for _, items in sorted(groups.items()):
        first = items[0]
        collision = len(items) > 1
        rows.append({
            "proposed_target_path": first["proposed_target_path"],
            "target_root_type": first["target_root_type"],
            "planned_action_count": len(items),
            "source_paths": "|".join(i["source_path"] for i in items[:20]),
            "collision_status": "DUPLICATE_TARGET_PATH" if collision else "UNIQUE",
            "severity": "ERROR" if collision else "OK",
            "notes": "dry-run target collision audit",
        })
    return rows


def filter_action(master: list[dict[str, Any]], action: str) -> list[dict[str, Any]]:
    return [r for r in master if r["planned_action_from_v21_226"] == action]


def policy_gate() -> dict[str, Any]:
    return {
        "dry_run_only": True,
        "copy_allowed_now": False,
        "move_allowed_now": False,
        "delete_allowed_now": False,
        "external_root_creation_allowed_now": False,
        "mutation_allowed_now": False,
        "data_fetch_allowed": False,
        "yfinance_allowed": False,
        "moomoo_import_allowed": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
        "next_allowed_stage": "V21.228_EXTERNAL_CACHE_AND_ARCHIVE_MIGRATION_COPY_ONLY",
    }


def root_readiness(cache_root: Path, archive_root: Path, quarantine_root: Path) -> list[dict[str, Any]]:
    rows = []
    for root_type, path in [("cache", cache_root), ("archive", archive_root), ("quarantine", quarantine_root)]:
        rows.append({"root_type": root_type, "planned_root_path": str(path), "exists": path.exists(), "is_directory": path.is_dir(), "will_create_in_v21_228": not path.exists(), "dry_run_created_now": False, "notes": "existence check only; no external root creation"})
    return rows


def storage_projection(master: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in master:
        groups.setdefault(row["planned_action_from_v21_226"], []).append(row)
    rows = []
    for category, items in sorted(groups.items()):
        total = sum(int(i["source_size_bytes"] or 0) for i in items)
        rows.append({
            "category": category,
            "planned_file_count": len(items),
            "planned_total_bytes": total,
            "planned_total_mb": round(total / (1024 * 1024), 3),
            "projected_repo_bytes_reducible_after_future_delete": total if category in {"MOVE_TO_CACHE_PLAN","MOVE_TO_ARCHIVE_PLAN","QUARANTINE_PLAN","DELETE_AFTER_VERIFICATION_PLAN"} else 0,
            "projected_external_bytes_to_cache": total if category == "MOVE_TO_CACHE_PLAN" else 0,
            "projected_external_bytes_to_archive": total if category == "MOVE_TO_ARCHIVE_PLAN" else 0,
            "projected_external_bytes_to_quarantine": total if category == "QUARANTINE_PLAN" else 0,
            "notes": "projection only; no bytes moved",
        })
    return rows


def execution_order(order_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    out = []
    for row in order_rows:
        stage = row.get("phase_name", "")
        out.append({
            "step_number": row.get("step_number", ""),
            "future_stage": stage,
            "simulated_action": row.get("action", ""),
            "allowed_now": stage == "V21.227 migration dry-run",
            "allowed_in_v21_228": stage == "V21.228 copy-only externalization",
            "allowed_in_v21_235": stage == "V21.235 clean delete after verification",
            "prerequisite": row.get("prerequisite", ""),
            "notes": "V21.227 only simulates; future stages require explicit invocation",
        })
    return out


def consistency(plan: list[dict[str, str]], summary: dict[str, Any], policy: dict[str, Any]) -> list[dict[str, Any]]:
    checks = []
    expected_total = int(summary.get("total_planned_items", len(plan)) or len(plan))
    checks.append({"check_name": "total_planned_items", "expected": expected_total, "actual": len(plan), "pass": expected_total == len(plan), "severity": "ERROR", "notes": "V21.226 summary vs master count"})
    for key in ["immediate_delete_allowed", "immediate_move_allowed", "immediate_copy_allowed"]:
        actual = str(summary.get(key, "")).lower()
        checks.append({"check_name": key, "expected": "false", "actual": actual, "pass": actual == "false", "severity": "ERROR", "notes": "immediate actions must remain disabled"})
    checks.append({"check_name": "repo_lightweight_policy", "expected": "present", "actual": "present" if policy else "missing", "pass": bool(policy), "severity": "ERROR", "notes": "policy gate input"})
    return checks


def required_inputs_present(v226: Path) -> list[str]:
    return [name for name in REQUIRED_V226 if not (v226 / name).exists()]


def write_report(path: Path, summary: dict[str, Any]) -> None:
    keys = ["final_status","final_decision","total_dry_run_items","dry_run_pass_count","dry_run_fail_count","missing_source_count","path_collision_count","invalid_target_path_count","cache_action_count","archive_action_count","quarantine_action_count","delete_after_verification_action_count","user_review_blocker_count","protected_no_action_count","pointer_manifest_action_count","projected_repo_bytes_reducible","projected_cache_bytes","projected_archive_bytes","projected_quarantine_bytes","warning_count","error_count"]
    path.write_text("\n".join([STAGE, *[f"{k}={summary[k]}" for k in keys], "dry_run_only=True", "copy_allowed_now=False", "move_allowed_now=False", "delete_allowed_now=False", "external_root_creation_allowed_now=False"]) + "\n", encoding="utf-8")


def run(repo_root: Path | None = None, output_dir: Path | None = None, v21_226_output_dir: Path | None = None, cache_root: Path = DEFAULT_CACHE_ROOT, archive_root: Path = DEFAULT_ARCHIVE_ROOT, quarantine_root: Path = DEFAULT_QUARANTINE_ROOT, hash_threshold_bytes: int = HASH_THRESHOLD, hash_large: bool = False) -> dict[str, Any]:
    root = (repo_root or default_repo_root()).resolve()
    out = (output_dir or root / OUT_REL).resolve()
    v226 = (v21_226_output_dir or root / V226_REL).resolve()
    out.mkdir(parents=True, exist_ok=True)
    missing_inputs = required_inputs_present(v226)
    if missing_inputs:
        summary = {
            "final_status": FAIL_INPUT_STATUS, "final_decision": "V21_226_SEPARATION_PLAN_INPUTS_REQUIRED", "repo_root": str(root), "output_dir": str(out), "v21_226_input_found": False,
            "total_dry_run_items": 0, "dry_run_pass_count": 0, "dry_run_fail_count": 0, "missing_source_count": 0, "path_collision_count": 0, "invalid_target_path_count": 0,
            "cache_action_count": 0, "archive_action_count": 0, "quarantine_action_count": 0, "delete_after_verification_action_count": 0, "user_review_blocker_count": 0,
            "protected_no_action_count": 0, "pointer_manifest_action_count": 0, "hash_computed_count": 0, "hash_deferred_count": 0, "projected_repo_bytes_reducible": 0,
            "projected_cache_bytes": 0, "projected_archive_bytes": 0, "projected_quarantine_bytes": 0, "external_cache_root_exists": cache_root.exists(), "external_archive_root_exists": archive_root.exists(), "external_quarantine_root_exists": quarantine_root.exists(),
            "dry_run_only": True, "copy_allowed_now": False, "move_allowed_now": False, "delete_allowed_now": False, "external_root_creation_allowed_now": False, "yfinance_used": False, "data_fetch_used": False, "moomoo_import_used": False, "broker_action_allowed": False, "official_adoption_allowed": False, "research_only": True, "warning_count": 0, "error_count": 1, "missing_inputs": missing_inputs,
        }
        write_json(out / "v21_227_summary.json", summary)
        return summary
    try:
        plan = read_csv(v226 / "separation_plan_master.csv")
        cache_plan = read_csv(v226 / "cache_migration_plan.csv")
        archive_plan = read_csv(v226 / "archive_migration_plan.csv")
        quarantine_plan = read_csv(v226 / "quarantine_plan.csv")
        delete_plan = read_csv(v226 / "delete_after_verification_plan.csv")
        repo_keep = read_csv(v226 / "repo_keep_plan.csv")
        review_plan = read_csv(v226 / "user_review_required_plan.csv")
        protected_plan = read_csv(v226 / "protected_no_action_plan.csv")
        pointer_plan = read_csv(v226 / "pointer_manifest_plan.csv")
        order_rows = read_csv(v226 / "migration_order_plan.csv")
        summary226 = read_json(v226 / "v21_226_summary.json")
        policy226 = read_json(v226 / "repo_lightweight_output_policy.json")
        master, missing_sources, hash_rows = build_master(plan, cache_root, archive_root, quarantine_root, hash_threshold_bytes, hash_large)
        collisions = collision_audit(master)
        roots = root_readiness(cache_root, archive_root, quarantine_root)
        storage = storage_projection(master)
        order = execution_order(order_rows)
        consistency_rows = consistency(plan, summary226, policy226)
        invalid_targets = [r for r in master if not r["target_path_valid"] or not r["target_under_allowed_root"]]
        collision_count = sum(1 for r in collisions if r["collision_status"] != "UNIQUE")
        hard_fail = sum(1 for r in master if not r["dry_run_pass"] and r["planned_action_from_v21_226"] in {"MOVE_TO_CACHE_PLAN","MOVE_TO_ARCHIVE_PLAN","QUARANTINE_PLAN","DELETE_AFTER_VERIFICATION_PLAN"})
        final_status = FAIL_PLAN_STATUS if hard_fail or collision_count or invalid_targets else WARN_STATUS if review_plan else PASS_STATUS
        proj_cache = sum(r["projected_external_bytes_to_cache"] for r in storage)
        proj_archive = sum(r["projected_external_bytes_to_archive"] for r in storage)
        proj_quarantine = sum(r["projected_external_bytes_to_quarantine"] for r in storage)
        proj_reduce = sum(r["projected_repo_bytes_reducible_after_future_delete"] for r in storage)
        summary = {
            "final_status": final_status,
            "final_decision": FINAL_DECISION,
            "repo_root": str(root),
            "output_dir": str(out),
            "v21_226_input_found": True,
            "total_dry_run_items": len(master),
            "dry_run_pass_count": sum(1 for r in master if r["dry_run_pass"]),
            "dry_run_fail_count": sum(1 for r in master if not r["dry_run_pass"]),
            "missing_source_count": len(missing_sources),
            "path_collision_count": collision_count,
            "invalid_target_path_count": len(invalid_targets),
            "cache_action_count": len(cache_plan),
            "archive_action_count": len(archive_plan),
            "quarantine_action_count": len(quarantine_plan),
            "delete_after_verification_action_count": len(delete_plan),
            "user_review_blocker_count": len(review_plan),
            "protected_no_action_count": len(protected_plan),
            "pointer_manifest_action_count": len(pointer_plan),
            "hash_computed_count": sum(1 for r in hash_rows if r["sha256_status"] == "HASH_COMPUTED"),
            "hash_deferred_count": sum(1 for r in hash_rows if r["sha256_status"] == "HASH_DEFERRED_TO_COPY_ONLY_STAGE"),
            "projected_repo_bytes_reducible": proj_reduce,
            "projected_cache_bytes": proj_cache,
            "projected_archive_bytes": proj_archive,
            "projected_quarantine_bytes": proj_quarantine,
            "external_cache_root_exists": cache_root.exists(),
            "external_archive_root_exists": archive_root.exists(),
            "external_quarantine_root_exists": quarantine_root.exists(),
            **policy_gate(),
            "yfinance_used": False,
            "data_fetch_used": False,
            "moomoo_import_used": False,
            "warning_count": 1 if final_status == WARN_STATUS else 0,
            "error_count": 1 if final_status == FAIL_PLAN_STATUS else 0,
        }
        write_csv(out / "dry_run_master_plan.csv", master, MASTER_FIELDS)
        write_csv(out / "dry_run_cache_actions.csv", [{"source_path": r.get("source_path"), "proposed_cache_path": r.get("proposed_cache_path"), "cache_category": r.get("cache_category"), "source_exists": Path(r.get("source_path","")).exists(), "active_runtime_needed": r.get("active_runtime_needed"), "target_path_valid": True, "sha256_status": next((m["sha256_status"] for m in master if m["source_path"] == r.get("source_path")), ""), "dry_run_pass": next((m["dry_run_pass"] for m in master if m["source_path"] == r.get("source_path")), False), "reason": r.get("reason")} for r in cache_plan], CACHE_FIELDS)
        write_csv(out / "dry_run_archive_actions.csv", [{"source_path": r.get("source_path"), "proposed_archive_path": r.get("proposed_archive_path"), "archive_category": r.get("archive_category"), "protected_evidence": r.get("protected_evidence"), "user_review_required": r.get("user_review_required"), "target_path_valid": True, "sha256_status": next((m["sha256_status"] for m in master if m["source_path"] == r.get("source_path")), ""), "dry_run_pass": next((m["dry_run_pass"] for m in master if m["source_path"] == r.get("source_path")), False), "reason": r.get("reason")} for r in archive_plan], ARCHIVE_FIELDS)
        write_csv(out / "dry_run_quarantine_actions.csv", [{"source_path": r.get("source_path"), "proposed_quarantine_path": r.get("proposed_quarantine_path"), "reason": r.get("reason"), "target_path_valid": True, "user_review_required": r.get("user_review_required"), "dry_run_pass": next((m["dry_run_pass"] for m in master if m["source_path"] == r.get("source_path")), False)} for r in quarantine_plan], QUARANTINE_FIELDS)
        write_csv(out / "dry_run_delete_after_verification_actions.csv", [{"source_path": r.get("source_path"), "size_bytes": r.get("size_bytes"), "reason": r.get("reason"), "source_exists": Path(r.get("source_path","")).exists(), "required_pre_delete_checks": r.get("required_pre_delete_checks"), "protected_blocker": r.get("protected_blocker"), "user_review_blocker": r.get("user_review_blocker"), "archive_or_cache_copy_required": r.get("archive_or_cache_copy_required"), "immediate_delete_allowed": False, "dry_run_delete_allowed_now": False, "dry_run_pass": next((m["dry_run_pass"] for m in master if m["source_path"] == r.get("source_path")), True)} for r in delete_plan], DELETE_FIELDS)
        write_csv(out / "dry_run_repo_keep_actions.csv", [{"source_path": r.get("source_path"), "reason": r.get("reason"), "lightweight_policy": r.get("lightweight_policy"), "source_size_bytes": Path(r.get("source_path","")).stat().st_size if Path(r.get("source_path","")).exists() else "", "pointer_required": r.get("pointer_required"), "keep_pass": True, "notes": "repo keep dry-run"} for r in repo_keep], REPO_FIELDS)
        write_csv(out / "dry_run_user_review_blockers.csv", [{"source_path": r.get("source_path"), "project_name": r.get("project_name"), "reason": r.get("reason"), "recommended_review_action": r.get("recommended_review_action"), "blocks_delete": True, "blocks_migration": True, "notes": "user review blocks action"} for r in review_plan], REVIEW_FIELDS)
        write_csv(out / "dry_run_protected_no_action.csv", [{"source_path": r.get("source_path"), "reason": r.get("reason"), "protected_by": r.get("protected_by"), "no_action_until": r.get("no_action_until"), "dry_run_pass": True} for r in protected_plan], PROTECTED_FIELDS)
        write_csv(out / "dry_run_pointer_manifest_actions.csv", [{"source_path": r.get("source_path"), "future_repo_pointer_path": r.get("future_repo_pointer_path"), "target_external_path": r.get("target_external_path"), "pointer_type": r.get("pointer_type"), "required_fields": r.get("required_fields"), "pointer_path_valid": bool(r.get("future_repo_pointer_path")), "target_path_valid": bool(r.get("target_external_path")), "dry_run_pass": bool(r.get("future_repo_pointer_path")) and bool(r.get("target_external_path"))} for r in pointer_plan], POINTER_FIELDS)
        write_csv(out / "dry_run_path_collision_audit.csv", collisions, COLLISION_FIELDS)
        write_csv(out / "dry_run_missing_source_audit.csv", missing_sources, MISSING_FIELDS)
        write_csv(out / "dry_run_hash_feasibility_audit.csv", hash_rows, HASH_FIELDS)
        write_csv(out / "dry_run_external_root_readiness.csv", roots, ROOT_FIELDS)
        write_csv(out / "dry_run_storage_projection.csv", storage, STORAGE_FIELDS)
        write_csv(out / "dry_run_execution_order.csv", order, ORDER_FIELDS)
        write_json(out / "dry_run_policy_gate.json", policy_gate())
        write_csv(out / "v21_226_plan_consistency_audit.csv", consistency_rows, CONSISTENCY_FIELDS)
        write_json(out / "v21_227_summary.json", summary)
        write_report(out / "V21.227_external_migration_dry_run_report.txt", summary)
    except Exception as exc:
        summary = {"final_status": FAIL_PLAN_STATUS, "final_decision": "V21_227_DRY_RUN_GENERATION_FAILED", "repo_root": str(root), "output_dir": str(out), "v21_226_input_found": True, "total_dry_run_items": 0, "dry_run_pass_count": 0, "dry_run_fail_count": 0, "missing_source_count": 0, "path_collision_count": 0, "invalid_target_path_count": 0, "cache_action_count": 0, "archive_action_count": 0, "quarantine_action_count": 0, "delete_after_verification_action_count": 0, "user_review_blocker_count": 0, "protected_no_action_count": 0, "pointer_manifest_action_count": 0, "hash_computed_count": 0, "hash_deferred_count": 0, "projected_repo_bytes_reducible": 0, "projected_cache_bytes": 0, "projected_archive_bytes": 0, "projected_quarantine_bytes": 0, "external_cache_root_exists": cache_root.exists(), "external_archive_root_exists": archive_root.exists(), "external_quarantine_root_exists": quarantine_root.exists(), **policy_gate(), "yfinance_used": False, "data_fetch_used": False, "moomoo_import_used": False, "warning_count": 0, "error_count": 1, "error_message": f"{type(exc).__name__}: {exc}"}
        write_json(out / "v21_227_summary.json", summary)
    for key in ["final_status","final_decision","total_dry_run_items","dry_run_pass_count","dry_run_fail_count","missing_source_count","path_collision_count","invalid_target_path_count","cache_action_count","archive_action_count","quarantine_action_count","delete_after_verification_action_count","user_review_blocker_count","protected_no_action_count","pointer_manifest_action_count","projected_repo_bytes_reducible","projected_cache_bytes","projected_archive_bytes","projected_quarantine_bytes","warning_count","error_count"]:
        print(f"{key}={summary[key]}")
    print(f"summary_path={out / 'v21_227_summary.json'}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=STAGE)
    p.add_argument("--repo-root")
    p.add_argument("--output-dir")
    p.add_argument("--v21-226-output-dir")
    p.add_argument("--cache-root", default=str(DEFAULT_CACHE_ROOT))
    p.add_argument("--archive-root", default=str(DEFAULT_ARCHIVE_ROOT))
    p.add_argument("--quarantine-root", default=str(DEFAULT_QUARANTINE_ROOT))
    p.add_argument("--hash-threshold-bytes", type=int, default=HASH_THRESHOLD)
    p.add_argument("--hash-large", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(
        repo_root=Path(args.repo_root) if args.repo_root else None,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        v21_226_output_dir=Path(args.v21_226_output_dir) if args.v21_226_output_dir else None,
        cache_root=Path(args.cache_root),
        archive_root=Path(args.archive_root),
        quarantine_root=Path(args.quarantine_root),
        hash_threshold_bytes=args.hash_threshold_bytes,
        hash_large=args.hash_large,
    )
    return 1 if summary["final_status"] in {FAIL_INPUT_STATUS, FAIL_PLAN_STATUS} else 0


if __name__ == "__main__":
    sys.exit(main())
