#!/usr/bin/env python
"""V20.109-R9 second-round effectiveness comparison.

Research-only comparison of R8 second-round simulated reranks. This stage does
not accept weights, mutate weights, create official ranks, or make performance
claims.
"""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R8_RERANK = CONSOLIDATION / "V20_109_R8_SECOND_ROUND_SIMULATED_WEIGHT_STRICT_EQUITY_RERANK.csv"
R8_DELTA = CONSOLIDATION / "V20_109_R8_SECOND_ROUND_SIMULATED_RANK_DELTA_AUDIT.csv"
R8_COMPONENT = CONSOLIDATION / "V20_109_R8_SECOND_ROUND_SIMULATED_SCORE_COMPONENT_AUDIT.csv"
R8_VALIDATION = CONSOLIDATION / "V20_109_R8_SECOND_ROUND_SIMULATED_RERANK_VALIDATION.csv"
R8_GATE = CONSOLIDATION / "V20_109_R8_NEXT_STAGE_GATE.csv"
R6_PRIOR = CONSOLIDATION / "V20_109_R6_PRIOR_FAILURE_AREA_REPAIR_AUDIT.csv"
R6_SUMMARY = CONSOLIDATION / "V20_109_R6_SIMULATED_SCENARIO_STRESS_TEST_SUMMARY.csv"
R7_TARGET = CONSOLIDATION / "V20_109_R7_PRIOR_FAILURE_AREA_TARGETING_AUDIT.csv"
R12_RERANK = CONSOLIDATION / "V20_108_R12_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK.csv"
V104_FORWARD = CONSOLIDATION / "V20_104_RANDOM_ASOF_FORWARD_OUTCOME_MATRIX.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"
AUTHORITATIVE_CURRENT = CONSOLIDATION / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"

OUT_COMPARE = CONSOLIDATION / "V20_109_R9_SECOND_ROUND_EFFECTIVENESS_COMPARISON.csv"
OUT_PRIOR = CONSOLIDATION / "V20_109_R9_PRIOR_FAILURE_REPAIR_COMPARISON.csv"
OUT_STABILITY = CONSOLIDATION / "V20_109_R9_TOP20_TOP40_STABILITY_AUDIT.csv"
OUT_BASELINE = CONSOLIDATION / "V20_109_R9_BASELINE_VS_SECOND_ROUND_SCENARIO_AUDIT.csv"
OUT_SELECTION = CONSOLIDATION / "V20_109_R9_SCENARIO_SELECTION_RECOMMENDATION.csv"
OUT_GATE = CONSOLIDATION / "V20_109_R9_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_109_R9_SECOND_ROUND_EFFECTIVENESS_COMPARISON_REPORT.md"

PASS_STATUS = "PASS_V20_109_R9_SECOND_ROUND_EFFECTIVENESS_COMPARISON_ACCEPTANCE_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V20_109_R9_EFFECTIVENESS_COMPARISON_WITH_LIMITED_EVIDENCE"
BLOCKED_MISSING_STATUS = "BLOCKED_V20_109_R9_MISSING_REQUIRED_R8_INPUTS"
BLOCKED_PRIOR_STATUS = "BLOCKED_V20_109_R9_PRIOR_FAILURE_REPAIR_NOT_VALIDATED"
WARN_STATUS = "WARN_V20_109_R9_SCENARIO_EFFECTIVE_BUT_FRAGILE"

WINDOWS = ["5D", "10D", "20D", "60D", "120D"]
TOPNS = [10, 20, 40, 50, 100]

