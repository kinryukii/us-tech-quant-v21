"""Synthetic cash-inclusive H5 descendant tests; no market/body/model reads."""
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.data.joint_input_binding import (
    shareholder_open_targets, cash_inclusive_shareholder_open_targets, existing_event_functions,
)
from scripts.v22.corporate_action_transition_r1 import (
    SourceBackedEntitlementEvent, RAW_OLD_SHARE_COORDINATE, USD_PER_RAW_OLD_SHARE,
)

@pytest.fixture
def setup():
    # Same frozen pure quantity-window source used by the existing owner tests.
    source=Path('D:/us-tech-quant-results/A2_STATEFUL_ACTION_AND_CASH_PRE2026_TEST2026_R1/LABEL_REPAIR_R1.py')
    apply,_=existing_event_functions(source)
    dates=pd.bdate_range('2024-01-02',periods=9)
    keys=pd.DataFrame({'signal_date':[dates[0]],'ticker':['X'],'security_id':['CUSIP:EXACT_X']})
    raw=pd.DataFrame({'ticker':['X','X'],'trade_date':[dates[1],dates[6]],'open':[100.,110.]})
    return keys,raw,dates,apply


def cash(dates,*,ex=3,pay='2024-01-19',available='2023-12-29T20:00:00Z',sid='CUSIP:EXACT_X',amount=2.):
    return SourceBackedEntitlementEvent('CASH_X','CASH_DIVIDEND',sid,'X',str(dates[ex].date()),
        str(dates[ex].date()),pay,available,amount,'USD',USD_PER_RAW_OLD_SHARE,
        RAW_OLD_SHARE_COORDINATE,'TIER1_ISSUER_REGULATOR_EXCHANGE','https://issuer.example/dated-declaration','a'*64)


def build(setup,events=(),cash_events=(),cutoff='2025-01-01T00:00:00Z'):
    keys,raw,dates,apply=setup
    return cash_inclusive_shareholder_open_targets(keys,raw,dates,events,apply,cash_events=cash_events,cutoff=cutoff)


def test_no_event_matches_old_price_quantity_value_and_new_coordinate(setup):
    keys,raw,dates,apply=setup
    old=shareholder_open_targets(keys,raw,dates,(),apply)
    new=build(setup)
    assert new.loc[0,'label_available'] and new.loc[0,'y_open5']==old.loc[0,'y_open5']
    assert new.loc[0,'label_coordinate']!=old.loc[0,'label_coordinate']
    assert new.loc[0,'label_cash_paid_per_entry_share']==new.loc[0,'label_cash_receivable_per_entry_share']==0
    assert not new.loc[0,'strict_PIT_promotion_eligible']


@pytest.mark.parametrize('pay,paid,claim',[('2024-01-19',0.,2.),('2024-01-08',2.,0.)])
def test_paid_cash_and_receivable_are_both_economic_value_without_double_count(setup,pay,paid,claim):
    out=build(setup,cash_events=(cash(setup[2],pay=pay),))
    assert out.loc[0,'label_available']
    assert out.loc[0,'y_open5']==pytest.approx(.12)
    assert out.loc[0,'label_cash_paid_per_entry_share']==paid
    assert out.loc[0,'label_cash_receivable_per_entry_share']==claim


@pytest.mark.parametrize('ex,expected',[(1,.10),(6,.12),(7,.10)])
def test_cash_event_window_entry_excluded_exit_included(setup,ex,expected):
    out=build(setup,cash_events=(cash(setup[2],ex=ex),))
    assert out.loc[0,'label_available'] and out.loc[0,'y_open5']==pytest.approx(expected)


@pytest.mark.parametrize('share_day,cash_day,claim',[(2,3,4.),(4,3,2.),(3,3,2.)])
def test_share_quantity_once_and_cash_uses_pre_ex_raw_old_shares(setup,share_day,cash_day,claim):
    keys,raw,dates,apply=setup
    raw=raw.copy();raw.loc[1,'open']=55.
    event=dict(ticker='X',event_date=str(dates[share_day].date()),status='SHARE_ONLY_SUPPORTED',
        quantity_multiplier=2.,security_id='CUSIP:EXACT_X',available_at='2023-12-29T20:00:00Z')
    out=build((keys,raw,dates,apply),events=(event,),cash_events=(cash(dates,ex=cash_day),))
    assert out.loc[0,'label_available']
    assert out.loc[0,'label_quantity_multiplier']==2.
    assert out.loc[0,'label_cash_receivable_per_entry_share']==claim
    assert out.loc[0,'y_open5']==pytest.approx((110.+claim)/100.-1.)


def test_unsupported_original_event_never_removed_by_label_builder(setup):
    event=dict(ticker='X',event_date=str(setup[2][3].date()),status='UNSUPPORTED')
    out=build(setup,events=(event,),cash_events=(cash(setup[2]),))
    assert not out.loc[0,'label_available'] and pd.isna(out.loc[0,'y_open5'])


