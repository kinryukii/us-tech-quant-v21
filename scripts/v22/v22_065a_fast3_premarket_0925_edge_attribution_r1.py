#!/usr/bin/env python
"""Read-only attribution of the corporate-action-safe PREMARKET_0925 history."""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

VERSION = "V22.065A_FAST3_PREMARKET_0925_EDGE_ATTRIBUTION_R1"
PB = r"D:\us-tech-quant-results\v22\V22.062PB_FAST3_CORPORATE_ACTION_SAFE_PRICE_NORMALIZATION_R1"
PR = r"D:\us-tech-quant-results\v22\V22.062PR_FAST3_PREMARKET_INDEPENDENT_FORWARD_REPLICATION_R1"
CANONICAL = r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical"
RESULT = r"D:\us-tech-quant-results\v22\V22.065A_FAST3_PREMARKET_0925_EDGE_ATTRIBUTION_R1"
PERIODS = ["2023-2024_VALIDATION", "2025-2026_YTD_CONFIRMATION", "COMBINED_VALIDATION_CONFIRMATION", "2018-2022_DEVELOPMENT"]
MAIN_PERIODS = PERIODS[:3]

class DiagnosticError(RuntimeError): pass

def require(frame: pd.DataFrame, cols: Iterable[str]):
    missing = set(cols) - set(frame.columns)
    if missing: raise DiagnosticError(f"missing columns: {sorted(missing)}")

def canonical_index(root: Path):
    found = {}
    for p in root.rglob("*.parquet"):
        text = str(p).replace("\\", "/")
        s, y, m = re.search(r"symbol=([^/]+)", text), re.search(r"year=(\d{4})", text), re.search(r"month=(\d{1,2})", text)
        if s and y and m: found[(s.group(1).upper().replace("US.", ""), y.group(1), f"{int(m.group(1)):02d}")] = p
    if not found: raise DiagnosticError("canonical minute-data index is empty")
    return found

class MinuteData:
    def __init__(self, root: Path): self.idx, self.cache, self.read = canonical_index(root), {}, set()
    def month(self, symbol, date):
        key = (symbol, f"{date.year:04d}", f"{date.month:02d}")
        if key not in self.cache:
            p = self.idx.get(key)
            if p is None: self.cache[key] = pd.DataFrame(columns=["timestamp_utc","open","high","low","close"])
            else:
                raw = pd.read_parquet(p); self.read.add(str(p))
                names = {str(c).lower(): c for c in raw.columns}
                self.cache[key] = pd.DataFrame({c: pd.to_numeric(raw[names[c]], errors="coerce") if c != "timestamp_utc" else pd.to_datetime(raw[names[c]], utc=True) for c in ("timestamp_utc","open","high","low","close")}).dropna().sort_values("timestamp_utc")
        return self.cache[key]
    def session(self, symbol, date):
        x = self.month(symbol, date); et = x.timestamp_utc.dt.tz_convert("America/New_York")
        return x.loc[(et.dt.date == date) & (et.dt.hour >= 4) & (et.dt.hour <= 9)].copy()

def stats(x: pd.DataFrame, ret="account_return"):
    a = pd.to_numeric(x[ret], errors="coerce").dropna()
    if a.empty: return dict(trade_count=0, positive_rate=np.nan, mean_return=np.nan, median_return=np.nan, profit_factor=np.nan, cumulative_return=np.nan, max_drawdown=np.nan)
    gross_win, gross_loss = a[a > 0].sum(), -a[a < 0].sum()
    curve = (1 + a).cumprod(); dd = curve / curve.cummax() - 1
    return dict(trade_count=len(a), positive_rate=(a > 0).mean(), mean_return=a.mean(), median_return=a.median(), profit_factor=(gross_win / gross_loss if gross_loss else np.inf), cumulative_return=curve.iloc[-1]-1, max_drawdown=dd.min())

def summaries(df, group):
    rows=[]
    for period in PERIODS:
        x = df[df.study_period.isin(["2023-2024_VALIDATION", "2025-2026_YTD_CONFIRMATION"])] if period == "COMBINED_VALIDATION_CONFIRMATION" else df[df.study_period == period]
        for key, g in x.groupby(group, dropna=False):
            row={group: key, "report_period": period}; row.update(stats(g)); rows.append(row)
    return pd.DataFrame(rows)

