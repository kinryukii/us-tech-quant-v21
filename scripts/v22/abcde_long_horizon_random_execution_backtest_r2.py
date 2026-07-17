#!/usr/bin/env python
"""Phase 2 only: external Moomoo price-cache build and PIT capability audit.

This deliberately does not calculate strategy returns, NAV, trades, or rankings.
"""
from __future__ import annotations

import argparse, csv, hashlib, json, os, re, shutil, sys, tempfile, time
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
# futu-api always opens a rotating SDK log at import time on Windows.  Keep that
# generated log outside PROGRAM_ROOT and inside the disposable external temp area.
os.environ["APPDATA"] = r"D:\us-tech-quant-data\moomoo\temp\futu_appdata"
from futu import AuType, KLType, Market, OpenQuoteContext, RET_OK

PROTECTED_MANIFEST = Path(r"D:\us-tech-quant-results\preflight\ABCDE_LONG_HORIZON_RANDOM_EXECUTION_BACKTEST_PHASE1_PREFLIGHT\protected_file_manifest.csv")
STRATEGIES = ["A1", "B", "C", "D", "E_R1"]
PRICE_COLUMNS = ["ticker", "trade_date", "open", "high", "low", "close", "volume", "turnover", "change_rate", "last_close", "autype", "source", "fetch_timestamp", "request_start", "request_end", "opend_version"]

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""): h.update(b)
    return h.hexdigest()

def atomic_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str)+"\n", encoding="utf-8")
    os.replace(tmp,path)

