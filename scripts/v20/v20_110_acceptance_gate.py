#!/usr/bin/env python
"""V20.110 acceptance gate for the selected R11 repair scenario.

This stage consumes the V20.109-R11 robustness validation outputs and decides
whether the selected robust repair scenario is eligible for V20.111 shadow
acceptance review. It creates only audit, decision, manifest, and gate files.
It never creates official weights, official rankings, recommendations, trades,
broker actions, authoritative overwrites, performance claims, or weight changes.
"""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_VALIDATION = CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv"
IN_PERSISTENCE = CONSOLIDATION / "V20_109_R11_120D_TOP20_REPAIR_PERSISTENCE_AUDIT.csv"
IN_QUALITY = CONSOLIDATION / "V20_109_R11_BASELINE_QUALITY_ROBUSTNESS_AUDIT.csv"
IN_STABILITY = CONSOLIDATION / "V20_109_R11_TOP20_TOP40_STABILITY_ROBUSTNESS_AUDIT.csv"
IN_COMPONENT = CONSOLIDATION / "V20_109_R11_COMPONENT_DEVIATION_ROBUSTNESS_AUDIT.csv"
IN_FRAGILITY = CONSOLIDATION / "V20_109_R11_SCENARIO_FRAGILITY_AUDIT.csv"
IN_SELECTION = CONSOLIDATION / "V20_109_R11_SCENARIO_FINAL_SELECTION_CANDIDATE.csv"
IN_R11_GATE = CONSOLIDATION / "V20_109_R11_NEXT_STAGE_GATE.csv"

OUT_DECISION = CONSOLIDATION / "V20_110_ACCEPTANCE_GATE_DECISION.csv"
OUT_SELECTED_AUDIT = CONSOLIDATION / "V20_110_SELECTED_REPAIR_SCENARIO_ACCEPTANCE_AUDIT.csv"
OUT_PRIOR_FAILURE_AUDIT = CONSOLIDATION / "V20_110_PRIOR_FAILURE_REPAIR_ACCEPTANCE_AUDIT.csv"
OUT_BASELINE_AUDIT = CONSOLIDATION / "V20_110_BASELINE_QUALITY_ACCEPTANCE_AUDIT.csv"
OUT_SAFETY_AUDIT = CONSOLIDATION / "V20_110_SAFETY_BOUNDARY_AUDIT.csv"
OUT_MANIFEST = CONSOLIDATION / "V20_110_ACCEPTANCE_CANDIDATE_MANIFEST.csv"
OUT_GATE = CONSOLIDATION / "V20_110_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_110_ACCEPTANCE_GATE_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"

PASS_STATUS = "PASS_V20_110_ACCEPTANCE_GATE_READY_FOR_V20_111"
WARN_STATUS = "WARN_V20_110_ACCEPTANCE_GATE_READY_WITH_GUARD"
BLOCKED_MISSING_STATUS = "BLOCKED_V20_110_MISSING_REQUIRED_R11_INPUTS"
BLOCKED_R11_STATUS = "BLOCKED_V20_110_R11_DID_NOT_ALLOW_ACCEPTANCE_GATE"
BLOCKED_NOT_ROBUST_STATUS = "BLOCKED_V20_110_SELECTED_SCENARIO_NOT_ROBUST"
BLOCKED_SAFETY_STATUS = "BLOCKED_V20_110_SAFETY_BOUNDARY_VIOLATION"
BLOCKED_REQUIREMENTS_STATUS = "BLOCKED_V20_110_ACCEPTANCE_GATE_REQUIREMENTS_NOT_MET"

REQUIRED_INPUTS = [
    IN_VALIDATION,
    IN_PERSISTENCE,
    IN_QUALITY,
    IN_STABILITY,
    IN_COMPONENT,
    IN_FRAGILITY,
    IN_SELECTION,
    IN_R11_GATE,
]

