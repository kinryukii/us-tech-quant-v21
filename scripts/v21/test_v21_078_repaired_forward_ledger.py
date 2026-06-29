#!/usr/bin/env python
from pathlib import Path
import importlib.util
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
P = ROOT / "scripts/v21/v21_078_sector_aware_forward_ledger_prep.py"
S = importlib.util.spec_from_file_location("m", P)
M = importlib.util.module_from_spec(S)
S.loader.exec_module(M)

if __name__ == "__main__":
    M.run_stage(ROOT)
    out = ROOT / M.OUT_REL
    required = [
        M.R4_REPAIR_REPORT_NAME, M.R4_MASTER_NAME, M.R5_FEASIBILITY_NAME,
        M.R5_FALLBACK_NAME, M.R6_LEDGER_NAME, M.R6_AUDIT_NAME,
        M.R6_READINESS_NAME,
    ]
    for name in required:
        assert (out / name).is_file(), name
    report = pd.read_csv(out / M.R6_READINESS_NAME).iloc[0]
    audit = pd.read_csv(out / M.R6_AUDIT_NAME).iloc[0]
    fallback = pd.read_csv(out / M.R5_FALLBACK_NAME)
    ledger = pd.read_csv(out / M.R6_LEDGER_NAME)
    assert int(audit["duplicate_observation_ids"]) == 0
    assert int(audit["missing_sector_industry"]) == 0
    assert str(audit["weight_sum_validity"]).upper() == "TRUE"
    assert float(audit["max_ticker_weight"]) <= 0.10000001
    assert str(audit["theme_hard_cap_usage"]).upper() == "FALSE"
    assert int(audit["pit_leakage_warnings"]) == 0
    assert str(audit["protected_outputs_modified"]).upper() == "FALSE"
    assert str(audit["official_outputs_mutated"]).upper() == "FALSE"
    assert {"D_EW_TOP20_R1", "D_EW_TOP50_R1", "D_SECTOR_INDUSTRY_CAP_TOP20_R1", "D_SECTOR_CAP_TOP50_R1"}.issubset(set(ledger["original_policy_id"]))
    assert fallback["forward_ready"].astype(str).str.upper().eq("TRUE").all()
    assert str(report["official_adoption_allowed"]).upper() == "FALSE"
    assert str(report["forward_portfolio_append_allowed"]) == "RESEARCH_ONLY_REPAIRED_LEDGER_ONLY"
    print("PASS test_v21_078_repaired_forward_ledger")
