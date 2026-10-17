"""Synthetic-only R6 source/identity/window/native-delegation tests."""
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import joint_method_space_opportunity_r6 as owner


def metadata(n=6):
    dates=pd.date_range('2021-06-01',periods=n,freq='B')
    return pd.DataFrame(dict(signal_date=dates,ticker='SYNTHETIC',execution_date=dates+pd.Timedelta(days=1),
        label_end_date=dates+pd.Timedelta(days=6),label_mature_date=dates+pd.Timedelta(days=7),
        fit_eligible=True,security_uid='REAL_SECURITY_UID',asset_epoch='OBSERVED_EPOCH_1',
        identity_qualified=True,source_qualified=True))


def history_fixture():
    dates=pd.bdate_range('2021-01-01',periods=65)
    h=pd.DataFrame(dict(signal_date=dates,ticker='SYNTHETIC',security_uid='REAL_SECURITY_UID',
        asset_epoch='OBSERVED_EPOCH_1',identity_qualified=True,source_qualified=True,feature_available=True))
    for j,c in enumerate(owner.FEATURES):h[c]=np.arange(len(h),dtype=float)+j
    keys=h.iloc[[-1]][['signal_date','ticker','security_uid','asset_epoch','identity_qualified','source_qualified']].copy()
    return h,keys,dates


def test_literal_recipe_and_physical_dag():
    spec=owner.specification();slots=owner.slot_matrix()
    dag=owner.physical_dag();assert len({n['node_id'] for n in dag['nodes']})==len(dag['nodes'])
    assert all(n['learned_units']==len(n['component_ids']) for n in dag['nodes'])
    assert sum(n['learned_units'] for n in dag['nodes'])==544
    assert len(slots)==200 and sum(s['backend_calls'] for s in slots)==200
    assert sum(s['parameter_components'] for s in slots)==360
    assert spec['budget']['sequence_parameter_components_upper']==360+48==408
    assert spec['annual_genuine_OOF']==[2022,2023,2024,2025]
    assert spec['recipes']['TCN']['width']==16 and spec['recipes']['TCN']['epochs']==12
    assert spec['recipes']['TCN']['tcn_dilations']==[1,2,4,8,16]
    assert spec['recipes']['TemporalMLP']['hidden_layer_sizes']==[16,8]
    assert spec==owner.json.loads(owner.json.dumps(spec))
    assert not spec['outer_account_length_selection'] and spec['scientific_retry']==0
    assert all(s['seed']==20260928 and s['capacity']=='LOW' for s in slots)


def test_inner_clock_rules_and_selection_complete_ties():
    for year in owner.YEARS:
        folds=owner.inner_folds(year)
        assert [f['validation_start'][5:7] for f in folds]==['04','07','10']
        assert all(pd.Timestamp(f['validation_end'])<=pd.Timestamp(f'{year}-01-01') for f in folds)
    assert owner.select_window({5:[2,2,2],20:[2,2,2],60:[3,3,3]})==5
    assert owner.select_window({5:[3,3,3],20:[2,2,2],60:[1,1,1]})==60
    with pytest.raises(owner.OpportunityBlocked):owner.select_window({5:[1,2,3],20:[1,2],60:[1,2,3]})
    with pytest.raises(owner.OpportunityBlocked):owner.select_window({5:[1,2,3],20:[1,2,np.nan],60:[1,2,3]})


@pytest.mark.parametrize('length',[5,20,60])
def test_exact_windows_legal_current_and_full_requested_rows(length):
    h,k,cal=history_fixture();windows=owner.build_windows(h,k,cal,length)
    assert windows.values.shape==(1,length,32) and windows.qualified.tolist()==[True]
    assert windows.observed.all() and windows.block_reasons==(None,)
    assert windows.values[0,0,0]==65-length


@pytest.mark.parametrize('field',['security_uid','asset_epoch'])
def test_previous_identity_never_stitched(field):
    h,k,cal=history_fixture();h.loc[h.index[-10:-1],field]='DIFFERENT_PRIOR_IDENTITY'
    w=owner.build_windows(h,k,cal,20)
    assert w.qualified.tolist()==[True]
    assert not w.observed[0,-10:-1].any() and w.observed[0,-1].all()


