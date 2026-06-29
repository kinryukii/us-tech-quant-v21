#!/usr/bin/env python
"""V21.033-R1 technical variant robustness and shadow adoption gate.

Research-only gate for deciding whether the V21.032-R1 best technical variant
is robust enough for future shadow research runs. This stage never mutates
official rankings, official weights, recommendations, broker actions, or book
state.
"""

from __future__ import annotations

import csv
import math
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median


STAGE = "V21.033-R1_TECHNICAL_VARIANT_ROBUSTNESS_AND_SHADOW_ADOPTION_GATE"
UPSTREAM_STAGE = "V21.032-R1_TECHNICAL_SUBFACTOR_WEIGHT_VARIANT_BACKTEST"
PASS_STATUS = "PASS_V21_033_R1_TECHNICAL_VARIANT_SHADOW_ADOPTION_GATE_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_033_R1_TECHNICAL_VARIANT_GATE_LIMITED_EVIDENCE"
INPUTS_MISSING_STATUS = "BLOCKED_V21_033_R1_INPUTS_MISSING"
RESEARCH_ONLY_VIOLATION_STATUS = "BLOCKED_V21_033_R1_RESEARCH_ONLY_VIOLATION"

DECISION_ALLOWED = "TECHNICAL_VARIANT_SHADOW_ADOPTION_ALLOWED_OFFICIAL_UPDATE_BLOCKED"
DECISION_MORE = "TECHNICAL_VARIANT_SHADOW_ADOPTION_BLOCKED_NEEDS_MORE_EVIDENCE"
DECISION_ROBUST = "TECHNICAL_VARIANT_SHADOW_ADOPTION_BLOCKED_BENCHMARK_OR_ROBUSTNESS_FAILURE"
DECISION_INPUTS = "TECHNICAL_VARIANT_SHADOW_ADOPTION_BLOCKED_INPUTS_MISSING"

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

UPSTREAM_SUMMARY = OUT_DIR / "V21_032_R1_TECHNICAL_VARIANT_BACKTEST_SUMMARY.csv"
UPSTREAM_BY_WINDOW = OUT_DIR / "V21_032_R1_TECHNICAL_VARIANT_BACKTEST_BY_WINDOW.csv"

SUMMARY_OUT = OUT_DIR / "V21_033_R1_TECHNICAL_VARIANT_ROBUSTNESS_SUMMARY.csv"
BY_WINDOW_OUT = OUT_DIR / "V21_033_R1_TECHNICAL_VARIANT_ROBUSTNESS_BY_WINDOW.csv"
BY_BUCKET_OUT = OUT_DIR / "V21_033_R1_TECHNICAL_VARIANT_ROBUSTNESS_BY_BUCKET.csv"
BENCH_OUT = OUT_DIR / "V21_033_R1_TECHNICAL_VARIANT_BENCHMARK_DECOMPOSITION.csv"
DECISION_OUT = OUT_DIR / "V21_033_R1_TECHNICAL_VARIANT_SHADOW_ADOPTION_DECISION.csv"
REPORT_OUT = READ_CENTER_DIR / "V21_033_R1_TECHNICAL_VARIANT_ROBUSTNESS_AND_SHADOW_ADOPTION_GATE_REPORT.md"

REQUIRED_INPUTS = [UPSTREAM_SUMMARY, UPSTREAM_BY_WINDOW]
BENCHMARKS = ["QQQ", "SPY", "SOXX"]


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


def truth(value: object) -> bool:
    return str(value).strip().upper() == "TRUE"


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def avg(values: list[float]) -> float | None:
    return mean(values) if values else None


def med(values: list[float]) -> float | None:
    return median(values) if values else None


def rows_for(by_window: list[dict[str, str]], variant: str, bucket: str | None = None) -> list[dict[str, str]]:
    rows = [row for row in by_window if row.get("variant_name") == variant and row.get("interpretation_allowed") == "TRUE"]
    if bucket:
        rows = [row for row in rows if row.get("top_bucket") == bucket]
    return rows


