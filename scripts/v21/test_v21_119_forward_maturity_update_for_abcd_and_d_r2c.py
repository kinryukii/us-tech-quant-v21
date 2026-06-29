from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_119_forward_maturity_update_for_abcd_and_d_r2c.py"
OUT = ROOT / "outputs/v21/V21.119_FORWARD_MATURITY_UPDATE_FOR_ABCD_AND_D_R2C"


def test_v21_119_forward_maturity_update_outputs() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((OUT / "V21.119_manifest.json").read_text(encoding="utf-8"))
    assert manifest["protected_outputs_modified"] is False
    assert manifest["official_adoption_allowed"] is False
    assert manifest["D_R2C_official_adoption_allowed"] is False
    assert manifest["broker_action_allowed"] is False
    assert manifest["research_only"] is True
    assert manifest["no_parameter_optimization_performed"] is True
    assert manifest["new_variant_generated"] is False

    for name in [
        "forward_maturity_by_date_horizon.csv",
        "pairwise_winrate_all_matured.csv",
        "pairwise_winrate_new_maturity_only.csv",
        "d_r2c_robustness_update.csv",
        "d_r2c_overfit_guard_update.csv",
        "repeated_loser_maturity_update.csv",
        "bc_vs_d_r2c_comparison.csv",
        "benchmark_sanity_update.csv",
        "V21.119_forward_maturity_update_report.txt",
    ]:
        assert (OUT / name).is_file(), name

    panel = pd.read_csv(OUT / "forward_maturity_by_date_horizon.csv")
    assert {"OLD_DESIGN_WINDOW", "UNMATURED"}.issubset(set(panel["maturity_partition"]))
    assert panel[panel["matured"].astype(str).str.upper().eq("FALSE")].shape[0] > 0
    matured = panel[panel["matured"].astype(str).str.upper().eq("TRUE")]
    assert not ((matured["missing_price_count"] > 0) & (matured["equal_weight_return"].fillna(0).eq(0))).all()
    pairs = pd.read_csv(OUT / "pairwise_winrate_all_matured.csv")
    required = {
        "D_R2C_BC_CONFIRMATION_OVERLAY_vs_D_WEIGHT_OPTIMIZED_R1",
        "D_R2C_BC_CONFIRMATION_OVERLAY_vs_A1_BASELINE_CONTROL",
        "D_R2C_BC_CONFIRMATION_OVERLAY_vs_B_STATIC_MOMENTUM_BLEND",
        "D_R2C_BC_CONFIRMATION_OVERLAY_vs_C_DYNAMIC_MOMENTUM_BLEND",
        "D_R2C_BC_CONFIRMATION_OVERLAY_vs_QQQ",
        "D_R2C_BC_CONFIRMATION_OVERLAY_vs_SOXX",
    }
    assert required.issubset(set(pairs["comparison"]))
