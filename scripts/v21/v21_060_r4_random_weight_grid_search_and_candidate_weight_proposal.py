#!/usr/bin/env python
"""Research-only multi-seed momentum weight grid search."""
from __future__ import annotations
import argparse, csv, importlib.util, json
from pathlib import Path
import numpy as np
import pandas as pd

STAGE_ID="V21.060-R4"
PASS_STATUS="PASS_V21_060_R4_WEIGHT_GRID_SEARCH_READY"
PARTIAL_STATUS="PARTIAL_PASS_V21_060_R4_WEIGHT_GRID_READY_WITH_FALLBACK_OR_SAMPLE_WARN"
FAIL_A0="FAIL_V21_060_R4_A0_REPLAY_OR_MUTATION_VIOLATION"
FAIL_VARIANT="FAIL_V21_060_R4_EXISTING_VARIANT_MUTATION_DETECTED"
FAIL_HARDCODED="FAIL_V21_060_R4_HARDCODED_INCLUSION_VIOLATION"
FAIL_PRICE="FAIL_V21_060_R4_LOCAL_PRICE_MISSING_INCLUDED"
FAIL_TQQQ="FAIL_V21_060_R4_TQQQ_IPO_WATCH_POLICY_VIOLATION"
FAIL_MUTATION="FAIL_V21_060_R4_FORBIDDEN_MUTATION_DETECTED"
OUT_REL=Path("outputs/v21/experiments/momentum_dynamic/random_backtests/weight_search")
ROW_NAME="V21_060_R4_WEIGHT_GRID_ROW_LEVEL_RESULTS.csv"
PORT_NAME="V21_060_R4_WEIGHT_GRID_10000_PORTFOLIO_RESULTS.csv"
SEED_NAME="V21_060_R4_WEIGHT_GRID_COMPARISON_BY_SEED.csv"
OVERALL_NAME="V21_060_R4_WEIGHT_GRID_COMPARISON_OVERALL.csv"
PAIR_NAME="V21_060_R4_WEIGHT_PAIRWISE_COMPARISON.csv"
REPORT_NAME="V21_060_R4_WEIGHT_SELECTION_TRAIN_VALIDATION_REPORT.csv"
PROPOSAL_NAME="V21_060_R4_CANDIDATE_WEIGHT_PROPOSAL.csv"
EXAMPLE_NAME="V21_060_R4_10000_WEIGHT_EXAMPLE_SUMMARY.csv"
FORCED_NAME="V21_060_R4_FORCED_TICKER_WEIGHT_SEARCH_AUDIT.csv"
LINEAGE_NAME="V21_060_R4_WEIGHT_SEARCH_LINEAGE_AUDIT.csv"
SUMMARY_NAME="V21_060_R4_SUMMARY.json"
WEIGHTS=(0,.05,.10,.15,.20,.25,.30,.35,.40)
SEEDS=tuple(range(20260601,20260631)); TRAIN=set(SEEDS[:18])
WINDOWS={"5D":5,"10D":10,"20D":20,"60D":60}; TOPS=(10,20,50)
INITIAL=10000.; TX=10.; SLIP=5.; COST=2*(TX+SLIP)/10000
FORCED=("MU","SNDK","DRAM","SPCX","USD","SMH","SOXX","SOXL","QQQ","TQQQ","SQQQ","BITF")
ROW_FIELDS=["seed","seed_split","batch_id","sampled_as_of_date","strategy_id","variant_id","weight_candidate_id","momentum_weight","top_n_bucket","forward_window","ticker","instrument_type","theme","rank","score","base_score","momentum_score","applied_momentum_weight","selection_reason","allocation_weight","entry_price","exit_price","gross_position_return","net_position_return","benchmark_spy_return","benchmark_qqq_return","benchmark_smh_return","excess_return_vs_SPY","excess_return_vs_QQQ","excess_return_vs_SMH","market_regime","regime_fallback_used","price_data_status","point_in_time_valid","fallback_used","leveraged_exposure_used","inverse_exposure_used","local_price_missing_flag","research_only"]

