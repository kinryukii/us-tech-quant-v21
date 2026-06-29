#!/usr/bin/env python
"""V21.054-R1 post-migration source isolation recheck."""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.054-R1_POST_MIGRATION_SOURCE_ISOLATION_RECHECK"

PASS_STATUS = "PASS_V21_054_R1_POST_MIGRATION_SOURCE_ISOLATION_CONFIRMED"
PARTIAL_STATUS = "PARTIAL_PASS_V21_054_R1_SOURCE_ISOLATION_CONFIRMED_HISTORICAL_REFERENCES_REMAIN"
BLOCKED_ACTIVE = "BLOCKED_V21_054_R1_ACTIVE_V20_DEPENDENCY_REMAINS"
BLOCKED_STALE = "BLOCKED_V21_054_R1_ACTIVE_STALE_DOWNSTREAM_DEPENDENCY_REMAINS"
BLOCKED_TARGET = "BLOCKED_V21_054_R1_SHARED_TARGET_VALIDATION_FAILED"
BLOCKED_INPUT = "BLOCKED_V21_054_R1_SOURCE_INPUT_MISSING_OR_INVALID"
BLOCKED_FILE_MUTATION = "BLOCKED_V21_054_R1_FILE_MUTATION_DETECTED"
BLOCKED_V20 = "BLOCKED_V21_054_R1_V20_OUTPUT_MUTATION_DETECTED"
BLOCKED_V21 = "BLOCKED_V21_054_R1_V21_CURRENT_OUTPUT_MUTATION_DETECTED"
BLOCKED_PROTECTED = "BLOCKED_V21_054_R1_PROTECTED_OUTPUT_MUTATION_DETECTED"
BLOCKED_PERMISSION = "BLOCKED_V21_054_R1_OFFICIAL_PERMISSION_VIOLATION"

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "source_v21_053_r2_status",
    "source_shared_migration_committed", "copied_file_count_from_r2",
    "copied_file_count_validated", "copied_file_hash_mismatch_count",
    "missing_copied_target_count", "v21_active_current_reads_v20_scripts",
    "v21_active_current_reads_v20_outputs",
    "v21_active_current_reads_v20_8_to_v20_16_stale_downstream",
    "true_v20_script_dependency_count", "true_v20_output_dependency_count",
    "active_stale_downstream_dependency_count", "harmless_historical_v20_reference_count",
    "shared_target_validation_pass", "source_isolation_pass",
    "ready_for_v20_archive_dry_run", "ready_for_v20_delete_candidate_dry_run",
    "files_deleted_or_moved", "files_archived", "files_copied", "source_files_mutated",
    "v20_outputs_mutated", "v21_current_outputs_mutated", "protected_outputs_mutated",
    "protected_output_mutation_count", "deletion_allowed", "archive_allowed",
    "migration_allowed", "official_activation_allowed", "official_recommendation_allowed",
    "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
    "broker_execution_allowed", "trade_action_allowed", "research_only",
    "recommended_next_stage", "created_at_utc",
]

DEPENDENCY_FIELDS = ["file_path", "reference_type", "classification", "reference", "reason"]
TARGET_FIELDS = ["target_path", "source_path", "expected_hash", "actual_hash", "exists", "hash_match", "status"]
ARCHIVE_FIELDS = ["item", "status", "reason"]

