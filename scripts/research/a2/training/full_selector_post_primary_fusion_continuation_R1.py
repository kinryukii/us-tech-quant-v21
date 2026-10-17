"""Fixed post-primary engineering continuation. SOURCE-ONLY PROPOSAL until installed.
Only original unentered fusion DAG nodes may enter the original fusion owner.
No primary/replay/risk/account/statistics business implementation is introduced.
"""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import re
import sqlite3
import sys
import traceback
from types import MethodType, SimpleNamespace

REPO=Path("D:/us-tech-quant")
RUN=Path("D:/us-tech-quant-backtests/V24/20261010T151740+0000_642c1248")
CACHE=Path("D:/us-tech-quant-cache/V24/C_SELECTOR/FULL_SELECTOR_FIXED_POLICY_FAST_R1")
ID="V24_C_FULL_SELECTOR_FIXED_POLICY_FAST_R1"
NAME="POST_PRIMARY_FUSION_SOURCE_CONTINUATION_R1"
ENTRY=REPO/"scripts/research/a2/training/full_selector_post_primary_fusion_continuation_R1.py"
TEST=CACHE/"proposals/test_full_selector_post_primary_fusion_continuation_R1.py"
FOLDER=RUN/"continuation"
CONFIG=FOLDER/(NAME+"_CONFIGURATION.json")
REVIEW=RUN/"maintenance"/(NAME+"_SOURCE_REVIEW_R1.json")
ADMISSION=RUN/"maintenance"/(NAME+"_INDEPENDENT_ADMISSION_REVIEW_R1.json")
ACCEPT=FOLDER/(NAME+"_ACCEPTANCE.json")
COLD=CACHE/"proposals"/(NAME+"_COLD.json")
START=FOLDER/(NAME+"_STARTED.json")
COMPLETE=FOLDER/(NAME+"_COMPLETE.json")
FAILURE=FOLDER/(NAME+"_FAILURE.json")
R4=RUN/"ENGINEERING_SOURCE_CORRECTION_R4.json"
CONTROLLER=REPO/"scripts/research/a2/training/selector_full_fixed_policy.py"
TARGET="MODEL|FT_TRANSFORMER|2024-07-01|HIGH|20260929|None"
TOKEN="cb5995cda52856965cb76b71111613c7cc2b3d82e07655deb8037170d4d2b075"
METHODS=("median","simplex","nnls","ridge_stack","elastic_stack","hgb_stack","mlp_stack","linear_gate","mlp_gate","ridge_then_hgb","hgb_then_ridge")
ALPHA={"ESTIMATOR","SCALER","CALIBRATOR","META_MODEL","META_SCALER","META_TARGET_SCALE","HYBRID_ESTIMATOR","HYBRID_SCALER"}
FUSION={"META_MODEL","META_SCALER","META_TARGET_SCALE"}
TERM={"COMPLETE","FAILED","SOURCE_NOT_TESTABLE","BLOCKED_DEPENDENCY"}
HISTORY={
 "boundary_ref":(FOLDER/"ALPHA_REBOOT_FAILURE_FUSION_SOURCE_DRIFT_R1_BOUNDARY.json","3dc4f969640b65a82acf6fe69b9bdfe61b9e7c1fd92a1b75b892271775262595"),
 "prior_failure_ref":(FOLDER/"REMAINING_ALPHA_REBOOT_RECOVERY_R1_FAILURE.json","a75a237323b19fa06ada0f5bcdd0f48cfcc8efb998528760d3f2559b69cef03e"),
 "prior_started_ref":(FOLDER/"REMAINING_ALPHA_REBOOT_RECOVERY_R1_STARTED.json","802ae235823af588a004638595c6592551a1137c1bafae4ce10a381f0da6ed5d"),
 "prior_configuration_ref":(FOLDER/"REMAINING_ALPHA_REBOOT_RECOVERY_R1_CONFIGURATION.json","6676582c67bf0966349bd1476f07d9af56399b3d72df4700df6640a033ac54e6"),
 "prior_acceptance_ref":(FOLDER/"REMAINING_ALPHA_REBOOT_RECOVERY_R1_ACCEPTANCE.json","b530db332b2c112766047a7e709e11069c839391e987089b189b4304b09c91ec"),
 "design_ref":(RUN/"DESIGN_FREEZE.json","20a855c2bf4df41b1e84fbc8159a473a04a575ccfb5ba76ed819d1975bcb8359"),
 "authority_ref":(FOLDER/"CURRENT_ROUND_BACKGROUND_PYTHON_PERMISSION_R1.json","7c5648dc99dea580d7ec32491d838eae182c40ffa4bd28e40eacfbcc0cd83235")}
