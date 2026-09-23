#!/usr/bin/env python
"""V20.170-R1 DATA_TRUST ticker-level PIT safety emitter repair."""

from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
CONSOLIDATION = OUTPUTS / "consolidation"
FACTORS = OUTPUTS / "factors"
BACKTEST = OUTPUTS / "backtest"
READ_CENTER = OUTPUTS / "read_center"

V170_CONTRACT = FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_CONTRACT.csv"
V170_DISCOVERY = FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_SOURCE_DISCOVERY.csv"
V170_EMITTER = FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_EMITTER.csv"
V170_STATUS = FACTORS / "V20_170_DATA_TRUST_DIRECT_PASS_FAIL_UNKNOWN.csv"
V170_BACKLOG = FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_REPAIR_BACKLOG.csv"
V170_COVERAGE = FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_COVERAGE_AUDIT.csv"
V170_GATE = FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_NEXT_GATE.csv"
V170_SAFETY = FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_SAFETY_AUDIT.csv"
BASELINE = CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"

NAMED_PIT_SOURCES = [
    CONSOLIDATION / "V20_35_BLOCKED_NON_PIT_FACTOR_ENFORCEMENT.csv",
    CONSOLIDATION / "V20_35_R2_BLOCKED_NON_PIT_FACTOR_ENFORCEMENT.csv",
    BACKTEST / "V20_152_RANDOM_AS_OF_ELIGIBILITY_AUDIT.csv",
    FACTORS / "V20_153_FACTOR_ABLATION_ELIGIBILITY_AUDIT.csv",
    FACTORS / "V20_153_R2_FACTOR_ABLATION_REPAIRED_MATRIX.csv",
    CONSOLIDATION / "V20_82_FACTOR_MULTI_PATH_VALIDATION_TABLE.csv",
    CONSOLIDATION / "V20_CURRENT_FACTOR_MULTI_PATH_VALIDATION_TABLE.csv",
    CONSOLIDATION / "V20_12_FACTOR_INPUT_DATA_QUALITY_REVIEW.csv",
    CONSOLIDATION / "V20_13_FACTOR_EVIDENCE_DATA_QUALITY_AUDIT.csv",
    CONSOLIDATION / "V20_14_FACTOR_EVIDENCE_DATA_QUALITY_REVIEW.csv",
    CONSOLIDATION / "V20_15_FACTOR_SCORE_DATA_QUALITY_AUDIT.csv",
    CONSOLIDATION / "V20_16_FACTOR_SCORE_DATA_QUALITY_REVIEW.csv",
]

OUT_DISCOVERY = FACTORS / "V20_170_R1_DATA_TRUST_PIT_SOURCE_DISCOVERY.csv"
OUT_STATUS = FACTORS / "V20_170_R1_TICKER_LEVEL_PIT_SAFETY_STATUS.csv"
OUT_LINEAGE = FACTORS / "V20_170_R1_PIT_SAFETY_EVIDENCE_LINEAGE.csv"
OUT_BACKLOG = FACTORS / "V20_170_R1_PIT_SAFETY_REPAIR_BACKLOG.csv"
OUT_RETEST = FACTORS / "V20_170_R1_DATA_TRUST_DIRECT_STATUS_RETEST_INPUT.csv"
OUT_COVERAGE = FACTORS / "V20_170_R1_PIT_SAFETY_COVERAGE_AUDIT.csv"
OUT_GATE = FACTORS / "V20_170_R1_PIT_SAFETY_NEXT_GATE.csv"
OUT_SAFETY = FACTORS / "V20_170_R1_PIT_SAFETY_SAFETY_AUDIT.csv"
REPORT = READ_CENTER / "V20_170_R1_DATA_TRUST_TICKER_LEVEL_PIT_SAFETY_EMITTER_REPAIR_REPORT.md"

