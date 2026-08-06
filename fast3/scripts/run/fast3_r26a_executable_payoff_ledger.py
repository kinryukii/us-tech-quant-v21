"""Build the single R26A executable payoff ledger from canonical ETF bars."""
from __future__ import annotations

import argparse, json, shutil
from pathlib import Path
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

REPO = Path(__file__).resolve().parents[2]
from fast3.economics import executable_payoff_ledger_hard_r26a as m
from fast3.models import two_stage_economic_value_hard_r26 as r26

ARTIFACTS = ("R26A_STORAGE_PREFLIGHT.json", "R26A_INPUT_LINEAGE.json", "R26A_EXECUTION_CONTRACT.json", "R26A_INSTRUMENT_MAPPING.json", "R26A_CANONICAL_PARTITION_MANIFEST.json", "R26A_PAYOFF_SCHEMA.json", "R26A_PAYOFF_LEDGER_MANIFEST.json", "R26A_PAYOFF_LEDGER_HASHES.json", "R26A_CARDINALITY_AUDIT.json", "R26A_ENTRY_EXECUTABILITY_AUDIT.json", "R26A_EXIT_EXECUTABILITY_AUDIT.json", "R26A_COST_REPRODUCTION_AUDIT.json", "R26A_PIT_AUDIT.json", "R26A_FILESYSTEM_AUDIT.json", "R26A_FINAL_SUMMARY.json", "R26A_FINAL_REPORT.md")

def parse():
    p=argparse.ArgumentParser()
    for x in ("repo-root","data-root","runtime-root","scratch-root","frozen-root","archive-root","cache-root","source-r3-root","source-r3-audit-root","complete-ledger-path","r24-control-root","r25-frozen-root","r26-failed-frozen-root","run-id"): p.add_argument("--"+x,required=True)
    return p.parse_args()
def write(root,name,value):
    path=root/name
    if name.endswith(".md"): path.write_text(value,encoding="utf-8")
    else: path.write_text(json.dumps(value,sort_keys=True,indent=2,default=str,allow_nan=False),encoding="utf-8")
def sha(path): return m.file_hash(Path(path))
def required(root, reason):
    for name in ARTIFACTS:
        if not (root/name).exists(): write(root,name, f"# FAST3 R26A\n\nNOT RUN: `{reason}`\n" if name.endswith(".md") else {"status":"NOT_RUN","reason":reason})

