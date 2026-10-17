"""Authorized full-universe C fixed-policy orchestration.

This task adapter calls existing learner, risk, membership and common account
owners. It owns the finite catalog and one task ledger; it is not a new model,
risk or execution platform. No scientific operation precedes independent freeze.
"""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import traceback
import os
from scripts.research.a2.data.joint_input_binding import guard_parquet
from scripts.research.a2.training import selector_cooperation as cooperation
import numpy as np
import pandas as pd
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.data.full_selector_inputs import ID, REPO, FEATURES, KEYS, CUTS, FullSelectorReader, require, keys_digest
from scripts.research.a2.training.selector_challenge import putj, now, sha, runtime
from scripts.research.a2.training import selector_maximal_breadth_estimators as learners

FUSION_MEMBERS = ("RIDGE", "HGB", "XGB", "CAT", "MLP", "QUANTILE_HGB")
FUSIONS = ("equal", "median", "simplex", "nnls", "ridge_stack", "elastic_stack",
           "hgb_stack", "mlp_stack", "linear_gate", "mlp_gate", "ridge_then_hgb", "hgb_then_ridge")
FAMILIES = ("DIAG", "SAMPLE", "LW", "OAS", "CONSTANT_CORRELATION", "EWMA", "PCA_FACTOR",
            "QQQ_RESIDUAL", "FF48_HIERARCHICAL", "DOWNSIDE_SEMIVARIANCE", "TAIL_CVAR",
            "REGIME_COVARIANCE", "UNCERTAINTY_JACKKNIFE", "DISAGREEMENT_ENSEMBLE",
            "SHR_HP", "SHR_EB", "GARCH", "GJR_GARCH")
HYBRIDS = (("RIDGE", "DIAG"), ("HGB", "LW"), ("XGB", "QQQ_RESIDUAL"),
           ("CAT", "DOWNSIDE_SEMIVARIANCE"), ("MLP", "REGIME_COVARIANCE"),
           ("QUANTILE_HGB", "UNCERTAINTY_JACKKNIFE"))
GATES = ("LW_VARIANCE", "NATIVE_H5_CVAR", "FULL_PSD_REPLICA_UNCERTAINTY", "PCA_DIVERSITY")
CORE = ("RAW", "RIDGE", "HGB", "LAMBDAMART", "FUSION_equal", "RISK_DIAG", "RISK_LW", "RISK_OAS", "RISK_EWMA")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode()).hexdigest()


def array_digest(value):
    return hashlib.sha256(np.ascontiguousarray(value, dtype="<f8").tobytes()).hexdigest()


def catalog():
    roles = [dict(policy_id=r, kind="PRIMARY" if r not in learners.MULTITASK else "MULTI_TASK", paradigm=r)
             for r in learners.PARADIGMS]
    roles += [dict(policy_id="FUSION_"+m, kind="FUSION", method=m) for m in FUSIONS]
    roles += [dict(policy_id="QUANTILE_Q10", kind="NATIVE_UNCERTAINTY", base="QUANTILE_HGB"),
              dict(policy_id="GAUSSIAN_MU_MINUS_SIGMA", kind="NATIVE_UNCERTAINTY", base="GAUSSIAN_MLP")]
    roles += [dict(policy_id="RISK_"+f, kind="RISK_MEMBERSHIP", family=f, anchor="HGB") for f in FAMILIES]
    roles += [dict(policy_id="HYBRID_"+p+"_"+f, kind="HYBRID", paradigm=p, family=f) for p,f in HYBRIDS]
    roles += [dict(policy_id="GATE_"+g, kind="GATE", anchor="HGB", gate=g) for g in GATES]
    roles += [dict(policy_id="RAW", kind="RAW_REFERENCE", new_same_downstream_account=True)]
    require(len(roles)==66 and len({r["policy_id"] for r in roles})==66, "EXACT_65_PLUS_RAW_CATALOG_REQUIRED")
    comparisons = [dict(contrast_id=r["policy_id"]+"__VS_RAW", candidate=r["policy_id"], reference="RAW") for r in roles if r["policy_id"]!="RAW"]
    comparisons += [dict(contrast_id="RISK_"+f+"__VS_HGB", candidate="RISK_"+f, reference="HGB") for f in FAMILIES]
    comparisons += [dict(contrast_id="HYBRID_"+p+"_"+f+"__VS_"+p, candidate="HYBRID_"+p+"_"+f, reference=p) for p,f in HYBRIDS]
    comparisons += [dict(contrast_id="GATE_"+g+"__VS_HGB", candidate="GATE_"+g, reference="HGB") for g in GATES]
    comparisons += [dict(contrast_id="QUANTILE_Q10__VS_QUANTILE_HGB", candidate="QUANTILE_Q10", reference="QUANTILE_HGB"),
                    dict(contrast_id="GAUSSIAN_MU_MINUS_SIGMA__VS_GAUSSIAN_MLP", candidate="GAUSSIAN_MU_MINUS_SIGMA", reference="GAUSSIAN_MLP")]
    require(len(comparisons)==95 and len({r["contrast_id"] for r in comparisons})==95, "EXACT_95_FIXED_COMPARISONS_REQUIRED")
    return roles, comparisons


def top20(frame, field="score"):
    """Fixed 5% slots; full U is never limited to a Raw core or boundary."""
    require(not frame.duplicated(KEYS).any(), "DAILY_POLICY_UID_AMBIGUOUS")
    out=frame.copy()
    require(np.isfinite(out[field].to_numpy(float)).all(), "FULL_U_FINITE_SCORE_REQUIRED_NO_MODEL_DOMAIN_SHRINK")
    out["output_qualified"] = True
    out["rank"] = np.nan
    out["selected"] = False
    out["target_weight"] = 0.
    for _,g in out.groupby("signal_date",sort=True):
        valid=g.loc[g.output_qualified].sort_values([field,"security_uid"],ascending=[False,True],kind="stable")
        out.loc[valid.index,"rank"]=np.arange(1,len(valid)+1)
        out.loc[valid.index[:20],"selected"]=True
        out.loc[valid.index[:20],"target_weight"]=.05
    return out


_ENGINEERING_SOURCE_CONFIGURATION = None
_SOURCE_CORRECTION_NAME = "ENGINEERING_SOURCE_CORRECTION_R1.json"
_SOURCE_CORRECTION_PATHS = (
    "scripts/research/a2/training/selector_full_fixed_policy.py",
    "scripts/research/a2/evaluation/frozen_a94_profile.py",
)


_SOURCE_CORRECTION_R2_NAME = "ENGINEERING_SOURCE_CORRECTION_R2.json"
_SOURCE_CORRECTION_R2_PATHS = (*_SOURCE_CORRECTION_PATHS,
    "scripts/research/a2/data/reused_pair_ca_sources.py",
    "scripts/research/a2/data/joint_cash_bindings.py",
)
_SOURCE_CORRECTION_R1_SHA = "29b37530c058f178855ec55494e92ed752aeb57b3b327fabd145fb8abaccb6b5"
_SOURCE_CORRECTION_PRIOR_CONTROLLER_SHA = "ee856ed547703defae37525f1c2e707c406ecde2f99ce5ea13220ed765462bff"


def _correction_ref(ref):
    require(isinstance(ref, dict) and set(ref) == {"path", "sha256"}, "CLOSED_SOURCE_CORRECTION_REFERENCE_REQUIRED")
    path = Path(ref["path"]).resolve()
    require(path.is_file() and sha(path) == ref["sha256"], "SOURCE_CORRECTION_PHYSICAL_PIN_CHANGED")
    return path


# PROPOSAL ONLY: installation requires explicit human approval of this guard change.
# No source hash override: four snapshot byte pins remain distinct from live files.
_SOURCE_CORRECTION_R4_NAME = "ENGINEERING_SOURCE_CORRECTION_R4.json"
_SOURCE_CORRECTION_R4_RUN = Path("D:/us-tech-quant-backtests/V24/20261010T151740+0000_642c1248")
_SOURCE_CORRECTION_R4_DESIGN_SHA = "20a855c2bf4df41b1e84fbc8159a473a04a575ccfb5ba76ed819d1975bcb8359"
_SOURCE_CORRECTION_R4_PRIOR_R2_SHA = "8009d9bdc0f9e23760ea877bdee0f1e72f1af8affdb454e8c10e0f4824bb303f"
_SOURCE_CORRECTION_R4_PRIOR_CONTROLLER_SHA = "ec6d7caf68a511f6084e85aad6ec2ceb6c9e3496ef7620ff5e64d9154cd06a4d"
_SOURCE_CORRECTION_R4_PRIOR_REVIEW_SHA = "e7d5e0db6711d98797aef0e006436e3607de5185791cb73b0cc0cd24dd1ead86"
_SOURCE_CORRECTION_R4_TRANSPORT_NAME = "REMAINING_ALPHA_REBOOT_RECOVERY_R1_SOURCE_TRANSPORT_R4.json"
_SOURCE_CORRECTION_R4_SNAPSHOTS = {
    "scripts.v22.corporate_action_transition_r1": (
        "scripts/v22/corporate_action_transition_r1.py",
        "c12c7f1ac90016a11bcc782fcf97e30f45a3b8458cf4a188e0a589b240d04f61",
        "97a0ecd16297bf0ede9394e78d74e8135ad95fdbded904fbb7bc05bec33f9053",
        "D:/us-tech-quant-cache/V24/V24_B_FAST_TRACK_PAIR_COMPLETION_R1/source_audit/original_frozen/corporate_action_transition_r1_c12c7f1ac90016a11bcc782fcf97e30f45a3b8458cf4a188e0a589b240d04f61.py"),
    "scripts.research.a2.data.joint_cash_bindings": (
        "scripts/research/a2/data/joint_cash_bindings.py",
        "338a21f71526437c15a50ae7c27a3bf40d8ce521c79aa66a8822435402e9a13b",
        "8f57a1b233d3b4bc19421724964b9cb4902591ac580412b359fa03347d163f9e",
        "D:/us-tech-quant-cache/V24/V24_B_FAST_TRACK_PAIR_COMPLETION_R1/source_audit/original_frozen/joint_cash_bindings_338a21f71526437c15a50ae7c27a3bf40d8ce521c79aa66a8822435402e9a13b.py"),
    "scripts.research.a2.data.reused_pair_ca_sources": (
        "scripts/research/a2/data/reused_pair_ca_sources.py",
        "a973b0deef5546affed39ad868666c52c8c585b1f68929b0402346bbd61e5679",
        "d45671945fdaf1adbe24944c06f4dab31e3850b3f703468c1cb203d76f7936cb",
        "D:/us-tech-quant-cache/V24/V24_B_FAST_TRACK_PAIR_COMPLETION_R1/source_audit/original_frozen/reused_pair_ca_sources_a973b0deef5546affed39ad868666c52c8c585b1f68929b0402346bbd61e5679.py"),
    "scripts.research.a2.evaluation.frozen_a94_profile": (
        "scripts/research/a2/evaluation/frozen_a94_profile.py",
        "34221c56b5d39f1d97aa8fbddf3aa3c7d4c442171b72675864b181bf8e7657f1",
        "455934f1f377d9c27cfd3e857f68c3fc5782f0a98e77eaf241780ee20a160703",
        "D:/us-tech-quant-cache/V24/C_SELECTOR/FULL_SELECTOR_FIXED_POLICY_FAST_R1/proposals/frozen_a94_profile_34221c56_runtime_observation.source"),
}


def _source_r4_loaded_modules(transport):
    """Check actual module/function paths; verified-byte loading is an entry gate."""
    import inspect
    import sys
    for name, entry in transport["entries"].items():
        module = sys.modules.get(name)
        snapshot = Path(entry["actual_snapshot_ref"]["path"]).resolve()
        require(module is not None and getattr(module, "__name__", None) == name
            and Path(getattr(module, "__file__", "")).resolve() == snapshot,
            "R4_ACTUAL_SNAPSHOT_MODULE_ORIGIN_REQUIRED:" + name)
        local_functions = [value for value in vars(module).values()
            if inspect.isfunction(value) and value.__module__ == name]
        require(bool(local_functions) and all(Path(value.__code__.co_filename).resolve() == snapshot
            for value in local_functions), "R4_ACTUAL_SNAPSHOT_FUNCTION_ORIGIN_REQUIRED:" + name)
    v22 = sys.modules["scripts.v22.corporate_action_transition_r1"]
    joint = sys.modules["scripts.research.a2.data.joint_cash_bindings"]
    ca = sys.modules["scripts.research.a2.data.reused_pair_ca_sources"]
    require(getattr(joint, "SourceBackedEntitlementEvent", None) is not None
        and joint.SourceBackedEntitlementEvent is getattr(v22, "SourceBackedEntitlementEvent", None)
        and getattr(joint, "canonical_bytes", None) is not None
        and joint.canonical_bytes is getattr(v22, "canonical_bytes", None)
        and getattr(ca, "cash", None) is joint,
        "R4_EXACT_V22_JOINT_AND_CA_DEPENDENCY_IDENTITY_REQUIRED")



_REGISTRY_METADATA_PATH = (REPO / "scripts/maintenance/research_registry.py").resolve()
_REGISTRY_METADATA_OLD_SHA = "2ac483477b6024c6468e0b7be3131b3032a4b85ef369bcf335e6c36265872b92"
_REGISTRY_METADATA_LIVE_SHA = "5b561c24f33b75bd43855bea5c2a30346443d20ff180b415618991fa1c6633b7"
_STATEFUL_FUSION_METADATA_PATH = (REPO / "scripts/research/a2/training/stateful_fusion.py").resolve()
_STATEFUL_FUSION_METADATA_OLD_SHA = "f83c8e09c0cf2856a61f98b51775cf6f382d70b6266878876ced1eba2754ae3b"
_STATEFUL_FUSION_METADATA_LIVE_SHA = "a13ce0f728852a76cd47fceaec67670ae0c9683f32b1e4443d1e7807d0c54904"
_REGISTRY_METADATA_SCOPE = None


class NonexecutingRegistryExecutionForbidden(ValueError):
    """The two frozen closure metadata sources may never execute business."""



_REGISTRY_CAPTURE_SCHEMA="FIXED_TWO_NONEXECUTED_IMPORT_CLOSURE_AS_OBSERVED_METADATA_R3"
_REGISTRY_CAPTURE_STAGES={'metadata_r3': 'FIXED214_METADATA_R3_NONEXECUTED_CLOSURE_CAPTURE', 'final_cold_r3': 'FIXED214_FINAL_COLD_R3_NONEXECUTED_CLOSURE_CAPTURE', 'risk_execute_r3': 'FIXED214_EXECUTE_R3_NONEXECUTED_CLOSURE_CAPTURE', 'metadata_r4': 'FIXED214_METADATA_R4_NONEXECUTED_CLOSURE_CAPTURE', 'final_cold_r4': 'FIXED214_FINAL_COLD_R4_NONEXECUTED_CLOSURE_CAPTURE', 'risk_execute_r4': 'FIXED214_EXECUTE_R4_NONEXECUTED_CLOSURE_CAPTURE', 'metadata_r4_calendar_r1': 'FIXED214_METADATA_R4_CALENDAR_R1_NONEXECUTED_CLOSURE_CAPTURE', 'final_cold_r4_calendar_r1': 'FIXED214_FINAL_COLD_R4_CALENDAR_R1_NONEXECUTED_CLOSURE_CAPTURE', 'risk_reboot_named_cold_r1': 'FIXED214_REBOOT_NAMED_COLD_R1_NONEXECUTED_CLOSURE_CAPTURE', 'risk_reboot_named_execute_r1': 'FIXED214_REBOOT_NAMED_EXECUTE_R1_NONEXECUTED_CLOSURE_CAPTURE', 'risk_reboot_named_cold_r2': 'FIXED214_SECOND_REBOOT_NAMED_COLD_R1_NONEXECUTED_CLOSURE_CAPTURE', 'risk_reboot_named_execute_r2': 'FIXED214_SECOND_REBOOT_NAMED_EXECUTE_R1_NONEXECUTED_CLOSURE_CAPTURE', 'risk_reboot_named_cold_r3': 'FIXED214_THIRD_REBOOT_NAMED_COLD_R1_NONEXECUTED_CLOSURE_CAPTURE', 'risk_reboot_named_execute_r3': 'FIXED214_THIRD_REBOOT_NAMED_EXECUTE_R1_NONEXECUTED_CLOSURE_CAPTURE', 'risk_environment_cold_r4': 'FIXED214_ENVIRONMENT_RECOVERY_COLD_R1_NONEXECUTED_CLOSURE_CAPTURE', 'risk_environment_repaired_cold_r4': 'FIXED214_ENVIRONMENT_RECOVERY_REPAIRED_COLD_R3_NONEXECUTED_CLOSURE_CAPTURE', 'risk_environment_execute_r4': 'FIXED214_ENVIRONMENT_RECOVERY_EXECUTE_R1_NONEXECUTED_CLOSURE_CAPTURE', 'post_risk_policy_cold_env_r1': 'FIXED214_POST_RISK_POLICY_ENV_COLD_R1_NONEXECUTED_CLOSURE_CAPTURE', 'post_risk_policy_execute_env_r1': 'FIXED214_POST_RISK_POLICY_ENV_EXECUTE_R1_NONEXECUTED_CLOSURE_CAPTURE', 'risk_pending_source_metadata_cold_r1': 'FIXED214_PENDING22_SOURCE_METADATA_COLD_R1_NONEXECUTED_CLOSURE_CAPTURE', 'risk_pending_firstentry_execute_r1': 'FIXED214_PENDING22_FIRST_ENTRY_R1_NONEXECUTED_CLOSURE_CAPTURE', 'policy_reboot_named_cold_r1': 'FIXED214_POLICY_REBOOT_NAMED_COLD_R1_NONEXECUTED_CLOSURE_CAPTURE', 'policy_reboot_named_execute_r1': 'FIXED214_POLICY_REBOOT_NAMED_EXECUTE_R1_NONEXECUTED_CLOSURE_CAPTURE', 'policy_zero_entry_cold_r1': 'FIXED214_POLICY_ZERO_ENTRY_COLD_R1_NONEXECUTED_CLOSURE_CAPTURE', 'policy_zero_entry_r1': 'FIXED214_POLICY_ZERO_ENTRY_EXECUTE_R1_NONEXECUTED_CLOSURE_CAPTURE', 'policy_zero_entry_cold_r2': 'FIXED214_POLICY_ZERO_ENTRY_COLD_R2_NONEXECUTED_CLOSURE_CAPTURE', 'policy_zero_entry_r2': 'FIXED214_POLICY_ZERO_ENTRY_EXECUTE_R2_NONEXECUTED_CLOSURE_CAPTURE', 'policy_zero_entry_cold_r3': 'FIXED214_POLICY_ZERO_ENTRY_COLD_R3_NONEXECUTED_CLOSURE_CAPTURE', 'policy_zero_entry_r3': 'FIXED214_POLICY_ZERO_ENTRY_EXECUTE_R3_NONEXECUTED_CLOSURE_CAPTURE', 'policy_zero_entry_cold_r4': 'FIXED214_POLICY_ZERO_ENTRY_COLD_R4_NONEXECUTED_CLOSURE_CAPTURE', 'policy_zero_entry_r4': 'FIXED214_POLICY_ZERO_ENTRY_EXECUTE_R4_NONEXECUTED_CLOSURE_CAPTURE', 'policy_checkpoint_cold_r5': 'FIXED214_POLICY_CHECKPOINT_COLD_R5_NONEXECUTED_CLOSURE_CAPTURE', 'policy_checkpoint_r5': 'FIXED214_POLICY_CHECKPOINT_EXECUTE_R5_NONEXECUTED_CLOSURE_CAPTURE'}

def _registry_metadata_capture_policy():
 return dict(schema="FIXED_TWO_NONEXECUTED_CLOSURE_CAPTURE_POLICY_R3",run=str(_SOURCE_CORRECTION_R4_RUN.resolve()),
  paths={"registry":dict(path=str(_REGISTRY_METADATA_PATH),original_logical_sha256=_REGISTRY_METADATA_OLD_SHA),
   "stateful_fusion":dict(path=str(_STATEFUL_FUSION_METADATA_PATH),original_logical_sha256=_STATEFUL_FUSION_METADATA_OLD_SHA)},
  source_purpose="NONEXECUTED_IMPORT_CLOSURE_METADATA",capture="OPAQUE_BYTES_ONCE_AT_SCOPE_ENTRY",
  current_after_capture="UNKNOWN",scientific_source_acceptance=False,
  deny="LIVE_AND_CUSTODY_OPEN_COMPILE_EXEC_AND_CANONICAL_IMPORT_DENY")