OWNER_PINS={
 "scripts/research/a2/training/full_selector_engineering_continuation.py":"c6a8f9ac13ba1570661c7496b661007d211d17b01a70dcebca37126df6a6dcc0",
 "scripts/research/a2/training/full_selector_workflow.py":"4e989ebb783ce4b7c0f231417afee1e1357a6b38c94f78ddd60801c7ad72160d",
 "scripts/research/a2/training/full_selector_alpha_reboot_recovery.py":"0e81a6dab455ad23b80d1014f6cc14b87ef830d34b04b3086855c153eafdd64c"}
CONFIG_KEYS={"schema","research_id","phase","entry_ref","test_ref","boundary_ref","prior_failure_ref","source_configuration_ref","controller_ref","source_review_ref","authority_ref","fixed_methods","first_fusion_entry_only","new_backend_replays_authorized","paid_cap"}
ACCEPT_KEYS={"schema","research_id","status","independent_from_entry_writer","config_ref","entry_ref","boundary_ref","source_review_ref","actual_cold_ref","admission_review_ref","old_workers_gone","first_fusion_entry_only"}

def require(value,message):
 if not value:raise ValueError(message)

def stamp():return datetime.now(timezone.utc).isoformat()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),default=str,allow_nan=False).encode()).hexdigest()
def sha(path):
 h=hashlib.sha256()
 with Path(path).open("rb") as handle:
  for block in iter(lambda:handle.read(1024*1024),b""):h.update(block)
 return h.hexdigest()
def reference(path):return dict(path=str(Path(path).resolve()),sha256=sha(path))

def pin(value,path=None):
 require(isinstance(value,dict) and set(value)=={"path","sha256"} and re.fullmatch("[0-9a-f]{64}",str(value["sha256"])) is not None,"CLOSED_PHYSICAL_REFERENCE_REQUIRED")
 physical=Path(value["path"]).resolve()
 require(path is None or physical==Path(path).resolve(),"FIXED_PHYSICAL_PATH_REQUIRED")
 require(physical.is_file() and sha(physical)==value["sha256"],"PHYSICAL_REFERENCE_CHANGED:"+str(physical))
 return physical

def read(path,limit=2*1024*1024):
 path=Path(path);require(path.is_file() and path.stat().st_size<=limit,"BOUNDED_METADATA_REQUIRED")
 return json.loads(path.read_text(encoding="utf-8"))

def historical_refs():
 refs={name:dict(path=str(path.resolve()),sha256=expected) for name,(path,expected) in HISTORY.items()}
 for name,value in refs.items():pin(value,HISTORY[name][0])
 return refs

def validate_configuration(cfg,entry_ref,test_ref,refs):
 require(set(cfg)==CONFIG_KEYS and cfg["schema"]=="FULL_SELECTOR_POST_PRIMARY_FUSION_CONFIGURATION_R1" and cfg["research_id"]==ID and cfg["phase"]==NAME,"CLOSED_FIXED_FUSION_CONFIGURATION_REQUIRED")
 require(cfg["entry_ref"]==entry_ref and cfg["test_ref"]==test_ref and cfg["boundary_ref"]==refs["boundary_ref"] and cfg["prior_failure_ref"]==refs["prior_failure_ref"] and cfg["authority_ref"]==refs["authority_ref"],"EXACT_SOURCE_AND_HISTORY_BINDINGS_REQUIRED")
 require(cfg["fixed_methods"]==list(METHODS) and cfg["first_fusion_entry_only"] is True and type(cfg["new_backend_replays_authorized"]) is int and cfg["new_backend_replays_authorized"]==0 and type(cfg["paid_cap"]) is int and cfg["paid_cap"]==738,"ONLY_FIXED11_FIRST_ENTRY_NO_REPLAY_CAP738")
 require(Path(cfg["controller_ref"]["path"]).resolve()==CONTROLLER.resolve() and Path(cfg["source_configuration_ref"]["path"]).resolve()==R4.resolve() and Path(cfg["source_review_ref"]["path"]).resolve()==REVIEW.resolve(),"FIXED_CONTROLLER_R4_REVIEW_PATHS_REQUIRED")

