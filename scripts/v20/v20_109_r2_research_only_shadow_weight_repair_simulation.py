#!/usr/bin/env python
"""V20.109-R2 research-only shadow weight repair simulation.

Creates simulated shadow weight scenarios for later testing. It does not mutate
V20.107 weights, V20.98B-R5 base weights, or create a rerank/official artifact.
"""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R1_SUMMARY = CONSOLIDATION / "V20_109_R1_UNDERPERFORMANCE_DECOMPOSITION_SUMMARY.csv"
R1_FAILURE = CONSOLIDATION / "V20_109_R1_FORWARD_WINDOW_TOPN_FAILURE_MAP.csv"
R1_FACTOR = CONSOLIDATION / "V20_109_R1_FACTOR_FAMILY_FAILURE_ATTRIBUTION.csv"
R1_BUCKET = CONSOLIDATION / "V20_109_R1_RANK_DELTA_BUCKET_EFFECTIVENESS_AUDIT.csv"
R1_PLAN = CONSOLIDATION / "V20_109_R1_SHADOW_WEIGHT_REPAIR_PLAN.csv"
R1_GATE = CONSOLIDATION / "V20_109_R1_NEXT_STAGE_GATE.csv"
V109_SUMMARY = CONSOLIDATION / "V20_109_STRICT_EQUITY_SHADOW_VS_BASELINE_EFFECTIVENESS_SUMMARY.csv"
V109_MATRIX = CONSOLIDATION / "V20_109_FORWARD_WINDOW_TOPN_EFFECTIVENESS_MATRIX.csv"
R12_RERANK = CONSOLIDATION / "V20_108_R12_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK.csv"
R12_COMPONENT = CONSOLIDATION / "V20_108_R12_SHADOW_SCORE_COMPONENT_CONTRIBUTION_AUDIT.csv"
R107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R107_VALIDATION = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_WEIGHT_VALIDATION.csv"
R98B_WEIGHTS = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OUT_SCENARIOS = CONSOLIDATION / "V20_109_R2_SHADOW_WEIGHT_REPAIR_SIMULATION_SCENARIOS.csv"
OUT_CHANGE = CONSOLIDATION / "V20_109_R2_SIMULATED_WEIGHT_CHANGE_AUDIT.csv"
OUT_RATIONALE = CONSOLIDATION / "V20_109_R2_REPAIR_SCENARIO_RATIONALE_AUDIT.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_109_R2_WEIGHT_SIMULATION_VALIDATION.csv"
OUT_GATE = CONSOLIDATION / "V20_109_R2_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_109_R2_RESEARCH_ONLY_SHADOW_WEIGHT_REPAIR_SIMULATION_REPORT.md"

PASS_STATUS = "PASS_V20_109_R2_RESEARCH_ONLY_SHADOW_WEIGHT_REPAIR_SIMULATION"
PARTIAL_STATUS = "PARTIAL_PASS_V20_109_R2_WEIGHT_REPAIR_SIMULATION_WITH_LIMITED_EVIDENCE"
BLOCKED_STATUS = "BLOCKED_V20_109_R2_MISSING_REPAIR_PLAN_INPUTS"

FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
WEIGHT_FIELD = {
    "FUNDAMENTAL": "fundamental_weight",
    "TECHNICAL": "technical_weight",
    "STRATEGY": "strategy_weight",
    "RISK": "risk_weight",
    "MARKET_REGIME": "market_regime_weight",
    "DATA_TRUST": "data_trust_weight",
}
CAP = Decimal("0.3500000000")

