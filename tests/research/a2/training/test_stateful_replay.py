"""Synthetic-only replay orchestration; no actual forecast or economic read."""
import json
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import stateful_replay as r


def test_pending_phase_stops_before_source_or_numeric_read(tmp_path,monkeypatch):
    (tmp_path/'run_config.json').write_text(json.dumps({'phase':'ROOT_PENDING'}))
    monkeypatch.setattr(r,'assert_write_path',lambda *args:None)
    pins=[];monkeypatch.setattr(r,'_pin',lambda *args:pins.append(args))
    with pytest.raises(ValueError,match='ROOT_FREEZE_REQUIRED'):r.frozen_contract(tmp_path)
    assert pins==[] and not (tmp_path/'ACCOUNT_PATH_LOG.jsonl').exists()


@pytest.mark.parametrize('flag',('feature_available','prediction_qualified'))
def test_metadata_preserves_missing_forecast_keys_and_legacy_flags(flag):
    keys=pd.DataFrame({'signal_date':pd.to_datetime(['2023-01-03']*2),'ticker':['A','B'],'feature_available':[True,False]})
    meta=keys[['signal_date','ticker']].copy();meta[flag]=[True,False]
    r._packet_key_guard(keys,meta,flag)
    with pytest.raises(ValueError,match='DROPPED_OR_ADDED'):r._packet_key_guard(keys,meta.iloc[:1],flag)
    meta.loc[1,flag]=True
    with pytest.raises(ValueError,match='SOURCE_FLAG_NOT_BOUND'):r._packet_key_guard(keys,meta,flag)


def test_native_width_is_never_daily_collapsed_to_common_sigma():
    assert r._common_sigma(np.array([.01,.01]),.01)==.01
    with pytest.raises(ValueError,match='COMMON_FOLD'):r._common_sigma(np.array([.005,.015]),.01)
    with pytest.raises(ValueError,match='COMMON_FOLD'):r._common_sigma(np.array([.01]),None)


def fixture_market():
    dates=pd.to_datetime(['2023-12-28','2023-12-29','2024-01-02','2024-01-03'])
    names=[f'T{i:02d}' for i in range(20)];prices=np.full((4,20),10.)
    opens=prices.copy();opens[1,0]=np.nan
    top=np.ones((4,20),bool);top[-1]=False
    market=r.MarketArrays(dates,names,opens,prices,input_present=np.ones((4,20),bool),new_buy_eligible=top,
        signal_asof=[d.tz_localize('America/New_York')+pd.Timedelta(hours=16) for d in dates])
    candidates=[{'candidate_id':'B_REF','action':'raw','value_model':'synthetic','control':'none','gross':'fixed','risk':'diag'},
        {'candidate_id':'A_VALUE','action':'stateful','value_model':'synthetic','control':'none','gross':'fixed','risk':'diag'}]
    mu=np.full((4,20),.04);mu[2,1]=np.nan
    packet={'synthetic':{'mu':mu,'sigma':np.full(4,.001),'lineage':np.array(['SYNTHETIC_ONLY']*4)}}
    config={'base_currency':'USD','initial_nav':3000.,'initial_cash':3000.,'initial_holdings':[],
        'fractional_shares':True,'integer_share_rounding':False,'transaction_cost_bps':0.,'cash_interest':0.,
        'financing':False,'borrowed_cash':False,'long_only':True,'max_weight':1.,'max_positions':20,'max_invested':1.,'capacity_fraction':None}
    return market,candidates,packet,top,np.ones((4,20),bool),np.full((4,20),.03),config


