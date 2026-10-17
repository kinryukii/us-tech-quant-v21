
"""V24 continuation orchestration; common policies/account remain single owners.

The parent freezes and records are read-only. This module binds new Raw held
input scope and explicit slippage before any new replay, retains failures, and
never selects from an uncertified account or from 2026 observations.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.data.joint_input_binding import guard_parquet, load_training_inputs
from scripts.research.a2.evaluation.joint_method_coverage import JointMethodCoverage
from scripts.research.a2.evaluation.joint_method_stages import task_writer
from scripts.research.a2.evaluation import joint_method_accounts as methods
from scripts.research.a2.evaluation import joint_account_runtime as runtime
from scripts.research.a2.evaluation.joint_execution_resume import digest
from scripts.research.a2.portfolio import joint_allocation_methods as allocation
from scripts.research.a2.inference.joint_portfolio_policy import JointResearchPolicy
from scripts.research.a2.inference.joint_stateful_policy import RuleStatefulPolicy
from scripts.research.a2.evaluation import continuous_research_account as common

CACHE_SHA = "98d5d499576b62d7491fcc92890ac1c10b370ca9114636f8feae9a1fa335b5b3"
WRAPPER_SHA = "57ace7d28e6366fe08fb325aa63aeb7db000eae007172920c82f346122bbd38a"
ALLOCATION_SHA = "0feae460e1de42fb712ae2a035bf6fcbd48f22f96e7e4c97db2cf1309e721250"
INPUT_SHA = "a9ff56bd5feb2b90fb836fde3258102a4893a8abdecbb780a9864961867e0fc2"
PRIMARY_BPS = 10
SCENARIOS = (5, 10, 20)
R3_STAGE = "continuation/cash_r3"
R4_STAGE = "continuation/cash_r4"
CONTROL_ONLY_STAGES = (R3_STAGE,R4_STAGE)
STAGES = ("continuation","continuation/cash_r1","continuation/cash_r2",R3_STAGE,R4_STAGE)
R2_CASH_FREEZE_SHA = "0c3222f3e485a0030a5da0fff2eee2992767e3270ff7835b031d8cf922e789aa"
R2_CASH_RECEIPT_SHA = "aa17fa8876c077035954cde93b1f45f43cd384dc44556cf77120e96d4e5b15f0"
OLD_XP_SOURCE_SHA = "22676791739cf2adb16c023f707cd3858f24098ed771b42a61d818ff468682dc"
OLD_XP_SOURCE_REL = "sources/BP_XP_FCNCA_GM_Q3/XP_2023-09-11.official_reader_facts.json"
SCENARIO_ALLOCATION = {"mean_cvar","mean_es","kelly","log_growth","mean_semivariance"}

def continuation_roles():
    """Current one-layer roles; exact old aliases do not become new fits."""
    roles = {p:dict(s) for p,s in methods.catalogue().items()
             if p in methods.CONTROLS or p == methods.ANCHOR
             or (p.startswith("M") and p[1:].isdigit() and 50 <= int(p[1:]) <= 106)}
    for pid in ("M052","M058","M064","M066"):
        roles.pop(pid, None)
    roles["M090"] = dict(roles[methods.ANCHOR], allocation="cost_aware", rho=1.)
    roles["MV_FULL_REBALANCE_CONTROL"] = dict(roles[methods.ANCHOR], allocation="mean_variance", rho=1.)
    return roles

def validate_stage_operation(stage,phase,bps):
    if stage not in STAGES:raise ValueError("UNREGISTERED_CONTINUATION_STAGE")
    if stage in CONTROL_ONLY_STAGES and (phase not in ("cash-freeze","controls","control-gate")
                           or type(bps) is not int or bps!=PRIMARY_BPS):
        raise ValueError("R3_CONTROLS_ONLY_10BPS")
    if phase=="control-gate" and stage not in CONTROL_ONLY_STAGES:
        raise ValueError("CONTROL_GATE_REQUIRES_R3_OR_R4")


def stage_roles(stage):
    if stage in CONTROL_ONLY_STAGES:
        catalogue=methods.catalogue()
        return {p:dict(catalogue[p]) for p in methods.CONTROLS}
    return continuation_roles()


def validate_control_records(status):
    attempts=combined_account_attempts(status.get("attempts"),0)
    records=status.get("records")
    if attempts>2 or not isinstance(records,list) or len(records)>2:
        raise ValueError("R3_CONTROL_SCOPE_OR_BUDGET_CHANGED")
    seen=set();physical=0
    for record in records:
        pid=record.get("policy_path_id")
        if (pid not in methods.CONTROLS or record.get("bps")!=PRIMARY_BPS
                or record.get("path_id")!=pid+"_S10" or pid in seen):
            raise ValueError("R3_CONTROL_ROLE_CHANGED_OR_DUPLICATED")
        seen.add(pid)
        if record.get("status") not in ("STARTED","COMPLETE","FAILED_RETAINED",
                                        "INTERRUPTED_FAILURE_RETAINED","BLOCKED_DEPENDENCY"):
            raise ValueError("R3_UNKNOWN_ACCOUNT_STATUS")
        physical+=record["status"]!="BLOCKED_DEPENDENCY"
    if attempts!=physical:raise ValueError("R3_CONTROL_ATTEMPTS_CHANGED")
    return records


def _verified_dependency(item,error="CASH_SOURCE_DEPENDENCY_CHANGED"):
    path=Path(item["path"]).resolve()
    if digest(path)!=item["sha256"]:raise ValueError(error)
    return path


def r3_source_revision(task):
    """A hash-bound replacement, never an unconstrained directory scan."""
    revision_path=task.out("XP_SOURCE_REVISION.json")
    revision=task.read("XP_SOURCE_REVISION.json")
    reuse_root=(task.base_root/"cash_r2").resolve()
    if (revision.get("schema_version")!=1 or revision.get("reuse_stage")!="continuation/cash_r2"
            or Path(revision["reuse_root"]).resolve()!=reuse_root
            or revision.get("reuse_freeze_sha256")!=R2_CASH_FREEZE_SHA):
        raise ValueError("R3_REUSE_IDENTITY_CHANGED")
    prior_freeze=dict(path=str(reuse_root/"CASH_INPUT_FREEZE.json"),sha256=R2_CASH_FREEZE_SHA)
    prior_receipt=dict(path=str(reuse_root/"CASH_INPUT_RECEIPT.json"),sha256=R2_CASH_RECEIPT_SHA)
    _verified_dependency(prior_freeze);_verified_dependency(prior_receipt)
    old=revision["old_source"]
    if (Path(old["path"]).resolve()!=(task.base_root/OLD_XP_SOURCE_REL).resolve()
            or old.get("sha256")!=OLD_XP_SOURCE_SHA):
        raise ValueError("R3_OLD_XP_IDENTITY_CHANGED")
    _verified_dependency(old)
    prior=json.loads(Path(prior_freeze["path"]).read_text(encoding="utf-8"))
    receipt=json.loads(Path(prior_receipt["path"]).read_text(encoding="utf-8"))
    if receipt.get("freeze_sha256")!=R2_CASH_FREEZE_SHA or receipt.get("events_bound")!=38:
        raise ValueError("R3_PARENT_CASH_RECEIPT_CHANGED")
    sources=prior["sources"]
    old_matches=[i for i in sources if Path(i["path"]).resolve()==Path(old["path"]).resolve()
                 and i["sha256"]==OLD_XP_SOURCE_SHA]
    if len(sources)!=39 or len(old_matches)!=1 or len({Path(i["path"]).resolve() for i in sources})!=39:
        raise ValueError("R3_PARENT_SOURCE_SET_CHANGED")
    reused=[dict(i) for i in sources if i is not old_matches[0]]
    for item in reused:_verified_dependency(item)
    replacement=dict(revision["replacement_source"])
    replacement_path=_verified_dependency(replacement)
    if replacement_path in {Path(i["path"]).resolve() for i in sources}:
        raise ValueError("R3_XP_REPLACEMENT_MUST_BE_NEW_SOURCE")
    identity_source=revision["security_identity_source"]
    _verified_dependency(identity_source)
    identity=dict(identity_source["identity"])
    fields=("security_id","identity_kind","issuer","ticker","listing_identity","security_type")
    payload={k:identity[k] for k in fields}
    if payload["ticker"]!="XP" or payload["security_type"]!="COMMON_STOCK" or payload["listing_identity"]!="NASDAQ:XP":
        raise ValueError("R3_XP_SECURITY_CLASS_CHANGED")
    from scripts.v22.corporate_action_transition_r1 import canonical_bytes
    identity["identity_payload_sha256"]=hashlib.sha256(canonical_bytes(payload)).hexdigest()
    identity["source_fingerprint"]=identity_source["sha256"]
    if not identity.get("source_reference"):raise ValueError("R3_IDENTITY_SOURCE_REFERENCE_REQUIRED")
    # available_at is source-declared. Unknown/late remains blocked by the binder.
    identity.setdefault("available_at",None)
    dependencies=dict(reuse_freeze=prior_freeze,reuse_receipt=prior_receipt,
        old_xp_source=dict(old),xp_revision=dict(path=str(revision_path),sha256=digest(revision_path)),
        security_identity_source={k:identity_source[k] for k in ("path","sha256")})
    evidence=revision.get("source_evidence")
    if not isinstance(evidence,list) or not evidence:raise ValueError("R3_EXPLICIT_SOURCE_EVIDENCE_REQUIRED")
    for index,item in enumerate(evidence):
        if not item.get("purpose"):raise ValueError("R3_SOURCE_EVIDENCE_PURPOSE_REQUIRED")
        _verified_dependency(item)
        dependencies["xp_source_evidence_%03d"%index]=dict(item)
    if task.stage==R4_STAGE:
        if identity.get("security_class")!="CLASS_A_COMMON_SHARES":
            raise ValueError("R4_XP_CLASS_A_IDENTITY_REQUIRED")
        item=dict(revision["source_precedence_policy"])
        if Path(item["path"]).resolve()!=task.out("XP_SOURCE_PRECEDENCE.json"):
            raise ValueError("R4_SOURCE_PRECEDENCE_POLICY_PATH_CHANGED")
        _load_source_precedence_policy(item)
        dependencies["xp_source_precedence_policy"]=item
    return reused+[replacement],identity,dependencies,receipt["source_binding"]["event_fingerprints"]



def _load_source_precedence_policy(item):
    """Read the exact policy bytes and validate both physical and canonical hashes."""
    path=_verified_dependency(item,"R4_SOURCE_PRECEDENCE_POLICY_CHANGED")
    document=json.loads(path.read_text(encoding="utf-8"))
    if set(document)!={"payload","payload_sha256"}:
        raise ValueError("R4_SOURCE_PRECEDENCE_DOCUMENT_CHANGED")
    from scripts.v22.corporate_action_transition_r1 import canonical_bytes
    from scripts.research.a2.data import joint_cash_bindings as binder
    payload_sha=hashlib.sha256(canonical_bytes(document["payload"])).hexdigest()
    if document["payload_sha256"]!=payload_sha:
        raise ValueError("SOURCE_PRECEDENCE_CANONICAL_PAYLOAD_CHANGED")
    envelope=dict(path=str(path),sha256=item["sha256"],payload=document["payload"],
        payload_sha256=payload_sha,guard=dict(status="HASH_VERIFIED_PAYLOAD",
            path=str(path),sha256=item["sha256"],payload_sha256=payload_sha))
    binder.validate_source_precedence_policy(envelope)
    return envelope


def _precedence_metadata(envelope):
    return dict(qualification_basis="SOURCE_DECLARED_GROSS",
        vendor_numeric_conflict_reconciled=False,final_paid_rate_verified=False,
        source_precedence_policy=dict(path=envelope["path"],sha256=envelope["sha256"],
                                     payload_sha256=envelope["payload_sha256"]))



def _precedence_metadata_matches(value,expected):
    return all(value.get(k)==v and (not isinstance(v,bool) or value.get(k) is v)
               for k,v in expected.items())


def _verify_precedence_fact(envelope,source,normalized,physical,identity):
    from scripts.v22.corporate_action_transition_r1 import canonical_bytes
    scope=envelope["payload"]["scope"]
    actual=dict(original_statement_source_sha256=source["sha256"],
        statement_fact_sha256=physical,
        statement_payload_sha256=hashlib.sha256(canonical_bytes(normalized)).hexdigest(),
        ticker=normalized["ticker"],effective_date=normalized["ex_date_binding"]["value"],
        fact_key=normalized["event_key"],security_id=identity["security_id"],
        identity_payload_sha256=identity["identity_payload_sha256"],
        security_class=normalized.get("security_class"),security_type=normalized["security_type"],
        listing_identity=identity["listing_identity"],
        issuer_cash_per_raw_old_share=declared_cash_amount(normalized),
        amount_unit=normalized["amount_unit"],quantity_coordinate=normalized["quantity_coordinate"])
    if (identity.get("security_class")!="CLASS_A_COMMON_SHARES"
            or any(scope.get(k)!=v for k,v in actual.items())):
        raise ValueError("R4_SOURCE_PRECEDENCE_FACT_IDENTITY_CHANGED")


def verify_cash_inputs(task):
    receipt=task.read("CASH_INPUT_RECEIPT.json");freeze=task.read("CASH_INPUT_FREEZE.json")
    if receipt["freeze_sha256"]!=digest(task.out("CASH_INPUT_FREEZE.json")):
        raise ValueError("CASH_INPUT_FREEZE_CHANGED")
    item=receipt["artifact"];path=Path(item["path"]).resolve()
    if not path.is_relative_to(task.root) or digest(path)!=item["sha256"]:
        raise ValueError("CASH_INPUT_ARTIFACT_CHANGED")
    if freeze["market_cache_sha256"]!=CACHE_SHA or freeze["input_binding_sha256"]!=INPUT_SHA:
        raise ValueError("CASH_PARENT_IDENTITY_CHANGED")
    dependencies=freeze["sources"]+list(freeze["required"].values())+[freeze["calendar"]]
    dependencies += [dict(path=r["source_reference"],sha256=r["source_fingerprint"]) for r in freeze["rules"].values()]
    for dependency in dependencies:_verified_dependency(dependency)
    if digest(__file__)!=freeze["controller_sha256"]:raise ValueError("CASH_CONTROLLER_IDENTITY_CHANGED")
    from scripts.research.a2.data import joint_cash_bindings as binder
    if digest(binder.__file__)!=freeze["binder_sha256"]:raise ValueError("CASH_BINDER_CHANGED")
    if task.stage in CONTROL_ONLY_STAGES:
        sources,identity,required,prior_events=r3_source_revision(task)
        if sources!=freeze["sources"] or any(freeze["required"].get(k)!=v for k,v in required.items()):
            raise ValueError("R3_SOURCE_REVISION_FREEZE_CHANGED")
        if not set(prior_events).issubset(set(receipt["source_binding"]["event_fingerprints"])):
            raise ValueError("R3_REUSED_CASH_EVENTS_CHANGED")
    if task.stage==R4_STAGE:
        policy=_load_source_precedence_policy(freeze["required"]["xp_source_precedence_policy"])
        expected=_precedence_metadata(policy)
        if not _precedence_metadata_matches(freeze,expected) or not _precedence_metadata_matches(receipt,expected):
            raise ValueError("R4_SOURCE_PRECEDENCE_QUALIFICATION_BASIS_CHANGED")
        saved=receipt["source_binding"]["manifest"].get("source_precedence",{})
        if saved.get("payload")!=policy["payload"] or saved.get("guard",{}).get("sha256")!=policy["sha256"]:
            raise ValueError("R4_SOURCE_PRECEDENCE_MANIFEST_CHANGED")
    return receipt,freeze,path


def combined_account_attempts(current,other):
    if any(isinstance(v,bool) or not isinstance(v,int) or v<0 for v in (current,other)):raise ValueError("INVALID_ACCOUNT_ATTEMPT_COUNT")
    return current+other

def friction(bps):
    if bps not in (0, *SCENARIOS):
        raise ValueError("UNREGISTERED_FRICTION_SCENARIO")
    return dict(kind="FIXED_ADVERSE_OPEN_SLIPPAGE", scenario_id=f"V24_FIXED_{bps}BPS",
                one_way_bps=bps, fee_bps=0, benchmark="NEXT_RAW_OPEN",
                authority="HYPOTHETICAL_RESEARCH_SCENARIO")

class Continuation:
    def __init__(self, parent, stage="continuation"):
        self.parent = JointMethodCoverage(parent)
        if stage not in STAGES:raise ValueError("UNREGISTERED_CONTINUATION_STAGE")
        self.base_root = self.parent.out("continuation").resolve()
        self.root = self.parent.out(stage).resolve()
        self.stage = stage
        paths = resolve(Path(__file__).resolve().parents[4])
        assert_safe_output_path(self.root, kind="results", paths=paths)
        self.root.mkdir(parents=True,exist_ok=True)
    def out(self, rel):
        path = (self.root/rel).resolve()
        if not path.is_relative_to(self.root): raise ValueError("CONTINUATION_PATH_ESCAPE")
        return path
    def read(self, rel):
        return json.loads(self.out(rel).read_text(encoding="utf-8"))
    def write(self, rel, value, immutable=False):
        path=self.out(rel);path.parent.mkdir(parents=True,exist_ok=True)
        safe=methods.json_safe(value)
        if immutable and path.exists():
            if self.read(rel)!=safe: raise ValueError("CONTINUATION_FREEZE_CHANGED")
            return
        tmp=path.with_name(path.name+".tmp")
        tmp.write_text(json.dumps(safe,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
        tmp.replace(path)

def raw_extension_into_inputs(task, inputs):
    raw_receipt=task.base_root/"RAW_HELD_INPUT_VALIDATION.json"
    report=json.loads(raw_receipt.read_text(encoding="utf-8"))
    if report["status"]!="PASS_FROZEN_RAW_MISSING_HELD_KEY_INFERENCE":
        raise ValueError("UNQUALIFIED_RAW_HELD_INFERENCE")
    before=inputs["mu"]["RAW_CONTROL"].copy()
    di=pd.Index(inputs["market"].dates);ti=pd.Index(inputs["market"].tickers)
    added=0;deps={}
    for year in methods.YEARS:
        item=report["annual_outputs"][str(year)]
        file,metadata=guard_parquet(item["path"],item["sha256"],["signal_date","source_fit_cutoff"])
        block=file.read(columns=["signal_date","ticker","source_fit_cutoff","a2_prediction"]).to_pandas()
        if block.duplicated(["signal_date","ticker"]).any():raise ValueError("DUPLICATE_RAW_EXTENSION")
        if not pd.to_datetime(block.signal_date).dt.year.eq(year).all():raise ValueError("WRONG_RAW_EXTENSION_YEAR")
        if not pd.to_datetime(block.source_fit_cutoff).eq(pd.Timestamp(year,1,1)).all():
            raise ValueError("WRONG_RAW_EXTENSION_FIT_CUTOFF")
        ri=di.get_indexer(block.signal_date);ci=ti.get_indexer(block.ticker);ok=(ri>=0)&(ci>=0)
        if np.isfinite(before[ri[ok],ci[ok]]).any():raise ValueError("RAW_EXTENSION_OVERWRITES_EXISTING_VALUE")
        values=block.a2_prediction.to_numpy(float)
        if not np.isfinite(values).all():raise ValueError("NONFINITE_RAW_EXTENSION")
        inputs["mu"]["RAW_CONTROL"][ri[ok],ci[ok]]=values[ok]
        added+=int(ok.sum());deps[str(year)]=metadata
    inputs["sigma"]["RAW_CONTROL"]=np.where(np.isfinite(inputs["mu"]["RAW_CONTROL"]),0.,np.nan)
    return dict(raw_extension_receipt_sha256=digest(raw_receipt),
                in_market_missing_keys_added=added,annual=deps)

def prepared(task,*,phase=None,bps=None):
    if task.stage in CONTROL_ONLY_STAGES:validate_stage_operation(task.stage,phase,bps)
    if digest(common.__file__)!=WRAPPER_SHA or digest(allocation.__file__)!=ALLOCATION_SHA:
        raise ValueError("CONTINUATION_BUSINESS_SOURCE_IDENTITY_CHANGED")
    if task.parent.input_sha!=INPUT_SHA:raise ValueError("PARENT_INPUT_IDENTITY_CHANGED")
    cached=task.parent.out("cache/market_and_inputs.joblib")
    if digest(cached)!=CACHE_SHA:raise ValueError("PARENT_MARKET_CACHE_CHANGED")
    inputs=joblib.load(cached)
    dates=pd.DatetimeIndex(inputs["market"].dates)
    if dates.isna().any() or dates.max()>=pd.Timestamp("2026-01-01"):
        raise ValueError("TEST_INPUT_IN_CONTINUATION")
    raw=raw_extension_into_inputs(task,inputs)
    market,start=methods.evaluation_market(inputs["market"])
    # Cash revision preserves the original quote-quality policy domain.
    market=methods.with_effective_event_quality(market,inputs["replay_kwargs"])
    if task.stage!="continuation":
        receipt,freeze,path=verify_cash_inputs(task)
        inputs["replay_kwargs"]=joblib.load(path)

    if task.stage in CONTROL_ONLY_STAGES:
        covariance={};riskdeps=dict(status="NOT_REQUIRED_FOR_CONTROL_ONLY",new_fit_units=0)
    else:
        covariance,reports,riskdeps=methods.risk_inputs(task.parent,market.tickers)
    return inputs,market,start,covariance,raw,riskdeps

def policy_for(pid,spec,mu,sigma,covariance,scenarios,known,reference,callback,bps):
    if spec.get("kind"):
        return JointResearchPolicy([pid],mu[:,None,:],sigma[:,None,:],covariance,
            roles={pid:{"kind":spec["kind"]}},parameters=methods.PARAMETERS,on_diagnostics=callback)
    base=allocation.JointAllocationPolicy([pid],mu[:,None,:],sigma[:,None,:],covariance,
        roles={pid:{"risk":spec["risk"],"rho":spec["rho"]}},parameters=methods.PARAMETERS,
        method=spec["allocation"],gross_method=spec["gross"],
        scenarios_by_year=scenarios,reference_by_day=reference,on_diagnostics=callback,
        execution_friction_bps=bps if spec["allocation"]=="cost_aware" else 0.)
    if spec.get("control")=="buy_hold_hysteresis":
        base=RuleStatefulPolicy(base,mu[:,None,:],sigma[:,None,:],no_trade_band=0,minimum_trade_usd=0,hysteresis=.5)
    elif spec.get("control"):base=allocation.TradingControlPolicy(base,spec["control"])
    if spec["allocation"] in SCENARIO_ALLOCATION:base=methods.ScenarioCoverageGate(base,known)
    return base

def save_tables(task,path_id,replay,diagnostics,coverage):
    artifacts={}
    for name in ("daily","positions","orders","fills","execution_results","contexts",
                 "operational_actions","accounting_exceptions","entitlements"):
        frame=getattr(replay,name,None)
        if frame is None:continue
        target=task.out("ledgers/"+path_id+"/"+name+".parquet");target.parent.mkdir(parents=True,exist_ok=True)
        frame.to_parquet(target,index=False)
        artifacts[name]=dict(path=str(target),sha256=digest(target),rows=len(frame))
    for name,rows in (("policy_diagnostics",diagnostics),("forecast_coverage",coverage)):
        target=task.out("ledgers/"+path_id+"/"+name+".parquet")
        pd.DataFrame(rows).to_parquet(target,index=False)
        artifacts[name]=dict(path=str(target),sha256=digest(target),rows=len(rows))
    target=task.out("ledgers/"+path_id+"/final_state.joblib")
    joblib.dump(replay.final_state,target,compress=3)
    artifacts["final_state"]=dict(path=str(target),sha256=digest(target))
    return artifacts

def run(parent,phase,bps,stage="continuation"):
    validate_stage_operation(stage,phase,bps)
    if stage in CONTROL_ONLY_STAGES and phase!="controls":raise ValueError("R3_RUN_REQUIRES_CONTROLS")
    task=Continuation(parent,stage)
    inputs,market,start,covariance,rawdeps,riskdeps=(prepared(task,phase=phase,bps=bps)
        if stage in CONTROL_ONLY_STAGES else prepared(task))
    roles=stage_roles(stage)
    freeze=dict(status="FROZEN_BEFORE_CONTINUATION_ECONOMIC_REPLAY",role="B_NON_ML_INCREMENT",
      years=list(methods.YEARS),frictions=list(SCENARIOS),primary_one_way_bps=PRIMARY_BPS,
      parameters=methods.PARAMETERS,allocation_spec=allocation.SPEC,roles=roles,
      aliases_retained=methods.ALIASES,old_cost_aware_zero_alias_replaced_only_in_nonzero_scenarios=True,
      selection="At10bps require both qualified controls and complete candidate; strictly exceed both final certified continuous NAV; ties path_id; max1 finalist. Sensitivities5/20bps report only, no retuning/selection.",
      research_friction="fixed adverse nextOpen scenario; not empirically estimated broker slippage",
      source_sha256={str(Path(f).resolve()):digest(f) for f in (__file__,common.__file__,allocation.__file__,runtime.__file__,methods.__file__)},
      indexed_runtime=runtime.source_lineage(source_sha256=WRAPPER_SHA),raw_held=rawdeps,
      market_cache_sha256=CACHE_SHA,input_binding_sha256=INPUT_SHA,
      original_freezes_preserved=True,test2026_reads=0,
      CA_qualification="Original full848 share binding preserved; only exact source-backed cash terms added in explicit revision; residual unknown rights unqualified.",
      stage=task.stage,cash_input_revision=dict(path=str(task.out("CASH_INPUT_FREEZE.json")),sha256=digest(task.out("CASH_INPUT_FREEZE.json")),receipt_sha256=digest(task.out("CASH_INPUT_RECEIPT.json"))) if task.stage!="continuation" else None,
      budget=dict(additional_account_cap=154,max_one_path_seconds=900,library_threads=2,new_fit_units=0))
    if stage in CONTROL_ONLY_STAGES:
        freeze.update(role="B_SOURCE_ACCOUNTING_CONTROL_QUALIFICATION",frictions=[PRIMARY_BPS],
            aliases_retained={},old_cost_aware_zero_alias_replaced_only_in_nonzero_scenarios=False,
            selection="Two controls only; strict source/accounting qualification; no candidate ranking or2026unlock",
            controls_only=True,allowed_role_ids=list(methods.CONTROLS),candidate_attempts=0)
        freeze["budget"].update(stage_account_cap=2,new_fit_units=0)
    if stage==R4_STAGE:
        cash_freeze=task.read("CASH_INPUT_FREEZE.json")
        freeze.update(_precedence_metadata(_load_source_precedence_policy(
            cash_freeze["required"]["xp_source_precedence_policy"])))
    task.write("ACCOUNT_FREEZE.json",freeze,immutable=True)
    if bps not in SCENARIOS and not (bps==0 and phase=="controls"):
        raise ValueError("ZERO_FRICTION_ONLY_DIAGNOSTIC_CONTROLS")
    if phase=="primary" and bps!=PRIMARY_BPS:raise ValueError("PRIMARY_SCENARIO_IS_FROZEN_10BPS")
    status=task.read("ACCOUNT_STATUS.json") if task.out("ACCOUNT_STATUS.json").exists() else dict(attempts=0,records=[])
    if phase=="controls":wanted=list(methods.CONTROLS)
    elif phase=="primary":wanted=list(roles)
    else:wanted=list(roles)
    if stage in CONTROL_ONLY_STAGES:
        validate_control_records(status)
        scenarios=known=reference=None
    else:
        frame=load_training_inputs(task.parent.read("INPUT_BINDING.json"))
        mean={y:methods.artifact_from_status(task.parent,"risk_LW",y) for y in methods.YEARS}
        scenarios,known,scenario_receipts=methods.scenario_inputs(frame,market.tickers,mean)
        reference=methods.reference_portfolios(market,inputs["mu"]["RAW_CONTROL"][start:])
        task.write("SCENARIO_INPUTS.json",dict(status="EXACT_PRIOR_RISK_MEAN_REUSE_NO_NEW_FIT",years=scenario_receipts,input_binding_sha256=INPUT_SHA),immutable=True)
    for pid in wanted:
        sid=f"{pid}_S{bps:02d}";spec=roles[pid]
        existing=next((r for r in status["records"] if r["path_id"]==sid),None)
        if existing:
            if existing.get("receipt"):
                saved=task.read(existing["receipt"])
                if digest(task.out(existing["receipt"]))!=existing["receipt_sha256"] or saved["path_id"]!=sid:
                    raise ValueError("CONTINUATION_RECEIPT_CHANGED")
                for item in saved.get("artifacts",{}).values():
                    target=Path(item["path"]).resolve()
                    if not target.is_relative_to(task.root) or digest(target)!=item["sha256"]:
                        raise ValueError("CONTINUATION_ARTIFACT_CHANGED")
            if existing["status"]=="STARTED":
                existing.update(status="INTERRUPTED_FAILURE_RETAINED")
                task.write("ACCOUNT_STATUS.json",status)
            continue
        mu,sigma,complete,forecastdeps=methods.forecast_inputs(task.parent,market,inputs,start,spec["forecast"])
        scenario_role=spec.get("allocation") in SCENARIO_ALLOCATION
        domain=known if scenario_role else None
        if scenario_role:
            for y in methods.YEARS:
                bad=~known[y];days=market.dates.year==y
                mu[np.ix_(days,bad)]=np.nan;sigma[np.ix_(days,bad)]=np.nan
        if not spec.get("kind"):
            complete=complete and all((y,spec["risk"]) in covariance for y in methods.YEARS)
        static=methods.static_forecast_coverage(market,mu,sigma,domain)
        complete=complete and static["complete"]
        record=dict(path_id=sid,policy_path_id=pid,bps=bps,spec=spec,status="BLOCKED_DEPENDENCY",
                    freeze_sha256=digest(task.out("ACCOUNT_FREEZE.json")),forecast=forecastdeps,
                    static_forecast_coverage=static,scope_complete=complete)
        if stage==R4_STAGE:
            record.update({key:freeze[key] for key in ("qualification_basis",
                "vendor_numeric_conflict_reconciled","final_paid_rate_verified","source_precedence_policy")})
        status["records"].append(record)
        if not spec.get("kind") and not all((y,spec["risk"]) in covariance for y in methods.YEARS):
            task.write("ACCOUNT_STATUS.json",status);continue
        total_attempts=status["attempts"]
        for other_stage in STAGES:
            if other_stage==task.stage:continue
            other_path=(task.base_root.parent/other_stage/"ACCOUNT_STATUS.json")
            other_attempts=json.loads(other_path.read_text())["attempts"] if other_path.exists() else 0
            total_attempts=combined_account_attempts(total_attempts,other_attempts)
        if total_attempts>=154:raise RuntimeError("CONTINUATION_ACCOUNT_BUDGET_EXHAUSTED")
        if stage in CONTROL_ONLY_STAGES and status["attempts"]>=2:raise RuntimeError("R3_CONTROL_ACCOUNT_BUDGET_EXHAUSTED")
        diagnostics=[]
        callback=lambda block:diagnostics.extend(block.to_dict("records"))
        policy=policy_for(pid,spec,mu,sigma,covariance,scenarios,known,reference,callback,bps)
        coverage=methods.ScientificCoveragePolicy(policy,mu,sigma,domain)
        begun=time.monotonic()
        def bounded(day,ctx):
            if time.monotonic()-begun>900:raise TimeoutError("FROZEN_PATH_WALL_LIMIT")
            return coverage(day,ctx)
        status["attempts"]+=1;record["status"]="STARTED";task.write("ACCOUNT_STATUS.json",status)
        print(json.dumps(dict(status="STARTED",path_id=sid)),flush=True)
        try:
            with threadpool_limits(limits=2):
                replay=runtime.run_continuous_account_indexed(market,[pid],bounded,inputs["account"],
                    source_sha256=WRAPPER_SHA,execution_friction=friction(bps),**inputs["replay_kwargs"])
            scope=bool(complete and coverage.missing_rows==0)
            metrics=methods.path_metrics(replay,pid,scope,diagnostics)
            # New cash-flow gate supplements retained benchmark identities.
            actual=replay.audit.get("actual_cash_flow_identity_error_max")
            if actual is not None and (not np.isfinite(actual) or actual>1e-5):
                metrics.update(eligible_for_selection=False,final_certified_nav=None)
            record.update(status="COMPLETE",scope_complete=scope,metrics=metrics,
                audit=replay.audit,coverage_missing=coverage.missing_rows,
                coverage_missing_held=coverage.missing_held_rows,
                artifacts=save_tables(task,sid,replay,diagnostics,coverage.records))
            shared={k:replay.metadata[k] for k in ("corporate_action_receipts","corporate_action_exceptions")}
            task.write("receipts/EVENT_SHARED.json",shared,immutable=True)
            record["metadata"]={k:v for k,v in replay.metadata.items() if k not in shared}
            record["metadata"]["shared_event_binding_sha256"]=digest(task.out("receipts/EVENT_SHARED.json"))
            record["prefix_identity"]=replay.prefix_identity
            record["receipt"]="receipts/"+sid+".json"
            task.write(record["receipt"],record,immutable=True)
            record["receipt_sha256"]=digest(task.out(record["receipt"]))
        except Exception as exc:
            record.update(status="FAILED_RETAINED",error=repr(exc))
            task.write("receipts/"+sid+"_FAILED.json",record,immutable=True)
        record["seconds"]=round(time.monotonic()-begun,3);task.write("ACCOUNT_STATUS.json",status)
        print(json.dumps(dict(status=record["status"],path_id=sid,seconds=record["seconds"],
                             qualified=record.get("metrics",{}).get("eligible_for_selection",False))),flush=True)
    return status

def normalized_cash_fact(payload, original):
    """Schema projection only; retains the original source file identity."""
    import copy
    x=copy.deepcopy(payload)
    if "id" in x:
        supported_basis={
            "EXPLICIT_USD":"EXPLICIT_USD","INFERRED_USD_CONTEXT":"INFERRED_USD",
            "Inferred from US issuer, US-listed ordinary common-stock context and dollar-denominated announcement; original text uses dollar sign, not an explicit ISO USD token.":"INFERRED_USD",
            "Inferred from US issuer/listing/common-stock context and dollar-denominated announcement; original uses dollar sign, not explicit ISO USD.":"INFERRED_USD"}
        if x.get("cash_is_gross_announced_amount") is not True:raise ValueError("UNCONFIRMED_GROSS_COMMON_CASH")
        if x.get("currency_basis") not in supported_basis:raise ValueError("UNCONFIRMED_USD_BASIS")
        listing=x["listing_identity"].replace("NYSE American","NYSE_AMERICAN").replace(" ","")
        ticker=listing.split(":")[1]
        x=dict(event_key=x["id"],ticker=ticker,issuer=x["issuer"],
            listed_exchange=listing.split(":")[0],security_type="COMMON_STOCK",
            source_url=x["source_url"],cash_per_raw_ex_pretrade_common_share=x["cash_per_common_share"],
            currency=x["currency"],currency_confidence=supported_basis[x["currency_basis"]],
            amount_unit="USD_PER_RAW_OLD_SHARE",quantity_coordinate="RAW_OLD_SECURITY_SHARES",
            record_date=x["record_date"],scheduled_pay_date=x["pay_date"],publication_date=x["publication_date"],
            available_at_upper_bound=x["availability_bound"]["available_at"],
            ex_date_binding=dict(value=x["candidate_ex_date"],issuer_direct=False),
            raw_bytes_available=x.get("raw_bytes_available",False),raw_sha256=x.get("raw_sha256"))
    if x.get("caller_event_ticker") and x["caller_event_ticker"]!=x["ticker"]:
        proof=x.get("ticker_continuity_proof",{})
        if not (proof.get("same_common_stock") and proof.get("retrospective_identity_crosswalk_only")):
            raise ValueError("UNPROVEN_TICKER_ALIAS")
        if digest(proof["path"])!=proof["sha256"]:raise ValueError("TICKER_ALIAS_PROOF_CHANGED")
        x["historical_declared_ticker"]=x["ticker"]
        x["ticker"]=x["caller_event_ticker"]
        x["identity_crosswalk_use"]="Retrospective class continuity only; not backfilled decision information"
    if x.get("listed_exchange")=="Nasdaq":x["listed_exchange"]="NASDAQ"
    x["original_source_projection"]=original
    return x

def declared_cash_amount(payload):
    if payload.get("security_type") not in ("COMMON_STOCK","AMERICAN_DEPOSITARY_SHARE"):raise ValueError("SOURCE_CASH_AMOUNT_UNKNOWN_OR_WRONG_CLASS")
    field=("cash_per_raw_ex_pretrade_ads" if payload.get("security_type")=="AMERICAN_DEPOSITARY_SHARE" else "cash_per_raw_ex_pretrade_common_share")
    value=payload.get(field)
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not np.isfinite(value) or value<0:
        raise ValueError("SOURCE_CASH_AMOUNT_UNKNOWN_OR_WRONG_CLASS")
    return float(value)

def typed_cash_amount_matches(vendor,declared):
    return bool(not isinstance(vendor,(bool,np.bool_)) and isinstance(vendor,(int,float,np.integer,np.floating))
        and np.isfinite(vendor) and vendor>=0 and abs(vendor-declared)<=1e-10)

def prepare_cash_stage(parent, stage,*,bps=PRIMARY_BPS):
    """Freeze a source-only revision; no relabel, refit or market-cache overwrite."""
    validate_stage_operation(stage,"cash-freeze",bps)
    import copy
    from scripts.research.a2.data import joint_cash_bindings as binder
    from scripts.v22.corporate_action_transition_r1 import canonical_bytes
    task=Continuation(parent,stage)
    if stage=="continuation":raise ValueError("NEW_CASH_REVISION_REQUIRED")
    base=task.base_root
    xp_identity=None;r3_required={};prior_event_fingerprints=[]
    if stage in CONTROL_ONLY_STAGES:
        sources,xp_identity,r3_required,prior_event_fingerprints=r3_source_revision(task)
    else:
        groups=("PFE_LNG","GM_FCNCA","NVDA_HPE","FCX_KEY_VRT","TDS_HBAN_PCG_GAP",
                "BP_TFPM","WING_OLED_MRVL","M_WCC_MMM_TPR_STX","WDC_AVGO_MU_ORCL_TER_SEI","BP_XP_FCNCA_GM_Q3")
        sources=[]
        for group in groups:
            directory=base/"sources"/group
            if not directory.exists():continue
            for p in sorted(directory.glob("*.json")):
                # Source partitions are pure facts/metadata, never account/model results.
                x=json.loads(p.read_text(encoding="utf-8"))
                if ("id" in x and "cash_per_common_share" in x) or ("event_key" in x and "cash_per_raw_ex_pretrade_common_share" in x):
                    sources.append(dict(path=str(p),sha256=digest(p)))
    if not sources:raise ValueError("NO_OFFICIAL_CASH_SOURCE_PROJECTIONS")
    required={"vendor_receipt":base/"CASH_VENDOR_READ_RECEIPT.json",
       "vendor_keys":base/"CASH_VENDOR_EXACT_KEYS_R2.json",
       "typed_vendor":base/"inputs/CASH_VENDOR_EXACT39.parquet",
       "source_closure":base/"ACCOUNT_SOURCE_CLOSURE.json",
       "binder_validation":task.parent.out("receipts/CASH_BINDER_COMPONENT_VALIDATION.json")}
    freeze_required={k:dict(path=str(path),sha256=digest(path)) for k,path in required.items()}
    if set(freeze_required)&set(r3_required):raise ValueError("R3_REQUIRED_DEPENDENCY_COLLISION")
    for item in r3_required.values():_verified_dependency(item)
    freeze_required.update(r3_required)
    if digest(required["typed_vendor"])!="9da9a09ef63b00f3b82f691a682b4a7fb5ed8d4b6cc337ba5665d51de4851f4f":
        raise ValueError("TYPED_VENDOR_INPUT_CHANGED")
    if digest(required["source_closure"])!="5bb84e13cc6e113baa964122e7a85e5d4d9edc3a44c23f7a70bc30f0e2417181":
        raise ValueError("SOURCE_CLOSURE_CHANGED")
    b=task.parent.read("INPUT_BINDING.json")
    cal_source=b["extended_five_day_labels"]["common_calendar"]
    rules={
      "TPLUS2":dict(source_reference=str(base/"sources/BP_TFPM/FINRA_17_19.pdf"),
        source_fingerprint="52a8ee08c6b7766fddaff1bdc587275271434290546712c687b3e31e5522348f",
        effective_from="2017-09-05",effective_until_exclusive="2024-05-28",kind="FINRA_17_19_NORMAL_SMALL_CASH"),
      "TPLUS1":dict(source_reference=str(base/"sources/BP_TFPM/FINRA_24_04.pdf"),
        source_fingerprint="b3b74a8cc5f150839cd5a209026d60c0db449722ab62ce38c310506b74d612e5",
        effective_from="2024-05-28",kind="FINRA_24_04_NORMAL_SMALL_CASH")}
    for r in rules.values():
        if digest(r["source_reference"])!=r["source_fingerprint"]:raise ValueError("RULE_SOURCE_CHANGED")
    freeze=dict(status="FROZEN_BEFORE_NEW_CASH_INPUT_MATERIALIZATION",stage=stage,
        sources=sources,required=freeze_required,
        calendar=dict(path=cal_source["path"],sha256=cal_source["sha256"],columns=["trade_date"]),
        rules=rules,market_cache_sha256=CACHE_SHA,input_binding_sha256=INPUT_SHA,
        binder_sha256=digest(binder.__file__),controller_sha256=digest(__file__),
        scientific_change="Declared gross pre-tax cash entitlement economics revision on unchanged ML bank/training-label population",
        policy_domain="Retain original event-day quote block; no buy-domain expansion or new feature",
        training_labels="Exact parent immutable supported-event labels; no cash-gap target fill or refit",
        payment="Announced scheduled first legal Open; no claim of observed broker payment, ADR fee or tax",
        ADS="Explicit source-declared gross USD per raw ADS opt-in; ordinary-share fallback forbidden; deductions not estimated",
        unknown_events="Preserved, fail certification",test2026_market_dataset_pages_read=0,incidental_test_window_source_snippet_exposure_preserved=True)
    if stage in CONTROL_ONLY_STAGES:
        freeze.update(controls_only=True,allowed_role_ids=list(methods.CONTROLS),bps=PRIMARY_BPS,
            max_new_paths=2,new_fit_units=0,xp_announced_cash_per_raw_old_share=.58)
    precedence_policy=None
    if stage==R4_STAGE:
        precedence_policy=_load_source_precedence_policy(freeze_required["xp_source_precedence_policy"])
        freeze.update(_precedence_metadata(precedence_policy))
    task.write("CASH_INPUT_FREEZE.json",freeze,immutable=True)
    file,_=guard_parquet(cal_source["path"],cal_source["sha256"],["trade_date"])
    calendar=pd.DatetimeIndex(file.read(columns=["trade_date"]).to_pandas().trade_date)
    if calendar.has_duplicates or not calendar.is_monotonic_increasing:raise ValueError("INVALID_CALENDAR")
    cal_binding=dict(status="SOURCE_BOUND_LEGAL_SESSION_CALENDAR",source_reference=cal_source["path"],
        source_fingerprint=cal_source["sha256"],
        session_dates_sha256=hashlib.sha256(canonical_bytes([str(d.date()) for d in calendar])).hexdigest())
    cache=task.parent.out("cache/market_and_inputs.joblib")
    if digest(cache)!=CACHE_SHA:raise ValueError("MARKET_CACHE_CHANGED")
    inputs=joblib.load(cache);market=inputs["market"]
    if market.dates.max()>=pd.Timestamp("2026-01-01"):raise ValueError("TEST_MARKET_FORBIDDEN")
    identities={};envelopes=[];prices={};fact_by_event={};original_by_event={};incomplete_sources=[]
    for original in sources:
        p=Path(original["path"])
        if digest(p)!=original["sha256"]:raise ValueError("FACT_SOURCE_CHANGED")
        try:
            x=normalized_cash_fact(json.loads(p.read_text()),original)
            declared_cash_amount(x)
            if stage in CONTROL_ONLY_STAGES and original==sources[-1]:
                if x.get("ticker")!="XP" or x.get("ex_date_binding",{}).get("value")!="2023-09-11" or declared_cash_amount(x)!=.58:
                    raise ValueError("R3_XP_FACT_SCOPE_OR_ANNOUNCED_AMOUNT_CHANGED")
            sid=binder.source_derived_security_id(x["issuer"],x["ticker"],x["listed_exchange"]+":"+x["ticker"],security_type=x["security_type"])
        except (ValueError,KeyError,TypeError) as exc:
            incomplete_sources.append(dict(source=original,reason=str(exc),vendor_events_retained=True));continue
        path=task.out("inputs/normalized/"+x["event_key"]+".json")
        task.write("inputs/normalized/"+x["event_key"]+".json",x,immutable=True)
        physical=digest(path);payload_sha=hashlib.sha256(canonical_bytes(x)).hexdigest()
        envelope=dict(path=str(path),sha256=physical,payload=x,
          guard=dict(status="HASH_VERIFIED_PAYLOAD",path=str(path),sha256=physical,payload_sha256=payload_sha))
        if stage==R4_STAGE and x["ticker"]=="XP":
            _verify_precedence_fact(precedence_policy,original,x,physical,xp_identity)
            envelope["original_statement_source_sha256"]=original["sha256"]
        envelopes.append(envelope)
        ticker=x["ticker"];security_type=x["security_type"]
        identity=dict(security_id=sid,identity_kind="SOURCE_DERIVED_ISSUER_COMMON_CLASS",issuer=x["issuer"],
          ticker=ticker,listing_identity=x["listed_exchange"]+":"+ticker,security_type=security_type)
        identity["identity_payload_sha256"]=hashlib.sha256(canonical_bytes(identity)).hexdigest()
        identity.update(source_reference=x["source_url"],source_fingerprint=physical,available_at=x["available_at_upper_bound"])
        if stage in CONTROL_ONLY_STAGES and ticker=="XP":
            identity=dict(xp_identity);sid=identity["security_id"]
        old=identities.get(ticker)
        if old:
            if old["security_id"]!=sid:raise ValueError("ISSUER_IDENTITY_CONFLICT:"+ticker)
            if pd.Timestamp(identity["available_at"])<pd.Timestamp(old["available_at"]):identities[ticker]=identity
        else:identities[ticker]=identity
        ex=pd.Timestamp(x["ex_date_binding"]["value"]);pos=calendar.get_indexer([ex])[0]
        if pos<=0:continue
        prior=calendar[pos-1];ri=market.dates.get_indexer([prior])[0];ci=pd.Index(market.tickers).get_indexer([ticker])[0]
        if ri<0 or ci<0:continue
        prices[x["event_key"]]=dict(ticker=ticker,security_id=sid,signal_date=str(prior.date()),
          raw_close=float(market.close[ri,ci]),available_at=str(pd.Timestamp(market.signal_asof[ri])),
          source_fingerprint=CACHE_SHA,price_coordinate="RAW_CLOSE",quantity_coordinate="RAW_OLD_SECURITY_SHARES")
        key=(ticker,str(ex.date()))
        if key in fact_by_event:raise ValueError("DUPLICATE_OFFICIAL_EVENT_PROJECTIONS")
        fact_by_event[key]=(x,physical)
        original_by_event[key]=original
    task.write("PRICE_IDENTITY_INPUTS.json",dict(identities=identities,pre_ex_raw_closes=prices,calendar_binding=cal_binding),immutable=True)
    typed=pd.read_parquet(required["typed_vendor"])
    mappings=json.loads(required["vendor_keys"].read_text())["keys"]
    unsupported=inputs["replay_kwargs"]["unsupported_events"];classifications={}
    noncash=[c for c in typed.columns if c not in ("code","ex_div_date","per_cash_div","special_dividend")]
    for item in unsupported:
        key=(item["ticker"],str(pd.Timestamp(item["effective_date"]).date()))
        if key not in fact_by_event:continue
        mapping=next((x for x in mappings if (x["ticker"],x["effective_date"])==key),None)
        if mapping is None:continue
        rows=typed.loc[typed.code.eq(mapping["code"])&typed.ex_div_date.eq(pd.Timestamp(mapping["source_event_date"]))]
        if len(rows)!=1:continue
        row=rows.iloc[0];x,physical=fact_by_event[key];amount=float(row.per_cash_div)
        no_noncash=bool(row[noncash].fillna(0).eq(0).all())
        precedence_candidate=(stage==R4_STAGE and key==("XP","2023-09-11"))
        if not no_noncash or (not typed_cash_amount_matches(amount,declared_cash_amount(x)) and not precedence_candidate):continue
        proof=dict(family="CASH_DIVIDEND",vendor_event_source_fingerprint=item["source_fingerprint"],
          statement_fact_sha256=physical,vendor_cash_per_raw_old_share=amount,
          non_cash_flags_absent=True,amount_unit="USD_PER_RAW_OLD_SHARE",quantity_coordinate="RAW_OLD_SECURITY_SHARES",
          vendor_typed_cash_field_source_sha256=digest(required["typed_vendor"]),
          vendor_row={c:(None if pd.isna(row[c]) else str(row[c])) for c in typed.columns},
          null_noncash_meaning="No typed noncash action recorded in existing vendor schema; no factor inference")
        if precedence_candidate:
            proof.update(vendor_cash_field="per_cash_div",
                original_statement_source_sha256=original_by_event[key]["sha256"])
        proof["classification_source_fingerprint"]=hashlib.sha256(canonical_bytes(proof)).hexdigest()
        classifications[(key[0],key[1],item["source_fingerprint"])]=proof
    result=binder.bind_cash_entitlements(envelopes,calendar=calendar,calendar_binding=cal_binding,
       unsupported_events=unsupported,security_bindings=identities,pre_ex_raw_closes=prices,
       rule_sources=rules,cash_event_classification=classifications,allow_ads=True,
       source_precedence_policy=precedence_policy)
    if stage in CONTROL_ONLY_STAGES and not set(prior_event_fingerprints).issubset({e.event_fingerprint for e in result.events}):
        raise ValueError("R3_REUSED_CASH_EVENTS_CHANGED")
    # Preserve old quote-quality/trade domain independently of entitlement removal.
    kwargs=copy.deepcopy(inputs["replay_kwargs"])
    kwargs.update(unsupported_events=result.remaining_unsupported_events,entitlement_enabled=True,
       entitlement_events=result.events,entitlement_security_tickers=result.security_tickers,
       entitlement_source_binding=result.source_binding)
    path=task.out("inputs/cash_replay_kwargs.joblib");path.parent.mkdir(exist_ok=True)
    if path.exists():raise ValueError("CASH_INPUT_ALREADY_BUILT_NO_REPEAT")
    joblib.dump(kwargs,path,compress=3)
    receipt=dict(status="SOURCE_BOUND_CASH_INPUT_REVISION_READY",freeze_sha256=digest(task.out("CASH_INPUT_FREEZE.json")),
      artifact=dict(path=str(path),sha256=digest(path)),source_binding=result.source_binding,
      events_bound=len(result.events),exact_vendor_exceptions_removed=len(result.removal_keys),
      unsupported_before=len(unsupported),unsupported_after=len(result.remaining_unsupported_events),
      blocked=list(result.blocked)+incomplete_sources,original_training_labels_unchanged=True,quote_quality_domain_preserved=True,
      new_fits=0,test2026_market_dataset_pages_read=0,incidental_test_window_source_snippet_exposure_preserved=True)
    if stage==R4_STAGE:
        receipt.update(_precedence_metadata(precedence_policy))
    task.write("CASH_INPUT_RECEIPT.json",receipt,immutable=True)
    return receipt


def qualified_finalist(records):
    """Frozen primary gate only; no uncertified NAV participates."""
    primary={r["policy_path_id"]:r for r in records if r.get("bps")==PRIMARY_BPS}
    controls=[primary.get(p) for p in methods.CONTROLS]
    def qualified(r):
        value=r.get("metrics",{}).get("final_certified_nav") if r else None
        finite_nav=(not isinstance(value,(bool,np.bool_)) and isinstance(value,(int,float,np.integer,np.floating))
                    and np.isfinite(value) and value>0)
        return bool(finite_nav and r and r.get("status")=="COMPLETE" and r.get("scope_complete")
            and r.get("metrics",{}).get("eligible_for_selection")
            and r.get("metrics",{}).get("final_certified_nav") is not None)
    if not all(qualified(r) for r in controls):
        return dict(status="NO_TESTABLE_FINALIST",finalist=None,reason="REQUIRED_CONTROL_ACCOUNT_UNQUALIFIED",
                    test2026_unlocked=False)
    threshold=max(r["metrics"]["final_certified_nav"] for r in controls)
    candidates=[r for p,r in primary.items() if p not in methods.CONTROLS and qualified(r)
                and r["metrics"]["final_certified_nav"]>threshold]
    if not candidates:return dict(status="NO_UPGRADE",finalist=None,test2026_unlocked=False)
    chosen=sorted(candidates,key=lambda r:(-r["metrics"]["final_certified_nav"],r["policy_path_id"]))[0]
    return dict(status="ONE_QUALIFIED_PRE2026_FINALIST",finalist=chosen["policy_path_id"],
                receipt_sha256=chosen["receipt_sha256"],test2026_unlocked=False,
                reason="Requires final model/PIT2026 inference input freeze before any descriptive test")

def finish(parent,stage):
    validate_stage_operation(stage,"finish",PRIMARY_BPS)
    task=Continuation(parent,stage);status=task.read("ACCOUNT_STATUS.json")
    primary={r["policy_path_id"]:r for r in status["records"] if r.get("bps")==PRIMARY_BPS}
    if set(primary)!=set(continuation_roles()) or any(r["status"] not in ("COMPLETE","FAILED_RETAINED","INTERRUPTED_FAILURE_RETAINED","BLOCKED_DEPENDENCY") for r in primary.values()):
        raise ValueError("FINITE_PRIMARY_CATALOGUE_NOT_FINISHED")
    for record in status["records"]:
        if record["status"]=="COMPLETE" and not (record.get("receipt") and record.get("artifacts")):raise ValueError("COMPLETE_ACCOUNT_EVIDENCE_MISSING")
        if record.get("receipt"):
            if digest(task.out(record["receipt"]))!=record["receipt_sha256"]:raise ValueError("RECEIPT_CHANGED")
            for item in record.get("artifacts",{}).values():
                path=Path(item["path"]).resolve()
                if not path.is_relative_to(task.root) or digest(path)!=item["sha256"]:raise ValueError("ACCOUNT_ARTIFACT_CHANGED")
    result=qualified_finalist(status["records"])
    result.update(primary_roles=len(primary),completed=sum(r["status"]=="COMPLETE" for r in primary.values()),
       failed=sum(r["status"]=="FAILED_RETAINED" for r in primary.values()),
       dependency_blocked=sum(r["status"]=="BLOCKED_DEPENDENCY" for r in primary.values()),
       qualified=sum(bool(r.get("metrics",{}).get("eligible_for_selection")) for r in primary.values()),
       freeze_sha256=digest(task.out("ACCOUNT_FREEZE.json")),status_sha256=digest(task.out("ACCOUNT_STATUS.json")),
       no_uncertified_economic_ranking=True,all_failures_retained=True,artifact_integrity="PASS",
       parent_fit_bank_reused=True,new_fit_states_in_nonML_comparison=0)
    task.write("FINALIST_GATE.json",result,immutable=True)
    print(json.dumps({k:result[k] for k in ("status","finalist","primary_roles","completed","failed","qualified")}),flush=True)
    return result


def control_gate(parent,stage=R3_STAGE):
    """Metadata qualification only. No NAV comparison and no candidate execution."""
    validate_stage_operation(stage,"control-gate",PRIMARY_BPS)
    if stage not in CONTROL_ONLY_STAGES:raise ValueError("CONTROL_GATE_REQUIRES_R3_OR_R4")
    task=Continuation(parent,stage)
    cash,_,_=verify_cash_inputs(task)
    freeze=task.read("ACCOUNT_FREEZE.json");freeze_sha=digest(task.out("ACCOUNT_FREEZE.json"))
    if (freeze.get("stage")!=stage or freeze.get("controls_only") is not True
            or freeze.get("roles")!=stage_roles(stage) or freeze.get("frictions")!=[PRIMARY_BPS]
            or freeze.get("allowed_role_ids")!=list(methods.CONTROLS)
            or freeze.get("budget",{}).get("stage_account_cap")!=2
            or freeze.get("budget",{}).get("new_fit_units")!=0):
        raise ValueError("R3_CONTROL_ACCOUNT_FREEZE_CHANGED")
    if stage==R4_STAGE:
        policy=_load_source_precedence_policy(task.read("CASH_INPUT_FREEZE.json")["required"]["xp_source_precedence_policy"])
        if not _precedence_metadata_matches(freeze,_precedence_metadata(policy)):
            raise ValueError("R4_CONTROL_QUALIFICATION_BASIS_CHANGED")
    cash_revision=freeze["cash_input_revision"]
    if (cash_revision["sha256"]!=digest(task.out("CASH_INPUT_FREEZE.json"))
            or cash_revision["receipt_sha256"]!=digest(task.out("CASH_INPUT_RECEIPT.json"))):
        raise ValueError("R3_CONTROL_CASH_BINDING_CHANGED")
    for source,sha in freeze["source_sha256"].items():
        _verified_dependency(dict(path=source,sha256=sha),"R3_CONTROL_EXECUTION_SOURCE_CHANGED")
    runtime.source_lineage(source_sha256=WRAPPER_SHA)
    if digest(task.parent.out("cache/market_and_inputs.joblib"))!=CACHE_SHA:
        raise ValueError("PARENT_MARKET_CACHE_CHANGED")
    if task.parent.input_sha!=INPUT_SHA:raise ValueError("PARENT_INPUT_IDENTITY_CHANGED")
    raw_receipt=task.base_root/"RAW_HELD_INPUT_VALIDATION.json"
    if digest(raw_receipt)!=freeze["raw_held"]["raw_extension_receipt_sha256"]:
        raise ValueError("R3_RAW_HELD_INPUT_CHANGED")
    raw=json.loads(raw_receipt.read_text(encoding="utf-8"))
    for item in raw["annual_outputs"].values():_verified_dependency(item,"R3_RAW_HELD_INPUT_CHANGED")
    status=task.read("ACCOUNT_STATUS.json");records=validate_control_records(status)
    flags={};evidence={}
    for record in records:
        if stage==R4_STAGE and not _precedence_metadata_matches(record,_precedence_metadata(policy)):
            raise ValueError("R4_CONTROL_RECORD_QUALIFICATION_BASIS_CHANGED")
        pid=record["policy_path_id"]
        if record.get("freeze_sha256")!=freeze_sha:raise ValueError("R3_CONTROL_RECORD_FREEZE_CHANGED")
        complete=record["status"]=="COMPLETE"
        if complete:
            if not record.get("receipt") or not record.get("artifacts"):
                raise ValueError("COMPLETE_ACCOUNT_EVIDENCE_MISSING")
            path=task.out(record["receipt"])
            if digest(path)!=record["receipt_sha256"]:raise ValueError("RECEIPT_CHANGED")
            saved=task.read(record["receipt"])
            if stage==R4_STAGE and not _precedence_metadata_matches(saved,_precedence_metadata(policy)):
                raise ValueError("R4_CONTROL_SAVED_QUALIFICATION_BASIS_CHANGED")
            fields=("path_id","policy_path_id","bps","status","freeze_sha256","scope_complete","metrics","artifacts")
            if stage==R4_STAGE:
                fields+=("qualification_basis","vendor_numeric_conflict_reconciled","final_paid_rate_verified","source_precedence_policy")
            for field in fields:
                if saved.get(field)!=record.get(field):raise ValueError("R3_CONTROL_RECEIPT_RECORD_CHANGED")
            for item in record["artifacts"].values():
                path=Path(item["path"]).resolve()
                if not path.is_relative_to(task.root) or digest(path)!=item["sha256"]:
                    raise ValueError("ACCOUNT_ARTIFACT_CHANGED")
            evidence[pid]=dict(receipt=record["receipt"],sha256=record["receipt_sha256"])
        metrics=record.get("metrics",{})
        flags[pid]=dict(status=record["status"],scope_complete=record.get("scope_complete") is True,
            accounting_qualified=metrics.get("accounting_qualified") is True,
            required_audits_passed=metrics.get("required_audits_passed") is True,
            eligible_for_selection=metrics.get("eligible_for_selection") is True)
    passed=set(flags)==set(methods.CONTROLS) and all(
        f["status"]=="COMPLETE" and all(f[k] for k in ("scope_complete","accounting_qualified","required_audits_passed","eligible_for_selection"))
        for f in flags.values())
    result=dict(status="CONTROLS_QUALIFIED" if passed else "STOP_CONTROL_UNQUALIFIED",
        controls=flags,evidence=evidence,controls_only=True,bps=PRIMARY_BPS,
        candidate_attempts=0,finalist=None,test2026_unlocked=False,new_fit_units=0,
        account_attempts=status["attempts"],account_freeze_sha256=freeze_sha,
        account_status_sha256=digest(task.out("ACCOUNT_STATUS.json")),
        cash_receipt_sha256=digest(task.out("CASH_INPUT_RECEIPT.json")))
    if stage==R4_STAGE:
        result.update(_precedence_metadata(policy))
    task.write("CONTROL_QUALIFICATION_GATE.json",result,immutable=True)
    print(json.dumps(result),flush=True)
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument("--task-root",required=True)
    p.add_argument("phase",choices=["cash-freeze","controls","primary","sensitivity","finish","control-gate"])
    p.add_argument("--stage",choices=list(STAGES),default="continuation")
    p.add_argument("--bps",type=int,default=PRIMARY_BPS,choices=[0,*SCENARIOS])
    args=p.parse_args()
    validate_stage_operation(args.stage,args.phase,args.bps)
    with task_writer(args.task_root):
        if args.phase=="cash-freeze":
            receipt=prepare_cash_stage(args.task_root,args.stage,bps=args.bps)
            print(json.dumps({k:receipt[k] for k in ("status","events_bound","exact_vendor_exceptions_removed","unsupported_after")}),flush=True)
        elif args.phase=="control-gate":control_gate(args.task_root,args.stage)
        elif args.phase=="finish":finish(args.task_root,args.stage)
        else:run(args.task_root,args.phase,args.bps,args.stage)
if __name__=="__main__":main()

