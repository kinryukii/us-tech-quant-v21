"""Synthetic raw-share lifecycle plus real shared execution integration."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.evaluation import consensus_shareholder_account as bridge
from scripts.research.a2.evaluation.consensus_cash_account import FeeConfig
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays, TargetDecision
from scripts.v22 import corporate_action_transition_r1 as ca


def ref(path):
    return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def binding(tmp_path, events):
    root=tmp_path/bridge.TASK;root.mkdir(exist_ok=True)
    contract=root/'DESIGN_FREEZE.json';contract.write_text(json.dumps(dict(task_id=bridge.TASK,status='SYNTHETIC_ONLY')))
    scope=root/'ACCOUNT_SOURCE_SCOPE.json';scope.write_text(json.dumps(dict(schema='CONSENSUS100_ACCOUNT_SOURCE_SCOPE_R1',task_id=bridge.TASK)))
    source=dict(task_id=bridge.TASK,quantity_coordinate='RAW_ACTUAL_SHARE',historical_quote_vintage_status='UNKNOWN',
        source_refs=[dict(path='synthetic://raw',sha256='a'*64)],coverage_gaps=['synthetic declared vendor provenance unknown'])
    return bridge.make_task_authority(events,frozen_contract_ref=ref(contract),source_scope_ref=ref(scope),market_source_binding=source)


def market(split=False):
    dates=pd.DatetimeIndex(['2025-06-02','2025-06-03','2025-06-04','2025-06-05','2025-06-06','2025-06-09'])
    values=np.array([100.,100.,50. if split else 100.,50. if split else 100.,50. if split else 100.,50. if split else 100.])[:,None]
    return MarketArrays(dates,['S'],values.copy(),values.copy(),adv=np.full(values.shape,1e9),signal_mask=np.arange(6)<5)


def entitlement():
    return ca.SourceBackedEntitlementEvent('synthetic dividend','CASH_DIVIDEND','new','S','2025-06-05','2025-06-05','2025-06-06',
        '2025-06-04T12:00:00Z',1.,'USD',ca.USD_PER_RAW_OLD_SHARE,ca.RAW_OLD_SHARE_COORDINATE,
        'TIER2_LOCAL_CANONICAL','synthetic://dividend','b'*64)


def source_binding(events, mappings):
    return dict(status='SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND',source_fingerprint='c'*64,
        event_fingerprints=[e.event_fingerprint for e in events],security_tickers=mappings,quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE)


def hold_then_exit(observed=None):
    def policy(di,ctx):
        if observed is not None:
            observed.append(dict(date=ctx.signal_date,units=ctx.current_units.copy(),cash=ctx.settled_cash.copy(),
                unsettled=ctx.unsettled_cash.copy(),receivable=ctx.receivable_value_usd.copy()))
        target=np.array([[.1 if di<3 else 0.]])
        return TargetDecision(target,ctx.decision_mask.copy(),'synthetic joint target')
    return policy


def test_full_shareholder_split_dividend_sale_settlement_and_single_fees(tmp_path):
    e=entitlement();events=(e,);m=market(split=True);observed=[]
    split=ca.CorporateActionTransition('2025-06-04','FORWARD_SPLIT','old','new','S','S',2.,0.,
        'TIER2_LOCAL_CANONICAL','synthetic://split','d'*64)
    before=Path(bridge.owner.__file__).read_bytes();ca_before=Path(ca.__file__).read_bytes()
    replay=bridge.run_shareholder_cash_account(m,['x'],hold_then_exit(observed),task_authority=binding(tmp_path,events),
        settlement_calendar=m.dates,fee_config=FeeConfig(10,.5,5,True),corporate_actions=(split,),
        corporate_action_known_at={split.event_fingerprint:'2025-06-03T12:00:00Z'},entitlement_events=events,
        entitlement_security_tickers={'old':'S','new':'S'},entitlement_source_binding=source_binding(events,{'old':'S','new':'S'}))
    assert len(replay.fills)==2
    np.testing.assert_allclose(replay.fills.transaction_cost,[.8,.8])
    assert observed[3]['units'][0,0]==pytest.approx(6.)
    assert observed[3]['receivable'][0]==pytest.approx(6.)
    assert observed[4]['unsettled'][0]==pytest.approx(299.2)
    assert replay.daily.loc[replay.daily.date.eq(m.dates[4]),'corporate_receivable'].iloc[0]==pytest.approx(6.)
    assert replay.daily.loc[replay.daily.date.eq(m.dates[5]),'settlement_release'].iloc[0]==pytest.approx(299.2)
    assert replay.final_cash[0]==pytest.approx(3004.4)
    assert replay.final_state['fractional_shares'][0,0]==0.
    assert replay.final_state['total_cash_assets'][0]==pytest.approx(3004.4)
    assert replay.metadata['quote_vintage_status']=='UNKNOWN' and replay.metadata['certified_NAV'] is False
    assert replay.audit['actual_cash_flow_identity_error_max']<1e-8
    assert Path(bridge.owner.__file__).read_bytes()==before and Path(ca.__file__).read_bytes()==ca_before


def test_empty_events_are_explicit_binding_not_assumed_full_coverage(tmp_path):
    m=market();events=()
    replay=bridge.run_shareholder_cash_account(m,['x'],hold_then_exit(),task_authority=binding(tmp_path,events),
        settlement_calendar=m.dates,entitlement_events=events,entitlement_security_tickers={},entitlement_source_binding=source_binding(events,{}))
    assert len(replay.fills)==2 and replay.metadata['conditional_shareholder_research_only']
    assert replay.metadata['task_account_authority']['market_source_binding']['coverage_gaps']


def test_old_task_authority_and_index_price_coordinate_fail_closed(tmp_path):
    authority=binding(tmp_path,())
    with pytest.raises(ValueError,match='NEW_TASK_SHAREHOLDER_AUTHORITY'):
        bridge.validate_task_authority((),dict(authority,task_id='V24_C_FULL_SELECTOR_FIXED_POLICY_FAST_R1'))
    with pytest.raises(ValueError,match='NEW_TASK_SHAREHOLDER_AUTHORITY'):
        bridge.validate_task_authority((),dict(authority,raw_price_coordinate='PIT_FORWARD_REHAB_INDEX'))
    changed=json.loads(json.dumps(authority));changed['market_source_binding']['quantity_coordinate']='PIT_FORWARD_REHAB_INDEX'
    with pytest.raises(ValueError,match='RAW_SHARE_MARKET_SOURCE_BINDING'):
        bridge.validate_task_authority((),changed)


def test_source_binding_mismatch_and_owner_change_fail_without_fill(tmp_path,monkeypatch):
    m=market();authority=binding(tmp_path,())
    with pytest.raises(ValueError,match='ENTITLEMENT_COVERAGE_EVENT_CATALOGUE'):
        bridge.run_shareholder_cash_account(m,['x'],hold_then_exit(),task_authority=authority,settlement_calendar=m.dates,
            entitlement_security_tickers={},entitlement_source_binding=dict(source_binding((),{}),event_fingerprints=['f'*64]))
    monkeypatch.setattr(bridge,'OWNER_SHA','0'*64)
    with pytest.raises(ValueError,match='SHAREHOLDER_OWNER_SOURCE_CHANGED'):
        bridge.run_shareholder_cash_account(m,['x'],hold_then_exit(),task_authority=authority,settlement_calendar=m.dates,
            entitlement_security_tickers={},entitlement_source_binding=source_binding((),{}))


def test_unsupported_quantity_event_keeps_account_unqualified(tmp_path):
    m=market();split=ca.CorporateActionTransition('2025-06-05','FORWARD_SPLIT','old','new','S','S',2.,1.,
        'TIER2_LOCAL_CANONICAL','synthetic://cash-split','d'*64)
    replay=bridge.run_shareholder_cash_account(m,['x'],hold_then_exit(),task_authority=binding(tmp_path,()),settlement_calendar=m.dates,
        corporate_actions=(split,),corporate_action_known_at={split.event_fingerprint:'2025-06-04T12:00:00Z'},
        entitlement_security_tickers={},entitlement_source_binding=source_binding((),{}))
    assert not replay.final_state['accounting_qualified'][0]
    assert replay.accounting_exceptions.reason.eq('UNSUPPORTED_OR_UNAVAILABLE_CORPORATE_ACTION').any()
    assert replay.daily.certified_nav.iloc[-1]!=replay.daily.certified_nav.iloc[-1]

def test_account_prefix_requires_exact_active_source_catalogue(tmp_path):
    e=entitlement();authority=binding(tmp_path,(e,));m=market()
    m.dates=pd.DatetimeIndex(['2025-06-06','2025-06-09','2025-06-10','2025-06-11','2025-06-12','2025-06-13'])
    with pytest.raises(ValueError,match='CALLER_EVENT_CATALOGUE_MUST_MATCH_ACCOUNT_PREFIX'):
        bridge.run_shareholder_cash_account(m,['x'],hold_then_exit(),task_authority=authority,settlement_calendar=m.dates,
            entitlement_events=(e,),entitlement_security_tickers={'new':'S'},entitlement_source_binding=source_binding((e,),{'new':'S'}))


def test_joint_risk_policy_reaches_shareholder_owner_and_metadata_is_not_reopened(tmp_path,monkeypatch):
    from scripts.research.a2.inference import consensus_joint_policy as joint
    m=market();events=();authority=binding(tmp_path,events);fee=FeeConfig(10,.5,5,True)
    forecasts=pd.DataFrame([dict(signal_date=d,ticker='S',mu=.05 if i<3 else -.1,sigma=.01,p_up=.8 if i<3 else .1,
        q10=.04 if i<3 else -.11,q50=.05 if i<3 else -.1,q90=.08 if i<3 else -.08) for i,d in enumerate(m.dates[:-1])])
    forecasts.attrs['unit']=joint.UNIT
    dates=pd.bdate_range(end=m.dates[0]-pd.Timedelta(days=1),periods=140)
    returns=pd.DataFrame(np.random.default_rng(13).normal(0,.01,(140,1)),index=dates,columns=['S'])
    returns.attrs['source_id']='SYNTHETIC_UNKNOWN'
    policy=joint.ConsensusJointPolicy(forecasts,returns,fee_config=fee)
    calls=[];original=bridge._metadata_ref
    def spy(*a,**kw):
        calls.append(a[0]['path']);return original(*a,**kw)
    monkeypatch.setattr(bridge,'_metadata_ref',spy)
    replay=bridge.run_shareholder_cash_account(m,['x'],policy,task_authority=authority,settlement_calendar=m.dates,
        fee_config=fee,entitlement_events=events,entitlement_security_tickers={},entitlement_source_binding=source_binding(events,{}))
    assert len(calls)==2
    assert replay.fills.side.eq('BUY').any() and replay.fills.side.eq('SELL').any()
    assert all(max(pd.Timestamp(x) for x in bundle.fitted_dates)<m.dates[0] for bundle in policy.risk_cache.values())
    assert replay.audit['actual_cash_flow_identity_error_max']<1e-8
    assert replay.metadata['shareholder_bridge_lineage']['ast_anchor_count']==4
    assert replay.final_state['total_cash_assets'][0]==pytest.approx(replay.final_cash[0]+replay.final_unsettled_cash[0])
