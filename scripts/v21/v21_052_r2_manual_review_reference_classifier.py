#!/usr/bin/env python
"""V21.052-R2 manual review V20 reference classifier.

Classification-only stage. Reads the V21.052-R1 manual-review output and
separates historical references, true V20 dependencies, shared helper/data
dependencies, and any active stale downstream dependency.
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
STAGE = "V21.052-R2_MANUAL_REVIEW_REFERENCE_CLASSIFIER"

PASS_STATUS = "PASS_V21_052_R2_MANUAL_REFERENCES_CLASSIFIED_READY_FOR_MIGRATION"
PARTIAL_STATUS = "PARTIAL_PASS_V21_052_R2_MANUAL_REFERENCES_CLASSIFIED_REVIEW_REMAINING"
BLOCKED_STALE = "BLOCKED_V21_052_R2_ACTIVE_STALE_DOWNSTREAM_DEPENDENCY_FOUND"
BLOCKED_INPUT = "BLOCKED_V21_052_R2_INPUT_MISSING_OR_INVALID"
BLOCKED_V20 = "BLOCKED_V21_052_R2_V20_OUTPUT_MUTATION_DETECTED"
BLOCKED_V21 = "BLOCKED_V21_052_R2_V21_CURRENT_OUTPUT_MUTATION_DETECTED"
BLOCKED_PROTECTED = "BLOCKED_V21_052_R2_PROTECTED_OUTPUT_MUTATION_DETECTED"
BLOCKED_PERMISSION = "BLOCKED_V21_052_R2_OFFICIAL_PERMISSION_VIOLATION"

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "source_v21_052_r1_status",
    "corrected_stage_matching_used", "manual_review_reference_count_from_summary",
    "manual_review_reference_count_from_file", "manual_review_count_reconciled",
    "total_manual_review_references_classified", "harmless_historical_reference_count",
    "true_v20_script_dependency_count", "true_v20_output_dependency_count",
    "shared_helper_or_data_dependency_count", "active_current_v20_output_dependency_count",
    "active_current_v20_script_dependency_count", "active_stale_downstream_dependency_count",
    "stale_downstream_dependency_found", "references_requiring_migration_count",
    "references_requiring_archive_only_count", "references_safe_to_ignore_count",
    "references_requiring_manual_review_after_r2", "files_deleted_or_moved",
    "v20_outputs_mutated", "v21_current_outputs_mutated", "protected_outputs_mutated",
    "protected_output_mutation_count", "deletion_allowed", "migration_allowed",
    "archive_allowed", "official_activation_allowed", "official_recommendation_allowed",
    "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
    "broker_execution_allowed", "trade_action_allowed", "research_only",
    "recommended_next_stage", "created_at_utc",
]

CLASSIFIED_FIELDS = [
    "file_path", "file_type", "size_mb", "last_modified", "referenced_by_v21",
    "reference_type", "active_current_dependency", "historical_report_reference",
    "manual_review_reference", "shared_dependency", "dependency_risk",
    "stale_lineage_risk", "r1_classification", "r1_proposed_action", "r1_reason",
    "primary_classification", "proposed_action", "requires_migration",
    "archive_only", "safe_to_ignore", "requires_manual_review_after_r2",
    "active_stale_downstream_dependency", "classification_reason",
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
    return "V21_052_R2" not in path.name and bool(PROTECTED_RE.search(path.name))


def v20_output_matcher(path: Path) -> bool:
    return "staging" not in {part.lower() for part in path.parts}


def v21_current_matcher(path: Path) -> bool:
    return "V21_052_R2" not in path.name and any(
        token in path.name for token in ("V21_048", "V21_049", "V21_050", "V21_051", "V21_052_R1")
    )


def corrected_stale_stage_reference(text: str) -> bool:
    normalized = text.replace("\\", "/")
    return bool(re.search(r"(?i)(?:^|[^0-9A-Za-z])(?:V20[._](?:8|9|10|11|12|13|14|15|16)|v20_(?:8|9|10|11|12|13|14|15|16))(?!\d)", normalized))


def is_active_source(source: str) -> bool:
    source = source.replace("\\", "/")
    name = Path(source).name.lower()
    if not source.startswith("scripts/v21/"):
        return False
    if name.startswith("test_") or any(token in name for token in ("v21_050", "v21_051", "v21_052")):
        return False
    return Path(source).suffix.lower() in ACTIVE_SUFFIXES


def split_sources(row: dict[str, str]) -> list[str]:
    return [clean(part).replace("\\", "/") for part in clean(row.get("referenced_by_v21")).split("|") if clean(part)]


def is_historical_source(source: str) -> bool:
    source = source.replace("\\", "/")
    return source.startswith("outputs/v21/") and bool(HISTORICAL_RE.search(source))


def is_shared_dependency(row: dict[str, str], file_path: str) -> bool:
    text = " ".join([
        file_path,
        clean(row.get("referenced_by_v21")),
        clean(row.get("reason")),
        clean(row.get("reference_type")),
    ])
    return clean(row.get("shared_dependency")).upper() == "TRUE" or bool(SHARED_RE.search(text))


def classify_manual_row(row: dict[str, str]) -> dict[str, object]:
    file_path = clean(row.get("file_path")).replace("\\", "/")
    ref_type = clean(row.get("reference_type"))
    sources = split_sources(row)
    active_sources = [src for src in sources if is_active_source(src)]
    historical_sources = [src for src in sources if is_historical_source(src)]
    stale = corrected_stale_stage_reference(file_path)
    script_dep = file_path.startswith("scripts/v20/") or "V20_SCRIPT" in ref_type
    output_dep = file_path.startswith("outputs/v20/") or "V20_OUTPUT" in ref_type
    shared_dep = is_shared_dependency(row, file_path)
    active = bool(active_sources)
    historical = bool(historical_sources) or clean(row.get("historical_report_reference")).upper() == "TRUE"
    active_stale = active and stale and (script_dep or output_dep)

    if active_stale:
        primary = "ACTIVE_STALE_DOWNSTREAM_DEPENDENCY"
        action = "REMOVE_ACTIVE_STALE_DEPENDENCY"
        reason = "Active current V21 source references exact V20.8-V20.16 stale downstream."
    elif script_dep and active:
        primary = "TRUE_V20_SCRIPT_DEPENDENCY"
        action = "MIGRATE_HELPER_TO_SHARED_OR_V21"
        reason = "Active V21 source imports or calls scripts/v20."
    elif output_dep and active:
        primary = "TRUE_V20_OUTPUT_DEPENDENCY"
        action = "MIGRATE_OUTPUT_SOURCE_TO_V21_NATIVE"
        reason = "Active V21 source uses outputs/v20 as a current input/source."
    elif shared_dep:
        primary = "SHARED_HELPER_OR_DATA_DEPENDENCY"
        action = "MIGRATE_HELPER_TO_SHARED_OR_V21"
        reason = "Reference is shared data/helper infrastructure rather than stale V20 downstream."
    elif historical:
        primary = "HARMLESS_HISTORICAL_REFERENCE"
        action = "KEEP_AS_HISTORICAL_REFERENCE"
        reason = "Reference appears only in historical/report/audit evidence, not active execution."
    elif output_dep:
        primary = "HARMLESS_HISTORICAL_REFERENCE"
        action = "ARCHIVE_WITH_V20_LEGACY"
        reason = "V20 output reference is not active; retain for legacy archive context."
    else:
        primary = "UNKNOWN_REQUIRES_MANUAL_REVIEW"
        action = "MANUAL_REVIEW_REQUIRED"
        reason = "Reference could not be safely classified by R2 rules."

    requires_migration = primary in {
        "TRUE_V20_SCRIPT_DEPENDENCY",
        "TRUE_V20_OUTPUT_DEPENDENCY",
        "SHARED_HELPER_OR_DATA_DEPENDENCY",
    }
    archive_only = action == "ARCHIVE_WITH_V20_LEGACY"
    safe_to_ignore = primary == "HARMLESS_HISTORICAL_REFERENCE" and action == "KEEP_AS_HISTORICAL_REFERENCE"
    requires_manual = primary == "UNKNOWN_REQUIRES_MANUAL_REVIEW"
    classified = {
        "file_path": file_path,
        "file_type": clean(row.get("file_type")),
        "size_mb": clean(row.get("size_mb")),
        "last_modified": clean(row.get("last_modified")),
        "referenced_by_v21": clean(row.get("referenced_by_v21")),
        "reference_type": ref_type,
        "active_current_dependency": tf(active),
        "historical_report_reference": tf(historical),
        "manual_review_reference": "TRUE",
        "shared_dependency": tf(shared_dep),
        "dependency_risk": clean(row.get("dependency_risk")),
        "stale_lineage_risk": "HIGH" if active_stale else clean(row.get("stale_lineage_risk")) or "LOW",
        "r1_classification": clean(row.get("classification")),
        "r1_proposed_action": clean(row.get("proposed_action")),
        "r1_reason": clean(row.get("reason")),
        "primary_classification": primary,
        "proposed_action": action,
        "requires_migration": tf(requires_migration),
        "archive_only": tf(archive_only),
        "safe_to_ignore": tf(safe_to_ignore),
        "requires_manual_review_after_r2": tf(requires_manual),
        "active_stale_downstream_dependency": tf(active_stale),
        "classification_reason": reason,
    }
    return classified


def rows_for(rows: list[dict[str, object]], classifications: set[str]) -> list[dict[str, object]]:
    return [row for row in rows if clean(row.get("primary_classification")) in classifications]


def render_report(summary: dict[str, object]) -> str:
    return f"""# V21.052-R2 Manual Review Reference Classifier

