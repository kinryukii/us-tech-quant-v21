#!/usr/bin/env python
from __future__ import annotations

import argparse, hashlib, json, os, re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from functools import reduce
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

VERSION = "V22.050_FAST3_SIX_ETF_MINUTE_TRADABILITY_AUDIT_R1"
SYMBOLS = ("QQQ","SOXX","TQQQ","SQQQ","SOXL","SOXS")
SESSIONS = ("NIGHT","PREMARKET","RTH","AFTERHOURS")
PAIRS = (("QQQ_TQQQ","QQQ","TQQQ"),("QQQ_SQQQ","QQQ","SQQQ"),("SOXX_SOXL","SOXX","SOXL"),("SOXX_SOXS","SOXX","SOXS"),("QQQ_SOXX","QQQ","SOXX"))
RTH_REQUIRED = ("QQQ_TQQQ","QQQ_SQQQ","SOXX_SOXL","SOXX_SOXS")

class AuditError(RuntimeError): pass

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""): h.update(b)
    return h.hexdigest().upper()

def atomic_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str)+"\n",encoding="utf-8")
    os.replace(tmp,path)

def utc_z(ns: int) -> str:
    return pd.Timestamp(ns,unit="ns",tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")

def normalize_utc(s: pd.Series) -> pd.Series:
    if isinstance(s.dtype,pd.DatetimeTZDtype): x=s.dt.tz_convert("UTC")
    elif pd.api.types.is_datetime64_dtype(s.dtype): raise AuditError("timestamp_utc is naive")
    else: x=pd.to_datetime(s,utc=True,errors="raise")
    return pd.Series(pd.array(x,dtype="datetime64[ns, UTC]"),index=s.index,name=s.name)

def classify_session(et: pd.Series) -> pd.Series:
    if not isinstance(et.dtype,pd.DatetimeTZDtype): raise AuditError("timestamp_et must be timezone-aware")
    m=et.dt.hour*60+et.dt.minute
    v=np.select([(m>=1200)|(m<240),(m>=240)&(m<570),(m>=570)&(m<960),(m>=960)&(m<1200)],SESSIONS,default="UNKNOWN")
    return pd.Series(v,index=et.index,dtype="string")

def next_weekday(d):
    while d.weekday()>=5: d+=timedelta(days=1)
    return d

def broker_date(et: pd.Series) -> pd.Series:
    out=[]
    for d,h in zip(et.dt.date,et.dt.hour,strict=True):
        if int(h)>=20: d=next_weekday(d+timedelta(days=1))
        out.append(d.isoformat())
    return pd.Series(out,index=et.index,dtype="string")

def col(df: pd.DataFrame,*names,required=True):
    m={str(c).lower():str(c) for c in df.columns}
    for n in names:
        if n.lower() in m: return m[n.lower()]
    if required: raise AuditError(f"missing column {names}; got {list(df.columns)}")
    return None

def symbol_from(path: Path) -> str:
    for p in path.parts:
        q=re.fullmatch(r"symbol=(.+)",p,re.I)
        if q:return q.group(1).upper()
    raise AuditError(f"cannot parse symbol: {path}")

def validate_snapshot(s: dict[str,Any]) -> None:
    checks={"data_baseline_frozen":True,"v22_050_allowed":True,"canonical_parquet_count":582,"duplicate_count":0,"invalid_ohlc_count":0}
    bad=[f"{k}={s.get(k)!r}" for k,v in checks.items() if s.get(k)!=v]
    if bad: raise AuditError("V22.049 gate failed: "+", ".join(bad))

def invalid_ohlc(df: pd.DataFrame) -> pd.Series:
    o=pd.to_numeric(df[col(df,"open")],errors="coerce"); h=pd.to_numeric(df[col(df,"high")],errors="coerce")
    l=pd.to_numeric(df[col(df,"low")],errors="coerce"); c=pd.to_numeric(df[col(df,"close")],errors="coerce")
    return ~(o.notna()&h.notna()&l.notna()&c.notna()&(o>0)&(h>0)&(l>0)&(c>0)&(h>=o)&(h>=c)&(h>=l)&(l<=o)&(l<=c)&(l<=h))

def alignment(source: np.ndarray,target: np.ndarray) -> dict[str,Any]:
    s=np.unique(source); t=np.unique(target); a=np.intersect1d(s,t,assume_unique=True)
    return {"source_row_count":int(s.size),"target_row_count":int(t.size),"aligned_row_count":int(a.size),"alignment_ratio":float(a.size/s.size) if s.size else 0.0,"missing_execution_timestamp_count":int(s.size-a.size),"common_coverage_start":utc_z(int(a[0])) if a.size else "","common_coverage_end":utc_z(int(a[-1])) if a.size else ""}

def tradability(session,row_count,median_cov,p05_cov,zero_share,median_vol,clean):
    eligible=clean and row_count>0 and median_cov>=.99 and p05_cov>=.95 and zero_share<=.05 and median_vol>0
    if session=="RTH":
        return "BACKTEST_ELIGIBLE" if eligible else ("BACKTEST_WITH_CAUTION" if clean and row_count>0 and median_cov>=.95 else "OBSERVATION_ONLY")
    if eligible and median_vol>=100:return "BACKTEST_ELIGIBLE"
    if clean and row_count>0 and median_cov>=.95 and zero_share<=.20 and median_vol>0:return "BACKTEST_WITH_CAUTION"
    return "OBSERVATION_ONLY"

def fast3_gate(rth:dict[str,str],ratios:dict[str,float],dup:int,bad:int,tz:bool,bd:bool):
    failed=[]
    for s in SYMBOLS:
        if rth.get(s)!="BACKTEST_ELIGIBLE":failed.append(f"rth_not_eligible_{s}")
    for p in RTH_REQUIRED:
        if ratios.get(p,0)<.995:failed.append(f"rth_alignment_below_0_995_{p}")
    if dup:failed.append("duplicate_count_nonzero")
    if bad:failed.append("invalid_ohlc_count_nonzero")
    if not tz:failed.append("timezone_validation_failed")
    if not bd:failed.append("broker_trade_date_validation_failed")
    return not failed,failed

def q(a,qv): return float(np.nanquantile(a,qv)) if a.size else 0.0

def run(acceptance:Path,root:Path,result:Path):
    snap=json.loads(acceptance.read_text(encoding="utf-8-sig")); validate_snapshot(snap)
    files=sorted(root.rglob("*.parquet"))
    if len(files)!=582:raise AuditError(f"expected 582 parquet, found {len(files)}")
    before={str(p):sha256(p) for p in files}
    part=Counter(); rows=Counter(); earliest={}; latest={}; dup=0; bad=0; tz_ok=True; bd_ok=True
    daily=defaultdict(lambda:{"count":0,"volume":0.0,"last_ns":None,"last_close":None,"longest":0,"g2":0,"g5":0,"g15":0,"jumps":[]})
    volumes=defaultdict(list); timestamps=defaultdict(list)
    for i,p in enumerate(files,1):
        s=symbol_from(p)
        if s not in SYMBOLS:raise AuditError(f"unexpected symbol {s}")
        df=pd.read_parquet(p)
        part[s]+=1
        if df.empty:continue
        tc=col(df,"timestamp_utc"); df[tc]=normalize_utc(df[tc]); et=df[tc].dt.tz_convert("America/New_York")
        tz_ok &= str(df[tc].dtype)=="datetime64[ns, UTC]" and isinstance(et.dtype,pd.DatetimeTZDtype)
        sess=classify_session(et); dc=broker_date(et)
        existing=col(df,"broker_trade_date","trade_date",required=False)
        if existing:
            e=pd.to_datetime(df[existing],errors="coerce").dt.strftime("%Y-%m-%d").astype("string"); valid=e.notna()
            if valid.any(): bd_ok &= float((e[valid]!=dc[valid]).mean())<=.01; dc=e.where(valid,dc)
        ns=df[tc].astype("int64"); closev=pd.to_numeric(df[col(df,"close")],errors="coerce"); volv=pd.to_numeric(df[col(df,"volume")],errors="coerce").fillna(0)
        rows[s]+=len(df); dup+=int(ns.duplicated().sum()); bad+=int(invalid_ohlc(df).sum())
        mn=int(ns.min()); mx=int(ns.max()); earliest[s]=min(earliest.get(s,mn),mn); latest[s]=max(latest.get(s,mx),mx)
        for se in SESSIONS:
            m=sess.eq(se)
            if not m.any():continue
            nsv=ns[m].to_numpy(np.int64,copy=True); vv=volv[m].to_numpy(np.float64,copy=True)
            volumes[(s,se)].append(vv); timestamps[(s,se)].append(nsv)
            sub=pd.DataFrame({"d":dc[m].to_numpy(),"ns":nsv,"c":closev[m].to_numpy(np.float64),"v":vv})
            for d,g in sub.groupby("d",sort=True):
                st=daily[(s,str(d),se)]; order=np.argsort(g.ns.to_numpy(),kind="mergesort"); t=g.ns.to_numpy(np.int64)[order]; c=g.c.to_numpy(np.float64)[order]; v=g.v.to_numpy(np.float64)[order]
                if st["last_ns"] is not None:
                    miss=max(int(round((int(t[0])-st["last_ns"])/60_000_000_000))-1,0)
                    if miss:st["longest"]=max(st["longest"],miss);st["g2"]+=miss>=2;st["g5"]+=miss>=5;st["g15"]+=miss>=15
                    if st["last_close"] and st["last_close"]>0 and c[0]>0:st["jumps"].append(abs(c[0]/st["last_close"]-1)*10000)
                if len(t)>1:
                    miss=np.maximum(np.rint(np.diff(t)/60_000_000_000).astype(int)-1,0)
                    if miss.size:st["longest"]=max(st["longest"],int(miss.max()));st["g2"]+=int((miss>=2).sum());st["g5"]+=int((miss>=5).sum());st["g15"]+=int((miss>=15).sum())
                    prev=c[:-1];cur=c[1:];ok=np.isfinite(prev)&np.isfinite(cur)&(prev>0)&(cur>0);st["jumps"].extend((np.abs(cur[ok]/prev[ok]-1)*10000).tolist())
                st["count"]+=len(t);st["volume"]+=float(np.nansum(v));st["last_ns"]=int(t[-1]);st["last_close"]=float(c[-1]) if np.isfinite(c[-1]) else st["last_close"]
        if i%25==0 or i==582:print(f"[AUDIT] processed={i}/582 rows={sum(rows.values())}",flush=True)
    if any(part[s]!=97 for s in SYMBOLS):raise AuditError(f"partition counts {dict(part)}")
    expected=defaultdict(int)
    for (s,d,se),st in daily.items():expected[(d,se)]=max(expected[(d,se)],st["count"])
    daily_rows=[];gap_rows=[]
    for (s,d,se),st in sorted(daily.items()):
        ex=expected[(d,se)];cov=st["count"]/ex if ex else 0
        daily_rows.append({"symbol":s,"broker_trade_date":d,"session":se,"observed_minute_count":st["count"],"expected_minute_count":ex,"missing_minute_count":max(ex-st["count"],0),"coverage_ratio":cov,"daily_volume":st["volume"]})
        gap_rows.append({"symbol":s,"broker_trade_date":d,"session":se,"longest_missing_gap_minutes":st["longest"],"gap_count_ge_2m":st["g2"],"gap_count_ge_5m":st["g5"],"gap_count_ge_15m":st["g15"]})
    daily_df=pd.DataFrame(daily_rows);gap_df=pd.DataFrame(gap_rows)
    ss=[];volrows=[];jrows=[];tm=[]; ts_unique={}
    clean=dup==0 and bad==0 and tz_ok
    for s in SYMBOLS:
        for se in SESSIONS:
            dd=daily_df[(daily_df.symbol==s)&(daily_df.session==se)]; cov=dd.coverage_ratio.to_numpy(float); dv=dd.daily_volume.to_numpy(float)
            vv=np.concatenate(volumes[(s,se)]) if volumes[(s,se)] else np.empty(0); tt=np.unique(np.concatenate(timestamps[(s,se)])) if timestamps[(s,se)] else np.empty(0,dtype=np.int64); ts_unique[(s,se)]=tt
            jj=np.array([x for (ssym,d,sess),st in daily.items() if ssym==s and sess==se for x in st["jumps"]],dtype=float)
            med=float(np.nanmedian(cov)) if cov.size else 0;p05=q(cov,.05);zero=float((vv==0).mean()) if vv.size else 0;medv=float(np.nanmedian(vv)) if vv.size else 0
            tr=tradability(se,len(tt),med,p05,zero,medv,clean)
            gg=gap_df[(gap_df.symbol==s)&(gap_df.session==se)]
            ss.append({"symbol":s,"session":se,"first_timestamp_utc":utc_z(int(tt.min())) if tt.size else "","last_timestamp_utc":utc_z(int(tt.max())) if tt.size else "","active_trade_day_count":len(dd),"total_row_count":rows[s],"session_row_count":len(tt),"median_daily_coverage_ratio":med,"p05_daily_coverage_ratio":p05,"worst_daily_coverage_ratio":float(cov.min()) if cov.size else 0,"days_below_99_percent":int((cov<.99).sum()),"days_below_95_percent":int((cov<.95).sum()),"longest_missing_gap_minutes":int(gg.longest_missing_gap_minutes.max()) if len(gg) else 0,"tradability":tr})
            volrows.append({"symbol":s,"session":se,"row_count":len(vv),"median_minute_volume":medv,"mean_minute_volume":float(np.nanmean(vv)) if vv.size else 0,"p10_minute_volume":q(vv,.1),"p50_minute_volume":q(vv,.5),"p90_minute_volume":q(vv,.9),"zero_volume_row_count":int((vv==0).sum()),"zero_volume_share":zero,"median_daily_volume":float(np.nanmedian(dv)) if dv.size else 0,"p10_daily_volume":q(dv,.1)})
            jrows.append({"symbol":s,"session":se,"return_observation_count":len(jj),"p95_abs_return_bps":q(jj,.95),"p99_abs_return_bps":q(jj,.99),"max_abs_return_bps":float(jj.max()) if jj.size else 0,"jump_count_ge_50bps":int((jj>=50).sum()),"jump_count_ge_100bps":int((jj>=100).sum()),"jump_count_ge_300bps":int((jj>=300).sum())})
            tm.append({"symbol":s,"session":se,"tradability":tr,"median_daily_coverage_ratio":med,"p05_daily_coverage_ratio":p05,"zero_volume_share":zero,"median_minute_volume":medv})
    align_rows=[]; amap=defaultdict(dict)
    for name,a,b in PAIRS:
        for se in SESSIONS:
            m=alignment(ts_unique[(a,se)],ts_unique[(b,se)]);align_rows.append({"pair":name,"source_symbol":a,"target_symbol":b,"session":se,**m});amap[name][se]=m["alignment_ratio"]
    six={}
    for se in SESSIONS:
        arr=[ts_unique[(s,se)] for s in SYMBOLS];common=reduce(lambda x,y:np.intersect1d(x,y,assume_unique=True),arr) if all(len(x) for x in arr) else np.empty(0,dtype=np.int64);src=max(map(len,arr));ratio=len(common)/src if src else 0;six[se]=ratio
        align_rows.append({"pair":"SIX_SYMBOL_COMMON","source_symbol":"MAX_OF_SIX","target_symbol":"ALL_SIX","session":se,"source_row_count":src,"target_row_count":min(map(len,arr)),"aligned_row_count":len(common),"alignment_ratio":ratio,"missing_execution_timestamp_count":src-len(common),"common_coverage_start":utc_z(int(common[0])) if len(common) else "","common_coverage_end":utc_z(int(common[-1])) if len(common) else ""})
    ssdf=pd.DataFrame(ss);vdf=pd.DataFrame(volrows);jdf=pd.DataFrame(jrows);tdf=pd.DataFrame(tm);adf=pd.DataFrame(align_rows)
    rth={r.symbol:r.tradability for r in tdf.itertuples() if r.session=="RTH"}; rr={p:float(amap[p]["RTH"]) for p in RTH_REQUIRED}; ready,failed=fast3_gate(rth,rr,dup,bad,tz_ok,bd_ok)
    result.mkdir(parents=True,exist_ok=True)
    outputs={"symbol_session":result/"v22_050_symbol_session_audit.csv","daily":result/"v22_050_daily_coverage.csv","gap":result/"v22_050_gap_audit.csv","volume":result/"v22_050_volume_audit.csv","jump":result/"v22_050_price_jump_audit.csv","alignment":result/"v22_050_alignment_audit.csv","matrix":result/"v22_050_tradability_matrix.csv","summary":result/"v22_050_summary.json","manifest":result/"v22_050_run_manifest.json"}
    ssdf.to_csv(outputs["symbol_session"],index=False,encoding="utf-8-sig");daily_df.to_csv(outputs["daily"],index=False,encoding="utf-8-sig");gap_df.to_csv(outputs["gap"],index=False,encoding="utf-8-sig");vdf.to_csv(outputs["volume"],index=False,encoding="utf-8-sig");jdf.to_csv(outputs["jump"],index=False,encoding="utf-8-sig");adf.to_csv(outputs["alignment"],index=False,encoding="utf-8-sig");tdf.to_csv(outputs["matrix"],index=False,encoding="utf-8-sig")
    after={str(p):sha256(p) for p in files}
    if before!=after:raise AuditError("canonical changed during read-only audit")
    nonrth={s:{r.session:r.tradability for r in tdf.itertuples() if r.symbol==s and r.session!="RTH"} for s in SYMBOLS}
    summary={"version":VERSION,"final_status":"PASS" if ready else "INCONCLUSIVE","final_decision":"RTH_DATA_READY_FOR_FAST3_BACKTEST_NON_RTH_RESTRICTED_BY_OBSERVED_LIQUIDITY" if ready else "DATA_AUDIT_COMPLETED_BUT_FAST3_BACKTEST_GATE_NOT_MET","v22_049_acceptance_path":str(acceptance),"v22_049_acceptance_sha256":sha256(acceptance),"v22_049_baseline_validated":True,"canonical_parquet_count":582,"symbol_count":6,"row_count_by_symbol":{f"US.{s}":rows[s] for s in SYMBOLS},"partition_count_by_symbol":dict(part),"earliest_timestamp_by_symbol":{f"US.{s}":utc_z(earliest[s]) for s in SYMBOLS},"latest_timestamp_by_symbol":{f"US.{s}":utc_z(latest[s]) for s in SYMBOLS},"rth_tradability_by_symbol":rth,"non_rth_tradability_by_symbol":nonrth,"rth_alignment_ratios":rr,"six_symbol_alignment_ratio_by_session":six,"duplicate_count":dup,"invalid_ohlc_count":bad,"timezone_validation_pass":tz_ok,"broker_trade_date_validation_pass":bd_ok,"data_ready_for_fast3_backtest":ready,"broker_action_allowed":False,"official_adoption_allowed":False,"paper_trading_allowed":False,"failed_gate_names":failed,"canonical_files_modified":False,"raw_files_modified":False,"open_d_called":False,"history_download_executed":False,"coverage_expected_minute_method":"max observed minute count across six frozen symbols for each broker_trade_date/session"}
    atomic_json(outputs["summary"],summary);atomic_json(outputs["manifest"],{"version":VERSION,"generated_at_utc":datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),"outputs":{k:str(v) for k,v in outputs.items()},"read_only":True})
    print(f"FINAL_STATUS={summary['final_status']}");print(f"FINAL_DECISION={summary['final_decision']}");print("FILES_MODIFIED=None");print("V22_049_BASELINE_VALIDATED=True");print("CANONICAL_FILES_MODIFIED=False");print("RAW_FILES_MODIFIED=False");print("OPEN_D_CALLED=False");print("HISTORY_DOWNLOAD_EXECUTED=False");print("CANONICAL_PARQUET_COUNT=582");print("SYMBOL_COUNT=6");print("ROW_COUNT_BY_SYMBOL="+json.dumps(summary["row_count_by_symbol"],ensure_ascii=False));print("RTH_TRADABILITY_BY_SYMBOL="+json.dumps(rth,ensure_ascii=False));print("NON_RTH_TRADABILITY_BY_SYMBOL="+json.dumps(nonrth,ensure_ascii=False));print("RTH_ALIGNMENT_RATIOS="+json.dumps(rr,ensure_ascii=False));print(f"SIX_SYMBOL_ALIGNMENT_RATIO={six['RTH']}");print(f"DATA_READY_FOR_FAST3_BACKTEST={ready}");print("BROKER_ACTION_ALLOWED=False");print("OFFICIAL_ADOPTION_ALLOWED=False");print("PAPER_TRADING_ALLOWED=False");print("FAILED_GATE_NAMES="+",".join(failed));print(f"SUMMARY_PATH={outputs['summary']}");print(f"RESULT_DIRECTORY={result}")
    return 0

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--acceptance-path",default=r"D:\us-tech-quant-results\v22\V22.049_FAST3_SIX_ETF_24H_MINUTE_DATA_INGEST_R1\v22_049_acceptance_snapshot.json");ap.add_argument("--canonical-root",default=r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical");ap.add_argument("--result-dir",default=r"D:\us-tech-quant-results\v22\V22.050_FAST3_SIX_ETF_MINUTE_TRADABILITY_AUDIT_R1");ap.add_argument("--execute",action="store_true");a=ap.parse_args()
    if not a.execute:print("FINAL_STATUS=BLOCKED_EXECUTE_FLAG_REQUIRED");return 2
    try:return run(Path(a.acceptance_path),Path(a.canonical_root),Path(a.result_dir))
    except Exception as e:print("FINAL_STATUS=FAIL");print(f"ERROR_TYPE={type(e).__name__}");print(f"ERROR={e}");return 1
if __name__=="__main__":raise SystemExit(main())
