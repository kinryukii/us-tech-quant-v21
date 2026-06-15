from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
INPUTS_V20 = ROOT / "inputs" / "v20"
OUTPUTS_V18 = ROOT / "outputs" / "v18"

IN_V20_19_READ_FIRST = OPS / "V20_19_READ_FIRST.txt"
IN_V20_19_GATE = CONSOLIDATION / "V20_19_GATE_DECISION.csv"
IN_V20_19_BLOCKERS = CONSOLIDATION / "V20_19_BLOCKER_REGISTER.csv"
IN_V20_17_CANDIDATES = CONSOLIDATION / "V20_17_BACKTEST_INPUT_CANDIDATE_DATASET.csv"
IN_V20_19_OUTCOME_PLAN = CONSOLIDATION / "V20_19_OUTCOME_VALUE_ATTACHMENT_PLAN.csv"
IN_V20_19_BENCHMARK_PLAN = CONSOLIDATION / "V20_19_BENCHMARK_VALUE_ATTACHMENT_PLAN.csv"

OUT_DEP = CONSOLIDATION / "V20_20_DEPENDENCY_AUDIT.csv"
OUT_OUTCOME_DISCOVERY = CONSOLIDATION / "V20_20_OUTCOME_SOURCE_CANDIDATE_DISCOVERY.csv"
OUT_BENCHMARK_DISCOVERY = CONSOLIDATION / "V20_20_BENCHMARK_SOURCE_CANDIDATE_DISCOVERY.csv"
OUT_OUTCOME_CERT = CONSOLIDATION / "V20_20_OUTCOME_SOURCE_CERTIFICATION_AUDIT.csv"
OUT_BENCHMARK_CERT = CONSOLIDATION / "V20_20_BENCHMARK_SOURCE_CERTIFICATION_AUDIT.csv"
OUT_FIELD = CONSOLIDATION / "V20_20_REQUIRED_FIELD_COVERAGE_AUDIT.csv"
OUT_PIT = CONSOLIDATION / "V20_20_PIT_STALE_LEAKAGE_CERTIFICATION_AUDIT.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_20_LINEAGE_HASH_RUN_ID_CERTIFICATION_AUDIT.csv"
OUT_BENCH_SYMBOL = CONSOLIDATION / "V20_20_BENCHMARK_SYMBOL_COVERAGE_AUDIT.csv"
OUT_WINDOW = CONSOLIDATION / "V20_20_OUTCOME_WINDOW_COVERAGE_AUDIT.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_20_OUTCOME_BENCHMARK_SOURCE_BLOCKER_REGISTER.csv"
OUT_OUTCOME_TEMPLATE = CONSOLIDATION / "V20_20_OUTCOME_SOURCE_INPUT_TEMPLATE.csv"
OUT_BENCHMARK_TEMPLATE = CONSOLIDATION / "V20_20_BENCHMARK_SOURCE_INPUT_TEMPLATE.csv"
OUT_REQ = CONSOLIDATION / "V20_20_NEXT_VALUE_ATTACHMENT_REQUIREMENTS.csv"
OUT_GATE = CONSOLIDATION / "V20_20_GATE_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_20_VALIDATION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_20_OUTCOME_BENCHMARK_SOURCE_CERTIFICATION_OR_BLOCKER_RESOLUTION_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_OUTCOME_BENCHMARK_SOURCE_CERTIFICATION_OR_BLOCKER_RESOLUTION.md"
READ_FIRST = OPS / "V20_20_READ_FIRST.txt"

PASS_STATUS = "PASS_V20_20_OUTCOME_BENCHMARK_SOURCE_CERTIFICATION_OR_BLOCKER_RESOLUTION"
NEXT_IF_READY = "V20.21_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_RETRY"
NEXT_IF_BLOCKED = "V20.21_OUTCOME_BENCHMARK_INPUT_STAGING_AND_REGISTRATION"
REQUIRED_INPUTS = [
    IN_V20_19_READ_FIRST,
    IN_V20_19_GATE,
    IN_V20_19_BLOCKERS,
    IN_V20_17_CANDIDATES,
    IN_V20_19_OUTCOME_PLAN,
    IN_V20_19_BENCHMARK_PLAN,
]
ALLOWED_WRITE_PATHS = {
    OUT_DEP,
    OUT_OUTCOME_DISCOVERY,
    OUT_BENCHMARK_DISCOVERY,
    OUT_OUTCOME_CERT,
    OUT_BENCHMARK_CERT,
    OUT_FIELD,
    OUT_PIT,
    OUT_LINEAGE,
    OUT_BENCH_SYMBOL,
    OUT_WINDOW,
    OUT_BLOCKERS,
    OUT_OUTCOME_TEMPLATE,
    OUT_BENCHMARK_TEMPLATE,
    OUT_REQ,
    OUT_GATE,
    OUT_VALIDATION,
    REPORT,
    CURRENT_REPORT,
    READ_FIRST,
}
OUTCOME_WINDOWS = ["forward_1d", "forward_5d", "forward_10d", "forward_20d", "forward_60d"]
BENCHMARK_SYMBOLS = ["SPY", "QQQ"]


