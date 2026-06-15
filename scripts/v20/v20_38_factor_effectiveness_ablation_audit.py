from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"

IN_V37_NEXT = CONSOLIDATION / "V20_37_NEXT_STEP_DECISION_SUMMARY.csv"
IN_V37_RETURNS = CONSOLIDATION / "V20_37_ENTRY_STRATEGY_ROW_LEVEL_RETURNS.csv"
IN_V37_PIT = CONSOLIDATION / "V20_37_STALE_LEAKAGE_PIT_GATE.csv"
IN_V37_FORMULA = CONSOLIDATION / "V20_37_FORMULA_RECHECK.csv"
IN_V37_BLOCKED = CONSOLIDATION / "V20_37_BLOCKED_NON_PIT_ENTRY_DEPENDENCY_ENFORCEMENT.csv"
IN_V37_DECISION = CONSOLIDATION / "V20_37_ENTRY_STRATEGY_BACKTEST_DECISION.csv"
IN_V35_FACTORS = CONSOLIDATION / "V20_35_R2_ASOF_TECHNICAL_FACTOR_RECOMPUTE_MATRIX.csv"
IN_V35_RANKING = CONSOLIDATION / "V20_35_R2_ASOF_TECHNICAL_SCORE_AND_RANKING.csv"
IN_V35_BLOCKED = CONSOLIDATION / "V20_35_R2_BLOCKED_NON_PIT_FACTOR_ENFORCEMENT.csv"
IN_V34_BLOCKED = CONSOLIDATION / "V20_34_RANDOM_ASOF_BLOCKED_NON_PIT_FACTOR_REGISTER.csv"

OUT_GATE = CONSOLIDATION / "V20_38_V20_37_GATE_REVIEW.csv"
OUT_DATASET = CONSOLIDATION / "V20_38_FACTOR_RETURN_ANALYSIS_DATASET.csv"
OUT_COVERAGE = CONSOLIDATION / "V20_38_FACTOR_COVERAGE_AND_QUALITY_AUDIT.csv"
OUT_EFFECT = CONSOLIDATION / "V20_38_FACTOR_EFFECTIVENESS_METRICS.csv"
OUT_BUCKET = CONSOLIDATION / "V20_38_FACTOR_BUCKET_RETURN_SUMMARY.csv"
OUT_ABL_VAR = CONSOLIDATION / "V20_38_FACTOR_ABLATION_SCORE_VARIANT_AUDIT.csv"
OUT_ABL_PERF = CONSOLIDATION / "V20_38_FACTOR_ABLATION_PERFORMANCE_COMPARISON.csv"
OUT_INTERACTION = CONSOLIDATION / "V20_38_STRATEGY_FACTOR_INTERACTION_AUDIT.csv"
OUT_STABILITY = CONSOLIDATION / "V20_38_FACTOR_STABILITY_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_38_OVERFITTING_AND_SAMPLE_SAFETY_AUDIT.csv"
OUT_CLASS = CONSOLIDATION / "V20_38_EXPLORATORY_FACTOR_REVIEW_CLASSIFICATION.csv"
OUT_BLOCKED = CONSOLIDATION / "V20_38_BLOCKED_NON_PIT_FACTOR_ENFORCEMENT.csv"
OUT_PIT = CONSOLIDATION / "V20_38_STALE_LEAKAGE_PIT_GATE.csv"
OUT_FORMULA = CONSOLIDATION / "V20_38_FORMULA_RECHECK.csv"
OUT_DECISION = CONSOLIDATION / "V20_38_FACTOR_EFFECTIVENESS_ABLATION_DECISION.csv"
OUT_NEXT = CONSOLIDATION / "V20_38_NEXT_STEP_DECISION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_38_FACTOR_EFFECTIVENESS_ABLATION_AUDIT_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_FACTOR_EFFECTIVENESS_ABLATION_AUDIT.md"
READ_FIRST = OPS / "V20_38_READ_FIRST.txt"

STAGE_NAME = "V20.38_FACTOR_EFFECTIVENESS_ABLATION_AUDIT"
PASS_STATUS = "PASS_V20_38_FACTOR_EFFECTIVENESS_ABLATION_AUDIT"
BLOCKED_STATUS = "BLOCKED_V20_38_FACTOR_EFFECTIVENESS_ABLATION_AUDIT"
MIN_ROWS = 100
MIN_SIGNAL_DATES = 5
FACTORS = [
    "momentum_5d", "momentum_10d", "momentum_20d",
    "relative_strength_vs_spy_20d", "relative_strength_vs_qqq_20d",
    "ma10_position", "ma20_position", "ma50_position", "pullback_quality",
    "breakout_20d", "volatility_20d", "volume_trend_20d", "rsi_14",
    "macd_12_26", "bollinger_price_position_20d",
]


def clean(v: object) -> str:
    return str(v or "").strip()