def load_authority():
 require(Path(__file__).resolve()==ENTRY.resolve(),"SOURCE_ONLY_PROPOSAL_NOT_INSTALLED")
 refs=historical_refs()
 for relative,expected in OWNER_PINS.items():pin(dict(path=str(REPO/relative),sha256=expected),REPO/relative)
 cfg=read(CONFIG,65536);entry_ref=reference(ENTRY);test_ref=reference(TEST);validate_configuration(cfg,entry_ref,test_ref,refs)
 pin(cfg["controller_ref"],CONTROLLER);pin(cfg["source_configuration_ref"],R4);pin(cfg["source_review_ref"],REVIEW)
 source=read(R4);require(source.get("schema")=="FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R4" and source.get("status")=="PASS" and source.get("research_id")==ID,"ACTUAL_APPROVED_R4_CONFIGURATION_REQUIRED")
 review=read(REVIEW)
 require(review.get("schema")=="FULL_SELECTOR_POST_PRIMARY_FUSION_SOURCE_REVIEW_R1" and review.get("status")=="PASS" and review.get("research_id")==ID and review.get("independent_from_entry_writer") is True,"INDEPENDENT_FIXED_FUSION_SOURCE_REVIEW_REQUIRED")
 for key in ("entry_ref","test_ref","source_configuration_ref","controller_ref","boundary_ref"):require(review.get(key)==cfg[key],"SOURCE_REVIEW_BINDING_CHANGED:"+key)
 boundary=read(refs["boundary_ref"]["path"])
 require(boundary.get("schema")=="FULL_SELECTOR_ALPHA_REBOOT_FAILURE_FUSION_SOURCE_DRIFT_BOUNDARY_R1" and boundary.get("status")=="ENGINEERING_FAILURE_BOUNDARY_OBSERVED_NO_ACCEPTANCE" and boundary.get("research_id")==ID and boundary.get("metadata_only") is True,"ACTUAL_FAILURE_BOUNDARY_REQUIRED")
 require(boundary["failure_ref"]==refs["prior_failure_ref"] and boundary["reboot_started_ref"]==refs["prior_started_ref"] and boundary["reboot_configuration_ref"]==refs["prior_configuration_ref"] and boundary["reboot_acceptance_ref"]==refs["prior_acceptance_ref"] and boundary["freeze_ref"]==refs["design_ref"],"OLD_REBOOT_HISTORY_CHANGED")
 require(not (FOLDER/"REMAINING_ALPHA_REBOOT_RECOVERY_R1_COMPLETE.json").exists(),"OLD_REBOOT_FAILURE_CANNOT_BECOME_COMPLETE")
 return cfg,refs,boundary

def scope_nodes(design):
 nodes=[v for v in design["dag"]["nodes"] if v.get("method") in METHODS]
 require(len(nodes)==74 and len({v["node_id"] for v in nodes})==74 and Counter(v["kind"] for v in nodes)=={"META_MODEL":32,"META_SCALER":28,"META_TARGET_SCALE":14},"EXACT_FROZEN74_FUSION_SCOPE_REQUIRED")
 require(all(v["kind"] in FUSION for v in nodes),"NONFUSION_NODE_IN_SCOPE")
 return {v["node_id"] for v in nodes}

