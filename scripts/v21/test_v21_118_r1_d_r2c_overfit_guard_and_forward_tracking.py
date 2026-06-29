from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_118_r1_d_r2c_overfit_guard_and_forward_tracking.py"
OUT = ROOT / "outputs/v21/V21.118_R1_D_R2C_OVERFIT_GUARD_AND_FORWARD_TRACKING"


def test_v21_118_r1_d_r2c_overfit_guard_outputs() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((OUT / "V21.118_R1_manifest.json").read_text(encoding="utf-8"))
    assert manifest["protected_outputs_modified"] is False
    assert manifest["official_adoption_allowed"] is False
    assert manifest["D_R2C_official_adoption_allowed"] is False
    assert manifest["broker_action_allowed"] is False
    assert manifest["research_only"] is True
    assert manifest["frozen_variant_name"] == "D_R2C_BC_CONFIRMATION_OVERLAY"
    assert manifest["no_parameter_optimization_performed"] is True
    assert manifest["new_variant_generated"] is False
    assert manifest["out_of_sample_observations_available"] is False
    assert manifest["overfit_warning"] is True

    for name in [
        "d_r2c_frozen_rule_audit.csv",
        "d_r2c_forward_tracking_by_date_horizon.csv",
        "d_r2c_vs_original_d_pairwise.csv",
        "d_r2c_vs_a1_b_c_pairwise.csv",
        "d_r2c_benchmark_sanity.csv",
        "d_r2c_overfit_diagnostics.csv",
        "d_r2c_repeated_loser_tracking.csv",
        "d_r2c_bc_dependency_audit.csv",
        "V21.118_R1_D_R2C_overfit_guard_report.txt",
    ]:
        assert (OUT / name).is_file(), name

    repeated = pd.read_csv(OUT / "d_r2c_repeated_loser_tracking.csv")
    assert "repeated_loser_reduction_meaningful" in repeated.columns
    bc = pd.read_csv(OUT / "d_r2c_bc_dependency_audit.csv")
    assert not bc.empty
    bench = pd.read_csv(OUT / "d_r2c_benchmark_sanity.csv")
    assert bench["comparison"].str.contains("QQQ|SOXX", regex=True).any()