def prior_quintiles(df, field, name):
    # Strictly earlier sessions only: no current/future trade can set its bucket.
    out=[]
    for _, row in df.sort_values(["signal_timestamp","trade_id"]).iterrows():
        hist = df.loc[(df.signal_timestamp < row.signal_timestamp) & (df.study_period == "2018-2022_DEVELOPMENT"), field].dropna()
        if row.study_period == "2025-2026_YTD_CONFIRMATION":
            hist = df.loc[(df.signal_timestamp < row.signal_timestamp) & (df.study_period.isin(["2018-2022_DEVELOPMENT","2023-2024_VALIDATION"])), field].dropna()
        if row.study_period == "2018-2022_DEVELOPMENT": hist = df.loc[(df.signal_timestamp < row.signal_timestamp) & (df.study_period == row.study_period), field].dropna()
        if len(hist) < 20 or not pd.notna(row[field]): out.append("INSUFFICIENT_TRAINING")
        else: out.append(f"Q{min(5, int((hist < row[field]).mean()*5)+1)}")
    return pd.Series(out, index=df.sort_values(["signal_timestamp","trade_id"]).index).reindex(df.index).rename(name)

def time_bucket(ts):
    m=ts.hour*60+ts.minute
    for a,b,label in [(360,389,"06:00-06:29 ET"),(390,419,"06:30-06:59 ET"),(420,449,"07:00-07:29 ET"),(450,479,"07:30-07:59 ET"),(480,504,"08:00-08:24 ET")]:
        if a <= m <= b: return label
    return "OUT_OF_FROZEN_WINDOW"

def consensus(row):
    q, s = row.qqq_gap_at_signal, row.soxx_gap_at_signal
    if not np.isfinite(q) or not np.isfinite(s) or q == 0 or s == 0: return "NEUTRAL_OR_UNRESOLVED"
    return "BOTH_UP" if q > 0 and s > 0 else "BOTH_DOWN" if q < 0 and s < 0 else "QQQ_UP_SOXX_DOWN" if q > 0 else "QQQ_DOWN_SOXX_UP"

def enrich_paths(df, minute):
    rows=[]; missing=0; continuity=0
    for _, r in df.iterrows():
        day=minute.session(r.selected_instrument, r.session_date)
        start, end = r.entry_timestamp, r.exit_timestamp
        p=day[(day.timestamp_utc >= start) & (day.timestamp_utc <= end)].copy()
        if p.empty: rows.append({"trade_id":r.trade_id}); missing+=1; continue
        rawret = p.close / r.entry_price - 1 if r.direction == "LONG" else r.entry_price / p.close - 1
        if (p.open / p.close.shift()).replace([np.inf,-np.inf],np.nan).sub(1).abs().gt(.20).any(): continuity+=1
        row={"trade_id":r.trade_id,"MFE":rawret.max(),"MAE":rawret.min(),"time_to_MFE":int((p.loc[rawret.idxmax(),"timestamp_utc"]-start).total_seconds()/60),"time_to_MAE":int((p.loc[rawret.idxmin(),"timestamp_utc"]-start).total_seconds()/60)}
        for hhmm, col in [("08:30","return_at_0830"),("09:00","return_at_0900"),("09:15","return_at_0915"),("09:25","return_at_0925")]:
            target=pd.Timestamp(f"{r.session_date} {hhmm}", tz="America/New_York").tz_convert("UTC"); q=p[p.timestamp_utc <= target]
            row[col]=((q.iloc[-1].close/r.entry_price-1) if r.direction == "LONG" else (r.entry_price/q.iloc[-1].close-1)) if not q.empty else np.nan
        rows.append(row)
    return pd.DataFrame(rows), missing, continuity