@pytest.mark.parametrize('field,value',[('security_uid','UNKNOWN'),('asset_epoch',''),('source_qualified',False),('identity_qualified',False)])
def test_unknown_current_preserves_key_as_block(field,value):
    h,k,cal=history_fixture();k[field]=value
    w=owner.build_windows(h,k,cal,20)
    assert len(w.keys)==1 and not w.qualified[0] and not w.observed.any()
    assert w.block_reasons==('UNKNOWN_OR_UNQUALIFIED_CURRENT_UID_EPOCH',)


def test_current_mismatch_and_missing_day_no_fill():
    h,k,cal=history_fixture();h=h.drop(h.index[-2]);h.loc[h.index[-1],'asset_epoch']='OTHER_EPOCH'
    w=owner.build_windows(h,k,cal,5)
    assert not w.qualified[0] and not w.observed[0,-2:].any()


def test_future_and_forbidden_input_fail_before_values():
    h,k,cal=history_fixture()
    with pytest.raises(owner.OpportunityBlocked,match='HISTORY_AFTER'):owner.build_windows(h,k.assign(signal_date=cal[-2]),cal,20)
    with pytest.raises(owner.OpportunityBlocked,match='RAW_SCORE'):owner.build_windows(h.assign(raw_a2_prediction=1.),k,cal,20)
    with pytest.raises(owner.OpportunityBlocked,match='PRE2026'):owner.build_windows(h,k,pd.DatetimeIndex([*cal,pd.Timestamp('2026-01-01')]),20)


def test_training_metadata_before_numeric_conversion():
    class ForbiddenArray:
        def __array__(self,*args,**kwargs):raise AssertionError('NUMERIC_WAS_TOUCHED')
    m=metadata();m.loc[0,'label_mature_date']=pd.Timestamp('2022-01-01')
    with pytest.raises(owner.OpportunityBlocked,match='IMMATURE'):
        owner.fit_model('LagLinear',ForbiddenArray(),ForbiddenArray(),ForbiddenArray(),m,'2022-01-01',lookback=5,on_fit_started=lambda e:True)


def test_native_weighted_scaler_one_state_and_missing_mask():
    h,k,cal=history_fixture();h.loc[h.index[-2],owner.FEATURES[0]]=np.nan
    w=owner.build_windows(h,k,cal,5)
    m=metadata(1);m['signal_date']=k.signal_date.to_numpy();events=[]
    scaler,receipt=owner.fit_window_scaler(w,np.ones(1),m,'2022-01-01',on_fit_started=events.append)
    assert len(events)==1 and events[0]['learned_units']==1 and events[0]['backend_calls']==0
    z=owner.transform_windows(w,scaler,'TCN')
    assert z.shape==(1,5,64) and z[0,-2,0]==0. and z[0,-2,32]==1.
    assert owner.transform_windows(w,scaler,'TemporalMLP').shape==(1,320)
    assert receipt['actual_fit_count']==1


def test_no_reservation_no_fit():
    m=metadata();x=np.zeros((len(m),320))
    with pytest.raises(owner.OpportunityBlocked,match='CALLER_FIT'):
        owner.fit_model('LagLinear',x,np.arange(len(m)),np.ones(len(m)),m,'2022-01-01',lookback=5)


def test_temporal_native_delegation_and_component_callback(monkeypatch):
    calls=[]
    def fake_fit(node,x,payload,**kwargs):
        calls.append((node,x.shape,payload));kwargs['on_fit_started']('NATIVE_ESTIMATOR')
        return object(),dict(native_owner=True)
    monkeypatch.setattr(owner.mechanism,'fit',fake_fit)
    m=metadata();events=[]
    model,info=owner.fit_model('TemporalMLP',np.zeros((len(m),60*64)),np.arange(len(m)),np.ones(len(m)),m,
        '2022-01-01',lookback=60,on_fit_started=events.append)
    assert calls[0][0]['family']=='MLP' and calls[0][0]['capacity']=='LOW'
    assert calls[0][1]==(len(m),3840) and len(events)==1
    assert events[0]['components']==['TRUNK','POINT_HEAD'] and events[0]['learned_units']==2
    assert model.name=='TemporalMLP' and info['native_owner']


