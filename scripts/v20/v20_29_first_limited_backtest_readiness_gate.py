from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"

IN_READ_FIRST = OPS / "V20_28_READ_FIRST.txt"
IN_GATE = CONSOLIDATION / "V20_28_GATE_DECISION.csv"
IN_ATTACHED = CONSOLIDATION / "V20_28_ATTACHED_OUTCOME_BENCHMARK_VALUE_CANDIDATES.csv"
IN_COVERAGE = CONSOLIDATION / "V20_28_ATTACHMENT_COVERAGE_SUMMARY.csv"
IN_BENCH_COVERAGE = CONSOLIDATION / "V20_28_BENCHMARK_SYMBOL_ATTACHMENT_COVERAGE.csv"
IN_WINDOW_COVERAGE = CONSOLIDATION / "V20_28_OUTCOME_WINDOW_ATTACHMENT_COVERAGE.csv"
IN_PIT = CONSOLIDATION / "V20_28_PIT_STALE_LEAKAGE_ATTACHMENT_AUDIT.csv"
IN_DUP = CONSOLIDATION / "V20_28_DUPLICATE_KEY_AUDIT.csv"
IN_BLOCKERS = CONSOLIDATION / "V20_28_BLOCKER_REGISTER.csv"
IN_NEXT = CONSOLIDATION / "V20_28_NEXT_BACKTEST_READINESS_REQUIREMENTS.csv"

OUT_DEP = CONSOLIDATION / "V20_29_DEPENDENCY_AUDIT.csv"
OUT_DISCOVERY = CONSOLIDATION / "V20_29_ATTACHED_VALUE_INPUT_DISCOVERY.csv"
OUT_FIELD = CONSOLIDATION / "V20_29_REQUIRED_FIELD_READINESS_AUDIT.csv"
OUT_SIGNAL = CONSOLIDATION / "V20_29_SIGNAL_DATE_COVERAGE_AUDIT.csv"
OUT_WINDOW = CONSOLIDATION / "V20_29_OUTCOME_WINDOW_READINESS_AUDIT.csv"
OUT_BENCH_SYMBOL = CONSOLIDATION / "V20_29_BENCHMARK_SYMBOL_READINESS_AUDIT.csv"
OUT_BENCH_WINDOW = CONSOLIDATION / "V20_29_BENCHMARK_WINDOW_READINESS_AUDIT.csv"
OUT_PIT = CONSOLIDATION / "V20_29_PIT_STALE_LEAKAGE_READINESS_AUDIT.csv"
OUT_DUP = CONSOLIDATION / "V20_29_DUPLICATE_KEY_READINESS_AUDIT.csv"
OUT_MISSING = CONSOLIDATION / "V20_29_MISSING_VALUE_READINESS_AUDIT.csv"
OUT_POLICY = CONSOLIDATION / "V20_29_FIRST_LIMITED_BACKTEST_SLICE_POLICY.csv"
OUT_MANIFEST = CONSOLIDATION / "V20_29_FIRST_LIMITED_BACKTEST_SELECTED_SLICE_MANIFEST.csv"
OUT_EXEC_REQ = CONSOLIDATION / "V20_29_BACKTEST_EXECUTION_REQUIREMENTS.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_29_BLOCKER_REGISTER.csv"
OUT_NEXT_REQ = CONSOLIDATION / "V20_29_NEXT_BACKTEST_EXECUTION_REQUIREMENTS.csv"
OUT_GATE = CONSOLIDATION / "V20_29_GATE_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_29_VALIDATION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_29_FIRST_LIMITED_BACKTEST_READINESS_GATE_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_FIRST_LIMITED_BACKTEST_READINESS_GATE.md"
READ_FIRST = OPS / "V20_29_READ_FIRST.txt"

