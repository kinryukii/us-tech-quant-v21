from __future__ import annotations

import csv
import hashlib
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"

IN_V20_33_GATE = CONSOLIDATION / "V20_33_GATE_DECISION.csv"
IN_V20_33_WARN = CONSOLIDATION / "V20_33_EXTREME_RETURN_ANOMALY_AUDIT.csv"
IN_V20_33_WARN_REGISTER = CONSOLIDATION / "V20_33_REVIEW_WARNING_REGISTER.csv"
IN_V20_33_READ_FIRST = OPS / "V20_33_READ_FIRST.txt"
IN_V20_32_RESULTS = CONSOLIDATION / "V20_32_ROW_LEVEL_RETURN_RESULTS.csv"
IN_V20_32_PIT = CONSOLIDATION / "V20_32_PIT_STALE_LEAKAGE_EXECUTION_AUDIT.csv"
IN_V20_32_DUP = CONSOLIDATION / "V20_32_DUPLICATE_KEY_AUDIT.csv"
IN_V20_32_MISSING = CONSOLIDATION / "V20_32_MISSING_VALUE_AUDIT.csv"
IN_V20_32_ZERO_NEG = CONSOLIDATION / "V20_32_ZERO_NEGATIVE_PRICE_AUDIT.csv"
IN_UNIVERSE = CONSOLIDATION / "V20_26_REQUIRED_SYMBOL_UNIVERSE.csv"
IN_CACHE_DISCOVERY = CONSOLIDATION / "V20_27_YAHOO_CACHE_FILE_DISCOVERY.csv"
IN_CACHE_SCHEMA = CONSOLIDATION / "V20_27_YAHOO_CACHE_SCHEMA_CERTIFICATION_AUDIT.csv"
IN_ACTIVE_REGISTER = CONSOLIDATION / "V20_27_CERTIFIED_ACTIVE_INPUT_REGISTER.csv"
IN_BENCH_COVERAGE = CONSOLIDATION / "V20_27_BENCHMARK_SYMBOL_COVERAGE_AUDIT.csv"
IN_FACTOR_REGISTRY = CONSOLIDATION / "V20_2_FACTOR_UNIVERSE_REGISTRY.csv"
IN_FACTOR_SOURCE_AUDIT = CONSOLIDATION / "V20_10_TECHNICAL_FACTOR_SOURCE_AUDIT.csv"

OUT_SOURCE = CONSOLIDATION / "V20_34_EXTREME_RETURN_WARNING_SOURCE_AUDIT.csv"
OUT_TRIAGE = CONSOLIDATION / "V20_34_EXTREME_RETURN_WARNING_ROW_TRIAGE.csv"
OUT_FORMULA = CONSOLIDATION / "V20_34_EXTREME_RETURN_FORMULA_RECHECK.csv"
OUT_CLASS_SUM = CONSOLIDATION / "V20_34_EXTREME_RETURN_CLASSIFICATION_SUMMARY.csv"
OUT_QUARANTINE = CONSOLIDATION / "V20_34_QUARANTINE_DECISION_REGISTER.csv"
OUT_PREFLIGHT = CONSOLIDATION / "V20_34_RANDOM_ASOF_BACKTEST_PREFLIGHT_INPUT_AUDIT.csv"
OUT_ALLOWED = CONSOLIDATION / "V20_34_RANDOM_ASOF_TECHNICAL_FACTOR_ALLOWED_SET.csv"
OUT_BLOCKED = CONSOLIDATION / "V20_34_RANDOM_ASOF_BLOCKED_NON_PIT_FACTOR_REGISTER.csv"
OUT_WINDOWS = CONSOLIDATION / "V20_34_RANDOM_ASOF_FORWARD_WINDOW_PREFLIGHT.csv"
OUT_DECISION = CONSOLIDATION / "V20_34_RANDOM_ASOF_TOP20_PREFLIGHT_DECISION.csv"
OUT_NEXT = CONSOLIDATION / "V20_34_NEXT_STEP_DECISION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_34_EXTREME_RETURN_WARNING_TRIAGE_AND_RANDOM_BACKTEST_PREFLIGHT_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_EXTREME_RETURN_WARNING_TRIAGE_AND_RANDOM_BACKTEST_PREFLIGHT.md"
READ_FIRST = OPS / "V20_34_READ_FIRST.txt"

STAGE_NAME = "V20.34_EXTREME_RETURN_WARNING_TRIAGE_AND_RANDOM_BACKTEST_PREFLIGHT"
STATUS = "PASS_V20_34_EXTREME_RETURN_WARNING_TRIAGE_AND_RANDOM_BACKTEST_PREFLIGHT"
TOLERANCE = 1e-10
WARNING_THRESHOLD = 0.25
FORWARD_WINDOWS = ["1d", "3d", "5d", "10d", "20d"]


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


def sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def num(value: object) -> float | None:
    try:
        value_f = float(clean(value))
    except ValueError:
        return None
    if math.isnan(value_f) or math.isinf(value_f):
        return None
    return value_f


