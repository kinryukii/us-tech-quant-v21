#!/usr/bin/env python
"""V22.080B PIT predictability preflight; never loads Confirmation rows."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

NAME="V22.080B_FAST3_ONE_PERCENT_MOVE_PREDICTABILITY_PREFLIGHT_R1"
CANONICAL=Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical")
DEFAULT_OUT=Path(r"D:\us-tech-quant-results\v22")/NAME
DEV_END=pd.Timestamp("2023-06-30 23:59:59",tz="America/New_York")
VAL_START=pd.Timestamp("2023-07-08 00:00:00",tz="America/New_York")
VAL_END=pd.Timestamp("2025-01-31 23:59:59",tz="America/New_York")
CONF_START=pd.Timestamp("2025-02-08 00:00:00",tz="America/New_York")
MAPPING={("QQQ","UP"):"TQQQ",("QQQ","DOWN"):"SQQQ",("SOXX","UP"):"SOXL",("SOXX","DOWN"):"SOXS"}
FEATURES=("return_5m","return_15m","return_60m","realized_vol_15m","realized_vol_60m","relative_volume","range_position","symbol_code","direction_code","session_code")
SESSION_CODE={"OVERNIGHT":0,"PREMARKET":1,"REGULAR_TRADING_HOURS":2,"AFTER_HOURS":3}
REQUIRED=("timestamp_et","timestamp_utc","broker_trade_date","session","open","high","low","close","volume")

def write_json(path, value):
    def d(x):
        if isinstance(x,(np.integer,)): return int(x)
        if isinstance(x,(np.floating,float)): return float(x) if np.isfinite(x) else None
        if isinstance(x,pd.Timestamp): return x.isoformat()
        return str(x)
    path.write_text(json.dumps(value,indent=2,default=d)+"\n",encoding="utf-8")

def sha(value): return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()

def approved_paths(symbol, canonical=CANONICAL):
    paths=[]
    for p in sorted(Path(canonical).glob(f"symbol={symbol}/year=*/month=*/data.parquet")):
        y=int(p.parts[-3].split("=")[1]); m=int(p.parts[-2].split("=")[1])
        if (y,m) <= (2025,1): paths.append(p)
    if not paths: raise RuntimeError(f"SOURCE_DATA_MISSING:{symbol}")
    return paths

def load_preconfirmation(symbol, canonical=CANONICAL):
    paths=approved_paths(symbol,canonical)
    df=pd.concat([pd.read_parquet(p,columns=list(REQUIRED)) for p in paths],ignore_index=True)
    df.timestamp_et=pd.to_datetime(df.timestamp_et,errors="raise")
    df.timestamp_utc=pd.to_datetime(df.timestamp_utc,utc=True,errors="raise")
    df=df.sort_values("timestamp_utc",kind="mergesort").drop_duplicates("timestamp_utc").reset_index(drop=True)
    if (df.timestamp_et>=CONF_START).any(): raise RuntimeError("CONFIRMATION_ISOLATION_VIOLATION")
    for c in ("open","high","low","close","volume"): df[c]=pd.to_numeric(df[c],errors="coerce")
    df["valid"]=(df.open>0)&(df.high>=df[["open","low","close"]].max(axis=1))&(df.low<=df[["open","high","close"]].min(axis=1))
    df["session_code"]=df.session.astype(str).str.upper().map(SESSION_CODE).fillna(4).astype(int)
    return df, {"symbol":symbol,"path_count":len(paths),"row_count":len(df),"date_start":str(df.timestamp_et.min()),"date_end":str(df.timestamp_et.max()),"confirmation_rows_read":0,"invalid_ohlc_count":int((~df.valid).sum())}

def build_tree(values, is_max):
    n=len(values); size=1
    while size<n: size*=2
    fill=-np.inf if is_max else np.inf
    t=np.full(size*2,fill,dtype=float); t[size:size+n]=values
    for i in range(size-1,0,-1): t[i]=max(t[2*i],t[2*i+1]) if is_max else min(t[2*i],t[2*i+1])
    return t,size

def first_cross(tree,size,left,right,threshold,is_max):
    """First index in inclusive [left,right] with high>=x or low<=x."""
    if left>right: return -1
    left+=size; right+=size; a=[]; b=[]
    while left<=right:
        if left&1: a.append(left); left+=1
        if not(right&1): b.append(right); right-=1
        left//=2; right//=2
    for node in a+list(reversed(b)):
        ok=tree[node]>=threshold if is_max else tree[node]<=threshold
        if not ok: continue
        while node<size:
            child=node*2; left_ok=tree[child]>=threshold if is_max else tree[child]<=threshold
            node=child if left_ok else child+1
        return node-size
    return -1

def next_valid(ns, valid, start):
    i=start
    while i<len(valid) and not valid[i]: i+=1
    return i if i<len(valid) else -1

def feature_frame(df, symbol):
    close=df.close.to_numpy(float); vol=df.volume.to_numpy(float); high=df.high.to_numpy(float); low=df.low.to_numpy(float)
    ret=np.r_[np.nan,np.diff(np.log(close))]
    out=pd.DataFrame(index=df.index)
    for w in (5,15,60): out[f"return_{w}m"]=pd.Series(close).pct_change(w)
    out["realized_vol_15m"]=pd.Series(ret).rolling(15,min_periods=15).std()
    out["realized_vol_60m"]=pd.Series(ret).rolling(60,min_periods=60).std()
    out["relative_volume"]=pd.Series(vol)/pd.Series(vol).rolling(60,min_periods=60).mean()
    lo=pd.Series(low).rolling(60,min_periods=60).min(); hi=pd.Series(high).rolling(60,min_periods=60).max()
    out["range_position"]=(pd.Series(close)-lo)/(hi-lo).replace(0,np.nan)
    out["symbol_code"]=0 if symbol=="QQQ" else 1
    out["session_code"]=df.session_code.to_numpy()
    return out

def candidates_for_symbol(df,symbol):
    """Create 5-minute PIT rows and first-passage labels with no future feature use."""
    feat=feature_frame(df,symbol); ns=df.timestamp_utc.astype("int64").to_numpy(); et=df.timestamp_et.to_numpy()
    high=df.high.to_numpy(float); low=df.low.to_numpy(float); op=df.open.to_numpy(float); valid=df.valid.to_numpy(bool)
    maxt,sz=build_tree(high,True); mint,_=build_tree(low,False); rows=[]; audit={"candidate_grid_count":0,"ambiguous_count":0,"horizon_incomplete_count":0}
    grid=np.flatnonzero((df.timestamp_et.dt.minute.to_numpy()%5==0)&valid)
    for i in grid:
        if i<60: continue
        entry_i=next_valid(ns,valid,i+1)
        if entry_i<0: continue
        end=int(np.searchsorted(ns,ns[entry_i]+24*60*60*1_000_000_000,side="right")-1)
        if end<=entry_i or pd.Timestamp(et[end])>VAL_END+pd.Timedelta(hours=24): audit["horizon_incomplete_count"]+=1; continue
        ts=pd.Timestamp(et[i])
        split="DEVELOPMENT" if ts<=DEV_END else ("VALIDATION" if VAL_START<=ts<=VAL_END-pd.Timedelta(hours=24) else "EXCLUDED")
        if split=="EXCLUDED": continue
        audit["candidate_grid_count"]+=1; price=op[entry_i]; up=first_cross(maxt,sz,entry_i,end,price*1.01,True); down=first_cross(mint,sz,entry_i,end,price*.99,False)
        if up>=0 and up==down: audit["ambiguous_count"]+=1; continue
        first="UP_1PCT_FIRST" if up>=0 and (down<0 or up<down) else ("DOWN_1PCT_FIRST" if down>=0 else "NO_1PCT_MOVE_WITHIN_HORIZON")
        base={"decision_timestamp_et":ts,"decision_timestamp_utc":df.timestamp_utc.iat[i],"entry_timestamp_utc":df.timestamp_utc.iat[entry_i],"horizon_timestamp_utc":df.timestamp_utc.iat[end],"underlying_symbol":symbol,"split":split,"first_passage_label":first,"calendar_date":str(ts.date()),"year":ts.year,"session_code":int(df.session_code.iat[i]),**{k:feat[k].iat[i] for k in FEATURES if k not in ("symbol_code","direction_code","session_code")},"symbol_code":0 if symbol=="QQQ" else 1}
        for direction in ("UP","DOWN"):
            rows.append({**base,"direction":direction,"direction_code":1 if direction=="UP" else -1,"target_first":int(first==f"{direction}_1PCT_FIRST"),"execution_etf":MAPPING[(symbol,direction)]})
    return pd.DataFrame(rows),audit

def select_model(dev):
    x=dev[list(FEATURES)]; y=dev.target_first.to_numpy(); candidates={
        "logistic":Pipeline([("impute",SimpleImputer(strategy="median")),("scale",StandardScaler()),("model",LogisticRegression(C=1.0,max_iter=200,n_jobs=1,random_state=1729))]),
        "tree_depth3":Pipeline([("impute",SimpleImputer(strategy="median")),("model",DecisionTreeClassifier(max_depth=3,min_samples_leaf=200,random_state=1729))]),
        "hgb_depth2":Pipeline([("impute",SimpleImputer(strategy="median")),("model",HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=7,l2_regularization=1.0,learning_rate=.08,random_state=1729))])}
    scores=[]
    for name,model in candidates.items():
        model.fit(x,y); p=model.predict_proba(x)[:,1]; n=max(1,int(len(p)*.05)); rate=float(y[np.argsort(-p,kind="mergesort")[:n]].mean()); scores.append((rate/(y.mean() or np.nan),name,model))
    scores.sort(key=lambda z:(z[0],z[1]),reverse=True)
    return scores[0][1],scores[0][2],scores

def evaluate(model, frame, split):
    p=model.predict_proba(frame[list(FEATURES)])[:,1]; order=np.argsort(-p,kind="mergesort"); n=max(1,int(len(p)*.05)); sel=frame.iloc[order[:n]].copy(); sel["model_probability"]=p[order[:n]]
    y=frame.target_first.to_numpy(); top=float(sel.target_first.mean()); base=float(y.mean());
    return sel,{"split":split,"row_count":int(len(frame)),"top5_selected_count":int(n),"unconditional_target_first_rate":base,"top5_target_first_rate":top,"top5_target_first_lift":float(top/base) if base else None,"auc":float(roc_auc_score(y,p)),"brier":float(brier_score_loss(y,p))}

def etf_outcomes(selected, etfs):
    """Real ETF OHLC target-or-24h timeout economics for the selected rows only."""
    caches={}
    for sym,df in etfs.items():
        caches[sym]=(df,np.asarray(df.timestamp_utc.astype("int64")),*build_tree(df.high.to_numpy(float),True))
    out=[]
    for r in selected.itertuples(index=False):
        df,ns,tree,sz=caches[r.execution_etf]; ts=pd.Timestamp(r.entry_timestamp_utc).value; ep=int(np.searchsorted(ns,ts));
        if ep>=len(df) or ns[ep]-ts>60_000_000_000 or not df.valid.iat[ep]: out.append({"mapping_status":"ENTRY_TIMESTAMP_MISMATCH"}); continue
        hp=int(np.searchsorted(ns,pd.Timestamp(r.horizon_timestamp_utc).value));
        if hp>=len(df) or ns[hp]-pd.Timestamp(r.horizon_timestamp_utc).value>60_000_000_000 or not df.valid.iat[hp]: out.append({"mapping_status":"EXIT_TIMESTAMP_MISMATCH"}); continue
        entry=float(df.open.iat[ep]); hit=first_cross(tree,sz,ep,hp,entry*1.03,True); gross=.03 if hit>=0 else float(df.open.iat[hp]/entry-1)
        out.append({"mapping_status":"SUCCESS","gross_return":gross,"net_return_10bps":gross-.001,"net_return_20bps":gross-.002,"etf_target_hit":bool(hit>=0),"execution_etf":r.execution_etf,"year":r.year,"session_code":r.session_code})
    return pd.DataFrame(out)

def concentration(outcomes):
    x=outcomes[outcomes.mapping_status.eq("SUCCESS")].copy()
    if x.empty: return {"single_etf_profit_contribution":None,"top5_profit_concentration":None}
    pos=x.net_return_10bps.clip(lower=0); total=float(pos.sum())
    return {"single_etf_profit_contribution":float(pos.groupby(x.execution_etf).sum().max()/total) if total else None,"top5_profit_concentration":float(pos.nlargest(5).sum()/total) if total else None}

def random_asof_robustness(selected, outcomes, seed=1729, iterations=3, window_days=120):
    """Fixed-seed contiguous validation windows; no row-level randomization or tuning."""
    x=selected.reset_index(drop=True).copy(); y=outcomes.reset_index(drop=True).copy()
    x["net_return_10bps"]=y.net_return_10bps; x["net_return_20bps"]=y.net_return_20bps
    x["day"]=pd.to_datetime(x.decision_timestamp_et).dt.normalize(); days=np.array(sorted(x.day.unique()))
    rng=np.random.default_rng(seed); rows=[]
    if len(days)<window_days: return pd.DataFrame(rows)
    for iteration in range(1,iterations+1):
        start_i=int(rng.integers(0,len(days)-window_days+1)); start,end=days[start_i],days[start_i+window_days-1]
        w=x[x.day.between(start,end)]
        rows.append({"iteration_id":iteration,"predeclared_hypothesis":"Development-frozen top5 selection remains economically nonnegative in a random continuous Validation as-of window","random_seed":seed,"window_days":window_days,"window_start":start,"window_end":end,"selected_trade_count":len(w),"target_first_rate":float(w.target_first.mean()),"mean_net_return_10bps":float(w.net_return_10bps.mean()),"mean_net_return_20bps":float(w.net_return_20bps.mean()),"decision":"ROBUSTNESS_EVIDENCE_ONLY_NO_RETUNING"})
    return pd.DataFrame(rows)

def run(output_dir=DEFAULT_OUT,canonical=CANONICAL):
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True); data={}; audit=[]
    for s in ("QQQ","SOXX","TQQQ","SQQQ","SOXL","SOXS"): data[s],a=load_preconfirmation(s,canonical); audit.append(a)
    frames=[]; cand_audit=[]
    for s in ("QQQ","SOXX"):
        f,a=candidates_for_symbol(data[s],s); frames.append(f); cand_audit.append({"symbol":s,**a})
    sample=pd.concat(frames,ignore_index=True); dev=sample[sample.split.eq("DEVELOPMENT")].reset_index(drop=True); val=sample[sample.split.eq("VALIDATION")].reset_index(drop=True)
    if dev.empty or val.empty: raise RuntimeError("INSUFFICIENT_VALIDATION_SAMPLE")
    model_name,model,dev_scores=select_model(dev); dev_sel,dev_metric=evaluate(model,dev,"DEVELOPMENT"); val_sel,val_metric=evaluate(model,val,"VALIDATION")
    dev_out=etf_outcomes(dev_sel,{s:data[s] for s in ("TQQQ","SQQQ","SOXL","SOXS")}); val_out=etf_outcomes(val_sel,{s:data[s] for s in ("TQQQ","SQQQ","SOXL","SOXS")})
    valid=val_out[val_out.mapping_status.eq("SUCCESS")]; economics={"top5_mean_net_return_10bps":float(valid.net_return_10bps.mean()) if len(valid) else None,"top5_mean_net_return_20bps":float(valid.net_return_20bps.mean()) if len(valid) else None,"top5_etf_mapping_success_rate":float(len(valid)/len(val_out)) if len(val_out) else 0,**concentration(valid)}
    years=valid.groupby("year").net_return_10bps.mean(); stable_years=int((years>0).sum())
    random_windows=random_asof_robustness(val_sel,val_out)
    gates=[val_metric["top5_selected_count"]>=100,val_metric["top5_target_first_lift"]>=1.5,economics["top5_mean_net_return_10bps"] is not None and economics["top5_mean_net_return_10bps"]>0,economics["top5_mean_net_return_20bps"] is not None and economics["top5_mean_net_return_20bps"]>0,stable_years>=3,(economics["single_etf_profit_contribution"] or 1)>=0 and (economics["single_etf_profit_contribution"] or 1)<.70,(economics["top5_profit_concentration"] or 1)>=0 and (economics["top5_profit_concentration"] or 1)<.25]
    decision="PREDICTABILITY_VALIDATED_FOR_FROZEN_CONFIRMATION" if all(gates) else ("PREDICTABILITY_NOT_ECONOMICALLY_ACTIONABLE" if economics["top5_mean_net_return_10bps"] is None or economics["top5_mean_net_return_10bps"]<=0 or economics["top5_mean_net_return_20bps"]<=0 else "EDGE_TOO_CONCENTRATED_FOR_FREEZE")
    contract={"candidate_grid":"minute % 5 == 0; next valid minute open","barrier":"symmetric +/-1% within 24 natural hours","split":{"development_end":str(DEV_END),"validation_start":str(VAL_START),"validation_end":str(VAL_END),"confirmation_start":str(CONF_START),"embargo_days":5},"features":list(FEATURES),"models":["logistic C=1.0","DecisionTree max_depth=3 min_samples_leaf=200","HistGradientBoosting max_iter=100 max_leaf_nodes=7"],"selection":"highest Development top-5% target-first lift; deterministic tie by name","random_asof":{"seed":1729,"iterations":3,"continuous_validation_window_days":120,"purpose":"robustness evidence only; never used for model or threshold selection"},"confirmation_row_read_count":0}
    feature_hash=sha(contract); summary={"research_id":NAME,"final_status":"PASS","final_decision":decision,"selected_model":model_name,"feature_contract_sha256":feature_hash,"confirmation_row_read_count":0,"development":dev_metric,"validation":val_metric,"validation_economics":economics,"positive_year_count":stable_years,"random_asof_robustness":random_windows.to_dict(orient="records"),"candidate_audit":cand_audit,"source_audit":audit,"broker_action_allowed":False,"paper_trading_allowed":False,"official_adoption_allowed":False,"order_generation_allowed":False,"output_directory":str(out)}
    write_json(out/"v22_080b_split_contract.json",contract); write_json(out/"v22_080b_feature_contract.json",{**contract,"sha256":feature_hash}); write_json(out/"v22_080b_summary.json",summary)
    pd.DataFrame([{"model":n,"development_top5_lift":s} for s,n,_ in dev_scores]).to_csv(out/"v22_080b_model_results.csv",index=False)
    pd.DataFrame([dev_metric,val_metric]).to_csv(out/"v22_080b_baseline_results.csv",index=False); pd.DataFrame([val_metric|economics]).to_csv(out/"v22_080b_validation_topk.csv",index=False)
    pd.DataFrame(cand_audit).to_csv(out/"v22_080b_candidate_label_audit.csv",index=False); pd.concat([valid.groupby("year").net_return_10bps.mean().rename("mean_net_return_10bps"),valid.groupby("year").size().rename("trade_count")],axis=1).reset_index().to_csv(out/"v22_080b_stability.csv",index=False)
    random_windows.to_csv(out/"v22_080b_random_asof_robustness.csv",index=False)
    valid.groupby(["execution_etf","session_code"]).net_return_10bps.agg(["size","mean","sum"]).reset_index().to_csv(out/"v22_080b_concentration.csv",index=False)
    pd.DataFrame(audit).to_csv(out/"v22_080b_zero_and_missing_diagnostic.csv",index=False); pd.DataFrame({"bin":["not_computed"],"count":[0]}).to_csv(out/"v22_080b_calibration.csv",index=False)
    (out/"v22_080b_report.md").write_text(f"# {NAME}\n\nFINAL_STATUS=PASS\n\nFINAL_DECISION={decision}\n\nConfirmation rows loaded: 0. Selected by Development only: {model_name}. Validation top-5% lift: {val_metric['top5_target_first_lift']}. This is research-only and produces no orders.\n",encoding="utf-8")
    print("FINAL_STATUS=PASS"); print("FINAL_DECISION="+decision); print("SUMMARY_PATH="+str(out/"v22_080b_summary.json")); return summary

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--output-dir",default=str(DEFAULT_OUT)); p.add_argument("--canonical-root",default=str(CANONICAL)); a=p.parse_args(); run(a.output_dir,Path(a.canonical_root))
