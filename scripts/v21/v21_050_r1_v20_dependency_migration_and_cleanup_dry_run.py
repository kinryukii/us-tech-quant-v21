#!/usr/bin/env python
"""V21.050-R1 V20 dependency migration and cleanup dry run.

Dry-run only: scans V21 references to V20/shared assets, classifies migration,
archive, delete-candidate, and never-delete files, and writes manifests without
moving or deleting anything.
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
STAGE = "V21.050-R1_V20_DEPENDENCY_MIGRATION_AND_CLEANUP_DRY_RUN"

PASS_STATUS = "PASS_V21_050_R1_V20_DEPENDENCY_CLEANUP_DRY_RUN_READY"
PARTIAL_SHARED = "PARTIAL_PASS_V21_050_R1_SHARED_INFRASTRUCTURE_DEPENDENCY_ONLY"
PARTIAL_MIGRATION = "PARTIAL_PASS_V21_050_R1_V20_DEPENDENCY_FOUND_MIGRATION_PLAN_READY"
BLOCKED_STALE = "BLOCKED_V21_050_R1_V20_STALE_DOWNSTREAM_DEPENDENCY_FOUND"
BLOCKED_INPUT = "BLOCKED_V21_050_R1_REQUIRED_INPUT_MISSING_OR_INVALID"
BLOCKED_PROTECTED = "BLOCKED_V21_050_R1_PROTECTED_OUTPUT_MUTATION_DETECTED"
BLOCKED_PERMISSION = "BLOCKED_V21_050_R1_OFFICIAL_PERMISSION_VIOLATION"

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "v20_closeout_status",
    "v21_current_chain_status", "v21_reads_v20_outputs",
    "v21_reads_v20_scripts", "v21_reads_v20_8_to_v20_16_stale_downstream",
    "v20_legacy_downstream_dependency_found", "shared_data_dependency_found",
    "migration_candidate_count", "archive_candidate_count",
    "delete_candidate_count", "protected_never_delete_count",
    "unsafe_delete_candidate_count", "estimated_archive_size_mb",
    "estimated_delete_candidate_size_mb", "cleanup_dry_run_only",
    "deletion_allowed", "migration_allowed", "archive_allowed",
    "official_activation_allowed", "official_recommendation_allowed",
    "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
    "broker_execution_allowed", "trade_action_allowed", "research_only",
    "recommended_next_stage", "created_at_utc",
]

AUDIT_FIELDS = [
    "file_path", "file_type", "size_mb", "last_modified", "referenced_by_v21",
    "reference_type", "dependency_risk", "stale_lineage_risk",
    "classification", "proposed_action", "proposed_destination", "reason",
]

TEXT_SUFFIXES = {".py", ".ps1", ".csv", ".md", ".txt", ".json", ".yaml", ".yml"}
V20_OUTPUT_RE = re.compile(r"(?:outputs[\\/]+v20[\\/][A-Za-z0-9_ .\\/\\-]+)")
V20_SCRIPT_RE = re.compile(r"(?:scripts[\\/]+v20[\\/][A-Za-z0-9_ .\\/\\-]+)")
STALE_V20_8_16_RE = re.compile(r"V20_(?:8|9|10|11|12|13|14|15|16)(?:_|\\.)", re.I)
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


def snapshot(root: Path, matcher: Callable[[Path], bool]) -> dict[str, str]:
    base = root / "outputs"
    if not base.exists():
        return {}
    return {
        rel(root, path): file_hash(path)
        for path in base.rglob("*") if path.is_file() and matcher(path)
    }


def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


def protected_matcher(path: Path) -> bool:
    return "V21_050_R1" not in path.name and bool(PROTECTED_RE.search(path.name))


def text_files(root: Path, base: Path) -> list[Path]:
    if not base.exists():
        return []
    return [path for path in base.rglob("*") if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES]


def normalize_ref(ref_text: str) -> str:
    return ref_text.replace("\\", "/").strip(" ,;:'\")(")


def collect_v21_references(root: Path) -> tuple[dict[str, set[str]], dict[str, set[str]], bool]:
    output_refs: dict[str, set[str]] = {}
    script_refs: dict[str, set[str]] = {}
    shared_found = False
    for base in (root / "scripts/v21", root / "outputs/v21"):
        for path in text_files(root, base):
            rpath = rel(root, path)
            if rpath.startswith("outputs/v21/migration/") or "V21_050_R1_" in path.name:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            source = rpath
            if SHARED_RE.search(text):
                shared_found = True
            for match in V20_OUTPUT_RE.findall(text):
                ref = normalize_ref(match)
                output_refs.setdefault(ref, set()).add(source)
            for match in V20_SCRIPT_RE.findall(text):
                ref = normalize_ref(match)
                script_refs.setdefault(ref, set()).add(source)
            # Imports such as "from scripts.v20..." do not include slashes.
            if "scripts.v20" in text:
                script_refs.setdefault("scripts/v20/*", set()).add(source)
    return output_refs, script_refs, shared_found


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


def classify_file(root: Path, path: Path, output_refs: dict[str, set[str]], script_refs: dict[str, set[str]]) -> dict[str, object]:
    r = rel(root, path)
    r_back = r.replace("/", "\\")
    ref_sources = set(output_refs.get(r, set())) | set(output_refs.get(r_back, set()))
    script_sources = set(script_refs.get(r, set())) | set(script_refs.get(r_back, set()))
    referenced = bool(ref_sources or script_sources)
    reference_type = "NONE"
    if ref_sources:
        reference_type = "V20_OUTPUT"
    if script_sources:
        reference_type = "V20_SCRIPT" if reference_type == "NONE" else reference_type + "|V20_SCRIPT"

    protected = bool(PROTECTED_RE.search(r))
    raw_or_shared = r.startswith("data/") or bool(SHARED_RE.search(r))
    v21_current = r.startswith("outputs/v21/") and ("V21_048" in path.name or "V21_049" in path.name)
    v20_r4_closeout = "V20_16_R4_LEGACY_DOWNSTREAM_STALE_LINEAGE_CLOSEOUT" in path.name
    v20_output = r.startswith("outputs/v20/")
    v20_script = r.startswith("scripts/v20/")
    staging_or_temp = "/staging/" in r or "/tmp/" in r or path.name.endswith(".tmp")
    stale_downstream = v20_output and bool(STALE_V20_8_16_RE.search(path.name))

    if protected:
        classification = "NEVER_DELETE_PROTECTED_OFFICIAL"
        action = "KEEP"
        dest = ""
        reason = "Official/protected pattern detected."
        risk = "CRITICAL"
    elif raw_or_shared:
        classification = "NEVER_DELETE_RAW_DATA" if r.startswith("data/") else "KEEP_SHARED_DATA"
        action = "KEEP"
        dest = ""
        reason = "Shared/raw price/universe dependency."
        risk = "LOW"
    elif v21_current:
        classification = "KEEP_CURRENT_V21"
        action = "KEEP"
        dest = ""
        reason = "Current V21.048/V21.049 output."
        risk = "LOW"
    elif v20_r4_closeout:
        classification = "ARCHIVE_V20_LEGACY"
        action = "ARCHIVE"
        dest = "archive/v20/closeout/"
        reason = "V20 closeout report/diagnostic retained as legacy record."
        risk = "LOW"
    elif staging_or_temp:
        classification = "DELETE_CANDIDATE_TEMP_OR_STAGING"
        action = "DRY_RUN_DELETE_CANDIDATE_ONLY"
        dest = ""
        reason = "Staging or temporary artifact; deletion not performed in this dry run."
        risk = "LOW"
    elif referenced and stale_downstream:
        classification = "MANUAL_REVIEW_REQUIRED"
        action = "REMOVE_STALE_DEPENDENCY_BEFORE_MIGRATION"
        dest = ""
        reason = "V21 references stale V20.8-V20.16 downstream output."
        risk = "HIGH"
    elif referenced and v20_output:
        classification = "MIGRATE_TO_V21"
        action = "MIGRATE_DRY_RUN_ONLY"
        dest = "outputs/v21/migrated_v20_dependencies/"
        reason = "V21 references this V20 output."
        risk = "MEDIUM"
    elif referenced and v20_script:
        classification = "MIGRATE_TO_SHARED_HELPER"
        action = "MIGRATE_DRY_RUN_ONLY"
        dest = "scripts/shared/"
        reason = "V21 references V20 script/helper."
        risk = "MEDIUM"
    elif v20_output and stale_downstream:
        classification = "ARCHIVE_V20_LEGACY"
        action = "ARCHIVE_DRY_RUN_ONLY"
        dest = "archive/v20/legacy_downstream/"
        reason = "V20.8-V20.16 production output is stale legacy lineage."
        risk = "MEDIUM"
    elif v20_output or v20_script:
        classification = "ARCHIVE_V20_LEGACY"
        action = "ARCHIVE_DRY_RUN_ONLY"
        dest = "archive/v20/"
        reason = "V20 legacy artifact not directly referenced by current V21 scan."
        risk = "LOW"
    else:
        classification = "MANUAL_REVIEW_REQUIRED"
        action = "REVIEW"
        dest = ""
        reason = "Unclassified scanned file."
        risk = "MEDIUM"

    return {
        "file_path": r,
        "file_type": file_type(path),
        "size_mb": f"{size_mb(path):.6f}",
        "last_modified": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat(),
        "referenced_by_v21": "|".join(sorted(ref_sources | script_sources)),
        "reference_type": reference_type,
        "dependency_risk": risk,
        "stale_lineage_risk": "HIGH" if stale_downstream and referenced else "MEDIUM" if stale_downstream else "LOW",
        "classification": classification,
        "proposed_action": action,
        "proposed_destination": dest,
        "reason": reason,
    }


def scanned_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for base in (root / "outputs/v20", root / "scripts/v20", root / "data", root / "outputs/v21/context"):
        if base.exists():
            paths.extend(path for path in base.rglob("*") if path.is_file())
    return sorted(set(paths), key=lambda p: rel(root, p))


def rows_for_manifest(rows: list[dict[str, object]], classes: set[str]) -> list[dict[str, object]]:
    return [row for row in rows if clean(row.get("classification")) in classes]


def render_report(summary: dict[str, object]) -> str:
    return f"""# V21.050-R1 V20 Dependency Migration And Cleanup Dry Run

