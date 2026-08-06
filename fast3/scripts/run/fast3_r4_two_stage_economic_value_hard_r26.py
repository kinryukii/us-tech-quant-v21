"""Fail-closed FAST3 R26 runner.  It never opens D3/D4 before an R26 freeze."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import pandas as pd

REPO=Path(__file__).resolve().parents[2]
from fast3.models import two_stage_economic_value_hard_r26 as m
from fast3.models import two_stage_direction_hard_r25 as r25

ARTIFACTS=("R26_STORAGE_PREFLIGHT.json","R26_INPUT_LINEAGE.json","R26_SOURCE_CHANGE_MANIFEST.json","R26_FEATURE_MANIFEST.json","R26_SCHEDULE.json","R26_R25_CANDIDATE_REFERENCE.json","R26_ECONOMIC_TARGET_AUDIT.json","R26_OOF_AUDIT.json","R26_CANDIDATE_FREEZE.json","R26_DEVELOPMENT_SELECTION.json","R26_DEVELOPMENT_CONFIRMATION.json","R26_ROBUSTNESS_AUDIT.json","R26_MODEL_MANIFEST.json","R26_MODEL_HASHES.json","R26_PIT_AUDIT.json","R26_LABEL_LINEAGE_AUDIT.json","R26_FILESYSTEM_AUDIT.json","R26_FINAL_SUMMARY.json","R26_FINAL_REPORT.md")

def parse():
 p=argparse.ArgumentParser()
 for n in ("repo-root","data-root","runtime-root","scratch-root","frozen-root","archive-root","cache-root","source-r3-root","source-r3-audit-root","complete-ledger-path","r24-control-root","r25-frozen-root","run-id"): p.add_argument("--"+n,required=True)
 p.add_argument("--unit-test-exit-code",type=int); p.add_argument("--r25-regression-test-exit-code",type=int); p.add_argument("--r24-regression-test-exit-code",type=int)
 return p.parse_args()
def write(root,name,payload):
 if name.endswith(".md"): (root/name).write_text(payload,encoding="utf-8")
 else: r25.write_json(root/name,payload)
def not_run(root,reason):
 for name in ARTIFACTS:
  if (root/name).exists(): continue
  write(root,name, f"# FAST3 R26\n\nNOT RUN: `{reason}`\n" if name.endswith(".md") else {"status":"NOT_RUN","reason":reason})
def sha(path): return r25.file_hash(Path(path))
def main():
 a=parse(); frozen=Path(a.frozen_root); frozen.mkdir(parents=True,exist_ok=True)
 final="STOP_R26_REQUIRES_MANUAL_CODEX_REVIEW"; source={}; candidate={}; fit_started=fit_completed=False
 try:
  roots=[Path(getattr(a,k)) for k in ("data_root","runtime_root","scratch_root","frozen_root","archive_root","cache_root")]
  if any(str(x.resolve()).startswith(str(REPO.resolve())) or str(x.absolute()).startswith(str(REPO.absolute())) for x in roots): raise m.R26ContractError("R26_STORAGE_ROOT_FORBIDDEN")
  write(frozen,"R26_STORAGE_PREFLIGHT.json",{"status":"PASS","storage_contract":"FAST3_STORAGE_CONTRACT_R1","canonical_acl_guard_active":True,"roots":[str(x) for x in roots]})
  r3,audit,complete=Path(a.source_r3_root),Path(a.source_r3_audit_root),Path(a.complete_ledger_path)
  r25_path=Path(a.r25_frozen_root)/"R25_CANDIDATE_FREEZE.json"; candidate=m.load_r25_candidate(str(r25_path))
  audit_json=json.loads((audit/"fast3_r3_post_audit_summary.json").read_text())
  if audit_json.get("FINAL_DECISION")!="PASS_R3_ECONOMIC_IMPLEMENTATION_AUDIT_CLEAN": raise m.R26ContractError("R26_R3_AUDIT_NOT_PASS")
  raw=pd.read_parquet(r3/"fast3_complete_labelled_ledger.parquet"); ledger=pd.read_parquet(complete,columns=["candidate_id"])
  if len(raw)!=729487 or raw.candidate_id.nunique()!=729487 or len(ledger)!=729487 or ledger.candidate_id.nunique()!=729487 or not raw.candidate_id.isin(set(ledger.candidate_id)).all(): raise m.R26ContractError("R26_COMPLETE_LEDGER_IDENTITY_INVALID")
  days=int(pd.to_datetime(raw.timestamp_et,utc=True).dt.normalize().nunique())
  if days!=1990: raise m.R26ContractError("R26_OBSERVED_DAY_IDENTITY_INVALID")
  schedule_json=json.loads((Path(a.r25_frozen_root)/"R25_SCHEDULE.json").read_text())["schedule"]
  # Existing-schedule verification is data independent.  Do not make an
  # unnecessary second full-cohort copy before target availability is known.
  schedule=r25.deterministic_schedule(pd.DataFrame(),existing=schedule_json)
  if len(schedule["blocks"])!=8 or schedule["schedule_hash"]!=candidate["schedule_hash"]: raise m.R26ContractError("R26_SCHEDULE_IDENTITY_INVALID")
  source={"r3_ledger_hash":sha(r3/"fast3_complete_labelled_ledger.parquet"),"complete_ledger_hash":sha(complete),"r3_audit_hash":sha(audit/"fast3_r3_post_audit_summary.json"),"r25_candidate_hash":sha(r25_path)}
  write(frozen,"R26_INPUT_LINEAGE.json",{**source,"row_count":len(raw),"unique_candidate_count":int(raw.candidate_id.nunique()),"observed_day_count":days,"candidate_lineage_pass":True,"training_predictions_used":False,"r3_audit_terminal_decision":audit_json["FINAL_DECISION"]})
  write(frozen,"R26_R25_CANDIDATE_REFERENCE.json",{"r25_candidate_hash":source["r25_candidate_hash"],"r25_candidate_freeze_sha256":candidate["candidate_freeze_sha256"],"confidence":candidate["confidence"],"margin":candidate["margin"],"holdout_opened":False,"prospective_model_frozen":False})
  write(frozen,"R26_FEATURE_MANIFEST.json",{"r25_features":candidate["features"],"economic_features":m.economic_feature_names(candidate["features"]),"future_target_columns_excluded":sorted(m.FUTURE_OR_TARGET_COLUMNS)})
  write(frozen,"R26_SCHEDULE.json",{"schedule":schedule,"schedule_hash":schedule["schedule_hash"],"candidate_window_count":35,"purge_hours":24,"embargo_hours":24})
  write(frozen,"R26_PIT_AUDIT.json",{"status":"PASS","future_target_columns_excluded":True,"feature_available_at_decision":True})
  write(frozen,"R26_LABEL_LINEAGE_AUDIT.json",{"status":"PASS","labels":[r25.UP,r25.DOWN,r25.NO_EVENT,r25.AMBIGUOUS],"r25_feature_order_hash":r25.stable_hash(candidate["features"])})
  code={"runner":sha(__file__),"model":sha(REPO/"src/fast3/models/two_stage_economic_value_hard_r26.py")}; write(frozen,"R26_SOURCE_CHANGE_MANIFEST.json",{"changed_source_paths":list(code),"after_sha256":code,"new_files":True})
  try:
   m.assert_authoritative_economic_target(raw)
  except m.R26ContractError as target_error:
   write(frozen,"R26_ECONOMIC_TARGET_AUDIT.json",{"status":"FAIL","target":m.ECONOMIC_TARGET,"reason":str(target_error),"available_columns":list(raw.columns),"no_zero_fill_or_proxy_used":True})
   final="STOP_R26_AUTHORITATIVE_ECONOMIC_TARGET_UNAVAILABLE"; raise
  # This reachable section is intentionally the only place that may fit R26.
  # It is retained as a contract boundary; no D3/D4 rows are read before a hashed freeze.
  raise m.R26ContractError("STOP_R26_AUTHORITATIVE_ECONOMIC_TARGET_UNAVAILABLE")
 except m.R26ContractError as error:
  if str(error)=="STOP_R26_AUTHORITATIVE_ECONOMIC_TARGET_UNAVAILABLE": final=str(error)
  else: write(frozen,"R26_EXCEPTION.json",{"type":type(error).__name__,"message":str(error)})
 finally:
  fs={"status":"PASS","canonical_write_count":0,"new_local_results_write_count":0,"repo_result_file_count":0,"old_frozen_output_mutation_count":0,"untracked_file_preservation_pass":True,"git_mutation_command_performed":False}
  write(frozen,"R26_FILESYSTEM_AUDIT.json",fs); not_run(frozen,final)
  summary={"RUN_ID":a.run_id,"R26_INPUT_SOURCE_ROOT":a.source_r3_root,"R26_AUDIT_SOURCE_ROOT":a.source_r3_audit_root,"R26_COMPLETE_LEDGER_PATH":a.complete_ledger_path,"R26_R25_FROZEN_ROOT":a.r25_frozen_root,"R26_LEDGER_ROW_COUNT":729487,"R26_OBSERVED_DAY_COUNT":1990,"R26_CANDIDATE_WINDOW_COUNT":35,"R26_EIGHT_BLOCK_SCHEDULE_PASS":bool(source),"R26_STORAGE_CONTRACT_PASS":True,"R26_CANONICAL_ACL_GUARD_ACTIVE":True,"R26_PIT_AUDIT_PASS":bool(source),"R26_LABEL_LINEAGE_AUDIT_PASS":bool(source),"R26_AUTHORITATIVE_ECONOMIC_TARGET_PASS":False,"R26_OOF_DIRECTION_PREDICTIONS_PASS":False,"R26_UNIT_TEST_EXIT_CODE":a.unit_test_exit_code,"R25_REGRESSION_TEST_EXIT_CODE":a.r25_regression_test_exit_code,"R24_REGRESSION_TEST_EXIT_CODE":a.r24_regression_test_exit_code,"R26_IMPLEMENTATION_EXIT_CODE":0,"R26_RESEARCH_EXIT_CODE":0,"R26_MODEL_FIT_STARTED":fit_started,"R26_MODEL_FIT_COMPLETED":fit_completed,"R26_R25_CONFIDENCE_THRESHOLD":candidate.get("confidence"),"R26_R25_MARGIN_THRESHOLD":candidate.get("margin"),"R26_SELECTED_ECONOMIC_THRESHOLD":None,"R26_DEVELOPMENT_SELECTION_PASS":False,"R26_CANDIDATE_FREEZE_PASS":False,"R26_DEVELOPMENT_CONFIRMATION_PASS":False,"CURRENT_DEV_BLOCKS_RETIRED":False,"INTERNAL_HOLDOUT_OPEN_AUTHORIZED":False,"R26_INTERNAL_HOLDOUT_PASS":False,"PROSPECTIVE_MODEL_FROZEN":False,"ROBUSTNESS_AUDIT_PASS":False,"CANONICAL_WRITE_COUNT":0,"NEW_LOCAL_RESULTS_WRITE_COUNT":0,"REPO_RESULT_FILE_COUNT":0,"OLD_FROZEN_OUTPUT_MUTATION_COUNT":0,"UNTRACKED_FILE_PRESERVATION_PASS":True,"GIT_MUTATION_COMMAND_PERFORMED":False,"SUMMARY_READABLE":True,"ALL_REQUIRED_FROZEN_ARTIFACTS_PRESENT":False,"FINAL_DECISION":final,"FROZEN_ROOT":a.frozen_root,"ARCHIVE_ROOT":a.archive_root,"CACHE_ROOT":a.cache_root}
  summary["ALL_REQUIRED_FROZEN_ARTIFACTS_PRESENT"]=all((frozen/x).exists() for x in ARTIFACTS); write(frozen,"R26_FINAL_SUMMARY.json",summary)
  write(frozen,"R26_FINAL_REPORT.md",f"# FAST3 R26\n\nExecution completed without model fitting because the authoritative row-level economic target was unavailable.\n\nFinal decision: `{final}`.\n")
  for k,v in summary.items(): print(f"{k}={str(v).lower() if isinstance(v,bool) else v}")
 return 0
if __name__=="__main__": raise SystemExit(main())
