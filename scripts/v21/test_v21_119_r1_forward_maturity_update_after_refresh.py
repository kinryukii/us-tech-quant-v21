from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_119_r1_forward_maturity_update_after_refresh.py"
OUT = ROOT / "outputs/v21/V21.119_R1_FORWARD_MATURITY_UPDATE_AFTER_REFRESH"


def test_v21_119_r1_forward_maturity_after_refresh_outputs() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr

    manifest_path = OUT / "V21.119_R1_manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["protected_outputs_modified"] is False
    assert manifest["official_adoption_allowed"] is False
    assert manifest["D_R2C_official_adoption_allowed"] is False
    assert manifest["broker_action_allowed"] is False
    assert manifest["research_only"] is True
    assert manifest["no_parameter_optimization_performed"] is True
    assert manifest["new_variant_generated"] is False
    assert manifest["D_R2C_frozen_variant_only"] is True
    assert manifest["latest_price_date_used"] >= "2026-06-26"
    assert manifest["source_v21_120_latest_price_date_after_refresh"] >= "2026-06-26"

    for name in [
        "forward_maturity_by_date_horizon_after_refresh.csv",
        "pairwise_winrate_all_matured_after_refresh.csv",
        "pairwise_winrate_new_maturity_only_after_refresh.csv",
        "d_r2c_new_maturity_robustness.csv",
        "d_r2c_overfit_guard_after_refresh.csv",
        "repeated_loser_after_refresh_update.csv",
        "bc_vs_d_r2c_after_refresh_comparison.csv",
        "benchmark_sanity_after_refresh.csv",
        "V21.119_R1_forward_maturity_after_refresh_report.txt",
    ]:
        assert (OUT / name).is_file(), name

    panel = pd.read_csv(OUT / "forward_maturity_by_date_horizon_after_refresh.csv")
    assert {
        "OLD_OR_DESIGN_WINDOW",
        "NEWLY_MATURED_AFTER_V21_120_REFRESH",
        "STILL_UNMATURED",
    }.issubset(set(panel["observation_bucket"]))
    assert panel[panel["observation_bucket"].eq("NEWLY_MATURED_AFTER_V21_120_REFRESH")].shape[0] == 30
    assert panel[panel["matured"].astype(str).str.upper().eq("FALSE")].shape[0] > 0

    unmatured = panel[panel["observation_bucket"].eq("STILL_UNMATURED")]
    assert unmatured["matured"].astype(str).str.upper().eq("FALSE").all()
    assert unmatured["end_date"].fillna("").eq("").all()

    matured = panel[panel["matured"].astype(str).str.upper().eq("TRUE")]
    assert not ((matured["missing_price_count"] > 0) & (matured["equal_weight_return"].fillna(0).eq(0))).all()

    pairs_all = pd.read_csv(OUT / "pairwise_winrate_all_matured_after_refresh.csv")
    pairs_new = pd.read_csv(OUT / "pairwise_winrate_new_maturity_only_after_refresh.csv")
    required = {
        "D_R2C_BC_CONFIRMATION_OVERLAY_vs_D_WEIGHT_OPTIMIZED_R1",
        "D_R2C_BC_CONFIRMATION_OVERLAY_vs_A1_BASELINE_CONTROL",
        "D_R2C_BC_CONFIRMATION_OVERLAY_vs_B_STATIC_MOMENTUM_BLEND",
        "D_R2C_BC_CONFIRMATION_OVERLAY_vs_C_DYNAMIC_MOMENTUM_BLEND",
        "D_R2C_BC_CONFIRMATION_OVERLAY_vs_QQQ",
        "D_R2C_BC_CONFIRMATION_OVERLAY_vs_SOXX",
        "D_WEIGHT_OPTIMIZED_R1_vs_A1_BASELINE_CONTROL",
        "D_WEIGHT_OPTIMIZED_R1_vs_B_STATIC_MOMENTUM_BLEND",
        "D_WEIGHT_OPTIMIZED_R1_vs_C_DYNAMIC_MOMENTUM_BLEND",
        "B_STATIC_MOMENTUM_BLEND_vs_C_DYNAMIC_MOMENTUM_BLEND",
    }
    assert required.issubset(set(pairs_all["comparison"]))
    assert required.issubset(set(pairs_new["comparison"]))

    bench = pd.read_csv(OUT / "benchmark_sanity_after_refresh.csv")
    assert {"D_R2C_vs_QQQ_Top20_average_excess_newly_matured_only", "D_R2C_vs_SOXX_Top20_average_excess_newly_matured_only"}.issubset(bench.columns)

    report = (OUT / "V21.119_R1_forward_maturity_after_refresh_report.txt").read_text(encoding="utf-8")
    assert "overfit status=" in report
    assert "D_R2C official adoption allowed=false" in report
