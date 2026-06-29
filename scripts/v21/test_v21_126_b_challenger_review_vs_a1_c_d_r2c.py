from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_126_b_challenger_review_vs_a1_c_d_r2c.py"
OUT = ROOT / "outputs/v21/V21.126_B_CHALLENGER_REVIEW_VS_A1_C_D_R2C"


def test_v21_126_b_challenger_review_outputs() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((OUT / "V21.126_manifest.json").read_text(encoding="utf-8"))
    assert manifest["protected_outputs_modified"] is False
    assert manifest["official_adoption_allowed"] is False
    assert manifest["broker_action_allowed"] is False
    assert manifest["research_only"] is True
    assert manifest["model_parameters_changed"] is False
    assert manifest["rankings_recomputed"] is False
    assert manifest["new_strategy_variants_created"] is False
    assert manifest["v21_125_read_as_frozen_evidence"] is True

    for name in [
        "b_leadership_confirmation.csv",
        "b_consistency_by_horizon.csv",
        "b_top20_top50_stability.csv",
        "b_concentration_overfit_audit.csv",
        "b_repeated_loser_audit.csv",
        "b_vs_a1_role_review.csv",
        "current_b_top20_top50_with_cross_confirmation.csv",
        "V21.126_B_challenger_review_report.txt",
    ]:
        assert (OUT / name).is_file(), name

    leadership = pd.read_csv(OUT / "b_leadership_confirmation.csv")
    assert not leadership.empty
    assert set([20, 50]).issubset(set(leadership["topN"]))
    assert "win_rate_vs_QQQ" in leadership.columns

    horizon = pd.read_csv(OUT / "b_consistency_by_horizon.csv")
    assert not horizon.empty
    assert "B_win_rate_vs_QQQ" in horizon.columns

    concentration = pd.read_csv(OUT / "b_concentration_overfit_audit.csv")
    assert "B_concentration_warning" in concentration.columns
    assert "B_overfit_warning" in concentration.columns

    current = pd.read_csv(OUT / "current_b_top20_top50_with_cross_confirmation.csv")
    assert len(current) == 50
    assert current["not_trade_list"].astype(str).str.upper().eq("TRUE").all()

    report = (OUT / "V21.126_B_challenger_review_report.txt").read_text(encoding="utf-8")
    assert "official_adoption_allowed=false" in report
    assert "broker_action_allowed=false" in report
