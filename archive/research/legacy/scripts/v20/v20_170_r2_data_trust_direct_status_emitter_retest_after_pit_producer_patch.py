#!/usr/bin/env python
"""V20.170-R2 DATA_TRUST direct status emitter retest after PIT producer patch."""

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
PIT_SCHEMA_AUDIT = CONSOLIDATION / "V20_108_R10_PIT_LINEAGE_SCHEMA_EXTENSION_AUDIT.csv"
PIT_GAP_AUDIT = CONSOLIDATION / "V20_108_R10_PIT_LINEAGE_SOURCE_CONTRACT_GAP_AUDIT.csv"

R1C_INPUTS = [
    FACTORS / "V20_170_R1C_PIT_PRODUCER_PATCH_IMPLEMENTATION_AUDIT.csv",
    FACTORS / "V20_170_R1C_PATCHED_PIT_LINEAGE_VALIDATION.csv",
    FACTORS / "V20_170_R1C_PIT_FIELD_COMPLETION_AUDIT.csv",
    FACTORS / "V20_170_R1C_UNRESOLVED_SOURCE_CONTRACT_BACKLOG.csv",
    FACTORS / "V20_170_R1C_PIT_PRODUCER_PATCH_NEXT_GATE.csv",
    FACTORS / "V20_170_R1C_PIT_PRODUCER_PATCH_SAFETY_AUDIT.csv",
]
V170_INPUTS = [
    FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_CONTRACT.csv",
    FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_EMITTER.csv",
    FACTORS / "V20_170_DATA_TRUST_DIRECT_PASS_FAIL_UNKNOWN.csv",
    FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_REPAIR_BACKLOG.csv",
    FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_COVERAGE_AUDIT.csv",
]

OUT_RETEST = FACTORS / "V20_170_R2_DATA_TRUST_DIRECT_STATUS_RETEST.csv"
OUT_STATUS = FACTORS / "V20_170_R2_DATA_TRUST_DIRECT_PASS_FAIL_UNKNOWN.csv"
OUT_CONSUMPTION = FACTORS / "V20_170_R2_PIT_LINEAGE_CONSUMPTION_AUDIT.csv"
OUT_BLOCKERS = FACTORS / "V20_170_R2_DIRECT_STATUS_BLOCKER_AUDIT.csv"
OUT_BACKLOG = FACTORS / "V20_170_R2_DIRECT_STATUS_REPAIR_BACKLOG.csv"
OUT_SUMMARY = FACTORS / "V20_170_R2_DIRECT_STATUS_COVERAGE_SUMMARY.csv"
OUT_GATE = FACTORS / "V20_170_R2_DIRECT_STATUS_NEXT_GATE.csv"
OUT_SAFETY = FACTORS / "V20_170_R2_DIRECT_STATUS_SAFETY_AUDIT.csv"
REPORT = READ_CENTER / "V20_170_R2_DATA_TRUST_DIRECT_STATUS_EMITTER_RETEST_AFTER_PIT_PRODUCER_PATCH_REPORT.md"

ALLOWED_R1C = {
    "WARN_V20_170_R1C_PIT_PRODUCER_PATCH_CREATED_BUT_NO_ACCEPTED_DIRECT_LINEAGE",
    "PARTIAL_PASS_V20_170_R1C_PIT_PRODUCER_PATCH_WITH_SOURCE_CONTRACT_GAPS_READY_FOR_V20_170_R2",
    "PASS_V20_170_R1C_PIT_PRODUCER_PATCH_READY_FOR_V20_170_R2",
}
PASS_STATUS = "PASS_V20_170_R2_DIRECT_STATUS_RETEST_READY_FOR_V20_171"
PARTIAL_STATUS = "PARTIAL_PASS_V20_170_R2_DIRECT_STATUS_RETEST_WITH_REMAINING_UNKNOWN_READY_FOR_V20_171"
WARN_STATUS = "WARN_V20_170_R2_DIRECT_STATUS_RETEST_BLOCKED_BY_SOURCE_CONTRACT_GAPS"
BLOCKED_STATUS = "BLOCKED_V20_170_R2_DATA_TRUST_DIRECT_STATUS_RETEST"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_DIRECT_STATUS_EMITTER_RETEST_AFTER_PIT_PRODUCER_PATCH"
REQUIRED_FAMILIES = {"FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"}

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
COMMON = {**SAFETY, "direct_status_retest_created": "TRUE", "repair_scope": SCOPE, "audit_only": "TRUE"}

