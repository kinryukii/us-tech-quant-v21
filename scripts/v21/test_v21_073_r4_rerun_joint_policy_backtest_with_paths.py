#!/usr/bin/env python
from __future__ import annotations
import importlib.util
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_073_r4_rerun_joint_policy_backtest_with_paths.py"
SPEC = importlib.util.spec_from_file_location("r4", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC); assert SPEC.loader; SPEC.loader.exec_module(MODULE)
if __name__ == "__main__":
    result = MODULE.run_stage(ROOT)
    out = ROOT / MODULE.OUT_REL
    metrics = pd.read_csv(out / MODULE.METRICS_NAME)
    recs = pd.read_csv(out / MODULE.RECOMMENDATION_NAME)
    assert bool(result["pass_gate"])
    assert result["leakage_warnings"] == 0
    assert {"TRAIN", "VALIDATION", "TEST"}.issubset(set(metrics["split"]))
    assert {"5D", "10D", "20D"}.issubset(set(metrics["window"]))
    assert not recs["official_adoption_allowed"].any()
    assert not recs["forward_trade_signal_ledger_append_allowed"].any()
    assert result["protected_outputs_modified"] is False
    assert result["official_outputs_mutated"] is False
    print("PASS test_v21_073_r4_rerun_joint_policy_backtest_with_paths")
