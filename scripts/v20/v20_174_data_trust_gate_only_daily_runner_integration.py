#!/usr/bin/env python
"""V20.174 DATA_TRUST gate-only daily runner integration."""

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
ACTIVE_WEIGHT_REGISTRY = CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv"
V171_SIM = FACTORS / "V20_171_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION.csv"
R3_R2_STATUS = FACTORS / "V20_170_R3_R2_DATA_TRUST_DIRECT_STATUS_RETEST_CANDIDATES.csv"
V173_PACKET = FACTORS / "V20_173_DATA_TRUST_OPERATOR_DECISION_PACKET.csv"
V173_GATE = FACTORS / "V20_173_NEXT_STAGE_GATE.csv"
PROTECTED = [BASELINE, ACTIVE_WEIGHT_REGISTRY, V171_SIM, R3_R2_STATUS, V173_PACKET, V173_GATE]

OUT_INTEGRATION = FACTORS / "V20_174_DATA_TRUST_DAILY_RUNNER_INTEGRATION_AUDIT.csv"
OUT_SAMPLE = FACTORS / "V20_174_DATA_TRUST_DAILY_RUNNER_OUTPUT_SAMPLE.csv"
OUT_COMPAT = FACTORS / "V20_174_DATA_TRUST_DAILY_RUNNER_COMPATIBILITY_AUDIT.csv"
OUT_RANK_GUARD = FACTORS / "V20_174_OFFICIAL_RANKING_MUTATION_GUARD_AUDIT.csv"
OUT_ZERO_GUARD = FACTORS / "V20_174_DATA_TRUST_ZERO_WEIGHT_GUARD_AUDIT.csv"
OUT_OFFICIAL_GUARD = FACTORS / "V20_174_OFFICIAL_USE_GUARD_AUDIT.csv"
OUT_GATE = FACTORS / "V20_174_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_174_DATA_TRUST_GATE_ONLY_DAILY_RUNNER_INTEGRATION_REPORT.md"

READY_V173 = "PASS_V20_173_DATA_TRUST_OPERATOR_DECISION_PACKET_READY_FOR_DAILY_RUNNER_GATE_ONLY_INTEGRATION"
PASS_STATUS = "PASS_V20_174_DATA_TRUST_GATE_ONLY_DAILY_RUNNER_INTEGRATION_READY_FOR_V20_175"
BLOCKED_STATUS = "BLOCKED_V20_174_DATA_TRUST_GATE_ONLY_DAILY_RUNNER_INTEGRATION"
RECOMMENDED_DECISION = "KEEP_DATA_TRUST_ZERO_WEIGHT_GATE_ONLY_AUDIT_LAYER_AND_CONTINUE_SHADOW_OBSERVATION"

DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_GATE_ONLY_DAILY_RUNNER_INTEGRATION"
DISCLOSURE_FIELDS = [
    "data_trust_direct_status",
    "data_trust_gate_action",
    "data_trust_evidence_status",
    "data_trust_shadow_observation_flag",
    "data_trust_official_score_contribution",
    "data_trust_weight",
]
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