COMPARE_FIELDS = ["simulation_scenario_id","parent_scenario_id","scenario_type","forward_window","top_n","scenario_top_n_count","baseline_top_n_count","current_shadow_top_n_count","overlap_with_baseline_count","overlap_with_current_shadow_count","turnover_vs_baseline_count","turnover_vs_current_shadow_count","scenario_mean_forward_return","baseline_mean_forward_return","current_shadow_mean_forward_return","scenario_minus_baseline_mean_return","scenario_minus_current_shadow_mean_return","scenario_median_forward_return","baseline_median_forward_return","current_shadow_median_forward_return","scenario_minus_baseline_median_return","scenario_minus_current_shadow_median_return","scenario_hit_rate","baseline_hit_rate","current_shadow_hit_rate","scenario_minus_baseline_hit_rate","scenario_minus_current_shadow_hit_rate","available_forward_outcome_count","missing_forward_outcome_count","coverage_status","cell_effectiveness_status","broad_or_local_status","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
PRIOR_FIELDS = ["simulation_scenario_id","scenario_type","prior_failure_area","prior_failure_forward_window","prior_failure_top_n","baseline_mean_forward_return","current_shadow_mean_forward_return","scenario_mean_forward_return","scenario_minus_baseline_mean_return","scenario_minus_current_shadow_mean_return","baseline_hit_rate","current_shadow_hit_rate","scenario_hit_rate","scenario_minus_baseline_hit_rate","scenario_minus_current_shadow_hit_rate","prior_failure_repair_passed","prior_failure_repair_status","prior_failure_repair_reason","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
STABILITY_FIELDS = ["simulation_scenario_id","scenario_type","top_n","scenario_top_n_count","baseline_top_n_count","current_shadow_top_n_count","overlap_with_baseline_count","overlap_with_current_shadow_count","turnover_vs_baseline_count","turnover_vs_current_shadow_count","turnover_vs_baseline_ratio","turnover_vs_current_shadow_ratio","churn_acceptable","stability_status","stability_reason","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
BASELINE_FIELDS = ["simulation_scenario_id","scenario_type","evaluated_cell_count","cells_beating_baseline_count","cells_beating_current_shadow_count","cells_beating_both_count","cells_losing_to_both_count","average_delta_vs_baseline","average_delta_vs_current_shadow","average_hit_rate_delta_vs_baseline","average_hit_rate_delta_vs_current_shadow","improvement_breadth_status","scenario_effectiveness_status","scenario_effectiveness_reason","accepted_weight_created","official_weight_created","new_weights_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","performance_effectiveness_claim_created","authoritative_ranking_overwritten","research_only","shadow_only","simulation_only","official_promotion_allowed","is_official_weight","weight_mutated"]
SELECTION_FIELDS = ["selection_check_id","scenario_count","valid_scenario_count","best_scenario_id","best_scenario_type","best_scenario_cells_beating_both_count","best_scenario_average_delta_vs_baseline","best_scenario_average_delta_vs_current_shadow","best_scenario_prior_failure_repair_passed","best_scenario_top20_churn_acceptable","best_scenario_top40_churn_acceptable","evidence_coverage_status","scenario_selection_status","scenario_selection_reason","v20_110_acceptance_gate_allowed","accepted_weight_created","official_weight_created","new_weights_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","performance_effectiveness_claim_created","authoritative_ranking_overwritten","research_only","shadow_only","simulation_only","official_promotion_allowed","is_official_weight","weight_mutated"]
GATE_FIELDS = ["gate_check_id","second_round_effectiveness_comparison_created","scenario_count","valid_scenario_count","prior_failure_repair_validated","top20_top40_churn_acceptable","duplicate_rank_count","missing_rank_count","evidence_limited_or_fragile","v20_110_acceptance_gate_allowed","next_recommended_action","blocking_reason","accepted_weight_created","official_weight_created","new_weights_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","performance_effectiveness_claim_created","authoritative_ranking_overwritten","research_only","shadow_only","simulation_only","official_promotion_allowed","is_official_weight","weight_mutated"]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def dec(value: str) -> Decimal | None:
    try:
        return Decimal(clean(value))
    except (InvalidOperation, ValueError):
        return None


def fmt(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{float(value):.10f}"


def mean(values: list[Decimal]) -> Decimal | None:
    return sum(values, Decimal("0")) / Decimal(len(values)) if values else None


def med(values: list[Decimal]) -> Decimal | None:
    return Decimal(str(median(values))) if values else None


def hit_rate(values: list[Decimal]) -> Decimal | None:
    return Decimal(sum(1 for value in values if value > 0)) / Decimal(len(values)) if values else None


def avg(values: list[Decimal | None]) -> Decimal | None:
    real = [value for value in values if value is not None]
    return mean(real)


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
        return [{key: clean(value) for key, value in row.items()} for row in reader], list(reader.fieldnames or []), "OK"


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def top_set(rows: list[dict[str, str]], rank_field: str, top_n: int) -> set[str]:
    result = set()
    for row in rows:
        rank = dec(row.get(rank_field, ""))
        if rank is not None and int(rank) <= top_n:
            result.add(row["ticker"])
    return result


def outcome_values(tickers: set[str], window: str, outcomes: dict[tuple[str, str], list[Decimal]]) -> list[Decimal]:
    return [value for ticker in tickers for value in outcomes.get((ticker, window), [])]


def with_outcome_count(tickers: set[str], window: str, outcomes: dict[tuple[str, str], list[Decimal]]) -> int:
    return sum(1 for ticker in tickers if (ticker, window) in outcomes)


def stats(values: list[Decimal]) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    return mean(values), med(values), hit_rate(values)


def delta(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    return left - right if left is not None and right is not None else None


def main() -> int:
    rerank, _, rerank_status = read_csv(R8_RERANK)
    validation, _, validation_status = read_csv(R8_VALIDATION)
    gate, _, gate_status = read_csv(R8_GATE)
    current, _, current_status = read_csv(R12_RERANK)
    forward, _, forward_status = read_csv(V104_FORWARD)
    prior, _, prior_status = read_csv(R6_PRIOR)
    read_csv(AUTHORITATIVE_CURRENT)  # optional, only proves we do not overwrite it

    v = validation[0] if validation else {}
    valid_inputs = (
        rerank_status == "OK"
        and validation_status == "OK"
        and gate_status == "OK"
        and current_status == "OK"
        and forward_status == "OK"
        and v.get("scenario_count") == "8"
        and v.get("strict_equity_candidate_count") == "297"
        and v.get("duplicate_rank_count") == "0"
        and v.get("missing_rank_count") == "0"
        and gate
        and gate[0].get("v20_109_r9_second_round_effectiveness_comparison_allowed") == "TRUE"
    )

    scenario_ids = sorted({row["simulation_scenario_id"] for row in rerank})
    scenario_meta = {sid: next(row for row in rerank if row["simulation_scenario_id"] == sid) for sid in scenario_ids}
    current_by_ticker = {row["ticker"]: row for row in current}
    strict_tickers = {row["ticker"] for row in current}
    outcomes: dict[tuple[str, str], list[Decimal]] = {}
    for row in forward:
        ticker = row.get("ticker", "")
        window = row.get("forward_window", "")
        value = dec(row.get("forward_return", ""))
        if ticker in strict_tickers and window in WINDOWS and row.get("outcome_available") == "TRUE" and value is not None:
            outcomes.setdefault((ticker, window), []).append(value)

    comparison_rows: list[dict[str, str]] = []
    baseline_rows: list[dict[str, str]] = []
    prior_rows: list[dict[str, str]] = []
    stability_rows: list[dict[str, str]] = []
    rollups: dict[str, dict[str, object]] = {}
    any_partial = False
    prior_area = prior[0].get("prior_failure_area", "120D_TOP20") if prior else "120D_TOP20"
    prior_window = prior[0].get("prior_failure_forward_window", "120D") if prior else "120D"
    prior_topn = int(prior[0].get("prior_failure_top_n", "20") or "20") if prior else 20

    for sid in scenario_ids:
        rows = [row for row in rerank if row["simulation_scenario_id"] == sid]
        meta = scenario_meta[sid]
        mean_delta_base: list[Decimal | None] = []
        mean_delta_current: list[Decimal | None] = []
        hit_delta_base: list[Decimal | None] = []
        hit_delta_current: list[Decimal | None] = []
        beat_base = beat_current = beat_both = lose_both = 0
        prior_pass = False
        top_churn: dict[int, bool] = {}

        for window in WINDOWS:
            for top_n in TOPNS:
                scenario_set = top_set(rows, "second_round_simulated_shadow_rank", top_n)
                baseline_set = top_set(current, "baseline_rank", top_n)
                current_set = top_set(current, "strict_equity_shadow_rank", top_n)
                s_vals = outcome_values(scenario_set, window, outcomes)
                b_vals = outcome_values(baseline_set, window, outcomes)
                c_vals = outcome_values(current_set, window, outcomes)
                s_mean, s_med, s_hit = stats(s_vals)
                b_mean, b_med, b_hit = stats(b_vals)
                c_mean, c_med, c_hit = stats(c_vals)
                d_base = delta(s_mean, b_mean)
                d_current = delta(s_mean, c_mean)
                d_med_base = delta(s_med, b_med)
                d_med_current = delta(s_med, c_med)
                d_hit_base = delta(s_hit, b_hit)
                d_hit_current = delta(s_hit, c_hit)
                scenario_available = with_outcome_count(scenario_set, window, outcomes)
                baseline_available = with_outcome_count(baseline_set, window, outcomes)
                current_available = with_outcome_count(current_set, window, outcomes)
                missing = (len(scenario_set) + len(baseline_set) + len(current_set)) - scenario_available - baseline_available - current_available
                coverage = "PARTIAL_FORWARD_OUTCOME_COVERAGE" if missing > 0 else "FULL_FORWARD_OUTCOME_COVERAGE"
                any_partial = any_partial or missing > 0
                beats_base_cell = d_base is not None and d_base > 0
                beats_current_cell = d_current is not None and d_current > 0
                beat_base += int(beats_base_cell)
                beat_current += int(beats_current_cell)
                beat_both += int(beats_base_cell and beats_current_cell)
                lose_both += int(d_base is not None and d_current is not None and d_base < 0 and d_current < 0)
                mean_delta_base.append(d_base)
                mean_delta_current.append(d_current)
                hit_delta_base.append(d_hit_base)
                hit_delta_current.append(d_hit_current)
                if beats_base_cell and beats_current_cell:
                    cell_status = "SCENARIO_BEATS_BASELINE_AND_CURRENT"
                elif beats_current_cell:
                    cell_status = "SCENARIO_BEATS_CURRENT_ONLY"
                elif beats_base_cell:
                    cell_status = "SCENARIO_BEATS_BASELINE_ONLY"
                elif d_base is None or d_current is None:
                    cell_status = "INSUFFICIENT_FORWARD_OUTCOME_EVIDENCE"
                else:
                    cell_status = "SCENARIO_DOES_NOT_IMPROVE"
                comparison_rows.append({
                    "simulation_scenario_id": sid,
                    "parent_scenario_id": meta["parent_scenario_id"],
                    "scenario_type": meta["scenario_type"],
                    "forward_window": window,
                    "top_n": str(top_n),
                    "scenario_top_n_count": str(len(scenario_set)),
                    "baseline_top_n_count": str(len(baseline_set)),
                    "current_shadow_top_n_count": str(len(current_set)),
                    "overlap_with_baseline_count": str(len(scenario_set & baseline_set)),
                    "overlap_with_current_shadow_count": str(len(scenario_set & current_set)),
                    "turnover_vs_baseline_count": str(len(scenario_set - baseline_set)),
                    "turnover_vs_current_shadow_count": str(len(scenario_set - current_set)),
                    "scenario_mean_forward_return": fmt(s_mean),
                    "baseline_mean_forward_return": fmt(b_mean),
                    "current_shadow_mean_forward_return": fmt(c_mean),
                    "scenario_minus_baseline_mean_return": fmt(d_base),
                    "scenario_minus_current_shadow_mean_return": fmt(d_current),
                    "scenario_median_forward_return": fmt(s_med),
                    "baseline_median_forward_return": fmt(b_med),
                    "current_shadow_median_forward_return": fmt(c_med),
                    "scenario_minus_baseline_median_return": fmt(d_med_base),
                    "scenario_minus_current_shadow_median_return": fmt(d_med_current),
                    "scenario_hit_rate": fmt(s_hit),
                    "baseline_hit_rate": fmt(b_hit),
                    "current_shadow_hit_rate": fmt(c_hit),
                    "scenario_minus_baseline_hit_rate": fmt(d_hit_base),
                    "scenario_minus_current_shadow_hit_rate": fmt(d_hit_current),
                    "available_forward_outcome_count": str(len(s_vals) + len(b_vals) + len(c_vals)),
                    "missing_forward_outcome_count": str(max(0, missing)),
                    "coverage_status": coverage,
                    "cell_effectiveness_status": cell_status,
                    "broad_or_local_status": "LOCAL_TARGET_CELL" if window == prior_window and top_n == prior_topn else "BROAD_CONTEXT_CELL",
                    **safety(),
                })
                if window == prior_window and top_n == prior_topn:
                    prior_pass = beats_base_cell and beats_current_cell
                    prior_rows.append({
                        "simulation_scenario_id": sid,
                        "scenario_type": meta["scenario_type"],
                        "prior_failure_area": prior_area,
                        "prior_failure_forward_window": prior_window,
                        "prior_failure_top_n": str(prior_topn),
                        "baseline_mean_forward_return": fmt(b_mean),
                        "current_shadow_mean_forward_return": fmt(c_mean),
                        "scenario_mean_forward_return": fmt(s_mean),
                        "scenario_minus_baseline_mean_return": fmt(d_base),
                        "scenario_minus_current_shadow_mean_return": fmt(d_current),
                        "baseline_hit_rate": fmt(b_hit),
                        "current_shadow_hit_rate": fmt(c_hit),
                        "scenario_hit_rate": fmt(s_hit),
                        "scenario_minus_baseline_hit_rate": fmt(d_hit_base),
                        "scenario_minus_current_shadow_hit_rate": fmt(d_hit_current),
                        "prior_failure_repair_passed": tf(prior_pass),
                        "prior_failure_repair_status": "PRIOR_FAILURE_REPAIRED" if prior_pass else "PRIOR_FAILURE_UNRESOLVED",
                        "prior_failure_repair_reason": "120D_TOP20 must beat both baseline and current shadow on mean return.",
                        **safety(),
                    })

        for top_n in [20, 40]:
            scenario_set = top_set(rows, "second_round_simulated_shadow_rank", top_n)
            baseline_set = top_set(current, "baseline_rank", top_n)
            current_set = top_set(current, "strict_equity_shadow_rank", top_n)
            turnover_base = len(scenario_set - baseline_set)
            turnover_current = len(scenario_set - current_set)
            ratio_base = Decimal(turnover_base) / Decimal(max(1, len(scenario_set)))
            ratio_current = Decimal(turnover_current) / Decimal(max(1, len(scenario_set)))
            acceptable = ratio_base <= Decimal("0.75") and ratio_current <= Decimal("0.50")
            top_churn[top_n] = acceptable
            stability_rows.append({
                "simulation_scenario_id": sid,
                "scenario_type": meta["scenario_type"],
                "top_n": str(top_n),
                "scenario_top_n_count": str(len(scenario_set)),
                "baseline_top_n_count": str(len(baseline_set)),
                "current_shadow_top_n_count": str(len(current_set)),
                "overlap_with_baseline_count": str(len(scenario_set & baseline_set)),
                "overlap_with_current_shadow_count": str(len(scenario_set & current_set)),
                "turnover_vs_baseline_count": str(turnover_base),
                "turnover_vs_current_shadow_count": str(turnover_current),
                "turnover_vs_baseline_ratio": fmt(ratio_base),
                "turnover_vs_current_shadow_ratio": fmt(ratio_current),
                "churn_acceptable": tf(acceptable),
                "stability_status": "TOPN_CHURN_ACCEPTABLE" if acceptable else "TOPN_CHURN_ELEVATED",
                "stability_reason": "Top20/Top40 churn is diagnostic only; no ranking is promoted.",
                **safety(),
            })

        avg_base = avg(mean_delta_base)
        avg_current = avg(mean_delta_current)
        avg_hit_base = avg(hit_delta_base)
        avg_hit_current = avg(hit_delta_current)
        broad = beat_both >= 8
        effectiveness = "BROAD_DIAGNOSTIC_IMPROVEMENT" if broad else ("LOCAL_OR_FRAGILE_IMPROVEMENT" if beat_both > 0 else "NO_DIAGNOSTIC_IMPROVEMENT")
        rollups[sid] = {
            "beat_both": beat_both,
            "avg_base": avg_base,
            "avg_current": avg_current,
            "prior_pass": prior_pass,
            "top20": top_churn.get(20, False),
            "top40": top_churn.get(40, False),
        }
        baseline_rows.append({
            "simulation_scenario_id": sid,
            "scenario_type": meta["scenario_type"],
            "evaluated_cell_count": str(len(WINDOWS) * len(TOPNS)),
            "cells_beating_baseline_count": str(beat_base),
            "cells_beating_current_shadow_count": str(beat_current),
            "cells_beating_both_count": str(beat_both),
            "cells_losing_to_both_count": str(lose_both),
            "average_delta_vs_baseline": fmt(avg_base),
            "average_delta_vs_current_shadow": fmt(avg_current),
            "average_hit_rate_delta_vs_baseline": fmt(avg_hit_base),
            "average_hit_rate_delta_vs_current_shadow": fmt(avg_hit_current),
            "improvement_breadth_status": "BROAD" if broad else "LOCAL_OR_FRAGILE",
            "scenario_effectiveness_status": effectiveness,
            "scenario_effectiveness_reason": "Research-only comparison, no performance claim or acceptance.",
            "accepted_weight_created": "FALSE",
            "official_weight_created": "FALSE",
            "new_weights_created": "FALSE",
            "official_ranking_created": "FALSE",
            "official_recommendation_created": "FALSE",
            "trade_action_created": "FALSE",
            "broker_execution_supported": "FALSE",
            "performance_effectiveness_claim_created": "FALSE",
            "authoritative_ranking_overwritten": "FALSE",
            **safety(),
            "is_official_weight": "FALSE",
            "weight_mutated": "FALSE",
        })

    def best_key(sid: str) -> tuple[int, Decimal, Decimal]:
        roll = rollups[sid]
        return (
            int(roll["beat_both"]),
            roll["avg_current"] if isinstance(roll["avg_current"], Decimal) else Decimal("-999"),
            roll["avg_base"] if isinstance(roll["avg_base"], Decimal) else Decimal("-999"),
        )

    best_id = max(scenario_ids, key=best_key) if scenario_ids else ""
    best_meta = scenario_meta.get(best_id, {})
    best_roll = rollups.get(best_id, {})
    evidence_limited = any_partial
    duplicate_rank_count = int(v.get("duplicate_rank_count", "999") or "999")
    missing_rank_count = int(v.get("missing_rank_count", "999") or "999")
    prior_validated = any(row["prior_failure_repair_passed"] == "TRUE" for row in prior_rows)
    best_prior = bool(best_roll.get("prior_pass"))
    best_churn = bool(best_roll.get("top20")) and bool(best_roll.get("top40"))
    materially_better = int(best_roll.get("beat_both", 0) or 0) >= 8 and (best_roll.get("avg_current") or Decimal("-1")) > 0 and (best_roll.get("avg_base") or Decimal("-1")) > 0
    acceptance_allowed = valid_inputs and materially_better and best_prior and best_churn and duplicate_rank_count == 0 and missing_rank_count == 0 and not evidence_limited

    if not valid_inputs:
        wrapper = BLOCKED_MISSING_STATUS
        next_action = "V20.109-R8_INPUT_REPAIR"
        blocking_reason = "MISSING_REQUIRED_R8_INPUTS"
    elif not prior_validated:
        wrapper = BLOCKED_PRIOR_STATUS
        next_action = "V20.109-R10_TARGETED_PRIOR_FAILURE_REPAIR"
        blocking_reason = "PRIOR_FAILURE_REPAIR_NOT_VALIDATED"
    elif acceptance_allowed:
        wrapper = PASS_STATUS
        next_action = "V20.110_RESEARCH_ACCEPTANCE_GATE"
        blocking_reason = ""
    elif evidence_limited or not best_churn or not materially_better:
        wrapper = WARN_STATUS if materially_better else PARTIAL_STATUS
        next_action = "V20.109-R10_SCENARIO_SELECTION_GUARD"
        blocking_reason = "EVIDENCE_LIMITED_OR_SCENARIO_FRAGILE"
    else:
        wrapper = PARTIAL_STATUS
        next_action = "V20.109-R10_SCENARIO_SELECTION_GUARD"
        blocking_reason = "STRICT_ACCEPTANCE_CONDITIONS_NOT_MET"

    selection_rows = [{
        "selection_check_id": "V20_109_R9_SCENARIO_SELECTION_001",
        "scenario_count": str(len(scenario_ids)),
        "valid_scenario_count": str(len(scenario_ids)),
        "best_scenario_id": best_id,
        "best_scenario_type": best_meta.get("scenario_type", ""),
        "best_scenario_cells_beating_both_count": str(best_roll.get("beat_both", 0)),
        "best_scenario_average_delta_vs_baseline": fmt(best_roll.get("avg_base") if isinstance(best_roll.get("avg_base"), Decimal) else None),
        "best_scenario_average_delta_vs_current_shadow": fmt(best_roll.get("avg_current") if isinstance(best_roll.get("avg_current"), Decimal) else None),
        "best_scenario_prior_failure_repair_passed": tf(best_prior),
        "best_scenario_top20_churn_acceptable": tf(bool(best_roll.get("top20"))),
        "best_scenario_top40_churn_acceptable": tf(bool(best_roll.get("top40"))),
        "evidence_coverage_status": "PARTIAL_FORWARD_OUTCOME_COVERAGE" if evidence_limited else "FULL_FORWARD_OUTCOME_COVERAGE",
        "scenario_selection_status": "ACCEPTANCE_READY_DIAGNOSTIC" if acceptance_allowed else "NOT_ACCEPTANCE_READY_DIAGNOSTIC",
        "scenario_selection_reason": "Strict gate requires broad improvement, prior repair, acceptable churn, complete ranks, and non-fragile evidence.",
        "v20_110_acceptance_gate_allowed": tf(acceptance_allowed),
        "accepted_weight_created": "FALSE",
        "official_weight_created": "FALSE",
        "new_weights_created": "FALSE",
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
    gate_rows = [{
        "gate_check_id": "V20_109_R9_NEXT_STAGE_GATE_001",
        "second_round_effectiveness_comparison_created": tf(valid_inputs),
        "scenario_count": str(len(scenario_ids)),
        "valid_scenario_count": str(len(scenario_ids)),
        "prior_failure_repair_validated": tf(prior_validated),
        "top20_top40_churn_acceptable": tf(best_churn),
        "duplicate_rank_count": str(duplicate_rank_count),
        "missing_rank_count": str(missing_rank_count),
        "evidence_limited_or_fragile": tf(evidence_limited or not materially_better or not best_churn),
        "v20_110_acceptance_gate_allowed": tf(acceptance_allowed),
        "next_recommended_action": next_action,
        "blocking_reason": blocking_reason,
        "accepted_weight_created": "FALSE",
        "official_weight_created": "FALSE",
        "new_weights_created": "FALSE",
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

    write_csv(OUT_COMPARE, COMPARE_FIELDS, comparison_rows)
    write_csv(OUT_PRIOR, PRIOR_FIELDS, prior_rows)
    write_csv(OUT_STABILITY, STABILITY_FIELDS, stability_rows)
    write_csv(OUT_BASELINE, BASELINE_FIELDS, baseline_rows)
    write_csv(OUT_SELECTION, SELECTION_FIELDS, selection_rows)
    write_csv(OUT_GATE, GATE_FIELDS, gate_rows)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        "\n".join([
            "# V20.109-R9 Second Round Effectiveness Comparison Report",
            "",
            "## Current Result",
            f"- wrapper_status: {wrapper}",
            f"- scenario_count: {len(scenario_ids)}",
            f"- best_scenario_id: {best_id}",
            f"- prior_failure_repair_validated: {tf(prior_validated)}",
            f"- v20_110_acceptance_gate_allowed: {tf(acceptance_allowed)}",
            f"- next_recommended_action: {next_action}",
            "- accepted_weight_created: FALSE",
            "- official_weight_created: FALSE",
            "- official_ranking_created: FALSE",
            "- performance_effectiveness_claim_created: FALSE",
        ]) + "\n",
        encoding="utf-8",
    )

    print(wrapper)
    print(f"SCENARIO_COUNT={len(scenario_ids)}")
    print(f"VALID_SCENARIO_COUNT={len(scenario_ids)}")
    print(f"BEST_SCENARIO_ID={best_id}")
    print(f"PRIOR_FAILURE_AREA={prior_area}")
    print(f"PRIOR_FAILURE_REPAIR_VALIDATED={tf(prior_validated)}")
    print(f"TOP20_TOP40_CHURN_ACCEPTABLE={tf(best_churn)}")
    print(f"DUPLICATE_RANK_COUNT={duplicate_rank_count}")
    print(f"MISSING_RANK_COUNT={missing_rank_count}")
    print(f"V20_110_ACCEPTANCE_GATE_ALLOWED={tf(acceptance_allowed)}")
    print(f"NEXT_RECOMMENDED_ACTION={next_action}")
    print("ACCEPTED_WEIGHT_CREATED=FALSE")
    print("OFFICIAL_WEIGHT_CREATED=FALSE")
    print("NEW_WEIGHTS_CREATED=FALSE")
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
