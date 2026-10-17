"""No research data readers; finite catalogue/friction admission contract only."""
import pytest
from scripts.research.a2.evaluation.joint_continuation import continuation_roles,friction,PRIMARY_BPS,SCENARIOS
from scripts.research.a2.evaluation import joint_method_accounts as methods

def test_new_cost_aware_role_has_matched_full_rebalance_control():
    roles=continuation_roles()
    cost=roles["M090"];control=roles["MV_FULL_REBALANCE_CONTROL"]
    assert cost["rho"]==control["rho"]==1.
    assert {k:v for k,v in cost.items() if k!="allocation"}=={k:v for k,v in control.items() if k!="allocation"}
    assert cost["allocation"]=="cost_aware" and control["allocation"]=="mean_variance"

def test_failed_risk_roles_remain_excluded_and_aliases_have_one_account():
    roles=continuation_roles()
    assert len(roles)==42 and all(p in roles for p in methods.CONTROLS)
    assert not {"M052","M058","M061","M064","M066","M098"}&set(roles)
    assert methods.ANCHOR in roles
    assert not set("M%03d"%i for i in methods.ALIASES if i!=90)&set(roles)

@pytest.mark.parametrize("bps",[-1,1,15,10000])
def test_friction_not_an_open_parameter_search(bps):
    with pytest.raises(ValueError,match="UNREGISTERED"):friction(bps)

def test_scenarios_have_explicit_hypothetical_authority_and_zero_broker_fee():
    assert PRIMARY_BPS==10 and SCENARIOS==(5,10,20)
    for bps in (0,*SCENARIOS):
        value=friction(bps)
        assert value["one_way_bps"]==bps and value["fee_bps"]==0
        assert value["authority"]=="HYPOTHETICAL_RESEARCH_SCENARIO"
        assert value["benchmark"]=="NEXT_RAW_OPEN"


# CASH_REVISION_SYNTHETIC_BOUNDARIES: all inputs below are fictional.
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import joblib
import numpy as np
import pandas as pd
from scripts.research.a2.evaluation import joint_continuation as continuation
from scripts.research.a2.data import joint_cash_bindings as cash_binder


def _synthetic_fact():
    return dict(id="AAA_FAKE_2023-01-26",issuer="Fictional Alpha Inc.",
        listing_identity="NYSE:AAA",source_url="https://issuer.example/fake-cash",
        cash_per_common_share=.12,currency="USD",currency_basis="INFERRED_USD_CONTEXT",
        cash_is_gross_announced_amount=True,record_date="2023-01-27",pay_date="2023-03-03",
        publication_date="2022-12-01",candidate_ex_date="2023-01-26",
        availability_bound={"available_at":"2022-12-02T23:59:59Z"})


@pytest.mark.parametrize("listing,venue,ticker",[
    (" NYSE : AAA ","NYSE","AAA"),
    (" NASDAQ : AAA ","NASDAQ","AAA"),
    ("NYSE American: AAA","NYSE_AMERICAN","AAA"),
])
def test_cash_normalizer_spaces_preserve_listing_venue_and_source(listing,venue,ticker):
    payload=_synthetic_fact();payload["listing_identity"]=listing
    before=copy.deepcopy(payload);original={"path":"FAKE_ONLY/source.json","sha256":"a"*64}
    value=continuation.normalized_cash_fact(payload,original)
    assert (value["listed_exchange"],value["ticker"])==(venue,ticker)
    assert value["original_source_projection"]==original and payload==before
    assert value["cash_per_raw_ex_pretrade_common_share"]==.12


@pytest.mark.parametrize("basis,expected",[
    ("EXPLICIT_USD","EXPLICIT_USD"),("INFERRED_USD_CONTEXT","INFERRED_USD"),
    ("Inferred from US issuer, US-listed ordinary common-stock context and dollar-denominated announcement; original text uses dollar sign, not an explicit ISO USD token.","INFERRED_USD"),
    ("Inferred from US issuer/listing/common-stock context and dollar-denominated announcement; original uses dollar sign, not explicit ISO USD.","INFERRED_USD"),
])
def test_cash_normalizer_only_frozen_currency_prose_is_admitted(basis,expected):
    payload=_synthetic_fact();payload["currency_basis"]=basis
    value=continuation.normalized_cash_fact(payload,{"path":"FAKE_ONLY/source.json","sha256":"a"*64})
    assert value["currency_confidence"]==expected


@pytest.mark.parametrize("basis",[None,"UNKNOWN","US dollars probably", "INFERRED_USD_CONTEXT "])
def test_cash_normalizer_unknown_currency_basis_is_not_upgraded(basis):
    payload=_synthetic_fact();payload["currency_basis"]=basis
    with pytest.raises(ValueError,match="UNCONFIRMED_USD"):
        continuation.normalized_cash_fact(payload,{})


@pytest.mark.parametrize("gross",[False,None,1,"true"])
def test_cash_normalizer_unconfirmed_gross_unit_is_not_upgraded(gross):
    payload=_synthetic_fact();payload["cash_is_gross_announced_amount"]=gross
    with pytest.raises(ValueError,match="UNCONFIRMED_GROSS"):
        continuation.normalized_cash_fact(payload,{})


def test_cash_alias_requires_explicit_continuity_proof_and_hash(tmp_path):
    value=continuation.normalized_cash_fact(_synthetic_fact(),{})
    value["caller_event_ticker"]="BBB"
    with pytest.raises(ValueError,match="UNPROVEN_TICKER_ALIAS"):
        continuation.normalized_cash_fact(value,{})
    path=tmp_path/"FAKE_ONLY_class_continuity.json";path.write_text('{"fixture":"common class continuity"}')
    value["ticker_continuity_proof"]={"same_common_stock":True,"retrospective_identity_crosswalk_only":True,
        "path":str(path),"sha256":continuation.digest(path)}
    before=copy.deepcopy(value);result=continuation.normalized_cash_fact(value,{})
    assert result["ticker"]=="BBB" and result["historical_declared_ticker"]=="AAA"
    assert "not backfilled" in result["identity_crosswalk_use"] and value==before
    assert result["publication_date"]==value["publication_date"]
    assert result["available_at_upper_bound"]==value["available_at_upper_bound"]
    assert result["ex_date_binding"]==value["ex_date_binding"]
    path.write_text('{"fixture":"changed class continuity"}')
    with pytest.raises(ValueError,match="TICKER_ALIAS_PROOF_CHANGED"):
        continuation.normalized_cash_fact(value,{})


@pytest.mark.parametrize("current,other",[(1,153),(0,154),(154,0)])
def test_cash_cumulative_budget_includes_other_revision(current,other):
    assert continuation.combined_account_attempts(current,other)==154


@pytest.mark.parametrize("bad",[-1,True,1.,"1",None])
def test_cash_cumulative_counter_unknown_is_fail_closed(bad):
    with pytest.raises(ValueError,match="INVALID_ACCOUNT_ATTEMPT_COUNT"):
        continuation.combined_account_attempts(0,bad)


def _bare_task(tmp_path,stage="continuation/cash_r1"):
    task=continuation.Continuation.__new__(continuation.Continuation)
    task.stage=stage;task.base_root=(tmp_path/"continuation").resolve()
    task.root=(tmp_path/stage).resolve()
    task.root.mkdir(parents=True,exist_ok=True)
    parent_root=tmp_path/"FAKE_ONLY_parent"
    task.parent=SimpleNamespace(input_sha=continuation.INPUT_SHA,
        out=lambda rel:(parent_root/rel).resolve(),read=lambda rel:{"fixture":"FAKE_ONLY"})
    return task


def test_cash_revision_freeze_is_immutable_and_preserves_pilot(tmp_path):
    pilot=_bare_task(tmp_path,"continuation");cash=_bare_task(tmp_path)
    pilot.write("ACCOUNT_FREEZE.json",{"stage":"pilot","identity":"FAKE_ONLY"},immutable=True)
    old=pilot.out("ACCOUNT_FREEZE.json").read_bytes()
    cash.write("CASH_INPUT_FREEZE.json",{"stage":"cash_r1"},immutable=True)
    cash.write("CASH_INPUT_FREEZE.json",{"stage":"cash_r1"},immutable=True)
    with pytest.raises(ValueError,match="CONTINUATION_FREEZE_CHANGED"):
        cash.write("CASH_INPUT_FREEZE.json",{"stage":"changed"},immutable=True)
    assert pilot.out("ACCOUNT_FREEZE.json").read_bytes()==old
    with pytest.raises(ValueError,match="CONTINUATION_PATH_ESCAPE"):
        cash.out("../../outside.json")


