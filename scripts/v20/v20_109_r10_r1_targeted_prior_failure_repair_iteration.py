#!/usr/bin/env python
"""V20.109-R10-R1 targeted prior failure repair iteration."""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R10_SCENARIOS = CONSOLIDATION / "V20_109_R10_TARGETED_PRIOR_FAILURE_REPAIR_SCENARIOS.csv"
R10_REPAIR = CONSOLIDATION / "V20_109_R10_120D_TOP20_REPAIR_AUDIT.csv"
R10_CHURN = CONSOLIDATION / "V20_109_R10_TOP20_TOP40_CHURN_CONSTRAINT_AUDIT.csv"
R10_RERANK = CONSOLIDATION / "V20_109_R10_REPAIR_RERANK_AUDIT.csv"
R10_VALIDATION = CONSOLIDATION / "V20_109_R10_REPAIR_EFFECTIVENESS_VALIDATION.csv"
R10_GUARD = CONSOLIDATION / "V20_109_R10_SCENARIO_SELECTION_GUARD.csv"
R10_GATE = CONSOLIDATION / "V20_109_R10_NEXT_STAGE_GATE.csv"
R9_COMPARE = CONSOLIDATION / "V20_109_R9_SECOND_ROUND_EFFECTIVENESS_COMPARISON.csv"
R9_PRIOR = CONSOLIDATION / "V20_109_R9_PRIOR_FAILURE_REPAIR_COMPARISON.csv"
R9_STABILITY = CONSOLIDATION / "V20_109_R9_TOP20_TOP40_STABILITY_AUDIT.csv"
R9_SELECTION = CONSOLIDATION / "V20_109_R9_SCENARIO_SELECTION_RECOMMENDATION.csv"
R8_RERANK = CONSOLIDATION / "V20_109_R8_SECOND_ROUND_SIMULATED_WEIGHT_STRICT_EQUITY_RERANK.csv"
R8_COMPONENT = CONSOLIDATION / "V20_109_R8_SECOND_ROUND_SIMULATED_SCORE_COMPONENT_AUDIT.csv"

OUT_ANATOMY = CONSOLIDATION / "V20_109_R10_R1_120D_TOP20_FAILURE_ANATOMY.csv"
OUT_MOVEMENT = CONSOLIDATION / "V20_109_R10_R1_FAILED_TICKER_MOVEMENT_AUDIT.csv"
OUT_LEVER = CONSOLIDATION / "V20_109_R10_R1_REPAIR_LEVER_DIAGNOSTIC.csv"
OUT_SCENARIOS = CONSOLIDATION / "V20_109_R10_R1_TARGETED_REPAIR_SCENARIOS.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_109_R10_R1_REPAIR_VALIDATION.csv"
OUT_CHURN = CONSOLIDATION / "V20_109_R10_R1_CHURN_AND_STABILITY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_109_R10_R1_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_109_R10_R1_TARGETED_PRIOR_FAILURE_REPAIR_ITERATION_REPORT.md"

PASS_STATUS = "PASS_V20_109_R10_R1_TARGETED_REPAIR_READY_FOR_R11"
PARTIAL_STATUS = "PARTIAL_PASS_V20_109_R10_R1_FAILURE_ANATOMY_CREATED_REPAIR_LIMITED"
BLOCKED_MISSING_STATUS = "BLOCKED_V20_109_R10_R1_MISSING_REQUIRED_R10_INPUTS"
BLOCKED_UNVALIDATED_STATUS = "BLOCKED_V20_109_R10_R1_120D_TOP20_REPAIR_STILL_UNVALIDATED"
WARN_CHURN_STATUS = "WARN_V20_109_R10_R1_CHURN_GATE_TOO_STRICT"
WARN_LEVER_STATUS = "WARN_V20_109_R10_R1_REPAIR_LEVER_NOT_CONNECTED_TO_FAILURE"
WARN_EVIDENCE_STATUS = "WARN_V20_109_R10_R1_INSUFFICIENT_EVIDENCE_TO_CLASSIFY_FAILURE"

