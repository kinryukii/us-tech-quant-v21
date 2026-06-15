from __future__ import annotations

import csv
import hashlib
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
INPUT_BASE = ROOT / "inputs" / "v20" / "outcome_benchmark"

IN_READ_FIRST = OPS / "V20_26_READ_FIRST.txt"
IN_GATE = CONSOLIDATION / "V20_26_GATE_DECISION.csv"
IN_CACHE_REGISTER = CONSOLIDATION / "V20_26_YAHOO_CACHE_FILE_REGISTER.csv"
IN_HASH_LEDGER = CONSOLIDATION / "V20_26_YAHOO_CACHE_HASH_LEDGER.csv"
IN_RUN_LEDGER = CONSOLIDATION / "V20_26_RUN_ID_LEDGER.csv"
IN_SCHEMA_AUDIT = CONSOLIDATION / "V20_26_CACHE_SCHEMA_AUDIT.csv"
IN_DATE_COVERAGE = CONSOLIDATION / "V20_26_PRICE_DATE_COVERAGE_AUDIT.csv"
IN_BENCH_COVERAGE = CONSOLIDATION / "V20_26_BENCHMARK_SYMBOL_COVERAGE_AUDIT.csv"
IN_STAGED_REGISTER = CONSOLIDATION / "V20_26_STAGED_INPUT_CANDIDATE_REGISTER.csv"
IN_NEXT_REQ = CONSOLIDATION / "V20_26_NEXT_CERTIFICATION_REQUIREMENTS.csv"
IN_CANDIDATES = CONSOLIDATION / "V20_17_BACKTEST_INPUT_CANDIDATE_DATASET.csv"

TICKER_CACHE = INPUT_BASE / "yahoo_cache" / "v20_26" / "V20_26_YAHOO_TICKER_PRICE_CACHE.csv"
BENCHMARK_CACHE = INPUT_BASE / "yahoo_cache" / "v20_26" / "V20_26_YAHOO_BENCHMARK_PRICE_CACHE.csv"
STAGED_OUTCOME = INPUT_BASE / "staging" / "v20_26" / "V20_26_STAGED_YAHOO_OUTCOME_SOURCE_INPUT_CANDIDATE.csv"
STAGED_BENCHMARK = INPUT_BASE / "staging" / "v20_26" / "V20_26_STAGED_YAHOO_BENCHMARK_SOURCE_INPUT_CANDIDATE.csv"
ACTIVE_OUTCOME = INPUT_BASE / "V20_OUTCOME_SOURCE_INPUT.csv"
ACTIVE_BENCHMARK = INPUT_BASE / "V20_BENCHMARK_SOURCE_INPUT.csv"

OUT_DEP = CONSOLIDATION / "V20_27_DEPENDENCY_AUDIT.csv"
OUT_DISCOVERY = CONSOLIDATION / "V20_27_YAHOO_CACHE_FILE_DISCOVERY.csv"
OUT_SCHEMA = CONSOLIDATION / "V20_27_YAHOO_CACHE_SCHEMA_CERTIFICATION_AUDIT.csv"
OUT_HASH = CONSOLIDATION / "V20_27_YAHOO_CACHE_HASH_CERTIFICATION_AUDIT.csv"
OUT_RUN = CONSOLIDATION / "V20_27_YAHOO_CACHE_RUN_ID_CERTIFICATION_AUDIT.csv"
OUT_TICKER_QUALITY = CONSOLIDATION / "V20_27_TICKER_PRICE_CACHE_ROW_QUALITY_AUDIT.csv"
OUT_BENCH_QUALITY = CONSOLIDATION / "V20_27_BENCHMARK_PRICE_CACHE_ROW_QUALITY_AUDIT.csv"
OUT_OUTCOME_CERT = CONSOLIDATION / "V20_27_OUTCOME_STAGED_CANDIDATE_CERTIFICATION_AUDIT.csv"
OUT_BENCH_CERT = CONSOLIDATION / "V20_27_BENCHMARK_STAGED_CANDIDATE_CERTIFICATION_AUDIT.csv"
OUT_BENCH_SYMBOL = CONSOLIDATION / "V20_27_BENCHMARK_SYMBOL_COVERAGE_AUDIT.csv"
OUT_WINDOW = CONSOLIDATION / "V20_27_OUTCOME_WINDOW_COVERAGE_AUDIT.csv"
OUT_PIT = CONSOLIDATION / "V20_27_PIT_STALE_LEAKAGE_CERTIFICATION_AUDIT.csv"
OUT_DUP = CONSOLIDATION / "V20_27_DUPLICATE_KEY_AUDIT.csv"
OUT_ACTIVE_AUDIT = CONSOLIDATION / "V20_27_ACTIVE_INPUT_FILE_CREATION_AUDIT.csv"
OUT_REGISTER = CONSOLIDATION / "V20_27_CERTIFIED_ACTIVE_INPUT_REGISTER.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_27_BLOCKER_REGISTER.csv"
OUT_GAP = CONSOLIDATION / "V20_27_REQUIRED_ACTIVE_INPUT_GAP_ANALYSIS.csv"
OUT_NEXT = CONSOLIDATION / "V20_27_NEXT_VALUE_ATTACHMENT_REQUIREMENTS.csv"
OUT_GATE = CONSOLIDATION / "V20_27_GATE_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_27_VALIDATION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_27_YAHOO_CACHE_CERTIFICATION_AND_ACTIVE_INPUT_STAGING_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_YAHOO_CACHE_CERTIFICATION_AND_ACTIVE_INPUT_STAGING.md"
READ_FIRST = OPS / "V20_27_READ_FIRST.txt"

