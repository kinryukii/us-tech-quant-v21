"""One human-authorized interrupted-fit replay, using the existing C owners.

No ledger reset, extra node, learner, account engine or source-hash waiver.
Original scientific failures remain terminal. The sole interrupted backend is
charged again in its original journal; all other once calls retain their owner.
"""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
import importlib
import importlib.machinery
import importlib.util
import inspect
import sys
import json
from pathlib import Path
import sqlite3
import traceback
from types import MethodType, SimpleNamespace

from scripts.research.a2.training import full_selector_engineering_continuation as e

RUN=e.RUN; ID=e.ID; REPO=e.REPO
NAME="REMAINING_ALPHA_REBOOT_RECOVERY_R1"
FOLDER=RUN/"continuation"
TARGET="MODEL|FT_TRANSFORMER|2024-07-01|HIGH|20260929|None"
TOKEN="cb5995cda52856965cb76b71111613c7cc2b3d82e07655deb8037170d4d2b075"
OLD_PREFIX="1977b4a8dd6472a008714de5504d38ab99282a1aa73323af1a1a04e9ab2f5961"
ALPHA_KINDS={"ESTIMATOR","SCALER","CALIBRATOR","META_MODEL","META_SCALER","META_TARGET_SCALE","HYBRID_ESTIMATOR","HYBRID_SCALER"}
PINS={
 "scripts/research/a2/training/full_selector_engineering_continuation.py":"c6a8f9ac13ba1570661c7496b661007d211d17b01a70dcebca37126df6a6dcc0",
 "scripts/research/a2/training/selector_full_fixed_policy.py":"f28adfcbe664aa1720879dffee998398fea47a9435a63596b94c7eaab3a77e26",
 "scripts/research/a2/training/full_selector_workflow.py":"4e989ebb783ce4b7c0f231417afee1e1357a6b38c94f78ddd60801c7ad72160d"}
CFG_SHA="de6049eeec7a1f61ef6e23a163291306f0e56ce4ef496246517f6cf9c9436778"
SOURCE_SHA="8009d9bdc0f9e23760ea877bdee0f1e72f1af8affdb454e8c10e0f4824bb303f"
OLD_START_SHA="9f4a495276be16f3420ca661baac42a002425810235e5afe7ef70d0da85731ac"
OLD_ACCEPT_SHA="783d0f558006ff12c28819b1b72dfa7d8358bb4d36e76accea6e8db0c3a0a658"
AUTH=FOLDER/(NAME+"_HUMAN_AUTHORIZATION.json")
CONFIG=FOLDER/(NAME+"_CONFIGURATION.json")
ACCEPT=FOLDER/(NAME+"_ACCEPTANCE.json")
TRANSPORT=FOLDER/(NAME+"_SOURCE_TRANSPORT_R4.json")
R4_SOURCE=RUN/"ENGINEERING_SOURCE_CORRECTION_R4.json"
GUARD_AUTH=FOLDER/(NAME+"_SOURCE_GUARD_HUMAN_APPROVAL.json")
GUARD_AUTH_SHA="b007db5df542659fa318fa9f89aebbf1fece235fd56be1e42999f591f9e5f3df"
PRESTATE=FOLDER/(NAME+"_PRESTATE.json")
START=FOLDER/(NAME+"_STARTED.json")
COMPLETE=FOLDER/(NAME+"_COMPLETE.json")
FAILURE=FOLDER/(NAME+"_FAILURE.json")
COLD=e.CACHE/"proposals"/(NAME+"_COLD.json")
require=e.require


TRANSPORT_MODULES={
 "scripts.v22.corporate_action_transition_r1":("scripts/v22/corporate_action_transition_r1.py","c12c7f1ac90016a11bcc782fcf97e30f45a3b8458cf4a188e0a589b240d04f61",Path("D:/us-tech-quant-cache/V24/V24_B_FAST_TRACK_PAIR_COMPLETION_R1/source_audit/original_frozen/corporate_action_transition_r1_c12c7f1ac90016a11bcc782fcf97e30f45a3b8458cf4a188e0a589b240d04f61.py")),
 "scripts.research.a2.data.joint_cash_bindings":("scripts/research/a2/data/joint_cash_bindings.py","338a21f71526437c15a50ae7c27a3bf40d8ce521c79aa66a8822435402e9a13b",Path("D:/us-tech-quant-cache/V24/V24_B_FAST_TRACK_PAIR_COMPLETION_R1/source_audit/original_frozen/joint_cash_bindings_338a21f71526437c15a50ae7c27a3bf40d8ce521c79aa66a8822435402e9a13b.py")),
 "scripts.research.a2.data.reused_pair_ca_sources":("scripts/research/a2/data/reused_pair_ca_sources.py","a973b0deef5546affed39ad868666c52c8c585b1f68929b0402346bbd61e5679",Path("D:/us-tech-quant-cache/V24/V24_B_FAST_TRACK_PAIR_COMPLETION_R1/source_audit/original_frozen/reused_pair_ca_sources_a973b0deef5546affed39ad868666c52c8c585b1f68929b0402346bbd61e5679.py")),
 "scripts.research.a2.evaluation.frozen_a94_profile":("scripts/research/a2/evaluation/frozen_a94_profile.py","34221c56b5d39f1d97aa8fbddf3aa3c7d4c442171b72675864b181bf8e7657f1",e.CACHE/"proposals/frozen_a94_profile_34221c56_runtime_observation.source")}
CONSUMERS=("scripts.research.a2.data.full_selector_inputs","scripts.research.a2.training.selector_full_fixed_policy","scripts.research.a2.training.full_selector_workflow","scripts.research.a2.data.full_selector_account_inputs")


_SOURCE_R5_FORMAL_NAME="ENGINEERING_SOURCE_CORRECTION_R5.json"
_SOURCE_R5_TRANSPORT_NAME="SAVED5_POST_PRIMARY_SOURCE_TRANSPORT_R5.json"
_SOURCE_R5_REVIEW_NAME="SAVED5_POST_PRIMARY_SOURCE_GUARD_R5_INDEPENDENT_REVIEW_R1.json"
_SOURCE_R5_RUN=Path("D:/us-tech-quant-backtests/V24/20261010T151740+0000_642c1248")
_SOURCE_R5_OLD_FORMAL_REF=dict(path=str(_SOURCE_R5_RUN/"ENGINEERING_SOURCE_CORRECTION_R4.json"),sha256="c3025e79f43c6503b97aecfb686399592385e788c0a12bdba3bf38a0a95658b9")
_SOURCE_R5_OLD_TRANSPORT_REF=dict(path=str(_SOURCE_R5_RUN/"continuation/REMAINING_ALPHA_REBOOT_RECOVERY_R1_SOURCE_TRANSPORT_R4.json"),sha256="ced8eb8fff68686b0bc2c654e3a80ac70e90959a124f0612faddc2781557da95")
_SOURCE_R5_CAPTURE_REF=dict(path=str(_SOURCE_R5_RUN/"maintenance/SAVED5_POST_PRIMARY_R5_NONEXECUTED_LIVE_CUSTODY_OBSERVATION_R1.json"),sha256="8ac4183796b0c87636276914bf1dcd907df00c1bb9da73f99a67bf30b72b6de0")
_SOURCE_R5_AUTH_REF=dict(path=str(_SOURCE_R5_RUN/"continuation/CURRENT_ROUND_BACKGROUND_PYTHON_PERMISSION_R1.json"),sha256="7c5648dc99dea580d7ec32491d838eae182c40ffa4bd28e40eacfbcc0cd83235")
_SOURCE_R5_CUSTODY_REFS={
 "controller":dict(path=str(_SOURCE_R5_RUN/"source_corrections/SAVED5_POST_PRIMARY_SOURCE_R5/controller.8ec650d05d97129a9e8dba6d29e41883273f4a5a48d9729f21acc577c9afc414.before.py"),sha256="8ec650d05d97129a9e8dba6d29e41883273f4a5a48d9729f21acc577c9afc414"),
 "transport_owner":dict(path=str(_SOURCE_R5_RUN/"source_corrections/SAVED5_POST_PRIMARY_SOURCE_R5/transport_owner.0e81a6dab455ad23b80d1014f6cc14b87ef830d34b04b3086855c153eafdd64c.before.py"),sha256="0e81a6dab455ad23b80d1014f6cc14b87ef830d34b04b3086855c153eafdd64c")}
_SOURCE_R5_EXTRA_FIELDS={"prior_r4_configuration_ref","prior_r4_transport_ref","prior_runtime_custody_refs",
 "human_authorization_ref","nonexecuted_live_custody_observation_ref","transport_owner_ref"}
