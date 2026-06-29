from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_113_latest_data_abcd_rerun_20260625_price_refresh.py"
OUT = ROOT / "outputs/v21/V21.113_LATEST_DATA_ABCD_RERUN_20260625_PRICE_REFRESH"

REQUIRED_ALWAYS = [
    "latest_price_refresh_report.csv",
    "latest_price_panel_validation.json",
    "stale_or_missing_ticker_report.csv",
    "ABCD_rank_diff_vs_V21_108_R2.csv",
    "ABCD_rank_diff_vs_V21_112_R1.csv",
    "V21.113_latest_data_abcd_rerun_report.md",
    "V21.113_latest_data_abcd_rerun_summary.json",
]

REQUIRED_PASS = [
    "A1_BASELINE_CONTROL_latest_ranking.csv",
    "B_STATIC_MOMENTUM_BLEND_latest_ranking.csv",
    "C_DYNAMIC_MOMENTUM_BLEND_latest_ranking.csv",
    "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv",
    "ABCD_top20_summary.csv",
    "ABCD_top50_summary.csv",
    "ABCD_top20_overlap_matrix.csv",
    "ABCD_top50_overlap_matrix.csv",
]


def test_v21_113_script_contract_and_outputs() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert OUT.is_dir()

    for name in REQUIRED_ALWAYS:
        assert (OUT / name).is_file(), name

    summary = json.loads((OUT / "V21.113_latest_data_abcd_rerun_summary.json").read_text(encoding="utf-8"))
    validation = json.loads((OUT / "latest_price_panel_validation.json").read_text(encoding="utf-8"))

    assert summary["research_only"] is True
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["protected_outputs_modified"] is False
    assert validation["backup_created_before_refresh"] is True
    assert validation["refresh_attempted"] is True

    if summary["latest_price_date"] < "2026-06-25":
        assert summary["FINAL_STATUS"] == "BLOCKED_STALE_PRICE_PANEL"
        assert summary["DECISION"] == "DO_NOT_ARCHIVE_AS_TRUE_LATEST_DATA"
        return

    assert summary["DECISION"] == "LATEST_DATA_ABCD_RERUN_READY_RESEARCH_ONLY"
    for name in REQUIRED_PASS:
        assert (OUT / name).is_file(), name

    counts = summary["rows_per_strategy"]
    assert 300 <= counts["A1_BASELINE_CONTROL"]["rows"] <= 340
    for strategy in ["B_STATIC_MOMENTUM_BLEND", "C_DYNAMIC_MOMENTUM_BLEND", "D_WEIGHT_OPTIMIZED_R1"]:
        assert 300 <= counts[strategy]["eligible"] <= 340
    assert counts["D_WEIGHT_OPTIMIZED_R1"]["top20"] == 20
    assert counts["D_WEIGHT_OPTIMIZED_R1"]["top50"] == 50

    for matrix_name in ["ABCD_top20_overlap_matrix.csv", "ABCD_top50_overlap_matrix.csv"]:
        matrix = pd.read_csv(OUT / matrix_name)
        assert list(matrix["strategy"]) == ["A1", "B", "C", "D"]
        assert {"A1", "B", "C", "D"}.issubset(matrix.columns)

    for diff_name in ["ABCD_rank_diff_vs_V21_108_R2.csv", "ABCD_rank_diff_vs_V21_112_R1.csv"]:
        diff = pd.read_csv(OUT / diff_name)
        if not diff.empty and (diff["movement_type"] == "NO_MEANINGFUL_RANK_MOVEMENT").any():
            assert len(diff) == 1
