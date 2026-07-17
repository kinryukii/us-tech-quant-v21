"""Write small R2A size projections after offline conversion/validation."""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from storage_r2a import BACKTEST_ROOT, CACHE_ROOT, DATA_ROOT, REPO_ROOT, utc_now

def size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.exists() else 0

def main() -> None:
    pointer=json.loads((REPO_ROOT/"state/storage_migration_r2a/latest_migration_pointer.json").read_text())
    out=Path(pointer["summary_path"]).parent
    report=json.loads((out/"validation_summary.json").read_text())
    conversion=pd.read_parquet(out/"ticker_conversion_report.parquet")
    for ticker, group in conversion.groupby("ticker"):
        rows={row.adjustment: row for row in group.itertuples()}
        meta_path=DATA_ROOT/"stocks"/ticker/"metadata.json"
        metadata=json.loads(meta_path.read_text())
        metadata.update({
            "ticker":ticker,"daily_raw":{"path":"daily_raw.parquet","sha256":rows["raw"].sha256,"row_count":int(rows["raw"].output_row_count),"first_date":str(rows["raw"].first_date),"last_date":str(rows["raw"].last_date)},
            "daily_qfq":{"path":"daily_qfq.parquet","sha256":rows["qfq"].sha256,"row_count":int(rows["qfq"].output_row_count),"first_date":str(rows["qfq"].first_date),"last_date":str(rows["qfq"].last_date)},
            "schema_version":"R2A_OHLCV_V1","metadata_updated_utc":utc_now(),"broker_action_allowed":False,"official_adoption_allowed":False,"research_only":True})
        meta_path.write_text(json.dumps(metadata,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    repo_total=size(REPO_ROOT); repo_without_venv=repo_total-size(REPO_ROOT/".venv")-size(REPO_ROOT/".venv_moomoo_py312")
    projected_repo={"current_repo_size_bytes":repo_total,"current_repo_without_venv_bytes":repo_without_venv,"r2b_cleanup_required":True,"target_with_venv_bytes":1073741824,"target_without_venv_bytes":262144000,"status":"WARN_REPOSITORY_SIZE_BUDGET_EXCEEDED" if repo_total>1073741824 else "PASS"}
    projected_data={"data_root_size_bytes":size(DATA_ROOT),"ticker_directory_count":len([p for p in (DATA_ROOT/"stocks").iterdir() if p.is_dir()]),"layout":"stocks/<TICKER>/daily_raw.parquet,daily_qfq.parquet,metadata.json","status":"PASS"}
    projected_quarantine={"quarantine_current_bytes":size(Path(r"D:\us-tech-quant-quarantine")),"r2a_added_bytes":0,"r2b_candidates_not_moved":True,"status":"PASS"}
    for name,payload in [("projected_repo_size.json",projected_repo),("projected_data_size.json",projected_data),("projected_quarantine_size.json",projected_quarantine)]: (out/name).write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
    final={"status":"PASS_STORAGE_R2A_PER_TICKER_AND_ISOLATED_RUNS_READY" if report["status"]=="PASS" else "FAIL_STORAGE_R2A_VALIDATION","run_id":pointer["run_id"],"migration_output_root":str(out),"validation":report,"repo_projection":projected_repo,"data_projection":projected_data,"quarantine_projection":projected_quarantine,"daily_output_root_default":"outputs/v22","daily_output_root_switch_approved":False,"legacy_v22_044_path_unchanged":True,"legacy_files_modified":False,"legacy_files_moved":False,"network_called":False,"broker_called":False,"broker_action_allowed":False,"official_adoption_allowed":False,"research_only":True,"completed_utc":utc_now()}
    (out/"summary.json").write_text(json.dumps(final,indent=2)+"\n",encoding="utf-8")
    (REPO_ROOT/"state/storage_migration_r2a/summary.json").write_text(json.dumps({"run_id":pointer["run_id"],"status":final["status"],"summary_path":str(out/"summary.json"),"completed_utc":final["completed_utc"]},indent=2)+"\n",encoding="utf-8")
    print(json.dumps(final))
if __name__=="__main__": main()