_SOURCE_R5_TRANSPORT_EXTRA_FIELDS={"prior_r4_transport_ref","human_authorization_ref","nonexecuted_live_custody_observation_ref"}
_SOURCE_R5_OBSERVED_SHA={
 "scripts.v22.corporate_action_transition_r1":"97a0ecd16297bf0ede9394e78d74e8135ad95fdbded904fbb7bc05bec33f9053",
 "scripts.research.a2.data.joint_cash_bindings":"50c32537eec08491fec14f1ce0755a74b87d8c00ca591c0cd3b76b2da73588ea",
 "scripts.research.a2.data.reused_pair_ca_sources":"7f409781ba68231537c1f9fd8732ccf49bb1c120bc89aa81126bb9ab9de1ef2b",
 "scripts.research.a2.evaluation.frozen_a94_profile":"455934f1f377d9c27cfd3e857f68c3fc5782f0a98e77eaf241780ee20a160703"}
def _source_r5_capture_entry(name,relative,snapshot):
 observed=_SOURCE_R5_OBSERVED_SHA[name]
 basename=Path(relative).stem
 return dict(logical_live_path=str((REPO/relative).resolve()),
  live_observed_ref=dict(path=str((REPO/relative).resolve()),sha256=observed),
  nonexecuted_live_custody_ref=dict(path=str(_SOURCE_R5_RUN/"source_corrections/SAVED5_POST_PRIMARY_SOURCE_R5"/(basename+".live_observation."+observed+".nonexecuted.source")),sha256=observed),
  actual_execution_snapshot_ref=snapshot,exact_at_capture=True,current_after_capture_unknown=True)

class NonexecutingTransportSourceForbidden(RuntimeError):
 pass


_RISK_OBSERVER_REFRESH_SCHEMA="FULL_SELECTOR_RISK_FIXED_TWO_NONEXECUTED_SOURCE_OBSERVER_CAPTURE_R2"
_RISK_OBSERVER_REFRESH_NAME="ENGINEERING_RISK_NONEXECUTED_SOURCE_REFRESH_R1.json"
_RISK_OBSERVER_REFRESH_REVIEW_NAME="FIXED214_NONEXECUTED_SOURCE_REFRESH_INDEPENDENT_REVIEW_R1.json"
_RISK_OBSERVER_REFRESH_EXTRA_FIELDS={"prior_r5_configuration_ref","prior_r5_current_runtime_custody_refs"}
_RISK_OBSERVER_PRIOR_R5_REF=dict(path=str(RUN/"ENGINEERING_SOURCE_CORRECTION_R5.json"),sha256="c3bff6e808e73155f34f74928f28e041e1ee6107fb9b561984d02642e7766a8d")
_RISK_OBSERVER_PRIOR_RUNTIME={
 "controller":dict(path=str(REPO/"scripts/research/a2/training/selector_full_fixed_policy.py"),sha256="c06c16288e939b58e1a78cfbe196996c196c6c7d1f2c65716833f95e0d48442e"),
 "transport_owner":dict(path=str(REPO/"scripts/research/a2/training/full_selector_alpha_reboot_recovery.py"),sha256="343a867113d361ebf3956ebcc5b66f6b4c4fb4e5a88e083e99b44e059de2aca9")}
_RISK_OBSERVER_RUNTIME_CUSTODY={
 key:dict(path=str(RUN/"source_corrections/FIXED214_NONEXECUTED_METADATA_REFRESH_R1"/
 (("controller" if key=="controller" else "transport_owner")+"."+value["sha256"]+".before.py")),sha256=value["sha256"])
 for key,value in _RISK_OBSERVER_PRIOR_RUNTIME.items()}


_ENVIRONMENT_RECOVERY_SCHEMA="FULL_SELECTOR_FIXED_TWO_CAPTURE_ENVIRONMENT_RECOVERY_SOURCE_R4"
_ENVIRONMENT_RECOVERY_REVIEW_SCHEMA="FULL_SELECTOR_ENVIRONMENT_RISK_SOURCE_INDEPENDENT_REVIEW_R1"
_ACCOUNT_FROZEN_SCHEMA='FULL_SELECTOR_RISK_FIXED_TWO_NONEXECUTED_CAPTURE_ORIGINAL_ACCOUNT_TRANSPORT_R3'
_ACCOUNT_FROZEN_REVIEW_SCHEMA='FULL_SELECTOR_RISK_FIXED_TWO_CAPTURE_ORIGINAL_ACCOUNT_TRANSPORT_INDEPENDENT_REVIEW_R3'
_ACCOUNT_FROZEN_TRANSPORT_REF={'path': 'D:\\us-tech-quant-cache\\V24\\C_SELECTOR\\FULL_SELECTOR_FIXED_POLICY_FAST_R1\\proposals\\FIXED214_FROZEN_ACCOUNT_SOURCE_TRANSPORT_R4.json', 'sha256': '7d9f8eae5415cd00d4a2bd3ed17d8632685f9955324521d743324fa6dec90f5f'}
_ACCOUNT_FROZEN_NAMES=("scripts.research.a2.evaluation.continuous_research_account","scripts.research.a2.data.full_selector_account_inputs")

def frozen_account_transport(source_ref):
 source=e.read(e.pin(source_ref,RUN/_RISK_OBSERVER_REFRESH_NAME))
 require(source.get("schema") in (_ACCOUNT_FROZEN_SCHEMA,_ENVIRONMENT_RECOVERY_SCHEMA) and source.get("status")=="PASS" and source.get("frozen_account_source_transport_ref")==_ACCOUNT_FROZEN_TRANSPORT_REF,"CLOSED19_FIXED_ACCOUNT_TRANSPORT_AUTHORITY_REQUIRED")
 doc=e.read(e.pin(_ACCOUNT_FROZEN_TRANSPORT_REF))
 require(set(doc)=={"schema","research_id","scope","entries","recovery_receipt_ref","permission_ref","module_file_semantics"} and doc["schema"]=="FULL_SELECTOR_FIXED_TWO_ORIGINAL_ACCOUNT_SOURCE_TRANSPORT_R4" and doc["research_id"]==ID and set(doc["entries"])==set(_ACCOUNT_FROZEN_NAMES) and doc["scope"]=="EXACT_ORIGINAL_TWO_FROZEN_BYTES_NO_SCIENCE_CHANGE" and doc["permission_ref"]==_SOURCE_R5_AUTH_REF,"CLOSED_FIXED_TWO_ACCOUNT_TRANSPORT_REQUIRED")
 e.pin(doc["permission_ref"]);e.pin(doc["recovery_receipt_ref"])
 design=e.read(e.pin(source["design_ref"],RUN/"DESIGN_FREEZE.json"))
 for name,item in doc["entries"].items():
  require(set(item)=={"original_logical_ref","actual_snapshot_ref"},"CLOSED_TWO_ACCOUNT_ENTRY")
  logical=item["original_logical_ref"];actual=item["actual_snapshot_ref"];expected=(REPO/('/'.join(name.split('.'))+'.py')).resolve()
  require(logical==dict(path=str(expected),sha256=design["sources"][str(expected)]) and actual["sha256"]==logical["sha256"] and Path(actual["path"]).resolve()!=expected,"EXACT_DESIGN_ACCOUNT_BYTES_REQUIRED")
  e.pin(actual)
 review=e.read(e.pin(source["independent_review_ref"],RUN/"maintenance"/_RISK_OBSERVER_REFRESH_REVIEW_NAME))
 require(review.get("schema")==(_ENVIRONMENT_RECOVERY_REVIEW_SCHEMA if source.get("schema")==_ENVIRONMENT_RECOVERY_SCHEMA else _ACCOUNT_FROZEN_REVIEW_SCHEMA) and review.get("frozen_account_source_transport_ref")==_ACCOUNT_FROZEN_TRANSPORT_REF and review.get("original_two_account_snapshots_exact") is True and review.get("other_92_current_live_sources_exact") is False,"INDEPENDENT_FIXED_ACCOUNT_TRANSPORT_REQUIRED")
 return doc

