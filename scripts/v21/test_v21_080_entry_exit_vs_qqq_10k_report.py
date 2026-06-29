#!/usr/bin/env python
from pathlib import Path
import importlib.util
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
P = ROOT / "scripts/v21/v21_080_entry_exit_vs_qqq_10k_report.py"
S = importlib.util.spec_from_file_location("m", P)
M = importlib.util.module_from_spec(S)
S.loader.exec_module(M)

if __name__ == "__main__":
    result = M.run_stage(ROOT)
    out = ROOT / M.OUT_REL
    for name in (M.SUMMARY_NAME, M.SIM_NAME, M.READINESS_NAME):
        assert (out / name).is_file(), name
    summary = pd.read_csv(out / M.SUMMARY_NAME)
    sim = pd.read_csv(out / M.SIM_NAME)
    assert not summary.empty
    assert not sim.empty
    assert {"D_WEIGHT_OPTIMIZED_R1__EW_TOP20_R1", "D_WEIGHT_OPTIMIZED_R1__EW_TOP50_R1"}.issubset(set(summary["policy_id"]))
    assert "QQQ_BENCHMARK" in set(summary["policy_id"])
    assert sim["initial_capital"].eq(10000.0).all()
    assert not sim["annualization_used"].astype(str).str.upper().eq("TRUE").any()
    assert int(result["leakage_warnings"]) == 0
    assert str(result["protected_outputs_modified"]).upper() == "FALSE"
    assert str(result["official_outputs_mutated"]).upper() == "FALSE"
    assert str(result["official_adoption_allowed"]).upper() == "FALSE"
    print("PASS test_v21_080_entry_exit_vs_qqq_10k_report")
