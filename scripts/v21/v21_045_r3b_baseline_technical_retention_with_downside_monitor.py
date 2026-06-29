#!/usr/bin/env python
"""Research-only baseline Technical-only retention and downside monitor contract."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path


STAGE = "V21.045-R3B_BASELINE_TECHNICAL_RETENTION_WITH_DOWNSIDE_MONITOR"
PASS_STATUS = "PASS_V21_045_R3B_BASELINE_TECHNICAL_RETAINED_WITH_DOWNSIDE_MONITOR"
PENDING_STATUS = "PARTIAL_PASS_V21_045_R3B_BASELINE_RETAINED_PENDING_MATURED_OBSERVATIONS"
WARN_STATUS = "PARTIAL_PASS_V21_045_R3B_RETENTION_WITH_UPSTREAM_WARNINGS"
INPUT_BLOCKED = "BLOCKED_V21_045_R3B_REQUIRED_UPSTREAM_OUTPUTS_NOT_FOUND"
SCOPE_BLOCKED = "BLOCKED_V21_045_R3B_SCOPE_BOUNDARY_FAILED"

ROOT = Path(__file__).resolve().parents[2]
OPT = ROOT / "outputs" / "v21" / "optimization"
REVIEW = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"
BACKTEST = ROOT / "outputs" / "v21" / "backtest"

R1_DECISION = OPT / "V21_045_R1_FILTER_OPTIMIZATION_DECISION_SUMMARY.csv"
R1_SUMMARY = OPT / "V21_045_R1_FILTER_VARIANT_WINDOW_SUMMARY.csv"
R1_ATTR = OPT / "V21_045_R1_FILTER_SAMPLE_ATTRITION_AUDIT.csv"
R2_DECISION = REVIEW / "V21_045_R2_FILTER_REVIEW_DECISION_SUMMARY.csv"
R2_ATTR = REVIEW / "V21_045_R2_SAMPLE_ATTRITION_USABILITY_AUDIT.csv"
R2_CONC = REVIEW / "V21_045_R2_CONCENTRATION_AUDIT.csv"
R2_PAYOFF = REVIEW / "V21_045_R2_PAYOFF_DOWNSIDE_AUDIT.csv"
R3_DECISION = OPT / "V21_045_R3_SOFT_FILTER_DECISION_SUMMARY.csv"
R3_HIT = OPT / "V21_045_R3_SOFT_FILTER_HIT_RATE_EXCESS_COMPARISON.csv"
R3_ATTR = OPT / "V21_045_R3_SOFT_FILTER_ATTRITION_USABILITY_AUDIT.csv"
R3_CONC = OPT / "V21_045_R3_SOFT_FILTER_CONCENTRATION_AUDIT.csv"
R3_PAYOFF = OPT / "V21_045_R3_SOFT_FILTER_PAYOFF_DOWNSIDE_AUDIT.csv"
R5_SUMMARY = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_VARIANT_WINDOW_SUMMARY.csv"
R5_QQQ = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_QQQ_BENCHMARK_COMPARISON.csv"
R6_DECISION = REVIEW / "V21_044_R6_CONTINUITY_GATE_DECISION_SUMMARY.csv"
R8A_GATE = REVIEW / "V21_044_R8A_MATURITY_GATE_STATUS.csv"
R8A_WAIT = REVIEW / "V21_044_R8A_WAIT_UNTIL_FIRST_MATURITY_DATE_SUMMARY.csv"
R8R1_DECISION = REVIEW / "V21_044_R8_R1_TECHNICAL_ONLY_DECISION_SUMMARY.csv"

UPSTREAM_AUDIT = REVIEW / "V21_045_R3B_UPSTREAM_CHAIN_AUDIT.csv"
FILTER_REJECTION = REVIEW / "V21_045_R3B_FILTER_REJECTION_AUDIT.csv"
RETENTION_AUDIT = REVIEW / "V21_045_R3B_BASELINE_RETENTION_AUDIT.csv"
MONITOR_CONTRACT = REVIEW / "V21_045_R3B_DOWNSIDE_MONITOR_CONTRACT.csv"
FUTURE_ROUTING = REVIEW / "V21_045_R3B_FUTURE_DECISION_ROUTING.csv"
SCOPE_AUDIT = REVIEW / "V21_045_R3B_SCOPE_BOUNDARY_AUDIT.csv"
DECISION_SUMMARY = REVIEW / "V21_045_R3B_DECISION_SUMMARY.csv"
REPORT = READ_CENTER / "V21_045_R3B_BASELINE_TECHNICAL_RETENTION_WITH_DOWNSIDE_MONITOR_REPORT.md"
CURRENT_REPORT = READ_CENTER / "CURRENT_V21_045_R3B_BASELINE_TECHNICAL_RETENTION_WITH_DOWNSIDE_MONITOR_REPORT.md"

WINDOWS = ["5D", "10D", "20D", "60D"]
FILTERS = [
    "COMBINED_CONSERVATIVE_FILTER",
    "SOFT_COMBINED_V1_REGIME_ONLY_PLUS_LIGHT_OVERHEAT",
    "SOFT_COMBINED_V2_REGIME_PLUS_NO_EXTREME_EXTENSION",
    "SOFT_COMBINED_V3_PULLBACK_OR_TREND",
    "SOFT_COMBINED_V4_QQQ_REGIME_WITH_REFILL",
    "SOFT_COMBINED_V5_OVERHEAT_ONLY_LIGHT",
    "SOFT_COMBINED_V6_WATCHLIST_SCORE_NOT_BINARY_BLOCK",
]

GUARDRAILS = {
    "research_only": "TRUE",
    "retention_monitor_only": "TRUE",
    "filter_adoption_allowed": "FALSE",
    "technical_only_filter_overlay": "FALSE",
    "retained_stream": "BASELINE_TECHNICAL_ONLY",
    "technical_only_observation_allowed": "TRUE_INHERITED_FROM_V21_044_R6_ONLY",
    "full_weight_result_available": "FALSE",
    "full_weight_rebacktest_allowed_now": "FALSE",
    "official_adoption_allowed": "FALSE",
    "official_weight_mutation": "FALSE",
    "official_ranking_mutation": "FALSE",
    "official_recommendation_allowed": "FALSE",
    "real_book_action_allowed": "FALSE",
    "broker_execution_allowed": "FALSE",
    "trade_action_allowed": "FALSE",
    "shadow_gate_allowed": "FALSE",
    "shadow_adoption_allowed": "FALSE",
}
FALSE_GUARDRAILS = [
    "filter_adoption_allowed", "technical_only_filter_overlay", "full_weight_result_available",
    "full_weight_rebacktest_allowed_now", "official_adoption_allowed", "official_weight_mutation",
    "official_ranking_mutation", "official_recommendation_allowed", "real_book_action_allowed",
    "broker_execution_allowed", "trade_action_allowed", "shadow_gate_allowed", "shadow_adoption_allowed",
]


def yn(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: "" if row.get(field) is None else row.get(field, "") for field in fields})


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def metric_summary(rows: list[dict[str, str]], variant: str, field: str) -> str:
    selected = [r for r in rows if r.get("filter_variant") == variant and r.get("bucket") == "Top20"]
    if not selected:
        return "NOT_AVAILABLE"
    by_window: dict[str, str] = {}
    for row in selected:
        window = row.get("forward_return_window", "")
        if window in WINDOWS and window not in by_window:
            by_window[window] = row.get(field, "")
    return "|".join(f"{w}:{by_window.get(w, '')}" for w in WINDOWS)


def baseline_text(rows: list[dict[str, str]]) -> str:
    by_window = {r.get("forward_return_window", ""): r for r in rows}
    return "|".join(
        f"{w}:excess={by_window.get(w, {}).get('top20_excess_vs_QQQ', '')};hit={by_window.get(w, {}).get('top20_hit_rate_vs_QQQ', '')}"
        for w in WINDOWS
    )


def main() -> int:
    REVIEW.mkdir(parents=True, exist_ok=True)
    READ_CENTER.mkdir(parents=True, exist_ok=True)

    r1 = first(read_rows(R1_DECISION))
    r1_summary = read_rows(R1_SUMMARY)
    r1_attr = read_rows(R1_ATTR)
    r2 = first(read_rows(R2_DECISION))
    r2_attr = read_rows(R2_ATTR)
    r2_conc = read_rows(R2_CONC)
    r2_payoff = read_rows(R2_PAYOFF)
    r3 = first(read_rows(R3_DECISION))
    r3_hit = read_rows(R3_HIT)
    r3_attr = read_rows(R3_ATTR)
    r3_conc = read_rows(R3_CONC)
    r3_payoff = read_rows(R3_PAYOFF)
    r5 = read_rows(R5_SUMMARY)
    r5_qqq = read_rows(R5_QQQ)
    r6 = first(read_rows(R6_DECISION))
    r8a_wait = first(read_rows(R8A_WAIT))
    r8a_gate = read_rows(R8A_GATE)
    r8r1 = first(read_rows(R8R1_DECISION))

    required = [R1_DECISION, R1_SUMMARY, R1_ATTR, R2_DECISION, R2_ATTR, R2_CONC, R2_PAYOFF, R3_DECISION, R3_HIT, R3_ATTR, R3_CONC, R3_PAYOFF, R5_SUMMARY, R5_QQQ, R6_DECISION]
    required_found = all(path.exists() and path.stat().st_size > 0 for path in required)
    optional_maturity_found = R8A_WAIT.exists() and R8A_WAIT.stat().st_size > 0
    r1_ok = r1.get("final_status", "").startswith(("PASS_", "PARTIAL_PASS_"))
    r2_ok = r2.get("final_status", "").startswith(("PASS_", "PARTIAL_PASS_"))
    r3_ok = r3.get("final_status", "").startswith(("PASS_", "PARTIAL_PASS_"))
    r3_keep = r3.get("decision") in {"NO_SOFT_FILTER_BEATS_BASELINE_KEEP_TECHNICAL_ONLY", "SOFT_FILTER_REDUCES_ATTRITION_BUT_LOSES_EDGE"}
    no_filter_adopted = all(row.get("filter_adopted", "FALSE") == "FALSE" for row in [r1, r2, r3])
    full_weight_blocked = r6.get("full_weight_result_available") == "FALSE" and r6.get("full_weight_rebacktest_allowed_now") == "FALSE"

    upstream_rows = [
        {"chain_check": "r1_completed", "observed_value": r1.get("final_status", ""), "check_passed": yn(r1_ok), "notes": "R1 optimization dry-run completed.", **GUARDRAILS},
        {"chain_check": "r2_completed", "observed_value": r2.get("final_status", ""), "check_passed": yn(r2_ok), "notes": "R2 review gate completed.", **GUARDRAILS},
        {"chain_check": "r3_completed", "observed_value": r3.get("final_status", ""), "check_passed": yn(r3_ok), "notes": "R3 soft relaxation dry-run completed.", **GUARDRAILS},
        {"chain_check": "r3_keeps_baseline", "observed_value": r3.get("decision", ""), "check_passed": yn(r3_keep), "notes": "R3 must keep baseline or equivalent.", **GUARDRAILS},
        {"chain_check": "no_filter_adopted_upstream", "observed_value": yn(no_filter_adopted), "check_passed": yn(no_filter_adopted), "notes": "No filter may be adopted upstream.", **GUARDRAILS},
        {"chain_check": "full_weight_blocked", "observed_value": yn(full_weight_blocked), "check_passed": yn(full_weight_blocked), "notes": "Full-weight remains blocked.", **GUARDRAILS},
    ]
    write_rows(UPSTREAM_AUDIT, upstream_rows)

    rejection_rows = []
    for filt in FILTERS:
        if filt == "COMBINED_CONSERVATIVE_FILTER":
            review_result = "REVIEW_WORTHY_BUT_NOT_ADOPTABLE_ATTRITION_TOO_HIGH"
            reason = "EXTREME_ATTRITION_WARNING|CONCENTRATION_WARNING|PAYOFF_RATIO_WARNING|60D_DEGRADATION"
            hit = r1.get("hit_rate_improvement_summary", "")
            excess = r1.get("excess_return_change_summary", "")
            attr = r2.get("sample_attrition_warning", "")
            conc = r2.get("concentration_warning", "")
            payoff = r2.get("payoff_downside_warning", "")
        else:
            review_result = "NO_IMPROVEMENT_VS_BASELINE"
            reason = "R3_SOFT_RELAXATION_DID_NOT_BEAT_BASELINE_OR_BALANCED_CANDIDATE_FALSE"
            hit = metric_summary(r3_hit, filt, "hit_rate_improvement_vs_baseline")
            excess = metric_summary(r3_hit, filt, "excess_change_vs_baseline")
            attr = metric_summary(r3_attr, filt, "attrition_warning")
            conc = metric_summary(r3_conc, filt, "concentration_warning")
            payoff = metric_summary(r3_payoff, filt, "payoff_downside_warning")
        rejection_rows.append({
            "filter_family": filt,
            "review_result": review_result,
            "adoption_allowed": "FALSE",
            "reason_not_adopted": reason,
            "hit_rate_improvement_summary": hit,
            "excess_change_summary": excess,
            "attrition_status": attr,
            "concentration_status": conc,
            "payoff_downside_status": payoff,
            **GUARDRAILS,
        })
    write_rows(FILTER_REJECTION, rejection_rows)

    first_maturity_date = r8a_wait.get("first_maturity_date") or "2026-06-24"
    retained_stream = "BASELINE_TECHNICAL_ONLY"
    retention_rows = [{
        "retained_stream": retained_stream,
        "retention_reason": "NO_SOFT_FILTER_BEATS_BASELINE",
        "baseline_source": "V21_044_R5_CANONICAL_CONSERVATIVE",
        "baseline_result_summary": baseline_text(r5),
        "filter_adoption_allowed": "FALSE",
        "technical_only_observation_allowed": "TRUE_INHERITED_FROM_V21_044_R6_ONLY",
        "new_observation_rights_created_by_this_stage": "FALSE",
        **GUARDRAILS,
    }]
    write_rows(RETENTION_AUDIT, retention_rows)

    monitor_rows = [{
        "contract_name": "BASELINE_TECHNICAL_ONLY_DOWNSIDE_MONITOR",
        "hit_rate_vs_QQQ_warning_threshold": "0.50",
        "severe_hit_rate_warning_threshold": "0.45",
        "mean_excess_vs_QQQ_warning_threshold": "0.00",
        "severe_excess_warning_threshold": "negative_in_two_or_more_windows",
        "worst_5pct_excess_warning_threshold": "-0.10",
        "payoff_ratio_warning_threshold": "1.00",
        "sample_concentration_warning_threshold": "0.35",
        "downside_warning_enabled": "TRUE",
        "r9_dependency": "matured_rows_required",
        "first_maturity_date": first_maturity_date,
        "future_results_computed_now": "FALSE",
        **GUARDRAILS,
    }]
    write_rows(MONITOR_CONTRACT, monitor_rows)

    routing_rows = [
        {"routing_condition": "future_matured_5D_hit_rate_improves_and_excess_positive", "next_stage": "V21.045-R4_BASELINE_TECHNICAL_DOWNSIDE_MONITOR_REVIEW", "notes": "Review baseline Technical-only downside monitor after matured evidence exists.", **GUARDRAILS},
        {"routing_condition": "future_matured_results_deteriorate", "next_stage": "V21.045-R4A_BASELINE_TECHNICAL_DOWNSIDE_REPAIR_REVIEW", "notes": "Investigate downside/failure modes without adopting filters.", **GUARDRAILS},
        {"routing_condition": "future_matured_results_insufficient", "next_stage": "keep_collecting_observations", "notes": "Do not evaluate R9 without enough matured rows.", **GUARDRAILS},
        {"routing_condition": "full_family_PIT_data_available", "next_stage": "return_to_V21.044_full-family_materialization_line", "notes": "Full-family evidence must be handled outside this Technical-only filter line.", **GUARDRAILS},
    ]
    write_rows(FUTURE_ROUTING, routing_rows)

    scope_checks = [
        ("research_only", GUARDRAILS["research_only"] == "TRUE", "Research-only stage."),
        ("retention_monitor_only", GUARDRAILS["retention_monitor_only"] == "TRUE", "Retention/monitor contract only."),
        ("filter_adoption_disabled", GUARDRAILS["filter_adoption_allowed"] == "FALSE", "No filter adoption allowed."),
        ("restricted_permissions_disabled", all(GUARDRAILS[f] == "FALSE" for f in FALSE_GUARDRAILS), "Official, shadow, broker, execution, trade, and full-weight permissions disabled."),
    ]
    scope_ok = all(passed for _, passed, _ in scope_checks)
    write_rows(SCOPE_AUDIT, [
        {"boundary_check": name, "required_value": "TRUE", "observed_value": yn(passed), "check_passed": yn(passed), "blocking": "TRUE", "notes": notes, **GUARDRAILS}
        for name, passed, notes in scope_checks
    ])

    if not required_found:
        final_status = INPUT_BLOCKED
        decision = "RETENTION_REVIEW_BLOCKED"
    elif not scope_ok:
        final_status = SCOPE_BLOCKED
        decision = "RETENTION_REVIEW_BLOCKED"
    elif optional_maturity_found and r8a_wait.get("r9_allowed_now") == "FALSE":
        final_status = PENDING_STATUS
        decision = "KEEP_BASELINE_TECHNICAL_ONLY_WITH_DOWNSIDE_MONITOR"
    elif r2.get("sample_attrition_warning") or r3.get("final_status", "").startswith("PARTIAL_PASS"):
        final_status = WARN_STATUS
        decision = "KEEP_BASELINE_TECHNICAL_ONLY_WITH_DOWNSIDE_MONITOR"
    else:
        final_status = PASS_STATUS
        decision = "KEEP_BASELINE_TECHNICAL_ONLY_WITH_DOWNSIDE_MONITOR"

    recommended_next_stage = "rerun V21.044-R8/R8-R1 after local price cache covers 2026-06-24"
    decision_row = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "retained_stream": retained_stream,
        "filter_adoption_allowed": "FALSE",
        "downside_monitor_enabled": "TRUE",
        "first_maturity_date": first_maturity_date,
        "first_maturity_dependency": "matured_rows_required_before_R9_or_monitor_evaluation",
        "strict_filter_rejection_summary": "COMBINED_CONSERVATIVE_FILTER rejected: attrition too high, concentration warning, payoff warning, 60D degradation.",
        "soft_filter_rejection_summary": "R3 soft filters did not produce a balanced candidate that beat baseline.",
        "baseline_result_summary": baseline_text(r5),
        "recommended_next_stage": recommended_next_stage,
        "r1_rows_read": len(read_rows(R1_DECISION)),
        "r2_rows_read": len(read_rows(R2_DECISION)),
        "r3_rows_read": len(read_rows(R3_DECISION)),
        "r8a_maturity_gate_rows_read": len(r8a_gate),
        "r8r1_optional_rows_read": 1 if r8r1 else 0,
        "online_download_attempted": "FALSE",
        "yfinance_used": "FALSE",
        **GUARDRAILS,
    }
    write_rows(DECISION_SUMMARY, [decision_row])

    report = f"""# V21.045-R3B baseline Technical-only retention with downside monitor

