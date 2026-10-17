"""Pure R5 risk-bank continuity qualification; no readers, fitters or account.

The caller guards physical refs/code before supplying frozen metadata. This
module hashes metadata and checks current event witnesses only. It never reads a
next event, numerical covariance, model output, label or economic result.
"""
from pathlib import PureWindowsPath
from typing import Mapping
from scripts.research.a2.risk.event_risk_contract_r5 import EventWitness,structural_identity
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash
from scripts.research.a2.risk.shared_risk_engine_r2 import _time,CUTOFF,COORDINATE
from .joint_event_policy_r5 import EventMethodBinding

CONTINUOUS=("SHR_HP","SHR_CC","LW","OAS","EWMA","PCA_FACTOR","QQQ_RESIDUAL")
REQUIRED_DAILY_COUNT=752
RESEARCH_ID="V24_B_DYNAMIC_FULLPOOL_RISK_AND_IDENTITY_R5"
INHERITED_FIT_UNITS=3027
CUMULATIVE_FIT_CAP=4096
MAX_NEW_FIT_UNITS=1069
REF_FIELDS={"plan":"plan_ref","support":"event_support_ref","source_authority":"source_authority_ref",
            "model_producer":"model_producer_ref","execution_producer":"execution_producer_ref"}


class ChainQualificationBlocked(ValueError):
    """Source/identity qualification failure, never an economic conclusion."""


def _need(condition,reason):
    if not condition:raise ChainQualificationBlocked(reason)


def _sha(value):
    return isinstance(value,str) and len(value)==64 and all(c in "0123456789abcdef" for c in value)


def _ref(value):
    _need(isinstance(value,dict) and isinstance(value.get("path"),str) and value["path"]
          and _sha(value.get("sha256")),"PINNED_PHYSICAL_METADATA_REF_REQUIRED")
    return value


def _clock(value):
    result=_time(value)
    _need(result<CUTOFF,"PRE2026_CURRENT_EVENT_DAY_REQUIRED")
    return result


def _primary_signature(event):
    return {k:v for k,v in event["complete_structural_signature"].items()
            if k!="ff48_qualified_source_support"}


def _verify_global(plan,support,bank,pinned_refs,expected_content_sha256,expected_code_pins,observed_code_pins):
    _need(plan.get("schema")=="B_R5_FINITE_EVENT_RISK_PLAN_V1" and
          support.get("schema")=="B_R5_EVENT_RISK_METADATA_SUPPORT_V1" and
          bank.get("schema")=="B_R5_EVENT_RISK_BANK_V1","EXACT_R5_PLAN_SUPPORT_BANK_SCHEMA_REQUIRED")
    _need(plan.get("research_id")==support.get("research_id")==bank.get("research_id")==RESEARCH_ID,
          "EXACT_CURRENT_R5_RESEARCH_IDENTITY_REQUIRED")
    maximum=plan.get("maximum_new_fit_units");new=bank.get("new_fit_units");cumulative=bank.get("cumulative_fit_units")
    _need(type(maximum) is int and 0<=maximum<=MAX_NEW_FIT_UNITS and
          plan.get("prior_cumulative_fit_units")==INHERITED_FIT_UNITS and
          plan.get("cumulative_fit_cap")==CUMULATIVE_FIT_CAP,"EXACT_R5_NONREFUNDABLE_BUDGET_SCOPE_REQUIRED")
    _need(type(new) is int and type(cumulative) is int and 0<=new<=maximum and
          cumulative==INHERITED_FIT_UNITS+new and cumulative<=CUMULATIVE_FIT_CAP,
          "BANK_NONREFUNDABLE_BUDGET_ACCOUNTING_MISMATCH")
    for name,value in (("plan",plan),("support",support),("bank",bank)):
        _need(_sha(expected_content_sha256.get(name)) and
              content_hash(value)==expected_content_sha256[name],"FROZEN_METADATA_CONTENT_CHANGED:"+name)
    for name,field in REF_FIELDS.items():
        _need(_ref(bank.get(field))==_ref(pinned_refs.get(name)),"BANK_CALLER_PHYSICAL_PIN_MISMATCH:"+name)
    _ref(pinned_refs.get("bank"))
    run=PureWindowsPath(pinned_refs["plan"]["path"]).parent
    _need(run in PureWindowsPath(pinned_refs["bank"]["path"]).parents,
          "R5_BANK_MUST_BE_OWNED_BY_CURRENT_PLAN_RUN")
    _need(plan.get("support_ref")==pinned_refs["support"] and
          plan.get("model_producer_ref")==pinned_refs["model_producer"] and
          plan.get("source_authority_ref")==pinned_refs["source_authority"],"PLAN_SOURCE_CUSTODY_MISMATCH")
    _need(isinstance(expected_code_pins,Mapping) and bool(expected_code_pins) and
          dict(expected_code_pins)==dict(observed_code_pins) and
          all(_sha(s) for s in expected_code_pins.values()),"PINNED_CODE_CLOSURE_CHANGED")
    for name in ("model_producer","execution_producer"):
        reference=pinned_refs[name]
        _need(expected_code_pins.get(reference["path"])==reference["sha256"],"PRODUCER_CODE_NOT_IN_GUARDED_CLOSURE:"+name)
    _need(bank.get("method_bindings")==plan.get("method_bindings") and
          set(plan.get("continuous_families",()))==set(CONTINUOUS),"EXACT_FROZEN_FAMILY_ROSTER_REQUIRED")
    _need(bank.get("future_next_event_lookup_allowed") is False and
          all(bank.get(k) is False for k in ("strict_PIT_promotion_eligible","quote_qualified","certified_nav_qualified")),
          "SOURCE_CHAIN_CANNOT_PROMOTE_ECONOMIC_OR_STRICT_PIT_AUTHORITY")
    daily=support.get("daily_support_chain",[])
    _need(len(daily)==support.get("decision_session_count")==REQUIRED_DAILY_COUNT,
          "COMPLETE_752_DAILY_SUPPORT_DOMAIN_REQUIRED")
    return daily


