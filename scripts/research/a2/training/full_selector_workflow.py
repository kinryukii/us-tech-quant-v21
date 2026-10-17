"""Finite full-selector task wiring over the existing learner/risk/account owners.

All policy choices are frozen before outcome evaluation. This module dispatches
one real task ledger and persists exact owner outputs, without a second engine.
"""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import contextmanager
import json
from pathlib import Path
import traceback
import joblib
import numpy as np
import pandas as pd
from scripts.research.a2.training import selector_full_fixed_policy as c
from scripts.research.a2.data.full_selector_inputs import ID,KEYS,REPO,FullSelectorReader,require
from scripts.research.a2.training.selector_challenge import putj,sha,now
from scripts.research.a2.risk import mechanism_risk_adapter as risk
from scripts.common.storage_paths import resolve,assert_safe_output_path

SCOPE_FIELDS=('kind','research_id','status','reviewer','independent_from_root_writer','review_method','human_authority','proposal','preflight','terminal_A','factual_scope_findings','conclusion','execution_authority_basis','freeze_conditions','source_review_refs','mutations','real_data_body_reads','real_fit_calls','economic_result_reads','post2025_reads','registry_admission_granted','production_qualified')

GATE_OWNER={"LW_VARIANCE":("LW_VARIANCE","LW"),"NATIVE_H5_CVAR":("H5_CVAR","TAIL_CVAR"),
    "FULL_PSD_REPLICA_UNCERTAINTY":("PSD_UNCERTAINTY","UNCERTAINTY_JACKKNIFE"),
    "PCA_DIVERSITY":("PCA_DIVERSIFICATION","PCA_FACTOR")}


def load_contexts(run):
    design=json.loads((Path(run)/"DESIGN_FREEZE.json").read_text(encoding="utf-8"))
    ref=design["risk_contexts"]
    require(sha(ref["path"])==ref["sha256"],"FROZEN_RISK_CONTEXTS_CHANGED")
    from scripts.research.a2.data.full_selector_inputs import load_metadata_contexts
    value=load_metadata_contexts(ref)
    require(value["research_id"]==ID and value["numeric_reads"]==0 and value["risk_fits"]==0,
        "METADATA_CONTEXT_AUTHORITY_REQUIRED")
    return value


def task_dag(contexts):
    """Exact future namespace, with per-union risk learned bounds separated."""
    base=c.learners.single_training_dag();nodes=list(base["nodes"])
    for original in c.hybrid_training_dag()["nodes"]:
        nodes.append({**original,"kind":"HYBRID_"+original["kind"]})
    dates=sorted({n["decision_at"][:10] for n in contexts["plan"]["nodes"]})
    for day in dates:
        group="RISK_REFRESH|"+day
        nodes.append(dict(node_id=group,kind="RISK_REFRESH_DISPATCH",day=day))
        nodes += [dict(node_id=group+"|UNIT|"+str(i).zfill(2),kind="RISK_LEARNED_UNIT",day=day)
                  for i in range(71)]
    decisions=[r["decision_at"][:10] for r in contexts["decision_to_context"] if r["decision_at"][:10]>="2024-01-01"]
    require(len(decisions)==502 and len(set(decisions))==502,"FULL_502_RISK_POLICY_DECISIONS")
    for day in decisions:
        for family in c.FAMILIES:nodes.append(dict(node_id="MEMBERS|RISK_"+family+"|"+day,kind="MEMBER_SOLVE",policy_id="RISK_"+family,day=day))
        for gate in c.GATES:nodes.append(dict(node_id="GATE|"+gate+"|"+day,kind="WHOLE_SET_GATE",policy_id="GATE_"+gate,day=day))
    roles,_=c.catalog()
    nodes += [dict(node_id="ACCOUNT|"+r["policy_id"],kind="CONTINUOUS_ACCOUNT",policy_id=r["policy_id"]) for r in roles]
    nodes += [dict(node_id="STATISTICS|SHARED_321",kind="SHARED_BOOTSTRAP")]
    require(len({n["node_id"] for n in nodes})==len(nodes),"WHOLE_TASK_DAG_DUPLICATE")
    counts=dict(Counter(n["kind"] for n in nodes))
    require(counts["HYBRID_ESTIMATOR"]==120 and counts["HYBRID_SCALER"]==24,"EXACT_144_HYBRID_UPPER")
    return dict(nodes=nodes,counts=counts,risk_union_contexts=len(dates),risk_weighted_learned_ceiling=71*len(dates),
        scientific_retries=0,failed_budget_refund=False,conditional_exact_aliases=12,
        unused_learned_slots="NOT_REQUIRED_NOT_SUCCEEDED",member_solves=len(decisions)*18,
        gate_decisions=len(decisions)*4,max_accounts=66,shared_bootstrap=1,exposure_endpoints=321)


def _ref(path):return dict(path=str(path),sha256=sha(path))


def progress(run,stage):
    run=Path(run);plan=json.loads((run/"EXEC_PLAN.json").read_text(encoding="utf-8-sig"))
    journal=c._TaskLedger(run)
    bykind={}
    for kind,status,entered,count in journal.db.execute("SELECT kind,status,entered,count(*) FROM nodes GROUP BY kind,status,entered"):
        bykind.setdefault(kind,{})[status+"|entered="+str(entered)]=count
    plan.update(stage=stage,status="ACTIVE",last_observation_utc=now(),actual_ledger_counts=bykind)
    plan["progress"]["new_prediction_fits"]=journal.db.execute("SELECT count(*) FROM nodes WHERE kind IN ('ESTIMATOR','HYBRID_ESTIMATOR') AND entered=1").fetchone()[0]
    plan["progress"]["new_risk_estimates"]=_risk_environment_paid_attempts(journal)
    plan["progress"]["new_member_solves"]=journal.db.execute("SELECT count(*) FROM nodes WHERE kind='MEMBER_SOLVE' AND entered=1").fetchone()[0]
    plan["progress"]["new_account_replays"]=journal.db.execute("SELECT count(*) FROM nodes WHERE kind='CONTINUOUS_ACCOUNT' AND entered=1").fetchone()[0]
    plan["progress"]["new_bootstrap"]=journal.db.execute("SELECT count(*) FROM nodes WHERE kind='SHARED_BOOTSTRAP' AND entered=1").fetchone()[0]
    putj(run/"EXEC_PLAN.json",plan)
    print(json.dumps(dict(stage=stage,utc=now(),counts=bykind),ensure_ascii=False),flush=True)


def _risk_environment_replay_metadata(run,journal,node,token,recovery):
    """Explicit human-authorized environment recovery; scientific failures denied."""
    if recovery is None:return None
    require(set(recovery)=={"manifest_ref","independent_admission_ref"},"CLOSED_ENVIRONMENT_RECOVERY_REFERENCES_REQUIRED")
    for item in recovery.values():
        require(set(item)=={"path","sha256"} and Path(item["path"]).is_absolute() and sha(item["path"])==item["sha256"],"EXACT_ENVIRONMENT_RECOVERY_PIN_REQUIRED")
    manifest=json.loads(Path(recovery["manifest_ref"]["path"]).read_text(encoding="utf-8-sig"))
    review=json.loads(Path(recovery["independent_admission_ref"]["path"]).read_text(encoding="utf-8-sig"))
    require(review.get("schema")=="FULL_SELECTOR_ENVIRONMENT_RISK_REPLAY_INDEPENDENT_ADMISSION_R1" and review.get("status")=="PASS"
        and review.get("independent_from_entry_writer") is True and review.get("independent_from_dispatch_writer") is True
        and review.get("manifest_ref")==recovery["manifest_ref"] and review.get("workflow_candidate_sha256")==sha(__file__)
        and review.get("scientific_failed_trial_retries")==0 and review.get("new_scientific_nodes_authorized") is False,
        "ACTUAL_INDEPENDENT_ENVIRONMENT_RECOVERY_ADMISSION_REQUIRED")
    require(manifest.get("schema")=="FULL_SELECTOR_FIXED214_ENVIRONMENT_REPLAY_MANIFEST_R1" and manifest.get("research_id")==ID
        and manifest.get("risk_total_entry_cap")==15194 and manifest.get("scientific_failed_trial_retries")==0
        and manifest.get("new_scientific_nodes_authorized") is False and len(manifest.get("groups",{}))==4,
        "EXACT_FOUR_ENVIRONMENT_GROUP_MANIFEST_REQUIRED")
    human=manifest["human_authorization_ref"]
    require(set(human)=={"path","sha256"} and human["sha256"]=="c06815fccd5b8e6a9294f24cd7a629df745363243a300b85ad524bb6682863c5" and sha(human["path"])==human["sha256"],"CURRENT_DIRECT_HUMAN_ENVIRONMENT_REDO_REQUIRED")
    auth=json.loads(Path(human["path"]).read_text(encoding="utf-8-sig"))
    require(auth.get("user_quote")=="中断的你就继续重做" and auth.get("scientific_failed_trial_retries")==0
        and auth.get("new_scientific_nodes_authorized") is False and auth.get("real2026plus_body_reads_authorized")==0,
        "BOUNDED_HUMAN_AUTHORIZATION_REQUIRED")
    if node not in manifest["groups"]:return None
    group=manifest["groups"][node]
    rows=journal.db.execute("SELECT node_id,kind,status,entered,identity,artifact,error FROM nodes WHERE node_id=? OR node_id LIKE ? ORDER BY node_id",(node,node+"|UNIT|%")).fetchall()
    require([list(r) for r in rows]==group["original_rows"] and len(rows)==72,"EXACT_ENVIRONMENT_GROUP_PRESTATE_REQUIRED")
    parent=next(r for r in rows if r[0]==node);units=[r for r in rows if r[0]!=node]
    require(parent[2] in ("STARTED","FAILED") and parent[3]==0 and parent[4]==token and parent[5] is None,
        "EXACT_INTERRUPTED_PARENT_IDENTITY_REQUIRED")
    reason="ENVIRONMENT_OS_REBOOT_INTERRUPTION_NO_COMMITTED_OUTPUT_NOT_SCIENTIFIC_NEGATIVE"
    if parent[2]=="FAILED":require(parent[6]==reason,"SCIENTIFIC_FAILED_PARENT_CANNOT_REPLAY")
    require(all(r[5] is None and ((r[3]==1 and r[2] in ("STARTED","FAILED") and r[4]==token and (r[2]!="FAILED" or r[6]==reason))
        or (r[3]==0 and r[2] in ("NAMED","NOT_REQUIRED") and r[4] is None and (r[2]!="NOT_REQUIRED" or r[6]==reason))) for r in units),
        "SCIENTIFIC_FAILED_OR_COMMITTED_UNIT_CANNOT_REPLAY")
    require(not journal.db.execute("SELECT 1 FROM events WHERE node_id=? AND action='ENVIRONMENT_RISK_REPLAY_BEGIN' LIMIT 1",(node,)).fetchone(),"ENVIRONMENT_REPLAY_ALREADY_USED")
    day=node.split("|")[1]
    require(day<"2026-01-01" and all(not (Path(run)/"risk_states"/(day+s)).exists() for s in (".joblib",".json",".failure.json",".checkpoint")),"ABSENT_ORIGINAL_GROUP_OUTPUT_REQUIRED")
    actual=sum(r[3] for r in units);require(actual==group["original_paid_units"] and group["old_scientific_negative_inferred"] is False,"EXACT_PAID_ENVIRONMENT_INTERRUPTION_REQUIRED")
    return dict(group=group,units={r[0]:r for r in units},manifest_ref=recovery["manifest_ref"],admission_ref=recovery["independent_admission_ref"],additional_entries=0)

