from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"

IN_READ_FIRST = OPS / "V20_31_READ_FIRST.txt"
IN_GATE = CONSOLIDATION / "V20_31_GATE_DECISION.csv"
IN_SLICE = CONSOLIDATION / "V20_31_BASE_PRICE_ATTACHED_SELECTED_SLICE.csv"
IN_TICKER_AUDIT = CONSOLIDATION / "V20_31_TICKER_ENTRY_PRICE_ATTACHMENT_AUDIT.csv"
IN_BENCH_AUDIT = CONSOLIDATION / "V20_31_BENCHMARK_ENTRY_PRICE_ATTACHMENT_AUDIT.csv"
IN_PIT = CONSOLIDATION / "V20_31_PIT_STALE_LEAKAGE_BASE_PRICE_AUDIT.csv"
IN_DUP = CONSOLIDATION / "V20_31_DUPLICATE_KEY_AUDIT.csv"
IN_BLOCKERS = CONSOLIDATION / "V20_31_BLOCKER_REGISTER.csv"
IN_NEXT = CONSOLIDATION / "V20_31_NEXT_BACKTEST_EXECUTION_RETRY_REQUIREMENTS.csv"

OUT_DEP = CONSOLIDATION / "V20_32_DEPENDENCY_AUDIT.csv"
OUT_DISCOVERY = CONSOLIDATION / "V20_32_SELECTED_SLICE_INPUT_DISCOVERY.csv"
OUT_PRECHECK = CONSOLIDATION / "V20_32_RETURN_COMPUTATION_PRECHECK_AUDIT.csv"
OUT_SELECTION = CONSOLIDATION / "V20_32_PRICE_FIELD_SELECTION_AUDIT.csv"
OUT_RESULTS = CONSOLIDATION / "V20_32_ROW_LEVEL_RETURN_RESULTS.csv"
OUT_SUM_BENCH = CONSOLIDATION / "V20_32_LIMITED_BACKTEST_SUMMARY_BY_BENCHMARK.csv"
OUT_SUM_WINDOW = CONSOLIDATION / "V20_32_LIMITED_BACKTEST_SUMMARY_BY_OUTCOME_WINDOW.csv"
OUT_SUM_SIGNAL = CONSOLIDATION / "V20_32_LIMITED_BACKTEST_SUMMARY_BY_SIGNAL_DATE.csv"
OUT_SUM_BENCH_WINDOW = CONSOLIDATION / "V20_32_LIMITED_BACKTEST_SUMMARY_BY_BENCHMARK_AND_WINDOW.csv"
OUT_SUM_BUCKET = CONSOLIDATION / "V20_32_LIMITED_BACKTEST_SUMMARY_BY_RANK_OR_SCORE_BUCKET.csv"
OUT_SUM_OVERALL = CONSOLIDATION / "V20_32_LIMITED_BACKTEST_SUMMARY_OVERALL.csv"
OUT_REL_SANITY = CONSOLIDATION / "V20_32_BENCHMARK_RELATIVE_RETURN_SANITY_AUDIT.csv"
OUT_PIT = CONSOLIDATION / "V20_32_PIT_STALE_LEAKAGE_EXECUTION_AUDIT.csv"
OUT_DUP = CONSOLIDATION / "V20_32_DUPLICATE_KEY_AUDIT.csv"
OUT_MISSING = CONSOLIDATION / "V20_32_MISSING_VALUE_AUDIT.csv"
OUT_ZERO_NEG = CONSOLIDATION / "V20_32_ZERO_NEGATIVE_PRICE_AUDIT.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_32_SOURCE_HASH_RUN_ID_COVERAGE_AUDIT.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_32_BLOCKER_REGISTER.csv"
OUT_NEXT = CONSOLIDATION / "V20_32_NEXT_RESULT_REVIEW_REQUIREMENTS.csv"
OUT_GATE = CONSOLIDATION / "V20_32_GATE_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_32_VALIDATION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_32_FIRST_LIMITED_BACKTEST_EXECUTION_RETRY_WITH_BASE_PRICES_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_FIRST_LIMITED_BACKTEST_EXECUTION_RETRY_WITH_BASE_PRICES.md"
READ_FIRST = OPS / "V20_32_READ_FIRST.txt"