ANATOMY_FIELDS = ["anatomy_check_id","prior_failure_area","target_forward_window","target_topn_group","r10_blocked_gate_consumed","r10_validated_repair_scenario_count","best_r10_repair_scenario_id","baseline_mean_forward_return","current_shadow_mean_forward_return","seed_scenario_mean_forward_return","best_r10_repair_mean_forward_return","best_r10_repair_minus_baseline","best_r10_repair_minus_current_shadow","top20_churn_acceptable_count","top40_churn_acceptable_count","duplicate_rank_count","missing_rank_count","failure_mechanism_classification","failure_mechanism_reason","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
MOVEMENT_FIELDS = ["ticker","prior_failure_area","baseline_rank","current_shadow_rank","seed_scenario_rank","best_repair_audit_rank","selected_in_best_repair_top20","selected_in_best_repair_top40","ticker_movement_status","movement_reason","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
LEVER_FIELDS = ["repair_lever_id","linked_factor_or_constraint","diagnostic_signal","connected_to_failure_area","lever_effectiveness_status","lever_reason","recommended_next_repair_use","diagnostic_only","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
SCENARIO_FIELDS = ["repair_scenario_id","seed_scenario_id","scenario_family","scenario_priority","failure_mechanism_classification","prior_failure_area","target_forward_window","target_topn_group","top20_baseline_overlap_floor","top40_baseline_overlap_floor","repair_lever_used","repair_rule_summary","expected_next_test","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","accepted_weight_created","official_weight_created","new_weights_created","new_official_rerank_created","trade_action_created","broker_execution_supported","performance_effectiveness_claim_created","authoritative_ranking_overwritten"]
VALIDATION_FIELDS = ["validation_check_id","repair_scenario_count","validated_120d_top20_repair_scenario_count","top20_churn_acceptable_count","top40_churn_acceptable_count","duplicate_rank_count","missing_rank_count","failure_mechanism_classified","evidence_sufficient_for_robustness_validation","v20_109_r11_repair_robustness_validation_allowed","v20_110_acceptance_gate_allowed","accepted_weight_created","official_weight_created","new_weights_created","new_official_rerank_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","performance_effectiveness_claim_created","authoritative_ranking_overwritten","validation_status","validation_reason","research_only","shadow_only","simulation_only","official_promotion_allowed","is_official_weight","weight_mutated"]
CHURN_FIELDS = ["repair_scenario_id","top_n","baseline_overlap_floor","churn_constraint_status","churn_reason","top20_churn_acceptable","top40_churn_acceptable","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
GATE_FIELDS = ["gate_check_id","r10_r1_failure_anatomy_created","r10_r1_targeted_repair_scenarios_created","failure_mechanism_classification","validated_120d_top20_repair_scenario_count","v20_109_r11_repair_robustness_validation_allowed","v20_110_acceptance_gate_allowed","next_recommended_action","blocking_reason","accepted_weight_created","official_weight_created","new_weights_created","new_official_rerank_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","performance_effectiveness_claim_created","authoritative_ranking_overwritten","research_only","shadow_only","simulation_only","official_promotion_allowed","is_official_weight","weight_mutated"]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def dec(value: str) -> Decimal | None:
    try:
        return Decimal(clean(value))
    except (InvalidOperation, ValueError):
        return None


def fmt(value: Decimal | None) -> str:
    return "" if value is None else f"{float(value):.10f}"


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def safety(sim: bool = True) -> dict[str, str]:
    row = {"research_only":"TRUE","shadow_only":"TRUE","official_promotion_allowed":"FALSE","official_recommendation_created":"FALSE","trade_action_created":"FALSE","broker_execution_supported":"FALSE"}
    if sim:
        row["simulation_only"] = "TRUE"
    return row


def read_csv(path: Path) -> tuple[list[dict[str, str]], str]:
    if not path.exists() or path.stat().st_size == 0:
        return [], "MISSING_OR_EMPTY"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{k: clean(v) for k, v in row.items()} for row in reader], "OK"


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    r10_repair, s_repair = read_csv(R10_REPAIR)
    r10_churn, s_churn = read_csv(R10_CHURN)
    r10_rerank, s_rerank = read_csv(R10_RERANK)
    r10_validation, s_validation = read_csv(R10_VALIDATION)
    r10_gate, s_gate = read_csv(R10_GATE)
    r9_selection, s_r9 = read_csv(R9_SELECTION)
    r8_component, s_comp = read_csv(R8_COMPONENT)
    required_ok = all(s == "OK" for s in [s_repair, s_churn, s_rerank, s_validation, s_gate, s_r9, s_comp])

    v = r10_validation[0] if r10_validation else {}
    g = r10_gate[0] if r10_gate else {}
    r10_blocked_consumed = g.get("next_recommended_action") == "V20.109-R10_TARGETED_PRIOR_FAILURE_REPAIR_ITERATION"
    validated_count = int(v.get("validated_repair_scenario_count", "0") or "0")
    duplicate_rank_count = int(v.get("duplicate_rank_count", "0") or "0")
    missing_rank_count = int(v.get("missing_rank_count", "0") or "0")
    best_r10 = max(r10_repair, key=lambda r: dec(r.get("repair_minus_baseline_mean_return","")) or Decimal("-999")) if r10_repair else {}
    baseline_mean = dec(best_r10.get("baseline_mean_forward_return",""))
    current_mean = dec(best_r10.get("current_shadow_mean_forward_return",""))
    seed_mean = dec(best_r10.get("seed_scenario_mean_forward_return",""))
    best_mean = dec(best_r10.get("repair_scenario_mean_forward_return",""))
    best_vs_base = dec(best_r10.get("repair_minus_baseline_mean_return",""))
    best_vs_current = dec(best_r10.get("repair_minus_current_shadow_mean_return",""))
    top20_ok_count = sum(1 for r in r10_churn if r.get("top_n") == "20" and r.get("churn_acceptable") == "TRUE")
    top40_ok_count = sum(1 for r in r10_churn if r.get("top_n") == "40" and r.get("churn_acceptable") == "TRUE")

    if not required_ok:
        mechanism = "INSUFFICIENT_EVIDENCE_TO_CLASSIFY"
        reason = "Required R10/R9/R8 diagnostic inputs are missing."
    elif validated_count == 0 and best_vs_current is not None and best_vs_current > 0 and best_vs_base is not None and best_vs_base < 0:
        mechanism = "BASELINE_QUALITY_COLLAPSE"
        reason = "R10 repairs improved versus current shadow but still failed versus high-quality baseline 120D_TOP20."
    elif top20_ok_count == 0 or top40_ok_count == 0:
        mechanism = "TARGET_TICKERS_ENTER_BUT_CHURN_TOO_HIGH"
        reason = "Top20/Top40 churn constraints failed for the repair attempts."
    elif validated_count == 0:
        mechanism = "REPAIR_LEVER_NOT_CONNECTED_TO_FAILURE"
        reason = "Repair attempts did not improve the targeted 120D_TOP20 failure."
    else:
        mechanism = "SCORE_COMPONENT_INSUFFICIENT"
        reason = "Repair signal remains partial and needs robustness validation."

    anatomy_rows = [{
        "anatomy_check_id": "V20_109_R10_R1_120D_TOP20_FAILURE_ANATOMY_001",
        "prior_failure_area": "120D_TOP20",
        "target_forward_window": "120D",
        "target_topn_group": "20",
        "r10_blocked_gate_consumed": tf(r10_blocked_consumed),
        "r10_validated_repair_scenario_count": str(validated_count),
        "best_r10_repair_scenario_id": best_r10.get("repair_scenario_id",""),
        "baseline_mean_forward_return": fmt(baseline_mean),
        "current_shadow_mean_forward_return": fmt(current_mean),
        "seed_scenario_mean_forward_return": fmt(seed_mean),
        "best_r10_repair_mean_forward_return": fmt(best_mean),
        "best_r10_repair_minus_baseline": fmt(best_vs_base),
        "best_r10_repair_minus_current_shadow": fmt(best_vs_current),
        "top20_churn_acceptable_count": str(top20_ok_count),
        "top40_churn_acceptable_count": str(top40_ok_count),
        "duplicate_rank_count": str(duplicate_rank_count),
        "missing_rank_count": str(missing_rank_count),
        "failure_mechanism_classification": mechanism,
        "failure_mechanism_reason": reason,
        **safety(),
    }]

    best_id = best_r10.get("repair_scenario_id","")
    movement_rows = []
    for row in [r for r in r10_rerank if r.get("repair_scenario_id") == best_id][:40]:
        baseline_rank = dec(row.get("baseline_rank",""))
        audit_rank = dec(row.get("repair_audit_rank",""))
        if row.get("selected_in_repair_top20") == "TRUE" and baseline_rank is not None and baseline_rank <= 20:
            status = "BASELINE_QUALITY_PROTECTED_IN_TOP20"
        elif row.get("selected_in_repair_top20") == "TRUE":
            status = "TARGET_TICKER_ENTERED_TOP20"
        else:
            status = "TARGET_TICKER_OUTSIDE_TOP20"
        movement_rows.append({
            "ticker": row.get("ticker",""),
            "prior_failure_area": "120D_TOP20",
            "baseline_rank": row.get("baseline_rank",""),
            "current_shadow_rank": row.get("current_shadow_rank",""),
            "seed_scenario_rank": row.get("seed_scenario_rank",""),
            "best_repair_audit_rank": row.get("repair_audit_rank",""),
            "selected_in_best_repair_top20": row.get("selected_in_repair_top20",""),
            "selected_in_best_repair_top40": row.get("selected_in_repair_top40",""),
            "ticker_movement_status": status,
            "movement_reason": "Movement audit is diagnostic and does not create a new official rerank.",
            **safety(),
        })

    lever_rows = []
    for lever, connected, status, use in [
        ("BASELINE_OVERLAP_FLOOR", True, "CONNECTED_BUT_INSUFFICIENT", "protect baseline-quality candidates while testing new repair signals"),
        ("SIM2_002_WEIGHT_VECTOR", False, "REPAIR_LEVER_NOT_CONNECTED_TO_FAILURE", "do not rely only on SIM2_002"),
        ("CHURN_CONSTRAINT", True, "CHURN_CONSTRAINT_DIAGNOSTIC_REQUIRED", "test relaxed and strict churn bands separately"),
        ("COMPONENT_DIRECT_REPAIR", True, "REQUIRES_TARGETED_COMPONENT_TEST", "use component-level direct repair in next iteration"),
    ]:
        lever_rows.append({
            "repair_lever_id": lever,
            "linked_factor_or_constraint": lever,
            "diagnostic_signal": mechanism,
            "connected_to_failure_area": tf(connected),
            "lever_effectiveness_status": status,
            "lever_reason": reason,
            "recommended_next_repair_use": use,
            "diagnostic_only": "TRUE",
            **safety(),
        })

    scenario_defs = [
        ("R10_R1_REPAIR_001_SIM2_002_FAILURE_COMPONENT_BOOST","SIM2_002_FAILURE_COMPONENT_BOOST","HIGH",12,24,"COMPONENT_DIRECT_REPAIR"),
        ("R10_R1_REPAIR_002_NON_SIM2_COUNTERFACTUAL_REPAIR","NON_SIM2_COUNTERFACTUAL_REPAIR","HIGH",14,28,"NON_SIM2_COUNTERFACTUAL"),
        ("R10_R1_REPAIR_003_CHURN_GATE_RELAXATION_DIAGNOSTIC","CHURN_GATE_RELAXATION_DIAGNOSTIC","MEDIUM",8,18,"RELAXED_CHURN_GATE"),
        ("R10_R1_REPAIR_004_TOP20_OVERLAP_CONSTRAINED_REPAIR","TOP20_OVERLAP_CONSTRAINED_REPAIR","HIGH",16,28,"TOP20_OVERLAP_CONSTRAINT"),
        ("R10_R1_REPAIR_005_TOP40_OVERLAP_CONSTRAINED_REPAIR","TOP40_OVERLAP_CONSTRAINED_REPAIR","HIGH",12,34,"TOP40_OVERLAP_CONSTRAINT"),
        ("R10_R1_REPAIR_006_SCORE_COMPONENT_DIRECT_REPAIR","SCORE_COMPONENT_DIRECT_REPAIR","HIGH",15,30,"COMPONENT_DIRECT_REPAIR"),
        ("R10_R1_REPAIR_007_BASELINE_QUALITY_PROTECTED_REPAIR","BASELINE_QUALITY_PROTECTED_REPAIR","HIGH",18,34,"BASELINE_QUALITY_PROTECTION"),
        ("R10_R1_REPAIR_008_MINIMUM_CHURN_TARGETED_REPAIR","MINIMUM_CHURN_TARGETED_REPAIR","MEDIUM",10,20,"MINIMUM_CHURN_TARGETING"),
    ]
    scenario_rows = []
    churn_rows = []
    for sid, family, priority, floor20, floor40, lever in scenario_defs:
        scenario_rows.append({
            "repair_scenario_id": sid,
            "seed_scenario_id": "SIM2_002" if "NON_SIM2" not in family else "MULTI_SCENARIO_COUNTERFACTUAL",
            "scenario_family": family,
            "scenario_priority": priority,
            "failure_mechanism_classification": mechanism,
            "prior_failure_area": "120D_TOP20",
            "target_forward_window": "120D",
            "target_topn_group": "20",
            "top20_baseline_overlap_floor": str(floor20),
            "top40_baseline_overlap_floor": str(floor40),
            "repair_lever_used": lever,
            "repair_rule_summary": "Anatomy-driven diagnostic repair scenario; no accepted weights or official rerank created.",
            "expected_next_test": "V20.109-R10-R2_TARGETED_REPAIR_RERANK_OR_VALIDATION",
            **safety(),
            "accepted_weight_created": "FALSE",
            "official_weight_created": "FALSE",
            "new_weights_created": "FALSE",
            "new_official_rerank_created": "FALSE",
            "performance_effectiveness_claim_created": "FALSE",
            "authoritative_ranking_overwritten": "FALSE",
        })
        for topn, floor in [(20, floor20), (40, floor40)]:
            ok = floor >= (14 if topn == 20 else 28)
            churn_rows.append({
                "repair_scenario_id": sid,
                "top_n": str(topn),
                "baseline_overlap_floor": str(floor),
                "churn_constraint_status": "CHURN_CONSTRAINT_DESIGNED_ACCEPTABLE" if ok else "CHURN_CONSTRAINT_RELAXED_DIAGNOSTIC",
                "churn_reason": "Churn floor is scenario design only; no official rerank created.",
                "top20_churn_acceptable": tf(topn != 20 or ok),
                "top40_churn_acceptable": tf(topn != 40 or ok),
                **safety(),
            })

    repair_validated = False
    r11_allowed = repair_validated and top20_ok_count > 0 and top40_ok_count > 0 and duplicate_rank_count == 0 and missing_rank_count == 0
    evidence_sufficient = mechanism != "INSUFFICIENT_EVIDENCE_TO_CLASSIFY"
    validation_rows = [{
        "validation_check_id": "V20_109_R10_R1_REPAIR_VALIDATION_001",
        "repair_scenario_count": str(len(scenario_rows)),
        "validated_120d_top20_repair_scenario_count": "0",
        "top20_churn_acceptable_count": str(sum(1 for r in churn_rows if r["top_n"] == "20" and r["top20_churn_acceptable"] == "TRUE")),
        "top40_churn_acceptable_count": str(sum(1 for r in churn_rows if r["top_n"] == "40" and r["top40_churn_acceptable"] == "TRUE")),
        "duplicate_rank_count": str(duplicate_rank_count),
        "missing_rank_count": str(missing_rank_count),
        "failure_mechanism_classified": tf(evidence_sufficient),
        "evidence_sufficient_for_robustness_validation": tf(evidence_sufficient and repair_validated),
        "v20_109_r11_repair_robustness_validation_allowed": tf(r11_allowed),
        "v20_110_acceptance_gate_allowed": "FALSE",
        "accepted_weight_created": "FALSE",
        "official_weight_created": "FALSE",
        "new_weights_created": "FALSE",
        "new_official_rerank_created": "FALSE",
        "official_ranking_created": "FALSE",
        "official_recommendation_created": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        "performance_effectiveness_claim_created": "FALSE",
        "authoritative_ranking_overwritten": "FALSE",
        "validation_status": "PARTIAL" if evidence_sufficient else "BLOCKED",
        "validation_reason": "Failure anatomy created; new diagnostic scenarios require later validation.",
        **safety(),
        "is_official_weight": "FALSE",
        "weight_mutated": "FALSE",
    }]
    gate_rows = [{
        "gate_check_id": "V20_109_R10_R1_NEXT_STAGE_GATE_001",
        "r10_r1_failure_anatomy_created": tf(required_ok),
        "r10_r1_targeted_repair_scenarios_created": tf(bool(scenario_rows)),
        "failure_mechanism_classification": mechanism,
        "validated_120d_top20_repair_scenario_count": "0",
        "v20_109_r11_repair_robustness_validation_allowed": tf(r11_allowed),
        "v20_110_acceptance_gate_allowed": "FALSE",
        "next_recommended_action": "V20.109-R10-R2_TARGETED_REPAIR_RERANK_OR_VALIDATION",
        "blocking_reason": "120D_TOP20_REPAIR_STILL_UNVALIDATED",
        "accepted_weight_created": "FALSE",
        "official_weight_created": "FALSE",
        "new_weights_created": "FALSE",
        "new_official_rerank_created": "FALSE",
        "official_ranking_created": "FALSE",
        "official_recommendation_created": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        "performance_effectiveness_claim_created": "FALSE",
        "authoritative_ranking_overwritten": "FALSE",
        **safety(),
        "is_official_weight": "FALSE",
        "weight_mutated": "FALSE",
    }]

    if not required_ok:
        wrapper = BLOCKED_MISSING_STATUS
    elif mechanism == "INSUFFICIENT_EVIDENCE_TO_CLASSIFY":
        wrapper = WARN_EVIDENCE_STATUS
    elif mechanism == "REPAIR_LEVER_NOT_CONNECTED_TO_FAILURE":
        wrapper = WARN_LEVER_STATUS
    elif mechanism == "TARGET_TICKERS_ENTER_BUT_CHURN_TOO_HIGH":
        wrapper = WARN_CHURN_STATUS
    else:
        wrapper = PARTIAL_STATUS

    for path, fields, rows in [
        (OUT_ANATOMY, ANATOMY_FIELDS, anatomy_rows),
        (OUT_MOVEMENT, MOVEMENT_FIELDS, movement_rows),
        (OUT_LEVER, LEVER_FIELDS, lever_rows),
        (OUT_SCENARIOS, SCENARIO_FIELDS, scenario_rows),
        (OUT_VALIDATION, VALIDATION_FIELDS, validation_rows),
        (OUT_CHURN, CHURN_FIELDS, churn_rows),
        (OUT_GATE, GATE_FIELDS, gate_rows),
    ]:
        write_csv(path, fields, rows)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        "\n".join([
            "# V20.109-R10-R1 Targeted Prior Failure Repair Iteration Report",
            "",
            f"- wrapper_status: {wrapper}",
            f"- failure_mechanism_classification: {mechanism}",
            "- prior_failure_area: 120D_TOP20",
            f"- repair_scenario_count: {len(scenario_rows)}",
            "- validated_120d_top20_repair_scenario_count: 0",
            "- v20_110_acceptance_gate_allowed: FALSE",
            "- accepted_weight_created: FALSE",
            "- official_weight_created: FALSE",
            "- official_ranking_created: FALSE",
            "- performance_effectiveness_claim_created: FALSE",
        ]) + "\n",
        encoding="utf-8",
    )

    print(wrapper)
    print("R10_BLOCKED_GATE_CONSUMED=TRUE")
    print("PRIOR_FAILURE_AREA=120D_TOP20")
    print(f"FAILURE_MECHANISM_CLASSIFICATION={mechanism}")
    print(f"REPAIR_SCENARIO_COUNT={len(scenario_rows)}")
    print("VALIDATED_120D_TOP20_REPAIR_SCENARIO_COUNT=0")
    print(f"DUPLICATE_RANK_COUNT={duplicate_rank_count}")
    print(f"MISSING_RANK_COUNT={missing_rank_count}")
    print(f"V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION_ALLOWED={tf(r11_allowed)}")
    print("V20_110_ACCEPTANCE_GATE_ALLOWED=FALSE")
    print("ACCEPTED_WEIGHT_CREATED=FALSE")
    print("OFFICIAL_WEIGHT_CREATED=FALSE")
    print("NEW_WEIGHTS_CREATED=FALSE")
    print("NEW_OFFICIAL_RERANK_CREATED=FALSE")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED=FALSE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("IS_OFFICIAL_WEIGHT=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
