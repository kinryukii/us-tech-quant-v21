#!/usr/bin/env python
"""V20.184 daily research runner operator readability review."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"

V183_AUDIT = FACTORS / "V20_183_DATA_TRUST_READ_CENTER_INTEGRATION_AUDIT.csv"
V183_SAMPLE = FACTORS / "V20_183_DATA_TRUST_READ_CENTER_DISPLAY_SAMPLE.csv"
V183_GUARD = FACTORS / "V20_183_OFFICIAL_USE_GUARD_AUDIT.csv"
V183_GATE = FACTORS / "V20_183_NEXT_STAGE_GATE.csv"
V183_REPORT = READ_CENTER / "V20_183_DAILY_RESEARCH_RUNNER_READ_CENTER_INTEGRATION_REPORT.md"

PROTECTED = [V183_AUDIT, V183_SAMPLE, V183_GUARD, V183_GATE, V183_REPORT]

OUT_READABILITY = FACTORS / "V20_184_OPERATOR_READABILITY_AUDIT.csv"
OUT_MISLEADING = FACTORS / "V20_184_DATA_TRUST_MISLEADING_LANGUAGE_AUDIT.csv"
OUT_RECOMMENDATION = FACTORS / "V20_184_OPERATOR_DISPLAY_RECOMMENDATION.csv"
OUT_GATE = FACTORS / "V20_184_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_184_DAILY_RESEARCH_RUNNER_OPERATOR_READABILITY_REVIEW_REPORT.md"

READY_V183 = "PASS_V20_183_DAILY_RESEARCH_RUNNER_READ_CENTER_INTEGRATION_READY_FOR_V20_184_OPERATOR_READABILITY_REVIEW"
PASS_STATUS = "PASS_V20_184_DAILY_RESEARCH_RUNNER_OPERATOR_READABILITY_REVIEW_READY_FOR_V20_185_RELEASE_PACKET"
BLOCKED_STATUS = "BLOCKED_V20_184_DAILY_RESEARCH_RUNNER_OPERATOR_READABILITY_REVIEW"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DAILY_RESEARCH_RUNNER_OPERATOR_READABILITY_REVIEW"

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

READABILITY_FIELDS = [
    "readability_check_id", "operator_display_area", "readability_check",
    "expected_value", "actual_value", "readability_check_passed",
    "source_artifact", "operator_review_note", *COMMON.keys(),
]
MISLEADING_FIELDS = [
    "misleading_check_id", "misleading_language_check", "prohibited_implication",
    "detected_count", "misleading_language_detected", "guard_passed",
    "source_artifact", *COMMON.keys(),
]
RECOMMENDATION_FIELDS = [
    "recommendation_id", "operator_display_recommendation", "recommended_action",
    "recommendation_status", "readability_pass", "misleading_language_guard_pass",
    "official_use_disclosure_pass", "ready_for_release_packet",
    "ready_for_official_use", "real_book_use_allowed",
    "official_recommendation_created", "official_weight_mutation_allowed",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_183_status_consumed", "v20_183_status",
    "display_candidate_count", "readability_pass", "misleading_language_guard_pass",
    "official_use_disclosure_pass", "candidate_level_status_present",
    "aggregate_status_present", "official_ranking_score_participation_implied",
    "rank_order_change_implied", "real_book_or_official_recommendation_permission_implied",
    "ready_for_v20_185_daily_runner_final_gate_only_release_packet",
    "ready_for_official_use", "real_book_use_allowed", "official_recommendation_created",
    "official_weight_mutation_allowed", "data_trust_zero_weight", "data_trust_gate_only",
    "data_trust_audit_only", "data_trust_shadow_observation_continued",
    "recommended_next_action", "blocking_reason", "final_status", *COMMON.keys(),
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


def contains_any(text: str, phrases: list[str]) -> int:
    lowered = text.lower()
    return sum(lowered.count(phrase.lower()) for phrase in phrases)


def write_report(gate: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.184 Daily Research Runner Operator Readability Review Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- readability_pass: {gate['readability_pass']}",
        f"- misleading_language_guard_pass: {gate['misleading_language_guard_pass']}",
        f"- official_use_disclosure_pass: {gate['official_use_disclosure_pass']}",
        f"- ready_for_v20_185_daily_runner_final_gate_only_release_packet: {gate['ready_for_v20_185_daily_runner_final_gate_only_release_packet']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        f"- real_book_use_allowed: {gate['real_book_use_allowed']}",
        f"- official_recommendation_created: {gate['official_recommendation_created']}",
        f"- official_weight_mutation_allowed: {gate['official_weight_mutation_allowed']}",
        "",
        "Operator readability review confirms DATA_TRUST is shown as zero-weight, gate-only, audit-only metadata with continued shadow observation. The display does not imply official score participation, rank-order changes, real-book permission, or official recommendation permission.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [(OUT_READABILITY, READABILITY_FIELDS), (OUT_MISLEADING, MISLEADING_FIELDS), (OUT_RECOMMENDATION, RECOMMENDATION_FIELDS)]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_184_NEXT_STAGE_GATE_001",
        "v20_183_status_consumed": "FALSE",
        "v20_183_status": "",
        "display_candidate_count": "0",
        "readability_pass": "FALSE",
        "misleading_language_guard_pass": "FALSE",
        "official_use_disclosure_pass": "FALSE",
        "candidate_level_status_present": "FALSE",
        "aggregate_status_present": "FALSE",
        "official_ranking_score_participation_implied": "FALSE",
        "rank_order_change_implied": "FALSE",
        "real_book_or_official_recommendation_permission_implied": "FALSE",
        "ready_for_v20_185_daily_runner_final_gate_only_release_packet": "FALSE",
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_shadow_observation_continued": "TRUE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_V20_184",
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
    datasets = {path: read_csv(path)[0] for path in [V183_AUDIT, V183_SAMPLE, V183_GUARD, V183_GATE]}
    if any(not rows for rows in datasets.values()) or not V183_REPORT.exists():
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    audit_rows = datasets[V183_AUDIT]
    sample_rows = datasets[V183_SAMPLE]
    guard_rows = datasets[V183_GUARD]
    v183_gate = datasets[V183_GATE][0]
    if not all([
        v183_gate.get("final_status") == READY_V183,
        v183_gate.get("ready_for_v20_184_daily_research_runner_operator_readability_review") == "TRUE",
        v183_gate.get("ready_for_official_use") == "FALSE",
    ]):
        return emit_blocked("V20_183_REQUIREMENTS_NOT_MET")

    report_text = V183_REPORT.read_text(encoding="utf-8")
    candidate_level_status = all([
        len(sample_rows) == 40,
        all(row.get("data_trust_direct_status_summary") == "PASS" for row in sample_rows),
        all(row.get("data_trust_gate_only_status") == "TRUE" for row in sample_rows),
        all(row.get("data_trust_zero_weight_status") == "TRUE" for row in sample_rows),
        all(row.get("data_trust_audit_only_status") == "TRUE" for row in sample_rows),
        all(row.get("data_trust_shadow_observation_status") == "TRUE" for row in sample_rows),
        all(row.get("data_trust_score_contribution") == "0.0000000000" for row in sample_rows),
        all(row.get("data_trust_weight") == "0.0000000000" for row in sample_rows),
    ])
    aggregate_status = all([
        v183_gate.get("data_trust_zero_weight") == "TRUE",
        v183_gate.get("data_trust_gate_only") == "TRUE",
        v183_gate.get("data_trust_audit_only") == "TRUE",
        v183_gate.get("data_trust_shadow_observation_continued") == "TRUE",
        v183_gate.get("data_trust_score_contribution_sum") == "0.0000000000",
        v183_gate.get("data_trust_nonzero_weight_count") == "0",
        all(row.get("integration_check_passed") == "TRUE" for row in audit_rows),
    ])
    official_use_disclosure = all([
        v183_gate.get("ready_for_official_use") == "FALSE",
        v183_gate.get("real_book_use_allowed") == "FALSE",
        v183_gate.get("official_recommendation_created") == "FALSE",
        v183_gate.get("official_weight_mutation_allowed") == "FALSE",
        all(row.get("official_use_status") == "DISABLED" for row in sample_rows),
        all(row.get("real_book_use_status") == "DISABLED" for row in sample_rows),
        all(row.get("official_recommendation_status") == "DISABLED" for row in sample_rows),
        all(row.get("official_weight_mutation_status") == "DISABLED" for row in sample_rows),
        all(row.get("guard_passed") == "TRUE" for row in guard_rows),
    ])

    readability_specs = [
        ("CANDIDATE_LEVEL_DATA_TRUST_DIRECT_STATUS", "TRUE", tf(all(row.get("data_trust_direct_status_summary") == "PASS" for row in sample_rows)), V183_SAMPLE, "Candidate rows expose direct status."),
        ("CANDIDATE_LEVEL_GATE_ONLY_STATUS", "TRUE", tf(all(row.get("data_trust_gate_only_status") == "TRUE" for row in sample_rows)), V183_SAMPLE, "Candidate rows expose gate-only status."),
        ("CANDIDATE_LEVEL_ZERO_WEIGHT_STATUS", "TRUE", tf(all(row.get("data_trust_zero_weight_status") == "TRUE" for row in sample_rows)), V183_SAMPLE, "Candidate rows expose zero-weight status."),
        ("CANDIDATE_LEVEL_AUDIT_ONLY_STATUS", "TRUE", tf(all(row.get("data_trust_audit_only_status") == "TRUE" for row in sample_rows)), V183_SAMPLE, "Candidate rows expose audit-only status."),
        ("CANDIDATE_LEVEL_SHADOW_OBSERVATION_STATUS", "TRUE", tf(all(row.get("data_trust_shadow_observation_status") == "TRUE" for row in sample_rows)), V183_SAMPLE, "Candidate rows expose shadow observation continuation."),
        ("AGGREGATE_DATA_TRUST_SUMMARY", "TRUE", tf(aggregate_status), V183_GATE, "Aggregate read-center gate exposes closeout summary."),
        ("OFFICIAL_USE_DISABLED_STATUS", "TRUE", tf(official_use_disclosure), V183_SAMPLE, "Official-use disabled labels are visible."),
        ("CONTRIBUTION_AND_WEIGHT_ARE_ZERO", "TRUE", tf(all(row.get("data_trust_score_contribution") == "0.0000000000" and row.get("data_trust_weight") == "0.0000000000" for row in sample_rows)), V183_SAMPLE, "Display makes zero contribution and weight explicit."),
    ]
    readability_rows = [{
        "readability_check_id": f"V20_184_READABILITY_{idx:03d}",
        "operator_display_area": "DATA_TRUST_READ_CENTER_DISPLAY",
        "readability_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "readability_check_passed": tf(expected == actual),
        "source_artifact": rel(path),
        "operator_review_note": note,
        **COMMON,
    } for idx, (check, expected, actual, path, note) in enumerate(readability_specs, start=1)]
    readability_pass = all(row["readability_check_passed"] == "TRUE" for row in readability_rows)

    display_text = "\n".join(
        ",".join(row.get(field, "") for field in [
            "ticker", "data_trust_direct_status_summary", "data_trust_gate_only_status",
            "data_trust_zero_weight_status", "data_trust_audit_only_status",
            "data_trust_shadow_observation_status", "official_use_status",
            "real_book_use_status", "official_recommendation_status",
            "official_weight_mutation_status", "data_trust_score_contribution",
            "data_trust_weight",
        ])
        for row in sample_rows
    ) + "\n" + report_text
    misleading_specs = [
        ("OFFICIAL_SCORE_PARTICIPATION", "DATA_TRUST participates in official ranking score", contains_any(display_text, ["data_trust official score active", "data_trust score contribution nonzero", "data_trust contributes to official score"]), V183_SAMPLE),
        ("RANK_ORDER_CHANGE", "DATA_TRUST changes rank order", contains_any(display_text, ["data_trust changed rank", "rank changed by data_trust", "reranked by data_trust"]), V183_SAMPLE),
        ("REAL_BOOK_PERMISSION", "Real-book use is permitted", contains_any(display_text, ["real book allowed", "real-book allowed", "real_book_use_status,enabled", "real_book_use_allowed=true"]), V183_SAMPLE),
        ("OFFICIAL_RECOMMENDATION_PERMISSION", "Official recommendation is permitted", contains_any(display_text, ["official recommendation allowed", "official recommendation created true", "official_recommendation_status,enabled", "official_recommendation_created=true"]), V183_SAMPLE),
        ("OFFICIAL_WEIGHT_MUTATION_PERMISSION", "Official weight mutation is permitted", contains_any(display_text, ["official weight mutation allowed", "official_weight_mutation_status,enabled", "official_weight_mutation_allowed=true"]), V183_SAMPLE),
    ]
    misleading_rows = [{
        "misleading_check_id": f"V20_184_MISLEADING_{idx:03d}",
        "misleading_language_check": check,
        "prohibited_implication": implication,
        "detected_count": str(count),
        "misleading_language_detected": tf(count > 0),
        "guard_passed": tf(count == 0),
        "source_artifact": rel(path),
        **COMMON,
    } for idx, (check, implication, count, path) in enumerate(misleading_specs, start=1)]
    misleading_language_guard_pass = all(row["guard_passed"] == "TRUE" for row in misleading_rows)
    upstream_mutated = before != protected_hashes()
    all_pass = all([readability_pass, misleading_language_guard_pass, official_use_disclosure, not upstream_mutated])

    recommendation_rows = [{
        "recommendation_id": "V20_184_OPERATOR_DISPLAY_RECOMMENDATION_001",
        "operator_display_recommendation": "KEEP_DATA_TRUST_READ_CENTER_STATUS_VISIBLE_AS_ZERO_WEIGHT_GATE_ONLY_AUDIT_METADATA",
        "recommended_action": "PROCEED_TO_V20_185_DAILY_RUNNER_FINAL_GATE_ONLY_RELEASE_PACKET" if all_pass else "REPAIR_OPERATOR_READABILITY_OR_MISLEADING_LANGUAGE",
        "recommendation_status": "APPROVED_FOR_RELEASE_PACKET" if all_pass else "BLOCKED",
        "readability_pass": tf(readability_pass),
        "misleading_language_guard_pass": tf(misleading_language_guard_pass),
        "official_use_disclosure_pass": tf(official_use_disclosure),
        "ready_for_release_packet": tf(all_pass),
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        **COMMON,
    }]
    gate = {
        "gate_check_id": "V20_184_NEXT_STAGE_GATE_001",
        "v20_183_status_consumed": "TRUE",
        "v20_183_status": v183_gate.get("final_status", ""),
        "display_candidate_count": str(len(sample_rows)),
        "readability_pass": tf(readability_pass),
        "misleading_language_guard_pass": tf(misleading_language_guard_pass),
        "official_use_disclosure_pass": tf(official_use_disclosure),
        "candidate_level_status_present": tf(candidate_level_status),
        "aggregate_status_present": tf(aggregate_status),
        "official_ranking_score_participation_implied": tf(any(row["misleading_language_check"] == "OFFICIAL_SCORE_PARTICIPATION" and row["misleading_language_detected"] == "TRUE" for row in misleading_rows)),
        "rank_order_change_implied": tf(any(row["misleading_language_check"] == "RANK_ORDER_CHANGE" and row["misleading_language_detected"] == "TRUE" for row in misleading_rows)),
        "real_book_or_official_recommendation_permission_implied": tf(any(row["misleading_language_check"] in {"REAL_BOOK_PERMISSION", "OFFICIAL_RECOMMENDATION_PERMISSION"} and row["misleading_language_detected"] == "TRUE" for row in misleading_rows)),
        "ready_for_v20_185_daily_runner_final_gate_only_release_packet": tf(all_pass),
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_shadow_observation_continued": "TRUE",
        "recommended_next_action": "RUN_V20_185_DAILY_RUNNER_FINAL_GATE_ONLY_RELEASE_PACKET" if all_pass else "REPAIR_V20_184_OPERATOR_READABILITY_REVIEW",
        "blocking_reason": "NONE" if all_pass else "V20_184_OPERATOR_READABILITY_GUARD_FAILURE",
        "final_status": PASS_STATUS if all_pass else BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_READABILITY, READABILITY_FIELDS, readability_rows)
    write_csv(OUT_MISLEADING, MISLEADING_FIELDS, misleading_rows)
    write_csv(OUT_RECOMMENDATION, RECOMMENDATION_FIELDS, recommendation_rows)
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
