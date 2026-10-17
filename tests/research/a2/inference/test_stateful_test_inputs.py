"""Synthetic source-time and opportunity-union tests; no real data reads."""
import numpy as np
import pandas as pd
import pytest
from types import SimpleNamespace
from scripts.research.a2.inference.stateful_test_inputs import project_features, assemble_flags
from scripts.research.a2.training.stateful_inputs import FEATURES
from scripts.research.a2.inference import stateful_test_inputs as projected
from scripts.research.a2.inference import stateful_frozen_test as frozen
from scripts.research.a2.training import stateful_replay, stateful_decision as decision
from scripts.research.a2.evaluation import frozen_test_authority as authority


def fixture():
    dates=pd.bdate_range('2025-06-02',periods=150)
    raw=pd.DataFrame(dict(trade_date=dates,open=np.arange(150)+20.,close=np.arange(150)+21.,volume=1000.))
    entry=dict(ticker='SYNTH',code='US.SYNTH',price_basis='PIT_FORWARD_REHAB_INDEX')
    def adjust(code,ticker,r,f,w):return r.assign(ticker=ticker),[]
    def features(f):
        f=f[['trade_date','ticker']].copy()
        for name in FEATURES:f[name]=1.
        return f
    kw=dict(adapter=SimpleNamespace(adjusted_price_frame=adjust),wolf={},feature_function=features)
    return dates,raw,entry,kw


def test_minimum_contiguous_context_and_missing_session():
    dates,raw,entry,kw=fixture()
    got,_=project_features(raw,pd.DataFrame(),entry,dates,dates[0],dates[-1],**kw)
    assert got.trade_date.tolist()==list(dates[120:])
    got,_=project_features(raw.drop(index=50),pd.DataFrame(),entry,dates,dates[0],dates[-1],**kw)
    assert got.empty


@pytest.mark.parametrize('kind',['raw_future','factor_future','duplicate'])
def test_fail_before_adjustment(kind):
    dates,raw,entry,kw=fixture();f=pd.DataFrame()
    if kind=='raw_future':raw.loc[len(raw)]={'trade_date':pd.Timestamp('2027-01-01'),'open':1.,'close':1.,'volume':1.}
    elif kind=='factor_future':f=pd.DataFrame({'ex_div_date':['2027-01-01']})
    else:raw=pd.concat([raw,raw.iloc[[0]]])
    def forbidden(*a):raise AssertionError('must reject before numerical owner')
    kw['adapter']=SimpleNamespace(adjusted_price_frame=forbidden)
    with pytest.raises(ValueError):project_features(raw,f,entry,dates,dates[0],dates[-1],**kw)


def flags_fixture():
    tickers=['S'+str(i) for i in range(22)];date=pd.Timestamp('2026-01-02')
    f=pd.DataFrame({'trade_date':date,'ticker':tickers})
    for c in FEATURES:f[c]=1.
    r=pd.DataFrame(dict(target_date=date,ticker=tickers[:20],rank=range(1,21),score=1.,universe_quarter='2025Q3'))
    identity=pd.DataFrame(dict(signal_date=date,ticker=tickers[:21],security_id=tickers[:21],is_max_group=[True]*21))
    return f,r,identity


def test_full_member_flag_not_replaced_by_rank_presence_and_unknown_sid_not_filled():
    out=assemble_flags(*flags_fixture()).set_index('ticker')
    assert bool(out.loc['S20','is_max_group']) and not bool(out.loc['S20','raw_selector_input_present'])
    assert bool(out.loc['S20','decision_information_present_union'])
    assert pd.isna(out.loc['S21','security_id']) and not bool(out.loc['S21','new_buy_eligible'])
    assert out.is_raw_top20.sum()==20 and out.new_buy_eligible.sum()==20


def test_partial_raw20_rejected():
    f,r,i=flags_fixture()
    with pytest.raises(ValueError,match='INCOMPLETE_RAW20'):assemble_flags(f,r.iloc[:19],i)


def test_unsorted_raw_rejected_before_cumulative_adjustment():
    dates,raw,entry,kw=fixture()
    def forbidden(*a):raise AssertionError('unsorted rows reached stateful event adjustment')
    kw['adapter']=SimpleNamespace(adjusted_price_frame=forbidden)
    with pytest.raises(ValueError,match='FEATURE_RAW_TIME'):
        project_features(raw.iloc[::-1],pd.DataFrame(),entry,dates,dates[0],dates[-1],**kw)


def test_empty_rank_and_unknown_identity_preserve_feature_union():
    f,r,i=flags_fixture()
    out=assemble_flags(f,r.iloc[:0],i.iloc[:0])
    assert len(out)==22 and out.security_id.isna().all()
    assert out.stock_forecast_input_present.all() and out.decision_information_present_union.all()
    assert not out.is_raw_top20.any() and not out.new_buy_eligible.any()


@pytest.mark.parametrize("bad_ranks", [np.arange(20)+.1, np.arange(2,22), [*range(1,20),21]])
def test_top20_requires_exact_integer_one_through_twenty(bad_ranks):
    f,r,i=flags_fixture()
    r["rank"]=bad_ranks
    with pytest.raises(ValueError):
        assemble_flags(f,r,i)


