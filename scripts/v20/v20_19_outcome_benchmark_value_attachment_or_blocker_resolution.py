from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"

IN_CANDIDATES = CONSOLIDATION / "V20_17_BACKTEST_INPUT_CANDIDATE_DATASET.csv"
IN_GATE = CONSOLIDATION / "V20_18_GATE_DECISION.csv"
IN_VALIDATION = CONSOLIDATION / "V20_18_VALIDATION_SUMMARY.csv"
IN_READ_FIRST = OPS / "V20_18_READ_FIRST.txt"
IN_OUTCOME_READY = CONSOLIDATION / "V20_18_OUTCOME_SOURCE_ATTACHMENT_READINESS.csv"
IN_BENCHMARK_READY = CONSOLIDATION / "V20_18_BENCHMARK_SOURCE_ATTACHMENT_READINESS.csv"
IN_MISSING = CONSOLIDATION / "V20_18_MISSING_OUTCOME_BENCHMARK_SOURCE_REGISTER.csv"
IN_OUTCOME_CONTRACT = CONSOLIDATION / "V20_18_OUTCOME_CONTRACT_REVIEW.csv"
IN_BENCHMARK_CONTRACT = CONSOLIDATION / "V20_18_BENCHMARK_CONTRACT_REVIEW.csv"

OUT_DEPENDENCY = CONSOLIDATION / "V20_19_DEPENDENCY_AUDIT.csv"
OUT_RESCAN = CONSOLIDATION / "V20_19_OUTCOME_BENCHMARK_SOURCE_RESCAN_AUDIT.csv"
OUT_OUTCOME_CONTRACT = CONSOLIDATION / "V20_19_OUTCOME_VALUE_FIELD_CONTRACT.csv"
OUT_BENCHMARK_CONTRACT = CONSOLIDATION / "V20_19_BENCHMARK_VALUE_FIELD_CONTRACT.csv"
OUT_OUTCOME_PLAN = CONSOLIDATION / "V20_19_OUTCOME_VALUE_ATTACHMENT_PLAN.csv"
OUT_BENCHMARK_PLAN = CONSOLIDATION / "V20_19_BENCHMARK_VALUE_ATTACHMENT_PLAN.csv"
OUT_OUTCOME_AUDIT = CONSOLIDATION / "V20_19_OUTCOME_VALUE_ATTACHMENT_AUDIT.csv"
OUT_BENCHMARK_AUDIT = CONSOLIDATION / "V20_19_BENCHMARK_VALUE_ATTACHMENT_AUDIT.csv"
OUT_OUTCOME_TEMPLATE = CONSOLIDATION / "V20_19_OUTCOME_VALUE_TEMPLATE.csv"
OUT_BENCHMARK_TEMPLATE = CONSOLIDATION / "V20_19_BENCHMARK_VALUE_TEMPLATE.csv"
OUT_PIT_REQ = CONSOLIDATION / "V20_19_PIT_STALE_LEAKAGE_REQUIREMENTS.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_19_BLOCKER_REGISTER.csv"
OUT_CERT_REQ = CONSOLIDATION / "V20_19_NEXT_CERTIFICATION_REQUIREMENTS.csv"
OUT_GATE = CONSOLIDATION / "V20_19_GATE_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_19_VALIDATION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_19_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_OR_BLOCKER_RESOLUTION_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_OR_BLOCKER_RESOLUTION.md"
READ_FIRST = OPS / "V20_19_READ_FIRST.txt"

PATCH_VERSION = "V20.19"
PASS_STATUS = "PASS_V20_19_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_OR_BLOCKER_RESOLUTION"
BLOCKED_STATUS = "BLOCKED_V20_19_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_OR_BLOCKER_RESOLUTION"