def test_long_network_private_constants_no_parent_mutation():
    before=owner.sequence._network.__code__
    clone=owner._long_network()
    def constants(code):
        out=[]
        for value in code.co_consts:
            if hasattr(value,'co_consts'):out+=constants(value)
            else:out.append(value)
        return out
    assert (1,2,4,8,16) in constants(clone.__code__) and (2,4,8,16,32) in constants(clone.__code__)
    assert owner.sequence._network.__code__ is before and (1,2,4,8) in constants(before)
    assert clone.__globals__['HIDDEN']==16


def test_extended_node_keeps_native_seed_guard():
    p=dict(target=np.arange(3),weights=np.ones(3))
    node=owner._node(dict(family='TCN',capacity='LOW',seed=owner.SEED,lookback=60,objective=owner.TARGET),p)
    assert node['lookback']==60 and node['capacity']=='LOW'
    with pytest.raises(ValueError):owner._node(dict(family='TCN',capacity='LOW',seed=123,lookback=60),p)


def test_bayesian_native_synthetic_posterior_and_callback():
    m=metadata(8);rng=np.random.default_rng(11);x=rng.normal(size=(len(m),32));y=x[:,0]*.02
    events=[];model,info=owner.fit_model('BayesianRidge',x,y,np.ones(len(m)),m,'2022-01-01',on_fit_started=events.append)
    out=owner.predict(model,x)
    assert np.isfinite(out['mean']).all() and (out['sigma']>0).all()
    assert len(events)==1 and events[0]['kind']=='posterior_fit'
    assert info['posterior_covariance_is_part_of_same_fit'] and info['learned_noise_precision']


def test_distribution_mixture_variance_and_tail_bound():
    packet={name:dict(mean=np.array([i*1.,0.]),sigma=np.ones(2)) for i,name in enumerate(owner.DISTRIBUTION_PACKET)}
    out=owner.distribution_ensemble(packet)
    assert out['mean'][0]==1.5 and np.isclose(out['sigma'][0]**2,2.25)
    assert np.isclose(out['q10_lower_bound'][0],-1.2815515655446004)
    assert out['new_fits']==0 and 'UNCALIBRATED_COVERAGE' in out['lower_tail_semantics']
    mus=np.stack([v['mean'] for v in packet.values()]);sigmas=np.stack([v['sigma'] for v in packet.values()])
    assert np.allclose(owner.ndtr((out['q10'][None,:]-mus)/sigmas).mean(0),.1)
    with pytest.raises(owner.OpportunityBlocked):owner.distribution_ensemble(dict(list(packet.items())[:-1]))


def test_fusion_reuses_full_packet_single_seed(monkeypatch):
    calls=[]
    monkeypatch.setattr(owner.fusion,'fit_meta',lambda *a,**kw:calls.append((a,kw)) or {'status':'SYNTHETIC'})
    assert owner.fit_fusion('NO_REAL_DATA','2023-01-01','equal',lambda *a:None)['status']=='SYNTHETIC'
    assert calls[0][0][3]==owner.PACKET and calls[0][1]['seeds']==(owner.SEED,)
    assert len(calls[0][1]['fixed_weights'])==6
    with pytest.raises(owner.OpportunityBlocked):owner.fit_fusion(None,None,'UNREGISTERED',None)


def test_torch_snapshot_version_cpu_origin_only():
    # No network construction, tensor forward, fitting or model deserialization.
    torch=owner.sequence._torch((str(owner.sequence.TORCH_SNAPSHOT),))
    assert torch.__version__=='2.14.0+cpu' and torch.version.cuda is None
    assert str(owner.sequence.TORCH_SNAPSHOT.resolve()).lower() in str(torch.__file__).lower()


