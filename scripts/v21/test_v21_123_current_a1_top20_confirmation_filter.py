from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_123_current_a1_top20_confirmation_filter.py"
OUT = ROOT / "outputs/v21/V21.123_CURRENT_A1_TOP20_CONFIRMATION_FILTER"


def test_v21_123_current_a1_top20_confirmation_filter_outputs() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr

    manifest_path = OUT / "V21.123_manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["protected_outputs_modified"] is False
    assert manifest["official_adoption_allowed"] is False
    assert manifest["broker_action_allowed"] is False
    assert manifest["research_only"] is True
    assert manifest["no_parameter_optimization_performed"] is True
    assert manifest["new_variant_generated"] is False
    assert manifest["rankings_recomputed"] is False
    assert manifest["current_rule_variant"] == "A1_BASELINE_CONTROL"
    assert manifest["D_R2C_used_as_frozen_tracking_evidence_only"] is True

    for name in [
        "current_a1_top20_confirmation_filter.csv",
        "current_a1_top20_bucket_summary.csv",
        "current_a1_top20_risk_annotations.csv",
        "current_a1_top20_cross_variant_overlap.csv",
        "V21.123_current_a1_top20_confirmation_filter_report.txt",
    ]:
        assert (OUT / name).is_file(), name

    filtered = pd.read_csv(OUT / "current_a1_top20_confirmation_filter.csv")
    assert len(filtered) == 20
    assert filtered["ranking_date"].nunique() == 1
    assert filtered["ranking_date"].iloc[0] == manifest["latest_ranking_date_used"]
    assert {"B_rank", "C_rank", "in_B_top20", "in_B_top30", "in_B_top50", "in_C_top20", "in_C_top30", "in_C_top50"}.issubset(filtered.columns)
    assert {"D_R2C_rank", "in_D_R2C_top20", "in_D_R2C_top50"}.issubset(filtered.columns)
    assert filtered["current_research_bucket"].notna().all()
    assert set(filtered["current_research_bucket"]).issubset({"HIGH_PRIORITY_CONFIRMED", "MEDIUM_PRIORITY_WATCH", "LOW_PRIORITY_A1_ONLY", "RISK_FLAGGED"})

    risk = pd.read_csv(OUT / "current_a1_top20_risk_annotations.csv")
    assert "repeated_loser_flag" in risk.columns
    assert "metadata_warning" in risk.columns

    summary = pd.read_csv(OUT / "current_a1_top20_bucket_summary.csv")
    assert int(summary[["HIGH_PRIORITY_CONFIRMED_count", "MEDIUM_PRIORITY_WATCH_count", "LOW_PRIORITY_A1_ONLY_count", "RISK_FLAGGED_count"]].sum(axis=1).iloc[0]) == 20

    report = (OUT / "V21.123_current_a1_top20_confirmation_filter_report.txt").read_text(encoding="utf-8")
    assert "official_adoption_allowed=false" in report
    assert "broker_action_allowed=false" in report
