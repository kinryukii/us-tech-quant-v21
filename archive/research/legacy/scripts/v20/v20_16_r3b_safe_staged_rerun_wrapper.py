#!/usr/bin/env python
"""V20.16-R3B safe staged rerun wrapper.

Runs V20.8-V20.16 only when the downstream scripts can resolve all reads and
writes inside an isolated staging workspace. Otherwise it blocks with an exact
staging-contract blocker and leaves production outputs untouched.
"""

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
STAGE = "V20.16-R3B_SAFE_STAGED_RERUN_WRAPPER"

PASS_STATUS = "PASS_V20_16_R3B_SAFE_STAGED_RERUN_COMPLETED"
PARTIAL_STAGE_FAILED = "PARTIAL_PASS_V20_16_R3B_STAGED_RERUN_STARTED_STAGE_FAILED"
BLOCKED_R3A = "BLOCKED_V20_16_R3B_R3A_INPUT_MISSING_OR_INVALID"
BLOCKED_V7X = "BLOCKED_V20_16_R3B_CERTIFIED_V20_7X_INPUT_MISSING"
BLOCKED_ABSOLUTE = "BLOCKED_V20_16_R3B_ABSOLUTE_PRODUCTION_PATH_BINDING"
BLOCKED_WORKSPACE = "BLOCKED_V20_16_R3B_STAGING_WORKSPACE_CREATION_FAILED"
BLOCKED_UNSAFE = "BLOCKED_V20_16_R3B_STAGED_RERUN_UNSAFE"
BLOCKED_RECON = "BLOCKED_V20_16_R3B_STAGED_RECONCILIATION_FAILED"
BLOCKED_PRODUCTION_MUTATION = "BLOCKED_V20_16_R3B_PRODUCTION_OUTPUT_MUTATION_DETECTED"
BLOCKED_PROTECTED_MUTATION = "BLOCKED_V20_16_R3B_PROTECTED_OUTPUT_MUTATION_DETECTED"

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "source_v20_16_r3a_status",
    "source_v20_16_r3a_decision", "certified_v20_7x_as_of_date",
    "certified_v20_7x_eligible_row_count",
    "production_downstream_as_of_date_before",
    "production_downstream_eligible_row_count_before",
    "staging_workspace_path", "staging_workspace_created",
    "absolute_path_binding_detected", "relative_path_staging_supported",
    "staged_rerun_attempted", "staged_rerun_completed",
    "earliest_failed_stage", "earliest_failure_reason",
    "staged_downstream_as_of_date", "staged_eligible_row_count",
    "expected_eligible_row_count", "expected_vs_staged_delta",
    "staged_reconciliation_pass",
    "production_v20_8_to_v20_16_outputs_mutated",
    "certified_v20_7x_outputs_mutated", "protected_outputs_mutated",
    "protected_output_mutation_count", "official_activation_allowed",
    "official_recommendation_allowed", "official_ranking_mutation_allowed",
    "official_weight_mutation_allowed", "broker_execution_allowed",
    "trade_action_allowed", "research_only", "recommended_next_stage",
    "created_at_utc",
]

STAGE_RESULT_FIELDS = [
    "stage_name", "script_path", "wrapper_path", "attempted", "status",
    "exit_code", "produced_file_count", "produced_files",
    "as_of_date", "eligible_row_count", "error",
]

MANIFEST_FIELDS = [
    "relative_path", "size_bytes", "sha256", "row_count", "as_of_date",
    "eligible_row_count", "stage_hint", "created_at_utc",
]

