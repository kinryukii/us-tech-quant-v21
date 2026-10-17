"""Pure synthetic variant capabilities; no actual model or research inputs."""
from copy import deepcopy
from types import SimpleNamespace
import json
import pandas as pd
import pytest
from tests.research.a2.evaluation.test_frozen_a94_profile import bundle, all_bundle
from scripts.research.a2.evaluation import frozen_a94_profile as p
from scripts.research.a2.evaluation import frozen_test_authority as a
from scripts.research.a2.inference import frozen_a94_values as v


@pytest.fixture
def repair(all_bundle, monkeypatch, tmp_path):
    base = all_bundle; write = base["legacy"]["write"]
    row = base["docs"]["inventory"]["candidates"][0]
    row["candidate_id"] = row["specification"]["candidate_id"] = "RAW_s10"
    row["specification"].update(action="raw", value_model="ridge", gross="fixed", control="none")
    base["docs"]["schedule"] = p.build_random_schedule(pd.bdate_range("2026-01-02", "2026-10-08"),
        as_of=base["docs"]["plan"]["as_of_utc"], candidate_ids=[r["candidate_id"] for r in base["docs"]["inventory"]["candidates"]])
    base["freeze"](); parent = p.profile_contract(p.ALL_TASK)
    monkeypatch.setattr(p, "_REPAIR_ROOT", tmp_path)
    decision = write("repair_decision.json", {"synthetic": True})
    monkeypatch.setattr(p, "_REPAIR_POST_VERIFIED_DECISION_PIN", (decision["path"], decision["sha256"]))
    leaf = write("physical_source.json", {"synthetic": True})
    variants = {}
    for i, key in enumerate(p.REPAIR_VARIANTS):
        variants[key] = dict(n=(100,200,300,400)[i] if i < 4 else 100, cohort_count=25 if i < 4 else 24,
            excluded_manager=None if i < 4 else p._REPAIR_MANAGERS[i-4],
            members_ref=leaf, schedule_ref=leaf, ledger_ref=leaf)
    manifest = dict(schema="CONSENSUS_SENSITIVITY_SOURCE_MANIFEST_R1",task_id=p.REPAIR_TASK,variants=variants)
    plan = dict(schema="EXPOSED_2026_REPAIR_AND_CONSENSUS_EVALUATION_PLAN_R1",task_id=p.REPAIR_TASK,
        fit_count_in_frozen_inference=0,evaluation_start="2026-01-02",evaluation_end="2026-10-08",
        window_count=101,expected_raw_accounts=2929,
        original_inputs={k+"_ref":parent["metadata_refs"][k] for k in ("plan","inventory","schedule")},
        variants=[dict(pool_variant_id=k,list_source_entry=deepcopy(e),**{j:e[j] for j in ("n","cohort_count","excluded_manager")}) for k,e in variants.items()])
    inventory = dict(task_id=p.REPAIR_TASK,parent_inventory_ref=parent["metadata_refs"]["inventory"],candidates=[deepcopy(row)])
    runtime = dict(schema="A_REPAIR_COMMON_MATH_OWNER_CONTRACT_R1",task_id=p.REPAIR_TASK,
        schedule_ref=parent["metadata_refs"]["schedule"],cash_decision_ref=decision,
        raw_specification=deepcopy(row["specification"]),owners=[leaf])
    proof = dict(universe_variant="CONSENSUS_SENSITIVITY",pool_variant_id="TOP100",n=100,cohort_count=25,
        excluded_manager=None,variant_list_refs={k:leaf for k in ("members_ref","schedule_ref","ledger_ref")},
        origin="SYNTHETIC_PINNED_ORIGIN",physical_pool_ref=leaf,source_ref=base["bound"]["source_refs"]["action_inputs"],
        feature_order_sha256=v.values.digest(parent["raw_selector_binding"]["ordered_32_features"]),
        sessions={d:{"rows":100} for d in parent["schedule"]["common_sessions"]})
    source = dict(schema="CONSENSUS_VARIANT_INPUT_BUNDLE_R1",task_id=p.REPAIR_TASK,pool_variant_id="TOP100",
        universe_variant="CONSENSUS_SENSITIVITY",selection_rule="MANAGER_COUNT_WEIGHT_SUM",
        original_window_schedule_ref=parent["metadata_refs"]["schedule"],list_source_entry=deepcopy(variants["TOP100"]),
        n=100,cohort_count=25,excluded_manager=None,execution_admission_inherited=False,
        physical_pool_ref=leaf,full_pit32_pool=proof)
    catalog = dict(schema="A_REPAIR_RAW_VARIANT_SOURCE_CATALOG_R1",task_id=p.REPAIR_TASK,
        variant_order=list(p.REPAIR_VARIANTS),same_original_activation_clock=True,
        original_window_schedule_ref=parent["metadata_refs"]["schedule"],variants={k:dict(
            status="READY" if k=="TOP100" else "PENDING",reason="synthetic missing source",
            **{j:e[j] for j in ("n","cohort_count","excluded_manager")}) for k,e in variants.items()})
    docs = dict(plan=plan,inventory=inventory,common_runtime=runtime,source_manifest=manifest,source_catalog=catalog,source_bundle=source)
    refs = {}
    def freeze():
        refs["source_manifest"] = write("repair_manifest.json",manifest)
        plan["consensus_list_manifest_ref"] = refs["source_manifest"]
        refs["plan"] = write("repair_plan.json",plan)
        refs["inventory"] = write("repair_inventory.json",inventory)
        runtime.update(plan_ref=refs["plan"],candidate_inventory_ref=refs["inventory"])
        refs["common_runtime"] = write("repair_runtime.json",runtime)
        source.update(plan_ref=refs["plan"],source_manifest_ref=refs["source_manifest"],universe_source_ref=refs["source_manifest"])
        proof.update(source_manifest_ref=refs["source_manifest"],universe_source_ref=refs["source_manifest"])
        support = dict(proof, origin="CONSENSUS_SENSITIVITY_ASOF_HOLDING_VALUE_SUPPORT",
            role="OFFPOOL_HOLDING_VALUE_CONTINUITY_ONLY", domain_policy="CURRENT_POOL_UNION_PREVIOUSLY_EFFECTIVE_MEMBERS_ASOF",
            no_future_first_membership=True, no_new_buy_eligibility=True, daily_top100_sessions=deepcopy(proof["sessions"]))
        source["value_holding_support"] = support
        source["physical_value_support_ref"] = write("support_frame.json", {"synthetic":"support"})
        source["value_holding_support_manifest_ref"] = write("support_manifest.json", dict(task_id=p.REPAIR_TASK,
            pool_variant_id=source["pool_variant_id"], value_holding_support=support,
            physical_daily_top100_ref=source["physical_pool_ref"],physical_support_ref=source["physical_value_support_ref"]))
        refs["source_bundle"] = write("repair_bundle.json",source)
        catalog.update(plan_ref=refs["plan"],source_manifest_ref=refs["source_manifest"])
        catalog["variants"]["TOP100"]["source_bundle_ref"] = refs["source_bundle"]
        refs["source_catalog"] = write("repair_catalog.json",catalog)
        monkeypatch.setattr(p,"_REPAIR_PINS",{k:(r["path"],r["sha256"]) for k,r in refs.items() if k!="source_bundle"})
    freeze()
    contract=p.profile_contract(p.REPAIR_TASK,pool_variant_id="TOP100")
    bound=deepcopy(base["bound"]);q=deepcopy(base["qualification"])
    shared=dict(task_id=p.REPAIR_TASK,pool_variant_id="TOP100",source_catalog_ref=refs["source_catalog"],
        source_bundle_ref=refs["source_bundle"],common_runtime_contract_ref=refs["common_runtime"])
    bound.update(shared,plan_ref=refs["plan"],candidate_manifest_ref=refs["inventory"],candidate_bindings=contract["candidate_bindings"],
        state_refs=contract["state_refs"],allowed_path_ids=["RAW_s10"],
        schedule_ref=parent["metadata_refs"]["schedule"],windows=parent["schedule"]["windows"])
    q.update(shared,raw_selector_binding=contract["raw_selector_binding"],full_pit32_pool=proof,
        full_pit32_value_support=contract["full_pit32_value_support"],
        candidate_source_qualification={"RAW_s10":dict(required_action_roles=[],source_ref=bound["source_refs"]["action_inputs"],status="QUALIFIED")})
    q["groups"]["action_inputs"]=True
    authority=dict(schema="A_2026_DESCRIPTIVE_AUTHORITY_REF_R1",window_id="MAIN",**shared)
    def persist():
        bound["source_qualification_ref"]=write("repair_qualification.json",q)
        authority["admission_ref"]=write("repair_admission.json",bound)
        return authority
    persist()
    return dict(base=base,parent=parent,docs=docs,refs=refs,contract=contract,freeze=freeze,persist=persist,
        bound=bound,q=q,authority=authority,write=write)


