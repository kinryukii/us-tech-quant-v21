"""Generated metadata/tables only. No real source reader, model or fitting."""
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from scripts.research.a2.data import consensus_comparison_inputs as c

spec=importlib.util.spec_from_file_location('_comparison_h5_fixture',Path(__file__).with_name('test_shared_risk_inputs_r3.py'))
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)


def write(path,obj):
    path.write_text(json.dumps(obj,default=str),encoding='utf-8')
    return dict(path=str(path),sha256=c.r3.sha(path))


class Reader:
    def __init__(self,tables):self.tables=tables;self.audit=[]
    def read(self,name,columns,**kw):
        frame=self.tables[name];mask=pd.Series(True,index=frame.index)
        clock=pd.to_datetime(frame[kw['date_field']])
        if kw.get('start') is not None:mask &= clock.ge(kw['start'])
        if kw.get('stop') is not None:mask &= clock.lt(kw['stop'])
        if kw.get('day') is not None:mask &= clock.eq(kw['day'])
        if kw.get('tickers') is not None:mask &= frame[kw.get('ticker_field','ticker')].isin(kw['tickers'])
        if kw.get('mature_before') is not None:
            for field in ('execution_date','label_end_date','label_mature_date'):
                mask &= pd.to_datetime(frame[field]).lt(kw['mature_before'])
        if kw.get('availability_cutoff') is not None:
            field,cut=kw['availability_cutoff'];mask &= pd.to_datetime(frame[field]).le(cut)
        self.audit.append((name,tuple(columns),kw))
        return frame.loc[mask,list(columns)].copy()


@pytest.fixture
def provider(tmp_path,monkeypatch):
    package=fixture.package.__wrapped__()
    days=package['calendar_sessions'];history=package['identity_history']
    features=history.rename(columns={'available_at':'unused'}).copy()
    features['feature_available']=True;features['all_features_finite']=True
    features['feature_source']=c.r3.FEATURE_TAGS[0]
    ff=pd.DataFrame([dict(decision_date=days[0],canonical_security_id=u,ticker_at_date=a,
        sic_available_at=fixture.close(days[0]),ff48_code=i+1,identity_status='AUTHORITATIVE',
        taxonomy_status='STRICT_PIT_SIC_FF12_FF48_MAPPED',sic_source_sha256='e'*64,source_fingerprints='generated')
        for i,(a,u) in enumerate(package['asset_uids'].items())])
    tables=dict(calendar=pd.DataFrame({'trade_date':days}),extended_shareholder_y5=package['stored_labels'],
        shareholder_y5=package['stored_labels'][['ticker','signal_date','security_id']],qqq_qfq_years=package['qqq_opens'],
        ff48_surface=ff,prediction_features=features,raw_open_close=history.rename(columns={'signal_date':'trade_date'}),
        uid_intervals=pd.DataFrame([dict(ticker=a,security_id=u,effective_start=days[0]) for a,u in package['asset_uids'].items()]))
    reader=Reader(tables)
    root=write(tmp_path/'root.json',dict(research_id='CONSENSUS100_PTO_3000_PRE2026_FULL_METHOD_COMPLETION_R12',
        source_policy=c.MODE,test2026_read_authorized=False,confirmation_read_authorized=False))
    source=write(tmp_path/'source.json',dict(research_id='GENERATED_SOURCE',family_design_freeze_sha256='f'*64,
        sources=dict(extended_shareholder_y5=dict(path=str(tmp_path/'h5'),sha256='a'*64),
            qqq_qfq_years=[dict(path=str(tmp_path/'qqq'),year=2024,sha256='b'*64)],
            ff48_surface=dict(path=str(tmp_path/'ff48'),sha256='c'*64))))
    monkeypatch.setattr(c,'assert_safe_output_path',lambda *a,**k:None)
    frozen=c.freeze_template(tmp_path,root,source,actual_snapshot_timestamp='2026-10-15T00:00:00Z')
    assert frozen['status']=='PROPOSED' and frozen['numeric_read_authorized'] is False
    frozen.update(status=c.GATE,numeric_read_authorized=True)
    fr=write(tmp_path/'freeze.json',frozen)
    return c.ComparisonInputProvider(fr,reader=reader),reader,frozen,fr,package


