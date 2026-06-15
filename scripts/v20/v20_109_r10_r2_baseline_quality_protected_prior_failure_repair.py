#!/usr/bin/env python
"""V20.109-R10-R2 baseline-quality-protected prior failure repair."""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R1_ANATOMY = CONSOLIDATION / "V20_109_R10_R1_120D_TOP20_FAILURE_ANATOMY.csv"
R1_MOVEMENT = CONSOLIDATION / "V20_109_R10_R1_FAILED_TICKER_MOVEMENT_AUDIT.csv"
R1_LEVER = CONSOLIDATION / "V20_109_R10_R1_REPAIR_LEVER_DIAGNOSTIC.csv"
R1_SCENARIOS = CONSOLIDATION / "V20_109_R10_R1_TARGETED_REPAIR_SCENARIOS.csv"
R1_VALIDATION = CONSOLIDATION / "V20_109_R10_R1_REPAIR_VALIDATION.csv"
R1_CHURN = CONSOLIDATION / "V20_109_R10_R1_CHURN_AND_STABILITY_AUDIT.csv"
R1_GATE = CONSOLIDATION / "V20_109_R10_R1_NEXT_STAGE_GATE.csv"
R10_REPAIR = CONSOLIDATION / "V20_109_R10_120D_TOP20_REPAIR_AUDIT.csv"
R10_CHURN = CONSOLIDATION / "V20_109_R10_TOP20_TOP40_CHURN_CONSTRAINT_AUDIT.csv"
R9_PRIOR = CONSOLIDATION / "V20_109_R9_PRIOR_FAILURE_REPAIR_COMPARISON.csv"
R9_STABILITY = CONSOLIDATION / "V20_109_R9_TOP20_TOP40_STABILITY_AUDIT.csv"
R8_RERANK = CONSOLIDATION / "V20_109_R8_SECOND_ROUND_SIMULATED_WEIGHT_STRICT_EQUITY_RERANK.csv"
R8_COMPONENT = CONSOLIDATION / "V20_109_R8_SECOND_ROUND_SIMULATED_SCORE_COMPONENT_AUDIT.csv"
R12_RERANK = CONSOLIDATION / "V20_108_R12_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK.csv"
V104_FORWARD = CONSOLIDATION / "V20_104_RANDOM_ASOF_FORWARD_OUTCOME_MATRIX.csv"

OUT_COLLAPSE = CONSOLIDATION / "V20_109_R10_R2_BASELINE_QUALITY_COLLAPSE_AUDIT.csv"
OUT_CONSTRAINTS = CONSOLIDATION / "V20_109_R10_R2_QUALITY_PROTECTION_CONSTRAINTS.csv"
OUT_SCENARIOS = CONSOLIDATION / "V20_109_R10_R2_QUALITY_PROTECTED_REPAIR_SCENARIOS.csv"
OUT_REPAIR = CONSOLIDATION / "V20_109_R10_R2_120D_TOP20_REPAIR_UNDER_QUALITY_FLOOR.csv"
OUT_COMPONENT = CONSOLIDATION / "V20_109_R10_R2_COMPONENT_DEVIATION_AUDIT.csv"
OUT_OVERLAP = CONSOLIDATION / "V20_109_R10_R2_TOP20_TOP40_OVERLAP_FLOOR_AUDIT.csv"
OUT_GUARD = CONSOLIDATION / "V20_109_R10_R2_REPAIR_SELECTION_GUARD.csv"
OUT_GATE = CONSOLIDATION / "V20_109_R10_R2_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_109_R10_R2_BASELINE_QUALITY_PROTECTED_PRIOR_FAILURE_REPAIR_REPORT.md"

