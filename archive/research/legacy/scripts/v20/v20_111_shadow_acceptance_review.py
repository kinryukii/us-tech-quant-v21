#!/usr/bin/env python
"""V20.111 shadow-only acceptance review.

This stage reviews the V20.110 selected repair scenario for shadow-only
eligibility to proceed to V20.112 integration planning. It emits only review,
lineage, criteria, safety, gate, and report artifacts. It does not create
official recommendations, official rankings, accepted weights, real-book
weights, trades, broker actions, authoritative overwrites, performance claims,
or weight mutations.
"""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_V110_DECISION = CONSOLIDATION / "V20_110_ACCEPTANCE_GATE_DECISION.csv"
IN_V110_GATE = CONSOLIDATION / "V20_110_NEXT_STAGE_GATE.csv"
IN_V110_SELECTED = CONSOLIDATION / "V20_110_SELECTED_REPAIR_SCENARIO_ACCEPTANCE_AUDIT.csv"
IN_V110_SAFETY = CONSOLIDATION / "V20_110_SAFETY_BOUNDARY_AUDIT.csv"
IN_V110_MANIFEST = CONSOLIDATION / "V20_110_ACCEPTANCE_CANDIDATE_MANIFEST.csv"
IN_R11_VALIDATION = CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv"
IN_R11_SELECTION = CONSOLIDATION / "V20_109_R11_SCENARIO_FINAL_SELECTION_CANDIDATE.csv"

OUT_DECISION = CONSOLIDATION / "V20_111_SHADOW_ACCEPTANCE_REVIEW_DECISION.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_111_SELECTED_SCENARIO_LINEAGE_AUDIT.csv"
OUT_CRITERIA = CONSOLIDATION / "V20_111_SHADOW_REVIEW_CRITERIA_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_111_SHADOW_ACCEPTANCE_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_111_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_111_SHADOW_ACCEPTANCE_REVIEW_REPORT.md"

PASS_STATUS = "PASS_V20_111_SHADOW_ACCEPTANCE_REVIEW_READY_FOR_V20_112"
BLOCKED_STATUS = "BLOCKED_V20_111_SHADOW_ACCEPTANCE_REVIEW"

REQUIRED_INPUTS = [
    IN_V110_DECISION,
    IN_V110_GATE,
    IN_V110_SELECTED,
    IN_V110_SAFETY,
    IN_V110_MANIFEST,
    IN_R11_VALIDATION,
    IN_R11_SELECTION,
]

PROHIBITED_FIELDS = [
    "accepted_weight_created",
    "accepted_weights_created",
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
    "performance_claim_created",
    "performance_claims_created",
    "performance_effectiveness_claim_created",
    "official_promotion_allowed",
    "is_official_weight",
]

COMMON_SAFETY = {
    "accepted_weight_created": "FALSE",
    "accepted_weights_created": "FALSE",
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
    "performance_claim_created": "FALSE",
    "performance_claims_created": "FALSE",
    "performance_effectiveness_claim_created": "FALSE",
    "real_book_weight_created": "FALSE",
    "real_book_action_created": "FALSE",
    "official_promotion_allowed": "FALSE",
    "promotion_ready": "FALSE",
    "is_official_weight": "FALSE",
    "research_only": "TRUE",
    "shadow_only": "TRUE",
    "simulation_only": "TRUE",
}

