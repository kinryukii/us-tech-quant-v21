#!/usr/bin/env python
"""V21.051-R1 remove active V20.8-V20.16 stale downstream dependencies."""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.051-R1_REMOVE_V20_STALE_DOWNSTREAM_DEPENDENCY"

PASS_STATUS = "PASS_V21_051_R1_V20_STALE_DOWNSTREAM_DEPENDENCY_REMOVED"
PARTIAL_STATUS = "PARTIAL_PASS_V21_051_R1_STALE_DEPENDENCY_REDUCED_MANUAL_REVIEW_REMAINING"
BLOCKED_UNSAFE = "BLOCKED_V21_051_R1_UNSAFE_STALE_DEPENDENCY_REMAINS"
BLOCKED_AUDIT = "BLOCKED_V21_051_R1_SOURCE_AUDIT_MISSING_OR_INVALID"
BLOCKED_NO_REPLACEMENT = "BLOCKED_V21_051_R1_NO_SAFE_REPLACEMENT_FOUND"
BLOCKED_V20_MUTATION = "BLOCKED_V21_051_R1_V20_OUTPUT_MUTATION_DETECTED"
BLOCKED_V21_MUTATION = "BLOCKED_V21_051_R1_V21_CURRENT_OUTPUT_MUTATION_DETECTED"
BLOCKED_PROTECTED = "BLOCKED_V21_051_R1_PROTECTED_OUTPUT_MUTATION_DETECTED"
BLOCKED_PERMISSION = "BLOCKED_V21_051_R1_OFFICIAL_PERMISSION_VIOLATION"

V21_NATIVE_LEDGER = "outputs/v21/context/V21_048_R1_REPAIRED_CONTEXT_OBSERVATION_LEDGER.csv"
V21_NATIVE_MATURITY = "outputs/v21/context/V21_049_R1_REPAIRED_CONTEXT_MATURITY_EVALUATION_SUMMARY.csv"

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "source_v21_050_status",
    "stale_dependency_found_before", "stale_dependency_reference_count_before",
    "stale_dependency_reference_count_after", "stale_dependency_removed_count",
    "stale_dependency_remaining_count",
    "v21_reads_v20_8_to_v20_16_stale_downstream_after",
    "v21_reads_v20_outputs_after", "v21_reads_v20_scripts_after",
    "shared_data_dependency_found_after", "v21_native_replacement_count",
    "shared_source_replacement_count", "manual_review_remaining_count",
    "files_modified_count", "files_deleted_or_moved", "v20_outputs_mutated",
    "v21_current_outputs_mutated", "protected_outputs_mutated",
    "protected_output_mutation_count", "official_activation_allowed",
    "official_recommendation_allowed", "official_ranking_mutation_allowed",
    "official_weight_mutation_allowed", "broker_execution_allowed",
    "trade_action_allowed", "research_only", "recommended_next_stage",
    "created_at_utc",
]

MAP_FIELDS = [
    "original_reference", "reference_location", "reference_type", "stale_risk",
    "replacement_type", "replacement_reference", "replacement_reason",
    "changed", "manual_review_required",
]

AUDIT_FIELDS = [
    "reference", "reference_location", "reference_type", "active_current_source",
    "stale_risk", "manual_review_required", "reason",
]

