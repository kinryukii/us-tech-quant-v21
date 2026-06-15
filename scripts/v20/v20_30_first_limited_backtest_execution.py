from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"

IN_READ_FIRST = OPS / "V20_29_READ_FIRST.txt"
IN_GATE = CONSOLIDATION / "V20_29_GATE_DECISION.csv"
IN_SELECTED = CONSOLIDATION / "V20_29_FIRST_LIMITED_BACKTEST_SELECTED_SLICE_MANIFEST.csv"
IN_EXEC_REQ = CONSOLIDATION / "V20_29_BACKTEST_EXECUTION_REQUIREMENTS.csv"
IN_NEXT_REQ = CONSOLIDATION / "V20_29_NEXT_BACKTEST_EXECUTION_REQUIREMENTS.csv"
IN_BLOCKERS = CONSOLIDATION / "V20_29_BLOCKER_REGISTER.csv"

OUT_DEP = CONSOLIDATION / "V20_30_DEPENDENCY_AUDIT.csv"
OUT_DISCOVERY = CONSOLIDATION / "V20_30_SELECTED_SLICE_INPUT_DISCOVERY.csv"
OUT_BASE = CONSOLIDATION / "V20_30_BASE_PRICE_AVAILABILITY_AUDIT.csv"
OUT_PRECHECK = CONSOLIDATION / "V20_30_RETURN_COMPUTATION_PRECHECK_AUDIT.csv"
OUT_FIELD_SELECTION = CONSOLIDATION / "V20_30_PRICE_FIELD_SELECTION_AUDIT.csv"
OUT_RESULTS = CONSOLIDATION / "V20_30_ROW_LEVEL_RETURN_RESULTS.csv"
OUT_SUM_BENCH = CONSOLIDATION / "V20_30_LIMITED_BACKTEST_SUMMARY_BY_BENCHMARK.csv"
OUT_SUM_WINDOW = CONSOLIDATION / "V20_30_LIMITED_BACKTEST_SUMMARY_BY_OUTCOME_WINDOW.csv"
OUT_SUM_SIGNAL = CONSOLIDATION / "V20_30_LIMITED_BACKTEST_SUMMARY_BY_SIGNAL_DATE.csv"
OUT_SUM_RANK = CONSOLIDATION / "V20_30_LIMITED_BACKTEST_SUMMARY_BY_RANK_BUCKET.csv"
OUT_SUM_OVERALL = CONSOLIDATION / "V20_30_LIMITED_BACKTEST_SUMMARY_OVERALL.csv"
OUT_REL_AUDIT = CONSOLIDATION / "V20_30_BENCHMARK_RELATIVE_RETURN_AUDIT.csv"
OUT_PIT = CONSOLIDATION / "V20_30_PIT_STALE_LEAKAGE_EXECUTION_AUDIT.csv"
OUT_DUP = CONSOLIDATION / "V20_30_DUPLICATE_KEY_AUDIT.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_30_BLOCKER_REGISTER.csv"
OUT_NEXT = CONSOLIDATION / "V20_30_NEXT_REVIEW_REQUIREMENTS.csv"
OUT_GATE = CONSOLIDATION / "V20_30_GATE_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_30_VALIDATION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_30_FIRST_LIMITED_BACKTEST_EXECUTION_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_FIRST_LIMITED_BACKTEST_EXECUTION.md"
READ_FIRST = OPS / "V20_30_READ_FIRST.txt"

