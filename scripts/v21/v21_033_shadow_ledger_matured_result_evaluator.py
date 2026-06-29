#!/usr/bin/env python
"""V21.033 shadow ledger matured result evaluator.

Research-only evaluator for V21.030 matured shadow ledger results. It audits
context overlap before allowing any context alpha interpretation.
"""

from __future__ import annotations

import csv
import itertools
import math
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median


STAGE_NAME = "V21_033_SHADOW_LEDGER_MATURED_RESULT_EVALUATOR"
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "shadow_observation"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

SUMMARY_OUT = OUT_DIR / "V21_033_MATURED_RESULT_EVALUATION_SUMMARY.csv"
CONTEXT_PERF = OUT_DIR / "V21_033_CONTEXT_PERFORMANCE_EVALUATION.csv"
OVERLAP = OUT_DIR / "V21_033_CONTEXT_OVERLAP_AUDIT.csv"
DISCRIM = OUT_DIR / "V21_033_CONTEXT_DISCRIMINATION_AUDIT.csv"
WINDOW_EVAL = OUT_DIR / "V21_033_FORWARD_WINDOW_EVALUATION.csv"
DECISION = OUT_DIR / "V21_033_SHADOW_EVALUATOR_DECISION.csv"
REPORT = READ_CENTER_DIR / "V21_033_SHADOW_LEDGER_MATURED_RESULT_EVALUATOR_REPORT.md"

