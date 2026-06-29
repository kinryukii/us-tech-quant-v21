#!/usr/bin/env python
from pathlib import Path
import importlib.util

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/v21/v21_084_top20_execution_policy_backtest.py"
SPEC = importlib.util.spec_from_file_location("v21_084", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


if __name__ == "__main__":
    result = MODULE.run_stage(ROOT)
    out = ROOT / MODULE.OUT_REL
    for name in (
        MODULE.POLICY_NAME,
        MODULE.SUMMARY_NAME,
        MODULE.SIM_NAME,
        MODULE.LABEL_NAME,
        MODULE.MISSED_NAME,
        MODULE.COMPARISON_NAME,
        MODULE.READINESS_NAME,
    ):
        assert (out / name).is_file(), name

    policies = pd.read_csv(out / MODULE.POLICY_NAME)
    summary = pd.read_csv(out / MODULE.SUMMARY_NAME)
    sim = pd.read_csv(out / MODULE.SIM_NAME)
    comparison = pd.read_csv(out / MODULE.COMPARISON_NAME)
    readiness = pd.read_csv(out / MODULE.READINESS_NAME).iloc[0]

    required = {
        "D_TOP20_EW_BASELINE_R1",
        "D_TOP20_CORE_80_EXECUTION_20_R1",
        "D_TOP20_RISK_ONLY_EXIT_R1",
        "D_TOP20_CORE_80_RISK_EXIT_R1",
        "D_TOP20_LABEL_ONLY_DIAGNOSTIC_R1",
    }
    assert required.issubset(set(policies["policy_id"]))
    assert required.issubset(set(summary["policy_id"]))
    assert required.issubset(set(comparison["policy_id"]))
    assert len(sim) == len(summary)
    assert int(readiness["leakage_warnings"]) == 0
    assert str(readiness["d_top20_baseline_preserved"]).upper() == "TRUE"
    assert str(readiness["protected_outputs_modified"]).upper() == "FALSE"
    assert str(readiness["official_outputs_mutated"]).upper() == "FALSE"
    assert str(readiness["official_adoption_allowed"]).upper() == "FALSE"
    assert float(readiness["top20_10d_10000_d_ew_ending_value"]) > 10000
    print("PASS test_v21_084_top20_execution_policy_backtest")