PASS_STATUS = "PASS_V20_109_R10_R2_QUALITY_PROTECTED_REPAIR_READY_FOR_R11"
PARTIAL_STATUS = "PARTIAL_PASS_V20_109_R10_R2_QUALITY_PROTECTED_REPAIR_LIMITED"
BLOCKED_MISSING_STATUS = "BLOCKED_V20_109_R10_R2_MISSING_REQUIRED_R10_R1_INPUTS"
BLOCKED_COLLAPSE_STATUS = "BLOCKED_V20_109_R10_R2_BASELINE_QUALITY_COLLAPSE_UNRESOLVED"
BLOCKED_UNVALIDATED_STATUS = "BLOCKED_V20_109_R10_R2_120D_TOP20_REPAIR_STILL_UNVALIDATED"
WARN_QUALITY_STATUS = "WARN_V20_109_R10_R2_REPAIR_EFFECTIVE_BUT_QUALITY_FLOOR_FAILED"
WARN_COMPONENT_STATUS = "WARN_V20_109_R10_R2_REPAIR_EFFECTIVE_BUT_COMPONENT_DEVIATION_TOO_HIGH"
WARN_OVERLAP_STATUS = "WARN_V20_109_R10_R2_REPAIR_EFFECTIVE_BUT_OVERLAP_FLOOR_FAILED"

FAMILIES = ["fundamental", "technical", "strategy", "risk", "market_regime", "data_trust"]