def validate_metadata(rows,events,design,boundary,terminal=False):
 """Pure metadata comparison against the actual failure boundary; no second ledger."""
 require(all(len(v)==7 for v in rows) and len({v[0] for v in rows})==len(rows),"EXACT_SEVEN_COLUMN_ROWS_REQUIRED")
 byid={v[0]:v for v in rows};frozen={v["node_id"]:v["kind"] for v in design["dag"]["nodes"]};scope=scope_nodes(design)
 require({n:v[1] for n,v in byid.items()}==frozen and len(rows)==boundary["actual_sql_observation"]["node_count"],"FROZEN_NODE_SET_CHANGED")
 require([v[0] for v in events]==list(range(1,len(events)+1)) and all(v[1] in byid for v in events),"CONTIGUOUS_KNOWN_NODE_EVENTS_REQUIRED")
 require(len(events)>=1554 and digest(events[:1554])==boundary["actual_sql_observation"]["events_sha256"],"ORIGINAL1554_FAILURE_PREFIX_CHANGED")
 require(all(v[2] in TERM|{"NAMED"} and v[3] in (0,1) for v in rows),"STARTED_OR_INVALID_TAIL_CANNOT_CONTINUE")
 require(all(v[2:] == ("NAMED",0,None,None,None) for v in rows if v[2]=="NAMED"),"NAMED_HAS_PRIOR_ENTRY_OR_ERROR")
 require(byid[TARGET][2:5]==("COMPLETE",1,TOKEN) and byid[TARGET][5] is not None and byid[TARGET][6] is None,"REPLAY_TARGET_MUST_REMAIN_COMPLETE")
 failed={v[0] for v in rows if v[2]=="FAILED" and v[0] not in scope}
 require(len(failed)==9 and all(n.startswith("MODEL|ELASTIC_NET|") and byid[n][3]==1 and byid[n][5] is None for n in failed),"ORIGINAL9_FAILED_MUST_REMAIN")
 require(Counter(v[2] for v in events if v[2].startswith("REBOOT_"))=={"REBOOT_REPLAY_RESERVED":1,"REBOOT_REPLAY_ENTER":1} and all(v[1]==TARGET for v in events if v[2].startswith("REBOOT_")),"NO_ADDITIONAL_REBOOT_EVENTS_ALLOWED")
 require(all(v[2] in TERM for v in rows if v[1] in {"ESTIMATOR","SCALER","CALIBRATOR"}),"PRIMARY_NOT_ALL_TERMINAL")
 projection=[(v[0],v[1],"NAMED",0,None,None,None) if v[0] in scope else v for v in rows]
 require(digest(projection)==boundary["actual_sql_observation"]["nodes_sha256"],"PRIMARY_OR_OTHER_BRANCH_CHANGED")
 new=events[1554:];require(all(v[1] in scope for v in new),"NEW_EVENT_OUTSIDE_FIXED_FUSION_SCOPE")
 require(all(v[2] in {"BEGIN","BACKEND_ENTER","COMPLETE","FAILED","BLOCKED_DEPENDENCY"} for v in new),"UNAUTHORIZED_NEW_EVENT_OR_REPLAY")
 require(all(v==1 for v in Counter(x[1] for x in events if x[2]=="BACKEND_ENTER").values()),"DUPLICATE_BACKEND_ENTRY")
 if not terminal:
  require(len(events)==1554 and all(byid[n][2:]==("NAMED",0,None,None,None) for n in scope) and not any(v[1] in scope for v in events),"FUSION_FIRSTENTRY_PRISTINE_REQUIRED")
 else:
  require(all(byid[n][2] in TERM for n in scope),"FIXED_FUSION_NONTERMINAL_TAIL")
  for n in scope:
   row=byid[n];tail=[v for v in new if v[1]==n];actions=[v[2] for v in tail]
   if row[2] in {"COMPLETE","FAILED"}:
    require(actions==["BEGIN","BACKEND_ENTER",row[2]] and row[3]==1 and row[4]==digest(json.loads(tail[0][3])),"FUSION_FIRSTENTRY_CHAIN_CHANGED")
    if row[2]=="COMPLETE":require(row[6] is None and row[5] is not None and json.loads(row[5])==json.loads(tail[-1][3]),"FUSION_COMPLETE_REFERENCE_CHANGED")
    else:require(row[5] is None and isinstance(row[6],str) and row[6] and json.loads(tail[-1][3]).get("entered")==1,"FUSION_FAILED_CHARGE_CHANGED")
   else:
    require(row[2]=="BLOCKED_DEPENDENCY" and actions==["BLOCKED_DEPENDENCY"] and row[3:6]==(0,None,None) and row[6]==json.loads(tail[0][3]).get("reason"),"FUSION_BLOCKED_METADATA_CHANGED")
 paid=sum(v[2] in {"BACKEND_ENTER","REBOOT_REPLAY_ENTER"} and byid[v[1]][1] in ALPHA for v in events)
 remaining=sum(v[1] in ALPHA and v[2]=="NAMED" for v in rows)
 require(paid<=591 and paid+remaining<=738 and (terminal or (paid==517 and remaining==218)),"ORIGINAL738_CUMULATIVE_CAP_REQUIRED")
 return dict(nodes_sha256=digest(rows),events_sha256=digest(events),event_count=len(events),cumulative_paid_alpha_attempts=paid,remaining_alpha_upper=paid+remaining,fusion_firstentry_upper=591,fusion_scope_count=74)

