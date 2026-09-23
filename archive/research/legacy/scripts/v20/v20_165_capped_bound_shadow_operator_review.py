#!/usr/bin/env python
"""V20.165 capped bound shadow operator review packet.

Builds a research-only operator review packet from V20.164 capped stability
retest outputs. This stage does not auto-select an operator option and does
not mutate official rankings, weights, recommendations, trades, broker actions,
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

V164_RETEST = FACTORS / "V20_164_CAPPED_BOUND_SHADOW_STABILITY_RETEST.csv"
V164_SUMMARY = FACTORS / "V20_164_CAPPED_BOUND_SHADOW_STABILITY_SUMMARY.csv"
V164_GUARDRAIL = FACTORS / "V20_164_CAPPED_BOUND_SHADOW_GUARDRAIL_AUDIT.csv"
V164_OUTLIER = FACTORS / "V20_164_CAPPED_BOUND_SHADOW_OUTLIER_RETEST_AUDIT.csv"
V164_GATE = FACTORS / "V20_164_CAPPED_BOUND_SHADOW_NEXT_GATE.csv"
V164_SAFETY = FACTORS / "V20_164_CAPPED_BOUND_SHADOW_SAFETY_AUDIT.csv"

OUT_PACKET = FACTORS / "V20_165_CAPPED_BOUND_SHADOW_OPERATOR_REVIEW_PACKET.csv"
OUT_REVIEW = FACTORS / "V20_165_CAPPED_BOUND_SHADOW_STABILITY_REVIEW.csv"
OUT_OPTIONS = FACTORS / "V20_165_CAPPED_BOUND_SHADOW_OPERATOR_OPTIONS.csv"
OUT_GATE = FACTORS / "V20_165_CAPPED_BOUND_SHADOW_NEXT_GATE.csv"
OUT_SAFETY = FACTORS / "V20_165_CAPPED_BOUND_SHADOW_SAFETY_AUDIT.csv"
REPORT = READ_CENTER / "V20_165_CAPPED_BOUND_SHADOW_OPERATOR_REVIEW_REPORT.md"

REQUIRED_V164_STATUS = "PASS_V20_164_CAPPED_BOUND_SHADOW_STABILITY_RETEST_READY_FOR_V20_165"
PASS_STATUS = "PASS_V20_165_CAPPED_BOUND_SHADOW_OPERATOR_REVIEW_AWAITING_OPERATOR_INPUT"
PARTIAL_STATUS = "PARTIAL_PASS_V20_165_CAPPED_BOUND_SHADOW_REVIEW_REQUIRES_MORE_FORWARD_OUTCOMES"
WARN_STATUS = "WARN_V20_165_CAPPED_BOUND_SHADOW_NOT_READY_FOR_OPERATOR_REVIEW"
BLOCKED_STATUS = "BLOCKED_V20_165_CAPPED_BOUND_SHADOW_OPERATOR_REVIEW"
SCOPE = "RESEARCH_ONLY_LIMITED_CONSERVATIVE_BOUND_TO_AUTHORITATIVE_BASELINE_WITH_CAPS"
AWAITING = "AWAITING_EXPLICIT_OPERATOR_REVIEW"

OPTIONS = [
    "APPROVE_CONTINUED_CAPPED_BOUND_SHADOW_RESEARCH_ONLY",
    "REQUEST_MORE_FORWARD_OUTCOMES_BEFORE_ANY_EXPANSION",
    "REQUEST_MORE_STABILITY_RETESTS",
    "REQUEST_SCORE_CAP_PARAMETER_REVIEW",
    "REJECT_CAPPED_SHADOW_DYNAMIC_WEIGHT_PATH_FOR_NOW",
]

SAFETY = {
    "formal_activation_allowed": "FALSE",
    "promotion_ready": "FALSE",
    "official_recommendation_created": "FALSE",
    "official_ranking_mutated": "FALSE",
    "official_weight_change_created": "FALSE",
    "capped_bound_shadow_operator_review_created": "TRUE",
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
    "operator_review_packet_only": "TRUE",
    "capped_shadow_only": "TRUE",
    "audit_only": "TRUE",
}

REVIEW_FIELDS = [
    "retest_run_count",
    "stability_pass_count",
    "stability_warn_count",
    "stability_fail_count",
    "max_capped_top20_turnover_rate",
    "max_capped_rank_delta",
    "outlier_ticker_count_max",
    "factor_impact_concentration_max",
    "all_capped_guardrails_passed",
    "stable_enough_for_continued_capped_shadow_research",
    "stable_enough_for_shadow_expansion",
    "stable_enough_for_official_weight_change",
    "operator_review_required",
    "operator_input_required",
    "selected_operator_option",
    "recommended_next_action",
    *COMMON.keys(),
]
PACKET_FIELDS = [
    "packet_id",
    "operator_input_required",
    "selected_operator_option",
    "default_decision",
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
    "v20_164_gate_consumed",
    "v20_164_status",
    "all_capped_guardrails_passed",
    "v20_165_operator_review_allowed",
    "operator_review_required",
    "operator_input_required",
    "selected_operator_option",
    "shadow_weight_expansion_allowed",
    "official_weight_change_allowed",
    "no_new_shadow_proposal_rows_created",
    "no_factor_scope_expansion",
    "no_official_ranking_mutated",
    "no_official_weights_mutated",
    "no_official_recommendation_created",
    "no_real_book_action_created",
    "no_trade_action_created",
    "no_broker_action_created",
    "no_outcomes_fabricated",
    "no_benchmarks_fabricated",
    "no_performance_claim_created",
    "no_upstream_outputs_mutated",
    "blocking_reason",
    "final_status",
    *COMMON.keys(),
]
SAFETY_FIELDS = [
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
    return [V164_RETEST, V164_SUMMARY, V164_GUARDRAIL, V164_OUTLIER, V164_GATE, V164_SAFETY]


def input_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in inputs() if path.exists()}


def build_review(summary: dict[str, str], gate: dict[str, str]) -> dict[str, str]:
    if gate.get("all_capped_guardrails_passed") == "TRUE":
        next_action = "AWAIT_OPERATOR_DECISION_FOR_CONTINUED_CAPPED_BOUND_SHADOW_RESEARCH_ONLY"
    elif num(summary.get("max_capped_top20_turnover_rate")) > 0 or summary.get("outlier_ticker_count_max") != "0":
        next_action = "REQUEST_MORE_STABILITY_RETESTS"
    else:
        next_action = "REQUEST_MORE_FORWARD_OUTCOMES_BEFORE_ANY_EXPANSION"
    return {
        "retest_run_count": summary.get("retest_run_count", "0"),
        "stability_pass_count": summary.get("stability_pass_count", "0"),
        "stability_warn_count": summary.get("stability_warn_count", "0"),
        "stability_fail_count": summary.get("stability_fail_count", "0"),
        "max_capped_top20_turnover_rate": summary.get("max_capped_top20_turnover_rate", "0"),
        "max_capped_rank_delta": summary.get("max_capped_rank_delta", "0"),
        "outlier_ticker_count_max": summary.get("outlier_ticker_count_max", "0"),
        "factor_impact_concentration_max": summary.get("factor_impact_concentration_max", "0"),
        "all_capped_guardrails_passed": gate.get("all_capped_guardrails_passed", "FALSE"),
        "stable_enough_for_continued_capped_shadow_research": summary.get("stable_enough_for_continued_capped_shadow_research", "FALSE"),
        "stable_enough_for_shadow_expansion": "FALSE",
        "stable_enough_for_official_weight_change": "FALSE",
        "operator_review_required": "TRUE",
        "operator_input_required": "TRUE",
        "selected_operator_option": AWAITING,
        "recommended_next_action": next_action,
        **COMMON,
    }


def build_packet(review: dict[str, str]) -> dict[str, str]:
    return {
        "packet_id": "V20_165_CAPPED_BOUND_SHADOW_OPERATOR_REVIEW_PACKET_001",
        "operator_input_required": "TRUE",
        "selected_operator_option": AWAITING,
        "default_decision": AWAITING,
        "review_summary": "CAPPED_BOUND_SHADOW_GUARDRAILS_PASSED_OPERATOR_DECISION_REQUIRED_FOR_RESEARCH_ONLY_CONTINUATION",
        **review,
    }


def option_rows() -> list[dict[str, str]]:
    reasons = {
        "APPROVE_CONTINUED_CAPPED_BOUND_SHADOW_RESEARCH_ONLY": "All capped guardrails passed; approval remains research-only.",
        "REQUEST_MORE_FORWARD_OUTCOMES_BEFORE_ANY_EXPANSION": "Forward outcomes remain outside this stability packet.",
        "REQUEST_MORE_STABILITY_RETESTS": "Operator may request more capped retests before continuing.",
        "REQUEST_SCORE_CAP_PARAMETER_REVIEW": "Operator may review cap parameters before further research.",
        "REJECT_CAPPED_SHADOW_DYNAMIC_WEIGHT_PATH_FOR_NOW": "Operator may stop the capped shadow path without official mutation.",
    }
    return [{
        "operator_option_id": f"V20_165_OPERATOR_OPTION_{idx:03d}",
        "operator_option": option,
        "option_available": "TRUE",
        "selected_operator_option": AWAITING,
        "operator_input_required": "TRUE",
        "option_reason": reasons[option],
        **COMMON,
    } for idx, option in enumerate(OPTIONS, start=1)]


def safety_rows(upstream_mutated: bool, prereq_ok: bool) -> list[dict[str, str]]:
    checks = [
        ("v20_164_prerequisites_met", "TRUE", tf(prereq_ok)),
        ("formal_activation_allowed", "FALSE", "FALSE"),
        ("promotion_ready", "FALSE", "FALSE"),
        ("official_recommendation_created", "FALSE", "FALSE"),
        ("official_ranking_mutated", "FALSE", "FALSE"),
        ("official_weight_change_created", "FALSE", "FALSE"),
        ("capped_bound_shadow_operator_review_created", "TRUE", "TRUE"),
        ("shadow_review_scope", SCOPE, SCOPE),
        ("shadow_weight_expansion_allowed", "FALSE", "FALSE"),
        ("weight_mutated", "FALSE", "FALSE"),
        ("real_book_action_created", "FALSE", "FALSE"),
        ("trade_action_created", "FALSE", "FALSE"),
        ("broker_execution_supported", "FALSE", "FALSE"),
        ("performance_claim_created", "FALSE", "FALSE"),
        ("new_shadow_proposal_rows_created", "FALSE", "FALSE"),
        ("factor_scope_expanded", "FALSE", "FALSE"),
        ("outcomes_fabricated", "FALSE", "FALSE"),
        ("benchmarks_fabricated", "FALSE", "FALSE"),
        ("upstream_outputs_mutated", "FALSE", tf(upstream_mutated)),
    ]
    return [{
        "safety_check_id": f"V20_165_SAFETY_{idx:03d}",
        "safety_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "safety_passed": tf(expected == actual),
        **COMMON,
    } for idx, (check, expected, actual) in enumerate(checks, start=1)]


def write_report(status: str, review: dict[str, str] | None = None) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.165 Capped Bound Shadow Operator Review Report",
        "",
        f"- wrapper_status: {status}",
        f"- shadow_review_scope: {SCOPE}",
        "- operator_input_required: TRUE",
        f"- selected_operator_option: {AWAITING}",
        "- shadow_weight_expansion_allowed: FALSE",
        "- official_weight_change_allowed: FALSE",
        "- performance_claim_created: FALSE",
    ]
    if review:
        lines.extend([
            f"- retest_run_count: {review['retest_run_count']}",
            f"- stability_pass_count: {review['stability_pass_count']}",
            f"- max_capped_top20_turnover_rate: {review['max_capped_top20_turnover_rate']}",
            f"- max_capped_rank_delta: {review['max_capped_rank_delta']}",
            f"- all_capped_guardrails_passed: {review['all_capped_guardrails_passed']}",
            f"- recommended_next_action: {review['recommended_next_action']}",
        ])
    lines.extend(["", "No operator option is selected by this packet."])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_165_CAPPED_BOUND_SHADOW_NEXT_GATE_001",
        "v20_164_gate_consumed": "FALSE",
        "v20_164_status": "",
        "all_capped_guardrails_passed": "FALSE",
        "v20_165_operator_review_allowed": "FALSE",
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
        "no_outcomes_fabricated": "TRUE",
        "no_benchmarks_fabricated": "TRUE",
        "no_performance_claim_created": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_PACKET, PACKET_FIELDS, [])
    write_csv(OUT_REVIEW, REVIEW_FIELDS, [])
    write_csv(OUT_OPTIONS, OPTION_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SAFETY, SAFETY_FIELDS, [])
    write_report(BLOCKED_STATUS)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    before = input_hashes()
    missing = [path for path in inputs() if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))

    retest_rows, _ = read_csv(V164_RETEST)
    summary_rows, _ = read_csv(V164_SUMMARY)
    guardrail_rows, _ = read_csv(V164_GUARDRAIL)
    outlier_rows, _ = read_csv(V164_OUTLIER)
    gate_rows, _ = read_csv(V164_GATE)
    safety_in_rows, _ = read_csv(V164_SAFETY)
    if not all([retest_rows, summary_rows, guardrail_rows, outlier_rows, gate_rows, safety_in_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    summary = summary_rows[0]
    gate = gate_rows[0]
    prereq_ok = all([
        gate.get("final_status") == REQUIRED_V164_STATUS,
        gate.get("all_capped_guardrails_passed") == "TRUE",
        gate.get("v20_165_operator_review_allowed") == "TRUE",
        summary.get("max_capped_top20_turnover_rate") == "0.0000000000",
        summary.get("outlier_ticker_count_max") == "0",
        summary.get("factor_impact_concentration_max") == "0.0000000000",
        gate.get("shadow_weight_expansion_allowed") == "FALSE",
        gate.get("official_weight_change_allowed") == "FALSE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_164_REQUIREMENTS_NOT_MET")

    review = build_review(summary, gate)
    packet = build_packet(review)
    options = option_rows()
    upstream_mutated = before != input_hashes()
    safety = safety_rows(upstream_mutated, prereq_ok)
    safety_ok = all(row["safety_passed"] == "TRUE" for row in safety)

    if upstream_mutated or not safety_ok:
        status, blocking = BLOCKED_STATUS, "SAFETY_OR_UPSTREAM_MUTATION_FAILURE"
    elif gate.get("all_capped_guardrails_passed") != "TRUE" or gate.get("v20_165_operator_review_allowed") != "TRUE":
        status, blocking = WARN_STATUS, ""
    elif summary.get("stability_warn_count") != "0":
        status, blocking = PARTIAL_STATUS, ""
    else:
        status, blocking = PASS_STATUS, ""

    gate_out = {
        "gate_check_id": "V20_165_CAPPED_BOUND_SHADOW_NEXT_GATE_001",
        "v20_164_gate_consumed": "TRUE",
        "v20_164_status": gate.get("final_status", ""),
        "all_capped_guardrails_passed": gate.get("all_capped_guardrails_passed", "FALSE"),
        "v20_165_operator_review_allowed": gate.get("v20_165_operator_review_allowed", "FALSE"),
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
        "no_outcomes_fabricated": "TRUE",
        "no_benchmarks_fabricated": "TRUE",
        "no_performance_claim_created": "TRUE",
        "no_upstream_outputs_mutated": tf(not upstream_mutated),
        "blocking_reason": blocking,
        "final_status": status,
        **COMMON,
    }

    write_csv(OUT_PACKET, PACKET_FIELDS, [packet])
    write_csv(OUT_REVIEW, REVIEW_FIELDS, [review])
    write_csv(OUT_OPTIONS, OPTION_FIELDS, options)
    write_csv(OUT_GATE, GATE_FIELDS, [gate_out])
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_report(status, review)

    print(status)
    print("V20_164_GATE_CONSUMED=TRUE")
    print(f"V20_164_STATUS={gate.get('final_status', '')}")
    print("ALL_CAPPED_GUARDRAILS_PASSED=TRUE")
    print("V20_165_OPERATOR_REVIEW_ALLOWED=TRUE")
    print(f"RETEST_RUN_COUNT={review['retest_run_count']}")
    print(f"STABILITY_PASS_COUNT={review['stability_pass_count']}")
    print(f"STABILITY_WARN_COUNT={review['stability_warn_count']}")
    print(f"STABILITY_FAIL_COUNT={review['stability_fail_count']}")
    print(f"MAX_CAPPED_TOP20_TURNOVER_RATE={review['max_capped_top20_turnover_rate']}")
    print(f"MAX_CAPPED_RANK_DELTA={review['max_capped_rank_delta']}")
    print(f"OUTLIER_TICKER_COUNT_MAX={review['outlier_ticker_count_max']}")
    print(f"FACTOR_IMPACT_CONCENTRATION_MAX={review['factor_impact_concentration_max']}")
    print("OPERATOR_REVIEW_REQUIRED=TRUE")
    print("OPERATOR_INPUT_REQUIRED=TRUE")
    print(f"SELECTED_OPERATOR_OPTION={AWAITING}")
    print("SHADOW_WEIGHT_EXPANSION_ALLOWED=FALSE")
    print("OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE")
    print("FORMAL_ACTIVATION_ALLOWED=FALSE")
    print("PROMOTION_READY=FALSE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("OFFICIAL_WEIGHTS_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_ACTION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_ACTION_CREATED=FALSE")
    print("OUTCOMES_FABRICATED=0")
    print("BENCHMARKS_FABRICATED=0")
    print("PERFORMANCE_CLAIM_CREATED=FALSE")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
