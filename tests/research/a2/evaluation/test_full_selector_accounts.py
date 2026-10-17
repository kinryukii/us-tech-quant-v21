"""Synthetic-only account source and finite policy integration checks."""
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.data import full_selector_account_inputs as inp
from scripts.research.a2.evaluation import full_selector_accounts as call
from scripts.research.a2.evaluation import continuous_research_account as account
from scripts.v22 import corporate_action_transition_r1 as ca

def old_fixture():
    path=inp.REPO/"tests/research/a2/evaluation/test_continuous_account_entitlements.py"
    spec=importlib.util.spec_from_file_location("_existing_account_synthetic_fixture",path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod


def frames(n=2):
    days=pd.DatetimeIndex(["2025-04-23","2025-04-24","2025-04-25","2025-04-28","2025-04-29"])
    names=("S","MKFG") if n==2 else tuple("T"+str(i) for i in range(n))
    keys=pd.DataFrame([dict(signal_date=d,security_uid="CUSIP:"+t,ticker=t,cusip=t)
        for d in days for t in names])
    m=pd.DataFrame([dict(path_id=p,signal_date=d,security_uid="CUSIP:"+t,ticker=t,rank=i+1)
        for p in ("Raw","HGB") for d in days for i,t in enumerate(names)])
    return days,names,keys,m


def test_small_universe_remains_five_percent_each_with_explicit_outside_pool_exit():
    days,names,k,m=frames()
    policy=call.membership_policy(k,m,("Raw","HGB"),days)
    ctx=SimpleNamespace(path_ids=("Raw","HGB"),signal_date=days[0],tickers=(*names,"OLD"),
        decision_mask=np.array([[True,False,True],[True,True,True]]))
    result=policy(0,ctx)
    assert result.weights.tolist()==[[.05,.05,0.],[.05,.05,0.]]
    assert np.array_equal(result.explicit_mask,ctx.decision_mask)
    assert result.weights.sum(axis=1).tolist()==pytest.approx([.1,.1])


def test_missing_full_pool_output_uid_swap_rank_hole_and_new_account_namespace_rejected():
    days,names,k,m=frames()
    cases=[]
    cases.append(m.drop(index=0))
    bad=m.copy();bad.loc[0,"security_uid"]="CUSIP:OTHER";cases.append(bad)
    bad=m.copy();bad.loc[0,"rank"]=3;cases.append(bad)
    for bad in cases:
        with pytest.raises(ValueError):call.membership_policy(k,bad,("Raw","HGB"),days)
    with pytest.raises(ValueError,match="FINITE_UNIQUE"):
        call.membership_policy(k,m,tuple("p"+str(i) for i in range(67)),days)


def test_twenty_names_ignore_rank21_and_never_concentrate():
    days,names,k,m=frames(21)
    # Full ranking is accepted; fixed policy consumes 1..20 without numerical scores.
    p=call.membership_policy(k,m,("Raw","HGB"),days)
    ctx=SimpleNamespace(path_ids=("Raw","HGB"),signal_date=days[0],tickers=names,
        decision_mask=np.ones((2,21),bool))
    out=p(0,ctx)
    assert out.weights[:,:20].tolist()==[[.05]*20]*2
    assert out.weights[:,20].tolist()==[0.,0.]
    assert out.weights.sum(axis=1).tolist()==pytest.approx([1.,1.])


def test_original_cusip_and_dated_share_mapping_required_without_ticker_guess():
    days,names,k,m=frames()
    mapping={"records":[dict(sid="FROZEN_RAW_TRANSPORT_CODE:US."+t,ticker=t,start="2025-01-01",
        end="2026-01-01",coordinate="RAW_ACTUAL_SHARE") for t in names]}
    projection={"rows":[dict(ticker=t,observed_decision_security_ids=[t]) for t in names]}
    links,gaps=inp.identity_links(k,mapping,projection)
    assert not gaps and len(links)==len(k)
    projection["rows"][0]["observed_decision_security_ids"].append("OTHER")
    _,gaps=inp.identity_links(k,mapping,projection)
    assert len(gaps)==len(days) and {x["ticker"] for x in gaps}=={"S"}
    projection["rows"][0]["observed_decision_security_ids"]=["OTHER"]
    _,gaps=inp.identity_links(k,mapping,projection)
    assert len(gaps)==len(days)


def test_exact_a_b_corroboration_preserves_original_a_bytes_and_cash_once():
    fx=old_fixture();cash,terminal,authority=fx.full_selector_catalogue()
    ordinary=fx.event(event_id="oldordinary",old_security_id="secS",ticker="S",
        ex_date="2025-04-25",record_date="2025-04-25",pay_date="2025-04-25",
        available_at="2025-04-24T12:00:00Z",cash_per_old_share=1.)
    same=ca.SourceBackedEntitlementEvent(**dict(ca.asdict(ordinary),event_id="corroborated"))
    b=fx.entitlement_args((cash,ordinary),{"secS":"S"})
    b["research_account_authority"]={"frozen_history_cash_admission":authority["frozen_history_cash_admission"]}
    descendant={"events":b,"ordinary_cash_event_fingerprints":{cash.event_fingerprint,ordinary.event_fingerprint}}
    # The fixture's cash and ordinary share economic key; use a different genuine ex key.
    ordinary=ca.SourceBackedEntitlementEvent(**dict(ca.asdict(ordinary),ex_date="2025-04-24",
        record_date="2025-04-24",available_at="2025-04-23T12:00:00Z"))
    same=ca.SourceBackedEntitlementEvent(**dict(ca.asdict(ordinary),event_id="corroborated"))
    b["entitlement_events"]=(cash,ordinary)
    descendant["ordinary_cash_event_fingerprints"]={cash.event_fingerprint,ordinary.event_fingerprint}
    merged,receipt=inp.combine_cash_and_terminal(descendant,(same,terminal),
        authority["terminal_source_authority"],authority["frozen_contract_ref"])
    assert len(merged["entitlement_events"])==3
    assert next(e for e in merged["entitlement_events"] if e.event_id=="corroborated")==same
    assert ordinary.event_fingerprint not in merged["research_account_authority"]["event_fingerprints"]
    assert same.event_fingerprint in merged["research_account_authority"]["ordinary_cash_event_fingerprints"]
    assert receipt["A_exact_corroborations"][0]["cash_counted_once"]
    changed=ca.SourceBackedEntitlementEvent(**dict(ca.asdict(same),cash_per_old_share=2.))
    with pytest.raises(ValueError,match="A_B_CASH_FACT_CONFLICT"):
        inp.combine_cash_and_terminal(descendant,(changed,terminal),authority["terminal_source_authority"],authority["frozen_contract_ref"])


def test_merged_source_catalogue_rejects_terminal_settlement_and_missing_authority():
    fx=old_fixture();cash,terminal,authority=fx.full_selector_catalogue()
    b=fx.entitlement_args((cash,),{"secS":"S"})
    b["research_account_authority"]={"frozen_history_cash_admission":authority["frozen_history_cash_admission"]}
    desc={"events":b,"ordinary_cash_event_fingerprints":{cash.event_fingerprint}}
    with pytest.raises(ValueError):inp.combine_cash_and_terminal(desc,(terminal,),{},authority["frozen_contract_ref"])


def test_actual_shared_ast_owner_once_cost_unknown_terminal_dual_nav_and_strict_flags(monkeypatch):
    fx=old_fixture();cash,terminal,authority=fx.full_selector_catalogue()
    days,names,k,m=frames()
    data=fx.inputs(prices=[[100.,100.]]*len(days),dates=list(days),tickers=names)
    ref=inp.DEFAULT_REFS["quote_composer"]
    # Source import only: no parent input loader/worker/account data is called.
    composer=inp._load_python(ref,"_existing_quote_composition_synthetic")
    bound=dict(reader=SimpleNamespace(run=Path("D:/synthetic/new_run"),manifest={"account_inputs":{"synthetic":True}}),
        freeze={"account_path_ids":["Raw","HGB"]},keys=k,
        identity_links=k.assign(accounting_sid="synthetic_exact_raw_share"),
        raw_identity_links=k.assign(accounting_sid="synthetic_exact_raw_share"),
        calendar=days,market=data,composer=composer,
        usable_a=np.zeros(data.open.shape,bool),source_gaps=[],
        events=dict(fx.entitlement_args((cash,terminal),{"secS":"S","secMKFG":"MKFG"}),
            research_account_authority=authority))
    # The qualifier's inherited valuation is tested by the real composed owner.
    replay,receipt,proof=call.run_fixed_accounts(bound,m,("Raw","HGB"))
    assert all(q["mechanism_accounting_consistent"] for q in receipt.values())
    assert all(q["full_window_complete"] for q in receipt.values())
    assert not replay.daily.accounting_qualified.all()
    assert replay.daily.research_accounting_qualified.all()
    assert len(proof)>0
    assert not any(replay.entitlements.loc[replay.entitlements.ticker.eq("MKFG"),"phase"].eq("CASH_PAID"))
    assert replay.daily.loc[replay.daily.date.eq(days[1]),"transaction_cost_amount"].sum()==pytest.approx(.6)
    assert replay.daily.transaction_cost_amount.sum()==pytest.approx(replay.daily.slippage_amount.sum())
    assert replay.daily.actual_cash_flow_identity_error.abs().max()<1e-8
    assert (replay.daily.TOTAL_ECONOMIC_NAV-replay.daily.LIQUID_NAV).to_numpy()==pytest.approx(
        replay.daily.receivable_value_usd.to_numpy())
    assert replay.daily.certified_nav.isna().all()
    assert replay.accounting_exceptions.reason.eq("TERMINAL_SETTLEMENT_AUTHORITY_MISSING").all()
    cancelled=replay.execution_results.loc[replay.execution_results.ticker.eq("MKFG")&replay.execution_results.status.eq("REJECTED")]
    assert len(cancelled)==2 and cancelled.reason.eq("MISSING_PRICE_ROW").all()
    assert replay.metadata["exact_unknown_terminal_exception_projection"]["exact_pre_effective_zero_fill_cancel_rows"]==2
    other=copy.deepcopy(replay)
    row=cancelled.iloc[[0]].copy();row["ticker"]="S"
    other.execution_results=pd.concat([other.execution_results,row],ignore_index=True)
    with pytest.raises(ValueError,match="FULL_WINDOW_ACCOUNT_QUALIFICATION_FAILED"):
        call.qualify_research_account(other,bound,("Raw","HGB"))
    bad=copy.deepcopy(replay);bad.accounting_exceptions["reason"]="OTHER_UNRESOLVED_SOURCE"
    with pytest.raises(ValueError,match="FULL_WINDOW_ACCOUNT_QUALIFICATION_FAILED"):
        call.qualify_research_account(bad,bound,("Raw","HGB"))


def test_scope_no_rank_repair_or_unregistered_path_and_material_exception_not_waived(monkeypatch):
    fx=old_fixture();cash,terminal,authority=fx.full_selector_catalogue()
    days,names,k,m=frames()
    with pytest.raises(ValueError,match="FROZEN_66"):
        call.run_fixed_accounts({"freeze":{"account_path_ids":["Raw"]}},m,("Raw","OTHER"))


def test_same_bytes_transport_refuses_other_source_drift_and_arbitrary_legacy_subject(monkeypatch):
    custody={"path":"D:/synthetic/oldca.before","sha256":inp.OLD_CA["sha256"]}
    tx={"original_ref":dict(inp.OLD_CA),"custody_ref":custody,"original_bytes_unchanged":True}
    hashes={custody["path"]:custody["sha256"],"D:/synthetic/other.json":"b"*64}
    monkeypatch.setattr(inp,"resolve",lambda *a:SimpleNamespace(backtest_root=Path("D:/synthetic")))
    monkeypatch.setattr(inp,"sha256",lambda p:hashes[str(p).replace("\\","/")])
    pin,read=inp.custody_reader([tx])
    assert pin(inp.OLD_CA)==Path(custody["path"])
    with pytest.raises(ValueError,match="ACCOUNT_SOURCE_CUSTODY_CHANGED"):
        pin({"path":"D:/synthetic/other.json","sha256":"a"*64})
    tx["original_ref"]={"path":"D:/synthetic/other.py","sha256":custody["sha256"]}
    with pytest.raises(ValueError,match="SAME_BYTE_CA_CUSTODY"):
        inp.custody_reader([tx])


def test_private_source_namespace_preserves_original_owner_and_actual_guard():
    original_pin=inp.source._pin
    pin=lambda r:Path(r["path"])
    read=lambda r:{"synthetic":True}
    private=inp.private_source_adapter(pin,read)
    assert inp.source._pin is original_pin
    assert private.bind_source_account_descendant.__code__ is inp.source.bind_source_account_descendant.__code__
    assert private.bind_source_account_descendant.__globals__["_pin"] is pin
    assert private.bind_source_account_descendant.__globals__["_read"] is read
    assert private._post_verified_terms.__globals__ is private.bind_source_account_descendant.__globals__


def test_freeze_acceptance_precedes_price_decode_and_source_kwargs(monkeypatch,tmp_path):
    (tmp_path/"FREEZE_ACCEPTANCE.json").write_text('{"status":"FAIL"}',encoding="utf-8")
    bound={"reader":SimpleNamespace(run=tmp_path),"pin":lambda r:None,"read":lambda r:None,
        "freeze_ref":{"path":"D:/synthetic/freeze.json","sha256":"a"*64}}
    monkeypatch.setattr(inp,"metadata_preflight",lambda run:bound)
    def forbidden(*a,**kw):raise AssertionError("source kwargs or price body decoded before acceptance")
    monkeypatch.setattr(inp.joblib,"load",forbidden)
    with pytest.raises(ValueError,match="INDEPENDENT_ACCOUNT_FREEZE"):
        inp.load_account_inputs(tmp_path)


def test_multiple_original_cusips_require_exact_original_daily_uid_transport():
    days,names,k,m=frames()
    mapping={"records":[dict(sid="FROZEN_RAW_TRANSPORT_CODE:US."+t,ticker=t,start="2025-01-01",
        end="2026-01-01",coordinate="RAW_ACTUAL_SHARE") for t in names]}
    projection={"rows":[dict(ticker=t,observed_decision_security_ids=[t,"OTHER"]) for t in names]}
    dated=k[["signal_date","ticker","cusip"]].rename(columns={"cusip":"security_id"})
    dated["moomoo_transport_code"]="US."+dated.ticker
    links,gaps=inp.identity_links(k,mapping,projection,dated)
    assert not gaps and len(links)==len(k)
    wrong=dated.copy();wrong.loc[0,"security_id"]="OTHER"
    _,gaps=inp.identity_links(k,mapping,projection,wrong)
    assert len(gaps)==1 and gaps[0]["signal_date"]==str(days[0].date())
    wrong=dated.copy();wrong.loc[0,"moomoo_transport_code"]="US.OTHER"
    _,gaps=inp.identity_links(k,mapping,projection,wrong)
    assert len(gaps)==1
    with pytest.raises(ValueError,match="DATED_IDENTITY_KEY_AMBIGUOUS"):
        inp.identity_links(k,mapping,projection,pd.concat([dated,dated.iloc[[0]]]))


def test_literal_original_bare_cusip_is_exact_prefix_link_without_sid_rewrite():
    days,names,k,m=frames()
    mapping={"records":[dict(sid=t,ticker=t,start="2025-01-01",end="2026-01-01",
        coordinate="RAW_ACTUAL_SHARE") for t in names]}
    projection={"rows":[dict(ticker=t,observed_decision_security_ids=[t]) for t in names]}
    dated=k[["signal_date","ticker","cusip"]].rename(columns={"cusip":"security_id"})
    dated["moomoo_transport_code"]="US."+dated.ticker
    links,gaps=inp.identity_links(k,mapping,projection,dated)
    assert not gaps and links.accounting_sid.eq(links.ticker).all()
    assert set(map(tuple,links[["signal_date","security_uid","ticker"]].to_numpy()))==set(map(tuple,k[["signal_date","security_uid","ticker"]].to_numpy()))
    wrong=copy.deepcopy(mapping);wrong["records"][0]["sid"]="OTHER"
    _,gaps=inp.identity_links(k,wrong,projection,dated)
    assert len(gaps)==len(days)


def test_identity_gap_blocks_only_selected_account_and_never_changes_model_u():
    days,names,k,m=frames()
    keys=k.copy(deep=True)
    bound={"freeze":{"account_path_ids":["Raw","HGB"]},"keys":k,
        "identity_links":k.iloc[1:].assign(accounting_sid="same"),"calendar":days}
    with pytest.raises(ValueError,match="SELECTED_PATH_DATED_IDENTITY"):
        call.run_fixed_accounts(bound,m,("Raw","HGB"))
    pd.testing.assert_frame_equal(k,keys)


def test_exact_original_source_cash_issuer_class_basis_requires_all_bindings():
    days,names,k,m=frames()
    sid={t:"SOURCE_ISSUER_COMMON_CLASS:"+str(i+1)*64 for i,t in enumerate(names)}
    mapping={"records":[dict(sid=sid[t],ticker=t,start="2025-01-01",end="2026-01-01",
        coordinate="RAW_ACTUAL_SHARE") for t in names],
        "basis_by_ticker":{t:dict(kind="EXACT_REUSED_SOURCE_CASH_ISSUER_CLASS",source_sid=sid[t],
            source_ref=dict(inp.DEFAULT_REFS["original_cash_kwargs"]),not_a_CUSIP_claim=False) for t in names}}
    projection={"rows":[dict(ticker=t,observed_decision_security_ids=[t]) for t in names]}
    dated=k[["signal_date","ticker","cusip"]].rename(columns={"cusip":"security_id"})
    dated["moomoo_transport_code"]="US."+dated.ticker
    links,gaps=inp.identity_links(k,mapping,projection,dated)
    assert not gaps and set(links.accounting_sid)==set(sid.values())
    cases=[]
    bad=copy.deepcopy(mapping);bad["basis_by_ticker"]["S"]["source_sid"]="OTHER";cases.append(bad)
    bad=copy.deepcopy(mapping);bad["basis_by_ticker"]["S"]["source_ref"]["sha256"]="0"*64;cases.append(bad)
    bad=copy.deepcopy(mapping);bad["basis_by_ticker"]["S"]["kind"]="TICKER_GUESS";cases.append(bad)
    bad=copy.deepcopy(mapping);bad["basis_by_ticker"]["S"]["not_a_CUSIP_claim"]=True;cases.append(bad)
    for bad in cases:
        _,gaps=inp.identity_links(k,bad,projection,dated)
        assert len(gaps)==len(days)