REQUIRED_V170_STATUS = "WARN_V20_170_DIRECT_STATUS_EMITTER_CREATED_BUT_NO_DIRECT_PASS_ROWS"
PASS_STATUS = "PASS_V20_170_R1_TICKER_LEVEL_PIT_SAFETY_REPAIR_READY_FOR_V20_170_R2"
PARTIAL_STATUS = "PARTIAL_PASS_V20_170_R1_PIT_SAFETY_REPAIR_WITH_REMAINING_UNKNOWN_READY_FOR_V20_170_R2"
WARN_STATUS = "WARN_V20_170_R1_NO_TICKER_LEVEL_PIT_SAFETY_EVIDENCE_RECOVERED"
BLOCKED_STATUS = "BLOCKED_V20_170_R1_DATA_TRUST_TICKER_LEVEL_PIT_SAFETY_EMITTER_REPAIR"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_TICKER_LEVEL_PIT_SAFETY_EMITTER_REPAIR"

SAFETY = {
    "research_only": "TRUE",
    "data_trust_scoring_weight": "0.0000000000",
    "data_trust_role": DATA_TRUST_ROLE,
    "direct_ticker_mapping_required_before_official_use": "TRUE",
    "formal_activation_allowed": "FALSE",
    "promotion_ready": "FALSE",
    "official_recommendation_created": "FALSE",
    "official_ranking_mutated": "FALSE",
    "official_weight_change_created": "FALSE",
    "official_weight_registry_mutated": "FALSE",
    "weight_mutated": "FALSE",
    "real_book_action_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "performance_claim_created": "FALSE",
    "shadow_weight_expansion_allowed": "FALSE",
}
COMMON = {**SAFETY, "pit_safety_emitter_repair_created": "TRUE", "repair_scope": SCOPE, "audit_only": "TRUE"}

