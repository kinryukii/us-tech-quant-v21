#!/usr/bin/env python
from pathlib import Path
import importlib.util
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
P = ROOT / "scripts/v21/v21_077_sector_aware_risk_budget_backtest.py"
S = importlib.util.spec_from_file_location("m", P)
M = importlib.util.module_from_spec(S)
S.loader.exec_module(M)

if __name__ == "__main__":
    out = ROOT / M.OUT_REL
    required = [
        M.POLICY_NAME, M.HOLDINGS_NAME, M.SUMMARY_NAME, M.CONC_NAME,
        M.THEME_NAME, M.COMPARISON_NAME, M.READINESS_NAME,
    ]
    if not all((out / name).is_file() for name in required):
        result = M.run_stage(ROOT)
    else:
        result = pd.read_csv(out / M.READINESS_NAME).iloc[0].to_dict()
    for name in required:
        assert (out / name).is_file(), name
    policies = pd.read_csv(out / M.POLICY_NAME)
    summary = pd.read_csv(out / M.SUMMARY_NAME)
    comparison = pd.read_csv(out / M.COMPARISON_NAME)
    assert policies["policy_id"].nunique() == 14
    assert int(result["policies_tested"]) == 14
    assert not policies["hard_theme_cap_used"].astype(str).str.upper().eq("TRUE").any()
    assert summary["weight_sum_valid"].astype(str).str.upper().eq("TRUE").all()
    assert summary["max_ticker_concentration"].max() <= 0.10000001
    assert int(result["leakage_warnings"]) == 0
    assert str(result["protected_outputs_modified"]).upper() == "FALSE"
    assert str(result["official_outputs_mutated"]).upper() == "FALSE"
    assert str(result["official_adoption_allowed"]).upper() == "FALSE"
    assert str(result["forward_portfolio_append_allowed"]).upper() == "FALSE"
    assert {"TOP20", "TOP50"} <= set(comparison["top_n"])
    print("PASS test_v21_077_sector_aware_risk_budget_backtest")
