#!/usr/bin/env python
"""V21.053-R2 shared dependency migration commit.

Commits the safe portion of the V21.053-R1 plan by copying approved shared
dependency files and rewriting only active source/config references that are
explicitly listed in the rewrite plan. It never deletes, moves, or archives.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.053-R2_SHARED_DEPENDENCY_MIGRATION_COMMIT"

PASS_STATUS = "PASS_V21_053_R2_SHARED_DEPENDENCY_MIGRATION_COMMITTED"
PARTIAL_STATUS = "PARTIAL_PASS_V21_053_R2_MIGRATION_COMMITTED_RECHECK_RECOMMENDED"
BLOCKED_INPUT = "BLOCKED_V21_053_R2_SOURCE_INPUT_MISSING_OR_INVALID"
BLOCKED_DUPLICATE = "BLOCKED_V21_053_R2_DUPLICATE_TARGET_CONFLICT"
BLOCKED_COPY = "BLOCKED_V21_053_R2_COPY_FAILURE"
BLOCKED_REWRITE = "BLOCKED_V21_053_R2_REFERENCE_REWRITE_FAILURE"
BLOCKED_STALE = "BLOCKED_V21_053_R2_STALE_DOWNSTREAM_DEPENDENCY_REINTRODUCED"
BLOCKED_TRUE_V20 = "BLOCKED_V21_053_R2_TRUE_V20_DEPENDENCY_REINTRODUCED"
BLOCKED_V20 = "BLOCKED_V21_053_R2_V20_OUTPUT_MUTATION_DETECTED"
BLOCKED_V21 = "BLOCKED_V21_053_R2_V21_CURRENT_OUTPUT_MUTATION_DETECTED"
BLOCKED_PROTECTED = "BLOCKED_V21_053_R2_PROTECTED_OUTPUT_MUTATION_DETECTED"
BLOCKED_PERMISSION = "BLOCKED_V21_053_R2_OFFICIAL_PERMISSION_VIOLATION"

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "source_v21_053_r1_status",
    "source_ready_for_shared_dependency_migration_commit", "migration_plan_row_count",
    "unique_source_path_count", "unique_target_path_count", "duplicate_target_path_count",
    "duplicate_target_path_conflict_count", "copy_attempt_count", "copy_success_count",
    "copy_failure_count", "reference_rewrite_attempt_count", "reference_rewrite_success_count",
    "reference_rewrite_failure_count", "source_modification_count", "copied_file_count",
    "files_deleted_or_moved", "files_archived", "planned_delete_count", "actual_delete_count",
    "migration_commit_allowed", "deletion_allowed", "archive_allowed",
    "rollback_manifest_created", "target_hash_manifest_created", "v20_outputs_mutated",
    "v21_current_outputs_mutated", "protected_outputs_mutated", "protected_output_mutation_count",
    "active_stale_downstream_dependency_reintroduced", "true_v20_script_dependency_reintroduced",
    "true_v20_output_dependency_reintroduced", "post_migration_v21_reads_v20_scripts",
    "post_migration_v21_reads_v20_outputs_as_current_source", "post_migration_shared_dependency_ok",
    "official_activation_allowed", "official_recommendation_allowed",
    "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
    "broker_execution_allowed", "trade_action_allowed", "research_only",
    "recommended_next_stage", "created_at_utc",
]

COPY_FIELDS = [
    "source_path", "target_path", "attempted", "success", "status",
    "source_hash", "preexisting_target", "preexisting_target_hash", "target_hash", "error",
]
REWRITE_FIELDS = [
    "referencing_file", "old_reference", "new_reference", "attempted", "success",
    "status", "original_hash", "new_hash", "error",
]
AUDIT_FIELDS = ["audit_item", "status", "detail"]
ROLLBACK_FIELDS = [
    "copied_file_path", "original_source_path", "preexisting_target",
    "preexisting_target_hash", "new_target_hash", "referencing_file",
    "old_reference", "new_reference", "original_referencing_file_hash",
    "new_referencing_file_hash", "rollback_action",
]
HASH_FIELDS = ["target_path", "source_path", "source_hash", "target_hash", "hash_match"]

PROTECTED_RE = re.compile(
    r"(authoritative.*official.*rank|official.*weight|official.*recommend|"
    r"broker|trade[_ .-]*action|real[_ .-]*book)", re.I
)
TEXT_SUFFIXES = {".py", ".ps1", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini"}


def clean(value: object) -> str:
    return str(value or "").strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def read_first(path: Path) -> dict[str, str]:
    rows, _ = read_csv(path)
    return rows[0] if rows else {}


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def snapshot(root: Path, base: Path, matcher: Callable[[Path], bool]) -> dict[str, str]:
    if not base.exists():
        return {}
    return {rel(root, p): file_hash(p) for p in base.rglob("*") if p.is_file() and matcher(p)}


def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    keys = set(before) | set(after)
    return sorted(key for key in keys if before.get(key) != after.get(key))


def protected_matcher(path: Path) -> bool:
    return "V21_053_R2" not in path.name and bool(PROTECTED_RE.search(path.name))


def v20_output_matcher(path: Path) -> bool:
    return "staging" not in {part.lower() for part in path.parts}


def v21_current_matcher(path: Path) -> bool:
    return "V21_053_R2" not in path.name and any(
        token in path.name for token in ("V21_048", "V21_049", "V21_050", "V21_051", "V21_052", "V21_053_R1")
    )


def source_matcher(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES and "V21_053_R2" not in path.name


def corrected_stale_stage_reference(text: str) -> bool:
    normalized = text.replace("\\", "/")
    return bool(re.search(r"(?i)(?:^|[^0-9A-Za-z])(?:V20[._](?:8|9|10|11|12|13|14|15|16)|v20_(?:8|9|10|11|12|13|14|15|16))(?!\d)", normalized))


def active_rewrite_file(path: str) -> bool:
    p = Path(path.replace("\\", "/"))
    normalized = p.as_posix()
    if not (normalized.startswith("scripts/v21/") or normalized.startswith("configs/") or normalized.startswith("scripts/shared/")):
        return False
    if p.name.lower().startswith("test_"):
        return False
    return p.suffix.lower() in TEXT_SUFFIXES


def active_current_source_file(path: Path, root: Path) -> bool:
    rel_path = rel(root, path)
    name = path.name.lower()
    if path.suffix.lower() not in TEXT_SUFFIXES or name.startswith("test_"):
        return False
    if name.startswith("v21_047"):
        return False
    if name.startswith(("v21_050", "v21_051", "v21_052", "v21_053")):
        return False
    inactive_tokens = ("audit", "plan", "dry_run", "discovery", "ablation", "historical", "forensic", "review")
    if any(token in name for token in inactive_tokens):
        return False
    return rel_path.startswith("scripts/v21/") or rel_path.startswith("configs/")


def validate_r1(summary: dict[str, str]) -> bool:
    return (
        clean(summary.get("final_status")) == "PASS_V21_053_R1_SHARED_DEPENDENCY_MIGRATION_DRY_RUN_READY"
        and clean(summary.get("ready_for_shared_dependency_migration_commit")).upper() == "TRUE"
        and clean(summary.get("protected_path_conflict_count")) in {"", "0"}
        and clean(summary.get("unsafe_migration_candidate_count")) in {"", "0"}
        and clean(summary.get("active_stale_downstream_dependency_reintroduced")).upper() == "FALSE"
        and clean(summary.get("true_v20_script_dependency_reintroduced")).upper() == "FALSE"
        and clean(summary.get("true_v20_output_dependency_reintroduced")).upper() == "FALSE"
    )


def duplicate_conflicts(root: Path, plan_rows: list[dict[str, str]]) -> tuple[int, int, dict[str, list[dict[str, str]]]]:
    groups: dict[str, list[dict[str, str]]] = {}
    for row in plan_rows:
        target = clean(row.get("proposed_target_path"))
        if target:
            groups.setdefault(target, []).append(row)
    duplicate_groups = {target: rows for target, rows in groups.items() if len(rows) > 1}
    conflicts = 0
    for rows in duplicate_groups.values():
        hashes = set()
        for row in rows:
            source = root / clean(row.get("source_path"))
            hashes.add(file_hash(source) if source.exists() else "MISSING")
        if len(hashes) > 1:
            conflicts += 1
    return len(duplicate_groups), conflicts, duplicate_groups


def copy_files(root: Path, plan_rows: list[dict[str, str]]) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    logs: list[dict[str, object]] = []
    rollback: list[dict[str, object]] = []
    hashes: list[dict[str, object]] = []
    attempted_targets: set[str] = set()
    for row in plan_rows:
        if clean(row.get("copy_required")).upper() != "TRUE":
            continue
        source_rel = clean(row.get("source_path"))
        target_rel = clean(row.get("proposed_target_path"))
        if not source_rel or not target_rel or target_rel in attempted_targets:
            continue
        attempted_targets.add(target_rel)
        source = root / source_rel
        target = root / target_rel
        preexisting = target.exists()
        pre_hash = file_hash(target) if preexisting else ""
        err = ""
        success = False
        status = "NOT_ATTEMPTED"
        source_hash = file_hash(source) if source.exists() else ""
        target_hash = ""
        try:
            if not source.exists():
                status = "SOURCE_MISSING"
                err = "Source file missing."
            elif preexisting and pre_hash == source_hash:
                status = "TARGET_ALREADY_MATCHES"
                success = True
            elif preexisting and pre_hash != source_hash:
                status = "TARGET_OVERWRITTEN_BY_PLAN"
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                success = True
            else:
                status = "COPIED"
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                success = True
            if target.exists():
                target_hash = file_hash(target)
        except Exception as exc:  # pragma: no cover - defensive log path
            status = "COPY_FAILED"
            err = str(exc)
        logs.append({
            "source_path": source_rel,
            "target_path": target_rel,
            "attempted": "TRUE",
            "success": tf(success),
            "status": status,
            "source_hash": source_hash,
            "preexisting_target": tf(preexisting),
            "preexisting_target_hash": pre_hash,
            "target_hash": target_hash,
            "error": err,
        })
        rollback.append({
            "copied_file_path": target_rel,
            "original_source_path": source_rel,
            "preexisting_target": tf(preexisting),
            "preexisting_target_hash": pre_hash,
            "new_target_hash": target_hash,
            "referencing_file": "",
            "old_reference": "",
            "new_reference": "",
            "original_referencing_file_hash": "",
            "new_referencing_file_hash": "",
            "rollback_action": "RESTORE_PREEXISTING_TARGET" if preexisting else "DELETE_COPIED_TARGET",
        })
        hashes.append({
            "target_path": target_rel,
            "source_path": source_rel,
            "source_hash": source_hash,
            "target_hash": target_hash,
            "hash_match": tf(bool(source_hash) and source_hash == target_hash),
        })
    return logs, rollback, hashes


def rewrite_refs(root: Path, rewrite_rows: list[dict[str, str]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    logs: list[dict[str, object]] = []
    rollback: list[dict[str, object]] = []
    for row in rewrite_rows:
        if clean(row.get("rewrite_required")).upper() != "TRUE" or clean(row.get("rewrite_safe")).upper() != "TRUE":
            continue
        ref_file = clean(row.get("referencing_file")).replace("\\", "/")
        if not active_rewrite_file(ref_file):
            continue
        path = root / ref_file
        old = clean(row.get("old_reference"))
        new = clean(row.get("new_reference"))
        original_hash = file_hash(path) if path.exists() else ""
        success = False
        status = "NOT_ATTEMPTED"
        err = ""
        new_hash = original_hash
        try:
            if not path.exists():
                status = "REFERENCING_FILE_MISSING"
                err = "Referencing file missing."
            else:
                text = path.read_text(encoding="utf-8")
                if old not in text:
                    status = "OLD_REFERENCE_NOT_FOUND"
                else:
                    path.write_text(text.replace(old, new), encoding="utf-8")
                    new_hash = file_hash(path)
                    status = "REWRITTEN"
                    success = True
        except Exception as exc:  # pragma: no cover - defensive log path
            status = "REWRITE_FAILED"
            err = str(exc)
        logs.append({
            "referencing_file": ref_file,
            "old_reference": old,
            "new_reference": new,
            "attempted": "TRUE",
            "success": tf(success),
            "status": status,
            "original_hash": original_hash,
            "new_hash": new_hash,
            "error": err,
        })
        rollback.append({
            "copied_file_path": "",
            "original_source_path": "",
            "preexisting_target": "",
            "preexisting_target_hash": "",
            "new_target_hash": "",
            "referencing_file": ref_file,
            "old_reference": old,
            "new_reference": new,
            "original_referencing_file_hash": original_hash,
            "new_referencing_file_hash": new_hash,
            "rollback_action": "RESTORE_ORIGINAL_REFERENCE_TEXT",
        })
    return logs, rollback


def post_audit(root: Path) -> tuple[list[dict[str, object]], bool, bool, bool]:
    rows: list[dict[str, object]] = []
    reads_v20_scripts = False
    reads_v20_outputs = False
    stale = False
    for base in (root / "scripts/v21", root / "configs"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or not active_current_source_file(path, root):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            rel_path = rel(root, path)
            if "scripts/v20/" in text or "scripts\\v20\\" in text:
                reads_v20_scripts = True
                rows.append({"audit_item": rel_path, "status": "TRUE_V20_SCRIPT_REFERENCE", "detail": "Active source references scripts/v20."})
            if "outputs/v20/" in text or "outputs\\v20\\" in text:
                reads_v20_outputs = True
                rows.append({"audit_item": rel_path, "status": "TRUE_V20_OUTPUT_REFERENCE", "detail": "Active source references outputs/v20."})
                if corrected_stale_stage_reference(text):
                    stale = True
                    rows.append({"audit_item": rel_path, "status": "ACTIVE_STALE_DOWNSTREAM_REFERENCE", "detail": "Active source references V20.8-V20.16 token."})
    if not rows:
        rows.append({"audit_item": "post_migration_dependency_scan", "status": "PASS", "detail": "No active V20 script/output source dependency detected."})
    return rows, stale, reads_v20_scripts, reads_v20_outputs


def render_report(summary: dict[str, object]) -> str:
    return f"""# V21.053-R2 Shared Dependency Migration Commit

