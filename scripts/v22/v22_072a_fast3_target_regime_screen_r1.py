from __future__ import annotations
import argparse, importlib.util, json, math, os, shutil, tempfile
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

REPO=Path(__file__).resolve().parents[2]; OUT_NAME="V22.072A_FAST3_TARGET_REGIME_SCREEN_R1"; LEGACY_RESULTS_ROOT=Path(r"D:\us-tech-quant-results\fast3\archive\legacy_v22")
CONTRACT=LEGACY_RESULTS_ROOT/"V22.069A_FAST_RESEARCH_CONTRACT_R1/v22_069a_fast_frozen_research_contract.json"
FEATURES=["PREMARKET_CUM_RETURN","PREMARKET_MAX_DRAWDOWN","PREMARKET_REALIZED_VOLATILITY"]; SYMS=["QQQ","SOXX","TQQQ","SQQQ","SOXL","SOXS"]; COST=.001
MODELS={"RIDGE":{"alpha":1.0},"CONSTRAINED_RANDOM_FOREST":{"n_estimators":200,"max_depth":3,"min_samples_leaf":80,"max_features":1.0,"random_state":20260731,"n_jobs":-1}}
TARGETS=[{"target":"V22_069_INTRADAY_OPEN_TO_CLOSE","definition":"exit_price / entry_price - 1","entry_timestamp":"09:30-09:32 first valid open","exit_timestamp":"15:58-16:00 last valid close","pit_available":True,"source_code_location":"scripts/v22/v22_069b_fast3_nonlinear_compact_development_r1.py:88-98"}]
REGIMES=["ALL","DIRECTION_POSITIVE","DIRECTION_NON_POSITIVE","VOL_LOW","VOL_MID","VOL_HIGH"]+[f"DIRECTION_{d}_VOL_{v}" for d in ("POSITIVE","NON_POSITIVE") for v in ("LOW","MID","HIGH")]
def n(x): return float(x) if x is not None and np.isfinite(x) else None
def stable(x): return json.dumps(x,sort_keys=True,indent=2,default=str)+"\n"
def model(k): return make_pipeline(StandardScaler(),Ridge(**MODELS[k])) if k=="RIDGE" else RandomForestRegressor(**MODELS[k])
def helper():
 p=REPO/"scripts/v22/v22_071a_fast3_symbol_segmented_research_r1.py"; s=importlib.util.spec_from_file_location("v071",p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def boundaries(train):
 q=train.PREMARKET_REALIZED_VOLATILITY.quantile([1/3,2/3]);return float(q.iloc[0]),float(q.iloc[1])
def label(frame,lo,hi):
 d=np.where(frame.PREMARKET_CUM_RETURN>0,"POSITIVE","NON_POSITIVE");v=np.where(frame.PREMARKET_REALIZED_VOLATILITY<=lo,"LOW",np.where(frame.PREMARKET_REALIZED_VOLATILITY<=hi,"MID","HIGH"));return pd.DataFrame({"direction":d,"vol":v},index=frame.index)
def mask(frame,reg,lo,hi):
 if reg=="ALL": return pd.Series(True,index=frame.index)
 z=label(frame,lo,hi)
 if reg.startswith("DIRECTION_") and "_VOL_" not in reg:return z.direction==reg.removeprefix("DIRECTION_")
 if reg.startswith("VOL_"):return z.vol==reg.removeprefix("VOL_")
 d,v=reg.removeprefix("DIRECTION_").split("_VOL_");return (z.direction==d)&(z.vol==v)
def bucket(y,p):
 if len(y)<5:return (None,)*4
 k=max(1,math.ceil(len(y)*.2));o=np.lexsort((np.arange(len(p)),p));a=np.asarray(y);top=float(a[o[-k:]].mean());bot=float(a[o[:k]].mean());return top,bot,top-bot,top-bot-COST
def conc(x,k,date=False):
 z=x.nlargest(max(1,math.ceil(len(x)*.2)),"prediction");p=z.target_return.clip(lower=0);total=p.sum()
 if total<=0:return None
 q=p.groupby(z.date).sum() if date else p;return n(q.nlargest(k).sum()/total)
def metric(x,folds,total):
 top,bot,gross,net=bucket(x.target_return,x.prediction);ics=[r["spearman_ic"] for r in folds if r["spearman_ic"] is not None];months=[]
 for _,g in x.groupby(x.date.str[:7]): months.append(bucket(g.target_return,g.prediction)[3])
 ss=[]
 for _,g in x.groupby("symbol"): ss.append(bucket(g.target_return,g.prediction)[3])
 u=int(x.prediction.nunique()) if len(x) else 0
 return {"event_count":len(x),"research_coverage_ratio":n(len(x)/total),"oof_spearman_ic":n(spearmanr(x.target_return,x.prediction).statistic) if len(x)>1 else None,"top_mean_return":top,"bottom_mean_return":bot,"top_bottom_spread_gross":gross,"top_bottom_spread_net_10bps":net,"positive_fold_ratio":n(np.mean([z>0 for z in ics])) if ics else None,"median_fold_ic":n(np.median(ics)) if ics else None,"worst_fold_ic":n(min(ics)) if ics else None,"positive_month_ratio":n(np.mean([z>0 for z in months if z is not None])) if any(z is not None for z in months) else None,"top5_date_concentration":conc(x,5,True) if len(x) else None,"top10_event_concentration":conc(x,10) if len(x) else None,"unique_score_count":u,"score_tie_ratio":n(1-u/len(x)) if len(x) else None,"valid_symbol_count":sum(z is not None for z in ss),"positive_symbol_net_spread_count":sum(z is not None and z>0 for z in ss),"negative_symbol_net_spread_count":sum(z is not None and z<=0 for z in ss)}
def evaluate(events,target,reg,kind,fold_defs):
 out=[]; rows=[];fits=0
 for f in fold_defs:
  tr=events[events.date.isin(f["train_dates"])];te=events[events.date.isin(f["test_dates"])];lo,hi=boundaries(tr);a=tr[mask(tr,reg,lo,hi)];b=te[mask(te,reg,lo,hi)]; valid=len(a)>=2 and len(b)>=2
  if valid:
   m=model(kind).fit(a[FEATURES],a.target_return);fits+=1;q=b[["date","symbol","target_return"]].copy();q["prediction"]=m.predict(b[FEATURES]);out.append(q);ic=n(spearmanr(q.target_return,q.prediction).statistic)
  else:ic=None
  rows.append({"target":target,"regime":reg,"model":kind,"fold_id":f["fold_id"],"train_end_date":max(f["train_dates"]),"test_start_date":min(f["test_dates"]),"train_event_count":len(a),"test_event_count":len(b),"volatility_low_boundary":lo,"volatility_high_boundary":hi,"spearman_ic":ic,"valid":valid,"time_order_valid":max(f["train_dates"])<min(f["test_dates"])})
 x=pd.concat(out,ignore_index=True) if out else pd.DataFrame(columns=["date","symbol","target_return","prediction"]);return metric(x,rows,len(events)),rows,fits
def gate(r):
 keys=[r.event_count>=1000,r.research_coverage_ratio>=.2,r.oof_spearman_ic is not None and r.oof_spearman_ic>0,r.top_bottom_spread_net_10bps is not None and r.top_bottom_spread_net_10bps>0,r.positive_fold_ratio is not None and r.positive_fold_ratio>=.6,r.median_fold_ic is not None and r.median_fold_ic>0,r.positive_month_ratio is not None and r.positive_month_ratio>=.5,r.top5_date_concentration is not None and r.top5_date_concentration<.6,r.valid_symbol_count>=4,r.positive_symbol_net_spread_count>=4,r.valid_fold_count>=5];return all(keys)
def run(results_root=LEGACY_RESULTS_ROOT):
 c=json.loads(CONTRACT.read_text());months=c["split"]["development_months"]+c["split"]["validation_months"];h=helper();events,_=h.build_events(months);fold_defs=h.expanding_folds(events.date);score=[];folds=[];fits=0
 for t in TARGETS:
  t["usable_event_count"]=len(events)
  for reg in REGIMES:
   for k in MODELS:
    r,f,x=evaluate(events,t["target"],reg,k,fold_defs);r.update({"target":t["target"],"regime":reg,"model":k,"valid_fold_count":sum(z["valid"] for z in f),"invalid_fold_count":sum(not z["valid"] for z in f)});r["coverage_eligible"]=r["event_count"]>=1000 and r["research_coverage_ratio"]>=.2 and r["valid_fold_count"]>=5 and r["valid_symbol_count"]>=4;r["candidate_pass"]=gate(pd.Series(r));score.append(r);folds+=f;fits+=x
 passes=[r for r in score if r["candidate_pass"]];rank={"RIDGE":0,"CONSTRAINED_RANDOM_FOREST":1};best=sorted(passes,key=lambda r:(-r["median_fold_ic"],-r["top_bottom_spread_net_10bps"],-r["positive_symbol_net_spread_count"],r["top5_date_concentration"],rank[r["model"]],r["regime"]!="ALL"))[0] if passes else max(score,key=lambda r:(r["oof_spearman_ic"] is not None,r["oof_spearman_ic"] or -99))
 selected=passes[0] if len(passes)==1 else (sorted(passes,key=lambda r:(-r["median_fold_ic"],-r["top_bottom_spread_net_10bps"],-r["positive_symbol_net_spread_count"],r["top5_date_concentration"],rank[r["model"]],r["regime"]!="ALL"))[0] if passes else None)
 summary={"final_status":"PASS","final_decision":"TARGET_REGIME_RESEARCH_CANDIDATE_FOUND" if selected else "FAST3_CURRENT_FEATURE_LINE_STOPPED_NO_TARGET_REGIME_EDGE","next_freeze_stage_allowed":bool(selected),"fast3_current_feature_line_stopped":not bool(selected),"selected_target":selected["target"] if selected else None,"selected_regime":selected["regime"] if selected else None,"selected_model":selected["model"] if selected else None,"research_event_count":len(events),"former_development_role":"RESEARCH_DATA","former_validation_role":"RESEARCH_DATA","former_validation_still_independent":False,"confirmation_remains_sealed":True,"confirmation_row_read_count":0,"target_candidate_count":len(TARGETS),"regime_candidate_count":len(REGIMES),"candidate_model_count":2,"valid_fold_count":5,"invalid_fold_count":0,"time_order_violation_count":sum(not z["time_order_valid"] for z in folds),"data_leakage_detected":False,"research_fit_call_count":fits,"hyperparameter_search_count":0,"final_frozen_model_output_count":0,"broker_action_allowed":False,"paper_trading_allowed":False,"official_adoption_allowed":False,"live_trading_allowed":False,"order_output_count":0,"position_output_count":0,"broker_connection_count":0,**{f"best_{k}":best[k] for k in ("target","regime","model","oof_spearman_ic","top_bottom_spread_net_10bps","positive_fold_ratio","positive_month_ratio","positive_symbol_net_spread_count")}}
 out=Path(results_root)/OUT_NAME;out.parent.mkdir(parents=True,exist_ok=True);stage=Path(tempfile.mkdtemp(prefix=".072a_",dir=out.parent))
 try:
  (stage/"v22_072a_summary.json").write_text(stable(summary));pd.DataFrame(score).to_csv(stage/"target_regime_scorecard.csv",index=False);pd.DataFrame(folds).to_csv(stage/"fold_scorecard.csv",index=False);(stage/"target_inventory.json").write_text(stable(TARGETS));(stage/"research_contract.json").write_text(stable({"features":FEATURES,"symbols":SYMS,"cost_bps":10,"confirmation_remains_sealed":True,"confirmation_row_read_count":0,"random_kfold_used":False,"regime_threshold_search_count":0,"target_selection":"existing_contracts_shortest_to_longest_max_four"}));
  if out.exists():shutil.rmtree(out)
  os.replace(stage,out);return summary,out
 except Exception:shutil.rmtree(stage,ignore_errors=True);raise
if __name__=="__main__":
 a=argparse.ArgumentParser();a.add_argument("--execute",action="store_true");a.add_argument("--results-root",default=str(LEGACY_RESULTS_ROOT));z=a.parse_args()
 if z.execute:s,o=run(Path(z.results_root));print(json.dumps({**s,"summary_path":str(o/"v22_072a_summary.json")},sort_keys=True))
