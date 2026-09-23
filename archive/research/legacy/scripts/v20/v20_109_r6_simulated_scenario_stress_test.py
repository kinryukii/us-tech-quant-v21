#!/usr/bin/env python
"""V20.109-R6 simulated scenario stress test."""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R5_SUMMARY = CONSOLIDATION / "V20_109_R5_CANDIDATE_SCENARIO_ROBUSTNESS_SUMMARY.csv"
R5_WINDOW = CONSOLIDATION / "V20_109_R5_WINDOW_TOPN_ROBUSTNESS_AUDIT.csv"
R5_BUCKET = CONSOLIDATION / "V20_109_R5_RANK_BUCKET_ROBUSTNESS_AUDIT.csv"
R5_ATTR = CONSOLIDATION / "V20_109_R5_FACTOR_FAMILY_ROBUSTNESS_ATTRIBUTION.csv"
R5_SELECTION = CONSOLIDATION / "V20_109_R5_SCENARIO_STABILITY_AND_SELECTION_AUDIT.csv"
R5_GATE = CONSOLIDATION / "V20_109_R5_NEXT_STAGE_GATE.csv"
R4_SUMMARY = CONSOLIDATION / "V20_109_R4_SIMULATED_SCENARIO_EFFECTIVENESS_SUMMARY.csv"
R4_MATRIX = CONSOLIDATION / "V20_109_R4_FORWARD_WINDOW_TOPN_SCENARIO_COMPARISON_MATRIX.csv"
R4_AUDIT = CONSOLIDATION / "V20_109_R4_SCENARIO_VS_BASELINE_AND_CURRENT_SHADOW_AUDIT.csv"
R4_ATTR = CONSOLIDATION / "V20_109_R4_SIMULATED_SCENARIO_FACTOR_ATTRIBUTION.csv"
R4_SELECTION = CONSOLIDATION / "V20_109_R4_EVIDENCE_QUALITY_AND_SELECTION_AUDIT.csv"
R3_RERANK = CONSOLIDATION / "V20_109_R3_SIMULATED_WEIGHT_STRICT_EQUITY_RERANK.csv"
R3_DELTA = CONSOLIDATION / "V20_109_R3_SIMULATED_RANK_DELTA_AUDIT.csv"
R3_COMPONENT = CONSOLIDATION / "V20_109_R3_SIMULATED_SCORE_COMPONENT_AUDIT.csv"
R1_FAILURE = CONSOLIDATION / "V20_109_R1_FORWARD_WINDOW_TOPN_FAILURE_MAP.csv"
R1_SUMMARY = CONSOLIDATION / "V20_109_R1_UNDERPERFORMANCE_DECOMPOSITION_SUMMARY.csv"
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

OUT_SUMMARY = CONSOLIDATION / "V20_109_R6_SIMULATED_SCENARIO_STRESS_TEST_SUMMARY.csv"
OUT_WINDOW = CONSOLIDATION / "V20_109_R6_FORWARD_WINDOW_STRESS_AUDIT.csv"
OUT_TOPN = CONSOLIDATION / "V20_109_R6_TOPN_CONCENTRATION_AND_TURNOVER_STRESS_AUDIT.csv"
OUT_DOWNSIDE = CONSOLIDATION / "V20_109_R6_DOWNSIDE_AND_HIT_RATE_STRESS_AUDIT.csv"
OUT_PRIOR = CONSOLIDATION / "V20_109_R6_PRIOR_FAILURE_AREA_REPAIR_AUDIT.csv"
OUT_SELECTION = CONSOLIDATION / "V20_109_R6_STRESS_TEST_SELECTION_GATE.csv"
OUT_GATE = CONSOLIDATION / "V20_109_R6_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_109_R6_SIMULATED_SCENARIO_STRESS_TEST_REPORT.md"