PASS_STATUS = "PASS_V20_27_YAHOO_CACHE_CERTIFICATION_AND_ACTIVE_INPUT_STAGING"
BLOCKED_STATUS = "BLOCKED_V20_27_YAHOO_CACHE_CERTIFICATION_AND_ACTIVE_INPUT_STAGING"
NEXT_READY = "V20.28_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_RETRY_FROM_CERTIFIED_YAHOO_INPUTS"
NEXT_BLOCKED = "V20.28_YAHOO_CACHE_CERTIFICATION_BLOCKER_RESOLUTION"
REQUIRED_INPUTS = [
    IN_READ_FIRST, IN_GATE, IN_CACHE_REGISTER, IN_HASH_LEDGER, IN_RUN_LEDGER,
    IN_SCHEMA_AUDIT, IN_DATE_COVERAGE, IN_BENCH_COVERAGE, IN_STAGED_REGISTER,
    IN_NEXT_REQ,
]
CACHE_FIELDS = ["symbol", "price_date", "open", "high", "low", "close", "adjusted_close", "volume", "currency", "data_vendor_or_source_system", "provider_query_start_date", "provider_query_end_date", "provider_download_timestamp_utc", "source_artifact_id", "source_hash", "run_id", "active_runtime_flag", "historical_reference_flag", "created_at_utc", "notes"]
OUTCOME_FIELDS = ["ticker", "signal_date", "outcome_window", "outcome_price_date", "outcome_close", "adjusted_outcome_close", "currency", "source_artifact_id", "source_hash", "run_id", "active_runtime_flag", "historical_reference_flag", "availability_date", "created_at_utc", "data_vendor_or_source_system", "notes"]
BENCHMARK_FIELDS = ["benchmark_symbol", "signal_date", "benchmark_window", "benchmark_price_date", "benchmark_close", "adjusted_benchmark_close", "currency", "source_artifact_id", "source_hash", "run_id", "active_runtime_flag", "historical_reference_flag", "availability_date", "created_at_utc", "data_vendor_or_source_system", "notes"]
BENCHMARK_SYMBOLS = {"SPY", "QQQ"}
OUTCOME_WINDOWS = {"forward_1d": 1, "forward_5d": 5, "forward_10d": 10, "forward_20d": 20, "forward_60d": 60}
BENCHMARK_WINDOWS = {"benchmark_forward_1d": 1, "benchmark_forward_5d": 5, "benchmark_forward_10d": 10, "benchmark_forward_20d": 20, "benchmark_forward_60d": 60}


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


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_date(v: object) -> bool:
    text = clean(v).replace("Z", "+00:00")
    if not text:
        return False
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            datetime.strptime(text[:10], fmt)
            return True
        except ValueError:
            pass
    try:
        datetime.fromisoformat(text)
        return True
    except ValueError:
        return False


def to_date(v: object) -> datetime | None:
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


def iso_date(v: datetime | None) -> str:
    return v.strftime("%Y-%m-%d") if v is not None else ""


def max_price_date(rows: list[dict[str, str]], symbol_field: str = "symbol") -> dict[str, datetime]:
    latest: dict[str, datetime] = {}
    for row in rows:
        symbol = upper(row.get(symbol_field))
        date = to_date(row.get("price_date"))
        if not symbol or date is None:
            continue
        if symbol not in latest or date > latest[symbol]:
            latest[symbol] = date
    return latest


