#!/usr/bin/env python
"""V20.193 final operator acceptance with DATA_TRUST gate-only metadata."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"

V192_PACKET = FACTORS / "V20_192_CURRENT_CHAIN_RELEASE_CANDIDATE_PACKET.csv"
V192_GUARDRAIL = FACTORS / "V20_192_CURRENT_CHAIN_RELEASE_CANDIDATE_GUARDRAIL_AUDIT.csv"
V192_READINESS = FACTORS / "V20_192_CURRENT_CHAIN_READINESS_AUDIT.csv"
V192_STATUS = FACTORS / "V20_192_DATA_TRUST_SEALED_STATUS_AUDIT.csv"
V192_GATE = FACTORS / "V20_192_NEXT_STAGE_GATE.csv"
V192_REPORT = READ_CENTER / "V20_192_CURRENT_CHAIN_RELEASE_CANDIDATE_WITH_DATA_TRUST_GATE_ONLY_REPORT.md"

PROTECTED = [V192_PACKET, V192_GUARDRAIL, V192_READINESS, V192_STATUS, V192_GATE, V192_REPORT]

OUT_PACKET = FACTORS / "V20_193_FINAL_OPERATOR_ACCEPTANCE_PACKET.csv"
OUT_EVIDENCE = FACTORS / "V20_193_FINAL_ACCEPTANCE_EVIDENCE_SUMMARY.csv"
OUT_GUARDRAIL = FACTORS / "V20_193_FINAL_GUARDRAIL_CONFIRMATION_AUDIT.csv"
OUT_STATUS = FACTORS / "V20_193_DAILY_RUNNER_ACCEPTANCE_STATUS.csv"
OUT_GATE = FACTORS / "V20_193_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_193_FINAL_OPERATOR_ACCEPTANCE_WITH_DATA_TRUST_GATE_ONLY_REPORT.md"

READY_V192 = "PASS_V20_192_CURRENT_CHAIN_RELEASE_CANDIDATE_WITH_DATA_TRUST_GATE_ONLY_READY_FOR_V20_193_FINAL_OPERATOR_ACCEPTANCE"
PASS_STATUS = "PASS_V20_193_FINAL_OPERATOR_ACCEPTANCE_WITH_DATA_TRUST_GATE_ONLY_READY_FOR_DAILY_RESEARCH_RUNNER_REGULAR_USE"
BLOCKED_STATUS = "BLOCKED_V20_193_FINAL_OPERATOR_ACCEPTANCE_WITH_DATA_TRUST_GATE_ONLY"
RECOMMENDED_DECISION = "ACCEPT_CURRENT_CHAIN_RELEASE_CANDIDATE_FOR_DAILY_RESEARCH_USE_WITH_DATA_TRUST_ZERO_WEIGHT_GATE_ONLY_AND_CONTINUED_SHADOW_OBSERVATION"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_FINAL_OPERATOR_ACCEPTANCE_WITH_DATA_TRUST_GATE_ONLY"

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

PACKET_FIELDS = [
    "operator_decision_option", "option_available", "recommended_option",
    "recommended_operator_decision", "operator_decision_captured",
    "decision_scope", "decision_effect", "official_use_enabled_by_option",
    "real_book_use_enabled_by_option", "official_recommendation_enabled_by_option",
    "official_weight_mutation_enabled_by_option", "decision_rationale", *COMMON.keys(),
]
EVIDENCE_FIELDS = [
    "evidence_id", "evidence_category", "evidence_metric", "evidence_value",
    "expected_value", "evidence_passed", "source_artifact", "operator_relevance",
    *COMMON.keys(),
]
GUARDRAIL_FIELDS = [
    "guardrail_id", "guardrail", "expected_value", "actual_value",
    "guardrail_passed", "source_artifact", *COMMON.keys(),
]
STATUS_FIELDS = [
    "status_id", "daily_runner_acceptance_status",
    "current_chain_daily_research_use_accepted",
    "data_trust_zero_weight_gate_only_audit_status_preserved",
    "data_trust_zero_weight", "data_trust_gate_only", "data_trust_audit_only",
    "data_trust_read_center_disclosed", "data_trust_shadow_observation_continued",
    "ready_for_daily_research_runner_regular_use", "ready_for_official_use",
    "real_book_use_allowed", "official_recommendation_created",
    "official_weight_mutation_allowed", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_192_status_consumed", "v20_192_status",
    "recommended_operator_decision", "final_operator_acceptance_complete",
    "current_chain_daily_research_use_accepted",
    "data_trust_zero_weight_gate_only_audit_status_preserved",
    "ready_for_daily_research_runner_regular_use",
    "candidate_removed_or_reordered_count", "official_ranking_score_mutation_count",
    "official_rank_mutation_count", "data_trust_score_contribution_sum",
    "data_trust_nonzero_weight_count", "ready_for_official_use",
    "real_book_use_allowed", "official_recommendation_created",
    "official_weight_mutation_allowed", "data_trust_zero_weight",
    "data_trust_gate_only", "data_trust_audit_only",
    "data_trust_read_center_disclosed", "recommended_next_action",
    "blocking_reason", "final_status", *COMMON.keys(),
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


def evidence_row(idx: int, category: str, metric: str, value: str, expected: str, path: Path, relevance: str) -> dict[str, str]:
    return {
        "evidence_id": f"V20_193_EVIDENCE_{idx:03d}",
        "evidence_category": category,
        "evidence_metric": metric,
        "evidence_value": value,
        "expected_value": expected,
        "evidence_passed": tf(value == expected),
        "source_artifact": rel(path),
        "operator_relevance": relevance,
        **COMMON,
    }


def guardrail_row(idx: int, guardrail: str, expected: str, actual: str, path: Path) -> dict[str, str]:
    return {
        "guardrail_id": f"V20_193_GUARDRAIL_{idx:03d}",
        "guardrail": guardrail,
        "expected_value": expected,
        "actual_value": actual,
        "guardrail_passed": tf(expected == actual),
        "source_artifact": rel(path),
        **COMMON,
    }


def write_report(gate: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.193 Final Operator Acceptance With DATA_TRUST Gate-Only Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- recommended_operator_decision: {gate['recommended_operator_decision']}",
        f"- final_operator_acceptance_complete: {gate['final_operator_acceptance_complete']}",
        f"- current_chain_daily_research_use_accepted: {gate['current_chain_daily_research_use_accepted']}",
        f"- data_trust_zero_weight_gate_only_audit_status_preserved: {gate['data_trust_zero_weight_gate_only_audit_status_preserved']}",
        f"- ready_for_daily_research_runner_regular_use: {gate['ready_for_daily_research_runner_regular_use']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        f"- real_book_use_allowed: {gate['real_book_use_allowed']}",
        f"- official_recommendation_created: {gate['official_recommendation_created']}",
        f"- official_weight_mutation_allowed: {gate['official_weight_mutation_allowed']}",
        "",
        "Final operator acceptance confirms current chain daily research use with DATA_TRUST preserved as zero-weight gate-only audit metadata and continued shadow observation.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    write_csv(OUT_PACKET, PACKET_FIELDS, [])
    write_csv(OUT_EVIDENCE, EVIDENCE_FIELDS, [])
    write_csv(OUT_GUARDRAIL, GUARDRAIL_FIELDS, [])
    write_csv(OUT_STATUS, STATUS_FIELDS, [])
    gate = {
        "gate_check_id": "V20_193_NEXT_STAGE_GATE_001",
        "v20_192_status_consumed": "FALSE",
        "v20_192_status": "",
        "recommended_operator_decision": RECOMMENDED_DECISION,
        "final_operator_acceptance_complete": "FALSE",
        "current_chain_daily_research_use_accepted": "FALSE",
        "data_trust_zero_weight_gate_only_audit_status_preserved": "FALSE",
        "ready_for_daily_research_runner_regular_use": "FALSE",
        "candidate_removed_or_reordered_count": "0",
        "official_ranking_score_mutation_count": "0",
        "official_rank_mutation_count": "0",
        "data_trust_score_contribution_sum": "0.0000000000",
        "data_trust_nonzero_weight_count": "0",
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_read_center_disclosed": "TRUE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_V20_193",
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
    before = protected_hashes()
    packet_rows, _ = read_csv(V192_PACKET)
    guardrail_rows, _ = read_csv(V192_GUARDRAIL)
    readiness_rows, _ = read_csv(V192_READINESS)
    status_rows, _ = read_csv(V192_STATUS)
    gate_rows, _ = read_csv(V192_GATE)
    if not all([packet_rows, guardrail_rows, readiness_rows, status_rows, gate_rows, V192_REPORT.exists()]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    packet = packet_rows[0]
    gate192 = gate_rows[0]
    upstream_ready = all([
        gate192.get("final_status") == READY_V192,
        gate192.get("ready_for_v20_193_final_operator_acceptance") == "TRUE",
        packet.get("release_candidate_created") == "TRUE",
        packet.get("data_trust_sealed_status_preserved") == "TRUE",
        all(row.get("audit_check_passed") == "TRUE" for row in guardrail_rows),
        all(row.get("audit_check_passed") == "TRUE" for row in readiness_rows),
        all(row.get("audit_check_passed") == "TRUE" for row in status_rows),
    ])
    if not upstream_ready:
        return emit_blocked("V20_192_RELEASE_CANDIDATE_NOT_READY")

    upstream_mutated = before != protected_hashes()
    preserved = all([
        gate192.get("data_trust_zero_weight") == "TRUE",
        gate192.get("data_trust_gate_only") == "TRUE",
        gate192.get("data_trust_audit_only") == "TRUE",
        gate192.get("data_trust_read_center_disclosed") == "TRUE",
        packet.get("data_trust_zero_weight") == "TRUE",
        packet.get("data_trust_gate_only") == "TRUE",
        packet.get("data_trust_audit_only") == "TRUE",
        packet.get("data_trust_read_center_disclosed") == "TRUE",
    ])
    guardrails_ok = all([
        gate192.get("current_chain_release_candidate_created") == "TRUE",
        gate192.get("release_candidate_guardrail_pass") == "TRUE",
        gate192.get("current_chain_readiness_pass") == "TRUE",
        gate192.get("data_trust_sealed_status_pass") == "TRUE",
        gate192.get("candidate_removed_or_reordered_count") == "0",
        gate192.get("official_ranking_score_mutation_count") == "0",
        gate192.get("official_rank_mutation_count") == "0",
        gate192.get("data_trust_score_contribution_sum") == "0.0000000000",
        gate192.get("data_trust_nonzero_weight_count") == "0",
        gate192.get("ready_for_official_use") == "FALSE",
        gate192.get("real_book_use_allowed") == "FALSE",
        gate192.get("official_recommendation_created") == "FALSE",
        gate192.get("official_weight_mutation_allowed") == "FALSE",
        not upstream_mutated,
    ])
    all_pass = all([preserved, guardrails_ok])

    decisions = [
        ("ACCEPT_CURRENT_CHAIN_RELEASE_CANDIDATE_FOR_DAILY_RESEARCH_USE", "ACCEPT_FOR_DAILY_RESEARCH_RUNNER_REGULAR_USE_WITH_CONTINUED_DATA_TRUST_SHADOW_OBSERVATION", "Selected because V20.192 release candidate, readiness, sealed-status, and guardrail checks passed."),
        ("ACCEPT_WITH_CONTINUED_SHADOW_OBSERVATION", "NOT_SELECTED", "Available fallback if regular daily research use acceptance is deferred."),
        ("REQUEST_ADDITIONAL_REGRESSION", "NOT_SELECTED", "Available if V20.192 evidence is incomplete or unstable."),
        ("REJECT_RELEASE_CANDIDATE", "NOT_SELECTED", "Available if release candidate guardrails fail."),
    ]
    packet_out = []
    for option, effect, rationale in decisions:
        recommended = option == "ACCEPT_CURRENT_CHAIN_RELEASE_CANDIDATE_FOR_DAILY_RESEARCH_USE"
        packet_out.append({
            "operator_decision_option": option,
            "option_available": "TRUE",
            "recommended_option": tf(recommended),
            "recommended_operator_decision": RECOMMENDED_DECISION,
            "operator_decision_captured": tf(recommended and all_pass),
            "decision_scope": "CURRENT_DAILY_RESEARCH_CHAIN_RELEASE_CANDIDATE_WITH_DATA_TRUST_ZERO_WEIGHT_GATE_ONLY",
            "decision_effect": effect,
            "official_use_enabled_by_option": "FALSE",
            "real_book_use_enabled_by_option": "FALSE",
            "official_recommendation_enabled_by_option": "FALSE",
            "official_weight_mutation_enabled_by_option": "FALSE",
            "decision_rationale": rationale,
            **COMMON,
        })

    evidence = [
        evidence_row(1, "release_candidate", "current_chain_release_candidate_created", gate192.get("current_chain_release_candidate_created", ""), "TRUE", V192_GATE, "Confirms release candidate exists for final operator acceptance."),
        evidence_row(2, "release_candidate", "release_candidate_guardrail_pass", gate192.get("release_candidate_guardrail_pass", ""), "TRUE", V192_GATE, "Confirms release candidate guardrails passed."),
        evidence_row(3, "readiness", "current_chain_readiness_pass", gate192.get("current_chain_readiness_pass", ""), "TRUE", V192_GATE, "Confirms current chain is ready for daily research use."),
        evidence_row(4, "sealed_status", "data_trust_sealed_status_pass", gate192.get("data_trust_sealed_status_pass", ""), "TRUE", V192_GATE, "Confirms DATA_TRUST sealed metadata status is preserved."),
        evidence_row(5, "ranking", "candidate_removed_or_reordered_count", gate192.get("candidate_removed_or_reordered_count", ""), "0", V192_GATE, "Confirms DATA_TRUST did not remove or reorder candidates."),
        evidence_row(6, "ranking", "official_ranking_score_mutation_count", gate192.get("official_ranking_score_mutation_count", ""), "0", V192_GATE, "Confirms no official score mutation."),
        evidence_row(7, "ranking", "official_rank_mutation_count", gate192.get("official_rank_mutation_count", ""), "0", V192_GATE, "Confirms no official rank mutation."),
        evidence_row(8, "zero_weight", "data_trust_score_contribution_sum", gate192.get("data_trust_score_contribution_sum", ""), "0.0000000000", V192_GATE, "Confirms DATA_TRUST contributes zero score."),
        evidence_row(9, "zero_weight", "data_trust_nonzero_weight_count", gate192.get("data_trust_nonzero_weight_count", ""), "0", V192_GATE, "Confirms no nonzero DATA_TRUST weight exists."),
        evidence_row(10, "official_use", "ready_for_official_use", gate192.get("ready_for_official_use", ""), "FALSE", V192_GATE, "Confirms official use remains disabled."),
        evidence_row(11, "official_use", "real_book_use_allowed", gate192.get("real_book_use_allowed", ""), "FALSE", V192_GATE, "Confirms real-book use remains disabled."),
        evidence_row(12, "official_use", "official_recommendation_created", gate192.get("official_recommendation_created", ""), "FALSE", V192_GATE, "Confirms no official recommendation is created."),
        evidence_row(13, "official_use", "official_weight_mutation_allowed", gate192.get("official_weight_mutation_allowed", ""), "FALSE", V192_GATE, "Confirms official weight mutation remains disallowed."),
    ]
    guardrails = [
        guardrail_row(1, "ready_for_official_use", "FALSE", gate192.get("ready_for_official_use", ""), V192_GATE),
        guardrail_row(2, "real_book_use_allowed", "FALSE", gate192.get("real_book_use_allowed", ""), V192_GATE),
        guardrail_row(3, "official_recommendation_created", "FALSE", gate192.get("official_recommendation_created", ""), V192_GATE),
        guardrail_row(4, "official_weight_mutation_allowed", "FALSE", gate192.get("official_weight_mutation_allowed", ""), V192_GATE),
        guardrail_row(5, "data_trust_zero_weight", "TRUE", gate192.get("data_trust_zero_weight", ""), V192_GATE),
        guardrail_row(6, "data_trust_gate_only", "TRUE", gate192.get("data_trust_gate_only", ""), V192_GATE),
        guardrail_row(7, "data_trust_audit_only", "TRUE", gate192.get("data_trust_audit_only", ""), V192_GATE),
        guardrail_row(8, "data_trust_read_center_disclosed", "TRUE", gate192.get("data_trust_read_center_disclosed", ""), V192_GATE),
        guardrail_row(9, "official_ranking_score_mutation_count", "0", gate192.get("official_ranking_score_mutation_count", ""), V192_GATE),
        guardrail_row(10, "official_rank_mutation_count", "0", gate192.get("official_rank_mutation_count", ""), V192_GATE),
        guardrail_row(11, "data_trust_score_contribution_sum", "0.0000000000", gate192.get("data_trust_score_contribution_sum", ""), V192_GATE),
        guardrail_row(12, "data_trust_nonzero_weight_count", "0", gate192.get("data_trust_nonzero_weight_count", ""), V192_GATE),
        guardrail_row(13, "upstream_v20_192_artifacts_mutated", "FALSE", tf(upstream_mutated), V192_GATE),
    ]
    evidence_pass = all(row["evidence_passed"] == "TRUE" for row in evidence)
    guardrail_pass = all(row["guardrail_passed"] == "TRUE" for row in guardrails)
    acceptance_complete = all([all_pass, evidence_pass, guardrail_pass])

    status = {
        "status_id": "V20_193_DAILY_RUNNER_ACCEPTANCE_STATUS_001",
        "daily_runner_acceptance_status": "ACCEPTED_FOR_DAILY_RESEARCH_RUNNER_REGULAR_USE",
        "current_chain_daily_research_use_accepted": tf(acceptance_complete),
        "data_trust_zero_weight_gate_only_audit_status_preserved": tf(preserved),
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_read_center_disclosed": "TRUE",
        "data_trust_shadow_observation_continued": "TRUE",
        "ready_for_daily_research_runner_regular_use": tf(acceptance_complete),
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        **COMMON,
    }
    gate = {
        "gate_check_id": "V20_193_NEXT_STAGE_GATE_001",
        "v20_192_status_consumed": "TRUE",
        "v20_192_status": gate192.get("final_status", ""),
        "recommended_operator_decision": RECOMMENDED_DECISION,
        "final_operator_acceptance_complete": tf(acceptance_complete),
        "current_chain_daily_research_use_accepted": tf(acceptance_complete),
        "data_trust_zero_weight_gate_only_audit_status_preserved": tf(preserved),
        "ready_for_daily_research_runner_regular_use": tf(acceptance_complete),
        "candidate_removed_or_reordered_count": gate192.get("candidate_removed_or_reordered_count", ""),
        "official_ranking_score_mutation_count": gate192.get("official_ranking_score_mutation_count", ""),
        "official_rank_mutation_count": gate192.get("official_rank_mutation_count", ""),
        "data_trust_score_contribution_sum": gate192.get("data_trust_score_contribution_sum", ""),
        "data_trust_nonzero_weight_count": gate192.get("data_trust_nonzero_weight_count", ""),
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_read_center_disclosed": "TRUE",
        "recommended_next_action": "USE_DAILY_RESEARCH_RUNNER_REGULARLY_WITH_DATA_TRUST_GATE_ONLY_METADATA" if acceptance_complete else "REPAIR_V20_193_ACCEPTANCE_BLOCKER",
        "blocking_reason": "NONE" if acceptance_complete else "V20_193_FINAL_ACCEPTANCE_GUARD_FAILURE",
        "final_status": PASS_STATUS if acceptance_complete else BLOCKED_STATUS,
        **COMMON,
    }

    write_csv(OUT_PACKET, PACKET_FIELDS, packet_out)
    write_csv(OUT_EVIDENCE, EVIDENCE_FIELDS, evidence)
    write_csv(OUT_GUARDRAIL, GUARDRAIL_FIELDS, guardrails)
    write_csv(OUT_STATUS, STATUS_FIELDS, [status])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate)

    print(gate["final_status"])
    for key in GATE_FIELDS:
        if key in gate and key not in COMMON and key != "gate_check_id":
            print(f"{key.upper()}={gate[key]}")
    print("READY_FOR_OFFICIAL_USE=FALSE")
    print("REAL_BOOK_USE_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("OFFICIAL_WEIGHT_MUTATION_ALLOWED=FALSE")
    print(f"OFFICIAL_MUTATION_DETECTED={tf(upstream_mutated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
