#!/usr/bin/env python
"""V20.109-R10 targeted prior failure repair.

Research-only targeted repair of the unresolved 120D_TOP20 failure. This stage
creates conservative repair scenario diagnostics only. It does not create
accepted weights, official weights, recommendations, trades, or a full rerank.
"""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R9_COMPARE = CONSOLIDATION / "V20_109_R9_SECOND_ROUND_EFFECTIVENESS_COMPARISON.csv"
R9_PRIOR = CONSOLIDATION / "V20_109_R9_PRIOR_FAILURE_REPAIR_COMPARISON.csv"
R9_STABILITY = CONSOLIDATION / "V20_109_R9_TOP20_TOP40_STABILITY_AUDIT.csv"
R9_BASELINE = CONSOLIDATION / "V20_109_R9_BASELINE_VS_SECOND_ROUND_SCENARIO_AUDIT.csv"
R9_SELECTION = CONSOLIDATION / "V20_109_R9_SCENARIO_SELECTION_RECOMMENDATION.csv"
R9_GATE = CONSOLIDATION / "V20_109_R9_NEXT_STAGE_GATE.csv"
R8_RERANK = CONSOLIDATION / "V20_109_R8_SECOND_ROUND_SIMULATED_WEIGHT_STRICT_EQUITY_RERANK.csv"
R8_DELTA = CONSOLIDATION / "V20_109_R8_SECOND_ROUND_SIMULATED_RANK_DELTA_AUDIT.csv"
R8_COMPONENT = CONSOLIDATION / "V20_109_R8_SECOND_ROUND_SIMULATED_SCORE_COMPONENT_AUDIT.csv"
R8_VALIDATION = CONSOLIDATION / "V20_109_R8_SECOND_ROUND_SIMULATED_RERANK_VALIDATION.csv"
R12_RERANK = CONSOLIDATION / "V20_108_R12_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK.csv"
V104_FORWARD = CONSOLIDATION / "V20_104_RANDOM_ASOF_FORWARD_OUTCOME_MATRIX.csv"

OUT_SCENARIOS = CONSOLIDATION / "V20_109_R10_TARGETED_PRIOR_FAILURE_REPAIR_SCENARIOS.csv"
OUT_REPAIR = CONSOLIDATION / "V20_109_R10_120D_TOP20_REPAIR_AUDIT.csv"
OUT_CHURN = CONSOLIDATION / "V20_109_R10_TOP20_TOP40_CHURN_CONSTRAINT_AUDIT.csv"
OUT_RERANK = CONSOLIDATION / "V20_109_R10_REPAIR_RERANK_AUDIT.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_109_R10_REPAIR_EFFECTIVENESS_VALIDATION.csv"
OUT_GUARD = CONSOLIDATION / "V20_109_R10_SCENARIO_SELECTION_GUARD.csv"
OUT_GATE = CONSOLIDATION / "V20_109_R10_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_109_R10_TARGETED_PRIOR_FAILURE_REPAIR_REPORT.md"

PASS_STATUS = "PASS_V20_109_R10_TARGETED_PRIOR_FAILURE_REPAIR_READY_FOR_R11"
PARTIAL_STATUS = "PARTIAL_PASS_V20_109_R10_REPAIR_CREATED_WITH_LIMITED_EVIDENCE"
BLOCKED_MISSING_STATUS = "BLOCKED_V20_109_R10_MISSING_REQUIRED_R9_INPUTS"
BLOCKED_UNVALIDATED_STATUS = "BLOCKED_V20_109_R10_120D_TOP20_REPAIR_STILL_UNVALIDATED"
WARN_CHURN_STATUS = "WARN_V20_109_R10_REPAIR_EFFECTIVE_BUT_CHURN_TOO_HIGH"
WARN_ROBUSTNESS_STATUS = "WARN_V20_109_R10_REPAIR_EFFECTIVE_BUT_NEEDS_ROBUSTNESS_VALIDATION"

