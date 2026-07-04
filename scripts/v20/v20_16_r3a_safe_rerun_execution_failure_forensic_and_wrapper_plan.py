#!/usr/bin/env python
"""V20.16-R3A safe-rerun execution failure forensic and wrapper plan.

Static, non-mutating audit of the V20.8-V20.16 execution contracts.
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
STAGE = "V20.16-R3A_SAFE_RERUN_EXECUTION_FAILURE_FORENSIC_AND_WRAPPER_PLAN"
PASS_STATUS = "PASS_V20_16_R3A_FAILURE_ROOT_CAUSE_IDENTIFIED_WRAPPER_PLAN_READY"
PARTIAL_MULTIPLE = "PARTIAL_PASS_V20_16_R3A_FAILURE_CONFIRMED_MULTIPLE_UNSAFE_CONTRACTS"
PARTIAL_MANUAL = "PARTIAL_PASS_V20_16_R3A_FAILURE_CONFIRMED_MANUAL_LOG_REVIEW_REQUIRED"
PASS_NONE = "PASS_V20_16_R3A_NO_EXECUTION_FAILURE_FOUND"
BLOCKED_INPUT = "BLOCKED_V20_16_R3A_INPUT_MISSING_OR_INVALID"
BLOCKED_PRODUCTION = "BLOCKED_V20_16_R3A_PRODUCTION_OUTPUT_MUTATION_DETECTED"
BLOCKED_PROTECTED = "BLOCKED_V20_16_R3A_PROTECTED_OUTPUT_MUTATION_DETECTED"

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "source_v20_7x_r2_status",
    "source_v20_16_r3_status", "current_v20_7v_as_of_date",
    "certified_v20_7x_as_of_date_after", "certified_v20_7x_eligible_row_count_after",
    "downstream_v20_8_to_v20_16_as_of_date_current",
    "expected_eligible_row_count", "current_downstream_eligible_row_count",
    "execution_failure_confirmed", "suspected_failure_stage",
    "suspected_failure_reason", "failure_reason_confidence",
    "safe_wrapper_available", "recommended_next_stage",
    "production_v20_8_to_v20_16_outputs_mutated",
    "certified_v20_7x_outputs_mutated", "protected_outputs_mutated",
    "protected_output_mutation_count", "official_activation_allowed",
    "official_recommendation_allowed", "official_ranking_mutation_allowed",
    "official_weight_mutation_allowed", "broker_execution_allowed",
    "trade_action_allowed", "research_only", "created_at_utc",
]

DEPENDENCY_FIELDS = [
    "stage_name", "script_path", "wrapper_path", "expected_input_path",
    "actual_input_path", "expected_output_path", "currently_existing_output_path",
    "current_output_as_of_date", "row_count", "safe_no_write_mode_available",
    "production_write_behavior", "protected_output_risk",
    "can_be_invoked_by_r3_safely", "notes",
]

CONTRACT_FIELDS = [
    "stage_name", "has_python_script", "has_powershell_wrapper",
    "supports_input_override", "supports_output_override_or_staging",
    "supports_dry_run", "writes_production_outputs_directly",
    "requires_certified_v20_7x", "reads_current_certified_v20_7x",
    "still_points_to_stale_june15_input", "missing_required_input",
    "blocker_reason",
]

STAGES = [
    ("V20.8", "v20_8_normalized_research_dataset_construction.py", "run_v20_8_normalized_research_dataset_construction.ps1",
     "outputs/v20/consolidation/V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv", "outputs/v20/consolidation/V20_8_NORMALIZED_RESEARCH_DATASET.csv"),
    ("V20.9", "v20_9_factor_research_dataset_preparation.py", "run_v20_9_factor_research_dataset_preparation.ps1",
     "outputs/v20/consolidation/V20_8_NORMALIZED_RESEARCH_DATASET.csv", "outputs/v20/consolidation/V20_9_FACTOR_RESEARCH_BASE_DATASET.csv"),
    ("V20.10", "v20_10_factor_source_attachment_or_availability_audit.py", "run_v20_10_factor_source_attachment_or_availability_audit.ps1",
     "outputs/v20/consolidation/V20_9_FACTOR_RESEARCH_BASE_DATASET.csv", "outputs/v20/consolidation/V20_10_VALIDATION_SUMMARY.csv"),
    ("V20.11", "v20_11_factor_source_attachment_plan_or_first_attachable_factor_layer.py", "run_v20_11_factor_source_attachment_plan_or_first_attachable_factor_layer.ps1",
     "outputs/v20/consolidation/V20_10_GATE_DECISION.csv", "outputs/v20/consolidation/V20_11_FIRST_ATTACHABLE_FACTOR_INPUT_LAYER.csv"),
    ("V20.12", "v20_12_factor_input_layer_review_or_factor_evidence_gate.py", "run_v20_12_factor_input_layer_review_or_factor_evidence_gate.ps1",
     "outputs/v20/consolidation/V20_11_FIRST_ATTACHABLE_FACTOR_INPUT_LAYER.csv", "outputs/v20/consolidation/V20_12_GATE_DECISION.csv"),
    ("V20.13", "v20_13_first_limited_factor_evidence_layer.py", "run_v20_13_first_limited_factor_evidence_layer.ps1",
     "outputs/v20/consolidation/V20_12_GATE_DECISION.csv", "outputs/v20/consolidation/V20_13_LIMITED_FACTOR_EVIDENCE_LAYER.csv"),
    ("V20.14", "v20_14_factor_evidence_review_or_factor_score_gate.py", "run_v20_14_factor_evidence_review_or_factor_score_gate.ps1",
     "outputs/v20/consolidation/V20_13_LIMITED_FACTOR_EVIDENCE_LAYER.csv", "outputs/v20/consolidation/V20_14_GATE_DECISION.csv"),
    ("V20.15", "v20_15_first_limited_factor_score_layer.py", "run_v20_15_first_limited_factor_score_layer.ps1",
     "outputs/v20/consolidation/V20_14_GATE_DECISION.csv", "outputs/v20/consolidation/V20_15_LIMITED_FACTOR_SCORE_LAYER.csv"),
    ("V20.16", "v20_16_factor_score_review_or_backtest_readiness_gate.py", "run_v20_16_factor_score_review_or_backtest_readiness_gate.ps1",
     "outputs/v20/consolidation/V20_15_LIMITED_FACTOR_SCORE_LAYER.csv", "outputs/v20/consolidation/V20_16_GATE_DECISION.csv"),
]

PROTECTED_RE = re.compile(
    r"(authoritative.*official.*rank|official.*weight|official.*recommend|"
    r"broker|trade[_ .-]*action|real[_ .-]*book)", re.IGNORECASE
)
PRODUCTION_RE = re.compile(r"^V20_(?:8|9|10|11|12|13|14|15|16)(?:_|\\.)", re.IGNORECASE)
V7X_RE = re.compile(r"^V20_7X_", re.IGNORECASE)


def clean(value: object) -> str:
    return str(value or "").strip()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists() or path.stat().st_size == 0:
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


def unique_date(rows: list[dict[str, str]]) -> str:
    fields = (
        "effective_observation_date", "observation_date", "as_of_date",
        "signal_date", "latest_price_date", "effective_price_date",
    )
    dates = sorted({
        clean(row.get(field))[:10] for row in rows for field in fields
        if clean(row.get(field))
    })
    return dates[-1] if dates else ""


def script_contract(script: Path, wrapper: Path) -> dict[str, bool]:
    script_text = script.read_text(encoding="utf-8", errors="replace") if script.exists() else ""
    wrapper_text = wrapper.read_text(encoding="utf-8", errors="replace") if wrapper.exists() else ""
    combined = script_text + "\n" + wrapper_text
    input_override = bool(re.search(r"(--input|input_override|source_path\s*=.*arg|param\s*\([^)]*Input)", combined, re.I | re.S))
    output_override = bool(re.search(r"(--output|output_override|output_dir\s*=.*arg|staging_dir|param\s*\([^)]*Output)", combined, re.I | re.S))
    dry_run = bool(re.search(r"(--dry-run|--dry_run|\[switch\]\s*\$DryRun|dry_run\s*=.*arg)", combined, re.I))
    direct_write = bool(re.search(r"OUT_[A-Z_]+\s*=\s*CONSOLIDATION\s*/|write_csv\(OUT_|write_text\(OUT_", script_text))
    requires_v7x = "V20_7X" in script_text
    reads_current_v7x = "V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv" in script_text
    return {
        "input_override": input_override,
        "output_override": output_override,
        "dry_run": dry_run,
        "direct_write": direct_write,
        "requires_v7x": requires_v7x,
        "reads_current_v7x": reads_current_v7x,
    }


def classify_contract(
    has_script: bool,
    has_wrapper: bool,
    contract: dict[str, bool],
    stale_binding: bool,
    missing_input: bool,
) -> tuple[str, str]:
    if not has_wrapper:
        return "WRAPPER_MISSING", "HIGH"
    if not has_script:
        return "STAGE_CONTRACT_INCOMPATIBLE", "HIGH"
    if missing_input:
        return "REQUIRED_INPUT_MISSING", "HIGH"
    if stale_binding and contract["requires_v7x"] and not contract["reads_current_v7x"]:
        return "CERTIFIED_V20_7X_NOT_READ_BY_DOWNSTREAM", "HIGH"
    if stale_binding and contract["reads_current_v7x"]:
        return "SCRIPT_STILL_POINTS_TO_STALE_INPUT", "MEDIUM"
    if not contract["input_override"]:
        return "INPUT_OVERRIDE_UNSUPPORTED", "HIGH"
    if not contract["output_override"]:
        return "OUTPUT_STAGING_UNSUPPORTED", "HIGH"
    if contract["direct_write"]:
        return "SCRIPT_WRITES_PRODUCTION_DIRECTLY", "HIGH"
    return "", ""


def audit_stage(root: Path, definition: tuple[str, str, str, str, str], certified_date: str) -> tuple[dict[str, object], dict[str, object]]:
    stage, script_name, wrapper_name, input_rel, output_rel = definition
    script = root / "scripts/v20" / script_name
    wrapper = root / "scripts/v20" / wrapper_name
    input_path = root / input_rel
    output_path = root / output_rel
    rows, _ = read_csv(output_path)
    output_date = unique_date(rows)
    contract = script_contract(script, wrapper)
    stale_binding = bool(
        stage == "V20.8" and certified_date and output_date and output_date < certified_date
        and contract["requires_v7x"] and not contract["reads_current_v7x"]
    )
    missing_input = not input_path.exists()
    reason, _ = classify_contract(script.exists(), wrapper.exists(), contract, stale_binding, missing_input)
    safely_invokable = bool(
        script.exists() and wrapper.exists() and not missing_input
        and contract["input_override"] and contract["output_override"]
        and not contract["direct_write"]
    )
    dependency = {
        "stage_name": stage,
        "script_path": script.resolve().relative_to(root.resolve()).as_posix(),
        "wrapper_path": wrapper.resolve().relative_to(root.resolve()).as_posix(),
        "expected_input_path": input_rel,
        "actual_input_path": input_rel if input_path.exists() else "MISSING",
        "expected_output_path": output_rel,
        "currently_existing_output_path": output_rel if output_path.exists() else "MISSING",
        "current_output_as_of_date": output_date,
        "row_count": len(rows),
        "safe_no_write_mode_available": "TRUE" if contract["dry_run"] or contract["output_override"] else "FALSE",
        "production_write_behavior": "DIRECT_PRODUCTION_WRITE" if contract["direct_write"] else "CONTROLLED_OR_UNKNOWN",
        "protected_output_risk": "LOW_RESEARCH_ONLY_PATHS_BUT_NO_TRANSACTIONAL_STAGING" if contract["direct_write"] else "LOW",
        "can_be_invoked_by_r3_safely": "TRUE" if safely_invokable else "FALSE",
        "notes": reason or "No static blocker detected.",
    }
    execution = {
        "stage_name": stage,
        "has_python_script": "TRUE" if script.exists() else "FALSE",
        "has_powershell_wrapper": "TRUE" if wrapper.exists() else "FALSE",
        "supports_input_override": "TRUE" if contract["input_override"] else "FALSE",
        "supports_output_override_or_staging": "TRUE" if contract["output_override"] else "FALSE",
        "supports_dry_run": "TRUE" if contract["dry_run"] else "FALSE",
        "writes_production_outputs_directly": "TRUE" if contract["direct_write"] else "FALSE",
        "requires_certified_v20_7x": "TRUE" if contract["requires_v7x"] else "FALSE",
        "reads_current_certified_v20_7x": "TRUE" if contract["reads_current_v7x"] else "FALSE",
        "still_points_to_stale_june15_input": "TRUE" if stale_binding else "FALSE",
        "missing_required_input": "TRUE" if missing_input else "FALSE",
        "blocker_reason": reason,
    }
    return dependency, execution


def run_forensic(
    root: Path,
    production_mutation_hook: Callable[[], None] | None = None,
    protected_mutation_hook: Callable[[], None] | None = None,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    d = root / "outputs/v20/diagnostics"
    c = root / "outputs/v20/consolidation"
    v7x = read_first(d / "V20_7X_R2_CURRENT_LINEAGE_CERTIFICATION_REFRESH_COMMIT_SUMMARY.csv")
    r3 = read_first(d / "V20_16_R3_CURRENT_LINEAGE_DOWNSTREAM_REFRESH_COMMIT_SUMMARY.csv")
    v7x_valid = (
        clean(v7x.get("final_status")) == "PASS_V20_7X_R2_CURRENT_LINEAGE_CERTIFICATION_REFRESH_COMMITTED"
        and clean(v7x.get("certification_commit_pass")).upper() == "TRUE"
    )
    r3_failure = (
        clean(r3.get("final_status")) == "BLOCKED_V20_16_R3_SAFE_RERUN_PATH_UNAVAILABLE"
        and clean(r3.get("decision")) == "BLOCK_COMMIT_SAFE_RERUN_EXECUTION_FAILED"
    )
    inputs_valid = bool(v7x and r3)
    certified_date = clean(v7x.get("certified_v20_7x_as_of_date_after"))
    certified_count = clean(v7x.get("certified_v20_7x_eligible_row_count_after"))

    before_production = snapshot(root, lambda path: bool(PRODUCTION_RE.match(path.name)))
    before_v7x = snapshot(root, lambda path: bool(V7X_RE.match(path.name)))
    before_protected = snapshot(
        root,
        lambda path: "V20_16_R3A_SAFE_RERUN" not in path.name and bool(PROTECTED_RE.search(path.name)),
    )

    dependency_rows, contract_rows = [], []
    for definition in STAGES:
        dependency, contract = audit_stage(root, definition, certified_date)
        dependency_rows.append(dependency)
        contract_rows.append(contract)

    blockers = [
        (row["stage_name"], row["blocker_reason"])
        for row in contract_rows if clean(row["blocker_reason"])
    ]
    earliest_stage = blockers[0][0] if blockers else ""
    earliest_reason = blockers[0][1] if blockers else ""
    _, confidence = classify_contract(
        contract_rows[0]["has_python_script"] == "TRUE",
        contract_rows[0]["has_powershell_wrapper"] == "TRUE",
        {
            "input_override": contract_rows[0]["supports_input_override"] == "TRUE",
            "output_override": contract_rows[0]["supports_output_override_or_staging"] == "TRUE",
            "dry_run": contract_rows[0]["supports_dry_run"] == "TRUE",
            "direct_write": contract_rows[0]["writes_production_outputs_directly"] == "TRUE",
            "requires_v7x": contract_rows[0]["requires_certified_v20_7x"] == "TRUE",
            "reads_current_v7x": contract_rows[0]["reads_current_certified_v20_7x"] == "TRUE",
        },
        contract_rows[0]["still_points_to_stale_june15_input"] == "TRUE",
        contract_rows[0]["missing_required_input"] == "TRUE",
    )
    unsafe_count = sum(row["can_be_invoked_by_r3_safely"] == "FALSE" for row in dependency_rows)
    safe_wrapper = unsafe_count == 0

    gate = read_first(c / "V20_16_GATE_DECISION.csv")
    downstream_count = clean(gate.get("eligible_row_count"))
    v8_rows, _ = read_csv(c / "V20_8_NORMALIZED_RESEARCH_DATASET.csv")
    downstream_date = unique_date(v8_rows)

    if production_mutation_hook:
        production_mutation_hook()
    if protected_mutation_hook:
        protected_mutation_hook()
    production_changes = changed(before_production, snapshot(root, lambda path: bool(PRODUCTION_RE.match(path.name))))
    v7x_changes = changed(before_v7x, snapshot(root, lambda path: bool(V7X_RE.match(path.name))))
    protected_changes = changed(
        before_protected,
        snapshot(root, lambda path: "V20_16_R3A_SAFE_RERUN" not in path.name and bool(PROTECTED_RE.search(path.name))),
    )

    if protected_changes:
        final_status = BLOCKED_PROTECTED
        decision = "BLOCK_FORENSIC_PROTECTED_OUTPUT_MUTATION_DETECTED"
    elif production_changes or v7x_changes:
        final_status = BLOCKED_PRODUCTION
        decision = "BLOCK_FORENSIC_PRODUCTION_OUTPUT_MUTATION_DETECTED"
    elif not inputs_valid or not v7x_valid:
        final_status = BLOCKED_INPUT
        decision = "BLOCK_FORENSIC_REQUIRED_INPUT_MISSING_OR_INVALID"
    elif not r3_failure:
        final_status = PASS_NONE
        decision = "NO_SAFE_RERUN_EXECUTION_FAILURE_FOUND"
    elif not blockers:
        final_status = PARTIAL_MANUAL
        decision = "EXECUTION_FAILURE_REQUIRES_MANUAL_LOG_REVIEW"
        earliest_reason = "EXECUTION_ERROR_REQUIRES_LOG_INSPECTION"
        confidence = "LOW"
    elif unsafe_count > 1:
        final_status = PARTIAL_MULTIPLE
        decision = "MULTIPLE_UNSAFE_STAGE_CONTRACTS_REQUIRE_STAGED_WRAPPER"
    else:
        final_status = PASS_STATUS
        decision = "FAILURE_ROOT_CAUSE_IDENTIFIED_SAFE_WRAPPER_PLAN_READY"

    if blockers:
        recommended = "V20.16-R3B_SAFE_STAGED_RERUN_WRAPPER"
    elif r3_failure:
        recommended = "V20.16-R3_MANUAL_LOG_REVIEW_REQUIRED"
    else:
        recommended = "V20.16_R3_RETRY_AFTER_FIXING_STAGE_CONTRACT"

    summary = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "source_v20_7x_r2_status": clean(v7x.get("final_status")) or "NOT_AVAILABLE",
        "source_v20_16_r3_status": clean(r3.get("final_status")) or "NOT_AVAILABLE",
        "current_v20_7v_as_of_date": clean(v7x.get("current_v20_7v_as_of_date")),
        "certified_v20_7x_as_of_date_after": certified_date,
        "certified_v20_7x_eligible_row_count_after": certified_count,
        "downstream_v20_8_to_v20_16_as_of_date_current": downstream_date,
        "expected_eligible_row_count": clean(r3.get("expected_eligible_row_count")),
        "current_downstream_eligible_row_count": downstream_count,
        "execution_failure_confirmed": "TRUE" if r3_failure else "FALSE",
        "suspected_failure_stage": earliest_stage,
        "suspected_failure_reason": earliest_reason,
        "failure_reason_confidence": confidence or "LOW",
        "safe_wrapper_available": "TRUE" if safe_wrapper else "FALSE",
        "recommended_next_stage": recommended,
        "production_v20_8_to_v20_16_outputs_mutated": "TRUE" if production_changes else "FALSE",
        "certified_v20_7x_outputs_mutated": "TRUE" if v7x_changes else "FALSE",
        "protected_outputs_mutated": "TRUE" if protected_changes else "FALSE",
        "protected_output_mutation_count": len(protected_changes),
        "official_activation_allowed": "FALSE",
        "official_recommendation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "research_only": "TRUE",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    return summary, dependency_rows, contract_rows


def render_report(summary: dict[str, object], contracts: list[dict[str, object]]) -> str:
    unsafe = "\n".join(
        f"- {row['stage_name']}: {row['blocker_reason']}"
        for row in contracts if clean(row["blocker_reason"])
    ) or "- NONE"
    return f"""# V20.16-R3A Safe Rerun Execution Failure Forensic and Wrapper Plan

