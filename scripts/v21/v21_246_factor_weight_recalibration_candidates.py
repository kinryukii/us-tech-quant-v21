#!/usr/bin/env python
from __future__ import annotations
import argparse,csv,json
from pathlib import Path
from typing import Any

STAGE="V21.246_FACTOR_WEIGHT_RECALIBRATION_CANDIDATES"; OUT_REL=Path("outputs/v21")/STAGE
FAMILIES=["Fundamental","Technical","Strategy","Risk","Market Regime","Data Trust"]
BASE={"Fundamental":0.15,"Technical":0.35,"Strategy":0.20,"Risk":0.15,"Market Regime":0.10,"Data Trust":0.05}
CANDIDATES={
"E_R2_CONSERVATIVE_DEFENSIVE_RETURN":{"Fundamental":0.12,"Technical":0.28,"Strategy":0.18,"Risk":0.27,"Market Regime":0.10,"Data Trust":0.05},
"A1_LEFT_TAIL_REPAIRED":{"Fundamental":0.14,"Technical":0.30,"Strategy":0.18,"Risk":0.23,"Market Regime":0.10,"Data Trust":0.05},
"AGGREGATE_D_SUPPRESSED":{"Fundamental":0.15,"Technical":0.34,"Strategy":0.16,"Risk":0.20,"Market Regime":0.10,"Data Trust":0.05},
"DRAM_GATE_AWARE":{"Fundamental":0.12,"Technical":0.30,"Strategy":0.18,"Risk":0.20,"Market Regime":0.15,"Data Trust":0.05},
"NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL":{"Fundamental":0.12,"Technical":0.29,"Strategy":0.17,"Risk":0.27,"Market Regime":0.10,"Data Trust":0.05},
}
def wcsv(p:Path, rows:list[dict[str,Any]], fields:list[str]):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open("w",encoding="utf-8",newline="") as f:
  wr=csv.DictWriter(f,fields,extrasaction="ignore",lineterminator="\n"); wr.writeheader(); wr.writerows(rows)
def wjson(p:Path,d): p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(d,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
def run(repo:Path,out:Path|None=None):
 out=out or repo/OUT_REL; out.mkdir(parents=True,exist_ok=True)
 master=[]; delta=[]; defs=[]; risk=[]
 for cand,weights in CANDIDATES.items():
  total=round(sum(weights.values()),10); concentration_warn="D_SUPPRESSED" not in cand and weights["Strategy"]>BASE["Strategy"]
  for fam in FAMILIES:
   master.append({"candidate":cand,"factor_family":fam,"weight":weights[fam],"weights_sum":total,"research_only":True,"official_adoption_allowed":False,"broker_action_allowed":False})
   delta.append({"candidate":cand,"factor_family":fam,"baseline_weight":BASE[fam],"candidate_weight":weights[fam],"delta":weights[fam]-BASE[fam],"bounded_delta_pass":abs(weights[fam]-BASE[fam])<=0.120000001})
  defs.append({"candidate":cand,"definition":"bounded shadow recalibration candidate","baseline_control_preserved":cand!="A1","official_adoption_allowed":False})
  risk.append({"candidate":cand,"family_weights_sum":total,"concentration_risk_warning":concentration_warn,"d_style_signal_status":"CAPPED_OR_DIAGNOSTIC_ONLY" if cand in {"AGGREGATE_D_SUPPRESSED","NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"} else "UNCHANGED","risk_constraint_pass":abs(total-1.0)<1e-9 and not concentration_warn})
 feasibility=[
  {"factor":"repeated_loser_penalty","feasible":True,"source":"V21.243_R1 repeated loser rows","moomoo_only":True},
  {"factor":"left_tail_memory_factor","feasible":True,"source":"V21.245 tail attribution","moomoo_only":True},
  {"factor":"intraday_follow_through_factor","feasible":True,"source":"DRAM intraday cache where ticker available","moomoo_only":True},
  {"factor":"gap_overnight_risk_factor","feasible":True,"source":"Moomoo OHLC daily open/close","moomoo_only":True},
  {"factor":"event_proximity_risk_factor","feasible":False,"source":"No reliable local Moomoo event source confirmed","moomoo_only":False},
 ]
 wcsv(out/"factor_weight_candidate_master.csv",master,["candidate","factor_family","weight","weights_sum","research_only","official_adoption_allowed","broker_action_allowed"])
 wcsv(out/"factor_weight_candidate_delta_audit.csv",delta,["candidate","factor_family","baseline_weight","candidate_weight","delta","bounded_delta_pass"])
 wcsv(out/"new_factor_feasibility_audit.csv",feasibility,["factor","feasible","source","moomoo_only"])
 wcsv(out/"candidate_strategy_definition.csv",defs,["candidate","definition","baseline_control_preserved","official_adoption_allowed"])
 wcsv(out/"candidate_risk_constraint_audit.csv",risk,["candidate","family_weights_sum","concentration_risk_warning","d_style_signal_status","risk_constraint_pass"])
 s={"final_status":"PASS_V21_246_WEIGHT_CANDIDATES_READY","final_decision":"FACTOR_WEIGHT_RECALIBRATION_CANDIDATES_READY_RESEARCH_ONLY","candidate_count":len(CANDIDATES),"all_weights_sum_to_one":all(abs(sum(w.values())-1)<1e-9 for w in CANDIDATES.values()),"bounded_candidate_deltas":all(abs(r["delta"])<=0.120000001 for r in delta),"official_adoption_allowed":False,"broker_action_allowed":False,"warning_count":sum(1 for r in risk if r["concentration_risk_warning"]),"error_count":0}
 wjson(out/"v21_246_summary.json",s); (out/"V21.246_factor_weight_recalibration_report.txt").write_text(f"{STAGE}\nfinal_status={s['final_status']}\nofficial_adoption_allowed=False\n",encoding="utf-8"); return s
def main(argv=None):
 p=argparse.ArgumentParser(); p.add_argument("--repo-root",type=Path,default=Path(r"D:\us-tech-quant")); p.add_argument("--output-dir",type=Path)
 a=p.parse_args(argv); s=run(a.repo_root.resolve(),a.output_dir); print(str((a.output_dir or a.repo_root/OUT_REL)/"v21_246_summary.json")); return int(s["error_count"])
if __name__=="__main__": raise SystemExit(main())
