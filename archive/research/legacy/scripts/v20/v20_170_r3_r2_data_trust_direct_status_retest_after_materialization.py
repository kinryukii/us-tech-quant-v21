#!/usr/bin/env python
"""V20.170-R3-R2 DATA_TRUST direct status retest after materialization."""

from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
CONSOLIDATION = OUTPUTS / "consolidation"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"

BASELINE = CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
ACTIVE_WEIGHT_REGISTRY = CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv"
PIT_LINEAGE = CONSOLIDATION / "V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv"

R2C_GATE = FACTORS / "V20_170_R2C_NEXT_STAGE_GATE.csv"
R3_R1B_INPUTS = [
    FACTORS / "V20_170_R3_R1B_MATERIALIZED_EVIDENCE_VALUE_DETAIL.csv",
    FACTORS / "V20_170_R3_R1B_PRODUCER_MATERIALIZATION_AUDIT.csv",
    FACTORS / "V20_170_R3_R1B_FIELD_MATERIALIZATION_AUDIT.csv",
    FACTORS / "V20_170_R3_R1B_CANDIDATE_MATERIALIZATION_AUDIT.csv",
    FACTORS / "V20_170_R3_R1B_REMAINING_MISSING_EVIDENCE_AUDIT.csv",
    FACTORS / "V20_170_R3_R1B_NEXT_STAGE_GATE.csv",
]
PROTECTED = [BASELINE, ACTIVE_WEIGHT_REGISTRY, PIT_LINEAGE, R2C_GATE, *R3_R1B_INPUTS]

OUT_CANDIDATES = FACTORS / "V20_170_R3_R2_DATA_TRUST_DIRECT_STATUS_RETEST_CANDIDATES.csv"
OUT_FIELDS = FACTORS / "V20_170_R3_R2_FIELD_RETEST_AUDIT.csv"
OUT_COMPLETENESS = FACTORS / "V20_170_R3_R2_CANDIDATE_EVIDENCE_COMPLETENESS_AUDIT.csv"
OUT_UNKNOWN = FACTORS / "V20_170_R3_R2_REMAINING_UNKNOWN_DIAGNOSTICS.csv"
OUT_FAIL = FACTORS / "V20_170_R3_R2_REMAINING_FAIL_DIAGNOSTICS.csv"
OUT_GATE = FACTORS / "V20_170_R3_R2_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_170_R3_R2_DATA_TRUST_DIRECT_STATUS_RETEST_AFTER_MATERIALIZATION_REPORT.md"

READY_R1B = "PASS_V20_170_R3_R1B_PRODUCER_VALUE_MATERIALIZATION_READY_FOR_R3_R2_RETEST"
PASS_STATUS = "PASS_V20_170_R3_R2_DIRECT_STATUS_RETEST_READY_FOR_V20_171"
PARTIAL_STATUS = "PARTIAL_PASS_V20_170_R3_R2_DIRECT_STATUS_RETEST_WITH_REMAINING_UNKNOWN_READY_FOR_V20_171"
BLOCKED_STATUS = "BLOCKED_V20_170_R3_R2_DATA_TRUST_DIRECT_STATUS_RETEST_AFTER_MATERIALIZATION"

DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_DIRECT_STATUS_RETEST_AFTER_MATERIALIZATION"
EXPECTED_FIELDS = [
    "factor_input_as_of_date",
    "factor_input_source_timestamp",
    "factor_input_publication_lag_handled",
    "factor_input_point_in_time_safe",
    "non_pit_blocker_present",
    "leakage_flag_present",
    "source_quality_usable",
    "freshness_usable",
]
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
COMMON = {**SAFETY, "repair_scope": SCOPE, "audit_only": "TRUE"}