INPUTS = [
    OUT_DIR / "V21_030_SHADOW_OBSERVATION_LEDGER_MATURITY_TRACKER_SUMMARY.csv",
    OUT_DIR / "V21_030_REALIZED_FORWARD_RETURNS.csv",
    OUT_DIR / "V21_030_PENDING_OBSERVATIONS.csv",
    OUT_DIR / "V21_030_MATURITY_SUMMARY_BY_CONTEXT.csv",
    OUT_DIR / "V21_030_LEDGER_INTEGRITY_AUDIT.csv",
    OUT_DIR / "V21_030_FALLBACK_SNAPSHOT_LIMITATION_AUDIT.csv",
    OUT_DIR / "V21_030_SHADOW_LEDGER_MATURITY_TRACKER_DECISION.csv",
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
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


def fmt(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.10f}"
    return value


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def fnum(value: object) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def stats(values: list[float]) -> dict[str, object]:
    pos = sum(1 for v in values if v > 0)
    neg = sum(1 for v in values if v < 0)
    zero = sum(1 for v in values if v == 0)
    if not values:
        return {
            "mean_realized_forward_return": None,
            "median_realized_forward_return": None,
            "hit_rate": None,
            "positive_count": 0,
            "negative_count": 0,
            "zero_count": 0,
            "min_realized_forward_return": None,
            "max_realized_forward_return": None,
            "std_realized_forward_return": None,
        }
    mu = mean(values)
    sd = math.sqrt(sum((v - mu) ** 2 for v in values) / (len(values) - 1)) if len(values) > 1 else 0.0
    return {
        "mean_realized_forward_return": mu,
        "median_realized_forward_return": median(values),
        "hit_rate": pos / len(values),
        "positive_count": pos,
        "negative_count": neg,
        "zero_count": zero,
        "min_realized_forward_return": min(values),
        "max_realized_forward_return": max(values),
        "std_realized_forward_return": sd,
    }


def context_key(row: dict[str, str]) -> str:
    return row.get("context_combination") or row.get("context_label") or "UNKNOWN_CONTEXT"


def metric_tuple(row: dict[str, object]) -> tuple[object, object, object]:
    return (
        fmt(row.get("mean_realized_forward_return")),
        fmt(row.get("median_realized_forward_return")),
        fmt(row.get("hit_rate")),
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    missing = [p.name for p in INPUTS if not p.exists() or p.stat().st_size == 0]
    summary_030 = first(read_csv(OUT_DIR / "V21_030_SHADOW_OBSERVATION_LEDGER_MATURITY_TRACKER_SUMMARY.csv"))
    decision_030 = first(read_csv(OUT_DIR / "V21_030_SHADOW_LEDGER_MATURITY_TRACKER_DECISION.csv"))
    realized = read_csv(OUT_DIR / "V21_030_REALIZED_FORWARD_RETURNS.csv")
    pending = read_csv(OUT_DIR / "V21_030_PENDING_OBSERVATIONS.csv")
    fallback = first(read_csv(OUT_DIR / "V21_030_FALLBACK_SNAPSHOT_LIMITATION_AUDIT.csv"))
    integrity = first(read_csv(OUT_DIR / "V21_030_LEDGER_INTEGRITY_AUDIT.csv"))

    values = [fnum(r.get("realized_forward_return")) for r in realized]
    values = [v for v in values if v is not None]
    overall = stats(values)

    by_context_window: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    by_context: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_window: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in realized:
        ck = context_key(row)
        by_context_window[(ck, row.get("forward_return_window", ""))].append(row)
        by_context[ck].append(row)
        by_window[row.get("forward_return_window", "")].append(row)

    context_perf_rows = []
    for (ck, window), rows in sorted(by_context_window.items()):
        vals = [fnum(r.get("realized_forward_return")) for r in rows]
        vals = [v for v in vals if v is not None]
        s = stats(vals)
        scheduled = sum(1 for r in read_csv(OUT_DIR / "V21_030_FORWARD_SCHEDULE_MATURITY_AUDIT.csv") if (r.get("context_combination") or r.get("context_label") or "UNKNOWN_CONTEXT") == ck and r.get("forward_return_window") == window)
        pending_count = sum(1 for r in pending if (r.get("context_combination") or r.get("context_label") or "UNKNOWN_CONTEXT") == ck and r.get("forward_return_window") == window)
        price_missing = sum(1 for r in read_csv(OUT_DIR / "V21_030_FORWARD_SCHEDULE_MATURITY_AUDIT.csv") if (r.get("context_combination") or r.get("context_label") or "UNKNOWN_CONTEXT") == ck and r.get("forward_return_window") == window and r.get("maturity_status") == "MATURED_PRICE_MISSING")
        sample_status = "SUFFICIENT" if len(vals) >= 20 else "INSUFFICIENT_SAMPLE"
        perf_status = "POSITIVE_CONTEXT_RETURN" if s["hit_rate"] is not None and fnum(s["mean_realized_forward_return"]) and fnum(s["mean_realized_forward_return"]) > 0 else "NON_POSITIVE_OR_INCONCLUSIVE"
        context_perf_rows.append({
            "context_key": ck,
            "forward_return_window": window,
            "scheduled_count": scheduled,
            "matured_count": len(vals),
            "pending_count": pending_count,
            "price_missing_count": price_missing,
            **s,
            "sample_sufficiency_status": sample_status,
            "context_performance_status": perf_status,
        })

    identity_by_context: dict[str, set[tuple[str, str, str, str]]] = {}
    metrics_by_context: dict[str, tuple[object, object, object]] = {}
    for ck, rows in by_context.items():
        identity_by_context[ck] = {
            (r.get("ticker", ""), r.get("as_of_date", ""), r.get("forward_return_window", ""), fmt(fnum(r.get("realized_forward_return"))))
            for r in rows
        }
        vals = [fnum(r.get("realized_forward_return")) for r in rows]
        vals = [v for v in vals if v is not None]
        metrics_by_context[ck] = metric_tuple(stats(vals))

    overlap_rows = []
    ratios = []
    exact_metric_match_count = 0
    for a, b in itertools.combinations(sorted(identity_by_context), 2):
        ia, ib = identity_by_context[a], identity_by_context[b]
        shared = ia & ib
        ra = len(shared) / len(ia) if ia else 0.0
        rb = len(shared) / len(ib) if ib else 0.0
        ratios.extend([ra, rb])
        exact_metrics = metrics_by_context.get(a) == metrics_by_context.get(b)
        exact_metric_match_count += 1 if exact_metrics else 0
        same_mean = metrics_by_context.get(a, ("", "", ""))[0] == metrics_by_context.get(b, ("", "", ""))[0]
        same_median = metrics_by_context.get(a, ("", "", ""))[1] == metrics_by_context.get(b, ("", "", ""))[1]
        same_hit = metrics_by_context.get(a, ("", "", ""))[2] == metrics_by_context.get(b, ("", "", ""))[2]
        status = "NOT_INDEPENDENT_HIGH_OVERLAP" if max(ra, rb) >= 0.80 else "PARTIAL_OVERLAP" if shared else "NO_SHARED_MATURED_IDENTITIES"
        overlap_rows.append({
            "context_key_a": a,
            "context_key_b": b,
            "matured_count_a": len(ia),
            "matured_count_b": len(ib),
            "shared_matured_observation_identity_count": len(shared),
            "overlap_ratio_a_to_b": ra,
            "overlap_ratio_b_to_a": rb,
            "exact_metric_match": "TRUE" if exact_metrics else "FALSE",
            "same_mean_return": "TRUE" if same_mean else "FALSE",
            "same_median_return": "TRUE" if same_median else "FALSE",
            "same_hit_rate": "TRUE" if same_hit else "FALSE",
            "context_independence_status": status,
        })

    metric_set = set(metrics_by_context.values())
    all_identical = bool(metrics_by_context) and len(metric_set) == 1
    max_overlap = max(ratios) if ratios else 0.0
    avg_overlap = mean(ratios) if ratios else 0.0
    if all_identical:
        discr_status = "CONTEXT_DISCRIMINATION_FAILED_IDENTICAL_METRICS"
        alpha_allowed = "FALSE"
        reason = "All context-level mean, median, and hit-rate metrics are identical; context alpha cannot be interpreted."
    elif max_overlap >= 0.80:
        discr_status = "CONTEXT_DISCRIMINATION_FAILED_HIGH_OVERLAP"
        alpha_allowed = "FALSE"
        reason = "Pairwise matured observation overlap is too high for independent context interpretation."
    else:
        discr_status = "CONTEXT_DISCRIMINATION_AVAILABLE"
        alpha_allowed = "TRUE"
        reason = "Context metrics differ and pairwise overlap is below the high-overlap threshold."
    discr_rows = [{
        "distinct_context_key_count": len(by_context),
        "exact_duplicate_metric_context_count": exact_metric_match_count,
        "max_pairwise_overlap_ratio": max_overlap,
        "average_pairwise_overlap_ratio": avg_overlap,
        "all_context_metrics_identical": "TRUE" if all_identical else "FALSE",
        "context_discrimination_status": discr_status,
        "alpha_interpretation_allowed": alpha_allowed,
        "reason": reason,
    }]

    window_rows = []
    for window, rows in sorted(by_window.items()):
        vals = [fnum(r.get("realized_forward_return")) for r in rows]
        vals = [v for v in vals if v is not None]
        s = stats(vals)
        status = "WINDOW_POSITIVE" if s["mean_realized_forward_return"] is not None and fnum(s["mean_realized_forward_return"]) > 0 else "WINDOW_NON_POSITIVE_OR_INCONCLUSIVE"
        window_rows.append({"forward_return_window": window, "matured_count": len(vals), **s, "window_performance_status": status})

    fallback_blocks_current = fallback.get("fallback_prevents_current_daily_observation_use") == "TRUE"
    current_allowed = "FALSE" if fallback_blocks_current else "TRUE"
    if missing or summary_030.get("final_status") != "PASS_V21_030_SHADOW_LEDGER_MATURITY_TRACKER_READY_WITH_MATURED_RESULTS":
        evaluator_decision = "NO_MATURED_RESULTS_AVAILABLE" if not realized else "MATURED_RESULTS_AVAILABLE_BUT_INPUT_STATUS_INCONCLUSIVE"
        final_status = "BLOCKED_V21_033_NO_MATURED_RESULTS" if not realized else "PARTIAL_PASS_V21_033_MATURED_RESULTS_AVAILABLE_CONTEXT_DISCRIMINATION_FAILED"
        next_stage = "V21.030_SHADOW_OBSERVATION_LEDGER_MATURITY_TRACKER"
        alpha_allowed = "FALSE"
    elif not realized:
        final_status = "BLOCKED_V21_033_NO_MATURED_RESULTS"
        evaluator_decision = "NO_MATURED_RESULTS_AVAILABLE"
        next_stage = "V21.030_SHADOW_OBSERVATION_LEDGER_MATURITY_TRACKER"
        alpha_allowed = "FALSE"
    elif alpha_allowed == "FALSE":
        final_status = "PARTIAL_PASS_V21_033_MATURED_RESULTS_AVAILABLE_CONTEXT_DISCRIMINATION_FAILED"
        evaluator_decision = "MATURED_RESULTS_AVAILABLE_BUT_CONTEXT_ALPHA_NOT_INTERPRETABLE"
        next_stage = "V21.034_CONTEXT_DEDUPLICATED_OBSERVATION_REBUILDER"
    else:
        final_status = "PASS_V21_033_MATURED_RESULTS_EVALUATED_CONTEXT_DIFFERENTIATION_AVAILABLE"
        evaluator_decision = "MATURED_RESULTS_EVALUATED_CONTEXT_DIFFERENTIATION_AVAILABLE"
        next_stage = "V21.034_CONTEXT_EDGE_STABILITY_EVALUATOR"

    decision_rows = [{
        "evaluator_decision": evaluator_decision,
        "final_status": final_status,
        "official_use_allowed": "FALSE",
        "official_ranking_readiness_allowed": "FALSE",
        "official_weight_update_readiness_allowed": "FALSE",
        "official_weight_update_blocked": "TRUE",
        "broker_execution_supported": "FALSE",
        "shadow_activation": "FALSE",
        "context_alpha_interpretation_allowed": alpha_allowed,
        "current_daily_observation_allowed": current_allowed,
        "recommended_next_stage": next_stage,
        "selected_recommended_next_stage": "TRUE",
        "research_only": "TRUE",
    }]

    total_rows = int(summary_030.get("ledger_row_count") or len(realized) + len(pending))
    summary_rows = [{
        "final_status": final_status,
        "evaluator_decision": evaluator_decision,
        "total_ledger_rows": total_rows,
        "matured_row_count": len(realized),
        "pending_row_count": len(pending),
        "price_missing_row_count": int(summary_030.get("price_missing_count") or 0),
        "distinct_context_key_count": len(by_context),
        "distinct_ticker_count": len({r.get("ticker", "") for r in realized}),
        "distinct_as_of_date_count": len({r.get("as_of_date", "") for r in realized}),
        "distinct_forward_return_window_count": len({r.get("forward_return_window", "") for r in realized}),
        "mean_realized_forward_return": overall["mean_realized_forward_return"],
        "median_realized_forward_return": overall["median_realized_forward_return"],
        "overall_hit_rate": overall["hit_rate"],
        "fallback_snapshot_status": summary_030.get("fallback_snapshot_status", ""),
        "fallback_as_of_date": fallback.get("fallback_as_of_date", ""),
        "latest_available_current_daily_candidate_date": fallback.get("latest_available_current_daily_candidate_date", ""),
        "fallback_date_gap_days": fallback.get("date_gap_days", ""),
        "current_daily_observation_allowed": current_allowed,
        "research_only": "TRUE",
    }]

    write_csv(SUMMARY_OUT, summary_rows, list(summary_rows[0].keys()))
    write_csv(CONTEXT_PERF, context_perf_rows, ["context_key", "forward_return_window", "scheduled_count", "matured_count", "pending_count", "price_missing_count", "mean_realized_forward_return", "median_realized_forward_return", "hit_rate", "positive_count", "negative_count", "zero_count", "min_realized_forward_return", "max_realized_forward_return", "std_realized_forward_return", "sample_sufficiency_status", "context_performance_status"])
    write_csv(OVERLAP, overlap_rows, ["context_key_a", "context_key_b", "matured_count_a", "matured_count_b", "shared_matured_observation_identity_count", "overlap_ratio_a_to_b", "overlap_ratio_b_to_a", "exact_metric_match", "same_mean_return", "same_median_return", "same_hit_rate", "context_independence_status"])
    write_csv(DISCRIM, discr_rows, ["distinct_context_key_count", "exact_duplicate_metric_context_count", "max_pairwise_overlap_ratio", "average_pairwise_overlap_ratio", "all_context_metrics_identical", "context_discrimination_status", "alpha_interpretation_allowed", "reason"])
    write_csv(WINDOW_EVAL, window_rows, ["forward_return_window", "matured_count", "mean_realized_forward_return", "median_realized_forward_return", "hit_rate", "positive_count", "negative_count", "zero_count", "std_realized_forward_return", "window_performance_status"])
    write_csv(DECISION, decision_rows, list(decision_rows[0].keys()))

    REPORT.write_text(f"""# V21.033 Shadow Ledger Matured Result Evaluator Report

## Executive summary
This research-only evaluator consumed V21.030 matured shadow observation results. It found {len(realized)} matured rows and {len(pending)} pending rows.

## Final evaluator decision
{evaluator_decision}

Final status: {final_status}

## V21.030 input status
V21.030 status: {summary_030.get('final_status', '')}. Decision: {summary_030.get('maturity_tracker_decision', '')}.

## Matured versus pending status
Matured rows: {len(realized)}. Pending rows: {len(pending)}. Price-missing rows: {summary_rows[0]['price_missing_row_count']}.

## Overall realized forward return results
Mean realized return: {fmt(overall['mean_realized_forward_return'])}. Median: {fmt(overall['median_realized_forward_return'])}. Hit rate: {fmt(overall['hit_rate'])}.

## Context-level result table
See V21_033_CONTEXT_PERFORMANCE_EVALUATION.csv.

## Forward-window result table
See V21_033_FORWARD_WINDOW_EVALUATION.csv.

## Context overlap audit result
Context overlap warning: {reason}

## Context alpha interpretation
Context alpha interpretation allowed: {alpha_allowed}.

## Fallback snapshot limitation
Fallback limitation: V21.030 used {fallback.get('fallback_as_of_date', '')}, latest current candidate date is {fallback.get('latest_available_current_daily_candidate_date', '')}, gap is {fallback.get('date_gap_days', '')} days, and current daily observation allowed is {current_allowed}.

## Guardrail status
Official use, ranking readiness, weight update readiness, broker execution, and shadow activation remain blocked. This evaluator does not mutate official rankings or weights and creates no recommendations or trades.

## Recommended next stage
{next_stage}
""", encoding="utf-8")

    print(f"STAGE_NAME={STAGE_NAME}")
    print(f"final_status={final_status}")
    print(f"evaluator_decision={evaluator_decision}")
    print(f"matured_row_count={len(realized)}")
    print(f"pending_row_count={len(pending)}")
    print(f"recommended_next_stage={next_stage}")
    print("official_use_allowed=FALSE")
    print("official_ranking_readiness_allowed=FALSE")
    print("official_weight_update_readiness_allowed=FALSE")
    print("official_weight_update_blocked=TRUE")
    print("broker_execution_supported=FALSE")
    print("shadow_activation=FALSE")
    print("research_only=TRUE")


if __name__ == "__main__":
    main()