def _event_indices(support):
    events={};last=None
    for event in support["events"]:
        asof=_clock(event["decision_asof"])
        _need(event["event_id"] not in events and (last is None or asof>last),"UNIQUE_MONOTONIC_EVENT_METADATA_REQUIRED")
        _need(_clock(event["fit_history_cutoff"])<asof,"ORIGINAL_EVENT_FIT_CUTOFF_MUST_PRECEDE_CLOSE")
        assets=tuple(event["requested_assets"])
        signature=event["complete_structural_signature"]
        _need(signature["ordered_assets"]==list(assets) and signature["asset_uids"]==event["asset_uids"] and
              signature["asset_epochs"]==event["asset_epochs"] and signature["security_coordinates"]==event["security_coordinates"],
              "CURRENT_EVENT_FULL_DOMAIN_PROOF_MISMATCH")
        _need(content_hash(signature)==event["structural_signature_sha256"],"EVENT_STRUCTURAL_METADATA_MUTATION")
        _need(content_hash(_primary_signature(event))==event["dependency_local_signature_sha256"]["PRIMARY"] and
              content_hash(signature)==event["dependency_local_signature_sha256"]["FF48"],"METHOD_LOCAL_SOURCE_SIGNATURE_MISMATCH")
        _need(set(event["history_support"]["nominal_n"])==set(assets),"FULL_N0_HISTORY_METADATA_DOMAIN_REQUIRED")
        # UID/epoch validity is checked without inventing security type/class.
        structural_identity(assets=assets,uids=event["asset_uids"],epochs=event["asset_epochs"],
            security_coordinate=COORDINATE,source_support_identity={"source":signature["source_identity"]})
        events[event["event_id"]]=event;last=asof
    return events


def _record_index(plan,bank,events):
    nodes={};roster=set()
    for node in plan["nodes"]:
        _need(node["event_id"] in events and node["event_id"] not in nodes,"EXACT_FROZEN_PRIMARY_NODE_REQUIRED")
        nodes[node["event_id"]]=node
        _need(node["dependency"]=="PRIMARY" and set(node["family_dependencies"])==set(node["families"]),
              "COMPLETE_FAMILY_LOCAL_DEPENDENCY_MAP_REQUIRED")
        for family in node["families"]:
            dep="FF48" if family=="FF48_HIERARCHICAL" else "PRIMARY"
            _need(node["family_dependencies"][family]==dep,"UNFROZEN_FAMILY_SOURCE_DEPENDENCY")
            roster.add((node["event_id"],family))
    qualified={};blocked={};retained=[]
    for passed,records in ((True,bank.get("states",[])),(False,bank.get("blocked_or_failed",[]))):
        for record in records:
            eid,family=record["event_id"],record["family"]
            _need((eid,family) in roster,"BANK_FAMILY_NOT_IN_FROZEN_QUEUE")
            dep=nodes[eid]["family_dependencies"][family]
            local=events[eid]["dependency_local_event_ids"][dep]
            _need(record["dependency"]==dep and record["dependency_local_event_id"]==local,
                  "BANK_EVENT_LOCAL_DEPENDENCY_MISMATCH")
            key=(family,local)
            _need(key not in qualified and key not in blocked,"DUPLICATE_BANK_FAMILY_EVENT_STATE")
            (qualified if passed else blocked)[key]=record
            if not passed:retained.append({k:record.get(k) for k in
                ("family","event_id","dependency","dependency_local_event_id","status","block_reason","risk_state_id","artifact_ref")})
    return nodes,qualified,blocked,retained


