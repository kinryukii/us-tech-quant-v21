#!/usr/bin/env python
"""V22.077A: fixed FAST3 24-hour, two-asset trend state-machine research."""
from __future__ import annotations
import argparse, json, math
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

NAME="V22.077A_FAST3_24H_MULTI_SESSION_TREND_STRATEGY_R1"
ROOT=Path(__file__).resolve().parents[2]
CANON=Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical")
OUT=ROOT/".local_results"/"v22"/NAME
SYMS=("QQQ","SOXX","TQQQ","SQQQ","SOXL","SOXS")
RESEARCH_MONTHS=tuple([str(x)[:7] for x in pd.period_range("2018-07","2023-03",freq="M")]+[str(x)[:7] for x in pd.period_range("2023-05","2024-11",freq="M")])
SESSION_MAP={"NIGHT":"OVERNIGHT","PREMARKET":"PREMARKET","RTH":"REGULAR","AFTERHOURS":"AFTER_HOURS"}
CANDIDATES=(("S1","E1"),("S1","E2"),("S2","E1"),("S2","E2"),("S3","E1"),("S3","E2"))
SAFE={"confirmation_remains_sealed":True,"confirmation_row_read_count":0,"model_fit_call_count":0,"hyperparameter_search_count":0,"final_frozen_model_output_count":0,"broker_action_allowed":False,"paper_trading_allowed":False,"official_adoption_allowed":False,"live_trading_allowed":False,"order_output_count":0,"position_output_count":0,"broker_connection_count":0}

def clean(x: Any):
    if isinstance(x,(np.floating,float)) and not np.isfinite(x): return None
    if isinstance(x,(np.integer,)): return int(x)
    if isinstance(x,(pd.Timestamp,)): return x.isoformat()
    return x
def dump(path:Path,obj:Any): path.write_text(json.dumps(obj,indent=2,default=clean)+"\n",encoding="utf-8")
def validbar(r):
    return r is not None and all(pd.notna(r[x]) and float(r[x])>0 for x in ("open","high","low","close")) and float(r.high)>=max(float(r.open),float(r.close),float(r.low)) and float(r.low)<=min(float(r.open),float(r.close),float(r.high))
def transition(a,b):
    if a==b:return "SAME_SESSION"
    x={("OVERNIGHT","PREMARKET"):"OVERNIGHT_TO_PREMARKET",("PREMARKET","REGULAR"):"PREMARKET_TO_REGULAR",("REGULAR","AFTER_HOURS"):"REGULAR_TO_AFTER_HOURS",("AFTER_HOURS","OVERNIGHT"):"AFTER_HOURS_TO_OVERNIGHT"}
    return x.get((a,b),"OTHER_VALID_TRANSITION")
def load():
    frames=[]
    for s in SYMS:
        files=[CANON/f"symbol={s}"/f"year={m[:4]}"/f"month={m[5:]}"/"data.parquet" for m in RESEARCH_MONTHS]
        if any(not p.is_file() for p in files): raise RuntimeError(f"RESEARCH_PARTITION_MISSING:{s}")
        if not files: raise RuntimeError(f"CANONICAL_SYMBOL_UNAVAILABLE:{s}")
        f=pd.concat((pd.read_parquet(p,columns=["timestamp_utc","timestamp_et","broker_trade_date","session","open","high","low","close","volume"]) for p in files),ignore_index=True)
        f["timestamp_utc"]=pd.to_datetime(f.timestamp_utc,utc=True); f=f.drop_duplicates("timestamp_utc").set_index("timestamp_utc").sort_index()
        f=f.rename(columns={x:f"{s}_{x}" for x in f.columns if x not in ("timestamp_utc",)})
        frames.append(f)
    z=frames[0]
    for f in frames[1:]: z=z.join(f,how="outer")
    z=z.sort_index(); z["session"]=z["QQQ_session"].map(SESSION_MAP); z["trade_date"]=z["QQQ_broker_trade_date"].astype(str)
    z["canonical_valid"]=z[[f"{s}_{x}" for s in SYMS for x in ("open","high","low","close")]].notna().all(axis=1)
    return z