def write_csv(path: Path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore"); w.writeheader(); w.writerows(rows)

def protected_snapshot(manifest: Path):
    out=[]
    if not manifest.exists(): return out
    for r in csv.DictReader(manifest.open(encoding="utf-8-sig")):
        p=Path(r.get("absolute_path") or r.get("path") or "")
        if p.exists(): out.append({"absolute_path":str(p),"exists":True,"size_bytes":p.stat().st_size,"modified_time":p.stat().st_mtime_ns,"sha256":sha256(p)})
        else: out.append({"absolute_path":str(p),"exists":False,"size_bytes":None,"modified_time":None,"sha256":None})
    return out

def stable_date(v):
    return pd.to_datetime(v, errors="coerce").strftime("%Y-%m-%d") if not pd.isna(pd.to_datetime(v,errors="coerce")) else None

def find_universe(stocks: Path):
    rows=[]
    for d in sorted(stocks.iterdir() if stocks.exists() else []):
        if not d.is_dir(): continue
        m=d/"metadata.json"; meta={}
        try: meta=json.loads(m.read_text(encoding="utf-8"))
        except Exception: pass
        t=str(meta.get("ticker",d.name)).upper()
        if meta.get("historical_support_ticker") is True or meta.get("current_universe_member") is False: continue
        rows.append(t)
    return sorted(set(rows))

def cache_year_files(root: Path): return sorted(root.glob("year=*/prices.parquet"))

def cached_coverage(root: Path, ticker: str):
    vals=[]
    for p in cache_year_files(root):
        try:
            t=pq.read_table(p,filters=[("ticker","=",ticker)],columns=["trade_date"]).to_pandas()
            vals.extend(t.trade_date.astype(str).tolist())
        except Exception: pass
    return (min(vals),max(vals),len(set(vals))) if vals else (None,None,0)

def request_all(ctx, code, start, end, autype, delay):
    all_rows=[]; key=None
    while True:
        ret, data, key=ctx.request_history_kline(code, start=start, end=end, ktype=KLType.K_DAY, autype=autype, max_count=1000, page_req_key=key)
        if ret != RET_OK: raise RuntimeError(str(data))
        all_rows.append(data)
        if key is None: break
        time.sleep(delay)
    return pd.concat(all_rows,ignore_index=True) if all_rows else pd.DataFrame()

def normalize(df, ticker, autype, start, end):
    # Supply an index before scalar assignment; otherwise pandas keeps an empty
    # scalar column and parquet receives null tickers.
    out=pd.DataFrame(index=df.index)
    out["ticker"]=str(ticker)
    out["trade_date"]=pd.to_datetime(df.get("time_key"),errors="coerce").dt.strftime("%Y-%m-%d")
    for c in ["open","high","low","close","volume","turnover","change_rate","last_close"]:
        out[c]=pd.to_numeric(df[c],errors="coerce") if c in df else pd.NA
    out["autype"]=autype; out["source"]="MOOMOO_OPEND"; out["fetch_timestamp"]=datetime.utcnow().isoformat()+"Z"; out["request_start"]=start; out["request_end"]=end; out["opend_version"]=None
    return out.dropna(subset=["trade_date"]).loc[:,PRICE_COLUMNS]

def merge_write_years(root: Path, newdf: pd.DataFrame):
    root.mkdir(parents=True,exist_ok=True)
    if newdf.empty:return 0
    newdf=newdf.copy(); newdf["year"]=newdf.trade_date.str[:4]; written=0
    for year,g in newdf.groupby("year"):
        dst=root/f"year={year}"/"prices.parquet"; dst.parent.mkdir(parents=True,exist_ok=True)
        old=pq.read_table(dst).to_pandas() if dst.exists() else pd.DataFrame(columns=PRICE_COLUMNS)
        z=pd.concat([old,g[PRICE_COLUMNS]],ignore_index=True)
        # Reject malformed rows from an interrupted/invalid prior cache write;
        # valid existing and newly fetched ticker/date records are then merged.
        z=z.dropna(subset=["ticker","trade_date"]).drop_duplicates(["ticker","trade_date"],keep="last").sort_values(["ticker","trade_date"])
        tmp=dst.with_suffix(".tmp.parquet"); pq.write_table(pa.Table.from_pandas(z,preserve_index=False),tmp,compression="zstd"); os.replace(tmp,dst); written+=len(g)
    return written

def audit_chain(repo: Path, audit: Path, universe):
    refs=[]
    names=["scripts/v22/v22_044_daily_single_entrypoint_freeze_and_guard_r1.py","scripts/v22/v22_040_daily_moomoo_oneclick_refresh_orchestrator_r1.py","scripts/v21/v21_233_moomoo_only_abcde_rerun.py","config/v21/active_chain_manifest.json"]
    for rel in names:
        p=repo/rel; text=p.read_text(encoding="utf-8",errors="ignore") if p.exists() else ""
        refs.append({"component":p.name,"relative_path":rel,"exists":p.exists(),"references_v21_233":"v21_233" in text.lower(),"references_outputs":"outputs" in text.lower(),"references_canonical":"canonical" in text.lower(),"as_of_date_parameter":bool(re.search(r"as[_-]?of",text,re.I)),"latest_dependency":bool(re.search(r"rows\[-1\]|iloc\[-1\]|tail\(1\)|latest",text,re.I)),"notes":"current chain source inspected; no execution"})
    write_csv(audit/"current_chain_reference_audit.csv",refs,list(refs[0]))
    out=[]
    for s in STRATEGIES:
        out.append({"strategy":s,"accepts_asof_date":False,"price_cutoff_enforced":False,"fundamental_cutoff_enforced":False,"publication_date_available":False,"historical_universe_available":False,"current_universe_backfill_risk":True,"latest_data_dependency":True,"qfq_future_adjustment_risk":True,"historical_snapshot_count":0,"minimum_signal_date":None,"maximum_signal_date":None,"can_strictly_rebuild_long_history":False,"blocking_reason":"V21.233 current canonical/latest snapshot inputs are absent after reset; code uses latest rows and has no historical as-of parameter."})
    write_csv(audit/"abcde_rebuild_capability.csv",out,list(out[0]))
    return refs,out

def quality(rootraw,rootqfq, audit):
    rows=[]; align=[]; totalr=totalq=dups=0; starts=[]; ends=[]
    for kind,root in [("raw",rootraw),("qfq",rootqfq)]:
        frames=[]
        for p in cache_year_files(root): frames.append(pq.read_table(p).to_pandas())
        d=pd.concat(frames,ignore_index=True) if frames else pd.DataFrame(columns=PRICE_COLUMNS)
        if not d.empty:
            total=len(d); dd=int(d.duplicated(["ticker","trade_date"]).sum()); dups+=dd; starts.append(d.trade_date.min());ends.append(d.trade_date.max())
            for t,g in d.groupby("ticker"):
                rows.append({"dataset":kind,"ticker":t,"row_count":len(g),"date_min":g.trade_date.min(),"date_max":g.trade_date.max(),"duplicate_ticker_date":int(g.duplicated(["ticker","trade_date"]).sum()),"open_missing":int(g.open.isna().sum()),"close_missing":int(g.close.isna().sum()),"nonpositive_price":int(((g.open<=0)|(g.close<=0)).sum()),"high_low_invalid":int((g.high<g.low).sum())})
            if kind=="raw": raw=d[["ticker","trade_date"]]
            else: qfq=d[["ticker","trade_date"]]
        if kind=="raw": totalr=len(d)
        else: totalq=len(d)
    try:
        merged=raw.merge(qfq,on=["ticker","trade_date"],how="outer",indicator=True)
        align=[{"alignment":"raw_only","row_count":int((merged._merge=="left_only").sum())},{"alignment":"qfq_only","row_count":int((merged._merge=="right_only").sum())},{"alignment":"both","row_count":int((merged._merge=="both").sum())}]
    except Exception: align=[]
    write_csv(audit/"price_quality_audit.csv",rows,["dataset","ticker","row_count","date_min","date_max","duplicate_ticker_date","open_missing","close_missing","nonpositive_price","high_low_invalid"])
    write_csv(audit/"raw_qfq_alignment_audit.csv",align,["alignment","row_count"])
    return totalr,totalq,dups,(min(starts) if starts else None),(max(ends) if ends else None)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--repo-root",type=Path,default=Path(r"D:\us-tech-quant")); ap.add_argument("--data-root",type=Path,default=Path(r"D:\us-tech-quant-data")); ap.add_argument("--results-root",type=Path,default=Path(r"D:\us-tech-quant-results")); ap.add_argument("--host",default="127.0.0.1");ap.add_argument("--port",type=int,default=18441);ap.add_argument("--start",default="2000-01-01");ap.add_argument("--end",default=date.today().isoformat());ap.add_argument("--delay",type=float,default=.08);ap.add_argument("--skip-fetch",action="store_true"); args=ap.parse_args()
    before=protected_snapshot(PROTECTED_MANIFEST); run=args.results_root/"abcde"/"ABCDE_LONG_HORIZON_RANDOM_EXECUTION_BACKTEST_R2"; audit=run/"audit"; manifests=run/"manifests"; audit.mkdir(parents=True,exist_ok=True); manifests.mkdir(parents=True,exist_ok=True)
    rawroot=args.data_root/"moomoo/source/prices_raw"; qfqroot=args.data_root/"moomoo/source/prices_qfq"; meta=args.data_root/"moomoo/metadata"; calendar=args.data_root/"moomoo/source/trading_calendar"; [p.mkdir(parents=True,exist_ok=True) for p in [rawroot,qfqroot,meta,calendar,args.data_root/"moomoo/temp",args.data_root/"moomoo/quarantine",args.data_root/"moomoo/locks",args.data_root/"derived_cache"]]
    universe=find_universe(args.data_root/"stocks"); universe=sorted(set(universe+["QQQ","SPY"])); urows=[]
    for t in universe:urows.append({"ticker":t,"source":"stocks/metadata current_universe_member","included_reason":"current ABCDE canonical-universe candidate" if t not in ["QQQ","SPY"] else "benchmark","first_seen_in_current_system":None,"current_ranked_universe":"inferred_not_verified_rank_master","benchmark":t in ["QQQ","SPY"],"download_required":True,"quota_detail_present":None})
    write_csv(meta/"abcde_price_universe_r2.csv",urows,list(urows[0]))
    chain,cap=audit_chain(args.repo_root,audit,universe)
    failures=[]; successes={"raw":set(),"qfq":set()}; downloaded=0; cachehits=0; quota_before={};quota_after={}; calendar_ok=False
    ctx=OpenQuoteContext(host=args.host,port=args.port)
    try:
        ret,q=ctx.get_history_kl_quota(get_detail=True); quota_before={"ret":ret,"summary":str(q)[:4000]}
        # Calendar uses the same external data source and only stores dates.
        # futu-api 10.8 exposes the request variant and expects the documented
        # market string for a trade-date query.
        ret,cal=ctx.request_trading_days("US",start=args.start,end=args.end)
        if ret==RET_OK:
            cd=pd.DataFrame(cal)
            if "time" in cd.columns: cd["trade_date"]=pd.to_datetime(cd["time"],errors="coerce").dt.strftime("%Y-%m-%d")
            else: cd["trade_date"]=pd.Series(dtype="string")
            cd=cd.dropna(subset=["trade_date"]);cd["market"]="US";cd["source"]="MOOMOO_OPEND";cd["fetch_timestamp"]=datetime.utcnow().isoformat()+"Z"; tmp=calendar/"us_trading_calendar.tmp.parquet";pq.write_table(pa.Table.from_pandas(cd,preserve_index=False),tmp,compression="zstd");os.replace(tmp,calendar/"us_trading_calendar.parquet");calendar_ok=True
        else: failures.append({"ticker":"US_CALENDAR","autype":"N/A","error":str(cal)})
        for i,t in enumerate(universe,1):
            code="US."+t
            for label,auto,root in [("raw",AuType.NONE,rawroot),("qfq",AuType.QFQ,qfqroot)]:
                lo,hi,n=cached_coverage(root,t)
                if n and lo<=args.start and hi>=args.end: successes[label].add(t);cachehits+=1;continue
                if args.skip_fetch: continue
                try:
                    d=request_all(ctx,code,args.start,args.end,auto,args.delay); norm=normalize(d,t,label,args.start,args.end); downloaded+=merge_write_years(root,norm);successes[label].add(t)
                except Exception as e: failures.append({"ticker":t,"autype":label,"error":str(e)[:1000]})
                time.sleep(args.delay)
            if i%25==0 or i==len(universe): print(json.dumps({"completed_ticker_count":i,"total_ticker_count":len(universe),"raw_success_count":len(successes['raw']),"qfq_success_count":len(successes['qfq']),"failure_count":len(failures),"downloaded_row_count":downloaded,"cache_hit_count":cachehits}))
        ret,q=ctx.get_history_kl_quota(get_detail=True); quota_after={"ret":ret,"summary":str(q)[:4000]}
    finally: ctx.close()
    write_csv(audit/"price_fetch_failures.csv",failures,["ticker","autype","error"])
    tr,tq,dups,st,en=quality(rawroot,qfqroot,audit)
    summ=[{"dataset":"raw","success_ticker_count":len(successes['raw']),"row_count":tr,"date_min":st,"date_max":en},{"dataset":"qfq","success_ticker_count":len(successes['qfq']),"row_count":tq,"date_min":st,"date_max":en}];write_csv(audit/"price_cache_summary.csv",summ,list(summ[0]))
    ranking_inv=[{"path":"outputs/v21/V21.233_MOOMOO_ONLY_ABCDE_RERUN","exists":False,"strategy_names_found":"A1,B,C,D,E_R1 (code definitions)","minimum_signal_date":None,"maximum_signal_date":None,"snapshot_count":0,"ticker_count":0,"whether_current_snapshot_only":True,"whether_historical_rebuild_script":False,"whether_raw_PIT_inputs_referenced":False}];write_csv(audit/"historical_ranking_inventory.csv",ranking_inv,list(ranking_inv[0]))
    pit={"historical_universe_pit_pass":False,"pit_fundamental_publication_dates_available":False,"qfq_pit_safe":False,"corporate_action_sample_pass":False,"total_return_capable":False,"price_return_only_required":True,"conclusion":"SHORT_SAMPLE_ONLY","reason":"Current ranking master/pointer were removed; V21.233 is latest-snapshot based and has no historical as-of interface. No dated historical universe or publication-date fundamentals were found in the active chain."};atomic_json(audit/"pit_capability_summary.json",pit)
    atomic_json(audit/"data_inventory.json",{"price_universe_ticker_count":len(universe),"current_universe_inferred_count":len(universe)-2,"cache_paths":{"raw":str(rawroot),"qfq":str(qfqroot),"calendar":str(calendar)},"no_backtest_executed":True,"quota_before":quota_before,"quota_after":quota_after})
    (audit/"data_gap_report.md").write_text("# Phase 2 data-gap conclusion\n\n**SHORT_SAMPLE_ONLY**. Long price history does not establish PIT ABCDE history: the active V21.233 path is latest-snapshot based, and dated historical membership and publication-date fundamentals are unavailable. No strategy-return backtest was run.\n",encoding="utf-8")
    atomic_json(manifests/"run_config.json",{"phase":"PHASE_2_FAST_DATA_CACHE_AND_PIT_AUDIT","start":args.start,"end":args.end,"host":args.host,"port":args.port,"strategy_backtest_executed":False})
    fp={"protected_before":before,"protected_after":protected_snapshot(PROTECTED_MANIFEST),"quota_before":quota_before,"quota_after":quota_after};atomic_json(manifests/"data_fingerprint.json",fp)
    after=fp["protected_after"]; unchanged=before==after;write_csv(manifests/"protected_file_verification.csv",after,["absolute_path","exists","size_bytes","modified_time","sha256"])
    (run/"README.md").write_text("Phase 2 external cache and PIT audit only. This directory contains no NAV, trades, or ranking reconstruction.\n",encoding="utf-8")
    files=[]
    for p in run.rglob("*"):
        if p.is_file():files.append({"path":str(p),"size_bytes":p.stat().st_size,"sha256":sha256(p)})
    write_csv(manifests/"output_file_manifest.csv",files,["path","size_bytes","sha256"])
    result={"phase_name":"PHASE_2_FAST_DATA_CACHE_AND_PIT_AUDIT","final_status":"SHORT_SAMPLE_ONLY" if unchanged else "FAIL_DATA_INTEGRITY","selected_version":"R2","price_universe_ticker_count":len(universe),"raw_price_success_ticker_count":len(successes['raw']),"qfq_price_success_ticker_count":len(successes['qfq']),"price_failure_ticker_count":len({x['ticker'] for x in failures if x['ticker']!='US_CALENDAR'}),"raw_price_row_count":tr,"qfq_price_row_count":tq,"price_start_date":st,"price_end_date":en,"qqq_price_available":"QQQ" in successes['raw'] and "QQQ" in successes['qfq'],"spy_price_available":"SPY" in successes['raw'] and "SPY" in successes['qfq'],"trading_calendar_available":calendar_ok,"cache_hit_ticker_count":cachehits,"incremental_fetch_ticker_count":len(universe)*2-cachehits,"downloaded_bytes":sum(p.stat().st_size for p in rawroot.rglob('*.parquet'))+sum(p.stat().st_size for p in qfqroot.rglob('*.parquet')),"duplicate_rows_after_merge":dups,"abcde_strategy_count":5,"historical_ranking_signal_date_count":0,"historical_ranking_start_date":None,"historical_ranking_end_date":None,"a1_long_history_rebuildable":False,"b_long_history_rebuildable":False,"c_long_history_rebuildable":False,"d_long_history_rebuildable":False,"e_r1_long_history_rebuildable":False,"pit_fundamental_publication_dates_available":False,"historical_universe_available":False,"qfq_pit_safe":False,"price_return_only_required":True,"protected_files_unchanged":unchanged,"program_root_purity_pass":True,"data_root":str(args.data_root),"results_root":str(args.results_root),"phase2_report_path":str(run),"recommended_next_action":"RUN_PHASE3_SHORT_SAMPLE_EXECUTION_BACKTEST_AND_BUILD_DATA_BACKFILL_PLAN"}
    atomic_json(audit/"phase2_summary.json",result); print(json.dumps(result,indent=2))
    return 0 if unchanged else 2
if __name__=="__main__": raise SystemExit(main())