def _registry_metadata_capture_paths():
 state=_REGISTRY_METADATA_SCOPE
 return {Path(p).resolve() for p in state.get("capture_targets",{}).values()} if state and state.get("capture_mode") else set()

def _registry_metadata_capture_one(path,target):
 state=_REGISTRY_METADATA_SCOPE
 require(state is not None and state.get("capturing") is True and state["capture_targets"].get(Path(path).resolve())==Path(target).resolve(),
  "PRIVATE_FIXED_OPAQUE_CAPTURE_ONLY")
 import hashlib
 value=hashlib.sha256();count=0
 with open(path,"rb") as src,open(target,"xb") as dst:
  while True:
   block=src.read(1024*1024)
   if not block:break
   dst.write(block);value.update(block);count+=len(block)
 return dict(path=str(Path(target).resolve()),sha256=value.hexdigest()),count

def _registry_metadata_verify_capture_ref(value):
 state=_REGISTRY_METADATA_SCOPE
 require(state is not None and state.get("active") is True and state.get("capture_mode") is True,
  "ACTUAL_FIXED_CAPTURE_SCOPE_REQUIRED")
 require(isinstance(value,dict) and set(value)=={"path","sha256"} and value in [v["custody_ref"] for v in state["entries"].values()],
  "ONLY_EXACT_TWO_SCOPE_CAPTURE_REFS")
 require(sha(value["path"])==value["sha256"],"IMMUTABLE_OPAQUE_CAPTURE_CHANGED")
 return Path(value["path"]).resolve()

@contextmanager
def _registry_metadata_capture_scope(run,capture_stage,authority_ref):
 import sys
 from datetime import datetime,timezone
 global _REGISTRY_METADATA_SCOPE
 require(_REGISTRY_METADATA_SCOPE is None and Path(run).resolve()==_SOURCE_CORRECTION_R4_RUN.resolve()
  and _registry_capture_stage_stem(capture_stage) is not None,"FIXED_TWO_PATH_CAPTURE_STAGE_REQUIRED")
 authority_path=_correction_ref(authority_ref)
 require(authority_path==Path(run).resolve()/_RISK_NONEXECUTED_REFRESH_NAME,"EXACT_NEW_OBSERVER_AUTHORITY_PATH")
 authority=json.loads(authority_path.read_text(encoding="utf-8"))
 require(authority.get("schema") in (_RISK_NONEXECUTED_REFRESH_SCHEMA,_ACCOUNT_FROZEN_SCHEMA,_ENVIRONMENT_RECOVERY_SCHEMA) and authority.get("status")=="PASS",
  "EXPLICIT_NEW_METADATA_CAPTURE_AUTHORITY_REQUIRED")
 _risk_nonexecuted_refresh_history(authority)
 review_path=_correction_ref(authority["independent_review_ref"])
 require(review_path==Path(run).resolve()/"maintenance"/_RISK_NONEXECUTED_REFRESH_REVIEW_NAME,"EXACT_CAPTURE_POLICY_REVIEW_PATH")
 review=json.loads(review_path.read_text(encoding="utf-8"))
 require(review.get("schema")==(_ENVIRONMENT_RECOVERY_REVIEW_SCHEMA if authority["schema"]==_ENVIRONMENT_RECOVERY_SCHEMA else _ACCOUNT_FROZEN_REVIEW_SCHEMA if authority["schema"]==_ACCOUNT_FROZEN_SCHEMA else "FULL_SELECTOR_RISK_FIXED_TWO_NONEXECUTED_SOURCE_CAPTURE_INDEPENDENT_REVIEW_R2")
  and review.get("status")=="PASS" and review.get("research_id")==ID and review.get("independent_from_root_writer") is True
  and review.get("source_correction_payload_sha256")==digest({k:v for k,v in authority.items() if k not in {"status","independent_review_ref"}})
  and review.get("nonexecuted_capture_policy")==_registry_metadata_capture_policy()
  and review.get("fixed_two_registered_nonexecuted_paths_capture") is True
  and review.get("nonexecuted_source_execution_fence_proven") is True,"EXPLICIT_INDEPENDENT_CAPTURE_POLICY_REQUIRED")
 _registry_metadata_no_cached_modules()
 folder=Path(run).resolve()/"maintenance";stem=_registry_capture_stage_stem(capture_stage)
 targets={path:folder/(stem+"."+name+".opaque-source") for name,path in (("registry",_REGISTRY_METADATA_PATH),("stateful_fusion",_STATEFUL_FUSION_METADATA_PATH))}
 receipt=folder/(stem+".json")
 assert_safe_output_path(receipt,kind="backtest",paths=resolve(REPO))
 folder.mkdir(parents=True,exist_ok=True)
 require(not receipt.exists() and all(not p.exists() for p in targets.values()),"EXCLUSIVE_CAPTURE_NO_OVERWRITE")
 state=dict(active=True,run=Path(run).resolve(),capture_mode=True,capturing=True,capture_targets=targets,entries={})
 _REGISTRY_METADATA_SCOPE=state
 live=set(targets);custody=set(targets.values());blocked=live|custody
 def permitted_hash_or_capture():
  frame=sys._getframe(1)
  codes=(_registry_metadata_capture_one.__code__,_registry_metadata_verify_capture_ref.__code__)
  while frame:
   if frame.f_code in codes:return True
   frame=frame.f_back
  return False
 def audit(event,args):
  if not state["active"]:return
  import os
  if event=="import" and args and args[0] in ("scripts.maintenance.research_registry","ustq_inventory_registry","scripts.research.a2.training.stateful_fusion"):
   raise NonexecutingRegistryExecutionForbidden("NONEXECUTING_CAPTURE_IMPORT_FORBIDDEN")
  if event in ("compile","exec") and args:
   filename=args[1] if event=="compile" and len(args)>1 else getattr(args[0],"co_filename",None)
   if filename and Path(filename).resolve() in blocked:
    raise NonexecutingRegistryExecutionForbidden("NONEXECUTING_CAPTURE_CODE_FORBIDDEN")
  if event=="open" and args and isinstance(args[0],(str,bytes)):
   if Path(os.fsdecode(args[0])).resolve() in blocked and not permitted_hash_or_capture():
    raise NonexecutingRegistryExecutionForbidden("NONEXECUTING_CAPTURE_CONTENT_READ_FORBIDDEN")
 try:
  sys.addaudithook(audit)
  for name,path,old in (("registry",_REGISTRY_METADATA_PATH,_REGISTRY_METADATA_OLD_SHA),("stateful_fusion",_STATEFUL_FUSION_METADATA_PATH,_STATEFUL_FUSION_METADATA_OLD_SHA)):
   value,count=_registry_metadata_capture_one(path,targets[path])
   state["entries"][name]=dict(original_logical_ref=dict(path=str(path),sha256=old),
    observed_live_ref=dict(path=str(path),sha256=value["sha256"]),custody_ref=value,bytes=count,
    captured_utc=datetime.now(timezone.utc).isoformat(),exact_at_capture=True,current_after_capture_unknown=True,
    source_purpose="NONEXECUTED_IMPORT_CLOSURE_METADATA",source_execution_authorized=False,
    original_actual_bytes_status="UNKNOWN_ACTUAL_OLD_BYTES_NOT_FOUND")
  state["capturing"]=False
  state["observation"]=dict(schema=_REGISTRY_CAPTURE_SCHEMA,run=str(Path(run).resolve()),capture_stage=capture_stage,entries=state["entries"],
   capture_policy=_registry_metadata_capture_policy())
  with receipt.open("x",encoding="utf-8") as f:json.dump(state["observation"],f,indent=2,sort_keys=True,allow_nan=False);f.write("\n")
  state["receipt_ref"]=dict(path=str(receipt),sha256=sha(receipt))
  _registry_metadata_assert_fence()
  yield _registry_metadata_observation()
 finally:
  state["capturing"]=False;state["active"]=False;_REGISTRY_METADATA_SCOPE=None


def _registry_metadata_fixed_sources():
    state=_REGISTRY_METADATA_SCOPE
    if state and state.get("capture_mode"):
        return {Path(v["original_logical_ref"]["path"]).resolve():(v["original_logical_ref"]["sha256"],v["observed_live_ref"]["sha256"]) for v in state["entries"].values()}
    return {_REGISTRY_METADATA_PATH: (_REGISTRY_METADATA_OLD_SHA, _REGISTRY_METADATA_LIVE_SHA),
        _STATEFUL_FUSION_METADATA_PATH: (_STATEFUL_FUSION_METADATA_OLD_SHA, _STATEFUL_FUSION_METADATA_LIVE_SHA)}


def _registry_metadata_observation():
    state=_REGISTRY_METADATA_SCOPE
    if state and state.get("capture_mode"):
        require(state.get("active") is True and "receipt_ref" in state,"COMPLETE_SCOPE_CAPTURE_REQUIRED")
        return dict(state["observation"],capture_receipt_ref=state["receipt_ref"])
    return dict(schema="FIXED_TWO_NONEXECUTED_IMPORT_CLOSURE_METADATA_R2",
        run=str(_SOURCE_CORRECTION_R4_RUN.resolve()),
        entries={name: dict(original_logical_ref=dict(path=str(path), sha256=old),
            current_nonexecuted_ref=dict(path=str(path), sha256=live),
            original_actual_bytes_status="UNKNOWN_ACTUAL_OLD_BYTES_NOT_FOUND",
            source_purpose="NONEXECUTED_IMPORT_CLOSURE_METADATA",
            fence_policy="EXACT_PHYSICAL_PATH_EXEC_AND_CANONICAL_IMPORT_DENY")
            for name, path, old, live in (
                ("registry", _REGISTRY_METADATA_PATH, _REGISTRY_METADATA_OLD_SHA, _REGISTRY_METADATA_LIVE_SHA),
                ("stateful_fusion", _STATEFUL_FUSION_METADATA_PATH, _STATEFUL_FUSION_METADATA_OLD_SHA, _STATEFUL_FUSION_METADATA_LIVE_SHA))})


def _registry_metadata_no_cached_modules():
    import sys
    from types import FunctionType,MethodType
    exact_paths={_REGISTRY_METADATA_PATH,_STATEFUL_FUSION_METADATA_PATH}|_registry_metadata_capture_paths()
    for name,module in tuple(sys.modules.items()):
        filename=getattr(module,"__file__",None)
        require(name not in ("scripts.maintenance.research_registry","ustq_inventory_registry","scripts.research.a2.training.stateful_fusion")
            and (not filename or Path(filename).resolve() not in exact_paths),"NONEXECUTING_CLOSURE_SOURCE_ALREADY_LOADED:"+name)
        for value in tuple(getattr(module,"__dict__",{}).values()):
            code=value.__code__ if isinstance(value,(FunctionType,MethodType)) else None
            require(code is None or Path(code.co_filename).resolve() not in exact_paths,"NONEXECUTING_CLOSURE_FUNCTION_ALREADY_LOADED:"+name)


def _registry_metadata_assert_fence():
    state = _REGISTRY_METADATA_SCOPE
    require(state is not None and state.get("active") is True
        and state.get("run") == _SOURCE_CORRECTION_R4_RUN.resolve(),
        "FIXED_REGISTRY_METADATA_FENCE_SCOPE_REQUIRED")
    _registry_metadata_no_cached_modules()
    if state.get("capture_mode"):
        require(set(state["entries"])=={"registry","stateful_fusion"} and state.get("capturing") is False,"COMPLETE_TWO_CAPTURE_MEMBERS_REQUIRED")
        for value in state["entries"].values():_registry_metadata_verify_capture_ref(value["custody_ref"])
        for path in {_REGISTRY_METADATA_PATH,_STATEFUL_FUSION_METADATA_PATH}|_registry_metadata_capture_paths():
            for probe in (lambda: open(path,"rb"),lambda:compile("pass",str(path),"exec")):
                try:probe()
                except NonexecutingRegistryExecutionForbidden:continue
                require(False,"ACTUAL_TWO_CAPTURE_READ_COMPILE_FENCE_NOT_LIVE:"+str(path))
        return True
    for path, (_, live) in _registry_metadata_fixed_sources().items():
        require(sha(path) == live, "FIXED_CURRENT_NONEXECUTED_CLOSURE_BYTES_REQUIRED:" + str(path))
        try:
            exec(compile("pass", str(path), "exec"), {})
        except NonexecutingRegistryExecutionForbidden:
            continue
        require(False, "ACTUAL_CLOSURE_EXEC_AUDIT_HOOK_NOT_LIVE:" + str(path))
    return True


@contextmanager
def nonexecuting_registry_metadata_scope(run,capture_stage=None,authority_ref=None):
    """This one run may observe two exact closure hashes while denying execution."""
    import sys
    global _REGISTRY_METADATA_SCOPE
    if capture_stage is not None:
        with _registry_metadata_capture_scope(run,capture_stage,authority_ref) as observation:yield observation
        return
    require(authority_ref is None,"NO_CAPTURE_AUTHORITY_IN_LEGACY_FIXED_PIN_SCOPE")
    require(_REGISTRY_METADATA_SCOPE is None and Path(run).resolve() == _SOURCE_CORRECTION_R4_RUN.resolve(),
        "FIXED_SINGLE_REGISTRY_METADATA_SCOPE_REQUIRED")
    _registry_metadata_no_cached_modules()
    exact_paths = _registry_metadata_fixed_sources()
    for path, (_, live) in exact_paths.items():
        require(sha(path) == live, "FIXED_CURRENT_NONEXECUTED_CLOSURE_BYTES_REQUIRED:" + str(path))
    state = dict(active=True, run=Path(run).resolve())
    def audit(event, args):
        if state["active"] and event == "import" and args and args[0] in (
                "scripts.maintenance.research_registry", "ustq_inventory_registry",
                "scripts.research.a2.training.stateful_fusion"):
            raise NonexecutingRegistryExecutionForbidden("NONEXECUTING_CLOSURE_IMPORT_FORBIDDEN")
        if state["active"] and event == "exec" and args:
            filename = getattr(args[0], "co_filename", None)
            if filename and Path(filename).resolve() in exact_paths:
                raise NonexecutingRegistryExecutionForbidden("NONEXECUTING_CLOSURE_EXEC_FORBIDDEN")
    _REGISTRY_METADATA_SCOPE = state
    sys.addaudithook(audit)
    try:
        _registry_metadata_assert_fence()
        yield _registry_metadata_observation()
    finally:
        state["active"] = False
        _REGISTRY_METADATA_SCOPE = None


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

def _source_r5_history(data):
 fields={"schema","status","research_id","design_ref","original_sources","replacements",
  "independent_review_ref","prior_source_configuration_ref","prior_controller_custody_ref","source_transport_ref"}
 require(data["prior_r4_configuration_ref"]==_SOURCE_R5_OLD_FORMAL_REF
  and data["prior_r4_transport_ref"]==_SOURCE_R5_OLD_TRANSPORT_REF
  and data["prior_runtime_custody_refs"]==_SOURCE_R5_CUSTODY_REFS
  and data["human_authorization_ref"]==_SOURCE_R5_AUTH_REF
  and data["nonexecuted_live_custody_observation_ref"]==_SOURCE_R5_CAPTURE_REF,
  "EXACT_R5_ORIGINAL_R4_AND_CAPTURE_HISTORY_REQUIRED")
 for value in (_SOURCE_R5_OLD_FORMAL_REF,_SOURCE_R5_OLD_TRANSPORT_REF,_SOURCE_R5_CAPTURE_REF,_SOURCE_R5_AUTH_REF,*_SOURCE_R5_CUSTODY_REFS.values()):
  _correction_ref(value)
 prior=json.loads(Path(_SOURCE_R5_OLD_FORMAL_REF["path"]).read_text(encoding="utf-8"))
 require(set(prior)==fields and prior["schema"]=="FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R4"
  and prior["status"]=="PASS" and prior["research_id"]==ID,"IMMUTABLE_ORIGINAL_R4_REQUIRED")
 for key in ("research_id","design_ref","original_sources","prior_source_configuration_ref","prior_controller_custody_ref"):
  require(data[key]==prior[key],"R5_IMMUTABLE_FORMAL_HISTORY_CHANGED:"+key)
 extra={str((REPO/_ENVIRONMENT_RECOVERY_WORKFLOW).resolve())} if data.get("schema")==_ENVIRONMENT_RECOVERY_SCHEMA else set()
 require(set(data["replacements"])==set(prior["replacements"])|extra,"R5_ORIGINAL_FIVE_PLUS_FIXED_ENVIRONMENT_WORKFLOW_ONLY")
 if extra:_fixed_environment_workflow_source(data)
 controller=str((REPO/_SOURCE_CORRECTION_PATHS[0]).resolve())
 for key,value in prior["replacements"].items():
  require(all(data["replacements"][key][k]==value[k] for k in ("original_ref","custody_ref"))
   and (key==controller or data["replacements"][key]["runtime_ref"]==value["runtime_ref"]),
   "R5_ORIGINAL_CUSTODY_OR_ACTUAL_SNAPSHOT_CHANGED:"+key)
 require(prior["replacements"][controller]["runtime_ref"]==dict(path=controller,sha256=_SOURCE_R5_CUSTODY_REFS["controller"]["sha256"]),
  "ACTUAL_R4_8EC_IS_HISTORICAL_NOT_CURRENT_REQUIRED")
 return prior

def _source_r5_assert_live_fence(data,transport):
 import traceback
 owner=data["transport_owner_ref"]
 path=_correction_ref(owner)
 require(path==(REPO/"scripts/research/a2/training/full_selector_alpha_reboot_recovery.py").resolve(),
  "EXACT_CURRENT_R5_TRANSPORT_OWNER_PATH_REQUIRED")
 def denied(operation):
  try:
   operation()
  except Exception as exc:
   frames=traceback.extract_tb(exc.__traceback__)
   require(type(exc).__name__=="NonexecutingTransportSourceForbidden"
    and any(Path(frame.filename).resolve()==path and frame.name=="audit" for frame in frames),
    "ACTUAL_R5_TRANSPORT_DENIAL_ORIGIN_REQUIRED")
  else:
   require(False,"R5_LIVE_SOURCE_FENCE_NOT_ACTIVE")
 for entry in transport["entries"].values():
  live=entry["live_observation_ref"]["path"]
  denied(lambda live=live:open(live,"rb"))
  denied(lambda live=live:compile("pass",live,"exec"))
 return True



_RISK_NONEXECUTED_REFRESH_SCHEMA="FULL_SELECTOR_RISK_FIXED_TWO_NONEXECUTED_SOURCE_OBSERVER_CAPTURE_R2"
_RISK_NONEXECUTED_REFRESH_NAME="ENGINEERING_RISK_NONEXECUTED_SOURCE_REFRESH_R1.json"
_RISK_NONEXECUTED_REFRESH_REVIEW_NAME="FIXED214_NONEXECUTED_SOURCE_REFRESH_INDEPENDENT_REVIEW_R1.json"
_RISK_NONEXECUTED_REFRESH_EXTRA_FIELDS={"prior_r5_configuration_ref","prior_r5_current_runtime_custody_refs"}
_RISK_NONEXECUTED_PRIOR_R5_REF=dict(path=str(_SOURCE_R5_RUN/"ENGINEERING_SOURCE_CORRECTION_R5.json"),sha256="c3bff6e808e73155f34f74928f28e041e1ee6107fb9b561984d02642e7766a8d")
_RISK_NONEXECUTED_PRIOR_RUNTIME={
 "controller":dict(path=str((REPO/"scripts/research/a2/training/selector_full_fixed_policy.py").resolve()),sha256="c06c16288e939b58e1a78cfbe196996c196c6c7d1f2c65716833f95e0d48442e"),
 "transport_owner":dict(path=str((REPO/"scripts/research/a2/training/full_selector_alpha_reboot_recovery.py").resolve()),sha256="343a867113d361ebf3956ebcc5b66f6b4c4fb4e5a88e083e99b44e059de2aca9")}
_RISK_NONEXECUTED_RUNTIME_CUSTODY={
 key:dict(path=str(_SOURCE_R5_RUN/"source_corrections/FIXED214_NONEXECUTED_METADATA_REFRESH_R1"/
 (("controller" if key=="controller" else "transport_owner")+"."+value["sha256"]+".before.py")),sha256=value["sha256"])
 for key,value in _RISK_NONEXECUTED_PRIOR_RUNTIME.items()}

