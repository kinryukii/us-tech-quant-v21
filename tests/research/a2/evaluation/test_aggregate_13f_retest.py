"""Synthetic aggregate pool clocks and existing-owner wiring; no real data."""
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.evaluation import aggregate_13f_retest as a


def fixture():
    days = pd.DatetimeIndex(['2026-02-17','2026-02-18','2026-02-19'])
    schedule = pd.DataFrame([
        dict(snapshot_id='old',quarter='2025Q3',effective_at='2025-11-21T16:00:00-05:00',institution_count=25),
        dict(snapshot_id='new',quarter='2025Q4',effective_at='2026-02-17T17:00:00-05:00',institution_count=25),
        dict(snapshot_id='old_revision',quarter='2025Q3',effective_at='2026-02-18T15:00:00-05:00',institution_count=25)])
    members = pd.DataFrame([dict(snapshot_id=s,cusip=f'C{i:08d}',amount_rank=i+1)
        for s in schedule.snapshot_id for i in range(100)])
    identity = pd.DataFrame([dict(signal_date=d,cusip=f'C{i:08d}',ticker=f'S{i:03d}',security_id=f'SID{i}')
        for d in days for i in range(100)])
    return schedule,members,identity,days


def test_afterclose_and_newer_quarter_precede_late_old_revision():
    p = a.project_universe(*fixture())
    assert p['schedule'].source_snapshot_id.tolist() == ['old','new','new']
    assert p['schedule'].institution_count.eq(25).all()
    assert len(p['members']) == 300


def test_missing_identity_stays_in_top100_and_never_substitutes_101():
    s,m,i,d = fixture(); i = i.loc[~i.cusip.eq('C00000099')]
    p = a.project_universe(s,m,i,d)
    assert p['schedule'].universe_member_count.eq(100).all()
    assert p['schedule'].mapped_count.eq(99).all()
    assert p['members'].ticker.isna().sum() == 3
    assert p['members'].amount_rank.max() == 100


@pytest.mark.parametrize('kind',['less_than_100','future_identity','collision','naive_publication'])
def test_invalid_source_fails_closed(kind):
    s,m,i,d = fixture()
    if kind == 'less_than_100': m = m.loc[m.amount_rank.ne(100)]
    elif kind == 'future_identity': i['available_at'] = '2026-02-19T23:00:00Z'
    elif kind == 'collision': i['ticker'] = 'SAME'
    else: s['effective_at'] = '2026-02-17'
    with pytest.raises(ValueError): a.project_universe(s,m,i,d)


def test_original_rank_owner_receives_all_100_before_original_flags(monkeypatch):
    s,m,i,d = fixture(); p = a.project_universe(s,m,i,d)
    f = pd.DataFrame([dict(trade_date=date,ticker=f'S{n:03d}',**dict.fromkeys(a.inputs.FEATURES,1.))
        for date in d for n in range(100)])
    def ranked(features,schedule,members,ledger,models,columns):
        assert members.groupby('snapshot_id').size().eq(100).all()
        r = pd.DataFrame([dict(target_date=date,ticker=f'S{n:03d}',rank=n+1,score=100-n,universe_quarter='2025Q3')
            for date in d for n in range(100)])
        return r,pd.DataFrame(dict(status=['READY']*len(d)))
    monkeypatch.setattr(a.ranking,'ranked_predictions',ranked)
    monkeypatch.setattr(a.authority,'load_descriptive_authority',lambda v:v)
    monkeypatch.setattr(a.authority,'validate_descriptive_input_dates',lambda *args,**kw:None)
    models = dict(feature_columns=a.inputs.FEATURES,artifacts={'2026':{'sha256':a.authority.RAW_SELECTOR_SHA256}})
    r,c,flags = a.rank_and_flags(f,p,models,SimpleNamespace(task_id=a.TASK))
    assert len(r)==300 and flags.groupby('signal_date').is_raw_top20.sum().eq(20).all()
    assert flags.is_max_group.all()
    assert flags.raw_selector_input_present.all()