SCENARIO_FIELDS = ["repair_scenario_id","seed_scenario_id","seed_scenario_type","repair_scenario_type","repair_priority","prior_failure_area","target_forward_window","target_topn_group","top20_baseline_overlap_floor","top40_baseline_overlap_floor","churn_constraint_method","repair_rule_summary","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","accepted_weight_created","official_weight_created","new_weights_created","new_rerank_created","trade_action_created","broker_execution_supported","performance_effectiveness_claim_created","authoritative_ranking_overwritten"]
REPAIR_FIELDS = ["repair_scenario_id","seed_scenario_id","prior_failure_area","target_forward_window","target_topn_group","baseline_mean_forward_return","current_shadow_mean_forward_return","seed_scenario_mean_forward_return","repair_scenario_mean_forward_return","repair_minus_baseline_mean_return","repair_minus_current_shadow_mean_return","repair_minus_seed_mean_return","baseline_hit_rate","current_shadow_hit_rate","seed_scenario_hit_rate","repair_scenario_hit_rate","repair_minus_baseline_hit_rate","repair_minus_current_shadow_hit_rate","repair_120d_top20_validated","repair_status","repair_reason","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
CHURN_FIELDS = ["repair_scenario_id","seed_scenario_id","top_n","baseline_overlap_count","current_shadow_overlap_count","seed_scenario_overlap_count","turnover_vs_baseline_count","turnover_vs_current_shadow_count","turnover_vs_seed_count","turnover_vs_baseline_ratio","turnover_vs_current_shadow_ratio","turnover_vs_seed_ratio","churn_acceptable","churn_status","churn_reason","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
RERANK_FIELDS = ["repair_scenario_id","ticker","audit_scope","baseline_rank","current_shadow_rank","seed_scenario_rank","repair_audit_rank","selected_in_repair_top20","selected_in_repair_top40","selection_source","rank_source_status","duplicate_rank_count","missing_rank_count","research_only","shadow_only","simulation_only","official_promotion_allowed","official_recommendation_created","accepted_weight_created","official_weight_created","new_rerank_created","trade_action_created","broker_execution_supported"]
VALIDATION_FIELDS = ["validation_check_id","repair_scenario_count","validated_repair_scenario_count","top20_churn_acceptable_count","top40_churn_acceptable_count","duplicate_rank_count","missing_rank_count","r9_seed_scenario_id","prior_failure_area","prior_failure_repair_validated","best_repair_scenario_id","best_repair_status","evidence_limited","accepted_weight_created","official_weight_created","new_weights_created","new_rerank_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","performance_effectiveness_claim_created","authoritative_ranking_overwritten","validation_status","validation_reason","research_only","shadow_only","simulation_only","official_promotion_allowed","is_official_weight","weight_mutated"]
GUARD_FIELDS = ["guard_check_id","best_repair_scenario_id","best_repair_validates_120d_top20","best_repair_top20_churn_acceptable","best_repair_top40_churn_acceptable","sufficient_for_r11_repair_robustness_validation","sufficient_for_v20_110_acceptance_gate","guard_status","guard_reason","accepted_weight_created","official_weight_created","new_weights_created","new_rerank_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","performance_effectiveness_claim_created","authoritative_ranking_overwritten","research_only","shadow_only","simulation_only","official_promotion_allowed","is_official_weight","weight_mutated"]
GATE_FIELDS = ["gate_check_id","targeted_prior_failure_repair_created","repair_scenario_count","validated_repair_scenario_count","best_repair_scenario_id","v20_109_r11_repair_robustness_validation_allowed","v20_110_acceptance_gate_allowed","next_recommended_action","blocking_reason","accepted_weight_created","official_weight_created","new_weights_created","new_rerank_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","performance_effectiveness_claim_created","authoritative_ranking_overwritten","research_only","shadow_only","simulation_only","official_promotion_allowed","is_official_weight","weight_mutated"]


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


def top_by(rows: list[dict[str, str]], rank_field: str, top_n: int) -> list[str]:
    ranked = sorted(
        [row for row in rows if dec(row.get(rank_field, "")) is not None],
        key=lambda row: (int(dec(row.get(rank_field, "")) or Decimal("999999")), row["ticker"]),
    )
    return [row["ticker"] for row in ranked[:top_n]]


def outcome_stats(tickers: list[str], outcomes: dict[str, list[Decimal]]) -> tuple[Decimal | None, Decimal | None]:
    vals = [value for ticker in tickers for value in outcomes.get(ticker, [])]
    if not vals:
        return None, None
    return sum(vals, Decimal("0")) / Decimal(len(vals)), Decimal(sum(1 for value in vals if value > 0)) / Decimal(len(vals))


def constrained_top(seed: list[str], baseline: list[str], top_n: int, baseline_floor: int) -> list[str]:
    selected: list[str] = []
    for ticker in baseline:
        if ticker not in selected and len(selected) < baseline_floor:
            selected.append(ticker)
    for ticker in seed:
        if ticker not in selected and len(selected) < top_n:
            selected.append(ticker)
    for ticker in baseline:
        if ticker not in selected and len(selected) < top_n:
            selected.append(ticker)
    return selected[:top_n]


def main() -> int:
    r9_selection, _, r9_selection_status = read_csv(R9_SELECTION)
    r9_gate, _, r9_gate_status = read_csv(R9_GATE)
    r9_prior, _, r9_prior_status = read_csv(R9_PRIOR)
    r9_stability, _, r9_stability_status = read_csv(R9_STABILITY)
    r8_rerank, _, r8_status = read_csv(R8_RERANK)
    r8_validation, _, r8_validation_status = read_csv(R8_VALIDATION)
    current, _, current_status = read_csv(R12_RERANK)
    forward, _, forward_status = read_csv(V104_FORWARD)
    required_ok = all(status == "OK" for status in [r9_selection_status, r9_gate_status, r9_prior_status, r9_stability_status, r8_status, r8_validation_status, current_status, forward_status])

    seed_id = r9_selection[0].get("best_scenario_id", "SIM2_002") if r9_selection else "SIM2_002"
    seed_type = r9_selection[0].get("best_scenario_type", "") if r9_selection else ""
    prior_area = "120D_TOP20"
    target_window = "120D"
    target_topn = 20
    seed_rows = [row for row in r8_rerank if row.get("simulation_scenario_id") == seed_id]
    v = r8_validation[0] if r8_validation else {}
    duplicate_rank_count = int(v.get("duplicate_rank_count", "0") or "0")
    missing_rank_count = int(v.get("missing_rank_count", "0") or "0")
    outcomes: dict[str, list[Decimal]] = {}
    for row in forward:
        value = dec(row.get("forward_return", ""))
        if row.get("forward_window") == target_window and row.get("outcome_available") == "TRUE" and value is not None:
            outcomes.setdefault(row.get("ticker", ""), []).append(value)

    baseline20 = top_by(current, "baseline_rank", 20)
    baseline40 = top_by(current, "baseline_rank", 40)
    current20 = top_by(current, "strict_equity_shadow_rank", 20)
    current40 = top_by(current, "strict_equity_shadow_rank", 40)
    seed20 = top_by(seed_rows, "second_round_simulated_shadow_rank", 20)
    seed40 = top_by(seed_rows, "second_round_simulated_shadow_rank", 40)
    baseline_mean, baseline_hit = outcome_stats(baseline20, outcomes)
    current_mean, current_hit = outcome_stats(current20, outcomes)
    seed_mean, seed_hit = outcome_stats(seed20, outcomes)

    variants = [
        ("R10_REPAIR_001_SIM2_002_LIGHT_120D_TOP20_BOOST", "LIGHT_120D_TOP20_BOOST", "HIGH", 8, 18, "baseline_floor_8_top20"),
        ("R10_REPAIR_002_SIM2_002_CHURN_REDUCTION", "CHURN_REDUCTION", "HIGH", 10, 22, "baseline_floor_10_top20"),
        ("R10_REPAIR_003_SIM2_002_RANK_STABILITY_PENALTY", "RANK_STABILITY_PENALTY", "MEDIUM", 11, 24, "baseline_floor_11_top20"),
        ("R10_REPAIR_004_SIM2_002_TOP20_OVERLAP_FLOOR", "TOP20_OVERLAP_FLOOR", "HIGH", 12, 24, "top20_overlap_floor"),
        ("R10_REPAIR_005_SIM2_002_TOP40_OVERLAP_FLOOR", "TOP40_OVERLAP_FLOOR", "HIGH", 10, 28, "top40_overlap_floor"),
        ("R10_REPAIR_006_SIM2_002_REPAIR_PLUS_CHURN_CAP", "REPAIR_PLUS_CHURN_CAP", "HIGH", 13, 30, "repair_plus_churn_cap"),
        ("R10_REPAIR_007_CONSERVATIVE_FALLBACK_REPAIR", "CONSERVATIVE_FALLBACK_REPAIR", "MEDIUM", 15, 32, "conservative_fallback"),
        ("R10_REPAIR_008_MINIMUM_CHANGE_REPAIR", "MINIMUM_CHANGE_REPAIR", "LOW", 6, 14, "minimum_change"),
    ]

    scenario_rows = []
    repair_rows = []
    churn_rows = []
    rerank_rows = []
    best_id = ""
    best_score = Decimal("-999")
    validated_count = 0
    top20_ok_count = 0
    top40_ok_count = 0

    for repair_id, repair_type, priority, floor20, floor40, method in variants:
        repair20 = constrained_top(seed20, baseline20, 20, floor20)
        repair40 = constrained_top(seed40, baseline40, 40, floor40)
        repair_mean, repair_hit = outcome_stats(repair20, outcomes)
        repair_vs_base = repair_mean - baseline_mean if repair_mean is not None and baseline_mean is not None else None
        repair_vs_current = repair_mean - current_mean if repair_mean is not None and current_mean is not None else None
        repair_vs_seed = repair_mean - seed_mean if repair_mean is not None and seed_mean is not None else None
        hit_vs_base = repair_hit - baseline_hit if repair_hit is not None and baseline_hit is not None else None
        hit_vs_current = repair_hit - current_hit if repair_hit is not None and current_hit is not None else None
        repair_validated = repair_vs_base is not None and repair_vs_current is not None and repair_vs_base >= 0 and repair_vs_current > 0
        top20_turnover_base = len(set(repair20) - set(baseline20))
        top20_turnover_current = len(set(repair20) - set(current20))
        top40_turnover_base = len(set(repair40) - set(baseline40))
        top40_turnover_current = len(set(repair40) - set(current40))
        top20_ok = top20_turnover_base <= 10 and top20_turnover_current <= 18
        top40_ok = top40_turnover_base <= 18 and top40_turnover_current <= 35
        validated_count += int(repair_validated)
        top20_ok_count += int(top20_ok)
        top40_ok_count += int(top40_ok)
        combined_score = (repair_vs_base or Decimal("-1")) + (Decimal("0.01") * Decimal(floor20))
        if repair_validated and top20_ok and top40_ok and combined_score > best_score:
            best_score = combined_score
            best_id = repair_id
        scenario_rows.append({
            "repair_scenario_id": repair_id,
            "seed_scenario_id": seed_id,
            "seed_scenario_type": seed_type,
            "repair_scenario_type": repair_type,
            "repair_priority": priority,
            "prior_failure_area": prior_area,
            "target_forward_window": target_window,
            "target_topn_group": str(target_topn),
            "top20_baseline_overlap_floor": str(floor20),
            "top40_baseline_overlap_floor": str(floor40),
            "churn_constraint_method": method,
            "repair_rule_summary": "Constrained seed scenario with baseline overlap floor; no full rerank or accepted weights created.",
            **safety(),
            "accepted_weight_created": "FALSE",
            "official_weight_created": "FALSE",
            "new_weights_created": "FALSE",
            "new_rerank_created": "FALSE",
            "performance_effectiveness_claim_created": "FALSE",
            "authoritative_ranking_overwritten": "FALSE",
        })
        repair_rows.append({
            "repair_scenario_id": repair_id,
            "seed_scenario_id": seed_id,
            "prior_failure_area": prior_area,
            "target_forward_window": target_window,
            "target_topn_group": str(target_topn),
            "baseline_mean_forward_return": fmt(baseline_mean),
            "current_shadow_mean_forward_return": fmt(current_mean),
            "seed_scenario_mean_forward_return": fmt(seed_mean),
            "repair_scenario_mean_forward_return": fmt(repair_mean),
            "repair_minus_baseline_mean_return": fmt(repair_vs_base),
            "repair_minus_current_shadow_mean_return": fmt(repair_vs_current),
            "repair_minus_seed_mean_return": fmt(repair_vs_seed),
            "baseline_hit_rate": fmt(baseline_hit),
            "current_shadow_hit_rate": fmt(current_hit),
            "seed_scenario_hit_rate": fmt(seed_hit),
            "repair_scenario_hit_rate": fmt(repair_hit),
            "repair_minus_baseline_hit_rate": fmt(hit_vs_base),
            "repair_minus_current_shadow_hit_rate": fmt(hit_vs_current),
            "repair_120d_top20_validated": tf(repair_validated),
            "repair_status": "REPAIR_VALIDATED_DIAGNOSTIC" if repair_validated else "REPAIR_NOT_VALIDATED",
            "repair_reason": "Uses real 120D outcomes for constrained top20 audit; no imputation.",
            **safety(),
        })
        for top_n, repair_top, baseline_top, current_top, seed_top, ok in [
            (20, repair20, baseline20, current20, seed20, top20_ok),
            (40, repair40, baseline40, current40, seed40, top40_ok),
        ]:
            turnover_base = len(set(repair_top) - set(baseline_top))
            turnover_current = len(set(repair_top) - set(current_top))
            turnover_seed = len(set(repair_top) - set(seed_top))
            churn_rows.append({
                "repair_scenario_id": repair_id,
                "seed_scenario_id": seed_id,
                "top_n": str(top_n),
                "baseline_overlap_count": str(len(set(repair_top) & set(baseline_top))),
                "current_shadow_overlap_count": str(len(set(repair_top) & set(current_top))),
                "seed_scenario_overlap_count": str(len(set(repair_top) & set(seed_top))),
                "turnover_vs_baseline_count": str(turnover_base),
                "turnover_vs_current_shadow_count": str(turnover_current),
                "turnover_vs_seed_count": str(turnover_seed),
                "turnover_vs_baseline_ratio": fmt(Decimal(turnover_base) / Decimal(top_n)),
                "turnover_vs_current_shadow_ratio": fmt(Decimal(turnover_current) / Decimal(top_n)),
                "turnover_vs_seed_ratio": fmt(Decimal(turnover_seed) / Decimal(top_n)),
                "churn_acceptable": tf(ok),
                "churn_status": "CHURN_CONSTRAINT_PASS" if ok else "CHURN_CONSTRAINT_FAIL",
                "churn_reason": "Top20/Top40 constrained overlap diagnostic; no new rerank artifact created.",
                **safety(),
            })
        for rank, ticker in enumerate(repair40, start=1):
            current_row = next((row for row in current if row["ticker"] == ticker), {})
            seed_row = next((row for row in seed_rows if row["ticker"] == ticker), {})
            rerank_rows.append({
                "repair_scenario_id": repair_id,
                "ticker": ticker,
                "audit_scope": "TOP20_TOP40_REPAIR_AUDIT_ONLY",
                "baseline_rank": current_row.get("baseline_rank", ""),
                "current_shadow_rank": current_row.get("strict_equity_shadow_rank", ""),
                "seed_scenario_rank": seed_row.get("second_round_simulated_shadow_rank", ""),
                "repair_audit_rank": str(rank),
                "selected_in_repair_top20": tf(ticker in repair20),
                "selected_in_repair_top40": "TRUE",
                "selection_source": "BASELINE_OVERLAP_FLOOR" if ticker in baseline40 else "SEED_SCENARIO_FILL",
                "rank_source_status": "DIAGNOSTIC_AUDIT_ONLY_NOT_FULL_RERANK",
                "duplicate_rank_count": str(duplicate_rank_count),
                "missing_rank_count": str(missing_rank_count),
                **safety(),
                "accepted_weight_created": "FALSE",
                "official_weight_created": "FALSE",
                "new_rerank_created": "FALSE",
            })

    promising = bool(best_id)
    validation_status = "PASS" if promising else "BLOCKED"
    v20_110_allowed = False
    validation_rows = [{
        "validation_check_id": "V20_109_R10_REPAIR_EFFECTIVENESS_VALIDATION_001",
        "repair_scenario_count": str(len(scenario_rows)),
        "validated_repair_scenario_count": str(validated_count),
        "top20_churn_acceptable_count": str(top20_ok_count),
        "top40_churn_acceptable_count": str(top40_ok_count),
        "duplicate_rank_count": str(duplicate_rank_count),
        "missing_rank_count": str(missing_rank_count),
        "r9_seed_scenario_id": seed_id,
        "prior_failure_area": prior_area,
        "prior_failure_repair_validated": tf(validated_count > 0),
        "best_repair_scenario_id": best_id,
        "best_repair_status": "PROMISING_FOR_R11_DIAGNOSTIC" if promising else "NO_REPAIR_VALIDATED",
        "evidence_limited": "TRUE",
        "accepted_weight_created": "FALSE",
        "official_weight_created": "FALSE",
        "new_weights_created": "FALSE",
        "new_rerank_created": "FALSE",
        "official_ranking_created": "FALSE",
        "official_recommendation_created": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        "performance_effectiveness_claim_created": "FALSE",
        "authoritative_ranking_overwritten": "FALSE",
        "validation_status": validation_status,
        "validation_reason": "Targeted repair created for R11 robustness validation." if promising else "120D_TOP20 repair still unvalidated.",
        **safety(),
        "is_official_weight": "FALSE",
        "weight_mutated": "FALSE",
    }]
    guard_rows = [{
        "guard_check_id": "V20_109_R10_SCENARIO_SELECTION_GUARD_001",
        "best_repair_scenario_id": best_id,
        "best_repair_validates_120d_top20": tf(promising),
        "best_repair_top20_churn_acceptable": tf(promising),
        "best_repair_top40_churn_acceptable": tf(promising),
        "sufficient_for_r11_repair_robustness_validation": tf(promising),
        "sufficient_for_v20_110_acceptance_gate": "FALSE",
        "guard_status": "READY_FOR_R11_REPAIR_ROBUSTNESS_VALIDATION" if promising else "REPAIR_ITERATION_REQUIRED",
        "guard_reason": "R10 cannot accept weights; promising repairs require R11 robustness validation.",
        "accepted_weight_created": "FALSE",
        "official_weight_created": "FALSE",
        "new_weights_created": "FALSE",
        "new_rerank_created": "FALSE",
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
        "gate_check_id": "V20_109_R10_NEXT_STAGE_GATE_001",
        "targeted_prior_failure_repair_created": tf(required_ok),
        "repair_scenario_count": str(len(scenario_rows)),
        "validated_repair_scenario_count": str(validated_count),
        "best_repair_scenario_id": best_id,
        "v20_109_r11_repair_robustness_validation_allowed": tf(promising),
        "v20_110_acceptance_gate_allowed": tf(v20_110_allowed),
        "next_recommended_action": "V20.109-R11_REPAIR_ROBUSTNESS_VALIDATION" if promising else "V20.109-R10_TARGETED_PRIOR_FAILURE_REPAIR_ITERATION",
        "blocking_reason": "" if promising else "120D_TOP20_REPAIR_STILL_UNVALIDATED",
        "accepted_weight_created": "FALSE",
        "official_weight_created": "FALSE",
        "new_weights_created": "FALSE",
        "new_rerank_created": "FALSE",
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
    elif not promising:
        wrapper = BLOCKED_UNVALIDATED_STATUS
    else:
        wrapper = WARN_ROBUSTNESS_STATUS

    write_csv(OUT_SCENARIOS, SCENARIO_FIELDS, scenario_rows)
    write_csv(OUT_REPAIR, REPAIR_FIELDS, repair_rows)
    write_csv(OUT_CHURN, CHURN_FIELDS, churn_rows)
    write_csv(OUT_RERANK, RERANK_FIELDS, rerank_rows)
    write_csv(OUT_VALIDATION, VALIDATION_FIELDS, validation_rows)
    write_csv(OUT_GUARD, GUARD_FIELDS, guard_rows)
    write_csv(OUT_GATE, GATE_FIELDS, gate_rows)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        "\n".join([
            "# V20.109-R10 Targeted Prior Failure Repair Report",
            "",
            "## Current Result",
            f"- wrapper_status: {wrapper}",
            f"- seed_scenario_id: {seed_id}",
            f"- prior_failure_area: {prior_area}",
            f"- repair_scenario_count: {len(scenario_rows)}",
            f"- validated_repair_scenario_count: {validated_count}",
            f"- best_repair_scenario_id: {best_id}",
            f"- v20_109_r11_repair_robustness_validation_allowed: {tf(promising)}",
            "- v20_110_acceptance_gate_allowed: FALSE",
            "- accepted_weight_created: FALSE",
            "- official_weight_created: FALSE",
            "- official_ranking_created: FALSE",
            "- performance_effectiveness_claim_created: FALSE",
        ]) + "\n",
        encoding="utf-8",
    )

    print(wrapper)
    print(f"SEED_SCENARIO_ID={seed_id}")
    print(f"PRIOR_FAILURE_AREA={prior_area}")
    print(f"REPAIR_SCENARIO_COUNT={len(scenario_rows)}")
    print(f"VALIDATED_REPAIR_SCENARIO_COUNT={validated_count}")
    print(f"BEST_REPAIR_SCENARIO_ID={best_id}")
    print(f"DUPLICATE_RANK_COUNT={duplicate_rank_count}")
    print(f"MISSING_RANK_COUNT={missing_rank_count}")
    print(f"V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION_ALLOWED={tf(promising)}")
    print("V20_110_ACCEPTANCE_GATE_ALLOWED=FALSE")
    print("ACCEPTED_WEIGHT_CREATED=FALSE")
    print("OFFICIAL_WEIGHT_CREATED=FALSE")
    print("NEW_WEIGHTS_CREATED=FALSE")
    print("NEW_RERANK_CREATED=FALSE")
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
