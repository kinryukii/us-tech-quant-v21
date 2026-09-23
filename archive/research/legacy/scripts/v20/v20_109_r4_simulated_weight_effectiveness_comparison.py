#!/usr/bin/env python
"""V20.109-R4 research-only simulated weight effectiveness comparison."""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R3_RERANK = CONSOLIDATION / "V20_109_R3_SIMULATED_WEIGHT_STRICT_EQUITY_RERANK.csv"
R3_DELTA = CONSOLIDATION / "V20_109_R3_SIMULATED_RANK_DELTA_AUDIT.csv"
R3_COMPONENT = CONSOLIDATION / "V20_109_R3_SIMULATED_SCORE_COMPONENT_AUDIT.csv"
R3_VALIDATION = CONSOLIDATION / "V20_109_R3_SIMULATED_RERANK_VALIDATION.csv"
R3_GATE = CONSOLIDATION / "V20_109_R3_NEXT_STAGE_GATE.csv"
R2_SCENARIOS = CONSOLIDATION / "V20_109_R2_SHADOW_WEIGHT_REPAIR_SIMULATION_SCENARIOS.csv"
R2_CHANGE = CONSOLIDATION / "V20_109_R2_SIMULATED_WEIGHT_CHANGE_AUDIT.csv"
R2_RATIONALE = CONSOLIDATION / "V20_109_R2_REPAIR_SCENARIO_RATIONALE_AUDIT.csv"
R12_RERANK = CONSOLIDATION / "V20_108_R12_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK.csv"
V109_MATRIX = CONSOLIDATION / "V20_109_FORWARD_WINDOW_TOPN_EFFECTIVENESS_MATRIX.csv"
V109_SUMMARY = CONSOLIDATION / "V20_109_STRICT_EQUITY_SHADOW_VS_BASELINE_EFFECTIVENESS_SUMMARY.csv"
V109_ATTR = CONSOLIDATION / "V20_109_SHADOW_RERANK_FACTOR_EFFECTIVENESS_ATTRIBUTION.csv"
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

OUT_SUMMARY = CONSOLIDATION / "V20_109_R4_SIMULATED_SCENARIO_EFFECTIVENESS_SUMMARY.csv"
OUT_MATRIX = CONSOLIDATION / "V20_109_R4_FORWARD_WINDOW_TOPN_SCENARIO_COMPARISON_MATRIX.csv"
OUT_AUDIT = CONSOLIDATION / "V20_109_R4_SCENARIO_VS_BASELINE_AND_CURRENT_SHADOW_AUDIT.csv"
OUT_ATTR = CONSOLIDATION / "V20_109_R4_SIMULATED_SCENARIO_FACTOR_ATTRIBUTION.csv"
OUT_SELECTION = CONSOLIDATION / "V20_109_R4_EVIDENCE_QUALITY_AND_SELECTION_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_109_R4_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_109_R4_SIMULATED_WEIGHT_EFFECTIVENESS_COMPARISON_REPORT.md"

PASS_STATUS = "PASS_V20_109_R4_SIMULATED_WEIGHT_EFFECTIVENESS_COMPARISON"
PARTIAL_STATUS = "PARTIAL_PASS_V20_109_R4_SIMULATED_EFFECTIVENESS_COMPARISON_WITH_LIMITED_FORWARD_OUTCOME_COVERAGE"
WARN_STATUS = "WARN_V20_109_R4_NO_SIMULATED_SCENARIO_IMPROVES_CURRENT_SHADOW"
BLOCKED_STATUS = "BLOCKED_V20_109_R4_MISSING_SIMULATED_RERANK_OR_FORWARD_OUTCOME_INPUTS"

WINDOWS = ["5D", "10D", "20D", "60D", "120D"]
TOPNS = [10, 20, 50, 100]
FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]

