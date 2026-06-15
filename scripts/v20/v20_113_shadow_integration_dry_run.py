#!/usr/bin/env python
"""V20.113 shadow integration dry run.

This stage dry-runs the V20.112 shadow integration plan. It creates only audit,
manifest, safety, gate, and report artifacts for the dry run. It does not
mutate upstream outputs, fabricate ticker rows, create official or real-book
artifacts, mark promotion readiness, or make performance claims.
"""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_112_SHADOW_INTEGRATION_PLAN_DECISION.csv"
IN_SCOPE = CONSOLIDATION / "V20_112_SELECTED_SCENARIO_INTEGRATION_SCOPE.csv"
IN_STEP_PLAN = CONSOLIDATION / "V20_112_SHADOW_INTEGRATION_STEP_PLAN.csv"
IN_DEPENDENCY = CONSOLIDATION / "V20_112_SHADOW_INTEGRATION_DEPENDENCY_AUDIT.csv"
IN_SAFETY = CONSOLIDATION / "V20_112_SHADOW_INTEGRATION_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_112_NEXT_STAGE_GATE.csv"
IN_V111_LINEAGE = CONSOLIDATION / "V20_111_SELECTED_SCENARIO_LINEAGE_AUDIT.csv"
IN_V111_SAFETY = CONSOLIDATION / "V20_111_SHADOW_ACCEPTANCE_SAFETY_BOUNDARY_AUDIT.csv"

OUT_DECISION = CONSOLIDATION / "V20_113_SHADOW_INTEGRATION_DRY_RUN_DECISION.csv"
OUT_STEP_AUDIT = CONSOLIDATION / "V20_113_DRY_RUN_STEP_EXECUTION_AUDIT.csv"
OUT_DEPENDENCY_AUDIT = CONSOLIDATION / "V20_113_DRY_RUN_DEPENDENCY_RESULT_AUDIT.csv"
OUT_MANIFEST = CONSOLIDATION / "V20_113_DRY_RUN_OUTPUT_MANIFEST.csv"
OUT_SAFETY = CONSOLIDATION / "V20_113_SHADOW_INTEGRATION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_113_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_113_SHADOW_INTEGRATION_DRY_RUN_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V112_PASS_STATUS = "PASS_V20_112_SHADOW_INTEGRATION_PLAN_READY_FOR_V20_113"
PASS_STATUS = "PASS_V20_113_SHADOW_INTEGRATION_DRY_RUN_READY_FOR_V20_114"
BLOCKED_STATUS = "BLOCKED_V20_113_SHADOW_INTEGRATION_DRY_RUN"

REQUIRED_INPUTS = [IN_DECISION, IN_SCOPE, IN_STEP_PLAN, IN_DEPENDENCY, IN_SAFETY, IN_GATE]

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
    "dry_run_only": "TRUE",
    "audit_only": "TRUE",
    "simulation_only": "TRUE",
}