def test_partial_pool_retains_original_no_support_semantics(monkeypatch):
    s,m,i,d = fixture(); p = a.project_universe(s,m,i,d)
    features = pd.DataFrame([dict(trade_date=date,ticker=f'S{n:03d}',**dict.fromkeys(a.inputs.FEATURES,1.)) for date in d for n in range(98)])
    ranked = pd.DataFrame([dict(target_date=date,ticker=f'S{n:03d}',rank=n+1,score=100-n,universe_quarter='2025Q3') for date in d for n in range(98)])
    coverage = pd.DataFrame(dict(status=['PARTIAL']*3,universe_member_count=[100]*3,eligible_count=[98]*3))
    monkeypatch.setattr(a.ranking,'ranked_predictions',lambda *args:(ranked,coverage))
    monkeypatch.setattr(a.authority,'load_descriptive_authority',lambda v:v)
    monkeypatch.setattr(a.authority,'validate_descriptive_input_dates',lambda *args,**kw:None)
    models = dict(feature_columns=a.inputs.FEATURES,artifacts={'2026':{'sha256':a.authority.RAW_SELECTOR_SHA256}})
    _,actual,flags = a.rank_and_flags(features,p,models,SimpleNamespace(task_id=a.TASK))
    assert actual.status.eq('PARTIAL').all() and actual.universe_member_count.eq(100).all()
    assert flags.groupby('signal_date').is_raw_top20.sum().eq(20).all()
    assert not flags.ticker.isin(['S098','S099','S100']).any()


def test_empty_original_support_is_explicit_and_no_fake_predict(monkeypatch):
    dates = pd.DatetimeIndex(['2026-01-02','2026-01-05'])
    auth = SimpleNamespace(start=dates[0],end=dates[-1])
    monkeypatch.setattr(a.authority,'load_descriptive_authority',lambda value: value)
    monkeypatch.setattr(a.inputs,'build_proxy_samples',lambda *args,**kw:({'buy':pd.DataFrame(),'replace':pd.DataFrame()},{}))
    def fail(*args): raise AssertionError('empty R6 support must not invoke native inference')
    monkeypatch.setattr(a.inference,'predict_r6_frozen',fail)
    def value(bundle,frame,authority):
        return pd.DataFrame(dict(signal_date=dates,ticker='S',prediction_qualified=False))
    monkeypatch.setattr(a.inference,'predict_value_frozen',value)
    bundles = {cid:SimpleNamespace(objective=o,features=f) for cid,o,f in zip(a.authority.MODEL_IDS,
        ('buy','replace','ngboost'),(a.decision.SINGLE,a.decision.PAIR,a.inputs.FEATURES))}
    flags = pd.DataFrame(dict(signal_date=dates))
    out = a.infer_heads(flags,dates,bundles,auth,history_flags=pd.DataFrame())
    assert all(v['support'].status.eq('NO_SUPPORT').all() for v in out['inference_evidence'].values())
    assert all(not v for v in out['action_packets'].values())


def test_random_window_slices_frozen_proxy_predictions_without_rebuilding(monkeypatch):
    dates = pd.bdate_range('2026-01-02',periods=5)
    market = a.replay.MarketArrays(dates,['S'],np.ones((5,1)),np.ones((5,1)))
    pred = pd.DataFrame(dict(signal_date=dates,ticker='S',cohort_age_sessions=range(10,15)))
    model = object()
    full = dict(market=market,account={'initial_nav':3000},top=np.ones((5,1),bool),qualified=np.ones((5,1),bool),
        vol=np.ones((5,1)),stock_present=np.ones((5,1),bool),raw_selector_present=np.ones((5,1),bool),
        packets={'ridge':dict(mu=np.ones((5,1)),sigma=np.ones(5),lineage=np.arange(5))},
        sid_by_key={(d,'S'):'SID' for d in dates},action_packets={'BUY':{dates[2]:[{'age':12}]}},
        inference_evidence={'BUY':dict(bundle=model,predictions=pred,samples=pred,support=pred)})
    auth = SimpleNamespace(start=dates[2],end=dates[-1])
    monkeypatch.setattr(a.authority,'load_descriptive_authority',lambda value:value)
    w = dict(start=str(dates[2].date()),end=str(dates[-1].date()),first_execution_date=str(dates[3].date()))
    out = a.slice_account_inputs(full,w,auth,account_source_kwargs={'source':'WINDOW_OWNER'})
    assert list(out['inference_evidence']['BUY']['samples'].cohort_age_sessions)==[12,13,14]
    assert out['inference_evidence']['BUY']['bundle'] is model
    assert out['packets']['ridge']['lineage'].tolist()==[2,3,4]
    assert out['market'].dates.equals(dates[2:]) and len(full['market'].dates)==5
    assert out['account_source_kwargs']=={'source':'WINDOW_OWNER'}


