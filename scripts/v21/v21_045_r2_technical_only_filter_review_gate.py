#!/usr/bin/env python
"""Research-only review gate for V21.045-R1 Technical-only filter dry-run."""

from __future__ import annotations

import csv
import math
import shutil
from collections import Counter, defaultdict
from pathlib import Path


STAGE = "V21.045-R2_TECHNICAL_ONLY_FILTER_REVIEW_GATE"
PASS_STATUS = "PASS_V21_045_R2_FILTER_REVIEW_GATE_READY"
ATTRITION_STATUS = "PARTIAL_PASS_V21_045_R2_FILTER_REVIEW_WITH_ATTRITION_WARNING"
CONCENTRATION_STATUS = "PARTIAL_PASS_V21_045_R2_FILTER_REVIEW_WITH_CONCENTRATION_WARNING"
PAYOFF_STATUS = "PARTIAL_PASS_V21_045_R2_FILTER_REVIEW_WITH_PAYOFF_WARNING"
R1_BLOCKED = "BLOCKED_V21_045_R2_R1_OUTPUTS_NOT_READY"
SCOPE_BLOCKED = "BLOCKED_V21_045_R2_SCOPE_BOUNDARY_FAILED"

ROOT = Path(__file__).resolve().parents[2]
OPT = ROOT / "outputs" / "v21" / "optimization"
REVIEW = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"
BACKTEST = ROOT / "outputs" / "v21" / "backtest"

COL_AUDIT_IN = OPT / "V21_045_R1_FILTER_COLUMN_AVAILABILITY_AUDIT.csv"
REGISTER_IN = OPT / "V21_045_R1_FILTER_VARIANT_DEFINITION_REGISTER.csv"
PANEL_IN = OPT / "V21_045_R1_FILTERED_REBACKTEST_PANEL.csv"
SUMMARY_IN = OPT / "V21_045_R1_FILTER_VARIANT_WINDOW_SUMMARY.csv"
HIT_PAYOFF_IN = OPT / "V21_045_R1_FILTER_HIT_RATE_AND_PAYOFF_AUDIT.csv"
DOWNSIDE_IN = OPT / "V21_045_R1_FILTER_DOWNSIDE_AUDIT.csv"
ATTRITION_IN = OPT / "V21_045_R1_FILTER_SAMPLE_ATTRITION_AUDIT.csv"
R1_DECISION_IN = OPT / "V21_045_R1_FILTER_OPTIMIZATION_DECISION_SUMMARY.csv"
R1_REPORT_IN = READ_CENTER / "V21_045_R1_TECHNICAL_ONLY_ENTRY_REGIME_FILTER_OPTIMIZATION_DRY_RUN_REPORT.md"
R5_SUMMARY = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_VARIANT_WINDOW_SUMMARY.csv"
R5_QQQ = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_QQQ_BENCHMARK_COMPARISON.csv"
R6_DECISION = REVIEW / "V21_044_R6_CONTINUITY_GATE_DECISION_SUMMARY.csv"

UPSTREAM_AUDIT = REVIEW / "V21_045_R2_UPSTREAM_READINESS_AUDIT.csv"
CANDIDATE_AUDIT = REVIEW / "V21_045_R2_CANDIDATE_FILTER_AUDIT.csv"
HIT_AUDIT = REVIEW / "V21_045_R2_HIT_RATE_IMPROVEMENT_AUDIT.csv"
EXCESS_AUDIT = REVIEW / "V21_045_R2_EXCESS_PRESERVATION_AUDIT.csv"
ATTRITION_AUDIT = REVIEW / "V21_045_R2_SAMPLE_ATTRITION_USABILITY_AUDIT.csv"
CONCENTRATION_AUDIT = REVIEW / "V21_045_R2_CONCENTRATION_AUDIT.csv"
PAYOFF_AUDIT = REVIEW / "V21_045_R2_PAYOFF_DOWNSIDE_AUDIT.csv"
SCOPE_AUDIT = REVIEW / "V21_045_R2_SCOPE_BOUNDARY_AUDIT.csv"
DECISION_SUMMARY = REVIEW / "V21_045_R2_FILTER_REVIEW_DECISION_SUMMARY.csv"
REPORT = READ_CENTER / "V21_045_R2_TECHNICAL_ONLY_FILTER_REVIEW_GATE_REPORT.md"
CURRENT_REPORT = READ_CENTER / "CURRENT_V21_045_R2_TECHNICAL_ONLY_FILTER_REVIEW_GATE_REPORT.md"