- final_status: {summary['final_status']}
- decision: {summary['decision']}
- manual_review_reference_count_from_summary: {summary['manual_review_reference_count_from_summary']}
- manual_review_reference_count_from_file: {summary['manual_review_reference_count_from_file']}
- manual_review_count_reconciled: {summary['manual_review_count_reconciled']}
- total_manual_review_references_classified: {summary['total_manual_review_references_classified']}
- active_stale_downstream_dependency_count: {summary['active_stale_downstream_dependency_count']}
- stale_downstream_dependency_found: {summary['stale_downstream_dependency_found']}
- references_requiring_migration_count: {summary['references_requiring_migration_count']}
- references_requiring_manual_review_after_r2: {summary['references_requiring_manual_review_after_r2']}
- recommended_next_stage: {summary['recommended_next_stage']}

This stage is classification-only. It uses corrected V20 stage matching, so
V20_108 is not V20.10 and V20_166 is not V20.16. No files were deleted, moved,
migrated, archived, or mutated.
"""


def run_classifier(
    root: Path,
    protected_mutation_hook: Callable[[], None] | None = None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    root = root.resolve()
    out_dir = root / "outputs/v21/migration"
    summary_r1 = read_first(out_dir / "V21_052_R1_V20_DEPENDENCY_MIGRATION_RECHECK_SUMMARY.csv")
    manual_rows, _ = read_csv(out_dir / "V21_052_R1_MANUAL_REVIEW_REFERENCES.csv")
    inputs_valid = bool(summary_r1) and bool(manual_rows)

    before_files = {rel(root, p) for p in root.rglob("*") if p.is_file()}
    before_v20 = snapshot(root, root / "outputs/v20", v20_output_matcher)
    before_v21 = snapshot(root, root / "outputs/v21", v21_current_matcher)
    before_protected = snapshot(root, root / "outputs", protected_matcher)

    classified_rows = [classify_manual_row(row) for row in manual_rows]
    if protected_mutation_hook:
        protected_mutation_hook()

    script_rows = rows_for(classified_rows, {"TRUE_V20_SCRIPT_DEPENDENCY"})
    output_rows = rows_for(classified_rows, {"TRUE_V20_OUTPUT_DEPENDENCY"})
    historical_rows = rows_for(classified_rows, {"HARMLESS_HISTORICAL_REFERENCE"})
    shared_rows = rows_for(classified_rows, {"SHARED_HELPER_OR_DATA_DEPENDENCY"})
    active_stale_rows = rows_for(classified_rows, {"ACTIVE_STALE_DOWNSTREAM_DEPENDENCY"})
    unknown_rows = rows_for(classified_rows, {"UNKNOWN_REQUIRES_MANUAL_REVIEW"})

    after_files = {rel(root, p) for p in root.rglob("*") if p.is_file()}
    deleted_or_moved = bool(before_files - after_files)
    v20_changes = changed(before_v20, snapshot(root, root / "outputs/v20", v20_output_matcher))
    v21_changes = changed(before_v21, snapshot(root, root / "outputs/v21", v21_current_matcher))
    protected_changes = changed(before_protected, snapshot(root, root / "outputs", protected_matcher))

    from_summary = clean(summary_r1.get("manual_review_reference_count"))
    from_file = len(manual_rows)
    reconciled = from_summary.isdigit() and int(from_summary) == from_file
    references_requiring_migration = len(script_rows) + len(output_rows) + len(shared_rows)
    archive_only = sum(1 for row in classified_rows if row["archive_only"] == "TRUE")
    safe_to_ignore = sum(1 for row in classified_rows if row["safe_to_ignore"] == "TRUE")

    if not inputs_valid:
        final_status = BLOCKED_INPUT
        decision = "BLOCK_INPUT_MISSING_OR_INVALID"
        recommended = "V21.052-R2_INPUT_REPAIR"
    elif active_stale_rows:
        final_status = BLOCKED_STALE
        decision = "BLOCK_ACTIVE_STALE_DOWNSTREAM_DEPENDENCY_FOUND"
        recommended = "V21.052-R3_ACTIVE_STALE_DEPENDENCY_REPAIR"
    elif unknown_rows:
        final_status = PARTIAL_STATUS
        decision = "MANUAL_REFERENCES_CLASSIFIED_REVIEW_REMAINING"
        recommended = "V21.052-R3_MANUAL_REVIEW_RESOLUTION"
    else:
        final_status = PASS_STATUS
        decision = "MANUAL_REFERENCES_CLASSIFIED_READY_FOR_MIGRATION"
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
        "source_v21_052_r1_status": clean(summary_r1.get("final_status")) or "NOT_AVAILABLE",
        "corrected_stage_matching_used": "TRUE",
        "manual_review_reference_count_from_summary": from_summary or "NOT_AVAILABLE",
        "manual_review_reference_count_from_file": from_file,
        "manual_review_count_reconciled": tf(reconciled),
        "total_manual_review_references_classified": len(classified_rows),
        "harmless_historical_reference_count": len(historical_rows),
        "true_v20_script_dependency_count": len(script_rows),
        "true_v20_output_dependency_count": len(output_rows),
        "shared_helper_or_data_dependency_count": len(shared_rows),
        "active_current_v20_output_dependency_count": len(output_rows) + len([row for row in active_stale_rows if "V20_OUTPUT" in clean(row.get("reference_type"))]),
        "active_current_v20_script_dependency_count": len(script_rows) + len([row for row in active_stale_rows if "V20_SCRIPT" in clean(row.get("reference_type"))]),
        "active_stale_downstream_dependency_count": len(active_stale_rows),
        "stale_downstream_dependency_found": tf(bool(active_stale_rows)),
        "references_requiring_migration_count": references_requiring_migration,
        "references_requiring_archive_only_count": archive_only,
        "references_safe_to_ignore_count": safe_to_ignore,
        "references_requiring_manual_review_after_r2": len(unknown_rows),
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

    write_csv(out_dir / "V21_052_R2_MANUAL_REVIEW_REFERENCE_CLASSIFIER_SUMMARY.csv", [summary], SUMMARY_FIELDS)
    write_csv(out_dir / "V21_052_R2_CLASSIFIED_MANUAL_REVIEW_REFERENCES.csv", classified_rows, CLASSIFIED_FIELDS)
    write_csv(out_dir / "V21_052_R2_TRUE_V20_SCRIPT_DEPENDENCIES.csv", script_rows, CLASSIFIED_FIELDS)
    write_csv(out_dir / "V21_052_R2_TRUE_V20_OUTPUT_DEPENDENCIES.csv", output_rows, CLASSIFIED_FIELDS)
    write_csv(out_dir / "V21_052_R2_HARMLESS_HISTORICAL_REFERENCES.csv", historical_rows, CLASSIFIED_FIELDS)
    write_csv(out_dir / "V21_052_R2_SHARED_HELPER_OR_DATA_DEPENDENCIES.csv", shared_rows, CLASSIFIED_FIELDS)
    write_csv(out_dir / "V21_052_R2_STALE_DOWNSTREAM_ACTIVE_DEPENDENCY_AUDIT.csv", active_stale_rows, CLASSIFIED_FIELDS)
    report_path = root / "outputs/v21/read_center/V21_052_R2_MANUAL_REVIEW_REFERENCE_CLASSIFIER_REPORT.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(summary), encoding="utf-8")
    return summary, classified_rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    summary, _ = run_classifier(args.root)
    for field in SUMMARY_FIELDS:
        print(f"{field.upper()}={summary.get(field, '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