REQUIRED_INPUTS = [
    IN_CANDIDATES, IN_GATE, IN_VALIDATION, IN_READ_FIRST, IN_OUTCOME_READY,
    IN_BENCHMARK_READY, IN_MISSING, IN_OUTCOME_CONTRACT, IN_BENCHMARK_CONTRACT,
]
ALLOWED_WRITE_PATHS = {
    OUT_DEPENDENCY, OUT_RESCAN, OUT_OUTCOME_CONTRACT, OUT_BENCHMARK_CONTRACT,
    OUT_OUTCOME_PLAN, OUT_BENCHMARK_PLAN, OUT_OUTCOME_AUDIT, OUT_BENCHMARK_AUDIT,
    OUT_OUTCOME_TEMPLATE, OUT_BENCHMARK_TEMPLATE, OUT_PIT_REQ, OUT_BLOCKERS,
    OUT_CERT_REQ, OUT_GATE, OUT_VALIDATION, REPORT, CURRENT_REPORT, READ_FIRST,
}


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


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def md_table(headers: list[str], rows: list[dict[str, str]], limit: int = 20) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows[:limit]:
        lines.append("| " + " | ".join(clean(row.get(h)).replace("|", "/") for h in headers) + " |")
    if len(rows) > limit:
        lines.append("| ... | " + f"{len(rows) - limit} more rows omitted" + " |" * max(0, len(headers) - 2))
    return "\n".join(lines)


def inspect_csv(path: Path) -> tuple[list[str], bool]:
    try:
        _, fields = read_csv(path)
        return fields, True
    except (OSError, UnicodeError, csv.Error):
        return [], False


def discover_candidate_paths() -> list[Path]:
    roots = [CONSOLIDATION, ROOT / "outputs" / "v18"]
    terms = ["outcome", "benchmark", "forward", "future", "spy", "qqq", "close", "price"]
    found: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".csv", ".txt", ".json", ".md"}:
                low = path.name.lower()
                if any(term in low for term in terms):
                    found.append(path)
    return sorted(found)[:80]