@contextmanager
def frozen_account_scope(source_ref):
 doc=frozen_account_transport(source_ref);entries=doc["entries"]
 require(not any(name in sys.modules for name in (*_ACCOUNT_FROZEN_NAMES,*CONSUMERS)),"PRISTINE_FROZEN_ACCOUNT_CONSUMERS_REQUIRED")
 live={Path(v["original_logical_ref"]["path"]).resolve() for v in entries.values()};actual={Path(v["actual_snapshot_ref"]["path"]).resolve():v["actual_snapshot_ref"]["sha256"] for v in entries.values()}
 require(live.isdisjoint(actual),"SEPARATE_FROZEN_ACCOUNT_SOURCE_REQUIRED")
 state={"active":True};saved={};missing=object();observed={}
 def physical(value):
  if not isinstance(value,(str,bytes,Path)):return None
  if isinstance(value,bytes):value=value.decode(sys.getfilesystemencoding(),errors="surrogateescape")
  return None if str(value).startswith("<") else Path(value).resolve()
 for name,module in tuple(sys.modules.items()):
  origins=[physical(getattr(module,"__file__",None)),physical(getattr(getattr(module,"__spec__",None),"origin",None))]
  origins += [physical(v.__code__.co_filename) for v in vars(module).values() if inspect.isfunction(v)] if module is not None else []
  require(not any(x in live|set(actual) for x in origins),"CACHED_FROZEN_ACCOUNT_ALIAS_FORBIDDEN:"+name)
 def audit(event,args):
  if not state["active"]:return
  if event=="open" and args and physical(args[0]) in live:raise ValueError("FIXED_ACCOUNT_LIVE_SOURCE_FORBIDDEN")
  if event=="import" and args and args[0] in entries and args[0] not in sys.modules:raise ValueError("FIXED_ACCOUNT_LIVE_SOURCE_FORBIDDEN")
  if event=="compile" and len(args)>1:
   origin=physical(args[1]);body=args[0].encode('utf-8') if isinstance(args[0],str) else args[0]
   if origin in live:raise ValueError("FIXED_ACCOUNT_LIVE_SOURCE_FORBIDDEN")
   if origin in actual and (not isinstance(body,(bytes,bytearray)) or e.hashlib.sha256(body).hexdigest()!=actual[origin]):raise ValueError("FIXED_ACCOUNT_SNAPSHOT_COMPILE_BYTES_CHANGED")
   if isinstance(body,(bytes,bytearray)) and e.hashlib.sha256(body).hexdigest() in set(actual.values()) and origin not in actual:raise ValueError("FIXED_ACCOUNT_SNAPSHOT_FILENAME_CHANGED")
  if event=="exec" and args and physical(getattr(args[0],"co_filename",None)) in live:raise ValueError("FIXED_ACCOUNT_LIVE_SOURCE_FORBIDDEN")
 try:
  sys.addaudithook(audit)
  for name in _ACCOUNT_FROZEN_NAMES:
   item=entries[name];parent_name,child=name.rsplit('.',1);parent=importlib.import_module(parent_name);saved[name]=(parent,child,getattr(parent,child,missing))
   require(getattr(parent,child,missing) is missing,"STALE_FROZEN_ACCOUNT_PACKAGE_EXPORT")
   snapshot=Path(item["actual_snapshot_ref"]["path"]).resolve();e.pin(item["actual_snapshot_ref"])
   loader=importlib.machinery.SourceFileLoader(name,str(snapshot));spec=importlib.util.spec_from_loader(name,loader);module=importlib.util.module_from_spec(spec)
   module.__file__=item["original_logical_ref"]["path"];module.__frozen_account_transport_ref__=_ACCOUNT_FROZEN_TRANSPORT_REF
   sys.modules[name]=module;setattr(parent,child,module)
   payload=snapshot.read_bytes();require(e.hashlib.sha256(payload).hexdigest()==item["actual_snapshot_ref"]["sha256"],"FROZEN_ACCOUNT_COMPILE_BYTES_CHANGED")
   exec(compile(payload,str(snapshot),'exec'),module.__dict__)
   require(Path(module.__file__).resolve()==Path(item["original_logical_ref"]["path"]).resolve() and Path(module.__spec__.origin).resolve()==snapshot and Path(module.__loader__.path).resolve()==snapshot and module.__loader__ is module.__spec__.loader,"LOGICAL_FILE_ACTUAL_LOADER_SPEC_REQUIRED")
   own=[v for v in vars(module).values() if inspect.isfunction(v) and v.__module__==name]
   require(own and all(Path(v.__code__.co_filename).resolve()==snapshot for v in own),"FROZEN_ACCOUNT_FUNCTION_ORIGINS_REQUIRED")
   observed[name]=dict(logical_file_ref=item["original_logical_ref"],actual_snapshot_ref=item["actual_snapshot_ref"],local_function_count=len(own),all_local_function_origins_exact=True)
  require(sys.modules[_ACCOUNT_FROZEN_NAMES[1]].account is sys.modules[_ACCOUNT_FROZEN_NAMES[0]],"SAME_FROZEN_ACCOUNT_OBJECT_REQUIRED")
  yield observed
 finally:
  for name in reversed(tuple(saved)):
   parent,child,previous=saved[name];sys.modules.pop(name,None)
   if previous is missing:
    if hasattr(parent,child):delattr(parent,child)
   else:setattr(parent,child,previous)
  state["active"]=False

def _source_r5_transport_inputs(configuration_ref,source_ref):
 require(configuration_ref is not None and source_ref is not None,"R5_REQUIRES_BOTH_EXACT_REFS")
 e.pin(configuration_ref,RUN/"continuation"/_SOURCE_R5_TRANSPORT_NAME)
 is_refresh=Path(source_ref["path"]).resolve()==(RUN/_RISK_OBSERVER_REFRESH_NAME).resolve()
 e.pin(source_ref,RUN/(_RISK_OBSERVER_REFRESH_NAME if is_refresh else _SOURCE_R5_FORMAL_NAME))
 source=e.read(source_ref["path"]);data=e.read(configuration_ref["path"])
 is_environment=source.get("schema")==_ENVIRONMENT_RECOVERY_SCHEMA
 is_account=source.get("schema") in (_ACCOUNT_FROZEN_SCHEMA,_ENVIRONMENT_RECOVERY_SCHEMA)
 base_fields={"schema","status","research_id","design_ref","original_sources","replacements","independent_review_ref",
  "prior_source_configuration_ref","prior_controller_custody_ref","source_transport_ref"}
 require(set(source)==base_fields|_SOURCE_R5_EXTRA_FIELDS|(_RISK_OBSERVER_REFRESH_EXTRA_FIELDS if is_refresh else set())|({"frozen_account_source_transport_ref"} if is_account else set())|({"environment_recovery_manifest_ref"} if is_environment else set()) and source["schema"]==(_ENVIRONMENT_RECOVERY_SCHEMA if is_environment else _ACCOUNT_FROZEN_SCHEMA if is_account else _RISK_OBSERVER_REFRESH_SCHEMA if is_refresh else "FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R5")
  and source["status"]=="PASS" and source["research_id"]==ID and source["source_transport_ref"]==configuration_ref
  and source["prior_r4_configuration_ref"]==_SOURCE_R5_OLD_FORMAL_REF
  and source["prior_r4_transport_ref"]==_SOURCE_R5_OLD_TRANSPORT_REF
  and source["prior_runtime_custody_refs"]==_SOURCE_R5_CUSTODY_REFS
  and source["human_authorization_ref"]==_SOURCE_R5_AUTH_REF
  and source["nonexecuted_live_custody_observation_ref"]==_SOURCE_R5_CAPTURE_REF
  and source["transport_owner_ref"]==e.ref(__file__),"CLOSED_EXACT_R5_FORMAL_AND_OWNER_REQUIRED")
 if is_refresh:
  require(source["prior_r5_configuration_ref"]==_RISK_OBSERVER_PRIOR_R5_REF and source["prior_r5_current_runtime_custody_refs"]==_RISK_OBSERVER_RUNTIME_CUSTODY,"FIXED_ACTUAL_PRIOR_R5_AND_RUNTIME_BYTE_CUSTODIES_REQUIRED")
  e.pin(_RISK_OBSERVER_PRIOR_R5_REF,RUN/"ENGINEERING_SOURCE_CORRECTION_R5.json");prior=e.read(_RISK_OBSERVER_PRIOR_R5_REF["path"])
  require(set(prior)==base_fields|_SOURCE_R5_EXTRA_FIELDS and prior["schema"]=="FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R5" and prior["status"]=="PASS","IMMUTABLE_PRIOR_R5_REQUIRED")
  for key in base_fields|_SOURCE_R5_EXTRA_FIELDS-{"schema","status","independent_review_ref","replacements","transport_owner_ref"}:
   if key not in {"schema","status","independent_review_ref","replacements","transport_owner_ref"}:require(source[key]==prior[key],"ONLY_CURRENT_NONEXECUTED_PROVENANCE_CHANGED:"+key)
  controller=str((REPO/"scripts/research/a2/training/selector_full_fixed_policy.py").resolve())
  extra={str((REPO/"scripts/research/a2/training/full_selector_workflow.py").resolve())} if is_environment else set()
  require(set(source["replacements"])==set(prior["replacements"])|extra,"ORIGINAL_FIVE_PLUS_EXACT_ENVIRONMENT_WORKFLOW_ONLY")
  if is_environment:
   manifest_ref=source["environment_recovery_manifest_ref"];e.pin(manifest_ref)
   require(manifest_ref["sha256"]=="9ddb8ae9164ad4d97fb62db1a47f5aad7a0212fe1079bc3d1a840b42c400df6e","EXACT_ENVIRONMENT_MANIFEST_TRANSPORT")
  for key,item in prior["replacements"].items():
   if key==controller:require(source["replacements"][key]["original_ref"]==item["original_ref"] and source["replacements"][key]["custody_ref"]==item["custody_ref"] and Path(source["replacements"][key]["runtime_ref"]["path"]).resolve()==Path(controller),"ORIGINAL_CONTROLLER_SCIENCE_CUSTODY_PRESERVED")
   else:require(source["replacements"][key]==item,"ORIGINAL_FOUR_EXECUTION_SNAPSHOTS_PRESERVED")
  for key,ref in _RISK_OBSERVER_RUNTIME_CUSTODY.items():e.pin(ref,Path(_RISK_OBSERVER_RUNTIME_CUSTODY[key]["path"]))
  require(prior["replacements"][controller]["runtime_ref"]==_RISK_OBSERVER_PRIOR_RUNTIME["controller"] and prior["transport_owner_ref"]==_RISK_OBSERVER_PRIOR_RUNTIME["transport_owner"],"PRIOR_ACTUAL_C06_343_HISTORY_REQUIRED")
 for ref in (_SOURCE_R5_OLD_FORMAL_REF,_SOURCE_R5_OLD_TRANSPORT_REF,_SOURCE_R5_CAPTURE_REF,_SOURCE_R5_AUTH_REF,*_SOURCE_R5_CUSTODY_REFS.values()):
  e.pin(ref)
 review_ref=source["independent_review_ref"];e.pin(review_ref,RUN/"maintenance"/(_RISK_OBSERVER_REFRESH_REVIEW_NAME if is_refresh else _SOURCE_R5_REVIEW_NAME));review=e.read(review_ref["path"])
 payload={k:source[k] for k in set(source)-{"status","independent_review_ref"}}
 require(review.get("schema")==(_ENVIRONMENT_RECOVERY_REVIEW_SCHEMA if is_environment else _ACCOUNT_FROZEN_REVIEW_SCHEMA if is_account else "FULL_SELECTOR_RISK_FIXED_TWO_NONEXECUTED_SOURCE_CAPTURE_INDEPENDENT_REVIEW_R2" if is_refresh else "FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R5_INDEPENDENT_REVIEW_R1")
  and review.get("status")=="PASS" and review.get("research_id")==ID and review.get("independent_from_root_writer") is True
  and review.get("source_correction_payload_sha256")==e.digest(payload)
  and review.get("source_transport_payload_sha256")==e.digest(data)
  and review.get("four_live_paths_nonexecuted") is True and review.get("original_four_actual_snapshots_exact") is True
  and review.get("current_live_equals_capture_claimed") is False,"ACTUAL_INDEPENDENT_R5_TRANSPORT_REVIEW_REQUIRED")
 if is_refresh:
  require(review.get("prior_c3_c06_343_history_preserved") is True and review.get("fixed_two_registered_nonexecuted_paths_capture") is True and review.get("prior_r5_configuration_ref")==source["prior_r5_configuration_ref"] and review.get("prior_r5_current_runtime_custody_refs")==source["prior_r5_current_runtime_custody_refs"],"ACTUAL_INDEPENDENT_FIXED_OBSERVER_REFRESH_REVIEW_REQUIRED")
 return data

