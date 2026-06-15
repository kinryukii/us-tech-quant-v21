#!/usr/bin/env python
"""Tests for V20.197 daily walk-forward validation runner."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_197_daily_walk_forward_validation_runner.py"
OUT_DIR = ROOT / "outputs" / "v20" / "walk_forward"
FORWARD_DIR = ROOT / "outputs" / "v20" / "forward_observation"
INPUTS = [
    ROOT / "outputs" / "v20" / "backtest_snapshots" / "V20_194_RECOMPUTABLE_FACTOR_SNAPSHOT_LEDGER.csv",
    FORWARD_DIR / "V20_195_FORWARD_OBSERVATION_SCHEDULE.csv",
    FORWARD_DIR / "V20_195_FORWARD_RETURN_OBSERVATION_LEDGER.csv",
    FORWARD_DIR / "V20_195_BENCHMARK_OBSERVATION_LEDGER.csv",
    FORWARD_DIR / "V20_196_UPDATED_FORWARD_RETURN_OBSERVATION_LEDGER.csv",
    FORWARD_DIR / "V20_196_UPDATED_BENCHMARK_OBSERVATION_LEDGER.csv",
    FORWARD_DIR / "V20_196_NEXT_STAGE_GATE.csv",
    FORWARD_DIR / "V20_196_NO_FABRICATION_GUARD_AUDIT.csv",
]
OUTPUTS = [
    OUT_DIR / "V20_197_RUN_CHAIN_AUDIT.csv",
    OUT_DIR / "V20_197_SNAPSHOT_ACCUMULATION_STATUS.csv",
    OUT_DIR / "V20_197_FORWARD_OBSERVATION_STATUS.csv",
    OUT_DIR / "V20_197_MATURITY_STATUS_BY_WINDOW.csv",
    OUT_DIR / "V20_197_TOPN_PENDING_AND_OBSERVED_STATUS.csv",
    OUT_DIR / "V20_197_BENCHMARK_STATUS.csv",
    OUT_DIR / "V20_197_NO_FABRICATION_AND_NO_LEAKAGE_GUARD.csv",
    OUT_DIR / "V20_197_OFFICIAL_TRADE_MUTATION_GUARD.csv",
    OUT_DIR / "V20_197_OPERATOR_READABLE_WALK_FORWARD_REPORT.md",
    OUT_DIR / "V20_197_NEXT_STAGE_GATE.csv",
]
METRICS = [
    "total_snapshot_rows",
    "usable_snapshot_rows",
    "excluded_snapshot_rows",
    "total_scheduled_observations",
    "pending_not_matured_count",
    "matured_observation_count",
    "observed_return_count",
    "benchmark_observed_count",
    "missing_price_data_count",
    "observed_top5_count",
    "observed_top10_count",
    "observed_top20_count",
    "observed_top40_count",
    "pending_5d_count",
    "pending_10d_count",
    "pending_20d_count",
    "pending_60d_count",
    "matured_5d_count",
    "matured_10d_count",
    "matured_20d_count",
    "matured_60d_count",
    "observed_5d_count",
    "observed_10d_count",
    "observed_20d_count",
    "observed_60d_count",
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
    assert row["no_fabricated_ticker_rows"] == "TRUE"
    assert row["no_future_price_used"] == "TRUE"
    assert row["future_price_leakage_detected"] == "FALSE"
    assert row["zero_weight_policy_binding"] == "TRUE"
    assert row["data_trust_scoring_weight"] == "0.0000000000"


def assert_append_only_counts(row: dict[str, str], scheduled_field: str = "total_scheduled_observations") -> None:
    total = int(row["total_snapshot_rows"])
    usable = int(row["usable_snapshot_rows"])
    scheduled = int(row[scheduled_field])
    pending = int(row["pending_not_matured_count"])
    matured = int(row["matured_observation_count"])
    assert total >= 315
    assert usable >= 297
    if "excluded_snapshot_rows" in row:
        assert int(row["excluded_snapshot_rows"]) == total - usable
    assert scheduled == usable * 4
    assert pending + matured == scheduled


def test_daily_walk_forward_validation_runner() -> None:
    before = input_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = input_hashes()
    assert before == after, "V20.197 mutated protected input artifacts"
    stdout = result.stdout
    for expected in [
        "SNAPSHOT_LEDGER_EXISTS=TRUE",
        "OBSERVATION_SCHEDULE_EXISTS=TRUE",
        "MATURITY_UPDATER_OUTPUTS_EXIST=TRUE",
        "NO_FABRICATION_GUARD_PASS=TRUE",
        "NO_FUTURE_LEAKAGE_GUARD_PASS=TRUE",
        "NO_OFFICIAL_TRADE_MUTATION=TRUE",
        "RESEARCH_ONLY=TRUE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
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

    chain = read_csv(OUTPUTS[0])
    snapshot_status = read_csv(OUTPUTS[1])[0]
    forward_status = read_csv(OUTPUTS[2])[0]
    maturity = read_csv(OUTPUTS[3])
    topn = read_csv(OUTPUTS[4])
    benchmarks = read_csv(OUTPUTS[5])
    no_fab = read_csv(OUTPUTS[6])
    mutation = read_csv(OUTPUTS[7])
    gate = read_csv(OUTPUTS[9])[0]

    assert len(chain) >= 8
    assert all(row["chain_status"] == "PASS" for row in chain)
    assert len(maturity) == 4
    assert len(topn) == 4
    assert len(benchmarks) == 3
    assert all(row["guard_passed"] == "TRUE" for row in no_fab)
    assert all(row["guard_passed"] == "TRUE" for row in mutation)
    for row in [snapshot_status, forward_status, gate]:
        assert set(METRICS).issubset(row.keys())
        assert_common(row)
    assert gate["snapshot_ledger_exists"] == "TRUE"
    assert gate["observation_schedule_exists"] == "TRUE"
    assert gate["maturity_updater_outputs_exist"] == "TRUE"
    assert gate["no_fabrication_guard_pass"] == "TRUE"
    assert gate["no_future_leakage_guard_pass"] == "TRUE"
    assert gate["no_official_trade_mutation"] == "TRUE"
    assert_append_only_counts(gate)
    assert gate["final_status"].startswith(("PASS", "PARTIAL_PASS"))
    if int(gate["matured_observation_count"]) == 0:
        assert gate["final_status"] == "PARTIAL_PASS_PENDING_V20_197_DAILY_WALK_FORWARD_VALIDATION_RUNNER"
        assert gate["pending_not_matured_count"] == gate["total_scheduled_observations"]
    report = OUTPUTS[8].read_text(encoding="utf-8")
    assert "does not prove effectiveness" in report


if __name__ == "__main__":
    test_daily_walk_forward_validation_runner()
    print("PASS test_v20_197_daily_walk_forward_validation_runner")
