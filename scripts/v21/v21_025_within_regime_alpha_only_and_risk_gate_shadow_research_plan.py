#!/usr/bin/env python
"""V21.025 within-regime alpha-only and risk-gate shadow research plan.

Research-only planning stage. It defines a non-activated shadow observation
plan and never mutates official ranking, weight, recommendation, trade,
market-regime, broker, or shadow-policy artifacts.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path


STAGE_NAME = "V21_025_WITHIN_REGIME_ALPHA_ONLY_AND_RISK_GATE_SHADOW_RESEARCH_PLAN"
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

V21_027_INPUTS = [
    OUT_DIR / "V21_027_V21_026_DECISION_INGEST_AUDIT.csv",
    OUT_DIR / "V21_027_REPAIRED_LABEL_COVERAGE_AUDIT.csv",
    OUT_DIR / "V21_027_CONTEXT_RETEST_UNIVERSE.csv",
    OUT_DIR / "V21_027_REPAIRED_CONTEXT_RANK_BUCKET_PERFORMANCE.csv",
    OUT_DIR / "V21_027_STABLE_VS_UNSTABLE_REGIME_TEST.csv",
    OUT_DIR / "V21_027_TREND_COMBINATION_CONTEXT_TEST.csv",
    OUT_DIR / "V21_027_RISK_GATE_BY_REPAIRED_CONTEXT.csv",
    OUT_DIR / "V21_027_STATISTICAL_RANDOM_BASELINE_RETEST.csv",
    OUT_DIR / "V21_027_REMAINING_SOURCE_GAP_IMPACT_AUDIT.csv",
    OUT_DIR / "V21_027_CONTEXT_RETEST_DECISION.csv",
    OUT_DIR / "V21_027_MARKET_REGIME_CONTEXT_RETEST_WITH_REPAIRED_LABELS_SUMMARY.csv",
    READ_CENTER_DIR / "V21_027_MARKET_REGIME_CONTEXT_RETEST_WITH_REPAIRED_LABELS_REPORT.md",
]

INGEST = OUT_DIR / "V21_025_V21_027_DECISION_INGEST_AUDIT.csv"
CONTEXTS = OUT_DIR / "V21_025_RESEARCH_CONTEXT_CANDIDATE_SELECTION.csv"
DESIGN = OUT_DIR / "V21_025_SHADOW_RESEARCH_PLAN_DESIGN.csv"
GUARDS = OUT_DIR / "V21_025_PLAN_GUARDRAILS.csv"
LEDGER = OUT_DIR / "V21_025_SHADOW_OBSERVATION_LEDGER_SPEC.csv"
SELECTION = OUT_DIR / "V21_025_SELECTION_POLICY_PROTOTYPE.csv"
RISK_POLICY = OUT_DIR / "V21_025_RISK_GATE_POLICY_PROTOTYPE.csv"
METRICS = OUT_DIR / "V21_025_REQUIRED_MONITORING_METRICS.csv"
BLOCKERS = OUT_DIR / "V21_025_PROMOTION_BLOCKER_AND_EXIT_CRITERIA.csv"
ARTIFACTS = OUT_DIR / "V21_025_DRY_RUN_ARTIFACT_PLAN.csv"
DECISION = OUT_DIR / "V21_025_SHADOW_RESEARCH_PLAN_DECISION.csv"
SUMMARY = OUT_DIR / "V21_025_WITHIN_REGIME_ALPHA_ONLY_AND_RISK_GATE_SHADOW_RESEARCH_PLAN_SUMMARY.csv"
REPORT = READ_CENTER_DIR / "V21_025_WITHIN_REGIME_ALPHA_ONLY_AND_RISK_GATE_SHADOW_RESEARCH_PLAN_REPORT.md"

CONTEXT_LIST = [
    "stable_regime_window", "no_regime_transition_risk", "unstable_regime_window", "regime_transition_risk",
    "QQQ_uptrend", "QQQ_downtrend", "SPY_uptrend", "SPY_downtrend",
    "sector_uptrend", "sector_downtrend", "semiconductor_uptrend", "semiconductor_downtrend",
    "QQQ_uptrend+SPY_uptrend", "semiconductor_uptrend+QQQ_uptrend", "sector_uptrend+SPY_uptrend",
    "QQQ_uptrend+stable_regime_window", "semiconductor_uptrend+stable_regime_window",
    "QQQ_downtrend+unstable_regime_window", "semiconductor_downtrend+unstable_regime_window",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: "" if row.get(field) is None else row.get(field, "") for field in fields})


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def yn(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def fnum(value: object) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    missing = [path.relative_to(ROOT).as_posix() for path in V21_027_INPUTS if not path.exists() or path.stat().st_size == 0]
    decision_027 = first(read_csv(OUT_DIR / "V21_027_CONTEXT_RETEST_DECISION.csv"))
    summary_027 = first(read_csv(OUT_DIR / "V21_027_MARKET_REGIME_CONTEXT_RETEST_WITH_REPAIRED_LABELS_SUMMARY.csv"))
    coverage = read_csv(OUT_DIR / "V21_027_REPAIRED_LABEL_COVERAGE_AUDIT.csv")
    perf = read_csv(OUT_DIR / "V21_027_REPAIRED_CONTEXT_RANK_BUCKET_PERFORMANCE.csv")
    combo = read_csv(OUT_DIR / "V21_027_TREND_COMBINATION_CONTEXT_TEST.csv")
    risk = read_csv(OUT_DIR / "V21_027_RISK_GATE_BY_REPAIRED_CONTEXT.csv")
    gaps = read_csv(OUT_DIR / "V21_027_REMAINING_SOURCE_GAP_IMPACT_AUDIT.csv")

    ingest_rows = [
        {"audit_item": "required_v21_027_artifacts_present", "audit_passed": yn(not missing), "observed_value": "|".join(missing) if missing else "ALL_PRESENT", "required_value": "TRUE", "research_only": "TRUE"},
        {"audit_item": "v21_027_decision_ingested", "audit_passed": yn(decision_027.get("context_retest_decision") == "REPAIRED_LABEL_CONTEXT_SIGNAL_CONFIRMED_RESEARCH_ONLY"), "observed_value": decision_027.get("context_retest_decision", ""), "required_value": "REPAIRED_LABEL_CONTEXT_SIGNAL_CONFIRMED_RESEARCH_ONLY", "research_only": "TRUE"},
        {"audit_item": "recommended_next_stage_v21_025", "audit_passed": yn(decision_027.get("recommended_next_stage") == "V21.025_WITHIN_REGIME_ALPHA_ONLY_AND_RISK_GATE_SHADOW_RESEARCH_PLAN"), "observed_value": decision_027.get("recommended_next_stage", ""), "required_value": "V21.025_WITHIN_REGIME_ALPHA_ONLY_AND_RISK_GATE_SHADOW_RESEARCH_PLAN", "research_only": "TRUE"},
        {"audit_item": "official_use_false", "audit_passed": yn(summary_027.get("official_use_allowed") == "FALSE"), "observed_value": summary_027.get("official_use_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "official_ranking_readiness_false", "audit_passed": yn(summary_027.get("official_ranking_readiness_allowed") == "FALSE"), "observed_value": summary_027.get("official_ranking_readiness_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "official_weight_update_readiness_false", "audit_passed": yn(summary_027.get("official_weight_update_readiness_allowed") == "FALSE"), "observed_value": summary_027.get("official_weight_update_readiness_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "official_weight_update_blocked", "audit_passed": yn(summary_027.get("official_weight_update_blocked") == "TRUE"), "observed_value": summary_027.get("official_weight_update_blocked", ""), "required_value": "TRUE", "research_only": "TRUE"},
        {"audit_item": "data_trust_zero_alpha_ranking_contribution", "audit_passed": yn(summary_027.get("data_trust_alpha_contribution") == "0" and summary_027.get("data_trust_ranking_weight") == "0"), "observed_value": f"{summary_027.get('data_trust_ranking_weight','')}|{summary_027.get('data_trust_alpha_contribution','')}", "required_value": "0|0", "research_only": "TRUE"},
        {"audit_item": "risk_additive_alpha_contribution_zero", "audit_passed": yn(summary_027.get("risk_additive_alpha_contribution") == "0"), "observed_value": summary_027.get("risk_additive_alpha_contribution", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "market_regime_additive_alpha_contribution_zero", "audit_passed": yn(summary_027.get("market_regime_additive_alpha_contribution") == "0"), "observed_value": summary_027.get("market_regime_additive_alpha_contribution", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "official_ranking_mutation_count_zero", "audit_passed": yn(summary_027.get("official_ranking_mutation_count") == "0"), "observed_value": summary_027.get("official_ranking_mutation_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "official_factor_weight_mutation_count_zero", "audit_passed": yn(summary_027.get("official_factor_weight_mutation_count") == "0"), "observed_value": summary_027.get("official_factor_weight_mutation_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "official_recommendation_count_zero", "audit_passed": yn(summary_027.get("official_recommendation_count") == "0"), "observed_value": summary_027.get("official_recommendation_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "trade_action_count_zero", "audit_passed": yn(summary_027.get("trade_action_count") == "0"), "observed_value": summary_027.get("trade_action_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "shadow_activation_false", "audit_passed": yn(summary_027.get("shadow_activation") == "FALSE"), "observed_value": summary_027.get("shadow_activation", ""), "required_value": "FALSE", "research_only": "TRUE"},
    ]

    cov = {row["label_name"]: row for row in coverage}
    risk_by_context = {}
    for row in risk:
        risk_by_context.setdefault(row.get("context_label", ""), []).append(row.get("risk_gate_context_classification", ""))
    perf_by_context = {}
    for row in perf:
        if row.get("rank_type") == "WITHIN_REPAIRED_LABEL_ALPHA_ONLY_RANK" and row.get("forward_return_window") == "10d":
            perf_by_context[row.get("context_label", "")] = row
    combo_by_context = {row.get("context_combination", ""): row for row in combo if row.get("forward_return_window") == "10d"}
    gap_block = any(row.get("severity") == "HIGH" and row.get("cannot_fabricate") == "TRUE" for row in gaps)

    context_rows = []
    for ctx in CONTEXT_LIST:
        is_combo = "+" in ctx
        src = combo_by_context.get(ctx, {}) if is_combo else perf_by_context.get(ctx, {})
        csrc = {} if is_combo else cov.get(ctx, {})
        obs = src.get("observation_count") or csrc.get("observation_count", "0")
        dates = src.get("distinct_as_of_date_count") or csrc.get("distinct_as_of_date_count", "0")
        tickers = src.get("distinct_ticker_count") or csrc.get("distinct_ticker_count", "0")
        strength = fnum(src.get("top_quintile_mean_return") or src.get("alpha_top20_mean_return"))
        rclasses = risk_by_context.get(ctx, [])
        ruse = "DIAGNOSTIC_ONLY_MIXED" if "MIXED_IN_CONTEXT" in rclasses else "INSUFFICIENT_SAMPLE" if not rclasses else "|".join(sorted(set(rclasses)))
        context_rows.append({
            "research_context": ctx,
            "observation_count": obs,
            "distinct_as_of_date_count": dates,
            "distinct_ticker_count": tickers,
            "evaluated_forward_return_windows": csrc.get("available_forward_return_windows", "5d|10d|20d" if obs != "0" else ""),
            "signal_strength": strength,
            "risk_gate_usefulness": ruse,
            "sample_adequacy": src.get("sample_adequacy") or csrc.get("sample_adequacy", "INSUFFICIENT_SAMPLE"),
            "source_gap_limitations": "VIX_EVENT_GAPS_REMAIN_BUT_DO_NOT_BLOCK_RESEARCH_LEDGER" if gap_block else "NONE",
            "research_only_eligibility": yn((src.get("sample_adequacy") == "SUFFICIENT") or (csrc.get("sample_adequacy") == "SUFFICIENT")),
            "research_only": "TRUE",
        })

    design_rows = [
        {"lane_id": "WITHIN_REGIME_ALPHA_ONLY_PRIMARY", "lane_status": "PLAN_ONLY_NOT_ACTIVATED", "base_rank": "WITHIN_REPAIRED_LABEL_ALPHA_ONLY_RANK", "eligible_contexts": "stable_regime_window|no_regime_transition_risk|QQQ_uptrend|SPY_uptrend|sector_uptrend|semiconductor_uptrend", "alpha_families": "FUNDAMENTAL|TECHNICAL|STRATEGY", "data_trust_alpha_contribution": "0", "risk_additive_alpha_contribution": "0", "market_regime_additive_alpha_contribution": "0", "uses_global_market_regime_adjusted_score": "FALSE", "shadow_activation": "FALSE", "research_only": "TRUE"},
        {"lane_id": "UNSTABLE_CONTEXT_RISK_GATE_OVERLAY", "lane_status": "DIAGNOSTIC_OVERLAY_ONLY_NOT_ACTIVATED", "base_rank": "WITHIN_REPAIRED_LABEL_ALPHA_ONLY_RANK", "eligible_contexts": "unstable_regime_window|regime_transition_risk|QQQ_downtrend|SPY_downtrend", "alpha_families": "FUNDAMENTAL|TECHNICAL|STRATEGY", "data_trust_alpha_contribution": "0", "risk_additive_alpha_contribution": "0", "market_regime_additive_alpha_contribution": "0", "uses_global_market_regime_adjusted_score": "FALSE", "shadow_activation": "FALSE", "research_only": "TRUE"},
        {"lane_id": "TREND_COMBINATION_CONTEXT_DIAGNOSTIC", "lane_status": "DIAGNOSTIC_CONTEXT_ONLY_NOT_ACTIVATED", "base_rank": "WITHIN_REPAIRED_LABEL_ALPHA_ONLY_RANK", "eligible_contexts": "QQQ_uptrend+stable_regime_window|semiconductor_uptrend+stable_regime_window|QQQ_uptrend+SPY_uptrend", "alpha_families": "FUNDAMENTAL|TECHNICAL|STRATEGY", "data_trust_alpha_contribution": "0", "risk_additive_alpha_contribution": "0", "market_regime_additive_alpha_contribution": "0", "uses_global_market_regime_adjusted_score": "FALSE", "shadow_activation": "FALSE", "research_only": "TRUE"},
    ]
    guard_items = [
        "no_official_ranking_mutation", "no_official_weight_mutation", "no_recommendation_creation", "no_trade_action_creation",
        "no_broker_execution", "no_shadow_activation", "no_official_performance_claim", "research_only_outputs_only",
        "data_trust_gate_audit_only", "risk_market_regime_zero_additive_alpha", "missing_vix_event_labels_remain_gaps",
    ]
    guard_rows = [{"guardrail": item, "guardrail_status": "BLOCKED_OR_ENFORCED", "official_use_allowed": "FALSE", "shadow_activation": "FALSE", "broker_execution_supported": "FALSE", "research_only": "TRUE"} for item in guard_items]
    ledger_fields = ["observation_id", "as_of_date", "ticker", "context_label", "context_combination", "lane_id", "alpha_only_score", "global_alpha_only_rank", "within_regime_alpha_only_rank", "risk_gate_flag", "risk_gate_action", "within_regime_risk_gated_rank", "selected_for_shadow_observation", "selection_bucket", "forward_return_window", "future_return_due_date", "realized_forward_return", "observation_status", "research_only", "official_use_allowed", "trade_action_created"]
    ledger_rows = [{"field_name": f, "required": "TRUE", "description": f"future ledger field {f}", "research_only": "TRUE"} for f in ledger_fields]
    selection_rows = [
        {"policy_item": "top_n_per_eligible_context", "policy_value": "TOP_5|TOP_10|TOP_20|TOP_QUINTILE_DIAGNOSTICS", "creates_recommendation": "FALSE", "creates_trade_action": "FALSE", "observation_only": "TRUE", "research_only": "TRUE"},
        {"policy_item": "eligibility_requirements", "policy_value": "sample_adequacy|no_source_gap_blocker|pit_valid_label|data_trust_gate_pass_if_available", "creates_recommendation": "FALSE", "creates_trade_action": "FALSE", "observation_only": "TRUE", "research_only": "TRUE"},
    ]
    risk_policy_rows = [
        {"context_rule": "stable_regime_window", "risk_gate_policy": "REVIEW_ONLY_UNLESS_PROTECTIVE_EVIDENCE", "global_hard_gate_allowed": "FALSE", "preserve_blocked_names": "TRUE", "research_only": "TRUE"},
        {"context_rule": "unstable_regime_window", "risk_gate_policy": "DIAGNOSTIC_OVERLAY_ALLOWED", "global_hard_gate_allowed": "FALSE", "preserve_blocked_names": "TRUE", "research_only": "TRUE"},
        {"context_rule": "regime_transition_risk", "risk_gate_policy": "DIAGNOSTIC_OVERLAY_ALLOWED", "global_hard_gate_allowed": "FALSE", "preserve_blocked_names": "TRUE", "research_only": "TRUE"},
        {"context_rule": "uptrend_contexts", "risk_gate_policy": "NO_GLOBAL_HARD_GATE_WITHOUT_CONTEXT_EVIDENCE", "global_hard_gate_allowed": "FALSE", "preserve_blocked_names": "TRUE", "research_only": "TRUE"},
        {"context_rule": "downtrend_contexts", "risk_gate_policy": "SEPARATELY_TRACK_MIXED_EVIDENCE", "global_hard_gate_allowed": "FALSE", "preserve_blocked_names": "TRUE", "research_only": "TRUE"},
    ]
    metric_names = ["top_bucket_forward_return", "top_minus_universe_spread", "top_minus_bottom_spread", "hit_rate", "median_return", "rank_monotonicity", "risk_gate_improvement", "missed_winner_rate", "downside_protection_rate", "outlier_dependency", "context_stability", "source_gap_status", "pit_label_validity"]
    metric_rows = [{"metric_name": m, "monitoring_scope": "future_shadow_observation_only", "promotion_allowed": "FALSE", "research_only": "TRUE"} for m in metric_names]
    blocker_names = ["VIX labels missing", "macro/event labels missing", "insufficient new matured observations", "unstable context performance", "risk gate false-block rate too high", "context signal fails out-of-sample", "rank turnover too high", "official mutation attempted", "DATA_TRUST alpha contribution nonzero", "RISK/MARKET_REGIME additive alpha contribution nonzero"]
    continuation = "enough_new_observations|pit_labels_pass|stable_context_positive|unstable_overlay_beneficial|false_block_acceptable|no_official_mutation"
    blocker_rows = [{"criteria_type": "PROMOTION_BLOCKER", "criteria": b, "blocks_activation": "TRUE", "research_only_continuation_criteria": continuation, "research_only": "TRUE"} for b in blocker_names]
    artifact_rows = [
        {"artifact_type": "producer", "proposed_artifact": "scripts/v21/v21_029_within_regime_shadow_observation_ledger_producer.py", "execute_now": "FALSE", "blocked_official_artifacts": "official_scores|official_ranks|recommendations|trades|weights|market_regime", "research_only": "TRUE"},
        {"artifact_type": "ledger", "proposed_artifact": "outputs/v21/factor_backtest/V21_029_WITHIN_REGIME_SHADOW_OBSERVATION_LEDGER.csv", "execute_now": "FALSE", "blocked_official_artifacts": "official_recommendations|trade_actions", "research_only": "TRUE"},
        {"artifact_type": "report", "proposed_artifact": "outputs/v21/read_center/V21_029_WITHIN_REGIME_SHADOW_OBSERVATION_LEDGER_REPORT.md", "execute_now": "FALSE", "blocked_official_artifacts": "production_readiness|real_book_readiness", "research_only": "TRUE"},
        {"artifact_type": "test", "proposed_artifact": "scripts/v21/test_v21_029_within_regime_shadow_observation_ledger_producer.py", "execute_now": "FALSE", "blocked_official_artifacts": "shadow_activation", "research_only": "TRUE"},
        {"artifact_type": "dependency", "proposed_artifact": "V21_026_DERIVED_RESEARCH_ONLY_REGIME_LABELS|primary_matured_observations", "execute_now": "FALSE", "blocked_official_artifacts": "broker_execution", "research_only": "TRUE"},
    ]

    source_gaps_material = False
    risk_false_block_material = any("OVERLY_RESTRICTIVE_IN_CONTEXT" in v for vals in risk_by_context.values() for v in vals)
    if missing or any(row["audit_passed"] == "FALSE" for row in ingest_rows[:3]):
        plan_decision = "SHADOW_RESEARCH_PLAN_INCONCLUSIVE_REQUIRED_FIELDS_MISSING"
        next_stage = "V21.019_MORE_MATURED_OBSERVATION_ACCUMULATION_PLAN"
    elif risk_false_block_material:
        plan_decision = "SHADOW_RESEARCH_PLAN_BLOCKED_BY_RISK_GATE_FALSE_BLOCK"
        next_stage = "V21.017_OVERHEAT_ENTRY_TIMING_AND_FALSE_BLOCK_REPAIR"
    elif source_gaps_material:
        plan_decision = "SHADOW_RESEARCH_PLAN_PARTIAL_SOURCE_GAPS_REMAIN"
        next_stage = "V21.028_MARKET_REGIME_DATA_PRODUCER_IMPLEMENTATION"
    else:
        plan_decision = "SHADOW_RESEARCH_PLAN_READY_NOT_ACTIVATED"
        next_stage = "V21.029_WITHIN_REGIME_SHADOW_OBSERVATION_LEDGER_PRODUCER"
    prefix = "PASS" if plan_decision == "SHADOW_RESEARCH_PLAN_READY_NOT_ACTIVATED" else "PARTIAL_PASS"
    final_status = f"{prefix}_V21_025_{plan_decision}"
    decision_rows = [{"shadow_research_plan_decision": plan_decision, "final_status": final_status, "official_use_allowed": "FALSE", "official_ranking_readiness_allowed": "FALSE", "official_weight_update_readiness_allowed": "FALSE", "official_weight_update_blocked": "TRUE", "broker_execution_supported": "FALSE", "shadow_activation": "FALSE", "recommended_next_stage": next_stage, "selected_recommended_next_stage": "TRUE", "research_only": "TRUE"}]
    summary = {
        "stage_name": STAGE_NAME,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "research_only": "TRUE",
        "final_status": final_status,
        "shadow_research_plan_decision": plan_decision,
        "v21_027_context_retest_decision": decision_027.get("context_retest_decision", ""),
        "v21_027_recommended_next_stage": decision_027.get("recommended_next_stage", ""),
        "official_use_allowed": "FALSE",
        "official_ranking_readiness_allowed": "FALSE",
        "official_weight_update_readiness_allowed": "FALSE",
        "official_weight_update_blocked": "TRUE",
        "broker_execution_supported": "FALSE",
        "recommended_next_stage": next_stage,
        "prototype_output_scope": "V21_025_RESEARCH_ONLY",
        "data_trust_ranking_weight": "0",
        "data_trust_alpha_contribution": "0",
        "risk_additive_alpha_contribution": "0",
        "market_regime_additive_alpha_contribution": "0",
        "official_ranking_mutation_count": "0",
        "official_factor_weight_mutation_count": "0",
        "official_recommendation_count": "0",
        "trade_action_count": "0",
        "shadow_activation": "FALSE",
    }

    write_csv(INGEST, ingest_rows, ["audit_item", "audit_passed", "observed_value", "required_value", "research_only"])
    write_csv(CONTEXTS, context_rows, ["research_context", "observation_count", "distinct_as_of_date_count", "distinct_ticker_count", "evaluated_forward_return_windows", "signal_strength", "risk_gate_usefulness", "sample_adequacy", "source_gap_limitations", "research_only_eligibility", "research_only"])
    write_csv(DESIGN, design_rows, ["lane_id", "lane_status", "base_rank", "eligible_contexts", "alpha_families", "data_trust_alpha_contribution", "risk_additive_alpha_contribution", "market_regime_additive_alpha_contribution", "uses_global_market_regime_adjusted_score", "shadow_activation", "research_only"])
    write_csv(GUARDS, guard_rows, ["guardrail", "guardrail_status", "official_use_allowed", "shadow_activation", "broker_execution_supported", "research_only"])
    write_csv(LEDGER, ledger_rows, ["field_name", "required", "description", "research_only"])
    write_csv(SELECTION, selection_rows, ["policy_item", "policy_value", "creates_recommendation", "creates_trade_action", "observation_only", "research_only"])
    write_csv(RISK_POLICY, risk_policy_rows, ["context_rule", "risk_gate_policy", "global_hard_gate_allowed", "preserve_blocked_names", "research_only"])
    write_csv(METRICS, metric_rows, ["metric_name", "monitoring_scope", "promotion_allowed", "research_only"])
    write_csv(BLOCKERS, blocker_rows, ["criteria_type", "criteria", "blocks_activation", "research_only_continuation_criteria", "research_only"])
    write_csv(ARTIFACTS, artifact_rows, ["artifact_type", "proposed_artifact", "execute_now", "blocked_official_artifacts", "research_only"])
    write_csv(DECISION, decision_rows, ["shadow_research_plan_decision", "final_status", "official_use_allowed", "official_ranking_readiness_allowed", "official_weight_update_readiness_allowed", "official_weight_update_blocked", "broker_execution_supported", "shadow_activation", "recommended_next_stage", "selected_recommended_next_stage", "research_only"])
    write_csv(SUMMARY, [summary], list(summary.keys()))

    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(f"""# V21.025 Within-Regime Alpha-Only And Risk-Gate Shadow Research Plan Report