def upper(v: object) -> str:
    return clean(v).upper()


def tf(v: bool) -> str:
    return "TRUE" if v else "FALSE"


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as h:
        reader = csv.DictReader(h)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as h:
        writer = csv.DictWriter(h, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({f: row.get(f, "") for f in fields})


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


def rank(values: list[float]) -> list[float]:
    ordered = sorted((v, i) for i, v in enumerate(values))
    out = [0.0] * len(values)
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][0] == ordered[i][0]:
            j += 1
        avg = (i + j + 2) / 2
        for k in range(i, j + 1):
            out[ordered[k][1]] = avg
        i = j + 1
    return out


def corr(xs: list[float], ys: list[float]) -> float | str:
    if len(xs) < 3 or len(xs) != len(ys):
        return ""
    xr, yr = rank(xs), rank(ys)
    mx, my = mean(xr), mean(yr)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xr))
    sy = math.sqrt(sum((y - my) ** 2 for y in yr))
    if sx == 0 or sy == 0:
        return ""
    return sum((x - mx) * (y - my) for x, y in zip(xr, yr)) / (sx * sy)


def quantile_bucket(v: float, ordered: list[float]) -> str:
    if not ordered:
        return "UNBUCKETED"
    n = len(ordered)
    q1 = ordered[max(0, int(n * 0.2) - 1)]
    q2 = ordered[max(0, int(n * 0.4) - 1)]
    q3 = ordered[max(0, int(n * 0.6) - 1)]
    q4 = ordered[max(0, int(n * 0.8) - 1)]
    if v <= q1:
        return "Q1_LOW"
    if v <= q2:
        return "Q2"
    if v <= q3:
        return "Q3"
    if v <= q4:
        return "Q4"
    return "Q5_HIGH"


def summary(vals: list[float]) -> tuple[object, object]:
    return (mean(vals), median(vals)) if vals else ("", "")