def test_wrong_raw_model_fails_before_ranking(monkeypatch):
    monkeypatch.setattr(a.authority,'load_descriptive_authority',lambda v:v)
    monkeypatch.setattr(a.authority,'validate_descriptive_input_dates',lambda *args,**kw:None)
    def forbidden(*args): raise AssertionError('wrong model reached scoring')
    monkeypatch.setattr(a.ranking,'ranked_predictions',forbidden)
    features = pd.DataFrame({'trade_date':[pd.Timestamp('2026-01-02')]})
    models = dict(feature_columns=a.inputs.FEATURES,artifacts={'2026':{'sha256':'WRONG_MODEL'}})
    with pytest.raises(ValueError,match='MODEL_VINTAGES'):
        a.rank_and_flags(features,{},models,SimpleNamespace(task_id=a.TASK))


def test_original_samples_context_and_label_firewall(monkeypatch):
    days=pd.bdate_range('2023-01-03','2026-01-09');dates=days[days.year==2026]
    auth=SimpleNamespace(start=dates[0],end=dates[-1])
    monkeypatch.setattr(a.authority,'load_descriptive_authority',lambda value:value)
    monkeypatch.setattr(a.authority,'validate_descriptive_input_dates',lambda *args,**kw:None)
    from scripts.research.a2.training import stateful_inputs
    columns=list(dict.fromkeys((*stateful_inputs.PRED_FLAGS,*a.inputs.FEATURES,*a.decision.PRED_EXTRA)))
    records=[]
    for d in days:
        for n in range(20):
            row=dict.fromkeys(columns,True);row.update(dict.fromkeys(a.inputs.FEATURES,1.))
            row.update(signal_date=d,ticker=f'S{n:02d}',security_id=f'SID{n}',raw_a2_rank=n+1,
                raw_a2_prediction=1.,raw_a2_oof_split='SYNTH',feature_source='SYNTH',
                active_13f_quarter='SYNTH',raw_top20_set_count=20)
            records.append(row)
    flags=pd.DataFrame(records);history=flags.loc[flags.signal_date.lt('2026-01-01')];test=flags.loc[flags.signal_date.ge('2026-01-01')]
    def r6(bundle,frame,authority):
        assert not (set(frame)&a.inference._FORBIDDEN)
        assert frame.signal_date.ge(dates[0]).all()
        keys=[k for k in ('signal_date','sample_id','ticker','security_id','incumbent','incumbent_sid','cohort_age_sessions') if k in frame]
        return frame[keys].assign(p_superior=.7,model_year=2025).reset_index(drop=True)
    def value(bundle,frame,authority):
        assert not (set(frame)&a.inference._FORBIDDEN)
        return frame[['signal_date','ticker']].assign(prediction_qualified=True,prediction=.1,value_sigma=.01,year=2025)
    monkeypatch.setattr(a.inference,'predict_r6_frozen',r6);monkeypatch.setattr(a.inference,'predict_value_frozen',value)
    bundles={cid:SimpleNamespace(objective=o,features=f) for cid,o,f in zip(a.authority.MODEL_IDS,
        ('buy','replace','ngboost'),(a.decision.SINGLE,a.decision.PAIR,a.inputs.FEATURES))}
    out=a.infer_heads(test,days,bundles,auth,history_flags=history)
    assert out['sample_audit']['phase']=='ORIGINAL_2023_EXOGENOUS_COHORT_NOT_FRESH_ACCOUNT_STATE'
    assert out['inference_evidence'][a.authority.MODEL_IDS[2]]['support'].eligible_count.eq(20).all()
    with pytest.raises(ValueError,match='PROXY_COMPLETE_PRE2026_PHASE_REQUIRED'):
        a.infer_heads(test,days,bundles,auth,history_flags=history.loc[history.signal_date.ge('2025-11-21')])