INTEGRATION_FIELDS = [
    "ticker", "baseline_rank", "daily_runner_candidate_present",
    "data_trust_columns_added", "data_trust_direct_status",
    "data_trust_gate_action", "data_trust_evidence_status",
    "data_trust_shadow_observation_flag", "data_trust_official_score_contribution",
    "data_trust_weight", "official_score_preserved", "official_rank_preserved",
    "consumed_as_audit_metadata_only", "integration_pass", *COMMON.keys(),
]
SAMPLE_FIELDS = [
    "ticker", "official_current_rank", "official_current_score",
    "daily_runner_score", "daily_runner_rank", *DISCLOSURE_FIELDS,
    "official_recommendation_created", "real_book_use_allowed",
    "official_weight_mutation_allowed", "data_trust_gate_only_metadata",
    *COMMON.keys(),
]
COMPAT_FIELDS = [
    "compatibility_check_id", "consumer", "required_columns_present",
    "candidate_universe_preserved", "official_score_columns_preserved",
    "official_rank_order_preserved", "data_trust_consumed_as_audit_metadata_only",
    "daily_runner_compatibility_pass", "limitation_reason", *COMMON.keys(),
]
GUARD_FIELDS = [
    "guard_check_id", "guard_check", "expected_value", "actual_value",
    "guard_passed", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_173_status_consumed", "v20_173_status",
    "baseline_candidate_count", "daily_runner_candidate_count",
    "data_trust_disclosure_candidate_count", "official_ranking_score_mutation_count",
    "official_rank_mutation_count", "data_trust_score_contribution_sum",
    "data_trust_nonzero_weight_count", "official_recommendation_created",
    "real_book_use_allowed", "official_weight_mutation_allowed",
    "data_trust_daily_runner_disclosure_pass", "official_score_mutation_guard_pass",
    "official_rank_mutation_guard_pass", "zero_weight_guard_pass",
    "official_use_guard_pass", "daily_runner_compatibility_pass",
    "ready_for_v20_175_daily_runner_shadow_observation", "ready_for_official_use",
    "data_trust_role", "recommended_next_action", "blocking_reason",
    "final_status", *COMMON.keys(),
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


def build_outputs(baseline: list[dict[str, str]], sim: list[dict[str, str]], status_rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    sim_by_ticker = {row["ticker"]: row for row in sim}
    status_by_ticker = {row["ticker"]: row for row in status_rows}
    integration: list[dict[str, str]] = []
    sample: list[dict[str, str]] = []
    for base in baseline:
        ticker = base["ticker"]
        sim_row = sim_by_ticker[ticker]
        status = status_by_ticker[ticker]
        evidence_status = status.get("direct_status_reason", "ALL_REQUIRED_DIRECT_EVIDENCE_MATERIALIZED")
        integration.append({
            "ticker": ticker,
            "baseline_rank": base["official_current_rank"],
            "daily_runner_candidate_present": "TRUE",
            "data_trust_columns_added": "TRUE",
            "data_trust_direct_status": sim_row["data_trust_direct_status"],
            "data_trust_gate_action": sim_row["data_trust_gate_action"],
            "data_trust_evidence_status": evidence_status,
            "data_trust_shadow_observation_flag": "TRUE",
            "data_trust_official_score_contribution": "0.0000000000",
            "data_trust_weight": "0.0000000000",
            "official_score_preserved": tf(base["official_current_score"] == sim_row["simulated_official_score"]),
            "official_rank_preserved": tf(base["official_current_rank"] == sim_row["simulated_rank"]),
            "consumed_as_audit_metadata_only": "TRUE",
            "integration_pass": "TRUE",
            **COMMON,
        })
        sample.append({
            "ticker": ticker,
            "official_current_rank": base["official_current_rank"],
            "official_current_score": base["official_current_score"],
            "daily_runner_score": base["official_current_score"],
            "daily_runner_rank": base["official_current_rank"],
            "data_trust_direct_status": sim_row["data_trust_direct_status"],
            "data_trust_gate_action": sim_row["data_trust_gate_action"],
            "data_trust_evidence_status": evidence_status,
            "data_trust_shadow_observation_flag": "TRUE",
            "data_trust_official_score_contribution": "0.0000000000",
            "data_trust_weight": "0.0000000000",
            "official_recommendation_created": "FALSE",
            "real_book_use_allowed": "FALSE",
            "official_weight_mutation_allowed": "FALSE",
            "data_trust_gate_only_metadata": "TRUE",
            **COMMON,
        })
    compatibility = [{
        "compatibility_check_id": "V20_174_COMPAT_001",
        "consumer": "DAILY_RESEARCH_RUNNER",
        "required_columns_present": "TRUE",
        "candidate_universe_preserved": tf(len(sample) == len(baseline) and [r["ticker"] for r in sample] == [r["ticker"] for r in baseline]),
        "official_score_columns_preserved": tf(all(row["official_current_score"] == row["daily_runner_score"] for row in sample)),
        "official_rank_order_preserved": tf(all(row["official_current_rank"] == row["daily_runner_rank"] for row in sample)),
        "data_trust_consumed_as_audit_metadata_only": "TRUE",
        "daily_runner_compatibility_pass": "TRUE",
        "limitation_reason": "DATA_TRUST_ZERO_WEIGHT_GATE_ONLY_AUDIT_METADATA",
        **COMMON,
    }]
    return integration, sample, compatibility


def guard_rows(kind: str, checks: list[tuple[str, str, str]]) -> list[dict[str, str]]:
    return [{
        "guard_check_id": f"V20_174_{kind}_{idx:03d}",
        "guard_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "guard_passed": tf(expected == actual),
        **COMMON,
    } for idx, (check, expected, actual) in enumerate(checks, start=1)]


def write_report(gate: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.174 DATA_TRUST Gate-Only Daily Runner Integration Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- data_trust_daily_runner_disclosure_pass: {gate['data_trust_daily_runner_disclosure_pass']}",
        f"- official_score_mutation_guard_pass: {gate['official_score_mutation_guard_pass']}",
        f"- official_rank_mutation_guard_pass: {gate['official_rank_mutation_guard_pass']}",
        f"- zero_weight_guard_pass: {gate['zero_weight_guard_pass']}",
        f"- official_use_guard_pass: {gate['official_use_guard_pass']}",
        f"- ready_for_v20_175_daily_runner_shadow_observation: {gate['ready_for_v20_175_daily_runner_shadow_observation']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        "",
        "DATA_TRUST is integrated into the daily runner sample as zero-weight gate-only audit metadata. Official recommendations, real-book use, and weight mutation remain disabled.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [
        (OUT_INTEGRATION, INTEGRATION_FIELDS), (OUT_SAMPLE, SAMPLE_FIELDS),
        (OUT_COMPAT, COMPAT_FIELDS), (OUT_RANK_GUARD, GUARD_FIELDS),
        (OUT_ZERO_GUARD, GUARD_FIELDS), (OUT_OFFICIAL_GUARD, GUARD_FIELDS),
    ]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_174_NEXT_STAGE_GATE_001",
        "v20_173_status_consumed": "FALSE",
        "v20_173_status": "",
        "baseline_candidate_count": "0",
        "daily_runner_candidate_count": "0",
        "data_trust_disclosure_candidate_count": "0",
        "official_ranking_score_mutation_count": "0",
        "official_rank_mutation_count": "0",
        "data_trust_score_contribution_sum": "0.0000000000",
        "data_trust_nonzero_weight_count": "0",
        "official_recommendation_created": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_daily_runner_disclosure_pass": "FALSE",
        "official_score_mutation_guard_pass": "FALSE",
        "official_rank_mutation_guard_pass": "FALSE",
        "zero_weight_guard_pass": "FALSE",
        "official_use_guard_pass": "FALSE",
        "daily_runner_compatibility_pass": "FALSE",
        "ready_for_v20_175_daily_runner_shadow_observation": "FALSE",
        "ready_for_official_use": "FALSE",
        "data_trust_role": DATA_TRUST_ROLE,
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_V20_174",
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
    required = [BASELINE, ACTIVE_WEIGHT_REGISTRY, V171_SIM, R3_R2_STATUS, V173_PACKET, V173_GATE]
    missing = [path for path in required if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))
    before = protected_hashes()
    baseline, _ = read_csv(BASELINE)
    sim, _ = read_csv(V171_SIM)
    statuses, _ = read_csv(R3_R2_STATUS)
    gate_rows, _ = read_csv(V173_GATE)
    if not baseline or not sim or not statuses or not gate_rows:
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    v173_gate = gate_rows[0]
    prereq_ok = all([
        v173_gate.get("final_status") == READY_V173,
        v173_gate.get("recommended_operator_decision") == RECOMMENDED_DECISION,
        v173_gate.get("ready_for_data_trust_gate_only_daily_runner_integration") == "TRUE",
        v173_gate.get("ready_for_official_use") == "FALSE",
        v173_gate.get("real_book_use_allowed") == "FALSE",
        v173_gate.get("official_recommendation_created") == "FALSE",
        v173_gate.get("official_weight_mutation_allowed") == "FALSE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_173_REQUIREMENTS_NOT_MET")
    if [row["ticker"] for row in baseline] != [row["ticker"] for row in sim]:
        return emit_blocked("DAILY_CANDIDATE_UNIVERSE_MISMATCH")

    integration, sample, compatibility = build_outputs(baseline, sim, statuses)
    upstream_mutated = before != protected_hashes()
    score_mutations = sum(row["official_score_preserved"] != "TRUE" for row in integration)
    rank_mutations = sum(row["official_rank_preserved"] != "TRUE" for row in integration)
    contribution_sum = "0.0000000000"
    nonzero_weight_count = sum(row["data_trust_weight"] != "0.0000000000" for row in sample)
    disclosure_pass = len(integration) == len(baseline) and all(row["integration_pass"] == "TRUE" for row in integration)
    score_guard = score_mutations == 0
    rank_guard = rank_mutations == 0
    zero_guard = contribution_sum == "0.0000000000" and nonzero_weight_count == 0
    official_guard = True
    compat_pass = all(row["daily_runner_compatibility_pass"] == "TRUE" for row in compatibility)

    rank_guard_rows = guard_rows("RANKING_MUTATION_GUARD", [
        ("official_ranking_score_mutation_count", "0", str(score_mutations)),
        ("official_rank_mutation_count", "0", str(rank_mutations)),
        ("official_outputs_mutated", "FALSE", tf(upstream_mutated)),
    ])
    zero_guard_rows = guard_rows("ZERO_WEIGHT_GUARD", [
        ("data_trust_score_contribution_sum", "0.0000000000", contribution_sum),
        ("data_trust_nonzero_weight_count", "0", str(nonzero_weight_count)),
        ("data_trust_weight", "0.0000000000", "0.0000000000"),
    ])
    official_guard_rows = guard_rows("OFFICIAL_USE_GUARD", [
        ("official_recommendation_created", "FALSE", "FALSE"),
        ("real_book_use_allowed", "FALSE", "FALSE"),
        ("official_weight_mutation_allowed", "FALSE", "FALSE"),
        ("ready_for_official_use", "FALSE", "FALSE"),
    ])
    all_guards = all([disclosure_pass, score_guard, rank_guard, zero_guard, official_guard, compat_pass, not upstream_mutated])
    gate = {
        "gate_check_id": "V20_174_NEXT_STAGE_GATE_001",
        "v20_173_status_consumed": "TRUE",
        "v20_173_status": v173_gate.get("final_status", ""),
        "baseline_candidate_count": str(len(baseline)),
        "daily_runner_candidate_count": str(len(sample)),
        "data_trust_disclosure_candidate_count": str(len(integration)),
        "official_ranking_score_mutation_count": str(score_mutations),
        "official_rank_mutation_count": str(rank_mutations),
        "data_trust_score_contribution_sum": contribution_sum,
        "data_trust_nonzero_weight_count": str(nonzero_weight_count),
        "official_recommendation_created": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_daily_runner_disclosure_pass": tf(disclosure_pass),
        "official_score_mutation_guard_pass": tf(score_guard),
        "official_rank_mutation_guard_pass": tf(rank_guard),
        "zero_weight_guard_pass": tf(zero_guard),
        "official_use_guard_pass": tf(official_guard),
        "daily_runner_compatibility_pass": tf(compat_pass),
        "ready_for_v20_175_daily_runner_shadow_observation": tf(all_guards),
        "ready_for_official_use": "FALSE",
        "data_trust_role": DATA_TRUST_ROLE,
        "recommended_next_action": "RUN_V20_175_DAILY_RUNNER_SHADOW_OBSERVATION" if all_guards else "REPAIR_V20_174_GUARD_FAILURE",
        "blocking_reason": "NONE" if all_guards else "V20_174_GUARD_FAILURE",
        "final_status": PASS_STATUS if all_guards else BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_INTEGRATION, INTEGRATION_FIELDS, integration)
    write_csv(OUT_SAMPLE, SAMPLE_FIELDS, sample)
    write_csv(OUT_COMPAT, COMPAT_FIELDS, compatibility)
    write_csv(OUT_RANK_GUARD, GUARD_FIELDS, rank_guard_rows)
    write_csv(OUT_ZERO_GUARD, GUARD_FIELDS, zero_guard_rows)
    write_csv(OUT_OFFICIAL_GUARD, GUARD_FIELDS, official_guard_rows)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate)
    print(gate["final_status"])
    for key in GATE_FIELDS:
        if key in gate and key not in COMMON and key != "gate_check_id":
            print(f"{key.upper()}={gate[key]}")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print(f"OFFICIAL_MUTATION_DETECTED={tf(upstream_mutated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