def test_scaler_exact_key_binding_before_native_fit(monkeypatch):
    h,k,cal=history_fixture();windows=owner.build_windows(h,k,cal,5)
    monkeypatch.setattr(owner.mechanism,'fit_weighted_scaler',lambda *a,**k:pytest.fail('UNBOUND_NATIVE_FIT'))
    with pytest.raises(owner.OpportunityBlocked,match='EXACT_ORDERED_WINDOW'):
        owner.fit_window_scaler(windows,np.ones(1),metadata(1),'2022-01-01',on_fit_started=lambda e:True)


def test_fit_residual_reuses_native_ridge_body_with_explicit_tcn_alias(monkeypatch):
    m=metadata(2);m['TCN__mu']=[.01,.02];m['TCN__source_cutoff']=pd.Timestamp('2021-01-01',tz='UTC')
    for c in owner.FEATURES:m[c]=0.
    monkeypatch.setattr(owner.fusion,'prepare_history',lambda *a:(m,pd.Timestamp('2023-01-01',tz='UTC'),['TCN__mu']))
    calls=[]
    def fake_residual(frame,cut,method):
        calls.append((frame,cut,method))
        return dict(method=method,primary='HGB',sigma=None)
    monkeypatch.setattr(owner.residual,'fit_oof_residual',fake_residual)
    events=[];out=owner.fit_residual(m,'2023-01-01',on_fit_started=events.append)
    assert calls[0][2]=='hgb_then_ridge' and np.array_equal(calls[0][0].HGB_raw,m['TCN__mu'])
    assert out['primary']=='TCN' and out['method']=='residual_tcn_then_ridge' and out['sigma'] is None
    assert events[0]['backend_calls']==2 and events[0]['components']==['B32_SCALER','RIDGE_RESIDUAL']


def test_true_mixture_q10_distinct_from_min_and_average_component_quantiles():
    packet={name:dict(mean=np.array([i*1.7]),sigma=np.array([.3+i*.6])) for i,name in enumerate(owner.DISTRIBUTION_PACKET)}
    out=owner.distribution_ensemble(packet)
    component=np.array([v['mean'][0]-1.2815515655446004*v['sigma'][0] for v in packet.values()])
    assert not np.isclose(out['q10'][0],component.min()) and not np.isclose(out['q10'][0],component.mean())
    assert np.isclose(np.mean([owner.ndtr((out['q10'][0]-v['mean'][0])/v['sigma'][0]) for v in packet.values()]),.1,atol=1e-12)
    packet[owner.DISTRIBUTION_PACKET[0]]['sigma'][0]=0.
    with pytest.raises(owner.OpportunityBlocked):owner.distribution_ensemble(packet)


def test_native_error_proxy_is_one_existing_rms_without_fake_quantile(monkeypatch):
    monkeypatch.setattr(owner.fusion,'fit_meta',lambda *a,**k:dict(qualified=True,prior_OOF_error_RMS=.03,cutoff='2023-01-01'))
    out=owner.fit_native_uncertainty(None,'2023-01-01','TCN',None)
    assert out['q10'] is None and out['learned_states']==1 and out['mean_transform']=='IDENTITY_NATIVE_B5D'


def identity_fixture():
    from scripts.research.a2.training import joint_method_space_opportunity_execution_r6 as e
    days=pd.bdate_range('2021-01-04',periods=6)
    feature=pd.DataFrame(dict(signal_date=days,ticker='SYNTH',security_id='CUSIP_REAL',feature_available=True,all_features_finite=True,feature_source=sorted(e.ACCEPTED_FEATURE_TAGS)[0]))
    raw=pd.DataFrame(dict(signal_date=days,ticker='SYNTH',code='US.SYNTH'))
    intervals=pd.DataFrame([dict(effective_start=days[0],effective_end=days[-1],ticker='SYNTH',security_id='CUSIP_REAL',security_id_type='CUSIP',cusip='CUSIP_REAL',title_of_class='COMMON',moomoo_transport_code='US.SYNTH',mapping_status='RESOLVED',report_quarter='2020Q3',quarter_universe_fingerprint='a'*64)])
    panel=pd.DataFrame(dict(signal_date=days,ticker='SYNTH',security_id='CUSIP_REAL',security_id_type='CUSIP',cusip='CUSIP_REAL',active_13f_quarter='2020Q3',quarter_universe_fingerprint='a'*64,execution_date=days+pd.Timedelta(days=1),label_end_date=days+pd.Timedelta(days=2),label_mature_date=days+pd.Timedelta(days=3),trade_eligible=True,fit_eligible=True))
    held=pd.DataFrame(dict(signal_date=[days[-1]],ticker=['MISSING_HELD']))
    return e,feature,raw,intervals,panel,held,days


