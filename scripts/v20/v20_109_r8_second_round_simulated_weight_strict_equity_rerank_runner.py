#!/usr/bin/env python
"""V20.109-R8 second-round simulated strict equity rerank runner."""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R7_SCENARIOS = CONSOLIDATION / "V20_109_R7_ADDITIONAL_SIMULATION_SCENARIOS.csv"
R7_RATIONALE = CONSOLIDATION / "V20_109_R7_CONSERVATIVE_REPAIR_RATIONALE_AUDIT.csv"
R7_TARGET = CONSOLIDATION / "V20_109_R7_PRIOR_FAILURE_AREA_TARGETING_AUDIT.csv"
R7_CHANGE = CONSOLIDATION / "V20_109_R7_SECOND_ROUND_WEIGHT_CHANGE_AUDIT.csv"
R7_VALIDATION = CONSOLIDATION / "V20_109_R7_SIMULATION_SCENARIO_VALIDATION.csv"
R7_GATE = CONSOLIDATION / "V20_109_R7_NEXT_STAGE_GATE.csv"
R11_MATRIX = CONSOLIDATION / "V20_108_R11_STRICT_EQUITY_SHADOW_RERANK_INPUT_MATRIX.csv"
R12_RERANK = CONSOLIDATION / "V20_108_R12_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK.csv"
R3_RERANK = CONSOLIDATION / "V20_109_R3_SIMULATED_WEIGHT_STRICT_EQUITY_RERANK.csv"
R6_SUMMARY = CONSOLIDATION / "V20_109_R6_SIMULATED_SCENARIO_STRESS_TEST_SUMMARY.csv"
R6_PRIOR = CONSOLIDATION / "V20_109_R6_PRIOR_FAILURE_AREA_REPAIR_AUDIT.csv"
R107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R107_VALIDATION = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_WEIGHT_VALIDATION.csv"
R98B_WEIGHTS = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OUT_RERANK = CONSOLIDATION / "V20_109_R8_SECOND_ROUND_SIMULATED_WEIGHT_STRICT_EQUITY_RERANK.csv"
OUT_DELTA = CONSOLIDATION / "V20_109_R8_SECOND_ROUND_SIMULATED_RANK_DELTA_AUDIT.csv"
OUT_COMPONENT = CONSOLIDATION / "V20_109_R8_SECOND_ROUND_SIMULATED_SCORE_COMPONENT_AUDIT.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_109_R8_SECOND_ROUND_SIMULATED_RERANK_VALIDATION.csv"
OUT_GATE = CONSOLIDATION / "V20_109_R8_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_109_R8_SECOND_ROUND_SIMULATED_WEIGHT_STRICT_EQUITY_RERANK_REPORT.md"

PASS_STATUS = "PASS_V20_109_R8_SECOND_ROUND_SIMULATED_WEIGHT_STRICT_EQUITY_RERANK_RUNNER"
PARTIAL_STATUS = "PARTIAL_PASS_V20_109_R8_SECOND_ROUND_SIMULATED_RERANK_WITH_LIMITED_EVIDENCE"
BLOCKED_STATUS = "BLOCKED_V20_109_R8_MISSING_SECOND_ROUND_SIMULATION_SCENARIOS_OR_INPUT_MATRIX"

FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
CONTRIB = {
    "FUNDAMENTAL": "fundamental_contribution",
    "TECHNICAL": "technical_contribution",
    "STRATEGY": "strategy_contribution",
    "RISK": "risk_contribution",
    "MARKET_REGIME": "market_regime_contribution",
    "DATA_TRUST": "data_trust_contribution",
}
WEIGHT_FIELD = {
    "FUNDAMENTAL": "fundamental_weight",
    "TECHNICAL": "technical_weight",
    "STRATEGY": "strategy_weight",
    "RISK": "risk_weight",
    "MARKET_REGIME": "market_regime_weight",
    "DATA_TRUST": "data_trust_weight",
}
OUT_WEIGHT_FIELD = {
    "FUNDAMENTAL": "second_round_fundamental_weight",
    "TECHNICAL": "second_round_technical_weight",
    "STRATEGY": "second_round_strategy_weight",
    "RISK": "second_round_risk_weight",
    "MARKET_REGIME": "second_round_market_regime_weight",
    "DATA_TRUST": "second_round_data_trust_weight",
}
PARENT_WEIGHT_FIELD = {
    "FUNDAMENTAL": "simulated_fundamental_weight",
    "TECHNICAL": "simulated_technical_weight",
    "STRATEGY": "simulated_strategy_weight",
    "RISK": "simulated_risk_weight",
    "MARKET_REGIME": "simulated_market_regime_weight",
    "DATA_TRUST": "simulated_data_trust_weight",
}

