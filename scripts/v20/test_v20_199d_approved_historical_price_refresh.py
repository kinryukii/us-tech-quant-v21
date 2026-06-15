#!/usr/bin/env python
"""Tests for V20.199D approved historical price refresh."""

from __future__ import annotations

import csv
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_199d_approved_historical_price_refresh.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_199d_approved_historical_price_refresh.ps1"
OUT_DIR = ROOT / "outputs" / "v20" / "price_history"
OUTPUTS = [
    OUT_DIR / "V20_199D_REFRESH_INPUT_UNIVERSE.csv",
    OUT_DIR / "V20_199D_APPROVED_REFRESH_MECHANISM_AUDIT.csv",
    OUT_DIR / "V20_199D_HISTORICAL_PRICE_REFRESH_RESULT.csv",
    OUT_DIR / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
    OUT_DIR / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv",
    OUT_DIR / "V20_199D_PRICE_REFRESH_FAILURES.csv",
    OUT_DIR / "V20_199D_PRICE_SCHEMA_VALIDATION.csv",
    OUT_DIR / "V20_199D_PRICE_COVERAGE_AFTER_REFRESH.csv",
    OUT_DIR / "V20_199D_HISTORICAL_BENCHMARK_COVERAGE_AUDIT.csv",
    OUT_DIR / "V20_199D_NO_FABRICATION_GUARD_AUDIT.csv",
    OUT_DIR / "V20_199D_NEXT_STAGE_GATE.csv",
    OUT_DIR / "V20_199D_READ_CENTER_REPORT.md",
]
CANONICAL_FIELDS = [
    "symbol", "date", "open", "high", "low", "close", "adjusted_close",
    "volume", "source_provider", "source_artifact", "refresh_timestamp",
    "row_hash", "price_row_status",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def run_script() -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)


def live_refresh_enabled() -> bool:
    return os.environ.get("V20_199D_ENABLE_YFINANCE_REFRESH", "").upper() == "TRUE"


def assert_common(row: dict[str, str]) -> None:
    assert row["research_only"] == "TRUE"
    assert row["official_ranking_mutated"] == "FALSE"
    assert row["official_ranking_score_mutation_count"] == "0"
    assert row["official_rank_mutation_count"] == "0"
    assert row["official_recommendation_created"] == "FALSE"
    assert row["trade_action_created"] == "FALSE"
    assert row["broker_execution_supported"] == "FALSE"
    assert row["real_book_action_created"] == "FALSE"


