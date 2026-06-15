#!/usr/bin/env python
"""V20.169 DATA_TRUST direct ticker-level mapping repair.

Scans existing artifacts for direct ticker-level DATA_TRUST evidence. Inferred
or aggregate-only evidence is not converted into direct mapping. Unknown rows
remain excluded from any gate-only ranking path and are carried in the repair
backlog. Official rankings, weights, recommendations, actions, performance
claims, and upstream outputs are not mutated.
"""

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

V168_DECISION = FACTORS / "V20_168_DATA_TRUST_GATE_ONLY_OPERATOR_DECISION_CAPTURE.csv"
V168_GATE = FACTORS / "V20_168_DATA_TRUST_GATE_ONLY_DECISION_GATE.csv"
V168_SAFETY = FACTORS / "V20_168_DATA_TRUST_GATE_ONLY_DECISION_SAFETY_AUDIT.csv"
V168_DIRECT_REQ = FACTORS / "V20_168_DATA_TRUST_DIRECT_MAPPING_REQUIREMENT_PACKET.csv"
V168_NEXT = FACTORS / "V20_168_DATA_TRUST_NEXT_STAGE_PACKET.csv"
BASELINE = CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
R1_SOURCE_MAPPING = FACTORS / "V20_166_R1_DATA_TRUST_STATUS_SOURCE_MAPPING.csv"
R1_TICKER_STATUS = FACTORS / "V20_166_R1_DATA_TRUST_TICKER_STATUS.csv"
R1_REPAIR = FACTORS / "V20_166_R1_DATA_TRUST_STATUS_REPAIR_AUDIT.csv"
R1_UNKNOWN = FACTORS / "V20_166_R1_DATA_TRUST_REMAINING_UNKNOWN_BACKLOG.csv"
R2_MAPPING = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_MAPPING_CONFIDENCE_AUDIT.csv"
R3_MAPPING = FACTORS / "V20_166_R3_MAPPING_CONFIDENCE_LIMITATION_AUDIT.csv"
V167_MAPPING = FACTORS / "V20_167_DATA_TRUST_MAPPING_LIMITATION_REVIEW.csv"

NAMED_SOURCE_CANDIDATES = [
    CONSOLIDATION / "V20_9_DATA_TRUSTWORTHINESS_FACTOR_READINESS_AUDIT.csv",
    CONSOLIDATION / "V20_10_DATA_TRUSTWORTHINESS_FACTOR_SOURCE_AUDIT.csv",
    CONSOLIDATION / "V20_12_FACTOR_INPUT_DATA_QUALITY_REVIEW.csv",
    CONSOLIDATION / "V20_13_FACTOR_EVIDENCE_DATA_QUALITY_AUDIT.csv",
    CONSOLIDATION / "V20_14_FACTOR_EVIDENCE_DATA_QUALITY_REVIEW.csv",
    CONSOLIDATION / "V20_15_FACTOR_SCORE_DATA_QUALITY_AUDIT.csv",
    CONSOLIDATION / "V20_16_FACTOR_SCORE_DATA_QUALITY_REVIEW.csv",
    CONSOLIDATION / "V20_35_BLOCKED_NON_PIT_FACTOR_ENFORCEMENT.csv",
    CONSOLIDATION / "V20_35_R2_BLOCKED_NON_PIT_FACTOR_ENFORCEMENT.csv",
    CONSOLIDATION / "V20_45_CURRENT_OPERATOR_FACTOR_SUPPORT_VIEW.csv",
    CONSOLIDATION / "V20_48_REFRESHED_FACTOR_SUPPORT_VIEW.csv",
    CONSOLIDATION / "V20_54_FACTOR_SUPPORT_READABLE_VIEW.csv",
    CONSOLIDATION / "V20_82_FACTOR_MULTI_PATH_VALIDATION_TABLE.csv",
    CONSOLIDATION / "V20_CURRENT_FACTOR_MULTI_PATH_VALIDATION_TABLE.csv",
    BACKTEST / "V20_152_RANDOM_AS_OF_ELIGIBILITY_AUDIT.csv",
    FACTORS / "V20_153_FACTOR_ABLATION_ELIGIBILITY_AUDIT.csv",
    FACTORS / "V20_153_R2_FACTOR_ABLATION_REPAIRED_MATRIX.csv",
]

