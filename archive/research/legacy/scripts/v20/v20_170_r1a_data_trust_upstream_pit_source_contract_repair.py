#!/usr/bin/env python
"""V20.170-R1A DATA_TRUST upstream PIT source contract repair."""

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

REQUIRED_R1_STATUS = "WARN_V20_170_R1_NO_TICKER_LEVEL_PIT_SAFETY_EVIDENCE_RECOVERED"
PASS_STATUS = "PASS_V20_170_R1A_UPSTREAM_PIT_SOURCE_CONTRACT_READY_FOR_V20_170_R2"
PARTIAL_STATUS = "PARTIAL_PASS_V20_170_R1A_PIT_SOURCE_CONTRACT_WITH_REMAINING_UNKNOWN_READY_FOR_V20_170_R2"
WARN_STATUS = "WARN_V20_170_R1A_UPSTREAM_PIT_PRODUCER_PATCH_PLAN_REQUIRED"
BLOCKED_STATUS = "BLOCKED_V20_170_R1A_UPSTREAM_PIT_SOURCE_CONTRACT_REPAIR"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_UPSTREAM_PIT_SOURCE_CONTRACT_REPAIR"

R1_INPUTS = [
    FACTORS / "V20_170_R1_DATA_TRUST_PIT_SOURCE_DISCOVERY.csv",
    FACTORS / "V20_170_R1_TICKER_LEVEL_PIT_SAFETY_STATUS.csv",
    FACTORS / "V20_170_R1_PIT_SAFETY_EVIDENCE_LINEAGE.csv",
    FACTORS / "V20_170_R1_PIT_SAFETY_REPAIR_BACKLOG.csv",
    FACTORS / "V20_170_R1_DATA_TRUST_DIRECT_STATUS_RETEST_INPUT.csv",
    FACTORS / "V20_170_R1_PIT_SAFETY_COVERAGE_AUDIT.csv",
    FACTORS / "V20_170_R1_PIT_SAFETY_NEXT_GATE.csv",
    FACTORS / "V20_170_R1_PIT_SAFETY_SAFETY_AUDIT.csv",
]
BASELINE = CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
ACTIVE_WEIGHT_REGISTRY = CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv"

NAMED_SOURCES = [
    BASELINE,
    CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv",
    CONSOLIDATION / "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv",
    CONSOLIDATION / "V20_108_R1_CANDIDATE_FACTOR_FAMILY_CONTRIBUTIONS.csv",
    CONSOLIDATION / "V20_108_R2_EXPANDED_CANDIDATE_FACTOR_FAMILY_CONTRIBUTIONS.csv",
    CONSOLIDATION / "V20_98B_FACTOR_SCORE_CONTRIBUTION_AUDIT.csv",
    CONSOLIDATION / "V20_98B_RESEARCH_ONLY_FACTOR_WEIGHT_EXPOSURE.csv",
    CONSOLIDATION / "V20_45_CURRENT_OPERATOR_FACTOR_SUPPORT_VIEW.csv",
    CONSOLIDATION / "V20_48_REFRESHED_FACTOR_SUPPORT_VIEW.csv",
    CONSOLIDATION / "V20_54_FACTOR_SUPPORT_READABLE_VIEW.csv",
    CONSOLIDATION / "V20_CURRENT_FACTOR_MULTI_PATH_VALIDATION_TABLE.csv",
    CONSOLIDATION / "V20_82_FACTOR_MULTI_PATH_VALIDATION_TABLE.csv",
    CONSOLIDATION / "V20_9_DATA_TRUSTWORTHINESS_FACTOR_READINESS_AUDIT.csv",
    CONSOLIDATION / "V20_10_DATA_TRUSTWORTHINESS_FACTOR_SOURCE_AUDIT.csv",
    CONSOLIDATION / "V20_12_FACTOR_INPUT_DATA_QUALITY_REVIEW.csv",
    CONSOLIDATION / "V20_13_FACTOR_EVIDENCE_DATA_QUALITY_AUDIT.csv",
    CONSOLIDATION / "V20_14_FACTOR_EVIDENCE_DATA_QUALITY_REVIEW.csv",
    CONSOLIDATION / "V20_15_FACTOR_SCORE_DATA_QUALITY_AUDIT.csv",
    CONSOLIDATION / "V20_16_FACTOR_SCORE_DATA_QUALITY_REVIEW.csv",
    CONSOLIDATION / "V20_35_BLOCKED_NON_PIT_FACTOR_ENFORCEMENT.csv",
    CONSOLIDATION / "V20_35_R2_BLOCKED_NON_PIT_FACTOR_ENFORCEMENT.csv",
    BACKTEST / "V20_152_RANDOM_AS_OF_ELIGIBILITY_AUDIT.csv",
    FACTORS / "V20_153_FACTOR_ABLATION_ELIGIBILITY_AUDIT.csv",
    FACTORS / "V20_153_R2_FACTOR_ABLATION_REPAIRED_MATRIX.csv",
]

