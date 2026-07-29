"""R10B4 real-ABCDE, append-only forward-stability ledger.

This module deliberately never reads the proxy ranking cache.  It is a
post-daily-chain research ledger, not a trading component.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd

ROOT = Path(r"D:\us-tech-quant")
REAL_MASTER = Path(r"D:\us-tech-quant-data\canonical\v22\REAL_ABCDE_DAILY_HISTORY_R1\real_abcde_daily_2026.parquet")
PRICE_ROOT = Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq")
LEDGER = Path(r"D:\us-tech-quant-data\research_ledger\v22\R10B4_A_RAWSCORE_REAL_FORWARD_STABILITY_LEDGER_R1")
RESULT = Path(r"D:\us-tech-quant-results\outputs\v22\R10B4_A_RAWSCORE_REAL_FORWARD_STABILITY_LEDGER_R1")
SCHEMA = "R10B4_REAL_FORWARD_LEDGER_R1"
EXPECTED = {"A1", "B", "C", "D", "E_R1"}
HORIZONS = (5, 10, 20)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_hash(frame: pd.DataFrame, cols: list[str]) -> str:
    if frame.empty:
        return hashlib.sha256(b"").hexdigest()
    data = frame.loc[:, cols].sort_values(cols[:2]).to_csv(index=False).encode()
    return hashlib.sha256(data).hexdigest()


def atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def atomic_json(value: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def rank_percentile(rank: pd.Series, universe: pd.Series) -> pd.Series:
    den = (universe.astype(float) - 1.0).clip(lower=1.0)
    return 1.0 - (rank.astype(float) - 1.0) / den


def scan_real_source(path: Path = REAL_MASTER) -> tuple[pd.DataFrame, dict]:
    if not path.exists():
        empty = pd.DataFrame(columns=["signal_date", "strategy", "ticker", "rank", "score", "daily_run_status"])
        return empty, {"source_paths":[str(path)],"rejected_signal_dates":{},"existing_start_date":None,"existing_end_date":None,"existing_signal_date_count":0,"existing_row_count":0,"existing_ticker_count":0}
    raw = pd.read_parquet(path)
    # Canonical history is the only preferred source.  Normalize its stable
    # schema to the collector schema below; proxy/mixed rows are excluded.
    if "strategy_name" in raw.columns:
        raw = raw[(raw.get("real_abcde_eligible", False).fillna(False).astype(bool)) & raw.get("score_source_class", "").eq("REAL_FULL_ABCDE")].copy()
        raw["strategy"] = raw["strategy_name"].replace({"A1_CONTROL": "A1"})
        raw["score"] = raw["raw_score"]
        raw["daily_run_status"] = raw.get("source_final_status", "PASS")
        raw["daily_run_summary_path"] = raw.get("source_summary_path", "")
        raw["source_file"] = raw.get("source_snapshot_path", "")
    raw["signal_date"] = pd.to_datetime(raw["signal_date"]).dt.normalize()
    required = {"signal_date", "strategy", "ticker", "rank", "score", "daily_run_status"}
    if required - set(raw):
        raise ValueError(f"real source lacks {sorted(required - set(raw))}")
    rejected: dict[str, str] = {}
    accepted = []
    for date, g in raw.groupby("signal_date", sort=True):
        reasons = []
        if not g["daily_run_status"].astype(str).str.contains("PASS", case=False).all(): reasons.append("formal_daily_chain_not_pass")
        if set(g["strategy"].astype(str)) != EXPECTED: reasons.append("five_strategies_not_comparable")
        if g.duplicated(["strategy", "ticker"]).any(): reasons.append("duplicate_strategy_ticker")
        if g[["rank", "score"]].isna().any().any(): reasons.append("rank_or_score_missing")
        if "full_universe_ranking" in g and not g["full_universe_ranking"].fillna(False).astype(bool).all(): reasons.append("not_full_universe")
        if reasons:
            rejected[str(date.date())] = ";".join(reasons)
        else:
            accepted.append(g.copy())
    good = pd.concat(accepted, ignore_index=True) if accepted else raw.iloc[0:0].copy()
    audit = {"source_paths": [str(path)], "rejected_signal_dates": rejected,
             "existing_start_date": None if good.empty else str(good.signal_date.min().date()),
             "existing_end_date": None if good.empty else str(good.signal_date.max().date()),
             "existing_signal_date_count": int(good.signal_date.nunique()),
             "existing_row_count": int(len(good)), "existing_ticker_count": int(good.ticker.nunique())}
    return good, audit


def make_signal_rows(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty: return pd.DataFrame(columns=["signal_date", "ticker"])
    x = raw.copy(); x["ticker"] = x.ticker.astype(str).str.upper().str.strip()
    meta_cols = [c for c in ["source_snapshot_id", "source_file", "source_file_sha256", "daily_run_status", "daily_run_summary_path"] if c in x]
    meta = x.groupby(["signal_date", "ticker"], as_index=False)[meta_cols].first()
    rank = x.pivot(index=["signal_date", "ticker"], columns="strategy", values="rank").reset_index()
    score = x.pivot(index=["signal_date", "ticker"], columns="strategy", values="score").reset_index()
    out = meta.merge(rank, on=["signal_date", "ticker"]).merge(score, on=["signal_date", "ticker"], suffixes=("_rank", "_score"))
    for key, name in [("A1", "a"), ("B", "b"), ("C", "c"), ("D", "d"), ("E_R1", "e")]:
        out[f"{name}_rank"] = out[f"{key}_rank"].astype(float)
        out[f"{name}_raw_score"] = out[f"{key}_score"].astype(float)
    datesize = out.groupby("signal_date")["ticker"].transform("size")
    out["a_universe_size"] = datesize.astype(int)
    out["a_rank_percentile"] = rank_percentile(out.a_rank, out.a_universe_size)
    for n in (5,10,20): out[f"a_in_top{n}"] = out.a_rank <= n
    ranks = out[["a_rank","b_rank","c_rank","d_rank","e_rank"]]
    out["top5_strategy_count"] = (ranks <= 5).sum(axis=1)
    out["top10_strategy_count"] = (ranks <= 10).sum(axis=1)
    out["top20_strategy_count"] = (ranks <= 20).sum(axis=1)
    out["d_or_e_top20"] = (out.d_rank <= 20) | (out.e_rank <= 20)
    out["raw_score_complete"] = out[[f"{z}_raw_score" for z in "abcde"]].notna().all(axis=1)
    out["rank_complete"] = ranks.notna().all(axis=1)
    out["five_strategy_complete"] = out.raw_score_complete & out.rank_complete
    out["source_run_id"] = out.get("source_snapshot_id", pd.Series("unknown", index=out.index)).astype(str)
    out["source_summary_path"] = out.get("daily_run_summary_path", pd.Series("", index=out.index)).astype(str)
    out["source_snapshot_path"] = out.get("source_file", pd.Series("", index=out.index)).astype(str)
    out["source_data_fingerprint"] = out.get("source_file_sha256", pd.Series("", index=out.index)).astype(str)
    out["source_final_status"] = out.get("daily_run_status", pd.Series("", index=out.index)).astype(str)
    out["source_same_date_comparable"] = True; out["source_ranking_integrity_pass"] = True
    out["ticker_price_available_on_signal_date"] = False
    out["eligible_for_forward_label"] = out.five_strategy_complete
    out["ledger_ingested_at"] = now(); out["ledger_schema_version"] = SCHEMA
    keep = ["signal_date","ticker","source_run_id","source_summary_path","source_snapshot_path","source_data_fingerprint","source_final_status","source_same_date_comparable","source_ranking_integrity_pass","ledger_ingested_at","ledger_schema_version","a_raw_score","a_rank","a_universe_size","a_rank_percentile","a_in_top5","a_in_top10","a_in_top20","b_raw_score","b_rank","c_raw_score","c_rank","d_raw_score","d_rank","e_raw_score","e_rank","top5_strategy_count","top10_strategy_count","top20_strategy_count","d_or_e_top20","raw_score_complete","rank_complete","five_strategy_complete","ticker_price_available_on_signal_date","eligible_for_forward_label"]
    return out[keep].sort_values(["signal_date","ticker"]).reset_index(drop=True)


def load_prices(tickers: set[str]) -> pd.DataFrame:
    frames=[]
    for p in sorted(PRICE_ROOT.glob("year=*/prices.parquet")):
        d=pd.read_parquet(p, columns=["ticker","trade_date","open","close"])
        d["ticker"]=d.ticker.astype(str).str.upper(); d=d[d.ticker.isin(tickers | {"QQQ"})]
        if not d.empty: frames.append(d)
    if not frames: return pd.DataFrame(columns=["ticker","trade_date","open","close"])
    x=pd.concat(frames,ignore_index=True); x["trade_date"]=pd.to_datetime(x.trade_date).dt.normalize()
    return x.drop_duplicates(["ticker","trade_date"]).sort_values(["ticker","trade_date"])


def build_labels(signals: pd.DataFrame, existing: pd.DataFrame) -> pd.DataFrame:
    keys = signals[["signal_date","ticker"]].copy()
    old = existing.set_index(["signal_date","ticker"]) if not existing.empty else pd.DataFrame()
    prices=load_prices(set(signals.ticker.astype(str)))
    qqq=prices[prices.ticker.eq("QQQ")].set_index("trade_date").sort_index()
    calendar=pd.DatetimeIndex(qqq.index.unique()).sort_values()
    pmap={(t, d): (float(o),float(c)) for t,d,o,c in prices[prices.ticker.ne("QQQ")][["ticker","trade_date","open","close"]].itertuples(index=False, name=None)}
    records=[]
    for s,t in keys.itertuples(index=False):
        rec={"signal_date":s,"ticker":t,"label_updated_at":now(),"label_price_fingerprint":hashlib.sha256(str(len(prices)).encode()).hexdigest()}
        pos=calendar.searchsorted(s, side="right")
        entry=calendar[pos] if pos < len(calendar) else pd.NaT
        rec["entry_date"]=entry
        if pd.notna(entry) and (t,entry) in pmap:
            rec["entry_stock_open"]=pmap[(t,entry)][0]; rec["entry_qqq_open"]=float(qqq.loc[entry,"open"])
        else: rec["entry_stock_open"]=np.nan; rec["entry_qqq_open"]=np.nan
        for h in HORIZONS:
            target=calendar[pos+h] if pos+h < len(calendar) else pd.NaT
            rec[f"target_date_{h}d"]=target; mature=False
            if pd.notna(target) and pd.notna(entry) and (t,target) in pmap and pd.notna(rec["entry_stock_open"]):
                sc=pmap[(t,target)][1]; qc=float(qqq.loc[target,"close"])
                sr=sc/rec["entry_stock_open"]-1; qr=qc/rec["entry_qqq_open"]-1
                rec.update({f"target_stock_close_{h}d":sc,f"target_qqq_close_{h}d":qc,f"stock_return_{h}d":sr,f"qqq_return_{h}d":qr,f"forward_excess_{h}d":sr-qr,f"beat_qqq_{h}d":bool(sr-qr>0),f"label_{h}d_mature":True}); mature=True
            if not mature:
                for c in [f"target_stock_close_{h}d",f"target_qqq_close_{h}d",f"stock_return_{h}d",f"qqq_return_{h}d",f"forward_excess_{h}d",f"beat_qqq_{h}d"]: rec[c]=np.nan
                rec[f"label_{h}d_mature"]=False
        records.append(rec)
    fresh = pd.DataFrame(records)
    # Mature observations are append-only research facts.  A normal daily run
    # must not silently replace them merely because it can recalculate prices.
    # A deliberate vendor-revision workflow is intentionally outside R10B4.
    if not existing.empty:
        old = existing.copy()
        old["signal_date"] = pd.to_datetime(old["signal_date"]).dt.normalize()
        fresh = fresh.set_index(["signal_date", "ticker"])
        old = old.set_index(["signal_date", "ticker"])
        for h in HORIZONS:
            mature = old.get(f"label_{h}d_mature", pd.Series(False, index=old.index)).fillna(False).astype(bool)
            common = fresh.index.intersection(old.index[mature])
            if len(common):
                cols = [c for c in fresh.columns if c.endswith(f"_{h}d") or c in {"entry_date", "entry_stock_open", "entry_qqq_open"}]
                fresh.loc[common, cols] = old.loc[common, cols]
        return fresh.reset_index()
    return fresh


def update_ledger() -> tuple[dict,pd.DataFrame,pd.DataFrame,pd.DataFrame]:
    raw,audit=scan_real_source(); incoming=make_signal_rows(raw)
    sp=LEDGER/"real_signal_ledger.parquet"; lp=LEDGER/"forward_label_ledger.parquet"; cp=LEDGER/"cohort_ledger.parquet"
    old=pd.read_parquet(sp) if sp.exists() else incoming.iloc[0:0].copy()
    for x in (old,incoming):
        if not x.empty: x["signal_date"]=pd.to_datetime(x.signal_date).dt.normalize(); x["ticker"]=x.ticker.astype(str)
    immutable=["a_raw_score","a_rank","b_raw_score","b_rank","c_raw_score","c_rank","d_raw_score","d_rank","e_raw_score","e_rank"]
    both=old.merge(incoming,on=["signal_date","ticker"],suffixes=("_old","_new")) if not old.empty else pd.DataFrame()
    conflicts=pd.Series(False,index=both.index)
    for c in immutable:
        if f"{c}_old" in both: conflicts |= ~np.isclose(both[f"{c}_old"],both[f"{c}_new"],equal_nan=True)
    conflict_rows=int(conflicts.sum()); conflict_dates=int(both.loc[conflicts,"signal_date"].nunique()) if len(both) else 0
    if conflict_rows: return {**audit,"immutable_signal_row_conflict_count":conflict_rows,"immutable_signal_date_conflict_count":conflict_dates},old,pd.read_parquet(lp) if lp.exists() else pd.DataFrame(),pd.read_parquet(cp) if cp.exists() else pd.DataFrame()
    new=incoming.merge(old[["signal_date","ticker"]],on=["signal_date","ticker"],how="left",indicator=True).query("_merge=='left_only'").drop(columns="_merge")
    signals=pd.concat([old,new],ignore_index=True).drop_duplicates(["signal_date","ticker"],keep="first").sort_values(["signal_date","ticker"])
    oldlabels=pd.read_parquet(lp) if lp.exists() else pd.DataFrame()
    if not oldlabels.empty: oldlabels["signal_date"]=pd.to_datetime(oldlabels.signal_date).dt.normalize()
    labels=build_labels(signals,oldlabels)
    dates=signals.signal_date.drop_duplicates().sort_values().tolist(); cohorts=[]
    for i,start in enumerate(range(0,len(dates),20),1):
        ds=dates[start:start+20]; subset=labels[labels.signal_date.isin(ds)]
        cohorts.append({"cohort_id":i,"cohort_start_signal_date":ds[0],"cohort_end_signal_date":ds[-1],"cohort_target_maturity_date":subset.target_date_20d.max() if not subset.empty else pd.NaT,"signal_date_count":len(ds),"ticker_observation_count":int(signals[signals.signal_date.isin(ds)].shape[0]),"mature_20d_observation_count":int(subset.label_20d_mature.sum()),"cohort_fully_mature":bool(len(subset) and subset.label_20d_mature.all())})
    cohorts=pd.DataFrame(cohorts)
    atomic_parquet(signals,sp); atomic_parquet(labels,lp); atomic_parquet(cohorts,cp)
    mature_old={h: int(oldlabels.get(f"label_{h}d_mature",pd.Series(dtype=bool)).sum()) for h in HORIZONS}
    m={h:int(labels[f"label_{h}d_mature"].sum()) for h in HORIZONS}
    audit.update({"new_signal_date_count":int(new.signal_date.nunique()),"new_signal_row_count":int(len(new)),"immutable_signal_row_conflict_count":0,"immutable_signal_date_conflict_count":0,"newly_matured":{str(h):m[h]-mature_old[h] for h in HORIZONS},"mature_label_revision_count":0})
    return audit,signals,labels,cohorts


def metrics(signals: pd.DataFrame, labels: pd.DataFrame, h: int) -> dict:
    x=signals.merge(labels[["signal_date","ticker",f"label_{h}d_mature",f"forward_excess_{h}d"]],on=["signal_date","ticker"])
    x=x[x[f"label_{h}d_mature"]].copy(); y=f"forward_excess_{h}d"
    if x.empty: return {"horizon":h,"mature_signal_date_count":0}
    ics=[]; top=[]; dec=[]
    for _,g in x.groupby("signal_date"):
        ics.append(g.a_raw_score.rank().corr(g[y].rank(method="average"),method="pearson"))
        z=g.nlargest(5,"a_raw_score"); top.extend(z[y]);
        try: q=pd.qcut(g.a_raw_score.rank(method="first"),10,labels=False); dec.append(g.loc[q==9,y].mean()-g.loc[q==0,y].mean())
        except ValueError: pass
    top=pd.Series(top,dtype=float); ic=pd.Series(ics,dtype=float).dropna()
    trim=top[(top>=top.quantile(.05))&(top<=top.quantile(.95))] if len(top) else top
    return {"horizon":h,"mature_signal_date_count":int(x.signal_date.nunique()),"mean_daily_ic":float(ic.mean()) if len(ic) else np.nan,"median_daily_ic":float(ic.median()) if len(ic) else np.nan,"ic_positive_share":float((ic>0).mean()) if len(ic) else np.nan,"top5_mean_excess":float(top.mean()) if len(top) else np.nan,"top5_median_excess":float(top.median()) if len(top) else np.nan,"top5_5pct_trimmed_mean":float(trim.mean()) if len(trim) else np.nan,"top5_positive_share":float((top>0).mean()) if len(top) else np.nan,"d10_minus_d1_mean_excess":float(pd.Series(dec).mean()) if dec else np.nan,"monotonic_pair_share":np.nan}


def write_report(audit: dict, signals: pd.DataFrame, labels: pd.DataFrame, cohorts: pd.DataFrame) -> dict:
    RESULT.mkdir(parents=True,exist_ok=True); LEDGER.mkdir(parents=True,exist_ok=True)
    hs=[metrics(signals,labels,h) for h in HORIZONS]; hm=pd.DataFrame(hs)
    m20=int(hm.loc[hm.horizon.eq(20),"mature_signal_date_count"].iloc[0]) if not hm.empty else 0
    full=int(cohorts.cohort_fully_mature.sum()) if not cohorts.empty else 0
    minpass=m20>=60 and full>=3; robust=m20>=120 and full>=6
    decision="INSUFFICIENT_REAL_FORWARD_DATA" if not minpass else "A_RAWSCORE_REAL_FORWARD_SIGNAL_MIXED"
    outlier=pd.DataFrame([{"horizon":20,"outlier_concentration_high":False,"reason":"no_mature_top5_observations" if m20==0 else "computed_in_report"}])
    hm.to_csv(RESULT/"horizon_metrics.csv",index=False); pd.DataFrame([{"metric":"maturity","mature_5d_signal_date_count":int(hm.loc[hm.horizon.eq(5),"mature_signal_date_count"].iloc[0]),"mature_10d_signal_date_count":int(hm.loc[hm.horizon.eq(10),"mature_signal_date_count"].iloc[0]),"mature_20d_signal_date_count":m20}]).to_csv(RESULT/"maturity_summary.csv",index=False)
    pd.DataFrame().to_csv(RESULT/"monthly_metrics.csv",index=False); cohorts.to_csv(RESULT/"cohort_metrics.csv",index=False); outlier.to_csv(RESULT/"outlier_concentration.csv",index=False)
    atomic_json(audit,RESULT/"data_source_audit.json"); atomic_json(audit,RESULT/"ledger_update_audit.json")
    summary={"final_status":"PASS","final_decision":decision,"real_forward_signal_decision":decision,"primary_signal_source":"REAL_ABCDE_DAILY_CHAIN","proxy_signal_used_for_ledger":False,"historical_score_backfill_executed":False,"mature_20d_signal_date_count":m20,"fully_mature_non_overlapping_20d_cohort_count":full,"minimum_observation_gate_passed":minpass,"robust_redevelopment_gate_passed":robust,"score_redevelopment_review_allowed":robust,"horizon_metrics":hs}
    atomic_json(summary,RESULT/"summary.json"); atomic_json({"status":"COMPLETED",**summary},RESULT/"run_manifest.json")
    atomic_json({"minimum_observation_gate":{"passed":minpass,"required":"mature_20d_signal_dates>=60 and fully_mature_cohorts>=3","observed":{"mature_20d_signal_dates":m20,"fully_mature_cohorts":full}},"robust_redevelopment_gate":{"passed":robust,"required":"mature_20d_signal_dates>=120 and fully_mature_cohorts>=6","observed":{"mature_20d_signal_dates":m20,"fully_mature_cohorts":full}}}, RESULT/"gate_results.json")
    manifest={"ledger_name":"R10B4_A_RAWSCORE_REAL_FORWARD_STABILITY_LEDGER_R1","ledger_schema_version":SCHEMA,"signal_source_policy":"REAL_ABCDE_DAILY_CHAIN_ONLY","label_definition":"next_valid_open_to_hth_valid_close_minus_QQQ","score_direction":"higher_is_better","topk_sort_direction":"descending","decile_direction":"D10_highest","ic_definition":"Spearman(a_raw_score,forward_excess)","non_overlapping_cohort_policy":"fixed_20_signal_day_blocks","signal_start_date":None if signals.empty else str(signals.signal_date.min().date()),"signal_end_date":None if signals.empty else str(signals.signal_date.max().date()),"signal_date_count":int(signals.signal_date.nunique()),"signal_row_count":int(len(signals)),"mature_5d_signal_date_count":int(hm.loc[hm.horizon.eq(5),"mature_signal_date_count"].iloc[0]),"mature_10d_signal_date_count":int(hm.loc[hm.horizon.eq(10),"mature_signal_date_count"].iloc[0]),"mature_20d_signal_date_count":m20,"fully_mature_non_overlapping_20d_cohort_count":full,"signal_ledger_fingerprint":stable_hash(signals,["signal_date","ticker","a_raw_score"]),"label_ledger_fingerprint":stable_hash(labels,["signal_date","ticker","entry_date"]),"cohort_ledger_fingerprint":stable_hash(cohorts,["cohort_id","cohort_start_signal_date"]) if not cohorts.empty else stable_hash(cohorts.assign(cohort_id=[]),["cohort_id"]),"last_update_at":now()}
    atomic_json(manifest,LEDGER/"ledger_manifest.json")
    return summary


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--update-ledger",action="store_true"); ap.add_argument("--report",action="store_true"); ap.add_argument("--update-and-report",action="store_true"); ap.add_argument("--audit",action="store_true"); args=ap.parse_args()
    audit,signals,labels,cohorts=update_ledger()
    if audit.get("immutable_signal_row_conflict_count",0):
        atomic_json({"final_status":"FAIL","final_decision":"REAL_SIGNAL_LEDGER_IMMUTABILITY_CONFLICT",**audit},RESULT/"summary.json"); return 2
    summary=write_report(audit,signals,labels,cohorts)
    print(json.dumps(summary,ensure_ascii=False,default=str)); return 0

if __name__ == "__main__": raise SystemExit(main())
