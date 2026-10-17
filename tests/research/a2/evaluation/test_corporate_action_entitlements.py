"""Synthetic pure-event checks; no market, model, account or provider files."""
from dataclasses import replace
import hashlib
import importlib.util
from pathlib import Path
import pickle
import sys

import pandas as pd
import pytest

from scripts.v22 import corporate_action_transition_r1 as ca

ROOT = Path(r"D:\us-tech-quant-results\JOINT_TOP20_PORTFOLIO_POLICY_PRE2026_TEST2026_R1\V24")
OLD_SHA = "7b9411c6d6e21ebb4738d080ded28da93d73dec36058d76d808961d22f270ddc"
BINDINGS = {"SEC-A": "AAA", "SEC-B": "BBB"}


def event(**values):
    fields = dict(event_id="SYNTHETIC-CASH-1", action_type="CASH_DIVIDEND",
        old_security_id="SEC-A", ticker="AAA", ex_date="2024-12-30",
        record_date="2024-12-31", pay_date="2025-01-04",
        available_at="2024-12-20T15:00:00Z", cash_per_old_share=.25,
        currency="USD", amount_unit=ca.USD_PER_RAW_OLD_SHARE,
        quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,
        source_type="TIER1_ISSUER_REGULATOR_EXCHANGE",
        source_reference="synthetic://issuer/1", source_fingerprint="a"*64)
    fields.update(values)
    return ca.SourceBackedEntitlementEvent(**fields)


def step(events, day, shares, cash=100., state=None, **kwargs):
    opening = (pd.Timestamp(day)+pd.Timedelta(hours=9, minutes=30)).tz_localize("America/New_York")
    fields = dict(execution_date=day, session_open_at=opening.tz_convert("UTC"),
        security_tickers=BINDINGS, quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,
        state=state, enabled=True)
    fields.update(kwargs)
    return ca.apply_entitlement_lifecycle(events, shares, cash, **fields)


def test_disabled_is_no_event_passthrough_even_with_unqualified_event_input():
    shares={"SEC-A":3.}
    result=ca.apply_entitlement_lifecycle([object()],shares,20.,execution_date=None,
        session_open_at=None,security_tickers={},quantity_coordinate="",enabled=False)
    assert result.positions==shares and result.positions is not shares
    assert result.cash==20 and result.receivable_value_usd==0 and result.records==()
    assert result.accounting_qualified and result.state.last_session is None


def test_receivable_nav_asset_is_not_cash_and_survives_sale_crossyear_weekend_pay():
    e=event()
    ex=step([e],"2024-12-30",{"SEC-A":10.})
    assert ex.cash==100 and ex.receivable_value_usd==2.5
    assert ex.cash+ex.receivable_value_usd==102.5
    assert [r["phase"] for r in ex.records]==["EX_PRETRADE_RAW_SHARE_SNAPSHOT","RECEIVABLE_RECOGNIZED"]
    sold=step([e],"2025-01-02",{},ex.cash,ex.state)
    assert sold.cash==100 and sold.receivable_value_usd==2.5
    paid=step([e],"2025-01-06",{},sold.cash,sold.state)
    assert paid.cash==102.5 and paid.receivable_value_usd==0 and paid.accounting_qualified
    assert paid.records[0]["phase"]=="CASH_PAID"
    later=step([e],"2025-01-07",{},paid.cash,paid.state)
    assert later.cash==102.5 and later.records==()


def test_ex_session_buy_has_no_rights_record_date_is_not_ownership_clock():
    e=event(pay_date="2025-01-02")
    ex=step([e],"2024-12-30",{})
    bought=step([e],"2024-12-31",{"SEC-A":10.},ex.cash,ex.state)
    pay=step([e],"2025-01-02",{"SEC-A":10.},bought.cash,bought.state)
    assert pay.cash==100 and pay.receivable_value_usd==0 and pay.accounting_qualified


def test_future_event_never_changes_current_rights_cash_or_qualification():
    e=event(available_at="2025-01-03T18:00:00Z")
    before=step([e],"2024-12-27",{"SEC-A":10.})
    assert before.records==() and before.receivable_value_usd==0
    assert before.cash==100 and before.accounting_qualified


def test_late_publication_held_ex_prefix_is_never_recertified_or_backfilled():
    e=event(available_at="2024-12-30T16:00:00Z",pay_date="2025-01-02")
    ex=step([e],"2024-12-30",{"SEC-A":10.})
    assert not ex.accounting_qualified and ex.receivable_value_usd==0
    assert ex.state.blocked_events==((e.event_id,"SOURCE_NOT_AVAILABLE_BY_EX_OPEN"),)
    pay=step([e],"2025-01-02",{},ex.cash,ex.state)
    assert pay.cash==100 and pay.receivable_value_usd==0 and not pay.accounting_qualified
    assert pay.records==()