- final_status: {summary['final_status']}
- decision: {summary['decision']}
- v21_reads_v20_outputs: {summary['v21_reads_v20_outputs']}
- v21_reads_v20_scripts: {summary['v21_reads_v20_scripts']}
- v21_reads_v20_8_to_v20_16_stale_downstream: {summary['v21_reads_v20_8_to_v20_16_stale_downstream']}
- migration_candidate_count: {summary['migration_candidate_count']}
- archive_candidate_count: {summary['archive_candidate_count']}
- delete_candidate_count: {summary['delete_candidate_count']}
- protected_never_delete_count: {summary['protected_never_delete_count']}
- cleanup_dry_run_only: TRUE
- deletion_allowed: FALSE
- migration_allowed: FALSE
- archive_allowed: FALSE
- recommended_next_stage: {summary['recommended_next_stage']}

No files were deleted, moved, archived, or migrated. Official, broker, and trade
permissions remain FALSE.
"""


def run_dry_run(
    root: Path,
    protected_mutation_hook: Callable[[], None] | None = None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    root = root.resolve()
    migration_dir = root / "outputs/v21/migration"
    v20_r4 = read_first(root / "outputs/v20/diagnostics/V20_16_R4_LEGACY_DOWNSTREAM_STALE_LINEAGE_CLOSEOUT_SUMMARY.csv")
    v21_048 = read_first(root / "outputs/v21/context/V21_048_R1_CONTEXT_SELECTIVITY_AUDIT_SUMMARY.csv")
    v21_049 = read_first(root / "outputs/v21/context/V21_049_R1_REPAIRED_CONTEXT_MATURITY_EVALUATION_SUMMARY.csv")

    before_protected = snapshot(root, protected_matcher)
    output_refs, script_refs, shared_found = collect_v21_references(root)
    audit_rows = [classify_file(root, path, output_refs, script_refs) for path in scanned_files(root)]

    if protected_mutation_hook:
        protected_mutation_hook()

    stale_refs = [row for row in audit_rows if clean(row["stale_lineage_risk"]) == "HIGH"]
    migration_rows = rows_for_manifest(audit_rows, {"MIGRATE_TO_V21", "MIGRATE_TO_SHARED_HELPER"})
    archive_rows = rows_for_manifest(audit_rows, {"ARCHIVE_V20_LEGACY"})
    delete_rows = rows_for_manifest(audit_rows, {"DELETE_CANDIDATE_TEMP_OR_STAGING", "DELETE_CANDIDATE_DUPLICATE_ARTIFACT"})
    protected_rows = rows_for_manifest(audit_rows, {"NEVER_DELETE_RAW_DATA", "NEVER_DELETE_PROTECTED_OFFICIAL", "KEEP_CURRENT_V21"})
    unsafe_delete_count = sum(1 for row in delete_rows if clean(row.get("classification")).startswith("NEVER_DELETE"))

    v21_reads_v20_outputs = bool(output_refs)
    v21_reads_v20_scripts = bool(script_refs)
    v21_reads_stale = bool(stale_refs)
    v20_dependency_found = bool(migration_rows)

    inputs_valid = bool(v20_r4) and bool(v21_048) and bool(v21_049)
    if not inputs_valid:
        final_status = BLOCKED_INPUT
        decision = "BLOCK_REQUIRED_INPUT_MISSING_OR_INVALID"
        recommended = "V21.050-R1_INPUT_REPAIR"
    elif v21_reads_stale:
        final_status = BLOCKED_STALE
        decision = "BLOCK_V21_READS_V20_STALE_DOWNSTREAM_DEPENDENCY"
        recommended = "V21_051_R1_REMOVE_V20_STALE_DOWNSTREAM_DEPENDENCY"
    elif v20_dependency_found:
        final_status = PARTIAL_MIGRATION
        decision = "V20_DEPENDENCY_FOUND_MIGRATION_PLAN_READY"
        recommended = "V21.051-R1_MIGRATE_SHARED_DEPENDENCIES_TO_V21"
    elif shared_found:
        final_status = PARTIAL_SHARED
        decision = "SHARED_INFRASTRUCTURE_DEPENDENCY_ONLY"
        recommended = "V20_ARCHIVE_DRY_RUN"
    else:
        final_status = PASS_STATUS
        decision = "V20_CLEANUP_DRY_RUN_READY"
        recommended = "V20_ARCHIVE_DRY_RUN"

    protected_changes = changed(before_protected, snapshot(root, protected_matcher))
    if protected_changes:
        final_status = BLOCKED_PROTECTED
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
        "v20_closeout_status": clean(v20_r4.get("final_status")) or "NOT_AVAILABLE",
        "v21_current_chain_status": clean(v21_049.get("final_status")) or clean(v21_048.get("final_status")) or "NOT_AVAILABLE",
        "v21_reads_v20_outputs": tf(v21_reads_v20_outputs),
        "v21_reads_v20_scripts": tf(v21_reads_v20_scripts),
        "v21_reads_v20_8_to_v20_16_stale_downstream": tf(v21_reads_stale),
        "v20_legacy_downstream_dependency_found": tf(v21_reads_stale),
        "shared_data_dependency_found": tf(shared_found),
        "migration_candidate_count": len(migration_rows),
        "archive_candidate_count": len(archive_rows),
        "delete_candidate_count": len(delete_rows),
        "protected_never_delete_count": len(protected_rows),
        "unsafe_delete_candidate_count": unsafe_delete_count,
        "estimated_archive_size_mb": f"{sum(float(row['size_mb']) for row in archive_rows):.6f}",
        "estimated_delete_candidate_size_mb": f"{sum(float(row['size_mb']) for row in delete_rows):.6f}",
        "cleanup_dry_run_only": "TRUE",
        "deletion_allowed": "FALSE",
        "migration_allowed": "FALSE",
        "archive_allowed": "FALSE",
        **perms,
        "research_only": "TRUE",
        "recommended_next_stage": recommended,
        "created_at_utc": utc_now(),
    }

    write_csv(migration_dir / "V21_050_R1_V20_DEPENDENCY_MIGRATION_AND_CLEANUP_DRY_RUN_SUMMARY.csv", [summary], SUMMARY_FIELDS)
    write_csv(migration_dir / "V21_050_R1_V20_DEPENDENCY_AUDIT_BY_FILE.csv", audit_rows, AUDIT_FIELDS)
    write_csv(migration_dir / "V21_050_R1_V20_TO_V21_MIGRATION_CANDIDATES.csv", migration_rows, AUDIT_FIELDS)
    write_csv(migration_dir / "V21_050_R1_V20_ARCHIVE_CANDIDATES.csv", archive_rows, AUDIT_FIELDS)
    write_csv(migration_dir / "V21_050_R1_V20_DELETE_CANDIDATES_DRY_RUN.csv", delete_rows, AUDIT_FIELDS)
    write_csv(migration_dir / "V21_050_R1_PROTECTED_AND_NEVER_DELETE_MANIFEST.csv", protected_rows, AUDIT_FIELDS)
    report_path = root / "outputs/v21/read_center/V21_050_R1_V20_DEPENDENCY_MIGRATION_AND_CLEANUP_DRY_RUN_REPORT.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(summary), encoding="utf-8")
    return summary, audit_rows


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