def baseline_match(by_window: list[dict[str, str]], window: str, bucket: str, baseline: str) -> dict[str, str]:
    for row in by_window:
        if row.get("variant_name") == baseline and row.get("forward_window") == window and row.get("top_bucket") == bucket:
            return row
    return {}


def pass_window(candidate: dict[str, str], baseline: dict[str, str]) -> tuple[str, str]:
    excess = fnum(candidate.get("mean_excess_vs_baseline"))
    hit = fnum(candidate.get("hit_rate"))
    base_hit = fnum(baseline.get("hit_rate"))
    down = fnum(candidate.get("downside_rate"))
    base_down = fnum(baseline.get("downside_rate"))
    failures = []
    if excess is None or excess <= 0:
        failures.append("mean_excess_vs_baseline_not_positive")
    if hit is not None and base_hit is not None and hit < base_hit:
        failures.append("hit_rate_below_baseline")
    if down is not None and base_down is not None and down > base_down:
        failures.append("downside_rate_above_baseline")
    return ("TRUE" if not failures else "FALSE", "|".join(failures))


def build_by_window(by_window: list[dict[str, str]], candidate: str, baseline: str) -> list[dict[str, object]]:
    out = []
    for cand in rows_for(by_window, candidate, "TOP20"):
        base = baseline_match(by_window, cand.get("forward_window", ""), cand.get("top_bucket", ""), baseline)
        window_pass, reason = pass_window(cand, base)
        out.append({
            "candidate_variant_name": candidate,
            "forward_window": cand.get("forward_window", ""),
            "rows_used": cand.get("rows_used", ""),
            "distinct_as_of_dates": cand.get("distinct_as_of_dates", ""),
            "distinct_tickers": cand.get("distinct_tickers", ""),
            "candidate_mean_forward_return": cand.get("mean_forward_return", ""),
            "baseline_mean_forward_return": base.get("mean_forward_return", ""),
            "mean_excess_vs_baseline": cand.get("mean_excess_vs_baseline", ""),
            "candidate_median_forward_return": cand.get("median_forward_return", ""),
            "baseline_median_forward_return": base.get("median_forward_return", ""),
            "median_excess_vs_baseline": cand.get("median_excess_vs_baseline", ""),
            "candidate_hit_rate": cand.get("hit_rate", ""),
            "baseline_hit_rate": base.get("hit_rate", ""),
            "hit_rate_delta": delta(cand.get("hit_rate"), base.get("hit_rate")),
            "candidate_downside_rate": cand.get("downside_rate", ""),
            "baseline_downside_rate": base.get("downside_rate", ""),
            "downside_rate_delta": delta(cand.get("downside_rate"), base.get("downside_rate")),
            "mean_excess_vs_qqq": cand.get("mean_excess_vs_qqq", ""),
            "mean_excess_vs_spy": cand.get("mean_excess_vs_spy", ""),
            "mean_excess_vs_soxx": cand.get("mean_excess_vs_soxx", ""),
            "window_pass": window_pass,
            "failure_reason": reason,
        })
    return sorted(out, key=lambda row: row["forward_window"])


def delta(a: object, b: object) -> float | None:
    av, bv = fnum(a), fnum(b)
    return None if av is None or bv is None else av - bv