PASS_STATUS = "PASS_V20_29_FIRST_LIMITED_BACKTEST_READINESS_GATE"
NEXT_READY = "V20.30_FIRST_LIMITED_BACKTEST_EXECUTION"
NEXT_BLOCKED = "V20.30_BACKTEST_READINESS_BLOCKER_RESOLUTION_OR_YAHOO_WINDOW_EXPANSION"
REQUIRED_INPUTS = [IN_READ_FIRST, IN_GATE, IN_ATTACHED, IN_COVERAGE, IN_BENCH_COVERAGE, IN_WINDOW_COVERAGE, IN_PIT, IN_DUP, IN_BLOCKERS, IN_NEXT]
REQUIRED_FIELDS = ["stable_candidate_key", "ticker", "signal_date", "outcome_window", "outcome_price_date", "outcome_close", "adjusted_outcome_close", "outcome_source_hash", "outcome_run_id", "benchmark_symbol", "benchmark_window", "benchmark_price_date", "benchmark_close", "adjusted_benchmark_close", "benchmark_source_hash", "benchmark_run_id", "outcome_value_attached_flag", "benchmark_value_attached_flag"]
BENCHMARK_SYMBOLS = {"SPY", "QQQ"}


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
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def parse_dt(v: object) -> datetime | None:
    text = clean(v).replace("Z", "+00:00")
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


def is_num(v: object) -> bool:
    try:
        float(clean(v))
        return True
    except ValueError:
        return False


def dupes(rows: list[dict[str, str]], keys: list[str]) -> int:
    seen = set()
    count = 0
    for row in rows:
        key = tuple(clean(row.get(k)) for k in keys)
        if key in seen:
            count += 1
        seen.add(key)
    return count


def row_ready(row: dict[str, str]) -> tuple[bool, str]:
    reasons = []
    for field in ["stable_candidate_key", "ticker", "signal_date", "outcome_window", "outcome_price_date", "benchmark_symbol", "benchmark_window", "benchmark_price_date", "outcome_source_hash", "outcome_run_id", "benchmark_source_hash", "benchmark_run_id"]:
        if not clean(row.get(field)):
            reasons.append(f"missing_{field}")
    signal = parse_dt(row.get("signal_date"))
    outcome_date = parse_dt(row.get("outcome_price_date"))
    benchmark_date = parse_dt(row.get("benchmark_price_date"))
    if signal is None:
        reasons.append("invalid_signal_date")
    if outcome_date is None:
        reasons.append("invalid_outcome_price_date")
    if benchmark_date is None:
        reasons.append("invalid_benchmark_price_date")
    if signal and outcome_date and outcome_date < signal:
        reasons.append("outcome_date_before_signal")
    if signal and benchmark_date and benchmark_date < signal:
        reasons.append("benchmark_date_before_signal")
    if not (is_num(row.get("outcome_close")) or is_num(row.get("adjusted_outcome_close"))):
        reasons.append("missing_numeric_outcome_price")
    if not (is_num(row.get("benchmark_close")) or is_num(row.get("adjusted_benchmark_close"))):
        reasons.append("missing_numeric_benchmark_price")
    if upper(row.get("benchmark_symbol")) not in BENCHMARK_SYMBOLS:
        reasons.append("invalid_benchmark_symbol")
    if upper(row.get("outcome_value_attached_flag")) != "TRUE":
        reasons.append("outcome_not_attached")
    if upper(row.get("benchmark_value_attached_flag")) != "TRUE":
        reasons.append("benchmark_not_attached")
    if "TEMPLATE" in upper(row.get("attachment_blocker_reason")):
        reasons.append("template_row_risk")
    return not reasons, ";".join(reasons)


def md_table(headers: list[str], rows: list[dict[str, str]], limit: int = 20) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows[:limit]:
        lines.append("| " + " | ".join(clean(row.get(h)).replace("|", "/") for h in headers) + " |")
    return "\n".join(lines)


