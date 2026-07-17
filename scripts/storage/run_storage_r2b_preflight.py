"""Offline non-destructive R2B gate. It never deletes legacy data."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

REPO=Path(r"D:\us-tech-quant"); DATA=Path(r"D:\us-tech-quant-data"); BACK=Path(r"D:\us-tech-quant-backtests")

def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def main():
    run=f"STORAGE_R2B_AGGRESSIVE_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out=BACK/"_system_migrations"/run; out.mkdir(parents=True,exist_ok=False)
    tickers=[p for p in (DATA/"stocks").iterdir() if p.is_dir()]
    checks=[
      ("per_ticker_count",len(tickers)==326,f"count={len(tickers)}"),
      ("raw_qfq_metadata_count",all((p/'daily_raw.parquet').exists() and (p/'daily_qfq.parquet').exists() and (p/'metadata.json').exists() for p in tickers),"R2A assets present"),
      ("abcde_rank_rebuild_without_v21_246",False,"abcde_local_effectiveness_backtest_r1.py discover_panel() requires technical_forward_join_panel or outputs ranking snapshots; no raw-OHLCV ranking adapter exists"),
      ("abcde_top20_equality_without_legacy",False,"Top20 comparison cannot be computed without an adapter that preserves the existing ranking/factor logic"),
      ("v22_daily_root_switch",False,"V22.040/V22.044 still contain legacy repo outputs paths; R2A deliberately left formal switch disabled"),
    ]
    rows=[{"check":n,"passed":p,"detail":d,"network_called":False,"broker_called":False,"broker_action_allowed":False,"official_adoption_allowed":False,"research_only":True} for n,p,d in checks]
    pd.DataFrame(rows).to_parquet(out/'switch_validation_report.parquet',index=False,engine='pyarrow',compression='zstd')
    pd.DataFrame(rows).to_parquet(out/'offline_test_results.parquet',index=False,engine='pyarrow',compression='zstd')
    pd.DataFrame([],columns=['legacy_path','new_path','comparison','maximum_absolute_difference','maximum_relative_difference','affected_column_count','affected_row_count','status']).to_parquet(out/'legacy_vs_new_comparison.parquet',index=False,engine='pyarrow',compression='zstd')
    pd.DataFrame([],columns=['path','classification','reason','size_bytes','sha256','related_dataset','related_run','related_snapshot','validation_passed','deleted_at','delete_status']).to_parquet(out/'deletion_manifest.parquet',index=False,engine='pyarrow',compression='zstd')
    pd.DataFrame([],columns=['path','error','time']).to_parquet(out/'deletion_failures.parquet',index=False,engine='pyarrow',compression='zstd')
    summary={"status":"FAIL_STORAGE_AGGRESSIVE_SWITCH_VALIDATION","run_id":run,"blocking_checks":[r for r in rows if not r['passed']],"legacy_files_deleted":False,"existing_files_permanently_deleted":0,"rollback_data_available":True,"rebuild_from_per_ticker_required_if_issue":False,"network_called":False,"broker_called":False,"broker_action_allowed":False,"official_adoption_allowed":False,"research_only":True,"created_utc":now()}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+"\n",encoding='utf-8')
    (out/'execution_journal.jsonl').write_text(json.dumps({"time":now(),"event":"R2B_PREFLIGHT_STOP","reason":"ABCDE and V22 output-root switch validation failed; no deletion attempted"})+'\n',encoding='utf-8')
    (out/'STORAGE_R2B_AGGRESSIVE_REPORT.md').write_text('# R2B aggressive preflight stopped\n\nNo legacy file was deleted. The current ABCDE engine requires legacy panel/ranking artifacts; the required no-panel parity validation cannot pass until a separately reviewed adapter is implemented.\n',encoding='utf-8')
    pd.DataFrame([{"path":str(REPO/'outputs'),"exists":(REPO/'outputs').exists()},{"path":str(REPO/'exports'),"exists":(REPO/'exports').exists()}]).to_parquet(out/'repository_final_inventory.parquet',index=False,engine='pyarrow')
    pd.DataFrame([{"path":str(Path(r'D:\us-tech-quant-cache')),"status":"NOT_CLEARED_DUE_TO_FAILED_GATE"}]).to_parquet(out/'cache_final_inventory.parquet',index=False,engine='pyarrow')
    pd.DataFrame([],columns=['path','action','status']).to_parquet(out/'archive_cleanup_report.parquet',index=False,engine='pyarrow')
    (out/'repository_size_report.json').write_text(json.dumps({"status":"NOT_EVALUATED_AFTER_PURGE","reason":"purge blocked"},indent=2)+'\n',encoding='utf-8')
    (out/'storage_guard_test_results.json').write_text(json.dumps({"status":"NOT_ENABLED_R2B","reason":"formal V22 output switch blocked"},indent=2)+'\n',encoding='utf-8')
    state=REPO/'state/storage_migration_r2b'; state.mkdir(parents=True,exist_ok=True)
    (state/'latest_migration_pointer.json').write_text(json.dumps({"run_id":run,"status":summary['status'],"summary_path":str(out/'summary.json')},indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary)); return 2
if __name__=='__main__': raise SystemExit(main())