def _cash_prepared_fixture(tmp_path,monkeypatch):
    task=_bare_task(tmp_path)
    market=SimpleNamespace(dates=pd.DatetimeIndex(["2023-01-03","2023-01-04"]),tickers=np.array(["AAA"]))
    original_kwargs={"unsupported_events":({"ticker":"AAA","effective_date":"2023-01-04","reason":"FAKE_ONLY_FORENSIC"},)}
    cash_kwargs={"unsupported_events":copy.deepcopy(original_kwargs["unsupported_events"]),
        "entitlement_enabled":True,"entitlement_events":(),"entitlement_source_binding":{"fixture":"FAKE_ONLY"}}
    cached=task.parent.out("cache/market_and_inputs.joblib");cached.parent.mkdir(parents=True,exist_ok=True)
    joblib.dump({"market":market,"replay_kwargs":original_kwargs},cached)
    artifact=task.out("inputs/cash_replay_kwargs.joblib");artifact.parent.mkdir(parents=True,exist_ok=True);joblib.dump(cash_kwargs,artifact)
    children={}
    for name in ("fact","required","calendar","rule"):
        p=task.out("FAKE_ONLY_dependencies/"+name+".txt");p.parent.mkdir(parents=True,exist_ok=True);p.write_text("FAKE_ONLY "+name)
        children[name]=p
    freeze=dict(sources=[dict(path=str(children["fact"]),sha256=continuation.digest(children["fact"]))],
        required={"source_closure":dict(path=str(children["required"]),sha256=continuation.digest(children["required"]))},
        calendar=dict(path=str(children["calendar"]),sha256=continuation.digest(children["calendar"])),
        rules={"FAKE_ONLY":dict(source_reference=str(children["rule"]),source_fingerprint=continuation.digest(children["rule"]))},
        controller_sha256=continuation.digest(continuation.__file__),binder_sha256=continuation.digest(cash_binder.__file__),
        market_cache_sha256=continuation.CACHE_SHA,input_binding_sha256=continuation.INPUT_SHA)
    task.write("CASH_INPUT_FREEZE.json",freeze)
    receipt={"freeze_sha256":continuation.digest(task.out("CASH_INPUT_FREEZE.json")),
        "artifact":{"path":str(artifact),"sha256":continuation.digest(artifact)}}
    task.write("CASH_INPUT_RECEIPT.json",receipt)
    original_digest=continuation.digest
    def fictional_digest(path):
        p=Path(path).resolve()
        if p==cached.resolve():return continuation.CACHE_SHA
        if p==Path(continuation.common.__file__).resolve():return continuation.WRAPPER_SHA
        if p==Path(continuation.allocation.__file__).resolve():return continuation.ALLOCATION_SHA
        return original_digest(path)
    monkeypatch.setattr(continuation,"digest",fictional_digest)
    monkeypatch.setattr(continuation,"raw_extension_into_inputs",lambda task,inputs:{"fixture":"NO_REAL_RAW_READER"})
    monkeypatch.setattr(methods,"evaluation_market",lambda m:(m,0))
    seen=[]
    monkeypatch.setattr(methods,"with_effective_event_quality",lambda m,k:(seen.append(copy.deepcopy(k)) or m))
    monkeypatch.setattr(methods,"risk_inputs",lambda *args:({}, {}, {"fixture":"NO_REAL_RISK_READER"}))
    return task,children,artifact,cash_kwargs,original_kwargs,seen


def test_cash_prepared_preserves_original_quote_domain_before_loading_new_kwargs(tmp_path,monkeypatch):
    task,children,artifact,cash_kwargs,original_kwargs,seen=_cash_prepared_fixture(tmp_path,monkeypatch)
    inputs,*_=continuation.prepared(task)
    assert seen==[original_kwargs] and inputs["replay_kwargs"]==cash_kwargs
    assert inputs["replay_kwargs"]["unsupported_events"]==original_kwargs["unsupported_events"]


@pytest.mark.parametrize("dependency",["fact","required","calendar","rule"])
def test_cash_resume_rechecks_every_physical_source_dependency(tmp_path,monkeypatch,dependency):
    task,children,*_=_cash_prepared_fixture(tmp_path,monkeypatch)
    children[dependency].write_text("FAKE_ONLY changed bytes")
    with pytest.raises(ValueError,match="CASH_SOURCE_DEPENDENCY_CHANGED"):
        continuation.prepared(task)


@pytest.mark.parametrize("mutation",["freeze","artifact","outside","controller","binder","parent"])
def test_cash_resume_rejects_changed_freeze_artifact_and_source_pins(tmp_path,monkeypatch,mutation):
    task,children,artifact,*_=_cash_prepared_fixture(tmp_path,monkeypatch)
    if mutation=="freeze":
        task.out("CASH_INPUT_FREEZE.json").write_text('{}')
    elif mutation=="artifact":
        artifact.write_bytes(b"FAKE_ONLY changed joblib")
    elif mutation=="outside":
        receipt=task.read("CASH_INPUT_RECEIPT.json");receipt["artifact"]["path"]=str(task.base_root/"outside.joblib");task.write("CASH_INPUT_RECEIPT.json",receipt)
    else:
        freeze=task.read("CASH_INPUT_FREEZE.json")
        key={"controller":"controller_sha256","binder":"binder_sha256","parent":"input_binding_sha256"}[mutation]
        freeze[key]="0"*64;task.write("CASH_INPUT_FREEZE.json",freeze)
        receipt=task.read("CASH_INPUT_RECEIPT.json");receipt["freeze_sha256"]=continuation.digest(task.out("CASH_INPUT_FREEZE.json"));task.write("CASH_INPUT_RECEIPT.json",receipt)
    with pytest.raises(ValueError):continuation.prepared(task)


def _gate_record(pid,value=100.,*,bps=10,status="COMPLETE",scope=True,eligible=True):
    return dict(policy_path_id=pid,path_id=pid+"_S%02d"%bps,bps=bps,status=status,scope_complete=scope,
        metrics=dict(eligible_for_selection=eligible,final_certified_nav=value),receipt_sha256="a"*64)


def _gate_controls():return [_gate_record(methods.CONTROLS[0],100.),_gate_record(methods.CONTROLS[1],110.)]


@pytest.mark.parametrize("change",[{"scope_complete":False},{"status":"FAILED_RETAINED"},
    {"metrics":{"eligible_for_selection":False,"final_certified_nav":110.}},
    {"metrics":{"eligible_for_selection":True,"final_certified_nav":None}}])
def test_gate_unqualified_required_control_blocks_all_candidates(change):
    records=_gate_controls();records[1].update(change);records.append(_gate_record("M070",1000.))
    result=continuation.qualified_finalist(records)
    assert result["status"]=="NO_TESTABLE_FINALIST" and result["finalist"] is None
    assert result["test2026_unlocked"] is False


@pytest.mark.parametrize("value",[float("nan"),float("inf"),float("-inf"),True,np.bool_(True),"110",0.,-1.])
def test_gate_unknown_or_nonreal_certified_nav_cannot_qualify(value):
    records=_gate_controls();records[1]["metrics"]["final_certified_nav"]=value
    records.append(_gate_record("M070",1000.))
    assert continuation.qualified_finalist(records)["status"]=="NO_TESTABLE_FINALIST"


def test_gate_requires_strict_improvement_and_ignores_sensitivity():
    records=_gate_controls()+[_gate_record("M070",110.),_gate_record("M068",999.,bps=20)]
    assert continuation.qualified_finalist(records)["status"]=="NO_UPGRADE"


def test_gate_tie_break_is_frozen_id_and_incomplete_high_candidate_is_excluded():
    records=_gate_controls()+[_gate_record("M070",120.),_gate_record("M068",120.),_gate_record("M069",1000.,scope=False)]
    result=continuation.qualified_finalist(records)
    assert result["status"]=="ONE_QUALIFIED_PRE2026_FINALIST" and result["finalist"]=="M068"
    assert result["test2026_unlocked"] is False


def _finish_fixture(tmp_path,monkeypatch):
    task=_bare_task(tmp_path)
    monkeypatch.setattr(continuation,"Continuation",lambda *args:task)
    records=[]
    roles=continuation.continuation_roles()
    for index,pid in enumerate(roles):
        if pid in methods.CONTROLS or pid==methods.ANCHOR:
            record=_gate_record(pid,100.+index)
            file=task.out("FAKE_ONLY_ledgers/"+pid+".txt");file.parent.mkdir(parents=True,exist_ok=True);file.write_text("SYNTHETIC_ONLY_LEDGER_BYTES")
            record["artifacts"]={"daily":{"path":str(file),"sha256":continuation.digest(file)}}
            record["receipt"]="FAKE_ONLY_receipts/"+pid+".json";task.write(record["receipt"],record)
            record["receipt_sha256"]=continuation.digest(task.out(record["receipt"]))
        else:record=_gate_record(pid,None,status="BLOCKED_DEPENDENCY",scope=False,eligible=False)
        records.append(record)
    task.write("ACCOUNT_STATUS.json",{"attempts":3,"records":records})
    task.write("ACCOUNT_FREEZE.json",{"fixture":"FAKE_ONLY_FREEZE"},immutable=True)
    return task,records