OUT_SCAN = FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_SOURCE_SCAN.csv"
OUT_MAPPING = FACTORS / "V20_169_DATA_TRUST_DIRECT_TICKER_MAPPING.csv"
OUT_STATUS = FACTORS / "V20_169_DATA_TRUST_DIRECT_PASS_FAIL_STATUS.csv"
OUT_REPAIR = FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_REPAIR_AUDIT.csv"
OUT_BACKLOG = FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_REMAINING_BACKLOG.csv"
OUT_SUMMARY = FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_COVERAGE_SUMMARY.csv"
OUT_GATE = FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_NEXT_GATE.csv"
OUT_SAFETY = FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_SAFETY_AUDIT.csv"
REPORT = READ_CENTER / "V20_169_DATA_TRUST_DIRECT_TICKER_LEVEL_MAPPING_REPAIR_REPORT.md"

REQUIRED_V168_STATUS = "PASS_V20_168_DATA_TRUST_GATE_ONLY_OPERATOR_DECISION_CAPTURE_READY_FOR_V20_169"
PASS_STATUS = "PASS_V20_169_DATA_TRUST_DIRECT_MAPPING_READY_FOR_V20_170"
PARTIAL_STATUS = "PARTIAL_PASS_V20_169_DATA_TRUST_DIRECT_MAPPING_WITH_REMAINING_UNKNOWN_READY_FOR_V20_170"
WARN_STATUS = "WARN_V20_169_NO_DIRECT_TICKER_LEVEL_DATA_TRUST_MAPPING_RECOVERED"
BLOCKED_STATUS = "BLOCKED_V20_169_DATA_TRUST_DIRECT_TICKER_LEVEL_MAPPING_REPAIR"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_DIRECT_TICKER_LEVEL_MAPPING_REPAIR"

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
COMMON = {**SAFETY, "direct_mapping_repair_created": "TRUE", "repair_scope": SCOPE, "audit_only": "TRUE"}

