#!/usr/bin/env python
"""V20 legacy archive planning stage.

This module is deliberately non-operational: it inventories and classifies
files, but never copies, moves, deletes, or archives them.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V20_ARCHIVE_DRY_RUN"

PASS_STATUS = "PASS_V20_ARCHIVE_DRY_RUN_READY"
PARTIAL_KEEP = "PARTIAL_PASS_V20_ARCHIVE_DRY_RUN_READY_WITH_KEEP_REFERENCES"
PARTIAL_REVIEW = "PARTIAL_PASS_V20_ARCHIVE_DRY_RUN_READY_WITH_MANUAL_REVIEW"
BLOCKED_ACTIVE = "BLOCKED_V20_ARCHIVE_DRY_RUN_ACTIVE_V21_DEPENDENCY_FOUND"
BLOCKED_INPUT = "BLOCKED_V20_ARCHIVE_DRY_RUN_SOURCE_INPUT_MISSING_OR_INVALID"
BLOCKED_UNSAFE = "BLOCKED_V20_ARCHIVE_DRY_RUN_UNSAFE_ARCHIVE_CANDIDATES"
BLOCKED_FILE = "BLOCKED_V20_ARCHIVE_DRY_RUN_FILE_MUTATION_DETECTED"
BLOCKED_V20 = "BLOCKED_V20_ARCHIVE_DRY_RUN_V20_OUTPUT_MUTATION_DETECTED"
BLOCKED_V21 = "BLOCKED_V20_ARCHIVE_DRY_RUN_V21_CURRENT_OUTPUT_MUTATION_DETECTED"
BLOCKED_PROTECTED = "BLOCKED_V20_ARCHIVE_DRY_RUN_PROTECTED_OUTPUT_MUTATION_DETECTED"
BLOCKED_PERMISSION = "BLOCKED_V20_ARCHIVE_DRY_RUN_OFFICIAL_PERMISSION_VIOLATION"

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "source_v21_054_r1_status",
    "source_isolation_pass", "v21_active_current_reads_v20_scripts",
    "v21_active_current_reads_v20_outputs",
    "v21_active_current_reads_v20_8_to_v20_16_stale_downstream",
    "harmless_historical_v20_reference_count_from_summary",
    "harmless_historical_v20_reference_count_from_audit_file",
    "harmless_historical_reference_count_reconciled", "v20_file_count_scanned",
    "archive_candidate_count", "keep_reference_count",
    "protected_never_archive_count", "future_delete_candidate_count",
    "unsafe_archive_candidate_count", "archive_package_count",
    "estimated_archive_size_mb", "estimated_future_delete_candidate_size_mb",
    "archive_dry_run_only", "archive_allowed", "deletion_allowed",
    "migration_allowed", "files_deleted_or_moved", "files_archived",
    "files_copied", "source_files_mutated", "v20_outputs_mutated",
    "v21_current_outputs_mutated", "protected_outputs_mutated",
    "protected_output_mutation_count", "ready_for_v20_archive_commit",
    "ready_for_v20_delete_candidate_dry_run", "official_activation_allowed",
    "official_recommendation_allowed", "official_ranking_mutation_allowed",
    "official_weight_mutation_allowed", "broker_execution_allowed",
    "trade_action_allowed", "research_only", "recommended_next_stage",
    "created_at_utc",
]

MANIFEST_FIELDS = [
    "file_path", "file_type", "size_mb", "last_modified", "archive_class",
    "archive_reason", "proposed_archive_package", "protected_flag",
    "active_v21_dependency_flag", "historical_reference_flag",
    "future_delete_candidate_flag", "risk_level",
]
PACKAGE_FIELDS = [
    "package_name", "package_scope", "file_count", "estimated_size_mb",
    "package_reason",
]
RISK_FIELDS = ["risk_id", "status", "severity", "file_path", "finding", "mitigation"]

SOURCE_SUMMARY = "V21_054_R1_POST_MIGRATION_SOURCE_ISOLATION_RECHECK_SUMMARY.csv"
SOURCE_ACTIVE_AUDIT = "V21_054_R1_ACTIVE_SOURCE_DEPENDENCY_AUDIT.csv"
SOURCE_HISTORY_AUDIT = "V21_054_R1_HARMLESS_HISTORICAL_V20_REFERENCES.csv"
TARGET_HASH_MANIFEST = "V21_053_R2_TARGET_HASH_MANIFEST.csv"
ROLLBACK_MANIFEST = "V21_053_R2_ROLLBACK_MANIFEST.csv"

OUTPUT_NAMES = {
    "V20_ARCHIVE_DRY_RUN_SUMMARY.csv",
    "V20_ARCHIVE_CANDIDATE_MANIFEST.csv",
    "V20_KEEP_ACTIVE_OR_REFERENCE_MANIFEST.csv",
    "V20_PROTECTED_NEVER_ARCHIVE_MANIFEST.csv",
    "V20_FUTURE_DELETE_CANDIDATE_DRY_RUN_QUEUE.csv",
    "V20_ARCHIVE_PACKAGE_PLAN.csv",
    "V20_ARCHIVE_READINESS_RISK_AUDIT.csv",
}
REPORT_NAME = "V20_ARCHIVE_DRY_RUN_REPORT.md"

PROTECTED_RE = re.compile(
    r"(authoritative.*official|official.*(?:rank|weight|recommend)|"
    r"broker|trade[_ .-]*action|real[_ .-]*book|universe|price[_ .-]*history|"
    r"raw[_ .-]*(?:price|ohlcv)|ohlcv[_ .-]*cache)", re.I
)
KEEP_RE = re.compile(
    r"(V20_16_R4|V20[._-]?7V|V20[._-]?7X|V20_200|"
    r"FINAL[_ .-]*(?:STATUS|REPORT)|CLOSEOUT|DEPRECATION)", re.I
)
STALE_RE = re.compile(r"(?:^|[^0-9])V20[._-]?(?:8|9|10|11|12|13|14|15|16)(?:[^0-9]|$)", re.I)
DELETE_RE = re.compile(
    r"(?:^|[/_.-])(?:tmp|temp|scratch|smoke[_ .-]*test|dry[_ .-]*run)(?:[/_.-]|$)|"
    r"(?:duplicate|\.tmp$|~$)", re.I
)
ACTIVE_SUFFIXES = {".py", ".ps1", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini"}


def clean(value: object) -> str:
    return str(value or "").strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def as_bool(value: object) -> bool:
    return clean(value).upper() == "TRUE"


def as_int(value: object) -> int:
    try:
        return int(clean(value))
    except ValueError:
        return 0


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


def write_csv(path: Path, rows: Iterable[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(root: Path, paths: Iterable[Path]) -> dict[str, str]:
    return {rel(root, path): file_hash(path) for path in paths if path.is_file()}


def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))


def files_under(base: Path) -> list[Path]:
    return sorted((path for path in base.rglob("*") if path.is_file()), key=lambda p: p.as_posix().lower()) if base.exists() else []


def is_stage_output(path: Path) -> bool:
    return path.name in OUTPUT_NAMES or path.name == REPORT_NAME


def is_protected_path(root: Path, path: Path) -> bool:
    rpath = rel(root, path)
    return (
        bool(PROTECTED_RE.search(rpath))
        or rpath.startswith(("data/raw/", "data/universe/", "outputs/shared/"))
        or path.name in {TARGET_HASH_MANIFEST, ROLLBACK_MANIFEST}
    )


def v21_current_files(root: Path) -> list[Path]:
    return [
        path for path in files_under(root / "outputs/v21")
        if not is_stage_output(path)
    ]


def protected_files(root: Path) -> list[Path]:
    candidates = files_under(root / "outputs") + files_under(root / "data")
    return [path for path in candidates if is_protected_path(root, path)]


def source_files(root: Path) -> list[Path]:
    return [
        path for path in files_under(root / "scripts")
        if path.suffix.lower() in ACTIVE_SUFFIXES
        and path.name not in {"v20_archive_dry_run.py", "run_v20_archive_dry_run.ps1", "test_v20_archive_dry_run.py"}
    ]


def metadata(root: Path, path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "file_path": rel(root, path),
        "file_type": "script" if rel(root, path).startswith("scripts/") else path.suffix.lower().lstrip(".") or "file",
        "size_mb": round(stat.st_size / (1024 * 1024), 6),
        "last_modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).replace(microsecond=0).isoformat(),
    }


def classify_v20_file(
    root: Path,
    path: Path,
    active_dependency_paths: set[str] | None = None,
) -> tuple[str, dict[str, object]]:
    """Return the exclusive class and manifest row for one V20 file."""
    active_dependency_paths = active_dependency_paths or set()
    row = metadata(root, path)
    rpath = clean(row["file_path"])
    name = path.name
    protected = is_protected_path(root, path)
    active = rpath in active_dependency_paths
    keep = bool(KEEP_RE.search(name))
    future_delete = bool(DELETE_RE.search(rpath))
    stale = rpath.startswith("outputs/v20/") and bool(STALE_RE.search(name))

    if protected:
        category = "protected"
        archive_class = "PROTECTED_NEVER_ARCHIVE"
        reason = "Raw/universe/price or official/broker/trade protected asset."
        package = ""
        risk = "CRITICAL"
    elif active:
        category = "unsafe"
        archive_class = "UNSAFE_ACTIVE_V21_DEPENDENCY"
        reason = "File is still identified as an active/current V21 dependency."
        package = ""
        risk = "CRITICAL"
    elif keep:
        category = "keep"
        archive_class = "KEEP_HISTORICAL_REFERENCE"
        reason = "Closeout, final status, lineage/certification, or final research evidence."
        package = ""
        risk = "LOW"
    elif future_delete:
        category = "future_delete"
        archive_class = "FUTURE_DELETE_CANDIDATE_DRY_RUN_ONLY"
        reason = "Temporary, staging, duplicate, scratch, dry-run, or smoke-test artifact."
        package = ""
        risk = "MEDIUM"
    else:
        category = "archive"
        if rpath.startswith("scripts/v20/"):
            archive_class = "LEGACY_V20_SCRIPT"
            package = "v20-legacy-scripts"
            reason = "V20 script is no longer imported or called by active/current V21."
        elif stale:
            archive_class = "V20_8_TO_V20_16_STALE_DOWNSTREAM"
            package = "v20-stale-downstream"
            reason = "V20.8-V20.16 stale downstream output is no longer used by V21."
        elif "/diagnostics/" in rpath or "DIAGNOSTIC" in name.upper() or "AUDIT" in name.upper():
            archive_class = "LEGACY_V20_DIAGNOSTIC"
            package = "v20-diagnostics"
            reason = "Legacy V20 diagnostic/audit output."
        elif "/reports/" in rpath or "/read_center/" in rpath or path.suffix.lower() == ".md":
            archive_class = "LEGACY_V20_REPORT"
            package = "v20-reports"
            reason = "Legacy V20 report not selected as required historical evidence."
        elif any(token in rpath for token in ("/repair/", "/ops/", "/evidence/", "/consolidation/")):
            archive_class = "LEGACY_V20_INTERMEDIATE"
            package = "v20-intermediate"
            reason = "Old V20 migration/intermediate artifact no longer used by V21."
        else:
            archive_class = "LEGACY_V20_OUTPUT"
            package = "v20-legacy-outputs"
            reason = "Legacy V20 output no longer used by active/current V21."
        risk = "MEDIUM" if stale else "LOW"

    row.update({
        "archive_class": archive_class,
        "archive_reason": reason,
        "proposed_archive_package": package,
        "protected_flag": tf(protected),
        "active_v21_dependency_flag": tf(active),
        "historical_reference_flag": tf(keep),
        "future_delete_candidate_flag": tf(future_delete and not protected and not keep),
        "risk_level": risk,
    })
    return category, row


def source_inputs_valid(summary: dict[str, str], active_rows: list[dict[str, str]], required_files_exist: bool) -> bool:
    if not summary or not required_files_exist:
        return False
    return (
        as_bool(summary.get("source_isolation_pass"))
        and as_bool(summary.get("ready_for_v20_archive_dry_run"))
        and not as_bool(summary.get("v21_active_current_reads_v20_scripts"))
        and not as_bool(summary.get("v21_active_current_reads_v20_outputs"))
        and not as_bool(summary.get("v21_active_current_reads_v20_8_to_v20_16_stale_downstream"))
        and not as_bool(summary.get("v20_outputs_mutated"))
        and not as_bool(summary.get("v21_current_outputs_mutated"))
        and not as_bool(summary.get("protected_outputs_mutated"))
        and not any(clean(row.get("classification")).startswith("ACTIVE_") for row in active_rows)
    )


def package_plan(archive_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    reasons = {
        "v20-legacy-scripts": "Legacy V20 source package.",
        "v20-stale-downstream": "Isolated V20.8-V20.16 downstream package.",
        "v20-diagnostics": "Legacy diagnostics and audit package.",
        "v20-reports": "Legacy report package.",
        "v20-intermediate": "Legacy migration/intermediate package.",
        "v20-legacy-outputs": "Remaining legacy V20 output package.",
    }
    result = []
    for package in sorted({clean(row["proposed_archive_package"]) for row in archive_rows if clean(row["proposed_archive_package"])}):
        members = [row for row in archive_rows if row["proposed_archive_package"] == package]
        result.append({
            "package_name": package,
            "package_scope": "|".join(sorted({clean(row["archive_class"]) for row in members})),
            "file_count": len(members),
            "estimated_size_mb": round(sum(float(row["size_mb"]) for row in members), 6),
            "package_reason": reasons.get(package, "V20 legacy archive package."),
        })
    return result


def render_report(summary: dict[str, object], count_note: str, risk_rows: list[dict[str, object]]) -> str:
    risks = "\n".join(
        f"- {row['risk_id']}: {row['status']} — {row['finding']}" for row in risk_rows
    )
    return f"""# V20 Archive Dry-Run Report

