"""Pilot then continue missing raw daily-K on currently occupied fixed-pool codes."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE=Path(__file__).resolve().parent
SDK=HERE/"sdk_appdata"
SDK.mkdir(exist_ok=True)
os.environ["APPDATA"]=str(SDK.resolve())
os.environ["appdata"]=str(SDK.resolve())
import moomoo  # noqa: E402

LIMITER=Path(r"D:\us-tech-quant\scripts\v21\v21_231_moomoo_only_historical_refetch_and_canonical_rebuild.py")
REBUILD=Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\scripts\run_rebuild.py")
QQQ_RAW=Path(r"D:\us-tech-quant-data\moomoo\source\prices_raw\year=2026\prices.parquet")


def import_file(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module


def quota(ctx):
    ret,payload=ctx.get_history_kl_quota(get_detail=True)
    if ret!=moomoo.RET_OK or not isinstance(payload,tuple) or len(payload)<3:
        raise RuntimeError("QUOTA_DETAIL_UNAVAILABLE:"+str(payload)[:200])
    used,remain,detail=payload
    return {"used":int(used),"remaining":int(remain),"codes":{str(x.get("code","")) for x in detail}}


def main():
    assert str(moomoo.KLType.K_DAY)=="K_DAY"
    assert str(moomoo.AuType.NONE)=="None"
    assert str(moomoo.Session.RTH)=="RTH"
    all_pool=pd.read_csv(HERE/"QUARTER_POOL_PRICE_INVENTORY.csv")
    pool=all_pool.loc[all_pool.raw_direct_last_date.fillna("").eq("2026-08-14")]
    partial=pd.read_parquet(HERE/"PARTIAL_2026_A2_TOP20_INPUT_ONLY.parquet",columns=["ticker","moomoo_transport_code"])
    frequency=partial.groupby("moomoo_transport_code").size().sort_values(ascending=False)
    necessary=set(pool.moomoo_transport_code)&set(partial.moomoo_transport_code)
    result={"requested_at_utc":datetime.now(timezone.utc).isoformat(),"request_count":0,
            "ktype":"K_DAY","autype":"NONE","session":"RTH","extended_time":False,
            "start":"2026-08-14","end":"2026-09-22","fixed_test_asof":"2026-09-23T18:40:43Z"}
    try:
        with socket.create_connection(("127.0.0.1",18441),timeout=2):
            pass
    except OSError as exc:
        result.update({"status":"OPEND_UNREACHABLE_NO_HISTORY_REQUEST",
                       "error":f"{type(exc).__name__}: {exc}",
                       "quota_detail_this_attempt":"UNAVAILABLE_NO_CONNECTION",
                       "pilot_candidate_basis":"cached_partial_top20_intersect_original_raw_last_2026_08_14",
                       "pilot_candidate_codes":len(necessary)})
        (HERE/"PILOT_REUSED_QUOTA_RECEIPT.json").write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        print(json.dumps(result,ensure_ascii=False))
        return
    ctx=moomoo.OpenQuoteContext(host="127.0.0.1",port=18441)
    try:
        before=quota(ctx)
        intersection=necessary&before["codes"]
        result.update({"quota_before":{"used":before["used"],"remaining":before["remaining"],
                                       "occupied_codes":len(before["codes"])},
                       "pilot_candidate_basis":"cached_partial_top20_intersect_original_raw_last_2026_08_14",
                       "pilot_candidate_codes":len(necessary),"pilot_currently_occupied_codes":len(intersection)})
        if not intersection:
            result["status"]="NO_OCCUPIED_NECESSARY_CODE_NO_REQUEST"
            return
        chosen=next(c for c in frequency.index if c in intersection)
        ticker=partial.loc[partial.moomoo_transport_code.eq(chosen),"ticker"].iloc[0]
        result.update({"code":chosen,"ticker":ticker})
        original=import_file("original_raw_index_pilot",REBUILD)
        index,failures=original.raw_file_index()
        assert not failures and chosen in index
        old=original.load_raw_code(chosen,index[chosen])
        old_overlap=old.loc[old.trade_date.eq("2026-08-14")]
        assert len(old_overlap)==1
        limiter_module=import_file("original_history_limiter_pilot",LIMITER)
        limiter=limiter_module.HistoryKlineLimiter()
        path=HERE/f"PILOT_{chosen.replace('.','_')}_RAW_DAY_K.parquet"
        if path.exists():
            data=pd.read_parquet(path)
            ret,page=moomoo.RET_OK,None
            result["pilot_source"]="SAVED_PRIOR_QUALIFIED_RAW_NO_REQUEST"
        else:
            limiter.acquire({"ticker":ticker,"adjustment":"none","frequency":"1d"})
            ret,data,page=ctx.request_history_kline(chosen,start=result["start"],end=result["end"],
                 ktype=moomoo.KLType.K_DAY,autype=moomoo.AuType.NONE,max_count=1000,
                 page_req_key=None,extended_time=False,session=moomoo.Session.RTH)
            result["request_count"]=1
            result["pilot_source"]="LIVE_OPEND_REQUEST"
        result["return_code"]=ret
        result["page_key_present"]=bool(page)
        after=quota(ctx)
        result["quota_after"]={k:v for k,v in after.items() if k!="codes"}
        if ret!=moomoo.RET_OK:
            result["status"]="PROVIDER_REJECTED_STOP"
            result["error"]=str(data)[:450]
            return
        if not isinstance(data,pd.DataFrame) or data.empty or page:
            result["status"]="EMPTY_OR_PAGINATED_PILOT_STOP"
            result["row_count"]=0 if not isinstance(data,pd.DataFrame) else len(data)
            return
        data["trade_date"]=pd.to_datetime(data.time_key).dt.normalize()
        if data.trade_date.min()<pd.Timestamp(result["start"]) or data.trade_date.max()>pd.Timestamp(result["end"]):
            result["status"]="DATE_SCOPE_ERROR_STOP";return
        for field in ("open","close","high","low","volume"):
            data[field]=pd.to_numeric(data[field],errors="raise")
        overlap=data.loc[data.trade_date.eq("2026-08-14")]
        if len(overlap)!=1:
            result["status"]="NO_REQUIRED_OVERLAP_STOP";return
        difference=max(abs(float(overlap[field].iloc[0])-float(old_overlap[field].iloc[0])) for field in ("open","close","high","low","volume"))
        result["overlap_max_abs_difference"]=difference
        if difference>1e-9:
            result["status"]="RAW_OVERLAP_CONFLICT_STOP";return
        if not path.exists():
            data.to_parquet(path,index=False)
        result.update({"status":"PASS_REUSED_OCCUPIED_CODE_RAW","row_count":len(data),
                       "first_date":str(data.trade_date.min().date()),"last_date":str(data.trade_date.max().date()),
                       "new_dates_after_overlap":int(data.trade_date.gt("2026-08-14").sum()),
                       "saved_path":str(path),"saved_sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
        # A successful pilot is the only gate for the remaining occupied codes.
        # Remaining quota may be zero: these codes are already in live detail.
        candidates=all_pool.drop_duplicates("moomoo_transport_code").copy()
        candidates=candidates.loc[candidates.moomoo_transport_code.isin(after["codes"])]
        candidates=candidates.loc[candidates.moomoo_transport_code.ne(chosen)]
        candidates=candidates.loc[candidates.raw_direct_last_date.fillna("").lt("2026-09-22")]
        if "US.QQQ" in after["codes"]:
            qqq=pd.DataFrame([{"quarter":"BENCHMARK","ticker":"QQQ",
                               "moomoo_transport_code":"US.QQQ",
                               "raw_direct_last_date":"2026-07-14"}])
            candidates=pd.concat([qqq,candidates],ignore_index=True)
        result["qqq_currently_occupied"]="US.QQQ" in after["codes"]
        result["batch_occupied_missing_code_count"]=len(candidates)
        result["batch_receipts"]=[]
        for row in candidates.itertuples(index=False):
            code=str(row.moomoo_transport_code)
            last=str(row.raw_direct_last_date) if pd.notna(row.raw_direct_last_date) else ""
            start=max(last,"2025-06-01") if last else "2025-06-01"
            target=HERE/f"REUSED_{code.replace('.','_')}_RAW_DAY_K.parquet"
            record={"code":code,"ticker":str(row.ticker),"start":start,"end":"2026-09-22"}
            if code=="US.QQQ" and (HERE/"QQQ_RAW_OVERLAP_CONFLICT_OPEN_D.parquet").exists():
                record["status"]="QQQ_PRIOR_OVERLAP_CONFLICT_PRESERVED_NO_REQUEST"
                result["batch_receipts"].append(record)
                continue
            if target.exists():
                record["status"]="EXISTING_CONTINUATION_PRESERVED_NO_REQUEST"
                result["batch_receipts"].append(record)
                continue
            limiter.acquire({"ticker":str(row.ticker),"adjustment":"none","frequency":"1d"})
            ret,frame,page=ctx.request_history_kline(
                code,start=start,end="2026-09-22",ktype=moomoo.KLType.K_DAY,
                autype=moomoo.AuType.NONE,max_count=1000,page_req_key=None,
                extended_time=False,session=moomoo.Session.RTH)
            result["request_count"]+=1
            record["return_code"]=ret
            if ret!=moomoo.RET_OK:
                record.update({"status":"PROVIDER_REJECTED_STOP","error":str(frame)[:450]})
                result["batch_receipts"].append(record)
                result["status"]="PILOT_PASS_BATCH_PROVIDER_REJECTED_STOP"
                break
            if page:
                record.update({"status":"PAGINATED_RESPONSE_STOP","row_count":0 if not isinstance(frame,pd.DataFrame) else len(frame)})
                result["batch_receipts"].append(record)
                result["status"]="PILOT_PASS_BATCH_INCOMPLETE_STOP"
                break
            if not isinstance(frame,pd.DataFrame) or frame.empty:
                record.update({"status":"NO_ROWS_SOURCE_GAP_UNRESOLVED_CONTINUE","row_count":0})
                result["batch_receipts"].append(record)
                continue
            frame["trade_date"]=pd.to_datetime(frame.time_key).dt.normalize()
            for field in ("open","close","high","low","volume"):
                frame[field]=pd.to_numeric(frame[field],errors="raise")
            if frame.trade_date.min()<pd.Timestamp(start) or frame.trade_date.max()>pd.Timestamp("2026-09-22"):
                record["status"]="DATE_SCOPE_ERROR_STOP"
                result["batch_receipts"].append(record)
                result["status"]="PILOT_PASS_BATCH_INPUT_CONFLICT_STOP"
                break
            if (code in index or code=="US.QQQ") and last and last>=start:
                if code=="US.QQQ":
                    existing=pd.read_parquet(QQQ_RAW,columns=["ticker","trade_date","open","close","high","low","volume"])
                    existing=existing.loc[existing.ticker.eq("QQQ")]
                else:
                    existing=original.load_raw_code(code,index[code])
                prior=existing.loc[existing.trade_date.eq(last)]
                overlap=frame.loc[frame.trade_date.eq(last)]
                if len(prior)!=1 or len(overlap)!=1 or any(
                    abs(float(prior[field].iloc[0])-float(overlap[field].iloc[0]))>1e-9
                    for field in ("open","close","high","low","volume")):
                    record["status"]="RAW_OVERLAP_CONFLICT_STOP"
                    if len(prior)==1 and len(overlap)==1:
                        record["prior_overlap"]={field:float(prior[field].iloc[0]) for field in ("open","close","high","low","volume")}
                        record["new_overlap"]={field:float(overlap[field].iloc[0]) for field in ("open","close","high","low","volume")}
                    if code=="US.QQQ":
                        conflict=HERE/"QQQ_RAW_OVERLAP_CONFLICT_OPEN_D.parquet"
                        frame.to_parquet(conflict,index=False)
                        record["status"]="QQQ_RAW_OVERLAP_CONFLICT_QUARANTINED_CONTINUE_STOCKS"
                        record["quarantine_path"]=str(conflict)
                        record["quarantine_sha256"]=hashlib.sha256(conflict.read_bytes()).hexdigest()
                        result["batch_receipts"].append(record)
                        continue
                    result["batch_receipts"].append(record)
                    result["status"]="PILOT_PASS_BATCH_INPUT_CONFLICT_STOP"
                    break
            frame.to_parquet(target,index=False)
            record.update({"status":"SAVED","row_count":len(frame),
                           "first_date":str(frame.trade_date.min().date()),
                           "last_date":str(frame.trade_date.max().date()),
                           "saved_path":str(target),
                           "sha256":hashlib.sha256(target.read_bytes()).hexdigest()})
            result["batch_receipts"].append(record)
        result["batch_success_count"]=sum(x["status"]=="SAVED" for x in result["batch_receipts"])
        result["quota_after_batch"]={k:v for k,v in quota(ctx).items() if k!="codes"}
    finally:
        ctx.close()
        (HERE/"PILOT_REUSED_QUOTA_RECEIPT.json").write_text(json.dumps(result,indent=2,ensure_ascii=False,default=str)+"\n",encoding="utf-8")
        print(json.dumps({k:result.get(k) for k in ("status","code","return_code","row_count","first_date","last_date","quota_before","quota_after","overlap_max_abs_difference","error")},default=str))


def subscription_pilot():
    """Probe two necessary codes through the official recent K_DAY subscription path."""
    gaps=pd.read_csv(HERE/"REUSED_ACTIVE_QUARTER_PRICE_GAPS.csv")
    raw_manifest=pd.read_csv(HERE/"REUSED_RAW_FILES_MANIFEST.csv")
    overlap_code="US.SLMT"
    assert overlap_code in set(raw_manifest.code)
    result={"requested_at_utc":datetime.now(timezone.utc).isoformat(),
            "fixed_test_asof":"2026-09-23T18:40:43Z",
            "accepted_complete_daily_end":"2026-09-22",
            "subscription_type":"K_DAY","autype":"NONE","session":"RTH",
            "request_count":0,"subscribe_calls":0,"unsubscribe_calls":0,"codes":[]}
    ctx=moomoo.OpenQuoteContext(host="127.0.0.1",port=18441)
    owned=[]
    try:
        ret_sub,before=ctx.query_subscription(is_all_conn=True)
        ret_hist,hist=ctx.get_history_kl_quota(get_detail=True)
        if ret_sub!=moomoo.RET_OK or ret_hist!=moomoo.RET_OK:
            result.update({"status":"QUOTA_QUERY_FAILED_NO_SUBSCRIPTION",
                           "subscription_return_code":ret_sub,"history_return_code":ret_hist})
            return
        result["subscription_before"]={k:before.get(k) for k in ("total_used","own_used","remain")}
        result["history_before"]={"used":int(hist[0]),"remaining":int(hist[1]),
                                  "occupied_codes":len(hist[2])}
        occupied={str(x.get("code","")) for x in hist[2]}
        subscribed=set(before.get("sub_list",{}).get("K_DAY",[]))
        q2=gaps.loc[gaps.quarter.eq("2026Q2")&gaps.gap_kind.eq("NO_RAW_SOURCE"),"code"].drop_duplicates()
        candidates=sorted(c for c in q2 if c not in occupied and c not in subscribed
                          and c.startswith("US.") and c[3:].isalpha() and c[3:].isupper())
        if not candidates:
            result["status"]="NO_LEGAL_UNOCCUPIED_Q2_GAP_CODE"
            return
        new_code=candidates[0]
        assert new_code in set(gaps.code) and new_code not in occupied
        result["pilot_codes"]=[overlap_code,new_code]
        result["new_code_gap_quarters"]=sorted(set(gaps.loc[gaps.code.eq(new_code),"quarter"]))
        needed=sum(c not in subscribed for c in result["pilot_codes"])
        if int(before["remain"])<needed:
            result["status"]="SUBSCRIPTION_QUOTA_INSUFFICIENT_NO_REQUEST"
            return
        for code in result["pilot_codes"]:
            record={"code":code,"preexisting_subscription":code in subscribed}
            if code not in subscribed:
                ret,msg=ctx.subscribe([code],[moomoo.SubType.K_DAY],is_first_push=False,
                                      subscribe_push=False,extended_time=False,session=moomoo.Session.RTH)
                result["subscribe_calls"]+=1
                record["subscribe_return_code"]=ret
                if ret!=moomoo.RET_OK:
                    record["status"]="SUBSCRIBE_REJECTED"
                    record["error"]=str(msg)[:300]
                    result["codes"].append(record)
                    continue
                owned.append((code,time.monotonic()))
            else:
                record["subscribe_return_code"]="ALREADY_SUBSCRIBED_BY_OTHER_CONNECTION"
            ret,frame=ctx.get_cur_kline(code,1000,ktype=moomoo.KLType.K_DAY,autype=moomoo.AuType.NONE)
            result["request_count"]+=1
            record["kline_return_code"]=ret
            if ret!=moomoo.RET_OK:
                record["status"]="GET_CUR_KLINE_REJECTED"
                record["error"]=str(frame)[:300]
                result["codes"].append(record)
                continue
            if not isinstance(frame,pd.DataFrame) or frame.empty:
                record.update({"status":"NO_ROWS","total_returned_rows":0})
                result["codes"].append(record)
                continue
            frame=frame.copy()
            frame["trade_date"]=pd.to_datetime(frame.time_key).dt.normalize()
            record["total_returned_rows"]=len(frame)
            record["first_returned_date"]=str(frame.trade_date.min().date())
            record["last_returned_date"]=str(frame.trade_date.max().date())
            record["post_2026_09_22_rows_isolated"]=int(frame.trade_date.gt("2026-09-22").sum())
            allowed=frame.loc[frame.trade_date.le("2026-09-22")].copy()
            record["allowed_rows"]=len(allowed)
            if not allowed.empty:
                record["allowed_first_date"]=str(allowed.trade_date.min().date())
                record["allowed_last_date"]=str(allowed.trade_date.max().date())
            for field in ("open","close","high","low","volume"):
                allowed[field]=pd.to_numeric(allowed[field],errors="raise")
            if code==overlap_code:
                old_path=HERE/raw_manifest.loc[raw_manifest.code.eq(code),"file"].iloc[0]
                old=pd.read_parquet(old_path)
                old["trade_date"]=pd.to_datetime(old.time_key).dt.normalize()
                common=old.merge(allowed,on="trade_date",suffixes=("_old","_new"))
                record["overlap_rows"]=len(common)
                if common.empty:
                    record["status"]="NO_OVERLAP_UNQUALIFIED"
                else:
                    error=max((pd.to_numeric(common[f"{field}_old"])-pd.to_numeric(common[f"{field}_new"])).abs().max()
                              for field in ("open","close","high","low","volume"))
                    record["overlap_max_abs_difference"]=float(error)
                    record["status"]="OVERLAP_EXACT" if error<=1e-9 else "OVERLAP_CONFLICT_NO_INPUT"
            elif not allowed.empty:
                target=HERE/f"SUBSCRIPTION_{code.replace('.','_')}_RAW_DAY_K_INPUT_ONLY.parquet"
                if target.exists():
                    record["status"]="EXISTING_PILOT_PRESERVED"
                else:
                    allowed.to_parquet(target,index=False)
                    record.update({"status":"SAVED_INPUT_ONLY","saved_path":str(target),
                                   "saved_sha256":hashlib.sha256(target.read_bytes()).hexdigest()})
            else:
                record["status"]="NO_PRE_ASOF_COMPLETE_DAY_ROWS"
            result["codes"].append(record)
        ret_sub,after=ctx.query_subscription(is_all_conn=True)
        ret_hist,hist=ctx.get_history_kl_quota(get_detail=True)
        result["subscription_after_fetch"]={k:after.get(k) for k in ("total_used","own_used","remain")} if ret_sub==moomoo.RET_OK else {"return_code":ret_sub}
        result["history_after_fetch"]={"used":int(hist[0]),"remaining":int(hist[1])} if ret_hist==moomoo.RET_OK else {"return_code":ret_hist}
        result["status"]="PILOT_RECORDED"
    finally:
        for code,started in owned:
            delay=60.0-(time.monotonic()-started)
            if delay>0:time.sleep(delay)
            ret,msg=ctx.unsubscribe([code],[moomoo.SubType.K_DAY],unsubscribe_all=False)
            result["unsubscribe_calls"]+=1
            result.setdefault("own_unsubscriptions",[]).append({"code":code,"return_code":ret,
                                                                  "error":None if ret==moomoo.RET_OK else str(msg)[:250]})
        ctx.close()
        (HERE/"SUBSCRIPTION_PILOT_RECEIPT.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+"\n",encoding="utf-8")
        print(json.dumps({"status":result.get("status"),"subscription_before":result.get("subscription_before"),
                          "history_before":result.get("history_before"),"request_count":result["request_count"],
                          "codes":[{k:x.get(k) for k in ("code","status","kline_return_code","total_returned_rows",
                                                         "allowed_rows","first_returned_date","last_returned_date",
                                                         "overlap_rows","overlap_max_abs_difference")}
                                   for x in result["codes"]]},ensure_ascii=False,default=str))


def subscription_batch(targeted=False, authority_aliases=False, ge_alias=False, official_common_aliases=False):
    """Resume only active-window gaps in batches of at most 20 own subscriptions."""
    pilot=json.loads((HERE/"SUBSCRIPTION_PILOT_RECEIPT.json").read_text(encoding="utf-8"))
    assert {x["status"] for x in pilot["codes"]}=={"OVERLAP_EXACT","SAVED_INPUT_ONLY"}
    gaps=pd.read_csv(HERE/"REUSED_ACTIVE_QUARTER_PRICE_GAPS.csv")
    inv=pd.read_csv(HERE/"QUARTER_POOL_PRICE_INVENTORY.csv")
    inventory={str(r.moomoo_transport_code):r for r in inv.drop_duplicates("moomoo_transport_code").itertuples(index=False)}
    reused_manifest=pd.read_csv(HERE/"REUSED_RAW_FILES_MANIFEST.csv")
    already=set(reused_manifest.code)
    reused_paths=dict(zip(reused_manifest.code,reused_manifest.file))
    groups=gaps.groupby("code",sort=False)
    priority=[];special=[]
    for code,rows in groups:
        if code in already or code=="US.AAL":
            continue
        suffix=code.removeprefix("US.")
        if not code.startswith("US.") or not suffix.isalpha() or not suffix.isupper():
            special.append(code)
            continue
        no_raw=rows.gap_kind.eq("NO_RAW_SOURCE").any()
        q2=rows.quarter.eq("2026Q2").any()
        priority.append((0 if no_raw and q2 else 1 if no_raw else 2 if q2 else 3,code))
    if official_common_aliases:
        source=pd.concat([
            pd.read_parquet(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\universe\quarterly_universe_members.parquet")
              .loc[lambda d:d.quarter.isin(["2025Q3","2025Q4","2026Q1"])],
            pd.read_parquet(HERE/"Q2_ORIGINAL24_INITIAL_CANDIDATES.parquet")],ignore_index=True)
        assert set(source.loc[source.ticker.eq("DTP"),"cusip"].astype(str))=={"233331107"}
        assert set(source.loc[source.ticker.eq("LILAB"),"cusip"].astype(str))=={"G9001E102"}
        assert set(source.loc[source.ticker.eq("DTP"),"title_of_class"].astype(str))=={"COM"}
        assert set(source.loc[source.ticker.eq("LILAB"),"title_of_class"].astype(str))=={"COM CL A"}
        targets=["US.DTE","US.LILA"]
    elif authority_aliases:
        # Exact current symbols for the seven hash-verified R31 authority cases.
        expected={
            "BGNE":("07725L102","ONC"),"BLDE":("092667104","SRTA"),
            "BSIG":("10948W103","AAMI"),"AZNCF":("G0593M107","AZN"),
            "LLYVB":("530909308","LLYVK"),"MSTLW":("617446448","MS"),
            "CBDY":("87612E106","TGT"),
        }
        authority=pd.read_csv(
            r"D:\us-tech-quant-results\massive_r3_remaining31_external_authority_r2\20260903T131804Z\tables\external_identity_authority.csv",
            dtype={"input_security_key":str},
        )
        for ticker,(cusip,current) in expected.items():
            row=authority.loc[authority.input_ticker.eq(ticker)]
            assert len(row)==1 and row.iloc[0].input_security_key==cusip
            assert row.iloc[0].provider_symbol==current
            assert bool(row.iloc[0].minimum_standard_pass)
        targets=sorted("US."+current for _,current in expected.values())
    elif ge_alias:
        # 2026Q2 original CUSIP 369604301 is GE Aerospace common;
        # issuer's 2024 spin-off notice says GE WI ended 2024-04-01,
        # while the same common shares continue regular-way as GE.
        pool_ge=inv.loc[inv.moomoo_transport_code.eq("US.GE.WI")]
        assert set(pool_ge.loc[pool_ge.quarter.eq("2026Q2"),"ticker"])=={"GE.WI"}
        q2_ge=pd.read_parquet(HERE/"Q2_ORIGINAL24_INITIAL_CANDIDATES.parquet")
        assert set(q2_ge.loc[q2_ge.ticker.eq("GE.WI"),"cusip"])=={"369604301"}
        targets=["US.GE"]
    else:
        targets=sorted(set(special)|{"US.TALK","US.WBS"}) if targeted else [code for _,code in sorted(priority)]
    receipt_path=HERE/("SUBSCRIPTION_OFFICIAL_COMMON_ALIASES_RECEIPT.json" if official_common_aliases else
                       "SUBSCRIPTION_GE_AUTHORITY_RECEIPT.json" if ge_alias else
                       "SUBSCRIPTION_AUTHORITY31_ALIAS_RECEIPT.json" if authority_aliases else
                       "SUBSCRIPTION_TARGETED_RECEIPT.json" if targeted else "SUBSCRIPTION_BATCH_RECEIPT.json")
    if receipt_path.exists():
        result=json.loads(receipt_path.read_text(encoding="utf-8"))
        completed={x["code"] for x in result["records"] if x["status"] in
                   {"SAVED_INPUT_ONLY","OVERLAP_CONFLICT_QUARANTINED","NO_ROWS_SOURCE_GAP",
                    "NO_OVERLAP_QUARANTINED","SUBSCRIBE_REJECTED_CODE","NO_ALLOWED_ROWS"}}
        targets=[code for code in targets if code not in completed]
        result["resume_count"]=result.get("resume_count",0)+1
    else:
        result={"started_at_utc":datetime.now(timezone.utc).isoformat(),
                "fixed_test_asof":"2026-09-23T18:40:43Z","complete_daily_end":"2026-09-22",
                "subscription_batch_max":20,"ktype":"K_DAY","autype":"NONE","session":"RTH",
                "special_alias_or_digit_codes_deferred":sorted(special) if not targeted else [],
                "targeted_exact_transport_and_tail_checks":bool(targeted),
                "authority_aliases_from_verified_R31":bool(authority_aliases),
                "ge_alias_from_official_issuer_and_sec":bool(ge_alias),
                "official_dte_lila_cusip_class_aliases":bool(official_common_aliases),
                "already_complete_250_codes_skipped":len(already),
                "pilot_US_AAL_skipped":True,"target_count":len(targets),
                "subscribe_calls":0,"kline_calls":0,"unsubscribe_calls":0,"records":[],"batches":[]}
    def persist():
        tmp=receipt_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+"\n",encoding="utf-8")
        tmp.replace(receipt_path)
    limiter_module=import_file("original_subscription_batch_limiter",LIMITER)
    # Count both subscriptions and K-line reads in one conservative budget.
    limiter=limiter_module.HistoryKlineLimiter(max_calls=40,window_seconds=30.0,min_interval=0.75)
    ctx=moomoo.OpenQuoteContext(host="127.0.0.1",port=18441)
    owned=[]
    def release_aged(force=False):
        remaining=[]
        for item in owned:
            delay=60.0-(time.monotonic()-item["started"])
            if force and delay>0:time.sleep(delay)
            if force or delay<=0:
                ret,msg=ctx.unsubscribe(item["codes"],[moomoo.SubType.K_DAY],unsubscribe_all=False)
                result["unsubscribe_calls"]+=1
                result.setdefault("own_unsubscriptions",[]).append({"codes":item["codes"],"return_code":ret,
                                                                      "error":None if ret==moomoo.RET_OK else str(msg)[:220]})
            else:remaining.append(item)
        owned[:]=remaining
        persist()
    try:
        ret_hist,hist=ctx.get_history_kl_quota(get_detail=True)
        result["history_before"]={"return_code":ret_hist,"used":int(hist[0]),"remaining":int(hist[1])} if ret_hist==moomoo.RET_OK else {"return_code":ret_hist}
        for offset in range(0,len(targets),20):
            release_aged()
            batch=targets[offset:offset+20]
            ret_sub,sub=ctx.query_subscription(is_all_conn=True)
            if ret_sub!=moomoo.RET_OK:
                result["status"]="SUBSCRIPTION_QUERY_FAILED_STOP"
                result["error"]=str(sub)[:220]
                break
            remaining=int(sub["remain"])
            if remaining<len(batch):
                release_aged(force=True)
                ret_sub,sub=ctx.query_subscription(is_all_conn=True)
                if ret_sub!=moomoo.RET_OK or int(sub["remain"])<len(batch):
                    result["status"]="LIVE_SUBSCRIPTION_QUOTA_INSUFFICIENT_STOP"
                    break
            limiter.acquire({"ticker":"BATCH","adjustment":"none","frequency":"1d"})
            ret,msg=ctx.subscribe(batch,[moomoo.SubType.K_DAY],is_first_push=False,
                                  subscribe_push=False,extended_time=False,session=moomoo.Session.RTH)
            started=time.monotonic()
            result["subscribe_calls"]+=1
            entry={"index":len(result["batches"])+1,"codes":batch,"subscribe_return_code":ret,
                   "quota_remaining_before":int(sub["remain"])}
            result["batches"].append(entry)
            if ret!=moomoo.RET_OK:
                entry["error"]=str(msg)[:250]
                entry["split_to_single_codes"]=True
                active=[]
                for code in batch:
                    limiter.acquire({"ticker":code,"adjustment":"none","frequency":"1d"})
                    ret_one,msg_one=ctx.subscribe([code],[moomoo.SubType.K_DAY],is_first_push=False,
                                                  subscribe_push=False,extended_time=False,session=moomoo.Session.RTH)
                    result["subscribe_calls"]+=1
                    if ret_one==moomoo.RET_OK:
                        owned.append({"codes":[code],"started":time.monotonic()})
                        active.append(code)
                    else:
                        result["records"].append({"code":code,"batch_index":entry["index"],
                                                  "status":"SUBSCRIBE_REJECTED_CODE","return_code":ret_one,
                                                  "error":str(msg_one)[:250]})
                        persist()
            else:
                owned.append({"codes":batch,"started":started})
                active=batch
            for code in active:
                record={"code":code,"batch_index":entry["index"],"status":"REQUEST_STARTED"}
                limiter.acquire({"ticker":code,"adjustment":"none","frequency":"1d"})
                ret,frame=ctx.get_cur_kline(code,1000,ktype=moomoo.KLType.K_DAY,autype=moomoo.AuType.NONE)
                result["kline_calls"]+=1
                record["return_code"]=ret
                if ret!=moomoo.RET_OK:
                    record.update({"status":"KLINE_REJECTED","error":str(frame)[:250]})
                    result["records"].append(record);persist()
                    continue
                if not isinstance(frame,pd.DataFrame) or frame.empty:
                    record.update({"status":"NO_ROWS_SOURCE_GAP","returned_rows":0})
                    result["records"].append(record);persist()
                    continue
                frame=frame.copy()
                frame["trade_date"]=pd.to_datetime(frame.time_key).dt.normalize()
                record.update({"returned_rows":len(frame),
                               "first_returned_date":str(frame.trade_date.min().date()),
                               "last_returned_date":str(frame.trade_date.max().date()),
                               "post_cutoff_rows_isolated":int(frame.trade_date.gt("2026-09-22").sum())})
                allowed=frame.loc[frame.trade_date.le("2026-09-22")].copy()
                record["allowed_rows"]=len(allowed)
                if allowed.empty:
                    record["status"]="NO_ALLOWED_ROWS"
                    result["records"].append(record);persist()
                    continue
                record["allowed_first_date"]=str(allowed.trade_date.min().date())
                record["allowed_last_date"]=str(allowed.trade_date.max().date())
                for field in ("open","close","high","low","volume"):
                    allowed[field]=pd.to_numeric(allowed[field],errors="raise")
                if allowed.trade_date.duplicated().any() or set(allowed.code.astype(str))!={code}:
                    record["status"]="RESPONSE_IDENTITY_OR_DATE_DUPLICATE_CONFLICT"
                    result["records"].append(record);persist()
                    continue
                raw_path=inventory[code].raw_paths if code in inventory else None
                if (pd.isna(raw_path) or not raw_path) and code in reused_paths:
                    raw_path=str(HERE/reused_paths[code])
                overlap_status="NO_OLD_RAW_TO_COMPARE"
                if pd.notna(raw_path) and raw_path:
                    old=pd.read_parquet(Path(raw_path))
                    old=old.loc[old.code.astype(str).eq(code)].copy()
                    old["trade_date"]=pd.to_datetime(old.time_key).dt.normalize()
                    common=old.merge(allowed,on="trade_date",suffixes=("_old","_new"))
                    record["overlap_rows"]=len(common)
                    if common.empty:
                        overlap_status="NO_OVERLAP_QUARANTINED"
                    else:
                        error=max((pd.to_numeric(common[f"{field}_old"])-pd.to_numeric(common[f"{field}_new"])).abs().max()
                                  for field in ("open","close","high","low","volume"))
                        record["overlap_max_abs_difference"]=float(error)
                        overlap_status="OVERLAP_EXACT" if error<=1e-9 else "OVERLAP_CONFLICT_QUARANTINED"
                if overlap_status in ("NO_OVERLAP_QUARANTINED","OVERLAP_CONFLICT_QUARANTINED"):
                    target=HERE/f"SUBSCRIPTION_CONFLICT_{code.replace('.','_')}_RAW_DAY_K.parquet"
                    record["status"]=overlap_status
                else:
                    target=HERE/f"SUBSCRIPTION_{code.replace('.','_')}_RAW_DAY_K_INPUT_ONLY.parquet"
                    record["status"]="SAVED_INPUT_ONLY"
                if not target.exists():allowed.to_parquet(target,index=False)
                record["saved_file"]=target.name
                record["sha256"]=hashlib.sha256(target.read_bytes()).hexdigest()
                result["records"].append(record);persist()
            entry["completed_at_utc"]=datetime.now(timezone.utc).isoformat()
            persist()
        else:result["status"]="ALL_NORMAL_TARGETS_ATTEMPTED"
        ret_hist,hist=ctx.get_history_kl_quota(get_detail=True)
        result["history_after"]={"return_code":ret_hist,"used":int(hist[0]),"remaining":int(hist[1])} if ret_hist==moomoo.RET_OK else {"return_code":ret_hist}
        result["completed_at_utc"]=datetime.now(timezone.utc).isoformat()
    finally:
        release_aged(force=True)
        ctx.close()
        persist()
        print(json.dumps({"status":result.get("status"),"target_count":result.get("target_count"),
                          "subscribe_calls":result["subscribe_calls"],"kline_calls":result["kline_calls"],
                          "saved":sum(x["status"]=="SAVED_INPUT_ONLY" for x in result["records"]),
                          "conflicts":sum("CONFLICT" in x["status"] for x in result["records"]),
                          "no_rows":sum(x["status"]=="NO_ROWS_SOURCE_GAP" for x in result["records"])},ensure_ascii=False))


if __name__=="__main__":
    if "--subscription-pilot" in sys.argv:
        subscription_pilot()
    elif "--subscription-batch" in sys.argv:
        subscription_batch()
    elif "--subscription-targeted" in sys.argv:
        subscription_batch(targeted=True)
    elif "--subscription-authority-aliases" in sys.argv:
        subscription_batch(authority_aliases=True)
    elif "--subscription-ge-alias" in sys.argv:
        subscription_batch(ge_alias=True)
    elif "--subscription-official-common-aliases" in sys.argv:
        subscription_batch(official_common_aliases=True)
    else:
        main()