def build_by_bucket(by_window: list[dict[str, str]], candidate: str, baseline: str) -> list[dict[str, object]]:
    out = []
    buckets = sorted({row.get("top_bucket", "") for row in rows_for(by_window, candidate) if row.get("top_bucket", "").startswith("TOP")})
    for bucket in buckets:
        cand_rows = rows_for(by_window, candidate, bucket)
        pairs = [(cand, baseline_match(by_window, cand.get("forward_window", ""), bucket, baseline)) for cand in cand_rows]
        pairs = [(cand, base) for cand, base in pairs if base]
        cand_mean = [fnum(cand.get("mean_forward_return")) for cand, _base in pairs]
        base_mean = [fnum(base.get("mean_forward_return")) for _cand, base in pairs]
        cand_hit = [fnum(cand.get("hit_rate")) for cand, _base in pairs]
        base_hit = [fnum(base.get("hit_rate")) for _cand, base in pairs]
        cand_down = [fnum(cand.get("downside_rate")) for cand, _base in pairs]
        base_down = [fnum(base.get("downside_rate")) for _cand, base in pairs]
        cand_mean = [v for v in cand_mean if v is not None]
        base_mean = [v for v in base_mean if v is not None]
        cand_hit = [v for v in cand_hit if v is not None]
        base_hit = [v for v in base_hit if v is not None]
        cand_down = [v for v in cand_down if v is not None]
        base_down = [v for v in base_down if v is not None]
        excess = None if not cand_mean or not base_mean else avg(cand_mean) - avg(base_mean)
        hit_delta = None if not cand_hit or not base_hit else avg(cand_hit) - avg(base_hit)
        down_delta = None if not cand_down or not base_down else avg(cand_down) - avg(base_down)
        failures = []
        if excess is None or excess <= 0:
            failures.append("mean_excess_vs_baseline_not_positive")
        if hit_delta is not None and hit_delta < 0:
            failures.append("hit_rate_below_baseline")
        if down_delta is not None and down_delta > 0:
            failures.append("downside_rate_above_baseline")
        overlap_vals = [fnum(cand.get("rank_overlap_with_baseline_top20")) for cand, _base in pairs]
        turnover_vals = [fnum(cand.get("turnover_proxy")) for cand, _base in pairs]
        overlap_vals = [v for v in overlap_vals if v is not None]
        turnover_vals = [v for v in turnover_vals if v is not None]
        out.append({
            "candidate_variant_name": candidate,
            "top_bucket": bucket,
            "rows_used": sum(int(fnum(cand.get("rows_used")) or 0) for cand, _base in pairs),
            "distinct_as_of_dates": max((int(fnum(cand.get("distinct_as_of_dates")) or 0) for cand, _base in pairs), default=0),
            "distinct_tickers": max((int(fnum(cand.get("distinct_tickers")) or 0) for cand, _base in pairs), default=0),
            "candidate_mean_forward_return": avg(cand_mean),
            "baseline_mean_forward_return": avg(base_mean),
            "mean_excess_vs_baseline": excess,
            "candidate_hit_rate": avg(cand_hit),
            "baseline_hit_rate": avg(base_hit),
            "hit_rate_delta": hit_delta,
            "candidate_downside_rate": avg(cand_down),
            "baseline_downside_rate": avg(base_down),
            "downside_rate_delta": down_delta,
            "rank_overlap_with_baseline": avg(overlap_vals),
            "turnover_proxy": avg(turnover_vals),
            "bucket_pass": "TRUE" if not failures else "FALSE",
            "failure_reason": "|".join(failures),
        })
    return out