DECISION_FIELDS = [
    "decision_check_id",
    "v20_110_gate_consumed",
    "v20_110_shadow_acceptance_review_allowed",
    "v20_110_decision_consumed",
    "selected_repair_scenario_id",
    "selected_scenario_id_present",
    "selected_scenario_matches_v20_110",
    "lineage_audit_not_empty",
    "selected_scenario_lineage_valid",
    "lineage_source",
    "shadow_only_confirmed",
    "safety_boundary_audit_passed",
    "prohibited_action_true_count",
    "criteria_all_passed",
    "v20_112_shadow_integration_plan_allowed",
    "shadow_acceptance_review_status",
    "blocking_reason",
    *COMMON_SAFETY.keys(),
]
LINEAGE_FIELDS = [
    "lineage_check_id",
    "selected_repair_scenario_id",
    "v20_110_gate_selected_scenario_id",
    "v20_110_manifest_selected_scenario_id",
    "v20_110_selected_audit_selected_scenario_id",
    "r11_validation_selected_scenario_id",
    "r11_selection_selected_scenario_id",
    "v20_110_manifest_candidate_created",
    "v20_110_selected_scenario_passed_robustness_validation",
    "r11_v20_110_acceptance_gate_allowed",
    "r11_selected_for_v20_110_review",
    "lineage_valid",
    "lineage_status",
    "lineage_reason",
    *COMMON_SAFETY.keys(),
]
CRITERIA_FIELDS = [
    "criteria_check_id",
    "criterion_name",
    "required_value",
    "observed_value",
    "criterion_passed",
    "criterion_status",
    "selected_repair_scenario_id",
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
    "v20_110_gate_consumed",
    "v20_110_shadow_acceptance_review_allowed",
    "selected_repair_scenario_id",
    "shadow_acceptance_review_decision_created",
    "selected_scenario_lineage_valid",
    "shadow_only_confirmed",
    "safety_boundary_audit_passed",
    "v20_112_shadow_integration_plan_allowed",
    "next_recommended_action",
    "blocking_reason",
    "shadow_acceptance_review_status",
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


def prohibited_true_counts(row_groups: list[list[dict[str, str]]]) -> dict[str, int]:
    counts = {field: 0 for field in PROHIBITED_FIELDS}
    for rows in row_groups:
        for row in rows:
            for field in PROHIBITED_FIELDS:
                if field in row and truthy(row.get(field)):
                    counts[field] += 1
    return counts


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def write_all(rows: dict[str, list[dict[str, str]]]) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, rows["decision"])
    write_csv(OUT_LINEAGE, LINEAGE_FIELDS, rows["lineage"])
    write_csv(OUT_CRITERIA, CRITERIA_FIELDS, rows["criteria"])
    write_csv(OUT_SAFETY, SAFETY_FIELDS, rows["safety"])
    write_csv(OUT_GATE, GATE_FIELDS, rows["gate"])


