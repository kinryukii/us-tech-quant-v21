#!/usr/bin/env python
"""Validation checks for V20.89 evidence coverage matrix outputs."""

from __future__ import annotations

import csv
import hashlib
import json
import py_compile
from pathlib import Path


SCRIPT = Path("scripts") / "v20" / "v20_89_evidence_coverage_matrix.py"
OUTPUT_DIR = Path("outputs") / "v20" / "evidence_coverage"

VERSIONED = {
    "matrix": OUTPUT_DIR / "V20_89_EVIDENCE_COVERAGE_MATRIX.csv",
    "summary": OUTPUT_DIR / "V20_89_EVIDENCE_COVERAGE_SUMMARY.csv",
    "gap_table": OUTPUT_DIR / "V20_89_EVIDENCE_COVERAGE_GAP_TABLE.csv",
    "report": OUTPUT_DIR / "V20_89_EVIDENCE_COVERAGE_REPORT.md",
    "manifest": OUTPUT_DIR / "V20_89_EVIDENCE_COVERAGE_MANIFEST.json",
}

ALIASES = {
    "matrix": OUTPUT_DIR / "V20_CURRENT_EVIDENCE_COVERAGE_MATRIX.csv",
    "summary": OUTPUT_DIR / "V20_CURRENT_EVIDENCE_COVERAGE_SUMMARY.csv",
    "gap_table": OUTPUT_DIR / "V20_CURRENT_EVIDENCE_COVERAGE_GAP_TABLE.csv",
    "report": OUTPUT_DIR / "V20_CURRENT_EVIDENCE_COVERAGE_REPORT.md",
    "manifest": OUTPUT_DIR / "V20_CURRENT_EVIDENCE_COVERAGE_MANIFEST.json",
}

REQUIRED_COLUMNS = {
    "ticker",
    "evidence_universe_source",
    "base_candidate_present",
    "multi_path_evidence_status",
    "multi_path_usable",
    "etf_rotation_evidence_status",
    "etf_rotation_usable",
    "regime_evidence_status",
    "regime_usable",
    "downside_risk_evidence_status",
    "downside_risk_usable",
    "benchmark_comparison_evidence_status",
    "benchmark_comparison_usable",
    "usable_evidence_family_count",
    "required_evidence_family_count",
    "evidence_coverage_ratio",
    "evidence_coverage_tier",
    "shadow_ranking_eligible",
    "official_recommendation_eligible",
    "blocking_reason",
    "gap_reason",
    "notes",
}

STATUS_COLUMNS = [
    "multi_path_evidence_status",
    "etf_rotation_evidence_status",
    "regime_evidence_status",
    "downside_risk_evidence_status",
    "benchmark_comparison_evidence_status",
]

CONTROLLED_STATUSES = {
    "USABLE",
    "PARTIAL",
    "MISSING",
    "BLOCKED",
    "NOT_APPLICABLE",
    "UNKNOWN",
}

EXPECTED_FINAL_STATUSES = {
    "PASS_V20_89_EVIDENCE_COVERAGE_MATRIX_CREATED_WITH_PARTIAL_COVERAGE",
    "BLOCKED_V20_89_INSUFFICIENT_EVIDENCE_INPUTS",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)

    for name, path in VERSIONED.items():
        assert_true(path.exists(), f"missing versioned output: {name} {path}")
    for name, path in ALIASES.items():
        assert_true(path.exists(), f"missing current alias: {name} {path}")
        assert_true(sha256(path) == sha256(VERSIONED[name]), f"alias differs from versioned output: {name}")

    rows = read_csv(VERSIONED["matrix"])
    assert_true(bool(rows), "matrix is empty")
    assert_true(REQUIRED_COLUMNS.issubset(rows[0].keys()), "matrix missing required columns")

    for row in rows:
        assert_true(row["official_recommendation_eligible"] == "FALSE", "official eligibility must always be FALSE")
        assert_true(row["shadow_ranking_eligible"] in {"TRUE", "FALSE", "True", "False", "0", "1"}, "shadow eligibility is not boolean-compatible")
        ratio = float(row["evidence_coverage_ratio"])
        assert_true(0.0 <= ratio <= 1.0, f"coverage ratio out of range: {ratio}")
        for column in STATUS_COLUMNS:
            assert_true(row[column] in CONTROLLED_STATUSES, f"bad controlled status in {column}: {row[column]}")

    manifest = json.loads(VERSIONED["manifest"].read_text(encoding="utf-8"))
    assert_true("input_files_missing" in manifest, "manifest missing input_files_missing")
    assert_true(isinstance(manifest["input_files_missing"], dict), "manifest input_files_missing must be an object")
    if not manifest.get("input_files_found"):
        assert_true(bool(manifest["input_files_missing"]), "missing upstream inputs were not recorded")
    assert_true(manifest["final_status"] in EXPECTED_FINAL_STATUSES, "unexpected final status")

    output_names = [Path(path).name.upper() for path in manifest["output_files"].values()]
    forbidden = ["RECOMMENDATION", "TRADE_ACTION", "TRADE", "WEIGHT", "PORTFOLIO"]
    for name in output_names:
        assert_true(not any(token in name for token in forbidden), f"forbidden mutation-style output name: {name}")

    print("PASS_V20_89_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