def test_root_gate_rejects_before_any_source_body(provider):
    _,reader,frozen,fr,_=provider;reader.audit.clear()
    frozen['status']='PROPOSED';write(Path(fr['path']),frozen)
    fr['sha256']=c.r3.sha(fr['path'])
    with pytest.raises(ValueError,match='ROOT_COMPARISON_INPUT_FREEZE'):
        c.ComparisonInputProvider(fr,reader=reader)
    assert reader.audit==[]


def test_full_cash_risk_label_claim_is_rejected_before_source_body(provider):
    _,reader,frozen,fr,_=provider;reader.audit.clear()
    frozen['risk_label_economic_semantics']='FULL_CASH_TOTAL_RETURN'
    fr=write(Path(fr['path']),frozen)
    with pytest.raises(ValueError,match='QUANTITY_PRICE_RISK_LABEL_PROXY'):
        c.ComparisonInputProvider(fr,reader=reader)
    assert reader.audit==[]


def test_previous_legal_close_cutoff_ordered_domain_and_all_five_clocks(provider):
    p,reader,_,_,_=provider
    inputs,as_of=p.typed_r2('RD','2024-04-16',('B','A'))
    cutoff=fixture.close('2024-04-15')
    assert as_of==fixture.close('2024-04-16') and inputs.assets==('B','A')
    assert p.last_declaration['shared_engine_previous_close_cutoff']==cutoff.isoformat()
    for field in ('origin_at','entry_at','endpoint_at','matured_at','available_at'):
        assert inputs.observations[field].lt(cutoff).all()
    label_read=next(x for x in reader.audit if x[0]=='extended_shareholder_y5')
    assert label_read[2]['mature_before']==pd.Timestamp('2024-04-15')
    assert label_read[2]['tickers']==('B','A')
    assert p.last_declaration['missing_stock_horizons']==[3,10,20]


def test_future_2026_decision_rejected_before_source_projection(provider):
    p,reader,_,_,_=provider;reader.audit.clear()
    with pytest.raises(ValueError,match='PRE2026'):
        p.typed_r2('RD','2026-01-02',('A','B'))
    assert reader.audit==[]


def test_missing_held_uid_is_blocked_without_dropping_requested_asset(provider):
    p,reader,_,_,_=provider
    reader.tables['prediction_features']=reader.tables['prediction_features'].loc[lambda x:~x.ticker.eq('B')]
    with pytest.raises(ValueError,match='REQUESTED_CURRENT_OR_HELD'):
        p.typed_r2('RD','2024-04-16',('A','B'))
    assert not any(name=='extended_shareholder_y5' for name,_,_ in reader.audit)


def test_dated_uid_interval_mismatch_is_not_normalized_or_guessed(provider):
    p,reader,_,_,_=provider;reader.tables['uid_intervals'].loc[0,'security_id']='OTHER_UID'
    with pytest.raises(ValueError,match='DATED_UID_INTERVAL_MISMATCH'):
        p.typed_r2('RD','2024-04-16',('A','B'))


def test_bank_independent_qqq_and_real_ff48_order_no_fundamental_invention(provider):
    p,_,_,_,_=provider
    q=p.bank_dependencies('SINGLE_INDEX',pd.Timestamp('2024-04-16'),('B','A'))
    assert q['market_returns'].eq(0).all()  # Synthetic QQQ Close is constant; stock means are unused.
    assert q['market_returns'].attrs['source_id']=='FROZEN_INDEPENDENT_QQQ_QFQ_CLOSE'
    ff=p.bank_dependencies('INDUSTRY',pd.Timestamp('2024-04-16'),('B','A'))
    assert tuple(ff['exposure_frame'].index)==('B','A')
    assert ff['exposure_frame'].iloc[0].to_list()==[0.,1.]
    assert ff['available_at']<pd.Timestamp('2024-04-16')
    assert 'BLOCK_NO_FROZEN_REAL_FUNDAMENTAL' in p.bank_dependencies('FUNDAMENTAL','2024-04-16',('A','B'))['blocked_reason']


def test_missing_ff48_remains_explicit_block(provider):
    p,reader,_,_,_=provider;reader.tables['ff48_surface']=reader.tables['ff48_surface'].iloc[:0]
    dep=p.bank_dependencies('INDUSTRY',pd.Timestamp('2024-04-16'),('A','B'))
    assert dep['blocked_reason']=='BLOCK_MISSING_OR_UID_UNBOUND_FF48' and 'exposure_frame' not in dep