PASS_STATUS = "PASS_V20_109_R6_SIMULATED_SCENARIO_STRESS_TEST"
PARTIAL_STATUS = "PARTIAL_PASS_V20_109_R6_STRESS_TEST_WITH_LIMITED_FORWARD_OUTCOME_COVERAGE"
WARN_STATUS = "WARN_V20_109_R6_SCENARIO_FRAGILE_OR_PRIOR_FAILURE_NOT_REPAIRED"
BLOCKED_STATUS = "BLOCKED_V20_109_R6_MISSING_R5_SELECTION_OR_EFFECTIVENESS_INPUTS"

WINDOWS = ["5D", "10D", "20D", "60D", "120D"]
TOPNS = [10, 20, 50, 100]

SUMMARY_FIELDS = ["stress_summary_id","selected_simulation_scenario_id","selected_scenario_type","strict_equity_candidate_count","evaluated_forward_window_count","evaluated_topn_group_count","evaluated_cell_count","stress_pass_cell_count","stress_warn_cell_count","stress_fail_cell_count","insufficient_coverage_cell_count","cells_beating_baseline_count","cells_beating_current_shadow_count","cells_beating_both_count","dominant_prior_failure_area","dominant_prior_failure_area_repaired","overall_stress_status","overall_stress_reason","evidence_coverage_status","accepted_weight_created","new_weights_created","new_rerank_created","performance_effectiveness_claim_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","research_only","shadow_only","simulation_only","official_promotion_allowed","is_official_weight","weight_mutated"]
WINDOW_FIELDS = ["selected_simulation_scenario_id","selected_scenario_type","forward_window","window_cell_count","cells_beating_baseline_count","cells_beating_current_shadow_count","cells_beating_both_count","average_delta_vs_baseline","average_delta_vs_current_shadow","average_hit_rate_delta_vs_baseline","average_hit_rate_delta_vs_current_shadow","downside_proxy_delta_vs_baseline","downside_proxy_delta_vs_current_shadow","window_stress_status","window_stress_reason","coverage_status","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
TOPN_FIELDS = ["selected_simulation_scenario_id","selected_scenario_type","top_n","topn_cell_count","cells_beating_baseline_count","cells_beating_current_shadow_count","cells_beating_both_count","average_turnover_vs_baseline","average_turnover_vs_current_shadow","average_overlap_with_baseline","average_overlap_with_current_shadow","concentration_or_turnover_risk_status","concentration_or_turnover_reason","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
DOWNSIDE_FIELDS = ["selected_simulation_scenario_id","selected_scenario_type","forward_window","top_n","scenario_hit_rate","baseline_hit_rate","current_shadow_hit_rate","scenario_minus_baseline_hit_rate","scenario_minus_current_shadow_hit_rate","scenario_downside_proxy","baseline_downside_proxy","current_shadow_downside_proxy","scenario_minus_baseline_downside_proxy","scenario_minus_current_shadow_downside_proxy","downside_hit_rate_stress_status","downside_hit_rate_stress_reason","coverage_status","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
PRIOR_FIELDS = ["selected_simulation_scenario_id","selected_scenario_type","prior_failure_area","prior_failure_forward_window","prior_failure_top_n","baseline_mean_forward_return","current_shadow_mean_forward_return","selected_scenario_mean_forward_return","selected_minus_baseline_mean_return","selected_minus_current_shadow_mean_return","baseline_hit_rate","current_shadow_hit_rate","selected_scenario_hit_rate","selected_minus_baseline_hit_rate","selected_minus_current_shadow_hit_rate","failure_area_repaired","repair_status","repair_reason","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
SELECTION_FIELDS = ["selection_check_id","selected_simulation_scenario_id","selected_scenario_type","selected_by_r5","stress_test_created","overall_stress_status","dominant_prior_failure_area_repaired","sufficient_for_research_acceptance_review","sufficient_for_additional_simulation","selection_status","selection_reason","accepted_weight_created","new_weights_created","new_rerank_created","performance_effectiveness_claim_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","research_only","shadow_only","simulation_only","official_promotion_allowed","is_official_weight","weight_mutated"]
GATE_FIELDS = ["gate_check_id","stress_test_created","selected_simulation_scenario_id","selected_scenario_type","overall_stress_status","dominant_prior_failure_area_repaired","v20_109_r7_additional_simulation_allowed","v20_110_research_acceptance_review_allowed","v20_110_acceptance_gate_allowed","recommended_next_stage","blocking_reason","accepted_weight_created","new_weights_created","new_rerank_created","performance_effectiveness_claim_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","research_only","shadow_only","simulation_only","official_promotion_allowed","is_official_weight","weight_mutated"]


def clean(v: object) -> str:
    return "" if v is None else str(v).strip()


def tf(v: bool) -> str:
    return "TRUE" if v else "FALSE"


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


def cell_status(row: dict[str, str]) -> str:
    coverage = row.get("coverage_status", "")
    d_base = dec(row.get("scenario_minus_baseline_mean_return", ""))
    d_shadow = dec(row.get("scenario_minus_current_shadow_mean_return", ""))
    h_base = dec(row.get("scenario_minus_baseline_hit_rate", ""))
    h_shadow = dec(row.get("scenario_minus_current_shadow_hit_rate", ""))
    if d_base is None or d_shadow is None:
        return "INSUFFICIENT_COVERAGE_STRESS_CELL"
    if d_base > 0 and d_shadow > 0 and (h_base is None or h_base >= 0) and (h_shadow is None or h_shadow >= 0):
        return "WARN_MIXED_STRESS_CELL" if coverage == "PARTIAL_FORWARD_OUTCOME_COVERAGE" else "PASS_STRESS_CELL"
    if d_base < 0 and d_shadow < 0:
        return "FAIL_STRESS_CELL"
    return "WARN_MIXED_STRESS_CELL"


def main() -> int:
    r5_summary, _, r5_summary_status = read_csv(R5_SUMMARY)
    r5_gate, _, r5_gate_status = read_csv(R5_GATE)
    r4_matrix, _, r4_matrix_status = read_csv(R4_MATRIX)
    r3_rerank, _, r3_status = read_csv(R3_RERANK)
    r1_summary, _, r1_summary_status = read_csv(R1_SUMMARY)

    selected_id = r5_summary[0].get("selected_simulation_scenario_id", "") if r5_summary else ""
    selected_type = r5_summary[0].get("selected_scenario_type", "") if r5_summary else ""
    selected_by_r5 = bool(selected_id)
    selected_rows = [r for r in r3_rerank if r.get("simulation_scenario_id") == selected_id]
    selected_matrix = [r for r in r4_matrix if r.get("simulation_scenario_id") == selected_id]
    strict_count = len({r["ticker"] for r in selected_rows})
    dominant_area = r1_summary[0].get("dominant_underperformance_area", "120D_TOP20") if r1_summary else "120D_TOP20"
    required_ok = all(s == "OK" for s in [r5_summary_status, r5_gate_status, r4_matrix_status, r3_status, r1_summary_status]) and strict_count == 297 and len(selected_matrix) == 20

    downside_rows: list[dict[str, str]] = []
    pass_count = warn_count = fail_count = insufficient_count = 0
    beats_base = beats_shadow = beats_both = 0
    any_partial = False
    for row in selected_matrix:
        status = cell_status(row)
        pass_count += int(status == "PASS_STRESS_CELL")
        warn_count += int(status == "WARN_MIXED_STRESS_CELL")
        fail_count += int(status == "FAIL_STRESS_CELL")
        insufficient_count += int(status == "INSUFFICIENT_COVERAGE_STRESS_CELL")
        d_base = dec(row.get("scenario_minus_baseline_mean_return", ""))
        d_shadow = dec(row.get("scenario_minus_current_shadow_mean_return", ""))
        beats_base += int(d_base is not None and d_base > 0)
        beats_shadow += int(d_shadow is not None and d_shadow > 0)
        beats_both += int(d_base is not None and d_shadow is not None and d_base > 0 and d_shadow > 0)
        any_partial = any_partial or row.get("coverage_status") == "PARTIAL_FORWARD_OUTCOME_COVERAGE"
        s_down = dec(row.get("scenario_downside_proxy", ""))
        b_down = dec(row.get("baseline_downside_proxy", ""))
        c_down = dec(row.get("current_shadow_downside_proxy", ""))
        downside_rows.append({
            "selected_simulation_scenario_id": selected_id,
            "selected_scenario_type": selected_type,
            "forward_window": row.get("forward_window", ""),
            "top_n": row.get("top_n", ""),
            "scenario_hit_rate": row.get("scenario_hit_rate", ""),
            "baseline_hit_rate": row.get("baseline_hit_rate", ""),
            "current_shadow_hit_rate": row.get("current_shadow_hit_rate", ""),
            "scenario_minus_baseline_hit_rate": row.get("scenario_minus_baseline_hit_rate", ""),
            "scenario_minus_current_shadow_hit_rate": row.get("scenario_minus_current_shadow_hit_rate", ""),
            "scenario_downside_proxy": row.get("scenario_downside_proxy", ""),
            "baseline_downside_proxy": row.get("baseline_downside_proxy", ""),
            "current_shadow_downside_proxy": row.get("current_shadow_downside_proxy", ""),
            "scenario_minus_baseline_downside_proxy": fmt(s_down - b_down if s_down is not None and b_down is not None else None),
            "scenario_minus_current_shadow_downside_proxy": fmt(s_down - c_down if s_down is not None and c_down is not None else None),
            "downside_hit_rate_stress_status": status,
            "downside_hit_rate_stress_reason": "Stress cell uses only available R4/V20.104 outcome-derived hit rate and downside proxy.",
            "coverage_status": row.get("coverage_status", ""),
            **safety(),
        })

    window_rows: list[dict[str, str]] = []
    for window in WINDOWS:
        rows = [r for r in selected_matrix if r.get("forward_window") == window]
        statuses = [cell_status(r) for r in rows]
        d_base = [dec(r.get("scenario_minus_baseline_mean_return", "")) for r in rows]
        d_shadow = [dec(r.get("scenario_minus_current_shadow_mean_return", "")) for r in rows]
        h_base = [dec(r.get("scenario_minus_baseline_hit_rate", "")) for r in rows]
        h_shadow = [dec(r.get("scenario_minus_current_shadow_hit_rate", "")) for r in rows]
        sd_base = []
        sd_shadow = []
        for r in rows:
            s = dec(r.get("scenario_downside_proxy", ""))
            b = dec(r.get("baseline_downside_proxy", ""))
            c = dec(r.get("current_shadow_downside_proxy", ""))
            sd_base.append(s - b if s is not None and b is not None else None)
            sd_shadow.append(s - c if s is not None and c is not None else None)
        coverage = "PARTIAL_FORWARD_OUTCOME_COVERAGE" if any(r.get("coverage_status") == "PARTIAL_FORWARD_OUTCOME_COVERAGE" for r in rows) else "FULL_FORWARD_OUTCOME_COVERAGE"
        beat_base = sum(1 for v in d_base if v is not None and v > 0)
        beat_shadow = sum(1 for v in d_shadow if v is not None and v > 0)
        beat_both = sum(1 for a, b in zip(d_base, d_shadow) if a is not None and b is not None and a > 0 and b > 0)
        if "FAIL_STRESS_CELL" in statuses:
            w_status = "FAIL_STRESS_CELL"
        elif all(s == "PASS_STRESS_CELL" for s in statuses):
            w_status = "PASS_STRESS_CELL"
        elif all(s == "INSUFFICIENT_COVERAGE_STRESS_CELL" for s in statuses):
            w_status = "INSUFFICIENT_COVERAGE_STRESS_CELL"
        else:
            w_status = "WARN_MIXED_STRESS_CELL"
        window_rows.append({
            "selected_simulation_scenario_id": selected_id,
            "selected_scenario_type": selected_type,
            "forward_window": window,
            "window_cell_count": str(len(rows)),
            "cells_beating_baseline_count": str(beat_base),
            "cells_beating_current_shadow_count": str(beat_shadow),
            "cells_beating_both_count": str(beat_both),
            "average_delta_vs_baseline": fmt(avg(d_base)),
            "average_delta_vs_current_shadow": fmt(avg(d_shadow)),
            "average_hit_rate_delta_vs_baseline": fmt(avg(h_base)),
            "average_hit_rate_delta_vs_current_shadow": fmt(avg(h_shadow)),
            "downside_proxy_delta_vs_baseline": fmt(avg(sd_base)),
            "downside_proxy_delta_vs_current_shadow": fmt(avg(sd_shadow)),
            "window_stress_status": w_status,
            "window_stress_reason": "Aggregated from selected scenario top-N stress cells.",
            "coverage_status": coverage,
            **safety(),
        })

    topn_rows: list[dict[str, str]] = []
    for topn in TOPNS:
        rows = [r for r in selected_matrix if r.get("top_n") == str(topn)]
        d_base = [dec(r.get("scenario_minus_baseline_mean_return", "")) for r in rows]
        d_shadow = [dec(r.get("scenario_minus_current_shadow_mean_return", "")) for r in rows]
        beat_base = sum(1 for v in d_base if v is not None and v > 0)
        beat_shadow = sum(1 for v in d_shadow if v is not None and v > 0)
        beat_both = sum(1 for a, b in zip(d_base, d_shadow) if a is not None and b is not None and a > 0 and b > 0)
        scenario_counts = [dec(r.get("scenario_top_n_count", "")) for r in rows]
        baseline_overlaps = [dec(r.get("overlap_with_baseline_count", "")) for r in rows]
        shadow_overlaps = [dec(r.get("overlap_with_current_shadow_count", "")) for r in rows]
        turnovers_base = [s - o if s is not None and o is not None else None for s, o in zip(scenario_counts, baseline_overlaps)]
        turnovers_shadow = [s - o if s is not None and o is not None else None for s, o in zip(scenario_counts, shadow_overlaps)]
        turnover_ratio_shadow = (avg(turnovers_shadow) / Decimal(str(topn))) if avg(turnovers_shadow) is not None else None
        risk_status = "TURNOVER_CONCENTRATION_ACCEPTABLE_DIAGNOSTIC"
        if turnover_ratio_shadow is not None and turnover_ratio_shadow > Decimal("0.50"):
            risk_status = "TURNOVER_CONCENTRATION_ELEVATED"
        topn_rows.append({
            "selected_simulation_scenario_id": selected_id,
            "selected_scenario_type": selected_type,
            "top_n": str(topn),
            "topn_cell_count": str(len(rows)),
            "cells_beating_baseline_count": str(beat_base),
            "cells_beating_current_shadow_count": str(beat_shadow),
            "cells_beating_both_count": str(beat_both),
            "average_turnover_vs_baseline": fmt(avg(turnovers_base)),
            "average_turnover_vs_current_shadow": fmt(avg(turnovers_shadow)),
            "average_overlap_with_baseline": fmt(avg(baseline_overlaps)),
            "average_overlap_with_current_shadow": fmt(avg(shadow_overlaps)),
            "concentration_or_turnover_risk_status": risk_status,
            "concentration_or_turnover_reason": "Turnover measured against baseline and current shadow top-N memberships; no rerank created.",
            **safety(),
        })

    prior_window = "120D"
    prior_topn = "20"
    prior_row = next((r for r in selected_matrix if r.get("forward_window") == prior_window and r.get("top_n") == prior_topn), {})
    prior_d_base = dec(prior_row.get("scenario_minus_baseline_mean_return", ""))
    prior_d_shadow = dec(prior_row.get("scenario_minus_current_shadow_mean_return", ""))
    prior_h_base = dec(prior_row.get("scenario_minus_baseline_hit_rate", ""))
    prior_h_shadow = dec(prior_row.get("scenario_minus_current_shadow_hit_rate", ""))
    repaired = prior_d_base is not None and prior_d_shadow is not None and prior_d_base > 0 and prior_d_shadow > 0
    prior_rows = [{
        "selected_simulation_scenario_id": selected_id,
        "selected_scenario_type": selected_type,
        "prior_failure_area": dominant_area,
        "prior_failure_forward_window": prior_window,
        "prior_failure_top_n": prior_topn,
        "baseline_mean_forward_return": prior_row.get("baseline_mean_forward_return", ""),
        "current_shadow_mean_forward_return": prior_row.get("current_shadow_mean_forward_return", ""),
        "selected_scenario_mean_forward_return": prior_row.get("scenario_mean_forward_return", ""),
        "selected_minus_baseline_mean_return": prior_row.get("scenario_minus_baseline_mean_return", ""),
        "selected_minus_current_shadow_mean_return": prior_row.get("scenario_minus_current_shadow_mean_return", ""),
        "baseline_hit_rate": prior_row.get("baseline_hit_rate", ""),
        "current_shadow_hit_rate": prior_row.get("current_shadow_hit_rate", ""),
        "selected_scenario_hit_rate": prior_row.get("scenario_hit_rate", ""),
        "selected_minus_baseline_hit_rate": prior_row.get("scenario_minus_baseline_hit_rate", ""),
        "selected_minus_current_shadow_hit_rate": prior_row.get("scenario_minus_current_shadow_hit_rate", ""),
        "failure_area_repaired": tf(repaired),
        "repair_status": "PRIOR_FAILURE_AREA_REPAIRED_DIAGNOSTIC" if repaired else "PRIOR_FAILURE_AREA_NOT_REPAIRED",
        "repair_reason": "120D_TOP20 requires selected scenario to beat both baseline and current shadow on mean return.",
        **safety(),
    }]

    evidence_status = "PARTIAL_FORWARD_OUTCOME_COVERAGE" if any_partial else "FULL_FORWARD_OUTCOME_COVERAGE"
    if not required_ok:
        overall_status = "FAIL_STRESS_TEST"
        wrapper = BLOCKED_STATUS
    elif not repaired:
        overall_status = "WARN_MIXED_OR_FRAGILE_STRESS_TEST"
        wrapper = WARN_STATUS
    elif any_partial:
        overall_status = "PARTIAL_PASS_LIMITED_COVERAGE_STRESS_TEST"
        wrapper = PARTIAL_STATUS
    elif fail_count == 0 and pass_count >= 12:
        overall_status = "PASS_RESEARCH_ONLY_STRESS_TEST"
        wrapper = PASS_STATUS
    else:
        overall_status = "WARN_MIXED_OR_FRAGILE_STRESS_TEST"
        wrapper = WARN_STATUS
    additional_allowed = required_ok and overall_status in {"PARTIAL_PASS_LIMITED_COVERAGE_STRESS_TEST", "WARN_MIXED_OR_FRAGILE_STRESS_TEST"}
    acceptance_review_allowed = required_ok and overall_status == "PASS_RESEARCH_ONLY_STRESS_TEST" and repaired and not any_partial

    summary_rows = [{
        "stress_summary_id": "V20_109_R6_STRESS_SUMMARY_001",
        "selected_simulation_scenario_id": selected_id,
        "selected_scenario_type": selected_type,
        "strict_equity_candidate_count": str(strict_count),
        "evaluated_forward_window_count": str(len(WINDOWS)),
        "evaluated_topn_group_count": str(len(TOPNS)),
        "evaluated_cell_count": str(len(selected_matrix)),
        "stress_pass_cell_count": str(pass_count),
        "stress_warn_cell_count": str(warn_count),
        "stress_fail_cell_count": str(fail_count),
        "insufficient_coverage_cell_count": str(insufficient_count),
        "cells_beating_baseline_count": str(beats_base),
        "cells_beating_current_shadow_count": str(beats_shadow),
        "cells_beating_both_count": str(beats_both),
        "dominant_prior_failure_area": dominant_area,
        "dominant_prior_failure_area_repaired": tf(repaired),
        "overall_stress_status": overall_status,
        "overall_stress_reason": "Stress test is diagnostic only; partial coverage or unrepaired prior failure blocks acceptance.",
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
        "selection_check_id": "V20_109_R6_STRESS_SELECTION_001",
        "selected_simulation_scenario_id": selected_id,
        "selected_scenario_type": selected_type,
        "selected_by_r5": tf(selected_by_r5),
        "stress_test_created": tf(required_ok),
        "overall_stress_status": overall_status,
        "dominant_prior_failure_area_repaired": tf(repaired),
        "sufficient_for_research_acceptance_review": tf(acceptance_review_allowed),
        "sufficient_for_additional_simulation": tf(additional_allowed),
        "selection_status": "REQUIRES_ADDITIONAL_SIMULATION_OR_STRESS_REPAIR" if additional_allowed else ("READY_FOR_RESEARCH_ACCEPTANCE_REVIEW" if acceptance_review_allowed else "STRESS_TEST_BLOCKED"),
        "selection_reason": "No accepted weights or official artifacts are created by this stress test.",
        "accepted_weight_created": "FALSE",
        "new_weights_created": "FALSE",
        "new_rerank_created": "FALSE",
        "performance_effectiveness_claim_created": "FALSE",
        "official_ranking_created": "FALSE",
        **safety(),
        "is_official_weight": "FALSE",
        "weight_mutated": "FALSE",
    }]
    gate_rows = [{
        "gate_check_id": "V20_109_R6_NEXT_STAGE_GATE_001",
        "stress_test_created": tf(required_ok),
        "selected_simulation_scenario_id": selected_id,
        "selected_scenario_type": selected_type,
        "overall_stress_status": overall_status,
        "dominant_prior_failure_area_repaired": tf(repaired),
        "v20_109_r7_additional_simulation_allowed": tf(additional_allowed),
        "v20_110_research_acceptance_review_allowed": tf(acceptance_review_allowed),
        "v20_110_acceptance_gate_allowed": "FALSE",
        "recommended_next_stage": "V20.109-R7_ADDITIONAL_RESEARCH_ONLY_SIMULATION" if additional_allowed else ("V20.110_RESEARCH_ACCEPTANCE_REVIEW" if acceptance_review_allowed else "V20.109-R6_INPUT_REPAIR"),
        "blocking_reason": "" if required_ok else "MISSING_R5_SELECTION_OR_EFFECTIVENESS_INPUTS",
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
    write_csv(OUT_TOPN, TOPN_FIELDS, topn_rows)
    write_csv(OUT_DOWNSIDE, DOWNSIDE_FIELDS, downside_rows)
    write_csv(OUT_PRIOR, PRIOR_FIELDS, prior_rows)
    write_csv(OUT_SELECTION, SELECTION_FIELDS, selection_rows)
    write_csv(OUT_GATE, GATE_FIELDS, gate_rows)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        "\n".join([
            "# V20.109-R6 Simulated Scenario Stress Test Report",
            "",
            "## Current Result",
            f"- wrapper_status: {wrapper}",
            f"- selected_simulation_scenario_id: {selected_id}",
            f"- selected_scenario_type: {selected_type}",
            f"- strict_equity_candidate_count: {strict_count}",
            f"- evaluated_cell_count: {len(selected_matrix)}",
            f"- overall_stress_status: {overall_status}",
            f"- dominant_prior_failure_area: {dominant_area}",
            f"- dominant_prior_failure_area_repaired: {tf(repaired)}",
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
    print(f"STRICT_EQUITY_CANDIDATE_COUNT={strict_count}")
    print(f"EVALUATED_CELL_COUNT={len(selected_matrix)}")
    print(f"DOMINANT_PRIOR_FAILURE_AREA={dominant_area}")
    print(f"DOMINANT_PRIOR_FAILURE_AREA_REPAIRED={tf(repaired)}")
    print(f"OVERALL_STRESS_STATUS={overall_status}")
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
    print(f"OUTPUT_TOPN={OUT_TOPN.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_DOWNSIDE={OUT_DOWNSIDE.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_PRIOR={OUT_PRIOR.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_SELECTION={OUT_SELECTION.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_GATE={OUT_GATE.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_REPORT={REPORT.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