@pytest.fixture
def provider_case(monkeypatch):
    def validate(admitted,dates,feature_context=False):
        d=pd.DatetimeIndex(pd.to_datetime(dates))
        if not d.empty:
            assert d.max()<=admitted.end
            assert d.min() >= (pd.Timestamp('2023-01-01') if feature_context else admitted.start)
    monkeypatch.setattr(authority,'validate_descriptive_input_dates',validate)
    monkeypatch.setattr(frozen,'_check_sources',lambda bundle:None)
    def forbidden(*a,**kw):raise AssertionError('pure provider must never predict or fit')
    monkeypatch.setattr(frozen,'predict_r6_frozen',forbidden)
    monkeypatch.setattr(frozen,'predict_value_frozen',forbidden)
    dates=pd.DatetimeIndex(['2023-01-03','2025-12-30','2025-12-31',
                           '2026-01-02','2026-01-05','2026-01-06','2026-01-07','2026-01-08'])
    future=dates[dates.year==2026]
    admitted=SimpleNamespace(start=future[0],end=future[-1],window_id='MAIN')
    rows=[]
    for d in dates:
        f,r,i=flags_fixture()
        f['trade_date']=d;r['target_date']=d;i['signal_date']=d
        if d.year==2026:r.loc[r['ticker'].eq('S19'),'ticker']='S20'
        rows.append(assemble_flags(f,r,i))
    flags=pd.concat(rows,ignore_index=True)
    history=flags.loc[flags.signal_date.lt('2026-01-01')].copy()
    test=flags.loc[flags.signal_date.ge('2026-01-01')].copy()
    return dates,future,admitted,history,test,stateful_replay._old().values


def test_proxy_history_phase_is_preserved_and_labels_never_enter(provider_case):
    dates,future,admitted,history,test,_=provider_case
    got,audit=projected.build_proxy_samples(history,test,dates,admitted)
    assert set(got['buy'].loc[got['buy'].signal_date.eq(future[0]),'ticker'])=={'S20'}
    pair=got['replace'].loc[got['replace'].signal_date.eq(future[0])]
    assert pair.incumbent.tolist()==['S0','S1']
    assert not set(got['buy']) & frozen._FORBIDDEN
    assert not set(got['replace']) & frozen._FORBIDDEN
    assert audit['label_rows_read']==audit['new_fit']==0
    assert not got['replace'].empty


@pytest.mark.parametrize('change',['missing_history','label_column','duplicate_test'])
def test_proxy_causal_source_contract_rejects_missing_phase_or_labels(provider_case,change):
    dates,_,admitted,history,test,_=provider_case
    if change=='missing_history':history=history.loc[history.signal_date.ne('2025-12-30')]
    elif change=='label_column':test=test.assign(y_open5=123.)
    else:test=pd.concat([test,test.iloc[:1]],ignore_index=True)
    with pytest.raises(ValueError):projected.build_proxy_samples(history,test,dates,admitted)


def test_original_support_uses_sid_age_without_filling_unknowns(provider_case):
    dates,_,admitted,history,test,_=provider_case
    samples,_=projected.build_proxy_samples(history,test,dates,admitted)
    buy=samples['buy']; assert not buy.empty
    bad=buy.copy();bad.loc[0,'security_id']=pd.NA
    assert projected.r6_supported_samples(bad,'buy').empty
    bad=buy.copy();bad.loc[0,'cohort_age_sessions']=21
    assert projected.r6_supported_samples(bad,'buy').empty


def provider_evidence(samples,test):
    evidence={}
    for cid,obj,features in zip(authority.MODEL_IDS,('buy','replace','ngboost'),
                                (decision.SINGLE,decision.PAIR,FEATURES)):
        model=SimpleNamespace(calibration={'sigma':.03}) if obj=='ngboost' else None
        bundle=frozen.Frozen2025Model(cid,obj,tuple(features),model,'{}',
            dict(path='synthetic://model',sha256=authority.MODEL_SHA256[cid]),
            dict(path='synthetic://receipt',sha256=frozen.RECEIPT_SHA256[cid]),frozen._SEAL)
        if obj=='ngboost':
            p=test[['signal_date','ticker']].assign(prediction=.05,value_sigma=.03,
                prediction_qualified=True,year=2025,model_sha256=authority.MODEL_SHA256[cid])
            s=None
        else:
            s=samples[obj]
            eligible=projected.r6_supported_samples(s,obj)
            keys=['signal_date','sample_id','ticker','security_id','incumbent','incumbent_sid','cohort_age_sessions']
            p=eligible[[c for c in keys if c in eligible]].assign(p_superior=.2,model_year=2025)
        evidence[cid]=dict(bundle=bundle,samples=s,predictions=p)
    return evidence