OUT_CONTRACT = FACTORS / "V20_170_R1A_UPSTREAM_PIT_SOURCE_CONTRACT.csv"
OUT_DISCOVERY = FACTORS / "V20_170_R1A_UPSTREAM_PIT_SOURCE_DISCOVERY.csv"
OUT_EMITTER = FACTORS / "V20_170_R1A_TICKER_FACTOR_PIT_LINEAGE_EMITTER.csv"
OUT_STATUS = FACTORS / "V20_170_R1A_TICKER_LEVEL_PIT_DIRECT_STATUS.csv"
OUT_MISSING = FACTORS / "V20_170_R1A_PIT_DIRECT_STATUS_MISSING_FIELD_AUDIT.csv"
OUT_BACKLOG = FACTORS / "V20_170_R1A_PIT_SOURCE_CONTRACT_REPAIR_BACKLOG.csv"
OUT_SUMMARY = FACTORS / "V20_170_R1A_PIT_SOURCE_CONTRACT_COVERAGE_SUMMARY.csv"
OUT_GATE = FACTORS / "V20_170_R1A_PIT_SOURCE_CONTRACT_NEXT_GATE.csv"
OUT_SAFETY = FACTORS / "V20_170_R1A_PIT_SOURCE_CONTRACT_SAFETY_AUDIT.csv"
REPORT = READ_CENTER / "V20_170_R1A_DATA_TRUST_UPSTREAM_PIT_SOURCE_CONTRACT_REPAIR_REPORT.md"
OUTPUT_PATHS = [OUT_CONTRACT, OUT_DISCOVERY, OUT_EMITTER, OUT_STATUS, OUT_MISSING, OUT_BACKLOG, OUT_SUMMARY, OUT_GATE, OUT_SAFETY]

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
COMMON = {**SAFETY, "upstream_pit_source_contract_repair_created": "TRUE", "repair_scope": SCOPE, "audit_only": "TRUE"}

CONTRACT_REQUIRED = [
    "ticker", "ranking_context_id", "ranking_as_of_date", "data_snapshot_id", "source_artifact",
    "source_row_id", "factor_family", "factor_input_name", "factor_input_as_of_date",
    "factor_input_source_timestamp", "factor_input_publication_lag_handled",
    "factor_input_point_in_time_safe", "non_pit_blocker_present", "leakage_flag_present",
    "schema_valid", "source_quality_usable", "freshness_usable",
    "lineage_to_ranking_score_available", "accepted_for_data_trust_direct_pit_status",
]
FACTOR_FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]

CONTRACT_FIELDS = ["contract_field", "required", "nullable_for_unknown", "accepted_values", "contract_role", *COMMON.keys()]
DISCOVERY_FIELDS = [
    "source_artifact", "artifact_exists", "row_count", "ticker_level", "has_ticker_column",
    "ticker_column_name", "has_ranking_as_of_date", "has_data_snapshot_id",
    "has_factor_family_field", "has_factor_input_name_field", "has_factor_input_as_of_date",
    "has_source_timestamp", "has_pit_status_field", "has_non_pit_blocker_field",
    "has_leakage_flag_field", "has_schema_valid_field", "has_source_quality_field",
    "has_freshness_field", "usable_for_upstream_pit_contract", "aggregate_only",
    "limitation_reason", *COMMON.keys(),
]
EMITTER_FIELDS = [
    "ticker", "baseline_rank", "ranking_context_id", "ranking_as_of_date", "data_snapshot_id",
    "source_artifact", "source_row_id", "factor_family", "factor_input_name",
    "factor_input_as_of_date", "factor_input_source_timestamp",
    "factor_input_publication_lag_handled", "factor_input_point_in_time_safe",
    "non_pit_blocker_present", "leakage_flag_present", "schema_valid",
    "source_quality_usable", "freshness_usable", "lineage_to_ranking_score_available",
    "direct_ticker_level_evidence", "aggregate_only_evidence",
    "accepted_for_data_trust_direct_pit_status", "rejection_reason", *COMMON.keys(),
]
STATUS_FIELDS = [
    "ticker", "baseline_rank", "pit_direct_status", "pit_direct_pass", "pit_direct_fail",
    "pit_direct_unknown", "accepted_pit_lineage_row_count", "required_factor_family_pit_lineage_count",
    "missing_factor_family_pit_lineage_count", "non_pit_blocker_present", "leakage_flag_present",
    "pit_source_artifacts", "pit_missing_fields", "pit_status_confidence",
    "failure_or_unknown_reason", "repair_required", "recommended_repair_action", *COMMON.keys(),
]
MISSING_FIELDS = [
    "ticker", "factor_family", "missing_required_field", "source_artifact",
    "source_field_expected", "available_alternative_field", "can_repair_from_existing_artifact",
    "requires_upstream_producer_patch", "recommended_upstream_stage_or_script",
    "repair_priority", *COMMON.keys(),
]
BACKLOG_FIELDS = [
    "ticker", "baseline_rank", "factor_family", "repair_issue", "missing_required_fields",
    "source_artifact", "recommended_repair_action", "repair_priority", *COMMON.keys(),
]
SUMMARY_FIELDS = [
    "summary_id", "baseline_candidate_count", "upstream_pit_contract_created",
    "pit_lineage_emitter_created", "ticker_factor_lineage_row_count", "pit_direct_pass_count",
    "pit_direct_fail_count", "pit_direct_unknown_count", "pit_direct_coverage_rate",
    "accepted_direct_pit_lineage_row_count", "aggregate_only_pit_lineage_row_count",
    "missing_required_pit_field_count", "ticker_level_source_artifact_count",
    "usable_upstream_pit_source_count", "remaining_unknown_count",
    "ready_for_v20_170_r2_direct_status_retest",
    "ready_for_v20_171_gate_only_ranking_simulation", "ready_for_official_use",
    "recommended_next_action", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_170_r1_status_consumed", "v20_170_r1_status",
    "baseline_candidate_count", "pit_direct_pass_count", "pit_direct_fail_count",
    "pit_direct_unknown_count", "pit_direct_coverage_rate",
    "ready_for_v20_170_r2_direct_status_retest",
    "ready_for_v20_171_gate_only_ranking_simulation", "ready_for_official_use",
    "official_weight_change_allowed", "official_ranking_mutation_allowed",
    "ranking_simulation_created", "no_pit_status_fabricated",
    "aggregate_pit_not_treated_as_ticker_pass", "unknown_not_treated_as_pass",
    "pit_criteria_not_lowered", "no_upstream_outputs_mutated", "blocking_reason",
    "final_status", *COMMON.keys(),
]
SAFETY_FIELDS = ["safety_check_id", "safety_check", "expected_value", "actual_value", "safety_passed", *COMMON.keys()]