def test_continuous_top20_truncation_does_not_wash_out_after_21_days():
    days=pd.bdate_range('2024-01-02',periods=110)
    flags=pd.DataFrame([dict(signal_date=d,ticker='S',security_id='SID',raw_a2_rank=1,
        raw_a2_prediction=1.,new_buy_eligible=True,feature_available=True,is_raw_top20=True,
        raw_top20_set_complete=True,**dict.fromkeys(a.inputs.FEATURES,1.)) for d in days])
    labels=pd.DataFrame(columns=a.decision.LABEL_COLS)
    full,_=a.decision.build_samples(flags,labels,days)
    truncated,_=a.decision.build_samples(flags.loc[flags.signal_date.isin(days[5:])],labels,days[5:])
    later=days[71]
    assert len(full['hold'].loc[full['hold'].signal_date.eq(later)])==1
    assert len(truncated['buy'].loc[truncated['buy'].signal_date.eq(later)])==1
    assert full['hold'].loc[full['hold'].signal_date.eq(later),'cohort_age_sessions'].iloc[0]==4
    assert truncated['buy'].loc[truncated['buy'].signal_date.eq(later),'cohort_age_sessions'].iloc[0]==0


def test_nan_raw_diagnostic_preserves_original_fixed_gross_decisions():
    from scripts.research.a2.training.stateful_account import reference_policy_class
    owner=reference_policy_class()
    names=np.array([f'S{n:02d}' for n in range(22)])
    dates=pd.DatetimeIndex(['2025-12-31'])
    top=np.array([[True]*20+[False]*2]); qualified=np.array([[True]*21+[False]])
    units=np.zeros((1,22)); units[0,[0,21]]=[3.,2.]
    weights=np.zeros((1,22)); weights[0,[0,21]]=[.3,.2]
    context=SimpleNamespace(current_units=units,current_weights=weights,path_ids=('B',),
        decision_mask=np.ones((1,22),bool),buy_allowed=qualified,available_budget=np.array([.5]),
        tickers=names,cash=np.array([1500.]),nav=np.array([3000.]),signal_date=dates[0])
    absent=a.raw_diagnostic_packet(dates,names)
    expected=owner(np.arange(22,dtype=float)[None,:],np.array([.02]),None,None,
        np.ones((1,22))*.01,top,qualified,np.array(['ACTUAL_DIAGNOSTIC_ONLY']))(0,context)
    actual=owner(absent['mu'],absent['sigma'],None,None,np.ones((1,22))*.01,
        top,qualified,absent['lineage'])(0,context)
    np.testing.assert_array_equal(actual.weights,expected.weights)
    np.testing.assert_array_equal(actual.explicit_mask,expected.explicit_mask)
    assert actual.raw_evidence_id=='NOT_APPLICABLE_RAW_BRANCH_NO_VALUE_FORECAST'
    assert not actual.explicit_mask[0,21]  # original out-of-pool held units stay frozen


