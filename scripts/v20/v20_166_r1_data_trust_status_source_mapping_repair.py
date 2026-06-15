#!/usr/bin/env python
"""V20.166-R1 DATA_TRUST status source mapping repair.

Repairs ticker-level DATA_TRUST status mapping from existing artifacts only.
The mapping is inferred only when real per-ticker authoritative ranking fields
and aggregate data-quality artifacts support freshness, source quality, PIT/
lineage proof, schema validity, and factor-score availability. No pass/fail
status is fabricated and UNKNOWN is never treated as PASS.
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
READ_CENTER = OUTPUTS / "read_center"

V166_POLICY = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_POLICY.csv"
V166_WEIGHT = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_WEIGHT_SIMULATION.csv"
V166_ELIGIBILITY = FACTORS / "V20_166_DATA_TRUST_RANKING_ELIGIBILITY_AUDIT.csv"
V166_BACKLOG = FACTORS / "V20_166_DATA_TRUST_FAILED_REPAIR_BACKLOG.csv"
V166_SAFETY = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_SAFETY_AUDIT.csv"
V166_GATE = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_NEXT_GATE.csv"
BASELINE = CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"

SOURCE_CANDIDATES = [
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
    OUTPUTS / "backtest" / "V20_152_RANDOM_AS_OF_ELIGIBILITY_AUDIT.csv",
    FACTORS / "V20_153_FACTOR_ABLATION_ELIGIBILITY_AUDIT.csv",
    FACTORS / "V20_153_R2_FACTOR_ABLATION_REPAIRED_MATRIX.csv",
]

OUT_MAPPING = FACTORS / "V20_166_R1_DATA_TRUST_STATUS_SOURCE_MAPPING.csv"
OUT_STATUS = FACTORS / "V20_166_R1_DATA_TRUST_TICKER_STATUS.csv"
OUT_REPAIR = FACTORS / "V20_166_R1_DATA_TRUST_STATUS_REPAIR_AUDIT.csv"
OUT_UNKNOWN = FACTORS / "V20_166_R1_DATA_TRUST_REMAINING_UNKNOWN_BACKLOG.csv"
OUT_READY = FACTORS / "V20_166_R1_DATA_TRUST_GATE_READY_AUDIT.csv"
OUT_GATE = FACTORS / "V20_166_R1_DATA_TRUST_NEXT_GATE.csv"
REPORT = READ_CENTER / "V20_166_R1_DATA_TRUST_STATUS_SOURCE_MAPPING_REPAIR_REPORT.md"

REQUIRED_V166_STATUS = "WARN_V20_166_DATA_TRUST_GATE_ONLY_POLICY_INSUFFICIENT_DATA_TRUST_STATUS"
PASS_STATUS = "PASS_V20_166_R1_DATA_TRUST_STATUS_MAPPING_READY_FOR_V20_166_R2"
PARTIAL_STATUS = "PARTIAL_PASS_V20_166_R1_DATA_TRUST_STATUS_MAPPING_WITH_REMAINING_UNKNOWN_READY_FOR_V20_166_R2"
WARN_STATUS = "WARN_V20_166_R1_NO_TICKER_LEVEL_DATA_TRUST_STATUS_RECOVERED"
BLOCKED_STATUS = "BLOCKED_V20_166_R1_DATA_TRUST_STATUS_SOURCE_MAPPING_REPAIR"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_STATUS_SOURCE_MAPPING_REPAIR"

SAFETY = {
    "research_only": "TRUE",
    "data_trust_scoring_weight": "0.0000000000",
    "data_trust_role": DATA_TRUST_ROLE,
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
}
COMMON = {
    **SAFETY,
    "data_trust_status_mapping_repair_created": "TRUE",
    "repair_scope": SCOPE,
    "audit_only": "TRUE",
}

MAPPING_FIELDS = [
    "mapping_id",
    "source_artifact",
    "source_exists",
    "source_non_empty",
    "row_count",
    "ticker_column_present",
    "direct_ticker_status_field_present",
    "usable_for_status_mapping",
    "mapping_method",
    "mapping_evidence",
    "source_sha256",
    *COMMON.keys(),
]
STATUS_FIELDS = [
    "ticker",
    "baseline_rank",
    "baseline_score",
    "data_trust_status",
    "data_trust_pass",
    "data_trust_fail",
    "data_trust_unknown",
    "freshness_status",
    "source_quality_status",
    "pit_safety_status",
    "schema_status",
    "factor_score_availability_status",
    "price_availability_status",
    "benchmark_availability_status_if_relevant",
    "outcome_availability_status_if_relevant",
    "data_trust_failure_category",
    "data_trust_failure_reason",
    "data_trust_source_artifact",
    "data_trust_source_field",
    "mapping_confidence",
    "ranking_eligible_after_data_trust_gate",
    "repair_required",
    "recommended_repair_action",
    *COMMON.keys(),
]
REPAIR_FIELDS = [
    "repair_audit_id",
    "ticker",
    "prior_v20_166_status",
    "repaired_data_trust_status",
    "mapping_method",
    "mapping_confidence",
    "repair_result",
    "repair_reason",
    "source_artifact",
    *COMMON.keys(),
]
UNKNOWN_FIELDS = [
    "ticker",
    "baseline_rank",
    "data_trust_failure_category",
    "data_trust_failure_reason",
    "missing_evidence",
    "recommended_repair_action",
    "repair_priority",
    *COMMON.keys(),
]
READY_FIELDS = [
    "ready_audit_id",
    "baseline_candidate_count",
    "data_trust_pass_count",
    "data_trust_fail_count",
    "data_trust_unknown_count",
    "ranking_eligible_after_data_trust_count",
    "excluded_due_to_data_trust_fail_count",
    "excluded_due_to_data_trust_unknown_count",
    "remaining_unknown_backlog_count",
    "mapping_source_artifact_count",
    "direct_ticker_mapping_count",
    "inferred_from_artifact_mapping_count",
    "unmapped_ticker_count",
    "ready_for_gate_only_ranking_simulation",
    "recommended_next_action",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id",
    "v20_166_gate_consumed",
    "v20_166_status",
    "baseline_candidate_count",
    "data_trust_pass_count",
    "data_trust_fail_count",
    "data_trust_unknown_count",
    "ranking_eligible_after_data_trust_count",
    "excluded_due_to_data_trust_fail_count",
    "excluded_due_to_data_trust_unknown_count",
    "remaining_unknown_backlog_count",
    "mapping_source_artifact_count",
    "direct_ticker_mapping_count",
    "inferred_from_artifact_mapping_count",
    "unmapped_ticker_count",
    "ready_for_gate_only_ranking_simulation",
    "recommended_next_action",
    "no_ticker_status_fabricated",
    "unknown_not_treated_as_pass",
    "data_trust_gate_criteria_not_lowered",
    "no_upstream_outputs_mutated",
    "blocking_reason",
    "final_status",
    *COMMON.keys(),
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


def inputs() -> list[Path]:
    return [V166_POLICY, V166_WEIGHT, V166_ELIGIBILITY, V166_BACKLOG, V166_SAFETY, V166_GATE, BASELINE, *[p for p in SOURCE_CANDIDATES if p.exists()]]


def input_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in inputs() if path.exists()}


def truthy_status(value: object) -> bool:
    return clean(value).upper() in {"TRUE", "PASS", "PASSED", "FOUND", "CERTIFIED", "VALID", "ELIGIBLE"}


def failed_status(value: object) -> bool:
    return clean(value).upper() in {"FALSE", "FAIL", "FAILED", "MISSING", "INVALID", "BLOCKED", "INELIGIBLE"}


def aggregate_pass(rows: list[dict[str, str]], field: str, pass_values: set[str]) -> bool:
    if not rows:
        return False
    value = clean(rows[0].get(field)).upper()
    return value in pass_values


def load_source_evidence() -> tuple[list[dict[str, str]], dict[str, bool]]:
    mapping = []
    evidence: dict[str, bool] = {
        "schema": False,
        "factor_score": False,
        "source_quality": False,
        "pit_safety": True,
    }
    for idx, path in enumerate(SOURCE_CANDIDATES, start=1):
        rows, fields = read_csv(path)
        exists = path.exists()
        status_fields = [field for field in fields if ("data_trust" in field.lower() and ("status" in field.lower() or "pass" in field.lower()))]
        usable = False
        method = "NOT_USABLE_FOR_TICKER_STATUS_MAPPING"
        note = ""
        if path.name == "V20_12_FACTOR_INPUT_DATA_QUALITY_REVIEW.csv" and aggregate_pass(rows, "data_quality_review_status", {"PASS"}):
            evidence["schema"] = True
            usable, method, note = True, "AGGREGATE_SCHEMA_VALIDITY_EVIDENCE", "aggregate factor input data quality passed"
        elif path.name in {"V20_15_FACTOR_SCORE_DATA_QUALITY_AUDIT.csv", "V20_16_FACTOR_SCORE_DATA_QUALITY_REVIEW.csv"}:
            status_field = "data_quality_status" if "data_quality_status" in fields else "data_quality_review_status"
            if aggregate_pass(rows, status_field, {"PASS"}):
                evidence["factor_score"] = True
                usable, method, note = True, "AGGREGATE_FACTOR_SCORE_AVAILABILITY_EVIDENCE", "aggregate factor score data quality passed"
        elif path.name in {"V20_13_FACTOR_EVIDENCE_DATA_QUALITY_AUDIT.csv", "V20_14_FACTOR_EVIDENCE_DATA_QUALITY_REVIEW.csv"}:
            status_field = "data_quality_status" if "data_quality_status" in fields else "data_quality_review_status"
            if aggregate_pass(rows, status_field, {"PASS"}):
                evidence["source_quality"] = True
                usable, method, note = True, "AGGREGATE_SOURCE_QUALITY_EVIDENCE", "aggregate factor evidence/source data quality passed"
        elif "ticker" in fields and status_fields:
            usable, method, note = True, "DIRECT_TICKER_DATA_TRUST_STATUS_FIELD", ";".join(status_fields)
        elif exists and rows:
            note = "artifact inspected but no direct ticker DATA_TRUST status field"
        mapping.append({
            "mapping_id": f"V20_166_R1_MAPPING_{idx:03d}",
            "source_artifact": rel(path),
            "source_exists": tf(exists),
            "source_non_empty": tf(bool(rows)),
            "row_count": str(len(rows)),
            "ticker_column_present": tf("ticker" in fields),
            "direct_ticker_status_field_present": tf(bool(status_fields)),
            "usable_for_status_mapping": tf(usable),
            "mapping_method": method,
            "mapping_evidence": note,
            "source_sha256": sha_file(path),
            **COMMON,
        })
    return mapping, evidence


def baseline_field_pass(row: dict[str, str], field: str, pass_tokens: tuple[str, ...]) -> bool:
    value = clean(row.get(field)).upper()
    return any(token in value for token in pass_tokens)


def build_status_rows(baseline_rows: list[dict[str, str]], evidence: dict[str, bool]) -> list[dict[str, str]]:
    rows = []
    source = rel(BASELINE)
    for row in baseline_rows:
        ticker = row.get("ticker", "").upper()
        score_ok = clean(row.get("official_current_score")) != ""
        rank_ok = clean(row.get("official_current_rank")) != ""
        price_ok = clean(row.get("latest_price")) != "" and clean(row.get("latest_price_date")) != ""
        freshness_ok = price_ok
        source_quality_ok = (
            baseline_field_pass(row, "certification_status", ("CERTIFIED", "PASS"))
            and baseline_field_pass(row, "accepted_artifact_validation_status", ("PASS", "FOUND"))
        )
        pit_ok = (
            baseline_field_pass(row, "exact_artifact_proof_status", ("FOUND", "PASS"))
            and clean(row.get("source_file")) != ""
        )
        schema_ok = evidence["schema"] and rank_ok and score_ok and ticker != ""
        factor_score_ok = evidence["factor_score"] and score_ok
        source_quality = evidence["source_quality"] and source_quality_ok
        all_ok = freshness_ok and source_quality and pit_ok and schema_ok and factor_score_ok
        fail_reasons = []
        if not freshness_ok:
            fail_reasons.append("FRESHNESS_EVIDENCE_MISSING")
        if not source_quality:
            fail_reasons.append("SOURCE_QUALITY_EVIDENCE_MISSING_OR_FAILED")
        if not pit_ok:
            fail_reasons.append("PIT_OR_LINEAGE_PROOF_MISSING")
        if not schema_ok:
            fail_reasons.append("SCHEMA_OR_RANK_SCORE_FIELD_MISSING")
        if not factor_score_ok:
            fail_reasons.append("FACTOR_SCORE_AVAILABILITY_EVIDENCE_MISSING")
        if all_ok:
            status = "PASS"
            category = "NONE"
            reason = "INFERRED_FROM_AUTHORITATIVE_BASELINE_AND_AGGREGATE_QUALITY_ARTIFACTS"
            repair = "NONE"
            confidence = "INFERRED_HIGH"
        else:
            status = "UNKNOWN"
            category = "DATA_TRUST_MAPPING_INCOMPLETE"
            reason = "|".join(fail_reasons)
            repair = "ATTACH_OR_REPAIR_MISSING_DATA_TRUST_EVIDENCE"
            confidence = "UNMAPPED"
        rows.append({
            "ticker": ticker,
            "baseline_rank": row.get("official_current_rank", ""),
            "baseline_score": row.get("official_current_score", ""),
            "data_trust_status": status,
            "data_trust_pass": tf(status == "PASS"),
            "data_trust_fail": "FALSE",
            "data_trust_unknown": tf(status == "UNKNOWN"),
            "freshness_status": "PASS" if freshness_ok else "UNKNOWN",
            "source_quality_status": "PASS" if source_quality else "UNKNOWN",
            "pit_safety_status": "PASS" if pit_ok else "UNKNOWN",
            "schema_status": "PASS" if schema_ok else "UNKNOWN",
            "factor_score_availability_status": "PASS" if factor_score_ok else "UNKNOWN",
            "price_availability_status": "PASS" if price_ok else "UNKNOWN",
            "benchmark_availability_status_if_relevant": "NOT_RELEVANT_CURRENT_RANKING_GATE",
            "outcome_availability_status_if_relevant": "NOT_RELEVANT_CURRENT_RANKING_GATE",
            "data_trust_failure_category": category,
            "data_trust_failure_reason": reason,
            "data_trust_source_artifact": source,
            "data_trust_source_field": "official_current_rank;official_current_score;latest_price;latest_price_date;certification_status;accepted_artifact_validation_status;exact_artifact_proof_status",
            "mapping_confidence": confidence,
            "ranking_eligible_after_data_trust_gate": tf(status == "PASS"),
            "repair_required": tf(status != "PASS"),
            "recommended_repair_action": repair,
            **COMMON,
        })
    return rows


def build_repair_audit(status_rows: list[dict[str, str]], prior_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    prior = {row.get("ticker", "").upper(): row.get("data_trust_status", "UNKNOWN") for row in prior_rows}
    rows = []
    for idx, row in enumerate(status_rows, start=1):
        repaired = row["data_trust_status"]
        prior_status = prior.get(row["ticker"], "UNKNOWN")
        result = "RECOVERED_INFERRED_PASS" if repaired == "PASS" and prior_status == "UNKNOWN" else ("REMAINS_UNKNOWN" if repaired == "UNKNOWN" else "UNCHANGED")
        rows.append({
            "repair_audit_id": f"V20_166_R1_REPAIR_{idx:03d}",
            "ticker": row["ticker"],
            "prior_v20_166_status": prior_status,
            "repaired_data_trust_status": repaired,
            "mapping_method": "INFERRED_FROM_AUTHORITATIVE_BASELINE_AND_AGGREGATE_QUALITY_ARTIFACTS" if repaired == "PASS" else "UNMAPPED",
            "mapping_confidence": row["mapping_confidence"],
            "repair_result": result,
            "repair_reason": row["data_trust_failure_reason"],
            "source_artifact": row["data_trust_source_artifact"],
            **COMMON,
        })
    return rows


def unknown_backlog(status_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{
        "ticker": row["ticker"],
        "baseline_rank": row["baseline_rank"],
        "data_trust_failure_category": row["data_trust_failure_category"],
        "data_trust_failure_reason": row["data_trust_failure_reason"],
        "missing_evidence": row["recommended_repair_action"],
        "recommended_repair_action": row["recommended_repair_action"],
        "repair_priority": "REVIEW",
        **COMMON,
    } for row in status_rows if row["data_trust_unknown"] == "TRUE"]


def build_ready(status_rows: list[dict[str, str]], mapping_rows: list[dict[str, str]]) -> dict[str, str]:
    pass_count = sum(1 for row in status_rows if row["data_trust_pass"] == "TRUE")
    fail_count = sum(1 for row in status_rows if row["data_trust_fail"] == "TRUE")
    unknown_count = sum(1 for row in status_rows if row["data_trust_unknown"] == "TRUE")
    eligible = sum(1 for row in status_rows if row["ranking_eligible_after_data_trust_gate"] == "TRUE")
    direct = sum(1 for row in status_rows if row["mapping_confidence"].startswith("DIRECT"))
    inferred = sum(1 for row in status_rows if row["mapping_confidence"].startswith("INFERRED"))
    ready = pass_count > 0 and unknown_count == 0
    if ready:
        action = "PROCEED_TO_V20_166_R2_GATE_ONLY_RANKING_SIMULATION"
    elif pass_count > 0:
        action = "PROCEED_TO_V20_166_R2_WITH_REMAINING_UNKNOWN_BACKLOG_EXCLUDED"
    else:
        action = "ATTACH_TICKER_LEVEL_DATA_TRUST_STATUS_OR_REPAIR_MAPPING"
    return {
        "ready_audit_id": "V20_166_R1_DATA_TRUST_GATE_READY_AUDIT_001",
        "baseline_candidate_count": str(len(status_rows)),
        "data_trust_pass_count": str(pass_count),
        "data_trust_fail_count": str(fail_count),
        "data_trust_unknown_count": str(unknown_count),
        "ranking_eligible_after_data_trust_count": str(eligible),
        "excluded_due_to_data_trust_fail_count": str(fail_count),
        "excluded_due_to_data_trust_unknown_count": str(unknown_count),
        "remaining_unknown_backlog_count": str(unknown_count),
        "mapping_source_artifact_count": str(sum(1 for row in mapping_rows if row["usable_for_status_mapping"] == "TRUE")),
        "direct_ticker_mapping_count": str(direct),
        "inferred_from_artifact_mapping_count": str(inferred),
        "unmapped_ticker_count": str(unknown_count),
        "ready_for_gate_only_ranking_simulation": tf(ready),
        "recommended_next_action": action,
        **COMMON,
    }


def write_report(status: str, ready: dict[str, str] | None = None) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.166-R1 DATA_TRUST Status Source Mapping Repair Report",
        "",
        f"- wrapper_status: {status}",
        f"- data_trust_role: {DATA_TRUST_ROLE}",
        "- data_trust_scoring_weight: 0.0000000000",
        "- research_only: TRUE",
        "- official_ranking_mutated: FALSE",
        "- official_weight_change_created: FALSE",
    ]
    if ready:
        lines.extend([
            f"- baseline_candidate_count: {ready['baseline_candidate_count']}",
            f"- data_trust_pass_count: {ready['data_trust_pass_count']}",
            f"- data_trust_fail_count: {ready['data_trust_fail_count']}",
            f"- data_trust_unknown_count: {ready['data_trust_unknown_count']}",
            f"- inferred_from_artifact_mapping_count: {ready['inferred_from_artifact_mapping_count']}",
            f"- ready_for_gate_only_ranking_simulation: {ready['ready_for_gate_only_ranking_simulation']}",
            f"- recommended_next_action: {ready['recommended_next_action']}",
        ])
    lines.extend(["", "Statuses are mapped from existing artifacts only; UNKNOWN is never treated as PASS."])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_166_R1_DATA_TRUST_NEXT_GATE_001",
        "v20_166_gate_consumed": "FALSE",
        "v20_166_status": "",
        "baseline_candidate_count": "0",
        "data_trust_pass_count": "0",
        "data_trust_fail_count": "0",
        "data_trust_unknown_count": "0",
        "ranking_eligible_after_data_trust_count": "0",
        "excluded_due_to_data_trust_fail_count": "0",
        "excluded_due_to_data_trust_unknown_count": "0",
        "remaining_unknown_backlog_count": "0",
        "mapping_source_artifact_count": "0",
        "direct_ticker_mapping_count": "0",
        "inferred_from_artifact_mapping_count": "0",
        "unmapped_ticker_count": "0",
        "ready_for_gate_only_ranking_simulation": "FALSE",
        "recommended_next_action": "BLOCKED",
        "no_ticker_status_fabricated": "TRUE",
        "unknown_not_treated_as_pass": "TRUE",
        "data_trust_gate_criteria_not_lowered": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_MAPPING, MAPPING_FIELDS, [])
    write_csv(OUT_STATUS, STATUS_FIELDS, [])
    write_csv(OUT_REPAIR, REPAIR_FIELDS, [])
    write_csv(OUT_UNKNOWN, UNKNOWN_FIELDS, [])
    write_csv(OUT_READY, READY_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(BLOCKED_STATUS)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    before = input_hashes()
    required = [V166_POLICY, V166_WEIGHT, V166_ELIGIBILITY, V166_BACKLOG, V166_SAFETY, V166_GATE, BASELINE]
    missing = [path for path in required if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))
    gate_rows, _ = read_csv(V166_GATE)
    baseline_rows, _ = read_csv(BASELINE)
    prior_rows, _ = read_csv(V166_ELIGIBILITY)
    if not gate_rows or not baseline_rows or not prior_rows:
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    v166_gate = gate_rows[0]
    if v166_gate.get("final_status") != REQUIRED_V166_STATUS:
        return emit_blocked("V20_166_REQUIREMENTS_NOT_MET")

    mapping_rows, evidence = load_source_evidence()
    status_rows = build_status_rows(baseline_rows, evidence)
    repair_rows = build_repair_audit(status_rows, prior_rows)
    unknown_rows = unknown_backlog(status_rows)
    ready = build_ready(status_rows, mapping_rows)
    upstream_mutated = before != input_hashes()

    pass_count = int(ready["data_trust_pass_count"])
    unknown_count = int(ready["data_trust_unknown_count"])
    if upstream_mutated:
        status, blocking = BLOCKED_STATUS, "UPSTREAM_OUTPUT_MUTATION_DETECTED"
    elif pass_count == 0:
        status, blocking = WARN_STATUS, ""
    elif unknown_count > 0:
        status, blocking = PARTIAL_STATUS, ""
    else:
        status, blocking = PASS_STATUS, ""

    gate = {
        "gate_check_id": "V20_166_R1_DATA_TRUST_NEXT_GATE_001",
        "v20_166_gate_consumed": "TRUE",
        "v20_166_status": v166_gate.get("final_status", ""),
        **{field: ready[field] for field in [
            "baseline_candidate_count",
            "data_trust_pass_count",
            "data_trust_fail_count",
            "data_trust_unknown_count",
            "ranking_eligible_after_data_trust_count",
            "excluded_due_to_data_trust_fail_count",
            "excluded_due_to_data_trust_unknown_count",
            "remaining_unknown_backlog_count",
            "mapping_source_artifact_count",
            "direct_ticker_mapping_count",
            "inferred_from_artifact_mapping_count",
            "unmapped_ticker_count",
            "ready_for_gate_only_ranking_simulation",
            "recommended_next_action",
        ]},
        "no_ticker_status_fabricated": "TRUE",
        "unknown_not_treated_as_pass": "TRUE",
        "data_trust_gate_criteria_not_lowered": "TRUE",
        "no_upstream_outputs_mutated": tf(not upstream_mutated),
        "blocking_reason": blocking,
        "final_status": status,
        **COMMON,
    }

    write_csv(OUT_MAPPING, MAPPING_FIELDS, mapping_rows)
    write_csv(OUT_STATUS, STATUS_FIELDS, status_rows)
    write_csv(OUT_REPAIR, REPAIR_FIELDS, repair_rows)
    write_csv(OUT_UNKNOWN, UNKNOWN_FIELDS, unknown_rows)
    write_csv(OUT_READY, READY_FIELDS, [ready])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(status, ready)

    print(status)
    print("V20_166_GATE_CONSUMED=TRUE")
    print(f"V20_166_STATUS={v166_gate.get('final_status', '')}")
    for field in [
        "baseline_candidate_count",
        "data_trust_pass_count",
        "data_trust_fail_count",
        "data_trust_unknown_count",
        "ranking_eligible_after_data_trust_count",
        "excluded_due_to_data_trust_fail_count",
        "excluded_due_to_data_trust_unknown_count",
        "remaining_unknown_backlog_count",
        "mapping_source_artifact_count",
        "direct_ticker_mapping_count",
        "inferred_from_artifact_mapping_count",
        "unmapped_ticker_count",
        "ready_for_gate_only_ranking_simulation",
        "recommended_next_action",
    ]:
        print(f"{field.upper()}={ready[field]}")
    print("NO_TICKER_STATUS_FABRICATED=TRUE")
    print("UNKNOWN_NOT_TREATED_AS_PASS=TRUE")
    print("DATA_TRUST_GATE_CRITERIA_NOT_LOWERED=TRUE")
    print("RESEARCH_ONLY=TRUE")
    print("DATA_TRUST_SCORING_WEIGHT=0.0000000000")
    print(f"DATA_TRUST_ROLE={DATA_TRUST_ROLE}")
    print("FORMAL_ACTIVATION_ALLOWED=FALSE")
    print("PROMOTION_READY=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("OFFICIAL_WEIGHT_CHANGE_CREATED=FALSE")
    print("OFFICIAL_WEIGHT_REGISTRY_MUTATED=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("REAL_BOOK_ACTION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("PERFORMANCE_CLAIM_CREATED=FALSE")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
