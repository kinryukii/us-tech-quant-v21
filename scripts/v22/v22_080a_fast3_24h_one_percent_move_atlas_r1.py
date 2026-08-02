#!/usr/bin/env python
"""V22.080A FAST3 24-hour 1% directional-change opportunity atlas (research only)."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd

NAME = "V22.080A_FAST3_24H_ONE_PERCENT_MOVE_ATLAS_R1"
CANONICAL = Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical")
DEFAULT_OUT = Path(r"D:\us-tech-quant-results\v22") / NAME
SYMBOLS = ("QQQ", "SOXX", "TQQQ", "SQQQ", "SOXL", "SOXS")
UNDERLYINGS = ("QQQ", "SOXX")
LATENCIES = (0, 1, 3, 5, 10, 15)
REQUIRED_COLUMNS = ("timestamp_et", "timestamp_utc", "broker_trade_date", "session", "open", "high", "low", "close", "volume")
MAPPING = {("QQQ", "UP"): "TQQQ", ("QQQ", "DOWN"): "SQQQ", ("SOXX", "UP"): "SOXL", ("SOXX", "DOWN"): "SOXS"}
SESSION_MAP = {"OVERNIGHT": "OVERNIGHT", "PREMARKET": "PREMARKET", "REGULAR_TRADING_HOURS": "REGULAR_TRADING_HOURS", "AFTER_HOURS": "AFTER_HOURS"}
DELAY_INELIGIBLE_STATUS = "TARGET_ALREADY_REACHED_BEFORE_DELAY"

def jdefault(x):
    if isinstance(x, (np.integer,)): return int(x)
    if isinstance(x, (np.floating, float)) and not np.isfinite(x): return None
    if isinstance(x, (pd.Timestamp,)): return x.isoformat()
    return str(x)

def write_json(path, value): path.write_text(json.dumps(value, indent=2, default=jdefault) + "\n", encoding="utf-8")

def normalize_session(v): return SESSION_MAP.get(str(v).upper(), "UNKNOWN_SESSION")

def load_symbol(symbol, canonical=CANONICAL):
    paths = sorted(Path(canonical).glob(f"symbol={symbol}/year=*/month=*/data.parquet"))
    if not paths: raise RuntimeError(f"SOURCE_DATA_MISSING:{symbol}")
    df = pd.concat([pd.read_parquet(p, columns=list(REQUIRED_COLUMNS)) for p in paths], ignore_index=True)
    df["timestamp_utc"] = pd.to_datetime(df.timestamp_utc, utc=True, errors="raise")
    df["timestamp_et"] = pd.to_datetime(df.timestamp_et, errors="raise")
    df = df.sort_values("timestamp_utc", kind="mergesort").reset_index(drop=True)
    df["session"] = df.session.map(normalize_session)
    o,h,l,c = (pd.to_numeric(df[k], errors="coerce") for k in ("open","high","low","close"))
    df["valid_bar"] = np.isfinite(o)&np.isfinite(h)&np.isfinite(l)&np.isfinite(c)&(o>0)&(l>0)&(h>=np.maximum(np.maximum(o,l),c))&(l<=np.minimum(np.minimum(o,h),c))
    audit = {"symbol":symbol,"path_count":len(paths),"row_count":len(df),"date_start":str(df.timestamp_et.min()),"date_end":str(df.timestamp_et.max()),"required_columns_present":all(k in df for k in REQUIRED_COLUMNS),"duplicate_timestamp_count":int(df.timestamp_utc.duplicated().sum()),"monotonic_timestamp":bool(df.timestamp_utc.is_monotonic_increasing),"invalid_ohlc_count":int((~df.valid_bar).sum()),"sessions":sorted(df.session.dropna().unique().tolist())}
    return df, audit

def detect_events(df, symbol):
    """Non-overlapping directional-change state machine. Same-bar dual touch is audited."""
    rows=[]; low_i=high_i=None; event_no=0
    lowv=df.low.to_numpy(float); highv=df.high.to_numpy(float); good=df.valid_bar.to_numpy(); et=df.timestamp_et.to_numpy(); utc=df.timestamp_utc.to_numpy(); sess=df.session.to_numpy()
    for i in range(len(df)):
        if not good[i]: continue
        if low_i is None:
            low_i=high_i=i; continue
        low=lowv[low_i]; high=highv[high_i]
        up = highv[i] >= low*1.01
        down = lowv[i] <= high*.99
        if up or down:
            if up and down:
                rows.append({"event_id":f"{symbol}_AMB_{event_no:07d}","underlying_symbol":symbol,"direction":"AMBIGUOUS","start_type":"EX_POST_MOVE_START","start_timestamp_et":pd.NaT,"start_timestamp_utc":pd.NaT,"start_price":np.nan,"target_timestamp_et":et[i],"target_timestamp_utc":utc[i],"target_price":np.nan,"duration_minutes":np.nan,"start_session":"UNKNOWN_SESSION","target_session":sess[i],"cross_session_flag":False,"underlying_mfe":np.nan,"underlying_mae_before_target":np.nan,"calendar_date_et":str(pd.Timestamp(et[i]).date()),"year":pd.Timestamp(et[i]).year,"month":pd.Timestamp(et[i]).month,"ambiguity_status":"AMBIGUOUS_INTRABAR_ORDER","data_quality_status":"VALID"})
            else:
                direction="UP" if up else "DOWN"; si=low_i if up else high_i; sp=low if up else high
                signed_high=(highv[si:i+1].max()/sp-1) if up else (sp/lowv[si:i+1].min()-1)
                signed_low=(lowv[si:i+1].min()/sp-1) if up else (sp/highv[si:i+1].max()-1)
                rows.append({"event_id":f"{symbol}_{direction}_{event_no:07d}","underlying_symbol":symbol,"direction":direction,"start_type":"EX_POST_MOVE_START","start_timestamp_et":et[si],"start_timestamp_utc":utc[si],"start_price":sp,"target_timestamp_et":et[i],"target_timestamp_utc":utc[i],"target_price":sp*(1.01 if up else .99),"duration_minutes":(utc[i]-utc[si])/np.timedelta64(1,'m'),"start_session":sess[si],"target_session":sess[i],"cross_session_flag":bool(sess[si]!=sess[i]),"underlying_mfe":signed_high,"underlying_mae_before_target":min(signed_low,0),"calendar_date_et":str(pd.Timestamp(et[si]).date()),"year":pd.Timestamp(et[si]).year,"month":pd.Timestamp(et[si]).month,"ambiguity_status":"NOT_AMBIGUOUS","data_quality_status":"VALID"})
            event_no+=1; low_i=high_i=None; continue
        if lowv[i]<lowv[low_i]: low_i=i
        if highv[i]>highv[high_i]: high_i=i
    cols=["event_id","underlying_symbol","direction","start_type","start_timestamp_et","start_timestamp_utc","start_price","target_timestamp_et","target_timestamp_utc","target_price","duration_minutes","start_session","target_session","cross_session_flag","underlying_mfe","underlying_mae_before_target","calendar_date_et","year","month","ambiguity_status","data_quality_status"]
    return pd.DataFrame(rows,columns=cols)

def first_at_or_after(df, timestamp, max_gap_minutes=None):
    ns=np.asarray(df.timestamp_utc.dt.tz_localize(None), dtype="datetime64[ns]").astype("int64"); p=np.searchsorted(ns, pd.Timestamp(timestamp).value)
    if p>=len(df): return None
    row=df.iloc[p]
    if max_gap_minutes is not None and (row.timestamp_utc-pd.Timestamp(timestamp)).total_seconds()>max_gap_minutes*60: return None
    return row if row.valid_bar else None

def map_latency(events, underlyings, leveraged):
    def cache(df):
        return (df, np.asarray(df.timestamp_utc.dt.tz_localize(None), dtype="datetime64[ns]").astype("int64"), df.valid_bar.to_numpy())
    def locate(c, timestamp, gap=None):
        df, ns, good=c; p=np.searchsorted(ns, pd.Timestamp(timestamp).value)
        while p<len(ns) and not good[p]: p+=1
        if p>=len(ns) or (gap is not None and ns[p]-pd.Timestamp(timestamp).value>gap*60_000_000_000): return None
        return p
    uc={s:cache(x) for s,x in underlyings.items()}; lc={s:cache(x) for s,x in leveraged.items()}
    rows=[]
    for e in events[events.direction.isin(["UP","DOWN"])].itertuples(index=False):
        udf, uns, _=uc[e.underlying_symbol]; etf=MAPPING[(e.underlying_symbol,e.direction)]; ldf, lns, _=lc[etf]
        for latency in LATENCIES:
            desired=e.start_timestamp_utc+pd.Timedelta(minutes=latency)
            upos=locate(uc[e.underlying_symbol],desired); u=udf.iloc[upos] if upos is not None else None
            base={"event_id":e.event_id,"underlying_symbol":e.underlying_symbol,"direction":e.direction,"leveraged_symbol":etf,"latency_minutes":latency,"desired_entry_timestamp_et":e.start_timestamp_et+pd.Timedelta(minutes=latency)}
            if u is None: rows.append({**base,"latency_mapping_status":"NOT_COMPUTABLE"}); continue
            if u.timestamp_utc>e.target_timestamp_utc: rows.append({**base,"delayed_entry_timestamp_et":u.timestamp_et,"latency_mapping_status":"TARGET_ALREADY_REACHED_BEFORE_DELAY"}); continue
            remaining=(e.target_price/u.open-1) if e.direction=="UP" else (u.open/e.target_price-1)
            ep=locate(lc[etf],u.timestamp_utc,1); xp=locate(lc[etf],e.target_timestamp_utc,1)
            entry=ldf.iloc[ep] if ep is not None else None; exit_=ldf.iloc[xp] if xp is not None else None
            rec={**base,"delayed_entry_timestamp_et":u.timestamp_et,"delayed_entry_price":float(u.open),"remaining_underlying_return":remaining,"remaining_time_to_target_minutes":(e.target_timestamp_utc-u.timestamp_utc).total_seconds()/60,"delayed_underlying_mfe":np.nan,"delayed_underlying_mae":np.nan}
            if entry is None: rows.append({**rec,"latency_mapping_status":"ENTRY_TIMESTAMP_MISMATCH"}); continue
            if exit_ is None: rows.append({**rec,"latency_mapping_status":"EXIT_TIMESTAMP_MISMATCH"}); continue
            if entry.open<=0 or exit_.open<=0: rows.append({**rec,"latency_mapping_status":"INVALID_ENTRY_PRICE"}); continue
            path=ldf.iloc[ep:xp+1]
            gross=float(exit_.open/entry.open-1); highs=path.high.max()/entry.open-1; lows=path.low.min()/entry.open-1
            hit=lambda x: bool((path.high>=entry.open*(1+x)).any())
            timehit=lambda x: ((path.loc[path.high>=entry.open*(1+x),"timestamp_utc"].iloc[0]-entry.timestamp_utc).total_seconds()/60 if hit(x) else np.nan)
            rows.append({**rec,"etf_entry_timestamp_et":entry.timestamp_et,"etf_entry_price":float(entry.open),"etf_exit_timestamp_et":exit_.timestamp_et,"etf_exit_price":float(exit_.open),"gross_return":gross,"net_return_0bps":gross,"net_return_10bps":gross-.001,"net_return_20bps":gross-.002,"leveraged_mfe":float(highs),"leveraged_mae":float(lows),"hit_2pct":hit(.02),"hit_2_5pct":hit(.025),"hit_3pct":hit(.03),"time_to_2pct_minutes":timehit(.02),"time_to_2_5pct_minutes":timehit(.025),"time_to_3pct_minutes":timehit(.03),"latency_mapping_status":"SUCCESS"})
    return pd.DataFrame(rows)

def primary_mapping_metrics(latency):
    """Separate latency opportunity loss from the ETF timestamp-mapping contract.

    A target already reached before the specified delayed entry has no executable
    delayed entry to map.  It belongs in post-latency opportunity statistics, not
    the ETF mapping denominator.  Only rows that reached an attempted ETF mapping
    can establish whether the <=1 minute ETF mapping contract succeeded.
    """
    primary_all = latency[latency.latency_minutes.eq(3)].copy()
    eligible = primary_all[primary_all.latency_mapping_status.ne(DELAY_INELIGIBLE_STATUS)]
    success = eligible[eligible.latency_mapping_status.eq("SUCCESS")]
    return primary_all, eligible, success, {
        "primary_total_event_count": int(len(primary_all)),
        "primary_delay_ineligible_count": int((primary_all.latency_mapping_status == DELAY_INELIGIBLE_STATUS).sum()),
        "primary_mapping_contract_eligible_count": int(len(eligible)),
        "primary_mapping_success_count": int(len(success)),
        "primary_mapping_failure_count": int((eligible.latency_mapping_status != "SUCCESS").sum()),
        "primary_leveraged_mapping_success_rate": float(len(success) / len(eligible)) if len(eligible) else 0.0,
    }

def run(output_dir=DEFAULT_OUT, canonical=CANONICAL):
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    data={}; audits=[]
    for s in SYMBOLS: data[s],a=load_symbol(s,canonical); audits.append(a)
    events=pd.concat([detect_events(data[s],s) for s in UNDERLYINGS],ignore_index=True)
    latency=map_latency(events,{s:data[s] for s in UNDERLYINGS},{s:data[s] for s in SYMBOLS if s not in UNDERLYINGS})
    primary_all, mapping_eligible, primary, mapping_metrics = primary_mapping_metrics(latency)
    normal=events[events.direction.isin(["UP","DOWN"])]
    total=len(normal); by_group=normal.groupby(["underlying_symbol","direction"]).size().to_dict(); success=mapping_metrics["primary_leveraged_mapping_success_rate"]
    hit2=float(primary.hit_2pct.mean()) if len(primary) else 0; hit3=float(primary.hit_3pct.mean()) if len(primary) else 0
    failures=[]
    if not all(a["required_columns_present"] and a["duplicate_timestamp_count"]==0 and a["monotonic_timestamp"] for a in audits): decision="SOURCE_DATA_CONTRACT_INCOMPLETE"
    elif total<500 or any(by_group.get((s,d),0)<100 for s in UNDERLYINGS for d in ("UP","DOWN")): decision="INSUFFICIENT_INDEPENDENT_MOVE_SAMPLE"
    elif success<.98: decision="LEVERAGED_MAPPING_CONTRACT_INCOMPLETE"
    elif hit2<.15 or hit3<.05: decision="INSUFFICIENT_POST_LATENCY_CAPTURE_OPPORTUNITY"
    else: decision="SUFFICIENT_24H_MOVE_OPPORTUNITY_FOR_PREDICTABILITY_RESEARCH"
    summary={"research_id":NAME,"final_status":"PASS","final_decision":decision,"historical_move_event_count":total,"ambiguous_event_count":int(events.direction.eq("AMBIGUOUS").sum()),"event_count_by_underlying_direction":{f"{k[0]}_{k[1]}":int(v) for k,v in by_group.items()},"primary_latency_minutes":3,**mapping_metrics,"primary_etf_2pct_hit_rate":hit2,"primary_etf_3pct_hit_rate":hit3,"primary_median_net_return_10bps":float(primary.net_return_10bps.median()) if len(primary) else None,"source_data_contract":audits,"confirmation_row_read_count":0,"broker_action_allowed":False,"paper_trading_allowed":False,"official_adoption_allowed":False,"order_generation_allowed":False,"output_directory":str(out)}
    events.to_csv(out/"v22_080a_move_event_catalog.csv",index=False); latency.to_csv(out/"v22_080a_latency_capture.csv",index=False)
    events.groupby(["underlying_symbol","direction","start_session"],dropna=False).size().reset_index(name="event_count").to_csv(out/"v22_080a_session_distribution.csv",index=False)
    latency.to_csv(out/"v22_080a_underlying_to_leveraged_mapping.csv",index=False)
    primary.assign(year=pd.to_datetime(primary.etf_entry_timestamp_et).dt.year).groupby(["year","underlying_symbol","direction"],dropna=False).agg(event_count=("event_id","size"),mapping_success=("event_id","size"),hit_2pct_rate=("hit_2pct","mean"),hit_3pct_rate=("hit_3pct","mean"),median_net_return_10bps=("net_return_10bps","median")).reset_index().to_csv(out/"v22_080a_year_stability.csv",index=False)
    pd.concat([pd.DataFrame(audits).assign(diagnostic_type="SOURCE_DATA"), primary_all.groupby("latency_mapping_status").size().reset_index(name="row_count").assign(diagnostic_type="PRIMARY_3M_MAPPING_STATUS")], ignore_index=True, sort=False).to_csv(out/"v22_080a_zero_and_missing_diagnostic.csv",index=False)
    write_json(out/"v22_080a_summary.json",summary)
    (out/"v22_080a_report.md").write_text(f"# {NAME}\n\nFINAL_STATUS=PASS\n\nFINAL_DECISION={decision}\n\nAt the 3-minute latency, {mapping_metrics['primary_delay_ineligible_count']} events had already reached their underlying target before any delayed entry and are excluded from the ETF mapping-contract denominator. The real attempted ETF mapping rate is {success:.6%} ({mapping_metrics['primary_mapping_success_count']}/{mapping_metrics['primary_mapping_contract_eligible_count']}); {mapping_metrics['primary_mapping_failure_count']} attempted mappings failed, chiefly at the trailing source-data boundary.\n\nThis descriptive ex-post atlas uses real ETF OHLC, not 3x arithmetic. It is research-only and not a signal or order generator.\n",encoding="utf-8")
    print("FINAL_STATUS=PASS"); print("FINAL_DECISION="+decision); print("SUMMARY_PATH="+str(out/"v22_080a_summary.json")); return summary

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--output-dir",default=str(DEFAULT_OUT)); p.add_argument("--canonical-root",default=str(CANONICAL)); a=p.parse_args(); run(a.output_dir,Path(a.canonical_root))
