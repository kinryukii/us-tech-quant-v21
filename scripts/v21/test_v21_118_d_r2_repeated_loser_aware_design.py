from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_118_d_r2_repeated_loser_aware_design.py"
OUT = ROOT / "outputs/v21/V21.118_D_R2_REPEATED_LOSER_AWARE_DESIGN"


def test_v21_118_d_r2_repeated_loser_aware_design_outputs() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((OUT / "V21.118_manifest.json").read_text(encoding="utf-8"))
    assert manifest["protected_outputs_modified"] is False
    assert manifest["official_adoption_allowed"] is False
    assert manifest["D_R2_official_adoption_allowed"] is False
    assert manifest["broker_action_allowed"] is False
    assert manifest["research_only"] is True

    for name in [
        "d_r2_adjusted_rankings.csv",
        "d_r2_top20_top50_membership.csv",
        "d_r2_penalty_attribution.csv",
        "d_r2_diff_vs_original_d.csv",
        "d_r2_forward_by_date_horizon.csv",
        "d_r2_pairwise_winrate.csv",
        "d_r2_repeated_loser_reduction.csv",
        "d_r2_top20_top50_impact.csv",
        "d_r2_turnover_stability.csv",
        "d_r2_benchmark_sanity.csv",
        "V21.118_D_R2_design_report.txt",
    ]:
        assert (OUT / name).is_file(), name

    penalties = pd.read_csv(OUT / "d_r2_penalty_attribution.csv")
    assert penalties["bounded_penalty_ok"].astype(str).str.upper().eq("TRUE").all()
    assert penalties["future_leakage_guard"].str.contains("before_ranking_date").all()

    membership = pd.read_csv(OUT / "d_r2_top20_top50_membership.csv")
    cooldown = membership[membership["candidate_variant"].eq("D_R2B_TOP20_COOLDOWN")]
    assert not cooldown.empty
    assert cooldown.groupby(["as_of_date"])["ticker"].count().min() == 50

    pair = pd.read_csv(OUT / "d_r2_pairwise_winrate.csv")
    assert pair["comparison"].str.contains("_vs_D_WEIGHT_OPTIMIZED_R1").any()
    assert pair["comparison"].str.contains("_vs_A1_BASELINE_CONTROL").any()
    sanity = pd.read_csv(OUT / "d_r2_benchmark_sanity.csv")
    assert not sanity.empty
