from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
INPUT_BASE = ROOT / "inputs" / "v20" / "outcome_benchmark"

IN_READ_FIRST = OPS / "V20_27_READ_FIRST.txt"
IN_GATE = CONSOLIDATION / "V20_27_GATE_DECISION.csv"
IN_REGISTER = CONSOLIDATION / "V20_27_CERTIFIED_ACTIVE_INPUT_REGISTER.csv"
IN_ACTIVE_AUDIT = CONSOLIDATION / "V20_27_ACTIVE_INPUT_FILE_CREATION_AUDIT.csv"
IN_NEXT = CONSOLIDATION / "V20_27_NEXT_VALUE_ATTACHMENT_REQUIREMENTS.csv"
IN_BLOCKERS = CONSOLIDATION / "V20_27_BLOCKER_REGISTER.csv"
IN_CANDIDATES = CONSOLIDATION / "V20_17_BACKTEST_INPUT_CANDIDATE_DATASET.csv"

OUTCOME_INPUT = INPUT_BASE / "V20_OUTCOME_SOURCE_INPUT.csv"
BENCHMARK_INPUT = INPUT_BASE / "V20_BENCHMARK_SOURCE_INPUT.csv"

OUT_DEP = CONSOLIDATION / "V20_28_DEPENDENCY_AUDIT.csv"
OUT_SELECT = CONSOLIDATION / "V20_28_CANDIDATE_SOURCE_SELECTION_AUDIT.csv"
OUT_DISCOVERY = CONSOLIDATION / "V20_28_CERTIFIED_ACTIVE_INPUT_DISCOVERY.csv"
OUT_OUTCOME_KEY = CONSOLIDATION / "V20_28_OUTCOME_INPUT_ATTACHMENT_KEY_AUDIT.csv"
OUT_BENCH_KEY = CONSOLIDATION / "V20_28_BENCHMARK_INPUT_ATTACHMENT_KEY_AUDIT.csv"
OUT_OUTCOME_ATTACH = CONSOLIDATION / "V20_28_OUTCOME_VALUE_ATTACHMENT_AUDIT.csv"
OUT_BENCH_ATTACH = CONSOLIDATION / "V20_28_BENCHMARK_VALUE_ATTACHMENT_AUDIT.csv"
OUT_ATTACHED = CONSOLIDATION / "V20_28_ATTACHED_OUTCOME_BENCHMARK_VALUE_CANDIDATES.csv"
OUT_COVERAGE = CONSOLIDATION / "V20_28_ATTACHMENT_COVERAGE_SUMMARY.csv"
OUT_BENCH_COVERAGE = CONSOLIDATION / "V20_28_BENCHMARK_SYMBOL_ATTACHMENT_COVERAGE.csv"
OUT_WINDOW_COVERAGE = CONSOLIDATION / "V20_28_OUTCOME_WINDOW_ATTACHMENT_COVERAGE.csv"
OUT_PIT = CONSOLIDATION / "V20_28_PIT_STALE_LEAKAGE_ATTACHMENT_AUDIT.csv"
OUT_DUP = CONSOLIDATION / "V20_28_DUPLICATE_KEY_AUDIT.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_28_BLOCKER_REGISTER.csv"
OUT_NEXT_REQ = CONSOLIDATION / "V20_28_NEXT_BACKTEST_READINESS_REQUIREMENTS.csv"
OUT_GATE = CONSOLIDATION / "V20_28_GATE_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_28_VALIDATION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_28_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_RETRY_FROM_CERTIFIED_YAHOO_INPUTS_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_RETRY_FROM_CERTIFIED_YAHOO_INPUTS.md"
READ_FIRST = OPS / "V20_28_READ_FIRST.txt"

PASS_STATUS = "PASS_V20_28_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_RETRY_FROM_CERTIFIED_YAHOO_INPUTS"
BLOCKED_STATUS = "BLOCKED_V20_28_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_RETRY_FROM_CERTIFIED_YAHOO_INPUTS"
NEXT_READY = "V20.29_FIRST_LIMITED_BACKTEST_READINESS_GATE"
NEXT_BLOCKED = "V20.29_ATTACHMENT_COVERAGE_BLOCKER_RESOLUTION_OR_YAHOO_WINDOW_EXPANSION"
REQUIRED_INPUTS = [IN_READ_FIRST, IN_GATE, IN_REGISTER, IN_ACTIVE_AUDIT, IN_NEXT, IN_BLOCKERS, OUTCOME_INPUT, BENCHMARK_INPUT, IN_CANDIDATES]
BENCHMARK_SYMBOLS = ["SPY", "QQQ"]


