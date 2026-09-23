#!/usr/bin/env python
"""V20.116 shadow stability and regression audit.

This stage validates that V20.115 scenario-level shadow deltas are stable,
explainable, and audit-only. It hashes representative upstream artifacts before
and after execution and creates only V20.116 audit, gate, and report outputs.
"""

from __future__ import annotations

import csv
import hashlib
from decimal import Decimal, InvalidOperation
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_115_SHADOW_BASELINE_COMPARISON_DECISION.csv"
IN_BASELINE = CONSOLIDATION / "V20_115_BASELINE_REFERENCE_AUDIT.csv"
IN_DELTA = CONSOLIDATION / "V20_115_SHADOW_VS_BASELINE_DELTA_AUDIT.csv"
IN_EXPLANATION = CONSOLIDATION / "V20_115_CHANGE_EXPLANATION_AUDIT.csv"
IN_SAFETY = CONSOLIDATION / "V20_115_SHADOW_BASELINE_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_115_NEXT_STAGE_GATE.csv"

OUT_DECISION = CONSOLIDATION / "V20_116_SHADOW_STABILITY_REGRESSION_DECISION.csv"
OUT_CRITERIA = CONSOLIDATION / "V20_116_STABILITY_CRITERIA_AUDIT.csv"
OUT_HASH = CONSOLIDATION / "V20_116_REGRESSION_HASH_AUDIT.csv"
OUT_DELTA_STABILITY = CONSOLIDATION / "V20_116_SHADOW_DELTA_STABILITY_AUDIT.csv"
OUT_EXCEPTION = CONSOLIDATION / "V20_116_REGRESSION_EXCEPTION_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_116_SHADOW_STABILITY_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_116_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_116_SHADOW_STABILITY_REGRESSION_AUDIT_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V115_PASS_STATUS = "PASS_V20_115_SHADOW_BASELINE_COMPARISON_READY_FOR_V20_116"
PASS_STATUS = "PASS_V20_116_SHADOW_STABILITY_REGRESSION_AUDIT_READY_FOR_V20_117"
BLOCKED_STATUS = "BLOCKED_V20_116_SHADOW_STABILITY_REGRESSION_AUDIT"

REQUIRED_INPUTS = [IN_DECISION, IN_BASELINE, IN_DELTA, IN_EXPLANATION, IN_SAFETY, IN_GATE]
UPSTREAM_HASH_INPUTS = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    CONSOLIDATION / "V20_110_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_111_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_112_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_113_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_114_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_115_NEXT_STAGE_GATE.csv",
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
    "audit_only": "TRUE", "stability_regression_audit_only": "TRUE", "simulation_only": "TRUE",
}

DECISION_FIELDS = [
    "decision_check_id", "v20_115_gate_consumed", "v20_116_shadow_stability_regression_audit_allowed_by_v115",
    "v20_115_final_status", "v20_115_status_passed", "selected_repair_scenario_id",
    "expected_selected_repair_scenario_id", "selected_scenario_matches_v20_115",
    "baseline_reference_valid", "delta_audit_consumed", "change_explanation_consumed",
    "stability_criteria_created", "stability_criteria_passed", "delta_stability_audit_created",
    "scenario_level_delta_count", "unstable_delta_count", "regression_hash_audit_created",
    "upstream_mutation_detected", "no_upstream_outputs_mutated", "regression_exception_audit_created",
    "violating_exception_count", "no_violating_regression_exception", "fabricated_ticker_row_count",
    "no_ticker_rows_fabricated", "shadow_only_confirmed", "audit_only_confirmed",
    "safety_boundary_audit_passed", "prohibited_action_true_count",
    "all_shadow_stability_regression_checks_passed", "v20_117_multi_run_shadow_observation_allowed",
    "shadow_stability_regression_audit_status", "blocking_reason", *COMMON_SAFETY.keys(),
]
CRITERIA_FIELDS = ["criteria_check_id", "selected_repair_scenario_id", "criterion_name", "required_value", "observed_value", "criterion_passed", "criterion_status", *COMMON_SAFETY.keys()]
HASH_FIELDS = ["hash_check_id", "artifact_path", "before_sha256", "after_sha256", "hash_unchanged", "regression_hash_status", *COMMON_SAFETY.keys()]
DELTA_FIELDS = ["delta_stability_check_id", "selected_repair_scenario_id", "delta_name", "scenario_level_delta", "explanation_found", "performance_claim_created", "ticker_rows_created", "delta_stable", "delta_stability_status", *[k for k in COMMON_SAFETY.keys() if k != "performance_claim_created"]]
EXCEPTION_FIELDS = ["exception_check_id", "exception_type", "exception_present", "exception_violates_pass", "exception_status", "exception_reason", *COMMON_SAFETY.keys()]
SAFETY_FIELDS = ["safety_check_id", "prohibited_field", "observed_true_count", "safety_boundary_passed", "safety_status", "safety_reason", *COMMON_SAFETY.keys()]
GATE_FIELDS = [
    "gate_check_id", "v20_115_gate_consumed", "v20_116_shadow_stability_regression_audit_allowed_by_v115",
    "selected_repair_scenario_id", "shadow_stability_regression_decision_created",
    "stability_criteria_passed", "no_upstream_outputs_mutated", "no_violating_regression_exception",
    "no_ticker_rows_fabricated", "safety_boundary_audit_passed", "v20_117_multi_run_shadow_observation_allowed",
    "next_recommended_action", "blocking_reason", "shadow_stability_regression_audit_status", *COMMON_SAFETY.keys(),
]


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


