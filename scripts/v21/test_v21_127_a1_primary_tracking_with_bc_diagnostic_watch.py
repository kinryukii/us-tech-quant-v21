from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_127_a1_primary_tracking_with_bc_diagnostic_watch.py"
OUT = ROOT / "outputs/v21/V21.127_A1_PRIMARY_TRACKING_WITH_BC_DIAGNOSTIC_WATCH"


def test_v21_127_a1_primary_tracking_outputs() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((OUT / "V21.127_manifest.json").read_text(encoding="utf-8"))
    assert manifest["protected_outputs_modified"] is False
    assert manifest["official_adoption_allowed"] is False
    assert manifest["broker_action_allowed"] is False
    assert manifest["research_only"] is True
    assert manifest["model_parameters_changed"] is False
    assert manifest["rankings_recomputed"] is False
    assert manifest["official_new_strategy_variants_created"] is False
    assert manifest["diagnostic_subsets_only"] is True

    for name in [
        "hierarchy_audit.csv",
        "forward_tracking_summary.csv",
        "a1_leadership_check.csv",
        "b_diagnostic_watch.csv",
        "c_secondary_watch.csv",
        "d_and_d_r2c_freeze_monitor.csv",
        "next_action_gate.csv",
        "V21.127_A1_primary_tracking_report.txt",
    ]:
        assert (OUT / name).is_file(), name

    hierarchy = pd.read_csv(OUT / "hierarchy_audit.csv").iloc[0]
    assert "PRIMARY_CONTROL" in hierarchy["A1_status"]
    assert "NOT_SUPPORTED" in hierarchy["B_status"]
    assert "DIAGNOSTIC_ONLY" in hierarchy["B_clean_status"]
    assert "SECONDARY" in hierarchy["C_status"]
    assert "DOWNGRADED" in hierarchy["D_original_status"]
    assert "FROZEN" in hierarchy["D_R2C_status"]

    tracking = pd.read_csv(OUT / "forward_tracking_summary.csv")
    assert set(tracking["strategy"]) == {
        "A1_BASELINE_CONTROL",
        "B_STATIC_MOMENTUM_BLEND",
        "B_CLEAN_EX_REPEATED_LOSERS",
        "C_DYNAMIC_MOMENTUM_BLEND",
        "D_WEIGHT_OPTIMIZED_R1",
        "D_R2C_BC_CONFIRMATION_OVERLAY",
    }
    b_watch = pd.read_csv(OUT / "b_diagnostic_watch.csv").iloc[0]
    assert b_watch["B_repeated_loser_risk_level"] == "HIGH"
    assert bool(b_watch["diagnostic_only"]) is True
    assert bool(b_watch["official_variant"]) is False

    gate = pd.read_csv(OUT / "next_action_gate.csv")
    assert "next_action_gate" in gate.columns
    report = (OUT / "V21.127_A1_primary_tracking_report.txt").read_text(encoding="utf-8")
    assert "official_adoption_allowed=false" in report
    assert "broker_action_allowed=false" in report