STAGES = [
    ("V20.8", "v20_8_normalized_research_dataset_construction.py", "run_v20_8_normalized_research_dataset_construction.ps1", "outputs/v20/consolidation/V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv", "outputs/v20/consolidation/V20_8_NORMALIZED_RESEARCH_DATASET.csv"),
    ("V20.9", "v20_9_factor_research_dataset_preparation.py", "run_v20_9_factor_research_dataset_preparation.ps1", "outputs/v20/consolidation/V20_8_NORMALIZED_RESEARCH_DATASET.csv", "outputs/v20/consolidation/V20_9_FACTOR_RESEARCH_BASE_DATASET.csv"),
    ("V20.10", "v20_10_factor_source_attachment_or_availability_audit.py", "run_v20_10_factor_source_attachment_or_availability_audit.ps1", "outputs/v20/consolidation/V20_9_FACTOR_RESEARCH_BASE_DATASET.csv", "outputs/v20/consolidation/V20_10_VALIDATION_SUMMARY.csv"),
    ("V20.11", "v20_11_factor_source_attachment_plan_or_first_attachable_factor_layer.py", "run_v20_11_factor_source_attachment_plan_or_first_attachable_factor_layer.ps1", "outputs/v20/consolidation/V20_10_GATE_DECISION.csv", "outputs/v20/consolidation/V20_11_FIRST_ATTACHABLE_FACTOR_INPUT_LAYER.csv"),
    ("V20.12", "v20_12_factor_input_layer_review_or_factor_evidence_gate.py", "run_v20_12_factor_input_layer_review_or_factor_evidence_gate.ps1", "outputs/v20/consolidation/V20_11_FIRST_ATTACHABLE_FACTOR_INPUT_LAYER.csv", "outputs/v20/consolidation/V20_12_GATE_DECISION.csv"),
    ("V20.13", "v20_13_first_limited_factor_evidence_layer.py", "run_v20_13_first_limited_factor_evidence_layer.ps1", "outputs/v20/consolidation/V20_12_GATE_DECISION.csv", "outputs/v20/consolidation/V20_13_LIMITED_FACTOR_EVIDENCE_LAYER.csv"),
    ("V20.14", "v20_14_factor_evidence_review_or_factor_score_gate.py", "run_v20_14_factor_evidence_review_or_factor_score_gate.ps1", "outputs/v20/consolidation/V20_13_LIMITED_FACTOR_EVIDENCE_LAYER.csv", "outputs/v20/consolidation/V20_14_GATE_DECISION.csv"),
    ("V20.15", "v20_15_first_limited_factor_score_layer.py", "run_v20_15_first_limited_factor_score_layer.ps1", "outputs/v20/consolidation/V20_14_GATE_DECISION.csv", "outputs/v20/consolidation/V20_15_LIMITED_FACTOR_SCORE_LAYER.csv"),
    ("V20.16", "v20_16_factor_score_review_or_backtest_readiness_gate.py", "run_v20_16_factor_score_review_or_backtest_readiness_gate.ps1", "outputs/v20/consolidation/V20_15_LIMITED_FACTOR_SCORE_LAYER.csv", "outputs/v20/consolidation/V20_16_GATE_DECISION.csv"),
]

VALID_R3A_STATUSES = {
    "PARTIAL_PASS_V20_16_R3A_FAILURE_CONFIRMED_MULTIPLE_UNSAFE_CONTRACTS",
    "PASS_V20_16_R3A_FAILURE_ROOT_CAUSE_IDENTIFIED_WRAPPER_PLAN_READY",
}

PROTECTED_RE = re.compile(
    r"(authoritative.*official.*rank|official.*weight|official.*recommend|"
    r"broker|trade[_ .-]*action|real[_ .-]*book)", re.IGNORECASE
)
PRODUCTION_RE = re.compile(r"^V20_(?:8|9|10|11|12|13|14|15|16)(?:_|\\.)", re.IGNORECASE)
V7X_RE = re.compile(r"^V20_7X_", re.IGNORECASE)
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
    out: dict[str, str] = {}
    for path in base.rglob("*"):
        if path.is_file() and matcher(path):
            out[path.resolve().relative_to(root.resolve()).as_posix()] = file_hash(path)
    return out


def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


def is_r3b_output(path: Path) -> bool:
    return "V20_16_R3B" in path.name or "V20.16-R3B" in path.name


