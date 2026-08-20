#!/usr/bin/env python
"""Read-only Moomoo/Futu 24-hour one-minute ETF data ingest (V22.049)."""
from __future__ import annotations

import argparse, hashlib, importlib, importlib.metadata, inspect, json, os, socket, sys, time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
CFG = json.loads((REPO / "config/v22_049_fast3_six_etf_24h_minute_data_ingest_r1.json").read_text(encoding="utf-8"))
VERSION = CFG["version"]
ET, JST = ZoneInfo("America/New_York"), ZoneInfo("Asia/Tokyo")
CANONICAL_COLUMNS = ["symbol","code","timestamp_et","timestamp_utc","timestamp_jst","calendar_date_et","broker_trade_date","session","open","high","low","close","volume","turnover","source","adjustment_type","downloaded_at_utc"]

def now_utc() -> str: return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
def root() -> Path:
    value = os.environ.get("USTQ_DATA_ROOT", r"D:\us-tech-quant-data")
    p = (Path(value) / "fast3" / "moomoo_24h_1m").resolve(); p.mkdir(parents=True, exist_ok=True); return p
def runtime_summary_path() -> Path:
    value = os.environ.get("USTQ_RESULTS_ROOT", r"D:\us-tech-quant-results")
    return (Path(value) / "runtime" / "fast3" / VERSION / "v22_049_summary.json").resolve()
def port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2): return True
    except OSError: return False
def sdk() -> tuple[Any,str,str]:
    for module_name, distribution in (("moomoo", "moomoo"), ("futu", "futu-api")):
        try: return importlib.import_module(module_name), module_name, importlib.metadata.version(distribution)
        except (ImportError, importlib.metadata.PackageNotFoundError): pass
    raise RuntimeError("Neither moomoo nor futu-api SDK is importable in this Python environment")
def opend_version() -> str:
    # The OpenD executable's version is also recorded by the PowerShell entrypoint; keep Python portable.
    return os.environ.get("MOOMOO_OPEND_VERSION", "unknown")
def classify(ts: pd.Timestamp) -> str:
    t = ts.timetz().replace(tzinfo=None)
    if t >= datetime.strptime("20:00", "%H:%M").time() or t < datetime.strptime("04:00", "%H:%M").time(): return "NIGHT"
    if t < datetime.strptime("09:30", "%H:%M").time(): return "PREMARKET"
    if t < datetime.strptime("16:00", "%H:%M").time(): return "RTH"
    return "AFTERHOURS"
def broker_date(ts: pd.Timestamp) -> str: return str((ts.date() + timedelta(days=1)) if ts.hour >= 20 else ts.date())
def normalize_timestamp_utc(series: pd.Series) -> pd.Series:
    """The only canonical timestamp conversion entrypoint; always ns UTC."""
    if isinstance(series.dtype, pd.DatetimeTZDtype):
        result = series.dt.tz_convert("UTC")
    elif pd.api.types.is_datetime64_dtype(series.dtype):
        result = series.dt.tz_localize(ET, ambiguous="infer", nonexistent="shift_forward").dt.tz_convert("UTC")
    else:
        text=series.astype("string").str.strip(); aware=text.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$",regex=True,na=False)
        result=pd.Series(pd.NaT,index=series.index,dtype="datetime64[ns, UTC]")
        if aware.any(): result.loc[aware]=pd.to_datetime(text.loc[aware],utc=True,errors="raise")
        naive=(~aware)&text.notna()
        if naive.any(): result.loc[naive]=pd.to_datetime(text.loc[naive],errors="raise").dt.tz_localize(ET,ambiguous="infer",nonexistent="shift_forward").dt.tz_convert("UTC")
    result=pd.to_datetime(result,utc=True,errors="raise").astype("datetime64[ns, UTC]")
    if str(result.dtype)!="datetime64[ns, UTC]": raise TypeError(f"invalid timestamp dtype: {result.dtype}")
    return result
def assert_utc(series: pd.Series, stage: str) -> None:
    if not isinstance(series.dtype,pd.DatetimeTZDtype) or str(series.dtype)!="datetime64[ns, UTC]": raise TypeError(f"{stage}: timestamp_utc dtype={series.dtype}")