SAFETY_FIELDS = [
    "accepted_weight_created",
    "official_weight_created",
    "official_weights_created",
    "new_weights_created",
    "new_official_rerank_created",
    "official_ranking_created",
    "official_recommendation_created",
    "trade_action_created",
    "broker_action_created",
    "broker_execution_supported",
    "performance_claim_created",
    "performance_effectiveness_claim_created",
    "authoritative_overwrite_created",
    "authoritative_ranking_overwritten",
    "official_promotion_allowed",
    "is_official_weight",
    "weight_mutated",
]

COMMON_SAFETY = {
    "accepted_weight_created": "FALSE",
    "official_weight_created": "FALSE",
    "official_weights_created": "FALSE",
    "new_weights_created": "FALSE",
    "new_official_rerank_created": "FALSE",
    "official_ranking_created": "FALSE",
    "official_recommendation_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "performance_claim_created": "FALSE",
    "performance_effectiveness_claim_created": "FALSE",
    "authoritative_overwrite_created": "FALSE",
    "authoritative_ranking_overwritten": "FALSE",
    "official_promotion_allowed": "FALSE",
    "is_official_weight": "FALSE",
    "weight_mutated": "FALSE",
    "research_only": "TRUE",
    "shadow_only": "TRUE",
    "simulation_only": "TRUE",
}

