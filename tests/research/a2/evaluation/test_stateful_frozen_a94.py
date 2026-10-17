"""Thin A94 controller tests using synthetic policy metadata and owner spies.

No model/market reader, fitted object, provider, account ledger or real2026 input.
The existing shared account's pure admission checker is exercised by the spy.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace
import pandas as pd
import numpy as np
import pytest
from scripts.research.a2.evaluation import frozen_test_authority as authority
from scripts.research.a2.evaluation import frozen_a94_profile as profile
from scripts.research.a2.evaluation import stateful_frozen_a94 as seam


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    rows = []
    for i in range(94):
        cost = 5 if i in (53, 54) else 20 if i in (55, 56) else 10
        candidate_id = "C" + str(i)
        spec = dict(candidate_id=candidate_id, scientific_tuple_sha256=hashlib.sha256(candidate_id.encode()).hexdigest(),
            action="raw", action_cost_mode="blind", control="none", gross="fixed", risk="diag20_reference",
            forecast="none", value_model="ridge", execution_friction=dict(authority="HYPOTHETICAL_RESEARCH_SCENARIO",
                benchmark="NEXT_RAW_OPEN", fee_bps=0, kind="FIXED_ADVERSE_OPEN_SLIPPAGE", one_way_bps=cost,
                scenario_id="ADVERSE_OPEN_" + str(cost) + "BPS_USD3000"))
        rows.append(dict(candidate_id=candidate_id, source_group="OLD57" if i < 57 else "NEW37",
            specification=spec, scientific_tuple_sha256=spec["scientific_tuple_sha256"]))
    path = tmp_path / "synthetic_inventory.json"
    path.write_text(json.dumps(dict(candidates=rows),sort_keys=True),encoding="utf-8")
    inventory_ref = dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    # One original-risk candidate makes silent fallback testable without models.
    rows[0]["specification"].update(gross="volatility_targeting",risk="OAS")
    path.write_text(json.dumps(dict(candidates=rows),sort_keys=True),encoding="utf-8")
    inventory_ref=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    sources={}
    for key in authority.SOURCE_GROUPS:
        f=tmp_path/(key+".json");f.write_text(json.dumps(dict(synthetic=True,role=key)),encoding="utf-8")
        sources[key]=dict(path=str(f),sha256=hashlib.sha256(f.read_bytes()).hexdigest())
    new_ids=[r["candidate_id"] for r in rows if r["source_group"]=="NEW37"]
    def synthetic_roles(cid):
        n=int(cid[1:])
        return ("R10:HAZARD",) if n>=89 else ("R6:duration",) if n>=86 else ("R10:ENTRY","R10:INCUMBENT") if n>=57 else ()
    monkeypatch.setattr(profile,"required_action_roles",synthetic_roles,raising=False)
    dates=pd.to_datetime(["2026-01-05","2026-01-06"])
    def rebind(actions=None,sid=None,*,ready=None,include_probe=True,include_coverage=True):
        selected=tuple(r["candidate_id"] for r in rows) if ready is None else tuple(ready)
        active_new=[cid for cid in new_ids if cid in selected]
        actions=({cid:{d:[] for d in dates} for cid in active_new} if actions is None else actions)
        sid={} if sid is None else sid
        payload=[dict(candidate_id=cid,sessions=[dict(signal_date=str(pd.Timestamp(d).date()),proposals=list(records))
            for d,records in sorted(actions[cid].items())]) for cid in active_new]
        sidrows=sorted([[str(pd.Timestamp(d).date()),ticker,value] for (d,ticker),value in sid.items()])
        cost=lambda value:hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(",",":")).encode()).hexdigest()
        proof=dict(source_ref=sources["action_inputs"],new_fit_count=0,future_unmatured_probe_outcomes_read=0,
            outcome_columns_in_model_features=0,matured_probe_state=dict(source_ref=sources["action_inputs"],
                as_of_utc="2026-10-07T18:42:01.905856Z",key_sha256=cost([]),
                causal_rule="previous_probe_mature_date < current_signal_date",
                prior_probe_mature_before_current_decision=True),candidate_ids=active_new,
            decision_dates=[str(d.date()) for d in dates],action_packets_sha256=cost(payload),sid_by_key_sha256=cost(sidrows),
            computed_sessions={cid:{str(d.date()):dict(status="COMPUTED_WITH_PROPOSALS" if actions[cid][d] else "COMPUTED_NO_PROPOSALS",
                proposal_count=len(actions[cid][d])) for d in dates} for cid in active_new})
        if not include_probe:proof.pop("matured_probe_state")
        qualification=dict(task_id=profile.TASK,source_refs=sources)
        if include_coverage:qualification["action_packet_coverage"]=proof
        qpath=tmp_path/"source_qualification.json";qpath.write_text(json.dumps(qualification,sort_keys=True),encoding="utf-8")
        qref=dict(path=str(qpath),sha256=hashlib.sha256(qpath.read_bytes()).hexdigest())
        ready_scope={} if ready is None else dict(source_ready_policy_ids=list(selected))
        provenance=json.dumps(dict(**ready_scope,task_id=profile.TASK,candidate_manifest_ref=inventory_ref,source_qualification_ref=qref,
            source_refs=sources,candidate_bindings=[{k:r[k] for k in ("candidate_id","scientific_tuple_sha256","specification")} for r in rows]),sort_keys=True)
        admitted=authority.ValidatedDescriptiveAuthority(profile.TASK,"COMMON",dates[0],dates[-1],
            pd.Timestamp("2026-10-07T18:42:01.905856Z"),pd.Timestamp("2023-01-01"),
            tuple(r["candidate_id"] for r in rows),provenance,authority._SEAL)
        candidates=[deepcopy(r["specification"]) for r in rows if r["candidate_id"] in selected]
        monkeypatch.setattr(profile,"_roots",lambda:(tmp_path.resolve(),))
        return SimpleNamespace(rows=rows,inventory_path=path,admitted=admitted,candidates=candidates,
            batches=seam.prepare_batches(admitted,candidates),rebind=rebind,action_packets=actions,sid_by_key=sid,
            qualification=qualification,qpath=qpath)
    return rebind()



class SpyOverlay:
    calls = []
    mutate_constructor = False
    mutate_tick = False
    def __init__(self,candidates,*args,**kwargs):
        self.candidates=candidates
        self.descriptive_evaluation_authority=kwargs["descriptive_evaluation_authority"]
        self.kwargs=kwargs;self.audit=[]
        self.action_packets=kwargs.get("action_packets");self.sid_by_key=kwargs.get("sid_by_key")
        self.raw=SimpleNamespace(candidates=candidates,descriptive_evaluation_authority=self.descriptive_evaluation_authority)
        self.calls.append(self)
        if self.mutate_constructor:self.candidates[0]["risk"]="changed_by_constructor"
    def __call__(self,di,ctx):
        for c in self.candidates:
            authority.require_descriptive_decision(self.descriptive_evaluation_authority,ctx.signal_date,c["candidate_id"])
        if self.mutate_tick:self.candidates[0]["control"]="changed_inside_tick"
        self.audit.append(di)
        return "ORIGINAL_OWNER_TARGET"


@pytest.fixture
def owner_spies(monkeypatch):
    old=type("OldSpy",(SpyOverlay,),dict(calls=[],mutate_constructor=False,mutate_tick=False))
    new=type("NewSpy",(SpyOverlay,),dict(calls=[],mutate_constructor=False,mutate_tick=False))
    monkeypatch.setattr(seam,"StatefulOverlay",old);monkeypatch.setattr(seam,"FinalActionOverlay",new)
    state=SimpleNamespace(old=old,new=new,calls=[],before_tick=None,accepted_targets=[])
    def original_replay(market,candidates,packets,top,qualified,vol,account,**kwargs):
        state.calls.append(dict(market=market,candidates=candidates,packets=packets,top=top,qualified=qualified,
            vol=vol,account=account,kwargs=kwargs))
        authority.validate_descriptive_account(kwargs["descriptive_evaluation_authority"],market.dates,
            [c["candidate_id"] for c in candidates],account,kwargs["execution_friction"])
        overlay=kwargs["policy_factory"](candidates,packets,top,qualified,vol,
            risk_provider=kwargs["risk_provider"],descriptive_evaluation_authority=kwargs["descriptive_evaluation_authority"])
        if state.before_tick:state.before_tick(overlay)
        for di,date in enumerate(market.dates):
            target=overlay(di,SimpleNamespace(signal_date=date))
            state.accepted_targets.append(target)
        return "ORIGINAL_REPLAY",dict(gross=overlay.audit)
    monkeypatch.setattr(seam.replay,"execute_market",original_replay)
    return state


def inputs(batch):
    return dict(market=SimpleNamespace(dates=pd.to_datetime(["2026-01-05","2026-01-06"])),
        packets=object(),top=object(),qualified=object(),vol=object(),account=dict(initial_nav=3000),
        stock_present=object(),raw_selector_present=object(),risk_provider=lambda *args:None,
        account_source_kwargs=dict(events=("synthetic_source_event",),known_at={"event":"2026-01-04"},
            unsupported=(),entitlement_enabled=True,entitlement_events=(),
            entitlement_security_tickers={"synthetic_sid":"S"},entitlement_source_binding={"synthetic":True}),
        action_packets={cid:{d:[] for d in pd.to_datetime(["2026-01-05","2026-01-06"])} for cid in batch.candidate_ids} if batch.source_group=="NEW37" else None,
        sid_by_key={} if batch.source_group=="NEW37" else None)


def test_all94_grouped_only_by_original_inventory_and_full_cost(prepared):
    batches=prepared.batches
    assert len(batches)==4
    assert {(b.source_group,b.execution_friction["one_way_bps"]):len(b.candidate_ids) for b in batches}=={
        ("OLD57",10):53,("OLD57",5):2,("OLD57",20):2,("NEW37",10):37}
    assert sum(len(b.candidate_ids) for b in batches)==94
    assert {i for b in batches for i in b.candidate_ids}==set(prepared.admitted.allowed_path_ids)
    for batch in batches:
        assert batch.scoped_authority.runtime_policy_ids==batch.candidate_ids
        assert batch.candidates[0] is not prepared.candidates[int(batch.candidate_ids[0][1:])]


@pytest.mark.parametrize("index",range(4))
def test_original_replay_authority_candidates_and_fixed_overlay_forwarded(prepared,owner_spies,index):
    batch=prepared.batches[index];given=inputs(batch)
    result=seam.execute_batch(batch,**given)
    assert result==("ORIGINAL_REPLAY",dict(gross=[0,1]))
    call=owner_spies.calls[0]
    assert call["candidates"] is batch.candidates
    for name in ("market","packets","top","qualified","vol"):
        assert call[name] is given[name]
    assert call["account"]==given["account"] and call["account"] is not given["account"]
    assert call["kwargs"]["descriptive_evaluation_authority"] is batch.scoped_authority
    assert call["kwargs"]["execution_friction"]==batch.execution_friction
    assert call["kwargs"]["events"]==given["account_source_kwargs"]["events"]
    assert call["kwargs"]["entitlement_source_binding"]==given["account_source_kwargs"]["entitlement_source_binding"]
    selected=owner_spies.old if batch.source_group=="OLD57" else owner_spies.new
    other=owner_spies.new if batch.source_group=="OLD57" else owner_spies.old
    assert len(selected.calls)==1 and not other.calls
    if batch.source_group=="NEW37":
        assert selected.calls[0].kwargs["resource_decoder"] is seam.decode_resource_proposals
        assert selected.calls[0].kwargs["action_packets"] is not given["action_packets"]
        assert selected.calls[0].kwargs["sid_by_key"] is not given["sid_by_key"]


@pytest.mark.parametrize("field",["risk","control","execution_friction"])
def test_same_id_initial_spec_changes_rejected(prepared,field):
    changed=deepcopy(prepared.candidates)
    if field=="execution_friction":changed[0][field]["one_way_bps"]=5
    else:changed[0][field]="changed_while_same_id_and_digest"
    with pytest.raises(ValueError,match="FULL_SPEC_CHANGED"):
        seam.prepare_batches(prepared.admitted,changed)


def test_external_candidate_mutation_cannot_change_owned_snapshot(prepared,owner_spies):
    prepared.candidates[0]["risk"]="caller_mutated_after_prepare"
    assert prepared.batches[0].candidates[0]["risk"]=="OAS"
    assert seam.execute_batch(prepared.batches[0],**inputs(prepared.batches[0]))[0]=="ORIGINAL_REPLAY"


@pytest.mark.parametrize("mutation",["risk","cost","friction_copy"])
def test_prepared_snapshot_mutation_rejected_before_owner_call(prepared,owner_spies,mutation):
    batch=prepared.batches[0]
    if mutation=="risk":batch.candidates[0]["risk"]="PCA"
    elif mutation=="cost":batch.candidates[0]["execution_friction"]["one_way_bps"]=20
    else:batch.execution_friction["one_way_bps"]=20
    with pytest.raises(ValueError,match="SNAPSHOT_CHANGED|FRICTION_CHANGED|CUSTODY_CHANGED"):
        seam.execute_batch(batch,**inputs(batch))
    assert owner_spies.calls==[]


@pytest.mark.parametrize("which",["OLD57","NEW37"])
def test_constructor_cannot_mutate_same_candidate_list(prepared,owner_spies,which):
    batch=next(b for b in prepared.batches if b.source_group==which)
    selected=owner_spies.old if which=="OLD57" else owner_spies.new
    selected.mutate_constructor=True
    with pytest.raises(ValueError,match="SNAPSHOT_CHANGED"):
        seam.execute_batch(batch,**inputs(batch))
    assert owner_spies.accepted_targets==[]


@pytest.mark.parametrize("which",["OLD57","NEW37"])
def test_mutation_inside_tick_rejected_before_target_reaches_account(prepared,owner_spies,which):
    batch=next(b for b in prepared.batches if b.source_group==which)
    selected=owner_spies.old if which=="OLD57" else owner_spies.new
    selected.mutate_tick=True
    with pytest.raises(ValueError,match="SNAPSHOT_CHANGED"):
        seam.execute_batch(batch,**inputs(batch))
    assert owner_spies.accepted_targets==[]


@pytest.mark.parametrize("mutation",["outer_collection","raw_collection","authority"])
def test_actual_overlay_collection_and_authority_cannot_be_swapped(prepared,owner_spies,mutation):
    batch=prepared.batches[-1]
    def change(wrapper):
        original=wrapper._overlay
        if mutation=="outer_collection":original.candidates=tuple(deepcopy(batch.candidates))
        elif mutation=="raw_collection":original.raw.candidates=tuple(deepcopy(batch.candidates))
        else:original.descriptive_evaluation_authority=prepared.admitted
    owner_spies.before_tick=change
    with pytest.raises(ValueError,match="COLLECTION_CHANGED"):
        seam.execute_batch(batch,**inputs(batch))
    assert owner_spies.accepted_targets==[]


def test_tick_checks_only_batch_in_memory_without_metadata_io(prepared,owner_spies,monkeypatch):
    def fail(*args,**kwargs):raise AssertionError("no metadata or file IO after preparation")
    monkeypatch.setattr(profile,"_document",fail);monkeypatch.setattr(authority,"_physical",fail)
    counts=[];original=seam._canonical
    def observed(value):
        if isinstance(value,tuple):counts.append(len(value))
        return original(value)
    monkeypatch.setattr(seam,"_canonical",observed)
    batch=prepared.batches[0]
    seam.execute_batch(batch,**inputs(batch))
    assert counts and set(counts)=={53}


@pytest.mark.parametrize("keyword",["policy_factory","resource_decoder","descriptive_evaluation_authority","execution_friction"])
def test_no_caller_factory_decoder_authority_or_cost_override(prepared,owner_spies,keyword):
    batch=prepared.batches[-1];given=inputs(batch);given[keyword]=object()
    with pytest.raises(TypeError):seam.execute_batch(batch,**given)
    assert owner_spies.calls==[]


@pytest.mark.parametrize("change",["override","ca_disabled","ca_unbound","actions_missing","sid_missing"])
def test_original_ca_and_new_action_inputs_remain_explicit(prepared,owner_spies,change):
    batch=prepared.batches[-1];given=inputs(batch)
    if change=="override":given["account_source_kwargs"]["research_quote_domain"]={}
    if change=="ca_disabled":given["account_source_kwargs"]["entitlement_enabled"]=False
    if change=="ca_unbound":given["account_source_kwargs"]["entitlement_source_binding"]=None
    if change=="actions_missing":given["action_packets"].pop(batch.candidate_ids[0])
    if change=="sid_missing":given["sid_by_key"]=None
    with pytest.raises(ValueError):seam.execute_batch(batch,**given)
    assert owner_spies.calls==[]


def test_all_source_ready_policies_required_and_cannot_pickle(prepared):
    with pytest.raises(ValueError,match="SOURCE_READY_POLICIES"):
        seam.prepare_batches(prepared.admitted,prepared.candidates[:-1])
    with pytest.raises(TypeError):prepared.batches[0].__reduce__()


@pytest.mark.parametrize("mutation",["route","spec_and_commitment","authority","candidate_collection","friction"])
def test_dataclass_replace_cannot_rebind_independent_batch_custody(prepared,owner_spies,mutation):
    batch=prepared.batches[-1]
    if mutation=="route":forged=replace(batch,source_group="OLD57")
    elif mutation=="spec_and_commitment":
        candidates=tuple(deepcopy(batch.candidates));candidates[0]["risk"]="PCA"
        forged=replace(batch,candidates=candidates,canonical_specs=seam._canonical(candidates))
    elif mutation=="authority":forged=replace(batch,scoped_authority=replace(batch.scoped_authority,end=pd.Timestamp("2027-01-01")))
    elif mutation=="candidate_collection":forged=replace(batch,candidates=tuple(deepcopy(batch.candidates)))
    else:forged=replace(batch,execution_friction=dict(batch.execution_friction,one_way_bps=5))
    with pytest.raises(ValueError,match="CUSTODY_CHANGED"):
        seam.execute_batch(forged,**inputs(forged))
    assert not owner_spies.calls
    with pytest.raises(TypeError):batch._seal._bound=()


@pytest.mark.parametrize("mutation",["missing_day","missing_terminal_day","empty_uncomputed","new_payload","sid_payload"])
def test_action_missing_is_distinct_from_computed_empty(prepared,owner_spies,mutation):
    batch=prepared.batches[-1];given=inputs(batch);first=batch.candidate_ids[0]
    if mutation=="missing_day":given["action_packets"][first].pop(pd.Timestamp("2026-01-05"))
    elif mutation=="missing_terminal_day":given["action_packets"][first].pop(pd.Timestamp("2026-01-06"))
    elif mutation=="empty_uncomputed":given["action_packets"][first]={}
    elif mutation=="new_payload":given["action_packets"][first][pd.Timestamp("2026-01-05")]=[{"unbound":True}]
    else:given["sid_by_key"][(pd.Timestamp("2026-01-05"),"S") ]="swapped_sid"
    with pytest.raises(ValueError,match="ACTION_COMPUTATION"):
        seam.execute_batch(batch,**given)
    assert not owner_spies.calls


@pytest.mark.parametrize("value",[None,object()])
def test_nonfixed_candidate_requires_original_callable_risk_provider(prepared,owner_spies,value):
    batch=prepared.batches[0];given=inputs(batch);given["risk_provider"]=value
    with pytest.raises(ValueError,match="FROZEN_RISK_PROVIDER"):
        seam.execute_batch(batch,**given)
    assert not owner_spies.calls


def test_missing_computation_proof_rejected_during_preparation(prepared,monkeypatch):
    original=profile._document
    def missing(ref):
        value=original(ref)
        if ref["path"]==str(prepared.qpath):value.pop("action_packet_coverage")
        return value
    monkeypatch.setattr(profile,"_document",missing)
    with pytest.raises(ValueError,match="COMPUTATION_COVERAGE"):
        seam.prepare_batches(prepared.admitted,prepared.candidates)


def test_real_original_overlay_and_engine_apply_nonempty_action(prepared):
    # Original reviewed synthetic_engine shape:20 Raw entries plus one outsider.
    # This test uses original numerical owners, not the owner_spies fixture.
    dates=pd.to_datetime(["2026-01-05","2026-01-06"])
    names=["S%02d"%i for i in range(20)]+["OUTSIDE"]
    shape=(2,len(names));mask=np.ones(shape,bool);top=mask.copy();top[:,-1]=False
    market=seam.replay.MarketArrays(dates,names,np.full(shape,10.),np.full(shape,10.),input_present=mask.copy(),
        new_buy_eligible=top.copy(),signal_asof=[d.tz_localize("America/New_York")+pd.Timedelta(hours=16) for d in dates])
    ids=prepared.batches[-1].candidate_ids
    actions={cid:{d:[] for d in dates} for cid in ids}
    actions[ids[0]][dates[0]]=[dict(kind="BUY",decision="SKIP",ticker="S00",entrant=None,
        security_id="SID_S00",entrant_security_id=None,source_order=0,source_score=-1.,sample_id="SYNTHETIC_SKIP",local_resolver="R6")]
    sid={(d,t):"SID_"+t for d in dates for t in names}
    rebound=prepared.rebind(actions,sid);batch=rebound.batches[-1]
    account=dict(base_currency="USD",initial_nav=3000.,initial_cash=3000.,initial_holdings=[],
        fractional_shares=True,integer_share_rounding=False,transaction_cost_bps=0.,cash_interest=0.,
        financing=False,borrowed_cash=False,long_only=True,max_weight=1.,max_positions=20,max_invested=1.,capacity_fraction=None)
    security={"SID_"+t:t for t in names}
    source=dict(entitlement_enabled=True,entitlement_events=(),entitlement_security_tickers=security,
        entitlement_source_binding=dict(status="SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND",source_fingerprint="d"*64,
            quantity_coordinate="RAW_OLD_SECURITY_SHARES",event_fingerprints=[],security_tickers=security))
    result,frames=seam.execute_batch(batch,market=market,packets={"ridge":dict(mu=np.full(shape,.03),
        sigma=np.full(2,.001),lineage=np.full(2,"SYNTHETIC"))},top=top,qualified=mask.copy(),vol=np.full(shape,.02),
        account=account,stock_present=mask.copy(),raw_selector_present=mask.copy(),account_source_kwargs=source,
        action_packets=actions,sid_by_key=sid)
    fills=frames["fills"]
    assert len(fills)>0
    assert not ((fills.path_id==ids[0])&(fills.ticker=="S00")&(fills.side=="BUY")).any()
    assert ((fills.path_id==ids[1])&(fills.ticker=="S00")&(fills.side=="BUY")).any()
    assert fills.execution_date.eq(dates[1]).all()
    terminal=frames["actions"].loc[frames["actions"].signal_date.eq(dates[-1])]
    assert set(terminal.path_id)==set(ids) and terminal.planned_execution_date.isna().all()
    assert result.metadata["annual_reset"] is False
    assert result.metadata["entitlement_lifecycle_enabled"] is True
    assert set(frames["daily"].path_id)==set(ids)
    assert result.metadata["descriptive_evaluation_authority"]["task_id"]==profile.TASK


@pytest.mark.parametrize("mutation",["caller_actions","caller_sid","private_actions","private_sid","map_swap"])
def test_action_proof_stays_bound_after_initial_coverage(prepared,owner_spies,mutation):
    batch=prepared.batches[-1];given=inputs(batch)
    def after_coverage(wrapper):
        if mutation=="caller_actions":given["action_packets"][batch.candidate_ids[0]][pd.Timestamp("2026-01-05")].append({"unbound":True})
        elif mutation=="caller_sid":given["sid_by_key"][(pd.Timestamp("2026-01-05"),"S") ]="NEW_SID"
        elif mutation=="map_swap":wrapper._overlay.action_packets=given["action_packets"]
        else:
            original=wrapper._overlay.__class__.__call__
            def modify(self,di,ctx):
                result=original(self,di,ctx)
                if mutation=="private_actions":self.kwargs["action_packets"][batch.candidate_ids[0]][ctx.signal_date].append({"unbound":True})
                else:self.kwargs["sid_by_key"][(ctx.signal_date,"S") ]="NEW_SID"
                return result
            wrapper._overlay.__class__.__call__=modify
    owner_spies.before_tick=after_coverage
    with pytest.raises(ValueError,match="INPUT_SNAPSHOT_CHANGED"):
        seam.execute_batch(batch,**given)
    assert owner_spies.accepted_targets==[]


@pytest.mark.parametrize("change",["new_fit_count","future_unmatured_probe_outcomes_read",
    "outcome_columns_in_model_features","causal_rule","prior_probe_mature_before_current_decision",
    "source_ref","key_sha256","naive_asof","future_asof"])
def test_causal_probe_qualification_rejects_noncausal_or_unbound_metadata(prepared,monkeypatch,change):
    original=profile._document
    def altered(ref):
        value=deepcopy(original(ref))
        if ref["path"]==str(prepared.qpath):
            proof=value["action_packet_coverage"];probe=proof["matured_probe_state"]
            if change in ("new_fit_count","future_unmatured_probe_outcomes_read","outcome_columns_in_model_features"):
                proof[change]=1
            elif change=="causal_rule":probe[change]="mature_by_final_asof_only"
            elif change=="prior_probe_mature_before_current_decision":probe[change]=False
            elif change=="source_ref":probe[change]=dict(probe[change],sha256="0"*64)
            elif change=="key_sha256":probe[change]="not_a_bound_key_digest"
            elif change=="naive_asof":probe["as_of_utc"]="2026-10-07T18:42:01"
            else:probe["as_of_utc"]="2026-10-08T18:42:01Z"
        return value
    monkeypatch.setattr(profile,"_document",altered)
    with pytest.raises(ValueError,match="COMPUTATION_COVERAGE|CAUSAL_PROBE_BINDING"):
        seam.prepare_batches(prepared.admitted,prepared.candidates)


def test_causal_probe_metadata_allows_past_matured_state_without_blanket_label_zero(prepared,monkeypatch):
    original=profile._document
    def historical(ref):
        value=deepcopy(original(ref))
        if ref["path"]==str(prepared.qpath):
            proof=value["action_packet_coverage"]
            proof["matured_probe_state"]["qualified_matured_probe_count"]=7
            proof["labels_read"]=7  # Historical diagnostics are not a no-label rule.
        return value
    monkeypatch.setattr(profile,"_document",historical)
    assert len(seam.prepare_batches(prepared.admitted,prepared.candidates))==4



def test_all86_h5_free_policies_prepare_with_original_costs_without_probe_claim(prepared,owner_spies):
    ready=["C"+str(i) for i in range(86)]
    accepted=prepared.rebind(ready=ready,include_probe=False)
    assert sum(len(b.candidate_ids) for b in accepted.batches)==86
    assert len(accepted.admitted.allowed_path_ids)==94
    assert {(b.source_group,b.execution_friction["one_way_bps"]):len(b.candidate_ids) for b in accepted.batches}=={
        ("OLD57",10):53,("OLD57",5):2,("OLD57",20):2,("NEW37",10):29}
    for batch in accepted.batches:assert seam.execute_batch(batch,**inputs(batch))[0]=="ORIGINAL_REPLAY"
    assert len(owner_spies.calls)==4


def test_old57_only_needs_no_action_packet_or_probe_coverage(prepared,owner_spies):
    accepted=prepared.rebind(ready=["C"+str(i) for i in range(57)],include_coverage=False)
    assert len(accepted.batches)==3
    for batch in accepted.batches:
        assert batch.source_group=="OLD57"
        assert seam.execute_batch(batch,**inputs(batch))[0]=="ORIGINAL_REPLAY"


@pytest.mark.parametrize("ready",[["C"+str(i) for i in range(87)],["C89"]])
def test_ready_h5_candidate_cannot_execute_without_matured_probe_proof(prepared,ready):
    with pytest.raises(ValueError,match="CAUSAL_PROBE_BINDING"):
        prepared.rebind(ready=ready,include_probe=False)


def test_h5_free_new29_still_requires_complete_bound_action_computation(prepared):
    with pytest.raises(ValueError,match="COMPUTATION_COVERAGE"):
        prepared.rebind(ready=["C"+str(i) for i in range(86)],include_coverage=False)


@pytest.mark.parametrize("change",["blocked","missing_ready","wrong_order"])
def test_subset_cannot_add_blocked_or_omit_or_reorder_ready_policy(prepared,change):
    accepted=prepared.rebind(ready=["C"+str(i) for i in range(86)],include_probe=False)
    candidates=deepcopy(accepted.candidates)
    if change=="blocked":candidates.append(deepcopy(prepared.rows[86]["specification"]))
    elif change=="missing_ready":candidates.pop()
    else:candidates[-2:]=reversed(candidates[-2:])
    with pytest.raises(ValueError,match="SOURCE_READY_POLICIES"):
        seam.prepare_batches(accepted.admitted,candidates)


def test_partial_ready_batch_still_checks_full94_inventory_identity(prepared,monkeypatch):
    accepted=prepared.rebind(ready=["C0"],include_coverage=False)
    original=profile._document
    def changed(ref):
        value=deepcopy(original(ref))
        if ref["path"]==str(accepted.inventory_path):value["candidates"].pop()
        return value
    monkeypatch.setattr(profile,"_document",changed)
    with pytest.raises(ValueError,match="ORIGINAL_INVENTORY"):
        seam.prepare_batches(accepted.admitted,accepted.candidates)


def test_partial_ready_actions_keep_exact_current_batch_payload_binding(prepared,owner_spies):
    accepted=prepared.rebind(ready=["C"+str(i) for i in range(86)],include_probe=False)
    batch=accepted.batches[-1];given=inputs(batch)
    given["action_packets"]["C86"]={d:[] for d in given["market"].dates}
    with pytest.raises(ValueError,match="ORIGINAL_ACTION_AND_SID"):
        seam.execute_batch(batch,**given)
    assert not owner_spies.calls


@pytest.fixture
def all_action_calendar(prepared, monkeypatch):
    rows=deepcopy([prepared.rows[0],prepared.rows[57]])
    for i,row in enumerate(rows):
        row.update(source_group="ORIGINAL_A" if i==0 else "R10",runtime_owner="STATEFUL_OVERLAY" if i==0 else "FINAL_ACTION_OVERLAY",
            required_action_roles=[] if i==0 else ["R10:ENTRY","R10:INCUMBENT"],
            dependency_closure=dict(status="COMPLETE",state_ids=[]),lookback=None)
    roles={r["candidate_id"]:tuple(r["required_action_roles"]) for r in rows}
    monkeypatch.setattr(profile,"required_action_roles",lambda cid,**kw:roles[cid])
    prepared.inventory_path.write_text(json.dumps(dict(candidates=rows),sort_keys=True),encoding="utf8")
    dates=pd.DatetimeIndex(["2026-01-05","2026-01-06","2026-01-07"])
    cid=rows[1]["candidate_id"];packets={cid:{d:[] for d in dates}};sid={(d,"X"):"CUSIP:X" for d in dates}
    proof=deepcopy(prepared.qualification["action_packet_coverage"])
    proof.update(candidate_ids=[cid],decision_dates=[str(d.date()) for d in dates],
        action_packets_sha256=seam._digest([dict(candidate_id=cid,sessions=[dict(signal_date=str(d.date()),proposals=[]) for d in dates])]),
        sid_by_key_sha256=seam._digest(seam._sid_payload(sid)),
        computed_sessions={cid:{str(d.date()):dict(status="COMPUTED_NO_PROPOSALS",proposal_count=0) for d in dates}})
    q=deepcopy(prepared.qualification);q.update(task_id=profile.ALL_TASK,action_packet_coverage=proof)
    prepared.qpath.write_text(json.dumps(q,sort_keys=True),encoding="utf8")
    prov=json.loads(prepared.admitted.provenance_json)
    prov.update(task_id=profile.ALL_TASK,candidate_manifest_ref=dict(path=str(prepared.inventory_path),sha256=hashlib.sha256(prepared.inventory_path.read_bytes()).hexdigest()),
        source_qualification_ref=dict(path=str(prepared.qpath),sha256=hashlib.sha256(prepared.qpath.read_bytes()).hexdigest()),candidate_bindings=rows)
    auth=replace(prepared.admitted,task_id=profile.ALL_TASK,start=dates[0],end=dates[-1],allowed_path_ids=tuple(r["candidate_id"] for r in rows),
        provenance_json=json.dumps(prov),runtime_policy_ids=())
    specs=[r["specification"] for r in rows]
    full=next(b for b in seam.prepare_batches(auth,specs) if b.source_group=="FINAL_ACTION_OVERLAY")
    calendar=seam.bind_action_calendar(full,SimpleNamespace(dates=dates),packets,sid)
    random=next(b for b in seam.prepare_batches(replace(auth,start=dates[1],window_id="RANDOM_001"),specs) if b.source_group=="FINAL_ACTION_OVERLAY")
    return SimpleNamespace(full=full,random=random,calendar=calendar,packets=packets,sid=sid,dates=dates)


def test_all_a_fresh_window_projects_original_full_source_without_recomputing(all_action_calendar):
    x=all_action_calendar
    packets,sid,checks=seam._window_action_calendar(x.random,SimpleNamespace(dates=x.dates[1:]),x.calendar)
    assert packets is x.packets and sid is x.sid and set(checks)=={"2026-01-06","2026-01-07"}
    guard=seam._ActionGuard(x.random,packets,sid,checks);guard.stage(x.dates[1])
    assert set(guard.sid)=={(x.dates[1],"X")}
    assert all(set(v)=={x.dates[1]} for v in guard.actions.values())


def test_all_a_window_cannot_inherit_mutated_or_unbound_action_state(all_action_calendar):
    x=all_action_calendar
    packets,sid,checks=seam._window_action_calendar(x.random,SimpleNamespace(dates=x.dates[1:]),x.calendar)
    cid=x.random.candidate_ids[0];packets[cid][x.dates[1]].append({"mutation":True})
    with pytest.raises(ValueError,match="INPUT_SNAPSHOT_CHANGED"):
        seam._ActionGuard(x.random,packets,sid,checks).stage(x.dates[1])


def test_all_a_random_calendar_cannot_skip_internal_original_sessions(all_action_calendar):
    x=all_action_calendar
    with pytest.raises(ValueError,match="WINDOW"):
        seam._window_action_calendar(x.full,SimpleNamespace(dates=x.dates[[0,2]]),x.calendar)
    with pytest.raises(ValueError,match="CUSTODY"):
        seam._window_action_calendar(x.random,SimpleNamespace(dates=x.dates[1:]),replace(x.calendar,dates=x.calendar.dates[1:]))


def test_all_a_original_complete_packet_source_cannot_omit_a_day(all_action_calendar):
    x=all_action_calendar;cid=x.full.candidate_ids[0]
    del x.packets[cid][x.dates[0]]
    with pytest.raises(ValueError,match="PAYLOAD_CHANGED"):
        seam.bind_action_calendar(x.full,SimpleNamespace(dates=x.dates),x.packets,x.sid)


@pytest.mark.parametrize("missing", [None, np.nan, pd.NA, pd.NaT])
def test_sid_fingerprint_missing_null_keeps_source_identity_invalid(missing):
    from scripts.research.a2.training.stateful_decision import _valid_sid
    day = pd.Timestamp("2025-12-01")
    original = {(day, "UNKNOWN"): missing}
    payload = seam._sid_payload(original)
    assert payload == [["2025-12-01", "UNKNOWN", None]]
    assert original[(day, "UNKNOWN")] is missing
    assert not _valid_sid(original[(day, "UNKNOWN")])
    assert seam._digest(payload) == seam._digest([["2025-12-01", "UNKNOWN", None]])


def test_sid_fingerprint_preserves_existing_valid_payload_hash_exactly():
    day = pd.Timestamp("2025-12-01")
    sid = {(day, "ZZ"): "CUSIP:26614N201", (day, "AA"): "CUSIP:26614N102"}
    legacy = [["2025-12-01", "AA", "CUSIP:26614N102"], ["2025-12-01", "ZZ", "CUSIP:26614N201"]]
    encoded = json.dumps(legacy, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    assert seam._sid_payload(sid) == legacy
    assert seam._digest(seam._sid_payload(sid)) == hashlib.sha256(encoded).hexdigest()
    changed = dict(sid); changed[(day, "AA")] = "CUSIP:26614N201"
    assert seam._digest(seam._sid_payload(changed)) != hashlib.sha256(encoded).hexdigest()


@pytest.mark.parametrize("value", [np.inf, -np.inf])
def test_sid_fingerprint_keeps_nonmissing_infinite_value_rejected(value):
    with pytest.raises(ValueError, match="Out of range float"):
        seam._digest(seam._sid_payload({(pd.Timestamp("2025-12-01"), "S"): value}))


def test_action_guard_preserves_missing_source_and_rejects_valid_sid_change():
    day = pd.Timestamp("2025-12-01")
    sid = {(day, "UNKNOWN"): np.nan, (day, "VALID"): "SID_VALID"}
    actions = {"C": {day: []}}
    commitment = (seam._digest([dict(candidate_id="C", proposals=[])]), seam._digest(seam._sid_payload(sid)))
    guard = seam._ActionGuard(SimpleNamespace(candidate_ids=("C",)), actions, sid, {str(day.date()): commitment})
    guard.stage(day)
    assert pd.isna(sid[(day, "UNKNOWN")]) and pd.isna(guard.sid[(day, "UNKNOWN")])
    guard.sid[(day, "UNKNOWN")] = None
    guard.verify()  # Both forms still mean missing identity; no valid SID was inferred.
    guard.sid[(day, "VALID")] = "A_DIFFERENT_VALID_SID"
    with pytest.raises(ValueError, match="INPUT_SNAPSHOT_CHANGED"):
        guard.verify()


@pytest.mark.parametrize("missing", [None, np.nan, pd.NA, pd.NaT])
@pytest.mark.parametrize("role", ["ticker", "entrant"])
def test_original_action_overlay_still_rejects_missing_identity(missing, role):
    day = pd.Timestamp("2025-12-01")
    keys = {(day, "S"): "SID_S", (day, "E"): "SID_E"}
    keys[(day, "S" if role == "ticker" else "E")] = missing
    record = dict(ticker="S", security_id="SID_S", entrant="E", entrant_security_id="SID_E",
                  kind="REPLACE", decision="REPLACE", source_order=0)
    overlay = object.__new__(seam.FinalActionOverlay)
    overlay.candidates = [dict(candidate_id="C")]
    overlay.descriptive_evaluation_authority = None
    overlay.top = overlay.qualified = np.ones((1, 2), bool)
    overlay.action_packets = {"C": {day: [record]}}
    overlay.sid_by_key = keys
    overlay.action_audit = []; overlay.audit = []
    received = []
    def decoder(records, **kwargs):
        received.append(records)
        return dict(accepted=records, conflicts=[])
    overlay.resource_decoder = decoder
    class Raw:
        audit = []
        def __call__(self, *args):
            return SimpleNamespace(weights=np.full((1, 2), .05), explicit_mask=np.ones((1, 2), bool))
    overlay.raw = Raw()
    context = SimpleNamespace(signal_date=day, tickers=["S", "E"], decision_mask=np.ones((1, 2), bool),
                              current_units=np.array([[1., 0.]]), buy_allowed=np.ones((1, 2), bool))
    result = overlay(0, context)
    assert received == [[]] and overlay.action_audit == []
    np.testing.assert_array_equal(result.weights, np.full((1, 2), .05))
    assert keys[(day, "S" if role == "ticker" else "E")] is missing