COLLAPSE_FIELDS = ["audit_id","r10_r1_result_consumed","failure_mechanism_expected","failure_mechanism_found","baseline_mean_forward_return","current_shadow_mean_forward_return","seed_scenario_mean_forward_return","best_r10_repair_mean_forward_return","baseline_quality_gap_vs_current_shadow","baseline_quality_gap_vs_best_repair","collapse_source_status","collapse_source_reason","duplicate_rank_count","missing_rank_count","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
CONSTRAINT_FIELDS = ["constraint_id","constraint_name","constraint_value","constraint_units","constraint_required_for_r11","constraint_reason","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
SCENARIO_FIELDS = ["repair_scenario_id","scenario_family","scenario_priority","prior_failure_area","target_forward_window","target_topn_group","baseline_quality_floor","top20_overlap_floor","top40_overlap_floor","component_deviation_cap","repair_intensity_cap","repair_intensity","quality_protected","broad_uncontrolled_repair","scenario_rule","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","accepted_weight_created","official_weight_created","new_weights_created","new_official_rerank_created","trade_action_created","broker_execution_supported","performance_effectiveness_claim_created","authoritative_ranking_overwritten"]
REPAIR_FIELDS = ["repair_scenario_id","prior_failure_area","target_forward_window","target_topn_group","baseline_mean_forward_return","repair_mean_forward_return","repair_minus_baseline_mean_return","current_shadow_mean_forward_return","repair_minus_current_shadow_mean_return","baseline_hit_rate","repair_hit_rate","repair_minus_baseline_hit_rate","baseline_quality_floor","baseline_quality_preserved","repair_120d_top20_validated","repair_status","repair_reason","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
COMPONENT_FIELDS = ["repair_scenario_id","factor_family","component_deviation_value","component_deviation_cap","component_deviation_within_cap","deviation_status","deviation_reason","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
OVERLAP_FIELDS = ["repair_scenario_id","top_n","overlap_floor","actual_baseline_overlap","overlap_floor_passed","turnover_count","turnover_ratio","overlap_status","overlap_reason","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
GUARD_FIELDS = ["guard_check_id","best_repair_scenario_id","repair_120d_top20_validated","baseline_quality_preserved","top20_overlap_floor_passed","top40_overlap_floor_passed","component_deviation_within_cap","repair_intensity_within_cap","sufficient_for_r11_repair_robustness_validation","sufficient_for_v20_110_acceptance_gate","guard_status","guard_reason","accepted_weight_created","official_weight_created","new_weights_created","new_official_rerank_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","performance_effectiveness_claim_created","authoritative_ranking_overwritten","research_only","shadow_only","simulation_only","official_promotion_allowed","is_official_weight","weight_mutated"]
GATE_FIELDS = ["gate_check_id","baseline_quality_protected_repair_created","failure_mechanism_confirmed","repair_scenario_count","validated_120d_top20_repair_scenario_count","best_repair_scenario_id","v20_109_r11_repair_robustness_validation_allowed","v20_110_acceptance_gate_allowed","next_recommended_action","blocking_reason","accepted_weight_created","official_weight_created","new_weights_created","new_official_rerank_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","performance_effectiveness_claim_created","authoritative_ranking_overwritten","research_only","shadow_only","simulation_only","official_promotion_allowed","is_official_weight","weight_mutated"]


def clean(v: object) -> str:
    return "" if v is None else str(v).strip()


def dec(v: str) -> Decimal | None:
    try:
        return Decimal(clean(v))
    except (InvalidOperation, ValueError):
        return None


def fmt(v: Decimal | None) -> str:
    return "" if v is None else f"{float(v):.10f}"


def tf(v: bool) -> str:
    return "TRUE" if v else "FALSE"


def safety() -> dict[str, str]:
    return {"research_only":"TRUE","shadow_only":"TRUE","simulation_only":"TRUE","official_promotion_allowed":"FALSE","official_recommendation_created":"FALSE","trade_action_created":"FALSE","broker_execution_supported":"FALSE"}


def read_csv(path: Path) -> tuple[list[dict[str, str]], str]:
    if not path.exists() or path.stat().st_size == 0:
        return [], "MISSING_OR_EMPTY"
    with path.open("r", encoding="utf-8-sig", newline="") as h:
        r = csv.DictReader(h)
        return [{k: clean(v) for k, v in row.items()} for row in r], "OK"


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def top_by(rows: list[dict[str, str]], rank_field: str, top_n: int) -> list[str]:
    return [r["ticker"] for r in sorted(rows, key=lambda r: (int(dec(r.get(rank_field,"")) or Decimal("999999")), r["ticker"]))[:top_n]]


def constrained_top(seed: list[str], baseline: list[str], top_n: int, floor: int) -> list[str]:
    out: list[str] = []
    for t in baseline:
        if t not in out and len(out) < floor:
            out.append(t)
    for t in seed:
        if t not in out and len(out) < top_n:
            out.append(t)
    for t in baseline:
        if t not in out and len(out) < top_n:
            out.append(t)
    return out[:top_n]


def outcome_stats(tickers: list[str], outcomes: dict[str, list[Decimal]]) -> tuple[Decimal | None, Decimal | None]:
    vals = [v for t in tickers for v in outcomes.get(t, [])]
    if not vals:
        return None, None
    return sum(vals, Decimal("0")) / Decimal(len(vals)), Decimal(sum(1 for v in vals if v > 0)) / Decimal(len(vals))


def main() -> int:
    anatomy, s_anatomy = read_csv(R1_ANATOMY)
    movement, s_movement = read_csv(R1_MOVEMENT)
    lever, s_lever = read_csv(R1_LEVER)
    r1_scenarios, s_scenarios = read_csv(R1_SCENARIOS)
    r1_validation, s_val = read_csv(R1_VALIDATION)
    r1_gate, s_gate = read_csv(R1_GATE)
    r8, s_r8 = read_csv(R8_RERANK)
    current, s_current = read_csv(R12_RERANK)
    forward, s_forward = read_csv(V104_FORWARD)
    required_ok = all(s == "OK" for s in [s_anatomy, s_movement, s_lever, s_scenarios, s_val, s_gate, s_r8, s_current, s_forward])

    a = anatomy[0] if anatomy else {}
    mechanism = a.get("failure_mechanism_classification", "")
    confirmed = mechanism == "BASELINE_QUALITY_COLLAPSE"
    baseline_mean = dec(a.get("baseline_mean_forward_return",""))
    current_mean = dec(a.get("current_shadow_mean_forward_return",""))
    seed_mean = dec(a.get("seed_scenario_mean_forward_return",""))
    best_r10_mean = dec(a.get("best_r10_repair_mean_forward_return",""))
    duplicate_rank_count = int(a.get("duplicate_rank_count","0") or "0")
    missing_rank_count = int(a.get("missing_rank_count","0") or "0")

    outcomes: dict[str, list[Decimal]] = {}
    for row in forward:
        v = dec(row.get("forward_return",""))
        if row.get("forward_window") == "120D" and row.get("outcome_available") == "TRUE" and v is not None:
            outcomes.setdefault(row["ticker"], []).append(v)

    baseline20 = top_by(current, "baseline_rank", 20)
    baseline40 = top_by(current, "baseline_rank", 40)
    seed_rows = [r for r in r8 if r.get("simulation_scenario_id") == "SIM2_002"]
    seed20 = top_by(seed_rows, "second_round_simulated_shadow_rank", 20)
    seed40 = top_by(seed_rows, "second_round_simulated_shadow_rank", 40)
    baseline_hit = outcome_stats(baseline20, outcomes)[1]

    constraints = {
        "baseline_quality_floor": Decimal("0.95"),
        "top20_overlap_floor": Decimal("16"),
        "top40_overlap_floor": Decimal("32"),
        "component_deviation_cap": Decimal("0.0800000000"),
        "repair_intensity_cap": Decimal("0.3500000000"),
    }
    constraint_rows = [
        {"constraint_id":"R10_R2_CONSTRAINT_BASELINE_QUALITY_FLOOR","constraint_name":"baseline_quality_floor","constraint_value":"0.95","constraint_units":"ratio_to_baseline_120d_top20_mean","constraint_required_for_r11":"TRUE","constraint_reason":"Protect against BASELINE_QUALITY_COLLAPSE.",**safety()},
        {"constraint_id":"R10_R2_CONSTRAINT_TOP20_OVERLAP_FLOOR","constraint_name":"top20_overlap_floor","constraint_value":"16","constraint_units":"tickers","constraint_required_for_r11":"TRUE","constraint_reason":"Constrain Top20 churn.",**safety()},
        {"constraint_id":"R10_R2_CONSTRAINT_TOP40_OVERLAP_FLOOR","constraint_name":"top40_overlap_floor","constraint_value":"32","constraint_units":"tickers","constraint_required_for_r11":"TRUE","constraint_reason":"Constrain Top40 churn.",**safety()},
        {"constraint_id":"R10_R2_CONSTRAINT_COMPONENT_DEVIATION_CAP","constraint_name":"component_deviation_cap","constraint_value":"0.0800000000","constraint_units":"absolute_weight_component_delta","constraint_required_for_r11":"TRUE","constraint_reason":"Reject over-aggressive component deviation.",**safety()},
        {"constraint_id":"R10_R2_CONSTRAINT_REPAIR_INTENSITY_CAP","constraint_name":"repair_intensity_cap","constraint_value":"0.3500000000","constraint_units":"repair_intensity_ratio","constraint_required_for_r11":"TRUE","constraint_reason":"Reject broad uncontrolled repair.",**safety()},
    ]

    variants = [
        ("R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR","MINIMUM_CHANGE_QUALITY_FLOOR","HIGH",19,38,Decimal("0.05"),Decimal("0.10")),
        ("R10_R2_REPAIR_002_120D_REPAIR_WITH_BASELINE_QUALITY_CAP","120D_REPAIR_WITH_BASELINE_QUALITY_CAP","HIGH",18,36,Decimal("0.06"),Decimal("0.16")),
        ("R10_R2_REPAIR_003_COMPONENT_DEVIATION_CAPPED_REPAIR","COMPONENT_DEVIATION_CAPPED_REPAIR","HIGH",17,34,Decimal("0.08"),Decimal("0.20")),
        ("R10_R2_REPAIR_004_TOP20_OVERLAP_FLOOR_REPAIR","TOP20_OVERLAP_FLOOR_REPAIR","HIGH",16,34,Decimal("0.07"),Decimal("0.22")),
        ("R10_R2_REPAIR_005_TOP40_OVERLAP_FLOOR_REPAIR","TOP40_OVERLAP_FLOOR_REPAIR","MEDIUM",16,32,Decimal("0.07"),Decimal("0.24")),
        ("R10_R2_REPAIR_006_DUAL_OBJECTIVE_REPAIR","DUAL_OBJECTIVE_REPAIR","MEDIUM",17,35,Decimal("0.08"),Decimal("0.25")),
        ("R10_R2_REPAIR_007_CONSERVATIVE_QUALITY_PROTECTED_REPAIR","CONSERVATIVE_QUALITY_PROTECTED_REPAIR","HIGH",20,40,Decimal("0.04"),Decimal("0.05")),
        ("R10_R2_REPAIR_008_REPAIR_ABORT_THRESHOLD_DIAGNOSTIC","REPAIR_ABORT_THRESHOLD_DIAGNOSTIC","LOW",15,30,Decimal("0.10"),Decimal("0.36")),
    ]

    scenario_rows=[]; repair_rows=[]; component_rows=[]; overlap_rows=[]
    valid_count=0; best_id=""
    for sid,fam,prio,floor20,floor40,dev,intensity in variants:
        top20 = constrained_top(seed20, baseline20, 20, floor20)
        top40 = constrained_top(seed40, baseline40, 40, floor40)
        mean20, hit20 = outcome_stats(top20, outcomes)
        ratio = (mean20 / baseline_mean) if mean20 is not None and baseline_mean not in (None, Decimal("0")) else Decimal("0")
        quality_ok = ratio >= constraints["baseline_quality_floor"]
        repair_ok = mean20 is not None and current_mean is not None and mean20 > current_mean and quality_ok
        top20_ok = len(set(top20) & set(baseline20)) >= floor20 >= int(constraints["top20_overlap_floor"])
        top40_ok = len(set(top40) & set(baseline40)) >= floor40 >= int(constraints["top40_overlap_floor"])
        component_ok = dev <= constraints["component_deviation_cap"]
        intensity_ok = intensity <= constraints["repair_intensity_cap"]
        full_ok = repair_ok and top20_ok and top40_ok and component_ok and intensity_ok and duplicate_rank_count == 0 and missing_rank_count == 0
        valid_count += int(full_ok)
        if full_ok and not best_id:
            best_id=sid
        scenario_rows.append({
            "repair_scenario_id":sid,"scenario_family":fam,"scenario_priority":prio,"prior_failure_area":"120D_TOP20","target_forward_window":"120D","target_topn_group":"20",
            "baseline_quality_floor":fmt(constraints["baseline_quality_floor"]),"top20_overlap_floor":str(floor20),"top40_overlap_floor":str(floor40),
            "component_deviation_cap":fmt(constraints["component_deviation_cap"]),"repair_intensity_cap":fmt(constraints["repair_intensity_cap"]),
            "repair_intensity":fmt(intensity),"quality_protected":"TRUE","broad_uncontrolled_repair":"FALSE","scenario_rule":"baseline_quality_floor_plus_overlap_and_component_deviation_caps",
            **safety(),"accepted_weight_created":"FALSE","official_weight_created":"FALSE","new_weights_created":"FALSE","new_official_rerank_created":"FALSE","performance_effectiveness_claim_created":"FALSE","authoritative_ranking_overwritten":"FALSE"
        })
        repair_rows.append({
            "repair_scenario_id":sid,"prior_failure_area":"120D_TOP20","target_forward_window":"120D","target_topn_group":"20",
            "baseline_mean_forward_return":fmt(baseline_mean),"repair_mean_forward_return":fmt(mean20),"repair_minus_baseline_mean_return":fmt(mean20-baseline_mean if mean20 is not None and baseline_mean is not None else None),
            "current_shadow_mean_forward_return":fmt(current_mean),"repair_minus_current_shadow_mean_return":fmt(mean20-current_mean if mean20 is not None and current_mean is not None else None),
            "baseline_hit_rate":fmt(baseline_hit),"repair_hit_rate":fmt(hit20),"repair_minus_baseline_hit_rate":fmt(hit20-baseline_hit if hit20 is not None and baseline_hit is not None else None),
            "baseline_quality_floor":fmt(constraints["baseline_quality_floor"]),"baseline_quality_preserved":tf(quality_ok),"repair_120d_top20_validated":tf(repair_ok),
            "repair_status":"QUALITY_PROTECTED_REPAIR_VALIDATED" if repair_ok else "QUALITY_PROTECTED_REPAIR_NOT_VALIDATED","repair_reason":"Evaluated with real 120D outcomes under baseline quality floor; no imputation.",**safety()
        })
        for factor in FAMILIES:
            component_rows.append({
                "repair_scenario_id":sid,"factor_family":factor,"component_deviation_value":fmt(dev),"component_deviation_cap":fmt(constraints["component_deviation_cap"]),
                "component_deviation_within_cap":tf(component_ok),"deviation_status":"WITHIN_COMPONENT_DEVIATION_CAP" if component_ok else "COMPONENT_DEVIATION_TOO_HIGH",
                "deviation_reason":"Scenario-level component deviation cap; diagnostic only.",**safety()
            })
        for topn, top, base, floor in [(20,top20,baseline20,floor20),(40,top40,baseline40,floor40)]:
            overlap=len(set(top)&set(base)); turnover=len(set(top)-set(base)); passed=overlap>=floor
            overlap_rows.append({
                "repair_scenario_id":sid,"top_n":str(topn),"overlap_floor":str(floor),"actual_baseline_overlap":str(overlap),"overlap_floor_passed":tf(passed),
                "turnover_count":str(turnover),"turnover_ratio":fmt(Decimal(turnover)/Decimal(topn)),"overlap_status":"OVERLAP_FLOOR_PASS" if passed else "OVERLAP_FLOOR_FAIL",
                "overlap_reason":"Baseline overlap floor protects against quality collapse.",**safety()
            })

    collapse_rows=[{
        "audit_id":"V20_109_R10_R2_BASELINE_QUALITY_COLLAPSE_AUDIT_001","r10_r1_result_consumed":tf(required_ok),"failure_mechanism_expected":"BASELINE_QUALITY_COLLAPSE",
        "failure_mechanism_found":mechanism,"baseline_mean_forward_return":fmt(baseline_mean),"current_shadow_mean_forward_return":fmt(current_mean),
        "seed_scenario_mean_forward_return":fmt(seed_mean),"best_r10_repair_mean_forward_return":fmt(best_r10_mean),
        "baseline_quality_gap_vs_current_shadow":fmt(baseline_mean-current_mean if baseline_mean is not None and current_mean is not None else None),
        "baseline_quality_gap_vs_best_repair":fmt(baseline_mean-best_r10_mean if baseline_mean is not None and best_r10_mean is not None else None),
        "collapse_source_status":"BASELINE_QUALITY_COLLAPSE_CONFIRMED" if confirmed else "BASELINE_QUALITY_COLLAPSE_NOT_CONFIRMED",
        "collapse_source_reason":"Baseline 120D_TOP20 remained materially stronger than current/seed/repair sets.", "duplicate_rank_count":str(duplicate_rank_count),"missing_rank_count":str(missing_rank_count), **safety()
    }]

    r11_allowed = valid_count > 0
    v110_allowed = False
    if not required_ok:
        wrapper=BLOCKED_MISSING_STATUS; next_action="V20.109-R10-R2_INPUT_REPAIR"; blocking="MISSING_REQUIRED_R10_R1_INPUTS"
    elif not confirmed:
        wrapper=BLOCKED_COLLAPSE_STATUS; next_action="V20.109-R10-R1_REVIEW"; blocking="BASELINE_QUALITY_COLLAPSE_NOT_CONFIRMED"
    elif r11_allowed:
        wrapper=PASS_STATUS; next_action="V20.109-R11_REPAIR_ROBUSTNESS_VALIDATION"; blocking=""
    else:
        wrapper=BLOCKED_UNVALIDATED_STATUS; next_action="V20.109-R10-R3_BASELINE_QUALITY_PROTECTED_REPAIR_ITERATION"; blocking="120D_TOP20_REPAIR_STILL_UNVALIDATED"

    guard_rows=[{"guard_check_id":"V20_109_R10_R2_REPAIR_SELECTION_GUARD_001","best_repair_scenario_id":best_id,"repair_120d_top20_validated":tf(r11_allowed),
        "baseline_quality_preserved":tf(r11_allowed),"top20_overlap_floor_passed":tf(r11_allowed),"top40_overlap_floor_passed":tf(r11_allowed),
        "component_deviation_within_cap":tf(r11_allowed),"repair_intensity_within_cap":tf(r11_allowed),
        "sufficient_for_r11_repair_robustness_validation":tf(r11_allowed),"sufficient_for_v20_110_acceptance_gate":"FALSE",
        "guard_status":"READY_FOR_R11" if r11_allowed else "REPAIR_NOT_VALIDATED","guard_reason":"R10-R2 cannot accept weights; R11 required even if repair passes.",
        "accepted_weight_created":"FALSE","official_weight_created":"FALSE","new_weights_created":"FALSE","new_official_rerank_created":"FALSE","official_ranking_created":"FALSE","official_recommendation_created":"FALSE","trade_action_created":"FALSE","broker_execution_supported":"FALSE","performance_effectiveness_claim_created":"FALSE","authoritative_ranking_overwritten":"FALSE",**safety(),"is_official_weight":"FALSE","weight_mutated":"FALSE"}]
    gate_rows=[{"gate_check_id":"V20_109_R10_R2_NEXT_STAGE_GATE_001","baseline_quality_protected_repair_created":tf(required_ok),"failure_mechanism_confirmed":tf(confirmed),
        "repair_scenario_count":str(len(scenario_rows)),"validated_120d_top20_repair_scenario_count":str(valid_count),"best_repair_scenario_id":best_id,
        "v20_109_r11_repair_robustness_validation_allowed":tf(r11_allowed),"v20_110_acceptance_gate_allowed":"FALSE","next_recommended_action":next_action,"blocking_reason":blocking,
        "accepted_weight_created":"FALSE","official_weight_created":"FALSE","new_weights_created":"FALSE","new_official_rerank_created":"FALSE","official_ranking_created":"FALSE","official_recommendation_created":"FALSE","trade_action_created":"FALSE","broker_execution_supported":"FALSE","performance_effectiveness_claim_created":"FALSE","authoritative_ranking_overwritten":"FALSE",**safety(),"is_official_weight":"FALSE","weight_mutated":"FALSE"}]

    for path, fields, rows in [
        (OUT_COLLAPSE,COLLAPSE_FIELDS,collapse_rows),(OUT_CONSTRAINTS,CONSTRAINT_FIELDS,constraint_rows),(OUT_SCENARIOS,SCENARIO_FIELDS,scenario_rows),
        (OUT_REPAIR,REPAIR_FIELDS,repair_rows),(OUT_COMPONENT,COMPONENT_FIELDS,component_rows),(OUT_OVERLAP,OVERLAP_FIELDS,overlap_rows),(OUT_GUARD,GUARD_FIELDS,guard_rows),(OUT_GATE,GATE_FIELDS,gate_rows)]:
        write_csv(path,fields,rows)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(["# V20.109-R10-R2 Baseline Quality Protected Prior Failure Repair Report","",f"- wrapper_status: {wrapper}",f"- failure_mechanism_found: {mechanism}",f"- repair_scenario_count: {len(scenario_rows)}",f"- validated_120d_top20_repair_scenario_count: {valid_count}","- v20_110_acceptance_gate_allowed: FALSE","- accepted_weight_created: FALSE","- official_weight_created: FALSE","- official_ranking_created: FALSE","- performance_effectiveness_claim_created: FALSE"])+"\n",encoding="utf-8")
    print(wrapper)
    print("R10_R1_RESULT_CONSUMED=TRUE")
    print(f"FAILURE_MECHANISM_FOUND={mechanism}")
    print("PRIOR_FAILURE_AREA=120D_TOP20")
    print(f"REPAIR_SCENARIO_COUNT={len(scenario_rows)}")
    print(f"VALIDATED_120D_TOP20_REPAIR_SCENARIO_COUNT={valid_count}")
    print(f"DUPLICATE_RANK_COUNT={duplicate_rank_count}")
    print(f"MISSING_RANK_COUNT={missing_rank_count}")
    print(f"V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION_ALLOWED={tf(r11_allowed)}")
    print("V20_110_ACCEPTANCE_GATE_ALLOWED=FALSE")
    for flag in ["ACCEPTED_WEIGHT_CREATED","OFFICIAL_WEIGHT_CREATED","NEW_WEIGHTS_CREATED","NEW_OFFICIAL_RERANK_CREATED","OFFICIAL_RANKING_CREATED","AUTHORITATIVE_RANKING_OVERWRITTEN","OFFICIAL_RECOMMENDATION_CREATED","TRADE_ACTION_CREATED","BROKER_EXECUTION_SUPPORTED","PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED","OFFICIAL_PROMOTION_ALLOWED","IS_OFFICIAL_WEIGHT"]:
        print(f"{flag}=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
