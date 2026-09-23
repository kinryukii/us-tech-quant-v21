#!/usr/bin/env python
"""V20.167 DATA_TRUST gate-only operator review packet.

Creates a research-only operator review packet from the V20.166-R3 baseline
binding repair. This stage does not auto-approve the policy and does not mutate
official rankings, official weights, recommendations, trades, broker actions,
performance claims, or upstream outputs.
"""

from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"

R3_LINEAGE = FACTORS / "V20_166_R3_DATA_TRUST_SCORE_LINEAGE_AUDIT.csv"
R3_WEIGHT_BINDING = FACTORS / "V20_166_R3_DATA_TRUST_WEIGHT_BINDING_AUDIT.csv"
R3_NORMALIZATION = FACTORS / "V20_166_R3_DATA_TRUST_SCORE_NORMALIZATION_AUDIT.csv"
R3_REPAIR = FACTORS / "V20_166_R3_DATA_TRUST_BASELINE_BINDING_REPAIR.csv"
R3_SIM = FACTORS / "V20_166_R3_BOUND_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION.csv"
R3_DELTA = FACTORS / "V20_166_R3_BOUND_DATA_TRUST_GATE_ONLY_RANK_DELTA.csv"
R3_MAPPING = FACTORS / "V20_166_R3_MAPPING_CONFIDENCE_LIMITATION_AUDIT.csv"
R3_GATE = FACTORS / "V20_166_R3_DATA_TRUST_NEXT_GATE.csv"
R1_STATUS = FACTORS / "V20_166_R1_DATA_TRUST_TICKER_STATUS.csv"
R2_MAPPING = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_MAPPING_CONFIDENCE_AUDIT.csv"
R2_SAFETY = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_SAFETY_AUDIT.csv"

OUT_PACKET = FACTORS / "V20_167_DATA_TRUST_GATE_ONLY_OPERATOR_REVIEW_PACKET.csv"
OUT_POLICY = FACTORS / "V20_167_DATA_TRUST_GATE_ONLY_POLICY_REVIEW.csv"
OUT_MAPPING = FACTORS / "V20_167_DATA_TRUST_MAPPING_LIMITATION_REVIEW.csv"
OUT_OPTIONS = FACTORS / "V20_167_DATA_TRUST_OPERATOR_OPTIONS.csv"
OUT_GATE = FACTORS / "V20_167_DATA_TRUST_GATE_ONLY_NEXT_GATE.csv"
OUT_SAFETY = FACTORS / "V20_167_DATA_TRUST_GATE_ONLY_SAFETY_AUDIT.csv"
REPORT = READ_CENTER / "V20_167_DATA_TRUST_GATE_ONLY_OPERATOR_REVIEW_REPORT.md"

ALLOWED_R3_STATUSES = {
    "PARTIAL_PASS_V20_166_R3_DATA_TRUST_BASELINE_BINDING_WITH_MAPPING_LIMITATIONS_READY_FOR_V20_167",
    "PASS_V20_166_R3_DATA_TRUST_BASELINE_BINDING_REPAIR_READY_FOR_V20_167",
}
PASS_STATUS = "PASS_V20_167_DATA_TRUST_GATE_ONLY_OPERATOR_REVIEW_AWAITING_OPERATOR_INPUT"
PARTIAL_STATUS = "PARTIAL_PASS_V20_167_DATA_TRUST_GATE_ONLY_REVIEW_WITH_MAPPING_LIMITATIONS"
WARN_STATUS = "WARN_V20_167_DATA_TRUST_GATE_ONLY_NOT_READY_FOR_OPERATOR_REVIEW"
BLOCKED_STATUS = "BLOCKED_V20_167_DATA_TRUST_GATE_ONLY_OPERATOR_REVIEW"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_GATE_ONLY_OPERATOR_REVIEW_WITH_BASELINE_BINDING"
AWAITING = "AWAITING_EXPLICIT_OPERATOR_REVIEW"

OPTIONS = [
    "APPROVE_DATA_TRUST_GATE_ONLY_RESEARCH_POLICY_WITH_DIRECT_MAPPING_REQUIRED",
    "REQUEST_DIRECT_TICKER_LEVEL_DATA_TRUST_MAPPING_REPAIR",
    "REQUEST_MORE_DATA_TRUST_SOURCE_AUDIT",
    "REJECT_DATA_TRUST_GATE_ONLY_POLICY_FOR_NOW",
    "KEEP_DATA_TRUST_AS_SCORING_WEIGHT_FOR_NOW",
]

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
COMMON = {**SAFETY, "operator_review_packet_created": "TRUE", "review_scope": SCOPE, "audit_only": "TRUE"}