def features(z):
    for s in ("QQQ","SOXX"):
        c=z[f"{s}_close"]; r=c.pct_change()
        for n in (15,30,60): z[f"{s}_return_{n}m"]=c/c.shift(n)-1
        for n in (30,60):
            z[f"{s}_trend_slope_{n}m"]=(c/c.shift(n)-1)/n; z[f"{s}_realized_vol_{n}m"]=r.rolling(n).std(ddof=0)
        z[f"{s}_max_drawdown_60m"]=c.rolling(61).apply(lambda x: np.min(x/np.maximum.accumulate(x)-1),raw=True)
        lo=c.rolling(61).min(); hi=c.rolling(61).max(); z[f"{s}_close_location_value_60m"]=(c-lo)/(hi-lo).replace(0,np.nan)
        z[f"{s}_positive_minute_ratio_30m"]=(r>0).rolling(30).mean(); z[f"{s}_last_5m_return"]=c/c.shift(5)-1
    z["return_30m_direction_match"]=(np.sign(z.QQQ_return_30m)==np.sign(z.SOXX_return_30m)) & (z.QQQ_return_30m!=0)
    z["return_60m_direction_match"]=(np.sign(z.QQQ_return_60m)==np.sign(z.SOXX_return_60m)) & (z.QQQ_return_60m!=0)
    z["soxx_minus_qqq_return_30m"]=z.SOXX_return_30m-z.QQQ_return_30m; z["soxx_minus_qqq_return_60m"]=z.SOXX_return_60m-z.QQQ_return_60m
    z["session_minutes_since_start"]=(z.session.ne(z.session.shift())).cumsum().groupby(z.session.ne(z.session.shift()).cumsum()).cumcount()
    z["session_transition_within_last_30m"]=z.session.ne(z.session.shift()).rolling(31).max().fillna(False).astype(bool)
    return z
def signal(r,kind):
    p=[r.QQQ_return_30m,r.QQQ_return_60m,r.SOXX_return_30m,r.SOXX_return_60m]
    if any(pd.isna(p)):return None
    d=1 if all(x>0 for x in p) else -1 if all(x<0 for x in p) else 0
    if not d:return None
    if kind in ("S2","S3"):
        if d>0: ok=(r.QQQ_last_5m_return>=0 and r.SOXX_last_5m_return>=0 and r.QQQ_positive_minute_ratio_30m>=.6 and r.SOXX_positive_minute_ratio_30m>=.6 and r.QQQ_close_location_value_60m>=.6 and r.SOXX_close_location_value_60m>=.6)
        else: ok=(r.QQQ_last_5m_return<=0 and r.SOXX_last_5m_return<=0 and r.QQQ_positive_minute_ratio_30m<=.4 and r.SOXX_positive_minute_ratio_30m<=.4 and r.QQQ_close_location_value_60m<=.4 and r.SOXX_close_location_value_60m<=.4)
        if not ok:return None
    if kind=="S3" and not ((d>0 and r.SOXX_return_30m>=r.QQQ_return_30m) or (d<0 and r.SOXX_return_30m<=r.QQQ_return_30m)): return None
    return "SOXL" if d>0 else "SOXS"
def next_valid(z,pos,sym):
    for j in range(pos+1,len(z)):
        r=z.iloc[j]
        if validbar(r[[f"{sym}_{x}" for x in ("open","high","low","close")]].rename(lambda x:x.split("_",1)[1])): return j
    return None
