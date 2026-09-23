#!/usr/bin/env python
"""V20.109-R5 candidate scenario robustness validation."""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R4_SUMMARY = CONSOLIDATION / "V20_109_R4_SIMULATED_SCENARIO_EFFECTIVENESS_SUMMARY.csv"
R4_MATRIX = CONSOLIDATION / "V20_109_R4_FORWARD_WINDOW_TOPN_SCENARIO_COMPARISON_MATRIX.csv"
R4_AUDIT = CONSOLIDATION / "V20_109_R4_SCENARIO_VS_BASELINE_AND_CURRENT_SHADOW_AUDIT.csv"
R4_ATTR = CONSOLIDATION / "V20_109_R4_SIMULATED_SCENARIO_FACTOR_ATTRIBUTION.csv"
R4_SELECTION = CONSOLIDATION / "V20_109_R4_EVIDENCE_QUALITY_AND_SELECTION_AUDIT.csv"
R4_GATE = CONSOLIDATION / "V20_109_R4_NEXT_STAGE_GATE.csv"
R3_RERANK = CONSOLIDATION / "V20_109_R3_SIMULATED_WEIGHT_STRICT_EQUITY_RERANK.csv"
R3_DELTA = CONSOLIDATION / "V20_109_R3_SIMULATED_RANK_DELTA_AUDIT.csv"
R3_COMPONENT = CONSOLIDATION / "V20_109_R3_SIMULATED_SCORE_COMPONENT_AUDIT.csv"
R2_SCENARIOS = CONSOLIDATION / "V20_109_R2_SHADOW_WEIGHT_REPAIR_SIMULATION_SCENARIOS.csv"
R12_RERANK = CONSOLIDATION / "V20_108_R12_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK.csv"
V109_MATRIX = CONSOLIDATION / "V20_109_FORWARD_WINDOW_TOPN_EFFECTIVENESS_MATRIX.csv"
V104_FORWARD = CONSOLIDATION / "V20_104_RANDOM_ASOF_FORWARD_OUTCOME_MATRIX.csv"
V104_BENCH = CONSOLIDATION / "V20_104_RANDOM_ASOF_BENCHMARK_COMPARISON.csv"
V105_HIST = CONSOLIDATION / "V20_105_FACTOR_FAMILY_HISTORICAL_EVIDENCE.csv"
V105_ABLATION = CONSOLIDATION / "V20_105_FACTOR_ABLATION_EVIDENCE_MATRIX.csv"
V106_REGIME = CONSOLIDATION / "V20_106_REGIME_CONDITIONED_FACTOR_ALIGNMENT.csv"
R107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R107_VALIDATION = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_WEIGHT_VALIDATION.csv"
R98B_WEIGHTS = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OUT_SUMMARY = CONSOLIDATION / "V20_109_R5_CANDIDATE_SCENARIO_ROBUSTNESS_SUMMARY.csv"
OUT_WINDOW = CONSOLIDATION / "V20_109_R5_WINDOW_TOPN_ROBUSTNESS_AUDIT.csv"
OUT_BUCKET = CONSOLIDATION / "V20_109_R5_RANK_BUCKET_ROBUSTNESS_AUDIT.csv"
OUT_ATTR = CONSOLIDATION / "V20_109_R5_FACTOR_FAMILY_ROBUSTNESS_ATTRIBUTION.csv"
OUT_SELECTION = CONSOLIDATION / "V20_109_R5_SCENARIO_STABILITY_AND_SELECTION_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_109_R5_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_109_R5_CANDIDATE_SCENARIO_ROBUSTNESS_VALIDATION_REPORT.md"

PASS_STATUS = "PASS_V20_109_R5_CANDIDATE_SCENARIO_ROBUSTNESS_VALIDATION"
PARTIAL_STATUS = "PARTIAL_PASS_V20_109_R5_ROBUSTNESS_VALIDATION_WITH_LIMITED_FORWARD_OUTCOME_COVERAGE"
WARN_STATUS = "WARN_V20_109_R5_SELECTED_SCENARIO_NOT_ROBUST"
BLOCKED_STATUS = "BLOCKED_V20_109_R5_MISSING_R4_SELECTION_OR_SCENARIO_INPUTS"

