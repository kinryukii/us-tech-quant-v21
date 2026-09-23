#!/usr/bin/env python
"""Tests for V20.196 forward observation maturity updater."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_196_forward_observation_maturity_updater.py"
OUT_DIR = ROOT / "outputs" / "v20" / "forward_observation"
INPUTS = [
    OUT_DIR / "V20_195_FORWARD_OBSERVATION_SCHEDULE.csv",
    OUT_DIR / "V20_195_FORWARD_RETURN_OBSERVATION_LEDGER.csv",
    OUT_DIR / "V20_195_BENCHMARK_OBSERVATION_LEDGER.csv",
    ROOT / "outputs" / "v20" / "backtest_snapshots" / "V20_194_RECOMPUTABLE_FACTOR_SNAPSHOT_LEDGER.csv",
]
OUTPUTS = [
    OUT_DIR / "V20_196_MATURITY_INPUT_AUDIT.csv",
    OUT_DIR / "V20_196_MATURED_OBSERVATION_ELIGIBILITY.csv",
    OUT_DIR / "V20_196_UPDATED_FORWARD_RETURN_OBSERVATION_LEDGER.csv",
    OUT_DIR / "V20_196_UPDATED_BENCHMARK_OBSERVATION_LEDGER.csv",
    OUT_DIR / "V20_196_TOPN_FORWARD_RETURN_READOUT.csv",
    OUT_DIR / "V20_196_BENCHMARK_EXCESS_RETURN_READOUT.csv",
    OUT_DIR / "V20_196_PENDING_OBSERVATION_STATUS.csv",
    OUT_DIR / "V20_196_MISSING_PRICE_DATA_AUDIT.csv",
    OUT_DIR / "V20_196_NO_FABRICATION_GUARD_AUDIT.csv",
    OUT_DIR / "V20_196_NEXT_STAGE_GATE.csv",
    OUT_DIR / "V20_196_READ_CENTER_REPORT.md",
]
REQUIRED_METRICS = [
    "candidate_count",
    "matured_candidate_count",
    "observed_return_count",
    "average_forward_return",
    "median_forward_return",
    "win_rate",
    "average_excess_return_vs_QQQ",
    "average_excess_return_vs_SPY",
    "average_excess_return_vs_SOXX",
    "median_excess_return_vs_QQQ",
    "median_excess_return_vs_SPY",
    "median_excess_return_vs_SOXX",
    "positive_excess_return_rate_vs_QQQ",
    "positive_excess_return_rate_vs_SPY",
    "positive_excess_return_rate_vs_SOXX",
    "pending_count",
    "missing_price_data_count",
    "insufficient_data_reason",
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
    assert row["no_current_to_historical_score_join"] == "TRUE"
    assert row["data_trust_scoring_weight"] == "0.0000000000"
    assert row["zero_weight_policy_binding"] == "TRUE"


def test_forward_observation_maturity_updater() -> None:
    before = input_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = input_hashes()
    assert before == after, "V20.196 mutated protected input artifacts"
    stdout = result.stdout
    for expected in [
        "SCHEDULE_EXISTS=TRUE",
        "USABLE_OBSERVATION_ROWS=",
        "NO_FABRICATION_GUARD_PASS=TRUE",
        "NO_OFFICIAL_TRADE_MUTATION=TRUE",
        "FUTURE_PRICE_LEAKAGE_DETECTED=FALSE",
        "RESEARCH_ONLY=TRUE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "NO_FABRICATED_RETURNS=TRUE",
        "NO_FABRICATED_BENCHMARK_RETURNS=TRUE",
        "NO_FUTURE_PRICE_USED=TRUE",
        "NO_CURRENT_TO_HISTORICAL_SCORE_JOIN=TRUE",
        "ZERO_WEIGHT_POLICY_BINDING=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    input_audit = read_csv(OUTPUTS[0])
    eligibility = read_csv(OUTPUTS[1])
    updated_returns = read_csv(OUTPUTS[2])
    updated_benchmarks = read_csv(OUTPUTS[3])
    topn = read_csv(OUTPUTS[4])
    excess = read_csv(OUTPUTS[5])
    pending = read_csv(OUTPUTS[6])
    missing = read_csv(OUTPUTS[7])
    guard = read_csv(OUTPUTS[8])
    gate = read_csv(OUTPUTS[9])[0]

    assert len(input_audit) >= 5
    assert len(eligibility) == len(updated_returns)
    assert len(updated_returns) == int(gate["usable_observation_rows"])
    assert len(updated_returns) > 0
    assert {row["forward_window"] for row in updated_returns} == {"5D", "10D", "20D", "60D"}
    assert {row["benchmark"] for row in updated_benchmarks} == {"QQQ", "SPY", "SOXX"}
    assert all(row["observation_status"] in {"PENDING_NOT_MATURED", "OBSERVED", "MISSING_PRICE_DATA"} for row in updated_returns)
    assert all(row["forward_return"] == "" for row in updated_returns if row["observation_status"] != "OBSERVED")
    assert all(row["benchmark_forward_return"] == "" for row in updated_benchmarks if row["benchmark_observation_status"] != "OBSERVED")
    assert all(row["guard_passed"] == "TRUE" for row in guard)
    assert len(topn) == 4 * 4
    assert all(set(REQUIRED_METRICS).issubset(row.keys()) for row in topn)
    assert len(excess) == 4 * 4 * 3
    assert len(pending) == 4
    assert gate["schedule_exists"] == "TRUE"
    assert gate["no_fabrication_guard_pass"] == "TRUE"
    assert gate["no_official_trade_mutation"] == "TRUE"
    assert gate["future_price_leakage_detected"] == "FALSE"
    assert gate["final_status"].startswith(("PASS", "PARTIAL_PASS"))
    assert_common(gate)
    if int(gate["matured_observation_count"]) == 0:
        assert gate["final_status"] == "PARTIAL_PASS_V20_196_FORWARD_OBSERVATION_MATURITY_UPDATER_ALL_OBSERVATIONS_PENDING_NOT_MATURED"
        assert len(missing) == 0
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "Pending rows remain blank" in report


if __name__ == "__main__":
    test_forward_observation_maturity_updater()
    print("PASS test_v20_196_forward_observation_maturity_updater")
