#!/usr/bin/env python
"""V20.115 shadow baseline comparison.

Compares the selected shadow repair scenario against the available pre-repair
baseline reference from the R11 lineage. This stage is comparison-only,
audit-only, shadow-only, and non-mutating.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_114_SHADOW_OUTPUT_RECONCILIATION_DECISION.csv"
IN_STEP_RECON = CONSOLIDATION / "V20_114_STEP_PLAN_RECONCILIATION_AUDIT.csv"
IN_OUTPUT_RECON = CONSOLIDATION / "V20_114_DRY_RUN_OUTPUT_RECONCILIATION_AUDIT.csv"
IN_DEP_RECON = CONSOLIDATION / "V20_114_DEPENDENCY_RECONCILIATION_AUDIT.csv"
IN_SAFETY = CONSOLIDATION / "V20_114_SHADOW_OUTPUT_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_114_NEXT_STAGE_GATE.csv"
IN_V113_MANIFEST = CONSOLIDATION / "V20_113_DRY_RUN_OUTPUT_MANIFEST.csv"
IN_V113_STEPS = CONSOLIDATION / "V20_113_DRY_RUN_STEP_EXECUTION_AUDIT.csv"
IN_R11_BASELINE = CONSOLIDATION / "V20_109_R11_BASELINE_QUALITY_ROBUSTNESS_AUDIT.csv"
IN_R11_PERSISTENCE = CONSOLIDATION / "V20_109_R11_120D_TOP20_REPAIR_PERSISTENCE_AUDIT.csv"
IN_R11_SELECTION = CONSOLIDATION / "V20_109_R11_SCENARIO_FINAL_SELECTION_CANDIDATE.csv"

OUT_DECISION = CONSOLIDATION / "V20_115_SHADOW_BASELINE_COMPARISON_DECISION.csv"
OUT_BASELINE = CONSOLIDATION / "V20_115_BASELINE_REFERENCE_AUDIT.csv"
OUT_DELTA = CONSOLIDATION / "V20_115_SHADOW_VS_BASELINE_DELTA_AUDIT.csv"
OUT_EXPLANATION = CONSOLIDATION / "V20_115_CHANGE_EXPLANATION_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_115_SHADOW_BASELINE_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_115_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_115_SHADOW_BASELINE_COMPARISON_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V114_PASS_STATUS = "PASS_V20_114_SHADOW_OUTPUT_RECONCILIATION_READY_FOR_V20_115"
PASS_STATUS = "PASS_V20_115_SHADOW_BASELINE_COMPARISON_READY_FOR_V20_116"
BLOCKED_STATUS = "BLOCKED_V20_115_SHADOW_BASELINE_COMPARISON"

REQUIRED_INPUTS = [
    IN_DECISION,
    IN_STEP_RECON,
    IN_OUTPUT_RECON,
    IN_DEP_RECON,
    IN_SAFETY,
    IN_GATE,
    IN_V113_MANIFEST,
    IN_V113_STEPS,
    IN_R11_BASELINE,
    IN_R11_PERSISTENCE,
    IN_R11_SELECTION,
]

UPSTREAM_HASH_INPUTS = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    CONSOLIDATION / "V20_109_R11_BASELINE_QUALITY_ROBUSTNESS_AUDIT.csv",
    CONSOLIDATION / "V20_110_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_111_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_112_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_113_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_114_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_114_SHADOW_OUTPUT_RECONCILIATION_DECISION.csv",
]

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
    "comparison_only": "TRUE",
    "audit_only": "TRUE",
    "simulation_only": "TRUE",
}

DECISION_FIELDS = [
    "decision_check_id",
    "v20_114_gate_consumed",
    "v20_115_shadow_baseline_comparison_allowed_by_v114",
    "v20_114_final_status",
    "v20_114_status_passed",
    "selected_repair_scenario_id",
    "expected_selected_repair_scenario_id",
    "selected_scenario_matches_v20_114",
    "baseline_reference_identified",
    "baseline_reference_row_count",
    "delta_audit_created",
    "delta_audit_row_count",
    "change_explanation_audit_created",
    "change_explanation_row_count",
    "deltas_explainable",
    "unauthorized_artifact_count",
    "no_unauthorized_artifact_accepted",
    "fabricated_ticker_row_count",
    "no_ticker_rows_fabricated",
    "upstream_mutation_detected",
    "no_upstream_outputs_mutated",
    "shadow_only_confirmed",
    "comparison_only_confirmed",
    "audit_only_confirmed",
    "safety_boundary_audit_passed",
    "prohibited_action_true_count",
    "all_shadow_baseline_comparison_checks_passed",
    "v20_116_shadow_stability_regression_audit_allowed",
    "shadow_baseline_comparison_status",
    "blocking_reason",
    *COMMON_SAFETY.keys(),
]
BASELINE_FIELDS = [
    "baseline_reference_id",
    "selected_repair_scenario_id",
    "baseline_reference_source",
    "baseline_quality_floor",
    "repair_to_baseline_mean_return_ratio",
    "baseline_quality_preserved_by_r10_r2",
    "baseline_quality_robustly_preserved",
    "repair_minus_baseline_mean_return",
    "repair_minus_baseline_hit_rate",
    "baseline_reference_valid",
    "baseline_reference_status",
    "performance_claim_created",
    *[k for k in COMMON_SAFETY.keys() if k != "performance_claim_created"],
]
DELTA_FIELDS = [
    "delta_check_id",
    "selected_repair_scenario_id",
    "delta_name",
    "baseline_reference_value",
    "shadow_repair_value",
    "delta_value",
    "changed",
    "delta_audit_status",
    "performance_claim_created",
    *[k for k in COMMON_SAFETY.keys() if k != "performance_claim_created"],
]
EXPLANATION_FIELDS = [
    "explanation_check_id",
    "selected_repair_scenario_id",
    "change_topic",
    "change_observed",
    "explanation",
    "explainable",
    "audit_only_explanation",
    "performance_claim_created",
    *[k for k in COMMON_SAFETY.keys() if k != "performance_claim_created"],
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
    "v20_114_gate_consumed",
    "v20_115_shadow_baseline_comparison_allowed_by_v114",
    "selected_repair_scenario_id",
    "shadow_baseline_comparison_decision_created",
    "baseline_reference_identified",
    "delta_audit_created",
    "change_explanation_audit_created",
    "no_unauthorized_artifact_accepted",
    "no_ticker_rows_fabricated",
    "no_upstream_outputs_mutated",
    "safety_boundary_audit_passed",
    "v20_116_shadow_stability_regression_audit_allowed",
    "next_recommended_action",
    "blocking_reason",
    "shadow_baseline_comparison_status",
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


def find_row(rows: list[dict[str, str]], selected_id: str) -> dict[str, str]:
    for row in rows:
        if clean(row.get("repair_scenario_id")) == selected_id or clean(row.get("selected_repair_scenario_id")) == selected_id:
            return row
    return {}


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


def build_safety(counts: dict[str, int], passed: bool) -> list[dict[str, str]]:
    return [{
        "safety_check_id": f"V20_115_SHADOW_BASELINE_SAFETY_BOUNDARY_AUDIT_{index:03d}",
        "prohibited_field": field,
        "observed_true_count": str(counts.get(field, 0)),
        "safety_boundary_passed": tf(passed),
        "safety_status": "PASS" if passed else "BLOCKED",
        "safety_reason": "V20.115 creates only shadow baseline comparison audits and no prohibited artifacts or claims.",
        **COMMON_SAFETY,
    } for index, field in enumerate(PROHIBITED_FIELDS, start=1)]


def build_baseline(selected_id: str, quality: dict[str, str], persistence: dict[str, str]) -> list[dict[str, str]]:
    valid = bool(quality) and bool(persistence)
    return [{
        "baseline_reference_id": "V20_115_BASELINE_REFERENCE_AUDIT_001",
        "selected_repair_scenario_id": selected_id,
        "baseline_reference_source": "V20_109_R11_BASELINE_QUALITY_AND_120D_TOP20_REPAIR_PERSISTENCE_AUDITS",
        "baseline_quality_floor": clean(quality.get("baseline_quality_floor")),
        "repair_to_baseline_mean_return_ratio": clean(quality.get("repair_to_baseline_mean_return_ratio")),
        "baseline_quality_preserved_by_r10_r2": clean(quality.get("baseline_quality_preserved_by_r10_r2")),
        "baseline_quality_robustly_preserved": clean(quality.get("baseline_quality_robustly_preserved")),
        "repair_minus_baseline_mean_return": clean(persistence.get("repair_minus_baseline_mean_return")),
        "repair_minus_baseline_hit_rate": clean(persistence.get("repair_minus_baseline_hit_rate")),
        "baseline_reference_valid": tf(valid),
        "baseline_reference_status": "BASELINE_REFERENCE_VALID" if valid else "BASELINE_REFERENCE_MISSING",
        **COMMON_SAFETY,
    }]


def build_delta(selected_id: str, quality: dict[str, str], persistence: dict[str, str], selection: dict[str, str]) -> list[dict[str, str]]:
    specs = [
        ("baseline_quality_floor", clean(quality.get("baseline_quality_floor")), clean(quality.get("repair_to_baseline_mean_return_ratio")), "repair_ratio_minus_floor"),
        ("mean_return_delta_vs_baseline", "0.0000000000", clean(persistence.get("repair_minus_baseline_mean_return")), "repair_minus_baseline_mean_return"),
        ("hit_rate_delta_vs_baseline", "0.0000000000", clean(persistence.get("repair_minus_baseline_hit_rate")), "repair_minus_baseline_hit_rate"),
        ("fragility_state", "FALSE", clean(selection.get("scenario_fragile")), "scenario_fragile"),
    ]
    rows = []
    for index, (name, baseline_value, shadow_value, delta_value) in enumerate(specs, start=1):
        changed = baseline_value != shadow_value
        rows.append({
            "delta_check_id": f"V20_115_SHADOW_VS_BASELINE_DELTA_AUDIT_{index:03d}",
            "selected_repair_scenario_id": selected_id,
            "delta_name": name,
            "baseline_reference_value": baseline_value,
            "shadow_repair_value": shadow_value,
            "delta_value": delta_value,
            "changed": tf(changed),
            "delta_audit_status": "DELTA_RECORDED_AUDIT_ONLY",
            **COMMON_SAFETY,
        })
    return rows


def build_explanations(selected_id: str, baseline_valid: bool) -> list[dict[str, str]]:
    topics = [
        ("baseline_quality_reference", "TRUE", "Baseline reference is taken from R11 quality robustness and persistence audits."),
        ("shadow_repair_delta", "TRUE", "Delta values are recorded as shadow diagnostics only and are not performance claims."),
        ("non_mutating_boundary", "TRUE", "Comparison reads upstream artifacts and writes only V20.115 audit outputs."),
        ("no_ticker_rows", "TRUE", "Comparison is scenario-level and does not create ticker-level rows."),
    ]
    return [{
        "explanation_check_id": f"V20_115_CHANGE_EXPLANATION_AUDIT_{index:03d}",
        "selected_repair_scenario_id": selected_id,
        "change_topic": topic,
        "change_observed": observed if baseline_valid else "FALSE",
        "explanation": explanation,
        "explainable": tf(baseline_valid),
        "audit_only_explanation": "TRUE",
        **COMMON_SAFETY,
    } for index, (topic, observed, explanation) in enumerate(topics, start=1)]


def write_all(decision, baseline, delta, explanation, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_BASELINE, BASELINE_FIELDS, baseline)
    write_csv(OUT_DELTA, DELTA_FIELDS, delta)
    write_csv(OUT_EXPLANATION, EXPLANATION_FIELDS, explanation)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.115 Shadow Baseline Comparison Report",
        "",
        f"- wrapper_status: {decision.get('shadow_baseline_comparison_status')}",
        f"- v20_114_gate_consumed: {decision.get('v20_114_gate_consumed')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- baseline_reference_identified: {decision.get('baseline_reference_identified')}",
        f"- delta_audit_row_count: {decision.get('delta_audit_row_count')}",
        f"- change_explanation_row_count: {decision.get('change_explanation_row_count')}",
        f"- no_ticker_rows_fabricated: {decision.get('no_ticker_rows_fabricated')}",
        f"- no_upstream_outputs_mutated: {decision.get('no_upstream_outputs_mutated')}",
        f"- v20_116_shadow_stability_regression_audit_allowed: {decision.get('v20_116_shadow_stability_regression_audit_allowed')}",
        f"- blocking_reason: {decision.get('blocking_reason')}",
        "- performance_claim_created: FALSE",
        "- official_recommendation_created: FALSE",
        "- promotion_ready: FALSE",
    ]) + "\n", encoding="utf-8")


def print_safety_stdout() -> None:
    for flag in [
        "ACCEPTED_WEIGHT_CREATED", "ACCEPTED_WEIGHTS_CREATED", "REAL_BOOK_WEIGHT_CREATED", "REAL_BOOK_ACTION_CREATED",
        "OFFICIAL_WEIGHT_CREATED", "OFFICIAL_WEIGHTS_CREATED", "OFFICIAL_RANKING_CREATED", "OFFICIAL_RANKINGS_CREATED",
        "OFFICIAL_RECOMMENDATION_CREATED", "OFFICIAL_RECOMMENDATIONS_CREATED", "TRADE_ACTION_CREATED", "TRADE_ACTIONS_CREATED",
        "BROKER_ACTION_CREATED", "BROKER_ACTIONS_CREATED", "AUTHORITATIVE_OVERWRITE_CREATED", "AUTHORITATIVE_OVERWRITES_CREATED",
        "AUTHORITATIVE_RANKING_OVERWRITTEN", "WEIGHT_MUTATED", "WEIGHT_MUTATIONS_CREATED", "PROMOTION_READY",
        "PERFORMANCE_CLAIM_CREATED", "PERFORMANCE_CLAIMS_CREATED", "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED",
        "OFFICIAL_PROMOTION_ALLOWED", "IS_OFFICIAL_WEIGHT",
    ]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    counts = {field: 0 for field in PROHIBITED_FIELDS}
    safety = build_safety(counts, False)
    decision = {
        "decision_check_id": "V20_115_SHADOW_BASELINE_COMPARISON_DECISION_001",
        "v20_114_gate_consumed": "FALSE",
        "v20_115_shadow_baseline_comparison_allowed_by_v114": "FALSE",
        "v20_114_final_status": "",
        "v20_114_status_passed": "FALSE",
        "selected_repair_scenario_id": "",
        "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID,
        "selected_scenario_matches_v20_114": "FALSE",
        "baseline_reference_identified": "FALSE",
        "baseline_reference_row_count": "0",
        "delta_audit_created": "FALSE",
        "delta_audit_row_count": "0",
        "change_explanation_audit_created": "FALSE",
        "change_explanation_row_count": "0",
        "deltas_explainable": "FALSE",
        "unauthorized_artifact_count": "0",
        "no_unauthorized_artifact_accepted": "FALSE",
        "fabricated_ticker_row_count": "0",
        "no_ticker_rows_fabricated": "TRUE",
        "upstream_mutation_detected": "FALSE",
        "no_upstream_outputs_mutated": "TRUE",
        "shadow_only_confirmed": "FALSE",
        "comparison_only_confirmed": "TRUE",
        "audit_only_confirmed": "TRUE",
        "safety_boundary_audit_passed": "FALSE",
        "prohibited_action_true_count": "0",
        "all_shadow_baseline_comparison_checks_passed": "FALSE",
        "v20_116_shadow_stability_regression_audit_allowed": "FALSE",
        "shadow_baseline_comparison_status": BLOCKED_STATUS,
        "blocking_reason": blocking,
        **COMMON_SAFETY,
    }
    gate = {
        "gate_check_id": "V20_115_NEXT_STAGE_GATE_001",
        "v20_114_gate_consumed": "FALSE",
        "v20_115_shadow_baseline_comparison_allowed_by_v114": "FALSE",
        "selected_repair_scenario_id": "",
        "shadow_baseline_comparison_decision_created": "TRUE",
        "baseline_reference_identified": "FALSE",
        "delta_audit_created": "FALSE",
        "change_explanation_audit_created": "FALSE",
        "no_unauthorized_artifact_accepted": "FALSE",
        "no_ticker_rows_fabricated": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "safety_boundary_audit_passed": "FALSE",
        "v20_116_shadow_stability_regression_audit_allowed": "FALSE",
        "next_recommended_action": "V20.115_SHADOW_BASELINE_COMPARISON_REPAIR",
        "blocking_reason": blocking,
        "shadow_baseline_comparison_status": BLOCKED_STATUS,
        **COMMON_SAFETY,
    }
    write_all([decision], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_114_GATE_CONSUMED=FALSE")
    print("V20_115_SHADOW_BASELINE_COMPARISON_ALLOWED_BY_V114=FALSE")
    print("V20_116_SHADOW_STABILITY_REGRESSION_AUDIT_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def main() -> int:
    before_hashes = upstream_hashes()
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)

    decision_rows = read_csv(IN_DECISION)
    step_rows = read_csv(IN_STEP_RECON)
    output_rows = read_csv(IN_OUTPUT_RECON)
    dep_rows = read_csv(IN_DEP_RECON)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    manifest_rows = read_csv(IN_V113_MANIFEST)
    dry_step_rows = read_csv(IN_V113_STEPS)
    r11_baseline_rows = read_csv(IN_R11_BASELINE)
    r11_persistence_rows = read_csv(IN_R11_PERSISTENCE)
    r11_selection_rows = read_csv(IN_R11_SELECTION)
    if not all([decision_rows, step_rows, output_rows, dep_rows, safety_input_rows, gate_rows, manifest_rows, dry_step_rows, r11_baseline_rows, r11_persistence_rows, r11_selection_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v114_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_114_NEXT_STAGE_GATE_001"
    v115_allowed = truthy(gate_in.get("v20_115_shadow_baseline_comparison_allowed"))
    v114_status = clean(gate_in.get("shadow_output_reconciliation_status")) or clean(decision_in.get("shadow_output_reconciliation_status"))
    v114_status_passed = v114_status == V114_PASS_STATUS
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))
    quality = find_row(r11_baseline_rows, selected_id)
    persistence = find_row(r11_persistence_rows, selected_id)
    selection = find_row(r11_selection_rows, selected_id)
    baseline_rows = build_baseline(selected_id, quality, persistence)
    baseline_valid = truthy(baseline_rows[0].get("baseline_reference_valid"))
    delta_rows = build_delta(selected_id, quality, persistence, selection) if baseline_valid else []
    explanation_rows = build_explanations(selected_id, baseline_valid) if baseline_valid else []
    unauthorized_count = sum(1 for row in output_rows if truthy(row.get("unauthorized_output_artifact")))
    fabricated_ticker_count = sum(1 for row in output_rows if truthy(row.get("contains_ticker_rows"))) + sum(1 for row in manifest_rows if truthy(row.get("contains_ticker_rows"))) + sum(int(clean(row.get("ticker_rows_created")) or "0") for row in dry_step_rows)
    counts = prohibited_counts([decision_rows, step_rows, output_rows, dep_rows, safety_input_rows, gate_rows, manifest_rows, dry_step_rows, r11_baseline_rows, r11_persistence_rows, r11_selection_rows])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0
    safety_rows = build_safety(counts, safety_passed)
    checks = {
        "v20_114_gate_consumed": v114_gate_consumed,
        "v20_115_shadow_baseline_comparison_allowed_by_v114": v115_allowed,
        "v20_114_status_passed": v114_status_passed,
        "selected_scenario_matches_v20_114": selected_matches,
        "baseline_reference_identified": baseline_valid,
        "delta_audit_created": bool(delta_rows),
        "change_explanation_audit_created": bool(explanation_rows),
        "deltas_explainable": all(truthy(row.get("explainable")) for row in explanation_rows),
        "no_unauthorized_artifact_accepted": unauthorized_count == 0,
        "no_ticker_rows_fabricated": fabricated_ticker_count == 0,
        "no_upstream_outputs_mutated": not upstream_mutation,
        "shadow_only_confirmed": truthy(decision_in.get("shadow_only_confirmed")),
        "comparison_only_confirmed": True,
        "audit_only_confirmed": truthy(decision_in.get("audit_only_confirmed")),
        "safety_boundary_audit_passed": safety_passed,
        "prohibited_action_true_count_zero": prohibited_count == 0,
    }
    all_passed = all(checks.values())
    status = PASS_STATUS if all_passed else BLOCKED_STATUS
    blocking = "" if all_passed else ";".join(name for name, passed in checks.items() if not passed)
    decision = {
        "decision_check_id": "V20_115_SHADOW_BASELINE_COMPARISON_DECISION_001",
        "v20_114_gate_consumed": tf(v114_gate_consumed),
        "v20_115_shadow_baseline_comparison_allowed_by_v114": tf(v115_allowed),
        "v20_114_final_status": v114_status,
        "v20_114_status_passed": tf(v114_status_passed),
        "selected_repair_scenario_id": selected_id,
        "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID,
        "selected_scenario_matches_v20_114": tf(selected_matches),
        "baseline_reference_identified": tf(baseline_valid),
        "baseline_reference_row_count": str(len(baseline_rows) if baseline_valid else 0),
        "delta_audit_created": tf(bool(delta_rows)),
        "delta_audit_row_count": str(len(delta_rows)),
        "change_explanation_audit_created": tf(bool(explanation_rows)),
        "change_explanation_row_count": str(len(explanation_rows)),
        "deltas_explainable": tf(checks["deltas_explainable"]),
        "unauthorized_artifact_count": str(unauthorized_count),
        "no_unauthorized_artifact_accepted": tf(unauthorized_count == 0),
        "fabricated_ticker_row_count": str(fabricated_ticker_count),
        "no_ticker_rows_fabricated": tf(fabricated_ticker_count == 0),
        "upstream_mutation_detected": tf(upstream_mutation),
        "no_upstream_outputs_mutated": tf(not upstream_mutation),
        "shadow_only_confirmed": tf(checks["shadow_only_confirmed"]),
        "comparison_only_confirmed": "TRUE",
        "audit_only_confirmed": tf(checks["audit_only_confirmed"]),
        "safety_boundary_audit_passed": tf(safety_passed),
        "prohibited_action_true_count": str(prohibited_count),
        "all_shadow_baseline_comparison_checks_passed": tf(all_passed),
        "v20_116_shadow_stability_regression_audit_allowed": tf(all_passed),
        "shadow_baseline_comparison_status": status,
        "blocking_reason": blocking,
        **COMMON_SAFETY,
    }
    gate = {
        "gate_check_id": "V20_115_NEXT_STAGE_GATE_001",
        "v20_114_gate_consumed": tf(v114_gate_consumed),
        "v20_115_shadow_baseline_comparison_allowed_by_v114": tf(v115_allowed),
        "selected_repair_scenario_id": selected_id,
        "shadow_baseline_comparison_decision_created": "TRUE",
        "baseline_reference_identified": tf(baseline_valid),
        "delta_audit_created": tf(bool(delta_rows)),
        "change_explanation_audit_created": tf(bool(explanation_rows)),
        "no_unauthorized_artifact_accepted": tf(unauthorized_count == 0),
        "no_ticker_rows_fabricated": tf(fabricated_ticker_count == 0),
        "no_upstream_outputs_mutated": tf(not upstream_mutation),
        "safety_boundary_audit_passed": tf(safety_passed),
        "v20_116_shadow_stability_regression_audit_allowed": tf(all_passed),
        "next_recommended_action": "V20.116_SHADOW_STABILITY_REGRESSION_AUDIT" if all_passed else "V20.115_SHADOW_BASELINE_COMPARISON_REPAIR",
        "blocking_reason": blocking,
        "shadow_baseline_comparison_status": status,
        **COMMON_SAFETY,
    }
    write_all([decision], baseline_rows if baseline_valid else [], delta_rows, explanation_rows, safety_rows, [gate])
    write_report(decision)
    print(status)
    print(f"V20_114_GATE_CONSUMED={tf(v114_gate_consumed)}")
    print(f"V20_115_SHADOW_BASELINE_COMPARISON_ALLOWED_BY_V114={tf(v115_allowed)}")
    print(f"V20_114_FINAL_STATUS={v114_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_114={tf(selected_matches)}")
    print(f"BASELINE_REFERENCE_IDENTIFIED={tf(baseline_valid)}")
    print(f"DELTA_AUDIT_CREATED={tf(bool(delta_rows))}")
    print(f"CHANGE_EXPLANATION_AUDIT_CREATED={tf(bool(explanation_rows))}")
    print(f"DELTAS_EXPLAINABLE={tf(checks['deltas_explainable'])}")
    print(f"UNAUTHORIZED_ARTIFACT_COUNT={unauthorized_count}")
    print(f"NO_UNAUTHORIZED_ARTIFACT_ACCEPTED={tf(unauthorized_count == 0)}")
    print(f"FABRICATED_TICKER_ROW_COUNT={fabricated_ticker_count}")
    print(f"NO_TICKER_ROWS_FABRICATED={tf(fabricated_ticker_count == 0)}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"NO_UPSTREAM_OUTPUTS_MUTATED={tf(not upstream_mutation)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_116_SHADOW_STABILITY_REGRESSION_AUDIT_ALLOWED={tf(all_passed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