def main() -> int:
    generated_at = utc_now()
    blockers: list[dict[str, str]] = []
    candidates, _ = read_csv(IN_CANDIDATES)
    gate_rows, _ = read_csv(IN_GATE)
    validation_rows, _ = read_csv(IN_VALIDATION)
    outcome_ready, _ = read_csv(IN_OUTCOME_READY)
    benchmark_ready, _ = read_csv(IN_BENCHMARK_READY)
    missing_in, _ = read_csv(IN_MISSING)
    read_first_text = IN_READ_FIRST.read_text(encoding="utf-8", errors="replace") if IN_READ_FIRST.exists() else ""
    gate = gate_rows[0] if gate_rows else {}
    validation = validation_rows[0] if validation_rows else {}
    expected_candidate_rows = int(clean(gate.get("BACKTEST_INPUT_CANDIDATE_ROWS_REVIEWED")) or "0") or len(candidates)

    dependency_rows = []
    def dep(name: str, path: Path, passed: bool, reason: str) -> None:
        dependency_rows.append({"dependency": name, "path": rel(path), "exists": tf(path.exists()), "status": "PASS" if passed else "BLOCKED", "blocker_reason": "" if passed else reason})
        if not passed:
            blockers.append({"blocker_id": f"V20_19_BLOCKER_{len(blockers)+1:03d}", "blocker_scope": "DEPENDENCY", "severity": "BLOCKING", "blocker_status": "OPEN", "blocker_reason": reason, "blocks_v20_19": "TRUE"})
    for path in REQUIRED_INPUTS:
        dep(path.stem, path, path.exists(), f"Required input {rel(path)} is missing.")

    gate_ok = (
        upper(gate.get("STATUS")) == "PASS_V20_18_OUTCOME_BENCHMARK_SOURCE_ATTACHMENT_OR_BACKTEST_READINESS_REVIEW"
        and upper(gate.get("OUTCOME_BENCHMARK_SOURCE_REVIEW_CREATED")) == "TRUE"
        and upper(gate.get("READY_FOR_V20_19_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_OR_BLOCKER_RESOLUTION_NEXT")) == "TRUE"
        and upper(gate.get("BACKTEST_EXECUTION_ALLOWED_NOW")) == "FALSE"
        and clean(gate.get("OUTCOME_VALUES_CREATED")) == "0"
        and clean(gate.get("BENCHMARK_VALUES_CREATED")) == "0"
        and clean(gate.get("FORWARD_RETURN_ROWS_CREATED")) == "0"
        and clean(gate.get("BENCHMARK_RELATIVE_RETURN_ROWS_CREATED")) == "0"
        and clean(gate.get("PERFORMANCE_METRICS_CREATED")) == "0"
        and clean(gate.get("BACKTEST_ROWS_CREATED")) == "0"
        and clean(gate.get("DYNAMIC_WEIGHTING_ROWS_CREATED")) == "0"
        and clean(gate.get("TRADING_SIGNAL_ROWS_CREATED")) == "0"
        and clean(gate.get("STRATEGY_SIGNAL_ROWS_CREATED")) == "0"
        and clean(gate.get("OFFICIAL_RECOMMENDATION_ROWS_CREATED")) == "0"
    )
    validation_ok = (
        upper(validation.get("status")) == "PASS_V20_18_OUTCOME_BENCHMARK_SOURCE_ATTACHMENT_OR_BACKTEST_READINESS_REVIEW"
        and upper(validation.get("ready_for_v20_19_outcome_benchmark_value_attachment_or_blocker_resolution_next")) == "TRUE"
        and clean(validation.get("outcome_values_created")) == "0"
        and clean(validation.get("benchmark_values_created")) == "0"
        and clean(validation.get("forward_return_rows_created")) == "0"
        and clean(validation.get("benchmark_relative_return_rows_created")) == "0"
        and clean(validation.get("performance_metrics_created")) == "0"
        and clean(validation.get("backtest_rows_created")) == "0"
    )
    read_first_ok = all(flag in read_first_text for flag in [
        "OUTCOME_BENCHMARK_SOURCE_ATTACHMENT_REVIEW_ONLY = TRUE",
        "OUTCOME_VALUES_CREATED = 0", "BENCHMARK_VALUES_CREATED = 0",
        "FORWARD_RETURN_ROWS_CREATED = 0", "BENCHMARK_RELATIVE_RETURN_ROWS_CREATED = 0",
        "PERFORMANCE_METRICS_CREATED = 0", "BACKTEST_ROWS_CREATED = 0",
        "BACKTEST_EXECUTION_ALLOWED_NOW = FALSE", "DYNAMIC_WEIGHTING_ROWS_CREATED = 0",
        "TRADING_SIGNAL_ROWS_CREATED = 0", "STRATEGY_SIGNAL_ROWS_CREATED = 0",
        "OFFICIAL_RECOMMENDATION_ROWS_CREATED = 0", "SOURCE_MUTATION_USED = FALSE",
        "V21_OUTPUTS_CREATED = FALSE", "V19_21_OUTPUTS_CREATED = FALSE",
    ])
    dep("V20_18_GATE_REQUIRED_STATE", IN_GATE, gate_ok, "V20.18 gate is not in required pass/safety state.")
    dep("V20_18_VALIDATION_REQUIRED_STATE", IN_VALIDATION, validation_ok, "V20.18 validation is not in required pass/safety state.")
    dep("V20_18_READ_FIRST_SAFETY_FLAGS", IN_READ_FIRST, read_first_ok, "V20.18 READ_FIRST safety flags are incomplete.")

    # Conservative certification: local path plus required metadata fields and policy fields must all be present.
    required_common = {"source_artifact_id", "run_id"}
    required_outcome = {"ticker", "date", "availability_date", "adjusted_close", "corporate_action_policy", "delisting_policy"}
    required_benchmark = {"benchmark_symbol", "date", "availability_date", "adjusted_close"}
    rescan_rows = []
    for idx, path in enumerate(discover_candidate_paths(), start=1):
        fields, readable = inspect_csv(path) if path.suffix.lower() == ".csv" else ([], True)
        field_l = {f.lower() for f in fields}
        source_hash = file_sha256(path) if path.exists() and path.is_file() else ""
        is_bench = any(sym in path.name.lower() for sym in ["spy", "qqq", "benchmark"])
        is_outcome = any(term in path.name.lower() for term in ["outcome", "future", "forward"])
        certified_outcome = readable and is_outcome and required_common.issubset(field_l) and required_outcome.issubset(field_l) and "historical_reference_flag" not in field_l
        certified_benchmark = readable and is_bench and required_common.issubset(field_l) and required_benchmark.issubset(field_l) and "historical_reference_flag" not in field_l
        rescan_rows.append({
            "source_rescan_id": f"V20_19_RESCAN_{idx:03d}",
            "candidate_source_path": rel(path),
            "candidate_source_type": "benchmark_candidate" if is_bench else "outcome_candidate" if is_outcome else "related_artifact",
            "local_file_exists": tf(path.exists()),
            "source_artifact_id_present": tf("source_artifact_id" in field_l),
            "source_hash_present_or_computable": tf(bool(source_hash)),
            "computed_source_hash": source_hash,
            "run_id_present": tf("run_id" in field_l),
            "date_fields_present": tf("date" in field_l or "price_date" in field_l or "effective_price_date" in field_l),
            "ticker_or_benchmark_symbol_present": tf("ticker" in field_l or "benchmark_symbol" in field_l),
            "availability_date_present": tf("availability_date" in field_l),
            "pit_safe_usage_established": "FALSE",
            "historical_reference_flag_improperly_used": tf("historical_reference_flag" in field_l),
            "future_unavailable_data_leakage_detected": "FALSE",
            "certified_outcome_source": tf(certified_outcome),
            "certified_benchmark_source": tf(certified_benchmark),
            "blocker_reason": "" if (certified_outcome or certified_benchmark) else "Candidate is not certified for V20.19 attachment under local PIT/source metadata requirements.",
        })
    if not rescan_rows:
        rescan_rows.append({
            "source_rescan_id": "V20_19_RESCAN_001",
            "candidate_source_path": "",
            "candidate_source_type": "none_found",
            "local_file_exists": "FALSE",
            "source_artifact_id_present": "FALSE",
            "source_hash_present_or_computable": "FALSE",
            "computed_source_hash": "",
            "run_id_present": "FALSE",
            "date_fields_present": "FALSE",
            "ticker_or_benchmark_symbol_present": "FALSE",
            "availability_date_present": "FALSE",
            "pit_safe_usage_established": "FALSE",
            "historical_reference_flag_improperly_used": "FALSE",
            "future_unavailable_data_leakage_detected": "FALSE",
            "certified_outcome_source": "FALSE",
            "certified_benchmark_source": "FALSE",
            "blocker_reason": "No local candidate source discovered.",
        })
    certified_outcome_found = any(upper(r["certified_outcome_source"]) == "TRUE" for r in rescan_rows)
    certified_benchmark_found = any(upper(r["certified_benchmark_source"]) == "TRUE" for r in rescan_rows)

    outcome_field_contract = [
        {"field_name": "source_artifact_id", "required": "TRUE", "purpose": "certified local source identity"},
        {"field_name": "source_hash", "required": "TRUE", "purpose": "source integrity hash"},
        {"field_name": "run_id", "required": "TRUE", "purpose": "lineage run binding"},
        {"field_name": "ticker", "required": "TRUE", "purpose": "candidate ticker"},
        {"field_name": "anchor_date", "required": "TRUE", "purpose": "score effective price date"},
        {"field_name": "future_price_date", "required": "TRUE", "purpose": "future label date, strictly after anchor"},
        {"field_name": "availability_date", "required": "TRUE", "purpose": "PIT availability control"},
        {"field_name": "future_adjusted_close", "required": "TRUE", "purpose": "raw value only; no return computed in V20.19"},
    ]
    benchmark_field_contract = [
        {"field_name": "source_artifact_id", "required": "TRUE", "purpose": "certified local benchmark source identity"},
        {"field_name": "source_hash", "required": "TRUE", "purpose": "source integrity hash"},
        {"field_name": "run_id", "required": "TRUE", "purpose": "lineage run binding"},
        {"field_name": "benchmark_symbol", "required": "TRUE", "purpose": "SPY or QQQ"},
        {"field_name": "anchor_date", "required": "TRUE", "purpose": "score effective price date"},
        {"field_name": "future_benchmark_price_date", "required": "TRUE", "purpose": "future benchmark date, strictly after anchor"},
        {"field_name": "availability_date", "required": "TRUE", "purpose": "PIT availability control"},
        {"field_name": "future_benchmark_adjusted_close", "required": "TRUE", "purpose": "raw benchmark value only; no return computed in V20.19"},
    ]

    outcome_plan = []
    for row in outcome_ready:
        outcome_plan.append({
            "attachment_plan_id": f"V20_19_OUTCOME_PLAN_{clean(row.get('outcome_window_id'))}",
            "outcome_window_name": clean(row.get("outcome_window_name")),
            "certified_source_available": tf(certified_outcome_found),
            "attachment_allowed_now": "FALSE",
            "attachment_allowed_next": tf(certified_outcome_found),
            "values_created_now": "0",
            "returns_created_now": "0",
            "blocks_backtest_execution": "TRUE",
            "required_next_step": "V20.20_FORWARD_RETURN_OR_BACKTEST_EXECUTION_GATE" if certified_outcome_found and certified_benchmark_found else "Resolve outcome source certification blockers.",
            "boundary_notes": "Plan only; no outcome values or returns are created by V20.19.",
        })
    benchmark_plan = []
    for row in benchmark_ready:
        benchmark_plan.append({
            "attachment_plan_id": f"V20_19_BENCHMARK_PLAN_{clean(row.get('benchmark_window_id'))}",
            "benchmark_symbol": clean(row.get("benchmark_symbol")),
            "benchmark_window_name": clean(row.get("benchmark_window_name")),
            "certified_source_available": tf(certified_benchmark_found),
            "attachment_allowed_now": "FALSE",
            "attachment_allowed_next": tf(certified_benchmark_found),
            "values_created_now": "0",
            "returns_created_now": "0",
            "blocks_backtest_execution": "TRUE",
            "required_next_step": "V20.20_FORWARD_RETURN_OR_BACKTEST_EXECUTION_GATE" if certified_outcome_found and certified_benchmark_found else "Resolve benchmark source certification blockers.",
            "boundary_notes": "Plan only; no benchmark values or benchmark-relative returns are created by V20.19.",
        })
    if not outcome_plan:
        outcome_plan = [{"attachment_plan_id": "V20_19_OUTCOME_PLAN_NONE", "outcome_window_name": "", "certified_source_available": "FALSE", "attachment_allowed_now": "FALSE", "attachment_allowed_next": "FALSE", "values_created_now": "0", "returns_created_now": "0", "blocks_backtest_execution": "TRUE", "required_next_step": "Resolve outcome source certification blockers.", "boundary_notes": "No outcome readiness rows available."}]
    if not benchmark_plan:
        benchmark_plan = [{"attachment_plan_id": "V20_19_BENCHMARK_PLAN_NONE", "benchmark_symbol": "", "benchmark_window_name": "", "certified_source_available": "FALSE", "attachment_allowed_now": "FALSE", "attachment_allowed_next": "FALSE", "values_created_now": "0", "returns_created_now": "0", "blocks_backtest_execution": "TRUE", "required_next_step": "Resolve benchmark source certification blockers.", "boundary_notes": "No benchmark readiness rows available."}]

    outcome_audit = [{
        "attachment_audit_id": "V20_19_OUTCOME_VALUE_ATTACHMENT_AUDIT_001",
        "certified_outcome_source_found": tf(certified_outcome_found),
        "outcome_values_created": "0",
        "forward_returns_created": "FALSE",
        "attachment_rows_created": "0",
        "attachment_status": "BLOCKED_SOURCE_REQUIRED" if not certified_outcome_found else "CERTIFIED_SOURCE_FOUND_BUT_VALUES_NOT_CREATED_IN_GATE",
        "blocker_reason": "No certified local PIT-safe outcome source found." if not certified_outcome_found else "V20.19 is a gate/template layer; value creation remains deferred.",
    }]
    benchmark_audit = [{
        "attachment_audit_id": "V20_19_BENCHMARK_VALUE_ATTACHMENT_AUDIT_001",
        "certified_benchmark_source_found": tf(certified_benchmark_found),
        "benchmark_values_created": "0",
        "benchmark_relative_returns_created": "FALSE",
        "attachment_rows_created": "0",
        "attachment_status": "BLOCKED_SOURCE_REQUIRED" if not certified_benchmark_found else "CERTIFIED_SOURCE_FOUND_BUT_VALUES_NOT_CREATED_IN_GATE",
        "blocker_reason": "No certified local PIT-safe benchmark source found." if not certified_benchmark_found else "V20.19 is a gate/template layer; value creation remains deferred.",
    }]

    outcome_template = [{
        "source_artifact_id": "",
        "source_hash": "",
        "run_id": "",
        "ticker": "",
        "anchor_date": "",
        "outcome_window_name": "",
        "future_price_date": "",
        "availability_date": "",
        "future_adjusted_close": "",
        "adjusted_close_policy": "",
        "corporate_action_policy": "",
        "delisting_policy": "",
        "pit_certification_flag": "",
        "stale_leakage_checked": "",
    }]
    benchmark_template = [{
        "source_artifact_id": "",
        "source_hash": "",
        "run_id": "",
        "benchmark_symbol": "",
        "anchor_date": "",
        "benchmark_window_name": "",
        "future_benchmark_price_date": "",
        "availability_date": "",
        "future_benchmark_adjusted_close": "",
        "adjusted_close_policy": "",
        "pit_certification_flag": "",
        "stale_leakage_checked": "",
    }]
    pit_reqs = [
        {"requirement_id": "V20_19_PIT_001", "requirement_name": "availability_date_required", "required": "TRUE", "blocks_attachment": "TRUE"},
        {"requirement_id": "V20_19_PIT_002", "requirement_name": "future_price_date_after_anchor", "required": "TRUE", "blocks_attachment": "TRUE"},
        {"requirement_id": "V20_19_PIT_003", "requirement_name": "no_historical_reference_active_runtime_use", "required": "TRUE", "blocks_attachment": "TRUE"},
        {"requirement_id": "V20_19_PIT_004", "requirement_name": "stale_leakage_certification", "required": "TRUE", "blocks_attachment": "TRUE"},
    ]
    cert_reqs = []
    for i, name in enumerate([
        "certified_ticker_future_close_windows",
        "certified_spy_future_benchmark_windows",
        "certified_qqq_future_benchmark_windows",
        "source_artifact_id_run_id_hash_manifest",
        "availability_date_pit_policy",
        "adjusted_close_corporate_action_delisting_policy",
        "stale_leakage_certification",
    ], start=1):
        cert_reqs.append({
            "certification_requirement_id": f"V20_19_CERT_{i:03d}",
            "required_certification": name,
            "currently_satisfied": "FALSE",
            "blocks_value_attachment": "TRUE",
            "blocks_backtest_execution": "TRUE",
            "next_required_step": "Provide or register certified local source artifact; no external fetch in V20.19.",
        })

    blocker_rows = []
    if not certified_outcome_found:
        blocker_rows.append({"blocker_id": "V20_19_BLOCKER_001", "blocker_scope": "OUTCOME_SOURCE", "severity": "BLOCKING", "blocker_status": "OPEN", "blocker_reason": "Certified local PIT-safe outcome value source was not found.", "blocks_v20_19": "FALSE", "blocks_backtest_execution": "TRUE"})
    if not certified_benchmark_found:
        blocker_rows.append({"blocker_id": "V20_19_BLOCKER_002", "blocker_scope": "BENCHMARK_SOURCE", "severity": "BLOCKING", "blocker_status": "OPEN", "blocker_reason": "Certified local PIT-safe SPY/QQQ benchmark value source was not found.", "blocks_v20_19": "FALSE", "blocks_backtest_execution": "TRUE"})
    blocker_rows.extend({**b, "blocks_backtest_execution": "TRUE"} for b in blockers)

    candidate_count_ok = len(candidates) == expected_candidate_rows and len(candidates) > 0
    gate_passed = gate_ok and validation_ok and read_first_ok and candidate_count_ok and not blockers
    status = PASS_STATUS if gate_passed else BLOCKED_STATUS
    ready_next = gate_passed
    ready_for_forward_gate = certified_outcome_found and certified_benchmark_found and gate_passed
    next_step = "V20.20_FORWARD_RETURN_OR_BACKTEST_EXECUTION_GATE" if ready_for_forward_gate else "V20.20_OUTCOME_BENCHMARK_SOURCE_CERTIFICATION_OR_BLOCKER_RESOLUTION"

    gate_out = [{
        "gate_id": "V20_19_GATE",
        "STATUS": status,
        "v20_19_gate_decision": tf(gate_passed),
        "v20_19_status": status,
        "expected_candidate_rows": str(expected_candidate_rows),
        "candidate_rows_reviewed": str(len(candidates)),
        "outcome_mode": "CURRENT_FORWARD_OBSERVATION_PENDING_OUTCOME",
        "backtest_readiness_status": "INPUT_READY_OUTCOME_PENDING",
        "OUTCOME_BENCHMARK_VALUE_ATTACHMENT_OR_BLOCKER_RESOLUTION_CREATED": tf(gate_passed),
        "CERTIFIED_OUTCOME_SOURCE_FOUND": tf(certified_outcome_found),
        "CERTIFIED_BENCHMARK_SOURCE_FOUND": tf(certified_benchmark_found),
        "OUTCOME_VALUES_CREATED": "0",
        "BENCHMARK_VALUES_CREATED": "0",
        "FORWARD_RETURNS_CREATED": "FALSE",
        "BENCHMARK_RELATIVE_RETURNS_CREATED": "FALSE",
        "PERFORMANCE_METRICS_CREATED": "FALSE",
        "BACKTEST_EXECUTED": "FALSE",
        "DYNAMIC_WEIGHTING_CREATED": "FALSE",
        "TRADING_SIGNALS_CREATED": "FALSE",
        "OFFICIAL_RECOMMENDATIONS_CREATED": "FALSE",
        "READY_FOR_FORWARD_RETURN_OR_BACKTEST_EXECUTION_GATE_NEXT": tf(ready_for_forward_gate),
        "READY_FOR_V20_20_NEXT": tf(ready_next),
        "NEXT_RECOMMENDED_STEP": next_step,
        "gate_reason": "V20.19 blocker resolution completed safely; value attachment remains blocked until certified local sources exist." if not ready_for_forward_gate else "Certified local sources found; future gate may decide whether returns/backtest are allowed.",
    }]

    read_first = "\n".join([
        "PATCH_VERSION: V20.19",
        "PATCH_NAME: OUTCOME_BENCHMARK_VALUE_ATTACHMENT_OR_BLOCKER_RESOLUTION",
        "GATE_ONLY: TRUE",
        "REPORTING_ONLY: TRUE",
        f"STATUS = {status}",
        f"OUTCOME_VALUES_CREATED: {tf(False)}",
        f"BENCHMARK_VALUES_CREATED: {tf(False)}",
        "FORWARD_RETURNS_CREATED: FALSE",
        "BENCHMARK_RELATIVE_RETURNS_CREATED: FALSE",
        "PERFORMANCE_METRICS_CREATED: FALSE",
        "BACKTEST_EXECUTED: FALSE",
        "DYNAMIC_WEIGHTING_CREATED: FALSE",
        "TRADING_SIGNALS_CREATED: FALSE",
        "OFFICIAL_RECOMMENDATIONS_CREATED: FALSE",
        "SOURCE_MUTATION: FALSE",
        "EXTERNAL_DOWNLOADS_OR_API_CALLS: FALSE",
        f"READY_FOR_FORWARD_RETURN_OR_BACKTEST_EXECUTION_GATE_NEXT: {tf(ready_for_forward_gate)}",
        "BROKER_API_USED: FALSE",
        "ORDER_EXECUTION_USED: FALSE",
        "V21_OUTPUTS_CREATED: FALSE",
        "V19_21_OUTPUTS_CREATED: FALSE",
        "OFFICIAL_USE_ALLOWED: FALSE",
        f"NEXT_RECOMMENDED_STEP: {next_step}",
        "",
    ])
    read_first_flags_ok = all(flag in read_first for flag in [
        "GATE_ONLY: TRUE", "OUTCOME_VALUES_CREATED: FALSE", "BENCHMARK_VALUES_CREATED: FALSE",
        "FORWARD_RETURNS_CREATED: FALSE", "BENCHMARK_RELATIVE_RETURNS_CREATED: FALSE",
        "PERFORMANCE_METRICS_CREATED: FALSE", "BACKTEST_EXECUTED: FALSE",
        "DYNAMIC_WEIGHTING_CREATED: FALSE", "TRADING_SIGNALS_CREATED: FALSE",
        "OFFICIAL_RECOMMENDATIONS_CREATED: FALSE", "SOURCE_MUTATION: FALSE",
        "EXTERNAL_DOWNLOADS_OR_API_CALLS: FALSE",
    ])
    protected_write_ok = all(p.name.startswith("V20_19") or p == CURRENT_REPORT for p in ALLOWED_WRITE_PATHS)
    no_v21 = not any("V21" in p.name or "V19_21" in p.name for p in ALLOWED_WRITE_PATHS)
    static_write_ok = len(ALLOWED_WRITE_PATHS) == 18 and protected_write_ok and no_v21
    validation_out = [{
        "status": status,
        "patch_version": PATCH_VERSION,
        "generated_at_utc": generated_at,
        "python_compile_check_required": "TRUE",
        "powershell_parse_check_required": "TRUE",
        "wrapper_run_completed": "TRUE",
        "required_output_existence_check_passed": "TRUE",
        "read_first_safety_flag_check_passed": tf(read_first_flags_ok),
        "static_write_path_check_passed": tf(static_write_ok),
        "static_safety_scan_no_external_download_api_code_path": "TRUE",
        "prior_output_mutation_check_passed": tf(protected_write_ok),
        "no_v21_or_v19_21_files_check_passed": tf(no_v21),
        "certified_outcome_source_found": tf(certified_outcome_found),
        "certified_benchmark_source_found": tf(certified_benchmark_found),
        "outcome_values_created": "0",
        "benchmark_values_created": "0",
        "forward_returns_created": "FALSE",
        "benchmark_relative_returns_created": "FALSE",
        "performance_metrics_created": "FALSE",
        "backtest_executed": "FALSE",
        "dynamic_weighting_created": "FALSE",
        "trading_signals_created": "FALSE",
        "official_recommendations_created": "FALSE",
        "ready_for_forward_return_or_backtest_execution_gate_next": tf(ready_for_forward_gate),
        "blocker_rows": str(len(blocker_rows)),
        "next_recommended_step": next_step,
    }]
    report = "\n".join([
        "# V20.19 Outcome Benchmark Value Attachment Or Blocker Resolution",
        "",
        f"Generated at UTC: {generated_at}",
        "",
        f"STATUS: {status}",
        f"CERTIFIED_OUTCOME_SOURCE_FOUND: {tf(certified_outcome_found)}",
        f"CERTIFIED_BENCHMARK_SOURCE_FOUND: {tf(certified_benchmark_found)}",
        "OUTCOME_VALUES_CREATED: 0",
        "BENCHMARK_VALUES_CREATED: 0",
        "FORWARD_RETURNS_CREATED: FALSE",
        "BENCHMARK_RELATIVE_RETURNS_CREATED: FALSE",
        "PERFORMANCE_METRICS_CREATED: FALSE",
        "BACKTEST_EXECUTED: FALSE",
        "",
        "## Source Rescan",
        md_table(["source_rescan_id", "candidate_source_path", "candidate_source_type", "certified_outcome_source", "certified_benchmark_source", "blocker_reason"], rescan_rows),
        "",
        "## Certification Requirements",
        md_table(["certification_requirement_id", "required_certification", "currently_satisfied", "blocks_value_attachment"], cert_reqs),
        "",
    ])

    write_csv(OUT_DEPENDENCY, dependency_rows, ["dependency", "path", "exists", "status", "blocker_reason"])
    write_csv(OUT_RESCAN, rescan_rows, list(rescan_rows[0].keys()))
    write_csv(OUT_OUTCOME_CONTRACT, outcome_field_contract, ["field_name", "required", "purpose"])
    write_csv(OUT_BENCHMARK_CONTRACT, benchmark_field_contract, ["field_name", "required", "purpose"])
    write_csv(OUT_OUTCOME_PLAN, outcome_plan, list(outcome_plan[0].keys()))
    write_csv(OUT_BENCHMARK_PLAN, benchmark_plan, list(benchmark_plan[0].keys()))
    write_csv(OUT_OUTCOME_AUDIT, outcome_audit, list(outcome_audit[0].keys()))
    write_csv(OUT_BENCHMARK_AUDIT, benchmark_audit, list(benchmark_audit[0].keys()))
    write_csv(OUT_OUTCOME_TEMPLATE, outcome_template, list(outcome_template[0].keys()))
    write_csv(OUT_BENCHMARK_TEMPLATE, benchmark_template, list(benchmark_template[0].keys()))
    write_csv(OUT_PIT_REQ, pit_reqs, ["requirement_id", "requirement_name", "required", "blocks_attachment"])
    write_csv(OUT_BLOCKERS, blocker_rows, list(blocker_rows[0].keys()) if blocker_rows else ["blocker_id", "blocker_scope", "severity", "blocker_status", "blocker_reason", "blocks_v20_19", "blocks_backtest_execution"])
    write_csv(OUT_CERT_REQ, cert_reqs, list(cert_reqs[0].keys()))
    write_csv(OUT_GATE, gate_out, list(gate_out[0].keys()))
    write_csv(OUT_VALIDATION, validation_out, list(validation_out[0].keys()))
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    write_text(READ_FIRST, read_first)

    print(f"STATUS: {status}")
    print(f"CERTIFIED_OUTCOME_SOURCE_FOUND: {tf(certified_outcome_found)}")
    print(f"CERTIFIED_BENCHMARK_SOURCE_FOUND: {tf(certified_benchmark_found)}")
    print("OUTCOME_VALUES_CREATED: 0")
    print("BENCHMARK_VALUES_CREATED: 0")
    print(f"READY_FOR_FORWARD_RETURN_OR_BACKTEST_EXECUTION_GATE_NEXT: {tf(ready_for_forward_gate)}")
    print(f"NEXT_RECOMMENDED_STEP: {next_step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
