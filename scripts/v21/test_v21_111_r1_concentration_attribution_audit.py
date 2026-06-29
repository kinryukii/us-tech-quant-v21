#!/usr/bin/env python
"""Validation checks for V21.111-R1 concentration attribution audit."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/v21/V21.111_R1_CONCENTRATION_ATTRIBUTION_AUDIT"
SCRIPT = ROOT / "scripts/v21/v21_111_r1_concentration_attribution_audit.py"
SUMMARY = OUT / "V21.111_R1_CONCENTRATION_ATTRIBUTION_AUDIT_SUMMARY.json"
REPORT = OUT / "V21.111_R1_CONCENTRATION_ATTRIBUTION_AUDIT_REPORT.md"
MANIFEST = OUT / "V21.111_R1_CONCENTRATION_ATTRIBUTION_AUDIT_MANIFEST.csv"


def run_stage() -> str:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(ROOT)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "RESEARCH_ONLY: true" in result.stdout
    assert "OFFICIAL_ADOPTION_ALLOWED: false" in result.stdout
    assert "BROKER_ACTION_ALLOWED: false" in result.stdout
    assert "PROTECTED_OUTPUTS_MODIFIED: false" in result.stdout
    return result.stdout


def summary() -> dict:
    assert SUMMARY.is_file()
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def test_controls_and_required_outputs() -> None:
    run_stage()
    payload = summary()
    assert payload["research_only"] is True
    assert payload["official_adoption_allowed"] is False
    assert payload["broker_action_allowed"] is False
    assert payload["protected_outputs_modified"] is False
    assert payload["official_outputs_modified"] is False
    assert payload["source_ranking_files_modified"] is False
    assert payload["model_weights_changed"] is False
    assert payload["trade_instructions_produced"] is False
    assert REPORT.is_file()
    assert MANIFEST.is_file()


def test_csv_outputs_are_readable_and_isolated() -> None:
    payload = summary()
    assert payload["output_dir"].endswith("V21.111_R1_CONCENTRATION_ATTRIBUTION_AUDIT")
    csvs = sorted(OUT.glob("*.csv"))
    assert csvs
    for path in csvs:
        pd.read_csv(path)
    manifest = pd.read_csv(MANIFEST)
    assert not manifest.empty
    assert manifest["path"].astype(str).str.contains("V21.111_R1_CONCENTRATION_ATTRIBUTION_AUDIT").all()
    assert manifest["research_only"].astype(str).str.upper().isin(["TRUE", "1"]).all()


def test_missing_classification_is_partial_not_pass() -> None:
    payload = summary()
    if not payload["classification_data_available"]:
        assert payload["final_status"] == "PARTIAL_PASS"
        assert payload["decision"] == "D_CONCENTRATION_ATTRIBUTION_PARTIAL_MISSING_CLASSIFICATION_DATA"


def test_material_concentration_warning_rule() -> None:
    payload = summary()
    if (
        float(payload["d_top20_top_sector_weight"]) >= 0.70
        and float(payload["d_vs_universe_top_sector_overweight"]) >= 0.20
        and payload["classification_data_available"]
    ):
        assert payload["concentration_warning"] is True
        assert payload["decision"] == "D_CONCENTRATION_ATTRIBUTION_WARN_SECTOR_OR_INDUSTRY_CLUSTERING"


if __name__ == "__main__":
    test_controls_and_required_outputs()
    test_csv_outputs_are_readable_and_isolated()
    test_missing_classification_is_partial_not_pass()
    test_material_concentration_warning_rule()
    print("PASS test_v21_111_r1_concentration_attribution_audit")