PROTECTED_RE = re.compile(
    r"(authoritative.*official.*rank|official.*weight|official.*recommend|"
    r"broker|trade[_ .-]*action|real[_ .-]*book)", re.I
)
TEXT_SUFFIXES = {".py", ".ps1", ".csv", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini"}
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
    return "V21_054_R1" not in path.name and bool(PROTECTED_RE.search(path.name))


def v20_output_matcher(path: Path) -> bool:
    return "staging" not in {part.lower() for part in path.parts}


def v21_current_matcher(path: Path) -> bool:
    return "V21_054_R1" not in path.name and any(
        token in path.name for token in ("V21_048", "V21_049", "V21_050", "V21_051", "V21_052", "V21_053")
    )


def source_matcher(path: Path) -> bool:
    return "V21_054_R1" not in path.name and path.suffix.lower() in ACTIVE_SUFFIXES


def corrected_stale_stage_reference(text: str) -> bool:
    normalized = text.replace("\\", "/")
    return bool(re.search(r"(?i)(?:^|[^0-9A-Za-z])(?:V20[._](?:8|9|10|11|12|13|14|15|16)|v20_(?:8|9|10|11|12|13|14|15|16))(?!\d)", normalized))


def active_current_source_file(path: Path, root: Path) -> bool:
    rel_path = rel(root, path)
    name = path.name.lower()
    if path.suffix.lower() not in ACTIVE_SUFFIXES or name.startswith("test_"):
        return False
    if name.startswith("v21_047") or name.startswith(("v21_050", "v21_051", "v21_052", "v21_053", "v21_054")):
        return False
    inactive_tokens = ("audit", "plan", "dry_run", "discovery", "ablation", "historical", "forensic", "review")
    if any(token in name for token in inactive_tokens):
        return False
    return rel_path.startswith(("scripts/v21/", "scripts/shared/", "scripts/v21/common/", "configs/"))


def validate_r2(summary: dict[str, str]) -> bool:
    return (
        clean(summary.get("final_status")) == "PASS_V21_053_R2_SHARED_DEPENDENCY_MIGRATION_COMMITTED"
        and clean(summary.get("copy_failure_count")) in {"", "0"}
        and clean(summary.get("v20_outputs_mutated")).upper() == "FALSE"
        and clean(summary.get("v21_current_outputs_mutated")).upper() == "FALSE"
        and clean(summary.get("protected_outputs_mutated")).upper() == "FALSE"
        and clean(summary.get("post_migration_v21_reads_v20_scripts")).upper() == "FALSE"
        and clean(summary.get("post_migration_v21_reads_v20_outputs_as_current_source")).upper() == "FALSE"
        and clean(summary.get("post_migration_shared_dependency_ok")).upper() == "TRUE"
    )


def validate_targets(root: Path, manifest_rows: list[dict[str, str]]) -> tuple[list[dict[str, object]], int, int, int]:
    rows: list[dict[str, object]] = []
    validated = 0
    missing = 0
    mismatch = 0
    for row in manifest_rows:
        target_rel = clean(row.get("target_path"))
        target = root / target_rel
        expected = clean(row.get("target_hash"))
        exists = target.exists()
        actual = file_hash(target) if exists else ""
        match = exists and actual == expected
        if not exists:
            missing += 1
        elif not match:
            mismatch += 1
        else:
            validated += 1
        rows.append({
            "target_path": target_rel,
            "source_path": clean(row.get("source_path")),
            "expected_hash": expected,
            "actual_hash": actual,
            "exists": tf(exists),
            "hash_match": tf(match),
            "status": "PASS" if match else "MISSING" if not exists else "HASH_MISMATCH",
        })
    return rows, validated, mismatch, missing


def scan_references(root: Path) -> tuple[list[dict[str, object]], list[dict[str, object]], int, int, int]:
    active_rows: list[dict[str, object]] = []
    historical_rows: list[dict[str, object]] = []
    script_count = 0
    output_count = 0
    stale_count = 0
    bases = [root / "scripts/v21", root / "scripts/shared", root / "scripts/v21/common", root / "configs", root / "outputs/v21"]
    for base in bases:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            refs = []
            if "scripts/v20/" in text or "scripts\\v20\\" in text:
                refs.append(("V20_SCRIPT", "scripts/v20"))
            if "outputs/v20/" in text or "outputs\\v20\\" in text:
                refs.append(("V20_OUTPUT", "outputs/v20"))
            if not refs:
                continue
            rpath = rel(root, path)
            active = active_current_source_file(path, root)
            stale = corrected_stale_stage_reference(text)
            for ref_type, ref in refs:
                if active:
                    classification = "ACTIVE_CURRENT_V20_SCRIPT_DEPENDENCY" if ref_type == "V20_SCRIPT" else "ACTIVE_CURRENT_V20_OUTPUT_DEPENDENCY"
                    active_rows.append({"file_path": rpath, "reference_type": ref_type, "classification": classification, "reference": ref, "reason": "Active current source contains V20 reference."})
                    if ref_type == "V20_SCRIPT":
                        script_count += 1
                    else:
                        output_count += 1
                else:
                    classification = "CLOSEOUT_OR_ARCHIVE_REFERENCE" if "closeout" in rpath.lower() or "archive" in rpath.lower() else "HARMLESS_HISTORICAL_REFERENCE"
                    historical_rows.append({"file_path": rpath, "reference_type": ref_type, "classification": classification, "reference": ref, "reason": "Historical/report/audit reference, not active current source."})
            if active and stale:
                active_rows.append({"file_path": rpath, "reference_type": "V20_STALE_DOWNSTREAM", "classification": "ACTIVE_STALE_DOWNSTREAM_DEPENDENCY", "reference": "V20.8-V20.16", "reason": "Active current source contains exact stale downstream stage token."})
                stale_count += 1
    return active_rows, historical_rows, script_count, output_count, stale_count


def render_report(summary: dict[str, object]) -> str:
    return f"""# V21.054-R1 Post-Migration Source Isolation Recheck

- final_status: {summary['final_status']}
- decision: {summary['decision']}
- shared_target_validation_pass: {summary['shared_target_validation_pass']}
- source_isolation_pass: {summary['source_isolation_pass']}
- ready_for_v20_archive_dry_run: {summary['ready_for_v20_archive_dry_run']}
- ready_for_v20_delete_candidate_dry_run: {summary['ready_for_v20_delete_candidate_dry_run']}
- recommended_next_stage: {summary['recommended_next_stage']}

This stage is recheck-only. It did not delete, move, archive, copy, or rewrite
files.
"""


def run_recheck(root: Path, protected_mutation_hook: Callable[[], None] | None = None) -> tuple[dict[str, object], list[dict[str, object]]]:
    root = root.resolve()
    out_dir = root / "outputs/v21/migration"
    r2_summary = read_first(out_dir / "V21_053_R2_SHARED_DEPENDENCY_MIGRATION_COMMIT_SUMMARY.csv")
    hash_rows, _ = read_csv(out_dir / "V21_053_R2_TARGET_HASH_MANIFEST.csv")
    inputs_valid = validate_r2(r2_summary) and bool(hash_rows)
    before_files = {rel(root, p) for p in root.rglob("*") if p.is_file()}
    before_sources = snapshot(root, root / "scripts", source_matcher)
    before_v20 = snapshot(root, root / "outputs/v20", v20_output_matcher)
    before_v21 = snapshot(root, root / "outputs/v21", v21_current_matcher)
    before_protected = snapshot(root, root / "outputs", protected_matcher)

    target_audit, validated, mismatch, missing = validate_targets(root, hash_rows)
    active_rows, historical_rows, script_count, output_count, stale_count = scan_references(root)
    if protected_mutation_hook:
        protected_mutation_hook()

    after_files = {rel(root, p) for p in root.rglob("*") if p.is_file()}
    deleted_or_moved = bool(before_files - after_files)
    new_files = after_files - before_files
    source_changes = changed(before_sources, snapshot(root, root / "scripts", source_matcher))
    v20_changes = changed(before_v20, snapshot(root, root / "outputs/v20", v20_output_matcher))
    v21_changes = changed(before_v21, snapshot(root, root / "outputs/v21", v21_current_matcher))
    protected_changes = changed(before_protected, snapshot(root, root / "outputs", protected_matcher))
    allowed_new = {
        "outputs/v21/migration/V21_054_R1_POST_MIGRATION_SOURCE_ISOLATION_RECHECK_SUMMARY.csv",
        "outputs/v21/migration/V21_054_R1_ACTIVE_SOURCE_DEPENDENCY_AUDIT.csv",
        "outputs/v21/migration/V21_054_R1_HARMLESS_HISTORICAL_V20_REFERENCES.csv",
        "outputs/v21/migration/V21_054_R1_SHARED_TARGET_VALIDATION_AUDIT.csv",
        "outputs/v21/migration/V21_054_R1_V20_ARCHIVE_READINESS_AUDIT.csv",
        "outputs/v21/read_center/V21_054_R1_POST_MIGRATION_SOURCE_ISOLATION_RECHECK_REPORT.md",
    }
    unexpected_new_files = new_files - allowed_new
    target_pass = missing == 0 and mismatch == 0 and bool(hash_rows)
    isolation_pass = script_count == 0 and output_count == 0 and stale_count == 0
    ready_archive = inputs_valid and target_pass and isolation_pass

    if not inputs_valid:
        final_status = BLOCKED_INPUT
        decision = "BLOCK_SOURCE_INPUT_MISSING_OR_INVALID"
        recommended = "V21.054-R1_INPUT_REPAIR"
    elif not target_pass:
        final_status = BLOCKED_TARGET
        decision = "BLOCK_SHARED_TARGET_VALIDATION_FAILED"
        recommended = "V21.053-R2_SHARED_DEPENDENCY_MIGRATION_COMMIT_REPAIR"
    elif stale_count:
        final_status = BLOCKED_STALE
        decision = "BLOCK_ACTIVE_STALE_DOWNSTREAM_DEPENDENCY_REMAINS"
        recommended = "V21.054-R2_ACTIVE_STALE_DEPENDENCY_REPAIR"
    elif script_count or output_count:
        final_status = BLOCKED_ACTIVE
        decision = "BLOCK_ACTIVE_V20_DEPENDENCY_REMAINS"
        recommended = "V21.054-R2_ACTIVE_V20_DEPENDENCY_REPAIR"
    else:
        final_status = PARTIAL_STATUS if historical_rows else PASS_STATUS
        decision = "SOURCE_ISOLATION_CONFIRMED_HISTORICAL_REFERENCES_REMAIN" if historical_rows else "POST_MIGRATION_SOURCE_ISOLATION_CONFIRMED"
        recommended = "V20_ARCHIVE_DRY_RUN"
    if deleted_or_moved or unexpected_new_files or source_changes:
        final_status = BLOCKED_FILE_MUTATION
        decision = "BLOCK_FILE_MUTATION_DETECTED"
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

    archive_rows = [
        {"item": "source_isolation", "status": tf(isolation_pass), "reason": "No active V20 script/output/stale downstream dependencies remain."},
        {"item": "v20_archive_dry_run", "status": tf(ready_archive), "reason": "Archive dry-run is allowed after source isolation pass."},
        {"item": "v20_delete_candidate_dry_run", "status": "FALSE", "reason": "Delete candidate dry-run waits until after archive dry-run."},
    ]
    summary: dict[str, object] = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "source_v21_053_r2_status": clean(r2_summary.get("final_status")) or "NOT_AVAILABLE",
        "source_shared_migration_committed": tf(clean(r2_summary.get("final_status")) == "PASS_V21_053_R2_SHARED_DEPENDENCY_MIGRATION_COMMITTED"),
        "copied_file_count_from_r2": clean(r2_summary.get("copied_file_count")) or "0",
        "copied_file_count_validated": validated,
        "copied_file_hash_mismatch_count": mismatch,
        "missing_copied_target_count": missing,
        "v21_active_current_reads_v20_scripts": tf(script_count > 0),
        "v21_active_current_reads_v20_outputs": tf(output_count > 0),
        "v21_active_current_reads_v20_8_to_v20_16_stale_downstream": tf(stale_count > 0),
        "true_v20_script_dependency_count": script_count,
        "true_v20_output_dependency_count": output_count,
        "active_stale_downstream_dependency_count": stale_count,
        "harmless_historical_v20_reference_count": len(historical_rows),
        "shared_target_validation_pass": tf(target_pass),
        "source_isolation_pass": tf(isolation_pass),
        "ready_for_v20_archive_dry_run": tf(ready_archive),
        "ready_for_v20_delete_candidate_dry_run": "FALSE",
        "files_deleted_or_moved": tf(deleted_or_moved),
        "files_archived": "FALSE",
        "files_copied": tf(bool(unexpected_new_files)),
        "source_files_mutated": tf(bool(source_changes)),
        "v20_outputs_mutated": tf(bool(v20_changes)),
        "v21_current_outputs_mutated": tf(bool(v21_changes)),
        "protected_outputs_mutated": tf(bool(protected_changes)),
        "protected_output_mutation_count": len(protected_changes),
        "deletion_allowed": "FALSE",
        "archive_allowed": "FALSE",
        "migration_allowed": "FALSE",
        **perms,
        "research_only": "TRUE",
        "recommended_next_stage": recommended,
        "created_at_utc": utc_now(),
    }
    write_csv(out_dir / "V21_054_R1_POST_MIGRATION_SOURCE_ISOLATION_RECHECK_SUMMARY.csv", [summary], SUMMARY_FIELDS)
    write_csv(out_dir / "V21_054_R1_ACTIVE_SOURCE_DEPENDENCY_AUDIT.csv", active_rows or [{"file_path": "", "reference_type": "", "classification": "PASS", "reference": "", "reason": "No active V20 dependency."}], DEPENDENCY_FIELDS)
    write_csv(out_dir / "V21_054_R1_HARMLESS_HISTORICAL_V20_REFERENCES.csv", historical_rows, DEPENDENCY_FIELDS)
    write_csv(out_dir / "V21_054_R1_SHARED_TARGET_VALIDATION_AUDIT.csv", target_audit, TARGET_FIELDS)
    write_csv(out_dir / "V21_054_R1_V20_ARCHIVE_READINESS_AUDIT.csv", archive_rows, ARCHIVE_FIELDS)
    report_path = root / "outputs/v21/read_center/V21_054_R1_POST_MIGRATION_SOURCE_ISOLATION_RECHECK_REPORT.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(summary), encoding="utf-8")
    return summary, active_rows


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
