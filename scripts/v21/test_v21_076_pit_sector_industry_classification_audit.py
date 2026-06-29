#!/usr/bin/env python
from pathlib import Path
import importlib.util
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
P = ROOT / "scripts/v21/v21_076_pit_sector_industry_classification_audit.py"
S = importlib.util.spec_from_file_location("m", P)
M = importlib.util.module_from_spec(S)
S.loader.exec_module(M)

if __name__ == "__main__":
    out = ROOT / M.OUT_REL
    result = (
        pd.read_csv(out / M.READINESS_NAME).iloc[0].to_dict()
        if (out / M.READINESS_NAME).is_file()
        else M.run_stage(ROOT)
    )
    master = pd.read_csv(out / M.MASTER_NAME)
    assert int(result["universe_ticker_count"]) == master["ticker"].nunique()
    assert float(result["top20_coverage_rate"]) >= 0.98
    assert float(result["top50_coverage_rate"]) >= 0.98
    assert float(result["holdings_coverage_rate"]) >= 0.95
    assert int(result["pit_leakage_warnings"]) == 0
    assert str(result["protected_outputs_modified"]).upper() == "FALSE"
    assert str(result["official_outputs_mutated"]).upper() == "FALSE"
    assert str(result["official_adoption_allowed"]).upper() == "FALSE"
    print("PASS test_v21_076_pit_sector_industry_classification_audit")