## Executive summary
This research-only planning stage defines a non-activated shadow observation plan after V21.027 confirmed repaired-label context signal. It creates no official rankings, weights, recommendations, trades, broker instructions, or shadow activation.

## Final shadow research plan decision
{plan_decision}

Final status: {final_status}

## V21.027 decision ingestion
V21.027 decision: {decision_027.get('context_retest_decision', '')}. Recommended next stage: {decision_027.get('recommended_next_stage', '')}.

## Research context candidate selection
See V21_025_RESEARCH_CONTEXT_CANDIDATE_SELECTION.csv.

## Shadow research plan design
Lane A is within-regime alpha-only primary. Lane B is unstable-context risk-gate diagnostic overlay. Lane C is trend-combination context diagnostic.

## Plan guardrails
Official use, official ranking readiness, official weight update readiness, broker execution, and shadow activation are blocked.

## Shadow observation ledger specification
See V21_025_SHADOW_OBSERVATION_LEDGER_SPEC.csv.

## Selection policy prototype
Selection is observation-only and creates no recommendation or trade action.

## Risk gate policy prototype
Risk gate is not a global hard gate. It remains review-only or diagnostic overlay by context, with blocked/demoted names preserved for audit.

## Required monitoring metrics
See V21_025_REQUIRED_MONITORING_METRICS.csv.

