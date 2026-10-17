"""Synthetic source-backed child rights through the single shared account owners."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from scripts.v22 import corporate_action_transition_r1 as ca
from scripts.research.a2.evaluation import consensus_shareholder_account as bridge
from scripts.research.a2.evaluation.continuous_research_account import run_continuous_account
from scripts.research.a2.evaluation.consensus_cash_account import FeeConfig
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays, TargetDecision


def stock_event(**changes):
    fields = dict(event_id="synthetic stock distribution", action_type="MULTI_SECURITY_STOCK_DISTRIBUTION",
        old_security_id="parent_security", ticker="DHR", ex_date="2023-10-02", record_date="2023-09-13",
        available_at="2023-08-31T20:00:00Z", child_security_id="child_security", child_ticker="VLTO",
        child_ratio_numerator=1, child_ratio_denominator=3, child_quantity_unit="COMMON_SHARE",
        delivery_date="2023-10-02", regular_trading_date="2023-10-02",
        quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE, source_type="TIER2_LOCAL_CANONICAL",
        source_reference="synthetic://official-distribution-terms", source_fingerprint="a"*64,
        original_cash_in_lieu_terms="Synthetic issuer aggregate and sell fractions; actual CIL rate unknown.")
    fields.update(changes)
    return ca.SourceBackedStockDistributionEvent(**fields)


def apply(event, *, day="2023-10-02", positions=None, state=None, quote=True):
    return ca.apply_entitlement_lifecycle((event,), positions or {"parent_security": .8}, 11.,
        execution_date=day, session_open_at=(pd.Timestamp(day)+pd.Timedelta(hours=9,minutes=30)).tz_localize("America/New_York"),
        security_tickers={"parent_security":"DHR", "child_security":"VLTO"},
        quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE, enabled=True, state=state,
        stock_delivery_quote_qualified={"child_security":quote})


def ref(path):
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


@pytest.fixture
def scoped_authority(tmp_path, monkeypatch):
    root = tmp_path/bridge.CHILD_RESEARCH_ID/"synthetic_run";root.mkdir(parents=True)
    continuation = root/"CONTINUATION_SCOPE.json"
    continuation.write_text(json.dumps(dict(schema="CONSENSUS_PRE2026_SOURCE_COMPLETION_CONTINUATION_SCOPE_R1",
        task_id=bridge.TASK,research_id=bridge.CHILD_RESEARCH_ID,parent_research_id=bridge.TASK,run=str(root),
        boundaries=dict(no_new_2026_sample_or_outcome_read_authorized=True,FAST3_Confirmation_access=False))))
    cr=ref(continuation)
    convention=root/"ACCOUNT_CONVENTION_SCOPE.json"
    convention.write_text(json.dumps(dict(schema="CONSENSUS_SOURCE_COMPLETION_ACCOUNT_CONVENTION_R1",
        status="FROZEN_BEFORE_NEW_ACCOUNT_REPLAY_OR_SELECTION", task_id=bridge.TASK,research_id=bridge.CHILD_RESEARCH_ID,
        continuation_scope_ref=cr,stock_distribution_research_convention=dict(mode=ca.STOCK_DISTRIBUTION_RESEARCH_MODE,
            parent_share_multiplier=1.,exact_supported_event_tickers=["DHR","FTV","LBTYK"],
            supported_event_delivery_scope="DELIVERY_NO_LATER_THAN_EX_SESSION",
            pending_stock_claim_without_qualified_close_nav_mark="HARD_BLOCK",
            actual_broker_fractional_distribution_or_cash_in_lieu_execution_certified=False))))
    monkeypatch.setattr(bridge,"CHILD_RUN",root);monkeypatch.setattr(bridge,"CONTINUATION_REF",cr)
    monkeypatch.setattr(bridge,"CONVENTION_REF",ref(convention))
    contract=root/"SOURCE_FREEZE.json";contract.write_text(json.dumps(dict(task_id=bridge.TASK,status="SYNTHETIC_ONLY")))
    scope=root/"ACCOUNT_SOURCE_SCOPE.json";scope.write_text(json.dumps(dict(schema="CONSENSUS100_ACCOUNT_SOURCE_SCOPE_R1",task_id=bridge.TASK)))
    def make(events):
        return bridge.make_task_authority(events,frozen_contract_ref=ref(contract),source_scope_ref=ref(scope),
            market_source_binding=dict(task_id=bridge.TASK,quantity_coordinate="RAW_ACTUAL_SHARE",
                historical_quote_vintage_status="UNKNOWN",source_refs=[dict(path="synthetic://raw-child-share",sha256="b"*64)],coverage_gaps=[]),
            continuation_scope_ref=bridge.CONTINUATION_REF,account_convention_scope_ref=bridge.CONVENTION_REF)
    return make


def market(*, child_in_pool=False, final_signal=True, missing_close=False):
    dates=pd.DatetimeIndex(["2023-09-28","2023-09-29","2023-10-02","2023-10-03","2023-10-04","2023-10-05"])
    prices=np.array([[400.,np.nan],[400.,np.nan],[360.,120.],[360.,120.],[360.,120.],[360.,120.]])
    present=np.isfinite(prices);pool=np.ones_like(present);pool[:,1]=child_in_pool
    close=prices.copy()
    if missing_close:close[2,1]=np.nan
    return MarketArrays(dates,["DHR","VLTO"],prices.copy(),close,adv=np.full(prices.shape,1e9),
        row_present=present,input_present=np.column_stack((np.ones(6,bool),np.zeros(6,bool))),
        new_buy_eligible=pool,signal_mask=np.array([True,True,True,True,True,final_signal]))


def binding(event):
    mapping={"parent_security":"DHR","child_security":"VLTO"}
    return dict(entitlement_events=(event,),entitlement_security_tickers=mapping,
        entitlement_source_binding=dict(status="SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND",source_fingerprint="c"*64,
            event_fingerprints=[event.event_fingerprint],security_tickers=mapping,quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE))


def policy(observed):
    def decide(j,ctx):
        mask=ctx.stock_distribution_forced_exit_mask
        if mask is not None:
            assert np.all(~mask | ctx.operational_mask)
        observed.append((j,ctx.current_units.copy(),None if mask is None else mask.copy(),ctx.operational_mask.copy()))
        weights=np.zeros_like(ctx.current_units);explicit=np.zeros_like(weights,dtype=bool)
        if j==0:weights[:,0]=.1;explicit[:,0]=True
        return TargetDecision(weights,explicit,"synthetic parent-only signal")
    return decide


def replay(scoped_authority, m=None):
    e=stock_event();m=m or market();seen=[]
    result=bridge.run_shareholder_cash_account(m,["p"],policy(seen),task_authority=scoped_authority((e,)),
        settlement_calendar=m.dates,fee_config=FeeConfig(10,0,5,True),**binding(e))
    return result,seen


def test_pure_stock_right_keeps_parent_and_fractional_child_without_cash_conversion():
    e=stock_event();out=apply(e)
    assert out.positions==pytest.approx({"parent_security":.8,"child_security":.8/3})
    assert out.cash==11. and out.receivable_value_usd==0. and out.accounting_qualified
    assert out.state.stock_claims==() and out.state.delivered_stock_event_ids==(e.event_id,)
    assert out.records[-1]["actual_broker_fractional_delivery_certified"] is False
    later=apply(e,day="2023-10-03",positions={"parent_security":0.,"child_security":.8/3},state=out.state)
    assert later.positions["child_security"]==pytest.approx(.8/3) and later.cash==11.


def test_missing_delivery_quote_retains_nonspendable_claim_and_permanent_nav_block():
    e=stock_event();out=apply(e,quote=False)
    assert out.positions=={"parent_security":.8} and out.cash==11.
    assert out.state.stock_claims[0].child_units==pytest.approx(.8/3)
    assert not out.accounting_qualified and out.receivable_value_usd==0.
    later=apply(e,day="2023-10-03",state=out.state)
    assert not later.accounting_qualified and "child_security" not in later.positions


def test_late_source_and_unproved_or_price_factor_quantity_rejected():
    assert not apply(stock_event(available_at="2023-10-02T14:00:00Z")).accounting_qualified
    with pytest.raises(ValueError,match="RATIONAL_RATIO"):
        stock_event(child_ratio_numerator=.8863899)
    with pytest.raises(ValueError,match="PLACEHOLDER_SECURITY"):
        stock_event(child_security_id="UNKNOWN_child")
    with pytest.raises(ValueError,match="DELIVERY_BY_EX_SCOPE"):
        stock_event(delivery_date="2023-10-03")


def test_real_shared_bridge_delivery_first_close_exit_next_open_cost_and_settlement(scoped_authority):
    r,seen=replay(scoped_authority)
    delivered=r.entitlements.loc[r.entitlements.phase.eq("STOCK_DISTRIBUTION_DELIVERED")]
    assert delivered.child_units.iloc[0]==pytest.approx(.25)
    assert seen[2][1][0].tolist()==pytest.approx([.75,.25])
    assert seen[2][2].tolist()==[[False,True]]
    fills=r.fills
    assert fills.ticker.tolist()==["DHR","VLTO"] and fills.side.tolist()==["BUY","SELL"]
    assert fills.execution_date.tolist()==[pd.Timestamp("2023-09-29"),pd.Timestamp("2023-10-03")]
    assert fills.transaction_cost.tolist()==pytest.approx([.3,.03])
    assert fills.index_units.tolist()==pytest.approx([.75,.25])
    orders=r.orders.loc[r.orders.ticker.eq("VLTO") & r.orders.signal_date.eq(pd.Timestamp("2023-10-02"))]
    assert orders.order_type.iloc[0]=="EXIT" and not orders.explicit_model_decision.iloc[0]
    assert r.daily.loc[r.daily.date.eq(pd.Timestamp("2023-10-03")),"unsettled_cash"].iloc[0]==pytest.approx(29.97)
    assert r.final_cash[0]==pytest.approx(2729.67)
    assert r.final_state["fractional_shares"][0].tolist()==pytest.approx([.75,0.])
    assert r.final_state["stock_distribution_forced_exit_inventory_tickers"]==()
    assert r.final_state["accounting_qualified"].all() and r.audit["actual_cash_flow_identity_error_max"]<1e-8


def test_current_pool_child_with_missing_alpha_is_held_and_not_permanently_excluded(scoped_authority):
    r,seen=replay(scoped_authority,market(child_in_pool=True))
    assert not seen[2][2].any() and len(r.fills)==1
    assert r.final_state["fractional_shares"][0,1]==pytest.approx(.25)
    assert r.final_state["stock_distribution_forced_exit_inventory_tickers"]==()


def test_final_close_without_policy_still_freezes_exact_mechanical_inventory(scoped_authority):
    m=market();m.signal_mask[2:]=False
    r,seen=replay(scoped_authority,m)
    assert len(seen)==2 and r.final_state["fractional_shares"][0,1]==pytest.approx(.25)
    assert r.final_state["stock_distribution_forced_exit_inventory_tickers"]==("VLTO",)


def test_missing_child_close_blocks_nav_even_without_policy(scoped_authority):
    m=market(missing_close=True);m.signal_mask[2:]=False
    r,_=replay(scoped_authority,m)
    assert not r.final_state["accounting_qualified"].all()
    assert "DELIVERED_STOCK_WITHOUT_QUALIFIED_RAW_CLOSE_NAV_MARK" in r.accounting_exceptions.reason.tolist()
    assert not r.daily.loc[r.daily.date.eq(pd.Timestamp("2023-10-02")),"accounting_qualified"].iloc[0]


def test_exact_frozen_child_scope_and_ratio_guards_do_not_relax_cash_authority(scoped_authority):
    e=stock_event();a=scoped_authority((e,))
    with pytest.raises(ValueError,match="EXACT_SOURCE_COMPLETION"):
        bridge.validate_task_authority((e,),dict(a,account_convention_scope_ref=dict(a["account_convention_scope_ref"],sha256="d"*64)))
    bad=stock_event(child_ratio_denominator=5)
    with pytest.raises(ValueError,match="EXACT_THREE_STOCK_EVENT_TERMS"):
        scoped_authority((bad,))
    without={k:v for k,v in a.items() if k not in ("continuation_scope_ref","account_convention_scope_ref")}
    with pytest.raises(ValueError,match="NEW_TASK_METADATA|EXACT_CHILD_RESEARCH"):
        bridge.validate_task_authority((e,),without)