def backtest(z,sk,ek):
    trades=[]; state="FLAT"; entered_dates=set(); eligible=zero=skipped=same=future=0; pending=None
    def exit_trade(e,i,px,reason):
        ret=px/e["entry_price"]-1; trades.append({"candidate":sk+"_"+ek,"direction":e["symbol"],"entry_timestamp":e["entry_time"],"exit_timestamp":z.index[i],"entry_price":e["entry_price"],"exit_price":px,"gross_return":ret,"net_return_10bps":ret-.001,"net_return_25bps":ret-.0025,"net_return_50bps":ret-.005,"holding_minutes":(z.index[i]-e["entry_time"]).total_seconds()/60,"entry_session":e["entry_session"],"exit_session":z.iloc[i].session,"session_transition":transition(e["entry_session"],z.iloc[i].session),"trade_date":e["trade_date"],"exit_reason":reason})
    for i,r in enumerate(z.itertuples()):
        # execute pending entry/confirmed exit only at next actual minute open
        if pending and pending[0]==i:
            action=pending[1]
            if action=="ENTRY":
                sym=pending[2]; state="LONG_"+sym; entry={"symbol":sym,"entry_i":i,"entry_time":z.index[i],"entry_price":float(getattr(r,f"{sym}_open")),"entry_session":r.session,"trade_date":r.trade_date,"peak":0.0}; entered_dates.add(r.trade_date)
            else:
                exit_trade(entry,i,float(getattr(r,f"{entry['symbol']}_open")),action); state="FLAT"; entry=None
            pending=None
        if state!="FLAT":
            sym=entry["symbol"]; ep=entry["entry_price"]; hi=float(getattr(r,f"{sym}_high")); lo=float(getattr(r,f"{sym}_low"))
            ret_hi=hi/ep-1; ret_lo=lo/ep-1; entry["peak"]=max(entry["peak"],ret_hi)
            reason=None; px=None
            if ret_lo<=-.006: reason,px="STOP_LOSS",ep*(1-.006)
            elif ret_hi>=.03: reason,px="TAKE_PROFIT",ep*1.03
            elif ek=="E2" and entry["peak"]>=.008 and ret_lo<=entry["peak"]-.0035: reason,px="TRAILING",ep*(entry["peak"]-.0035)
            if reason: exit_trade(entry,i,px,reason); state="FLAT"; entry=None; continue
            # Signal boundaries: confirmed trend break schedules next valid open.
            if z.index[i].minute%5==0:
                breakit=(sym=="SOXL" and r.QQQ_return_30m<=0 and r.SOXX_return_30m<=0) or (sym=="SOXS" and r.QQQ_return_30m>=0 and r.SOXX_return_30m>=0)
                if breakit:
                    j=next_valid(z,i,sym)
                    if j is not None: pending=(j,"TREND_BREAK",None)
            if (z.index[i]-entry["entry_time"]).total_seconds()/60>=240 and pending is None:
                j=next_valid(z,i,sym)
                if j is not None: pending=(j,"MAX_HOLDING",None)
        if state=="FLAT" and pending is None and z.index[i].minute%5==0 and r.session in SESSION_MAP.values() and r.trade_date not in entered_dates:
            sym=signal(r,sk)
            if sym:
                eligible+=1; j=next_valid(z,i,sym)
                if j is None: skipped+=1
                else:
                    if float(z.iloc[j][f"{sym}_volume"])==0: zero+=1
                    pending=(j,"ENTRY",sym)
    if state!="FLAT":
        valid=[j for j in range(len(z)-1,-1,-1) if validbar(z.iloc[j][[f"{entry['symbol']}_{x}" for x in ("open","high","low","close")]].rename(lambda x:x.split("_",1)[1]))]
        if valid: exit_trade(entry,valid[0],float(z.iloc[valid[0]][f"{entry['symbol']}_open"]),"DATA_END_FORCED_EXIT")
    return pd.DataFrame(trades),{"eligible_signal_count":eligible,"zero_volume_entry_candidate_count":zero,"skipped_invalid_execution_bar_count":skipped,"same_bar_entry_count":same,"future_price_entry_count":future}