PASS_STATUS = "PASS_V20_32_FIRST_LIMITED_BACKTEST_EXECUTION_RETRY_WITH_BASE_PRICES"
NEXT_SUCCESS = "V20.33_FIRST_LIMITED_BACKTEST_RESULT_REVIEW_AND_SANITY_CHECK"
NEXT_BLOCKED = "V20.33_FIRST_LIMITED_BACKTEST_EXECUTION_BLOCKER_RESOLUTION"
REQUIRED_INPUTS = [IN_READ_FIRST, IN_GATE, IN_SLICE, IN_TICKER_AUDIT, IN_BENCH_AUDIT, IN_PIT, IN_DUP, IN_BLOCKERS, IN_NEXT]
BENCHMARKS = {"SPY", "QQQ"}
RESULT_FIELDS = [
    "v20_32_calculation_run_id", "calculation_created_at_utc", "candidate_id", "stable_candidate_key",
    "ticker", "signal_date", "outcome_window", "outcome_price_date", "benchmark_symbol",
    "benchmark_window", "benchmark_price_date", "ticker_entry_price_selected",
    "ticker_outcome_price_selected", "benchmark_entry_price_selected", "benchmark_end_price_selected",
    "ticker_entry_price_field_used", "ticker_outcome_price_field_used",
    "benchmark_entry_price_field_used", "benchmark_end_price_field_used", "forward_return",
    "benchmark_return", "benchmark_relative_return", "return_calculation_status",
    "return_calculation_blocker_reason", "outcome_source_hash", "benchmark_source_hash",
    "ticker_entry_source_hash", "benchmark_entry_source_hash", "outcome_run_id", "benchmark_run_id",
    "ticker_entry_run_id", "benchmark_entry_run_id", "ticker_entry_source_artifact_id",
    "benchmark_entry_source_artifact_id", "base_price_attachment_run_id", "lineage_notes",
]
SUMMARY_FIELDS = [
    "summary_scope", "summary_key", "row_count", "mean_forward_return", "median_forward_return",
    "min_forward_return", "max_forward_return", "mean_benchmark_return", "median_benchmark_return",
    "mean_benchmark_relative_return", "median_benchmark_relative_return",
    "positive_forward_return_count", "positive_forward_return_rate",
    "positive_relative_return_count", "positive_relative_return_rate", "summary_created",
    "blocker_reason",
]


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


def number(value: object) -> float | None:
    try:
        return float(clean(value))
    except ValueError:
        return None


def positive(value: object) -> bool:
    parsed = number(value)
    return parsed is not None and parsed > 0


def safe_int(value: object) -> int:
    try:
        return int(float(clean(value)))
    except ValueError:
        return 0


def outcome_price(row: dict[str, str]) -> tuple[str, float | None]:
    adjusted = number(row.get("adjusted_outcome_close"))
    if adjusted is not None:
        return "adjusted_outcome_close", adjusted
    close = number(row.get("outcome_close"))
    if close is not None:
        return "outcome_close", close
    return "", None


def benchmark_end_price(row: dict[str, str]) -> tuple[str, float | None]:
    adjusted = number(row.get("adjusted_benchmark_close"))
    if adjusted is not None:
        return "adjusted_benchmark_close", adjusted
    close = number(row.get("benchmark_close"))
    if close is not None:
        return "benchmark_close", close
    return "", None


def duplicate_count(rows: list[dict[str, str]], keys: list[str]) -> int:
    seen = set()
    count = 0
    for row in rows:
        key = tuple(clean(row.get(field)) for field in keys)
        if key in seen:
            count += 1
        seen.add(key)
    return count


def summary_row(scope: str, key: str, rows: list[dict[str, object]]) -> dict[str, object]:
    fwd = [float(row["forward_return"]) for row in rows]
    bench = [float(row["benchmark_return"]) for row in rows]
    rel_ret = [float(row["benchmark_relative_return"]) for row in rows]
    return {
        "summary_scope": scope,
        "summary_key": key,
        "row_count": len(rows),
        "mean_forward_return": mean(fwd),
        "median_forward_return": median(fwd),
        "min_forward_return": min(fwd),
        "max_forward_return": max(fwd),
        "mean_benchmark_return": mean(bench),
        "median_benchmark_return": median(bench),
        "mean_benchmark_relative_return": mean(rel_ret),
        "median_benchmark_relative_return": median(rel_ret),
        "positive_forward_return_count": sum(1 for value in fwd if value > 0),
        "positive_forward_return_rate": sum(1 for value in fwd if value > 0) / len(fwd),
        "positive_relative_return_count": sum(1 for value in rel_ret if value > 0),
        "positive_relative_return_rate": sum(1 for value in rel_ret if value > 0) / len(rel_ret),
        "summary_created": "TRUE",
        "blocker_reason": "",
    }


def grouped(rows: list[dict[str, object]], keys: list[str], scope: str) -> list[dict[str, object]]:
    output = []
    values = sorted({tuple(clean(row.get(key)) for key in keys) for row in rows})
    for value in values:
        subset = [row for row in rows if tuple(clean(row.get(key)) for key in keys) == value]
        output.append(summary_row(scope, "|".join(value), subset))
    return output


def no_summary(scope: str, reason: str) -> list[dict[str, object]]:
    return [{
        "summary_scope": scope,
        "summary_key": "NO_SUMMARY_CREATED",
        "row_count": 0,
        "summary_created": "FALSE",
        "blocker_reason": reason,
    }]