@contextmanager
def nonexecuting_transport_live_scope(data):
 """Deny the four live physical paths before any snapshot/consumer import."""
 live={Path(item["live_observation_ref"]["path"]).resolve() for item in data["entries"].values()}
 capture={Path(item["nonexecuted_live_custody_ref"]["path"]).resolve() for item in data["entries"].values()}
 snapshots={Path(item["actual_snapshot_ref"]["path"]).resolve():item["actual_snapshot_ref"]["sha256"] for item in data["entries"].values()}
 captured_hashes={item["nonexecuted_live_custody_ref"]["sha256"] for item in data["entries"].values()}
 require(live=={(REPO/value[0]).resolve() for value in TRANSPORT_MODULES.values()} and live.isdisjoint(capture|set(snapshots)),
  "FIXED_FOUR_SEPARATE_LIVE_CAPTURE_SNAPSHOT_PATHS_REQUIRED")
 require(not any(name in sys.modules for name in (*TRANSPORT_MODULES,*CONSUMERS)),"PRISTINE_R5_CONSUMERS_REQUIRED")
 state={"active":True}
 def physical(value):
  if not isinstance(value,(str,bytes,Path)):return None
  if isinstance(value,bytes):value=value.decode(sys.getfilesystemencoding(),errors="surrogateescape")
  if str(value).startswith("<"):return None
  return Path(value).resolve()
 for name,module in tuple(sys.modules.items()):
  origins=[physical(getattr(module,"__file__",None))]
  origins += [physical(value.__code__.co_filename) for value in vars(module).values() if inspect.isfunction(value)] if module is not None else []
  require(not any(path in live|capture for path in origins),"CACHED_R5_LIVE_OR_CAPTURE_ALIAS_FORBIDDEN:"+name)
 def audit(event,args):
  if not state["active"]:return
  if event=="open" and args and physical(args[0]) in live:
   raise NonexecutingTransportSourceForbidden("R5_LIVE_SOURCE_OPEN_FORBIDDEN")
  if event=="import" and args and args[0] in TRANSPORT_MODULES:
   loaded=sys.modules.get(args[0]);expected=TRANSPORT_MODULES[args[0]][2].resolve()
   if loaded is None or physical(getattr(loaded,"__file__",None))!=expected:
    raise NonexecutingTransportSourceForbidden("R5_LIVE_SOURCE_IMPORT_FORBIDDEN")
  if event=="compile" and len(args)>1:
   origin=physical(args[1]);body=args[0]
   if origin in live|capture:
    raise NonexecutingTransportSourceForbidden("R5_LIVE_OR_CAPTURE_SOURCE_COMPILE_FORBIDDEN")
   if isinstance(body,str):body=body.encode("utf-8")
   if isinstance(body,(bytes,bytearray)):
    h=e.hashlib.sha256(body).hexdigest()
    if origin in snapshots:
     if h!=snapshots[origin]:raise NonexecutingTransportSourceForbidden("R5_EXACT_SNAPSHOT_COMPILE_BYTES_REQUIRED")
    elif h in captured_hashes:
     raise NonexecutingTransportSourceForbidden("R5_CAPTURE_BYTES_EXECUTION_FORBIDDEN")
  if event=="exec" and args and physical(getattr(args[0],"co_filename",None)) in live|capture:
   raise NonexecutingTransportSourceForbidden("R5_LIVE_OR_CAPTURE_SOURCE_EXEC_FORBIDDEN")
 sys.addaudithook(audit)
 try:
  # Real denial probes; exceptions cannot be swallowed into a false PASS.
  for path in live:
   for operation in (lambda path=path:open(path,"rb"),lambda path=path:compile("pass",str(path),"exec")):
    try:operation()
    except NonexecutingTransportSourceForbidden:pass
    else:require(False,"R5_ACTUAL_LIVE_SOURCE_FENCE_NOT_ACTIVE")
  yield
 finally:state["active"]=False