def build_rows(
    *,
    status: str,
    blocking_reason: str,
    selected_id: str,
    v110_gate_consumed: bool,
    v110_allowed: bool,
    v110_decision_consumed: bool,
    selected_present: bool,
    selected_matches_v110: bool,
    lineage_valid: bool,
    lineage_source: str,
    shadow_only: bool,
    safety_passed: bool,
    prohibited_count: int,
    criteria: list[tuple[str, str, str, bool]],
    gate_row: dict[str, str] | None = None,
    decision_row: dict[str, str] | None = None,
    selected_row: dict[str, str] | None = None,
    manifest_row: dict[str, str] | None = None,
    r11_validation_row: dict[str, str] | None = None,
    r11_selection_row: dict[str, str] | None = None,
) -> dict[str, list[dict[str, str]]]:
    gate = gate_row or {}
    decision = decision_row or {}
    selected = selected_row or {}
    manifest = manifest_row or {}
    r11_validation = r11_validation_row or {}
    r11_selection = r11_selection_row or {}
    allowed = status == PASS_STATUS
    criteria_all_passed = all(item[3] for item in criteria)
    lineage_rows = [{
        "lineage_check_id": "V20_111_SELECTED_SCENARIO_LINEAGE_AUDIT_001",
        "selected_repair_scenario_id": selected_id,
        "v20_110_gate_selected_scenario_id": clean(gate.get("selected_repair_scenario_id")),
        "v20_110_manifest_selected_scenario_id": clean(manifest.get("selected_repair_scenario_id")),
        "v20_110_selected_audit_selected_scenario_id": clean(selected.get("selected_repair_scenario_id")),
        "r11_validation_selected_scenario_id": clean(r11_validation.get("selected_repair_scenario_id")),
        "r11_selection_selected_scenario_id": clean(r11_selection.get("selected_repair_scenario_id")),
        "v20_110_manifest_candidate_created": clean(manifest.get("acceptance_candidate_created")),
        "v20_110_selected_scenario_passed_robustness_validation": clean(selected.get("selected_scenario_passed_robustness_validation")),
        "r11_v20_110_acceptance_gate_allowed": clean(r11_validation.get("v20_110_acceptance_gate_allowed")),
        "r11_selected_for_v20_110_review": clean(r11_selection.get("selected_for_v20_110_review")),
        "lineage_valid": tf(lineage_valid),
        "lineage_status": "LINEAGE_VALID" if lineage_valid else "LINEAGE_BLOCKED",
        "lineage_reason": "Selected scenario traces through V20.110 manifest and R11 robust selection." if lineage_valid else blocking_reason,
        **COMMON_SAFETY,
    }]
    criteria_rows = []
    for index, (name, required, observed, passed) in enumerate(criteria, start=1):
        criteria_rows.append({
            "criteria_check_id": f"V20_111_SHADOW_REVIEW_CRITERIA_AUDIT_{index:03d}",
            "criterion_name": name,
            "required_value": required,
            "observed_value": observed,
            "criterion_passed": tf(passed),
            "criterion_status": "PASS" if passed else "BLOCKED",
            "selected_repair_scenario_id": selected_id,
            **COMMON_SAFETY,
        })
    decision_rows = [{
        "decision_check_id": "V20_111_SHADOW_ACCEPTANCE_REVIEW_DECISION_001",
        "v20_110_gate_consumed": tf(v110_gate_consumed),
        "v20_110_shadow_acceptance_review_allowed": tf(v110_allowed),
        "v20_110_decision_consumed": tf(v110_decision_consumed),
        "selected_repair_scenario_id": selected_id,
        "selected_scenario_id_present": tf(selected_present),
        "selected_scenario_matches_v20_110": tf(selected_matches_v110),
        "lineage_audit_not_empty": tf(bool(lineage_rows)),
        "selected_scenario_lineage_valid": tf(lineage_valid),
        "lineage_source": lineage_source,
        "shadow_only_confirmed": tf(shadow_only),
        "safety_boundary_audit_passed": tf(safety_passed),
        "prohibited_action_true_count": str(prohibited_count),
        "criteria_all_passed": tf(criteria_all_passed),
        "v20_112_shadow_integration_plan_allowed": tf(allowed),
        "shadow_acceptance_review_status": status,
        "blocking_reason": blocking_reason,
        **COMMON_SAFETY,
    }]
    safety_rows = []
    for field in PROHIBITED_FIELDS:
        observed = 1 if prohibited_count and False else 0
        safety_rows.append({
            "safety_check_id": f"V20_111_SHADOW_ACCEPTANCE_SAFETY_BOUNDARY_AUDIT_{len(safety_rows) + 1:03d}",
            "prohibited_field": field,
            "observed_true_count": str(observed),
            "safety_boundary_passed": tf(safety_passed),
            "safety_status": "PASS" if safety_passed else "BLOCKED",
            "safety_reason": "No prohibited official, real-book, trade, broker, overwrite, mutation, or performance claim action created by V20.111.",
            **COMMON_SAFETY,
        })
    gate_rows = [{
        "gate_check_id": "V20_111_NEXT_STAGE_GATE_001",
        "v20_110_gate_consumed": tf(v110_gate_consumed),
        "v20_110_shadow_acceptance_review_allowed": tf(v110_allowed),
        "selected_repair_scenario_id": selected_id,
        "shadow_acceptance_review_decision_created": "TRUE",
        "selected_scenario_lineage_valid": tf(lineage_valid),
        "shadow_only_confirmed": tf(shadow_only),
        "safety_boundary_audit_passed": tf(safety_passed),
        "v20_112_shadow_integration_plan_allowed": tf(allowed),
        "next_recommended_action": "V20.112_SHADOW_INTEGRATION_PLAN" if allowed else "V20.111_SHADOW_ACCEPTANCE_REVIEW_REPAIR",
        "blocking_reason": blocking_reason,
        "shadow_acceptance_review_status": status,
        **COMMON_SAFETY,
    }]
    return {
        "decision": decision_rows,
        "lineage": lineage_rows,
        "criteria": criteria_rows,
        "safety": safety_rows,
        "gate": gate_rows,
    }