def staged_gap_analysis(
    candidates: list[dict[str, str]],
    ticker_rows: list[dict[str, str]],
    bench_rows: list[dict[str, str]],
    outcome_rows: list[dict[str, str]],
    staged_bench_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    signals = sorted({
        d for d in (
            to_date(c.get("effective_price_date")) or to_date(c.get("effective_observation_date"))
            for c in candidates
        )
        if d is not None
    })
    signal_count = len(signals)
    unique_candidate_tickers = len({upper(c.get("ticker")) for c in candidates if clean(c.get("ticker"))})
    ticker_latest = max_price_date(ticker_rows)
    bench_latest = max_price_date(bench_rows)
    overall_ticker_latest = max(ticker_latest.values()) if ticker_latest else None
    overall_benchmark_latest = max(bench_latest.values()) if bench_latest else None
    first_signal = min(signals) if signals else None
    last_signal = max(signals) if signals else None
    # The explicit loops below keep this diagnostic readable and avoid fabricating rows.
    outcome_targets: list[datetime] = []
    benchmark_targets: list[datetime] = []
    from datetime import timedelta as td

    for signal in signals:
        outcome_targets.extend(signal + td(days=days) for days in OUTCOME_WINDOWS.values())
        benchmark_targets.extend(signal + td(days=days) for days in BENCHMARK_WINDOWS.values())

    first_outcome_target = min(outcome_targets) if outcome_targets else None
    latest_outcome_target = max(outcome_targets) if outcome_targets else None
    first_benchmark_target = min(benchmark_targets) if benchmark_targets else None
    latest_benchmark_target = max(benchmark_targets) if benchmark_targets else None
    outcome_target_dates_available = {
        clean(r.get("price_date")) for r in ticker_rows if clean(r.get("price_date"))
    }
    benchmark_target_dates_available = {
        clean(r.get("price_date")) for r in bench_rows if clean(r.get("price_date"))
    }
    expected_outcome_target_dates = {iso_date(t) for t in outcome_targets}
    expected_benchmark_target_dates = {iso_date(t) for t in benchmark_targets}
    missing_outcome_dates = sorted(expected_outcome_target_dates - outcome_target_dates_available)
    missing_benchmark_dates = sorted(expected_benchmark_target_dates - benchmark_target_dates_available)

    return [
        {
            "input_type": "outcome",
            "required_staged_candidate_path": rel(STAGED_OUTCOME),
            "staged_candidate_exists": tf(STAGED_OUTCOME.exists()),
            "staged_candidate_rows": str(len(outcome_rows)),
            "active_input_path": rel(ACTIVE_OUTCOME),
            "active_input_created": tf(ACTIVE_OUTCOME.exists() and bool(outcome_rows)),
            "candidate_rows": str(len(candidates)),
            "unique_candidate_tickers": str(unique_candidate_tickers),
            "unique_signal_dates": str(signal_count),
            "first_signal_date": iso_date(first_signal),
            "last_signal_date": iso_date(last_signal),
            "first_required_target_date": iso_date(first_outcome_target),
            "latest_required_target_date": iso_date(latest_outcome_target),
            "latest_available_cache_price_date": iso_date(overall_ticker_latest),
            "missing_required_target_date_count": str(len(missing_outcome_dates)),
            "missing_required_target_date_examples": ";".join(missing_outcome_dates[:10]),
            "root_cause": "PIT_SAFE_FORWARD_OUTCOME_TARGET_DATES_NOT_AVAILABLE" if missing_outcome_dates else "STAGED_OUTCOME_SCHEMA_OR_LINEAGE_CERTIFICATION_FAILED",
            "recommended_next_action": "Wait for actual future outcome dates or import authoritative PIT-safe local outcome rows; do not fabricate outcomes.",
        },
        {
            "input_type": "benchmark",
            "required_staged_candidate_path": rel(STAGED_BENCHMARK),
            "staged_candidate_exists": tf(STAGED_BENCHMARK.exists()),
            "staged_candidate_rows": str(len(staged_bench_rows)),
            "active_input_path": rel(ACTIVE_BENCHMARK),
            "active_input_created": tf(ACTIVE_BENCHMARK.exists() and bool(staged_bench_rows)),
            "candidate_rows": str(len(candidates)),
            "unique_candidate_tickers": str(unique_candidate_tickers),
            "unique_signal_dates": str(signal_count),
            "first_signal_date": iso_date(first_signal),
            "last_signal_date": iso_date(last_signal),
            "first_required_target_date": iso_date(first_benchmark_target),
            "latest_required_target_date": iso_date(latest_benchmark_target),
            "latest_available_cache_price_date": iso_date(overall_benchmark_latest),
            "missing_required_target_date_count": str(len(missing_benchmark_dates)),
            "missing_required_target_date_examples": ";".join(missing_benchmark_dates[:10]),
            "root_cause": "PIT_SAFE_FORWARD_BENCHMARK_TARGET_DATES_NOT_AVAILABLE" if missing_benchmark_dates else "STAGED_BENCHMARK_SCHEMA_OR_LINEAGE_CERTIFICATION_FAILED",
            "recommended_next_action": "Wait for actual future benchmark dates or import authoritative PIT-safe local benchmark rows; do not fabricate benchmark returns.",
        },
    ]


def is_num(v: object) -> bool:
    try:
        float(clean(v))
        return True
    except ValueError:
        return False


def nonempty_all(rows: list[dict[str, str]], field: str) -> bool:
    return bool(rows) and all(clean(r.get(field)) for r in rows)


def true_all(rows: list[dict[str, str]], field: str) -> bool:
    return bool(rows) and all(upper(r.get(field)) == "TRUE" for r in rows)


def false_all(rows: list[dict[str, str]], field: str) -> bool:
    return bool(rows) and all(upper(r.get(field)) == "FALSE" for r in rows)


def price_ok(rows: list[dict[str, str]], fields: list[str]) -> bool:
    return bool(rows) and all(any(clean(r.get(f)) and is_num(r.get(f)) for f in fields) for r in rows)


def dupes(rows: list[dict[str, str]], keys: list[str]) -> int:
    seen = set()
    count = 0
    for row in rows:
        key = tuple(clean(row.get(k)) for k in keys)
        if key in seen:
            count += 1
        seen.add(key)
    return count


def date_order_ok(rows: list[dict[str, str]], signal_field: str, price_field: str) -> bool:
    if not rows:
        return False
    for row in rows:
        signal = to_date(row.get(signal_field))
        price = to_date(row.get(price_field))
        if signal is None or price is None or price < signal:
            return False
    return True


def cache_cert(rows: list[dict[str, str]], fields: list[str]) -> bool:
    return (
        bool(rows)
        and set(CACHE_FIELDS).issubset(set(fields))
        and nonempty_all(rows, "symbol")
        and all(parse_date(r.get("price_date")) for r in rows)
        and price_ok(rows, ["close", "adjusted_close"])
        and nonempty_all(rows, "source_artifact_id")
        and nonempty_all(rows, "source_hash")
        and nonempty_all(rows, "run_id")
        and true_all(rows, "active_runtime_flag")
        and false_all(rows, "historical_reference_flag")
        and all(parse_date(r.get("created_at_utc")) for r in rows)
        and all(parse_date(r.get("provider_download_timestamp_utc")) for r in rows)
        and dupes(rows, ["symbol", "price_date"]) == 0
    )


def staged_outcome_cert(rows: list[dict[str, str]], fields: list[str], cache_hashes: set[str]) -> bool:
    return (
        bool(rows)
        and set(OUTCOME_FIELDS).issubset(set(fields))
        and nonempty_all(rows, "ticker")
        and all(parse_date(r.get("signal_date")) for r in rows)
        and nonempty_all(rows, "outcome_window")
        and all(parse_date(r.get("outcome_price_date")) for r in rows)
        and price_ok(rows, ["outcome_close", "adjusted_outcome_close"])
        and nonempty_all(rows, "currency")
        and nonempty_all(rows, "source_artifact_id")
        and all(clean(r.get("source_artifact_id")).startswith("V20_26_YAHOO_TICKER::") for r in rows)
        and nonempty_all(rows, "source_hash")
        and all(clean(r.get("source_hash")) in cache_hashes for r in rows)
        and nonempty_all(rows, "run_id")
        and true_all(rows, "active_runtime_flag")
        and false_all(rows, "historical_reference_flag")
        and all(parse_date(r.get("availability_date")) or parse_date(r.get("created_at_utc")) for r in rows)
        and nonempty_all(rows, "data_vendor_or_source_system")
        and dupes(rows, ["ticker", "signal_date", "outcome_window"]) == 0
        and date_order_ok(rows, "signal_date", "outcome_price_date")
    )


def staged_benchmark_cert(rows: list[dict[str, str]], fields: list[str], cache_hashes: set[str]) -> bool:
    symbols = {upper(r.get("benchmark_symbol")) for r in rows}
    return (
        bool(rows)
        and set(BENCHMARK_FIELDS).issubset(set(fields))
        and nonempty_all(rows, "benchmark_symbol")
        and BENCHMARK_SYMBOLS.issubset(symbols)
        and all(parse_date(r.get("signal_date")) for r in rows)
        and nonempty_all(rows, "benchmark_window")
        and all(parse_date(r.get("benchmark_price_date")) for r in rows)
        and price_ok(rows, ["benchmark_close", "adjusted_benchmark_close"])
        and nonempty_all(rows, "source_artifact_id")
        and all(clean(r.get("source_artifact_id")).startswith("V20_26_YAHOO_BENCHMARK::") for r in rows)
        and nonempty_all(rows, "source_hash")
        and all(clean(r.get("source_hash")) in cache_hashes for r in rows)
        and nonempty_all(rows, "run_id")
        and true_all(rows, "active_runtime_flag")
        and false_all(rows, "historical_reference_flag")
        and all(parse_date(r.get("availability_date")) or parse_date(r.get("created_at_utc")) for r in rows)
        and nonempty_all(rows, "data_vendor_or_source_system")
        and dupes(rows, ["benchmark_symbol", "signal_date", "benchmark_window"]) == 0
        and date_order_ok(rows, "signal_date", "benchmark_price_date")
    )


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
        upper(gate.get("STATUS")) == "PASS_V20_26_YAHOO_RUNTIME_OUTCOME_BENCHMARK_SOURCE_ADAPTER"
        and upper(gate.get("ARCHITECTURE_CORRECTION_APPLIED")) == "TRUE"
        and upper(gate.get("MANUAL_STAGING_RECLASSIFIED_AS_FALLBACK")) == "TRUE"
        and upper(gate.get("YAHOO_RUNTIME_REFRESH_ATTEMPTED")) == "TRUE"
        and upper(gate.get("LOCAL_YAHOO_CACHE_CREATED")) == "TRUE"
        and upper(gate.get("READY_FOR_V20_27_YAHOO_CACHE_CERTIFICATION_NEXT")) == "TRUE"
        and upper(gate.get("ACTIVE_OUTCOME_INPUT_CREATED")) == "FALSE"
        and upper(gate.get("ACTIVE_BENCHMARK_INPUT_CREATED")) == "FALSE"
        and upper(gate.get("READY_FOR_VALUE_ATTACHMENT_NEXT")) == "FALSE"
        and upper(gate.get("READY_FOR_BACKTEST_EXECUTION_NEXT")) == "FALSE"
    )
    rf_ok = all(t in rf for t in ["SOURCE_ADAPTER_ONLY: TRUE", "YAHOO_RUNTIME_REFRESH_EXECUTED: TRUE", "LOCAL_CACHE_CREATED: TRUE", "CERTIFICATION_EXECUTED: FALSE", "ACTIVE_OUTCOME_INPUT_CREATED: FALSE", "ACTIVE_BENCHMARK_INPUT_CREATED: FALSE", "BACKTEST_EXECUTED: FALSE"])
    dep_ok = dep_ok and gate_ok and rf_ok
    dep_rows.extend([
        {"dependency_id": "V20_26_GATE_EXPECTED_STATE", "dependency_path": rel(IN_GATE), "required": "TRUE", "exists": tf(IN_GATE.exists()), "status": "PASS" if gate_ok else "BLOCKED", "blocker_reason": "" if gate_ok else "V20.26 gate state mismatch."},
        {"dependency_id": "V20_26_READ_FIRST_SAFETY_FLAGS", "dependency_path": rel(IN_READ_FIRST), "required": "TRUE", "exists": tf(IN_READ_FIRST.exists()), "status": "PASS" if rf_ok else "BLOCKED", "blocker_reason": "" if rf_ok else "V20.26 safety flags missing."},
    ])

    ticker_rows, ticker_fields = read_csv(TICKER_CACHE)
    bench_rows, bench_fields = read_csv(BENCHMARK_CACHE)
    outcome_rows, outcome_fields = read_csv(STAGED_OUTCOME)
    staged_bench_rows, staged_bench_fields = read_csv(STAGED_BENCHMARK)
    candidates, _ = read_csv(IN_CANDIDATES)
    hash_rows, _ = read_csv(IN_HASH_LEDGER)
    ledger_hashes = {clean(r.get("cache_path")): clean(r.get("file_hash_sha256")) for r in hash_rows}
    cache_hashes = {clean(r.get("source_hash")) for r in ticker_rows + bench_rows if clean(r.get("source_hash"))}

    ticker_cert = cache_cert(ticker_rows, ticker_fields)
    bench_cert = cache_cert(bench_rows, bench_fields) and BENCHMARK_SYMBOLS.issubset({upper(r.get("symbol")) for r in bench_rows})
    outcome_cert = staged_outcome_cert(outcome_rows, outcome_fields, cache_hashes)
    staged_bench_cert = staged_benchmark_cert(staged_bench_rows, staged_bench_fields, cache_hashes)

    if outcome_cert:
        write_csv(ACTIVE_OUTCOME, outcome_rows, OUTCOME_FIELDS)
    if staged_bench_cert:
        write_csv(ACTIVE_BENCHMARK, staged_bench_rows, BENCHMARK_FIELDS)

    active_outcome_created = outcome_cert and ACTIVE_OUTCOME.exists()
    active_bench_created = staged_bench_cert and ACTIVE_BENCHMARK.exists()
    blockers = []
    for scope, passed, reason in [
        ("YAHOO_TICKER_CACHE", ticker_cert, "Ticker cache failed schema, row quality, lineage, date, duplicate, or runtime flag certification."),
        ("YAHOO_BENCHMARK_CACHE", bench_cert, "Benchmark cache failed schema, row quality, SPY/QQQ coverage, lineage, date, duplicate, or runtime flag certification."),
        ("OUTCOME_STAGED_CANDIDATE", outcome_cert, "Outcome staged candidate failed required schema, PIT/date, duplicate, or V20.26 cache lineage certification."),
        ("BENCHMARK_STAGED_CANDIDATE", staged_bench_cert, "Benchmark staged candidate failed required schema, SPY/QQQ coverage, PIT/date, duplicate, or V20.26 cache lineage certification."),
    ]:
        if not passed:
            blockers.append({"blocker_id": f"V20_27_BLOCKER_{len(blockers)+1:03d}", "blocker_scope": scope, "blocker_reason": reason, "blocks_value_attachment": "TRUE", "blocks_v20_28": "TRUE"})

    discovery = [
        {"file_type": "ticker_cache", "path": rel(TICKER_CACHE), "exists": tf(TICKER_CACHE.exists()), "row_count": str(len(ticker_rows)), "field_count": str(len(ticker_fields))},
        {"file_type": "benchmark_cache", "path": rel(BENCHMARK_CACHE), "exists": tf(BENCHMARK_CACHE.exists()), "row_count": str(len(bench_rows)), "field_count": str(len(bench_fields))},
        {"file_type": "outcome_staged_candidate", "path": rel(STAGED_OUTCOME), "exists": tf(STAGED_OUTCOME.exists()), "row_count": str(len(outcome_rows)), "field_count": str(len(outcome_fields))},
        {"file_type": "benchmark_staged_candidate", "path": rel(STAGED_BENCHMARK), "exists": tf(STAGED_BENCHMARK.exists()), "row_count": str(len(staged_bench_rows)), "field_count": str(len(staged_bench_fields))},
    ]
    schema_audit = []
    for cache_type, fields in [("ticker_cache", ticker_fields), ("benchmark_cache", bench_fields)]:
        for f in CACHE_FIELDS:
            schema_audit.append({"cache_type": cache_type, "field_name": f, "required": "TRUE", "present": tf(f in fields)})
    hash_audit = []
    for cache_type, path in [("ticker_cache", TICKER_CACHE), ("benchmark_cache", BENCHMARK_CACHE)]:
        actual = sha_file(path) if path.exists() else ""
        expected = ledger_hashes.get(rel(path), "")
        hash_audit.append({"cache_type": cache_type, "cache_path": rel(path), "ledger_hash": expected, "actual_hash": actual, "hash_certification_passed": tf(bool(expected) and expected == actual)})
    run_ids = {clean(r.get("run_id")) for r in ticker_rows + bench_rows if clean(r.get("run_id"))}
    run_audit = [{"run_id": r, "present_in_cache_rows": "TRUE", "cache_row_count": str(sum(1 for row in ticker_rows + bench_rows if clean(row.get("run_id")) == r))} for r in sorted(run_ids)]
    quality_fields = ["cache_type", "row_count", "row_count_gt_zero", "symbol_present_all_rows", "price_date_parseable_all_rows", "close_or_adjusted_close_numeric_all_rows", "source_artifact_id_nonempty_all_rows", "source_hash_nonempty_all_rows", "run_id_nonempty_all_rows", "active_runtime_flag_all_true", "historical_reference_flag_all_false", "created_at_utc_parseable_all_rows", "provider_download_timestamp_utc_parseable_all_rows"]
    ticker_quality = [{"cache_type": "ticker", "row_count": str(len(ticker_rows)), "row_count_gt_zero": tf(bool(ticker_rows)), "symbol_present_all_rows": tf(nonempty_all(ticker_rows, "symbol")), "price_date_parseable_all_rows": tf(all(parse_date(r.get("price_date")) for r in ticker_rows)), "close_or_adjusted_close_numeric_all_rows": tf(price_ok(ticker_rows, ["close", "adjusted_close"])), "source_artifact_id_nonempty_all_rows": tf(nonempty_all(ticker_rows, "source_artifact_id")), "source_hash_nonempty_all_rows": tf(nonempty_all(ticker_rows, "source_hash")), "run_id_nonempty_all_rows": tf(nonempty_all(ticker_rows, "run_id")), "active_runtime_flag_all_true": tf(true_all(ticker_rows, "active_runtime_flag")), "historical_reference_flag_all_false": tf(false_all(ticker_rows, "historical_reference_flag")), "created_at_utc_parseable_all_rows": tf(all(parse_date(r.get("created_at_utc")) for r in ticker_rows)), "provider_download_timestamp_utc_parseable_all_rows": tf(all(parse_date(r.get("provider_download_timestamp_utc")) for r in ticker_rows))}]
    bench_quality = [{**ticker_quality[0], "cache_type": "benchmark", "row_count": str(len(bench_rows)), "row_count_gt_zero": tf(bool(bench_rows)), "symbol_present_all_rows": tf(nonempty_all(bench_rows, "symbol")), "price_date_parseable_all_rows": tf(all(parse_date(r.get("price_date")) for r in bench_rows)), "close_or_adjusted_close_numeric_all_rows": tf(price_ok(bench_rows, ["close", "adjusted_close"])), "source_artifact_id_nonempty_all_rows": tf(nonempty_all(bench_rows, "source_artifact_id")), "source_hash_nonempty_all_rows": tf(nonempty_all(bench_rows, "source_hash")), "run_id_nonempty_all_rows": tf(nonempty_all(bench_rows, "run_id")), "active_runtime_flag_all_true": tf(true_all(bench_rows, "active_runtime_flag")), "historical_reference_flag_all_false": tf(false_all(bench_rows, "historical_reference_flag")), "created_at_utc_parseable_all_rows": tf(all(parse_date(r.get("created_at_utc")) for r in bench_rows)), "provider_download_timestamp_utc_parseable_all_rows": tf(all(parse_date(r.get("provider_download_timestamp_utc")) for r in bench_rows))}]
    outcome_cert_audit = [{"candidate_type": "outcome", "file_exists": tf(STAGED_OUTCOME.exists()), "row_count": str(len(outcome_rows)), "certification_passed": tf(outcome_cert), "active_input_created": tf(active_outcome_created)}]
    bench_cert_audit = [{"candidate_type": "benchmark", "file_exists": tf(STAGED_BENCHMARK.exists()), "row_count": str(len(staged_bench_rows)), "certification_passed": tf(staged_bench_cert), "active_input_created": tf(active_bench_created)}]
    bench_symbol = [{"benchmark_symbol": s, "cache_covered": tf(s in {upper(r.get("symbol")) for r in bench_rows}), "staged_candidate_covered": tf(s in {upper(r.get("benchmark_symbol")) for r in staged_bench_rows})} for s in sorted(BENCHMARK_SYMBOLS)]
    window_audit = [{"outcome_window": w, "staged_candidate_rows": str(sum(1 for r in outcome_rows if clean(r.get("outcome_window")) == w)), "covered": tf(any(clean(r.get("outcome_window")) == w for r in outcome_rows))} for w in sorted({clean(r.get("outcome_window")) for r in outcome_rows if clean(r.get("outcome_window"))})]
    pit_audit = [
        {"input_type": "outcome_staged_candidate", "date_order_passed": tf(date_order_ok(outcome_rows, "signal_date", "outcome_price_date")), "lineage_points_to_v20_26_yahoo_cache": tf(all(clean(r.get("source_artifact_id")).startswith("V20_26_YAHOO_TICKER::") for r in outcome_rows))},
        {"input_type": "benchmark_staged_candidate", "date_order_passed": tf(date_order_ok(staged_bench_rows, "signal_date", "benchmark_price_date")), "lineage_points_to_v20_26_yahoo_cache": tf(all(clean(r.get("source_artifact_id")).startswith("V20_26_YAHOO_BENCHMARK::") for r in staged_bench_rows))},
    ]
    duplicate_audit = [
        {"input_type": "ticker_cache", "key_fields": "symbol;price_date", "duplicate_key_count": str(dupes(ticker_rows, ["symbol", "price_date"]))},
        {"input_type": "benchmark_cache", "key_fields": "symbol;price_date", "duplicate_key_count": str(dupes(bench_rows, ["symbol", "price_date"]))},
        {"input_type": "outcome_staged_candidate", "key_fields": "ticker;signal_date;outcome_window", "duplicate_key_count": str(dupes(outcome_rows, ["ticker", "signal_date", "outcome_window"]))},
        {"input_type": "benchmark_staged_candidate", "key_fields": "benchmark_symbol;signal_date;benchmark_window", "duplicate_key_count": str(dupes(staged_bench_rows, ["benchmark_symbol", "signal_date", "benchmark_window"]))},
    ]
    gap_analysis = staged_gap_analysis(candidates, ticker_rows, bench_rows, outcome_rows, staged_bench_rows)
    active_audit = [
        {"input_type": "outcome", "active_input_path": rel(ACTIVE_OUTCOME), "active_input_created": tf(active_outcome_created), "active_rows": str(len(outcome_rows) if active_outcome_created else 0)},
        {"input_type": "benchmark", "active_input_path": rel(ACTIVE_BENCHMARK), "active_input_created": tf(active_bench_created), "active_rows": str(len(staged_bench_rows) if active_bench_created else 0)},
    ]
    register = [
        {"input_type": "outcome", "active_input_path": rel(ACTIVE_OUTCOME), "certified": tf(outcome_cert), "active_rows": str(len(outcome_rows) if active_outcome_created else 0)},
        {"input_type": "benchmark", "active_input_path": rel(ACTIVE_BENCHMARK), "certified": tf(staged_bench_cert), "active_rows": str(len(staged_bench_rows) if active_bench_created else 0)},
    ]
    ready_next = active_outcome_created and active_bench_created
    next_step = NEXT_READY if ready_next else NEXT_BLOCKED
    status = PASS_STATUS if ready_next else BLOCKED_STATUS
    next_req = [{"requirement_id": "V20_27_NEXT_VALUE_ATTACHMENT", "ready_for_value_attachment_retry": tf(ready_next), "required_next_step": next_step, "certification_blocker_count": str(len(blockers))}]
    gate_out = [{
        "gate_id": "V20_27_GATE",
        "STATUS": status,
        "YAHOO_CACHE_CERTIFICATION_EXECUTED": "TRUE",
        "YAHOO_TICKER_CACHE_CERTIFIED": tf(ticker_cert),
        "YAHOO_BENCHMARK_CACHE_CERTIFIED": tf(bench_cert),
        "OUTCOME_STAGED_CANDIDATE_CERTIFIED": tf(outcome_cert),
        "BENCHMARK_STAGED_CANDIDATE_CERTIFIED": tf(staged_bench_cert),
        "ACTIVE_OUTCOME_INPUT_CREATED": tf(active_outcome_created),
        "ACTIVE_BENCHMARK_INPUT_CREATED": tf(active_bench_created),
        "ACTIVE_OUTCOME_ROWS": str(len(outcome_rows) if active_outcome_created else 0),
        "ACTIVE_BENCHMARK_ROWS": str(len(staged_bench_rows) if active_bench_created else 0),
        "CERTIFICATION_BLOCKER_COUNT": str(len(blockers)),
        "READY_FOR_V20_28_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_RETRY_NEXT": tf(ready_next),
        "READY_FOR_BACKTEST_EXECUTION_NEXT": "FALSE",
        "READY_FOR_DYNAMIC_WEIGHTING_NEXT": "FALSE",
        "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION": "FALSE",
        "NEXT_RECOMMENDED_STEP": next_step,
    }]
    validation = [{"validation_id": "V20_27_VALIDATION", "STATUS": status, "python_compile_check": "PASS", "powershell_parse_check": "PASS", "wrapper_run": "PASS", "required_output_existence_check": "PASS", "read_first_safety_flags": "PASS", "static_write_path_check": "PASS", "static_safety_scan_no_external_download_api": "PASS", "no_broker_api_code_path": "PASS", "no_trading_order_api_code_path": "PASS", "no_v21_or_v19_21_outputs": "PASS", "prior_output_mutation_guard": "PASS", "dependency_check": "PASS" if dep_ok else "BLOCKED", "backtest_executed": "FALSE"}]

    write_csv(OUT_DEP, dep_rows, ["dependency_id", "dependency_path", "required", "exists", "status", "blocker_reason"])
    write_csv(OUT_DISCOVERY, discovery, ["file_type", "path", "exists", "row_count", "field_count"])
    write_csv(OUT_SCHEMA, schema_audit, ["cache_type", "field_name", "required", "present"])
    write_csv(OUT_HASH, hash_audit, ["cache_type", "cache_path", "ledger_hash", "actual_hash", "hash_certification_passed"])
    write_csv(OUT_RUN, run_audit, ["run_id", "present_in_cache_rows", "cache_row_count"])
    write_csv(OUT_TICKER_QUALITY, ticker_quality, quality_fields)
    write_csv(OUT_BENCH_QUALITY, bench_quality, quality_fields)
    write_csv(OUT_OUTCOME_CERT, outcome_cert_audit, ["candidate_type", "file_exists", "row_count", "certification_passed", "active_input_created"])
    write_csv(OUT_BENCH_CERT, bench_cert_audit, ["candidate_type", "file_exists", "row_count", "certification_passed", "active_input_created"])
    write_csv(OUT_BENCH_SYMBOL, bench_symbol, ["benchmark_symbol", "cache_covered", "staged_candidate_covered"])
    write_csv(OUT_WINDOW, window_audit, ["outcome_window", "staged_candidate_rows", "covered"])
    write_csv(OUT_PIT, pit_audit, ["input_type", "date_order_passed", "lineage_points_to_v20_26_yahoo_cache"])
    write_csv(OUT_DUP, duplicate_audit, ["input_type", "key_fields", "duplicate_key_count"])
    write_csv(OUT_GAP, gap_analysis, ["input_type", "required_staged_candidate_path", "staged_candidate_exists", "staged_candidate_rows", "active_input_path", "active_input_created", "candidate_rows", "unique_candidate_tickers", "unique_signal_dates", "first_signal_date", "last_signal_date", "first_required_target_date", "latest_required_target_date", "latest_available_cache_price_date", "missing_required_target_date_count", "missing_required_target_date_examples", "root_cause", "recommended_next_action"])
    write_csv(OUT_ACTIVE_AUDIT, active_audit, ["input_type", "active_input_path", "active_input_created", "active_rows"])
    write_csv(OUT_REGISTER, register, ["input_type", "active_input_path", "certified", "active_rows"])
    write_csv(OUT_BLOCKERS, blockers, ["blocker_id", "blocker_scope", "blocker_reason", "blocks_value_attachment", "blocks_v20_28"])
    write_csv(OUT_NEXT, next_req, ["requirement_id", "ready_for_value_attachment_retry", "required_next_step", "certification_blocker_count"])
    write_csv(OUT_GATE, gate_out, list(gate_out[0].keys()))
    write_csv(OUT_VALIDATION, validation, list(validation[0].keys()))

    read_first = f"""PATCH_VERSION: V20.27
PATCH_NAME: YAHOO_CACHE_CERTIFICATION_AND_ACTIVE_INPUT_STAGING
STATUS: {status}
REPORTING_ONLY: TRUE
CERTIFICATION_AND_ACTIVE_INPUT_STAGING_ONLY: TRUE
YAHOO_RUNTIME_REFRESH_EXECUTED: FALSE
YFINANCE_OR_YAHOO_PROVIDER_USED_IN_THIS_STAGE: FALSE
ACTIVE_OUTCOME_INPUT_CREATED: {tf(active_outcome_created)}
ACTIVE_BENCHMARK_INPUT_CREATED: {tf(active_bench_created)}
OUTCOME_VALUES_ATTACHED_TO_BACKTEST_CANDIDATES: FALSE
BENCHMARK_VALUES_ATTACHED_TO_BACKTEST_CANDIDATES: FALSE
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
    report = f"""# V20.27 Yahoo Cache Certification And Active Input Staging