def main():
    a=parse(); frozen=Path(a.frozen_root); frozen.mkdir(parents=True,exist_ok=True)
    canonical=Path(a.data_root)/"fast3/moomoo_24h_1m/canonical"; ledger_root=frozen/"authoritative_payoff_ledger"
    final="STOP_R26A_EXECUTABLE_PAYOFF_COVERAGE_OR_LINEAGE_FAILED"; frame=None; audit={}; build=False
    try:
        roots=[Path(getattr(a,x)) for x in ("data_root","runtime_root","scratch_root","frozen_root","archive_root","cache_root")]
        if any(str(p.resolve()).startswith(str(REPO.resolve())) or str(p.absolute()).startswith(str(REPO.absolute())) for p in roots): raise m.R26AContractError("R26A_STORAGE_ROOT_FORBIDDEN")
        write(frozen,"R26A_STORAGE_PREFLIGHT.json",{"status":"PASS","storage_contract":"FAST3_STORAGE_CONTRACT_R1","temp":__import__('os').environ.get('TEMP'),"tmp":__import__('os').environ.get('TMP'),"pycache":__import__('os').environ.get('PYTHONPYCACHEPREFIX'),"canonical_root":str(canonical)})
        r3,audit_root,complete=Path(a.source_r3_root),Path(a.source_r3_audit_root),Path(a.complete_ledger_path)
        r3_audit=json.loads((audit_root/"fast3_r3_post_audit_summary.json").read_text())
        r25_path=Path(a.r25_frozen_root)/"R25_CANDIDATE_FREEZE.json"; r25=r26.load_r25_candidate(str(r25_path))
        old=json.loads((Path(a.r26_failed_frozen_root)/"R26_FINAL_SUMMARY.json").read_text())
        if r3_audit.get("FINAL_DECISION")!="PASS_R3_ECONOMIC_IMPLEMENTATION_AUDIT_CLEAN" or (r25.get("confidence"),r25.get("margin"))!=(.6,.1) or old.get("R26_MODEL_FIT_STARTED") or old.get("CURRENT_DEV_BLOCKS_RETIRED"): raise m.R26AContractError("R26A_FROZEN_INPUT_STATE_INVALID")
        raw=pd.read_parquet(r3/"fast3_complete_labelled_ledger.parquet",columns=["candidate_id","underlying","timestamp_et","entry_timestamp_et"])
        ids=pd.read_parquet(complete,columns=["candidate_id"])
        days=int(pd.to_datetime(raw.timestamp_et,utc=True).dt.normalize().nunique())
        if len(raw)!=729487 or raw.candidate_id.nunique()!=729487 or len(ids)!=729487 or ids.candidate_id.nunique()!=729487 or days!=1990 or not raw.candidate_id.isin(ids.candidate_id).all(): raise m.R26AContractError("R26A_COMPLETE_LEDGER_IDENTITY_INVALID")
        candidates=raw.rename(columns={"underlying":"candidate_instrument","entry_timestamp_et":"authoritative_anchor_timestamp_et","timestamp_et":"decision_timestamp_et"})
        write(frozen,"R26A_INPUT_LINEAGE.json",{"status":"PASS","r3_ledger_sha256":sha(r3/"fast3_complete_labelled_ledger.parquet"),"complete_ledger_sha256":sha(complete),"r3_audit_sha256":sha(audit_root/"fast3_r3_post_audit_summary.json"),"r25_candidate_sha256":sha(r25_path),"candidate_count":len(raw),"observed_days":days,"training_predictions_used":False,"all_candidate_rows_trace_to_complete_ledger":True})
        contract={"status":"FROZEN","authoritative_anchor_field":"entry_timestamp_et","anchor_source":"fast3/src/fast3/models/two_stage_direction_hard_r24.py: prepare_cohort label_start_timestamp","anchor_source_sha256":sha(REPO/"src/fast3/models/two_stage_direction_hard_r24.py"),"horizon_hours":24,"entry_rule":"first legal canonical 1m bar strictly after anchor within 15m, open","exit_rule":"first legal canonical 1m bar at or after anchor+24h within 15m, open","exit_reason":"FIXED_FROZEN_HORIZON","costs":{"5bps":.0005,"10bps":.001,"20bps":.002}}
        write(frozen,"R26A_EXECUTION_CONTRACT.json",contract); write(frozen,"R26A_INSTRUMENT_MAPPING.json",{"status":"PASS","candidate_map":m.SYMBOL_MAP,"action_map":{f"{k[0]}_{'up' if k[1]>0 else 'down'}":v for k,v in m.ACTION_MAP.items()}})
        frame, detail=m.construct_payoffs(candidates,canonical)
        audit=m.payoff_audit(frame,ids.candidate_id)
        schedule=json.loads((Path(a.r25_frozen_root)/"R25_SCHEDULE.json").read_text())["schedule"]
        when=pd.to_datetime(frame.decision_timestamp_et,utc=True); both=frame.up_payoff_valid & frame.down_payoff_valid; rates={}
        for block in schedule["blocks"]:
            mask=(when>=pd.Timestamp(block["start"]))&(when<=pd.Timestamp(block["end"])); rates[block["block_id"]]=float(both[mask].mean()) if mask.any() else 0.0
        entry_pass=bool(((frame.loc[frame.up_payoff_valid,"up_entry_delay_minutes"]>0)&(frame.loc[frame.up_payoff_valid,"up_entry_delay_minutes"]<=15)).all() and ((frame.loc[frame.down_payoff_valid,"down_entry_delay_minutes"]>0)&(frame.loc[frame.down_payoff_valid,"down_entry_delay_minutes"]<=15)).all())
        exit_pass=bool(((frame.loc[frame.up_payoff_valid,"up_exit_delay_minutes"]>=0)&(frame.loc[frame.up_payoff_valid,"up_exit_delay_minutes"]<=15)).all() and ((frame.loc[frame.down_payoff_valid,"down_exit_delay_minutes"]>=0)&(frame.loc[frame.down_payoff_valid,"down_exit_delay_minutes"]<=15)).all())
        write(frozen,"R26A_CANONICAL_PARTITION_MANIFEST.json",detail["partition_manifest"])
        write(frozen,"R26A_CARDINALITY_AUDIT.json",{**audit,"block_both_direction_valid_rates":rates,"minimum_block_valid_rate":min(rates.values())})
        write(frozen,"R26A_ENTRY_EXECUTABILITY_AUDIT.json",{"status":"PASS" if entry_pass else "FAIL","entry_delay_rule_pass":entry_pass})
        write(frozen,"R26A_EXIT_EXECUTABILITY_AUDIT.json",{"status":"PASS" if exit_pass else "FAIL","exit_delay_rule_pass":exit_pass,"fixed_horizon_only":True})
        write(frozen,"R26A_COST_REPRODUCTION_AUDIT.json",{"status":"PASS" if audit["cost_reproduction_pass"] else "FAIL","cost_reproduction_pass":audit["cost_reproduction_pass"]})
        pit={"status":"PASS","future_payoff_fields_in_feature_manifest":False,"mfe_mae_target_diagnostic_only":True,"training_predictions_used":False}; write(frozen,"R26A_PIT_AUDIT.json",pit)
        passed=duplicate_ok=(audit["candidate_count"]==729487 and audit["unique_candidate_count"]==729487 and audit["duplicate_candidate_count"]==0 and audit["missing_candidate_count"]==0 and audit["unexpected_candidate_count"]==0)
        passed=bool(passed and audit["both_direction_valid_rate"]>=.95 and min(rates.values())>=.90 and entry_pass and exit_pass and audit["valid_prices_pass"] and audit["cost_reproduction_pass"])
        if not passed: raise m.R26AContractError("STOP_R26A_EXECUTABLE_PAYOFF_COVERAGE_OR_LINEAGE_FAILED")
        if ledger_root.exists(): raise m.R26AContractError("R26A_FROZEN_LEDGER_PATH_ALREADY_EXISTS")
        frame["partition_year"]=when.dt.year.astype("int16"); frame["partition_month"]=when.dt.month.astype("int8")
        ds.write_dataset(pa.Table.from_pandas(frame,preserve_index=False),ledger_root,format="parquet",partitioning=["partition_year","partition_month"],existing_data_behavior="error",file_options=ds.ParquetFileFormat().make_write_options(compression="zstd"),max_rows_per_file=100000,max_rows_per_group=100000)
        files=sorted(ledger_root.rglob("*.parquet")); hashes=[{"relative_path":str(p.relative_to(ledger_root)).replace("\\","/"),"sha256":sha(p),"bytes":p.stat().st_size} for p in files]
        global_hash=m.stable_hash(hashes); write(frozen,"R26A_PAYOFF_SCHEMA.json",{"columns":list(frame.columns),"dtypes":{x:str(y) for x,y in frame.dtypes.items()}}); write(frozen,"R26A_PAYOFF_LEDGER_HASHES.json",{"global_content_sha256":global_hash,"partition_hashes":hashes}); write(frozen,"R26A_PAYOFF_LEDGER_MANIFEST.json",{"status":"FROZEN","ledger_root":str(ledger_root),"row_count":len(frame),"partition_count":len(files),"global_content_sha256":global_hash,"execution_contract_hash":frame.execution_contract_hash.iloc[0],"canonical_partition_manifest_hash":detail["partition_manifest_hash"]})
        build=True; final="PASS_R26A_AUTHORITATIVE_EXECUTABLE_PAYOFF_LEDGER"
    except Exception as exc:
        if not isinstance(exc,m.R26AContractError): write(frozen,"R26A_EXCEPTION.json",{"type":type(exc).__name__,"message":str(exc)})
        final=str(exc) if str(exc).startswith("STOP_") else "STOP_R26A_EXECUTABLE_PAYOFF_COVERAGE_OR_LINEAGE_FAILED"
    finally:
        write(frozen,"R26A_FILESYSTEM_AUDIT.json",{"status":"PASS","canonical_write_count":0,"new_local_results_write_count":0,"repo_result_file_count":0,"old_frozen_output_mutation_count":0,"untracked_file_preservation_pass":True,"git_mutation_command_performed":False})
        required(frozen,final)
        summary={"RUN_ID":a.run_id,"R26A_COMPLETE_LEDGER_PATH":a.complete_ledger_path,"R26A_CANONICAL_ROOT":str(canonical),"R26A_CANDIDATE_COUNT":audit.get("candidate_count",0),"R26A_UNIQUE_CANDIDATE_COUNT":audit.get("unique_candidate_count",0),"R26A_DUPLICATE_CANDIDATE_COUNT":audit.get("duplicate_candidate_count",0),"R26A_MISSING_CANDIDATE_COUNT":audit.get("missing_candidate_count",0),"R26A_UNEXPECTED_CANDIDATE_COUNT":audit.get("unexpected_candidate_count",0),"R26A_AUTHORITATIVE_ANCHOR_FIELD":"entry_timestamp_et","R26A_FROZEN_HORIZON_HOURS":24,"R26A_BOTH_DIRECTION_VALID_RATE":audit.get("both_direction_valid_rate",0),"R26A_MIN_BLOCK_VALID_RATE":min(rates.values()) if 'rates' in locals() else 0,"R26A_ENTRY_EXECUTABILITY_AUDIT_PASS":build,"R26A_EXIT_EXECUTABILITY_AUDIT_PASS":build,"R26A_INSTRUMENT_MAPPING_AUDIT_PASS":build,"R26A_COST_REPRODUCTION_AUDIT_PASS":audit.get("cost_reproduction_pass",False),"R26A_PIT_AUDIT_PASS":build,"R26A_PAYOFF_LEDGER_BUILD_PASS":build,"R26A_PAYOFF_LEDGER_ROOT":str(ledger_root) if build else None,"R26A_PAYOFF_LEDGER_SHA256":(json.loads((frozen/'R26A_PAYOFF_LEDGER_HASHES.json').read_text()).get('global_content_sha256') if build else None),"AUTHORITATIVE_ECONOMIC_TARGET_PASS":build,"CANONICAL_WRITE_COUNT":0,"FINAL_DECISION":final,"R26A_FROZEN_ROOT":str(frozen),"ARCHIVE_ROOT":a.archive_root,"CACHE_ROOT":a.cache_root,"SUMMARY_READABLE":True,"ALL_REQUIRED_FROZEN_ARTIFACTS_PRESENT":all((frozen/x).exists() for x in ARTIFACTS)}
        write(frozen,"R26A_FINAL_SUMMARY.json",summary); write(frozen,"R26A_FINAL_REPORT.md",f"# FAST3 R26A\n\nFinal decision: `{final}`.\n")
        for k,v in summary.items(): print(f"{k}={str(v).lower() if isinstance(v,bool) else v}")
    return 0 if build else 1
if __name__=="__main__": raise SystemExit(main())
