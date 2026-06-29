#!/usr/bin/env python
"""Tests for V21.003-R1 risk/regime audit sanity repair."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_003_r1_risk_regime_audit_sanity_repair.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_003_r1_risk_regime_audit_sanity_repair.ps1"
V20_DIR = ROOT / "outputs" / "v20"
V21_AUDIT_DIR = ROOT / "outputs" / "v21" / "audit"
V21_ABLATION_DIR = ROOT / "outputs" / "v21" / "ablation"
V21_RECAL_DIR = ROOT / "outputs" / "v21" / "recalibration"
V21_RECAL_R1_DIR = ROOT / "outputs" / "v21" / "recalibration_r1"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_003_R1_RISK_REGIME_AUDIT_SANITY_REPAIR_REPORT.md"
REQUIRED_OUTPUTS = [
    V21_RECAL_R1_DIR / "V21_003_R1_INPUT_VALIDATION.csv",
    V21_RECAL_R1_DIR / "V21_003_R1_OVERHEAT_STATUS_SANITY_AUDIT.csv",
    V21_RECAL_R1_DIR / "V21_003_R1_OVERHEAT_FALSE_BLOCK_AUDIT_REPAIRED.csv",
    V21_RECAL_R1_DIR / "V21_003_R1_RISK_SCORE_DIRECTION_AUDIT.csv",
    V21_RECAL_R1_DIR / "V21_003_R1_REGIME_SCORE_DIRECTION_AUDIT.csv",
    V21_RECAL_R1_DIR / "V21_003_R1_REPAIRED_RISK_OVERPENALIZATION_CANDIDATES.csv",
    V21_RECAL_R1_DIR / "V21_003_R1_REPAIRED_REGIME_MISALIGNMENT_CANDIDATES.csv",
    V21_RECAL_R1_DIR / "V21_003_R1_REPAIRED_RECALIBRATION_PLAN.csv",
    V21_RECAL_R1_DIR / "V21_003_R1_NEXT_STAGE_GATE.csv",
    REPORT,
]
ALLOWED_STATUSES = {
    "FAIL_V21_003_R1_REQUIRED_INPUTS_MISSING",
    "FAIL_V21_003_R1_JOINED_ROWS_MISSING",
    "PARTIAL_PASS_V21_003_R1_OVERHEAT_AUDIT_CONTAMINATED_REPAIRED",
    "PARTIAL_PASS_V21_003_R1_SCORE_DIRECTION_AMBIGUOUS",
    "PASS_V21_003_R1_AUDIT_SANITY_REPAIRED_READY_FOR_SIMULATION_SELECTION",
}
SAFETY_FIELDS = [
    "official_weight_mutated",
    "official_recommendation_created",
    "real_book_signal_created",
    "broker_execution_supported",
    "trade_action_created",
    "shadow_weight_activated",
]
NEGATIVE_OVERHEAT_TOKENS = {"NOT_OVERHEAT", "NON_OVERHEAT", "NO_OVERHEAT", "FALSE", "NONE", "NO_MATCH", "NEUTRAL", "UNKNOWN"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def snapshot(paths: list[Path]) -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in paths if path.exists()}


def run_stage() -> subprocess.CompletedProcess[str]:
    v20_paths = [path for path in V20_DIR.rglob("*") if path.is_file()]
    v21_001_paths = [path for path in V21_AUDIT_DIR.glob("V21_001_*")]
    v21_002_paths = [path for path in V21_ABLATION_DIR.glob("V21_002_*")]
    v21_003_paths = [path for path in V21_RECAL_DIR.glob("V21_003_*")]
    before_v20 = snapshot(v20_paths)
    before_001 = snapshot(v21_001_paths)
    before_002 = snapshot(v21_002_paths)
    before_003 = snapshot(v21_003_paths)
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after_v20 = snapshot(v20_paths)
    after_001 = snapshot(v21_001_paths)
    after_002 = snapshot(v21_002_paths)
    after_003 = snapshot(v21_003_paths)
    assert all(after_v20.get(path) == mtime for path, mtime in before_v20.items()), "V20 files modified"
    assert all(after_001.get(path) == mtime for path, mtime in before_001.items()), "V21.001 files modified"
    assert all(after_002.get(path) == mtime for path, mtime in before_002.items()), "V21.002 files modified"
    assert all(after_003.get(path) == mtime for path, mtime in before_003.items()), "V21.003 files modified"
    return result


def test_v21_003_r1_contract() -> None:
    result = run_stage()
    assert "STAGE_NAME=V21_003_R1_RISK_REGIME_AUDIT_SANITY_REPAIR" in result.stdout

    for path in REQUIRED_OUTPUTS:
        assert path.exists(), f"missing output {path}"

    gate_rows = read_csv(V21_RECAL_R1_DIR / "V21_003_R1_NEXT_STAGE_GATE.csv")
    assert gate_rows, "gate is empty"
    gate = gate_rows[0]
    assert gate["final_status"] in ALLOWED_STATUSES
    for field in SAFETY_FIELDS:
        assert gate[field] == "FALSE", field

    repaired_overheat_rows = read_csv(V21_RECAL_R1_DIR / "V21_003_R1_OVERHEAT_FALSE_BLOCK_AUDIT_REPAIRED.csv")
    for row in repaired_overheat_rows:
        status = (row.get("overheat_status") or "").upper()
        assert not any(token in status for token in NEGATIVE_OVERHEAT_TOKENS), status

    report_text = REPORT.read_text(encoding="utf-8").lower()
    for expected in [
        "final_status",
        "contamination_ratio",
        "risk-score direction audit",
        "regime-score direction audit",
        "next recommended action",
    ]:
        assert expected in report_text

    script_text = SCRIPT.read_text(encoding="utf-8").lower()
    assert "yfinance" not in script_text
    blocked_terms = ["requests.", "urllib.request", "http.client", "socket.", "download("]
    for term in blocked_terms:
        assert term not in script_text, f"network access term found: {term}"

    for path in V21_RECAL_R1_DIR.rglob("*"):
        if path.is_file():
            assert not any(marker in path.name.lower() for marker in ["official_recommendation", "trade_action", "broker_execution", "weight_mutated"]), path

    assert int(gate["repaired_true_overheat_row_count"]) >= int(gate["repaired_false_block_candidate_count"])


def test_wrapper_parseable() -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    for expected in [
        "STAGE_NAME=V21_003_R1_RISK_REGIME_AUDIT_SANITY_REPAIR",
        "final_status=",
        "original_overheat_false_block_candidate_count=",
        "repaired_true_overheat_row_count=",
        "repaired_false_block_candidate_count=",
        "removed_not_overheat_row_count=",
        "contamination_ratio=",
        "risk_score_direction_audited_field_count=",
        "regime_score_direction_audited_field_count=",
        "next_recommended_action=",
    ]:
        assert expected in result.stdout


if __name__ == "__main__":
    test_v21_003_r1_contract()
    test_wrapper_parseable()
    print("V21_003-R1 risk/regime audit sanity repair tests passed")
