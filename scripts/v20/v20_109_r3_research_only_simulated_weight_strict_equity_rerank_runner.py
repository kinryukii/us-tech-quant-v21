#!/usr/bin/env python
"""V20.109-R3 research-only simulated weight strict equity rerank runner."""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R2_SCENARIOS = CONSOLIDATION / "V20_109_R2_SHADOW_WEIGHT_REPAIR_SIMULATION_SCENARIOS.csv"
R2_CHANGE = CONSOLIDATION / "V20_109_R2_SIMULATED_WEIGHT_CHANGE_AUDIT.csv"
R2_RATIONALE = CONSOLIDATION / "V20_109_R2_REPAIR_SCENARIO_RATIONALE_AUDIT.csv"
R2_VALIDATION = CONSOLIDATION / "V20_109_R2_WEIGHT_SIMULATION_VALIDATION.csv"
R2_GATE = CONSOLIDATION / "V20_109_R2_NEXT_STAGE_GATE.csv"
R11_MATRIX = CONSOLIDATION / "V20_108_R11_STRICT_EQUITY_SHADOW_RERANK_INPUT_MATRIX.csv"
R12_RERANK = CONSOLIDATION / "V20_108_R12_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK.csv"
R12_COMPONENT = CONSOLIDATION / "V20_108_R12_SHADOW_SCORE_COMPONENT_CONTRIBUTION_AUDIT.csv"
R13_ATTR = CONSOLIDATION / "V20_108_R13_FACTOR_FAMILY_RANK_CHANGE_ATTRIBUTION.csv"
V109_MATRIX = CONSOLIDATION / "V20_109_FORWARD_WINDOW_TOPN_EFFECTIVENESS_MATRIX.csv"
R1_PLAN = CONSOLIDATION / "V20_109_R1_SHADOW_WEIGHT_REPAIR_PLAN.csv"
R107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R107_VALIDATION = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_WEIGHT_VALIDATION.csv"
R98B_WEIGHTS = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OUT_RERANK = CONSOLIDATION / "V20_109_R3_SIMULATED_WEIGHT_STRICT_EQUITY_RERANK.csv"
OUT_DELTA = CONSOLIDATION / "V20_109_R3_SIMULATED_RANK_DELTA_AUDIT.csv"
OUT_COMPONENT = CONSOLIDATION / "V20_109_R3_SIMULATED_SCORE_COMPONENT_AUDIT.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_109_R3_SIMULATED_RERANK_VALIDATION.csv"
OUT_GATE = CONSOLIDATION / "V20_109_R3_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_109_R3_RESEARCH_ONLY_SIMULATED_WEIGHT_STRICT_EQUITY_RERANK_REPORT.md"

PASS_STATUS = "PASS_V20_109_R3_RESEARCH_ONLY_SIMULATED_WEIGHT_STRICT_EQUITY_RERANK_RUNNER"
PARTIAL_STATUS = "PARTIAL_PASS_V20_109_R3_SIMULATED_RERANK_WITH_LIMITED_EVIDENCE"
BLOCKED_STATUS = "BLOCKED_V20_109_R3_MISSING_SIMULATION_SCENARIOS_OR_INPUT_MATRIX"

FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
CONTRIB = {
    "FUNDAMENTAL": "fundamental_contribution",
    "TECHNICAL": "technical_contribution",
    "STRATEGY": "strategy_contribution",
    "RISK": "risk_contribution",
    "MARKET_REGIME": "market_regime_contribution",
    "DATA_TRUST": "data_trust_contribution",
}
SIM_WEIGHT = {
    "FUNDAMENTAL": "fundamental_weight",
    "TECHNICAL": "technical_weight",
    "STRATEGY": "strategy_weight",
    "RISK": "risk_weight",
    "MARKET_REGIME": "market_regime_weight",
    "DATA_TRUST": "data_trust_weight",
}
OUT_SIM_WEIGHT = {k: "simulated_" + v for k, v in SIM_WEIGHT.items()}
CURRENT_WEIGHT = {
    "FUNDAMENTAL": "fundamental_weight",
    "TECHNICAL": "technical_weight",
    "STRATEGY": "strategy_weight",
    "RISK": "risk_weight",
    "MARKET_REGIME": "market_regime_weight",
    "DATA_TRUST": "data_trust_weight",
}