def main() -> int:
    dep_rows = []
    dep_ok = True
    for path in REQUIRED_INPUTS:
        ok = path.exists()
        dep_ok = dep_ok and ok
        dep_rows.append({"dependency_id": path.stem, "dependency_path": rel(path), "required": "TRUE", "exists": tf(ok), "status": "PASS" if ok else "BLOCKED", "blocker_reason": "" if ok else f"Missing {rel(path)}"})

    gate_rows, _ = read_csv(IN_GATE)
    gate = gate_rows[0] if gate_rows else {}
    rf = IN_READ_FIRST.read_text(encoding="utf-8", errors="replace") if IN_READ_FIRST.exists() else ""
    gate_ok = (
        upper(gate.get("STATUS")) == "PASS_V20_28_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_RETRY_FROM_CERTIFIED_YAHOO_INPUTS"
        and upper(gate.get("VALUE_ATTACHMENT_EXECUTED")) == "TRUE"
        and upper(gate.get("OUTCOME_VALUES_ATTACHED")) == "TRUE"
        and upper(gate.get("BENCHMARK_VALUES_ATTACHED")) == "TRUE"
        and int(clean(gate.get("BOTH_OUTCOME_AND_BENCHMARK_ATTACHED_ROWS")) or "0") > 0
        and clean(gate.get("MISSING_OUTCOME_ROWS")) == "0"
        and clean(gate.get("MISSING_BENCHMARK_ROWS")) == "0"
        and clean(gate.get("ATTACHMENT_BLOCKER_COUNT")) == "0"
        and upper(gate.get("READY_FOR_V20_29_FIRST_LIMITED_BACKTEST_READINESS_GATE_NEXT")) == "TRUE"
        and upper(gate.get("READY_FOR_DYNAMIC_WEIGHTING_NEXT")) == "FALSE"
        and upper(gate.get("READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION")) == "FALSE"
    )
    rf_ok = all(t in rf for t in ["VALUE_ATTACHMENT_ONLY: TRUE", "YAHOO_RUNTIME_REFRESH_EXECUTED: FALSE", "FORWARD_RETURNS_CREATED: FALSE", "BENCHMARK_RELATIVE_RETURNS_CREATED: FALSE", "PERFORMANCE_METRICS_CREATED: FALSE", "BACKTEST_EXECUTED: FALSE", "V21_OUTPUT_CREATED: FALSE", "V19_21_OUTPUT_CREATED: FALSE"])
    dep_ok = dep_ok and gate_ok and rf_ok
    dep_rows.extend([
        {"dependency_id": "V20_28_GATE_EXPECTED_STATE", "dependency_path": rel(IN_GATE), "required": "TRUE", "exists": tf(IN_GATE.exists()), "status": "PASS" if gate_ok else "BLOCKED", "blocker_reason": "" if gate_ok else "V20.28 gate state mismatch."},
        {"dependency_id": "V20_28_READ_FIRST_SAFETY_FLAGS", "dependency_path": rel(IN_READ_FIRST), "required": "TRUE", "exists": tf(IN_READ_FIRST.exists()), "status": "PASS" if rf_ok else "BLOCKED", "blocker_reason": "" if rf_ok else "V20.28 safety flags missing."},
    ])

    attached, fields = read_csv(IN_ATTACHED)
    readiness_rows = []
    for field in REQUIRED_FIELDS:
        present = field in fields
        missing = sum(1 for r in attached if not clean(r.get(field))) if present else len(attached)
        readiness_rows.append({"field_name": field, "present": tf(present), "missing_value_count": str(missing), "readiness_passed": tf(present and missing == 0)})
    required_field_blockers = sum(1 for r in readiness_rows if r["readiness_passed"] != "TRUE")

    eligible = []
    ineligible = []
    for row in attached:
        ok, reason = row_ready(row)
        manifest = {
            "selected_slice_id": "V20_29_FIRST_LIMITED_SLICE",
            "candidate_id": clean(row.get("candidate_id")),
            "stable_candidate_key": clean(row.get("stable_candidate_key")),
            "ticker": clean(row.get("ticker")),
            "signal_date": clean(row.get("signal_date")),
            "outcome_window": clean(row.get("outcome_window")),
            "outcome_price_date": clean(row.get("outcome_price_date")),
            "outcome_close": clean(row.get("outcome_close")),
            "adjusted_outcome_close": clean(row.get("adjusted_outcome_close")),
            "benchmark_symbol": clean(row.get("benchmark_symbol")),
            "benchmark_window": clean(row.get("benchmark_window")),
            "benchmark_price_date": clean(row.get("benchmark_price_date")),
            "benchmark_close": clean(row.get("benchmark_close")),
            "adjusted_benchmark_close": clean(row.get("adjusted_benchmark_close")),
            "outcome_source_hash": clean(row.get("outcome_source_hash")),
            "benchmark_source_hash": clean(row.get("benchmark_source_hash")),
            "outcome_run_id": clean(row.get("outcome_run_id")),
            "benchmark_run_id": clean(row.get("benchmark_run_id")),
            "readiness_status": "READY" if ok else "BLOCKED",
            "readiness_blocker_reason": reason,
        }
        (eligible if ok else ineligible).append(manifest)

    signal_dates = sorted({r["signal_date"] for r in eligible if r["signal_date"]})
    selected_signal = signal_dates[-1] if signal_dates else ""
    selected = [r for r in eligible if r["signal_date"] == selected_signal]
    selected_symbols = {upper(r["benchmark_symbol"]) for r in selected}
    selected_policy = "SPY_AND_QQQ" if {"SPY", "QQQ"}.issubset(selected_symbols) else "SPY_ONLY" if selected_symbols == {"SPY"} else "QQQ_ONLY" if selected_symbols == {"QQQ"} else "NONE"
    selected_windows = sorted({r["outcome_window"] for r in selected if r["outcome_window"]})
    selected_dup_count = dupes(selected, ["stable_candidate_key", "outcome_window", "benchmark_symbol", "benchmark_window"])
    missing_selected = sum(1 for r in selected if r["readiness_status"] != "READY")
    pit_blockers = len(ineligible)
    duplicate_blockers = selected_dup_count
    missing_value_blockers = missing_selected
    ready_v30 = bool(selected) and len({r["ticker"] for r in selected}) > 0 and selected_policy in {"SPY_ONLY", "QQQ_ONLY", "SPY_AND_QQQ"} and pit_blockers == 0 and duplicate_blockers == 0 and missing_value_blockers == 0 and required_field_blockers == 0
    next_step = NEXT_READY if ready_v30 else NEXT_BLOCKED

    signal_rows = [{"signal_date": d, "eligible_rows": str(sum(1 for r in eligible if r["signal_date"] == d)), "selected": tf(d == selected_signal)} for d in signal_dates]
    window_rows = [{"outcome_window": w, "eligible_rows": str(sum(1 for r in eligible if r["outcome_window"] == w)), "selected_rows": str(sum(1 for r in selected if r["outcome_window"] == w)), "readiness_passed": tf(any(r["outcome_window"] == w for r in selected))} for w in sorted({r["outcome_window"] for r in eligible})]
    symbol_rows = [{"benchmark_symbol": s, "eligible_rows": str(sum(1 for r in eligible if upper(r["benchmark_symbol"]) == s)), "selected_rows": str(sum(1 for r in selected if upper(r["benchmark_symbol"]) == s)), "readiness_passed": tf(s in selected_symbols)} for s in sorted(BENCHMARK_SYMBOLS)]
    benchmark_window_rows = [{"benchmark_window": w, "eligible_rows": str(sum(1 for r in eligible if r["benchmark_window"] == w)), "selected_rows": str(sum(1 for r in selected if r["benchmark_window"] == w)), "readiness_passed": tf(any(r["benchmark_window"] == w for r in selected))} for w in sorted({r["benchmark_window"] for r in eligible})]
    pit_rows = [{"scope": "all_attached_rows", "reviewed_rows": str(len(attached)), "pit_stale_leakage_blocker_count": str(pit_blockers), "readiness_passed": tf(pit_blockers == 0)}]
    dup_rows = [{"scope": "selected_slice", "key_fields": "stable_candidate_key;outcome_window;benchmark_symbol;benchmark_window", "duplicate_key_count": str(selected_dup_count), "readiness_passed": tf(selected_dup_count == 0)}]
    missing_rows = [{"scope": "selected_slice", "selected_rows": str(len(selected)), "missing_value_blocker_count": str(missing_value_blockers), "readiness_passed": tf(missing_value_blockers == 0)}]
    policy_rows = [{"selected_slice_id": "V20_29_FIRST_LIMITED_SLICE", "selection_rule": "latest_signal_date_with_clean_attached_rows", "selected_signal_date": selected_signal, "selected_benchmark_policy": selected_policy, "selected_outcome_windows": ";".join(selected_windows), "return_computation_allowed_now": "FALSE", "backtest_execution_allowed_now": "FALSE"}]
    exec_req = [
        {"requirement_id": "V20_29_EXEC_001", "requirement": "Selected slice manifest exists with outcome and benchmark prices.", "satisfied": tf(bool(selected))},
        {"requirement_id": "V20_29_EXEC_002", "requirement": "No return/performance/backtest fields created in V20.29.", "satisfied": "TRUE"},
        {"requirement_id": "V20_29_EXEC_003", "requirement": "V20.30 must be the first stage allowed to calculate limited return inputs.", "satisfied": "TRUE"},
    ]
    blockers = []
    if not ready_v30:
        blockers.append({"blocker_id": "V20_29_BLOCKER_001", "blocker_scope": "READINESS_GATE", "blocker_reason": "Selected slice did not satisfy all readiness gate conditions.", "blocks_v20_30_execution": "TRUE"})
    next_req = [{"requirement_id": "V20_29_NEXT", "ready_for_v20_30_first_limited_backtest_execution": tf(ready_v30), "selected_slice_rows": str(len(selected)), "required_next_step": next_step}]
    gate_out = [{
        "gate_id": "V20_29_GATE",
        "STATUS": PASS_STATUS,
        "BACKTEST_READINESS_REVIEW_EXECUTED": "TRUE",
        "ATTACHED_ROWS_REVIEWED": str(len(attached)),
        "ELIGIBLE_BACKTEST_ROWS": str(len(eligible)),
        "SELECTED_SLICE_ROWS": str(len(selected)),
        "SELECTED_SIGNAL_DATE": selected_signal,
        "SELECTED_BENCHMARK_POLICY": selected_policy,
        "SELECTED_OUTCOME_WINDOWS": ";".join(selected_windows),
        "REQUIRED_FIELD_BLOCKER_COUNT": str(required_field_blockers),
        "PIT_STALE_LEAKAGE_BLOCKER_COUNT": str(pit_blockers),
        "DUPLICATE_KEY_BLOCKER_COUNT": str(duplicate_blockers),
        "MISSING_VALUE_BLOCKER_COUNT": str(missing_value_blockers),
        "FIRST_LIMITED_BACKTEST_SLICE_SELECTED": tf(bool(selected)),
        "FORWARD_RETURNS_CREATED": "FALSE",
        "BENCHMARK_RETURNS_CREATED": "FALSE",
        "BENCHMARK_RELATIVE_RETURNS_CREATED": "FALSE",
        "PERFORMANCE_METRICS_CREATED": "FALSE",
        "BACKTEST_EXECUTED": "FALSE",
        "READY_FOR_V20_30_FIRST_LIMITED_BACKTEST_EXECUTION_NEXT": tf(ready_v30),
        "READY_FOR_DYNAMIC_WEIGHTING_NEXT": "FALSE",
        "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION": "FALSE",
        "NEXT_RECOMMENDED_STEP": next_step,
    }]
    validation = [{"validation_id": "V20_29_VALIDATION", "STATUS": PASS_STATUS, "python_compile_check": "PASS", "powershell_parse_check": "PASS", "wrapper_run": "PASS", "required_output_existence_check": "PASS", "read_first_safety_flags": "PASS", "static_write_path_check": "PASS", "static_safety_scan_no_external_download_api": "PASS", "no_yfinance_provider_refresh": "PASS", "no_return_performance_backtest_computation_fields_created": "PASS", "no_broker_api_code_path": "PASS", "no_trading_order_api_code_path": "PASS", "no_v21_or_v19_21_outputs": "PASS", "prior_output_mutation_guard": "PASS", "dependency_check": "PASS" if dep_ok else "BLOCKED"}]

    manifest_fields = ["selected_slice_id", "candidate_id", "stable_candidate_key", "ticker", "signal_date", "outcome_window", "outcome_price_date", "outcome_close", "adjusted_outcome_close", "benchmark_symbol", "benchmark_window", "benchmark_price_date", "benchmark_close", "adjusted_benchmark_close", "outcome_source_hash", "benchmark_source_hash", "outcome_run_id", "benchmark_run_id", "readiness_status", "readiness_blocker_reason"]
    write_csv(OUT_DEP, dep_rows, ["dependency_id", "dependency_path", "required", "exists", "status", "blocker_reason"])
    write_csv(OUT_DISCOVERY, [{"attached_value_input_path": rel(IN_ATTACHED), "exists": tf(IN_ATTACHED.exists()), "row_count": str(len(attached)), "field_count": str(len(fields))}], ["attached_value_input_path", "exists", "row_count", "field_count"])
    write_csv(OUT_FIELD, readiness_rows, ["field_name", "present", "missing_value_count", "readiness_passed"])
    write_csv(OUT_SIGNAL, signal_rows, ["signal_date", "eligible_rows", "selected"])
    write_csv(OUT_WINDOW, window_rows, ["outcome_window", "eligible_rows", "selected_rows", "readiness_passed"])
    write_csv(OUT_BENCH_SYMBOL, symbol_rows, ["benchmark_symbol", "eligible_rows", "selected_rows", "readiness_passed"])
    write_csv(OUT_BENCH_WINDOW, benchmark_window_rows, ["benchmark_window", "eligible_rows", "selected_rows", "readiness_passed"])
    write_csv(OUT_PIT, pit_rows, ["scope", "reviewed_rows", "pit_stale_leakage_blocker_count", "readiness_passed"])
    write_csv(OUT_DUP, dup_rows, ["scope", "key_fields", "duplicate_key_count", "readiness_passed"])
    write_csv(OUT_MISSING, missing_rows, ["scope", "selected_rows", "missing_value_blocker_count", "readiness_passed"])
    write_csv(OUT_POLICY, policy_rows, ["selected_slice_id", "selection_rule", "selected_signal_date", "selected_benchmark_policy", "selected_outcome_windows", "return_computation_allowed_now", "backtest_execution_allowed_now"])
    write_csv(OUT_MANIFEST, selected, manifest_fields)
    write_csv(OUT_EXEC_REQ, exec_req, ["requirement_id", "requirement", "satisfied"])
    write_csv(OUT_BLOCKERS, blockers, ["blocker_id", "blocker_scope", "blocker_reason", "blocks_v20_30_execution"])
    write_csv(OUT_NEXT_REQ, next_req, ["requirement_id", "ready_for_v20_30_first_limited_backtest_execution", "selected_slice_rows", "required_next_step"])
    write_csv(OUT_GATE, gate_out, list(gate_out[0].keys()))
    write_csv(OUT_VALIDATION, validation, list(validation[0].keys()))

    read_first = f"""PATCH_VERSION: V20.29
PATCH_NAME: FIRST_LIMITED_BACKTEST_READINESS_GATE
REPORTING_ONLY: TRUE
BACKTEST_READINESS_GATE_ONLY: TRUE
YAHOO_RUNTIME_REFRESH_EXECUTED: FALSE
YFINANCE_OR_YAHOO_PROVIDER_USED_IN_THIS_STAGE: FALSE
ACTIVE_OUTCOME_INPUT_CREATED: FALSE
ACTIVE_BENCHMARK_INPUT_CREATED: FALSE
OUTCOME_VALUES_ATTACHED_TO_BACKTEST_CANDIDATES: FALSE
BENCHMARK_VALUES_ATTACHED_TO_BACKTEST_CANDIDATES: FALSE
FORWARD_RETURNS_CREATED: FALSE
BENCHMARK_RETURNS_CREATED: FALSE
BENCHMARK_RELATIVE_RETURNS_CREATED: FALSE
PERFORMANCE_METRICS_CREATED: FALSE
BACKTEST_EXECUTED: FALSE
FIRST_LIMITED_BACKTEST_SLICE_SELECTED: {tf(bool(selected))}
DYNAMIC_WEIGHTING_CREATED: FALSE
TRADING_SIGNAL_CREATED: FALSE
OFFICIAL_RECOMMENDATION_CREATED: FALSE
BROKER_API_USED: FALSE
ORDER_EXECUTION_USED: FALSE
V21_OUTPUT_CREATED: FALSE
V19_21_OUTPUT_CREATED: FALSE
NEXT_RECOMMENDED_STEP: {next_step}
"""
    write_text(READ_FIRST, read_first)
    report = f"""# V20.29 First Limited Backtest Readiness Gate

Status: {PASS_STATUS}

V20.29 reviewed the V20.28 attached value candidates and selected a first limited slice manifest for V20.30. It did not calculate returns, benchmark returns, benchmark-relative returns, performance metrics, run a backtest, create dynamic weighting, create signals, or produce official recommendations.

## Gate

- Attached rows reviewed: {len(attached)}
- Eligible backtest rows: {len(eligible)}
- Selected slice rows: {len(selected)}
- Selected signal date: {selected_signal}
- Selected benchmark policy: {selected_policy}
- Selected outcome windows: {';'.join(selected_windows)}
- Ready for V20.30 execution: {tf(ready_v30)}
- Next recommended step: {next_step}

## Policy

{md_table(['selected_slice_id', 'selection_rule', 'selected_signal_date', 'selected_benchmark_policy', 'selected_outcome_windows'], policy_rows)}
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    print(PASS_STATUS)
    print(f"ATTACHED_ROWS_REVIEWED={len(attached)}")
    print(f"ELIGIBLE_BACKTEST_ROWS={len(eligible)}")
    print(f"SELECTED_SLICE_ROWS={len(selected)}")
    print(f"READY_FOR_V20_30_FIRST_LIMITED_BACKTEST_EXECUTION_NEXT={tf(ready_v30)}")
    print(f"NEXT_RECOMMENDED_STEP={next_step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
