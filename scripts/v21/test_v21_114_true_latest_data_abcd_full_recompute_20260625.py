from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_114_true_latest_data_abcd_full_recompute_20260625.py"
OUT = ROOT / "outputs/v21/V21.114_TRUE_LATEST_DATA_ABCD_FULL_RECOMPUTE_20260625"
SUMMARY = OUT / "V21.114_true_latest_data_abcd_full_recompute_summary.json"
REPORT = OUT / "V21.114_true_latest_data_abcd_full_recompute_report.md"


def test_v21_114_true_latest_data_abcd_full_recompute_outputs() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert OUT.is_dir()
    assert SUMMARY.is_file()
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))

    assert summary["protected_outputs_modified"] is False
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["research_only"] is True
    assert summary["canonical_price_panel_latest_date"] >= "2026-06-25"

    required = [
        "recompute_input_manifest.csv",
        "technical_feature_recompute_latest.csv",
        "momentum_feature_recompute_latest.csv",
        "A1_BASELINE_CONTROL_true_latest_ranking.csv",
        "B_STATIC_MOMENTUM_BLEND_true_latest_ranking.csv",
        "C_DYNAMIC_MOMENTUM_BLEND_true_latest_ranking.csv",
        "D_WEIGHT_OPTIMIZED_R1_true_latest_ranking.csv",
        "ABCD_top20_summary.csv",
        "ABCD_top50_summary.csv",
        "ABCD_top20_overlap_matrix.csv",
        "ABCD_top50_overlap_matrix.csv",
        "D_entrants_removals_vs_V21_108_R2.csv",
        "D_entrants_removals_vs_V21_112_R1.csv",
        "D_entrants_removals_vs_V21_113.csv",
        "D_score_delta_vs_V21_113.csv",
        "stale_or_missing_ticker_report.csv",
        "stale_factor_cache_report.csv",
        "V21.114_true_latest_data_abcd_full_recompute_report.md",
    ]
    for name in required:
        assert (OUT / name).is_file(), name

    if summary["FINAL_STATUS"].startswith("PASS"):
        for field in [
            "technical_features_latest_date",
            "momentum_features_latest_date",
            "A1_ranking_latest_date",
            "B_ranking_latest_date",
            "C_ranking_latest_date",
            "D_ranking_latest_date",
        ]:
            assert summary[field] >= "2026-06-25", field
        assert summary["stale_factor_input_count"] == 0
        assert summary["read_v21_112_ranking_as_input"] is False
        assert summary["read_v21_113_ranking_as_input"] is False
        assert summary["copied_prior_ranking_files"] is False
        assert summary["full_recompute_confirmed"] is True
    else:
        text = REPORT.read_text(encoding="utf-8")
        assert "Blockers" in text
        assert "DO_NOT_ARCHIVE_AS_TRUE_LATEST_DATA" in text

    for name in [
        "D_entrants_removals_vs_V21_108_R2.csv",
        "D_entrants_removals_vs_V21_112_R1.csv",
        "D_entrants_removals_vs_V21_113.csv",
    ]:
        frame = pd.read_csv(OUT / name)
        if "change_type" in frame.columns and (frame["change_type"] == "NO_MEANINGFUL_RANK_MOVEMENT").any():
            assert len(frame) == 1
