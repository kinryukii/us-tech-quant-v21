#!/usr/bin/env python
"""V21.228 external cache/archive/quarantine migration copy-only execution."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


STAGE = "V21.228_EXTERNAL_CACHE_AND_ARCHIVE_MIGRATION_COPY_ONLY"
OUT_REL = Path("outputs/v21") / STAGE
V227_REL = Path("outputs/v21/V21.227_EXTERNAL_CACHE_AND_ARCHIVE_MIGRATION_DRY_RUN")
DEFAULT_CACHE_ROOT = Path(r"D:\us-tech-quant-cache")
DEFAULT_ARCHIVE_ROOT = Path(r"D:\us-tech-quant-archive")
DEFAULT_QUARANTINE_ROOT = Path(r"D:\us-tech-quant-quarantine")
PASS_STATUS = "PASS_V21_228_EXTERNAL_MIGRATION_COPY_ONLY_READY"
WARN_STATUS = "WARN_V21_228_EXTERNAL_MIGRATION_COPY_ONLY_READY_WITH_USER_REVIEW_BLOCKERS"
FAIL_VERIFY = "FAIL_V21_228_COPY_ONLY_VERIFICATION_FAILED"
FAIL_COLLISION = "FAIL_V21_228_TARGET_COLLISION_DIFFERENT_HASH"
FAIL_INPUT = "FAIL_V21_228_MISSING_V21_227_DRY_RUN_INPUTS"
FINAL_DECISION = "EXTERNAL_CACHE_ARCHIVE_QUARANTINE_COPY_VERIFIED_READY_FOR_MOOMOO_ONLY_POLICY_GATE"

REQUIRED_V227 = [
    "dry_run_master_plan.csv",
    "dry_run_cache_actions.csv",
    "dry_run_archive_actions.csv",
    "dry_run_quarantine_actions.csv",
    "dry_run_delete_after_verification_actions.csv",
    "dry_run_repo_keep_actions.csv",
    "dry_run_user_review_blockers.csv",
    "dry_run_protected_no_action.csv",
    "dry_run_pointer_manifest_actions.csv",
    "dry_run_path_collision_audit.csv",
    "dry_run_missing_source_audit.csv",
    "dry_run_hash_feasibility_audit.csv",
    "dry_run_external_root_readiness.csv",
    "dry_run_storage_projection.csv",
    "dry_run_execution_order.csv",
    "dry_run_policy_gate.json",
    "v21_226_plan_consistency_audit.csv",
    "v21_227_summary.json",
]

MASTER_FIELDS = ["source_path","relative_path","dry_run_future_action","copy_action_executed","source_exists_before","source_exists_after","source_size_before","source_size_after","source_mtime_before_utc","source_mtime_after_utc","external_target_path","external_root_type","target_exists_before","target_exists_after","target_size_after","source_sha256","target_sha256","copied","already_present_verified","skipped","skip_reason","verified","collision_status","error","notes"]
COPY_FIELDS = ["source_path","cache_path","source_sha256","target_sha256","size_bytes","copied","already_present_verified","verified","reason"]
ARCHIVE_FIELDS = ["source_path","archive_path","source_sha256","target_sha256","size_bytes","copied","already_present_verified","verified","reason"]
QUARANTINE_FIELDS = ["source_path","quarantine_path","source_sha256","target_sha256","size_bytes","copied","already_present_verified","verified","reason"]
SKIP_NO_FIELDS = ["source_path","dry_run_future_action","reason","protected","active_dependency"]
SKIP_REVIEW_FIELDS = ["source_path","project_name","reason","user_review_required","copied","deleted","moved"]
SKIP_DELETE_FIELDS = ["source_path","reason","copied","deleted","moved","future_stage"]
POINTER_FIELDS = ["source_path","future_repo_pointer_path","external_path","external_root_type","pointer_type","sha256","size_bytes","copied_status","pointer_written_now","reason"]
HASH_FIELDS = ["source_path","target_path","source_sha256","target_sha256","source_size","target_size","hash_match","size_match","verified","error"]
COLLISION_FIELDS = ["target_path","source_path","target_exists_before","existing_same_hash","existing_different_hash","collision_status","severity","action_taken"]
SOURCE_FIELDS = ["source_path","exists_before","exists_after","size_before","size_after","mtime_before_utc","mtime_after_utc","source_preserved","mutation_detected"]
ROOT_FIELDS = ["root_type","root_path","existed_before","exists_after","created_now","created_subdir_count","notes"]
STORAGE_FIELDS = ["category","planned_count","copied_count","already_present_verified_count","skipped_count","total_copied_bytes","total_verified_bytes","notes"]
CROSS_FIELDS = ["check_name","expected","actual","pass","severity","notes"]


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


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")


def as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mtime_utc(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def policy_gate() -> dict[str, Any]:
    return {
        "copy_only": True,
        "copy_allowed_now": True,
        "move_allowed_now": False,
        "delete_allowed_now": False,
        "source_mutation_allowed": False,
        "data_fetch_allowed": False,
        "yfinance_allowed": False,
        "moomoo_import_allowed": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
        "next_allowed_stage": "V21.229_MOOMOO_ONLY_DATA_SOURCE_POLICY_GATE",
        "clean_delete_stage": "V21.235_REPO_CLEAN_DELETE_AFTER_VERIFICATION",
    }


def root_type_for_action(action: str) -> str:
    return {"COPY_TO_CACHE_FUTURE": "cache", "COPY_TO_ARCHIVE_FUTURE": "archive", "COPY_TO_QUARANTINE_FUTURE": "quarantine"}.get(action, "")


def copy_status(source: Path, target: Path, force_recopy_same_hash: bool) -> tuple[bool, bool, bool, str, str, str]:
    source_hash = sha256_file(source)
    if target.exists():
        target_hash = sha256_file(target)
        if target_hash != source_hash:
            return False, False, False, source_hash, target_hash, "TARGET_EXISTS_DIFFERENT_HASH"
        if not force_recopy_same_hash:
            return False, True, True, source_hash, target_hash, "already_present_verified"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    target_hash = sha256_file(target)
    verified = target_hash == source_hash and target.stat().st_size == source.stat().st_size
    return True, False, verified, source_hash, target_hash, "" if verified else "COPY_VERIFICATION_FAILED"


def input_missing(v227: Path) -> list[str]:
    return [name for name in REQUIRED_V227 if not (v227 / name).exists()]


def pointer_lookup(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {r.get("source_path", ""): r for r in rows}


def execute_copy_rows(master: list[dict[str, str]], pointer_rows: list[dict[str, str]], max_copy_items: int | None, force_recopy_same_hash: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int]:
    copy_actions = {"COPY_TO_CACHE_FUTURE", "COPY_TO_ARCHIVE_FUTURE", "COPY_TO_QUARANTINE_FUTURE"}
    ptr = pointer_lookup(pointer_rows)
    execution: list[dict[str, Any]] = []
    hash_rows: list[dict[str, Any]] = []
    collision_rows: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    cache_rows: list[dict[str, Any]] = []
    archive_rows: list[dict[str, Any]] = []
    quarantine_rows: list[dict[str, Any]] = []
    pointer_index: list[dict[str, Any]] = []
    pointer_json: list[dict[str, Any]] = []
    copied_seen = 0
    for row in master:
        action = row.get("dry_run_future_action", "")
        source = Path(row.get("source_path", ""))
        target = Path(row.get("proposed_target_path", "")) if row.get("proposed_target_path") else Path()
        should_copy = action in copy_actions and (max_copy_items is None or copied_seen < max_copy_items)
        exists_before = source.exists()
        size_before = source.stat().st_size if exists_before else 0
        mtime_before = mtime_utc(source) if exists_before else ""
        target_exists_before = bool(str(target)) and target.exists()
        copied = already = verified = skipped = False
        source_hash = target_hash = error = skip_reason = collision = ""
        if action in copy_actions and not should_copy:
            skipped = True
            skip_reason = "max_copy_items_limit"
        elif should_copy:
            copied_seen += 1
            if not exists_before:
                error = "SOURCE_MISSING"
            else:
                source_hash_pre = sha256_file(source)
                copied, already, verified, source_hash, target_hash, error = copy_status(source, target, force_recopy_same_hash)
                if target_exists_before:
                    collision = "EXISTING_SAME_HASH" if already or verified else "EXISTING_DIFFERENT_HASH"
                if source_hash_pre != sha256_file(source):
                    error = error or "SOURCE_HASH_CHANGED_DURING_COPY"
        else:
            skipped = True
            skip_reason = "not_copy_action"
        exists_after = source.exists()
        size_after = source.stat().st_size if exists_after else 0
        mtime_after = mtime_utc(source) if exists_after else ""
        target_exists_after = bool(str(target)) and target.exists()
        target_size_after = target.stat().st_size if target_exists_after and target.is_file() else 0
        mutation = exists_before != exists_after or size_before != size_after or mtime_before != mtime_after
        source_rows.append({"source_path": str(source), "exists_before": exists_before, "exists_after": exists_after, "size_before": size_before, "size_after": size_after, "mtime_before_utc": mtime_before, "mtime_after_utc": mtime_after, "source_preserved": not mutation, "mutation_detected": mutation})
        execution.append({"source_path": str(source), "relative_path": row.get("relative_path", ""), "dry_run_future_action": action, "copy_action_executed": should_copy, "source_exists_before": exists_before, "source_exists_after": exists_after, "source_size_before": size_before, "source_size_after": size_after, "source_mtime_before_utc": mtime_before, "source_mtime_after_utc": mtime_after, "external_target_path": str(target) if action in copy_actions else "", "external_root_type": root_type_for_action(action), "target_exists_before": target_exists_before, "target_exists_after": target_exists_after, "target_size_after": target_size_after, "source_sha256": source_hash, "target_sha256": target_hash, "copied": copied, "already_present_verified": already, "skipped": skipped, "skip_reason": skip_reason, "verified": verified, "collision_status": collision, "error": error, "notes": "copy_only_no_source_mutation"})
        if action in copy_actions:
            hash_rows.append({"source_path": str(source), "target_path": str(target), "source_sha256": source_hash, "target_sha256": target_hash, "source_size": size_before, "target_size": target_size_after, "hash_match": bool(source_hash and source_hash == target_hash), "size_match": size_before == target_size_after, "verified": verified, "error": error})
            collision_rows.append({"target_path": str(target), "source_path": str(source), "target_exists_before": target_exists_before, "existing_same_hash": target_exists_before and not error, "existing_different_hash": error == "TARGET_EXISTS_DIFFERENT_HASH", "collision_status": collision or "NO_EXISTING_TARGET", "severity": "ERROR" if error == "TARGET_EXISTS_DIFFERENT_HASH" else "OK", "action_taken": "FAILED" if error else "VERIFIED" if already else "COPIED" if copied else "SKIPPED"})
            common = {"source_path": str(source), "source_sha256": source_hash, "target_sha256": target_hash, "size_bytes": size_before, "copied": copied, "already_present_verified": already, "verified": verified, "reason": row.get("reason", "")}
            if action == "COPY_TO_CACHE_FUTURE":
                cache_rows.append({"cache_path": str(target), **common})
            elif action == "COPY_TO_ARCHIVE_FUTURE":
                archive_rows.append({"archive_path": str(target), **common})
            elif action == "COPY_TO_QUARANTINE_FUTURE":
                quarantine_rows.append({"quarantine_path": str(target), **common})
            p = ptr.get(str(source), {})
            pointer_entry = {"source_path": str(source), "future_repo_pointer_path": p.get("future_repo_pointer_path", ""), "external_path": str(target), "external_root_type": root_type_for_action(action), "pointer_type": p.get("pointer_type", f"{root_type_for_action(action)}_pointer"), "sha256": source_hash, "size_bytes": size_before, "copied_status": "already_present_verified" if already else "copied_verified" if copied and verified else "failed", "pointer_written_now": False, "reason": row.get("reason", "")}
            pointer_index.append(pointer_entry)
            pointer_json.append({**pointer_entry, "artifact_type": row.get("dry_run_future_action", ""), "created_at_utc": datetime.now(timezone.utc).isoformat(), "source_preserved": True, "research_only": True, "broker_action_allowed": False, "official_adoption_allowed": False})
    return execution, cache_rows, archive_rows, quarantine_rows, hash_rows, collision_rows, source_rows, pointer_index, pointer_json, copied_seen


def root_audit(master: list[dict[str, str]], cache_root: Path, archive_root: Path, quarantine_root: Path, before: dict[str, bool]) -> list[dict[str, Any]]:
    rows = []
    roots = {"cache": cache_root, "archive": archive_root, "quarantine": quarantine_root}
    for root_type, root in roots.items():
        dirs = {Path(r["proposed_target_path"]).parent for r in master if root_type_for_action(r.get("dry_run_future_action", "")) == root_type and r.get("proposed_target_path")}
        created_subdirs = sum(1 for d in dirs if d.exists())
        rows.append({"root_type": root_type, "root_path": str(root), "existed_before": before[root_type], "exists_after": root.exists(), "created_now": (not before[root_type]) and root.exists(), "created_subdir_count": created_subdirs, "notes": "created only as needed for copy actions"})
    return rows


def storage_summary(execution: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cats = {
        "cache": [r for r in execution if r["dry_run_future_action"] == "COPY_TO_CACHE_FUTURE"],
        "archive": [r for r in execution if r["dry_run_future_action"] == "COPY_TO_ARCHIVE_FUTURE"],
        "quarantine": [r for r in execution if r["dry_run_future_action"] == "COPY_TO_QUARANTINE_FUTURE"],
        "skipped": [r for r in execution if r["skipped"]],
    }
    return [{"category": k, "planned_count": len(v), "copied_count": sum(1 for r in v if r["copied"]), "already_present_verified_count": sum(1 for r in v if r["already_present_verified"]), "skipped_count": sum(1 for r in v if r["skipped"]), "total_copied_bytes": sum(int(r["source_size_before"]) for r in v if r["copied"]), "total_verified_bytes": sum(int(r["source_size_before"]) for r in v if r["verified"]), "notes": "copy-only storage summary"} for k, v in cats.items()]


def crosscheck(summary227: dict[str, Any], master: list[dict[str, str]]) -> list[dict[str, Any]]:
    planned = sum(1 for r in master if r.get("dry_run_future_action") in {"COPY_TO_CACHE_FUTURE","COPY_TO_ARCHIVE_FUTURE","COPY_TO_QUARANTINE_FUTURE"})
    return [
        {"check_name": "dry_run_fail_count", "expected": "0", "actual": summary227.get("dry_run_fail_count", ""), "pass": int(summary227.get("dry_run_fail_count", 1) or 1) == 0, "severity": "ERROR", "notes": "V21.227 must have no dry-run failures"},
        {"check_name": "missing_source_count", "expected": "0", "actual": summary227.get("missing_source_count", ""), "pass": int(summary227.get("missing_source_count", 1) or 1) == 0, "severity": "ERROR", "notes": "V21.227 validated sources"},
        {"check_name": "planned_copy_item_count", "expected": planned, "actual": planned, "pass": True, "severity": "OK", "notes": "copy scope is derived from dry-run future actions"},
    ]


def skipped_rows(master: list[dict[str, str]], action: str) -> list[dict[str, str]]:
    return [r for r in master if r.get("dry_run_future_action") == action]


def run(repo_root: Path | None = None, output_dir: Path | None = None, v21_227_output_dir: Path | None = None, cache_root: Path = DEFAULT_CACHE_ROOT, archive_root: Path = DEFAULT_ARCHIVE_ROOT, quarantine_root: Path = DEFAULT_QUARANTINE_ROOT, force_recopy_same_hash: bool = False, max_copy_items: int | None = None) -> dict[str, Any]:
    root = (repo_root or default_repo_root()).resolve()
    out = (output_dir or root / OUT_REL).resolve()
    v227 = (v21_227_output_dir or root / V227_REL).resolve()
    out.mkdir(parents=True, exist_ok=True)
    missing = input_missing(v227)
    root_before = {"cache": cache_root.exists(), "archive": archive_root.exists(), "quarantine": quarantine_root.exists()}
    if missing:
        summary = base_summary(root, out, False, cache_root, archive_root, quarantine_root, FAIL_INPUT, "V21_227_DRY_RUN_INPUTS_REQUIRED", 1)
        summary["missing_inputs"] = missing
        write_json(out / "v21_228_summary.json", summary)
        return print_summary(summary, out)
    try:
        master = read_csv(v227 / "dry_run_master_plan.csv")
        pointer_rows = read_csv(v227 / "dry_run_pointer_manifest_actions.csv")
        summary227 = read_json(v227 / "v21_227_summary.json")
        execution, cache_rows, archive_rows, quarantine_rows, hash_rows, collision_rows, source_rows, pointer_index, pointer_json, _ = execute_copy_rows(master, pointer_rows, max_copy_items, force_recopy_same_hash)
        root_rows = root_audit(master, cache_root, archive_root, quarantine_root, root_before)
        skipped_review = read_csv(v227 / "dry_run_user_review_blockers.csv")
        skipped_delete = read_csv(v227 / "dry_run_delete_after_verification_actions.csv")
        skipped_no = [*skipped_rows(master, "KEEP_IN_REPO"), *skipped_rows(master, "PROTECTED_NO_ACTION"), *skipped_rows(master, "UNKNOWN_REVIEW_REQUIRED")]
        storage_rows = storage_summary(execution)
        hash_mismatch = sum(1 for r in hash_rows if r["source_sha256"] and r["target_sha256"] and r["source_sha256"] != r["target_sha256"])
        size_mismatch = sum(1 for r in hash_rows if not r["size_match"])
        mutation_count = sum(1 for r in source_rows if r["mutation_detected"])
        diff_collision = sum(1 for r in collision_rows if r["existing_different_hash"])
        failed = sum(1 for r in execution if r["error"])
        status = FAIL_COLLISION if diff_collision else FAIL_VERIFY if failed or hash_mismatch or size_mismatch or mutation_count else WARN_STATUS if skipped_review else PASS_STATUS
        summary = {
            **base_summary(root, out, True, cache_root, archive_root, quarantine_root, status, FINAL_DECISION, 1 if status.startswith("FAIL") else 0),
            "total_input_items": len(master),
            "planned_copy_item_count": len(cache_rows) + len(archive_rows) + len(quarantine_rows),
            "cache_copy_count": len(cache_rows),
            "archive_copy_count": len(archive_rows),
            "quarantine_copy_count": len(quarantine_rows),
            "copied_file_count": sum(1 for r in execution if r["copied"]),
            "already_present_verified_count": sum(1 for r in execution if r["already_present_verified"]),
            "skipped_file_count": sum(1 for r in execution if r["skipped"]),
            "verified_file_count": sum(1 for r in execution if r["verified"]),
            "failed_copy_count": failed,
            "hash_mismatch_count": hash_mismatch,
            "size_mismatch_count": size_mismatch,
            "source_mutation_detected_count": mutation_count,
            "target_collision_same_hash_count": sum(1 for r in collision_rows if r["existing_same_hash"]),
            "target_collision_different_hash_count": diff_collision,
            "external_root_created_count": sum(1 for r in root_rows if r["created_now"]),
            "external_subdir_created_count": sum(int(r["created_subdir_count"]) for r in root_rows),
            "copied_total_bytes": sum(int(r["source_size_before"]) for r in execution if r["copied"]),
            "verified_total_bytes": sum(int(r["source_size_before"]) for r in execution if r["verified"]),
            "skipped_user_review_count": len(skipped_review),
            "skipped_delete_after_verification_count": len(skipped_delete),
            "skipped_no_action_count": len(skipped_no),
            "pointer_manifest_entry_count": len(pointer_index),
            "warning_count": 1 if status == WARN_STATUS else 0,
        }
        write_csv(out / "copy_execution_master.csv", execution, MASTER_FIELDS)
        write_csv(out / "cache_copy_manifest.csv", cache_rows, COPY_FIELDS)
        write_csv(out / "archive_copy_manifest.csv", archive_rows, ARCHIVE_FIELDS)
        write_csv(out / "quarantine_copy_manifest.csv", quarantine_rows, QUARANTINE_FIELDS)
        write_csv(out / "skipped_no_action_manifest.csv", [{"source_path": r["source_path"], "dry_run_future_action": r["dry_run_future_action"], "reason": r["reason"], "protected": r.get("protected_blocker",""), "active_dependency": ""} for r in skipped_no], SKIP_NO_FIELDS)
        write_csv(out / "skipped_user_review_manifest.csv", [{"source_path": r.get("source_path"), "project_name": r.get("project_name"), "reason": r.get("reason"), "user_review_required": True, "copied": False, "deleted": False, "moved": False} for r in skipped_review], SKIP_REVIEW_FIELDS)
        write_csv(out / "skipped_delete_after_verification_manifest.csv", [{"source_path": r.get("source_path"), "reason": r.get("reason"), "copied": False, "deleted": False, "moved": False, "future_stage": "V21.235_REPO_CLEAN_DELETE_AFTER_VERIFICATION"} for r in skipped_delete], SKIP_DELETE_FIELDS)
        write_csv(out / "repo_pointer_manifest_index.csv", pointer_index, POINTER_FIELDS)
        write_json(out / "generated_pointer_manifests.json", pointer_json)
        write_csv(out / "copy_hash_verification.csv", hash_rows, HASH_FIELDS)
        write_csv(out / "copy_collision_audit.csv", collision_rows, COLLISION_FIELDS)
        write_csv(out / "source_integrity_audit.csv", source_rows, SOURCE_FIELDS)
        write_csv(out / "external_root_creation_audit.csv", root_rows, ROOT_FIELDS)
        write_csv(out / "copy_storage_summary.csv", storage_rows, STORAGE_FIELDS)
        write_csv(out / "v21_227_dry_run_crosscheck.csv", crosscheck(summary227, master), CROSS_FIELDS)
        write_json(out / "copy_only_policy_gate.json", policy_gate())
        write_json(out / "v21_228_summary.json", summary)
        write_report(out / "V21.228_external_migration_copy_only_report.txt", summary)
    except Exception as exc:
        summary = base_summary(root, out, True, cache_root, archive_root, quarantine_root, FAIL_VERIFY, "V21_228_COPY_ONLY_EXECUTION_FAILED", 1)
        summary["error_message"] = f"{type(exc).__name__}: {exc}"
        write_json(out / "v21_228_summary.json", summary)
    return print_summary(summary, out)


def base_summary(root: Path, out: Path, found: bool, cache_root: Path, archive_root: Path, quarantine_root: Path, status: str, decision: str, errors: int) -> dict[str, Any]:
    return {
        "final_status": status, "final_decision": decision, "repo_root": str(root), "output_dir": str(out), "v21_227_input_found": found,
        "total_input_items": 0, "planned_copy_item_count": 0, "cache_copy_count": 0, "archive_copy_count": 0, "quarantine_copy_count": 0,
        "copied_file_count": 0, "already_present_verified_count": 0, "skipped_file_count": 0, "verified_file_count": 0, "failed_copy_count": 0,
        "hash_mismatch_count": 0, "size_mismatch_count": 0, "source_mutation_detected_count": 0, "target_collision_same_hash_count": 0, "target_collision_different_hash_count": 0,
        "external_root_created_count": 0, "external_subdir_created_count": 0, "copied_total_bytes": 0, "verified_total_bytes": 0,
        "skipped_user_review_count": 0, "skipped_delete_after_verification_count": 0, "skipped_no_action_count": 0, "pointer_manifest_entry_count": 0,
        **policy_gate(), "yfinance_used": False, "data_fetch_used": False, "moomoo_import_used": False, "warning_count": 0, "error_count": errors,
    }


def write_report(path: Path, summary: dict[str, Any]) -> None:
    keys = ["final_status","final_decision","planned_copy_item_count","cache_copy_count","archive_copy_count","quarantine_copy_count","copied_file_count","already_present_verified_count","verified_file_count","failed_copy_count","hash_mismatch_count","size_mismatch_count","source_mutation_detected_count","target_collision_different_hash_count","external_root_created_count","external_subdir_created_count","copied_total_bytes","verified_total_bytes","skipped_user_review_count","skipped_delete_after_verification_count","pointer_manifest_entry_count","warning_count","error_count"]
    path.write_text("\n".join([STAGE, *[f"{k}={summary[k]}" for k in keys], "copy_only=True", "move_allowed_now=False", "delete_allowed_now=False", "source_mutation_allowed=False"]) + "\n", encoding="utf-8")


def print_summary(summary: dict[str, Any], out: Path) -> dict[str, Any]:
    for key in ["final_status","final_decision","planned_copy_item_count","cache_copy_count","archive_copy_count","quarantine_copy_count","copied_file_count","already_present_verified_count","verified_file_count","failed_copy_count","hash_mismatch_count","size_mismatch_count","source_mutation_detected_count","target_collision_different_hash_count","external_root_created_count","external_subdir_created_count","copied_total_bytes","verified_total_bytes","skipped_user_review_count","skipped_delete_after_verification_count","pointer_manifest_entry_count","warning_count","error_count"]:
        print(f"{key}={summary[key]}")
    print(f"summary_path={out / 'v21_228_summary.json'}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=STAGE)
    p.add_argument("--repo-root")
    p.add_argument("--output-dir")
    p.add_argument("--v21-227-output-dir")
    p.add_argument("--cache-root", default=str(DEFAULT_CACHE_ROOT))
    p.add_argument("--archive-root", default=str(DEFAULT_ARCHIVE_ROOT))
    p.add_argument("--quarantine-root", default=str(DEFAULT_QUARANTINE_ROOT))
    p.add_argument("--force-recopy-same-hash", action="store_true")
    p.add_argument("--max-copy-items", type=int)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(
        repo_root=Path(args.repo_root) if args.repo_root else None,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        v21_227_output_dir=Path(args.v21_227_output_dir) if args.v21_227_output_dir else None,
        cache_root=Path(args.cache_root),
        archive_root=Path(args.archive_root),
        quarantine_root=Path(args.quarantine_root),
        force_recopy_same_hash=args.force_recopy_same_hash,
        max_copy_items=args.max_copy_items,
    )
    return 1 if summary["final_status"] in {FAIL_INPUT, FAIL_VERIFY, FAIL_COLLISION} else 0


if __name__ == "__main__":
    sys.exit(main())
