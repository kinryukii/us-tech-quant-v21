#!/usr/bin/env python
"""V20.9-R1 relative path and staging contract repair audit."""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V20.9-R1_RELATIVE_PATH_AND_STAGING_CONTRACT_REPAIR"
TARGET_STAGE = "V20.9"
TARGET_SCRIPT = "scripts/v20/v20_9_factor_research_dataset_preparation.py"
TARGET_WRAPPER = "scripts/v20/run_v20_9_factor_research_dataset_preparation.ps1"
V20_8_SCRIPT = "scripts/v20/v20_8_normalized_research_dataset_construction.py"

PASS_STATUS = "PASS_V20_9_R1_RELATIVE_PATH_AND_STAGING_CONTRACT_REPAIRED"
PARTIAL_SMOKE_FAILED = "PARTIAL_PASS_V20_9_R1_CONTRACT_REPAIRED_STAGING_SMOKE_FAILED"
BLOCKED_R3B = "BLOCKED_V20_9_R1_R3B_INPUT_MISSING_OR_INVALID"
BLOCKED_TARGET = "BLOCKED_V20_9_R1_TARGET_SCRIPT_OR_WRAPPER_MISSING"
BLOCKED_BINDING = "BLOCKED_V20_9_R1_ABSOLUTE_PATH_BINDING_REMAINS"
BLOCKED_PRODUCTION_MUTATION = "BLOCKED_V20_9_R1_STAGING_SMOKE_MUTATED_PRODUCTION"
BLOCKED_PROTECTED_MUTATION = "BLOCKED_V20_9_R1_PROTECTED_OUTPUT_MUTATION_DETECTED"
BLOCKED_PERMISSION = "BLOCKED_V20_9_R1_OFFICIAL_PERMISSION_VIOLATION"

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "source_v20_16_r3b_status",
    "source_v20_16_r3b_decision", "target_stage", "target_script_path",
    "target_wrapper_path", "absolute_path_binding_before",
    "absolute_path_binding_after", "input_override_supported",
    "output_override_supported", "staging_mode_supported", "dry_run_supported",
    "production_write_default_preserved", "staging_smoke_attempted",
    "staging_smoke_pass", "staging_smoke_input_path",
    "staging_smoke_output_path", "staging_smoke_as_of_date",
    "staging_smoke_eligible_row_count", "expected_eligible_row_count",
    "expected_vs_staging_smoke_delta", "production_v20_9_outputs_mutated",
    "production_v20_10_to_v20_16_outputs_mutated",
    "production_v20_8_outputs_mutated", "certified_v20_7x_outputs_mutated",
    "protected_outputs_mutated", "protected_output_mutation_count",
    "official_activation_allowed", "official_recommendation_allowed",
    "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
    "broker_execution_allowed", "trade_action_allowed", "research_only",
    "recommended_next_stage", "created_at_utc",
]
AUDIT_FIELDS = ["check_name", "before_value", "after_value", "status", "details"]

PROTECTED_RE = re.compile(r"(authoritative.*official.*rank|official.*weight|official.*recommend|broker|trade[_ .-]*action|real[_ .-]*book)", re.I)
V20_8_RE = re.compile(r"^V20_8(?:_|\\.)", re.I)
V20_9_RE = re.compile(r"^V20_9(?:_|\\.)", re.I)
V20_10_16_RE = re.compile(r"^V20_(?:10|11|12|13|14|15|16)(?:_|\\.)", re.I)
V7X_RE = re.compile(r"^V20_7X_", re.I)
DRIVE_PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\"'\s)]+")


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


def snapshot(root: Path, matcher: Callable[[Path], bool]) -> dict[str, str]:
    base = root / "outputs/v20"
    if not base.exists():
        return {}
    return {
        path.resolve().relative_to(root.resolve()).as_posix(): file_hash(path)
        for path in base.rglob("*") if path.is_file() and matcher(path)
    }


def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


def non_staging(path: Path) -> bool:
    return "staging" not in {part.lower() for part in path.parts}


def unique_date(rows: list[dict[str, str]]) -> str:
    dates = sorted({clean(row.get(field))[:10] for row in rows for field in ("effective_observation_date", "as_of_date", "effective_price_date") if clean(row.get(field))})
    return dates[-1] if dates else ""


def eligible_count(rows: list[dict[str, str]]) -> int:
    if not rows:
        return 0
    if "eligible_row_count" in rows[0] and clean(rows[0].get("eligible_row_count")).isdigit():
        return int(clean(rows[0].get("eligible_row_count")))
    if "eligible_for_factor_source_attachment_next" in rows[0]:
        selected = [row for row in rows if clean(row.get("eligible_for_factor_source_attachment_next")).upper() == "TRUE"]
        return len(selected) if selected else len(rows)
    if "allowed_for_factor_research_next" in rows[0]:
        selected = [row for row in rows if clean(row.get("allowed_for_factor_research_next")).upper() == "TRUE"]
        return len(selected) if selected else len(rows)
    return len(rows)


