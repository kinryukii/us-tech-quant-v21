#!/usr/bin/env python
from __future__ import annotations
import importlib.util
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_073_r3_causal_exit_simulator.py"
SPEC = importlib.util.spec_from_file_location("r3", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC); assert SPEC.loader; SPEC.loader.exec_module(MODULE)
if __name__ == "__main__":
    result = MODULE.run_stage(ROOT)
    trades = pd.read_csv(ROOT / MODULE.OUT_REL / MODULE.TRADE_NAME)
    assert bool(result["pass_gate"])
    assert trades["exit_policy_name"].nunique() == 3
    assert set(trades["forward_window"]) == {"5D", "10D", "20D"}
    assert not trades["option_price_path_available"].any()
    print("PASS test_v21_073_r3_causal_exit_simulator")
