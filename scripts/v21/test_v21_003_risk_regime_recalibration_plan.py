#!/usr/bin/env python
"""Tests for V21.003 risk/regime recalibration plan."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_003_risk_regime_recalibration_plan.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_003_risk_regime_recalibration_plan.ps1"
OUT_DIR = ROOT / "outputs" / "v21" / "recalibration"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_003_RISK_REGIME_RECALIBRATION_PLAN_REPORT.md"
REQUIRED_OUTPUTS = [
    OUT_DIR / "V21_003_INPUT_DISCOVERY.csv",
    OUT_DIR / "V21_003_RISK_REGIME_FIELD_MAP.csv",
    OUT_DIR / "V21_003_RISK_REGIME_JOINED_OUTCOME_ROWS.csv",
    OUT_DIR / "V21_003_REGIME_SEGMENT_PERFORMANCE.csv",
    OUT_DIR / "V21_003_RISK_SCORE_DECILE_PERFORMANCE.csv",
    OUT_DIR / "V21_003_OVERHEAT_FALSE_BLOCK_AUDIT.csv",
    OUT_DIR / "V21_003_RISK_OVERPENALIZATION_CANDIDATES.csv",
    OUT_DIR / "V21_003_REGIME_MISALIGNMENT_CANDIDATES.csv",
    OUT_DIR / "V21_003_RECALIBRATION_SCENARIOS.csv",
    OUT_DIR / "V21_003_RECALIBRATION_PLAN.csv",
    OUT_DIR / "V21_003_NEXT_STAGE_GATE.csv",
    REPORT,
]
ALLOWED_STATUSES = {
    "FAIL_V21_003_REQUIRED_INPUTS_MISSING",
    "FAIL_V21_003_NO_RISK_REGIME_FIELDS_DETECTED",
    "PARTIAL_PASS_V21_003_LIMITED_RISK_REGIME_COVERAGE",
    "PARTIAL_PASS_V21_003_RECALIBRATION_EVIDENCE_LIMITED",
    "PASS_V21_003_RISK_REGIME_RECALIBRATION_PLAN_READY",
}
SAFETY_FIELDS = [
    "official_weight_mutated",
    "official_recommendation_created",
    "real_book_signal_created",
    "broker_execution_supported",
    "trade_action_created",
    "shadow_weight_activated",
]
OFFICIAL_MARKERS = [
    "official_recommendation",
    "trade_action",
    "broker_execution",
    "weight_mutated",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def snapshot(paths: list[Path]) -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in paths if path.exists()}


def run_stage() -> subprocess.CompletedProcess[str]:
    v20_paths = [path for path in (ROOT / "outputs" / "v20").rglob("*") if path.is_file()]
    v21_001_paths = [path for path in (ROOT / "outputs" / "v21" / "audit").glob("V21_001_*")]
    v21_002_paths = [path for path in (ROOT / "outputs" / "v21" / "ablation").glob("V21_002_*")]
    before_v20 = snapshot(v20_paths)
    before_001 = snapshot(v21_001_paths)
    before_002 = snapshot(v21_002_paths)
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after_v20 = snapshot(v20_paths)
    after_001 = snapshot(v21_001_paths)
    after_002 = snapshot(v21_002_paths)
    assert all(after_v20.get(path) == mtime for path, mtime in before_v20.items()), "V20 files modified"
    assert all(after_001.get(path) == mtime for path, mtime in before_001.items()), "V21.001 files modified"
    assert all(after_002.get(path) == mtime for path, mtime in before_002.items()), "V21.002 files modified"
    return result


def test_v21_003_contract() -> None:
    result = run_stage()
    assert "STAGE_NAME=V21_003_RISK_REGIME_RECALIBRATION_PLAN" in result.stdout

    for path in REQUIRED_OUTPUTS:
        assert path.exists(), f"missing output {path}"

    gate_rows = read_csv(OUT_DIR / "V21_003_NEXT_STAGE_GATE.csv")
    assert gate_rows, "gate is empty"
    gate = gate_rows[0]
    assert gate["final_status"] in ALLOWED_STATUSES
    for field in SAFETY_FIELDS:
        assert gate[field] == "FALSE", field

    report_text = REPORT.read_text(encoding="utf-8").lower()
    for expected in [
        "final_status",
        "joined_risk_regime_outcome_rows",
        "regime segment performance",
        "risk-score decile performance",
        "overheat false-block audit",
        "recalibration plan",
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
            assert not any(marker in path.name.lower() for marker in OFFICIAL_MARKERS), path

    assert int(gate["joined_risk_regime_outcome_rows"]) >= 500
    assert int(gate["evaluated_regime_segment_count"]) >= 1
    assert int(gate["recalibration_scenario_count"]) >= 3


def test_wrapper_parseable() -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    for expected in [
        "STAGE_NAME=V21_003_RISK_REGIME_RECALIBRATION_PLAN",
        "final_status=",
        "joined_risk_regime_outcome_rows=",
        "evaluated_regime_segment_count=",
        "evaluated_risk_score_field_count=",
        "overheat_false_block_candidate_count=",
        "risk_overpenalization_candidate_count=",
        "regime_misalignment_candidate_count=",
        "recalibration_scenario_count=",
        "next_recommended_action=",
    ]:
        assert expected in result.stdout


if __name__ == "__main__":
    test_v21_003_contract()
    test_wrapper_parseable()
    print("V21_003 risk/regime recalibration plan tests passed")