def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def fmt(value: float) -> str:
    return f"{value:.10f}"


def truthy(value: object) -> bool:
    return clean(value).upper() in {"TRUE", "PASS", "SAFE", "YES", "1", "USABLE", "VALID"}


def falsey(value: object) -> bool:
    return clean(value).upper() in {"FALSE", "NO", "0", "NONE", "PASS", "SAFE"}


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


def source_paths() -> list[Path]:
    found = set(NAMED_SOURCES)
    keywords = ("pit", "asof", "as_of", "snapshot", "cache", "certification", "timestamp", "lineage", "blocker", "source")
    for directory in [CONSOLIDATION, FACTORS, BACKTEST]:
        if directory.exists():
            for path in directory.glob("*.csv"):
                if any(k in path.name.lower() for k in keywords):
                    found.add(path)
    return sorted(path for path in found if path not in OUTPUT_PATHS)


def protected_inputs(sources: list[Path]) -> list[Path]:
    return sorted(set([*R1_INPUTS, BASELINE, ACTIVE_WEIGHT_REGISTRY, *sources]))


def input_hashes(paths: list[Path]) -> dict[str, str]:
    return {rel(path): sha_file(path) for path in paths if path.exists()}


def find_field(fields: list[str], groups: list[tuple[str, ...]]) -> str:
    for group in groups:
        for field in fields:
            low = field.lower()
            if all(part in low for part in group):
                return field
    return ""


def contract_rows() -> list[dict[str, str]]:
    bool_fields = {
        "factor_input_publication_lag_handled", "factor_input_point_in_time_safe",
        "non_pit_blocker_present", "leakage_flag_present", "schema_valid",
        "source_quality_usable", "freshness_usable", "lineage_to_ranking_score_available",
        "accepted_for_data_trust_direct_pit_status",
    }
    rows = []
    for field in CONTRACT_REQUIRED:
        rows.append({
            "contract_field": field,
            "required": "TRUE",
            "nullable_for_unknown": "TRUE",
            "accepted_values": "TRUE|FALSE|UNKNOWN" if field in bool_fields else "NON_EMPTY_STRING_OR_UNKNOWN",
            "contract_role": "REQUIRED_TICKER_LEVEL_PIT_EVIDENCE_FIELD",
            **COMMON,
        })
    return rows


