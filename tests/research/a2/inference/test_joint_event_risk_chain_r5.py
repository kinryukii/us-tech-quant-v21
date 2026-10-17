"""Source-only synthetic banks; no model/data loader, numerical state or account."""
import copy
import pandas as pd
import pytest
from scripts.research.a2.inference.joint_event_risk_chain_r5 import qualify_chain,CONTINUOUS,ChainQualificationBlocked,RESEARCH_ID
from scripts.research.a2.risk.event_risk_contract_r5 import structural_identity,FAMILIES
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash
from scripts.research.a2.risk.shared_risk_engine_r2 import COORDINATE
from scripts.research.a2.inference.joint_event_policy_r5 import PARENT_FAMILIES


def fixture():
    days=pd.bdate_range("2023-01-02",periods=752,tz="UTC")+pd.Timedelta(hours=21)
    starts={round(i*751/54) for i in range(55)}
    refs={name:dict(path="D:/synthetic/R5/"+name+".json",sha256=chr(97+i)*64)
          for i,name in enumerate(("plan","support","bank","source_authority","model_producer","execution_producer"))}
    refs["execution_producer"]["sha256"]="f"*64
    refs["model_producer"]["path"]="D:/synthetic/code/model.py"
    refs["execution_producer"]["path"]="D:/synthetic/code/execution.py"
    codes={refs[k]["path"]:refs[k]["sha256"] for k in ("model_producer","execution_producer")}
    events=[];daily=[];primary=[];current=None;primary_local=None;current_ff=0
    for i,day in enumerate(days):
        if i in starts or i==10:
            if i in starts:
                epoch="EPOCH_"+str(i);current_ff=0
            else:current_ff+=1
            uids={"A":"UID_A","B":"UID_B"};epochs={a:epoch+"_"+a for a in uids}
            coords={a:{"class_coordinate_status":"EXACT_FROZEN_INTERVAL_METADATA_DECLARATION","cusip":"SYNTHETIC"+a} for a in uids}
            signature=dict(ordered_assets=["A","B"],asset_uids=uids,asset_epochs=epochs,blocked_assets={},
                source_identity={"source_inputs_sha256":"c"*64},security_coordinates=coords,
                ff48_qualified_source_support={a:{"group":current_ff+1} for a in uids},feature_source_support={a:["SYNTHETIC"] for a in uids})
            ps={k:v for k,v in signature.items() if k!="ff48_qualified_source_support"}
            psha=content_hash(ps);fsha=content_hash(signature)
            if i in starts:primary_local=content_hash({"primary":i,"sha256":psha})
            locals_=dict(PRIMARY=primary_local,QQQ=content_hash(ps),FF48=content_hash({"ff48":i,"sha256":fsha}))
            current=dict(event_index=len(events),event_id=content_hash({"event":i}),decision_date=day.date().isoformat(),
                decision_asof=day.isoformat(),fit_history_cutoff=(day-pd.Timedelta(days=1)).isoformat(),
                complete_structural_signature=signature,structural_signature_sha256=fsha,
                dependency_local_event_ids=locals_,dependency_local_signature_sha256=dict(PRIMARY=psha,QQQ=content_hash(ps),FF48=fsha),
                requested_assets=["A","B"],asset_uids=uids,asset_epochs=epochs,security_coordinates=coords,
                history_support=dict(nominal_n={"A":252,"B":0},short0=["B"],current_identity_blockers={},source_metadata_blockers={}))
            events.append(current)
            if i in starts:primary.append(current)
        daily.append(dict(decision_date=day.date().isoformat(),decision_asof=day.isoformat(),support_epoch_event_id=current["event_id"],
            dependency_local_event_ids=current["dependency_local_event_ids"],dependency_local_signature_sha256=current["dependency_local_signature_sha256"],
            structural_signature_sha256=current["structural_signature_sha256"],requested_asset_count=2,future_event_date_used=False))
    anchors={next(e["event_id"] for e in primary if pd.Timestamp(e["decision_date"]).year==y) for y in (2023,2025)}
    recipe=dict(method_ids={f:"R5::"+f+"::SYNTHETIC_CHILD" for f in FAMILIES},source_only_synthetic_fixture=True)
    bindings=[]
    for family in FAMILIES:
        parent=next(k for k,v in PARENT_FAMILIES.items() if v==family)
        bindings.append(dict(parent_risk=parent,family=family,method="R5::"+family+"::SYNTHETIC_CHILD",
            representation="EVENT_HIERARCHICAL_PRIOR" if family.startswith("SHR_") else "EVENT_CLASSICAL_WITH_PRIOR_COMPLETION",
            recipe_sha256=content_hash(recipe),producer_sha256=refs["model_producer"]["sha256"],availability="READY"))
    nodes=[]
    for e in primary:
        families=list(FAMILIES) if e["event_id"] in anchors else list(CONTINUOUS)
        nodes.append(dict(event_id=e["event_id"],dependency="PRIMARY",recipe_id="SYNTHETIC_RECIPE",families=families,
            family_dependencies={f:"FF48" if f=="FF48_HIERARCHICAL" else "PRIMARY" for f in families}))
    plan=dict(schema="B_R5_FINITE_EVENT_RISK_PLAN_V1",research_id=RESEARCH_ID,support_ref=refs["support"],
        source_authority_ref=refs["source_authority"],model_producer_ref=refs["model_producer"],continuous_families=list(CONTINUOUS),
        maximum_new_fit_units=1056,prior_cumulative_fit_units=3027,cumulative_fit_cap=4096,
        risk_families=list(FAMILIES),method_bindings=bindings,nodes=nodes,estimator_recipes={"SYNTHETIC_RECIPE":recipe},broad_anchor_dates=[e["decision_date"] for e in primary if e["event_id"] in anchors])
    support=dict(schema="B_R5_EVENT_RISK_METADATA_SUPPORT_V1",research_id=plan["research_id"],events=events,
        daily_support_chain=daily,decision_session_count=752)
    records=[];failures=[]
    for node in nodes:
        e=next(e for e in events if e["event_id"]==node["event_id"])
        for family in node["families"]:
            dep=node["family_dependencies"][family]
            binding=next(b for b in bindings if b["family"]==family)
            source=dict(dependency=dep,dependency_local_event_id=e["dependency_local_event_ids"][dep],
                dependency_local_signature_sha256=e["dependency_local_signature_sha256"][dep],source_pins={"scientific_contract":refs["plan"]["sha256"],"primary":"c"*64})
            if dep=="FF48":source.update(industry_source={"id":"SYNTHETIC_FF48","version":"V1","sha256":"d"*64});source["source_pins"]["FF48"]="d"*64
            sid=structural_identity(assets=("A","B"),uids=e["asset_uids"],epochs=e["asset_epochs"],security_coordinate=COORDINATE,source_support_identity=source)
            proof=dict(parent_risk=binding["parent_risk"],representation=binding["representation"],recipe_sha256=binding["recipe_sha256"],
                model_producer_sha256=binding["producer_sha256"],structural_identity=sid,source_support_identity_sha256=content_hash(source),
                asset_uid_epoch_sha256=content_hash(dict(uids=e["asset_uids"],epochs=e["asset_epochs"])))
            r=dict(event_id=e["event_id"],family=family,dependency=dep,dependency_local_event_id=source["dependency_local_event_id"],
                recipe_id=node["recipe_id"],method=binding["method"],as_of=e["decision_asof"],cutoff=e["fit_history_cutoff"],
                assets=["A","B"],asset_uids=e["asset_uids"],asset_epochs=e["asset_epochs"],status="PASS_FROZEN_HISTORY_MECHANISM",finite_check=True,
                risk_state_id=content_hash({"state":family,"event":e["event_id"]}),source_support_identity=source,event_policy_binding=proof,
                source_receipt=dict(return_coordinate=COORDINATE,status="FROZEN_HISTORY_MECHANISM_SOURCE_BOUND",mechanism=True,synthetic=False,
                    scientific_contract_sha256=refs["plan"]["sha256"],identity_epoch="R5_CURRENT_POOL_OBSERVED_UIDS:"+content_hash(e["asset_epochs"]),
                    strict_PIT_promotion_eligible=False,quote_qualified=False,historical_authority_status="UNKNOWN"))
            if family=="TAIL_CVAR":r.update(status="BLOCKED",finite_check=False,block_reason="SCENARIO_SOURCE_UNBOUND");failures.append(r)
            else:records.append(r)
    bank=dict(schema="B_R5_EVENT_RISK_BANK_V1",research_id=plan["research_id"],method_bindings=bindings,states=records,blocked_or_failed=failures,
        plan_ref=refs["plan"],event_support_ref=refs["support"],source_authority_ref=refs["source_authority"],model_producer_ref=refs["model_producer"],
        execution_producer_ref=refs["execution_producer"],new_fit_units=100,cumulative_fit_units=3127,future_next_event_lookup_allowed=False,strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False)
    return plan,support,bank,refs,codes