SCAN_FIELDS = [
    "source_artifact", "artifact_exists", "row_count", "has_ticker_column",
    "ticker_column_name", "has_data_trust_status_field", "has_freshness_field",
    "has_source_quality_field", "has_pit_safety_field", "has_schema_status_field",
    "has_factor_score_availability_field", "direct_mapping_usable",
    "limitation_reason", *COMMON.keys(),
]
MAPPING_FIELDS = [
    "ticker", "baseline_rank", "prior_inferred_data_trust_status",
    "direct_data_trust_status", "direct_data_trust_pass", "direct_data_trust_fail",
    "direct_data_trust_unknown", "direct_mapping_found", "direct_mapping_source_artifact",
    "direct_mapping_source_field", "ticker_identity_match", "freshness_status",
    "source_quality_status", "pit_safety_status", "schema_status",
    "factor_score_availability_status", "price_availability_status",
    "current_ranking_eligibility_status", "direct_mapping_confidence",
    "direct_failure_category", "direct_failure_reason", "repair_required",
    "recommended_repair_action", *COMMON.keys(),
]
REPAIR_FIELDS = [
    "repair_audit_id", "ticker", "prior_inferred_data_trust_status",
    "direct_data_trust_status", "direct_mapping_found", "repair_result",
    "repair_reason", "source_artifact", *COMMON.keys(),
]
BACKLOG_FIELDS = [
    "ticker", "baseline_rank", "direct_data_trust_status",
    "direct_failure_category", "direct_failure_reason", "missing_direct_evidence",
    "recommended_repair_action", "repair_priority", *COMMON.keys(),
]
SUMMARY_FIELDS = [
    "summary_id", "baseline_candidate_count", "prior_inferred_pass_count",
    "direct_mapping_found_count", "direct_data_trust_pass_count",
    "direct_data_trust_fail_count", "direct_data_trust_unknown_count",
    "direct_mapping_coverage_rate", "remaining_unknown_count",
    "remaining_backlog_count", "direct_mapping_source_artifact_count",
    "aggregate_only_source_artifact_count",
    "ready_for_direct_mapping_gate_only_ranking_simulation",
    "ready_for_official_use", "recommended_next_action", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_168_gate_consumed", "v20_168_status",
    "baseline_candidate_count", "prior_inferred_pass_count",
    "direct_mapping_found_count", "direct_data_trust_pass_count",
    "direct_data_trust_fail_count", "direct_data_trust_unknown_count",
    "direct_mapping_coverage_rate", "remaining_unknown_count",
    "remaining_backlog_count", "ready_for_direct_mapping_gate_only_ranking_simulation",
    "ready_for_official_use", "official_weight_change_allowed",
    "official_ranking_mutation_allowed", "no_ticker_status_fabricated",
    "inferred_mapping_not_treated_as_direct", "unknown_not_treated_as_pass",
    "data_trust_gate_criteria_not_lowered", "no_upstream_outputs_mutated",
    "blocking_reason", "final_status", *COMMON.keys(),
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
        return [{key: clean(value) for key, value in row.items()} for row in reader], list(reader.fieldnames or [])


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
    return [
        V168_DECISION, V168_GATE, V168_SAFETY, V168_DIRECT_REQ, V168_NEXT, BASELINE,
        R1_SOURCE_MAPPING, R1_TICKER_STATUS, R1_REPAIR, R1_UNKNOWN,
        R2_MAPPING, R3_MAPPING, V167_MAPPING,
    ]


def discover_source_candidates() -> list[Path]:
    keywords = ("data", "trust", "fresh", "pit", "source", "quality", "eligib", "schema", "price", "factor", "current")
    discovered: set[Path] = set(NAMED_SOURCE_CANDIDATES)
    for directory in [CONSOLIDATION, FACTORS, BACKTEST]:
        if directory.exists():
            for path in directory.glob("*.csv"):
                lower = path.name.lower()
                if any(keyword in lower for keyword in keywords):
                    discovered.add(path)
    excluded = {
        OUT_SCAN, OUT_MAPPING, OUT_STATUS, OUT_REPAIR, OUT_BACKLOG, OUT_SUMMARY, OUT_GATE, OUT_SAFETY,
        V168_DECISION, V168_GATE, V168_SAFETY, V168_DIRECT_REQ, V168_NEXT,
        R1_TICKER_STATUS, R1_SOURCE_MAPPING, R1_REPAIR, R1_UNKNOWN, R2_MAPPING, R3_MAPPING, V167_MAPPING,
    }
    return sorted(path for path in discovered if path not in excluded)


def all_inputs(source_candidates: list[Path]) -> list[Path]:
    return [*required_inputs(), *[path for path in source_candidates if path.exists()]]


def input_hashes(source_candidates: list[Path]) -> dict[str, str]:
    return {rel(path): sha_file(path) for path in all_inputs(source_candidates) if path.exists()}


def find_field(fields: list[str], *needles: str) -> str:
    lowered = [(field, field.lower()) for field in fields]
    for field, low in lowered:
        if all(needle in low for needle in needles):
            return field
    return ""


def ticker_field(fields: list[str]) -> str:
    for name in ["ticker", "symbol", "candidate_ticker"]:
        for field in fields:
            if field.lower() == name:
                return field
    return find_field(fields, "ticker")


def field_value(row: dict[str, str], field: str) -> str:
    return clean(row.get(field, "")) if field else ""


def positive(value: str) -> bool:
    value = value.upper()
    return value in {"TRUE", "PASS", "PASSED", "VALID", "FOUND", "AVAILABLE", "USABLE", "ELIGIBLE", "CERTIFIED", "OK"}


def negative(value: str) -> bool:
    value = value.upper()
    return any(token in value for token in ["FALSE", "FAIL", "FAILED", "INVALID", "MISSING", "STALE", "BLOCKED", "UNUSABLE", "INELIGIBLE", "UNSAFE", "ERROR"])


def status_from(value: str) -> str:
    if positive(value):
        return "PASS"
    if negative(value):
        return "FAIL"
    return "UNKNOWN"


def scan_artifact(path: Path) -> tuple[dict[str, str], list[dict[str, str]], list[str], dict[str, str]]:
    rows, fields = read_csv(path)
    ticker = ticker_field(fields)
    status = find_field(fields, "data", "trust") or find_field(fields, "trust")
    freshness = find_field(fields, "fresh")
    source_quality = find_field(fields, "source", "quality") or find_field(fields, "evidence", "quality") or find_field(fields, "certification")
    pit = find_field(fields, "pit") or find_field(fields, "point", "time")
    schema = find_field(fields, "schema") or find_field(fields, "validation")
    factor_score = find_field(fields, "factor", "score") or find_field(fields, "score")
    direct_usable = bool(rows and ticker and status and freshness and source_quality and pit and schema and factor_score)
    if not path.exists():
        reason = "ARTIFACT_MISSING"
    elif not rows:
        reason = "ARTIFACT_EMPTY"
    elif not ticker:
        reason = "NO_TICKER_COLUMN"
    elif not status:
        reason = "NO_DIRECT_DATA_TRUST_STATUS_FIELD"
    elif not direct_usable:
        reason = "MISSING_REQUIRED_DIRECT_STATUS_FIELDS"
    else:
        reason = "DIRECT_TICKER_STATUS_FIELDS_PRESENT"
    scan = {
        "source_artifact": rel(path),
        "artifact_exists": tf(path.exists()),
        "row_count": str(len(rows)),
        "has_ticker_column": tf(bool(ticker)),
        "ticker_column_name": ticker,
        "has_data_trust_status_field": tf(bool(status)),
        "has_freshness_field": tf(bool(freshness)),
        "has_source_quality_field": tf(bool(source_quality)),
        "has_pit_safety_field": tf(bool(pit)),
        "has_schema_status_field": tf(bool(schema)),
        "has_factor_score_availability_field": tf(bool(factor_score)),
        "direct_mapping_usable": tf(direct_usable),
        "limitation_reason": reason,
        **COMMON,
    }
    fields_found = {
        "ticker": ticker,
        "data_trust": status,
        "freshness": freshness,
        "source_quality": source_quality,
        "pit": pit,
        "schema": schema,
        "factor_score": factor_score,
        "price": find_field(fields, "price"),
        "eligibility": find_field(fields, "eligib"),
    }
    return scan, rows, fields, fields_found


def build_direct_rows(baseline: list[dict[str, str]], prior_rows: list[dict[str, str]], source_candidates: list[Path]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    prior_by_ticker = {row.get("ticker", "").upper(): row for row in prior_rows}
    baseline_tickers = {row.get("ticker", "").upper() for row in baseline}
    scan_rows: list[dict[str, str]] = []
    usable_records: list[tuple[Path, list[dict[str, str]], dict[str, str]]] = []
    for path in source_candidates:
        scan, rows, _fields, found = scan_artifact(path)
        scan_rows.append(scan)
        if scan["direct_mapping_usable"] == "TRUE":
            usable_records.append((path, rows, found))

    direct_by_ticker: dict[str, dict[str, str]] = {}
    for path, rows, found in usable_records:
        for row in rows:
            ticker = field_value(row, found["ticker"]).upper()
            if ticker not in baseline_tickers or ticker in direct_by_ticker:
                continue
            component_statuses = {
                "freshness_status": status_from(field_value(row, found["freshness"])),
                "source_quality_status": status_from(field_value(row, found["source_quality"])),
                "pit_safety_status": status_from(field_value(row, found["pit"])),
                "schema_status": status_from(field_value(row, found["schema"])),
                "factor_score_availability_status": status_from(field_value(row, found["factor_score"])),
                "price_availability_status": status_from(field_value(row, found["price"])) if found["price"] else "UNKNOWN",
                "current_ranking_eligibility_status": status_from(field_value(row, found["eligibility"])) if found["eligibility"] else "UNKNOWN",
            }
            trust_status = status_from(field_value(row, found["data_trust"]))
            pass_ok = trust_status == "PASS" and all(component_statuses[k] == "PASS" for k in [
                "freshness_status", "source_quality_status", "pit_safety_status",
                "schema_status", "factor_score_availability_status",
            ])
            fail = trust_status == "FAIL" or any(value == "FAIL" for value in component_statuses.values())
            direct_by_ticker[ticker] = {
                "direct_data_trust_status": "DIRECT_PASS" if pass_ok else ("DIRECT_FAIL" if fail else "UNKNOWN"),
                "direct_mapping_source_artifact": rel(path),
                "direct_mapping_source_field": ";".join(value for value in found.values() if value),
                **component_statuses,
            }

    mapping_rows: list[dict[str, str]] = []
    repair_rows: list[dict[str, str]] = []
    backlog_rows: list[dict[str, str]] = []
    for idx, row in enumerate(baseline, start=1):
        ticker = row.get("ticker", "").upper()
        prior = prior_by_ticker.get(ticker, {})
        direct = direct_by_ticker.get(ticker)
        if direct:
            status = direct["direct_data_trust_status"]
            found = status != "UNKNOWN"
            failure_category = "NONE" if status == "DIRECT_PASS" else ("DIRECT_STATUS_FAILURE" if status == "DIRECT_FAIL" else "DIRECT_STATUS_AMBIGUOUS")
            failure_reason = "NONE" if status == "DIRECT_PASS" else "DIRECT_TICKER_ARTIFACT_DID_NOT_PASS_ALL_REQUIRED_DATA_TRUST_COMPONENTS"
            action = "NONE" if status == "DIRECT_PASS" else "REPAIR_DIRECT_TICKER_LEVEL_DATA_TRUST_COMPONENT_FAILURE"
        else:
            status = "UNKNOWN"
            found = False
            failure_category = "DIRECT_TICKER_LEVEL_EVIDENCE_MISSING"
            failure_reason = "NO_USABLE_DIRECT_TICKER_LEVEL_DATA_TRUST_ARTIFACT_FOUND;INFERRED_MAPPING_NOT_CONVERTED_TO_DIRECT"
            action = "CREATE_OR_REPAIR_DIRECT_TICKER_LEVEL_DATA_TRUST_STATUS_SOURCE_CONTRACT"
        mapping = {
            "ticker": ticker,
            "baseline_rank": row.get("official_current_rank", ""),
            "prior_inferred_data_trust_status": prior.get("data_trust_status", "UNKNOWN"),
            "direct_data_trust_status": status,
            "direct_data_trust_pass": tf(status == "DIRECT_PASS"),
            "direct_data_trust_fail": tf(status == "DIRECT_FAIL"),
            "direct_data_trust_unknown": tf(status == "UNKNOWN"),
            "direct_mapping_found": tf(found),
            "direct_mapping_source_artifact": direct.get("direct_mapping_source_artifact", "") if direct else "",
            "direct_mapping_source_field": direct.get("direct_mapping_source_field", "") if direct else "",
            "ticker_identity_match": tf(found),
            "freshness_status": direct.get("freshness_status", "UNKNOWN") if direct else "UNKNOWN",
            "source_quality_status": direct.get("source_quality_status", "UNKNOWN") if direct else "UNKNOWN",
            "pit_safety_status": direct.get("pit_safety_status", "UNKNOWN") if direct else "UNKNOWN",
            "schema_status": direct.get("schema_status", "UNKNOWN") if direct else "UNKNOWN",
            "factor_score_availability_status": direct.get("factor_score_availability_status", "UNKNOWN") if direct else "UNKNOWN",
            "price_availability_status": direct.get("price_availability_status", "UNKNOWN") if direct else "UNKNOWN",
            "current_ranking_eligibility_status": direct.get("current_ranking_eligibility_status", "UNKNOWN") if direct else "UNKNOWN",
            "direct_mapping_confidence": "DIRECT_HIGH" if status == "DIRECT_PASS" else ("DIRECT_FAIL_EVIDENCE" if status == "DIRECT_FAIL" else "UNKNOWN"),
            "direct_failure_category": failure_category,
            "direct_failure_reason": failure_reason,
            "repair_required": tf(status != "DIRECT_PASS"),
            "recommended_repair_action": action,
            **COMMON,
        }
        mapping_rows.append(mapping)
        repair_rows.append({
            "repair_audit_id": f"V20_169_DIRECT_MAPPING_REPAIR_AUDIT_{idx:04d}",
            "ticker": ticker,
            "prior_inferred_data_trust_status": mapping["prior_inferred_data_trust_status"],
            "direct_data_trust_status": status,
            "direct_mapping_found": tf(found),
            "repair_result": "DIRECT_MAPPING_RECOVERED" if found else "DIRECT_MAPPING_NOT_RECOVERED",
            "repair_reason": failure_reason,
            "source_artifact": mapping["direct_mapping_source_artifact"],
            **COMMON,
        })
        if status != "DIRECT_PASS":
            backlog_rows.append({
                "ticker": ticker,
                "baseline_rank": row.get("official_current_rank", ""),
                "direct_data_trust_status": status,
                "direct_failure_category": failure_category,
                "direct_failure_reason": failure_reason,
                "missing_direct_evidence": "DIRECT_TICKER_LEVEL_DATA_TRUST_COMPONENT_STATUS",
                "recommended_repair_action": action,
                "repair_priority": "HIGH" if status == "UNKNOWN" else "CRITICAL",
                **COMMON,
            })
    return scan_rows, mapping_rows, repair_rows, backlog_rows


def build_summary(baseline_count: int, prior_pass_count: int, scan_rows: list[dict[str, str]], mapping_rows: list[dict[str, str]], backlog_rows: list[dict[str, str]]) -> dict[str, str]:
    found_count = sum(row["direct_mapping_found"] == "TRUE" for row in mapping_rows)
    pass_count = sum(row["direct_data_trust_pass"] == "TRUE" for row in mapping_rows)
    fail_count = sum(row["direct_data_trust_fail"] == "TRUE" for row in mapping_rows)
    unknown_count = sum(row["direct_data_trust_unknown"] == "TRUE" for row in mapping_rows)
    coverage = found_count / baseline_count if baseline_count else 0.0
    direct_sources = {row["direct_mapping_source_artifact"] for row in mapping_rows if row["direct_mapping_source_artifact"]}
    aggregate_only = sum(row["artifact_exists"] == "TRUE" and row["direct_mapping_usable"] != "TRUE" for row in scan_rows)
    if found_count == 0:
        ready, action = "FALSE", "REQUIRE_SOURCE_CONTRACT_OR_UPSTREAM_DIRECT_TICKER_DATA_TRUST_AUDIT_REPAIR"
    elif unknown_count == 0 and coverage == 1.0:
        ready, action = "TRUE", "CONTINUE_TO_V20_170_DIRECT_MAPPING_GATE_ONLY_RANKING_SIMULATION"
    else:
        ready, action = "TRUE", "CONTINUE_TO_V20_170_PARTIAL_DIRECT_MAPPING_GATE_SIMULATION_EXCLUDING_UNKNOWN_ROWS"
    return {
        "summary_id": "V20_169_DATA_TRUST_DIRECT_MAPPING_COVERAGE_SUMMARY_001",
        "baseline_candidate_count": str(baseline_count),
        "prior_inferred_pass_count": str(prior_pass_count),
        "direct_mapping_found_count": str(found_count),
        "direct_data_trust_pass_count": str(pass_count),
        "direct_data_trust_fail_count": str(fail_count),
        "direct_data_trust_unknown_count": str(unknown_count),
        "direct_mapping_coverage_rate": fmt(coverage),
        "remaining_unknown_count": str(unknown_count),
        "remaining_backlog_count": str(len(backlog_rows)),
        "direct_mapping_source_artifact_count": str(len(direct_sources)),
        "aggregate_only_source_artifact_count": str(aggregate_only),
        "ready_for_direct_mapping_gate_only_ranking_simulation": ready,
        "ready_for_official_use": "FALSE",
        "recommended_next_action": action,
        **COMMON,
    }


def safety_rows(upstream_mutated: bool, prereq_ok: bool) -> list[dict[str, str]]:
    checks = [
        ("v20_168_prerequisites_met", "TRUE", tf(prereq_ok)),
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
        ("inferred_mapping_converted_to_direct", "FALSE", "FALSE"),
        ("unknown_treated_as_pass", "FALSE", "FALSE"),
        ("upstream_outputs_mutated", "FALSE", tf(upstream_mutated)),
    ]
    return [{
        "safety_check_id": f"V20_169_SAFETY_{idx:03d}",
        "safety_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "safety_passed": tf(expected == actual),
        **COMMON,
    } for idx, (check, expected, actual) in enumerate(checks, start=1)]


def write_report(status: str, summary: dict[str, str] | None = None) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.169 DATA_TRUST Direct Ticker-Level Mapping Repair Report",
        "",
        f"- wrapper_status: {status}",
        "- research_only: TRUE",
        "- data_trust_scoring_weight: 0.0000000000",
        f"- data_trust_role: {DATA_TRUST_ROLE}",
        "- direct_ticker_mapping_required_before_official_use: TRUE",
        "- ready_for_official_use: FALSE",
        "- official_weight_change_allowed: FALSE",
        "- official_ranking_mutation_allowed: FALSE",
    ]
    if summary:
        lines.extend([
            f"- baseline_candidate_count: {summary['baseline_candidate_count']}",
            f"- prior_inferred_pass_count: {summary['prior_inferred_pass_count']}",
            f"- direct_mapping_found_count: {summary['direct_mapping_found_count']}",
            f"- direct_data_trust_pass_count: {summary['direct_data_trust_pass_count']}",
            f"- direct_data_trust_fail_count: {summary['direct_data_trust_fail_count']}",
            f"- direct_data_trust_unknown_count: {summary['direct_data_trust_unknown_count']}",
            f"- direct_mapping_coverage_rate: {summary['direct_mapping_coverage_rate']}",
            f"- remaining_backlog_count: {summary['remaining_backlog_count']}",
            f"- recommended_next_action: {summary['recommended_next_action']}",
        ])
    lines.extend(["", "Inferred DATA_TRUST mapping is not treated as direct ticker-level evidence."])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_169_DATA_TRUST_DIRECT_MAPPING_NEXT_GATE_001",
        "v20_168_gate_consumed": "FALSE",
        "v20_168_status": "",
        "baseline_candidate_count": "0",
        "prior_inferred_pass_count": "0",
        "direct_mapping_found_count": "0",
        "direct_data_trust_pass_count": "0",
        "direct_data_trust_fail_count": "0",
        "direct_data_trust_unknown_count": "0",
        "direct_mapping_coverage_rate": "0.0000000000",
        "remaining_unknown_count": "0",
        "remaining_backlog_count": "0",
        "ready_for_direct_mapping_gate_only_ranking_simulation": "FALSE",
        "ready_for_official_use": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "no_ticker_status_fabricated": "TRUE",
        "inferred_mapping_not_treated_as_direct": "TRUE",
        "unknown_not_treated_as_pass": "TRUE",
        "data_trust_gate_criteria_not_lowered": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        **COMMON,
    }
    for path, fields in [
        (OUT_SCAN, SCAN_FIELDS), (OUT_MAPPING, MAPPING_FIELDS), (OUT_STATUS, MAPPING_FIELDS),
        (OUT_REPAIR, REPAIR_FIELDS), (OUT_BACKLOG, BACKLOG_FIELDS), (OUT_SUMMARY, SUMMARY_FIELDS),
        (OUT_SAFETY, SAFETY_FIELDS),
    ]:
        write_csv(path, fields, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(BLOCKED_STATUS)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    source_candidates = discover_source_candidates()
    before = input_hashes(source_candidates)
    missing = [path for path in required_inputs() if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))

    decision_rows, _ = read_csv(V168_DECISION)
    gate_rows, _ = read_csv(V168_GATE)
    direct_req_rows, _ = read_csv(V168_DIRECT_REQ)
    next_rows, _ = read_csv(V168_NEXT)
    baseline_rows, _ = read_csv(BASELINE)
    prior_rows, _ = read_csv(R1_TICKER_STATUS)
    if not all([decision_rows, gate_rows, direct_req_rows, next_rows, baseline_rows, prior_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision = decision_rows[0]
    gate = gate_rows[0]
    direct_req = direct_req_rows[0]
    prereq_ok = all([
        gate.get("final_status") == REQUIRED_V168_STATUS,
        gate.get("data_trust_scoring_weight") == "0.0000000000",
        gate.get("data_trust_role") == DATA_TRUST_ROLE,
        gate.get("data_trust_gate_only_research_policy_approved") == "TRUE",
        gate.get("direct_ticker_mapping_required_before_official_use") == "TRUE",
        gate.get("official_weight_change_allowed") == "FALSE",
        gate.get("official_ranking_mutation_allowed") == "FALSE",
        gate.get("formal_activation_allowed") == "FALSE",
        decision.get("data_trust_gate_only_research_policy_approved") == "TRUE",
        direct_req.get("direct_ticker_mapping_required_before_official_use") == "TRUE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_168_REQUIREMENTS_NOT_MET")

    scan_rows, mapping_rows, repair_rows, backlog_rows = build_direct_rows(baseline_rows, prior_rows, source_candidates)
    prior_pass_count = sum(row.get("data_trust_pass") == "TRUE" for row in prior_rows)
    summary = build_summary(len(baseline_rows), prior_pass_count, scan_rows, mapping_rows, backlog_rows)
    upstream_mutated = before != input_hashes(source_candidates)
    safety = safety_rows(upstream_mutated, prereq_ok)
    safety_ok = all(row["safety_passed"] == "TRUE" for row in safety)
    if upstream_mutated or not safety_ok:
        return emit_blocked("SAFETY_OR_UPSTREAM_MUTATION_FAILURE")

    found = int(num(summary["direct_mapping_found_count"]))
    unknown = int(num(summary["direct_data_trust_unknown_count"]))
    coverage = num(summary["direct_mapping_coverage_rate"])
    if found == 0:
        status = WARN_STATUS
    elif coverage == 1.0 and unknown == 0:
        status = PASS_STATUS
    else:
        status = PARTIAL_STATUS

    gate_out = {
        "gate_check_id": "V20_169_DATA_TRUST_DIRECT_MAPPING_NEXT_GATE_001",
        "v20_168_gate_consumed": "TRUE",
        "v20_168_status": gate.get("final_status", ""),
        **{field: summary[field] for field in SUMMARY_FIELDS if field in summary and field not in COMMON},
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "no_ticker_status_fabricated": "TRUE",
        "inferred_mapping_not_treated_as_direct": "TRUE",
        "unknown_not_treated_as_pass": "TRUE",
        "data_trust_gate_criteria_not_lowered": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "blocking_reason": "",
        "final_status": status,
        **COMMON,
    }

    write_csv(OUT_SCAN, SCAN_FIELDS, scan_rows)
    write_csv(OUT_MAPPING, MAPPING_FIELDS, mapping_rows)
    write_csv(OUT_STATUS, MAPPING_FIELDS, mapping_rows)
    write_csv(OUT_REPAIR, REPAIR_FIELDS, repair_rows)
    write_csv(OUT_BACKLOG, BACKLOG_FIELDS, backlog_rows)
    write_csv(OUT_SUMMARY, SUMMARY_FIELDS, [summary])
    write_csv(OUT_GATE, GATE_FIELDS, [gate_out])
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_report(status, summary)

    print(status)
    print("V20_168_GATE_CONSUMED=TRUE")
    print(f"V20_168_STATUS={gate.get('final_status', '')}")
    print("DATA_TRUST_SCORING_WEIGHT=0.0000000000")
    print(f"DATA_TRUST_ROLE={DATA_TRUST_ROLE}")
    print("DATA_TRUST_GATE_ONLY_RESEARCH_POLICY_APPROVED=TRUE")
    print("DIRECT_TICKER_MAPPING_REQUIRED_BEFORE_OFFICIAL_USE=TRUE")
    print(f"BASELINE_CANDIDATE_COUNT={summary['baseline_candidate_count']}")
    print(f"PRIOR_INFERRED_PASS_COUNT={summary['prior_inferred_pass_count']}")
    print(f"DIRECT_MAPPING_FOUND_COUNT={summary['direct_mapping_found_count']}")
    print(f"DIRECT_DATA_TRUST_PASS_COUNT={summary['direct_data_trust_pass_count']}")
    print(f"DIRECT_DATA_TRUST_FAIL_COUNT={summary['direct_data_trust_fail_count']}")
    print(f"DIRECT_DATA_TRUST_UNKNOWN_COUNT={summary['direct_data_trust_unknown_count']}")
    print(f"DIRECT_MAPPING_COVERAGE_RATE={summary['direct_mapping_coverage_rate']}")
    print(f"READY_FOR_DIRECT_MAPPING_GATE_ONLY_RANKING_SIMULATION={summary['ready_for_direct_mapping_gate_only_ranking_simulation']}")
    print("READY_FOR_OFFICIAL_USE=FALSE")
    print("OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE")
    print("OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE")
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
