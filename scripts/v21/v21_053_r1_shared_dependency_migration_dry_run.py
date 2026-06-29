#!/usr/bin/env python
"""V21.053-R1 shared dependency migration dry run.

Builds a migration and reference-rewrite plan only. It does not copy, move,
delete, archive, or rewrite any source files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.053-R1_SHARED_DEPENDENCY_MIGRATION_DRY_RUN"

PASS_STATUS = "PASS_V21_053_R1_SHARED_DEPENDENCY_MIGRATION_DRY_RUN_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_053_R1_MIGRATION_PLAN_READY_WITH_MANUAL_REVIEW"
BLOCKED_INPUT = "BLOCKED_V21_053_R1_SOURCE_INPUT_MISSING_OR_INVALID"
BLOCKED_STALE = "BLOCKED_V21_053_R1_STALE_DOWNSTREAM_DEPENDENCY_REINTRODUCED"
BLOCKED_TRUE_V20 = "BLOCKED_V21_053_R1_TRUE_V20_DEPENDENCY_REINTRODUCED"
BLOCKED_PROTECTED_PATH = "BLOCKED_V21_053_R1_PROTECTED_PATH_CONFLICT"
BLOCKED_UNSAFE = "BLOCKED_V21_053_R1_UNSAFE_MIGRATION_CANDIDATES"
BLOCKED_FILE_MUTATION = "BLOCKED_V21_053_R1_FILE_MUTATION_DETECTED"
BLOCKED_PROTECTED_MUTATION = "BLOCKED_V21_053_R1_PROTECTED_OUTPUT_MUTATION_DETECTED"
BLOCKED_PERMISSION = "BLOCKED_V21_053_R1_OFFICIAL_PERMISSION_VIOLATION"

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "source_v21_052_r3_status",
    "source_dependency_resolution_complete", "source_ready_for_shared_dependency_migration_dry_run",
    "shared_dependency_queue_count", "migration_plan_row_count", "unique_source_path_count",
    "unique_target_path_count", "reference_rewrite_count", "planned_copy_count",
    "planned_move_count", "planned_delete_count", "planned_source_modification_count",
    "migration_dry_run_only", "migration_allowed", "deletion_allowed", "archive_allowed",
    "source_files_mutated", "files_deleted_or_moved", "files_copied", "v20_outputs_mutated",
    "v21_current_outputs_mutated", "protected_outputs_mutated", "protected_output_mutation_count",
    "active_stale_downstream_dependency_reintroduced", "true_v20_script_dependency_reintroduced",
    "true_v20_output_dependency_reintroduced", "protected_path_conflict_count",
    "unsafe_migration_candidate_count", "ready_for_shared_dependency_migration_commit",
    "official_activation_allowed", "official_recommendation_allowed",
    "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
    "broker_execution_allowed", "trade_action_allowed", "research_only",
    "recommended_next_stage", "created_at_utc",
]

PLAN_FIELDS = [
    "source_path", "source_type", "dependency_class", "current_reference_locations",
    "proposed_target_path", "proposed_action", "proposed_reference_after_migration",
    "migration_required", "copy_required", "source_rewrite_required", "delete_required",
    "protected_path", "risk_level", "reason",
]

REWRITE_FIELDS = [
    "referencing_file", "old_reference", "new_reference", "rewrite_required",
    "rewrite_safe", "reason",
]

RISK_FIELDS = ["candidate", "risk_type", "risk_level", "blocker", "mitigation"]
PROTECTED_FIELDS = ["path", "protected_reason", "conflict", "action"]

PROTECTED_RE = re.compile(
    r"(authoritative.*official.*rank|official.*weight|official.*recommend|"
    r"broker|trade[_ .-]*action|real[_ .-]*book)", re.I
)
RAW_RE = re.compile(r"(data[\\/]+raw|price|universe|ohlcv|yahoo|cache)", re.I)
SCHEMA_RE = re.compile(r"(schema|contract|field|column|definition)", re.I)
HELPER_RE = re.compile(r"(helper|guardrail|hash|date|common|util|library)", re.I)
MANIFEST_RE = re.compile(r"(manifest|register|audit|map|coverage|source|family|factor|dependency)", re.I)


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
    return "V21_053_R1" not in path.name and bool(PROTECTED_RE.search(path.name))


def v20_output_matcher(path: Path) -> bool:
    return "staging" not in {part.lower() for part in path.parts}


def v21_current_matcher(path: Path) -> bool:
    return "V21_053_R1" not in path.name and any(
        token in path.name for token in ("V21_048", "V21_049", "V21_050", "V21_051", "V21_052")
    )


def source_matcher(path: Path) -> bool:
    return "V21_053_R1" not in path.name and path.suffix.lower() in {".py", ".ps1", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini"}


def corrected_stale_stage_reference(text: str) -> bool:
    normalized = text.replace("\\", "/")
    return bool(re.search(r"(?i)(?:^|[^0-9A-Za-z])(?:V20[._](?:8|9|10|11|12|13|14|15|16)|v20_(?:8|9|10|11|12|13|14|15|16))(?!\d)", normalized))


def strip_v20_prefix(name: str) -> str:
    stripped = re.sub(r"(?i)^V20[_ .-]*", "", name)
    return re.sub(r"(?i)V20[._](8|9|10|11|12|13|14|15|16)(?!\d)", r"LEGACY_STAGE_\1", stripped)


def classify_candidate(row: dict[str, str]) -> tuple[str, str, str, str, bool, bool, bool, bool, bool]:
    source = clean(row.get("file_path")).replace("\\", "/")
    name = Path(source).name
    protected = bool(PROTECTED_RE.search(source))
    text = " ".join([source, clean(row.get("reference_type")), clean(row.get("resolution_reason"))])
    convention_path = source.startswith(("outputs/v20/", "scripts/v20/", "data/"))
    if protected:
        return ("PROTECTED_NEVER_MIGRATE", "", "NEVER_MIGRATE_PROTECTED", "Protected official/broker/trade path.", False, False, False, False, True)
    if source.startswith("outputs/v21/"):
        return ("HISTORICAL_REFERENCE_ONLY", "", "KEEP_HISTORICAL_REFERENCE", "V21 migration/report artifact is retained as historical evidence, not migrated.", False, False, False, False, False)
    if not convention_path:
        return ("UNSAFE_MANUAL_REVIEW_REQUIRED", "", "MANUAL_REVIEW_REQUIRED", "Candidate is outside known V20/shared data conventions.", False, False, False, False, False)
    if source.startswith("scripts/v20/"):
        dep_class = "SHARED_GUARDRAIL_OR_HASH_HELPER" if HELPER_RE.search(text) else "SHARED_HELPER_SCRIPT"
        target = f"scripts/shared/{strip_v20_prefix(name)}"
        return (dep_class, target, "PLAN_COPY_TO_SHARED_HELPER", "Shared helper script should move under scripts/shared in a later commit.", True, True, True, False, False)
    if RAW_RE.search(source):
        target = f"data/manifests/{Path(source).stem}_manifest.csv"
        return ("SHARED_PRICE_OR_UNIVERSE_SOURCE", target, "PLAN_CREATE_SHARED_MANIFEST_REFERENCE", "Raw price/universe data remains in data; only a manifest/reference should be created.", True, False, True, False, False)
    if SCHEMA_RE.search(text):
        target = f"scripts/shared/contracts/{strip_v20_prefix(name)}"
        return ("SHARED_SCHEMA_OR_CONTRACT", target, "PLAN_COPY_CONTRACT_TO_SHARED", "Schema/contract dependency should move to shared contracts.", True, True, True, False, False)
    if MANIFEST_RE.search(text) or source.startswith("outputs/v20/"):
        target = f"outputs/shared/manifest/{strip_v20_prefix(name)}"
        return ("SHARED_DATA_MANIFEST", target, "PLAN_COPY_TO_SHARED_MANIFEST", "Shared manifest/register/audit dependency should move to a shared manifest namespace.", True, True, True, False, False)
    if clean(row.get("safe_to_ignore")).upper() == "TRUE":
        return ("HISTORICAL_REFERENCE_ONLY", "", "KEEP_HISTORICAL_REFERENCE", "Historical reference only; no migration required.", False, False, False, False, False)
    return ("UNSAFE_MANUAL_REVIEW_REQUIRED", "", "MANUAL_REVIEW_REQUIRED", "Candidate did not match safe dry-run migration rules.", False, False, False, False, False)


def build_plan(rows: list[dict[str, str]]) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    plan: list[dict[str, object]] = []
    rewrites: list[dict[str, object]] = []
    risks: list[dict[str, object]] = []
    protected_rows: list[dict[str, object]] = []
    for row in rows:
        source = clean(row.get("file_path")).replace("\\", "/")
        dep_class, target, action, reason, migrate, copy_req, rewrite_req, delete_req, protected = classify_candidate(row)
        refs = clean(row.get("referenced_by_v21"))
        risk = "HIGH" if dep_class in {"UNSAFE_MANUAL_REVIEW_REQUIRED", "PROTECTED_NEVER_MIGRATE"} else "LOW" if not corrected_stale_stage_reference(target) else "MEDIUM"
        plan_row = {
            "source_path": source,
            "source_type": clean(row.get("file_type")),
            "dependency_class": dep_class,
            "current_reference_locations": refs,
            "proposed_target_path": target,
            "proposed_action": action,
            "proposed_reference_after_migration": target,
            "migration_required": tf(migrate),
            "copy_required": tf(copy_req),
            "source_rewrite_required": tf(rewrite_req),
            "delete_required": tf(delete_req),
            "protected_path": tf(protected),
            "risk_level": risk,
            "reason": reason,
        }
        plan.append(plan_row)
        if protected:
            protected_rows.append({
                "path": source,
                "protected_reason": reason,
                "conflict": "TRUE",
                "action": "NEVER_MIGRATE",
            })
        if dep_class == "UNSAFE_MANUAL_REVIEW_REQUIRED":
            risks.append({
                "candidate": source,
                "risk_type": "UNSAFE_MIGRATION_CANDIDATE",
                "risk_level": "HIGH",
                "blocker": "TRUE",
                "mitigation": "Manual review before migration commit.",
            })
        if protected:
            risks.append({
                "candidate": source,
                "risk_type": "PROTECTED_PATH_CONFLICT",
                "risk_level": "HIGH",
                "blocker": "TRUE",
                "mitigation": "Never migrate protected path.",
            })
        for ref in [part.strip() for part in refs.split("|") if part.strip()]:
            rewrites.append({
                "referencing_file": ref,
                "old_reference": source,
                "new_reference": target,
                "rewrite_required": tf(rewrite_req),
                "rewrite_safe": tf(rewrite_req and bool(target) and not protected),
                "reason": "Dry-run reference rewrite plan only." if rewrite_req else "No rewrite needed.",
            })
    return plan, rewrites, risks, protected_rows


def render_report(summary: dict[str, object]) -> str:
    return f"""# V21.053-R1 Shared Dependency Migration Dry Run