DECISION_FIELDS = [
    "decision_check_id",
    "r11_next_stage_gate_consumed",
    "r11_v20_110_acceptance_gate_allowed",
    "selected_repair_scenario_id",
    "expected_selected_repair_scenario_id",
    "selected_scenario_exists",
    "selected_scenario_passed_robustness_validation",
    "robust_repair_scenario_count",
    "robust_repair_scenario_count_requirement_met",
    "repair_120d_top20_persistence_accepted",
    "baseline_quality_robustness_accepted",
    "top20_stability_robustness_accepted",
    "top40_stability_robustness_accepted",
    "component_deviation_robustness_accepted",
    "scenario_fragility_audit_consumed",
    "scenario_fragile",
    "duplicate_rank_count",
    "missing_rank_count",
    "safety_boundary_audit_passed",
    "acceptance_candidate_manifest_created",
    "v20_111_shadow_acceptance_review_allowed",
    "v20_111_candidate_acceptance_review_allowed",
    "acceptance_gate_status",
    "blocking_reason",
    *COMMON_SAFETY.keys(),
]
SELECTED_FIELDS = [
    "audit_check_id",
    "selected_repair_scenario_id",
    "r11_selection_candidate_consumed",
    "selected_for_v20_110_review",
    "selected_scenario_matches_expected",
    "repair_persistent",
    "baseline_quality_robustly_preserved",
    "top20_stability_robust",
    "top40_stability_robust",
    "component_deviation_robust",
    "scenario_fragile",
    "selected_scenario_passed_robustness_validation",
    "acceptance_audit_status",
    "acceptance_audit_reason",
    *COMMON_SAFETY.keys(),
]
PRIOR_FAILURE_FIELDS = [
    "audit_check_id",
    "selected_repair_scenario_id",
    "r11_persistence_audit_consumed",
    "repair_120d_top20_validated_by_r10_r2",
    "repair_persistent",
    "repair_120d_top20_persistence_accepted",
    "persistence_status",
    "acceptance_audit_status",
    "acceptance_audit_reason",
    *COMMON_SAFETY.keys(),
]
BASELINE_FIELDS = [
    "audit_check_id",
    "selected_repair_scenario_id",
    "r11_baseline_quality_audit_consumed",
    "baseline_quality_preserved_by_r10_r2",
    "baseline_quality_robustly_preserved",
    "baseline_quality_robustness_accepted",
    "baseline_quality_status",
    "acceptance_audit_status",
    "acceptance_audit_reason",
    *COMMON_SAFETY.keys(),
]
SAFETY_AUDIT_FIELDS = [
    "safety_check_id",
    "r11_outputs_checked",
    "safety_boundary_audit_passed",
    "safety_violation_count",
    "safety_violation_fields",
    "no_official_action_or_weight_mutation_created",
    "safety_audit_status",
    *COMMON_SAFETY.keys(),
]
MANIFEST_FIELDS = [
    "manifest_check_id",
    "candidate_manifest_type",
    "selected_repair_scenario_id",
    "source_stage",
    "target_stage",
    "acceptance_candidate_created",
    "accepted_weights_created",
    "official_weights_created",
    "official_rankings_created",
    "official_recommendations_created",
    "trade_actions_created",
    "broker_actions_created",
    "authoritative_overwrites_created",
    "weight_mutations_created",
    "performance_claims_created",
    "manifest_status",
    *COMMON_SAFETY.keys(),
]
GATE_FIELDS = [
    "gate_check_id",
    "r11_next_stage_gate_consumed",
    "r11_v20_110_acceptance_gate_allowed",
    "acceptance_gate_decision_created",
    "acceptance_candidate_manifest_created",
    "selected_repair_scenario_id",
    "v20_111_shadow_acceptance_review_allowed",
    "v20_111_candidate_acceptance_review_allowed",
    "next_recommended_action",
    "blocking_reason",
    "acceptance_gate_status",
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


def find_one(rows: list[dict[str, str]], field: str, value: str) -> dict[str, str]:
    for row in rows:
        if clean(row.get(field)) == value:
            return row
    return {}


def safety_violations(row_groups: list[list[dict[str, str]]]) -> list[str]:
    violations: list[str] = []
    for rows in row_groups:
        for row in rows:
            for field in SAFETY_FIELDS:
                if field in row and clean(row.get(field)).upper() not in {"", "FALSE"}:
                    violations.append(field)
    return sorted(set(violations))


def blocked_outputs(status: str, reason: str, missing: list[Path] | None = None) -> int:
    missing_reason = ";".join(str(path.relative_to(ROOT)).replace("\\", "/") for path in missing or [])
    blocking_reason = reason if not missing_reason else f"{reason}:{missing_reason}"
    rows = build_outputs(
        status=status,
        blocking_reason=blocking_reason,
        r11_gate_consumed=False,
        r11_allowed=False,
        selected_id="",
        selected_exists=False,
        selected_robust=False,
        robust_count="0",
        robust_count_ok=False,
        persistence_ok=False,
        quality_ok=False,
        top20_ok=False,
        top40_ok=False,
        component_ok=False,
        fragility_consumed=False,
        scenario_fragile=True,
        duplicate_count="",
        missing_count="",
        safety_ok=False,
    )
    write_all(rows)
    write_report(status, blocking_reason, rows["decision"][0])
    print(status)
    print("R11_NEXT_STAGE_GATE_CONSUMED=FALSE")
    print("R11_V20_110_ACCEPTANCE_GATE_ALLOWED=FALSE")
    print("V20_111_SHADOW_ACCEPTANCE_REVIEW_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def build_outputs(
    *,
    status: str,
    blocking_reason: str,
    r11_gate_consumed: bool,
    r11_allowed: bool,
    selected_id: str,
    selected_exists: bool,
    selected_robust: bool,
    robust_count: str,
    robust_count_ok: bool,
    persistence_ok: bool,
    quality_ok: bool,
    top20_ok: bool,
    top40_ok: bool,
    component_ok: bool,
    fragility_consumed: bool,
    scenario_fragile: bool,
    duplicate_count: str,
    missing_count: str,
    safety_ok: bool,
    selection_row: dict[str, str] | None = None,
    persistence_row: dict[str, str] | None = None,
    quality_row: dict[str, str] | None = None,
) -> dict[str, list[dict[str, str]]]:
    allowed = status in {PASS_STATUS, WARN_STATUS}
    manifest_created = selected_exists and selected_robust and safety_ok
    selected_row = selection_row or {}
    prior_row = persistence_row or {}
    baseline_row = quality_row or {}
    next_action = "V20.111_SHADOW_ACCEPTANCE_REVIEW" if allowed else "V20.109-R11_REPAIR_ROBUSTNESS_VALIDATION_REPAIR"
    if status == BLOCKED_R11_STATUS:
        next_action = "V20.109-R11_REPAIR_ROBUSTNESS_VALIDATION"
    elif status == BLOCKED_SAFETY_STATUS:
        next_action = "V20.110_SAFETY_BOUNDARY_REPAIR"

    decision = {
        "decision_check_id": "V20_110_ACCEPTANCE_GATE_DECISION_001",
        "r11_next_stage_gate_consumed": tf(r11_gate_consumed),
        "r11_v20_110_acceptance_gate_allowed": tf(r11_allowed),
        "selected_repair_scenario_id": selected_id,
        "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID,
        "selected_scenario_exists": tf(selected_exists),
        "selected_scenario_passed_robustness_validation": tf(selected_robust),
        "robust_repair_scenario_count": robust_count,
        "robust_repair_scenario_count_requirement_met": tf(robust_count_ok),
        "repair_120d_top20_persistence_accepted": tf(persistence_ok),
        "baseline_quality_robustness_accepted": tf(quality_ok),
        "top20_stability_robustness_accepted": tf(top20_ok),
        "top40_stability_robustness_accepted": tf(top40_ok),
        "component_deviation_robustness_accepted": tf(component_ok),
        "scenario_fragility_audit_consumed": tf(fragility_consumed),
        "scenario_fragile": tf(scenario_fragile),
        "duplicate_rank_count": duplicate_count,
        "missing_rank_count": missing_count,
        "safety_boundary_audit_passed": tf(safety_ok),
        "acceptance_candidate_manifest_created": tf(manifest_created),
        "v20_111_shadow_acceptance_review_allowed": tf(allowed),
        "v20_111_candidate_acceptance_review_allowed": tf(allowed),
        "acceptance_gate_status": status,
        "blocking_reason": blocking_reason,
        **COMMON_SAFETY,
    }
    return {
        "decision": [decision],
        "selected": [{
            "audit_check_id": "V20_110_SELECTED_REPAIR_SCENARIO_ACCEPTANCE_AUDIT_001",
            "selected_repair_scenario_id": selected_id,
            "r11_selection_candidate_consumed": tf(bool(selected_row)),
            "selected_for_v20_110_review": clean(selected_row.get("selected_for_v20_110_review")),
            "selected_scenario_matches_expected": tf(selected_id == EXPECTED_SCENARIO_ID),
            "repair_persistent": clean(selected_row.get("repair_persistent")),
            "baseline_quality_robustly_preserved": clean(selected_row.get("baseline_quality_robustly_preserved")),
            "top20_stability_robust": clean(selected_row.get("top20_stability_robust")),
            "top40_stability_robust": clean(selected_row.get("top40_stability_robust")),
            "component_deviation_robust": clean(selected_row.get("component_deviation_robust")),
            "scenario_fragile": clean(selected_row.get("scenario_fragile")) or tf(scenario_fragile),
            "selected_scenario_passed_robustness_validation": tf(selected_robust),
            "acceptance_audit_status": "ACCEPTED_FOR_V20_111_REVIEW" if selected_robust else "NOT_ACCEPTED_FOR_V20_111_REVIEW",
            "acceptance_audit_reason": "Selected R11 robust repair scenario checked without creating official outputs.",
            **COMMON_SAFETY,
        }],
        "prior": [{
            "audit_check_id": "V20_110_PRIOR_FAILURE_REPAIR_ACCEPTANCE_AUDIT_001",
            "selected_repair_scenario_id": selected_id,
            "r11_persistence_audit_consumed": tf(bool(prior_row)),
            "repair_120d_top20_validated_by_r10_r2": clean(prior_row.get("repair_120d_top20_validated_by_r10_r2")),
            "repair_persistent": clean(prior_row.get("repair_persistent")),
            "repair_120d_top20_persistence_accepted": tf(persistence_ok),
            "persistence_status": clean(prior_row.get("persistence_status")),
            "acceptance_audit_status": "ACCEPTED" if persistence_ok else "BLOCKED",
            "acceptance_audit_reason": "120D_TOP20 prior failure repair persistence was consumed from R11.",
            **COMMON_SAFETY,
        }],
        "baseline": [{
            "audit_check_id": "V20_110_BASELINE_QUALITY_ACCEPTANCE_AUDIT_001",
            "selected_repair_scenario_id": selected_id,
            "r11_baseline_quality_audit_consumed": tf(bool(baseline_row)),
            "baseline_quality_preserved_by_r10_r2": clean(baseline_row.get("baseline_quality_preserved_by_r10_r2")),
            "baseline_quality_robustly_preserved": clean(baseline_row.get("baseline_quality_robustly_preserved")),
            "baseline_quality_robustness_accepted": tf(quality_ok),
            "baseline_quality_status": clean(baseline_row.get("baseline_quality_status")),
            "acceptance_audit_status": "ACCEPTED" if quality_ok else "BLOCKED",
            "acceptance_audit_reason": "Baseline quality robustness was consumed from R11.",
            **COMMON_SAFETY,
        }],
        "safety": [{
            "safety_check_id": "V20_110_SAFETY_BOUNDARY_AUDIT_001",
            "r11_outputs_checked": tf(r11_gate_consumed),
            "safety_boundary_audit_passed": tf(safety_ok),
            "safety_violation_count": "0" if safety_ok else "1",
            "safety_violation_fields": "" if safety_ok else "see_blocking_reason",
            "no_official_action_or_weight_mutation_created": tf(safety_ok),
            "safety_audit_status": "PASS" if safety_ok else "BLOCKED",
            **COMMON_SAFETY,
        }],
        "manifest": [{
            "manifest_check_id": "V20_110_ACCEPTANCE_CANDIDATE_MANIFEST_001",
            "candidate_manifest_type": "SHADOW_ACCEPTANCE_REVIEW_CANDIDATE_ONLY",
            "selected_repair_scenario_id": selected_id,
            "source_stage": "V20.109-R11_REPAIR_ROBUSTNESS_VALIDATION",
            "target_stage": "V20.111_SHADOW_ACCEPTANCE_REVIEW",
            "acceptance_candidate_created": tf(manifest_created),
            "accepted_weights_created": "FALSE",
            "official_weights_created": "FALSE",
            "official_rankings_created": "FALSE",
            "official_recommendations_created": "FALSE",
            "trade_actions_created": "FALSE",
            "broker_actions_created": "FALSE",
            "authoritative_overwrites_created": "FALSE",
            "weight_mutations_created": "FALSE",
            "performance_claims_created": "FALSE",
            "manifest_status": "CANDIDATE_MANIFEST_CREATED" if manifest_created else "CANDIDATE_MANIFEST_BLOCKED",
            **COMMON_SAFETY,
        }],
        "gate": [{
            "gate_check_id": "V20_110_NEXT_STAGE_GATE_001",
            "r11_next_stage_gate_consumed": tf(r11_gate_consumed),
            "r11_v20_110_acceptance_gate_allowed": tf(r11_allowed),
            "acceptance_gate_decision_created": "TRUE",
            "acceptance_candidate_manifest_created": tf(manifest_created),
            "selected_repair_scenario_id": selected_id,
            "v20_111_shadow_acceptance_review_allowed": tf(allowed),
            "v20_111_candidate_acceptance_review_allowed": tf(allowed),
            "next_recommended_action": next_action,
            "blocking_reason": blocking_reason,
            "acceptance_gate_status": status,
            **COMMON_SAFETY,
        }],
    }


def write_all(rows: dict[str, list[dict[str, str]]]) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, rows["decision"])
    write_csv(OUT_SELECTED_AUDIT, SELECTED_FIELDS, rows["selected"])
    write_csv(OUT_PRIOR_FAILURE_AUDIT, PRIOR_FAILURE_FIELDS, rows["prior"])
    write_csv(OUT_BASELINE_AUDIT, BASELINE_FIELDS, rows["baseline"])
    write_csv(OUT_SAFETY_AUDIT, SAFETY_AUDIT_FIELDS, rows["safety"])
    write_csv(OUT_MANIFEST, MANIFEST_FIELDS, rows["manifest"])
    write_csv(OUT_GATE, GATE_FIELDS, rows["gate"])