def production_matcher(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    return "staging" not in parts and not is_r3b_output(path) and bool(PRODUCTION_RE.match(path.name))


def v7x_matcher(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    return "staging" not in parts and bool(V7X_RE.match(path.name))


def protected_matcher(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    return "staging" not in parts and not is_r3b_output(path) and bool(PROTECTED_RE.search(path.name))


def unique_date(rows: list[dict[str, str]]) -> str:
    fields = (
        "effective_observation_date", "observation_date", "as_of_date",
        "signal_date", "latest_price_date", "effective_price_date",
        "normalized_created_at_utc", "generated_at_utc",
    )
    dates = sorted({clean(row.get(field))[:10] for row in rows for field in fields if clean(row.get(field))})
    return dates[-1] if dates else ""


def eligible_count(rows: list[dict[str, str]]) -> int:
    if not rows:
        return 0
    for field in ("eligible_row_count", "NORMALIZED_ROWS_CREATED", "FACTOR_SCORE_ROWS_REVIEWED"):
        value = clean(rows[0].get(field))
        if value.isdigit():
            return int(value)
    if "allowed_for_v20_8_input" in rows[0]:
        selected = [row for row in rows if clean(row.get("allowed_for_v20_8_input")).upper() == "TRUE"]
        return len(selected) if selected else len(rows)
    if "allowed_for_factor_research_next" in rows[0]:
        selected = [row for row in rows if clean(row.get("allowed_for_factor_research_next")).upper() == "TRUE"]
        return len(selected) if selected else len(rows)
    return len(rows)


def current_downstream_state(root: Path) -> tuple[str, str]:
    c = root / "outputs/v20/consolidation"
    gate = read_first(c / "V20_16_GATE_DECISION.csv")
    count = clean(gate.get("eligible_row_count"))
    v8_rows, _ = read_csv(c / "V20_8_NORMALIZED_RESEARCH_DATASET.csv")
    return unique_date(v8_rows), count or str(eligible_count(v8_rows))


def certified_v7x_state(root: Path) -> tuple[Path, str, str, bool]:
    d = root / "outputs/v20/diagnostics"
    c = root / "outputs/v20/consolidation"
    r2 = read_first(d / "V20_7X_R2_CURRENT_LINEAGE_CERTIFICATION_REFRESH_COMMIT_SUMMARY.csv")
    path = c / "V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv"
    rows, _ = read_csv(path)
    artifact_date = unique_date(rows)
    artifact_count = eligible_count(rows)
    summary_date = clean(r2.get("certified_v20_7x_as_of_date_after"))
    summary_count = clean(r2.get("certified_v20_7x_eligible_row_count_after"))
    count = summary_count or str(artifact_count)
    date = summary_date or artifact_date
    valid = (
        path.exists() and bool(rows)
        and (not summary_date or artifact_date == summary_date)
        and (not summary_count or artifact_count == int(summary_count))
    )
    return path, date, count, valid


def validate_r3a(root: Path) -> tuple[dict[str, str], bool]:
    path = root / "outputs/v20/diagnostics/V20_16_R3A_SAFE_RERUN_EXECUTION_FAILURE_FORENSIC_SUMMARY.csv"
    row = read_first(path)
    valid = (
        clean(row.get("final_status")) in VALID_R3A_STATUSES
        and clean(row.get("recommended_next_stage")) == STAGE
    )
    return row, valid


def script_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def absolute_binding_audit(root: Path) -> tuple[bool, list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    detected = False
    for stage, script_name, wrapper_name, _, _ in STAGES:
        script = root / "scripts/v20" / script_name
        wrapper = root / "scripts/v20" / wrapper_name
        text = script_text(script) + "\n" + script_text(wrapper)
        drive_paths = DRIVE_PATH_RE.findall(text)
        repo_root_binding = bool(re.search(r"Path\(__file__\)\.resolve\(\)\.parents\[\d+\]", text))
        direct_output_binding = bool(re.search(r"\b(ROOT|CONSOLIDATION|OPS|READ_CENTER)\s*=", text)) and bool(re.search(r"\bOUT_[A-Z0-9_]+\s*=", text))
        stage_detected = bool(drive_paths) or (repo_root_binding and direct_output_binding)
        detected = detected or stage_detected
        rows.append({
            "stage_name": stage,
            "script_path": script.resolve().relative_to(root.resolve()).as_posix() if script.exists() else f"scripts/v20/{script_name}",
            "wrapper_path": wrapper.resolve().relative_to(root.resolve()).as_posix() if wrapper.exists() else f"scripts/v20/{wrapper_name}",
            "attempted": "FALSE",
            "status": "BLOCKED_ABSOLUTE_PRODUCTION_PATH_BINDING" if stage_detected else "NOT_ATTEMPTED",
            "exit_code": "",
            "produced_file_count": "0",
            "produced_files": "",
            "as_of_date": "",
            "eligible_row_count": "",
            "error": "hardcoded drive path or script-file-derived production ROOT output binding detected" if stage_detected else "",
        })
    return detected, rows


def create_staging_workspace(root: Path) -> tuple[Path, Path]:
    staging_root = root / "outputs/v20/staging/V20_16_R3B_CURRENT_LINEAGE_RERUN"
    workspace = staging_root / "workspace"
    if workspace.exists():
        shutil.rmtree(workspace)
    for rel in ("scripts/v20", "outputs/v20/consolidation", "outputs/v20/ops", "outputs/v20/read_center"):
        src = root / rel
        dst = workspace / rel
        if src.exists():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            dst.mkdir(parents=True, exist_ok=True)
    return staging_root, workspace


def staged_files(workspace: Path) -> dict[str, str]:
    base = workspace / "outputs/v20"
    if not base.exists():
        return {}
    return {
        path.resolve().relative_to(workspace.resolve()).as_posix(): file_hash(path)
        for path in base.rglob("*") if path.is_file()
    }


def run_staged_chain(workspace: Path) -> tuple[list[dict[str, object]], list[dict[str, object]], bool, str, str]:
    results: list[dict[str, object]] = []
    before = staged_files(workspace)
    completed = True
    earliest_stage = ""
    earliest_reason = ""
    for stage, script_name, wrapper_name, _, output_rel in STAGES:
        script_rel = f"scripts/v20/{script_name}"
        script = workspace / script_rel
        before_stage = staged_files(workspace)
        if not script.exists():
            completed = False
            earliest_stage = earliest_stage or stage
            earliest_reason = earliest_reason or "SCRIPT_MISSING_IN_STAGING_WORKSPACE"
            results.append({
                "stage_name": stage, "script_path": script_rel, "wrapper_path": f"scripts/v20/{wrapper_name}",
                "attempted": "FALSE", "status": "FAILED", "exit_code": "",
                "produced_file_count": "0", "produced_files": "", "as_of_date": "",
                "eligible_row_count": "", "error": "script missing in staging workspace",
            })
            break
        proc = subprocess.run(
            [sys.executable, script_rel],
            cwd=workspace,
            text=True,
            capture_output=True,
            timeout=300,
        )
        after_stage = staged_files(workspace)
        produced = sorted(path for path in set(after_stage) if before_stage.get(path) != after_stage.get(path))
        rows, _ = read_csv(workspace / output_rel)
        status = "PASS" if proc.returncode == 0 else "FAILED"
        error = (proc.stderr or proc.stdout or "").strip().replace("\r", " ").replace("\n", " ")[:1000]
        results.append({
            "stage_name": stage, "script_path": script_rel, "wrapper_path": f"scripts/v20/{wrapper_name}",
            "attempted": "TRUE", "status": status, "exit_code": str(proc.returncode),
            "produced_file_count": str(len(produced)), "produced_files": "|".join(produced),
            "as_of_date": unique_date(rows), "eligible_row_count": str(eligible_count(rows)),
            "error": "" if proc.returncode == 0 else error,
        })
        if proc.returncode != 0:
            completed = False
            earliest_stage = stage
            earliest_reason = error or "STAGED_SCRIPT_EXITED_NONZERO"
            break
    manifest = output_manifest(workspace, before)
    return results, manifest, completed, earliest_stage, earliest_reason


def output_manifest(workspace: Path, before: dict[str, str] | None = None) -> list[dict[str, object]]:
    before = before or {}
    now = utc_now()
    rows: list[dict[str, object]] = []
    for path in sorted((workspace / "outputs/v20").rglob("*")):
        if not path.is_file():
            continue
        rel = path.resolve().relative_to(workspace.resolve()).as_posix()
        if before and before.get(rel) == file_hash(path):
            continue
        csv_rows, _ = read_csv(path) if path.suffix.lower() == ".csv" else ([], [])
        rows.append({
            "relative_path": rel,
            "size_bytes": path.stat().st_size,
            "sha256": file_hash(path),
            "row_count": len(csv_rows) if path.suffix.lower() == ".csv" else "",
            "as_of_date": unique_date(csv_rows),
            "eligible_row_count": eligible_count(csv_rows) if path.suffix.lower() == ".csv" else "",
            "stage_hint": path.name.split("_")[0] + "_" + path.name.split("_")[1] if path.name.startswith("V20_") and len(path.name.split("_")) > 1 else "",
            "created_at_utc": now,
        })
    return rows


def validate_staged(workspace: Path, expected_date: str, expected_count: int) -> tuple[bool, str, str, str]:
    gate_rows, _ = read_csv(workspace / "outputs/v20/consolidation/V20_16_GATE_DECISION.csv")
    v8_rows, _ = read_csv(workspace / "outputs/v20/consolidation/V20_8_NORMALIZED_RESEARCH_DATASET.csv")
    score_rows, score_fields = read_csv(workspace / "outputs/v20/consolidation/V20_15_LIMITED_FACTOR_SCORE_LAYER.csv")
    date = unique_date(v8_rows)
    count = clean(gate_rows[0].get("eligible_row_count")) if gate_rows else str(eligible_count(v8_rows))
    if not count.isdigit():
        count = str(eligible_count(v8_rows))
    required_score_fields = {"ticker", "factor_score_value", "research_only_flag", "official_use_allowed"}
    duplicate_keys = len({(clean(r.get("ticker")), clean(r.get("effective_observation_date"))) for r in v8_rows}) != len(v8_rows)
    factors_present = not score_rows or required_score_fields.issubset(set(score_fields))
    no_fabrication_signal = all(clean(row.get("factor_score_value")) for row in score_rows) if score_rows else True
    passed = (
        date == expected_date and int(count) == expected_count and not duplicate_keys
        and factors_present and no_fabrication_signal
    )
    delta = str(int(count) - expected_count) if count.isdigit() else ""
    return passed, date, count, delta


def base_summary(
    root: Path,
    r3a: dict[str, str],
    staging_root: Path,
    final_status: str,
    decision: str,
    certified_date: str = "",
    certified_count: str = "",
    production_date: str = "",
    production_count: str = "",
) -> dict[str, object]:
    return {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "source_v20_16_r3a_status": clean(r3a.get("final_status")) or "NOT_AVAILABLE",
        "source_v20_16_r3a_decision": clean(r3a.get("decision")) or "NOT_AVAILABLE",
        "certified_v20_7x_as_of_date": certified_date,
        "certified_v20_7x_eligible_row_count": certified_count,
        "production_downstream_as_of_date_before": production_date,
        "production_downstream_eligible_row_count_before": production_count,
        "staging_workspace_path": staging_root.resolve().relative_to(root.resolve()).as_posix() if staging_root else "",
        "staging_workspace_created": "FALSE",
        "absolute_path_binding_detected": "FALSE",
        "relative_path_staging_supported": "FALSE",
        "staged_rerun_attempted": "FALSE",
        "staged_rerun_completed": "FALSE",
        "earliest_failed_stage": "",
        "earliest_failure_reason": "",
        "staged_downstream_as_of_date": "",
        "staged_eligible_row_count": "",
        "expected_eligible_row_count": certified_count,
        "expected_vs_staged_delta": "",
        "staged_reconciliation_pass": "FALSE",
        "production_v20_8_to_v20_16_outputs_mutated": "FALSE",
        "certified_v20_7x_outputs_mutated": "FALSE",
        "protected_outputs_mutated": "FALSE",
        "protected_output_mutation_count": "0",
        "official_activation_allowed": "FALSE",
        "official_recommendation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "research_only": "TRUE",
        "recommended_next_stage": "",
        "created_at_utc": utc_now(),
    }


def render_report(summary: dict[str, object], results: list[dict[str, object]]) -> str:
    result_lines = "\n".join(
        f"- {row['stage_name']}: {row['status']} {row.get('error', '')}".rstrip()
        for row in results
    ) or "- NONE"
    return f"""# V20.16-R3B Safe Staged Rerun Wrapper

- final_status: {summary['final_status']}
- decision: {summary['decision']}
- staging_workspace_path: {summary['staging_workspace_path']}
- absolute_path_binding_detected: {summary['absolute_path_binding_detected']}
- relative_path_staging_supported: {summary['relative_path_staging_supported']}
- staged_rerun_attempted: {summary['staged_rerun_attempted']}
- staged_rerun_completed: {summary['staged_rerun_completed']}
- staged_reconciliation_pass: {summary['staged_reconciliation_pass']}
- production_v20_8_to_v20_16_outputs_mutated: {summary['production_v20_8_to_v20_16_outputs_mutated']}
- certified_v20_7x_outputs_mutated: {summary['certified_v20_7x_outputs_mutated']}
- protected_outputs_mutated: {summary['protected_outputs_mutated']}
- recommended_next_stage: {summary['recommended_next_stage']}

## Stage Results

{result_lines}

This stage is staging-only. It does not commit staged outputs to production and
keeps all official, broker, and trade-action permissions FALSE.
"""


def run_wrapper(root: Path) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    root = root.resolve()
    diagnostics = root / "outputs/v20/diagnostics"
    staging_root = root / "outputs/v20/staging/V20_16_R3B_CURRENT_LINEAGE_RERUN"
    r3a, r3a_valid = validate_r3a(root)
    v7x_path, certified_date, certified_count, v7x_valid = certified_v7x_state(root)
    observed_production_date, observed_production_count = current_downstream_state(root)
    production_date = clean(r3a.get("downstream_v20_8_to_v20_16_as_of_date_current")) or observed_production_date
    production_count = clean(r3a.get("current_downstream_eligible_row_count")) or observed_production_count

    before_production = snapshot(root, production_matcher)
    before_v7x = snapshot(root, v7x_matcher)
    before_protected = snapshot(root, protected_matcher)

    stage_results: list[dict[str, object]] = []
    manifest: list[dict[str, object]] = []
    summary = base_summary(
        root, r3a, staging_root, BLOCKED_R3A, "BLOCK_R3A_INPUT_MISSING_OR_INVALID",
        certified_date, certified_count, production_date, production_count,
    )

    if not r3a_valid:
        summary["recommended_next_stage"] = "V20.16-R3A_SAFE_RERUN_EXECUTION_FAILURE_FORENSIC_AND_WRAPPER_PLAN"
    elif not v7x_valid or not v7x_path.exists():
        summary["final_status"] = BLOCKED_V7X
        summary["decision"] = "BLOCK_CERTIFIED_V20_7X_INPUT_MISSING_OR_INVALID"
        summary["recommended_next_stage"] = "V20.7X-R2_CURRENT_LINEAGE_CERTIFICATION_REFRESH_COMMIT"
    else:
        absolute_detected, audit_rows = absolute_binding_audit(root)
        stage_results = audit_rows
        summary["absolute_path_binding_detected"] = tf(absolute_detected)
        try:
            staging_root, workspace = create_staging_workspace(root)
            summary["staging_workspace_created"] = "TRUE"
            summary["staging_workspace_path"] = staging_root.resolve().relative_to(root.resolve()).as_posix()
        except Exception as exc:
            summary["final_status"] = BLOCKED_WORKSPACE
            summary["decision"] = "BLOCK_STAGING_WORKSPACE_CREATION_FAILED"
            summary["earliest_failure_reason"] = clean(exc)
            summary["recommended_next_stage"] = "V20.16-R3B_STAGING_WORKSPACE_REPAIR"
            workspace = None  # type: ignore[assignment]
        else:
            if absolute_detected:
                summary["final_status"] = BLOCKED_ABSOLUTE
                summary["decision"] = "BLOCK_STAGED_RERUN_ABSOLUTE_PRODUCTION_PATH_BINDING"
                summary["earliest_failed_stage"] = next((clean(r["stage_name"]) for r in stage_results if clean(r.get("status")) == "BLOCKED_ABSOLUTE_PRODUCTION_PATH_BINDING"), "")
                summary["earliest_failure_reason"] = "ABSOLUTE_PRODUCTION_PATH_BINDING_DETECTED_IN_DOWNSTREAM_SCRIPT_OR_WRAPPER"
                summary["recommended_next_stage"] = "V20.8-R1_RELATIVE_PATH_AND_STAGING_CONTRACT_REPAIR"
            else:
                summary["relative_path_staging_supported"] = "TRUE"
                summary["staged_rerun_attempted"] = "TRUE"
                stage_results, manifest, completed, failed_stage, failed_reason = run_staged_chain(workspace)
                summary["staged_rerun_completed"] = tf(completed)
                if not completed:
                    summary["final_status"] = PARTIAL_STAGE_FAILED
                    summary["decision"] = "STAGED_RERUN_STARTED_STAGE_FAILED"
                    summary["earliest_failed_stage"] = failed_stage
                    summary["earliest_failure_reason"] = failed_reason
                    repair_stage = failed_stage.replace(".", "_") if failed_stage else "V20_8"
                    summary["recommended_next_stage"] = f"{repair_stage}-R1_CERTIFIED_INPUT_BINDING_AND_STAGING_CONTRACT_REPAIR"
                else:
                    expected = int(certified_count)
                    recon, staged_date, staged_count, delta = validate_staged(workspace, certified_date, expected)
                    summary["staged_downstream_as_of_date"] = staged_date
                    summary["staged_eligible_row_count"] = staged_count
                    summary["expected_vs_staged_delta"] = delta
                    summary["staged_reconciliation_pass"] = tf(recon)
                    if recon:
                        summary["final_status"] = PASS_STATUS
                        summary["decision"] = "SAFE_STAGED_RERUN_COMPLETED_RECONCILED"
                        summary["recommended_next_stage"] = "V20.16-R3C_STAGED_DOWNSTREAM_REFRESH_COMMIT"
                    else:
                        summary["final_status"] = BLOCKED_RECON
                        summary["decision"] = "BLOCK_STAGED_RECONCILIATION_FAILED"
                        summary["earliest_failed_stage"] = "V20.16"
                        summary["earliest_failure_reason"] = "STAGED_OUTPUT_COUNT_OR_DATE_RECONCILIATION_FAILED"
                        summary["recommended_next_stage"] = "V20.8-R1_CERTIFIED_INPUT_BINDING_AND_STAGING_CONTRACT_REPAIR"
    production_changes = changed(before_production, snapshot(root, production_matcher))
    v7x_changes = changed(before_v7x, snapshot(root, v7x_matcher))
    protected_changes = changed(before_protected, snapshot(root, protected_matcher))
    if protected_changes:
        summary["final_status"] = BLOCKED_PROTECTED_MUTATION
        summary["decision"] = "BLOCK_PROTECTED_OUTPUT_MUTATION_DETECTED"
    elif production_changes or v7x_changes:
        summary["final_status"] = BLOCKED_PRODUCTION_MUTATION
        summary["decision"] = "BLOCK_PRODUCTION_OUTPUT_MUTATION_DETECTED"
    summary["production_v20_8_to_v20_16_outputs_mutated"] = tf(bool(production_changes))
    summary["certified_v20_7x_outputs_mutated"] = tf(bool(v7x_changes))
    summary["protected_outputs_mutated"] = tf(bool(protected_changes))
    summary["protected_output_mutation_count"] = str(len(protected_changes))

    write_csv(diagnostics / "V20_16_R3B_SAFE_STAGED_RERUN_WRAPPER_SUMMARY.csv", [summary], SUMMARY_FIELDS)
    write_csv(diagnostics / "V20_16_R3B_STAGED_RERUN_STAGE_RESULTS.csv", stage_results, STAGE_RESULT_FIELDS)
    write_csv(diagnostics / "V20_16_R3B_STAGED_OUTPUT_MANIFEST.csv", manifest, MANIFEST_FIELDS)
    report_path = root / "outputs/v20/read_center/V20_16_R3B_SAFE_STAGED_RERUN_WRAPPER_REPORT.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(summary, stage_results), encoding="utf-8")
    return summary, stage_results, manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    summary, _, _ = run_wrapper(args.root)
    for field in SUMMARY_FIELDS:
        print(f"{field.upper()}={summary.get(field, '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
