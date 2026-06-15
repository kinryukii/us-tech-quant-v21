#!/usr/bin/env python
"""V20.112 shadow-only integration plan.

This stage consumes the V20.111 shadow acceptance review and creates a
planning-only integration package for the selected repair scenario. It does not
execute integration, mutate weights, create ticker rows, create official or
real-book artifacts, mark promotion readiness, or make performance claims.
"""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_111_SHADOW_ACCEPTANCE_REVIEW_DECISION.csv"
IN_LINEAGE = CONSOLIDATION / "V20_111_SELECTED_SCENARIO_LINEAGE_AUDIT.csv"
IN_CRITERIA = CONSOLIDATION / "V20_111_SHADOW_REVIEW_CRITERIA_AUDIT.csv"
IN_SAFETY = CONSOLIDATION / "V20_111_SHADOW_ACCEPTANCE_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_111_NEXT_STAGE_GATE.csv"
IN_V110_SELECTED = CONSOLIDATION / "V20_110_SELECTED_REPAIR_SCENARIO_ACCEPTANCE_AUDIT.csv"
IN_V110_MANIFEST = CONSOLIDATION / "V20_110_ACCEPTANCE_CANDIDATE_MANIFEST.csv"

OUT_DECISION = CONSOLIDATION / "V20_112_SHADOW_INTEGRATION_PLAN_DECISION.csv"
OUT_SCOPE = CONSOLIDATION / "V20_112_SELECTED_SCENARIO_INTEGRATION_SCOPE.csv"
OUT_STEP_PLAN = CONSOLIDATION / "V20_112_SHADOW_INTEGRATION_STEP_PLAN.csv"
OUT_DEPENDENCY = CONSOLIDATION / "V20_112_SHADOW_INTEGRATION_DEPENDENCY_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_112_SHADOW_INTEGRATION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_112_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_112_SHADOW_INTEGRATION_PLAN_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V111_PASS_STATUS = "PASS_V20_111_SHADOW_ACCEPTANCE_REVIEW_READY_FOR_V20_112"
PASS_STATUS = "PASS_V20_112_SHADOW_INTEGRATION_PLAN_READY_FOR_V20_113"
BLOCKED_STATUS = "BLOCKED_V20_112_SHADOW_INTEGRATION_PLAN"

REQUIRED_INPUTS = [IN_DECISION, IN_LINEAGE, IN_CRITERIA, IN_SAFETY, IN_GATE]

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
    "planning_only": "TRUE",
    "simulation_only": "TRUE",
}

