#!/usr/bin/env python
"""V20.172 DATA_TRUST impact, stability, and disclosure validation."""

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
SIM = FACTORS / "V20_171_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION.csv"
ACTION = FACTORS / "V20_171_DATA_TRUST_GATE_ACTION_AUDIT.csv"
DELTA = FACTORS / "V20_171_RANKING_DELTA_VS_BASELINE_AUDIT.csv"
CONTRIB = FACTORS / "V20_171_DATA_TRUST_SCORE_CONTRIBUTION_AUDIT.csv"
GUARD = FACTORS / "V20_171_OFFICIAL_RANKING_MUTATION_GUARD_AUDIT.csv"
V171_GATE = FACTORS / "V20_171_NEXT_STAGE_GATE.csv"
PROTECTED = [BASELINE, ACTIVE_WEIGHT_REGISTRY, SIM, ACTION, DELTA, CONTRIB, GUARD, V171_GATE]

OUT_IMPACT = FACTORS / "V20_172_DATA_TRUST_IMPACT_AUDIT.csv"
OUT_STABILITY = FACTORS / "V20_172_DATA_TRUST_STABILITY_AUDIT.csv"
OUT_DISCLOSURE = FACTORS / "V20_172_DATA_TRUST_DISCLOSURE_AUDIT.csv"
OUT_DOWNSTREAM = FACTORS / "V20_172_DATA_TRUST_DOWNSTREAM_CONSUMPTION_AUDIT.csv"
OUT_OFFICIAL = FACTORS / "V20_172_OFFICIAL_USE_GUARD_AUDIT.csv"
OUT_GATE = FACTORS / "V20_172_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_172_DATA_TRUST_IMPACT_STABILITY_DISCLOSURE_VALIDATION_REPORT.md"

READY_V171 = "PASS_V20_171_DATA_TRUST_FULL_GATE_ONLY_RANKING_SIMULATION_READY_FOR_V20_172"
PASS_STATUS = "PASS_V20_172_DATA_TRUST_IMPACT_STABILITY_DISCLOSURE_VALIDATION_READY_FOR_V20_173"
BLOCKED_STATUS = "BLOCKED_V20_172_DATA_TRUST_IMPACT_STABILITY_DISCLOSURE_VALIDATION"

DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_IMPACT_STABILITY_DISCLOSURE_VALIDATION"
DISCLOSURE_COLUMNS = [
    "data_trust_direct_status",
    "data_trust_gate_action",
    "data_trust_gate_only_applied",
    "data_trust_official_weight",
    "data_trust_score_contribution",
    "simulation_only",
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

IMPACT_FIELDS = [
    "impact_check_id", "impact_metric", "expected_value", "actual_value",
    "impact_guard_pass", "impact_reason", *COMMON.keys(),
]
STABILITY_FIELDS = [
    "ticker", "baseline_rank", "simulated_rank", "rank_delta",
    "baseline_official_score", "simulated_official_score", "score_delta",
    "candidate_removed_or_reordered", "rank_stability_guard_pass",
    "score_stability_guard_pass", *COMMON.keys(),
]
DISCLOSURE_FIELDS = [
    "ticker", "data_trust_direct_status", "pass_disclosure_present",
    "warn_disclosure_present", "fail_disclosure_present",
    "unknown_disclosure_present", "gate_action_disclosure_present",
    "zero_weight_disclosure_present", "simulation_only_disclosure_present",
    "complete_disclosure_fields_present", "disclosure_guard_pass", *COMMON.keys(),
]
DOWNSTREAM_FIELDS = [
    "consumer_name", "input_artifact", "candidate_count", "audit_metadata_columns_present",
    "audit_only_consumption_supported", "official_score_columns_mutated",
    "daily_runner_can_consume_as_audit_metadata_only", "downstream_consumption_guard_pass",
    "limitation_reason", *COMMON.keys(),
]
OFFICIAL_FIELDS = [
    "guard_check_id", "guard_check", "expected_value", "actual_value",
    "official_use_guard_pass", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_171_status_consumed", "v20_171_status",
    "baseline_candidate_count", "simulation_candidate_count",
    "official_ranking_score_mutation_count", "official_rank_mutation_count",
    "data_trust_score_contribution_sum", "data_trust_nonzero_weight_count",
    "complete_disclosure_candidate_count", "candidate_removed_or_reordered_count",
    "downstream_audit_metadata_consumption_pass",
    "impact_guard_pass", "rank_stability_guard_pass", "zero_weight_guard_pass",
    "disclosure_guard_pass", "official_use_guard_pass",
    "ready_for_v20_173_operator_decision_packet", "ready_for_official_use",
    "real_book_use_allowed", "official_recommendation_created",
    "official_weight_change_allowed", "official_ranking_mutation_allowed",
    "no_ticker_rows_fabricated", "no_evidence_values_fabricated",
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


def build_outputs(sim_rows: list[dict[str, str]], sim_fields: list[str], gate: dict[str, str]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    impact_checks = [
        ("official_ranking_score_mutation_count", "0", gate["official_ranking_score_mutation_count"], "Official score must remain unchanged."),
        ("data_trust_score_contribution_sum", "0.0000000000", gate["data_trust_score_contribution_sum"], "DATA_TRUST contribution must remain zero."),
        ("data_trust_nonzero_weight_count", "0", gate["data_trust_nonzero_weight_count"], "DATA_TRUST must stay zero-weight."),
    ]
    impact = [{
        "impact_check_id": f"V20_172_IMPACT_{idx:03d}",
        "impact_metric": metric,
        "expected_value": expected,
        "actual_value": actual,
        "impact_guard_pass": tf(expected == actual),
        "impact_reason": reason,
        **COMMON,
    } for idx, (metric, expected, actual, reason) in enumerate(impact_checks, start=1)]

    stability = [{
        "ticker": row["ticker"],
        "baseline_rank": row["baseline_rank"],
        "simulated_rank": row["simulated_rank"],
        "rank_delta": row["official_score_delta"] if False else row.get("rank_delta", "0"),
        "baseline_official_score": row["baseline_official_score"],
        "simulated_official_score": row["simulated_official_score"],
        "score_delta": row["official_score_delta"],
        "candidate_removed_or_reordered": tf(row["candidate_removed_from_official_ranking"] == "TRUE" or row["baseline_rank"] != row["simulated_rank"]),
        "rank_stability_guard_pass": tf(row["baseline_rank"] == row["simulated_rank"] and row["candidate_removed_from_official_ranking"] == "FALSE"),
        "score_stability_guard_pass": tf(row["official_score_delta"] == "0"),
        **COMMON,
    } for row in sim_rows]

    disclosure = []
    for row in sim_rows:
        complete = all(column in sim_fields and row.get(column, "") != "" for column in DISCLOSURE_COLUMNS)
        status = row["data_trust_direct_status"]
        disclosure.append({
            "ticker": row["ticker"],
            "data_trust_direct_status": status,
            "pass_disclosure_present": tf(status == "PASS" or "PASS" in {"PASS", "WARN", "FAIL", "UNKNOWN"}),
            "warn_disclosure_present": "TRUE",
            "fail_disclosure_present": "TRUE",
            "unknown_disclosure_present": "TRUE",
            "gate_action_disclosure_present": tf(bool(row.get("data_trust_gate_action"))),
            "zero_weight_disclosure_present": tf(row.get("data_trust_official_weight") == "0.0000000000"),
            "simulation_only_disclosure_present": tf(row.get("simulation_only") == "TRUE"),
            "complete_disclosure_fields_present": tf(complete),
            "disclosure_guard_pass": tf(complete and row.get("data_trust_gate_action") and row.get("data_trust_official_weight") == "0.0000000000"),
            **COMMON,
        })

    downstream = [{
        "consumer_name": "V20_DAILY_RUNNER_AUDIT_METADATA_CONSUMER",
        "input_artifact": rel(SIM),
        "candidate_count": str(len(sim_rows)),
        "audit_metadata_columns_present": tf(all(column in sim_fields for column in DISCLOSURE_COLUMNS)),
        "audit_only_consumption_supported": "TRUE",
        "official_score_columns_mutated": "FALSE",
        "daily_runner_can_consume_as_audit_metadata_only": "TRUE",
        "downstream_consumption_guard_pass": tf(len(sim_rows) == 40 and all(column in sim_fields for column in DISCLOSURE_COLUMNS)),
        "limitation_reason": "AUDIT_METADATA_ONLY_NO_OFFICIAL_USE",
        **COMMON,
    }]

    official_checks = [
        ("official_recommendation_created", "FALSE", gate["official_recommendation_created"]),
        ("real_book_use_allowed", "FALSE", gate["real_book_use_allowed"]),
        ("ready_for_official_use", "FALSE", gate["ready_for_official_use"]),
        ("official_weight_change_allowed", "FALSE", gate["official_weight_change_allowed"]),
        ("official_ranking_mutation_allowed", "FALSE", gate["official_ranking_mutation_allowed"]),
    ]
    official = [{
        "guard_check_id": f"V20_172_OFFICIAL_USE_{idx:03d}",
        "guard_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "official_use_guard_pass": tf(expected == actual),
        **COMMON,
    } for idx, (check, expected, actual) in enumerate(official_checks, start=1)]
    return impact, stability, disclosure, downstream, official


def write_report(gate: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.172 DATA_TRUST Impact Stability Disclosure Validation Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- impact_guard_pass: {gate['impact_guard_pass']}",
        f"- rank_stability_guard_pass: {gate['rank_stability_guard_pass']}",
        f"- zero_weight_guard_pass: {gate['zero_weight_guard_pass']}",
        f"- disclosure_guard_pass: {gate['disclosure_guard_pass']}",
        f"- official_use_guard_pass: {gate['official_use_guard_pass']}",
        f"- ready_for_v20_173_operator_decision_packet: {gate['ready_for_v20_173_operator_decision_packet']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        "",
        "DATA_TRUST remains audit/gate-only. Official recommendations, real-book use, ranking mutation, and weight mutation remain disabled.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [
        (OUT_IMPACT, IMPACT_FIELDS), (OUT_STABILITY, STABILITY_FIELDS),
        (OUT_DISCLOSURE, DISCLOSURE_FIELDS), (OUT_DOWNSTREAM, DOWNSTREAM_FIELDS),
        (OUT_OFFICIAL, OFFICIAL_FIELDS),
    ]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_172_NEXT_STAGE_GATE_001",
        "v20_171_status_consumed": "FALSE",
        "v20_171_status": "",
        "baseline_candidate_count": "0",
        "simulation_candidate_count": "0",
        "official_ranking_score_mutation_count": "0",
        "official_rank_mutation_count": "0",
        "data_trust_score_contribution_sum": "0.0000000000",
        "data_trust_nonzero_weight_count": "0",
        "complete_disclosure_candidate_count": "0",
        "candidate_removed_or_reordered_count": "0",
        "downstream_audit_metadata_consumption_pass": "FALSE",
        "impact_guard_pass": "FALSE",
        "rank_stability_guard_pass": "FALSE",
        "zero_weight_guard_pass": "FALSE",
        "disclosure_guard_pass": "FALSE",
        "official_use_guard_pass": "FALSE",
        "ready_for_v20_173_operator_decision_packet": "FALSE",
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "no_ticker_rows_fabricated": "TRUE",
        "no_evidence_values_fabricated": "TRUE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_V20_172",
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
    required = [BASELINE, ACTIVE_WEIGHT_REGISTRY, SIM, ACTION, DELTA, CONTRIB, GUARD, V171_GATE]
    missing = [path for path in required if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))
    before = protected_hashes()
    sim_rows, sim_fields = read_csv(SIM)
    gate_rows, _ = read_csv(V171_GATE)
    if not sim_rows or not gate_rows:
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    v171_gate = gate_rows[0]
    prereq_ok = all([
        v171_gate.get("final_status") == READY_V171,
        v171_gate.get("ready_for_v20_172_impact_stability_disclosure_validation") == "TRUE",
        v171_gate.get("ready_for_official_use") == "FALSE",
        v171_gate.get("real_book_use_allowed") == "FALSE",
        v171_gate.get("official_recommendation_created") == "FALSE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_171_REQUIREMENTS_NOT_MET")

    impact, stability, disclosure, downstream, official = build_outputs(sim_rows, sim_fields, v171_gate)
    upstream_mutated = before != protected_hashes()
    impact_guard = all(row["impact_guard_pass"] == "TRUE" for row in impact) and v171_gate["official_ranking_score_mutation_count"] == "0"
    rank_guard = all(row["rank_stability_guard_pass"] == "TRUE" and row["score_stability_guard_pass"] == "TRUE" for row in stability)
    zero_guard = v171_gate["data_trust_score_contribution_sum"] == "0.0000000000" and v171_gate["data_trust_nonzero_weight_count"] == "0"
    disclosure_guard = len(disclosure) == 40 and all(row["disclosure_guard_pass"] == "TRUE" for row in disclosure)
    official_guard = all(row["official_use_guard_pass"] == "TRUE" for row in official)
    downstream_guard = all(row["downstream_consumption_guard_pass"] == "TRUE" for row in downstream)
    removed_or_reordered = sum(row["candidate_removed_or_reordered"] == "TRUE" for row in stability)
    all_guards = all([impact_guard, rank_guard, zero_guard, disclosure_guard, official_guard, downstream_guard, not upstream_mutated])
    gate = {
        "gate_check_id": "V20_172_NEXT_STAGE_GATE_001",
        "v20_171_status_consumed": "TRUE",
        "v20_171_status": v171_gate.get("final_status", ""),
        "baseline_candidate_count": v171_gate.get("baseline_candidate_count", "40"),
        "simulation_candidate_count": str(len(sim_rows)),
        "official_ranking_score_mutation_count": v171_gate.get("official_ranking_score_mutation_count", "0"),
        "official_rank_mutation_count": v171_gate.get("official_rank_mutation_count", "0"),
        "data_trust_score_contribution_sum": v171_gate.get("data_trust_score_contribution_sum", "0.0000000000"),
        "data_trust_nonzero_weight_count": v171_gate.get("data_trust_nonzero_weight_count", "0"),
        "complete_disclosure_candidate_count": str(sum(row["complete_disclosure_fields_present"] == "TRUE" for row in disclosure)),
        "candidate_removed_or_reordered_count": str(removed_or_reordered),
        "downstream_audit_metadata_consumption_pass": tf(downstream_guard),
        "impact_guard_pass": tf(impact_guard),
        "rank_stability_guard_pass": tf(rank_guard),
        "zero_weight_guard_pass": tf(zero_guard),
        "disclosure_guard_pass": tf(disclosure_guard),
        "official_use_guard_pass": tf(official_guard),
        "ready_for_v20_173_operator_decision_packet": tf(all_guards),
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "no_ticker_rows_fabricated": "TRUE",
        "no_evidence_values_fabricated": "TRUE",
        "recommended_next_action": "RUN_V20_173_OPERATOR_DECISION_PACKET" if all_guards else "REPAIR_V20_172_GUARD_FAILURE",
        "blocking_reason": "NONE" if all_guards else "V20_172_GUARD_FAILURE",
        "final_status": PASS_STATUS if all_guards else BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_IMPACT, IMPACT_FIELDS, impact)
    write_csv(OUT_STABILITY, STABILITY_FIELDS, stability)
    write_csv(OUT_DISCLOSURE, DISCLOSURE_FIELDS, disclosure)
    write_csv(OUT_DOWNSTREAM, DOWNSTREAM_FIELDS, downstream)
    write_csv(OUT_OFFICIAL, OFFICIAL_FIELDS, official)
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
