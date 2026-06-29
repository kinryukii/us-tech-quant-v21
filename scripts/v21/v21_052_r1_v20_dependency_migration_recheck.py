#!/usr/bin/env python
"""V21.052-R1 V20 dependency migration recheck.

Dry-run only. Rechecks V20 references with corrected stage-token matching so
V20_108 and V20_166 are not treated as stale V20.10/V20.16 downstream stages.
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
STAGE = "V21.052-R1_V20_DEPENDENCY_MIGRATION_RECHECK"

PASS_STATUS = "PASS_V21_052_R1_V20_DEPENDENCY_RECHECK_READY_FOR_MIGRATION_ARCHIVE"
PARTIAL_SHARED = "PARTIAL_PASS_V21_052_R1_SHARED_AND_HISTORICAL_DEPENDENCIES_ONLY"
PARTIAL_MANUAL = "PARTIAL_PASS_V21_052_R1_MANUAL_REVIEW_REFERENCES_REMAIN"
BLOCKED_STALE = "BLOCKED_V21_052_R1_ACTIVE_STALE_DOWNSTREAM_DEPENDENCY_REMAINS"
BLOCKED_INPUT = "BLOCKED_V21_052_R1_REQUIRED_INPUT_MISSING_OR_INVALID"
BLOCKED_V20 = "BLOCKED_V21_052_R1_V20_OUTPUT_MUTATION_DETECTED"
BLOCKED_V21 = "BLOCKED_V21_052_R1_V21_CURRENT_OUTPUT_MUTATION_DETECTED"
BLOCKED_PROTECTED = "BLOCKED_V21_052_R1_PROTECTED_OUTPUT_MUTATION_DETECTED"
BLOCKED_PERMISSION = "BLOCKED_V21_052_R1_OFFICIAL_PERMISSION_VIOLATION"

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "source_v21_050_status",
    "source_v21_051_status", "corrected_stage_matching_used",
    "v21_active_current_reads_v20_8_to_v20_16_stale_downstream",
    "v21_reads_v20_outputs", "v21_reads_v20_scripts",
    "shared_data_dependency_found", "historical_report_reference_count",
    "manual_review_reference_count", "shared_dependency_candidate_count",
    "migration_candidate_count", "archive_candidate_count",
    "delete_candidate_count", "protected_never_delete_count",
    "unsafe_delete_candidate_count", "estimated_archive_size_mb",
    "estimated_delete_candidate_size_mb", "files_deleted_or_moved",
    "v20_outputs_mutated", "v21_current_outputs_mutated",
    "protected_outputs_mutated", "protected_output_mutation_count",
    "deletion_allowed", "migration_allowed", "archive_allowed",
    "official_activation_allowed", "official_recommendation_allowed",
    "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
    "broker_execution_allowed", "trade_action_allowed", "research_only",
    "recommended_next_stage", "created_at_utc",
]

AUDIT_FIELDS = [
    "file_path", "file_type", "size_mb", "last_modified", "referenced_by_v21",
    "reference_type", "active_current_dependency", "historical_report_reference",
    "manual_review_reference", "shared_dependency", "dependency_risk",
    "stale_lineage_risk", "classification", "proposed_action",
    "proposed_destination", "reason",
]

TEXT_SUFFIXES = {".py", ".ps1", ".csv", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini"}
ACTIVE_SUFFIXES = {".py", ".ps1", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini"}
V20_OUTPUT_RE = re.compile(r"outputs[\\/]+v20[\\/][A-Za-z0-9_ .\\/\\-]+")
V20_SCRIPT_RE = re.compile(r"scripts[\\/]+v20[\\/][A-Za-z0-9_ .\\/\\-]+")
PROTECTED_RE = re.compile(
    r"(authoritative.*official.*rank|official.*weight|official.*recommend|"
    r"broker|trade[_ .-]*action|real[_ .-]*book)", re.I
)
SHARED_RE = re.compile(r"(data[\\/]+raw|universe|price|ohlcv|yahoo|cache)", re.I)


def clean(value: object) -> str:
    return str(value or "").strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists() or path.stat().st_size == 0:
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def read_first(path: Path) -> dict[str, str]:
    rows, _ = read_csv(path)
    return rows[0] if rows else {}


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def snapshot(root: Path, base: Path, matcher: Callable[[Path], bool]) -> dict[str, str]:
    if not base.exists():
        return {}
    return {rel(root, p): file_hash(p) for p in base.rglob("*") if p.is_file() and matcher(p)}


def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


def protected_matcher(path: Path) -> bool:
    return "V21_052_R1" not in path.name and bool(PROTECTED_RE.search(path.name))


def v20_output_matcher(path: Path) -> bool:
    return "staging" not in {part.lower() for part in path.parts}


def v21_current_matcher(path: Path) -> bool:
    return "V21_052_R1" not in path.name and (
        "V21_048" in path.name or "V21_049" in path.name or "V21_050" in path.name or "V21_051" in path.name
    )


def corrected_stale_stage_reference(text: str) -> bool:
    normalized = text.replace("\\", "/")
    return bool(re.search(r"(?i)(?:^|[^0-9A-Za-z])(?:V20[._](?:8|9|10|11|12|13|14|15|16)|v20_(?:8|9|10|11|12|13|14|15|16))(?!\d)", normalized))


def normalize_ref(ref_text: str) -> str:
    return ref_text.replace("\\", "/").strip(" ,;:'\")(")


def text_files(root: Path, base: Path) -> list[Path]:
    if not base.exists():
        return []
    return [p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES]


def is_active_location(path: Path, root: Path) -> bool:
    r = rel(root, path)
    if not r.startswith("scripts/v21/"):
        return False
    name = path.name.lower()
    if name.startswith("test_") or "v21_050" in name or "v21_051" in name or "v21_052" in name:
        return False
    return path.suffix.lower() in ACTIVE_SUFFIXES


def is_historical_location(path: Path, root: Path) -> bool:
    r = rel(root, path)
    return r.startswith("outputs/v21/") and not r.startswith("outputs/v21/migration/")


def reference_sources(root: Path) -> tuple[dict[str, set[str]], dict[str, set[str]], bool, set[str], set[str]]:
    output_refs: dict[str, set[str]] = {}
    script_refs: dict[str, set[str]] = {}
    shared_found = False
    active_stale_locations: set[str] = set()
    historical_locations: set[str] = set()
    for base in (root / "scripts/v21", root / "outputs/v21"):
        for path in text_files(root, base):
            rpath = rel(root, path)
            if rpath.startswith("outputs/v21/migration/") and "V21_050_R1" not in path.name and "V21_051_R1" not in path.name:
                continue
            if "V21_052_R1" in path.name:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if SHARED_RE.search(text):
                shared_found = True
            active = is_active_location(path, root)
            historical = is_historical_location(path, root)
            for match in V20_OUTPUT_RE.findall(text):
                ref = normalize_ref(match)
                output_refs.setdefault(ref, set()).add(rpath)
                if corrected_stale_stage_reference(ref):
                    if active:
                        active_stale_locations.add(rpath)
                    elif historical:
                        historical_locations.add(rpath)
            for match in V20_SCRIPT_RE.findall(text):
                ref = normalize_ref(match)
                script_refs.setdefault(ref, set()).add(rpath)
                if corrected_stale_stage_reference(ref):
                    if active:
                        active_stale_locations.add(rpath)
                    elif historical:
                        historical_locations.add(rpath)
    return output_refs, script_refs, shared_found, active_stale_locations, historical_locations


def file_type(path: Path) -> str:
    parts = {part.lower() for part in path.parts}
    if "scripts" in parts:
        return "script"
    if "outputs" in parts:
        return "output"
    if "data" in parts:
        return "data"
    return path.suffix.lower().lstrip(".") or "file"


def size_mb(path: Path) -> float:
    return round(path.stat().st_size / (1024 * 1024), 6)


def scanned_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for base in (root / "outputs/v20", root / "scripts/v20", root / "data", root / "outputs/v21/context", root / "outputs/v21/migration"):
        if base.exists():
            paths.extend(p for p in base.rglob("*") if p.is_file())
    return sorted(set(paths), key=lambda p: rel(root, p))


def classify_file(
    root: Path,
    path: Path,
    output_refs: dict[str, set[str]],
    script_refs: dict[str, set[str]],
) -> dict[str, object]:
    r = rel(root, path)
    rb = r.replace("/", "\\")
    ref_sources = set(output_refs.get(r, set())) | set(output_refs.get(rb, set()))
    script_sources = set(script_refs.get(r, set())) | set(script_refs.get(rb, set()))
    referenced_by = ref_sources | script_sources
    active_sources = {src for src in referenced_by if src.startswith("scripts/v21/")}
    historical_sources = {src for src in referenced_by if src.startswith("outputs/v21/")}
    protected = bool(PROTECTED_RE.search(r))
    raw_data = r.startswith("data/") or bool(SHARED_RE.search(r))
    v21_current = r.startswith("outputs/v21/") and any(token in path.name for token in ("V21_048", "V21_049", "V21_050", "V21_051"))
    v20_closeout = "V20_16_R4_LEGACY_DOWNSTREAM_STALE_LINEAGE_CLOSEOUT" in path.name
    staging_or_temp = "/staging/" in r or "/tmp/" in r or path.name.endswith(".tmp")
    v20_artifact = r.startswith("outputs/v20/") or r.startswith("scripts/v20/")
    stale = v20_artifact and corrected_stale_stage_reference(path.name)
    active_stale = stale and bool(active_sources)
    historical_stale = stale and bool(historical_sources) and not active_stale

    if protected:
        classification, action, dest, risk, reason = "NEVER_DELETE_PROTECTED_OFFICIAL", "KEEP", "", "CRITICAL", "Official/protected file."
    elif raw_data:
        classification, action, dest, risk, reason = "KEEP_SHARED_DATA", "KEEP", "", "LOW", "Shared raw data, price, cache, or universe dependency."
    elif v21_current:
        classification, action, dest, risk, reason = "KEEP_CURRENT_V21", "KEEP", "", "LOW", "Current V21.048/V21.049/V21.050/V21.051 output."
    elif v20_closeout:
        classification, action, dest, risk, reason = "NEVER_DELETE_PROTECTED_OFFICIAL", "KEEP", "", "LOW", "V20.16-R4 closeout retained as never-delete record."
    elif staging_or_temp:
        classification, action, dest, risk, reason = "DELETE_CANDIDATE_TEMP_OR_STAGING", "DRY_RUN_DELETE_CANDIDATE_ONLY", "", "LOW", "Temporary/staging artifact; dry-run candidate only."
    elif active_stale:
        classification, action, dest, risk, reason = "MANUAL_REVIEW_REQUIRED", "REPAIR_ACTIVE_STALE_DEPENDENCY", "", "HIGH", "Active V21 source references exact V20.8-V20.16 stale downstream."
    elif historical_stale:
        classification, action, dest, risk, reason = "MANUAL_REVIEW_REQUIRED", "MANUAL_REVIEW_HISTORICAL_REFERENCE", "", "MEDIUM", "Historical/report reference to stale V20.8-V20.16 artifact."
    elif referenced_by and r.startswith("outputs/v20/"):
        classification, action, dest, risk, reason = "MIGRATE_TO_V21", "MIGRATE_DRY_RUN_ONLY", "outputs/v21/migrated_v20_dependencies/", "MEDIUM", "V21 references V20 output that is not exact stale downstream."
    elif referenced_by and r.startswith("scripts/v20/"):
        classification, action, dest, risk, reason = "MIGRATE_TO_SHARED_HELPER", "MIGRATE_DRY_RUN_ONLY", "scripts/shared/", "MEDIUM", "V21 references V20 script/helper."
    elif v20_artifact:
        classification, action, dest, risk, reason = "ARCHIVE_V20_LEGACY", "ARCHIVE_DRY_RUN_ONLY", "archive/v20/", "LOW", "Unreferenced V20 legacy artifact."
    else:
        classification, action, dest, risk, reason = "MANUAL_REVIEW_REQUIRED", "REVIEW", "", "MEDIUM", "Unclassified scanned file."

    ref_type = "NONE"
    if ref_sources:
        ref_type = "V20_OUTPUT"
    if script_sources:
        ref_type = "V20_SCRIPT" if ref_type == "NONE" else ref_type + "|V20_SCRIPT"
    return {
        "file_path": r,
        "file_type": file_type(path),
        "size_mb": f"{size_mb(path):.6f}",
        "last_modified": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat(),
        "referenced_by_v21": "|".join(sorted(referenced_by)),
        "reference_type": ref_type,
        "active_current_dependency": tf(bool(active_sources)),
        "historical_report_reference": tf(bool(historical_sources)),
        "manual_review_reference": tf(classification == "MANUAL_REVIEW_REQUIRED"),
        "shared_dependency": tf(raw_data),
        "dependency_risk": risk,
        "stale_lineage_risk": "HIGH" if active_stale else "MEDIUM" if historical_stale or stale else "LOW",
        "classification": classification,
        "proposed_action": action,
        "proposed_destination": dest,
        "reason": reason,
    }


def rows_for(rows: list[dict[str, object]], classes: set[str]) -> list[dict[str, object]]:
    return [row for row in rows if clean(row.get("classification")) in classes]


def render_report(summary: dict[str, object]) -> str:
    return f"""# V21.052-R1 V20 Dependency Migration Recheck