def call(plan,support,bank,refs,codes,**kwargs):
    return qualify_chain(plan,support,bank,pinned_refs=refs,
        expected_content_sha256={k:content_hash(v) for k,v in (("plan",plan),("support",support),("bank",bank))},
        expected_code_pins=codes,observed_code_pins=codes,**kwargs)


def test_seven_complete_752_chains_anchor_scope_n0_and_failures_preserved():
    plan,support,bank,refs,codes=fixture()
    result=call(plan,support,bank,refs,codes)
    assert result["all_seven_continuous"] and result["daily_domain_count"]==752
    for family in CONTINUOUS:
        r=result["family_continuity"][family]
        assert r["continuous_chain"] and r["qualified_days"]==752 and r["state_count"]==55
        assert r["n0_prior_only_asset_day_contexts"]==752
    for family in set(FAMILIES)-set(CONTINUOUS)-{"TAIL_CVAR"}:
        r=result["family_continuity"][family]
        assert not r["continuous_chain"] and r["qualified_days"]==2 and r["not_applicable_days"]==750
    assert len(result["retained_blocked_or_failed"])==2
    assert "UNBOUND" in result["family_continuity"]["TAIL_CVAR"]["first_input_blocker"]["reason"]
    assert "RM_3_10_20" in result["family_continuity"]["MULTI_HORIZON"]["first_input_blocker"]["reason"]
    assert result["real_numeric_reads"]==result["new_fit_units"]==result["account_attempts"]==0
    assert not result["economic_qualification"] and not result["strict_PIT_promotion_eligible"]