def test_unheld_late_publication_never_contaminates_other_positions():
    e=event(available_at="2025-01-03T18:00:00Z")
    ex=step([e],"2024-12-30",{"SEC-B":7.})
    pay=step([e],"2025-01-06",{"SEC-B":7.},ex.cash,ex.state)
    assert pay.positions=={"SEC-B":7.} and pay.cash==100 and pay.accounting_qualified
    assert pay.state.blocked_events==()


@pytest.mark.parametrize("field,value,code",[
    ("currency","EUR","CURRENCY"),("currency",None,"CURRENCY"),
    ("amount_unit",None,"CASH_UNIT"),("amount_unit","UNCONFIRMED","CASH_UNIT"),
    ("quantity_coordinate","QFQ_UNITS","COORDINATE"),
    ("cash_per_old_share",None,"CASH_AMOUNT"),("cash_per_old_share",float("nan"),"CASH_AMOUNT"),
    ("cash_per_old_share",float("inf"),"CASH_AMOUNT"),("cash_per_old_share",-.1,"CASH_AMOUNT"),
    ("source_fingerprint","heuristic","SHA256"),("source_reference","","SOURCE_ID"),
    ("source_type","HEURISTIC","SOURCE_NOT_AUTHORIZED"),("old_security_id","","SECURITY_SOURCE_ID"),
    ("available_at","2024-12-20","AVAILABLE_TIME"),
    ("pay_date","2024-12-29","DUE_BILL"),
])
def test_source_units_clock_identity_and_terms_are_explicit(field,value,code):
    with pytest.raises(ValueError,match=code):event(**{field:value})


@pytest.mark.parametrize("family",["SPINOFF","MULTI_SECURITY_SPINOFF","COMPLEX_CA"])
def test_non_cash_and_multisecurity_events_explicitly_block_only_held_accounts(family):
    e=event(action_type=family,cash_per_old_share=None)
    held=step([e],"2024-12-30",{"SEC-A":10.})
    unrelated=step([e],"2024-12-30",{"SEC-B":5.})
    assert not held.accounting_qualified and held.cash==100 and held.receivable_value_usd==0
    assert held.state.blocked_events[0][1].endswith(family)
    assert unrelated.accounting_qualified and unrelated.positions=={"SEC-B":5.}


def test_security_ticker_identity_and_raw_coordinates_are_required():
    with pytest.raises(ValueError,match="SECURITY_TICKER_MISMATCH"):
        step([event()],"2024-12-30",{"SEC-A":1.},security_tickers={"SEC-A":"BBB"})
    with pytest.raises(ValueError,match="INPUT_NOT_RAW"):
        step([event()],"2024-12-30",{"SEC-A":1.},quantity_coordinate="ENGINE_INDEX_UNITS")
    with pytest.raises(ValueError,match="POSITION_SECURITY_BINDING"):
        step([event()],"2024-12-30",{"UNKNOWN":1.})


def test_duplicate_events_cannot_double_recognize_cash():
    e=event()
    with pytest.raises(ValueError,match="DUPLICATE_ENTITLEMENT_EVENT_ID"):
        step([e,e],"2024-12-30",{"SEC-A":1.})
    with pytest.raises(ValueError,match="DUPLICATE_ENTITLEMENT_ECONOMIC_EVENT"):
        step([e,replace(e,event_id="duplicate alias")],"2024-12-30",{"SEC-A":1.})


def test_repeat_or_reverse_session_cannot_double_pay():
    e=event(pay_date="2024-12-31")
    ex=step([e],"2024-12-30",{"SEC-A":1.})
    paid=step([e],"2024-12-31",{},ex.cash,ex.state)
    with pytest.raises(ValueError,match="SESSION_ALREADY_APPLIED"):
        step([e],"2024-12-31",{},paid.cash,paid.state)
    with pytest.raises(ValueError,match="SESSION_ALREADY_APPLIED"):
        step([e],"2024-12-30",{},paid.cash,paid.state)


def test_frozen_catalogue_and_security_binding_cannot_change_on_resume():
    e=event();ex=step([e],"2024-12-30",{"SEC-A":1.})
    with pytest.raises(ValueError,match="FROZEN_CATALOGUE_CHANGED"):
        step([replace(e,cash_per_old_share=1.)],"2024-12-31",{},ex.cash,ex.state)
    with pytest.raises(ValueError,match="FROZEN_SECURITY_BINDING_CHANGED"):
        step([e],"2024-12-31",{},ex.cash,ex.state,security_tickers={"SEC-A":"AAA"})