@pytest.mark.parametrize("status",["STARTED","PENDING","SCHEDULED"])
def test_gate_finish_rejects_every_nonterminal_primary_status(tmp_path,monkeypatch,status):
    task,records=_finish_fixture(tmp_path,monkeypatch)
    records[-1]["status"]=status;task.write("ACCOUNT_STATUS.json",{"attempts":3,"records":records})
    with pytest.raises(ValueError):continuation.finish("FAKE_ONLY",task.stage)
    assert not task.out("FINALIST_GATE.json").exists()


@pytest.mark.parametrize("field",["receipt","artifacts"])
def test_gate_finish_complete_record_requires_verified_receipt_and_artifacts(tmp_path,monkeypatch,field):
    task,records=_finish_fixture(tmp_path,monkeypatch)
    records[0].pop(field);task.write("ACCOUNT_STATUS.json",{"attempts":3,"records":records})
    with pytest.raises(ValueError):continuation.finish("FAKE_ONLY",task.stage)
    assert not task.out("FINALIST_GATE.json").exists()


def test_gate_finish_refuses_changed_ledger_and_never_writes_success(tmp_path,monkeypatch):
    task,records=_finish_fixture(tmp_path,monkeypatch)
    Path(records[0]["artifacts"]["daily"]["path"]).write_text("FAKE_ONLY_LEDGER_CHANGED")
    with pytest.raises(ValueError,match="ACCOUNT_ARTIFACT_CHANGED"):
        continuation.finish("FAKE_ONLY",task.stage)
    assert not task.out("FINALIST_GATE.json").exists()


def test_gate_finish_resume_is_immutable_and_keeps_blocked_methods(tmp_path,monkeypatch):
    task,records=_finish_fixture(tmp_path,monkeypatch)
    result=continuation.finish("FAKE_ONLY",task.stage);before=task.out("FINALIST_GATE.json").read_bytes()
    again=continuation.finish("FAKE_ONLY",task.stage)
    assert result==again and task.out("FINALIST_GATE.json").read_bytes()==before
    assert result["primary_roles"]==42 and result["dependency_blocked"]==39
    assert result["new_fit_states_in_nonML_comparison"]==0 and result["test2026_unlocked"] is False



def test_cash_declared_amount_uses_only_direct_class_field():
    ads=dict(security_type="AMERICAN_DEPOSITARY_SHARE",cash_per_raw_ex_pretrade_ads=.3966,
             cash_per_raw_ex_pretrade_common_share=None,ordinary_shares_per_ads=6)
    assert continuation.declared_cash_amount(ads)==.3966
    common=dict(security_type="COMMON_STOCK",cash_per_raw_ex_pretrade_common_share=.12,
                cash_per_raw_ex_pretrade_ads=6.)
    assert continuation.declared_cash_amount(common)==.12


@pytest.mark.parametrize("security_type",["COMMON_STOCK","AMERICAN_DEPOSITARY_SHARE"])
def test_cash_declared_amount_never_falls_back_to_other_class(security_type):
    payload=dict(security_type=security_type,cash_per_raw_ex_pretrade_common_share=.12,
                 cash_per_raw_ex_pretrade_ads=.3966)
    field=("cash_per_raw_ex_pretrade_ads" if security_type=="AMERICAN_DEPOSITARY_SHARE" else "cash_per_raw_ex_pretrade_common_share")
    payload[field]=None
    with pytest.raises(ValueError,match="SOURCE_CASH_AMOUNT_UNKNOWN_OR_WRONG_CLASS"):
        continuation.declared_cash_amount(payload)


@pytest.mark.parametrize("value",[None,True,np.bool_(True),"0.3966",float("nan"),float("inf"),-.1])
def test_cash_declared_amount_unknown_nonfinite_or_wrong_type_is_blocked(value):
    payload=dict(security_type="AMERICAN_DEPOSITARY_SHARE",cash_per_raw_ex_pretrade_ads=value,
                 cash_per_raw_ex_pretrade_common_share=.12)
    with pytest.raises(ValueError,match="SOURCE_CASH_AMOUNT_UNKNOWN_OR_WRONG_CLASS"):
        continuation.declared_cash_amount(payload)


@pytest.mark.parametrize("security_type",[None,"UNKNOWN","PREFERRED_STOCK"])
def test_cash_declared_amount_unknown_share_class_is_not_assumed_common(security_type):
    payload=dict(cash_per_raw_ex_pretrade_common_share=.12,cash_per_raw_ex_pretrade_ads=.3966)
    if security_type is not None:payload["security_type"]=security_type
    with pytest.raises(ValueError,match="SOURCE_CASH_AMOUNT_UNKNOWN_OR_WRONG_CLASS"):
        continuation.declared_cash_amount(payload)



@pytest.mark.parametrize("vendor",[float("nan"),float("inf"),float("-inf"),True,np.bool_(True),"0.12",None,-.1])
def test_cash_typed_vendor_unknown_never_matches_declaration(vendor):
    assert continuation.typed_cash_amount_matches(vendor,.12) is False


def test_cash_typed_vendor_amount_must_match_actual_direct_declaration():
    assert continuation.typed_cash_amount_matches(np.float64(.12),.12) is True
    assert continuation.typed_cash_amount_matches(.12+5e-11,.12) is True
    assert continuation.typed_cash_amount_matches(.12+1e-8,.12) is False
    assert continuation.typed_cash_amount_matches(0.,.12) is False



@pytest.mark.parametrize("schema",[1,2])
def test_cash_r2_normalizer_exact_nasdaq_alias_only(schema):
    payload=_synthetic_fact()
    if schema==1:payload["listing_identity"]="Nasdaq: AAA"
    else:
        payload=continuation.normalized_cash_fact(payload,{})
        payload["listed_exchange"]="Nasdaq"
    before=copy.deepcopy(payload)
    value=continuation.normalized_cash_fact(payload,{"path":"FAKE_ONLY/source.json","sha256":"a"*64})
    assert value["listed_exchange"]=="NASDAQ" and value["ticker"]=="AAA"
    assert payload==before
    assert value["cash_per_raw_ex_pretrade_common_share"]==.12
    variant=copy.deepcopy(value);variant["listed_exchange"]="nasdaq"
    assert continuation.normalized_cash_fact(variant,{})["listed_exchange"]=="nasdaq"


def test_cash_r2_budget_counts_three_registered_namespaces(tmp_path,monkeypatch):
    assert continuation.STAGES[:3]==("continuation","continuation/cash_r1","continuation/cash_r2")
    task=_bare_task(tmp_path,"continuation/cash_r2")
    monkeypatch.setattr(continuation,"Continuation",lambda *args:task)
    task.write("ACCOUNT_STATUS.json",{"attempts":52,"records":[]})
    for stage in continuation.STAGES[:2]:
        path=task.base_root.parent/stage/"ACCOUNT_STATUS.json";path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps({"attempts":51,"records":[],"fixture":"FAKE_ONLY"}))
    task.write("CASH_INPUT_FREEZE.json",{"fixture":"FAKE_ONLY"})
    task.write("CASH_INPUT_RECEIPT.json",{"fixture":"FAKE_ONLY"})
    market=SimpleNamespace(dates=pd.DatetimeIndex(["2023-01-03"]),tickers=np.array(["AAA"]))
    inputs={"mu":{"RAW_CONTROL":np.zeros((1,1))},"account":{"fixture":"FAKE_ONLY"}}
    monkeypatch.setattr(continuation,"prepared",lambda task:(inputs,market,0,{}, {}, {}))
    control=methods.CONTROLS[0]
    monkeypatch.setattr(continuation,"continuation_roles",lambda:{control:{"kind":"RAW_CONTROL","forecast":"RAW_CONTROL"}})
    monkeypatch.setattr(continuation.runtime,"source_lineage",lambda **kw:{"fixture":"FAKE_ONLY"})
    monkeypatch.setattr(continuation,"load_training_inputs",lambda *args:pd.DataFrame())
    monkeypatch.setattr(methods,"artifact_from_status",lambda *args:{"fixture":"FAKE_ONLY"})
    monkeypatch.setattr(methods,"scenario_inputs",lambda *args:({}, {}, {}))
    monkeypatch.setattr(methods,"reference_portfolios",lambda *args:None)
    monkeypatch.setattr(methods,"forecast_inputs",lambda *args:(np.zeros((1,1)),np.zeros((1,1)),True,{}))
    monkeypatch.setattr(methods,"static_forecast_coverage",lambda *args:{"complete":True})
    def forbidden(*args,**kwargs):raise AssertionError("NO_REAL_POLICY_OR_ACCOUNT_MAY_START")
    monkeypatch.setattr(continuation,"policy_for",forbidden)
    monkeypatch.setattr(continuation.runtime,"run_continuous_account_indexed",forbidden)
    with pytest.raises(RuntimeError,match="CONTINUATION_ACCOUNT_BUDGET_EXHAUSTED"):
        continuation.run("FAKE_ONLY","primary",10,task.stage)
    assert task.read("ACCOUNT_STATUS.json")["attempts"]==52
    assert not task.out("ledgers").exists()


