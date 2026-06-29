#!/usr/bin/env python
from pathlib import Path
import importlib.util

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/v21/v21_083_soft_execution_forward_evaluator.py"
SPEC = importlib.util.spec_from_file_location("v21_083", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


if __name__ == "__main__":
    result = MODULE.run_stage(ROOT)
    out = ROOT / MODULE.OUT_REL
    for name in (
        MODULE.TRACKED_NAME,
        MODULE.MATURITY_SUMMARY_NAME,
        MODULE.EVAL_SUMMARY_NAME,
        MODULE.COMPARISON_NAME,
        MODULE.READINESS_NAME,
    ):
        assert (out / name).is_file(), name

    tracked = pd.read_csv(out / MODULE.TRACKED_NAME)
    maturity = pd.read_csv(out / MODULE.MATURITY_SUMMARY_NAME).iloc[0]
    readiness = pd.read_csv(out / MODULE.READINESS_NAME).iloc[0]

    assert len(tracked) == int(result["ledger_rows"])
    assert int(maturity["ledger_rows"]) == int(result["ledger_rows"])
    assert set(tracked["policy_id"].unique()) == {MODULE.BASELINE, MODULE.CANDIDATE}
    assert set(tracked["maturity_status"]).issubset({"pending", "matured", "matured_price_missing"})
    assert {"observation_id", "rank", "score", "entry_label", "weighted_realized_return"}.issubset(tracked.columns)
    assert int(readiness["leakage_warnings"]) == 0
    assert str(readiness["protected_outputs_modified"]).upper() == "FALSE"
    assert str(readiness["official_outputs_mutated"]).upper() == "FALSE"
    assert str(readiness["official_adoption_allowed"]).upper() == "FALSE"
    assert str(readiness["v21_082_ledger_consumed"]).upper() == "TRUE"
    print("PASS test_v21_083_soft_execution_forward_evaluator")
