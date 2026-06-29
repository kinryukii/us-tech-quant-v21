#!/usr/bin/env python
from __future__ import annotations
import importlib.util
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_072_r2_joint_policy_backtest.py"
SPEC = importlib.util.spec_from_file_location("r2", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)

if __name__ == "__main__":
    result = MODULE.run_stage(ROOT)
    out = ROOT / MODULE.OUT_REL
    metrics = pd.read_csv(out / MODULE.OBS_NAME)
    recs = pd.read_csv(out / MODULE.RECOMMENDATION_NAME)
    assert result["pass_gate"] is True
    assert result["final_status"] in {
        "PASS_V21_072_R2_JOINT_POLICY_BACKTEST_READY",
        "PARTIAL_PASS_V21_072_R2_JOINT_POLICY_READY_WITH_SAMPLE_OR_RISK_WARN",
    }
    assert {"TRAIN", "VALIDATION", "TEST"}.issubset(set(metrics["split"]))
    assert {"TOP20", "TOP50"}.issubset(set(metrics["top_n"]))
    assert {"5D", "10D", "20D"}.issubset(set(metrics["window"]))
    assert not recs["official_adoption_allowed"].any()
    assert not recs["forward_trade_signal_ledger_append_allowed"].any()
    assert result["protected_outputs_modified"] is False
    assert result["forward_ledger_mutation"] is False
    assert result["official_outputs_mutated"] is False
    print("PASS test_v21_072_r2_joint_policy_backtest")