def test_new_sessions_splice_preserves_prefix_and_causal_features():
    from scripts.research.a2.evaluation.aggregate_13f_retest import append_new_raw_sessions
    from scripts.v22.abcde_a2_r1_nonlinear_cross_sectional_modeling import build_stock_state_features
    dates=pd.bdate_range('2024-01-02',periods=152)
    x=np.arange(152,dtype=float)
    all_raw=pd.DataFrame(dict(trade_date=dates,open=100+x*.2,high=102+x*.2,
        low=99+x*.2,close=101+x*.2,volume=10000+x*10))
    prefix=all_raw.iloc[:150].copy()
    current=all_raw.iloc[100:].copy()
    current.loc[current.index[-3],'volume']+=100
    merged,tail,proof=append_new_raw_sessions(prefix,current,dates,ticker='SYNTH',source_refs=[])
    pd.testing.assert_frame_equal(prefix,merged.iloc[:150])
    assert len(tail)==2 and len(proof['overlap_conflicts'])==1
    before=build_stock_state_features(prefix.assign(ticker='SYNTH')[['ticker','trade_date','close','volume']])
    after=build_stock_state_features(merged.assign(ticker='SYNTH')[['ticker','trade_date','close','volume']])
    pd.testing.assert_frame_equal(before,after.iloc[:150].reset_index(drop=True))
    assert proof['preserve_parent_prefix'] and not proof['full_snapshot_equivalence_claimed']


def test_new_sessions_splice_rejects_share_price_coordinate_change():
    from scripts.research.a2.evaluation.aggregate_13f_retest import append_new_raw_sessions
    dates=pd.bdate_range('2024-01-02',periods=12)
    raw=pd.DataFrame(dict(trade_date=dates,open=100.,high=102.,low=99.,close=101.,volume=1000.))
    revised=raw.copy();revised.loc[9,['open','high','low','close']]*=2
    with pytest.raises(ValueError,match='RAW_PRICE_COORDINATE_CONFLICT'):
        append_new_raw_sessions(raw.iloc[:10],revised,dates,ticker='SYNTH',source_refs=[])


def test_mapping_aggregate_source_and_identity_refs_remain_distinct(monkeypatch):
    from scripts.research.a2.inference import historical_top40_universe as owner
    schedule,members,identity,calendar=fixture()
    identity_ref=dict(path='synthetic_identity.parquet',sha256='identity-evidence')
    source_ref=dict(path='synthetic_aggregate_source.json',sha256='aggregate-holdings')
    def assemble(versions,frozen,sessions,mode,lineage):
        assert frozen is identity and sessions.equals(calendar)
        assert mode=='registry25'
        assert lineage==dict(frozen_members=identity_ref,aggregate_source=source_ref)
        assert [v['source_snapshot_id'] for v in versions]==schedule.snapshot_id.tolist()
        assert all(v['source_sha256']==source_ref['sha256'] for v in versions)
        assert all(len(v['frame'])==100 for v in versions)
        return 'original-owner-result'
    monkeypatch.setattr(owner,'_assemble',assemble)
    assert a.map_source_pool(schedule,members,identity,calendar,identity_ref,
                             source_ref=source_ref)=='original-owner-result'
    with pytest.raises(TypeError):
        a.map_source_pool(schedule,members,identity,calendar,identity_ref)