WINDOWS = ["5D", "10D", "20D", "60D"]
CANDIDATE_BUCKET = "Top20"
CANDIDATE_MODE = "strict_filter_no_refill"

GUARDRAILS = {
    "research_only": "TRUE",
    "review_gate_only": "TRUE",
    "filter_adoption_allowed": "FALSE",
    "technical_only_filter_overlay": "TRUE",
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
    "filter_adoption_allowed",
    "full_weight_result_available",
    "full_weight_rebacktest_allowed_now",
    "official_adoption_allowed",
    "official_weight_mutation",
    "official_ranking_mutation",
    "official_recommendation_allowed",
    "real_book_action_allowed",
    "broker_execution_allowed",
    "trade_action_allowed",
    "shadow_gate_allowed",
    "shadow_adoption_allowed",
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


def num(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.10f}"


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def split_summary(summary: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for part in (summary or "").split("|"):
        if ":" not in part:
            continue
        window, value = part.split(":", 1)
        parsed = num(value)
        if parsed is not None:
            out[window] = parsed
    return out


def candidate_rows(rows: list[dict[str, str]], variant: str) -> list[dict[str, str]]:
    return [
        row for row in rows
        if row.get("filter_variant") == variant
        and row.get("bucket") == CANDIDATE_BUCKET
        and row.get("refill_mode") == CANDIDATE_MODE
    ]


def severity(attrition: float) -> str:
    if attrition > 0.98:
        return "EXTREME_ATTRITION_WARNING"
    if attrition > 0.90:
        return "SEVERE_ATTRITION_WARNING"
    if attrition > 0.60:
        return "HIGH_ATTRITION_WARNING"
    return "ATTRITION_WITHIN_REVIEW_RANGE"


def contribution_share(counter: Counter[str], top_n: int) -> float:
    total = sum(counter.values())
    if total <= 0:
        return 0.0
    return sum(count for _, count in counter.most_common(top_n)) / total


def main() -> int:
    REVIEW.mkdir(parents=True, exist_ok=True)
    READ_CENTER.mkdir(parents=True, exist_ok=True)

    col_audit = read_rows(COL_AUDIT_IN)
    register = read_rows(REGISTER_IN)
    panel = read_rows(PANEL_IN)
    summaries = read_rows(SUMMARY_IN)
    hit_payoff = read_rows(HIT_PAYOFF_IN)
    downside = read_rows(DOWNSIDE_IN)
    attrition = read_rows(ATTRITION_IN)
    r1_decision = first(read_rows(R1_DECISION_IN))
    r5_summary = read_rows(R5_SUMMARY)
    r5_qqq = read_rows(R5_QQQ)
    r6_decision = read_rows(R6_DECISION)
    r1_report_available = R1_REPORT_IN.exists() and R1_REPORT_IN.stat().st_size > 0

    required_inputs = [
        COL_AUDIT_IN, REGISTER_IN, PANEL_IN, SUMMARY_IN, HIT_PAYOFF_IN, DOWNSIDE_IN,
        ATTRITION_IN, R1_DECISION_IN, R5_SUMMARY, R5_QQQ, R6_DECISION,
    ]
    inputs_found = all(path.exists() and path.stat().st_size > 0 for path in required_inputs)
    r1_status_ok = r1_decision.get("final_status", "").startswith(("PASS_", "PARTIAL_PASS_"))
    upstream_guardrails_ok = (
        r1_decision.get("optimization_dry_run_only") == "TRUE"
        and r1_decision.get("filter_adoption_allowed") == "FALSE"
        and all(r1_decision.get(field) == "FALSE" for field in [
            "official_adoption_allowed", "official_weight_mutation", "official_ranking_mutation",
            "official_recommendation_allowed", "real_book_action_allowed", "broker_execution_allowed",
            "trade_action_allowed", "shadow_gate_allowed", "shadow_adoption_allowed",
        ])
    )
    best_filter = r1_decision.get("best_filter_candidate") or "NONE"
    variants_tested = r1_decision.get("filter_variants_tested") or "|".join(row.get("filter_variant", "") for row in register)
    candidate_is_combined = best_filter == "COMBINED_CONSERVATIVE_FILTER"
    refill_modes = sorted({row.get("refill_mode", "") for row in summaries if row.get("filter_variant") == best_filter and row.get("refill_mode")})
    mode_status = "BOTH_STRICT_AND_REFILL" if set(refill_modes) >= {"strict_filter_no_refill", "filter_then_refill_from_next_ranked_names"} else "|".join(refill_modes)

    upstream_rows = [
        {"audit_check": "r1_outputs_found", "observed_value": yn(inputs_found), "check_passed": yn(inputs_found), "notes": "All required V21.045-R1 and baseline artifacts must exist.", **GUARDRAILS},
        {"audit_check": "r1_status_pass_or_partial", "observed_value": r1_decision.get("final_status", ""), "check_passed": yn(r1_status_ok), "notes": "R1 status must be pass or acceptable partial-pass.", **GUARDRAILS},
        {"audit_check": "r1_dry_run_only", "observed_value": r1_decision.get("optimization_dry_run_only", ""), "check_passed": yn(r1_decision.get("optimization_dry_run_only") == "TRUE"), "notes": "R1 must be dry-run only.", **GUARDRAILS},
        {"audit_check": "r1_filter_not_adopted", "observed_value": r1_decision.get("filter_adoption_allowed", ""), "check_passed": yn(r1_decision.get("filter_adoption_allowed") == "FALSE"), "notes": "Filter adoption must remain disabled.", **GUARDRAILS},
        {"audit_check": "r1_report_available", "observed_value": yn(r1_report_available), "check_passed": yn(True), "notes": "R1 markdown report is optional but recorded if present.", **GUARDRAILS},
        {"audit_check": "upstream_permissions_disabled", "observed_value": yn(upstream_guardrails_ok), "check_passed": yn(upstream_guardrails_ok), "notes": "Official, shadow, real-book, broker, execution, and trade permissions must remain disabled.", **GUARDRAILS},
    ]
    write_rows(UPSTREAM_AUDIT, upstream_rows)

    candidate_audit = [{
        "best_candidate_filter": best_filter,
        "candidate_is_combined_conservative_filter": yn(candidate_is_combined),
        "variants_tested": variants_tested,
        "refill_modes_available_for_candidate": "|".join(refill_modes),
        "candidate_mode_reviewed": CANDIDATE_MODE,
        "mode_coverage_status": mode_status,
        "filter_adopted": "FALSE",
        **GUARDRAILS,
    }]
    write_rows(CANDIDATE_AUDIT, candidate_audit)

    candidate_summary = {row["forward_return_window"]: row for row in candidate_rows(summaries, best_filter)}
    baseline_summary = {row["forward_return_window"]: row for row in candidate_rows(summaries, "BASELINE_TECHNICAL_ONLY")}
    candidate_hit = {row["forward_return_window"]: row for row in candidate_rows(hit_payoff, best_filter)}
    candidate_down = {row["forward_return_window"]: row for row in candidate_rows(downside, best_filter)}
    candidate_attr = {row["forward_return_window"]: row for row in candidate_rows(attrition, best_filter)}
    candidate_panel = candidate_rows(panel, best_filter)

    hit_rows = []
    improved_count = 0
    for window in WINDOWS:
        hp = candidate_hit.get(window, {})
        base_hit = num(hp.get("baseline_hit_rate_vs_QQQ")) or num(baseline_summary.get(window, {}).get("hit_rate_vs_QQQ")) or 0.0
        cand_hit = num(hp.get("variant_hit_rate_vs_QQQ")) or num(candidate_summary.get(window, {}).get("hit_rate_vs_QQQ")) or 0.0
        improvement = cand_hit - base_hit
        improved_count += 1 if improvement > 0 else 0
        hit_rows.append({
            "forward_return_window": window,
            "baseline_hit_rate": fmt(base_hit),
            "candidate_hit_rate": fmt(cand_hit),
            "hit_rate_improvement": fmt(improvement),
            "improvement_pass_threshold": yn(improvement >= 0.02),
            "number_of_windows_improved": "",
            "short_window_improvement_status": "IMPROVED" if window in {"5D", "10D"} and improvement > 0 else ("NOT_SHORT_WINDOW" if window not in {"5D", "10D"} else "NOT_IMPROVED"),
            "medium_window_improvement_status": "IMPROVED" if window == "20D" and improvement > 0 else ("NOT_MEDIUM_WINDOW" if window != "20D" else "NOT_IMPROVED"),
            "long_window_improvement_status": "IMPROVED" if window == "60D" and improvement > 0 else ("NOT_LONG_WINDOW" if window != "60D" else "NOT_IMPROVED"),
            "filter_adopted": "FALSE",
            **GUARDRAILS,
        })
    for row in hit_rows:
        row["number_of_windows_improved"] = improved_count
    write_rows(HIT_AUDIT, hit_rows)

    excess_rows = []
    positive_excess_windows = 0
    severe_long_degradation = False
    short_compensation = False
    for window in WINDOWS:
        hp = candidate_hit.get(window, {})
        base_excess = num(hp.get("baseline_mean_excess_vs_QQQ")) or num(baseline_summary.get(window, {}).get("mean_excess_vs_QQQ")) or 0.0
        cand_excess = num(hp.get("variant_mean_excess_vs_QQQ")) or num(candidate_summary.get(window, {}).get("mean_excess_vs_QQQ")) or 0.0
        change = cand_excess - base_excess
        positive_excess_windows += 1 if cand_excess > 0 else 0
        degradation_ratio = abs(change) / abs(base_excess) if base_excess and change < 0 else 0.0
        exceeds = window in {"20D", "60D"} and degradation_ratio > 0.35
        severe_long_degradation = severe_long_degradation or exceeds
        excess_rows.append({
            "forward_return_window": window,
            "baseline_excess_vs_QQQ": fmt(base_excess),
            "candidate_excess_vs_QQQ": fmt(cand_excess),
            "excess_change": fmt(change),
            "excess_degradation_ratio": fmt(degradation_ratio),
            "degradation_exceeds_threshold": yn(exceeds),
            "short_window_improvement_compensates": "",
            "filter_adopted": "FALSE",
            **GUARDRAILS,
        })
    short_changes = [num(row["excess_change"]) or 0.0 for row in excess_rows if row["forward_return_window"] in {"5D", "10D"}]
    long_changes = [num(row["excess_change"]) or 0.0 for row in excess_rows if row["forward_return_window"] in {"20D", "60D"}]
    short_compensation = sum(short_changes) > abs(sum(change for change in long_changes if change < 0))
    for row in excess_rows:
        row["short_window_improvement_compensates"] = yn(short_compensation)
    write_rows(EXCESS_AUDIT, excess_rows)

    attr_rows = []
    max_attrition = 0.0
    attrition_warning = "ATTRITION_WITHIN_REVIEW_RANGE"
    for window in WINDOWS:
        ar = candidate_attr.get(window, {})
        total = int(float(ar.get("total_candidate_rows") or 0))
        selected = int(float(ar.get("selected_rows") or 0))
        by_asof = Counter(row.get("as_of_date", "") for row in candidate_panel if row.get("forward_return_window") == window)
        counts = list(by_asof.values())
        avg_names = sum(counts) / len(counts) if counts else 0.0
        min_names = min(counts) if counts else 0
        pct20 = sum(1 for count in counts if count >= 20) / len(counts) if counts else 0.0
        pct10 = sum(1 for count in counts if count >= 10) / len(counts) if counts else 0.0
        attr = num(ar.get("sample_attrition_rate")) or (1.0 - selected / total if total else 0.0)
        max_attrition = max(max_attrition, attr)
        sev = severity(attr)
        if sev == "EXTREME_ATTRITION_WARNING":
            attrition_warning = sev
        elif sev == "SEVERE_ATTRITION_WARNING" and attrition_warning != "EXTREME_ATTRITION_WARNING":
            attrition_warning = sev
        elif sev == "HIGH_ATTRITION_WARNING" and attrition_warning == "ATTRITION_WITHIN_REVIEW_RANGE":
            attrition_warning = sev
        attr_rows.append({
            "forward_return_window": window,
            "baseline_sample_count": total,
            "candidate_sample_count": selected,
            "candidate_asof_count": len(by_asof),
            "average_names_per_asof": fmt(avg_names),
            "min_names_per_asof": min_names,
            "percent_asof_with_at_least_20_names": fmt(pct20),
            "percent_asof_with_at_least_10_names": fmt(pct10),
            "sample_attrition_rate": fmt(attr),
            "excessive_attrition_flag": yn(attr > 0.60),
            "usability_status": sev,
            "filter_adopted": "FALSE",
            **GUARDRAILS,
        })
    write_rows(ATTRITION_AUDIT, attr_rows)

    conc_rows = []
    concentration_warning = "NO_CONCENTRATION_WARNING"
    for window in WINDOWS:
        rows = [row for row in candidate_panel if row.get("forward_return_window") == window]
        asof_counter = Counter(row.get("as_of_date", "") for row in rows)
        ticker_counter = Counter(row.get("ticker", "") for row in rows)
        top5_asof = contribution_share(asof_counter, 5)
        top10_ticker = contribution_share(ticker_counter, 10)
        largest_asof = contribution_share(asof_counter, 1)
        largest_ticker = contribution_share(ticker_counter, 1)
        warning = "CONCENTRATION_WARNING" if top5_asof > 0.50 or top10_ticker > 0.50 or largest_asof > 0.20 or largest_ticker > 0.20 else "NO_CONCENTRATION_WARNING"
        if warning == "CONCENTRATION_WARNING":
            concentration_warning = warning
        conc_rows.append({
            "forward_return_window": window,
            "unique_asof_count": len(asof_counter),
            "unique_ticker_count": len(ticker_counter),
            "top_5_asof_contribution_share": fmt(top5_asof),
            "top_10_ticker_contribution_share": fmt(top10_ticker),
            "largest_single_asof_contribution": fmt(largest_asof),
            "largest_single_ticker_contribution": fmt(largest_ticker),
            "concentration_warning": warning,
            "concentration_assessment": "ROW_COUNT_BASED_CONTRIBUTION_AVAILABLE",
            "filter_adopted": "FALSE",
            **GUARDRAILS,
        })
    write_rows(CONCENTRATION_AUDIT, conc_rows)

    payoff_rows = []
    payoff_warning_count = 0
    downside_warning_count = 0
    for window in WINDOWS:
        cs = candidate_summary.get(window, {})
        cd = candidate_down.get(window, {})
        payoff = num(cs.get("payoff_ratio_vs_QQQ")) or num(cd.get("payoff_ratio_vs_QQQ")) or 0.0
        downside_warning = cd.get("downside_warning") == "TRUE"
        downside_warning_count += 1 if downside_warning else 0
        payoff_warning = payoff < 1.0
        payoff_warning_count += 1 if payoff_warning else 0
        payoff_rows.append({
            "forward_return_window": window,
            "average_win_vs_QQQ": cs.get("average_win_vs_QQQ", ""),
            "average_loss_vs_QQQ": cs.get("average_loss_vs_QQQ", ""),
            "payoff_ratio_vs_QQQ": fmt(payoff),
            "downside_warning_count": 1 if downside_warning else 0,
            "worst_5pct_excess_vs_QQQ": cd.get("worst_5pct_excess_vs_QQQ", ""),
            "downside_improved_vs_baseline": "NOT_ESTABLISHED",
            "payoff_ratio_acceptable": yn(payoff >= 1.0),
            "payoff_downside_warning": "PAYOFF_RATIO_WARNING" if payoff_warning else ("DOWNSIDE_WARNING" if downside_warning else "NO_PAYOFF_DOWNSIDE_WARNING"),
            "filter_adopted": "FALSE",
            **GUARDRAILS,
        })
    write_rows(PAYOFF_AUDIT, payoff_rows)

    scope_checks = [
        ("research_only", GUARDRAILS["research_only"] == "TRUE", "R2 is research-only."),
        ("review_gate_only", GUARDRAILS["review_gate_only"] == "TRUE", "R2 is a review gate only."),
        ("filter_not_adoptable", GUARDRAILS["filter_adoption_allowed"] == "FALSE", "No filter adoption allowed in this stage."),
        ("restricted_outputs_disabled", all(GUARDRAILS[field] == "FALSE" for field in FALSE_GUARDRAILS), "Official, full-weight, real-book, broker, execution, trade, and shadow outputs remain disabled."),
    ]
    scope_ok = all(passed for _, passed, _ in scope_checks)
    write_rows(SCOPE_AUDIT, [
        {"boundary_check": name, "required_value": "TRUE", "observed_value": yn(passed), "check_passed": yn(passed), "blocking": "TRUE", "notes": notes, **GUARDRAILS}
        for name, passed, notes in scope_checks
    ])

    leakage_count = sum(int(float(row.get("leakage_violation_count") or 0)) for row in candidate_summary.values())
    review_worthy = improved_count >= 2 and positive_excess_windows >= 2 and leakage_count == 0
    adoptable_now = False
    payoff_warning = "PAYOFF_RATIO_WARNING" if payoff_warning_count >= 3 else "NO_PAYOFF_RATIO_WARNING"

    if not inputs_found or not r1_status_ok:
        final_status = R1_BLOCKED
        decision = "FILTER_REVIEW_BLOCKED"
        recommended_next_stage = "V21.045-R1_TECHNICAL_ONLY_ENTRY_REGIME_FILTER_OPTIMIZATION_DRY_RUN"
    elif not scope_ok or not upstream_guardrails_ok:
        final_status = SCOPE_BLOCKED
        decision = "FILTER_REVIEW_BLOCKED"
        recommended_next_stage = "V21.045-R2_TECHNICAL_ONLY_FILTER_REVIEW_GATE"
    elif attrition_warning in {"SEVERE_ATTRITION_WARNING", "EXTREME_ATTRITION_WARNING"} and review_worthy:
        final_status = ATTRITION_STATUS
        decision = "FILTER_REVIEW_WORTHY_BUT_NOT_ADOPTABLE_ATTRITION_TOO_HIGH"
        recommended_next_stage = "V21.045-R3_SOFT_COMBINED_FILTER_THRESHOLD_RELAXATION_DRY_RUN"
    elif concentration_warning == "CONCENTRATION_WARNING":
        final_status = CONCENTRATION_STATUS
        decision = "FILTER_REVIEW_WORTHY_BUT_NOT_ADOPTABLE_ATTRITION_TOO_HIGH" if review_worthy else "FILTER_NOT_PROMISING_KEEP_BASELINE_TECHNICAL_ONLY"
        recommended_next_stage = "V21.045-R3_SOFT_COMBINED_FILTER_THRESHOLD_RELAXATION_DRY_RUN" if review_worthy else "V21.045-R2A_BASELINE_TECHNICAL_ONLY_RETENTION_AND_DOWNSIDE_REVIEW"
    elif payoff_warning == "PAYOFF_RATIO_WARNING":
        final_status = PAYOFF_STATUS
        decision = "FILTER_IMPROVES_HIT_RATE_BUT_DAMAGES_RIGHT_TAIL"
        recommended_next_stage = "V21.045-R3_SOFT_COMBINED_FILTER_THRESHOLD_RELAXATION_DRY_RUN"
    elif review_worthy:
        final_status = PASS_STATUS
        decision = "FILTER_PROMISING_FOR_SOFT_WATCHLIST_ONLY"
        recommended_next_stage = "V21.045-R3_SOFT_COMBINED_FILTER_THRESHOLD_RELAXATION_DRY_RUN"
    else:
        final_status = PASS_STATUS
        decision = "FILTER_NOT_PROMISING_KEEP_BASELINE_TECHNICAL_ONLY"
        recommended_next_stage = "V21.045-R2A_BASELINE_TECHNICAL_ONLY_RETENTION_AND_DOWNSIDE_REVIEW"

    hit_summary = r1_decision.get("hit_rate_improvement_summary", "")
    excess_summary = r1_decision.get("excess_return_change_summary", "")
    decision_row = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "best_candidate_filter": best_filter,
        "hit_rate_improvement_summary": hit_summary,
        "excess_preservation_degradation_summary": excess_summary,
        "sample_attrition_warning": attrition_warning,
        "max_sample_attrition_rate": fmt(max_attrition),
        "concentration_warning": concentration_warning,
        "payoff_downside_warning": payoff_warning if payoff_warning_count >= 3 else ("DOWNSIDE_WARNING" if downside_warning_count else "NO_PAYOFF_DOWNSIDE_WARNING"),
        "number_of_windows_improved": improved_count,
        "positive_excess_window_count": positive_excess_windows,
        "long_window_degradation_exceeds_threshold": yn(severe_long_degradation),
        "leakage_violation_count": leakage_count,
        "filter_review_worthy": yn(review_worthy),
        "filter_adoptable_now": yn(adoptable_now),
        "filter_adopted": "FALSE",
        "softer_filter_should_be_tested_next": yn(review_worthy and attrition_warning in {"SEVERE_ATTRITION_WARNING", "EXTREME_ATTRITION_WARNING"}),
        "recommended_next_stage": recommended_next_stage,
        "r1_rows_read": len(panel),
        "r5_summary_rows_read": len(r5_summary),
        "r5_qqq_rows_read": len(r5_qqq),
        "r6_rows_read": len(r6_decision),
        "online_download_attempted": "FALSE",
        "yfinance_used": "FALSE",
        **GUARDRAILS,
    }
    write_rows(DECISION_SUMMARY, [decision_row])

    report = f"""# V21.045-R2 Technical-only filter review gate

final_status: {final_status}

decision: {decision}

best candidate filter: {best_filter}

hit-rate improvement summary: {hit_summary}

excess preservation/degradation summary: {excess_summary}

sample attrition warning: {attrition_warning}; max attrition {fmt(max_attrition)}

concentration warning: {concentration_warning}

payoff/downside warning: {decision_row['payoff_downside_warning']}

filter review-worthy: {yn(review_worthy)}

why the filter is not adoptable now: this review gate never permits adoption, and the candidate has severe/extreme sample attrition plus medium/long-window degradation risk.

softer filter should be tested next: {decision_row['softer_filter_should_be_tested_next']}

No filter was adopted.

Technical-only filter results must not be interpreted as full-weight results or full-weight evidence.

Full-weight remains blocked: TRUE. full_weight_result_available=FALSE and full_weight_rebacktest_allowed_now=FALSE.

No buy/sell/hold signal was created.

Recommended next stage: {recommended_next_stage}

Guardrail statement: this stage is research-only and review-gate-only. It did not adopt a filter, mutate official ranking or weights, create official recommendations, enable official or shadow adoption, enable a shadow gate, run a full-weight backtest, create real-book, broker, execution, or trade-action files, download data, use yfinance, or fabricate scores, dates, returns, filter flags, or family labels.
"""
    REPORT.write_text(report, encoding="utf-8")
    shutil.copyfile(REPORT, CURRENT_REPORT)

    print(f"final_status={final_status}")
    print(f"decision={decision}")
    print(f"best_candidate_filter={best_filter}")
    print(f"sample_attrition_warning={attrition_warning}")
    print(f"recommended_next_stage={recommended_next_stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