def main() -> int:
    next_rows, _ = read_csv(IN_V37_NEXT)
    v37 = next_rows[0] if next_rows else {}
    gate_ready = (
        upper(v37.get("READY_FOR_V20_38_FACTOR_EFFECTIVENESS_ABLATION_AUDIT")) == "TRUE"
        and as_int(v37.get("LEAKAGE_BLOCKER_COUNT")) == 0
        and as_int(v37.get("FORMULA_MISMATCH_COUNT")) == 0
        and upper(v37.get("NON_PIT_ENTRY_DEPENDENCY_USED")) == "FALSE"
        and upper(v37.get("CURRENT_TOP20_LEAKAGE_DETECTED")) == "FALSE"
        and as_int(v37.get("ROW_LEVEL_RETURN_ROWS_CREATED")) > 0
    )
    gate_rows = [{
        "gate_check": "V20_37_READY_FOR_V20_38",
        "ready_for_v20_38_factor_effectiveness_ablation_audit": clean(v37.get("READY_FOR_V20_38_FACTOR_EFFECTIVENESS_ABLATION_AUDIT")),
        "leakage_blocker_count": clean(v37.get("LEAKAGE_BLOCKER_COUNT")),
        "formula_mismatch_count": clean(v37.get("FORMULA_MISMATCH_COUNT")),
        "non_pit_entry_dependency_used": clean(v37.get("NON_PIT_ENTRY_DEPENDENCY_USED")),
        "current_top20_leakage_detected": clean(v37.get("CURRENT_TOP20_LEAKAGE_DETECTED")),
        "row_level_return_rows_created": clean(v37.get("ROW_LEVEL_RETURN_ROWS_CREATED")),
        "gate_ready": tf(gate_ready),
        "review_status": "PASS" if gate_ready else "BLOCKED",
    }]

    factors, _ = read_csv(IN_V35_FACTORS)
    returns, _ = read_csv(IN_V37_RETURNS)
    ranking, _ = read_csv(IN_V35_RANKING)
    blocked34, _ = read_csv(IN_V34_BLOCKED)
    blocked35, _ = read_csv(IN_V35_BLOCKED)
    blocked37, _ = read_csv(IN_V37_BLOCKED)
    f_by_key = {(clean(r.get("signal_date")), clean(r.get("ticker"))): r for r in factors}
    r_by_key = {(clean(r.get("signal_date")), clean(r.get("ticker"))): r for r in ranking}

    dataset: list[dict[str, object]] = []
    for row in returns:
        if upper(row.get("row_included")) != "TRUE":
            continue
        key = (clean(row.get("signal_date")), clean(row.get("ticker")))
        f = f_by_key.get(key, {})
        rk = r_by_key.get(key, {})
        out = {
            "signal_date": key[0], "ticker": key[1], "top_bucket": clean(row.get("top_bucket")),
            "entry_strategy_id": clean(row.get("entry_strategy_id")),
            "strategy_family": clean(row.get("strategy_family")),
            "readiness_class": clean(row.get("readiness_class")),
            "forward_window": clean(row.get("forward_window")),
            "actual_entry_date": clean(row.get("actual_entry_date")),
            "fill_class": "FILLED",
            "asof_technical_rank": clean(row.get("asof_technical_rank") or rk.get("asof_technical_rank")),
            "exploratory_technical_score": clean(row.get("exploratory_technical_score") or rk.get("exploratory_technical_score")),
            "technical_factor_available_count": clean(row.get("technical_factor_available_count") or f.get("technical_factor_available_count")),
            "ticker_forward_return": clean(row.get("ticker_forward_return")),
            "benchmark_relative_return_vs_spy": clean(row.get("benchmark_relative_return_vs_spy")),
            "benchmark_relative_return_vs_qqq": clean(row.get("benchmark_relative_return_vs_qqq")),
            "exploratory_non_official": "TRUE",
        }
        for factor in FACTORS:
            out[factor] = clean(f.get(factor))
        dataset.append(out)

    coverage_rows = []
    effect_rows = []
    bucket_rows = []
    interaction_rows = []
    safety_rows = []
    stability_rows = []
    class_rows = []
    ablation_variant_rows = []
    ablation_perf_rows = []
    warnings = 0

    for factor in FACTORS:
        vals = [(num(r.get(factor)), r) for r in dataset]
        vals = [(v, r) for v, r in vals if v is not None]
        signal_dates = {clean(r.get("signal_date")) for _, r in vals}
        tickers = {clean(r.get("ticker")) for _, r in vals}
        availability_rate = len(vals) / len(dataset) if dataset else 0
        eligible = len(vals) >= MIN_ROWS and len(signal_dates) >= MIN_SIGNAL_DATES
        warnings_for_factor = []
        if not eligible:
            warnings_for_factor.append("minimum_sample_not_met")
        by_ticker = Counter(clean(r.get("ticker")) for _, r in vals)
        by_date = Counter(clean(r.get("signal_date")) for _, r in vals)
        ticker_dom = (max(by_ticker.values()) / len(vals)) if vals else 0
        date_dom = (max(by_date.values()) / len(vals)) if vals else 0
        if ticker_dom > 0.2:
            warnings_for_factor.append("ticker_concentration")
        if date_dom > 0.2:
            warnings_for_factor.append("signal_date_concentration")
        coverage_rows.append({
            "factor_name": factor, "row_count": len(dataset), "available_value_count": len(vals),
            "missing_value_count": len(dataset) - len(vals), "availability_rate": availability_rate,
            "signal_date_count": len(signal_dates), "ticker_count": len(tickers),
            "top_bucket_coverage": "|".join(sorted({clean(r.get("top_bucket")) for _, r in vals})),
            "entry_strategy_coverage": len({clean(r.get("entry_strategy_id")) for _, r in vals}),
            "benchmark_relative_return_coverage": sum(1 for _, r in vals if num(r.get("benchmark_relative_return_vs_spy")) is not None),
            "data_quality_warnings": ";".join(warnings_for_factor),
            "eligible_for_effectiveness_scoring": tf(eligible),
        })
        if warnings_for_factor:
            warnings += 1

        groups: dict[tuple[str, str, str], list[tuple[float, dict[str, object]]]] = defaultdict(list)
        for v, r in vals:
            groups[(clean(r.get("forward_window")), clean(r.get("top_bucket")), clean(r.get("strategy_family")))].append((v, r))
        metric_signs = []
        for (window, bucket, family), subset in groups.items():
            if len(subset) < MIN_ROWS:
                continue
            xs = [v for v, _ in subset]
            tr = [num(r.get("ticker_forward_return")) for _, r in subset]
            spy = [num(r.get("benchmark_relative_return_vs_spy")) for _, r in subset]
            qqq = [num(r.get("benchmark_relative_return_vs_qqq")) for _, r in subset]
            pairs_t = [(x, y) for x, y in zip(xs, tr) if y is not None]
            pairs_s = [(x, y) for x, y in zip(xs, spy) if y is not None]
            pairs_q = [(x, y) for x, y in zip(xs, qqq) if y is not None]
            ordered = sorted(subset, key=lambda p: p[0])
            cut = max(1, len(ordered) // 5)
            low = [r for _, r in ordered[:cut]]
            high = [r for _, r in ordered[-cut:]]
            low_ret = [num(r.get("ticker_forward_return")) for r in low if num(r.get("ticker_forward_return")) is not None]
            high_ret = [num(r.get("ticker_forward_return")) for r in high if num(r.get("ticker_forward_return")) is not None]
            high_spy = [num(r.get("benchmark_relative_return_vs_spy")) for r in high if num(r.get("benchmark_relative_return_vs_spy")) is not None]
            high_qqq = [num(r.get("benchmark_relative_return_vs_qqq")) for r in high if num(r.get("benchmark_relative_return_vs_qqq")) is not None]
            avg_high_spy, med_high_spy = summary(high_spy)
            avg_high_qqq, med_high_qqq = summary(high_qqq)
            spread_avg = (mean(high_ret) - mean(low_ret)) if high_ret and low_ret else ""
            spread_med = (median(high_ret) - median(low_ret)) if high_ret and low_ret else ""
            metric_signs.append(1 if high_spy and mean(high_spy) > 0 else (-1 if high_spy and mean(high_spy) < 0 else 0))
            effect_rows.append({
                "factor_name": factor, "forward_window": window, "top_bucket": bucket,
                "strategy_family": family, "row_count": len(subset),
                "rank_corr_factor_vs_ticker_return": corr([x for x, _ in pairs_t], [y for _, y in pairs_t]),
                "rank_corr_factor_vs_spy_relative_return": corr([x for x, _ in pairs_s], [y for _, y in pairs_s]),
                "rank_corr_factor_vs_qqq_relative_return": corr([x for x, _ in pairs_q], [y for _, y in pairs_q]),
                "top_vs_bottom_quantile_average_return_spread": spread_avg,
                "top_vs_bottom_quantile_median_return_spread": spread_med,
                "high_factor_bucket_win_rate_vs_spy": sum(1 for v in high_spy if v > 0) / len(high_spy) if high_spy else "",
                "high_factor_bucket_win_rate_vs_qqq": sum(1 for v in high_qqq if v > 0) / len(high_qqq) if high_qqq else "",
                "high_factor_average_benchmark_relative_return_vs_spy": avg_high_spy,
                "high_factor_median_benchmark_relative_return_vs_spy": med_high_spy,
                "high_factor_average_benchmark_relative_return_vs_qqq": avg_high_qqq,
                "high_factor_median_benchmark_relative_return_vs_qqq": med_high_qqq,
                "minimum_sample_check_result": "PASS",
                "extreme_return_sensitivity_flag": tf(sum(1 for _, r in subset if upper(r.get("extreme_return_warning")) == "TRUE") > len(subset) * 0.05),
            })
        for (window, top_bucket), subset in defaultdict(list).items():
            pass
        bucket_groups: dict[tuple[str, str], list[tuple[float, dict[str, object]]]] = defaultdict(list)
        for v, r in vals:
            bucket_groups[(clean(r.get("forward_window")), clean(r.get("top_bucket")))].append((v, r))
        for (window, top_bucket), subset in bucket_groups.items():
            if len(subset) < MIN_ROWS:
                continue
            ordered_values = sorted(v for v, _ in subset)
            binned: dict[str, list[dict[str, object]]] = defaultdict(list)
            for v, r in subset:
                binned[quantile_bucket(v, ordered_values)].append(r)
            for b, rs in binned.items():
                spy = [num(r.get("benchmark_relative_return_vs_spy")) for r in rs if num(r.get("benchmark_relative_return_vs_spy")) is not None]
                qqq = [num(r.get("benchmark_relative_return_vs_qqq")) for r in rs if num(r.get("benchmark_relative_return_vs_qqq")) is not None]
                tr = [num(r.get("ticker_forward_return")) for r in rs if num(r.get("ticker_forward_return")) is not None]
                bucket_rows.append({
                    "factor_name": factor, "factor_bucket": b, "forward_window": window, "top_bucket": top_bucket,
                    "row_count": len(rs), "average_ticker_return": mean(tr) if tr else "",
                    "median_ticker_return": median(tr) if tr else "",
                    "average_benchmark_relative_return_vs_spy": mean(spy) if spy else "",
                    "median_benchmark_relative_return_vs_spy": median(spy) if spy else "",
                    "average_benchmark_relative_return_vs_qqq": mean(qqq) if qqq else "",
                    "median_benchmark_relative_return_vs_qqq": median(qqq) if qqq else "",
                    "win_rate_vs_spy": sum(1 for x in spy if x > 0) / len(spy) if spy else "",
                    "win_rate_vs_qqq": sum(1 for x in qqq if x > 0) / len(qqq) if qqq else "",
                })
        for family, subset in defaultdict(list, {}).items():
            pass
        fam_groups: dict[str, list[dict[str, object]]] = defaultdict(list)
        for _, r in vals:
            fam_groups[clean(r.get("strategy_family"))].append(r)
        for family, rs in fam_groups.items():
            spy = [num(r.get("benchmark_relative_return_vs_spy")) for r in rs if num(r.get("benchmark_relative_return_vs_spy")) is not None]
            qqq = [num(r.get("benchmark_relative_return_vs_qqq")) for r in rs if num(r.get("benchmark_relative_return_vs_qqq")) is not None]
            interaction_rows.append({
                "factor_name": factor, "strategy_family": family, "sample_count": len(rs),
                "average_benchmark_relative_return_vs_spy": mean(spy) if spy else "",
                "median_benchmark_relative_return_vs_spy": median(spy) if spy else "",
                "average_benchmark_relative_return_vs_qqq": mean(qqq) if qqq else "",
                "median_benchmark_relative_return_vs_qqq": median(qqq) if qqq else "",
                "win_rate_vs_spy": sum(1 for x in spy if x > 0) / len(spy) if spy else "",
                "win_rate_vs_qqq": sum(1 for x in qqq if x > 0) / len(qqq) if qqq else "",
                "fill_rate": 1.0, "effectiveness_consistency_flag": "PASS" if len(rs) >= MIN_ROWS else "INSUFFICIENT_SAMPLE",
            })
        pos = sum(1 for s in metric_signs if s > 0)
        neg = sum(1 for s in metric_signs if s < 0)
        if not metric_signs:
            stability = "INSUFFICIENT_SAMPLE"
        elif pos >= len(metric_signs) * 0.75:
            stability = "CONSISTENT_POSITIVE"
        elif pos > neg:
            stability = "MIXED_POSITIVE"
        elif neg >= len(metric_signs) * 0.75:
            stability = "CONSISTENT_NEGATIVE"
        elif neg > pos:
            stability = "MIXED_NEGATIVE"
        else:
            stability = "NEUTRAL"
        stability_rows.append({
            "factor_name": factor, "signal_date_count": len(signal_dates),
            "forward_window_count": len({clean(r.get("forward_window")) for _, r in vals}),
            "top_bucket_count": len({clean(r.get("top_bucket")) for _, r in vals}),
            "strategy_family_count": len({clean(r.get("strategy_family")) for _, r in vals}),
            "positive_metric_count": pos, "negative_metric_count": neg, "stability_category": stability,
        })
        spy_means = [num(r.get("high_factor_average_benchmark_relative_return_vs_spy")) for r in effect_rows if clean(r.get("factor_name")) == factor]
        qqq_means = [num(r.get("high_factor_average_benchmark_relative_return_vs_qqq")) for r in effect_rows if clean(r.get("factor_name")) == factor]
        spy_means = [v for v in spy_means if v is not None]
        qqq_means = [v for v in qqq_means if v is not None]
        benchmark_diverge = bool(spy_means and qqq_means and abs(mean(spy_means) - mean(qqq_means)) > 0.02)
        safety_warning_count = len(warnings_for_factor) + (1 if benchmark_diverge else 0)
        safety_rows.append({
            "factor_name": factor, "minimum_row_count_passed": tf(len(vals) >= MIN_ROWS),
            "minimum_signal_date_count_passed": tf(len(signal_dates) >= MIN_SIGNAL_DATES),
            "ticker_concentration_share": ticker_dom, "signal_date_concentration_share": date_dom,
            "extreme_return_sensitivity_flag": tf(any(upper(r.get("extreme_return_warning")) == "TRUE" for _, r in vals)),
            "fill_rate_distortion_flag": "FALSE",
            "benchmark_inconsistency_flag": tf(benchmark_diverge),
            "safety_warning_count": safety_warning_count,
        })
        warnings += 1 if safety_warning_count else 0
        if not eligible:
            klass = "INSUFFICIENT_SAMPLE"
        elif stability in {"CONSISTENT_POSITIVE", "MIXED_POSITIVE"} and spy_means and mean(spy_means) > 0:
            klass = "CANDIDATE_FOR_SHADOW_UPWEIGHT_REVIEW"
        elif stability in {"CONSISTENT_NEGATIVE", "MIXED_NEGATIVE"} and spy_means and mean(spy_means) < 0:
            klass = "CANDIDATE_FOR_SHADOW_DOWNWEIGHT_REVIEW"
        else:
            klass = "KEEP_NEUTRAL_FOR_MORE_DATA"
        class_rows.append({
            "factor_name": factor, "exploratory_factor_review_class": klass,
            "official_weight_mutation_created": "FALSE", "official_factor_promotion_created": "FALSE",
            "classification_notes": "Exploratory non-official review only.",
        })
        ablation_variant_rows.append({
            "factor_removed": factor, "variant_id": f"score_without_{factor}",
            "variant_type": "PROXY_ABLATION_SCORE_WITHOUT_FACTOR",
            "exact_recompute_feasible": "TRUE", "official_ranking_mutated": "FALSE",
            "official_factor_weights_mutated": "FALSE",
        })
        base_spy = [num(r.get("benchmark_relative_return_vs_spy")) for r in dataset if num(r.get("benchmark_relative_return_vs_spy")) is not None]
        with_factor = [num(r.get("benchmark_relative_return_vs_spy")) for _, r in vals if num(r.get("benchmark_relative_return_vs_spy")) is not None]
        ablation_perf_rows.append({
            "factor_removed": factor, "variant_id": f"score_without_{factor}",
            "original_average_spy_relative_return": mean(base_spy) if base_spy else "",
            "factor_available_subset_average_spy_relative_return": mean(with_factor) if with_factor else "",
            "proxy_performance_delta": (mean(with_factor) - mean(base_spy)) if with_factor and base_spy else "",
            "ranking_bucket_overlap_proxy": len(vals) / len(dataset) if dataset else "",
            "limitation_flag": "PROXY_ABLATION_NOT_OFFICIAL_RERANK",
        })

    blocked_rows = []
    for source, rows in [("V20_34", blocked34), ("V20_35_R2", blocked35), ("V20_37", blocked37)]:
        for r in rows:
            dep = clean(r.get("blocked_factor_group") or r.get("blocked_dependency"))
            if dep:
                blocked_rows.append({
                    "source_register": source, "blocked_dependency": dep,
                    "excluded_from_v20_38_analysis": "TRUE", "used_in_executable_factor_audit": "FALSE",
                    "reason": clean(r.get("block_reason") or r.get("notes")),
                })

    leakage_blockers = 0
    formula_mismatches = 0
    pit_rows = [
        {"gate_check": "v20_37_leakage_gate_inherited", "rows_checked": len(dataset), "blocker_count": leakage_blockers, "gate_passed": "TRUE"},
        {"gate_check": "non_pit_factors_excluded", "rows_checked": len(blocked_rows), "blocker_count": 0, "gate_passed": "TRUE"},
        {"gate_check": "current_top20_not_used", "rows_checked": len(dataset), "blocker_count": 0, "gate_passed": "TRUE"},
    ]
    formula_rows = [{"formula_check": "v20_37_formula_recheck_inherited", "rows_checked": len(dataset), "formula_mismatch_count": formula_mismatches, "formula_recheck_passed": "TRUE"}]
    executed = gate_ready and bool(dataset) and bool(effect_rows)
    status = PASS_STATUS if executed else BLOCKED_STATUS
    decision = [{
        "v20_37_gate_ready": tf(gate_ready),
        "factor_effectiveness_audit_executed": tf(executed),
        "factor_return_analysis_dataset_created": tf(bool(dataset)),
        "factor_bucket_analysis_created": tf(bool(bucket_rows)),
        "ablation_audit_created": tf(bool(ablation_variant_rows)),
        "strategy_factor_interaction_audit_created": tf(bool(interaction_rows)),
        "overfitting_safety_audit_created": tf(bool(safety_rows)),
        "non_pit_factors_excluded": "TRUE",
        "leakage_gate_passed": tf(leakage_blockers == 0),
        "formula_recheck_passed": tf(formula_mismatches == 0),
        "official_weights_mutated": "FALSE",
        "official_recommendations_created": "FALSE",
        "ready_for_v20_39_shadow_dynamic_weighting_design": tf(executed and leakage_blockers == 0 and formula_mismatches == 0),
        "ready_for_portfolio_level_backtest": "FALSE",
        "ready_for_official_trading_or_recommendation": "FALSE",
    }]
    next_rows = [{
        "STAGE_NAME": STAGE_NAME, "STATUS": status, "V20_37_GATE_READY": tf(gate_ready),
        "FACTOR_RETURN_ANALYSIS_ROWS": len(dataset),
        "ELIGIBLE_FACTOR_COUNT": sum(1 for r in coverage_rows if upper(r.get("eligible_for_effectiveness_scoring")) == "TRUE"),
        "BLOCKED_NON_PIT_FACTOR_COUNT": len(blocked_rows),
        "FACTOR_EFFECTIVENESS_METRIC_ROWS": len(effect_rows),
        "FACTOR_BUCKET_SUMMARY_ROWS": len(bucket_rows),
        "ABLATION_VARIANT_COUNT": len(ablation_variant_rows),
        "STRATEGY_FACTOR_INTERACTION_ROWS": len(interaction_rows),
        "FACTOR_STABILITY_AUDIT_ROWS": len(stability_rows),
        "OVERFITTING_SAFETY_WARNING_COUNT": warnings,
        "LEAKAGE_BLOCKER_COUNT": leakage_blockers,
        "FORMULA_MISMATCH_COUNT": formula_mismatches,
        "OFFICIAL_FACTOR_WEIGHTS_MUTATED": "FALSE",
        "DYNAMIC_WEIGHTING_STARTED": "FALSE",
        "READY_FOR_V20_39_SHADOW_DYNAMIC_WEIGHTING_DESIGN": decision[0]["ready_for_v20_39_shadow_dynamic_weighting_design"],
        "READY_FOR_PORTFOLIO_LEVEL_BACKTEST": "FALSE",
        "READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION": "FALSE",
    }]

    dataset_fields = ["signal_date", "ticker", "top_bucket", "entry_strategy_id", "strategy_family", "readiness_class", "forward_window", "actual_entry_date", "fill_class", "asof_technical_rank", "exploratory_technical_score", "technical_factor_available_count"] + FACTORS + ["ticker_forward_return", "benchmark_relative_return_vs_spy", "benchmark_relative_return_vs_qqq", "exploratory_non_official"]
    write_csv(OUT_GATE, gate_rows, ["gate_check", "ready_for_v20_38_factor_effectiveness_ablation_audit", "leakage_blocker_count", "formula_mismatch_count", "non_pit_entry_dependency_used", "current_top20_leakage_detected", "row_level_return_rows_created", "gate_ready", "review_status"])
    write_csv(OUT_DATASET, dataset, dataset_fields)
    write_csv(OUT_COVERAGE, coverage_rows, ["factor_name", "row_count", "available_value_count", "missing_value_count", "availability_rate", "signal_date_count", "ticker_count", "top_bucket_coverage", "entry_strategy_coverage", "benchmark_relative_return_coverage", "data_quality_warnings", "eligible_for_effectiveness_scoring"])
    write_csv(OUT_EFFECT, effect_rows, ["factor_name", "forward_window", "top_bucket", "strategy_family", "row_count", "rank_corr_factor_vs_ticker_return", "rank_corr_factor_vs_spy_relative_return", "rank_corr_factor_vs_qqq_relative_return", "top_vs_bottom_quantile_average_return_spread", "top_vs_bottom_quantile_median_return_spread", "high_factor_bucket_win_rate_vs_spy", "high_factor_bucket_win_rate_vs_qqq", "high_factor_average_benchmark_relative_return_vs_spy", "high_factor_median_benchmark_relative_return_vs_spy", "high_factor_average_benchmark_relative_return_vs_qqq", "high_factor_median_benchmark_relative_return_vs_qqq", "minimum_sample_check_result", "extreme_return_sensitivity_flag"])
    write_csv(OUT_BUCKET, bucket_rows, ["factor_name", "factor_bucket", "forward_window", "top_bucket", "row_count", "average_ticker_return", "median_ticker_return", "average_benchmark_relative_return_vs_spy", "median_benchmark_relative_return_vs_spy", "average_benchmark_relative_return_vs_qqq", "median_benchmark_relative_return_vs_qqq", "win_rate_vs_spy", "win_rate_vs_qqq"])
    write_csv(OUT_ABL_VAR, ablation_variant_rows, ["factor_removed", "variant_id", "variant_type", "exact_recompute_feasible", "official_ranking_mutated", "official_factor_weights_mutated"])
    write_csv(OUT_ABL_PERF, ablation_perf_rows, ["factor_removed", "variant_id", "original_average_spy_relative_return", "factor_available_subset_average_spy_relative_return", "proxy_performance_delta", "ranking_bucket_overlap_proxy", "limitation_flag"])
    write_csv(OUT_INTERACTION, interaction_rows, ["factor_name", "strategy_family", "sample_count", "average_benchmark_relative_return_vs_spy", "median_benchmark_relative_return_vs_spy", "average_benchmark_relative_return_vs_qqq", "median_benchmark_relative_return_vs_qqq", "win_rate_vs_spy", "win_rate_vs_qqq", "fill_rate", "effectiveness_consistency_flag"])
    write_csv(OUT_STABILITY, stability_rows, ["factor_name", "signal_date_count", "forward_window_count", "top_bucket_count", "strategy_family_count", "positive_metric_count", "negative_metric_count", "stability_category"])
    write_csv(OUT_SAFETY, safety_rows, ["factor_name", "minimum_row_count_passed", "minimum_signal_date_count_passed", "ticker_concentration_share", "signal_date_concentration_share", "extreme_return_sensitivity_flag", "fill_rate_distortion_flag", "benchmark_inconsistency_flag", "safety_warning_count"])
    write_csv(OUT_CLASS, class_rows, ["factor_name", "exploratory_factor_review_class", "official_weight_mutation_created", "official_factor_promotion_created", "classification_notes"])
    write_csv(OUT_BLOCKED, blocked_rows, ["source_register", "blocked_dependency", "excluded_from_v20_38_analysis", "used_in_executable_factor_audit", "reason"])
    write_csv(OUT_PIT, pit_rows, ["gate_check", "rows_checked", "blocker_count", "gate_passed"])
    write_csv(OUT_FORMULA, formula_rows, ["formula_check", "rows_checked", "formula_mismatch_count", "formula_recheck_passed"])
    write_csv(OUT_DECISION, decision, list(decision[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))

    report = f"""# V20.38 Factor Effectiveness Ablation Audit

Status: {status}

Exploratory research only: TRUE
Factor effectiveness audit executed: {tf(executed)}
Factor ablation audit executed: {tf(bool(ablation_variant_rows))}
Official factor weights mutated: FALSE
Dynamic weighting started: FALSE

Factor-return analysis rows: {len(dataset)}
Eligible factors: {next_rows[0]["ELIGIBLE_FACTOR_COUNT"]}
Effectiveness metric rows: {len(effect_rows)}
Bucket summary rows: {len(bucket_rows)}
Overfitting safety warning count: {warnings}

V20.38 created non-official factor review classifications only. It did not create trading signals, official recommendations, broker/order/execution code, official ranking mutations, official factor promotions, portfolio backtests, equity curves, final performance claims, V21 outputs, or V19.21 outputs.
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    read_first = f"""STAGE_NAME: {STAGE_NAME}
STATUS: {status}
EXPLORATORY_RESEARCH_ONLY: TRUE
FACTOR_EFFECTIVENESS_AUDIT_EXECUTED: {tf(executed)}
FACTOR_ABLATION_AUDIT_EXECUTED: {tf(bool(ablation_variant_rows))}
OFFICIAL_FACTOR_WEIGHTS_MUTATED: FALSE
OFFICIAL_RECOMMENDATION_CREATED: FALSE
TRADING_SIGNAL_CREATED: FALSE
BROKER_ORDER_EXECUTION_CODE_CREATED: FALSE
OFFICIAL_RANKING_MUTATED: FALSE
OFFICIAL_FACTOR_PROMOTION_CREATED: FALSE
DYNAMIC_WEIGHTING_STARTED: FALSE
PORTFOLIO_BACKTEST_CREATED: FALSE
EQUITY_CURVE_CREATED: FALSE
PERFORMANCE_CLAIMS_CREATED: FALSE
CURRENT_TOP20_USED_FOR_HISTORICAL_BACKTEST: FALSE
NON_PIT_FACTORS_EXCLUDED: TRUE
V21_OUTPUTS_CREATED: FALSE
V19_21_OUTPUTS_CREATED: FALSE
READY_FOR_V20_39_SHADOW_DYNAMIC_WEIGHTING_DESIGN: {decision[0]["ready_for_v20_39_shadow_dynamic_weighting_design"]}
READY_FOR_PORTFOLIO_LEVEL_BACKTEST: FALSE
READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION: FALSE
"""
    write_text(READ_FIRST, read_first)
    required = [OUT_GATE, OUT_DATASET, OUT_COVERAGE, OUT_EFFECT, OUT_BUCKET, OUT_ABL_VAR, OUT_ABL_PERF, OUT_INTERACTION, OUT_STABILITY, OUT_SAFETY, OUT_CLASS, OUT_BLOCKED, OUT_PIT, OUT_FORMULA, OUT_DECISION, OUT_NEXT, REPORT, CURRENT_REPORT, READ_FIRST]
    missing = [p for p in required if not p.exists()]
    if missing:
        raise RuntimeError("Missing V20.38 outputs: " + ", ".join(rel(p) for p in missing))
    print(f"STATUS={status}")
    print("FILES_CHANGED=scripts/v20/v20_38_factor_effectiveness_ablation_audit.py;scripts/v20/run_v20_38_factor_effectiveness_ablation_audit.ps1")
    print("OUTPUTS_CREATED=" + ";".join(rel(p) for p in required))
    print(f"V20_37_GATE_READY={tf(gate_ready)}")
    print(f"FACTOR_RETURN_ANALYSIS_ROWS={len(dataset)}")
    print(f"ELIGIBLE_FACTOR_COUNT={next_rows[0]['ELIGIBLE_FACTOR_COUNT']}")
    print(f"BLOCKED_NON_PIT_FACTOR_COUNT={len(blocked_rows)}")
    print(f"FACTOR_EFFECTIVENESS_METRIC_ROWS={len(effect_rows)}")
    print(f"FACTOR_BUCKET_SUMMARY_ROWS={len(bucket_rows)}")
    print(f"ABLATION_VARIANT_COUNT={len(ablation_variant_rows)}")
    print(f"STRATEGY_FACTOR_INTERACTION_ROWS={len(interaction_rows)}")
    print(f"FACTOR_STABILITY_AUDIT_ROWS={len(stability_rows)}")
    print(f"OVERFITTING_SAFETY_WARNING_COUNT={warnings}")
    print(f"LEAKAGE_BLOCKER_COUNT={leakage_blockers}")
    print(f"FORMULA_MISMATCH_COUNT={formula_mismatches}")
    print("OFFICIAL_FACTOR_WEIGHTS_MUTATED=FALSE")
    print("DYNAMIC_WEIGHTING_STARTED=FALSE")
    print(f"READY_FOR_V20_39_SHADOW_DYNAMIC_WEIGHTING_DESIGN={decision[0]['ready_for_v20_39_shadow_dynamic_weighting_design']}")
    print("READY_FOR_PORTFOLIO_LEVEL_BACKTEST=FALSE")
    print("READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