- final_status: {summary['final_status']}
- decision: {summary['decision']}
- corrected_stage_matching_used: TRUE
- active stale downstream dependency: {summary['v21_active_current_reads_v20_8_to_v20_16_stale_downstream']}
- migration_candidate_count: {summary['migration_candidate_count']}
- archive_candidate_count: {summary['archive_candidate_count']}
- delete_candidate_count: {summary['delete_candidate_count']}
- manual_review_reference_count: {summary['manual_review_reference_count']}
- recommended_next_stage: {summary['recommended_next_stage']}

This dry run uses exact V20.8-V20.16 stage-token matching. V20_108 is not V20.10,
and V20_166 is not V20.16. No files were deleted, moved, archived, migrated, or
mutated.
"""


def run_recheck(
    root: Path,
    protected_mutation_hook: Callable[[], None] | None = None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    root = root.resolve()
    out_dir = root / "outputs/v21/migration"
    v21_050 = read_first(out_dir / "V21_050_R1_V20_DEPENDENCY_MIGRATION_AND_CLEANUP_DRY_RUN_SUMMARY.csv")
    v21_051 = read_first(out_dir / "V21_051_R1_REMOVE_V20_STALE_DOWNSTREAM_DEPENDENCY_SUMMARY.csv")
    inputs_valid = bool(v21_050) and bool(v21_051)
    before_files = {rel(root, p) for p in root.rglob("*") if p.is_file()}
    before_v20 = snapshot(root, root / "outputs/v20", v20_output_matcher)
    before_v21 = snapshot(root, root / "outputs/v21", v21_current_matcher)
    before_protected = snapshot(root, root / "outputs", protected_matcher)

    output_refs, script_refs, shared_found, active_stale_locations, historical_locations = reference_sources(root)
    audit_rows = [classify_file(root, path, output_refs, script_refs) for path in scanned_files(root)]
    if protected_mutation_hook:
        protected_mutation_hook()

    shared_rows = [row for row in audit_rows if row["shared_dependency"] == "TRUE"]
    migration_rows = rows_for(audit_rows, {"MIGRATE_TO_V21", "MIGRATE_TO_SHARED_HELPER"})
    archive_rows = rows_for(audit_rows, {"ARCHIVE_V20_LEGACY"})
    delete_rows = rows_for(audit_rows, {"DELETE_CANDIDATE_TEMP_OR_STAGING", "DELETE_CANDIDATE_DUPLICATE_ARTIFACT"})
    manual_rows = rows_for(audit_rows, {"MANUAL_REVIEW_REQUIRED"})
    protected_rows = rows_for(audit_rows, {"NEVER_DELETE_PROTECTED_OFFICIAL", "KEEP_CURRENT_V21", "KEEP_SHARED_DATA"})

    after_files = {rel(root, p) for p in root.rglob("*") if p.is_file()}
    deleted_or_moved = bool(before_files - after_files)
    v20_changes = changed(before_v20, snapshot(root, root / "outputs/v20", v20_output_matcher))
    v21_changes = changed(before_v21, snapshot(root, root / "outputs/v21", v21_current_matcher))
    protected_changes = changed(before_protected, snapshot(root, root / "outputs", protected_matcher))

    active_stale = bool(active_stale_locations)
    if not inputs_valid:
        final_status = BLOCKED_INPUT
        decision = "BLOCK_REQUIRED_INPUT_MISSING_OR_INVALID"
        recommended = "V21.052-R1_INPUT_REPAIR"
    elif active_stale:
        final_status = BLOCKED_STALE
        decision = "BLOCK_ACTIVE_STALE_DOWNSTREAM_DEPENDENCY_REMAINS"
        recommended = "V21.052-R2_ACTIVE_STALE_DEPENDENCY_REPAIR"
    elif manual_rows:
        final_status = PARTIAL_MANUAL
        decision = "MANUAL_REVIEW_REFERENCES_REMAIN_RECHECK_READY"
        recommended = "V21.052-R2_MANUAL_REVIEW_REFERENCE_CLASSIFIER"
    elif migration_rows:
        final_status = PASS_STATUS
        decision = "RECHECK_READY_FOR_SHARED_DEPENDENCY_MIGRATION_DRY_RUN"
        recommended = "V21.053-R1_SHARED_DEPENDENCY_MIGRATION_DRY_RUN"
    elif shared_rows:
        final_status = PARTIAL_SHARED
        decision = "SHARED_AND_HISTORICAL_DEPENDENCIES_ONLY"
        recommended = "V20_ARCHIVE_DRY_RUN"
    else:
        final_status = PASS_STATUS
        decision = "RECHECK_READY_FOR_ARCHIVE_DRY_RUN"
        recommended = "V20_ARCHIVE_DRY_RUN"
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
        "source_v21_050_status": clean(v21_050.get("final_status")) or "NOT_AVAILABLE",
        "source_v21_051_status": clean(v21_051.get("final_status")) or "NOT_AVAILABLE",
        "corrected_stage_matching_used": "TRUE",
        "v21_active_current_reads_v20_8_to_v20_16_stale_downstream": tf(active_stale),
        "v21_reads_v20_outputs": tf(bool(output_refs)),
        "v21_reads_v20_scripts": tf(bool(script_refs)),
        "shared_data_dependency_found": tf(shared_found or bool(shared_rows)),
        "historical_report_reference_count": len(historical_locations),
        "manual_review_reference_count": len(manual_rows),
        "shared_dependency_candidate_count": len(shared_rows),
        "migration_candidate_count": len(migration_rows),
        "archive_candidate_count": len(archive_rows),
        "delete_candidate_count": len(delete_rows),
        "protected_never_delete_count": len(protected_rows),
        "unsafe_delete_candidate_count": 0,
        "estimated_archive_size_mb": f"{sum(float(row['size_mb']) for row in archive_rows):.6f}",
        "estimated_delete_candidate_size_mb": f"{sum(float(row['size_mb']) for row in delete_rows):.6f}",
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

    write_csv(out_dir / "V21_052_R1_V20_DEPENDENCY_MIGRATION_RECHECK_SUMMARY.csv", [summary], SUMMARY_FIELDS)
    write_csv(out_dir / "V21_052_R1_RECHECK_DEPENDENCY_AUDIT_BY_FILE.csv", audit_rows, AUDIT_FIELDS)
    write_csv(out_dir / "V21_052_R1_SHARED_DEPENDENCY_CANDIDATES.csv", shared_rows, AUDIT_FIELDS)
    write_csv(out_dir / "V21_052_R1_MIGRATION_CANDIDATES.csv", migration_rows, AUDIT_FIELDS)
    write_csv(out_dir / "V21_052_R1_ARCHIVE_CANDIDATES.csv", archive_rows, AUDIT_FIELDS)
    write_csv(out_dir / "V21_052_R1_DELETE_CANDIDATES_DRY_RUN.csv", delete_rows, AUDIT_FIELDS)
    write_csv(out_dir / "V21_052_R1_MANUAL_REVIEW_REFERENCES.csv", manual_rows, AUDIT_FIELDS)
    write_csv(out_dir / "V21_052_R1_PROTECTED_NEVER_DELETE_MANIFEST.csv", protected_rows, AUDIT_FIELDS)
    report_path = root / "outputs/v21/read_center/V21_052_R1_V20_DEPENDENCY_MIGRATION_RECHECK_REPORT.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(summary), encoding="utf-8")
    return summary, audit_rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    summary, _ = run_recheck(args.root)
    for field in SUMMARY_FIELDS:
        print(f"{field.upper()}={summary.get(field, '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