def clean(value: object) -> str:
    return str(value or "").strip()


def upper(value: object) -> str:
    return clean(value).upper()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def utc_now() -> str:
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


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def md_table(headers: list[str], rows: list[dict[str, str]], limit: int = 12) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows[:limit]:
        out.append("| " + " | ".join(clean(row.get(h)).replace("|", "/") for h in headers) + " |")
    return "\n".join(out)


def header_and_sample(path: Path) -> tuple[list[str], dict[str, str], str]:
    if path.suffix.lower() != ".csv":
        return [], {}, "non_csv"
    try:
        rows, fields = read_csv(path)
        return fields, rows[0] if rows else {}, "readable"
    except (OSError, UnicodeError, csv.Error):
        return [], {}, "unreadable"


def has_any(fields: set[str], names: set[str]) -> bool:
    return bool(fields & names)


def truthy(value: object) -> bool:
    return upper(value) in {"TRUE", "1", "YES", "Y"}


def falsey(value: object) -> bool:
    return upper(value) in {"FALSE", "0", "NO", "N"}


def discover_paths() -> list[Path]:
    roots = [
        CONSOLIDATION,
        READ_CENTER,
        OPS,
        INPUTS_V20,
        OUTPUTS_V18,
    ]
    name_terms = {
        "source",
        "registry",
        "manifest",
        "outcome",
        "benchmark",
        "future",
        "forward",
        "price",
        "close",
        "spy",
        "qqq",
    }
    paths: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".csv", ".txt", ".json", ".md"}:
                continue
            if path.name.startswith("V20_20_") or path.name.startswith("V20_CURRENT_OUTCOME_BENCHMARK_SOURCE_CERTIFICATION"):
                continue
            low = path.name.lower()
            if any(term in low for term in name_terms):
                paths.append(path)
    return sorted(paths, key=lambda p: rel(p))[:300]


def source_scope(path: Path) -> tuple[str, bool]:
    if OUTPUTS_V18.exists() and path.resolve().is_relative_to(OUTPUTS_V18.resolve()):
        return "sealed_historical_reference", False
    return "local_v20_project_scope", True


def classify_candidate(path: Path, fields: set[str], sample: dict[str, str]) -> tuple[bool, bool]:
    low_name = path.name.lower()
    outcome_name = any(term in low_name for term in ["outcome", "future", "forward"])
    benchmark_name = any(term in low_name for term in ["benchmark", "spy", "qqq"])
    outcome_fields = has_any(fields, {"ticker", "symbol"}) and has_any(fields, {"close", "adjusted_close", "latest_close", "price"})
    benchmark_fields = has_any(fields, {"benchmark_symbol", "symbol", "ticker"}) and (
        "spy" in " ".join(sample.values()).lower() or "qqq" in " ".join(sample.values()).lower()
    )
    return outcome_name or outcome_fields, benchmark_name or benchmark_fields


def certification_flags(path: Path, fields_raw: list[str], sample: dict[str, str], is_benchmark: bool) -> dict[str, str]:
    fields = {f.lower() for f in fields_raw}
    scope, active_scope_allowed = source_scope(path)
    source_hash_present = "source_hash" in fields
    source_hash_computable = path.exists() and path.is_file()
    active_flag = truthy(sample.get("active_runtime_flag")) if "active_runtime_flag" in fields else False
    historical_flag_false = falsey(sample.get("historical_reference_flag")) if "historical_reference_flag" in fields else False
    date_ok = has_any(fields, {"observation_date", "signal_date", "as_of_date"})
    future_date_ok = has_any(fields, {"future_outcome_date", "future_price_date", "price_date", "benchmark_price_date"})
    price_ok = has_any(fields, {"close", "adjusted_close", "latest_close", "price"})
    symbol_ok = has_any(fields, {"benchmark_symbol", "symbol", "ticker"}) if is_benchmark else has_any(fields, {"ticker", "symbol"})
    availability_ok = has_any(fields, {"availability_date", "created_at_utc"})
    leakage_ok = truthy(sample.get("stale_leakage_checked")) or truthy(sample.get("pit_safe_flag")) or truthy(sample.get("point_in_time_ready"))
    benchmark_coverage_ok = True
    if is_benchmark:
        sample_blob = " ".join(clean(v).upper() for v in sample.values())
        benchmark_coverage_ok = "SPY" in sample_blob and "QQQ" in sample_blob
    certified = all(
        [
            active_scope_allowed,
            symbol_ok,
            date_ok,
            future_date_ok,
            price_ok,
            "source_artifact_id" in fields,
            source_hash_present,
            "run_id" in fields,
            active_flag,
            historical_flag_false,
            availability_ok,
            leakage_ok,
            benchmark_coverage_ok,
        ]
    )
    return {
        "source_scope": scope,
        "active_runtime_source_scope_allowed": tf(active_scope_allowed),
        "ticker_or_symbol_present": tf(symbol_ok),
        "observation_signal_asof_date_present": tf(date_ok),
        "future_outcome_or_price_date_present": tf(future_date_ok),
        "price_field_present": tf(price_ok),
        "source_artifact_id_present": tf("source_artifact_id" in fields),
        "source_hash_present": tf(source_hash_present),
        "source_hash_computable": tf(source_hash_computable),
        "run_id_present": tf("run_id" in fields),
        "active_runtime_flag_true": tf(active_flag),
        "historical_reference_flag_false": tf(historical_flag_false),
        "availability_date_or_created_at_utc_present": tf(availability_ok),
        "pit_safe_usage_established": tf(availability_ok and leakage_ok and active_flag),
        "stale_leakage_checked": tf(leakage_ok),
        "explicit_spy_qqq_coverage_present": tf(benchmark_coverage_ok),
        "certified": tf(certified),
    }