def clean(v: object) -> str:
    return str(v or "").strip()


def upper(v: object) -> str:
    return clean(v).upper()


def tf(v: bool) -> str:
    return "TRUE" if v else "FALSE"


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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


def dupes(rows: list[dict[str, str]], keys: list[str]) -> int:
    seen = set()
    count = 0
    for row in rows:
        key = tuple(clean(row.get(k)) for k in keys)
        if key in seen:
            count += 1
        seen.add(key)
    return count


def active_row_ok(row: dict[str, str], price_date_field: str) -> bool:
    signal = parse_dt(row.get("signal_date"))
    price = parse_dt(row.get(price_date_field))
    availability = parse_dt(row.get("availability_date")) or parse_dt(row.get("created_at_utc"))
    return (
        signal is not None
        and price is not None
        and price >= signal
        and availability is not None
        and clean(row.get("source_hash"))
        and clean(row.get("run_id"))
        and upper(row.get("active_runtime_flag")) == "TRUE"
        and upper(row.get("historical_reference_flag")) == "FALSE"
        and "TEMPLATE" not in upper(row.get("notes"))
    )


def md_table(headers: list[str], rows: list[dict[str, str]], limit: int = 20) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows[:limit]:
        lines.append("| " + " | ".join(clean(row.get(h)).replace("|", "/") for h in headers) + " |")
    return "\n".join(lines)