def test_metadata_sidecar_keeps_full_held_missing_and_current_role():
    e,f,r,i,p,h,d=identity_fixture();out=e.qualify_rows(f,r,i,p,h,d)
    assert len(out)==7 and out.is_required_held.sum()==1
    alpha=out.loc[out.ticker.eq('SYNTH')]
    assert alpha.identity_qualified.all() and alpha.alpha_structure_eligible.all()
    missing=out.loc[out.is_required_held].iloc[0]
    assert not missing.identity_qualified and missing.block_reason=='MISSING_EXACT_CURRENT_FEATURE_SECURITY_UID'
    assert not out.eligible_for_policy.any()


def test_metadata_cursor_missing_calendar_day_resets_epoch_without_filtering():
    e,f,r,i,p,h,d=identity_fixture();f=f.loc[f.signal_date.ne(d[2])]
    out=e.qualify_rows(f,r,i,p,h,d);a=out.loc[out.ticker.eq('SYNTH')].set_index('signal_date')
    assert a.loc[d[1],'asset_epoch']!=a.loc[d[3],'asset_epoch']
    assert a.loc[d[3],'same_uid_contiguous_sessions']==1


@pytest.mark.parametrize('field,value',[('security_id_type','UNKNOWN'),('cusip','OTHER'),('mapping_status','UNKNOWN'),('moomoo_transport_code','US.OTHER')])
def test_metadata_coordinate_unknown_or_conflicting_preserves_all_keys(field,value):
    e,f,r,i,p,h,d=identity_fixture();i[field]=value
    out=e.qualify_rows(f,r,i,p,h,d)
    assert len(out)==7 and not out.identity_qualified.any()
    assert not out.alpha_structure_eligible.any()


def test_metadata_rejects_values_and_future_before_body():
    e,f,r,i,p,h,d=identity_fixture()
    with pytest.raises(e.Blocked,match='METADATA_VALUES'):e.qualify_rows(f.assign(y_open5=1),r,i,p,h,d)
    with pytest.raises(owner.OpportunityBlocked,match='PRE2026'):e.qualify_rows(f,r,i,p,h,[*d,pd.Timestamp('2026-01-01')])


def test_sequence_sample_metadata_only_full_dates_fixed_keys_order_invariant():
    dates=pd.bdate_range('2021-01-04',periods=100)
    m=pd.DataFrame([dict(signal_date=d,ticker=f'SYNTH{i:04d}',security_uid=f'UID{i:04d}',asset_epoch=f'EPOCH{i:04d}',identity_qualified=True,source_qualified=True) for d in dates for i in range(500)])
    original=m.copy(deep=True);sample,proof=owner.sample_training_keys(m)
    shuffled,other=owner.sample_training_keys(m.sample(frac=1,random_state=12))
    assert len(sample)==48000 and sample.signal_date.nunique()==100
    assert proof['full_rows']==50000 and proof['selected_rows']==48000
    assert set(proof['date_quotas'].values())=={480}
    assert sample.equals(shuffled) and proof==other and m.equals(original)
    assert owner.specification()['sequence_training_sample']['cap']==48000


def test_sequence_sample_small_full_domain_and_reject_unknown_values():
    m=metadata().drop(columns=['execution_date','label_end_date','label_mature_date','fit_eligible'])
    sampled,proof=owner.sample_training_keys(m)
    assert len(sampled)==len(m) and proof['all_dates']==len(m)
    with pytest.raises(owner.OpportunityBlocked,match='UNKNOWN_UID'):owner.sample_training_keys(m.assign(security_uid='UNKNOWN'))
    with pytest.raises(owner.OpportunityBlocked,match='METADATA_ONLY'):owner.sample_training_keys(m.assign(y_open5=1.))
    with pytest.raises(owner.OpportunityBlocked,match='CAP'):owner.sample_training_keys(m,cap=24000)


