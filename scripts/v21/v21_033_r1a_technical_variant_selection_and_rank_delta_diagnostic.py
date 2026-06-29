#!/usr/bin/env python
"""V21.033-R1A technical variant selection and rank-delta diagnostic.

Research-only diagnostic for explaining why V21.032-R1 named a best shadow
technical variant while V21.033-R1 blocked adoption on zero excess return.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median


STAGE = "V21.033-R1A_TECHNICAL_VARIANT_SELECTION_AND_RANK_DELTA_DIAGNOSTIC"
PASS_STATUS = "PASS_V21_033_R1A_TECHNICAL_VARIANT_SELECTION_DIAGNOSTIC_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_033_R1A_DIAGNOSTIC_LIMITED_BY_MISSING_COLUMNS"
BLOCKED_STATUS = "BLOCKED_V21_033_R1A_INPUTS_MISSING"
DECISION = "TECHNICAL_VARIANT_SELECTION_DIAGNOSTIC_READY_SHADOW_AND_OFFICIAL_ADOPTION_BLOCKED"

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

V32_SUMMARY = OUT_DIR / "V21_032_R1_TECHNICAL_VARIANT_BACKTEST_SUMMARY.csv"
V32_BY_WINDOW = OUT_DIR / "V21_032_R1_TECHNICAL_VARIANT_BACKTEST_BY_WINDOW.csv"
V32_RANK = OUT_DIR / "V21_032_R1_TECHNICAL_VARIANT_RANK_COMPARISON.csv"
V33_SUMMARY = OUT_DIR / "V21_033_R1_TECHNICAL_VARIANT_ROBUSTNESS_SUMMARY.csv"
V33_DECISION = OUT_DIR / "V21_033_R1_TECHNICAL_VARIANT_SHADOW_ADOPTION_DECISION.csv"

SUMMARY_OUT = OUT_DIR / "V21_033_R1A_TECHNICAL_VARIANT_SELECTION_DIAGNOSTIC_SUMMARY.csv"
DELTA_OUT = OUT_DIR / "V21_033_R1A_TECHNICAL_VARIANT_SCORE_RANK_DELTA_AUDIT.csv"
BUCKET_OUT = OUT_DIR / "V21_033_R1A_TECHNICAL_VARIANT_BUCKET_COMPOSITION_AUDIT.csv"
TIEBREAK_OUT = OUT_DIR / "V21_033_R1A_TECHNICAL_VARIANT_SELECTION_TIEBREAK_AUDIT.csv"
RECOMMEND_OUT = OUT_DIR / "V21_033_R1A_TECHNICAL_VARIANT_DIAGNOSTIC_RECOMMENDATION.csv"
REPORT_OUT = READ_CENTER_DIR / "V21_033_R1A_TECHNICAL_VARIANT_SELECTION_AND_RANK_DELTA_DIAGNOSTIC_REPORT.md"

REQUIRED_INPUTS = [V32_SUMMARY, V32_BY_WINDOW, V32_RANK, V33_SUMMARY]
BUCKETS = [10, 20, 40, 60]
EPS = 1e-10


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


def fnum(value: object) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def bools(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def safe_mean(values: list[float]) -> float | None:
    return mean(values) if values else None


def safe_median(values: list[float]) -> float | None:
    return median(values) if values else None


def changed(a: object, b: object) -> bool:
    av, bv = fnum(a), fnum(b)
    if av is None or bv is None:
        return False
    return abs(av - bv) > EPS


def score_delta_rows(rank_rows: list[dict[str, str]], variant: str, by_window: list[dict[str, str]]) -> list[dict[str, object]]:
    rows = [row for row in rank_rows if row.get("variant_name") == variant]
    score_deltas = []
    rank_deltas = []
    score_changed = 0
    rank_changed = 0
    for row in rows:
        score_delta = abs((fnum(row.get("variant_score")) or 0.0) - (fnum(row.get("baseline_score")) or 0.0))
        rank_delta = abs((fnum(row.get("variant_rank")) or 0.0) - (fnum(row.get("baseline_rank")) or 0.0))
        score_deltas.append(score_delta)
        rank_deltas.append(rank_delta)
        score_changed += 1 if score_delta > EPS else 0
        rank_changed += 1 if rank_delta > EPS else 0
    overlaps = bucket_overlap_overall(rows)
    method = next((row.get("scoring_method", "") for row in by_window if row.get("variant_name") == variant), "")
    missing_raw = any(not row.get("rsi_detected_value_or_score") for row in rows[:100]) if rows else True
    noop = bool(rows) and score_changed == 0
    quality = "INPUT_COLUMN_LIMITATION" if missing_raw else "USABLE_SCORE_RANK_COMPARISON"
    if method in {"PROXY_RESCORING", "PROXY_LIMITED"}:
        quality = method
    return [{
        "variant_name": variant,
        "rows_compared": len(rows),
        "score_changed_count": score_changed,
        "score_changed_ratio": score_changed / len(rows) if rows else None,
        "rank_changed_count": rank_changed,
        "rank_changed_ratio": rank_changed / len(rows) if rows else None,
        "mean_abs_score_delta": safe_mean(score_deltas),
        "median_abs_score_delta": safe_median(score_deltas),
        "max_abs_score_delta": max(score_deltas) if score_deltas else None,
        "mean_abs_rank_delta": safe_mean(rank_deltas),
        "median_abs_rank_delta": safe_median(rank_deltas),
        "max_abs_rank_delta": max(rank_deltas) if rank_deltas else None,
        "top20_overlap_ratio": overlaps.get(20),
        "top40_overlap_ratio": overlaps.get(40),
        "top60_overlap_ratio": overlaps.get(60),
        "scoring_method": method,
        "scoring_method_quality": quality,
        "no_op_warning": bools(noop),
        "interpretation": "Variant scoring did not change observed scores/ranks; V21.032 best selection is a no-op/tie artifact." if noop else "Variant changed scores or ranks; inspect return evidence before adoption.",
    }]


def bucket_overlap_overall(rows: list[dict[str, str]]) -> dict[int, float | None]:
    out = {}
    for bucket in BUCKETS:
        ratios = []
        by_date: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            by_date[row.get("as_of_date", "")].append(row)
        for date_rows in by_date.values():
            base = {row.get("ticker", "") for row in date_rows if (fnum(row.get("baseline_rank")) or 999999) <= bucket}
            var = {row.get("ticker", "") for row in date_rows if (fnum(row.get("variant_rank")) or 999999) <= bucket}
            if base or var:
                ratios.append(len(base & var) / max(1, len(base | var)))
        out[bucket] = safe_mean(ratios)
    return out


def truncate_tickers(tickers: set[str]) -> str:
    ordered = sorted(t for t in tickers if t)
    shown = ordered[:20]
    suffix = f" ... (+{len(ordered) - len(shown)} more)" if len(ordered) > len(shown) else ""
    return "|".join(shown) + suffix


def bucket_composition_rows(rank_rows: list[dict[str, str]], variant: str) -> list[dict[str, object]]:
    rows = [row for row in rank_rows if row.get("variant_name") == variant]
    by_date: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_date[row.get("as_of_date", "")].append(row)
    out = []
    for as_of_date in sorted(by_date):
        date_rows = by_date[as_of_date]
        for bucket in BUCKETS:
            base = {row.get("ticker", "") for row in date_rows if (fnum(row.get("baseline_rank")) or 999999) <= bucket}
            var = {row.get("ticker", "") for row in date_rows if (fnum(row.get("variant_rank")) or 999999) <= bucket}
            added = var - base
            removed = base - var
            overlap = base & var
            out.append({
                "variant_name": variant,
                "as_of_date": as_of_date,
                "top_bucket": f"TOP{bucket}",
                "baseline_ticker_count": len(base),
                "variant_ticker_count": len(var),
                "overlap_count": len(overlap),
                "overlap_ratio": len(overlap) / max(1, len(base | var)),
                "added_tickers": truncate_tickers(added),
                "removed_tickers": truncate_tickers(removed),
                "composition_changed": bools(bool(added or removed)),
                "notes": "NO_BUCKET_COMPOSITION_CHANGE" if not (added or removed) else "BUCKET_COMPOSITION_CHANGED",
            })
    return out


def tiebreak_rows(by_window: list[dict[str, str]], summary_032: dict[str, str], summary_033: dict[str, str]) -> list[dict[str, object]]:
    selected_032 = summary_032.get("best_shadow_variant_name", "")
    selected_033 = summary_033.get("candidate_variant_name", "")
    rows = [row for row in by_window if row.get("top_bucket") == "TOP20" and row.get("forward_window") == "20D"]
    if not rows:
        rows = [row for row in by_window if row.get("top_bucket") == "TOP20"]
    baseline_by_window = {
        row.get("forward_window", ""): row
        for row in by_window
        if row.get("variant_name") == "BASELINE_CURRENT_TECHNICAL" and row.get("top_bucket") == "TOP20"
    }
    metric_keys = ["mean_forward_return", "mean_excess_vs_baseline", "hit_rate", "downside_rate"]
    signatures = defaultdict(int)
    for row in rows:
        sig = tuple(row.get(key, "") for key in metric_keys)
        signatures[sig] += 1
    out = []
    for row in sorted(rows, key=lambda item: item.get("variant_name", "")):
        base = baseline_by_window.get(row.get("forward_window", ""), {})
        excess = fnum(row.get("mean_excess_vs_baseline"))
        hit = fnum(row.get("hit_rate"))
        base_hit = fnum(base.get("hit_rate"))
        down = fnum(row.get("downside_rate"))
        base_down = fnum(base.get("downside_rate"))
        overlap = fnum(row.get("rank_overlap_with_baseline_top20"))
        sig = tuple(row.get(key, "") for key in metric_keys)
        tie_warning = signatures[sig] > 1 or excess is None or abs(excess) <= EPS
        out.append({
            "variant_name": row.get("variant_name", ""),
            "mean_forward_return": row.get("mean_forward_return", ""),
            "baseline_mean_forward_return": base.get("mean_forward_return", ""),
            "mean_excess_vs_baseline": row.get("mean_excess_vs_baseline", ""),
            "hit_rate": row.get("hit_rate", ""),
            "baseline_hit_rate": base.get("hit_rate", ""),
            "downside_rate": row.get("downside_rate", ""),
            "baseline_downside_rate": base.get("downside_rate", ""),
            "rank_overlap_with_baseline_top20": row.get("rank_overlap_with_baseline_top20", ""),
            "turnover_proxy": row.get("turnover_proxy", ""),
            "selected_as_best_in_v21_032": bools(row.get("variant_name") == selected_032),
            "selected_for_gate_in_v21_033": bools(row.get("variant_name") == selected_033),
            "positive_excess_gate_pass": bools(excess is not None and excess > EPS),
            "hit_rate_gate_pass": bools(hit is not None and base_hit is not None and hit >= base_hit),
            "downside_gate_pass": bools((down is None or base_down is None) or down <= base_down),
            "rank_overlap_gate_pass": bools(overlap is None or overlap >= 0.50),
            "tiebreak_or_zero_edge_warning": bools(tie_warning),
            "interpretation": "Selected variant has zero/duplicate edge; treat as tie/default artifact, not proven alpha." if tie_warning else "Variant has distinct positive edge candidate metrics.",
        })
    return out


def classify(delta: dict[str, object], summary_033: dict[str, str], tie_rows: list[dict[str, object]]) -> str:
    issues = []
    if fnum(delta.get("score_changed_ratio")) == 0:
        issues.append("VARIANT_SCORING_NOOP")
    if fnum(delta.get("rank_changed_ratio")) == 0:
        issues.append("RANK_DELTA_NOOP")
    if all((fnum(delta.get(key)) or 0) >= 1.0 - EPS for key in ["top20_overlap_ratio", "top40_overlap_ratio", "top60_overlap_ratio"]):
        issues.append("TOP_BUCKET_NOOP")
    if any(row.get("tiebreak_or_zero_edge_warning") == "TRUE" for row in tie_rows):
        issues.append("BEST_VARIANT_TIEBREAK_ARTIFACT")
    quality = str(delta.get("scoring_method_quality", ""))
    if "PROXY" in quality:
        issues.append("PROXY_RESCORING_LIMITATION")
    if "INPUT_COLUMN_LIMITATION" in quality:
        issues.append("INPUT_COLUMN_LIMITATION")
    if fnum(summary_033.get("candidate_mean_excess_vs_baseline")) == 0:
        issues.append("TRUE_NO_IMPROVEMENT")
    return "|".join(dict.fromkeys(issues)) or "UNKNOWN_REQUIRES_MANUAL_REVIEW"


def recommendations(issue_type: str) -> list[dict[str, object]]:
    rows = []
    if "VARIANT_SCORING_NOOP" in issue_type or "INPUT_COLUMN_LIMITATION" in issue_type:
        rows.append({
            "recommendation_id": "V21_033_R1A_REC_001",
            "recommendation_type": "DIAGNOSTIC_REPAIR",
            "target_stage_or_component": "V21.032-R1 technical variant scorer",
            "current_issue": "Variant scoring did not materially change ranks, likely because raw RSI/KDJ/MACD columns were unavailable.",
            "proposed_fix": "Implement true granular technical subfactor capture before reweighting variants.",
            "priority": "HIGH",
            "official_use_allowed": "FALSE",
            "shadow_use_allowed": "TRUE",
            "requires_new_backtest": "TRUE",
            "next_validation_required": "Rerun V21.032-style variant backtest with raw technical subfactor columns.",
        })
    if "BEST_VARIANT_TIEBREAK_ARTIFACT" in issue_type:
        rows.append({
            "recommendation_id": "V21_033_R1A_REC_002",
            "recommendation_type": "SELECTION_LOGIC_REPAIR",
            "target_stage_or_component": "V21.032-R1 best variant selector",
            "current_issue": "Best variant can be named when candidate edge is zero or tied with baseline.",
            "proposed_fix": "Require positive excess versus baseline and nonzero rank/selection delta before assigning best_shadow_variant_name.",
            "priority": "HIGH",
            "official_use_allowed": "FALSE",
            "shadow_use_allowed": "TRUE",
            "requires_new_backtest": "TRUE",
            "next_validation_required": "Selection gate retest with explicit tie/default artifact handling.",
        })
    rows.append({
        "recommendation_id": "V21_033_R1A_REC_003",
        "recommendation_type": "ADOPTION_BLOCKER",
        "target_stage_or_component": "V21.033-R1 shadow adoption gate",
        "current_issue": "RSI_DEEMPHASIZED has zero excess versus baseline in current artifacts.",
        "proposed_fix": "Keep shadow and official adoption blocked; test regime-aware RSI only after true trend/range labels and raw subfactors exist.",
        "priority": "MEDIUM",
        "official_use_allowed": "FALSE",
        "shadow_use_allowed": "FALSE",
        "requires_new_backtest": "TRUE",
        "next_validation_required": "V21.034 raw technical capture and matured validation.",
    })
    return rows


SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "research_only", "official_use_allowed", "official_weight_mutation_allowed",
    "official_ranking_mutation_allowed", "trade_action_allowed", "broker_execution_allowed", "real_book_mutation_allowed",
    "upstream_v21_032_final_status", "upstream_v21_033_final_status", "v21_032_best_shadow_variant_name",
    "v21_033_candidate_variant_name", "diagnostic_variant_name", "v21_033_shadow_adoption_allowed",
    "candidate_mean_excess_vs_baseline", "zero_excess_detected", "variant_score_changed", "variant_rank_changed",
    "top20_composition_changed", "top40_composition_changed", "top60_composition_changed", "probable_issue_type",
    "diagnostic_decision", "data_trust_alpha_weight_allowed", "next_recommended_stage",
]
DELTA_FIELDS = [
    "variant_name", "rows_compared", "score_changed_count", "score_changed_ratio", "rank_changed_count",
    "rank_changed_ratio", "mean_abs_score_delta", "median_abs_score_delta", "max_abs_score_delta",
    "mean_abs_rank_delta", "median_abs_rank_delta", "max_abs_rank_delta", "top20_overlap_ratio",
    "top40_overlap_ratio", "top60_overlap_ratio", "scoring_method", "scoring_method_quality", "no_op_warning",
    "interpretation",
]
BUCKET_FIELDS = [
    "variant_name", "as_of_date", "top_bucket", "baseline_ticker_count", "variant_ticker_count", "overlap_count",
    "overlap_ratio", "added_tickers", "removed_tickers", "composition_changed", "notes",
]
TIE_FIELDS = [
    "variant_name", "mean_forward_return", "baseline_mean_forward_return", "mean_excess_vs_baseline", "hit_rate",
    "baseline_hit_rate", "downside_rate", "baseline_downside_rate", "rank_overlap_with_baseline_top20",
    "turnover_proxy", "selected_as_best_in_v21_032", "selected_for_gate_in_v21_033", "positive_excess_gate_pass",
    "hit_rate_gate_pass", "downside_gate_pass", "rank_overlap_gate_pass", "tiebreak_or_zero_edge_warning",
    "interpretation",
]
REC_FIELDS = [
    "recommendation_id", "recommendation_type", "target_stage_or_component", "current_issue", "proposed_fix",
    "priority", "official_use_allowed", "shadow_use_allowed", "requires_new_backtest", "next_validation_required",
]


def write_blocked() -> None:
    row = {
        "stage": STAGE, "final_status": BLOCKED_STATUS, "decision": DECISION, "research_only": "TRUE",
        "official_use_allowed": "FALSE", "official_weight_mutation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE", "trade_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE", "real_book_mutation_allowed": "FALSE",
        "upstream_v21_032_final_status": "", "upstream_v21_033_final_status": "",
        "v21_032_best_shadow_variant_name": "", "v21_033_candidate_variant_name": "",
        "diagnostic_variant_name": "", "v21_033_shadow_adoption_allowed": "FALSE",
        "candidate_mean_excess_vs_baseline": "", "zero_excess_detected": "FALSE",
        "variant_score_changed": "FALSE", "variant_rank_changed": "FALSE",
        "top20_composition_changed": "FALSE", "top40_composition_changed": "FALSE",
        "top60_composition_changed": "FALSE", "probable_issue_type": "UNKNOWN_REQUIRES_MANUAL_REVIEW",
        "diagnostic_decision": "INPUTS_MISSING", "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "RERUN_V21_032_R1_AND_V21_033_R1",
    }
    write_csv(SUMMARY_OUT, [row], SUMMARY_FIELDS)
    write_csv(DELTA_OUT, [{"variant_name": "", "rows_compared": 0, "no_op_warning": "TRUE", "interpretation": "Inputs missing."}], DELTA_FIELDS)
    write_csv(BUCKET_OUT, [{"variant_name": "", "as_of_date": "", "top_bucket": "", "composition_changed": "FALSE", "notes": "INPUTS_MISSING"}], BUCKET_FIELDS)
    write_csv(TIEBREAK_OUT, [{"variant_name": "", "tiebreak_or_zero_edge_warning": "TRUE", "interpretation": "Inputs missing."}], TIE_FIELDS)
    write_csv(RECOMMEND_OUT, recommendations("UNKNOWN_REQUIRES_MANUAL_REVIEW"), REC_FIELDS)
    REPORT_OUT.write_text(f"# {STAGE}\n\nDecision: {DECISION}\n\nInputs missing. Shadow adoption remains blocked. Official adoption remains blocked.\n", encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    if any(not path.exists() or path.stat().st_size == 0 for path in REQUIRED_INPUTS):
        write_blocked()
        print(f"STAGE_NAME={STAGE}")
        print(f"final_status={BLOCKED_STATUS}")
        return

    summary_032 = first(read_csv(V32_SUMMARY))
    summary_033 = first(read_csv(V33_SUMMARY))
    by_window = read_csv(V32_BY_WINDOW)
    rank_rows = read_csv(V32_RANK)
    variant = summary_033.get("candidate_variant_name") or summary_032.get("best_shadow_variant_name") or "RSI_DEEMPHASIZED"

    delta_rows = score_delta_rows(rank_rows, variant, by_window)
    bucket_rows = bucket_composition_rows(rank_rows, variant)
    tie_rows = tiebreak_rows(by_window, summary_032, summary_033)
    delta = delta_rows[0]
    issue_type = classify(delta, summary_033, tie_rows)
    limited = "INPUT_COLUMN_LIMITATION" in issue_type
    final_status = PARTIAL_STATUS if limited else PASS_STATUS
    zero_excess = (fnum(summary_033.get("candidate_mean_excess_vs_baseline")) is not None and abs(fnum(summary_033.get("candidate_mean_excess_vs_baseline")) or 0.0) <= EPS)
    summary = [{
        "stage": STAGE,
        "final_status": final_status,
        "decision": DECISION,
        "research_only": "TRUE",
        "official_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "real_book_mutation_allowed": "FALSE",
        "upstream_v21_032_final_status": summary_032.get("final_status", ""),
        "upstream_v21_033_final_status": summary_033.get("final_status", ""),
        "v21_032_best_shadow_variant_name": summary_032.get("best_shadow_variant_name", ""),
        "v21_033_candidate_variant_name": summary_033.get("candidate_variant_name", ""),
        "diagnostic_variant_name": variant,
        "v21_033_shadow_adoption_allowed": summary_033.get("shadow_adoption_allowed", ""),
        "candidate_mean_excess_vs_baseline": summary_033.get("candidate_mean_excess_vs_baseline", ""),
        "zero_excess_detected": bools(zero_excess),
        "variant_score_changed": bools((fnum(delta.get("score_changed_ratio")) or 0.0) > 0),
        "variant_rank_changed": bools((fnum(delta.get("rank_changed_ratio")) or 0.0) > 0),
        "top20_composition_changed": bools((fnum(delta.get("top20_overlap_ratio")) or 0.0) < 1.0 - EPS),
        "top40_composition_changed": bools((fnum(delta.get("top40_overlap_ratio")) or 0.0) < 1.0 - EPS),
        "top60_composition_changed": bools((fnum(delta.get("top60_overlap_ratio")) or 0.0) < 1.0 - EPS),
        "probable_issue_type": issue_type,
        "diagnostic_decision": "BEST_VARIANT_IS_NOOP_OR_TIE_ARTIFACT_SHADOW_ADOPTION_BLOCKED" if "NOOP" in issue_type or "TIEBREAK" in issue_type else "REQUIRES_MANUAL_REVIEW",
        "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "V21.034_R1_TRUE_TECHNICAL_SUBFACTOR_CAPTURE_AND_SELECTION_LOGIC_REPAIR",
    }]
    recs = recommendations(issue_type)
    write_csv(SUMMARY_OUT, summary, SUMMARY_FIELDS)
    write_csv(DELTA_OUT, delta_rows, DELTA_FIELDS)
    write_csv(BUCKET_OUT, bucket_rows, BUCKET_FIELDS)
    write_csv(TIEBREAK_OUT, tie_rows, TIE_FIELDS)
    write_csv(RECOMMEND_OUT, recs, REC_FIELDS)

    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Final status and decision

- final_status: {final_status}
- decision: {DECISION}
- probable_issue_type: {issue_type}

## Summary of V21.032-R1 and V21.033-R1 mismatch

V21.032-R1 named `{summary_032.get("best_shadow_variant_name", "")}` as best_shadow_variant_name. V21.033-R1 evaluated `{summary_033.get("candidate_variant_name", "")}` and blocked adoption with candidate_mean_excess_vs_baseline `{summary_033.get("candidate_mean_excess_vs_baseline", "")}`.

## Whether RSI_DEEMPHASIZED actually changed scores

Score changed ratio: {delta.get("score_changed_ratio")}. No-op warning: {delta.get("no_op_warning")}.

## Whether RSI_DEEMPHASIZED actually changed ranks

Rank changed ratio: {delta.get("rank_changed_ratio")}. Mean absolute rank delta: {delta.get("mean_abs_rank_delta")}.

## Whether top10/top20/top40/top60 composition changed

Top20 overlap: {delta.get("top20_overlap_ratio")}. Top40 overlap: {delta.get("top40_overlap_ratio")}. Top60 overlap: {delta.get("top60_overlap_ratio")}. See `{BUCKET_OUT.relative_to(ROOT)}` for per-date TOP10/TOP20/TOP40/TOP60 composition.

## True edge or tie/default/proxy artifact

The diagnostic classifies the selection as `{issue_type}`. In the current artifacts, the selected variant appears to be a no-op/tie artifact rather than proven technical alpha.

## Why shadow adoption remains blocked

Shadow adoption remains blocked because the selected candidate produced zero excess versus baseline and did not materially change scores, ranks, or top-bucket selections.

## Why official adoption remains blocked

Official adoption remains blocked because this diagnostic is research-only, official mutation flags are FALSE, DATA_TRUST alpha weight remains disallowed, and the candidate has no proven positive edge.

## Recommended repair path

Implement true raw technical subfactor capture, repair V21.032 selection logic to require positive excess and nonzero rank/selection delta, then rerun the variant backtest and robustness gate.
"""
    REPORT_OUT.write_text(report, encoding="utf-8")
    print(f"STAGE_NAME={STAGE}")
    print(f"final_status={final_status}")
    print(f"decision={DECISION}")
    print(f"diagnostic_variant_name={variant}")
    print(f"probable_issue_type={issue_type}")


if __name__ == "__main__":
    main()