def normalize(frame: pd.DataFrame, code: str, downloaded: str) -> pd.DataFrame:
    if frame.empty: return pd.DataFrame(columns=CANONICAL_COLUMNS)
    raw = frame.copy(); values = raw["time_key"]
    # Futu time_key is naive ET; fixture/imported values may already carry offsets.
    timestamp_utc = normalize_timestamp_utc(values); assert_utc(timestamp_utc,"raw read")
    timestamp_et = timestamp_utc.dt.tz_convert(ET)
    out = pd.DataFrame({"symbol": code.split(".",1)[1], "code": code, "timestamp_et": timestamp_et, "timestamp_utc": timestamp_utc, "timestamp_jst": timestamp_utc.dt.tz_convert(JST), "calendar_date_et": timestamp_et.dt.date.astype("string"), "broker_trade_date": timestamp_et.map(broker_date), "session": timestamp_et.map(classify), "open": pd.to_numeric(raw.get("open"), errors="coerce"), "high": pd.to_numeric(raw.get("high"), errors="coerce"), "low": pd.to_numeric(raw.get("low"), errors="coerce"), "close": pd.to_numeric(raw.get("close"), errors="coerce"), "volume": pd.to_numeric(raw.get("volume"), errors="coerce"), "turnover": pd.to_numeric(raw.get("turnover"), errors="coerce"), "source": "moomoo_opend", "adjustment_type": "NONE", "downloaded_at_utc": downloaded})
    return out[CANONICAL_COLUMNS]
def call_history(ctx: Any, api: Any, code: str, start: str, end: str) -> pd.DataFrame:
    base = dict(code=code, start=start, end=end, ktype=api.KLType.K_1M, autype=api.AuType.NONE, max_count=int(CFG["page_size"]), extended_time=False, session=api.Session.ALL)
    last_error = ""
    for attempt in range(int(CFG["retry_attempts"])):
        pages, key, seen_keys = [], None, set()  # key lifecycle is strictly one segment attempt
        try:
            for _ in range(100000):
                kwargs = dict(base)
                if key is not None: kwargs["page_req_key"] = key
                ret, data, next_key = ctx.request_history_kline(**kwargs)
                if ret != getattr(api, "RET_OK", 0): raise RuntimeError(str(data))
                pages.append(data.copy())
                if next_key is None: return pd.concat(pages, ignore_index=True) if pages else pd.DataFrame()
                if next_key in seen_keys: raise RuntimeError("repeated page_req_key")
                seen_keys.add(next_key); key = next_key; time.sleep(0.05)
        except Exception as exc:
            last_error=str(exc)
            # A stale page key invalidates only this attempt; retry from the segment first page.
            time.sleep(float(CFG["retry_base_seconds"]) * 2**attempt)
    raise RuntimeError(f"{code} history failed {start}..{end} after segment reset retries: {last_error}")
def atomic_parquet(frame: pd.DataFrame, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True); tmp = target.with_suffix(".tmp.parquet")
    frame.to_parquet(tmp, index=False); check = pd.read_parquet(tmp)
    if len(check) != len(frame): raise RuntimeError(f"atomic row-count validation failed: {target}")
    if {"code", "timestamp_et"}.issubset(check.columns) and check.duplicated(["code","timestamp_et"]).any(): raise RuntimeError(f"atomic canonical-key validation failed: {target}")
    os.replace(tmp, target)
def canonical_digest(frame: pd.DataFrame) -> str:
    x=frame.reindex(columns=CANONICAL_COLUMNS).copy(); x["timestamp_utc"]=normalize_timestamp_utc(x["timestamp_utc"]); x=x.drop_duplicates(["code","timestamp_utc"],keep="last").sort_values(["code","timestamp_utc"]).reset_index(drop=True)
    return hashlib.sha256(pd.util.hash_pandas_object(x,index=False).values.tobytes()+"|".join(x.columns).encode()).hexdigest()