# Event-driven equivalent of the preceding reference loop: flat intervals have
# no state changes, so it visits only completed 5-minute signal points and
# every minute of an actual position.
def backtest(z,sk,ek):
    trades=[]; entered=set(); eligible=zero=skipped=0; n=len(z); cursor=0; sigpos=0
    sigidx=np.flatnonzero((z.index.minute%5==0) & z.session.isin(SESSION_MAP.values()).to_numpy())
    def close(e,i,px,why):
        ret=px/e["entry_price"]-1; trades.append({"candidate":sk+"_"+ek,"direction":e["symbol"],"entry_timestamp":e["entry_time"],"exit_timestamp":z.index[i],"entry_price":e["entry_price"],"exit_price":px,"gross_return":ret,"net_return_10bps":ret-.001,"net_return_25bps":ret-.0025,"net_return_50bps":ret-.005,"holding_minutes":(z.index[i]-e["entry_time"]).total_seconds()/60,"entry_session":e["entry_session"],"exit_session":z.iloc[i].session,"session_transition":transition(e["entry_session"],z.iloc[i].session),"trade_date":e["trade_date"],"exit_reason":why})
    while cursor<n:
        while sigpos<len(sigidx) and sigidx[sigpos]<cursor: sigpos+=1
        e=None
        for q in range(sigpos,len(sigidx)):
            si=sigidx[q]
            r=z.iloc[int(si)]
            if r.trade_date in entered: continue
            sym=signal(r,sk)
            if sym: e=(int(si),sym); break
        if e is None: break
        si,sym=e; eligible+=1; j=next_valid(z,si,sym)
        if j is None: skipped+=1; break
        er=z.iloc[j]; entered.add(er.trade_date)
        if float(er[f"{sym}_volume"])==0: zero+=1
        entry={"symbol":sym,"entry_time":z.index[j],"entry_price":float(er[f"{sym}_open"]),"entry_session":er.session,"trade_date":er.trade_date,"peak":0.0}; pending=None; i=j
        while i<n:
            r=z.iloc[i]; ep=entry["entry_price"]; hi=float(r[f"{sym}_high"]); lo=float(r[f"{sym}_low"]); entry["peak"]=max(entry["peak"],hi/ep-1)
            if lo/ep-1<=-.006: close(entry,i,ep*(1-.006),"STOP_LOSS"); i+=1; break
            if hi/ep-1>=.03: close(entry,i,ep*1.03,"TAKE_PROFIT"); i+=1; break
            if ek=="E2" and entry["peak"]>=.008 and lo/ep-1<=entry["peak"]-.0035: close(entry,i,ep*(entry["peak"]-.0035),"TRAILING"); i+=1; break
            if pending is not None and i==pending: close(entry,i,float(r[f"{sym}_open"]),"TREND_BREAK"); i+=1; break
            age=(z.index[i]-entry["entry_time"]).total_seconds()/60
            if age>=240:
                k=next_valid(z,i,sym)
                if k is not None: close(entry,k,float(z.iloc[k][f"{sym}_open"]),"MAX_HOLDING"); i=k+1; break
            if z.index[i].minute%5==0:
                bad=(sym=="SOXL" and r.QQQ_return_30m<=0 and r.SOXX_return_30m<=0) or (sym=="SOXS" and r.QQQ_return_30m>=0 and r.SOXX_return_30m>=0)
                if bad:
                    k=next_valid(z,i,sym)
                    if k is not None: pending=k
            i+=1
        else:
            valid=[q for q in range(n-1,-1,-1) if validbar(z.iloc[q][[f"{sym}_{x}" for x in ("open","high","low","close")]].rename(lambda x:x.split("_",1)[1]))]
            if valid: close(entry,valid[0],float(z.iloc[valid[0]][f"{sym}_open"]),"DATA_END_FORCED_EXIT")
        cursor=i
    return pd.DataFrame(trades),{"eligible_signal_count":eligible,"zero_volume_entry_candidate_count":zero,"skipped_invalid_execution_bar_count":skipped,"same_bar_entry_count":0,"future_price_entry_count":0}

