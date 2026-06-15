#!/usr/bin/env python
"""Validation checks for V20.92 evidence blocker gap resolver outputs."""

from __future__ import annotations

import csv
import hashlib
import py_compile
import subprocess
from pathlib import Path


SCRIPT = Path("scripts") / "v20" / "v20_92_evidence_blocker_gap_resolver.py"
TEST_SCRIPT = Path("scripts") / "v20" / "test_v20_92_evidence_blocker_gap_resolver.py"
WRAPPER = Path("scripts") / "v20" / "run_v20_92_evidence_blocker_gap_resolver.ps1"
EVIDENCE = Path("outputs") / "v20" / "evidence"

VERSIONED = EVIDENCE / "V20_92_EVIDENCE_BLOCKER_GAP_RESOLVER.csv"
VERSIONED_SUMMARY = EVIDENCE / "V20_92_EVIDENCE_BLOCKER_GAP_RESOLVER_SUMMARY.md"
CURRENT = EVIDENCE / "V20_CURRENT_EVIDENCE_BLOCKER_GAP_RESOLVER.csv"
CURRENT_SUMMARY = EVIDENCE / "V20_CURRENT_EVIDENCE_BLOCKER_GAP_RESOLVER_SUMMARY.md"
R5_DETAIL = EVIDENCE / "V20_CURRENT_MULTI_PATH_VALIDATION_DETAIL.csv"
R2_DETAIL = EVIDENCE / "V20_CURRENT_REQUIRED_PATH_INTEGRATION_DETAIL.csv"

EXPECTED_STATUS = "PASS_V20_92_EVIDENCE_BLOCKER_GAP_RESOLVER_CREATED"
REQUIRED_COLUMNS = {
    "category",
    "manifest_status",
    "v20_82_validation_status",
    "v20_84_integration_status",
    "blocker_status",
    "blocker_reason",
    "missing_source_file",
    "missing_alias",
    "missing_schema_fields",
    "missing_certification",
    "missing_row_count",
    "missing_unique_ticker_count",
    "missing_benchmark_count",
    "missing_regime_count",
    "recommended_next_stage",
    "recommended_fix_type",
    "blocking_if_missing",
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


def parse_wrapper() -> None:
    command = (
        "$tokens=$null;$errors=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile('{WRAPPER.as_posix()}', [ref]$tokens, [ref]$errors) > $null;"
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
    )
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command], text=True, capture_output=True, check=False)
    assert_true(result.returncode == 0, f"PowerShell wrapper parse failed: {result.stdout}\n{result.stderr}")


def expected_counts() -> dict[str, int]:
    r5 = {row["validation_category"]: row["validation_status"] for row in read_csv(R5_DETAIL)}
    r2 = {row["integration_category"]: row["integration_status"] for row in read_csv(R2_DETAIL)}
    counts = {"PASS": 0, "WARN": 0, "BLOCKED": 0}
    for category in sorted(set(r5) | set(r2)):
        statuses = {r5.get(category, ""), r2.get(category, "")}
        if "BLOCKED" in statuses:
            counts["BLOCKED"] += 1
        elif "WARN" in statuses:
            counts["WARN"] += 1
        else:
            counts["PASS"] += 1
    return counts


def test_outputs() -> None:
    for path in [VERSIONED, VERSIONED_SUMMARY, CURRENT, CURRENT_SUMMARY]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing or empty output: {path}")
    assert_true(sha256(VERSIONED) == sha256(CURRENT), "current resolver alias differs from versioned output")
    assert_true(sha256(VERSIONED_SUMMARY) == sha256(CURRENT_SUMMARY), "current summary alias differs from versioned output")
    rows = read_csv(VERSIONED)
    assert_true(rows, "resolver rows empty")
    assert_true(REQUIRED_COLUMNS.issubset(rows[0].keys()), "resolver missing required columns")
    counts = {status: sum(row["blocker_status"] == status for row in rows) for status in ["PASS", "WARN", "BLOCKED"]}
    assert_true(counts == expected_counts(), f"resolver counts do not match V20.82/V20.84 detail: {counts} vs {expected_counts()}")
    for row in rows:
        assert_true(row["research_only"] == "TRUE", f"research_only invariant failed: {row}")
        assert_true(row["official_recommendation_created"] == "FALSE", f"official recommendation created: {row}")
        assert_true(row["official_weight_mutated"] == "FALSE", f"official weight mutated: {row}")
        assert_true(row["trade_action_created"] == "FALSE", f"trade action created: {row}")
        if row["blocker_status"] == "BLOCKED" and any(token in row["blocker_reason"] for token in ["MISSING_REQUIRED_PATH", "MISSING_FILE"]):
            assert_true(row["recommended_fix_type"] == "SOURCE_PATH_GAP", f"missing file not classified as source path gap: {row}")
        if "CERTIFICATION" in row["blocker_reason"] and "MISSING_SCHEMA_FIELDS" not in row["blocker_reason"]:
            assert_true(row["recommended_fix_type"] == "CERTIFICATION_GAP", f"certification blocker not classified: {row}")
    summary = VERSIONED_SUMMARY.read_text(encoding="utf-8")
    for token in ["final_status:", "pass_count:", "warn_count:", "blocked_count:", "recommended_next_stages:"]:
        assert_true(token in summary, f"summary missing {token}")
    assert_true(EXPECTED_STATUS in summary, "summary missing final status")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_outputs()
    print("PASS_V20_92_EVIDENCE_BLOCKER_GAP_RESOLVER_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