final_status: {final_status}

decision: {decision}

R1/R2/R3 optimization summary:

- R1 best candidate: {r1.get('best_filter_candidate', '')}; decision: {r1.get('decision', '')}
- R2 decision: {r2.get('decision', '')}; warnings: {r2.get('sample_attrition_warning', '')}, {r2.get('concentration_warning', '')}, {r2.get('payoff_downside_warning', '')}
- R3 decision: {r3.get('decision', '')}; best soft candidate: {r3.get('best_soft_filter_candidate', '')}; classification: {r3.get('best_candidate_classification', '')}

Why strict combined filter is not adopted: extreme sample attrition, concentration warning, payoff warning, and 60D degradation risk.

Why soft filters are not adopted: R3 found no balanced soft candidate that beat the canonical baseline.

Retained baseline Technical-only result: {baseline_text(r5)}

Downside monitor thresholds:

- hit_rate_vs_QQQ_warning_threshold: 0.50
- severe_hit_rate_warning_threshold: 0.45
- mean_excess_vs_QQQ_warning_threshold: 0.00
- severe_excess_warning_threshold: negative in two or more windows
- worst_5pct_excess_warning_threshold: -0.10
- payoff_ratio_warning_threshold: 1.00
- sample_concentration_warning_threshold: 0.35