def transport_configuration(configuration_ref=None,source_ref=None):
 is_r5=configuration_ref is not None or source_ref is not None
 data=_source_r5_transport_inputs(configuration_ref,source_ref) if is_r5 else e.read(TRANSPORT)
 require(set(data)==({"schema","research_id","prior_source_configuration_ref","entries","scope"}|_SOURCE_R5_TRANSPORT_EXTRA_FIELDS if is_r5 else {"schema","research_id","prior_source_configuration_ref","entries","scope"}) and data["schema"]==("FULL_SELECTOR_ALPHA_REBOOT_EXACT_SOURCE_TRANSPORT_R5" if is_r5 else "FULL_SELECTOR_ALPHA_REBOOT_EXACT_SOURCE_TRANSPORT_R4")
  and data["research_id"]==ID and data["prior_source_configuration_ref"]==dict(path=str(RUN/"ENGINEERING_SOURCE_CORRECTION_R2.json"),sha256=SOURCE_SHA)
  and data["scope"]=="EXACT_APPROVED_RUNTIME_BYTES_ONLY" and set(data["entries"])==set(TRANSPORT_MODULES),"CLOSED_EXACT_FOUR_SOURCE_TRANSPORT_REQUIRED")
 if is_r5:
  require(data["prior_r4_transport_ref"]==_SOURCE_R5_OLD_TRANSPORT_REF and data["human_authorization_ref"]==_SOURCE_R5_AUTH_REF
   and data["nonexecuted_live_custody_observation_ref"]==_SOURCE_R5_CAPTURE_REF,"EXACT_CAPTURE_TRANSPORT_HISTORY_REQUIRED")
  capture=e.read(_SOURCE_R5_CAPTURE_REF["path"])
 for name,(relative,old_sha,snapshot) in TRANSPORT_MODULES.items():
  entry=data["entries"][name];logical=dict(path=str(REPO/relative),sha256=old_sha)
  if is_r5:
   observed=_source_r5_capture_entry(name,relative,dict(path=str(snapshot.resolve()),sha256=old_sha))
   require(capture.get("schema")=="FULL_SELECTOR_FIXED_FOUR_NONEXECUTED_LIVE_CUSTODY_OBSERVATION_R1"
    and capture.get("status")=="ACTUAL_METADATA_CAPTURE_NOT_SOURCE_ACCEPTANCE"
    and all(capture["entries"][name][key]==value for key,value in observed.items())
    and entry["live_observation_ref"]==observed["live_observed_ref"]
    and entry["nonexecuted_live_custody_ref"]==observed["nonexecuted_live_custody_ref"]
    and entry["exact_at_capture"] is True and entry["current_after_capture_unknown"] is True,
    "IMMUTABLE_CAPTURE_IS_NOT_CURRENT_LIVE_ACCEPTANCE")
  require(set(entry)==({"logical_original_runtime_ref","live_observation_ref","actual_snapshot_ref","nonexecuted_live_custody_ref","exact_at_capture","current_after_capture_unknown"} if is_r5 else {"logical_original_runtime_ref","live_observation_ref","actual_snapshot_ref"}) and entry["logical_original_runtime_ref"]==logical
   and entry["actual_snapshot_ref"]==dict(path=str(snapshot),sha256=old_sha),"FIXED_ORIGINAL_RUNTIME_SNAPSHOT_REQUIRED")
  if is_r5:e.pin(entry["nonexecuted_live_custody_ref"])
  else:e.pin(entry["live_observation_ref"],REPO/relative)
  e.pin(entry["actual_snapshot_ref"],snapshot)
 return data


@contextmanager
def transported_owners(configuration_ref=None,source_ref=None):
 data=transport_configuration(configuration_ref,source_ref)
 is_r5=configuration_ref is not None or source_ref is not None
 with nonexecuting_transport_live_scope(data) if is_r5 else nullcontext():
  require(not any(name in sys.modules for name in (*TRANSPORT_MODULES,*CONSUMERS)),"PRISTINE_SNAPSHOT_MODULES_AND_CONSUMERS_REQUIRED")
  saved_attrs={};loaded={};missing=object();c=None
  try:
   for name,(_,old_sha,snapshot) in TRANSPORT_MODULES.items():
    parent_name,child=name.rsplit(".",1);parent=importlib.import_module(parent_name)
    saved_attrs[name]=(parent,child,getattr(parent,child,missing))
    require(getattr(parent,child,missing) is missing,"STALE_LIVE_PACKAGE_EXPORT_REQUIRED_ABSENT")
    e.pin(dict(path=str(snapshot),sha256=old_sha))
    loader=importlib.machinery.SourceFileLoader(name,str(snapshot));spec=importlib.util.spec_from_loader(name,loader)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;setattr(parent,child,module)
    source_bytes=snapshot.read_bytes();require(e.hashlib.sha256(source_bytes).hexdigest()==old_sha,"ACTUAL_SOURCE_BYTES_CHANGED")
    exec(compile(source_bytes,str(snapshot),"exec"),module.__dict__)
    require(Path(module.__file__).resolve()==snapshot.resolve(),"ACTUAL_SNAPSHOT_MODULE_FILE_REQUIRED")
    own=[value for value in vars(module).values() if inspect.isfunction(value) and value.__module__==name]
    require(own and all(Path(value.__code__.co_filename).resolve()==snapshot.resolve() for value in own),"ACTUAL_LOCAL_EXPORT_SNAPSHOT_SOURCE_REQUIRED")
    loaded[name]=dict(actual_module_ref=e.ref(module.__file__),local_function_count=len(own),all_local_function_origins_exact=True)
   require(sys.modules["scripts.research.a2.data.reused_pair_ca_sources"].cash is sys.modules["scripts.research.a2.data.joint_cash_bindings"],"CA_MUST_CAPTURE_SAME_JOINT_SNAPSHOT_OBJECT")
   v22=sys.modules["scripts.v22.corporate_action_transition_r1"];joint=sys.modules["scripts.research.a2.data.joint_cash_bindings"]
   require(joint.SourceBackedEntitlementEvent is v22.SourceBackedEntitlementEvent and joint.canonical_bytes is v22.canonical_bytes,"EXACT_V22_JOINT_SNAPSHOT_OBJECTS_REQUIRED")
   source=e.read(source_ref["path"]) if is_r5 else {}
   with frozen_account_scope(source_ref) if source.get("schema") in (_ACCOUNT_FROZEN_SCHEMA,_ENVIRONMENT_RECOVERY_SCHEMA) else nullcontext({}) as frozen_accounts:
    c,w,_=e.owners()
    require(Path(c._correction_ref.__code__.co_filename).resolve()==(REPO/"scripts/research/a2/training/selector_full_fixed_policy.py").resolve(),"ORIGINAL_RESOLVER_MUST_REMAIN_UNWRAPPED")
    yield c,w,dict(configuration_ref=(configuration_ref if is_r5 else e.ref(TRANSPORT)),modules=loaded,live_and_snapshot_distinct=True,
     original_R1_R2_and_verify_task_sources_unchanged=True,actual_controller_ref=e.ref(c.__file__),
     active_source_configuration_ref=(source_ref if is_r5 else e.ref(R4_SOURCE)),source_guard_human_approval_ref=(_SOURCE_R5_AUTH_REF if is_r5 else e.ref(GUARD_AUTH)),frozen_account_modules=frozen_accounts)
  finally:
   for name in reversed(tuple(saved_attrs)):
    parent,child,previous=saved_attrs[name];sys.modules.pop(name,None)
    if previous is missing:
     if hasattr(parent,child):delattr(parent,child)
    else:setattr(parent,child,previous)

def stamp():return datetime.now(timezone.utc).isoformat()


def write(path,value,kind):
 from scripts.common.storage_paths import resolve,assert_safe_output_path
 assert_safe_output_path(Path(path),kind=kind,paths=resolve(REPO))
 return e.append_json(path,value)