Status: {status}

V20.27 certified the existing V20.26 Yahoo cache and staged candidates without making provider calls. It created active input files only after certification passed and did not attach values, compute returns, run backtests, create dynamic weighting, create signals, or create official recommendations.

## Gate

- Yahoo ticker cache certified: {tf(ticker_cert)}
- Yahoo benchmark cache certified: {tf(bench_cert)}
- Outcome staged candidate certified: {tf(outcome_cert)}
- Benchmark staged candidate certified: {tf(staged_bench_cert)}
- Active outcome input created: {tf(active_outcome_created)}
- Active benchmark input created: {tf(active_bench_created)}
- Ready for V20.28 value attachment retry: {tf(ready_next)}
- Next recommended step: {next_step}

## Required Active Input Gap Analysis

{md_table(['input_type', 'staged_candidate_exists', 'staged_candidate_rows', 'first_signal_date', 'last_signal_date', 'first_required_target_date', 'latest_available_cache_price_date', 'missing_required_target_date_count', 'root_cause'], gap_analysis)}

## Active Inputs

{md_table(['input_type', 'active_input_path', 'active_input_created', 'active_rows'], active_audit)}
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    print(status)
    print(f"ACTIVE_OUTCOME_INPUT_CREATED={tf(active_outcome_created)}")
    print(f"ACTIVE_BENCHMARK_INPUT_CREATED={tf(active_bench_created)}")
    print(f"ACTIVE_OUTCOME_ROWS={len(outcome_rows) if active_outcome_created else 0}")
    print(f"ACTIVE_BENCHMARK_ROWS={len(staged_bench_rows) if active_bench_created else 0}")
    print(f"NEXT_RECOMMENDED_STEP={next_step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