def _risk_environment_paid_attempts(journal):
    first=journal.db.execute("SELECT count(*) FROM nodes WHERE kind='RISK_LEARNED_UNIT' AND entered=1").fetchone()[0]
    replay=journal.db.execute("SELECT count(*) FROM events WHERE action='ENVIRONMENT_RISK_REENTER'").fetchone()[0]
    return first+replay

def risk_refresh_once(run,journal,context,loader,recovery=None):
    """One durable 71-unit group; actual owner callback counts each unit.

    Output count is not fit count. Unentered upper-bound slots are NOT_REQUIRED.
    Any partial STARTED group refuses scientific replay; source gaps retain cause.
    """
    day=context["decision_at"][:10];node="RISK_REFRESH|"+day
    identity=dict(context=context,sources=journal.design["risk_inputs"],recipe=risk.content_hash(risk.fixed_policy_risk_specification()))
    token=c.digest(identity);state=journal.status(node)
    if state["status"]=="COMPLETE":
        require(state["identity"]==token,"RISK_COMPLETE_IDENTITY_CHANGED")
        ref=json.loads(state["artifact"]);require(sha(ref["path"])==ref["sha256"],"RISK_COMPLETE_ARTIFACT_CHANGED")
        return joblib.load(ref["path"])
    replay=_risk_environment_replay_metadata(run,journal,node,token,recovery)
    if state["status"]!="NAMED" and replay is None:return None
    with journal.db:
        if replay is None:
            require(journal.db.execute("UPDATE nodes SET status='STARTED',identity=? WHERE node_id=? AND status='NAMED'",(token,node)).rowcount==1,"RISK_REFRESH_ALREADY_STARTED")
            journal.event(node,"BEGIN",identity)
        else:
            require(journal.db.execute("UPDATE nodes SET status='STARTED' WHERE node_id=? AND status=? AND entered=0 AND identity=? AND artifact IS NULL",(node,state["status"],token)).rowcount==1,"RECOVERY_PARENT_CHANGED")
            journal.event(node,"ENVIRONMENT_RISK_REPLAY_BEGIN",dict(manifest_ref=replay["manifest_ref"],independent_admission_ref=replay["admission_ref"],original_group_rows_sha256=c.digest(replay["group"]["original_rows"]),prior_paid_units=replay["group"]["original_paid_units"],paid_entry_refund=False,scientific_failed_trial_retries=0))
    observed=[];slot=0;reserved_payload=None
    def reserve(payload):
        nonlocal reserved_payload
        require(payload["maximum_weighted_units"]==71 and payload["recipe_sha256"]==identity["recipe"],"EXACT_RISK_UPPER_RESERVATION")
        if replay is not None:require(payload==replay["group"]["original_reservation_payload"],"ORIGINAL_RECOVERY_RESERVATION_CHANGED")
        if reserved_payload is None:
            with journal.db:journal.event(node,"RESERVE_WEIGHTED_UPPER_71",payload)
            reserved_payload=payload
        else:require(payload==reserved_payload,"RISK_RESERVATION_EXACT_PAYLOAD_REQUIRED")
        return dict(ack=True,reserved_units=71,reservation_id=node)
    def enter(event):
        nonlocal slot
        units=event["units"]
        require(isinstance(units,int) and units>0 and slot+units<=71,"RISK_FIT_UNIT_CAP")
        local=[]
        with journal.db:
            for i in range(slot,slot+units):
                unit=node+"|UNIT|"+str(i).zfill(2)
                require(_risk_environment_paid_attempts(journal)<15194,"ORIGINAL_TOTAL_RISK_PAID_ENTRY_CAP")
                if replay is None:
                    require(journal.db.execute("UPDATE nodes SET status='STARTED',identity=?,entered=1 WHERE node_id=? AND status='NAMED'",(token,unit)).rowcount==1,"DUPLICATE_RISK_FIT_ENTRY")
                    journal.event(unit,"BACKEND_ENTER",event)
                else:
                    old=replay["units"][unit]
                    require(journal.db.execute("UPDATE nodes SET status='STARTED',identity=?,entered=1 WHERE node_id=? AND status=? AND entered=? AND identity IS ? AND artifact IS NULL AND error IS ?",(token,unit,old[2],old[3],old[4],old[6])).rowcount==1,"EXACT_ENVIRONMENT_UNIT_CHANGED")
                    if old[3]==1:
                        journal.event(unit,"ENVIRONMENT_RISK_REENTER",dict(manifest_ref=replay["manifest_ref"],observation=event,paid_additional_attempt=1,prior_paid_entry_preserved=True));replay["additional_entries"]+=1
                    else:journal.event(unit,"BACKEND_ENTER",event)
                local.append(unit)
        observed.append((local,event));slot+=units
        return dict(ack=True)
    try:
        reservation=reserve(dict(research_id=ID,recipe_sha256=identity["recipe"],as_of=context["decision_at"],requested_families=list(c.FAMILIES),maximum_weighted_units=71))
        packet=loader(Path(run),context,reservation_ack=reservation)
        needed={"inputs","support_metadata","current_identity_proof"}
        require(needed<=set(packet),"ORIGINAL_TYPED_RISK_SOURCE_PACKET_REQUIRED")
        receipt=risk.estimate_fixed_policy_risk_refresh(packet["inputs"],as_of=context["decision_at"],
            support_metadata=packet["support_metadata"],current_identity_proof=packet["current_identity_proof"],
            authorization=dict(research_id=ID,frozen=True,recipe_sha256=identity["recipe"],
                native_scenario_source_projection_sha256=(packet.get("native_scenario_receipt") or {}).get("source_projection_sha256")),
            reserve_callback=reserve,on_component_start=enter,families=c.FAMILIES,
            native_scenario_receipt=packet.get("native_scenario_receipt"))
        require(receipt["weighted_learned_units"]==slot and len(receipt["component_starts"])==len(observed),"ACTUAL_RISK_OBSERVER_COUNT_MISMATCH")
        require(replay is None or slot>=replay["group"]["original_paid_units"],"PARTIAL_ENVIRONMENT_RECOVERY_CANNOT_PUBLISH")
        receipt.update(context=context,source_read_receipt=packet.get("source_read_receipt"),frozen_physical_inputs=identity["sources"])
        path=Path(run)/"risk_states"/(day+".joblib");path.parent.mkdir(parents=True,exist_ok=True)
        require(not path.exists(),"PRESERVE_RISK_REFRESH_OUTPUT");joblib.dump(receipt,path,compress=3);ref=_ref(path)
        with journal.db:
            for (units,_),physical in zip(observed,receipt["component_starts"]):
                outcome="COMPLETE" if physical["status"]=="SUCCEEDED" else "FAILED"
                for unit in units:
                    journal.db.execute("UPDATE nodes SET status=?,artifact=? WHERE node_id=?",(outcome,json.dumps(ref),unit));journal.event(unit,outcome,physical)
            for i in range(slot,71):
                unit=node+"|UNIT|"+str(i).zfill(2)
                journal.db.execute("UPDATE nodes SET status='NOT_REQUIRED',error='UNENTERED_FROZEN_UPPER_SLOT' WHERE node_id=? AND status='NAMED'",(unit,))
            journal.db.execute("UPDATE nodes SET status='COMPLETE',artifact=? WHERE node_id=?",(json.dumps(ref),node));journal.event(node,"COMPLETE",ref)
            if replay is not None:
                for units,_ in observed:
                    for unit in units:journal.db.execute("UPDATE nodes SET error=NULL WHERE node_id=?",(unit,))
                journal.db.execute("UPDATE nodes SET error=NULL WHERE node_id=?",(node,))
        putj(Path(run)/"risk_states"/(day+".json"),dict(ref=ref,actual_weighted_learned_units=slot,
            family_status={f:s["status"] for f,s in receipt["states"].items()},scientific_retry=0))
        return receipt
    except Exception as exc:
        with journal.db:
            status="FAILED" if slot else "SOURCE_NOT_TESTABLE"
            journal.db.execute("UPDATE nodes SET status=?,error=? WHERE node_id=?",(status,traceback.format_exc(),node));journal.event(node,status,dict(reason=str(exc),actual_entered_units=slot))
            for i in range(71):
                unit=node+"|UNIT|"+str(i).zfill(2)
                if replay is not None and replay["units"][unit][3]==1 and i>=slot:
                    journal.db.execute("UPDATE nodes SET status='FAILED',error=? WHERE node_id=? AND entered=1 AND artifact IS NULL",("ENVIRONMENT_OS_REBOOT_INTERRUPTION_NO_COMMITTED_OUTPUT_NOT_SCIENTIFIC_NEGATIVE",unit))
                else:
                    journal.db.execute("UPDATE nodes SET status=?,error=? WHERE node_id=? AND status IN ('STARTED','NAMED')",("FAILED" if i<slot else "NOT_REQUIRED",str(exc),unit))
        putj(Path(run)/"risk_states"/(day+".failure.json"),dict(status=status,error=str(exc),actual_entered_units=slot,traceback=traceback.format_exc()))
        print(json.dumps(dict(phase="RISK_SOURCE_OR_ENGINE_FAILURE",day=day,error=str(exc),entered=slot)),flush=True)
        return None


