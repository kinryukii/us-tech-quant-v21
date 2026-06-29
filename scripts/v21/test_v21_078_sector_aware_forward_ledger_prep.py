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
    result = M.run_stage(ROOT)
    out = ROOT / M.OUT_REL
    for name in (M.CANDIDATE_NAME, M.LEDGER_NAME, M.AUDIT_NAME, M.READINESS_NAME):
        assert (out / name).is_file(), name
    candidates = pd.read_csv(out / M.CANDIDATE_NAME)
    ledger = pd.read_csv(out / M.LEDGER_NAME)
    audit = pd.read_csv(out / M.AUDIT_NAME).iloc[0]
    assert {"D_EW_TOP20_R1", "D_EW_TOP50_R1", "D_SECTOR_INDUSTRY_CAP_TOP20_R1", "D_SECTOR_CAP_TOP50_R1"}.issubset(set(candidates["policy_id"]))
    assert int(audit["duplicate_observation_ids"]) == 0
    assert str(audit["weight_sum_validity"]).upper() == "TRUE"
    assert str(audit["theme_hard_cap_usage"]).upper() == "FALSE"
    assert int(result["leakage_warnings"]) == 0
    assert int(result["matured_observations"]) == 0
    assert str(result["protected_outputs_modified"]).upper() == "FALSE"
    assert str(result["official_outputs_mutated"]).upper() == "FALSE"
    assert str(result["official_adoption_allowed"]).upper() == "FALSE"
    assert set(ledger["forward_window"]) == {"5D", "10D", "20D"}
    if str(result["final_status"]).startswith("PASS"):
        assert int(audit["missing_sector_industry"]) == 0
        assert int(result["latest_infeasible_candidate_count"]) == 0
        assert str(result["baseline_candidate_pair_complete"]).upper() == "TRUE"
    else:
        assert str(result["final_status"]) == "BLOCKED_V21_078_R3_FORWARD_LEDGER_INTEGRITY_OR_LEAKAGE_RISK"
    print("PASS test_v21_078_sector_aware_forward_ledger_prep")