@pytest.mark.parametrize("defect",["uid","epoch","source","coordinate","cutoff","recipe"])
def test_bank_identity_source_recipe_mutation_blocks_full_domain(defect):
    plan,support,bank,refs,codes=fixture();record=next(r for r in bank["states"] if r["family"]=="LW")
    if defect=="uid":record["asset_uids"]={**record["asset_uids"],"B":"OTHER_UID"}
    elif defect=="epoch":record["asset_epochs"]={**record["asset_epochs"],"B":"OTHER_EPOCH"}
    elif defect=="source":record["source_support_identity"]={**record["source_support_identity"],"dependency_local_signature_sha256":"f"*64}
    elif defect=="coordinate":record["source_receipt"]["return_coordinate"]="ADJUSTED_PRICE"
    elif defect=="cutoff":record["cutoff"]=record["as_of"]
    else:record["event_policy_binding"]={**record["event_policy_binding"],"recipe_sha256":"f"*64}
    result=call(plan,support,bank,refs,codes)
    first=result["family_continuity"]["LW"]["first_input_blocker"]
    assert first and first["requested_assets"]==["A","B"]
    assert not result["family_continuity"]["LW"]["continuous_chain"]
    assert result["family_continuity"]["SHR_HP"]["continuous_chain"]


def test_missing_required_event_does_not_trim_day_or_asset_domain():
    plan,support,bank,refs,codes=fixture()
    bank["states"]=[r for r in bank["states"] if not (r["family"]=="LW" and r["event_id"]==plan["nodes"][1]["event_id"])]
    result=call(plan,support,bank,refs,codes)
    r=result["family_continuity"]["LW"]
    assert not r["continuous_chain"] and r["first_input_blocker"]["reason"]=="MISSING_REQUIRED_BANK_EVENT_STATE"
    assert result["daily_domain_count"]==752 and r["required_days"]==752


def test_ff_change_keeps_primary_chain_and_cannot_carry_anchor():
    plan,support,bank,refs,codes=fixture()
    # Event10 changes FF48 only, so there is no new PRIMARY fit or bank record.
    a,b=support["events"][:2]
    assert a["dependency_local_event_ids"]["PRIMARY"]==b["dependency_local_event_ids"]["PRIMARY"]
    assert a["dependency_local_event_ids"]["FF48"]!=b["dependency_local_event_ids"]["FF48"]
    result=call(plan,support,bank,refs,codes)
    assert result["all_seven_continuous"]
    ff=result["family_continuity"]["FF48_HIERARCHICAL"]
    assert not ff["continuous_chain"] and ff["qualified_days"]==2
    assert ff["qualified_anchor_dates"]==plan["broad_anchor_dates"]


