#!/usr/bin/env python
"""Tests for V20.199C historical price data coverage repair."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_199c_historical_price_data_coverage_repair.py"
OUT_DIR = ROOT / "outputs" / "v20" / "backtest"
OUTPUTS = [
    OUT_DIR / "V20_199C_PRICE_SOURCE_DISCOVERY.csv",
    OUT_DIR / "V20_199C_REQUIRED_SYMBOL_UNIVERSE.csv",
    OUT_DIR / "V20_199C_HISTORICAL_PRICE_COVERAGE_AUDIT.csv",
    OUT_DIR / "V20_199C_HISTORICAL_BENCHMARK_COVERAGE_AUDIT.csv",
    OUT_DIR / "V20_199C_USABLE_PRICE_HISTORY_MANIFEST.csv",
    OUT_DIR / "V20_199C_PRICE_HISTORY_GAP_REPORT.csv",
    OUT_DIR / "V20_199C_PIT_LITE_PRICE_SOURCE_RISK_AUDIT.csv",
    OUT_DIR / "V20_199C_RECOMPUTE_READINESS_AUDIT.csv",
    OUT_DIR / "V20_199C_NEXT_STAGE_GATE.csv",
    OUT_DIR / "V20_199C_READ_CENTER_REPORT.md",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_common(row: dict[str, str]) -> None:
    assert row["research_only"] == "TRUE"
    assert row["official_ranking_mutated"] == "FALSE"
    assert row["official_recommendation_created"] == "FALSE"
    assert row["trade_action_created"] == "FALSE"
    assert row["broker_execution_supported"] == "FALSE"
    assert row["real_book_action_created"] == "FALSE"
    assert row["no_fabricated_price_rows"] == "TRUE"
    assert row["no_fabricated_benchmark_rows"] == "TRUE"
    assert row["current_factor_snapshot_join_count"] == "0"
    assert row["current_fundamental_field_used_count"] == "0"


def test_historical_price_data_coverage_repair() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    for expected in [
        "USABLE_TICKER_60BAR_COUNT=",
        "QQQ_60BAR_READY=",
        "SPY_60BAR_READY=",
        "NO_FABRICATED_PRICES=TRUE",
        "NO_OFFICIAL_TRADE_MUTATION=TRUE",
        "RESEARCH_ONLY=TRUE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "NO_FABRICATED_PRICE_ROWS=TRUE",
        "NO_FABRICATED_BENCHMARK_ROWS=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    discovery = read_csv(OUTPUTS[0])
    universe = read_csv(OUTPUTS[1])
    price_audit = read_csv(OUTPUTS[2])
    bench_audit = read_csv(OUTPUTS[3])
    manifest = read_csv(OUTPUTS[4])
    gap = read_csv(OUTPUTS[5])
    risk = read_csv(OUTPUTS[6])
    readiness = read_csv(OUTPUTS[7])
    gate = read_csv(OUTPUTS[8])[0]

    assert len(discovery) > 0
    assert len(universe) >= 3
    assert {"QQQ", "SPY", "SOXX"}.issubset({row["symbol"] for row in universe})
    assert len(price_audit) >= 1
    assert {row["symbol"] for row in bench_audit} == {"QQQ", "SPY", "SOXX"}
    assert all("source_artifact" in row for row in manifest)
    assert all(row["risk_status"] in {"PASS", "DISCLOSED_RISK"} for row in risk)
    assert all(row["readiness_status"] in {"PASS", "FAIL"} for row in readiness)
    assert gate["final_status"].startswith(("PASS", "PARTIAL_PASS", "BLOCKED"))
    assert gate["no_fabricated_prices"] == "TRUE"
    assert gate["no_official_trade_mutation"] == "TRUE"
    assert_common(gate)
    if int(gate["usable_ticker_60bar_count"]) < 30:
        assert gate["final_status"].startswith("BLOCKED")
        assert len(gap) > 0
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "No external data download was performed" in report


if __name__ == "__main__":
    test_historical_price_data_coverage_repair()
    print("PASS test_v20_199c_historical_price_data_coverage_repair")