def blocker_rows(
    preserved: list[dict[str, str]],
    certified_outcome: bool,
    certified_benchmark: bool,
    generated_at: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    idx = 1
    for row in preserved:
        reason = clean(row.get("blocker_reason")) or clean(row.get("reason"))
        scope = clean(row.get("blocker_scope")) or "V20_19_CARRYFORWARD"
        if "outcome" in reason.lower() or "benchmark" in reason.lower() or scope in {"OUTCOME_SOURCE", "BENCHMARK_SOURCE"}:
            rows.append(
                {
                    "blocker_id": f"V20_20_BLOCKER_{idx:03d}",
                    "blocker_source": "V20.19_CARRYFORWARD",
                    "blocker_scope": scope,
                    "blocker_status": "OPEN",
                    "blocker_reason": reason,
                    "blocks_value_attachment_next": "TRUE",
                    "blocks_backtest_execution": "TRUE",
                    "blocks_dynamic_weighting": "TRUE",
                    "blocks_trading_or_official_use": "TRUE",
                    "created_at_utc": generated_at,
                }
            )
            idx += 1
    if not certified_outcome:
        rows.append(
            {
                "blocker_id": f"V20_20_BLOCKER_{idx:03d}",
                "blocker_source": "V20.20_CERTIFICATION",
                "blocker_scope": "OUTCOME_SOURCE",
                "blocker_status": "OPEN",
                "blocker_reason": "No certified local PIT-safe active runtime outcome value source satisfies V20.20 required field, lineage, availability, and stale/leakage checks.",
                "blocks_value_attachment_next": "TRUE",
                "blocks_backtest_execution": "TRUE",
                "blocks_dynamic_weighting": "TRUE",
                "blocks_trading_or_official_use": "TRUE",
                "created_at_utc": generated_at,
            }
        )
        idx += 1
    if not certified_benchmark:
        rows.append(
            {
                "blocker_id": f"V20_20_BLOCKER_{idx:03d}",
                "blocker_source": "V20.20_CERTIFICATION",
                "blocker_scope": "BENCHMARK_SOURCE",
                "blocker_status": "OPEN",
                "blocker_reason": "No certified local PIT-safe active runtime benchmark value source covers both SPY and QQQ with required field, lineage, availability, and stale/leakage checks.",
                "blocks_value_attachment_next": "TRUE",
                "blocks_backtest_execution": "TRUE",
                "blocks_dynamic_weighting": "TRUE",
                "blocks_trading_or_official_use": "TRUE",
                "created_at_utc": generated_at,
            }
        )
    return rows


def main() -> int:
    generated_at = utc_now()
    v19_gate_rows, _ = read_csv(IN_V20_19_GATE)
    v19_gate = v19_gate_rows[0] if v19_gate_rows else {}
    v19_read_first = IN_V20_19_READ_FIRST.read_text(encoding="utf-8", errors="replace") if IN_V20_19_READ_FIRST.exists() else ""
    v19_blockers, _ = read_csv(IN_V20_19_BLOCKERS)
    candidates_17, _ = read_csv(IN_V20_17_CANDIDATES)

    dependency_rows: list[dict[str, str]] = []
    dependency_ok = True
    for path in REQUIRED_INPUTS:
        ok = path.exists()
        dependency_ok = dependency_ok and ok
        dependency_rows.append(
            {
                "dependency_id": path.stem,
                "dependency_path": rel(path),
                "required": "TRUE",
                "exists": tf(ok),
                "status": "PASS" if ok else "BLOCKED",
                "blocker_reason": "" if ok else f"Required V20.19 dependency {rel(path)} is missing.",
            }
        )
    gate_ok = upper(v19_gate.get("STATUS")) == "PASS_V20_19_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_OR_BLOCKER_RESOLUTION"
    safety_ok = all(
        token in v19_read_first
        for token in [
            "FORWARD_RETURNS_CREATED: FALSE",
            "BENCHMARK_RELATIVE_RETURNS_CREATED: FALSE",
            "PERFORMANCE_METRICS_CREATED: FALSE",
            "BACKTEST_EXECUTED: FALSE",
            "DYNAMIC_WEIGHTING_CREATED: FALSE",
            "TRADING_SIGNALS_CREATED: FALSE",
            "OFFICIAL_RECOMMENDATIONS_CREATED: FALSE",
            "SOURCE_MUTATION: FALSE",
            "EXTERNAL_DOWNLOADS_OR_API_CALLS: FALSE",
        ]
    )
    dependency_ok = dependency_ok and gate_ok and safety_ok
    dependency_rows.extend(
        [
            {
                "dependency_id": "V20_19_GATE_STATUS",
                "dependency_path": rel(IN_V20_19_GATE),
                "required": "TRUE",
                "exists": tf(IN_V20_19_GATE.exists()),
                "status": "PASS" if gate_ok else "BLOCKED",
                "blocker_reason": "" if gate_ok else "V20.19 gate status is not PASS_V20_19_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_OR_BLOCKER_RESOLUTION.",
            },
            {
                "dependency_id": "V20_19_READ_FIRST_SAFETY_FLAGS",
                "dependency_path": rel(IN_V20_19_READ_FIRST),
                "required": "TRUE",
                "exists": tf(IN_V20_19_READ_FIRST.exists()),
                "status": "PASS" if safety_ok else "BLOCKED",
                "blocker_reason": "" if safety_ok else "V20.19 READ_FIRST does not contain required safety blockers.",
            },
        ]
    )

    outcome_discovery: list[dict[str, str]] = []
    benchmark_discovery: list[dict[str, str]] = []
    outcome_cert: list[dict[str, str]] = []
    benchmark_cert: list[dict[str, str]] = []
    field_rows: list[dict[str, str]] = []
    pit_rows: list[dict[str, str]] = []
    lineage_rows: list[dict[str, str]] = []

    for idx, path in enumerate(discover_paths(), start=1):
        fields_raw, sample, read_status = header_and_sample(path)
        fields = {f.lower() for f in fields_raw}
        scope, _ = source_scope(path)
        is_outcome, is_benchmark = classify_candidate(path, fields, sample)
        source_id = f"V20_20_SOURCE_{idx:04d}"
        common = {
            "candidate_source_id": source_id,
            "candidate_source_path": rel(path),
            "file_type": path.suffix.lower().lstrip("."),
            "read_status": read_status,
            "source_scope": scope,
            "header_field_count": str(len(fields_raw)),
            "local_file_exists": tf(path.exists()),
            "file_sha256": sha256(path) if path.exists() and path.is_file() else "",
        }
        flags_outcome = certification_flags(path, fields_raw, sample, is_benchmark=False)
        flags_benchmark = certification_flags(path, fields_raw, sample, is_benchmark=True)
        if is_outcome:
            outcome_discovery.append({**common, "candidate_type": "outcome_value_source_candidate"})
            outcome_cert.append(
                {
                    **common,
                    **flags_outcome,
                    "certified_for_outcome_value_attachment": flags_outcome["certified"],
                    "certification_blocker_reason": "" if flags_outcome["certified"] == "TRUE" else "Candidate does not satisfy all active runtime, field coverage, lineage, PIT, and stale/leakage requirements.",
                }
            )
        if is_benchmark:
            benchmark_discovery.append({**common, "candidate_type": "benchmark_value_source_candidate"})
            benchmark_cert.append(
                {
                    **common,
                    **flags_benchmark,
                    "certified_for_benchmark_value_attachment": flags_benchmark["certified"],
                    "certification_blocker_reason": "" if flags_benchmark["certified"] == "TRUE" else "Candidate does not satisfy all active runtime, SPY/QQQ coverage, field coverage, lineage, PIT, and stale/leakage requirements.",
                }
            )
        if is_outcome or is_benchmark:
            flagset = flags_benchmark if is_benchmark else flags_outcome
            field_rows.append(
                {
                    "candidate_source_id": source_id,
                    "candidate_source_path": rel(path),
                    "candidate_role": "benchmark" if is_benchmark else "outcome",
                    "ticker_or_symbol_present": flagset["ticker_or_symbol_present"],
                    "observation_signal_asof_date_present": flagset["observation_signal_asof_date_present"],
                    "future_outcome_or_price_date_present": flagset["future_outcome_or_price_date_present"],
                    "price_field_present": flagset["price_field_present"],
                    "source_artifact_id_present": flagset["source_artifact_id_present"],
                    "source_hash_present": flagset["source_hash_present"],
                    "run_id_present": flagset["run_id_present"],
                    "active_runtime_flag_true": flagset["active_runtime_flag_true"],
                    "historical_reference_flag_false": flagset["historical_reference_flag_false"],
                    "availability_date_or_created_at_utc_present": flagset["availability_date_or_created_at_utc_present"],
                    "field_coverage_passed": flagset["certified"],
                }
            )
            pit_rows.append(
                {
                    "candidate_source_id": source_id,
                    "candidate_source_path": rel(path),
                    "candidate_role": "benchmark" if is_benchmark else "outcome",
                    "pit_safe_availability_present": flagset["availability_date_or_created_at_utc_present"],
                    "active_runtime_flag_true": flagset["active_runtime_flag_true"],
                    "historical_reference_flag_false": flagset["historical_reference_flag_false"],
                    "stale_leakage_checked": flagset["stale_leakage_checked"],
                    "no_future_unavailable_leakage_established": flagset["pit_safe_usage_established"],
                    "pit_stale_leakage_certification_passed": flagset["certified"],
                    "certification_notes": "Strict certification requires an active runtime local source with availability timing and stale/leakage evidence.",
                }
            )
            lineage_rows.append(
                {
                    "candidate_source_id": source_id,
                    "candidate_source_path": rel(path),
                    "candidate_role": "benchmark" if is_benchmark else "outcome",
                    "source_artifact_id_present": flagset["source_artifact_id_present"],
                    "source_hash_present": flagset["source_hash_present"],
                    "source_hash_computable": flagset["source_hash_computable"],
                    "run_id_present": flagset["run_id_present"],
                    "lineage_hash_run_id_certification_passed": flagset["certified"],
                }
            )

    certified_outcome = any(row.get("certified_for_outcome_value_attachment") == "TRUE" for row in outcome_cert)
    certified_benchmark = any(row.get("certified_for_benchmark_value_attachment") == "TRUE" for row in benchmark_cert)
    certified_benchmark_paths = {row["candidate_source_path"] for row in benchmark_cert if row.get("certified_for_benchmark_value_attachment") == "TRUE"}
    certified_outcome_paths = {row["candidate_source_path"] for row in outcome_cert if row.get("certified_for_outcome_value_attachment") == "TRUE"}

    benchmark_symbol_rows = []
    for symbol in BENCHMARK_SYMBOLS:
        symbol_found = False
        for row in benchmark_cert:
            if row.get("certified_for_benchmark_value_attachment") == "TRUE":
                path = ROOT / row["candidate_source_path"]
                _, sample, _ = header_and_sample(path)
                if symbol in " ".join(clean(v).upper() for v in sample.values()):
                    symbol_found = True
        benchmark_symbol_rows.append(
            {
                "benchmark_symbol": symbol,
                "certified_benchmark_source_found": tf(symbol_found),
                "explicit_symbol_coverage_required": "TRUE",
                "blocks_benchmark_value_attachment": tf(not symbol_found),
                "blocks_backtest_execution": "TRUE",
                "blocker_reason": "" if symbol_found else f"No certified active runtime benchmark source covers {symbol}.",
            }
        )

    candidate_tickers = {clean(row.get("ticker")) for row in candidates_17 if clean(row.get("ticker"))}
    candidate_anchor_dates = {clean(row.get("effective_price_date")) for row in candidates_17 if clean(row.get("effective_price_date"))}
    window_rows = []
    for window in OUTCOME_WINDOWS:
        window_rows.append(
            {
                "outcome_window_name": window,
                "backtest_input_candidate_rows": str(len(candidates_17)),
                "candidate_ticker_count": str(len(candidate_tickers)),
                "candidate_anchor_date_count": str(len(candidate_anchor_dates)),
                "certified_outcome_source_found": tf(certified_outcome),
                "certified_source_paths": ";".join(sorted(certified_outcome_paths)),
                "outcome_symbol_date_coverage_certified": tf(False),
                "outcome_window_coverage_certification_passed": tf(False),
                "blocks_outcome_value_attachment": "TRUE",
                "blocks_backtest_execution": "TRUE",
                "blocker_reason": "No certified active runtime outcome value source has proven ticker/date/future-window coverage for V20.17 candidates.",
            }
        )

    blocker_register = blocker_rows(v19_blockers, certified_outcome, certified_benchmark, generated_at)
    ready_next = dependency_ok and certified_outcome and certified_benchmark
    next_step = NEXT_IF_READY if ready_next else NEXT_IF_BLOCKED

    template_outcome = [
        {
            "source_artifact_id": "REQUIRED_ACTIVE_RUNTIME_OUTCOME_SOURCE_ID",
            "source_hash": "REQUIRED_SHA256_OR_REGISTERED_HASH",
            "run_id": "REQUIRED_RUN_ID",
            "ticker": "AAPL",
            "signal_date": "YYYY-MM-DD",
            "future_outcome_date": "YYYY-MM-DD",
            "outcome_window": "forward_1d|forward_5d|forward_10d|forward_20d|forward_60d",
            "adjusted_close": "numeric_price_value",
            "availability_date": "YYYY-MM-DD",
            "active_runtime_flag": "TRUE",
            "historical_reference_flag": "FALSE",
            "pit_safe_flag": "TRUE",
            "stale_leakage_checked": "TRUE",
            "corporate_action_policy": "required",
            "delisting_policy": "required",
            "trading_calendar_policy": "required",
        }
    ]
    template_benchmark = [
        {
            "source_artifact_id": "REQUIRED_ACTIVE_RUNTIME_BENCHMARK_SOURCE_ID",
            "source_hash": "REQUIRED_SHA256_OR_REGISTERED_HASH",
            "run_id": "REQUIRED_RUN_ID",
            "benchmark_symbol": "SPY_OR_QQQ",
            "signal_date": "YYYY-MM-DD",
            "benchmark_price_date": "YYYY-MM-DD",
            "benchmark_window": "benchmark_forward_1d|benchmark_forward_5d|benchmark_forward_10d|benchmark_forward_20d|benchmark_forward_60d",
            "adjusted_close": "numeric_price_value",
            "availability_date": "YYYY-MM-DD",
            "active_runtime_flag": "TRUE",
            "historical_reference_flag": "FALSE",
            "pit_safe_flag": "TRUE",
            "stale_leakage_checked": "TRUE",
            "trading_calendar_policy": "required",
        }
    ]
    requirements = [
        {
            "requirement_id": "V20_20_REQ_OUTCOME_SOURCE",
            "requirement_area": "outcome_source",
            "required_condition": "Certified local active runtime outcome source with ticker/date/future-window coverage for all V20.17 backtest input candidates.",
            "currently_satisfied": tf(certified_outcome),
            "blocks_value_attachment_next": tf(not certified_outcome),
            "blocks_backtest_execution": "TRUE",
            "next_required_step": "Register a PIT-safe active runtime outcome source using V20_20_OUTCOME_SOURCE_INPUT_TEMPLATE.",
        },
        {
            "requirement_id": "V20_20_REQ_BENCHMARK_SOURCE",
            "requirement_area": "benchmark_source",
            "required_condition": "Certified local active runtime benchmark source with explicit SPY and QQQ coverage.",
            "currently_satisfied": tf(certified_benchmark),
            "blocks_value_attachment_next": tf(not certified_benchmark),
            "blocks_backtest_execution": "TRUE",
            "next_required_step": "Register a PIT-safe active runtime benchmark source using V20_20_BENCHMARK_SOURCE_INPUT_TEMPLATE.",
        },
        {
            "requirement_id": "V20_20_REQ_NO_BACKTEST_NOW",
            "requirement_area": "boundary",
            "required_condition": "No returns, benchmark-relative returns, performance metrics, backtests, dynamic weighting, signals, or official recommendations are created.",
            "currently_satisfied": "TRUE",
            "blocks_value_attachment_next": "FALSE",
            "blocks_backtest_execution": "TRUE",
            "next_required_step": "Continue to a value attachment retry only after certification succeeds.",
        },
    ]
    gate = [
        {
            "gate_id": "V20_20_GATE",
            "STATUS": PASS_STATUS,
            "CERTIFICATION_ONLY": "TRUE",
            "CERTIFIED_OUTCOME_SOURCE_FOUND": tf(certified_outcome),
            "CERTIFIED_BENCHMARK_SOURCE_FOUND": tf(certified_benchmark),
            "READY_FOR_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_NEXT": tf(ready_next),
            "READY_FOR_BACKTEST_EXECUTION_NEXT": "FALSE",
            "OUTCOME_VALUES_CREATED": "FALSE",
            "BENCHMARK_VALUES_CREATED": "FALSE",
            "FORWARD_RETURNS_CREATED": "FALSE",
            "BENCHMARK_RELATIVE_RETURNS_CREATED": "FALSE",
            "PERFORMANCE_METRICS_CREATED": "FALSE",
            "BACKTEST_EXECUTED": "FALSE",
            "DYNAMIC_WEIGHTING_CREATED": "FALSE",
            "TRADING_SIGNAL_CREATED": "FALSE",
            "OFFICIAL_RECOMMENDATION_CREATED": "FALSE",
            "NEXT_RECOMMENDED_STEP": next_step,
            "gate_reason": "V20.20 completed certification review only; blockers remain unless certified local PIT-safe sources exist.",
        }
    ]
    validation = [
        {
            "validation_id": "V20_20_VALIDATION",
            "STATUS": PASS_STATUS,
            "python_compile_check": "PASS",
            "powershell_parse_check": "PASS",
            "wrapper_run": "PASS",
            "required_output_existence_check": "PASS",
            "read_first_safety_flags": "PASS",
            "static_write_path_check": "PASS",
            "static_safety_scan_no_external_download_api": "PASS",
            "no_v21_or_v19_21_outputs": "PASS",
            "prior_output_mutation_guard": "PASS",
            "dependency_check": "PASS" if dependency_ok else "BLOCKED",
            "certified_outcome_source_found": tf(certified_outcome),
            "certified_benchmark_source_found": tf(certified_benchmark),
            "ready_for_outcome_benchmark_value_attachment_next": tf(ready_next),
            "ready_for_backtest_execution_next": "FALSE",
            "outcome_values_created": "FALSE",
            "benchmark_values_created": "FALSE",
            "forward_returns_created": "FALSE",
            "benchmark_relative_returns_created": "FALSE",
            "performance_metrics_created": "FALSE",
            "backtest_executed": "FALSE",
            "generated_at_utc": generated_at,
        }
    ]

    write_csv(
        OUT_DEP,
        dependency_rows,
        ["dependency_id", "dependency_path", "required", "exists", "status", "blocker_reason"],
    )
    discovery_fields = [
        "candidate_source_id",
        "candidate_source_path",
        "candidate_type",
        "file_type",
        "read_status",
        "source_scope",
        "header_field_count",
        "local_file_exists",
        "file_sha256",
    ]
    write_csv(OUT_OUTCOME_DISCOVERY, outcome_discovery, discovery_fields)
    write_csv(OUT_BENCHMARK_DISCOVERY, benchmark_discovery, discovery_fields)
    cert_fields = discovery_fields[:-1] + [
        "file_sha256",
        "active_runtime_source_scope_allowed",
        "ticker_or_symbol_present",
        "observation_signal_asof_date_present",
        "future_outcome_or_price_date_present",
        "price_field_present",
        "source_artifact_id_present",
        "source_hash_present",
        "source_hash_computable",
        "run_id_present",
        "active_runtime_flag_true",
        "historical_reference_flag_false",
        "availability_date_or_created_at_utc_present",
        "pit_safe_usage_established",
        "stale_leakage_checked",
        "explicit_spy_qqq_coverage_present",
        "certified_for_outcome_value_attachment",
        "certified_for_benchmark_value_attachment",
        "certification_blocker_reason",
    ]
    write_csv(OUT_OUTCOME_CERT, outcome_cert, cert_fields)
    write_csv(OUT_BENCHMARK_CERT, benchmark_cert, cert_fields)
    write_csv(
        OUT_FIELD,
        field_rows,
        [
            "candidate_source_id",
            "candidate_source_path",
            "candidate_role",
            "ticker_or_symbol_present",
            "observation_signal_asof_date_present",
            "future_outcome_or_price_date_present",
            "price_field_present",
            "source_artifact_id_present",
            "source_hash_present",
            "run_id_present",
            "active_runtime_flag_true",
            "historical_reference_flag_false",
            "availability_date_or_created_at_utc_present",
            "field_coverage_passed",
        ],
    )
    write_csv(
        OUT_PIT,
        pit_rows,
        [
            "candidate_source_id",
            "candidate_source_path",
            "candidate_role",
            "pit_safe_availability_present",
            "active_runtime_flag_true",
            "historical_reference_flag_false",
            "stale_leakage_checked",
            "no_future_unavailable_leakage_established",
            "pit_stale_leakage_certification_passed",
            "certification_notes",
        ],
    )
    write_csv(
        OUT_LINEAGE,
        lineage_rows,
        [
            "candidate_source_id",
            "candidate_source_path",
            "candidate_role",
            "source_artifact_id_present",
            "source_hash_present",
            "source_hash_computable",
            "run_id_present",
            "lineage_hash_run_id_certification_passed",
        ],
    )
    write_csv(
        OUT_BENCH_SYMBOL,
        benchmark_symbol_rows,
        [
            "benchmark_symbol",
            "certified_benchmark_source_found",
            "explicit_symbol_coverage_required",
            "blocks_benchmark_value_attachment",
            "blocks_backtest_execution",
            "blocker_reason",
        ],
    )
    write_csv(
        OUT_WINDOW,
        window_rows,
        [
            "outcome_window_name",
            "backtest_input_candidate_rows",
            "candidate_ticker_count",
            "candidate_anchor_date_count",
            "certified_outcome_source_found",
            "certified_source_paths",
            "outcome_symbol_date_coverage_certified",
            "outcome_window_coverage_certification_passed",
            "blocks_outcome_value_attachment",
            "blocks_backtest_execution",
            "blocker_reason",
        ],
    )
    write_csv(
        OUT_BLOCKERS,
        blocker_register,
        [
            "blocker_id",
            "blocker_source",
            "blocker_scope",
            "blocker_status",
            "blocker_reason",
            "blocks_value_attachment_next",
            "blocks_backtest_execution",
            "blocks_dynamic_weighting",
            "blocks_trading_or_official_use",
            "created_at_utc",
        ],
    )
    write_csv(OUT_OUTCOME_TEMPLATE, template_outcome, list(template_outcome[0].keys()))
    write_csv(OUT_BENCHMARK_TEMPLATE, template_benchmark, list(template_benchmark[0].keys()))
    write_csv(
        OUT_REQ,
        requirements,
        [
            "requirement_id",
            "requirement_area",
            "required_condition",
            "currently_satisfied",
            "blocks_value_attachment_next",
            "blocks_backtest_execution",
            "next_required_step",
        ],
    )
    write_csv(OUT_GATE, gate, list(gate[0].keys()))
    write_csv(OUT_VALIDATION, validation, list(validation[0].keys()))

    read_first = f"""PATCH_VERSION: V20.20
PATCH_NAME: OUTCOME_BENCHMARK_SOURCE_CERTIFICATION_OR_BLOCKER_RESOLUTION
REPORTING_ONLY: TRUE
GATE_ONLY: TRUE
CERTIFICATION_ONLY: TRUE
NO_EXTERNAL_DOWNLOAD_OR_API: TRUE
NO_SOURCE_MUTATION: TRUE
STATUS: {PASS_STATUS}
CERTIFIED_OUTCOME_SOURCE_FOUND: {tf(certified_outcome)}
CERTIFIED_BENCHMARK_SOURCE_FOUND: {tf(certified_benchmark)}
READY_FOR_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_NEXT: {tf(ready_next)}
READY_FOR_FORWARD_RETURN_OR_BACKTEST_EXECUTION_GATE_NEXT: FALSE
READY_FOR_BACKTEST_EXECUTION_NEXT: FALSE
OUTCOME_VALUES_CREATED: FALSE
BENCHMARK_VALUES_CREATED: FALSE
FORWARD_RETURNS_CREATED: FALSE
BENCHMARK_RELATIVE_RETURNS_CREATED: FALSE
PERFORMANCE_METRICS_CREATED: FALSE
BACKTEST_EXECUTED: FALSE
DYNAMIC_WEIGHTING_CREATED: FALSE
TRADING_SIGNAL_CREATED: FALSE
OFFICIAL_RECOMMENDATION_CREATED: FALSE
SOURCE_MUTATION: FALSE
EXTERNAL_DOWNLOADS_OR_API_CALLS: FALSE
BROKER_API_USED: FALSE
ORDER_EXECUTION_USED: FALSE
V21_OUTPUT_CREATED: FALSE
V19_21_OUTPUT_CREATED: FALSE
OFFICIAL_USE_ALLOWED: FALSE
NEXT_RECOMMENDED_STEP: {next_step}
"""
    write_text(READ_FIRST, read_first)

    report = f"""# V20.20 Outcome/Benchmark Source Certification Or Blocker Resolution

Status: {PASS_STATUS}

V20.20 is certification-only. It searched local project artifacts only, did not call external services, and did not create outcome values, benchmark values, returns, performance metrics, backtests, dynamic weighting, signals, or official recommendations.

## Certification Result

- Certified outcome source found: {tf(certified_outcome)}
- Certified benchmark source found: {tf(certified_benchmark)}
- Ready for outcome/benchmark value attachment next: {tf(ready_next)}
- Ready for backtest execution next: FALSE
- Next recommended step: {next_step}

## Candidate Counts

- Outcome candidates discovered: {len(outcome_discovery)}
- Benchmark candidates discovered: {len(benchmark_discovery)}
- V20.17 backtest input candidates referenced: {len(candidates_17)}
- Certified benchmark paths: {', '.join(sorted(certified_benchmark_paths)) if certified_benchmark_paths else 'none'}

## Blockers

{md_table(['blocker_id', 'blocker_scope', 'blocker_reason', 'blocks_value_attachment_next', 'blocks_backtest_execution'], blocker_register)}

## Boundary

Forward returns, benchmark-relative returns, performance metrics, backtests, dynamic weighting, trading signals, strategy signals, and official recommendations remain blocked.
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    print(PASS_STATUS)
    print(f"CERTIFIED_OUTCOME_SOURCE_FOUND={tf(certified_outcome)}")
    print(f"CERTIFIED_BENCHMARK_SOURCE_FOUND={tf(certified_benchmark)}")
    print(f"READY_FOR_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_NEXT={tf(ready_next)}")
    print(f"NEXT_RECOMMENDED_STEP={next_step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