def test_raw_only_capability_and_unchanged_old_contracts(repair):
    r=repair;c=p.profile_contract(p.REPAIR_TASK,pool_variant_id="TOP100")
    assert c["candidate_bindings"]==[r["parent"]["candidate_bindings"][0]]
    assert list(c["state_refs"])==["old_value:ridge"]
    assert c["schedule"]==r["parent"]["schedule"]
    assert p.profile_contract(p.ALL_TASK)==r["parent"]
    assert p.profile_contract(p.TASK)==r["base"]["legacy"]["contract"]
    auth=a.load_descriptive_authority(r["authority"])
    assert auth.allowed_path_ids==auth.source_ready_policy_ids==("RAW_s10",)
    auth=a.validate_descriptive_policy(auth,[c["candidate_bindings"][0]["specification"]])
    loader=v.FrozenStateLoader(auth)
    assert loader._check()==c
    assert p.required_action_roles("RAW_s10",authority=auth)==()
    with pytest.raises(ValueError,match="UNKNOWN_OR_UNBOUND"):
        loader.load("old_value:hgb")


@pytest.mark.parametrize("variant",[None,"TOP500","LOO_unknown_TOP100"])
def test_unfrozen_variants_rejected(repair,variant):
    with pytest.raises(ValueError,match="EXACT_POOL_VARIANT"):
        p.profile_contract(p.REPAIR_TASK,pool_variant_id=variant)