# R3_CONTROL_ONLY: fictional sources, serialized fixtures and stubbed accounts only.
@pytest.mark.parametrize("phase,bps",[("primary",10),("sensitivity",10),("finish",10),
    ("controls",0),("controls",5),("controls",20),("cash-freeze",5),("control-gate",20),
    ("controls",True),("controls","10")])
def test_r3_forbidden_operation_precedes_constructor_prepared_and_data(monkeypatch,phase,bps):
    def forbidden(*a,**k):raise AssertionError("NO_CONSTRUCTOR_OR_DATA_LOAD")
    monkeypatch.setattr(continuation,"Continuation",forbidden)
    monkeypatch.setattr(continuation,"prepared",forbidden)
    with pytest.raises(ValueError,match="R3_CONTROLS_ONLY_10BPS"):
        continuation.run("FAKE_ONLY",phase,bps,continuation.R3_STAGE)


def test_r3_prepared_direct_call_requires_explicit_control_admission():
    task=SimpleNamespace(stage=continuation.R3_STAGE)
    with pytest.raises(ValueError,match="R3_CONTROLS_ONLY_10BPS"):continuation.prepared(task)


def test_r3_main_rejects_old_finish_before_writer_lease(monkeypatch):
    import sys
    monkeypatch.setattr(sys,"argv",["FAKE_ONLY","--task-root","FAKE_ONLY","finish",
        "--stage",continuation.R3_STAGE,"--bps","10"])
    def forbidden(*a,**k):raise AssertionError("NO_WRITER_OR_ACCOUNT")
    monkeypatch.setattr(continuation,"task_writer",forbidden)
    with pytest.raises(ValueError,match="R3_CONTROLS_ONLY_10BPS"):continuation.main()


def _r3_revision_fixture(tmp_path,monkeypatch):
    task=_bare_task(tmp_path,continuation.R3_STAGE)
    sources=[]
    for index in range(38):
        p=task.base_root/("FAKE_ONLY_sources/fact_%02d.json"%index)
        p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({"fixture":"FAKE_ONLY","index":index}))
        sources.append(dict(path=str(p.resolve()),sha256=continuation.digest(p)))
    old=task.base_root/continuation.OLD_XP_SOURCE_REL
    old.parent.mkdir(parents=True,exist_ok=True);old.write_text('{"fixture":"FAKE_ONLY_UNKNOWN_XP"}')
    old_item=dict(path=str(old.resolve()),sha256=continuation.digest(old));sources.append(old_item)
    monkeypatch.setattr(continuation,"OLD_XP_SOURCE_SHA",old_item["sha256"])
    reuse=task.base_root/"cash_r2";reuse.mkdir(parents=True,exist_ok=True)
    freeze=reuse/"CASH_INPUT_FREEZE.json";freeze.write_text(json.dumps({"sources":sources}))
    freeze_sha=continuation.digest(freeze);monkeypatch.setattr(continuation,"R2_CASH_FREEZE_SHA",freeze_sha)
    events=[hashlib.sha256(("FAKE_ONLY_EVENT_%d"%i).encode()).hexdigest() for i in range(38)]
    receipt=reuse/"CASH_INPUT_RECEIPT.json"
    receipt.write_text(json.dumps({"freeze_sha256":freeze_sha,"events_bound":38,"source_binding":{"event_fingerprints":events}}))
    monkeypatch.setattr(continuation,"R2_CASH_RECEIPT_SHA",continuation.digest(receipt))
    new=task.out("sources/FAKE_ONLY_XP_NEW.json");new.parent.mkdir(exist_ok=True)
    new.write_text('{"fixture":"FAKE_ONLY_ANNOUNCED_CASH_NOT_VENDOR_AMOUNT"}')
    proof=task.out("sources/FAKE_ONLY_historical_class.txt");proof.write_text("SYNTHETIC_PREEX_CLASS_IDENTITY")
    publication=task.out("sources/FAKE_ONLY_publication.txt");publication.write_text("SYNTHETIC_PREEX_PUBLICATION")
    issuer="Fictional X\u00e9 Ltd."
    identity=dict(security_id=cash_binder.source_derived_security_id(issuer,"XP","NASDAQ:XP"),
        identity_kind="SOURCE_DERIVED_ISSUER_COMMON_CLASS",issuer=issuer,ticker="XP",
        listing_identity="NASDAQ:XP",security_type="COMMON_STOCK",available_at="2023-04-28T00:00:00Z",
        source_reference="https://issuer.example/fake-historical-class")
    revision=dict(schema_version=1,reuse_stage="continuation/cash_r2",reuse_root=str(reuse.resolve()),
        reuse_freeze_sha256=freeze_sha,old_source=old_item,
        replacement_source=dict(path=str(new),sha256=continuation.digest(new)),
        security_identity_source=dict(path=str(proof),sha256=continuation.digest(proof),identity=identity),
        source_evidence=[dict(path=str(publication),sha256=continuation.digest(publication),purpose="FAKE_ONLY publication")])
    task.write("XP_SOURCE_REVISION.json",revision)
    return task,revision,sources,events


def test_r3_reuses_exact38_sources_and_replaces_one_unknown_without_glob(tmp_path,monkeypatch):
    from scripts.v22.corporate_action_transition_r1 import canonical_bytes
    task,revision,old,events=_r3_revision_fixture(tmp_path,monkeypatch)
    extra=task.base_root/"FAKE_ONLY_sources/unfrozen_intruder.json";extra.write_text('{}')
    sources,identity,required,prior=continuation.r3_source_revision(task)
    assert sources[:-1]==old[:-1] and sources[-1]==revision["replacement_source"] and len(sources)==39
    assert revision["old_source"] not in sources and all(i["path"]!=str(extra) for i in sources)
    assert required["old_xp_source"]==revision["old_source"] and required["reuse_freeze"]["sha256"]==revision["reuse_freeze_sha256"]
    assert required["xp_source_evidence_000"]==revision["source_evidence"][0] and prior==events
    payload={k:identity[k] for k in ("security_id","identity_kind","issuer","ticker","listing_identity","security_type")}
    assert identity["identity_payload_sha256"]==hashlib.sha256(canonical_bytes(payload)).hexdigest()
    assert identity["available_at"]==revision["security_identity_source"]["identity"]["available_at"]


@pytest.mark.parametrize("which",["old_source","replacement_source","security_identity_source","reuse_freeze","reuse_receipt","source_evidence"])
def test_r3_every_explicit_source_evidence_sha_is_rechecked(tmp_path,monkeypatch,which):
    task,revision,*_=_r3_revision_fixture(tmp_path,monkeypatch)
    if which in ("reuse_freeze","reuse_receipt"):
        name="CASH_INPUT_FREEZE.json" if which=="reuse_freeze" else "CASH_INPUT_RECEIPT.json"
        path=Path(revision["reuse_root"])/name
    elif which=="source_evidence":path=Path(revision["source_evidence"][0]["path"])
    else:path=Path(revision[which]["path"])
    path.write_text("FAKE_ONLY changed bytes")
    with pytest.raises(ValueError,match="CASH_SOURCE_DEPENDENCY_CHANGED"):continuation.r3_source_revision(task)


@pytest.mark.parametrize("which",["reuse_root","reuse_freeze_sha256","old_path","old_sha","missing_evidence"])
def test_r3_unpinned_or_missing_parent_identity_is_rejected(tmp_path,monkeypatch,which):
    task,revision,*_=_r3_revision_fixture(tmp_path,monkeypatch)
    if which=="reuse_root":revision[which]=str(tmp_path/"OTHER_FAKE_ONLY")
    elif which=="reuse_freeze_sha256":revision[which]="0"*64
    elif which=="old_path":revision["old_source"]["path"]=revision["replacement_source"]["path"]
    elif which=="old_sha":revision["old_source"]["sha256"]="0"*64
    else:revision["source_evidence"]=[]
    task.write("XP_SOURCE_REVISION.json",revision)
    with pytest.raises(ValueError):continuation.r3_source_revision(task)


def test_r3_identity_unknown_availability_is_not_invented(tmp_path,monkeypatch):
    task,revision,*_=_r3_revision_fixture(tmp_path,monkeypatch)
    revision["security_identity_source"]["identity"].pop("available_at")
    task.write("XP_SOURCE_REVISION.json",revision)
    assert continuation.r3_source_revision(task)[1]["available_at"] is None


def test_r3_prepared_skips_risk_estimation_and_preserves_quote_domain(tmp_path,monkeypatch):
    task,children,artifact,cash_kwargs,original_kwargs,seen=_cash_prepared_fixture(tmp_path,monkeypatch)
    task.stage=continuation.R3_STAGE
    freeze=task.read("CASH_INPUT_FREEZE.json")
    monkeypatch.setattr(continuation,"r3_source_revision",lambda t:(freeze["sources"],{}, {}, []))
    receipt=task.read("CASH_INPUT_RECEIPT.json");receipt["source_binding"]={"event_fingerprints":[]};task.write("CASH_INPUT_RECEIPT.json",receipt)
    def forbidden(*a,**k):raise AssertionError("NO_RISK_STATE_READER")
    monkeypatch.setattr(methods,"risk_inputs",forbidden)
    inputs,market,start,covariance,raw,risk=continuation.prepared(task,phase="controls",bps=10)
    assert covariance=={} and risk["status"]=="NOT_REQUIRED_FOR_CONTROL_ONLY"
    assert inputs["replay_kwargs"]==cash_kwargs and seen==[original_kwargs]