def benchmark_decomposition(by_window: list[dict[str, str]], candidate: str) -> list[dict[str, object]]:
    out = []
    top20 = rows_for(by_window, candidate, "TOP20")
    qqq_positive = False
    soxx_positive = False
    temp = {}
    for bench in BENCHMARKS:
        key = f"mean_excess_vs_{bench.lower()}"
        avail = [row for row in top20 if fnum(row.get(key)) is not None]
        cand_means = [fnum(row.get("mean_forward_return")) for row in avail]
        excess_vals = [fnum(row.get(key)) for row in avail]
        cand_means = [v for v in cand_means if v is not None]
        excess_vals = [v for v in excess_vals if v is not None]
        if not avail or not cand_means or not excess_vals:
            temp[bench] = {
                "candidate_variant_name": candidate,
                "benchmark_name": bench,
                "benchmark_available": "FALSE",
                "rows_used": 0,
                "candidate_mean_forward_return": None,
                "benchmark_mean_forward_return": None,
                "mean_excess_vs_benchmark": None,
                "candidate_hit_rate_vs_benchmark": None,
                "benchmark_interpretation_status": "BENCHMARK_DATA_MISSING",
                "beta_exposure_warning": "",
                "notes": "Benchmark proxy data unavailable in upstream V21.032-R1 rows for evaluated TOP20 windows.",
            }
            continue
        mean_excess = avg(excess_vals)
        if bench == "QQQ" and mean_excess and mean_excess > 0:
            qqq_positive = True
        if bench == "SOXX" and mean_excess and mean_excess > 0:
            soxx_positive = True
        temp[bench] = {
            "candidate_variant_name": candidate,
            "benchmark_name": bench,
            "benchmark_available": "TRUE",
            "rows_used": sum(int(fnum(row.get("rows_used")) or 0) for row in avail),
            "candidate_mean_forward_return": avg(cand_means),
            "benchmark_mean_forward_return": None if avg(cand_means) is None or mean_excess is None else avg(cand_means) - mean_excess,
            "mean_excess_vs_benchmark": mean_excess,
            "candidate_hit_rate_vs_benchmark": sum(1 for v in excess_vals if v > 0) / len(excess_vals),
            "benchmark_interpretation_status": "BENCHMARK_COMPARISON_AVAILABLE",
            "beta_exposure_warning": "",
            "notes": "Aggregated from available upstream TOP20 benchmark-excess windows.",
        }
    if qqq_positive and not soxx_positive and temp.get("SOXX", {}).get("benchmark_available") == "TRUE":
        temp["SOXX"]["beta_exposure_warning"] = "POSSIBLE_SEMICONDUCTOR_BETA_EXPOSURE"
        temp["SOXX"]["benchmark_interpretation_status"] = "BENCHMARK_AVAILABLE_BETA_EXPOSURE_WARNING"
    for bench in BENCHMARKS:
        out.append(temp[bench])
    return out


def choose_primary(by_window: list[dict[str, str]], candidate: str) -> dict[str, str]:
    for window in ["20D", "10D", "5D"]:
        for row in by_window:
            if row.get("variant_name") == candidate and row.get("top_bucket") == "TOP20" and row.get("forward_window") == window:
                return row
    return {}


def evaluate_gate(summary_032: dict[str, str], by_window_rows: list[dict[str, object]], by_bucket_rows: list[dict[str, object]], bench_rows: list[dict[str, object]], primary: dict[str, str], baseline_primary: dict[str, str], candidate: str) -> tuple[str, str, str, list[str], list[str]]:
    passed = []
    failed = []
    def require(name: str, ok: bool) -> None:
        (passed if ok else failed).append(name)

    require("research_only_true", truth(summary_032.get("research_only")))
    require("official_use_blocked", summary_032.get("official_use_allowed") == "FALSE")
    require("official_weight_mutation_blocked", summary_032.get("official_weight_mutation_allowed") == "FALSE")
    require("candidate_present", bool(candidate))
    require("matured_rows_positive", int(fnum(summary_032.get("matured_rows_used")) or 0) > 0)

    candidate_excess = fnum(primary.get("mean_excess_vs_baseline"))
    candidate_hit = fnum(primary.get("hit_rate"))
    baseline_hit = fnum(baseline_primary.get("hit_rate"))
    candidate_down = fnum(primary.get("downside_rate"))
    baseline_down = fnum(baseline_primary.get("downside_rate"))
    overlap = fnum(primary.get("rank_overlap_with_baseline_top20"))
    turnover = fnum(primary.get("turnover_proxy"))
    baseline_turnover = fnum(baseline_primary.get("turnover_proxy"))
    require("candidate_mean_excess_vs_baseline_positive", candidate_excess is not None and candidate_excess > 0)
    require("candidate_hit_rate_not_below_baseline", candidate_hit is not None and baseline_hit is not None and candidate_hit >= baseline_hit)
    require("candidate_downside_not_worse", (candidate_down is None or baseline_down is None) or candidate_down <= baseline_down)
    require("rank_overlap_at_least_0_50_if_available", overlap is None or overlap >= 0.50)
    require("turnover_not_materially_worse_if_available", (turnover is None or baseline_turnover is None) or turnover <= baseline_turnover + 0.10)

    window_passes = sum(1 for row in by_window_rows if row.get("window_pass") == "TRUE")
    available_windows = len(by_window_rows)
    require("at_least_two_forward_windows_pass_or_limited_one_window", window_passes >= 2 or (available_windows == 1 and window_passes == 1))

    beta_warning = any(row.get("beta_exposure_warning") == "POSSIBLE_SEMICONDUCTOR_BETA_EXPOSURE" for row in bench_rows)
    require("no_clear_beta_only_improvement", not beta_warning)

    adoption_allowed = not failed
    benchmark_missing = any(row.get("benchmark_interpretation_status") == "BENCHMARK_DATA_MISSING" for row in bench_rows)
    if adoption_allowed:
        decision = DECISION_ALLOWED
    elif "candidate_mean_excess_vs_baseline_positive" in failed or "candidate_hit_rate_not_below_baseline" in failed or "candidate_downside_not_worse" in failed or "no_clear_beta_only_improvement" in failed:
        decision = DECISION_ROBUST
    else:
        decision = DECISION_MORE
    final_status = PARTIAL_STATUS if benchmark_missing or available_windows < 2 else PASS_STATUS
    return final_status, decision, "TRUE" if adoption_allowed else "FALSE", passed, failed


