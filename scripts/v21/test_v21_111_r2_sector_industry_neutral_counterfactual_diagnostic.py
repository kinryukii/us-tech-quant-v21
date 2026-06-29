#!/usr/bin/env python
"""Validation checks for V21.111-R2 neutral counterfactual diagnostic."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/v21/V21.111_R2_SECTOR_INDUSTRY_NEUTRAL_COUNTERFACTUAL_DIAGNOSTIC"
SCRIPT = ROOT / "scripts/v21/v21_111_r2_sector_industry_neutral_counterfactual_diagnostic.py"
SUMMARY = OUT / "V21.111_R2_SECTOR_INDUSTRY_NEUTRAL_COUNTERFACTUAL_DIAGNOSTIC_SUMMARY.json"
REPORT = OUT / "V21.111_R2_SECTOR_INDUSTRY_NEUTRAL_COUNTERFACTUAL_DIAGNOSTIC_REPORT.md"
MANIFEST = OUT / "V21.111_R2_SECTOR_INDUSTRY_NEUTRAL_COUNTERFACTUAL_DIAGNOSTIC_MANIFEST.csv"
RAW20_SOURCE = ROOT / "outputs/v21/V21.108_latest_data_multi_strategy_rerun/R2_archived_latest_strategy_rankings/D_WEIGHT_OPTIMIZED_R1/top20_ranking.csv"
RAW50_SOURCE = ROOT / "outputs/v21/V21.108_latest_data_multi_strategy_rerun/R2_archived_latest_strategy_rankings/D_WEIGHT_OPTIMIZED_R1/top50_ranking.csv"


def run_stage() -> None:
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


def payload() -> dict:
    assert SUMMARY.is_file()
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def test_required_outputs_and_controls() -> None:
    run_stage()
    data = payload()
    assert data["research_only"] is True
    assert data["official_adoption_allowed"] is False
    assert data["broker_action_allowed"] is False
    assert data["protected_outputs_modified"] is False
    assert data["official_outputs_modified"] is False
    assert data["source_ranking_files_modified"] is False
    assert data["model_weights_changed"] is False
    assert data["trade_instructions_produced"] is False
    assert REPORT.is_file()
    assert MANIFEST.is_file()


def test_csvs_readable_and_isolated() -> None:
    data = payload()
    assert data["output_dir"].endswith("V21.111_R2_SECTOR_INDUSTRY_NEUTRAL_COUNTERFACTUAL_DIAGNOSTIC")
    csvs = sorted(OUT.glob("*.csv"))
    assert csvs
    for path in csvs:
        pd.read_csv(path)
    manifest = pd.read_csv(MANIFEST)
    assert not manifest.empty
    assert manifest["path"].astype(str).str.contains("V21.111_R2_SECTOR_INDUSTRY_NEUTRAL_COUNTERFACTUAL_DIAGNOSTIC").all()
    assert manifest["research_only"].astype(str).str.upper().isin(["TRUE", "1"]).all()


def test_raw_d_reconstructed_without_mutation() -> None:
    raw20 = pd.read_csv(OUT / "raw_d_top20.csv")
    raw50 = pd.read_csv(OUT / "raw_d_top50.csv")
    src20 = pd.read_csv(RAW20_SOURCE)
    src50 = pd.read_csv(RAW50_SOURCE)
    assert raw20["ticker"].tolist() == src20["ticker"].tolist()
    assert raw50["ticker"].tolist() == src50["ticker"].tolist()
    assert raw20["final_score"].round(10).tolist() == src20["final_score"].round(10).tolist()
    assert raw50["final_score"].round(10).tolist() == src50["final_score"].round(10).tolist()


def test_counterfactuals_are_diagnostic_only() -> None:
    for name in [
        "d_sector_neutral_percentile_ranking.csv",
        "d_sector_quota_counterfactual_top20.csv",
        "d_sector_quota_counterfactual_top50.csv",
        "d_industry_neutral_percentile_ranking.csv",
        "d_industry_quota_counterfactual_top20.csv",
        "d_industry_quota_counterfactual_top50.csv",
    ]:
        frame = pd.read_csv(OUT / name)
        assert frame["diagnostic_only"].astype(str).str.upper().isin(["TRUE", "1"]).all()
        assert frame["official_adoption_allowed"].astype(str).str.upper().isin(["FALSE", "0"]).all()
        assert frame["broker_action_allowed"].astype(str).str.upper().isin(["FALSE", "0"]).all()


def test_partial_when_required_columns_missing_and_raw_tech_preserved() -> None:
    data = payload()
    if not data["required_columns_available"]:
        assert data["final_status"] == "PARTIAL_PASS"
        assert data["decision"] == "D_NEUTRAL_COUNTERFACTUAL_PARTIAL_MISSING_REQUIRED_COLUMNS"
    assert float(data["raw_d_top20_tech_weight"]) == 0.90


if __name__ == "__main__":
    test_required_outputs_and_controls()
    test_csvs_readable_and_isolated()
    test_raw_d_reconstructed_without_mutation()
    test_counterfactuals_are_diagnostic_only()
    test_partial_when_required_columns_missing_and_raw_tech_preserved()
    print("PASS test_v21_111_r2_sector_industry_neutral_counterfactual_diagnostic")