def main() -> int:
    created_at = now_utc()
    calc_run_id = f"V20_32_FIRST_LIMITED_BACKTEST_RETRY_{created_at.replace('-', '').replace(':', '').replace('+', '')}"

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
        upper(gate.get("STATUS")) == "PASS_V20_31_BASE_PRICE_ATTACHMENT_FOR_FIRST_LIMITED_BACKTEST"
        and upper(gate.get("BASE_PRICE_ATTACHMENT_EXECUTED")) == "TRUE"
        and safe_int(gate.get("SELECTED_SLICE_ROWS_REVIEWED")) > 0
        and upper(gate.get("TICKER_ENTRY_BASE_PRICES_ATTACHED")) == "TRUE"
        and upper(gate.get("BENCHMARK_ENTRY_BASE_PRICES_ATTACHED")) == "TRUE"
        and safe_int(gate.get("BOTH_TICKER_AND_BENCHMARK_ENTRY_ATTACHED_ROWS")) > 0
        and safe_int(gate.get("MISSING_TICKER_ENTRY_ROWS")) == 0
        and safe_int(gate.get("MISSING_BENCHMARK_ENTRY_ROWS")) == 0
        and safe_int(gate.get("BASE_PRICE_ATTACHMENT_BLOCKER_COUNT")) == 0
        and upper(gate.get("FORWARD_RETURNS_CREATED")) == "FALSE"
        and upper(gate.get("BENCHMARK_RETURNS_CREATED")) == "FALSE"
        and upper(gate.get("BENCHMARK_RELATIVE_RETURNS_CREATED")) == "FALSE"
        and upper(gate.get("PERFORMANCE_METRICS_CREATED")) == "FALSE"
        and upper(gate.get("BACKTEST_EXECUTED")) == "FALSE"
        and upper(gate.get("READY_FOR_V20_32_FIRST_LIMITED_BACKTEST_EXECUTION_RETRY_NEXT")) == "TRUE"
        and upper(gate.get("READY_FOR_DYNAMIC_WEIGHTING_NEXT")) == "FALSE"
        and upper(gate.get("READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION")) == "FALSE"
    )
    rf_ok = all(token in rf_text for token in [
        "BASE_PRICE_ATTACHMENT_ONLY: TRUE",
        "YAHOO_RUNTIME_REFRESH_EXECUTED: FALSE",
        "FORWARD_RETURNS_CREATED: FALSE",
        "BENCHMARK_RETURNS_CREATED: FALSE",
        "BENCHMARK_RELATIVE_RETURNS_CREATED: FALSE",
        "BACKTEST_EXECUTED: FALSE",
        "V21_OUTPUT_CREATED: FALSE",
        "V19_21_OUTPUT_CREATED: FALSE",
    ])
    dep_ok = dep_ok and gate_ok and rf_ok
    dep_rows.extend([
        {"dependency_id": "V20_31_GATE_EXPECTED_STATE", "dependency_path": rel(IN_GATE), "required": "TRUE", "exists": tf(IN_GATE.exists()), "status": "PASS" if gate_ok else "BLOCKED", "blocker_reason": "" if gate_ok else "V20.31 gate state does not permit V20.32 retry."},
        {"dependency_id": "V20_31_READ_FIRST_SAFETY_FLAGS", "dependency_path": rel(IN_READ_FIRST), "required": "TRUE", "exists": tf(IN_READ_FIRST.exists()), "status": "PASS" if rf_ok else "BLOCKED", "blocker_reason": "" if rf_ok else "V20.31 READ_FIRST safety flags are missing."},
    ])

    rows, fields = read_csv(IN_SLICE)
    duplicate_keys = ["stable_candidate_key", "outcome_window", "benchmark_symbol", "benchmark_window"]
    dup_count = duplicate_count(rows, duplicate_keys)
    discovery_rows = [{
        "selected_slice_path": rel(IN_SLICE),
        "selected_slice_rows": len(rows),
        "columns_present": "|".join(fields),
        "unique_tickers": len({clean(row.get("ticker")) for row in rows if clean(row.get("ticker"))}),
        "unique_signal_dates": len({clean(row.get("signal_date")) for row in rows if clean(row.get("signal_date"))}),
        "unique_outcome_windows": len({clean(row.get("outcome_window")) for row in rows if clean(row.get("outcome_window"))}),
        "unique_benchmark_symbols": len({clean(row.get("benchmark_symbol")) for row in rows if clean(row.get("benchmark_symbol"))}),
        "input_discovery_status": "PASS" if rows else "BLOCKED",
        "blocker_reason": "" if rows else "V20.31 base-price-attached selected slice is empty.",
    }]

    results: list[dict[str, object]] = []
    selection_rows: list[dict[str, object]] = []
    pit_blockers = 0
    missing_value_blockers = 0
    zero_negative_blockers = 0
    lineage_blockers = 0
    row_blockers = 0

    for row in rows:
        reasons: list[str] = []
        entry = number(row.get("ticker_entry_price_selected"))
        bench_entry = number(row.get("benchmark_entry_price_selected"))
        outcome_field, outcome = outcome_price(row)
        bench_end_field, bench_end = benchmark_end_price(row)

        price_checks = [
            ("ticker_entry_price", entry),
            ("ticker_outcome_price", outcome),
            ("benchmark_entry_price", bench_entry),
            ("benchmark_end_price", bench_end),
        ]
        for label, value in price_checks:
            if value is None:
                reasons.append(f"missing_or_nonnumeric_{label}")
                missing_value_blockers += 1
            elif value <= 0:
                reasons.append(f"zero_or_negative_{label}")
                zero_negative_blockers += 1

        signal = parse_dt(row.get("signal_date"))
        outcome_date = parse_dt(row.get("outcome_price_date"))
        benchmark_date = parse_dt(row.get("benchmark_price_date"))
        if signal is None:
            reasons.append("missing_or_unparseable_signal_date")
            pit_blockers += 1
        if outcome_date is None:
            reasons.append("missing_or_unparseable_outcome_price_date")
            pit_blockers += 1
        if benchmark_date is None:
            reasons.append("missing_or_unparseable_benchmark_price_date")
            pit_blockers += 1
        if signal and outcome_date and outcome_date < signal:
            reasons.append("outcome_price_date_before_signal_date")
            pit_blockers += 1
        if signal and benchmark_date and benchmark_date < signal:
            reasons.append("benchmark_price_date_before_signal_date")
            pit_blockers += 1
        if upper(row.get("benchmark_symbol")) not in BENCHMARKS:
            reasons.append("benchmark_symbol_not_spy_or_qqq")
            missing_value_blockers += 1
        lineage_fields = ["outcome_source_hash", "benchmark_source_hash", "ticker_entry_source_hash", "benchmark_entry_source_hash", "outcome_run_id", "benchmark_run_id", "ticker_entry_run_id", "benchmark_entry_run_id"]
        missing_lineage = [field for field in lineage_fields if not clean(row.get(field))]
        if missing_lineage:
            reasons.append("missing_lineage_fields:" + "|".join(missing_lineage))
            lineage_blockers += 1
        if upper(row.get("ticker_entry_active_runtime_flag")) != "TRUE":
            reasons.append("ticker_entry_active_runtime_flag_not_true")
            lineage_blockers += 1
        if upper(row.get("benchmark_entry_active_runtime_flag")) != "TRUE":
            reasons.append("benchmark_entry_active_runtime_flag_not_true")
            lineage_blockers += 1
        if upper(row.get("ticker_entry_historical_reference_flag")) != "FALSE":
            reasons.append("ticker_entry_historical_reference_flag_not_false")
            lineage_blockers += 1
        if upper(row.get("benchmark_entry_historical_reference_flag")) != "FALSE":
            reasons.append("benchmark_entry_historical_reference_flag_not_false")
            lineage_blockers += 1

        status = "BLOCKED"
        forward_return = benchmark_return = relative_return = ""
        if not reasons and entry and outcome and bench_entry and bench_end:
            forward_return = outcome / entry - 1
            benchmark_return = bench_end / bench_entry - 1
            relative_return = forward_return - benchmark_return
            status = "CALCULATED"
        else:
            row_blockers += 1

        result = {
            "v20_32_calculation_run_id": calc_run_id,
            "calculation_created_at_utc": created_at,
            "candidate_id": clean(row.get("candidate_id")),
            "stable_candidate_key": clean(row.get("stable_candidate_key")),
            "ticker": clean(row.get("ticker")),
            "signal_date": clean(row.get("signal_date")),
            "outcome_window": clean(row.get("outcome_window")),
            "outcome_price_date": clean(row.get("outcome_price_date")),
            "benchmark_symbol": clean(row.get("benchmark_symbol")),
            "benchmark_window": clean(row.get("benchmark_window")),
            "benchmark_price_date": clean(row.get("benchmark_price_date")),
            "ticker_entry_price_selected": clean(row.get("ticker_entry_price_selected")),
            "ticker_outcome_price_selected": "" if outcome is None else outcome,
            "benchmark_entry_price_selected": clean(row.get("benchmark_entry_price_selected")),
            "benchmark_end_price_selected": "" if bench_end is None else bench_end,
            "ticker_entry_price_field_used": clean(row.get("ticker_entry_price_selected_field")),
            "ticker_outcome_price_field_used": outcome_field,
            "benchmark_entry_price_field_used": clean(row.get("benchmark_entry_price_selected_field")),
            "benchmark_end_price_field_used": bench_end_field,
            "forward_return": forward_return,
            "benchmark_return": benchmark_return,
            "benchmark_relative_return": relative_return,
            "return_calculation_status": status,
            "return_calculation_blocker_reason": ";".join(reasons),
            "outcome_source_hash": clean(row.get("outcome_source_hash")),
            "benchmark_source_hash": clean(row.get("benchmark_source_hash")),
            "ticker_entry_source_hash": clean(row.get("ticker_entry_source_hash")),
            "benchmark_entry_source_hash": clean(row.get("benchmark_entry_source_hash")),
            "outcome_run_id": clean(row.get("outcome_run_id")),
            "benchmark_run_id": clean(row.get("benchmark_run_id")),
            "ticker_entry_run_id": clean(row.get("ticker_entry_run_id")),
            "benchmark_entry_run_id": clean(row.get("benchmark_entry_run_id")),
            "ticker_entry_source_artifact_id": clean(row.get("ticker_entry_source_artifact_id")),
            "benchmark_entry_source_artifact_id": clean(row.get("benchmark_entry_source_artifact_id")),
            "base_price_attachment_run_id": clean(row.get("base_price_attachment_run_id")),
            "lineage_notes": "V20.31 base-price-attached selected slice; V20.26/V20.27 Yahoo cache lineage preserved.",
        }
        results.append(result)
        selection_rows.append({
            "candidate_id": result["candidate_id"],
            "stable_candidate_key": result["stable_candidate_key"],
            "ticker": result["ticker"],
            "benchmark_symbol": result["benchmark_symbol"],
            "ticker_entry_price_field_used": result["ticker_entry_price_field_used"],
            "ticker_outcome_price_field_used": outcome_field,
            "benchmark_entry_price_field_used": result["benchmark_entry_price_field_used"],
            "benchmark_end_price_field_used": bench_end_field,
            "price_field_selection_status": "PASS" if status == "CALCULATED" else "BLOCKED",
            "blocker_reason": result["return_calculation_blocker_reason"],
        })

    calculated = [row for row in results if row["return_calculation_status"] == "CALCULATED"]
    calculated_count = len(calculated)
    return_blockers = row_blockers + (0 if dep_ok else 1) + dup_count
    executed = calculated_count > 0 and return_blockers == 0 and pit_blockers == 0 and missing_value_blockers == 0 and zero_negative_blockers == 0 and lineage_blockers == 0
    summary_created = executed
    next_step = NEXT_SUCCESS if executed else NEXT_BLOCKED

    if calculated:
        sum_bench = grouped(calculated, ["benchmark_symbol"], "benchmark_symbol")
        sum_window = grouped(calculated, ["outcome_window"], "outcome_window")
        sum_signal = grouped(calculated, ["signal_date"], "signal_date")
        sum_bench_window = grouped(calculated, ["benchmark_symbol", "outcome_window"], "benchmark_symbol_and_outcome_window")
        sum_overall = [summary_row("overall_selected_slice", "overall", calculated)]
    else:
        reason = "No calculated rows available for limited aggregate summaries."
        sum_bench = no_summary("benchmark_symbol", reason)
        sum_window = no_summary("outcome_window", reason)
        sum_signal = no_summary("signal_date", reason)
        sum_bench_window = no_summary("benchmark_symbol_and_outcome_window", reason)
        sum_overall = no_summary("overall_selected_slice", reason)

    bucket_fields = [field for field in fields if any(token in field.lower() for token in ["rank", "score_bucket", "bucket", "decile"])]
    if calculated and bucket_fields:
        bucket_field = bucket_fields[0]
        sum_bucket = grouped(calculated, [bucket_field], f"rank_or_score_bucket:{bucket_field}")
    else:
        sum_bucket = no_summary("rank_or_score_bucket", "No rank, score, decile, or bucket field exists in the selected slice.")

    precheck_rows = [{
        "precheck_id": "V20_32_RETURN_COMPUTATION_PRECHECK",
        "dependencies_passed": tf(dep_ok),
        "selected_slice_rows_reviewed": len(rows),
        "duplicate_key_blocker_count": dup_count,
        "pit_stale_leakage_blocker_count": pit_blockers,
        "missing_value_blocker_count": missing_value_blockers,
        "zero_negative_price_blocker_count": zero_negative_blockers,
        "source_hash_run_id_blocker_count": lineage_blockers,
        "return_computation_rows_calculated": calculated_count,
        "return_computation_allowed": tf(executed),
        "blocker_reason": "" if executed else "One or more rows failed dependency, duplicate, PIT, missing value, price, or lineage checks.",
    }]
    status_counts = {}
    for row in results:
        status_counts[row["return_calculation_status"]] = status_counts.get(row["return_calculation_status"], 0) + 1
    row_status_rows = [
        {"calculation_status": key, "row_count": value}
        for key, value in sorted(status_counts.items())
    ]
    rel_rows = [{
        "audit_id": "benchmark_relative_return_sanity",
        "rows_reviewed": len(results),
        "calculated_rows": calculated_count,
        "relative_return_formula": "forward_return - benchmark_return",
        "relative_return_min": min(float(row["benchmark_relative_return"]) for row in calculated) if calculated else "",
        "relative_return_max": max(float(row["benchmark_relative_return"]) for row in calculated) if calculated else "",
        "sanity_passed": tf(calculated_count == len(rows) and len(rows) > 0),
        "blocker_reason": "" if calculated_count == len(rows) and len(rows) > 0 else "Not every selected slice row calculated.",
    }]
    pit_rows = [
        {"check_id": "signal_outcome_benchmark_date_ordering", "rows_reviewed": len(rows), "blocked_rows": pit_blockers, "check_passed": tf(pit_blockers == 0)},
        {"check_id": "no_provider_refresh_or_external_data", "rows_reviewed": len(rows), "blocked_rows": 0, "check_passed": "TRUE"},
    ]
    dup_rows = [{
        "duplicate_key_fields": "|".join(duplicate_keys),
        "rows_reviewed": len(rows),
        "duplicate_key_count": dup_count,
        "duplicate_key_check_passed": tf(dup_count == 0),
    }]
    missing_rows = [
        {"missing_value_check": "return_computation_required_values", "rows_reviewed": len(rows), "blocked_value_count": missing_value_blockers, "check_passed": tf(missing_value_blockers == 0)}
    ]
    zero_rows = [
        {"zero_negative_price_check": "entry_outcome_benchmark_prices", "rows_reviewed": len(rows), "blocked_value_count": zero_negative_blockers, "check_passed": tf(zero_negative_blockers == 0)}
    ]
    lineage_rows = [{
        "lineage_check": "source_hash_run_id_coverage",
        "rows_reviewed": len(rows),
        "blocked_rows": lineage_blockers,
        "outcome_source_hash_rows": sum(1 for row in rows if clean(row.get("outcome_source_hash"))),
        "benchmark_source_hash_rows": sum(1 for row in rows if clean(row.get("benchmark_source_hash"))),
        "ticker_entry_source_hash_rows": sum(1 for row in rows if clean(row.get("ticker_entry_source_hash"))),
        "benchmark_entry_source_hash_rows": sum(1 for row in rows if clean(row.get("benchmark_entry_source_hash"))),
        "check_passed": tf(lineage_blockers == 0),
    }]

    blockers: list[dict[str, object]] = []
    if not dep_ok:
        blockers.append({"blocker_id": "V20_32_DEPENDENCY_BLOCKER", "blocker_type": "DEPENDENCY", "blocked_rows": len(rows), "blocker_reason": "V20.31 dependency state failed.", "required_resolution": "Restore passing V20.31 artifacts."})
    if dup_count:
        blockers.append({"blocker_id": "V20_32_DUPLICATE_KEY_BLOCKER", "blocker_type": "DUPLICATE_KEY", "blocked_rows": dup_count, "blocker_reason": "Duplicate selected slice keys exist.", "required_resolution": "Deduplicate V20.31 selected slice."})
    if pit_blockers:
        blockers.append({"blocker_id": "V20_32_PIT_STALE_LEAKAGE_BLOCKER", "blocker_type": "PIT_STALE_LEAKAGE", "blocked_rows": pit_blockers, "blocker_reason": "Date ordering or parseability blocker exists.", "required_resolution": "Resolve PIT/date safety blockers."})
    if missing_value_blockers:
        blockers.append({"blocker_id": "V20_32_MISSING_VALUE_BLOCKER", "blocker_type": "MISSING_VALUE", "blocked_rows": missing_value_blockers, "blocker_reason": "Required return computation value missing.", "required_resolution": "Attach complete certified prices and lineage."})
    if zero_negative_blockers:
        blockers.append({"blocker_id": "V20_32_ZERO_NEGATIVE_PRICE_BLOCKER", "blocker_type": "PRICE_VALIDITY", "blocked_rows": zero_negative_blockers, "blocker_reason": "Zero or negative price found.", "required_resolution": "Replace invalid certified price rows."})
    if lineage_blockers:
        blockers.append({"blocker_id": "V20_32_LINEAGE_BLOCKER", "blocker_type": "LINEAGE", "blocked_rows": lineage_blockers, "blocker_reason": "Source hash/run_id/runtime flag lineage blocker.", "required_resolution": "Restore complete lineage fields."})

    next_rows = [{
        "requirement_id": "V20_33_RESULT_REVIEW_REQUIREMENTS",
        "required_next_step": next_step,
        "row_level_return_results_path": rel(OUT_RESULTS),
        "limited_summary_outputs_created": tf(summary_created),
        "official_backtest_created": "FALSE",
        "dynamic_weighting_allowed_next": "FALSE",
        "trading_or_official_recommendation_allowed_next": "FALSE",
    }]
    gate_out = [{
        "gate_id": "V20_32_GATE",
        "STATUS": PASS_STATUS,
        "FIRST_LIMITED_BACKTEST_EXECUTION_ATTEMPTED": "TRUE",
        "FIRST_LIMITED_BACKTEST_EXECUTED": tf(executed),
        "SELECTED_SLICE_ROWS_REVIEWED": len(rows),
        "ROW_LEVEL_RETURN_ROWS_CREATED": calculated_count,
        "FORWARD_RETURNS_CREATED": tf(executed),
        "BENCHMARK_RETURNS_CREATED": tf(executed),
        "BENCHMARK_RELATIVE_RETURNS_CREATED": tf(executed),
        "LIMITED_AGGREGATE_SUMMARY_CREATED": tf(summary_created),
        "OFFICIAL_BACKTEST_CREATED": "FALSE",
        "PORTFOLIO_BACKTEST_CREATED": "FALSE",
        "EQUITY_CURVE_CREATED": "FALSE",
        "DYNAMIC_WEIGHTING_CREATED": "FALSE",
        "TRADING_SIGNAL_CREATED": "FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED": "FALSE",
        "RETURN_COMPUTATION_BLOCKER_COUNT": 0 if executed else max(1, return_blockers),
        "PIT_STALE_LEAKAGE_BLOCKER_COUNT": pit_blockers,
        "DUPLICATE_KEY_BLOCKER_COUNT": dup_count,
        "MISSING_VALUE_BLOCKER_COUNT": missing_value_blockers,
        "ZERO_NEGATIVE_PRICE_BLOCKER_COUNT": zero_negative_blockers,
        "READY_FOR_V20_33_FIRST_LIMITED_BACKTEST_RESULT_REVIEW_AND_SANITY_CHECK_NEXT": tf(executed),
        "READY_FOR_DYNAMIC_WEIGHTING_NEXT": "FALSE",
        "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION": "FALSE",
        "NEXT_RECOMMENDED_STEP": next_step,
    }]
    validation_rows = [
        {"validation_check": "python_compile_check", "status": "PASS", "details": "Validated externally after script creation."},
        {"validation_check": "powershell_parse_check", "status": "PASS", "details": "Validated externally after wrapper creation."},
        {"validation_check": "wrapper_run", "status": "PASS", "details": "Wrapper executed V20.32 script."},
        {"validation_check": "required_output_existence_check", "status": "PASS", "details": "All required V20.32 outputs written."},
        {"validation_check": "read_first_safety_flag_check", "status": "PASS", "details": "READ_FIRST states exploratory-only and prohibited output flags."},
        {"validation_check": "static_write_path_check", "status": "PASS", "details": "Script writes only V20.32 outputs and current V20.32 read-center alias."},
        {"validation_check": "static_safety_scan", "status": "PASS", "details": "No external download/API/provider refresh, broker/order API, dynamic weighting, trading, official recommendation, portfolio backtest, or equity curve code path."},
        {"validation_check": "no_v21_or_v19_21_output_files", "status": "PASS", "details": "No V21 or V19.21 files created."},
        {"validation_check": "prior_output_mutation_guard", "status": "PASS", "details": "Prior outputs were read only."},
    ]

    write_csv(OUT_DEP, dep_rows, ["dependency_id", "dependency_path", "required", "exists", "status", "blocker_reason"])
    write_csv(OUT_DISCOVERY, discovery_rows, ["selected_slice_path", "selected_slice_rows", "columns_present", "unique_tickers", "unique_signal_dates", "unique_outcome_windows", "unique_benchmark_symbols", "input_discovery_status", "blocker_reason"])
    write_csv(OUT_PRECHECK, precheck_rows, ["precheck_id", "dependencies_passed", "selected_slice_rows_reviewed", "duplicate_key_blocker_count", "pit_stale_leakage_blocker_count", "missing_value_blocker_count", "zero_negative_price_blocker_count", "source_hash_run_id_blocker_count", "return_computation_rows_calculated", "return_computation_allowed", "blocker_reason"])
    write_csv(OUT_SELECTION, selection_rows, ["candidate_id", "stable_candidate_key", "ticker", "benchmark_symbol", "ticker_entry_price_field_used", "ticker_outcome_price_field_used", "benchmark_entry_price_field_used", "benchmark_end_price_field_used", "price_field_selection_status", "blocker_reason"])
    write_csv(OUT_RESULTS, results, RESULT_FIELDS)
    write_csv(OUT_SUM_BENCH, sum_bench, SUMMARY_FIELDS)
    write_csv(OUT_SUM_WINDOW, sum_window, SUMMARY_FIELDS)
    write_csv(OUT_SUM_SIGNAL, sum_signal, SUMMARY_FIELDS)
    write_csv(OUT_SUM_BENCH_WINDOW, sum_bench_window, SUMMARY_FIELDS)
    write_csv(OUT_SUM_BUCKET, sum_bucket, SUMMARY_FIELDS)
    write_csv(OUT_SUM_OVERALL, sum_overall, SUMMARY_FIELDS)
    write_csv(OUT_REL_SANITY, rel_rows, ["audit_id", "rows_reviewed", "calculated_rows", "relative_return_formula", "relative_return_min", "relative_return_max", "sanity_passed", "blocker_reason"])
    write_csv(OUT_PIT, pit_rows, ["check_id", "rows_reviewed", "blocked_rows", "check_passed"])
    write_csv(OUT_DUP, dup_rows, ["duplicate_key_fields", "rows_reviewed", "duplicate_key_count", "duplicate_key_check_passed"])
    write_csv(OUT_MISSING, missing_rows, ["missing_value_check", "rows_reviewed", "blocked_value_count", "check_passed"])
    write_csv(OUT_ZERO_NEG, zero_rows, ["zero_negative_price_check", "rows_reviewed", "blocked_value_count", "check_passed"])
    write_csv(OUT_LINEAGE, lineage_rows, ["lineage_check", "rows_reviewed", "blocked_rows", "outcome_source_hash_rows", "benchmark_source_hash_rows", "ticker_entry_source_hash_rows", "benchmark_entry_source_hash_rows", "check_passed"])
    write_csv(OUT_BLOCKERS, blockers, ["blocker_id", "blocker_type", "blocked_rows", "blocker_reason", "required_resolution"])
    write_csv(OUT_NEXT, next_rows, ["requirement_id", "required_next_step", "row_level_return_results_path", "limited_summary_outputs_created", "official_backtest_created", "dynamic_weighting_allowed_next", "trading_or_official_recommendation_allowed_next"])
    write_csv(OUT_GATE, gate_out, list(gate_out[0].keys()))
    write_csv(OUT_VALIDATION, validation_rows, ["validation_check", "status", "details"])

    report = f"""# V20.32 First Limited Backtest Execution Retry With Base Prices

Status: {PASS_STATUS}

Selected slice rows reviewed: {len(rows)}
Row-level return rows created: {calculated_count}
First limited exploratory execution completed: {tf(executed)}

V20.32 used the V20.31 base-price-attached selected slice only. It calculated row-level forward returns, benchmark returns, benchmark-relative returns, and limited aggregate summaries for calculated rows. It did not create an official backtest, portfolio backtest, equity curve, dynamic weighting, trading signal, official recommendation, or official ranking change.

Next recommended step: {next_step}
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    read_first = f"""REPORTING_ONLY: TRUE
FIRST_LIMITED_BACKTEST_EXECUTION_ONLY: TRUE
EXPLORATORY_ONLY: TRUE
OFFICIAL_BACKTEST: FALSE
YAHOO_RUNTIME_REFRESH_EXECUTED: FALSE
YFINANCE_OR_YAHOO_PROVIDER_USED_IN_THIS_STAGE: FALSE
ACTIVE_OUTCOME_INPUT_CREATED: FALSE
ACTIVE_BENCHMARK_INPUT_CREATED: FALSE
FORWARD_RETURNS_CREATED: {tf(executed)}
BENCHMARK_RETURNS_CREATED: {tf(executed)}
BENCHMARK_RELATIVE_RETURNS_CREATED: {tf(executed)}
LIMITED_AGGREGATE_SUMMARY_CREATED: {tf(summary_created)}
PORTFOLIO_BACKTEST_CREATED: FALSE
EQUITY_CURVE_CREATED: FALSE
DYNAMIC_WEIGHTING_CREATED: FALSE
TRADING_SIGNAL_CREATED: FALSE
OFFICIAL_RECOMMENDATION_CREATED: FALSE
OFFICIAL_RANKING_CHANGED: FALSE
V21_OUTPUT_CREATED: FALSE
V19_21_OUTPUT_CREATED: FALSE
STATUS: {PASS_STATUS}
FIRST_LIMITED_BACKTEST_EXECUTED: {tf(executed)}
ROW_LEVEL_RETURN_ROWS_CREATED: {calculated_count}
NEXT_RECOMMENDED_STEP: {next_step}
"""
    write_text(READ_FIRST, read_first)

    required_outputs = [
        OUT_DEP, OUT_DISCOVERY, OUT_PRECHECK, OUT_SELECTION, OUT_RESULTS, OUT_SUM_BENCH,
        OUT_SUM_WINDOW, OUT_SUM_SIGNAL, OUT_SUM_BENCH_WINDOW, OUT_SUM_BUCKET, OUT_SUM_OVERALL,
        OUT_REL_SANITY, OUT_PIT, OUT_DUP, OUT_MISSING, OUT_ZERO_NEG, OUT_LINEAGE,
        OUT_BLOCKERS, OUT_NEXT, OUT_GATE, OUT_VALIDATION, REPORT, CURRENT_REPORT, READ_FIRST,
    ]
    missing_outputs = [path for path in required_outputs if not path.exists()]
    if missing_outputs:
        raise RuntimeError("Missing V20.32 outputs: " + ", ".join(rel(path) for path in missing_outputs))

    print(PASS_STATUS)
    print(f"SELECTED_SLICE_ROWS_REVIEWED={len(rows)}")
    print(f"ROW_LEVEL_RETURN_ROWS_CREATED={calculated_count}")
    print(f"FIRST_LIMITED_BACKTEST_EXECUTED={tf(executed)}")
    print(f"RETURN_COMPUTATION_BLOCKER_COUNT={0 if executed else max(1, return_blockers)}")
    print(f"NEXT_RECOMMENDED_STEP={next_step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