def _r3_gate_fixture(tmp_path,monkeypatch):
    task,children,artifact,cash_kwargs,original_kwargs,seen=_cash_prepared_fixture(tmp_path,monkeypatch)
    task.stage=continuation.R3_STAGE
    cash_freeze=task.read("CASH_INPUT_FREEZE.json")
    monkeypatch.setattr(continuation,"r3_source_revision",lambda t:(cash_freeze["sources"],{}, {}, []))
    cash_receipt=task.read("CASH_INPUT_RECEIPT.json");cash_receipt["source_binding"]={"event_fingerprints":[]};task.write("CASH_INPUT_RECEIPT.json",cash_receipt)
    annual=task.out("FAKE_ONLY_raw_output.txt");annual.write_text("FAKE_ONLY_FROZEN_INFERENCE_BYTES")
    raw_receipt=task.base_root/"RAW_HELD_INPUT_VALIDATION.json";raw_receipt.parent.mkdir(exist_ok=True)
    raw_receipt.write_text(json.dumps({"annual_outputs":{"2023":{"path":str(annual),"sha256":continuation.digest(annual)}}}))
    freeze=dict(stage=continuation.R3_STAGE,controls_only=True,roles=continuation.stage_roles(continuation.R3_STAGE),
        frictions=[10],allowed_role_ids=list(methods.CONTROLS),budget=dict(stage_account_cap=2,new_fit_units=0),
        cash_input_revision=dict(sha256=continuation.digest(task.out("CASH_INPUT_FREEZE.json")),receipt_sha256=continuation.digest(task.out("CASH_INPUT_RECEIPT.json"))),
        source_sha256={continuation.__file__:continuation.digest(continuation.__file__)},
        raw_held=dict(raw_extension_receipt_sha256=continuation.digest(raw_receipt)))
    task.write("ACCOUNT_FREEZE.json",freeze)
    records=[]
    for pid in methods.CONTROLS:
        record=dict(policy_path_id=pid,path_id=pid+"_S10",bps=10,status="COMPLETE",scope_complete=True,
            freeze_sha256=continuation.digest(task.out("ACCOUNT_FREEZE.json")),
            metrics=dict(accounting_qualified=True,required_audits_passed=True,eligible_for_selection=True))
        ledger=task.out("FAKE_ONLY_ledgers/"+pid+".txt");ledger.parent.mkdir(exist_ok=True);ledger.write_text("SYNTHETIC_ONLY_ARTIFACT")
        record["artifacts"]={"daily":{"path":str(ledger),"sha256":continuation.digest(ledger)}}
        record["receipt"]="FAKE_ONLY_receipts/"+pid+".json";task.write(record["receipt"],record)
        record["receipt_sha256"]=continuation.digest(task.out(record["receipt"]));records.append(record)
    task.write("ACCOUNT_STATUS.json",dict(attempts=2,records=records))
    monkeypatch.setattr(continuation,"Continuation",lambda *a,**k:task)
    monkeypatch.setattr(continuation.runtime,"source_lineage",lambda **k:{"fixture":"FAKE_ONLY"})
    def forbidden(*a,**k):raise AssertionError("NO_TRAINING_ACCOUNT_RANKING_OR_PREPARED")
    monkeypatch.setattr(continuation,"prepared",forbidden)
    monkeypatch.setattr(continuation,"qualified_finalist",forbidden)
    monkeypatch.setattr(continuation,"run",forbidden)
    return task,records,children,artifact


def _r3_update_saved_record(task,record):
    task.write(record["receipt"],{k:v for k,v in record.items() if k!="receipt_sha256"})
    record["receipt_sha256"]=continuation.digest(task.out(record["receipt"]))


def test_r3_gate_is_metadata_only_and_never_promotes_or_starts_candidates(tmp_path,monkeypatch):
    task,records,*_=_r3_gate_fixture(tmp_path,monkeypatch)
    result=continuation.control_gate("FAKE_ONLY")
    before=task.out("CONTROL_QUALIFICATION_GATE.json").read_bytes()
    assert result["status"]=="CONTROLS_QUALIFIED" and result["candidate_attempts"]==0
    assert result["finalist"] is None and result["test2026_unlocked"] is False and result["new_fit_units"]==0
    assert continuation.control_gate("FAKE_ONLY")==result
    assert task.out("CONTROL_QUALIFICATION_GATE.json").read_bytes()==before
    assert not task.out("FINALIST_GATE.json").exists()


@pytest.mark.parametrize("field",["scope_complete","accounting_qualified","required_audits_passed","eligible_for_selection"])
@pytest.mark.parametrize("value",[False,None,1,"true"])
def test_r3_gate_each_qualification_requires_exact_true(tmp_path,monkeypatch,field,value):
    task,records,*_=_r3_gate_fixture(tmp_path,monkeypatch)
    if field=="scope_complete":records[0][field]=value
    else:records[0]["metrics"][field]=value
    _r3_update_saved_record(task,records[0]);task.write("ACCOUNT_STATUS.json",dict(attempts=2,records=records))
    result=continuation.control_gate("FAKE_ONLY")
    assert result["status"]=="STOP_CONTROL_UNQUALIFIED" and result["candidate_attempts"]==0


@pytest.mark.parametrize("which",["source","raw","cash_artifact","receipt","ledger","record"])
def test_r3_gate_source_and_artifact_closure_fail_closed(tmp_path,monkeypatch,which):
    task,records,children,artifact=_r3_gate_fixture(tmp_path,monkeypatch)
    if which=="source":children["fact"].write_text("FAKE_ONLY corrupted source")
    elif which=="raw":task.out("FAKE_ONLY_raw_output.txt").write_text("FAKE_ONLY corrupted output")
    elif which=="cash_artifact":artifact.write_bytes(b"FAKE_ONLY corrupted kwargs")
    elif which=="receipt":task.out(records[0]["receipt"]).write_text('{}')
    elif which=="ledger":Path(records[0]["artifacts"]["daily"]["path"]).write_text("FAKE_ONLY changed artifact")
    else:
        records[0]["metrics"]["accounting_qualified"]=False;task.write("ACCOUNT_STATUS.json",dict(attempts=2,records=records))
    with pytest.raises(ValueError):continuation.control_gate("FAKE_ONLY")
    assert not task.out("CONTROL_QUALIFICATION_GATE.json").exists()


@pytest.mark.parametrize("status",["FAILED_RETAINED","INTERRUPTED_FAILURE_RETAINED","BLOCKED_DEPENDENCY"])
def test_r3_gate_noncomplete_and_missing_controls_stop(tmp_path,monkeypatch,status):
    task,records,*_=_r3_gate_fixture(tmp_path,monkeypatch)
    records[0]["status"]=status;attempts=1 if status=="BLOCKED_DEPENDENCY" else 2
    task.write("ACCOUNT_STATUS.json",dict(attempts=attempts,records=records))
    result=continuation.control_gate("FAKE_ONLY")
    assert result["status"]=="STOP_CONTROL_UNQUALIFIED" and result["candidate_attempts"]==0


def test_r3_record_scope_duplicate_or_candidate_never_admitted():
    control=methods.CONTROLS[0]
    record=dict(policy_path_id=control,path_id=control+"_S10",bps=10,status="COMPLETE")
    for records in ([record,dict(record)],[dict(record,policy_path_id="M070",path_id="M070_S10")]):
        with pytest.raises(ValueError):continuation.validate_control_records(dict(attempts=len(records),records=records))


@pytest.mark.parametrize("retained",["FAILED_RETAINED","STARTED"])
def test_r3_resume_preserves_failed_attempts_skips_completed_and_never_reads_labels(tmp_path,monkeypatch,retained):
    task=_bare_task(tmp_path,continuation.R3_STAGE)
    monkeypatch.setattr(continuation,"Continuation",lambda *a:task)
    task.write("CASH_INPUT_FREEZE.json",{"fixture":"FAKE_ONLY"});task.write("CASH_INPUT_RECEIPT.json",{"fixture":"FAKE_ONLY"})
    records=[dict(policy_path_id=p,path_id=p+"_S10",bps=10,status=retained) for p in methods.CONTROLS]
    task.write("ACCOUNT_STATUS.json",dict(attempts=2,records=records))
    market=SimpleNamespace(dates=pd.DatetimeIndex(["2023-01-03"]),tickers=np.array(["AAA"]))
    monkeypatch.setattr(continuation,"prepared",lambda *a,**k:({},market,0,{}, {}, {}))
    monkeypatch.setattr(continuation.runtime,"source_lineage",lambda **k:{"fixture":"FAKE_ONLY"})
    def forbidden(*a,**k):raise AssertionError("NO_LABEL_RISK_SCENARIO_REFERENCE_OR_NEW_ACCOUNT")
    for name in ("load_training_inputs","policy_for") :monkeypatch.setattr(continuation,name,forbidden)
    for name in ("risk_inputs","scenario_inputs","reference_portfolios","forecast_inputs"):monkeypatch.setattr(methods,name,forbidden)
    monkeypatch.setattr(continuation.runtime,"run_continuous_account_indexed",forbidden)
    result=continuation.run("FAKE_ONLY","controls",10,continuation.R3_STAGE)
    assert result["attempts"]==2 and len(result["records"])==2
    assert all(x["status"]==("INTERRUPTED_FAILURE_RETAINED" if retained=="STARTED" else retained) for x in result["records"])
    assert set(task.read("ACCOUNT_FREEZE.json")["roles"])==set(methods.CONTROLS)
    assert task.read("ACCOUNT_FREEZE.json")["frictions"]==[10] and not task.out("SCENARIO_INPUTS.json").exists()


