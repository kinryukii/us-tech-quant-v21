#!/usr/bin/env python
"""Tests for V20.198 daily walk-forward chain integration."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_198_daily_walk_forward_chain_integration.py"
OUT_DIR = ROOT / "outputs" / "v20" / "walk_forward"
FORWARD_DIR = ROOT / "outputs" / "v20" / "forward_observation"
INPUTS = [
    ROOT / "outputs" / "v20" / "backtest_snapshots" / "V20_194_RECOMPUTABLE_FACTOR_SNAPSHOT_LEDGER.csv",
    FORWARD_DIR / "V20_195_FORWARD_OBSERVATION_SCHEDULE.csv",
    FORWARD_DIR / "V20_195_FORWARD_RETURN_OBSERVATION_LEDGER.csv",
    FORWARD_DIR / "V20_195_BENCHMARK_OBSERVATION_LEDGER.csv",
    FORWARD_DIR / "V20_196_UPDATED_FORWARD_RETURN_OBSERVATION_LEDGER.csv",
    FORWARD_DIR / "V20_196_UPDATED_BENCHMARK_OBSERVATION_LEDGER.csv",
    OUT_DIR / "V20_197_NEXT_STAGE_GATE.csv",
    OUT_DIR / "V20_197_OPERATOR_READABLE_WALK_FORWARD_REPORT.md",
]
OUTPUTS = [
    OUT_DIR / "V20_198_CHAIN_INPUT_AUDIT.csv",
    OUT_DIR / "V20_198_STAGE_STATUS_SUMMARY.csv",
    OUT_DIR / "V20_198_DAILY_CHAIN_INTEGRATION_AUDIT.csv",
    OUT_DIR / "V20_198_APPEND_ONLY_CONTINUITY_AUDIT.csv",
    OUT_DIR / "V20_198_PENDING_MATURITY_STATUS.csv",
    OUT_DIR / "V20_198_READY_FOR_DAILY_RESEARCH_RUNNER_BINDING.csv",
    OUT_DIR / "V20_198_NO_FABRICATION_NO_LEAKAGE_GUARD.csv",
    OUT_DIR / "V20_198_OFFICIAL_TRADE_MUTATION_GUARD.csv",
    OUT_DIR / "V20_198_OPERATOR_READABLE_CHAIN_REPORT.md",
    OUT_DIR / "V20_198_NEXT_STAGE_GATE.csv",
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


def test_daily_walk_forward_chain_integration() -> None:
    before = input_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = input_hashes()
    assert before == after, "V20.198 mutated protected input artifacts"
    stdout = result.stdout
    for expected in [
        "ALL_REQUIRED_INPUTS_EXIST=TRUE",
        "USABLE_SNAPSHOT_ROWS_MINIMUM_PASS=TRUE",
        "SCHEDULE_CREATED=TRUE",
        "APPEND_ONLY_CONTINUITY_GUARD=TRUE",
        "DUPLICATE_SNAPSHOT_ID_COUNT=0",
        "DUPLICATE_OBSERVATION_ID_COUNT=0",
        "NO_FABRICATION_GUARD_PASS=TRUE",
        "NO_FUTURE_LEAKAGE_GUARD_PASS=TRUE",
        "NO_OFFICIAL_TRADE_MUTATION=TRUE",
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

    input_audit = read_csv(OUTPUTS[0])
    stage_summary = read_csv(OUTPUTS[1])
    integration = read_csv(OUTPUTS[2])
    append = read_csv(OUTPUTS[3])
    pending = read_csv(OUTPUTS[4])[0]
    binding = read_csv(OUTPUTS[5])[0]
    no_fab = read_csv(OUTPUTS[6])
    mutation = read_csv(OUTPUTS[7])
    gate = read_csv(OUTPUTS[9])[0]

    assert len(input_audit) == 8
    assert all(row["input_status"] == "PASS" for row in input_audit)
    assert len(stage_summary) == 8
    assert all(row["stage_status"] == "PASS" for row in stage_summary)
    assert all(row["audit_status"] == "PASS" for row in integration)
    assert all(row["audit_status"] == "PASS" for row in append)
    assert all(row["guard_passed"] == "TRUE" for row in no_fab)
    assert all(row["guard_passed"] == "TRUE" for row in mutation)
    assert gate["all_required_inputs_exist"] == "TRUE"
    assert gate["usable_snapshot_rows_minimum_pass"] == "TRUE"
    assert gate["schedule_created"] == "TRUE"
    assert gate["append_only_continuity_guard"] == "TRUE"
    assert gate["duplicate_snapshot_id_count"] == "0"
    assert gate["duplicate_observation_id_count"] == "0"
    assert gate["no_fabrication_guard_pass"] == "TRUE"
    assert gate["no_future_leakage_guard_pass"] == "TRUE"
    assert gate["no_official_trade_mutation"] == "TRUE"
    assert_append_only_counts(gate)
    assert gate["ready_for_daily_research_runner_binding"] == "TRUE"
    assert gate["final_status"].startswith(("PASS", "PARTIAL_PASS"))
    if int(gate["matured_observation_count"]) == 0:
        assert gate["final_status"] == "PARTIAL_PASS_PENDING_V20_198_DAILY_WALK_FORWARD_CHAIN_INTEGRATION"
    assert pending["all_observations_pending_not_matured"] == "TRUE"
    assert binding["safe_for_daily_research_runner_binding"] == "TRUE"
    assert binding["effectiveness_claim_created"] == "FALSE"
    assert_common(gate)
    report = OUTPUTS[8].read_text(encoding="utf-8")
    assert "does not prove strategy effectiveness" in report


if __name__ == "__main__":
    test_daily_walk_forward_chain_integration()
    print("PASS test_v20_198_daily_walk_forward_chain_integration")