- final_status: {summary['final_status']}
- decision: {summary['decision']}
- shared_dependency_queue_count: {summary['shared_dependency_queue_count']}
- migration_plan_row_count: {summary['migration_plan_row_count']}
- reference_rewrite_count: {summary['reference_rewrite_count']}
- planned_copy_count: {summary['planned_copy_count']}
- planned_move_count: {summary['planned_move_count']}
- planned_delete_count: {summary['planned_delete_count']}
- ready_for_shared_dependency_migration_commit: {summary['ready_for_shared_dependency_migration_commit']}
- recommended_next_stage: {summary['recommended_next_stage']}

This stage is dry-run only. It did not copy, move, delete, archive, migrate, or
rewrite files.
"""


def run_dry_run(
    root: Path,
    protected_mutation_hook: Callable[[], None] | None = None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    root = root.resolve()
    out_dir = root / "outputs/v21/migration"
    r3_summary = read_first(out_dir / "V21_052_R3_MANUAL_REVIEW_RESOLUTION_SUMMARY.csv")
    queue_rows, _ = read_csv(out_dir / "V21_052_R3_FINAL_SHARED_DEPENDENCY_MIGRATION_QUEUE.csv")
    inputs_valid = (
        bool(r3_summary)
        and clean(r3_summary.get("dependency_resolution_complete")).upper() == "TRUE"
        and clean(r3_summary.get("ready_for_shared_dependency_migration_dry_run")).upper() == "TRUE"
        and clean(r3_summary.get("final_active_stale_downstream_dependency_count")) in {"", "0"}
        and clean(r3_summary.get("final_true_v20_script_dependency_count")) in {"", "0"}
        and clean(r3_summary.get("final_true_v20_output_dependency_count")) in {"", "0"}
        and bool(queue_rows)
    )
    before_files = {rel(root, p) for p in root.rglob("*") if p.is_file()}
    before_sources = snapshot(root, root / "scripts", source_matcher)
    before_v20 = snapshot(root, root / "outputs/v20", v20_output_matcher)
    before_v21 = snapshot(root, root / "outputs/v21", v21_current_matcher)
    before_protected = snapshot(root, root / "outputs", protected_matcher)

    plan_rows, rewrite_rows, risk_rows, protected_rows = build_plan(queue_rows)
    if protected_mutation_hook:
        protected_mutation_hook()

    after_files = {rel(root, p) for p in root.rglob("*") if p.is_file()}
    created_files = after_files - before_files
    deleted_or_moved = bool(before_files - after_files)
    source_changes = changed(before_sources, snapshot(root, root / "scripts", source_matcher))
    v20_changes = changed(before_v20, snapshot(root, root / "outputs/v20", v20_output_matcher))
    v21_changes = changed(before_v21, snapshot(root, root / "outputs/v21", v21_current_matcher))
    protected_changes = changed(before_protected, snapshot(root, root / "outputs", protected_matcher))

    active_stale_reintroduced = any(corrected_stale_stage_reference(clean(row.get("proposed_reference_after_migration"))) for row in plan_rows)
    true_v20_script_reintroduced = any(clean(row.get("proposed_reference_after_migration")).startswith("scripts/v20/") for row in plan_rows)
    true_v20_output_reintroduced = any(clean(row.get("proposed_reference_after_migration")).startswith("outputs/v20/") for row in plan_rows)
    protected_conflicts = [row for row in plan_rows if row["protected_path"] == "TRUE"]
    unsafe_candidates = [row for row in plan_rows if row["dependency_class"] == "UNSAFE_MANUAL_REVIEW_REQUIRED"]

    allowed_new_prefixes = {
        "outputs/v21/migration/V21_053_R1_SHARED_DEPENDENCY_MIGRATION_DRY_RUN_SUMMARY.csv",
        "outputs/v21/migration/V21_053_R1_SHARED_DEPENDENCY_MIGRATION_PLAN.csv",
        "outputs/v21/migration/V21_053_R1_REFERENCE_REWRITE_PLAN.csv",
        "outputs/v21/migration/V21_053_R1_MIGRATION_RISK_AUDIT.csv",
        "outputs/v21/migration/V21_053_R1_PROTECTED_PATH_AUDIT.csv",
        "outputs/v21/read_center/V21_053_R1_SHARED_DEPENDENCY_MIGRATION_DRY_RUN_REPORT.md",
    }
    files_copied = bool(created_files - allowed_new_prefixes)
    ready_commit = inputs_valid and not (
        active_stale_reintroduced or true_v20_script_reintroduced or true_v20_output_reintroduced
        or protected_conflicts or unsafe_candidates
    )

    if not inputs_valid:
        final_status = BLOCKED_INPUT
        decision = "BLOCK_SOURCE_INPUT_MISSING_OR_INVALID"
        recommended = "V21.053-R1_INPUT_REPAIR"
    elif active_stale_reintroduced:
        final_status = BLOCKED_STALE
        decision = "BLOCK_STALE_DOWNSTREAM_DEPENDENCY_REINTRODUCED"
        recommended = "V21.053-R1A_MIGRATION_PLAN_MANUAL_REVIEW"
    elif true_v20_script_reintroduced or true_v20_output_reintroduced:
        final_status = BLOCKED_TRUE_V20
        decision = "BLOCK_TRUE_V20_DEPENDENCY_REINTRODUCED"
        recommended = "V21.053-R1A_MIGRATION_PLAN_MANUAL_REVIEW"
    elif protected_conflicts:
        final_status = BLOCKED_PROTECTED_PATH
        decision = "BLOCK_PROTECTED_PATH_CONFLICT"
        recommended = "V21.053-R1A_MIGRATION_PLAN_MANUAL_REVIEW"
    elif unsafe_candidates:
        final_status = BLOCKED_UNSAFE
        decision = "BLOCK_UNSAFE_MIGRATION_CANDIDATES"
        recommended = "V21.053-R1A_MIGRATION_PLAN_MANUAL_REVIEW"
    else:
        final_status = PASS_STATUS if ready_commit else PARTIAL_STATUS
        decision = "SHARED_DEPENDENCY_MIGRATION_DRY_RUN_READY" if ready_commit else "MIGRATION_PLAN_READY_WITH_MANUAL_REVIEW"
        recommended = "V21.053-R2_SHARED_DEPENDENCY_MIGRATION_COMMIT" if ready_commit else "V21.053-R1A_MIGRATION_PLAN_MANUAL_REVIEW"
    if source_changes or deleted_or_moved or files_copied or v20_changes or v21_changes:
        final_status = BLOCKED_FILE_MUTATION
        decision = "BLOCK_FILE_MUTATION_DETECTED"
    if protected_changes:
        final_status = BLOCKED_PROTECTED_MUTATION
        decision = "BLOCK_PROTECTED_OUTPUT_MUTATION_DETECTED"

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
        "source_v21_052_r3_status": clean(r3_summary.get("final_status")) or "NOT_AVAILABLE",
        "source_dependency_resolution_complete": clean(r3_summary.get("dependency_resolution_complete")) or "FALSE",
        "source_ready_for_shared_dependency_migration_dry_run": clean(r3_summary.get("ready_for_shared_dependency_migration_dry_run")) or "FALSE",
        "shared_dependency_queue_count": len(queue_rows),
        "migration_plan_row_count": len(plan_rows),
        "unique_source_path_count": len({row["source_path"] for row in plan_rows}),
        "unique_target_path_count": len({row["proposed_target_path"] for row in plan_rows if row["proposed_target_path"]}),
        "reference_rewrite_count": len([row for row in rewrite_rows if row["rewrite_required"] == "TRUE"]),
        "planned_copy_count": len([row for row in plan_rows if row["copy_required"] == "TRUE"]),
        "planned_move_count": 0,
        "planned_delete_count": 0,
        "planned_source_modification_count": len([row for row in plan_rows if row["source_rewrite_required"] == "TRUE"]),
        "migration_dry_run_only": "TRUE",
        "migration_allowed": "FALSE",
        "deletion_allowed": "FALSE",
        "archive_allowed": "FALSE",
        "source_files_mutated": tf(bool(source_changes)),
        "files_deleted_or_moved": tf(deleted_or_moved),
        "files_copied": tf(files_copied),
        "v20_outputs_mutated": tf(bool(v20_changes)),
        "v21_current_outputs_mutated": tf(bool(v21_changes)),
        "protected_outputs_mutated": tf(bool(protected_changes)),
        "protected_output_mutation_count": len(protected_changes),
        "active_stale_downstream_dependency_reintroduced": tf(active_stale_reintroduced),
        "true_v20_script_dependency_reintroduced": tf(true_v20_script_reintroduced),
        "true_v20_output_dependency_reintroduced": tf(true_v20_output_reintroduced),
        "protected_path_conflict_count": len(protected_conflicts),
        "unsafe_migration_candidate_count": len(unsafe_candidates),
        "ready_for_shared_dependency_migration_commit": tf(ready_commit),
        **perms,
        "research_only": "TRUE",
        "recommended_next_stage": recommended,
        "created_at_utc": utc_now(),
    }

    write_csv(out_dir / "V21_053_R1_SHARED_DEPENDENCY_MIGRATION_DRY_RUN_SUMMARY.csv", [summary], SUMMARY_FIELDS)
    write_csv(out_dir / "V21_053_R1_SHARED_DEPENDENCY_MIGRATION_PLAN.csv", plan_rows, PLAN_FIELDS)
    write_csv(out_dir / "V21_053_R1_REFERENCE_REWRITE_PLAN.csv", rewrite_rows, REWRITE_FIELDS)
    write_csv(out_dir / "V21_053_R1_MIGRATION_RISK_AUDIT.csv", risk_rows, RISK_FIELDS)
    write_csv(out_dir / "V21_053_R1_PROTECTED_PATH_AUDIT.csv", protected_rows, PROTECTED_FIELDS)
    report_path = root / "outputs/v21/read_center/V21_053_R1_SHARED_DEPENDENCY_MIGRATION_DRY_RUN_REPORT.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(summary), encoding="utf-8")
    return summary, plan_rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    summary, _ = run_dry_run(args.root)
    for field in SUMMARY_FIELDS:
        print(f"{field.upper()}={summary.get(field, '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