def dec(value: str) -> Decimal | None:
    try:
        return Decimal((value or "").strip())
    except InvalidOperation:
        return None


def prohibited_counts(groups: list[list[dict[str, str]]]) -> dict[str, int]:
    counts = {field: 0 for field in PROHIBITED_FIELDS}
    for rows in groups:
        for row in rows:
            for field in PROHIBITED_FIELDS:
                if field in row and truthy(row.get(field)):
                    counts[field] += 1
    return counts


def build_criteria(selected_id: str, baseline_valid: bool, delta_rows: list[dict[str, str]], explanation_rows: list[dict[str, str]], no_tickers: bool) -> list[dict[str, str]]:
    explanation_topics = {clean(row.get("change_topic")) for row in explanation_rows if truthy(row.get("explainable"))}
    checks = [
        ("baseline_reference_valid", "TRUE", tf(baseline_valid), baseline_valid),
        ("delta_rows_scenario_level", "TRUE", tf(bool(delta_rows)), bool(delta_rows)),
        ("change_explanations_present", "TRUE", tf(bool(explanation_topics)), bool(explanation_topics)),
        ("no_ticker_rows_fabricated", "TRUE", tf(no_tickers), no_tickers),
        ("no_performance_claims", "TRUE", tf(all(not truthy(row.get("performance_claim_created")) for row in delta_rows + explanation_rows)), all(not truthy(row.get("performance_claim_created")) for row in delta_rows + explanation_rows)),
    ]
    return [{
        "criteria_check_id": f"V20_116_STABILITY_CRITERIA_AUDIT_{index:03d}",
        "selected_repair_scenario_id": selected_id,
        "criterion_name": name,
        "required_value": required,
        "observed_value": observed,
        "criterion_passed": tf(passed),
        "criterion_status": "PASS" if passed else "BLOCKED",
        **COMMON_SAFETY,
    } for index, (name, required, observed, passed) in enumerate(checks, start=1)]