def fixed_authority():
 for rel,value in PINS.items():e.pin(dict(path=str(REPO/rel),sha256=value))
 for rel,value in e.ORIGINAL_PINS.items():e.pin(dict(path=str(RUN/rel),sha256=value))
 cfg_ref=dict(path=str(FOLDER/e.SOURCE_RECOVERY_CONFIG),sha256=CFG_SHA);e.pin(cfg_ref)
 source_ref=dict(path=str(RUN/"ENGINEERING_SOURCE_CORRECTION_R2.json"),sha256=SOURCE_SHA);e.pin(source_ref)
 cfg=e.read(cfg_ref["path"])
 require(cfg["engineering_source_configuration_ref"]==source_ref,"ORIGINAL_R2_CONTEXT_REQUIRED")
 old_accept,old_accept_ref=e.load_source_recovery_acceptance(RUN,cfg)
 require(old_accept_ref["sha256"]==OLD_ACCEPT_SHA,"OLD_PHASE_ACCEPTANCE_CHANGED")
 old_start_ref=dict(path=str(FOLDER/(e.SOURCE_RECOVERY_NAME+"_STARTED.json")),sha256=OLD_START_SHA);e.pin(old_start_ref)
 old_start=e.read(old_start_ref["path"])
 require(old_start["review_ref"]==old_accept_ref and old_start["phase_configuration_ref"]==cfg_ref
  and old_start["runtime_entry_ref"]==e.ref(e.__file__),"ORIGINAL_START_BINDING_CHANGED")
 for key in ("base_manifest_ref","previous_entry_custody_ref","prior_source_configuration_ref","prior_remaining_acceptance_ref","prior_metadata_review_ref","preflight_failure_ref"):
  e.pin(cfg[key])
 for key,(relative,value) in e.PRESERVED_CORE_REFS.items():e.pin(cfg[key],RUN/relative);require(cfg[key]["sha256"]==value,"PRESERVED_HISTORY_CHANGED")
 require(not (FOLDER/(e.SOURCE_RECOVERY_NAME+"_COMPLETE.json")).exists() and not (FOLDER/(e.SOURCE_RECOVERY_NAME+"_FAILURE.json")).exists(),"OLD_PHASE_ALREADY_TERMINAL")
 auth=e.read(AUTH)
 require(set(auth)=={"schema","research_id","user_quote","authorized_target","authorized_interruption_replays","old_worker_disposition","boot_utc","original_request_ref","scientific_failure_retries","new_nodes_authorized"}
  and auth["schema"]=="FULL_SELECTOR_INTERRUPTED_FIT_HUMAN_AUTHORIZATION_R1" and auth["research_id"]==ID
  and auth["user_quote"]=="中断的 重新做呗" and auth["authorized_target"]==TARGET and auth["authorized_interruption_replays"]==1
  and auth["scientific_failure_retries"]==0 and auth["new_nodes_authorized"] is False
  and auth["old_worker_disposition"]=="TERMINATED_BY_OS_REBOOT" and auth["boot_utc"]=="2026-10-11T12:15:12.5000000Z","EXACT_NEW_HUMAN_AUTHORITY_REQUIRED")
 e.pin(auth["original_request_ref"],RUN/"USER_REQUEST.txt")
 require(auth["original_request_ref"]["sha256"]=="92248abc42d62a87d759a417814259ad026870bd0947b1ee7d6c628ab9207281","ORIGINAL_USER_SCOPE_CHANGED")
 transport_configuration()
 e.pin(dict(path=str(GUARD_AUTH),sha256=GUARD_AUTH_SHA),GUARD_AUTH)
 guard_auth=e.read(GUARD_AUTH)
 require(guard_auth.get("schema")=="FULL_SELECTOR_ALPHA_REBOOT_FINITE_SOURCE_GUARD_HUMAN_APPROVAL_R1" and guard_auth.get("research_id")==ID
  and guard_auth.get("approved_target")==str(REPO/"scripts/research/a2/training/selector_full_fixed_policy.py")
  and guard_auth.get("proposal_ref",{}).get("sha256")=="1828b9ec7c0daf0768e8da22f641139eaadf8d2f5994262993f8c47f6292f73f"
  and guard_auth.get("scientific_parameters_and_budget_unchanged") is True and guard_auth.get("authorized_interruption_replays")==1
  and guard_auth.get("scientific_failure_retries")==0 and guard_auth.get("new_nodes_authorized") is False,"SPECIFIC_FINITE_SOURCE_GUARD_APPROVAL_REQUIRED")
 e.pin(guard_auth["proposal_ref"]);e.pin(guard_auth["root_review_ref"]);e.pin(guard_auth["prior_controller_custody_ref"])
 active_source_ref=e.ref(R4_SOURCE);r4=e.read(R4_SOURCE)
 require(r4.get("schema")=="FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R4" and r4.get("status")=="PASS"
  and r4.get("prior_source_configuration_ref")==source_ref and r4.get("source_transport_ref")==e.ref(TRANSPORT)
  and r4.get("prior_controller_custody_ref")==guard_auth["prior_controller_custody_ref"],"EXACT_ACTIVE_R4_SOURCE_CHAIN_REQUIRED")
 e.pin(r4["independent_review_ref"])
 return cfg,e.read(RUN/"DESIGN_FREEZE.json"),dict(source_transport_ref=e.ref(TRANSPORT),original_start_ref=old_start_ref,original_acceptance_ref=old_accept_ref,original_configuration_ref=cfg_ref,original_source_configuration_ref=source_ref,source_configuration_ref=active_source_ref,source_guard_human_approval_ref=e.ref(GUARD_AUTH),human_authorization_ref=e.ref(AUTH))


def _require_unentered_named(row,history):
 require(len(row)==7 and row[2]=="NAMED" and row[3:]==(0,None,None,None) and not history[row[0]],"NAMED_WITH_ENTRY_OR_HISTORY")


def observe(journal,c):
 rows=journal.db.execute("SELECT node_id,kind,status,entered,identity,artifact,error FROM nodes ORDER BY node_id").fetchall()
 events=journal.db.execute("SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence").fetchall()
 require(len(rows)==27257 and e.digest(events[:432])==OLD_PREFIX,"SOLE_ORIGINAL_DAG_OR432_PREFIX_CHANGED")
 by_id={row[0]:row for row in rows};history=Counter(event[1] for event in events)
 require(by_id[TARGET][2:]==("STARTED",1,TOKEN,None,None) and [row[0] for row in rows if row[2]=="STARTED"]==[TARGET],"ONLY_EXACT_INTERRUPTED_FIT_CAN_REPLAY")
 require(len(events)==1059 and events[-2][0:3]==(1058,TARGET,"BEGIN") and events[-1][0:3]==(1059,TARGET,"BACKEND_ENTER"),"EXACT_PRE_REBOOT_ENTRY_BOUNDARY_REQUIRED")
 require(c.digest(json.loads(events[-2][3]))==TOKEN,"INTERRUPTED_IDENTITY_CHANGED")
 for row in rows:
  node,kind,status,entered,identity,artifact,error=row
  require(status in e.TERMINAL|{"NAMED","STARTED"} and entered in (0,1),"INVALID_NODE_STATE")
  if status=="NAMED":_require_unentered_named(row,history)
  if status=="COMPLETE":
   require(isinstance(identity,str) and len(identity)==64 and error is None,"INVALID_COMPLETE_ENVELOPE")
   model=e.pin(json.loads(artifact));require(model.is_relative_to((RUN/"models").resolve()),"ARTIFACT_OUTSIDE_SOLE_RUN")
  if status=="FAILED":require(node.startswith("MODEL|ELASTIC_NET|") and entered==1 and artifact is None,"ONLY_PRESERVED_SCIENTIFIC_FAILURE_ALLOWED")
 require(sum(row[2]=="FAILED" for row in rows)==9,"ORIGINAL9_FAILURES_CHANGED")
 require(journal.db.execute("SELECT design_sha256 FROM authority").fetchall()==[(e.sha(RUN/"DESIGN_FREEZE.json"),)],"SOLE_AUTHORITY_CHANGED")
 ordinary=Counter(event[1] for event in events if event[2]=="BACKEND_ENTER")
 require(all(n==1 for n in ordinary.values()) and not any(event[2].startswith("REBOOT_") for event in events),"REBOOT_ATTEMPT_OR_DUPLICATE_ENTRY_EXISTS")
 eligible={row[0] for row in rows if row[1] in ALPHA_KINDS}
 require(len(eligible)==738,"ORIGINAL738_LEARNED_BUDGET_REQUIRED")
 paid=sum(event[2]=="BACKEND_ENTER" and event[1] in eligible for event in events)
 upper=paid+1+sum(row[2]=="NAMED" and row[1] in ALPHA_KINDS for row in rows)
 require(upper<=738,"REPLAY_EXCEEDS_ORIGINAL_PAID_CAP")
 require(not (RUN/"models"/(c.digest(TARGET)+".joblib")).exists(),"ORPHAN_INTERRUPTED_ARTIFACT_NO_OVERWRITE")
 return rows,events,dict(nodes_sha256=e.digest(rows),events_sha256=e.digest(events),event_count=len(events),paid_backend_attempts=paid,paid_attempt_upper_bound=upper)


def dispatch(journal,c,cfg):
 prior=e.read(cfg["prior_remaining_acceptance_ref"]["path"])
 roles=tuple(r for r in c.learners.PARADIGMS if r not in e.core_roles(c));methods=tuple(m for m in c.FUSIONS if m!="equal")
 require(list(roles)==prior["fixed_remaining_roles"] and list(methods)==prior["fixed_remaining_fusions"] and len(roles)==16 and len(methods)==11,"FROZEN_ROSTER_CHANGED")
 active_roles=[];active_methods=[];preserved={}
 for name,kind in [(r,"primary") for r in roles]+[(m,"fusion") for m in methods]:
  cid=name if kind=="primary" else "FUSION_"+name
  policy=RUN/"predictions"/("policy_"+cid+".parquet");failure=RUN/"predictions"/("failure_"+cid+".json")
  relevant=[n["node_id"] for n in journal.design["dag"]["nodes"] if n.get("role")==name or n.get("method")==name or (kind=="primary" and n["node_id"].startswith("PLATT|"+name+"|"))]
  states=[journal.status(node) for node in relevant]
  require(not (policy.exists() and failure.exists()),"AMBIGUOUS_PUBLICATION")
  if policy.exists() or failure.exists():
   require(all(s["status"] in e.TERMINAL for s in states),"PUBLICATION_WITH_OPEN_LEARNER")
   if policy.exists():receipt=e.read(str(policy)+".json");e.frame_receipt(receipt,e.ref(str(policy)+".json"));preserved[cid]=dict(disposition="COMPLETE",ref=receipt,receipt_ref=e.ref(str(policy)+".json"))
   else:preserved[cid]=dict(disposition="FAILED",ref=e.ref(failure))
   continue
  if name=="FT_TRANSFORMER" and kind=="primary":
   require(TARGET in relevant and all(s["status"] in ("COMPLETE","NAMED","STARTED") for s in states),"ONLY_EXACT_FT_PARTIAL_ROLE_ALLOWED")
  else:
   require(all(s["status"]=="NAMED" and s["entered"]==0 for s in states),"OTHER_PARTIAL_ROLE_NOT_AUTHORIZED")
   prefixes=[RUN/"predictions/annual_native"/(cid+"_"+str(y)+".parquet") for y in (2024,2025)]
   if kind=="fusion":prefixes += [RUN/"predictions"/("fusion_receipt_"+name+"_"+str(y)+".json") for y in (2024,2025)]
   require(not any(p.exists() or Path(str(p)+".json").exists() for p in prefixes),"UNREVIEWED_PARTIAL_PUBLICATION")
  (active_roles if kind=="primary" else active_methods).append(name)
 require("FT_TRANSFORMER" in active_roles,"INTERRUPTED_ROLE_MISSING")
 return roles,methods,tuple(active_roles),tuple(active_methods),preserved