def validate_prediction_pins(current,boundary,terminal=False):
 old=boundary["primary"]["current_prediction_opaque_pins"]
 require(len(old)==596 and digest(old)==boundary["primary"]["current_prediction_pins_sha256"],"ACTUAL596_BOUNDARY_PREDICTIONS_REQUIRED")
 require(all(current.get(path)==expected for path,expected in old.items()),"PRIMARY_OR_EQUAL_PREDICTION_CHANGED")
 if not terminal:require(current==old,"UNREVIEWED_PARTIAL_PREDICTION_PUBLICATION")
 else:
  allowed=set()
  for method in METHODS:
   names=[f"policy_FUSION_{method}.parquet",f"policy_FUSION_{method}.parquet.json",f"failure_FUSION_{method}.json"]
   names += [f"fusion_receipt_{method}_{year}.json" for year in (2024,2025)]
   names += [f"annual_native/FUSION_{method}_{year}.parquet"+suffix for year in (2024,2025) for suffix in ("",".json")]
   allowed.update(str((RUN/"predictions"/name).resolve()) for name in names)
  require(set(current)-set(old)<=allowed,"NEW_PREDICTION_OUTSIDE_FIXED_FUSIONS")
 return dict(file_count=len(current),opaque_pins_sha256=digest(current),primary_and_equal_596_opaque_preserved=True)

def publication_gate(e,boundary,terminal=False):
 for role,item in boundary["primary"]["publications"].items():
  pub=pin(item["publication_ref"]);opposite=RUN/"predictions"/(("failure_" if item["disposition"]=="COMPLETE" else "policy_")+role+(".json" if item["disposition"]=="COMPLETE" else ".parquet"))
  require(not opposite.exists(),"AMBIGUOUS_PRIMARY_PUBLICATION")
  if item["disposition"]=="COMPLETE":side=pin(item["sidecar_ref"],str(pub)+".json");e.frame_receipt(read(side),item["sidecar_ref"])
 for method in METHODS:
  policy=RUN/"predictions"/("policy_FUSION_"+method+".parquet");failure=RUN/"predictions"/("failure_FUSION_"+method+".json")
  paths=[policy,failure]+[RUN/"predictions/annual_native"/("FUSION_"+method+"_"+str(y)+".parquet") for y in (2024,2025)]+[RUN/"predictions"/("fusion_receipt_"+method+"_"+str(y)+".json") for y in (2024,2025)]
  if not terminal:require(not any(p.exists() or Path(str(p)+".json").exists() for p in paths),"FUSION_PARTIAL_PUBLICATION")
  else:
   require(policy.exists()!=failure.exists(),"FUSION_TERMINAL_PUBLICATION_REQUIRED")
   if policy.exists():e.frame_receipt(read(str(policy)+".json"),reference(str(policy)+".json"))
 assembly=read(RUN/"SCORE_ASSEMBLY.json")
 require(assembly.get("forecast2026_rows")==0 and assembly.get("accounts_evaluated")==0,"NO2026_OR_ACCOUNT_ENTRY_ALLOWED")
 return reference(RUN/"SCORE_ASSEMBLY.json")