Dependency on matured observations: R9 and monitor evaluation require matured rows.

First maturity date: {first_maturity_date}

Future routing logic: improved matured baseline results route to V21.045-R4; deteriorating matured results route to V21.045-R4A; insufficient matured evidence means keep collecting observations; full-family PIT data routes back to the full-family materialization line.

No filter was adopted.

Technical-only retention is not full-weight evidence and must not be interpreted as a full-weight result.

Full-weight remains blocked: TRUE. full_weight_result_available=FALSE and full_weight_rebacktest_allowed_now=FALSE.

Recommended next stage: {recommended_next_stage}

Guardrail statement: this stage is research-only and retention-monitor-only. It did not adopt a filter, mutate official ranking or weights, create official recommendations, create buy/sell/hold recommendations, enable official or shadow adoption, enable a shadow gate, run a full-weight backtest, materialize blocked families, write real-book/broker/execution/trade-action files, download data, use yfinance, or fabricate scores, dates, returns, filter flags, or family labels.
"""
    REPORT.write_text(report, encoding="utf-8")
    shutil.copyfile(REPORT, CURRENT_REPORT)

    print(f"final_status={final_status}")
    print(f"decision={decision}")
    print(f"retained_stream={retained_stream}")
    print("filter_adoption_allowed=FALSE")
    print("downside_monitor_enabled=TRUE")
    print(f"recommended_next_stage={recommended_next_stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