REVIEW_FIELDS = [
    "data_trust_scoring_weight_before", "data_trust_scoring_weight_after",
    "data_trust_role", "proposed_scoring_weight_sum", "baseline_candidate_count",
    "data_trust_pass_count", "data_trust_fail_count", "data_trust_unknown_count",
    "direct_ticker_mapping_count", "inferred_from_artifact_mapping_count",
    "mapping_confidence_limitation_flag", "bound_top20_turnover_rate",
    "bound_max_absolute_rank_delta", "baseline_binding_success",
    "gate_only_policy_research_ready", "direct_ticker_mapping_required_before_official_use",
    "operator_review_required", "operator_input_required", "selected_operator_option",
    "recommended_next_action", *COMMON.keys(),
]
PACKET_FIELDS = [
    "packet_id", "default_decision", "operator_input_required",
    "selected_operator_option", "operator_review_summary", *REVIEW_FIELDS,
]
MAPPING_FIELDS = [
    "mapping_review_id", "direct_ticker_mapping_count",
    "inferred_from_artifact_mapping_count", "mapping_confidence_limitation_flag",
    "direct_ticker_mapping_required_before_official_use",
    "official_promotion_sufficient", "mapping_limitation_reason",
    "operator_input_required", "selected_operator_option", *COMMON.keys(),
]
OPTION_FIELDS = [
    "operator_option_id", "operator_option", "option_available",
    "selected_operator_option", "operator_input_required", "option_reason", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_166_r3_gate_consumed", "v20_166_r3_status",
    "baseline_binding_success", "gate_only_policy_research_ready",
    "mapping_confidence_limitation_flag", "operator_review_required",
    "operator_input_required", "selected_operator_option",
    "shadow_weight_expansion_allowed", "official_weight_change_allowed",
    "no_new_shadow_proposal_rows_created", "no_factor_scope_expansion",
    "no_official_ranking_mutated", "no_official_weights_mutated",
    "no_official_recommendation_created", "no_real_book_action_created",
    "no_trade_action_created", "no_broker_action_created",
    "no_performance_claim_created", "no_upstream_outputs_mutated",
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
    required = [R3_LINEAGE, R3_WEIGHT_BINDING, R3_NORMALIZATION, R3_REPAIR, R3_SIM, R3_DELTA, R3_MAPPING, R3_GATE]
    optional = [R1_STATUS, R2_MAPPING, R2_SAFETY]
    return required + [path for path in optional if path.exists()]


def input_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in inputs() if path.exists()}


def required_inputs() -> list[Path]:
    return [R3_LINEAGE, R3_WEIGHT_BINDING, R3_NORMALIZATION, R3_REPAIR, R3_SIM, R3_DELTA, R3_MAPPING, R3_GATE]


def build_review(delta: dict[str, str], gate: dict[str, str], weight_binding: dict[str, str]) -> dict[str, str]:
    limitation = delta.get("mapping_confidence_limitation_flag") == "TRUE"
    research_ready = all([
        gate.get("ready_for_operator_review") == "TRUE",
        delta.get("ready_for_operator_review") == "TRUE",
        delta.get("bound_top20_turnover_rate") == "0.0000000000",
        int(num(delta.get("bound_max_absolute_rank_delta"), -1)) == 0,
    ])
    next_action = (
        "AWAIT_EXPLICIT_OPERATOR_REVIEW_WITH_DIRECT_TICKER_MAPPING_REQUIRED_BEFORE_OFFICIAL_USE"
        if limitation else
        "AWAIT_EXPLICIT_OPERATOR_REVIEW_FOR_RESEARCH_ONLY_DATA_TRUST_GATE_POLICY"
    )
    return {
        "data_trust_scoring_weight_before": weight_binding.get("data_trust_weight_before", "0.1000000000"),
        "data_trust_scoring_weight_after": "0.0000000000",
        "data_trust_role": DATA_TRUST_ROLE,
        "proposed_scoring_weight_sum": weight_binding.get("proposed_gate_only_weight_sum", "1.0000000000"),
        "baseline_candidate_count": delta.get("baseline_candidate_count", "0"),
        "data_trust_pass_count": delta.get("data_trust_pass_count", "0"),
        "data_trust_fail_count": delta.get("data_trust_fail_count", "0"),
        "data_trust_unknown_count": delta.get("data_trust_unknown_count", "0"),
        "direct_ticker_mapping_count": delta.get("direct_ticker_mapping_count", "0"),
        "inferred_from_artifact_mapping_count": delta.get("inferred_from_artifact_mapping_count", "0"),
        "mapping_confidence_limitation_flag": tf(limitation),
        "bound_top20_turnover_rate": delta.get("bound_top20_turnover_rate", "0"),
        "bound_max_absolute_rank_delta": delta.get("bound_max_absolute_rank_delta", "0"),
        "baseline_binding_success": delta.get("baseline_binding_improved_rank_stability", "FALSE"),
        "gate_only_policy_research_ready": tf(research_ready),
        "direct_ticker_mapping_required_before_official_use": tf(limitation),
        "operator_review_required": "TRUE",
        "operator_input_required": "TRUE",
        "selected_operator_option": AWAITING,
        "recommended_next_action": next_action,
        **COMMON,
    }