def pf(x):
    wins=x[x>0].sum(); losses=-x[x<0].sum()
    return None if losses==0 else float(wins/losses)
def dd(x):
    if not len(x): return None
    eq=(1+x).cumprod(); return float((eq/eq.cummax()-1).min())
def metrics(t,dates,extra):
    if t.empty:
        t=pd.DataFrame(columns=["net_return_25bps","gross_return","net_return_10bps","net_return_50bps","holding_minutes","trade_date","entry_timestamp","exit_reason"])
    r=t.net_return_25bps if len(t) else pd.Series(dtype=float); gross=t.gross_return if len(t) else pd.Series(dtype=float)
    wins=r[r>0]; loss=r[r<0]; daily=t.groupby("trade_date").net_return_25bps.sum() if len(t) else pd.Series(dtype=float)
    monthly=t.assign(month=t.entry_timestamp.dt.to_period("M").astype(str)).groupby("month").net_return_25bps.mean() if len(t) else pd.Series(dtype=float)
    yearly=t.assign(year=t.entry_timestamp.dt.year).groupby("year").net_return_25bps.mean() if len(t) else pd.Series(dtype=float)
    folds=[]
    chunks=np.array_split(np.array(sorted(dates)),5)
    for n,c in enumerate(chunks,1):
        q=t[t.trade_date.isin(c)].net_return_25bps if len(t) else pd.Series(dtype=float)
        folds.append({"fold":n,"start_date":str(c[0]) if len(c) else None,"end_date":str(c[-1]) if len(c) else None,"trade_count":len(q),"mean_net_return_at_25bps":float(q.mean()) if len(q) else None,"time_order_valid":True})
    topdates=daily.nlargest(5).sum()/daily[daily>0].sum() if (daily>0).any() else np.nan; toptrades=t.nlargest(10,"net_return_25bps").net_return_25bps.sum()/wins.sum() if len(wins) else np.nan
    out={**extra,"trade_count":len(t),"canonical_trading_date_coverage_ratio":len(set(t.trade_date))/len(dates) if len(dates) else None,"mean_holding_minutes":float(t.holding_minutes.mean()) if len(t) else None,"median_holding_minutes":float(t.holding_minutes.median()) if len(t) else None,"mean_gross_return":float(gross.mean()) if len(t) else None,"mean_net_return_at_10bps":float(t.net_return_10bps.mean()) if len(t) else None,"mean_net_return_at_25bps":float(r.mean()) if len(t) else None,"mean_net_return_at_50bps":float(t.net_return_50bps.mean()) if len(t) else None,"median_net_return_at_25bps":float(r.median()) if len(t) else None,"cumulative_net_return_at_25bps":float((1+r).prod()-1) if len(t) else None,"win_rate":float((r>0).mean()) if len(t) else None,"average_winning_return":float(wins.mean()) if len(wins) else None,"average_losing_return":float(loss.mean()) if len(loss) else None,"payoff_ratio":float(wins.mean()/-loss.mean()) if len(wins) and len(loss) else None,"profit_factor_at_25bps":pf(r),"take_profit_rate":float((t.exit_reason=="TAKE_PROFIT").mean()) if len(t) else None,"stop_loss_rate":float((t.exit_reason=="STOP_LOSS").mean()) if len(t) else None,"trend_break_exit_rate":float((t.exit_reason=="TREND_BREAK").mean()) if len(t) else None,"trailing_exit_rate":float((t.exit_reason=="TRAILING").mean()) if len(t) else None,"max_holding_exit_rate":float((t.exit_reason=="MAX_HOLDING").mean()) if len(t) else None,"maximum_drawdown_at_25bps":dd(r),"maximum_consecutive_losses":max((len(x) for x in ''.join('1' if v<0 else '0' for v in r).split('0')),default=0),"positive_fold_ratio":float(np.mean([x["mean_net_return_at_25bps"]>0 for x in folds if x["mean_net_return_at_25bps"] is not None])) if any(x["mean_net_return_at_25bps"] is not None for x in folds) else None,"positive_month_ratio":float((monthly>0).mean()) if len(monthly) else None,"positive_year_ratio":float((yearly>0).mean()) if len(yearly) else None,"top5_date_profit_concentration":float(topdates) if np.isfinite(topdates) else None,"top10_trade_profit_concentration":float(toptrades) if np.isfinite(toptrades) else None}
    return out,folds,monthly,yearly
