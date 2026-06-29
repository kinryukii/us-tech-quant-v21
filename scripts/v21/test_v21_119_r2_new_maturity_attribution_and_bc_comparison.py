from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_119_r2_new_maturity_attribution_and_bc_comparison.py"
OUT = ROOT / "outputs/v21/V21.119_R2_NEW_MATURITY_ATTRIBUTION_AND_BC_COMPARISON"


def test_v21_119_r2_new_maturity_attribution_outputs() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr

    manifest_path = OUT / "V21.119_R2_manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["protected_outputs_modified"] is False
    assert manifest["official_adoption_allowed"] is False
    assert manifest["broker_action_allowed"] is False
    assert manifest["research_only"] is True
    assert manifest["no_parameter_optimization_performed"] is True
    assert manifest["new_variant_generated"] is False
    assert manifest["D_R2C_frozen_variant_only"] is True
    assert manifest["latest_price_date_used"] >= "2026-06-26"
    assert manifest["newly_matured_observation_count_analyzed"] == 30

    for name in [
        "d_r2c_vs_original_d_new_maturity_attribution.csv",
        "d_r2c_vs_a1_b_c_new_maturity_attribution.csv",
        "d_r2c_soxx_alpha_attribution.csv",
        "d_r2c_repeated_loser_new_maturity_update.csv",
        "bc_superiority_audit.csv",
        "new_maturity_concentration_diagnostics.csv",
        "V21.119_R2_new_maturity_attribution_report.txt",
    ]:
        assert (OUT / name).is_file(), name

    original = pd.read_csv(OUT / "d_r2c_vs_original_d_new_maturity_attribution.csv")
    assert not original.empty
    assert {"D_R2C_only_tickers", "original_D_only_tickers", "contribution_from_D_R2C_only_tickers", "contribution_avoided_by_removing_original_D_only_tickers"}.issubset(original.columns)
    assert set(original["top_n"]).issubset({20, 50})

    bc = pd.read_csv(OUT / "bc_superiority_audit.csv")
    assert "evidence_favors" in bc.columns
    assert "B_or_C_remains_better_than_D_R2C" in bc.columns

    soxx = pd.read_csv(OUT / "d_r2c_soxx_alpha_attribution.csv")
    assert {"D_R2C_minus_SOXX", "top_contributor_abs_share", "alpha_driver"}.issubset(soxx.columns)

    repeated = pd.read_csv(OUT / "d_r2c_repeated_loser_new_maturity_update.csv")
    assert "repeated_losers_still_present_in_D_R2C" in repeated.columns
    assert "repeated_loser_reduction_meaningful" in repeated.columns

    report = (OUT / "V21.119_R2_new_maturity_attribution_report.txt").read_text(encoding="utf-8")
    assert "source V21.119_R1 status=" in report
    assert "official_adoption_allowed=false" in report