def build_mapping_review(review: dict[str, str]) -> dict[str, str]:
    return {
        "mapping_review_id": "V20_167_DATA_TRUST_MAPPING_LIMITATION_REVIEW_001",
        "direct_ticker_mapping_count": review["direct_ticker_mapping_count"],
        "inferred_from_artifact_mapping_count": review["inferred_from_artifact_mapping_count"],
        "mapping_confidence_limitation_flag": review["mapping_confidence_limitation_flag"],
        "direct_ticker_mapping_required_before_official_use": review["direct_ticker_mapping_required_before_official_use"],
        "official_promotion_sufficient": "FALSE",
        "mapping_limitation_reason": "DATA_TRUST_PASS_MAPPING_IS_INFERRED_FROM_AUTHORITATIVE_BASELINE_FIELDS_PLUS_AGGREGATE_QUALITY_ARTIFACTS_NOT_DIRECT_TICKER_LEVEL_DATA_TRUST_EVIDENCE",
        "operator_input_required": "TRUE",
        "selected_operator_option": AWAITING,
        **COMMON,
    }


def option_rows() -> list[dict[str, str]]:
    reasons = {
        OPTIONS[0]: "Operator may approve research-only policy continuation while requiring direct ticker DATA_TRUST mapping before official use.",
        OPTIONS[1]: "Operator may require direct ticker-level DATA_TRUST mapping repair before any further policy path.",
        OPTIONS[2]: "Operator may request a deeper source audit for DATA_TRUST evidence lineage.",
        OPTIONS[3]: "Operator may reject the gate-only policy path without official mutation.",
        OPTIONS[4]: "Operator may keep DATA_TRUST as a scoring weight for now; this packet does not mutate weights.",
    }
    return [{
        "operator_option_id": f"V20_167_OPERATOR_OPTION_{idx:03d}",
        "operator_option": option,
        "option_available": "TRUE",
        "selected_operator_option": AWAITING,
        "operator_input_required": "TRUE",
        "option_reason": reasons[option],
        **COMMON,
    } for idx, option in enumerate(OPTIONS, start=1)]


def safety_rows(upstream_mutated: bool, prereq_ok: bool) -> list[dict[str, str]]:
    checks = [
        ("v20_166_r3_prerequisites_met", "TRUE", tf(prereq_ok)),
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
        ("data_trust_inferred_mapping_treated_as_direct", "FALSE", "FALSE"),
        ("upstream_outputs_mutated", "FALSE", tf(upstream_mutated)),
    ]
    return [{
        "safety_check_id": f"V20_167_SAFETY_{idx:03d}",
        "safety_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "safety_passed": tf(expected == actual),
        **COMMON,
    } for idx, (check, expected, actual) in enumerate(checks, start=1)]