def test_r3_is_in_cumulative_stage_budget_and_no_counter_is_reset():
    assert continuation.STAGES[:4][-1]==continuation.R3_STAGE and len(continuation.STAGES[:4])==4
    total=0
    for value in [2,0,46,2]:total=continuation.combined_account_attempts(total,value)
    assert total==50
    assert continuation.combined_account_attempts(152,2)==154



def _r3_stub_run_fixture(tmp_path,monkeypatch,prior_attempts=48):
    task=_bare_task(tmp_path,continuation.R3_STAGE)
    monkeypatch.setattr(continuation,"Continuation",lambda *a:task)
    task.write("CASH_INPUT_FREEZE.json",{"fixture":"FAKE_ONLY"});task.write("CASH_INPUT_RECEIPT.json",{"fixture":"FAKE_ONLY"})
    for stage,attempts in zip(continuation.STAGES[:3],[2,0,prior_attempts-2]):
        path=task.base_root.parent/stage/"ACCOUNT_STATUS.json";path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(dict(attempts=attempts,records=[])))
    market=SimpleNamespace(dates=pd.DatetimeIndex(["2023-01-03"]),tickers=np.array(["AAA"]))
    inputs=dict(mu={"RAW_CONTROL":np.zeros((1,1))},account={"fixture":"FAKE_ONLY"},replay_kwargs={})
    monkeypatch.setattr(continuation,"prepared",lambda *a,**k:(inputs,market,0,{}, {}, {}))
    monkeypatch.setattr(continuation.runtime,"source_lineage",lambda **k:{"fixture":"FAKE_ONLY"})
    def forbidden(*a,**k):raise AssertionError("NO_LABEL_RISK_SCENARIO_REFERENCE_READER")
    monkeypatch.setattr(continuation,"load_training_inputs",forbidden)
    for name in ("risk_inputs","scenario_inputs","reference_portfolios","artifact_from_status"):
        monkeypatch.setattr(methods,name,forbidden)
    monkeypatch.setattr(methods,"forecast_inputs",lambda *a:(np.zeros((1,1)),np.zeros((1,1)),True,{"fixture":"FAKE_ONLY"}))
    monkeypatch.setattr(methods,"static_forecast_coverage",lambda *a:{"complete":True})
    monkeypatch.setattr(continuation,"policy_for",lambda *a:object())
    monkeypatch.setattr(methods,"ScientificCoveragePolicy",lambda *a:SimpleNamespace(missing_rows=0,missing_held_rows=0,records=[]))
    monkeypatch.setattr(methods,"path_metrics",lambda *a:dict(accounting_qualified=True,required_audits_passed=True,eligible_for_selection=True))
    def save(task,sid,*a):
        path=task.out("FAKE_ONLY_ARTIFACTS/"+sid+".txt");path.parent.mkdir(exist_ok=True);path.write_text("FAKE_ONLY")
        return {"daily":{"path":str(path),"sha256":continuation.digest(path)}}
    monkeypatch.setattr(continuation,"save_tables",save)
    calls=[]
    def replay(m,roles,*a,**k):
        calls.extend(roles)
        return SimpleNamespace(audit={"actual_cash_flow_identity_error_max":0.},
            metadata={"corporate_action_receipts":{},"corporate_action_exceptions":[]},prefix_identity={"fixture":"FAKE_ONLY"})
    monkeypatch.setattr(continuation.runtime,"run_continuous_account_indexed",replay)
    return task,calls


def test_r3_stub_run_starts_exactly_two_controls_with_no_label_risk_or_candidate_work(tmp_path,monkeypatch):
    task,calls=_r3_stub_run_fixture(tmp_path,monkeypatch)
    result=continuation.run("FAKE_ONLY","controls",10,continuation.R3_STAGE)
    assert calls==list(methods.CONTROLS) and result["attempts"]==2
    assert all(r["status"]=="COMPLETE" for r in result["records"])
    freeze=task.read("ACCOUNT_FREEZE.json")
    assert set(freeze["roles"])==set(methods.CONTROLS) and freeze["budget"]["stage_account_cap"]==2
    assert freeze["candidate_attempts"]==0 and freeze["budget"]["new_fit_units"]==0
    assert not task.out("SCENARIO_INPUTS.json").exists()
    before=task.out("ACCOUNT_STATUS.json").read_bytes()
    again=continuation.run("FAKE_ONLY","controls",10,continuation.R3_STAGE)
    assert again==result and calls==list(methods.CONTROLS)
    assert task.out("ACCOUNT_STATUS.json").read_bytes()==before


def test_r3_four_namespace_exhausted_budget_prevents_even_first_stub_account(tmp_path,monkeypatch):
    task,calls=_r3_stub_run_fixture(tmp_path,monkeypatch,154)
    with pytest.raises(RuntimeError,match="CONTINUATION_ACCOUNT_BUDGET_EXHAUSTED"):
        continuation.run("FAKE_ONLY","controls",10,continuation.R3_STAGE)
    assert calls==[] and not task.out("ACCOUNT_STATUS.json").exists()
    prior=json.loads((task.base_root/"cash_r2/ACCOUNT_STATUS.json").read_text())
    assert prior["attempts"]==152


def test_r3_announced_cash_never_rounds_vendor_amount_into_match():
    assert continuation.declared_cash_amount(dict(security_type="COMMON_STOCK",cash_per_raw_ex_pretrade_common_share=.58))==.58
    assert continuation.typed_cash_amount_matches(.58498,.58) is False
    assert continuation.typed_cash_amount_matches(.58,.58) is True


def test_r3_identity_hash_matches_binder_without_promoting_extra_class_metadata(tmp_path,monkeypatch):
    task,revision,*_=_r3_revision_fixture(tmp_path,monkeypatch)
    revision["security_identity_source"]["identity"]["security_class"]="CLASS_A_COMMON_SHARES"
    task.write("XP_SOURCE_REVISION.json",revision)
    identity=continuation.r3_source_revision(task)[1]
    terms=dict(issuer=identity["issuer"],ticker="XP",listing="NASDAQ:XP",security_type="COMMON_STOCK")
    sid,proof=cash_binder._identity(terms,identity,pd.Timestamp("2023-09-11T13:30:00Z"))
    assert sid==identity["security_id"] and identity["security_class"]=="CLASS_A_COMMON_SHARES"
    assert "security_class" not in proof["identity"] and proof["identity_payload_sha256"]==identity["identity_payload_sha256"]