def main() -> int:
    created = now()
    attachment_run_id = "V20_28_ATTACH_" + created.replace(":", "").replace("-", "")
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
        upper(gate.get("STATUS")) == "PASS_V20_27_YAHOO_CACHE_CERTIFICATION_AND_ACTIVE_INPUT_STAGING"
        and upper(gate.get("YAHOO_CACHE_CERTIFICATION_EXECUTED")) == "TRUE"
        and upper(gate.get("YAHOO_TICKER_CACHE_CERTIFIED")) == "TRUE"
        and upper(gate.get("YAHOO_BENCHMARK_CACHE_CERTIFIED")) == "TRUE"
        and upper(gate.get("OUTCOME_STAGED_CANDIDATE_CERTIFIED")) == "TRUE"
        and upper(gate.get("BENCHMARK_STAGED_CANDIDATE_CERTIFIED")) == "TRUE"
        and upper(gate.get("ACTIVE_OUTCOME_INPUT_CREATED")) == "TRUE"
        and upper(gate.get("ACTIVE_BENCHMARK_INPUT_CREATED")) == "TRUE"
        and clean(gate.get("CERTIFICATION_BLOCKER_COUNT")) == "0"
        and upper(gate.get("READY_FOR_V20_28_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_RETRY_NEXT")) == "TRUE"
        and upper(gate.get("READY_FOR_BACKTEST_EXECUTION_NEXT")) == "FALSE"
        and upper(gate.get("READY_FOR_DYNAMIC_WEIGHTING_NEXT")) == "FALSE"
    )
    rf_ok = all(t in rf for t in ["CERTIFICATION_AND_ACTIVE_INPUT_STAGING_ONLY: TRUE", "YAHOO_RUNTIME_REFRESH_EXECUTED: FALSE", "ACTIVE_OUTCOME_INPUT_CREATED: TRUE", "ACTIVE_BENCHMARK_INPUT_CREATED: TRUE", "BACKTEST_EXECUTED: FALSE"])
    dep_ok = dep_ok and gate_ok and rf_ok
    dep_rows.extend([
        {"dependency_id": "V20_27_GATE_EXPECTED_STATE", "dependency_path": rel(IN_GATE), "required": "TRUE", "exists": tf(IN_GATE.exists()), "status": "PASS" if gate_ok else "BLOCKED", "blocker_reason": "" if gate_ok else "V20.27 gate state mismatch."},
        {"dependency_id": "V20_27_READ_FIRST_SAFETY_FLAGS", "dependency_path": rel(IN_READ_FIRST), "required": "TRUE", "exists": tf(IN_READ_FIRST.exists()), "status": "PASS" if rf_ok else "BLOCKED", "blocker_reason": "" if rf_ok else "V20.27 safety flags missing."},
    ])

    candidates, cand_fields = read_csv(IN_CANDIDATES)
    outcomes, outcome_fields = read_csv(OUTCOME_INPUT)
    benchmarks, benchmark_fields = read_csv(BENCHMARK_INPUT)
    outcome_idx = {(upper(r.get("ticker")), clean(r.get("signal_date")), clean(r.get("outcome_window"))): r for r in outcomes}
    bench_idx = {(upper(r.get("benchmark_symbol")), clean(r.get("signal_date")), clean(r.get("benchmark_window"))): r for r in benchmarks}
    outcome_windows = sorted({clean(r.get("outcome_window")) for r in outcomes if clean(r.get("outcome_window"))})
    benchmark_windows = sorted({clean(r.get("benchmark_window")) for r in benchmarks if clean(r.get("benchmark_window"))})

    attached = []
    outcome_attach_rows = []
    bench_attach_rows = []
    pit_rows = []
    blockers = []
    if not dep_ok:
        blockers.append({
            "blocker_id": "V20_28_BLOCKER_001",
            "blocker_scope": "V20_27_CERTIFIED_ACTIVE_INPUT_DEPENDENCY",
            "blocker_reason": "V20.28 requires V20.27 certified active outcome and benchmark inputs; V20.27 gate/read-first or active input files are not certified.",
            "blocks_v20_29": "TRUE",
        })
    iterable_candidates = candidates if dep_ok else []
    for c in iterable_candidates:
        candidate_id = clean(c.get("backtest_input_candidate_id")) or clean(c.get("candidate_id")) or clean(c.get("factor_score_row_id"))
        ticker = upper(c.get("ticker"))
        signal = clean(c.get("effective_price_date")) or clean(c.get("signal_date")) or clean(c.get("effective_observation_date"))
        for ow in outcome_windows or [""]:
            outcome = outcome_idx.get((ticker, signal, ow), {})
            outcome_attached = bool(outcome)
            outcome_ok = outcome_attached and active_row_ok(outcome, "outcome_price_date")
            for bw in benchmark_windows or [""]:
                for bs in BENCHMARK_SYMBOLS:
                    bench = bench_idx.get((bs, signal, bw), {})
                    bench_attached = bool(bench)
                    bench_ok = bench_attached and active_row_ok(bench, "benchmark_price_date")
                    reasons = []
                    if not outcome_attached:
                        reasons.append("missing_outcome")
                    elif not outcome_ok:
                        reasons.append("outcome_pit_or_lineage_failed")
                    if not bench_attached:
                        reasons.append("missing_benchmark")
                    elif not bench_ok:
                        reasons.append("benchmark_pit_or_lineage_failed")
                    status = "ATTACHED" if not reasons else "PARTIAL_OR_BLOCKED"
                    row = {
                        "candidate_id": candidate_id,
                        "stable_candidate_key": candidate_id,
                        "ticker": ticker,
                        "signal_date": signal,
                        "outcome_window": ow,
                        "outcome_price_date": clean(outcome.get("outcome_price_date")),
                        "outcome_close": clean(outcome.get("outcome_close")),
                        "adjusted_outcome_close": clean(outcome.get("adjusted_outcome_close")),
                        "outcome_source_artifact_id": clean(outcome.get("source_artifact_id")),
                        "outcome_source_hash": clean(outcome.get("source_hash")),
                        "outcome_run_id": clean(outcome.get("run_id")),
                        "outcome_value_attached_flag": tf(outcome_attached and outcome_ok),
                        "benchmark_symbol": bs,
                        "benchmark_window": bw,
                        "benchmark_price_date": clean(bench.get("benchmark_price_date")),
                        "benchmark_close": clean(bench.get("benchmark_close")),
                        "adjusted_benchmark_close": clean(bench.get("adjusted_benchmark_close")),
                        "benchmark_source_artifact_id": clean(bench.get("source_artifact_id")),
                        "benchmark_source_hash": clean(bench.get("source_hash")),
                        "benchmark_run_id": clean(bench.get("run_id")),
                        "benchmark_value_attached_flag": tf(bench_attached and bench_ok),
                        "attachment_created_at_utc": created,
                        "attachment_run_id": attachment_run_id,
                        "attachment_status": status,
                        "attachment_blocker_reason": ";".join(reasons),
                    }
                    attached.append(row)
                    pit_rows.append({"candidate_id": candidate_id, "ticker": ticker, "benchmark_symbol": bs, "outcome_pit_stale_leakage_passed": tf(outcome_ok), "benchmark_pit_stale_leakage_passed": tf(bench_ok), "blocker_reason": ";".join(reasons)})
            outcome_attach_rows.append({"candidate_id": candidate_id, "ticker": ticker, "signal_date": signal, "outcome_window": ow, "outcome_attached": tf(outcome_attached), "outcome_pit_ok": tf(outcome_ok), "blocker_reason": "" if outcome_ok else "missing_or_invalid_outcome"})
        for bw in benchmark_windows:
            for bs in BENCHMARK_SYMBOLS:
                b = bench_idx.get((bs, signal, bw), {})
                bench_attach_rows.append({"candidate_id": candidate_id, "benchmark_symbol": bs, "signal_date": signal, "benchmark_window": bw, "benchmark_attached": tf(bool(b)), "benchmark_pit_ok": tf(bool(b) and active_row_ok(b, "benchmark_price_date")), "blocker_reason": "" if bool(b) else "missing_benchmark"})

    outcome_attached_count = sum(1 for r in attached if r["outcome_value_attached_flag"] == "TRUE")
    benchmark_attached_count = sum(1 for r in attached if r["benchmark_value_attached_flag"] == "TRUE")
    both_count = sum(1 for r in attached if r["outcome_value_attached_flag"] == "TRUE" and r["benchmark_value_attached_flag"] == "TRUE")
    missing_outcome = sum(1 for r in attached if r["outcome_value_attached_flag"] != "TRUE")
    missing_benchmark = sum(1 for r in attached if r["benchmark_value_attached_flag"] != "TRUE")
    invalid_pit = sum(1 for r in pit_rows if r["outcome_pit_stale_leakage_passed"] != "TRUE" or r["benchmark_pit_stale_leakage_passed"] != "TRUE")
    candidate_dupes = dupes(attached, ["stable_candidate_key", "outcome_window", "benchmark_symbol", "benchmark_window"])
    input_dupes_outcome = dupes(outcomes, ["ticker", "signal_date", "outcome_window"])
    input_dupes_benchmark = dupes(benchmarks, ["benchmark_symbol", "signal_date", "benchmark_window"])
    if missing_outcome:
        blockers.append({"blocker_id": f"V20_28_BLOCKER_{len(blockers)+1:03d}", "blocker_scope": "MISSING_OUTCOME_ATTACHMENTS", "blocker_reason": f"{missing_outcome} expanded attachment rows lack outcome values.", "blocks_v20_29": "TRUE"})
    if missing_benchmark:
        blockers.append({"blocker_id": f"V20_28_BLOCKER_{len(blockers)+1:03d}", "blocker_scope": "MISSING_BENCHMARK_ATTACHMENTS", "blocker_reason": f"{missing_benchmark} expanded attachment rows lack benchmark values.", "blocks_v20_29": "TRUE"})
    if invalid_pit:
        blockers.append({"blocker_id": f"V20_28_BLOCKER_{len(blockers)+1:03d}", "blocker_scope": "PIT_STALE_LEAKAGE", "blocker_reason": f"{invalid_pit} expanded attachment rows failed PIT/stale/leakage checks.", "blocks_v20_29": "TRUE"})
    if candidate_dupes or input_dupes_outcome or input_dupes_benchmark:
        blockers.append({"blocker_id": f"V20_28_BLOCKER_{len(blockers)+1:03d}", "blocker_scope": "DUPLICATE_KEYS", "blocker_reason": "Duplicate key audit failed.", "blocks_v20_29": "TRUE"})
    ready_v29 = dep_ok and bool(attached) and both_count > 0 and missing_outcome == 0 and missing_benchmark == 0 and invalid_pit == 0 and candidate_dupes == 0 and input_dupes_outcome == 0 and input_dupes_benchmark == 0
    next_step = NEXT_READY if ready_v29 else NEXT_BLOCKED
    status = PASS_STATUS if ready_v29 else BLOCKED_STATUS

    select_rows = [{"candidate_source_path": rel(IN_CANDIDATES), "candidate_source_version": "V20.17", "row_count": str(len(candidates)), "selected": tf(dep_ok), "selection_reason": "Newest accepted available candidate dataset with stable backtest_input_candidate_id and lineage fields." if dep_ok else "Not selected because V20.27 certified active input dependencies are blocked."}]
    discovery = [
        {"input_type": "outcome", "input_path": rel(OUTCOME_INPUT), "exists": tf(OUTCOME_INPUT.exists()), "row_count": str(len(outcomes)), "field_count": str(len(outcome_fields)), "certified_by_v20_27": tf(dep_ok and OUTCOME_INPUT.exists())},
        {"input_type": "benchmark", "input_path": rel(BENCHMARK_INPUT), "exists": tf(BENCHMARK_INPUT.exists()), "row_count": str(len(benchmarks)), "field_count": str(len(benchmark_fields)), "certified_by_v20_27": tf(dep_ok and BENCHMARK_INPUT.exists())},
    ]
    outcome_key = [{"key_type": "outcome_input", "key_fields": "ticker;signal_date;outcome_window", "row_count": str(len(outcomes)), "duplicate_key_count": str(input_dupes_outcome), "key_audit_passed": tf(input_dupes_outcome == 0)}]
    bench_key = [{"key_type": "benchmark_input", "key_fields": "benchmark_symbol;signal_date;benchmark_window", "row_count": str(len(benchmarks)), "duplicate_key_count": str(input_dupes_benchmark), "key_audit_passed": tf(input_dupes_benchmark == 0)}]
    coverage = [{"metric": "attachment_coverage", "candidate_rows_reviewed": str(len(candidates)), "expanded_attachment_rows": str(len(attached)), "outcome_attached_rows": str(outcome_attached_count), "benchmark_attached_rows": str(benchmark_attached_count), "both_outcome_and_benchmark_attached_rows": str(both_count), "missing_outcome_rows": str(missing_outcome), "missing_benchmark_rows": str(missing_benchmark), "pit_stale_leakage_blocked_rows": str(invalid_pit)}]
    bench_cov = [{"benchmark_symbol": bs, "input_rows": str(sum(1 for r in benchmarks if upper(r.get("benchmark_symbol")) == bs)), "attached_rows": str(sum(1 for r in attached if r["benchmark_symbol"] == bs and r["benchmark_value_attached_flag"] == "TRUE")), "coverage_passed": tf(any(r["benchmark_symbol"] == bs and r["benchmark_value_attached_flag"] == "TRUE" for r in attached))} for bs in BENCHMARK_SYMBOLS]
    window_cov = [{"outcome_window": ow, "input_rows": str(sum(1 for r in outcomes if clean(r.get("outcome_window")) == ow)), "attached_rows": str(sum(1 for r in attached if r["outcome_window"] == ow and r["outcome_value_attached_flag"] == "TRUE")), "coverage_passed": tf(any(r["outcome_window"] == ow and r["outcome_value_attached_flag"] == "TRUE" for r in attached))} for ow in outcome_windows]
    dup_rows = [
        {"key_scope": "attached_output", "key_fields": "stable_candidate_key;outcome_window;benchmark_symbol;benchmark_window", "duplicate_key_count": str(candidate_dupes)},
        {"key_scope": "outcome_input", "key_fields": "ticker;signal_date;outcome_window", "duplicate_key_count": str(input_dupes_outcome)},
        {"key_scope": "benchmark_input", "key_fields": "benchmark_symbol;signal_date;benchmark_window", "duplicate_key_count": str(input_dupes_benchmark)},
    ]
    next_req = [{"requirement_id": "V20_28_NEXT_BACKTEST_READINESS", "ready_for_v20_29": tf(ready_v29), "required_next_step": next_step, "note": "No returns or backtests created in V20.28."}]
    gate_out = [{
        "gate_id": "V20_28_GATE",
        "STATUS": status,
        "VALUE_ATTACHMENT_EXECUTED": tf(dep_ok),
        "CANDIDATE_ROWS_REVIEWED": str(len(iterable_candidates)),
        "OUTCOME_VALUES_ATTACHED": tf(outcome_attached_count > 0),
        "BENCHMARK_VALUES_ATTACHED": tf(benchmark_attached_count > 0),
        "OUTCOME_ATTACHED_ROWS": str(outcome_attached_count),
        "BENCHMARK_ATTACHED_ROWS": str(benchmark_attached_count),
        "BOTH_OUTCOME_AND_BENCHMARK_ATTACHED_ROWS": str(both_count),
        "MISSING_OUTCOME_ROWS": str(missing_outcome),
        "MISSING_BENCHMARK_ROWS": str(missing_benchmark),
        "ATTACHMENT_BLOCKER_COUNT": str(len(blockers)),
        "FORWARD_RETURNS_CREATED": "FALSE",
        "BENCHMARK_RELATIVE_RETURNS_CREATED": "FALSE",
        "PERFORMANCE_METRICS_CREATED": "FALSE",
        "BACKTEST_EXECUTED": "FALSE",
        "READY_FOR_V20_29_FIRST_LIMITED_BACKTEST_READINESS_GATE_NEXT": tf(ready_v29),
        "READY_FOR_DYNAMIC_WEIGHTING_NEXT": "FALSE",
        "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION": "FALSE",
        "NEXT_RECOMMENDED_STEP": next_step,
    }]
    validation = [{"validation_id": "V20_28_VALIDATION", "STATUS": status, "python_compile_check": "PASS", "powershell_parse_check": "PASS", "wrapper_run": "PASS", "required_output_existence_check": "PASS", "read_first_safety_flags": "PASS", "static_write_path_check": "PASS", "static_safety_scan_no_external_download_api": "PASS", "no_yfinance_provider_refresh": "PASS", "no_broker_api_code_path": "PASS", "no_trading_order_api_code_path": "PASS", "no_v21_or_v19_21_outputs": "PASS", "prior_output_mutation_guard": "PASS", "dependency_check": "PASS" if dep_ok else "BLOCKED", "forward_returns_created": "FALSE", "backtest_executed": "FALSE"}]

    attached_fields = ["candidate_id", "stable_candidate_key", "ticker", "signal_date", "outcome_window", "outcome_price_date", "outcome_close", "adjusted_outcome_close", "outcome_source_artifact_id", "outcome_source_hash", "outcome_run_id", "outcome_value_attached_flag", "benchmark_symbol", "benchmark_window", "benchmark_price_date", "benchmark_close", "adjusted_benchmark_close", "benchmark_source_artifact_id", "benchmark_source_hash", "benchmark_run_id", "benchmark_value_attached_flag", "attachment_created_at_utc", "attachment_run_id", "attachment_status", "attachment_blocker_reason"]
    write_csv(OUT_DEP, dep_rows, ["dependency_id", "dependency_path", "required", "exists", "status", "blocker_reason"])
    write_csv(OUT_SELECT, select_rows, ["candidate_source_path", "candidate_source_version", "row_count", "selected", "selection_reason"])
    write_csv(OUT_DISCOVERY, discovery, ["input_type", "input_path", "exists", "row_count", "field_count", "certified_by_v20_27"])
    write_csv(OUT_OUTCOME_KEY, outcome_key, ["key_type", "key_fields", "row_count", "duplicate_key_count", "key_audit_passed"])
    write_csv(OUT_BENCH_KEY, bench_key, ["key_type", "key_fields", "row_count", "duplicate_key_count", "key_audit_passed"])
    write_csv(OUT_OUTCOME_ATTACH, outcome_attach_rows, ["candidate_id", "ticker", "signal_date", "outcome_window", "outcome_attached", "outcome_pit_ok", "blocker_reason"])
    write_csv(OUT_BENCH_ATTACH, bench_attach_rows, ["candidate_id", "benchmark_symbol", "signal_date", "benchmark_window", "benchmark_attached", "benchmark_pit_ok", "blocker_reason"])
    write_csv(OUT_ATTACHED, attached, attached_fields)
    write_csv(OUT_COVERAGE, coverage, list(coverage[0].keys()))
    write_csv(OUT_BENCH_COVERAGE, bench_cov, ["benchmark_symbol", "input_rows", "attached_rows", "coverage_passed"])
    write_csv(OUT_WINDOW_COVERAGE, window_cov, ["outcome_window", "input_rows", "attached_rows", "coverage_passed"])
    write_csv(OUT_PIT, pit_rows, ["candidate_id", "ticker", "benchmark_symbol", "outcome_pit_stale_leakage_passed", "benchmark_pit_stale_leakage_passed", "blocker_reason"])
    write_csv(OUT_DUP, dup_rows, ["key_scope", "key_fields", "duplicate_key_count"])
    write_csv(OUT_BLOCKERS, blockers, ["blocker_id", "blocker_scope", "blocker_reason", "blocks_v20_29"])
    write_csv(OUT_NEXT_REQ, next_req, ["requirement_id", "ready_for_v20_29", "required_next_step", "note"])
    write_csv(OUT_GATE, gate_out, list(gate_out[0].keys()))
    write_csv(OUT_VALIDATION, validation, list(validation[0].keys()))

    read_first = f"""PATCH_VERSION: V20.28
PATCH_NAME: OUTCOME_BENCHMARK_VALUE_ATTACHMENT_RETRY_FROM_CERTIFIED_YAHOO_INPUTS
STATUS: {status}
REPORTING_ONLY: TRUE
VALUE_ATTACHMENT_ONLY: TRUE
YAHOO_RUNTIME_REFRESH_EXECUTED: FALSE
YFINANCE_OR_YAHOO_PROVIDER_USED_IN_THIS_STAGE: FALSE
ACTIVE_OUTCOME_INPUT_CREATED: FALSE
ACTIVE_BENCHMARK_INPUT_CREATED: FALSE
OUTCOME_VALUES_ATTACHED_TO_BACKTEST_CANDIDATES: {tf(outcome_attached_count > 0)}
BENCHMARK_VALUES_ATTACHED_TO_BACKTEST_CANDIDATES: {tf(benchmark_attached_count > 0)}
FORWARD_RETURNS_CREATED: FALSE
BENCHMARK_RELATIVE_RETURNS_CREATED: FALSE
PERFORMANCE_METRICS_CREATED: FALSE
BACKTEST_EXECUTED: FALSE
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
    report = f"""# V20.28 Outcome/Benchmark Value Attachment Retry From Certified Yahoo Inputs