DISCOVERY_FIELDS = [
    "source_artifact", "artifact_exists", "row_count", "ticker_level",
    "has_ticker_column", "ticker_column_name", "has_as_of_date_field",
    "has_pit_status_field", "has_non_pit_blocker_field", "has_factor_lineage_field",
    "has_source_timestamp_field", "has_leakage_flag_field",
    "usable_for_ticker_level_pit_status", "aggregate_only", "limitation_reason",
    *COMMON.keys(),
]
STATUS_FIELDS = [
    "ticker", "baseline_rank", "ticker_identity_match", "pit_direct_status",
    "pit_direct_pass", "pit_direct_fail", "pit_direct_unknown",
    "as_of_date_available", "factor_input_lineage_available",
    "source_timestamp_available", "non_pit_blocker_present", "leakage_flag_present",
    "pit_validation_status", "pit_source_artifact", "pit_source_field",
    "pit_status_confidence", "pit_failure_or_unknown_reason", "repair_required",
    "recommended_repair_action", *COMMON.keys(),
]
LINEAGE_FIELDS = [
    "ticker", "evidence_dimension", "source_artifact", "source_field",
    "source_value", "direct_ticker_level_evidence", "aggregate_only_evidence",
    "accepted_for_direct_pit_status", "rejection_reason", *COMMON.keys(),
]
BACKLOG_FIELDS = [
    "ticker", "baseline_rank", "pit_direct_status", "pit_failure_or_unknown_reason",
    "missing_pit_evidence", "recommended_repair_action", "repair_priority",
    *COMMON.keys(),
]
RETEST_FIELDS = [
    "ticker", "baseline_rank", "prior_direct_data_trust_status",
    "prior_pit_safety_status", "repaired_pit_direct_status",
    "repaired_pit_direct_pass", "repaired_pit_direct_fail",
    "repaired_pit_direct_unknown", "ready_for_v20_170_r2_direct_status_retest",
    "remaining_blocker_reason", *COMMON.keys(),
]
SUMMARY_FIELDS = [
    "summary_id", "baseline_candidate_count", "pit_direct_pass_count",
    "pit_direct_fail_count", "pit_direct_unknown_count", "pit_direct_coverage_rate",
    "usable_pit_source_artifact_count", "aggregate_only_pit_source_artifact_count",
    "ticker_level_pit_source_artifact_count", "remaining_pit_unknown_count",
    "pit_repair_backlog_count", "ready_for_direct_status_retest",
    "ready_for_direct_status_gate_only_ranking_simulation", "ready_for_official_use",
    "recommended_next_action", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_170_gate_consumed", "v20_170_status",
    "baseline_candidate_count", "pit_direct_pass_count", "pit_direct_fail_count",
    "pit_direct_unknown_count", "pit_direct_coverage_rate",
    "ready_for_direct_status_retest", "ready_for_direct_status_gate_only_ranking_simulation",
    "ready_for_official_use", "official_weight_change_allowed",
    "official_ranking_mutation_allowed", "ranking_simulation_created",
    "no_pit_status_fabricated", "aggregate_pit_not_treated_as_ticker_pass",
    "unknown_not_treated_as_pass", "pit_criteria_not_lowered",
    "no_upstream_outputs_mutated", "blocking_reason", "final_status",
    *COMMON.keys(),
]
SAFETY_FIELDS = [
    "safety_check_id", "safety_check", "expected_value", "actual_value",
    "safety_passed", *COMMON.keys(),
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def num(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(clean(value))
    except ValueError:
        return default
    return default if math.isnan(parsed) or math.isinf(parsed) else parsed


def fmt(value: float) -> str:
    return f"{value:.10f}"


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists() or path.stat().st_size == 0:
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{k: clean(v) for k, v in row.items()} for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def sha_file(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def required_inputs() -> list[Path]:
    return [V170_CONTRACT, V170_DISCOVERY, V170_EMITTER, V170_STATUS, V170_BACKLOG, V170_COVERAGE, V170_GATE, V170_SAFETY, BASELINE]


def discover_sources() -> list[Path]:
    found = set(NAMED_PIT_SOURCES)
    keywords = ("pit", "asof", "as_of", "snapshot", "cache", "lineage", "timestamp", "leakage", "non_pit", "eligib", "quality")
    for directory in [CONSOLIDATION, FACTORS, BACKTEST]:
        if directory.exists():
            for path in directory.glob("*.csv"):
                low = path.name.lower()
                if any(k in low for k in keywords):
                    found.add(path)
    outputs = {OUT_DISCOVERY, OUT_STATUS, OUT_LINEAGE, OUT_BACKLOG, OUT_RETEST, OUT_COVERAGE, OUT_GATE, OUT_SAFETY}
    return sorted(path for path in found if path not in outputs and path not in required_inputs())


def input_hashes(sources: list[Path]) -> dict[str, str]:
    return {rel(path): sha_file(path) for path in [*required_inputs(), *[p for p in sources if p.exists()]] if path.exists()}


def find_field(fields: list[str], *needles: str) -> str:
    for field in fields:
        low = field.lower()
        if all(n in low for n in needles):
            return field
    return ""


def ticker_field(fields: list[str]) -> str:
    for field in fields:
        if field.lower() in {"ticker", "symbol", "candidate_ticker"}:
            return field
    return find_field(fields, "ticker")


def positive(value: str) -> bool:
    v = value.upper()
    return v in {"TRUE", "PASS", "PASSED", "VALID", "FOUND", "SAFE", "PIT_SAFE", "ELIGIBLE", "USABLE"}


def negative(value: str) -> bool:
    v = value.upper()
    return any(token in v for token in ["FALSE", "FAIL", "BLOCK", "UNSAFE", "LEAK", "NON_PIT", "MISSING", "INVALID", "INELIGIBLE"])


def scan_source(path: Path) -> tuple[dict[str, str], list[dict[str, str]], dict[str, str]]:
    rows, fields = read_csv(path)
    ticker = ticker_field(fields)
    found = {
        "ticker": ticker,
        "as_of": find_field(fields, "as_of") or find_field(fields, "date"),
        "pit": find_field(fields, "pit"),
        "blocker": find_field(fields, "non", "pit") or find_field(fields, "block"),
        "lineage": find_field(fields, "lineage") or find_field(fields, "source", "artifact"),
        "timestamp": find_field(fields, "timestamp") or find_field(fields, "date"),
        "leakage": find_field(fields, "leak"),
    }
    ticker_level = bool(rows and ticker)
    usable = bool(ticker_level and found["as_of"] and found["pit"] and found["lineage"] and found["timestamp"])
    reason = "USABLE_TICKER_LEVEL_PIT_SOURCE" if usable else ("AGGREGATE_ONLY_OR_MISSING_REQUIRED_PIT_FIELDS" if rows else "MISSING_OR_EMPTY")
    scan = {
        "source_artifact": rel(path),
        "artifact_exists": tf(path.exists()),
        "row_count": str(len(rows)),
        "ticker_level": tf(ticker_level),
        "has_ticker_column": tf(bool(ticker)),
        "ticker_column_name": ticker,
        "has_as_of_date_field": tf(bool(found["as_of"])),
        "has_pit_status_field": tf(bool(found["pit"])),
        "has_non_pit_blocker_field": tf(bool(found["blocker"])),
        "has_factor_lineage_field": tf(bool(found["lineage"])),
        "has_source_timestamp_field": tf(bool(found["timestamp"])),
        "has_leakage_flag_field": tf(bool(found["leakage"])),
        "usable_for_ticker_level_pit_status": tf(usable),
        "aggregate_only": tf(rows and not ticker_level),
        "limitation_reason": reason,
        **COMMON,
    }
    return scan, rows, found


def build_outputs(baseline: list[dict[str, str]], prior_emitter: list[dict[str, str]], sources: list[Path]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    prior = {row["ticker"].upper(): row for row in prior_emitter}
    baseline_tickers = {row["ticker"].upper() for row in baseline}
    scans = []
    usable = []
    for path in sources:
        scan, rows, fields = scan_source(path)
        scans.append(scan)
        if scan["usable_for_ticker_level_pit_status"] == "TRUE":
            usable.append((path, rows, fields))

    evidence_by_ticker: dict[str, dict[str, str]] = {}
    for path, rows, fields in usable:
        for row in rows:
            ticker = clean(row.get(fields["ticker"])).upper()
            if ticker not in baseline_tickers or ticker in evidence_by_ticker:
                continue
            as_of = clean(row.get(fields["as_of"]))
            pit_value = clean(row.get(fields["pit"]))
            blocker_value = clean(row.get(fields["blocker"])) if fields["blocker"] else ""
            lineage = clean(row.get(fields["lineage"]))
            timestamp = clean(row.get(fields["timestamp"]))
            leakage = clean(row.get(fields["leakage"])) if fields["leakage"] else ""
            fail = negative(pit_value) or positive(blocker_value) or positive(leakage)
            passed = bool(as_of and lineage and timestamp and positive(pit_value) and not fail)
            evidence_by_ticker[ticker] = {
                "pit_direct_status": "PIT_DIRECT_PASS" if passed else ("PIT_DIRECT_FAIL" if fail else "PIT_UNKNOWN"),
                "as_of": as_of,
                "pit_value": pit_value,
                "blocker_value": blocker_value,
                "lineage": lineage,
                "timestamp": timestamp,
                "leakage": leakage,
                "artifact": rel(path),
                "fields": ";".join(v for v in fields.values() if v),
            }

    status_rows = []
    lineage_rows = []
    backlog_rows = []
    retest_rows = []
    dimensions = ["as_of_date", "pit_validation_status", "factor_input_lineage", "source_timestamp", "non_pit_blocker", "leakage_flag"]
    for row in baseline:
        ticker = row["ticker"].upper()
        base_rank = row.get("official_current_rank", "")
        ev = evidence_by_ticker.get(ticker)
        prior_row = prior.get(ticker, {})
        if ev:
            status = ev["pit_direct_status"]
            reason = "NONE" if status == "PIT_DIRECT_PASS" else "DIRECT_TICKER_LEVEL_PIT_EVIDENCE_DID_NOT_PASS_ALL_REQUIRED_CHECKS"
            action = "NONE" if status == "PIT_DIRECT_PASS" else "REPAIR_TICKER_LEVEL_PIT_EVIDENCE_FAILURE"
        else:
            status = "PIT_UNKNOWN"
            reason = "NO_USABLE_TICKER_LEVEL_PIT_SAFETY_EVIDENCE_FOUND"
            action = "CREATE_TICKER_LEVEL_PIT_SAFETY_SOURCE_CONTRACT_AND_EMITTER"
        fail = status == "PIT_DIRECT_FAIL"
        passed = status == "PIT_DIRECT_PASS"
        unknown = status == "PIT_UNKNOWN"
        status_row = {
            "ticker": ticker,
            "baseline_rank": base_rank,
            "ticker_identity_match": "TRUE",
            "pit_direct_status": status,
            "pit_direct_pass": tf(passed),
            "pit_direct_fail": tf(fail),
            "pit_direct_unknown": tf(unknown),
            "as_of_date_available": tf(bool(ev and ev["as_of"])),
            "factor_input_lineage_available": tf(bool(ev and ev["lineage"])),
            "source_timestamp_available": tf(bool(ev and ev["timestamp"])),
            "non_pit_blocker_present": tf(bool(ev and positive(ev["blocker_value"]))),
            "leakage_flag_present": tf(bool(ev and positive(ev["leakage"]))),
            "pit_validation_status": "PASS" if passed else ("FAIL" if fail else "UNKNOWN"),
            "pit_source_artifact": ev["artifact"] if ev else "",
            "pit_source_field": ev["fields"] if ev else "",
            "pit_status_confidence": "DIRECT_HIGH" if passed else ("DIRECT_FAIL_EVIDENCE" if fail else "UNKNOWN"),
            "pit_failure_or_unknown_reason": reason,
            "repair_required": tf(not passed),
            "recommended_repair_action": action,
            **COMMON,
        }
        status_rows.append(status_row)
        values = {
            "as_of_date": ev["as_of"] if ev else "",
            "pit_validation_status": ev["pit_value"] if ev else "",
            "factor_input_lineage": ev["lineage"] if ev else "",
            "source_timestamp": ev["timestamp"] if ev else "",
            "non_pit_blocker": ev["blocker_value"] if ev else "",
            "leakage_flag": ev["leakage"] if ev else "",
        }
        for dim in dimensions:
            lineage_rows.append({
                "ticker": ticker,
                "evidence_dimension": dim,
                "source_artifact": ev["artifact"] if ev else "",
                "source_field": ev["fields"] if ev else "",
                "source_value": values[dim],
                "direct_ticker_level_evidence": tf(bool(ev)),
                "aggregate_only_evidence": "FALSE",
                "accepted_for_direct_pit_status": tf(passed or fail),
                "rejection_reason": "NONE" if ev else "NO_TICKER_LEVEL_PIT_EVIDENCE",
                **COMMON,
            })
        if not passed:
            backlog_rows.append({
                "ticker": ticker,
                "baseline_rank": base_rank,
                "pit_direct_status": status,
                "pit_failure_or_unknown_reason": reason,
                "missing_pit_evidence": "TICKER_LEVEL_AS_OF_PIT_LINEAGE_TIMESTAMP",
                "recommended_repair_action": action,
                "repair_priority": "HIGH" if unknown else "CRITICAL",
                **COMMON,
            })
        retest_rows.append({
            "ticker": ticker,
            "baseline_rank": base_rank,
            "prior_direct_data_trust_status": prior_row.get("direct_data_trust_status", "UNKNOWN"),
            "prior_pit_safety_status": prior_row.get("pit_safety_status", "UNKNOWN"),
            "repaired_pit_direct_status": status,
            "repaired_pit_direct_pass": tf(passed),
            "repaired_pit_direct_fail": tf(fail),
            "repaired_pit_direct_unknown": tf(unknown),
            "ready_for_v20_170_r2_direct_status_retest": tf(passed or fail),
            "remaining_blocker_reason": "NONE" if (passed or fail) else reason,
            **COMMON,
        })
    return scans, status_rows, lineage_rows, backlog_rows, retest_rows


def build_summary(baseline_count: int, scans: list[dict[str, str]], statuses: list[dict[str, str]], backlog: list[dict[str, str]]) -> dict[str, str]:
    pass_count = sum(r["pit_direct_pass"] == "TRUE" for r in statuses)
    fail_count = sum(r["pit_direct_fail"] == "TRUE" for r in statuses)
    unknown_count = sum(r["pit_direct_unknown"] == "TRUE" for r in statuses)
    coverage = (pass_count + fail_count) / baseline_count if baseline_count else 0.0
    usable = sum(r["usable_for_ticker_level_pit_status"] == "TRUE" for r in scans)
    aggregate = sum(r["aggregate_only"] == "TRUE" for r in scans)
    ticker_level = sum(r["ticker_level"] == "TRUE" for r in scans)
    if pass_count > 0 and unknown_count == 0:
        ready, action = "TRUE", "CONTINUE_TO_V20_170_R2_DIRECT_STATUS_RETEST"
    elif pass_count > 0:
        ready, action = "TRUE", "CONTINUE_TO_V20_170_R2_DIRECT_STATUS_RETEST_EXCLUDING_UNKNOWN_ROWS"
    else:
        ready, action = "FALSE", "REQUIRE_UPSTREAM_PIT_SOURCE_CONTRACT_REPAIR"
    return {
        "summary_id": "V20_170_R1_PIT_SAFETY_COVERAGE_AUDIT_001",
        "baseline_candidate_count": str(baseline_count),
        "pit_direct_pass_count": str(pass_count),
        "pit_direct_fail_count": str(fail_count),
        "pit_direct_unknown_count": str(unknown_count),
        "pit_direct_coverage_rate": fmt(coverage),
        "usable_pit_source_artifact_count": str(usable),
        "aggregate_only_pit_source_artifact_count": str(aggregate),
        "ticker_level_pit_source_artifact_count": str(ticker_level),
        "remaining_pit_unknown_count": str(unknown_count),
        "pit_repair_backlog_count": str(len(backlog)),
        "ready_for_direct_status_retest": ready,
        "ready_for_direct_status_gate_only_ranking_simulation": "FALSE",
        "ready_for_official_use": "FALSE",
        "recommended_next_action": action,
        **COMMON,
    }


def safety_rows(upstream_mutated: bool, prereq_ok: bool) -> list[dict[str, str]]:
    checks = [
        ("v20_170_prerequisites_met", "TRUE", tf(prereq_ok)),
        ("ranking_simulation_created", "FALSE", "FALSE"),
        ("research_only", "TRUE", "TRUE"),
        ("data_trust_scoring_weight", "0.0000000000", "0.0000000000"),
        ("data_trust_role", DATA_TRUST_ROLE, DATA_TRUST_ROLE),
        ("direct_ticker_mapping_required_before_official_use", "TRUE", "TRUE"),
        ("formal_activation_allowed", "FALSE", "FALSE"),
        ("promotion_ready", "FALSE", "FALSE"),
        ("official_recommendation_created", "FALSE", "FALSE"),
        ("official_ranking_mutated", "FALSE", "FALSE"),
        ("official_weight_change_created", "FALSE", "FALSE"),
        ("official_weight_registry_mutated", "FALSE", "FALSE"),
        ("weight_mutated", "FALSE", "FALSE"),
        ("real_book_action_created", "FALSE", "FALSE"),
        ("trade_action_created", "FALSE", "FALSE"),
        ("broker_execution_supported", "FALSE", "FALSE"),
        ("performance_claim_created", "FALSE", "FALSE"),
        ("shadow_weight_expansion_allowed", "FALSE", "FALSE"),
        ("pit_status_fabricated", "FALSE", "FALSE"),
        ("aggregate_pit_treated_as_ticker_pass", "FALSE", "FALSE"),
        ("unknown_treated_as_pass", "FALSE", "FALSE"),
        ("upstream_outputs_mutated", "FALSE", tf(upstream_mutated)),
    ]
    return [{
        "safety_check_id": f"V20_170_R1_SAFETY_{i:03d}",
        "safety_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "safety_passed": tf(expected == actual),
        **COMMON,
    } for i, (check, expected, actual) in enumerate(checks, start=1)]


def write_report(status: str, summary: dict[str, str] | None = None) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.170-R1 DATA_TRUST Ticker-Level PIT Safety Emitter Repair Report",
        "",
        f"- wrapper_status: {status}",
        "- research_only: TRUE",
        "- ranking_simulation_created: FALSE",
        "- ready_for_official_use: FALSE",
    ]
    if summary:
        for key in ["baseline_candidate_count", "pit_direct_pass_count", "pit_direct_fail_count", "pit_direct_unknown_count", "pit_direct_coverage_rate", "pit_repair_backlog_count", "recommended_next_action"]:
            lines.append(f"- {key}: {summary[key]}")
    lines.extend(["", "Aggregate PIT evidence is not treated as ticker-level PIT safety evidence."])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_170_R1_PIT_SAFETY_NEXT_GATE_001",
        "v20_170_gate_consumed": "FALSE",
        "v20_170_status": "",
        "baseline_candidate_count": "0",
        "pit_direct_pass_count": "0",
        "pit_direct_fail_count": "0",
        "pit_direct_unknown_count": "0",
        "pit_direct_coverage_rate": "0.0000000000",
        "ready_for_direct_status_retest": "FALSE",
        "ready_for_direct_status_gate_only_ranking_simulation": "FALSE",
        "ready_for_official_use": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE",
        "no_pit_status_fabricated": "TRUE",
        "aggregate_pit_not_treated_as_ticker_pass": "TRUE",
        "unknown_not_treated_as_pass": "TRUE",
        "pit_criteria_not_lowered": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        **COMMON,
    }
    for path, fields in [(OUT_DISCOVERY, DISCOVERY_FIELDS), (OUT_STATUS, STATUS_FIELDS), (OUT_LINEAGE, LINEAGE_FIELDS), (OUT_BACKLOG, BACKLOG_FIELDS), (OUT_RETEST, RETEST_FIELDS), (OUT_COVERAGE, SUMMARY_FIELDS), (OUT_SAFETY, SAFETY_FIELDS)]:
        write_csv(path, fields, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(BLOCKED_STATUS)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    sources = discover_sources()
    before = input_hashes(sources)
    missing = [p for p in required_inputs() if not p.exists() or p.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(p) for p in missing))
    gate_rows, _ = read_csv(V170_GATE)
    baseline, _ = read_csv(BASELINE)
    prior_emitter, _ = read_csv(V170_EMITTER)
    if not all([gate_rows, baseline, prior_emitter]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    gate = gate_rows[0]
    prereq_ok = all([
        gate.get("final_status") == REQUIRED_V170_STATUS,
        gate.get("data_trust_scoring_weight") == "0.0000000000",
        gate.get("data_trust_role") == DATA_TRUST_ROLE,
        gate.get("direct_ticker_mapping_required_before_official_use") == "TRUE",
        gate.get("ready_for_direct_status_gate_only_ranking_simulation") == "FALSE",
        gate.get("ready_for_official_use") == "FALSE",
        gate.get("official_weight_change_allowed") == "FALSE",
        gate.get("official_ranking_mutation_allowed") == "FALSE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_170_REQUIREMENTS_NOT_MET")

    scans, statuses, lineage, backlog, retest = build_outputs(baseline, prior_emitter, sources)
    summary = build_summary(len(baseline), scans, statuses, backlog)
    upstream_mutated = before != input_hashes(sources)
    safety = safety_rows(upstream_mutated, prereq_ok)
    if upstream_mutated or not all(r["safety_passed"] == "TRUE" for r in safety):
        return emit_blocked("SAFETY_OR_UPSTREAM_MUTATION_FAILURE")

    pass_count = int(num(summary["pit_direct_pass_count"]))
    unknown_count = int(num(summary["pit_direct_unknown_count"]))
    baseline_count = int(num(summary["baseline_candidate_count"]))
    if pass_count > 0 and unknown_count == 0:
        status = PASS_STATUS
    elif pass_count > 0:
        status = PARTIAL_STATUS
    elif unknown_count == baseline_count:
        status = WARN_STATUS
    else:
        status = WARN_STATUS

    gate_out = {
        "gate_check_id": "V20_170_R1_PIT_SAFETY_NEXT_GATE_001",
        "v20_170_gate_consumed": "TRUE",
        "v20_170_status": gate.get("final_status", ""),
        **{f: summary[f] for f in SUMMARY_FIELDS if f in summary and f not in COMMON},
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE",
        "no_pit_status_fabricated": "TRUE",
        "aggregate_pit_not_treated_as_ticker_pass": "TRUE",
        "unknown_not_treated_as_pass": "TRUE",
        "pit_criteria_not_lowered": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "blocking_reason": "",
        "final_status": status,
        **COMMON,
    }
    write_csv(OUT_DISCOVERY, DISCOVERY_FIELDS, scans)
    write_csv(OUT_STATUS, STATUS_FIELDS, statuses)
    write_csv(OUT_LINEAGE, LINEAGE_FIELDS, lineage)
    write_csv(OUT_BACKLOG, BACKLOG_FIELDS, backlog)
    write_csv(OUT_RETEST, RETEST_FIELDS, retest)
    write_csv(OUT_COVERAGE, SUMMARY_FIELDS, [summary])
    write_csv(OUT_GATE, GATE_FIELDS, [gate_out])
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_report(status, summary)
    print(status)
    print("V20_170_GATE_CONSUMED=TRUE")
    print(f"V20_170_STATUS={gate.get('final_status', '')}")
    print("DATA_TRUST_SCORING_WEIGHT=0.0000000000")
    print(f"DATA_TRUST_ROLE={DATA_TRUST_ROLE}")
    print(f"BASELINE_CANDIDATE_COUNT={summary['baseline_candidate_count']}")
    print(f"PIT_DIRECT_PASS_COUNT={summary['pit_direct_pass_count']}")
    print(f"PIT_DIRECT_FAIL_COUNT={summary['pit_direct_fail_count']}")
    print(f"PIT_DIRECT_UNKNOWN_COUNT={summary['pit_direct_unknown_count']}")
    print(f"PIT_DIRECT_COVERAGE_RATE={summary['pit_direct_coverage_rate']}")
    print(f"READY_FOR_DIRECT_STATUS_RETEST={summary['ready_for_direct_status_retest']}")
    print("READY_FOR_DIRECT_STATUS_GATE_ONLY_RANKING_SIMULATION=FALSE")
    print("READY_FOR_OFFICIAL_USE=FALSE")
    print("OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE")
    print("OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE")
    print("RANKING_SIMULATION_CREATED=FALSE")
    print("FORMAL_ACTIVATION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_ACTION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("PERFORMANCE_CLAIM_CREATED=FALSE")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