@pytest.mark.parametrize('unsupported',(False,True))
def test_one_shared_engine_own_fills_persistent_years_and_local_ca_failclosed(unsupported,monkeypatch):
    market,candidates,packet,top,qualified,vol,config=fixture_market()
    original=r.run_continuous_account;calls=[]
    def common(*args,**kwargs):calls.append(True);return original(*args,**kwargs)
    monkeypatch.setattr(r,'run_continuous_account',common)
    exception=({'ticker':'T02','effective_date':'2024-01-02','reason':'SYNTHETIC_CASH_WITHOUT_AUTHORITY'},) if unsupported else ()
    stock=np.ones(top.shape,bool);stock[2,1]=False
    raw=np.ones(top.shape,bool);raw[-1]=False
    replay,frames=r.execute_market(market,candidates,packet,top,qualified,vol,config,stock_present=stock,raw_selector_present=raw,unsupported=exception)
    assert calls==[True] and len(frames['daily'])==8 and frames['daily'].date.nunique()==4
    assert frames['actions'].is_raw_top20.sum()==120 and len(frames['actions'])>=120
    failed=frames['execution_results'].loc[frames['execution_results'].ticker.eq('T00')&frames['execution_results'].execution_date.eq(market.dates[1])]
    assert len(failed)==2 and not frames['fills'].execution_date.ge('2026-01-01').any()
    holding=frames['positions'].loc[frames['positions'].ticker.eq('T01')&frames['positions'].date.eq(market.dates[-1])]
    assert len(holding)==2 and holding.entry_date.eq(market.dates[1]).all() and holding.holding_age.eq(2).all()
    assert holding.previous_actual_action.ne('NO_ACTUAL_FILL').all()
    action=frames['actions'].loc[frames['actions'].path_id.eq('A_VALUE')&frames['actions'].ticker.eq('T01')&frames['actions'].signal_date.eq(market.dates[2])]
    assert len(action)==1 and not action.policy_explicit.iloc[0] and action.policy_action.iloc[0]=='HOLD'
    assert not action.stock_forecast_input_present.iloc[0] and action.raw_selector_input_present.iloc[0] and action.decision_information_present_union.iloc[0]
    assert len(frames['continuation'])>=2 and not frames['continuation'].annual_reset.any()
    if unsupported:
        last=frames['daily'].loc[frames['daily'].date.eq(market.dates[-1])]
        assert not last.accounting_qualified.any() and last.certified_nav.isna().all()
    else:assert frames['daily'].accounting_qualified.all()


def test_static_risk_bundle_is_transformed_without_any_new_fit():
    from scripts.research.a2.risk.joint_risk_estimators import RiskBundle,risk_matrix
    bundle=RiskBundle('DIAG','FITTED',('A',),('2022-12-30T00:00:00',),estimated_assets=('A',),
        covariance=np.array([[.001]]),fallback_variance=.002,
        fitted_state={'return_unit':'SYNTHETIC_PROXY','return_horizon_sessions':1})
    covariance,metadata=risk_matrix(bundle,['A','UNKNOWN'],return_metadata=True)
    assert np.array_equal(covariance*5.,np.diag([.005,.01]))
    assert metadata['unknown_assets']==['UNKNOWN'] and metadata['strategy_eligibility_upgraded'] is False

def test_label_maturity_equal_calibration_start_stops_before_forecast_read(monkeypatch):
    from types import SimpleNamespace
    dates=pd.bdate_range("2022-10-06",periods=60)
    cutoff=pd.Timestamp("2023-01-01")
    fold={"calibration_sessions":dates,"calibration_start":dates[0],"cutoff_exclusive":cutoff,"calendar_sha256":"SYNTHETIC_CALENDAR"}
    receipt={"status":"TRAINED","scientific_target_qualified":True,"scientific_feature_pit_qualified":True,
        "train_label_maturity_max":dates[0].isoformat(),
        "reuse_tuple":{"fold":"ANNUAL_2023","calendar_sha256":"SYNTHETIC_CALENDAR","calibration_sessions":[d.isoformat() for d in dates],
        "training_signal_and_label_maturity_exclusive":dates[0].isoformat(),"cutoff_exclusive":cutoff.isoformat(),
        "calibration_label_maturity_exclusive":cutoff.isoformat(),"label_definition":r.LABEL,"feature_binding":{"features":list(r.FEATURES)}}}
    monkeypatch.setattr(r,"_old",lambda:None);monkeypatch.setattr(r,"_json",lambda path:receipt);monkeypatch.setattr(r,"_pin",lambda *args:None)
    reads=[];monkeypatch.setattr(r,"_read_projection",lambda *args:reads.append(True))
    reader=SimpleNamespace(annual_fold=lambda year:fold)
    packet={"source_kind":"V24_VALUE_OUTPUTS","annual":{"2023":{"receipt":{"path":"SYNTHETIC_ONLY","sha256":"0"*64}}}}
    with pytest.raises(ValueError,match="TRAIN_LABEL_CLOCK_MISMATCH"):
        r.read_packet(packet,reader,pd.DatetimeIndex([pd.Timestamp("2023-01-03")]),["A"])
    assert reads==[]