def test_future_append_does_not_change_past_typed_observations(provider):
    p,reader,_,_,_=provider
    old,_=p.typed_r2('RD','2024-04-16',('A','B'))
    extra=reader.tables['extended_shareholder_y5'].iloc[:1].copy()
    for field in ('signal_date','execution_date','label_end_date','label_mature_date'):extra[field]=pd.Timestamp('2025-01-03')
    extra['y_open5']=[fixture.UnreadableValue()]
    reader.tables['extended_shareholder_y5']=pd.concat([reader.tables['extended_shareholder_y5'],extra],ignore_index=True)
    new,_=p.typed_r2('RD','2024-04-16',('A','B'))
    pd.testing.assert_frame_equal(old.observations,new.observations)


def test_er_close_excess_not_relabelled_as_native_shareholder_horizons(provider):
    _,_,_,_,package=provider
    assembly=fixture.build(package)
    receipt=replace(package['source_receipt'],return_coordinate='CLOSE_EXCESS_VS_QQQ')
    with pytest.raises(ValueError):
        c.append_native_horizons(assembly,pd.DataFrame({'ER_3D':[fixture.UnreadableValue()]}),receipt,cutoff=package['cutoff'])


def test_er_native_footer_rejected_without_numeric_callback(tmp_path,monkeypatch):
    path=tmp_path/'er.parquet'
    pq.write_table(pa.table({'signal_date':[pd.Timestamp('2024-01-02')],'ER_3D':[.123]}),path)
    monkeypatch.setattr(c.r3,'_safe_source',lambda value:Path(value))
    with pytest.raises(ValueError,match='COORDINATE_SCHEMA_MISMATCH'):
        c.native_horizon_metadata(dict(path=str(path),sha256=c.r3.sha(path)))


def test_native_horizon_packaging_uses_stored_values_and_rejects_late_clock_first(provider):
    _,_,_,_,package=provider;assembly=fixture.build(package);days=package['calendar_sessions']
    receipt=replace(package['source_receipt'],source_identity='GENERATED_NATIVE_HORIZONS',source_sha256='d'*64)
    records=[]
    for asset in package['assets']:
        for horizon in (3,10,20):
            records.append(dict(asset=asset,origin_at=fixture.close(days[0]),
                entry_at=c.packaging._clock(days[1],opening=True),
                endpoint_at=c.packaging._clock(days[1+horizon],opening=True),
                matured_at=fixture.close(days[1+horizon]),available_at=fixture.close(days[1+horizon]),
                horizon=horizon,uid=package['asset_uids'][asset],identity_epoch=package['identity_epoch'],
                source_identity=receipt.source_identity,return_value=horizon/1000))
    native=pd.DataFrame(records)
    out=c.append_native_horizons(assembly,native,receipt,cutoff=package['cutoff'])
    assert set(out.risk_input.observations.horizon)=={3,5,10,20}
    assert out.risk_input.observations.loc[lambda f:f.horizon.eq(20),'return_value'].eq(.02).all()
    assert out.support_declarations['method_block_reasons']['RM']==[]
    native['return_value']=native.return_value.astype(object)
    native.loc[0,'return_value']=fixture.UnreadableValue();native.loc[0,'available_at']=fixture.close('2025-01-03')
    with pytest.raises(ValueError,match='ISOLATED_BEFORE_NUMERIC'):
        c.append_native_horizons(assembly,native,receipt,cutoff=package['cutoff'])


def test_r10_pure_native_owner_reused_with_current_uid_segment_and_quantity_proxy(provider):
    p,reader,_,_,package=provider;cutoff=fixture.close('2024-04-15')
    domain=p.default_domain(cutoff,('A','B'))
    sid=domain['identity_history'].loc[lambda x:x.signal_date.lt('2024-04-15'),['ticker','signal_date','security_id']]
    quotes=sid[['ticker','signal_date']].rename(columns={'signal_date':'trade_date'}).copy()
    daypos={d:i for i,d in enumerate(package['calendar_sessions'])}
    quotes['open']=quotes.trade_date.map(lambda d:100.+daypos[d])
    payload=dict(keys=sid,sid_projection=sid,raw_quotes=quotes,event_records=[],
        event_window=lambda plan,events:(np.full(len(plan),1.5),np.zeros(len(plan),bool),np.zeros(len(plan),int)),
        risk_label_economic_semantics=c.LABEL_ECONOMICS)
    receipt=replace(package['source_receipt'],identity_epoch=domain['identity_epoch'])
    obs=c.assemble_native_shareholder_horizons(payload,domain,package['calendar_sessions'],cutoff,receipt)
    assert set(obs.horizon)=={3,10,20} and obs.identity_epoch.eq(domain['identity_epoch']).all()
    first=obs.loc[obs.asset.eq('A') & obs.horizon.eq(3)].iloc[0]
    assert first.return_value==pytest.approx(104./101.*1.5-1.)
    assert 'security_segment_epoch' in obs and obs.risk_label_economic_semantics.eq(c.LABEL_ECONOMICS).all()
    payload['risk_label_economic_semantics']='FULL_CASH_TOTAL_RETURN'
    with pytest.raises(ValueError,match='NOT_FULL_CASH_TOTAL_RETURN'):
        c.assemble_native_shareholder_horizons(payload,domain,package['calendar_sessions'],cutoff,receipt)