@pytest.mark.parametrize("stage",[continuation.R3_STAGE,continuation.R4_STAGE])
def test_r3_real_cash_prepare_assembly_preserves38_claims_and_vendor_mismatch(tmp_path,monkeypatch,stage):
    # Real prepare and cash binder; only physical market/calendar/vendor readers are fake.
    from scripts.v22.corporate_action_transition_r1 import (canonical_bytes,SourceBackedEntitlementEvent,
        USD_PER_RAW_OLD_SHARE,RAW_OLD_SHARE_COORDINATE)
    task,revision,sources,_=_r3_revision_fixture(tmp_path,monkeypatch)
    if stage==continuation.R4_STAGE:task=_bare_task(tmp_path,stage)
    revision["security_identity_source"]["identity"]["security_class"]="CLASS_A_COMMON_SHARES"
    prior_task=_bare_task(tmp_path,"continuation/cash_r2")
    old_fingerprints=[]
    tickers=["A%02d"%i for i in range(38)]+["XP"]
    source_by_ticker={}
    for index,item in enumerate(sources[:-1]+[revision["replacement_source"]]):
        ticker=tickers[index]
        issuer=(revision["security_identity_source"]["identity"]["issuer"] if ticker=="XP" else "Fictional Alpha %02d Inc."%index)
        payload=dict(event_key=ticker+"_FAKE_2023-09-11",ticker=ticker,issuer=issuer,
            listed_exchange="NASDAQ",security_type="COMMON_STOCK",currency="USD",currency_confidence="EXPLICIT_USD",
            source_url="https://issuer.example/FAKE_ONLY_"+ticker,
            cash_per_raw_ex_pretrade_common_share=.58 if ticker=="XP" else .12,
            amount_unit=USD_PER_RAW_OLD_SHARE,quantity_coordinate=RAW_OLD_SHARE_COORDINATE,
            record_date="2023-09-12",scheduled_pay_date="2023-09-25",publication_date="2023-09-01",
            available_at_upper_bound="2023-09-03T00:00:00Z",ex_date_binding={"value":"2023-09-11","issuer_direct":False})
        if stage==continuation.R4_STAGE and ticker=="XP":payload["security_class"]="CLASS_A_COMMON_SHARES"
        path=Path(item["path"]);path.write_text(json.dumps(payload));item["sha256"]=continuation.digest(path)
        source_by_ticker[ticker]=item
        if ticker!="XP":
            normalized=continuation.normalized_cash_fact(payload,item)
            prior_task.write("inputs/normalized/"+payload["event_key"]+".json",normalized)
            physical=continuation.digest(prior_task.out("inputs/normalized/"+payload["event_key"]+".json"))
            sid=cash_binder.source_derived_security_id(issuer,ticker,"NASDAQ:"+ticker)
            event_id="SOURCE_CASH:"+hashlib.sha256(canonical_bytes({"security_id":sid,"ex":"2023-09-11","family":"CASH_DIVIDEND"})).hexdigest()
            event=SourceBackedEntitlementEvent(event_id,"CASH_DIVIDEND",sid,ticker,"2023-09-11","2023-09-12","2023-09-25",
                str(pd.Timestamp(payload["available_at_upper_bound"])),.12,"USD",USD_PER_RAW_OLD_SHARE,RAW_OLD_SHARE_COORDINATE,
                "TIER1_ISSUER_REGULATOR_EXCHANGE",payload["source_url"],physical)
            old_fingerprints.append(event.event_fingerprint)
    reuse=Path(revision["reuse_root"])
    prior_freeze=reuse/"CASH_INPUT_FREEZE.json";prior_freeze.write_text(json.dumps({"sources":sources}))
    prior_sha=continuation.digest(prior_freeze);revision["reuse_freeze_sha256"]=prior_sha
    monkeypatch.setattr(continuation,"R2_CASH_FREEZE_SHA",prior_sha)
    prior_receipt=reuse/"CASH_INPUT_RECEIPT.json"
    prior_receipt.write_text(json.dumps({"freeze_sha256":prior_sha,"events_bound":38,"source_binding":{"event_fingerprints":old_fingerprints}}))
    monkeypatch.setattr(continuation,"R2_CASH_RECEIPT_SHA",continuation.digest(prior_receipt))
    task.write("XP_SOURCE_REVISION.json",revision)
    common_calendar=task.out("FAKE_ONLY_calendar.txt");common_calendar.write_text("FAKE_ONLY_LEGAL_SESSIONS")
    calendar_sha=continuation.digest(common_calendar)
    dates=pd.DatetimeIndex(["2023-09-08","2023-09-11","2023-09-12","2023-09-25"])
    parent_read=lambda rel:dict(extended_five_day_labels={"common_calendar":{"path":str(common_calendar),"sha256":calendar_sha}})
    task.parent.read=parent_read
    for name in ["CASH_VENDOR_READ_RECEIPT.json","CASH_VENDOR_EXACT_KEYS_R2.json","ACCOUNT_SOURCE_CLOSURE.json"]:
        path=task.base_root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{}')
    vendor=task.base_root/"inputs/CASH_VENDOR_EXACT39.parquet";vendor.parent.mkdir(parents=True,exist_ok=True);vendor.write_bytes(b"FAKE_ONLY_TYPED_VENDOR")
    mappings=[];vendor_rows=[];unsupported=[]
    for ticker in tickers:
        mappings.append(dict(ticker=ticker,effective_date="2023-09-11",code=ticker,source_event_date="2023-09-11"))
        vendor_rows.append(dict(code=ticker,ex_div_date=pd.Timestamp("2023-09-11"),per_cash_div=.58498 if ticker=="XP" else .12,special_dividend=0.))
        unsupported.append(dict(ticker=ticker,effective_date="2023-09-11",source_fingerprint=hashlib.sha256(("FAKE_ONLY_VENDOR_"+ticker).encode()).hexdigest(),reason="VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY"))
    (task.base_root/"CASH_VENDOR_EXACT_KEYS_R2.json").write_text(json.dumps({"keys":mappings}))
    validation=task.parent.out("receipts/CASH_BINDER_COMPONENT_VALIDATION.json");validation.parent.mkdir(parents=True,exist_ok=True);validation.write_text('{"fixture":"FAKE_ONLY"}')
    for name in ["FINRA_17_19.pdf","FINRA_24_04.pdf"]:
        path=task.base_root/"sources/BP_TFPM"/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b"FAKE_ONLY_HISTORICAL_RULE_BYTES")
    cache=task.parent.out("cache/market_and_inputs.joblib");cache.parent.mkdir(parents=True,exist_ok=True);cache.write_bytes(b"FAKE_ONLY_MARKET_OBJECT")
    market=SimpleNamespace(dates=pd.DatetimeIndex(["2023-09-08"]),tickers=np.array(tickers),
        close=np.full((1,len(tickers)),100.),signal_asof=[pd.Timestamp("2023-09-08T20:00:00Z")])
    inputs=dict(market=market,replay_kwargs=dict(unsupported_events=tuple(unsupported),quote_fixture="ORIGINAL_QUALITY_UNCHANGED"))
    actual_digest=continuation.digest
    pinned={cache.resolve():continuation.CACHE_SHA,vendor.resolve():"9da9a09ef63b00f3b82f691a682b4a7fb5ed8d4b6cc337ba5665d51de4851f4f",
        (task.base_root/"ACCOUNT_SOURCE_CLOSURE.json").resolve():"5bb84e13cc6e113baa964122e7a85e5d4d9edc3a44c23f7a70bc30f0e2417181",
        (task.base_root/"sources/BP_TFPM/FINRA_17_19.pdf").resolve():"52a8ee08c6b7766fddaff1bdc587275271434290546712c687b3e31e5522348f",
        (task.base_root/"sources/BP_TFPM/FINRA_24_04.pdf").resolve():"b3b74a8cc5f150839cd5a209026d60c0db449722ab62ce38c310506b74d612e5"}
    monkeypatch.setattr(continuation,"digest",lambda p:pinned.get(Path(p).resolve(),None) or actual_digest(p))
    monkeypatch.setattr(continuation,"Continuation",lambda *a:task)
    monkeypatch.setattr(continuation,"guard_parquet",lambda *a:(SimpleNamespace(read=lambda **k:SimpleNamespace(to_pandas=lambda:pd.DataFrame({"trade_date":dates}))),{}))
    monkeypatch.setattr(continuation.pd,"read_parquet",lambda *a,**k:pd.DataFrame(vendor_rows))
    actual_load=continuation.joblib.load
    monkeypatch.setattr(continuation.joblib,"load",lambda p,*a,**k:copy.deepcopy(inputs) if Path(p).resolve()==cache.resolve() else actual_load(p,*a,**k))
    if stage==continuation.R4_STAGE:
        item=source_by_ticker["XP"];xp_payload=json.loads(Path(item["path"]).read_text())
        xp_vendor=next(e for e in unsupported if e["ticker"]=="XP")
        _write_r4_policy_fixture(task,revision,xp_payload,item,xp_vendor["source_fingerprint"],pinned[vendor.resolve()])
    result=continuation.prepare_cash_stage("FAKE_ONLY",stage)
    freeze=task.read("CASH_INPUT_FREEZE.json")
    assert len(freeze["sources"])==39 and freeze["sources"][:-1]==sources[:-1]
    assert freeze["required"]["typed_vendor"]["path"]==str(vendor)
    assert freeze["required"]["xp_source_evidence_000"]==revision["source_evidence"][0]
    assert freeze["controls_only"] is True and freeze["allowed_role_ids"]==list(methods.CONTROLS)
    assert result["events_bound"]==39 and result["exact_vendor_exceptions_removed"]==(39 if stage==continuation.R4_STAGE else 38)
    assert result["unsupported_after"]==(0 if stage==continuation.R4_STAGE else 1) and result["new_fits"]==0
    kwargs=actual_load(result["artifact"]["path"])
    assert kwargs["entitlement_enabled"] is True and kwargs["quote_fixture"]=="ORIGINAL_QUALITY_UNCHANGED"
    if stage==continuation.R4_STAGE:
        assert kwargs["unsupported_events"]==()
        assert result["qualification_basis"]=="SOURCE_DECLARED_GROSS"
        assert result["vendor_numeric_conflict_reconciled"] is False and result["final_paid_rate_verified"] is False
        conflict=result["source_binding"]["manifest"]["source_precedence"]["numeric_conflict_diagnostics"][0]
        assert conflict["issuer_cash_per_raw_old_share"]==.58 and conflict["vendor_cash_per_raw_old_share"]==.58498
    else:assert len(kwargs["unsupported_events"])==1 and kwargs["unsupported_events"][0]["ticker"]=="XP"
    assert {e.event_fingerprint for e in kwargs["entitlement_events"] if e.ticker!="XP"}==set(old_fingerprints)
    xp=next(e for e in kwargs["entitlement_events"] if e.ticker=="XP")
    assert xp.cash_per_old_share==.58
    assert task.read("PRICE_IDENTITY_INPUTS.json")["identities"]["XP"]["security_class"]=="CLASS_A_COMMON_SHARES"
    assert continuation.verify_cash_inputs(task)[0]["artifact"]==result["artifact"]
    if stage==continuation.R4_STAGE:
        policy_path=task.out("XP_SOURCE_PRECEDENCE.json");old_bytes=policy_path.read_bytes();policy_path.write_text("{}")
        with pytest.raises(ValueError):continuation.verify_cash_inputs(task)
        policy_path.write_bytes(old_bytes)
    Path(revision["source_evidence"][0]["path"]).write_text("FAKE_ONLY altered publication evidence")
    with pytest.raises(ValueError,match="CASH_SOURCE_DEPENDENCY_CHANGED"):continuation.verify_cash_inputs(task)