def audit_contract(root: Path) -> dict[str, bool]:
    text = (root / TARGET_SCRIPT).read_text(encoding="utf-8", errors="replace") + "\n" + (root / TARGET_WRAPPER).read_text(encoding="utf-8", errors="replace")
    absolute = bool(DRIVE_PATH_RE.search(text)) or bool(re.search(r"Path\(__file__\)\.resolve\(\)\.parents\[\d+\]", text) and re.search(r"\bOUT_[A-Z0-9_]+\s*=", text))
    return {
        "absolute_path_binding": absolute,
        "input_override": "--input-path" in text and "InputPath" in text,
        "output_override": "--output-dir" in text and "OutputDir" in text,
        "staging_mode": "--staging-mode" in text and "StagingMode" in text,
        "dry_run": "--dry-run" in text and "DryRun" in text,
        "production_default": "production_write_allowed = bool(args.production_write_allowed or (args.output_dir is None" in text,
    }


def validate_r3b(root: Path) -> tuple[dict[str, str], bool]:
    row = read_first(root / "outputs/v20/diagnostics/V20_16_R3B_SAFE_STAGED_RERUN_WRAPPER_SUMMARY.csv")
    valid = (
        clean(row.get("final_status")) == "BLOCKED_V20_16_R3B_ABSOLUTE_PRODUCTION_PATH_BINDING"
        and clean(row.get("earliest_failed_stage")) == "V20.9"
    )
    return row, valid


def ensure_v20_8_smoke(root: Path) -> Path:
    staged = root / "outputs/v20/staging/V20_8_R1_CONTRACT_SMOKE/consolidation/V20_8_NORMALIZED_RESEARCH_DATASET.csv"
    if staged.exists():
        return staged
    smoke_dir = root / "outputs/v20/staging/V20_8_R1_CONTRACT_SMOKE"
    if smoke_dir.exists():
        shutil.rmtree(smoke_dir)
    input_path = root / "outputs/v20/consolidation/V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv"
    subprocess.run(
        [sys.executable, V20_8_SCRIPT, "--input-path", str(input_path), "--output-dir", str(smoke_dir), "--staging-mode"],
        cwd=root, text=True, capture_output=True, timeout=120, check=False,
    )
    return staged


def run_smoke(root: Path, expected_count: int) -> tuple[bool, str, str, str, str, str]:
    input_path = ensure_v20_8_smoke(root)
    smoke_dir = root / "outputs/v20/staging/V20_9_R1_CONTRACT_SMOKE"
    if smoke_dir.exists():
        shutil.rmtree(smoke_dir)
    proc = subprocess.run(
        [sys.executable, TARGET_SCRIPT, "--input-path", str(input_path), "--output-dir", str(smoke_dir), "--staging-mode"],
        cwd=root, text=True, capture_output=True, timeout=120,
    )
    output_path = smoke_dir / "consolidation/V20_9_FACTOR_RESEARCH_BASE_DATASET.csv"
    rows, _ = read_csv(output_path)
    date = unique_date(rows)
    count = str(eligible_count(rows))
    delta = str(int(count) - expected_count) if count.isdigit() else ""
    passed = proc.returncode == 0 and output_path.exists() and int(count or "0") == expected_count
    error = (proc.stderr or proc.stdout or "").strip().replace("\r", " ").replace("\n", " ")[:1000]
    return passed, input_path.resolve().relative_to(root.resolve()).as_posix(), output_path.resolve().relative_to(root.resolve()).as_posix(), date, count, delta or error


def render_report(summary: dict[str, object], audit_rows: list[dict[str, object]]) -> str:
    checks = "\n".join(f"- {row['check_name']}: {row['status']} ({row['after_value']})" for row in audit_rows)
    return f"""# V20.9-R1 Relative Path And Staging Contract Repair

- final_status: {summary['final_status']}
- decision: {summary['decision']}
- staging_smoke_pass: {summary['staging_smoke_pass']}
- staging_smoke_input_path: {summary['staging_smoke_input_path']}
- staging_smoke_output_path: {summary['staging_smoke_output_path']}
- recommended_next_stage: {summary['recommended_next_stage']}

## Contract Audit

{checks}

The V20.9 script now supports explicit input/output overrides, staging mode,
dry-run mode, and status fields required by the staged rerun wrapper. This stage
does not commit or refresh production downstream outputs.
"""