## Finding

- final_status: {summary['final_status']}
- decision: {summary['decision']}
- execution_failure_confirmed: {summary['execution_failure_confirmed']}
- suspected_failure_stage: {summary['suspected_failure_stage']}
- suspected_failure_reason: {summary['suspected_failure_reason']}
- failure_reason_confidence: {summary['failure_reason_confidence']}
- safe_wrapper_available: {summary['safe_wrapper_available']}
- recommended_next_stage: {summary['recommended_next_stage']}

## Unsafe Contracts

{unsafe}

## Wrapper Plan

Implement V20.16-R3B as a transactionally staged runner:

1. Copy the certified V20.7X inputs into an isolated staging root.
2. Run V20.8 through V20.16 against staged input/output overrides.
3. Validate all stage gates, counts, lineage dates, IDs, and research-only flags.
4. Atomically promote only V20.8-V20.16 research artifacts after every check passes.
5. Roll back on any failure and verify protected hashes remain unchanged.

The existing scripts cannot provide this contract because they bind repository
paths at import time and write production outputs directly.
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    summary, dependencies, contracts = run_forensic(root)
    diagnostics = root / "outputs/v20/diagnostics"
    write_csv(diagnostics / "V20_16_R3A_SAFE_RERUN_EXECUTION_FAILURE_FORENSIC_SUMMARY.csv", [summary], SUMMARY_FIELDS)
    write_csv(diagnostics / "V20_16_R3A_RERUN_DEPENDENCY_MAP.csv", dependencies, DEPENDENCY_FIELDS)
    write_csv(diagnostics / "V20_16_R3A_STAGE_EXECUTION_CONTRACT_AUDIT.csv", contracts, CONTRACT_FIELDS)
    report_path = root / "outputs/v20/read_center/V20_16_R3A_SAFE_RERUN_EXECUTION_FAILURE_FORENSIC_AND_WRAPPER_PLAN_REPORT.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(summary, contracts), encoding="utf-8")
    for field in (
        "final_status", "decision", "certified_v20_7x_as_of_date_after",
        "certified_v20_7x_eligible_row_count_after",
        "downstream_v20_8_to_v20_16_as_of_date_current",
        "current_downstream_eligible_row_count", "execution_failure_confirmed",
        "suspected_failure_stage", "suspected_failure_reason",
        "failure_reason_confidence", "safe_wrapper_available",
        "recommended_next_stage", "certified_v20_7x_outputs_mutated",
        "production_v20_8_to_v20_16_outputs_mutated",
        "protected_outputs_mutated",
    ):
        print(f"{field.upper()}={summary[field]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
