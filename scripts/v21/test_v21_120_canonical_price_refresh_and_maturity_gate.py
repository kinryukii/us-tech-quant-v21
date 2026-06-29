from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_120_canonical_price_refresh_and_maturity_gate.py"
OUT = ROOT / "outputs/v21/V21.120_CANONICAL_PRICE_REFRESH_AND_MATURITY_GATE"


def test_v21_120_canonical_price_refresh_and_maturity_gate_outputs() -> None:
    env = os.environ.copy()
    env.pop("V21_120_ALLOW_CANONICAL_PRICE_REFRESH", None)
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr

    manifest = json.loads((OUT / "V21.120_manifest.json").read_text(encoding="utf-8"))
    assert manifest["official_adoption_allowed"] is False
    assert manifest["broker_action_allowed"] is False
    assert manifest["research_only"] is True
    assert manifest["refresh_attempted"] is False
    assert manifest["protected_outputs_modified"] is False
    assert manifest["model_parameters_changed"] is False
    assert manifest["strategy_rankings_changed"] is False

    for name in [
        "price_panel_audit_before_refresh.csv",
        "price_panel_audit_after_refresh.csv",
        "price_refresh_log.txt",
        "maturity_gate_by_ranking_date_horizon.csv",
        "maturity_gate_summary.csv",
        "V21.120_price_refresh_and_maturity_gate_report.txt",
    ]:
        assert (OUT / name).is_file(), name

    before = pd.read_csv(OUT / "price_panel_audit_before_refresh.csv")
    assert "stale_or_missing_ticker_count" in before.columns
    assert "QQQ_available" in before.columns
    assert "SOXX_available" in before.columns

    gate = pd.read_csv(OUT / "maturity_gate_by_ranking_date_horizon.csv")
    assert {"newly_matured_vs_v21_119", "was_matured_in_v21_119", "currently_matured"}.issubset(gate.columns)
    summary = pd.read_csv(OUT / "maturity_gate_summary.csv")
    assert "rerun_V21_119_R1_recommended" in summary.columns