class RiskProvider:
    def __init__(self,run):
        self.run=Path(run);self.contexts=load_contexts(run)
        self.daymap={r["decision_at"][:10]:r for r in self.contexts["decision_to_context"]}
        self.family_nodes={risk.content_hash(n):n for n in self.contexts["plan"]["nodes"]}
        self.loaded={}
    def state(self,day,family):
        key=pd.Timestamp(day).strftime("%Y-%m-%d");current=self.daymap[key]
        context=self.family_nodes[current["family_context_ids"][family]];refresh=context["decision_at"][:10]
        if refresh not in self.loaded:
            journal=c._TaskLedger(self.run);record=journal.status("RISK_REFRESH|"+refresh)
            require(record["status"]=="COMPLETE","RISK_CONTEXT_SOURCE_OR_TRAINING_NOT_COMPLETE:"+refresh)
            ref=json.loads(record["artifact"]);require(sha(ref["path"])==ref["sha256"],"RISK_CONTEXT_ARTIFACT_CHANGED")
            self.loaded={refresh:joblib.load(ref["path"])}
        state=self.loaded[refresh]["states"][family]
        require(state["status"]=="ESTIMATED","RISK_FAMILY_SOURCE_OR_TRAINING_NOT_TESTABLE:"+family)
        require(tuple(state["assets"])==tuple(current["ordered_assets"]) and state["asset_uids"]==current["asset_uids"]
            and state["asset_epochs"]==current["asset_epochs"],"RISK_FULL_UID_EPOCH_CHANGED")
        proof=dict(assets=current["ordered_assets"],asset_uids=current["asset_uids"],asset_epochs=current["asset_epochs"],
            security_coordinate=current["security_coordinate"],source_support_identity=current["source_support_identity"],
            family_source_support_identity=current["family_source_support_identity"],source_qualified=True,maturity_qualified=True)
        risk.validate_fixed_policy_exact_reuse(state,decision_at=current["decision_at"],current_identity_proof=proof,
            source_cache_identity=state["source_cache_identity"],expected_state_digest=risk.content_hash(state),
            expected_recipe_sha256=self.contexts["plan"]["recipe_sha256"])
        return state
    def __call__(self,*,family,signal_date,full_axis):
        state=self.state(signal_date,family)
        features=risk.fixed_policy_single_stock_risk_features(state)
        require(set(full_axis.ticker)==set(state["assets"]),"HYBRID_FULL_U_DAY_AXIS_REQUIRED")
        local=full_axis[KEYS+["ticker","U_t_fingerprint"]].copy()
        for field in risk.FIXED_POLICY_RISK_COLUMNS:local[field]=local.ticker.map(features[field])
        refresh=pd.Timestamp(state["as_of"]).strftime("%Y-%m-%d")
        source=_ref(self.run/"risk_states"/(refresh+".joblib"))
        qualified=dict(status="PASS",family=family,signal_date=str(signal_date),input_max_date=refresh,
            full_axis_sha256=c.keys_digest(full_axis),native_H5=True,axis_complete=True,source_ref=source,
            state_sha256=risk.content_hash(state),source_completion=state.get("completion"))
        return dict(frame=local,qualified_ref=qualified)


def train_risk(run,loader):
    journal=c._TaskLedger(run);contexts=load_contexts(run)
    union={n["decision_at"][:10]:n for n in contexts["plan"]["nodes"]}
    map_by_date={r["decision_at"][:10]:r for r in contexts["decision_to_context"]}
    for day in sorted(union):
        ctx=map_by_date[day];risk_refresh_once(run,journal,ctx,loader)
        progress(run,"RISK_REFRESH_CONTEXT_"+day)
    return RiskProvider(run)


def _decision_panel(group,members):
    out=group.copy();require(len(members)==min(20,len(group)) and len(set(members))==len(members) and set(members)<=set(group.ticker),"EXACT_FULL_U_MEMBER_SET_REQUIRED")
    out["selected"]=out.ticker.isin(members);out["target_weight"]=np.where(out.selected,.05,0.)
    return out


def risk_policies(run,provider,roles=None):
    journal=c._TaskLedger(run);reader=FullSelectorReader(run)
    hgb,_=c._load_frame(Path(run)/"predictions/policy_HGB.parquet")
    raw,_=c._load_frame(Path(run)/"predictions/policy_RAW.parquet")
    raw_days=dict(tuple(raw.groupby("signal_date",sort=True)))
    namespace=(*('RISK_'+f for f in c.FAMILIES),*('GATE_'+g for g in c.GATES))
    roles=namespace if roles is None else tuple(roles)
    require(len(set(roles))==len(roles) and set(roles)<=set(namespace),'EXACT_FROZEN_RISK_POLICY_NAMESPACE')
    for role in roles:
        parts=[];receipts=[];failed=None
        for day,g in hgb.groupby("signal_date",sort=True):
            if day.year==2023:
                part=raw_days[day].copy();part["source_kind"]="RAW_FALLBACK_2023";parts.append(part);continue
            date=day.strftime("%Y-%m-%d");is_member=role.startswith("RISK_")
            family=role[5:] if is_member else GATE_OWNER[role[5:]][1]
            node="MEMBERS|"+role+"|"+date if is_member else "GATE|"+role[5:]+"|"+date
            try:
                state=provider.state(day,family)
                scores=dict(zip(g.ticker,g.score));uids=dict(zip(g.ticker,g.security_uid))
                identity=dict(policy=role,day=date,state_sha256=risk.content_hash(state),score_ref=c._ref(Path(run)/"predictions/policy_HGB.parquet") if hasattr(c,"_ref") else _ref(Path(run)/"predictions/policy_HGB.parquet"),raw_ref=_ref(Path(run)/"predictions/policy_RAW.parquet"))
                def decision(enter):
                    enter(dict(operation="original_bounded_full_U_swap" if is_member else "original_whole_set_veto"))
                    if is_member:
                        value=risk.fixed_policy_bounded_swap([scores[a] for a in state["assets"]],[uids[a] for a in state["assets"]],state,count=20,max_swaps=20,quality_floor=.975)
                        value['anchor_objective']=risk.fixed_policy_risk_objective(state,value['anchor_members'])
                        return value
                    return risk.fixed_policy_whole_set_gate(GATE_OWNER[role[5:]][0],tuple(g.loc[g.selected,"ticker"]),tuple(raw_days[day].loc[raw_days[day].selected,"ticker"]),state)
                result=journal.once(node,identity,decision)
                require(result is not None,"FROZEN_DECISION_FAILED_NO_SCIENTIFIC_RETRY")
                part=_decision_panel(g,result["members"]);part["source_kind"]="FROZEN_RISK_MEMBER_POLICY";parts.append(part)
                receipts.append(dict(signal_date=date,state_sha256=identity["state_sha256"],**result))
            except Exception as exc:
                journal.block(node,str(exc));failed=failed or (type(exc).__name__+":"+str(exc))
        if failed is None:
            panel=pd.concat(parts,ignore_index=True);panel["policy_id"]=role;c.validate_policy_domain(panel,reader)
            c._store_frame(run,Path(run)/"predictions"/("policy_"+role+".parquet"),panel,dict(policy_id=role,risk_contexts=journal.design["risk_contexts"],anchor_ref=_ref(Path(run)/"predictions/policy_HGB.parquet")))
            putj(Path(run)/"predictions"/("risk_decisions_"+role+".json"),dict(decisions=receipts))
        else:putj(Path(run)/"predictions"/("failure_"+role+".json"),dict(policy_id=role,status="SOURCE_OR_TRAINING_NOT_TESTABLE",reason=failed,scientific_retry=0))
    return c.assemble_selection(run)


def freeze_policy_terminal(run):
    run=Path(run);journal=c._TaskLedger(run);assembly=c.assemble_selection(run)
    learned={"ESTIMATOR","SCALER","CALIBRATOR","META_MODEL","META_SCALER","META_TARGET_SCALE","HYBRID_ESTIMATOR","HYBRID_SCALER","RISK_LEARNED_UNIT","RISK_REFRESH_DISPATCH","MEMBER_SOLVE","WHOLE_SET_GATE"}
    unfinished=[(n,k,s) for n,k,s in journal.db.execute("SELECT node_id,kind,status FROM nodes") if k in learned and s in ("NAMED","STARTED")]
    require(not unfinished,"ALL_SCIENTIFIC_NODES_TERMINAL_REQUIRED_NO_UNEXECUTED_SUCCESS")
    result=dict(research_id=ID,status="ALL_POLICIES_FROZEN_BEFORE_OUTCOMES",all_training_terminal=True,all_scientific_nodes_terminal=True,
        outer_result_feedback=False,design_sha256=sha(run/"DESIGN_FREEZE.json"),assembly_ref=_ref(run/"SCORE_ASSEMBLY.json"),
        role_status=assembly["role_status"],policy_refs=assembly["score_paths"],pre2026_exposed=True,independent_holdout=False)
    path=run/"POLICY_TERMINAL.json"
    if path.exists():require(json.loads(path.read_text(encoding="utf-8"))==result,"FROZEN_POLICY_TERMINAL_CHANGED")
    else:putj(path,result)
    return result