def test_missing_ex_snapshot_is_not_inferred_from_later_holdings():
    e=event()
    with pytest.raises(ValueError,match="MISSING_EX_PRETRADE_POSITION_SNAPSHOT"):
        step([e],"2024-12-31",{"SEC-A":1.})
    unrelated=step([e],"2024-12-31",{"SEC-B":1.})
    assert unrelated.accounting_qualified and unrelated.receivable_value_usd==0


def test_fractional_claim_and_state_roundtrip_have_no_rounding_or_mutation():
    e=event();shares={"SEC-A":.125}
    ex=step([e],"2024-12-30",shares)
    assert ex.receivable_value_usd==.03125 and shares=={"SEC-A":.125}
    restored=pickle.loads(pickle.dumps(ex.state))
    assert restored==ex.state
    pay=step([e],"2025-01-06",{},ex.cash,restored)
    assert pay.cash==100.03125


def test_legacy_source_bytes_and_api_outputs_remain_exact():
    snapshot=ROOT/"receipts/source_audit"/("corporate_action_transition_r1_"+OLD_SHA+".py")
    oldbytes=snapshot.read_bytes()
    assert hashlib.sha256(oldbytes).hexdigest()==OLD_SHA
    assert Path(ca.__file__).read_bytes().startswith(oldbytes)
    spec=importlib.util.spec_from_file_location("_synthetic_legacy_ca",snapshot)
    old=importlib.util.module_from_spec(spec);sys.modules[spec.name]=old;spec.loader.exec_module(old)
    for new_ticker,amount in [("AAA",0.),("NEW",.75)]:
        fields=dict(effective_date="2024-01-03",action_type="MERGER_MIXED_CONVERSION",
            old_security_id="OLD",new_security_id="NEW",old_ticker="AAA",new_ticker=new_ticker,
            quantity_multiplier=.2,cash_component_per_old_share=amount,
            source_type="TIER1_ISSUER_REGULATOR_EXCHANGE",source_reference="synthetic://1",
            source_fingerprint="a"*64)
        for module in (old,ca):
            transition=module.CorporateActionTransition(**fields)
            result=module.CorporateActionTransitionAdapter([transition]).apply(
                execution_date=pd.Timestamp("2024-01-03"),shares={"AAA":1.25},cash=2.)
            if module is old:expected=result
            else:assert result==expected



def test_close_clock_cannot_make_late_publication_available_at_ex_open():
    e=event(available_at="2024-12-30T16:00:00Z")
    with pytest.raises(ValueError,match="OPEN_0930_NY"):
        step([e],"2024-12-30",{"SEC-A":1.},session_open_at="2024-12-30T21:00:00Z")


@pytest.mark.parametrize("placeholder",["UNKNOWN", "FROZEN_VENDOR:AAA", "SOURCE_ID_NOT_EXTRACTED"])
def test_source_placeholders_cannot_qualify_cash_rights(placeholder):
    with pytest.raises(ValueError,match="PLACEHOLDER_SECURITY_ID"):
        event(old_security_id=placeholder)


def test_receivable_or_payment_overflow_fails_closed():
    first=event(cash_per_old_share=1.e308)
    second=event(event_id="SYNTHETIC-CASH-2",old_security_id="SEC-B",ticker="BBB",
        cash_per_old_share=1.e308)
    with pytest.raises(ValueError,match="RECEIVABLE_TOTAL_OVERFLOW"):
        step([first,second],"2024-12-30",{"SEC-A":1.,"SEC-B":1.})
    claim=step([first],"2024-12-30",{"SEC-A":1.},cash=1.e308)
    with pytest.raises(ValueError,match="CASH_OVERFLOW"):
        step([first],"2025-01-06",{},claim.cash,claim.state)


# Merger cash rights use a separate type from cash dividends.
def terminal(**changes):
    fields=dict(event_id="terminal",old_security_id="SEC-A",ticker="AAA",
        effective_at="2024-12-30T14:30:00Z",available_at="2024-12-20T15:00:00Z",
        cash_per_old_share=5.,currency="USD",amount_unit=ca.USD_PER_RAW_OLD_SHARE,
        quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,
        quantity_source_reference="synthetic://post-split-coordinate",quantity_source_fingerprint="b"*64,
        source_type="TIER1_ISSUER_REGULATOR_EXCHANGE",source_reference="synthetic://closing",source_fingerprint="c"*64)
    fields.update(changes)
    return ca.SourceBackedTerminalEvent(**fields)


def terminal_payment(**changes):
    fields=dict(event_id="terminal",old_security_id="SEC-A",pay_date="2025-01-02",
        available_at="2024-12-31T12:00:00Z",cash_per_old_share=5.,currency="USD",
        amount_unit=ca.USD_PER_RAW_OLD_SHARE,quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,
        source_type="TIER1_ISSUER_REGULATOR_EXCHANGE",source_reference="synthetic://payment",source_fingerprint="d"*64)
    fields.update(changes)
    return ca.SourceBackedTerminalSettlement(**fields)


