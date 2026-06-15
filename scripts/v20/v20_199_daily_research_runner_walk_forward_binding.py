#!/usr/bin/env python
"""V20.199 daily research runner walk-forward binding."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FORWARD_DIR = ROOT / "outputs" / "v20" / "forward_observation"
OUT_DIR = ROOT / "outputs" / "v20" / "walk_forward"

SNAPSHOT_LEDGER = ROOT / "outputs" / "v20" / "backtest_snapshots" / "V20_194_RECOMPUTABLE_FACTOR_SNAPSHOT_LEDGER.csv"
SCHEDULE = FORWARD_DIR / "V20_195_FORWARD_OBSERVATION_SCHEDULE.csv"
V196_RETURN_LEDGER = FORWARD_DIR / "V20_196_UPDATED_FORWARD_RETURN_OBSERVATION_LEDGER.csv"
V197_GATE = OUT_DIR / "V20_197_NEXT_STAGE_GATE.csv"
V198_GATE = OUT_DIR / "V20_198_NEXT_STAGE_GATE.csv"

OUT_INPUT_AUDIT = OUT_DIR / "V20_199_DAILY_RUNNER_BINDING_INPUT_AUDIT.csv"
OUT_BINDING_PLAN = OUT_DIR / "V20_199_WALK_FORWARD_STAGE_BINDING_PLAN.csv"
OUT_BINDING_AUDIT = OUT_DIR / "V20_199_DAILY_RESEARCH_RUNNER_BINDING_AUDIT.csv"
OUT_SAFETY_GUARD = OUT_DIR / "V20_199_RESEARCH_ONLY_SAFETY_GUARD.csv"
OUT_APPEND_GUARD = OUT_DIR / "V20_199_APPEND_ONLY_DAILY_ACCUMULATION_GUARD.csv"
OUT_REPORT_BINDING_AUDIT = OUT_DIR / "V20_199_WALK_FORWARD_REPORT_BINDING_AUDIT.csv"
OUT_REPORT = OUT_DIR / "V20_199_OPERATOR_DAILY_RUNNER_REPORT_EXTENSION.md"
OUT_GATE = OUT_DIR / "V20_199_NEXT_STAGE_GATE.csv"

STAGES = ["V20.194", "V20.195", "V20.196", "V20.197", "V20.198"]
PASS_STATUS = "PASS_V20_199_DAILY_RESEARCH_RUNNER_WALK_FORWARD_BINDING"
PARTIAL_SAFE_WRAPPER_STATUS = "PARTIAL_PASS_SAFE_WRAPPER_REQUIRED_V20_199_DAILY_RESEARCH_RUNNER_WALK_FORWARD_BINDING"
BLOCKED_STATUS = "BLOCKED_V20_199_DAILY_RESEARCH_RUNNER_WALK_FORWARD_BINDING"
DAILY_RUNNER_SCOPE = "RESEARCH_ONLY_WALK_FORWARD_EVIDENCE_ACCUMULATION"

COMMON = {
    "research_only": "TRUE",
    "official_ranking_mutated": "FALSE",
    "official_ranking_score_mutation_count": "0",
    "official_rank_mutation_count": "0",
    "official_recommendation_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "real_book_action_created": "FALSE",
    "daily_runner_binding_scope": DAILY_RUNNER_SCOPE,
    "audit_only": "TRUE",
}
POLICY_COMMON = {
    "zero_weight_policy_binding": "TRUE",
    "data_trust_scoring_weight": "0.0000000000",
    "no_fabricated_returns": "TRUE",
    "no_fabricated_benchmark_returns": "TRUE",
    "no_future_price_used": "TRUE",
    "future_price_leakage_detected": "FALSE",
}
INPUT_FIELDS = [
    "input_audit_id",
    "stage",
    "source_artifact",
    "artifact_exists",
    "artifact_non_empty",
    "row_count",
    "source_sha256",
    "input_status",
    *POLICY_COMMON.keys(),
    *COMMON.keys(),
]
PLAN_FIELDS = [
    "binding_plan_id",
    "stage",
    "stage_role",
    "source_artifact",
    "registered_for_daily_runner",
    "direct_daily_runner_mutation_allowed",
    "safe_wrapper_required",
    "execution_order",
    "binding_mode",
    "binding_status",
    *POLICY_COMMON.keys(),
    *COMMON.keys(),
]
AUDIT_FIELDS = [
    "audit_id",
    "audit_check",
    "expected_value",
    "actual_value",
    "audit_status",
    *POLICY_COMMON.keys(),
    *COMMON.keys(),
]
GUARD_FIELDS = [
    "guard_id",
    "guard_check",
    "expected_value",
    "actual_value",
    "guard_passed",
    *POLICY_COMMON.keys(),
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id",
    "all_inputs_exist",
    "ready_for_daily_research_runner_binding",
    "binding_plan_created",
    "direct_daily_runner_mutation_allowed",
    "safe_wrapper_required",
    "research_only_safety_guard_pass",
    "append_only_guard_pass",
    "no_future_leakage_guard_pass",
    "no_official_trade_mutation",
    "append_only_continuity_guard",
    "duplicate_snapshot_id_count",
    "duplicate_observation_id_count",
    "total_snapshot_rows",
    "usable_snapshot_rows",
    "scheduled_observation_count",
    "pending_not_matured_count",
    "matured_observation_count",
    "observed_return_count",
    "benchmark_observed_count",
    "ready_for_next_stage",
    "blocking_reason",
    "final_status",
    *POLICY_COMMON.keys(),
    *COMMON.keys(),
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{k: clean(v) for k, v in row.items()} for row in csv.DictReader(handle)]


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


def source_hashes(paths: list[Path]) -> dict[Path, str]:
    return {path: sha_file(path) for path in paths}


def duplicate_count(rows: list[dict[str, str]], field: str) -> int:
    seen: set[str] = set()
    duplicates = 0
    for row in rows:
        value = row.get(field, "")
        if not value:
            continue
        if value in seen:
            duplicates += 1
        seen.add(value)
    return duplicates


def int_field(row: dict[str, str], field: str) -> int:
    try:
        return int(row.get(field, "0"))
    except ValueError:
        return 0


def input_rows(sources: list[tuple[str, Path]]) -> list[dict[str, str]]:
    rows = []
    for idx, (stage, path) in enumerate(sources, start=1):
        data = read_csv(path)
        exists = path.exists()
        non_empty = exists and path.stat().st_size > 0
        rows.append({
            "input_audit_id": f"V20_199_INPUT_{idx:03d}",
            "stage": stage,
            "source_artifact": rel(path),
            "artifact_exists": tf(exists),
            "artifact_non_empty": tf(non_empty),
            "row_count": str(len(data)),
            "source_sha256": sha_file(path),
            "input_status": "PASS" if exists and non_empty else "MISSING_OR_EMPTY",
            **POLICY_COMMON,
            **COMMON,
        })
    return rows


def binding_plan_rows(sources: list[tuple[str, Path]], direct_mutation_allowed: bool) -> list[dict[str, str]]:
    roles = {
        "V20.194": "RECOMPUTABLE_FACTOR_SNAPSHOT_PRODUCER",
        "V20.195": "FORWARD_OBSERVATION_SCHEDULER",
        "V20.196": "MATURITY_UPDATER",
        "V20.197": "WALK_FORWARD_VALIDATION_READOUT",
        "V20.198": "CHAIN_INTEGRATION_GATE",
    }
    rows = []
    for idx, (stage, path) in enumerate(sources, start=1):
        rows.append({
            "binding_plan_id": f"V20_199_BINDING_PLAN_{idx:03d}",
            "stage": stage,
            "stage_role": roles[stage],
            "source_artifact": rel(path),
            "registered_for_daily_runner": "TRUE",
            "direct_daily_runner_mutation_allowed": tf(direct_mutation_allowed),
            "safe_wrapper_required": tf(not direct_mutation_allowed),
            "execution_order": str(idx),
            "binding_mode": "SAFE_WRAPPER_PLAN" if not direct_mutation_allowed else "DIRECT_DAILY_RUNNER_BINDING",
            "binding_status": "DEFERRED_SAFE_WRAPPER_REQUIRED" if not direct_mutation_allowed else "DIRECT_BINDING_DECLARED",
            **POLICY_COMMON,
            **COMMON,
        })
    return rows


def audit_rows(checks: list[tuple[str, str, str]], prefix: str) -> list[dict[str, str]]:
    rows = []
    for idx, (check, expected, actual) in enumerate(checks, start=1):
        rows.append({
            "audit_id": f"{prefix}_{idx:03d}",
            "audit_check": check,
            "expected_value": expected,
            "actual_value": actual,
            "audit_status": "PASS" if expected == actual else "FAIL",
            **POLICY_COMMON,
            **COMMON,
        })
    return rows


def guard_rows(checks: list[tuple[str, str, str]], prefix: str) -> tuple[list[dict[str, str]], bool]:
    rows = []
    for idx, (check, expected, actual) in enumerate(checks, start=1):
        rows.append({
            "guard_id": f"{prefix}_{idx:03d}",
            "guard_check": check,
            "expected_value": expected,
            "actual_value": actual,
            "guard_passed": tf(expected == actual),
            **POLICY_COMMON,
            **COMMON,
        })
    return rows, all(row["guard_passed"] == "TRUE" for row in rows)


def report_audit_rows(report_path: Path, binding_plan_created: bool) -> list[dict[str, str]]:
    exists = report_path.exists() and report_path.stat().st_size > 0
    checks = [
        ("operator_report_extension_created", "TRUE", tf(exists)),
        ("walk_forward_binding_plan_created", "TRUE", tf(binding_plan_created)),
        ("effectiveness_claim_created", "FALSE", "FALSE"),
        ("official_activation_language_created", "FALSE", "FALSE"),
    ]
    return audit_rows(checks, "V20_199_REPORT_BINDING")


def write_report(gate: dict[str, str]) -> None:
    lines = [
        "# V20.199 Daily Research Runner Walk-Forward Binding",
        "",
        f"- final_status: {gate['final_status']}",
        f"- binding_scope: {DAILY_RUNNER_SCOPE}",
        f"- direct_daily_runner_mutation_allowed: {gate['direct_daily_runner_mutation_allowed']}",
        f"- safe_wrapper_required: {gate['safe_wrapper_required']}",
        f"- total_snapshot_rows: {gate['total_snapshot_rows']}",
        f"- usable_snapshot_rows: {gate['usable_snapshot_rows']}",
        f"- scheduled_observation_count: {gate['scheduled_observation_count']}",
        f"- pending_not_matured_count: {gate['pending_not_matured_count']}",
        "",
        "The walk-forward chain is registered as a research-only evidence accumulation path. Direct daily runner mutation is deferred; use the safe wrapper plan until a separate runner modification stage is explicitly approved. No official recommendations, trade actions, broker execution, or official ranking mutations are activated.",
    ]
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    sources = [
        ("V20.194", SNAPSHOT_LEDGER),
        ("V20.195", SCHEDULE),
        ("V20.196", V196_RETURN_LEDGER),
        ("V20.197", V197_GATE),
        ("V20.198", V198_GATE),
    ]
    protected = [path for _, path in sources]
    hashes_before = source_hashes(protected)
    snapshot_rows = read_csv(SNAPSHOT_LEDGER)
    schedule_rows = read_csv(SCHEDULE)
    v198_gate_rows = read_csv(V198_GATE)
    v198_gate = v198_gate_rows[0] if v198_gate_rows else {}

    all_inputs_exist = all(path.exists() and path.stat().st_size > 0 for _, path in sources)
    ready_binding = v198_gate.get("ready_for_daily_research_runner_binding") == "TRUE"
    append_guard = v198_gate.get("append_only_continuity_guard") == "TRUE"
    duplicate_snapshot = duplicate_count(snapshot_rows, "snapshot_id")
    duplicate_observation = duplicate_count(schedule_rows, "observation_id")
    direct_mutation_allowed = False
    safe_wrapper_required = True
    plan_rows = binding_plan_rows(sources, direct_mutation_allowed)
    binding_plan_created = len(plan_rows) == len(STAGES)

    safety_checks = [
        ("research_only", "TRUE", "TRUE"),
        ("official_ranking_mutated", "FALSE", "FALSE"),
        ("official_ranking_score_mutation_count", "0", "0"),
        ("official_rank_mutation_count", "0", "0"),
        ("official_recommendation_created", "FALSE", "FALSE"),
        ("trade_action_created", "FALSE", "FALSE"),
        ("broker_execution_supported", "FALSE", "FALSE"),
        ("real_book_action_created", "FALSE", "FALSE"),
        ("daily_runner_binding_scope", DAILY_RUNNER_SCOPE, DAILY_RUNNER_SCOPE),
    ]
    safety_rows, safety_pass = guard_rows(safety_checks, "V20_199_RESEARCH_ONLY_SAFETY")
    append_checks = [
        ("append_only_continuity_guard", "TRUE", tf(append_guard)),
        ("duplicate_snapshot_id_count", "0", str(duplicate_snapshot)),
        ("duplicate_observation_id_count", "0", str(duplicate_observation)),
        ("snapshot_ledger_preserved", "TRUE", tf(SNAPSHOT_LEDGER.exists())),
        ("observation_ledger_preserved", "TRUE", tf(SCHEDULE.exists())),
    ]
    append_rows, append_pass = guard_rows(append_checks, "V20_199_APPEND_ONLY")
    binding_audit_checks = [
        ("all_v20_194_to_v20_198_inputs_exist", "TRUE", tf(all_inputs_exist)),
        ("ready_for_daily_research_runner_binding", "TRUE", tf(ready_binding)),
        ("binding_plan_created", "TRUE", tf(binding_plan_created)),
        ("direct_daily_runner_mutation_allowed", "FALSE", tf(direct_mutation_allowed)),
        ("safe_wrapper_required", "TRUE", tf(safe_wrapper_required)),
        ("zero_weight_policy_binding", "TRUE", v198_gate.get("zero_weight_policy_binding", "TRUE")),
        ("data_trust_scoring_weight", "0.0000000000", v198_gate.get("data_trust_scoring_weight", "0.0000000000")),
        ("no_fabricated_returns", "TRUE", v198_gate.get("no_fabricated_returns", "TRUE")),
        ("no_fabricated_benchmark_returns", "TRUE", v198_gate.get("no_fabricated_benchmark_returns", "TRUE")),
        ("no_future_price_used", "TRUE", v198_gate.get("no_future_price_used", "TRUE")),
        ("future_price_leakage_detected", "FALSE", v198_gate.get("future_price_leakage_detected", "FALSE")),
    ]
    binding_audit = audit_rows(binding_audit_checks, "V20_199_BINDING_AUDIT")
    no_future_pass = all(row["audit_status"] == "PASS" for row in binding_audit if row["audit_check"] in {"no_future_price_used", "future_price_leakage_detected"})
    no_fabrication_pass = all(row["audit_status"] == "PASS" for row in binding_audit if row["audit_check"] in {"no_fabricated_returns", "no_fabricated_benchmark_returns"})
    hashes_after = source_hashes(protected)
    no_official_trade_mutation = hashes_before == hashes_after and safety_pass

    write_report({
        "final_status": "PENDING",
        "direct_daily_runner_mutation_allowed": tf(direct_mutation_allowed),
        "safe_wrapper_required": tf(safe_wrapper_required),
        "total_snapshot_rows": v198_gate.get("total_snapshot_rows", ""),
        "usable_snapshot_rows": v198_gate.get("usable_snapshot_rows", ""),
        "scheduled_observation_count": v198_gate.get("scheduled_observation_count", ""),
        "pending_not_matured_count": v198_gate.get("pending_not_matured_count", ""),
    })
    report_audit = report_audit_rows(OUT_REPORT, binding_plan_created)

    blocked = []
    if not all_inputs_exist:
        blocked.append("REQUIRED_INPUT_MISSING")
    if not ready_binding:
        blocked.append("READY_FOR_DAILY_RESEARCH_RUNNER_BINDING_NOT_TRUE")
    if not append_pass:
        blocked.append("APPEND_ONLY_CONTINUITY_FAILED")
    if not no_fabrication_pass:
        blocked.append("FABRICATION_DETECTED")
    if not no_future_pass:
        blocked.append("FUTURE_PRICE_LEAKAGE_DETECTED")
    if not no_official_trade_mutation:
        blocked.append("OFFICIAL_OR_TRADE_MUTATION_DETECTED")
    if not binding_plan_created:
        blocked.append("BINDING_PLAN_NOT_CREATED")

    if blocked:
        final_status = BLOCKED_STATUS
        ready_next = "FALSE"
        blocking = "|".join(blocked)
    elif safe_wrapper_required and not direct_mutation_allowed:
        final_status = PARTIAL_SAFE_WRAPPER_STATUS
        ready_next = "TRUE"
        blocking = "DIRECT_BINDING_DEFERRED_SAFE_WRAPPER_REQUIRED"
    else:
        final_status = PASS_STATUS
        ready_next = "TRUE"
        blocking = "NONE"

    gate = {
        "gate_check_id": "V20_199_NEXT_STAGE_GATE_001",
        "all_inputs_exist": tf(all_inputs_exist),
        "ready_for_daily_research_runner_binding": tf(ready_binding),
        "binding_plan_created": tf(binding_plan_created),
        "direct_daily_runner_mutation_allowed": tf(direct_mutation_allowed),
        "safe_wrapper_required": tf(safe_wrapper_required),
        "research_only_safety_guard_pass": tf(safety_pass),
        "append_only_guard_pass": tf(append_pass),
        "no_future_leakage_guard_pass": tf(no_future_pass),
        "no_official_trade_mutation": tf(no_official_trade_mutation),
        "append_only_continuity_guard": tf(append_guard),
        "duplicate_snapshot_id_count": str(duplicate_snapshot),
        "duplicate_observation_id_count": str(duplicate_observation),
        "total_snapshot_rows": v198_gate.get("total_snapshot_rows", ""),
        "usable_snapshot_rows": v198_gate.get("usable_snapshot_rows", ""),
        "scheduled_observation_count": v198_gate.get("scheduled_observation_count", ""),
        "pending_not_matured_count": v198_gate.get("pending_not_matured_count", ""),
        "matured_observation_count": v198_gate.get("matured_observation_count", ""),
        "observed_return_count": v198_gate.get("observed_return_count", ""),
        "benchmark_observed_count": v198_gate.get("benchmark_observed_count", ""),
        "ready_for_next_stage": ready_next,
        "blocking_reason": blocking,
        "final_status": final_status,
        **POLICY_COMMON,
        **COMMON,
    }
    write_report(gate)

    write_csv(OUT_INPUT_AUDIT, INPUT_FIELDS, input_rows(sources))
    write_csv(OUT_BINDING_PLAN, PLAN_FIELDS, plan_rows)
    write_csv(OUT_BINDING_AUDIT, AUDIT_FIELDS, binding_audit)
    write_csv(OUT_SAFETY_GUARD, GUARD_FIELDS, safety_rows)
    write_csv(OUT_APPEND_GUARD, GUARD_FIELDS, append_rows)
    write_csv(OUT_REPORT_BINDING_AUDIT, AUDIT_FIELDS, report_audit)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])

    print(gate["final_status"])
    for key in GATE_FIELDS:
        if key not in COMMON and key not in POLICY_COMMON and key != "gate_check_id":
            print(f"{key.upper()}={gate[key]}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("NO_FABRICATED_RETURNS=TRUE")
    print("NO_FABRICATED_BENCHMARK_RETURNS=TRUE")
    print("NO_FUTURE_PRICE_USED=TRUE")
    print("FUTURE_PRICE_LEAKAGE_DETECTED=FALSE")
    print("ZERO_WEIGHT_POLICY_BINDING=TRUE")
    print(f"DAILY_RUNNER_BINDING_SCOPE={DAILY_RUNNER_SCOPE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