def test_scenarios_require_counted_mean_and_reference_requires_frozen_benchmark():
    with pytest.raises(ValueError,match='COUNTED_MEAN'):
        c.scenario_record(pd.DataFrame(),('A',),'2024-04-16',mean_state=None,source_refs={})
    with pytest.raises(ValueError,match='FROZEN_REFERENCE'):
        c.reference_record(None,None,0,source_refs={},available_at='2023-01-01')


def test_scenario_owner_uses_exact_counted_means_and_ignores_future_values():
    days=pd.bdate_range('2024-01-02',periods=55);assets=('B','A')
    frame=pd.DataFrame([dict(ticker=a,signal_date=days[i],execution_date=days[i+1],
        label_end_date=days[i+6],label_mature_date=days[i+6],fit_eligible=True,
        label_coordinate=c.packaging.STORED_LABEL_COORDINATE,y_open5=np.nan if a=='B' and i==0 else i/1000)
        for a in assets for i in range(45)])
    mean=SimpleNamespace(status='FITTED',fitted_dates=tuple(days[:45]),estimated_assets=assets,
                         fitted_state={'mean':np.array([.123,.456])})
    refs={'labels':{'path':'synthetic://h5','sha256':'a'*64}}
    result=c.scenario_record(frame,assets,'2025-03-03',mean_state=(mean,{'counted_state':'generated'}),source_refs=refs)
    assert result['assets']==assets and result['values'][0,0]==pytest.approx(.123)
    assert result['owner_receipt']['mean_preprocessor']['new_fit_states']==0
    future=frame.iloc[:1].copy()
    for column in ('signal_date','execution_date','label_end_date','label_mature_date'):
        future[column]=pd.Timestamp('2025-01-03')
    future['y_open5']=[fixture.UnreadableValue()]
    appended=c.scenario_record(pd.concat([frame,future],ignore_index=True),assets,'2025-03-03',
        mean_state=(mean,{'counted_state':'generated'}),source_refs=refs)
    np.testing.assert_array_equal(appended['values'],result['values'])


def test_scenario_padding_is_only_explicit_caller_inactive_domain():
    days=pd.bdate_range('2024-01-02',periods=55);assets=('A',)
    frame=pd.DataFrame([dict(ticker='A',signal_date=days[i],execution_date=days[i+1],
        label_end_date=days[i+6],label_mature_date=days[i+6],fit_eligible=True,
        label_coordinate=c.packaging.STORED_LABEL_COORDINATE,y_open5=i/1000) for i in range(45)])
    mean=SimpleNamespace(status='FITTED',fitted_dates=tuple(days[:45]),estimated_assets=assets,fitted_state={'mean':np.array([.1])})
    item=c.scenario_record(frame,assets,'2025-03-03',mean_state=(mean,{'generated_counted_receipt':True}),
        source_refs={'generated':True},account_assets=('A','UNRELATED_IPO'),inactive_zero_padding_assets=('UNRELATED_IPO',))
    assert item['assets']==('A',) and item['values'].shape==(45,1)
    assert item['inactive_zero_padding_assets']==('UNRELATED_IPO',)
    with pytest.raises(ValueError,match='EXPLICIT_ACCOUNT_DOMAIN'):
        c.scenario_record(frame,assets,'2025-03-03',mean_state=(mean,{'generated_counted_receipt':True}),
            source_refs={'generated':True},account_assets=('A','ACTIVE_BUT_MISSING'),inactive_zero_padding_assets=())


