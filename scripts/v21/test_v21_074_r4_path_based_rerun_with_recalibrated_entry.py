#!/usr/bin/env python
from pathlib import Path
import importlib.util, pandas as pd
ROOT=Path(__file__).resolve().parents[2]
P=ROOT/"scripts/v21/v21_074_r4_path_based_rerun_with_recalibrated_entry.py"
S=importlib.util.spec_from_file_location("m",P); M=importlib.util.module_from_spec(S); S.loader.exec_module(M)
if __name__=="__main__":
 r=M.run_stage(ROOT); out=ROOT/M.OUT_REL
 metrics=pd.read_csv(out/M.METRICS_NAME); recs=pd.read_csv(out/M.RECOMMENDATION_NAME)
 assert r["pass_gate"] and r["d_ranking_only_baseline_preserved"]
 assert r["leakage_warnings"]==0
 assert metrics.entry_policy_id.nunique()==5
 assert not recs.official_adoption_allowed.any()
 assert not recs.forward_trade_signal_ledger_append_allowed.any()
 assert r["protected_outputs_modified"] is False
 print("PASS test_v21_074_r4_path_based_rerun_with_recalibrated_entry")
