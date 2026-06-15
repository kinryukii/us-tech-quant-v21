#!/usr/bin/env python
"""Validation checks for V20.91 multi-window strategy evidence matrix outputs."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path("scripts") / "v20" / "v20_91_multi_window_strategy_evidence_matrix.py"
WRAPPER = Path("scripts") / "v20" / "run_v20_91_multi_window_strategy_evidence_matrix.ps1"
OUTPUT_DIR = Path("outputs") / "v20" / "evidence"

VERSIONED_MATRIX = OUTPUT_DIR / "V20_91_MULTI_WINDOW_STRATEGY_EVIDENCE_MATRIX.csv"
VERSIONED_SUMMARY = OUTPUT_DIR / "V20_91_MULTI_WINDOW_STRATEGY_EVIDENCE_SUMMARY.md"
CURRENT_MATRIX = OUTPUT_DIR / "V20_CURRENT_MULTI_WINDOW_STRATEGY_EVIDENCE_MATRIX.csv"
CURRENT_SUMMARY = OUTPUT_DIR / "V20_CURRENT_MULTI_WINDOW_STRATEGY_EVIDENCE_SUMMARY.md"

EXPECTED_STATUS = "PASS_V20_91_MULTI_WINDOW_STRATEGY_EVIDENCE_MATRIX_WITH_PARTIAL_COVERAGE"
REQUIRED_WINDOWS = {"forward_1d", "forward_5d", "forward_10d", "forward_20d"}

REQUIRED_COLUMNS = {
    "signal_date",
    "as_of_date",
    "ticker",
    "strategy_id",
    "entry_rule",
    "exit_rule",
    "holding_window",
    "entry_price",
    "exit_price",
    "forward_return",
    "benchmark_ticker",
    "benchmark_forward_return",
    "excess_return",
    "max_drawdown",
    "volatility",
    "win_flag",
    "risk_adjusted_score",
    "source_stage",
    "source_run_id",
    "source_cache_file",
    "certification_status",
    "certification_reason",
    "research_only",
    "official_recommendation_created",
    "official_weight_mutated",
    "trade_action_created",
}


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module():
    spec = importlib.util.spec_from_file_location("v20_91_multi_window_strategy_evidence_matrix", SCRIPT)
    assert_true(spec is not None and spec.loader is not None, "could not load module spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_wrapper() -> None:
    command = (
        "$tokens=$null;$errors=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile('{WRAPPER.as_posix()}', [ref]$tokens, [ref]$errors) > $null;"
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        check=False,
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"PowerShell wrapper parse failed: {result.stdout}\n{result.stderr}")


def test_outputs() -> None:
    for path in [VERSIONED_MATRIX, VERSIONED_SUMMARY, CURRENT_MATRIX, CURRENT_SUMMARY]:
        assert_true(path.exists(), f"missing output: {path}")
        assert_true(path.stat().st_size > 0, f"empty output: {path}")
    assert_true(sha256(VERSIONED_MATRIX) == sha256(CURRENT_MATRIX), "current matrix alias differs from versioned output")
    assert_true(sha256(VERSIONED_SUMMARY) == sha256(CURRENT_SUMMARY), "current summary alias differs from versioned output")

    rows = read_csv(VERSIONED_MATRIX)
    assert_true(bool(rows), "matrix is empty")
    assert_true(REQUIRED_COLUMNS.issubset(rows[0].keys()), "matrix missing required columns")
    represented = {row["holding_window"] for row in rows}
    summary = VERSIONED_SUMMARY.read_text(encoding="utf-8")
    missing = REQUIRED_WINDOWS - represented
    assert_true(not missing or "required_windows_missing:" in summary, f"missing windows not explicitly reported: {missing}")
    assert_true(REQUIRED_WINDOWS.issubset(represented) or "required_windows_missing:" in summary, "required windows neither represented nor reported")

    for row in rows:
        assert_true(row["certification_status"] in {"CERTIFIED_MULTI_WINDOW_STRATEGY_EVIDENCE", "PARTIAL_COVERAGE", "BLOCKED_MULTI_WINDOW_STRATEGY_EVIDENCE"}, f"bad certification status: {row}")
        assert_true(row["research_only"] == "TRUE", f"research_only invariant failed: {row}")
        assert_true(row["official_recommendation_created"] == "FALSE", f"official recommendation created: {row}")
        assert_true(row["official_weight_mutated"] == "FALSE", f"official weight mutated: {row}")
        assert_true(row["trade_action_created"] == "FALSE", f"trade action created: {row}")

    for token in [
        f"final_status: {EXPECTED_STATUS}",
        "row_count:",
        "ticker_count:",
        "strategy_count:",
        "window_count:",
        "certified_row_count:",
        "partial_row_count:",
        "blocked_row_count:",
    ]:
        assert_true(token in summary, f"summary missing {token}")


def write_price_csv(path: Path, prices: list[tuple[str, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "adj_close"], lineterminator="\n")
        writer.writeheader()
        for date, price in prices:
            writer.writerow({"date": date, "adj_close": price})


def test_synthetic_rules(module) -> None:
    notes_only = {
        "ticker": "AAA",
        "notes": "CERTIFIED_MULTI_WINDOW_STRATEGY_EVIDENCE",
        "certification_reason": "CERTIFIED_MULTI_WINDOW_STRATEGY_EVIDENCE",
    }
    assert_true(not module.structured_certification_is_positive(notes_only), "notes-only certification was accepted")

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        rows = module.build_rows(root=root, tickers=["AAA"], run_id="TEST_RUN")
        assert_true(len(rows) == 4, "missing data did not still emit required window rows")
        assert_true(all(row["certification_status"] == "PARTIAL_COVERAGE" for row in rows), f"missing data did not produce partial coverage: {rows}")
        assert_true(all(row["official_recommendation_created"] == "FALSE" for row in rows), "synthetic row created recommendation")
        assert_true(all(row["official_weight_mutated"] == "FALSE" for row in rows), "synthetic row mutated weight")
        assert_true(all(row["trade_action_created"] == "FALSE" for row in rows), "synthetic row created trade action")

        cache = root / "state" / "v18" / "price_cache"
        prices_a = [(f"2026-01-{day:02d}", 100.0 + day) for day in range(1, 24)]
        prices_b = [(f"2026-01-{day:02d}", 100.0) for day in range(1, 24)]
        write_price_csv(cache / "AAA.csv", prices_a)
        write_price_csv(cache / "QQQ.csv", prices_b)
        certified = module.build_rows(root=root, tickers=["AAA"], run_id="TEST_RUN")
        by_window = {row["holding_window"]: row for row in certified}
        assert_true(set(by_window) == REQUIRED_WINDOWS, f"required windows missing in synthetic certified case: {by_window}")
        assert_true(by_window["forward_20d"]["certification_status"] == "CERTIFIED_MULTI_WINDOW_STRATEGY_EVIDENCE", f"complete cache did not certify 20d: {by_window['forward_20d']}")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(Path(__file__)), doraise=True)
    parse_wrapper()
    module = load_module()
    test_outputs()
    test_synthetic_rules(module)
    print("PASS_V20_91_MULTI_WINDOW_STRATEGY_EVIDENCE_MATRIX_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
