#!/usr/bin/env python
"""R7: validate real ABCDE snapshots and backtest only when dates permit it."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

STRATEGIES = ["A1", "B", "C", "D", "E_R1"]
POLICIES = [*(f"{s}_TOP5_DAILY_EQUAL" for s in STRATEGIES), *(f"{s}_TOP5_ENTRY_EXIT10_NO_REBAL" for s in STRATEGIES), "QQQ_BUY_HOLD", "SPY_BUY_HOLD", "CASH"]
MAIN_POLICY = "A1_TOP5_ENTRY_EXIT10_NO_REBAL"

def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""): h.update(b)
    return h.hexdigest()

def load_master(path: Path) -> pd.DataFrame:
    d=pq.read_table(path).to_pandas()
    d["signal_date"]=d["signal_date"].astype(str).str[:10]
    d["strategy"]=d["strategy"].astype(str)
    d["ticker"]=d["ticker"].astype(str).str.upper()
    d["rank"]=pd.to_numeric(d["rank"],errors="coerce")
    return d

def initialize_from_official_ranking(master_path: Path, ranking_path: Path) -> None:
    """Create the R6 append-only store from a verified current daily artifact."""
    src=pd.read_csv(ranking_path)
    mapping={"A1_CONTROL":"A1","B_STATIC_MOMENTUM":"B","C_DYNAMIC_MOMENTUM":"C","D_WEIGHT_OPTIMIZED_REFERENCE":"D","E_R1_DEFENSIVE_REFERENCE":"E_R1"}
    if not {"strategy_name","rank","ticker","latest_date"}.issubset(src.columns): raise RuntimeError("OFFICIAL_RANKING_SCHEMA_INVALID")
    src["strategy"]=src.strategy_name.map(mapping); src["signal_date"]=src.latest_date.astype(str).str[:10]
    if src.strategy.isna().any() or src.duplicated(["signal_date","strategy","ticker"]).any(): raise RuntimeError("OFFICIAL_RANKING_KEYS_INVALID")
    for s in STRATEGIES:
        g=src[src.strategy==s]
        if len(g)<10 or set(g["rank"].astype(int)) != set(range(1,len(g)+1)): raise RuntimeError("OFFICIAL_RANKING_INTEGRITY_INVALID")
    digest=sha(ranking_path); now=pd.Timestamp.now(tz="UTC").isoformat()
    out=pd.DataFrame({"signal_date":src.signal_date,"strategy":src.strategy,"rank":src["rank"].astype(int),"ticker":src.ticker.astype(str).str.upper(),"score":src.get("score"),"source_file":str(ranking_path),"source_file_sha256":digest,"source_snapshot_id":src.get("source_snapshot_id"),"snapshot_authenticity":"DAILY_SUCCESS_OUTPUT","capture_method":"R7_INITIAL_OFFICIAL_IMPORT","captured_at":now,"price_max_date":src.signal_date,"data_trust_flag":"MOOMOO_ONLY_COMPACT_PROXY","ranking_scope":"FULL_UNIVERSE","full_universe_ranking":True,"daily_run_status":"PASS_V22_044_DAILY_SINGLE_ENTRYPOINT_FROZEN","daily_run_summary_path":"","capture_timestamp":now,"capture_version":"R7"})
    master_path.parent.mkdir(parents=True,exist_ok=True)
    if master_path.exists():
        old=load_master(master_path)
        same=old[old.signal_date.isin(set(out.signal_date))]
        if not same.empty:
            left=same[["signal_date","strategy","ticker","rank","score"]].sort_values(["signal_date","strategy","ticker"]).reset_index(drop=True)
            right=out[["signal_date","strategy","ticker","rank","score"]].sort_values(["signal_date","strategy","ticker"]).reset_index(drop=True)
            left["score"]=pd.to_numeric(left["score"],errors="coerce").round(12)
            right["score"]=pd.to_numeric(right["score"],errors="coerce").round(12)
            if left.equals(right): return
            raise RuntimeError("SAME_DATE_SNAPSHOT_CONFLICT")
        out=pd.concat([old,out],ignore_index=True)
    pq.write_table(pa.Table.from_pandas(out,preserve_index=False),master_path,compression="zstd")

def integrity(master: pd.DataFrame) -> tuple[dict, pd.DataFrame, list[str]]:
    dates=sorted(master.signal_date.dropna().unique())
    latest=dates[-1] if dates else None
    rows=[]; ok=bool(latest)
    expected_sets={}
    if latest:
        x=master[master.signal_date==latest]
        for s in STRATEGIES:
            g=x[x.strategy==s].copy(); ranks=g["rank"].dropna().astype(int)
            expected_sets[s]=set(g.ticker)
            continuous=set(ranks)==set(range(1,len(g)+1))
            row={"signal_date":latest,"strategy":s,"row_count":len(g),"minimum_rank":int(ranks.min()) if len(ranks) else None,"maximum_rank":int(ranks.max()) if len(ranks) else None,"duplicate_ticker_count":int(g.ticker.duplicated().sum()),"duplicate_rank_count":int(ranks.duplicated().sum()),"missing_rank_count":int(len(g)-len(set(ranks)&set(range(1,len(g)+1)))),"rank_continuous":continuous,"ticker_set_difference_vs_other_strategies":0}
            rows.append(row); ok=ok and len(g)>=10 and not row["duplicate_ticker_count"] and not row["duplicate_rank_count"] and continuous
        all_union=set().union(*expected_sets.values()) if expected_sets else set()
        for row in rows: row["ticker_set_difference_vs_other_strategies"]=len(expected_sets[row["strategy"]]^all_union)
        ok=ok and all(not r["ticker_set_difference_vs_other_strategies"] for r in rows)
    common=sorted(set.intersection(*(set(master[master.strategy==s].signal_date) for s in STRATEGIES))) if all((master.strategy==s).any() for s in STRATEGIES) else []
    return {"latest_signal_date":latest,"historical_signal_date_count":len(dates),"common_signal_date_count":len(common),"common_history_start":common[0] if common else None,"common_history_end":common[-1] if common else None,"ranking_integrity_pass":bool(ok)},pd.DataFrame(rows),dates

def write_json(path: Path, value: dict):
    path.write_text(json.dumps(value,indent=2,default=str)+"\n",encoding="utf-8")

def run(master_path: Path, results: Path, official_ranking: Path | None=None) -> dict:
    results.mkdir(parents=True,exist_ok=True)
    if official_ranking is not None and official_ranking.exists(): initialize_from_official_ranking(master_path,official_ranking)
    if not master_path.exists(): raise RuntimeError("R6_RANKING_MASTER_MISSING")
    master=load_master(master_path)
    info,audit,_=integrity(master)
    audit.to_csv(results/"ranking_integrity_audit.csv",index=False)
    if not info["ranking_integrity_pass"]:
        status="BLOCKED_LATEST_RANKING_INTEGRITY_FAILED"; scope="NONE"; backtest=False
    elif info["common_signal_date_count"]<2:
        status="PASS_DAILY_CAPTURED_WAITING_FOR_SECOND_SIGNAL_DATE"; scope="WAITING_FOR_SECOND_REAL_SIGNAL_DATE"; backtest=False
    elif info["common_signal_date_count"]<=4:
        status="PASS_EXECUTION_INTERVAL_VALIDATION"; scope="EXECUTION_INTERVAL_VALIDATION"; backtest=True
    elif info["common_signal_date_count"]<20:
        status="PASS_SHORT_SAMPLE_BACKTEST"; scope="SHORT_SAMPLE_ONLY"; backtest=True
    else:
        status="PASS_SHORT_SAMPLE_BACKTEST"; scope="SHORT_SAMPLE_WITH_ELIGIBLE_WINDOWS"; backtest=True
    price_manifest=master_path.parents[2]/"moomoo"/"metadata"/"abcde_price_universe_r2.csv"
    price_tickers=set(pd.read_csv(price_manifest)["ticker"].astype(str).str.upper()) if price_manifest.exists() else set()
    latest_ranked=set(master[master.signal_date==info["latest_signal_date"]].ticker)
    unranked=sorted(price_tickers-latest_ranked)
    # Backtest implementation is intentionally not invoked without at least two
    # dated, common real snapshots.  This prevents fabricated intervals/NAV.
    summary={**info,"final_status":status,"backtest_run":backtest,"backtest_scope":scope,"predeclared_main_policy":MAIN_POLICY,"predeclared_main_total_return":None,"predeclared_main_max_drawdown":None,"predeclared_main_daily_win_rate_vs_qqq":None,"qqq_total_return":None,"predeclared_main_excess_vs_qqq":None,"annualization_reliable":False,"long_horizon_claim_allowed":False,"ranking_universe_count":int(audit.row_count.iloc[0]) if len(audit) else 0,"price_universe_count":len(price_tickers),"unranked_price_ticker_count":len(unranked),"unranked_tickers":unranked,"unranked_reason":"STALE_PRICE_DATE_EXCLUDED_FROM_SAME_DATE_RANKING" if unranked else None,"snapshot_master_path":str(master_path),"snapshot_master_sha256":sha(master_path),"broker_action_allowed":False,"official_adoption_allowed":False,"research_only":True}
    write_json(results/"latest_run_summary.json",summary)
    pd.DataFrame([{"policy":p,"status":"NOT_RUN" if not backtest else "PENDING_EXECUTION_ENGINE","reason":"requires real dated execution interval"} for p in POLICIES]).to_csv(results/"policy_summary.csv",index=False)
    (results/"final_research_report.md").write_text(f"# R7 conditional ABCDE run\n\nStatus: `{status}`.\n\nReal common signal dates: {info['common_signal_date_count']}. No NAV/trades are emitted until a real interval exists.\n",encoding="utf-8")
    manifest=[]
    for p in results.iterdir():
        if p.is_file(): manifest.append({"path":str(p),"size_bytes":p.stat().st_size,"sha256":sha(p)})
    pd.DataFrame(manifest).to_csv(results/"output_file_manifest.csv",index=False)
    return summary

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--master-path",type=Path,required=True); ap.add_argument("--results-root",type=Path,required=True); ap.add_argument("--official-ranking-path",type=Path); a=ap.parse_args()
    print(json.dumps(run(a.master_path,a.results_root,a.official_ranking_path),indent=2,default=str))
if __name__=="__main__": main()