def observe(e,c,design,boundary,terminal=False):
 e.validate_existing_sqlite(RUN,design)
 db=sqlite3.connect((RUN/"TASK_LEDGER.sqlite").resolve().as_uri()+"?mode=ro",uri=True);db.execute("PRAGMA query_only=ON")
 try:
  journal=SimpleNamespace(db=db,run=RUN,design=design);journal.status=MethodType(c._TaskLedger.status,journal)
  require(db.execute("SELECT design_sha256 FROM authority").fetchall()==[(sha(RUN/"DESIGN_FREEZE.json"),)],"SOLE_AUTHORITY_CHANGED")
  state=e.ledger_snapshot(journal,RUN);events=list(db.execute("SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence"))
  summary=validate_metadata(state["rows"],events,design,boundary,terminal)
  if terminal:e.require_remaining_terminal(journal,(),METHODS)
  predictions={str(p.resolve()):sha(p) for p in sorted((RUN/"predictions").rglob("*")) if p.is_file()}
  require(len(predictions)<=5000,"PREDICTION_METADATA_EXPANSION")
  opaque=validate_prediction_pins(predictions,boundary,terminal);assembly_ref=publication_gate(e,boundary,terminal)
  require(list(db.execute("SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence"))==events,"SQL_CHANGED_DURING_READONLY_OBSERVATION")
  return dict(ledger=summary,predictions=opaque,selection_assembly_ref=assembly_ref)
 finally:db.close()

def no_phase_marker():
 require(not any(path.exists() for path in (START,COMPLETE,FAILURE)),"PHASE_ALREADY_ENTERED_NO_RELAUNCH")

def validate_acceptance(accept,cold,cfg_ref,entry_ref,boundary_ref,source_review_ref,admission_ref,cold_ref):
 require(set(accept)==ACCEPT_KEYS and accept["schema"]=="FULL_SELECTOR_POST_PRIMARY_FUSION_ACCEPTANCE_R1" and accept["status"]=="PASS" and accept["research_id"]==ID and accept["independent_from_entry_writer"] is True and accept["old_workers_gone"] is True and accept["first_fusion_entry_only"] is True,"FINAL_INDEPENDENT_FUSION_ACCEPTANCE_REQUIRED")
 for key,value in dict(config_ref=cfg_ref,entry_ref=entry_ref,boundary_ref=boundary_ref,source_review_ref=source_review_ref,actual_cold_ref=cold_ref,admission_review_ref=admission_ref).items():require(accept[key]==value,"ACCEPTANCE_BINDING_CHANGED:"+key)
 require(cold.get("schema")=="FULL_SELECTOR_POST_PRIMARY_FUSION_COLD_R1" and cold.get("status")=="PASS" and cold.get("research_id")==ID and cold.get("actual_cold") is True and cold.get("synthetic") is False and cold.get("business_entry_calls")==0 and cold.get("model_deserialization_calls")==0 and cold.get("forecast_or_label_value_reads")==0 and cold.get("phase_marker_writes")==0 and cold.get("economic_reads")==0 and cold.get("source_and_sql_unchanged") is True and cold.get("source_guard_passed") is True and cold.get("registry_metadata_scope_passed") is True and cold.get("numerical_body_sentinel_active") is True and cold.get("metadata_contexts_restored") is True,"ACTUAL_ZERO_BUSINESS_COLD_REQUIRED")
 for key,value in dict(config_ref=cfg_ref,entry_ref=entry_ref,boundary_ref=boundary_ref,source_review_ref=source_review_ref).items():require(cold.get(key)==value,"COLD_BINDING_CHANGED:"+key)
 require(cold["before"]==cold["after"],"COLD_PRE_POST_METADATA_CHANGED")

def write(e,path,value,kind):
 from scripts.common.storage_paths import resolve,assert_safe_output_path
 assert_safe_output_path(path,kind=kind,paths=resolve(REPO))
 return e.append_json(path,value)