@pytest.mark.parametrize("variant",p.REPAIR_VARIANTS[1:])
def test_each_unready_frozen_arm_rejected(repair,variant):
    with pytest.raises(ValueError,match="SOURCE_NOT_READY"):
        p.profile_contract(p.REPAIR_TASK,pool_variant_id=variant)


@pytest.mark.parametrize("where,field,value",[
    ("plan","evaluation_end","2027-01-01"),("plan","fit_count_in_frozen_inference",1),
    ("plan","window_count",100),("source_catalog","same_original_activation_clock",False),
    ("source_bundle","pool_variant_id","TOP200"),("source_bundle","n",200),
    ("source_bundle","excluded_manager","akre"),("source_bundle","execution_admission_inherited",True),
])
def test_changed_scope_source_clock_and_legacy_seal_rejected(repair,where,field,value):
    repair["docs"][where][field]=value;repair["freeze"]()
    with pytest.raises(ValueError):p.profile_contract(p.REPAIR_TASK,pool_variant_id="TOP100")


@pytest.mark.parametrize("mutation",["cost","model","inventory","missing_arm","extra_arm","same_vote_clock","proof","proof_calendar"])
def test_frozen_semantic_rejection_even_when_metadata_rehashed(repair,mutation):
    d=repair["docs"]
    if mutation=="cost":d["common_runtime"]["raw_specification"]["execution_friction"]["one_way_bps"]=5
    if mutation=="model":d["inventory"]["candidates"][0]["specification"]["value_model"]="hgb"
    if mutation=="inventory":d["inventory"]["candidates"].append(deepcopy(d["inventory"]["candidates"][0]))
    if mutation=="missing_arm":d["source_catalog"]["variant_order"].pop()
    if mutation=="extra_arm":d["source_manifest"]["variants"]["TOP500"]={}
    if mutation=="same_vote_clock":d["plan"]["variants"][4]["list_source_entry"]["schedule_ref"]={"path":"other","sha256":"0"*64}
    if mutation=="proof":d["source_bundle"]["full_pit32_pool"]["cohort_count"]=24
    if mutation=="proof_calendar":d["source_bundle"]["full_pit32_pool"]["sessions"]["2027-01-04"]={"rows":100}
    repair["freeze"]()
    with pytest.raises(ValueError):p.profile_contract(p.REPAIR_TASK,pool_variant_id="TOP100")


