#!/usr/bin/env python
"""Tests for V21.001 baseline strategy performance audit."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_001_baseline_strategy_performance_audit.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_001_baseline_strategy_performance_audit.ps1"
OUT_DIR = ROOT / "outputs" / "v21" / "audit"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_001_BASELINE_STRATEGY_PERFORMANCE_AUDIT_REPORT.md"
REQUIRED_OUTPUTS = [
    OUT_DIR / "V21_001_INPUT_DISCOVERY.csv",
    OUT_DIR / "V21_001_BASELINE_RANKING_SNAPSHOT.csv",
    OUT_DIR / "V21_001_FORWARD_OUTCOME_ROWS.csv",
    OUT_DIR / "V21_001_BUCKET_PERFORMANCE_SUMMARY.csv",
    OUT_DIR / "V21_001_LABEL_FORWARD_PERFORMANCE.csv",
    OUT_DIR / "V21_001_BENCHMARK_RELATIVE_PERFORMANCE.csv",
    OUT_DIR / "V21_001_FAILURE_CASES_TOP_RANKED.csv",
    OUT_DIR / "V21_001_NEXT_STAGE_GATE.csv",
    REPORT,
]
ALLOWED_STATUSES = {
    "FAIL_V21_001_NO_RANKING_INPUT_FOUND",
    "PARTIAL_PASS_V21_001_DISCOVERY_READY_OUTCOME_DATA_INSUFFICIENT",
    "PARTIAL_PASS_V21_001_LIMITED_OUTCOME_EVIDENCE",
    "PASS_V21_001_BASELINE_AUDIT_READY_FOR_FACTOR_ABLATION",
}
SAFETY_FIELDS = [
    "official_weight_mutated",
    "official_recommendation_created",
    "real_book_signal_created",
    "broker_execution_supported",
    "trade_action_created",
    "shadow_weight_activated",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def v20_mtimes() -> dict[Path, int]:
    base = ROOT / "outputs" / "v20"
    if not base.exists():
        return {}
    return {path: path.stat().st_mtime_ns for path in base.rglob("*") if path.is_file()}


def run_stage() -> subprocess.CompletedProcess[str]:
    before = v20_mtimes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = v20_mtimes()
    changed = [path for path, mtime in before.items() if after.get(path) != mtime]
    assert not changed, f"V20 files modified: {changed[:5]}"
    return result


def test_v21_001_contract() -> None:
    result = run_stage()
    assert "STAGE_NAME=V21_001_BASELINE_STRATEGY_PERFORMANCE_AUDIT" in result.stdout

    for path in REQUIRED_OUTPUTS:
        assert path.exists(), f"missing output {path}"

    gate_rows = read_csv(OUT_DIR / "V21_001_NEXT_STAGE_GATE.csv")
    assert gate_rows, "gate is empty"
    gate = gate_rows[0]
    assert gate["final_status"] in ALLOWED_STATUSES
    for field in SAFETY_FIELDS:
        assert gate[field] == "FALSE", field

    report_text = REPORT.read_text(encoding="utf-8").lower()
    for expected in ["final_status", "evaluated_forward_rows", "strategy diagnosis", "next recommended action"]:
        assert expected in report_text

    script_text = SCRIPT.read_text(encoding="utf-8").lower()
    assert "yfinance" not in script_text
    blocked_terms = ["requests.", "urllib.request", "http.client", "socket.", "download("]
    for term in blocked_terms:
        assert term not in script_text, f"network access term found: {term}"


def test_wrapper_parseable() -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    for expected in [
        "STAGE_NAME=V21_001_BASELINE_STRATEGY_PERFORMANCE_AUDIT",
        "final_status=",
        "evaluated_forward_rows=",
        "evaluated_as_of_date_count=",
        "next_recommended_action=",
    ]:
        assert expected in result.stdout


if __name__ == "__main__":
    test_v21_001_contract()
    test_wrapper_parseable()
    print("V21_001 baseline strategy performance audit tests passed")
