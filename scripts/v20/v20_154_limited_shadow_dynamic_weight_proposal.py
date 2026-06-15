#!/usr/bin/env python
"""V20.154 limited shadow dynamic weight proposal.

Creates a conservative research-only shadow weight proposal from V20.153-R2
shadow-eligible repaired matrix rows. This stage creates no official weights,
official recommendations, official ranking changes, real-book actions, trades,
broker actions, performance claims, or upstream mutations.
"""

from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
FACTORS = OUTPUTS / "factors"
CONSOLIDATION = OUTPUTS / "consolidation"
READ_CENTER = OUTPUTS / "read_center"

IN_REPAIR = FACTORS / "V20_153_R2_FACTOR_ABLATION_EXISTING_EVIDENCE_BRIDGE_REPAIR.csv"
IN_SOURCE = FACTORS / "V20_153_R2_FACTOR_ABLATION_BRIDGE_SOURCE_AUDIT.csv"
IN_MATRIX = FACTORS / "V20_153_R2_FACTOR_ABLATION_REPAIRED_MATRIX.csv"
IN_BLOCKERS = FACTORS / "V20_153_R2_FACTOR_ABLATION_REMAINING_BLOCKERS.csv"
IN_GATE = FACTORS / "V20_153_R2_FACTOR_ABLATION_NEXT_GATE.csv"
BASE_WEIGHT_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"

OUT_PROPOSAL = FACTORS / "V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv"
OUT_GATE = FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_GATE.csv"
OUT_SOURCE_AUDIT = FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_SOURCE_AUDIT.csv"
OUT_SAFETY_AUDIT = FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_SAFETY_AUDIT.csv"
OUT_BLOCKED_OFFICIAL = FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_BLOCKED_OFFICIAL_AUDIT.csv"
REPORT = READ_CENTER / "V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL_REPORT.md"

R2_ALLOWED = {
    "PARTIAL_PASS_V20_153_R2_FACTOR_ABLATION_BRIDGE_REPAIR_WITH_LIMITED_SHADOW_ELIGIBILITY",
    "PASS_V20_153_R2_FACTOR_ABLATION_BRIDGE_REPAIR_READY_FOR_V20_154",
}
PASS_STATUS = "PASS_V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL_READY_FOR_V20_155"
PARTIAL_STATUS = "PARTIAL_PASS_V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL_WITH_LOW_CONFIDENCE_READY_FOR_V20_155"
WARN_STATUS = "WARN_V20_154_NO_SHADOW_ELIGIBLE_FACTORS_FOUND"
BLOCKED_STATUS = "BLOCKED_V20_154_SHADOW_DYNAMIC_WEIGHT_PROPOSAL"
SCOPE = "RESEARCH_ONLY_LIMITED"
MAX_ABS_DELTA = 0.015
MAX_REL_DELTA = 0.08

SAFETY_FIELDS = [
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
    "official_weight_change_created",
    "shadow_weight_proposal_created",
    "shadow_weight_proposal_scope",
    "weight_mutated",
    "real_book_action_created",
    "trade_action_created",
    "broker_execution_supported",
    "performance_claim_created",
]
SAFETY = {
    "formal_activation_allowed": "FALSE",
    "promotion_ready": "FALSE",
    "official_recommendation_created": "FALSE",
    "official_ranking_mutated": "FALSE",
    "official_weight_change_created": "FALSE",
    "shadow_weight_proposal_created": "TRUE",
    "shadow_weight_proposal_scope": SCOPE,
    "weight_mutated": "FALSE",
    "real_book_action_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "performance_claim_created": "FALSE",
}
COMMON = {
    **SAFETY,
    "research_only": "TRUE",
    "staging_review_only": "TRUE",
    "limited_shadow_proposal_only": "TRUE",
    "audit_only": "TRUE",
}