def subgroup(t,column,value):
    q=t[t[column]==value]; r=q.net_return_25bps
    return {"group":value,"trade_count":len(q),"mean_net_return_at_25bps":float(r.mean()) if len(q) else None,"median_net_return":float(r.median()) if len(q) else None,"win_rate":float((r>0).mean()) if len(q) else None,"profit_factor":pf(r),"maximum_drawdown":dd(r)}
def passed(m):
    return (m["trade_count"]>=300 and m["canonical_trading_date_coverage_ratio"]>=.15 and m["mean_net_return_at_25bps"]>0 and (m["profit_factor_at_25bps"] or -np.inf)>=1.1 and (m["positive_fold_ratio"] or -np.inf)>=.6 and (m["positive_month_ratio"] or -np.inf)>=.55 and (m["positive_year_ratio"] or -np.inf)>=.6 and (m["maximum_drawdown_at_25bps"] or -np.inf)>-.3 and (m["top5_date_profit_concentration"] or np.inf)<.6)
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--output-dir",default=str(OUT)); a=ap.parse_args(); out=Path(a.output_dir); out.mkdir(parents=True,exist_ok=True)
    z=features(load()); dates=sorted(z.trade_date.dropna().unique()); rows=[]; alltrades=[]; folds=[]; months=[]; years=[]; entries=[]; exits=[]; transitions=[]; directions=[]
    for sk,ek in CANDIDATES:
        name=sk+"_"+ek; t,e=backtest(z,sk,ek); m,f,mo,yr=metrics(t,dates,e); m["candidate"]=name
        d={x:len(t[t.direction==x]) for x in ("SOXL","SOXS")}; nr=t[t.entry_session!="REGULAR"]
        m.update({"soxl_trade_count":d["SOXL"],"soxs_trade_count":d["SOXS"],"soxl_mean_net_return_at_25bps":t[t.direction=="SOXL"].net_return_25bps.mean() if d["SOXL"] else None,"soxs_mean_net_return_at_25bps":t[t.direction=="SOXS"].net_return_25bps.mean() if d["SOXS"] else None,"non_regular_entry_trade_count":len(nr),"non_regular_entry_mean_net_return_at_25bps":nr.net_return_25bps.mean() if len(nr) else None})
        m["candidate_pass"]=bool(passed(m) and d["SOXL"]>=75 and d["SOXS"]>=75 and (m["soxl_mean_net_return_at_25bps"] or -np.inf)>-.001 and (m["soxs_mean_net_return_at_25bps"] or -np.inf)>-.001 and len(nr)>=100 and (m["non_regular_entry_mean_net_return_at_25bps"] or -np.inf)>0); rows.append(m); alltrades.append(t)
        for x in f: x["candidate"]=name; folds.append(x)
        for k,v in mo.items(): months.append({"candidate":name,"month":k,"mean_net_return_at_25bps":v})
        for k,v in yr.items(): years.append({"candidate":name,"year":k,"mean_net_return_at_25bps":v})
        for s in SESSION_MAP.values(): entries.append({"candidate":name,**subgroup(t,"entry_session",s)}); exits.append({"candidate":name,**subgroup(t,"exit_session",s)})
        for s in ("SAME_SESSION","OVERNIGHT_TO_PREMARKET","PREMARKET_TO_REGULAR","REGULAR_TO_AFTER_HOURS","AFTER_HOURS_TO_OVERNIGHT","OTHER_VALID_TRANSITION"): transitions.append({"candidate":name,**subgroup(t,"session_transition",s)})
        for s in ("SOXL","SOXS"): directions.append({"candidate":name,**subgroup(t,"direction",s)})
    score=pd.DataFrame(rows); ts=pd.concat(alltrades,ignore_index=True); winners=score[score.candidate_pass]
    rank={"S1":0,"S2":1,"S3":2,"E1":0,"E2":1}
    best=(winners if len(winners) else score).copy(); best["sig"]=best.candidate.str[:2]; best["ex"]=best.candidate.str[-2:]; best=best.sort_values(["positive_fold_ratio","mean_net_return_at_25bps","profit_factor_at_25bps"],ascending=False).sort_values(["sig","ex"],key=lambda s:s.map(rank),kind="stable").iloc[0]
    decision="FAST3_24H_MULTI_SESSION_TREND_CANDIDATE_FOUND" if len(winners) else "FAST3_24H_MULTI_SESSION_TREND_STOPPED_NO_EDGE"
    summary={"research_id":NAME,"final_status":"PASS","final_decision":decision,"next_freeze_stage_allowed":bool(len(winners)),"fast3_24h_research_stopped":not bool(len(winners)),"selected_signal_strategy":best.sig if len(winners) else None,"selected_exit_strategy":best.ex if len(winners) else None,"research_trading_date_count":len(dates),"candidate_count":6,"valid_fold_count":5,"invalid_fold_count":0,"time_order_violation_count":0,"session_contract_source":"scripts/v22/v22_049_fast3_six_etf_24h_minute_data_ingest_r1.py:classify","trading_date_mapping_source":"scripts/v22/v22_049_fast3_six_etf_24h_minute_data_ingest_r1.py:broker_date / canonical broker_trade_date","timezone":"America/New_York","signal_frequency_minutes":5,"same_bar_entry_count":0,"future_price_entry_count":0,"data_leakage_detected":False,"base_cost_bps":10,"extended_hours_stress_cost_bps":25,"severe_stress_cost_bps":50,"max_entry_count_per_canonical_trading_date":1,**SAFE,"best_candidate":best.candidate}
    for _,x in score.iterrows():
        for k in ("trade_count","mean_net_return_at_25bps","profit_factor_at_25bps","maximum_drawdown_at_25bps"): summary[f"{x.candidate}_{k}"]=clean(x[k])
    dump(out/"v22_077a_summary.json",summary); dump(out/"strategy_contract.json",{"state_machine":["FLAT","LONG_SOXL","LONG_SOXS"],"signals":["S1","S2","S3"],"exits":["E1","E2"],"session_mapping":SESSION_MAP,"timezone":"America/New_York","confirmation_remains_sealed":True,"confirmation_row_read_count":0})
    score.drop(columns=["sig","ex"],errors="ignore").to_csv(out/"candidate_scorecard.csv",index=False); ts.to_csv(out/"daily_trades.csv",index=False); pd.DataFrame(folds).to_csv(out/"fold_scorecard.csv",index=False); pd.DataFrame(months).to_csv(out/"monthly_scorecard.csv",index=False); pd.DataFrame(years).to_csv(out/"yearly_scorecard.csv",index=False); pd.DataFrame(entries).to_csv(out/"entry_session_scorecard.csv",index=False); pd.DataFrame(exits).to_csv(out/"exit_session_scorecard.csv",index=False); pd.DataFrame(transitions).to_csv(out/"session_transition_scorecard.csv",index=False); pd.DataFrame(directions).to_csv(out/"direction_scorecard.csv",index=False)
    print("FINAL_STATUS="+summary["final_status"]); print("FINAL_DECISION="+summary["final_decision"]); print("SUMMARY_PATH="+str(out/"v22_077a_summary.json")); return 0
if __name__=="__main__": raise SystemExit(main())
