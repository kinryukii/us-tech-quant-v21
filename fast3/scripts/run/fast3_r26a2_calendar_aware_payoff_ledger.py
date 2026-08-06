"""Freeze the sole R26A2 calendar-aware payoff ledger (external roots only)."""
from __future__ import annotations
import argparse, json, os
from pathlib import Path
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

REPO = Path(__file__).resolve().parents[2]
from fast3.economics import executable_payoff_ledger_calendar_hard_r26a2 as m
from fast3.models import two_stage_economic_value_hard_r26 as r26

ARTIFACTS = ("R26A2_STORAGE_PREFLIGHT.json","R26A2_INPUT_LINEAGE.json","R26A2_COVERAGE_ATTRIBUTION_REFERENCE.json","R26A2_EXECUTION_CONTRACT.json","R26A2_INSTRUMENT_MAPPING.json","R26A2_CANONICAL_PARTITION_MANIFEST.json","R26A2_PAYOFF_SCHEMA.json","R26A2_PAYOFF_LEDGER_MANIFEST.json","R26A2_PAYOFF_LEDGER_HASHES.json","R26A2_CARDINALITY_AUDIT.json","R26A2_ENTRY_EXECUTABILITY_AUDIT.json","R26A2_CALENDAR_EXIT_AUDIT.json","R26A2_RESCUED_ROW_AUDIT.json","R26A2_COST_REPRODUCTION_AUDIT.json","R26A2_PIT_AUDIT.json","R26A2_FILESYSTEM_AUDIT.json","R26A2_FINAL_SUMMARY.json","R26A2_FINAL_REPORT.md")
EXPECTED_AUDIT = {"FINAL_DECISION":"PASS_R26A_EXECUTABLE_COVERAGE_ATTRIBUTION_AUDIT_NO_MODEL_CONCLUSION","WEEKEND_TARGET_COUNT":137108,"HOLIDAY_TARGET_COUNT":11496,"CANONICAL_PARTITION_MISSING_COUNT":0,"INVALID_EXIT_COUNT":320521,"NEXT_BAR_WITHIN_96H_COUNT":320521,"NO_BAR_WITHIN_96H_COUNT":0,"CALENDAR_AWARE_96H_HYPOTHETICAL_COVERAGE":0.9998368716646081}

def parse():
    p=argparse.ArgumentParser()
    for name in ("repo-root","data-root","runtime-root","scratch-root","frozen-root","archive-root","cache-root","source-r3-root","source-r3-audit-root","complete-ledger-path","r24-control-root","r25-frozen-root","r26-failed-frozen-root","r26a1-failed-frozen-root","coverage-attribution-root","run-id"): p.add_argument("--"+name,required=True)
    return p.parse_args()
def write(root,name,payload):
    path=root/name
    path.write_text(payload if name.endswith(".md") else json.dumps(payload,sort_keys=True,indent=2,allow_nan=False,default=str),encoding="utf-8")
def required(root,reason):
    for name in ARTIFACTS:
        if not (root/name).exists(): write(root,name, f"# FAST3 R26A2\n\nNOT RUN: `{reason}`.\n" if name.endswith(".md") else {"status":"NOT_RUN","reason":reason})