def write_missing_outputs() -> None:
    summary = [{
        "stage": STAGE,
        "final_status": INPUTS_MISSING_STATUS,
        "decision": DECISION_INPUTS,
        "research_only": "TRUE",
        "official_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "real_book_mutation_allowed": "FALSE",
        "upstream_stage": UPSTREAM_STAGE,
        "upstream_final_status": "",
        "candidate_variant_name": "",
        "baseline_variant_name": "",
        "matured_rows_used": 0,
        "immature_rows_excluded": 0,
        "forward_windows_tested": "",
        "top_buckets_tested": "",
        "benchmark_primary": "BENCHMARK_DATA_MISSING",
        "benchmark_secondary": "BENCHMARK_DATA_MISSING",
        "benchmark_semiconductor_proxy": "BENCHMARK_DATA_MISSING",
        "candidate_mean_forward_return": None,
        "baseline_mean_forward_return": None,
        "candidate_mean_excess_vs_baseline": None,
        "candidate_mean_excess_vs_qqq": None,
        "candidate_mean_excess_vs_spy": None,
        "candidate_mean_excess_vs_soxx": None,
        "candidate_hit_rate": None,
        "baseline_hit_rate": None,
        "candidate_downside_rate": None,
        "baseline_downside_rate": None,
        "candidate_turnover_proxy": None,
        "candidate_rank_overlap_with_baseline_top20": None,
        "robustness_pass": "FALSE",
        "shadow_adoption_allowed": "FALSE",
        "official_adoption_allowed": "FALSE",
        "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "RERUN_V21_032_R1_TECHNICAL_SUBFACTOR_WEIGHT_VARIANT_BACKTEST",
    }]
    write_csv(SUMMARY_OUT, summary, list(summary[0].keys()))
    write_csv(BY_WINDOW_OUT, [], BY_WINDOW_FIELDS)
    write_csv(BY_BUCKET_OUT, [], BY_BUCKET_FIELDS)
    write_csv(BENCH_OUT, [], BENCH_FIELDS)
    write_csv(DECISION_OUT, [{
        "candidate_variant_name": "",
        "shadow_adoption_allowed": "FALSE",
        "official_adoption_allowed": "FALSE",
        "reason": "Required V21.032-R1 outputs are missing.",
        "required_conditions_passed": "",
        "required_conditions_failed": "inputs_present",
        "recommended_shadow_action": "Do not adopt; rerun upstream stage.",
        "recommended_official_action": "Official adoption remains blocked.",
        "next_validation_required": "V21.032-R1 output regeneration.",
    }], DECISION_FIELDS)


SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "research_only", "official_use_allowed", "official_weight_mutation_allowed",
    "official_ranking_mutation_allowed", "trade_action_allowed", "broker_execution_allowed", "real_book_mutation_allowed",
    "upstream_stage", "upstream_final_status", "candidate_variant_name", "baseline_variant_name", "matured_rows_used",
    "immature_rows_excluded", "forward_windows_tested", "top_buckets_tested", "benchmark_primary", "benchmark_secondary",
    "benchmark_semiconductor_proxy", "candidate_mean_forward_return", "baseline_mean_forward_return",
    "candidate_mean_excess_vs_baseline", "candidate_mean_excess_vs_qqq", "candidate_mean_excess_vs_spy",
    "candidate_mean_excess_vs_soxx", "candidate_hit_rate", "baseline_hit_rate", "candidate_downside_rate",
    "baseline_downside_rate", "candidate_turnover_proxy", "candidate_rank_overlap_with_baseline_top20",
    "robustness_pass", "shadow_adoption_allowed", "official_adoption_allowed", "data_trust_alpha_weight_allowed",
    "next_recommended_stage",
]
BY_WINDOW_FIELDS = [
    "candidate_variant_name", "forward_window", "rows_used", "distinct_as_of_dates", "distinct_tickers",
    "candidate_mean_forward_return", "baseline_mean_forward_return", "mean_excess_vs_baseline",
    "candidate_median_forward_return", "baseline_median_forward_return", "median_excess_vs_baseline",
    "candidate_hit_rate", "baseline_hit_rate", "hit_rate_delta", "candidate_downside_rate", "baseline_downside_rate",
    "downside_rate_delta", "mean_excess_vs_qqq", "mean_excess_vs_spy", "mean_excess_vs_soxx", "window_pass",
    "failure_reason",
]
BY_BUCKET_FIELDS = [
    "candidate_variant_name", "top_bucket", "rows_used", "distinct_as_of_dates", "distinct_tickers",
    "candidate_mean_forward_return", "baseline_mean_forward_return", "mean_excess_vs_baseline", "candidate_hit_rate",
    "baseline_hit_rate", "hit_rate_delta", "candidate_downside_rate", "baseline_downside_rate", "downside_rate_delta",
    "rank_overlap_with_baseline", "turnover_proxy", "bucket_pass", "failure_reason",
]
BENCH_FIELDS = [
    "candidate_variant_name", "benchmark_name", "benchmark_available", "rows_used", "candidate_mean_forward_return",
    "benchmark_mean_forward_return", "mean_excess_vs_benchmark", "candidate_hit_rate_vs_benchmark",
    "benchmark_interpretation_status", "beta_exposure_warning", "notes",
]
DECISION_FIELDS = [
    "candidate_variant_name", "shadow_adoption_allowed", "official_adoption_allowed", "reason",
    "required_conditions_passed", "required_conditions_failed", "recommended_shadow_action",
    "recommended_official_action", "next_validation_required",
]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)

    if any(not path.exists() or path.stat().st_size == 0 for path in REQUIRED_INPUTS):
        write_missing_outputs()
        REPORT_OUT.write_text(f"# {STAGE}\n\nFinal status: {INPUTS_MISSING_STATUS}\n\nDecision: {DECISION_INPUTS}\n\nOfficial adoption remains blocked because required upstream inputs are missing.\n", encoding="utf-8")
        print(f"STAGE_NAME={STAGE}")
        print(f"final_status={INPUTS_MISSING_STATUS}")
        print(f"decision={DECISION_INPUTS}")
        return

    summary_032 = first(read_csv(UPSTREAM_SUMMARY))
    by_window = read_csv(UPSTREAM_BY_WINDOW)
    candidate = summary_032.get("best_shadow_variant_name") or "RSI_DEEMPHASIZED"
    baseline = summary_032.get("baseline_variant_name") or "BASELINE_CURRENT_TECHNICAL"
    research_violation = not truth(summary_032.get("research_only")) or summary_032.get("official_use_allowed") != "FALSE" or summary_032.get("official_weight_mutation_allowed") != "FALSE"

    by_window_rows = build_by_window(by_window, candidate, baseline)
    by_bucket_rows = build_by_bucket(by_window, candidate, baseline)
    bench_rows = benchmark_decomposition(by_window, candidate)
    primary = choose_primary(by_window, candidate)
    baseline_primary = baseline_match(by_window, primary.get("forward_window", ""), primary.get("top_bucket", ""), baseline) if primary else {}
    final_status, decision, shadow_allowed, passed, failed = evaluate_gate(summary_032, by_window_rows, by_bucket_rows, bench_rows, primary, baseline_primary, candidate)
    if research_violation:
        final_status = RESEARCH_ONLY_VIOLATION_STATUS
        decision = DECISION_ROBUST
        shadow_allowed = "FALSE"
        failed.append("research_only_guardrail_violation")

    summary = [{
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "research_only": "TRUE",
        "official_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "real_book_mutation_allowed": "FALSE",
        "upstream_stage": UPSTREAM_STAGE,
        "upstream_final_status": summary_032.get("final_status", ""),
        "candidate_variant_name": candidate,
        "baseline_variant_name": baseline,
        "matured_rows_used": summary_032.get("matured_rows_used", ""),
        "immature_rows_excluded": summary_032.get("immature_rows_excluded", ""),
        "forward_windows_tested": "|".join(sorted({row["forward_window"] for row in by_window_rows})),
        "top_buckets_tested": "|".join(sorted({row["top_bucket"] for row in by_bucket_rows})),
        "benchmark_primary": "QQQ" if any(row["benchmark_name"] == "QQQ" and row["benchmark_available"] == "TRUE" for row in bench_rows) else "BENCHMARK_DATA_MISSING",
        "benchmark_secondary": "SPY" if any(row["benchmark_name"] == "SPY" and row["benchmark_available"] == "TRUE" for row in bench_rows) else "BENCHMARK_DATA_MISSING",
        "benchmark_semiconductor_proxy": "SOXX" if any(row["benchmark_name"] == "SOXX" and row["benchmark_available"] == "TRUE" for row in bench_rows) else "BENCHMARK_DATA_MISSING",
        "candidate_mean_forward_return": primary.get("mean_forward_return", ""),
        "baseline_mean_forward_return": baseline_primary.get("mean_forward_return", ""),
        "candidate_mean_excess_vs_baseline": primary.get("mean_excess_vs_baseline", ""),
        "candidate_mean_excess_vs_qqq": primary.get("mean_excess_vs_qqq", ""),
        "candidate_mean_excess_vs_spy": primary.get("mean_excess_vs_spy", ""),
        "candidate_mean_excess_vs_soxx": primary.get("mean_excess_vs_soxx", ""),
        "candidate_hit_rate": primary.get("hit_rate", ""),
        "baseline_hit_rate": baseline_primary.get("hit_rate", ""),
        "candidate_downside_rate": primary.get("downside_rate", ""),
        "baseline_downside_rate": baseline_primary.get("downside_rate", ""),
        "candidate_turnover_proxy": primary.get("turnover_proxy", ""),
        "candidate_rank_overlap_with_baseline_top20": primary.get("rank_overlap_with_baseline_top20", ""),
        "robustness_pass": "TRUE" if shadow_allowed == "TRUE" else "FALSE",
        "shadow_adoption_allowed": shadow_allowed,
        "official_adoption_allowed": "FALSE",
        "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "V21.034_R1_TECHNICAL_RAW_SUBFACTOR_CAPTURE_AND_SHADOW_LEDGER_VALIDATION",
    }]

    decision_rows = [{
        "candidate_variant_name": candidate,
        "shadow_adoption_allowed": shadow_allowed,
        "official_adoption_allowed": "FALSE",
        "reason": "All shadow adoption conditions passed." if shadow_allowed == "TRUE" else "Shadow adoption blocked: " + "|".join(failed),
        "required_conditions_passed": "|".join(passed),
        "required_conditions_failed": "|".join(failed),
        "recommended_shadow_action": "Accept as shadow-only candidate for future research runs." if shadow_allowed == "TRUE" else "Do not adopt yet; keep as research candidate and gather stronger matured evidence.",
        "recommended_official_action": "Official adoption remains blocked; do not mutate production weights or rankings.",
        "next_validation_required": "Raw technical subfactor capture, additional matured observations, and repeated benchmark/bucket robustness testing.",
    }]

    write_csv(SUMMARY_OUT, summary, SUMMARY_FIELDS)
    write_csv(BY_WINDOW_OUT, by_window_rows, BY_WINDOW_FIELDS)
    write_csv(BY_BUCKET_OUT, by_bucket_rows, BY_BUCKET_FIELDS)
    write_csv(BENCH_OUT, bench_rows, BENCH_FIELDS)
    write_csv(DECISION_OUT, decision_rows, DECISION_FIELDS)

    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Final status and decision

