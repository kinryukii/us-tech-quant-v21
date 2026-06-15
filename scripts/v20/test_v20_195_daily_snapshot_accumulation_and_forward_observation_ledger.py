#!/usr/bin/env python
"""Tests for V20.195 daily snapshot accumulation and forward observation ledger."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_195_daily_snapshot_accumulation_and_forward_observation_ledger.py"
OUT_DIR = ROOT / "outputs" / "v20" / "forward_observation"
SNAPSHOT_LEDGER = ROOT / "outputs" / "v20" / "backtest_snapshots" / "V20_194_RECOMPUTABLE_FACTOR_SNAPSHOT_LEDGER.csv"

OUTPUTS = [
    OUT_DIR / "V20_195_SNAPSHOT_ACCUMULATION_AUDIT.csv",
    OUT_DIR / "V20_195_FORWARD_OBSERVATION_SCHEDULE.csv",
    OUT_DIR / "V20_195_FORWARD_RETURN_OBSERVATION_LEDGER.csv",
    OUT_DIR / "V20_195_BENCHMARK_OBSERVATION_LEDGER.csv",
    OUT_DIR / "V20_195_MATURED_OBSERVATION_COVERAGE_AUDIT.csv",
    OUT_DIR / "V20_195_TOPN_FORWARD_OBSERVATION_PREVIEW.csv",
    OUT_DIR / "V20_195_DATA_TRUST_ZERO_WEIGHT_POLICY_BINDING_AUDIT.csv",
    OUT_DIR / "V20_195_NO_FABRICATION_GUARD_AUDIT.csv",
    OUT_DIR / "V20_195_NEXT_STAGE_GATE.csv",
    OUT_DIR / "V20_195_READ_CENTER_REPORT.md",
]
SCHEDULE_REQUIRED = [
    "observation_id",
    "snapshot_id",
    "as_of_date",
    "ticker",
    "zero_weight_score",
    "zero_weight_rank",
    "top_n_group_membership",
    "forward_window",
    "scheduled_observation_date",
    "observation_status",
    "price_source_status",
    "benchmark_source_status",
]
RETURN_REQUIRED = [
    "observation_id",
    "snapshot_id",
    "as_of_date",
    "ticker",
    "zero_weight_rank",
    "top_n_group_membership",
    "forward_window",
    "entry_price",
    "exit_price",
    "forward_return",
    "observation_status",
    "insufficient_data_reason",
]
BENCH_REQUIRED = [
    "as_of_date",
    "forward_window",
    "benchmark",
    "benchmark_entry_price",
    "benchmark_exit_price",
    "benchmark_forward_return",
    "benchmark_observation_status",
    "insufficient_data_reason",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_common(row: dict[str, str]) -> None:
    assert row["no_fabricated_returns"] == "TRUE"
    assert row["no_fabricated_benchmark_rows"] == "TRUE"
    assert row["no_current_to_historical_join"] == "TRUE"
    assert row["research_only"] == "TRUE"
    assert row["official_ranking_mutated"] == "FALSE"
    assert row["official_ranking_score_mutation_count"] == "0"
    assert row["official_rank_mutation_count"] == "0"
    assert row["trade_action_created"] == "FALSE"
    assert row["broker_execution_supported"] == "FALSE"
    assert row["real_book_action_created"] == "FALSE"
    assert row["data_trust_scoring_weight"] == "0.0000000000"
    assert row["data_trust_score_contribution_sum"] == "0.0000000000"


def test_daily_snapshot_accumulation_and_forward_observation_ledger() -> None:
    before = digest(SNAPSHOT_LEDGER)
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = digest(SNAPSHOT_LEDGER)
    assert before == after, "V20.194 snapshot ledger was mutated"
    stdout = result.stdout
    for expected in [
        "USABLE_SNAPSHOT_ROWS=",
        "SCHEDULED_OBSERVATION_COUNT=",
        "ZERO_WEIGHT_POLICY_BINDING_AUDIT_PASS=TRUE",
        "NO_FABRICATION_GUARD_PASS=TRUE",
        "NO_OFFICIAL_TRADE_MUTATION=TRUE",
        "NO_FABRICATED_RETURNS=TRUE",
        "NO_FABRICATED_BENCHMARK_ROWS=TRUE",
        "NO_CURRENT_TO_HISTORICAL_JOIN=TRUE",
        "RESEARCH_ONLY=TRUE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    audit = read_csv(OUTPUTS[0])[0]
    schedule = read_csv(OUTPUTS[1])
    returns = read_csv(OUTPUTS[2])
    benchmarks = read_csv(OUTPUTS[3])
    coverage = read_csv(OUTPUTS[4])[0]
    preview = read_csv(OUTPUTS[5])
    policy = read_csv(OUTPUTS[6])
    fabrication = read_csv(OUTPUTS[7])
    gate = read_csv(OUTPUTS[8])[0]

    assert set(SCHEDULE_REQUIRED).issubset(schedule[0].keys())
    assert set(RETURN_REQUIRED).issubset(returns[0].keys())
    assert set(BENCH_REQUIRED).issubset(benchmarks[0].keys())
    assert int(audit["usable_snapshot_rows"]) >= 20
    assert int(audit["scheduled_observation_count"]) == int(audit["usable_snapshot_rows"]) * 4
    assert len(schedule) == int(audit["scheduled_observation_count"])
    assert len(returns) == len(schedule)
    assert {row["forward_window"] for row in schedule} == {"5D", "10D", "20D", "60D"}
    assert {row["benchmark"] for row in benchmarks} == {"QQQ", "SPY", "SOXX"}
    assert all(row["observation_status"] in {"PENDING_NOT_MATURED", "OBSERVED", "MISSING_PRICE_DATA"} for row in schedule)
    assert all(row["forward_return"] == "" for row in returns if row["observation_status"] != "OBSERVED")
    assert all(row["benchmark_forward_return"] == "" for row in benchmarks if row["benchmark_observation_status"] != "OBSERVED")
    assert all(row["audit_status"] == "PASS" for row in policy)
    assert all(row["guard_passed"] == "TRUE" for row in fabrication)
    assert len(preview) == 4 * 4 * 3
    assert coverage["scheduled_observation_count"] == audit["scheduled_observation_count"]
    assert gate["zero_weight_policy_binding_audit_pass"] == "TRUE"
    assert gate["no_fabrication_guard_pass"] == "TRUE"
    assert gate["no_official_trade_mutation"] == "TRUE"
    assert gate["final_status"].startswith(("PASS", "PARTIAL_PASS"))
    assert_common(audit)
    assert_common(gate)
    assert "No returns, benchmark returns, official rankings, or trade actions are fabricated" in OUTPUTS[-1].read_text(encoding="utf-8")


if __name__ == "__main__":
    test_daily_snapshot_accumulation_and_forward_observation_ledger()
    print("PASS test_v20_195_daily_snapshot_accumulation_and_forward_observation_ledger")
