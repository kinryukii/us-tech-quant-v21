#!/usr/bin/env python
"""V20.109-R11 repair robustness validation.

This stage validates only R10-R2 scenarios that were already marked as
120D_TOP20 repair validated. It does not create accepted weights, official
weights, official rankings, recommendations, trades, broker payloads, or
performance claims.
"""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_COLLAPSE = CONSOLIDATION / "V20_109_R10_R2_BASELINE_QUALITY_COLLAPSE_AUDIT.csv"
IN_CONSTRAINTS = CONSOLIDATION / "V20_109_R10_R2_QUALITY_PROTECTION_CONSTRAINTS.csv"
IN_SCENARIOS = CONSOLIDATION / "V20_109_R10_R2_QUALITY_PROTECTED_REPAIR_SCENARIOS.csv"
IN_REPAIR = CONSOLIDATION / "V20_109_R10_R2_120D_TOP20_REPAIR_UNDER_QUALITY_FLOOR.csv"
IN_COMPONENT = CONSOLIDATION / "V20_109_R10_R2_COMPONENT_DEVIATION_AUDIT.csv"
IN_OVERLAP = CONSOLIDATION / "V20_109_R10_R2_TOP20_TOP40_OVERLAP_FLOOR_AUDIT.csv"
IN_GUARD = CONSOLIDATION / "V20_109_R10_R2_REPAIR_SELECTION_GUARD.csv"
IN_GATE = CONSOLIDATION / "V20_109_R10_R2_NEXT_STAGE_GATE.csv"

OUT_VALIDATION = CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv"
OUT_PERSISTENCE = CONSOLIDATION / "V20_109_R11_120D_TOP20_REPAIR_PERSISTENCE_AUDIT.csv"
OUT_QUALITY = CONSOLIDATION / "V20_109_R11_BASELINE_QUALITY_ROBUSTNESS_AUDIT.csv"
OUT_STABILITY = CONSOLIDATION / "V20_109_R11_TOP20_TOP40_STABILITY_ROBUSTNESS_AUDIT.csv"
OUT_COMPONENT = CONSOLIDATION / "V20_109_R11_COMPONENT_DEVIATION_ROBUSTNESS_AUDIT.csv"
OUT_FRAGILITY = CONSOLIDATION / "V20_109_R11_SCENARIO_FRAGILITY_AUDIT.csv"
OUT_SELECTION = CONSOLIDATION / "V20_109_R11_SCENARIO_FINAL_SELECTION_CANDIDATE.csv"
OUT_GATE = CONSOLIDATION / "V20_109_R11_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION_REPORT.md"

PASS_STATUS = "PASS_V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION_READY_FOR_V20_110"
PARTIAL_STATUS = "PARTIAL_PASS_V20_109_R11_ROBUSTNESS_VALIDATION_WITH_LIMITED_EVIDENCE"
BLOCKED_MISSING_STATUS = "BLOCKED_V20_109_R11_MISSING_REQUIRED_R10_R2_INPUTS"
BLOCKED_NO_ROBUST_STATUS = "BLOCKED_V20_109_R11_NO_ROBUST_REPAIR_SCENARIO"
WARN_FRAGILE_STATUS = "WARN_V20_109_R11_REPAIR_EFFECTIVE_BUT_FRAGILE"
WARN_GUARD_STATUS = "WARN_V20_109_R11_REPAIR_ROBUST_BUT_ACCEPTANCE_NEEDS_GUARD"

FAMILIES = {"fundamental", "technical", "strategy", "risk", "market_regime", "data_trust"}

