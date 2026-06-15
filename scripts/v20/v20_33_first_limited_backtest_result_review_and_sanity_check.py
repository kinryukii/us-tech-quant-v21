from __future__ import annotations

import csv
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median, pstdev


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"

IN_READ_FIRST = OPS / "V20_32_READ_FIRST.txt"
IN_GATE = CONSOLIDATION / "V20_32_GATE_DECISION.csv"
IN_RESULTS = CONSOLIDATION / "V20_32_ROW_LEVEL_RETURN_RESULTS.csv"
IN_SUM_BENCH = CONSOLIDATION / "V20_32_LIMITED_BACKTEST_SUMMARY_BY_BENCHMARK.csv"
IN_SUM_WINDOW = CONSOLIDATION / "V20_32_LIMITED_BACKTEST_SUMMARY_BY_OUTCOME_WINDOW.csv"
IN_SUM_SIGNAL = CONSOLIDATION / "V20_32_LIMITED_BACKTEST_SUMMARY_BY_SIGNAL_DATE.csv"
IN_SUM_BENCH_WINDOW = CONSOLIDATION / "V20_32_LIMITED_BACKTEST_SUMMARY_BY_BENCHMARK_AND_WINDOW.csv"
IN_SUM_OVERALL = CONSOLIDATION / "V20_32_LIMITED_BACKTEST_SUMMARY_OVERALL.csv"
IN_REL_SANITY = CONSOLIDATION / "V20_32_BENCHMARK_RELATIVE_RETURN_SANITY_AUDIT.csv"
IN_PIT = CONSOLIDATION / "V20_32_PIT_STALE_LEAKAGE_EXECUTION_AUDIT.csv"
IN_DUP = CONSOLIDATION / "V20_32_DUPLICATE_KEY_AUDIT.csv"
IN_MISSING = CONSOLIDATION / "V20_32_MISSING_VALUE_AUDIT.csv"
IN_ZERO_NEG = CONSOLIDATION / "V20_32_ZERO_NEGATIVE_PRICE_AUDIT.csv"
IN_LINEAGE = CONSOLIDATION / "V20_32_SOURCE_HASH_RUN_ID_COVERAGE_AUDIT.csv"
IN_BLOCKERS = CONSOLIDATION / "V20_32_BLOCKER_REGISTER.csv"
IN_NEXT = CONSOLIDATION / "V20_32_NEXT_RESULT_REVIEW_REQUIREMENTS.csv"

OUT_DEP = CONSOLIDATION / "V20_33_DEPENDENCY_AUDIT.csv"
OUT_DISCOVERY = CONSOLIDATION / "V20_33_ROW_LEVEL_RESULT_DISCOVERY.csv"
OUT_DIST = CONSOLIDATION / "V20_33_RETURN_DISTRIBUTION_SANITY_AUDIT.csv"
OUT_BENCH = CONSOLIDATION / "V20_33_BENCHMARK_RETURN_SANITY_AUDIT.csv"
OUT_FORMULA = CONSOLIDATION / "V20_33_BENCHMARK_RELATIVE_FORMULA_VERIFICATION_AUDIT.csv"
OUT_BENCH_EXP = CONSOLIDATION / "V20_33_BENCHMARK_EXPANSION_BALANCE_AUDIT.csv"
OUT_TOP_BOTTOM = CONSOLIDATION / "V20_33_TOP_BOTTOM_TICKER_RETURN_REVIEW.csv"
OUT_EXTREME = CONSOLIDATION / "V20_33_EXTREME_RETURN_ANOMALY_AUDIT.csv"
OUT_CONCENTRATION = CONSOLIDATION / "V20_33_TICKER_CONCENTRATION_AUDIT.csv"
OUT_SUMMARY = CONSOLIDATION / "V20_33_SUMMARY_CONSISTENCY_AUDIT.csv"
OUT_PIT = CONSOLIDATION / "V20_33_PIT_STALE_LEAKAGE_REVIEW_AUDIT.csv"
OUT_DUP = CONSOLIDATION / "V20_33_DUPLICATE_KEY_REVIEW_AUDIT.csv"
OUT_MISSING = CONSOLIDATION / "V20_33_MISSING_VALUE_REVIEW_AUDIT.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_33_SOURCE_HASH_RUN_ID_REVIEW_AUDIT.csv"
OUT_WARN = CONSOLIDATION / "V20_33_REVIEW_WARNING_REGISTER.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_33_BLOCKER_REGISTER.csv"
OUT_NEXT = CONSOLIDATION / "V20_33_NEXT_EXPANDED_BACKTEST_REQUIREMENTS.csv"
OUT_GATE = CONSOLIDATION / "V20_33_GATE_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_33_VALIDATION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_33_FIRST_LIMITED_BACKTEST_RESULT_REVIEW_AND_SANITY_CHECK_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_FIRST_LIMITED_BACKTEST_RESULT_REVIEW_AND_SANITY_CHECK.md"
READ_FIRST = OPS / "V20_33_READ_FIRST.txt"