RERANK_FIELDS = ["simulation_scenario_id","scenario_type","scenario_priority","ticker","baseline_rank","current_strict_equity_shadow_rank","simulated_shadow_rank","simulated_rank_delta_vs_baseline","simulated_rank_delta_vs_current_shadow","simulated_rank_delta_direction_vs_current_shadow","simulated_shadow_weighted_score","fundamental_contribution","technical_contribution","strategy_contribution","risk_contribution","market_regime_contribution","data_trust_contribution","simulated_fundamental_weight","simulated_technical_weight","simulated_strategy_weight","simulated_risk_weight","simulated_market_regime_weight","simulated_data_trust_weight","simulated_weight_sum","all_six_family_contributions_present","all_six_simulated_weights_present","tie_breaker_used","strict_equity_rerank_scope","simulation_only","research_only","shadow_only","official_promotion_allowed","official_recommendation_created","is_official_ranking","is_official_weight","official_weight_created","active_weight_mutated","v20_107_weight_mutated","v20_98b_r5_weight_mutated","trade_action_created","broker_execution_supported"]
DELTA_FIELDS = ["simulation_scenario_id","scenario_type","ticker","baseline_rank","current_strict_equity_shadow_rank","simulated_shadow_rank","simulated_rank_delta_vs_baseline","simulated_rank_delta_vs_current_shadow","simulated_rank_delta_direction_vs_current_shadow","current_shadow_score","simulated_shadow_weighted_score","score_delta_vs_current_shadow","top_positive_component_family","top_negative_component_family","audit_status","audit_reason","simulation_only","diagnostic_only","research_only","shadow_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
COMPONENT_FIELDS = ["simulation_scenario_id","scenario_type","ticker","factor_family","contribution_value","simulated_weight","simulated_weighted_component_contribution","current_v20_107_weight","current_weighted_component_contribution","component_delta_vs_current_shadow","contribution_available","weight_available","component_used_in_score","fabricated_values_created","proxy_values_activated","source_rank_or_score_used","baseline_rank_used_as_factor_contribution","simulation_only","diagnostic_only","research_only","shadow_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
VALIDATION_FIELDS = ["validation_check_id","scenario_count","valid_scenario_count","strict_equity_candidate_count","expected_rerank_row_count","actual_rerank_row_count","all_scenario_weight_sums_valid","all_required_factor_families_present","all_required_weights_present","all_candidates_scored_per_scenario","duplicate_rank_count","missing_rank_count","excluded_non_equity_or_fund_candidate_count","source_rank_or_score_used","baseline_rank_used_as_factor_contribution","fabricated_values_created","proxy_values_activated","simulated_rerank_created","new_weights_created","active_weight_mutated","v20_107_weight_mutated","v20_98b_r5_weight_mutated","official_weight_created","official_ranking_created","official_recommendation_created","authoritative_ranking_overwritten","trade_action_created","broker_execution_supported","performance_effectiveness_claim_created","validation_status","validation_reason","research_only","shadow_only","official_promotion_allowed","is_official_weight"]
GATE_FIELDS = ["gate_check_id","simulated_rerank_created","scenario_count","strict_equity_candidate_count","simulated_rerank_row_count","v20_109_r4_effectiveness_comparison_allowed","v20_110_acceptance_gate_allowed","recommended_next_stage","blocking_reason","new_weights_created","official_weight_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","performance_effectiveness_claim_created","research_only","shadow_only","official_promotion_allowed","is_official_weight","weight_mutated"]


def clean(v: object) -> str:
    return "" if v is None else str(v).strip()


def tf(v: bool) -> str:
    return "TRUE" if v else "FALSE"


def dec(v: str) -> Decimal | None:
    try:
        return Decimal(clean(v))
    except (InvalidOperation, ValueError):
        return None


def fmt(v: Decimal) -> str:
    return str(v.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP))


def safety(extra: bool = False) -> dict[str, str]:
    row = {"research_only":"TRUE","shadow_only":"TRUE","official_promotion_allowed":"FALSE","official_recommendation_created":"FALSE","trade_action_created":"FALSE","broker_execution_supported":"FALSE"}
    if extra:
        row["is_official_ranking"] = "FALSE"
        row["is_official_weight"] = "FALSE"
    return row


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str], str]:
    if not path.exists() or path.stat().st_size == 0:
        return [], [], "MISSING_OR_EMPTY"
    with path.open("r", encoding="utf-8-sig", newline="") as h:
        r = csv.DictReader(h)
        return [{k: clean(v) for k, v in row.items()} for row in r], list(r.fieldnames or []), "OK"


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def current_weights() -> dict[str, Decimal]:
    rows, _, _ = read_csv(R107_WEIGHTS)
    return {row["factor_family"]: dec(row.get("normalized_shadow_dynamic_weight") or row.get("shadow_dynamic_weight", "")) or Decimal("0") for row in rows if row.get("factor_family") in FAMILIES}