- final_status: {final_status}
- decision: {decision}
- research_only: TRUE
- shadow_adoption_allowed: {shadow_allowed}
- official_adoption_allowed: FALSE

## Upstream V21.032-R1 summary

- upstream_final_status: {summary_032.get("final_status", "")}
- matured_rows_used: {summary_032.get("matured_rows_used", "")}
- immature_rows_excluded: {summary_032.get("immature_rows_excluded", "")}
- upstream best shadow variant selected flag: {summary_032.get("best_shadow_variant_selected", "")}

## Candidate variant name

{candidate}

## Why RSI_DEEMPHASIZED was evaluated

V21.032-R1 identified `RSI_DEEMPHASIZED` as the best shadow technical variant name, while keeping official selection and weight mutation blocked. This gate evaluates whether that candidate is robust enough for shadow-only use in future research runs.

## Robustness results by forward window

See `{BY_WINDOW_OUT.relative_to(ROOT)}`. A window passes only when mean excess versus baseline is positive, hit rate is not below baseline, and downside rate is not worse.

## Robustness results by top bucket

See `{BY_BUCKET_OUT.relative_to(ROOT)}` for TOP10, TOP20, TOP40, and TOP60 aggregate stability checks when present upstream.

## Comparison versus baseline

Primary candidate mean excess versus baseline: {primary.get("mean_excess_vs_baseline", "")}. The gate blocks shadow adoption when excess is not positive.