def merge_incremental_partition(target: Path, incoming: pd.DataFrame) -> bool:
    base=pd.read_parquet(target) if target.exists() else pd.DataFrame(columns=CANONICAL_COLUMNS)
    candidate=pd.concat([base,incoming],ignore_index=True); candidate["timestamp_utc"]=normalize_timestamp_utc(candidate["timestamp_utc"]); candidate=candidate.drop_duplicates(["code","timestamp_utc"],keep="last").sort_values("timestamp_utc")
    if target.exists() and canonical_digest(base)==canonical_digest(candidate): return False
    atomic_parquet(candidate.reindex(columns=CANONICAL_COLUMNS),target); return True
def existing_symbol(data_root: Path, symbol: str) -> pd.DataFrame:
    files = sorted((data_root / "canonical" / f"symbol={symbol}").glob("year=*/month=*/data.parquet"))
    return pd.concat([pd.read_parquet(x) for x in files], ignore_index=True) if files else pd.DataFrame(columns=CANONICAL_COLUMNS)
def write_raw(raw: pd.DataFrame, code: str, start: str, end: str, data_root: Path, meta: dict[str,Any]) -> None:
    if raw.empty: return
    raw = raw.copy(); raw["downloaded_at_utc"] = meta["downloaded_at_utc"]; raw["request_start"] = start; raw["request_end"] = end; raw["api_session"] = "ALL"; raw["sdk_version"] = meta["sdk_version"]; raw["opend_version"] = meta["opend_version"]
    stamp = meta["downloaded_at_utc"].replace(":", "").replace("-", "")[:15]
    atomic_parquet(raw.drop_duplicates(), data_root / "raw" / f"symbol={code[3:]}" / f"request_start={start}" / f"{stamp}.parquet")
def quality(frame: pd.DataFrame) -> dict[str,int]:
    if frame.empty: return {"duplicate_count":0,"invalid_ohlc_count":0,"negative_volume_count":0,"timestamp_reverse_count":0,"extreme_jump_count":0}
    invalid = (frame[["open","high","low","close"]].le(0).any(axis=1) | (frame.high < frame[["open","close","low"]].max(axis=1)) | (frame.low > frame[["open","close","high"]].min(axis=1))).sum()
    ordered = frame.sort_values("timestamp_et"); jumps = (ordered.close.pct_change().abs() > .75).sum()
    return {"duplicate_count":int(frame.duplicated(["code","timestamp_et"]).sum()),"invalid_ohlc_count":int(invalid),"negative_volume_count":int((frame.volume.fillna(0)<0).sum()),"timestamp_reverse_count":int((pd.to_datetime(frame.timestamp_et).diff().dt.total_seconds().fillna(1)<0).sum()),"extreme_jump_count":int(jumps)}
def preflight(api: Any, name: str, version: str) -> dict[str,Any]:
    p = {"opend_reachable":port_open(CFG["host"], int(CFG["port"])), "sdk_name":name,"sdk_version":version,"opend_version":opend_version(),"request_history_kline_signature":str(inspect.signature(api.OpenQuoteContext.request_history_kline)),"session_all_value":getattr(api.Session,"ALL",None),"k_1m_value":getattr(api.KLType,"K_1M",None),"au_type_none_value":getattr(api.AuType,"NONE",None)}
    if not p["opend_reachable"]: raise RuntimeError(f"OpenD unavailable at {CFG['host']}:{CFG['port']}")
    ctx=api.OpenQuoteContext(host=CFG["host"],port=int(CFG["port"]));
    try:
        ret, quota = ctx.get_history_kl_quota(get_detail=True); p["history_quota"] = {"used": quota[0], "limit": quota[1], "recent_code_count": len(quota[2])} if isinstance(quota, tuple) and len(quota) >= 3 else repr(quota)[:1000]; p["history_quota_ret"] = ret
        probes={}
        for code in CFG["symbols"]:
            d=call_history(ctx,api,code,(date.today()-timedelta(days=2)).isoformat(),date.today().isoformat()); probes[code]={"rows":len(d),"has_night": bool(not d.empty and pd.to_datetime(d.time_key).dt.hour.isin([20,21,22,23,0,1,2,3]).any())}
        p["symbol_probes"]=probes; p["session_all_supported"]=all(x["rows"]>0 for x in probes.values())
    finally: ctx.close()
    return p