def test_existing_six_path_provider_keeps_bad_quality_and_separates_benchmarks(monkeypatch):
    dates=pd.bdate_range('2026-01-02',periods=3)
    names=[f'S{i:02}' for i in range(20)]
    flags=pd.DataFrame([dict(signal_date=d,ticker=t,security_id=f'SID{t}',is_raw_top20=True,
        is_max_group=True,stock_forecast_input_present=True,raw_selector_input_present=True,
        decision_information_present_union=True,new_buy_eligible=True,realized_vol_20d=.1)
        for d in dates for t in names])
    bars=pd.DataFrame([dict(trade_date=d,ticker=t,open=10.,close=11.,quality=(d==dates[1] and t in ['S00','QQQ']))
        for d in dates for t in names+['QQQ','SPY']])
    auth=SimpleNamespace(task_id=a.TASK,start=dates[0],end=dates[-1])
    monkeypatch.setattr(a.authority,'load_descriptive_authority',lambda value:value)
    monkeypatch.setattr(a.authority,'validate_descriptive_input_dates',lambda *args,**kw:None)
    window=dict(start=str(dates[0].date()),end=str(dates[-1].date()),first_execution_date=str(dates[1].date()))
    kwargs={group:dict(entitlement_enabled=True) for group in ['stocks',*a.authority.PATH_IDS[4:]]}
    actual=a.assemble_six_path_inputs(window,auth,flags=flags,bars=bars,calendar=dates,
        account={'initial_nav':3000},account_source_kwargs_by_group=kwargs,heads={'inference_evidence':{}})
    assert set(actual)==set(kwargs)
    assert set(actual['stocks']['market'].tickers)==set(names)
    assert actual['stocks']['market'].quality[1,0]
    assert actual['QQQ_BUY_AND_HOLD']['market'].quality[:,0].tolist()==[False,True,False]
    assert not actual['SPY_BUY_AND_HOLD']['market'].quality.any()
    assert all(v['market'].row_present.all() for v in actual.values())
    random=dict(start=str(dates[1].date()),end=str(dates[-1].date()),first_execution_date=str(dates[2].date()))
    out=a.slice_account_inputs(actual['QQQ_BUY_AND_HOLD'],random,
        SimpleNamespace(start=dates[1],end=dates[-1]),account_source_kwargs=kwargs['QQQ_BUY_AND_HOLD'])
    assert out['market'].quality[:,0].tolist()==[True,False]
    bad=bars.copy();bad['quality']='good'
    with pytest.raises(ValueError,match='RAW_QUOTE_SCHEMA'):
        a.assemble_six_path_inputs(window,auth,flags=flags,bars=bad,calendar=dates,account={},
            account_source_kwargs_by_group=kwargs,heads={'inference_evidence':{}})


# Reuse the reviewed synthetic authority fixtures; no real research files.
import importlib.util as _importlib_util
from pathlib import Path as _Path
_fixture_spec=_importlib_util.spec_from_file_location('_aggregate_provider_authority_fixture',
    _Path(__file__).with_name('test_aggregate_13f_authority.py'))
_custody_fixture=_importlib_util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_custody_fixture)
descriptive_fixture=_custody_fixture.descriptive_fixture
variant=_custody_fixture.variant


@pytest.mark.parametrize('ticker,path_id',[('S','RAW_s10'),('QQQ','QQQ_BUY_AND_HOLD'),('SPY','SPY_BUY_AND_HOLD')])
@pytest.mark.parametrize('fresh_after_ex',[False,True])
def test_full_cash_terminal_catalogue_shared_by_stock_and_etf_accounts(variant,ticker,path_id,fresh_after_ex):
    from dataclasses import replace
    from scripts.v22 import corporate_action_transition_r1 as ca
    fixture=_custody_fixture._variant_cash_fixture(variant)
    fx=_custody_fixture.fixtures
    first=fx._postverified_event(fixture)
    cash=[first,replace(first,event_id='QQQ_CASH',old_security_id='secQQQ',ticker='QQQ',cash_per_old_share=2.),
          replace(first,event_id='SPY_CASH',old_security_id='secSPY',ticker='SPY',cash_per_old_share=3.)]
    terminal=ca.SourceBackedTerminalEvent(event_id='S_STRICT_TERMINAL',old_security_id='secS',ticker='S',
        effective_at='2026-01-07T14:30:00Z',available_at='2026-01-06T12:00:00Z',cash_per_old_share=5.,
        currency='USD',amount_unit=ca.USD_PER_RAW_OLD_SHARE,quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,
        quantity_source_reference='synthetic://raw',quantity_source_fingerprint='b'*64,
        source_type='TIER1_ISSUER_REGULATOR_EXCHANGE',source_reference='synthetic://terminal',
        source_fingerprint='c'*64,settlement=None)
    events=[*cash,terminal]
    admitted,bound=fx._postverified_bind(fixture,events)
    if fresh_after_ex:
        bound['windows']=[dict(window_id='MAIN',start='2026-01-07',end='2026-01-08')]
        admitted=a.authority.load_descriptive_authority(fixture[2](bound))
    dates=pd.bdate_range(admitted.start,admitted.end)
    price=np.full((len(dates),1),100.)
    if ticker=='S':price[dates>=pd.Timestamp('2026-01-07')]=np.nan
    market=a.replay.MarketArrays(dates,[ticker],price.copy(),price.copy(),
        row_present=np.isfinite(price),signal_mask=np.ones(len(dates),bool))
    replay=fx.run_continuous_account(market,[path_id],fx.buy_then_hold(),dict(fx.config(),capacity_fraction=None),
        execution_friction=fx._descriptive_friction(),descriptive_evaluation_authority=admitted,
        **fx._postverified_account_args(events))
    a.authority.validate_reconstructed_accounting_events(admitted,events,require_exact=True)
    if fresh_after_ex:
        assert replay.daily.entitlement_cash_flow_usd.eq(0).all()
        assert replay.daily.receivable_value_usd.eq(0).all()
        assert replay.final_state['accounting_qualified'].tolist()==[True]
        assert len(replay.fills)==(0 if ticker=='S' else 1)
    else:
        quantity=replay.fills.fractional_shares.iloc[0]
        amount={'S':10.,'QQQ':2.,'SPY':3.}[ticker]
        assert replay.daily.entitlement_cash_flow_usd.sum()==pytest.approx(quantity*amount)
        assert replay.final_state['accounting_qualified'].tolist()==[ticker!='S']
        if ticker=='S':
            assert replay.final_state['fractional_shares'][0,0]==0
            assert replay.final_state['receivable_value_usd'][0]==pytest.approx(quantity*5.)
        else:
            assert replay.final_state['receivable_value_usd'][0]==0
    assert replay.daily.nav_identity_error.abs().max()<1e-8