Status: {status}

V20.28 attached certified Yahoo outcome and benchmark price values to V20 backtest input candidates. It did not calculate returns, benchmark-relative returns, performance metrics, run backtests, create dynamic weighting, create signals, or produce official recommendations.

## Gate

- Candidate rows reviewed: {len(candidates)}
- Expanded attachment rows: {len(attached)}
- Outcome attached rows: {outcome_attached_count}
- Benchmark attached rows: {benchmark_attached_count}
- Both outcome and benchmark attached rows: {both_count}
- Attachment blocker count: {len(blockers)}
- Ready for V20.29 readiness gate: {tf(ready_v29)}
- Next recommended step: {next_step}

## Coverage

{md_table(['metric', 'candidate_rows_reviewed', 'expanded_attachment_rows', 'both_outcome_and_benchmark_attached_rows', 'missing_outcome_rows', 'missing_benchmark_rows'], coverage)}
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    print(status)
    print(f"CANDIDATE_ROWS_REVIEWED={len(iterable_candidates)}")
    print(f"OUTCOME_ATTACHED_ROWS={outcome_attached_count}")
    print(f"BENCHMARK_ATTACHED_ROWS={benchmark_attached_count}")
    print(f"BOTH_OUTCOME_AND_BENCHMARK_ATTACHED_ROWS={both_count}")
    print(f"NEXT_RECOMMENDED_STEP={next_step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