def write_report(status: str, rows: dict[str, list[dict[str, str]]]) -> None:
    decision = rows["decision"][0]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        "\n".join([
            "# V20.111 Shadow Acceptance Review Report",
            "",
            f"- wrapper_status: {status}",
            f"- v20_110_gate_consumed: {decision.get('v20_110_gate_consumed')}",
            f"- v20_110_shadow_acceptance_review_allowed: {decision.get('v20_110_shadow_acceptance_review_allowed')}",
            f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
            f"- selected_scenario_lineage_valid: {decision.get('selected_scenario_lineage_valid')}",
            f"- shadow_only_confirmed: {decision.get('shadow_only_confirmed')}",
            f"- safety_boundary_audit_passed: {decision.get('safety_boundary_audit_passed')}",
            f"- v20_112_shadow_integration_plan_allowed: {decision.get('v20_112_shadow_integration_plan_allowed')}",
            f"- blocking_reason: {decision.get('blocking_reason')}",
            "- accepted_weight_created: FALSE",
            "- official_weight_created: FALSE",
            "- official_ranking_created: FALSE",
            "- official_recommendation_created: FALSE",
            "- trade_action_created: FALSE",
            "- broker_action_created: FALSE",
            "- authoritative_overwrite_created: FALSE",
            "- weight_mutated: FALSE",
            "- performance_claim_created: FALSE",
            "- promotion_ready: FALSE",
        ])
        + "\n",
        encoding="utf-8",
    )


def print_safety_stdout() -> None:
    for flag in [
        "ACCEPTED_WEIGHT_CREATED",
        "ACCEPTED_WEIGHTS_CREATED",
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
        "PERFORMANCE_CLAIM_CREATED",
        "PERFORMANCE_CLAIMS_CREATED",
        "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED",
        "REAL_BOOK_WEIGHT_CREATED",
        "REAL_BOOK_ACTION_CREATED",
        "OFFICIAL_PROMOTION_ALLOWED",
        "PROMOTION_READY",
        "IS_OFFICIAL_WEIGHT",
    ]:
        print(f"{flag}=FALSE")