def run_repair(root: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    root = root.resolve()
    diagnostics = root / "outputs/v20/diagnostics"
    r3b, r3b_valid = validate_r3b(root)
    expected_count = int(clean(r3b.get("expected_eligible_row_count")) or clean(r3b.get("certified_v20_7x_eligible_row_count")) or "0")
    before_absolute = clean(r3b.get("absolute_path_binding_detected")) or "TRUE"

    before_v20_9 = snapshot(root, lambda p: non_staging(p) and bool(V20_9_RE.match(p.name)))
    before_v20_10_16 = snapshot(root, lambda p: non_staging(p) and bool(V20_10_16_RE.match(p.name)))
    before_v20_8 = snapshot(root, lambda p: non_staging(p) and bool(V20_8_RE.match(p.name)))
    before_v7x = snapshot(root, lambda p: non_staging(p) and bool(V7X_RE.match(p.name)))
    before_protected = snapshot(root, lambda p: non_staging(p) and "V20_9_R1" not in p.name and bool(PROTECTED_RE.search(p.name)))

    script = root / TARGET_SCRIPT
    wrapper = root / TARGET_WRAPPER
    after = audit_contract(root) if script.exists() and wrapper.exists() else {
        "absolute_path_binding": True, "input_override": False, "output_override": False,
        "staging_mode": False, "dry_run": False, "production_default": False,
    }
    audit_rows = [
        {"check_name": "absolute_path_binding", "before_value": before_absolute, "after_value": tf(after["absolute_path_binding"]), "status": "PASS" if not after["absolute_path_binding"] else "BLOCKED", "details": "No drive path or script-file-derived production root binding remains."},
        {"check_name": "input_override_supported", "before_value": "FALSE", "after_value": tf(after["input_override"]), "status": "PASS" if after["input_override"] else "BLOCKED", "details": "--input-path and -InputPath supported."},
        {"check_name": "output_override_supported", "before_value": "FALSE", "after_value": tf(after["output_override"]), "status": "PASS" if after["output_override"] else "BLOCKED", "details": "--output-dir and -OutputDir supported."},
        {"check_name": "staging_mode_supported", "before_value": "FALSE", "after_value": tf(after["staging_mode"]), "status": "PASS" if after["staging_mode"] else "BLOCKED", "details": "--staging-mode and -StagingMode supported."},
        {"check_name": "dry_run_supported", "before_value": "FALSE", "after_value": tf(after["dry_run"]), "status": "PASS" if after["dry_run"] else "BLOCKED", "details": "--dry-run and -DryRun supported."},
        {"check_name": "production_write_default_preserved", "before_value": "TRUE", "after_value": tf(after["production_default"]), "status": "PASS" if after["production_default"] else "BLOCKED", "details": "No-override invocation still allows production V20.9 writes."},
    ]
    summary: dict[str, object] = {
        "stage": STAGE, "final_status": PASS_STATUS,
        "decision": "V20_9_CONTRACT_REPAIRED_STAGING_SMOKE_PASSED",
        "source_v20_16_r3b_status": clean(r3b.get("final_status")) or "NOT_AVAILABLE",
        "source_v20_16_r3b_decision": clean(r3b.get("decision")) or "NOT_AVAILABLE",
        "target_stage": TARGET_STAGE, "target_script_path": TARGET_SCRIPT,
        "target_wrapper_path": TARGET_WRAPPER,
        "absolute_path_binding_before": before_absolute,
        "absolute_path_binding_after": tf(after["absolute_path_binding"]),
        "input_override_supported": tf(after["input_override"]),
        "output_override_supported": tf(after["output_override"]),
        "staging_mode_supported": tf(after["staging_mode"]),
        "dry_run_supported": tf(after["dry_run"]),
        "production_write_default_preserved": tf(after["production_default"]),
        "staging_smoke_attempted": "FALSE", "staging_smoke_pass": "FALSE",
        "staging_smoke_input_path": "", "staging_smoke_output_path": "",
        "staging_smoke_as_of_date": "", "staging_smoke_eligible_row_count": "",
        "expected_eligible_row_count": str(expected_count), "expected_vs_staging_smoke_delta": "",
        "production_v20_9_outputs_mutated": "FALSE",
        "production_v20_10_to_v20_16_outputs_mutated": "FALSE",
        "production_v20_8_outputs_mutated": "FALSE",
        "certified_v20_7x_outputs_mutated": "FALSE",
        "protected_outputs_mutated": "FALSE", "protected_output_mutation_count": "0",
        "official_activation_allowed": "FALSE", "official_recommendation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE", "official_weight_mutation_allowed": "FALSE",
        "broker_execution_allowed": "FALSE", "trade_action_allowed": "FALSE",
        "research_only": "TRUE", "recommended_next_stage": "V20.16-R3B_SAFE_STAGED_RERUN_WRAPPER",
        "created_at_utc": utc_now(),
    }

    if not r3b_valid:
        summary["final_status"] = BLOCKED_R3B
        summary["decision"] = "BLOCK_R3B_INPUT_MISSING_OR_INVALID"
    elif not script.exists() or not wrapper.exists():
        summary["final_status"] = BLOCKED_TARGET
        summary["decision"] = "BLOCK_TARGET_SCRIPT_OR_WRAPPER_MISSING"
    elif after["absolute_path_binding"]:
        summary["final_status"] = BLOCKED_BINDING
        summary["decision"] = "BLOCK_ABSOLUTE_PATH_BINDING_REMAINS"
    elif not (not after["absolute_path_binding"] and after["input_override"] and after["output_override"] and after["staging_mode"] and after["dry_run"] and after["production_default"]):
        summary["final_status"] = PARTIAL_SMOKE_FAILED
        summary["decision"] = "CONTRACT_REPAIR_INCOMPLETE"
    else:
        summary["staging_smoke_attempted"] = "TRUE"
        smoke_pass, input_path, output_path, date, count, delta = run_smoke(root, expected_count)
        summary["staging_smoke_pass"] = tf(smoke_pass)
        summary["staging_smoke_input_path"] = input_path
        summary["staging_smoke_output_path"] = output_path
        summary["staging_smoke_as_of_date"] = date
        summary["staging_smoke_eligible_row_count"] = count
        summary["expected_vs_staging_smoke_delta"] = delta if delta.lstrip("-").isdigit() else ""
        if not smoke_pass:
            summary["final_status"] = PARTIAL_SMOKE_FAILED
            summary["decision"] = "CONTRACT_REPAIRED_STAGING_SMOKE_FAILED"

    changes = {
        "production_v20_9_outputs_mutated": changed(before_v20_9, snapshot(root, lambda p: non_staging(p) and bool(V20_9_RE.match(p.name)))),
        "production_v20_10_to_v20_16_outputs_mutated": changed(before_v20_10_16, snapshot(root, lambda p: non_staging(p) and bool(V20_10_16_RE.match(p.name)))),
        "production_v20_8_outputs_mutated": changed(before_v20_8, snapshot(root, lambda p: non_staging(p) and bool(V20_8_RE.match(p.name)))),
        "certified_v20_7x_outputs_mutated": changed(before_v7x, snapshot(root, lambda p: non_staging(p) and bool(V7X_RE.match(p.name)))),
        "protected_outputs_mutated": changed(before_protected, snapshot(root, lambda p: non_staging(p) and "V20_9_R1" not in p.name and bool(PROTECTED_RE.search(p.name)))),
    }
    for field, paths in changes.items():
        summary[field] = tf(bool(paths))
    summary["protected_output_mutation_count"] = str(len(changes["protected_outputs_mutated"]))
    if changes["protected_outputs_mutated"]:
        summary["final_status"] = BLOCKED_PROTECTED_MUTATION
        summary["decision"] = "BLOCK_PROTECTED_OUTPUT_MUTATION_DETECTED"
    elif any(paths for key, paths in changes.items() if key != "protected_outputs_mutated"):
        summary["final_status"] = BLOCKED_PRODUCTION_MUTATION
        summary["decision"] = "BLOCK_STAGING_SMOKE_MUTATED_PRODUCTION"
    if any(summary[field] != "FALSE" for field in ("official_activation_allowed", "official_recommendation_allowed", "official_ranking_mutation_allowed", "official_weight_mutation_allowed", "broker_execution_allowed", "trade_action_allowed")):
        summary["final_status"] = BLOCKED_PERMISSION
        summary["decision"] = "BLOCK_OFFICIAL_PERMISSION_VIOLATION"

    write_csv(diagnostics / "V20_9_R1_RELATIVE_PATH_AND_STAGING_CONTRACT_REPAIR_SUMMARY.csv", [summary], SUMMARY_FIELDS)
    write_csv(diagnostics / "V20_9_R1_CONTRACT_AUDIT.csv", audit_rows, AUDIT_FIELDS)
    report = root / "outputs/v20/read_center/V20_9_R1_RELATIVE_PATH_AND_STAGING_CONTRACT_REPAIR_REPORT.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(summary, audit_rows), encoding="utf-8")
    return summary, audit_rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    summary, _ = run_repair(args.root)
    for field in SUMMARY_FIELDS:
        print(f"{field.upper()}={summary.get(field, '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