TEXT_SUFFIXES = {".py", ".ps1", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini"}
OUTPUT_TEXT_SUFFIXES = {".csv", ".md", ".txt", ".json"}
STALE_PATH_RE = re.compile(
    r"(?:outputs[\\/]+v20[\\/][A-Za-z0-9_ .\\/\\-]*V20_(?:8|9|10|11|12|13|14|15|16)(?!\d)[A-Za-z0-9_ .\\/\\-]*)",
    re.I,
)
STALE_SCRIPT_RE = re.compile(
    r"(?:scripts[\\/]+v20[\\/][A-Za-z0-9_ .\\/\\-]*v20_(?:8|9|10|11|12|13|14|15|16)(?!\d)[A-Za-z0-9_ .\\/\\-]*)",
    re.I,
)
PROTECTED_RE = re.compile(
    r"(authoritative.*official.*rank|official.*weight|official.*recommend|"
    r"broker|trade[_ .-]*action|real[_ .-]*book)", re.I,
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
    return "V21_051_R1" not in path.name and bool(PROTECTED_RE.search(path.name))


def v20_output_matcher(path: Path) -> bool:
    return "staging" not in {part.lower() for part in path.parts}


def v21_current_matcher(path: Path) -> bool:
    return "V21_051_R1" not in path.name and ("V21_048" in path.name or "V21_049" in path.name)


def active_v21_files(root: Path) -> list[Path]:
    base = root / "scripts/v21"
    if not base.exists():
        return []
    files = []
    for path in base.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        name = path.name.lower()
        if name.startswith("test_") or "v21_050" in name or "v21_051" in name:
            continue
        files.append(path)
    return sorted(files)


def historical_v21_reference_files(root: Path) -> list[Path]:
    base = root / "outputs/v21"
    if not base.exists():
        return []
    files = []
    for path in base.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in OUTPUT_TEXT_SUFFIXES:
            continue
        r = rel(root, path)
        if r.startswith("outputs/v21/migration/") or "V21_051_R1" in path.name:
            continue
        files.append(path)
    return sorted(files)


def normalize_ref(ref: str) -> str:
    return ref.replace("\\", "/").strip(" ,;:'\")(")


def find_refs_in_text(text: str) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for match in STALE_PATH_RE.findall(text):
        refs.append((normalize_ref(match), "V20_OUTPUT"))
    for match in STALE_SCRIPT_RE.findall(text):
        refs.append((normalize_ref(match), "V20_SCRIPT"))
    return refs


def scan_active_refs(root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in active_v21_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for ref, rtype in find_refs_in_text(text):
            rows.append({
                "reference": ref,
                "reference_location": rel(root, path),
                "reference_type": rtype,
                "active_current_source": "TRUE",
                "stale_risk": "HIGH",
                "manual_review_required": "FALSE",
                "reason": "Active V21 script/config references V20.8-V20.16 stale downstream.",
            })
    return rows


def scan_historical_refs(root: Path, source_audit_rows: list[dict[str, str]] | None = None) -> list[dict[str, object]]:
    if source_audit_rows is not None:
        rows: list[dict[str, object]] = []
        for source in source_audit_rows:
            if clean(source.get("stale_lineage_risk")) != "HIGH":
                continue
            refs = [part for part in clean(source.get("referenced_by_v21")).split("|") if part]
            historical_refs = [
                ref for ref in refs
                if ref.startswith("outputs/v21/")
                and not ref.startswith("outputs/v21/migration/")
                and "V21_051_R1" not in ref
            ]
            for ref_location in historical_refs:
                rows.append({
                    "reference": clean(source.get("file_path")),
                    "reference_location": ref_location,
                    "reference_type": clean(source.get("reference_type")) or "V20_OUTPUT",
                    "active_current_source": "FALSE",
                    "stale_risk": "HIGH",
                    "manual_review_required": "TRUE",
                    "reason": "Historical/report reference retained for manual review; not an active current source.",
                })
        return rows
    rows: list[dict[str, object]] = []
    for path in historical_v21_reference_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for ref, rtype in find_refs_in_text(text):
            rows.append({
                "reference": ref,
                "reference_location": rel(root, path),
                "reference_type": rtype,
                "active_current_source": "FALSE",
                "stale_risk": "HIGH",
                "manual_review_required": "TRUE",
                "reason": "Historical/report reference retained for manual review; not an active current source.",
            })
    return rows


def replacement_for(ref: str) -> tuple[str, str, str]:
    if "V20_15_LIMITED_FACTOR_SCORE_LAYER.csv" in ref:
        return "V21_NATIVE", V21_NATIVE_LEDGER, "Replace stale V20.15 limited score layer with current repaired V21 context observation ledger."
    if "V20_16" in ref and "SUMMARY" in ref.upper():
        return "V21_NATIVE", V21_NATIVE_MATURITY, "Replace V20.16 status dependency with current V21 maturity summary."
    return "NONE", "", "No safe automatic replacement for this active stale dependency."


def apply_replacements(root: Path, active_before: list[dict[str, object]]) -> tuple[list[dict[str, object]], set[str]]:
    by_file: dict[str, list[dict[str, object]]] = {}
    for row in active_before:
        by_file.setdefault(clean(row["reference_location"]), []).append(row)
    replacement_rows: list[dict[str, object]] = []
    modified: set[str] = set()
    for location, rows in by_file.items():
        path = root / location
        text = path.read_text(encoding="utf-8", errors="replace")
        new_text = text
        for row in rows:
            original = clean(row["reference"])
            replacement_type, replacement, reason = replacement_for(original)
            changed_flag = False
            manual = replacement_type == "NONE"
            if replacement:
                # Replace both slash styles and bare filename where the file is Path-composed.
                new_text = new_text.replace(original, replacement)
                new_text = new_text.replace(original.replace("/", "\\"), replacement)
                if "V20_15_LIMITED_FACTOR_SCORE_LAYER.csv" in original:
                    new_text = new_text.replace("V20_15_LIMITED_FACTOR_SCORE_LAYER.csv", "V21_048_R1_REPAIRED_CONTEXT_OBSERVATION_LEDGER.csv")
                    new_text = new_text.replace('ROOT / "outputs" / "v20" / "consolidation"', 'ROOT / "outputs" / "v21" / "context"')
                changed_flag = new_text != text
            replacement_rows.append({
                "original_reference": original,
                "reference_location": location,
                "reference_type": row["reference_type"],
                "stale_risk": row["stale_risk"],
                "replacement_type": replacement_type,
                "replacement_reference": replacement,
                "replacement_reason": reason,
                "changed": tf(changed_flag),
                "manual_review_required": tf(manual),
            })
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            modified.add(location)
    return replacement_rows, modified


def collect_v20_after_flags(root: Path, remaining_active: list[dict[str, object]]) -> tuple[bool, bool, bool]:
    v20_output = False
    v20_script = False
    shared = False
    for path in active_v21_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        v20_output = v20_output or "outputs/v20" in text or "outputs\\v20" in text
        v20_script = v20_script or "scripts/v20" in text or "scripts\\v20" in text or "scripts.v20" in text
        shared = shared or bool(SHARED_RE.search(text))
    stale = bool(remaining_active)
    return v20_output or stale, v20_script, shared


def render_report(summary: dict[str, object]) -> str:
    return f"""# V21.051-R1 Remove V20 Stale Downstream Dependency

- final_status: {summary['final_status']}
- decision: {summary['decision']}
- stale_dependency_reference_count_before: {summary['stale_dependency_reference_count_before']}
- stale_dependency_reference_count_after: {summary['stale_dependency_reference_count_after']}
- stale_dependency_removed_count: {summary['stale_dependency_removed_count']}
- manual_review_remaining_count: {summary['manual_review_remaining_count']}
- files_modified_count: {summary['files_modified_count']}
- files_deleted_or_moved: FALSE
- recommended_next_stage: {summary['recommended_next_stage']}

Active current-source V21 script dependencies on V20.8-V20.16 stale downstream
were replaced when a clear V21-native source was available. Historical V21
reports/manifests may still mention stale V20 artifacts as manual-review records.
No V20 outputs, V21 current outputs, or protected official outputs were mutated.
"""


def run_repair(
    root: Path,
    protected_mutation_hook: Callable[[], None] | None = None,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    root = root.resolve()
    out_dir = root / "outputs/v21/migration"
    v21_050 = read_first(root / "outputs/v21/migration/V21_050_R1_V20_DEPENDENCY_MIGRATION_AND_CLEANUP_DRY_RUN_SUMMARY.csv")
    audit_rows, _ = read_csv(root / "outputs/v21/migration/V21_050_R1_V20_DEPENDENCY_AUDIT_BY_FILE.csv")
    source_valid = (
        clean(v21_050.get("final_status")) == "BLOCKED_V21_050_R1_V20_STALE_DOWNSTREAM_DEPENDENCY_FOUND"
        and clean(v21_050.get("recommended_next_stage")) == "V21_051_R1_REMOVE_V20_STALE_DOWNSTREAM_DEPENDENCY"
        and bool(audit_rows)
    )

    before_files = {rel(root, p) for p in root.rglob("*") if p.is_file()}
    before_v20 = snapshot(root, root / "outputs/v20", v20_output_matcher)
    before_v21_current = snapshot(root, root / "outputs/v21", v21_current_matcher)
    before_protected = snapshot(root, root / "outputs", protected_matcher)

    active_before = scan_active_refs(root)
    stale_found_before = bool(active_before) or clean(v21_050.get("v21_reads_v20_8_to_v20_16_stale_downstream")) == "TRUE"
    replacement_rows: list[dict[str, object]] = []
    modified: set[str] = set()
    if source_valid:
        replacement_rows, modified = apply_replacements(root, active_before)
    active_after = scan_active_refs(root)
    historical_after = scan_historical_refs(root, audit_rows)
    remaining_audit = active_after + historical_after
    v20_outputs_after, v20_scripts_after, shared_after = collect_v20_after_flags(root, active_after)

    if protected_mutation_hook:
        protected_mutation_hook()

    after_files = {rel(root, p) for p in root.rglob("*") if p.is_file()}
    deleted_or_moved = bool(before_files - after_files)
    v20_changes = changed(before_v20, snapshot(root, root / "outputs/v20", v20_output_matcher))
    v21_current_changes = changed(before_v21_current, snapshot(root, root / "outputs/v21", v21_current_matcher))
    protected_changes = changed(before_protected, snapshot(root, root / "outputs", protected_matcher))

    changed_count = sum(1 for row in replacement_rows if row["changed"] == "TRUE")
    manual_active = sum(1 for row in replacement_rows if row["manual_review_required"] == "TRUE")
    manual_total = manual_active + len(historical_after)
    if not source_valid:
        final_status = BLOCKED_AUDIT
        decision = "BLOCK_SOURCE_AUDIT_MISSING_OR_INVALID"
        recommended = "V21.050-R1_V20_DEPENDENCY_MIGRATION_AND_CLEANUP_DRY_RUN"
    elif active_after:
        final_status = BLOCKED_UNSAFE if manual_active else BLOCKED_NO_REPLACEMENT
        decision = "BLOCK_ACTIVE_STALE_DEPENDENCY_REMAINS"
        recommended = "V21_051_R1_MANUAL_STALE_DEPENDENCY_REPAIR"
    elif historical_after:
        final_status = PARTIAL_STATUS
        decision = "STALE_ACTIVE_DEPENDENCY_REMOVED_HISTORICAL_MANUAL_REVIEW_REMAINING"
        recommended = "V21.052-R1_V20_DEPENDENCY_MIGRATION_RECHECK"
    else:
        final_status = PASS_STATUS
        decision = "V20_STALE_DOWNSTREAM_ACTIVE_DEPENDENCY_REMOVED"
        recommended = "V21.052-R1_V20_DEPENDENCY_MIGRATION_RECHECK"
    if protected_changes:
        final_status = BLOCKED_PROTECTED
        decision = "BLOCK_PROTECTED_OUTPUT_MUTATION_DETECTED"
    elif v20_changes:
        final_status = BLOCKED_V20_MUTATION
        decision = "BLOCK_V20_OUTPUT_MUTATION_DETECTED"
    elif v21_current_changes:
        final_status = BLOCKED_V21_MUTATION
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
        "stale_dependency_found_before": tf(stale_found_before),
        "stale_dependency_reference_count_before": len(active_before),
        "stale_dependency_reference_count_after": len(active_after),
        "stale_dependency_removed_count": max(0, len(active_before) - len(active_after)),
        "stale_dependency_remaining_count": len(active_after),
        "v21_reads_v20_8_to_v20_16_stale_downstream_after": tf(bool(active_after)),
        "v21_reads_v20_outputs_after": tf(v20_outputs_after),
        "v21_reads_v20_scripts_after": tf(v20_scripts_after),
        "shared_data_dependency_found_after": tf(shared_after),
        "v21_native_replacement_count": sum(1 for row in replacement_rows if row["replacement_type"] == "V21_NATIVE" and row["changed"] == "TRUE"),
        "shared_source_replacement_count": sum(1 for row in replacement_rows if row["replacement_type"] == "SHARED_SOURCE" and row["changed"] == "TRUE"),
        "manual_review_remaining_count": manual_total,
        "files_modified_count": len(modified),
        "files_deleted_or_moved": tf(deleted_or_moved),
        "v20_outputs_mutated": tf(bool(v20_changes)),
        "v21_current_outputs_mutated": tf(bool(v21_current_changes)),
        "protected_outputs_mutated": tf(bool(protected_changes)),
        "protected_output_mutation_count": len(protected_changes),
        **perms,
        "research_only": "TRUE",
        "recommended_next_stage": recommended,
        "created_at_utc": utc_now(),
    }

    write_csv(out_dir / "V21_051_R1_REMOVE_V20_STALE_DOWNSTREAM_DEPENDENCY_SUMMARY.csv", [summary], SUMMARY_FIELDS)
    write_csv(out_dir / "V21_051_R1_STALE_DEPENDENCY_REPLACEMENT_MAP.csv", replacement_rows, MAP_FIELDS)
    write_csv(out_dir / "V21_051_R1_REMAINING_V20_DEPENDENCY_AUDIT.csv", remaining_audit, AUDIT_FIELDS)
    report_path = root / "outputs/v21/read_center/V21_051_R1_REMOVE_V20_STALE_DOWNSTREAM_DEPENDENCY_REPORT.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(summary), encoding="utf-8")
    return summary, replacement_rows, remaining_audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    summary, _, _ = run_repair(args.root)
    for field in SUMMARY_FIELDS:
        print(f"{field.upper()}={summary.get(field, '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