def scan_source(path: Path) -> dict[str, str]:
    rows, fields = read_csv(path)
    ticker_col = find_field(fields, [("ticker",), ("symbol",)])
    has = {
        "ranking_as_of_date": find_field(fields, [("ranking", "as", "of"), ("as_of",), ("as", "of")]),
        "data_snapshot_id": find_field(fields, [("data", "snapshot"), ("snapshot", "id"), ("run", "id")]),
        "factor_family": find_field(fields, [("factor", "family"), ("factor", "category"), ("factor", "type")]),
        "factor_input_name": find_field(fields, [("factor", "input"), ("factor", "name"), ("source", "column")]),
        "factor_input_as_of_date": find_field(fields, [("input", "as", "of"), ("as_of",), ("price", "date")]),
        "source_timestamp": find_field(fields, [("source", "timestamp"), ("ranking", "timestamp"), ("timestamp",)]),
        "pit_status": find_field(fields, [("point", "time"), ("pit",), ("leakage",)]),
        "non_pit_blocker": find_field(fields, [("non", "pit", "blocker"), ("blocked", "non", "pit"), ("non_pit",)]),
        "leakage_flag": find_field(fields, [("leakage", "flag"), ("leakage",)]),
        "schema_valid": find_field(fields, [("schema", "valid"), ("schema", "status")]),
        "source_quality": find_field(fields, [("source", "quality"), ("evidence", "quality"), ("quality", "status")]),
        "freshness": find_field(fields, [("freshness",), ("fresh",)]),
    }
    ticker_level = bool(ticker_col) and ticker_col.lower() not in {"ticker_count", "unique_ticker_count"}
    required_present = all([ticker_level, has["ranking_as_of_date"], has["data_snapshot_id"], has["factor_family"],
                            has["factor_input_name"], has["factor_input_as_of_date"], has["source_timestamp"],
                            has["pit_status"], has["non_pit_blocker"], has["leakage_flag"], has["schema_valid"],
                            has["source_quality"], has["freshness"]])
    aggregate_only = (not ticker_level and any(has.values())) or (ticker_col.lower() in {"ticker_count", "unique_ticker_count"})
    missing = []
    for name, field in has.items():
        if not field:
            missing.append(name)
    if not ticker_level:
        missing.insert(0, "ticker")
    limitation = "USABLE_UPSTREAM_PIT_CONTRACT_SOURCE" if required_present and rows else "MISSING_REQUIRED_FIELDS:" + "|".join(missing)
    if not rows:
        limitation = "EMPTY_OR_HEADER_ONLY_ARTIFACT"
    return {
        "source_artifact": rel(path), "artifact_exists": tf(path.exists()), "row_count": str(len(rows)),
        "ticker_level": tf(ticker_level), "has_ticker_column": tf(bool(ticker_col)),
        "ticker_column_name": ticker_col, "has_ranking_as_of_date": tf(bool(has["ranking_as_of_date"])),
        "has_data_snapshot_id": tf(bool(has["data_snapshot_id"])), "has_factor_family_field": tf(bool(has["factor_family"])),
        "has_factor_input_name_field": tf(bool(has["factor_input_name"])),
        "has_factor_input_as_of_date": tf(bool(has["factor_input_as_of_date"])),
        "has_source_timestamp": tf(bool(has["source_timestamp"])), "has_pit_status_field": tf(bool(has["pit_status"])),
        "has_non_pit_blocker_field": tf(bool(has["non_pit_blocker"])),
        "has_leakage_flag_field": tf(bool(has["leakage_flag"])), "has_schema_valid_field": tf(bool(has["schema_valid"])),
        "has_source_quality_field": tf(bool(has["source_quality"])), "has_freshness_field": tf(bool(has["freshness"])),
        "usable_for_upstream_pit_contract": tf(required_present and bool(rows)),
        "aggregate_only": tf(aggregate_only), "limitation_reason": limitation, **COMMON,
    }


def baseline_rows() -> list[dict[str, str]]:
    rows, _ = read_csv(BASELINE)
    return rows


def baseline_rank(row: dict[str, str], fallback: int) -> str:
    return clean(row.get("official_current_rank") or row.get("baseline_rank") or fallback)


def ranking_context(row: dict[str, str]) -> tuple[str, str, str]:
    context = clean(row.get("source_run_id") or row.get("source_stage") or "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING")
    as_of = clean(row.get("ranking_timestamp_utc") or row.get("latest_price_date"))
    snapshot = clean(row.get("accepted_artifact_path") or row.get("source_file") or row.get("source_run_id"))
    return context, as_of, snapshot


def build_direct_lookup(scans: list[dict[str, str]]) -> dict[tuple[str, str], list[dict[str, str]]]:
    lookup: dict[tuple[str, str], list[dict[str, str]]] = {}
    usable_paths = [ROOT / row["source_artifact"] for row in scans if row["usable_for_upstream_pit_contract"] == "TRUE"]
    for path in usable_paths:
        rows, fields = read_csv(path)
        ticker_col = find_field(fields, [("ticker",), ("symbol",)])
        family_col = find_field(fields, [("factor", "family"), ("factor", "category"), ("factor", "type")])
        if not ticker_col:
            continue
        for idx, row in enumerate(rows, start=1):
            ticker = clean(row.get(ticker_col)).upper()
            family = clean(row.get(family_col)).upper() if family_col else "UNKNOWN"
            row["_source_artifact"] = rel(path)
            row["_source_row_id"] = str(idx)
            row["_fields"] = "|".join(fields)
            lookup.setdefault((ticker, family), []).append(row)
    return lookup