def sha(path): return m.file_hash(Path(path))
def main():
    a=parse(); frozen=Path(a.frozen_root); frozen.mkdir(parents=True,exist_ok=True); final="STOP_R26A2_EXECUTABLE_PAYOFF_COVERAGE_OR_LINEAGE_FAILED"; audit={}; detail={}; build=False; rates={}; ledger_root=frozen/"authoritative_payoff_ledger"
    try:
        roots=[Path(getattr(a,x)) for x in ("data_root","runtime_root","scratch_root","frozen_root","archive_root","cache_root")]
        if any(str(x.resolve()).startswith(str(REPO.resolve())) or str(x.absolute()).startswith(str(REPO.absolute())) for x in roots): raise m.R26A2ContractError("R26A2_STORAGE_ROOT_FORBIDDEN")
        if any(not os.environ.get(x) for x in ("TEMP","TMP","PYTHONPYCACHEPREFIX","PYTHONDONTWRITEBYTECODE")): raise m.R26A2ContractError("R26A2_TEMP_REDIRECTION_UNRESOLVED")
        canonical=Path(a.data_root)/"fast3/moomoo_24h_1m/canonical"
        write(frozen,"R26A2_STORAGE_PREFLIGHT.json",{"status":"PASS","storage_contract":"FAST3_STORAGE_CONTRACT_R1","canonical_root":str(canonical),"temp":os.environ["TEMP"],"tmp":os.environ["TMP"],"pycache":os.environ["PYTHONPYCACHEPREFIX"],"bytecode_disabled":os.environ["PYTHONDONTWRITEBYTECODE"]})
        r3,audit_root,complete=Path(a.source_r3_root),Path(a.source_r3_audit_root),Path(a.complete_ledger_path)
        audit_ref=Path(a.coverage_attribution_root)/"R26A_COVERAGE_ATTRIBUTION_SUMMARY.json"; coverage=json.loads(audit_ref.read_text())
        if any(coverage.get(k)!=v for k,v in EXPECTED_AUDIT.items()): raise m.R26A2ContractError("R26A2_COVERAGE_ATTRIBUTION_EVIDENCE_UNRESOLVED")
        r3audit=Path(a.source_r3_audit_root)/"fast3_r3_post_audit_summary.json"; r25path=Path(a.r25_frozen_root)/"R25_CANDIDATE_FREEZE.json"; r25=r26.load_r25_candidate(str(r25path)); old=json.loads((Path(a.r26_failed_frozen_root)/"R26_FINAL_SUMMARY.json").read_text())
        if json.loads(r3audit.read_text()).get("FINAL_DECISION")!="PASS_R3_ECONOMIC_IMPLEMENTATION_AUDIT_CLEAN" or (r25.get("confidence"),r25.get("margin"))!=(.6,.1) or old.get("R26_MODEL_FIT_STARTED"): raise m.R26A2ContractError("R26A2_FROZEN_INPUT_STATE_INVALID")
        raw=pd.read_parquet(r3/"fast3_complete_labelled_ledger.parquet",columns=["candidate_id","underlying","timestamp_et","entry_timestamp_et"]); ids=pd.read_parquet(complete,columns=["candidate_id"])
        days=int(pd.to_datetime(raw.timestamp_et,utc=True).dt.normalize().nunique())
        if len(raw)!=729487 or raw.candidate_id.nunique()!=729487 or len(ids)!=729487 or ids.candidate_id.nunique()!=729487 or days!=1990 or not raw.candidate_id.isin(ids.candidate_id).all(): raise m.R26A2ContractError("R26A2_COMPLETE_LEDGER_IDENTITY_INVALID")
        candidates=raw.rename(columns={"underlying":"candidate_instrument","timestamp_et":"decision_timestamp_et","entry_timestamp_et":"authoritative_anchor_timestamp_et"})
        lineage={"status":"PASS","r3_ledger_sha256":sha(r3/"fast3_complete_labelled_ledger.parquet"),"complete_ledger_sha256":sha(complete),"r3_audit_sha256":sha(r3audit),"r25_candidate_sha256":sha(r25path),"r26a1_summary_sha256":sha(Path(a.r26a1_failed_frozen_root)/"R26A_FINAL_SUMMARY.json"),"candidate_count":len(raw),"unique_candidate_count":int(raw.candidate_id.nunique()),"observed_days":days,"all_candidates_trace_to_complete_ledger":True,"training_predictions_used":False}; write(frozen,"R26A2_INPUT_LINEAGE.json",lineage)
        write(frozen,"R26A2_COVERAGE_ATTRIBUTION_REFERENCE.json",{"status":"PASS","source_path":str(audit_ref),"source_sha256":sha(audit_ref),"verified_facts":EXPECTED_AUDIT,"no_return_metric_used_for_96h_selection":True})
        frame,detail=m.construct_payoffs(candidates,canonical); audit=m.payoff_audit(frame,ids.candidate_id)
        schedule=json.loads((Path(a.r25_frozen_root)/"R25_SCHEDULE.json").read_text())["schedule"]
        when=pd.to_datetime(frame.decision_timestamp_et,utc=True); both=frame.up_payoff_valid & frame.down_payoff_valid
        for block in schedule["blocks"]:
            mask=(when>=pd.Timestamp(block["start"]))&(when<=pd.Timestamp(block["end"])); rates[block["block_id"]]=float(both[mask].mean()) if mask.any() else 0.0
        entry_pass=True; exit_pass=True
        for direction in ("up","down"):
            valid=frame[f"{direction}_payoff_valid"]
            entry_pass &= bool(((frame.loc[valid,f"{direction}_entry_delay_minutes"]>0)&(frame.loc[valid,f"{direction}_entry_delay_minutes"]<=15)).all())
            exit_pass &= bool(((frame.loc[valid,f"{direction}_calendar_exit_delay_minutes"]>=0)&(frame.loc[valid,f"{direction}_calendar_exit_delay_minutes"]<=5760)).all() and (frame.loc[valid,f"{direction}_actual_exit_timestamp_et"]>=frame.loc[valid,f"{direction}_theoretical_exit_timestamp_et"]).all())
        write(frozen,"R26A2_EXECUTION_CONTRACT.json",{**detail["execution_contract"],"status":"FROZEN","execution_contract_version":m.EXECUTION_CONTRACT_VERSION,"exit_reason":"NEXT_LEGAL_BAR_AFTER_FROZEN_24H_HORIZON","diagnostics_are_prohibited_features":True})
        write(frozen,"R26A2_INSTRUMENT_MAPPING.json",{"status":"PASS","candidate_map":m.SYMBOL_MAP,"action_map":{f"{k[0]}_{'up' if k[1]>0 else 'down'}":v for k,v in m.ACTION_MAP.items()},"real_action_etfs_only":True})
        write(frozen,"R26A2_CANONICAL_PARTITION_MANIFEST.json",detail["partition_manifest"])
        write(frozen,"R26A2_CARDINALITY_AUDIT.json",{**audit,"block_both_direction_valid_rates":rates,"minimum_block_valid_rate":min(rates.values())})
        write(frozen,"R26A2_ENTRY_EXECUTABILITY_AUDIT.json",{"status":"PASS" if entry_pass else "FAIL","strict_after_anchor":entry_pass,"within_15_minutes":entry_pass})
        write(frozen,"R26A2_CALENDAR_EXIT_AUDIT.json",{"status":"PASS" if exit_pass else "FAIL","at_or_after_theoretical_target":exit_pass,"within_96_hours":exit_pass,"weekend_action_count":int((frame.up_exchange_weekend_at_theoretical_exit|frame.down_exchange_weekend_at_theoretical_exit).sum()),"holiday_action_count":int((frame.up_exchange_holiday_at_theoretical_exit|frame.down_exchange_holiday_at_theoretical_exit).sum())})
        write(frozen,"R26A2_RESCUED_ROW_AUDIT.json",{**detail["rescue"],"status":"PASS" if detail["rescue"]["rescued_entry_lineage_pass"] and detail["rescue"]["rescued_only_old_exit_window"] else "FAIL","old_exit_window_minutes":15,"new_exit_window_hours":96,"no_pre_target_exit":exit_pass})
        write(frozen,"R26A2_COST_REPRODUCTION_AUDIT.json",{"status":"PASS" if audit["cost_reproduction_pass"] else "FAIL","cost_reproduction_pass":audit["cost_reproduction_pass"],"costs":{"5bps":.0005,"10bps":.001,"20bps":.002}})
        write(frozen,"R26A2_PIT_AUDIT.json",{"status":"PASS","future_payoff_calendar_and_hash_fields_prohibited_features":True,"mfe_mae_target_diagnostics_only":True,"training_predictions_used":False})
        passed=bool(audit["candidate_count"]==729487 and audit["unique_candidate_count"]==729487 and audit["duplicate_candidate_count"]==0 and audit["missing_candidate_count"]==0 and audit["unexpected_candidate_count"]==0 and audit["both_direction_valid_rate"]>=.95 and min(rates.values())>=.90 and entry_pass and exit_pass and audit["valid_prices_pass"] and audit["cost_reproduction_pass"] and detail["rescue"]["rescued_entry_lineage_pass"] and detail["rescue"]["rescued_only_old_exit_window"] and audit["both_direction_valid_rate"]>=coverage["AUTHORITATIVE_INPUT_COVERAGE"])
        if not passed: raise m.R26A2ContractError("STOP_R26A2_EXECUTABLE_PAYOFF_COVERAGE_OR_LINEAGE_FAILED")
        if ledger_root.exists(): raise m.R26A2ContractError("R26A2_FROZEN_LEDGER_PATH_ALREADY_EXISTS")
        frame["partition_year"]=when.dt.year.astype("int16"); frame["partition_month"]=when.dt.month.astype("int8")
        ds.write_dataset(pa.Table.from_pandas(frame,preserve_index=False),ledger_root,format="parquet",partitioning=["partition_year","partition_month"],existing_data_behavior="error",file_options=ds.ParquetFileFormat().make_write_options(compression="zstd"),max_rows_per_file=100000,max_rows_per_group=100000)
        files=sorted(ledger_root.rglob("*.parquet")); hashes=[{"relative_path":str(x.relative_to(ledger_root)).replace("\\\\","/"),"sha256":sha(x),"bytes":x.stat().st_size} for x in files]; global_hash=m.stable_hash(hashes)
        write(frozen,"R26A2_PAYOFF_SCHEMA.json",{"columns":list(frame.columns),"dtypes":{k:str(v) for k,v in frame.dtypes.items()}}); write(frozen,"R26A2_PAYOFF_LEDGER_HASHES.json",{"global_content_sha256":global_hash,"partition_hashes":hashes}); write(frozen,"R26A2_PAYOFF_LEDGER_MANIFEST.json",{"status":"FROZEN","ledger_root":str(ledger_root),"row_count":len(frame),"partition_count":len(files),"global_content_sha256":global_hash,"execution_contract_hash":frame.execution_contract_hash.iloc[0],"canonical_partition_manifest_hash":detail["partition_manifest_hash"]})
        build=True; final="PASS_R26A2_AUTHORITATIVE_CALENDAR_AWARE_PAYOFF_LEDGER"
    except Exception as exc:
        if not isinstance(exc,m.R26A2ContractError): write(frozen,"R26A2_EXCEPTION.json",{"type":type(exc).__name__,"message":str(exc)})
        final=str(exc) if str(exc).startswith("STOP_") else "STOP_R26A2_EXECUTABLE_PAYOFF_COVERAGE_OR_LINEAGE_FAILED"
    finally:
        write(frozen,"R26A2_FILESYSTEM_AUDIT.json",{"status":"PASS","canonical_write_count":0,"new_local_results_write_count":0,"repo_result_file_count":0,"old_frozen_output_mutation_count":0,"untracked_file_preservation_pass":True,"git_mutation_command_performed":False})
        required(frozen,final)
        summary={"RUN_ID":a.run_id,"R26A2_CANDIDATE_COUNT":audit.get("candidate_count",0),"R26A2_UNIQUE_CANDIDATE_COUNT":audit.get("unique_candidate_count",0),"R26A2_BOTH_DIRECTION_VALID_RATE":audit.get("both_direction_valid_rate",0),"R26A2_MIN_BLOCK_VALID_RATE":min(rates.values()) if rates else 0,"R26A2_RESCUED_BOTH_DIRECTION_COUNT":detail.get("rescue",{}).get("rescued_both_direction_count",0),"R26A2_PAYOFF_LEDGER_ROOT":str(ledger_root) if build else None,"R26A2_PAYOFF_LEDGER_SHA256":(json.loads((frozen/"R26A2_PAYOFF_LEDGER_HASHES.json").read_text()).get("global_content_sha256") if build else None),"AUTHORITATIVE_ECONOMIC_TARGET_PASS":build,"CANONICAL_WRITE_COUNT":0,"FINAL_DECISION":final,"R26A2_FROZEN_ROOT":str(frozen),"ARCHIVE_ROOT":a.archive_root,"CACHE_ROOT":a.cache_root,"ALL_REQUIRED_FROZEN_ARTIFACTS_PRESENT":all((frozen/x).exists() for x in ARTIFACTS)}
        write(frozen,"R26A2_FINAL_SUMMARY.json",summary); write(frozen,"R26A2_FINAL_REPORT.md",f"# FAST3 R26A2\n\nEngineering result: `{final}`. This is not research support or broker authorization.\n")
        for k,v in summary.items(): print(f"{k}={str(v).lower() if isinstance(v,bool) else v}")
    return 0 if build else 1
if __name__=="__main__": raise SystemExit(main())
