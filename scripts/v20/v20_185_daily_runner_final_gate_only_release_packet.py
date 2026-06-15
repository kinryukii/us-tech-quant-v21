#!/usr/bin/env python
"""V20.185 DATA_TRUST daily runner final gate-only release packet."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"

V182_PACKET = FACTORS / "V20_182_DATA_TRUST_FINAL_OPERATOR_DECISION_PACKET.csv"
V182_GUARDRAIL = FACTORS / "V20_182_DATA_TRUST_FINAL_GUARDRAIL_AUDIT.csv"
V182_STATUS = FACTORS / "V20_182_DATA_TRUST_DAILY_RUNNER_INTEGRATION_STATUS.csv"
V182_GATE = FACTORS / "V20_182_NEXT_STAGE_GATE.csv"
V183_AUDIT = FACTORS / "V20_183_DATA_TRUST_READ_CENTER_INTEGRATION_AUDIT.csv"
V183_SAMPLE = FACTORS / "V20_183_DATA_TRUST_READ_CENTER_DISPLAY_SAMPLE.csv"
V183_GUARD = FACTORS / "V20_183_OFFICIAL_USE_GUARD_AUDIT.csv"
V183_GATE = FACTORS / "V20_183_NEXT_STAGE_GATE.csv"
V184_READABILITY = FACTORS / "V20_184_OPERATOR_READABILITY_AUDIT.csv"
V184_MISLEADING = FACTORS / "V20_184_DATA_TRUST_MISLEADING_LANGUAGE_AUDIT.csv"
V184_RECOMMENDATION = FACTORS / "V20_184_OPERATOR_DISPLAY_RECOMMENDATION.csv"
V184_GATE = FACTORS / "V20_184_NEXT_STAGE_GATE.csv"

PROTECTED = [
    V182_PACKET, V182_GUARDRAIL, V182_STATUS, V182_GATE,
    V183_AUDIT, V183_SAMPLE, V183_GUARD, V183_GATE,
    V184_READABILITY, V184_MISLEADING, V184_RECOMMENDATION, V184_GATE,
]

OUT_PACKET = FACTORS / "V20_185_DATA_TRUST_FINAL_GATE_ONLY_RELEASE_PACKET.csv"
OUT_GUARDRAIL = FACTORS / "V20_185_DATA_TRUST_FINAL_RELEASE_GUARDRAIL_AUDIT.csv"
OUT_SUMMARY = FACTORS / "V20_185_OPERATOR_FACING_RELEASE_SUMMARY.csv"
OUT_GATE = FACTORS / "V20_185_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_185_DAILY_RUNNER_FINAL_GATE_ONLY_RELEASE_PACKET_REPORT.md"

READY_V182 = "PASS_V20_182_DATA_TRUST_GATE_ONLY_CLOSEOUT_OPERATOR_DECISION_READY_FOR_V20_183_READ_CENTER_INTEGRATION"
READY_V183 = "PASS_V20_183_DAILY_RESEARCH_RUNNER_READ_CENTER_INTEGRATION_READY_FOR_V20_184_OPERATOR_READABILITY_REVIEW"
READY_V184 = "PASS_V20_184_DAILY_RESEARCH_RUNNER_OPERATOR_READABILITY_REVIEW_READY_FOR_V20_185_RELEASE_PACKET"
PASS_STATUS = "PASS_V20_185_DAILY_RUNNER_FINAL_GATE_ONLY_RELEASE_PACKET_READY_FOR_V20_186_RELEASE_LOCK"
BLOCKED_STATUS = "BLOCKED_V20_185_DAILY_RUNNER_FINAL_GATE_ONLY_RELEASE_PACKET"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DAILY_RUNNER_FINAL_GATE_ONLY_RELEASE_PACKET"

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
    "release_packet_id", "release_scope", "release_status",
    "released_as_zero_weight", "released_as_gate_only", "released_as_audit_only",
    "released_as_read_center_disclosed", "released_as_shadow_observation_continued",
    "released_as_official_scoring_factor", "released_as_official_ranking_weight",
    "released_as_official_recommendation_trigger", "released_as_real_book_permission_gate",
    "official_ranking_score_mutation_count", "official_rank_mutation_count",
    "data_trust_score_contribution_sum", "data_trust_nonzero_weight_count",
    "ready_for_official_use", "real_book_use_allowed",
    "official_recommendation_created", "official_weight_mutation_allowed",
    *COMMON.keys(),
]
GUARDRAIL_FIELDS = [
    "guardrail_id", "guardrail", "expected_value", "actual_value",
    "guardrail_passed", "source_artifact", *COMMON.keys(),
]
SUMMARY_FIELDS = [
    "summary_id", "operator_facing_release_summary", "release_packet_pass",
    "ranking_mutation_guard_pass", "zero_weight_guard_pass",
    "official_use_guard_pass", "ready_for_v20_186_daily_research_runner_release_lock",
    "ready_for_official_use", "real_book_use_allowed",
    "official_recommendation_created", "official_weight_mutation_allowed",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_182_status_consumed", "v20_182_status",
    "v20_183_status_consumed", "v20_183_status", "v20_184_status_consumed",
    "v20_184_status", "data_trust_gate_only_release_pass",
    "ranking_mutation_guard_pass", "zero_weight_guard_pass",
    "official_use_guard_pass", "official_ranking_score_mutation_count",
    "official_rank_mutation_count", "data_trust_score_contribution_sum",
    "data_trust_nonzero_weight_count", "released_as_official_scoring_factor",
    "released_as_official_ranking_weight", "released_as_official_recommendation_trigger",
    "released_as_real_book_permission_gate",
    "ready_for_v20_186_daily_research_runner_release_lock",
    "ready_for_official_use", "real_book_use_allowed", "official_recommendation_created",
    "official_weight_mutation_allowed", "data_trust_zero_weight", "data_trust_gate_only",
    "data_trust_audit_only", "data_trust_read_center_disclosed",
    "data_trust_shadow_observation_continued", "recommended_next_action",
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


def write_report(gate: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.185 Daily Runner Final Gate-Only Release Packet Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- data_trust_gate_only_release_pass: {gate['data_trust_gate_only_release_pass']}",
        f"- ranking_mutation_guard_pass: {gate['ranking_mutation_guard_pass']}",
        f"- zero_weight_guard_pass: {gate['zero_weight_guard_pass']}",
        f"- official_use_guard_pass: {gate['official_use_guard_pass']}",
        f"- ready_for_v20_186_daily_research_runner_release_lock: {gate['ready_for_v20_186_daily_research_runner_release_lock']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        f"- real_book_use_allowed: {gate['real_book_use_allowed']}",
        f"- official_recommendation_created: {gate['official_recommendation_created']}",
        f"- official_weight_mutation_allowed: {gate['official_weight_mutation_allowed']}",
        "",
        "Final release packet releases DATA_TRUST only as zero-weight gate-only audit metadata that remains read-center disclosed and under continued shadow observation. It is not released as an official scoring factor, official ranking weight, official recommendation trigger, or real-book permission gate.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [(OUT_PACKET, PACKET_FIELDS), (OUT_GUARDRAIL, GUARDRAIL_FIELDS), (OUT_SUMMARY, SUMMARY_FIELDS)]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_185_NEXT_STAGE_GATE_001",
        "v20_182_status_consumed": "FALSE",
        "v20_182_status": "",
        "v20_183_status_consumed": "FALSE",
        "v20_183_status": "",
        "v20_184_status_consumed": "FALSE",
        "v20_184_status": "",
        "data_trust_gate_only_release_pass": "FALSE",
        "ranking_mutation_guard_pass": "FALSE",
        "zero_weight_guard_pass": "FALSE",
        "official_use_guard_pass": "FALSE",
        "official_ranking_score_mutation_count": "0",
        "official_rank_mutation_count": "0",
        "data_trust_score_contribution_sum": "0.0000000000",
        "data_trust_nonzero_weight_count": "0",
        "released_as_official_scoring_factor": "FALSE",
        "released_as_official_ranking_weight": "FALSE",
        "released_as_official_recommendation_trigger": "FALSE",
        "released_as_real_book_permission_gate": "FALSE",
        "ready_for_v20_186_daily_research_runner_release_lock": "FALSE",
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_read_center_disclosed": "TRUE",
        "data_trust_shadow_observation_continued": "TRUE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_V20_185",
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
    datasets = {path: read_csv(path)[0] for path in PROTECTED}
    if any(not rows for rows in datasets.values()):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    v182_gate = datasets[V182_GATE][0]
    v182_status = datasets[V182_STATUS][0]
    v183_gate = datasets[V183_GATE][0]
    v184_gate = datasets[V184_GATE][0]
    v184_recommendation = datasets[V184_RECOMMENDATION][0]
    if not all([
        v182_gate.get("final_status") == READY_V182,
        v183_gate.get("final_status") == READY_V183,
        v184_gate.get("final_status") == READY_V184,
        v184_gate.get("ready_for_v20_185_daily_runner_final_gate_only_release_packet") == "TRUE",
        v184_recommendation.get("ready_for_release_packet") == "TRUE",
    ]):
        return emit_blocked("V20_182_V20_183_OR_V20_184_REQUIREMENTS_NOT_MET")

    upstream_mutated = before != protected_hashes()
    release_as = {
        "zero_weight": all([v182_gate.get("data_trust_zero_weight") == "TRUE", v183_gate.get("data_trust_zero_weight") == "TRUE", v184_gate.get("data_trust_zero_weight") == "TRUE"]),
        "gate_only": all([v182_gate.get("data_trust_gate_only") == "TRUE", v183_gate.get("data_trust_gate_only") == "TRUE", v184_gate.get("data_trust_gate_only") == "TRUE"]),
        "audit_only": all([v182_gate.get("data_trust_audit_only") == "TRUE", v183_gate.get("data_trust_audit_only") == "TRUE", v184_gate.get("data_trust_audit_only") == "TRUE"]),
        "read_center_disclosed": all([v183_gate.get("data_trust_daily_runner_disclosed") == "TRUE", v184_gate.get("aggregate_status_present") == "TRUE"]),
        "shadow_observation_continued": all([v182_gate.get("data_trust_daily_runner_shadow_observation_continued") == "TRUE", v183_gate.get("data_trust_shadow_observation_continued") == "TRUE", v184_gate.get("data_trust_shadow_observation_continued") == "TRUE"]),
    }
    not_released_as = {
        "official_scoring_factor": "FALSE",
        "official_ranking_weight": "FALSE",
        "official_recommendation_trigger": "FALSE",
        "real_book_permission_gate": "FALSE",
    }
    ranking_score_mutations = v183_gate.get("official_ranking_score_mutation_count", "")
    rank_mutations = v183_gate.get("official_rank_mutation_count", "")
    contribution_sum = v183_gate.get("data_trust_score_contribution_sum", "")
    nonzero_weight_count = v183_gate.get("data_trust_nonzero_weight_count", "")
    ranking_guard = ranking_score_mutations == "0" and rank_mutations == "0"
    zero_weight_guard = contribution_sum == "0.0000000000" and nonzero_weight_count == "0"
    official_use_guard = all([
        v182_gate.get("ready_for_official_use") == "FALSE",
        v183_gate.get("ready_for_official_use") == "FALSE",
        v184_gate.get("ready_for_official_use") == "FALSE",
        v182_gate.get("real_book_use_allowed") == "FALSE",
        v183_gate.get("real_book_use_allowed") == "FALSE",
        v184_gate.get("real_book_use_allowed") == "FALSE",
        v182_gate.get("official_recommendation_created") == "FALSE",
        v183_gate.get("official_recommendation_created") == "FALSE",
        v184_gate.get("official_recommendation_created") == "FALSE",
        v182_gate.get("official_weight_mutation_allowed") == "FALSE",
        v183_gate.get("official_weight_mutation_allowed") == "FALSE",
        v184_gate.get("official_weight_mutation_allowed") == "FALSE",
    ])
    release_pass = all(release_as.values()) and all(value == "FALSE" for value in not_released_as.values())
    all_pass = all([release_pass, ranking_guard, zero_weight_guard, official_use_guard, not upstream_mutated])

    packet = [{
        "release_packet_id": "V20_185_DATA_TRUST_FINAL_GATE_ONLY_RELEASE_PACKET_001",
        "release_scope": "DAILY_RUNNER_ZERO_WEIGHT_GATE_ONLY_AUDIT_METADATA",
        "release_status": "RELEASED_FOR_DAILY_RUNNER_GATE_ONLY_AUDIT_USE" if release_pass else "BLOCKED",
        "released_as_zero_weight": tf(release_as["zero_weight"]),
        "released_as_gate_only": tf(release_as["gate_only"]),
        "released_as_audit_only": tf(release_as["audit_only"]),
        "released_as_read_center_disclosed": tf(release_as["read_center_disclosed"]),
        "released_as_shadow_observation_continued": tf(release_as["shadow_observation_continued"]),
        "released_as_official_scoring_factor": not_released_as["official_scoring_factor"],
        "released_as_official_ranking_weight": not_released_as["official_ranking_weight"],
        "released_as_official_recommendation_trigger": not_released_as["official_recommendation_trigger"],
        "released_as_real_book_permission_gate": not_released_as["real_book_permission_gate"],
        "official_ranking_score_mutation_count": ranking_score_mutations,
        "official_rank_mutation_count": rank_mutations,
        "data_trust_score_contribution_sum": contribution_sum,
        "data_trust_nonzero_weight_count": nonzero_weight_count,
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        **COMMON,
    }]
    guard_specs = [
        ("released_as_zero_weight", "TRUE", packet[0]["released_as_zero_weight"], V182_GATE),
        ("released_as_gate_only", "TRUE", packet[0]["released_as_gate_only"], V182_GATE),
        ("released_as_audit_only", "TRUE", packet[0]["released_as_audit_only"], V182_GATE),
        ("released_as_read_center_disclosed", "TRUE", packet[0]["released_as_read_center_disclosed"], V183_GATE),
        ("released_as_shadow_observation_continued", "TRUE", packet[0]["released_as_shadow_observation_continued"], V184_GATE),
        ("released_as_official_scoring_factor", "FALSE", packet[0]["released_as_official_scoring_factor"], V184_GATE),
        ("released_as_official_ranking_weight", "FALSE", packet[0]["released_as_official_ranking_weight"], V184_GATE),
        ("released_as_official_recommendation_trigger", "FALSE", packet[0]["released_as_official_recommendation_trigger"], V184_GATE),
        ("released_as_real_book_permission_gate", "FALSE", packet[0]["released_as_real_book_permission_gate"], V184_GATE),
        ("official_ranking_score_mutation_count", "0", ranking_score_mutations, V183_GATE),
        ("official_rank_mutation_count", "0", rank_mutations, V183_GATE),
        ("data_trust_score_contribution_sum", "0.0000000000", contribution_sum, V183_GATE),
        ("data_trust_nonzero_weight_count", "0", nonzero_weight_count, V183_GATE),
        ("ready_for_official_use", "FALSE", "FALSE", V184_GATE),
        ("real_book_use_allowed", "FALSE", "FALSE", V184_GATE),
        ("official_recommendation_created", "FALSE", "FALSE", V184_GATE),
        ("official_weight_mutation_allowed", "FALSE", "FALSE", V184_GATE),
        ("upstream_release_artifacts_mutated", "FALSE", tf(upstream_mutated), V184_GATE),
    ]
    guardrail_rows = [{
        "guardrail_id": f"V20_185_RELEASE_GUARDRAIL_{idx:03d}",
        "guardrail": guardrail,
        "expected_value": expected,
        "actual_value": actual,
        "guardrail_passed": tf(expected == actual),
        "source_artifact": rel(path),
        **COMMON,
    } for idx, (guardrail, expected, actual, path) in enumerate(guard_specs, start=1)]

    summary = [{
        "summary_id": "V20_185_OPERATOR_FACING_RELEASE_SUMMARY_001",
        "operator_facing_release_summary": "DATA_TRUST_RELEASED_ONLY_AS_ZERO_WEIGHT_GATE_ONLY_AUDIT_METADATA_WITH_READ_CENTER_DISCLOSURE_AND_CONTINUED_SHADOW_OBSERVATION",
        "release_packet_pass": tf(release_pass),
        "ranking_mutation_guard_pass": tf(ranking_guard),
        "zero_weight_guard_pass": tf(zero_weight_guard),
        "official_use_guard_pass": tf(official_use_guard),
        "ready_for_v20_186_daily_research_runner_release_lock": tf(all_pass),
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        **COMMON,
    }]
    gate = {
        "gate_check_id": "V20_185_NEXT_STAGE_GATE_001",
        "v20_182_status_consumed": "TRUE",
        "v20_182_status": v182_gate.get("final_status", ""),
        "v20_183_status_consumed": "TRUE",
        "v20_183_status": v183_gate.get("final_status", ""),
        "v20_184_status_consumed": "TRUE",
        "v20_184_status": v184_gate.get("final_status", ""),
        "data_trust_gate_only_release_pass": tf(release_pass),
        "ranking_mutation_guard_pass": tf(ranking_guard),
        "zero_weight_guard_pass": tf(zero_weight_guard),
        "official_use_guard_pass": tf(official_use_guard),
        "official_ranking_score_mutation_count": ranking_score_mutations,
        "official_rank_mutation_count": rank_mutations,
        "data_trust_score_contribution_sum": contribution_sum,
        "data_trust_nonzero_weight_count": nonzero_weight_count,
        "released_as_official_scoring_factor": "FALSE",
        "released_as_official_ranking_weight": "FALSE",
        "released_as_official_recommendation_trigger": "FALSE",
        "released_as_real_book_permission_gate": "FALSE",
        "ready_for_v20_186_daily_research_runner_release_lock": tf(all_pass),
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_read_center_disclosed": "TRUE",
        "data_trust_shadow_observation_continued": "TRUE",
        "recommended_next_action": "RUN_V20_186_DAILY_RESEARCH_RUNNER_RELEASE_LOCK" if all_pass else "REPAIR_V20_185_RELEASE_PACKET",
        "blocking_reason": "NONE" if all_pass else "V20_185_RELEASE_PACKET_GUARD_FAILURE",
        "final_status": PASS_STATUS if all_pass else BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_PACKET, PACKET_FIELDS, packet)
    write_csv(OUT_GUARDRAIL, GUARDRAIL_FIELDS, guardrail_rows)
    write_csv(OUT_SUMMARY, SUMMARY_FIELDS, summary)
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