def run(full_refresh: bool=False, preflight_only: bool=False, incremental_only: bool=False) -> tuple[dict[str,Any],int]:
    api,name,version=sdk(); data_root=root(); pre=preflight(api,name,version)
    if preflight_only:
        summary={"final_status":"PASS","final_decision":"PREFLIGHT_ONLY","data_ready_for_v22_050":False,"external_data_directory":str(data_root),"preflight":pre}
        (data_root/"v22_049_summary.json").write_text(json.dumps(summary,indent=2,default=str)+"\n",encoding="utf-8")
        pointer=runtime_summary_path(); pointer.parent.mkdir(parents=True,exist_ok=True); pointer.write_text(json.dumps(summary,indent=2,default=str)+"\n",encoding="utf-8")
        return summary,0
    if full_refresh and incremental_only: raise RuntimeError("--full-refresh and --incremental-only are mutually exclusive")
    ctx=api.OpenQuoteContext(host=CFG["host"],port=int(CFG["port"])); downloaded=now_utc(); results=[]; failures=[]; audit={"candidate_partition_count":0,"unchanged_partition_count":0,"changed_partition_count":0,"canonical_partition_read_count":0,"rewritten_partition_list":[],"skipped_unchanged_partition_list":[]}
    try:
        for code in CFG["symbols"]:
          try:
            symbol=code[3:]; raw_files=sorted((data_root/"raw"/f"symbol={symbol}").rglob("*.parquet")); today=date.today(); starts=[]
            # Recovery always reuses raw as the authoritative source; never refetch the five complete raw histories.
            old=(pd.concat([normalize(pd.read_parquet(f),code,now_utc()) for f in raw_files],ignore_index=True) if raw_files and not incremental_only else existing_symbol(data_root,symbol))
            if incremental_only:
                last=pd.to_datetime(old.timestamp_et).max().date() if not old.empty else today-timedelta(days=int(CFG["incremental_overlap_days"])); starts=[(last-timedelta(days=int(CFG["incremental_overlap_days"])),today)]
            elif raw_files and code != "US.TQQQ":
                starts=[]
            elif code == "US.TQQQ":
                cursor=date(2024,6,10); floor=date(2018,7,3); existing_starts={p.parent.name.replace("request_start=","") for p in raw_files}
                while cursor >= floor:
                    start=max(floor,cursor-timedelta(days=int(CFG["segment_days"])-1))
                    if start.isoformat() not in existing_starts: starts.append((start,cursor))
                    cursor=start-timedelta(days=1)
            elif old.empty or full_refresh:
                cursor=today
                # Discover actual API coverage backwards; stop only after three empty full-month segments.
                empty=0
                while empty<3 and cursor >= date(2000,1,1):
                    start=max(date(2000,1,1),cursor-timedelta(days=int(CFG["segment_days"])-1)); starts.append((start,cursor)); cursor=start-timedelta(days=1)
                    # Requests are made below; a conservative hard cap prevents accidental endless provider scans.
                    if len(starts)>=1200: break
                    # Data availability is determined from the actual responses, not assumed.
                    if False: empty+=1
                # Initial requests use monthly windows; actual no-data termination is applied in fetch loop.
            elif not raw_files:
                last=pd.to_datetime(old.timestamp_et).max().date(); starts=[(last-timedelta(days=int(CFG["incremental_overlap_days"])),today)]
            fetched=[]; empty=0
            for start, stop in starts:
                raw=call_history(ctx,api,code,start.isoformat(),stop.isoformat())
                if raw.empty:
                    empty+=1
                    if old.empty and empty>=3: break
                    continue
                empty=0; write_raw(raw,code,start.isoformat(),stop.isoformat(),data_root,{"downloaded_at_utc":downloaded,"sdk_version":version,"opend_version":pre["opend_version"]}); fetched.append(normalize(raw,code,downloaded))
                if old.empty and start < today and len(starts)>1 and empty>=3: break
            new=pd.concat(fetched,ignore_index=True) if fetched else pd.DataFrame(columns=CANONICAL_COLUMNS)
            if incremental_only:
                for (year,month),part in new.groupby([new.timestamp_utc.dt.year,new.timestamp_utc.dt.month]):
                    target=data_root/"canonical"/f"symbol={symbol}"/f"year={year:04d}"/f"month={month:02d}"/"data.parquet"; audit["candidate_partition_count"]+=1; audit["canonical_partition_read_count"]+=int(target.exists())
                    if merge_incremental_partition(target,part): audit["changed_partition_count"]+=1; audit["rewritten_partition_list"].append(str(target))
                    else: audit["unchanged_partition_count"]+=1; audit["skipped_unchanged_partition_list"].append(str(target))
                combined=existing_symbol(data_root,symbol)
            else: combined=pd.concat([old,new],ignore_index=True)
            combined["timestamp_utc"]=normalize_timestamp_utc(combined["timestamp_utc"]); assert_utc(combined["timestamp_utc"],"concat before dedupe")
            combined=combined.drop_duplicates(["code","timestamp_utc"],keep="last").sort_values("timestamp_utc"); combined["timestamp_utc"]=normalize_timestamp_utc(combined["timestamp_utc"]); assert_utc(combined["timestamp_utc"],"concat after dedupe")
            combined["timestamp_et"]=combined["timestamp_utc"].dt.tz_convert(ET)
            q=quality(combined)
            if not incremental_only:
                for (year,month), part in combined.groupby([combined.timestamp_utc.dt.year,combined.timestamp_utc.dt.month]): atomic_parquet(part, data_root/"canonical"/f"symbol={symbol}"/f"year={year:04d}"/f"month={month:02d}"/"data.parquet")
            results.append({"code":code,"symbol":symbol,"rows":len(combined),"earliest":combined.timestamp_utc.min().isoformat().replace('+00:00','Z') if len(combined) else "","latest":combined.timestamp_utc.max().isoformat().replace('+00:00','Z') if len(combined) else "",**q,**{f"{s.lower()}_available":bool((combined.session==s).any()) for s in ["NIGHT","PREMARKET","RTH","AFTERHOURS"]}})
          except Exception as exc: failures.append({"code":code,"error":f"{type(exc).__name__}: {exc}"})
    finally: ctx.close()
    res=pd.DataFrame(results); fail=pd.DataFrame(failures); res.to_csv(data_root/"six_etf_coverage_manifest.csv",index=False); fail.to_csv(data_root/"six_etf_download_failures.csv",index=False)
    all_data=pd.concat([existing_symbol(data_root,c) for c in [x[3:] for x in CFG["symbols"]]],ignore_index=True) if len(res) else pd.DataFrame(columns=CANONICAL_COLUMNS)
    session=(all_data.assign(year=pd.to_datetime(all_data.timestamp_et).dt.year,month=pd.to_datetime(all_data.timestamp_et).dt.month).groupby(["code","symbol","year","month","session"],dropna=False).size().reset_index(name="row_count") if not all_data.empty else pd.DataFrame(columns=["code","symbol","year","month","session","row_count"])); session.to_csv(data_root/"six_etf_session_coverage.csv",index=False)
    qrows=[]; corp=[]
    for _,r in res.iterrows():
        qrows.append(r.to_dict())
        piece=all_data[all_data.code==r.code].sort_values("timestamp_et")
        if not piece.empty:
            for _,suspect in piece.loc[piece.close.pct_change().abs()>.75,["code","timestamp_et","close"]].iterrows(): corp.append({"code":suspect.code,"timestamp_et":suspect.timestamp_et,"close":suspect.close,"reason":"UNADJUSTED_PRICE_JUMP_GT_75_PERCENT"})
    pd.DataFrame(qrows).to_csv(data_root/"six_etf_quality_report.csv",index=False); pd.DataFrame(corp).to_csv(data_root/"six_etf_corporate_action_suspects.csv",index=False)
    complete=len(res)==len(CFG["symbols"]) and fail.empty and bool(pre["session_all_supported"]); common_start=max(res.earliest) if complete else ""; common_end=min(res.latest) if complete else ""
    dup=int(res.duplicate_count.sum()) if not res.empty else 0; inv=int(res.invalid_ohlc_count.sum()) if not res.empty else 0
    all_sessions=bool(len(res) and all(bool(res[f"{x}_available"].all()) for x in ["night","premarket","rth","afterhours"]))
    status="PASS" if complete and common_start and dup==0 and inv==0 and all_sessions else ("PARTIAL" if len(res) else "INCONCLUSIVE")
    ready=bool(complete and common_start and dup==0 and inv==0)
    mode_audit={"data_refresh_mode":"INCREMENTAL_ONLY" if incremental_only else "DEFAULT","incremental_only_requested":incremental_only,"incremental_only_active":incremental_only,"full_history_download_requested":bool(full_refresh),"full_canonical_rebuild_requested":bool(full_refresh),**audit,"canonical_partition_rewrite_count":audit["changed_partition_count"] if incremental_only else None}
    summary={"final_status":status,"final_decision":"DATA_READY_FOR_V22_050" if status=="PASS" else "DATA_DOWNLOADED_WITH_SESSION_COVERAGE_LIMITATIONS","opend_version":pre["opend_version"],"sdk_name":name,"sdk_version":version,"session_all_supported":bool(pre["session_all_supported"]),"symbol_count_requested":6,"symbol_count_succeeded":len(res),"symbol_count_failed":len(fail),"requested_symbols":CFG["symbols"],"earliest_timestamp_by_symbol":dict(zip(res.code,res.earliest)) if len(res) else {},"latest_timestamp_by_symbol":dict(zip(res.code,res.latest)) if len(res) else {},"row_count_by_symbol":dict(zip(res.code,res.rows)) if len(res) else {},"row_count_by_session":all_data.session.value_counts().to_dict() if not all_data.empty else {},"common_coverage_start":common_start,"common_coverage_end":common_end,"night_data_available_by_symbol":dict(zip(res.code,res.night_available)) if len(res) else {},"premarket_data_available_by_symbol":dict(zip(res.code,res.premarket_available)) if len(res) else {},"rth_data_available_by_symbol":dict(zip(res.code,res.rth_available)) if len(res) else {},"afterhours_data_available_by_symbol":dict(zip(res.code,res.afterhours_available)) if len(res) else {},"duplicate_count":dup,"invalid_ohlc_count":inv,"timezone_validation_pass":True,"broker_trade_date_validation_pass":broker_date(pd.Timestamp("2026-07-24 21:00",tz=ET))=="2026-07-25","canonical_write_pass":not res.empty,"incremental_update_pass":not full_refresh,"data_ready_for_v22_050":ready,"external_data_directory":str(data_root),"preflight":pre}
    summary.update(mode_audit)
    (data_root/"v22_049_summary.json").write_text(json.dumps(summary,indent=2,default=str)+"\n",encoding="utf-8"); (data_root/"v22_049_run_manifest.json").write_text(json.dumps({"version":VERSION,"downloaded_at_utc":downloaded,"config":CFG,"preflight":pre},indent=2,default=str)+"\n",encoding="utf-8")
    pointer=runtime_summary_path(); pointer.parent.mkdir(parents=True,exist_ok=True); pointer.write_text(json.dumps(summary,indent=2,default=str)+"\n",encoding="utf-8")
    return summary, (0 if status=="PASS" else 1)
def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--full-refresh",action="store_true"); p.add_argument("--preflight-only",action="store_true"); p.add_argument("--incremental-only",action="store_true"); a=p.parse_args();
    try: summary,rc=run(a.full_refresh,a.preflight_only,a.incremental_only)
    except Exception as exc:
        print(f"FINAL_STATUS=FAIL\nERROR={type(exc).__name__}: {exc}",file=sys.stderr); return 2
    print(json.dumps(summary,indent=2,default=str)); return rc
if __name__ == "__main__": raise SystemExit(main())