def blocked(status_reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    reason = status_reason if not missing_text else f"{status_reason}:{missing_text}"
    criteria = [
        ("required_inputs_present", "TRUE", "FALSE", False),
        ("v20_110_shadow_acceptance_review_allowed", "TRUE", "FALSE", False),
        ("selected_scenario_lineage_valid", "TRUE", "FALSE", False),
        ("shadow_only_confirmed", "TRUE", "FALSE", False),
        ("safety_boundary_audit_passed", "TRUE", "FALSE", False),
    ]
    rows = build_rows(
        status=BLOCKED_STATUS,
        blocking_reason=reason,
        selected_id="",
        v110_gate_consumed=False,
        v110_allowed=False,
        v110_decision_consumed=False,
        selected_present=False,
        selected_matches_v110=False,
        lineage_valid=False,
        lineage_source="",
        shadow_only=False,
        safety_passed=False,
        prohibited_count=0,
        criteria=criteria,
    )
    write_all(rows)
    write_report(BLOCKED_STATUS, rows)
    print(BLOCKED_STATUS)
    print("V20_110_GATE_CONSUMED=FALSE")
    print("V20_110_SHADOW_ACCEPTANCE_REVIEW_ALLOWED=FALSE")
    print("SELECTED_SCENARIO_LINEAGE_VALID=FALSE")
    print("SHADOW_ONLY_CONFIRMED=FALSE")
    print("SAFETY_BOUNDARY_AUDIT_PASSED=FALSE")
    print("V20_112_SHADOW_INTEGRATION_PLAN_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def main() -> int:
    missing_inputs = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing_inputs:
        return blocked("MISSING_REQUIRED_INPUTS", missing_inputs)

    v110_decision = read_csv(IN_V110_DECISION)
    v110_gate = read_csv(IN_V110_GATE)
    v110_selected = read_csv(IN_V110_SELECTED)
    v110_safety = read_csv(IN_V110_SAFETY)
    v110_manifest = read_csv(IN_V110_MANIFEST)
    r11_validation = read_csv(IN_R11_VALIDATION)
    r11_selection = read_csv(IN_R11_SELECTION)
    if not all([v110_decision, v110_gate, v110_selected, v110_safety, v110_manifest, r11_validation, r11_selection]):
        return blocked("EMPTY_REQUIRED_INPUTS")

    gate = first(v110_gate)
    decision = first(v110_decision)
    selected = first(v110_selected)
    safety = first(v110_safety)
    manifest = first(v110_manifest)
    r11_v = first(r11_validation)
    r11_s = first(r11_selection)

    selected_id = clean(gate.get("selected_repair_scenario_id")) or clean(decision.get("selected_repair_scenario_id"))
    v110_gate_consumed = clean(gate.get("gate_check_id")) == "V20_110_NEXT_STAGE_GATE_001"
    v110_allowed = truthy(gate.get("v20_111_shadow_acceptance_review_allowed"))
    v110_decision_consumed = clean(decision.get("decision_check_id")) == "V20_110_ACCEPTANCE_GATE_DECISION_001"
    selected_present = bool(selected_id)
    selected_matches_v110 = (
        selected_present
        and selected_id == clean(decision.get("selected_repair_scenario_id"))
        and selected_id == clean(selected.get("selected_repair_scenario_id"))
    )
    manifest_lineage = selected_id == clean(manifest.get("selected_repair_scenario_id")) and truthy(manifest.get("acceptance_candidate_created"))
    r11_lineage = (
        selected_id == clean(r11_v.get("selected_repair_scenario_id"))
        and selected_id == clean(r11_s.get("selected_repair_scenario_id"))
        and truthy(r11_v.get("v20_110_acceptance_gate_allowed"))
        and truthy(r11_s.get("selected_for_v20_110_review"))
    )
    selected_robust = truthy(selected.get("selected_scenario_passed_robustness_validation"))
    lineage_valid = selected_matches_v110 and selected_robust and (manifest_lineage or r11_lineage)
    lineage_source = "V20.110_ACCEPTANCE_CANDIDATE_MANIFEST_AND_V20.109_R11" if manifest_lineage and r11_lineage else "V20.110_ACCEPTANCE_CANDIDATE_MANIFEST" if manifest_lineage else "V20.109_R11" if r11_lineage else ""
    shadow_only = all(truthy(row.get("shadow_only")) and not truthy(row.get("official_promotion_allowed")) for row in [gate, decision, selected, safety, manifest])
    counts = prohibited_true_counts([v110_decision, v110_gate, v110_selected, v110_safety, v110_manifest, r11_validation, r11_selection])
    prohibited_count = sum(counts.values())
    safety_passed = truthy(safety.get("safety_boundary_audit_passed")) and prohibited_count == 0

    criteria = [
        ("v20_110_gate_consumed", "TRUE", tf(v110_gate_consumed), v110_gate_consumed),
        ("v20_110_shadow_acceptance_review_allowed", "TRUE", tf(v110_allowed), v110_allowed),
        ("selected_scenario_id_present", "TRUE", tf(selected_present), selected_present),
        ("selected_scenario_matches_v20_110", "TRUE", tf(selected_matches_v110), selected_matches_v110),
        ("selected_scenario_lineage_valid", "TRUE", tf(lineage_valid), lineage_valid),
        ("shadow_only_confirmed", "TRUE", tf(shadow_only), shadow_only),
        ("safety_boundary_audit_passed", "TRUE", tf(safety_passed), safety_passed),
        ("prohibited_action_true_count", "0", str(prohibited_count), prohibited_count == 0),
    ]
    all_passed = all(item[3] for item in criteria)
    status = PASS_STATUS if all_passed else BLOCKED_STATUS
    blocking_reason = "" if all_passed else ";".join(name for name, _, _, passed in criteria if not passed)

    rows = build_rows(
        status=status,
        blocking_reason=blocking_reason,
        selected_id=selected_id,
        v110_gate_consumed=v110_gate_consumed,
        v110_allowed=v110_allowed,
        v110_decision_consumed=v110_decision_consumed,
        selected_present=selected_present,
        selected_matches_v110=selected_matches_v110,
        lineage_valid=lineage_valid,
        lineage_source=lineage_source,
        shadow_only=shadow_only,
        safety_passed=safety_passed,
        prohibited_count=prohibited_count,
        criteria=criteria,
        gate_row=gate,
        decision_row=decision,
        selected_row=selected,
        manifest_row=manifest,
        r11_validation_row=r11_v,
        r11_selection_row=r11_s,
    )
    for safety_row in rows["safety"]:
        field = safety_row["prohibited_field"]
        safety_row["observed_true_count"] = str(counts.get(field, 0))
    write_all(rows)
    write_report(status, rows)

    print(status)
    print(f"V20_110_GATE_CONSUMED={tf(v110_gate_consumed)}")
    print(f"V20_110_SHADOW_ACCEPTANCE_REVIEW_ALLOWED={tf(v110_allowed)}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_110={tf(selected_matches_v110)}")
    print(f"SELECTED_SCENARIO_LINEAGE_VALID={tf(lineage_valid)}")
    print(f"SHADOW_ONLY_CONFIRMED={tf(shadow_only)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_112_SHADOW_INTEGRATION_PLAN_ALLOWED={tf(status == PASS_STATUS)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