def _state_metadata(state):
    """Whitelist only; covariance/sigma/output fields are never accessed."""
    def get(k):return state.get(k) if isinstance(state,Mapping) else getattr(state,k)
    coverage=get("coverage")
    return dict(risk_state_id=get("risk_state_id"),assets=tuple(get("assets")),method=get("method"),
        status=get("status"),as_of=get("as_of"),cutoff=get("cutoff"),
        coverage={a:{k:v.get(k) for k in ("uid","identity_epoch","nominal_n","n0_prior_only")}
                  for a,v in coverage.items()},event_policy_binding=get("notes").get("event_policy_binding"))


def _qualify_record(record,family,node,current,day,fit_event,binding,plan_ref,qualified_states):
    _need(family!="TAIL_CVAR","TAIL_CVAR_INDEPENDENT_SCENARIO_SOURCE_UNBOUND")
    _need(record.get("status")=="PASS_FROZEN_HISTORY_MECHANISM" and record.get("finite_check") is True,
          "QUALIFIED_PRODUCER_FINITE_METADATA_REQUIRED")
    _need(record.get("recipe_id")==node["recipe_id"] and record.get("method")==binding["method"],
          "FAMILY_RECIPE_OR_METHOD_MISMATCH")
    _need(binding["availability"]=="READY","FAMILY_SOURCE_NOT_READY:"+binding["availability"])
    _need(record.get("assets")==current["requested_assets"] and record.get("asset_uids")==current["asset_uids"] and
          record.get("asset_epochs")==current["asset_epochs"],"CURRENT_FULL_REQUESTED_UID_EPOCH_DOMAIN_CHANGED")
    _need(_clock(record["as_of"])==_clock(fit_event["decision_asof"]) and
          _clock(record["cutoff"])==_clock(fit_event["fit_history_cutoff"]),"ORIGINAL_FIT_CUTOFF_CHANGED")
    source=record["source_support_identity"];dep=node["family_dependencies"][family]
    _need(source.get("dependency")==dep and
          source.get("dependency_local_event_id")==current["dependency_local_event_ids"][dep] and
          source.get("dependency_local_signature_sha256")==current["dependency_local_signature_sha256"][dep],
          "CURRENT_METHOD_LOCAL_SOURCE_EVENT_CHANGED")
    pins=source.get("source_pins",{})
    _need(pins.get("scientific_contract")==plan_ref["sha256"] and bool(pins),"SOURCE_SUPPORT_NOT_BOUND_TO_FROZEN_PLAN")
    if dep=="FF48":
        _need(isinstance(source.get("industry_source"),dict) and
              pins.get("FF48")==source["industry_source"].get("sha256"),"FF48_EXACT_INDUSTRY_SOURCE_PIN_REQUIRED")
    receipt=record["source_receipt"]
    _need(receipt.get("return_coordinate")==COORDINATE and
          receipt.get("status")=="FROZEN_HISTORY_MECHANISM_SOURCE_BOUND" and
          receipt.get("mechanism") is True and receipt.get("synthetic") is False and
          receipt.get("scientific_contract_sha256")==plan_ref["sha256"] and
          receipt.get("identity_epoch")=="R5_CURRENT_POOL_OBSERVED_UIDS:"+content_hash(current["asset_epochs"]),
          "QUALIFIED_SOURCE_COORDINATE_OR_POOL_EPOCH_MISMATCH")
    _need(receipt.get("strict_PIT_promotion_eligible") is False and receipt.get("quote_qualified") is False and
          receipt.get("historical_authority_status")=="UNKNOWN","MECHANISM_SOURCE_AUTHORITY_UPGRADE_FORBIDDEN")
    # Local signature includes security coordinates, source semantics and feature support.
    sid=structural_identity(assets=tuple(current["requested_assets"]),uids=current["asset_uids"],epochs=current["asset_epochs"],
        security_coordinate=receipt["return_coordinate"],source_support_identity=source)
    proof=dict(parent_risk=binding["parent_risk"],representation=binding["representation"],
        recipe_sha256=binding["recipe_sha256"],model_producer_sha256=binding["producer_sha256"],
        structural_identity=sid,source_support_identity_sha256=content_hash(source),
        asset_uid_epoch_sha256=content_hash(dict(uids=current["asset_uids"],epochs=current["asset_epochs"])))
    _need(record.get("event_policy_binding")==proof,"BANK_PRODUCER_SOURCE_UID_PROOF_MISMATCH")
    history=current["history_support"]
    source_valid=not history.get("source_metadata_blockers") and not history.get("current_identity_blockers")
    EventWitness(str(day),sid,record["event_policy_binding"]["structural_identity"],source_valid,True).validate(record["as_of"])
    if qualified_states is not None:
        _need(record["risk_state_id"] in qualified_states,"CALLER_QUALIFIED_STATE_METADATA_MISSING")
        meta=_state_metadata(qualified_states[record["risk_state_id"]])
        _need(meta["risk_state_id"]==record["risk_state_id"] and meta["assets"]==tuple(record["assets"]) and
              meta["method"]==record["method"] and meta["status"]==record["status"] and
              _clock(meta["as_of"])==_clock(record["as_of"]) and _clock(meta["cutoff"])==_clock(record["cutoff"]) and
              meta["event_policy_binding"]==proof,"CALLER_STATE_AND_BANK_METADATA_MISMATCH")
        for asset in current["requested_assets"]:
            c=meta["coverage"].get(asset,{})
            _need(c.get("uid")==current["asset_uids"][asset] and c.get("identity_epoch")==current["asset_epochs"][asset],
                  "CALLER_STATE_FULL_DOMAIN_COVERAGE_MISMATCH")
    return len(fit_event["history_support"]["short0"])