DECISION_FIELDS = [
    "decision_check_id",
    "v20_111_gate_consumed",
    "v20_112_shadow_integration_plan_allowed_by_v111",
    "v20_111_final_status",
    "v20_111_status_passed",
    "selected_repair_scenario_id",
    "expected_selected_repair_scenario_id",
    "selected_scenario_matches_v20_111",
    "lineage_valid_from_v20_111",
    "integration_scope_created",
    "integration_step_plan_created",
    "dependency_audit_created",
    "shadow_only_confirmed",
    "planning_only_confirmed",
    "non_mutating_confirmed",
    "safety_boundary_audit_passed",
    "prohibited_action_true_count",
    "all_shadow_integration_plan_checks_passed",
    "v20_113_shadow_integration_dry_run_allowed",
    "shadow_integration_plan_status",
    "blocking_reason",
    *COMMON_SAFETY.keys(),
]
SCOPE_FIELDS = [
    "scope_check_id",
    "selected_repair_scenario_id",
    "scope_item",
    "scope_description",
    "scope_included",
    "scope_boundary",
    "creates_weight_mutation",
    "creates_official_artifact",
    "scope_status",
    *COMMON_SAFETY.keys(),
]
STEP_FIELDS = [
    "step_id",
    "step_order",
    "selected_repair_scenario_id",
    "step_name",
    "step_description",
    "execution_mode",
    "requires_prior_dependency_clearance",
    "mutating_step",
    "official_artifact_step",
    "step_status",
    *COMMON_SAFETY.keys(),
]
DEPENDENCY_FIELDS = [
    "dependency_check_id",
    "selected_repair_scenario_id",
    "dependency_name",
    "dependency_source",
    "dependency_required_before_dry_run",
    "dependency_available_for_planning",
    "dependency_status",
    "dependency_reason",
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
    "v20_111_gate_consumed",
    "v20_112_shadow_integration_plan_allowed_by_v111",
    "selected_repair_scenario_id",
    "shadow_integration_plan_decision_created",
    "integration_scope_created",
    "integration_step_plan_created",
    "dependency_audit_created",
    "safety_boundary_audit_passed",
    "v20_113_shadow_integration_dry_run_allowed",
    "next_recommended_action",
    "blocking_reason",
    "shadow_integration_plan_status",
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


def build_scope(selected_id: str) -> list[dict[str, str]]:
    items = [
        ("scenario_identity", "Bind the selected repair scenario id into a shadow integration dry-run context."),
        ("shadow_weight_template_reference", "Reference the repair scenario as a candidate plan input without creating accepted or official weights."),
        ("lineage_and_safety_precheck", "Carry forward V20.111 lineage and prohibited-action safety gates into the dry-run plan."),
        ("dry_run_output_contract", "Define future dry-run outputs as shadow diagnostics only, with no real-book or official artifacts."),
    ]
    rows = []
    for index, (item, description) in enumerate(items, start=1):
        rows.append({
            "scope_check_id": f"V20_112_SELECTED_SCENARIO_INTEGRATION_SCOPE_{index:03d}",
            "selected_repair_scenario_id": selected_id,
            "scope_item": item,
            "scope_description": description,
            "scope_included": "TRUE",
            "scope_boundary": "SHADOW_ONLY_PLANNING",
            "creates_weight_mutation": "FALSE",
            "creates_official_artifact": "FALSE",
            "scope_status": "IN_SCOPE",
            **COMMON_SAFETY,
        })
    return rows


def build_steps(selected_id: str) -> list[dict[str, str]]:
    steps = [
        ("confirm_v111_gate", "Confirm V20.111 passed and allowed V20.112 planning."),
        ("bind_shadow_candidate", "Bind the selected repair scenario into a dry-run-only integration context."),
        ("prepare_non_mutating_contract", "Specify that future dry-run artifacts cannot mutate existing weights or authoritative rankings."),
        ("define_shadow_diagnostics", "Define diagnostics needed for a later shadow integration dry run."),
        ("recheck_safety_before_execution", "Require another safety boundary check before V20.113 dry-run execution."),
    ]
    rows = []
    for order, (name, description) in enumerate(steps, start=1):
        rows.append({
            "step_id": f"V20_112_SHADOW_INTEGRATION_STEP_{order:03d}",
            "step_order": str(order),
            "selected_repair_scenario_id": selected_id,
            "step_name": name,
            "step_description": description,
            "execution_mode": "PLAN_ONLY_SHADOW",
            "requires_prior_dependency_clearance": "TRUE",
            "mutating_step": "FALSE",
            "official_artifact_step": "FALSE",
            "step_status": "PLANNED",
            **COMMON_SAFETY,
        })
    return rows


def build_dependencies(selected_id: str, v110_available: bool) -> list[dict[str, str]]:
    dependencies = [
        ("v20_111_next_stage_gate", "V20.111 next-stage gate", True),
        ("v20_111_shadow_acceptance_decision", "V20.111 decision output", True),
        ("v20_111_lineage_audit", "V20.111 selected scenario lineage audit", True),
        ("v20_111_safety_boundary_audit", "V20.111 safety boundary audit", True),
        ("v20_110_candidate_manifest_reference", "V20.110 candidate manifest reference", v110_available),
        ("future_v20_113_non_mutating_runner", "Future V20.113 dry-run runner implementation", False),
    ]
    rows = []
    for index, (name, source, available) in enumerate(dependencies, start=1):
        rows.append({
            "dependency_check_id": f"V20_112_SHADOW_INTEGRATION_DEPENDENCY_AUDIT_{index:03d}",
            "selected_repair_scenario_id": selected_id,
            "dependency_name": name,
            "dependency_source": source,
            "dependency_required_before_dry_run": "TRUE",
            "dependency_available_for_planning": tf(available),
            "dependency_status": "AVAILABLE_FOR_PLANNING" if available else "REQUIRED_BEFORE_EXECUTION",
            "dependency_reason": "Dependency is available for the planning stage." if available else "Dependency is recorded as required before a later dry-run execution stage.",
            **COMMON_SAFETY,
        })
    return rows


def build_safety(counts: dict[str, int], safety_passed: bool) -> list[dict[str, str]]:
    rows = []
    for index, field in enumerate(PROHIBITED_FIELDS, start=1):
        rows.append({
            "safety_check_id": f"V20_112_SHADOW_INTEGRATION_SAFETY_BOUNDARY_AUDIT_{index:03d}",
            "prohibited_field": field,
            "observed_true_count": str(counts.get(field, 0)),
            "safety_boundary_passed": tf(safety_passed),
            "safety_status": "PASS" if safety_passed else "BLOCKED",
            "safety_reason": "V20.112 creates only a shadow integration plan and no prohibited artifacts or mutations.",
            **COMMON_SAFETY,
        })
    return rows


def write_all(
    decision_rows: list[dict[str, str]],
    scope_rows: list[dict[str, str]],
    step_rows: list[dict[str, str]],
    dependency_rows: list[dict[str, str]],
    safety_rows: list[dict[str, str]],
    gate_rows: list[dict[str, str]],
) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision_rows)
    write_csv(OUT_SCOPE, SCOPE_FIELDS, scope_rows)
    write_csv(OUT_STEP_PLAN, STEP_FIELDS, step_rows)
    write_csv(OUT_DEPENDENCY, DEPENDENCY_FIELDS, dependency_rows)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety_rows)
    write_csv(OUT_GATE, GATE_FIELDS, gate_rows)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        "\n".join([
            "# V20.112 Shadow Integration Plan Report",
            "",
            f"- wrapper_status: {decision.get('shadow_integration_plan_status')}",
            f"- v20_111_gate_consumed: {decision.get('v20_111_gate_consumed')}",
            f"- v20_112_shadow_integration_plan_allowed_by_v111: {decision.get('v20_112_shadow_integration_plan_allowed_by_v111')}",
            f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
            f"- integration_scope_created: {decision.get('integration_scope_created')}",
            f"- integration_step_plan_created: {decision.get('integration_step_plan_created')}",
            f"- dependency_audit_created: {decision.get('dependency_audit_created')}",
            f"- safety_boundary_audit_passed: {decision.get('safety_boundary_audit_passed')}",
            f"- v20_113_shadow_integration_dry_run_allowed: {decision.get('v20_113_shadow_integration_dry_run_allowed')}",
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
        ])
        + "\n",
        encoding="utf-8",
    )


