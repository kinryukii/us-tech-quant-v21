#!/usr/bin/env python
"""Validation checks for V20.89 required evidence path manifest outputs."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path("scripts") / "v20" / "v20_89_required_evidence_path_manifest.py"
WRAPPER = Path("scripts") / "v20" / "run_v20_89_required_evidence_path_manifest.ps1"
OUTPUT_DIR = Path("outputs") / "v20" / "evidence"

VERSIONED_MANIFEST = OUTPUT_DIR / "V20_89_REQUIRED_EVIDENCE_PATH_MANIFEST.csv"
VERSIONED_SUMMARY = OUTPUT_DIR / "V20_89_REQUIRED_EVIDENCE_PATH_MANIFEST_SUMMARY.md"
CURRENT_MANIFEST = OUTPUT_DIR / "V20_CURRENT_REQUIRED_EVIDENCE_PATH_MANIFEST.csv"
CURRENT_SUMMARY = OUTPUT_DIR / "V20_CURRENT_REQUIRED_EVIDENCE_PATH_MANIFEST_SUMMARY.md"

EXPECTED_STATUS = "PASS_V20_89_REQUIRED_EVIDENCE_PATH_MANIFEST_CREATED_WITH_BLOCKERS_ALLOWED"

REQUIRED_COLUMNS = {
    "path_id",
    "evidence_family",
    "required_level",
    "required_for",
    "expected_source_file",
    "expected_current_alias",
    "expected_schema_fields",
    "min_row_count",
    "min_unique_ticker_count",
    "min_benchmark_count",
    "min_regime_count",
    "certification_required",
    "blocking_if_missing",
    "current_status",
    "missing_reason",
    "next_required_stage",
    "research_only",
    "official_recommendation_created",
    "official_weight_mutated",
    "trade_action_created",
}

REQUIRED_PATH_IDS = {
    "certified_etf_rotation_evidence",
    "regime_conditioned_evidence",
    "downside_risk_evidence",
    "benchmark_comparison_evidence",
    "multi_window_strategy_evidence",
    "score_lineage_evidence",
    "ranking_delta_diagnostic_evidence",
    "acceptance_proof_evidence",
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
    spec = importlib.util.spec_from_file_location("v20_89_required_evidence_path_manifest", SCRIPT)
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
    for path in [VERSIONED_MANIFEST, VERSIONED_SUMMARY, CURRENT_MANIFEST, CURRENT_SUMMARY]:
        assert_true(path.exists(), f"missing output: {path}")
        assert_true(path.stat().st_size > 0, f"empty output: {path}")
    assert_true(sha256(VERSIONED_MANIFEST) == sha256(CURRENT_MANIFEST), "current manifest alias differs from versioned output")
    assert_true(sha256(VERSIONED_SUMMARY) == sha256(CURRENT_SUMMARY), "current summary alias differs from versioned output")

    rows = read_csv(VERSIONED_MANIFEST)
    assert_true(bool(rows), "manifest rows are empty")
    assert_true(REQUIRED_COLUMNS.issubset(rows[0].keys()), "manifest missing required columns")
    path_ids = {row["path_id"] for row in rows}
    assert_true(REQUIRED_PATH_IDS.issubset(path_ids), f"missing path ids: {sorted(REQUIRED_PATH_IDS - path_ids)}")

    for row in rows:
        assert_true(row["research_only"] == "TRUE", f"research_only invariant failed: {row['path_id']}")
        assert_true(row["official_recommendation_created"] == "FALSE", f"official recommendation created: {row['path_id']}")
        assert_true(row["official_weight_mutated"] == "FALSE", f"official weight mutated: {row['path_id']}")
        assert_true(row["trade_action_created"] == "FALSE", f"trade action created: {row['path_id']}")
        if row["blocking_if_missing"] == "TRUE" and row["missing_reason"] == "MISSING_REQUIRED_PATH":
            assert_true(row["current_status"] == "BLOCKED", f"required missing path did not block: {row}")
        if row["blocking_if_missing"] == "FALSE" and row["missing_reason"] == "MISSING_REQUIRED_PATH":
            assert_true(row["current_status"] == "WARN", f"optional missing path blocked: {row}")

    summary = VERSIONED_SUMMARY.read_text(encoding="utf-8")
    assert_true(f"final_status: {EXPECTED_STATUS}" in summary, "summary missing final status")
    assert_true("blocked_path_count:" in summary, "summary missing blocker count")
    assert_true("warn_path_count:" in summary, "summary missing warn count")


def write_temp_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_synthetic_rules(module) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)

        required_missing = module.EvidencePathSpec(
            "synthetic_required_missing",
            "synthetic",
            "REQUIRED",
            "test",
            "missing/source.csv",
            "missing/current.csv",
            ("ticker",),
            1,
            1,
            0,
            0,
            False,
            True,
            "TEST",
        )
        optional_missing = module.EvidencePathSpec(
            "synthetic_optional_missing",
            "synthetic",
            "OPTIONAL",
            "test",
            "missing/optional_source.csv",
            "missing/optional_current.csv",
            ("ticker",),
            1,
            1,
            0,
            0,
            False,
            False,
            "TEST",
        )
        required_row = module.evaluate_spec(required_missing, root)
        optional_row = module.evaluate_spec(optional_missing, root)
        assert_true(required_row["current_status"] == "BLOCKED", f"missing required path did not block: {required_row}")
        assert_true(required_row["missing_reason"] == "MISSING_REQUIRED_PATH", f"bad missing reason: {required_row}")
        assert_true(optional_row["current_status"] == "WARN", f"missing optional path blocked: {optional_row}")
        assert_true(optional_row["missing_reason"] == "MISSING_REQUIRED_PATH", f"bad optional missing reason: {optional_row}")

        source = root / "source.csv"
        alias = root / "current.csv"
        fields = ["ticker", "certification_status", "notes"]
        rows = [{"ticker": "AAA", "certification_status": "", "notes": "Certified in notes only"}]
        write_temp_csv(source, fields, rows)
        write_temp_csv(alias, fields, rows)
        notes_only = module.EvidencePathSpec(
            "synthetic_notes_only",
            "synthetic",
            "REQUIRED",
            "test",
            "source.csv",
            "current.csv",
            ("ticker", "certification_status", "notes"),
            1,
            1,
            0,
            0,
            True,
            True,
            "TEST",
        )
        row = module.evaluate_spec(notes_only, root)
        assert_true(row["current_status"] == "BLOCKED", f"notes-only certification was accepted: {row}")
        assert_true(row["missing_reason"] == "NOTES_ONLY_CERTIFICATION_REJECTED", f"notes-only reason missing: {row}")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(Path(__file__)), doraise=True)
    parse_wrapper()
    module = load_module()
    test_outputs()
    test_synthetic_rules(module)
    print("PASS_V20_89_REQUIRED_EVIDENCE_PATH_MANIFEST_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