def test_late_or_unknown_cash_source_and_wrong_identity_fail_closed(setup):
    cases=(cash(setup[2],available='2024-01-05T15:00:00Z'),
           cash(setup[2],available='2025-01-02T00:00:00Z'),
           cash(setup[2],sid='CUSIP:OTHER'))
    for event in cases:
        out=build(setup,cash_events=(event,))
        assert not out.loc[0,'label_available'] and pd.isna(out.loc[0,'y_open5'])
    event=cash(setup[2]);object.__setattr__(event,'cash_per_old_share',None)
    out=build(setup,cash_events=(event,))
    assert not out.loc[0,'label_available'] and pd.isna(out.loc[0,'y_open5'])


def test_unknown_quantity_identity_or_source_clock_fail_closed(setup):
    day=str(setup[2][2].date())
    base=dict(ticker='X',event_date=day,status='SHARE_ONLY_SUPPORTED',quantity_multiplier=2.)
    for event in (base,{**base,'security_id':'CUSIP:OTHER','available_at':'2023-12-29T20:00:00Z'},
                  {**base,'security_id':'CUSIP:EXACT_X','available_at':'2024-01-04T15:00:00Z'}):
        out=build(setup,events=(event,))
        assert not out.loc[0,'label_available'] and pd.isna(out.loc[0,'y_open5'])


def test_maturity_strict_and_no_future_source_for_earlier_fold(setup):
    out=build(setup,cutoff='2024-01-10T21:00:00Z')
    assert not out.loc[0,'label_available'] and out.loc[0,'cash_label_reason']=='LABEL_NOT_MATURE_BEFORE_FOLD_CUTOFF'
    out=build(setup,cutoff='2024-01-10T21:00:00.000001Z')
    assert out.loc[0,'label_available']
    with pytest.raises(ValueError,match='EXPLICIT_PRE2026_FOLD'):
        build(setup,cutoff='2025-01-01')
    with pytest.raises(ValueError,match='EXPLICIT_PRE2026_FOLD'):
        build(setup,cutoff='2026-01-02T00:00:00Z')


def test_missing_endpoint_and_identity_are_never_filled_or_dropped(setup):
    keys,raw,dates,apply=setup
    out=build((keys,raw.iloc[:1],dates,apply))
    assert len(out)==1 and not out.loc[0,'label_available'] and pd.isna(out.loc[0,'y_open5'])
    bad=keys.copy();bad['security_id']='UNKNOWN'
    with pytest.raises(ValueError,match='KNOWN_SECURITY_ID'):
        build((bad,raw,dates,apply))


def test_duplicate_cash_catalogue_is_not_paid_twice(setup):
    event=cash(setup[2])
    with pytest.raises(ValueError,match='DUPLICATE_CASH_EVENT_ID'):
        build(setup,cash_events=(event,event))


def test_source_inputs_not_mutated_and_cash_owner_is_used(setup,monkeypatch):
    import scripts.v22.corporate_action_transition_r1 as owner
    original=owner.apply_entitlement_lifecycle;calls=[]
    def spy(*args,**kwargs):
        calls.append(kwargs['execution_date']);return original(*args,**kwargs)
    monkeypatch.setattr(owner,'apply_entitlement_lifecycle',spy)
    keys,raw,dates,apply=setup;before_keys=keys.copy(deep=True);before_raw=raw.copy(deep=True)
    out=build(setup,cash_events=(cash(dates),))
    assert out.loc[0,'label_available'] and len(calls)==5
    pd.testing.assert_frame_equal(keys,before_keys);pd.testing.assert_frame_equal(raw,before_raw)


def test_strict_source_cash_is_usable_for_synthetic_2022_fold(setup):
    _, _, _, apply = setup
    dates = pd.bdate_range('2022-01-03', periods=9)
    keys = pd.DataFrame({'signal_date': [dates[0]], 'ticker': ['X'], 'security_id': ['CUSIP:EXACT_X']})
    raw = pd.DataFrame({'ticker': ['X', 'X'], 'trade_date': [dates[1], dates[6]], 'open': [100., 110.]})
    event = cash(dates, pay='2022-01-19', available='2021-12-09T21:00:00Z')
    out = build((keys, raw, dates, apply), cash_events=(event,), cutoff='2023-01-01T00:00:00Z')
    assert out.loc[0, 'label_available'] and out.loc[0, 'y_open5'] == pytest.approx(.12)
    assert out.loc[0, 'label_cash_receivable_per_entry_share'] == 2.
    assert out.loc[0, 'label_available_at'] == pd.Timestamp('2022-01-11T21:00:00Z')


def test_unknown_cash_publication_clock_remains_blocked(setup):
    event = cash(setup[2])
    object.__setattr__(event, 'available_at', None)
    out = build(setup, cash_events=(event,))
    assert not out.loc[0, 'label_available'] and pd.isna(out.loc[0, 'y_open5'])


def test_distinct_cash_events_accumulate_via_single_owner(setup):
    dates = setup[2]
    first = cash(dates, pay='2024-01-08')
    second = cash(dates, ex=4, pay='2024-01-19', amount=3.)
    object.__setattr__(second, 'event_id', 'CASH_X_SECOND')
    out = build(setup, cash_events=(first, second))
    assert out.loc[0, 'label_available'] and out.loc[0, 'y_open5'] == pytest.approx(.15)
    assert out.loc[0, 'label_cash_paid_per_entry_share'] == 2.
    assert out.loc[0, 'label_cash_receivable_per_entry_share'] == 3.
    assert out.loc[0, 'label_cash_event_count'] == 2
