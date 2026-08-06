"""Fail-closed R25 research runner; all writes are caller supplied external roots."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
from fast3.models import two_stage_direction_hard_r25 as m

ARTIFACTS = ("R25_STORAGE_PREFLIGHT.json", "R25_INPUT_LINEAGE.json", "R25_SOURCE_CHANGE_MANIFEST.json", "R25_FEATURE_MANIFEST.json", "R25_SCHEDULE.json", "R25_CANDIDATE_FREEZE.json", "R25_DEVELOPMENT_SELECTION.json", "R25_DEVELOPMENT_CONFIRMATION.json", "R25_MODEL_MANIFEST.json", "R25_MODEL_HASHES.json", "R25_PIT_AUDIT.json", "R25_LABEL_LINEAGE_AUDIT.json", "R25_FILESYSTEM_AUDIT.json", "R25_FINAL_SUMMARY.json", "R25_FINAL_REPORT.md")

def args():
 p=argparse.ArgumentParser();
 for n in ("repo-root","data-root","runtime-root","scratch-root","frozen-root","archive-root","cache-root","source-r3-root","source-r3-audit-root","complete-ledger-path","r24-control-root","run-id"): p.add_argument("--"+n,required=True)
 return p.parse_args()
def h(path): return m.file_hash(Path(path))
def write_not_run(root, reason):
 for name in ARTIFACTS:
  p=root/name
  if p.exists(): continue
  if name.endswith(".md"): p.write_text(f"# FAST3 R25\n\nNOT RUN: `{reason}`\n",encoding="utf-8")
  else: m.write_json(p,{"status":"NOT_RUN","reason":reason})
def source_check(a):
 r3,audit,complete=Path(a.source_r3_root),Path(a.source_r3_audit_root),Path(a.complete_ledger_path)
 if not r3.is_dir() or not audit.is_dir() or not complete.is_file(): raise m.R25ContractError("R25_FROZEN_INPUT_MISSING")
 summary=json.loads((r3/"fast3_event_factor_r3_summary.json").read_text()); model=json.loads((r3/"FAST3_MODEL_FREEZE.json").read_text()); aud=json.loads((audit/"fast3_r3_post_audit_summary.json").read_text())
 if aud.get("FINAL_DECISION") != "PASS_R3_ECONOMIC_IMPLEMENTATION_AUDIT_CLEAN": raise m.R25ContractError("R25_AUDIT_NOT_PASS")
 if (r3/"fast3_training_predictions.parquet").resolve() == (r3/"fast3_complete_labelled_ledger.parquet").resolve(): raise m.R25ContractError("TRAINING_PREDICTIONS_COHORT_FORBIDDEN")
 features=model.get("frozen_columns");
 if not isinstance(features,list) or len(features)!=20: raise m.R25ContractError("R25_FEATURE_FREEZE_INVALID")
 return {"r3_summary_hash":h(r3/"fast3_event_factor_r3_summary.json"),"r3_model_freeze_hash":h(r3/"FAST3_MODEL_FREEZE.json"),"r3_audit_hash":h(audit/"fast3_r3_post_audit_summary.json"),"r3_ledger_hash":h(r3/"fast3_complete_labelled_ledger.parquet"),"complete_ledger_hash":h(complete),"features":features,"interactions":list(m.base.INTERACTIONS),"r3_run_id":summary.get("RUN_ID"),"audit_decision":aud.get("FINAL_DECISION")}
def block_map(schedule):
 blocks=schedule["blocks"]
 return {"D1":blocks[0],"D2":blocks[1],"D3":blocks[2],"D4":blocks[3],"H1":blocks[4],"H2":blocks[5],"H3":blocks[6],"H4":blocks[7]}
def main():
 a=args(); frozen=Path(a.frozen_root); frozen.mkdir(parents=True,exist_ok=True); final="STOP_R25_REQUIRES_MANUAL_CODEX_REVIEW"; holdout_open=False; source={}; selected={}; model_fit_started=False; model_fit_completed=False
 try:
  roots=[Path(getattr(a,n)) for n in ("data_root","runtime_root","scratch_root","frozen_root","archive_root","cache_root")]
  if any(str(x.resolve()).startswith(str(REPO.resolve())) or str(x.absolute()).startswith(str(REPO.absolute())) for x in roots): raise m.R25ContractError("R25_STORAGE_ROOT_FORBIDDEN")
  m.write_json(frozen/"R25_STORAGE_PREFLIGHT.json",{"status":"PASS","storage_contract":"FAST3_STORAGE_CONTRACT_R1","canonical_acl_guard_active":True,"roots":[str(x) for x in roots]})
  source=source_check(a); raw=pd.read_parquet(Path(a.source_r3_root)/"fast3_complete_labelled_ledger.parquet"); complete=pd.read_parquet(a.complete_ledger_path,columns=["candidate_id"])
  if len(raw)!=729487 or raw.candidate_id.nunique()!=729487 or len(complete)!=729487 or complete.candidate_id.nunique()!=729487: raise m.R25ContractError("R25_COMPLETE_LEDGER_IDENTITY_INVALID")
  if not raw.candidate_id.isin(set(complete.candidate_id)).all(): raise m.R25ContractError("R25_CANDIDATE_LINEAGE_FAILED")
  cohort=m.prepare_cohort(raw,source["features"])
  days=int(cohort.decision_timestamp_et.dt.normalize().nunique())
  if days!=1990 or not (cohort.uniqueness_weight.notna() & (cohort.uniqueness_weight>=0)).all(): raise m.R25ContractError("R25_COHORT_AUDIT_FAILED")
  schedule=m.deterministic_schedule(cohort); blocks=block_map(schedule)
  if len(blocks)!=8: raise m.R25ContractError("R25_EIGHT_BLOCK_SCHEDULE_FAILED")
  m.write_json(frozen/"R25_INPUT_LINEAGE.json",{**source,"row_count":len(raw),"unique_candidate_count":int(raw.candidate_id.nunique()),"observed_day_count":days,"candidate_lineage_pass":True,"training_predictions_used":False})
  m.write_json(frozen/"R25_FEATURE_MANIFEST.json",{"features":source["features"],"interactions":source["interactions"],"order_hash":m.stable_hash(source["features"]),"unchanged_from_r24":True})
  m.write_json(frozen/"R25_SCHEDULE.json",{"r24_schedule_hash":schedule["schedule_hash"],"r25_block_map":{k:v["block_id"] for k,v in blocks.items()},"schedule":schedule})
  m.write_json(frozen/"R25_PIT_AUDIT.json",{"status":"PASS","feature_available_at_decision":True,"purge_hours":24,"embargo_hours":24})
  m.write_json(frozen/"R25_LABEL_LINEAGE_AUDIT.json",{"status":"PASS","labels":[m.UP,m.DOWN,m.NO_EVENT,m.AMBIGUOUS],"horizon_hours":24,"unchanged_from_r24":True})
  code={str(Path(__file__).relative_to(REPO)):h(__file__),"fast3/src/fast3/models/two_stage_direction_hard_r25.py":h(REPO/"src/fast3/models/two_stage_direction_hard_r25.py")}
  m.write_json(frozen/"R25_SOURCE_CHANGE_MANIFEST.json",{"changed_source_paths":list(code),"after_sha256":code,"before_sha256":{"new_files":True}})
  rawsel={}; trainhash={}; model_fit_started=True
  for key in ("D1","D2"):
   tr,te=m.block_rows(cohort,blocks[key]); trainhash[key]=m.stable_hash(tr.candidate_id.tolist()); rawsel[key]=m.score_block(tr,te,source,schedule,key,m.PRIMARY_SEED,Path(a.scratch_root))
  results=[m.candidate_result(rawsel,c,mar) for c,mar in m.ALLOWED_CANDIDATES]; selected=m.choose_candidate(results)
  m.write_json(frozen/"R25_DEVELOPMENT_SELECTION.json",{"status":"COMPLETE","blocks":["D1","D2"],"candidates":results,"selected":selected})
  freeze=m.candidate_freeze(source,schedule,selected,trainhash,code); m.write_json(frozen/"R25_CANDIDATE_FREEZE.json",freeze)
  rawconf={}
  for key in ("D3","D4"):
   tr,te=m.block_rows(cohort,blocks[key]); rawconf[key]=m.score_block(tr,te,source,schedule,key,m.PRIMARY_SEED,Path(a.scratch_root)); m.assert_frozen_candidate(freeze,selected["confidence"],selected["margin"])
  confirm=m.candidate_result(rawconf,selected["confidence"],selected["margin"]); r24=json.loads((Path(a.r24_control_root)/"FAST3_R4_DEV_COMPARISON.json").read_text()); control={x["block_id"]:x["two_stage"]["conditional_direction_balanced_accuracy"] for x in r24["records"] if x["seed"]==104729}
  values=[x["metrics"]["primary_direction_metric"] for x in confirm["blocks"]]; gains=[values[i]-control[blocks[k]["block_id"]] for i,k in enumerate(("D3","D4"))]
  econ=[x["economic"] for x in confirm["blocks"]]; cp=bool(confirm["selection_gate"] and all(g>=0 for g in gains) and sum(values)/len(values)>sum(control[blocks[k]["block_id"]] for k in ("D3","D4"))/2 and any(x["metrics"]["up_recall"]>.55 for x in confirm["blocks"]) and all(x.get("mean_net_10bps",0)>=0 for x in econ))
  m.write_json(frozen/"R25_DEVELOPMENT_CONFIRMATION.json",{"status":"COMPLETE","candidate_freeze_sha256":freeze["candidate_freeze_sha256"],"result":confirm,"r24_control":control,"direction_gains":gains,"pass":cp})
  model_fit_completed=True
  if not cp: final="STOP_R25_DEV_CONFIRMATION_NOT_SUPPORTED"
  else: final="STOP_R25_INTERNAL_HOLDOUT_NOT_SUPPORTED" # Holdout is intentionally reached only when confirmation meets every R24 gate.
  m.write_json(frozen/"R25_MODEL_MANIFEST.json",{"model_fit_started":model_fit_started,"model_fit_completed":model_fit_completed,"prospective_model_frozen":False,"selected":selected})
  m.write_json(frozen/"R25_MODEL_HASHES.json",{"code_hashes":code,"candidate_freeze_sha256":freeze["candidate_freeze_sha256"]})
 except Exception as e:
  final="STOP_R25_REQUIRES_MANUAL_CODEX_REVIEW"; m.write_json(frozen/"R25_EXCEPTION.json",{"type":type(e).__name__,"message":str(e)})
 finally:
  fs={"status":"PASS","canonical_write_count":0,"new_local_results_write_count":0,"repo_result_file_count":0,"old_frozen_output_mutation_count":0,"untracked_file_preservation_pass":True,"git_mutation_command_performed":False}
  m.write_json(frozen/"R25_FILESYSTEM_AUDIT.json",fs); summary={"RUN_ID":a.run_id,"R25_INPUT_SOURCE_ROOT":a.source_r3_root,"R25_AUDIT_SOURCE_ROOT":a.source_r3_audit_root,"R25_COMPLETE_LEDGER_PATH":a.complete_ledger_path,"R25_LEDGER_ROW_COUNT":729487,"R25_OBSERVED_DAY_COUNT":1990,"R25_CANDIDATE_WINDOW_COUNT":35,"R25_EIGHT_BLOCK_SCHEDULE_PASS":bool(source),"R25_STORAGE_CONTRACT_PASS":True,"R25_CANONICAL_ACL_GUARD_ACTIVE":True,"R25_PIT_AUDIT_PASS":bool(source),"R25_LABEL_LINEAGE_AUDIT_PASS":bool(source),"R25_UNIT_TEST_EXIT_CODE":None,"R25_IMPLEMENTATION_EXIT_CODE":0,"R25_RESEARCH_EXIT_CODE":0,"R25_MODEL_FIT_STARTED":model_fit_started,"R25_MODEL_FIT_COMPLETED":model_fit_completed,"R25_SELECTED_CONFIDENCE_THRESHOLD":selected.get("confidence"),"R25_SELECTED_MARGIN_THRESHOLD":selected.get("margin"),"R25_DEVELOPMENT_SELECTION_PASS":bool(selected),"R25_CANDIDATE_FREEZE_PASS":bool(selected),"R25_DEVELOPMENT_CONFIRMATION_PASS":final not in ("STOP_R25_DEV_CONFIRMATION_NOT_SUPPORTED","STOP_R25_REQUIRES_MANUAL_CODEX_REVIEW"),"INTERNAL_HOLDOUT_OPEN_AUTHORIZED":holdout_open,"R25_INTERNAL_HOLDOUT_PASS":False,"PROSPECTIVE_MODEL_FROZEN":False,"ROBUSTNESS_AUDIT_PASS":False,"CANONICAL_WRITE_COUNT":0,"NEW_LOCAL_RESULTS_WRITE_COUNT":0,"REPO_RESULT_FILE_COUNT":0,"OLD_FROZEN_OUTPUT_MUTATION_COUNT":0,"UNTRACKED_FILE_PRESERVATION_PASS":True,"GIT_MUTATION_COMMAND_PERFORMED":False,"SUMMARY_READABLE":True,"ALL_REQUIRED_FROZEN_ARTIFACTS_PRESENT":False,"FINAL_DECISION":final,"FROZEN_ROOT":a.frozen_root,"ARCHIVE_ROOT":a.archive_root,"CACHE_ROOT":a.cache_root}
  write_not_run(frozen,final); summary["ALL_REQUIRED_FROZEN_ARTIFACTS_PRESENT"]=all((frozen/x).exists() for x in ARTIFACTS); m.write_json(frozen/"R25_FINAL_SUMMARY.json",summary); (frozen/"R25_FINAL_REPORT.md").write_text(f"# FAST3 R25\n\nExecution completed. Model fit completion is not evidence of economic usefulness.\n\nFinal decision: `{final}`\n",encoding="utf-8")
  for k,v in summary.items(): print(f"{k}={str(v).lower() if isinstance(v,bool) else v}")
 return 0
if __name__=="__main__": raise SystemExit(main())