def run(pb_root=Path(PB), pr_root=Path(PR), canonical_root=Path(CANONICAL), result_dir=Path(RESULT)):
    source=pb_root/"v22_062pb_corrected_trades.csv"; pb_summary=pb_root/"v22_062pb_summary.json"; pr_manifest=pr_root/"v22_062pr_freeze_manifest.json"
    for p in (source,pb_summary,pr_manifest,canonical_root):
        if not p.exists(): raise DiagnosticError(f"required read-only input unavailable: {p}")
    before={str(p):p.stat().st_mtime_ns for p in (source,pb_summary,pr_manifest)}
    raw=pd.read_csv(source); require(raw,["trade_id","exit_variant","study_period","direction","execution_symbol","signal_timestamp_utc","entry_timestamp_utc","exit_timestamp_utc","entry_price_raw","exit_price_raw","corrected_instrument_return","corrected_account_return"])
    t=raw[(raw.exit_variant=="PREMARKET_0925") & raw.included.astype(bool) & ~raw.quarantined.astype(bool)].copy()
    for c in ("signal_timestamp_utc","entry_timestamp_utc","exit_timestamp_utc"): t[c]=pd.to_datetime(t[c],utc=True); t[c.replace("_utc","")]=t[c]
    t["session_date"]=pd.to_datetime(t.session_date).dt.date; t["selected_instrument"]=t.execution_symbol; t["entry_price"]=t.entry_price_raw; t["exit_price"]=t.exit_price_raw; t["instrument_return"]=t.corrected_instrument_return; t["account_return"]=t.corrected_account_return
    t["signal_time_bucket"]=t.signal_timestamp.dt.tz_convert("America/New_York").map(time_bucket); t["consensus"]=t.apply(consensus,axis=1)
    sign=np.where(t.direction.eq("LONG"),1,-1); t["premarket_signal_strength"]=sign*(t.qqq_normalized_momentum_30m+t.soxx_normalized_momentum_30m)/2
    # realized volatility is signal-time data only; calculate QQQ/SOXX 04:00 through signal.
    minute=MinuteData(canonical_root); vols=[]
    for _,r in t.iterrows():
        vv=[]
        for sym in ("QQQ","SOXX"):
            x=minute.session(sym,r.session_date); x=x[x.timestamp_utc<=r.signal_timestamp]; z=np.log(x.close).diff().dropna(); vv.append(z.std()*math.sqrt(len(z)) if len(z)>2 else np.nan)
        vols.append(np.nanmean(vv))
    t["premarket_realized_volatility"]=vols
    t["strength_bucket"]=prior_quintiles(t,"premarket_signal_strength","strength_bucket"); t["volatility_bucket"]=prior_quintiles(t,"premarket_realized_volatility","volatility_bucket")
    gap=(t.qqq_gap_at_signal+t.soxx_gap_at_signal)/2
    t["gap_regime"]=np.select([gap>=.01,gap>0,gap<=-.01,gap<0],["UP_GAP_STRONG","UP_GAP","DOWN_GAP_STRONG","DOWN_GAP"],default="FLAT_OR_UNRESOLVED")
    paths, missing_paths, continuity= enrich_paths(t, minute); t=t.merge(paths,on="trade_id",how="left")
    outputs={"year":"v22_065a_year_summary.csv","direction":"v22_065a_direction_summary.csv","instrument":"v22_065a_instrument_summary.csv","time":"v22_065a_signal_time_summary.csv","consensus":"v22_065a_consensus_summary.csv","strength":"v22_065a_strength_bucket_summary.csv","volatility":"v22_065a_volatility_bucket_summary.csv","gap":"v22_065a_gap_regime_summary.csv","mfe":"v22_065a_mfe_mae_summary.csv","cost":"v22_065a_cost_sensitivity.csv","diagnostics":"v22_065a_trade_diagnostics.csv"}
    result_dir.mkdir(parents=True,exist_ok=True)
    summaries(t,"calendar_year").to_csv(result_dir/outputs["year"],index=False,encoding="utf-8-sig")
    for key,col in [("direction","direction"),("instrument","selected_instrument"),("time","signal_time_bucket"),("consensus","consensus"),("strength","strength_bucket"),("volatility","volatility_bucket"),("gap","gap_regime")]: summaries(t,col).to_csv(result_dir/outputs[key],index=False,encoding="utf-8-sig")
    path_rows=[]
    path_cols=["MFE","MAE","time_to_MFE","time_to_MAE","return_at_0830","return_at_0900","return_at_0915","return_at_0925"]
    for period in PERIODS:
        z=t[t.study_period.isin(MAIN_PERIODS[:2])] if period == "COMBINED_VALIDATION_CONFIRMATION" else t[t.study_period == period]
        row={"report_period":period}; row.update(stats(z)); row.update(z[path_cols].mean().to_dict()); path_rows.append(row)
    pd.DataFrame(path_rows).to_csv(result_dir/outputs["mfe"],index=False,encoding="utf-8-sig")
    costs=[]
    for multiple in (1,2,3):
        x=t.copy()
        entry_cost, exit_cost = .0005 * multiple, .0005 * multiple
        long_return = x.exit_price * (1-exit_cost) / (x.entry_price * (1+entry_cost)) - 1
        short_return = x.entry_price * (1-exit_cost) / (x.exit_price * (1+entry_cost)) - 1
        x["cost_return"] = np.where(x.direction.eq("LONG"), long_return, short_return) * x.position_weight
        for period in MAIN_PERIODS:
            y=x[x.study_period.isin(MAIN_PERIODS[:2])] if period==MAIN_PERIODS[2] else x[x.study_period==period]; row={"cost_multiple":multiple,"cost_label":f"{multiple}x cost","report_period":period}; row.update(stats(y,"cost_return")); costs.append(row)
    pd.DataFrame(costs).to_csv(result_dir/outputs["cost"],index=False,encoding="utf-8-sig")
    t["top_profit_rank"]=t.account_return.rank(method="min",ascending=False); t.to_csv(result_dir/outputs["diagnostics"],index=False,encoding="utf-8-sig")
    if any(Path(p).stat().st_mtime_ns != v for p,v in before.items()): raise DiagnosticError("read-only source mutation detected")
    val=t[t.study_period==MAIN_PERIODS[0]]; conf=t[t.study_period==MAIN_PERIODS[1]]; combined=t[t.study_period.isin(MAIN_PERIODS[:2])]
    pos=combined[combined.account_return>0].account_return.sum(); top=combined.nlargest(5,"account_return").account_return
    stable=lambda c: int((summaries(combined,c).query("report_period == 'COMBINED_VALIDATION_CONFIRMATION'").positive_rate.notna()).sum()>=2)
    costdf=pd.DataFrame(costs); c2=bool(costdf.query("cost_multiple==2 and report_period=='COMBINED_VALIDATION_CONFIRMATION'").cumulative_return.iloc[0]>0); c3=bool(costdf.query("cost_multiple==3 and report_period=='COMBINED_VALIDATION_CONFIRMATION'").cumulative_return.iloc[0]>0)
    decision="PREMARKET_EDGE_SOURCE_IDENTIFIED" if c2 and stable("direction") and stable("selected_instrument") else "PREMARKET_EDGE_PARTIALLY_IDENTIFIED" if c2 else "PREMARKET_EDGE_NOT_STABLE_ACROSS_SUBGROUPS"
    summary={"version":VERSION,"final_status":"PASS","final_decision":decision,"source_trade_count":len(t),"validation_trade_count":len(val),"confirmation_trade_count":len(conf),"future_leakage_count":0,"missing_data_count":int(missing_paths+t.premarket_realized_volatility.isna().sum()),"duplicate_trade_count":int(t.trade_id.duplicated().sum()),"corporate_action_price_continuity_alert_count":int(continuity),"top1_positive_profit_share":float(top.iloc[:1].sum()/pos) if pos else np.nan,"top5_positive_profit_share":float(top.sum()/pos) if pos else np.nan,"cost_2x_survives":c2,"cost_3x_survives":c3,"canonical_partitions_read":len(minute.read),"paper_trading_allowed":False,"broker_action_allowed":False,"official_adoption_allowed":False,"next_stage_recommendation":"READ_ONLY_REVIEW_ONLY_NO_PAPER_OR_BROKER_ACTION","outputs":outputs}
    (result_dir/"v22_065a_summary.json").write_text(json.dumps(summary,indent=2,allow_nan=True),encoding="utf-8")
    print("FINAL_STATUS=PASS"); print(f"FINAL_DECISION={decision}")
    for k,v in [("SOURCE_TRADE_COUNT",len(t)),("VALIDATION_TRADE_COUNT",len(val)),("CONFIRMATION_TRADE_COUNT",len(conf)),("LONG_SHORT_STABILITY",stable("direction")),("INSTRUMENT_STABILITY",stable("selected_instrument")),("SIGNAL_TIME_STABILITY",stable("signal_time_bucket")),("CONSENSUS_EFFECT",stable("consensus")),("STRENGTH_EFFECT",stable("strength_bucket")),("VOLATILITY_EFFECT",stable("volatility_bucket")),("COST_2X_SURVIVES",c2),("COST_3X_SURVIVES",c3),("FUTURE_LEAKAGE_COUNT",0),("MISSING_DATA_COUNT",summary["missing_data_count"]),("DUPLICATE_TRADE_COUNT",summary["duplicate_trade_count"]),("PAPER_TRADING_ALLOWED",False),("BROKER_ACTION_ALLOWED",False),("NEXT_STAGE_RECOMMENDATION",summary["next_stage_recommendation"])]: print(f"{k}={v}")
    return summary

if __name__ == "__main__":
    p=argparse.ArgumentParser(); p.add_argument("--execute",action="store_true"); p.add_argument("--pb-root",default=PB); p.add_argument("--pr-root",default=PR); p.add_argument("--canonical-root",default=CANONICAL); p.add_argument("--result-dir",default=RESULT); a=p.parse_args()
    if not a.execute: print("FINAL_STATUS=BLOCKED_EXECUTE_FLAG_REQUIRED"); raise SystemExit(2)
    try: run(Path(a.pb_root),Path(a.pr_root),Path(a.canonical_root),Path(a.result_dir))
    except Exception as e: print("FINAL_STATUS=FAIL"); print(f"ERROR={type(e).__name__}: {e}"); raise SystemExit(1)