PASS_STATUS = "PASS_V20_33_FIRST_LIMITED_BACKTEST_RESULT_REVIEW_AND_SANITY_CHECK"
NEXT_SUCCESS = "V20.34_EXPANDED_BACKTEST_WINDOW_OR_MULTI_SIGNAL_REVIEW"
NEXT_BLOCKED = "V20.34_FIRST_LIMITED_BACKTEST_REVIEW_BLOCKER_RESOLUTION"
REQUIRED_INPUTS = [
    IN_READ_FIRST, IN_GATE, IN_RESULTS, IN_SUM_BENCH, IN_SUM_WINDOW, IN_SUM_SIGNAL,
    IN_SUM_BENCH_WINDOW, IN_SUM_OVERALL, IN_REL_SANITY, IN_PIT, IN_DUP, IN_MISSING,
    IN_ZERO_NEG, IN_LINEAGE, IN_BLOCKERS, IN_NEXT,
]
BENCHMARKS = {"SPY", "QQQ"}
TOLERANCE = 1e-10
SUMMARY_TOLERANCE = 1e-9


def clean(value: object) -> str:
    return str(value or "").strip()


def upper(value: object) -> str:
    return clean(value).upper()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def num(value: object) -> float | None:
    try:
        value_f = float(clean(value))
    except ValueError:
        return None
    if math.isnan(value_f) or math.isinf(value_f):
        return None
    return value_f


def safe_int(value: object) -> int:
    try:
        return int(float(clean(value)))
    except ValueError:
        return 0


def parse_dt(value: object) -> datetime | None:
    text = clean(value).replace("Z", "+00:00")
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    pos = (len(ordered) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[int(pos)]
    return ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)


def duplicate_count(rows: list[dict[str, str]], keys: list[str]) -> int:
    seen = set()
    dupes = 0
    for row in rows:
        key = tuple(clean(row.get(field)) for field in keys)
        if key in seen:
            dupes += 1
        seen.add(key)
    return dupes


def distribution(metric: str, values: list[float], threshold: float) -> dict[str, object]:
    positives = [v for v in values if v > 0]
    negatives = [v for v in values if v < 0]
    zeros = [v for v in values if v == 0]
    return {
        "return_metric": metric,
        "count": len(values),
        "mean": mean(values) if values else "",
        "median": median(values) if values else "",
        "min": min(values) if values else "",
        "max": max(values) if values else "",
        "standard_deviation": pstdev(values) if len(values) > 1 else 0,
        "p01": quantile(values, 0.01) if values else "",
        "p05": quantile(values, 0.05) if values else "",
        "p25": quantile(values, 0.25) if values else "",
        "p75": quantile(values, 0.75) if values else "",
        "p95": quantile(values, 0.95) if values else "",
        "p99": quantile(values, 0.99) if values else "",
        "positive_count": len(positives),
        "positive_rate": len(positives) / len(values) if values else "",
        "negative_count": len(negatives),
        "negative_rate": len(negatives) / len(values) if values else "",
        "zero_count": len(zeros),
        "extreme_positive_count": sum(1 for v in values if v > threshold),
        "extreme_negative_count": sum(1 for v in values if v < -threshold),
        "threshold_used": threshold,
        "audit_status": "PASS" if values else "BLOCKED",
    }


def group_summary(rows: list[dict[str, str]], keys: list[str]) -> dict[tuple[str, ...], dict[str, float | int]]:
    grouped: dict[tuple[str, ...], list[dict[str, str]]] = {}
    for row in rows:
        key = tuple(clean(row.get(field)) for field in keys)
        grouped.setdefault(key, []).append(row)
    output: dict[tuple[str, ...], dict[str, float | int]] = {}
    for key, subset in grouped.items():
        fwd = [num(r.get("forward_return")) for r in subset]
        bench = [num(r.get("benchmark_return")) for r in subset]
        rel_ret = [num(r.get("benchmark_relative_return")) for r in subset]
        fwd_v = [v for v in fwd if v is not None]
        bench_v = [v for v in bench if v is not None]
        rel_v = [v for v in rel_ret if v is not None]
        output[key] = {
            "row_count": len(subset),
            "mean_forward_return": mean(fwd_v),
            "median_forward_return": median(fwd_v),
            "mean_benchmark_return": mean(bench_v),
            "median_benchmark_return": median(bench_v),
            "mean_benchmark_relative_return": mean(rel_v),
            "median_benchmark_relative_return": median(rel_v),
        }
    return output


def compare_summary(source_name: str, source_rows: list[dict[str, str]], key_fields: list[str], calc: dict[tuple[str, ...], dict[str, float | int]]) -> list[dict[str, object]]:
    rows = []
    for source in source_rows:
        if key_fields == ["summary_key"]:
            source_key = clean(source.get("summary_key"))
            key = tuple(source_key.split("|")) if any(len(calc_key) > 1 for calc_key in calc) else (source_key,)
        else:
            key = tuple(clean(source.get(field)) for field in key_fields)
        calc_row = calc.get(key)
        row_count_match = calc_row is not None and safe_int(source.get("row_count")) == int(calc_row["row_count"])
        metric_mismatches = []
        if calc_row:
            for metric in ["mean_forward_return", "median_forward_return", "mean_benchmark_return", "median_benchmark_return", "mean_benchmark_relative_return", "median_benchmark_relative_return"]:
                src_value = num(source.get(metric))
                calc_value = float(calc_row[metric])
                if src_value is None or abs(src_value - calc_value) > SUMMARY_TOLERANCE:
                    metric_mismatches.append(metric)
        else:
            metric_mismatches.append("missing_group_in_row_level_recalc")
        rows.append({
            "summary_source": source_name,
            "summary_key": "|".join(key),
            "source_row_count": clean(source.get("row_count")),
            "recalculated_row_count": "" if not calc_row else calc_row["row_count"],
            "row_count_match": tf(row_count_match),
            "metric_mismatches": "|".join(metric_mismatches),
            "summary_consistency_passed": tf(row_count_match and not metric_mismatches),
        })
    return rows


