#!/usr/bin/env python
"""Validation checks for V20.90 ETF rotation evidence builder outputs."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path("scripts") / "v20" / "v20_90_etf_rotation_evidence_builder.py"
WRAPPER = Path("scripts") / "v20" / "run_v20_90_etf_rotation_evidence_builder.ps1"
OUTPUT_DIR = Path("outputs") / "v20" / "evidence"

VERSIONED_TABLE = OUTPUT_DIR / "V20_90_ETF_ROTATION_EVIDENCE_TABLE.csv"
VERSIONED_SUMMARY = OUTPUT_DIR / "V20_90_ETF_ROTATION_EVIDENCE_SUMMARY.md"
CURRENT_TABLE = OUTPUT_DIR / "V20_CURRENT_ETF_ROTATION_EVIDENCE_TABLE.csv"
CURRENT_SUMMARY = OUTPUT_DIR / "V20_CURRENT_ETF_ROTATION_EVIDENCE_SUMMARY.md"

EXPECTED_STATUS = "PASS_V20_90_ETF_ROTATION_EVIDENCE_BUILDER_WITH_PARTIAL_COVERAGE"

REQUIRED_COLUMNS = {
    "signal_date",
    "as_of_date",
    "rotation_pair_id",
    "rotation_pair_type",
    "from_etf",
    "to_etf",
    "candidate_etf",
    "benchmark_etf",
    "holding_window",
    "candidate_forward_return",
    "benchmark_forward_return",
    "excess_return",
    "max_drawdown",
    "volatility",
    "win_flag",
    "risk_adjusted_score",
    "certification_status",
    "certification_reason",
    "source_cache_file",
    "source_run_id",
    "research_only",
    "official_eligible",
    "official_recommendation_created",
    "official_weight_mutated",
    "trade_action_created",
}

CORE_PAIR_IDS = {"QQQ_SPY", "XLK_SPY", "SOXX_QQQ", "SMH_SOXX", "IWM_SPY", "TLT_QQQ", "GLD_QQQ", "XLY_XLP"}
LEVERAGED_PAIR_IDS = {"TQQQ_SQQQ", "SOXL_SOXS", "TECL_TECS"}


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module():
    spec = importlib.util.spec_from_file_location("v20_90_etf_rotation_evidence_builder", SCRIPT)
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
    for path in [VERSIONED_TABLE, VERSIONED_SUMMARY, CURRENT_TABLE, CURRENT_SUMMARY]:
        assert_true(path.exists(), f"missing output: {path}")
        assert_true(path.stat().st_size > 0, f"empty output: {path}")
    assert_true(sha256(VERSIONED_TABLE) == sha256(CURRENT_TABLE), "current table alias differs from versioned output")
    assert_true(sha256(VERSIONED_SUMMARY) == sha256(CURRENT_SUMMARY), "current summary alias differs from versioned output")

    rows = read_csv(VERSIONED_TABLE)
    assert_true(bool(rows), "evidence table is empty")
    assert_true(REQUIRED_COLUMNS.issubset(rows[0].keys()), "evidence table missing required columns")
    pair_ids = {row["rotation_pair_id"] for row in rows}
    assert_true(CORE_PAIR_IDS.issubset(pair_ids), f"missing core pairs: {sorted(CORE_PAIR_IDS - pair_ids)}")
    assert_true(LEVERAGED_PAIR_IDS.issubset(pair_ids), f"missing leveraged pairs: {sorted(LEVERAGED_PAIR_IDS - pair_ids)}")

    for row in rows:
        assert_true(row["certification_status"] in {"CERTIFIED_ETF_ROTATION_EVIDENCE", "PARTIAL_COVERAGE", "BLOCKED_ETF_ROTATION_EVIDENCE"}, f"bad explicit certification status: {row}")
        assert_true(row["research_only"] == "TRUE", f"research_only invariant failed: {row['rotation_pair_id']}")
        assert_true(row["official_recommendation_created"] == "FALSE", f"official recommendation created: {row['rotation_pair_id']}")
        assert_true(row["official_weight_mutated"] == "FALSE", f"official weight mutated: {row['rotation_pair_id']}")
        assert_true(row["trade_action_created"] == "FALSE", f"trade action created: {row['rotation_pair_id']}")
        if row["rotation_pair_id"] in LEVERAGED_PAIR_IDS:
            assert_true(row["research_only"] == "TRUE", f"leveraged pair not research-only: {row}")
            assert_true(row["official_eligible"] == "FALSE", f"leveraged pair official eligible: {row}")

    summary = VERSIONED_SUMMARY.read_text(encoding="utf-8")
    for token in [
        f"final_status: {EXPECTED_STATUS}",
        "total_pair_count:",
        "core_pair_count:",
        "leveraged_pair_count:",
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
        "ticker": "QQQ",
        "notes": "CERTIFIED_ETF_ROTATION_EVIDENCE",
        "certification_reason": "CERTIFIED_ETF_ROTATION_EVIDENCE",
    }
    assert_true(not module.structured_certification_is_positive(notes_only), "notes-only certification was accepted")

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        rows = module.build_rows(
            root=root,
            pairs=[module.RotationPair("AAA", "BBB", "CORE")],
            source_run_id="TEST_RUN",
        )
        assert_true(len(rows) == 1, "synthetic missing data did not produce one row")
        row = rows[0]
        assert_true(row["certification_status"] == "PARTIAL_COVERAGE", f"missing data did not produce partial coverage: {row}")
        assert_true(row["official_recommendation_created"] == "FALSE", "synthetic row created recommendation")
        assert_true(row["official_weight_mutated"] == "FALSE", "synthetic row mutated weight")
        assert_true(row["trade_action_created"] == "FALSE", "synthetic row created trade action")

        cache = root / "state" / "v18" / "price_cache"
        prices_a = [(f"2026-01-{day:02d}", 100.0 + day) for day in range(1, 24)]
        prices_b = [(f"2026-01-{day:02d}", 100.0) for day in range(1, 24)]
        write_price_csv(cache / "AAA.csv", prices_a)
        write_price_csv(cache / "BBB.csv", prices_b)
        original_dirs = list(module.PRICE_CACHE_DIRS)
        try:
            module.PRICE_CACHE_DIRS[:] = [cache]
            certified = module.build_rows(root=root, pairs=[module.RotationPair("AAA", "BBB", "CORE")], source_run_id="TEST_RUN")
        finally:
            module.PRICE_CACHE_DIRS[:] = original_dirs
        assert_true(certified[0]["certification_status"] == "CERTIFIED_ETF_ROTATION_EVIDENCE", f"complete cache did not certify: {certified[0]}")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(Path(__file__)), doraise=True)
    parse_wrapper()
    module = load_module()
    test_outputs()
    test_synthetic_rules(module)
    print("PASS_V20_90_ETF_ROTATION_EVIDENCE_BUILDER_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