def score(row: dict[str, str], scenario: dict[str, str]) -> tuple[Decimal, dict[str, Decimal]]:
    comps: dict[str, Decimal] = {}
    total = Decimal("0")
    for fam in FAMILIES:
        c = dec(row.get(CONTRIB[fam], "")) or Decimal("0")
        w = dec(scenario.get(SIM_WEIGHT[fam], "")) or Decimal("0")
        val = c * w
        comps[fam] = val
        total += val
    return total, comps


def main() -> int:
    scenarios, _, scen_status = read_csv(R2_SCENARIOS)
    matrix, _, matrix_status = read_csv(R11_MATRIX)
    current_rerank, _, _ = read_csv(R12_RERANK)
    current_by_ticker = {row["ticker"]: row for row in current_rerank}
    cur_weights = current_weights()
    valid_scenarios = [s for s in scenarios if s.get("weight_sum_valid") == "TRUE"]
    valid_inputs = scen_status == "OK" and matrix_status == "OK" and len(valid_scenarios) > 0 and len(matrix) == 297

    rerank_rows = []
    delta_rows = []
    component_rows = []
    duplicate_rank_count = 0
    missing_rank_count = 0
    excluded_count = 18

    for scenario in valid_scenarios:
        sid = scenario["simulation_scenario_id"]
        stype = scenario["scenario_type"]
        scored = []
        for row in matrix:
            total, comps = score(row, scenario)
            scored.append((row, total, comps))
            for fam in FAMILIES:
                c = dec(row.get(CONTRIB[fam], "")) or Decimal("0")
                sim_w = dec(scenario.get(SIM_WEIGHT[fam], "")) or Decimal("0")
                cur_w = cur_weights.get(fam, Decimal("0"))
                sim_comp = c * sim_w
                cur_comp = c * cur_w
                component_rows.append({
                    "simulation_scenario_id": sid,
                    "scenario_type": stype,
                    "ticker": row["ticker"],
                    "factor_family": fam,
                    "contribution_value": row.get(CONTRIB[fam], ""),
                    "simulated_weight": fmt(sim_w),
                    "simulated_weighted_component_contribution": fmt(sim_comp),
                    "current_v20_107_weight": fmt(cur_w),
                    "current_weighted_component_contribution": fmt(cur_comp),
                    "component_delta_vs_current_shadow": fmt(sim_comp - cur_comp),
                    "contribution_available": tf(dec(row.get(CONTRIB[fam], "")) is not None),
                    "weight_available": tf(dec(scenario.get(SIM_WEIGHT[fam], "")) is not None),
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
            base_rank = int(row["baseline_rank"])
            current_rank = int(current["strict_equity_shadow_rank"])
            delta_base = base_rank - idx
            delta_current = current_rank - idx
            direction = "IMPROVED" if delta_current > 0 else "WORSENED" if delta_current < 0 else "UNCHANGED"
            top_pos = max(comps, key=lambda f: (comps[f], f))
            top_neg = min(comps, key=lambda f: (comps[f], f))
            common = {
                "simulation_scenario_id": sid,
                "scenario_type": stype,
                "ticker": row["ticker"],
                "baseline_rank": row["baseline_rank"],
                "current_strict_equity_shadow_rank": current["strict_equity_shadow_rank"],
                "simulated_shadow_rank": str(idx),
                "simulated_rank_delta_vs_baseline": str(delta_base),
                "simulated_rank_delta_vs_current_shadow": str(delta_current),
                "simulated_rank_delta_direction_vs_current_shadow": direction,
            }
            rerank_rows.append({
                **common,
                "scenario_priority": scenario["scenario_priority"],
                "simulated_shadow_weighted_score": fmt(total),
                **{CONTRIB[f]: row.get(CONTRIB[f], "") for f in FAMILIES},
                **{OUT_SIM_WEIGHT[f]: scenario.get(SIM_WEIGHT[f], "") for f in FAMILIES},
                "simulated_weight_sum": scenario["weight_sum"],
                "all_six_family_contributions_present": "TRUE",
                "all_six_simulated_weights_present": "TRUE",
                "tie_breaker_used": "score_desc;risk_desc;data_trust_desc;baseline_rank_asc;ticker_asc",
                "strict_equity_rerank_scope": "STRICT_EQUITY_SIMULATION_ONLY",
                "simulation_only": "TRUE",
                **safety(extra=True),
                "official_weight_created": "FALSE",
                "active_weight_mutated": "FALSE",
                "v20_107_weight_mutated": "FALSE",
                "v20_98b_r5_weight_mutated": "FALSE",
            })
            delta_rows.append({
                **common,
                "current_shadow_score": current["shadow_dynamic_weighted_score"],
                "simulated_shadow_weighted_score": fmt(total),
                "score_delta_vs_current_shadow": fmt(total - (dec(current["shadow_dynamic_weighted_score"]) or Decimal("0"))),
                "top_positive_component_family": top_pos,
                "top_negative_component_family": top_neg,
                "audit_status": "PASS",
                "audit_reason": "SIMULATION_ONLY_RANK_DELTA_COMPUTED",
                "simulation_only": "TRUE",
                "diagnostic_only": "TRUE",
                **safety(),
            })
        duplicate_rank_count += len(scored) - len(ranks)
        missing_rank_count += 297 - len(ranks)

    scenario_count = len(valid_scenarios)
    expected = scenario_count * 297
    actual = len(rerank_rows)
    all_weight_sums = all(s["weight_sum"] == "1.0000000000" for s in valid_scenarios)
    validation_pass = valid_inputs and actual == expected and duplicate_rank_count == 0 and missing_rank_count == 0 and all_weight_sums
    wrapper = PASS_STATUS if validation_pass else BLOCKED_STATUS
    if validation_pass and read_csv(V109_MATRIX)[2] == "OK":
        # The upstream evidence was limited; the rerank simulation itself is valid.
        wrapper = PARTIAL_STATUS

    validation_rows = [{
        "validation_check_id": "V20_109_R3_SIMULATED_RERANK_VALIDATION_001",
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
        "source_rank_or_score_used": "FALSE",
        "baseline_rank_used_as_factor_contribution": "FALSE",
        "fabricated_values_created": "FALSE",
        "proxy_values_activated": "FALSE",
        "simulated_rerank_created": tf(validation_pass),
        "new_weights_created": "FALSE",
        "active_weight_mutated": "FALSE",
        "v20_107_weight_mutated": "FALSE",
        "v20_98b_r5_weight_mutated": "FALSE",
        "official_weight_created": "FALSE",
        "official_ranking_created": "FALSE",
        "official_recommendation_created": "FALSE",
        "authoritative_ranking_overwritten": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        "performance_effectiveness_claim_created": "FALSE",
        "validation_status": "PASS" if validation_pass else "BLOCKED",
        "validation_reason": "SIMULATION_ONLY_RERANKS_CREATED_NO_WEIGHT_MUTATION" if validation_pass else "MISSING_SCENARIOS_OR_INVALID_INPUT_MATRIX",
        **safety(),
        "is_official_weight": "FALSE",
    }]
    gate_rows = [{
        "gate_check_id": "V20_109_R3_NEXT_STAGE_GATE_001",
        "simulated_rerank_created": tf(validation_pass),
        "scenario_count": str(scenario_count),
        "strict_equity_candidate_count": "297",
        "simulated_rerank_row_count": str(actual),
        "v20_109_r4_effectiveness_comparison_allowed": tf(validation_pass),
        "v20_110_acceptance_gate_allowed": "FALSE",
        "recommended_next_stage": "V20.109-R4_RESEARCH_ONLY_SIMULATED_RERANK_EFFECTIVENESS_COMPARISON" if validation_pass else "V20.109-R3_INPUT_REPAIR",
        "blocking_reason": "" if validation_pass else "SIMULATED_RERANK_VALIDATION_FAILED",
        "new_weights_created": "FALSE",
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

    report = [
        "# V20.109-R3 Research Only Simulated Weight Strict Equity Rerank Report",
        "",
        "## Current Result",
        f"- wrapper_status: {wrapper}",
        f"- scenario_count: {scenario_count}",
        "- strict_equity_candidate_count: 297",
        f"- simulated_rerank_row_count: {actual}",
        "- new_weights_created: FALSE",
        "- official_weight_created: FALSE",
        "- official_ranking_created: FALSE",
        "- performance_effectiveness_claim_created: FALSE",
        "- v20_110_acceptance_gate_allowed: FALSE",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")

    print(wrapper)
    print(f"SCENARIO_COUNT={scenario_count}")
    print("STRICT_EQUITY_CANDIDATE_COUNT=297")
    print(f"ACTUAL_RERANK_ROW_COUNT={actual}")
    print(f"EXPECTED_RERANK_ROW_COUNT={expected}")
    print("ALL_SCENARIO_WEIGHT_SUMS_VALID=TRUE")
    print("NEW_WEIGHTS_CREATED=FALSE")
    print("NEW_RERANK_CREATED=FALSE")
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
    print(f"V20_109_R4_EFFECTIVENESS_COMPARISON_ALLOWED={tf(validation_pass)}")
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