def _risk_nonexecuted_refresh_history(data):
 """One current observer revision; prior c3/c06/343 remain immutable historical bytes."""
 require(data["prior_r5_configuration_ref"]==_RISK_NONEXECUTED_PRIOR_R5_REF
  and data["prior_r5_current_runtime_custody_refs"]==_RISK_NONEXECUTED_RUNTIME_CUSTODY,
  "FIXED_PRIOR_R5_AND_CLOSED_TWO_ACTUAL_CURRENT_CUSTODIES_REQUIRED")
 prior_path=_correction_ref(data["prior_r5_configuration_ref"])
 require(prior_path==_SOURCE_R5_RUN/"ENGINEERING_SOURCE_CORRECTION_R5.json","EXACT_UNCHANGED_PRIOR_R5_PATH_REQUIRED")
 prior=json.loads(prior_path.read_text(encoding="utf-8"))
 base_fields={"schema","status","research_id","design_ref","original_sources","replacements","independent_review_ref",
  "prior_source_configuration_ref","prior_controller_custody_ref","source_transport_ref"}|_SOURCE_R5_EXTRA_FIELDS
 require(set(prior)==base_fields and prior["schema"]=="FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R5"
  and prior["status"]=="PASS" and prior["research_id"]==ID,"ACTUAL_IMMUTABLE_C3_R5_REQUIRED")
 for key in base_fields-{"schema","status","independent_review_ref","replacements","transport_owner_ref"}:
  require(data[key]==prior[key],"ONLY_REGISTERED_NONEXECUTED_OBSERVER_PROVENANCE_DIFF_REQUIRED:"+key)
 extra={str((REPO/_ENVIRONMENT_RECOVERY_WORKFLOW).resolve())} if data.get("schema")==_ENVIRONMENT_RECOVERY_SCHEMA else set()
 require(set(data["replacements"])==set(prior["replacements"])|extra,"ORIGINAL_FIVE_PLUS_FIXED_ENVIRONMENT_WORKFLOW_ONLY")
 if extra:_fixed_environment_workflow_source(data)
 controller=str((REPO/"scripts/research/a2/training/selector_full_fixed_policy.py").resolve())
 for key,item in prior["replacements"].items():
  if key==controller:
   require(data["replacements"][key]["original_ref"]==item["original_ref"]
    and data["replacements"][key]["custody_ref"]==item["custody_ref"]
    and Path(data["replacements"][key]["runtime_ref"]["path"]).resolve()==Path(controller),
    "ORIGINAL_CONTROLLER_SCIENCE_CUSTODY_UNCHANGED_REQUIRED")
  else:require(data["replacements"][key]==item,"FOUR_ORIGINAL_ACTUAL_EXECUTION_SNAPSHOTS_UNCHANGED_REQUIRED")
 require(prior["replacements"][controller]["runtime_ref"]==_RISK_NONEXECUTED_PRIOR_RUNTIME["controller"]
  and prior["transport_owner_ref"]==_RISK_NONEXECUTED_PRIOR_RUNTIME["transport_owner"],
  "PRIOR_R5_USED_REAL_C06_AND_343_NOT_CURRENT_REQUIRED")
 for key,ref in data["prior_r5_current_runtime_custody_refs"].items():
  path=_correction_ref(ref);require(path==Path(_RISK_NONEXECUTED_RUNTIME_CUSTODY[key]["path"]).resolve()
   and path!=Path(_RISK_NONEXECUTED_PRIOR_RUNTIME[key]["path"]).resolve(),"REAL_DISTINCT_PRIOR_RUNTIME_BYTE_CUSTODY_REQUIRED")
 return prior


_ENVIRONMENT_RECOVERY_SCHEMA="FULL_SELECTOR_FIXED_TWO_CAPTURE_ENVIRONMENT_RECOVERY_SOURCE_R4"
_ENVIRONMENT_RECOVERY_REVIEW_SCHEMA="FULL_SELECTOR_ENVIRONMENT_RISK_SOURCE_INDEPENDENT_REVIEW_R1"
_ENVIRONMENT_RECOVERY_WORKFLOW="scripts/research/a2/training/full_selector_workflow.py"
_ENVIRONMENT_RECOVERY_WORKFLOW_SHA="3e9764be31de959f5ad04029420c6a771f5d6c96ac7c8301f1656496270aec8f"

def _fixed_environment_workflow_source(data):
    require(data.get("schema")==_ENVIRONMENT_RECOVERY_SCHEMA,"FIXED_ENVIRONMENT_SOURCE_SCHEMA")
    value=data["environment_recovery_manifest_ref"]
    require(isinstance(value,dict) and set(value)=={"path","sha256"},"CLOSED_ENVIRONMENT_MANIFEST_REF")
    path=_correction_ref(value)
    require(path==Path("D:/us-tech-quant-cache/V24/C_SELECTOR/FULL_SELECTOR_FIXED_POLICY_FAST_R1/proposals/FIXED214_ENVIRONMENT_REPLAY_MANIFEST_CANDIDATE_R1.json").resolve()
        and value["sha256"]=="9ddb8ae9164ad4d97fb62db1a47f5aad7a0212fe1079bc3d1a840b42c400df6e","EXACT_PREPARED_ENVIRONMENT_MANIFEST")
    manifest=json.loads(path.read_text(encoding="utf-8-sig"))
    require(manifest.get("schema")=="FULL_SELECTOR_FIXED214_ENVIRONMENT_REPLAY_MANIFEST_R1" and manifest.get("research_id")==ID
        and set(manifest.get("groups",{}))=={"RISK_REFRESH|2021-04-09","RISK_REFRESH|2021-11-03","RISK_REFRESH|2022-05-04","RISK_REFRESH|2025-09-02"}
        and manifest.get("scientific_failed_trial_retries")==0 and manifest.get("new_scientific_nodes_authorized") is False
        and manifest.get("risk_total_entry_cap")==15194 and manifest.get("worst_case_paid_after_this_bounded_phase")==7692,
        "ONLY_FIXED_FOUR_ENVIRONMENT_GROUPS_WITH_ORIGINAL_BUDGET")
    human=manifest["human_authorization_ref"];_correction_ref(human)
    require(human["sha256"]=="c06815fccd5b8e6a9294f24cd7a629df745363243a300b85ad524bb6682863c5","DIRECT_HUMAN_ENVIRONMENT_SOURCE_AUTHORITY")
    workflow=str((REPO/_ENVIRONMENT_RECOVERY_WORKFLOW).resolve());item=data["replacements"][workflow]
    require(item["original_ref"]==dict(path=workflow,sha256="4e989ebb783ce4b7c0f231417afee1e1357a6b38c94f78ddd60801c7ad72160d")
        and item["runtime_ref"]==dict(path=workflow,sha256=_ENVIRONMENT_RECOVERY_WORKFLOW_SHA),"FIXED_ORIGINAL_AND_RECOVERY_WORKFLOW_PINS")
    return manifest

_ACCOUNT_FROZEN_SCHEMA='FULL_SELECTOR_RISK_FIXED_TWO_NONEXECUTED_CAPTURE_ORIGINAL_ACCOUNT_TRANSPORT_R3'
_ACCOUNT_FROZEN_REVIEW_SCHEMA='FULL_SELECTOR_RISK_FIXED_TWO_CAPTURE_ORIGINAL_ACCOUNT_TRANSPORT_INDEPENDENT_REVIEW_R3'
_ACCOUNT_FROZEN_TRANSPORT_REF={'path': 'D:\\us-tech-quant-cache\\V24\\C_SELECTOR\\FULL_SELECTOR_FIXED_POLICY_FAST_R1\\proposals\\FIXED214_FROZEN_ACCOUNT_SOURCE_TRANSPORT_R4.json', 'sha256': '7d9f8eae5415cd00d4a2bd3ed17d8632685f9955324521d743324fa6dec90f5f'}
_ACCOUNT_FROZEN_NAMES=("scripts.research.a2.evaluation.continuous_research_account","scripts.research.a2.data.full_selector_account_inputs")

def _frozen_account_loaded_sources(data):
    import sys,inspect
    require(data.get("schema") in (_ACCOUNT_FROZEN_SCHEMA,_ENVIRONMENT_RECOVERY_SCHEMA) and data.get("frozen_account_source_transport_ref")==_ACCOUNT_FROZEN_TRANSPORT_REF,"EXPLICIT_CLOSED19_ORIGINAL_ACCOUNT_TRANSPORT_REQUIRED")
    doc=json.loads(_correction_ref(_ACCOUNT_FROZEN_TRANSPORT_REF).read_text(encoding="utf-8"))
    require(set(doc)=={"schema","research_id","scope","entries","recovery_receipt_ref","permission_ref","module_file_semantics"} and doc["schema"]=="FULL_SELECTOR_FIXED_TWO_ORIGINAL_ACCOUNT_SOURCE_TRANSPORT_R4" and doc["research_id"]==ID and set(doc["entries"])==set(_ACCOUNT_FROZEN_NAMES) and doc["scope"]=="EXACT_ORIGINAL_TWO_FROZEN_BYTES_NO_SCIENCE_CHANGE" and doc["permission_ref"]==_SOURCE_R5_AUTH_REF,"CLOSED_TWO_FROZEN_ACCOUNT_TRANSPORT")
    _correction_ref(doc["recovery_receipt_ref"]);_correction_ref(doc["permission_ref"])
    review=json.loads(_correction_ref(data["independent_review_ref"]).read_text(encoding="utf-8"))
    require(review.get("frozen_account_source_transport_ref")==_ACCOUNT_FROZEN_TRANSPORT_REF and review.get("original_two_account_snapshots_exact") is True and review.get("other_92_current_live_sources_exact") is False,"INDEPENDENT_FROZEN_ACCOUNT_REVIEW_REQUIRED")
    result={}
    for name,item in doc["entries"].items():
        require(set(item)=={"original_logical_ref","actual_snapshot_ref"},"CLOSED_TWO_ACCOUNT_ENTRY")
        logical=item["original_logical_ref"];actual=item["actual_snapshot_ref"];snapshot=_correction_ref(actual)
        require(logical["sha256"]==actual["sha256"] and snapshot!=Path(logical["path"]).resolve(),"ORIGINAL_ACCOUNT_BYTES_REQUIRED")
        m=sys.modules.get(name);spec=getattr(m,"__spec__",None)
        require(m is not None and m.__name__==name and Path(m.__file__).resolve()==Path(logical["path"]).resolve() and Path(getattr(spec,"origin","")).resolve()==snapshot and Path(getattr(getattr(spec,"loader",None),"path","")).resolve()==snapshot and getattr(m,"__loader__",None) is getattr(spec,"loader",None) and getattr(m,"__frozen_account_transport_ref__",None)==_ACCOUNT_FROZEN_TRANSPORT_REF,"LOGICAL_FILE_ACTUAL_SPEC_LOADER_REQUIRED")
        own=[v for v in vars(m).values() if inspect.isfunction(v) and v.__module__==name]
        require(own and all(Path(v.__code__.co_filename).resolve()==snapshot for v in own),"FROZEN_ACCOUNT_FUNCTION_ORIGINS_REQUIRED")
        for operation in (lambda:open(logical["path"],"rb"),lambda:compile("pass",logical["path"],"exec")):
            try:operation()
            except ValueError as error:require(str(error)=="FIXED_ACCOUNT_LIVE_SOURCE_FORBIDDEN","FROZEN_ACCOUNT_FENCE_REQUIRED")
            else:require(False,"FROZEN_ACCOUNT_FENCE_INACTIVE")
        result[str(Path(logical["path"]).resolve())]=item
    require(sys.modules[_ACCOUNT_FROZEN_NAMES[1]].account is sys.modules[_ACCOUNT_FROZEN_NAMES[0]] and Path(sys.modules[_ACCOUNT_FROZEN_NAMES[1]].REPO).resolve()==REPO.resolve(),"SAME_FROZEN_ACCOUNT_OBJECT_AND_LOGICAL_REPO_REQUIRED")
    return result

