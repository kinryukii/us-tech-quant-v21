#!/usr/bin/env python
from pathlib import Path
import importlib.util, pandas as pd
ROOT=Path(__file__).resolve().parents[2]
P=ROOT/"scripts/v21/v21_074_r1_entry_threshold_diagnostic.py"
S=importlib.util.spec_from_file_location("m",P); M=importlib.util.module_from_spec(S); S.loader.exec_module(M)
if __name__=="__main__":
 r=M.run_stage(ROOT); d=pd.read_csv(ROOT/M.OUT_REL/M.SUMMARY_NAME)
 assert r["pass_gate"] and not d.empty
 assert {"TOP20","TOP50"}.issubset(set(d.top_n))
 print("PASS test_v21_074_r1_entry_threshold_diagnostic")