SCENARIO_FIELDS = ["simulation_scenario_id","scenario_type","scenario_priority","fundamental_weight","technical_weight","strategy_weight","risk_weight","market_regime_weight","data_trust_weight","weight_sum","weight_sum_valid","max_family_weight","max_family_weight_cap","max_family_weight_cap_valid","risk_weight_positive","market_regime_weight_positive","data_trust_weight_positive","simulation_only","official_weight_created","active_weight_mutated","v20_107_weight_mutated","v20_98b_r5_weight_mutated","scenario_rationale","evidence_basis","affected_forward_windows","affected_topn_groups","expected_next_test","research_only","shadow_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
CHANGE_FIELDS = ["simulation_scenario_id","factor_family","current_v20_107_weight","simulated_weight","absolute_weight_change","relative_weight_change","change_direction","repair_plan_signal","evidence_basis","change_allowed_in_simulation","active_weight_mutated","official_weight_created","research_only","shadow_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
RATIONALE_FIELDS = ["simulation_scenario_id","repair_focus_area","linked_r1_failure_pattern","linked_forward_windows","linked_topn_groups","linked_factor_family","rationale_status","rationale_reason","scenario_supported_by_r1_evidence","diagnostic_only","research_only","shadow_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
VALIDATION_FIELDS = ["validation_check_id","scenario_count","valid_scenario_count","invalid_scenario_count","current_dynamic_weight_sum","current_dynamic_weight_sum_valid","all_simulated_weight_sums_valid","all_required_families_present","all_family_caps_valid","all_required_positive_weights_valid","new_weights_created","active_weight_mutated","v20_107_weight_mutated","v20_98b_r5_weight_mutated","official_weight_created","new_rerank_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","performance_effectiveness_claim_created","validation_status","validation_reason","research_only","shadow_only","official_promotion_allowed","is_official_weight"]
GATE_FIELDS = ["gate_check_id","weight_repair_simulation_scenarios_created","scenario_count","valid_scenario_count","new_weights_created","new_rerank_created","v20_110_acceptance_gate_allowed","v20_109_r3_simulated_rerank_allowed","recommended_next_stage","blocking_reason","performance_effectiveness_claim_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","research_only","shadow_only","official_promotion_allowed","is_official_weight","weight_mutated"]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def dec(value: str) -> Decimal:
    try:
        return Decimal(clean(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def fmt(value: Decimal) -> str:
    return f"{value:.10f}"


def safety() -> dict[str, str]:
    return {"research_only":"TRUE","shadow_only":"TRUE","official_promotion_allowed":"FALSE","official_recommendation_created":"FALSE","trade_action_created":"FALSE","broker_execution_supported":"FALSE"}


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str], str]:
    if not path.exists() or path.stat().st_size == 0:
        return [], [], "MISSING_OR_EMPTY"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{key: clean(value) for key, value in row.items()} for row in reader], list(reader.fieldnames or []), "OK"


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load_current_weights() -> dict[str, Decimal]:
    rows, _, _ = read_csv(R107_WEIGHTS)
    weights: dict[str, Decimal] = {}
    for row in rows:
        family = row.get("factor_family", "").upper()
        if family in FAMILIES:
            weights[family] = dec(row.get("normalized_shadow_dynamic_weight") or row.get("shadow_dynamic_weight", ""))
    return weights


def normalize(weights: dict[str, Decimal]) -> dict[str, Decimal]:
    total = sum(weights.values(), Decimal("0"))
    if total == 0:
        return weights
    out = {family: (weights[family] / total).quantize(Decimal("0.0000000001")) for family in FAMILIES}
    drift = Decimal("1.0000000000") - sum(out.values(), Decimal("0"))
    out["DATA_TRUST"] = (out["DATA_TRUST"] + drift).quantize(Decimal("0.0000000001"))
    return out


def scenario_definitions(current: dict[str, Decimal]) -> list[tuple[str, str, str, dict[str, Decimal], str, str, str, str, str, str]]:
    c = current
    return [
        ("SIM_001", "BASELINE_CURRENT_DYNAMIC_WEIGHTS_REFERENCE", "HIGH", dict(c), "Reference scenario using current V20.107 shadow dynamic weights.", "current dynamic weights baseline", "5D;10D;20D;60D;120D", "10;20;50;100", "reference", "ALL"),
        ("SIM_002", "LOWER_RISK_WEIGHT_SCENARIO", "HIGH", {**c, "RISK": Decimal("0.1000000000"), "FUNDAMENTAL": Decimal("0.2250000000"), "STRATEGY": Decimal("0.2250000000")}, "Lower risk weight and redistribute to fundamental/strategy for simulation.", "R1 risk_component repair plan", "5D;10D;20D;60D;120D", "10;20;50;100", "risk_component", "RISK"),
        ("SIM_003", "HIGHER_STRATEGY_WEIGHT_SCENARIO", "MEDIUM", {**c, "STRATEGY": Decimal("0.2500000000"), "TECHNICAL": Decimal("0.2200000000"), "RISK": Decimal("0.1300000000")}, "Increase strategy setup contribution while reducing technical/risk.", "R1 strategy_component repair plan", "5D;10D;20D;60D;120D", "10;20;50;100", "strategy_component", "STRATEGY"),
        ("SIM_004", "HIGHER_FUNDAMENTAL_WEIGHT_SCENARIO", "MEDIUM", {**c, "FUNDAMENTAL": Decimal("0.2500000000"), "TECHNICAL": Decimal("0.2200000000"), "RISK": Decimal("0.1300000000")}, "Increase fundamental contribution for strict equity names.", "R1 fundamental_component repair plan", "5D;10D;20D;60D;120D", "10;20;50;100", "fundamental_component", "FUNDAMENTAL"),
        ("SIM_005", "LOWER_MARKET_REGIME_WEIGHT_SCENARIO", "MEDIUM", {**c, "MARKET_REGIME": Decimal("0.0500000000"), "FUNDAMENTAL": Decimal("0.2250000000"), "STRATEGY": Decimal("0.2250000000")}, "Reduce current-context market regime weight.", "R1 market_regime_component repair plan", "5D;10D;20D;60D;120D", "10;20;50;100", "market_regime_component", "MARKET_REGIME"),
        ("SIM_006", "CONSERVATIVE_TOPN_STABILITY_SCENARIO", "HIGH", {"FUNDAMENTAL":Decimal("0.2200000000"),"TECHNICAL":Decimal("0.2200000000"),"STRATEGY":Decimal("0.2200000000"),"RISK":Decimal("0.1200000000"),"MARKET_REGIME":Decimal("0.0900000000"),"DATA_TRUST":Decimal("0.1300000000")}, "Conservative top-N stability simulation with higher data-trust ballast.", "R1 top-N concentration and rank-delta repair plans", "5D;10D;20D;60D;120D", "10;20", "top_n_concentration", "ALL"),
        ("SIM_007", "LONG_WINDOW_REPAIR_SCENARIO", "HIGH", {"FUNDAMENTAL":Decimal("0.2400000000"),"TECHNICAL":Decimal("0.2000000000"),"STRATEGY":Decimal("0.2300000000"),"RISK":Decimal("0.1200000000"),"MARKET_REGIME":Decimal("0.0800000000"),"DATA_TRUST":Decimal("0.1300000000")}, "Long-window repair scenario focused on 60D/120D failures.", "dominant underperformance area 120D_TOP20", "60D;120D", "10;20;50;100", "window_specificity", "ALL"),
        ("SIM_008", "BALANCED_REPAIR_SCENARIO", "MEDIUM", {"FUNDAMENTAL":Decimal("0.2200000000"),"TECHNICAL":Decimal("0.2200000000"),"STRATEGY":Decimal("0.2200000000"),"RISK":Decimal("0.1300000000"),"MARKET_REGIME":Decimal("0.1000000000"),"DATA_TRUST":Decimal("0.1100000000")}, "Balanced repair vector across fundamental, technical, strategy, risk, regime, and data trust.", "combined R1 failure attribution", "5D;10D;20D;60D;120D", "10;20;50;100", "balanced_repair", "ALL"),
    ]


def main() -> int:
    r1_plan, _, plan_status = read_csv(R1_PLAN)
    r1_summary, _, summary_status = read_csv(R1_SUMMARY)
    current = load_current_weights()
    current_sum = sum(current.values(), Decimal("0"))
    current_valid = len(current) == 6 and current_sum == Decimal("1.0000000000")
    valid_inputs = plan_status == "OK" and summary_status == "OK" and current_valid

    scenarios = []
    change_rows = []
    rationale_rows = []
    if valid_inputs:
        for sid, stype, priority, raw_weights, rationale, basis, windows, topns, focus, linked_family in scenario_definitions(current):
            weights = normalize(raw_weights)
            weight_sum = sum(weights.values(), Decimal("0"))
            max_weight = max(weights.values())
            valid = (
                weight_sum == Decimal("1.0000000000")
                and max_weight <= CAP
                and weights["RISK"] > 0
                and weights["MARKET_REGIME"] > 0
                and weights["DATA_TRUST"] > 0
            )
            row = {
                "simulation_scenario_id": sid,
                "scenario_type": stype,
                "scenario_priority": priority,
                **{WEIGHT_FIELD[f]: fmt(weights[f]) for f in FAMILIES},
                "weight_sum": fmt(weight_sum),
                "weight_sum_valid": tf(weight_sum == Decimal("1.0000000000")),
                "max_family_weight": fmt(max_weight),
                "max_family_weight_cap": fmt(CAP),
                "max_family_weight_cap_valid": tf(max_weight <= CAP),
                "risk_weight_positive": tf(weights["RISK"] > 0),
                "market_regime_weight_positive": tf(weights["MARKET_REGIME"] > 0),
                "data_trust_weight_positive": tf(weights["DATA_TRUST"] > 0),
                "simulation_only": "TRUE",
                "official_weight_created": "FALSE",
                "active_weight_mutated": "FALSE",
                "v20_107_weight_mutated": "FALSE",
                "v20_98b_r5_weight_mutated": "FALSE",
                "scenario_rationale": rationale,
                "evidence_basis": basis,
                "affected_forward_windows": windows,
                "affected_topn_groups": topns,
                "expected_next_test": "V20.109-R3_RESEARCH_ONLY_SIMULATED_WEIGHT_RERANK_TEST",
                **safety(),
            }
            scenarios.append(row)
            rationale_rows.append({
                "simulation_scenario_id": sid,
                "repair_focus_area": focus,
                "linked_r1_failure_pattern": basis,
                "linked_forward_windows": windows,
                "linked_topn_groups": topns,
                "linked_factor_family": linked_family,
                "rationale_status": "PASS" if valid else "BLOCKED",
                "rationale_reason": rationale,
                "scenario_supported_by_r1_evidence": "TRUE" if stype != "BASELINE_CURRENT_DYNAMIC_WEIGHTS_REFERENCE" else "REFERENCE",
                "diagnostic_only": "TRUE",
                **safety(),
            })
            for family in FAMILIES:
                cur = current[family]
                sim = weights[family]
                change = sim - cur
                rel_change = Decimal("0") if cur == 0 else change / cur
                direction = "INCREASE" if change > 0 else "DECREASE" if change < 0 else "UNCHANGED"
                signal = next((p.get("repair_action_type", "") for p in r1_plan if family.lower().split("_")[0] in p.get("repair_focus_area", "").lower()), "")
                change_rows.append({
                    "simulation_scenario_id": sid,
                    "factor_family": family,
                    "current_v20_107_weight": fmt(cur),
                    "simulated_weight": fmt(sim),
                    "absolute_weight_change": fmt(abs(change)),
                    "relative_weight_change": fmt(rel_change),
                    "change_direction": direction,
                    "repair_plan_signal": signal or "REFERENCE_OR_BALANCED_REPAIR",
                    "evidence_basis": basis,
                    "change_allowed_in_simulation": "TRUE",
                    "active_weight_mutated": "FALSE",
                    "official_weight_created": "FALSE",
                    **safety(),
                })

    valid_scenarios = [s for s in scenarios if s["weight_sum_valid"] == "TRUE" and s["max_family_weight_cap_valid"] == "TRUE" and s["risk_weight_positive"] == "TRUE" and s["market_regime_weight_positive"] == "TRUE" and s["data_trust_weight_positive"] == "TRUE"]
    all_sums = len(valid_scenarios) == len(scenarios) and bool(scenarios)
    validation_status = "PASS" if valid_inputs and all_sums else "BLOCKED"
    wrapper = PASS_STATUS if validation_status == "PASS" else BLOCKED_STATUS
    if validation_status == "PASS" and r1_summary and "PARTIAL" in (read_csv(V109_SUMMARY)[0][0].get("evidence_coverage_status", "") if read_csv(V109_SUMMARY)[2] == "OK" else ""):
        wrapper = PARTIAL_STATUS

    validation_rows = [{
        "validation_check_id": "V20_109_R2_WEIGHT_SIMULATION_VALIDATION_001",
        "scenario_count": str(len(scenarios)),
        "valid_scenario_count": str(len(valid_scenarios)),
        "invalid_scenario_count": str(len(scenarios) - len(valid_scenarios)),
        "current_dynamic_weight_sum": fmt(current_sum),
        "current_dynamic_weight_sum_valid": tf(current_valid),
        "all_simulated_weight_sums_valid": tf(all_sums),
        "all_required_families_present": tf(all(all(WEIGHT_FIELD[f] in s for f in FAMILIES) for s in scenarios)),
        "all_family_caps_valid": tf(all(s["max_family_weight_cap_valid"] == "TRUE" for s in scenarios)),
        "all_required_positive_weights_valid": tf(all(s["risk_weight_positive"] == "TRUE" and s["market_regime_weight_positive"] == "TRUE" and s["data_trust_weight_positive"] == "TRUE" for s in scenarios)),
        "new_weights_created": "FALSE",
        "active_weight_mutated": "FALSE",
        "v20_107_weight_mutated": "FALSE",
        "v20_98b_r5_weight_mutated": "FALSE",
        "official_weight_created": "FALSE",
        "new_rerank_created": "FALSE",
        "official_ranking_created": "FALSE",
        "official_recommendation_created": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        "performance_effectiveness_claim_created": "FALSE",
        "validation_status": validation_status,
        "validation_reason": "SIMULATION_SCENARIOS_CREATED_NO_WEIGHT_MUTATION" if validation_status == "PASS" else "MISSING_REPAIR_PLAN_OR_INVALID_WEIGHTS",
        **safety(),
        "is_official_weight": "FALSE",
    }]
    gate_rows = [{
        "gate_check_id": "V20_109_R2_NEXT_STAGE_GATE_001",
        "weight_repair_simulation_scenarios_created": tf(bool(scenarios)),
        "scenario_count": str(len(scenarios)),
        "valid_scenario_count": str(len(valid_scenarios)),
        "new_weights_created": "FALSE",
        "new_rerank_created": "FALSE",
        "v20_110_acceptance_gate_allowed": "FALSE",
        "v20_109_r3_simulated_rerank_allowed": tf(bool(valid_scenarios)),
        "recommended_next_stage": "V20.109-R3_RESEARCH_ONLY_SIMULATED_WEIGHT_RERANK_TEST" if valid_scenarios else "V20.109-R2_INPUT_REPAIR",
        "blocking_reason": "" if valid_scenarios else "NO_VALID_SIMULATION_SCENARIOS",
        "performance_effectiveness_claim_created": "FALSE",
        "official_ranking_created": "FALSE",
        "official_recommendation_created": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        **safety(),
        "is_official_weight": "FALSE",
        "weight_mutated": "FALSE",
    }]

    write_csv(OUT_SCENARIOS, SCENARIO_FIELDS, scenarios)
    write_csv(OUT_CHANGE, CHANGE_FIELDS, change_rows)
    write_csv(OUT_RATIONALE, RATIONALE_FIELDS, rationale_rows)
    write_csv(OUT_VALIDATION, VALIDATION_FIELDS, validation_rows)
    write_csv(OUT_GATE, GATE_FIELDS, gate_rows)

    report = [
        "# V20.109-R2 Research Only Shadow Weight Repair Simulation Report",
        "",
        "## Current Result",
        f"- wrapper_status: {wrapper}",
        f"- scenario_count: {len(scenarios)}",
        f"- valid_scenario_count: {len(valid_scenarios)}",
        f"- current_dynamic_weight_sum: {fmt(current_sum)}",
        "- new_weights_created: FALSE",
        "- new_rerank_created: FALSE",
        "- official_weight_created: FALSE",
        "- performance_effectiveness_claim_created: FALSE",
        "- v20_110_acceptance_gate_allowed: FALSE",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")

    print(wrapper)
    print(f"SCENARIO_COUNT={len(scenarios)}")
    print(f"VALID_SCENARIO_COUNT={len(valid_scenarios)}")
    print(f"CURRENT_DYNAMIC_WEIGHT_SUM={fmt(current_sum)}")
    print(f"CURRENT_DYNAMIC_WEIGHT_SUM_VALID={tf(current_valid)}")
    print(f"ALL_SIMULATED_WEIGHT_SUMS_VALID={tf(all_sums)}")
    print("NEW_WEIGHTS_CREATED=FALSE")
    print("NEW_RERANK_CREATED=FALSE")
    print("V20_110_ACCEPTANCE_GATE_ALLOWED=FALSE")
    print(f"V20_109_R3_SIMULATED_RERANK_ALLOWED={tf(bool(valid_scenarios))}")
    print("OFFICIAL_WEIGHT_CREATED=FALSE")
    print("ACTIVE_WEIGHT_MUTATED=FALSE")
    print("V20_107_WEIGHT_MUTATED=FALSE")
    print("V20_98B_R5_WEIGHT_MUTATED=FALSE")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED=FALSE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("IS_OFFICIAL_WEIGHT=FALSE")
    print(f"OUTPUT_SCENARIOS={OUT_SCENARIOS.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_CHANGE_AUDIT={OUT_CHANGE.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_RATIONALE={OUT_RATIONALE.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_VALIDATION={OUT_VALIDATION.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_GATE={OUT_GATE.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_REPORT={REPORT.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