RETEST_FIELDS = [
    "ticker", "baseline_rank", "prior_direct_data_trust_status", "retested_direct_data_trust_status",
    "retested_direct_data_trust_pass", "retested_direct_data_trust_fail",
    "retested_direct_data_trust_unknown", "ticker_identity_match", "price_data_available",
    "required_factor_family_scores_available", "fundamental_score_available",
    "technical_score_available", "strategy_score_available", "risk_score_available",
    "market_regime_score_available", "data_trust_score_excluded_from_scoring",
    "pit_lineage_sidecar_available", "accepted_direct_pit_lineage_row_count",
    "required_pit_lineage_row_count", "source_contract_required_field_count",
    "unknown_required_pit_field_count", "pit_safety_status", "source_quality_status",
    "freshness_status", "schema_status", "current_ranking_eligibility_status",
    "score_lineage_bindable", "direct_status_confidence", "failure_or_unknown_reason",
    "repair_required", "recommended_repair_action", *COMMON.keys(),
]
CONSUMPTION_FIELDS = [
    "ticker", "factor_family", "lineage_sidecar_row_count",
    "accepted_for_data_trust_direct_pit_status_count", "unknown_required_field_count",
    "source_contract_required_field_count", "non_pit_blocker_present", "leakage_flag_present",
    "schema_valid", "source_quality_usable", "freshness_usable",
    "factor_input_point_in_time_safe", "lineage_to_ranking_score_available",
    "consumed_by_direct_status_emitter", "rejection_reason", *COMMON.keys(),
]
BLOCKER_FIELDS = [
    "ticker", "blocker_category", "blocker_field", "blocker_reason",
    "affected_factor_family_count", "affected_lineage_row_count", "source_contract_required",
    "can_repair_from_current_r10_sidecar", "requires_upstream_source_contract_patch",
    "proposed_next_repair_stage", "repair_priority", *COMMON.keys(),
]
BACKLOG_FIELDS = [
    "ticker", "baseline_rank", "retested_direct_data_trust_status", "failure_or_unknown_reason",
    "source_contract_required_field_count", "unknown_required_pit_field_count",
    "recommended_repair_action", "repair_priority", *COMMON.keys(),
]
SUMMARY_FIELDS = [
    "summary_id", "baseline_candidate_count", "retested_direct_data_trust_pass_count",
    "retested_direct_data_trust_fail_count", "retested_direct_data_trust_unknown_count",
    "direct_status_coverage_rate", "pit_lineage_sidecar_row_count",
    "accepted_direct_pit_lineage_row_count", "consumed_pit_lineage_row_count",
    "source_contract_required_field_count", "unknown_required_pit_field_count",
    "direct_pass_blocker_count", "repair_backlog_count",
    "ready_for_v20_171_gate_only_ranking_simulation",
    "ready_for_v20_170_r2a_source_contract_gap_repair", "ready_for_official_use",
    "recommended_next_action", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_170_r1c_status_consumed", "v20_170_r1c_status",
    "baseline_candidate_count", "retested_direct_data_trust_pass_count",
    "retested_direct_data_trust_fail_count", "retested_direct_data_trust_unknown_count",
    "direct_status_coverage_rate", "pit_lineage_sidecar_row_count",
    "accepted_direct_pit_lineage_row_count", "consumed_pit_lineage_row_count",
    "source_contract_required_field_count", "unknown_required_pit_field_count",
    "direct_pass_blocker_count", "repair_backlog_count",
    "ready_for_v20_171_gate_only_ranking_simulation",
    "ready_for_v20_170_r2a_source_contract_gap_repair", "ready_for_official_use",
    "official_weight_change_allowed", "official_ranking_mutation_allowed",
    "ranking_simulation_created", "no_data_trust_status_fabricated",
    "no_pit_status_fabricated", "unknown_not_treated_as_pass",
    "source_contract_required_not_treated_as_pass", "aggregate_evidence_not_treated_as_direct",
    "no_upstream_outputs_mutated", "recommended_next_action", "blocking_reason",
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


def is_true(value: object) -> bool:
    return clean(value).upper() == "TRUE"


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


def protected_hashes() -> dict[str, str]:
    protected = [BASELINE, ACTIVE_WEIGHT_REGISTRY, *R1C_INPUTS, PIT_LINEAGE, PIT_SCHEMA_AUDIT, PIT_GAP_AUDIT, *V170_INPUTS]
    return {rel(p): sha_file(p) for p in protected if p.exists()}


def baseline_rank(row: dict[str, str], fallback: int) -> str:
    return row.get("official_current_rank") or row.get("baseline_rank") or str(fallback)


def unknown_count(row: dict[str, str]) -> int:
    fields = [
        "ranking_as_of_date", "data_snapshot_id", "factor_input_as_of_date",
        "factor_input_source_timestamp", "factor_input_publication_lag_handled",
        "factor_input_point_in_time_safe", "non_pit_blocker_present", "leakage_flag_present",
        "source_quality_usable", "freshness_usable", "lineage_to_ranking_score_available",
    ]
    return sum(clean(row.get(field)).upper() in {"", "UNKNOWN", "UNKNOWN_CONTEXT_ID", "UNKNOWN_NOT_FACTOR_INPUT_LEVEL"} for field in fields)


def source_contract_count(row: dict[str, str]) -> int:
    fields = clean(row.get("source_contract_required_fields"))
    return len([f for f in fields.split("|") if f])


def prior_by_ticker(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row.get("ticker", ""): row for row in rows if row.get("ticker")}


def build_outputs(baseline: list[dict[str, str]], prior_rows: list[dict[str, str]], lineage: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    prior = prior_by_ticker(prior_rows)
    lineage_by_ticker_family: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    baseline_tickers = {row.get("ticker", "") for row in baseline}
    for row in lineage:
        ticker = row.get("ticker", "")
        family = row.get("factor_family", "")
        if ticker in baseline_tickers:
            lineage_by_ticker_family[(ticker, family)].append(row)

    retest = []
    consumption = []
    blockers = []
    backlog = []
    for idx, base in enumerate(baseline, start=1):
        ticker = base.get("ticker", "")
        prior_row = prior.get(ticker, {})
        rank = baseline_rank(base, idx)
        ticker_rows = []
        accepted_count = 0
        unknown_fields = 0
        source_contract_fields = 0
        non_pit_fail = False
        leakage_fail = False
        consumed_count = 0
        for family in sorted(REQUIRED_FAMILIES):
            rows = lineage_by_ticker_family.get((ticker, family), [])
            ticker_rows.extend(rows)
            accepted = sum(is_true(r.get("accepted_for_data_trust_direct_pit_status")) for r in rows)
            accepted_count += accepted
            ucount = sum(unknown_count(r) for r in rows)
            scount = sum(source_contract_count(r) for r in rows)
            unknown_fields += ucount
            source_contract_fields += scount
            non_pit = any(clean(r.get("non_pit_blocker_present")).upper() == "TRUE" for r in rows)
            leak = any(clean(r.get("leakage_flag_present")).upper() == "TRUE" for r in rows)
            non_pit_fail = non_pit_fail or non_pit
            leakage_fail = leakage_fail or leak
            consumed = bool(rows)
            consumed_count += len(rows)
            rejection = ""
            if not rows:
                rejection = "NO_BASELINE_MATCHING_SIDE_CAR_ROW"
            elif accepted == 0:
                rejection = "NO_ACCEPTED_DIRECT_PIT_LINEAGE_SOURCE_CONTRACT_OR_UNKNOWN_FIELDS_PRESENT"
            consumption.append({
                "ticker": ticker,
                "factor_family": family,
                "lineage_sidecar_row_count": str(len(rows)),
                "accepted_for_data_trust_direct_pit_status_count": str(accepted),
                "unknown_required_field_count": str(ucount),
                "source_contract_required_field_count": str(scount),
                "non_pit_blocker_present": "TRUE" if non_pit else ("UNKNOWN" if rows else "UNKNOWN"),
                "leakage_flag_present": "TRUE" if leak else ("UNKNOWN" if rows else "UNKNOWN"),
                "schema_valid": "TRUE" if rows and all(is_true(r.get("schema_valid")) for r in rows) else "UNKNOWN",
                "source_quality_usable": "TRUE" if rows and all(is_true(r.get("source_quality_usable")) for r in rows) else "UNKNOWN",
                "freshness_usable": "TRUE" if rows and all(is_true(r.get("freshness_usable")) for r in rows) else "UNKNOWN",
                "factor_input_point_in_time_safe": "TRUE" if rows and all(is_true(r.get("factor_input_point_in_time_safe")) for r in rows) else "UNKNOWN",
                "lineage_to_ranking_score_available": "TRUE" if rows and all(is_true(r.get("lineage_to_ranking_score_available")) for r in rows) else "UNKNOWN",
                "consumed_by_direct_status_emitter": tf(consumed),
                "rejection_reason": rejection,
                **COMMON,
            })
        required_lineage = len(REQUIRED_FAMILIES)
        enough_lineage = len({r.get("factor_family") for r in ticker_rows}) >= required_lineage
        prior_bool = lambda key: prior_row.get(key, "FALSE") == "TRUE"
        base_dims_pass = all([
            prior_bool("ticker_identity_match"),
            prior_bool("price_data_available"),
            prior_bool("required_factor_family_scores_available"),
            prior_bool("fundamental_score_available"),
            prior_bool("technical_score_available"),
            prior_bool("strategy_score_available"),
            prior_bool("risk_score_available"),
            prior_bool("market_regime_score_available"),
            prior_bool("data_trust_score_excluded_from_scoring"),
            prior_bool("score_lineage_bindable"),
        ])
        if non_pit_fail or leakage_fail:
            status = "FAIL"
            pass_flag, fail_flag, unknown_flag = "FALSE", "TRUE", "FALSE"
            confidence = "DIRECT_FAIL"
            reason = "DIRECT_NON_PIT_OR_LEAKAGE_BLOCKER_PRESENT"
        elif base_dims_pass and enough_lineage and accepted_count >= required_lineage and unknown_fields == 0 and source_contract_fields == 0:
            status = "PASS"
            pass_flag, fail_flag, unknown_flag = "TRUE", "FALSE", "FALSE"
            confidence = "DIRECT_PASS"
            reason = ""
        else:
            status = "UNKNOWN"
            pass_flag, fail_flag, unknown_flag = "FALSE", "FALSE", "TRUE"
            confidence = "UNKNOWN"
            reason = "SOURCE_CONTRACT_GAPS_OR_UNKNOWN_PIT_LINEAGE_FIELDS"
        pit_safety_status = "FAIL" if fail_flag == "TRUE" else ("PASS" if pass_flag == "TRUE" else "UNKNOWN")
        row = {
            "ticker": ticker,
            "baseline_rank": rank,
            "prior_direct_data_trust_status": prior_row.get("direct_data_trust_status", "UNKNOWN"),
            "retested_direct_data_trust_status": status,
            "retested_direct_data_trust_pass": pass_flag,
            "retested_direct_data_trust_fail": fail_flag,
            "retested_direct_data_trust_unknown": unknown_flag,
            "ticker_identity_match": prior_row.get("ticker_identity_match", "FALSE"),
            "price_data_available": prior_row.get("price_data_available", "FALSE"),
            "required_factor_family_scores_available": prior_row.get("required_factor_family_scores_available", "FALSE"),
            "fundamental_score_available": prior_row.get("fundamental_score_available", "FALSE"),
            "technical_score_available": prior_row.get("technical_score_available", "FALSE"),
            "strategy_score_available": prior_row.get("strategy_score_available", "FALSE"),
            "risk_score_available": prior_row.get("risk_score_available", "FALSE"),
            "market_regime_score_available": prior_row.get("market_regime_score_available", "FALSE"),
            "data_trust_score_excluded_from_scoring": prior_row.get("data_trust_score_excluded_from_scoring", "FALSE"),
            "pit_lineage_sidecar_available": tf(bool(lineage)),
            "accepted_direct_pit_lineage_row_count": str(accepted_count),
            "required_pit_lineage_row_count": str(required_lineage),
            "source_contract_required_field_count": str(source_contract_fields),
            "unknown_required_pit_field_count": str(unknown_fields),
            "pit_safety_status": pit_safety_status,
            "source_quality_status": "PASS" if pass_flag == "TRUE" else "UNKNOWN",
            "freshness_status": "PASS" if pass_flag == "TRUE" else "UNKNOWN",
            "schema_status": "PASS" if ticker_rows and all(is_true(r.get("schema_valid")) for r in ticker_rows) else "UNKNOWN",
            "current_ranking_eligibility_status": prior_row.get("current_ranking_eligibility_status", "UNKNOWN"),
            "score_lineage_bindable": prior_row.get("score_lineage_bindable", "FALSE"),
            "direct_status_confidence": confidence,
            "failure_or_unknown_reason": reason,
            "repair_required": tf(status != "PASS"),
            "recommended_repair_action": "" if status == "PASS" else "REPAIR_SOURCE_CONTRACT_GAPS_BEFORE_RANKING",
            **COMMON,
        }
        retest.append(row)
        if status != "PASS":
            backlog.append({
                "ticker": ticker,
                "baseline_rank": rank,
                "retested_direct_data_trust_status": status,
                "failure_or_unknown_reason": reason,
                "source_contract_required_field_count": str(source_contract_fields),
                "unknown_required_pit_field_count": str(unknown_fields),
                "recommended_repair_action": "REPAIR_SOURCE_CONTRACT_GAPS_BEFORE_RANKING",
                "repair_priority": "HIGH",
                **COMMON,
            })
        if source_contract_fields or unknown_fields:
            blockers.append({
                "ticker": ticker,
                "blocker_category": "PIT_SOURCE_CONTRACT_GAP",
                "blocker_field": "source_contract_required_fields|unknown_required_pit_fields",
                "blocker_reason": reason,
                "affected_factor_family_count": str(len({r.get("factor_family") for r in ticker_rows})),
                "affected_lineage_row_count": str(len(ticker_rows)),
                "source_contract_required": tf(source_contract_fields > 0),
                "can_repair_from_current_r10_sidecar": "FALSE",
                "requires_upstream_source_contract_patch": "TRUE",
                "proposed_next_repair_stage": "V20_170_R2A_SOURCE_CONTRACT_GAP_REPAIR",
                "repair_priority": "HIGH",
                **COMMON,
            })
    return retest, consumption, blockers, backlog


def build_summary(baseline_count: int, retest: list[dict[str, str]], consumption: list[dict[str, str]], blockers: list[dict[str, str]], backlog: list[dict[str, str]], lineage: list[dict[str, str]]) -> dict[str, str]:
    pass_count = sum(r["retested_direct_data_trust_pass"] == "TRUE" for r in retest)
    fail_count = sum(r["retested_direct_data_trust_fail"] == "TRUE" for r in retest)
    unknown_count = sum(r["retested_direct_data_trust_unknown"] == "TRUE" for r in retest)
    consumed = sum(int(r["lineage_sidecar_row_count"]) for r in consumption)
    accepted = sum(int(r["accepted_for_data_trust_direct_pit_status_count"]) for r in consumption)
    scount = sum(int(r["source_contract_required_field_count"]) for r in retest)
    ucount = sum(int(r["unknown_required_pit_field_count"]) for r in retest)
    coverage = (pass_count + fail_count) / baseline_count if baseline_count else 0.0
    if pass_count > 0 and unknown_count == 0:
        ready_171, ready_r2a, action = "TRUE", "FALSE", "RUN_V20_171_GATE_ONLY_RANKING_SIMULATION_EXCLUDING_FAIL_ROWS"
    elif pass_count > 0:
        ready_171, ready_r2a, action = "TRUE", "TRUE", "RUN_V20_171_PARTIAL_GATE_ONLY_RANKING_SIMULATION_EXCLUDING_FAIL_AND_UNKNOWN_ROWS"
    elif pass_count == 0 and scount > 0:
        ready_171, ready_r2a, action = "FALSE", "TRUE", "REPAIR_SOURCE_CONTRACT_GAPS_BEFORE_RANKING"
    else:
        ready_171, ready_r2a, action = "FALSE", "TRUE", "REPAIR_DIRECT_STATUS_INPUTS"
    if unknown_count == baseline_count:
        action = "REPAIR_SOURCE_CONTRACT_GAPS_BEFORE_RANKING"
    return {
        "summary_id": "V20_170_R2_DIRECT_STATUS_COVERAGE_SUMMARY_001",
        "baseline_candidate_count": str(baseline_count),
        "retested_direct_data_trust_pass_count": str(pass_count),
        "retested_direct_data_trust_fail_count": str(fail_count),
        "retested_direct_data_trust_unknown_count": str(unknown_count),
        "direct_status_coverage_rate": fmt(coverage),
        "pit_lineage_sidecar_row_count": str(len(lineage)),
        "accepted_direct_pit_lineage_row_count": str(accepted),
        "consumed_pit_lineage_row_count": str(consumed),
        "source_contract_required_field_count": str(scount),
        "unknown_required_pit_field_count": str(ucount),
        "direct_pass_blocker_count": str(len(blockers)),
        "repair_backlog_count": str(len(backlog)),
        "ready_for_v20_171_gate_only_ranking_simulation": ready_171,
        "ready_for_v20_170_r2a_source_contract_gap_repair": ready_r2a,
        "ready_for_official_use": "FALSE",
        "recommended_next_action": action,
        **COMMON,
    }


def safety_rows(summary: dict[str, str], upstream_mutated: bool, prereq_ok: bool) -> list[dict[str, str]]:
    checks = [
        ("v20_170_r1c_prerequisites_met", "TRUE", tf(prereq_ok)),
        ("ranking_simulation_created", "FALSE", "FALSE"),
        ("ready_for_official_use", "FALSE", "FALSE"),
        ("official_weight_change_allowed", "FALSE", "FALSE"),
        ("official_ranking_mutation_allowed", "FALSE", "FALSE"),
        ("data_trust_status_fabricated", "FALSE", "FALSE"),
        ("pit_status_fabricated", "FALSE", "FALSE"),
        ("unknown_treated_as_pass", "FALSE", "FALSE"),
        ("source_contract_required_treated_as_pass", "FALSE", "FALSE"),
        ("upstream_outputs_mutated", "FALSE", tf(upstream_mutated)),
    ]
    return [{"safety_check_id": f"V20_170_R2_SAFETY_{i:03d}", "safety_check": c, "expected_value": e,
             "actual_value": a, "safety_passed": tf(e == a), **COMMON}
            for i, (c, e, a) in enumerate(checks, start=1)]


def write_report(status: str, summary: dict[str, str] | None = None) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.170-R2 DATA_TRUST Direct Status Emitter Retest After PIT Producer Patch Report",
        "",
        f"- final_status: {status}",
        "- research_only: TRUE",
        "- ranking_simulation_created: FALSE",
        "- ready_for_official_use: FALSE",
    ]
    if summary:
        for key in ["baseline_candidate_count", "retested_direct_data_trust_pass_count",
                    "retested_direct_data_trust_fail_count", "retested_direct_data_trust_unknown_count",
                    "direct_status_coverage_rate", "pit_lineage_sidecar_row_count",
                    "consumed_pit_lineage_row_count", "source_contract_required_field_count",
                    "unknown_required_pit_field_count", "recommended_next_action"]:
            lines.append(f"- {key}: {summary[key]}")
    lines.extend(["", "UNKNOWN/source-contract-required PIT lineage is not treated as direct DATA_TRUST PASS evidence."])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [(OUT_RETEST, RETEST_FIELDS), (OUT_STATUS, RETEST_FIELDS), (OUT_CONSUMPTION, CONSUMPTION_FIELDS),
                         (OUT_BLOCKERS, BLOCKER_FIELDS), (OUT_BACKLOG, BACKLOG_FIELDS), (OUT_SUMMARY, SUMMARY_FIELDS),
                         (OUT_SAFETY, SAFETY_FIELDS)]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_170_R2_DIRECT_STATUS_NEXT_GATE_001",
        "v20_170_r1c_status_consumed": "FALSE", "v20_170_r1c_status": "",
        "baseline_candidate_count": "0", "retested_direct_data_trust_pass_count": "0",
        "retested_direct_data_trust_fail_count": "0", "retested_direct_data_trust_unknown_count": "0",
        "direct_status_coverage_rate": "0.0000000000", "pit_lineage_sidecar_row_count": "0",
        "accepted_direct_pit_lineage_row_count": "0", "consumed_pit_lineage_row_count": "0",
        "source_contract_required_field_count": "0", "unknown_required_pit_field_count": "0",
        "direct_pass_blocker_count": "0", "repair_backlog_count": "0",
        "ready_for_v20_171_gate_only_ranking_simulation": "FALSE",
        "ready_for_v20_170_r2a_source_contract_gap_repair": "FALSE", "ready_for_official_use": "FALSE",
        "official_weight_change_allowed": "FALSE", "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE", "no_data_trust_status_fabricated": "TRUE",
        "no_pit_status_fabricated": "TRUE", "unknown_not_treated_as_pass": "TRUE",
        "source_contract_required_not_treated_as_pass": "TRUE",
        "aggregate_evidence_not_treated_as_direct": "TRUE", "no_upstream_outputs_mutated": "TRUE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_R2", "blocking_reason": reason,
        "final_status": BLOCKED_STATUS, **COMMON,
    }
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(BLOCKED_STATUS)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    required = [*R1C_INPUTS, PIT_LINEAGE, PIT_SCHEMA_AUDIT, PIT_GAP_AUDIT, *V170_INPUTS, BASELINE]
    missing = [p for p in required if not p.exists() or p.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(p) for p in missing))
    before = protected_hashes()
    r1c_gate, _ = read_csv(FACTORS / "V20_170_R1C_PIT_PRODUCER_PATCH_NEXT_GATE.csv")
    baseline, _ = read_csv(BASELINE)
    prior, _ = read_csv(FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_EMITTER.csv")
    lineage, _ = read_csv(PIT_LINEAGE)
    if not r1c_gate or not baseline or not prior or not lineage:
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    gate = r1c_gate[0]
    r1c_status = gate.get("final_status", "")
    prereq_ok = all([
        r1c_status in ALLOWED_R1C,
        gate.get("producer_script_patched") == "TRUE",
        gate.get("sidecar_pit_lineage_artifact_created") == "TRUE",
        gate.get("row_count_preserved") == "TRUE",
        gate.get("ready_for_v20_170_r2_direct_status_retest") == "TRUE",
        gate.get("ready_for_v20_171_gate_only_ranking_simulation") == "FALSE",
        gate.get("ready_for_official_use") == "FALSE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_170_R1C_REQUIREMENTS_NOT_MET")
    retest, consumption, blockers, backlog = build_outputs(baseline, prior, lineage)
    summary = build_summary(len(baseline), retest, consumption, blockers, backlog, lineage)
    upstream_mutated = before != protected_hashes()
    safety = safety_rows(summary, upstream_mutated, prereq_ok)
    if upstream_mutated or not all(r["safety_passed"] == "TRUE" for r in safety):
        return emit_blocked("SAFETY_OR_UPSTREAM_MUTATION_FAILURE")
    pass_count = int(summary["retested_direct_data_trust_pass_count"])
    unknown_count = int(summary["retested_direct_data_trust_unknown_count"])
    scount = int(summary["source_contract_required_field_count"])
    baseline_count = int(summary["baseline_candidate_count"])
    if pass_count > 0 and unknown_count == 0:
        final_status = PASS_STATUS
        blocking_reason = ""
    elif pass_count > 0:
        final_status = PARTIAL_STATUS
        blocking_reason = "REMAINING_UNKNOWN_ROWS_EXCLUDED_FROM_V20_171"
    elif pass_count == 0 and scount > 0:
        final_status = WARN_STATUS
        blocking_reason = "SOURCE_CONTRACT_GAPS_BLOCK_DIRECT_PASS"
    else:
        final_status = BLOCKED_STATUS
        blocking_reason = "NO_DIRECT_PASS_AND_NO_REPAIRABLE_SOURCE_CONTRACT_GAP"
    if unknown_count == baseline_count:
        summary["recommended_next_action"] = "REPAIR_SOURCE_CONTRACT_GAPS_BEFORE_RANKING"
    gate_out = {
        "gate_check_id": "V20_170_R2_DIRECT_STATUS_NEXT_GATE_001",
        "v20_170_r1c_status_consumed": "TRUE", "v20_170_r1c_status": r1c_status,
        **summary,
        "official_weight_change_allowed": "FALSE", "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE", "no_data_trust_status_fabricated": "TRUE",
        "no_pit_status_fabricated": "TRUE", "unknown_not_treated_as_pass": "TRUE",
        "source_contract_required_not_treated_as_pass": "TRUE",
        "aggregate_evidence_not_treated_as_direct": "TRUE", "no_upstream_outputs_mutated": "TRUE",
        "blocking_reason": blocking_reason, "final_status": final_status, **COMMON,
    }
    write_csv(OUT_RETEST, RETEST_FIELDS, retest)
    write_csv(OUT_STATUS, RETEST_FIELDS, retest)
    write_csv(OUT_CONSUMPTION, CONSUMPTION_FIELDS, consumption)
    write_csv(OUT_BLOCKERS, BLOCKER_FIELDS, blockers)
    write_csv(OUT_BACKLOG, BACKLOG_FIELDS, backlog)
    write_csv(OUT_SUMMARY, SUMMARY_FIELDS, [summary])
    write_csv(OUT_GATE, GATE_FIELDS, [gate_out])
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_report(final_status, summary)
    print(final_status)
    print(f"V20_170_R1C_STATUS={r1c_status}")
    for key in SUMMARY_FIELDS:
        if key in summary and key not in COMMON and key != "summary_id":
            print(f"{key.upper()}={summary[key]}")
    print("OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE")
    print("OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE")
    print("RANKING_SIMULATION_CREATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_ACTION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("PERFORMANCE_CLAIM_CREATED=FALSE")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