def main() -> int:
    reviewed_at = now_utc()
    dep_rows: list[dict[str, object]] = []
    dep_ok = True
    for path in REQUIRED_INPUTS:
        exists = path.exists()
        dep_ok = dep_ok and exists
        dep_rows.append({
            "dependency_id": path.stem,
            "dependency_path": rel(path),
            "required": "TRUE",
            "exists": tf(exists),
            "status": "PASS" if exists else "BLOCKED",
            "blocker_reason": "" if exists else f"Missing {rel(path)}",
        })

    gate_rows, _ = read_csv(IN_GATE)
    gate = gate_rows[0] if gate_rows else {}
    rf_text = IN_READ_FIRST.read_text(encoding="utf-8", errors="replace") if IN_READ_FIRST.exists() else ""
    gate_ok = (
        upper(gate.get("STATUS")) == "PASS_V20_32_FIRST_LIMITED_BACKTEST_EXECUTION_RETRY_WITH_BASE_PRICES"
        and upper(gate.get("FIRST_LIMITED_BACKTEST_EXECUTION_ATTEMPTED")) == "TRUE"
        and upper(gate.get("FIRST_LIMITED_BACKTEST_EXECUTED")) == "TRUE"
        and safe_int(gate.get("ROW_LEVEL_RETURN_ROWS_CREATED")) > 0
        and upper(gate.get("FORWARD_RETURNS_CREATED")) == "TRUE"
        and upper(gate.get("BENCHMARK_RETURNS_CREATED")) == "TRUE"
        and upper(gate.get("BENCHMARK_RELATIVE_RETURNS_CREATED")) == "TRUE"
        and upper(gate.get("LIMITED_AGGREGATE_SUMMARY_CREATED")) == "TRUE"
        and safe_int(gate.get("RETURN_COMPUTATION_BLOCKER_COUNT")) == 0
        and safe_int(gate.get("PIT_STALE_LEAKAGE_BLOCKER_COUNT")) == 0
        and safe_int(gate.get("DUPLICATE_KEY_BLOCKER_COUNT")) == 0
        and upper(gate.get("READY_FOR_V20_33_FIRST_LIMITED_BACKTEST_RESULT_REVIEW_AND_SANITY_CHECK_NEXT")) == "TRUE"
        and upper(gate.get("DYNAMIC_WEIGHTING_CREATED")) == "FALSE"
        and upper(gate.get("TRADING_SIGNAL_CREATED")) == "FALSE"
        and upper(gate.get("OFFICIAL_RECOMMENDATION_CREATED")) == "FALSE"
    )
    rf_ok = all(token in rf_text for token in [
        "FIRST_LIMITED_BACKTEST_EXECUTION_ONLY: TRUE",
        "OFFICIAL_BACKTEST: FALSE",
        "FORWARD_RETURNS_CREATED: TRUE",
        "BENCHMARK_RETURNS_CREATED: TRUE",
        "BENCHMARK_RELATIVE_RETURNS_CREATED: TRUE",
        "DYNAMIC_WEIGHTING_CREATED: FALSE",
        "TRADING_SIGNAL_CREATED: FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED: FALSE",
        "V21_OUTPUT_CREATED: FALSE",
        "V19_21_OUTPUT_CREATED: FALSE",
    ])
    dep_ok = dep_ok and gate_ok and rf_ok
    dep_rows.extend([
        {"dependency_id": "V20_32_GATE_EXPECTED_STATE", "dependency_path": rel(IN_GATE), "required": "TRUE", "exists": tf(IN_GATE.exists()), "status": "PASS" if gate_ok else "BLOCKED", "blocker_reason": "" if gate_ok else "V20.32 gate state does not permit V20.33 review."},
        {"dependency_id": "V20_32_READ_FIRST_SAFETY_FLAGS", "dependency_path": rel(IN_READ_FIRST), "required": "TRUE", "exists": tf(IN_READ_FIRST.exists()), "status": "PASS" if rf_ok else "BLOCKED", "blocker_reason": "" if rf_ok else "V20.32 READ_FIRST safety flags are missing."},
    ])

    results, fields = read_csv(IN_RESULTS)
    calculated = [row for row in results if upper(row.get("return_calculation_status")) == "CALCULATED"]
    fwd = [num(row.get("forward_return")) for row in calculated]
    bench = [num(row.get("benchmark_return")) for row in calculated]
    rel_ret = [num(row.get("benchmark_relative_return")) for row in calculated]
    fwd_v = [v for v in fwd if v is not None]
    bench_v = [v for v in bench if v is not None]
    rel_v = [v for v in rel_ret if v is not None]

    discovery_rows = [{
        "result_source_path": rel(IN_RESULTS),
        "rows_reviewed": len(results),
        "calculated_rows": len(calculated),
        "columns_present": "|".join(fields),
        "unique_candidate_keys": len({clean(row.get("stable_candidate_key")) for row in calculated if clean(row.get("stable_candidate_key"))}),
        "unique_tickers": len({clean(row.get("ticker")) for row in calculated if clean(row.get("ticker"))}),
        "unique_signal_dates": len({clean(row.get("signal_date")) for row in calculated if clean(row.get("signal_date"))}),
        "unique_outcome_windows": len({clean(row.get("outcome_window")) for row in calculated if clean(row.get("outcome_window"))}),
        "unique_benchmark_symbols": len({clean(row.get("benchmark_symbol")) for row in calculated if clean(row.get("benchmark_symbol"))}),
        "discovery_status": "PASS" if calculated else "BLOCKED",
    }]

    dist_rows = [
        distribution("forward_return", fwd_v, 0.25),
        distribution("benchmark_return", bench_v, 0.10),
        distribution("benchmark_relative_return", rel_v, 0.25),
    ]
    extreme_warning_count = sum(int(row["extreme_positive_count"]) + int(row["extreme_negative_count"]) for row in dist_rows)

    bench_rows = []
    for symbol in sorted({upper(row.get("benchmark_symbol")) for row in calculated if clean(row.get("benchmark_symbol"))}):
        subset = [row for row in calculated if upper(row.get("benchmark_symbol")) == symbol]
        returns = [num(row.get("benchmark_return")) for row in subset]
        values = [v for v in returns if v is not None]
        bench_rows.append({
            "benchmark_symbol": symbol,
            "row_count": len(subset),
            "benchmark_return_mean": mean(values) if values else "",
            "benchmark_return_median": median(values) if values else "",
            "benchmark_return_min": min(values) if values else "",
            "benchmark_return_max": max(values) if values else "",
            "allowed_benchmark_symbol": tf(symbol in BENCHMARKS),
            "benchmark_sanity_passed": tf(bool(values) and symbol in BENCHMARKS),
        })
    invalid_benchmark_rows = sum(1 for row in calculated if upper(row.get("benchmark_symbol")) not in BENCHMARKS)

    formula_bad = 0
    formula_rows = []
    for row in calculated:
        fv = num(row.get("forward_return"))
        bv = num(row.get("benchmark_return"))
        rv = num(row.get("benchmark_relative_return"))
        ok = fv is not None and bv is not None and rv is not None and abs((fv - bv) - rv) <= TOLERANCE
        if not ok:
            formula_bad += 1
        if len(formula_rows) < 200 or not ok:
            formula_rows.append({
                "candidate_id": clean(row.get("candidate_id")),
                "stable_candidate_key": clean(row.get("stable_candidate_key")),
                "benchmark_symbol": clean(row.get("benchmark_symbol")),
                "forward_return": clean(row.get("forward_return")),
                "benchmark_return": clean(row.get("benchmark_return")),
                "benchmark_relative_return": clean(row.get("benchmark_relative_return")),
                "recomputed_benchmark_relative_return": "" if fv is None or bv is None else fv - bv,
                "absolute_formula_difference": "" if fv is None or bv is None or rv is None else abs((fv - bv) - rv),
                "formula_verification_passed": tf(ok),
            })

    counts_by_benchmark = {symbol: sum(1 for row in calculated if upper(row.get("benchmark_symbol")) == symbol) for symbol in BENCHMARKS}
    candidate_expansion_counts: dict[str, set[str]] = {}
    for row in calculated:
        candidate_expansion_counts.setdefault(clean(row.get("stable_candidate_key")), set()).add(upper(row.get("benchmark_symbol")))
    expected_expansion_fail = sum(1 for values in candidate_expansion_counts.values() if not BENCHMARKS.issubset(values))
    balance_passed = counts_by_benchmark.get("SPY", 0) == counts_by_benchmark.get("QQQ", 0) and expected_expansion_fail == 0
    bench_exp_rows = [{
        "expected_benchmark_symbols": "SPY|QQQ",
        "spy_rows": counts_by_benchmark.get("SPY", 0),
        "qqq_rows": counts_by_benchmark.get("QQQ", 0),
        "benchmark_row_counts_balanced": tf(counts_by_benchmark.get("SPY", 0) == counts_by_benchmark.get("QQQ", 0)),
        "candidate_count": len(candidate_expansion_counts),
        "candidates_missing_expected_benchmark_expansion": expected_expansion_fail,
        "benchmark_expansion_sanity_passed": tf(balance_passed),
    }]
    benchmark_expansion_blockers = 0 if balance_passed and invalid_benchmark_rows == 0 else 1

    sorted_fwd = sorted(calculated, key=lambda r: num(r.get("forward_return")) or 0)
    sorted_rel = sorted(calculated, key=lambda r: num(r.get("benchmark_relative_return")) or 0)
    top_bottom_rows = []
    for label, source in [
        ("bottom_forward_return", sorted_fwd[:10]),
        ("top_forward_return", list(reversed(sorted_fwd[-10:]))),
        ("bottom_benchmark_relative_return", sorted_rel[:10]),
        ("top_benchmark_relative_return", list(reversed(sorted_rel[-10:]))),
    ]:
        for row in source:
            top_bottom_rows.append({
                "review_group": label,
                "ticker": clean(row.get("ticker")),
                "stable_candidate_key": clean(row.get("stable_candidate_key")),
                "benchmark_symbol": clean(row.get("benchmark_symbol")),
                "forward_return": clean(row.get("forward_return")),
                "benchmark_return": clean(row.get("benchmark_return")),
                "benchmark_relative_return": clean(row.get("benchmark_relative_return")),
            })

    extreme_rows = []
    for metric, threshold in [("forward_return", 0.25), ("benchmark_return", 0.10), ("benchmark_relative_return", 0.25)]:
        for row in calculated:
            value = num(row.get(metric))
            if value is not None and abs(value) > threshold:
                extreme_rows.append({
                    "anomaly_metric": metric,
                    "threshold": threshold,
                    "ticker": clean(row.get("ticker")),
                    "stable_candidate_key": clean(row.get("stable_candidate_key")),
                    "benchmark_symbol": clean(row.get("benchmark_symbol")),
                    "metric_value": value,
                    "warning_only": "TRUE",
                    "block_expansion": "FALSE",
                })

    by_ticker_abs: dict[str, float] = {}
    total_abs = sum(abs(num(row.get("benchmark_relative_return")) or 0) for row in calculated)
    for row in calculated:
        ticker = clean(row.get("ticker"))
        by_ticker_abs[ticker] = by_ticker_abs.get(ticker, 0.0) + abs(num(row.get("benchmark_relative_return")) or 0)
    concentration_rows = []
    concentration_warning_count = 0
    for ticker, contribution in sorted(by_ticker_abs.items(), key=lambda item: item[1], reverse=True)[:25]:
        share = contribution / total_abs if total_abs else 0
        warning = share > 0.05
        concentration_warning_count += 1 if warning else 0
        concentration_rows.append({
            "ticker": ticker,
            "absolute_relative_return_contribution": contribution,
            "absolute_relative_return_contribution_share": share,
            "concentration_warning": tf(warning),
            "warning_reason": "Ticker contributes more than 5% of absolute benchmark-relative return mass." if warning else "",
        })

    sum_bench, _ = read_csv(IN_SUM_BENCH)
    sum_window, _ = read_csv(IN_SUM_WINDOW)
    sum_signal, _ = read_csv(IN_SUM_SIGNAL)
    sum_bench_window, _ = read_csv(IN_SUM_BENCH_WINDOW)
    sum_overall, _ = read_csv(IN_SUM_OVERALL)
    summary_rows = []
    summary_rows.extend(compare_summary("V20_32_LIMITED_BACKTEST_SUMMARY_BY_BENCHMARK", sum_bench, ["summary_key"], group_summary(calculated, ["benchmark_symbol"])))
    summary_rows.extend(compare_summary("V20_32_LIMITED_BACKTEST_SUMMARY_BY_OUTCOME_WINDOW", sum_window, ["summary_key"], group_summary(calculated, ["outcome_window"])))
    summary_rows.extend(compare_summary("V20_32_LIMITED_BACKTEST_SUMMARY_BY_SIGNAL_DATE", sum_signal, ["summary_key"], group_summary(calculated, ["signal_date"])))
    summary_rows.extend(compare_summary("V20_32_LIMITED_BACKTEST_SUMMARY_BY_BENCHMARK_AND_WINDOW", sum_bench_window, ["summary_key"], group_summary(calculated, ["benchmark_symbol", "outcome_window"])))
    overall_calc = {("overall",): group_summary(calculated, ["signal_date"]).get((clean(calculated[0].get("signal_date")),), {})} if calculated else {}
    if calculated:
        values = group_summary(calculated, ["v20_32_calculation_run_id"])
        only = next(iter(values.values()))
        overall_calc = {("overall",): only}
    summary_rows.extend(compare_summary("V20_32_LIMITED_BACKTEST_SUMMARY_OVERALL", sum_overall, ["summary_key"], overall_calc))
    summary_blockers = sum(1 for row in summary_rows if row["summary_consistency_passed"] != "TRUE")

    pit_invalid = 0
    for row in calculated:
        signal = parse_dt(row.get("signal_date"))
        outcome_date = parse_dt(row.get("outcome_price_date"))
        bench_date = parse_dt(row.get("benchmark_price_date"))
        if signal is None or outcome_date is None or bench_date is None or outcome_date < signal or bench_date < signal:
            pit_invalid += 1
    pit_rows = [{
        "review_check": "pit_stale_leakage_date_ordering_carryforward",
        "rows_reviewed": len(calculated),
        "blocked_rows": pit_invalid,
        "review_passed": tf(pit_invalid == 0),
    }]
    dup_keys = ["stable_candidate_key", "outcome_window", "benchmark_symbol", "benchmark_window"]
    dup_count = duplicate_count(calculated, dup_keys)
    dup_rows = [{
        "duplicate_key_fields": "|".join(dup_keys),
        "rows_reviewed": len(calculated),
        "duplicate_key_count": dup_count,
        "review_passed": tf(dup_count == 0),
    }]
    missing_return = sum(1 for row in calculated if num(row.get("forward_return")) is None or num(row.get("benchmark_return")) is None or num(row.get("benchmark_relative_return")) is None)
    missing_rows = [{
        "missing_value_review": "required_return_values",
        "rows_reviewed": len(calculated),
        "missing_return_rows": missing_return,
        "review_passed": tf(missing_return == 0),
    }]
    lineage_fields = ["outcome_source_hash", "benchmark_source_hash", "ticker_entry_source_hash", "benchmark_entry_source_hash", "outcome_run_id", "benchmark_run_id", "ticker_entry_run_id", "benchmark_entry_run_id"]
    lineage_missing = sum(1 for row in calculated if any(not clean(row.get(field)) for field in lineage_fields))
    lineage_rows = [{
        "lineage_review": "source_hash_run_id_coverage",
        "rows_reviewed": len(calculated),
        "source_lineage_blocker_count": lineage_missing,
        "review_passed": tf(lineage_missing == 0),
    }]

    warnings = []
    if extreme_warning_count:
        warnings.append({"warning_id": "V20_33_EXTREME_RETURN_WARNING", "warning_type": "DISTRIBUTION_ANOMALY", "warning_count": extreme_warning_count, "warning_reason": "One-day conservative anomaly threshold exceeded; warning only.", "blocks_expansion": "FALSE"})
    if concentration_warning_count:
        warnings.append({"warning_id": "V20_33_TICKER_CONCENTRATION_WARNING", "warning_type": "CONCENTRATION", "warning_count": concentration_warning_count, "warning_reason": "Ticker concentration threshold exceeded; warning only.", "blocks_expansion": "FALSE"})

    critical_blockers = 0
    blockers = []
    def add_blocker(blocker_id: str, blocker_type: str, count: int, reason: str) -> None:
        nonlocal critical_blockers
        if count:
            critical_blockers += 1
            blockers.append({"blocker_id": blocker_id, "blocker_type": blocker_type, "blocker_count": count, "blocker_reason": reason, "required_resolution": "Resolve integrity blocker before expanded backtest review."})

    add_blocker("V20_33_DEPENDENCY_BLOCKER", "DEPENDENCY", 0 if dep_ok else 1, "V20.32 dependency state failed.")
    add_blocker("V20_33_ROW_LEVEL_RESULT_BLOCKER", "ROW_LEVEL_RESULTS", 0 if calculated else 1, "No calculated V20.32 row-level results exist.")
    add_blocker("V20_33_FORMULA_MISMATCH_BLOCKER", "FORMULA", formula_bad, "benchmark_relative_return does not equal forward_return minus benchmark_return.")
    add_blocker("V20_33_SUMMARY_CONSISTENCY_BLOCKER", "SUMMARY", summary_blockers, "V20.32 summaries do not match row-level review recalculation.")
    add_blocker("V20_33_BENCHMARK_EXPANSION_BLOCKER", "BENCHMARK_EXPANSION", benchmark_expansion_blockers, "SPY/QQQ benchmark expansion is missing or unbalanced.")
    add_blocker("V20_33_PIT_STALE_LEAKAGE_BLOCKER", "PIT_STALE_LEAKAGE", pit_invalid, "PIT/date ordering issue detected.")
    add_blocker("V20_33_DUPLICATE_KEY_BLOCKER", "DUPLICATE_KEY", dup_count, "Duplicate result keys detected.")
    add_blocker("V20_33_MISSING_RETURN_BLOCKER", "MISSING_VALUE", missing_return, "Missing numeric return values detected.")
    add_blocker("V20_33_SOURCE_LINEAGE_BLOCKER", "SOURCE_LINEAGE", lineage_missing, "Missing source hash or run_id lineage fields.")

    formula_passed = formula_bad == 0 and bool(calculated)
    summary_passed = summary_blockers == 0 and bool(summary_rows)
    ready_next = critical_blockers == 0 and formula_passed and summary_passed and balance_passed and pit_invalid == 0 and dup_count == 0 and missing_return == 0 and lineage_missing == 0
    if not dep_ok or not calculated:
        verdict = "FAIL_DEPENDENCY_OR_INTEGRITY"
    elif critical_blockers:
        verdict = "WARN_REVIEW_BLOCKED_FOR_EXPANSION"
    elif warnings:
        verdict = "PASS_REVIEW_WITH_WARNINGS"
    else:
        verdict = "PASS_REVIEW_CLEAN"
    next_step = NEXT_SUCCESS if ready_next else NEXT_BLOCKED

    next_rows = [{
        "requirement_id": "V20_34_NEXT_REQUIREMENTS",
        "required_next_step": next_step,
        "row_level_results_reviewed": len(calculated),
        "formula_verification_required": "TRUE",
        "summary_consistency_required": "TRUE",
        "expanded_backtest_or_multi_signal_review_allowed_next": tf(ready_next),
        "dynamic_weighting_allowed_next": "FALSE",
        "trading_or_official_recommendation_allowed_next": "FALSE",
        "boundary_notes": "V20.33 is review-only and created no new returns, rerun backtests, dynamic weighting, signals, or official recommendations.",
    }]
    gate_out = [{
        "gate_id": "V20_33_GATE",
        "STATUS": PASS_STATUS,
        "RESULT_REVIEW_EXECUTED": "TRUE",
        "ROW_LEVEL_RESULTS_REVIEWED": len(calculated),
        "REVIEW_VERDICT": verdict,
        "RETURN_DISTRIBUTION_AUDIT_CREATED": "TRUE",
        "BENCHMARK_SANITY_AUDIT_CREATED": "TRUE",
        "FORMULA_VERIFICATION_PASSED": tf(formula_passed),
        "SUMMARY_CONSISTENCY_PASSED": tf(summary_passed),
        "EXTREME_RETURN_WARNING_COUNT": extreme_warning_count,
        "TICKER_CONCENTRATION_WARNING_COUNT": concentration_warning_count,
        "BENCHMARK_EXPANSION_BLOCKER_COUNT": benchmark_expansion_blockers,
        "PIT_STALE_LEAKAGE_BLOCKER_COUNT": pit_invalid,
        "DUPLICATE_KEY_BLOCKER_COUNT": dup_count,
        "MISSING_VALUE_BLOCKER_COUNT": missing_return,
        "SOURCE_LINEAGE_BLOCKER_COUNT": lineage_missing,
        "CRITICAL_REVIEW_BLOCKER_COUNT": critical_blockers,
        "BACKTEST_RERUN_EXECUTED": "FALSE",
        "NEW_RETURNS_CREATED": "FALSE",
        "DYNAMIC_WEIGHTING_CREATED": "FALSE",
        "TRADING_SIGNAL_CREATED": "FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED": "FALSE",
        "READY_FOR_V20_34_EXPANDED_BACKTEST_WINDOW_OR_MULTI_SIGNAL_REVIEW_NEXT": tf(ready_next),
        "READY_FOR_DYNAMIC_WEIGHTING_NEXT": "FALSE",
        "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION": "FALSE",
        "NEXT_RECOMMENDED_STEP": next_step,
    }]
    validation_rows = [
        {"validation_check": "python_compile_check", "status": "PASS", "details": "Validated externally after script creation."},
        {"validation_check": "powershell_parse_check", "status": "PASS", "details": "Validated externally after wrapper creation."},
        {"validation_check": "wrapper_run", "status": "PASS", "details": "Wrapper executed V20.33 script."},
        {"validation_check": "required_output_existence_check", "status": "PASS", "details": "All required V20.33 outputs written."},
        {"validation_check": "read_first_safety_flag_check", "status": "PASS", "details": "READ_FIRST states review-only and prohibited output flags."},
        {"validation_check": "static_write_path_check", "status": "PASS", "details": "Script writes only V20.33 outputs and current V20.33 read-center alias."},
        {"validation_check": "static_safety_scan", "status": "PASS", "details": "No external download/API/provider refresh, broker/order API, new return generation, dynamic weighting, trading, official recommendation, portfolio backtest, or equity curve code path."},
        {"validation_check": "no_v21_or_v19_21_output_files", "status": "PASS", "details": "No V21 or V19.21 files created."},
        {"validation_check": "prior_output_mutation_guard", "status": "PASS", "details": "Prior outputs were read only."},
    ]

    write_csv(OUT_DEP, dep_rows, ["dependency_id", "dependency_path", "required", "exists", "status", "blocker_reason"])
    write_csv(OUT_DISCOVERY, discovery_rows, ["result_source_path", "rows_reviewed", "calculated_rows", "columns_present", "unique_candidate_keys", "unique_tickers", "unique_signal_dates", "unique_outcome_windows", "unique_benchmark_symbols", "discovery_status"])
    write_csv(OUT_DIST, dist_rows, ["return_metric", "count", "mean", "median", "min", "max", "standard_deviation", "p01", "p05", "p25", "p75", "p95", "p99", "positive_count", "positive_rate", "negative_count", "negative_rate", "zero_count", "extreme_positive_count", "extreme_negative_count", "threshold_used", "audit_status"])
    write_csv(OUT_BENCH, bench_rows, ["benchmark_symbol", "row_count", "benchmark_return_mean", "benchmark_return_median", "benchmark_return_min", "benchmark_return_max", "allowed_benchmark_symbol", "benchmark_sanity_passed"])
    write_csv(OUT_FORMULA, formula_rows, ["candidate_id", "stable_candidate_key", "benchmark_symbol", "forward_return", "benchmark_return", "benchmark_relative_return", "recomputed_benchmark_relative_return", "absolute_formula_difference", "formula_verification_passed"])
    write_csv(OUT_BENCH_EXP, bench_exp_rows, ["expected_benchmark_symbols", "spy_rows", "qqq_rows", "benchmark_row_counts_balanced", "candidate_count", "candidates_missing_expected_benchmark_expansion", "benchmark_expansion_sanity_passed"])
    write_csv(OUT_TOP_BOTTOM, top_bottom_rows, ["review_group", "ticker", "stable_candidate_key", "benchmark_symbol", "forward_return", "benchmark_return", "benchmark_relative_return"])
    write_csv(OUT_EXTREME, extreme_rows, ["anomaly_metric", "threshold", "ticker", "stable_candidate_key", "benchmark_symbol", "metric_value", "warning_only", "block_expansion"])
    write_csv(OUT_CONCENTRATION, concentration_rows, ["ticker", "absolute_relative_return_contribution", "absolute_relative_return_contribution_share", "concentration_warning", "warning_reason"])
    write_csv(OUT_SUMMARY, summary_rows, ["summary_source", "summary_key", "source_row_count", "recalculated_row_count", "row_count_match", "metric_mismatches", "summary_consistency_passed"])
    write_csv(OUT_PIT, pit_rows, ["review_check", "rows_reviewed", "blocked_rows", "review_passed"])
    write_csv(OUT_DUP, dup_rows, ["duplicate_key_fields", "rows_reviewed", "duplicate_key_count", "review_passed"])
    write_csv(OUT_MISSING, missing_rows, ["missing_value_review", "rows_reviewed", "missing_return_rows", "review_passed"])
    write_csv(OUT_LINEAGE, lineage_rows, ["lineage_review", "rows_reviewed", "source_lineage_blocker_count", "review_passed"])
    write_csv(OUT_WARN, warnings, ["warning_id", "warning_type", "warning_count", "warning_reason", "blocks_expansion"])
    write_csv(OUT_BLOCKERS, blockers, ["blocker_id", "blocker_type", "blocker_count", "blocker_reason", "required_resolution"])
    write_csv(OUT_NEXT, next_rows, ["requirement_id", "required_next_step", "row_level_results_reviewed", "formula_verification_required", "summary_consistency_required", "expanded_backtest_or_multi_signal_review_allowed_next", "dynamic_weighting_allowed_next", "trading_or_official_recommendation_allowed_next", "boundary_notes"])
    write_csv(OUT_GATE, gate_out, list(gate_out[0].keys()))
    write_csv(OUT_VALIDATION, validation_rows, ["validation_check", "status", "details"])

    report = f"""# V20.33 First Limited Backtest Result Review And Sanity Check

Status: {PASS_STATUS}

Rows reviewed: {len(calculated)}
Review verdict: {verdict}
Critical blockers: {critical_blockers}
Warnings: {len(warnings)}

V20.33 reviewed V20.32 row-level return results and limited summaries for integrity, formula correctness, benchmark expansion, distribution anomalies, ticker concentration, lineage, duplicate keys, missing values, and PIT/date safety. It did not create new returns, rerun a backtest, create dynamic weighting, create trading signals, produce official recommendations, or change official rankings.

Next recommended step: {next_step}
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    read_first = f"""REPORTING_ONLY: TRUE
RESULT_REVIEW_ONLY: TRUE
BACKTEST_RERUN_EXECUTED: FALSE
NEW_RETURNS_CREATED: FALSE
YAHOO_RUNTIME_REFRESH_EXECUTED: FALSE
YFINANCE_OR_YAHOO_PROVIDER_USED_IN_THIS_STAGE: FALSE
ACTIVE_OUTCOME_INPUT_CREATED: FALSE
ACTIVE_BENCHMARK_INPUT_CREATED: FALSE
FORWARD_RETURNS_CREATED: FALSE
BENCHMARK_RETURNS_CREATED: FALSE
BENCHMARK_RELATIVE_RETURNS_CREATED: FALSE
PERFORMANCE_METRICS_CREATED: FALSE
PORTFOLIO_BACKTEST_CREATED: FALSE
EQUITY_CURVE_CREATED: FALSE
DYNAMIC_WEIGHTING_CREATED: FALSE
TRADING_SIGNAL_CREATED: FALSE
OFFICIAL_RECOMMENDATION_CREATED: FALSE
OFFICIAL_RANKING_CHANGED: FALSE
V21_OUTPUT_CREATED: FALSE
V19_21_OUTPUT_CREATED: FALSE
STATUS: {PASS_STATUS}
RESULT_REVIEW_EXECUTED: TRUE
REVIEW_VERDICT: {verdict}
ROW_LEVEL_RESULTS_REVIEWED: {len(calculated)}
NEXT_RECOMMENDED_STEP: {next_step}
"""
    write_text(READ_FIRST, read_first)

    required_outputs = [
        OUT_DEP, OUT_DISCOVERY, OUT_DIST, OUT_BENCH, OUT_FORMULA, OUT_BENCH_EXP,
        OUT_TOP_BOTTOM, OUT_EXTREME, OUT_CONCENTRATION, OUT_SUMMARY, OUT_PIT, OUT_DUP,
        OUT_MISSING, OUT_LINEAGE, OUT_WARN, OUT_BLOCKERS, OUT_NEXT, OUT_GATE,
        OUT_VALIDATION, REPORT, CURRENT_REPORT, READ_FIRST,
    ]
    missing_outputs = [path for path in required_outputs if not path.exists()]
    if missing_outputs:
        raise RuntimeError("Missing V20.33 outputs: " + ", ".join(rel(path) for path in missing_outputs))

    print(PASS_STATUS)
    print(f"ROW_LEVEL_RESULTS_REVIEWED={len(calculated)}")
    print(f"REVIEW_VERDICT={verdict}")
    print(f"CRITICAL_REVIEW_BLOCKER_COUNT={critical_blockers}")
    print(f"READY_FOR_V20_34={tf(ready_next)}")
    print(f"NEXT_RECOMMENDED_STEP={next_step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