- final_status: {summary['final_status']}
- decision: {summary['decision']}
- source_isolation_pass: {summary['source_isolation_pass']}
- archive_candidate_count: {summary['archive_candidate_count']}
- keep_reference_count: {summary['keep_reference_count']}
- protected_never_archive_count: {summary['protected_never_archive_count']}
- future_delete_candidate_count: {summary['future_delete_candidate_count']}
- unsafe_archive_candidate_count: {summary['unsafe_archive_candidate_count']}
- ready_for_v20_archive_commit: {summary['ready_for_v20_archive_commit']}
- recommended_next_stage: {summary['recommended_next_stage']}

## Historical reference count reconciliation

{count_note}

## Readiness risks

{risks}

This was an archive dry-run only. No source, V20 output, V21 current output,
official/protected output, archive, deletion, move, or copy operation was
performed. All official and trading permissions remained disabled.
"""


def run_archive_dry_run(
    root: Path,
    mutation_hook: Callable[[], None] | None = None,
) -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
    root = root.resolve()
    migration = root / "outputs/v21/migration"
    read_center = root / "outputs/v21/read_center"
    summary_path = migration / SOURCE_SUMMARY
    active_path = migration / SOURCE_ACTIVE_AUDIT
    history_path = migration / SOURCE_HISTORY_AUDIT
    target_path = migration / TARGET_HASH_MANIFEST
    rollback_path = migration / ROLLBACK_MANIFEST

    source_summary = read_first(summary_path)
    active_rows, _ = read_csv(active_path)
    historical_rows, _ = read_csv(history_path)
    target_rows, _ = read_csv(target_path)
    rollback_rows, _ = read_csv(rollback_path)
    required_exist = all(path.exists() for path in (summary_path, active_path, history_path, target_path, rollback_path))
    valid_input = source_inputs_valid(source_summary, active_rows, required_exist) and bool(target_rows) and bool(rollback_rows)

    history_count_summary = as_int(source_summary.get("harmless_historical_v20_reference_count"))
    history_count_audit = sum(1 for row in historical_rows if clean(row.get("file_path")))
    history_reconciled = history_count_summary == history_count_audit
    count_note = (
        f"The persisted V21.054-R1 summary and audit both contain {history_count_audit} harmless "
        "historical references. The pasted value of 151 is superseded by the persisted evidence."
        if history_reconciled
        else f"The summary reports {history_count_summary}, while the audit contains {history_count_audit} rows. "
        "The audit row count is treated as authoritative; manual review is required."
    )

    before_files = {rel(root, path) for path in root.rglob("*") if path.is_file()}
    before_sources = snapshot(root, source_files(root))
    before_v20 = snapshot(root, files_under(root / "outputs/v20"))
    before_v21 = snapshot(root, v21_current_files(root))
    before_protected = snapshot(root, protected_files(root))

    active_dependency_paths = {
        clean(row.get("reference")).replace("\\", "/")
        for row in active_rows
        if clean(row.get("classification")).startswith("ACTIVE_")
        and clean(row.get("reference")).startswith(("outputs", "scripts"))
    }
    v20_paths = files_under(root / "scripts/v20") + files_under(root / "outputs/v20")
    classified = {"archive": [], "keep": [], "protected": [], "future_delete": [], "unsafe": []}
    for path in v20_paths:
        category, row = classify_v20_file(root, path, active_dependency_paths)
        classified[category].append(row)

    # Preserve the migration evidence and migrated targets even though they are
    # outside the V20 inventory.
    supplementary_paths = {target_path, rollback_path}
    for row in target_rows:
        target = root / clean(row.get("target_path"))
        if target.is_file():
            supplementary_paths.add(target)
    existing_protected = {clean(row["file_path"]) for row in classified["protected"]}
    for path in sorted(supplementary_paths, key=lambda p: p.as_posix().lower()):
        rpath = rel(root, path)
        if path.is_file() and rpath not in existing_protected:
            row = metadata(root, path)
            row.update({
                "archive_class": "PROTECTED_V21_MIGRATION_OR_SHARED_TARGET",
                "archive_reason": "Shared migrated target or rollback/hash evidence required by V21.053-R2.",
                "proposed_archive_package": "",
                "protected_flag": "TRUE",
                "active_v21_dependency_flag": "FALSE",
                "historical_reference_flag": "TRUE",
                "future_delete_candidate_flag": "FALSE",
                "risk_level": "CRITICAL",
            })
            classified["protected"].append(row)

    packages = package_plan(classified["archive"])
    if mutation_hook:
        mutation_hook()

    after_files = {rel(root, path) for path in root.rglob("*") if path.is_file()}
    deleted_or_moved = bool(before_files - after_files)
    unexpected_new = {
        path for path in after_files - before_files
        if Path(path).name not in OUTPUT_NAMES | {REPORT_NAME}
    }
    source_changes = changed(before_sources, snapshot(root, source_files(root)))
    v20_changes = changed(before_v20, snapshot(root, files_under(root / "outputs/v20")))
    v21_changes = changed(before_v21, snapshot(root, v21_current_files(root)))
    protected_changes = changed(before_protected, snapshot(root, protected_files(root)))

    source_isolation = (
        as_bool(source_summary.get("source_isolation_pass"))
        and not as_bool(source_summary.get("v21_active_current_reads_v20_scripts"))
        and not as_bool(source_summary.get("v21_active_current_reads_v20_outputs"))
        and not as_bool(source_summary.get("v21_active_current_reads_v20_8_to_v20_16_stale_downstream"))
    )
    unsafe_count = len(classified["unsafe"])
    manual_review = not history_reconciled
    ready_commit = valid_input and source_isolation and unsafe_count == 0 and not (
        deleted_or_moved or unexpected_new or source_changes or v20_changes or v21_changes or protected_changes
    )

    if not valid_input:
        final_status = BLOCKED_INPUT
        decision = "BLOCK_SOURCE_INPUT_MISSING_OR_INVALID"
    elif not source_isolation:
        final_status = BLOCKED_ACTIVE
        decision = "BLOCK_ACTIVE_V21_DEPENDENCY_FOUND"
    elif unsafe_count:
        final_status = BLOCKED_UNSAFE
        decision = "BLOCK_UNSAFE_ARCHIVE_CANDIDATES"
    elif manual_review:
        final_status = PARTIAL_REVIEW
        decision = "ARCHIVE_DRY_RUN_READY_WITH_MANUAL_REVIEW"
    elif classified["keep"]:
        final_status = PARTIAL_KEEP
        decision = "ARCHIVE_DRY_RUN_READY_WITH_KEEP_REFERENCES"
    else:
        final_status = PASS_STATUS
        decision = "ARCHIVE_DRY_RUN_READY"

    if deleted_or_moved or unexpected_new or source_changes:
        final_status = BLOCKED_FILE
        decision = "BLOCK_FILE_MUTATION_DETECTED"
        ready_commit = False
    if v20_changes:
        final_status = BLOCKED_V20
        decision = "BLOCK_V20_OUTPUT_MUTATION_DETECTED"
        ready_commit = False
    if v21_changes:
        final_status = BLOCKED_V21
        decision = "BLOCK_V21_CURRENT_OUTPUT_MUTATION_DETECTED"
        ready_commit = False
    if protected_changes:
        final_status = BLOCKED_PROTECTED
        decision = "BLOCK_PROTECTED_OUTPUT_MUTATION_DETECTED"
        ready_commit = False

    permissions = {
        "official_activation_allowed": "FALSE",
        "official_recommendation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
    }
    if any(value != "FALSE" for value in permissions.values()):
        final_status = BLOCKED_PERMISSION
        decision = "BLOCK_OFFICIAL_PERMISSION_VIOLATION"
        ready_commit = False

    risk_rows: list[dict[str, object]] = [
        {"risk_id": "SOURCE_INPUT", "status": "PASS" if valid_input else "BLOCK", "severity": "CRITICAL", "file_path": rel(root, summary_path), "finding": "V21.054-R1 source-isolation evidence is valid." if valid_input else "Required V21.054-R1 evidence is missing or invalid.", "mitigation": "Repair or rerun V21.054-R1 before archive planning."},
        {"risk_id": "ACTIVE_DEPENDENCY", "status": "PASS" if source_isolation and not unsafe_count else "BLOCK", "severity": "CRITICAL", "file_path": "", "finding": f"Unsafe active archive candidates: {unsafe_count}.", "mitigation": "Remove active dependencies before archive commit."},
        {"risk_id": "HISTORICAL_COUNT", "status": "PASS" if history_reconciled else "REVIEW", "severity": "MEDIUM", "file_path": rel(root, history_path), "finding": count_note, "mitigation": "Use persisted audit rows as canonical and resolve any mismatch."},
        {"risk_id": "FILE_MUTATION", "status": "PASS" if not (deleted_or_moved or unexpected_new or source_changes) else "BLOCK", "severity": "CRITICAL", "file_path": "", "finding": "No deletion, move, copy, archive, or source mutation detected.", "mitigation": "Revert unauthorized mutation and rerun."},
        {"risk_id": "V20_OUTPUT_MUTATION", "status": "PASS" if not v20_changes else "BLOCK", "severity": "CRITICAL", "file_path": "|".join(v20_changes), "finding": f"Changed V20 outputs: {len(v20_changes)}.", "mitigation": "Restore V20 outputs before continuing."},
        {"risk_id": "V21_CURRENT_MUTATION", "status": "PASS" if not v21_changes else "BLOCK", "severity": "CRITICAL", "file_path": "|".join(v21_changes), "finding": f"Changed V21 current outputs: {len(v21_changes)}.", "mitigation": "Restore V21 current outputs before continuing."},
        {"risk_id": "PROTECTED_MUTATION", "status": "PASS" if not protected_changes else "BLOCK", "severity": "CRITICAL", "file_path": "|".join(protected_changes), "finding": f"Changed protected outputs: {len(protected_changes)}.", "mitigation": "Restore protected outputs before continuing."},
    ]

    summary: dict[str, object] = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "source_v21_054_r1_status": clean(source_summary.get("final_status")) or "NOT_AVAILABLE",
        "source_isolation_pass": tf(source_isolation),
        "v21_active_current_reads_v20_scripts": tf(as_bool(source_summary.get("v21_active_current_reads_v20_scripts"))),
        "v21_active_current_reads_v20_outputs": tf(as_bool(source_summary.get("v21_active_current_reads_v20_outputs"))),
        "v21_active_current_reads_v20_8_to_v20_16_stale_downstream": tf(as_bool(source_summary.get("v21_active_current_reads_v20_8_to_v20_16_stale_downstream"))),
        "harmless_historical_v20_reference_count_from_summary": history_count_summary,
        "harmless_historical_v20_reference_count_from_audit_file": history_count_audit,
        "harmless_historical_reference_count_reconciled": tf(history_reconciled),
        "v20_file_count_scanned": len(v20_paths),
        "archive_candidate_count": len(classified["archive"]),
        "keep_reference_count": len(classified["keep"]),
        "protected_never_archive_count": len(classified["protected"]),
        "future_delete_candidate_count": len(classified["future_delete"]),
        "unsafe_archive_candidate_count": unsafe_count,
        "archive_package_count": len(packages),
        "estimated_archive_size_mb": round(sum(float(row["size_mb"]) for row in classified["archive"]), 6),
        "estimated_future_delete_candidate_size_mb": round(sum(float(row["size_mb"]) for row in classified["future_delete"]), 6),
        "archive_dry_run_only": "TRUE",
        "archive_allowed": "FALSE",
        "deletion_allowed": "FALSE",
        "migration_allowed": "FALSE",
        "files_deleted_or_moved": tf(deleted_or_moved),
        "files_archived": "FALSE",
        "files_copied": tf(bool(unexpected_new)),
        "source_files_mutated": tf(bool(source_changes)),
        "v20_outputs_mutated": tf(bool(v20_changes)),
        "v21_current_outputs_mutated": tf(bool(v21_changes)),
        "protected_outputs_mutated": tf(bool(protected_changes)),
        "protected_output_mutation_count": len(protected_changes),
        "ready_for_v20_archive_commit": tf(ready_commit),
        "ready_for_v20_delete_candidate_dry_run": "FALSE",
        **permissions,
        "research_only": "TRUE",
        "recommended_next_stage": "V20_ARCHIVE_COMMIT" if ready_commit else "V20_ARCHIVE_DRY_RUN_R1A_MANUAL_REVIEW",
        "created_at_utc": utc_now(),
    }

    write_csv(migration / "V20_ARCHIVE_DRY_RUN_SUMMARY.csv", [summary], SUMMARY_FIELDS)
    write_csv(migration / "V20_ARCHIVE_CANDIDATE_MANIFEST.csv", classified["archive"], MANIFEST_FIELDS)
    write_csv(migration / "V20_KEEP_ACTIVE_OR_REFERENCE_MANIFEST.csv", classified["keep"], MANIFEST_FIELDS)
    write_csv(migration / "V20_PROTECTED_NEVER_ARCHIVE_MANIFEST.csv", classified["protected"], MANIFEST_FIELDS)
    write_csv(migration / "V20_FUTURE_DELETE_CANDIDATE_DRY_RUN_QUEUE.csv", classified["future_delete"], MANIFEST_FIELDS)
    write_csv(migration / "V20_ARCHIVE_PACKAGE_PLAN.csv", packages, PACKAGE_FIELDS)
    write_csv(migration / "V20_ARCHIVE_READINESS_RISK_AUDIT.csv", risk_rows, RISK_FIELDS)
    read_center.mkdir(parents=True, exist_ok=True)
    (read_center / REPORT_NAME).write_text(render_report(summary, count_note, risk_rows), encoding="utf-8")
    return summary, {**classified, "packages": packages, "risks": risk_rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    summary, _ = run_archive_dry_run(args.root)
    for field in SUMMARY_FIELDS:
        print(f"{field.upper()}={summary.get(field, '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
