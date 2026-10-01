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
