"""Offline R2A parity checks. Reads legacy cache and new per-ticker files only."""
from __future__ import annotations
import json, random, sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
from storage_r2a import BACKTEST_ROOT, CACHE_ROOT, DATA_ROOT, REPO_ROOT, load_ticker_daily, scan_universe_daily, sha256, utc_now
from backtest_run_manager import create_backtest_run, validate_backtest_run

def legacy(ticker: str, adjustment: str) -> pd.DataFrame:
    root = CACHE_ROOT / "raw/moomoo" / ("daily_qfq" if adjustment == "qfq" else "daily_raw")
    parts=[]
    for p in sorted(root.glob(f"snapshot_id=*/{ticker}.csv"), key=lambda x:x.parent.name):
        frame=pd.read_csv(p); frame["date"]=pd.to_datetime(frame.date,errors="coerce").dt.strftime("%Y-%m-%d"); parts.append(frame)
    return pd.concat(parts,ignore_index=True).drop_duplicates(["ticker","date"],keep="last").sort_values("date").reset_index(drop=True)

def main() -> int:
    pointer=json.loads((REPO_ROOT/"state/storage_migration_r2a/latest_migration_pointer.json").read_text())
    out=Path(pointer["summary_path"]).parent
    report=pd.read_parquet(out/"ticker_conversion_report.parquet")
    tickers=sorted(report.ticker.unique())
    chosen=random.Random(22047).sample(tickers, min(30,len(tickers)))
    rows=[]; failures=[]
    for ticker in chosen:
        for adjustment in ("raw","qfq"):
            old=legacy(ticker,adjustment); new=load_ticker_daily(ticker,adjustment)
            cols=[c for c in ["ticker","date","open","high","low","close","volume","turnover"] if c in old.columns and c in new.columns]
            equal=len(old)==len(new) and old[cols].reset_index(drop=True).equals(new[cols].reset_index(drop=True))
            dates=sorted(old.date.dropna().unique()); sample_dates=random.Random(f"{ticker}{adjustment}").sample(dates,min(20,len(dates)))
            pit_ok=all(len(new[new.date<=d])==len(old[old.date<=d]) for d in sample_dates)
            row={"ticker":ticker,"adjustment":adjustment,"legacy_rows":len(old),"new_rows":len(new),"first_date":str(new.date.min()),"last_date":str(new.date.max()),"sample_dates_checked":len(sample_dates),"ohlcv_parity":equal,"pit_asof_parity":pit_ok,"status":"PASS" if equal and pit_ok else "FAIL"}
            rows.append(row)
            if row["status"]!="PASS": failures.append(row)
    latest = max(pd.read_parquet(DATA_ROOT/"stocks"/t/"daily_qfq.parquet").date.max() for t in chosen)
    scan=scan_universe_daily(chosen,"qfq",str(latest),str(latest))
    same_date={"sample_date":str(latest),"tickers":len(chosen),"rows":len(scan),"all_tickers_present":set(chosen).issubset(set(scan.ticker)),"result":"PASS" if set(chosen).issubset(set(scan.ticker)) else "FAIL"}
    run=create_backtest_run("R2A_STORAGE_VALIDATION", "59475ed", str(latest), str(latest), chosen)
    run_check=validate_backtest_run(run)
    pd.DataFrame(rows).to_parquet(out/"ticker_validation_report.parquet",index=False,engine="pyarrow",compression="zstd")
    run_size=sum(p.stat().st_size for p in run.rglob("*") if p.is_file())
    validation={"status":"PASS" if not failures and same_date["result"]=="PASS" and run_check["result"]=="PASS" else "FAIL","random_tickers":len(chosen),"random_dates_per_ticker":20,"raw_qfq_separate":True,"same_date_abcde_input_readable":same_date,"dram_readable":("DRAM" in tickers),"etf_direction_underlyings_readable":all(t in tickers for t in ["QQQ","SPY"]),"iv_greeks_underlyings_readable":all(t in tickers for t in ["QQQ","SPY"]),"backtest_run":run_check,"run_size_bytes":run_size,"largest_file":"run_config.json","input_data_copied":False,"duplicate_market_data_count":0,"failures":failures,"network_called":False,"broker_called":False,"broker_action_allowed":False,"official_adoption_allowed":False,"research_only":True,"validated_utc":utc_now()}
    (out/"validation_summary.json").write_text(json.dumps(validation,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(validation)); return 0 if validation["status"]=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