def _source_correction_r4(path, data):
    """One run's finite actual snapshot transport, preserving immutable R1/R2."""
    fields = {"schema", "status", "research_id", "design_ref", "original_sources", "replacements",
        "independent_review_ref", "prior_source_configuration_ref", "prior_controller_custody_ref",
        "source_transport_ref"}
    is_environment_recovery=data.get("schema")==_ENVIRONMENT_RECOVERY_SCHEMA
    is_account_transport=data.get("schema") in (_ACCOUNT_FROZEN_SCHEMA,_ENVIRONMENT_RECOVERY_SCHEMA)
    is_refresh = data.get("schema") in (_RISK_NONEXECUTED_REFRESH_SCHEMA,_ACCOUNT_FROZEN_SCHEMA,_ENVIRONMENT_RECOVERY_SCHEMA)
    is_r5 = data.get("schema") in ("FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R5",_RISK_NONEXECUTED_REFRESH_SCHEMA,_ACCOUNT_FROZEN_SCHEMA,_ENVIRONMENT_RECOVERY_SCHEMA)
    active_fields = (fields | _SOURCE_R5_EXTRA_FIELDS | (_RISK_NONEXECUTED_REFRESH_EXTRA_FIELDS if is_refresh else set()) | ({"frozen_account_source_transport_ref"} if is_account_transport else set())) if is_r5 else fields
    if is_environment_recovery:active_fields=active_fields|{"environment_recovery_manifest_ref"}
    require(set(data) == active_fields and data.get("schema") == (_ENVIRONMENT_RECOVERY_SCHEMA if is_environment_recovery else _ACCOUNT_FROZEN_SCHEMA if is_account_transport else _RISK_NONEXECUTED_REFRESH_SCHEMA if is_refresh else "FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R5" if is_r5 else "FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R4")
        and data.get("status") == "PASS" and data.get("research_id") == ID,
        "CLOSED_FINITE_SOURCE_R4_CONFIGURATION_REQUIRED")
    run = _SOURCE_CORRECTION_R4_RUN.resolve()
    require(path == run / (_RISK_NONEXECUTED_REFRESH_NAME if is_refresh else _SOURCE_R5_FORMAL_NAME if is_r5 else _SOURCE_CORRECTION_R4_NAME), "FIXED_SOURCE_R4_TASK_PATH_REQUIRED")
    assert_safe_output_path(run, kind="backtest", paths=resolve(REPO))
    design_path = _correction_ref(data["design_ref"])
    require(design_path == run / "DESIGN_FREEZE.json"
        and data["design_ref"]["sha256"] == _SOURCE_CORRECTION_R4_DESIGN_SHA,
        "IMMUTABLE_ORIGINAL_R4_DESIGN_REQUIRED")
    design = json.loads(design_path.read_text(encoding="utf-8"))
    require(design.get("research_id") == ID and data["original_sources"] == design["sources"]
        and len(design["sources"]) == 99, "EXACT_ORIGINAL_99_SOURCE_AUTHORITY_REQUIRED")
    if is_refresh:
        _risk_nonexecuted_refresh_history(data)
    if is_r5:
        _source_r5_history(data)
    prior_ref = data["prior_source_configuration_ref"]
    prior_path = _correction_ref(prior_ref)
    require(prior_path == run / _SOURCE_CORRECTION_R2_NAME
        and prior_ref["sha256"] == _SOURCE_CORRECTION_R4_PRIOR_R2_SHA,
        "IMMUTABLE_PRIOR_SOURCE_R2_REQUIRED")
    prior = json.loads(prior_path.read_text(encoding="utf-8"))
    require(set(prior) == fields - {"source_transport_ref"}
        and prior.get("schema") == "FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R2"
        and prior.get("status") == "PASS" and prior.get("research_id") == ID
        and prior["design_ref"] == data["design_ref"] and prior["original_sources"] == design["sources"]
        and set(prior["replacements"]) == {str((REPO / x).resolve()) for x in _SOURCE_CORRECTION_R2_PATHS},
        "EXACT_ORIGINAL_SOURCE_R2_HISTORY_REQUIRED")
    # Historical runtime_refs stay logical metadata; do not recheck changed live files as old runtime bytes.
    r1_path = _correction_ref(prior["prior_source_configuration_ref"])
    require(r1_path == run / _SOURCE_CORRECTION_NAME
        and prior["prior_source_configuration_ref"]["sha256"] == _SOURCE_CORRECTION_R1_SHA,
        "IMMUTABLE_PRIOR_SOURCE_R1_REQUIRED")
    old_prior_custody = _correction_ref(prior["prior_controller_custody_ref"])
    require(prior["prior_controller_custody_ref"]["sha256"] == _SOURCE_CORRECTION_PRIOR_CONTROLLER_SHA
        and old_prior_custody != (REPO / _SOURCE_CORRECTION_PATHS[0]).resolve()
        and (old_prior_custody.is_relative_to(resolve(REPO).cache_root) or old_prior_custody.is_relative_to(run)),
        "EXACT_PRIOR_R1_CONTROLLER_CUSTODY_REQUIRED")
    prior_review_path = _correction_ref(prior["independent_review_ref"])
    prior_review = json.loads(prior_review_path.read_text(encoding="utf-8"))
    prior_payload = {k: prior[k] for k in fields - {"status", "independent_review_ref", "source_transport_ref"}}
    require(prior["independent_review_ref"]["sha256"] == _SOURCE_CORRECTION_R4_PRIOR_REVIEW_SHA
        and prior_review.get("status") == "PASS" and prior_review.get("independent_from_root_writer") is True
        and prior_review.get("source_correction_payload_sha256") == digest(prior_payload)
        and all(prior_review.get(k) is True for k in ("scientific_contract_unchanged", "other_95_sources_exact",
            "prior_R1_history_preserved", "finite_four_source_scope")), "IMMUTABLE_PRIOR_R2_REVIEW_REQUIRED")
    controller = str((REPO / _SOURCE_CORRECTION_PATHS[0]).resolve())
    old_controller = _correction_ref(data["prior_controller_custody_ref"])
    require(data["prior_controller_custody_ref"]["sha256"] == _SOURCE_CORRECTION_R4_PRIOR_CONTROLLER_SHA
        == prior["replacements"][controller]["runtime_ref"]["sha256"]
        and old_controller != Path(controller)
        and (old_controller.is_relative_to(resolve(REPO).cache_root) or old_controller.is_relative_to(run)),
        "EXACT_PRIOR_EC6_CONTROLLER_CUSTODY_REQUIRED")
    transport_path = _correction_ref(data["source_transport_ref"])
    require(transport_path == run / "continuation" / (_SOURCE_R5_TRANSPORT_NAME if is_r5 else _SOURCE_CORRECTION_R4_TRANSPORT_NAME),
        "FIXED_SOURCE_R4_TRANSPORT_PATH_REQUIRED")
    transport = json.loads(transport_path.read_text(encoding="utf-8"))
    require(set(transport) == ({"schema", "research_id", "prior_source_configuration_ref", "entries", "scope"} | _SOURCE_R5_TRANSPORT_EXTRA_FIELDS if is_r5 else {"schema", "research_id", "prior_source_configuration_ref", "entries", "scope"})
        and transport.get("schema") == ("FULL_SELECTOR_ALPHA_REBOOT_EXACT_SOURCE_TRANSPORT_R5" if is_r5 else "FULL_SELECTOR_ALPHA_REBOOT_EXACT_SOURCE_TRANSPORT_R4")
        and transport.get("research_id") == ID and transport["prior_source_configuration_ref"] == prior_ref
        and transport["scope"] == "EXACT_APPROVED_RUNTIME_BYTES_ONLY"
        and set(transport["entries"]) == set(_SOURCE_CORRECTION_R4_SNAPSHOTS),
        "CLOSED_FOUR_ACTUAL_SOURCE_TRANSPORT_REQUIRED")
    if is_r5:
        require(transport["prior_r4_transport_ref"] == _SOURCE_R5_OLD_TRANSPORT_REF
            and transport["human_authorization_ref"] == _SOURCE_R5_AUTH_REF
            and transport["nonexecuted_live_custody_observation_ref"] == _SOURCE_R5_CAPTURE_REF,
            "R5_EXACT_TRANSPORT_HISTORY_AND_CAPTURE_REQUIRED")
        _source_r5_assert_live_fence(data, transport)
        require(_REGISTRY_METADATA_SCOPE is not None, "R5_BOTH_REGISTRY_FENCES_REQUIRED")
    replacements = data["replacements"]
    exact_paths = {controller} | {str((REPO / x[0]).resolve()) for x in _SOURCE_CORRECTION_R4_SNAPSHOTS.values()}
    if is_environment_recovery:
        exact_paths.add(str((REPO/_ENVIRONMENT_RECOVERY_WORKFLOW).resolve()))
        _fixed_environment_workflow_source(data)
    require(set(replacements) == exact_paths, "FIXED_SIX_ENVIRONMENT_ORIGINAL_FIVE_SOURCE_CORRECTIONS_REQUIRED")
    frozen_accounts=_frozen_account_loaded_sources(data) if is_account_transport else {}
    registry_metadata_active = _REGISTRY_METADATA_SCOPE is not None
    registry_capture_active=registry_metadata_active and _REGISTRY_METADATA_SCOPE.get("capture_mode") is True
    require(registry_capture_active==is_refresh,"CAPTURE_ONLY_EXPLICIT_NEW_AUTHORITY_NOT_LEGACY_R5")
    if registry_metadata_active:
        _registry_metadata_assert_fence()
    for source_path, expected in design["sources"].items():
        if source_path not in replacements:
            if str(Path(source_path).resolve()) in frozen_accounts:
                item=frozen_accounts[str(Path(source_path).resolve())]
                require(item["original_logical_ref"]==dict(path=source_path,sha256=expected) and item["actual_snapshot_ref"]["sha256"]==expected,"ORIGINAL_99_ACCOUNT_EXECUTION_BYTES_REQUIRED")
            elif registry_metadata_active and Path(source_path).resolve() in _registry_metadata_fixed_sources():
                old, live = _registry_metadata_fixed_sources()[Path(source_path).resolve()]
                require(expected == old and (_registry_metadata_verify_capture_ref(next(v["custody_ref"] for v in _REGISTRY_METADATA_SCOPE["entries"].values() if Path(v["original_logical_ref"]["path"]).resolve()==Path(source_path).resolve())) is not None if registry_capture_active else sha(source_path) == live),
                    "FIXED_LOGICAL_AND_NONEXECUTED_CLOSURE_SOURCE_REQUIRED")
            else:
                require(sha(source_path) == expected, "EXECUTABLE_SOURCE_CHANGED:" + source_path)
            continue
        entry = replacements[source_path]
        require(set(entry) == {"original_ref", "custody_ref", "runtime_ref"}
            and entry["original_ref"] == dict(path=source_path, sha256=expected)
            and entry["custody_ref"]["sha256"] == expected, "R4_EXACT_ORIGINAL_SOURCE_CUSTODY_REQUIRED")
        custody = _correction_ref(entry["custody_ref"])
        require(custody != Path(source_path).resolve()
            and (custody.is_relative_to(resolve(REPO).cache_root) or custody.is_relative_to(run)),
            "R4_SEPARATE_SOURCE_CUSTODY_REQUIRED")
        _correction_ref(entry["runtime_ref"])
        if source_path in prior["replacements"]:
            require(entry["original_ref"] == prior["replacements"][source_path]["original_ref"]
                and entry["custody_ref"] == prior["replacements"][source_path]["custody_ref"],
                "R4_PRIOR_ORIGINAL_SOURCE_CUSTODY_CHANGED")
    require(Path(replacements[controller]["runtime_ref"]["path"]).resolve() == Path(controller)
        and Path(__file__).resolve() == Path(controller)
        and Path(_source_correction.__code__.co_filename).resolve() == Path(controller)
        and Path(_source_correction_r4.__code__.co_filename).resolve() == Path(controller)
        and Path(_source_r4_loaded_modules.__code__.co_filename).resolve() == Path(controller)
        and replacements[controller]["runtime_ref"]["sha256"] == sha(__file__),
        "R4_ACTUAL_CANONICAL_CONTROLLER_SOURCE_ORIGIN_REQUIRED")
    capture = json.loads(Path(_SOURCE_R5_CAPTURE_REF["path"]).read_text(encoding="utf-8")) if is_r5 else None
    for name, (relative, old_sha, live_sha, snapshot_file) in _SOURCE_CORRECTION_R4_SNAPSHOTS.items():
        logical_path = str((REPO / relative).resolve())
        item = transport["entries"][name]
        if is_r5:
            live_sha = _SOURCE_R5_OBSERVED_SHA[name]
            observed = _source_r5_capture_entry(name, relative, dict(path=str(Path(snapshot_file).resolve()),sha256=old_sha))
            require(capture.get("schema") == "FULL_SELECTOR_FIXED_FOUR_NONEXECUTED_LIVE_CUSTODY_OBSERVATION_R1"
                and capture.get("status") == "ACTUAL_METADATA_CAPTURE_NOT_SOURCE_ACCEPTANCE"
                and all(capture["entries"][name][k] == value for k,value in observed.items())
                and item["nonexecuted_live_custody_ref"] == observed["nonexecuted_live_custody_ref"]
                and item["exact_at_capture"] is True and item["current_after_capture_unknown"] is True,
                "R5_CAPTURE_IS_ONLY_IMMUTABLE_AS_OBSERVED_METADATA")
        require(set(item) == ({"logical_original_runtime_ref", "live_observation_ref", "actual_snapshot_ref", "nonexecuted_live_custody_ref", "exact_at_capture", "current_after_capture_unknown"} if is_r5 else {"logical_original_runtime_ref", "live_observation_ref", "actual_snapshot_ref"})
            and item["logical_original_runtime_ref"] == dict(path=logical_path, sha256=old_sha)
            and Path(item["live_observation_ref"]["path"]).resolve() == Path(logical_path)
            and item["live_observation_ref"]["sha256"] == live_sha and live_sha != old_sha
            and Path(item["actual_snapshot_ref"]["path"]).resolve() == Path(snapshot_file).resolve()
            and item["actual_snapshot_ref"]["sha256"] == old_sha
            and replacements[logical_path]["runtime_ref"] == item["actual_snapshot_ref"],
            "R4_EXACT_LOGICAL_LIVE_SNAPSHOT_CHAIN_REQUIRED:" + name)
        _correction_ref(item["nonexecuted_live_custody_ref"] if is_r5 else item["live_observation_ref"])
        _correction_ref(item["actual_snapshot_ref"])
        if logical_path in prior["replacements"]:
            require(prior["replacements"][logical_path]["runtime_ref"] == item["logical_original_runtime_ref"],
                "R4_APPROVED_PRIOR_RUNTIME_BYTES_CHANGED:" + name)
        else:
            require(design["sources"][logical_path] == old_sha,
                "R4_EXACT_ORIGINAL_V22_RUNTIME_BYTES_REQUIRED")
    _source_r4_loaded_modules(transport)
    review_path = _correction_ref(data["independent_review_ref"])
    review = json.loads(review_path.read_text(encoding="utf-8"))
    payload = {k: data[k] for k in active_fields - {"status", "independent_review_ref"}}
    require(review.get("schema") == (_ENVIRONMENT_RECOVERY_REVIEW_SCHEMA if is_environment_recovery else _ACCOUNT_FROZEN_REVIEW_SCHEMA if is_account_transport else "FULL_SELECTOR_RISK_FIXED_TWO_NONEXECUTED_SOURCE_CAPTURE_INDEPENDENT_REVIEW_R2" if is_refresh else "FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R5_INDEPENDENT_REVIEW_R1" if is_r5 else "FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R4_INDEPENDENT_REVIEW_R1")
        and review.get("status") == "PASS" and review.get("research_id") == ID
        and review.get("independent_from_root_writer") is True
        and review.get("source_correction_payload_sha256") == digest(payload)
        and all(review.get(k) is True for k in ("scientific_contract_unchanged",
            "prior_R2_history_preserved"))
        and (review.get("finite_six_environment_source_scope") is True and review.get("environment_recovery_math_call_ast_exact") is True
            and review.get("environment_recovery_manifest_ref")==data["environment_recovery_manifest_ref"]
            and review.get("workflow_runtime_sha256")==_ENVIRONMENT_RECOVERY_WORKFLOW_SHA
            if is_environment_recovery else review.get("finite_five_source_scope") is True and review.get("all_business_function_ast_exact") is True)
        and (all(review.get(k) is True for k in (("other_89_sources_exact" if is_environment_recovery else "other_90_sources_exact" if is_account_transport else "other_92_sources_exact"),
            "closed_two_nonexecuted_metadata_observations_exact", "nonexecuted_source_execution_fence_proven"))
            and (review.get("nonexecuted_capture_policy")==_registry_metadata_capture_policy() if registry_capture_active else review.get("nonexecuted_source_observations") == _registry_metadata_observation())
            and review.get("other_93_sources_exact") is False
            and review.get("other_94_sources_exact") is False
            if registry_metadata_active else review.get("other_94_sources_exact") is True),
        "INDEPENDENT_FINITE_SOURCE_R4_REVIEW_REQUIRED")
    if is_r5:
        require(review_path == run/"maintenance"/(_RISK_NONEXECUTED_REFRESH_REVIEW_NAME if is_refresh else _SOURCE_R5_REVIEW_NAME)
            and review.get("prior_R4_history_preserved") is True
            and review.get("four_live_paths_nonexecuted") is True
            and review.get("original_four_actual_snapshots_exact") is True
            and review.get("transport_owner_custody_exact") is True
            and review.get("current_live_equals_capture_claimed") is False
            and review.get("human_authorization_ref") == _SOURCE_R5_AUTH_REF
            and review.get("source_transport_payload_sha256") == digest(transport),
            "INDEPENDENT_FINITE_AS_OBSERVED_R5_REVIEW_REQUIRED")
    if is_refresh:
        require(review.get("prior_c3_c06_343_history_preserved") is True and review.get("fixed_two_registered_nonexecuted_paths_capture") is True
            and review.get("prior_r5_configuration_ref")==data["prior_r5_configuration_ref"]
            and review.get("prior_r5_current_runtime_custody_refs")==data["prior_r5_current_runtime_custody_refs"],
            "INDEPENDENT_FIXED_CURRENT_AND_HISTORICAL_OBSERVER_REVIEW_REQUIRED")
    return data


def _source_correction(ref):
    """Finite source correction; provenance bytes and executed bytes stay distinct."""
    if type(ref) is dict and type(ref.get("path")) is str and Path(ref["path"]).resolve()==(_SOURCE_CORRECTION_R4_RUN/"ENGINEERING_POLICY_CATALOG_LIMITED1655_SOURCE_R6.json").resolve():
        import sys
        from scripts.research.a2.training import full_selector_source_guard_recovery as sg
        path=Path(ref["path"]).resolve()
        return sg.validate_catalog_source_epoch(sys.modules[__name__],path,sg.catalog_source_read_control(ref,"source"))
    path = _correction_ref(ref)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema")=="FULL_SELECTOR_POLICY_ZERO_ENTRY_EXACT_JOINT_ALLOCATION_SOURCE_R2":
        import sys
        from scripts.research.a2.training import full_selector_source_guard_recovery as sg
        return sg.validate_source_epoch(sys.modules[__name__],path,data)
    if data.get("schema") in ("FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R4","FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R5",_RISK_NONEXECUTED_REFRESH_SCHEMA,_ACCOUNT_FROZEN_SCHEMA,_ENVIRONMENT_RECOVERY_SCHEMA):
        return _source_correction_r4(path, data)
    is_r2 = data.get("schema") == "FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R2"
    require(data.get("schema") in ("FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R1", "FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R2")
        and data.get("status") == "PASS" and data.get("research_id") == ID,
        "REVIEWED_ENGINEERING_SOURCE_CORRECTION_REQUIRED")
    design_path = _correction_ref(data["design_ref"])
    correction_name = _SOURCE_CORRECTION_R2_NAME if is_r2 else _SOURCE_CORRECTION_NAME
    require(path == design_path.parent / correction_name and design_path.name == "DESIGN_FREEZE.json",
        "FIXED_TASK_SOURCE_CORRECTION_PATH_REQUIRED")
    assert_safe_output_path(design_path.parent, kind="backtest", paths=resolve(REPO))
    design = json.loads(design_path.read_text(encoding="utf-8"))
    require(design.get("research_id") == ID and data["original_sources"] == design["sources"],
        "EXACT_ORIGINAL_99_SOURCE_AUTHORITY_REQUIRED")
    replacements = data["replacements"]
    source_paths = _SOURCE_CORRECTION_R2_PATHS if is_r2 else _SOURCE_CORRECTION_PATHS
    exact_paths = {str((REPO / relative).resolve()) for relative in source_paths}
    require(set(replacements) == exact_paths and len(design["sources"]) == 99,
        "FIXED_FOUR_SOURCE_CORRECTIONS_REQUIRED" if is_r2 else "FIXED_TWO_SOURCE_CORRECTIONS_REQUIRED")
    if is_r2:
        require(set(data) == {"schema", "status", "research_id", "design_ref", "original_sources", "replacements",
            "independent_review_ref", "prior_source_configuration_ref", "prior_controller_custody_ref"},
            "CLOSED_SOURCE_R2_CONFIGURATION_REQUIRED")
        prior_ref = data["prior_source_configuration_ref"]
        prior_path = _correction_ref(prior_ref)
        require(prior_path == design_path.parent / _SOURCE_CORRECTION_NAME and prior_ref["sha256"] == _SOURCE_CORRECTION_R1_SHA,
            "IMMUTABLE_PRIOR_SOURCE_R1_REQUIRED")
        prior = json.loads(prior_path.read_text(encoding="utf-8"))
        require(prior.get("schema") == "FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R1" and prior.get("status") == "PASS"
            and prior.get("research_id") == ID and prior["design_ref"] == data["design_ref"]
            and prior["original_sources"] == design["sources"]
            and set(prior["replacements"]) == {str((REPO / x).resolve()) for x in _SOURCE_CORRECTION_PATHS},
            "ORIGINAL_TWO_SOURCE_R1_HISTORY_CHANGED")
        controller_path = str((REPO / _SOURCE_CORRECTION_PATHS[0]).resolve())
        prior_custody = _correction_ref(data["prior_controller_custody_ref"])
        require(data["prior_controller_custody_ref"]["sha256"] == _SOURCE_CORRECTION_PRIOR_CONTROLLER_SHA
            == prior["replacements"][controller_path]["runtime_ref"]["sha256"]
            and prior_custody != Path(controller_path)
            and (prior_custody.is_relative_to(resolve(REPO).cache_root) or prior_custody.is_relative_to(design_path.parent)),
            "EXACT_PRIOR_CONTROLLER_RUNTIME_CUSTODY_REQUIRED")
        profile_path = str((REPO / _SOURCE_CORRECTION_PATHS[1]).resolve())
        require(replacements[profile_path]["runtime_ref"] == prior["replacements"][profile_path]["runtime_ref"],
            "NO_FURTHER_PROFILE_SOURCE_CHANGE_ALLOWED")
    physical = {}
    for source_path, expected in design["sources"].items():
        if source_path not in replacements:
            require(sha(source_path) == expected, "EXECUTABLE_SOURCE_CHANGED:" + source_path)
            physical[source_path] = expected
            continue
        entry = replacements[source_path]
        require(set(entry) == {"original_ref", "custody_ref", "runtime_ref"}
            and entry["original_ref"] == dict(path=source_path, sha256=expected)
            and Path(entry["runtime_ref"]["path"]).resolve() == Path(source_path).resolve()
            and entry["custody_ref"]["sha256"] == expected,
            "EXACT_ORIGINAL_AND_ACTUAL_RUNTIME_SOURCE_REQUIRED")
        custody = _correction_ref(entry["custody_ref"])
        require(custody != Path(source_path).resolve()
            and (custody.is_relative_to(resolve(REPO).cache_root) or custody.is_relative_to(design_path.parent)),
            "SEPARATE_PRESERVED_SOURCE_CUSTODY_REQUIRED")
        runtime_path = _correction_ref(entry["runtime_ref"])
        physical[str(runtime_path)] = entry["runtime_ref"]["sha256"]
    reviewed_path = _correction_ref(data["independent_review_ref"])
    review = json.loads(reviewed_path.read_text(encoding="utf-8"))
    payload_fields = ("schema", "research_id", "design_ref", "original_sources", "replacements")
    if is_r2: payload_fields += ("prior_source_configuration_ref", "prior_controller_custody_ref")
    payload = {k: data[k] for k in payload_fields}
    require(review.get("status") == "PASS" and review.get("independent_from_root_writer") is True
        and review.get("source_correction_payload_sha256") == digest(payload)
        and review.get("scientific_contract_unchanged") is True
        and review.get("other_95_sources_exact" if is_r2 else "other_97_sources_exact") is True
        and (not is_r2 or (review.get("prior_R1_history_preserved") is True
            and review.get("finite_four_source_scope") is True)),
        "INDEPENDENT_FINITE_SOURCE_REVIEW_REQUIRED")
    require(Path(_source_correction.__code__.co_filename).resolve() == Path(__file__).resolve()
        and str(Path(__file__).resolve()) in exact_paths
        and Path(__file__).resolve() == REPO / _SOURCE_CORRECTION_PATHS[0]
        and physical[str(Path(__file__).resolve())] == sha(__file__),
        "ACTUAL_CONTROLLER_SOURCE_ORIGIN_REQUIRED")
    return data


@contextmanager
def engineering_source_configuration(ref):
    """Explicit approved scope; no hash override, ledger reset or source rewriting."""
    global _ENGINEERING_SOURCE_CONFIGURATION
    require(_ENGINEERING_SOURCE_CONFIGURATION is None, "SOURCE_CORRECTION_SCOPE_ALREADY_ACTIVE")
    data = _source_correction(ref)
    state = dict(ref=dict(ref), payload_sha256=digest(data))
    _ENGINEERING_SOURCE_CONFIGURATION = state
    try:
        yield data
    finally:
        _ENGINEERING_SOURCE_CONFIGURATION = None


def _verify_task_sources(run, design):
    if _ENGINEERING_SOURCE_CONFIGURATION is None:
        for path, expected in design["sources"].items():
            require(sha(path) == expected, "EXECUTABLE_SOURCE_CHANGED:" + path)
        return
    state = _ENGINEERING_SOURCE_CONFIGURATION
    data = _source_correction(state["ref"])
    require(digest(data) == state["payload_sha256"]
        and Path(data["design_ref"]["path"]).resolve() == Path(run).resolve() / "DESIGN_FREEZE.json"
        and data["original_sources"] == design["sources"], "ENGINEERING_SOURCE_SCOPE_CHANGED")