def print_safety_stdout() -> None:
    for flag in [
        "ACCEPTED_WEIGHT_CREATED",
        "ACCEPTED_WEIGHTS_CREATED",
        "REAL_BOOK_WEIGHT_CREATED",
        "REAL_BOOK_ACTION_CREATED",
        "OFFICIAL_WEIGHT_CREATED",
        "OFFICIAL_WEIGHTS_CREATED",
        "OFFICIAL_RANKING_CREATED",
        "OFFICIAL_RANKINGS_CREATED",
        "OFFICIAL_RECOMMENDATION_CREATED",
        "OFFICIAL_RECOMMENDATIONS_CREATED",
        "TRADE_ACTION_CREATED",
        "TRADE_ACTIONS_CREATED",
        "BROKER_ACTION_CREATED",
        "BROKER_ACTIONS_CREATED",
        "AUTHORITATIVE_OVERWRITE_CREATED",
        "AUTHORITATIVE_OVERWRITES_CREATED",
        "AUTHORITATIVE_RANKING_OVERWRITTEN",
        "WEIGHT_MUTATED",
        "WEIGHT_MUTATIONS_CREATED",
        "PROMOTION_READY",
        "PERFORMANCE_CLAIM_CREATED",
        "PERFORMANCE_CLAIMS_CREATED",
        "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED",
        "OFFICIAL_PROMOTION_ALLOWED",
        "IS_OFFICIAL_WEIGHT",
    ]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    selected_id = ""
    scope_rows: list[dict[str, str]] = []
    step_rows: list[dict[str, str]] = []
    dependency_rows: list[dict[str, str]] = []
    counts = {field: 0 for field in PROHIBITED_FIELDS}
    safety_rows = build_safety(counts, False)
    decision = {
        "decision_check_id": "V20_112_SHADOW_INTEGRATION_PLAN_DECISION_001",
        "v20_111_gate_consumed": "FALSE",
        "v20_112_shadow_integration_plan_allowed_by_v111": "FALSE",
        "v20_111_final_status": "",
        "v20_111_status_passed": "FALSE",
        "selected_repair_scenario_id": selected_id,
        "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID,
        "selected_scenario_matches_v20_111": "FALSE",
        "lineage_valid_from_v20_111": "FALSE",
        "integration_scope_created": "FALSE",
        "integration_step_plan_created": "FALSE",
        "dependency_audit_created": "FALSE",
        "shadow_only_confirmed": "FALSE",
        "planning_only_confirmed": "TRUE",
        "non_mutating_confirmed": "FALSE",
        "safety_boundary_audit_passed": "FALSE",
        "prohibited_action_true_count": "0",
        "all_shadow_integration_plan_checks_passed": "FALSE",
        "v20_113_shadow_integration_dry_run_allowed": "FALSE",
        "shadow_integration_plan_status": BLOCKED_STATUS,
        "blocking_reason": blocking,
        **COMMON_SAFETY,
    }
    gate = {
        "gate_check_id": "V20_112_NEXT_STAGE_GATE_001",
        "v20_111_gate_consumed": "FALSE",
        "v20_112_shadow_integration_plan_allowed_by_v111": "FALSE",
        "selected_repair_scenario_id": selected_id,
        "shadow_integration_plan_decision_created": "TRUE",
        "integration_scope_created": "FALSE",
        "integration_step_plan_created": "FALSE",
        "dependency_audit_created": "FALSE",
        "safety_boundary_audit_passed": "FALSE",
        "v20_113_shadow_integration_dry_run_allowed": "FALSE",
        "next_recommended_action": "V20.112_SHADOW_INTEGRATION_PLAN_REPAIR",
        "blocking_reason": blocking,
        "shadow_integration_plan_status": BLOCKED_STATUS,
        **COMMON_SAFETY,
    }
    write_all([decision], scope_rows, step_rows, dependency_rows, safety_rows, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_111_GATE_CONSUMED=FALSE")
    print("V20_112_SHADOW_INTEGRATION_PLAN_ALLOWED_BY_V111=FALSE")
    print("V20_113_SHADOW_INTEGRATION_DRY_RUN_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def main() -> int:
    missing_inputs = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing_inputs:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing_inputs)

    decision_rows = read_csv(IN_DECISION)
    lineage_rows = read_csv(IN_LINEAGE)
    criteria_rows = read_csv(IN_CRITERIA)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    if not all([decision_rows, lineage_rows, criteria_rows, safety_input_rows, gate_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(decision_rows)
    lineage_in = first(lineage_rows)
    gate_in = first(gate_rows)
    v110_selected_rows = read_csv(IN_V110_SELECTED) if IN_V110_SELECTED.exists() and IN_V110_SELECTED.stat().st_size > 0 else []
    v110_manifest_rows = read_csv(IN_V110_MANIFEST) if IN_V110_MANIFEST.exists() and IN_V110_MANIFEST.stat().st_size > 0 else []

    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v111_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_111_NEXT_STAGE_GATE_001"
    v112_allowed_by_v111 = truthy(gate_in.get("v20_112_shadow_integration_plan_allowed"))
    v111_status = clean(gate_in.get("shadow_acceptance_review_status")) or clean(decision_in.get("shadow_acceptance_review_status"))
    v111_status_passed = v111_status == V111_PASS_STATUS
    selected_matches = (
        selected_id == EXPECTED_SCENARIO_ID
        and selected_id == clean(decision_in.get("selected_repair_scenario_id"))
        and selected_id == clean(lineage_in.get("selected_repair_scenario_id"))
    )
    lineage_valid = truthy(lineage_in.get("lineage_valid")) and truthy(decision_in.get("selected_scenario_lineage_valid"))
    upstream_shadow_only = all(truthy(row.get("shadow_only")) for row in [decision_in, lineage_in, gate_in])
    criteria_passed = all(truthy(row.get("criterion_passed")) for row in criteria_rows)
    upstream_safety_passed = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    counts = prohibited_counts([decision_rows, lineage_rows, criteria_rows, safety_input_rows, gate_rows, v110_selected_rows, v110_manifest_rows])
    prohibited_count = sum(counts.values())
    safety_passed = upstream_safety_passed and prohibited_count == 0

    scope_rows = build_scope(selected_id) if selected_id else []
    step_rows = build_steps(selected_id) if selected_id else []
    dependency_rows = build_dependencies(selected_id, bool(v110_manifest_rows and v110_selected_rows)) if selected_id else []
    integration_scope_created = bool(scope_rows)
    step_plan_created = bool(step_rows)
    dependency_audit_created = bool(dependency_rows)
    planning_only = True
    non_mutating = all(row["mutating_step"] == "FALSE" for row in step_rows) and all(row["creates_weight_mutation"] == "FALSE" for row in scope_rows)
    shadow_only = upstream_shadow_only and all(row.get("shadow_only") == "TRUE" for row in scope_rows + step_rows + dependency_rows)

    checks = {
        "v20_111_gate_consumed": v111_gate_consumed,
        "v20_112_shadow_integration_plan_allowed_by_v111": v112_allowed_by_v111,
        "v20_111_status_passed": v111_status_passed,
        "selected_scenario_matches_v20_111": selected_matches,
        "lineage_valid_from_v20_111": lineage_valid,
        "criteria_passed_from_v20_111": criteria_passed,
        "integration_scope_created": integration_scope_created,
        "integration_step_plan_created": step_plan_created,
        "dependency_audit_created": dependency_audit_created,
        "shadow_only_confirmed": shadow_only,
        "planning_only_confirmed": planning_only,
        "non_mutating_confirmed": non_mutating,
        "safety_boundary_audit_passed": safety_passed,
        "prohibited_action_true_count_zero": prohibited_count == 0,
    }
    all_passed = all(checks.values())
    status = PASS_STATUS if all_passed else BLOCKED_STATUS
    blocking = "" if all_passed else ";".join(name for name, passed in checks.items() if not passed)
    safety_rows = build_safety(counts, safety_passed)
    decision = {
        "decision_check_id": "V20_112_SHADOW_INTEGRATION_PLAN_DECISION_001",
        "v20_111_gate_consumed": tf(v111_gate_consumed),
        "v20_112_shadow_integration_plan_allowed_by_v111": tf(v112_allowed_by_v111),
        "v20_111_final_status": v111_status,
        "v20_111_status_passed": tf(v111_status_passed),
        "selected_repair_scenario_id": selected_id,
        "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID,
        "selected_scenario_matches_v20_111": tf(selected_matches),
        "lineage_valid_from_v20_111": tf(lineage_valid),
        "integration_scope_created": tf(integration_scope_created),
        "integration_step_plan_created": tf(step_plan_created),
        "dependency_audit_created": tf(dependency_audit_created),
        "shadow_only_confirmed": tf(shadow_only),
        "planning_only_confirmed": tf(planning_only),
        "non_mutating_confirmed": tf(non_mutating),
        "safety_boundary_audit_passed": tf(safety_passed),
        "prohibited_action_true_count": str(prohibited_count),
        "all_shadow_integration_plan_checks_passed": tf(all_passed),
        "v20_113_shadow_integration_dry_run_allowed": tf(all_passed),
        "shadow_integration_plan_status": status,
        "blocking_reason": blocking,
        **COMMON_SAFETY,
    }
    gate = {
        "gate_check_id": "V20_112_NEXT_STAGE_GATE_001",
        "v20_111_gate_consumed": tf(v111_gate_consumed),
        "v20_112_shadow_integration_plan_allowed_by_v111": tf(v112_allowed_by_v111),
        "selected_repair_scenario_id": selected_id,
        "shadow_integration_plan_decision_created": "TRUE",
        "integration_scope_created": tf(integration_scope_created),
        "integration_step_plan_created": tf(step_plan_created),
        "dependency_audit_created": tf(dependency_audit_created),
        "safety_boundary_audit_passed": tf(safety_passed),
        "v20_113_shadow_integration_dry_run_allowed": tf(all_passed),
        "next_recommended_action": "V20.113_SHADOW_INTEGRATION_DRY_RUN" if all_passed else "V20.112_SHADOW_INTEGRATION_PLAN_REPAIR",
        "blocking_reason": blocking,
        "shadow_integration_plan_status": status,
        **COMMON_SAFETY,
    }
    write_all([decision], scope_rows, step_rows, dependency_rows, safety_rows, [gate])
    write_report(decision)

    print(status)
    print(f"V20_111_GATE_CONSUMED={tf(v111_gate_consumed)}")
    print(f"V20_112_SHADOW_INTEGRATION_PLAN_ALLOWED_BY_V111={tf(v112_allowed_by_v111)}")
    print(f"V20_111_FINAL_STATUS={v111_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_111={tf(selected_matches)}")
    print(f"LINEAGE_VALID_FROM_V20_111={tf(lineage_valid)}")
    print(f"INTEGRATION_SCOPE_CREATED={tf(integration_scope_created)}")
    print(f"INTEGRATION_STEP_PLAN_CREATED={tf(step_plan_created)}")
    print(f"DEPENDENCY_AUDIT_CREATED={tf(dependency_audit_created)}")
    print(f"SHADOW_ONLY_CONFIRMED={tf(shadow_only)}")
    print(f"PLANNING_ONLY_CONFIRMED={tf(planning_only)}")
    print(f"NON_MUTATING_CONFIRMED={tf(non_mutating)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_113_SHADOW_INTEGRATION_DRY_RUN_ALLOWED={tf(all_passed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
