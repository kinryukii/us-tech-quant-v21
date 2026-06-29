#!/usr/bin/env python
from pathlib import Path
import importlib.util
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
P = ROOT / "scripts/v21/v21_081_soft_execution_policy_backtest.py"
S = importlib.util.spec_from_file_location("m", P)
M = importlib.util.module_from_spec(S)
S.loader.exec_module(M)

if __name__ == "__main__":
    result = M.run_stage(ROOT)
    out = ROOT / M.OUT_REL
    for name in (M.POLICY_NAME, M.SUMMARY_NAME, M.SIM_NAME, M.LABEL_NAME, M.MISSED_NAME, M.COMPARISON_NAME, M.READINESS_NAME):
        assert (out / name).is_file(), name
    summary = pd.read_csv(out / M.SUMMARY_NAME)
    comparison = pd.read_csv(out / M.COMPARISON_NAME)
    assert not summary.empty
    assert not comparison.empty
    assert "D_EXECUTION_PRIORITY_COMBINED_TOP20_R1" in set(summary["policy_id"])
    assert "D_EW_TOP20_R1" in set(summary["policy_id"])
    assert int(result["leakage_warnings"]) == 0
    assert str(result["protected_outputs_modified"]).upper() == "FALSE"
    assert str(result["official_outputs_mutated"]).upper() == "FALSE"
    assert str(result["official_adoption_allowed"]).upper() == "FALSE"
    print("PASS test_v21_081_soft_execution_policy_backtest")