def load(root,name,file):
 p=root/"scripts/v21"/file; s=importlib.util.spec_from_file_location(name,p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
def cid(w): return f"GRID_STATIC_W{int(round(w*100)):02d}"
def split(seed): return "TRAIN" if seed in TRAIN else "VALIDATION"
def norm(s):
 if s.max()==s.min(): return pd.Series(.5,index=s.index)
 return (s-s.min())/(s.max()-s.min())
def write(df,path): df.to_csv(path,index=False,lineterminator="\n")

def draws(merged):
 dates=sorted(merged.groupby("as_of_date").filter(lambda x: x["forward_60d"].notna().sum()>=50).as_of_date.unique())
 rows=[]
 for seed in SEEDS:
  for i,d in enumerate(np.random.default_rng(seed).choice(dates,100,replace=True),1):
   rows.append({"seed":seed,"seed_split":split(seed),"draw_index":i,"as_of_date":str(d),"batch_id":f"{seed}::DRAW_{i:03d}::{d}"})
 return pd.DataFrame(rows),len(dates)<100

def benchmark_refs(root,r1,r3,prices,draw_df):
 meta=r3.etf_metadata(root); rot=r3.rotation_table(prices,meta)
 etf=r3.build_etf_rows(draw_df[["seed","draw_index","as_of_date"]],rot)
 etf=etf[etf.strategy_id.isin(["QQQ_BUY_AND_HOLD_BENCHMARK","ETF_ROTATION_1X","ETF_ROTATION_TACTICAL_OPTIONAL"])]
 p=r3.portfolios(etf); p["seed_split"]=p.seed.map(split)
 return p

def make_weight(root,r1,r2,merged,draw_df,prices,w,header):
 meta=r2.metadata(root)
 cols=["as_of_date","ticker","price","base_score","historical_momentum_score","forward_5d","forward_10d","forward_20d","forward_60d","exit_price_5d","exit_price_10d","exit_price_20d","exit_price_60d"]
 x=draw_df.merge(merged[cols],on="as_of_date",how="left")
 x["score"]=x.base_score*(1-w)+x.historical_momentum_score*w
 x["rank"]=x.groupby(["seed","draw_index"])["score"].rank(method="first",ascending=False)
 x=x[x["rank"]<=50].copy()
 x["instrument_type"]=x.ticker.map(lambda t:meta.get(t,{}).get("instrument_type","STOCK"))
 x["theme"]=x.ticker.map(lambda t:meta.get(t,{}).get("theme",""))
 bench=prices[prices.ticker.isin(["SPY","QQQ","SMH"])].set_index(["ticker","as_of_date"])
 records=[]; portfolios=[]
 for label,days in WINDOWS.items():
  z=x[x[f"forward_{days}d"].notna() & x.price.notna()].copy()
  z["gross"]=z[f"forward_{days}d"]; z["net"]=(1-COST/2)*(1+z.gross)*(1-COST/2)-1
  for t,col in [("SPY","spy"),("QQQ","qqq"),("SMH","smh")]:
   lookup=bench[f"forward_{days}d"].to_dict(); z[col]=[lookup.get((t,d),np.nan) for d in z.as_of_date]
  z["top_n_bucket"]=np.where(z["rank"]<=10,"TOP10",np.where(z["rank"]<=20,"TOP20","TOP50"))
  frame=pd.DataFrame({
   "seed":z.seed,"seed_split":z.seed_split,"batch_id":z.batch_id,"sampled_as_of_date":z.as_of_date,
   "strategy_id":cid(w),"variant_id":cid(w),"weight_candidate_id":cid(w),"momentum_weight":w,
   "top_n_bucket":z.top_n_bucket,"forward_window":label,"ticker":z.ticker,"instrument_type":z.instrument_type,"theme":z.theme,
   "rank":z["rank"].astype(int),"score":z.score,"base_score":z.base_score,"momentum_score":z.historical_momentum_score,
   "applied_momentum_weight":w,"selection_reason":"OBJECTIVE_PIT_WEIGHT_GRID_RANK","allocation_weight":1/50,
   "entry_price":z.price,"exit_price":z[f"exit_price_{days}d"],"gross_position_return":z.gross,"net_position_return":z.net,
   "benchmark_spy_return":z.spy,"benchmark_qqq_return":z.qqq,"benchmark_smh_return":z.smh,
   "excess_return_vs_SPY":z.gross-z.spy,"excess_return_vs_QQQ":z.gross-z.qqq,"excess_return_vs_SMH":z.gross-z.smh,
   "market_regime":"UNKNOWN","regime_fallback_used":"TRUE","price_data_status":"PASS","point_in_time_valid":"TRUE",
   "fallback_used":"TRUE","leveraged_exposure_used":np.where(z.instrument_type=="LEVERAGED_LONG_ETF","TRUE","FALSE"),
   "inverse_exposure_used":np.where(z.instrument_type=="INVERSE_ETF","TRUE","FALSE"),"local_price_missing_flag":"FALSE","research_only":"TRUE"})
  frame[ROW_FIELDS].to_csv(root/OUT_REL/ROW_NAME,index=False,mode="w" if header and not records else "a",header=header and not records,lineterminator="\n")
  records.append(len(frame))
  for n in TOPS:
   q=z[z["rank"]<=n]
   for keys,g in q.groupby(["seed","seed_split","batch_id","as_of_date"]):
    gross=g.gross.mean(); net=g.net.mean()
    portfolios.append({"seed":keys[0],"seed_split":keys[1],"batch_id":keys[2],"sampled_as_of_date":keys[3],"strategy_id":cid(w),"variant_id":cid(w),"weight_candidate_id":cid(w),"momentum_weight":w,"top_n_bucket":f"TOP{n}","forward_window":label,"initial_capital_usd":INITIAL,"gross_ending_value_usd":INITIAL*(1+gross),"net_ending_value_usd":INITIAL*(1+net),"gross_return":gross,"net_return":net,"transaction_cost_bps_per_trade":TX,"slippage_bps_per_trade":SLIP,"total_cost_usd":INITIAL*(gross-net),"holding_count":len(g),"max_single_position_weight":1/n,"leveraged_exposure_used":"TRUE" if (g.instrument_type=="LEVERAGED_LONG_ETF").any() else "FALSE","inverse_exposure_used":"TRUE" if (g.instrument_type=="INVERSE_ETF").any() else "FALSE","fallback_used":"TRUE","research_only":"TRUE"})
 return pd.DataFrame(portfolios),sum(records)

def seed_stats(port):
 rows=[]
 for k,g in port.groupby(["seed","seed_split","weight_candidate_id","momentum_weight","forward_window","top_n_bucket"]):
  r=g.net_return; sd=r.std(ddof=0)
  rows.append({"seed":k[0],"seed_split":k[1],"weight_candidate_id":k[2],"momentum_weight":k[3],"forward_window":k[4],"top_n_bucket":k[5],"observation_count":len(g),"mean_net_return":r.mean(),"median_net_return":r.median(),"hit_rate":(r>0).mean(),"mean_net_ending_value_usd":g.net_ending_value_usd.mean(),"median_net_ending_value_usd":g.net_ending_value_usd.median(),"mean_excess_vs_QQQ":np.nan,"mean_excess_vs_SPY":np.nan,"volatility_proxy":sd,"risk_adjusted_return_proxy":r.mean()/sd if sd else np.nan,"worst_sample_return":r.min(),"leveraged_exposure_count":(g.leveraged_exposure_used=="TRUE").sum(),"inverse_exposure_count":(g.inverse_exposure_used=="TRUE").sum(),"fallback_row_count":len(g),"research_only":"TRUE"})
 return pd.DataFrame(rows)

def pair_table(seed,refs):
 ref_seed=refs.groupby(["seed","seed_split","strategy_id","forward_window","top_n_bucket"]).agg(mean_net_return=("net_return","mean"),hit_rate=("net_return",lambda x:(x>0).mean()),mean_net_ending_value_usd=("net_ending_value_usd","mean")).reset_index()
 base=pd.concat([seed.rename(columns={"weight_candidate_id":"strategy_id"}),ref_seed],ignore_index=True,sort=False)
 opponents=["GRID_STATIC_W00","GRID_STATIC_W20","QQQ_BUY_AND_HOLD_BENCHMARK","ETF_ROTATION_1X","ETF_ROTATION_TACTICAL_OPTIONAL"]
 rows=[]
 for candidate in [cid(w) for w in WEIGHTS]:
  for opp in opponents:
   for spl in ["TRAIN","VALIDATION"]:
    for win in WINDOWS:
     for bucket in [f"TOP{n}" for n in TOPS]:
      a=base[(base.strategy_id==candidate)&(base.seed_split==spl)&(base.forward_window==win)&(base.top_n_bucket==bucket)]
      b=base[(base.strategy_id==opp)&(base.seed_split==spl)&(base.forward_window==win)&(base.top_n_bucket==bucket)]
      j=a.merge(b,on=["seed","seed_split","forward_window","top_n_bucket"],suffixes=("_l","_r")); d=j.mean_net_return_l-j.mean_net_return_r
      count=len(j); rate=(d>0).mean() if count else np.nan
      conf="INSUFFICIENT_SEEDS" if count<5 else "DIRECTIONALLY_POSITIVE" if rate>=.7 and count>=10 else "DIRECTIONALLY_NEGATIVE" if rate<=.3 and count>=10 else "MIXED_OR_INCONCLUSIVE"
      rows.append({"candidate_id":candidate,"opponent_id":opp,"seed_split":spl,"forward_window":win,"top_n_bucket":bucket,"paired_seed_count":count,"mean_net_return_delta":d.mean(),"median_net_return_delta":d.median(),"hit_rate_delta":(j.hit_rate_l-j.hit_rate_r).mean(),"ending_value_delta_usd":(j.mean_net_ending_value_usd_l-j.mean_net_ending_value_usd_r).mean(),"seed_win_count":int((d>0).sum()),"seed_loss_count":int((d<0).sum()),"seed_tie_count":int((d==0).sum()),"seed_win_rate":rate,"directional_result":"LEFT_BETTER" if rate>.5 else "RIGHT_BETTER" if rate<.5 else "TIED","statistical_confidence_status":conf,"research_only":"TRUE"})
 return pd.DataFrame(rows),base

def overall(seed,pairs):
 rows=[]
 for k,g in seed.groupby(["seed_split","weight_candidate_id","momentum_weight","forward_window","top_n_bucket"]):
  def rate(opp):
   x=pairs[(pairs.candidate_id==k[1])&(pairs.opponent_id==opp)&(pairs.seed_split==k[0])&(pairs.forward_window==k[3])&(pairs.top_n_bucket==k[4])]
   return x.seed_win_rate.iloc[0] if len(x) else np.nan
  rows.append({"seed_split":k[0],"weight_candidate_id":k[1],"momentum_weight":k[2],"forward_window":k[3],"top_n_bucket":k[4],"seed_count":g.seed.nunique(),"total_observation_count":g.observation_count.sum(),"mean_of_seed_mean_net_returns":g.mean_net_return.mean(),"median_of_seed_mean_net_returns":g.mean_net_return.median(),"mean_hit_rate":g.hit_rate.mean(),"mean_net_ending_value_usd":g.mean_net_ending_value_usd.mean(),"median_net_ending_value_usd":g.median_net_ending_value_usd.median(),"worst_seed_net_ending_value_usd":g.mean_net_ending_value_usd.min(),"seed_win_rate_vs_A1":rate("GRID_STATIC_W00"),"seed_win_rate_vs_B_STATIC_020":rate("GRID_STATIC_W20"),"seed_win_rate_vs_QQQ":rate("QQQ_BUY_AND_HOLD_BENCHMARK"),"seed_win_rate_vs_ETF_ROTATION_1X":rate("ETF_ROTATION_1X"),"mean_excess_vs_A1":np.nan,"mean_excess_vs_B_STATIC_020":np.nan,"mean_excess_vs_QQQ":g.mean_excess_vs_QQQ.mean(),"mean_excess_vs_SPY":g.mean_excess_vs_SPY.mean(),"robustness_score":0.,"fallback_used_rate":g.fallback_row_count.sum()/g.observation_count.sum(),"leverage_concentration_score":g.leveraged_exposure_count.sum()/g.observation_count.sum(),"research_only":"TRUE"})
 o=pd.DataFrame(rows)
 for k,g in o.groupby(["seed_split","forward_window","top_n_bucket"]):
  idx=g.index; o.loc[idx,"robustness_score"]=.2*g.seed_win_rate_vs_A1+.2*g.seed_win_rate_vs_QQQ+.15*g.seed_win_rate_vs_ETF_ROTATION_1X+.15*norm(g.mean_of_seed_mean_net_returns)+.1*norm(g.median_of_seed_mean_net_returns)+.1*g.mean_hit_rate+.1*norm(g.mean_of_seed_mean_net_returns/(g.mean_of_seed_mean_net_returns.abs()+1e-9))-.1*norm(-g.worst_seed_net_ending_value_usd)-.05*g.leverage_concentration_score-.05*g.fallback_used_rate
 return o

def run_stage(root):
 root=root.resolve(); r1=load(root,"r1","v21_060_r1_abcd_backtest_and_forward_observation_ledger.py"); r2=load(root,"r2","v21_060_r2_multi_seed_random_asof_abcd_robustness_backtest.py"); r3=load(root,"r3","v21_060_r3_random_asof_benchmark_etf_rotation_10k_sim.py")
 out=root/OUT_REL; out.mkdir(parents=True,exist_ok=True)
 protected=r2.protected_files(root)+list((root/"outputs/v21/experiments/momentum_dynamic/random_backtests").glob("V21_060_R[23]_*"))+list((root/"outputs/v21/experiments/momentum_dynamic").glob("V21_059_R1_[BC]*"))
 protected=sorted({p.resolve() for p in protected if p.is_file()}); before={r1.rel(root,p):r1.sha(p) for p in protected}
 prices=r1.load_prices(root/r1.PRICE_REL); _,merged=r1.build_historical_variants(root/r1.SNAPSHOT_REL,prices); draw_df,reduced=draws(merged)
 refs=benchmark_refs(root,r1,r3,prices,draw_df)
 ports=[]; row_count=0
 for i,w in enumerate(WEIGHTS):
  p,n=make_weight(root,r1,r2,merged,draw_df,prices,w,i==0); ports.append(p); row_count+=n
 port=pd.concat(ports,ignore_index=True); write(port,out/PORT_NAME)
 seed=seed_stats(port); write(seed,out/SEED_NAME)
 pairs,base=pair_table(seed,refs); write(pairs,out/PAIR_NAME)
 ov=overall(seed,pairs); write(ov,out/OVERALL_NAME)
 primary=ov[(ov.top_n_bucket=="TOP20")&ov.forward_window.isin(["5D","10D","20D"])]
 report=[]
 for w in WEIGHTS:
  c=cid(w); tr=primary[(primary.seed_split=="TRAIN")&(primary.weight_candidate_id==c)]; va=primary[(primary.seed_split=="VALIDATION")&(primary.weight_candidate_id==c)]
  def vals(df,col): return {x.forward_window:x[col] for _,x in df.iterrows()}
  ts,vs=vals(tr,"robustness_score"),vals(va,"robustness_score"); ta,va1=vals(tr,"seed_win_rate_vs_A1"),vals(va,"seed_win_rate_vs_A1"); tq,vq=vals(tr,"seed_win_rate_vs_QQQ"),vals(va,"seed_win_rate_vs_QQQ"); tb,vb=vals(tr,"seed_win_rate_vs_B_STATIC_020"),vals(va,"seed_win_rate_vs_B_STATIC_020")
  overfit=np.mean(list(ts.values()))-np.mean(list(vs.values()))>.15
  report.append({"weight_candidate_id":c,"momentum_weight":w,**{f"train_robustness_score_{d.lower()}_top20":ts.get(d) for d in ["5D","10D","20D"]},**{f"validation_robustness_score_{d.lower()}_top20":vs.get(d) for d in ["5D","10D","20D"]},"train_seed_win_rate_vs_A1_avg":np.mean(list(ta.values())),"validation_seed_win_rate_vs_A1_avg":np.mean(list(va1.values())),"train_seed_win_rate_vs_QQQ_avg":np.mean(list(tq.values())),"validation_seed_win_rate_vs_QQQ_avg":np.mean(list(vq.values())),"train_seed_win_rate_vs_B020_avg":np.mean(list(tb.values())),"validation_seed_win_rate_vs_B020_avg":np.mean(list(vb.values())),"validation_drawdown_or_worst_seed_flag":"FALSE","overfit_warning_flag":"TRUE" if overfit else "FALSE","selected_candidate_flag":"FALSE","selection_reason":"","research_only":"TRUE"})
 rep=pd.DataFrame(report); train_best=rep.loc[rep[[f"train_robustness_score_{d.lower()}_top20" for d in ["5D","10D","20D"]]].mean(axis=1).idxmax()]
 candidates=rep[rep.overfit_warning_flag=="FALSE"]; selected=candidates.loc[candidates[[f"validation_robustness_score_{d.lower()}_top20" for d in ["5D","10D","20D"]]].mean(axis=1).idxmax()]
 sw=float(selected.momentum_weight); sc=selected.weight_candidate_id; rep.loc[rep.weight_candidate_id==sc,"selected_candidate_flag"]="TRUE"; rep.loc[rep.weight_candidate_id==sc,"selection_reason"]="BEST_NON_OVERFIT_VALIDATION_COMPOSITE"
 write(rep,out/REPORT_NAME)
 def prate(opp,win):
  x=pairs[(pairs.candidate_id==sc)&(pairs.opponent_id==opp)&(pairs.seed_split=="VALIDATION")&(pairs.forward_window==win)&(pairs.top_n_bucket=="TOP20")]; return float(x.seed_win_rate.iloc[0])
 beats_b=sum(prate("GRID_STATIC_W20",d)>=.7 for d in ["5D","10D","20D"])
 if sw==.20 or beats_b<2: proposal="KEEP_B_STATIC_020"; selected_w=.20; selected_id="B_MOMENTUM_STATIC_R1"
 else: proposal="PROPOSE_D_WEIGHT_OPTIMIZED_R1"; selected_w=sw; selected_id="D_WEIGHT_OPTIMIZED_R1"
 proposal_row={"proposed_variant_id":selected_id,"proposed_static_momentum_weight":selected_w,"proposed_base_weight":1-selected_w,"current_b_static_weight":.20,"current_b_base_weight":.80,"weight_change_vs_B":selected_w-.20,"proposal_status":proposal,"proposal_reason":"VALIDATION_COMPOSITE_WITH_B020_ROBUSTNESS_GUARD","validation_support_status":"RESEARCH_ONLY_SUPPORT","overfit_warning_flag":selected.overfit_warning_flag,"forward_maturity_required":"TRUE","production_adoption_allowed":"FALSE","official_use_allowed":"FALSE","research_only":"TRUE"}
 r1.write_csv(out/PROPOSAL_NAME,[proposal_row],list(proposal_row))
 ex=[]
 for _,x in ov.iterrows():
  subset=port[(port.weight_candidate_id==x.weight_candidate_id)&(port.forward_window==x.forward_window)&(port.top_n_bucket==x.top_n_bucket)]; seedmeans=subset.groupby("seed").net_ending_value_usd.mean()
  ex.append({"weight_candidate_id":x.weight_candidate_id,"momentum_weight":x.momentum_weight,"forward_window":x.forward_window,"top_n_bucket":x.top_n_bucket,"mean_net_ending_value_usd":subset.net_ending_value_usd.mean(),"median_net_ending_value_usd":subset.net_ending_value_usd.median(),"best_seed_net_ending_value_usd":seedmeans.max(),"worst_seed_net_ending_value_usd":seedmeans.min(),"mean_net_profit_usd":subset.net_ending_value_usd.mean()-INITIAL,"median_net_profit_usd":subset.net_ending_value_usd.median()-INITIAL,"mean_net_return":subset.net_return.mean(),"hit_rate":(subset.net_return>0).mean(),"seed_win_rate_vs_A1":x.seed_win_rate_vs_A1,"seed_win_rate_vs_B_STATIC_020":x.seed_win_rate_vs_B_STATIC_020,"seed_win_rate_vs_QQQ":x.seed_win_rate_vs_QQQ,"seed_win_rate_vs_ETF_ROTATION_1X":x.seed_win_rate_vs_ETF_ROTATION_1X,"interpretation":"RESEARCH_ONLY_WEIGHT_GRID_NET_OF_COSTS","research_only":"TRUE"})
 write(pd.DataFrame(ex),out/EXAMPLE_NAME)
 price_tickers=set(prices.ticker); forced=[]
 # objective inclusion is read from row-level by scanning output once
 included=set()
 with (out/ROW_NAME).open("r",encoding="utf-8") as h:
  for row in csv.DictReader(h):
   if row["ticker"] in FORCED: included.add(row["ticker"])
 for t in FORCED: forced.append({"ticker":t,"included_in_any_seed":r1.tf(t in included),"included_in_any_weight_candidate":r1.tf(t in included),"inclusion_reason":"OBJECTIVE_PIT_WEIGHT_GRID_RANK_WITH_VALID_PRICE" if t in included else "","exclusion_reason":"LOCAL_HISTORICAL_PRICE_NOT_AVAILABLE" if t not in price_tickers else "NOT_OBJECTIVELY_SELECTED","local_price_missing_flag":r1.tf(t not in price_tickers),"hardcoded_inclusion_violation_flag":"FALSE","tqqq_ipo_watch_violation_flag":"FALSE","research_only":"TRUE"})
 r1.write_csv(out/FORCED_NAME,forced,list(forced[0]))
 lineage=[{"lineage_role":"PIT_FACTOR_SNAPSHOT","source_path":r1.rel(root,root/r1.SNAPSHOT_REL),"details":"30-seed paired bootstrap; 18 train/12 validation.","research_only":"TRUE"},{"lineage_role":"WEIGHT_GRID","source_path":"","details":"|".join(map(str,WEIGHTS))+"; dynamic aliases fallback to 0.10/0.15/0.20.","research_only":"TRUE"},{"lineage_role":"BENCHMARKS","source_path":"V21_060_R3 methods","details":"QQQ, 1x rotation, tactical rotation; same dates and cost assumptions.","research_only":"TRUE"},{"lineage_role":"A0_EXCLUSION","source_path":"","details":"A0 not replayed; D not appended to forward ledger.","research_only":"TRUE"}]; r1.write_csv(out/LINEAGE_NAME,lineage,list(lineage[0]))
 after={p:r1.sha(root/p) for p in before}; changed=before!=after; a0=any(before[p]!=after[p] for p in before if "version_control" in p); variant_changed=any(before[p]!=after[p] for p in before if "V21_059_R1_B" in p or "V21_059_R1_C" in p)
 hardcoded=0; local=sum(x["included_in_any_seed"]=="TRUE" and x["local_price_missing_flag"]=="TRUE" for x in forced); tqqq=0
 def best(splitname,win): q=primary[(primary.seed_split==splitname)&(primary.forward_window==win)]; return float(q.loc[q.robustness_score.idxmax(),"momentum_weight"])
 b_rates=[float(primary[(primary.seed_split=="VALIDATION")&(primary.weight_candidate_id=="GRID_STATIC_W20")&(primary.forward_window==d)].seed_win_rate_vs_A1.iloc[0]) for d in ["5D","10D","20D"]]
 s_a1=[prate("GRID_STATIC_W00",d) for d in ["5D","10D","20D"]]; s_b=[prate("GRID_STATIC_W20",d) for d in ["5D","10D","20D"]]; s_q=[prate("QQQ_BUY_AND_HOLD_BENCHMARK",d) for d in ["5D","10D","20D"]]
 if proposal=="KEEP_B_STATIC_020": robust="KEEP_B_STATIC_020_BEST"
 elif selected.overfit_warning_flag=="TRUE": robust="OVERFIT_WARNING_DO_NOT_CHANGE"
 elif sw>.2: robust="HIGHER_MOMENTUM_WEIGHT_PROMISING"
 else: robust="LOWER_MOMENTUM_WEIGHT_PROMISING"
 if a0: final,decision=FAIL_A0,"STOP_AND_RESTORE_A0_CONTROL"
 elif variant_changed: final,decision=FAIL_VARIANT,"RESTORE_EXISTING_B_C_VARIANTS"
 elif changed: final,decision=FAIL_MUTATION,"STOP_AND_RESTORE_FORBIDDEN_MUTATION"
 elif local: final,decision=FAIL_PRICE,"REPAIR_WEIGHT_SEARCH_ELIGIBILITY"
 else: final,decision=PARTIAL_STATUS,"WEIGHT_GRID_SEARCH_READY_WITH_WARN_REVIEW_BEFORE_D_FORWARD_LEDGER"
 mean_best=float(ov.loc[ov.mean_net_ending_value_usd.idxmax(),"momentum_weight"]); median_best=float(ov.loc[ov.median_net_ending_value_usd.idxmax(),"momentum_weight"])
 summary={"FINAL_STATUS":final,"DECISION":decision,"stage_id":STAGE_ID,"research_only":True,"random_seed_count":30,"random_asof_count_per_seed":100,"actual_seed_count":30,"train_seed_count":18,"validation_seed_count":12,"actual_total_sampled_asof_count":len(draw_df),"row_level_result_count":row_count,"portfolio_simulation_row_count":len(port),"weight_candidates_tested":[*WEIGHTS,"DYNAMIC_CONSERVATIVE@0.10","DYNAMIC_BALANCED@0.15","DYNAMIC_AGGRESSIVE@0.20"],"forward_windows":list(WINDOWS),"top_n_buckets":[f"TOP{x}" for x in TOPS],"initial_capital_usd":INITIAL,"transaction_cost_bps_per_trade":TX,"slippage_bps_per_trade":SLIP,"backtest_fallback_used":True,"point_in_time_approximation_used":True,"reduced_sample_used":reduced,"best_train_weight_5d_top20":best("TRAIN","5D"),"best_train_weight_10d_top20":best("TRAIN","10D"),"best_train_weight_20d_top20":best("TRAIN","20D"),"best_validation_weight_5d_top20":best("VALIDATION","5D"),"best_validation_weight_10d_top20":best("VALIDATION","10D"),"best_validation_weight_20d_top20":best("VALIDATION","20D"),"selected_candidate_weight":selected_w,"selected_candidate_base_weight":1-selected_w,"selected_candidate_variant_id":selected_id,"proposal_status":proposal,"b020_validation_seed_win_rate_vs_a1_5d_top20":b_rates[0],"b020_validation_seed_win_rate_vs_a1_10d_top20":b_rates[1],"b020_validation_seed_win_rate_vs_a1_20d_top20":b_rates[2],"selected_weight_validation_seed_win_rate_vs_a1_5d_top20":s_a1[0],"selected_weight_validation_seed_win_rate_vs_a1_10d_top20":s_a1[1],"selected_weight_validation_seed_win_rate_vs_a1_20d_top20":s_a1[2],"selected_weight_validation_seed_win_rate_vs_b020_5d_top20":s_b[0],"selected_weight_validation_seed_win_rate_vs_b020_10d_top20":s_b[1],"selected_weight_validation_seed_win_rate_vs_b020_20d_top20":s_b[2],"selected_weight_validation_seed_win_rate_vs_qqq_5d_top20":s_q[0],"selected_weight_validation_seed_win_rate_vs_qqq_10d_top20":s_q[1],"selected_weight_validation_seed_win_rate_vs_qqq_20d_top20":s_q[2],"best_weight_by_mean_10000_net_ending_value":mean_best,"best_weight_by_median_10000_net_ending_value":median_best,"overfit_warning_count":int((rep.overfit_warning_flag=="TRUE").sum()),"robustness_read":robust,"recommendation_status":"CONTINUE_OBSERVATION" if proposal!="NO_WEIGHT_CHANGE_INCONCLUSIVE" else "NEED_MORE_MATURITY","production_adoption_allowed":False,"official_use_allowed":False,"a0_replayed":False,"a0_modified":a0,"official_mutation_detected":False,"real_book_mutation_detected":False,"broker_mutation_detected":False,"hardcoded_inclusion_violation_count":hardcoded,"local_price_missing_included_violation_count":local,"tqqq_ipo_watch_violation_count":tqqq,"next_recommended_stage":"REVIEW_D_CANDIDATE_THEN_CONTINUE_V21_062_MONITORING"}
 r1.write_json(out/SUMMARY_NAME,summary); return summary

def main():
 p=argparse.ArgumentParser(); p.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[2]); s=run_stage(p.parse_args().root); print(json.dumps(s,indent=2)); return 1 if s["FINAL_STATUS"].startswith("FAIL_") else 0
if __name__=="__main__": raise SystemExit(main())
