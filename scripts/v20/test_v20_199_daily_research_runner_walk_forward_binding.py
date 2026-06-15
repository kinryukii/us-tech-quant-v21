#!/usr/bin/env python
"""Tests for V20.199 daily research runner walk-forward binding."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_199_daily_research_runner_walk_forward_binding.py"
OUT_DIR = ROOT / "outputs" / "v20" / "walk_forward"
FORWARD_DIR = ROOT / "outputs" / "v20" / "forward_observation"
INPUTS = [
    ROOT / "outputs" / "v20" / "backtest_snapshots" / "V20_194_RECOMPUTABLE_FACTOR_SNAPSHOT_LEDGER.csv",
    FORWARD_DIR / "V20_195_FORWARD_OBSERVATION_SCHEDULE.csv",
    FORWARD_DIR / "V20_196_UPDATED_FORWARD_RETURN_OBSERVATION_LEDGER.csv",
    OUT_DIR / "V20_197_NEXT_STAGE_GATE.csv",
    OUT_DIR / "V20_198_NEXT_STAGE_GATE.csv",
]
OUTPUTS = [
    OUT_DIR / "V20_199_DAILY_RUNNER_BINDING_INPUT_AUDIT.csv",
    OUT_DIR / "V20_199_WALK_FORWARD_STAGE_BINDING_PLAN.csv",
    OUT_DIR / "V20_199_DAILY_RESEARCH_RUNNER_BINDING_AUDIT.csv",
    OUT_DIR / "V20_199_RESEARCH_ONLY_SAFETY_GUARD.csv",
    OUT_DIR / "V20_199_APPEND_ONLY_DAILY_ACCUMULATION_GUARD.csv",
    OUT_DIR / "V20_199_WALK_FORWARD_REPORT_BINDING_AUDIT.csv",
    OUT_DIR / "V20_199_OPERATOR_DAILY_RUNNER_REPORT_EXTENSION.md",
    OUT_DIR / "V20_199_NEXT_STAGE_GATE.csv",
]
SCOPE = "RESEARCH_ONLY_WALK_FORWARD_EVIDENCE_ACCUMULATION"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def input_hashes() -> dict[Path, str]:
    return {path: digest(path) for path in INPUTS if path.exists()}


def assert_common(row: dict[str, str]) -> None:
    assert row["research_only"] == "TRUE"
    assert row["official_ranking_mutated"] == "FALSE"
    assert row["official_ranking_score_mutation_count"] == "0"
    assert row["official_rank_mutation_count"] == "0"
    assert row["official_recommendation_created"] == "FALSE"
    assert row["trade_action_created"] == "FALSE"
    assert row["broker_execution_supported"] == "FALSE"
    assert row["real_book_action_created"] == "FALSE"
    assert row["daily_runner_binding_scope"] == SCOPE
    assert row["no_fabricated_returns"] == "TRUE"
    assert row["no_fabricated_benchmark_returns"] == "TRUE"
    assert row["no_future_price_used"] == "TRUE"
    assert row["future_price_leakage_detected"] == "FALSE"
    assert row["zero_weight_policy_binding"] == "TRUE"


def assert_append_only_counts(row: dict[str, str]) -> None:
    total = int(row["total_snapshot_rows"])
    usable = int(row["usable_snapshot_rows"])
    scheduled = int(row["scheduled_observation_count"])
    pending = int(row["pending_not_matured_count"])
    matured = int(row["matured_observation_count"])
    assert total >= 315
    assert usable >= 297
    if "excluded_snapshot_rows" in row:
        assert int(row["excluded_snapshot_rows"]) == total - usable
    assert scheduled == usable * 4
    assert pending + matured == scheduled


def test_daily_research_runner_walk_forward_binding() -> None:
    before = input_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = input_hashes()
    assert before == after, "V20.199 mutated protected input artifacts"
    stdout = result.stdout
    for expected in [
        "ALL_INPUTS_EXIST=TRUE",
        "READY_FOR_DAILY_RESEARCH_RUNNER_BINDING=TRUE",
        "BINDING_PLAN_CREATED=TRUE",
        "DIRECT_DAILY_RUNNER_MUTATION_ALLOWED=FALSE",
        "SAFE_WRAPPER_REQUIRED=TRUE",
        "RESEARCH_ONLY_SAFETY_GUARD_PASS=TRUE",
        "APPEND_ONLY_GUARD_PASS=TRUE",
        "NO_FUTURE_LEAKAGE_GUARD_PASS=TRUE",
        "NO_OFFICIAL_TRADE_MUTATION=TRUE",
        "DUPLICATE_SNAPSHOT_ID_COUNT=0",
        "DUPLICATE_OBSERVATION_ID_COUNT=0",
        "RESEARCH_ONLY=TRUE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "NO_FABRICATED_RETURNS=TRUE",
        "NO_FABRICATED_BENCHMARK_RETURNS=TRUE",
        "NO_FUTURE_PRICE_USED=TRUE",
        "FUTURE_PRICE_LEAKAGE_DETECTED=FALSE",
        "ZERO_WEIGHT_POLICY_BINDING=TRUE",
        f"DAILY_RUNNER_BINDING_SCOPE={SCOPE}",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    inputs = read_csv(OUTPUTS[0])
    plan = read_csv(OUTPUTS[1])
    audit = read_csv(OUTPUTS[2])
    safety = read_csv(OUTPUTS[3])
    append = read_csv(OUTPUTS[4])
    report_audit = read_csv(OUTPUTS[5])
    gate = read_csv(OUTPUTS[7])[0]

    assert len(inputs) == 5
    assert all(row["input_status"] == "PASS" for row in inputs)
    assert {row["stage"] for row in plan} == {"V20.194", "V20.195", "V20.196", "V20.197", "V20.198"}
    assert all(row["registered_for_daily_runner"] == "TRUE" for row in plan)
    assert all(row["direct_daily_runner_mutation_allowed"] == "FALSE" for row in plan)
    assert all(row["safe_wrapper_required"] == "TRUE" for row in plan)
    assert all(row["binding_status"] == "DEFERRED_SAFE_WRAPPER_REQUIRED" for row in plan)
    assert all(row["audit_status"] == "PASS" for row in audit)
    assert all(row["guard_passed"] == "TRUE" for row in safety)
    assert all(row["guard_passed"] == "TRUE" for row in append)
    assert all(row["audit_status"] == "PASS" for row in report_audit)
    assert gate["all_inputs_exist"] == "TRUE"
    assert gate["ready_for_daily_research_runner_binding"] == "TRUE"
    assert gate["binding_plan_created"] == "TRUE"
    assert gate["safe_wrapper_required"] == "TRUE"
    assert gate["research_only_safety_guard_pass"] == "TRUE"
    assert gate["append_only_guard_pass"] == "TRUE"
    assert gate["no_future_leakage_guard_pass"] == "TRUE"
    assert gate["no_official_trade_mutation"] == "TRUE"
    assert gate["append_only_continuity_guard"] == "TRUE"
    assert gate["duplicate_snapshot_id_count"] == "0"
    assert gate["duplicate_observation_id_count"] == "0"
    assert gate["ready_for_next_stage"] == "TRUE"
    assert_append_only_counts(gate)
    assert gate["final_status"] == "PARTIAL_PASS_SAFE_WRAPPER_REQUIRED_V20_199_DAILY_RESEARCH_RUNNER_WALK_FORWARD_BINDING"
    assert_common(gate)
    report = OUTPUTS[6].read_text(encoding="utf-8")
    assert "Direct daily runner mutation is deferred" in report


if __name__ == "__main__":
    test_daily_research_runner_walk_forward_binding()
    print("PASS test_v20_199_daily_research_runner_walk_forward_binding")