@pytest.mark.parametrize("where,field,value",[
    ("authority","pool_variant_id","TOP200"),("bound","pool_variant_id","TOP200"),
    ("authority","source_catalog_ref",{}),("authority","source_bundle_ref",{}),("authority","common_runtime_contract_ref",{}),
    ("q","pool_variant_id","TOP200"),("q","source_catalog_ref",{}),("bound","source_bundle_ref",{}),
    ("q","common_runtime_contract_ref",{}),("bound","initial_cash_usd",3001),
    ("bound","as_of","2026-10-08T01:00:00Z"),
])
def test_account_and_source_splices_rejected_before_consumption(repair,where,field,value):
    repair[where][field]=value;repair["persist"]()
    with pytest.raises(ValueError):a.load_descriptive_authority(repair["authority"])


def test_full_proof_mutation_rejected_at_both_admission_and_pool_binding(repair):
    r=repair
    auth=a.validate_descriptive_policy(a.load_descriptive_authority(r["authority"]),[r["contract"]["candidate_bindings"][0]["specification"]])
    loader=v.FrozenStateLoader(auth)
    features=r["contract"]["raw_selector_binding"]["ordered_32_features"]
    frame=pd.DataFrame({k:[.01] for k in features})
    frame["signal_date"]=pd.to_datetime(["2026-01-02"]);frame["ticker"]="SYN";frame["security_id"]="SID"
    frame["feature_available"]=True;frame["input_present"]=True;frame["feature_source"]="synthetic"
    r["q"]["full_pit32_pool"]=deepcopy(r["q"]["full_pit32_pool"])
    r["q"]["full_pit32_pool"]["pool_variant_id"]="TOP200";r["persist"]()
    with pytest.raises(ValueError,match="FULL_POOL_PROOF"):
        a.load_descriptive_authority(r["authority"])
    # Existing sealed handles also refuse mutable source qualification bytes.
    with pytest.raises(ValueError,match="SHA_CHANGED"):
        v.bind_pool(loader,frame)


def test_source_catalog_mutation_not_resealed(repair):
    from pathlib import Path
    Path(repair["refs"]["source_catalog"]["path"]).write_text("{}",encoding="utf-8")
    with pytest.raises(ValueError,match="SHA_CHANGED"):
        p.profile_contract(p.REPAIR_TASK,pool_variant_id="TOP100")


def test_random_window_has_original_dates_and_no_source_alias(repair):
    repair["authority"]["window_id"]="RANDOM_050"
    auth=a.load_descriptive_authority(repair["authority"])
    w=next(w for w in repair["parent"]["schedule"]["windows"] if w["window_id"]=="RANDOM_050")
    assert auth.start==pd.Timestamp(w["start"]) and auth.end==pd.Timestamp(w["end"])
    assert auth.runtime_policy_ids==()
    assert json.loads(auth.provenance_json)["pool_variant_id"]=="TOP100"


