#!/usr/bin/env python
"""V20.109-R7 additional simulation or conservative weight repair.

Creates second-round simulation-only weight scenarios after SIM_004 failed the
R6 stress test. This stage does not create a rerank or mutate any weight source.
"""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R6_SUMMARY = CONSOLIDATION / "V20_109_R6_SIMULATED_SCENARIO_STRESS_TEST_SUMMARY.csv"
R6_WINDOW = CONSOLIDATION / "V20_109_R6_FORWARD_WINDOW_STRESS_AUDIT.csv"
R6_TOPN = CONSOLIDATION / "V20_109_R6_TOPN_CONCENTRATION_AND_TURNOVER_STRESS_AUDIT.csv"
R6_DOWNSIDE = CONSOLIDATION / "V20_109_R6_DOWNSIDE_AND_HIT_RATE_STRESS_AUDIT.csv"
R6_PRIOR = CONSOLIDATION / "V20_109_R6_PRIOR_FAILURE_AREA_REPAIR_AUDIT.csv"
R6_SELECTION = CONSOLIDATION / "V20_109_R6_STRESS_TEST_SELECTION_GATE.csv"
R6_GATE = CONSOLIDATION / "V20_109_R6_NEXT_STAGE_GATE.csv"
R5_SUMMARY = CONSOLIDATION / "V20_109_R5_CANDIDATE_SCENARIO_ROBUSTNESS_SUMMARY.csv"
R5_WINDOW = CONSOLIDATION / "V20_109_R5_WINDOW_TOPN_ROBUSTNESS_AUDIT.csv"
R5_BUCKET = CONSOLIDATION / "V20_109_R5_RANK_BUCKET_ROBUSTNESS_AUDIT.csv"
R5_ATTR = CONSOLIDATION / "V20_109_R5_FACTOR_FAMILY_ROBUSTNESS_ATTRIBUTION.csv"
R4_SUMMARY = CONSOLIDATION / "V20_109_R4_SIMULATED_SCENARIO_EFFECTIVENESS_SUMMARY.csv"
R4_MATRIX = CONSOLIDATION / "V20_109_R4_FORWARD_WINDOW_TOPN_SCENARIO_COMPARISON_MATRIX.csv"
R4_AUDIT = CONSOLIDATION / "V20_109_R4_SCENARIO_VS_BASELINE_AND_CURRENT_SHADOW_AUDIT.csv"
R4_ATTR = CONSOLIDATION / "V20_109_R4_SIMULATED_SCENARIO_FACTOR_ATTRIBUTION.csv"
R3_RERANK = CONSOLIDATION / "V20_109_R3_SIMULATED_WEIGHT_STRICT_EQUITY_RERANK.csv"
R2_SCENARIOS = CONSOLIDATION / "V20_109_R2_SHADOW_WEIGHT_REPAIR_SIMULATION_SCENARIOS.csv"
R1_FAILURE = CONSOLIDATION / "V20_109_R1_FORWARD_WINDOW_TOPN_FAILURE_MAP.csv"
R1_PLAN = CONSOLIDATION / "V20_109_R1_SHADOW_WEIGHT_REPAIR_PLAN.csv"
V109_MATRIX = CONSOLIDATION / "V20_109_FORWARD_WINDOW_TOPN_EFFECTIVENESS_MATRIX.csv"
R11_MATRIX = CONSOLIDATION / "V20_108_R11_STRICT_EQUITY_SHADOW_RERANK_INPUT_MATRIX.csv"
R107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R107_VALIDATION = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_WEIGHT_VALIDATION.csv"
R98B_WEIGHTS = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OUT_SCENARIOS = CONSOLIDATION / "V20_109_R7_ADDITIONAL_SIMULATION_SCENARIOS.csv"
OUT_RATIONALE = CONSOLIDATION / "V20_109_R7_CONSERVATIVE_REPAIR_RATIONALE_AUDIT.csv"
OUT_TARGET = CONSOLIDATION / "V20_109_R7_PRIOR_FAILURE_AREA_TARGETING_AUDIT.csv"
OUT_CHANGE = CONSOLIDATION / "V20_109_R7_SECOND_ROUND_WEIGHT_CHANGE_AUDIT.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_109_R7_SIMULATION_SCENARIO_VALIDATION.csv"
OUT_GATE = CONSOLIDATION / "V20_109_R7_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_109_R7_ADDITIONAL_SIMULATION_OR_CONSERVATIVE_WEIGHT_REPAIR_REPORT.md"