VALIDATION_FIELDS = [
    "validation_check_id",
    "r10_r2_gate_consumed",
    "r10_r2_r11_allowed",
    "input_repair_scenario_count",
    "evaluated_validated_repair_scenario_count",
    "excluded_unvalidated_repair_scenario_count",
    "robust_repair_scenario_count",
    "final_selection_candidate_count",
    "selected_repair_scenario_id",
    "duplicate_rank_count",
    "missing_rank_count",
    "repair_persistence_all_passed",
    "baseline_quality_robustness_all_passed",
    "top20_stability_all_passed",
    "top40_stability_all_passed",
    "component_deviation_all_within_cap",
    "fragile_scenario_count",
    "v20_110_acceptance_gate_allowed",
    "validation_status",
    "validation_reason",
    "accepted_weight_created",
    "official_weight_created",
    "new_weights_created",
    "new_official_rerank_created",
    "official_ranking_created",
    "official_recommendation_created",
    "trade_action_created",
    "broker_execution_supported",
    "performance_effectiveness_claim_created",
    "authoritative_ranking_overwritten",
    "research_only",
    "shadow_only",
    "simulation_only",
    "official_promotion_allowed",
    "is_official_weight",
    "weight_mutated",
]
PERSISTENCE_FIELDS = [
    "repair_scenario_id",
    "scenario_family",
    "repair_120d_top20_validated_by_r10_r2",
    "repair_minus_current_shadow_mean_return",
    "repair_minus_baseline_mean_return",
    "repair_minus_baseline_hit_rate",
    "repair_persistent",
    "persistence_status",
    "persistence_reason",
    "research_only",
    "shadow_only",
    "simulation_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "trade_action_created",
    "broker_execution_supported",
]
QUALITY_FIELDS = [
    "repair_scenario_id",
    "baseline_quality_floor",
    "repair_to_baseline_mean_return_ratio",
    "baseline_quality_preserved_by_r10_r2",
    "baseline_quality_robustly_preserved",
    "baseline_quality_status",
    "baseline_quality_reason",
    "research_only",
    "shadow_only",
    "simulation_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "trade_action_created",
    "broker_execution_supported",
]
STABILITY_FIELDS = [
    "repair_scenario_id",
    "top_n",
    "actual_baseline_overlap",
    "overlap_floor",
    "turnover_count",
    "turnover_ratio",
    "overlap_floor_passed_by_r10_r2",
    "stability_robust",
    "stability_status",
    "stability_reason",
    "research_only",
    "shadow_only",
    "simulation_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "trade_action_created",
    "broker_execution_supported",
]
COMPONENT_FIELDS = [
    "repair_scenario_id",
    "factor_family",
    "component_deviation_value",
    "component_deviation_cap",
    "component_deviation_within_cap_by_r10_r2",
    "component_deviation_robust",
    "component_status",
    "component_reason",
    "research_only",
    "shadow_only",
    "simulation_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "trade_action_created",
    "broker_execution_supported",
]
FRAGILITY_FIELDS = [
    "repair_scenario_id",
    "scenario_family",
    "repair_intensity",
    "repair_intensity_cap",
    "top20_turnover_ratio",
    "top40_turnover_ratio",
    "component_max_deviation",
    "fragility_score",
    "scenario_fragile",
    "fragility_status",
    "fragility_reason",
    "diagnostic_only",
    "research_only",
    "shadow_only",
    "simulation_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "trade_action_created",
    "broker_execution_supported",
]
SELECTION_FIELDS = [
    "selection_check_id",
    "selected_repair_scenario_id",
    "selected_scenario_family",
    "selected_for_v20_110_review",
    "selection_basis",
    "repair_persistent",
    "baseline_quality_robustly_preserved",
    "top20_stability_robust",
    "top40_stability_robust",
    "component_deviation_robust",
    "scenario_fragile",
    "accepted_weight_created",
    "official_weight_created",
    "new_weights_created",
    "new_official_rerank_created",
    "official_ranking_created",
    "official_recommendation_created",
    "trade_action_created",
    "broker_execution_supported",
    "performance_effectiveness_claim_created",
    "authoritative_ranking_overwritten",
    "research_only",
    "shadow_only",
    "simulation_only",
    "official_promotion_allowed",
    "is_official_weight",
    "weight_mutated",
]
GATE_FIELDS = [
    "gate_check_id",
    "repair_robustness_validation_created",
    "r10_r2_gate_consumed",
    "evaluated_validated_repair_scenario_count",
    "robust_repair_scenario_count",
    "selected_repair_scenario_id",
    "v20_110_acceptance_gate_allowed",
    "next_recommended_action",
    "blocking_reason",
    "accepted_weight_created",
    "official_weight_created",
    "new_weights_created",
    "new_official_rerank_created",
    "official_ranking_created",
    "official_recommendation_created",
    "trade_action_created",
    "broker_execution_supported",
    "performance_effectiveness_claim_created",
    "authoritative_ranking_overwritten",
    "research_only",
    "shadow_only",
    "simulation_only",
    "official_promotion_allowed",
    "is_official_weight",
    "weight_mutated",
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def dec(value: object) -> Decimal | None:
    try:
        return Decimal(clean(value))
    except (InvalidOperation, ValueError):
        return None


def fmt(value: Decimal | None) -> str:
    return "" if value is None else f"{float(value):.10f}"


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def read_csv(path: Path) -> tuple[list[dict[str, str]], str]:
    if not path.exists() or path.stat().st_size == 0:
        return [], "MISSING_OR_EMPTY"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{key: clean(value) for key, value in row.items()} for row in reader], "OK"


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def safety() -> dict[str, str]:
    return {
        "research_only": "TRUE",
        "shadow_only": "TRUE",
        "simulation_only": "TRUE",
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
    }


