#!/usr/bin/env python
"""Tests for V21.004 factor backtest forensic audit and redesign."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_004_factor_backtest_forensic_audit_and_redesign.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_004_factor_backtest_forensic_audit_and_redesign.ps1"
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_004_FACTOR_BACKTEST_FORENSIC_AUDIT_AND_REDESIGN_REPORT.md"
REQUIRED_OUTPUTS = [
    OUT_DIR / "V21_004_FACTOR_BACKTEST_ARTIFACT_INVENTORY.csv",
    OUT_DIR / "V21_004_OBSERVATION_MATURITY_AUDIT.csv",
    OUT_DIR / "V21_004_LEAKAGE_RISK_AUDIT.csv",
    OUT_DIR / "V21_004_FACTOR_EVIDENCE_CAPABILITY_MATRIX.csv",
    OUT_DIR / "V21_004_DECISION_GRADE_GAP_TABLE.csv",
    OUT_DIR / "V21_004_REDESIGN_CONTRACT.csv",
    REPORT,
]
UPSTREAM_ROOTS = [
    ROOT / "outputs" / "v20",
    ROOT / "outputs" / "v21" / "audit",
    ROOT / "outputs" / "v21" / "ablation",
    ROOT / "outputs" / "v21" / "recalibration",
    ROOT / "outputs" / "v21" / "recalibration_r1",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def snapshot(paths: list[Path]) -> dict[Path, int]:
    result: dict[Path, int] = {}
    for root in paths:
        if root.exists():
            for path in root.rglob("*"):
                if path.is_file():
                    result[path] = path.stat().st_mtime_ns
    return result


def run_stage() -> subprocess.CompletedProcess[str]:
    before = snapshot(UPSTREAM_ROOTS)
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = snapshot(UPSTREAM_ROOTS)
    changed = [path for path, mtime in before.items() if after.get(path) != mtime]
    assert not changed, f"upstream official/evidence files modified: {changed[:3]}"
    return result


def test_v21_004_contract() -> None:
    result = run_stage()
    assert "STAGE_NAME=V21_004_FACTOR_BACKTEST_FORENSIC_AUDIT_AND_REDESIGN" in result.stdout

    for path in REQUIRED_OUTPUTS:
        assert path.exists(), f"missing required output {path}"
        assert path.stat().st_size > 0, f"empty required output {path}"

    contract_rows = read_csv(OUT_DIR / "V21_004_REDESIGN_CONTRACT.csv")
    assert contract_rows, "redesign contract missing rows"
    contract = contract_rows[0]
    assert contract["research_only"] == "TRUE"
    assert contract["audit_only"] == "TRUE"
    assert contract["official_ranking_mutation_count"] == "0"
    assert contract["official_factor_weight_mutation_count"] == "0"
    assert contract["official_recommendation_count"] == "0"
    assert contract["trade_action_count"] == "0"
    assert contract["shadow_activation"] == "FALSE"
    assert contract["data_trust_ranking_weight"] in {"0", ""}
    assert contract["data_trust_ranking_contribution"] in {"0", ""}

    matured = int(contract["matured_observations"])
    usable_snapshots = int(contract["usable_snapshots"])
    required_matured = int(contract["minimum_decision_grade_matured_observations"])
    required_snapshots = int(contract["minimum_decision_grade_usable_snapshots"])
    verdict = contract["final_verdict"]
    if matured < required_matured or usable_snapshots < required_snapshots:
        assert verdict != "DECISION_GRADE_READY"

    gap_rows = read_csv(OUT_DIR / "V21_004_DECISION_GRADE_GAP_TABLE.csv")
    if verdict == "DECISION_GRADE_READY":
        assert all(row["gap_status"] == "PASS" for row in gap_rows)
    else:
        assert any(row["gap_status"] == "GAP" for row in gap_rows)

    capability_rows = read_csv(OUT_DIR / "V21_004_FACTOR_EVIDENCE_CAPABILITY_MATRIX.csv")
    assert any(row["capability"] == "trade_entry_exit_policy" for row in capability_rows)
    assert all(row["can_support_official_action"] == "FALSE" for row in capability_rows)

    leakage_rows = read_csv(OUT_DIR / "V21_004_LEAKAGE_RISK_AUDIT.csv")
    assert any(row["risk_id"] == "missing_as_of_source_contract" for row in leakage_rows)

    observation_rows = read_csv(OUT_DIR / "V21_004_OBSERVATION_MATURITY_AUDIT.csv")
    assert observation_rows, "observation maturity audit missing rows"
    assert any(row["maturity_status"] in {"MATURED", "PENDING", "REJECTED"} for row in observation_rows)

    report_text = REPORT.read_text(encoding="utf-8").lower()
    for expected in [
        "research_only: true",
        "audit_only: true",
        "current backtest credibility verdict",
        "data_trust treatment confirmation",
        "explicit blocked actions",
        "v21.005_point_in_time_walk_forward_factor_backtest_engine",
    ]:
        assert expected in report_text

    script_text = SCRIPT.read_text(encoding="utf-8").lower()
    assert "yfinance" not in script_text
    for blocked_term in ["requests.", "urllib.request", "http.client", "socket.", "download("]:
        assert blocked_term not in script_text, f"network access term found: {blocked_term}"


def test_wrapper_parseable() -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    for expected in [
        "STAGE_NAME=V21_004_FACTOR_BACKTEST_FORENSIC_AUDIT_AND_REDESIGN",
        "final_verdict=",
        "final_status=",
        "matured_observations=",
        "official_ranking_mutation_count=0",
        "official_recommendation_count=0",
        "trade_action_count=0",
        "shadow_activation=FALSE",
        "research_only=TRUE",
    ]:
        assert expected in result.stdout


if __name__ == "__main__":
    test_v21_004_contract()
    test_wrapper_parseable()
    print("V21.004 factor backtest forensic audit and redesign tests passed")
