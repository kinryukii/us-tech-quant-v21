"""Generated-only evaluation gate, causal projection, selection and owner tests."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import json
import joblib
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.evaluation import consensus_evaluation_run as owner
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision
from test_consensus_shareholder_account import binding, source_binding, market


def daily(flat=False):
    return pd.DataFrame(dict(date=pd.to_datetime(['2023-01-03','2023-01-04','2024-01-02','2024-01-03','2025-01-02','2025-01-03']),
        nav=[3000.]*6 if flat else [3000.,3030.,3060.,3090.,3120.,3150.],turnover=[0.]*6,
        transaction_cost_amount=[0.]*6,accounting_qualified=True))


def forecast():
    f=pd.DataFrame(dict(signal_date=pd.to_datetime(['2023-01-03','2024-01-02','2025-01-02']),ticker='S',
        prediction=[.02,-.02,0.],value_sigma=.01,prediction_qualified=True))
    return owner.compatible_forecasts(f)


def test_normal_forecast_is_explicit_compatibility_not_native_quantile_calibration():
    f=forecast();assert f.attrs['unit']==owner.joint.UNIT
    assert 'NOT_NATIVE_QUANTILE_CALIBRATION' in f.attrs['compatibility_assumption']
    np.testing.assert_allclose(f.q10,f.mu-1.28155*f.sigma)
    assert f.p_up.iloc[0]>.5 and f.p_up.iloc[1]<.5 and f.p_up.iloc[2]==.5


def test_bad_sigma_and_duplicate_oof_cannot_enter_policy():
    f=pd.DataFrame(dict(signal_date=[pd.Timestamp('2025-01-02')],ticker='S',prediction=0.,value_sigma=0.,prediction_qualified=True))
    with pytest.raises(ValueError,match='INVALID_FUSION'):owner.compatible_forecasts(f)
    with pytest.raises(ValueError,match='DUPLICATE'):owner.compatible_forecasts(pd.concat([f,f]))


def test_flat_cash_has_zero_sharpe_and_three_continuous_years():
    r=owner.annual_statistics(daily(True));assert r['mean_annual_cost_net_sharpe']==0.
    assert all(y['flat_cash_result'] and y['cost_net_sharpe']==0. for y in r['annual_statistics'])
    changed=owner.annual_statistics(daily())
    assert changed['annual_statistics'][1]['nav_begin']==3030.
    assert changed['annual_statistics'][2]['nav_begin']==3090.


def test_unqualified_account_and_missing_year_never_get_a_selection_score():
    f=daily();f.loc[1,'accounting_qualified']=False
    with pytest.raises(owner.NotTestable,match='LIFECYCLE'):owner.annual_statistics(f)
    with pytest.raises(owner.NotTestable,match='YEAR'):owner.annual_statistics(daily().iloc[:-2])


def test_selection_uses_mean_year_sharpe_then_turnover_then_lexical_name():
    items=[dict(status='COMPLETE',flow_id=k,statistics=dict(mean_annual_cost_net_sharpe=s,total_turnover=t))
        for k,s,t in [('z',1.,.1),('a',1.,.1),('better',2.,.9),('lowturn',1.,0.)]]
    assert owner.select_best(items)['flow_id']=='better'
    assert owner.select_best(items[:2])['flow_id']=='a'
    assert owner.select_best([*items[:2],items[3]])['flow_id']=='lowturn'
    with pytest.raises(owner.NotTestable):owner.select_best([dict(status='FAILED_NO_RETRY')])


def test_exact_daily_pool_flags_precede_adv_and_return_numeric_projection():
    day=pd.Timestamp('2025-01-02');calls=[];source=dict(path='synthetic://features',sha256='a'*64)
    class Reader:
        membership=pd.DataFrame(dict(signal_date=[day,day],ticker=['GOOD','BAD']))
        pred_flags=pd.DataFrame(dict(signal_date=[day]*3,ticker=['GOOD','BAD','FUTURE_POOL_ONLY'],feature_available=[True,False,True],feature_source='FROZEN_RAW_A2_TRAINING_MATRIX_32'))
        records={'prediction_feature_panel':source}
        def _vectors(self,name,columns,filters):
            calls.append(filters);assert filters[0][0]==('ticker','==','GOOD')
            return pd.DataFrame(dict(signal_date=[day],ticker=['GOOD'],avg_dollar_volume_20d=[10000.],ret_1d=[.01]))
    adv,returns,keys=owner.qualified_vectors(Reader(),dict(signal_adv_source_ref=source))
    assert list(keys.ticker)==['GOOD'] and list(returns.columns)==['GOOD']
    assert adv.attrs['source_ref']==source and adv.available_at.iloc[0]==pd.Timestamp('2025-01-02T21:00:00Z')
    assert len(calls)==1
    with pytest.raises(ValueError,match='PINNED'):owner.qualified_vectors(Reader(),dict(signal_adv_source_ref=dict(source,sha256='b'*64)))
    assert len(calls)==1


def test_proposed_gate_rejects_before_any_account_loader(tmp_path,monkeypatch):
    monkeypatch.setattr(owner,'assert_safe_output_path',lambda *a,**kw:None)
    (tmp_path/owner.FREEZE).write_text(json.dumps(dict(schema='CONSENSUS_ACCOUNT_EVALUATION_FREEZE_R1',task_id=owner.TASK,status='PROPOSED',run=str(tmp_path))))
    monkeypatch.setattr(owner.account_inputs,'metadata_preflight',lambda **kw:pytest.fail('unauthorized account metadata'))
    with pytest.raises(ValueError,match='FREEZE_REQUIRED'):owner.run_all(tmp_path)


def test_worker_reserves_two_attempts_before_existing_numerical_owner(monkeypatch):
    messages=[];fit_calls=[]
    class Pipe:
        def send(self,x):messages.append(x)
        def recv(self):return True
        def close(self):pass
    bundle=SimpleNamespace(fitted_dates=('2024-12-30',),budget={'total_state_estimations':2},status='FITTED',failure_reason='')
    def fitted(method,x,params):fit_calls.append(len(messages));return bundle
    monkeypatch.setattr(owner.joint.risk,'fit_risk_estimator',fitted)
    owner._risk_worker(Pipe(),'risk','LW',None,None,None,None,None,None,dict(fit_cutoff='2025-01-01'))
    assert fit_calls==[2] and [m[0] for m in messages]==['FIT_START','FIT_START','RESULT']
    assert messages[-1][2]['actual_bundle_budget']['total_state_estimations']==2


def test_denied_worker_attempt_cannot_fit(monkeypatch):
    messages=[]
    class Pipe:
        def send(self,x):messages.append(x)
        def recv(self):return False
        def close(self):pass
    monkeypatch.setattr(owner.joint.risk,'fit_risk_estimator',lambda *a,**kw:pytest.fail('denied native fit'))
    owner._risk_worker(Pipe(),'risk','LW',None,None,None,None,None,None,{})
    assert [m[0] for m in messages]==['FIT_START','ERROR']


def test_private_owner_binding_keeps_current_columns_and_month_freeze(tmp_path,monkeypatch):
    dates=pd.bdate_range('2024-06-03',periods=160);rng=np.random.default_rng(8)
    returns=pd.DataFrame(rng.normal(0,.01,(160,2)),index=dates,columns=['S','FUTURE_POOL_ONLY']);returns.attrs['source_id']='SYNTHETIC'
    f=forecast();calls=[];original=owner.joint.risk.fit_risk_estimator
    monkeypatch.setattr(owner.values,'_events',lambda path:[])
    def worker(operation,method,x,*args,**kw):
        calls.append((tuple(x.columns),x.index.max(),kw['worker_target']));return original(method,x,params=args[-1])
    monkeypatch.setattr(owner.values,'_fit_job',worker)
    r=dict(receipt_path=str(tmp_path/'receipt.json'),fit_units=0)
    p=owner.make_policy(f,returns,owner.joint.PolicyConfig(),owner.cash.FeeConfig(),tmp_path,r,{},'synthetic')
    p._risk(pd.Timestamp('2025-01-02'),('S','FUTURE_POOL_ONLY'),fit_assets=('S',))
    p._risk(pd.Timestamp('2025-01-03'),('S',),fit_assets=('S',))
    assert len(calls)==1 and calls[0][0]==('S',) and calls[0][1]<pd.Timestamp('2025-01-02')
    assert calls[0][2] is owner._risk_worker and owner.joint.risk.fit_risk_estimator is original


def test_registered_names_are_not_claimed_as_all44_primary_accounts():
    c=owner.catalogue_coverage();assert len(c['full_registered_risk_names'])==18 and len(c['full_registered_allocation_names'])==26
    assert len(c['primary_account_paths'])==17 and c['primary_paths_are_not_all44']
    assert len(c['scenario_paths'])==3 and all(r['status']=='NOT_TESTABLE' for r in c['scenario_paths'])


def test_one_continuous_three_year_owner_replay_and_exact_checkpoint_no_retry(tmp_path,monkeypatch):
    m=market();m=replace(m,dates=pd.DatetimeIndex(daily(True).date),signal_asof=None)
    loaded=dict(market=m,events=dict(entitlement_events=(),entitlement_security_tickers={},entitlement_source_binding=source_binding((),{})),
        task_authority=binding(tmp_path,()),settlement_calendar=m.dates,usable_a=np.zeros_like(m.quality),source_scope_ref={'path':'synthetic://scope','sha256':'c'*64})
    monkeypatch.setattr(owner,'write_json_atomic',lambda p,v:p.write_text(json.dumps(v,default=str)))
    def save(path,value,kind):
        value.to_parquet(path,index=False) if kind=='frame' else joblib.dump(value,path)
        return owner.ref(path)
    monkeypatch.setattr(owner,'_save_artifact',save)
    seen=[]
    class Policy:
        config=owner.joint.PolicyConfig();fee_config=owner.cash.FeeConfig();risk_cache={};monthly_state_keys={};diagnostics=[]
        def __call__(self,di,ctx):seen.append(ctx.signal_date);return TargetDecision(np.zeros_like(ctx.current_weights),ctx.decision_mask.copy(),'SYNTHETIC_CASH')
    monkeypatch.setattr(owner,'make_policy',lambda *a,**kw:Policy())
    returns=pd.DataFrame({'S':[.01]},index=pd.DatetimeIndex(['2022-12-30']))
    r=owner.evaluate_flow(tmp_path,'equal','LW','cost_aware',forecast(),returns,loaded,{'path':'synthetic://freeze','sha256':'d'*64},[],{})
    assert r['status']=='COMPLETE' and r['statistics']['mean_annual_cost_net_sharpe']==0.
    assert len(seen)==5 and set(d.year for d in seen)=={2023,2024,2025}
    monkeypatch.setattr(owner,'make_policy',lambda *a,**kw:pytest.fail('completed checkpoint refit'))
    reused=owner.evaluate_flow(tmp_path,'equal','LW','cost_aware',forecast(),returns,loaded,{'path':'synthetic://freeze','sha256':'d'*64},[],{})
    assert reused['identity_sha256']==r['identity_sha256']
    changed=returns.copy();changed.index=pd.DatetimeIndex(['2022-12-29'])
    with pytest.raises(ValueError,match='IDENTITY_CHANGED'):
        owner.evaluate_flow(tmp_path,'equal','LW','cost_aware',forecast(),changed,loaded,{'path':'synthetic://freeze','sha256':'d'*64},[],{})



def test_physical_ack_worker_reports_two_units_and_actual_bundle_budget(tmp_path,monkeypatch):
    # Genuine numerical fit on generated pre2025 returns; same parent deadline
    # and ACK ledger protocol as predictors/fusion, isolated synthetic log.
    monkeypatch.setattr(owner.values,'assert_write_path',lambda *a,**kw:None)
    monkeypatch.setattr(owner.values,'write_json_atomic',lambda p,v:Path(p).write_text(json.dumps(v,default=str)))
    dates=pd.bdate_range('2024-01-02',periods=60)
    frame=pd.DataFrame(np.random.default_rng(19).normal(0,.01,(60,2)),index=dates,columns=['A','B'])
    receipt=dict(receipt_path=str(tmp_path/'receipt.json'),fit_units=0)
    params=dict(fit_cutoff='2025-01-01',return_unit='DAILY_DECIMAL_RETURN',return_horizon_sessions=1,
        source_id='GENERATED_SYNTHETIC_ONLY',information_set_id='GENERATED_SYNTHETIC_ONLY')
    bundle=owner.values._fit_job('risk','LW',frame,None,None,None,(),[],params,
        log=tmp_path/'FIT_LOG.jsonl',auth=dict(max_fit_units=2,budget_bucket='SYNTHETIC'),prior=0,
        year=2025,tuple_sha='a'*64,receipt=receipt,worker_target=owner._risk_worker)
    assert bundle.status=='FITTED' and receipt['fit_units']==2
    assert sum(e.get('fit_units',0) for e in owner.values._events(tmp_path/'FIT_LOG.jsonl'))==2
    meta=receipt['physical_fit_metadata'][0]['metadata']
    assert meta['actual_bundle_budget']['total_state_estimations']==2
    assert max(pd.Timestamp(d) for d in bundle.fitted_dates)<pd.Timestamp('2025-01-01')


def test_fixed_sensitivity_passes_same_fee_to_policy_and_replay(tmp_path,monkeypatch):
    m=replace(market(),dates=pd.DatetimeIndex(daily(True).date),signal_asof=None)
    loaded=dict(market=m,events=dict(entitlement_events=(),entitlement_security_tickers={},entitlement_source_binding=source_binding((),{})),
        task_authority=binding(tmp_path,()),settlement_calendar=m.dates,usable_a=np.zeros_like(m.quality),source_scope_ref={'path':'synthetic://scope','sha256':'c'*64})
    monkeypatch.setattr(owner,'write_json_atomic',lambda p,v:p.write_text(json.dumps(v,default=str)))
    def save(path,value,kind):
        value.to_parquet(path,index=False) if kind=='frame' else joblib.dump(value,path)
        return owner.ref(path)
    monkeypatch.setattr(owner,'_save_artifact',save)
    seen=[]
    class Policy:
        risk_cache={};monthly_state_keys={};diagnostics=[]
        def __init__(self,config,fee):self.config=config;self.fee_config=fee
        def __call__(self,di,ctx):
            assert ctx.fee_config==self.fee_config
            return TargetDecision(np.zeros_like(ctx.current_weights),ctx.decision_mask.copy(),'SYNTHETIC_CASH')
    def make(f,returns,config,fee,*a):seen.append((config.lookback_sessions,fee));return Policy(config,fee)
    monkeypatch.setattr(owner,'make_policy',make)
    returns=pd.DataFrame({'S':[.01]},index=pd.DatetimeIndex(['2022-12-30']))
    for d in owner.RECIPE['diagnostic_sensitivities']:
        r=owner.evaluate_flow(tmp_path,'equal','LW','cost_aware',forecast(),returns,loaded,{'path':'synthetic://freeze','sha256':'d'*64},[],{},diagnostic=d)
        assert r['status']=='COMPLETE' and r['diagnostic_only']
        assert r['fee_config']['one_way_all_in_bps']==d['one_way_all_in_bps']
        assert r['fee_config']['fixed_per_fill_usd']==d['fixed_per_fill_usd']
        assert r['diagnostics_summary']['max_drawdown']==0.
    assert [n for n,f in seen]==[120,120,120,60]
    assert [(f.one_way_all_in_bps,f.fixed_per_fill_usd) for n,f in seen]==[(5.,0.),(25.,0.),(10.,.5),(10.,0.)]


def test_coordinator_sensitivities_cannot_change_two_stage_selection(tmp_path,monkeypatch):
    f=forecast();returns=pd.DataFrame({'S':[.01]},index=pd.DatetimeIndex(['2022-12-30']))
    scope=dict(signal_adv_source_ref={'path':'synthetic://adv','sha256':'a'*64})
    monkeypatch.setattr(owner,'contract',lambda r:(r,dict(account_source_scope_ref={'path':'synthetic://scope','sha256':'b'*64}),{'path':'synthetic://freeze','sha256':'c'*64}))
    monkeypatch.setattr(owner.account_inputs,'metadata_preflight',lambda **kw:dict(scope=scope))
    monkeypatch.setattr(owner,'ConsensusInputs',lambda *a:object())
    monkeypatch.setattr(owner.predictors,'contract',lambda *a:(None,{},None))
    monkeypatch.setattr(owner.predictors,'reader_integrity',lambda *a:None)
    monkeypatch.setattr(owner,'qualified_vectors',lambda *a:(pd.DataFrame(),returns,pd.DataFrame()))
    monkeypatch.setattr(owner.account_inputs,'load_account_inputs',lambda *a,**kw:dict(market=SimpleNamespace(dates=pd.DatetimeIndex(daily().date))))
    monkeypatch.setattr(owner,'published_forecasts',lambda *a:(f,[]))
    monkeypatch.setattr(owner,'write_json_atomic',lambda p,v:(p.parent.mkdir(parents=True,exist_ok=True),p.write_text(json.dumps(v,default=str))))
    frozen=[]
    def evaluate(run,method,risk,alloc,*a,diagnostic=None):
        tag=None if diagnostic is None else diagnostic['tag'];fid=owner.flow_id(method,risk,alloc,tag)
        score=10000. if diagnostic is not None else 50. if risk=='EWMA' else 10. if method=='median' else 1.
        return dict(status='COMPLETE',flow_id=fid,fusion_method=method,risk_method=risk,allocation_method=alloc,
            statistics=dict(mean_annual_cost_net_sharpe=score,total_turnover=0.))
    monkeypatch.setattr(owner,'evaluate_flow',evaluate)
    def final(run,selected,*a):frozen.append(selected['flow_id']);return dict(status='COMPLETE')
    monkeypatch.setattr(owner,'freeze_selected_risk',final)
    r=owner.run_all(tmp_path)
    assert r['status']=='COMPLETE' and r['selected_fusion']=='median'
    assert r['selected_flow']==owner.flow_id('median','EWMA','cost_aware')
    assert len(r['stage1'])==13 and len(r['stage2'])==17 and len(r['sensitivities'])==4
    assert not r['sensitivity_selection_feedback'] and len(frozen)==5
    assert all('__diagnostic_' in k for k in frozen[1:])


def synthetic_publication_pins(run,members,year):
    pins=[]
    for member in members:
        for y in range(2021,year):
            output=run/'predictions/consensus_predictors'/member['model_id']/f"{member['horizon']}d/{y}.parquet"
            output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(b'generated-only-not-parquet')
            rp=output.with_suffix('.receipt.json');rp.write_text('{}')
            _,fr,_,_=owner.predictors.slot_paths(run,member['model_id'],y,member['horizon'])
            fr.parent.mkdir(parents=True,exist_ok=True);fr.write_text('{}')
            pins.append(dict(member=owner.fusion.member_key(member),year=y,prediction_sha256=owner.values.sha(output),
                publication_receipt_sha256=owner.values.sha(rp),fit_receipt_sha256=owner.values.sha(fr)))
    return pins


@pytest.mark.parametrize('changed',('prediction','publication','fit'))
def test_fusion_past_custody_is_exact_hash_only_not_current_year_packet(tmp_path,monkeypatch,changed):
    members=[dict(model_id='ridge',horizon=5),dict(model_id='hgb',horizon=5)]
    pins=synthetic_publication_pins(tmp_path,members,2023)
    monkeypatch.setattr(owner.pq,'read_table',lambda *a,**kw:pytest.fail('custody check must not decode prediction numeric'))
    owner.validate_past_publication_pins(tmp_path,members,2023,pins)
    with pytest.raises(ValueError,match='PACKET_CHANGED'):
        owner.validate_past_publication_pins(tmp_path,members,2023,pins+[dict(pins[0],year=2023)])
    with pytest.raises(ValueError,match='PACKET_CHANGED'):
        owner.validate_past_publication_pins(tmp_path,members,2023,pins[::-1])
    output=tmp_path/'predictions/consensus_predictors/ridge/5d/2021.parquet'
    _,fr,_,_=owner.predictors.slot_paths(tmp_path,'ridge',2021,5)
    path={'prediction':output,'publication':output.with_suffix('.receipt.json'),'fit':fr}[changed]
    path.write_bytes(b'changed-generated-only')
    with pytest.raises(ValueError,match='CUSTODY_CHANGED'):
        owner.validate_past_publication_pins(tmp_path,members,2023,pins)
    path.unlink()
    with pytest.raises(owner.NotTestable,match='MISSING_FUSION_TRAINING'):
        owner.validate_past_publication_pins(tmp_path,members,2023,pins)


def test_risk_worker_rejects_nonprimary_before_ack_or_estimation(monkeypatch):
    messages=[]
    pipe=SimpleNamespace(send=messages.append,recv=lambda:pytest.fail('no nonprimary budget ACK'),close=lambda:None)
    monkeypatch.setattr(owner.joint.risk,'fit_risk_estimator',lambda *a,**kw:pytest.fail('nonprimary owner cannot fit'))
    owner._risk_worker(pipe,'risk','GARCH',None,None,None,None,None,None,{})
    assert len(messages)==1 and messages[0][0]=='ERROR' and 'PRIMARY_RISK_WORKER_ONLY' in messages[0][2]


def test_risk_worker_cannot_report_more_estimation_units_than_reserved(monkeypatch):
    messages=[]
    pipe=SimpleNamespace(send=messages.append,recv=lambda:True,close=lambda:None)
    monkeypatch.setattr(owner.joint.risk,'fit_risk_estimator',lambda *a,**kw:SimpleNamespace(budget={'total_state_estimations':3}))
    owner._risk_worker(pipe,'risk','LW',None,None,None,None,None,None,{})
    assert [m[0] for m in messages]==['FIT_START','FIT_START','ERROR']
    assert 'RISK_ACTUAL_BUDGET_EXCEEDS_RESERVED_ATTEMPTS' in messages[-1][2]


def test_continuation_recipe_adds_only_zero_candidate_and_retains_original_disposition(tmp_path,monkeypatch):
    monkeypatch.setattr(owner.fusion,'CONTINUATION_RUN',tmp_path)
    recipe=owner.recipe_for_run(tmp_path)
    assert len(recipe['fusion_methods'])==14 and len(owner.RECIPE['fusion_methods'])==13
    assert recipe['fusion_methods'][:-1]==owner.RECIPE['fusion_methods']
    assert recipe['fusion_methods'][-1]==owner.fusion.owner.NNLS_ZERO_ABSTAIN
    assert recipe['stage2']==owner.RECIPE['stage2'] and recipe['diagnostic_sensitivities']==owner.RECIPE['diagnostic_sensitivities']
    with pytest.raises(ValueError,match='UNPLANNED'):owner.flow_id(owner.fusion.owner.NNLS_ZERO_ABSTAIN)
    assert owner.flow_id(owner.fusion.owner.NNLS_ZERO_ABSTAIN,run=tmp_path).startswith('core5__nnls_zero_abstain__')


def test_continuation_risk_ack_preserves_global_parent_fit_budget(tmp_path,monkeypatch):
    monkeypatch.setattr(owner.fusion,'CONTINUATION_RUN',tmp_path)
    monkeypatch.setattr(owner.fusion,'metadata',lambda p:dict(budget=dict(prior_fit_units=1098)))
    monkeypatch.setattr(owner.values,'_events',lambda p:[])
    dates=pd.bdate_range('2024-06-03',periods=120)
    returns=pd.DataFrame(np.random.default_rng(3).normal(0,.01,(120,1)),index=dates,columns=['S']);returns.attrs['source_id']='SYNTHETIC'
    seen=[];original=owner.joint.risk.fit_risk_estimator
    def worker(operation,method,x,*args,**kw):
        seen.append(kw['prior']);return original(method,x,params=args[-1])
    monkeypatch.setattr(owner.values,'_fit_job',worker)
    p=owner.make_policy(forecast(),returns,owner.joint.PolicyConfig(),owner.cash.FeeConfig(),tmp_path,{}, {},'synthetic')
    p._risk(pd.Timestamp('2025-01-02'),('S',),fit_assets=('S',))
    assert seen==[1098]


def test_child_publications_use_guarded_parent_and_new_slot_api_only(tmp_path,monkeypatch):
    monkeypatch.setattr(owner.fusion,'CONTINUATION_RUN',tmp_path)
    seen=[]
    def publication(run,method,year,reader):
        seen.append((run,method,year,reader))
        return pd.DataFrame(dict(signal_date=[pd.Timestamp(f'{year}-01-03')],ticker='S',prediction=0.,value_sigma=.01,prediction_qualified=True)),dict(year=year)
    monkeypatch.setattr(owner.fusion,'published_fusion_forecasts',publication)
    frame,pins=owner.published_forecasts(tmp_path,'nnls_zero_abstain','synthetic-reader')
    assert [x[2] for x in seen]==[2023,2024,2025] and [p['year'] for p in pins]==[2023,2024,2025]
    assert frame.mu.eq(0.).all() and frame.sigma.gt(0.).all() and frame.signal_date.lt('2026-01-01').all()


def test_yearend_delivered_inventory_excluded_from_final_fit_without_erasing_nav_holdings(tmp_path,monkeypatch):
    selected_path=tmp_path/'selected.json';selected_path.write_text('{}')
    state=dict(config=owner.asdict(owner.joint.PolicyConfig()),monthly_state_keys={},tickers=['S','CHILD','ORDINARY_HELD'],
        final_raw_units=np.array([[1.,.25,1.]]),final_state=dict(nav=3000.),
        stock_distribution_forced_exit_inventory_tickers=('CHILD',))
    sp=tmp_path/'input_state.joblib';joblib.dump(state,sp)
    selected=dict(flow_id='synthetic',receipt_path=str(selected_path),artifacts=dict(state=owner.ref(sp)),fee_config=owner.RECIPE['fee_config'])
    day=pd.Timestamp('2025-12-31');loaded=dict(market=SimpleNamespace(dates=pd.DatetimeIndex([day])),
        pool=pd.DataFrame(dict(signal_date=[day],ticker=['S'],identity_present=True)))
    f=forecast();f.loc[f.index[-1],'signal_date']=day
    seen=[];bundle=SimpleNamespace(status='FITTED',budget=dict(synthetic=True))
    class Policy:
        monthly_state_keys={}
        risk_cache={'final':bundle}
        def freeze_final_risk(self,assets):
            seen.append(tuple(assets));self.monthly_state_keys[owner.BOUNDARY.to_period('M').start_time]='final'
    monkeypatch.setattr(owner,'make_policy',lambda *a,**kw:Policy())
    monkeypatch.setattr(owner,'write_json_atomic',lambda p,v:p.write_text(json.dumps(v,default=str)))
    monkeypatch.setattr(owner,'_save_artifact',lambda p,v,k:(joblib.dump(v,p),owner.ref(p))[1])
    result=owner.freeze_selected_risk(tmp_path,selected,f,pd.DataFrame(),loaded,dict(path='synthetic',sha256='a'*64),{})
    assert result['status']=='COMPLETE' and seen==[('ORDINARY_HELD','S')]
    saved=joblib.load(result['artifacts']['state']['path'])
    np.testing.assert_array_equal(saved['final_raw_units'],state['final_raw_units'])
    assert saved['final_state']['nav']==3000. and saved['stock_distribution_forced_exit_inventory_tickers']==('CHILD',)


def test_foreign_conversion_fee_in_statistics_once_without_second_nav_deduction():
    f=daily();base=owner.annual_statistics(f)
    f['fx_conversion_fee_usd']=[0.,.15,0.,.2,0.,.25]
    f['transaction_cost_amount']=[0.,.3,0.,.4,0.,.5]
    result=owner.annual_statistics(f)
    assert result['mean_annual_cost_net_sharpe']==base['mean_annual_cost_net_sharpe']
    for row,trade,fx in zip(result['annual_statistics'],(.3,.4,.5),(.15,.2,.25)):
        assert row['fees']==pytest.approx(trade+fx)
        assert row['trade_fees']==pytest.approx(trade)
        assert row['fx_conversion_fees']==pytest.approx(fx)


@pytest.mark.parametrize('bad_fee',(-.1,float('nan'),float('inf')))
def test_foreign_fee_invalid_values_cannot_enter_selection(bad_fee):
    f=daily();f['fx_conversion_fee_usd']=0.;f.loc[0,'fx_conversion_fee_usd']=bad_fee
    with pytest.raises(ValueError,match='NONNEGATIVE_ACCOUNT_FEES'):owner.annual_statistics(f)