@pytest.mark.parametrize('cut,mature',[('2023-02-01','2022-12-01'),('2023-01-01','2023-01-01'),('2023-01-01',None),('2026-01-01','2025-12-01')])
def test_native_genuine_clock_real_fields_not_cohort_name(cut,mature):
    from scripts.research.a2.training import joint_method_space_opportunity_execution_r6 as e
    with pytest.raises(e.Blocked):e._oof_clocks(dict(source_fit_cutoff=cut,source_label_mature_max=mature),2023,r4=True)


def test_native_clock_and_flat_mmap_descriptor_exactshape(tmp_path):
    from scripts.research.a2.training import joint_method_space_opportunity_execution_r6 as e
    a,b=e._oof_clocks(dict(source_fit_cutoff='2023-01-01',source_label_mature_max='2022-12-28'),2023,r4=True)
    assert a>b and a==pd.Timestamp('2023-01-01',tz='UTC')
    path=tmp_path/'synthetic.npy';array=np.lib.format.open_memmap(path,mode='w+',dtype='float64',shape=(3,5,64));array[:]=1;array.flush()
    descriptor=e._mmap_descriptor(array.reshape(3,320));restored=e._array(descriptor)
    assert restored.shape==(3,320) and np.array_equal(restored,array.reshape(3,320))
    bad=dict(descriptor,shape=[4,320])
    with pytest.raises(e.Blocked,match='DESCRIPTOR'):e._array(bad)


def test_numeric_runtime_guard_precedes_source_or_cache_body(monkeypatch):
    from scripts.research.a2.training import joint_method_space_opportunity_execution_r6 as e
    monkeypatch.setattr(e.runtime,'guard_numeric',lambda *a:(_ for _ in ()).throw(e.Blocked('SYNTHETIC_NOT_ADMITTED')))
    monkeypatch.setattr(e,'source_binding',lambda *a:(_ for _ in ()).throw(AssertionError('SOURCE_TOUCHED_BEFORE_ADMISSION')))
    with pytest.raises(e.Blocked,match='NOT_ADMITTED'):e.Source('synthetic','f'*64)
    with pytest.raises(e.Blocked,match='NOT_ADMITTED'):e.run_opportunity('synthetic','f'*64)


def test_completed_scaler_prefix_never_restores_as_model(monkeypatch,tmp_path):
    from scripts.research.a2.training import joint_method_space_opportunity_execution_r6 as e
    ledger=SimpleNamespace(status={'physical_events':[dict(node_id='MODEL:SCALER:0',status='COMPLETE')]})
    monkeypatch.setattr(e.runtime,'guard_numeric',lambda *a:tmp_path)
    seen=[]
    def cloned(*a,**k):
        seen.append(True)
        return lambda *args,**kwargs:'NEW_SYNTHETIC_MODEL'
    monkeypatch.setattr(e.mechanism,'_clone',cloned)
    monkeypatch.setattr(e,'_own_artifact',lambda *a,**k:dict(path='synthetic',sha256='a'*64))
    result,_=e.worker_fit(tmp_path,'f'*64,ledger,'MODEL','model','LagLinear',np.zeros((2,3)),np.zeros(2),np.ones(2),metadata(2),'2022-01-01')
    assert result=='NEW_SYNTHETIC_MODEL' and seen==[True]