def _immutable_account_json(path,value):
    """Append-only publication of exact owner facts, including failed traces."""
    path=Path(path)
    normalized=json.loads(json.dumps(value,ensure_ascii=False,default=str,allow_nan=False))
    if path.exists():
        require(json.loads(path.read_text(encoding="utf-8"))==normalized,"IMMUTABLE_ACCOUNT_RECEIPT_CHANGED:"+str(path))
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open("x",encoding="utf-8",newline="\n") as stream:
            json.dump(normalized,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write("\n")
    return _ref(path)


def _publish_account_result(run,role,identity,state,value):
    """Publish one ledger COMPLETE artifact; resume verifies original pins."""
    result,qualification,proof=value;output=Path(run)/"accounts"/role
    assert_safe_output_path(output,kind="backtest",paths=resolve(REPO))
    require(output.resolve().is_relative_to(Path(run).resolve()),"RUN_OWNED_ACCOUNT_PUBLICATION_REQUIRED")
    require(state["status"]=="COMPLETE" and state["identity"]==c.digest(identity),"ACCOUNT_COMPLETE_ARTIFACT_AUTHORITY_REQUIRED")
    artifact=json.loads(state["artifact"]);require(sha(artifact["path"])==artifact["sha256"],"ACCOUNT_COMPLETE_ARTIFACT_CHANGED")
    frames={name:getattr(result,name,None) for name in
        ("daily","positions","orders","fills","execution_results","entitlements","accounting_exceptions","contexts","operational_actions")}
    frames={name:frame for name,frame in frames.items() if frame is not None}
    if proof is not None:frames["source_quote_proof"]=proof
    facts={"qualification":qualification,"owner_metadata":getattr(result,"metadata",{}),
        "owner_audit":getattr(result,"audit",{}),"owner_prefix_identity":getattr(result,"prefix_identity",None)}
    normalized={name:json.loads(json.dumps(value,default=str,allow_nan=False)) for name,value in facts.items()}
    expected_content={name+".parquet":c._frame_hash(frame) for name,frame in frames.items()}
    expected_content.update({name+".json":c.digest(value) for name,value in normalized.items()})
    publication=output/"PUBLICATION_COMPLETE.json"
    if publication.exists():
        saved=json.loads(publication.read_text(encoding="utf-8"))
        require(saved["identity_sha256"]==c.digest(identity) and saved["node_artifact"]==artifact
            and saved["content_sha256"]==expected_content and set(saved["files"])==set(expected_content),
            "ACCOUNT_PUBLICATION_IDENTITY_OR_CONTENT_CHANGED")
        for ref in saved["files"].values():
            require(Path(ref["path"]).resolve().parent==output.resolve() and sha(ref["path"])==ref["sha256"],
                "ACCOUNT_PUBLICATION_PHYSICAL_CHANGED")
    else:
        output.mkdir(parents=True,exist_ok=True);files={}
        # A file without its closed publication is preserved as an incomplete
        # engineering artifact; it is never silently rehashed or overwritten.
        require(not any((output/name).exists() for name in expected_content),"INCOMPLETE_ACCOUNT_PUBLICATION_NO_OVERWRITE")
        for name,frame in frames.items():
            path=output/(name+".parquet");frame.to_parquet(path,index=False);files[path.name]=_ref(path)
        for name,value in normalized.items():
            path=output/(name+".json");files[path.name]=_immutable_account_json(path,value)
        saved=dict(research_id=ID,policy_id=role,status="COMPLETE",identity_sha256=c.digest(identity),
            node_artifact=artifact,content_sha256=expected_content,files=files)
        _immutable_account_json(publication,saved)
    return dict(daily=saved["files"]["daily.parquet"],qualification=saved["files"]["qualification.json"],
        publication=_ref(publication),source_quote_proof=saved["files"].get("source_quote_proof.parquet"))


def run_accounts(run,policy_terminal=None):
    from scripts.research.a2.data.full_selector_account_inputs import load_account_inputs
    from scripts.research.a2.evaluation.full_selector_accounts import run_fixed_accounts
    import pyarrow as pa
    import pyarrow.parquet as pq
    run=Path(run);journal=c._TaskLedger(run);terminal=freeze_policy_terminal(run) if policy_terminal is None else policy_terminal;bound=load_account_inputs(run)
    core=policy_terminal is not None
    if core:
        require(terminal.get('status') in ('CORE_POLICY_FROZEN_FOR_ACCOUNT','CORE_BASE_POLICY_FROZEN_FOR_ACCOUNT') and terminal.get('design_sha256')==sha(run/'DESIGN_FREEZE.json')
            and set(terminal['policy_refs'])<=set(c.CORE),'EXACT_FROZEN_CORE_ACCOUNT_ONLY')
    refs={};failed={}
    for role in journal.design["account_path_ids"]:
        node="ACCOUNT|"+role
        if role not in terminal["policy_refs"]:
            if core:continue
            journal.block(node,"POLICY_NOT_COMPLETE");failed[role]=dict(status="POLICY_NOT_COMPLETE");continue
        policy_ref=terminal["policy_refs"][role]
        require(sha(policy_ref["path"])==policy_ref["sha256"],"FROZEN_ACCOUNT_POLICY_CHANGED")
        panel,_=c._load_frame(policy_ref["path"])
        selected=panel.loc[panel.selected,KEYS+["ticker","score"]].copy()
        selected=selected.sort_values(["signal_date","score","security_uid"],ascending=[True,False,True],kind="stable")
        selected["rank"]=selected.groupby("signal_date").cumcount()+1;selected["path_id"]=role
        identity=dict(policy_ref=policy_ref,account_sources=journal.design["account_inputs"],account_config=journal.design["account_config"],friction=journal.design["friction"])
        output=run/"accounts"/role;trace=output/"owner_trace"
        def replay(enter):
            # Only the retained owner emits these values. No replay or extra
            # economic projection occurs to recover a failed causal trace.
            require(not trace.exists(),"PRESERVE_EXISTING_ACCOUNT_OWNER_TRACE")
            writers={};counts={};entered=False;returned=False;error=None
            def begin():
                nonlocal entered
                enter(dict(operation="existing_continuous_account_full752"));entered=True
                assert_safe_output_path(trace,kind="backtest",paths=resolve(REPO))
                trace.mkdir(parents=True,exist_ok=False)
                _immutable_account_json(trace/"TRACE_IDENTITY.json",dict(policy_id=role,node_id=node,
                    identity_sha256=c.digest(identity),identity=identity,original_owner_values=True))
            def callback(name,frame):
                if name not in {"daily","positions","orders","fills","execution_results","entitlements",
                        "accounting_exceptions","contexts","operational_actions"} or frame.empty:return
                require(entered,"ORIGINAL_ACCOUNT_CALLBACK_BEFORE_BACKEND_ENTRY")
                table=pa.Table.from_pandas(frame,preserve_index=False)
                schema=pa.schema([pa.field(f.name,pa.timestamp("ns",tz=f.type.tz),nullable=f.nullable)
                    if pa.types.is_timestamp(f.type) else f for f in table.schema])
                table=table.cast(schema)
                if name not in writers:writers[name]=pq.ParquetWriter(trace/(name+".parquet"),schema)
                writers[name].write_table(table);counts[name]=counts.get(name,0)+len(frame)
            try:
                value=run_fixed_accounts(bound,selected,(role,),ledger_callback=callback,on_backend=begin)
                returned=True;return value
            except Exception as exc:
                error=dict(type=type(exc).__name__,reason=str(exc),traceback=traceback.format_exc());raise
            finally:
                for writer in writers.values():writer.close()
                if entered:
                    _immutable_account_json(trace/"TRACE_COMPLETE.json",dict(research_id=ID,policy_id=role,
                        node_id=node,identity_sha256=c.digest(identity),status="OWNER_AND_QUALIFICATION_RETURNED" if returned else "OWNER_OR_QUALIFICATION_FAILED",
                        entered=True,scientific_retry=0,original_owner_values=True,rows=counts,
                        files={name:_ref(trace/(name+".parquet")) for name in counts},failure=error))
        value=journal.once(node,identity,replay)
        if value is None:
            state=journal.status(node);trace_receipt=trace/"TRACE_COMPLETE.json"
            prefix_ref=None
            if trace_receipt.exists():
                saved=json.loads(trace_receipt.read_text(encoding="utf-8"))
                require(saved["identity_sha256"]==c.digest(identity),"FAILED_ACCOUNT_TRACE_IDENTITY_CHANGED")
                for ref in saved["files"].values():require(sha(ref["path"])==ref["sha256"],"FAILED_ACCOUNT_TRACE_CHANGED")
                prefix_ref=_ref(trace_receipt)
            failed[role]=dict(status=state["status"],entered=bool(state["entered"]),error=state.get("error"),
                original_owner_trace=prefix_ref,scientific_retry=0);continue
        refs[role]=_publish_account_result(run,role,identity,journal.status(node),value)
        print(json.dumps(dict(phase="ACCOUNT_TERMINAL",policy=role,status="COMPLETE",full_window_qualification=value[1][role]["full_window_complete"])),flush=True)
    receipt=dict(research_id=ID,complete=refs,failed=failed,account_inputs=journal.design["account_inputs"],config=journal.design["account_config"],same_policy_all_accounts=True)
    name="CORE_BASE_ACCOUNT_TERMINAL.json" if terminal.get("status")=="CORE_BASE_POLICY_FROZEN_FOR_ACCOUNT" else "CORE_ACCOUNT_TERMINAL.json" if core else "ACCOUNT_TERMINAL.json"
    _immutable_account_json(run/name,receipt);return receipt

def evaluate(run,outer_h5_loader):
    from scripts.research.a2.evaluation import full_selector_evidence as e
    run=Path(run);journal=c._TaskLedger(run);terminal=freeze_policy_terminal(run)
    account_terminal=json.loads((run/"ACCOUNT_TERMINAL.json").read_text(encoding="utf-8"))
    clock_ref=journal.design["evaluation"]["clock_ref"]
    require(sha(clock_ref["path"])==clock_ref["sha256"],"FROZEN_EVALUATION_CLOCK_CHANGED")
    reader=FullSelectorReader(run);clock=pd.read_parquet(clock_ref["path"])
    raw,_=c._load_frame(run/"predictions/policy_RAW.parquet")
    # Final outcome read happens only after all finite policies are terminal.
    labels=reader.labels("2023-01-01","2026-01-01");diagnostics={};account_series={};qualifications={}
    for role,ref in terminal["policy_refs"].items():
        panel,_=c._load_frame(ref["path"]);daily=e.selection_daily(raw,panel,labels,clock);diagnostics[role]=daily
        daily.to_parquet(run/"predictions"/("diagnostics_"+role+".parquet"),index=False)
    for role,refs in account_terminal["complete"].items():
        require(sha(refs["daily"]["path"])==refs["daily"]["sha256"],"ACCOUNT_DAILY_CHANGED")
        daily=pd.read_parquet(refs["daily"]["path"])
        try:
            account_source_qualification(refs,role)
            qualifications[role]=e.account_qualification(daily,clock,role)
            account_series[role]={m:e.account_netlog(daily,clock,f) for m,f in (("TOTAL_NETLOG","TOTAL_ECONOMIC_NAV"),("LIQUID_NETLOG","LIQUID_NAV"))}
        except ValueError as exc:
            qualifications[role]=dict(policy_id=role,status='SOURCE_NOT_TESTABLE',reason=str(exc))
    endpoints={};failed={};support=pd.DatetimeIndex(clock.loc[clock.alpha_learned_mature,"signal_date"])
    for spec in e.endpoint_specs():
        metric=spec["metric"];candidate,reference=spec["candidate"],spec["reference"]
        if metric=="ALPHA" and all(role in diagnostics for role in (candidate,reference)):
            endpoints[spec["endpoint_id"]]=pd.Series(diagnostics[candidate].set_index("signal_date").loc[support,"mean_er"]-diagnostics[reference].set_index("signal_date").loc[support,"mean_er"],index=support)
        elif metric in ("TOTAL_NETLOG","LIQUID_NETLOG") and all(role in account_series for role in (candidate,reference)):
            endpoints[spec["endpoint_id"]]=account_series[candidate][metric]-account_series[reference][metric]
    outer_keys=reader.keys.loc[reader.keys.signal_date.ge('2023-01-01'),KEYS+['ticker']].copy()
    packet=outer_h5_loader(run,terminal,outer_keys)
    require(isinstance(packet,dict) and {'frame','source_ref'}<=set(packet),'NATIVE_OUTER_H5_SOURCE_PACKET_REQUIRED')
    for spec in e.endpoint_specs():
        if spec['metric'] in ('TOTAL_NETLOG','LIQUID_NETLOG') and spec['endpoint_id'] not in endpoints:
            reasons={role:qualifications.get(role,accounts_failure) for role in (spec['candidate'],spec['reference'])
                if role not in account_series for accounts_failure in [account_terminal['failed'].get(role,'ACCOUNT_NOT_COMPLETE')]}
            failed[spec['endpoint_id']]='ACCOUNT_NOT_TESTABLE:'+json.dumps(reasons,default=str)
    h5_returns,source_failures=outer_h5_series(run,terminal,clock,packet)
    putj(run/'evaluation/h5_source_coverage.json',source_failures)
    identity=dict(design=sha(run/"DESIGN_FREEZE.json"),terminal=_ref(run/"POLICY_TERMINAL.json"),accounts=_ref(run/"ACCOUNT_TERMINAL.json"),rule=e.RULE,endpoints=e.endpoint_specs(),source_h5=source_failures)
    def bootstrap(enter):
        enter(dict(operation="single_shared_5000_master_block_draw_maxT"))
        return e.paired_statistics(clock,endpoints,h5_returns,failed,design=journal.design,terminal=terminal,account_qualifications=qualifications)
    result=journal.once("STATISTICS|SHARED_321",identity,bootstrap)
    require(result is not None,"STATISTICS_STARTED_OR_FAILED_CANNOT_REBOOTSTRAP")
    summary,receipt,maxima=result;output=run/"evaluation";output.mkdir(parents=True,exist_ok=True)
    summary.to_parquet(output/"paired_summary.parquet",index=False);np.save(output/"master_max_t.npy",maxima)
    receipt.update(source_h5_failures=source_failures);putj(output/"statistics_complete.json",receipt)
    return summary,receipt

def source_closure(runtime_objects=()):
    """Directed local executable imports plus existing explicit native loaders."""
    import ast,importlib.util
    from scripts.research.a2.training import selector_challenge as existing
    queue=[Path(__file__),Path(c.__file__),REPO/'scripts/research/a2/data/full_selector_inputs.py',
        REPO/'scripts/research/a2/data/full_selector_account_inputs.py',REPO/'scripts/research/a2/evaluation/full_selector_accounts.py',
        REPO/'scripts/research/a2/evaluation/full_selector_evidence.py',REPO/'scripts/research/a2/risk/mechanism_risk_adapter.py',
        existing.RETAINED/'runtime_bootstrap.py',existing.RETAINED/'predictors.py',existing.RETAINED/'shared.py',
        existing.RETAINED/'calibration_fusion.py',REPO/'scripts/research/a2/retained/a2_predict_then_optimize_20260928_r1/models_native.py',
        REPO/'scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py']
    from scripts.research.a2.data import full_selector_account_inputs as account
    queue += [Path(v.__file__) for v in runtime_objects if getattr(v,'__file__',None) and Path(v.__file__).is_relative_to(REPO)]
    external={k:v for k,v in account.DEFAULT_REFS.items() if str(v['path']).endswith('.py')}
    files={}
    for name,ref in external.items():
        require(sha(ref['path'])==ref['sha256'],'EXTERNAL_EXECUTABLE_SOURCE_CHANGED:'+name)
        files[str(Path(ref['path']).resolve())]=ref['sha256']
    while queue:
        path=queue.pop().resolve()
        if str(path) in files:continue
        require(path.is_relative_to(REPO) and path.exists(),"LOCAL_SOURCE_CLOSURE_PATH_MISSING:"+str(path))
        files[str(path)]=sha(path)
        relative=path.relative_to(REPO).with_suffix('');module='.'.join(relative.parts)
        package=module.rpartition('.')[0]
        tree=ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            names=[]
            if isinstance(node,ast.Import):names=[a.name for a in node.names]
            elif isinstance(node,ast.ImportFrom):
                base=importlib.util.resolve_name('.'*node.level+(node.module or ''),package) if node.level else node.module or ''
                names=[base]+[base+'.'+a.name for a in node.names if a.name!='*']
            for name in names:
                if name.startswith('scripts.'):
                    target=REPO.joinpath(*name.split('.')).with_suffix('.py')
                    init=REPO.joinpath(*name.split('.'))/'__init__.py'
                    if target.exists():queue.append(target)
                    elif init.exists():queue.append(init)
                elif name in ('runtime_bootstrap','models_native','predictors','shared','calibration_fusion'):
                    target=existing.RETAINED/(name+'.py')
                    if target.exists():queue.append(target)
    return files


def build_design_candidate(run,risk_binding_ref):
    """Pure schema/metadata freeze construction; independent gate is external."""
    from scripts.research.a2.evaluation import full_selector_evidence as e
    from scripts.research.a2.data import full_selector_account_inputs as account
    from scripts.research.a2.training import selector_challenge as existing
    run=Path(run);cfg=json.loads((run/'run_config.json').read_text(encoding='utf-8'))
    manifest=json.loads((run/'input_manifest.json').read_text(encoding='utf-8-sig'))
    require(sha(risk_binding_ref['path'])==risk_binding_ref['sha256'],'RISK_SOURCE_BINDING_CHANGED')
    binding=json.loads(Path(risk_binding_ref['path']).read_text(encoding='utf-8'))
    contexts_ref=binding['contexts_ref']
    # The source reader alone decodes compact metadata; no numeric projection.
    from scripts.research.a2.data.full_selector_inputs import load_metadata_contexts
    contexts=load_metadata_contexts(contexts_ref)
    require(contexts['numeric_reads']==contexts['risk_fits']==0,'CONTEXT_METADATA_ONLY')
    clock_ref=manifest['input_qualification']['strengthened_guard_validation']['clock_ref']
    require(sha(clock_ref['path'])==clock_ref['sha256'],'EVALUATION_CLOCK_CHANGED')
    clock=pd.read_parquet(clock_ref['path'])
    account_inputs=dict(sources=account.DEFAULT_REFS,legacy_source_transport=[dict(original_ref=account.OLD_CA,
        custody_ref=dict(path=str(run/'source_custody'/('corporate_action_transition_r1.py.'+account.OLD_CA['sha256']+'.before')),sha256=account.OLD_CA['sha256']),original_bytes_unchanged=True)])
    manifest['account_inputs']=account_inputs;manifest['risk_inputs']=binding
    roles,contrasts=c.catalog()
    runtime=c.worker_runtime(run);fusion_runtime=runtime[8]
    candidate=dict(research_id=ID,status='FINITE_SCIENCE_RESOURCE_CANDIDATE',freeze_created_at=now(),
        human_authority=cfg['authority'],run_config_sha256=sha(run/'run_config.json'),scope=dict(full_universe=True,raw_core10_replaceable=True,outside_raw40_allowed=True,candidate_count=65,accounts_max=66),
        inputs=manifest['input_sources'],full_U_keys=manifest['input_qualification']['full_U_keys'],
        cutoffs=list(c.CUTS),feature_order=list(c.FEATURES),representation='SINGLE_FULL_U32',hybrid_representation='SINGLE_HYBRID_U34',
        feature_missing_handling='PAST_DATE_BALANCED_SCALER_MEAN_IMPUTATION_KEEP32_NO_ROW_DROP',
        target='MEAN_ER_3D_5D_10D_20D',target_formula='exact equal four source-bound stock Close excess returns relative to QQQ; all four horizons mature strictly before corresponding cutoff',
        time_boundary=dict(training_and_development_stop_exclusive='2026-01-01',market_label_forecast_risk_account_2026_rows=0,read_2027=False,exposed_pre2026=True,independent_holdout=False),
        training_specs=c.learners.capacity_specs(input_feature_count=32,representation=c.learners.SINGLE_FULL_U32),
        hybrid_specs=c.learners.capacity_specs(input_feature_count=34,representation=c.learners.SINGLE_HYBRID_U34),
        fusion_specs=fusion_runtime.SPEC,fusion_members=list(c.FUSION_MEMBERS),
        inner_selection=dict(year2024=['2023-07-01'],year2025=['2024-01-01','2024-07-01'],native_losses='owner source _validation_record',ties='LOW then MID then HIGH',outer_result_feedback=False),
        row_weights='N/(D*N_t) complete legal mature keys',native_seeds=list(c.learners.SEEDS),capacities=list(c.learners.CAPACITIES),
        output_rule='complete native score DESC then UID ASC; first min(20,N); each 5%; no positivity filter, normalization or Raw core constraint',
        raw_fallback_2023_exact=True,catalog=roles,contrasts=contrasts,
        risk_inputs=dict(risk_binding_ref),risk_contexts=contexts_ref,risk_recipe=risk.fixed_policy_risk_specification(),
        risk_update_rule='initial + month first + original fullU/UID/epoch/source invalidation; fixed whole training/OOF/outer metadata schedule',
        member_rule=dict(max_swaps=20,minimum_ordinal_quality_fraction=.975,tie='exitUID,entrantUID deterministic',claim='bounded strict improving local solution, not global optimum'),
        gates=GATE_OWNER,account_inputs=account_inputs,account_config=account.ACCOUNT,friction=account.FRICTION,
        account_path_ids=[r['policy_id'] for r in roles],account_accounting='ordinary issuer pay-date end cash; next session spendable; exact MKFG5/raw-share unsettled rights nonspendable; no annual reset/liquidation',
        evaluation=dict(rule=e.RULE,clock_ref=clock_ref,clock_sha256=e.clock_digest(clock),endpoint_specs=e.endpoint_specs(),comparison_count=95,outcome_gate='all training/policies terminal before paired outer outcome comparison',descriptive_fields=['annual_and_cumulative_dual_NAV_returns','max_drawdown','cost_once','turnover','fills','holding_age','gross_cash_concentration','rejected_orders','unspendable_receivables','native_H5_std_down_CVaR','raw_overlap_core10_outside40','rank_IC','complete_domain_and_qualification']),
        dag=task_dag(contexts),resources=cfg['resource_policy'],sources=source_closure(runtime),
        runtime_dependencies=dict(native_existing_paths=[str(existing.RETAINED),str(existing.DEP),str(existing.TORCH_DEP)],native_runtime=runtime[5].RUNTIME),
        registry=dict(automatic_preflight=_ref(run/'REGISTRY_PREFLIGHT.json'),explicit_human_scope_review=dict(path=str(Path(cfg['cache_root'])/'INDEPENDENT_TASK_SCOPE_REVIEW.json'),scope_fields=list(SCOPE_FIELDS),scope_payload_sha256=c.digest({k:json.loads((Path(cfg['cache_root'])/'INDEPENDENT_TASK_SCOPE_REVIEW.json').read_text(encoding='utf-8'))[k] for k in SCOPE_FIELDS})),accepted_registry_modified=False),
        preservation=dict(old_C14_reopened=False,old_C15_started=False,old_statistics_recomputed=False,failed_history_preserved=True),
        strict_PIT_promotion_eligible=False,production_qualified=False,certified_quote_authority=False,broker_allowed=False)
    putj(run/'input_manifest.json',manifest)
    candidate['input_manifest_sha256']=sha(run/'input_manifest.json')
    path=Path(cfg['cache_root'])/'DESIGN_CANDIDATE.json';putj(path,candidate)
    print(json.dumps(dict(phase='FINITE_DESIGN_CANDIDATE',path=str(path),sha256=sha(path),counts=candidate['dag']['counts'],sources=len(candidate['sources']),fits=0)),flush=True)
    return candidate


def outer_h5_series(run,terminal,clock,packet):
    """Only complete native selected baskets on the fixed whole H5 calendar."""
    from scripts.research.a2.evaluation import full_selector_evidence as e
    frame=packet['frame'];require({'signal_date','security_uid','ticker','y_open5','native_metadata_qualified'}<=set(frame),'NATIVE_H5_FULL_KEY_PACKET')
    require(sha(packet['source_ref']['path'])==packet['source_ref']['sha256'],'NATIVE_H5_SOURCE_CHANGED')
    dates=pd.DatetimeIndex(clock.loc[clock.h5_endpoint_calendar_available,'signal_date'])
    returns={};failed={};coverage={}
    for role,ref in terminal['policy_refs'].items():
        panel,_=c._load_frame(ref['path']);selected=panel.loc[panel.selected & panel.signal_date.isin(dates),KEYS+['ticker']]
        joined=selected.merge(frame[KEYS+['ticker','y_open5','native_metadata_qualified']],on=KEYS+['ticker'],how='left',validate='one_to_one')
        good=joined.native_metadata_qualified.eq(True)&np.isfinite(joined.y_open5.to_numpy(float))
        counts=joined.groupby('signal_date').size().reindex(dates,fill_value=0)
        coverage[role]=dict(required_dates=len(dates),selected_rows=len(joined),native_rows=int(good.sum()),missing_rows=int((~good).sum()),full_calendar=bool(counts.eq(20).all()))
        if not good.all() or not counts.eq(20).all():
            failed[role]='SOURCE_NOT_TESTABLE_COMPLETE_NATIVE_H5_BASKET';continue
        series=joined.groupby('signal_date').y_open5.sum().reindex(dates)/20
        require(np.isfinite(series).all(),'NATIVE_H5_NO_ZERO_FILL');returns[role]=series
    output=Path(run)/'evaluation';output.mkdir(parents=True,exist_ok=True)
    source=dict(source_ref=packet['source_ref'],roles=coverage,failed=failed,numeric_h5_rows=packet.get('numeric_h5_rows'),unknown_tail_fabricated=False,missing_filled_with_zero=False)
    if returns:
        pd.DataFrame(returns,index=dates).rename_axis('signal_date').reset_index().to_parquet(output/'native_h5_selected_baskets.parquet',index=False)
    return returns,source


def _table(columns,rows):
    def cell(v):
        if v is None:return '不适用或未保存'
        if isinstance(v,(dict,list,tuple)):v=json.dumps(v,ensure_ascii=False,default=str)
        if isinstance(v,(float,np.floating)):v=format(v,'.8g') if np.isfinite(v) else '未知'
        return str(v).replace('|','／').replace('\n',' ')
    return ['| '+' | '.join(columns)+' |','| '+' | '.join(['---']*len(columns))+' |',*['| '+' | '.join(cell(row.get(k)) for k in columns)+' |' for row in rows]]


def render_report(run):
    """Describe actual original-owner artifacts; never rank economic winners."""
    run=Path(run);journal=c._TaskLedger(run);terminal=freeze_policy_terminal(run)
    accounts=json.loads((run/'ACCOUNT_TERMINAL.json').read_text(encoding='utf-8'))
    receipt=json.loads((run/'evaluation/statistics_complete.json').read_text(encoding='utf-8'))
    require(receipt['status']=='COMPLETE','REAL_SHARED_STATISTICS_REQUIRED_BEFORE_REPORT')
    summary=pd.read_parquet(run/'evaluation/paired_summary.parquet');cfg=json.loads((run/'run_config.json').read_text(encoding='utf-8'))
    roles,contrasts=c.catalog();counts=[dict(kind=k,status=s,entered=n,count=q) for k,s,n,q in journal.db.execute('SELECT kind,status,entered,count(*) FROM nodes GROUP BY kind,status,entered')]
    role_rows=[];selection_rows=[];account_rows=[];risk_rows=[];training_rows=[];predicted_risk_rows=[]
    h5path=run/'evaluation/native_h5_selected_baskets.parquet'
    h5=pd.read_parquet(h5path).set_index('signal_date') if h5path.exists() else pd.DataFrame()
    for item in roles:
        role=item['policy_id'];state=terminal['role_status'][role]
        if role in terminal['policy_refs']:
            state='NEWLY_TRAINED_OR_ESTIMATED_AND_EVALUATED' if role!='RAW' else 'EXACT_REUSED_AND_EVALUATED'
        if role not in accounts['complete']:state='ACCOUNT_NOT_TESTABLE' if role in terminal['policy_refs'] else state
        role_rows.append(dict(policy=role,kind=item['kind'],status=state,selection_complete=role in terminal['policy_refs'],account_complete=role in accounts['complete'],reason=accounts['failed'].get(role)))
        choicepath=run/'predictions'/('selection_'+role+'.json')
        if choicepath.exists():
            choice=json.loads(choicepath.read_text(encoding='utf-8'))
            for year,value in choice['choices'].items():training_rows.append(dict(policy=role,year=year,**value,full_legal_date_balanced_training=True))
        riskpath=run/'predictions'/('risk_decisions_'+role+'.json')
        if riskpath.exists():
            rows=json.loads(riskpath.read_text(encoding='utf-8'))['decisions']
            for year in (2024,2025):
                group=[v for v in rows if str(v['signal_date']).startswith(str(year))]
                record=dict(policy=role,year=year,actual_decisions=len(group))
                for field in ('anchor_objective','objective','ordinal_quality_floor','selected_ordinal_mean','candidate_objective_evaluations','hgb_statistic','raw_statistic'):
                    values=[v[field] for v in group if field in v and v[field] is not None]
                    record[field+'_mean']=float(np.mean(values)) if values else None
                record['accepted_swaps_total']=sum(len(v.get('accepted_swaps',[])) for v in group)
                record['gate_pass_count']=sum(v.get('passed') is True for v in group) if role.startswith('GATE_') else None
                predicted_risk_rows.append(record)
        path=run/'predictions'/('diagnostics_'+role+'.parquet')
        if path.exists():
            d=pd.read_parquet(path)
            for year,g in d.groupby('year'):
                mature=g.loc[g.mature]
                selection_rows.append(dict(policy=role,year=year,dates=len(g),mature_dates=len(mature),mean_ER_return=mature.mean_er.mean(),incremental_ER_return=mature.alpha_edge.mean(),rank_IC=mature.rank_ic.mean(),raw_overlap=g.raw_overlap.mean(),replaced_core10=g.raw_core10_replaced.mean(),outside_raw40=g.selected_outside_raw40.mean(),member_turnover=g.member_turnover.mean()))
        if role in accounts['complete']:
            refs=accounts['complete'][role];account_source_qualification(refs,role)
            require(sha(refs['daily']['path'])==refs['daily']['sha256'],'ACCOUNT_REPORT_DAILY_CHANGED')
            d=pd.read_parquet(refs['daily']['path']).sort_values('date');d['year']=pd.to_datetime(d.date).dt.year
            for label,g in [('ALL_2023_2025',d),*list(d.groupby('year'))]:
                before=d.loc[pd.to_datetime(d.date)<pd.Timestamp(g.date.iloc[0])]
                row=dict(policy=role,year=label,dates=len(g))
                for field in ('TOTAL_ECONOMIC_NAV','LIQUID_NAV'):
                    initial=3000. if before.empty else float(before[field].iloc[-1]);v=g[field].to_numpy(float)
                    row[field+'_end_USD']=v[-1];row[field+'_return']=v[-1]/initial-1
                    curve=np.r_[initial,v];row[field+'_max_drawdown']=float(np.min(curve/np.maximum.accumulate(curve)-1))
                for field in ('gross_exposure','cash','turnover','transaction_cost_amount','receivable_value_usd'):
                    row[field+('_sum' if field=='transaction_cost_amount' else '_mean')]=float(g[field].sum() if field=='transaction_cost_amount' else g[field].mean()) if field in g else None
                root=Path(refs['daily']['path']).parent
                for table in ('fills','execution_results','positions'):
                    fpath=root/(table+'.parquet')
                    if not fpath.exists():continue
                    f=pd.read_parquet(fpath);datefield='execution_date' if 'execution_date' in f else 'date' if 'date' in f else None
                    if datefield and label!='ALL_2023_2025':f=f.loc[pd.to_datetime(f[datefield]).dt.year.eq(label)]
                    if table=='fills':row['fill_count']=len(f)
                    elif table=='execution_results':row['rejected_execution_count']=int(f.status.eq('REJECTED').sum()) if 'status' in f else None
                    elif table=='positions':
                        row['held_age_mean']=float(f.loc[f.fractional_shares.gt(0),'holding_age'].mean()) if {'holding_age','fractional_shares'}<=set(f) else None
                        row['max_single_position_weight']=float(f.weight.max()) if 'weight' in f else None
                account_rows.append(row)
        if role in h5:
            for label,g in [('ALL_NATIVE_H5',h5[role]),*list(h5[role].groupby(h5.index.year))]:
                values=g.to_numpy(float);risk_rows.append(dict(policy=role,year=label,dates=len(values),H5_std_return=float(np.std(values,ddof=1)),H5_downside_return=float(np.sqrt(np.mean(np.minimum(values,0)**2))),H5_CVaR_loss_return=float(__import__('scripts.research.a2.evaluation.full_selector_evidence',fromlist=['_risk_function'])._risk_function(values,'CVAR'))))
    complete_all=len(accounts['complete'])==66 and summary.status.eq('COMPLETE').all()
    supported=int(summary.supported.eq(True).sum())
    status=('COMPLETE_WITH_RESEARCH_SUPPORT_NOT_PRODUCTION' if supported else 'COMPLETE_FULL_SCOPE_NO_SUPPORTED_REPLACEMENT') if complete_all else ('CORE_COMPLETE_BREADTH_PARTIAL' if set(c.CORE)<=set(accounts['complete']) else 'PARTIAL_REAL_SOURCE_BLOCKED')
    lines=['# C 完整股票池选股与固定账户研究报告','',f'任务：{ID}。实际交付状态：**{status}**。',
        f'目录固定为65个候选和Raw，共66条账户；实际完整账户{len(accounts["complete"])}条，321个事前端点中{int(summary.status.eq("COMPLETE").sum())}个可检验，获得各自预定标准支持的端点{supported}个。账户、选股和风险支持分别列出，不依据NAV另选赢家。','',
        '本次研究限定2023–2025共同评价窗口；训练及每次选择只消费相应cutoff以前完整成熟的标签。2023全部政策同Raw fallback，2024–2025共502日模型输出，482日成熟alpha支持；账户752日连续运行，H5只用冻结日历和完整原生来源。2026及2027行情、标签、推断、拟合、风险更新和账户评价均未授权进入。','',
        '历史窗口已暴露，独立留出为false；strict PIT、生产资格、市场报价认证和broker交易授权均为false。C14结论与文件保留，A关闭、B独立和C15未启动不因本任务改变。','',
        '## 冻结设计与复用','',
        '复用原canonical BASE32、四h等权MEAN_ER、完整共同历史U、native模型工厂、风险估计平台、固定成员目标与连续账户引擎。新增为单股全U32／hybrid34表示和本次有限调用编排。Raw评分不进训练特征，UID仅用于身份与确定性tie。','',
        '每只入选证券固定5%，最多20只，负预测不现金过滤；可替换Raw前10，允许Raw40以外入选。风险更新为初始、月首及原U／UID／epoch／source改变，最高20次严格改善swap且保留97.5%HGB序位质量；这是有界局部结果，不是全局最优证明。','',
        '账户初始USD3000空仓，下一合法raw Open先卖后买，单程10bp只计一次；不年重置、不期末强平，不融资、不计现金利息。普通现金权益按来源支付日终入账、下一交易日可用；MKFG5USD/raw share未知结算权益进入非可支用应收。TOTAL与LIQUID NAV必须共同满足资格和支持标准。','',
        f'冻结SHA：{sha(run/"DESIGN_FREEZE.json")}；原始用户请求SHA：{journal.design["human_authority"]["sha256"]}。',
        '','## 实际工作量与失败保留','']
    lines+=_table(['kind','status','entered','count'],counts)
    lines+=['','entered是实际后台操作入口，不是输出文件数。未进入的风险上界slot为NOT_REQUIRED；失败不退款，无科学重试，不把工程异常、缺来源或账户资格不足写成负经济结果。','',
        '## 全角色覆盖','']+_table(['policy','kind','status','selection_complete','account_complete','reason'],role_rows)
    lines+=['','## 训练、容量选择及真正过去OOF','', '确定性模型1seed；随机模型使用固定20260928／29／30全部required等权。LOW／MID／HIGH只由原生损失的过去验证选择，2024用2023过去OOF，2025用2024两个过去OOF；固定MID六成员融合不使用in-sample或Raw fallback。具体学习参数已完整存入科学冻结，失败选择也保留。','']+_table(['policy','year','selected_capacity','inner_folds','past_only_validation','full_legal_date_balanced_training'],training_rows)
    lines+=['','## 逐年选股结果','', '收益数值单位return（1=100%）；重叠与替换为平均证券数。2023共同fallback不计为模型训练成功。','']+_table(list(selection_rows[0]) if selection_rows else ['policy'],selection_rows)
    lines+=['','## 连续账户结果','', '收益含冻结执行摩擦，不代表实际券商账户净赚。缺来源账户保留真实prefix与失败理由，不能删除日期或填零进入配对。持仓与订单完整账本见各账户目录。','']+_table(list(dict.fromkeys(k for row in account_rows for k in row)) or ['policy'],account_rows)
    lines+=['','## 成员机制与预测风险变化','', '下列数值来自相同已固定risk state和原数学目标，协方差目标单位为return²；CVaR／sigma目标的单位为return。风险目标下降只说明预测模型内的变化，不是账户或实现H5改善。未保存的个体风险贡献不补造。','']+_table(list(dict.fromkeys(k for row in predicted_risk_rows for k in row)) or ['policy'],predicted_risk_rows)
    lines+=['','## 实现H5风险','', '仅完整native H5 basket可列数值。预测协方差改善不能替代这里的实现风险；CVaR用原owner直接计算，不使用日代理。','']+_table(list(risk_rows[0]) if risk_rows else ['policy'],risk_rows)
    lines+=['','## 全部固定配对与统计','', '统一5000次、20session非环形移动块、固定seed20260928、单侧95%maxT；alpha要求2024与2025均正，经济要求TOTAL／LIQUID两种同时下界均正且两年方向同时正。零SE不能通过；失败端点保留曝光，不拼接旧C14统计或补造0。','']+_table(['contrast_id','metric','status','observed','bootstrap_se','lower','support_dates','annual_mean','annual_direction_pass','dual_nav_simultaneous_positive','supported'],summary.to_dict('records'))
    lines+=['','## 来源缺口与限制','',json.dumps(json.loads((run/'evaluation/h5_source_coverage.json').read_text(encoding='utf-8')),ensure_ascii=False,default=str),'',
        '完整U的预测、风险、身份与账户资格分别报告；UNKNOWN来源vintage与publication authority仍未知。风险kernel中明确披露的模型补全不是独立native scenario，scalar sigma不是full PSD replica；未保存的个体风险贡献不补造。','',
        '任何研究支持最多用于未来验证，不自动升级生产、不打开2026、不下单。独立最终验收仍须核对实际来源、账本、覆盖、报告与原冻结保护；报告存在不等于任务通过。','',
        f'运行目录：{run}；生成时间：{now()}。']
    output=Path(cfg['results_root'])/'FULL_SELECTOR_RESEARCH_REPORT.md';assert_safe_output_path(output,kind='results',paths=resolve(REPO));output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    putj(run/'DELIVERY_STATUS.json',dict(status=status,all_required_comparisons_complete=complete_all,report_ref=_ref(output),account_complete=len(accounts['complete']),supported_endpoints=supported,independent_final_acceptance=False))
    return output


def account_source_qualification(refs,role):
    """Original producer qualification and all original immutable publications."""
    require('publication' in refs and sha(refs['publication']['path'])==refs['publication']['sha256'],'ACCOUNT_PUBLICATION_CUSTODY_REQUIRED')
    publication=json.loads(Path(refs['publication']['path']).read_text(encoding='utf-8'))
    require(publication['research_id']==ID and publication['policy_id']==role and publication['status']=='COMPLETE','ACCOUNT_PRODUCER_AUTHORITY_REQUIRED')
    for ref in publication['files'].values():require(sha(ref['path'])==ref['sha256'],'ACCOUNT_PRODUCER_FILE_CHANGED')
    require(publication['files']['qualification.json']==refs['qualification'] and publication['files']['daily.parquet']==refs['daily'],'ACCOUNT_PRODUCER_PUBLICATION_CHAIN_REQUIRED')
    q=json.loads(Path(refs['qualification']['path']).read_text(encoding='utf-8'))[role]
    for field in ('full_window_complete','mechanism_accounting_consistent','execution_audit_pass','raw_endpoints_finite','actual_execution_inputs_complete','selection_input_complete'):
        require(q.get(field) is True,'ORIGINAL_ACCOUNT_PRODUCER_QUALIFICATION_REQUIRED:'+field)
    return q


def execute_all(run):
    """One worker, core first, independent breadth continues, no outcome feedback."""
    from scripts.research.a2.data.full_selector_inputs import load_fixed_policy_risk_inputs,load_fixed_policy_outer_h5
    run=Path(run);journal=c._TaskLedger(run)
    progress(run,'ACTUAL_CORE_PREDICTION_TRAINING')
    primary_core=tuple(dict.fromkeys(('RIDGE','HGB','LAMBDAMART',*c.FUSION_MEMBERS)))
    c.train_primary(run,primary_core);progress(run,'CORE_BASE_PREDICTION_TERMINAL')
    c.train_fusion(run,('equal',));progress(run,'CORE_EQUAL_FUSION_TERMINAL')
    provider=train_risk(run,load_fixed_policy_risk_inputs)
    risk_core=tuple(r for r in c.CORE if r.startswith('RISK_'))
    risk_policies(run,provider,risk_core)
    assembly=c.assemble_selection(run)
    core=dict(research_id=ID,status='CORE_POLICY_FROZEN_FOR_ACCOUNT',design_sha256=sha(run/'DESIGN_FREEZE.json'),
        policy_refs={k:v for k,v in assembly['score_paths'].items() if k in c.CORE},outer_result_feedback=False)
    _immutable_account_json(run/'CORE_POLICY_TERMINAL.json',core)
    try:run_accounts(run,policy_terminal=core)
    except Exception:
        # Original failures and emitted values remain; full independent training
        # is authorized even when a source/account package cannot be composed.
        putj(run/'accounts/core_input_failure.json',dict(error=traceback.format_exc(),source_stage=True))
    progress(run,'CORE_ACCOUNT_STAGE_TERMINAL_BREADTH_TRAINING_CONTINUES')
    remaining=tuple(r for r in c.learners.PARADIGMS if r not in primary_core)
    c.train_primary(run,remaining);c.train_fusion(run,tuple(m for m in c.FUSIONS if m!='equal'))
    risk_policies(run,provider,tuple(r for r in (*('RISK_'+f for f in c.FAMILIES),*('GATE_'+g for g in c.GATES)) if r not in risk_core))
    c.train_hybrids(run,provider);progress(run,'FULL_TRAINING_RISK_MEMBERS_TERMINAL')
    freeze_policy_terminal(run);run_accounts(run);progress(run,'ALL_APPLICABLE_ACCOUNTS_TERMINAL')
    evaluate(run,load_fixed_policy_outer_h5);progress(run,'ACTUAL_SHARED_STATISTICS_COMPLETE')
    report=render_report(run);progress(run,'REPORT_WRITTEN_INDEPENDENT_FINAL_ACCEPTANCE_PENDING')
    print(json.dumps(dict(phase='DETAILED_REPORT_WRITTEN',report_ref=_ref(report),independent_final_acceptance=False),ensure_ascii=False),flush=True)


@contextmanager
def _worker_lock(run):
    """One native process lock across both finite commands, released on exit."""
    import msvcrt
    with (Path(run)/'worker.lock').open('a+b') as handle:
        if handle.tell()==0:handle.write(b'0');handle.flush()
        handle.seek(0)
        try:msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as exc:raise ValueError('SINGLE_WORKER_PROCESS_LOCK_HELD') from exc
        try:yield
        finally:
            handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',required=True,type=Path)
    parser.add_argument('command',choices=('design-candidate','run-primary-core','run-all'))
    args=parser.parse_args();run=args.run.resolve()
    if args.command=='design-candidate':build_design_candidate(run,_ref(run/'risk_inputs.json'));return
    c._TaskLedger(run)
    with _worker_lock(run):_execute_command(run,args.command)


def _execute_command(run,command):
    # A live launch marker is immutable; recovery is reviewed separately after
    # actual ledger/partial-entry boundaries, never by repeating this entry.
    marker=run/('PRIMARY_CORE_EXECUTION_STARTED.json' if command=='run-primary-core' else 'EXECUTION_STARTED.json')
    require(not marker.exists(),'SINGLE_WORKER_ALREADY_STARTED_NO_BLIND_RESTART')
    if command=='run-primary-core':
        require(not (run/'EXECUTION_STARTED.json').exists(),'SINGLE_WORKER_FULL_PHASE_ALREADY_STARTED')
    elif (run/'PRIMARY_CORE_EXECUTION_STARTED.json').exists():
        complete=run/'PRIMARY_CORE_EXECUTION_COMPLETE.json'
        require(complete.exists(),'SINGLE_WORKER_PRIMARY_PHASE_NOT_COMPLETE')
        prior=json.loads((run/'PRIMARY_CORE_EXECUTION_STARTED.json').read_text(encoding='utf-8'))
        done=json.loads(complete.read_text(encoding='utf-8'))
        require(prior['research_id']==done['research_id']==ID and done['status']=='CORE_NON_RISK_STAGE_COMPLETE'
            and prior['design_ref']==done['design_ref']==_ref(run/'DESIGN_FREEZE.json')
            and prior['source_ref']==_ref(__file__),'SINGLE_WORKER_PRIMARY_AUTHORITY_CHANGED')
    _immutable_account_json(marker,dict(research_id=ID,created_at=now(),process_id=__import__('os').getpid(),
        design_ref=_ref(run/'DESIGN_FREEZE.json'),source_ref=_ref(__file__),workers=1,threads=2))
    try:
        if command=='run-primary-core':
            primary_core=tuple(dict.fromkeys(('RIDGE','HGB','LAMBDAMART',*c.FUSION_MEMBERS)))
            progress(run,'ACTUAL_CORE_NON_RISK_TRAINING_RISK_FACTS_PENDING')
            c.train_primary(run,primary_core);c.train_fusion(run,('equal',))
            assembly=c.assemble_selection(run)
            core=dict(research_id=ID,status='CORE_BASE_POLICY_FROZEN_FOR_ACCOUNT',design_sha256=sha(run/'DESIGN_FREEZE.json'),
                policy_refs={k:v for k,v in assembly['score_paths'].items() if k in c.CORE},outer_result_feedback=False)
            _immutable_account_json(run/'CORE_BASE_POLICY_TERMINAL.json',core)
            run_accounts(run,policy_terminal=core)
            progress(run,'CORE_NON_RISK_ACCOUNT_ENTRY_COMPLETE_RISK_FACTS_PENDING')
            _immutable_account_json(run/'PRIMARY_CORE_EXECUTION_COMPLETE.json',dict(research_id=ID,status='CORE_NON_RISK_STAGE_COMPLETE',
                design_ref=_ref(run/'DESIGN_FREEZE.json'),all_task_complete=False,risk_estimates_started=False))
        else:execute_all(run)
    except BaseException:
        putj(run/'EXECUTION_FAILURE.json',dict(research_id=ID,error=traceback.format_exc(),utc=now(),scientific_retries=0))
        progress(run,'EXECUTION_FAILED_REVIEW_REAL_ENTRY_BOUNDARIES');raise


if __name__=='__main__':main()
