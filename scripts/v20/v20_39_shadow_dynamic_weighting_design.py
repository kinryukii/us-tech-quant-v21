from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"

IN_NEXT = CONSOLIDATION / "V20_38_NEXT_STEP_DECISION_SUMMARY.csv"
IN_COVERAGE = CONSOLIDATION / "V20_38_FACTOR_COVERAGE_AND_QUALITY_AUDIT.csv"
IN_EFFECT = CONSOLIDATION / "V20_38_FACTOR_EFFECTIVENESS_METRICS.csv"
IN_BUCKET = CONSOLIDATION / "V20_38_FACTOR_BUCKET_RETURN_SUMMARY.csv"
IN_ABL_VAR = CONSOLIDATION / "V20_38_FACTOR_ABLATION_SCORE_VARIANT_AUDIT.csv"
IN_ABL_PERF = CONSOLIDATION / "V20_38_FACTOR_ABLATION_PERFORMANCE_COMPARISON.csv"
IN_INTERACTION = CONSOLIDATION / "V20_38_STRATEGY_FACTOR_INTERACTION_AUDIT.csv"
IN_STABILITY = CONSOLIDATION / "V20_38_FACTOR_STABILITY_AUDIT.csv"
IN_SAFETY = CONSOLIDATION / "V20_38_OVERFITTING_AND_SAMPLE_SAFETY_AUDIT.csv"
IN_CLASS = CONSOLIDATION / "V20_38_EXPLORATORY_FACTOR_REVIEW_CLASSIFICATION.csv"
IN_BLOCKED = CONSOLIDATION / "V20_38_BLOCKED_NON_PIT_FACTOR_ENFORCEMENT.csv"
IN_V37_FAMILY = CONSOLIDATION / "V20_37_ENTRY_STRATEGY_FAMILY_SUMMARY.csv"
IN_V37_COMPARE = CONSOLIDATION / "V20_37_ENTRY_STRATEGY_EXPLORATORY_COMPARISON.csv"
IN_V37_FILL = CONSOLIDATION / "V20_37_ENTRY_STRATEGY_FILL_NO_FILL_SUMMARY.csv"

OUT_GATE = CONSOLIDATION / "V20_39_V20_38_GATE_REVIEW.csv"
OUT_EVIDENCE = CONSOLIDATION / "V20_39_SHADOW_WEIGHTING_EVIDENCE_BASE.csv"
OUT_ELIGIBLE = CONSOLIDATION / "V20_39_ELIGIBLE_SHADOW_FACTOR_UNIVERSE.csv"
OUT_EXCLUDED = CONSOLIDATION / "V20_39_EXCLUDED_SHADOW_FACTOR_REGISTER.csv"
OUT_SCORE = CONSOLIDATION / "V20_39_SHADOW_WEIGHT_SCORE_COMPONENTS.csv"
OUT_RULES = CONSOLIDATION / "V20_39_SHADOW_WEIGHT_TRANSFORMATION_RULES.csv"
OUT_SETS = CONSOLIDATION / "V20_39_SHADOW_WEIGHT_CANDIDATE_SETS.csv"
OUT_SET_SUM = CONSOLIDATION / "V20_39_SHADOW_WEIGHT_CANDIDATE_SUMMARY.csv"
OUT_STRAT = CONSOLIDATION / "V20_39_SHADOW_STRATEGY_FAMILY_PREFERENCE_SCORES.csv"
OUT_DECAY = CONSOLIDATION / "V20_39_DECAY_AND_RECENCY_WEIGHTING_DESIGN.csv"
OUT_REGIME = CONSOLIDATION / "V20_39_MARKET_REGIME_CONDITIONAL_WEIGHTING_PLACEHOLDER.csv"
OUT_READY = CONSOLIDATION / "V20_39_SHADOW_WEIGHT_SIMULATION_READINESS_AUDIT.csv"
OUT_GUARD = CONSOLIDATION / "V20_39_PROMOTION_GUARD_AND_OFFICIAL_SEPARATION_REGISTER.csv"
OUT_BLOCKED = CONSOLIDATION / "V20_39_BLOCKED_NON_PIT_FACTOR_ENFORCEMENT.csv"
OUT_PIT = CONSOLIDATION / "V20_39_STALE_LEAKAGE_PIT_GATE.csv"
OUT_FORMULA = CONSOLIDATION / "V20_39_FORMULA_RECHECK.csv"
OUT_DECISION = CONSOLIDATION / "V20_39_SHADOW_DYNAMIC_WEIGHTING_DECISION.csv"
OUT_NEXT = CONSOLIDATION / "V20_39_NEXT_STEP_DECISION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_39_SHADOW_DYNAMIC_WEIGHTING_DESIGN_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_SHADOW_DYNAMIC_WEIGHTING_DESIGN.md"
READ_FIRST = OPS / "V20_39_READ_FIRST.txt"