def prediction_pins():
 # Bounded metadata/opaque hashes, never parquet/model values at admission.
 paths=sorted((RUN/"predictions").rglob("*"));files=[p for p in paths if p.is_file()]
 require(len(files)<=5000,"UNEXPECTED_PREDICTION_METADATA_EXPANSION")
 return {str(p.resolve()):e.sha(p) for p in files}


def preflight(c,w,cfg,design):
 e.validate_existing_sqlite(RUN,design)
 db=sqlite3.connect((RUN/"TASK_LEDGER.sqlite").resolve().as_uri()+"?mode=ro",uri=True);db.execute("PRAGMA query_only=ON")
 try:
  journal=SimpleNamespace(db=db,run=RUN,design=design);journal.status=MethodType(c._TaskLedger.status,journal)
  before,events,summary=observe(journal,c)
  roles,methods,active_roles,active_methods,preserved=dispatch(journal,c,cfg)
  predictions=prediction_pins()
  return before,events,predictions,dict(ledger_prestate=summary,active_roles=list(active_roles),active_fusions=list(active_methods),fixed_roles=list(roles),fixed_fusions=list(methods),preserved_alpha_refs=preserved,prediction_opaque_pins_sha256=e.digest(predictions),prediction_file_count=len(predictions))
 finally:db.close()


@contextmanager
def interrupted_once(c,authorization_ref,marker_ref,allowed_forecasts):
 import joblib
 saved_once=c._TaskLedger.once;saved_predict=c._predict;state=dict(calls=0,entries=0,forecast_exact_reuses=0)
 def once(journal,node,identity,work):
  if node!=TARGET:return saved_once(journal,node,identity,work)
  if journal.status(node)["status"]=="COMPLETE":return saved_once(journal,node,identity,work)
  require(state["calls"]==0 and journal.status(node)==dict(status="STARTED",entered=1,identity=TOKEN,artifact=None,error=None) and c.digest(identity)==TOKEN,"EXACT_SINGLE_INTERRUPTED_REPLAY_REQUIRED")
  state["calls"]+=1;path=journal.run/"models"/(c.digest(node)+".joblib")
  require(not path.exists(),"ORPHAN_OR_COMPLETE_ARTIFACT_NO_REPLAY")
  with journal.db:journal.event(node,"REBOOT_REPLAY_RESERVED",dict(human_authorization_ref=authorization_ref,marker_ref=marker_ref,prior_identity=TOKEN,attempt_number=2))
  def entered(observation=None):
   require(state["entries"]==0 and journal.status(node)["status"]=="STARTED" and journal.status(node)["entered"]==1,"REPLAY_CALLBACK_EXACTLY_ONCE")
   with journal.db:journal.event(node,"REBOOT_REPLAY_ENTER",dict(human_authorization_ref=authorization_ref,marker_ref=marker_ref,observation=observation or {},paid_additional_attempt=1))
   state["entries"]+=1
  try:
   result=work(entered);require(state["entries"]==1,"REPLAY_WITHOUT_NATIVE_CALLBACK")
   require(not path.exists(),"PRESERVE_EXISTING_NODE_ARTIFACT");path.parent.mkdir(parents=True,exist_ok=True)
   joblib.dump(result,path,compress=3);ref=dict(path=str(path),sha256=c.sha(path))
   with journal.db:
    require(journal.db.execute("UPDATE nodes SET status='COMPLETE',artifact=? WHERE node_id=? AND status='STARTED' AND entered=1 AND identity=?",(json.dumps(ref),node,TOKEN)).rowcount==1,"REPLAY_STATE_CHANGED")
    journal.event(node,"COMPLETE",ref)
   return result
  except Exception as exc:
   with journal.db:
    journal.db.execute("UPDATE nodes SET status='FAILED',error=? WHERE node_id=?",(traceback.format_exc(),node))
    journal.event(node,"FAILED",dict(error=type(exc).__name__+":"+str(exc),entered=1,authorized_interruption_replay=True,additional_native_entries=state["entries"]))
   print(json.dumps(dict(phase="INTERRUPTION_REPLAY_FAILED",node=node,error=str(exc))),flush=True);return None
 def predict(bundle,vectors,calibrator=None):
  if bundle["role"]=="FT_TRANSFORMER":
   path=c._native_path(RUN,bundle["role"],bundle["cutoff"],bundle["capacity"])
   if str(path.resolve()) in allowed_forecasts:
    require(c.sha(path)==allowed_forecasts[str(path.resolve())],"PRESERVED_NATIVE_FORECAST_CHANGED")
    receipt=e.read(str(path)+".json")
    if receipt["keys_sha256"]==c.keys_digest(vectors):
     identity=dict(role=bundle["role"],cutoff=bundle["cutoff"],capacity=bundle["capacity"],training_keys=bundle["training_keys"],max_train_label_end=bundle["max_train_label_end"])
     require(receipt["identity_sha256"]==c.digest(identity),"EXACT_NATIVE_FORECAST_IDENTITY_CHANGED")
     frame,_=c._load_frame(path);state["forecast_exact_reuses"]+=1;return frame
  return saved_predict(bundle,vectors,calibrator)
 c._TaskLedger.once=once;c._predict=predict
 try:yield state
 finally:c._TaskLedger.once=saved_once;c._predict=saved_predict


def validate_admission(accept,config,metadata,transport_observation):
 for k in ("source_review_ref","test_evidence_ref","actual_cold_ref"):e.pin(accept[k])
 source=e.read(accept["source_review_ref"]["path"]);tests=e.read(accept["test_evidence_ref"]["path"])
 require(source.get("schema")=="FULL_SELECTOR_ALPHA_REBOOT_SOURCE_REVIEW_R1" and source.get("research_id")==ID and source.get("status")=="PASS"
  and source.get("independent_from_entry_writer") is True and source.get("entry_ref")==config["entry_ref"] and source.get("test_ref")==config["test_ref"]
  and source.get("source_configuration_ref")==config["source_configuration_ref"] and source.get("source_guard_human_approval_ref")==config["source_guard_human_approval_ref"],"ACTUAL_REVIEWED_ENTRY_AND_TEST_REQUIRED")
 require(tests.get("schema")=="FULL_SELECTOR_ALPHA_REBOOT_TEST_EVIDENCE_R1" and tests.get("research_id")==ID and tests.get("status")=="PASS"
  and tests.get("entry_ref")==config["entry_ref"] and tests.get("test_ref")==config["test_ref"] and tests.get("targeted_final_exit_code")==0
  and tests.get("default_exit_code")==0 and tests.get("source_configuration_ref")==config["source_configuration_ref"]
  and tests.get("source_guard_human_approval_ref")==config["source_guard_human_approval_ref"],"FINAL_TARGETED_AND_APPLICABLE_DEFAULT_EVIDENCE_REQUIRED")
 e.pin(accept["actual_cold_ref"],COLD);cold=e.read(COLD)
 require(cold.get("schema")=="FULL_SELECTOR_ALPHA_REBOOT_COLD_R1" and cold.get("research_id")==ID and cold.get("actual_cold") is True
  and cold.get("status")=="PASS" and cold.get("config_ref")==e.ref(CONFIG) and cold.get("entry_ref")==config["entry_ref"]
  and cold.get("actual_source_transport")==transport_observation and cold.get("prestate_ref")==config["prestate_ref"] and cold.get("ledger_prestate")==metadata["ledger_prestate"]
  and all(cold.get(k) is True for k in ("all99_source_guard","sole_readonly_ledger","opaque_artifacts_verified","no_native_or_prediction_or_label_or_account_or_risk_or_bootstrap_entry")),"ACTUAL_COLD_BINDING_CHANGED")

