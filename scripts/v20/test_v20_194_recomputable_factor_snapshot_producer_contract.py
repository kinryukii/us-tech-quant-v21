#!/usr/bin/env python
"""Tests for V20.194 recomputable factor snapshot producer contract."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_194_recomputable_factor_snapshot_producer_contract.py"
OUT_DIR = ROOT / "outputs" / "v20" / "backtest_snapshots"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
FACTORS = ROOT / "outputs" / "v20" / "factors"
BACKTEST = ROOT / "outputs" / "v20" / "backtest"

OUTPUTS = [
    OUT_DIR / "V20_194_FACTOR_SNAPSHOT_PRODUCER_CONTRACT.csv",
    OUT_DIR / "V20_194_FACTOR_SNAPSHOT_FIELD_REQUIREMENTS.csv",
    OUT_DIR / "V20_194_CURRENT_RUN_RECOMPUTABLE_FACTOR_SNAPSHOT.csv",
    OUT_DIR / "V20_194_RECOMPUTABLE_FACTOR_SNAPSHOT_LEDGER.csv",
    OUT_DIR / "V20_194_ZERO_WEIGHT_SCORE_RECOMPUTE_AUDIT.csv",
    OUT_DIR / "V20_194_BASE_WEIGHT_SCORE_RECOMPUTE_AUDIT.csv",
    OUT_DIR / "V20_194_SNAPSHOT_APPEND_ONLY_GUARD_AUDIT.csv",
    OUT_DIR / "V20_194_PIT_SAFETY_GUARD_AUDIT.csv",
    OUT_DIR / "V20_194_NEXT_STAGE_GATE.csv",
    OUT_DIR / "V20_194_READ_CENTER_REPORT.md",
]
PROTECTED = [
    CONSOLIDATION / "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv",
    CONSOLIDATION / "V20_47_YAHOO_CURRENT_CANDIDATE_PRICE_CACHE.csv",
    CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv",
    FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_WEIGHT_SIMULATION.csv",
    BACKTEST / "V20_193_NEXT_STAGE_GATE.csv",
]
PASS_STATUS = "PARTIAL_PASS_V20_194_RECOMPUTABLE_FACTOR_SNAPSHOT_PRODUCER_CONTRACT_LIMITED_CURRENT_RUN_COVERAGE"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected_hashes() -> dict[Path, str]:
    return {path: digest(path) for path in PROTECTED if path.exists()}


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        assert row.get("research_only") == "TRUE"
        assert row.get("official_ranking_mutated") == "FALSE"
        assert row.get("official_ranking_score_mutation_count") == "0"
        assert row.get("official_rank_mutation_count") == "0"
        assert row.get("trade_action_created") == "FALSE"
        assert row.get("broker_execution_supported") == "FALSE"
        assert row.get("real_book_action_created") == "FALSE"
        assert row.get("no_future_outcome_joined") == "TRUE"
        assert row.get("no_fabricated_scores") == "TRUE"
        assert row.get("no_fabricated_ticker_rows") == "TRUE"


def test_recomputable_factor_snapshot_producer_contract() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected source artifacts were mutated"
    stdout = result.stdout
    for expected in [
        PASS_STATUS,
        "ALL_SIX_FAMILY_SCORES_PRESENT=FALSE",
        "ZERO_WEIGHT_SCORE_RECOMPUTABLE=FALSE",
        "BASE_WEIGHT_SCORE_RECOMPUTABLE=FALSE",
        "PIT_GUARD_PASS=TRUE",
        "APPEND_ONLY_LEDGER_GUARD_PASS=TRUE",
        "NO_OFFICIAL_TRADE_MUTATION=TRUE",
        "READY_FOR_V20_195_DAILY_SNAPSHOT_ACCUMULATION=TRUE",
        "RESEARCH_ONLY=TRUE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "NO_FUTURE_OUTCOME_JOINED=TRUE",
        "NO_FABRICATED_SCORES=TRUE",
        "NO_FABRICATED_TICKER_ROWS=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    contract = read_csv(OUTPUTS[0])
    requirements = read_csv(OUTPUTS[1])
    snapshot = read_csv(OUTPUTS[2])
    ledger = read_csv(OUTPUTS[3])
    zero_audit = read_csv(OUTPUTS[4])
    base_audit = read_csv(OUTPUTS[5])
    append_audit = read_csv(OUTPUTS[6])
    pit_audit = read_csv(OUTPUTS[7])
    gate = read_csv(OUTPUTS[8])[0]

    assert len(contract) == 1
    assert contract[0]["historical_backfill_allowed"] == "FALSE"
    assert contract[0]["future_outcome_join_allowed"] == "FALSE"
    assert contract[0]["append_only_ledger_required"] == "TRUE"
    assert len(requirements) >= 7
    assert all(row["field_status"] == "AVAILABLE" for row in requirements)
    assert len(snapshot) >= 20
    assert len(ledger) >= len(snapshot)
    assert len({row["snapshot_id"] for row in ledger}) == len(ledger)
    assert any(row["snapshot_usable_for_future_backtest"] == "TRUE" for row in snapshot)
    assert any(row["snapshot_usable_for_future_backtest"] == "FALSE" for row in snapshot)
    assert all(row["pit_safe_status"] in {"CURRENT_RUN_PIT_SNAPSHOT", "MISSING_CURRENT_AS_OF_DATE"} for row in snapshot)
    assert all(row["zero_weight_data_trust"] == "0.0000000000" for row in snapshot)
    assert any(row["audit_status"] == "PASS" for row in zero_audit)
    assert any(row["audit_status"] == "FAIL" for row in zero_audit)
    assert any(row["audit_status"] == "PASS" for row in base_audit)
    assert any(row["audit_status"] == "FAIL" for row in base_audit)
    assert all(row["guard_passed"] == "TRUE" for row in append_audit)
    assert all(row["guard_passed"] == "TRUE" for row in pit_audit)
    assert gate["final_status"] == PASS_STATUS
    assert int(gate["current_run_ticker_rows_emitted"]) >= 20
    assert int(gate["fully_recomputable_current_rows"]) >= 10
    assert int(gate["partially_recomputable_current_rows"]) > 0
    assert gate["all_six_family_scores_present"] == "FALSE"
    assert gate["pit_guard_pass"] == "TRUE"
    assert gate["append_only_ledger_guard_pass"] == "TRUE"
    assert gate["ready_for_v20_195_daily_snapshot_accumulation"] == "TRUE"
    assert_safety([gate, contract[0], *snapshot[:5], *append_audit, *pit_audit])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "No historical backfill" in report


if __name__ == "__main__":
    test_recomputable_factor_snapshot_producer_contract()
    print("PASS test_v20_194_recomputable_factor_snapshot_producer_contract")
