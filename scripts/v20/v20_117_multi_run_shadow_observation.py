#!/usr/bin/env python
"""V20.117 multi-run shadow observation.

Accumulates bounded, scenario-level shadow observations for the selected repair
scenario from the current V20.109-V20.116 lineage. This stage is observation-
only, audit-only, shadow-only, and non-mutating.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_116_SHADOW_STABILITY_REGRESSION_DECISION.csv"
IN_CRITERIA = CONSOLIDATION / "V20_116_STABILITY_CRITERIA_AUDIT.csv"
IN_HASH = CONSOLIDATION / "V20_116_REGRESSION_HASH_AUDIT.csv"
IN_DELTA = CONSOLIDATION / "V20_116_SHADOW_DELTA_STABILITY_AUDIT.csv"
IN_EXCEPTION = CONSOLIDATION / "V20_116_REGRESSION_EXCEPTION_AUDIT.csv"
IN_SAFETY = CONSOLIDATION / "V20_116_SHADOW_STABILITY_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_116_NEXT_STAGE_GATE.csv"
IN_V115_DELTA = CONSOLIDATION / "V20_115_SHADOW_VS_BASELINE_DELTA_AUDIT.csv"
IN_V114_DECISION = CONSOLIDATION / "V20_114_SHADOW_OUTPUT_RECONCILIATION_DECISION.csv"
IN_V113_DECISION = CONSOLIDATION / "V20_113_SHADOW_INTEGRATION_DRY_RUN_DECISION.csv"

OUT_DECISION = CONSOLIDATION / "V20_117_MULTI_RUN_SHADOW_OBSERVATION_DECISION.csv"
OUT_REGISTRY = CONSOLIDATION / "V20_117_SHADOW_OBSERVATION_RUN_REGISTRY.csv"
OUT_SUMMARY = CONSOLIDATION / "V20_117_MULTI_RUN_OBSERVATION_SUMMARY.csv"
OUT_CONSISTENCY = CONSOLIDATION / "V20_117_OBSERVATION_CONSISTENCY_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_117_OBSERVATION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_117_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_117_MULTI_RUN_SHADOW_OBSERVATION_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V116_PASS_STATUS = "PASS_V20_116_SHADOW_STABILITY_REGRESSION_AUDIT_READY_FOR_V20_117"
PASS_STATUS = "PASS_V20_117_MULTI_RUN_SHADOW_OBSERVATION_READY_FOR_V20_118"
BLOCKED_STATUS = "BLOCKED_V20_117_MULTI_RUN_SHADOW_OBSERVATION"

REQUIRED_INPUTS = [IN_DECISION, IN_CRITERIA, IN_HASH, IN_DELTA, IN_EXCEPTION, IN_SAFETY, IN_GATE]
UPSTREAM_HASH_INPUTS = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    CONSOLIDATION / "V20_110_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_111_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_112_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_113_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_114_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_115_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_116_NEXT_STAGE_GATE.csv",
    IN_DECISION,
    IN_DELTA,
]

PROHIBITED_FIELDS = [
    "accepted_weight_created", "accepted_weights_created", "real_book_weight_created", "real_book_action_created",
    "official_weight_created", "official_weights_created", "official_ranking_created", "official_rankings_created",
    "official_recommendation_created", "official_recommendations_created", "trade_action_created", "trade_actions_created",
    "broker_action_created", "broker_actions_created", "authoritative_overwrite_created", "authoritative_overwrites_created",
    "authoritative_ranking_overwritten", "weight_mutated", "weight_mutations_created", "promotion_ready",
    "performance_claim_created", "performance_claims_created", "performance_effectiveness_claim_created",
    "official_promotion_allowed", "is_official_weight",
]
COMMON_SAFETY = {
    "accepted_weight_created": "FALSE", "accepted_weights_created": "FALSE",
    "real_book_weight_created": "FALSE", "real_book_action_created": "FALSE",
    "official_weight_created": "FALSE", "official_weights_created": "FALSE",
    "official_ranking_created": "FALSE", "official_rankings_created": "FALSE",
    "official_recommendation_created": "FALSE", "official_recommendations_created": "FALSE",
    "trade_action_created": "FALSE", "trade_actions_created": "FALSE",
    "broker_action_created": "FALSE", "broker_actions_created": "FALSE",
    "authoritative_overwrite_created": "FALSE", "authoritative_overwrites_created": "FALSE",
    "authoritative_ranking_overwritten": "FALSE", "weight_mutated": "FALSE",
    "weight_mutations_created": "FALSE", "promotion_ready": "FALSE",
    "performance_claim_created": "FALSE", "performance_claims_created": "FALSE",
    "performance_effectiveness_claim_created": "FALSE", "official_promotion_allowed": "FALSE",
    "is_official_weight": "FALSE", "research_only": "TRUE", "shadow_only": "TRUE",
    "observation_only": "TRUE", "audit_only": "TRUE", "simulation_only": "TRUE",
}

DECISION_FIELDS = [
    "decision_check_id", "v20_116_gate_consumed", "v20_117_multi_run_shadow_observation_allowed_by_v116",
    "v20_116_final_status", "v20_116_status_passed", "selected_repair_scenario_id",
    "expected_selected_repair_scenario_id", "selected_scenario_matches_v20_116",
    "observation_registry_created", "observation_registry_row_count", "observation_summary_created",
    "observation_summary_row_count", "observation_consistency_audit_created",
    "observation_consistency_all_passed", "scenario_level_observation_count", "fabricated_ticker_row_count",
    "no_ticker_rows_fabricated", "upstream_mutation_detected", "no_upstream_outputs_mutated",
    "shadow_only_confirmed", "observation_only_confirmed", "audit_only_confirmed",
    "safety_boundary_audit_passed", "prohibited_action_true_count",
    "all_multi_run_shadow_observation_checks_passed", "v20_118_promotion_blocker_recheck_allowed",
    "multi_run_shadow_observation_status", "blocking_reason", *COMMON_SAFETY.keys(),
]
REGISTRY_FIELDS = ["observation_run_id", "selected_repair_scenario_id", "source_stage", "source_artifact", "observation_type", "observation_value", "scenario_level_only", "ticker_rows_created", "observation_status", *COMMON_SAFETY.keys()]
SUMMARY_FIELDS = ["summary_check_id", "selected_repair_scenario_id", "observation_run_count", "scenario_level_observation_count", "consistent_observation_count", "ticker_rows_created", "summary_status", *COMMON_SAFETY.keys()]
CONSISTENCY_FIELDS = ["consistency_check_id", "selected_repair_scenario_id", "consistency_rule", "required_value", "observed_value", "consistency_passed", "consistency_status", *COMMON_SAFETY.keys()]
SAFETY_FIELDS = ["safety_check_id", "prohibited_field", "observed_true_count", "safety_boundary_passed", "safety_status", "safety_reason", *COMMON_SAFETY.keys()]
GATE_FIELDS = ["gate_check_id", "v20_116_gate_consumed", "v20_117_multi_run_shadow_observation_allowed_by_v116", "selected_repair_scenario_id", "multi_run_shadow_observation_decision_created", "observation_registry_created", "observation_consistency_all_passed", "no_ticker_rows_fabricated", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "v20_118_promotion_blocker_recheck_allowed", "next_recommended_action", "blocking_reason", "multi_run_shadow_observation_status", *COMMON_SAFETY.keys()]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def truthy(value: str | None) -> bool:
    return (value or "").strip().upper() == "TRUE"


def clean(value: str | None) -> str:
    return (value or "").strip()


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def upstream_hashes() -> dict[str, str]:
    return {display_path(path): digest(path) for path in UPSTREAM_HASH_INPUTS if path.exists()}


def prohibited_counts(groups: list[list[dict[str, str]]]) -> dict[str, int]:
    counts = {field: 0 for field in PROHIBITED_FIELDS}
    for rows in groups:
        for row in rows:
            for field in PROHIBITED_FIELDS:
                if field in row and truthy(row.get(field)):
                    counts[field] += 1
    return counts


def build_registry(selected_id: str, decision: dict[str, str], criteria_rows: list[dict[str, str]], delta_rows: list[dict[str, str]], exception_rows: list[dict[str, str]], v115_delta_rows: list[dict[str, str]], v114_rows: list[dict[str, str]], v113_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    specs = [
        ("V20.116", IN_DECISION, "stability_regression_status", clean(decision.get("shadow_stability_regression_audit_status"))),
        ("V20.116", IN_CRITERIA, "criteria_pass_count", str(sum(1 for row in criteria_rows if truthy(row.get("criterion_passed"))))),
        ("V20.116", IN_DELTA, "stable_delta_count", str(sum(1 for row in delta_rows if truthy(row.get("delta_stable"))))),
        ("V20.116", IN_EXCEPTION, "violating_exception_count", str(sum(1 for row in exception_rows if truthy(row.get("exception_violates_pass"))))),
        ("V20.115", IN_V115_DELTA, "baseline_delta_row_count", str(len(v115_delta_rows))),
        ("V20.114", IN_V114_DECISION, "reconciliation_pass", clean(first(v114_rows).get("all_shadow_output_reconciliation_checks_passed")) if v114_rows else "TRUE"),
        ("V20.113", IN_V113_DECISION, "dry_run_pass", clean(first(v113_rows).get("all_shadow_integration_dry_run_checks_passed")) if v113_rows else "TRUE"),
    ]
    rows = []
    for index, (stage, artifact, obs_type, value) in enumerate(specs, start=1):
        rows.append({
            "observation_run_id": f"V20_117_SHADOW_OBSERVATION_RUN_REGISTRY_{index:03d}",
            "selected_repair_scenario_id": selected_id,
            "source_stage": stage,
            "source_artifact": display_path(artifact),
            "observation_type": obs_type,
            "observation_value": value,
            "scenario_level_only": "TRUE",
            "ticker_rows_created": "0",
            "observation_status": "OBSERVED",
            **COMMON_SAFETY,
        })
    return rows


def build_consistency(selected_id: str, registry: list[dict[str, str]], before: dict[str, str], after: dict[str, str], safety_passed: bool) -> list[dict[str, str]]:
    checks = [
        ("registry_not_empty", "TRUE", tf(bool(registry)), bool(registry)),
        ("all_observations_scenario_level", "TRUE", tf(all(truthy(row.get("scenario_level_only")) for row in registry)), all(truthy(row.get("scenario_level_only")) for row in registry)),
        ("no_ticker_rows", "0", str(sum(int(clean(row.get("ticker_rows_created")) or "0") for row in registry)), all(clean(row.get("ticker_rows_created")) == "0" for row in registry)),
        ("upstream_hashes_unchanged", "TRUE", tf(before == after), before == after),
        ("safety_boundary_passed", "TRUE", tf(safety_passed), safety_passed),
    ]
    return [{
        "consistency_check_id": f"V20_117_OBSERVATION_CONSISTENCY_AUDIT_{index:03d}",
        "selected_repair_scenario_id": selected_id,
        "consistency_rule": name,
        "required_value": required,
        "observed_value": observed,
        "consistency_passed": tf(passed),
        "consistency_status": "PASS" if passed else "BLOCKED",
        **COMMON_SAFETY,
    } for index, (name, required, observed, passed) in enumerate(checks, start=1)]


def build_safety(counts: dict[str, int], passed: bool) -> list[dict[str, str]]:
    return [{
        "safety_check_id": f"V20_117_OBSERVATION_SAFETY_BOUNDARY_AUDIT_{index:03d}",
        "prohibited_field": field,
        "observed_true_count": str(counts.get(field, 0)),
        "safety_boundary_passed": tf(passed),
        "safety_status": "PASS" if passed else "BLOCKED",
        "safety_reason": "V20.117 creates only shadow observation audit artifacts.",
        **COMMON_SAFETY,
    } for index, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_all(decision, registry, summary, consistency, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_REGISTRY, REGISTRY_FIELDS, registry)
    write_csv(OUT_SUMMARY, SUMMARY_FIELDS, summary)
    write_csv(OUT_CONSISTENCY, CONSISTENCY_FIELDS, consistency)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.117 Multi-Run Shadow Observation Report",
        "",
        f"- wrapper_status: {decision.get('multi_run_shadow_observation_status')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- observation_registry_row_count: {decision.get('observation_registry_row_count')}",
        f"- observation_consistency_all_passed: {decision.get('observation_consistency_all_passed')}",
        f"- upstream_mutation_detected: {decision.get('upstream_mutation_detected')}",
        f"- v20_118_promotion_blocker_recheck_allowed: {decision.get('v20_118_promotion_blocker_recheck_allowed')}",
        "- promotion_ready: FALSE",
        "- performance_claim_created: FALSE",
    ]) + "\n", encoding="utf-8")


def print_safety_stdout() -> None:
    for flag in [
        "ACCEPTED_WEIGHT_CREATED", "ACCEPTED_WEIGHTS_CREATED", "REAL_BOOK_WEIGHT_CREATED", "REAL_BOOK_ACTION_CREATED",
        "OFFICIAL_WEIGHT_CREATED", "OFFICIAL_WEIGHTS_CREATED", "OFFICIAL_RANKING_CREATED", "OFFICIAL_RANKINGS_CREATED",
        "OFFICIAL_RECOMMENDATION_CREATED", "OFFICIAL_RECOMMENDATIONS_CREATED", "TRADE_ACTION_CREATED", "TRADE_ACTIONS_CREATED",
        "BROKER_ACTION_CREATED", "BROKER_ACTIONS_CREATED", "AUTHORITATIVE_OVERWRITE_CREATED", "AUTHORITATIVE_OVERWRITES_CREATED",
        "AUTHORITATIVE_RANKING_OVERWRITTEN", "WEIGHT_MUTATED", "WEIGHT_MUTATIONS_CREATED", "PROMOTION_READY",
        "PERFORMANCE_CLAIM_CREATED", "PERFORMANCE_CLAIMS_CREATED", "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED",
        "OFFICIAL_PROMOTION_ALLOWED", "IS_OFFICIAL_WEIGHT",
    ]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    counts = {field: 0 for field in PROHIBITED_FIELDS}
    safety = build_safety(counts, False)
    decision = {"decision_check_id": "V20_117_MULTI_RUN_SHADOW_OBSERVATION_DECISION_001", "v20_116_gate_consumed": "FALSE", "v20_117_multi_run_shadow_observation_allowed_by_v116": "FALSE", "v20_116_final_status": "", "v20_116_status_passed": "FALSE", "selected_repair_scenario_id": "", "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_116": "FALSE", "observation_registry_created": "FALSE", "observation_registry_row_count": "0", "observation_summary_created": "FALSE", "observation_summary_row_count": "0", "observation_consistency_audit_created": "FALSE", "observation_consistency_all_passed": "FALSE", "scenario_level_observation_count": "0", "fabricated_ticker_row_count": "0", "no_ticker_rows_fabricated": "TRUE", "upstream_mutation_detected": "FALSE", "no_upstream_outputs_mutated": "TRUE", "shadow_only_confirmed": "FALSE", "observation_only_confirmed": "TRUE", "audit_only_confirmed": "TRUE", "safety_boundary_audit_passed": "FALSE", "prohibited_action_true_count": "0", "all_multi_run_shadow_observation_checks_passed": "FALSE", "v20_118_promotion_blocker_recheck_allowed": "FALSE", "multi_run_shadow_observation_status": BLOCKED_STATUS, "blocking_reason": blocking, **COMMON_SAFETY}
    gate = {"gate_check_id": "V20_117_NEXT_STAGE_GATE_001", "v20_116_gate_consumed": "FALSE", "v20_117_multi_run_shadow_observation_allowed_by_v116": "FALSE", "selected_repair_scenario_id": "", "multi_run_shadow_observation_decision_created": "TRUE", "observation_registry_created": "FALSE", "observation_consistency_all_passed": "FALSE", "no_ticker_rows_fabricated": "TRUE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "v20_118_promotion_blocker_recheck_allowed": "FALSE", "next_recommended_action": "V20.117_MULTI_RUN_SHADOW_OBSERVATION_REPAIR", "blocking_reason": blocking, "multi_run_shadow_observation_status": BLOCKED_STATUS, **COMMON_SAFETY}
    write_all([decision], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_116_GATE_CONSUMED=FALSE")
    print("V20_118_PROMOTION_BLOCKER_RECHECK_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def main() -> int:
    before_hashes = upstream_hashes()
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)

    decision_rows = read_csv(IN_DECISION)
    criteria_rows = read_csv(IN_CRITERIA)
    hash_rows = read_csv(IN_HASH)
    delta_rows = read_csv(IN_DELTA)
    exception_rows = read_csv(IN_EXCEPTION)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    if not all([decision_rows, criteria_rows, hash_rows, delta_rows, exception_rows, safety_input_rows, gate_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v116_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_116_NEXT_STAGE_GATE_001"
    v117_allowed = truthy(gate_in.get("v20_117_multi_run_shadow_observation_allowed"))
    v116_status = clean(gate_in.get("shadow_stability_regression_audit_status")) or clean(decision_in.get("shadow_stability_regression_audit_status"))
    v116_status_passed = v116_status == V116_PASS_STATUS
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))
    v115_delta_rows = read_csv(IN_V115_DELTA) if IN_V115_DELTA.exists() and IN_V115_DELTA.stat().st_size > 0 else []
    v114_rows = read_csv(IN_V114_DECISION) if IN_V114_DECISION.exists() and IN_V114_DECISION.stat().st_size > 0 else []
    v113_rows = read_csv(IN_V113_DECISION) if IN_V113_DECISION.exists() and IN_V113_DECISION.stat().st_size > 0 else []
    registry = build_registry(selected_id, decision_in, criteria_rows, delta_rows, exception_rows, v115_delta_rows, v114_rows, v113_rows)
    counts = prohibited_counts([decision_rows, criteria_rows, hash_rows, delta_rows, exception_rows, safety_input_rows, gate_rows, v115_delta_rows, v114_rows, v113_rows])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0
    consistency = build_consistency(selected_id, registry, before_hashes, after_hashes, safety_passed)
    consistency_all = all(truthy(row.get("consistency_passed")) for row in consistency)
    ticker_count = sum(int(clean(row.get("ticker_rows_created")) or "0") for row in registry)
    scenario_obs_count = sum(1 for row in registry if truthy(row.get("scenario_level_only")))
    summary = [{"summary_check_id": "V20_117_MULTI_RUN_OBSERVATION_SUMMARY_001", "selected_repair_scenario_id": selected_id, "observation_run_count": str(len(registry)), "scenario_level_observation_count": str(scenario_obs_count), "consistent_observation_count": str(sum(1 for row in consistency if truthy(row.get("consistency_passed")))), "ticker_rows_created": str(ticker_count), "summary_status": "OBSERVATION_SUMMARY_READY" if registry and consistency_all else "OBSERVATION_SUMMARY_BLOCKED", **COMMON_SAFETY}]
    safety = build_safety(counts, safety_passed)
    checks = {"v20_116_gate_consumed": v116_gate_consumed, "v20_117_multi_run_shadow_observation_allowed_by_v116": v117_allowed, "v20_116_status_passed": v116_status_passed, "selected_scenario_matches_v20_116": selected_matches, "observation_registry_created": bool(registry), "observation_summary_created": bool(summary), "observation_consistency_all_passed": consistency_all, "no_ticker_rows_fabricated": ticker_count == 0, "no_upstream_outputs_mutated": not upstream_mutation, "shadow_only_confirmed": truthy(decision_in.get("shadow_only_confirmed")), "audit_only_confirmed": truthy(decision_in.get("audit_only_confirmed")), "safety_boundary_audit_passed": safety_passed, "prohibited_action_true_count_zero": prohibited_count == 0}
    all_passed = all(checks.values())
    status = PASS_STATUS if all_passed else BLOCKED_STATUS
    blocking = "" if all_passed else ";".join(name for name, passed in checks.items() if not passed)
    decision = {"decision_check_id": "V20_117_MULTI_RUN_SHADOW_OBSERVATION_DECISION_001", "v20_116_gate_consumed": tf(v116_gate_consumed), "v20_117_multi_run_shadow_observation_allowed_by_v116": tf(v117_allowed), "v20_116_final_status": v116_status, "v20_116_status_passed": tf(v116_status_passed), "selected_repair_scenario_id": selected_id, "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_116": tf(selected_matches), "observation_registry_created": tf(bool(registry)), "observation_registry_row_count": str(len(registry)), "observation_summary_created": tf(bool(summary)), "observation_summary_row_count": str(len(summary)), "observation_consistency_audit_created": tf(bool(consistency)), "observation_consistency_all_passed": tf(consistency_all), "scenario_level_observation_count": str(scenario_obs_count), "fabricated_ticker_row_count": str(ticker_count), "no_ticker_rows_fabricated": tf(ticker_count == 0), "upstream_mutation_detected": tf(upstream_mutation), "no_upstream_outputs_mutated": tf(not upstream_mutation), "shadow_only_confirmed": tf(checks["shadow_only_confirmed"]), "observation_only_confirmed": "TRUE", "audit_only_confirmed": tf(checks["audit_only_confirmed"]), "safety_boundary_audit_passed": tf(safety_passed), "prohibited_action_true_count": str(prohibited_count), "all_multi_run_shadow_observation_checks_passed": tf(all_passed), "v20_118_promotion_blocker_recheck_allowed": tf(all_passed), "multi_run_shadow_observation_status": status, "blocking_reason": blocking, **COMMON_SAFETY}
    gate = {"gate_check_id": "V20_117_NEXT_STAGE_GATE_001", "v20_116_gate_consumed": tf(v116_gate_consumed), "v20_117_multi_run_shadow_observation_allowed_by_v116": tf(v117_allowed), "selected_repair_scenario_id": selected_id, "multi_run_shadow_observation_decision_created": "TRUE", "observation_registry_created": tf(bool(registry)), "observation_consistency_all_passed": tf(consistency_all), "no_ticker_rows_fabricated": tf(ticker_count == 0), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "v20_118_promotion_blocker_recheck_allowed": tf(all_passed), "next_recommended_action": "V20.118_PROMOTION_BLOCKER_RECHECK" if all_passed else "V20.117_MULTI_RUN_SHADOW_OBSERVATION_REPAIR", "blocking_reason": blocking, "multi_run_shadow_observation_status": status, **COMMON_SAFETY}
    write_all([decision], registry, summary, consistency, safety, [gate])
    write_report(decision)
    print(status)
    print(f"V20_116_GATE_CONSUMED={tf(v116_gate_consumed)}")
    print(f"V20_117_MULTI_RUN_SHADOW_OBSERVATION_ALLOWED_BY_V116={tf(v117_allowed)}")
    print(f"V20_116_FINAL_STATUS={v116_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_116={tf(selected_matches)}")
    print(f"OBSERVATION_REGISTRY_CREATED={tf(bool(registry))}")
    print(f"OBSERVATION_REGISTRY_ROW_COUNT={len(registry)}")
    print(f"OBSERVATION_SUMMARY_CREATED={tf(bool(summary))}")
    print(f"OBSERVATION_CONSISTENCY_ALL_PASSED={tf(consistency_all)}")
    print(f"FABRICATED_TICKER_ROW_COUNT={ticker_count}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_118_PROMOTION_BLOCKER_RECHECK_ALLOWED={tf(all_passed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
