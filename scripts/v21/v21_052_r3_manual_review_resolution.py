#!/usr/bin/env python
"""V21.052-R3 manual review resolution.

Classification/resolution only. Carries forward V21.052-R2 classifications,
resolves the remaining unknown rows where deterministic rules allow it, and
emits final queues for shared dependency migration dry-run.
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
STAGE = "V21.052-R3_MANUAL_REVIEW_RESOLUTION"

PASS_STATUS = "PASS_V21_052_R3_MANUAL_REVIEW_RESOLVED_READY_FOR_SHARED_MIGRATION_DRY_RUN"
PARTIAL_STATUS = "PARTIAL_PASS_V21_052_R3_MANUAL_REVIEW_REDUCED_REVIEW_REMAINING"
BLOCKED_STALE = "BLOCKED_V21_052_R3_ACTIVE_STALE_DOWNSTREAM_DEPENDENCY_FOUND"
BLOCKED_TRUE_ACTIVE = "BLOCKED_V21_052_R3_TRUE_V20_ACTIVE_DEPENDENCY_FOUND"
BLOCKED_INPUT = "BLOCKED_V21_052_R3_INPUT_MISSING_OR_INVALID"
BLOCKED_V20 = "BLOCKED_V21_052_R3_V20_OUTPUT_MUTATION_DETECTED"
BLOCKED_V21 = "BLOCKED_V21_052_R3_V21_CURRENT_OUTPUT_MUTATION_DETECTED"
BLOCKED_PROTECTED = "BLOCKED_V21_052_R3_PROTECTED_OUTPUT_MUTATION_DETECTED"
BLOCKED_PERMISSION = "BLOCKED_V21_052_R3_OFFICIAL_PERMISSION_VIOLATION"

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "source_v21_052_r2_status",
    "unresolved_manual_review_count_before", "unresolved_manual_review_count_after",
    "total_references_reviewed", "newly_classified_as_harmless_historical_count",
    "newly_classified_as_shared_dependency_count", "newly_classified_as_migration_required_count",
    "newly_classified_as_archive_only_count", "newly_classified_as_safe_to_ignore_count",
    "newly_classified_as_blocking_dependency_count", "final_harmless_historical_reference_count",
    "final_shared_dependency_count", "final_references_requiring_migration_count",
    "final_references_requiring_archive_only_count", "final_references_safe_to_ignore_count",
    "final_active_stale_downstream_dependency_count", "final_true_v20_script_dependency_count",
    "final_true_v20_output_dependency_count", "dependency_resolution_complete",
    "ready_for_shared_dependency_migration_dry_run", "files_deleted_or_moved",
    "v20_outputs_mutated", "v21_current_outputs_mutated", "protected_outputs_mutated",
    "protected_output_mutation_count", "deletion_allowed", "migration_allowed",
    "archive_allowed", "official_activation_allowed", "official_recommendation_allowed",
    "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
    "broker_execution_allowed", "trade_action_allowed", "research_only",
    "recommended_next_stage", "created_at_utc",
]

RESOLVED_FIELDS = [
    "file_path", "file_type", "size_mb", "last_modified", "referenced_by_v21",
    "reference_type", "active_current_dependency", "historical_report_reference",
    "manual_review_reference", "shared_dependency", "dependency_risk",
    "stale_lineage_risk", "r2_primary_classification", "r2_proposed_action",
    "r2_classification_reason", "final_classification", "final_proposed_action",
    "requires_migration", "archive_only", "safe_to_ignore",
    "requires_manual_review_after_r3", "active_stale_downstream_dependency",
    "newly_classified_by_r3", "resolution_reason",
]

PROTECTED_RE = re.compile(
    r"(authoritative.*official.*rank|official.*weight|official.*recommend|"
    r"broker|trade[_ .-]*action|real[_ .-]*book)", re.I
)
SHARED_RE = re.compile(
    r"(data[\\/]+raw|universe|price|ohlcv|yahoo|cache|schema|guardrail|"
    r"date[_ .-]*helper|hash[_ .-]*helper|common[_ .-]*helper|shared)", re.I
)
HISTORICAL_RE = re.compile(r"(read_center|diagnostics|history|audit|review|report|migration|factor_backtest|factors)", re.I)
ACTIVE_SUFFIXES = {".py", ".ps1", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini"}


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
    return "V21_052_R3" not in path.name and bool(PROTECTED_RE.search(path.name))


def v20_output_matcher(path: Path) -> bool:
    return "staging" not in {part.lower() for part in path.parts}


def v21_current_matcher(path: Path) -> bool:
    return "V21_052_R3" not in path.name and any(
        token in path.name for token in ("V21_048", "V21_049", "V21_050", "V21_051", "V21_052_R1", "V21_052_R2")
    )


def corrected_stale_stage_reference(text: str) -> bool:
    normalized = text.replace("\\", "/")
    return bool(re.search(r"(?i)(?:^|[^0-9A-Za-z])(?:V20[._](?:8|9|10|11|12|13|14|15|16)|v20_(?:8|9|10|11|12|13|14|15|16))(?!\d)", normalized))


def split_sources(row: dict[str, str]) -> list[str]:
    return [clean(part).replace("\\", "/") for part in clean(row.get("referenced_by_v21")).split("|") if clean(part)]


def is_active_source(source: str) -> bool:
    source = source.replace("\\", "/")
    name = Path(source).name.lower()
    if not source.startswith("scripts/v21/"):
        return False
    if name.startswith("test_") or any(token in name for token in ("v21_050", "v21_051", "v21_052")):
        return False
    return Path(source).suffix.lower() in ACTIVE_SUFFIXES


def is_historical_source(source: str) -> bool:
    source = source.replace("\\", "/")
    return source.startswith("outputs/v21/") and bool(HISTORICAL_RE.search(source))


def shared_dependency(row: dict[str, str], file_path: str) -> bool:
    text = " ".join([
        file_path,
        clean(row.get("referenced_by_v21")),
        clean(row.get("r2_classification_reason")),
        clean(row.get("classification_reason")),
        clean(row.get("reference_type")),
    ])
    return clean(row.get("shared_dependency")).upper() == "TRUE" or bool(SHARED_RE.search(text))


def resolve_row(row: dict[str, str]) -> dict[str, object]:
    file_path = clean(row.get("file_path")).replace("\\", "/")
    ref_type = clean(row.get("reference_type"))
    sources = split_sources(row)
    active = any(is_active_source(source) for source in sources)
    historical = any(is_historical_source(source) for source in sources) or clean(row.get("historical_report_reference")).upper() == "TRUE"
    stale = corrected_stale_stage_reference(file_path)
    script_dep = file_path.startswith("scripts/v20/") or "V20_SCRIPT" in ref_type
    output_dep = file_path.startswith("outputs/v20/") or "V20_OUTPUT" in ref_type
    shared = shared_dependency(row, file_path)
    r2_class = clean(row.get("primary_classification"))
    unresolved = r2_class == "UNKNOWN_REQUIRES_MANUAL_REVIEW" or clean(row.get("requires_manual_review_after_r2")).upper() == "TRUE"
    newly = False

    if not unresolved:
        final = r2_class
        action = clean(row.get("proposed_action"))
        reason = clean(row.get("classification_reason")) or "Carried forward from V21.052-R2."
    else:
        newly = True
        if active and stale and (script_dep or output_dep):
            final = "ACTIVE_STALE_DOWNSTREAM_DEPENDENCY"
            action = "REMOVE_ACTIVE_STALE_DEPENDENCY"
            reason = "Unresolved R2 row is an active exact V20.8-V20.16 dependency."
        elif script_dep and active:
            final = "TRUE_V20_SCRIPT_DEPENDENCY"
            action = "MIGRATE_HELPER_TO_SHARED_OR_V21"
            reason = "Unresolved R2 row is an active scripts/v20 dependency."
        elif output_dep and active:
            final = "TRUE_V20_OUTPUT_DEPENDENCY"
            action = "MIGRATE_OUTPUT_SOURCE_TO_V21_NATIVE"
            reason = "Unresolved R2 row is an active outputs/v20 dependency."
        elif shared:
            final = "SHARED_HELPER_OR_DATA_DEPENDENCY"
            action = "MIGRATE_HELPER_TO_SHARED_OR_V21"
            reason = "Unresolved R2 row is shared helper/data infrastructure."
        elif historical or file_path.startswith("outputs/v21/migration/"):
            final = "HARMLESS_HISTORICAL_REFERENCE"
            action = "KEEP_AS_HISTORICAL_REFERENCE"
            reason = "Unresolved R2 row is a V21 report/migration/audit artifact, not an active source."
        else:
            final = "UNKNOWN_REQUIRES_MANUAL_REVIEW"
            action = "MANUAL_REVIEW_REQUIRED"
            reason = "R3 deterministic rules could not safely resolve this row."

    active_stale = final == "ACTIVE_STALE_DOWNSTREAM_DEPENDENCY"
    requires_migration = final in {
        "TRUE_V20_SCRIPT_DEPENDENCY",
        "TRUE_V20_OUTPUT_DEPENDENCY",
        "SHARED_HELPER_OR_DATA_DEPENDENCY",
    }
    archive_only = action == "ARCHIVE_WITH_V20_LEGACY"
    safe_to_ignore = final == "HARMLESS_HISTORICAL_REFERENCE"
    requires_manual = final == "UNKNOWN_REQUIRES_MANUAL_REVIEW"
    return {
        "file_path": file_path,
        "file_type": clean(row.get("file_type")),
        "size_mb": clean(row.get("size_mb")),
        "last_modified": clean(row.get("last_modified")),
        "referenced_by_v21": clean(row.get("referenced_by_v21")),
        "reference_type": ref_type,
        "active_current_dependency": tf(active),
        "historical_report_reference": tf(historical),
        "manual_review_reference": clean(row.get("manual_review_reference")) or "TRUE",
        "shared_dependency": tf(shared),
        "dependency_risk": clean(row.get("dependency_risk")),
        "stale_lineage_risk": "HIGH" if active_stale else clean(row.get("stale_lineage_risk")) or "LOW",
        "r2_primary_classification": r2_class,
        "r2_proposed_action": clean(row.get("proposed_action")),
        "r2_classification_reason": clean(row.get("classification_reason")),
        "final_classification": final,
        "final_proposed_action": action,
        "requires_migration": tf(requires_migration),
        "archive_only": tf(archive_only),
        "safe_to_ignore": tf(safe_to_ignore),
        "requires_manual_review_after_r3": tf(requires_manual),
        "active_stale_downstream_dependency": tf(active_stale),
        "newly_classified_by_r3": tf(newly and final != "UNKNOWN_REQUIRES_MANUAL_REVIEW"),
        "resolution_reason": reason,
    }


def rows_for(rows: list[dict[str, object]], classes: set[str]) -> list[dict[str, object]]:
    return [row for row in rows if clean(row.get("final_classification")) in classes]


def render_report(summary: dict[str, object]) -> str:
    return f"""# V21.052-R3 Manual Review Resolution