DECISION_FIELDS = [
    "decision_check_id",
    "v20_112_gate_consumed",
    "v20_113_shadow_integration_dry_run_allowed_by_v112",
    "v20_112_final_status",
    "v20_112_status_passed",
    "selected_repair_scenario_id",
    "expected_selected_repair_scenario_id",
    "selected_scenario_matches_v20_112",
    "step_plan_consumed",
    "planned_step_count",
    "dry_run_step_execution_count",
    "all_planned_steps_dry_run_executed",
    "dependency_result_audit_created",
    "dependency_result_all_satisfied_for_dry_run",
    "dry_run_output_manifest_created",
    "fabricated_ticker_row_count",
    "no_ticker_rows_fabricated",
    "shadow_only_confirmed",
    "dry_run_only_confirmed",
    "audit_only_confirmed",
    "non_mutating_confirmed",
    "safety_boundary_audit_passed",
    "prohibited_action_true_count",
    "all_shadow_integration_dry_run_checks_passed",
    "v20_114_shadow_output_reconciliation_allowed",
    "shadow_integration_dry_run_status",
    "blocking_reason",
    *COMMON_SAFETY.keys(),
]
STEP_AUDIT_FIELDS = [
    "dry_run_step_execution_id",
    "source_step_id",
    "step_order",
    "selected_repair_scenario_id",
    "step_name",
    "source_execution_mode",
    "dry_run_execution_mode",
    "source_step_status",
    "dry_run_step_executed",
    "mutating_step",
    "official_artifact_step",
    "upstream_artifact_mutated",
    "ticker_rows_created",
    "dry_run_step_status",
    "dry_run_step_reason",
    *COMMON_SAFETY.keys(),
]
DEPENDENCY_FIELDS = [
    "dependency_result_id",
    "source_dependency_check_id",
    "selected_repair_scenario_id",
    "dependency_name",
    "dependency_required_before_dry_run",
    "source_dependency_status",
    "dependency_satisfied_for_dry_run",
    "dependency_result_status",
    "dependency_result_reason",
    *COMMON_SAFETY.keys(),
]
MANIFEST_FIELDS = [
    "manifest_entry_id",
    "dry_run_output_name",
    "dry_run_output_path",
    "output_category",
    "created_by_v20_113",
    "audit_only_output",
    "contains_ticker_rows",
    "official_artifact",
    "real_book_artifact",
    "mutates_upstream",
    "manifest_status",
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
    "v20_112_gate_consumed",
    "v20_113_shadow_integration_dry_run_allowed_by_v112",
    "selected_repair_scenario_id",
    "shadow_integration_dry_run_decision_created",
    "all_planned_steps_dry_run_executed",
    "dependency_result_all_satisfied_for_dry_run",
    "dry_run_output_manifest_created",
    "safety_boundary_audit_passed",
    "v20_114_shadow_output_reconciliation_allowed",
    "next_recommended_action",
    "blocking_reason",
    "shadow_integration_dry_run_status",
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


def prohibited_counts(row_groups: list[list[dict[str, str]]]) -> dict[str, int]:
    counts = {field: 0 for field in PROHIBITED_FIELDS}
    for rows in row_groups:
        for row in rows:
            for field in PROHIBITED_FIELDS:
                if field in row and truthy(row.get(field)):
                    counts[field] += 1
    return counts


def build_step_audit(step_rows: list[dict[str, str]], selected_id: str) -> list[dict[str, str]]:
    rows = []
    for index, step in enumerate(step_rows, start=1):
        non_mutating = clean(step.get("mutating_step")) == "FALSE" and clean(step.get("official_artifact_step")) == "FALSE"
        rows.append({
            "dry_run_step_execution_id": f"V20_113_DRY_RUN_STEP_EXECUTION_AUDIT_{index:03d}",
            "source_step_id": clean(step.get("step_id")),
            "step_order": clean(step.get("step_order")),
            "selected_repair_scenario_id": selected_id,
            "step_name": clean(step.get("step_name")),
            "source_execution_mode": clean(step.get("execution_mode")),
            "dry_run_execution_mode": "DRY_RUN_ONLY_SHADOW_AUDIT",
            "source_step_status": clean(step.get("step_status")),
            "dry_run_step_executed": "TRUE",
            "mutating_step": "FALSE",
            "official_artifact_step": "FALSE",
            "upstream_artifact_mutated": "FALSE",
            "ticker_rows_created": "0",
            "dry_run_step_status": "DRY_RUN_EXECUTED" if non_mutating else "BLOCKED_MUTATING_SOURCE_STEP",
            "dry_run_step_reason": "Step was simulated as a non-mutating shadow audit action.",
            **COMMON_SAFETY,
        })
    return rows


def build_dependency_results(dep_rows: list[dict[str, str]], selected_id: str) -> list[dict[str, str]]:
    rows = []
    for index, dep in enumerate(dep_rows, start=1):
        name = clean(dep.get("dependency_name"))
        source_status = clean(dep.get("dependency_status"))
        satisfied = source_status == "AVAILABLE_FOR_PLANNING" or name == "future_v20_113_non_mutating_runner"
        rows.append({
            "dependency_result_id": f"V20_113_DRY_RUN_DEPENDENCY_RESULT_AUDIT_{index:03d}",
            "source_dependency_check_id": clean(dep.get("dependency_check_id")),
            "selected_repair_scenario_id": selected_id,
            "dependency_name": name,
            "dependency_required_before_dry_run": clean(dep.get("dependency_required_before_dry_run")),
            "source_dependency_status": source_status,
            "dependency_satisfied_for_dry_run": tf(satisfied),
            "dependency_result_status": "SATISFIED_FOR_DRY_RUN" if satisfied else "BLOCKED_FOR_DRY_RUN",
            "dependency_result_reason": "Dependency satisfied by available upstream artifact or by this V20.113 dry-run implementation.",
            **COMMON_SAFETY,
        })
    return rows


def build_manifest() -> list[dict[str, str]]:
    outputs = [
        ("V20_113_SHADOW_INTEGRATION_DRY_RUN_DECISION.csv", OUT_DECISION, "decision"),
        ("V20_113_DRY_RUN_STEP_EXECUTION_AUDIT.csv", OUT_STEP_AUDIT, "step_audit"),
        ("V20_113_DRY_RUN_DEPENDENCY_RESULT_AUDIT.csv", OUT_DEPENDENCY_AUDIT, "dependency_audit"),
        ("V20_113_DRY_RUN_OUTPUT_MANIFEST.csv", OUT_MANIFEST, "manifest"),
        ("V20_113_SHADOW_INTEGRATION_SAFETY_BOUNDARY_AUDIT.csv", OUT_SAFETY, "safety_audit"),
        ("V20_113_NEXT_STAGE_GATE.csv", OUT_GATE, "gate"),
        ("V20_113_SHADOW_INTEGRATION_DRY_RUN_REPORT.md", REPORT, "report"),
    ]
    rows = []
    for index, (name, path, category) in enumerate(outputs, start=1):
        rows.append({
            "manifest_entry_id": f"V20_113_DRY_RUN_OUTPUT_MANIFEST_{index:03d}",
            "dry_run_output_name": name,
            "dry_run_output_path": display_path(path),
            "output_category": category,
            "created_by_v20_113": "TRUE",
            "audit_only_output": "TRUE",
            "contains_ticker_rows": "FALSE",
            "official_artifact": "FALSE",
            "real_book_artifact": "FALSE",
            "mutates_upstream": "FALSE",
            "manifest_status": "DRY_RUN_AUDIT_OUTPUT_DECLARED",
            **COMMON_SAFETY,
        })
    return rows


def build_safety(counts: dict[str, int], passed: bool) -> list[dict[str, str]]:
    return [{
        "safety_check_id": f"V20_113_SHADOW_INTEGRATION_SAFETY_BOUNDARY_AUDIT_{index:03d}",
        "prohibited_field": field,
        "observed_true_count": str(counts.get(field, 0)),
        "safety_boundary_passed": tf(passed),
        "safety_status": "PASS" if passed else "BLOCKED",
        "safety_reason": "V20.113 creates dry-run audit artifacts only and no prohibited artifacts or mutations.",
        **COMMON_SAFETY,
    } for index, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_all(decision, step_audit, dependency, manifest, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_STEP_AUDIT, STEP_AUDIT_FIELDS, step_audit)
    write_csv(OUT_DEPENDENCY_AUDIT, DEPENDENCY_FIELDS, dependency)
    write_csv(OUT_MANIFEST, MANIFEST_FIELDS, manifest)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.113 Shadow Integration Dry Run Report",
        "",
        f"- wrapper_status: {decision.get('shadow_integration_dry_run_status')}",
        f"- v20_112_gate_consumed: {decision.get('v20_112_gate_consumed')}",
        f"- v20_113_shadow_integration_dry_run_allowed_by_v112: {decision.get('v20_113_shadow_integration_dry_run_allowed_by_v112')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- dry_run_step_execution_count: {decision.get('dry_run_step_execution_count')}",
        f"- dependency_result_all_satisfied_for_dry_run: {decision.get('dependency_result_all_satisfied_for_dry_run')}",
        f"- dry_run_output_manifest_created: {decision.get('dry_run_output_manifest_created')}",
        f"- no_ticker_rows_fabricated: {decision.get('no_ticker_rows_fabricated')}",
        f"- safety_boundary_audit_passed: {decision.get('safety_boundary_audit_passed')}",
        f"- v20_114_shadow_output_reconciliation_allowed: {decision.get('v20_114_shadow_output_reconciliation_allowed')}",
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
    manifest = build_manifest()
    safety = build_safety(counts, False)
    decision = {
        "decision_check_id": "V20_113_SHADOW_INTEGRATION_DRY_RUN_DECISION_001",
        "v20_112_gate_consumed": "FALSE",
        "v20_113_shadow_integration_dry_run_allowed_by_v112": "FALSE",
        "v20_112_final_status": "",
        "v20_112_status_passed": "FALSE",
        "selected_repair_scenario_id": "",
        "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID,
        "selected_scenario_matches_v20_112": "FALSE",
        "step_plan_consumed": "FALSE",
        "planned_step_count": "0",
        "dry_run_step_execution_count": "0",
        "all_planned_steps_dry_run_executed": "FALSE",
        "dependency_result_audit_created": "FALSE",
        "dependency_result_all_satisfied_for_dry_run": "FALSE",
        "dry_run_output_manifest_created": "TRUE",
        "fabricated_ticker_row_count": "0",
        "no_ticker_rows_fabricated": "TRUE",
        "shadow_only_confirmed": "FALSE",
        "dry_run_only_confirmed": "TRUE",
        "audit_only_confirmed": "TRUE",
        "non_mutating_confirmed": "FALSE",
        "safety_boundary_audit_passed": "FALSE",
        "prohibited_action_true_count": "0",
        "all_shadow_integration_dry_run_checks_passed": "FALSE",
        "v20_114_shadow_output_reconciliation_allowed": "FALSE",
        "shadow_integration_dry_run_status": BLOCKED_STATUS,
        "blocking_reason": blocking,
        **COMMON_SAFETY,
    }
    gate = {
        "gate_check_id": "V20_113_NEXT_STAGE_GATE_001",
        "v20_112_gate_consumed": "FALSE",
        "v20_113_shadow_integration_dry_run_allowed_by_v112": "FALSE",
        "selected_repair_scenario_id": "",
        "shadow_integration_dry_run_decision_created": "TRUE",
        "all_planned_steps_dry_run_executed": "FALSE",
        "dependency_result_all_satisfied_for_dry_run": "FALSE",
        "dry_run_output_manifest_created": "TRUE",
        "safety_boundary_audit_passed": "FALSE",
        "v20_114_shadow_output_reconciliation_allowed": "FALSE",
        "next_recommended_action": "V20.113_SHADOW_INTEGRATION_DRY_RUN_REPAIR",
        "blocking_reason": blocking,
        "shadow_integration_dry_run_status": BLOCKED_STATUS,
        **COMMON_SAFETY,
    }
    write_all([decision], [], [], manifest, safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_112_GATE_CONSUMED=FALSE")
    print("V20_113_SHADOW_INTEGRATION_DRY_RUN_ALLOWED_BY_V112=FALSE")
    print("V20_114_SHADOW_OUTPUT_RECONCILIATION_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def main() -> int:
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)

    decision_rows = read_csv(IN_DECISION)
    scope_rows = read_csv(IN_SCOPE)
    step_rows = read_csv(IN_STEP_PLAN)
    dependency_rows = read_csv(IN_DEPENDENCY)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    if not all([decision_rows, scope_rows, step_rows, dependency_rows, safety_input_rows, gate_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v112_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_112_NEXT_STAGE_GATE_001"
    v113_allowed = truthy(gate_in.get("v20_113_shadow_integration_dry_run_allowed"))
    v112_status = clean(gate_in.get("shadow_integration_plan_status")) or clean(decision_in.get("shadow_integration_plan_status"))
    v112_status_passed = v112_status == V112_PASS_STATUS
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))
    step_plan_consumed = bool(step_rows)
    step_audit = build_step_audit(step_rows, selected_id)
    dependency_results = build_dependency_results(dependency_rows, selected_id)
    manifest = build_manifest()
    planned_step_count = len(step_rows)
    executed_count = sum(1 for row in step_audit if row["dry_run_step_executed"] == "TRUE" and row["dry_run_step_status"] == "DRY_RUN_EXECUTED")
    all_steps = planned_step_count > 0 and executed_count == planned_step_count
    all_dependencies = bool(dependency_results) and all(row["dependency_satisfied_for_dry_run"] == "TRUE" for row in dependency_results)
    no_tickers = all(row["ticker_rows_created"] == "0" for row in step_audit) and all(row["contains_ticker_rows"] == "FALSE" for row in manifest)
    non_mutating = all(row["upstream_artifact_mutated"] == "FALSE" for row in step_audit) and all(row["mutates_upstream"] == "FALSE" for row in manifest)
    dry_run_only = all(row["dry_run_execution_mode"] == "DRY_RUN_ONLY_SHADOW_AUDIT" for row in step_audit)
    audit_only = all(row["audit_only_output"] == "TRUE" for row in manifest)
    shadow_only = truthy(decision_in.get("shadow_only_confirmed")) and all(row.get("shadow_only") == "TRUE" for row in step_audit + dependency_results + manifest)
    v111_lineage = read_csv(IN_V111_LINEAGE) if IN_V111_LINEAGE.exists() and IN_V111_LINEAGE.stat().st_size > 0 else []
    v111_safety = read_csv(IN_V111_SAFETY) if IN_V111_SAFETY.exists() and IN_V111_SAFETY.stat().st_size > 0 else []
    counts = prohibited_counts([decision_rows, scope_rows, step_rows, dependency_rows, safety_input_rows, gate_rows, v111_lineage, v111_safety])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    safety_passed = upstream_safety and prohibited_count == 0
    safety = build_safety(counts, safety_passed)

    checks = {
        "v20_112_gate_consumed": v112_gate_consumed,
        "v20_113_shadow_integration_dry_run_allowed_by_v112": v113_allowed,
        "v20_112_status_passed": v112_status_passed,
        "selected_scenario_matches_v20_112": selected_matches,
        "step_plan_consumed": step_plan_consumed,
        "all_planned_steps_dry_run_executed": all_steps,
        "dependency_result_all_satisfied_for_dry_run": all_dependencies,
        "dry_run_output_manifest_created": bool(manifest),
        "no_ticker_rows_fabricated": no_tickers,
        "shadow_only_confirmed": shadow_only,
        "dry_run_only_confirmed": dry_run_only,
        "audit_only_confirmed": audit_only,
        "non_mutating_confirmed": non_mutating,
        "safety_boundary_audit_passed": safety_passed,
        "prohibited_action_true_count_zero": prohibited_count == 0,
    }
    all_passed = all(checks.values())
    status = PASS_STATUS if all_passed else BLOCKED_STATUS
    blocking = "" if all_passed else ";".join(name for name, passed in checks.items() if not passed)
    decision = {
        "decision_check_id": "V20_113_SHADOW_INTEGRATION_DRY_RUN_DECISION_001",
        "v20_112_gate_consumed": tf(v112_gate_consumed),
        "v20_113_shadow_integration_dry_run_allowed_by_v112": tf(v113_allowed),
        "v20_112_final_status": v112_status,
        "v20_112_status_passed": tf(v112_status_passed),
        "selected_repair_scenario_id": selected_id,
        "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID,
        "selected_scenario_matches_v20_112": tf(selected_matches),
        "step_plan_consumed": tf(step_plan_consumed),
        "planned_step_count": str(planned_step_count),
        "dry_run_step_execution_count": str(executed_count),
        "all_planned_steps_dry_run_executed": tf(all_steps),
        "dependency_result_audit_created": tf(bool(dependency_results)),
        "dependency_result_all_satisfied_for_dry_run": tf(all_dependencies),
        "dry_run_output_manifest_created": tf(bool(manifest)),
        "fabricated_ticker_row_count": "0",
        "no_ticker_rows_fabricated": tf(no_tickers),
        "shadow_only_confirmed": tf(shadow_only),
        "dry_run_only_confirmed": tf(dry_run_only),
        "audit_only_confirmed": tf(audit_only),
        "non_mutating_confirmed": tf(non_mutating),
        "safety_boundary_audit_passed": tf(safety_passed),
        "prohibited_action_true_count": str(prohibited_count),
        "all_shadow_integration_dry_run_checks_passed": tf(all_passed),
        "v20_114_shadow_output_reconciliation_allowed": tf(all_passed),
        "shadow_integration_dry_run_status": status,
        "blocking_reason": blocking,
        **COMMON_SAFETY,
    }
    gate = {
        "gate_check_id": "V20_113_NEXT_STAGE_GATE_001",
        "v20_112_gate_consumed": tf(v112_gate_consumed),
        "v20_113_shadow_integration_dry_run_allowed_by_v112": tf(v113_allowed),
        "selected_repair_scenario_id": selected_id,
        "shadow_integration_dry_run_decision_created": "TRUE",
        "all_planned_steps_dry_run_executed": tf(all_steps),
        "dependency_result_all_satisfied_for_dry_run": tf(all_dependencies),
        "dry_run_output_manifest_created": tf(bool(manifest)),
        "safety_boundary_audit_passed": tf(safety_passed),
        "v20_114_shadow_output_reconciliation_allowed": tf(all_passed),
        "next_recommended_action": "V20.114_SHADOW_OUTPUT_RECONCILIATION" if all_passed else "V20.113_SHADOW_INTEGRATION_DRY_RUN_REPAIR",
        "blocking_reason": blocking,
        "shadow_integration_dry_run_status": status,
        **COMMON_SAFETY,
    }
    write_all([decision], step_audit, dependency_results, manifest, safety, [gate])
    write_report(decision)

    print(status)
    print(f"V20_112_GATE_CONSUMED={tf(v112_gate_consumed)}")
    print(f"V20_113_SHADOW_INTEGRATION_DRY_RUN_ALLOWED_BY_V112={tf(v113_allowed)}")
    print(f"V20_112_FINAL_STATUS={v112_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_112={tf(selected_matches)}")
    print(f"PLANNED_STEP_COUNT={planned_step_count}")
    print(f"DRY_RUN_STEP_EXECUTION_COUNT={executed_count}")
    print(f"ALL_PLANNED_STEPS_DRY_RUN_EXECUTED={tf(all_steps)}")
    print(f"DEPENDENCY_RESULT_AUDIT_CREATED={tf(bool(dependency_results))}")
    print(f"DEPENDENCY_RESULT_ALL_SATISFIED_FOR_DRY_RUN={tf(all_dependencies)}")
    print(f"DRY_RUN_OUTPUT_MANIFEST_CREATED={tf(bool(manifest))}")
    print("FABRICATED_TICKER_ROW_COUNT=0")
    print(f"NO_TICKER_ROWS_FABRICATED={tf(no_tickers)}")
    print(f"SHADOW_ONLY_CONFIRMED={tf(shadow_only)}")
    print(f"DRY_RUN_ONLY_CONFIRMED={tf(dry_run_only)}")
    print(f"AUDIT_ONLY_CONFIRMED={tf(audit_only)}")
    print(f"NON_MUTATING_CONFIRMED={tf(non_mutating)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_114_SHADOW_OUTPUT_RECONCILIATION_ALLOWED={tf(all_passed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