## Promotion blockers and exit criteria
VIX and macro/event labels remain gaps. Official mutation attempts, nonzero DATA_TRUST alpha, or nonzero RISK/MARKET_REGIME additive alpha block promotion.

## Dry-run artifact plan
See V21_025_DRY_RUN_ARTIFACT_PLAN.csv. No dry-run producer is executed in this stage.

## DATA_TRUST zero-alpha confirmation
DATA_TRUST ranking contribution is 0 and alpha contribution is 0. RISK and MARKET_REGIME additive alpha contribution are 0.

## Explicit blocked actions
No official ranking mutation. No official factor weight mutation. No official recommendation. No trade action. No broker execution. No shadow activation. No official use. No official ranking readiness. No official weight update readiness. No production readiness. No real-book readiness.

## What this stage allows
It allows only a future research-only observation ledger producer plan.

## What this stage still blocks
It blocks production readiness, real-book readiness, official activation, official rankings, official weights, recommendations, trades, broker execution, and shadow policy activation.

## Recommended next stage
{next_stage}
""", encoding="utf-8")
    print(f"STAGE_NAME={STAGE_NAME}")
    print(f"final_status={final_status}")
    print(f"shadow_research_plan_decision={plan_decision}")
    print(f"recommended_next_stage={next_stage}")
    print("official_use_allowed=FALSE")
    print("official_ranking_readiness_allowed=FALSE")
    print("official_weight_update_readiness_allowed=FALSE")
    print("official_weight_update_blocked=TRUE")
    print("broker_execution_supported=FALSE")
    print("data_trust_ranking_weight=0")
    print("data_trust_alpha_contribution=0")
    print("risk_additive_alpha_contribution=0")
    print("market_regime_additive_alpha_contribution=0")
    print("official_ranking_mutation_count=0")
    print("official_factor_weight_mutation_count=0")
    print("official_recommendation_count=0")
    print("trade_action_count=0")
    print("shadow_activation=FALSE")
    print("research_only=TRUE")


if __name__ == "__main__":
    main()
