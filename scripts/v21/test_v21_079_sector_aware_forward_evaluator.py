#!/usr/bin/env python
from pathlib import Path
import importlib.util
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
P = ROOT / "scripts/v21/v21_079_sector_aware_forward_evaluator.py"
S = importlib.util.spec_from_file_location("m", P)
M = importlib.util.module_from_spec(S)
S.loader.exec_module(M)

if __name__ == "__main__":
    result = M.run_stage(ROOT)
    out = ROOT / M.OUT_REL
    for name in (M.TRACKED_NAME, M.MATURITY_SUMMARY_NAME, M.EVAL_SUMMARY_NAME, M.COMPARISON_NAME, M.READINESS_NAME):
        assert (out / name).is_file(), name
    tracked = pd.read_csv(out / M.TRACKED_NAME)
    summary = pd.read_csv(out / M.MATURITY_SUMMARY_NAME).iloc[0]
    assert len(tracked) == int(result["ledger_rows"])
    assert int(summary["ledger_rows"]) == int(result["ledger_rows"])
    assert set(tracked["maturity_status"]).issubset({"pending", "matured", "matured_price_missing"})
    assert int(result["leakage_warnings"]) == 0
    assert str(result["protected_outputs_modified"]).upper() == "FALSE"
    assert str(result["official_outputs_mutated"]).upper() == "FALSE"
    assert str(result["official_adoption_allowed"]).upper() == "FALSE"
    print("PASS test_v21_079_sector_aware_forward_evaluator")
