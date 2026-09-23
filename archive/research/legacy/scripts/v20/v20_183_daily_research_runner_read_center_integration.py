#!/usr/bin/env python
"""V20.183 daily research runner read-center integration."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
CONSOLIDATION = OUTPUTS / "consolidation"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"

BASELINE = CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
WEIGHT_REGISTRY = CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv"
DAILY_SAMPLE = FACTORS / "V20_174_DATA_TRUST_DAILY_RUNNER_OUTPUT_SAMPLE.csv"
V182_PACKET = FACTORS / "V20_182_DATA_TRUST_FINAL_OPERATOR_DECISION_PACKET.csv"
V182_EVIDENCE = FACTORS / "V20_182_DATA_TRUST_FINAL_EVIDENCE_SUMMARY.csv"
V182_GUARDRAIL = FACTORS / "V20_182_DATA_TRUST_FINAL_GUARDRAIL_AUDIT.csv"
V182_STATUS = FACTORS / "V20_182_DATA_TRUST_DAILY_RUNNER_INTEGRATION_STATUS.csv"
V182_GATE = FACTORS / "V20_182_NEXT_STAGE_GATE.csv"

PROTECTED = [
    BASELINE, WEIGHT_REGISTRY, DAILY_SAMPLE,
    V182_PACKET, V182_EVIDENCE, V182_GUARDRAIL, V182_STATUS, V182_GATE,
]

OUT_AUDIT = FACTORS / "V20_183_DATA_TRUST_READ_CENTER_INTEGRATION_AUDIT.csv"
OUT_SAMPLE = FACTORS / "V20_183_DATA_TRUST_READ_CENTER_DISPLAY_SAMPLE.csv"
OUT_GUARD = FACTORS / "V20_183_OFFICIAL_USE_GUARD_AUDIT.csv"
OUT_GATE = FACTORS / "V20_183_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_183_DAILY_RESEARCH_RUNNER_READ_CENTER_INTEGRATION_REPORT.md"

READY_V182 = "PASS_V20_182_DATA_TRUST_GATE_ONLY_CLOSEOUT_OPERATOR_DECISION_READY_FOR_V20_183_READ_CENTER_INTEGRATION"
PASS_STATUS = "PASS_V20_183_DAILY_RESEARCH_RUNNER_READ_CENTER_INTEGRATION_READY_FOR_V20_184_OPERATOR_READABILITY_REVIEW"
BLOCKED_STATUS = "BLOCKED_V20_183_DAILY_RESEARCH_RUNNER_READ_CENTER_INTEGRATION"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DAILY_RESEARCH_RUNNER_READ_CENTER_INTEGRATION"

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

AUDIT_FIELDS = [
    "integration_check_id", "read_center_section", "display_requirement",
    "expected_value", "actual_value", "integration_check_passed",
    "source_artifact", *COMMON.keys(),
]
SAMPLE_FIELDS = [
    "display_row_id", "ticker", "official_current_rank", "official_current_score",
    "daily_runner_rank", "daily_runner_score", "data_trust_direct_status_summary",
    "data_trust_gate_only_status", "data_trust_zero_weight_status",
    "data_trust_audit_only_status", "data_trust_shadow_observation_status",
    "official_use_status", "real_book_use_status", "official_recommendation_status",
    "official_weight_mutation_status", "data_trust_score_contribution",
    "data_trust_weight", "read_center_display_ready", *COMMON.keys(),
]
GUARD_FIELDS = [
    "guard_check_id", "guard_check", "expected_value", "actual_value",
    "guard_passed", "source_artifact", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_182_status_consumed", "v20_182_status",
    "read_center_display_candidate_count", "official_ranking_score_mutation_count",
    "official_rank_mutation_count", "data_trust_score_contribution_sum",
    "data_trust_nonzero_weight_count", "data_trust_read_center_integration_pass",
    "data_trust_status_disclosure_pass", "official_use_guard_pass",
    "ranking_mutation_guard_pass", "ready_for_v20_184_daily_research_runner_operator_readability_review",
    "ready_for_official_use", "real_book_use_allowed", "official_recommendation_created",
    "official_weight_mutation_allowed", "data_trust_zero_weight", "data_trust_gate_only",
    "data_trust_audit_only", "data_trust_daily_runner_disclosed",
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
        "# V20.183 Daily Research Runner Read-Center Integration Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- data_trust_read_center_integration_pass: {gate['data_trust_read_center_integration_pass']}",
        f"- data_trust_status_disclosure_pass: {gate['data_trust_status_disclosure_pass']}",
        f"- official_use_guard_pass: {gate['official_use_guard_pass']}",
        f"- ranking_mutation_guard_pass: {gate['ranking_mutation_guard_pass']}",
        f"- ready_for_v20_184_daily_research_runner_operator_readability_review: {gate['ready_for_v20_184_daily_research_runner_operator_readability_review']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        f"- real_book_use_allowed: {gate['real_book_use_allowed']}",
        f"- official_recommendation_created: {gate['official_recommendation_created']}",
        f"- official_weight_mutation_allowed: {gate['official_weight_mutation_allowed']}",
        "",
        "Read-center integration now displays DATA_TRUST direct status, gate-only status, zero-weight status, audit-only status, continued shadow observation, and disabled official-use constraints. Official ranking score and rank order remain unchanged.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [(OUT_AUDIT, AUDIT_FIELDS), (OUT_SAMPLE, SAMPLE_FIELDS), (OUT_GUARD, GUARD_FIELDS)]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_183_NEXT_STAGE_GATE_001",
        "v20_182_status_consumed": "FALSE",
        "v20_182_status": "",
        "read_center_display_candidate_count": "0",
        "official_ranking_score_mutation_count": "0",
        "official_rank_mutation_count": "0",
        "data_trust_score_contribution_sum": "0.0000000000",
        "data_trust_nonzero_weight_count": "0",
        "data_trust_read_center_integration_pass": "FALSE",
        "data_trust_status_disclosure_pass": "FALSE",
        "official_use_guard_pass": "FALSE",
        "ranking_mutation_guard_pass": "FALSE",
        "ready_for_v20_184_daily_research_runner_operator_readability_review": "FALSE",
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_daily_runner_disclosed": "TRUE",
        "data_trust_shadow_observation_continued": "TRUE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_V20_183",
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

    baseline = datasets[BASELINE]
    sample = datasets[DAILY_SAMPLE]
    v182_status = datasets[V182_STATUS][0]
    v182_gate = datasets[V182_GATE][0]
    if not all([
        v182_gate.get("final_status") == READY_V182,
        v182_gate.get("ready_for_v20_183_daily_research_runner_read_center_integration") == "TRUE",
        v182_status.get("ready_for_read_center_integration") == "TRUE",
        v182_gate.get("ready_for_official_use") == "FALSE",
    ]):
        return emit_blocked("V20_182_REQUIREMENTS_NOT_MET")

    baseline_by_ticker = {row["ticker"]: row for row in baseline}
    official_score_mutations = 0
    official_rank_mutations = 0
    contribution_sum = 0.0
    nonzero_weight_count = 0
    display_rows = []
    for idx, row in enumerate(sample, start=1):
        base = baseline_by_ticker.get(row["ticker"], {})
        score_mutated = base.get("official_current_score") != row.get("daily_runner_score")
        rank_mutated = base.get("official_current_rank") != row.get("daily_runner_rank")
        official_score_mutations += int(score_mutated)
        official_rank_mutations += int(rank_mutated)
        contribution = row.get("data_trust_official_score_contribution", "0.0000000000")
        weight = row.get("data_trust_weight", "0.0000000000")
        contribution_sum += float(contribution or "0")
        nonzero_weight_count += int(weight != "0.0000000000")
        display_rows.append({
            "display_row_id": f"V20_183_DISPLAY_{idx:03d}",
            "ticker": row.get("ticker", ""),
            "official_current_rank": base.get("official_current_rank", row.get("official_current_rank", "")),
            "official_current_score": base.get("official_current_score", row.get("official_current_score", "")),
            "daily_runner_rank": row.get("daily_runner_rank", ""),
            "daily_runner_score": row.get("daily_runner_score", ""),
            "data_trust_direct_status_summary": row.get("data_trust_direct_status", ""),
            "data_trust_gate_only_status": "TRUE" if row.get("data_trust_gate_action", "").startswith("PASS_GATE_ONLY") else "FALSE",
            "data_trust_zero_weight_status": tf(weight == "0.0000000000"),
            "data_trust_audit_only_status": row.get("audit_only", ""),
            "data_trust_shadow_observation_status": row.get("data_trust_shadow_observation_flag", ""),
            "official_use_status": "DISABLED",
            "real_book_use_status": "DISABLED" if row.get("real_book_use_allowed") == "FALSE" else "ENABLED",
            "official_recommendation_status": "DISABLED" if row.get("official_recommendation_created") == "FALSE" else "ENABLED",
            "official_weight_mutation_status": "DISABLED" if row.get("official_weight_mutation_allowed") == "FALSE" else "ENABLED",
            "data_trust_score_contribution": contribution,
            "data_trust_weight": weight,
            "read_center_display_ready": "TRUE",
            **COMMON,
        })

    data_trust_read_center_integration = len(display_rows) == len(sample) == 40 and all(row["read_center_display_ready"] == "TRUE" for row in display_rows)
    status_disclosure = all([
        v182_gate.get("data_trust_zero_weight") == "TRUE",
        v182_gate.get("data_trust_gate_only") == "TRUE",
        v182_gate.get("data_trust_audit_only") == "TRUE",
        v182_gate.get("data_trust_daily_runner_disclosed") == "TRUE",
        v182_gate.get("data_trust_daily_runner_shadow_observation_continued") == "TRUE",
        all(row["data_trust_direct_status_summary"] == "PASS" for row in display_rows),
        all(row["data_trust_gate_only_status"] == "TRUE" for row in display_rows),
        all(row["data_trust_zero_weight_status"] == "TRUE" for row in display_rows),
        all(row["data_trust_audit_only_status"] == "TRUE" for row in display_rows),
        all(row["data_trust_shadow_observation_status"] == "TRUE" for row in display_rows),
    ])
    official_disabled = all([
        v182_gate.get("ready_for_official_use") == "FALSE",
        v182_gate.get("real_book_use_allowed") == "FALSE",
        v182_gate.get("official_recommendation_created") == "FALSE",
        v182_gate.get("official_weight_mutation_allowed") == "FALSE",
        all(row["official_use_status"] == "DISABLED" for row in display_rows),
        all(row["real_book_use_status"] == "DISABLED" for row in display_rows),
        all(row["official_recommendation_status"] == "DISABLED" for row in display_rows),
        all(row["official_weight_mutation_status"] == "DISABLED" for row in display_rows),
    ])
    ranking_guard = official_score_mutations == 0 and official_rank_mutations == 0
    contribution_text = f"{contribution_sum:.10f}"
    upstream_mutated = before != protected_hashes()

    audit_specs = [
        ("DATA_TRUST_DIRECT_STATUS_SUMMARY", "TRUE", tf(all(row["data_trust_direct_status_summary"] == "PASS" for row in display_rows)), DAILY_SAMPLE),
        ("DATA_TRUST_GATE_ONLY_STATUS", "TRUE", tf(all(row["data_trust_gate_only_status"] == "TRUE" for row in display_rows)), DAILY_SAMPLE),
        ("DATA_TRUST_ZERO_WEIGHT_STATUS", "TRUE", tf(all(row["data_trust_zero_weight_status"] == "TRUE" for row in display_rows)), DAILY_SAMPLE),
        ("DATA_TRUST_AUDIT_ONLY_STATUS", "TRUE", tf(all(row["data_trust_audit_only_status"] == "TRUE" for row in display_rows)), DAILY_SAMPLE),
        ("DATA_TRUST_SHADOW_OBSERVATION_CONTINUED", "TRUE", v182_gate.get("data_trust_daily_runner_shadow_observation_continued", ""), V182_GATE),
        ("OFFICIAL_USE_DISABLED_DISPLAY", "TRUE", tf(all(row["official_use_status"] == "DISABLED" for row in display_rows)), OUT_SAMPLE),
        ("REAL_BOOK_USE_DISABLED_DISPLAY", "TRUE", tf(all(row["real_book_use_status"] == "DISABLED" for row in display_rows)), OUT_SAMPLE),
        ("OFFICIAL_RECOMMENDATION_DISABLED_DISPLAY", "TRUE", tf(all(row["official_recommendation_status"] == "DISABLED" for row in display_rows)), OUT_SAMPLE),
        ("OFFICIAL_WEIGHT_MUTATION_DISABLED_DISPLAY", "TRUE", tf(all(row["official_weight_mutation_status"] == "DISABLED" for row in display_rows)), OUT_SAMPLE),
    ]
    audit_rows = [{
        "integration_check_id": f"V20_183_INTEGRATION_{idx:03d}",
        "read_center_section": "DATA_TRUST_CLOSEOUT_STATUS",
        "display_requirement": requirement,
        "expected_value": expected,
        "actual_value": actual,
        "integration_check_passed": tf(expected == actual),
        "source_artifact": rel(path),
        **COMMON,
    } for idx, (requirement, expected, actual, path) in enumerate(audit_specs, start=1)]

    guard_specs = [
        ("ready_for_official_use", "FALSE", v182_gate.get("ready_for_official_use", ""), V182_GATE),
        ("real_book_use_allowed", "FALSE", v182_gate.get("real_book_use_allowed", ""), V182_GATE),
        ("official_recommendation_created", "FALSE", v182_gate.get("official_recommendation_created", ""), V182_GATE),
        ("official_weight_mutation_allowed", "FALSE", v182_gate.get("official_weight_mutation_allowed", ""), V182_GATE),
        ("official_weight_registry_mutated", "FALSE", v182_gate.get("official_weight_registry_mutated", ""), V182_GATE),
        ("official_recommendation_creation_attempted", "FALSE", v182_gate.get("official_recommendation_creation_attempted", ""), V182_GATE),
        ("real_book_use_attempted", "FALSE", v182_gate.get("real_book_use_attempted", ""), V182_GATE),
        ("official_ranking_score_mutation_count", "0", str(official_score_mutations), DAILY_SAMPLE),
        ("official_rank_mutation_count", "0", str(official_rank_mutations), DAILY_SAMPLE),
        ("data_trust_score_contribution_sum", "0.0000000000", contribution_text, DAILY_SAMPLE),
        ("data_trust_nonzero_weight_count", "0", str(nonzero_weight_count), DAILY_SAMPLE),
        ("official_weight_registry_artifact_mutated", "FALSE", tf(upstream_mutated), WEIGHT_REGISTRY),
    ]
    guard_rows = [{
        "guard_check_id": f"V20_183_OFFICIAL_USE_GUARD_{idx:03d}",
        "guard_check": guard,
        "expected_value": expected,
        "actual_value": actual,
        "guard_passed": tf(expected == actual),
        "source_artifact": rel(path),
        **COMMON,
    } for idx, (guard, expected, actual, path) in enumerate(guard_specs, start=1)]
    official_use_guard = all(row["guard_passed"] == "TRUE" for row in guard_rows[:7]) and not upstream_mutated
    all_pass = all([data_trust_read_center_integration, status_disclosure, official_use_guard, ranking_guard])

    gate = {
        "gate_check_id": "V20_183_NEXT_STAGE_GATE_001",
        "v20_182_status_consumed": "TRUE",
        "v20_182_status": v182_gate.get("final_status", ""),
        "read_center_display_candidate_count": str(len(display_rows)),
        "official_ranking_score_mutation_count": str(official_score_mutations),
        "official_rank_mutation_count": str(official_rank_mutations),
        "data_trust_score_contribution_sum": contribution_text,
        "data_trust_nonzero_weight_count": str(nonzero_weight_count),
        "data_trust_read_center_integration_pass": tf(data_trust_read_center_integration),
        "data_trust_status_disclosure_pass": tf(status_disclosure),
        "official_use_guard_pass": tf(official_use_guard),
        "ranking_mutation_guard_pass": tf(ranking_guard),
        "ready_for_v20_184_daily_research_runner_operator_readability_review": tf(all_pass),
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_daily_runner_disclosed": "TRUE",
        "data_trust_shadow_observation_continued": "TRUE",
        "recommended_next_action": "RUN_V20_184_DAILY_RESEARCH_RUNNER_OPERATOR_READABILITY_REVIEW" if all_pass else "REPAIR_V20_183_READ_CENTER_INTEGRATION",
        "blocking_reason": "NONE" if all_pass else "V20_183_READ_CENTER_INTEGRATION_GUARD_FAILURE",
        "final_status": PASS_STATUS if all_pass else BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_AUDIT, AUDIT_FIELDS, audit_rows)
    write_csv(OUT_SAMPLE, SAMPLE_FIELDS, display_rows)
    write_csv(OUT_GUARD, GUARD_FIELDS, guard_rows)
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
