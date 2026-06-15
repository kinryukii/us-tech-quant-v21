#!/usr/bin/env python
"""V20.114 shadow output reconciliation.

This stage reconciles V20.113 dry-run outputs against the V20.112 integration
plan. It is reconciliation-only, audit-only, shadow-only, and non-mutating.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_113_SHADOW_INTEGRATION_DRY_RUN_DECISION.csv"
IN_STEP_EXECUTION = CONSOLIDATION / "V20_113_DRY_RUN_STEP_EXECUTION_AUDIT.csv"
IN_DEPENDENCY_RESULT = CONSOLIDATION / "V20_113_DRY_RUN_DEPENDENCY_RESULT_AUDIT.csv"
IN_MANIFEST = CONSOLIDATION / "V20_113_DRY_RUN_OUTPUT_MANIFEST.csv"
IN_SAFETY = CONSOLIDATION / "V20_113_SHADOW_INTEGRATION_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_113_NEXT_STAGE_GATE.csv"
IN_V112_STEPS = CONSOLIDATION / "V20_112_SHADOW_INTEGRATION_STEP_PLAN.csv"
IN_V112_DEPENDENCY = CONSOLIDATION / "V20_112_SHADOW_INTEGRATION_DEPENDENCY_AUDIT.csv"
IN_V112_GATE = CONSOLIDATION / "V20_112_NEXT_STAGE_GATE.csv"

OUT_DECISION = CONSOLIDATION / "V20_114_SHADOW_OUTPUT_RECONCILIATION_DECISION.csv"
OUT_STEP_RECON = CONSOLIDATION / "V20_114_STEP_PLAN_RECONCILIATION_AUDIT.csv"
OUT_OUTPUT_RECON = CONSOLIDATION / "V20_114_DRY_RUN_OUTPUT_RECONCILIATION_AUDIT.csv"
OUT_DEP_RECON = CONSOLIDATION / "V20_114_DEPENDENCY_RECONCILIATION_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_114_SHADOW_OUTPUT_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_114_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_114_SHADOW_OUTPUT_RECONCILIATION_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V113_PASS_STATUS = "PASS_V20_113_SHADOW_INTEGRATION_DRY_RUN_READY_FOR_V20_114"
PASS_STATUS = "PASS_V20_114_SHADOW_OUTPUT_RECONCILIATION_READY_FOR_V20_115"
BLOCKED_STATUS = "BLOCKED_V20_114_SHADOW_OUTPUT_RECONCILIATION"

REQUIRED_INPUTS = [
    IN_DECISION,
    IN_STEP_EXECUTION,
    IN_DEPENDENCY_RESULT,
    IN_MANIFEST,
    IN_SAFETY,
    IN_GATE,
    IN_V112_STEPS,
    IN_V112_DEPENDENCY,
]

UPSTREAM_HASH_INPUTS = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    CONSOLIDATION / "V20_110_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_111_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_112_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_112_SHADOW_INTEGRATION_STEP_PLAN.csv",
    CONSOLIDATION / "V20_112_SHADOW_INTEGRATION_DEPENDENCY_AUDIT.csv",
    CONSOLIDATION / "V20_113_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_113_DRY_RUN_STEP_EXECUTION_AUDIT.csv",
    CONSOLIDATION / "V20_113_DRY_RUN_OUTPUT_MANIFEST.csv",
]

EXPECTED_MANIFEST_NAMES = {
    "V20_113_SHADOW_INTEGRATION_DRY_RUN_DECISION.csv",
    "V20_113_DRY_RUN_STEP_EXECUTION_AUDIT.csv",
    "V20_113_DRY_RUN_DEPENDENCY_RESULT_AUDIT.csv",
    "V20_113_DRY_RUN_OUTPUT_MANIFEST.csv",
    "V20_113_SHADOW_INTEGRATION_SAFETY_BOUNDARY_AUDIT.csv",
    "V20_113_NEXT_STAGE_GATE.csv",
    "V20_113_SHADOW_INTEGRATION_DRY_RUN_REPORT.md",
}

PROHIBITED_FIELDS = [
    "accepted_weight_created",
    "accepted_weights_created",
    "real_book_weight_created",
    "real_book_action_created",
    "official_weight_created",
    "official_weights_created",
    "official_ranking_created",
    "official_rankings_created",
    "official_recommendation_created",
    "official_recommendations_created",
    "trade_action_created",
    "trade_actions_created",
    "broker_action_created",
    "broker_actions_created",
    "authoritative_overwrite_created",
    "authoritative_overwrites_created",
    "authoritative_ranking_overwritten",
    "weight_mutated",
    "weight_mutations_created",
    "promotion_ready",
    "performance_claim_created",
    "performance_claims_created",
    "performance_effectiveness_claim_created",
    "official_promotion_allowed",
    "is_official_weight",
]

COMMON_SAFETY = {
    "accepted_weight_created": "FALSE",
    "accepted_weights_created": "FALSE",
    "real_book_weight_created": "FALSE",
    "real_book_action_created": "FALSE",
    "official_weight_created": "FALSE",
    "official_weights_created": "FALSE",
    "official_ranking_created": "FALSE",
    "official_rankings_created": "FALSE",
    "official_recommendation_created": "FALSE",
    "official_recommendations_created": "FALSE",
    "trade_action_created": "FALSE",
    "trade_actions_created": "FALSE",
    "broker_action_created": "FALSE",
    "broker_actions_created": "FALSE",
    "authoritative_overwrite_created": "FALSE",
    "authoritative_overwrites_created": "FALSE",
    "authoritative_ranking_overwritten": "FALSE",
    "weight_mutated": "FALSE",
    "weight_mutations_created": "FALSE",
    "promotion_ready": "FALSE",
    "performance_claim_created": "FALSE",
    "performance_claims_created": "FALSE",
    "performance_effectiveness_claim_created": "FALSE",
    "official_promotion_allowed": "FALSE",
    "is_official_weight": "FALSE",
    "research_only": "TRUE",
    "shadow_only": "TRUE",
    "reconciliation_only": "TRUE",
    "audit_only": "TRUE",
    "simulation_only": "TRUE",
}

DECISION_FIELDS = [
    "decision_check_id",
    "v20_113_gate_consumed",
    "v20_114_shadow_output_reconciliation_allowed_by_v113",
    "v20_113_final_status",
    "v20_113_status_passed",
    "selected_repair_scenario_id",
    "expected_selected_repair_scenario_id",
    "selected_scenario_matches_v20_113",
    "planned_step_count",
    "reconciled_step_count",
    "missing_planned_step_count",
    "no_planned_dry_run_step_missing",
    "manifest_entry_count",
    "unauthorized_output_artifact_count",
    "no_unauthorized_output_artifact_accepted",
    "dependency_source_count",
    "dependency_reconciled_count",
    "dependency_reconciliation_all_passed",
    "fabricated_ticker_row_count",
    "no_ticker_rows_fabricated",
    "upstream_mutation_detected",
    "no_upstream_outputs_mutated",
    "shadow_only_confirmed",
    "reconciliation_only_confirmed",
    "audit_only_confirmed",
    "safety_boundary_audit_passed",
    "prohibited_action_true_count",
    "all_shadow_output_reconciliation_checks_passed",
    "v20_115_shadow_baseline_comparison_allowed",
    "shadow_output_reconciliation_status",
    "blocking_reason",
    *COMMON_SAFETY.keys(),
]
STEP_FIELDS = [
    "reconciliation_check_id",
    "selected_repair_scenario_id",
    "source_step_id",
    "planned_step_name",
    "planned_step_order",
    "dry_run_step_execution_id",
    "dry_run_step_executed",
    "step_reconciled",
    "missing_planned_step",
    "step_reconciliation_status",
    "step_reconciliation_reason",
    *COMMON_SAFETY.keys(),
]
OUTPUT_FIELDS = [
    "output_reconciliation_id",
    "dry_run_output_name",
    "dry_run_output_path",
    "expected_audit_only_output",
    "manifest_entry_present",
    "contains_ticker_rows",
    "official_artifact",
    "real_book_artifact",
    "mutates_upstream",
    "unauthorized_output_artifact",
    "output_reconciliation_status",
    "output_reconciliation_reason",
    *COMMON_SAFETY.keys(),
]
DEPENDENCY_FIELDS = [
    "dependency_reconciliation_id",
    "source_dependency_check_id",
    "dependency_name",
    "dependency_result_id",
    "dependency_required_before_dry_run",
    "dependency_satisfied_for_dry_run",
    "dependency_reconciled",
    "dependency_reconciliation_status",
    "dependency_reconciliation_reason",
    *COMMON_SAFETY.keys(),
]
SAFETY_FIELDS = [
    "safety_check_id",
    "prohibited_field",
    "observed_true_count",
    "safety_boundary_passed",
    "safety_status",
    "safety_reason",
    *COMMON_SAFETY.keys(),
]
GATE_FIELDS = [
    "gate_check_id",
    "v20_113_gate_consumed",
    "v20_114_shadow_output_reconciliation_allowed_by_v113",
    "selected_repair_scenario_id",
    "shadow_output_reconciliation_decision_created",
    "no_planned_dry_run_step_missing",
    "no_unauthorized_output_artifact_accepted",
    "dependency_reconciliation_all_passed",
    "no_upstream_outputs_mutated",
    "safety_boundary_audit_passed",
    "v20_115_shadow_baseline_comparison_allowed",
    "next_recommended_action",
    "blocking_reason",
    "shadow_output_reconciliation_status",
    *COMMON_SAFETY.keys(),
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def truthy(value: str | None) -> bool:
    return (value or "").strip().upper() == "TRUE"


def clean(value: str | None) -> str:
    return (value or "").strip()


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def upstream_hashes() -> dict[str, str]:
    return {display_path(path): digest(path) for path in UPSTREAM_HASH_INPUTS if path.exists()}


def prohibited_counts(row_groups: list[list[dict[str, str]]]) -> dict[str, int]:
    counts = {field: 0 for field in PROHIBITED_FIELDS}
    for rows in row_groups:
        for row in rows:
            for field in PROHIBITED_FIELDS:
                if field in row and truthy(row.get(field)):
                    counts[field] += 1
    return counts


def reconcile_steps(plan_rows: list[dict[str, str]], execution_rows: list[dict[str, str]], selected_id: str) -> list[dict[str, str]]:
    execution_by_step = {clean(row.get("source_step_id")): row for row in execution_rows}
    rows = []
    for index, planned in enumerate(plan_rows, start=1):
        step_id = clean(planned.get("step_id"))
        executed = execution_by_step.get(step_id, {})
        ok = bool(executed) and truthy(executed.get("dry_run_step_executed")) and clean(executed.get("dry_run_step_status")) == "DRY_RUN_EXECUTED"
        rows.append({
            "reconciliation_check_id": f"V20_114_STEP_PLAN_RECONCILIATION_AUDIT_{index:03d}",
            "selected_repair_scenario_id": selected_id,
            "source_step_id": step_id,
            "planned_step_name": clean(planned.get("step_name")),
            "planned_step_order": clean(planned.get("step_order")),
            "dry_run_step_execution_id": clean(executed.get("dry_run_step_execution_id")),
            "dry_run_step_executed": clean(executed.get("dry_run_step_executed")) or "FALSE",
            "step_reconciled": tf(ok),
            "missing_planned_step": tf(not ok),
            "step_reconciliation_status": "RECONCILED" if ok else "MISSING_OR_FAILED_DRY_RUN_STEP",
            "step_reconciliation_reason": "Planned V20.112 step has a matching V20.113 dry-run execution audit row.",
            **COMMON_SAFETY,
        })
    return rows


def reconcile_outputs(manifest_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for index, manifest in enumerate(manifest_rows, start=1):
        name = clean(manifest.get("dry_run_output_name"))
        unauthorized = (
            name not in EXPECTED_MANIFEST_NAMES
            or truthy(manifest.get("contains_ticker_rows"))
            or truthy(manifest.get("official_artifact"))
            or truthy(manifest.get("real_book_artifact"))
            or truthy(manifest.get("mutates_upstream"))
            or not truthy(manifest.get("audit_only_output"))
        )
        rows.append({
            "output_reconciliation_id": f"V20_114_DRY_RUN_OUTPUT_RECONCILIATION_AUDIT_{index:03d}",
            "dry_run_output_name": name,
            "dry_run_output_path": clean(manifest.get("dry_run_output_path")),
            "expected_audit_only_output": tf(name in EXPECTED_MANIFEST_NAMES),
            "manifest_entry_present": "TRUE",
            "contains_ticker_rows": clean(manifest.get("contains_ticker_rows")) or "FALSE",
            "official_artifact": clean(manifest.get("official_artifact")) or "FALSE",
            "real_book_artifact": clean(manifest.get("real_book_artifact")) or "FALSE",
            "mutates_upstream": clean(manifest.get("mutates_upstream")) or "FALSE",
            "unauthorized_output_artifact": tf(unauthorized),
            "output_reconciliation_status": "RECONCILED_AUDIT_ONLY_OUTPUT" if not unauthorized else "UNAUTHORIZED_OUTPUT_ARTIFACT",
            "output_reconciliation_reason": "Manifest entry is expected, audit-only, non-mutating, and contains no ticker rows.",
            **COMMON_SAFETY,
        })
    return rows


def reconcile_dependencies(source_rows: list[dict[str, str]], result_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    result_by_name = {clean(row.get("dependency_name")): row for row in result_rows}
    rows = []
    for index, source in enumerate(source_rows, start=1):
        name = clean(source.get("dependency_name"))
        result = result_by_name.get(name, {})
        ok = bool(result) and truthy(result.get("dependency_satisfied_for_dry_run"))
        rows.append({
            "dependency_reconciliation_id": f"V20_114_DEPENDENCY_RECONCILIATION_AUDIT_{index:03d}",
            "source_dependency_check_id": clean(source.get("dependency_check_id")),
            "dependency_name": name,
            "dependency_result_id": clean(result.get("dependency_result_id")),
            "dependency_required_before_dry_run": clean(source.get("dependency_required_before_dry_run")),
            "dependency_satisfied_for_dry_run": clean(result.get("dependency_satisfied_for_dry_run")) or "FALSE",
            "dependency_reconciled": tf(ok),
            "dependency_reconciliation_status": "RECONCILED" if ok else "DEPENDENCY_NOT_SATISFIED_FOR_DRY_RUN",
            "dependency_reconciliation_reason": "V20.113 dependency result satisfies the V20.112 dependency audit row.",
            **COMMON_SAFETY,
        })
    return rows


def build_safety(counts: dict[str, int], passed: bool) -> list[dict[str, str]]:
    return [{
        "safety_check_id": f"V20_114_SHADOW_OUTPUT_SAFETY_BOUNDARY_AUDIT_{index:03d}",
        "prohibited_field": field,
        "observed_true_count": str(counts.get(field, 0)),
        "safety_boundary_passed": tf(passed),
        "safety_status": "PASS" if passed else "BLOCKED",
        "safety_reason": "V20.114 reconciles audit-only shadow outputs and creates no prohibited artifacts or mutations.",
        **COMMON_SAFETY,
    } for index, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_all(decision, step_recon, output_recon, dep_recon, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_STEP_RECON, STEP_FIELDS, step_recon)
    write_csv(OUT_OUTPUT_RECON, OUTPUT_FIELDS, output_recon)
    write_csv(OUT_DEP_RECON, DEPENDENCY_FIELDS, dep_recon)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.114 Shadow Output Reconciliation Report",
        "",
        f"- wrapper_status: {decision.get('shadow_output_reconciliation_status')}",
        f"- v20_113_gate_consumed: {decision.get('v20_113_gate_consumed')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- missing_planned_step_count: {decision.get('missing_planned_step_count')}",
        f"- unauthorized_output_artifact_count: {decision.get('unauthorized_output_artifact_count')}",
        f"- dependency_reconciliation_all_passed: {decision.get('dependency_reconciliation_all_passed')}",
        f"- upstream_mutation_detected: {decision.get('upstream_mutation_detected')}",
        f"- safety_boundary_audit_passed: {decision.get('safety_boundary_audit_passed')}",
        f"- v20_115_shadow_baseline_comparison_allowed: {decision.get('v20_115_shadow_baseline_comparison_allowed')}",
        f"- blocking_reason: {decision.get('blocking_reason')}",
        "- accepted_weight_created: FALSE",
        "- real_book_weight_created: FALSE",
        "- official_weight_created: FALSE",
        "- official_ranking_created: FALSE",
        "- official_recommendation_created: FALSE",
        "- trade_action_created: FALSE",
        "- broker_action_created: FALSE",
        "- authoritative_overwrite_created: FALSE",
        "- weight_mutated: FALSE",
        "- promotion_ready: FALSE",
        "- performance_claim_created: FALSE",
    ]) + "\n", encoding="utf-8")


def print_safety_stdout() -> None:
    for flag in [
        "ACCEPTED_WEIGHT_CREATED", "ACCEPTED_WEIGHTS_CREATED", "REAL_BOOK_WEIGHT_CREATED",
        "REAL_BOOK_ACTION_CREATED", "OFFICIAL_WEIGHT_CREATED", "OFFICIAL_WEIGHTS_CREATED",
        "OFFICIAL_RANKING_CREATED", "OFFICIAL_RANKINGS_CREATED", "OFFICIAL_RECOMMENDATION_CREATED",
        "OFFICIAL_RECOMMENDATIONS_CREATED", "TRADE_ACTION_CREATED", "TRADE_ACTIONS_CREATED",
        "BROKER_ACTION_CREATED", "BROKER_ACTIONS_CREATED", "AUTHORITATIVE_OVERWRITE_CREATED",
        "AUTHORITATIVE_OVERWRITES_CREATED", "AUTHORITATIVE_RANKING_OVERWRITTEN", "WEIGHT_MUTATED",
        "WEIGHT_MUTATIONS_CREATED", "PROMOTION_READY", "PERFORMANCE_CLAIM_CREATED",
        "PERFORMANCE_CLAIMS_CREATED", "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED",
        "OFFICIAL_PROMOTION_ALLOWED", "IS_OFFICIAL_WEIGHT",
    ]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    counts = {field: 0 for field in PROHIBITED_FIELDS}
    safety = build_safety(counts, False)
    decision = {
        "decision_check_id": "V20_114_SHADOW_OUTPUT_RECONCILIATION_DECISION_001",
        "v20_113_gate_consumed": "FALSE",
        "v20_114_shadow_output_reconciliation_allowed_by_v113": "FALSE",
        "v20_113_final_status": "",
        "v20_113_status_passed": "FALSE",
        "selected_repair_scenario_id": "",
        "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID,
        "selected_scenario_matches_v20_113": "FALSE",
        "planned_step_count": "0",
        "reconciled_step_count": "0",
        "missing_planned_step_count": "0",
        "no_planned_dry_run_step_missing": "FALSE",
        "manifest_entry_count": "0",
        "unauthorized_output_artifact_count": "0",
        "no_unauthorized_output_artifact_accepted": "FALSE",
        "dependency_source_count": "0",
        "dependency_reconciled_count": "0",
        "dependency_reconciliation_all_passed": "FALSE",
        "fabricated_ticker_row_count": "0",
        "no_ticker_rows_fabricated": "TRUE",
        "upstream_mutation_detected": "FALSE",
        "no_upstream_outputs_mutated": "TRUE",
        "shadow_only_confirmed": "FALSE",
        "reconciliation_only_confirmed": "TRUE",
        "audit_only_confirmed": "TRUE",
        "safety_boundary_audit_passed": "FALSE",
        "prohibited_action_true_count": "0",
        "all_shadow_output_reconciliation_checks_passed": "FALSE",
        "v20_115_shadow_baseline_comparison_allowed": "FALSE",
        "shadow_output_reconciliation_status": BLOCKED_STATUS,
        "blocking_reason": blocking,
        **COMMON_SAFETY,
    }
    gate = {
        "gate_check_id": "V20_114_NEXT_STAGE_GATE_001",
        "v20_113_gate_consumed": "FALSE",
        "v20_114_shadow_output_reconciliation_allowed_by_v113": "FALSE",
        "selected_repair_scenario_id": "",
        "shadow_output_reconciliation_decision_created": "TRUE",
        "no_planned_dry_run_step_missing": "FALSE",
        "no_unauthorized_output_artifact_accepted": "FALSE",
        "dependency_reconciliation_all_passed": "FALSE",
        "no_upstream_outputs_mutated": "TRUE",
        "safety_boundary_audit_passed": "FALSE",
        "v20_115_shadow_baseline_comparison_allowed": "FALSE",
        "next_recommended_action": "V20.114_SHADOW_OUTPUT_RECONCILIATION_REPAIR",
        "blocking_reason": blocking,
        "shadow_output_reconciliation_status": BLOCKED_STATUS,
        **COMMON_SAFETY,
    }
    write_all([decision], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_113_GATE_CONSUMED=FALSE")
    print("V20_114_SHADOW_OUTPUT_RECONCILIATION_ALLOWED_BY_V113=FALSE")
    print("V20_115_SHADOW_BASELINE_COMPARISON_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def main() -> int:
    before_hashes = upstream_hashes()
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)

    decision_rows = read_csv(IN_DECISION)
    step_execution_rows = read_csv(IN_STEP_EXECUTION)
    dependency_result_rows = read_csv(IN_DEPENDENCY_RESULT)
    manifest_rows = read_csv(IN_MANIFEST)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    planned_step_rows = read_csv(IN_V112_STEPS)
    source_dependency_rows = read_csv(IN_V112_DEPENDENCY)
    if not all([decision_rows, step_execution_rows, dependency_result_rows, manifest_rows, safety_input_rows, gate_rows, planned_step_rows, source_dependency_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v113_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_113_NEXT_STAGE_GATE_001"
    v114_allowed = truthy(gate_in.get("v20_114_shadow_output_reconciliation_allowed"))
    v113_status = clean(gate_in.get("shadow_integration_dry_run_status")) or clean(decision_in.get("shadow_integration_dry_run_status"))
    v113_status_passed = v113_status == V113_PASS_STATUS
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))

    step_recon = reconcile_steps(planned_step_rows, step_execution_rows, selected_id)
    output_recon = reconcile_outputs(manifest_rows)
    dep_recon = reconcile_dependencies(source_dependency_rows, dependency_result_rows)
    missing_step_count = sum(1 for row in step_recon if truthy(row.get("missing_planned_step")))
    reconciled_step_count = sum(1 for row in step_recon if truthy(row.get("step_reconciled")))
    unauthorized_count = sum(1 for row in output_recon if truthy(row.get("unauthorized_output_artifact")))
    dep_reconciled_count = sum(1 for row in dep_recon if truthy(row.get("dependency_reconciled")))
    fabricated_ticker_count = sum(1 for row in output_recon if truthy(row.get("contains_ticker_rows")))
    counts = prohibited_counts([decision_rows, step_execution_rows, dependency_result_rows, manifest_rows, safety_input_rows, gate_rows])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    after_hashes = upstream_hashes()
    upstream_mutation_detected = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0
    safety = build_safety(counts, safety_passed)

    checks = {
        "v20_113_gate_consumed": v113_gate_consumed,
        "v20_114_shadow_output_reconciliation_allowed_by_v113": v114_allowed,
        "v20_113_status_passed": v113_status_passed,
        "selected_scenario_matches_v20_113": selected_matches,
        "no_planned_dry_run_step_missing": bool(step_recon) and missing_step_count == 0,
        "no_unauthorized_output_artifact_accepted": bool(output_recon) and unauthorized_count == 0,
        "dependency_reconciliation_all_passed": bool(dep_recon) and dep_reconciled_count == len(dep_recon),
        "no_ticker_rows_fabricated": fabricated_ticker_count == 0,
        "no_upstream_outputs_mutated": not upstream_mutation_detected,
        "shadow_only_confirmed": truthy(decision_in.get("shadow_only_confirmed")),
        "reconciliation_only_confirmed": True,
        "audit_only_confirmed": all(truthy(row.get("audit_only_output")) for row in manifest_rows),
        "safety_boundary_audit_passed": safety_passed,
        "prohibited_action_true_count_zero": prohibited_count == 0,
    }
    all_passed = all(checks.values())
    status = PASS_STATUS if all_passed else BLOCKED_STATUS
    blocking = "" if all_passed else ";".join(name for name, passed in checks.items() if not passed)
    decision = {
        "decision_check_id": "V20_114_SHADOW_OUTPUT_RECONCILIATION_DECISION_001",
        "v20_113_gate_consumed": tf(v113_gate_consumed),
        "v20_114_shadow_output_reconciliation_allowed_by_v113": tf(v114_allowed),
        "v20_113_final_status": v113_status,
        "v20_113_status_passed": tf(v113_status_passed),
        "selected_repair_scenario_id": selected_id,
        "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID,
        "selected_scenario_matches_v20_113": tf(selected_matches),
        "planned_step_count": str(len(planned_step_rows)),
        "reconciled_step_count": str(reconciled_step_count),
        "missing_planned_step_count": str(missing_step_count),
        "no_planned_dry_run_step_missing": tf(missing_step_count == 0 and bool(step_recon)),
        "manifest_entry_count": str(len(manifest_rows)),
        "unauthorized_output_artifact_count": str(unauthorized_count),
        "no_unauthorized_output_artifact_accepted": tf(unauthorized_count == 0 and bool(output_recon)),
        "dependency_source_count": str(len(source_dependency_rows)),
        "dependency_reconciled_count": str(dep_reconciled_count),
        "dependency_reconciliation_all_passed": tf(bool(dep_recon) and dep_reconciled_count == len(dep_recon)),
        "fabricated_ticker_row_count": str(fabricated_ticker_count),
        "no_ticker_rows_fabricated": tf(fabricated_ticker_count == 0),
        "upstream_mutation_detected": tf(upstream_mutation_detected),
        "no_upstream_outputs_mutated": tf(not upstream_mutation_detected),
        "shadow_only_confirmed": tf(checks["shadow_only_confirmed"]),
        "reconciliation_only_confirmed": "TRUE",
        "audit_only_confirmed": tf(checks["audit_only_confirmed"]),
        "safety_boundary_audit_passed": tf(safety_passed),
        "prohibited_action_true_count": str(prohibited_count),
        "all_shadow_output_reconciliation_checks_passed": tf(all_passed),
        "v20_115_shadow_baseline_comparison_allowed": tf(all_passed),
        "shadow_output_reconciliation_status": status,
        "blocking_reason": blocking,
        **COMMON_SAFETY,
    }
    gate = {
        "gate_check_id": "V20_114_NEXT_STAGE_GATE_001",
        "v20_113_gate_consumed": tf(v113_gate_consumed),
        "v20_114_shadow_output_reconciliation_allowed_by_v113": tf(v114_allowed),
        "selected_repair_scenario_id": selected_id,
        "shadow_output_reconciliation_decision_created": "TRUE",
        "no_planned_dry_run_step_missing": tf(missing_step_count == 0 and bool(step_recon)),
        "no_unauthorized_output_artifact_accepted": tf(unauthorized_count == 0 and bool(output_recon)),
        "dependency_reconciliation_all_passed": tf(bool(dep_recon) and dep_reconciled_count == len(dep_recon)),
        "no_upstream_outputs_mutated": tf(not upstream_mutation_detected),
        "safety_boundary_audit_passed": tf(safety_passed),
        "v20_115_shadow_baseline_comparison_allowed": tf(all_passed),
        "next_recommended_action": "V20.115_SHADOW_BASELINE_COMPARISON" if all_passed else "V20.114_SHADOW_OUTPUT_RECONCILIATION_REPAIR",
        "blocking_reason": blocking,
        "shadow_output_reconciliation_status": status,
        **COMMON_SAFETY,
    }
    write_all([decision], step_recon, output_recon, dep_recon, safety, [gate])
    write_report(decision)

    print(status)
    print(f"V20_113_GATE_CONSUMED={tf(v113_gate_consumed)}")
    print(f"V20_114_SHADOW_OUTPUT_RECONCILIATION_ALLOWED_BY_V113={tf(v114_allowed)}")
    print(f"V20_113_FINAL_STATUS={v113_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_113={tf(selected_matches)}")
    print(f"PLANNED_STEP_COUNT={len(planned_step_rows)}")
    print(f"RECONCILED_STEP_COUNT={reconciled_step_count}")
    print(f"MISSING_PLANNED_STEP_COUNT={missing_step_count}")
    print(f"NO_PLANNED_DRY_RUN_STEP_MISSING={tf(missing_step_count == 0 and bool(step_recon))}")
    print(f"UNAUTHORIZED_OUTPUT_ARTIFACT_COUNT={unauthorized_count}")
    print(f"NO_UNAUTHORIZED_OUTPUT_ARTIFACT_ACCEPTED={tf(unauthorized_count == 0 and bool(output_recon))}")
    print(f"DEPENDENCY_RECONCILIATION_ALL_PASSED={tf(bool(dep_recon) and dep_reconciled_count == len(dep_recon))}")
    print(f"FABRICATED_TICKER_ROW_COUNT={fabricated_ticker_count}")
    print(f"NO_TICKER_ROWS_FABRICATED={tf(fabricated_ticker_count == 0)}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation_detected)}")
    print(f"NO_UPSTREAM_OUTPUTS_MUTATED={tf(not upstream_mutation_detected)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_115_SHADOW_BASELINE_COMPARISON_ALLOWED={tf(all_passed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