def test_window_provider_original_arrays_nan_raw_carrier_exact_heads_and_independent_state(provider_case):
    from scripts.research.a2.evaluation import stateful_frozen_six_path as six
    dates,future,admitted,history,test,old_values=provider_case
    samples,_=projected.build_proxy_samples(history,test,dates,admitted)
    evidence=provider_evidence(samples,test)
    bars=test[['signal_date','ticker']].assign(open=10.,close=10.)
    etfs={t:pd.DataFrame(dict(signal_date=future,ticker=t,open=100.,close=100.)) for t in ('QQQ','SPY')}
    account=dict(initial_cash_usd=3000.,max_positions=20)
    source={g:dict(entitlement_enabled=True,events=[]) for g in ('stocks',*authority.PATH_IDS[4:])}
    w=dict(start=str(future[0].date()),end=str(future[-1].date()),first_execution_date=str(future[1].date()))
    result=projected.window_inputs(w,admitted,flags=test,stock_bars=bars,etf_bars=etfs,calendar=future,
        account=account,account_source_kwargs_by_group=source,model_evidence=evidence,values_function=old_values)
    stocks=result['stocks'];names=stocks['market'].tickers
    assert np.array_equal(stocks['top'],old_values(test,future,names,'is_raw_top20',False,bool))
    assert np.array_equal(stocks['market'].input_present,stocks['stock_present']|stocks['raw_selector_present'])
    assert np.allclose(stocks['vol'],old_values(test,future,names,'realized_vol_20d')*np.sqrt(5.))
    assert np.isnan(stocks['packets']['ridge']['mu']).all()
    assert stocks['packets']['ridge']['packet_role']=='UNUSED_INTERFACE_CARRIER_NO_RIDGE_INFERENCE'
    assert np.all(stocks['packets']['ngboost']['mu']==.05)
    assert pd.isna(stocks['sid_by_key'][(future[0],'S21')])
    for cid in authority.MODEL_IDS:
        actual=six._inference_coverage({'candidate_id':cid},stocks,admitted)
        assert actual['inferred_rows']==len(evidence[cid]['predictions'])
    result[authority.PATH_IDS[4]]['account']['max_positions']=1
    result['stocks']['account_source_kwargs']['events'].append('SYNTHETIC_MUTATION')
    assert account['max_positions']==20 and not source['stocks']['events']
    assert result[authority.PATH_IDS[5]]['account']['max_positions']==20


def test_missing_head_stays_missing_and_legal_empty_is_explicit(provider_case):
    dates,future,admitted,history,test,old_values=provider_case
    samples,_=projected.build_proxy_samples(history,test,dates,admitted)
    evidence=provider_evidence(samples,test)
    evidence.pop(authority.MODEL_IDS[0])
    bars=test[['signal_date','ticker']].assign(open=10.,close=10.)
    etfs={t:pd.DataFrame(dict(signal_date=future,ticker=t,open=100.,close=100.)) for t in ('QQQ','SPY')}
    source={g:dict(entitlement_enabled=True) for g in ('stocks',*authority.PATH_IDS[4:])}
    w=dict(start=str(future[1].date()),end=str(future[-1].date()),first_execution_date=str(future[2].date()))
    later=SimpleNamespace(start=future[1],end=future[-1])
    result=projected.window_inputs(w,later,flags=test,stock_bars=bars,etf_bars=etfs,calendar=future,
        account={},account_source_kwargs_by_group=source,model_evidence=evidence,values_function=old_values)
    stocks=result['stocks']
    assert authority.MODEL_IDS[0] not in stocks['inference_evidence']
    cov=stocks['inference_evidence'][authority.MODEL_IDS[1]]['support']
    assert cov.status.eq('NO_SUPPORT').all() and cov.reason.str.len().gt(0).all()


@pytest.mark.parametrize("aux_quality", [False, True])
def test_original_etf_projection_ignores_auxiliary_bit_but_preserves_missing_quotes(aux_quality):
    dates=pd.bdate_range("2026-01-02",periods=3)
    bars={t:pd.DataFrame(dict(trade_date=dates,ticker=t,open=[10.,11.,12.],close=[11.,12.,13.],quality=aux_quality)) for t in ("QQQ","SPY")}
    bars["SPY"]=bars["SPY"].iloc[:2].copy()
    def values(frame,dates,names,col,fill=np.nan,dtype=float):
        return frame.pivot(index="signal_date",columns="ticker",values=col).reindex(index=dates,columns=names).fillna(fill).to_numpy(dtype=dtype)
    kwargs={cid:dict(entitlement_enabled=True) for cid in authority.PATH_IDS[4:]}
    result=projected.benchmark_window_inputs(dates,etf_bars=bars,account=dict(initial_cash=3000),account_source_kwargs_by_group=kwargs,values_function=values)
    q=result[authority.PATH_IDS[4]]["market"];s=result[authority.PATH_IDS[5]]["market"]
    assert not q.quality.any() and not s.quality.any()
    assert q.row_present.all() and not s.row_present[-1,0]
    assert np.isnan(s.open[-1,0]) and np.isnan(s.close[-1,0])
    np.testing.assert_array_equal(q.open[:,0],[10.,11.,12.])
    assert result[authority.PATH_IDS[4]]["account"]==dict(initial_cash=3000)
