#!/usr/bin/env python
from pathlib import Path
import importlib.util, pandas as pd
ROOT=Path(__file__).resolve().parents[2]
P=ROOT/"scripts/v21/v21_075_r2_ranking_only_portfolio_backtest.py"
S=importlib.util.spec_from_file_location("m",P); M=importlib.util.module_from_spec(S); S.loader.exec_module(M)
if __name__=="__main__":
 out=ROOT/M.OUT_REL
 r=(pd.read_csv(out/M.VALIDATION_NAME).iloc[0].to_dict()
    if (out/M.VALIDATION_NAME).is_file() else M.run_stage(ROOT))
 metrics=pd.read_csv(out/M.METRICS_NAME)
 assert str(r["pass_gate"]).upper()=="TRUE" and int(r["portfolio_policy_count"])==20
 assert {"TRAIN","VALIDATION","TEST"}.issubset(set(metrics.split))
 assert {"5D","10D","20D"}.issubset(set(metrics.window))
 assert str(r["protected_outputs_modified"]).upper()=="FALSE"
 print("PASS test_v21_075_r2_ranking_only_portfolio_backtest")