@contextmanager
def metadata_only_scope(c):
 """Block numerical/business bodies during inspect/cold, then restore objects."""
 import joblib
 import pickle
 saved=[];calls=Counter()
 def block(label):
  def denied(*args,**kwargs):
   calls[label]+=1
   raise ValueError("METADATA_ONLY_BODY_ENTRY_FORBIDDEN:"+label)
  return denied
 targets=[(c,name) for name in ("train_primary","train_fusion","FullSelectorReader","worker_runtime","_load_frame","_raw_reference","_fusion_inputs","_fusion_forecast","assemble_selection")]
 targets += [(c._TaskLedger,"__init__"),(joblib,"load"),(pickle,"load"),(pickle,"loads"),(c.pd,"read_parquet")]
 try:
  for owner,name in targets:
   original=getattr(owner,name);require(callable(original),"ORIGINAL_NUMERICAL_ENTRY_REQUIRED:"+name)
   saved.append((owner,name,original));setattr(owner,name,block(name))
  yield calls
 finally:
  for owner,name,original in reversed(saved):setattr(owner,name,original)

def fusion_only(c):
 # One existing owner remains authoritative for learners, calibration and journal.
 return c.train_fusion(RUN,METHODS)

def run(operation):
 require(operation in {"inspect","cold","execute"},"FIXED_OPERATION_REQUIRED");no_phase_marker()
 cfg,refs,boundary=load_authority()
 if str(REPO) not in sys.path:sys.path.insert(0,str(REPO))
 r=importlib.import_module("scripts.research.a2.training.full_selector_alpha_reboot_recovery");e=r.e;design=e.read(RUN/"DESIGN_FREEZE.json")
 binding=dict(config_ref=reference(CONFIG),entry_ref=cfg["entry_ref"],test_ref=cfg["test_ref"],boundary_ref=refs["boundary_ref"],source_review_ref=cfg["source_review_ref"],source_configuration_ref=cfg["source_configuration_ref"],controller_ref=cfg["controller_ref"],history_refs=refs)
 result=None
 with r.transported_owners() as (c,w,transport),w._worker_lock(RUN):
  pin(cfg["controller_ref"],c.__file__)
  scope=getattr(c,"nonexecuting_registry_metadata_scope",None)
  require(callable(scope) and Path(inspect.unwrap(scope).__code__.co_filename).resolve()==CONTROLLER.resolve(),"ORIGINAL_CONTROLLER_FINITE_REGISTRY_METADATA_SCOPE_REQUIRED")
  # Activate the real finite registry scope before source guard and SQL admission.
  with (metadata_only_scope(c) if operation!="execute" else nullcontext()) as sentinel_calls:
   with scope(RUN):
    with c.engineering_source_configuration(cfg["source_configuration_ref"]):
     c._verify_task_sources(RUN,design)
     before=observe(e,c,design,boundary)
     nonexecuting_sources=c._registry_metadata_observation()
     c._verify_task_sources(RUN,design);pin(cfg["controller_ref"],CONTROLLER);pin(cfg["source_configuration_ref"],R4)
     if operation!="execute":require(not sentinel_calls,"METADATA_ONLY_ENTRY_ATTEMPT_OBSERVED")
     if operation=="inspect":result=dict(schema="FULL_SELECTOR_POST_PRIMARY_FUSION_INSPECT_R1",status="READONLY_PRESTATE_OK",research_id=ID,**binding,observation=before,nonexecuting_source_observation=nonexecuting_sources,business_entry_calls=0)
     elif operation=="cold":
      after=observe(e,c,design,boundary);require(before==after,"ACTUAL_COLD_METADATA_CHANGED")
      c._verify_task_sources(RUN,design);pin(cfg["controller_ref"],CONTROLLER);pin(cfg["source_configuration_ref"],R4)
      require(c._registry_metadata_observation()==nonexecuting_sources,"NONEXECUTING_SOURCE_CLOSURE_CHANGED")
      require(not sentinel_calls,"METADATA_ONLY_ENTRY_ATTEMPT_OBSERVED")
      result=dict(schema="FULL_SELECTOR_POST_PRIMARY_FUSION_COLD_R1",status="PASS",research_id=ID,actual_cold=True,synthetic=False,observed_utc=stamp(),**binding,before=before,after=after,actual_source_transport=transport,nonexecuting_source_observation=nonexecuting_sources,source_guard_passed=True,registry_metadata_scope_passed=True,source_and_sql_unchanged=True,business_entry_calls=0,model_deserialization_calls=0,forecast_or_label_value_reads=0,economic_reads=0,phase_marker_writes=0,numerical_body_sentinel_active=True)
     else:
      pin(reference(ADMISSION),ADMISSION);admission=read(ADMISSION)
      require(admission.get("status")=="PASS" and admission.get("schema")=="FULL_SELECTOR_POST_PRIMARY_FUSION_ADMISSION_REVIEW_R1" and admission.get("research_id")==ID and admission.get("independent_from_entry_writer") is True,"ACTUAL_INDEPENDENT_FUSION_ADMISSION_REQUIRED")
      acceptance=read(ACCEPT);cold=read(COLD);cold_ref=reference(COLD)
      validate_acceptance(acceptance,cold,reference(CONFIG),cfg["entry_ref"],refs["boundary_ref"],cfg["source_review_ref"],reference(ADMISSION),cold_ref)
      for key in ("test_ref","source_configuration_ref","controller_ref"):require(cold.get(key)==cfg[key],"COLD_CURRENT_SOURCE_BINDING_CHANGED:"+key)
      for key,value in dict(config_ref=reference(CONFIG),entry_ref=cfg["entry_ref"],boundary_ref=refs["boundary_ref"],actual_cold_ref=cold_ref).items():require(admission.get(key)==value,"ADMISSION_BINDING_CHANGED:"+key)
      require(before==cold["after"],"ACTUAL_PRELAUNCH_COLD_STATE_CHANGED");no_phase_marker()
      marker=dict(schema="FULL_SELECTOR_POST_PRIMARY_FUSION_STARTED_R1",status="STARTED",research_id=ID,utc=stamp(),**binding,acceptance_ref=reference(ACCEPT),ledger_prestate=before["ledger"],first_fusion_entry_only=True,new_backend_replays_authorized=0)
      marker_ref=write(e,START,marker,"backtest")
      try:
       fusion_only(c)
       c._verify_task_sources(RUN,design)
       after=observe(e,c,design,boundary,terminal=True)
       c._verify_task_sources(RUN,design);pin(cfg["controller_ref"],CONTROLLER);pin(cfg["source_configuration_ref"],R4)
       require(c._registry_metadata_observation()==nonexecuting_sources,"NONEXECUTING_SOURCE_CLOSURE_CHANGED")
       result=dict(schema="FULL_SELECTOR_POST_PRIMARY_FUSION_COMPLETE_R1",status="NATURAL_APPLICATION_RETURN",research_id=ID,utc=stamp(),**binding,marker_ref=marker_ref,acceptance_ref=reference(ACCEPT),before=before,after=after,first_fusion_entry_only=True,new_backend_replay_events=0,original_replay_events_preserved=True,scientific_failed_retries=0,application_fusion_owner_calls=1,os_exit_code_not_inferred=True,actual_source_transport=transport,nonexecuting_source_observation=nonexecuting_sources)
       result["completion_ref"]=write(e,COMPLETE,result,"backtest")
      except Exception:
       failure=dict(schema="FULL_SELECTOR_POST_PRIMARY_FUSION_FAILURE_R1",status="ENGINEERING_FAILURE",research_id=ID,utc=stamp(),**binding,marker_ref=marker_ref,history_preserved=True,retry_authorized=False,error=traceback.format_exc())
       write(e,FAILURE,failure,"backtest")
       raise
 # Context owners restore on success or exception; no natural OS exit is fabricated.
 if operation=="cold":
  result["metadata_contexts_restored"]=True
  result["cold_ref"]=write(e,COLD,result,"cache")
 return result

def main():
 parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group();group.add_argument("--inspect",action="store_true");group.add_argument("--cold",action="store_true");group.add_argument("--execute",action="store_true");args=parser.parse_args()
 result=run("execute" if args.execute else "cold" if args.cold else "inspect")
 print(json.dumps(result,ensure_ascii=False,allow_nan=False),flush=True)
if __name__=="__main__":main()