- final_status: {summary['final_status']}
- decision: {summary['decision']}
- copy_success_count: {summary['copy_success_count']}
- reference_rewrite_success_count: {summary['reference_rewrite_success_count']}
- active_stale_downstream_dependency_reintroduced: {summary['active_stale_downstream_dependency_reintroduced']}
- true_v20_script_dependency_reintroduced: {summary['true_v20_script_dependency_reintroduced']}
- true_v20_output_dependency_reintroduced: {summary['true_v20_output_dependency_reintroduced']}
- recommended_next_stage: {summary['recommended_next_stage']}

This stage copied approved shared dependency artifacts and produced rollback and
hash manifests. It did not delete, move, or archive any files.
"""


def run_commit(root: Path, protected_mutation_hook: Callable[[], None] | None = None) -> tuple[dict[str, object], list[dict[str, object]]]:
    root = root.resolve()
    out_dir = root / "outputs/v21/migration"
    r1 = read_first(out_dir / "V21_053_R1_SHARED_DEPENDENCY_MIGRATION_DRY_RUN_SUMMARY.csv")
    plan_rows, _ = read_csv(out_dir / "V21_053_R1_SHARED_DEPENDENCY_MIGRATION_PLAN.csv")
    rewrite_rows, _ = read_csv(out_dir / "V21_053_R1_REFERENCE_REWRITE_PLAN.csv")
    inputs_valid = validate_r1(r1) and bool(plan_rows)
    before_files = {rel(root, p) for p in root.rglob("*") if p.is_file()}
    before_v20 = snapshot(root, root / "outputs/v20", v20_output_matcher)
    before_v21 = snapshot(root, root / "outputs/v21", v21_current_matcher)
    before_protected = snapshot(root, root / "outputs", protected_matcher)

    duplicate_count, duplicate_conflict_count, _ = duplicate_conflicts(root, plan_rows)
    copy_logs: list[dict[str, object]] = []
    rewrite_logs: list[dict[str, object]] = []
    rollback_rows: list[dict[str, object]] = []
    hash_rows: list[dict[str, object]] = []
    if inputs_valid and duplicate_conflict_count == 0:
        copy_logs, copy_rollbacks, hash_rows = copy_files(root, plan_rows)
        rewrite_logs, rewrite_rollbacks = rewrite_refs(root, rewrite_rows)
        rollback_rows = copy_rollbacks + rewrite_rollbacks
    if protected_mutation_hook:
        protected_mutation_hook()

    audit_rows, stale_reintroduced, reads_v20_scripts, reads_v20_outputs = post_audit(root)
    after_files = {rel(root, p) for p in root.rglob("*") if p.is_file()}
    deleted_or_moved = bool(before_files - after_files)
    v20_changes = changed(before_v20, snapshot(root, root / "outputs/v20", v20_output_matcher))
    v21_changes = changed(before_v21, snapshot(root, root / "outputs/v21", v21_current_matcher))
    protected_changes = changed(before_protected, snapshot(root, root / "outputs", protected_matcher))

    copy_attempts = len(copy_logs)
    copy_success = len([row for row in copy_logs if row["success"] == "TRUE"])
    copy_failures = copy_attempts - copy_success
    rewrite_attempts = len(rewrite_logs)
    rewrite_success = len([row for row in rewrite_logs if row["success"] == "TRUE"])
    rewrite_failures = len([row for row in rewrite_logs if row["status"] in {"REFERENCING_FILE_MISSING", "REWRITE_FAILED"}])
    source_modifications = len({row["referencing_file"] for row in rewrite_logs if row["success"] == "TRUE"})
    copied_count = len({row["target_path"] for row in copy_logs if row["success"] == "TRUE"})
    true_v20_reintroduced = reads_v20_scripts or reads_v20_outputs

    if not inputs_valid:
        final_status = BLOCKED_INPUT
        decision = "BLOCK_SOURCE_INPUT_MISSING_OR_INVALID"
        recommended = "V21.053-R2_INPUT_REPAIR"
    elif duplicate_conflict_count:
        final_status = BLOCKED_DUPLICATE
        decision = "BLOCK_DUPLICATE_TARGET_CONFLICT"
        recommended = "V21.053-R1A_MIGRATION_PLAN_MANUAL_REVIEW"
    elif copy_failures:
        final_status = BLOCKED_COPY
        decision = "BLOCK_COPY_FAILURE"
        recommended = "V21.053-R2_COPY_REPAIR"
    elif rewrite_failures:
        final_status = BLOCKED_REWRITE
        decision = "BLOCK_REFERENCE_REWRITE_FAILURE"
        recommended = "V21.053-R2_REWRITE_REPAIR"
    elif stale_reintroduced:
        final_status = BLOCKED_STALE
        decision = "BLOCK_STALE_DOWNSTREAM_DEPENDENCY_REINTRODUCED"
        recommended = "V21.053-R3_POST_MIGRATION_DEPENDENCY_REPAIR"
    elif true_v20_reintroduced:
        final_status = BLOCKED_TRUE_V20
        decision = "BLOCK_TRUE_V20_DEPENDENCY_REINTRODUCED"
        recommended = "V21.053-R3_POST_MIGRATION_DEPENDENCY_REPAIR"
    else:
        final_status = PASS_STATUS
        decision = "SHARED_DEPENDENCY_MIGRATION_COMMITTED"
        recommended = "V21.054-R1_POST_MIGRATION_SOURCE_ISOLATION_RECHECK"
    if protected_changes:
        final_status = BLOCKED_PROTECTED
        decision = "BLOCK_PROTECTED_OUTPUT_MUTATION_DETECTED"
    elif v20_changes:
        final_status = BLOCKED_V20
        decision = "BLOCK_V20_OUTPUT_MUTATION_DETECTED"
    elif v21_changes:
        final_status = BLOCKED_V21
        decision = "BLOCK_V21_CURRENT_OUTPUT_MUTATION_DETECTED"

    perms = {
        "official_activation_allowed": "FALSE",
        "official_recommendation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
    }
    if any(value != "FALSE" for value in perms.values()):
        final_status = BLOCKED_PERMISSION
        decision = "BLOCK_OFFICIAL_PERMISSION_VIOLATION"

    summary: dict[str, object] = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "source_v21_053_r1_status": clean(r1.get("final_status")) or "NOT_AVAILABLE",
        "source_ready_for_shared_dependency_migration_commit": clean(r1.get("ready_for_shared_dependency_migration_commit")) or "FALSE",
        "migration_plan_row_count": len(plan_rows),
        "unique_source_path_count": len({clean(row.get("source_path")) for row in plan_rows}),
        "unique_target_path_count": len({clean(row.get("proposed_target_path")) for row in plan_rows if clean(row.get("proposed_target_path"))}),
        "duplicate_target_path_count": duplicate_count,
        "duplicate_target_path_conflict_count": duplicate_conflict_count,
        "copy_attempt_count": copy_attempts,
        "copy_success_count": copy_success,
        "copy_failure_count": copy_failures,
        "reference_rewrite_attempt_count": rewrite_attempts,
        "reference_rewrite_success_count": rewrite_success,
        "reference_rewrite_failure_count": rewrite_failures,
        "source_modification_count": source_modifications,
        "copied_file_count": copied_count,
        "files_deleted_or_moved": tf(deleted_or_moved),
        "files_archived": "FALSE",
        "planned_delete_count": clean(r1.get("planned_delete_count")) or "0",
        "actual_delete_count": 0,
        "migration_commit_allowed": "TRUE",
        "deletion_allowed": "FALSE",
        "archive_allowed": "FALSE",
        "rollback_manifest_created": tf(bool(rollback_rows)),
        "target_hash_manifest_created": tf(bool(hash_rows)),
        "v20_outputs_mutated": tf(bool(v20_changes)),
        "v21_current_outputs_mutated": tf(bool(v21_changes)),
        "protected_outputs_mutated": tf(bool(protected_changes)),
        "protected_output_mutation_count": len(protected_changes),
        "active_stale_downstream_dependency_reintroduced": tf(stale_reintroduced),
        "true_v20_script_dependency_reintroduced": tf(reads_v20_scripts),
        "true_v20_output_dependency_reintroduced": tf(reads_v20_outputs),
        "post_migration_v21_reads_v20_scripts": tf(reads_v20_scripts),
        "post_migration_v21_reads_v20_outputs_as_current_source": tf(reads_v20_outputs),
        "post_migration_shared_dependency_ok": tf(not stale_reintroduced and not true_v20_reintroduced and copy_failures == 0 and duplicate_conflict_count == 0),
        **perms,
        "research_only": "TRUE",
        "recommended_next_stage": recommended,
        "created_at_utc": utc_now(),
    }

    write_csv(out_dir / "V21_053_R2_SHARED_DEPENDENCY_MIGRATION_COMMIT_SUMMARY.csv", [summary], SUMMARY_FIELDS)
    write_csv(out_dir / "V21_053_R2_COPY_COMMIT_LOG.csv", copy_logs, COPY_FIELDS)
    write_csv(out_dir / "V21_053_R2_REFERENCE_REWRITE_COMMIT_LOG.csv", rewrite_logs, REWRITE_FIELDS)
    write_csv(out_dir / "V21_053_R2_POST_MIGRATION_DEPENDENCY_AUDIT.csv", audit_rows, AUDIT_FIELDS)
    write_csv(out_dir / "V21_053_R2_ROLLBACK_MANIFEST.csv", rollback_rows, ROLLBACK_FIELDS)
    write_csv(out_dir / "V21_053_R2_TARGET_HASH_MANIFEST.csv", hash_rows, HASH_FIELDS)
    report_path = root / "outputs/v21/read_center/V21_053_R2_SHARED_DEPENDENCY_MIGRATION_COMMIT_REPORT.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(summary), encoding="utf-8")
    return summary, copy_logs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    summary, _ = run_commit(args.root)
    for field in SUMMARY_FIELDS:
        print(f"{field.upper()}={summary.get(field, '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