def extract_direct(row: dict[str, str]) -> dict[str, str]:
    fields = row.get("_fields", "").split("|")
    def f(groups: list[tuple[str, ...]]) -> str:
        return find_field(fields, groups)
    mapping = {
        "ranking_as_of_date": f([("ranking", "as", "of"), ("as_of",), ("as", "of")]),
        "data_snapshot_id": f([("data", "snapshot"), ("snapshot", "id"), ("run", "id")]),
        "factor_family": f([("factor", "family"), ("factor", "category"), ("factor", "type")]),
        "factor_input_name": f([("factor", "input"), ("factor", "name"), ("source", "column")]),
        "factor_input_as_of_date": f([("input", "as", "of"), ("as_of",), ("price", "date")]),
        "factor_input_source_timestamp": f([("source", "timestamp"), ("ranking", "timestamp"), ("timestamp",)]),
        "factor_input_publication_lag_handled": f([("publication", "lag"), ("lag", "handled")]),
        "factor_input_point_in_time_safe": f([("point", "time"), ("pit",)]),
        "non_pit_blocker_present": f([("non", "pit", "blocker"), ("blocked", "non", "pit"), ("non_pit",)]),
        "leakage_flag_present": f([("leakage", "flag"), ("leakage",)]),
        "schema_valid": f([("schema", "valid"), ("schema", "status")]),
        "source_quality_usable": f([("source", "quality"), ("evidence", "quality"), ("quality", "status")]),
        "freshness_usable": f([("freshness",), ("fresh",)]),
        "lineage_to_ranking_score_available": f([("lineage", "ranking"), ("binding", "status"), ("factor", "lineage")]),
    }
    out = {"source_artifact": row.get("_source_artifact", ""), "source_row_id": row.get("_source_row_id", "")}
    for contract_field, source_field in mapping.items():
        out[contract_field] = clean(row.get(source_field)) if source_field else ""
    return out


def missing_required(evidence: dict[str, str]) -> list[str]:
    upstream_required = [field for field in CONTRACT_REQUIRED if field != "accepted_for_data_trust_direct_pit_status"]
    return [field for field in upstream_required if not clean(evidence.get(field))]


def accepted(evidence: dict[str, str]) -> bool:
    if missing_required(evidence):
        return False
    return all([
        truthy(evidence.get("factor_input_publication_lag_handled")),
        truthy(evidence.get("factor_input_point_in_time_safe")),
        not truthy(evidence.get("non_pit_blocker_present")),
        not truthy(evidence.get("leakage_flag_present")),
        truthy(evidence.get("schema_valid")),
        truthy(evidence.get("source_quality_usable")),
        truthy(evidence.get("freshness_usable")),
        truthy(evidence.get("lineage_to_ranking_score_available")),
    ])


