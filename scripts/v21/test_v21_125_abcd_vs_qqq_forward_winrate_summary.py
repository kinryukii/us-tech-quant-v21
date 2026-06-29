from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_125_abcd_vs_qqq_forward_winrate_summary.py"
OUT = ROOT / "outputs/v21/V21.125_ABCD_VS_QQQ_FORWARD_WINRATE_SUMMARY"


def test_v21_125_abcd_vs_qqq_forward_winrate_summary_outputs() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL_MATURED_SUMMARY" in result.stdout
    assert "CONCLUSION" in result.stdout

    manifest_path = OUT / "V21.125_manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["official_adoption_allowed"] is False
    assert manifest["broker_action_allowed"] is False
    assert manifest["research_only"] is True
    assert manifest["model_parameters_changed"] is False
    assert manifest["rankings_recomputed"] is False
    assert manifest["new_strategy_variants_created"] is False
    assert manifest["nasdaq_proxy"] == "QQQ"
    if manifest.get("leader_top20"):
        assert isinstance(manifest["leader_top20"]["topN"], int)
    if manifest.get("leader_top50"):
        assert isinstance(manifest["leader_top50"]["topN"], int)

    summary_path = OUT / "abcd_vs_qqq_winrate_summary_all_matured.csv"
    assert summary_path.is_file()
    summary = pd.read_csv(summary_path)
    assert not summary.empty
    assert "win_rate_vs_QQQ" in summary.columns

    for name in [
        "abcd_vs_qqq_winrate_by_horizon.csv",
        "abcd_vs_qqq_winrate_by_observation_bucket.csv",
        "abcd_vs_qqq_forward_detail.csv",
        "V21.125_abcd_vs_qqq_forward_winrate_report.txt",
    ]:
        assert (OUT / name).is_file(), name
