#!/usr/bin/env python
from pathlib import Path
import importlib.util
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
P = ROOT / "scripts/v21/v21_082_soft_execution_forward_ledger_prep.py"
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
    assert {M.BASELINE, M.PRIMARY}.issubset(set(candidates["policy_id"]))
    assert {M.BASELINE, M.PRIMARY}.issubset(set(ledger["policy_id"]))
    assert int(audit["duplicate_observation_ids"]) == 0
    assert str(audit["weight_sums_valid"]).upper() == "TRUE"
    assert int(audit["leakage_warnings"]) == 0
    assert str(audit["baseline_candidate_pair_complete"]).upper() == "TRUE"
    assert str(audit["maturity_schedule_valid"]).upper() == "TRUE"
    assert str(result["protected_outputs_modified"]).upper() == "FALSE"
    assert str(result["official_outputs_mutated"]).upper() == "FALSE"
    assert str(result["official_adoption_allowed"]).upper() == "FALSE"
    print("PASS test_v21_082_soft_execution_forward_ledger_prep")
