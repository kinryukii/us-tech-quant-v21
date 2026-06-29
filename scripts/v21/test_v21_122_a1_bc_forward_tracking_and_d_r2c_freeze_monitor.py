from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_122_a1_bc_forward_tracking_and_d_r2c_freeze_monitor.py"
OUT = ROOT / "outputs/v21/V21.122_A1_BC_FORWARD_TRACKING_AND_D_R2C_FREEZE_MONITOR"


def test_v21_122_a1_bc_forward_tracking_outputs() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr

    manifest_path = OUT / "V21.122_manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["protected_outputs_modified"] is False
    assert manifest["official_adoption_allowed"] is False
    assert manifest["broker_action_allowed"] is False
    assert manifest["research_only"] is True
    assert manifest["no_parameter_optimization_performed"] is True
    assert manifest["new_variant_generated"] is False
    assert manifest["historical_rankings_recomputed"] is False
    assert manifest["candidate_hierarchy_loaded"] is True
    assert manifest["D_R2C_frozen_tracking_only"] is True
    assert manifest["original_D_downgraded_reference_only"] is True

    for name in [
        "candidate_hierarchy_audit.csv",
        "forward_tracking_by_date_horizon.csv",
        "a1_leadership_monitor.csv",
        "bc_challenge_monitor.csv",
        "d_r2c_freeze_monitor.csv",
        "candidate_role_drift.csv",
        "benchmark_sanity_tracking.csv",
        "V21.122_forward_tracking_report.txt",
    ]:
        assert (OUT / name).is_file(), name

    panel = pd.read_csv(OUT / "forward_tracking_by_date_horizon.csv")
    assert set(panel["strategy"]) == {
        "A1_BASELINE_CONTROL",
        "B_STATIC_MOMENTUM_BLEND",
        "C_DYNAMIC_MOMENTUM_BLEND",
        "D_WEIGHT_OPTIMIZED_R1",
        "D_R2C_BC_CONFIRMATION_OVERLAY",
    }
    assert {"OLD_OR_PRIOR_MATURED", "STILL_UNMATURED"}.issubset(set(panel["observation_bucket"]))
    matured = panel[panel["matured"].astype(str).str.upper().eq("TRUE")]
    assert not ((matured["missing_price_count"] > 0) & (matured["equal_weight_return"].fillna(0).eq(0))).all()

    hierarchy = pd.read_csv(OUT / "candidate_hierarchy_audit.csv").iloc[0]
    assert hierarchy["primary_control"] == "A1_BASELINE_CONTROL"
    assert "D_R2C_BC_CONFIRMATION_OVERLAY" in hierarchy["secondary_research_candidates"]

    d2c = pd.read_csv(OUT / "d_r2c_freeze_monitor.csv").iloc[0]
    assert bool(d2c["D_R2C_frozen_secondary_tracking_only"]) is True
    assert bool(d2c["D_R2C_tuned_or_modified"]) is False
    assert "DOWNGRADED" in d2c["D_original_status"]

    drift = pd.read_csv(OUT / "candidate_role_drift.csv")
    assert "role_drift_flag" in drift.columns
    bench = pd.read_csv(OUT / "benchmark_sanity_tracking.csv")
    assert set(bench["strategy"]) == set(panel["strategy"])

    report = (OUT / "V21.122_forward_tracking_report.txt").read_text(encoding="utf-8")
    assert "official_adoption_allowed=false" in report
    assert "broker_action_allowed=false" in report
