#!/usr/bin/env python
"""V20.168 DATA_TRUST gate-only operator decision capture.

Captures the explicit operator approval for continuing DATA_TRUST gate-only
research policy with direct ticker-level mapping still required before any
official use. This stage does not mutate official rankings, official weights,
recommendations, actions, performance claims, or upstream outputs.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"

V167_PACKET = FACTORS / "V20_167_DATA_TRUST_GATE_ONLY_OPERATOR_REVIEW_PACKET.csv"
V167_POLICY = FACTORS / "V20_167_DATA_TRUST_GATE_ONLY_POLICY_REVIEW.csv"
V167_MAPPING = FACTORS / "V20_167_DATA_TRUST_MAPPING_LIMITATION_REVIEW.csv"
V167_OPTIONS = FACTORS / "V20_167_DATA_TRUST_OPERATOR_OPTIONS.csv"
V167_GATE = FACTORS / "V20_167_DATA_TRUST_GATE_ONLY_NEXT_GATE.csv"
V167_SAFETY = FACTORS / "V20_167_DATA_TRUST_GATE_ONLY_SAFETY_AUDIT.csv"

OUT_DECISION = FACTORS / "V20_168_DATA_TRUST_GATE_ONLY_OPERATOR_DECISION_CAPTURE.csv"
OUT_GATE = FACTORS / "V20_168_DATA_TRUST_GATE_ONLY_DECISION_GATE.csv"
OUT_SAFETY = FACTORS / "V20_168_DATA_TRUST_GATE_ONLY_DECISION_SAFETY_AUDIT.csv"
OUT_DIRECT_MAPPING = FACTORS / "V20_168_DATA_TRUST_DIRECT_MAPPING_REQUIREMENT_PACKET.csv"
OUT_NEXT_STAGE = FACTORS / "V20_168_DATA_TRUST_NEXT_STAGE_PACKET.csv"
REPORT = READ_CENTER / "V20_168_DATA_TRUST_GATE_ONLY_OPERATOR_DECISION_CAPTURE_REPORT.md"

SELECTED_OPTION = "APPROVE_DATA_TRUST_GATE_ONLY_RESEARCH_POLICY_WITH_DIRECT_MAPPING_REQUIRED"
ALLOWED_V167_STATUSES = {
    "PARTIAL_PASS_V20_167_DATA_TRUST_GATE_ONLY_REVIEW_WITH_MAPPING_LIMITATIONS",
    "PASS_V20_167_DATA_TRUST_GATE_ONLY_OPERATOR_REVIEW_AWAITING_OPERATOR_INPUT",
}
PASS_STATUS = "PASS_V20_168_DATA_TRUST_GATE_ONLY_OPERATOR_DECISION_CAPTURE_READY_FOR_V20_169"
BLOCKED_STATUS = "BLOCKED_V20_168_DATA_TRUST_GATE_ONLY_OPERATOR_DECISION_CAPTURE"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_GATE_ONLY_OPERATOR_DECISION_CAPTURE"
NEXT_STAGE = "V20_169_DIRECT_TICKER_LEVEL_DATA_TRUST_MAPPING_REPAIR_OR_RESEARCH_CONTINUATION_GATE"

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
    "shadow_weight_expansion_allowed": "FALSE",
}
COMMON = {**SAFETY, "operator_decision_capture_created": "TRUE", "decision_scope": SCOPE, "audit_only": "TRUE"}

DECISION_FIELDS = [
    "selected_operator_option", "operator_decision_status",
    "data_trust_gate_only_research_policy_approved",
    "data_trust_scoring_weight_after", "data_trust_role_after",
    "data_trust_fail_unknown_exclusion_required",
    "repair_backlog_required_for_failed_or_unknown_rows",
    "direct_ticker_mapping_required_before_official_use",
    "direct_ticker_mapping_count", "inferred_from_artifact_mapping_count",
    "mapping_confidence_limitation_flag", "official_weight_change_allowed",
    "official_ranking_mutation_allowed", "formal_activation_allowed",
    "next_allowed_stage", "recommended_next_action", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_167_gate_consumed", "v20_167_status",
    "selected_operator_option", "operator_decision_status",
    "data_trust_gate_only_research_policy_approved",
    "data_trust_scoring_weight", "data_trust_role",
    "data_trust_fail_unknown_exclusion_required",
    "repair_backlog_required_for_failed_or_unknown_rows",
    "direct_ticker_mapping_required_before_official_use",
    "direct_ticker_mapping_count", "inferred_from_artifact_mapping_count",
    "mapping_confidence_limitation_flag", "official_weight_change_allowed",
    "official_ranking_mutation_allowed", "no_official_recommendation_created",
    "no_real_book_action_created", "no_trade_action_created",
    "no_broker_action_created", "no_performance_claim_created",
    "no_upstream_outputs_mutated", "blocking_reason", "final_status", *COMMON.keys(),
]
SAFETY_FIELDS = [
    "safety_check_id", "safety_check", "expected_value", "actual_value",
    "safety_passed", *COMMON.keys(),
]
DIRECT_MAPPING_FIELDS = [
    "requirement_id", "direct_ticker_mapping_required_before_official_use",
    "direct_ticker_mapping_count", "inferred_from_artifact_mapping_count",
    "mapping_confidence_limitation_flag",
    "inferred_mapping_allowed_for_research_only_continuation",
    "inferred_mapping_sufficient_for_official_use", "required_repair_action",
    "recommended_next_action", *COMMON.keys(),
]
NEXT_STAGE_FIELDS = [
    "next_stage_packet_id", "next_allowed_stage", "research_only_continuation_allowed",
    "official_weight_change_allowed", "official_ranking_mutation_allowed",
    "formal_activation_allowed", "direct_mapping_required_before_official_use",
    "data_trust_fail_unknown_exclusion_required",
    "repair_backlog_required_for_failed_or_unknown_rows",
    "recommended_next_action", *COMMON.keys(),
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


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
    return [V167_PACKET, V167_POLICY, V167_MAPPING, V167_OPTIONS, V167_GATE, V167_SAFETY]


def input_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in inputs() if path.exists()}


def build_decision(policy: dict[str, str], mapping: dict[str, str]) -> dict[str, str]:
    return {
        "selected_operator_option": SELECTED_OPTION,
        "operator_decision_status": "APPROVED_RESEARCH_ONLY_WITH_DIRECT_MAPPING_REQUIRED",
        "data_trust_gate_only_research_policy_approved": "TRUE",
        "data_trust_scoring_weight_after": "0.0000000000",
        "data_trust_role_after": DATA_TRUST_ROLE,
        "data_trust_fail_unknown_exclusion_required": "TRUE",
        "repair_backlog_required_for_failed_or_unknown_rows": "TRUE",
        "direct_ticker_mapping_required_before_official_use": "TRUE",
        "direct_ticker_mapping_count": mapping.get("direct_ticker_mapping_count", policy.get("direct_ticker_mapping_count", "0")),
        "inferred_from_artifact_mapping_count": mapping.get("inferred_from_artifact_mapping_count", policy.get("inferred_from_artifact_mapping_count", "0")),
        "mapping_confidence_limitation_flag": mapping.get("mapping_confidence_limitation_flag", policy.get("mapping_confidence_limitation_flag", "FALSE")),
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "formal_activation_allowed": "FALSE",
        "next_allowed_stage": NEXT_STAGE,
        "recommended_next_action": "CONTINUE_RESEARCH_ONLY_DATA_TRUST_GATE_POLICY_WITH_DIRECT_TICKER_MAPPING_REPAIR_REQUIRED_BEFORE_OFFICIAL_USE",
        **COMMON,
    }


def build_direct_mapping_packet(decision: dict[str, str]) -> dict[str, str]:
    return {
        "requirement_id": "V20_168_DATA_TRUST_DIRECT_MAPPING_REQUIREMENT_001",
        "direct_ticker_mapping_required_before_official_use": "TRUE",
        "direct_ticker_mapping_count": decision["direct_ticker_mapping_count"],
        "inferred_from_artifact_mapping_count": decision["inferred_from_artifact_mapping_count"],
        "mapping_confidence_limitation_flag": decision["mapping_confidence_limitation_flag"],
        "inferred_mapping_allowed_for_research_only_continuation": "TRUE",
        "inferred_mapping_sufficient_for_official_use": "FALSE",
        "required_repair_action": "BUILD_DIRECT_TICKER_LEVEL_DATA_TRUST_STATUS_MAPPING_BEFORE_ANY_OFFICIAL_USE",
        "recommended_next_action": "ROUTE_TO_DIRECT_MAPPING_REPAIR_OR_RESEARCH_CONTINUATION_GATE",
        **COMMON,
    }


def build_next_stage_packet(decision: dict[str, str]) -> dict[str, str]:
    return {
        "next_stage_packet_id": "V20_168_DATA_TRUST_NEXT_STAGE_PACKET_001",
        "next_allowed_stage": NEXT_STAGE,
        "research_only_continuation_allowed": "TRUE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "formal_activation_allowed": "FALSE",
        "direct_mapping_required_before_official_use": "TRUE",
        "data_trust_fail_unknown_exclusion_required": "TRUE",
        "repair_backlog_required_for_failed_or_unknown_rows": "TRUE",
        "recommended_next_action": decision["recommended_next_action"],
        **COMMON,
    }


def safety_rows(upstream_mutated: bool, prereq_ok: bool) -> list[dict[str, str]]:
    checks = [
        ("v20_167_prerequisites_met", "TRUE", tf(prereq_ok)),
        ("selected_operator_option", SELECTED_OPTION, SELECTED_OPTION),
        ("research_only", "TRUE", "TRUE"),
        ("data_trust_scoring_weight", "0.0000000000", "0.0000000000"),
        ("data_trust_role", DATA_TRUST_ROLE, DATA_TRUST_ROLE),
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
        ("upstream_outputs_mutated", "FALSE", tf(upstream_mutated)),
    ]
    return [{
        "safety_check_id": f"V20_168_SAFETY_{idx:03d}",
        "safety_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "safety_passed": tf(expected == actual),
        **COMMON,
    } for idx, (check, expected, actual) in enumerate(checks, start=1)]


def write_report(status: str, decision: dict[str, str] | None = None) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.168 DATA_TRUST Gate-Only Operator Decision Capture Report",
        "",
        f"- wrapper_status: {status}",
        f"- selected_operator_option: {SELECTED_OPTION}",
        "- research_only: TRUE",
        "- data_trust_scoring_weight_after: 0.0000000000",
        f"- data_trust_role_after: {DATA_TRUST_ROLE}",
        "- official_weight_change_allowed: FALSE",
        "- official_ranking_mutation_allowed: FALSE",
        "- formal_activation_allowed: FALSE",
        "- performance_claim_created: FALSE",
    ]
    if decision:
        lines.extend([
            f"- operator_decision_status: {decision['operator_decision_status']}",
            f"- direct_ticker_mapping_required_before_official_use: {decision['direct_ticker_mapping_required_before_official_use']}",
            f"- direct_ticker_mapping_count: {decision['direct_ticker_mapping_count']}",
            f"- inferred_from_artifact_mapping_count: {decision['inferred_from_artifact_mapping_count']}",
            f"- mapping_confidence_limitation_flag: {decision['mapping_confidence_limitation_flag']}",
            f"- next_allowed_stage: {decision['next_allowed_stage']}",
            "",
            "This approval is limited to research-only continuation. Direct ticker-level DATA_TRUST mapping remains required before any official use.",
        ])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_168_DATA_TRUST_GATE_ONLY_DECISION_GATE_001",
        "v20_167_gate_consumed": "FALSE",
        "v20_167_status": "",
        "selected_operator_option": SELECTED_OPTION,
        "operator_decision_status": "BLOCKED",
        "data_trust_gate_only_research_policy_approved": "FALSE",
        "data_trust_scoring_weight": "0.0000000000",
        "data_trust_role": DATA_TRUST_ROLE,
        "data_trust_fail_unknown_exclusion_required": "TRUE",
        "repair_backlog_required_for_failed_or_unknown_rows": "TRUE",
        "direct_ticker_mapping_required_before_official_use": "TRUE",
        "direct_ticker_mapping_count": "0",
        "inferred_from_artifact_mapping_count": "0",
        "mapping_confidence_limitation_flag": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "no_official_recommendation_created": "TRUE",
        "no_real_book_action_created": "TRUE",
        "no_trade_action_created": "TRUE",
        "no_broker_action_created": "TRUE",
        "no_performance_claim_created": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_DECISION, DECISION_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SAFETY, SAFETY_FIELDS, [])
    write_csv(OUT_DIRECT_MAPPING, DIRECT_MAPPING_FIELDS, [])
    write_csv(OUT_NEXT_STAGE, NEXT_STAGE_FIELDS, [])
    write_report(BLOCKED_STATUS)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    before = input_hashes()
    missing = [path for path in inputs() if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))

    packet_rows, _ = read_csv(V167_PACKET)
    policy_rows, _ = read_csv(V167_POLICY)
    mapping_rows, _ = read_csv(V167_MAPPING)
    option_rows, _ = read_csv(V167_OPTIONS)
    gate_rows, _ = read_csv(V167_GATE)
    safety_in_rows, _ = read_csv(V167_SAFETY)
    if not all([packet_rows, policy_rows, mapping_rows, option_rows, gate_rows, safety_in_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    policy = policy_rows[0]
    mapping = mapping_rows[0]
    gate = gate_rows[0]
    option_available = any(row.get("operator_option") == SELECTED_OPTION and row.get("option_available") == "TRUE" for row in option_rows)
    prereq_ok = all([
        gate.get("final_status") in ALLOWED_V167_STATUSES,
        option_available,
        policy.get("data_trust_scoring_weight_after") == "0.0000000000",
        policy.get("data_trust_role") == DATA_TRUST_ROLE,
        mapping.get("direct_ticker_mapping_required_before_official_use") == "TRUE",
        mapping.get("direct_ticker_mapping_count") == "0",
        mapping.get("inferred_from_artifact_mapping_count") == "40",
        mapping.get("mapping_confidence_limitation_flag") == "TRUE",
        gate.get("official_ranking_mutated") == "FALSE",
        gate.get("official_weight_change_created") == "FALSE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_167_REQUIREMENTS_NOT_MET")

    decision = build_decision(policy, mapping)
    direct_mapping = build_direct_mapping_packet(decision)
    next_stage = build_next_stage_packet(decision)
    upstream_mutated = before != input_hashes()
    safety = safety_rows(upstream_mutated, prereq_ok)
    safety_ok = all(row["safety_passed"] == "TRUE" for row in safety)
    if upstream_mutated or not safety_ok:
        return emit_blocked("SAFETY_OR_UPSTREAM_MUTATION_FAILURE")

    gate_out = {
        "gate_check_id": "V20_168_DATA_TRUST_GATE_ONLY_DECISION_GATE_001",
        "v20_167_gate_consumed": "TRUE",
        "v20_167_status": gate.get("final_status", ""),
        "selected_operator_option": SELECTED_OPTION,
        "operator_decision_status": decision["operator_decision_status"],
        "data_trust_gate_only_research_policy_approved": "TRUE",
        "data_trust_scoring_weight": "0.0000000000",
        "data_trust_role": DATA_TRUST_ROLE,
        "data_trust_fail_unknown_exclusion_required": "TRUE",
        "repair_backlog_required_for_failed_or_unknown_rows": "TRUE",
        "direct_ticker_mapping_required_before_official_use": "TRUE",
        "direct_ticker_mapping_count": decision["direct_ticker_mapping_count"],
        "inferred_from_artifact_mapping_count": decision["inferred_from_artifact_mapping_count"],
        "mapping_confidence_limitation_flag": decision["mapping_confidence_limitation_flag"],
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "no_official_recommendation_created": "TRUE",
        "no_real_book_action_created": "TRUE",
        "no_trade_action_created": "TRUE",
        "no_broker_action_created": "TRUE",
        "no_performance_claim_created": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "blocking_reason": "",
        "final_status": PASS_STATUS,
        **COMMON,
    }

    write_csv(OUT_DECISION, DECISION_FIELDS, [decision])
    write_csv(OUT_GATE, GATE_FIELDS, [gate_out])
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_DIRECT_MAPPING, DIRECT_MAPPING_FIELDS, [direct_mapping])
    write_csv(OUT_NEXT_STAGE, NEXT_STAGE_FIELDS, [next_stage])
    write_report(PASS_STATUS, decision)

    print(PASS_STATUS)
    print("V20_167_GATE_CONSUMED=TRUE")
    print(f"V20_167_STATUS={gate.get('final_status', '')}")
    print(f"SELECTED_OPERATOR_OPTION={SELECTED_OPTION}")
    print("OPERATOR_DECISION_STATUS=APPROVED_RESEARCH_ONLY_WITH_DIRECT_MAPPING_REQUIRED")
    print("DATA_TRUST_GATE_ONLY_RESEARCH_POLICY_APPROVED=TRUE")
    print("DATA_TRUST_SCORING_WEIGHT_AFTER=0.0000000000")
    print(f"DATA_TRUST_ROLE_AFTER={DATA_TRUST_ROLE}")
    print("DATA_TRUST_FAIL_UNKNOWN_EXCLUSION_REQUIRED=TRUE")
    print("REPAIR_BACKLOG_REQUIRED_FOR_FAILED_OR_UNKNOWN_ROWS=TRUE")
    print("DIRECT_TICKER_MAPPING_REQUIRED_BEFORE_OFFICIAL_USE=TRUE")
    print(f"DIRECT_TICKER_MAPPING_COUNT={decision['direct_ticker_mapping_count']}")
    print(f"INFERRED_FROM_ARTIFACT_MAPPING_COUNT={decision['inferred_from_artifact_mapping_count']}")
    print(f"MAPPING_CONFIDENCE_LIMITATION_FLAG={decision['mapping_confidence_limitation_flag']}")
    print("OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE")
    print("OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE")
    print("FORMAL_ACTIVATION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_ACTION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("PERFORMANCE_CLAIM_CREATED=FALSE")
    print("UPSTREAM_MUTATION_DETECTED=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