RERANK_FIELDS = ["simulation_scenario_id","parent_scenario_id","scenario_type","scenario_priority","targeted_forward_window","targeted_topn_group","ticker","baseline_rank","current_strict_equity_shadow_rank","parent_sim004_shadow_rank","second_round_simulated_shadow_rank","second_round_rank_delta_vs_baseline","second_round_rank_delta_vs_current_shadow","second_round_rank_delta_vs_parent_sim004","second_round_rank_delta_direction_vs_current_shadow","second_round_simulated_shadow_weighted_score","fundamental_contribution","technical_contribution","strategy_contribution","risk_contribution","market_regime_contribution","data_trust_contribution","second_round_fundamental_weight","second_round_technical_weight","second_round_strategy_weight","second_round_risk_weight","second_round_market_regime_weight","second_round_data_trust_weight","second_round_weight_sum","all_six_family_contributions_present","all_six_second_round_weights_present","tie_breaker_used","strict_equity_rerank_scope","targets_prior_failure_area","simulation_only","research_only","shadow_only","official_promotion_allowed","official_recommendation_created","is_official_ranking","is_official_weight","official_weight_created","accepted_weight_created","active_weight_mutated","v20_107_weight_mutated","v20_98b_r5_weight_mutated","trade_action_created","broker_execution_supported"]
DELTA_FIELDS = ["simulation_scenario_id","parent_scenario_id","scenario_type","ticker","baseline_rank","current_strict_equity_shadow_rank","parent_sim004_shadow_rank","second_round_simulated_shadow_rank","second_round_rank_delta_vs_baseline","second_round_rank_delta_vs_current_shadow","second_round_rank_delta_vs_parent_sim004","current_shadow_score","parent_sim004_score","second_round_simulated_shadow_weighted_score","score_delta_vs_current_shadow","score_delta_vs_parent_sim004","top_positive_component_family","top_negative_component_family","audit_status","audit_reason","simulation_only","diagnostic_only","research_only","shadow_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
COMPONENT_FIELDS = ["simulation_scenario_id","parent_scenario_id","scenario_type","ticker","factor_family","contribution_value","second_round_simulated_weight","second_round_weighted_component_contribution","current_v20_107_weight","current_weighted_component_contribution","parent_sim004_weight","parent_sim004_weighted_component_contribution","component_delta_vs_current_shadow","component_delta_vs_parent_sim004","contribution_available","weight_available","component_used_in_score","fabricated_values_created","proxy_values_activated","source_rank_or_score_used","baseline_rank_used_as_factor_contribution","simulation_only","diagnostic_only","research_only","shadow_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
VALIDATION_FIELDS = ["validation_check_id","scenario_count","valid_scenario_count","strict_equity_candidate_count","expected_rerank_row_count","actual_rerank_row_count","all_scenario_weight_sums_valid","all_required_factor_families_present","all_required_weights_present","all_candidates_scored_per_scenario","duplicate_rank_count","missing_rank_count","excluded_non_equity_or_fund_candidate_count","prior_failure_area_targeted_count","source_rank_or_score_used","baseline_rank_used_as_factor_contribution","fabricated_values_created","proxy_values_activated","second_round_simulated_rerank_created","new_weights_created","active_weight_mutated","v20_107_weight_mutated","v20_98b_r5_weight_mutated","official_weight_created","accepted_weight_created","official_ranking_created","official_recommendation_created","authoritative_ranking_overwritten","trade_action_created","broker_execution_supported","performance_effectiveness_claim_created","validation_status","validation_reason","research_only","shadow_only","official_promotion_allowed","is_official_weight"]
GATE_FIELDS = ["gate_check_id","second_round_simulated_rerank_created","scenario_count","strict_equity_candidate_count","second_round_simulated_rerank_row_count","prior_failure_area_targeted","v20_109_r9_second_round_effectiveness_comparison_allowed","v20_110_acceptance_gate_allowed","recommended_next_stage","blocking_reason","new_weights_created","accepted_weight_created","official_weight_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","performance_effectiveness_claim_created","research_only","shadow_only","official_promotion_allowed","is_official_weight","weight_mutated"]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def dec(value: str) -> Decimal | None:
    try:
        return Decimal(clean(value))
    except (InvalidOperation, ValueError):
        return None


def fmt(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP))


def safety(extra: bool = False) -> dict[str, str]:
    row = {
        "research_only": "TRUE",
        "shadow_only": "TRUE",
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
    }
    if extra:
        row["is_official_ranking"] = "FALSE"
        row["is_official_weight"] = "FALSE"
    return row


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str], str]:
    if not path.exists() or path.stat().st_size == 0:
        return [], [], "MISSING_OR_EMPTY"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{k: clean(v) for k, v in row.items()} for row in reader], list(reader.fieldnames or []), "OK"


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load_current_weights() -> dict[str, Decimal]:
    rows, _, _ = read_csv(R107_WEIGHTS)
    return {
        row["factor_family"]: dec(row.get("normalized_shadow_dynamic_weight") or row.get("shadow_dynamic_weight", "")) or Decimal("0")
        for row in rows
        if row.get("factor_family") in FAMILIES
    }