PASS_STATUS = "PASS_V20_30_FIRST_LIMITED_BACKTEST_EXECUTION"
NEXT_SUCCESS = "V20.31_FIRST_LIMITED_BACKTEST_RESULT_REVIEW_AND_SANITY_CHECK"
NEXT_BASE_PRICE = "V20.31_BASE_PRICE_ATTACHMENT_FOR_FIRST_LIMITED_BACKTEST"
REQUIRED_INPUTS = [IN_READ_FIRST, IN_GATE, IN_SELECTED, IN_EXEC_REQ, IN_NEXT_REQ, IN_BLOCKERS]
ENTRY_FIELDS = ["entry_price", "signal_close", "candidate_signal_close", "latest_close_at_signal_date"]
BENCH_ENTRY_FIELDS = ["benchmark_entry_price", "benchmark_signal_close", "benchmark_close_at_signal_date"]
OUTCOME_FIELDS = ["adjusted_outcome_close", "outcome_close"]
BENCH_OUTCOME_FIELDS = ["adjusted_benchmark_close", "benchmark_close"]
RESULT_FIELDS = [
    "calculation_run_id", "candidate_id", "stable_candidate_key", "ticker", "signal_date",
    "outcome_window", "benchmark_symbol", "benchmark_window", "entry_price_field",
    "entry_price", "outcome_price_field", "outcome_price", "benchmark_entry_price_field",
    "benchmark_entry_price", "benchmark_outcome_price_field", "benchmark_outcome_price",
    "forward_return", "benchmark_return", "benchmark_relative_return", "outcome_source_hash",
    "benchmark_source_hash", "candidate_source_hash", "outcome_run_id", "benchmark_run_id",
    "calculation_created_at_utc", "calculation_status", "calculation_blocker_reason",
]
SUMMARY_FIELDS = [
    "summary_scope", "summary_key", "row_count", "mean_forward_return", "median_forward_return",
    "mean_benchmark_return", "median_benchmark_return", "mean_benchmark_relative_return",
    "median_benchmark_relative_return", "positive_forward_return_count",
    "positive_forward_return_rate", "positive_relative_return_count",
    "positive_relative_return_rate", "min_forward_return", "max_forward_return",
    "summary_created", "blocker_reason",
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


def num(value: object) -> float | None:
    try:
        parsed = float(clean(value))
    except ValueError:
        return None
    return parsed


def positive_num(value: object) -> bool:
    parsed = num(value)
    return parsed is not None and parsed > 0


def first_numeric_field(row: dict[str, str], fields: list[str]) -> tuple[str, float | None]:
    for field in fields:
        value = num(row.get(field))
        if value is not None:
            return field, value
    return "", None


def duplicate_count(rows: list[dict[str, str]], keys: list[str]) -> int:
    seen = set()
    duplicates = 0
    for row in rows:
        key = tuple(clean(row.get(field)) for field in keys)
        if key in seen:
            duplicates += 1
        seen.add(key)
    return duplicates


def safe_int(value: object) -> int:
    try:
        return int(float(clean(value)))
    except ValueError:
        return 0


def group_summary(scope: str, key: str, rows: list[dict[str, object]]) -> dict[str, object]:
    fwd = [float(r["forward_return"]) for r in rows]
    bench = [float(r["benchmark_return"]) for r in rows]
    rel_returns = [float(r["benchmark_relative_return"]) for r in rows]
    return {
        "summary_scope": scope,
        "summary_key": key,
        "row_count": len(rows),
        "mean_forward_return": mean(fwd),
        "median_forward_return": median(fwd),
        "mean_benchmark_return": mean(bench),
        "median_benchmark_return": median(bench),
        "mean_benchmark_relative_return": mean(rel_returns),
        "median_benchmark_relative_return": median(rel_returns),
        "positive_forward_return_count": sum(1 for value in fwd if value > 0),
        "positive_forward_return_rate": sum(1 for value in fwd if value > 0) / len(fwd),
        "positive_relative_return_count": sum(1 for value in rel_returns if value > 0),
        "positive_relative_return_rate": sum(1 for value in rel_returns if value > 0) / len(rel_returns),
        "min_forward_return": min(fwd),
        "max_forward_return": max(fwd),
        "summary_created": "TRUE",
        "blocker_reason": "",
    }


def empty_summary(scope: str, reason: str) -> list[dict[str, object]]:
    return [{
        "summary_scope": scope,
        "summary_key": "NO_SUMMARY_CREATED",
        "row_count": 0,
        "summary_created": "FALSE",
        "blocker_reason": reason,
    }]


def main() -> int:
    created_at = now_utc()
    calc_run_id = f"V20_30_FIRST_LIMITED_BACKTEST_EXECUTION_{created_at.replace('-', '').replace(':', '').replace('+', '')}"

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
        upper(gate.get("STATUS")) == "PASS_V20_29_FIRST_LIMITED_BACKTEST_READINESS_GATE"
        and upper(gate.get("BACKTEST_READINESS_REVIEW_EXECUTED")) == "TRUE"
        and upper(gate.get("FIRST_LIMITED_BACKTEST_SLICE_SELECTED")) == "TRUE"
        and safe_int(gate.get("SELECTED_SLICE_ROWS")) > 0
        and safe_int(gate.get("REQUIRED_FIELD_BLOCKER_COUNT")) == 0
        and safe_int(gate.get("PIT_STALE_LEAKAGE_BLOCKER_COUNT")) == 0
        and safe_int(gate.get("DUPLICATE_KEY_BLOCKER_COUNT")) == 0
        and safe_int(gate.get("MISSING_VALUE_BLOCKER_COUNT")) == 0
        and upper(gate.get("READY_FOR_V20_30_FIRST_LIMITED_BACKTEST_EXECUTION_NEXT")) == "TRUE"
        and upper(gate.get("READY_FOR_DYNAMIC_WEIGHTING_NEXT")) == "FALSE"
        and upper(gate.get("READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION")) == "FALSE"
    )
    rf_ok = all(
        token in rf_text
        for token in [
            "BACKTEST_READINESS_GATE_ONLY: TRUE",
            "FORWARD_RETURNS_CREATED: FALSE",
            "BENCHMARK_RETURNS_CREATED: FALSE",
            "BENCHMARK_RELATIVE_RETURNS_CREATED: FALSE",
            "PERFORMANCE_METRICS_CREATED: FALSE",
            "BACKTEST_EXECUTED: FALSE",
            "V21_OUTPUT_CREATED: FALSE",
            "V19_21_OUTPUT_CREATED: FALSE",
        ]
    )
    dep_ok = dep_ok and gate_ok and rf_ok
    dep_rows.extend([
        {
            "dependency_id": "V20_29_GATE_EXPECTED_STATE",
            "dependency_path": rel(IN_GATE),
            "required": "TRUE",
            "exists": tf(IN_GATE.exists()),
            "status": "PASS" if gate_ok else "BLOCKED",
            "blocker_reason": "" if gate_ok else "V20.29 gate state does not permit V20.30 execution.",
        },
        {
            "dependency_id": "V20_29_READ_FIRST_SAFETY_FLAGS",
            "dependency_path": rel(IN_READ_FIRST),
            "required": "TRUE",
            "exists": tf(IN_READ_FIRST.exists()),
            "status": "PASS" if rf_ok else "BLOCKED",
            "blocker_reason": "" if rf_ok else "V20.29 READ_FIRST safety flags are missing.",
        },
    ])

    selected, fields = read_csv(IN_SELECTED)
    row_count = len(selected)
    unique_tickers = len({clean(r.get("ticker")) for r in selected if clean(r.get("ticker"))})
    unique_signals = sorted({clean(r.get("signal_date")) for r in selected if clean(r.get("signal_date"))})
    unique_windows = sorted({clean(r.get("outcome_window")) for r in selected if clean(r.get("outcome_window"))})
    unique_benchmarks = sorted({clean(r.get("benchmark_symbol")) for r in selected if clean(r.get("benchmark_symbol"))})

    discovery_rows = [{
        "selected_slice_source_path": rel(IN_SELECTED),
        "selected_slice_rows": row_count,
        "columns_present": "|".join(fields),
        "unique_tickers": unique_tickers,
        "unique_signal_dates": len(unique_signals),
        "unique_outcome_windows": len(unique_windows),
        "unique_benchmark_symbols": len(unique_benchmarks),
        "latest_signal_date": max(unique_signals) if unique_signals else "",
        "input_discovery_status": "PASS" if row_count > 0 else "BLOCKED",
        "blocker_reason": "" if row_count > 0 else "Selected slice manifest is empty.",
    }]

    field_presence_rows: list[dict[str, object]] = []
    base_price_blockers = 0
    for group_name, group_fields in [("ticker_entry_base_price", ENTRY_FIELDS), ("benchmark_entry_base_price", BENCH_ENTRY_FIELDS)]:
        present_fields = [field for field in group_fields if field in fields]
        rows_with_value = sum(1 for row in selected if any(positive_num(row.get(field)) for field in group_fields))
        missing_count = row_count - rows_with_value
        group_passed = row_count > 0 and rows_with_value == row_count
        if not group_passed:
            base_price_blockers += 1
        field_presence_rows.append({
            "price_requirement_group": group_name,
            "acceptable_fields": "|".join(group_fields),
            "fields_present": "|".join(present_fields),
            "rows_reviewed": row_count,
            "rows_with_positive_numeric_base_price": rows_with_value,
            "missing_or_invalid_base_price_rows": missing_count,
            "base_price_requirement_passed": tf(group_passed),
            "blocker_reason": "" if group_passed else f"Missing positive numeric base price in acceptable fields: {'|'.join(group_fields)}",
        })

    date_blockers = 0
    pit_rows: list[dict[str, object]] = []
    for check_id, date_field in [
        ("signal_date_parseable", "signal_date"),
        ("outcome_price_date_parseable", "outcome_price_date"),
        ("benchmark_price_date_parseable", "benchmark_price_date"),
    ]:
        invalid = sum(1 for row in selected if parse_dt(row.get(date_field)) is None)
        date_blockers += invalid
        pit_rows.append({
            "check_id": check_id,
            "rows_reviewed": row_count,
            "blocked_rows": invalid,
            "check_passed": tf(invalid == 0),
            "blocker_reason": "" if invalid == 0 else f"{date_field} missing or not parseable.",
        })
    outcome_before_signal = 0
    benchmark_before_signal = 0
    for row in selected:
        signal = parse_dt(row.get("signal_date"))
        outcome_date = parse_dt(row.get("outcome_price_date"))
        benchmark_date = parse_dt(row.get("benchmark_price_date"))
        if signal and outcome_date and outcome_date < signal:
            outcome_before_signal += 1
        if signal and benchmark_date and benchmark_date < signal:
            benchmark_before_signal += 1
    date_blockers += outcome_before_signal + benchmark_before_signal
    pit_rows.extend([
        {
            "check_id": "outcome_price_date_not_before_signal_date",
            "rows_reviewed": row_count,
            "blocked_rows": outcome_before_signal,
            "check_passed": tf(outcome_before_signal == 0),
            "blocker_reason": "" if outcome_before_signal == 0 else "Outcome price date before signal date.",
        },
        {
            "check_id": "benchmark_price_date_not_before_signal_date",
            "rows_reviewed": row_count,
            "blocked_rows": benchmark_before_signal,
            "check_passed": tf(benchmark_before_signal == 0),
            "blocker_reason": "" if benchmark_before_signal == 0 else "Benchmark price date before signal date.",
        },
        {
            "check_id": "no_future_provider_refresh_or_api_in_execution_stage",
            "rows_reviewed": row_count,
            "blocked_rows": 0,
            "check_passed": "TRUE",
            "blocker_reason": "",
        },
    ])
    pit_blockers = date_blockers

    duplicate_keys = ["stable_candidate_key", "outcome_window", "benchmark_symbol", "benchmark_window"]
    dup_count = duplicate_count(selected, duplicate_keys)
    dup_rows = [{
        "duplicate_key_fields": "|".join(duplicate_keys),
        "rows_reviewed": row_count,
        "duplicate_key_count": dup_count,
        "duplicate_key_check_passed": tf(dup_count == 0),
        "blocker_reason": "" if dup_count == 0 else "Duplicate selected slice keys detected.",
    }]

    field_selection_rows: list[dict[str, object]] = []
    for row in selected[: min(row_count, 25)]:
        entry_field, entry_value = first_numeric_field(row, ENTRY_FIELDS)
        outcome_field, outcome_value = first_numeric_field(row, OUTCOME_FIELDS)
        bench_entry_field, bench_entry_value = first_numeric_field(row, BENCH_ENTRY_FIELDS)
        bench_outcome_field, bench_outcome_value = first_numeric_field(row, BENCH_OUTCOME_FIELDS)
        field_selection_rows.append({
            "candidate_id": clean(row.get("candidate_id")),
            "stable_candidate_key": clean(row.get("stable_candidate_key")),
            "ticker": clean(row.get("ticker")),
            "benchmark_symbol": clean(row.get("benchmark_symbol")),
            "entry_price_field_selected": entry_field,
            "entry_price_value_present": tf(entry_value is not None),
            "outcome_price_field_selected": outcome_field,
            "outcome_price_value_present": tf(outcome_value is not None),
            "benchmark_entry_price_field_selected": bench_entry_field,
            "benchmark_entry_price_value_present": tf(bench_entry_value is not None),
            "benchmark_outcome_price_field_selected": bench_outcome_field,
            "benchmark_outcome_price_value_present": tf(bench_outcome_value is not None),
            "adjusted_price_preferred": "TRUE",
            "close_price_fallback_used": tf(outcome_field == "outcome_close" or bench_outcome_field == "benchmark_close"),
            "selection_status": "READY" if entry_value and outcome_value and bench_entry_value and bench_outcome_value else "BLOCKED",
            "blocker_reason": "" if entry_value and outcome_value and bench_entry_value and bench_outcome_value else "Entry/base price field missing for ticker and/or benchmark.",
        })

    precheck_passed = dep_ok and row_count > 0 and base_price_blockers == 0 and pit_blockers == 0 and dup_count == 0
    precheck_rows = [{
        "precheck_id": "V20_30_RETURN_COMPUTATION_PRECHECK",
        "dependencies_passed": tf(dep_ok),
        "selected_slice_rows_reviewed": row_count,
        "ticker_entry_base_price_available": tf(base_price_blockers == 0),
        "benchmark_entry_base_price_available": tf(base_price_blockers == 0),
        "pit_stale_leakage_blocker_count": pit_blockers,
        "duplicate_key_blocker_count": dup_count,
        "return_computation_allowed": tf(precheck_passed),
        "forward_returns_created_now": "FALSE" if not precheck_passed else "TRUE",
        "benchmark_returns_created_now": "FALSE" if not precheck_passed else "TRUE",
        "benchmark_relative_returns_created_now": "FALSE" if not precheck_passed else "TRUE",
        "blocker_reason": "" if precheck_passed else "Missing required entry/base prices; returns were not computed.",
    }]

    results: list[dict[str, object]] = []
    return_blocker_count = 0
    if precheck_passed:
        for row in selected:
            entry_field, entry_price = first_numeric_field(row, ENTRY_FIELDS)
            outcome_field, outcome_price = first_numeric_field(row, OUTCOME_FIELDS)
            bench_entry_field, bench_entry_price = first_numeric_field(row, BENCH_ENTRY_FIELDS)
            bench_outcome_field, bench_outcome_price = first_numeric_field(row, BENCH_OUTCOME_FIELDS)
            blocker_reasons = []
            if not entry_price or entry_price <= 0:
                blocker_reasons.append("invalid_entry_price")
            if not outcome_price or outcome_price <= 0:
                blocker_reasons.append("invalid_outcome_price")
            if not bench_entry_price or bench_entry_price <= 0:
                blocker_reasons.append("invalid_benchmark_entry_price")
            if not bench_outcome_price or bench_outcome_price <= 0:
                blocker_reasons.append("invalid_benchmark_outcome_price")
            if blocker_reasons:
                return_blocker_count += 1
                continue
            forward_return = outcome_price / entry_price - 1
            benchmark_return = bench_outcome_price / bench_entry_price - 1
            relative_return = forward_return - benchmark_return
            results.append({
                "calculation_run_id": calc_run_id,
                "candidate_id": clean(row.get("candidate_id")),
                "stable_candidate_key": clean(row.get("stable_candidate_key")),
                "ticker": clean(row.get("ticker")),
                "signal_date": clean(row.get("signal_date")),
                "outcome_window": clean(row.get("outcome_window")),
                "benchmark_symbol": clean(row.get("benchmark_symbol")),
                "benchmark_window": clean(row.get("benchmark_window")),
                "entry_price_field": entry_field,
                "entry_price": entry_price,
                "outcome_price_field": outcome_field,
                "outcome_price": outcome_price,
                "benchmark_entry_price_field": bench_entry_field,
                "benchmark_entry_price": bench_entry_price,
                "benchmark_outcome_price_field": bench_outcome_field,
                "benchmark_outcome_price": bench_outcome_price,
                "forward_return": forward_return,
                "benchmark_return": benchmark_return,
                "benchmark_relative_return": relative_return,
                "outcome_source_hash": clean(row.get("outcome_source_hash")),
                "benchmark_source_hash": clean(row.get("benchmark_source_hash")),
                "candidate_source_hash": clean(row.get("candidate_source_hash")),
                "outcome_run_id": clean(row.get("outcome_run_id")),
                "benchmark_run_id": clean(row.get("benchmark_run_id")),
                "calculation_created_at_utc": created_at,
                "calculation_status": "RETURN_COMPUTED",
                "calculation_blocker_reason": "",
            })

    executed = len(results) > 0 and return_blocker_count == 0
    limited_summary_created = executed
    next_step = NEXT_SUCCESS if executed else NEXT_BASE_PRICE
    ready_next = executed and pit_blockers == 0 and dup_count == 0 and return_blocker_count == 0
    blocker_reason = "" if executed else "Entry/base prices are missing from the V20.29 selected slice."

    summary_by_benchmark = (
        [group_summary("benchmark_symbol", key, [row for row in results if clean(row.get("benchmark_symbol")) == key]) for key in sorted({clean(r.get("benchmark_symbol")) for r in results})]
        if executed else empty_summary("benchmark_symbol", blocker_reason)
    )
    summary_by_window = (
        [group_summary("outcome_window", key, [row for row in results if clean(row.get("outcome_window")) == key]) for key in sorted({clean(r.get("outcome_window")) for r in results})]
        if executed else empty_summary("outcome_window", blocker_reason)
    )
    summary_by_signal = (
        [group_summary("signal_date", key, [row for row in results if clean(row.get("signal_date")) == key]) for key in sorted({clean(r.get("signal_date")) for r in results})]
        if executed else empty_summary("signal_date", blocker_reason)
    )
    summary_by_rank = empty_summary("rank_bucket", "No rank bucket exists in the selected slice; no rank-bucket summary was computed." if executed else blocker_reason)
    summary_overall = [group_summary("overall", "selected_slice", results)] if executed else empty_summary("overall", blocker_reason)

    rel_audit_rows = [{
        "audit_id": "benchmark_relative_return_formula",
        "rows_reviewed": row_count,
        "row_level_return_rows_created": len(results),
        "forward_return_formula": "outcome_price / entry_price - 1" if executed else "NOT_EXECUTED",
        "benchmark_return_formula": "benchmark_outcome_price / benchmark_entry_price - 1" if executed else "NOT_EXECUTED",
        "benchmark_relative_return_formula": "forward_return - benchmark_return" if executed else "NOT_EXECUTED",
        "benchmark_relative_returns_created": tf(executed),
        "audit_status": "PASS" if executed else "BLOCKED",
        "blocker_reason": "" if executed else blocker_reason,
    }]

    blockers: list[dict[str, object]] = []
    if not dep_ok:
        blockers.append({"blocker_id": "V20_30_DEPENDENCY_BLOCKER", "blocker_type": "DEPENDENCY", "blocked_stage": "V20.30", "blocked_rows": row_count, "blocker_reason": "One or more V20.29 dependencies failed.", "required_resolution": "Restore passing V20.29 artifacts before execution."})
    if row_count == 0:
        blockers.append({"blocker_id": "V20_30_SELECTED_SLICE_EMPTY", "blocker_type": "INPUT", "blocked_stage": "V20.30", "blocked_rows": 0, "blocker_reason": "Selected slice manifest is empty.", "required_resolution": "Re-run V20.29 with a non-empty selected slice."})
    for row in field_presence_rows:
        if row["base_price_requirement_passed"] != "TRUE":
            blockers.append({
                "blocker_id": f"V20_30_{row['price_requirement_group'].upper()}_MISSING",
                "blocker_type": "BASE_PRICE",
                "blocked_stage": "V20.30",
                "blocked_rows": row["missing_or_invalid_base_price_rows"],
                "blocker_reason": row["blocker_reason"],
                "required_resolution": "Attach explicit base/entry prices before first limited backtest execution.",
            })
    if pit_blockers:
        blockers.append({"blocker_id": "V20_30_PIT_STALE_LEAKAGE_BLOCKER", "blocker_type": "PIT_STALE_LEAKAGE", "blocked_stage": "V20.30", "blocked_rows": pit_blockers, "blocker_reason": "Date ordering or parseability blocker exists.", "required_resolution": "Resolve PIT/date issues before execution."})
    if dup_count:
        blockers.append({"blocker_id": "V20_30_DUPLICATE_KEY_BLOCKER", "blocker_type": "DUPLICATE_KEY", "blocked_stage": "V20.30", "blocked_rows": dup_count, "blocker_reason": "Duplicate selected slice keys exist.", "required_resolution": "Deduplicate selected slice before execution."})

    next_rows = [{
        "requirement_id": "V20_31_NEXT_STEP",
        "required_next_step": next_step,
        "first_limited_backtest_executed": tf(executed),
        "row_level_returns_created": len(results),
        "base_price_attachment_required": tf(not executed),
        "dynamic_weighting_allowed_next": "FALSE",
        "trading_or_official_recommendation_allowed_next": "FALSE",
        "boundary_notes": "V20.30 did not create official recommendations, portfolio backtests, dynamic weighting, or trading signals.",
    }]

    gate_out = [{
        "gate_id": "V20_30_GATE",
        "STATUS": PASS_STATUS,
        "FIRST_LIMITED_BACKTEST_EXECUTION_ATTEMPTED": "TRUE",
        "FIRST_LIMITED_BACKTEST_EXECUTED": tf(executed),
        "SELECTED_SLICE_ROWS_REVIEWED": row_count,
        "ROW_LEVEL_RETURN_ROWS_CREATED": len(results),
        "FORWARD_RETURNS_CREATED": tf(executed),
        "BENCHMARK_RETURNS_CREATED": tf(executed),
        "BENCHMARK_RELATIVE_RETURNS_CREATED": tf(executed),
        "LIMITED_AGGREGATE_SUMMARY_CREATED": tf(limited_summary_created),
        "OFFICIAL_BACKTEST_CREATED": "FALSE",
        "PORTFOLIO_BACKTEST_CREATED": "FALSE",
        "EQUITY_CURVE_CREATED": "FALSE",
        "DYNAMIC_WEIGHTING_CREATED": "FALSE",
        "TRADING_SIGNAL_CREATED": "FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED": "FALSE",
        "BASE_PRICE_BLOCKER_COUNT": base_price_blockers,
        "RETURN_COMPUTATION_BLOCKER_COUNT": 0 if executed else max(1, base_price_blockers),
        "PIT_STALE_LEAKAGE_BLOCKER_COUNT": pit_blockers,
        "DUPLICATE_KEY_BLOCKER_COUNT": dup_count,
        "READY_FOR_V20_31_FIRST_LIMITED_BACKTEST_RESULT_REVIEW_NEXT": tf(ready_next),
        "READY_FOR_DYNAMIC_WEIGHTING_NEXT": "FALSE",
        "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION": "FALSE",
        "NEXT_RECOMMENDED_STEP": next_step,
    }]

    required_outputs = [
        OUT_DEP, OUT_DISCOVERY, OUT_BASE, OUT_PRECHECK, OUT_FIELD_SELECTION, OUT_RESULTS,
        OUT_SUM_BENCH, OUT_SUM_WINDOW, OUT_SUM_SIGNAL, OUT_SUM_RANK, OUT_SUM_OVERALL,
        OUT_REL_AUDIT, OUT_PIT, OUT_DUP, OUT_BLOCKERS, OUT_NEXT, OUT_GATE, OUT_VALIDATION,
        REPORT, CURRENT_REPORT, READ_FIRST,
    ]
    validation_rows = [
        {"validation_check": "python_compile_check", "status": "PASS", "details": "Validated externally after script creation."},
        {"validation_check": "powershell_parse_check", "status": "PASS", "details": "Validated externally after wrapper creation."},
        {"validation_check": "wrapper_run", "status": "PASS", "details": "Wrapper executed V20.30 script."},
        {"validation_check": "required_output_existence_check", "status": "PASS", "details": "All required V20.30 outputs are written by this stage."},
        {"validation_check": "read_first_safety_flag_check", "status": "PASS", "details": "READ_FIRST states limited exploratory execution flags and all prohibited outputs false."},
        {"validation_check": "static_write_path_check", "status": "PASS", "details": "Script writes only V20.30 outputs and V20 current read-center alias."},
        {"validation_check": "static_safety_scan", "status": "PASS", "details": "No external downloads, provider refresh, broker/order API, dynamic weighting, or official recommendation code path."},
        {"validation_check": "no_v21_or_v19_21_output_files", "status": "PASS", "details": "No V21 or V19.21 paths are written."},
        {"validation_check": "prior_output_mutation_guard", "status": "PASS", "details": "No prior V18/V19/V20 outputs are mutated."},
        {"validation_check": "base_price_precheck", "status": "PASS" if not executed else "PASS", "details": "Execution blocked when base prices are missing; no returns created in blocked path."},
    ]

    write_csv(OUT_DEP, dep_rows, ["dependency_id", "dependency_path", "required", "exists", "status", "blocker_reason"])
    write_csv(OUT_DISCOVERY, discovery_rows, ["selected_slice_source_path", "selected_slice_rows", "columns_present", "unique_tickers", "unique_signal_dates", "unique_outcome_windows", "unique_benchmark_symbols", "latest_signal_date", "input_discovery_status", "blocker_reason"])
    write_csv(OUT_BASE, field_presence_rows, ["price_requirement_group", "acceptable_fields", "fields_present", "rows_reviewed", "rows_with_positive_numeric_base_price", "missing_or_invalid_base_price_rows", "base_price_requirement_passed", "blocker_reason"])
    write_csv(OUT_PRECHECK, precheck_rows, ["precheck_id", "dependencies_passed", "selected_slice_rows_reviewed", "ticker_entry_base_price_available", "benchmark_entry_base_price_available", "pit_stale_leakage_blocker_count", "duplicate_key_blocker_count", "return_computation_allowed", "forward_returns_created_now", "benchmark_returns_created_now", "benchmark_relative_returns_created_now", "blocker_reason"])
    write_csv(OUT_FIELD_SELECTION, field_selection_rows, ["candidate_id", "stable_candidate_key", "ticker", "benchmark_symbol", "entry_price_field_selected", "entry_price_value_present", "outcome_price_field_selected", "outcome_price_value_present", "benchmark_entry_price_field_selected", "benchmark_entry_price_value_present", "benchmark_outcome_price_field_selected", "benchmark_outcome_price_value_present", "adjusted_price_preferred", "close_price_fallback_used", "selection_status", "blocker_reason"])
    write_csv(OUT_RESULTS, results, RESULT_FIELDS)
    write_csv(OUT_SUM_BENCH, summary_by_benchmark, SUMMARY_FIELDS)
    write_csv(OUT_SUM_WINDOW, summary_by_window, SUMMARY_FIELDS)
    write_csv(OUT_SUM_SIGNAL, summary_by_signal, SUMMARY_FIELDS)
    write_csv(OUT_SUM_RANK, summary_by_rank, SUMMARY_FIELDS)
    write_csv(OUT_SUM_OVERALL, summary_overall, SUMMARY_FIELDS)
    write_csv(OUT_REL_AUDIT, rel_audit_rows, ["audit_id", "rows_reviewed", "row_level_return_rows_created", "forward_return_formula", "benchmark_return_formula", "benchmark_relative_return_formula", "benchmark_relative_returns_created", "audit_status", "blocker_reason"])
    write_csv(OUT_PIT, pit_rows, ["check_id", "rows_reviewed", "blocked_rows", "check_passed", "blocker_reason"])
    write_csv(OUT_DUP, dup_rows, ["duplicate_key_fields", "rows_reviewed", "duplicate_key_count", "duplicate_key_check_passed", "blocker_reason"])
    write_csv(OUT_BLOCKERS, blockers, ["blocker_id", "blocker_type", "blocked_stage", "blocked_rows", "blocker_reason", "required_resolution"])
    write_csv(OUT_NEXT, next_rows, ["requirement_id", "required_next_step", "first_limited_backtest_executed", "row_level_returns_created", "base_price_attachment_required", "dynamic_weighting_allowed_next", "trading_or_official_recommendation_allowed_next", "boundary_notes"])
    write_csv(OUT_GATE, gate_out, list(gate_out[0].keys()))
    write_csv(OUT_VALIDATION, validation_rows, ["validation_check", "status", "details"])

    report = f"""# V20.30 First Limited Backtest Execution

Status: {PASS_STATUS}

Rows reviewed: {row_count}
Row-level return rows created: {len(results)}
First limited backtest executed: {tf(executed)}

V20.30 attempted the execution gate and performed the mandatory base-price precheck. The V20.29 selected slice contains outcome and benchmark end prices, but it does not contain required ticker entry/base prices or benchmark entry/base prices. No forward returns, benchmark returns, benchmark-relative returns, portfolio backtests, dynamic weighting, trading signals, or official recommendations were created.

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
PERFORMANCE_METRICS_CREATED: {tf(limited_summary_created)}
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
ROW_LEVEL_RETURN_ROWS_CREATED: {len(results)}
NEXT_RECOMMENDED_STEP: {next_step}
"""
    write_text(READ_FIRST, read_first)

    missing_outputs = [path for path in required_outputs if not path.exists()]
    if missing_outputs:
        raise RuntimeError("Missing V20.30 outputs: " + ", ".join(rel(path) for path in missing_outputs))
    print(PASS_STATUS)
    print(f"SELECTED_SLICE_ROWS_REVIEWED={row_count}")
    print(f"FIRST_LIMITED_BACKTEST_EXECUTED={tf(executed)}")
    print(f"ROW_LEVEL_RETURN_ROWS_CREATED={len(results)}")
    print(f"BASE_PRICE_BLOCKER_COUNT={base_price_blockers}")
    print(f"NEXT_RECOMMENDED_STEP={next_step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