@pytest.mark.parametrize("phase,bps",[("primary",10),("sensitivity",10),("finish",10),("controls",5),("controls",20)])
def test_r4_forbidden_operation_precedes_all_construction_and_data(monkeypatch,phase,bps):
    def forbidden(*a,**k):raise AssertionError("R4_MUST_REJECT_BEFORE_DATA")
    monkeypatch.setattr(continuation,"Continuation",forbidden)
    monkeypatch.setattr(continuation,"prepared",forbidden)
    with pytest.raises(ValueError):continuation.run("FAKE_ONLY",phase,bps,continuation.R4_STAGE)


def _write_r4_policy_fixture(task,revision,payload,item,vendor_fp,typed_sha):
    import os
    from scripts.v22.corporate_action_transition_r1 import canonical_bytes
    normalized=continuation.normalized_cash_fact(payload,item)
    text=json.dumps(methods.json_safe(normalized),ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    physical=hashlib.sha256(text.replace("\n",os.linesep).encode("utf-8")).hexdigest()
    identity=dict(revision["security_identity_source"]["identity"])
    identity_sha=hashlib.sha256(canonical_bytes({k:identity[k] for k in
        ("security_id","identity_kind","issuer","ticker","listing_identity","security_type")})).hexdigest()
    scope=dict(ticker="XP",effective_date="2023-09-11",fact_key=normalized["event_key"],
        vendor_event_source_fingerprint=vendor_fp,original_statement_source_sha256=item["sha256"],
        statement_fact_sha256=physical,statement_payload_sha256=hashlib.sha256(canonical_bytes(normalized)).hexdigest(),
        security_id=identity["security_id"],security_class="CLASS_A_COMMON_SHARES",
        security_type="COMMON_STOCK",listing_identity="NASDAQ:XP",identity_payload_sha256=identity_sha,
        amount_unit="USD_PER_RAW_OLD_SHARE",quantity_coordinate="RAW_OLD_SECURITY_SHARES",
        issuer_cash_per_raw_old_share=.58,vendor_cash_per_raw_old_share=.58498,
        vendor_typed_cash_field_source_sha256=typed_sha,vendor_cash_field="per_cash_div",
        non_cash_flags_absent=True)
    policy=dict(schema_version=1,policy_id="XP_2023_09_11_SOURCE_DECLARED_GROSS_R4",
        stage=continuation.R4_STAGE,accounting_authority="SOURCE_DECLARED_GROSS",
        numeric_conflict="RETAIN_UNRECONCILED_VENDOR_DIAGNOSTIC",scope=scope)
    task.write("XP_SOURCE_PRECEDENCE.json",dict(payload=policy,
        payload_sha256=hashlib.sha256(canonical_bytes(policy)).hexdigest()))
    revision["source_precedence_policy"]=dict(path=str(task.out("XP_SOURCE_PRECEDENCE.json")),
                                             sha256=continuation.digest(task.out("XP_SOURCE_PRECEDENCE.json")))
    revision["source_evidence"].append(dict(revision["source_precedence_policy"],purpose="FAKE_ONLY_R4_policy"))
    task.write("XP_SOURCE_REVISION.json",revision)


def test_r4_namespace_budget_counts_prior_r3_without_reset():
    assert continuation.STAGES[-1]==continuation.R4_STAGE and len(continuation.STAGES)==5
    assert continuation.stage_roles(continuation.R4_STAGE)==continuation.stage_roles(continuation.R3_STAGE)
    total=0
    for value in [2,0,46,2,2]:total=continuation.combined_account_attempts(total,value)
    assert total==52 and continuation.combined_account_attempts(152,2)==154


def _r4_gate_fixture(tmp_path,monkeypatch):
    task,records,children,artifact=_r3_gate_fixture(tmp_path,monkeypatch)
    task.stage=continuation.R4_STAGE
    policy=dict(path="FAKE_ONLY/policy.json",sha256="a"*64,payload_sha256="b"*64)
    expected=continuation._precedence_metadata(policy)
    cash_freeze=task.read("CASH_INPUT_FREEZE.json")
    cash_freeze.setdefault("required",{})["xp_source_precedence_policy"]={"path":policy["path"],"sha256":policy["sha256"]}
    task.write("CASH_INPUT_FREEZE.json",cash_freeze)
    cash_receipt=task.read("CASH_INPUT_RECEIPT.json")
    monkeypatch.setattr(continuation,"verify_cash_inputs",lambda t:(cash_receipt,cash_freeze,artifact))
    monkeypatch.setattr(continuation,"_load_source_precedence_policy",lambda item:policy)
    freeze=task.read("ACCOUNT_FREEZE.json");freeze.update(stage=continuation.R4_STAGE,**expected)
    freeze["cash_input_revision"]=dict(sha256=continuation.digest(task.out("CASH_INPUT_FREEZE.json")),
        receipt_sha256=continuation.digest(task.out("CASH_INPUT_RECEIPT.json")))
    task.write("ACCOUNT_FREEZE.json",freeze)
    for record in records:
        record.update(expected,freeze_sha256=continuation.digest(task.out("ACCOUNT_FREEZE.json")))
        _r3_update_saved_record(task,record)
    task.write("ACCOUNT_STATUS.json",dict(attempts=2,records=records))
    return task,records,expected


def test_r4_gate_propagates_declared_gross_basis_without_ranking_or_test_unlock(tmp_path,monkeypatch):
    task,records,expected=_r4_gate_fixture(tmp_path,monkeypatch)
    gate=continuation.control_gate("FAKE_ONLY",continuation.R4_STAGE)
    assert gate["status"]=="CONTROLS_QUALIFIED"
    assert all(gate[k]==v for k,v in expected.items())
    assert gate["candidate_attempts"]==gate["new_fit_units"]==0 and gate["test2026_unlocked"] is False
    assert gate["finalist"] is None


@pytest.mark.parametrize("field,value",[
    ("qualification_basis","EXACT_RATE_AGREEMENT"),
    ("vendor_numeric_conflict_reconciled",True),("vendor_numeric_conflict_reconciled",0),
    ("final_paid_rate_verified",True),("source_precedence_policy",{"sha256":"9"*64})])
def test_r4_gate_synchronized_record_and_receipt_tamper_cannot_change_frozen_basis(tmp_path,monkeypatch,field,value):
    task,records,expected=_r4_gate_fixture(tmp_path,monkeypatch)
    records[0][field]=value;_r3_update_saved_record(task,records[0])
    task.write("ACCOUNT_STATUS.json",dict(attempts=2,records=records))
    with pytest.raises(ValueError,match="R4_CONTROL_RECORD_QUALIFICATION_BASIS_CHANGED"):
        continuation.control_gate("FAKE_ONLY",continuation.R4_STAGE)
    assert not task.out("CONTROL_QUALIFICATION_GATE.json").exists()

@pytest.mark.parametrize("field",["vendor_numeric_conflict_reconciled","final_paid_rate_verified"])
@pytest.mark.parametrize("value",[0,None])
def test_r4_saved_receipt_false_fields_require_exact_false(tmp_path,monkeypatch,field,value):
    task,records,expected=_r4_gate_fixture(tmp_path,monkeypatch)
    saved=task.read(records[0]["receipt"]);saved[field]=value
    task.write(records[0]["receipt"],saved)
    records[0]["receipt_sha256"]=continuation.digest(task.out(records[0]["receipt"]))
    assert records[0][field] is False
    task.write("ACCOUNT_STATUS.json",dict(attempts=2,records=records))
    with pytest.raises(ValueError,match="R4_CONTROL_SAVED_QUALIFICATION_BASIS_CHANGED"):
        continuation.control_gate("FAKE_ONLY",continuation.R4_STAGE)
    assert not task.out("CONTROL_QUALIFICATION_GATE.json").exists()
