#!/usr/bin/env python
"""Validation checks for V21.111 D failure mode decomposition."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/v21/V21.111_D_FAILURE_MODE_DECOMPOSITION"
SCRIPT = ROOT / "scripts/v21/v21_111_d_failure_mode_decomposition.py"
SUMMARY = OUT / "V21.111_D_FAILURE_MODE_DECOMPOSITION_SUMMARY.json"
REPORT = OUT / "V21.111_D_FAILURE_MODE_DECOMPOSITION_REPORT.md"
MANIFEST = OUT / "V21.111_D_FAILURE_MODE_DECOMPOSITION_MANIFEST.csv"


def run_stage() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(ROOT)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "OFFICIAL_ADOPTION_ALLOWED: false" in result.stdout
    assert "BROKER_ACTION_ALLOWED: false" in result.stdout
    assert "PROTECTED_OUTPUTS_MODIFIED: false" in result.stdout


def load_summary() -> dict:
    assert SUMMARY.is_file()
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def test_summary_controls() -> None:
    run_stage()
    summary = load_summary()
    assert summary["research_only"] is True
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["protected_outputs_modified"] is False
    assert summary["source_ranking_files_modified"] is False
    assert summary["model_weights_changed"] is False
    assert summary["trade_instructions_produced"] is False


def test_required_outputs_exist_and_csvs_readable() -> None:
    summary = load_summary()
    assert summary["output_dir"].endswith("V21.111_D_FAILURE_MODE_DECOMPOSITION")
    assert REPORT.is_file()
    assert MANIFEST.is_file()
    csvs = sorted(OUT.glob("*.csv"))
    assert csvs
    for path in csvs:
        pd.read_csv(path)


def test_partial_when_forward_missing() -> None:
    summary = load_summary()
    if not summary["forward_data_available"]:
        assert summary["final_status"] == "PARTIAL_PASS"
        assert summary["decision"] == "D_FAILURE_MODE_DIAGNOSTIC_PARTIAL_INSUFFICIENT_FORWARD_DATA"


def test_isolated_output_manifest() -> None:
    manifest = pd.read_csv(MANIFEST)
    assert not manifest.empty
    assert manifest["path"].astype(str).str.contains("V21.111_D_FAILURE_MODE_DECOMPOSITION").all()
    assert manifest["research_only"].astype(str).str.upper().isin(["TRUE", "1"]).all()


if __name__ == "__main__":
    test_summary_controls()
    test_required_outputs_exist_and_csvs_readable()
    test_partial_when_forward_missing()
    test_isolated_output_manifest()
    print("PASS test_v21_111_d_failure_mode_decomposition")
