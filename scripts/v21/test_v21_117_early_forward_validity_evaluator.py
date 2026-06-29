from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_117_early_forward_validity_evaluator.py"
OUT = ROOT / "outputs/v21/V21.117_EARLY_FORWARD_VALIDITY_EVALUATOR"


def test_v21_117_early_forward_validity_evaluator_outputs() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((OUT / "V21.117_manifest.json").read_text(encoding="utf-8"))
    assert manifest["protected_outputs_modified"] is False
    assert manifest["official_adoption_allowed"] is False
    assert manifest["broker_action_allowed"] is False
    assert manifest["research_only"] is True
    assert (OUT / "V21.117_early_forward_validity_report.txt").is_file()

    by_date = pd.read_csv(OUT / "early_forward_by_date_horizon.csv")
    assert not by_date.empty
    assert by_date[by_date["horizon"].isin(["10D", "20D"])]["matured"].astype(str).str.upper().eq("FALSE").any()

    one_day = by_date[(by_date["as_of_date"].eq("2026-06-24")) & (by_date["horizon"].eq("1D"))]
    assert one_day["matured"].astype(str).str.upper().eq("TRUE").any()
    three_day = by_date[(by_date["as_of_date"].eq("2026-06-22")) & (by_date["horizon"].eq("3D"))]
    assert three_day["end_date"].astype(str).eq("2026-06-25").any()
    five_day = by_date[(by_date["as_of_date"].eq("2026-06-17")) & (by_date["horizon"].eq("5D"))]
    assert five_day["end_date"].astype(str).eq("2026-06-25").any()

    pairwise = pd.read_csv(OUT / "strategy_pairwise_winrate.csv")
    assert {"D_WEIGHT_OPTIMIZED_R1_vs_A1_BASELINE_CONTROL", "D_WEIGHT_OPTIMIZED_R1_vs_B_STATIC_MOMENTUM_BLEND", "D_WEIGHT_OPTIMIZED_R1_vs_C_DYNAMIC_MOMENTUM_BLEND"}.issubset(set(pairwise["pair"]))

    matured = by_date[by_date["matured"].astype(str).str.upper().eq("TRUE")]
    assert not ((matured["missing_price_count"] > 0) & (matured["equal_weight_return"].fillna(0).eq(0))).all()