@pytest.mark.parametrize('state',['STARTED','FAILED'])
def test_failed_started_fit_is_preserved_without_backend_retry(monkeypatch,tmp_path,state):
    from scripts.research.a2.training import joint_method_space_opportunity_execution_r6 as e
    ledger=SimpleNamespace(status={'physical_events':[dict(node_id='MODEL:0',status=state)]})
    monkeypatch.setattr(e.runtime,'guard_numeric',lambda *a:tmp_path)
    monkeypatch.setattr(e.mechanism,'_clone',lambda *a,**k:(_ for _ in ()).throw(AssertionError('FIT_RETRIED')))
    with pytest.raises(e.Blocked,match='NO_SCIENTIFIC_RETRY'):
        e.worker_fit(tmp_path,'f'*64,ledger,'MODEL','model','LagLinear',None,None,None,None,'2022-01-01')


def test_metadata_window_key_gate_precedes_values_and_keeps_missing_mask():
    from scripts.research.a2.training import joint_method_space_opportunity_execution_r6 as e
    h,k,cal=history_fixture()
    h.loc[h.index[-4],'security_uid']='PRIOR_DIFFERENT_UID'
    h.loc[h.index[-3],'source_qualified']=False
    h.loc[h.index[-2],'asset_epoch']='PRIOR_DIFFERENT_EPOCH'
    selected=e.qualified_history_keys(h,k,cal,5)
    assert selected.signal_date.tolist()==[cal[-5],cal[-1]]
    masked=h.drop(columns=owner.FEATURES).merge(selected[['signal_date','ticker',*owner.FEATURES]],on=['signal_date','ticker'],how='left',validate='one_to_one')
    left=owner.build_windows(h,k,cal,5);right=owner.build_windows(masked,k,cal,5)
    assert np.array_equal(left.observed,right.observed) and np.array_equal(left.values,right.values,equal_nan=True)
    with pytest.raises(e.Blocked,match='REQUESTED'):
        e.qualified_history_keys(h,k.assign(security_uid='UNKNOWN'),cal,5)


def test_catalogue_physical_freeze_pin_before_receipt_decode(monkeypatch,tmp_path):
    from scripts.research.a2.training import joint_method_space_opportunity_execution_r6 as e
    called=[];monkeypatch.setattr(e.old,'_pin',lambda *a:called.append(a))
    with pytest.raises(e.Blocked,match='CATALOGUE'):e._frozen_catalogue_ref(tmp_path,{})
    with pytest.raises(e.Blocked,match='CATALOGUE'):e._frozen_catalogue_ref(tmp_path,{'opportunity_catalogue_ref':{'source_ref':str(tmp_path/'foreign.json'),'sha256':'a'*64}})
    good={'source_ref':str(tmp_path/'work/R6_OPPORTUNITY_CATALOGUE_REUSE.json'),'sha256':'a'*64}
    assert e._frozen_catalogue_ref(tmp_path,{'opportunity_catalogue_ref':good})==good
    assert called==[(good['source_ref'],'a'*64,'R6_FROZEN_OPPORTUNITY_CATALOGUE')]


def test_batched_interval_qualification_exact_matches_original_producer_snapshot():
    import ast
    from scripts.research.a2.training import joint_method_space_opportunity_execution_r6 as e
    snapshot=e.Path('D:/us-tech-quant-cache/V24/B_METHOD_SPACE_R6/20261004T072652+0000_dded6a2f/source_audit/OPPORTUNITY_METADATA_PREPARE_SOURCE.py.txt').read_text(encoding='utf8')
    fn=next(n for n in ast.parse(snapshot).body if isinstance(n,ast.FunctionDef) and n.name=='qualify_rows')
    namespace=dict(e.__dict__);exec(compile(ast.Module(body=[fn],type_ignores=[]),'actual_metadata_producer_snapshot','exec'),namespace)
    original=namespace['qualify_rows']
    for mutation in ('NONE','UNKNOWN_UID','CLASS_CONFLICT','INTERVAL_GAP','OLD_PANEL_CONFLICT','MISSING_DAY','DUPLICATE_DECLARATION'):
        module,f,r,i,p,h,d=identity_fixture()
        if mutation=='UNKNOWN_UID':f['security_id']='UNKNOWN'
        elif mutation=='CLASS_CONFLICT':i=e.pd.concat([i,i.assign(title_of_class='OTHER_CLASS')],ignore_index=True)
        elif mutation=='INTERVAL_GAP':i['effective_start']=d[3]
        elif mutation=='OLD_PANEL_CONFLICT':p['security_id']='CONFLICTING_REAL_UID'
        elif mutation=='MISSING_DAY':f=f.loc[f.signal_date.ne(d[2])]
        elif mutation=='DUPLICATE_DECLARATION':i=e.pd.concat([i,i],ignore_index=True)
        left=original(f,r,i,p,h,d);right=e.qualify_rows(f,r,i,p,h,d)
        e.pd.testing.assert_frame_equal(left,right)