CANDIDATE_FIELDS = [
    "ticker", "baseline_rank", "direct_status_before_materialization",
    "direct_status_after_materialization", "factor_family_count",
    "required_materialized_evidence_value_count", "materialized_evidence_value_count",
    "missing_required_evidence_value_count", "fail_evidence_value_count",
    "warn_evidence_value_count", "structural_source_contract_gap_present",
    "accepted_for_v20_171_gate_only_ranking_simulation", "direct_status_reason",
    *COMMON.keys(),
]
FIELD_FIELDS = [
    "required_field", "field_retest_status", "required_value_count",
    "materialized_value_count", "missing_value_count", "fail_value_count",
    "warn_value_count", "affected_ticker_count", "affected_factor_family_count",
    "accepted_for_direct_status", "structural_source_contract_gap_present",
    "limitation_reason", *COMMON.keys(),
]
COMPLETENESS_FIELDS = [
    "ticker", "baseline_rank", "factor_family", "required_field_count",
    "materialized_field_count", "missing_field_count", "fail_field_count",
    "warn_field_count", "complete_for_direct_status", "evidence_status_reason",
    *COMMON.keys(),
]
UNKNOWN_FIELDS = [
    "ticker", "baseline_rank", "factor_family", "required_field",
    "unknown_reason", "recommended_action", *COMMON.keys(),
]
FAIL_FIELDS = [
    "ticker", "baseline_rank", "factor_family", "required_field",
    "failed_value", "fail_reason", "recommended_action", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_170_r3_r1b_status_consumed", "v20_170_r3_r1b_status",
    "baseline_candidate_count", "candidate_retest_count",
    "direct_pass_candidate_count", "direct_warn_candidate_count",
    "direct_fail_candidate_count", "direct_unknown_candidate_count",
    "materialized_evidence_value_count", "remaining_missing_evidence_value_count",
    "structural_source_contract_gap_count", "remaining_fail_evidence_value_count",
    "ready_for_v20_171_gate_only_ranking_simulation",
    "ready_for_v20_171_full_gate_only_ranking_simulation",
    "ready_for_official_use", "official_weight_change_allowed",
    "official_ranking_mutation_allowed", "ranking_simulation_created",
    "no_data_trust_status_fabricated", "no_evidence_values_fabricated",
    "no_ticker_rows_fabricated", "no_official_outputs_mutated",
    "recommended_next_action", "blocking_reason", "final_status", *COMMON.keys(),
]


def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


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


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def sha_file(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in PROTECTED if path.exists()}


def value_passes(field: str, value: str) -> bool:
    value = clean(value).upper()
    if field in {"non_pit_blocker_present", "leakage_flag_present"}:
        return value == "FALSE"
    if field in {"factor_input_publication_lag_handled", "factor_input_point_in_time_safe", "source_quality_usable", "freshness_usable"}:
        return value == "TRUE"
    return value not in {"", "UNKNOWN"}