def run(mode,config_sha=None,acceptance_sha=None):
 cfg,design,bindings=fixed_authority()
 with transported_owners() as (c,w,transport_observation),w._worker_lock(RUN),c.engineering_source_configuration(bindings["source_configuration_ref"]):
  c._verify_task_sources(RUN,design)
  require(not any(p.exists() for p in (START,COMPLETE,FAILURE)),"REBOOT_ATTEMPT_EXISTS_NO_RETRY")
  rows,events,predictions,metadata=preflight(c,w,cfg,design)
  if mode=="inspect":
   result=dict(schema="FULL_SELECTOR_ALPHA_REBOOT_PRESTATE_R1",research_id=ID,status="PASS",bindings=bindings,entry_ref=e.ref(__file__),target=TARGET,identity_sha256=TOKEN,actual_source_transport=transport_observation,**metadata)
   write(PRESTATE,result,"backtest");print(json.dumps(dict(phase=mode,status="PASS",**metadata["ledger_prestate"])),flush=True);return
  e.pin(dict(path=str(CONFIG),sha256=config_sha));config=e.read(CONFIG)
  expected={"schema","research_id","entry_ref","test_ref","authority_ref","prestate_ref","authorized_interruption_replays","scientific_failure_retries","new_nodes_authorized","source_configuration_ref","source_guard_human_approval_ref"}
  require(set(config)==expected and config["schema"]=="FULL_SELECTOR_ALPHA_REBOOT_CONFIGURATION_R1" and config["research_id"]==ID and config["entry_ref"]==e.ref(__file__)
   and config["authority_ref"]==bindings["human_authorization_ref"] and config["source_configuration_ref"]==bindings["source_configuration_ref"]
   and config["source_guard_human_approval_ref"]==bindings["source_guard_human_approval_ref"] and config["authorized_interruption_replays"]==1 and config["scientific_failure_retries"]==0 and config["new_nodes_authorized"] is False,"CLOSED_REBOOT_CONFIGURATION_REQUIRED")
  e.pin(config["test_ref"]);e.pin(config["prestate_ref"],PRESTATE);pre=e.read(PRESTATE)
  require(pre["entry_ref"]==config["entry_ref"] and pre["bindings"]==bindings and pre["actual_source_transport"]==transport_observation and all(pre[k]==v for k,v in metadata.items()),"COMPLETE_PRE_REBOOT_METADATA_SNAPSHOT_CHANGED")
  if mode=="validate-only":
   again=preflight(c,w,cfg,design)[3];require(again==metadata,"READONLY_COLD_CHANGED_STATE")
   write(COLD,dict(schema="FULL_SELECTOR_ALPHA_REBOOT_COLD_R1",research_id=ID,status="PASS",actual_cold=True,config_ref=e.ref(CONFIG),entry_ref=e.ref(__file__),prestate_ref=e.ref(PRESTATE),actual_source_transport=transport_observation,all99_source_guard=True,sole_readonly_ledger=True,opaque_artifacts_verified=True,no_native_or_prediction_or_label_or_account_or_risk_or_bootstrap_entry=True,ledger_prestate=metadata["ledger_prestate"]),"cache")
   print(json.dumps(dict(phase=mode,status="PASS",scientific_entry_calls=0)),flush=True);return
  require(mode=="execute","EXACT_MODE_REQUIRED")
  e.pin(dict(path=str(ACCEPT),sha256=acceptance_sha));accept=e.read(ACCEPT)
  require(set(accept)=={"schema","research_id","status","independent_from_entry_writer","config_ref","source_review_ref","test_evidence_ref","actual_cold_ref","old_workers_gone","authorized_interruption_replays","scientific_failure_retries"}
   and accept["schema"]=="FULL_SELECTOR_ALPHA_REBOOT_ACCEPTANCE_R1" and accept["research_id"]==ID and accept["status"]=="PASS"
   and accept["independent_from_entry_writer"] is True and accept["old_workers_gone"] is True and accept["config_ref"]==e.ref(CONFIG)
   and accept["authorized_interruption_replays"]==1 and accept["scientific_failure_retries"]==0,"INDEPENDENT_REBOOT_ADMISSION_REQUIRED")
  validate_admission(accept,config,metadata,transport_observation)
  e.validate_existing_sqlite(RUN,design);journal=c._TaskLedger(RUN)
  marker=write(START,dict(schema="FULL_SELECTOR_ALPHA_REBOOT_STARTED_R1",research_id=ID,status="STARTED",utc=stamp(),config_ref=e.ref(CONFIG),acceptance_ref=e.ref(ACCEPT),entry_ref=e.ref(__file__),bindings=bindings,actual_source_transport=transport_observation,ledger_prestate=metadata["ledger_prestate"],authorized_interruption_replays=1,scientific_failure_retries=0),"backtest")
  try:
   c.worker_runtime(RUN)
   with interrupted_once(c,bindings["human_authorization_ref"],marker,predictions) as replay:
    c.train_primary(RUN,metadata["active_roles"]);c.train_fusion(RUN,metadata["active_fusions"])
   require(replay["calls"]==replay["entries"]==1,"SOLE_AUTHORIZED_NATIVE_REPLAY_REQUIRED")
   e.require_remaining_terminal(journal,metadata["fixed_roles"],metadata["fixed_fusions"]);c.assemble_selection(RUN)
   after=e.ledger_snapshot(journal,RUN);after_rows={r[0]:r for r in after["rows"]}
   allowed={n["node_id"] for n in design["dag"]["nodes"] if n.get("role") in metadata["active_roles"] or n.get("method") in metadata["active_fusions"] or any(n["node_id"].startswith("PLATT|"+role+"|") for role in metadata["active_roles"])}
   require(all(after_rows[r[0]]==r for r in rows if r[0] not in allowed or r[2] in e.TERMINAL),"PRESERVED_TERMINAL_OR_OTHER_NODE_CHANGED")
   after_events=journal.db.execute("SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence").fetchall()
   require(after_events[:len(events)]==events and all(v[1] in allowed for v in after_events[len(events):]),"FULL_PRE_REBOOT_HISTORY_OR_NON_ALPHA_EVENT_CHANGED")
   require(Counter(v[2] for v in after_events[len(events):] if v[2].startswith("REBOOT_"))=={"REBOOT_REPLAY_RESERVED":1,"REBOOT_REPLAY_ENTER":1},"EXACT_SINGLE_REBOOT_ATTEMPT_CHAIN_REQUIRED")
   require(all(e.sha(path)==value for path,value in predictions.items()),"PRESERVED_PREDICTION_BYTES_CHANGED")
   paid=sum(v[2] in ("BACKEND_ENTER","REBOOT_REPLAY_ENTER") and after_rows[v[1]][1] in ALPHA_KINDS for v in after_events)
   require(paid+sum(r[2]=="NAMED" and r[1] in ALPHA_KINDS for r in after["rows"])<=738,"PAID_BUDGET_CHANGED")
   write(COMPLETE,dict(schema="FULL_SELECTOR_ALPHA_REBOOT_COMPLETE_R1",research_id=ID,status="INDEPENDENT_ALPHA_STAGE_TERMINAL",utc=stamp(),marker_ref=marker,config_ref=e.ref(CONFIG),acceptance_ref=e.ref(ACCEPT),entry_ref=e.ref(__file__),bindings=bindings,actual_source_transport=transport_observation,fixed_roles=metadata["fixed_roles"],fixed_fusions=metadata["fixed_fusions"],ledger_poststate=e.public_snapshot(after),pre_reboot_event_prefix_exact=True,preserved_terminal_nodes_and_prediction_bytes_exact=True,authorized_interruption_replays=1,scientific_failure_retries=0,old_worker_disposition="TERMINATED_BY_OS_REBOOT",new_worker_natural_completion=True,replay_observation=replay,paid_alpha_attempts=paid,other_branch_entry=False,all_task_complete=False),"backtest")
   print(json.dumps(dict(phase="ALPHA_REBOOT_NATURAL_TERMINAL",status="COMPLETE",replay_observation=replay,paid_alpha_attempts=paid)),flush=True)
  except BaseException:
   write(FAILURE,dict(schema="FULL_SELECTOR_ALPHA_REBOOT_FAILURE_R1",research_id=ID,status="FAILED",utc=stamp(),marker_ref=marker,error=traceback.format_exc(),history_preserved=True,retry_authorized=False),"backtest");raise
  finally:journal.db.close()


def main():
 parser=argparse.ArgumentParser();parser.add_argument("--mode",choices=("inspect","validate-only","execute"),required=True);parser.add_argument("--source-sha",required=True);parser.add_argument("--configuration-sha");parser.add_argument("--acceptance-sha");args=parser.parse_args()
 require(e.sha(__file__)==args.source_sha,"REVIEWED_ADDITIVE_SOURCE_REQUIRED")
 run(args.mode,args.configuration_sha,args.acceptance_sha)

if __name__=="__main__":main()