@pytest.mark.parametrize("defect",["2026","future_nextdate","future_witness","codepin","physicalref","contentpin"])
def test_future_or_unpinned_inputs_refused(defect):
    plan,support,bank,refs,codes=fixture()
    if defect=="2026":support["daily_support_chain"][-1]["decision_asof"]="2026-01-01T21:00:00Z"
    elif defect=="future_nextdate":support["daily_support_chain"][0]["future_event_date_used"]=True
    elif defect=="future_witness":support["daily_support_chain"][0]["support_epoch_event_id"]=support["events"][-1]["event_id"]
    elif defect=="codepin":codes={**codes,refs["execution_producer"]["path"]:"e"*64}
    elif defect=="physicalref":bank["plan_ref"]={**bank["plan_ref"],"sha256":"e"*64}
    else:
        expected={k:content_hash(v) for k,v in (("plan",plan),("support",support),("bank",bank))}
        bank["states"][0]["assets"]=["A"]
        with pytest.raises(ValueError,match="FROZEN_METADATA_CONTENT_CHANGED"):
            qualify_chain(plan,support,bank,pinned_refs=refs,expected_content_sha256=expected,
                expected_code_pins=codes,observed_code_pins=codes)
        return
    with pytest.raises(ValueError):call(plan,support,bank,refs,codes)


def test_optional_caller_state_whitelist_never_accesses_covariance_or_predictions():
    plan,support,bank,refs,codes=fixture()
    class MetadataOnly:
        def __init__(self,r):self.r=r
        def __getattr__(self,key):
            if key in {"covariance","sigma","model_outputs","NAV"}:raise AssertionError("numerical field read")
            if key=="coverage":return {a:dict(uid=self.r["asset_uids"][a],identity_epoch=self.r["asset_epochs"][a],nominal_n=0 if a=="B" else 252,n0_prior_only=a=="B") for a in self.r["assets"]}
            if key=="notes":return {"event_policy_binding":self.r["event_policy_binding"]}
            return self.r[key]
    states={r["risk_state_id"]:MetadataOnly(r) for r in bank["states"]}
    result=call(plan,support,bank,refs,codes,qualified_states=states)
    assert result["all_seven_continuous"] and not result["numerical_posterior_coverage_read"]
    assert result["bank_coverage_authority"]=="CALLER_OWNED_STATE_METADATA_CROSS_CHECKED"


def test_literal_recipe_mutation_cannot_be_hidden_by_refreshing_plan_content_pin():
    plan,support,bank,refs,codes=fixture()
    plan["estimator_recipes"]["SYNTHETIC_RECIPE"]["source_only_synthetic_fixture"]=False
    with pytest.raises(ValueError,match="LITERAL_NODE_RECIPE_OR_METHOD_PIN_MISMATCH"):
        call(plan,support,bank,refs,codes)


@pytest.mark.parametrize("defect",["foreign_identity","over_new_cap","over_cumulative_cap","inconsistent_total","bool_count","missing_total"])
def test_exact_r5_identity_and_nonrefundable_bank_budget(defect):
    plan,support,bank,refs,codes=fixture()
    if defect=="foreign_identity":
        for value in (plan,support,bank):value["research_id"]="SAME_ROSTER_FOREIGN_RESEARCH"
    elif defect=="over_new_cap":bank.update(new_fit_units=1057,cumulative_fit_units=4084)
    elif defect=="over_cumulative_cap":bank.update(new_fit_units=1070,cumulative_fit_units=4097)
    elif defect=="inconsistent_total":bank["cumulative_fit_units"]+=1
    elif defect=="bool_count":bank["new_fit_units"]=True
    else:bank.pop("cumulative_fit_units")
    with pytest.raises(ValueError,match="EXACT_CURRENT_R5_RESEARCH_IDENTITY_REQUIRED|BANK_NONREFUNDABLE_BUDGET_ACCOUNTING_MISMATCH"):
        call(plan,support,bank,refs,codes)