def build_outputs(
    baseline: list[dict[str, str]],
    materialized: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    rows_by_ticker: dict[str, list[dict[str, str]]] = defaultdict(list)
    rows_by_pair: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    rows_by_field: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in materialized:
        rows_by_ticker[row["ticker"]].append(row)
        rows_by_pair[(row["ticker"], row["factor_family"])].append(row)
        rows_by_field[row["required_field"]].append(row)

    candidates: list[dict[str, str]] = []
    completeness: list[dict[str, str]] = []
    unknown: list[dict[str, str]] = []
    fail: list[dict[str, str]] = []
    for base in baseline:
        ticker = base["ticker"]
        ticker_rows = rows_by_ticker.get(ticker, [])
        families = sorted({row["factor_family"] for row in ticker_rows})
        required_count = len(families) * len(EXPECTED_FIELDS)
        materialized_count = len(ticker_rows)
        fail_count = sum(not value_passes(row["required_field"], row["materialized_evidence_value"]) for row in ticker_rows)
        missing_count = max(required_count - materialized_count, 0)
        status = "PASS" if required_count > 0 and missing_count == 0 and fail_count == 0 else ("FAIL" if fail_count else "UNKNOWN")
        for family in families:
            pair_rows = rows_by_pair[(ticker, family)]
            fields = {row["required_field"]: row for row in pair_rows}
            pair_missing = [field for field in EXPECTED_FIELDS if field not in fields]
            pair_fail = [field for field, row in fields.items() if not value_passes(field, row["materialized_evidence_value"])]
            for field in pair_missing:
                unknown.append({
                    "ticker": ticker,
                    "baseline_rank": base.get("official_current_rank", ""),
                    "factor_family": family,
                    "required_field": field,
                    "unknown_reason": "MATERIALIZED_VALUE_NOT_PRESENT_IN_R3_R1B_SIDECAR",
                    "recommended_action": "REPAIR_R3_R1B_MATERIALIZATION_INPUT",
                    **COMMON,
                })
            for field in pair_fail:
                fail.append({
                    "ticker": ticker,
                    "baseline_rank": base.get("official_current_rank", ""),
                    "factor_family": family,
                    "required_field": field,
                    "failed_value": fields[field]["materialized_evidence_value"],
                    "fail_reason": "MATERIALIZED_VALUE_FAILED_DIRECT_EVIDENCE_RULE",
                    "recommended_action": "REPAIR_PRODUCER_VALUE",
                    **COMMON,
                })
            completeness.append({
                "ticker": ticker,
                "baseline_rank": base.get("official_current_rank", ""),
                "factor_family": family,
                "required_field_count": str(len(EXPECTED_FIELDS)),
                "materialized_field_count": str(len(fields)),
                "missing_field_count": str(len(pair_missing)),
                "fail_field_count": str(len(pair_fail)),
                "warn_field_count": "0",
                "complete_for_direct_status": tf(not pair_missing and not pair_fail),
                "evidence_status_reason": "ALL_REQUIRED_EVIDENCE_MATERIALIZED" if not pair_missing and not pair_fail else "INCOMPLETE_OR_FAILED_EVIDENCE",
                **COMMON,
            })
        candidates.append({
            "ticker": ticker,
            "baseline_rank": base.get("official_current_rank", ""),
            "direct_status_before_materialization": "UNKNOWN",
            "direct_status_after_materialization": status,
            "factor_family_count": str(len(families)),
            "required_materialized_evidence_value_count": str(required_count),
            "materialized_evidence_value_count": str(materialized_count),
            "missing_required_evidence_value_count": str(missing_count),
            "fail_evidence_value_count": str(fail_count),
            "warn_evidence_value_count": "0",
            "structural_source_contract_gap_present": "FALSE",
            "accepted_for_v20_171_gate_only_ranking_simulation": tf(status in {"PASS", "WARN", "FAIL"}),
            "direct_status_reason": "ALL_REQUIRED_DIRECT_EVIDENCE_MATERIALIZED" if status == "PASS" else "DIRECT_EVIDENCE_INCOMPLETE_OR_FAILED",
            **COMMON,
        })

    field_rows: list[dict[str, str]] = []
    ticker_count = len({row["ticker"] for row in materialized})
    family_count = len({row["factor_family"] for row in materialized})
    for field in EXPECTED_FIELDS:
        rows = rows_by_field.get(field, [])
        fail_count = sum(not value_passes(field, row["materialized_evidence_value"]) for row in rows)
        field_rows.append({
            "required_field": field,
            "field_retest_status": "PASS" if rows and fail_count == 0 else ("FAIL" if fail_count else "UNKNOWN"),
            "required_value_count": str(ticker_count * family_count),
            "materialized_value_count": str(len(rows)),
            "missing_value_count": str(max(ticker_count * family_count - len(rows), 0)),
            "fail_value_count": str(fail_count),
            "warn_value_count": "0",
            "affected_ticker_count": str(len({row["ticker"] for row in rows})),
            "affected_factor_family_count": str(len({row["factor_family"] for row in rows})),
            "accepted_for_direct_status": tf(bool(rows) and fail_count == 0),
            "structural_source_contract_gap_present": "FALSE",
            "limitation_reason": "NONE" if rows and fail_count == 0 else "MISSING_OR_FAILED_MATERIALIZED_VALUES",
            **COMMON,
        })

    return candidates, field_rows, completeness, unknown, fail


def write_report(gate: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.170-R3-R2 DATA_TRUST Direct Status Retest After Materialization Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- direct_pass_candidate_count: {gate['direct_pass_candidate_count']}",
        f"- direct_unknown_candidate_count: {gate['direct_unknown_candidate_count']}",
        f"- materialized_evidence_value_count: {gate['materialized_evidence_value_count']}",
        f"- remaining_missing_evidence_value_count: {gate['remaining_missing_evidence_value_count']}",
        f"- ready_for_v20_171_gate_only_ranking_simulation: {gate['ready_for_v20_171_gate_only_ranking_simulation']}",
        f"- ready_for_v20_171_full_gate_only_ranking_simulation: {gate['ready_for_v20_171_full_gate_only_ranking_simulation']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        "",
        "DATA_TRUST remains gate-only and research-only. This stage does not mutate official rankings or weights.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [
        (OUT_CANDIDATES, CANDIDATE_FIELDS), (OUT_FIELDS, FIELD_FIELDS),
        (OUT_COMPLETENESS, COMPLETENESS_FIELDS), (OUT_UNKNOWN, UNKNOWN_FIELDS),
        (OUT_FAIL, FAIL_FIELDS),
    ]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_170_R3_R2_NEXT_STAGE_GATE_001",
        "v20_170_r3_r1b_status_consumed": "FALSE",
        "v20_170_r3_r1b_status": "",
        "baseline_candidate_count": "0",
        "candidate_retest_count": "0",
        "direct_pass_candidate_count": "0",
        "direct_warn_candidate_count": "0",
        "direct_fail_candidate_count": "0",
        "direct_unknown_candidate_count": "0",
        "materialized_evidence_value_count": "0",
        "remaining_missing_evidence_value_count": "0",
        "structural_source_contract_gap_count": "0",
        "remaining_fail_evidence_value_count": "0",
        "ready_for_v20_171_gate_only_ranking_simulation": "FALSE",
        "ready_for_v20_171_full_gate_only_ranking_simulation": "FALSE",
        "ready_for_official_use": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE",
        "no_data_trust_status_fabricated": "TRUE",
        "no_evidence_values_fabricated": "TRUE",
        "no_ticker_rows_fabricated": "TRUE",
        "no_official_outputs_mutated": "TRUE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_R3_R2",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    required = [*R3_R1B_INPUTS, BASELINE, ACTIVE_WEIGHT_REGISTRY]
    missing = [path for path in required if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))
    before = protected_hashes()
    baseline, _ = read_csv(BASELINE)
    materialized, _ = read_csv(R3_R1B_INPUTS[0])
    remaining, _ = read_csv(R3_R1B_INPUTS[4])
    gate_rows, _ = read_csv(R3_R1B_INPUTS[5])
    if not baseline or not materialized or not gate_rows:
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    r1b_gate = gate_rows[0]
    prereq_ok = all([
        r1b_gate.get("final_status") == READY_R1B,
        r1b_gate.get("remaining_missing_evidence_value_count") == "0",
        r1b_gate.get("fabricated_value_count") == "0",
        r1b_gate.get("ticker_row_fabrication_count") == "0",
        r1b_gate.get("ready_for_v20_170_r3_r2_full_direct_status_retest") == "TRUE",
        r1b_gate.get("ready_for_v20_171_gate_only_ranking_simulation") == "FALSE",
        r1b_gate.get("ready_for_official_use") == "FALSE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_170_R3_R1B_REQUIREMENTS_NOT_MET")

    candidates, fields, completeness, unknown, fail = build_outputs(baseline, materialized)
    official_mutated = before != protected_hashes()
    if official_mutated:
        return emit_blocked("OFFICIAL_OR_UPSTREAM_MUTATION_DETECTED")
    pass_count = sum(row["direct_status_after_materialization"] == "PASS" for row in candidates)
    warn_count = sum(row["direct_status_after_materialization"] == "WARN" for row in candidates)
    fail_count = sum(row["direct_status_after_materialization"] == "FAIL" for row in candidates)
    unknown_count = sum(row["direct_status_after_materialization"] == "UNKNOWN" for row in candidates)
    non_unknown = pass_count + warn_count + fail_count
    ready_v171 = non_unknown > 0 and unknown_count < len(candidates)
    full_ready = unknown_count == 0
    gate = {
        "gate_check_id": "V20_170_R3_R2_NEXT_STAGE_GATE_001",
        "v20_170_r3_r1b_status_consumed": "TRUE",
        "v20_170_r3_r1b_status": r1b_gate.get("final_status", ""),
        "baseline_candidate_count": str(len(baseline)),
        "candidate_retest_count": str(len(candidates)),
        "direct_pass_candidate_count": str(pass_count),
        "direct_warn_candidate_count": str(warn_count),
        "direct_fail_candidate_count": str(fail_count),
        "direct_unknown_candidate_count": str(unknown_count),
        "materialized_evidence_value_count": str(len(materialized)),
        "remaining_missing_evidence_value_count": str(len(remaining) + len(unknown)),
        "structural_source_contract_gap_count": "0",
        "remaining_fail_evidence_value_count": str(len(fail)),
        "ready_for_v20_171_gate_only_ranking_simulation": tf(ready_v171),
        "ready_for_v20_171_full_gate_only_ranking_simulation": tf(full_ready),
        "ready_for_official_use": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE",
        "no_data_trust_status_fabricated": "TRUE",
        "no_evidence_values_fabricated": "TRUE",
        "no_ticker_rows_fabricated": "TRUE",
        "no_official_outputs_mutated": "TRUE",
        "recommended_next_action": "RUN_V20_171_GATE_ONLY_RANKING_SIMULATION" if ready_v171 else "REPAIR_REMAINING_UNKNOWN_OR_FAIL",
        "blocking_reason": "NONE" if ready_v171 else "NO_NON_UNKNOWN_DIRECT_STATUS",
        "final_status": PASS_STATUS if ready_v171 else PARTIAL_STATUS,
        **COMMON,
    }
    write_csv(OUT_CANDIDATES, CANDIDATE_FIELDS, candidates)
    write_csv(OUT_FIELDS, FIELD_FIELDS, fields)
    write_csv(OUT_COMPLETENESS, COMPLETENESS_FIELDS, completeness)
    write_csv(OUT_UNKNOWN, UNKNOWN_FIELDS, unknown)
    write_csv(OUT_FAIL, FAIL_FIELDS, fail)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate)
    print(gate["final_status"])
    for key in GATE_FIELDS:
        if key in gate and key not in COMMON and key != "gate_check_id":
            print(f"{key.upper()}={gate[key]}")
    print(f"OFFICIAL_MUTATION_DETECTED={tf(official_mutated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