def qualify_chain(plan,support,bank,*,pinned_refs,expected_content_sha256,
                  expected_code_pins,observed_code_pins,qualified_states=None):
    """Source-only continuity. Caller physical/numeric guards remain mandatory.

    Seven continuous methods need all 752 days. Broad methods have two exact
    anchor dates only and can never qualify an entire-year or continuous chain.
    No bank reader is provided while R5 execution authorization is pending.
    """
    daily=_verify_global(plan,support,bank,pinned_refs,expected_content_sha256,expected_code_pins,observed_code_pins)
    events=_event_indices(support);nodes,passed,blocked,retained=_record_index(plan,bank,events)
    bindings={};families=tuple(plan["risk_families"])
    for binding in plan["method_bindings"]:
        EventMethodBinding(**binding).validate()
        _need(binding["family"] not in bindings,"UNIQUE_FROZEN_FAMILY_BINDING_REQUIRED")
        _need(binding["producer_sha256"]==pinned_refs["model_producer"]["sha256"],"FAMILY_PRODUCER_PIN_MISMATCH")
        bindings[binding["family"]]=binding
    for node in nodes.values():
        recipe=plan["estimator_recipes"].get(node["recipe_id"])
        _need(isinstance(recipe,dict),"EXACT_NODE_FROZEN_RECIPE_REQUIRED")
        for family in node["families"]:
            b=bindings[family]
            _need(content_hash(recipe)==b["recipe_sha256"] and
                  recipe.get("method_ids",{}).get(family)==b["method"],"LITERAL_NODE_RECIPE_OR_METHOD_PIN_MISMATCH")
    _need(set(families)==set(bindings),"ALL_FROZEN_FAMILIES_MUST_REMAIN_IN_REPORT")
    result={f:dict(scope="CONTINUOUS" if f in CONTINUOUS else "TWO_ANCHORS_ONLY",continuous_chain=False,
        qualified_days=0,required_days=REQUIRED_DAILY_COUNT if f in CONTINUOUS else 2,not_applicable_days=0,
        first_input_blocker=None,qualified_anchor_dates=[],state_ids=set(),n0_prior_only_asset_day_contexts=0) for f in families}
    previous=None;previous_event=None;seen_events=set();lookup_count=0
    for item in daily:
        day=_clock(item["decision_asof"])
        _need(previous is None or day>previous,"MONOTONIC_UNIQUE_DAILY_CHAIN_REQUIRED")
        _need(item.get("future_event_date_used") is False,"FUTURE_NEXT_EVENT_LOOKUP_FORBIDDEN")
        eid=item["support_epoch_event_id"]
        _need(eid in events,"CURRENT_EVENT_METADATA_MISSING")
        current=events[eid]
        _need(_clock(current["decision_asof"])<=day,"FUTURE_EVENT_WITNESS_FORBIDDEN")
        _need(previous_event is None or _clock(current["decision_asof"])>=previous_event,"CURRENT_EVENT_CHAIN_REGRESSION_FORBIDDEN")
        if eid not in seen_events:
            _need(_clock(current["decision_asof"])==day,"CURRENT_EVENT_NOT_INTRODUCED_ON_ITS_ACTUAL_DAY")
            seen_events.add(eid)
        _need(item["dependency_local_event_ids"]==current["dependency_local_event_ids"] and
              item["dependency_local_signature_sha256"]==current["dependency_local_signature_sha256"] and
              item["structural_signature_sha256"]==current["structural_signature_sha256"] and
              item["requested_asset_count"]==len(current["requested_assets"]),"DAILY_CURRENT_EVENT_SIGNATURE_OR_FULL_DOMAIN_MISMATCH")
        for family in families:
            summary=result[family];dependency="FF48" if family=="FF48_HIERARCHICAL" else "PRIMARY"
            key=(family,item["dependency_local_event_ids"][dependency]);lookup_count+=1
            record=passed.get(key) or blocked.get(key)
            if family not in CONTINUOUS and (record is None or _clock(record["as_of"])!=day):
                summary["not_applicable_days"]+=1
                continue
            try:
                _need(record is not None,"MISSING_REQUIRED_BANK_EVENT_STATE")
                _need(key in passed,"BANK_STATE_BLOCKED_OR_FAILED:"+str(record.get("block_reason") or record.get("status")))
                fit_event=events[record["event_id"]];node=nodes[record["event_id"]]
                if family not in CONTINUOUS:
                    _need(item["decision_date"] in plan["broad_anchor_dates"],"ANCHOR_STATE_CANNOT_CARRY_TO_ANOTHER_DAY")
                n0=_qualify_record(record,family,node,current,day,fit_event,bindings[family],pinned_refs["plan"],qualified_states)
                summary["qualified_days"]+=1;summary["state_ids"].add(record["risk_state_id"])
                summary["n0_prior_only_asset_day_contexts"]+=n0
                if family not in CONTINUOUS:summary["qualified_anchor_dates"].append(item["decision_date"])
            except (ValueError,KeyError,TypeError) as error:
                if summary["first_input_blocker"] is None:
                    summary["first_input_blocker"]=dict(date=item["decision_date"],event_id=eid,
                        dependency=dependency,dependency_local_event_id=key[1],reason=str(error),
                        requested_assets=list(current["requested_assets"]))
        previous=day;previous_event=_clock(current["decision_asof"])
    for family,summary in result.items():
        summary["state_count"]=len(summary.pop("state_ids"))
        summary["continuous_chain"]=family in CONTINUOUS and summary["qualified_days"]==REQUIRED_DAILY_COUNT and summary["first_input_blocker"] is None
        if family not in CONTINUOUS and summary["qualified_days"]<2 and summary["first_input_blocker"] is None:
            summary["first_input_blocker"]=dict(reason="TAIL_CVAR_INDEPENDENT_SCENARIO_SOURCE_UNBOUND" if family=="TAIL_CVAR" else "MISSING_REQUIRED_ANCHOR_BANK_STATE",expected_anchor_dates=plan["broad_anchor_dates"])
    result["MULTI_HORIZON"]=dict(scope="UNBOUND_SOURCE",continuous_chain=False,qualified_days=0,
        first_input_blocker={"reason":"RM_3_10_20_HORIZON_SOURCE_UNBOUND"})
    return dict(schema="B_R5_RISK_CHAIN_SOURCE_QUALIFICATION_V1",research_id=plan["research_id"],
        input_refs=pinned_refs,bank_budget_accounting=dict(inherited_fit_units=INHERITED_FIT_UNITS,
            new_fit_units=bank["new_fit_units"],cumulative_fit_units=bank["cumulative_fit_units"],
            frozen_new_cap=plan["maximum_new_fit_units"],cumulative_cap=CUMULATIVE_FIT_CAP),daily_domain_count=REQUIRED_DAILY_COUNT,current_event_lookups=lookup_count,
        family_continuity=result,all_seven_continuous=all(result[f]["continuous_chain"] for f in CONTINUOUS),
        retained_blocked_or_failed=retained,full_requested_domain_preserved=True,
        bank_coverage_authority="PINNED_PRODUCER_BIND_POLICY_STATE_METADATA_ATTESTATION" if qualified_states is None else "CALLER_OWNED_STATE_METADATA_CROSS_CHECKED",
        numerical_posterior_coverage_read=False,source_only_qualification=True,physical_pin_verification_performed_by_caller=True,
        future_next_event_lookup=False,strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False,
        economic_qualification=False,real_numeric_reads=0,new_fit_units=0,account_attempts=0,test2026_rows_read=0)
