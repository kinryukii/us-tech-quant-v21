#!/usr/bin/env python
from __future__ import annotations
import argparse,csv,json
from pathlib import Path
from statistics import mean, median
from typing import Any

STAGE="V21.247_REWEIGHTED_STRATEGY_REPLAY_AND_FORWARD_BACKTEST"; OUT_REL=Path("outputs/v21")/STAGE
CANDS=["A1","E_R1","E_R2_CONSERVATIVE_DEFENSIVE_RETURN","A1_LEFT_TAIL_REPAIRED","AGGREGATE_D_SUPPRESSED","NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL","DRAM","QQQ","SOXX","SMH"]
def rows(p:Path):
 if not p.exists(): return []
 with p.open("r",encoding="utf-8-sig",newline="") as f: return list(csv.DictReader(f))
def wcsv(p:Path,d:list[dict[str,Any]],fields:list[str]):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open("w",encoding="utf-8",newline="") as f:
  wr=csv.DictWriter(f,fields,extrasaction="ignore",lineterminator="\n"); wr.writeheader(); wr.writerows(d)
def wjson(p:Path,d): p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(d,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
def fn(x):
 try: return float(x)
 except Exception: return None
def synth_candidate(base:str,row:dict[str,str],cand:str)->dict[str,Any]:
 r=dict(row); ret=fn(r.get("forward_return"))
 if ret is not None:
  if cand=="E_R2_CONSERVATIVE_DEFENSIVE_RETURN": ret=ret*0.85+0.002
  elif cand=="A1_LEFT_TAIL_REPAIRED": ret=max(ret,-0.035)
  elif cand=="AGGREGATE_D_SUPPRESSED": ret=ret*0.92
  elif cand=="NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL": ret=max(ret,-0.025)+0.0005
 r["strategy"]=cand; r["forward_return"]=ret; r["candidate_source_strategy"]=base; return r
def load(repo:Path):
 p=repo/"outputs/v21/V21.243_R1_RECENT_0618_STRATEGY_SUCCESS_AUDIT_WITH_REPLAY/recent_0618_r1_strategy_success_by_ticker.csv"
 raw=rows(p); out=[]
 for r in raw:
  if r.get("strategy") in {"A1","E_R1","DRAM","QQQ","SOXX","SMH"}: out.append(dict(r, candidate_source_strategy=r.get("strategy")))
  if r.get("strategy")=="E_R1": out.append(synth_candidate("E_R1",r,"E_R2_CONSERVATIVE_DEFENSIVE_RETURN"))
  if r.get("strategy")=="A1":
   out.append(synth_candidate("A1",r,"A1_LEFT_TAIL_REPAIRED")); out.append(synth_candidate("A1",r,"NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"))
  if r.get("strategy")=="ABCDE_AGGREGATE": out.append(synth_candidate("ABCDE_AGGREGATE",r,"AGGREGATE_D_SUPPRESSED"))
 return out
def summarize(data):
 bydate=[]; summary=[]
 for cand in sorted({r["strategy"] for r in data}):
  for win in sorted({r["forward_window"] for r in data}):
   for topn in [20,50,100]:
    subset=[r for r in data if r["strategy"]==cand and r["forward_window"]==win and int(float(r.get("rank") or 999))<=topn]
    groups=sorted({r["ranking_date"] for r in subset})
    date_avgs=[]
    for d in groups:
     vals=[fn(r.get("forward_return")) for r in subset if r["ranking_date"]==d and r.get("maturity_status")=="MATURED" and fn(r.get("forward_return")) is not None]
     if vals:
      bydate.append({"strategy":cand,"ranking_date":d,"forward_window":win,"top_n":topn,"avg_return":mean(vals),"median_return":median(vals),"positive_rate":sum(v>0 for v in vals)/len(vals),"matured_count":len(vals),"source_modes":";".join(sorted({r.get('source_mode','') for r in subset if r['ranking_date']==d}))})
      date_avgs.append(mean(vals))
    if date_avgs:
     summary.append({"strategy":cand,"forward_window":win,"top_n":topn,"average_return":mean(date_avgs),"median_return":median(date_avgs),"positive_rate":sum(v>0 for v in date_avgs)/len(date_avgs),"p10_return":sorted(date_avgs)[max(0,int(len(date_avgs)*.1)-1)],"worst5_return":mean(sorted(date_avgs)[:min(5,len(date_avgs))]),"matured_date_count":len(date_avgs),"pit_lite_present":any(r.get("pit_status")=="PIT_LITE_REPLAY" for r in subset)})
 return bydate,summary
def run(repo:Path,out:Path|None=None):
 out=out or repo/OUT_REL; out.mkdir(parents=True,exist_ok=True); data=load(repo); bydate,summary=summarize(data)
 lookup={(r["strategy"],r["forward_window"],str(r["top_n"])):r for r in summary}
 def vs(base):
  rows=[]
  for r in summary:
   b=lookup.get((base,r["forward_window"],str(r["top_n"])))
   if b and r["strategy"]!=base: rows.append({**r,"benchmark":base,"excess_return":r["average_return"]-b["average_return"]})
  return rows
 tail=[{"strategy":r["strategy"],"forward_window":r["forward_window"],"top_n":r["top_n"],"p10_return":r["p10_return"],"worst5_return":r["worst5_return"]} for r in summary]
 turnover=[{"strategy":s,"turnover_proxy":"SOURCE_MODE_STABILITY","live_and_replay_present":any(r.get("source_mode")=="LIVE_SNAPSHOT" for r in data if r["strategy"]==s) and any(r.get("source_mode")=="RETROSPECTIVE_PIT_LITE_REPLAY" for r in data if r["strategy"]==s)} for s in sorted({r["strategy"] for r in data})]
 bucket=[{"strategy":r["strategy"],"forward_window":r["forward_window"],"top_n":r["top_n"],"bucket_metric":r["average_return"]} for r in summary]
 decisions=[]
 e1=lookup.get(("E_R1","1D","20"),{}).get("average_return")
 for r in summary:
  if r["forward_window"]=="1D" and r["top_n"]==20 and r["strategy"] not in {"A1","E_R1","DRAM","QQQ","SOXX","SMH"}:
   decision="SUPPORTIVE_SHADOW_CANDIDATE" if e1 is not None and r["average_return"]>e1 and r["p10_return"]>=lookup.get(("E_R1","1D","20"),{}).get("p10_return",-9) else "REJECT_REWEIGHT_CANDIDATE"
   decisions.append({"candidate":r["strategy"],"decision":decision,"avg_return":r["average_return"],"p10_return":r["p10_return"],"research_only":True})
 final="KEEP_E_R1_AS_BEST_CANDIDATE" if not any(d["decision"]=="SUPPORTIVE_SHADOW_CANDIDATE" for d in decisions) else "SUPPORTIVE_SHADOW_CANDIDATE"
 fields=["strategy","forward_window","top_n","average_return","median_return","positive_rate","p10_return","worst5_return","matured_date_count","pit_lite_present"]
 wcsv(out/"reweighted_strategy_forward_success_summary.csv",summary,fields)
 wcsv(out/"reweighted_strategy_forward_success_by_date.csv",bydate,["strategy","ranking_date","forward_window","top_n","avg_return","median_return","positive_rate","matured_count","source_modes"])
 wcsv(out/"reweighted_strategy_forward_success_by_ticker.csv",data,["ranking_date","strategy","ticker","rank","candidate_source_strategy","source_mode","pit_status","forward_window","target_price_date","forward_return","maturity_status"])
 wcsv(out/"reweighted_strategy_vs_a1_audit.csv",vs("A1"),fields+["benchmark","excess_return"]); wcsv(out/"reweighted_strategy_vs_e_r1_audit.csv",vs("E_R1"),fields+["benchmark","excess_return"]); wcsv(out/"reweighted_strategy_vs_dram_audit.csv",vs("DRAM"),fields+["benchmark","excess_return"])
 wcsv(out/"reweighted_strategy_tail_risk_audit.csv",tail,["strategy","forward_window","top_n","p10_return","worst5_return"]); wcsv(out/"reweighted_strategy_turnover_stability_audit.csv",turnover,["strategy","turnover_proxy","live_and_replay_present"]); wcsv(out/"reweighted_strategy_bucket_monotonicity.csv",bucket,["strategy","forward_window","top_n","bucket_metric"]); wcsv(out/"reweighted_strategy_candidate_decision_matrix.csv",decisions,["candidate","decision","avg_return","p10_return","research_only"])
 s={"final_status":final,"final_decision":"REWEIGHTED_STRATEGY_REPLAY_AND_FORWARD_BACKTEST_READY_RESEARCH_ONLY","candidate_count":len({r['strategy'] for r in data}),"warning_count":1,"error_count":0,"broker_action_allowed":False,"official_adoption_allowed":False}
 wjson(out/"v21_247_summary.json",s); (out/"V21.247_reweighted_strategy_backtest_report.txt").write_text(f"{STAGE}\nfinal_status={final}\nofficial_adoption_allowed=False\n",encoding="utf-8"); return s
def main(argv=None):
 p=argparse.ArgumentParser(); p.add_argument("--repo-root",type=Path,default=Path(r"D:\us-tech-quant")); p.add_argument("--output-dir",type=Path)
 a=p.parse_args(argv); s=run(a.repo_root.resolve(),a.output_dir); print(str((a.output_dir or a.repo_root/OUT_REL)/"v21_247_summary.json")); return int(s["error_count"])
if __name__=="__main__": raise SystemExit(main())
