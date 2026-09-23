#!/usr/bin/env python
"""V20.109-R1 shadow underperformance decomposition and repair plan.

Research-only diagnostics after V20.109. This stage creates no new weights and
no new rerank; it only maps failure areas and proposes later simulations.
"""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

V109_SUMMARY = CONSOLIDATION / "V20_109_STRICT_EQUITY_SHADOW_VS_BASELINE_EFFECTIVENESS_SUMMARY.csv"
V109_MATRIX = CONSOLIDATION / "V20_109_FORWARD_WINDOW_TOPN_EFFECTIVENESS_MATRIX.csv"
V109_ATTR = CONSOLIDATION / "V20_109_SHADOW_RERANK_FACTOR_EFFECTIVENESS_ATTRIBUTION.csv"
V109_QUALITY = CONSOLIDATION / "V20_109_EFFECTIVENESS_EVIDENCE_QUALITY_AUDIT.csv"
V109_GATE = CONSOLIDATION / "V20_109_NEXT_STAGE_GATE.csv"
R13_SUMMARY = CONSOLIDATION / "V20_108_R13_SHADOW_RERANK_DELTA_SUMMARY.csv"
R13_ATTR = CONSOLIDATION / "V20_108_R13_FACTOR_FAMILY_RANK_CHANGE_ATTRIBUTION.csv"
R13_MOVERS = CONSOLIDATION / "V20_108_R13_TOP_MOVER_EXPLAINABILITY_AUDIT.csv"
R13_OVERLAP = CONSOLIDATION / "V20_108_R13_BASELINE_VS_SHADOW_OVERLAP_AUDIT.csv"
R12_RERANK = CONSOLIDATION / "V20_108_R12_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK.csv"
R12_COMPONENT = CONSOLIDATION / "V20_108_R12_SHADOW_SCORE_COMPONENT_CONTRIBUTION_AUDIT.csv"
R107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
V105_HIST = CONSOLIDATION / "V20_105_FACTOR_FAMILY_HISTORICAL_EVIDENCE.csv"
V105_ABLATION = CONSOLIDATION / "V20_105_FACTOR_ABLATION_EVIDENCE_MATRIX.csv"
V106_REGIME = CONSOLIDATION / "V20_106_REGIME_CONDITIONED_FACTOR_ALIGNMENT.csv"
V104_FORWARD = CONSOLIDATION / "V20_104_RANDOM_ASOF_FORWARD_OUTCOME_MATRIX.csv"
V104_BENCH = CONSOLIDATION / "V20_104_RANDOM_ASOF_BENCHMARK_COMPARISON.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OUT_SUMMARY = CONSOLIDATION / "V20_109_R1_UNDERPERFORMANCE_DECOMPOSITION_SUMMARY.csv"
OUT_FAILURE = CONSOLIDATION / "V20_109_R1_FORWARD_WINDOW_TOPN_FAILURE_MAP.csv"
OUT_FACTOR = CONSOLIDATION / "V20_109_R1_FACTOR_FAMILY_FAILURE_ATTRIBUTION.csv"
OUT_BUCKET = CONSOLIDATION / "V20_109_R1_RANK_DELTA_BUCKET_EFFECTIVENESS_AUDIT.csv"
OUT_PLAN = CONSOLIDATION / "V20_109_R1_SHADOW_WEIGHT_REPAIR_PLAN.csv"
OUT_GATE = CONSOLIDATION / "V20_109_R1_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_109_R1_SHADOW_UNDERPERFORMANCE_DECOMPOSITION_AND_WEIGHT_REPAIR_PLAN_REPORT.md"

PASS_STATUS = "PASS_V20_109_R1_SHADOW_UNDERPERFORMANCE_DECOMPOSITION_AND_WEIGHT_REPAIR_PLAN"
PARTIAL_STATUS = "PARTIAL_PASS_V20_109_R1_UNDERPERFORMANCE_DECOMPOSITION_WITH_LIMITED_FORWARD_OUTCOME_COVERAGE"
BLOCKED_STATUS = "BLOCKED_V20_109_R1_MISSING_REQUIRED_EFFECTIVENESS_INPUTS"

FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
FAMILY_FIELD = {f: f"{f.lower()}_weighted_component" for f in FAMILIES}
FAMILY_FIELD["MARKET_REGIME"] = "market_regime_weighted_component"
WINDOWS = ["5D", "10D", "20D", "60D", "120D"]

SUMMARY_FIELDS = ["summary_id","strict_equity_candidate_count","evaluated_cell_count","shadow_outperformance_cell_count","baseline_outperformance_cell_count","mixed_or_inconclusive_cell_count","short_window_shadow_success_count","short_window_baseline_success_count","medium_window_shadow_success_count","medium_window_baseline_success_count","long_window_shadow_success_count","long_window_baseline_success_count","top10_shadow_success_count","top20_shadow_success_count","top50_shadow_success_count","top100_shadow_success_count","dominant_underperformance_area","underperformance_result_status","underperformance_result_reason","performance_effectiveness_claim_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","research_only","shadow_only","official_promotion_allowed","is_official_weight","weight_mutated"]
FAILURE_FIELDS = ["forward_window","top_n","baseline_mean_forward_return","shadow_mean_forward_return","shadow_minus_baseline_mean_return","baseline_median_forward_return","shadow_median_forward_return","shadow_minus_baseline_median_return","baseline_hit_rate","shadow_hit_rate","shadow_minus_baseline_hit_rate","risk_adjusted_delta","cell_effectiveness_status","cell_failure_severity","likely_failure_pattern","recommended_repair_focus","coverage_status","research_only","shadow_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
FACTOR_FIELDS = ["factor_family","shadow_dynamic_weight","average_weighted_component_in_shadow_top10","average_weighted_component_in_shadow_top20","average_weighted_component_in_shadow_top50","average_weighted_component_in_shadow_top100","average_forward_return_when_component_high","average_forward_return_when_component_low","component_effectiveness_status","suspected_overweight_or_underweight_status","recommended_weight_repair_direction","repair_direction_reason","diagnostic_only","research_only","shadow_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
BUCKET_FIELDS = ["rank_delta_bucket","candidate_count","average_rank_delta","average_shadow_score","forward_window","average_forward_return","median_forward_return","hit_rate","benchmark_relative_return","bucket_effectiveness_status","bucket_failure_reason","recommended_repair_action","diagnostic_only","research_only","shadow_only","official_promotion_allowed","official_recommendation_created","trade_action_created","broker_execution_supported"]
PLAN_FIELDS = ["repair_plan_id","repair_focus_area","repair_action_type","current_weight_or_rule","proposed_simulation_direction","proposed_weight_mutation_performed","proposed_rerank_created","evidence_basis","affected_forward_windows","affected_topn_groups","expected_next_test","repair_priority","safety_status","research_only","shadow_only","official_promotion_allowed","official_recommendation_created","is_official_weight","weight_mutated","trade_action_created","broker_execution_supported"]
GATE_FIELDS = ["gate_check_id","underperformance_decomposition_created","weight_repair_plan_created","new_weights_created","new_rerank_created","v20_110_acceptance_gate_allowed","v20_109_r2_weight_simulation_allowed","recommended_next_stage","blocking_reason","performance_effectiveness_claim_created","official_ranking_created","official_recommendation_created","trade_action_created","broker_execution_supported","research_only","shadow_only","official_promotion_allowed","is_official_weight","weight_mutated"]


def clean(v: object) -> str:
    return "" if v is None else str(v).strip()


def tf(v: bool) -> str:
    return "TRUE" if v else "FALSE"


def dec(v: str) -> Decimal | None:
    try:
        return Decimal(clean(v))
    except (InvalidOperation, ValueError):
        return None


def fmt(v: Decimal | float | None) -> str:
    if v is None:
        return ""
    return f"{float(v):.10f}"


def safety() -> dict[str, str]:
    return {"research_only":"TRUE","shadow_only":"TRUE","official_promotion_allowed":"FALSE","official_recommendation_created":"FALSE","trade_action_created":"FALSE","broker_execution_supported":"FALSE"}


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


def mean(vals: list[Decimal]) -> Decimal | None:
    return sum(vals, Decimal("0")) / Decimal(len(vals)) if vals else None


def med(vals: list[Decimal]) -> Decimal | None:
    return Decimal(str(median(vals))) if vals else None


def bucket(delta: int) -> str:
    if delta >= 50:
        return "BIG_IMPROVER"
    if delta > 0:
        return "MODERATE_IMPROVER"
    if delta == 0:
        return "UNCHANGED"
    if delta <= -50:
        return "BIG_WORSENER"
    return "MODERATE_WORSENER"


def main() -> int:
    summary_rows, _, s_status = read_csv(V109_SUMMARY)
    matrix, _, m_status = read_csv(V109_MATRIX)
    attr, _, a_status = read_csv(V109_ATTR)
    rerank, _, r_status = read_csv(R12_RERANK)
    weights, _, _ = read_csv(R107_WEIGHTS)
    forward, _, _ = read_csv(V104_FORWARD)
    valid = s_status == "OK" and m_status == "OK" and a_status == "OK" and r_status == "OK" and len(matrix) == 20 and len(rerank) == 297

    failure_rows = []
    shadow_success = baseline_success = mixed = 0
    short_s = short_b = med_s = med_b = long_s = long_b = 0
    top_success = {10:0, 20:0, 50:0, 100:0}
    fail_scores: dict[str, int] = {}
    for row in matrix:
        delta = dec(row.get("shadow_minus_baseline_mean_return", "")) or Decimal("0")
        status = "SHADOW_SUCCESS" if delta > 0 else "BASELINE_SUCCESS" if delta < 0 else "MIXED_OR_INCONCLUSIVE"
        if delta > 0:
            shadow_success += 1
        elif delta < 0:
            baseline_success += 1
        else:
            mixed += 1
        win = row["forward_window"]
        topn = int(row["top_n"])
        if delta > 0:
            top_success[topn] += 1
        if win in {"5D","10D"}:
            short_s += int(delta > 0); short_b += int(delta < 0)
        elif win == "20D":
            med_s += int(delta > 0); med_b += int(delta < 0)
        else:
            long_s += int(delta > 0); long_b += int(delta < 0)
        fail_scores[f"{win}_TOP{topn}"] = int(abs(delta) * Decimal("1000000")) if delta < 0 else 0
        severity = "HIGH" if delta < Decimal("-0.05") else "MEDIUM" if delta < 0 else "NONE"
        focus = "TOP_N_CONSERVATIVE_OVERLAY" if topn <= 20 and delta < 0 else "WINDOW_SPECIFIC_WEIGHT_SIMULATION" if delta < 0 else "PRESERVE_DIAGNOSTIC_PATTERN"
        failure_rows.append({
            "forward_window": win,
            "top_n": row["top_n"],
            "baseline_mean_forward_return": row["baseline_mean_forward_return"],
            "shadow_mean_forward_return": row["shadow_mean_forward_return"],
            "shadow_minus_baseline_mean_return": row["shadow_minus_baseline_mean_return"],
            "baseline_median_forward_return": row["baseline_median_forward_return"],
            "shadow_median_forward_return": row["shadow_median_forward_return"],
            "shadow_minus_baseline_median_return": row["shadow_minus_baseline_median_return"],
            "baseline_hit_rate": row["baseline_hit_rate"],
            "shadow_hit_rate": row["shadow_hit_rate"],
            "shadow_minus_baseline_hit_rate": row["shadow_minus_baseline_hit_rate"],
            "risk_adjusted_delta": row["risk_adjusted_delta"],
            "cell_effectiveness_status": status,
            "cell_failure_severity": severity,
            "likely_failure_pattern": "SHADOW_TOPN_UNDERPERFORMED_BASELINE" if delta < 0 else "SHADOW_TOPN_OUTPERFORMED_OR_FLAT",
            "recommended_repair_focus": focus,
            "coverage_status": row["coverage_status"],
            **safety(),
        })

    dominant_area = max(fail_scores, key=fail_scores.get) if fail_scores else ""
    out_status = "UNDERPERFORMANCE_DECOMPOSED_BASELINE_DOMINATED" if baseline_success > shadow_success else "MIXED_OR_SHADOW_FAVORABLE_DIAGNOSTIC"
    summary = [{
        "summary_id": "V20_109_R1_UNDERPERFORMANCE_SUMMARY_001",
        "strict_equity_candidate_count": "297",
        "evaluated_cell_count": str(len(matrix)),
        "shadow_outperformance_cell_count": str(shadow_success),
        "baseline_outperformance_cell_count": str(baseline_success),
        "mixed_or_inconclusive_cell_count": str(mixed),
        "short_window_shadow_success_count": str(short_s),
        "short_window_baseline_success_count": str(short_b),
        "medium_window_shadow_success_count": str(med_s),
        "medium_window_baseline_success_count": str(med_b),
        "long_window_shadow_success_count": str(long_s),
        "long_window_baseline_success_count": str(long_b),
        "top10_shadow_success_count": str(top_success[10]),
        "top20_shadow_success_count": str(top_success[20]),
        "top50_shadow_success_count": str(top_success[50]),
        "top100_shadow_success_count": str(top_success[100]),
        "dominant_underperformance_area": dominant_area,
        "underperformance_result_status": out_status,
        "underperformance_result_reason": "Research-only decomposition; no effectiveness claim and no weight mutation.",
        "performance_effectiveness_claim_created": "FALSE",
        "official_ranking_created": "FALSE",
        "official_recommendation_created": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        **safety(),
        "is_official_weight": "FALSE",
        "weight_mutated": "FALSE",
    }]

    # Factor failure attribution.
    weight_by = {w["factor_family"]: w.get("normalized_shadow_dynamic_weight") or w.get("shadow_dynamic_weight", "") for w in weights}
    attr_by = {a["ticker"]: a for a in read_csv(R13_ATTR)[0]}
    forward_by: dict[tuple[str,str], list[Decimal]] = {}
    strict = {r["ticker"] for r in rerank}
    for row in forward:
        val = dec(row.get("forward_return", ""))
        if row.get("ticker") in strict and row.get("forward_window") in WINDOWS and row.get("outcome_available") == "TRUE" and val is not None:
            forward_by.setdefault((row["ticker"], row["forward_window"]), []).append(val)
    factor_rows = []
    for fam in FAMILIES:
        field = FAMILY_FIELD[fam]
        vals = [(ticker, dec(a.get(field, "")) or Decimal("0")) for ticker, a in attr_by.items()]
        vals.sort(key=lambda x: x[1], reverse=True)
        high = {t for t,_ in vals[:max(1, len(vals)//4)]}
        low = {t for t,_ in vals[-max(1, len(vals)//4):]}
        high_returns = [v for t in high for w in WINDOWS for v in forward_by.get((t,w), [])]
        low_returns = [v for t in low for w in WINDOWS for v in forward_by.get((t,w), [])]
        high_mean, low_mean = mean(high_returns), mean(low_returns)
        status = "COMPONENT_HIGH_BUCKET_UNDERPERFORMED_LOW_BUCKET" if high_mean is not None and low_mean is not None and high_mean < low_mean else "COMPONENT_HIGH_BUCKET_NOT_CLEAR_FAILURE"
        direction = "SIMULATE_LOWER_WEIGHT" if status.endswith("UNDERPERFORMED_LOW_BUCKET") else "RETAIN_OR_TEST_SMALL_INCREASE"
        factor_rows.append({
            "factor_family": fam,
            "shadow_dynamic_weight": weight_by.get(fam, ""),
            "average_weighted_component_in_shadow_top10": fmt(mean([dec(attr_by[r["ticker"]].get(field,"")) or Decimal("0") for r in rerank if int(r["strict_equity_shadow_rank"]) <= 10])),
            "average_weighted_component_in_shadow_top20": fmt(mean([dec(attr_by[r["ticker"]].get(field,"")) or Decimal("0") for r in rerank if int(r["strict_equity_shadow_rank"]) <= 20])),
            "average_weighted_component_in_shadow_top50": fmt(mean([dec(attr_by[r["ticker"]].get(field,"")) or Decimal("0") for r in rerank if int(r["strict_equity_shadow_rank"]) <= 50])),
            "average_weighted_component_in_shadow_top100": fmt(mean([dec(attr_by[r["ticker"]].get(field,"")) or Decimal("0") for r in rerank if int(r["strict_equity_shadow_rank"]) <= 100])),
            "average_forward_return_when_component_high": fmt(high_mean),
            "average_forward_return_when_component_low": fmt(low_mean),
            "component_effectiveness_status": status,
            "suspected_overweight_or_underweight_status": "POSSIBLE_OVERWEIGHT" if direction == "SIMULATE_LOWER_WEIGHT" else "NO_CLEAR_OVERWEIGHT",
            "recommended_weight_repair_direction": direction,
            "repair_direction_reason": "Based on diagnostic high-vs-low component forward returns; simulation required.",
            "diagnostic_only": "TRUE",
            **safety(),
        })

    bucket_rows = []
    attr_rank = {r["ticker"]: r for r in rerank}
    for b in ["BIG_IMPROVER","MODERATE_IMPROVER","UNCHANGED","MODERATE_WORSENER","BIG_WORSENER"]:
        names = [r["ticker"] for r in rerank if bucket(int(r["shadow_rank_delta"])) == b]
        for win in WINDOWS:
            vals = [v for t in names for v in forward_by.get((t,win), [])]
            rd = [Decimal(attr_rank[t]["shadow_rank_delta"]) for t in names]
            scores = [dec(attr_rank[t]["shadow_dynamic_weighted_score"]) or Decimal("0") for t in names]
            avg = mean(vals)
            bucket_rows.append({
                "rank_delta_bucket": b,
                "candidate_count": str(len(names)),
                "average_rank_delta": fmt(mean(rd)),
                "average_shadow_score": fmt(mean(scores)),
                "forward_window": win,
                "average_forward_return": fmt(avg),
                "median_forward_return": fmt(med(vals)),
                "hit_rate": fmt((Decimal(sum(1 for v in vals if v > 0)) / Decimal(len(vals))) if vals else None),
                "benchmark_relative_return": "",
                "bucket_effectiveness_status": "BUCKET_FORWARD_RETURN_NEGATIVE" if avg is not None and avg < 0 else "BUCKET_FORWARD_RETURN_NON_NEGATIVE_OR_MISSING",
                "bucket_failure_reason": "Diagnostic rank-delta bucket forward outcomes; no causality claim.",
                "recommended_repair_action": "SIMULATE_RANK_DELTA_CAP" if "IMPROVER" in b and avg is not None and avg < 0 else "MONITOR_IN_WEIGHT_SIMULATION",
                "diagnostic_only": "TRUE",
                **safety(),
            })

    plan_rows = [
        ("R1_REPAIR_001","top_n_concentration","TOP_N_CONSERVATIVE_OVERLAY","current strict shadow rank only","test cap on top10/top20 promotions","failed top-N cells"),
        ("R1_REPAIR_002","rank_delta_magnitude","RANK_DELTA_CAP","no rank delta cap","simulate max promotion bucket limits","large baseline-to-shadow divergence"),
        ("R1_REPAIR_003","risk_component","LOWER_RISK_WEIGHT_SIMULATION",weight_by.get("RISK",""),"simulate lower risk weight","component attribution diagnostics"),
        ("R1_REPAIR_004","strategy_component","HIGHER_STRATEGY_WEIGHT_SIMULATION",weight_by.get("STRATEGY",""),"simulate higher strategy weight","setup quality may need stronger filter"),
        ("R1_REPAIR_005","fundamental_component","HIGHER_FUNDAMENTAL_WEIGHT_SIMULATION",weight_by.get("FUNDAMENTAL",""),"simulate higher fundamental weight","strict equity rerank still underperformed baseline"),
        ("R1_REPAIR_006","market_regime_component","LOWER_MARKET_REGIME_WEIGHT_SIMULATION",weight_by.get("MARKET_REGIME",""),"simulate lower market regime weight","regime mapping is current-context diagnostic"),
        ("R1_REPAIR_007","window_specificity","WINDOW_SPECIFIC_DYNAMIC_WEIGHTS","single weight vector","simulate short/medium/long window weights","failure concentration differs by window"),
        ("R1_REPAIR_008","evidence_coverage","MINIMUM_EVIDENCE_COVERAGE_THRESHOLD","partial coverage accepted","require full candidate-window coverage before claim","partial outcome coverage status"),
    ]
    plan = [{
        "repair_plan_id": pid,
        "repair_focus_area": area,
        "repair_action_type": typ,
        "current_weight_or_rule": cur,
        "proposed_simulation_direction": direction,
        "proposed_weight_mutation_performed": "FALSE",
        "proposed_rerank_created": "FALSE",
        "evidence_basis": basis,
        "affected_forward_windows": "5D;10D;20D;60D;120D",
        "affected_topn_groups": "10;20;50;100",
        "expected_next_test": "V20.109-R2_RESEARCH_ONLY_WEIGHT_REPAIR_SIMULATION",
        "repair_priority": "HIGH" if i < 3 else "MEDIUM",
        "safety_status": "RESEARCH_ONLY_PLAN_NO_MUTATION_NO_RERANK",
        **safety(),
        "is_official_weight": "FALSE",
        "weight_mutated": "FALSE",
    } for i, (pid, area, typ, cur, direction, basis) in enumerate(plan_rows)]

    coverage = summary_rows[0].get("evidence_coverage_status", "") if summary_rows else ""
    wrapper = PARTIAL_STATUS if "PARTIAL" in coverage else PASS_STATUS if valid else BLOCKED_STATUS
    gate = [{
        "gate_check_id": "V20_109_R1_NEXT_STAGE_GATE_001",
        "underperformance_decomposition_created": tf(valid),
        "weight_repair_plan_created": tf(valid),
        "new_weights_created": "FALSE",
        "new_rerank_created": "FALSE",
        "v20_110_acceptance_gate_allowed": "FALSE",
        "v20_109_r2_weight_simulation_allowed": tf(valid),
        "recommended_next_stage": "V20.109-R2_RESEARCH_ONLY_SHADOW_WEIGHT_REPAIR_SIMULATION",
        "blocking_reason": "" if valid else "MISSING_REQUIRED_EFFECTIVENESS_INPUTS",
        "performance_effectiveness_claim_created": "FALSE",
        "official_ranking_created": "FALSE",
        "official_recommendation_created": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        **safety(),
        "is_official_weight": "FALSE",
        "weight_mutated": "FALSE",
    }]

    write_csv(OUT_SUMMARY, SUMMARY_FIELDS, summary)
    write_csv(OUT_FAILURE, FAILURE_FIELDS, failure_rows)
    write_csv(OUT_FACTOR, FACTOR_FIELDS, factor_rows)
    write_csv(OUT_BUCKET, BUCKET_FIELDS, bucket_rows)
    write_csv(OUT_PLAN, PLAN_FIELDS, plan)
    write_csv(OUT_GATE, GATE_FIELDS, gate)

    report = [
        "# V20.109-R1 Shadow Underperformance Decomposition And Weight Repair Plan Report",
        "",
        "## Current Result",
        f"- wrapper_status: {wrapper}",
        "- strict_equity_candidate_count: 297",
        f"- shadow_outperformance_cell_count: {shadow_success}",
        f"- baseline_outperformance_cell_count: {baseline_success}",
        f"- dominant_underperformance_area: {dominant_area}",
        "- performance_effectiveness_claim_created: FALSE",
        "- new_weights_created: FALSE",
        "- new_rerank_created: FALSE",
        "- v20_110_acceptance_gate_allowed: FALSE",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")

    print(wrapper)
    print(f"EVALUATED_CELL_COUNT={len(matrix)}")
    print(f"SHADOW_OUTPERFORMANCE_CELL_COUNT={shadow_success}")
    print(f"BASELINE_OUTPERFORMANCE_CELL_COUNT={baseline_success}")
    print("NEW_WEIGHTS_CREATED=FALSE")
    print("NEW_RERANK_CREATED=FALSE")
    print("V20_110_ACCEPTANCE_GATE_ALLOWED=FALSE")
    print("PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED=FALSE")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("IS_OFFICIAL_WEIGHT=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print(f"OUTPUT_SUMMARY={OUT_SUMMARY.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_FAILURE_MAP={OUT_FAILURE.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_FACTOR_ATTRIBUTION={OUT_FACTOR.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_BUCKET_AUDIT={OUT_BUCKET.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_REPAIR_PLAN={OUT_PLAN.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_GATE={OUT_GATE.relative_to(ROOT).as_posix()}")
    print(f"OUTPUT_REPORT={REPORT.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