def consensus_source_fixture():
    schedule,members,identity,days=fixture()
    members=members.rename(columns={"amount_rank":"consensus_rank"})
    members["manager_count"]=3
    members["holding_weight_sum_exact"]="1/10"
    return schedule,members,identity,days


def test_consensus_projection_keeps_rank_role_and_missing_member():
    schedule,members,identity,days=consensus_source_fixture()
    identity=identity.loc[identity.cusip.ne('C00000099')]
    p=a.project_universe(schedule,members,identity,days,task_id=a.authority.CONSENSUS_TASK,
        selection_rule="MANAGER_COUNT_WEIGHT_SUM")
    assert p['schedule'].universe_id.eq(a.authority.CONSENSUS_TASK).all()
    assert p['schedule'].universe_member_count.eq(100).all()
    assert p['schedule'].mapped_count.eq(99).all()
    assert 'amount_rank' not in p['members']
    assert p['members'].consensus_rank.max()==100
    assert p['members'].ticker.isna().sum()==3
    with pytest.raises(ValueError,match='RULE_TASK_MISMATCH'):
        a.project_universe(schedule,members,identity,days,task_id=a.authority.CONSENSUS_TASK,
            selection_rule="AGGREGATE_USD")
    with pytest.raises(ValueError,match='SOURCE_RANK_ROLE'):
        a.project_universe(*fixture(),task_id=a.authority.CONSENSUS_TASK)
    with pytest.raises(ValueError,match='EXACT_TASK'):
        a.project_universe(schedule,members,identity,days,task_id='ARBITRARY')