def write_report(status: str, blocking_reason: str, decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        "\n".join([
            "# V20.110 Acceptance Gate Report",
            "",
            f"- wrapper_status: {status}",
            f"- r11_next_stage_gate_consumed: {decision.get('r11_next_stage_gate_consumed')}",
            f"- r11_v20_110_acceptance_gate_allowed: {decision.get('r11_v20_110_acceptance_gate_allowed')}",
            f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
            f"- selected_scenario_passed_robustness_validation: {decision.get('selected_scenario_passed_robustness_validation')}",
            f"- repair_120d_top20_persistence_accepted: {decision.get('repair_120d_top20_persistence_accepted')}",
            f"- baseline_quality_robustness_accepted: {decision.get('baseline_quality_robustness_accepted')}",
            f"- top20_stability_robustness_accepted: {decision.get('top20_stability_robustness_accepted')}",
            f"- top40_stability_robustness_accepted: {decision.get('top40_stability_robustness_accepted')}",
            f"- component_deviation_robustness_accepted: {decision.get('component_deviation_robustness_accepted')}",
            f"- scenario_fragile: {decision.get('scenario_fragile')}",
            f"- duplicate_rank_count: {decision.get('duplicate_rank_count')}",
            f"- missing_rank_count: {decision.get('missing_rank_count')}",
            f"- safety_boundary_audit_passed: {decision.get('safety_boundary_audit_passed')}",
            f"- v20_111_shadow_acceptance_review_allowed: {decision.get('v20_111_shadow_acceptance_review_allowed')}",
            f"- blocking_reason: {blocking_reason}",
            "- accepted_weight_created: FALSE",
            "- official_weight_created: FALSE",
            "- official_weights_created: FALSE",
            "- official_ranking_created: FALSE",
            "- official_recommendation_created: FALSE",
            "- trade_action_created: FALSE",
            "- broker_action_created: FALSE",
            "- authoritative_ranking_overwritten: FALSE",
            "- weight_mutated: FALSE",
            "- performance_claim_created: FALSE",
        ])
        + "\n",
        encoding="utf-8",
    )