WINDOWS = ["5D", "10D", "20D", "60D", "120D"]
TOPNS = [10, 20, 50, 100]
BUCKETS = [
    "BIG_PROMOTED_BY_SIMULATION",
    "MODERATE_PROMOTED_BY_SIMULATION",
    "UNCHANGED_OR_SMALL_CHANGE",
    "MODERATE_DEMOTED_BY_SIMULATION",
    "BIG_DEMOTED_BY_SIMULATION",
]

SUMMARY_FIELDS = ["robustness_summary_id","selected_simulation_scenario_id","selected_scenario_type","strict_equity_candidate_count","evaluated_forward_window_count","evaluated_topn_group_count","evaluated_cell_count","cells_beating_baseline_count","cells_beating_current_shadow_count","cells_beating_both_count","cells_losing_to_both_count","average_delta_vs_baseline","average_delta_vs_current_shadow","average_hit_rate_delta_vs_baseline","average_hit_rate_delta_vs_current_shadow","robustness_status","robustness_reason","evidence_coverage_status","accepted_weight_created","new_weights_created","new_rerank_created","performance_effectiveness_claim_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","research_only","shadow_only","simulation_only","official_promotion_allowed","is_official_weight","weight_mutated"]
WINDOW_FIELDS = ["selected_simulation_scenario_id","selected_scenario_type","forward_window","top_n","scenario_mean_forward_return","baseline_mean_forward_return","current_shadow_mean_forward_return","scenario_minus_baseline_mean_return","scenario_minus_current_shadow_mean_return","scenario_median_forward_return","baseline_median_forward_return","current_shadow_median_forward_return","scenario_minus_baseline_median_return","scenario_minus_current_shadow_median_return","scenario_hit_rate","baseline_hit_rate","current_shadow_hit_rate","scenario_minus_baseline_hit_rate","scenario_minus_current_shadow_hit_rate","beats_baseline","beats_current_shadow","beats_both","loses_to_both","cell_robustness_status","cell_robustness_reason","coverage_status","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
BUCKET_FIELDS = ["selected_simulation_scenario_id","selected_scenario_type","rank_bucket","candidate_count","average_rank_delta_vs_current_shadow","average_rank_delta_vs_baseline","forward_window","average_forward_return","median_forward_return","hit_rate","benchmark_relative_return","bucket_robustness_status","bucket_robustness_reason","diagnostic_only","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
ATTR_FIELDS = ["selected_simulation_scenario_id","selected_scenario_type","factor_family","simulated_weight","current_v20_107_weight","weight_change_direction","average_component_contribution_in_top10","average_component_contribution_in_top20","average_component_contribution_in_top50","average_component_contribution_in_top100","average_forward_return_when_component_high","average_forward_return_when_component_low","robustness_signal_status","robustness_signal_reason","repair_signal_confirmed","new_weakness_detected","diagnostic_only","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
SELECTION_FIELDS = ["selection_check_id","selected_simulation_scenario_id","selected_scenario_type","selected_by_r4","r4_best_scenario_id","r4_best_scenario_type","scenario_weight_sum","scenario_weight_sum_valid","accepted_weight_created","new_weights_created","v20_107_weight_mutated","v20_98b_r5_weight_mutated","robustness_status","robustness_sufficient_for_acceptance_gate","robustness_sufficient_for_additional_stress_test","selection_status","selection_reason","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","performance_effectiveness_claim_created","research_only","shadow_only","simulation_only","official_promotion_allowed","is_official_weight","weight_mutated"]
GATE_FIELDS = ["gate_check_id","robustness_validation_created","selected_simulation_scenario_id","selected_scenario_type","robustness_status","robustness_sufficient_for_acceptance_gate","robustness_sufficient_for_additional_stress_test","v20_109_r6_stress_test_allowed","v20_110_acceptance_gate_allowed","recommended_next_stage","blocking_reason","accepted_weight_created","new_weights_created","new_rerank_created","performance_effectiveness_claim_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","research_only","shadow_only","simulation_only","official_promotion_allowed","is_official_weight","weight_mutated"]


def clean(v: object) -> str:
    return "" if v is None else str(v).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def dec(v: str) -> Decimal | None:
    try:
        return Decimal(clean(v))
    except (InvalidOperation, ValueError):
        return None


def fmt(v: Decimal | None) -> str:
    if v is None:
        return ""
    return f"{float(v):.10f}"


def mean(vals: list[Decimal]) -> Decimal | None:
    return sum(vals, Decimal("0")) / Decimal(len(vals)) if vals else None


def med(vals: list[Decimal]) -> Decimal | None:
    return Decimal(str(median(vals))) if vals else None


def hit(vals: list[Decimal]) -> Decimal | None:
    return Decimal(sum(1 for v in vals if v > 0)) / Decimal(len(vals)) if vals else None


def avg(vals: list[Decimal | None]) -> Decimal | None:
    real = [v for v in vals if v is not None]
    return mean(real)


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


def bucket_for(delta_vs_current: int) -> str:
    if delta_vs_current >= 25:
        return "BIG_PROMOTED_BY_SIMULATION"
    if delta_vs_current >= 5:
        return "MODERATE_PROMOTED_BY_SIMULATION"
    if delta_vs_current <= -25:
        return "BIG_DEMOTED_BY_SIMULATION"
    if delta_vs_current <= -5:
        return "MODERATE_DEMOTED_BY_SIMULATION"
    return "UNCHANGED_OR_SMALL_CHANGE"


def main() -> int:
    r4_selection, _, r4_selection_status = read_csv(R4_SELECTION)
    r4_matrix, _, r4_matrix_status = read_csv(R4_MATRIX)
    r4_attr, _, r4_attr_status = read_csv(R4_ATTR)
    r3_rerank, _, r3_status = read_csv(R3_RERANK)
    scenarios, _, scenarios_status = read_csv(R2_SCENARIOS)
    r12, _, r12_status = read_csv(R12_RERANK)
    forward, _, forward_status = read_csv(V104_FORWARD)

    required_ok = all(s == "OK" for s in [r4_selection_status, r4_matrix_status, r4_attr_status, r3_status, scenarios_status, r12_status, forward_status])
    best_id = r4_selection[0].get("best_scenario_id", "") if r4_selection else ""
    best_type = r4_selection[0].get("best_scenario_type", "") if r4_selection else ""
    selected_id = best_id or "SIM_004"
    selected_type = best_type or "HIGHER_FUNDAMENTAL_WEIGHT_SCENARIO"
    selected_by_r4 = selected_id == best_id and bool(best_id)
    scenario = next((row for row in scenarios if row.get("simulation_scenario_id") == selected_id), {})
    selected_rows = [row for row in r3_rerank if row.get("simulation_scenario_id") == selected_id]
    selected_matrix = [row for row in r4_matrix if row.get("simulation_scenario_id") == selected_id]
    selected_attr = [row for row in r4_attr if row.get("simulation_scenario_id") == selected_id]
    strict_tickers = {row["ticker"] for row in selected_rows}
    scenario_ok = (
        required_ok
        and selected_rows
        and len(strict_tickers) == 297
        and scenario.get("simulation_only") == "TRUE"
        and scenario.get("official_weight_created") == "FALSE"
        and scenario.get("v20_107_weight_mutated") == "FALSE"
        and scenario.get("v20_98b_r5_weight_mutated") == "FALSE"
        and scenario.get("weight_sum_valid") == "TRUE"
    )

    window_rows: list[dict[str, str]] = []
    mean_base_deltas: list[Decimal | None] = []
    mean_shadow_deltas: list[Decimal | None] = []
    hit_base_deltas: list[Decimal | None] = []
    hit_shadow_deltas: list[Decimal | None] = []
    beats_base = beats_shadow = beats_both = loses_both = 0
    any_partial = False
    for row in selected_matrix:
        d_base = dec(row.get("scenario_minus_baseline_mean_return", ""))
        d_shadow = dec(row.get("scenario_minus_current_shadow_mean_return", ""))
        h_base = dec(row.get("scenario_minus_baseline_hit_rate", ""))
        h_shadow = dec(row.get("scenario_minus_current_shadow_hit_rate", ""))
        beat_base = d_base is not None and d_base > 0
        beat_shadow = d_shadow is not None and d_shadow > 0
        lose_base = d_base is not None and d_base < 0
        lose_shadow = d_shadow is not None and d_shadow < 0
        beats_base += int(beat_base)
        beats_shadow += int(beat_shadow)
        beats_both += int(beat_base and beat_shadow)
        loses_both += int(lose_base and lose_shadow)
        mean_base_deltas.append(d_base)
        mean_shadow_deltas.append(d_shadow)
        hit_base_deltas.append(h_base)
        hit_shadow_deltas.append(h_shadow)
        any_partial = any_partial or row.get("coverage_status") == "PARTIAL_FORWARD_OUTCOME_COVERAGE"
        if beat_base and beat_shadow:
            status = "CELL_ROBUST_BEATS_BOTH"
        elif beat_shadow:
            status = "CELL_BEATS_CURRENT_SHADOW_ONLY"
        elif beat_base:
            status = "CELL_BEATS_BASELINE_ONLY"
        elif lose_base and lose_shadow:
            status = "CELL_LOSES_TO_BOTH"
        else:
            status = "CELL_MIXED_OR_INCONCLUSIVE"
        window_rows.append({
            "selected_simulation_scenario_id": selected_id,
            "selected_scenario_type": selected_type,
            "forward_window": row.get("forward_window", ""),
            "top_n": row.get("top_n", ""),
            "scenario_mean_forward_return": row.get("scenario_mean_forward_return", ""),
            "baseline_mean_forward_return": row.get("baseline_mean_forward_return", ""),
            "current_shadow_mean_forward_return": row.get("current_shadow_mean_forward_return", ""),
            "scenario_minus_baseline_mean_return": row.get("scenario_minus_baseline_mean_return", ""),
            "scenario_minus_current_shadow_mean_return": row.get("scenario_minus_current_shadow_mean_return", ""),
            "scenario_median_forward_return": row.get("scenario_median_forward_return", ""),
            "baseline_median_forward_return": row.get("baseline_median_forward_return", ""),
            "current_shadow_median_forward_return": row.get("current_shadow_median_forward_return", ""),
            "scenario_minus_baseline_median_return": row.get("scenario_minus_baseline_median_return", ""),
            "scenario_minus_current_shadow_median_return": row.get("scenario_minus_current_shadow_median_return", ""),
            "scenario_hit_rate": row.get("scenario_hit_rate", ""),
            "baseline_hit_rate": row.get("baseline_hit_rate", ""),
            "current_shadow_hit_rate": row.get("current_shadow_hit_rate", ""),
            "scenario_minus_baseline_hit_rate": row.get("scenario_minus_baseline_hit_rate", ""),
            "scenario_minus_current_shadow_hit_rate": row.get("scenario_minus_current_shadow_hit_rate", ""),
            "beats_baseline": tf(beat_base),
            "beats_current_shadow": tf(beat_shadow),
            "beats_both": tf(beat_base and beat_shadow),
            "loses_to_both": tf(lose_base and lose_shadow),
            "cell_robustness_status": status,
            "cell_robustness_reason": "R4 scenario cell reused without imputing missing forward outcomes.",
            "coverage_status": row.get("coverage_status", ""),
            **safety(),
        })

    outcomes: dict[tuple[str, str], list[Decimal]] = {}
    for row in forward:
        ticker = row.get("ticker", "")
        window = row.get("forward_window", "")
        value = dec(row.get("forward_return", ""))
        if ticker in strict_tickers and window in WINDOWS and row.get("outcome_available") == "TRUE" and value is not None:
            outcomes.setdefault((ticker, window), []).append(value)

    bucket_members = {bucket: [] for bucket in BUCKETS}
    for row in selected_rows:
        delta_current = int(dec(row.get("simulated_rank_delta_vs_current_shadow", "0")) or Decimal("0"))
        bucket_members[bucket_for(delta_current)].append(row)

    bucket_rows: list[dict[str, str]] = []
    for bucket in BUCKETS:
        members = bucket_members[bucket]
        avg_delta_current = mean([dec(r.get("simulated_rank_delta_vs_current_shadow", "0")) or Decimal("0") for r in members])
        avg_delta_base = mean([dec(r.get("simulated_rank_delta_vs_baseline", "0")) or Decimal("0") for r in members])
        tickers = {r["ticker"] for r in members}
        for window in WINDOWS:
            vals = [v for t in tickers for v in outcomes.get((t, window), [])]
            avg_return = mean(vals)
            med_return = med(vals)
            hit_rate = hit(vals)
            if not vals:
                status = "BUCKET_FORWARD_OUTCOME_MISSING"
            elif bucket in {"BIG_PROMOTED_BY_SIMULATION", "MODERATE_PROMOTED_BY_SIMULATION"} and avg_return is not None and avg_return > 0:
                status = "PROMOTION_BUCKET_SUPPORTIVE"
            elif bucket in {"BIG_DEMOTED_BY_SIMULATION", "MODERATE_DEMOTED_BY_SIMULATION"} and avg_return is not None and avg_return < 0:
                status = "DEMOTION_BUCKET_SUPPORTIVE"
            else:
                status = "BUCKET_MIXED_OR_WEAK"
            bucket_rows.append({
                "selected_simulation_scenario_id": selected_id,
                "selected_scenario_type": selected_type,
                "rank_bucket": bucket,
                "candidate_count": str(len(members)),
                "average_rank_delta_vs_current_shadow": fmt(avg_delta_current),
                "average_rank_delta_vs_baseline": fmt(avg_delta_base),
                "forward_window": window,
                "average_forward_return": fmt(avg_return),
                "median_forward_return": fmt(med_return),
                "hit_rate": fmt(hit_rate),
                "benchmark_relative_return": "",
                "bucket_robustness_status": status,
                "bucket_robustness_reason": "Bucket uses selected scenario rank deltas and available V20.104 forward outcomes only.",
                "diagnostic_only": "TRUE",
                **safety(),
            })

    attr_rows: list[dict[str, str]] = []
    for row in selected_attr:
        high = dec(row.get("average_forward_return_when_component_high", ""))
        low = dec(row.get("average_forward_return_when_component_low", ""))
        direction = row.get("weight_change_direction", "")
        signal = row.get("factor_effectiveness_status", "")
        weakness = direction == "INCREASED" and high is not None and low is not None and high < low
        attr_rows.append({
            "selected_simulation_scenario_id": selected_id,
            "selected_scenario_type": selected_type,
            "factor_family": row.get("factor_family", ""),
            "simulated_weight": row.get("simulated_weight", ""),
            "current_v20_107_weight": row.get("current_v20_107_weight", ""),
            "weight_change_direction": direction,
            "average_component_contribution_in_top10": row.get("average_component_contribution_in_top10", ""),
            "average_component_contribution_in_top20": row.get("average_component_contribution_in_top20", ""),
            "average_component_contribution_in_top50": row.get("average_component_contribution_in_top50", ""),
            "average_component_contribution_in_top100": row.get("average_component_contribution_in_top100", ""),
            "average_forward_return_when_component_high": row.get("average_forward_return_when_component_high", ""),
            "average_forward_return_when_component_low": row.get("average_forward_return_when_component_low", ""),
            "robustness_signal_status": "ROBUSTNESS_SIGNAL_SUPPORTIVE" if signal == "COMPONENT_SIGNAL_SUPPORTIVE" else "ROBUSTNESS_SIGNAL_MIXED_OR_WEAK",
            "robustness_signal_reason": "Factor signal copied from R4 attribution and checked for new weakness; diagnostic only.",
            "repair_signal_confirmed": row.get("repair_signal_confirmed", "FALSE"),
            "new_weakness_detected": tf(weakness),
            "diagnostic_only": "TRUE",
            **safety(),
        })

    avg_base = avg(mean_base_deltas)
    avg_shadow = avg(mean_shadow_deltas)
    avg_hit_base = avg(hit_base_deltas)
    avg_hit_shadow = avg(hit_shadow_deltas)
    evidence_status = "PARTIAL_FORWARD_OUTCOME_COVERAGE" if any_partial else "FULL_FORWARD_OUTCOME_COVERAGE"
    if not scenario_ok:
        robustness_status = "FAILED_ROBUSTNESS_VALIDATION"
        wrapper = BLOCKED_STATUS
    elif any_partial:
        robustness_status = "PARTIAL_ROBUSTNESS_LIMITED_COVERAGE"
        wrapper = PARTIAL_STATUS
    elif beats_both >= 12 and avg_shadow is not None and avg_shadow > 0:
        robustness_status = "ROBUST_DIAGNOSTIC_CANDIDATE"
        wrapper = PASS_STATUS
    elif beats_both == 0:
        robustness_status = "FAILED_ROBUSTNESS_VALIDATION"
        wrapper = WARN_STATUS
    else:
        robustness_status = "MIXED_OR_UNSTABLE_CANDIDATE"
        wrapper = WARN_STATUS
    stress_allowed = scenario_ok and robustness_status in {"PARTIAL_ROBUSTNESS_LIMITED_COVERAGE", "ROBUST_DIAGNOSTIC_CANDIDATE", "MIXED_OR_UNSTABLE_CANDIDATE"}

    summary_rows = [{
        "robustness_summary_id": "V20_109_R5_ROBUSTNESS_SUMMARY_001",
        "selected_simulation_scenario_id": selected_id,
        "selected_scenario_type": selected_type,
        "strict_equity_candidate_count": str(len(strict_tickers)),
        "evaluated_forward_window_count": str(len(WINDOWS)),
        "evaluated_topn_group_count": str(len(TOPNS)),
        "evaluated_cell_count": str(len(window_rows)),
        "cells_beating_baseline_count": str(beats_base),
        "cells_beating_current_shadow_count": str(beats_shadow),
        "cells_beating_both_count": str(beats_both),
        "cells_losing_to_both_count": str(loses_both),
        "average_delta_vs_baseline": fmt(avg_base),
        "average_delta_vs_current_shadow": fmt(avg_shadow),
        "average_hit_rate_delta_vs_baseline": fmt(avg_hit_base),
        "average_hit_rate_delta_vs_current_shadow": fmt(avg_hit_shadow),
        "robustness_status": robustness_status,
        "robustness_reason": "Selected scenario remains diagnostic; partial coverage prevents acceptance.",
        "evidence_coverage_status": evidence_status,
        "accepted_weight_created": "FALSE",
        "new_weights_created": "FALSE",
        "new_rerank_created": "FALSE",
        "performance_effectiveness_claim_created": "FALSE",
        "official_ranking_created": "FALSE",
        **safety(),
        "is_official_weight": "FALSE",
        "weight_mutated": "FALSE",
    }]
    selection_rows = [{
        "selection_check_id": "V20_109_R5_SCENARIO_STABILITY_SELECTION_001",
        "selected_simulation_scenario_id": selected_id,
        "selected_scenario_type": selected_type,
        "selected_by_r4": tf(selected_by_r4),
        "r4_best_scenario_id": best_id,
        "r4_best_scenario_type": best_type,
        "scenario_weight_sum": scenario.get("weight_sum", ""),
        "scenario_weight_sum_valid": scenario.get("weight_sum_valid", "FALSE"),
        "accepted_weight_created": "FALSE",
        "new_weights_created": "FALSE",
        "v20_107_weight_mutated": "FALSE",
        "v20_98b_r5_weight_mutated": "FALSE",
        "robustness_status": robustness_status,
        "robustness_sufficient_for_acceptance_gate": "FALSE",
        "robustness_sufficient_for_additional_stress_test": tf(stress_allowed),
        "selection_status": "SELECTED_FOR_RESEARCH_ONLY_STRESS_TEST" if stress_allowed else "NOT_READY_FOR_STRESS_TEST",
        "selection_reason": "R5 does not accept weights; it only allows further research-only stress testing when diagnostics exist.",
        "official_ranking_created": "FALSE",
        "performance_effectiveness_claim_created": "FALSE",
        **safety(),
        "is_official_weight": "FALSE",
        "weight_mutated": "FALSE",
    }]
    gate_rows = [{
        "gate_check_id": "V20_109_R5_NEXT_STAGE_GATE_001",
        "robustness_validation_created": tf(scenario_ok),
        "selected_simulation_scenario_id": selected_id,
        "selected_scenario_type": selected_type,
        "robustness_status": robustness_status,
        "robustness_sufficient_for_acceptance_gate": "FALSE",
        "robustness_sufficient_for_additional_stress_test": tf(stress_allowed),
        "v20_109_r6_stress_test_allowed": tf(stress_allowed),
        "v20_110_acceptance_gate_allowed": "FALSE",
        "recommended_next_stage": "V20.109-R6_RESEARCH_ONLY_SELECTED_SCENARIO_STRESS_TEST" if stress_allowed else "V20.109-R4_SELECTION_REPAIR",
        "blocking_reason": "" if scenario_ok else "MISSING_R4_SELECTION_OR_SCENARIO_INPUTS",
        "accepted_weight_created": "FALSE",
        "new_weights_created": "FALSE",
        "new_rerank_created": "FALSE",
        "performance_effectiveness_claim_created": "FALSE",
        "official_ranking_created": "FALSE",
        **safety(),
        "is_official_weight": "FALSE",
        "weight_mutated": "FALSE",
    }]

    write_csv(OUT_SUMMARY, SUMMARY_FIELDS, summary_rows)
    write_csv(OUT_WINDOW, WINDOW_FIELDS, window_rows)
    write_csv(OUT_BUCKET, BUCKET_FIELDS, bucket_rows)
    write_csv(OUT_ATTR, ATTR_FIELDS, attr_rows)
    write_csv(OUT_SELECTION, SELECTION_FIELDS, selection_rows)
    write_csv(OUT_GATE, GATE_FIELDS, gate_rows)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        "\n".join([
            "# V20.109-R5 Candidate Scenario Robustness Validation Report",
            "",
            "## Current Result",
            f"- wrapper_status: {wrapper}",
            f"- selected_simulation_scenario_id: {selected_id}",
            f"- selected_scenario_type: {selected_type}",
            f"- strict_equity_candidate_count: {len(strict_tickers)}",
            f"- evaluated_cell_count: {len(window_rows)}",
            f"- robustness_status: {robustness_status}",
            "- accepted_weight_created: FALSE",
            "- new_weights_created: FALSE",
            "- new_rerank_created: FALSE",
            "- official_ranking_created: FALSE",
            "- performance_effectiveness_claim_created: FALSE",
            "- v20_110_acceptance_gate_allowed: FALSE",
        ]) + "\n",
        encoding="utf-8",
    )

    print(wrapper)
    print(f"SELECTED_SIMULATION_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_TYPE={selected_type}")
    print(f"STRICT_EQUITY_CANDIDATE_COUNT={len(strict_tickers)}")
    print(f"EVALUATED_CELL_COUNT={len(window_rows)}")
    print(f"ROBUSTNESS_STATUS={robustness_status}")
    print("FORWARD_WINDOWS=5D,10D,20D,60D,120D")
    print("TOPN_GROUPS=10,20,50,100")
    print("ACCEPTED_WEIGHT_CREATED=FALSE")
    print("NEW_WEIGHTS_CREATED=FALSE")
    print("NEW_RERANK_CREATED=FALSE")
    print("V20_107_WEIGHT_MUTATED=FALSE")
    print("V20_98B_R5_WEIGHT_MUTATED=FALSE")
    print("OFFICIAL_WEIGHT_CREATED=FALSE")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED=FALSE")
    print("V20_110_ACCEPTANCE_GATE_ALLOWED=FALSE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("IS_OFFICIAL_WEIGHT=FALSE")
    print(f"OUTPUT_SUMMARY={OUT_SUMMARY.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_WINDOW={OUT_WINDOW.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_BUCKET={OUT_BUCKET.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_ATTRIBUTION={OUT_ATTR.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_SELECTION={OUT_SELECTION.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_GATE={OUT_GATE.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_REPORT={REPORT.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