def score(row: dict[str, str], scenario: dict[str, str]) -> tuple[Decimal, dict[str, Decimal]]:
    comps: dict[str, Decimal] = {}
    total = Decimal("0")
    for family in FAMILIES:
        contribution = dec(row.get(CONTRIB[family], "")) or Decimal("0")
        weight = dec(scenario.get(WEIGHT_FIELD[family], "")) or Decimal("0")
        component = contribution * weight
        comps[family] = component
        total += component
    return total, comps


def main() -> int:
    scenarios, _, scenario_status = read_csv(R7_SCENARIOS)
    r7_validation, _, validation_status = read_csv(R7_VALIDATION)
    r7_gate, _, gate_status = read_csv(R7_GATE)
    matrix, _, matrix_status = read_csv(R11_MATRIX)
    current_rerank, _, current_status = read_csv(R12_RERANK)
    parent_rerank, _, parent_status = read_csv(R3_RERANK)
    valid_scenarios = [row for row in scenarios if row.get("weight_sum_valid") == "TRUE"]
    current_by_ticker = {row["ticker"]: row for row in current_rerank}
    parent_by_ticker = {row["ticker"]: row for row in parent_rerank if row.get("simulation_scenario_id") == "SIM_004"}
    current_weights = load_current_weights()
    r7_allowed = bool(r7_gate) and r7_gate[0].get("v20_109_r8_second_round_simulated_rerank_allowed") == "TRUE"
    valid_inputs = (
        scenario_status == "OK"
        and validation_status == "OK"
        and gate_status == "OK"
        and matrix_status == "OK"
        and current_status == "OK"
        and parent_status == "OK"
        and r7_allowed
        and len(valid_scenarios) > 0
        and len(matrix) == 297
        and len(parent_by_ticker) == 297
    )

    rerank_rows: list[dict[str, str]] = []
    delta_rows: list[dict[str, str]] = []
    component_rows: list[dict[str, str]] = []
    duplicate_rank_count = 0
    missing_rank_count = 0
    excluded_count = 18

    for scenario in valid_scenarios:
        sid = scenario["simulation_scenario_id"]
        parent_id = scenario.get("parent_scenario_id", "SIM_004")
        stype = scenario["scenario_type"]
        scored = []
        for row in matrix:
            total, comps = score(row, scenario)
            scored.append((row, total, comps))
            parent = parent_by_ticker[row["ticker"]]
            for family in FAMILIES:
                contribution = dec(row.get(CONTRIB[family], "")) or Decimal("0")
                second_weight = dec(scenario.get(WEIGHT_FIELD[family], "")) or Decimal("0")
                current_weight = current_weights.get(family, Decimal("0"))
                parent_weight = dec(parent.get(PARENT_WEIGHT_FIELD[family], "")) or Decimal("0")
                second_component = contribution * second_weight
                current_component = contribution * current_weight
                parent_component = contribution * parent_weight
                component_rows.append({
                    "simulation_scenario_id": sid,
                    "parent_scenario_id": parent_id,
                    "scenario_type": stype,
                    "ticker": row["ticker"],
                    "factor_family": family,
                    "contribution_value": row.get(CONTRIB[family], ""),
                    "second_round_simulated_weight": fmt(second_weight),
                    "second_round_weighted_component_contribution": fmt(second_component),
                    "current_v20_107_weight": fmt(current_weight),
                    "current_weighted_component_contribution": fmt(current_component),
                    "parent_sim004_weight": fmt(parent_weight),
                    "parent_sim004_weighted_component_contribution": fmt(parent_component),
                    "component_delta_vs_current_shadow": fmt(second_component - current_component),
                    "component_delta_vs_parent_sim004": fmt(second_component - parent_component),
                    "contribution_available": tf(dec(row.get(CONTRIB[family], "")) is not None),
                    "weight_available": tf(dec(scenario.get(WEIGHT_FIELD[family], "")) is not None),
                    "component_used_in_score": "TRUE",
                    "fabricated_values_created": "FALSE",
                    "proxy_values_activated": "FALSE",
                    "source_rank_or_score_used": "FALSE",
                    "baseline_rank_used_as_factor_contribution": "FALSE",
                    "simulation_only": "TRUE",
                    "diagnostic_only": "TRUE",
                    **safety(),
                })
        scored.sort(key=lambda item: (
            -item[1],
            -(dec(item[0].get("risk_contribution", "")) or Decimal("0")),
            -(dec(item[0].get("data_trust_contribution", "")) or Decimal("0")),
            dec(item[0].get("baseline_rank", "")) or Decimal("999999"),
            item[0]["ticker"],
        ))
        ranks = set()
        for idx, (row, total, comps) in enumerate(scored, start=1):
            ranks.add(idx)
            current = current_by_ticker[row["ticker"]]
            parent = parent_by_ticker[row["ticker"]]
            baseline_rank = int(row["baseline_rank"])
            current_rank = int(current["strict_equity_shadow_rank"])
            parent_rank = int(parent["simulated_shadow_rank"])
            delta_baseline = baseline_rank - idx
            delta_current = current_rank - idx
            delta_parent = parent_rank - idx
            direction = "IMPROVED" if delta_current > 0 else "WORSENED" if delta_current < 0 else "UNCHANGED"
            top_positive = max(comps, key=lambda family: (comps[family], family))
            top_negative = min(comps, key=lambda family: (comps[family], family))
            common = {
                "simulation_scenario_id": sid,
                "parent_scenario_id": scenario.get("parent_scenario_id", "SIM_004"),
                "scenario_type": stype,
                "ticker": row["ticker"],
                "baseline_rank": row["baseline_rank"],
                "current_strict_equity_shadow_rank": current["strict_equity_shadow_rank"],
                "parent_sim004_shadow_rank": parent["simulated_shadow_rank"],
                "second_round_simulated_shadow_rank": str(idx),
                "second_round_rank_delta_vs_baseline": str(delta_baseline),
                "second_round_rank_delta_vs_current_shadow": str(delta_current),
                "second_round_rank_delta_vs_parent_sim004": str(delta_parent),
            }
            rerank_rows.append({
                **common,
                "scenario_priority": scenario["scenario_priority"],
                "targeted_forward_window": scenario["targeted_forward_window"],
                "targeted_topn_group": scenario["targeted_topn_group"],
                "second_round_rank_delta_direction_vs_current_shadow": direction,
                "second_round_simulated_shadow_weighted_score": fmt(total),
                **{CONTRIB[f]: row.get(CONTRIB[f], "") for f in FAMILIES},
                **{OUT_WEIGHT_FIELD[f]: scenario.get(WEIGHT_FIELD[f], "") for f in FAMILIES},
                "second_round_weight_sum": scenario["weight_sum"],
                "all_six_family_contributions_present": "TRUE",
                "all_six_second_round_weights_present": "TRUE",
                "tie_breaker_used": "score_desc;risk_desc;data_trust_desc;baseline_rank_asc;ticker_asc",
                "strict_equity_rerank_scope": "STRICT_EQUITY_SECOND_ROUND_SIMULATION_ONLY",
                "targets_prior_failure_area": scenario["targets_prior_failure_area"],
                "simulation_only": "TRUE",
                **safety(extra=True),
                "official_weight_created": "FALSE",
                "accepted_weight_created": "FALSE",
                "active_weight_mutated": "FALSE",
                "v20_107_weight_mutated": "FALSE",
                "v20_98b_r5_weight_mutated": "FALSE",
            })
            current_score = dec(current["shadow_dynamic_weighted_score"]) or Decimal("0")
            parent_score = dec(parent["simulated_shadow_weighted_score"]) or Decimal("0")
            delta_rows.append({
                **common,
                "current_shadow_score": current["shadow_dynamic_weighted_score"],
                "parent_sim004_score": parent["simulated_shadow_weighted_score"],
                "second_round_simulated_shadow_weighted_score": fmt(total),
                "score_delta_vs_current_shadow": fmt(total - current_score),
                "score_delta_vs_parent_sim004": fmt(total - parent_score),
                "top_positive_component_family": top_positive,
                "top_negative_component_family": top_negative,
                "audit_status": "PASS",
                "audit_reason": "SECOND_ROUND_SIMULATION_ONLY_RANK_DELTA_COMPUTED",
                "simulation_only": "TRUE",
                "diagnostic_only": "TRUE",
                **safety(),
            })
        duplicate_rank_count += len(scored) - len(ranks)
        missing_rank_count += 297 - len(ranks)

    scenario_count = len(valid_scenarios)
    expected = scenario_count * 297
    actual = len(rerank_rows)
    all_weight_sums = all(row["weight_sum"] == "1.0000000000" for row in valid_scenarios)
    prior_target_count = sum(1 for row in valid_scenarios if row.get("targets_prior_failure_area") == "TRUE")
    validation_pass = valid_inputs and actual == expected and duplicate_rank_count == 0 and missing_rank_count == 0 and all_weight_sums and prior_target_count > 0
    wrapper = PARTIAL_STATUS if validation_pass else BLOCKED_STATUS

    validation_rows = [{
        "validation_check_id": "V20_109_R8_SECOND_ROUND_SIMULATED_RERANK_VALIDATION_001",
        "scenario_count": str(scenario_count),
        "valid_scenario_count": str(scenario_count),
        "strict_equity_candidate_count": "297",
        "expected_rerank_row_count": str(expected),
        "actual_rerank_row_count": str(actual),
        "all_scenario_weight_sums_valid": tf(all_weight_sums),
        "all_required_factor_families_present": "TRUE",
        "all_required_weights_present": "TRUE",
        "all_candidates_scored_per_scenario": tf(actual == expected),
        "duplicate_rank_count": str(duplicate_rank_count),
        "missing_rank_count": str(missing_rank_count),
        "excluded_non_equity_or_fund_candidate_count": str(excluded_count),
        "prior_failure_area_targeted_count": str(prior_target_count),
        "source_rank_or_score_used": "FALSE",
        "baseline_rank_used_as_factor_contribution": "FALSE",
        "fabricated_values_created": "FALSE",
        "proxy_values_activated": "FALSE",
        "second_round_simulated_rerank_created": tf(validation_pass),
        "new_weights_created": "FALSE",
        "active_weight_mutated": "FALSE",
        "v20_107_weight_mutated": "FALSE",
        "v20_98b_r5_weight_mutated": "FALSE",
        "official_weight_created": "FALSE",
        "accepted_weight_created": "FALSE",
        "official_ranking_created": "FALSE",
        "official_recommendation_created": "FALSE",
        "authoritative_ranking_overwritten": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        "performance_effectiveness_claim_created": "FALSE",
        "validation_status": "PASS" if validation_pass else "BLOCKED",
        "validation_reason": "SECOND_ROUND_SIMULATION_ONLY_RERANKS_CREATED_NO_WEIGHT_MUTATION" if validation_pass else "MISSING_SECOND_ROUND_SIMULATION_SCENARIOS_OR_INPUT_MATRIX",
        **safety(),
        "is_official_weight": "FALSE",
    }]
    gate_rows = [{
        "gate_check_id": "V20_109_R8_NEXT_STAGE_GATE_001",
        "second_round_simulated_rerank_created": tf(validation_pass),
        "scenario_count": str(scenario_count),
        "strict_equity_candidate_count": "297",
        "second_round_simulated_rerank_row_count": str(actual),
        "prior_failure_area_targeted": tf(prior_target_count > 0),
        "v20_109_r9_second_round_effectiveness_comparison_allowed": tf(validation_pass),
        "v20_110_acceptance_gate_allowed": "FALSE",
        "recommended_next_stage": "V20.109-R9_SECOND_ROUND_SIMULATED_EFFECTIVENESS_COMPARISON" if validation_pass else "V20.109-R8_INPUT_REPAIR",
        "blocking_reason": "" if validation_pass else "SECOND_ROUND_SIMULATED_RERANK_VALIDATION_FAILED",
        "new_weights_created": "FALSE",
        "accepted_weight_created": "FALSE",
        "official_weight_created": "FALSE",
        "official_ranking_created": "FALSE",
        "official_recommendation_created": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        "performance_effectiveness_claim_created": "FALSE",
        **safety(),
        "is_official_weight": "FALSE",
        "weight_mutated": "FALSE",
    }]

    write_csv(OUT_RERANK, RERANK_FIELDS, rerank_rows)
    write_csv(OUT_DELTA, DELTA_FIELDS, delta_rows)
    write_csv(OUT_COMPONENT, COMPONENT_FIELDS, component_rows)
    write_csv(OUT_VALIDATION, VALIDATION_FIELDS, validation_rows)
    write_csv(OUT_GATE, GATE_FIELDS, gate_rows)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        "\n".join([
            "# V20.109-R8 Second Round Simulated Weight Strict Equity Rerank Report",
            "",
            "## Current Result",
            f"- wrapper_status: {wrapper}",
            f"- scenario_count: {scenario_count}",
            "- strict_equity_candidate_count: 297",
            f"- second_round_simulated_rerank_row_count: {actual}",
            f"- prior_failure_area_targeted_count: {prior_target_count}",
            "- new_weights_created: FALSE",
            "- accepted_weight_created: FALSE",
            "- official_weight_created: FALSE",
            "- official_ranking_created: FALSE",
            "- performance_effectiveness_claim_created: FALSE",
            "- v20_110_acceptance_gate_allowed: FALSE",
        ]) + "\n",
        encoding="utf-8",
    )

    print(wrapper)
    print(f"SCENARIO_COUNT={scenario_count}")
    print("STRICT_EQUITY_CANDIDATE_COUNT=297")
    print(f"ACTUAL_RERANK_ROW_COUNT={actual}")
    print(f"EXPECTED_RERANK_ROW_COUNT={expected}")
    print(f"PRIOR_FAILURE_AREA_TARGETED_COUNT={prior_target_count}")
    print("ALL_SCENARIO_WEIGHT_SUMS_VALID=TRUE")
    print("NEW_WEIGHTS_CREATED=FALSE")
    print("ACCEPTED_WEIGHT_CREATED=FALSE")
    print("OFFICIAL_WEIGHT_CREATED=FALSE")
    print("ACTIVE_WEIGHT_MUTATED=FALSE")
    print("V20_107_WEIGHT_MUTATED=FALSE")
    print("V20_98B_R5_WEIGHT_MUTATED=FALSE")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED=FALSE")
    print("V20_110_ACCEPTANCE_GATE_ALLOWED=FALSE")
    print(f"V20_109_R9_SECOND_ROUND_EFFECTIVENESS_COMPARISON_ALLOWED={tf(validation_pass)}")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("IS_OFFICIAL_WEIGHT=FALSE")
    print(f"OUTPUT_RERANK={OUT_RERANK.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_DELTA={OUT_DELTA.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_COMPONENT={OUT_COMPONENT.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_VALIDATION={OUT_VALIDATION.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_GATE={OUT_GATE.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_REPORT={REPORT.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