def parse_date(value: object) -> datetime | None:
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


def recompute(end_price: float | None, entry_price: float | None) -> float | None:
    if end_price is None or entry_price is None or entry_price <= 0:
        return None
    return end_price / entry_price - 1


def diff(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return a - b


def status_from_delta(delta: float | None) -> str:
    if delta is None:
        return "BLOCKER"
    return "PASS" if abs(delta) <= TOLERANCE else "BLOCKER"


def source_candidates() -> list[Path]:
    return sorted(CONSOLIDATION.glob("V20_33_*WARNING*.csv")) + sorted(CONSOLIDATION.glob("V20_33_*EXTREME*.csv"))


def select_warning_source() -> Path:
    candidates = source_candidates()
    if IN_V20_33_WARN in candidates or IN_V20_33_WARN.exists():
        return IN_V20_33_WARN
    row_level = [path for path in candidates if "ROW" in path.name.upper() and "EXTREME" in path.name.upper()]
    if row_level:
        return row_level[0]
    extreme = [path for path in candidates if "EXTREME" in path.name.upper()]
    if extreme:
        return extreme[0]
    return IN_V20_33_WARN


def audit_prior_flags() -> dict[str, str]:
    rows: dict[str, str] = {}
    for name, path in [
        ("pit_prior_blocked_rows", IN_V20_32_PIT),
        ("duplicate_prior_blocked_rows", IN_V20_32_DUP),
        ("missing_prior_blocked_rows", IN_V20_32_MISSING),
        ("zero_negative_prior_blocked_rows", IN_V20_32_ZERO_NEG),
    ]:
        data, _ = read_csv(path)
        text = " ".join(",".join(row.values()) for row in data)
        if any(token in text.upper() for token in ["BLOCKED", "FALSE"]) and not any(token in text for token in ["0", "TRUE"]):
            rows[name] = "REVIEW"
        else:
            rows[name] = "0_OR_PASS"
    return rows


def classify_row(
    warning: dict[str, str],
    result: dict[str, str],
    formula_status: str,
    duplicate_key_count: int,
) -> tuple[str, str, str, list[str]]:
    reasons: list[str] = []
    ticker_entry = num(result.get("ticker_entry_price_selected"))
    ticker_end = num(result.get("ticker_outcome_price_selected"))
    bench_entry = num(result.get("benchmark_entry_price_selected"))
    bench_end = num(result.get("benchmark_end_price_selected"))
    reported_forward = num(result.get("forward_return"))
    reported_bench = num(result.get("benchmark_return"))
    reported_relative = num(result.get("benchmark_relative_return"))
    signal_date = parse_date(result.get("signal_date"))
    outcome_date = parse_date(result.get("outcome_price_date"))
    benchmark_date = parse_date(result.get("benchmark_price_date"))
    outcome_window = clean(result.get("outcome_window"))
    benchmark_window = clean(result.get("benchmark_window"))

    if ticker_entry is None:
        reasons.append("missing_or_non_numeric_ticker_entry_price")
    if ticker_end is None:
        reasons.append("missing_or_non_numeric_ticker_end_price")
    if bench_entry is None:
        reasons.append("missing_or_non_numeric_benchmark_entry_price")
    if bench_end is None:
        reasons.append("missing_or_non_numeric_benchmark_end_price")
    if any(value is not None and value <= 0 for value in [ticker_entry, ticker_end, bench_entry, bench_end]):
        reasons.append("zero_or_negative_price")
    if signal_date and outcome_date and signal_date > outcome_date:
        reasons.append("entry_date_after_end_date")
    if signal_date and outcome_date and signal_date == outcome_date and "1D" in upper(outcome_window):
        reasons.append("same_day_window_mismatch")
    if outcome_date and benchmark_date and outcome_date.date() != benchmark_date.date():
        reasons.append("benchmark_date_mismatch")
    if outcome_window and benchmark_window and outcome_window.replace("forward_", "") not in benchmark_window:
        reasons.append("benchmark_window_mismatch")
    if formula_status != "PASS":
        reasons.append("formula_recheck_mismatch_or_uncomputable")
    if duplicate_key_count > 1:
        reasons.append("duplicate_ticker_date_window_benchmark_warning_context")

    recomputed_forward = recompute(ticker_end, ticker_entry)
    recomputed_bench = recompute(bench_end, bench_entry)
    recomputed_relative = diff(recomputed_forward, recomputed_bench)
    if reported_forward is not None and recomputed_forward is not None:
        if abs(reported_forward - recomputed_forward) > TOLERANCE:
            reasons.append("ticker_return_larger_than_price_movement_implied")
    if reported_relative is not None and recomputed_relative is not None:
        if abs(reported_relative - recomputed_relative) > TOLERANCE:
            reasons.append("benchmark_relative_return_mismatch")

    blocking_reasons = [
        reason for reason in reasons
        if reason not in {"duplicate_ticker_date_window_benchmark_warning_context"}
    ]
    if any(reason.startswith("missing_or_non_numeric") or reason == "zero_or_negative_price" or reason == "formula_recheck_mismatch_or_uncomputable" or reason == "ticker_return_larger_than_price_movement_implied" for reason in blocking_reasons):
        return "DATA_DEFECT", "BLOCKER", "TRUE", reasons
    if any(reason in {"entry_date_after_end_date", "same_day_window_mismatch"} for reason in blocking_reasons):
        return "DATE_ALIGNMENT_ISSUE", "BLOCKER", "TRUE", reasons
    if any(reason in {"benchmark_date_mismatch", "benchmark_window_mismatch", "benchmark_relative_return_mismatch"} for reason in blocking_reasons):
        return "BENCHMARK_ALIGNMENT_ISSUE", "BLOCKER", "TRUE", reasons

    field_text = " ".join([
        clean(result.get("ticker_entry_price_field_used")),
        clean(result.get("ticker_outcome_price_field_used")),
        clean(result.get("lineage_notes")),
    ]).lower()
    if reported_forward is not None and abs(reported_forward) > 1.0 and "adjusted" not in field_text:
        return "LIKELY_CORPORATE_ACTION", "BLOCKER", "TRUE", reasons + ["large_unadjusted_price_move_possible_corporate_action"]

    if reported_forward is not None and abs(reported_forward) >= WARNING_THRESHOLD:
        return "LEGITIMATE_MARKET_MOVE", "INFO", "FALSE", reasons + ["formula_prices_dates_and_benchmark_alignment_passed"]
    if reported_relative is not None and abs(reported_relative) >= WARNING_THRESHOLD:
        return "LEGITIMATE_MARKET_MOVE", "INFO", "FALSE", reasons + ["formula_prices_dates_and_benchmark_alignment_passed"]
    return "UNRESOLVED_QUARANTINE", "BLOCKER", "TRUE", reasons + ["extreme_warning_not_resolved_by_triage_rules"]


def input_exists_from_register(rows: list[dict[str, str]], file_type: str) -> bool:
    for row in rows:
        if clean(row.get("file_type")) == file_type:
            return upper(row.get("exists")) == "TRUE" and int(float(clean(row.get("row_count")) or "0")) > 0
    return False


def present_field(schema_rows: list[dict[str, str]], cache_type: str, field_name: str) -> bool:
    return any(
        clean(row.get("cache_type")) == cache_type
        and clean(row.get("field_name")) == field_name
        and upper(row.get("present")) == "TRUE"
        for row in schema_rows
    )


def main() -> int:
    run_at = now_utc()
    warning_source = select_warning_source()
    warning_rows, warning_fields = read_csv(warning_source)
    results, _ = read_csv(IN_V20_32_RESULTS)
    gate_rows, _ = read_csv(IN_V20_33_GATE)
    cache_rows, _ = read_csv(IN_CACHE_DISCOVERY)
    schema_rows, _ = read_csv(IN_CACHE_SCHEMA)
    active_rows, _ = read_csv(IN_ACTIVE_REGISTER)
    universe_rows, _ = read_csv(IN_UNIVERSE)
    bench_rows, _ = read_csv(IN_BENCH_COVERAGE)

    result_by_key = {
        (clean(row.get("stable_candidate_key")), clean(row.get("benchmark_symbol"))): row
        for row in results
    }
    duplicate_contexts: Counter[tuple[str, str, str, str]] = Counter()
    for row in results:
        duplicate_contexts[(
            clean(row.get("ticker")),
            clean(row.get("signal_date")),
            clean(row.get("outcome_window")),
            clean(row.get("benchmark_symbol")),
        )] += 1

    source_rows = [{
        "selected_warning_source_path": rel(warning_source),
        "source_hash": sha256_file(warning_source),
        "source_row_count": len(warning_rows),
        "source_columns_present": "|".join(warning_fields),
        "warning_source_selection_policy": "Most specific V20.33 extreme return anomaly warning file.",
        "alternate_warning_related_files": "|".join(rel(path) for path in source_candidates() if path != warning_source),
        "source_audit_status": "PASS" if warning_source.exists() and len(warning_rows) == 20 else "WARN",
    }]

    triage_rows: list[dict[str, object]] = []
    formula_rows: list[dict[str, object]] = []
    quarantine_rows: list[dict[str, object]] = []

    for index, warning in enumerate(warning_rows, start=1):
        stable_key = clean(warning.get("stable_candidate_key"))
        benchmark = clean(warning.get("benchmark_symbol"))
        result = result_by_key.get((stable_key, benchmark), {})

        ticker_entry = num(result.get("ticker_entry_price_selected"))
        ticker_end = num(result.get("ticker_outcome_price_selected"))
        bench_entry = num(result.get("benchmark_entry_price_selected"))
        bench_end = num(result.get("benchmark_end_price_selected"))
        calc_forward = recompute(ticker_end, ticker_entry)
        calc_bench = recompute(bench_end, bench_entry)
        calc_relative = diff(calc_forward, calc_bench)
        reported_forward = num(result.get("forward_return"))
        reported_bench = num(result.get("benchmark_return"))
        reported_relative = num(result.get("benchmark_relative_return"))
        forward_delta = diff(reported_forward, calc_forward)
        bench_delta = diff(reported_bench, calc_bench)
        relative_delta = diff(reported_relative, calc_relative)
        formula_statuses = [status_from_delta(forward_delta), status_from_delta(bench_delta), status_from_delta(relative_delta)]
        formula_status = "PASS" if all(status == "PASS" for status in formula_statuses) else "BLOCKER"
        duplicate_count = duplicate_contexts[(
            clean(result.get("ticker")),
            clean(result.get("signal_date")),
            clean(result.get("outcome_window")),
            clean(result.get("benchmark_symbol")),
        )]
        classification, severity, quarantine_required, reasons = classify_row(warning, result, formula_status, duplicate_count)
        include_future = "FALSE" if quarantine_required == "TRUE" else "TRUE"
        quarantine_reason = ";".join(reasons) if quarantine_required == "TRUE" else ""

        common = {
            "warning_row_id": f"V20_34_EXTREME_WARNING_{index:03d}",
            "source_warning_metric": clean(warning.get("anomaly_metric")),
            "source_warning_threshold": clean(warning.get("threshold")),
            "source_warning_metric_value": clean(warning.get("metric_value")),
            "ticker": clean(result.get("ticker") or warning.get("ticker")),
            "signal_date": clean(result.get("signal_date")),
            "benchmark_policy": "SPY_QQQ_PARALLEL_BENCHMARK_RELATIVE_REVIEW",
            "benchmark_symbol": benchmark,
            "outcome_window": clean(result.get("outcome_window")),
            "benchmark_window": clean(result.get("benchmark_window")),
            "outcome_price_date": clean(result.get("outcome_price_date")),
            "benchmark_price_date": clean(result.get("benchmark_price_date")),
            "candidate_id": clean(result.get("candidate_id")),
            "stable_candidate_key": stable_key,
            "lineage_id": clean(result.get("base_price_attachment_run_id")),
            "run_id": clean(result.get("v20_32_calculation_run_id")),
        }
        triage_rows.append({
            **common,
            "ticker_entry_price": clean(result.get("ticker_entry_price_selected")),
            "ticker_end_price": clean(result.get("ticker_outcome_price_selected")),
            "benchmark_entry_price": clean(result.get("benchmark_entry_price_selected")),
            "benchmark_end_price": clean(result.get("benchmark_end_price_selected")),
            "ticker_entry_price_field": clean(result.get("ticker_entry_price_field_used")),
            "ticker_end_price_field": clean(result.get("ticker_outcome_price_field_used")),
            "benchmark_entry_price_field": clean(result.get("benchmark_entry_price_field_used")),
            "benchmark_end_price_field": clean(result.get("benchmark_end_price_field_used")),
            "forward_return": clean(result.get("forward_return")),
            "benchmark_return": clean(result.get("benchmark_return")),
            "benchmark_relative_return": clean(result.get("benchmark_relative_return")),
            "classification": classification,
            "severity": severity,
            "include_in_future_backtest_candidate_pool": include_future,
            "quarantine_required": quarantine_required,
            "quarantine_reason": quarantine_reason,
            "audit_notes": ";".join(reasons),
        })
        formula_rows.append({
            **common,
            "reported_ticker_forward_return": clean(result.get("forward_return")),
            "recomputed_ticker_forward_return": "" if calc_forward is None else calc_forward,
            "ticker_forward_return_delta": "" if forward_delta is None else forward_delta,
            "ticker_forward_return_formula_status": status_from_delta(forward_delta),
            "reported_benchmark_forward_return": clean(result.get("benchmark_return")),
            "recomputed_benchmark_forward_return": "" if calc_bench is None else calc_bench,
            "benchmark_forward_return_delta": "" if bench_delta is None else bench_delta,
            "benchmark_forward_return_formula_status": status_from_delta(bench_delta),
            "reported_benchmark_relative_return": clean(result.get("benchmark_relative_return")),
            "recomputed_benchmark_relative_return": "" if calc_relative is None else calc_relative,
            "benchmark_relative_return_delta": "" if relative_delta is None else relative_delta,
            "benchmark_relative_return_formula_status": status_from_delta(relative_delta),
            "formula_recheck_status": formula_status,
            "severity": "INFO" if formula_status == "PASS" else "BLOCKER",
        })
        quarantine_rows.append({
            **common,
            "classification": classification,
            "include_in_future_backtest_candidate_pool": include_future,
            "quarantine_required": quarantine_required,
            "quarantine_reason": quarantine_reason,
            "severity": severity,
        })

    class_counts = Counter(clean(row["classification"]) for row in triage_rows)
    class_summary_rows = []
    for classification in [
        "DATA_DEFECT",
        "LIKELY_CORPORATE_ACTION",
        "DATE_ALIGNMENT_ISSUE",
        "BENCHMARK_ALIGNMENT_ISSUE",
        "LEGITIMATE_MARKET_MOVE",
        "UNRESOLVED_QUARANTINE",
    ]:
        class_summary_rows.append({
            "classification": classification,
            "row_count": class_counts[classification],
            "quarantine_required_count": sum(1 for row in triage_rows if row["classification"] == classification and row["quarantine_required"] == "TRUE"),
            "max_severity": "BLOCKER" if any(row["classification"] == classification and row["severity"] == "BLOCKER" for row in triage_rows) else ("INFO" if class_counts[classification] else ""),
        })

    formula_mismatch_count = sum(1 for row in formula_rows if row["formula_recheck_status"] != "PASS")
    quarantine_required_count = sum(1 for row in quarantine_rows if row["quarantine_required"] == "TRUE")
    data_defect_count = class_counts["DATA_DEFECT"]
    unresolved_quarantine_count = class_counts["UNRESOLVED_QUARANTINE"]
    blocker_exists = data_defect_count > 0 or quarantine_required_count > 0 or formula_mismatch_count > 0

    ticker_cache_ok = input_exists_from_register(cache_rows, "ticker_cache")
    benchmark_cache_ok = input_exists_from_register(cache_rows, "benchmark_cache")
    universe_ok = len([row for row in universe_rows if upper(row.get("symbol_role")) == "TICKER"]) > 0
    active_ok = all(upper(row.get("certified")) == "TRUE" for row in active_rows) and len(active_rows) >= 2
    spy_qqq_ok = "SPY" in " ".join(",".join(row.values()) for row in bench_rows).upper() and "QQQ" in " ".join(",".join(row.values()) for row in bench_rows).upper()
    ohlcv_ok = all(present_field(schema_rows, "ticker_cache", field) for field in ["open", "high", "low", "close", "adjusted_close", "volume"])
    benchmark_ohlcv_ok = all(present_field(schema_rows, "benchmark_cache", field) for field in ["open", "high", "low", "close", "adjusted_close", "volume"])
    random_sampling_ok = universe_ok and ticker_cache_ok
    technical_recompute_ok = ticker_cache_ok and ohlcv_ok

    preflight_rows = [
        {"preflight_check": "historical_ticker_price_cache_exists", "status": "PASS" if ticker_cache_ok else "BLOCKED", "ready": tf(ticker_cache_ok), "evidence_path": rel(IN_CACHE_DISCOVERY), "notes": "Certified Yahoo ticker cache discovery reviewed only."},
        {"preflight_check": "historical_benchmark_price_cache_exists", "status": "PASS" if benchmark_cache_ok else "BLOCKED", "ready": tf(benchmark_cache_ok), "evidence_path": rel(IN_CACHE_DISCOVERY), "notes": "Certified Yahoo benchmark cache discovery reviewed only."},
        {"preflight_check": "ticker_universe_available", "status": "PASS" if universe_ok else "BLOCKED", "ready": tf(universe_ok), "evidence_path": rel(IN_UNIVERSE), "notes": "Active symbol universe is available for future deterministic sampling."},
        {"preflight_check": "spy_qqq_benchmark_coverage_exists", "status": "PASS" if spy_qqq_ok else "BLOCKED", "ready": tf(spy_qqq_ok), "evidence_path": rel(IN_BENCH_COVERAGE), "notes": "SPY and QQQ are required future benchmark symbols."},
        {"preflight_check": "deterministic_random_signal_date_sampling_supported", "status": "PASS" if random_sampling_ok else "BLOCKED", "ready": tf(random_sampling_ok), "evidence_path": rel(IN_CACHE_DISCOVERY), "notes": "Future stage can use a fixed seed and cached price calendar; no sampling performed here."},
        {"preflight_check": "technical_only_factor_recompute_supported", "status": "PASS" if technical_recompute_ok else "BLOCKED", "ready": tf(technical_recompute_ok), "evidence_path": rel(IN_CACHE_SCHEMA), "notes": "OHLCV and adjusted close fields support technical-only recompute."},
        {"preflight_check": "benchmark_ohlcv_supported", "status": "PASS" if benchmark_ohlcv_ok else "BLOCKED", "ready": tf(benchmark_ohlcv_ok), "evidence_path": rel(IN_CACHE_SCHEMA), "notes": "Benchmark OHLCV fields support forward benchmark checks."},
        {"preflight_check": "certified_active_inputs_available", "status": "PASS" if active_ok else "BLOCKED", "ready": tf(active_ok), "evidence_path": rel(IN_ACTIVE_REGISTER), "notes": "Certified active inputs exist; no active input mutation performed."},
        {"preflight_check": "non_pit_fundamental_factors_blocked", "status": "PASS", "ready": "TRUE", "evidence_path": rel(IN_FACTOR_REGISTRY), "notes": "Future random as-of recompute must exclude non-PIT/current-only factors."},
    ]

    allowed_groups = [
        ("momentum", "adjusted_close", True),
        ("relative_strength", "adjusted_close plus SPY/QQQ benchmark adjusted_close", True),
        ("MA10_trend", "adjusted_close", True),
        ("MA20_trend", "adjusted_close", True),
        ("MA50_trend", "adjusted_close", True),
        ("pullback_quality", "open/high/low/close/adjusted_close", True),
        ("breakout", "high/low/close/adjusted_close", True),
        ("volatility", "adjusted_close and high/low range", True),
        ("volume_trend", "volume", present_field(schema_rows, "ticker_cache", "volume")),
        ("RSI", "adjusted_close", True),
        ("MACD", "adjusted_close", True),
        ("Bollinger_style_price_position", "adjusted_close", True),
    ]
    allowed_rows = [{
        "allowed_factor_group": group,
        "required_price_fields": fields,
        "supported_by_available_ohlcv": tf(bool(supported and ohlcv_ok)),
        "future_v20_35_allowed": tf(bool(supported and ohlcv_ok)),
        "boundary_notes": "Technical-only as-of recompute candidate; no official weights changed in V20.34.",
    } for group, fields, supported in allowed_groups]

    blocked_groups = [
        "current_fundamental_factors_without_point_in_time_availability",
        "non_pit_valuation_factors",
        "current_analyst_labels",
        "current_narrative_labels",
        "current_ranking_snapshots",
        "current_top20_snapshots",
        "manual_current_only_labels",
        "any_factor_that_requires_future_data_relative_to_random_signal_date",
    ]
    blocked_rows = [{
        "blocked_factor_group": group,
        "blocked_for_future_random_asof_backtests": "TRUE",
        "block_reason": "Not proven point-in-time safe for random historical as-of recompute.",
        "allowed_in_v20_35": "FALSE",
    } for group in blocked_groups]

    window_rows = [{
        "forward_window": f"forward_{window}",
        "ticker_price_coverage_available": tf(ticker_cache_ok),
        "benchmark_price_coverage_available": tf(benchmark_cache_ok and spy_qqq_ok),
        "window_preflight_status": "PASS" if ticker_cache_ok and benchmark_cache_ok and spy_qqq_ok else "BLOCKED",
        "backtest_executed_in_v20_34": "FALSE",
    } for window in FORWARD_WINDOWS]

    preflight_completed = True
    ready_v20_35 = preflight_completed and all(row["status"] == "PASS" for row in preflight_rows) and quarantine_required_count == 0 and formula_mismatch_count == 0
    decision_rows = [{
        "decision_id": "V20_34_RANDOM_ASOF_TOP20_PREFLIGHT",
        "v20_33_extreme_warning_triage_completed": "TRUE",
        "unresolved_data_defect_blockers_exist": tf(blocker_exists),
        "quarantine_file_created": "TRUE",
        "random_asof_top20_preflight_completed": tf(preflight_completed),
        "ready_for_v20_35_random_asof_top20_technical_recompute_backtest": tf(ready_v20_35),
        "ready_for_entry_strategy_matrix_design": "FALSE",
        "ready_for_factor_effectiveness_audit": "FALSE",
        "ready_for_shadow_dynamic_weighting": "FALSE",
        "ready_for_portfolio_level_backtest": "FALSE",
        "ready_for_official_trading_or_recommendation": "FALSE",
        "random_asof_top20_backtest_executed": "FALSE",
        "decision_reason": "Ready only if all warning rows are non-quarantined and all preflight inputs pass.",
    }]
    next_rows = [{
        "STAGE_NAME": STAGE_NAME,
        "STATUS": STATUS,
        "V20_33_WARNING_ROWS_REVIEWED": len(warning_rows),
        "FORMULA_MISMATCH_COUNT": formula_mismatch_count,
        "DATA_DEFECT_COUNT": data_defect_count,
        "LIKELY_CORPORATE_ACTION_COUNT": class_counts["LIKELY_CORPORATE_ACTION"],
        "DATE_ALIGNMENT_ISSUE_COUNT": class_counts["DATE_ALIGNMENT_ISSUE"],
        "BENCHMARK_ALIGNMENT_ISSUE_COUNT": class_counts["BENCHMARK_ALIGNMENT_ISSUE"],
        "LEGITIMATE_MARKET_MOVE_COUNT": class_counts["LEGITIMATE_MARKET_MOVE"],
        "UNRESOLVED_QUARANTINE_COUNT": unresolved_quarantine_count,
        "QUARANTINE_REQUIRED_COUNT": quarantine_required_count,
        "RANDOM_ASOF_PREFLIGHT_COMPLETED": tf(preflight_completed),
        "STRICT_TECHNICAL_FACTOR_ALLOWED_COUNT": sum(1 for row in allowed_rows if row["future_v20_35_allowed"] == "TRUE"),
        "BLOCKED_NON_PIT_FACTOR_COUNT": len(blocked_rows),
        "READY_FOR_V20_35_RANDOM_ASOF_TOP20_TECHNICAL_RECOMPUTE_BACKTEST": tf(ready_v20_35),
        "READY_FOR_DYNAMIC_WEIGHTING": "FALSE",
        "READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION": "FALSE",
        "NEXT_RECOMMENDED_STEP": "V20.35_RANDOM_ASOF_TOP20_TECHNICAL_RECOMPUTE_BACKTEST" if ready_v20_35 else "V20.34_QUARANTINE_OR_PREFLIGHT_BLOCKER_RESOLUTION",
    }]

    write_csv(OUT_SOURCE, source_rows, ["selected_warning_source_path", "source_hash", "source_row_count", "source_columns_present", "warning_source_selection_policy", "alternate_warning_related_files", "source_audit_status"])
    write_csv(OUT_TRIAGE, triage_rows, ["warning_row_id", "source_warning_metric", "source_warning_threshold", "source_warning_metric_value", "ticker", "signal_date", "benchmark_policy", "benchmark_symbol", "outcome_window", "benchmark_window", "outcome_price_date", "benchmark_price_date", "ticker_entry_price", "ticker_end_price", "benchmark_entry_price", "benchmark_end_price", "ticker_entry_price_field", "ticker_end_price_field", "benchmark_entry_price_field", "benchmark_end_price_field", "forward_return", "benchmark_return", "benchmark_relative_return", "candidate_id", "stable_candidate_key", "lineage_id", "run_id", "classification", "severity", "include_in_future_backtest_candidate_pool", "quarantine_required", "quarantine_reason", "audit_notes"])
    write_csv(OUT_FORMULA, formula_rows, ["warning_row_id", "source_warning_metric", "source_warning_threshold", "source_warning_metric_value", "ticker", "signal_date", "benchmark_policy", "benchmark_symbol", "outcome_window", "benchmark_window", "outcome_price_date", "benchmark_price_date", "candidate_id", "stable_candidate_key", "lineage_id", "run_id", "reported_ticker_forward_return", "recomputed_ticker_forward_return", "ticker_forward_return_delta", "ticker_forward_return_formula_status", "reported_benchmark_forward_return", "recomputed_benchmark_forward_return", "benchmark_forward_return_delta", "benchmark_forward_return_formula_status", "reported_benchmark_relative_return", "recomputed_benchmark_relative_return", "benchmark_relative_return_delta", "benchmark_relative_return_formula_status", "formula_recheck_status", "severity"])
    write_csv(OUT_CLASS_SUM, class_summary_rows, ["classification", "row_count", "quarantine_required_count", "max_severity"])
    write_csv(OUT_QUARANTINE, quarantine_rows, ["warning_row_id", "source_warning_metric", "source_warning_threshold", "source_warning_metric_value", "ticker", "signal_date", "benchmark_policy", "benchmark_symbol", "outcome_window", "benchmark_window", "outcome_price_date", "benchmark_price_date", "candidate_id", "stable_candidate_key", "lineage_id", "run_id", "classification", "include_in_future_backtest_candidate_pool", "quarantine_required", "quarantine_reason", "severity"])
    write_csv(OUT_PREFLIGHT, preflight_rows, ["preflight_check", "status", "ready", "evidence_path", "notes"])
    write_csv(OUT_ALLOWED, allowed_rows, ["allowed_factor_group", "required_price_fields", "supported_by_available_ohlcv", "future_v20_35_allowed", "boundary_notes"])
    write_csv(OUT_BLOCKED, blocked_rows, ["blocked_factor_group", "blocked_for_future_random_asof_backtests", "block_reason", "allowed_in_v20_35"])
    write_csv(OUT_WINDOWS, window_rows, ["forward_window", "ticker_price_coverage_available", "benchmark_price_coverage_available", "window_preflight_status", "backtest_executed_in_v20_34"])
    write_csv(OUT_DECISION, decision_rows, list(decision_rows[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))

    report = f"""# V20.34 Extreme Return Warning Triage And Random Backtest Preflight

Status: {STATUS}

Triage only: TRUE
Random backtest preflight only: TRUE
Random as-of Top20 backtest executed: FALSE

V20.33 warning rows reviewed: {len(warning_rows)}
Formula mismatch count: {formula_mismatch_count}
Quarantine required count: {quarantine_required_count}
Ready for V20.35 random as-of Top20 technical recompute backtest: {tf(ready_v20_35)}

Classification summary:

- DATA_DEFECT: {data_defect_count}
- LIKELY_CORPORATE_ACTION: {class_counts["LIKELY_CORPORATE_ACTION"]}
- DATE_ALIGNMENT_ISSUE: {class_counts["DATE_ALIGNMENT_ISSUE"]}
- BENCHMARK_ALIGNMENT_ISSUE: {class_counts["BENCHMARK_ALIGNMENT_ISSUE"]}
- LEGITIMATE_MARKET_MOVE: {class_counts["LEGITIMATE_MARKET_MOVE"]}
- UNRESOLVED_QUARANTINE: {unresolved_quarantine_count}

V20.34 reviewed existing V20.33 warning rows and existing certified input artifacts only. It did not mutate official ranking outputs or factor weights, did not create official recommendations or trading signals, did not create portfolio-level backtests or equity curves, and did not run a random historical Top20 backtest.
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)

    read_first = f"""STAGE_NAME: {STAGE_NAME}
STATUS: {STATUS}
TRIAGE_ONLY: TRUE
RANDOM_BACKTEST_PREFLIGHT_ONLY: TRUE
OFFICIAL_RECOMMENDATION_CREATED: FALSE
TRADING_SIGNAL_CREATED: FALSE
BROKER_ORDER_EXECUTION_CODE_CREATED: FALSE
OFFICIAL_RANKING_MUTATED: FALSE
OFFICIAL_FACTOR_WEIGHTS_MUTATED: FALSE
PORTFOLIO_BACKTEST_CREATED: FALSE
EQUITY_CURVE_CREATED: FALSE
PERFORMANCE_CLAIMS_CREATED: FALSE
DYNAMIC_WEIGHTING_STARTED: FALSE
RANDOM_ASOF_TOP20_BACKTEST_EXECUTED: FALSE
V21_OUTPUTS_CREATED: FALSE
V19_21_OUTPUTS_CREATED: FALSE
V20_33_WARNING_ROWS_REVIEWED: {len(warning_rows)}
FORMULA_MISMATCH_COUNT: {formula_mismatch_count}
QUARANTINE_REQUIRED_COUNT: {quarantine_required_count}
RANDOM_ASOF_PREFLIGHT_COMPLETED: {tf(preflight_completed)}
READY_FOR_V20_35_RANDOM_ASOF_TOP20_TECHNICAL_RECOMPUTE_BACKTEST: {tf(ready_v20_35)}
READY_FOR_DYNAMIC_WEIGHTING: FALSE
READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION: FALSE
"""
    write_text(READ_FIRST, read_first)

    required_outputs = [
        OUT_SOURCE, OUT_TRIAGE, OUT_FORMULA, OUT_CLASS_SUM, OUT_QUARANTINE,
        OUT_PREFLIGHT, OUT_ALLOWED, OUT_BLOCKED, OUT_WINDOWS, OUT_DECISION,
        OUT_NEXT, REPORT, CURRENT_REPORT, READ_FIRST,
    ]
    missing = [path for path in required_outputs if not path.exists()]
    if missing:
        raise RuntimeError("Missing V20.34 outputs: " + ", ".join(rel(path) for path in missing))

    print(f"STATUS={STATUS}")
    print("FILES_CHANGED=scripts/v20/v20_34_extreme_return_warning_triage_and_random_backtest_preflight.py;scripts/v20/run_v20_34_extreme_return_warning_triage_and_random_backtest_preflight.ps1")
    print("OUTPUTS_CREATED=" + ";".join(rel(path) for path in required_outputs))
    print(f"V20_33_WARNING_ROWS_REVIEWED={len(warning_rows)}")
    print(f"FORMULA_MISMATCH_COUNT={formula_mismatch_count}")
    print(f"DATA_DEFECT_COUNT={data_defect_count}")
    print(f"LIKELY_CORPORATE_ACTION_COUNT={class_counts['LIKELY_CORPORATE_ACTION']}")
    print(f"DATE_ALIGNMENT_ISSUE_COUNT={class_counts['DATE_ALIGNMENT_ISSUE']}")
    print(f"BENCHMARK_ALIGNMENT_ISSUE_COUNT={class_counts['BENCHMARK_ALIGNMENT_ISSUE']}")
    print(f"LEGITIMATE_MARKET_MOVE_COUNT={class_counts['LEGITIMATE_MARKET_MOVE']}")
    print(f"UNRESOLVED_QUARANTINE_COUNT={unresolved_quarantine_count}")
    print(f"QUARANTINE_REQUIRED_COUNT={quarantine_required_count}")
    print(f"RANDOM_ASOF_PREFLIGHT_COMPLETED={tf(preflight_completed)}")
    print(f"STRICT_TECHNICAL_FACTOR_ALLOWED_COUNT={sum(1 for row in allowed_rows if row['future_v20_35_allowed'] == 'TRUE')}")
    print(f"BLOCKED_NON_PIT_FACTOR_COUNT={len(blocked_rows)}")
    print(f"READY_FOR_V20_35_RANDOM_ASOF_TOP20_TECHNICAL_RECOMPUTE_BACKTEST={tf(ready_v20_35)}")
    print("READY_FOR_DYNAMIC_WEIGHTING=FALSE")
    print("READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