def print_safety_stdout() -> None:
    for flag in [
        "ACCEPTED_WEIGHT_CREATED",
        "OFFICIAL_WEIGHT_CREATED",
        "OFFICIAL_WEIGHTS_CREATED",
        "NEW_WEIGHTS_CREATED",
        "NEW_OFFICIAL_RERANK_CREATED",
        "OFFICIAL_RANKING_CREATED",
        "AUTHORITATIVE_RANKING_OVERWRITTEN",
        "AUTHORITATIVE_OVERWRITE_CREATED",
        "OFFICIAL_RECOMMENDATION_CREATED",
        "TRADE_ACTION_CREATED",
        "BROKER_ACTION_CREATED",
        "BROKER_EXECUTION_SUPPORTED",
        "PERFORMANCE_CLAIM_CREATED",
        "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED",
        "OFFICIAL_PROMOTION_ALLOWED",
        "IS_OFFICIAL_WEIGHT",
        "WEIGHT_MUTATED",
    ]:
        print(f"{flag}=FALSE")


def main() -> int:
    missing_inputs = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing_inputs:
        return blocked_outputs(BLOCKED_MISSING_STATUS, "MISSING_REQUIRED_R11_INPUTS", missing_inputs)

    validation = read_csv(IN_VALIDATION)
    persistence = read_csv(IN_PERSISTENCE)
    quality = read_csv(IN_QUALITY)
    stability = read_csv(IN_STABILITY)
    component = read_csv(IN_COMPONENT)
    fragility = read_csv(IN_FRAGILITY)
    selection = read_csv(IN_SELECTION)
    r11_gate = read_csv(IN_R11_GATE)
    if not all([validation, persistence, quality, stability, component, fragility, selection, r11_gate]):
        return blocked_outputs(BLOCKED_MISSING_STATUS, "EMPTY_REQUIRED_R11_INPUTS")

    gate_row = first(r11_gate)
    validation_row = first(validation)
    selection_row = first(selection)
    selected_id = clean(gate_row.get("selected_repair_scenario_id")) or clean(selection_row.get("selected_repair_scenario_id"))
    selected_persistence = find_one(persistence, "repair_scenario_id", selected_id)
    selected_quality = find_one(quality, "repair_scenario_id", selected_id)
    selected_fragility = find_one(fragility, "repair_scenario_id", selected_id)
    selected_stability = [row for row in stability if clean(row.get("repair_scenario_id")) == selected_id]
    selected_component = [row for row in component if clean(row.get("repair_scenario_id")) == selected_id]

    r11_gate_consumed = clean(gate_row.get("gate_check_id")) == "V20_109_R11_NEXT_STAGE_GATE_001"
    r11_allowed = truthy(gate_row.get("v20_110_acceptance_gate_allowed"))
    robust_count = clean(gate_row.get("robust_repair_scenario_count")) or clean(validation_row.get("robust_repair_scenario_count")) or "0"
    try:
        robust_count_ok = int(robust_count) >= 1
    except ValueError:
        robust_count_ok = False

    duplicate_count = clean(validation_row.get("duplicate_rank_count"))
    missing_count = clean(validation_row.get("missing_rank_count"))
    selected_exists = selected_id == EXPECTED_SCENARIO_ID and bool(selection_row)
    persistence_ok = truthy(selected_persistence.get("repair_120d_top20_validated_by_r10_r2")) and truthy(selected_persistence.get("repair_persistent"))
    quality_ok = truthy(selected_quality.get("baseline_quality_preserved_by_r10_r2")) and truthy(selected_quality.get("baseline_quality_robustly_preserved"))
    top20_ok = any(clean(row.get("top_n")) == "20" and truthy(row.get("stability_robust")) for row in selected_stability)
    top40_ok = any(clean(row.get("top_n")) == "40" and truthy(row.get("stability_robust")) for row in selected_stability)
    component_ok = bool(selected_component) and all(truthy(row.get("component_deviation_robust")) for row in selected_component)
    fragility_consumed = bool(selected_fragility)
    scenario_fragile = truthy(selected_fragility.get("scenario_fragile")) if selected_fragility else True
    ranks_ok = duplicate_count == "0" and missing_count == "0"
    selected_robust = (
        selected_exists
        and truthy(selection_row.get("selected_for_v20_110_review"))
        and truthy(selection_row.get("repair_persistent"))
        and truthy(selection_row.get("baseline_quality_robustly_preserved"))
        and truthy(selection_row.get("top20_stability_robust"))
        and truthy(selection_row.get("top40_stability_robust"))
        and truthy(selection_row.get("component_deviation_robust"))
        and not truthy(selection_row.get("scenario_fragile"))
    )
    violations = safety_violations([validation, persistence, quality, stability, component, fragility, selection, r11_gate])
    safety_ok = not violations

    strict_ok = all([
        r11_gate_consumed,
        r11_allowed,
        selected_exists,
        selected_robust,
        robust_count_ok,
        persistence_ok,
        quality_ok,
        top20_ok,
        top40_ok,
        component_ok,
        fragility_consumed,
        not scenario_fragile,
        ranks_ok,
        safety_ok,
    ])

    if not r11_gate_consumed:
        status = BLOCKED_MISSING_STATUS
        blocking_reason = "R11_NEXT_STAGE_GATE_NOT_CONSUMABLE"
    elif not r11_allowed:
        status = BLOCKED_R11_STATUS
        blocking_reason = "R11_DID_NOT_ALLOW_V20_110_ACCEPTANCE_GATE"
    elif not selected_robust:
        status = BLOCKED_NOT_ROBUST_STATUS
        blocking_reason = "SELECTED_SCENARIO_NOT_ROBUST_FOR_ACCEPTANCE_GATE"
    elif not safety_ok:
        status = BLOCKED_SAFETY_STATUS
        blocking_reason = "SAFETY_BOUNDARY_VIOLATION:" + ";".join(violations)
    elif strict_ok:
        status = PASS_STATUS
        blocking_reason = ""
    else:
        status = BLOCKED_REQUIREMENTS_STATUS
        blocking_reason = "ACCEPTANCE_GATE_REQUIREMENTS_NOT_MET"

    rows = build_outputs(
        status=status,
        blocking_reason=blocking_reason,
        r11_gate_consumed=r11_gate_consumed,
        r11_allowed=r11_allowed,
        selected_id=selected_id,
        selected_exists=selected_exists,
        selected_robust=selected_robust,
        robust_count=robust_count,
        robust_count_ok=robust_count_ok,
        persistence_ok=persistence_ok,
        quality_ok=quality_ok,
        top20_ok=top20_ok,
        top40_ok=top40_ok,
        component_ok=component_ok,
        fragility_consumed=fragility_consumed,
        scenario_fragile=scenario_fragile,
        duplicate_count=duplicate_count,
        missing_count=missing_count,
        safety_ok=safety_ok,
        selection_row=selection_row,
        persistence_row=selected_persistence,
        quality_row=selected_quality,
    )
    if rows["safety"]:
        rows["safety"][0]["safety_violation_count"] = str(len(violations))
        rows["safety"][0]["safety_violation_fields"] = ";".join(violations)
    write_all(rows)
    write_report(status, blocking_reason, rows["decision"][0])

    print(status)
    print(f"R11_NEXT_STAGE_GATE_CONSUMED={tf(r11_gate_consumed)}")
    print(f"R11_V20_110_ACCEPTANCE_GATE_ALLOWED={tf(r11_allowed)}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_PASSED_ROBUSTNESS_VALIDATION={tf(selected_robust)}")
    print(f"ROBUST_REPAIR_SCENARIO_COUNT={robust_count}")
    print(f"REPAIR_120D_TOP20_PERSISTENCE_ACCEPTED={tf(persistence_ok)}")
    print(f"BASELINE_QUALITY_ROBUSTNESS_ACCEPTED={tf(quality_ok)}")
    print(f"TOP20_STABILITY_ROBUSTNESS_ACCEPTED={tf(top20_ok)}")
    print(f"TOP40_STABILITY_ROBUSTNESS_ACCEPTED={tf(top40_ok)}")
    print(f"COMPONENT_DEVIATION_ROBUSTNESS_ACCEPTED={tf(component_ok)}")
    print(f"SCENARIO_FRAGILITY_AUDIT_CONSUMED={tf(fragility_consumed)}")
    print(f"SCENARIO_FRAGILE={tf(scenario_fragile)}")
    print(f"DUPLICATE_RANK_COUNT={duplicate_count}")
    print(f"MISSING_RANK_COUNT={missing_count}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_ok)}")
    print(f"ACCEPTANCE_CANDIDATE_MANIFEST_CREATED={rows['decision'][0]['acceptance_candidate_manifest_created']}")
    print(f"V20_111_SHADOW_ACCEPTANCE_REVIEW_ALLOWED={rows['decision'][0]['v20_111_shadow_acceptance_review_allowed']}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