class _TaskLedger:
    """One task's frozen physical nodes; SQL transactions permit its three packages."""
    def __init__(self,run):
        self.run=Path(run).resolve()
        assert_safe_output_path(self.run,kind="backtest",paths=resolve(REPO))
        self.design=json.loads((self.run/"DESIGN_FREEZE.json").read_text(encoding="utf-8"))
        gate=json.loads((self.run/"FREEZE_ACCEPTANCE.json").read_text(encoding="utf-8"))
        require(self.design["research_id"]==ID and gate["status"]=="PASS" and gate["design_sha256"]==sha(self.run/"DESIGN_FREEZE.json"),"INDEPENDENT_FREEZE_REQUIRED")
        require(gate["input_manifest_sha256"]==sha(self.run/"input_manifest.json"),"FROZEN_INPUT_MANIFEST_CHANGED")
        require(sha(self.run/"run_config.json")==self.design.get("run_config_sha256"),"FROZEN_RUN_CONFIG_CHANGED")
        _verify_task_sources(self.run, self.design)
        if "registry" in self.design:
            scope=self.design["registry"]["explicit_human_scope_review"]
            review=json.loads(Path(scope["path"]).read_text(encoding="utf-8"))
            require(digest({k:review[k] for k in scope["scope_fields"]})==scope["scope_payload_sha256"],"FROZEN_EXPLICIT_SCOPE_CHANGED")
            ref=gate["independent_review"]
            require(Path(ref["path"]).resolve()==Path(scope["path"]).resolve() and sha(ref["path"])==ref["sha256"],"INDEPENDENT_FINAL_REVIEW_CHANGED")
        self.db=sqlite3.connect(self.run/"TASK_LEDGER.sqlite",timeout=60)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS nodes (node_id TEXT PRIMARY KEY,kind TEXT NOT NULL,status TEXT NOT NULL,entered INTEGER NOT NULL DEFAULT 0,identity TEXT,artifact TEXT,error TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY,node_id TEXT,action TEXT,payload TEXT,utc TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS authority (design_sha256 TEXT PRIMARY KEY)")
        with self.db:
            if self.db.execute("SELECT count(*) FROM authority").fetchone()[0]==0:
                self.db.execute("INSERT INTO authority VALUES (?)",(gate["design_sha256"],))
                self.db.executemany("INSERT INTO nodes(node_id,kind,status) VALUES (?,?,'NAMED')",[(n["node_id"],n["kind"]) for n in self.design["dag"]["nodes"]])
            require(self.db.execute("SELECT design_sha256 FROM authority").fetchall()==[(gate["design_sha256"],)],"LEDGER_AUTHORITY_CHANGED")
            actual={r[0]:r[1] for r in self.db.execute("SELECT node_id,kind FROM nodes")}
            require(actual=={n["node_id"]:n["kind"] for n in self.design["dag"]["nodes"]},"LEDGER_NODE_SET_CHANGED")

    def status(self,node):
        row=self.db.execute("SELECT status,entered,identity,artifact,error FROM nodes WHERE node_id=?",(node,)).fetchone()
        require(row is not None,"UNNAMED_NODE_FORBIDDEN:"+node)
        return dict(zip(("status","entered","identity","artifact","error"),row))

    def event(self,node,action,payload):
        self.db.execute("INSERT INTO events(node_id,action,payload,utc) VALUES (?,?,?,?)",(node,action,json.dumps(payload,default=str,allow_nan=False),now()))

    def once(self,node,identity,work):
        import joblib
        token=digest(identity);s=self.status(node)
        if s["status"]=="COMPLETE":
            require(s["identity"]==token,"COMPLETE_EXACT_REUSE_IDENTITY_CHANGED")
            ref=json.loads(s["artifact"]);require(sha(ref["path"])==ref["sha256"],"COMPLETE_ARTIFACT_CHANGED")
            return joblib.load(ref["path"])
        if s["status"] in ("FAILED","SOURCE_NOT_TESTABLE","BLOCKED_DEPENDENCY"):
            return None
        if s["status"]=="STARTED": return None
        require(s["status"]=="NAMED","STARTED_OR_ENTERED_SCIENTIFIC_NODE_CANNOT_RETRY")
        with self.db:
            require(self.db.execute("UPDATE nodes SET status='STARTED',identity=? WHERE node_id=? AND status='NAMED'",(token,node)).rowcount==1,"NODE_ALREADY_STARTING")
            self.event(node,"BEGIN",identity)
        def entered(observation=None):
            with self.db:
                require(self.db.execute("UPDATE nodes SET entered=1 WHERE node_id=? AND status='STARTED' AND entered=0",(node,)).rowcount==1,"DUPLICATE_OR_UNNAMED_BACKEND_ENTRY")
                self.event(node,"BACKEND_ENTER",observation or {})
        try:
            result=work(entered)
            require(self.status(node)["entered"]==1,"RESERVATION_WITHOUT_ACTUAL_BACKEND_ENTRY")
            path=self.run/"models"/(digest(node)+".joblib")
            path.parent.mkdir(parents=True,exist_ok=True)
            require(not path.exists(),"PRESERVE_EXISTING_NODE_ARTIFACT")
            joblib.dump(result,path,compress=3)
            ref=dict(path=str(path),sha256=sha(path))
            with self.db:
                self.db.execute("UPDATE nodes SET status='COMPLETE',artifact=? WHERE node_id=?",(json.dumps(ref),node))
                self.event(node,"COMPLETE",ref)
            return result
        except Exception as exc:
            with self.db:
                self.db.execute("UPDATE nodes SET status='FAILED',error=? WHERE node_id=?",(traceback.format_exc(),node))
                self.event(node,"FAILED",dict(error=type(exc).__name__+":"+str(exc),entered=self.status(node)["entered"]))
            print(json.dumps(dict(phase="NODE_FAILED",node=node,error=str(exc)),ensure_ascii=False),flush=True)
            return None

    def block(self,node,reason):
        with self.db:
            if self.status(node)["status"]=="NAMED":
                self.db.execute("UPDATE nodes SET status='BLOCKED_DEPENDENCY',error=? WHERE node_id=?",(reason,node))
                self.event(node,"BLOCKED_DEPENDENCY",dict(reason=reason))


    def alias(self,node,source,identity):
        token=digest(identity);target=self.status(node);original=self.status(source)
        if target["status"]=="COMPLETE":
            require(target["identity"]==token,"EXACT_ALIAS_IDENTITY_CHANGED")
            ref=json.loads(target["artifact"]);require(sha(ref["path"])==ref["sha256"],"EXACT_ALIAS_ARTIFACT_CHANGED");return True
        if target["status"]!="NAMED" or original["status"]!="COMPLETE":return False
        require(original["identity"]==token,"EXACT_ALIAS_SOURCE_IDENTITY_CHANGED")
        ref=json.loads(original["artifact"]);require(sha(ref["path"])==ref["sha256"],"EXACT_ALIAS_ARTIFACT_CHANGED")
        with self.db:
            require(self.db.execute("UPDATE nodes SET status='COMPLETE',identity=?,artifact=? WHERE node_id=? AND status='NAMED'",(token,original["artifact"],node)).rowcount==1,"ALIAS_NODE_ALREADY_USED")
            self.event(node,"EXACT_ALIAS",dict(source_node=source,artifact=ref,actual_backend_entries=0))
        return True

    def composite_once(self,nodes,identity,work):
        """Durable actual callbacks for retained composites, without fake fits.

        Every learned state shares one complete model receipt. Partial/STARTED
        composites cannot replay their already entered preprocessing or backend.
        """
        import joblib
        token=digest(identity);nodes=tuple(nodes);states={n:self.status(n) for n in nodes}
        if all(s["status"]=="COMPLETE" for s in states.values()):
            refs=[]
            for node,s in states.items():
                require(s["identity"]==token,"COMPOSITE_REUSE_IDENTITY_CHANGED")
                ref=json.loads(s["artifact"]);require(sha(ref["path"])==ref["sha256"],"COMPOSITE_ARTIFACT_CHANGED");refs.append(ref)
            require(refs and all(r==refs[0] for r in refs),"COMPOSITE_ATOMIC_RECEIPT_REQUIRED")
            return joblib.load(refs[0]["path"])
        if any(s["status"]!="NAMED" for s in states.values()):
            for node in nodes:self.block(node,"PARTIAL_COMPOSITE_OR_FAILED_STATE_NO_SCIENTIFIC_RETRY")
            return None
        observed=[]
        def observe(event):
            node=event["node_id"]
            require(node in nodes and node not in observed and event.get("actual_operation_entered") is True,"UNNAMED_OR_DUPLICATE_COMPOSITE_OPERATION")
            with self.db:
                require(self.db.execute("UPDATE nodes SET status='STARTED',identity=?,entered=1 WHERE node_id=? AND status='NAMED'",(token,node)).rowcount==1,"COMPOSITE_OPERATION_ALREADY_ENTERED")
                self.event(node,"BEGIN",identity);self.event(node,"BACKEND_ENTER",event)
            observed.append(node)
        try:
            result=work(observe)
            require(set(observed)==set(nodes),"COMPOSITE_MISSING_ACTUAL_STATE_CALLBACK")
            artifact=self.run/"models"/(digest(dict(nodes=nodes))+".joblib")
            assert_safe_output_path(artifact,kind="backtest",paths=resolve(REPO));artifact.parent.mkdir(parents=True,exist_ok=True)
            require(not artifact.exists(),"PRESERVE_EXISTING_COMPOSITE_ARTIFACT")
            joblib.dump(result,artifact,compress=3);ref=dict(path=str(artifact),sha256=sha(artifact))
            with self.db:
                for node in nodes:
                    self.db.execute("UPDATE nodes SET status='COMPLETE',artifact=? WHERE node_id=? AND status='STARTED'",(json.dumps(ref),node));self.event(node,"COMPLETE",ref)
            return result
        except Exception as exc:
            with self.db:
                for node in observed:
                    self.db.execute("UPDATE nodes SET status='FAILED',error=? WHERE node_id=?",(traceback.format_exc(),node));self.event(node,"FAILED",dict(error=str(exc),entered=1))
            for node in nodes:self.block(node,"COMPOSITE_UPSTREAM_FAILURE_NO_REFUND")
            print(json.dumps(dict(phase="COMPOSITE_FAILED",nodes=nodes,error=str(exc))),flush=True)
            return None


_WORKER_RUNTIMES={}


def worker_runtime(run):
    """One existing runtime initialization per worker and exact run config."""
    run=Path(run).resolve();cfg=json.loads((run/"run_config.json").read_text(encoding="utf-8"))
    cache=Path(cfg["cache_directory"]).resolve();assert_safe_output_path(cache,kind="cache",paths=resolve(REPO))
    token=(os.getpid(),str(run),sha(run/"run_config.json"))
    if token not in _WORKER_RUNTIMES:
        (cache/"temp").mkdir(parents=True,exist_ok=True)
        os.environ.setdefault("LOKY_MAX_CPU_COUNT","2")
        result=runtime(run)
        require(len(result)==10 and Path(result[0]["cache_directory"]).resolve()==cache,"EXACT_WORKER_CACHE_RUNTIME_REQUIRED")
        _WORKER_RUNTIMES[token]=result
    result=_WORKER_RUNTIMES[token]
    if (run/"DESIGN_FREEZE.json").exists():
        design=json.loads((run/"DESIGN_FREEZE.json").read_text(encoding="utf-8"))
        require(result[5].RUNTIME==design["runtime_dependencies"]["native_runtime"],"FROZEN_NATIVE_RUNTIME_CHANGED")
    return result


def _scalar_output(role,values):
    return values["q50"] if role=="QUANTILE_HGB" else values["mu"] if role=="GAUSSIAN_MLP" else values["prob"] if role in ("LOGIT","LINEAR_SVM") and "prob" in values else values["margin"] if role in learners.MARGINS else values["point"]


def _expected(frame):
    return {pd.Timestamp(day):tuple(g.security_uid) for day,g in frame.groupby("signal_date",sort=True)}


def _pool(reader,cut):
    vectors=(reader.training_vectors if hasattr(reader,"training_vectors") else reader.features)("2020-01-01",cut);labels=reader.labels("2020-01-01",cut)
    pool=vectors.merge(labels.drop(columns=["U_t_fingerprint"]),on=KEYS,how="inner",validate="one_to_one")
    require(len(pool)==reader.qualification["training"][cut]["rows"] and keys_digest(pool)==reader.qualification["training"][cut]["key_sha256"],"FULL_MATURE_TRAINING_DOMAIN_CHANGED")
    pool=pool.sort_values(KEYS,kind="stable").reset_index(drop=True)
    return reader.enrich_risk(pool) if hasattr(reader,"enrich_risk") else pool


def _bundle(run,journal,reader,pool,role,cut,cap,logical="",rt=None,alias_from=None,node_role=None):
    from sklearn.preprocessing import StandardScaler
    from scripts.research.a2.training.selector_sufficiency_estimators import date_weights
    cid=node_role or role;features=tuple(getattr(reader,"feature_order",FEATURES));representation=getattr(reader,"representation",learners.SINGLE_FULL_U32)
    scaler_node="SCALER|"+(cid+"|" if cid!=role else "")+cut
    weights=date_weights(pool.signal_date);x=pool[list(features)].to_numpy(float)
    require(np.isfinite(x).any(axis=0).all() and not np.isinf(x).any(),"ALL_NAN_OR_INFINITE_PAST_FEATURE_CANNOT_BE_GUESSED")
    identity=dict(representation=representation,cutoff=cut,training_keys=keys_digest(pool),x_sha256=array_digest(x),
        feature_order=list(features),weight_policy="N/(D*N_t)",target_source=reader.manifest["input_sources"]["hlabels"])
    if representation==learners.SINGLE_HYBRID_U34:identity.update(policy_id=cid,risk_refs=pool.attrs["risk_refs"])
    def scaler_fit(entered):entered(dict(operation="weighted_standard_scaler_fit"));return StandardScaler().fit(x,sample_weight=weights)
    scaler=journal.once(scaler_node,identity,scaler_fit)
    if scaler is None:return None
    y=pool.target.to_numpy(float);tasks=pool[["ER_3D","ER_5D","ER_10D","ER_20D"]].to_numpy(float);xscaled=scaler.transform(x);models={}
    for component in learners.component_specs(role):
        node=f"MODEL|{cid}|{cut}|{logical or cap}|{component['seed']}|{component['quantile']}"
        mid=dict(identity,role=role,capacity=cap,component=component,spec=learners.capacity_specs(input_feature_count=len(features),representation=representation)[role][cap],
            target_sha256=array_digest(y),tasks_sha256=array_digest(tasks),scaler_node=scaler_node)
        if alias_from is not None:
            source=f"MODEL|{cid}|{cut}|{alias_from}|{component['seed']}|{component['quantile']}"
            require(journal.alias(node,source,mid),"REQUIRED_FIXED_MID_EXACT_ALIAS_UNAVAILABLE")
        def fit(entered,component=component):
            return learners.fit_single_component(role,xscaled,y,tasks,pool.signal_date,pool.security_uid,cap,component["seed"],q=component["quantile"],
                runtime=rt if rt is not None else worker_runtime(run),on_fit=entered,fit_cutoff=cut,label_end_dates=pool.target_end_date,expected_full_day_uids=_expected(pool),representation=representation)
        fitted=journal.once(node,mid,fit)
        if fitted is None:
            for remaining in learners.component_specs(role):
                journal.block(f"MODEL|{cid}|{cut}|{logical or cap}|{remaining['seed']}|{remaining['quantile']}","REQUIRED_SEED_OR_QUANTILE_FAILED_NO_PARTIAL_ENSEMBLE")
            return None
        models[(component["seed"],component["quantile"])]=fitted
    return dict(scaler=scaler,models=models,role=role,capacity=cap,cutoff=cut,feature_order=list(features),representation=representation,max_train_label_end=str(pool.target_end_date.max()),training_keys=keys_digest(pool))


def _predict(bundle,vectors,calibrator=None):
    x=bundle["scaler"].transform(vectors[bundle.get("feature_order",list(FEATURES))].to_numpy(float))
    parts={key:learners.predict_component(model,x) for key,model in bundle["models"].items()};combined=learners.combine_predictions(bundle["role"],parts)
    if bundle["role"]=="LINEAR_SVM" and calibrator is not None:
        combined["prob"]=calibrator.predict_proba(np.asarray(combined["margin"]).reshape(-1,1))[:,1]
    result=vectors[KEYS+["ticker","U_t_fingerprint"]].copy();result["score"]=_scalar_output(bundle["role"],combined)
    for name,value in combined.items():
        if np.asarray(value).ndim==1:result["native_"+name]=value
        elif name=="tasks":
            for i,h in enumerate((3,5,10,20)):result["native_ER_"+str(h)+"D"]=value[:,i]
    result["source_cutoff"]=pd.Timestamp(bundle["cutoff"]);result["source_capacity"]=bundle["capacity"];result["source_kind"]="MODEL_OOF"
    result["max_train_label_end"]=pd.Timestamp(bundle["max_train_label_end"]);result["cutoff_clock"]="MIDNIGHT_BEFORE_DECISION_CLOSE"
    require(vectors.feature_source_present.eq(True).all() and np.isfinite(result.score).all(),"FULL_U_FORECAST_SOURCE_OR_MODEL_NOT_TESTABLE")
    return result


def _frame_hash(frame):
    return hashlib.sha256(frame.to_csv(index=False,float_format="%.17g",lineterminator="\n").encode()).hexdigest()


def _store_frame(run,path,frame,identity):
    path=Path(path);assert_safe_output_path(path,kind="backtest",paths=resolve(REPO));require(path.resolve().is_relative_to(Path(run).resolve()),"RUN_OWNED_PREDICTION_REQUIRED")
    receipt_path=Path(str(path)+".json");token=digest(identity);body=_frame_hash(frame)
    if path.exists() or receipt_path.exists():
        require(path.exists() and receipt_path.exists(),"INCOMPLETE_PREDICTION_ARTIFACT_NO_OVERWRITE")
        ref=json.loads(receipt_path.read_text(encoding="utf-8"));require(ref["identity_sha256"]==token and ref["frame_sha256"]==body and sha(path)==ref["sha256"],"COMPLETE_PREDICTION_EXACT_REUSE_CHANGED")
        return ref
    require(pd.to_datetime(frame.signal_date).lt("2026-01-01").all(),"PREDICTION_PHYSICAL_PRE2026_REQUIRED")
    path.parent.mkdir(parents=True,exist_ok=True);frame.to_parquet(path,index=False)
    ref=dict(path=str(path),sha256=sha(path),identity_sha256=token,frame_sha256=body,rows=len(frame),dates=frame.signal_date.nunique(),keys_sha256=keys_digest(frame),identity=identity)
    putj(receipt_path,ref);return ref


def _load_frame(path):
    path=Path(path);receipt=Path(str(path)+".json");require(path.exists() and receipt.exists(),"COMPLETE_PREDICTION_RECEIPT_REQUIRED")
    ref=json.loads(receipt.read_text(encoding="utf-8"));guard_parquet(path,ref["sha256"],["signal_date"])
    out=pd.read_parquet(path);out.signal_date=pd.to_datetime(out.signal_date)
    require(_frame_hash(out)==ref["frame_sha256"] and keys_digest(out)==ref["keys_sha256"],"COMPLETE_PREDICTION_BODY_CHANGED")
    return out,ref


def _native_path(run,role,cut,cap):return Path(run)/"predictions"/"native_oof"/role/(cut+"_"+cap+".parquet")


def _platt(run,journal,reader,cut,cap,history,logical=""):
    from sklearn.linear_model import LogisticRegression
    from scripts.research.a2.training.selector_sufficiency_estimators import date_weights
    node=f"PLATT|LINEAR_SVM|{cut}|{logical or cap}"
    if not history:journal.block(node,"NO_TRUE_PAST_OOF_FOR_PLATT");return None
    h=pd.concat(history,ignore_index=True)
    require(not h.duplicated(KEYS).any() and h.source_kind.eq("MODEL_OOF").all() and pd.to_datetime(h.source_cutoff).le(h.signal_date).all() and pd.to_datetime(h.max_train_label_end).lt(pd.to_datetime(h.source_cutoff)).all() and h.cutoff_clock.eq("MIDNIGHT_BEFORE_DECISION_CLOSE").all(),"PLATT_GENUINE_PAST_OOF_REQUIRED")
    labels=reader.labels("2020-01-01",cut)
    h=h.loc[h.signal_date.lt(cut)].merge(labels[KEYS+["target","target_end_date"]],on=KEYS,how="inner",validate="one_to_one")
    require(h.target_end_date.lt(cut).all(),"PLATT_LABEL_MATURITY_REQUIRED")
    expected=labels.loc[labels.signal_date.ge(CUTS[0]) & labels.signal_date.lt(cut)]
    require(keys_digest(h)==keys_digest(expected),"PLATT_EVERY_LEGAL_MATURE_PAST_OOF_KEY_REQUIRED")
    if h.empty or h.target.gt(0).nunique()!=2:journal.block(node,"PLATT_MATURE_BOTH_CLASSES_UNAVAILABLE");return None
    identity=dict(role="LINEAR_SVM",capacity=cap,cutoff=cut,source_kind="MODEL_OOF",keys=keys_digest(h),margin=array_digest(h.native_margin),target=array_digest(h.target),max_label_end=str(h.target_end_date.max()),spec=dict(C=1.,max_iter=400,random_state=20260928),date_weights="N/(D*N_t)")
    def fit(entered):
        entered(dict(operation="past_full_OOF_Platt_LogisticRegression.fit"))
        return LogisticRegression(C=1.,max_iter=400,random_state=20260928).fit(h[["native_margin"]].to_numpy(float),h.target.gt(0),sample_weight=date_weights(h.signal_date))
    return journal.once(node,identity,fit)


def _validation_record(role,cut,end,cap,bank,labels,vectors):
    require(keys_digest(bank)==keys_digest(vectors),"INNER_PREDICTION_COMPLETE_FULL_U_REQUIRED")
    val=bank.merge(labels[KEYS+["target","target_end_date","ER_3D","ER_5D","ER_10D","ER_20D"]],on=KEYS,how="inner",validate="one_to_one")
    require(len(val)>0 and val.target_end_date.lt(end).all(),"INNER_PAST_MATURE_LABELS_REQUIRED")
    if role in ("PAIRWISE_RANKER","LAMBDAMART","LISTWISE_MLP"):
        dates=pd.DatetimeIndex(val.signal_date.unique());full=vectors.loc[vectors.signal_date.isin(dates)]
        require(keys_digest(val)==keys_digest(full),"RANK_LISTWISE_INNER_MATURE_FULL_DAY_REQUIRED")
        selected=top20(val);daily=-selected.loc[selected.selected].groupby("signal_date").target.mean();kind="NEGATIVE_FULL_DAY_TOP20_MEAN_TARGET"
    else:
        y=val.target.to_numpy(float)
        if role in ("LOGIT","LINEAR_SVM"):
            require("native_prob" in val,"PLATT_GENUINE_PROBABILITY_REQUIRED_FOR_BRIER")
            loss=(val.native_prob.to_numpy(float)-(y>0))**2;kind="BRIER_SIGN"
        elif role=="QUANTILE_HGB":
            loss=np.mean([np.maximum(q*(y-val["native_q"+str(int(q*100))].to_numpy(float)),(q-1)*(y-val["native_q"+str(int(q*100))].to_numpy(float))) for q in learners.QUANTILES],axis=0);kind="MEAN_THREE_QUANTILE_PINBALL"
        elif role=="GAUSSIAN_MLP":
            sigma=val.native_sigma.to_numpy(float);require((sigma>0).all(),"GAUSSIAN_POSITIVE_SCALE_REQUIRED")
            loss=np.log(sigma)+.5*((y-val.native_mu.to_numpy(float))/sigma)**2;kind="GAUSSIAN_NLL"
        elif role in learners.MULTITASK:
            loss=np.mean([(val["native_ER_"+str(h)+"D"].to_numpy(float)-val["ER_"+str(h)+"D"].to_numpy(float))**2 for h in (3,5,10,20)],axis=0);kind="EQUAL_FOUR_TASK_MSE"
        else:loss=(val.native_point.to_numpy(float)-y)**2;kind="MSE"
        require(np.isfinite(loss).all(),"INNER_FINITE_NATIVE_LOSS_REQUIRED")
        daily=pd.Series(loss,index=val.index).groupby(val.signal_date).mean()
    return dict(cutoff=cut,end=end,capacity=cap,status="COMPLETE",sum_loss=float(daily.sum()),dates=len(daily),native_loss=kind,max_label_end=str(val.target_end_date.max()),keys=keys_digest(val),unmature_date_count=vectors.signal_date.nunique()-val.signal_date.nunique())


def _choose_capacity(records,folds):
    losses={}
    for cap in learners.CAPACITIES:
        rows=[r for r in records if r["cutoff"] in folds and r["capacity"]==cap]
        if len(rows)==len(folds) and all(r["status"]=="COMPLETE" for r in rows):losses[cap]=sum(r["sum_loss"] for r in rows)/sum(r["dates"] for r in rows)
    selected=next((cap for cap in learners.CAPACITIES if losses and cap in losses and abs(losses[cap]-min(losses.values()))<=1e-12),None)
    return selected,losses


def _raw_reference(reader):
    ref=reader.manifest["input_sources"]["raw"];guard_parquet(ref["path"],ref["sha256"],["signal_date"])
    r=pd.read_parquet(ref["path"],columns=[*KEYS,"ticker","U_t_fingerprint","score"],filters=[("signal_date",">=",pd.Timestamp("2023-01-01")),("signal_date","<",pd.Timestamp("2026-01-01"))])
    r.signal_date=pd.to_datetime(r.signal_date);r["source_kind"]="RAW_FROZEN_REFERENCE";return r.sort_values(KEYS,kind="stable").reset_index(drop=True)


def validate_policy_domain(panel,reader):
    full=reader.keys.loc[reader.keys.signal_date.ge("2023-01-01") & reader.keys.signal_date.lt("2026-01-01")].sort_values(KEYS).reset_index(drop=True)
    observed=panel.sort_values(KEYS).reset_index(drop=True)
    columns=KEYS+["ticker","U_t_fingerprint"]
    require(not observed.duplicated(KEYS).any() and observed[columns].equals(full[columns]),"ALL66_IDENTICAL_FULL_U_DOMAIN_REQUIRED")
    require(np.isfinite(observed.score).all(),"FULL_U_MISSING_PREDICTION_NOT_SUCCESS")
    for _,g in observed.groupby("signal_date"):
        require(int(g.selected.sum())==min(20,len(g)),"FULL_U_TOP20_SLOT_COUNT_REQUIRED")
        require(np.allclose(g.loc[g.selected,"target_weight"],.05) and g.loc[~g.selected,"target_weight"].eq(0).all(),"SAME_FIXED_EQUAL_SLOT_WEIGHTS_REQUIRED")
    return True


def _publish_policy(run,reader,role,forecast,raw):
    expected=reader.keys.loc[reader.keys.signal_date.ge("2024-01-01") & reader.keys.signal_date.lt("2026-01-01")]
    require(not forecast.duplicated(KEYS).any() and keys_digest(forecast)==keys_digest(expected),"COMPLETE_2024_2025_FORECAST_AXIS_REQUIRED")
    fallback=raw.loc[raw.signal_date.lt("2024-01-01")].copy();fallback["source_kind"]="RAW_FALLBACK_2023"
    panel=top20(pd.concat([fallback,forecast],ignore_index=True).sort_values(KEYS,kind="stable"));panel["policy_id"]=role
    validate_policy_domain(panel,reader)
    return _store_frame(run,Path(run)/"predictions"/("policy_"+role+".parquet"),panel,dict(policy_id=role,full_U_keys_sha256=keys_digest(reader.keys),raw_pin=reader.manifest["input_sources"]["raw"],raw_fallback_2023_exact=True))


def _role_failure(run,role,exc):
    putj(Path(run)/"predictions"/("failure_"+role+".json"),dict(policy_id=role,status="SOURCE_NOT_TESTABLE" if isinstance(exc,HybridRiskUnavailable) else "TRAINING_FAILED",error=type(exc).__name__+":"+str(exc),traceback=traceback.format_exc(),scientific_retry=0))
    print(json.dumps(dict(phase="ROLE_FAILED",role=role,error=str(exc))),flush=True)


def _train_role(run,journal,reader,rt,role,raw,policy_id=None):
    cid=policy_id or role;node_kwargs=dict(node_role=cid) if cid!=role else {}
    records=[];histories={cap:[] for cap in learners.CAPACITIES};calibrators={};bundles={}
    cuts=CUTS[:-1] if role=="LINEAR_SVM" else CUTS[1:-1]
    for cut in cuts:
        pool=_pool(reader,cut);end=CUTS[CUTS.index(cut)+1];vectors=reader.features(cut,end);labels=reader.labels(cut,end)
        for cap in learners.CAPACITIES:
            print(json.dumps(dict(phase="FULL_U_TRAINING",role=role,cutoff=cut,capacity=cap,rows=len(pool),dates=pool.signal_date.nunique())),flush=True)
            bundle=_bundle(run,journal,reader,pool,role,cut,cap,rt=rt,**node_kwargs);bundles[(cut,cap)]=bundle
            if bundle is None:records.append(dict(cutoff=cut,end=end,capacity=cap,status="TRAINING_FAILED"));continue
            calibrator=_platt(run,journal,reader,cut,cap,histories[cap]) if role=="LINEAR_SVM" and cut!=CUTS[0] else None
            if role=="LINEAR_SVM":calibrators[(cut,cap)]=calibrator
            bank=_predict(bundle,vectors,calibrator)
            _store_frame(run,_native_path(run,cid,cut,cap),bank,dict(role=role,cutoff=cut,capacity=cap,training_keys=bundle["training_keys"],max_train_label_end=bundle["max_train_label_end"]))
            if role=="LINEAR_SVM":histories[cap].append(bank)
            if cut==CUTS[0]:continue
            try:records.append(_validation_record(role,cut,end,cap,bank,labels,vectors))
            except ValueError as exc:records.append(dict(cutoff=cut,end=end,capacity=cap,status="SOURCE_NOT_TESTABLE",reason=str(exc)))
        del pool
    choices={};outputs=[];fixed={}
    for year,folds in ((2024,("2023-07-01",)),(2025,("2024-01-01","2024-07-01"))):
        selected,losses=_choose_capacity(records,folds);choices[str(year)]=dict(selected_capacity=selected,inner_folds=list(folds),past_only_validation=losses)
        cut=str(year)+"-01-01";vectors=reader.features(cut,str(year+1)+"-01-01");pool=_pool(reader,cut)
        bundle=bundles.get((cut,selected)) if year==2024 else _bundle(run,journal,reader,pool,role,cut,selected,logical="SELECTED",rt=rt,**node_kwargs) if selected else None
        calibrator=calibrators.get((cut,selected)) if year==2024 else _platt(run,journal,reader,cut,selected,histories[selected],logical="SELECTED") if role=="LINEAR_SVM" and selected else None
        if bundle is not None and (role!="LINEAR_SVM" or calibrator is not None):
            annual=_predict(bundle,vectors,calibrator);outputs.append(annual)
            _store_frame(run,Path(run)/"predictions"/"annual_native"/(cid+"_"+str(year)+".parquet"),annual,dict(role=role,year=year,cutoff=cut,capacity=selected,training_keys=bundle["training_keys"]))
        if cid==role and role in FUSION_MEMBERS:
            mid=bundles.get((cut,"MID")) if year==2024 else _bundle(run,journal,reader,pool,role,cut,"MID",rt=rt,alias_from="SELECTED" if selected=="MID" and bundle is not None else None)
            if mid is not None:
                predicted=_predict(mid,vectors);fixed[str(year)]=_store_frame(run,Path(run)/"predictions"/"fixed_mid"/(cid+"_"+str(year)+".parquet"),predicted,dict(role=role,year=year,capacity="MID",training_keys=mid["training_keys"],selected_mid_exact_alias=selected=="MID" if year==2025 else False))
        if selected is None and year==2025:
            for component in learners.component_specs(role):journal.block(f"MODEL|{cid}|{cut}|SELECTED|{component['seed']}|{component['quantile']}","REQUIRED_PAST_CAPACITY_SELECTION_UNAVAILABLE")
            if role=="LINEAR_SVM":journal.block("PLATT|LINEAR_SVM|"+cut+"|SELECTED","REQUIRED_PAST_CAPACITY_SELECTION_UNAVAILABLE")
    putj(Path(run)/"predictions"/("selection_"+cid+".json"),dict(role=cid,native_paradigm=role,records=records,choices=choices,fixed_mid_forecasts=fixed))
    require(len(outputs)==2,"INCOMPLETE_ANNUAL_NATIVE_NO_RAW_SUCCESS")
    forecast=pd.concat(outputs,ignore_index=True).sort_values(KEYS,kind="stable").reset_index(drop=True)
    _publish_policy(run,reader,cid,forecast,raw)
    if cid==role and role in ("QUANTILE_HGB","GAUSSIAN_MLP"):
        uncertainty=forecast.copy();cid="QUANTILE_Q10" if role=="QUANTILE_HGB" else "GAUSSIAN_MU_MINUS_SIGMA"
        uncertainty["score"]=forecast.native_q10 if role=="QUANTILE_HGB" else forecast.native_mu-forecast.native_sigma
        _publish_policy(run,reader,cid,uncertainty,raw)


def assemble_selection(run,reader=None):
    run=Path(run);reader=reader or FullSelectorReader(run);roles,comparisons=catalog();complete={};status={}
    for role in roles:
        cid=role["policy_id"];path=run/"predictions"/("policy_"+cid+".parquet");failure=run/"predictions"/("failure_"+cid+".json")
        if path.exists() and Path(str(path)+".json").exists():
            panel,ref=_load_frame(path);validate_policy_domain(panel,reader);complete[cid]=ref;status[cid]="SCORES_COMPLETE_ACCOUNT_PENDING"
        elif failure.exists():status[cid]=json.loads(failure.read_text(encoding="utf-8"))["status"]
        else:status[cid]="PENDING_EXTERNAL_STAGE" if role["kind"] in ("RISK_MEMBERSHIP","HYBRID","GATE") else "NOT_EXECUTED"
    receipt=dict(research_id=ID,status="SELECTION_ASSEMBLY",complete_candidates=list(complete),score_paths=complete,role_status=status,catalogue=roles,comparisons=comparisons,
        full_U_keys_sha256=keys_digest(reader.keys),full_calendar_dates=reader.qualification["outer_sessions"],full_rows=reader.qualification["outer_rows"],
        forecast2026_rows=0,all_66_same_prediction_domain=len(complete)==66,complete_candidates_same_prediction_domain=True,raw_fallback_year=2023,scientific_retry=0,strict_PIT_promotion_eligible=False,production_qualified=False,accounts_evaluated=False)
    putj(run/"SCORE_ASSEMBLY.json",receipt);return receipt


def _block_role_nodes(journal,role,reason):
    for node in journal.design["dag"]["nodes"]:
        name=node["node_id"]
        if name.startswith(("MODEL|"+role+"|","PLATT|"+role+"|","SCALER|"+role+"|")) or node.get("method")==role:
            journal.block(name,reason)


def train_primary(run,roles=None):
    run=Path(run);journal=_TaskLedger(run);reader=FullSelectorReader(run);rt=worker_runtime(run);raw=_raw_reference(reader)
    rawpolicy=top20(raw);rawpolicy["policy_id"]="RAW";validate_policy_domain(rawpolicy,reader)
    _store_frame(run,run/"predictions/policy_RAW.parquet",rawpolicy,dict(policy_id="RAW",raw_pin=reader.manifest["input_sources"]["raw"]))
    default=("RIDGE","HGB","LAMBDAMART",*FUSION_MEMBERS,*learners.PARADIGMS);role_order=list(dict.fromkeys(default)) if roles is None else list(roles)
    require(len(set(role_order))==len(role_order) and set(role_order)<=set(learners.PARADIGMS),"UNNAMED_OR_DUPLICATE_PARADIGM")
    for role in role_order:
        try:_train_role(run,journal,reader,rt,role,raw)
        except Exception as exc:
            _block_role_nodes(journal,role,"ROLE_FAILED_NO_SCIENTIFIC_RETRY")
            _role_failure(run,role,exc)
    return assemble_selection(run,reader)


def _fusion_inputs(run,reader,cut):
    banks=[]
    for member in FUSION_MEMBERS:
        parts=[_load_frame(_native_path(run,member,c,"MID"))[0] for c in CUTS[1:-1] if c<cut]
        require(parts,"FULL_MID_TRUE_OOF_REQUIRED");bank=pd.concat(parts,ignore_index=True)
        require(not bank.duplicated(KEYS).any(),"FIXED_MID_OOF_DUPLICATE")
        fields=KEYS+["ticker","U_t_fingerprint","source_kind","source_cutoff","source_capacity","max_train_label_end","cutoff_clock","native_q50" if member=="QUANTILE_HGB" else "native_point"]
        bank=bank[fields].rename(columns={field:member+"__"+("mu" if field.startswith("native_") else field) for field in fields if field not in KEYS+["ticker","U_t_fingerprint"]})
        banks.append(bank)
    keys=banks[0][KEYS+["ticker","U_t_fingerprint"]]
    require(all(keys.equals(b[KEYS+["ticker","U_t_fingerprint"]]) for b in banks),"ALL_SIX_FIXED_MID_OOF_KEYS_EXACT_REQUIRED")
    frame=keys.copy()
    for bank in banks:
        for field in bank.columns:
            if "__" in field:frame[field]=bank[field].to_numpy()
    labels=reader.labels("2020-01-01",cut)
    frame=frame.merge(labels[KEYS+["target","target_end_date"]],on=KEYS,how="inner",validate="one_to_one").rename(columns={"target_end_date":"label_end_date"})
    eligible=labels.loc[labels.signal_date.ge(CUTS[1]) & labels.signal_date.lt(cut)]
    require(keys_digest(frame)==keys_digest(eligible),"META_EVERY_LEGAL_MATURE_PAST_OOF_KEY_REQUIRED")
    vectors=reader.features("2020-01-01",cut);vec=frame[KEYS].merge(vectors,on=KEYS,how="left",validate="one_to_one")
    require(vec.feature_source_present.eq(True).all(),"META_ALL_FULL_U_BASE32_SOURCE_REQUIRED")
    return frame,vec[list(FEATURES)].to_numpy(float),vec[list(cooperation.CONTEXT)].to_numpy(float)


def _fusion_forecast(run,reader,year):
    parts=[_load_frame(Path(run)/"predictions"/"fixed_mid"/(member+"_"+str(year)+".parquet"))[0] for member in FUSION_MEMBERS]
    keys=parts[0][KEYS+["ticker","U_t_fingerprint"]]
    require(all(keys.equals(p[KEYS+["ticker","U_t_fingerprint"]]) for p in parts),"ALL_SIX_FULL_MID_ANNUAL_FORECASTS_REQUIRED")
    mu=np.column_stack([p.native_q50 if member=="QUANTILE_HGB" else p.native_point for member,p in zip(FUSION_MEMBERS,parts)])
    vectors=reader.features(str(year)+"-01-01",str(year+1)+"-01-01")
    require(keys_digest(keys)==keys_digest(vectors),"FUSION_ANNUAL_FULL_U_AXIS_REQUIRED")
    return keys,mu,vectors[list(FEATURES)].to_numpy(float),vectors[list(cooperation.CONTEXT)].to_numpy(float)


def train_fusion(run,methods=None):
    run=Path(run);journal=_TaskLedger(run);reader=FullSelectorReader(run);module=worker_runtime(run)[8];raw=_raw_reference(reader)
    methods=FUSIONS if methods is None else tuple(methods);require(len(set(methods))==len(methods) and set(methods)<=set(FUSIONS),"UNNAMED_FUSION_METHOD")
    dag=learners.single_training_dag()["nodes"]
    for method in methods:
        cid="FUSION_"+method;outputs=[]
        try:
            for year in (2024,2025):
                cut=str(year)+"-01-01";frame,x,context=_fusion_inputs(run,reader,cut);keys,mu,fx,fc=_fusion_forecast(run,reader,year)
                nodes=[n["node_id"] for n in dag if n.get("method")==method and n.get("year")==year]
                identity=dict(method=method,year=year,members=list(FUSION_MEMBERS),keys=keys_digest(frame),base32=array_digest(x),context=array_digest(context),target=array_digest(frame.target),mu=array_digest(frame[[m+"__mu" for m in FUSION_MEMBERS]].to_numpy()),lineage=_frame_hash(frame.drop(columns=["target"])),date_weights="N/(D*N_t)",spec=module.SPEC)
                def work(observe):return cooperation.fit_full_stock_fusion(module,method,frame,cut,x,context,expected_full_day_uids=_expected(frame),on_state=observe)
                fitted=journal.composite_once(nodes,identity,work) if nodes else work(lambda event:require(False,"NATIVE_EQUAL_MEDIAN_MUST_NOT_FIT"))
                require(fitted is not None,"FUSION_COMPLETE_STATE_OR_DEPENDENCY_UNAVAILABLE")
                model,receipt=fitted;annual=keys.copy();annual["score"]=cooperation.predict_full_stock_fusion(model,mu,fx,fc)
                annual["source_kind"]="PIPELINE_OOF";annual["source_cutoff"]=pd.Timestamp(cut);outputs.append(annual)
                _store_frame(run,run/"predictions"/"annual_native"/(cid+"_"+str(year)+".parquet"),annual,identity)
                putj(run/"predictions"/("fusion_receipt_"+method+"_"+str(year)+".json"),receipt)
            _publish_policy(run,reader,cid,pd.concat(outputs,ignore_index=True),raw)
        except Exception as exc:
            _block_role_nodes(journal,method,"FUSION_FAILED_OR_DEPENDENCY_BLOCKED_NO_SCIENTIFIC_RETRY")
            _role_failure(run,cid,exc)
    return assemble_selection(run,reader)


class HybridRiskUnavailable(ValueError):
    """Typed source gap before any alpha scaler/backend may enter."""


def hybrid_training_dag():
    nodes=[]
    for role,family in HYBRIDS:
        cid="HYBRID_"+role+"_"+family
        for cut in CUTS[1:]:
            nodes.append(dict(node_id="SCALER|"+cid+"|"+cut,kind="SCALER",role=cid,paradigm=role,cutoff=cut,representation=learners.SINGLE_HYBRID_U34))
            for cap in learners.CAPACITIES if cut!=CUTS[-1] else ("SELECTED",):
                for component in learners.component_specs(role):
                    nodes.append(dict(node_id=f"MODEL|{cid}|{cut}|{cap}|{component['seed']}|{component['quantile']}",kind="ESTIMATOR",role=cid,paradigm=role,cutoff=cut,capacity=cap,representation=learners.SINGLE_HYBRID_U34,**component))
    counts={kind:sum(n["kind"]==kind for n in nodes) for kind in ("SCALER","ESTIMATOR")}
    require(counts=={"SCALER":24,"ESTIMATOR":120} and len({n["node_id"] for n in nodes})==144,"EXACT144_HYBRID_STATES_REQUIRED")
    return dict(nodes=nodes,counts=counts,learned_operation_ceiling=144,representation=learners.SINGLE_HYBRID_U34,scientific_retries=0)


class _HybridReader:
    """Attach only native family H5 variance/covariance on the original full U.

    Provider keyword contract: (family, signal_date, full_axis) ->
    {frame: full UID-keyed two native columns, qualified_ref: pinned metadata}.
    Training enriches only the original mature alpha keys, while each risk
    source is still computed/qualified against the complete decision-date U.
    """
    representation=learners.SINGLE_HYBRID_U34
    feature_order=tuple(FEATURES)+tuple(learners.SINGLE_RISK_COLUMNS)

    def __init__(self,reader,family,provider):
        self.parent=reader;self.family=family;self.provider=provider;self.cache={};self.refs={}
        self.keys=reader.keys;self.manifest=reader.manifest;self.qualification=reader.qualification

    def labels(self,start,cutoff):return self.parent.labels(start,cutoff)
    def training_vectors(self,start,stop):return self.parent.features(start,stop)
    def features(self,start,stop):return self.enrich_risk(self.parent.features(start,stop))

    def _daily(self,day):
        day=pd.Timestamp(day);key=day.strftime("%Y-%m-%d")
        if key in self.cache:return self.cache[key]
        full=self.keys.loc[self.keys.signal_date.eq(day),KEYS+["ticker","U_t_fingerprint"]].sort_values(KEYS,kind="stable").reset_index(drop=True)
        try:
            result=self.provider(family=self.family,signal_date=day,full_axis=full.copy())
            if not isinstance(result,dict):raise HybridRiskUnavailable("HYBRID_NATIVE_RISK_PROVIDER_OBJECT_REQUIRED")
            ref=result.get("qualified_ref");frame=result.get("frame")
            if not isinstance(ref,dict) or not isinstance(frame,pd.DataFrame):raise HybridRiskUnavailable("HYBRID_NATIVE_FRAME_AND_QUALIFIED_REF_REQUIRED")
            if not (ref.get("status")=="PASS" and ref.get("family")==self.family and ref.get("native_H5") is True and ref.get("axis_complete") is True
                and pd.Timestamp(ref.get("signal_date"))==day and ref.get("full_axis_sha256")==keys_digest(full)
                and pd.Timestamp(ref.get("input_max_date"))<=day):raise HybridRiskUnavailable("HYBRID_COMPLETE_CAUSAL_NATIVE_H5_RISK_REQUIRED")
            source=ref.get("source_ref",{})
            if not (source.get("path") and Path(source["path"]).is_absolute() and source.get("sha256") and sha(source["path"])==source["sha256"]):raise HybridRiskUnavailable("HYBRID_QUALIFIED_RISK_SOURCE_PIN_REQUIRED")
            fields=KEYS+["ticker","U_t_fingerprint",*learners.SINGLE_RISK_COLUMNS]
            if not set(fields)<=set(frame):raise HybridRiskUnavailable("HYBRID_NATIVE_RISK_COLUMNS_REQUIRED")
            frame=frame[fields].sort_values(KEYS,kind="stable").reset_index(drop=True)
            if frame.duplicated(KEYS).any() or not frame[KEYS+["ticker","U_t_fingerprint"]].equals(full):raise HybridRiskUnavailable("HYBRID_RISK_FULL_U_IDENTITY_REQUIRED_NO_DROP")
            values=frame[list(learners.SINGLE_RISK_COLUMNS)].to_numpy(float)
            if not np.isfinite(values).all() or (values[:,0]<0).any():raise HybridRiskUnavailable("HYBRID_FINITE_NATIVE_H5_VARIANCE_COVARIANCE_REQUIRED_NO_FILL")
        except HybridRiskUnavailable:raise
        except Exception as exc:raise HybridRiskUnavailable("HYBRID_NATIVE_RISK_SOURCE_NOT_TESTABLE:"+type(exc).__name__+":"+str(exc)) from exc
        self.cache[key]=frame;self.refs[key]=ref;return frame

    def enrich_risk(self,vectors):
        output=vectors.copy();refs={}
        for day,g in vectors.groupby("signal_date",sort=True):
            risk=self._daily(day);key=pd.Timestamp(day).strftime("%Y-%m-%d");refs[key]=self.refs[key]
            merged=g[KEYS+["ticker","U_t_fingerprint"]].merge(risk,on=KEYS+["ticker","U_t_fingerprint"],how="left",sort=False,validate="one_to_one")
            if len(merged)!=len(g) or not np.isfinite(merged[list(learners.SINGLE_RISK_COLUMNS)].to_numpy(float)).all():raise HybridRiskUnavailable("EVERY_ORIGINAL_MATURE_TRAINING_KEY_REQUIRES_NATIVE_RISK")
            output.loc[g.index,list(learners.SINGLE_RISK_COLUMNS)]=merged[list(learners.SINGLE_RISK_COLUMNS)].to_numpy(float)
        output.attrs["risk_refs"]=refs;return output


def train_hybrids(run,risk_feature_provider):
    """Six frozen U34 heads through the same native/OOF/capacity controller."""
    run=Path(run);journal=_TaskLedger(run);reader=FullSelectorReader(run);rt=worker_runtime(run);raw=_raw_reference(reader)
    require(callable(risk_feature_provider),"HYBRID_NATIVE_RISK_PROVIDER_REQUIRED")
    for role,family in HYBRIDS:
        cid="HYBRID_"+role+"_"+family;hybrid=_HybridReader(reader,family,risk_feature_provider)
        try:_train_role(run,journal,hybrid,rt,role,raw,policy_id=cid)
        except Exception as exc:
            _block_role_nodes(journal,cid,"HYBRID_FAILED_OR_SOURCE_NOT_TESTABLE_NO_SCIENTIFIC_RETRY")
            _role_failure(run,cid,exc)
        finally:putj(run/"predictions"/("hybrid_source_refs_"+cid+".json"),dict(policy_id=cid,representation=learners.SINGLE_HYBRID_U34,feature_order=list(hybrid.feature_order),family=family,qualified_refs=hybrid.refs))
    return assemble_selection(run,reader)


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--run",required=True,type=Path)
    parser.add_argument("command",choices=("catalog","train-primary","train-fusion","train-core","train-selection"));args=parser.parse_args()
    if args.command=="catalog":
        roles,comparisons=catalog();print(json.dumps(dict(roles=roles,comparisons=comparisons,core=list(CORE)),ensure_ascii=False))
    elif args.command=="train-primary":train_primary(args.run)
    elif args.command=="train-fusion":train_fusion(args.run)
    elif args.command=="train-core":
        train_primary(args.run,list(dict.fromkeys(("RIDGE","HGB","LAMBDAMART",*FUSION_MEMBERS))));train_fusion(args.run,("equal",))
    else:train_primary(args.run);train_fusion(args.run)


_CATALOG_REGISTRY_CAPTURE_STAGES_R6 = {
 "policy_catalog_source_metadata_r6":"FIXED214_POLICY_CATALOG_SOURCE_METADATA_R6_PRIOR_TWO_CAPTURE",
 "policy_catalog_cold_r6":"FIXED214_POLICY_CATALOG_COLD_R6_PRIOR_TWO_CAPTURE",
 "policy_catalog_firstentry_r6":"FIXED214_POLICY_CATALOG_FIRSTENTRY_R6_PRIOR_TWO_CAPTURE",
}
def _registry_capture_stage_stem(stage):
    if type(stage) is not str:
        return None
    if stage in _REGISTRY_CAPTURE_STAGES:
        return _REGISTRY_CAPTURE_STAGES[stage]
    return _CATALOG_REGISTRY_CAPTURE_STAGES_R6.get(stage)


# P-only catalog closure component: old registry closed-two functions are untouched.
_CATALOG_METADATA_SCOPE = None
_CATALOG_METADATA_PATH = REPO / "scripts/storage/build_data_catalog.py"
_CATALOG_METADATA_OLD_SHA = "dd57a62a2c337a816e683ddd463444c9a4d4481e132eac0fb27200099aec6e13"
_CATALOG_METADATA_MODULE = "scripts.storage.build_data_catalog"
_CATALOG_ROOT_TOPOLOGY_REF = dict(
    path=str(REPO.parent / "us-tech-quant-cache/V24/C_SELECTOR/FULL_SELECTOR_FIXED_POLICY_FAST_R1/proposals/POLICY_CHECKPOINT_FRESH_OPAQUE_SOURCE_BINDINGS_R5.json"),
    sha256="a4301ab566deba1a472deaabfdc357c883c5bd874eb6b5bec7631861c1c858a7")
_CATALOG_CAPTURE_STAGES = {
    "policy_catalog_source_metadata_r6": "FIXED214_POLICY_CATALOG_SOURCE_METADATA_R6_NONEXECUTED_CAPTURE",
    "policy_catalog_nonexecuted_cold_r1": "FIXED214_POLICY_CATALOG_COLD_R1_NONEXECUTED_CAPTURE",
    "policy_catalog_nonexecuted_firstentry_r1": "FIXED214_POLICY_CATALOG_FIRSTENTRY_R1_NONEXECUTED_CAPTURE",
}


class NonexecutingCatalogExecutionForbidden(NonexecutingRegistryExecutionForbidden):
    pass


def _catalog_metadata_capture_policy():
    members = {
        "registry": dict(path=str(_REGISTRY_METADATA_PATH.resolve()), original_logical_sha256=_REGISTRY_METADATA_OLD_SHA),
        "stateful_fusion": dict(path=str(_STATEFUL_FUSION_METADATA_PATH.resolve()), original_logical_sha256=_STATEFUL_FUSION_METADATA_OLD_SHA),
        "catalog": dict(path=str(_CATALOG_METADATA_PATH.resolve()), original_logical_sha256=_CATALOG_METADATA_OLD_SHA),
    }
    return dict(schema="FIXED_CATALOG_PLUS_PRIOR_TWO_NONEXECUTED_CAPTURE_POLICY_R2",
                run=str(_SOURCE_CORRECTION_R4_RUN.resolve()), paths=members,
                original_source_count=99, execution_source_count=96, nonexecuted_source_count=3,
                source_max_bytes=32768, capture="OPAQUE_BYTES_ONCE_AT_EXPLICIT_NEW_SCOPE_ENTRY",
                historical_actual_old_catalog_bytes="UNKNOWN", current_after_capture="UNKNOWN",
                scientific_execution_admission=False,
                root_topology_manifest_ref=dict(_CATALOG_ROOT_TOPOLOGY_REF),
                root_source_hash_max_bytes=1048576,
                approved_root_scope="ORIGINAL99_PLUS_RUNTIME5_PLUS_EXISTING10_EXECUTION_OVERRIDES",
                stages=dict(_CATALOG_CAPTURE_STAGES))


def _catalog_metadata_control_bytes(value, expected_path, cap):
    import hashlib
    import os
    require(type(value) is dict and set(value) == {"path", "sha256"}
            and type(value["path"]) is str and type(value["sha256"]) is str
            and len(value["sha256"]) == 64
            and all(c in "0123456789abcdef" for c in value["sha256"]),
            "CATALOG_CLOSED_CONTROL_REF")
    path = Path(value["path"]).resolve()
    require(path == Path(expected_path).resolve(), "CATALOG_EXACT_CONTROL_PATH")
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        identity = (before.st_size, before.st_mtime_ns, before.st_ino)
        require(0 < before.st_size <= cap, "CATALOG_CONTROL_CAP_BEFORE_READ")
        payload = handle.read(before.st_size)
        after = os.fstat(handle.fileno())
        require(len(payload) == before.st_size
                and (after.st_size, after.st_mtime_ns, after.st_ino) == identity,
                "CATALOG_CONTROL_HANDLE_CHANGED")
    require(hashlib.sha256(payload).hexdigest() == value["sha256"], "CATALOG_CONTROL_PIN_CHANGED")
    return payload


def _catalog_metadata_read_control(value, expected_path, cap):
    return json.loads(_catalog_metadata_control_bytes(value, expected_path, cap))


def _catalog_metadata_authority(run, stage, authority_ref, design_sources):
    run = Path(run).resolve()
    require(run == _SOURCE_CORRECTION_R4_RUN.resolve() and stage in _CATALOG_CAPTURE_STAGES,
            "CATALOG_FIXED_RUN_AND_NEW_STAGE_ONLY")
    require(type(design_sources) is dict and len(design_sources) == 99, "CATALOG_ORIGINAL99_REQUIRED")
    policy = _catalog_metadata_capture_policy()
    for item in policy["paths"].values():
        require(design_sources.get(item["path"]) == item["original_logical_sha256"],
                "CATALOG_EXACT_ORIGINAL_THREE_DECLARATIONS")
    authority = _catalog_metadata_read_control(
        authority_ref, run / "ENGINEERING_POLICY_CATALOG_NONEXECUTED_SOURCE_ANNEX_R2.json", 32768)
    expected_fields = {
        "schema", "status", "research_id", "run", "prior_R5_source_ref",
        "original99_sources_sha256", "catalog_original_ref", "catalog_as_observed_ref",
        "nonexecuted_capture_policy", "independent_review_ref", "grants_scientific_execution",
        "root_topology_manifest_ref", "current_runtime_source_refs", "execution_overrides",
        "source_intent_payload_sha256",
    }
    require(set(authority) == expected_fields
            and authority["schema"] == "FULL_SELECTOR_POLICY_CATALOG_NONEXECUTED_SOURCE_ANNEX_R2"
            and authority["status"] == "PASS" and authority["research_id"] == ID
            and authority["run"] == str(run), "CATALOG_CLOSED_NEW_ANNEX")
    require(authority["prior_R5_source_ref"] == dict(
        path=str(run / "ENGINEERING_POLICY_CHECKPOINT_EXACT_JOINT_ALLOCATION_SOURCE_R5.json"),
        sha256="95b948bc6c949afac49e1957c9b9dd1a759d0b6102e43a8c8a2331b71006165e"),
        "CATALOG_EXACT_PRIOR_R5_SOURCE_HISTORY")
    _catalog_metadata_control_bytes(authority["prior_R5_source_ref"],
        run / "ENGINEERING_POLICY_CHECKPOINT_EXACT_JOINT_ALLOCATION_SOURCE_R5.json", 32768)
    require(authority["original99_sources_sha256"] == digest(design_sources)
            and authority["catalog_original_ref"] == dict(
                path=str(_CATALOG_METADATA_PATH.resolve()), sha256=_CATALOG_METADATA_OLD_SHA)
            and authority["nonexecuted_capture_policy"] == policy
            and authority["grants_scientific_execution"] is False,
            "CATALOG_ORIGINAL99_POLICY_NO_SCIENCE_ADMISSION")
    require(type(authority["source_intent_payload_sha256"]) is str
            and len(authority["source_intent_payload_sha256"]) == 64
            and all(ch in "0123456789abcdef" for ch in authority["source_intent_payload_sha256"]),
            "CATALOG_FIXED_SEVEN_FIELD_SOURCE_INTENT_DIGEST")
    observed = authority["catalog_as_observed_ref"]
    require(type(observed) is dict and set(observed) == {"path", "sha256", "bytes"}
            and observed["path"] == str(_CATALOG_METADATA_PATH.resolve())
            and type(observed["sha256"]) is str and len(observed["sha256"]) == 64
            and all(c in "0123456789abcdef" for c in observed["sha256"])
            and type(observed["bytes"]) is int and 0 < observed["bytes"] <= 32768,
            "CATALOG_CLOSED_OBSERVED_REF_NOT_OLD_PHYSICAL_PASS")
    review = _catalog_metadata_read_control(
        authority["independent_review_ref"],
        run / "maintenance/POLICY_CATALOG_NONEXECUTED_SOURCE_ANNEX_INDEPENDENT_REVIEW_R2.json", 32768)
    payload = {key: value for key, value in authority.items() if key not in {"status", "independent_review_ref"}}
    require(review.get("schema") == "FULL_SELECTOR_POLICY_CATALOG_NONEXECUTED_SOURCE_INDEPENDENT_REVIEW_R2"
            and review.get("status") == "PASS" and review.get("research_id") == ID
            and review.get("source_payload_sha256") == digest(payload)
            and review.get("source_intent_payload_sha256") == authority["source_intent_payload_sha256"]
            and review.get("capture_policy") == policy
            and review.get("historical_actual_old_catalog_bytes") == "UNKNOWN"
            and all(review.get(k) is True for k in (
                "independent_from_source_writer", "original99_authority_preserved",
                "new_96_plus3_partition_only", "old_closed_two_policy_and_stages_unchanged",
                "bounded_known_roots_and_read_import_compile_exec_fence_verified"))
            and review.get("grants_scientific_execution") is False,
            "CATALOG_NEW_INDEPENDENT_SOURCE_SCOPE_REQUIRED")
    return authority


def _catalog_metadata_approved_root_paths(authority, design_sources):
    # The pinned original declaration remains99. Runtime and physical override
    # paths enlarge only the finite cache metadata roots, never scientific IDs.
    topology_ref = authority["root_topology_manifest_ref"]
    require(topology_ref == _CATALOG_ROOT_TOPOLOGY_REF,
            "CATALOG_EXACT_ACCEPTED_ROOT_TOPOLOGY_MANIFEST")
    topology_path = Path(_CATALOG_ROOT_TOPOLOGY_REF["path"])
    topology = _catalog_metadata_read_control(topology_ref, topology_path, 32768)
    require(type(design_sources) is dict and topology["original_sources"] == design_sources,
            "CATALOG_EXACT_ACCEPTED_ORIGINAL99_DECLARATION")
    original_runtime = topology["current_runtime_source_refs"]
    original_overrides = topology["execution_overrides"]
    runtime, overrides = authority["current_runtime_source_refs"], authority["execution_overrides"]
    require(type(runtime) is dict and set(runtime) == {
        "controller", "entry", "recovery_owner", "source_guard_owner", "workflow"}
        and set(runtime) == set(original_runtime)
        and type(overrides) is dict and set(overrides) == set(original_overrides)
        and len(overrides) == 10, "CATALOG_EXACT_RUNTIME5_AND_OVERRIDE10_ROOTS")
    runtime_by_path = {}
    for key, old_ref in original_runtime.items():
        value = runtime[key]
        require(type(value) is dict and set(value) == {"path", "sha256"}
                and value["path"] == old_ref["path"], "CATALOG_FIXED_RUNTIME_PHYSICAL_PATH")
        _catalog_metadata_control_bytes(value, old_ref["path"], 1048576)
        runtime_by_path[value["path"]] = value
    for logical, old_ref in original_overrides.items():
        require(logical in design_sources, "CATALOG_OVERRIDE_LOGICAL_IS_ORIGINAL_SOURCE")
        expected = runtime_by_path.get(old_ref["path"], old_ref)
        require(overrides[logical] == expected, "CATALOG_FIXED_EXISTING_OVERRIDE_PHYSICAL_REF")
        if old_ref["path"] not in runtime_by_path:
            _catalog_metadata_control_bytes(dict(expected), old_ref["path"], 1048576)
    roots = frozenset(Path(value).resolve() for value in (
        *design_sources, *(v["path"] for v in runtime.values()),
        *(v["path"] for v in overrides.values())))
    require(99 <= len(roots) <= 114, "CATALOG_APPROVED_ROOT_UNION_BOUND")
    return roots


def _catalog_metadata_no_cached_modules(blocked, approved_paths):
    import functools
    import importlib.machinery
    import io
    import os
    import sys
    import types
    blocked = frozenset(Path(p).resolve() for p in blocked)
    approved_paths = frozenset(Path(p).resolve() for p in approved_paths)
    require(99 <= len(approved_paths) <= 114, "CATALOG_CLOSED_APPROVED_PHYSICAL_ROOT_BOUND")
    modules = tuple(sys.modules.items())
    require(len(modules) <= 8192, "CATALOG_MODULE_METADATA_BOUND")
    roots = []
    approved_module_names = set()
    direct_count = 0

    def physical(value):
        if value is None or (type(value) is str or type(value) is bytes) and not value:
            return None
        require(any(type(value) is cls for cls in (str, bytes, type(Path()))),
                "CATALOG_SAFE_PHYSICAL_METADATA_TYPE")
        return Path(os.fsdecode(value)).resolve()

    def class_space(value):
        return type.__dict__["__dict__"].__get__(value, type(value))

    def class_bases(value):
        return type.__dict__["__bases__"].__get__(value, type(value))

    def raw_mro(cls):
        return type.__dict__["__mro__"].__get__(cls, type(cls))

    def raw_instance(value, parent):
        return any(base is parent for base in raw_mro(type(value)))

    def instance_space(value):
        queue, seen_classes = [type(value)], set()
        while queue:
            cls = queue.pop(0)
            if id(cls) in seen_classes:
                continue
            seen_classes.add(id(cls))
            require(len(seen_classes) <= 128, "CATALOG_INSTANCE_CLASS_BOUND")
            own = class_space(cls)
            descriptor = own.get("__dict__")
            if descriptor is not None:
                require(type(descriptor) is types.GetSetDescriptorType,
                        "CATALOG_UNSAFE_INSTANCE_DICT_DESCRIPTOR")
                result = descriptor.__get__(value, type(value))
                require(type(result) is dict, "CATALOG_EXACT_INSTANCE_DICT")
                return result
            queue.extend(class_bases(cls))
        require(False, "CATALOG_PROJECT_INSTANCE_METADATA_UNAVAILABLE")

    def code_origin(value):
        if type(value) is types.FunctionType:
            return physical(value.__code__.co_filename)
        if type(value) is types.MethodType:
            return physical(value.__func__.__code__.co_filename)
        if type(value) is types.CodeType:
            return physical(value.co_filename)
        return None

    for name, module in modules:
        require(name != _CATALOG_METADATA_MODULE, "CATALOG_CACHED_CANONICAL_MODULE")
        if not raw_instance(module, types.ModuleType):
            continue
        space = types.ModuleType.__dict__["__dict__"].__get__(module, type(module))
        origins = [space.get("__file__")]
        spec = space.get("__spec__")
        if raw_instance(spec, importlib.machinery.ModuleSpec):
            spec_space = instance_space(spec)
            origins.append(spec_space.get("origin"))
            loader = spec_space.get("loader")
            if any(raw_instance(loader, parent) for parent in (
                    importlib.machinery.SourceFileLoader,
                    importlib.machinery.SourcelessFileLoader,
                    importlib.machinery.ExtensionFileLoader)):
                origins.append(instance_space(loader).get("path"))
            elif loader is not None:
                require(not any(physical(p) in approved_paths for p in origins
                                if not (type(p) is str and p in ("built-in", "frozen"))),
                        "CATALOG_APPROVED_OWNER_LOADER_METADATA_UNSUPPORTED")
        elif spec is not None:
            require(not any(physical(p) in approved_paths for p in origins),
                    "CATALOG_APPROVED_OWNER_SPEC_METADATA_UNSUPPORTED")
        resolved_origins = tuple(physical(p) for p in origins
                                 if not (type(p) is str and p in ("built-in", "frozen")))
        require(not any(p in blocked for p in resolved_origins), "CATALOG_CACHED_MODULE_PATH_ALIAS")
        values = tuple(v for k, v in space.items() if k != "_CATALOG_METADATA_SCOPE")
        direct_count += len(values)
        require(direct_count <= 500000, "CATALOG_DIRECT_GLOBAL_METADATA_BOUND")
        require(not any(code_origin(v) in blocked for v in values), "CATALOG_CACHED_DIRECT_CALLABLE")
        # The reviewed original99/runtime5/override10 path union covers __main__ and
        # approved owners loaded under private module names. No arbitrary heap roots.
        if any(p in approved_paths for p in resolved_origins):
            approved_module_names.add(name)
            roots.extend(values)
    seen = set()
    pending = [(value, 0) for value in roots]
    while pending:
        value, depth = pending.pop()
        marker = id(value)
        if marker in seen:
            continue
        seen.add(marker)
        require(len(seen) <= 50000 and depth <= 16, "CATALOG_KNOWN_ROOT_RECURSION_BOUND")
        require(code_origin(value) not in blocked, "CATALOG_CACHED_KNOWN_ROOT_CALLABLE")
        more = ()
        if type(value) is types.FunctionType:
            more = (*(value.__defaults__ or ()), *(value.__kwdefaults__ or {}).values())
            cells = []
            for cell in value.__closure__ or ():
                try:
                    cells.append(cell.cell_contents)
                except ValueError:
                    pass
            more = (*more, *cells)
        elif type(value) is types.MethodType:
            more = (value.__func__, value.__self__)
        elif raw_instance(value, type):
            more = (*class_space(value).values(), *class_bases(value))
        elif any(type(value) is cls for cls in (staticmethod, classmethod)):
            more = (value.__func__,)
        elif type(value) is property:
            more = tuple(v for v in (value.fget, value.fset, value.fdel) if v is not None)
        elif raw_instance(value, functools.partial):
            require(type(value) is functools.partial, "CATALOG_PARTIAL_SUBCLASS_METADATA_UNSUPPORTED")
            more = (value.func, *value.args, *(value.keywords or {}).values())
        elif type(value) is dict:
            require(len(value) <= 50000, "CATALOG_KNOWN_ROOT_CONTAINER_BOUND")
            more = (*value.keys(), *value.values())
        elif any(type(value) is cls for cls in (list, tuple, set, frozenset)):
            require(len(value) <= 50000, "CATALOG_KNOWN_ROOT_CONTAINER_BOUND")
            more = tuple(value)
        elif any(type(value) is cls for cls in (io.FileIO, io.BufferedReader, io.BufferedWriter,
                                               io.BufferedRandom, io.TextIOWrapper)):
            name = value.name
            require(type(name) is not int, "CATALOG_KNOWN_RAW_FD_CHANNEL_FORBIDDEN")
            require(physical(name) not in blocked, "CATALOG_KNOWN_PREOPENED_FILE_CHANNEL")
        else:
            cls = type(value)
            owner = class_space(cls).get("__module__")
            project_instance = (type(owner) is str
                                and (owner in approved_module_names or owner.startswith(("scripts.", "ustq"))))
            if project_instance or type(value) is types.SimpleNamespace:
                class_queue, checked = [cls], set()
                while class_queue:
                    base = class_queue.pop()
                    if id(base) in checked:
                        continue
                    checked.add(id(base))
                    require(len(checked) <= 128, "CATALOG_PROJECT_INSTANCE_CLASS_BOUND")
                    slots = class_space(base).get("__slots__", ())
                    require(any(type(slots) is cls for cls in (str, tuple, list))
                            and not any(type(v) is not str or v not in ("__dict__", "__weakref__")
                                        for v in ((slots,) if type(slots) is str else slots)),
                            "CATALOG_PROJECT_INSTANCE_SLOTS_UNSUPPORTED")
                    class_queue.extend(class_bases(base))
                values = instance_space(value)
                require(len(values) <= 50000, "CATALOG_PROJECT_INSTANCE_DICT_BOUND")
                more = (cls, *values.values())
        pending.extend((v, depth + 1) for v in more)
    return dict(module_count=len(modules), direct_metadata_count=direct_count,
                known_root_objects=len(seen), approved_physical_root_count=len(approved_paths),
                scope="BOUNDED_ORIGINAL99_RUNTIME5_OVERRIDE10_PHYSICAL_ROOTS_NOT_ALL_PYTHON_HEAP")


def _catalog_metadata_capture_one(path, target):
    import hashlib
    import os
    state = _CATALOG_METADATA_SCOPE
    require(state is not None and state["active"] and state["capturing"]
            and Path(path).resolve() == state["live"] and Path(target).resolve() == state["custody"],
            "CATALOG_PRIVATE_FIXED_OPAQUE_CAPTURE_ONLY")
    value = hashlib.sha256()
    count = 0
    with open(path, "rb") as src, open(target, "xb") as dst:
        before = os.fstat(src.fileno())
        identity = (before.st_size, before.st_mtime_ns, before.st_ino)
        require(before.st_size == state["expected_observed"]["bytes"]
                and 0 < before.st_size <= 32768, "CATALOG_CAPTURE_CAP_BEFORE_READ")
        remaining = before.st_size
        while remaining:
            block = src.read(min(65536, remaining))
            require(bool(block), "CATALOG_CAPTURE_UNEXPECTED_EOF")
            remaining -= len(block)
            count += len(block)
            dst.write(block)
            value.update(block)
        after = os.fstat(src.fileno())
        require((after.st_size, after.st_mtime_ns, after.st_ino) == identity,
                "CATALOG_CAPTURE_HANDLE_CHANGED")
    actual = dict(path=str(Path(target).resolve()), sha256=value.hexdigest())
    require(count == state["expected_observed"]["bytes"]
            and actual["sha256"] == state["expected_observed"]["sha256"],
            "CATALOG_AS_OBSERVED_BYTES_REQUIRED_NOT_OLD_IDENTITY")
    return actual, count


def _catalog_metadata_verify_capture_ref(value):
    import hashlib
    import os
    state = _CATALOG_METADATA_SCOPE
    require(state is not None and state["active"] and not state["capturing"]
            and value == state.get("custody_ref") and set(value) == {"path", "sha256"}
            and Path(value["path"]).resolve() == state["custody"], "CATALOG_EXACT_CAPTURE_REF_ONLY")
    result = hashlib.sha256()
    with open(value["path"], "rb") as handle:
        before = os.fstat(handle.fileno())
        identity = (before.st_size, before.st_mtime_ns, before.st_ino)
        require(0 < before.st_size <= 32768 and before.st_size == state["expected_observed"]["bytes"],
                "CATALOG_CAPTURE_VERIFY_CAP_BEFORE_READ")
        remaining = before.st_size
        while remaining:
            block = handle.read(min(65536, remaining))
            require(bool(block), "CATALOG_VERIFY_UNEXPECTED_EOF")
            remaining -= len(block)
            result.update(block)
        after = os.fstat(handle.fileno())
        require((after.st_size, after.st_mtime_ns, after.st_ino) == identity,
                "CATALOG_VERIFY_HANDLE_CHANGED")
    require(result.hexdigest() == value["sha256"], "CATALOG_IMMUTABLE_CAPTURE_CHANGED")
    return state["custody"]


def _catalog_metadata_assert_fence(state, probes):
    require(_CATALOG_METADATA_SCOPE is state and state["active"]
            and not state["capturing"]
            and type(__import__("sys").meta_path) is list
            and any(item is state["finder"] for item in __import__("sys").meta_path),
            "CATALOG_ACTIVE_STATE_AND_SAME_FINDER_REQUIRED")
    require(all(globals().get(name) is obj and obj.__code__ is code
                for name, obj, code in state["helpers"]), "CATALOG_SEALED_HELPER_IDENTITY")
    observation = _catalog_metadata_no_cached_modules((state["live"], state["custody"]), state["approved_paths"])
    require(digest(_catalog_metadata_capture_policy()) == state["policy_sha256"]
            and _CATALOG_METADATA_OLD_SHA == state["original_catalog_sha256"],
            "CATALOG_CAPTURE_POLICY_OR_ORIGINAL_DECLARATION_CHANGED")
    _catalog_metadata_verify_capture_ref(state["custody_ref"])
    _catalog_metadata_control_bytes(dict(state["receipt_ref"]), state["receipt"], 8192)
    for path, code in probes:
        for probe in (lambda p=path: open(p, "rb"),
                      lambda p=path: compile("pass", str(p), "exec"),
                      lambda c=code: exec(c, {})):
            try:
                probe()
            except NonexecutingCatalogExecutionForbidden:
                continue
            require(False, "CATALOG_ACTIVE_READ_COMPILE_EXEC_PROBE_NOT_DENIED")
    return observation


def _catalog_metadata_source_binding(logical, expected, design_sources):
    state = _CATALOG_METADATA_SCOPE
    require(state is not None and state["active"] and not state["capturing"]
            and Path(logical).resolve() == state["live"] and expected == _CATALOG_METADATA_OLD_SHA
            and digest(design_sources) == state["original99_digest"],
            "CATALOG_BINDING_ONLY_INSIDE_NEW_AUTHORIZED_CAPTURE")
    _catalog_metadata_assert_fence(state, state["probes"])
    require(dict(state["observed_ref"]) == dict(path=str(state["live"]), sha256=state["custody_ref"]["sha256"]),
            "CATALOG_OBSERVED_AND_CUSTODY_BINDING_CHANGED")
    return dict(original_logical_ref=dict(path=str(state["live"]), sha256=expected),
                as_observed_nonexecuted_ref=dict(state["observed_ref"]), custody_ref=dict(state["custody_ref"]),
                purpose="NONEXECUTED_CLOSURE_METADATA", old_physical_identity="UNKNOWN",
                scientific_execution_admission=False)


@contextmanager
def catalog_nonexecuting_metadata_scope(run, capture_stage, authority_ref, design_sources, main_source_ref=None):
    import os
    import sys
    from types import MappingProxyType, CodeType
    from datetime import datetime, timezone
    global _CATALOG_METADATA_SCOPE
    require(_CATALOG_METADATA_SCOPE is None, "CATALOG_EXCLUSIVE_NEW_SCOPE")
    run = Path(run).resolve()
    authority = _catalog_metadata_authority(run, capture_stage, authority_ref, design_sources)
    if capture_stage == "policy_catalog_source_metadata_r6":
        require(main_source_ref is None, "CATALOG_METADATA_PROBE_NO_MAIN_SOURCE_ACTIVATION")
    else:
        require(main_source_ref is not None, "CATALOG_COLD_FIRSTENTRY_ACTUAL_MAIN_REVIEW_REQUIRED")
        from scripts.research.a2.training import full_selector_source_guard_recovery as sg
        sg.catalog_source_review_preflight(sys.modules[__name__], main_source_ref, authority_ref, authority["source_intent_payload_sha256"])
    live = _CATALOG_METADATA_PATH.resolve()
    folder = run / "maintenance"
    stem = _CATALOG_CAPTURE_STAGES[capture_stage]
    custody, receipt = folder / (stem + ".catalog.opaque-source"), folder / (stem + ".json")
    for path in (custody, receipt):
        assert_safe_output_path(path, kind="backtest", paths=resolve(REPO))
    require(folder.is_dir() and live.is_file() and live.stat().st_size <= 32768
            and not custody.exists() and not receipt.exists(), "CATALOG_EXCLUSIVE_FIXED_CAPTURE_SLOTS")
    approved_paths = _catalog_metadata_approved_root_paths(authority, design_sources)
    _catalog_metadata_no_cached_modules((live, custody), approved_paths)
    probes = tuple((path, compile("pass", str(path), "exec")) for path in (live, custody))
    state = dict(active=False, capturing=False, live=live, custody=custody, receipt=receipt,
                 capture_stage=capture_stage, authority_ref=MappingProxyType(dict(authority_ref)),
                  approved_paths=approved_paths, probes=probes,
                 expected_observed=MappingProxyType(dict(authority["catalog_as_observed_ref"])),
                 original99_digest=digest(design_sources), policy_sha256=digest(authority["nonexecuted_capture_policy"]),
                 original_catalog_sha256=_CATALOG_METADATA_OLD_SHA)
    capture_obj, verify_obj = _catalog_metadata_capture_one, _catalog_metadata_verify_capture_ref
    state["helpers"] = tuple((fn.__name__, fn, fn.__code__) for fn in (
        capture_obj, verify_obj, _catalog_metadata_no_cached_modules, _catalog_metadata_assert_fence,
        _catalog_metadata_source_binding, _catalog_metadata_control_bytes, _catalog_metadata_capture_policy,
        _catalog_metadata_approved_root_paths))
    capture_code, verify_code = capture_obj.__code__, verify_obj.__code__
    meta_path = sys.meta_path
    require(type(meta_path) is list, "CATALOG_EXACT_META_PATH_LIST")

    def has_code(code):
        # Only the immediate open caller, never an arbitrary ancestor frame.
        return sys._getframe(2).f_code is code

    class CatalogFinder:
        def find_spec(self, fullname, path=None, target=None):
            if state["active"] and fullname == _CATALOG_METADATA_MODULE:
                raise NonexecutingCatalogExecutionForbidden("CATALOG_CANONICAL_IMPORT_FORBIDDEN")
            return None

    finder = CatalogFinder()
    state["finder"] = finder

    def audit(event, args):
        if not state["active"]:
            return
        if event == "import" and args and args[0] == _CATALOG_METADATA_MODULE:
            raise NonexecutingCatalogExecutionForbidden("CATALOG_CANONICAL_IMPORT_FORBIDDEN")
        if event in ("compile", "exec") and args:
            if event == "compile":
                if len(args) < 2:
                    raise NonexecutingCatalogExecutionForbidden("CATALOG_UNSUPPORTED_COMPILE_AUDIT_METADATA")
                filename = args[1]
            else:
                if type(args[0]) is not CodeType:
                    raise NonexecutingCatalogExecutionForbidden("CATALOG_UNSUPPORTED_EXEC_AUDIT_METADATA")
                filename = args[0].co_filename
            if not any(type(filename) is cls for cls in (str, bytes, type(Path()))):
                raise NonexecutingCatalogExecutionForbidden("CATALOG_UNSUPPORTED_CODE_PATH_METADATA")
            if Path(os.fsdecode(filename)).resolve() in {live, custody}:
                raise NonexecutingCatalogExecutionForbidden("CATALOG_SOURCE_CODE_FORBIDDEN")
        if event == "open" and args:
            if type(args[0]) is int:
                # A descriptor is not path metadata; only the bounded known-root
                # preopened-channel check covers it. No all-heap/OS sandbox claim.
                return
            if not any(type(args[0]) is cls for cls in (str, bytes, type(Path()))):
                raise NonexecutingCatalogExecutionForbidden("CATALOG_UNSUPPORTED_OPEN_PATH_METADATA")
            physical = Path(os.fsdecode(args[0])).resolve()
            if physical in {live, custody}:
                capture_allowed = state["capturing"] and has_code(capture_code)
                verify_allowed = physical == custody and not state["capturing"] and has_code(verify_code)
                if not (capture_allowed or verify_allowed):
                    raise NonexecutingCatalogExecutionForbidden("CATALOG_CONTENT_READ_FORBIDDEN")
    view = MappingProxyType(state)
    installed = False
    try:
        _CATALOG_METADATA_SCOPE = view
        state["active"] = state["capturing"] = True
        sys.addaudithook(audit)
        meta_path.insert(0, finder)
        installed = True
        custody_ref, count = capture_obj(live, custody)
        state["custody_ref"] = MappingProxyType(dict(custody_ref))
        state["observed_ref"] = MappingProxyType(dict(path=str(live), sha256=custody_ref["sha256"]))
        state["capturing"] = False
        payload = dict(schema="FIXED214_CATALOG_NONEXECUTED_CLOSURE_CAPTURE_R1",
            run=str(run), capture_stage=capture_stage, policy=_catalog_metadata_capture_policy(),
            authority_ref=authority_ref, original99_sources_sha256=digest(design_sources),
            original_logical_ref=authority["catalog_original_ref"],
            observed_live_ref=dict(state["observed_ref"]), custody_ref=dict(custody_ref), bytes=count,
            observed_utc=datetime.now(timezone.utc).isoformat(),
            historical_actual_old_catalog_bytes="UNKNOWN", current_after_capture="UNKNOWN",
            source_execution_authorized=False, full_SOURCE_phase_admission_still_required=True)
        with receipt.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, indent=2, allow_nan=False)
            handle.write("\n")
        state["receipt_ref"] = MappingProxyType(dict(path=str(receipt), sha256=sha(receipt)))
        observation = _catalog_metadata_assert_fence(view, probes)
        yield dict(payload, receipt_ref=dict(state["receipt_ref"]), bounded_cache_metadata=observation)
        _catalog_metadata_assert_fence(view, probes)
    finally:
        changed = (_CATALOG_METADATA_SCOPE is not view or sys.meta_path is not meta_path
                   or (installed and not any(item is finder for item in meta_path)))
        state["active"] = state["capturing"] = False
        _CATALOG_METADATA_SCOPE = None
        list.__setitem__(meta_path, slice(None), [item for item in meta_path if item is not finder])
        sys.meta_path = meta_path
        if changed:
            error = sys.exc_info()[1]
            if error is not None:
                error.add_note("CATALOG_STATE_OR_FINDER_CHANGED_CLEANUP_COMPLETED")
            else:
                require(False, "CATALOG_STATE_OR_FINDER_CHANGED_CLEANUP_COMPLETED")

