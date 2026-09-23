#!/usr/bin/env python
"""V20.159 bound reduced shadow simulation operator review.

Builds a research-only operator review packet for the V20.158-R2 bound reduced
shadow ranking simulation. This stage does not auto-select an operator option
and does not mutate official rankings, weights, recommendations, trades,
broker actions, performance claims, or upstream outputs.
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

IN_REPAIR = FACTORS / "V20_158_R2_AUTHORITATIVE_BASELINE_SCORE_BINDING_REPAIR.csv"
IN_SIM = FACTORS / "V20_158_R2_BOUND_REDUCED_SHADOW_RANKING_SIMULATION.csv"
IN_DELTA = FACTORS / "V20_158_R2_BOUND_SHADOW_VS_BASELINE_RANK_DELTA.csv"
IN_BINDING = FACTORS / "V20_158_R2_BASELINE_BINDING_AUDIT.csv"
IN_ADJUST = FACTORS / "V20_158_R2_SCORE_ADJUSTMENT_AUDIT.csv"
IN_GATE = FACTORS / "V20_158_R2_RANK_IMPACT_RETEST_GATE.csv"

OUT_PACKET = FACTORS / "V20_159_BOUND_SHADOW_OPERATOR_REVIEW_PACKET.csv"
OUT_REVIEW = FACTORS / "V20_159_BOUND_SHADOW_STABILITY_REVIEW.csv"
OUT_OPTIONS = FACTORS / "V20_159_BOUND_SHADOW_OPERATOR_OPTIONS.csv"
OUT_GATE = FACTORS / "V20_159_BOUND_SHADOW_NEXT_GATE.csv"
OUT_SAFETY = FACTORS / "V20_159_BOUND_SHADOW_SAFETY_AUDIT.csv"
REPORT = READ_CENTER / "V20_159_BOUND_REDUCED_SHADOW_SIMULATION_OPERATOR_REVIEW_REPORT.md"

REQUIRED_R2_STATUS = "PASS_V20_158_R2_AUTHORITATIVE_BASELINE_BINDING_REPAIR_READY_FOR_V20_159"
PASS_STATUS = "PASS_V20_159_BOUND_SHADOW_OPERATOR_REVIEW_PACKET_AWAITING_OPERATOR_INPUT"
PARTIAL_STATUS = "PARTIAL_PASS_V20_159_BOUND_SHADOW_REVIEW_REQUIRES_MORE_FORWARD_OUTCOMES"
WARN_STATUS = "WARN_V20_159_BOUND_SHADOW_STILL_TOO_UNSTABLE_FOR_OPERATOR_APPROVAL"
BLOCKED_STATUS = "BLOCKED_V20_159_BOUND_SHADOW_OPERATOR_REVIEW"
SCOPE = "RESEARCH_ONLY_LIMITED_CONSERVATIVE_BOUND_TO_AUTHORITATIVE_BASELINE"

SAFETY_FIELDS = [
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
    "official_weight_change_created",
    "bound_reduced_shadow_ranking_simulation_created",
    "shadow_review_scope",
    "shadow_weight_expansion_allowed",
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
    "bound_reduced_shadow_ranking_simulation_created": "TRUE",
    "shadow_review_scope": SCOPE,
    "shadow_weight_expansion_allowed": "FALSE",
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
    "operator_review_packet_only": "TRUE",
    "audit_only": "TRUE",
}

REVIEW_FIELDS = [
    "baseline_candidate_count",
    "bound_shadow_candidate_count",
    "bound_top20_turnover_rate",
    "bound_max_absolute_rank_delta",
    "bound_average_absolute_rank_delta",
    "binding_repair_improved_rank_stability",
    "remaining_rank_impact_severity",
    "prior_unbound_top20_turnover_rate_if_available",
    "prior_unbound_average_absolute_rank_delta_if_available",
    "stability_review_result",
    "operator_review_required",
    "continued_bound_shadow_research_allowed",
    "shadow_weight_expansion_allowed",
    "official_weight_change_allowed",
    "required_next_action",
    *COMMON.keys(),
]
PACKET_FIELDS = [
    "packet_id",
    "operator_input_required",
    "selected_operator_option",
    "default_decision",
    "stability_review_result",
    "required_next_action",
    "review_summary",
    *REVIEW_FIELDS,
]
OPTION_FIELDS = [
    "operator_option_id",
    "operator_option",
    "option_available",
    "selected_operator_option",
    "operator_input_required",
    "option_reason",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id",
    "v20_158_r2_gate_consumed",
    "v20_158_r2_status",
    "v20_159_allowed_from_r2",
    "binding_repair_improved_rank_stability",
    "official_ranking_mutated",
    "official_weight_change_created",
    "performance_claim_created",
    "operator_input_required",
    "selected_operator_option",
    "continued_bound_shadow_research_allowed",
    "shadow_weight_expansion_allowed",
    "official_weight_change_allowed",
    "required_next_action",
    "no_official_ranking_mutated",
    "no_official_weights_mutated",
    "no_official_recommendation_created",
    "no_real_book_action_created",
    "no_trade_action_created",
    "no_broker_action_created",
    "no_performance_claim_created",
    "no_outcomes_fabricated",
    "no_benchmarks_fabricated",
    "no_upstream_outputs_mutated",
    "blocking_reason",
    "final_status",
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


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def truthy(value: object) -> bool:
    return clean(value).upper() == "TRUE"


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
    return [IN_REPAIR, IN_SIM, IN_DELTA, IN_BINDING, IN_ADJUST, IN_GATE]


def input_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in inputs() if path.exists()}


def build_review(summary: dict[str, str]) -> dict[str, str]:
    severity = summary.get("remaining_rank_impact_severity", "")
    improved = truthy(summary.get("binding_repair_improved_rank_stability"))
    turnover = num(summary.get("bound_top20_turnover_rate"))
    avg_delta = num(summary.get("bound_average_absolute_rank_delta"))
    max_delta = num(summary.get("bound_max_absolute_rank_delta"))
    if severity == "EXTREME" or turnover >= 0.30 or max_delta >= 25:
        result = "STILL_TOO_UNSTABLE_FOR_OPERATOR_APPROVAL"
        next_action = "REQUEST_SCORE_ADJUSTMENT_CAP_REPAIR"
        continued = False
    elif severity == "HIGH" or avg_delta >= 8:
        result = "REQUIRES_MORE_FORWARD_OUTCOMES_BEFORE_EXPANSION"
        next_action = "REQUEST_MORE_FORWARD_OUTCOMES_BEFORE_EXPANSION"
        continued = True
    elif severity == "ELEVATED":
        result = "ACCEPTABLE_FOR_OPERATOR_REVIEW_WITH_STABILITY_OBSERVATION"
        next_action = "REQUEST_ADDITIONAL_STABILITY_OBSERVATION_RUNS"
        continued = True
    else:
        result = "ACCEPTABLE_FOR_OPERATOR_REVIEW"
        next_action = "APPROVE_CONTINUED_BOUND_SHADOW_RESEARCH_ONLY"
        continued = True
    if not improved:
        result = "REQUIRES_MORE_FORWARD_OUTCOMES_BEFORE_EXPANSION"
        next_action = "REQUEST_MORE_FORWARD_OUTCOMES_BEFORE_EXPANSION"
    return {
        "baseline_candidate_count": summary.get("baseline_candidate_count", "0"),
        "bound_shadow_candidate_count": summary.get("bound_shadow_candidate_count", "0"),
        "bound_top20_turnover_rate": summary.get("bound_top20_turnover_rate", "0"),
        "bound_max_absolute_rank_delta": summary.get("bound_max_absolute_rank_delta", "0"),
        "bound_average_absolute_rank_delta": summary.get("bound_average_absolute_rank_delta", "0"),
        "binding_repair_improved_rank_stability": summary.get("binding_repair_improved_rank_stability", "FALSE"),
        "remaining_rank_impact_severity": severity,
        "prior_unbound_top20_turnover_rate_if_available": summary.get("prior_unbound_top20_turnover_rate_if_available", ""),
        "prior_unbound_average_absolute_rank_delta_if_available": summary.get("prior_unbound_average_absolute_rank_delta_if_available", ""),
        "stability_review_result": result,
        "operator_review_required": "TRUE",
        "continued_bound_shadow_research_allowed": tf(continued),
        "shadow_weight_expansion_allowed": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "required_next_action": next_action,
        **COMMON,
    }


def operator_options() -> list[dict[str, str]]:
    options = [
        ("APPROVE_CONTINUED_BOUND_SHADOW_RESEARCH_ONLY", "Continue bound shadow research without expansion or official changes."),
        ("REQUEST_MORE_FORWARD_OUTCOMES_BEFORE_EXPANSION", "Wait for additional realized outcomes before any scope expansion."),
        ("REQUEST_ADDITIONAL_STABILITY_OBSERVATION_RUNS", "Repeat bounded simulation observation before expansion decisions."),
        ("REQUEST_SCORE_ADJUSTMENT_CAP_REPAIR", "Reduce or cap score adjustments before another operator packet."),
        ("REJECT_SHADOW_DYNAMIC_WEIGHT_PATH_FOR_NOW", "Stop this shadow dynamic weighting path for now."),
    ]
    return [{
        "operator_option_id": f"V20_159_OPERATOR_OPTION_{index:03d}",
        "operator_option": option,
        "option_available": "TRUE",
        "selected_operator_option": "AWAITING_EXPLICIT_OPERATOR_REVIEW",
        "operator_input_required": "TRUE",
        "option_reason": reason,
        **COMMON,
    } for index, (option, reason) in enumerate(options, start=1)]


def safety_audit_rows(upstream_mutated: bool, gate_ok: bool) -> list[dict[str, str]]:
    checks = [
        ("formal_activation_allowed", "FALSE", "FALSE"),
        ("promotion_ready", "FALSE", "FALSE"),
        ("official_recommendation_created", "FALSE", "FALSE"),
        ("official_ranking_mutated", "FALSE", "FALSE"),
        ("official_weight_change_created", "FALSE", "FALSE"),
        ("bound_reduced_shadow_ranking_simulation_created", "TRUE", "TRUE"),
        ("shadow_review_scope", SCOPE, SCOPE),
        ("shadow_weight_expansion_allowed", "FALSE", "FALSE"),
        ("weight_mutated", "FALSE", "FALSE"),
        ("real_book_action_created", "FALSE", "FALSE"),
        ("trade_action_created", "FALSE", "FALSE"),
        ("broker_execution_supported", "FALSE", "FALSE"),
        ("performance_claim_created", "FALSE", "FALSE"),
        ("upstream_outputs_mutated", "FALSE", tf(upstream_mutated)),
        ("v20_158_r2_gate_requirements_met", "TRUE", tf(gate_ok)),
    ]
    return [{
        "safety_check_id": f"V20_159_SAFETY_{index:03d}",
        "safety_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "safety_passed": tf(expected == actual),
        **COMMON,
    } for index, (check, expected, actual) in enumerate(checks, start=1)]


def safety_issue_count(groups: list[list[dict[str, str]]]) -> int:
    count = 0
    for rows in groups:
        for row in rows:
            for field in SAFETY_FIELDS:
                if field == "bound_reduced_shadow_ranking_simulation_created":
                    if row.get(field) != "TRUE":
                        count += 1
                elif field == "shadow_review_scope":
                    if row.get(field) != SCOPE:
                        count += 1
                elif field == "shadow_weight_expansion_allowed":
                    if row.get(field) != "FALSE":
                        count += 1
                elif truthy(row.get(field)):
                    count += 1
    return count


def write_report(status: str, review: dict[str, str] | None = None) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.159 Bound Reduced Shadow Simulation Operator Review Report",
        "",
        f"- wrapper_status: {status}",
        f"- shadow_review_scope: {SCOPE}",
        "- operator_input_required: TRUE",
        "- selected_operator_option: AWAITING_EXPLICIT_OPERATOR_REVIEW",
        "- official_ranking_mutated: FALSE",
        "- official_weight_change_created: FALSE",
        "- performance_claim_created: FALSE",
    ]
    if review:
        lines.extend([
            f"- remaining_rank_impact_severity: {review['remaining_rank_impact_severity']}",
            f"- stability_review_result: {review['stability_review_result']}",
            f"- required_next_action: {review['required_next_action']}",
        ])
    lines.extend(["", "This packet awaits explicit operator review and does not auto-select an option."])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_159_BOUND_SHADOW_NEXT_GATE_001",
        "v20_158_r2_gate_consumed": "FALSE",
        "v20_158_r2_status": "",
        "v20_159_allowed_from_r2": "FALSE",
        "binding_repair_improved_rank_stability": "FALSE",
        "official_ranking_mutated": "FALSE",
        "official_weight_change_created": "FALSE",
        "performance_claim_created": "FALSE",
        "operator_input_required": "TRUE",
        "selected_operator_option": "AWAITING_EXPLICIT_OPERATOR_REVIEW",
        "continued_bound_shadow_research_allowed": "FALSE",
        "shadow_weight_expansion_allowed": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "required_next_action": "REJECT_SHADOW_DYNAMIC_WEIGHT_PATH_FOR_NOW",
        "no_official_ranking_mutated": "TRUE",
        "no_official_weights_mutated": "TRUE",
        "no_official_recommendation_created": "TRUE",
        "no_real_book_action_created": "TRUE",
        "no_trade_action_created": "TRUE",
        "no_broker_action_created": "TRUE",
        "no_performance_claim_created": "TRUE",
        "no_outcomes_fabricated": "TRUE",
        "no_benchmarks_fabricated": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_PACKET, PACKET_FIELDS, [])
    write_csv(OUT_REVIEW, REVIEW_FIELDS, [])
    write_csv(OUT_OPTIONS, OPTION_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SAFETY, SAFETY_AUDIT_FIELDS, [])
    write_report(BLOCKED_STATUS)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    before = input_hashes()
    missing = [path for path in inputs() if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_V20_158_R2_OUTPUTS:" + ";".join(rel(path) for path in missing))
    repair_rows, _ = read_csv(IN_REPAIR)
    sim_rows, _ = read_csv(IN_SIM)
    summary_rows, _ = read_csv(IN_DELTA)
    gate_rows, _ = read_csv(IN_GATE)
    if not all([repair_rows, sim_rows, summary_rows, gate_rows]):
        return emit_blocked("EMPTY_REQUIRED_V20_158_R2_OUTPUTS")
    gate_in = gate_rows[0]
    r2_status = gate_in.get("final_status", "")
    gate_ok = all([
        r2_status == REQUIRED_R2_STATUS,
        gate_in.get("v20_159_allowed") == "TRUE",
        gate_in.get("binding_repair_improved_rank_stability") == "TRUE",
        gate_in.get("official_ranking_mutated") == "FALSE",
        gate_in.get("official_weight_change_created") == "FALSE",
        gate_in.get("performance_claim_created") == "FALSE",
    ])
    if not gate_ok:
        return emit_blocked("V20_158_R2_GATE_REQUIREMENTS_NOT_MET")

    review = build_review(summary_rows[0])
    packet = {
        "packet_id": "V20_159_BOUND_SHADOW_OPERATOR_REVIEW_PACKET_001",
        "operator_input_required": "TRUE",
        "selected_operator_option": "AWAITING_EXPLICIT_OPERATOR_REVIEW",
        "default_decision": "DO_NOT_AUTO_SELECT_OPERATOR_OPTION",
        "stability_review_result": review["stability_review_result"],
        "required_next_action": review["required_next_action"],
        "review_summary": "BOUND_REDUCED_SHADOW_SIMULATION_READY_FOR_EXPLICIT_OPERATOR_REVIEW",
        **review,
    }
    options = operator_options()
    upstream_mutated = before != input_hashes()
    safety_rows = safety_audit_rows(upstream_mutated, gate_ok)
    safety_count = safety_issue_count([[review], [packet], options, safety_rows])

    severity = review["remaining_rank_impact_severity"]
    if upstream_mutated or safety_count:
        status = BLOCKED_STATUS
        blocking = "SAFETY_OR_UPSTREAM_MUTATION_FAILURE"
    elif severity == "EXTREME":
        status = WARN_STATUS
        blocking = ""
    elif severity == "HIGH":
        status = PARTIAL_STATUS
        blocking = ""
    else:
        status = PASS_STATUS
        blocking = ""
    gate = {
        "gate_check_id": "V20_159_BOUND_SHADOW_NEXT_GATE_001",
        "v20_158_r2_gate_consumed": "TRUE",
        "v20_158_r2_status": r2_status,
        "v20_159_allowed_from_r2": "TRUE",
        "binding_repair_improved_rank_stability": review["binding_repair_improved_rank_stability"],
        "official_ranking_mutated": "FALSE",
        "official_weight_change_created": "FALSE",
        "performance_claim_created": "FALSE",
        "operator_input_required": "TRUE",
        "selected_operator_option": "AWAITING_EXPLICIT_OPERATOR_REVIEW",
        "continued_bound_shadow_research_allowed": review["continued_bound_shadow_research_allowed"],
        "shadow_weight_expansion_allowed": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "required_next_action": review["required_next_action"],
        "no_official_ranking_mutated": "TRUE",
        "no_official_weights_mutated": "TRUE",
        "no_official_recommendation_created": "TRUE",
        "no_real_book_action_created": "TRUE",
        "no_trade_action_created": "TRUE",
        "no_broker_action_created": "TRUE",
        "no_performance_claim_created": "TRUE",
        "no_outcomes_fabricated": "TRUE",
        "no_benchmarks_fabricated": "TRUE",
        "no_upstream_outputs_mutated": tf(not upstream_mutated),
        "blocking_reason": blocking,
        "final_status": status,
        **COMMON,
    }
    write_csv(OUT_PACKET, PACKET_FIELDS, [packet])
    write_csv(OUT_REVIEW, REVIEW_FIELDS, [review])
    write_csv(OUT_OPTIONS, OPTION_FIELDS, options)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SAFETY, SAFETY_AUDIT_FIELDS, safety_rows)
    write_report(status, review)

    print(status)
    print("V20_158_R2_GATE_CONSUMED=TRUE")
    print("V20_159_ALLOWED_FROM_R2=TRUE")
    print(f"BINDING_REPAIR_IMPROVED_RANK_STABILITY={review['binding_repair_improved_rank_stability']}")
    print(f"REMAINING_RANK_IMPACT_SEVERITY={severity}")
    print(f"OPERATOR_INPUT_REQUIRED={packet['operator_input_required']}")
    print(f"SELECTED_OPERATOR_OPTION={packet['selected_operator_option']}")
    print(f"CONTINUED_BOUND_SHADOW_RESEARCH_ALLOWED={review['continued_bound_shadow_research_allowed']}")
    print("SHADOW_WEIGHT_EXPANSION_ALLOWED=FALSE")
    print("OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE")
    print(f"REQUIRED_NEXT_ACTION={review['required_next_action']}")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("OFFICIAL_WEIGHTS_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_ACTION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_ACTION_CREATED=FALSE")
    print("PERFORMANCE_CLAIM_CREATED=FALSE")
    print("OUTCOMES_FABRICATED=0")
    print("BENCHMARKS_FABRICATED=0")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    print(f"SAFETY_TRUE_COUNT={safety_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
