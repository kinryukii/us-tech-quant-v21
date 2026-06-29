#!/usr/bin/env python
from pathlib import Path
import importlib.util, pandas as pd
ROOT=Path(__file__).resolve().parents[2]
P=ROOT/"scripts/v21/v21_075_r1_position_sizing_policy_builder.py"
S=importlib.util.spec_from_file_location("m",P); M=importlib.util.module_from_spec(S); S.loader.exec_module(M)
if __name__=="__main__":
 r=M.run_stage(ROOT); out=ROOT/M.OUT_REL
 policies=pd.read_csv(out/M.POLICY_NAME); grid=pd.read_csv(out/M.GRID_NAME)
 assert r["pass_gate"] and len(policies)==10 and len(grid)==20
 assert not grid.official_adoption_allowed.any()
 print("PASS test_v21_075_r1_position_sizing_policy_builder")