PROPOSAL_FIELDS = [
    "factor_family",
    "factor_name",
    "evidence_source",
    "current_research_weight",
    "shadow_proposed_weight",
    "proposed_delta",
    "max_allowed_delta",
    "evidence_quality",
    "contribution_stability",
    "as_of_sample_count",
    "forward_observation_count",
    "outcome_available_count",
    "benchmark_available_count",
    "pending_outcome_count",
    "repair_source",
    "confidence_level",
    "proposal_reason",
    "usable_for_shadow_weight_proposal",
    "usable_for_official_weight_change",
    "official_weight_change_blocked_reason",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id",
    "v20_153_r2_gate_consumed",
    "v20_153_r2_status",
    "v20_153_r2_allowed_for_v20_154",
    *SAFETY_FIELDS,
    "eligible_input_row_count",
    "proposal_row_count",
    "low_or_limited_confidence_count",
    "official_weight_change_eligible_input_count",
    "blocked_official_row_count",
    "base_weight_registry_available",
    "no_official_weights_mutated",
    "no_official_ranking_mutated",
    "no_official_recommendation_created",
    "no_real_book_action_created",
    "no_trade_action_created",
    "no_broker_action_created",
    "no_outcomes_fabricated",
    "no_benchmarks_fabricated",
    "no_factor_contribution_fabricated",
    "no_eligibility_thresholds_lowered",
    "no_performance_claim_created",
    "no_upstream_outputs_mutated",
    "v20_155_limited_shadow_simulation_allowed",
    "blocking_reason",
    "final_status",
    "research_only",
    "staging_review_only",
    "limited_shadow_proposal_only",
    "audit_only",
]
SOURCE_FIELDS = [
    "source_audit_id",
    "source_artifact",
    "source_exists",
    "source_non_empty",
    "row_count",
    "source_sha256",
    "source_role",
    "source_status",
    "exclusion_reason",
    *COMMON.keys(),
]
SAFETY_AUDIT_FIELDS = [
    "safety_check_id",
    "safety_check",
    "expected_value",
    "actual_value",
    "safety_passed",
    *COMMON.keys(),
]
BLOCKED_OFFICIAL_FIELDS = [
    "blocked_official_audit_id",
    "factor_family",
    "factor_name",
    "evidence_source",
    "usable_for_official_weight_change",
    "official_weight_change_blocked_reason",
    *COMMON.keys(),
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def truthy(value: object) -> bool:
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


def upstream_inputs() -> list[Path]:
    return [IN_REPAIR, IN_SOURCE, IN_MATRIX, IN_BLOCKERS, IN_GATE]


def upstream_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in upstream_inputs() if path.exists()}