def test_fusion_retains_full_source_keys_when_expert_forecast_is_unavailable():
    keys=pd.DataFrame({'signal_date':pd.to_datetime(['2023-01-03']*3),'ticker':['A','B','C'],'feature_available':[True,True,False]})
    meta=keys[['signal_date','ticker']].copy();meta['prediction_qualified']=[True,False,False]
    r._packet_key_guard(keys,meta,'prediction_qualified',allow_unavailable=True)
    with pytest.raises(ValueError,match='SOURCE_FLAG_NOT_BOUND'):
        r._packet_key_guard(keys,meta,'prediction_qualified')
    meta.loc[2,'prediction_qualified']=True
    with pytest.raises(ValueError,match='SOURCE_FLAG_NOT_BOUND'):
        r._packet_key_guard(keys,meta,'prediction_qualified',allow_unavailable=True)


def test_fusion_wrong_estimator_role_rejected_before_expert_or_forecast_read(tmp_path,monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(r,'_pin',lambda *a:None);monkeypatch.setattr(r,'sha',lambda *a:'a'*64)
    pins=dict.fromkeys(['module_sha256','native_source_sha256','native_common_sha256','value_module_sha256','input_reader_sha256','input_manifest_sha256'],'a'*64)
    receipt={'reuse_tuple':{'source_pins':pins,'feature_binding_role':'DIRECT32'}}
    reads=[];monkeypatch.setattr(r,'_json',lambda *a:reads.append(True))
    with pytest.raises(ValueError,match='UNDERLYING32_ROLE'):
        r._fusion_receipt_guard(receipt,{},dict(fusion_module_sha256='a'*64),SimpleNamespace(run=tmp_path),2023)
    assert reads==[]


def test_fusion_future_meta_expert_stops_before_expert_projection(tmp_path,monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(r,'_pin',lambda *a:None);monkeypatch.setattr(r,'sha',lambda *a:'a'*64)
    pins=dict.fromkeys(['module_sha256','native_source_sha256','native_common_sha256','value_module_sha256','input_reader_sha256','input_manifest_sha256'],'a'*64)
    pred=tmp_path/'predictions/fusion/equal/2023.parquet';fit=tmp_path/'models/fusion/equal/2023/fit_receipt.json'
    record={'prediction':{'path':str(pred),'sha256':'b'*64},'receipt':{'path':str(fit),'sha256':'c'*64},'prediction_receipt':{'path':str(pred.with_suffix('.receipt.json')),'sha256':'d'*64}}
    receipt={'model_id':'equal','model_sha256':'e'*64,'reuse_tuple_sha256':'f'*64,'reuse_tuple':{'source_pins':pins,'feature_binding_role':'UNDERLYING_SOURCE32_NOT_FUSION_ESTIMATOR_INPUTS','packet':['ridge','hgb','lgb'],'model_input_columns':['expert_ridge','expert_hgb','expert_lgb'],'expert_oof_pins':[{'year':2023,'model_id':'ridge'}]}}
    publication={'status':'PUBLISHED','prediction_role':'MODEL_OOF','sha256':'b'*64,'model_sha256':'e'*64,'reuse_tuple_sha256':'f'*64,'fit_receipt_sha256':'c'*64,'producer_source_sha256':'a'*64,'input_manifest_sha256':'a'*64,'year':2023,'model_id':'equal','test_2026_rows_read':0,'path':str(pred),'fit_receipt_path':str(fit)}
    reads=[]
    def metadata(path):reads.append(str(path));return publication
    monkeypatch.setattr(r,'_json',metadata)
    with pytest.raises(ValueError,match='CURRENT_OR_FUTURE_EXPERT_YEAR'):
        r._fusion_receipt_guard(receipt,record,dict(fusion_module_sha256='a'*64),SimpleNamespace(run=tmp_path),2023)
    assert reads==[str(pred.with_suffix('.receipt.json'))]

def _friction(bps):
    return {'kind':'FIXED_ADVERSE_OPEN_SLIPPAGE','scenario_id':f'SYNTHETIC_{bps}',
            'one_way_bps':bps,'fee_bps':0,'benchmark':'NEXT_RAW_OPEN',
            'authority':'HYPOTHETICAL_RESEARCH_SCENARIO'}


def test_opt_in_adverse_open_slippage_is_cash_charged_once():
    market,candidates,packet,top,qualified,vol,config=fixture_market()
    friction=_friction(10)
    for c in candidates:c['execution_friction']=friction
    replay,frames=r.execute_market(market,candidates,packet,top,qualified,vol,config,
        stock_present=np.ones(top.shape,bool),raw_selector_present=top.copy(),execution_friction=friction)
    fills=replay.fills
    sign=np.where(fills.action.isin(['BUY','INCREASE']),1.,-1.)
    assert fills.action.isin(['BUY','INCREASE']).any() and fills.action.isin(['SELL','REDUCE']).any()
    assert np.allclose(fills.actual_fill_price,fills.price*(1+sign*.001))
    assert np.allclose(fills.actual_fill_notional,fills.actual_fill_price*fills.index_units)
    assert np.allclose(fills.transaction_cost,fills.slippage_amount)
    assert np.allclose(replay.daily.transaction_cost_amount,replay.daily.slippage_amount)
    assert replay.daily.transaction_fee.eq(0).all()
    assert replay.daily.cash_flow_identity_error.abs().max()<1e-8
    assert replay.daily.cost_identity_error.abs().max()<1e-8
    assert frames['costs'].costs_already_charged_in_cash.all()
    assert frames['gross'].input_time_qualification_verified.eq(False).all()


def test_policy_execution_schedule_mismatch_stops_before_common_engine(monkeypatch):
    market,candidates,packet,top,qualified,vol,config=fixture_market()
    for c in candidates:c['execution_friction']=_friction(10)
    calls=[];monkeypatch.setattr(r,'run_continuous_account',lambda *a,**k:calls.append(True))
    with pytest.raises(ValueError,match='FRICTION_IDENTITIES_DIFFER'):
        r.execute_market(market,candidates,packet,top,qualified,vol,config,
            stock_present=np.ones(top.shape,bool),raw_selector_present=top.copy(),execution_friction=_friction(20))
    assert calls==[]


def test_zero_opt_in_replay_retains_default_economic_ledger():
    market,candidates,packet,top,qualified,vol,config=fixture_market()
    kwargs={'stock_present':np.ones(top.shape,bool),'raw_selector_present':top.copy()}
    baseline,_=r.execute_market(market,candidates,packet,top,qualified,vol,config,**kwargs)
    for c in candidates:c['execution_friction']=_friction(0)
    zero,_=r.execute_market(market,candidates,packet,top,qualified,vol,config,execution_friction=_friction(0),**kwargs)
    for name in ('daily','positions','orders','execution_results'):
        before=getattr(baseline,name);after=getattr(zero,name)
        pd.testing.assert_frame_equal(before,after[before.columns],check_exact=True)

def test_parent_manifest_refresh_cannot_modify_frozen_bytes(tmp_path,monkeypatch):
    manifest=tmp_path/'input_manifest.json';manifest.write_text('FROZEN',encoding='utf-8')
    def mutating_reader(parent):
        (parent/'input_manifest.json').write_text('CHANGED',encoding='utf-8')
    monkeypatch.setattr(r,'InputReader',mutating_reader)
    with pytest.raises(ValueError,match='REFRESH_REFUSED'):r._read_parent_inputs_readonly(tmp_path)
    assert manifest.read_bytes()==b'FROZEN'


def test_equal_parent_manifest_refresh_remains_readonly(tmp_path,monkeypatch):
    manifest=tmp_path/'input_manifest.json';manifest.write_text('FROZEN',encoding='utf-8');before=manifest.stat().st_mtime_ns
    def equal_reader(parent):
        (parent/'input_manifest.json').write_text('FROZEN',encoding='utf-8')
        return 'SYNTHETIC_READER'
    monkeypatch.setattr(r,'InputReader',equal_reader)
    assert r._read_parent_inputs_readonly(tmp_path)=='SYNTHETIC_READER'
    assert manifest.stat().st_mtime_ns==before

def _synthetic_entitlement(pay_date='2024-01-03',available_at='2023-12-28T12:00:00Z',ex_date='2024-01-02'):
    from scripts.v22.corporate_action_transition_r1 import (
        SourceBackedEntitlementEvent, RAW_OLD_SHARE_COORDINATE, USD_PER_RAW_OLD_SHARE)
    event=SourceBackedEntitlementEvent(
        event_id='SYNTHETIC_T02_CASH',action_type='CASH_DIVIDEND',
        old_security_id='SYNTHETIC_T02_COMMON',ticker='T02',
        ex_date=ex_date,record_date=ex_date,pay_date=pay_date,
        available_at=available_at,cash_per_old_share=1.,currency='USD',
        amount_unit=USD_PER_RAW_OLD_SHARE,quantity_coordinate=RAW_OLD_SHARE_COORDINATE,
        source_type='TIER2_LOCAL_CANONICAL',source_reference='synthetic://cash-terms',
        source_fingerprint='d'*64)
    mapping={event.old_security_id:event.ticker}
    binding=dict(status='SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND',
        source_fingerprint='e'*64,event_fingerprints=[event.event_fingerprint],
        security_tickers=mapping,quantity_coordinate=RAW_OLD_SHARE_COORDINATE)
    return dict(entitlement_enabled=True,entitlement_events=(event,),
        entitlement_security_tickers=mapping,entitlement_source_binding=binding)


def _execute_entitlement_fixture(session_dates=None,**options):
    market,candidates,packet,top,qualified,vol,config=fixture_market()
    if session_dates is not None:
        dates=pd.to_datetime(session_dates)
        market=r.MarketArrays(dates,market.tickers,market.open,market.close,
            input_present=market.input_present,new_buy_eligible=market.new_buy_eligible,
            signal_asof=[d.tz_localize('America/New_York')+pd.Timedelta(hours=16) for d in dates])
    # Ex-session ownership precedes a policy exit, so selling must preserve claims.
    packet['synthetic']['mu'][1,2]=-.04
    return r.execute_market(market,candidates,packet,top,qualified,vol,config,
        stock_present=np.ones(top.shape,bool),raw_selector_present=top.copy(),**options)


def test_entitlement_default_off_preserves_every_existing_ledger():
    baseline,before=_execute_entitlement_fixture()
    disabled,after=_execute_entitlement_fixture(entitlement_enabled=False)
    assert set(before)==set(after) and 'entitlements' not in after
    for name in before:
        pd.testing.assert_frame_equal(before[name],after[name],check_exact=True)
    assert not disabled.metadata.get('entitlement_lifecycle_enabled',False)


def test_entitlement_opt_in_persists_receivable_payment_after_sale_and_full_state():
    replay,frames=_execute_entitlement_fixture(**_synthetic_entitlement())
    snapshots=frames['entitlements'].loc[frames['entitlements'].phase.eq('EX_PRETRADE_RAW_SHARE_SNAPSHOT')]
    assert len(snapshots)==2 and (snapshots.entitled_raw_shares>0).all()
    daily=frames['cash']
    on_ex=daily.loc[daily.date.eq(pd.Timestamp('2024-01-02'))]
    on_pay=daily.loc[daily.date.eq(pd.Timestamp('2024-01-03'))]
    assert (on_ex.receivable_value_usd>0).all() and on_ex.entitlement_cash_flow_usd.eq(0).all()
    assert on_pay.receivable_value_usd.eq(0).all() and (on_pay.entitlement_cash_flow_usd>0).all()
    sold=replay.fills.loc[replay.fills.ticker.eq('T02') & replay.fills.execution_date.eq(pd.Timestamp('2024-01-02'))]
    exited=sold.loc[sold.path_id.eq('A_VALUE')]
    assert len(exited)==1 and exited.side.eq('SELL').all() and exited.index_units_after.eq(0).all()
    assert replay.daily.accounting_qualified.all()
    assert replay.audit['actual_cash_flow_identity_error_max']<1e-8
    for row in frames['entitlement_state'].itertuples():
        state=json.loads(row.state_json)
        assert state['paid_event_ids']==['SYNTHETIC_T02_CASH'] and state['receivables']==[]
        assert state['catalogue_fingerprint'] and state['security_binding_fingerprint']
        assert state['ex_quantities'] and state['blocked_events']==[]
        assert 'FULL_PREFIX_RECONSTRUCTION_REQUIRED' in row.pending_orders_semantics
        assert json.loads(row.source_binding_json)['status']=='SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND'


def test_unpaid_claim_remains_separate_from_spendable_cash_in_continuation():
    replay,frames=_execute_entitlement_fixture(
        session_dates=['2023-12-27','2023-12-28','2023-12-29','2024-01-02'],
        **_synthetic_entitlement(ex_date='2023-12-29',pay_date='2024-01-05'))
    cash_rows=frames['continuation'].loc[frames['continuation'].row_type.eq('CASH')].set_index('path_id')
    assert (cash_rows.receivable_value_usd>0).all()
    for i,path in enumerate(('B_REF','A_VALUE')):
        assert cash_rows.loc[path,'cash']==replay.final_state['cash'][i]
        state=json.loads(frames['entitlement_state'].set_index('path_id').loc[path,'state_json'])
        assert len(state['receivables'])==1 and state['paid_event_ids']==[]
        assert state['receivables'][0]['amount_usd']==cash_rows.loc[path,'receivable_value_usd']
        assert state['receivables'][0]['old_security_id']=='SYNTHETIC_T02_COMMON'
        assert state['receivables'][0]['ex_date']=='2023-12-29' and state['last_session']=='2024-01-02'


@pytest.mark.parametrize('kind',('no_opt_in','catalogue_mismatch','missing_binding','non_bool'))
def test_entitlement_invalid_binding_stops_before_policy(monkeypatch,kind):
    args=_synthetic_entitlement()
    if kind=='no_opt_in':
        args['entitlement_enabled']=False
        error='EXPLICIT_OPT_IN'
    elif kind=='catalogue_mismatch':
        args['entitlement_source_binding']['event_fingerprints']=[]
        error='CATALOGUE_MISMATCH'
    elif kind=='missing_binding':
        args['entitlement_source_binding']=None
        error='SOURCE_COVERAGE_BINDING_REQUIRED'
    else:
        args={'entitlement_enabled':'true'}
        error='OPT_IN_MUST_BE_BOOL'
    calls=[]
    monkeypatch.setattr(r.StatefulOverlay,'__call__',lambda *a:calls.append(True))
    with pytest.raises(ValueError,match=error):
        _execute_entitlement_fixture(**args)
    assert calls==[]


def test_entitlement_forwarding_never_removes_unsupported_or_backfills_late_terms():
    unknown=({'ticker':'T02','effective_date':'2024-01-02','reason':'SYNTHETIC_UNPROVED_CLASSIFICATION'},)
    replay,frames=_execute_entitlement_fixture(unsupported=unknown,
        **_synthetic_entitlement(available_at='2024-01-02T15:00:00Z'))
    assert not replay.daily.loc[replay.daily.date.ge('2024-01-02'),'accounting_qualified'].any()
    assert frames['cash'].entitlement_cash_flow_usd.eq(0).all()
    assert replay.metadata['corporate_action_exceptions']==list(unknown)
    states=[json.loads(v) for v in frames['entitlement_state'].state_json]
    assert all(state['blocked_events'] for state in states)



def test_qualification_cash_and_entitlement_identity_separate_from_quote():
    replay,frames=_execute_entitlement_fixture(**_synthetic_entitlement())
    q=r.qualification_checks(replay,'B_REF')
    assert q['cash_identity_correct'] and q['entitlement_identity_correct']
    assert q['accounting_qualified'] and q['quote_qualified']
    assert not q['full_window_752_sessions'] and not q['eligible_for_selection']
    replay.positions.loc[replay.positions.path_id.eq('B_REF'),'stale']=True
    q=r.qualification_checks(replay,'B_REF')
    assert q['cash_identity_correct'] and q['entitlement_identity_correct']
    assert not q['quote_qualified'] and q['stale_holding_rows']>0
    replay.entitlements.loc[replay.entitlements.phase.eq('CASH_PAID'),'spendable_cash_delta']=0.
    assert not r.qualification_checks(replay,'B_REF')['entitlement_identity_correct']



def _synthetic_terminal(settle=True):
    from scripts.v22.corporate_action_transition_r1 import SourceBackedTerminalEvent,SourceBackedTerminalSettlement
    payment=SourceBackedTerminalSettlement(event_id='SYNTHETIC_TERMINAL_T02',old_security_id='SYNTHETIC_T02_COMMON',
        pay_date='2024-01-03',available_at='2024-01-03T12:00:00Z',cash_per_old_share=5.,currency='USD',
        amount_unit='USD_PER_RAW_OLD_SHARE',quantity_coordinate='RAW_OLD_SECURITY_SHARES',
        source_type='TIER2_LOCAL_CANONICAL',source_reference='synthetic://payment',source_fingerprint='e'*64) if settle else None
    event=SourceBackedTerminalEvent(event_id='SYNTHETIC_TERMINAL_T02',old_security_id='SYNTHETIC_T02_COMMON',ticker='T02',
        effective_at='2024-01-02T14:30:00Z',available_at='2023-12-28T12:00:00Z',cash_per_old_share=5.,currency='USD',
        amount_unit='USD_PER_RAW_OLD_SHARE',quantity_coordinate='RAW_OLD_SECURITY_SHARES',
        quantity_source_reference='synthetic://share-coordinate',quantity_source_fingerprint='b'*64,
        source_type='TIER2_LOCAL_CANONICAL',source_reference='synthetic://closing',source_fingerprint='c'*64,settlement=payment)
    mapping={event.old_security_id:event.ticker}
    binding=dict(status='SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND',source_fingerprint='d'*64,
        event_fingerprints=[event.event_fingerprint],security_tickers=mapping,quantity_coordinate='RAW_OLD_SECURITY_SHARES')
    return dict(entitlement_enabled=True,entitlement_events=(event,),entitlement_security_tickers=mapping,entitlement_source_binding=binding)


@pytest.mark.parametrize('settle',[False,True])
def test_runner_terminal_consumer_and_qualification_separate_rights_from_payment(settle):
    replay,frames=_execute_entitlement_fixture(**_synthetic_terminal(settle))
    assert 'entitlements' in frames and 'entitlement_state' in frames
    assert not replay.positions.loc[replay.positions.ticker.eq('T02'),'date'].ge('2024-01-02').any()
    assert not replay.fills.loc[replay.fills.ticker.eq('T02'),'execution_date'].ge('2024-01-02').any()
    q=r.qualification_checks(replay,'B_REF')
    assert q['cash_identity_correct'] and q['entitlement_identity_correct'] and q['terminal_identity_correct']
    assert q['terminal_settlement_qualified']==settle and q['accounting_qualified']==settle
    assert q['quote_qualified'] and not q['eligible_for_selection']  # Synthetic short window, never production PASS.
    if settle:
        replay.entitlements.loc[replay.entitlements.phase.eq('SECURITY_EXTINGUISHED'),'remaining_raw_shares']=1.
        assert not r.qualification_checks(replay,'B_REF')['terminal_identity_correct']
    else:
        assert replay.final_state['cash_receivables'] and replay.accounting_exceptions.reason.eq('TERMINAL_SETTLEMENT_AUTHORITY_MISSING').all()


def test_runner_terminal_source_bundle_boundary_and_frozen_payload(tmp_path,monkeypatch):
    import joblib
    kwargs=_synthetic_terminal(True)
    kwargs['entitlement_source_binding']['manifest']={'removal_keys':[]}
    bundle=tmp_path/'SYNTHETIC_bundle.joblib';joblib.dump(kwargs,bundle)
    b=dict(cash_source_bundle={'path':str(bundle),'sha256':r.sha(bundle)},cash_binding_semantic_fingerprint='d'*64,
        entitlement_catalogue_fingerprints=[kwargs['entitlement_events'][0].event_fingerprint],
        security_tickers=kwargs['entitlement_security_tickers'],training_label_contract='PARENT_UNCHANGED')
    market,*_=fixture_market()
    _,remaining,out,meta=r._bound_entitlement_inputs({'source_account_binding':b},market,(),())
    assert remaining==() and out['entitlement_events']==kwargs['entitlement_events']
    assert meta['training_label_contract']=='PARENT_UNCHANGED'
    b['entitlement_catalogue_fingerprints']=[]
    with pytest.raises(ValueError,match='CATALOGUE_PAYLOAD_CHANGED'):
        r._bound_entitlement_inputs({'source_account_binding':b},market,(),())


def test_runner_missing_terminal_snapshot_cannot_pass_audit():
    replay,_=_execute_entitlement_fixture(**_synthetic_terminal(True))
    assert r.qualification_checks(replay,'B_REF')['terminal_identity_correct']
    replay.entitlements=replay.entitlements.loc[~replay.entitlements.phase.eq('TERMINAL_PRE_EFFECTIVE_RAW_SHARE_SNAPSHOT')]
    assert not r.qualification_checks(replay,'B_REF')['terminal_identity_correct']



def test_qualification_is_local_to_actual_path_and_never_polluted_by_other_account():
    from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision
    market,_,_,_,_,_,config=fixture_market()
    def policy(j,ctx):
        weights=np.zeros_like(ctx.current_weights)
        if j==0:
            weights[0,2]=1.;weights[1,3]=1.
            return TargetDecision(weights,ctx.decision_mask)
        return TargetDecision(weights,np.zeros_like(ctx.decision_mask))
    replay=r.run_continuous_account(market,['held','other'],policy,config,
        **_synthetic_entitlement(available_at='2024-01-02T15:00:00Z'))
    held=r.qualification_checks(replay,'held');other=r.qualification_checks(replay,'other')
    assert not held['entitlement_identity_correct'] and not held['accounting_qualified']
    assert held['actual_CA_exception_rows']==1
    assert other['entitlement_identity_correct'] and other['accounting_qualified']
    assert other['actual_CA_exception_rows']==0 and other['accounting_exception_keys']==[]