## Comparison versus QQQ, SPY, and SOXX

See `{BENCH_OUT.relative_to(ROOT)}`. Missing benchmark windows are marked `BENCHMARK_DATA_MISSING` and do not crash the gate.

## Turnover and rank-overlap discussion

Primary rank overlap with baseline TOP20: {primary.get("rank_overlap_with_baseline_top20", "")}. Primary turnover proxy: {primary.get("turnover_proxy", "")}.

## Downside behavior discussion

Candidate downside rate: {primary.get("downside_rate", "")}. Baseline downside rate: {baseline_primary.get("downside_rate", "")}. Downside must not be worse for adoption.

## Shadow adoption decision

{decision_rows[0]["reason"]}

## Why official adoption remains blocked

Official adoption remains blocked because this stage is research-only, official use and mutation flags are FALSE, the gate is limited to shadow research candidacy, and DATA_TRUST alpha weight remains disallowed.

## Next recommended stage

{summary[0]["next_recommended_stage"]}
"""
    REPORT_OUT.write_text(report, encoding="utf-8")
    print(f"STAGE_NAME={STAGE}")
    print(f"final_status={final_status}")
    print(f"decision={decision}")
    print(f"candidate_variant_name={candidate}")
    print(f"shadow_adoption_allowed={shadow_allowed}")
    print("official_adoption_allowed=FALSE")


if __name__ == "__main__":
    main()