def test_reference_reuses_current_legal_top20_rank_owner_at_actual_signal_close():
    from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays
    names=tuple('ASSET'+str(i).zfill(2) for i in range(25));dates=pd.bdate_range('2024-03-04',periods=2)
    market=MarketArrays(dates,names,np.full((2,25),100.),np.full((2,25),100.),adv=np.full((2,25),1e7))
    market.signal_asof=pd.DatetimeIndex([fixture.close(d) for d in dates])
    item=c.reference_record(market,-np.arange(1,26,dtype=float),0,source_refs={'generated_roster':True},
        available_at=market.signal_asof[0],frozen_definition=c.REFERENCE)
    assert np.count_nonzero(item['values'])==20
    np.testing.assert_allclose(item['values'][:20],.05)
    assert item['values'][20:].sum()==0 and item['decision_as_of']==market.signal_asof[0]


def test_reference_roster_string_clocks_are_qualified_before_rank_projection(provider,tmp_path,monkeypatch):
    from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays
    p,_,_,_,_=provider;names=tuple('A'+str(i).zfill(2) for i in range(25));dates=pd.bdate_range('2024-03-04',periods=2)
    market=MarketArrays(dates,names,np.full((2,25),100.),np.full((2,25),100.),adv=np.full((2,25),1e7))
    market.signal_asof=pd.DatetimeIndex([fixture.close(d) for d in dates])
    rows=pd.DataFrame([dict(signal_date=dates[0],ticker=a,security_id='UID:'+a,identity_present=True,
        consensus_rank=i+1,decision_at=market.signal_asof[0].isoformat(),available_at=market.signal_asof[0].isoformat(),
        effective_at=market.signal_asof[0].isoformat()) for i,a in enumerate(names)])
    future=rows.iloc[:1].copy();future['available_at']=fixture.close('2024-03-06').isoformat();future['consensus_rank']=999
    path=tmp_path/'roster.parquet';pd.concat([rows,future],ignore_index=True).to_parquet(path,index=False)
    p.freeze['consensus_roster_ref']=dict(path=str(path),sha256=c.r3.sha(path))
    monkeypatch.setattr(c.r3,'_safe_source',lambda value:Path(value))
    item=p.reference(market,0)
    np.testing.assert_allclose(item['values'][:20],.05)
    assert item['values'][20:].sum()==0 and item['available_at']==market.signal_asof[0]


def test_scenario_training_frame_delegates_diagonal_mean_fit_on_exact_annual_h5(provider):
    from scripts.research.a2.risk import joint_risk_estimators as bank
    p,reader,_,_,_=provider;days=pd.bdate_range('2023-01-02','2024-04-19');uids={'A':'CUSIP:A','B':'CUSIP:B'}
    history=pd.DataFrame([dict(ticker=a,signal_date=d,security_id=u) for a,u in uids.items() for d in days])
    features=history.assign(feature_available=True,all_features_finite=True,feature_source=c.r3.FEATURE_TAGS[0])
    labels=pd.DataFrame([dict(ticker=a,signal_date=days[i],security_id=u,execution_date=days[i+1],
        label_end_date=days[i+6],label_mature_date=days[i+6],label_coordinate=c.packaging.STORED_LABEL_COORDINATE,
        label_available=True,label_unsupported_common_event=False,endpoint_pair_available=True,y_open5=i/1000)
        for a,u in uids.items() for i in range(45)])
    p.calendar=pd.Series(days)
    reader.tables.update(prediction_features=features,raw_open_close=history.rename(columns={'signal_date':'trade_date'}),
        uid_intervals=pd.DataFrame([dict(ticker=a,security_id=u,effective_start=days[0]) for a,u in uids.items()]),
        extended_shareholder_y5=labels,shareholder_y5=labels[['ticker','signal_date','security_id']])
    calls=[]
    def counted(table,**kw):
        calls.append((table.copy(),kw))
        state=bank.fit_risk_estimator('DIAG',table,params=kw['params'])
        return state,{'generated_counted_fit_receipt':True,'physical_preproc_diag_units':2}
    item=p.scenario('2024-04-16',('B','A'),mean_state_provider=counted,
        account_assets=('B','A','UNRELATED_IPO'),inactive_zero_padding_assets=('UNRELATED_IPO',))
    assert len(calls)==1 and tuple(calls[0][0].columns)==('B','A')
    assert calls[0][1]['cutoff']==pd.Timestamp('2024-01-01') and calls[0][1]['identity']['uids']==uids
    assert item['values'].shape==(45,2) and item['owner_receipt']['mean_preprocessor']['new_fit_states']==0
