#!/usr/bin/env python
"""Tests for V20.193 historical recomputable factor snapshot builder."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_193_historical_recomputable_factor_snapshot_builder.py"
BACKTEST = ROOT / "outputs" / "v20" / "backtest"

OUTPUTS = [
    BACKTEST / "V20_193_HISTORICAL_FACTOR_SOURCE_DISCOVERY.csv",
    BACKTEST / "V20_193_HISTORICAL_FACTOR_FIELD_COVERAGE_AUDIT.csv",
    BACKTEST / "V20_193_HISTORICAL_RECOMPUTABLE_FACTOR_SNAPSHOT.csv",
    BACKTEST / "V20_193_HISTORICAL_ZERO_WEIGHT_SCORE_PREVIEW.csv",
    BACKTEST / "V20_193_MISSING_FACTOR_FIELD_REPORT.csv",
    BACKTEST / "V20_193_PIT_SAFETY_AUDIT.csv",
    BACKTEST / "V20_193_NEXT_STAGE_GATE.csv",
    BACKTEST / "V20_193_READ_CENTER_REPORT.md",
]
PROTECTED = [
    BACKTEST / "V20_192_NEXT_STAGE_GATE.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_35_ASOF_TECHNICAL_SCORE_AND_RANKING.csv",
]
EXPECTED_STATUS = "BLOCKED_NO_USABLE_HISTORICAL_FAMILY_LEVEL_SCORING_FIELDS"


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
        assert row.get("no_current_to_historical_join") == "TRUE"
        assert row.get("no_fabricated_scores") == "TRUE"
        assert row.get("no_fabricated_ticker_rows") == "TRUE"


def test_historical_recomputable_factor_snapshot_builder() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected artifacts were mutated"
    stdout = result.stdout
    for expected in [
        EXPECTED_STATUS,
        "V20_192_STATUS_CONSUMED=TRUE",
        "USABLE_SOURCE_COUNT=0",
        "HISTORICAL_ASOF_COUNT=0",
        "FULLY_RECOMPUTABLE_ROW_COUNT=0",
        "READY_FOR_V20_192_R1_ZERO_WEIGHT_RANDOM_ASOF_BACKTEST_RERUN=FALSE",
        "RESEARCH_ONLY=TRUE",
        "NO_CURRENT_TO_HISTORICAL_JOIN=TRUE",
        "NO_FABRICATED_SCORES=TRUE",
        "NO_FABRICATED_TICKER_ROWS=TRUE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    discovery = read_csv(OUTPUTS[0])
    coverage = read_csv(OUTPUTS[1])
    snapshot = read_csv(OUTPUTS[2])
    preview = read_csv(OUTPUTS[3])
    missing = read_csv(OUTPUTS[4])
    pit = read_csv(OUTPUTS[5])
    gate = read_csv(OUTPUTS[6])[0]

    assert len(discovery) > 0
    assert len(coverage) >= len(discovery)
    assert len(snapshot) == 0
    assert len(preview) == 0
    assert len(missing) > 0
    assert len(pit) == len(discovery)
    assert any(row["rejection_reason"] == "CURRENT_ONLY_OR_UNKNOWN_PIT_SOURCE" for row in discovery)
    assert any(row["rejection_reason"] == "MISSING_REQUIRED_NON_DATA_TRUST_FAMILY_FIELDS" for row in discovery)
    assert gate["final_status"] == EXPECTED_STATUS
    assert gate["v20_192_status"] == "BLOCKED_MISSING_RECOMPUTABLE_FACTOR_FIELDS"
    assert gate["usable_source_count"] == "0"
    assert gate["historical_asof_count"] == "0"
    assert gate["fully_recomputable_row_count"] == "0"
    assert gate["pit_safety_audit_pass"] == "TRUE"
    assert gate["no_official_trade_mutation"] == "TRUE"
    assert gate["blocking_reason"] == "NO_USABLE_HISTORICAL_PIT_SAFE_FULL_FAMILY_FACTOR_SNAPSHOT"
    assert_safety([gate, *discovery[:5], *coverage[:5], *missing[:5], *pit[:5]])
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "No current-only factor rows were copied backward" in report


if __name__ == "__main__":
    test_historical_recomputable_factor_snapshot_builder()
    print("PASS test_v20_193_historical_recomputable_factor_snapshot_builder")