def test_consensus_raw_owner_scores_new_pool_with_original_model(monkeypatch):
    p=a.project_universe(*consensus_source_fixture(),task_id=a.authority.CONSENSUS_TASK)
    dates=pd.DatetimeIndex(p['ledger'].target_date)
    features=pd.DataFrame([dict(trade_date=d,ticker=f'S{i:03d}',**dict.fromkeys(a.inputs.FEATURES,1.))
        for d in dates for i in range(100)])
    def ranked(*args):
        assert args[2].consensus_rank.max()==100
        return pd.DataFrame([dict(target_date=d,ticker=f'S{i:03d}',rank=i+1,score=100-i,universe_quarter='2025Q3')
            for d in dates for i in range(100)]),pd.DataFrame(dict(status=['READY']*3))
    monkeypatch.setattr(a.authority,'load_descriptive_authority',lambda value:value)
    monkeypatch.setattr(a.authority,'validate_descriptive_input_dates',lambda *args,**kw:None)
    monkeypatch.setattr(a.ranking,'ranked_predictions',ranked)
    models=dict(feature_columns=a.inputs.FEATURES,artifacts={'2026':{'sha256':a.authority.RAW_SELECTOR_SHA256}})
    _,_,flags=a.rank_and_flags(features,p,models,SimpleNamespace(task_id=a.authority.CONSENSUS_TASK))
    assert flags.groupby('signal_date').is_raw_top20.sum().eq(20).all()
    with pytest.raises(ValueError,match='PROJECTION_TASK_MISMATCH'):
        a.rank_and_flags(features,p,models,SimpleNamespace(task_id=a.TASK))


def test_maintained_runner_rejects_arbitrary_task_before_inference(monkeypatch,tmp_path):
    from scripts.research.a2.evaluation import aggregate_frozen_runner as runner
    monkeypatch.setattr(runner.authority,'_document',lambda ref:{'strategy_id':'ARBITRARY'})
    def forbidden(*args,**kwargs): raise AssertionError('must not load model or account')
    monkeypatch.setattr(runner.frozen,'load_frozen_2025',forbidden)
    with pytest.raises(ValueError,match='MANAGED_RUN_REQUIRED'):
        runner.prepare(tmp_path/'ARBITRARY'/'run',expected_run_config_sha256='synthetic',
            main_admitted=None,account_source_kwargs_by_group={})


@pytest.mark.parametrize('consensus',[False,True])
def test_all_pool_descendant_reuses_exact_original_selection(consensus):
    s,m,i,d = fixture()
    if consensus:
        m = m.rename(columns={'amount_rank':'consensus_rank'}).assign(manager_count=2,holding_weight_sum_exact='1/10')
        task = a.authority.ALL_CONSENSUS_TASK
        parent = a.authority.CONSENSUS_TASK
    else:
        task = a.authority.ALL_AMOUNT_TASK
        parent = a.authority.AGGREGATE_TASK
    expected = a.project_universe(s,m,i,d,task_id=parent)
    actual = a.project_universe(s,m,i,d,task_id=task)
    for key in ('members','schedule'):
        left = expected[key].drop(columns=['universe_id','snapshot_id'],errors='ignore')
        right = actual[key].drop(columns=['universe_id','snapshot_id'],errors='ignore')
        pd.testing.assert_frame_equal(left,right)
    assert actual['schedule'].universe_member_count.eq(100).all()


@pytest.mark.parametrize("declared", [True, False])
def test_all_a_consensus_projection_requires_declared_profile(monkeypatch, declared):
    from scripts.research.a2.evaluation import frozen_a94_profile as profile
    monkeypatch.setattr(profile, "profile_contract", lambda task: {
        "raw_selector_binding": {"universe_variant": "CONSENSUS100" if declared else "ORIGINAL24"}})
    source = consensus_source_fixture()
    if not declared:
        with pytest.raises(ValueError, match="ALL_A_CONSENSUS_PROJECTION_SCOPE_REQUIRED"):
            a.project_universe(*source, task_id=profile.ALL_TASK)
        return
    expected = a.project_universe(*source, task_id=a.authority.CONSENSUS_TASK)
    actual = a.project_universe(*source, task_id=profile.ALL_TASK)
    for key in ("members", "ledger", "dated_identity"):
        pd.testing.assert_frame_equal(actual[key], expected[key], check_exact=True)
    pd.testing.assert_frame_equal(actual["schedule"].drop(columns="universe_id"),
                                  expected["schedule"].drop(columns="universe_id"), check_exact=True)
    assert actual["schedule"].universe_id.eq(profile.ALL_TASK).all()
    assert profile.ALL_TASK not in a.authority.universe_variant_tasks()