def test_terminal_extinguishment_unpaid_right_and_independent_payment_once():
    e=terminal();shares={"SEC-A":.125,"SEC-B":7.}
    ex=step([e],"2024-12-30",shares)
    assert ex.positions=={"SEC-A":0.,"SEC-B":7.} and shares["SEC-A"]==.125
    assert ex.cash==100 and ex.receivable_value_usd==.625 and ex.state.receivables[0].pay_date is None
    assert ex.accounting_qualified  # Rights qualified; full settlement is the consumer gate.
    assert [r['phase'] for r in ex.records]==['TERMINAL_PRE_EFFECTIVE_RAW_SHARE_SNAPSHOT',
        'SECURITY_EXTINGUISHED','MERGER_RECEIVABLE_RECOGNIZED','SETTLEMENT_PENDING_AUTHORITY']
    later=step([e],"2025-01-06",ex.positions,ex.cash,ex.state)
    assert later.cash==100 and later.receivable_value_usd==.625 and later.records==()
    e=terminal(settlement=terminal_payment())
    ex=step([e],"2024-12-30",{"SEC-A":2.5})
    assert ex.state.receivables[0].pay_date is None
    disclosed=step([e],"2024-12-31",ex.positions,ex.cash,ex.state)
    assert disclosed.cash==100 and disclosed.state.receivables[0].pay_date=='2025-01-02'
    paid=step([e],"2025-01-02",disclosed.positions,disclosed.cash,disclosed.state)
    assert paid.cash==112.5 and paid.receivable_value_usd==0
    payment=[r for r in paid.records if r['phase']=='CASH_PAID']
    assert len(payment)==1 and payment[0]['settlement_source_fingerprint']=='d'*64
    again=step([e],"2025-01-03",paid.positions,paid.cash,paid.state)
    assert again.cash==112.5 and again.records==()


def test_terminal_unheld_event_does_not_contaminate_other_security():
    result=step([terminal()],"2024-12-30",{"SEC-B":7.})
    assert result.positions=={"SEC-B":7.} and result.receivable_value_usd==0
    assert result.records==() and result.accounting_qualified


@pytest.mark.parametrize('changes,code',[
    ({'cash_per_old_share':None},'CONSIDERATION'),({'cash_per_old_share':float('nan')},'CONSIDERATION'),
    ({'cash_per_old_share':True},'CONSIDERATION'),({'cash_per_old_share':-1},'CONSIDERATION'),
    ({'action_type':'CASH_DIVIDEND'},'CONSIDERATION'),
    ({'available_at':'2024-12-30T14:30:01Z'},'NOT_AVAILABLE'),
    ({'effective_at':'2024-12-30T14:31:00Z'},'EFFECTIVE_TIME'),
    ({'quantity_source_fingerprint':'guessed'},'CONSIDERATION'),({'amount_unit':'QFQ_SHARE'},'CASH_UNIT'),
])
def test_terminal_explicit_clock_coordinate_and_amount(changes,code):
    with pytest.raises(ValueError,match=code):terminal(**changes)


@pytest.mark.parametrize('changes,code',[
    ({'authority':'PROMPTLY_PRACTICABLE'},'AUTHORITY_REQUIRED'),
    ({'available_at':'2025-01-02T14:31:00Z'},'NOT_AVAILABLE_BY_PAY_OPEN'),
    ({'old_security_id':'SEC-B'},'COORDINATE_MISMATCH'),({'cash_per_old_share':4.9},'COORDINATE_MISMATCH'),
])
def test_terminal_rejects_unproved_or_mismatched_payment(changes,code):
    with pytest.raises(ValueError,match=code):terminal(settlement=terminal_payment(**changes))


def test_terminal_conflicting_events_changed_source_and_reappeared_stock_rejected():
    e=terminal(settlement=terminal_payment())
    alias=terminal(event_id='other',settlement=terminal_payment(event_id='other',pay_date='2025-01-03'))
    with pytest.raises(ValueError,match='DUPLICATE_TERMINAL_SECURITY'):
        step([e,alias],'2024-12-30',{'SEC-A':1.})
    with pytest.raises(ValueError,match='SIMULTANEOUS_ENTITLEMENT_PRIORITY'):
        step([e,event()],'2024-12-30',{'SEC-A':1.})
    first=step([e],'2024-12-30',{'SEC-A':1.})
    changed=terminal(settlement=terminal_payment(source_fingerprint='e'*64))
    with pytest.raises(ValueError,match='FROZEN_CATALOGUE_CHANGED'):
        step([changed],'2024-12-31',first.positions,first.cash,first.state)
    with pytest.raises(ValueError,match='OLD_SECURITY_REAPPEARED'):
        step([e],'2024-12-31',{'SEC-A':1.},first.cash,first.state)