PASS_STATUS = "PASS_V20_109_R7_ADDITIONAL_SIMULATION_OR_CONSERVATIVE_WEIGHT_REPAIR"
PARTIAL_STATUS = "PARTIAL_PASS_V20_109_R7_ADDITIONAL_SIMULATION_WITH_LIMITED_EVIDENCE"
BLOCKED_STATUS = "BLOCKED_V20_109_R7_MISSING_R6_STRESS_TEST_INPUTS"

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

SCENARIO_FIELDS = ["simulation_scenario_id","parent_scenario_id","scenario_type","scenario_priority","fundamental_weight","technical_weight","strategy_weight","risk_weight","market_regime_weight","data_trust_weight","weight_sum","weight_sum_valid","max_family_weight","max_family_weight_cap","max_family_weight_cap_valid","risk_weight_positive","market_regime_weight_positive","data_trust_weight_positive","targets_prior_failure_area","targeted_forward_window","targeted_topn_group","simulation_only","official_weight_created","accepted_weight_created","active_weight_mutated","v20_107_weight_mutated","v20_98b_r5_weight_mutated","scenario_rationale","evidence_basis","expected_next_test","research_only","shadow_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
RATIONALE_FIELDS = ["simulation_scenario_id","scenario_type","repair_focus_area","linked_r6_stress_failure","linked_prior_failure_area","linked_forward_window","linked_topn_group","linked_factor_family","conservative_guardrail_used","rationale_status","rationale_reason","scenario_supported_by_r6_evidence","diagnostic_only","research_only","shadow_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
TARGET_FIELDS = ["simulation_scenario_id","scenario_type","prior_failure_area","prior_failure_forward_window","prior_failure_topn_group","prior_failure_repaired_by_parent_scenario","target_repair_mechanism","targeted_by_scenario","target_status","target_reason","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
CHANGE_FIELDS = ["simulation_scenario_id","factor_family","current_v20_107_weight","parent_sim004_weight","second_round_simulated_weight","change_vs_current_v20_107","change_vs_parent_sim004","change_direction_vs_current","change_direction_vs_parent","repair_signal","evidence_basis","active_weight_mutated","official_weight_created","accepted_weight_created","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
VALIDATION_FIELDS = ["validation_check_id","scenario_count","valid_scenario_count","invalid_scenario_count","current_dynamic_weight_sum","current_dynamic_weight_sum_valid","all_simulated_weight_sums_valid","all_required_families_present","all_family_caps_valid","all_required_positive_weights_valid","prior_failure_area_targeted_count","new_weights_created","active_weight_mutated","v20_107_weight_mutated","v20_98b_r5_weight_mutated","official_weight_created","accepted_weight_created","new_rerank_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","performance_effectiveness_claim_created","validation_status","validation_reason","research_only","shadow_only","simulation_only","official_promotion_allowed","is_official_weight"]
GATE_FIELDS = ["gate_check_id","additional_simulation_scenarios_created","scenario_count","valid_scenario_count","prior_failure_area_targeted_count","new_weights_created","new_rerank_created","v20_109_r8_second_round_simulated_rerank_allowed","v20_110_acceptance_gate_allowed","recommended_next_stage","blocking_reason","performance_effectiveness_claim_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","research_only","shadow_only","simulation_only","official_promotion_allowed","is_official_weight","weight_mutated"]


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


def safety(simulation: bool = True) -> dict[str, str]:
    row = {
        "research_only": "TRUE",
        "shadow_only": "TRUE",
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
    }
    if simulation:
        row["simulation_only"] = "TRUE"
    return row


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
    out: dict[str, Decimal] = {}
    for row in rows:
        family = row.get("factor_family", "").upper()
        if family in FAMILIES:
            out[family] = dec(row.get("normalized_shadow_dynamic_weight") or row.get("shadow_dynamic_weight", ""))
    return out


def load_parent_weights(parent_id: str) -> dict[str, Decimal]:
    rows, _, _ = read_csv(R2_SCENARIOS)
    parent = next((row for row in rows if row.get("simulation_scenario_id") == parent_id), {})
    return {family: dec(parent.get(WEIGHT_FIELD[family], "")) for family in FAMILIES}


def normalize(weights: dict[str, Decimal]) -> dict[str, Decimal]:
    total = sum(weights.values(), Decimal("0"))
    if total == 0:
        return weights
    out = {family: (weights[family] / total).quantize(Decimal("0.0000000001")) for family in FAMILIES}
    drift = Decimal("1.0000000000") - sum(out.values(), Decimal("0"))
    out["DATA_TRUST"] = (out["DATA_TRUST"] + drift).quantize(Decimal("0.0000000001"))
    return out


def direction(change: Decimal) -> str:
    return "INCREASE" if change > 0 else "DECREASE" if change < 0 else "UNCHANGED"


def scenario_defs() -> list[tuple[str, str, str, dict[str, Decimal], str, str, str, str]]:
    return [
        ("SIM2_001", "LONG_WINDOW_TOP20_REPAIR_SCENARIO", "HIGH", {"FUNDAMENTAL": Decimal("0.230"), "TECHNICAL": Decimal("0.200"), "STRATEGY": Decimal("0.250"), "RISK": Decimal("0.150"), "MARKET_REGIME": Decimal("0.070"), "DATA_TRUST": Decimal("0.100")}, "120D_TOP20 repair with strategy/risk guardrails rather than another pure fundamental increase.", "120D_TOP20 not repaired by SIM_004", "STRATEGY;RISK", "strategy_plus_risk_guardrail"),
        ("SIM2_002", "FUNDAMENTAL_PLUS_STRATEGY_BALANCE_SCENARIO", "HIGH", {"FUNDAMENTAL": Decimal("0.235"), "TECHNICAL": Decimal("0.205"), "STRATEGY": Decimal("0.235"), "RISK": Decimal("0.140"), "MARKET_REGIME": Decimal("0.075"), "DATA_TRUST": Decimal("0.110")}, "Balance fundamental with setup quality to reduce fragile long-window promotions.", "R6 fragile stress cells and R5 partial robustness", "FUNDAMENTAL;STRATEGY", "balanced_fundamental_strategy"),
        ("SIM2_003", "FUNDAMENTAL_WITH_RISK_GUARDRAIL_SCENARIO", "HIGH", {"FUNDAMENTAL": Decimal("0.240"), "TECHNICAL": Decimal("0.205"), "STRATEGY": Decimal("0.210"), "RISK": Decimal("0.165"), "MARKET_REGIME": Decimal("0.070"), "DATA_TRUST": Decimal("0.110")}, "Keep higher fundamental but raise risk guardrail for downside and hit-rate stress.", "R6 downside and hit-rate stress warnings", "FUNDAMENTAL;RISK", "risk_guardrail"),
        ("SIM2_004", "LOWER_MARKET_REGIME_HIGHER_STRATEGY_SCENARIO", "MEDIUM", {"FUNDAMENTAL": Decimal("0.220"), "TECHNICAL": Decimal("0.215"), "STRATEGY": Decimal("0.255"), "RISK": Decimal("0.145"), "MARKET_REGIME": Decimal("0.055"), "DATA_TRUST": Decimal("0.110")}, "Reduce market-regime sensitivity and shift weight to strategy setup quality.", "R6 fragile long-window context", "STRATEGY;MARKET_REGIME", "lower_regime_higher_strategy"),
        ("SIM2_005", "TOPN_STABILITY_CONSERVATIVE_SCENARIO", "HIGH", {"FUNDAMENTAL": Decimal("0.220"), "TECHNICAL": Decimal("0.220"), "STRATEGY": Decimal("0.225"), "RISK": Decimal("0.145"), "MARKET_REGIME": Decimal("0.080"), "DATA_TRUST": Decimal("0.110")}, "Conservative top-N stability scenario with lower factor concentration.", "R6 top-N turnover and concentration stress", "ALL", "topn_stability"),
        ("SIM2_006", "REDUCE_FRAGILE_PROMOTION_SCENARIO", "HIGH", {"FUNDAMENTAL": Decimal("0.215"), "TECHNICAL": Decimal("0.220"), "STRATEGY": Decimal("0.235"), "RISK": Decimal("0.160"), "MARKET_REGIME": Decimal("0.065"), "DATA_TRUST": Decimal("0.105")}, "Reduce fragile promotions by moderating fundamental and strengthening risk/strategy.", "R6 prior failure not repaired and fragile promotion concern", "FUNDAMENTAL;STRATEGY;RISK", "reduce_fragile_promotion"),
        ("SIM2_007", "LONG_WINDOW_RISK_ADJUSTED_SCENARIO", "MEDIUM", {"FUNDAMENTAL": Decimal("0.225"), "TECHNICAL": Decimal("0.205"), "STRATEGY": Decimal("0.225"), "RISK": Decimal("0.175"), "MARKET_REGIME": Decimal("0.065"), "DATA_TRUST": Decimal("0.105")}, "Long-window risk-adjusted scenario emphasizing risk controls.", "120D_TOP20 and downside stress", "RISK;STRATEGY", "long_window_risk_adjusted"),
        ("SIM2_008", "BALANCED_SECOND_ROUND_REPAIR_SCENARIO", "MEDIUM", {"FUNDAMENTAL": Decimal("0.220"), "TECHNICAL": Decimal("0.220"), "STRATEGY": Decimal("0.220"), "RISK": Decimal("0.150"), "MARKET_REGIME": Decimal("0.080"), "DATA_TRUST": Decimal("0.110")}, "Balanced second-round repair with no excessive single-factor overweight.", "combined R6 fragility evidence", "ALL", "balanced_second_round"),
    ]


def main() -> int:
    r6_summary, _, r6_summary_status = read_csv(R6_SUMMARY)
    r6_prior, _, r6_prior_status = read_csv(R6_PRIOR)
    r6_gate, _, r6_gate_status = read_csv(R6_GATE)
    r98b, _, r98b_status = read_csv(R98B_WEIGHTS)
    current = load_current_weights()
    parent_id = r6_summary[0].get("selected_simulation_scenario_id", "SIM_004") if r6_summary else "SIM_004"
    parent_type = r6_summary[0].get("selected_scenario_type", "HIGHER_FUNDAMENTAL_WEIGHT_SCENARIO") if r6_summary else "HIGHER_FUNDAMENTAL_WEIGHT_SCENARIO"
    parent = load_parent_weights(parent_id)
    prior_area = r6_prior[0].get("prior_failure_area", "120D_TOP20") if r6_prior else "120D_TOP20"
    prior_window = r6_prior[0].get("prior_failure_forward_window", "120D") if r6_prior else "120D"
    prior_topn = r6_prior[0].get("prior_failure_top_n", "20") if r6_prior else "20"
    parent_repaired = r6_prior[0].get("failure_area_repaired", "FALSE") if r6_prior else "FALSE"
    current_sum = sum(current.values(), Decimal("0"))
    current_valid = len(current) == 6 and current_sum == Decimal("1.0000000000")
    parent_valid = len(parent) == 6 and sum(parent.values(), Decimal("0")) == Decimal("1.0000000000")
    r6_allowed = bool(r6_gate) and r6_gate[0].get("v20_109_r7_additional_simulation_allowed") == "TRUE"
    required_ok = all(s == "OK" for s in [r6_summary_status, r6_prior_status, r6_gate_status, r98b_status]) and current_valid and parent_valid and r6_allowed

    scenario_rows: list[dict[str, str]] = []
    rationale_rows: list[dict[str, str]] = []
    target_rows: list[dict[str, str]] = []
    change_rows: list[dict[str, str]] = []

    if required_ok:
        for sid, stype, priority, raw_weights, rationale, evidence, linked_family, guardrail in scenario_defs():
            weights = normalize(raw_weights)
            total = sum(weights.values(), Decimal("0"))
            max_weight = max(weights.values())
            valid = total == Decimal("1.0000000000") and max_weight <= CAP and weights["RISK"] > 0 and weights["MARKET_REGIME"] > 0 and weights["DATA_TRUST"] > 0
            targets = prior_area == "120D_TOP20"
            scenario_rows.append({
                "simulation_scenario_id": sid,
                "parent_scenario_id": parent_id,
                "scenario_type": stype,
                "scenario_priority": priority,
                **{WEIGHT_FIELD[f]: fmt(weights[f]) for f in FAMILIES},
                "weight_sum": fmt(total),
                "weight_sum_valid": tf(total == Decimal("1.0000000000")),
                "max_family_weight": fmt(max_weight),
                "max_family_weight_cap": fmt(CAP),
                "max_family_weight_cap_valid": tf(max_weight <= CAP),
                "risk_weight_positive": tf(weights["RISK"] > 0),
                "market_regime_weight_positive": tf(weights["MARKET_REGIME"] > 0),
                "data_trust_weight_positive": tf(weights["DATA_TRUST"] > 0),
                "targets_prior_failure_area": tf(targets),
                "targeted_forward_window": prior_window,
                "targeted_topn_group": prior_topn,
                "simulation_only": "TRUE",
                "official_weight_created": "FALSE",
                "accepted_weight_created": "FALSE",
                "active_weight_mutated": "FALSE",
                "v20_107_weight_mutated": "FALSE",
                "v20_98b_r5_weight_mutated": "FALSE",
                "scenario_rationale": rationale,
                "evidence_basis": evidence,
                "expected_next_test": "V20.109-R8_SECOND_ROUND_SIMULATED_WEIGHT_STRICT_EQUITY_RERANK_RUNNER",
                **safety(False),
            })
            rationale_rows.append({
                "simulation_scenario_id": sid,
                "scenario_type": stype,
                "repair_focus_area": prior_area,
                "linked_r6_stress_failure": "PRIOR_FAILURE_AREA_NOT_REPAIRED;WARN_MIXED_OR_FRAGILE_STRESS_TEST",
                "linked_prior_failure_area": prior_area,
                "linked_forward_window": prior_window,
                "linked_topn_group": prior_topn,
                "linked_factor_family": linked_family,
                "conservative_guardrail_used": guardrail,
                "rationale_status": "PASS" if valid else "BLOCKED",
                "rationale_reason": rationale,
                "scenario_supported_by_r6_evidence": "TRUE",
                "diagnostic_only": "TRUE",
                **safety(False),
            })
            target_rows.append({
                "simulation_scenario_id": sid,
                "scenario_type": stype,
                "prior_failure_area": prior_area,
                "prior_failure_forward_window": prior_window,
                "prior_failure_topn_group": prior_topn,
                "prior_failure_repaired_by_parent_scenario": parent_repaired,
                "target_repair_mechanism": guardrail,
                "targeted_by_scenario": tf(targets),
                "target_status": "TARGETED_FOR_SECOND_ROUND_SIMULATION" if targets else "NOT_TARGETED",
                "target_reason": "Second-round scenario is designed for 120D_TOP20 repair; no rerank is created here.",
                **safety(True),
            })
            for family in FAMILIES:
                cur = current[family]
                par = parent[family]
                sim = weights[family]
                change_rows.append({
                    "simulation_scenario_id": sid,
                    "factor_family": family,
                    "current_v20_107_weight": fmt(cur),
                    "parent_sim004_weight": fmt(par),
                    "second_round_simulated_weight": fmt(sim),
                    "change_vs_current_v20_107": fmt(sim - cur),
                    "change_vs_parent_sim004": fmt(sim - par),
                    "change_direction_vs_current": direction(sim - cur),
                    "change_direction_vs_parent": direction(sim - par),
                    "repair_signal": guardrail,
                    "evidence_basis": evidence,
                    "active_weight_mutated": "FALSE",
                    "official_weight_created": "FALSE",
                    "accepted_weight_created": "FALSE",
                    **safety(True),
                })

    valid_scenarios = [
        row for row in scenario_rows
        if row["weight_sum_valid"] == "TRUE"
        and row["max_family_weight_cap_valid"] == "TRUE"
        and row["risk_weight_positive"] == "TRUE"
        and row["market_regime_weight_positive"] == "TRUE"
        and row["data_trust_weight_positive"] == "TRUE"
    ]
    scenario_count = len(scenario_rows)
    valid_count = len(valid_scenarios)
    target_count = sum(1 for row in valid_scenarios if row["targets_prior_failure_area"] == "TRUE")
    validation_pass = required_ok and scenario_count > 0 and valid_count == scenario_count and target_count > 0
    wrapper = PARTIAL_STATUS if validation_pass else BLOCKED_STATUS

    validation_rows = [{
        "validation_check_id": "V20_109_R7_SIMULATION_SCENARIO_VALIDATION_001",
        "scenario_count": str(scenario_count),
        "valid_scenario_count": str(valid_count),
        "invalid_scenario_count": str(scenario_count - valid_count),
        "current_dynamic_weight_sum": fmt(current_sum),
        "current_dynamic_weight_sum_valid": tf(current_valid),
        "all_simulated_weight_sums_valid": tf(valid_count == scenario_count and scenario_count > 0),
        "all_required_families_present": tf(all(all(WEIGHT_FIELD[f] in row for f in FAMILIES) for row in scenario_rows)),
        "all_family_caps_valid": tf(all(row["max_family_weight_cap_valid"] == "TRUE" for row in scenario_rows)),
        "all_required_positive_weights_valid": tf(all(row["risk_weight_positive"] == "TRUE" and row["market_regime_weight_positive"] == "TRUE" and row["data_trust_weight_positive"] == "TRUE" for row in scenario_rows)),
        "prior_failure_area_targeted_count": str(target_count),
        "new_weights_created": "FALSE",
        "active_weight_mutated": "FALSE",
        "v20_107_weight_mutated": "FALSE",
        "v20_98b_r5_weight_mutated": "FALSE",
        "official_weight_created": "FALSE",
        "accepted_weight_created": "FALSE",
        "new_rerank_created": "FALSE",
        "official_ranking_created": "FALSE",
        "official_recommendation_created": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        "performance_effectiveness_claim_created": "FALSE",
        "validation_status": "PASS" if validation_pass else "BLOCKED",
        "validation_reason": "SECOND_ROUND_SIMULATION_SCENARIOS_CREATED_NO_WEIGHT_MUTATION" if validation_pass else "MISSING_R6_STRESS_TEST_INPUTS",
        **safety(True),
        "is_official_weight": "FALSE",
    }]
    gate_rows = [{
        "gate_check_id": "V20_109_R7_NEXT_STAGE_GATE_001",
        "additional_simulation_scenarios_created": tf(validation_pass),
        "scenario_count": str(scenario_count),
        "valid_scenario_count": str(valid_count),
        "prior_failure_area_targeted_count": str(target_count),
        "new_weights_created": "FALSE",
        "new_rerank_created": "FALSE",
        "v20_109_r8_second_round_simulated_rerank_allowed": tf(validation_pass),
        "v20_110_acceptance_gate_allowed": "FALSE",
        "recommended_next_stage": "V20.109-R8_SECOND_ROUND_SIMULATED_WEIGHT_STRICT_EQUITY_RERANK_RUNNER" if validation_pass else "V20.109-R7_INPUT_REPAIR",
        "blocking_reason": "" if validation_pass else "MISSING_R6_STRESS_TEST_INPUTS",
        "performance_effectiveness_claim_created": "FALSE",
        "official_ranking_created": "FALSE",
        "official_recommendation_created": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        **safety(True),
        "is_official_weight": "FALSE",
        "weight_mutated": "FALSE",
    }]

    write_csv(OUT_SCENARIOS, SCENARIO_FIELDS, scenario_rows)
    write_csv(OUT_RATIONALE, RATIONALE_FIELDS, rationale_rows)
    write_csv(OUT_TARGET, TARGET_FIELDS, target_rows)
    write_csv(OUT_CHANGE, CHANGE_FIELDS, change_rows)
    write_csv(OUT_VALIDATION, VALIDATION_FIELDS, validation_rows)
    write_csv(OUT_GATE, GATE_FIELDS, gate_rows)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        "\n".join([
            "# V20.109-R7 Additional Simulation Or Conservative Weight Repair Report",
            "",
            "## Current Result",
            f"- wrapper_status: {wrapper}",
            f"- parent_scenario_id: {parent_id}",
            f"- parent_scenario_type: {parent_type}",
            f"- prior_failure_area: {prior_area}",
            f"- scenario_count: {scenario_count}",
            f"- valid_scenario_count: {valid_count}",
            f"- prior_failure_area_targeted_count: {target_count}",
            "- new_weights_created: FALSE",
            "- new_rerank_created: FALSE",
            "- official_weight_created: FALSE",
            "- official_ranking_created: FALSE",
            "- performance_effectiveness_claim_created: FALSE",
            "- v20_110_acceptance_gate_allowed: FALSE",
        ]) + "\n",
        encoding="utf-8",
    )

    print(wrapper)
    print(f"PARENT_SCENARIO_ID={parent_id}")
    print(f"PRIOR_FAILURE_AREA={prior_area}")
    print(f"TARGETED_FORWARD_WINDOW={prior_window}")
    print(f"TARGETED_TOPN_GROUP={prior_topn}")
    print(f"SCENARIO_COUNT={scenario_count}")
    print(f"VALID_SCENARIO_COUNT={valid_count}")
    print(f"PRIOR_FAILURE_AREA_TARGETED_COUNT={target_count}")
    print(f"CURRENT_DYNAMIC_WEIGHT_SUM={fmt(current_sum)}")
    print(f"CURRENT_DYNAMIC_WEIGHT_SUM_VALID={tf(current_valid)}")
    print("NEW_WEIGHTS_CREATED=FALSE")
    print("NEW_RERANK_CREATED=FALSE")
    print("ACCEPTED_WEIGHT_CREATED=FALSE")
    print("OFFICIAL_WEIGHT_CREATED=FALSE")
    print("ACTIVE_WEIGHT_MUTATED=FALSE")
    print("V20_107_WEIGHT_MUTATED=FALSE")
    print("V20_98B_R5_WEIGHT_MUTATED=FALSE")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED=FALSE")
    print("V20_110_ACCEPTANCE_GATE_ALLOWED=FALSE")
    print(f"V20_109_R8_SECOND_ROUND_SIMULATED_RERANK_ALLOWED={tf(validation_pass)}")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("IS_OFFICIAL_WEIGHT=FALSE")
    print(f"OUTPUT_SCENARIOS={OUT_SCENARIOS.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_RATIONALE={OUT_RATIONALE.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_TARGET={OUT_TARGET.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_CHANGE={OUT_CHANGE.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_VALIDATION={OUT_VALIDATION.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_GATE={OUT_GATE.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_REPORT={REPORT.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
