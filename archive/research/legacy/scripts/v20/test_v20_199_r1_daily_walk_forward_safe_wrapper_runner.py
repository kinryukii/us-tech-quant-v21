#!/usr/bin/env python
"""Tests for V20.199-R1 daily walk-forward safe wrapper runner."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_199_r1_daily_walk_forward_safe_wrapper_runner.py"
OUT_DIR = ROOT / "outputs" / "v20" / "walk_forward"
SCRIPT_DIR = ROOT / "scripts" / "v20"
FORWARD_DIR = ROOT / "outputs" / "v20" / "forward_observation"
INPUTS = [
    SCRIPT_DIR / "v20_194_recomputable_factor_snapshot_producer_contract.py",
    SCRIPT_DIR / "v20_195_daily_snapshot_accumulation_and_forward_observation_ledger.py",
    SCRIPT_DIR / "v20_196_forward_observation_maturity_updater.py",
    SCRIPT_DIR / "v20_197_daily_walk_forward_validation_runner.py",
    SCRIPT_DIR / "v20_198_daily_walk_forward_chain_integration.py",
    SCRIPT_DIR / "v20_199_daily_research_runner_walk_forward_binding.py",
    SCRIPT_DIR / "v20_daily_research_observation_operator.py",
    ROOT / "outputs" / "v20" / "backtest_snapshots" / "V20_194_RECOMPUTABLE_FACTOR_SNAPSHOT_LEDGER.csv",
    FORWARD_DIR / "V20_195_FORWARD_OBSERVATION_SCHEDULE.csv",
    FORWARD_DIR / "V20_196_UPDATED_FORWARD_RETURN_OBSERVATION_LEDGER.csv",
    OUT_DIR / "V20_197_NEXT_STAGE_GATE.csv",
    OUT_DIR / "V20_198_NEXT_STAGE_GATE.csv",
    OUT_DIR / "V20_199_NEXT_STAGE_GATE.csv",
]
OUTPUTS = [
    OUT_DIR / "V20_199_R1_SAFE_WRAPPER_INPUT_AUDIT.csv",
    OUT_DIR / "V20_199_R1_SAFE_WRAPPER_CHAIN_PLAN.csv",
    OUT_DIR / "V20_199_R1_SAFE_WRAPPER_EXECUTION_AUDIT.csv",
    OUT_DIR / "V20_199_R1_STAGE_OUTPUT_STATUS.csv",
    OUT_DIR / "V20_199_R1_APPEND_ONLY_LEDGER_CONTINUITY_AUDIT.csv",
    OUT_DIR / "V20_199_R1_NO_FABRICATION_NO_LEAKAGE_GUARD.csv",
    OUT_DIR / "V20_199_R1_OFFICIAL_TRADE_MUTATION_GUARD.csv",
    OUT_DIR / "V20_199_R1_OPERATOR_SAFE_WRAPPER_REPORT.md",
    OUT_DIR / "V20_199_R1_NEXT_STAGE_GATE.csv",
]


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
    assert row["original_daily_runner_mutated"] == "FALSE"


def test_daily_walk_forward_safe_wrapper_runner() -> None:
    before = input_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = input_hashes()
    assert before == after, "V20.199-R1 mutated protected inputs"
    stdout = result.stdout
    for expected in [
        "EXECUTION_MODE=PLAN_ONLY_SAFE_WRAPPER",
        "ALL_REQUIRED_STAGE_SCRIPTS_EXIST=TRUE",
        "ALL_REQUIRED_STAGE_OUTPUTS_EXIST=TRUE",
        "SAFE_WRAPPER_REQUIRED=TRUE",
        "DIRECT_DAILY_RUNNER_MUTATION_ALLOWED=FALSE",
        "WRAPPER_PLAN_CREATED=TRUE",
        "APPEND_ONLY_CONTINUITY_GUARD=TRUE",
        "DUPLICATE_SNAPSHOT_ID_COUNT=0",
        "DUPLICATE_OBSERVATION_ID_COUNT=0",
        "NO_FABRICATION_NO_LEAKAGE_GUARD_PASS=TRUE",
        "NO_OFFICIAL_TRADE_MUTATION=TRUE",
        "ORIGINAL_DAILY_RUNNER_MUTATED=FALSE",
        "WRAPPER_READY_FOR_DAILY_USE=TRUE",
        "RESEARCH_ONLY=TRUE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "NO_FABRICATED_RETURNS=TRUE",
        "NO_FABRICATED_BENCHMARK_RETURNS=TRUE",
        "NO_FABRICATED_TICKER_ROWS=TRUE",
        "NO_FUTURE_PRICE_USED=TRUE",
        "FUTURE_PRICE_LEAKAGE_DETECTED=FALSE",
        "ZERO_WEIGHT_POLICY_BINDING=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    inputs = read_csv(OUTPUTS[0])
    plan = read_csv(OUTPUTS[1])
    execution = read_csv(OUTPUTS[2])[0]
    stage_outputs = read_csv(OUTPUTS[3])
    append = read_csv(OUTPUTS[4])
    no_fab = read_csv(OUTPUTS[5])
    mutation = read_csv(OUTPUTS[6])
    gate = read_csv(OUTPUTS[8])[0]

    assert len(inputs) == 6
    assert all(row["input_status"] == "PASS" for row in inputs)
    assert len(plan) == 6
    assert all(row["execution_mode"] == "PLAN_ONLY_SAFE_WRAPPER" for row in plan)
    assert all(row["execute_now"] == "FALSE" for row in plan)
    assert all(row["registered_in_safe_wrapper"] == "TRUE" for row in plan)
    assert execution["wrapper_execution_performed"] == "FALSE"
    assert execution["wrapper_plan_created"] == "TRUE"
    assert len(stage_outputs) == 6
    assert all(row["stage_output_status"] == "PASS" for row in stage_outputs)
    assert all(row["audit_status"] == "PASS" for row in append)
    assert all(row["guard_passed"] == "TRUE" for row in no_fab)
    assert all(row["guard_passed"] == "TRUE" for row in mutation)
    assert gate["execution_mode"] == "PLAN_ONLY_SAFE_WRAPPER"
    assert gate["all_required_stage_scripts_exist"] == "TRUE"
    assert gate["all_required_stage_outputs_exist"] == "TRUE"
    assert gate["wrapper_plan_created"] == "TRUE"
    assert gate["append_only_continuity_guard"] == "TRUE"
    assert gate["duplicate_snapshot_id_count"] == "0"
    assert gate["duplicate_observation_id_count"] == "0"
    assert gate["no_fabrication_no_leakage_guard_pass"] == "TRUE"
    assert gate["no_official_trade_mutation"] == "TRUE"
    assert gate["original_daily_runner_mutated"] == "FALSE"
    assert gate["wrapper_ready_for_daily_use"] == "TRUE"
    assert gate["final_status"] == "PARTIAL_PASS_PLAN_ONLY_V20_199_R1_DAILY_WALK_FORWARD_SAFE_WRAPPER_RUNNER"
    assert_common(gate)
    report = OUTPUTS[7].read_text(encoding="utf-8")
    assert "does not mutate the original daily research runner" in report


if __name__ == "__main__":
    test_daily_walk_forward_safe_wrapper_runner()
    print("PASS test_v20_199_r1_daily_walk_forward_safe_wrapper_runner")