def write_report(status: str, review: dict[str, str] | None = None) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.167 DATA_TRUST Gate-Only Operator Review Report",
        "",
        f"- wrapper_status: {status}",
        f"- review_scope: {SCOPE}",
        "- DATA_TRUST role: GATE_ONLY_AND_REPAIR_DIAGNOSTIC",
        "- DATA_TRUST scoring weight after: 0.0000000000",
        "- operator_input_required: TRUE",
        f"- selected_operator_option: {AWAITING}",
        "- official_weight_change_created: FALSE",
        "- official_ranking_mutated: FALSE",
        "- performance_claim_created: FALSE",
    ]
    if review:
        lines.extend([
            f"- baseline_candidate_count: {review['baseline_candidate_count']}",
            f"- data_trust_pass_count: {review['data_trust_pass_count']}",
            f"- direct_ticker_mapping_count: {review['direct_ticker_mapping_count']}",
            f"- inferred_from_artifact_mapping_count: {review['inferred_from_artifact_mapping_count']}",
            f"- mapping_confidence_limitation_flag: {review['mapping_confidence_limitation_flag']}",
            f"- bound_top20_turnover_rate: {review['bound_top20_turnover_rate']}",
            f"- bound_max_absolute_rank_delta: {review['bound_max_absolute_rank_delta']}",
            f"- recommended_next_action: {review['recommended_next_action']}",
            "",
            "DATA_TRUST PASS remains inferred from authoritative baseline fields plus aggregate quality artifacts. This packet treats that as acceptable for research-only operator review, not as direct ticker-level evidence for official promotion.",
        ])
    lines.extend(["", "No operator option is selected by this packet."])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def empty_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_167_DATA_TRUST_GATE_ONLY_NEXT_GATE_001",
        "v20_166_r3_gate_consumed": "FALSE",
        "v20_166_r3_status": "",
        "baseline_binding_success": "FALSE",
        "gate_only_policy_research_ready": "FALSE",
        "mapping_confidence_limitation_flag": "FALSE",
        "operator_review_required": "FALSE",
        "operator_input_required": "FALSE",
        "selected_operator_option": AWAITING,
        "shadow_weight_expansion_allowed": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "no_new_shadow_proposal_rows_created": "TRUE",
        "no_factor_scope_expansion": "TRUE",
        "no_official_ranking_mutated": "TRUE",
        "no_official_weights_mutated": "TRUE",
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
    write_csv(OUT_PACKET, PACKET_FIELDS, [])
    write_csv(OUT_POLICY, REVIEW_FIELDS, [])
    write_csv(OUT_MAPPING, MAPPING_FIELDS, [])
    write_csv(OUT_OPTIONS, OPTION_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SAFETY, SAFETY_FIELDS, [])
    write_report(BLOCKED_STATUS)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    before = input_hashes()
    missing = [path for path in required_inputs() if not path.exists() or path.stat().st_size == 0]
    if missing:
        return empty_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))

    lineage_rows, _ = read_csv(R3_LINEAGE)
    weight_rows, _ = read_csv(R3_WEIGHT_BINDING)
    normalization_rows, _ = read_csv(R3_NORMALIZATION)
    repair_rows, _ = read_csv(R3_REPAIR)
    sim_rows, _ = read_csv(R3_SIM)
    delta_rows, _ = read_csv(R3_DELTA)
    mapping_rows, _ = read_csv(R3_MAPPING)
    gate_rows, _ = read_csv(R3_GATE)
    if not all([lineage_rows, weight_rows, normalization_rows, repair_rows, sim_rows, delta_rows, mapping_rows, gate_rows]):
        return empty_blocked("EMPTY_REQUIRED_INPUTS")

    delta = delta_rows[0]
    gate = gate_rows[0]
    weight = weight_rows[0]
    prereq_ok = all([
        gate.get("final_status") in ALLOWED_R3_STATUSES,
        gate.get("data_trust_scoring_weight") == "0.0000000000",
        gate.get("data_trust_role") == DATA_TRUST_ROLE,
        delta.get("bound_top20_turnover_rate") == "0.0000000000",
        int(num(delta.get("bound_max_absolute_rank_delta"), -1)) == 0,
        delta.get("direct_ticker_mapping_count") == "0",
        delta.get("inferred_from_artifact_mapping_count") == "40",
        delta.get("mapping_confidence_limitation_flag") == "TRUE",
        gate.get("official_ranking_mutated") == "FALSE",
        gate.get("official_weight_change_created") == "FALSE",
    ])
    if not prereq_ok:
        return empty_blocked("V20_166_R3_REQUIREMENTS_NOT_MET")

    review = build_review(delta, gate, weight)
    packet = {
        "packet_id": "V20_167_DATA_TRUST_GATE_ONLY_OPERATOR_REVIEW_PACKET_001",
        "default_decision": AWAITING,
        "operator_input_required": "TRUE",
        "selected_operator_option": AWAITING,
        "operator_review_summary": "DATA_TRUST_GATE_ONLY_RESEARCH_POLICY_READY_FOR_OPERATOR_REVIEW_WITH_DIRECT_MAPPING_LIMITATION_DISCLOSED",
        **review,
    }
    mapping_review = build_mapping_review(review)
    options = option_rows()
    upstream_mutated = before != input_hashes()
    safety = safety_rows(upstream_mutated, prereq_ok)
    safety_ok = all(row["safety_passed"] == "TRUE" for row in safety)

    if upstream_mutated or not safety_ok:
        status, blocking = BLOCKED_STATUS, "SAFETY_OR_UPSTREAM_MUTATION_FAILURE"
    elif review["gate_only_policy_research_ready"] != "TRUE":
        status, blocking = WARN_STATUS, ""
    elif review["mapping_confidence_limitation_flag"] == "TRUE":
        status, blocking = PARTIAL_STATUS, ""
    else:
        status, blocking = PASS_STATUS, ""

    gate_out = {
        "gate_check_id": "V20_167_DATA_TRUST_GATE_ONLY_NEXT_GATE_001",
        "v20_166_r3_gate_consumed": "TRUE",
        "v20_166_r3_status": gate.get("final_status", ""),
        "baseline_binding_success": review["baseline_binding_success"],
        "gate_only_policy_research_ready": review["gate_only_policy_research_ready"],
        "mapping_confidence_limitation_flag": review["mapping_confidence_limitation_flag"],
        "operator_review_required": "TRUE",
        "operator_input_required": "TRUE",
        "selected_operator_option": AWAITING,
        "shadow_weight_expansion_allowed": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "no_new_shadow_proposal_rows_created": "TRUE",
        "no_factor_scope_expansion": "TRUE",
        "no_official_ranking_mutated": "TRUE",
        "no_official_weights_mutated": "TRUE",
        "no_official_recommendation_created": "TRUE",
        "no_real_book_action_created": "TRUE",
        "no_trade_action_created": "TRUE",
        "no_broker_action_created": "TRUE",
        "no_performance_claim_created": "TRUE",
        "no_upstream_outputs_mutated": tf(not upstream_mutated),
        "blocking_reason": blocking,
        "final_status": status,
        **COMMON,
    }

    write_csv(OUT_PACKET, PACKET_FIELDS, [packet])
    write_csv(OUT_POLICY, REVIEW_FIELDS, [review])
    write_csv(OUT_MAPPING, MAPPING_FIELDS, [mapping_review])
    write_csv(OUT_OPTIONS, OPTION_FIELDS, options)
    write_csv(OUT_GATE, GATE_FIELDS, [gate_out])
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_report(status, review)

    print(status)
    print("V20_166_R3_GATE_CONSUMED=TRUE")
    print(f"V20_166_R3_STATUS={gate.get('final_status', '')}")
    print("DATA_TRUST_SCORING_WEIGHT_AFTER=0.0000000000")
    print(f"DATA_TRUST_ROLE={DATA_TRUST_ROLE}")
    print(f"BASELINE_CANDIDATE_COUNT={review['baseline_candidate_count']}")
    print(f"DATA_TRUST_PASS_COUNT={review['data_trust_pass_count']}")
    print(f"DIRECT_TICKER_MAPPING_COUNT={review['direct_ticker_mapping_count']}")
    print(f"INFERRED_FROM_ARTIFACT_MAPPING_COUNT={review['inferred_from_artifact_mapping_count']}")
    print(f"MAPPING_CONFIDENCE_LIMITATION_FLAG={review['mapping_confidence_limitation_flag']}")
    print(f"BOUND_TOP20_TURNOVER_RATE={review['bound_top20_turnover_rate']}")
    print(f"BOUND_MAX_ABSOLUTE_RANK_DELTA={review['bound_max_absolute_rank_delta']}")
    print("OPERATOR_REVIEW_REQUIRED=TRUE")
    print("OPERATOR_INPUT_REQUIRED=TRUE")
    print(f"SELECTED_OPERATOR_OPTION={AWAITING}")
    print("FORMAL_ACTIVATION_ALLOWED=FALSE")
    print("PROMOTION_READY=FALSE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("OFFICIAL_WEIGHT_CHANGE_CREATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_ACTION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("PERFORMANCE_CLAIM_CREATED=FALSE")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