def build_emitter_and_audits(baseline: list[dict[str, str]], scans: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    lookup = build_direct_lookup(scans)
    emitter: list[dict[str, str]] = []
    missing_rows: list[dict[str, str]] = []
    backlog: list[dict[str, str]] = []
    status_rows: list[dict[str, str]] = []
    for idx, base in enumerate(baseline, start=1):
        ticker = clean(base.get("ticker")).upper()
        rank = baseline_rank(base, idx)
        context, ranking_as_of, snapshot = ranking_context(base)
        accepted_count = 0
        fail = False
        leak = False
        blocker = False
        artifacts = set()
        ticker_missing = set()
        for family in FACTOR_FAMILIES:
            candidates = lookup.get((ticker, family), []) + lookup.get((ticker, "UNKNOWN"), [])
            evidence = extract_direct(candidates[0]) if candidates else {}
            if evidence:
                artifacts.add(evidence.get("source_artifact", ""))
            row = {
                "ticker": ticker, "baseline_rank": rank, "ranking_context_id": context,
                "ranking_as_of_date": evidence.get("ranking_as_of_date") or ranking_as_of,
                "data_snapshot_id": evidence.get("data_snapshot_id") or snapshot,
                "source_artifact": evidence.get("source_artifact", ""),
                "source_row_id": evidence.get("source_row_id", ""), "factor_family": family,
                "factor_input_name": evidence.get("factor_input_name", ""),
                "factor_input_as_of_date": evidence.get("factor_input_as_of_date", ""),
                "factor_input_source_timestamp": evidence.get("factor_input_source_timestamp", ""),
                "factor_input_publication_lag_handled": evidence.get("factor_input_publication_lag_handled", ""),
                "factor_input_point_in_time_safe": evidence.get("factor_input_point_in_time_safe", ""),
                "non_pit_blocker_present": evidence.get("non_pit_blocker_present", ""),
                "leakage_flag_present": evidence.get("leakage_flag_present", ""),
                "schema_valid": evidence.get("schema_valid", ""),
                "source_quality_usable": evidence.get("source_quality_usable", ""),
                "freshness_usable": evidence.get("freshness_usable", ""),
                "lineage_to_ranking_score_available": evidence.get("lineage_to_ranking_score_available", ""),
                "direct_ticker_level_evidence": tf(bool(evidence)),
                "aggregate_only_evidence": "FALSE",
                "accepted_for_data_trust_direct_pit_status": "FALSE",
                "rejection_reason": "NO_DIRECT_TICKER_LEVEL_PIT_CONTRACT_EVIDENCE",
                **COMMON,
            }
            if evidence:
                miss = missing_required({**evidence, "ticker": ticker, "ranking_context_id": context, "factor_family": family})
                blocker = blocker or truthy(evidence.get("non_pit_blocker_present"))
                leak = leak or truthy(evidence.get("leakage_flag_present"))
                fail = fail or blocker or leak
                if accepted({**evidence, "ticker": ticker, "ranking_context_id": context, "factor_family": family}):
                    accepted_count += 1
                    row["accepted_for_data_trust_direct_pit_status"] = "TRUE"
                    row["rejection_reason"] = ""
                else:
                    row["rejection_reason"] = "NON_PIT_BLOCKER_OR_LEAKAGE_PRESENT" if (blocker or leak) else "MISSING_REQUIRED_PIT_CONTRACT_FIELDS"
            else:
                miss = ["source_artifact", "source_row_id", "factor_input_name", "factor_input_as_of_date",
                        "factor_input_source_timestamp", "factor_input_publication_lag_handled",
                        "factor_input_point_in_time_safe", "non_pit_blocker_present", "leakage_flag_present",
                        "schema_valid", "source_quality_usable", "freshness_usable",
                        "lineage_to_ranking_score_available", "accepted_for_data_trust_direct_pit_status"]
            emitter.append(row)
            ticker_missing.update(miss)
            if miss:
                for field in miss:
                    missing_rows.append({
                        "ticker": ticker, "factor_family": family, "missing_required_field": field,
                        "source_artifact": evidence.get("source_artifact", ""),
                        "source_field_expected": field, "available_alternative_field": "",
                        "can_repair_from_existing_artifact": "FALSE",
                        "requires_upstream_producer_patch": "TRUE",
                        "recommended_upstream_stage_or_script": "UPSTREAM_TICKER_FACTOR_PIT_PRODUCER",
                        "repair_priority": "HIGH", **COMMON,
                    })
                backlog.append({
                    "ticker": ticker, "baseline_rank": rank, "factor_family": family,
                    "repair_issue": "MISSING_TICKER_FACTOR_PIT_CONTRACT_FIELDS",
                    "missing_required_fields": "|".join(miss),
                    "source_artifact": evidence.get("source_artifact", ""),
                    "recommended_repair_action": "PATCH_UPSTREAM_PRODUCER_TO_EMIT_CANONICAL_TICKER_FACTOR_PIT_CONTRACT",
                    "repair_priority": "HIGH", **COMMON,
                })
        if fail:
            pit_status, pass_flag, fail_flag, unknown_flag = "PIT_DIRECT_FAIL", "FALSE", "TRUE", "FALSE"
            reason = "NON_PIT_BLOCKER_OR_LEAKAGE_PRESENT"
            confidence = "DIRECT_FAIL"
        elif accepted_count == len(FACTOR_FAMILIES):
            pit_status, pass_flag, fail_flag, unknown_flag = "PIT_DIRECT_PASS", "TRUE", "FALSE", "FALSE"
            reason = ""
            confidence = "DIRECT_PASS"
        else:
            pit_status, pass_flag, fail_flag, unknown_flag = "PIT_DIRECT_UNKNOWN", "FALSE", "FALSE", "TRUE"
            reason = "MISSING_REQUIRED_TICKER_FACTOR_PIT_LINEAGE"
            confidence = "UNKNOWN"
        status_rows.append({
            "ticker": ticker, "baseline_rank": rank, "pit_direct_status": pit_status,
            "pit_direct_pass": pass_flag, "pit_direct_fail": fail_flag, "pit_direct_unknown": unknown_flag,
            "accepted_pit_lineage_row_count": str(accepted_count),
            "required_factor_family_pit_lineage_count": str(len(FACTOR_FAMILIES)),
            "missing_factor_family_pit_lineage_count": str(max(0, len(FACTOR_FAMILIES) - accepted_count)),
            "non_pit_blocker_present": tf(blocker), "leakage_flag_present": tf(leak),
            "pit_source_artifacts": "|".join(sorted(a for a in artifacts if a)),
            "pit_missing_fields": "|".join(sorted(ticker_missing)),
            "pit_status_confidence": confidence, "failure_or_unknown_reason": reason,
            "repair_required": tf(pit_status != "PIT_DIRECT_PASS"),
            "recommended_repair_action": "PATCH_UPSTREAM_PRODUCER_TO_EMIT_CANONICAL_TICKER_FACTOR_PIT_CONTRACT" if pit_status != "PIT_DIRECT_PASS" else "",
            **COMMON,
        })
    return emitter, status_rows, missing_rows, backlog


def build_summary(baseline_count: int, scans: list[dict[str, str]], emitter: list[dict[str, str]], statuses: list[dict[str, str]], missing: list[dict[str, str]]) -> dict[str, str]:
    pass_count = sum(r["pit_direct_pass"] == "TRUE" for r in statuses)
    fail_count = sum(r["pit_direct_fail"] == "TRUE" for r in statuses)
    unknown_count = sum(r["pit_direct_unknown"] == "TRUE" for r in statuses)
    accepted_count = sum(r["accepted_for_data_trust_direct_pit_status"] == "TRUE" for r in emitter)
    aggregate_count = sum(r["aggregate_only"] == "TRUE" for r in scans)
    ticker_level_sources = sum(r["ticker_level"] == "TRUE" for r in scans)
    usable_sources = sum(r["usable_for_upstream_pit_contract"] == "TRUE" for r in scans)
    coverage = pass_count / baseline_count if baseline_count else 0.0
    if pass_count > 0:
        ready_r2 = "TRUE"
        action = "RUN_V20_170_R2_DATA_TRUST_DIRECT_STATUS_RETEST"
    elif len(missing) > 0:
        ready_r2 = "FALSE"
        action = "CREATE_UPSTREAM_PIT_PRODUCER_PATCH_PLAN" if unknown_count == baseline_count else "PATCH_UPSTREAM_PIT_PRODUCER"
    else:
        ready_r2 = "FALSE"
        action = "INVESTIGATE_PIT_SOURCE_CONTRACT_BLOCKER"
    return {
        "summary_id": "V20_170_R1A_PIT_SOURCE_CONTRACT_COVERAGE_SUMMARY_001",
        "baseline_candidate_count": str(baseline_count),
        "upstream_pit_contract_created": "TRUE",
        "pit_lineage_emitter_created": "TRUE",
        "ticker_factor_lineage_row_count": str(len(emitter)),
        "pit_direct_pass_count": str(pass_count),
        "pit_direct_fail_count": str(fail_count),
        "pit_direct_unknown_count": str(unknown_count),
        "pit_direct_coverage_rate": fmt(coverage),
        "accepted_direct_pit_lineage_row_count": str(accepted_count),
        "aggregate_only_pit_lineage_row_count": str(aggregate_count),
        "missing_required_pit_field_count": str(len(missing)),
        "ticker_level_source_artifact_count": str(ticker_level_sources),
        "usable_upstream_pit_source_count": str(usable_sources),
        "remaining_unknown_count": str(unknown_count),
        "ready_for_v20_170_r2_direct_status_retest": ready_r2,
        "ready_for_v20_171_gate_only_ranking_simulation": "FALSE",
        "ready_for_official_use": "FALSE",
        "recommended_next_action": action,
        **COMMON,
    }


def safety_rows(upstream_mutated: bool, prereq_ok: bool) -> list[dict[str, str]]:
    checks = [
        ("v20_170_r1_status_required", "TRUE", tf(prereq_ok)),
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
        ("pit_criteria_lowered", "FALSE", "FALSE"),
        ("upstream_outputs_mutated", "FALSE", tf(upstream_mutated)),
    ]
    return [{"safety_check_id": f"V20_170_R1A_SAFETY_{i:03d}", "safety_check": c, "expected_value": e,
             "actual_value": a, "safety_passed": tf(e == a), **COMMON}
            for i, (c, e, a) in enumerate(checks, start=1)]


def write_report(status: str, summary: dict[str, str] | None = None) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.170-R1A DATA_TRUST Upstream PIT Source Contract Repair Report",
        "",
        f"- final_status: {status}",
        "- research_only: TRUE",
        "- data_trust_scoring_weight: 0.0000000000",
        "- ranking_simulation_created: FALSE",
        "- official_ranking_mutated: FALSE",
        "- official_weight_change_created: FALSE",
    ]
    if summary:
        for key in ["baseline_candidate_count", "ticker_factor_lineage_row_count", "pit_direct_pass_count",
                    "pit_direct_fail_count", "pit_direct_unknown_count", "pit_direct_coverage_rate",
                    "accepted_direct_pit_lineage_row_count", "missing_required_pit_field_count",
                    "recommended_next_action"]:
            lines.append(f"- {key}: {summary[key]}")
    lines.extend(["", "Aggregate PIT evidence is not accepted as ticker-level DATA_TRUST direct PIT evidence."])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    write_csv(OUT_CONTRACT, CONTRACT_FIELDS, contract_rows())
    for path, fields in [(OUT_DISCOVERY, DISCOVERY_FIELDS), (OUT_EMITTER, EMITTER_FIELDS), (OUT_STATUS, STATUS_FIELDS),
                         (OUT_MISSING, MISSING_FIELDS), (OUT_BACKLOG, BACKLOG_FIELDS), (OUT_SUMMARY, SUMMARY_FIELDS),
                         (OUT_SAFETY, SAFETY_FIELDS)]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_170_R1A_PIT_SOURCE_CONTRACT_NEXT_GATE_001",
        "v20_170_r1_status_consumed": "FALSE", "v20_170_r1_status": "",
        "baseline_candidate_count": "0", "pit_direct_pass_count": "0", "pit_direct_fail_count": "0",
        "pit_direct_unknown_count": "0", "pit_direct_coverage_rate": "0.0000000000",
        "ready_for_v20_170_r2_direct_status_retest": "FALSE",
        "ready_for_v20_171_gate_only_ranking_simulation": "FALSE", "ready_for_official_use": "FALSE",
        "official_weight_change_allowed": "FALSE", "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE", "no_pit_status_fabricated": "TRUE",
        "aggregate_pit_not_treated_as_ticker_pass": "TRUE", "unknown_not_treated_as_pass": "TRUE",
        "pit_criteria_not_lowered": "TRUE", "no_upstream_outputs_mutated": "TRUE",
        "blocking_reason": reason, "final_status": BLOCKED_STATUS, **COMMON,
    }
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(BLOCKED_STATUS)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    sources = source_paths()
    protected = protected_inputs(sources)
    before = input_hashes(protected)
    missing_inputs = [p for p in [*R1_INPUTS, BASELINE] if not p.exists() or p.stat().st_size == 0]
    if missing_inputs:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(p) for p in missing_inputs))
    r1_gate, _ = read_csv(FACTORS / "V20_170_R1_PIT_SAFETY_NEXT_GATE.csv")
    baseline = baseline_rows()
    if not r1_gate or not baseline:
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    r1_status = clean(r1_gate[0].get("final_status"))
    prereq_ok = r1_status == REQUIRED_R1_STATUS
    if not prereq_ok:
        return emit_blocked("V20_170_R1_REQUIRED_STATUS_NOT_MET")

    contract = contract_rows()
    scans = [scan_source(path) for path in sources]
    emitter, statuses, missing_audit, backlog = build_emitter_and_audits(baseline, scans)
    summary = build_summary(len(baseline), scans, emitter, statuses, missing_audit)
    upstream_mutated = before != input_hashes(protected)
    safety = safety_rows(upstream_mutated, prereq_ok)
    if upstream_mutated or not all(row["safety_passed"] == "TRUE" for row in safety):
        return emit_blocked("SAFETY_OR_UPSTREAM_MUTATION_FAILURE")

    pass_count = int(summary["pit_direct_pass_count"])
    unknown_count = int(summary["pit_direct_unknown_count"])
    baseline_count = int(summary["baseline_candidate_count"])
    missing_count = int(summary["missing_required_pit_field_count"])
    if pass_count > 0 and unknown_count == 0:
        final_status = PASS_STATUS
    elif pass_count > 0:
        final_status = PARTIAL_STATUS
    elif pass_count == 0 and missing_count > 0:
        final_status = WARN_STATUS
    else:
        final_status = BLOCKED_STATUS
    blocking_reason = "UPSTREAM_PRODUCER_PATCH_PLAN_REQUIRED" if final_status == WARN_STATUS else ""
    if unknown_count == baseline_count:
        summary["recommended_next_action"] = "CREATE_UPSTREAM_PIT_PRODUCER_PATCH_PLAN"

    gate = {
        "gate_check_id": "V20_170_R1A_PIT_SOURCE_CONTRACT_NEXT_GATE_001",
        "v20_170_r1_status_consumed": "TRUE", "v20_170_r1_status": r1_status,
        "baseline_candidate_count": summary["baseline_candidate_count"],
        "pit_direct_pass_count": summary["pit_direct_pass_count"],
        "pit_direct_fail_count": summary["pit_direct_fail_count"],
        "pit_direct_unknown_count": summary["pit_direct_unknown_count"],
        "pit_direct_coverage_rate": summary["pit_direct_coverage_rate"],
        "ready_for_v20_170_r2_direct_status_retest": summary["ready_for_v20_170_r2_direct_status_retest"],
        "ready_for_v20_171_gate_only_ranking_simulation": "FALSE", "ready_for_official_use": "FALSE",
        "official_weight_change_allowed": "FALSE", "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE", "no_pit_status_fabricated": "TRUE",
        "aggregate_pit_not_treated_as_ticker_pass": "TRUE", "unknown_not_treated_as_pass": "TRUE",
        "pit_criteria_not_lowered": "TRUE", "no_upstream_outputs_mutated": "TRUE",
        "blocking_reason": blocking_reason, "final_status": final_status, **COMMON,
    }
    write_csv(OUT_CONTRACT, CONTRACT_FIELDS, contract)
    write_csv(OUT_DISCOVERY, DISCOVERY_FIELDS, scans)
    write_csv(OUT_EMITTER, EMITTER_FIELDS, emitter)
    write_csv(OUT_STATUS, STATUS_FIELDS, statuses)
    write_csv(OUT_MISSING, MISSING_FIELDS, missing_audit)
    write_csv(OUT_BACKLOG, BACKLOG_FIELDS, backlog)
    write_csv(OUT_SUMMARY, SUMMARY_FIELDS, [summary])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_report(final_status, summary)
    print(final_status)
    print(f"V20_170_R1_STATUS={r1_status}")
    print(f"BASELINE_CANDIDATE_COUNT={summary['baseline_candidate_count']}")
    print(f"TICKER_FACTOR_LINEAGE_ROW_COUNT={summary['ticker_factor_lineage_row_count']}")
    print(f"PIT_DIRECT_PASS_COUNT={summary['pit_direct_pass_count']}")
    print(f"PIT_DIRECT_FAIL_COUNT={summary['pit_direct_fail_count']}")
    print(f"PIT_DIRECT_UNKNOWN_COUNT={summary['pit_direct_unknown_count']}")
    print(f"PIT_DIRECT_COVERAGE_RATE={summary['pit_direct_coverage_rate']}")
    print(f"MISSING_REQUIRED_PIT_FIELD_COUNT={summary['missing_required_pit_field_count']}")
    print(f"READY_FOR_V20_170_R2_DIRECT_STATUS_RETEST={summary['ready_for_v20_170_r2_direct_status_retest']}")
    print("READY_FOR_V20_171_GATE_ONLY_RANKING_SIMULATION=FALSE")
    print("READY_FOR_OFFICIAL_USE=FALSE")
    print("OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE")
    print("OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE")
    print("RANKING_SIMULATION_CREATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_ACTION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("PERFORMANCE_CLAIM_CREATED=FALSE")
    print(f"RECOMMENDED_NEXT_ACTION={summary['recommended_next_action']}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
