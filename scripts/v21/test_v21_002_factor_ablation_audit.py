#!/usr/bin/env python
"""Tests for V21.002 factor ablation audit."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_002_factor_ablation_audit.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_002_factor_ablation_audit.ps1"
OUT_DIR = ROOT / "outputs" / "v21" / "ablation"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_002_FACTOR_ABLATION_AUDIT_REPORT.md"
REQUIRED_OUTPUTS = [
    OUT_DIR / "V21_002_INPUT_DISCOVERY.csv",
    OUT_DIR / "V21_002_FACTOR_FIELD_MAP.csv",
    OUT_DIR / "V21_002_BASELINE_JOINED_FACTOR_OUTCOME_ROWS.csv",
    OUT_DIR / "V21_002_SINGLE_FACTOR_FAMILY_PERFORMANCE.csv",
    OUT_DIR / "V21_002_LEAVE_ONE_FAMILY_OUT_PERFORMANCE.csv",
    OUT_DIR / "V21_002_FACTOR_REMOVAL_IMPACT.csv",
    OUT_DIR / "V21_002_NEGATIVE_CONTRIBUTOR_CANDIDATES.csv",
    OUT_DIR / "V21_002_POSITIVE_CONTRIBUTOR_CANDIDATES.csv",
    OUT_DIR / "V21_002_RANKING_WEAKNESS_DIAGNOSIS.csv",
    OUT_DIR / "V21_002_NEXT_STAGE_GATE.csv",
    REPORT,
]
ALLOWED_STATUSES = {
    "FAIL_V21_002_REQUIRED_V21_001_INPUTS_MISSING",
    "FAIL_V21_002_NO_FACTOR_FIELDS_DETECTED",
    "PARTIAL_PASS_V21_002_LIMITED_FACTOR_COVERAGE",
    "PARTIAL_PASS_V21_002_ABLATION_EVIDENCE_LIMITED",
    "PASS_V21_002_FACTOR_ABLATION_READY_FOR_WEIGHT_REPAIR_PLAN",
}
SAFETY_FIELDS = [
    "official_weight_mutated",
    "official_recommendation_created",
    "real_book_signal_created",
    "broker_execution_supported",
    "trade_action_created",
    "shadow_weight_activated",
]
OFFICIAL_FILE_MARKERS = [
    "official_recommendation",
    "trade_action",
    "broker_execution",
    "weight_mutated",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def mtime_snapshot(paths: list[Path]) -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in paths if path.exists()}


def run_stage() -> subprocess.CompletedProcess[str]:
    v20_paths = [path for path in (ROOT / "outputs" / "v20").rglob("*") if path.is_file()]
    v21_001_paths = [path for path in (ROOT / "outputs" / "v21" / "audit").glob("V21_001_*.csv")]
    before_v20 = mtime_snapshot(v20_paths)
    before_v21_001 = mtime_snapshot(v21_001_paths)
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after_v20 = mtime_snapshot(v20_paths)
    after_v21_001 = mtime_snapshot(v21_001_paths)
    changed_v20 = [path for path, mtime in before_v20.items() if after_v20.get(path) != mtime]
    changed_v21_001 = [path for path, mtime in before_v21_001.items() if after_v21_001.get(path) != mtime]
    assert not changed_v20, f"V20 files modified: {changed_v20[:5]}"
    assert not changed_v21_001, f"V21.001 files modified: {changed_v21_001[:5]}"
    return result


def test_v21_002_contract() -> None:
    result = run_stage()
    assert "STAGE_NAME=V21_002_FACTOR_ABLATION_AUDIT" in result.stdout

    for path in REQUIRED_OUTPUTS:
        assert path.exists(), f"missing output {path}"

    gate_rows = read_csv(OUT_DIR / "V21_002_NEXT_STAGE_GATE.csv")
    assert gate_rows, "gate is empty"
    gate = gate_rows[0]
    assert gate["final_status"] in ALLOWED_STATUSES
    for field in SAFETY_FIELDS:
        assert gate[field] == "FALSE", field

    report_text = REPORT.read_text(encoding="utf-8").lower()
    for expected in [
        "final_status",
        "joined_factor_outcome_rows",
        "single factor-family performance",
        "leave-one-family-out performance",
        "ranking weakness diagnosis",
        "next recommended action",
    ]:
        assert expected in report_text

    script_text = SCRIPT.read_text(encoding="utf-8").lower()
    assert "yfinance" not in script_text
    blocked_terms = ["requests.", "urllib.request", "http.client", "socket.", "download("]
    for term in blocked_terms:
        assert term not in script_text, f"network access term found: {term}"

    for path in OUT_DIR.rglob("*"):
        if path.is_file():
            lower = path.name.lower()
            assert not any(marker in lower for marker in OFFICIAL_FILE_MARKERS), path

    assert int(gate["joined_factor_outcome_rows"]) >= 500
    assert int(gate["evaluated_factor_family_count"]) >= 3
    assert int(gate["negative_contributor_count"]) + int(gate["positive_contributor_count"]) >= 1


def test_wrapper_parseable() -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    for expected in [
        "STAGE_NAME=V21_002_FACTOR_ABLATION_AUDIT",
        "final_status=",
        "joined_factor_outcome_rows=",
        "evaluated_factor_family_count=",
        "negative_contributor_count=",
        "positive_contributor_count=",
        "next_recommended_action=",
    ]:
        assert expected in result.stdout


if __name__ == "__main__":
    test_v21_002_contract()
    test_wrapper_parseable()
    print("V21_002 factor ablation audit tests passed")