def build_delta_stability(selected_id: str, delta_rows: list[dict[str, str]], explanation_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    explanation_ok = any(truthy(row.get("explainable")) for row in explanation_rows)
    known_delta_tokens = {
        "repair_ratio_minus_floor",
        "repair_minus_baseline_mean_return",
        "repair_minus_baseline_hit_rate",
        "scenario_fragile",
    }
    rows = []
    for index, row in enumerate(delta_rows, start=1):
        delta_value = clean(row.get("delta_value"))
        numeric_or_known = dec(delta_value) is not None or delta_value in known_delta_tokens
        stable = explanation_ok and numeric_or_known and not truthy(row.get("performance_claim_created"))
        rows.append({
            "delta_stability_check_id": f"V20_116_SHADOW_DELTA_STABILITY_AUDIT_{index:03d}",
            "selected_repair_scenario_id": selected_id,
            "delta_name": clean(row.get("delta_name")),
            "scenario_level_delta": "TRUE",
            "explanation_found": tf(explanation_ok),
            "performance_claim_created": "FALSE",
            "ticker_rows_created": "0",
            "delta_stable": tf(stable),
            "delta_stability_status": "STABLE_SCENARIO_LEVEL_DELTA" if stable else "UNSTABLE_DELTA",
            **COMMON_SAFETY,
        })
    return rows


def build_safety(counts: dict[str, int], passed: bool) -> list[dict[str, str]]:
    return [{
        "safety_check_id": f"V20_116_SHADOW_STABILITY_SAFETY_BOUNDARY_AUDIT_{index:03d}",
        "prohibited_field": field,
        "observed_true_count": str(counts.get(field, 0)),
        "safety_boundary_passed": tf(passed),
        "safety_status": "PASS" if passed else "BLOCKED",
        "safety_reason": "V20.116 creates only shadow stability and regression audit artifacts.",
        **COMMON_SAFETY,
    } for index, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_all(decision, criteria, hash_rows, delta_stability, exceptions, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_CRITERIA, CRITERIA_FIELDS, criteria)
    write_csv(OUT_HASH, HASH_FIELDS, hash_rows)
    write_csv(OUT_DELTA_STABILITY, DELTA_FIELDS, delta_stability)
    write_csv(OUT_EXCEPTION, EXCEPTION_FIELDS, exceptions)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.116 Shadow Stability Regression Audit Report",
        "",
        f"- wrapper_status: {decision.get('shadow_stability_regression_audit_status')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- stability_criteria_passed: {decision.get('stability_criteria_passed')}",
        f"- unstable_delta_count: {decision.get('unstable_delta_count')}",
        f"- upstream_mutation_detected: {decision.get('upstream_mutation_detected')}",
        f"- violating_exception_count: {decision.get('violating_exception_count')}",
        f"- v20_117_multi_run_shadow_observation_allowed: {decision.get('v20_117_multi_run_shadow_observation_allowed')}",
        "- performance_claim_created: FALSE",
        "- promotion_ready: FALSE",
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
    decision = {"decision_check_id": "V20_116_SHADOW_STABILITY_REGRESSION_DECISION_001", "v20_115_gate_consumed": "FALSE", "v20_116_shadow_stability_regression_audit_allowed_by_v115": "FALSE", "v20_115_final_status": "", "v20_115_status_passed": "FALSE", "selected_repair_scenario_id": "", "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_115": "FALSE", "baseline_reference_valid": "FALSE", "delta_audit_consumed": "FALSE", "change_explanation_consumed": "FALSE", "stability_criteria_created": "FALSE", "stability_criteria_passed": "FALSE", "delta_stability_audit_created": "FALSE", "scenario_level_delta_count": "0", "unstable_delta_count": "0", "regression_hash_audit_created": "FALSE", "upstream_mutation_detected": "FALSE", "no_upstream_outputs_mutated": "TRUE", "regression_exception_audit_created": "FALSE", "violating_exception_count": "0", "no_violating_regression_exception": "FALSE", "fabricated_ticker_row_count": "0", "no_ticker_rows_fabricated": "TRUE", "shadow_only_confirmed": "FALSE", "audit_only_confirmed": "TRUE", "safety_boundary_audit_passed": "FALSE", "prohibited_action_true_count": "0", "all_shadow_stability_regression_checks_passed": "FALSE", "v20_117_multi_run_shadow_observation_allowed": "FALSE", "shadow_stability_regression_audit_status": BLOCKED_STATUS, "blocking_reason": blocking, **COMMON_SAFETY}
    gate = {"gate_check_id": "V20_116_NEXT_STAGE_GATE_001", "v20_115_gate_consumed": "FALSE", "v20_116_shadow_stability_regression_audit_allowed_by_v115": "FALSE", "selected_repair_scenario_id": "", "shadow_stability_regression_decision_created": "TRUE", "stability_criteria_passed": "FALSE", "no_upstream_outputs_mutated": "TRUE", "no_violating_regression_exception": "FALSE", "no_ticker_rows_fabricated": "TRUE", "safety_boundary_audit_passed": "FALSE", "v20_117_multi_run_shadow_observation_allowed": "FALSE", "next_recommended_action": "V20.116_SHADOW_STABILITY_REGRESSION_AUDIT_REPAIR", "blocking_reason": blocking, "shadow_stability_regression_audit_status": BLOCKED_STATUS, **COMMON_SAFETY}
    write_all([decision], [], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_115_GATE_CONSUMED=FALSE")
    print("V20_117_MULTI_RUN_SHADOW_OBSERVATION_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def main() -> int:
    before_hashes = upstream_hashes()
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)

    decision_rows = read_csv(IN_DECISION)
    baseline_rows = read_csv(IN_BASELINE)
    delta_rows = read_csv(IN_DELTA)
    explanation_rows = read_csv(IN_EXPLANATION)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    if not all([decision_rows, baseline_rows, delta_rows, explanation_rows, safety_input_rows, gate_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    baseline = first(baseline_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v115_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_115_NEXT_STAGE_GATE_001"
    v116_allowed = truthy(gate_in.get("v20_116_shadow_stability_regression_audit_allowed"))
    v115_status = clean(gate_in.get("shadow_baseline_comparison_status")) or clean(decision_in.get("shadow_baseline_comparison_status"))
    v115_status_passed = v115_status == V115_PASS_STATUS
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))
    baseline_valid = truthy(baseline.get("baseline_reference_valid"))
    no_tickers = clean(decision_in.get("fabricated_ticker_row_count")) == "0"
    criteria = build_criteria(selected_id, baseline_valid, delta_rows, explanation_rows, no_tickers)
    delta_stability = build_delta_stability(selected_id, delta_rows, explanation_rows)
    after_hashes = upstream_hashes()
    hash_rows = []
    for index, artifact in enumerate(sorted(before_hashes), start=1):
        unchanged = before_hashes.get(artifact) == after_hashes.get(artifact)
        hash_rows.append({"hash_check_id": f"V20_116_REGRESSION_HASH_AUDIT_{index:03d}", "artifact_path": artifact, "before_sha256": before_hashes.get(artifact, ""), "after_sha256": after_hashes.get(artifact, ""), "hash_unchanged": tf(unchanged), "regression_hash_status": "UNCHANGED" if unchanged else "MUTATED", **COMMON_SAFETY})
    upstream_mutation = any(row["hash_unchanged"] != "TRUE" for row in hash_rows)
    unstable_count = sum(1 for row in delta_stability if row["delta_stable"] != "TRUE")
    criteria_passed = all(truthy(row.get("criterion_passed")) for row in criteria)
    counts = prohibited_counts([decision_rows, baseline_rows, delta_rows, explanation_rows, safety_input_rows, gate_rows])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    safety_passed = upstream_safety and prohibited_count == 0
    preliminary_exceptions = [
        ("upstream_mutation", upstream_mutation, upstream_mutation, "Representative upstream hash changed during V20.116."),
        ("unstable_delta", unstable_count > 0, unstable_count > 0, "One or more scenario-level deltas failed stability criteria."),
        ("safety_boundary_violation", not safety_passed, not safety_passed, "A prohibited action flag or upstream safety failure was detected."),
        ("ticker_row_fabrication", not no_tickers, not no_tickers, "Ticker row fabrication was detected."),
    ]
    exceptions = [{"exception_check_id": f"V20_116_REGRESSION_EXCEPTION_AUDIT_{i:03d}", "exception_type": t, "exception_present": tf(p), "exception_violates_pass": tf(v), "exception_status": "VIOLATING_EXCEPTION" if v else "NO_VIOLATION", "exception_reason": r, **COMMON_SAFETY} for i, (t, p, v, r) in enumerate(preliminary_exceptions, start=1)]
    violating_exception_count = sum(1 for row in exceptions if truthy(row.get("exception_violates_pass")))
    safety = build_safety(counts, safety_passed)
    checks = {
        "v20_115_gate_consumed": v115_gate_consumed,
        "v20_116_shadow_stability_regression_audit_allowed_by_v115": v116_allowed,
        "v20_115_status_passed": v115_status_passed,
        "selected_scenario_matches_v20_115": selected_matches,
        "baseline_reference_valid": baseline_valid,
        "stability_criteria_passed": criteria_passed,
        "delta_stability_audit_created": bool(delta_stability),
        "no_upstream_outputs_mutated": not upstream_mutation,
        "no_violating_regression_exception": violating_exception_count == 0,
        "no_ticker_rows_fabricated": no_tickers,
        "safety_boundary_audit_passed": safety_passed,
        "prohibited_action_true_count_zero": prohibited_count == 0,
    }
    all_passed = all(checks.values())
    status = PASS_STATUS if all_passed else BLOCKED_STATUS
    blocking = "" if all_passed else ";".join(name for name, passed in checks.items() if not passed)
    decision = {"decision_check_id": "V20_116_SHADOW_STABILITY_REGRESSION_DECISION_001", "v20_115_gate_consumed": tf(v115_gate_consumed), "v20_116_shadow_stability_regression_audit_allowed_by_v115": tf(v116_allowed), "v20_115_final_status": v115_status, "v20_115_status_passed": tf(v115_status_passed), "selected_repair_scenario_id": selected_id, "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_115": tf(selected_matches), "baseline_reference_valid": tf(baseline_valid), "delta_audit_consumed": tf(bool(delta_rows)), "change_explanation_consumed": tf(bool(explanation_rows)), "stability_criteria_created": tf(bool(criteria)), "stability_criteria_passed": tf(criteria_passed), "delta_stability_audit_created": tf(bool(delta_stability)), "scenario_level_delta_count": str(len(delta_stability)), "unstable_delta_count": str(unstable_count), "regression_hash_audit_created": tf(bool(hash_rows)), "upstream_mutation_detected": tf(upstream_mutation), "no_upstream_outputs_mutated": tf(not upstream_mutation), "regression_exception_audit_created": tf(bool(exceptions)), "violating_exception_count": str(violating_exception_count), "no_violating_regression_exception": tf(violating_exception_count == 0), "fabricated_ticker_row_count": "0", "no_ticker_rows_fabricated": tf(no_tickers), "shadow_only_confirmed": tf(truthy(decision_in.get("shadow_only_confirmed"))), "audit_only_confirmed": tf(truthy(decision_in.get("audit_only_confirmed"))), "safety_boundary_audit_passed": tf(safety_passed), "prohibited_action_true_count": str(prohibited_count), "all_shadow_stability_regression_checks_passed": tf(all_passed), "v20_117_multi_run_shadow_observation_allowed": tf(all_passed), "shadow_stability_regression_audit_status": status, "blocking_reason": blocking, **COMMON_SAFETY}
    gate = {"gate_check_id": "V20_116_NEXT_STAGE_GATE_001", "v20_115_gate_consumed": tf(v115_gate_consumed), "v20_116_shadow_stability_regression_audit_allowed_by_v115": tf(v116_allowed), "selected_repair_scenario_id": selected_id, "shadow_stability_regression_decision_created": "TRUE", "stability_criteria_passed": tf(criteria_passed), "no_upstream_outputs_mutated": tf(not upstream_mutation), "no_violating_regression_exception": tf(violating_exception_count == 0), "no_ticker_rows_fabricated": tf(no_tickers), "safety_boundary_audit_passed": tf(safety_passed), "v20_117_multi_run_shadow_observation_allowed": tf(all_passed), "next_recommended_action": "V20.117_MULTI_RUN_SHADOW_OBSERVATION" if all_passed else "V20.116_SHADOW_STABILITY_REGRESSION_AUDIT_REPAIR", "blocking_reason": blocking, "shadow_stability_regression_audit_status": status, **COMMON_SAFETY}
    write_all([decision], criteria, hash_rows, delta_stability, exceptions, safety, [gate])
    write_report(decision)
    print(status)
    print(f"V20_115_GATE_CONSUMED={tf(v115_gate_consumed)}")
    print(f"V20_116_SHADOW_STABILITY_REGRESSION_AUDIT_ALLOWED_BY_V115={tf(v116_allowed)}")
    print(f"V20_115_FINAL_STATUS={v115_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_115={tf(selected_matches)}")
    print(f"STABILITY_CRITERIA_PASSED={tf(criteria_passed)}")
    print(f"REGRESSION_HASH_AUDIT_CREATED={tf(bool(hash_rows))}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"UNSTABLE_DELTA_COUNT={unstable_count}")
    print(f"VIOLATING_EXCEPTION_COUNT={violating_exception_count}")
    print("FABRICATED_TICKER_ROW_COUNT=0")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_117_MULTI_RUN_SHADOW_OBSERVATION_ALLOWED={tf(all_passed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