def test_old_task_rejects_new_variant_argument(repair):
    with pytest.raises(ValueError,match="VARIANT_ON_OLD_TASK"):
        p.profile_contract(p.ALL_TASK,pool_variant_id="TOP100")


@pytest.mark.parametrize("mutation",[None,"old_task","old_scope","old_inventory","future_asof","terminal_terms","model_permission"])
def test_new_cash_decision_preserves_exact_scope_and_terminal_terms(repair,monkeypatch,mutation):
    r=repair;c=r["contract"];terminal={"ticker":"SYN","settlement":None,"cash_per_old_share":16.0}
    decision=dict(schema="A94_POST_VERIFIED_CASH_TERMINAL_SOURCE_DECISION_R1",task_id=p.REPAIR_TASK,
        status="HUMAN_AUTHORIZED_NOT_SOURCE_OR_RUNTIME_ADMISSION",
        candidate_scope="EXACT_PINNED_RAW_S10_CONSENSUS_SENSITIVITY_FRESH_RANDOM_RESEARCH",
        clock_role="POST_VERIFIED_ACCOUNTING_ONLY",original_plan_ref=c["metadata_refs"]["plan"],
        candidate_manifest_ref=c["metadata_refs"]["inventory"],economic_as_of_utc=c["as_of_utc"],
        separate_A6_permission_inherited=False,authorized_terminal_terms=[terminal],
        prohibitions={k:False for k in ("model_or_H5_input_authority","new_fit","parameter_or_rule_change",
            "strategy_selection","production_qualified","strict_PIT_promotion_eligible","broker_orders",
            "source_or_account_admitted_by_decision_alone","economic_window_extended")})
    if mutation=="old_task":decision["task_id"]=p.ALL_TASK
    if mutation=="old_scope":decision["candidate_scope"]="EXACT_PINNED_FULL_A_INVENTORY_FRESH_RANDOM_RESEARCH"
    if mutation=="old_inventory":decision["candidate_manifest_ref"]=r["parent"]["metadata_refs"]["inventory"]
    if mutation=="future_asof":decision["economic_as_of_utc"]="2026-10-10T03:46:22Z"
    if mutation=="terminal_terms":decision["authorized_terminal_terms"]=[dict(terminal,cash_per_old_share=17.0)]
    if mutation=="model_permission":decision["prohibitions"]["model_or_H5_input_authority"]=True
    ref=r["write"]("new_cash_decision.json",decision)
    monkeypatch.setattr(p,"_REPAIR_POST_VERIFIED_DECISION_PIN",(ref["path"],ref["sha256"]))
    bound=dict(post_verified_accounting_decision_ref=ref,research_terminal_reconstruction=dict(task_id=p.REPAIR_TASK,
        authorization_ref=ref,events=[dict(terminal_terms=terminal)]))
    if mutation is None:assert p._accounting_decision(bound,c)==ref
    else:
        with pytest.raises(ValueError):p._accounting_decision(bound,c)


def test_missing_value_support_proof_fails_admission(repair):
    repair["q"].pop("full_pit32_value_support");repair["persist"]()
    with pytest.raises(ValueError,match="VALUE_SUPPORT_PROOF"):
        a.load_descriptive_authority(repair["authority"])

@pytest.mark.parametrize("field,value", [("pool_variant_id","TOP200"),("n",200),("no_new_buy_eligibility",False),("origin","CONSENSUS100_ASOF_HOLDING_VALUE_SUPPORT")])
def test_repaired_support_exact_scope_not_optional(repair,field,value):
    repair["q"]["full_pit32_value_support"]=deepcopy(repair["q"]["full_pit32_value_support"])
    repair["q"]["full_pit32_value_support"][field]=value;repair["persist"]()
    with pytest.raises(ValueError,match="VALUE_SUPPORT_PROOF"):
        a.load_descriptive_authority(repair["authority"])