SUMMARY_FIELDS = ["simulation_scenario_id","scenario_type","scenario_priority","strict_equity_candidate_count","evaluated_cell_count","cells_beating_baseline_count","cells_beating_current_shadow_count","cells_beating_both_count","cells_losing_to_both_count","average_scenario_minus_baseline_mean_return","average_scenario_minus_current_shadow_mean_return","average_scenario_minus_baseline_median_return","average_scenario_minus_current_shadow_median_return","average_scenario_minus_baseline_hit_rate","average_scenario_minus_current_shadow_hit_rate","short_window_success_count","medium_window_success_count","long_window_success_count","top10_success_count","top20_success_count","top50_success_count","top100_success_count","evidence_coverage_status","scenario_effectiveness_status","scenario_effectiveness_reason","research_only_candidate_for_next_validation","accepted_weight_created","new_rerank_created","performance_effectiveness_claim_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","research_only","shadow_only","simulation_only","official_promotion_allowed","is_official_weight","weight_mutated"]
MATRIX_FIELDS = ["simulation_scenario_id","scenario_type","forward_window","top_n","scenario_top_n_count","baseline_top_n_count","current_shadow_top_n_count","overlap_with_baseline_count","overlap_with_current_shadow_count","scenario_mean_forward_return","baseline_mean_forward_return","current_shadow_mean_forward_return","scenario_minus_baseline_mean_return","scenario_minus_current_shadow_mean_return","scenario_median_forward_return","baseline_median_forward_return","current_shadow_median_forward_return","scenario_minus_baseline_median_return","scenario_minus_current_shadow_median_return","scenario_hit_rate","baseline_hit_rate","current_shadow_hit_rate","scenario_minus_baseline_hit_rate","scenario_minus_current_shadow_hit_rate","scenario_downside_proxy","baseline_downside_proxy","current_shadow_downside_proxy","risk_adjusted_delta_vs_baseline","risk_adjusted_delta_vs_current_shadow","available_forward_outcome_count","missing_forward_outcome_count","coverage_status","cell_effectiveness_status","cell_effectiveness_reason","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
AUDIT_FIELDS = ["simulation_scenario_id","scenario_type","comparison_target","evaluated_cell_count","scenario_win_count","scenario_loss_count","scenario_tie_or_inconclusive_count","average_mean_return_delta","average_median_return_delta","average_hit_rate_delta","comparison_status","comparison_reason","diagnostic_only","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
ATTR_FIELDS = ["simulation_scenario_id","scenario_type","factor_family","simulated_weight","current_v20_107_weight","weight_change_direction","average_component_contribution_in_top10","average_component_contribution_in_top20","average_component_contribution_in_top50","average_component_contribution_in_top100","average_forward_return_when_component_high","average_forward_return_when_component_low","factor_effectiveness_status","factor_effectiveness_reason","repair_signal_confirmed","diagnostic_only","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
SELECTION_FIELDS = ["selection_check_id","scenario_count","valid_scenario_count","strict_equity_candidate_count","forward_window_count","topn_group_count","evidence_coverage_status","best_scenario_id","best_scenario_type","best_scenario_cells_beating_both_count","best_scenario_average_delta_vs_current_shadow","best_scenario_average_delta_vs_baseline","scenario_selection_status","scenario_selection_reason","accepted_weight_created","new_weights_created","new_rerank_created","performance_effectiveness_claim_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","research_only","shadow_only","simulation_only","official_promotion_allowed","is_official_weight","weight_mutated"]
GATE_FIELDS = ["gate_check_id","simulated_effectiveness_comparison_created","scenario_count","valid_scenario_count","best_scenario_selected_for_next_validation","best_scenario_id","best_scenario_type","v20_109_r5_candidate_scenario_validation_allowed","v20_110_acceptance_gate_allowed","recommended_next_stage","blocking_reason","accepted_weight_created","new_weights_created","new_rerank_created","performance_effectiveness_claim_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","research_only","shadow_only","simulation_only","official_promotion_allowed","is_official_weight","weight_mutated"]


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


def downside(vals: list[Decimal]) -> Decimal | None:
    neg = [v for v in vals if v < 0]
    return mean(neg) if neg else Decimal("0")


def safety(sim: bool = True) -> dict[str, str]:
    row = {
        "research_only": "TRUE",
        "shadow_only": "TRUE",
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
    }
    if sim:
        row["simulation_only"] = "TRUE"
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


def top_set(rows: list[dict[str, str]], rank_col: str, topn: int) -> set[str]:
    result = set()
    for row in rows:
        rank = dec(row.get(rank_col, ""))
        if rank is not None and int(rank) <= topn:
            result.add(row["ticker"])
    return result


def outcome_values(tickers: set[str], window: str, outcomes: dict[tuple[str, str], list[Decimal]]) -> list[Decimal]:
    return [v for ticker in tickers for v in outcomes.get((ticker, window), [])]


def count_with_outcome(tickers: set[str], window: str, outcomes: dict[tuple[str, str], list[Decimal]]) -> int:
    return sum(1 for ticker in tickers if (ticker, window) in outcomes)


def stats(vals: list[Decimal]) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
    return mean(vals), med(vals), hit(vals), downside(vals)


def delta(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return a - b if a is not None and b is not None else None


def avg(vals: list[Decimal | None]) -> Decimal | None:
    real = [v for v in vals if v is not None]
    return mean(real)


def main() -> int:
    r3_rerank, _, r3_status = read_csv(R3_RERANK)
    r3_validation, _, validation_status = read_csv(R3_VALIDATION)
    scenarios, _, scenario_status = read_csv(R2_SCENARIOS)
    r12_rerank, _, r12_status = read_csv(R12_RERANK)
    component, _, component_status = read_csv(R3_COMPONENT)
    forward, _, forward_status = read_csv(V104_FORWARD)

    valid_scenarios = [s for s in scenarios if s.get("weight_sum_valid") == "TRUE"]
    scenario_ids = [s["simulation_scenario_id"] for s in valid_scenarios]
    scenario_by_id = {s["simulation_scenario_id"]: s for s in valid_scenarios}
    strict_tickers = {r["ticker"] for r in r12_rerank}
    required_ok = (
        r3_status == "OK"
        and validation_status == "OK"
        and scenario_status == "OK"
        and r12_status == "OK"
        and forward_status == "OK"
        and len(valid_scenarios) == 8
        and len(strict_tickers) == 297
        and len(r3_rerank) == len(valid_scenarios) * 297
    )

    outcomes: dict[tuple[str, str], list[Decimal]] = {}
    for row in forward:
        ticker = row.get("ticker", "")
        window = row.get("forward_window", "")
        value = dec(row.get("forward_return", ""))
        if ticker in strict_tickers and window in WINDOWS and row.get("outcome_available") == "TRUE" and value is not None:
            outcomes.setdefault((ticker, window), []).append(value)

    matrix_rows: list[dict[str, str]] = []
    summary_rows: list[dict[str, str]] = []
    audit_rows: list[dict[str, str]] = []
    attr_rows: list[dict[str, str]] = []

    baseline_sets = {(window, topn): top_set(r12_rerank, "baseline_rank", topn) for window in WINDOWS for topn in TOPNS}
    current_sets = {(window, topn): top_set(r12_rerank, "strict_equity_shadow_rank", topn) for window in WINDOWS for topn in TOPNS}
    r3_by_scenario = {sid: [r for r in r3_rerank if r.get("simulation_scenario_id") == sid] for sid in scenario_ids}

    scenario_rollups: dict[str, dict[str, object]] = {}
    for sid in scenario_ids:
        scenario = scenario_by_id[sid]
        rows = r3_by_scenario[sid]
        beating_baseline = beating_shadow = beating_both = losing_both = 0
        short_success = medium_success = long_success = 0
        top_success = {10: 0, 20: 0, 50: 0, 100: 0}
        mean_base_deltas: list[Decimal | None] = []
        mean_shadow_deltas: list[Decimal | None] = []
        median_base_deltas: list[Decimal | None] = []
        median_shadow_deltas: list[Decimal | None] = []
        hit_base_deltas: list[Decimal | None] = []
        hit_shadow_deltas: list[Decimal | None] = []
        coverage_statuses: set[str] = set()

        for window in WINDOWS:
            for topn in TOPNS:
                scenario_set = top_set(rows, "simulated_shadow_rank", topn)
                baseline_set = baseline_sets[(window, topn)]
                current_set = current_sets[(window, topn)]
                s_vals = outcome_values(scenario_set, window, outcomes)
                b_vals = outcome_values(baseline_set, window, outcomes)
                c_vals = outcome_values(current_set, window, outcomes)
                s_mean, s_med, s_hit, s_down = stats(s_vals)
                b_mean, b_med, b_hit, b_down = stats(b_vals)
                c_mean, c_med, c_hit, c_down = stats(c_vals)
                s_b_mean, s_c_mean = delta(s_mean, b_mean), delta(s_mean, c_mean)
                s_b_med, s_c_med = delta(s_med, b_med), delta(s_med, c_med)
                s_b_hit, s_c_hit = delta(s_hit, b_hit), delta(s_hit, c_hit)
                s_b_risk = delta(s_b_mean, delta(s_down, b_down))
                s_c_risk = delta(s_c_mean, delta(s_down, c_down))
                available = len(s_vals) + len(b_vals) + len(c_vals)
                missing = (
                    len(scenario_set) + len(baseline_set) + len(current_set)
                    - count_with_outcome(scenario_set, window, outcomes)
                    - count_with_outcome(baseline_set, window, outcomes)
                    - count_with_outcome(current_set, window, outcomes)
                )
                coverage = "FULL_FORWARD_OUTCOME_COVERAGE" if missing == 0 else "PARTIAL_FORWARD_OUTCOME_COVERAGE"
                coverage_statuses.add(coverage)
                beats_base = s_b_mean is not None and s_b_mean > 0
                beats_shadow = s_c_mean is not None and s_c_mean > 0
                loses_base = s_b_mean is not None and s_b_mean < 0
                loses_shadow = s_c_mean is not None and s_c_mean < 0
                beating_baseline += int(beats_base)
                beating_shadow += int(beats_shadow)
                beating_both += int(beats_base and beats_shadow)
                losing_both += int(loses_base and loses_shadow)
                if beats_base and beats_shadow:
                    if window in {"5D", "10D"}:
                        short_success += 1
                    elif window == "20D":
                        medium_success += 1
                    else:
                        long_success += 1
                    top_success[topn] += 1
                    cell_status = "SCENARIO_BEATS_BASELINE_AND_CURRENT_SHADOW"
                elif beats_shadow:
                    cell_status = "SCENARIO_BEATS_CURRENT_SHADOW_ONLY"
                elif beats_base:
                    cell_status = "SCENARIO_BEATS_BASELINE_ONLY"
                elif s_b_mean is None or s_c_mean is None:
                    cell_status = "INSUFFICIENT_FORWARD_OUTCOME_EVIDENCE"
                else:
                    cell_status = "SCENARIO_DOES_NOT_IMPROVE"
                mean_base_deltas.append(s_b_mean)
                mean_shadow_deltas.append(s_c_mean)
                median_base_deltas.append(s_b_med)
                median_shadow_deltas.append(s_c_med)
                hit_base_deltas.append(s_b_hit)
                hit_shadow_deltas.append(s_c_hit)
                matrix_rows.append({
                    "simulation_scenario_id": sid,
                    "scenario_type": scenario["scenario_type"],
                    "forward_window": window,
                    "top_n": str(topn),
                    "scenario_top_n_count": str(len(scenario_set)),
                    "baseline_top_n_count": str(len(baseline_set)),
                    "current_shadow_top_n_count": str(len(current_set)),
                    "overlap_with_baseline_count": str(len(scenario_set & baseline_set)),
                    "overlap_with_current_shadow_count": str(len(scenario_set & current_set)),
                    "scenario_mean_forward_return": fmt(s_mean),
                    "baseline_mean_forward_return": fmt(b_mean),
                    "current_shadow_mean_forward_return": fmt(c_mean),
                    "scenario_minus_baseline_mean_return": fmt(s_b_mean),
                    "scenario_minus_current_shadow_mean_return": fmt(s_c_mean),
                    "scenario_median_forward_return": fmt(s_med),
                    "baseline_median_forward_return": fmt(b_med),
                    "current_shadow_median_forward_return": fmt(c_med),
                    "scenario_minus_baseline_median_return": fmt(s_b_med),
                    "scenario_minus_current_shadow_median_return": fmt(s_c_med),
                    "scenario_hit_rate": fmt(s_hit),
                    "baseline_hit_rate": fmt(b_hit),
                    "current_shadow_hit_rate": fmt(c_hit),
                    "scenario_minus_baseline_hit_rate": fmt(s_b_hit),
                    "scenario_minus_current_shadow_hit_rate": fmt(s_c_hit),
                    "scenario_downside_proxy": fmt(s_down),
                    "baseline_downside_proxy": fmt(b_down),
                    "current_shadow_downside_proxy": fmt(c_down),
                    "risk_adjusted_delta_vs_baseline": fmt(s_b_risk),
                    "risk_adjusted_delta_vs_current_shadow": fmt(s_c_risk),
                    "available_forward_outcome_count": str(available),
                    "missing_forward_outcome_count": str(max(0, missing)),
                    "coverage_status": coverage,
                    "cell_effectiveness_status": cell_status,
                    "cell_effectiveness_reason": "Measured only from available V20.104 forward outcomes; no imputation or recommendation.",
                    **safety(),
                })

        evidence_status = "PARTIAL_FORWARD_OUTCOME_COVERAGE" if "PARTIAL_FORWARD_OUTCOME_COVERAGE" in coverage_statuses else "FULL_FORWARD_OUTCOME_COVERAGE"
        avg_vs_base = avg(mean_base_deltas)
        avg_vs_shadow = avg(mean_shadow_deltas)
        candidate = beating_both > 0 and avg_vs_shadow is not None and avg_vs_shadow > 0
        status = "RESEARCH_ONLY_CANDIDATE_FOR_NEXT_SIMULATION_VALIDATION" if candidate else "NO_CLEAR_SIMULATED_IMPROVEMENT"
        scenario_rollups[sid] = {
            "cells_beating_both": beating_both,
            "avg_vs_shadow": avg_vs_shadow,
            "avg_vs_base": avg_vs_base,
            "candidate": candidate,
        }
        summary_rows.append({
            "simulation_scenario_id": sid,
            "scenario_type": scenario["scenario_type"],
            "scenario_priority": scenario["scenario_priority"],
            "strict_equity_candidate_count": "297",
            "evaluated_cell_count": str(len(WINDOWS) * len(TOPNS)),
            "cells_beating_baseline_count": str(beating_baseline),
            "cells_beating_current_shadow_count": str(beating_shadow),
            "cells_beating_both_count": str(beating_both),
            "cells_losing_to_both_count": str(losing_both),
            "average_scenario_minus_baseline_mean_return": fmt(avg_vs_base),
            "average_scenario_minus_current_shadow_mean_return": fmt(avg_vs_shadow),
            "average_scenario_minus_baseline_median_return": fmt(avg(median_base_deltas)),
            "average_scenario_minus_current_shadow_median_return": fmt(avg(median_shadow_deltas)),
            "average_scenario_minus_baseline_hit_rate": fmt(avg(hit_base_deltas)),
            "average_scenario_minus_current_shadow_hit_rate": fmt(avg(hit_shadow_deltas)),
            "short_window_success_count": str(short_success),
            "medium_window_success_count": str(medium_success),
            "long_window_success_count": str(long_success),
            "top10_success_count": str(top_success[10]),
            "top20_success_count": str(top_success[20]),
            "top50_success_count": str(top_success[50]),
            "top100_success_count": str(top_success[100]),
            "evidence_coverage_status": evidence_status,
            "scenario_effectiveness_status": status,
            "scenario_effectiveness_reason": "Diagnostic simulation comparison only; simulated weights are not accepted or official.",
            "research_only_candidate_for_next_validation": tf(candidate),
            "accepted_weight_created": "FALSE",
            "new_rerank_created": "FALSE",
            "performance_effectiveness_claim_created": "FALSE",
            "official_ranking_created": "FALSE",
            **safety(),
            "is_official_weight": "FALSE",
            "weight_mutated": "FALSE",
        })

        for target, deltas_mean, deltas_med, deltas_hit in [
            ("BASELINE_RANKING", mean_base_deltas, median_base_deltas, hit_base_deltas),
            ("CURRENT_V20_107_SHADOW_RERANK", mean_shadow_deltas, median_shadow_deltas, hit_shadow_deltas),
        ]:
            real_mean = [d for d in deltas_mean if d is not None]
            wins = sum(1 for d in real_mean if d > 0)
            losses = sum(1 for d in real_mean if d < 0)
            ties = len(deltas_mean) - wins - losses
            audit_rows.append({
                "simulation_scenario_id": sid,
                "scenario_type": scenario["scenario_type"],
                "comparison_target": target,
                "evaluated_cell_count": str(len(deltas_mean)),
                "scenario_win_count": str(wins),
                "scenario_loss_count": str(losses),
                "scenario_tie_or_inconclusive_count": str(ties),
                "average_mean_return_delta": fmt(avg(deltas_mean)),
                "average_median_return_delta": fmt(avg(deltas_med)),
                "average_hit_rate_delta": fmt(avg(deltas_hit)),
                "comparison_status": "SCENARIO_DIAGNOSTIC_OUTPERFORMANCE" if wins > losses else "SCENARIO_DIAGNOSTIC_UNDERPERFORMANCE_OR_MIXED",
                "comparison_reason": "Comparison is diagnostic only and does not create accepted weights.",
                "diagnostic_only": "TRUE",
                **safety(),
            })

    comp_by = {}
    for row in component:
        comp_by.setdefault((row["simulation_scenario_id"], row["factor_family"]), []).append(row)
    for sid in scenario_ids:
        scenario = scenario_by_id[sid]
        rows = r3_by_scenario[sid]
        ranks_by_top = {topn: {r["ticker"] for r in rows if int(r["simulated_shadow_rank"]) <= topn} for topn in TOPNS}
        for family in FAMILIES:
            comp_rows = comp_by.get((sid, family), [])
            comp_by_ticker = {r["ticker"]: dec(r.get("simulated_weighted_component_contribution", "")) for r in comp_rows}
            current_weight = comp_rows[0].get("current_v20_107_weight", "") if comp_rows else ""
            simulated_weight = comp_rows[0].get("simulated_weight", "") if comp_rows else ""
            sw = dec(simulated_weight)
            cw = dec(current_weight)
            if sw is None or cw is None:
                direction = "UNKNOWN"
            elif sw > cw:
                direction = "INCREASED"
            elif sw < cw:
                direction = "DECREASED"
            else:
                direction = "UNCHANGED"
            top_avgs = {}
            for topn in TOPNS:
                vals = [v for t, v in comp_by_ticker.items() if t in ranks_by_top[topn] and v is not None]
                top_avgs[topn] = mean(vals)
            ordered = sorted([(t, v) for t, v in comp_by_ticker.items() if v is not None], key=lambda item: item[1])
            low = {t for t, _ in ordered[: max(1, len(ordered) // 5)]}
            high = {t for t, _ in ordered[-max(1, len(ordered) // 5):]}
            high_vals = [v for t in high for w in WINDOWS for v in outcomes.get((t, w), [])]
            low_vals = [v for t in low for w in WINDOWS for v in outcomes.get((t, w), [])]
            high_return = mean(high_vals)
            low_return = mean(low_vals)
            confirmed = high_return is not None and low_return is not None and high_return > low_return
            attr_rows.append({
                "simulation_scenario_id": sid,
                "scenario_type": scenario["scenario_type"],
                "factor_family": family,
                "simulated_weight": simulated_weight,
                "current_v20_107_weight": current_weight,
                "weight_change_direction": direction,
                "average_component_contribution_in_top10": fmt(top_avgs[10]),
                "average_component_contribution_in_top20": fmt(top_avgs[20]),
                "average_component_contribution_in_top50": fmt(top_avgs[50]),
                "average_component_contribution_in_top100": fmt(top_avgs[100]),
                "average_forward_return_when_component_high": fmt(high_return),
                "average_forward_return_when_component_low": fmt(low_return),
                "factor_effectiveness_status": "COMPONENT_SIGNAL_SUPPORTIVE" if confirmed else "COMPONENT_SIGNAL_NOT_CONFIRMED_OR_MIXED",
                "factor_effectiveness_reason": "High/low component return spread is diagnostic only.",
                "repair_signal_confirmed": tf(confirmed),
                "diagnostic_only": "TRUE",
                **safety(),
            })

    def best_key(sid: str) -> tuple[int, Decimal, Decimal]:
        roll = scenario_rollups[sid]
        return (
            int(roll["cells_beating_both"]),
            roll["avg_vs_shadow"] if isinstance(roll["avg_vs_shadow"], Decimal) else Decimal("-999"),
            roll["avg_vs_base"] if isinstance(roll["avg_vs_base"], Decimal) else Decimal("-999"),
        )

    best_sid = max(scenario_ids, key=best_key) if scenario_ids else ""
    best = scenario_by_id.get(best_sid, {})
    best_roll = scenario_rollups.get(best_sid, {})
    best_selected = bool(best_sid) and int(best_roll.get("cells_beating_both", 0)) > 0
    any_partial = any(row["coverage_status"] == "PARTIAL_FORWARD_OUTCOME_COVERAGE" for row in matrix_rows)
    comparison_created = required_ok and bool(matrix_rows)
    wrapper = BLOCKED_STATUS
    if comparison_created:
        if best_selected:
            wrapper = PARTIAL_STATUS if any_partial else PASS_STATUS
        else:
            wrapper = WARN_STATUS

    selection_rows = [{
        "selection_check_id": "V20_109_R4_EVIDENCE_QUALITY_AND_SELECTION_001",
        "scenario_count": str(len(scenario_ids)),
        "valid_scenario_count": str(len(scenario_ids)),
        "strict_equity_candidate_count": "297",
        "forward_window_count": str(len(WINDOWS)),
        "topn_group_count": str(len(TOPNS)),
        "evidence_coverage_status": "PARTIAL_FORWARD_OUTCOME_COVERAGE" if any_partial else "FULL_FORWARD_OUTCOME_COVERAGE",
        "best_scenario_id": best_sid,
        "best_scenario_type": best.get("scenario_type", ""),
        "best_scenario_cells_beating_both_count": str(best_roll.get("cells_beating_both", 0)),
        "best_scenario_average_delta_vs_current_shadow": fmt(best_roll.get("avg_vs_shadow") if isinstance(best_roll.get("avg_vs_shadow"), Decimal) else None),
        "best_scenario_average_delta_vs_baseline": fmt(best_roll.get("avg_vs_base") if isinstance(best_roll.get("avg_vs_base"), Decimal) else None),
        "scenario_selection_status": "RESEARCH_ONLY_CANDIDATE_FOR_NEXT_VALIDATION" if best_selected else "NO_ACCEPTED_SIMULATION_CANDIDATE",
        "scenario_selection_reason": "Best scenario selected only for later validation; no weights accepted.",
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
        "gate_check_id": "V20_109_R4_NEXT_STAGE_GATE_001",
        "simulated_effectiveness_comparison_created": tf(comparison_created),
        "scenario_count": str(len(scenario_ids)),
        "valid_scenario_count": str(len(scenario_ids)),
        "best_scenario_selected_for_next_validation": tf(best_selected),
        "best_scenario_id": best_sid if best_selected else "",
        "best_scenario_type": best.get("scenario_type", "") if best_selected else "",
        "v20_109_r5_candidate_scenario_validation_allowed": tf(best_selected),
        "v20_110_acceptance_gate_allowed": "FALSE",
        "recommended_next_stage": "V20.109-R5_RESEARCH_ONLY_CANDIDATE_SCENARIO_VALIDATION" if best_selected else "V20.109-R2_WEIGHT_REPAIR_SIMULATION_REVIEW",
        "blocking_reason": "" if comparison_created else "MISSING_SIMULATED_RERANK_OR_FORWARD_OUTCOME_INPUTS",
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
    write_csv(OUT_MATRIX, MATRIX_FIELDS, matrix_rows)
    write_csv(OUT_AUDIT, AUDIT_FIELDS, audit_rows)
    write_csv(OUT_ATTR, ATTR_FIELDS, attr_rows)
    write_csv(OUT_SELECTION, SELECTION_FIELDS, selection_rows)
    write_csv(OUT_GATE, GATE_FIELDS, gate_rows)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        "\n".join([
            "# V20.109-R4 Simulated Weight Effectiveness Comparison Report",
            "",
            "## Current Result",
            f"- wrapper_status: {wrapper}",
            f"- scenario_count: {len(scenario_ids)}",
            "- strict_equity_candidate_count: 297",
            f"- comparison_cell_count: {len(matrix_rows)}",
            f"- best_scenario_id: {best_sid if best_selected else ''}",
            f"- best_scenario_selected_for_next_validation: {tf(best_selected)}",
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
    print(f"SCENARIO_COUNT={len(scenario_ids)}")
    print("STRICT_EQUITY_CANDIDATE_COUNT=297")
    print(f"COMPARISON_CELL_COUNT={len(matrix_rows)}")
    print("FORWARD_WINDOWS=5D,10D,20D,60D,120D")
    print("TOPN_GROUPS=10,20,50,100")
    print(f"BEST_SCENARIO_SELECTED_FOR_NEXT_VALIDATION={tf(best_selected)}")
    print("ACCEPTED_WEIGHT_CREATED=FALSE")
    print("NEW_WEIGHTS_CREATED=FALSE")
    print("NEW_RERANK_CREATED=FALSE")
    print("V20_107_WEIGHT_MUTATED=FALSE")
    print("V20_98B_R5_WEIGHT_MUTATED=FALSE")
    print("OFFICIAL_WEIGHT_CREATED=FALSE")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED=FALSE")
    print("V20_110_ACCEPTANCE_GATE_ALLOWED=FALSE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("IS_OFFICIAL_WEIGHT=FALSE")
    print(f"OUTPUT_SUMMARY={OUT_SUMMARY.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_MATRIX={OUT_MATRIX.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_AUDIT={OUT_AUDIT.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_ATTRIBUTION={OUT_ATTR.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_SELECTION={OUT_SELECTION.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_GATE={OUT_GATE.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_REPORT={REPORT.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