- final_status: {summary['final_status']}
- decision: {summary['decision']}
- unresolved_manual_review_count_before: {summary['unresolved_manual_review_count_before']}
- unresolved_manual_review_count_after: {summary['unresolved_manual_review_count_after']}
- final_active_stale_downstream_dependency_count: {summary['final_active_stale_downstream_dependency_count']}
- final_true_v20_script_dependency_count: {summary['final_true_v20_script_dependency_count']}
- final_true_v20_output_dependency_count: {summary['final_true_v20_output_dependency_count']}
- ready_for_shared_dependency_migration_dry_run: {summary['ready_for_shared_dependency_migration_dry_run']}
- recommended_next_stage: {summary['recommended_next_stage']}

This stage is classification/resolution only. No files were deleted, moved,
migrated, archived, or mutated.
"""


def run_resolution(
    root: Path,
    protected_mutation_hook: Callable[[], None] | None = None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    root = root.resolve()
    out_dir = root / "outputs/v21/migration"
    r2_summary = read_first(out_dir / "V21_052_R2_MANUAL_REVIEW_REFERENCE_CLASSIFIER_SUMMARY.csv")
    r2_rows, _ = read_csv(out_dir / "V21_052_R2_CLASSIFIED_MANUAL_REVIEW_REFERENCES.csv")
    inputs_valid = bool(r2_summary) and bool(r2_rows)

    before_files = {rel(root, p) for p in root.rglob("*") if p.is_file()}
    before_v20 = snapshot(root, root / "outputs/v20", v20_output_matcher)
    before_v21 = snapshot(root, root / "outputs/v21", v21_current_matcher)
    before_protected = snapshot(root, root / "outputs", protected_matcher)

    resolved_rows = [resolve_row(row) for row in r2_rows]
    if protected_mutation_hook:
        protected_mutation_hook()

    before_unresolved = sum(
        1 for row in r2_rows
        if clean(row.get("primary_classification")) == "UNKNOWN_REQUIRES_MANUAL_REVIEW"
        or clean(row.get("requires_manual_review_after_r2")).upper() == "TRUE"
    )
    after_unresolved = sum(1 for row in resolved_rows if row["requires_manual_review_after_r3"] == "TRUE")
    historical_rows = rows_for(resolved_rows, {"HARMLESS_HISTORICAL_REFERENCE"})
    shared_rows = rows_for(resolved_rows, {"SHARED_HELPER_OR_DATA_DEPENDENCY"})
    script_rows = rows_for(resolved_rows, {"TRUE_V20_SCRIPT_DEPENDENCY"})
    output_rows = rows_for(resolved_rows, {"TRUE_V20_OUTPUT_DEPENDENCY"})
    active_stale_rows = rows_for(resolved_rows, {"ACTIVE_STALE_DOWNSTREAM_DEPENDENCY"})
    blocking_rows = active_stale_rows + script_rows + output_rows
    migration_rows = shared_rows + script_rows + output_rows

    newly_rows = [row for row in resolved_rows if row["newly_classified_by_r3"] == "TRUE"]
    newly_historical = rows_for(newly_rows, {"HARMLESS_HISTORICAL_REFERENCE"})
    newly_shared = rows_for(newly_rows, {"SHARED_HELPER_OR_DATA_DEPENDENCY"})
    newly_script = rows_for(newly_rows, {"TRUE_V20_SCRIPT_DEPENDENCY"})
    newly_output = rows_for(newly_rows, {"TRUE_V20_OUTPUT_DEPENDENCY"})
    newly_active_stale = rows_for(newly_rows, {"ACTIVE_STALE_DOWNSTREAM_DEPENDENCY"})
    newly_archive = [row for row in newly_rows if row["archive_only"] == "TRUE"]
    newly_safe = [row for row in newly_rows if row["safe_to_ignore"] == "TRUE"]

    after_files = {rel(root, p) for p in root.rglob("*") if p.is_file()}
    deleted_or_moved = bool(before_files - after_files)
    v20_changes = changed(before_v20, snapshot(root, root / "outputs/v20", v20_output_matcher))
    v21_changes = changed(before_v21, snapshot(root, root / "outputs/v21", v21_current_matcher))
    protected_changes = changed(before_protected, snapshot(root, root / "outputs", protected_matcher))

    ready = inputs_valid and after_unresolved == 0 and not active_stale_rows and not script_rows and not output_rows
    if not inputs_valid:
        final_status = BLOCKED_INPUT
        decision = "BLOCK_INPUT_MISSING_OR_INVALID"
        recommended = "V21.052-R3_INPUT_REPAIR"
    elif active_stale_rows:
        final_status = BLOCKED_STALE
        decision = "BLOCK_ACTIVE_STALE_DOWNSTREAM_DEPENDENCY_FOUND"
        recommended = "V21.052-R4_ACTIVE_STALE_DEPENDENCY_REPAIR"
    elif script_rows or output_rows:
        final_status = BLOCKED_TRUE_ACTIVE
        decision = "BLOCK_TRUE_V20_ACTIVE_DEPENDENCY_FOUND"
        recommended = "V21.053-R1_TRUE_V20_ACTIVE_DEPENDENCY_MIGRATION"
    elif after_unresolved:
        final_status = PARTIAL_STATUS
        decision = "MANUAL_REVIEW_REDUCED_REVIEW_REMAINING"
        recommended = "V21.052-R4_MANUAL_REVIEW_RESOLUTION"
    else:
        final_status = PASS_STATUS
        decision = "MANUAL_REVIEW_RESOLVED_READY_FOR_SHARED_MIGRATION_DRY_RUN"
        recommended = "V21.053-R1_SHARED_DEPENDENCY_MIGRATION_DRY_RUN"
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
        "source_v21_052_r2_status": clean(r2_summary.get("final_status")) or "NOT_AVAILABLE",
        "unresolved_manual_review_count_before": before_unresolved,
        "unresolved_manual_review_count_after": after_unresolved,
        "total_references_reviewed": len(resolved_rows),
        "newly_classified_as_harmless_historical_count": len(newly_historical),
        "newly_classified_as_shared_dependency_count": len(newly_shared),
        "newly_classified_as_migration_required_count": len(newly_shared) + len(newly_script) + len(newly_output),
        "newly_classified_as_archive_only_count": len(newly_archive),
        "newly_classified_as_safe_to_ignore_count": len(newly_safe),
        "newly_classified_as_blocking_dependency_count": len(newly_active_stale) + len(newly_script) + len(newly_output),
        "final_harmless_historical_reference_count": len(historical_rows),
        "final_shared_dependency_count": len(shared_rows),
        "final_references_requiring_migration_count": len(migration_rows),
        "final_references_requiring_archive_only_count": sum(1 for row in resolved_rows if row["archive_only"] == "TRUE"),
        "final_references_safe_to_ignore_count": sum(1 for row in resolved_rows if row["safe_to_ignore"] == "TRUE"),
        "final_active_stale_downstream_dependency_count": len(active_stale_rows),
        "final_true_v20_script_dependency_count": len(script_rows),
        "final_true_v20_output_dependency_count": len(output_rows),
        "dependency_resolution_complete": tf(after_unresolved == 0),
        "ready_for_shared_dependency_migration_dry_run": tf(ready),
        "files_deleted_or_moved": tf(deleted_or_moved),
        "v20_outputs_mutated": tf(bool(v20_changes)),
        "v21_current_outputs_mutated": tf(bool(v21_changes)),
        "protected_outputs_mutated": tf(bool(protected_changes)),
        "protected_output_mutation_count": len(protected_changes),
        "deletion_allowed": "FALSE",
        "migration_allowed": "FALSE",
        "archive_allowed": "FALSE",
        **perms,
        "research_only": "TRUE",
        "recommended_next_stage": recommended,
        "created_at_utc": utc_now(),
    }

    write_csv(out_dir / "V21_052_R3_MANUAL_REVIEW_RESOLUTION_SUMMARY.csv", [summary], SUMMARY_FIELDS)
    write_csv(out_dir / "V21_052_R3_RESOLVED_MANUAL_REVIEW_REFERENCES.csv", resolved_rows, RESOLVED_FIELDS)
    write_csv(out_dir / "V21_052_R3_FINAL_SHARED_DEPENDENCY_MIGRATION_QUEUE.csv", migration_rows, RESOLVED_FIELDS)
    write_csv(out_dir / "V21_052_R3_FINAL_HARMLESS_HISTORICAL_REFERENCES.csv", historical_rows, RESOLVED_FIELDS)
    write_csv(out_dir / "V21_052_R3_FINAL_BLOCKING_DEPENDENCY_AUDIT.csv", blocking_rows, RESOLVED_FIELDS)
    report_path = root / "outputs/v21/read_center/V21_052_R3_MANUAL_REVIEW_RESOLUTION_REPORT.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(summary), encoding="utf-8")
    return summary, resolved_rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    summary, _ = run_resolution(args.root)
    for field in SUMMARY_FIELDS:
        print(f"{field.upper()}={summary.get(field, '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