@pytest.mark.parametrize('bad_uid',[None,'UNKNOWN','DIFFERENT_REAL_UID','MISSING_ROW','DUPLICATE_ROW'])
def test_bad_native_uid_metadata_never_calls_mu_scanner(monkeypatch,bad_uid):
    from scripts.research.a2.training import joint_method_space_opportunity_execution_r6 as e
    import pyarrow as pa
    keys=metadata(1).copy();keys['signal_date']=pd.Timestamp('2023-01-03');calls=[]
    class Dataset:
        schema=pa.schema([('signal_date',pa.timestamp('ns')),('ticker',pa.string()),('security_id',pa.string()),('native_mu',pa.float64())])
        def to_table(self,*,columns,filter):
            calls.append(columns)
            if 'native_mu' in columns:raise AssertionError('PREDICTION_BODY_BEFORE_SOURCE_UID')
            df=keys[e.KEYS].copy();df['security_id']=bad_uid
            if bad_uid=='MISSING_ROW':df=df.iloc[:0]
            if bad_uid=='DUPLICATE_ROW':df=pd.concat([df,df],ignore_index=True)
            return SimpleNamespace(to_pandas=lambda:df[columns].copy())
    receipt=dict(source_fit_cutoff='2023-01-01',source_label_mature_max='2022-12-27')
    monkeypatch.setattr(e,'_pinned_receipt',lambda *a,**k:(receipt,{'sha256':'a'*64},{'path':'synthetic','sha256':'b'*64},'native_mu','native_sigma'))
    monkeypatch.setattr(e,'_native_identity_audit_guard',lambda *a,**k:True)
    monkeypatch.setattr(e.old,'_safe_source',lambda p:p);monkeypatch.setattr(e.old,'_pin',lambda *a:None)
    stats=SimpleNamespace(has_min_max=True,max=pd.Timestamp('2023-01-03'))
    footer=SimpleNamespace(schema=SimpleNamespace(names=['signal_date']),metadata=SimpleNamespace(num_row_groups=1,row_group=lambda i:SimpleNamespace(column=lambda j:SimpleNamespace(statistics=stats))))
    monkeypatch.setattr(e.pq,'ParquetFile',lambda p:footer);monkeypatch.setattr(e.ds,'dataset',lambda *a,**k:Dataset())
    with pytest.raises(e.Blocked,match='METADATA_KEY|PREBODY'):e.read_native_oof(SimpleNamespace(),2023,'ridge',keys,r4=True)
    assert calls==[['signal_date','ticker','security_id']]


def test_native_uid_gate_preserves_complete_ordered_request():
    from scripts.research.a2.training import joint_method_space_opportunity_execution_r6 as e
    import pyarrow as pa
    keys=metadata(2).copy();keys['signal_date']=pd.to_datetime(['2023-01-03','2023-01-04']);calls=[]
    class Dataset:
        schema=pa.schema([('signal_date',pa.timestamp('ns')),('ticker',pa.string()),('security_id',pa.string())])
        def to_table(self,*,columns,filter):
            df=keys[e.KEYS].iloc[[len(calls)]].copy();df['security_id']='REAL_SECURITY_UID';calls.append(columns)
            return SimpleNamespace(to_pandas=lambda:df[columns].copy())
    proof=e._oof_source_metadata(Dataset(),keys,'security_id')
    assert len(proof)==len(keys) and proof.source_uid.eq(proof.security_uid).all()
    pd.testing.assert_frame_equal(proof[e.KEYS],keys[e.KEYS])
    assert calls==[['signal_date','ticker','security_id']]*2