def test_approved_historical_price_refresh_contract_for_current_mode() -> None:
    result = run_script()
    stdout = result.stdout
    mode_expected = "EXECUTION_MODE=LIVE_YFINANCE_REFRESH" if live_refresh_enabled() else "EXECUTION_MODE=PLAN_ONLY_APPROVED_MECHANISM_REQUIRED"
    for expected in [
        mode_expected,
        "NO_FABRICATED_PRICE_ROWS=TRUE",
        "NO_FABRICATED_BENCHMARK_ROWS=TRUE",
        "NO_FORWARD_RETURNS_COMPUTED=TRUE",
        "NO_FACTOR_SCORES_COMPUTED=TRUE",
        "NO_OFFICIAL_TRADE_MUTATION=TRUE",
        "RESEARCH_ONLY=TRUE",
    ]:
        assert expected in stdout, expected

    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    universe = read_csv(OUTPUTS[0])
    mechanism = read_csv(OUTPUTS[1])
    result_rows = read_csv(OUTPUTS[2])
    canonical = read_csv(OUTPUTS[3])
    benchmark = read_csv(OUTPUTS[4])
    failures = read_csv(OUTPUTS[5])
    schema = read_csv(OUTPUTS[6])
    coverage = read_csv(OUTPUTS[7])
    benchmark_coverage = read_csv(OUTPUTS[8])
    guard = read_csv(OUTPUTS[9])
    gate = read_csv(OUTPUTS[10])[0]

    assert len(universe) >= 3
    assert {"QQQ", "SPY", "SOXX"}.issubset({row["symbol"] for row in universe})
    assert all(row["universe_pit_status"] in {"CURRENT_UNIVERSE_SURVIVORSHIP_RISK", "BENCHMARK_REQUIRED_CURRENT_SYMBOL"} for row in universe)
    assert len(mechanism) >= 3
    assert any(row["refresh_mechanism_name"] == "V20_199D_INTERNAL_YFINANCE_CANONICAL_REFRESH" for row in mechanism)
    assert result_rows[0]["execution_mode"] == ("LIVE_YFINANCE_REFRESH" if live_refresh_enabled() else "PLAN_ONLY_APPROVED_MECHANISM_REQUIRED")
    assert result_rows[0]["no_synthetic_ohlcv"] == "TRUE"
    assert result_rows[0]["no_forward_returns_computed"] == "TRUE"
    assert result_rows[0]["no_factor_scores_computed"] == "TRUE"
    assert read_csv_header(OUTPUTS[3]) == CANONICAL_FIELDS
    assert read_csv_header(OUTPUTS[4]) == CANONICAL_FIELDS
    if live_refresh_enabled():
        assert gate["final_status"] in {
            "PASS_V20_199D_APPROVED_HISTORICAL_PRICE_REFRESH",
            "PARTIAL_PASS_V20_199D_APPROVED_HISTORICAL_PRICE_REFRESH",
            "BLOCKED_V20_199D_APPROVED_HISTORICAL_PRICE_REFRESH",
        }
        assert gate["refresh_execution_attempted"] == "TRUE"
        assert result_rows[0]["refresh_status"] in {"REFRESH_COMPLETED_WITH_ROWS", "REFRESH_FAILED_NO_ROWS"}
        if int(result_rows[0]["canonical_benchmark_rows"]) >= 180:
            by_benchmark = {row["symbol"]: row for row in benchmark_coverage}
            assert {"QQQ", "SPY", "SOXX"}.issubset(by_benchmark)
            for symbol in ["QQQ", "SPY", "SOXX"]:
                row = by_benchmark[symbol]
                if int(row["trading_day_count"]) >= 60 and int(row["missing_close_count"]) == 0 and int(row["duplicate_date_count"]) == 0:
                    assert row["has_60_bar_lookback_potential"] == "TRUE"
                    assert row["usable_for_pit_lite_recompute"] == "TRUE"
        assert all(row["symbol"] in {"QQQ", "SPY", "SOXX"} for row in benchmark)
    else:
        assert all(row["refresh_execution_attempted"] == "FALSE" for row in mechanism)
        assert result_rows[0]["refresh_status"] == "REFRESH_PLAN_ONLY"
        assert canonical == []
        assert benchmark == []
        assert len(failures) == len(universe)
        assert all(row["failure_type"] == "REFRESH_NOT_EXECUTED_PLAN_ONLY" for row in failures)
        assert gate["final_status"] == "PARTIAL_PASS_REFRESH_PLAN_ONLY_APPROVED_MECHANISM_REQUIRED"
        assert gate["refresh_execution_attempted"] == "FALSE"
    assert all(row["schema_validation_status"] == "PASS" for row in schema)
    assert len(coverage) == len(universe)
    assert {row["symbol"] for row in benchmark_coverage} == {"QQQ", "SPY", "SOXX"}
    assert all(row["guard_status"] == "PASS" for row in guard)
    assert gate["canonical_ohlcv_created"] == "TRUE"
    assert gate["no_fabricated_prices"] == "TRUE"
    assert gate["no_official_trade_mutation"] == "TRUE"
    assert_common(gate)
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "Live yfinance refresh is disabled" in report


def read_csv_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle).fieldnames or [])


def test_wrapper_parseable() -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    if live_refresh_enabled():
        assert any(status in result.stdout for status in [
            "PASS_V20_199D_APPROVED_HISTORICAL_PRICE_REFRESH",
            "PARTIAL_PASS_V20_199D_APPROVED_HISTORICAL_PRICE_REFRESH",
            "BLOCKED_V20_199D_APPROVED_HISTORICAL_PRICE_REFRESH",
        ])
        for expected in [
            "EXECUTION_MODE=LIVE_YFINANCE_REFRESH",
            "NO_FABRICATED_PRICE_ROWS=TRUE",
            "NO_FABRICATED_BENCHMARK_ROWS=TRUE",
            "NO_OFFICIAL_TRADE_MUTATION=TRUE",
            "RESEARCH_ONLY=TRUE",
        ]:
            assert expected in result.stdout, expected
    else:
        assert "PARTIAL_PASS_REFRESH_PLAN_ONLY_APPROVED_MECHANISM_REQUIRED" in result.stdout
        assert "EXECUTION_MODE=PLAN_ONLY_APPROVED_MECHANISM_REQUIRED" in result.stdout


if __name__ == "__main__":
    test_approved_historical_price_refresh_contract_for_current_mode()
    test_wrapper_parseable()
    print("PASS test_v20_199d_approved_historical_price_refresh")
