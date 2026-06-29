from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_112_latest_data_abcd_rerun.py"
OUT = ROOT / "outputs/v21/V21.112_LATEST_DATA_ABCD_RERUN"

REQUIRED_FILES = [
    "latest_abcd_summary.json",
    "latest_abcd_report.txt",
    "A1_BASELINE_CONTROL_full_ranking.csv",
    "B_STATIC_MOMENTUM_BLEND_full_ranking.csv",
    "C_DYNAMIC_MOMENTUM_BLEND_full_ranking.csv",
    "D_WEIGHT_OPTIMIZED_R1_full_ranking.csv",
    "A1_BASELINE_CONTROL_top20.csv",
    "B_STATIC_MOMENTUM_BLEND_top20.csv",
    "C_DYNAMIC_MOMENTUM_BLEND_top20.csv",
    "D_WEIGHT_OPTIMIZED_R1_top20.csv",
    "A1_BASELINE_CONTROL_top50.csv",
    "B_STATIC_MOMENTUM_BLEND_top50.csv",
    "C_DYNAMIC_MOMENTUM_BLEND_top50.csv",
    "D_WEIGHT_OPTIMIZED_R1_top50.csv",
    "top20_overlap_matrix.csv",
    "top50_overlap_matrix.csv",
    "sector_industry_concentration.csv",
    "excluded_tickers.csv",
    "validation_manifest.json",
]


def test_v21_112_latest_data_abcd_rerun_outputs() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert OUT.is_dir()

    for name in REQUIRED_FILES:
        assert (OUT / name).is_file(), name

    for strategy in [
        "A1_BASELINE_CONTROL",
        "B_STATIC_MOMENTUM_BLEND",
        "C_DYNAMIC_MOMENTUM_BLEND",
        "D_WEIGHT_OPTIMIZED_R1",
    ]:
        full = pd.read_csv(OUT / f"{strategy}_full_ranking.csv")
        assert not full.empty
        assert (OUT / f"{strategy}_top20.csv").is_file()
        assert (OUT / f"{strategy}_top50.csv").is_file()

    summary = json.loads((OUT / "latest_abcd_summary.json").read_text(encoding="utf-8"))
    for key in [
        "FINAL_STATUS",
        "DECISION",
        "latest_price_date",
        "rows_per_strategy",
        "eligible_counts_per_strategy",
        "excluded_counts_per_strategy",
        "research_only",
        "official_adoption_allowed",
        "broker_action_allowed",
        "protected_outputs_modified",
        "top20_tickers_per_strategy",
    ]:
        assert key in summary
    assert summary["research_only"] is True
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["protected_outputs_modified"] is False