def hard_safety() -> dict[str, str]:
    return {
        **safety(),
        "accepted_weight_created": "FALSE",
        "official_weight_created": "FALSE",
        "new_weights_created": "FALSE",
        "new_official_rerank_created": "FALSE",
        "official_ranking_created": "FALSE",
        "performance_effectiveness_claim_created": "FALSE",
        "authoritative_ranking_overwritten": "FALSE",
        "is_official_weight": "FALSE",
        "weight_mutated": "FALSE",
    }


def first_by(rows: list[dict[str, str]], key: str) -> dict[str, dict[str, str]]:
    return {row[key]: row for row in rows if row.get(key)}


def rows_by(rows: list[dict[str, str]], key: str) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        if row.get(key):
            out.setdefault(row[key], []).append(row)
    return out


def main() -> int:
    collapse, s_collapse = read_csv(IN_COLLAPSE)
    constraints, s_constraints = read_csv(IN_CONSTRAINTS)
    scenarios, s_scenarios = read_csv(IN_SCENARIOS)
    repair, s_repair = read_csv(IN_REPAIR)
    components, s_components = read_csv(IN_COMPONENT)
    overlap, s_overlap = read_csv(IN_OVERLAP)
    guard, s_guard = read_csv(IN_GUARD)
    gate, s_gate = read_csv(IN_GATE)
    required_ok = all(
        status == "OK"
        for status in [s_collapse, s_constraints, s_scenarios, s_repair, s_components, s_overlap, s_guard, s_gate]
    )

    gate_row = gate[0] if gate else {}
    collapse_row = collapse[0] if collapse else {}
    r10_r2_gate_consumed = (
        required_ok
        and gate_row.get("v20_109_r11_repair_robustness_validation_allowed") == "TRUE"
        and gate_row.get("v20_110_acceptance_gate_allowed") == "FALSE"
    )
    duplicate_rank_count = int(collapse_row.get("duplicate_rank_count", "0") or "0")
    missing_rank_count = int(collapse_row.get("missing_rank_count", "0") or "0")

    scenario_by_id = first_by(scenarios, "repair_scenario_id")
    repair_by_id = first_by(repair, "repair_scenario_id")
    components_by_id = rows_by(components, "repair_scenario_id")
    overlap_by_id = rows_by(overlap, "repair_scenario_id")
    validated_ids = [
        row["repair_scenario_id"]
        for row in repair
        if row.get("repair_120d_top20_validated") == "TRUE" and row.get("baseline_quality_preserved") == "TRUE"
    ]
    excluded_count = max(0, len(scenarios) - len(validated_ids))

    persistence_rows: list[dict[str, str]] = []
    quality_rows: list[dict[str, str]] = []
    stability_rows: list[dict[str, str]] = []
    component_rows: list[dict[str, str]] = []
    fragility_rows: list[dict[str, str]] = []
    scenario_results: dict[str, dict[str, object]] = {}

    for sid in validated_ids:
        scen = scenario_by_id.get(sid, {})
        rep = repair_by_id.get(sid, {})
        family = scen.get("scenario_family", "")
        repair_minus_current = dec(rep.get("repair_minus_current_shadow_mean_return"))
        repair_minus_baseline = dec(rep.get("repair_minus_baseline_mean_return"))
        repair_minus_hit = dec(rep.get("repair_minus_baseline_hit_rate"))
        baseline_mean = dec(rep.get("baseline_mean_forward_return"))
        repair_mean = dec(rep.get("repair_mean_forward_return"))
        quality_floor = dec(rep.get("baseline_quality_floor")) or Decimal("0.95")
        ratio = repair_mean / baseline_mean if repair_mean is not None and baseline_mean not in (None, Decimal("0")) else None
        repair_intensity = dec(scen.get("repair_intensity")) or Decimal("0")
        intensity_cap = dec(scen.get("repair_intensity_cap")) or Decimal("0.35")

        persistence = rep.get("repair_120d_top20_validated") == "TRUE" and repair_minus_current is not None and repair_minus_current > 0
        quality = rep.get("baseline_quality_preserved") == "TRUE" and ratio is not None and ratio >= quality_floor
        intensity_ok = repair_intensity <= intensity_cap

        persistence_rows.append({
            "repair_scenario_id": sid,
            "scenario_family": family,
            "repair_120d_top20_validated_by_r10_r2": rep.get("repair_120d_top20_validated", "FALSE"),
            "repair_minus_current_shadow_mean_return": fmt(repair_minus_current),
            "repair_minus_baseline_mean_return": fmt(repair_minus_baseline),
            "repair_minus_baseline_hit_rate": fmt(repair_minus_hit),
            "repair_persistent": tf(persistence),
            "persistence_status": "PERSISTENT_120D_TOP20_REPAIR" if persistence else "NON_PERSISTENT_120D_TOP20_REPAIR",
            "persistence_reason": "R10-R2 validated repair remains above current shadow in the 120D_TOP20 target cell.",
            **safety(),
        })
        quality_rows.append({
            "repair_scenario_id": sid,
            "baseline_quality_floor": fmt(quality_floor),
            "repair_to_baseline_mean_return_ratio": fmt(ratio),
            "baseline_quality_preserved_by_r10_r2": rep.get("baseline_quality_preserved", "FALSE"),
            "baseline_quality_robustly_preserved": tf(quality),
            "baseline_quality_status": "BASELINE_QUALITY_ROBUST" if quality else "BASELINE_QUALITY_NOT_ROBUST",
            "baseline_quality_reason": "Repair stays within the R10-R2 baseline quality floor.",
            **safety(),
        })

        top20_ok = False
        top40_ok = False
        top20_turnover = Decimal("1")
        top40_turnover = Decimal("1")
        for row in overlap_by_id.get(sid, []):
            top_n = int(row.get("top_n", "0") or "0")
            turnover_ratio = dec(row.get("turnover_ratio")) or Decimal("1")
            floor_passed = row.get("overlap_floor_passed") == "TRUE"
            stability_threshold = Decimal("0.15") if top_n == 20 else Decimal("0.20")
            stable = floor_passed and turnover_ratio <= stability_threshold
            if top_n == 20:
                top20_ok = stable
                top20_turnover = turnover_ratio
            if top_n == 40:
                top40_ok = stable
                top40_turnover = turnover_ratio
            stability_rows.append({
                "repair_scenario_id": sid,
                "top_n": str(top_n),
                "actual_baseline_overlap": row.get("actual_baseline_overlap", ""),
                "overlap_floor": row.get("overlap_floor", ""),
                "turnover_count": row.get("turnover_count", ""),
                "turnover_ratio": fmt(turnover_ratio),
                "overlap_floor_passed_by_r10_r2": row.get("overlap_floor_passed", "FALSE"),
                "stability_robust": tf(stable),
                "stability_status": "STABILITY_ROBUST" if stable else "STABILITY_FRAGILE",
                "stability_reason": "Overlap floor passed and turnover remained inside the R11 robustness threshold.",
                **safety(),
            })

        component_ok = True
        max_deviation = Decimal("0")
        family_count = 0
        for row in components_by_id.get(sid, []):
            factor = row.get("factor_family", "")
            deviation = dec(row.get("component_deviation_value")) or Decimal("0")
            cap = dec(row.get("component_deviation_cap")) or Decimal("0")
            robust = factor in FAMILIES and row.get("component_deviation_within_cap") == "TRUE" and deviation <= cap
            component_ok = component_ok and robust
            max_deviation = max(max_deviation, deviation)
            family_count += 1
            component_rows.append({
                "repair_scenario_id": sid,
                "factor_family": factor,
                "component_deviation_value": fmt(deviation),
                "component_deviation_cap": fmt(cap),
                "component_deviation_within_cap_by_r10_r2": row.get("component_deviation_within_cap", "FALSE"),
                "component_deviation_robust": tf(robust),
                "component_status": "COMPONENT_DEVIATION_ROBUST" if robust else "COMPONENT_DEVIATION_NOT_ROBUST",
                "component_reason": "R10-R2 component deviation cap is still respected.",
                **safety(),
            })
        component_ok = component_ok and family_count == len(FAMILIES)

        fragility_score = top20_turnover + top40_turnover + max_deviation + repair_intensity
        fragile = not (persistence and quality and top20_ok and top40_ok and component_ok and intensity_ok) or fragility_score > Decimal("0.50")
        fragility_rows.append({
            "repair_scenario_id": sid,
            "scenario_family": family,
            "repair_intensity": fmt(repair_intensity),
            "repair_intensity_cap": fmt(intensity_cap),
            "top20_turnover_ratio": fmt(top20_turnover),
            "top40_turnover_ratio": fmt(top40_turnover),
            "component_max_deviation": fmt(max_deviation),
            "fragility_score": fmt(fragility_score),
            "scenario_fragile": tf(fragile),
            "fragility_status": "SCENARIO_NOT_FRAGILE" if not fragile else "SCENARIO_FRAGILE",
            "fragility_reason": "Fragility combines turnover, component deviation, repair intensity, and failed robustness checks.",
            "diagnostic_only": "TRUE",
            **safety(),
        })
        robust = (
            persistence
            and quality
            and top20_ok
            and top40_ok
            and component_ok
            and intensity_ok
            and not fragile
            and duplicate_rank_count == 0
            and missing_rank_count == 0
        )
        scenario_results[sid] = {
            "robust": robust,
            "persistence": persistence,
            "quality": quality,
            "top20": top20_ok,
            "top40": top40_ok,
            "component": component_ok,
            "fragile": fragile,
            "score": fragility_score,
            "repair_minus_current": repair_minus_current or Decimal("0"),
            "family": family,
        }

    robust_ids = [sid for sid, result in scenario_results.items() if result["robust"]]
    selected_id = ""
    if robust_ids:
        selected_id = sorted(
            robust_ids,
            key=lambda sid: (
                scenario_results[sid]["score"],
                -(scenario_results[sid]["repair_minus_current"]),
                sid,
            ),
        )[0]
    selected = scenario_results.get(selected_id, {})
    v20_110_allowed = bool(selected_id)
    fragile_count = sum(1 for result in scenario_results.values() if result.get("fragile"))

    if not required_ok:
        wrapper_status = BLOCKED_MISSING_STATUS
        next_action = "V20.109-R11_INPUT_REPAIR"
        blocking_reason = "MISSING_REQUIRED_R10_R2_INPUTS"
    elif not r10_r2_gate_consumed:
        wrapper_status = BLOCKED_MISSING_STATUS
        next_action = "V20.109-R10-R2_BASELINE_QUALITY_PROTECTED_PRIOR_FAILURE_REPAIR"
        blocking_reason = "R10_R2_GATE_NOT_CONSUMABLE"
    elif not selected_id:
        wrapper_status = BLOCKED_NO_ROBUST_STATUS if fragile_count == len(scenario_results) else WARN_FRAGILE_STATUS
        next_action = "V20.109-R12_ROBUSTNESS_FAILURE_REPAIR"
        blocking_reason = "NO_ROBUST_REPAIR_SCENARIO"
    else:
        wrapper_status = PASS_STATUS
        next_action = "V20.110_RESEARCH_ACCEPTANCE_GATE_REVIEW"
        blocking_reason = ""

    selection_rows = [{
        "selection_check_id": "V20_109_R11_SCENARIO_FINAL_SELECTION_CANDIDATE_001",
        "selected_repair_scenario_id": selected_id,
        "selected_scenario_family": clean(selected.get("family", "")),
        "selected_for_v20_110_review": tf(v20_110_allowed),
        "selection_basis": "lowest_fragility_score_then_highest_repair_delta_vs_current_shadow",
        "repair_persistent": tf(bool(selected.get("persistence"))),
        "baseline_quality_robustly_preserved": tf(bool(selected.get("quality"))),
        "top20_stability_robust": tf(bool(selected.get("top20"))),
        "top40_stability_robust": tf(bool(selected.get("top40"))),
        "component_deviation_robust": tf(bool(selected.get("component"))),
        "scenario_fragile": tf(bool(selected.get("fragile", True))),
        **hard_safety(),
    }]
    validation_rows = [{
        "validation_check_id": "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION_001",
        "r10_r2_gate_consumed": tf(r10_r2_gate_consumed),
        "r10_r2_r11_allowed": gate_row.get("v20_109_r11_repair_robustness_validation_allowed", "FALSE"),
        "input_repair_scenario_count": str(len(scenarios)),
        "evaluated_validated_repair_scenario_count": str(len(validated_ids)),
        "excluded_unvalidated_repair_scenario_count": str(excluded_count),
        "robust_repair_scenario_count": str(len(robust_ids)),
        "final_selection_candidate_count": str(1 if selected_id else 0),
        "selected_repair_scenario_id": selected_id,
        "duplicate_rank_count": str(duplicate_rank_count),
        "missing_rank_count": str(missing_rank_count),
        "repair_persistence_all_passed": tf(all(bool(r.get("persistence")) for r in scenario_results.values()) if scenario_results else False),
        "baseline_quality_robustness_all_passed": tf(all(bool(r.get("quality")) for r in scenario_results.values()) if scenario_results else False),
        "top20_stability_all_passed": tf(all(bool(r.get("top20")) for r in scenario_results.values()) if scenario_results else False),
        "top40_stability_all_passed": tf(all(bool(r.get("top40")) for r in scenario_results.values()) if scenario_results else False),
        "component_deviation_all_within_cap": tf(all(bool(r.get("component")) for r in scenario_results.values()) if scenario_results else False),
        "fragile_scenario_count": str(fragile_count),
        "v20_110_acceptance_gate_allowed": tf(v20_110_allowed),
        "validation_status": "ROBUST_REPAIR_SCENARIO_SELECTED" if selected_id else "NO_ROBUST_REPAIR_SCENARIO",
        "validation_reason": "R11 validates robustness only; no weights or official outputs are created.",
        **hard_safety(),
    }]
    gate_rows = [{
        "gate_check_id": "V20_109_R11_NEXT_STAGE_GATE_001",
        "repair_robustness_validation_created": tf(required_ok),
        "r10_r2_gate_consumed": tf(r10_r2_gate_consumed),
        "evaluated_validated_repair_scenario_count": str(len(validated_ids)),
        "robust_repair_scenario_count": str(len(robust_ids)),
        "selected_repair_scenario_id": selected_id,
        "v20_110_acceptance_gate_allowed": tf(v20_110_allowed),
        "next_recommended_action": next_action,
        "blocking_reason": blocking_reason,
        **hard_safety(),
    }]

    for path, fields, rows in [
        (OUT_VALIDATION, VALIDATION_FIELDS, validation_rows),
        (OUT_PERSISTENCE, PERSISTENCE_FIELDS, persistence_rows),
        (OUT_QUALITY, QUALITY_FIELDS, quality_rows),
        (OUT_STABILITY, STABILITY_FIELDS, stability_rows),
        (OUT_COMPONENT, COMPONENT_FIELDS, component_rows),
        (OUT_FRAGILITY, FRAGILITY_FIELDS, fragility_rows),
        (OUT_SELECTION, SELECTION_FIELDS, selection_rows),
        (OUT_GATE, GATE_FIELDS, gate_rows),
    ]:
        write_csv(path, fields, rows)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        "\n".join([
            "# V20.109-R11 Repair Robustness Validation Report",
            "",
            f"- wrapper_status: {wrapper_status}",
            f"- r10_r2_gate_consumed: {tf(r10_r2_gate_consumed)}",
            f"- evaluated_validated_repair_scenario_count: {len(validated_ids)}",
            f"- robust_repair_scenario_count: {len(robust_ids)}",
            f"- selected_repair_scenario_id: {selected_id}",
            f"- v20_110_acceptance_gate_allowed: {tf(v20_110_allowed)}",
            "- accepted_weight_created: FALSE",
            "- official_weight_created: FALSE",
            "- official_ranking_created: FALSE",
            "- official_recommendation_created: FALSE",
            "- trade_action_created: FALSE",
            "- broker_execution_supported: FALSE",
            "- performance_effectiveness_claim_created: FALSE",
        ])
        + "\n",
        encoding="utf-8",
    )

    print(wrapper_status)
    print(f"R10_R2_GATE_CONSUMED={tf(r10_r2_gate_consumed)}")
    print(f"EVALUATED_VALIDATED_REPAIR_SCENARIO_COUNT={len(validated_ids)}")
    print(f"EXCLUDED_UNVALIDATED_REPAIR_SCENARIO_COUNT={excluded_count}")
    print(f"ROBUST_REPAIR_SCENARIO_COUNT={len(robust_ids)}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"DUPLICATE_RANK_COUNT={duplicate_rank_count}")
    print(f"MISSING_RANK_COUNT={missing_rank_count}")
    print(f"V20_110_ACCEPTANCE_GATE_ALLOWED={tf(v20_110_allowed)}")
    for flag in [
        "ACCEPTED_WEIGHT_CREATED",
        "OFFICIAL_WEIGHT_CREATED",
        "NEW_WEIGHTS_CREATED",
        "NEW_OFFICIAL_RERANK_CREATED",
        "OFFICIAL_RANKING_CREATED",
        "AUTHORITATIVE_RANKING_OVERWRITTEN",
        "OFFICIAL_RECOMMENDATION_CREATED",
        "TRADE_ACTION_CREATED",
        "BROKER_EXECUTION_SUPPORTED",
        "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED",
        "OFFICIAL_PROMOTION_ALLOWED",
        "IS_OFFICIAL_WEIGHT",
        "WEIGHT_MUTATED",
    ]:
        print(f"{flag}=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
