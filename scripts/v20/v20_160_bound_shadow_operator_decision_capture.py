#!/usr/bin/env python
"""V20.160 bound shadow operator decision capture.

Captures explicit operator input for the V20.159 bound reduced shadow review.
The captured decision allows continued bound shadow research and requires
additional stability observation runs only. It does not approve expansion,
official weight changes, formal activation, recommendations, real-book actions,
trades, broker actions, or performance claims.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"

IN_PACKET = FACTORS / "V20_159_BOUND_SHADOW_OPERATOR_REVIEW_PACKET.csv"
IN_REVIEW = FACTORS / "V20_159_BOUND_SHADOW_STABILITY_REVIEW.csv"
IN_OPTIONS = FACTORS / "V20_159_BOUND_SHADOW_OPERATOR_OPTIONS.csv"
IN_GATE = FACTORS / "V20_159_BOUND_SHADOW_NEXT_GATE.csv"
IN_SAFETY = FACTORS / "V20_159_BOUND_SHADOW_SAFETY_AUDIT.csv"

OUT_DECISION = FACTORS / "V20_160_BOUND_SHADOW_OPERATOR_DECISION_CAPTURE.csv"
OUT_GATE = FACTORS / "V20_160_BOUND_SHADOW_OPERATOR_DECISION_GATE.csv"
OUT_SAFETY = FACTORS / "V20_160_BOUND_SHADOW_DECISION_SAFETY_AUDIT.csv"
OUT_NEXT = FACTORS / "V20_160_BOUND_SHADOW_NEXT_STAGE_PACKET.csv"
REPORT = READ_CENTER / "V20_160_BOUND_SHADOW_OPERATOR_DECISION_CAPTURE_REPORT.md"

REQUIRED_V159_STATUS = "PASS_V20_159_BOUND_SHADOW_OPERATOR_REVIEW_PACKET_AWAITING_OPERATOR_INPUT"
SELECTED_OPTION = "REQUEST_ADDITIONAL_STABILITY_OBSERVATION_RUNS"
PASS_STATUS = "PASS_V20_160_BOUND_SHADOW_OPERATOR_DECISION_CAPTURE_READY_FOR_V20_161"
BLOCKED_STATUS = "BLOCKED_V20_160_BOUND_SHADOW_OPERATOR_DECISION_CAPTURE"
SCOPE = "RESEARCH_ONLY_LIMITED_CONSERVATIVE_BOUND_TO_AUTHORITATIVE_BASELINE"

SAFETY = {
    "continued_bound_shadow_research_allowed": "TRUE",
    "additional_stability_observation_runs_required": "TRUE",
    "shadow_weight_expansion_allowed": "FALSE",
    "official_weight_change_allowed": "FALSE",
    "formal_activation_allowed": "FALSE",
    "promotion_ready": "FALSE",
    "official_recommendation_created": "FALSE",
    "official_ranking_mutated": "FALSE",
    "official_weight_change_created": "FALSE",
    "real_book_action_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "performance_claim_created": "FALSE",
}
COMMON = {
    **SAFETY,
    "research_only": "TRUE",
    "staging_review_only": "TRUE",
    "operator_decision_capture_only": "TRUE",
    "shadow_review_scope": SCOPE,
    "audit_only": "TRUE",
}

DECISION_FIELDS = [
    "decision_id",
    "v20_159_status",
    "operator_input_required",
    "selected_operator_option",
    "operator_decision_captured",
    "operator_decision_source",
    "operator_scope",
    "continued_bound_shadow_research_allowed",
    "additional_stability_observation_runs_required",
    "shadow_weight_expansion_allowed",
    "official_weight_change_allowed",
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
    "official_weight_change_created",
    "real_book_action_created",
    "trade_action_created",
    "broker_execution_supported",
    "performance_claim_created",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id",
    "v20_159_gate_consumed",
    "v20_159_status",
    "v20_159_status_allowed",
    "selected_operator_option",
    "selected_operator_option_available",
    "continued_bound_shadow_research_allowed",
    "additional_stability_observation_runs_required",
    "shadow_weight_expansion_allowed",
    "official_weight_change_allowed",
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
    "official_weight_change_created",
    "real_book_action_created",
    "trade_action_created",
    "broker_execution_supported",
    "performance_claim_created",
    "no_upstream_outputs_mutated",
    "v20_161_allowed",
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
NEXT_FIELDS = [
    "next_stage_packet_id",
    "selected_operator_option",
    "v20_161_stage",
    "v20_161_allowed",
    "continued_bound_shadow_research_allowed",
    "additional_stability_observation_runs_required",
    "shadow_weight_expansion_allowed",
    "official_weight_change_allowed",
    "formal_activation_allowed",
    "recommended_next_action",
    *COMMON.keys(),
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


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


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def inputs() -> list[Path]:
    return [IN_PACKET, IN_REVIEW, IN_OPTIONS, IN_GATE, IN_SAFETY]


def input_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in inputs() if path.exists()}


def option_available(options: list[dict[str, str]]) -> bool:
    return any(row.get("operator_option") == SELECTED_OPTION and row.get("option_available") == "TRUE" for row in options)


def safety_rows(upstream_mutated: bool, prereq_ok: bool, option_ok: bool) -> list[dict[str, str]]:
    checks = [
        ("v20_159_prerequisites_met", "TRUE", tf(prereq_ok)),
        ("selected_operator_option_available", "TRUE", tf(option_ok)),
        ("continued_bound_shadow_research_allowed", "TRUE", "TRUE"),
        ("additional_stability_observation_runs_required", "TRUE", "TRUE"),
        ("shadow_weight_expansion_allowed", "FALSE", "FALSE"),
        ("official_weight_change_allowed", "FALSE", "FALSE"),
        ("formal_activation_allowed", "FALSE", "FALSE"),
        ("promotion_ready", "FALSE", "FALSE"),
        ("official_recommendation_created", "FALSE", "FALSE"),
        ("official_ranking_mutated", "FALSE", "FALSE"),
        ("official_weight_change_created", "FALSE", "FALSE"),
        ("real_book_action_created", "FALSE", "FALSE"),
        ("trade_action_created", "FALSE", "FALSE"),
        ("broker_execution_supported", "FALSE", "FALSE"),
        ("performance_claim_created", "FALSE", "FALSE"),
        ("upstream_outputs_mutated", "FALSE", tf(upstream_mutated)),
    ]
    return [{
        "safety_check_id": f"V20_160_SAFETY_{index:03d}",
        "safety_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "safety_passed": tf(expected == actual),
        **COMMON,
    } for index, (check, expected, actual) in enumerate(checks, start=1)]


def write_report(status: str, option: str, allowed: str) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.160 Bound Shadow Operator Decision Capture Report",
        "",
        f"- wrapper_status: {status}",
        f"- selected_operator_option: {option}",
        f"- continued_bound_shadow_research_allowed: {SAFETY['continued_bound_shadow_research_allowed']}",
        f"- additional_stability_observation_runs_required: {SAFETY['additional_stability_observation_runs_required']}",
        f"- v20_161_allowed: {allowed}",
        "- shadow_weight_expansion_allowed: FALSE",
        "- official_weight_change_allowed: FALSE",
        "- formal_activation_allowed: FALSE",
        "- performance_claim_created: FALSE",
        "",
        "The captured decision is limited to continued bound shadow research and additional stability observation runs.",
    ]) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_160_BOUND_SHADOW_OPERATOR_DECISION_GATE_001",
        "v20_159_gate_consumed": "FALSE",
        "v20_159_status": "",
        "v20_159_status_allowed": "FALSE",
        "selected_operator_option": SELECTED_OPTION,
        "selected_operator_option_available": "FALSE",
        **SAFETY,
        "no_upstream_outputs_mutated": "TRUE",
        "v20_161_allowed": "FALSE",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_DECISION, DECISION_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SAFETY, SAFETY_AUDIT_FIELDS, [])
    write_csv(OUT_NEXT, NEXT_FIELDS, [])
    write_report(BLOCKED_STATUS, SELECTED_OPTION, "FALSE")
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    before = input_hashes()
    missing = [path for path in inputs() if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_V20_159_OUTPUTS:" + ";".join(rel(path) for path in missing))
    packet_rows, _ = read_csv(IN_PACKET)
    review_rows, _ = read_csv(IN_REVIEW)
    option_rows, _ = read_csv(IN_OPTIONS)
    gate_rows, _ = read_csv(IN_GATE)
    safety_in, _ = read_csv(IN_SAFETY)
    if not all([packet_rows, review_rows, option_rows, gate_rows, safety_in]):
        return emit_blocked("EMPTY_REQUIRED_V20_159_OUTPUTS")
    v159_status = gate_rows[0].get("final_status", "")
    prereq_ok = (
        v159_status == REQUIRED_V159_STATUS
        and gate_rows[0].get("operator_input_required") == "TRUE"
        and gate_rows[0].get("selected_operator_option") == "AWAITING_EXPLICIT_OPERATOR_REVIEW"
    )
    option_ok = option_available(option_rows)
    if not prereq_ok or not option_ok:
        return emit_blocked("V20_159_OPERATOR_DECISION_CAPTURE_REQUIREMENTS_NOT_MET")
    upstream_mutated = before != input_hashes()
    safety = safety_rows(upstream_mutated, prereq_ok, option_ok)
    safety_ok = all(row["safety_passed"] == "TRUE" for row in safety)
    status = PASS_STATUS if safety_ok else BLOCKED_STATUS
    v20_161_allowed = tf(status == PASS_STATUS)
    decision = {
        "decision_id": "V20_160_BOUND_SHADOW_OPERATOR_DECISION_CAPTURE_001",
        "v20_159_status": v159_status,
        "operator_input_required": "TRUE",
        "selected_operator_option": SELECTED_OPTION,
        "operator_decision_captured": "TRUE",
        "operator_decision_source": "USER_PROVIDED_EXPLICIT_OPERATOR_INPUT",
        "operator_scope": "CONTINUED_BOUND_SHADOW_RESEARCH_ONLY_NO_EXPANSION_NO_OFFICIAL_CHANGES_NO_ACTIONS_NO_PERFORMANCE_CLAIMS",
        **SAFETY,
        **COMMON,
    }
    next_packet = {
        "next_stage_packet_id": "V20_160_BOUND_SHADOW_NEXT_STAGE_PACKET_001",
        "selected_operator_option": SELECTED_OPTION,
        "v20_161_stage": "V20.161_ADDITIONAL_BOUND_SHADOW_STABILITY_OBSERVATION_RUNS",
        "v20_161_allowed": v20_161_allowed,
        "continued_bound_shadow_research_allowed": "TRUE",
        "additional_stability_observation_runs_required": "TRUE",
        "shadow_weight_expansion_allowed": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "formal_activation_allowed": "FALSE",
        "recommended_next_action": "RUN_ADDITIONAL_BOUND_SHADOW_STABILITY_OBSERVATION_RUNS",
        **COMMON,
    }
    gate = {
        "gate_check_id": "V20_160_BOUND_SHADOW_OPERATOR_DECISION_GATE_001",
        "v20_159_gate_consumed": "TRUE",
        "v20_159_status": v159_status,
        "v20_159_status_allowed": "TRUE",
        "selected_operator_option": SELECTED_OPTION,
        "selected_operator_option_available": "TRUE",
        **SAFETY,
        "no_upstream_outputs_mutated": tf(not upstream_mutated),
        "v20_161_allowed": v20_161_allowed,
        "blocking_reason": "" if status == PASS_STATUS else "SAFETY_FAILURE",
        "final_status": status,
        **COMMON,
    }
    write_csv(OUT_DECISION, DECISION_FIELDS, [decision])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SAFETY, SAFETY_AUDIT_FIELDS, safety)
    write_csv(OUT_NEXT, NEXT_FIELDS, [next_packet])
    write_report(status, SELECTED_OPTION, v20_161_allowed)

    print(status)
    print("V20_159_GATE_CONSUMED=TRUE")
    print("V20_159_STATUS_ALLOWED=TRUE")
    print(f"SELECTED_OPERATOR_OPTION={SELECTED_OPTION}")
    print("OPERATOR_DECISION_CAPTURED=TRUE")
    print("CONTINUED_BOUND_SHADOW_RESEARCH_ALLOWED=TRUE")
    print("ADDITIONAL_STABILITY_OBSERVATION_RUNS_REQUIRED=TRUE")
    print("SHADOW_WEIGHT_EXPANSION_ALLOWED=FALSE")
    print("OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE")
    print("FORMAL_ACTIVATION_ALLOWED=FALSE")
    print("PROMOTION_READY=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("OFFICIAL_WEIGHT_CHANGE_CREATED=FALSE")
    print("REAL_BOOK_ACTION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("PERFORMANCE_CLAIM_CREATED=FALSE")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    print(f"V20_161_ALLOWED={v20_161_allowed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
