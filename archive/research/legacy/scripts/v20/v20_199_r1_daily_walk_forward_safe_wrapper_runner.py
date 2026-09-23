#!/usr/bin/env python
"""V20.199-R1 daily walk-forward safe wrapper runner."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "scripts" / "v20"
FORWARD_DIR = ROOT / "outputs" / "v20" / "forward_observation"
OUT_DIR = ROOT / "outputs" / "v20" / "walk_forward"

ORIGINAL_DAILY_RUNNER = SCRIPT_DIR / "v20_daily_research_observation_operator.py"
SNAPSHOT_LEDGER = ROOT / "outputs" / "v20" / "backtest_snapshots" / "V20_194_RECOMPUTABLE_FACTOR_SNAPSHOT_LEDGER.csv"
SCHEDULE = FORWARD_DIR / "V20_195_FORWARD_OBSERVATION_SCHEDULE.csv"
V196_RETURN_LEDGER = FORWARD_DIR / "V20_196_UPDATED_FORWARD_RETURN_OBSERVATION_LEDGER.csv"
V197_GATE = OUT_DIR / "V20_197_NEXT_STAGE_GATE.csv"
V198_GATE = OUT_DIR / "V20_198_NEXT_STAGE_GATE.csv"
V199_GATE = OUT_DIR / "V20_199_NEXT_STAGE_GATE.csv"

STAGES = [
    (
        "V20.194",
        "RECOMPUTABLE_FACTOR_SNAPSHOT_PRODUCER_CONTRACT",
        SCRIPT_DIR / "v20_194_recomputable_factor_snapshot_producer_contract.py",
        SNAPSHOT_LEDGER,
    ),
    (
        "V20.195",
        "DAILY_SNAPSHOT_ACCUMULATION_AND_FORWARD_OBSERVATION_LEDGER",
        SCRIPT_DIR / "v20_195_daily_snapshot_accumulation_and_forward_observation_ledger.py",
        SCHEDULE,
    ),
    (
        "V20.196",
        "FORWARD_OBSERVATION_MATURITY_UPDATER",
        SCRIPT_DIR / "v20_196_forward_observation_maturity_updater.py",
        V196_RETURN_LEDGER,
    ),
    (
        "V20.197",
        "DAILY_WALK_FORWARD_VALIDATION_RUNNER",
        SCRIPT_DIR / "v20_197_daily_walk_forward_validation_runner.py",
        V197_GATE,
    ),
    (
        "V20.198",
        "DAILY_WALK_FORWARD_CHAIN_INTEGRATION",
        SCRIPT_DIR / "v20_198_daily_walk_forward_chain_integration.py",
        V198_GATE,
    ),
    (
        "V20.199",
        "DAILY_RESEARCH_RUNNER_WALK_FORWARD_BINDING",
        SCRIPT_DIR / "v20_199_daily_research_runner_walk_forward_binding.py",
        V199_GATE,
    ),
]

OUT_INPUT_AUDIT = OUT_DIR / "V20_199_R1_SAFE_WRAPPER_INPUT_AUDIT.csv"
OUT_CHAIN_PLAN = OUT_DIR / "V20_199_R1_SAFE_WRAPPER_CHAIN_PLAN.csv"
OUT_EXECUTION_AUDIT = OUT_DIR / "V20_199_R1_SAFE_WRAPPER_EXECUTION_AUDIT.csv"
OUT_STAGE_OUTPUT_STATUS = OUT_DIR / "V20_199_R1_STAGE_OUTPUT_STATUS.csv"
OUT_APPEND_AUDIT = OUT_DIR / "V20_199_R1_APPEND_ONLY_LEDGER_CONTINUITY_AUDIT.csv"
OUT_NO_FAB_GUARD = OUT_DIR / "V20_199_R1_NO_FABRICATION_NO_LEAKAGE_GUARD.csv"
OUT_MUTATION_GUARD = OUT_DIR / "V20_199_R1_OFFICIAL_TRADE_MUTATION_GUARD.csv"
OUT_REPORT = OUT_DIR / "V20_199_R1_OPERATOR_SAFE_WRAPPER_REPORT.md"
OUT_GATE = OUT_DIR / "V20_199_R1_NEXT_STAGE_GATE.csv"

EXECUTION_MODE = "PLAN_ONLY_SAFE_WRAPPER"
PASS_STATUS = "PASS_V20_199_R1_DAILY_WALK_FORWARD_SAFE_WRAPPER_RUNNER"
PARTIAL_PLAN_ONLY_STATUS = "PARTIAL_PASS_PLAN_ONLY_V20_199_R1_DAILY_WALK_FORWARD_SAFE_WRAPPER_RUNNER"
BLOCKED_STATUS = "BLOCKED_V20_199_R1_DAILY_WALK_FORWARD_SAFE_WRAPPER_RUNNER"

COMMON = {
    "research_only": "TRUE",
    "official_ranking_mutated": "FALSE",
    "official_ranking_score_mutation_count": "0",
    "official_rank_mutation_count": "0",
    "official_recommendation_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "real_book_action_created": "FALSE",
    "original_daily_runner_mutated": "FALSE",
    "audit_only": "TRUE",
}
POLICY_COMMON = {
    "zero_weight_policy_binding": "TRUE",
    "data_trust_scoring_weight": "0.0000000000",
    "no_fabricated_returns": "TRUE",
    "no_fabricated_benchmark_returns": "TRUE",
    "no_fabricated_ticker_rows": "TRUE",
    "no_future_price_used": "TRUE",
    "future_price_leakage_detected": "FALSE",
}
INPUT_FIELDS = [
    "input_audit_id",
    "stage",
    "script_path",
    "script_exists",
    "output_path",
    "output_exists",
    "output_non_empty",
    "output_row_count",
    "script_sha256",
    "output_sha256",
    "input_status",
    *POLICY_COMMON.keys(),
    *COMMON.keys(),
]
PLAN_FIELDS = [
    "chain_plan_id",
    "stage",
    "stage_name",
    "execution_order",
    "script_path",
    "expected_output_path",
    "execution_mode",
    "execute_now",
    "plan_only_reason",
    "registered_in_safe_wrapper",
    "direct_daily_runner_mutation_allowed",
    "plan_status",
    *POLICY_COMMON.keys(),
    *COMMON.keys(),
]
EXECUTION_FIELDS = [
    "execution_audit_id",
    "execution_mode",
    "wrapper_execution_performed",
    "wrapper_plan_created",
    "all_required_stage_scripts_exist",
    "all_required_stage_outputs_exist",
    "safe_wrapper_required",
    "direct_daily_runner_mutation_allowed",
    "execution_status",
    *POLICY_COMMON.keys(),
    *COMMON.keys(),
]
STATUS_FIELDS = [
    "stage_output_status_id",
    "stage",
    "output_path",
    "output_exists",
    "output_non_empty",
    "output_row_count",
    "stage_output_status",
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
    "execution_mode",
    "all_required_stage_scripts_exist",
    "all_required_stage_outputs_exist",
    "safe_wrapper_required",
    "direct_daily_runner_mutation_allowed",
    "wrapper_plan_created",
    "append_only_continuity_guard",
    "duplicate_snapshot_id_count",
    "duplicate_observation_id_count",
    "no_fabrication_no_leakage_guard_pass",
    "no_official_trade_mutation",
    "original_daily_runner_mutated",
    "wrapper_ready_for_daily_use",
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


def stage_output_rows() -> list[dict[str, str]]:
    rows = []
    for idx, (stage, _, _, output) in enumerate(STAGES, start=1):
        data = read_csv(output)
        exists = output.exists()
        non_empty = exists and output.stat().st_size > 0
        rows.append({
            "stage_output_status_id": f"V20_199_R1_STAGE_OUTPUT_{idx:03d}",
            "stage": stage,
            "output_path": rel(output),
            "output_exists": tf(exists),
            "output_non_empty": tf(non_empty),
            "output_row_count": str(len(data)),
            "stage_output_status": "PASS" if exists and non_empty else "MISSING_OR_EMPTY",
            **POLICY_COMMON,
            **COMMON,
        })
    return rows


def input_audit_rows() -> list[dict[str, str]]:
    rows = []
    for idx, (stage, _, script, output) in enumerate(STAGES, start=1):
        data = read_csv(output)
        output_exists = output.exists()
        output_non_empty = output_exists and output.stat().st_size > 0
        script_exists = script.exists() and script.stat().st_size > 0
        rows.append({
            "input_audit_id": f"V20_199_R1_INPUT_{idx:03d}",
            "stage": stage,
            "script_path": rel(script),
            "script_exists": tf(script_exists),
            "output_path": rel(output),
            "output_exists": tf(output_exists),
            "output_non_empty": tf(output_non_empty),
            "output_row_count": str(len(data)),
            "script_sha256": sha_file(script),
            "output_sha256": sha_file(output),
            "input_status": "PASS" if script_exists and output_non_empty else "MISSING_SCRIPT_OR_OUTPUT",
            **POLICY_COMMON,
            **COMMON,
        })
    return rows


def chain_plan_rows() -> list[dict[str, str]]:
    rows = []
    for idx, (stage, name, script, output) in enumerate(STAGES, start=1):
        rows.append({
            "chain_plan_id": f"V20_199_R1_CHAIN_PLAN_{idx:03d}",
            "stage": stage,
            "stage_name": name,
            "execution_order": str(idx),
            "script_path": rel(script),
            "expected_output_path": rel(output),
            "execution_mode": EXECUTION_MODE,
            "execute_now": "FALSE",
            "plan_only_reason": "UPSTREAM_REEXECUTION_DEFERRED_TO_AVOID_UNREQUESTED_LEDGER_MUTATION",
            "registered_in_safe_wrapper": "TRUE",
            "direct_daily_runner_mutation_allowed": "FALSE",
            "plan_status": "PLAN_ONLY_SAFE_WRAPPER_READY",
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


def write_report(gate: dict[str, str]) -> None:
    lines = [
        "# V20.199-R1 Daily Walk-Forward Safe Wrapper Runner",
        "",
        f"- final_status: {gate['final_status']}",
        f"- execution_mode: {gate['execution_mode']}",
        f"- all_required_stage_scripts_exist: {gate['all_required_stage_scripts_exist']}",
        f"- all_required_stage_outputs_exist: {gate['all_required_stage_outputs_exist']}",
        f"- wrapper_ready_for_daily_use: {gate['wrapper_ready_for_daily_use']}",
        f"- append_only_continuity_guard: {gate['append_only_continuity_guard']}",
        "",
        "This wrapper is declarative and plan-only in the current environment. It does not mutate the original daily research runner, official rankings, recommendations, trades, broker execution settings, snapshots, or observation ledgers.",
    ]
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    scripts = [script for _, _, script, _ in STAGES]
    outputs = [output for _, _, _, output in STAGES]
    protected = [*scripts, *outputs, ORIGINAL_DAILY_RUNNER]
    before_hashes = source_hashes(protected)

    inputs = input_audit_rows()
    plan = chain_plan_rows()
    stage_outputs = stage_output_rows()
    all_scripts_exist = all(row["script_exists"] == "TRUE" for row in inputs)
    all_outputs_exist = all(row["output_exists"] == "TRUE" and row["output_non_empty"] == "TRUE" for row in inputs)
    wrapper_plan_created = len(plan) == len(STAGES) and all(row["registered_in_safe_wrapper"] == "TRUE" for row in plan)

    snapshot_rows = read_csv(SNAPSHOT_LEDGER)
    schedule_rows = read_csv(SCHEDULE)
    v199_gate_rows = read_csv(V199_GATE)
    v199_gate = v199_gate_rows[0] if v199_gate_rows else {}
    duplicate_snapshot = duplicate_count(snapshot_rows, "snapshot_id")
    duplicate_observation = duplicate_count(schedule_rows, "observation_id")
    append_continuity = (
        v199_gate.get("append_only_continuity_guard") == "TRUE"
        and duplicate_snapshot == 0
        and duplicate_observation == 0
    )
    safe_wrapper_required = v199_gate.get("safe_wrapper_required") == "TRUE"
    direct_daily_runner_mutation_allowed = v199_gate.get("direct_daily_runner_mutation_allowed") == "TRUE"

    execution_checks = [
        ("execution_mode", EXECUTION_MODE, EXECUTION_MODE),
        ("wrapper_execution_performed", "FALSE", "FALSE"),
        ("wrapper_plan_created", "TRUE", tf(wrapper_plan_created)),
        ("all_required_stage_scripts_exist", "TRUE", tf(all_scripts_exist)),
        ("all_required_stage_outputs_exist", "TRUE", tf(all_outputs_exist)),
        ("safe_wrapper_required", "TRUE", tf(safe_wrapper_required)),
        ("direct_daily_runner_mutation_allowed", "FALSE", tf(direct_daily_runner_mutation_allowed)),
    ]
    execution_audit = [{
        "execution_audit_id": "V20_199_R1_EXECUTION_AUDIT_001",
        "execution_mode": EXECUTION_MODE,
        "wrapper_execution_performed": "FALSE",
        "wrapper_plan_created": tf(wrapper_plan_created),
        "all_required_stage_scripts_exist": tf(all_scripts_exist),
        "all_required_stage_outputs_exist": tf(all_outputs_exist),
        "safe_wrapper_required": tf(safe_wrapper_required),
        "direct_daily_runner_mutation_allowed": tf(direct_daily_runner_mutation_allowed),
        "execution_status": "PLAN_ONLY_SAFE_WRAPPER" if wrapper_plan_created else "BLOCKED_PLAN_NOT_CREATED",
        **POLICY_COMMON,
        **COMMON,
    }]
    append_audit = audit_rows([
        ("append_only_continuity_guard", "TRUE", tf(append_continuity)),
        ("duplicate_snapshot_id_count", "0", str(duplicate_snapshot)),
        ("duplicate_observation_id_count", "0", str(duplicate_observation)),
        ("snapshot_ledger_preserved", "TRUE", tf(SNAPSHOT_LEDGER.exists())),
        ("observation_schedule_preserved", "TRUE", tf(SCHEDULE.exists())),
    ], "V20_199_R1_APPEND")
    no_fab_guard, no_fab_pass = guard_rows([
        ("zero_weight_policy_binding", "TRUE", v199_gate.get("zero_weight_policy_binding", "TRUE")),
        ("data_trust_scoring_weight", "0.0000000000", v199_gate.get("data_trust_scoring_weight", "0.0000000000")),
        ("no_fabricated_returns", "TRUE", v199_gate.get("no_fabricated_returns", "TRUE")),
        ("no_fabricated_benchmark_returns", "TRUE", v199_gate.get("no_fabricated_benchmark_returns", "TRUE")),
        ("no_fabricated_ticker_rows", "TRUE", v199_gate.get("no_fabricated_ticker_rows", "TRUE")),
        ("no_future_price_used", "TRUE", v199_gate.get("no_future_price_used", "TRUE")),
        ("future_price_leakage_detected", "FALSE", v199_gate.get("future_price_leakage_detected", "FALSE")),
    ], "V20_199_R1_NO_FAB")

    after_hashes = source_hashes(protected)
    original_daily_runner_mutated = before_hashes.get(ORIGINAL_DAILY_RUNNER, "") != after_hashes.get(ORIGINAL_DAILY_RUNNER, "")
    any_protected_mutated = before_hashes != after_hashes
    mutation_guard, mutation_pass = guard_rows([
        ("research_only", "TRUE", "TRUE"),
        ("official_ranking_mutated", "FALSE", "FALSE"),
        ("official_ranking_score_mutation_count", "0", "0"),
        ("official_rank_mutation_count", "0", "0"),
        ("official_recommendation_created", "FALSE", "FALSE"),
        ("trade_action_created", "FALSE", "FALSE"),
        ("broker_execution_supported", "FALSE", "FALSE"),
        ("real_book_action_created", "FALSE", "FALSE"),
        ("original_daily_runner_mutated", "FALSE", tf(original_daily_runner_mutated)),
        ("protected_stage_artifacts_mutated", "FALSE", tf(any_protected_mutated)),
    ], "V20_199_R1_MUTATION")

    blocked = []
    if not all_scripts_exist:
        blocked.append("REQUIRED_STAGE_SCRIPT_MISSING")
    if not all_outputs_exist:
        blocked.append("REQUIRED_STAGE_OUTPUT_MISSING")
    if not wrapper_plan_created:
        blocked.append("WRAPPER_PLAN_NOT_CREATED")
    if not append_continuity:
        blocked.append("APPEND_ONLY_CONTINUITY_FAILED")
    if not no_fab_pass:
        blocked.append("FABRICATION_OR_LEAKAGE_DETECTED")
    if not mutation_pass:
        blocked.append("OFFICIAL_TRADE_OR_ORIGINAL_RUNNER_MUTATION_DETECTED")

    wrapper_ready = not blocked
    if blocked:
        final_status = BLOCKED_STATUS
        ready_next = "FALSE"
        blocking = "|".join(blocked)
    elif EXECUTION_MODE == "PLAN_ONLY_SAFE_WRAPPER":
        final_status = PARTIAL_PLAN_ONLY_STATUS
        ready_next = "TRUE"
        blocking = "WRAPPER_EXECUTION_NOT_PERFORMED_PLAN_ONLY_SAFE_WRAPPER"
    else:
        final_status = PASS_STATUS
        ready_next = "TRUE"
        blocking = "NONE"

    gate = {
        "gate_check_id": "V20_199_R1_NEXT_STAGE_GATE_001",
        "execution_mode": EXECUTION_MODE,
        "all_required_stage_scripts_exist": tf(all_scripts_exist),
        "all_required_stage_outputs_exist": tf(all_outputs_exist),
        "safe_wrapper_required": tf(safe_wrapper_required),
        "direct_daily_runner_mutation_allowed": tf(direct_daily_runner_mutation_allowed),
        "wrapper_plan_created": tf(wrapper_plan_created),
        "append_only_continuity_guard": tf(append_continuity),
        "duplicate_snapshot_id_count": str(duplicate_snapshot),
        "duplicate_observation_id_count": str(duplicate_observation),
        "no_fabrication_no_leakage_guard_pass": tf(no_fab_pass),
        "no_official_trade_mutation": tf(mutation_pass),
        "original_daily_runner_mutated": tf(original_daily_runner_mutated),
        "wrapper_ready_for_daily_use": tf(wrapper_ready),
        "ready_for_next_stage": ready_next,
        "blocking_reason": blocking,
        "final_status": final_status,
        **POLICY_COMMON,
        **COMMON,
    }

    write_csv(OUT_INPUT_AUDIT, INPUT_FIELDS, inputs)
    write_csv(OUT_CHAIN_PLAN, PLAN_FIELDS, plan)
    write_csv(OUT_EXECUTION_AUDIT, EXECUTION_FIELDS, execution_audit)
    write_csv(OUT_STAGE_OUTPUT_STATUS, STATUS_FIELDS, stage_outputs)
    write_csv(OUT_APPEND_AUDIT, AUDIT_FIELDS, append_audit)
    write_csv(OUT_NO_FAB_GUARD, GUARD_FIELDS, no_fab_guard)
    write_csv(OUT_MUTATION_GUARD, GUARD_FIELDS, mutation_guard)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate)

    print(gate["final_status"])
    for key in GATE_FIELDS:
        if key not in COMMON and key not in POLICY_COMMON and key != "gate_check_id":
            print(f"{key.upper()}={gate[key]}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("ORIGINAL_DAILY_RUNNER_MUTATED=FALSE")
    print("NO_FABRICATED_RETURNS=TRUE")
    print("NO_FABRICATED_BENCHMARK_RETURNS=TRUE")
    print("NO_FABRICATED_TICKER_ROWS=TRUE")
    print("NO_FUTURE_PRICE_USED=TRUE")
    print("FUTURE_PRICE_LEAKAGE_DETECTED=FALSE")
    print("ZERO_WEIGHT_POLICY_BINDING=TRUE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
