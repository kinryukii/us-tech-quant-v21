#!/usr/bin/env python
"""Validation checks for V20.93 evidence schema repair pack."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import py_compile
import subprocess
import sys
from pathlib import Path


SCRIPT = Path("scripts") / "v20" / "v20_93_evidence_schema_repair_pack.py"
TEST_SCRIPT = Path("scripts") / "v20" / "test_v20_93_evidence_schema_repair_pack.py"
WRAPPER = Path("scripts") / "v20" / "run_v20_93_evidence_schema_repair_pack.ps1"
EVIDENCE = Path("outputs") / "v20" / "evidence"

DETAIL = EVIDENCE / "V20_93_EVIDENCE_SCHEMA_REPAIR_DETAIL.csv"
SUMMARY = EVIDENCE / "V20_93_EVIDENCE_SCHEMA_REPAIR_SUMMARY.md"
CURRENT_DETAIL = EVIDENCE / "V20_CURRENT_EVIDENCE_SCHEMA_REPAIR_DETAIL.csv"
CURRENT_SUMMARY = EVIDENCE / "V20_CURRENT_EVIDENCE_SCHEMA_REPAIR_SUMMARY.md"
RESOLVER = EVIDENCE / "V20_CURRENT_EVIDENCE_BLOCKER_GAP_RESOLVER.csv"
EXPECTED_STATUS = "PASS_V20_93_EVIDENCE_SCHEMA_REPAIR_PACK_CREATED_WITH_PARTIAL_REPAIRS_ALLOWED"


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


def load_module():
    spec = importlib.util.spec_from_file_location("v20_93", SCRIPT)
    assert_true(spec is not None and spec.loader is not None, "could not load module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_outputs() -> None:
    for path in [DETAIL, SUMMARY, CURRENT_DETAIL, CURRENT_SUMMARY]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing or empty output: {path}")
    assert_true(sha256(DETAIL) == sha256(CURRENT_DETAIL), "detail alias differs")
    assert_true(sha256(SUMMARY) == sha256(CURRENT_SUMMARY), "summary alias differs")
    detail = read_csv(DETAIL)
    assert_true(detail, "repair detail empty")
    blocked = {row["category"] for row in read_csv(RESOLVER) if row["blocker_status"] == "BLOCKED"}
    assert_true(blocked.issubset({row["category"] for row in detail}), f"repair detail missing blocked categories: {blocked}")
    for row in detail:
        assert_true(row["research_only"] == "TRUE", f"research_only invariant failed: {row}")
        assert_true(row["official_recommendation_created"] == "FALSE", f"official recommendation created: {row}")
        assert_true(row["official_weight_mutated"] == "FALSE", f"official weight mutated: {row}")
        assert_true(row["trade_action_created"] == "FALSE", f"trade action created: {row}")
    summary = SUMMARY.read_text(encoding="utf-8")
    for token in [EXPECTED_STATUS, "repaired_count:", "partial_repaired_count:", "unrepaired_count:", "recommended_rerun_stages:"]:
        assert_true(token in summary, f"summary missing {token}")


def test_notes_only_rejected() -> None:
    module = load_module()
    assert_true(not module.structured_certified({"notes": "CERTIFIED_DOWNSIDE_RISK_EVIDENCE"}), "notes-only certification accepted")
    assert_true(module.structured_certified({"certification_status": "CERTIFIED_DOWNSIDE_RISK_EVIDENCE"}), "structured certification_status rejected")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_outputs()
    test_notes_only_rejected()
    print("PASS_V20_93_EVIDENCE_SCHEMA_REPAIR_PACK_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