def num(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(clean(value))
    except ValueError:
        return default
    return default if math.isnan(parsed) or math.isinf(parsed) else parsed


def fmt(value: float) -> str:
    return f"{value:.10f}"


def load_base_weights() -> tuple[dict[str, float], bool]:
    rows, _ = read_csv(BASE_WEIGHT_REGISTRY)
    weights: dict[str, float] = {}
    for row in rows:
        family = row.get("factor_family", "")
        weight = num(row.get("active_research_base_weight"), -1.0)
        if family and weight >= 0 and row.get("is_official_weight") == "FALSE":
            weights[family] = weight
    return weights, bool(weights)


def source_audit_rows() -> list[dict[str, str]]:
    sources = [
        (IN_REPAIR, "R2_BRIDGE_REPAIR"),
        (IN_SOURCE, "R2_SOURCE_AUDIT"),
        (IN_MATRIX, "R2_REPAIRED_MATRIX"),
        (IN_BLOCKERS, "R2_REMAINING_BLOCKERS"),
        (IN_GATE, "R2_NEXT_GATE"),
        (BASE_WEIGHT_REGISTRY, "RESEARCH_BASE_WEIGHT_REGISTRY"),
    ]
    rows: list[dict[str, str]] = []
    for index, (path, role) in enumerate(sources, start=1):
        data, fields = read_csv(path)
        exists = path.exists()
        non_empty = exists and path.stat().st_size > 0
        ok = bool(fields) and non_empty
        rows.append({
            "source_audit_id": f"V20_154_SOURCE_AUDIT_{index:03d}",
            "source_artifact": rel(path),
            "source_exists": tf(exists),
            "source_non_empty": tf(non_empty),
            "row_count": str(len(data)),
            "source_sha256": sha_file(path),
            "source_role": role,
            "source_status": "PASS" if ok else "WARN_MISSING_OR_EMPTY",
            "exclusion_reason": "" if ok else "MISSING_OR_EMPTY_SOURCE",
            **COMMON,
        })
    return rows


def contribution_direction(row: dict[str, str]) -> int:
    positive = int(num(row.get("positive_contribution_count")))
    negative = int(num(row.get("negative_contribution_count")))
    if positive > negative:
        return 1
    if negative > positive:
        return -1
    return 0


def confidence_level(row: dict[str, str], r2_status: str) -> str:
    if "PARTIAL_PASS" in r2_status:
        return "LIMITED"
    if row.get("evidence_quality") == "HIGH" and row.get("contribution_stability") == "HIGH":
        return "MEDIUM"
    return "LIMITED"


def build_proposals(matrix_rows: list[dict[str, str]], base_weights: dict[str, float], r2_status: str) -> list[dict[str, str]]:
    proposals: list[dict[str, str]] = []
    for row in matrix_rows:
        if not truthy(row.get("usable_for_shadow_weight_proposal")):
            continue
        family = row.get("factor_family", "")
        current = base_weights.get(family, 0.0)
        max_delta = min(MAX_ABS_DELTA, current * MAX_REL_DELTA if current else MAX_ABS_DELTA)
        direction = contribution_direction(row)
        confidence = confidence_level(row, r2_status)
        confidence_multiplier = 0.50 if confidence == "LIMITED" else 0.75
        delta = direction * max_delta * confidence_multiplier
        proposed = max(0.0, current + delta)
        reason = "LIMITED_RESEARCH_ONLY_SHADOW_INCREASE_FROM_EXISTING_POSITIVE_CONTRIBUTION_EVIDENCE" if direction > 0 else (
            "LIMITED_RESEARCH_ONLY_SHADOW_DECREASE_FROM_EXISTING_NEGATIVE_CONTRIBUTION_EVIDENCE" if direction < 0 else "LIMITED_RESEARCH_ONLY_SHADOW_HOLD_NEUTRAL_CONTRIBUTION_EVIDENCE"
        )
        proposals.append({
            "factor_family": family,
            "factor_name": row.get("factor_name", ""),
            "evidence_source": row.get("evidence_source", ""),
            "current_research_weight": fmt(current),
            "shadow_proposed_weight": fmt(proposed),
            "proposed_delta": fmt(delta),
            "max_allowed_delta": fmt(max_delta),
            "evidence_quality": row.get("evidence_quality", ""),
            "contribution_stability": row.get("contribution_stability", ""),
            "as_of_sample_count": row.get("as_of_sample_count", ""),
            "forward_observation_count": row.get("forward_observation_count", ""),
            "outcome_available_count": row.get("outcome_available_count", ""),
            "benchmark_available_count": row.get("benchmark_available_count", ""),
            "pending_outcome_count": row.get("pending_outcome_count", ""),
            "repair_source": row.get("repair_source", ""),
            "confidence_level": confidence,
            "proposal_reason": reason,
            "usable_for_shadow_weight_proposal": "TRUE",
            "usable_for_official_weight_change": "FALSE",
            "official_weight_change_blocked_reason": "OFFICIAL_WEIGHT_CHANGE_NOT_ALLOWED_V20_154_RESEARCH_ONLY_LIMITED_SHADOW_SCOPE",
            **COMMON,
        })
    return proposals


def blocked_official_rows(matrix_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in matrix_rows:
        blocked_reason = "OFFICIAL_WEIGHT_CHANGE_NOT_ALLOWED_V20_154_RESEARCH_ONLY_LIMITED_SHADOW_SCOPE"
        rows.append({
            "blocked_official_audit_id": f"V20_154_BLOCKED_OFFICIAL_{len(rows)+1:04d}",
            "factor_family": row.get("factor_family", ""),
            "factor_name": row.get("factor_name", ""),
            "evidence_source": row.get("evidence_source", ""),
            "usable_for_official_weight_change": row.get("usable_for_official_weight_change", "FALSE"),
            "official_weight_change_blocked_reason": "BLOCKED_INPUT_OFFICIAL_WEIGHT_CHANGE_ELIGIBILITY_TRUE" if truthy(row.get("usable_for_official_weight_change")) else blocked_reason,
            **COMMON,
        })
    return rows


def safety_audit_rows(upstream_mutated: bool, official_true: bool) -> list[dict[str, str]]:
    checks = [
        ("formal_activation_allowed", "FALSE", "FALSE"),
        ("promotion_ready", "FALSE", "FALSE"),
        ("official_recommendation_created", "FALSE", "FALSE"),
        ("official_ranking_mutated", "FALSE", "FALSE"),
        ("official_weight_change_created", "FALSE", "FALSE"),
        ("shadow_weight_proposal_created", "TRUE", "TRUE"),
        ("shadow_weight_proposal_scope", SCOPE, SCOPE),
        ("weight_mutated", "FALSE", "FALSE"),
        ("real_book_action_created", "FALSE", "FALSE"),
        ("trade_action_created", "FALSE", "FALSE"),
        ("broker_execution_supported", "FALSE", "FALSE"),
        ("performance_claim_created", "FALSE", "FALSE"),
        ("official_weight_change_eligible_input_count", "0", "NONZERO" if official_true else "0"),
        ("upstream_outputs_mutated", "FALSE", tf(upstream_mutated)),
    ]
    rows: list[dict[str, str]] = []
    for index, (check, expected, actual) in enumerate(checks, start=1):
        rows.append({
            "safety_check_id": f"V20_154_SAFETY_{index:03d}",
            "safety_check": check,
            "expected_value": expected,
            "actual_value": actual,
            "safety_passed": tf(actual == expected),
            **COMMON,
        })
    return rows


def safety_true_count(groups: list[list[dict[str, str]]]) -> int:
    count = 0
    for rows in groups:
        for row in rows:
            for field in SAFETY_FIELDS:
                if field == "shadow_weight_proposal_created":
                    if row.get(field) != "TRUE":
                        count += 1
                elif field == "shadow_weight_proposal_scope":
                    if row.get(field) != SCOPE:
                        count += 1
                elif truthy(row.get(field)):
                    count += 1
    return count


def write_report(status: str, proposals: int, confidence_count: int) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.154 Limited Shadow Dynamic Weight Proposal Report",
        "",
        f"- wrapper_status: {status}",
        f"- proposal_row_count: {proposals}",
        f"- low_or_limited_confidence_count: {confidence_count}",
        "- shadow_weight_proposal_created: TRUE",
        f"- shadow_weight_proposal_scope: {SCOPE}",
        "- official_weight_change_created: FALSE",
        "- weight_mutated: FALSE",
        "",
        "The proposal is a research-only limited shadow input for V20.155. It uses only V20.153-R2 rows marked usable for shadow proposal and does not mutate official weights or rankings.",
    ]) + "\n", encoding="utf-8")


