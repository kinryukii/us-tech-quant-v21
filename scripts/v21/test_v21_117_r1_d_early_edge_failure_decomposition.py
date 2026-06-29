from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_117_r1_d_early_edge_failure_decomposition.py"
OUT = ROOT / "outputs/v21/V21.117_R1_D_EARLY_EDGE_FAILURE_DECOMPOSITION"


def test_v21_117_r1_d_early_edge_failure_decomposition_outputs() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((OUT / "V21.117_R1_manifest.json").read_text(encoding="utf-8"))
    assert manifest["protected_outputs_modified"] is False
    assert manifest["official_adoption_allowed"] is False
    assert manifest["broker_action_allowed"] is False
    assert manifest["research_only"] is True
    assert manifest["source_v21_117_status"]

    for name in [
        "d_underperformance_by_date_horizon.csv",
        "d_top20_vs_top50_decomposition.csv",
        "d_repeated_loser_attribution.csv",
        "missed_winners_vs_d.csv",
        "d_vs_soxx_decomposition.csv",
        "d_ranking_churn.csv",
        "bc_rescue_analysis.csv",
        "V21.117_R1_failure_decomposition_report.txt",
    ]:
        assert (OUT / name).is_file(), name

    repeated = pd.read_csv(OUT / "d_repeated_loser_attribution.csv")
    assert not repeated.empty
    soxx = pd.read_csv(OUT / "d_vs_soxx_decomposition.csv")
    assert not soxx.empty
    assert "D_minus_SOXX" in soxx.columns
    if manifest["D_R2_design_allowed_now"]:
        assert manifest["primary_D_weakness_classification"] not in {"D_MIXED_INCONCLUSIVE", "D_SAMPLE_TOO_SMALL"}
