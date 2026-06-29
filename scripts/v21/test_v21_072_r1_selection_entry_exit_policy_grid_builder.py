#!/usr/bin/env python
from __future__ import annotations
import importlib.util
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_072_r1_selection_entry_exit_policy_grid_builder.py"
SPEC = importlib.util.spec_from_file_location("r1", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)

if __name__ == "__main__":
    result = MODULE.run_stage(ROOT)
    out = ROOT / MODULE.OUT_REL
    grid = pd.read_csv(out / MODULE.GRID_NAME)
    assert result["pass_gate"] is True
    assert len(grid) == result["total_policy_combinations"]
    assert grid["selection_policy_id"].nunique() == result["selection_policy_count"]
    assert grid["entry_policy_id"].nunique() == 3
    assert grid["exit_policy_id"].nunique() == 3
    assert not grid["official_adoption_allowed"].any()
    assert not grid["forward_trade_signal_ledger_append_allowed"].any()
    print("PASS test_v21_072_r1_selection_entry_exit_policy_grid_builder")