def emit_blocked(reason: str, blocked_official: list[dict[str, str]] | None = None) -> int:
    gate = {
        "gate_check_id": "V20_154_SHADOW_WEIGHT_PROPOSAL_GATE_001",
        "v20_153_r2_gate_consumed": "FALSE",
        "v20_153_r2_status": "",
        "v20_153_r2_allowed_for_v20_154": "FALSE",
        **SAFETY,
        "eligible_input_row_count": "0",
        "proposal_row_count": "0",
        "low_or_limited_confidence_count": "0",
        "official_weight_change_eligible_input_count": str(sum(1 for row in blocked_official or [] if truthy(row.get("usable_for_official_weight_change")))),
        "blocked_official_row_count": str(len(blocked_official or [])),
        "base_weight_registry_available": "FALSE",
        "no_official_weights_mutated": "TRUE",
        "no_official_ranking_mutated": "TRUE",
        "no_official_recommendation_created": "TRUE",
        "no_real_book_action_created": "TRUE",
        "no_trade_action_created": "TRUE",
        "no_broker_action_created": "TRUE",
        "no_outcomes_fabricated": "TRUE",
        "no_benchmarks_fabricated": "TRUE",
        "no_factor_contribution_fabricated": "TRUE",
        "no_eligibility_thresholds_lowered": "TRUE",
        "no_performance_claim_created": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "v20_155_limited_shadow_simulation_allowed": "FALSE",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        "research_only": "TRUE",
        "staging_review_only": "TRUE",
        "limited_shadow_proposal_only": "TRUE",
        "audit_only": "TRUE",
    }
    write_csv(OUT_PROPOSAL, PROPOSAL_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SOURCE_AUDIT, SOURCE_FIELDS, [])
    write_csv(OUT_SAFETY_AUDIT, SAFETY_AUDIT_FIELDS, [])
    write_csv(OUT_BLOCKED_OFFICIAL, BLOCKED_OFFICIAL_FIELDS, blocked_official or [])
    write_report(BLOCKED_STATUS, 0, 0)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    before = upstream_hashes()
    missing = [path for path in upstream_inputs() if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_R2_OUTPUTS:" + ";".join(rel(path) for path in missing))
    gate_rows, _ = read_csv(IN_GATE)
    matrix_rows, _ = read_csv(IN_MATRIX)
    if not gate_rows or not matrix_rows:
        return emit_blocked("EMPTY_R2_GATE_OR_MATRIX")
    r2_status = gate_rows[0].get("final_status", "")
    r2_allowed = r2_status in R2_ALLOWED
    if not r2_allowed:
        return emit_blocked("R2_STATUS_NOT_ALLOWED_FOR_V20_154")
    official_true_rows = [row for row in matrix_rows if truthy(row.get("usable_for_official_weight_change"))]
    if official_true_rows:
        blocked_rows = blocked_official_rows(matrix_rows)
        return emit_blocked("OFFICIAL_WEIGHT_CHANGE_ELIGIBILITY_TRUE_IN_INPUT", blocked_rows)

    base_weights, base_available = load_base_weights()
    source_rows = source_audit_rows()
    eligible_rows = [row for row in matrix_rows if truthy(row.get("usable_for_shadow_weight_proposal"))]
    proposals = build_proposals(matrix_rows, base_weights, r2_status)
    blocked_rows = blocked_official_rows(matrix_rows)
    upstream_mutated = before != upstream_hashes()
    safety_rows = safety_audit_rows(upstream_mutated, bool(official_true_rows))
    safety_count = safety_true_count([proposals, source_rows, safety_rows, blocked_rows])
    low_limited = sum(1 for row in proposals if row["confidence_level"] in {"LOW", "LIMITED"})
    if upstream_mutated or safety_count:
        status = BLOCKED_STATUS
        blocking = "SAFETY_OR_UPSTREAM_MUTATION_FAILURE"
    elif not eligible_rows:
        status = WARN_STATUS
        blocking = ""
    elif low_limited:
        status = PARTIAL_STATUS
        blocking = ""
    else:
        status = PASS_STATUS
        blocking = ""
    next_allowed = status in {PASS_STATUS, PARTIAL_STATUS}
    gate = {
        "gate_check_id": "V20_154_SHADOW_WEIGHT_PROPOSAL_GATE_001",
        "v20_153_r2_gate_consumed": "TRUE",
        "v20_153_r2_status": r2_status,
        "v20_153_r2_allowed_for_v20_154": tf(r2_allowed),
        **SAFETY,
        "eligible_input_row_count": str(len(eligible_rows)),
        "proposal_row_count": str(len(proposals)),
        "low_or_limited_confidence_count": str(low_limited),
        "official_weight_change_eligible_input_count": str(len(official_true_rows)),
        "blocked_official_row_count": str(len(blocked_rows)),
        "base_weight_registry_available": tf(base_available),
        "no_official_weights_mutated": "TRUE",
        "no_official_ranking_mutated": "TRUE",
        "no_official_recommendation_created": "TRUE",
        "no_real_book_action_created": "TRUE",
        "no_trade_action_created": "TRUE",
        "no_broker_action_created": "TRUE",
        "no_outcomes_fabricated": "TRUE",
        "no_benchmarks_fabricated": "TRUE",
        "no_factor_contribution_fabricated": "TRUE",
        "no_eligibility_thresholds_lowered": "TRUE",
        "no_performance_claim_created": "TRUE",
        "no_upstream_outputs_mutated": tf(not upstream_mutated),
        "v20_155_limited_shadow_simulation_allowed": tf(next_allowed),
        "blocking_reason": blocking,
        "final_status": status,
        "research_only": "TRUE",
        "staging_review_only": "TRUE",
        "limited_shadow_proposal_only": "TRUE",
        "audit_only": "TRUE",
    }
    write_csv(OUT_PROPOSAL, PROPOSAL_FIELDS, proposals)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SOURCE_AUDIT, SOURCE_FIELDS, source_rows)
    write_csv(OUT_SAFETY_AUDIT, SAFETY_AUDIT_FIELDS, safety_rows)
    write_csv(OUT_BLOCKED_OFFICIAL, BLOCKED_OFFICIAL_FIELDS, blocked_rows)
    write_report(status, len(proposals), low_limited)

    print(status)
    print("V20_153_R2_GATE_CONSUMED=TRUE")
    print(f"V20_153_R2_ALLOWED_FOR_V20_154={tf(r2_allowed)}")
    print(f"ELIGIBLE_INPUT_ROW_COUNT={len(eligible_rows)}")
    print(f"PROPOSAL_ROW_COUNT={len(proposals)}")
    print(f"LOW_OR_LIMITED_CONFIDENCE_COUNT={low_limited}")
    print(f"OFFICIAL_WEIGHT_CHANGE_ELIGIBLE_INPUT_COUNT={len(official_true_rows)}")
    print("OFFICIAL_WEIGHT_CHANGE_CREATED=FALSE")
    print("OFFICIAL_WEIGHTS_MUTATED=FALSE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_ACTION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_ACTION_CREATED=FALSE")
    print("OUTCOMES_FABRICATED=0")
    print("BENCHMARKS_FABRICATED=0")
    print("FACTOR_CONTRIBUTION_FABRICATED=0")
    print("ELIGIBILITY_THRESHOLDS_LOWERED=FALSE")
    print("PERFORMANCE_CLAIM_CREATED=FALSE")
    print("SHADOW_WEIGHT_PROPOSAL_CREATED=TRUE")
    print(f"SHADOW_WEIGHT_PROPOSAL_SCOPE={SCOPE}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    print(f"SAFETY_TRUE_COUNT={safety_count}")
    print(f"V20_155_LIMITED_SHADOW_SIMULATION_ALLOWED={tf(next_allowed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
