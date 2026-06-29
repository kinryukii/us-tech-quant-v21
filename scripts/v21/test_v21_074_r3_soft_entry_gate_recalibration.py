#!/usr/bin/env python
from pathlib import Path
import importlib.util, pandas as pd
ROOT=Path(__file__).resolve().parents[2]
P=ROOT/"scripts/v21/v21_074_r3_soft_entry_gate_recalibration.py"
S=importlib.util.spec_from_file_location("m",P); M=importlib.util.module_from_spec(S); S.loader.exec_module(M)
if __name__=="__main__":
 r=M.run_stage(ROOT); d=pd.read_csv(ROOT/M.OUT_REL/M.POLICY_NAME)
 assert r["pass_gate"] and len(d)==5
 assert d.hard_block_data_quality.all()
 assert not d.official_adoption_allowed.any()
 print("PASS test_v21_074_r3_soft_entry_gate_recalibration")