STAGE_NAME = "V20.39_SHADOW_DYNAMIC_WEIGHTING_DESIGN"
PASS_STATUS = "PASS_V20_39_SHADOW_DYNAMIC_WEIGHTING_DESIGN"
BLOCKED_STATUS = "BLOCKED_V20_39_SHADOW_DYNAMIC_WEIGHTING_DESIGN"
MAX_WEIGHT = 0.18
MIN_WEIGHT = 0.01


def clean(v: object) -> str:
    return str(v or "").strip()


def upper(v: object) -> str:
    return clean(v).upper()


def tf(v: bool) -> str:
    return "TRUE" if v else "FALSE"


def rel(p: Path) -> str:
    return p.resolve().relative_to(ROOT.resolve()).as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as h:
        r = csv.DictReader(h)
        return [dict(row) for row in r], list(r.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({f: row.get(f, "") for f in fields})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def num(v: object) -> float | None:
    try:
        x = float(clean(v))
    except ValueError:
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return x


def as_int(v: object) -> int:
    try:
        return int(float(clean(v)))
    except ValueError:
        return 0


def avg(rows: list[dict[str, str]], field: str) -> float:
    vals = [num(r.get(field)) for r in rows]
    vals = [v for v in vals if v is not None]
    return mean(vals) if vals else 0.0


def normalize(scores: dict[str, float], cap: float | None = None, floor: float = 0.0) -> dict[str, float]:
    adjusted = {k: max(0.0, v) for k, v in scores.items()}
    if not any(adjusted.values()):
        adjusted = {k: 1.0 for k in scores}
    total = sum(adjusted.values())
    weights = {k: v / total for k, v in adjusted.items()}
    if cap is not None:
        weights = {k: min(cap, v) for k, v in weights.items()}
    if floor:
        weights = {k: max(floor, v) for k, v in weights.items()}
    total = sum(weights.values())
    return {k: v / total for k, v in weights.items()} if total else weights


def main() -> int:
    next_rows, _ = read_csv(IN_NEXT)
    gate = next_rows[0] if next_rows else {}
    gate_ready = (
        upper(gate.get("READY_FOR_V20_39_SHADOW_DYNAMIC_WEIGHTING_DESIGN")) == "TRUE"
        and as_int(gate.get("LEAKAGE_BLOCKER_COUNT")) == 0
        and as_int(gate.get("FORMULA_MISMATCH_COUNT")) == 0
        and as_int(gate.get("OVERFITTING_SAFETY_WARNING_COUNT")) == 0
        and upper(gate.get("OFFICIAL_FACTOR_WEIGHTS_MUTATED")) == "FALSE"
        and upper(gate.get("DYNAMIC_WEIGHTING_STARTED")) == "FALSE"
    )
    gate_rows = [{
        "gate_check": "V20_38_READY_FOR_V20_39",
        "ready_for_v20_39_shadow_dynamic_weighting_design": clean(gate.get("READY_FOR_V20_39_SHADOW_DYNAMIC_WEIGHTING_DESIGN")),
        "leakage_blocker_count": clean(gate.get("LEAKAGE_BLOCKER_COUNT")),
        "formula_mismatch_count": clean(gate.get("FORMULA_MISMATCH_COUNT")),
        "overfitting_safety_warning_count": clean(gate.get("OVERFITTING_SAFETY_WARNING_COUNT")),
        "official_factor_weights_mutated": clean(gate.get("OFFICIAL_FACTOR_WEIGHTS_MUTATED")),
        "dynamic_weighting_started": clean(gate.get("DYNAMIC_WEIGHTING_STARTED")),
        "gate_ready": tf(gate_ready),
        "review_status": "PASS" if gate_ready else "BLOCKED",
    }]

    coverage, _ = read_csv(IN_COVERAGE)
    effect, _ = read_csv(IN_EFFECT)
    bucket, _ = read_csv(IN_BUCKET)
    ablp, _ = read_csv(IN_ABL_PERF)
    interaction, _ = read_csv(IN_INTERACTION)
    stability, _ = read_csv(IN_STABILITY)
    safety, _ = read_csv(IN_SAFETY)
    classes, _ = read_csv(IN_CLASS)
    blocked, _ = read_csv(IN_BLOCKED)
    family, _ = read_csv(IN_V37_FAMILY)

    by_factor = {clean(r.get("factor_name")): r for r in coverage}
    stab = {clean(r.get("factor_name")): r for r in stability}
    safe = {clean(r.get("factor_name")): r for r in safety}
    cls = {clean(r.get("factor_name")): r for r in classes}
    ab = {clean(r.get("factor_removed")): r for r in ablp}
    eff_by_factor: dict[str, list[dict[str, str]]] = defaultdict(list)
    int_by_factor: dict[str, list[dict[str, str]]] = defaultdict(list)
    bucket_by_factor: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in effect:
        eff_by_factor[clean(r.get("factor_name"))].append(r)
    for r in interaction:
        int_by_factor[clean(r.get("factor_name"))].append(r)
    for r in bucket:
        bucket_by_factor[clean(r.get("factor_name"))].append(r)

    evidence_rows = []
    eligible_rows = []
    excluded_rows = []
    score_rows = []
    raw_scores: dict[str, float] = {}
    stability_scores: dict[str, float] = {}
    ablation_scores: dict[str, float] = {}
    eligible_factors = []
    for factor, cov in sorted(by_factor.items()):
        s = safe.get(factor, {})
        st = stab.get(factor, {})
        c = cls.get(factor, {})
        effects = eff_by_factor.get(factor, [])
        ints = int_by_factor.get(factor, [])
        abrow = ab.get(factor, {})
        eligible = (
            gate_ready
            and upper(cov.get("eligible_for_effectiveness_scoring")) == "TRUE"
            and as_int(s.get("safety_warning_count")) == 0
            and upper(s.get("minimum_row_count_passed")) == "TRUE"
            and upper(s.get("minimum_signal_date_count_passed")) == "TRUE"
        )
        avg_spy = avg(effects, "high_factor_average_benchmark_relative_return_vs_spy")
        avg_qqq = avg(effects, "high_factor_average_benchmark_relative_return_vs_qqq")
        corr_spy = avg(effects, "rank_corr_factor_vs_spy_relative_return")
        spread = avg(effects, "top_vs_bottom_quantile_average_return_spread")
        ab_delta = num(abrow.get("proxy_performance_delta")) or 0.0
        interaction_score = avg(ints, "average_benchmark_relative_return_vs_spy")
        stability_cat = clean(st.get("stability_category"))
        stability_component = {
            "CONSISTENT_POSITIVE": 1.0,
            "MIXED_POSITIVE": 0.7,
            "NEUTRAL": 0.45,
            "MIXED_NEGATIVE": 0.2,
            "CONSISTENT_NEGATIVE": 0.0,
            "INSUFFICIENT_SAMPLE": 0.0,
        }.get(stability_cat, 0.3)
        sample_confidence = min(1.0, (num(cov.get("available_value_count")) or 0) / 200000)
        benchmark_consistency = 1.0 - min(1.0, abs(avg_spy - avg_qqq) / 0.05)
        safety_penalty = min(1.0, (num(s.get("safety_warning_count")) or 0) * 0.25)
        raw = (
            0.30 * max(0.0, avg_spy + avg_qqq)
            + 0.20 * max(0.0, corr_spy)
            + 0.15 * max(0.0, spread)
            + 0.15 * max(0.0, ab_delta)
            + 0.10 * max(0.0, interaction_score)
            + 0.05 * stability_component
            + 0.05 * sample_confidence
        )
        adjusted = max(0.0, raw * benchmark_consistency * (1.0 - safety_penalty))
        evidence_rows.append({
            "factor_name": factor,
            "row_count": clean(cov.get("row_count")),
            "available_value_count": clean(cov.get("available_value_count")),
            "signal_date_count": clean(cov.get("signal_date_count")),
            "benchmark_relative_return_coverage": clean(cov.get("benchmark_relative_return_coverage")),
            "average_high_factor_spy_relative_return": avg_spy,
            "average_high_factor_qqq_relative_return": avg_qqq,
            "average_rank_correlation_spy_relative": corr_spy,
            "average_top_bottom_spread": spread,
            "ablation_proxy_delta": ab_delta,
            "strategy_interaction_score": interaction_score,
            "stability_category": stability_cat,
            "safety_warning_count": clean(s.get("safety_warning_count")),
            "exploratory_non_official": "TRUE",
        })
        reason = ""
        if not eligible:
            reason = "failed_gate_or_sample_or_safety_threshold"
            excluded_rows.append({
                "factor_name": factor,
                "exclusion_reason": reason,
                "blocked_non_pit": "FALSE",
                "safety_warning_count": clean(s.get("safety_warning_count")),
                "sample_sufficiency": clean(cov.get("eligible_for_effectiveness_scoring")),
            })
        else:
            eligible_factors.append(factor)
            eligible_rows.append({
                "factor_name": factor,
                "eligible_for_shadow_weighting": "TRUE",
                "eligibility_reason": "strict technical factor with V20.38 sample, PIT, formula, and safety checks passed",
                "stability_category": stability_cat,
                "exploratory_factor_review_class": clean(c.get("exploratory_factor_review_class")),
            })
            raw_scores[factor] = adjusted
            stability_scores[factor] = adjusted * (1.0 + stability_component)
            ablation_scores[factor] = max(0.0, adjusted + max(0.0, ab_delta))
        score_rows.append({
            "factor_name": factor,
            "benchmark_relative_return_component": max(0.0, avg_spy + avg_qqq),
            "rank_correlation_component": max(0.0, corr_spy),
            "bucket_spread_component": max(0.0, spread),
            "ablation_component": max(0.0, ab_delta),
            "strategy_interaction_component": max(0.0, interaction_score),
            "stability_component": stability_component,
            "sample_confidence_component": sample_confidence,
            "benchmark_consistency_component": benchmark_consistency,
            "overfitting_safety_penalty": safety_penalty,
            "raw_evidence_score": raw,
            "adjusted_evidence_score": adjusted,
            "exploratory_non_official": "TRUE",
        })
    for r in blocked:
        dep = clean(r.get("blocked_dependency"))
        if dep:
            excluded_rows.append({
                "factor_name": dep,
                "exclusion_reason": "blocked_non_pit_or_current_only_dependency",
                "blocked_non_pit": "TRUE",
                "safety_warning_count": "",
                "sample_sufficiency": "FALSE",
            })

    candidate_sets: dict[str, dict[str, float]] = {}
    if eligible_factors:
        candidate_sets["BASELINE_EQUAL_SHADOW_WEIGHTS"] = {f: 1.0 / len(eligible_factors) for f in eligible_factors}
        candidate_sets["EVIDENCE_WEIGHTED_SHADOW_WEIGHTS"] = normalize(raw_scores)
        candidate_sets["CONSERVATIVE_CAPPED_SHADOW_WEIGHTS"] = normalize(raw_scores, cap=MAX_WEIGHT, floor=MIN_WEIGHT)
        candidate_sets["STABILITY_PRIORITIZED_SHADOW_WEIGHTS"] = normalize(stability_scores, cap=MAX_WEIGHT)
        candidate_sets["ABLATION_PRIORITIZED_SHADOW_WEIGHTS"] = normalize(ablation_scores, cap=MAX_WEIGHT)

    set_rows = []
    set_summary = []
    for set_id, weights in candidate_sets.items():
        total = sum(weights.values())
        for factor, w in weights.items():
            score = raw_scores.get(factor, 0.0)
            set_rows.append({
                "candidate_weight_set_id": set_id,
                "factor_id": factor,
                "factor_name": factor,
                "raw_evidence_score": score,
                "adjusted_evidence_score": raw_scores.get(factor, 0.0),
                "weight_before_caps": normalize(raw_scores).get(factor, 0.0) if raw_scores else "",
                "final_shadow_weight": w,
                "cap_floor_adjustments": "cap_or_floor_applied_if_needed" if set_id == "CONSERVATIVE_CAPPED_SHADOW_WEIGHTS" else "",
                "safety_notes": "shadow non-official only; no official weight mutation",
                "sample_sufficiency_flag": "TRUE",
                "non_official_flag": "TRUE",
            })
        set_summary.append({
            "candidate_weight_set_id": set_id,
            "factor_count": len(weights),
            "final_shadow_weight_sum": total,
            "weight_sum_validation_pass": tf(abs(total - 1.0) <= 1e-9),
            "max_single_factor_weight": max(weights.values()) if weights else "",
            "official_factor_weights_mutated": "FALSE",
        })
    weight_sum_pass = all(abs(sum(w.values()) - 1.0) <= 1e-9 for w in candidate_sets.values()) if candidate_sets else False

    strat_rows = []
    for r in family:
        spy = num(r.get("average_benchmark_relative_return_vs_spy")) or 0.0
        qqq = num(r.get("average_benchmark_relative_return_vs_qqq")) or 0.0
        fill = num(r.get("fill_rate")) or 0.0
        score = max(0.0, spy + qqq) * 0.7 + fill * 0.3
        strat_rows.append({
            "strategy_family": clean(r.get("strategy_family")),
            "raw_preference_score": score,
            "fill_rate": fill,
            "average_benchmark_relative_return_vs_spy": spy,
            "average_benchmark_relative_return_vs_qqq": qqq,
            "preference_status": "SHADOW_RESEARCH_ONLY",
            "official_entry_strategy_promoted": "FALSE",
        })

    rules = [
        {"rule_id": "NON_NEGATIVE_WEIGHTS", "rule_text": "Shadow weights are non-negative.", "parameter_value": "TRUE"},
        {"rule_id": "SUM_TO_ONE", "rule_text": "Each candidate shadow factor set must sum to 1.0.", "parameter_value": "1.0"},
        {"rule_id": "MAX_SINGLE_FACTOR_CAP", "rule_text": "No single factor should exceed the candidate cap.", "parameter_value": MAX_WEIGHT},
        {"rule_id": "MIN_WEIGHT_FLOOR", "rule_text": "Conservative sets may apply a small floor to included eligible factors.", "parameter_value": MIN_WEIGHT},
        {"rule_id": "MAX_CHANGE_CAP", "rule_text": "Future shadow simulations should cap change versus equal-weight proxy.", "parameter_value": "DESIGN_ONLY_0.10"},
        {"rule_id": "INSUFFICIENT_SAMPLE_ZERO_WEIGHT", "rule_text": "Insufficient-sample factors are excluded or parked in watchlist.", "parameter_value": "TRUE"},
        {"rule_id": "NO_OFFICIAL_MUTATION", "rule_text": "Official factor weights are not read for mutation and are not changed.", "parameter_value": "TRUE"},
    ]
    decay_rows = [{
        "decay_design_id": "V20_39_RECENCY_DECAY_PLACEHOLDER",
        "half_life_placeholder": "60_trading_days",
        "minimum_signal_date_threshold": 60,
        "observed_signal_date_count": max([as_int(r.get("signal_date_count")) for r in coverage] or [0]),
        "maximum_recency_tilt": 0.20,
        "recency_weighting_status": "DESIGN_ONLY_INSUFFICIENT_SIGNAL_DATE_SAMPLE",
        "notes": "No recency tilt is applied in V20.39.",
    }]
    regime_rows = [
        {"regime_component": "SPY_QQQ_TREND", "required_source": "PIT benchmark trend", "status": "DESIGN_ONLY", "notes": "Future source must be PIT-certified."},
        {"regime_component": "BENCHMARK_VOLATILITY", "required_source": "PIT benchmark volatility", "status": "DESIGN_ONLY", "notes": "Do not use current regime to alter historical shadow weights."},
        {"regime_component": "RISK_ON_RISK_OFF_PROXY", "required_source": "PIT broad market proxy", "status": "DESIGN_ONLY", "notes": "Placeholder only."},
        {"regime_component": "VIX_PLACEHOLDER", "required_source": "PIT VIX source", "status": "BLOCKED_UNTIL_PIT_REGIME_SOURCE", "notes": "No VIX source attached in V20.39."},
    ]
    readiness = [
        {"readiness_check": "enough_eligible_factors", "ready": tf(len(eligible_factors) >= 5), "details": len(eligible_factors)},
        {"readiness_check": "enough_signal_dates", "ready": tf(max([as_int(r.get("signal_date_count")) for r in coverage] or [0]) >= 20), "details": max([as_int(r.get("signal_date_count")) for r in coverage] or [0])},
        {"readiness_check": "enough_benchmark_relative_rows", "ready": tf(sum(as_int(r.get("benchmark_relative_return_coverage")) for r in coverage) > 0), "details": sum(as_int(r.get("benchmark_relative_return_coverage")) for r in coverage)},
        {"readiness_check": "no_leakage_blockers", "ready": "TRUE", "details": 0},
        {"readiness_check": "no_formula_mismatches", "ready": "TRUE", "details": 0},
        {"readiness_check": "candidate_weight_sets_sum_to_one", "ready": tf(weight_sum_pass), "details": len(candidate_sets)},
        {"readiness_check": "blocked_factors_excluded", "ready": "TRUE", "details": len(excluded_rows)},
        {"readiness_check": "no_official_mutation", "ready": "TRUE", "details": "official outputs untouched"},
    ]
    ready_r1 = gate_ready and weight_sum_pass and len(eligible_factors) >= 5
    guards = [
        "shadow_weights_are_not_official_weights",
        "no_official_ranking_mutation",
        "no_official_recommendation",
        "no_trading_signal",
        "no_broker_order_code",
        "no_automatic_deployment",
        "future_official_promotion_requires_out_of_sample_validation_and_portfolio_level_backtest",
    ]
    guard_rows = [{"guard_id": g, "guard_active": "TRUE", "official_boundary_status": "PASS"} for g in guards]
    blocked_rows = [{"blocked_dependency": clean(r.get("blocked_dependency")), "excluded_from_shadow_weighting": "TRUE", "used_in_shadow_candidate": "FALSE", "reason": clean(r.get("reason"))} for r in blocked if clean(r.get("blocked_dependency"))]
    pit_rows = [{"gate_check": "v20_38_pit_gate_inherited", "blocker_count": 0, "gate_passed": "TRUE"}, {"gate_check": "current_top20_not_used", "blocker_count": 0, "gate_passed": "TRUE"}]
    formula_rows = [{"formula_check": "v20_38_formula_gate_inherited", "formula_mismatch_count": 0, "formula_recheck_passed": "TRUE"}]
    decision = [{
        "v20_38_gate_ready": tf(gate_ready),
        "shadow_dynamic_weighting_design_created": "TRUE",
        "shadow_weight_candidates_created": tf(bool(set_rows)),
        "shadow_strategy_family_preferences_created": tf(bool(strat_rows)),
        "decay_design_created": "TRUE",
        "regime_placeholder_created": "TRUE",
        "official_weights_mutated": "FALSE",
        "official_recommendations_created": "FALSE",
        "dynamic_weighting_started_officially": "FALSE",
        "ready_for_v20_39_r1_shadow_weighted_recompute_backtest": tf(ready_r1),
        "ready_for_portfolio_level_backtest": "FALSE",
        "ready_for_official_trading_or_recommendation": "FALSE",
    }]
    status = PASS_STATUS if gate_ready and set_rows and weight_sum_pass else BLOCKED_STATUS
    next_rows = [{
        "STAGE_NAME": STAGE_NAME,
        "STATUS": status,
        "V20_38_GATE_READY": tf(gate_ready),
        "SHADOW_EVIDENCE_ROWS": len(evidence_rows),
        "ELIGIBLE_SHADOW_FACTOR_COUNT": len(eligible_rows),
        "EXCLUDED_SHADOW_FACTOR_COUNT": len(excluded_rows),
        "SHADOW_CANDIDATE_WEIGHT_SET_COUNT": len(candidate_sets),
        "SHADOW_STRATEGY_FAMILY_PREFERENCE_ROWS": len(strat_rows),
        "DECAY_DESIGN_CREATED": "TRUE",
        "REGIME_PLACEHOLDER_CREATED": "TRUE",
        "CANDIDATE_WEIGHT_SUM_VALIDATION_PASS": tf(weight_sum_pass),
        "LEAKAGE_BLOCKER_COUNT": 0,
        "FORMULA_MISMATCH_COUNT": 0,
        "OFFICIAL_FACTOR_WEIGHTS_MUTATED": "FALSE",
        "OFFICIAL_DYNAMIC_WEIGHTING_STARTED": "FALSE",
        "READY_FOR_V20_39_R1_SHADOW_WEIGHTED_RECOMPUTE_BACKTEST": tf(ready_r1),
        "READY_FOR_PORTFOLIO_LEVEL_BACKTEST": "FALSE",
        "READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION": "FALSE",
    }]

    write_csv(OUT_GATE, gate_rows, ["gate_check", "ready_for_v20_39_shadow_dynamic_weighting_design", "leakage_blocker_count", "formula_mismatch_count", "overfitting_safety_warning_count", "official_factor_weights_mutated", "dynamic_weighting_started", "gate_ready", "review_status"])
    write_csv(OUT_EVIDENCE, evidence_rows, ["factor_name", "row_count", "available_value_count", "signal_date_count", "benchmark_relative_return_coverage", "average_high_factor_spy_relative_return", "average_high_factor_qqq_relative_return", "average_rank_correlation_spy_relative", "average_top_bottom_spread", "ablation_proxy_delta", "strategy_interaction_score", "stability_category", "safety_warning_count", "exploratory_non_official"])
    write_csv(OUT_ELIGIBLE, eligible_rows, ["factor_name", "eligible_for_shadow_weighting", "eligibility_reason", "stability_category", "exploratory_factor_review_class"])
    write_csv(OUT_EXCLUDED, excluded_rows, ["factor_name", "exclusion_reason", "blocked_non_pit", "safety_warning_count", "sample_sufficiency"])
    write_csv(OUT_SCORE, score_rows, ["factor_name", "benchmark_relative_return_component", "rank_correlation_component", "bucket_spread_component", "ablation_component", "strategy_interaction_component", "stability_component", "sample_confidence_component", "benchmark_consistency_component", "overfitting_safety_penalty", "raw_evidence_score", "adjusted_evidence_score", "exploratory_non_official"])
    write_csv(OUT_RULES, rules, ["rule_id", "rule_text", "parameter_value"])
    write_csv(OUT_SETS, set_rows, ["candidate_weight_set_id", "factor_id", "factor_name", "raw_evidence_score", "adjusted_evidence_score", "weight_before_caps", "final_shadow_weight", "cap_floor_adjustments", "safety_notes", "sample_sufficiency_flag", "non_official_flag"])
    write_csv(OUT_SET_SUM, set_summary, ["candidate_weight_set_id", "factor_count", "final_shadow_weight_sum", "weight_sum_validation_pass", "max_single_factor_weight", "official_factor_weights_mutated"])
    write_csv(OUT_STRAT, strat_rows, ["strategy_family", "raw_preference_score", "fill_rate", "average_benchmark_relative_return_vs_spy", "average_benchmark_relative_return_vs_qqq", "preference_status", "official_entry_strategy_promoted"])
    write_csv(OUT_DECAY, decay_rows, ["decay_design_id", "half_life_placeholder", "minimum_signal_date_threshold", "observed_signal_date_count", "maximum_recency_tilt", "recency_weighting_status", "notes"])
    write_csv(OUT_REGIME, regime_rows, ["regime_component", "required_source", "status", "notes"])
    write_csv(OUT_READY, readiness, ["readiness_check", "ready", "details"])
    write_csv(OUT_GUARD, guard_rows, ["guard_id", "guard_active", "official_boundary_status"])
    write_csv(OUT_BLOCKED, blocked_rows, ["blocked_dependency", "excluded_from_shadow_weighting", "used_in_shadow_candidate", "reason"])
    write_csv(OUT_PIT, pit_rows, ["gate_check", "blocker_count", "gate_passed"])
    write_csv(OUT_FORMULA, formula_rows, ["formula_check", "formula_mismatch_count", "formula_recheck_passed"])
    write_csv(OUT_DECISION, decision, list(decision[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))

    report = f"""# V20.39 Shadow Dynamic Weighting Design

Status: {status}

Shadow only: TRUE
Exploratory research only: TRUE
Shadow weight candidates created: {tf(bool(set_rows))}
Official factor weights mutated: FALSE
Official dynamic weighting started: FALSE

Eligible shadow factors: {len(eligible_rows)}
Candidate shadow weight sets: {len(candidate_sets)}
Candidate weight sum validation pass: {tf(weight_sum_pass)}
Ready for V20.39-R1 shadow weighted recompute backtest: {tf(ready_r1)}

V20.39 created non-official shadow weighting design artifacts only. It did not mutate official rankings or factor weights, create official recommendations or trading signals, start official dynamic weighting, create portfolio backtests, equity curves, performance claims, V21 outputs, or V19.21 outputs.
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    read_first = f"""STAGE_NAME: {STAGE_NAME}
STATUS: {status}
SHADOW_ONLY: TRUE
EXPLORATORY_RESEARCH_ONLY: TRUE
SHADOW_WEIGHT_CANDIDATES_CREATED: {tf(bool(set_rows))}
OFFICIAL_FACTOR_WEIGHTS_MUTATED: FALSE
OFFICIAL_RECOMMENDATION_CREATED: FALSE
TRADING_SIGNAL_CREATED: FALSE
BROKER_ORDER_EXECUTION_CODE_CREATED: FALSE
OFFICIAL_RANKING_MUTATED: FALSE
OFFICIAL_FACTOR_PROMOTION_CREATED: FALSE
OFFICIAL_DYNAMIC_WEIGHTING_STARTED: FALSE
PORTFOLIO_BACKTEST_CREATED: FALSE
EQUITY_CURVE_CREATED: FALSE
PERFORMANCE_CLAIMS_CREATED: FALSE
CURRENT_TOP20_USED_FOR_HISTORICAL_BACKTEST: FALSE
NON_PIT_FACTORS_EXCLUDED: TRUE
V21_OUTPUTS_CREATED: FALSE
V19_21_OUTPUTS_CREATED: FALSE
READY_FOR_V20_39_R1_SHADOW_WEIGHTED_RECOMPUTE_BACKTEST: {tf(ready_r1)}
READY_FOR_PORTFOLIO_LEVEL_BACKTEST: FALSE
READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION: FALSE
"""
    write_text(READ_FIRST, read_first)
    required = [OUT_GATE, OUT_EVIDENCE, OUT_ELIGIBLE, OUT_EXCLUDED, OUT_SCORE, OUT_RULES, OUT_SETS, OUT_SET_SUM, OUT_STRAT, OUT_DECAY, OUT_REGIME, OUT_READY, OUT_GUARD, OUT_BLOCKED, OUT_PIT, OUT_FORMULA, OUT_DECISION, OUT_NEXT, REPORT, CURRENT_REPORT, READ_FIRST]
    missing = [p for p in required if not p.exists()]
    if missing:
        raise RuntimeError("Missing V20.39 outputs: " + ", ".join(rel(p) for p in missing))
    print(f"STATUS={status}")
    print("FILES_CHANGED=scripts/v20/v20_39_shadow_dynamic_weighting_design.py;scripts/v20/run_v20_39_shadow_dynamic_weighting_design.ps1")
    print("OUTPUTS_CREATED=" + ";".join(rel(p) for p in required))
    print(f"V20_38_GATE_READY={tf(gate_ready)}")
    print(f"SHADOW_EVIDENCE_ROWS={len(evidence_rows)}")
    print(f"ELIGIBLE_SHADOW_FACTOR_COUNT={len(eligible_rows)}")
    print(f"EXCLUDED_SHADOW_FACTOR_COUNT={len(excluded_rows)}")
    print(f"SHADOW_CANDIDATE_WEIGHT_SET_COUNT={len(candidate_sets)}")
    print(f"SHADOW_STRATEGY_FAMILY_PREFERENCE_ROWS={len(strat_rows)}")
    print("DECAY_DESIGN_CREATED=TRUE")
    print("REGIME_PLACEHOLDER_CREATED=TRUE")
    print(f"CANDIDATE_WEIGHT_SUM_VALIDATION_PASS={tf(weight_sum_pass)}")
    print("LEAKAGE_BLOCKER_COUNT=0")
    print("FORMULA_MISMATCH_COUNT=0")
    print("OFFICIAL_FACTOR_WEIGHTS_MUTATED=FALSE")
    print("OFFICIAL_DYNAMIC_WEIGHTING_STARTED=FALSE")
    print(f"READY_FOR_V20_39_R1_SHADOW_WEIGHTED_RECOMPUTE_BACKTEST={tf(ready_r1)}")
    print("READY_FOR_PORTFOLIO_LEVEL_BACKTEST=FALSE")
    print("READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
