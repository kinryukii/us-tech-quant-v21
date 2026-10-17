"""R10 evaluation consumer: fabricated frames only, zero fit/file/account I/O."""
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import stateful_mechanism_evaluation as e
from scripts.research.a2.training import stateful_mechanism as r


def frame(n=4):
    dates=pd.to_datetime(['2024-01-02','2024-01-03','2025-01-02','2025-01-03'])[:n]
    f=pd.DataFrame(dict(signal_date=dates,label_mature_date=dates+pd.Timedelta(days=7),
        sample_id=['synthetic-'+str(j) for j in range(n)],ticker='SYN',
        security_id='SYNTHETIC_SID',target=np.resize([.002,-.003],n),
        reference_action=0.,label_qualified=True,base_weight=1.))
    return f


def prediction(n=4,**overrides):
    return dict(mean=np.resize([.002,-.003],n),probability=np.resize([.8,.2],n),
                q10=np.resize([.001,-.005],n),q50=np.resize([.002,-.003],n),
                q90=np.resize([.003,-.001],n),sigma=np.ones(n)*.001,**overrides)


def risk(f,**overrides):
    return pd.DataFrame(dict(signal_date=f.signal_date,sample_id=f.sample_id,
        risk_delta=np.ones(len(f))*.0005,portfolio_sigma=np.ones(len(f))*.04,
        regime_probability=np.ones(len(f))*.25,risk_qualified=True,**overrides))


def test_native_diagnostic_metrics_and_no_calibration_fit():
    d=e.distribution_diagnostics(frame(),prediction())
    assert d['mean_mae']==0.
    assert d['probability_brier']==pytest.approx(.04)
    assert d['native_80_interval_coverage']==1.
    assert d['native_sigma_rows']==4
    assert len(d['fixed_probability_bins'])==10
    assert d['sigma_from_residuals_or_fusion_diagnostics'] is False


def test_probability_only_model_cannot_become_mean_sigma_or_q():
    d=e.distribution_diagnostics(frame(),dict(probability=np.ones(4)*.6))
    assert d['mean_mae'] is None and d['gaussian_nll'] is None and d['q10_pinball'] is None
    streams=e.resolver_streams(frame(),dict(probability=np.ones(4)*.6),group='ENTRY')
    assert len(streams)==12 and all(s['status'].startswith('BLOCKED') for s in streams.values())


@pytest.mark.parametrize('field',('q10','sigma'))
def test_missing_native_capability_stays_blocked(field):
    pred=prediction();pred[field]=None
    streams=e.resolver_streams(frame(),pred,group='ENTRY')
    assert streams['P1' if field=='q10' else 'P2']['status']=='BLOCKED_CAPABILITY_OR_INPUT'
    assert streams['P0']['status']=='AVAILABLE'


def test_fixed_twelve_resolvers_risk_buffer_and_half():
    f=frame();streams=e.resolver_streams(f,prediction(),group='ENTRY',risk=risk(f))
    assert tuple(streams)==e.RECIPES
    assert streams['P0']['action'].tolist()==[1,0,1,0]
    assert streams['P5']['action'].tolist()==[.5,0,.5,0]
    assert streams['P9']['gross'].tolist()==[.5]*4
    assert streams['P11']['gross'].tolist()==[.75]*4
    assert streams['P3']['metrics']['additional_hurdle_is_not_fee'] is True


def test_hurdle_already_net_no_extra_cost_debit():
    f=frame();p=prediction();p['mean']=np.ones(4)*.001
    streams=e.resolver_streams(f,p,group='ENTRY')
    assert np.all(streams['P0']['action']==1)
    assert np.all(streams['P3']['action']==0)
    assert np.array_equal(streams['P3']['frame'].target,f.target)


@pytest.mark.parametrize('bad',(False,1,None))
def test_risk_literal_true_rejects_bad_values(bad):
    f=frame();q=risk(f);q['risk_qualified']=bad
    s=e.resolver_streams(f,prediction(),group='ENTRY',risk=q)
    for name in ('P4','P6','P7','P9','P11'):assert s[name]['status']=='BLOCKED_CAPABILITY_OR_INPUT'
    assert s['P0']['status']=='AVAILABLE'


def test_negative_risk_delta_not_rewarded():
    f=frame();q=risk(f);q['risk_delta']=-.9
    s=e.resolver_streams(f,prediction(),group='ENTRY',risk=q)
    assert np.array_equal(s['P6']['decision_score'],s['P0']['decision_score'])


def test_unknown_regime_does_not_become_low_regime():
    f=frame();q=risk(f);q['regime_probability']=np.nan
    s=e.resolver_streams(f,prediction(),group='ENTRY',risk=q)
    assert np.isnan(s['P11']['gross']).all()
    assert s['P11']['status']=='BLOCKED_CAPABILITY_OR_INPUT'


def test_incumbent_hysteresis_is_action_specific():
    f=frame();f['action_type']=[0,1,0,1];p=prediction();p['mean']=np.ones(4)*.001
    q=risk(f);q['risk_delta']=0.
    s=e.resolver_streams(f,p,group='INCUMBENT',risk=q)
    assert s['P4']['action'].tolist()==[1.,0.,1.,0.]


def test_unknown_partial_incumbent_score_cannot_claim_full_oracle():
    f=frame();f['signal_date']=pd.to_datetime(['2024-01-02']*4)
    f['required_actionset_count']=4;f['required_actionset_sha256']=r.digest(sorted(f.sample_id))
    p=prediction();p['mean'][0]=np.nan
    s=e.resolver_streams(f,p,group='INCUMBENT')
    full=s['P0']['full_oracle']
    assert not full.complete_action_labels.any()
    assert s['P5']['full_oracle'] is None


def gross_grid(f):
    records=[]
    for date in f.signal_date:
        for g in e.GRID:
            records.append(dict(signal_date=date,label_mature_date=date+pd.Timedelta(days=7),
                sample_id=str(date)+'|G'+str(g),gross_previous_proxy=1.,gross_candidate=g,
                label_qualified=True,target=-(g-.5)**2,mean=-(g-.5)**2,q10=-(g-.25)**2))
    return pd.DataFrame(records)


def test_gross_native_full_grid_choices_and_undefined_gprev():
    f=frame();grid=gross_grid(f)
    s=e.resolver_streams(f,prediction(),group='ENTRY',gross_predictions={'P8':grid,'P10':grid})
    assert s['P8']['status']=='BLOCKED_CAPABILITY_OR_INPUT'
    f['gross_previous_proxy']=1.
    s=e.resolver_streams(f,prediction(),group='ENTRY',gross_predictions={'P8':grid,'P10':grid})
    assert np.all(s['P8']['gross']==.5) and np.all(s['P10']['gross']==.25)
    assert s['P8']['gross_metric']['metrics']['metric_role']=='DATE_BALANCED_GROSS_PROXY_REGRET_NOT_ACCOUNT'


def test_missing_gross_grid_never_argmaxes_survivors():
    f=frame();f['gross_previous_proxy']=1.
    grid=gross_grid(f);grid=grid.loc[grid.gross_candidate!=.5]
    s=e.resolver_streams(f,prediction(),group='ENTRY',gross_predictions={'P8':grid})
    assert np.isnan(s['P8']['gross']).all()


def test_hazard_event_not_monetary_target_and_unknown_censor():
    f=frame();f['target']=[0.,1.,0.,1.];f['label_value']=[.02,-.03,.01,-.01]
    f['probe_age']=[0,7,0,7];f['cohort_id']=['a','a','b','b']
    f['hazard_at_risk']=True;f['right_censored_unknown']=[False,False,False,True]
    f.loc[3,'label_qualified']=False
    p=dict(probability=np.array([.2,.8,.2,.8]))
    out=e.hazard_duration_regret(f,p)
    assert out['metrics']['date_balanced_improvement'] is not None
    assert out['probe_duration'].loc[out['probe_duration'].cohort_id.eq('a'),'observed_probe_event_age'].iloc[0]==7.
    assert pd.isna(out['probe_duration'].loc[out['probe_duration'].cohort_id.eq('b'),'observed_probe_event_age'].iloc[0])
    assert not out['probe_duration'].true_terminal_duration_known.any()


def test_paired_streams_same_keys_reordering_and_no_target_drift():
    f=frame();a=e.resolver_streams(f,prediction(),group='ENTRY')['P0']
    rev=f.iloc[::-1].reset_index(drop=True);p={k:v[::-1] for k,v in prediction().items()}
    b=e.resolver_streams(rev,p,group='ENTRY')['P0']
    result=e.paired_stream_contrast(a,b,name='synthetic')
    assert np.all(result['daily_improvement']==0)
    b['frame'].loc[0,'target']+=.01
    with pytest.raises(ValueError,match='TARGET_IDENTITY'):e.paired_stream_contrast(a,b,name='synthetic')


def test_unmatched_planned_support_blocks_paired_claim():
    f=frame();a=e.resolver_streams(f,prediction(),group='ENTRY')['P0']
    b=e.resolver_streams(f.iloc[:2].copy(),prediction(2),group='ENTRY')['P0']
    d=e.paired_stream_contrast(a,b,name='synthetic')
    assert d['status']=='BLOCKED_UNMATCHED_EX_ANTE_SOURCE_SUPPORT'


def test_registered_twenty_preserves_missing_and_ci_delegation():
    f=frame();streams=e.resolver_streams(f,prediction(),group='ENTRY',risk=risk(f))
    calls=[]
    owner=SimpleNamespace(local_regret=r.local_regret,gross_regret=r.gross_regret,
        full_incumbent_oracle=r.full_incumbent_oracle,simultaneous_bounds=lambda series:calls.append(series) or {})
    result=e.registered_interactions(streams,owner=owner)
    assert len(result['contrasts'])==20 and len(calls)==1
    assert any(x['status']=='BLOCKED_PREDECLARED_STREAM_MISSING' for x in result['contrasts'])
    assert result['new_fit']==0
    assert result['contrasts'][-1]['mechanism_support_from_cost_level_choice'] is False


def test_friction_sensitivity_same_actions_all_horizon_and_no_refit():
    f=frame();f['action_type']=1.;f['e_y']=.04;f['i_y']=.01
    native={h:f.copy() for h in inputs_horizons()}
    result=e.friction_sensitivity(np.ones(4),native)
    assert set(result)=={5,10,20}
    assert result[5]['metrics']['date_balanced_improvement']>result[20]['metrics']['date_balanced_improvement']
    assert all(v['fixed_action_identity']=='ORIGINAL_10BPS_NO_REFIT_OR_RETUNE' for v in result.values())
    with pytest.raises(ValueError,match='ALL_FOUR'):e.friction_sensitivity(np.ones(4),{5:f})


def inputs_horizons():return (3,5,10,20)


def test_report_fifteen_questions_and_no_invented_answers():
    report=e.question_report({'13':'Source/account slots unbound'},budget_actual=123)
    assert len(report['questions'])==15
    assert report['questions'][0]['status']=='NOT_ESTABLISHED'
    assert report['questions'][12]['status']=='EVIDENCE_SUPPLIED'
    assert report['automatic_R11_created'] is False and report['report_generation_new_fit']==0


@pytest.mark.parametrize('call',(
    lambda f:e.distribution_diagnostics(f,prediction()),
    lambda f:e.resolver_streams(f,prediction(),group='ENTRY'),
    lambda f:e.hazard_duration_regret(f,dict(probability=np.ones(4)*.5))))
def test_2026_forbidden_at_input_boundary(call):
    f=frame();f.loc[0,'signal_date']=pd.Timestamp('2026-01-01')
    with pytest.raises(ValueError):call(f)


def test_no_hidden_io_or_fit_entrypoints():
    assert not hasattr(e,'fit') and not hasattr(e,'read_json')
    assert len(e.INTERACTIONS)==20 and len(e.RECIPES)==12


def test_comparison_templates_fixed_and_role_aliases():
    spec=e.comparison_templates()
    assert spec['sequence']['variants']==['S1','S2','S3']
    assert len(spec['fusion']['equal_median_reference_families'])==14
    assert len(spec['registered_interactions'])==20
    f=frame();f['action_type']=[-1,0,1,1]
    roles=dict(e._role_frames(f,'JOINT_SEQUENCE'))
    assert set(roles)=={'JOINT_SEQUENCE','INCUMBENT','CONTINUATION','SELL/HOLD','REPLACE_EDGE'}
    assert len(roles['INCUMBENT'])==3


def synthetic_complete_setup(tmp_path,monkeypatch):
    from scripts.common import storage_paths
    run=tmp_path/'backtests'/'synthetic_run';run.mkdir(parents=True)
    root=tmp_path/'results'/'task';root.mkdir(parents=True)
    monkeypatch.setattr(r,'RESULT',root)
    monkeypatch.setattr(storage_paths,'resolve',lambda *a,**k:SimpleNamespace(results_root=tmp_path/'results'))
    import json
    def synthetic_save(path,value):
        path=__import__('pathlib').Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(r.clean(value),default=str),encoding='utf-8')
    monkeypatch.setattr(r,'save',synthetic_save)
    def synthetic_append(path,value):
        path=__import__('pathlib').Path(path)
        with path.open('a',encoding='utf-8') as handle:handle.write(json.dumps(value)+'\n')
    monkeypatch.setattr(r.fit_owner,'_append',synthetic_append)
    for name in ('ACTION_BATCH.json','HAZARD_CONTINUATION_BATCH.json','SEQUENCE_BATCH.json',
                 'SHARED_RISK_BATCH.json','RISK_ACTION_BATCH.json','FUSION_BATCH.json',
                 'SEQUENCE_FUSION_BATCH.json','GROSS_BATCH.json'):
        synthetic_save(run/name,dict(status='COMPLETE'))
    design=dict(scientific_identity=r.IDENTITY,account_authorized=False,source_activated=False,**r.AUTHORITY)
    r.save(run/'FROZEN_DESIGN.json',design)
    r.save(root/'R10_INFO_EXPOSURE_RECEIPT.json',dict(status='INCIDENTAL_SOURCE_COMMENT_EXPOSURE_DISCLOSED_NO_USE',
        real_2026_or_2027_table_read=0,real_2026_prediction_account_or_financial_output_file_read=0))
    f=frame()
    native={h:{'ENTRY':f.copy(),'INCUMBENT':f.assign(action_type=1.,e_y=.04,i_y=.01),'CONTINUATION':f.iloc[:0].copy()} for h in (3,5,10,20)}
    native['MEAN']={'ENTRY':f.copy(),'INCUMBENT':f.assign(action_type=1.,e_y=.04,i_y=.01),'CONTINUATION':f.iloc[:0].copy()}
    bundle=SimpleNamespace(metadata_coverage=dict(role='SYNTHETIC_ONLY',planned_rows=4),frames=SimpleNamespace(gross=gross_native_labels()))
    calls=[]
    def ci(series,**kwargs):
        calls.append(series)
        return {key:dict(status='NO_SUPPORT',ci_status='CI_NOT_TESTABLE',yearly_improvement={'2024':None,'2025':None},
                    pooled_improvement=None,simultaneous_lower95=None) for key in series}
    monkeypatch.setattr(r,'simultaneous_bounds',ci)
    return run,root,design,native,bundle,calls


def synthetic_pub(run,f,*,horizon='MEAN',family='hgb',year=2024,group='ENTRY',**extra):
    path=run/'predictions'/(group+str(horizon)+family+str(year)+'.parquet')
    path.parent.mkdir(parents=True,exist_ok=True)
    if family=='gaussian_mlp':
        f=f.copy();f['sigma']=.001;f['q10']=f['mean']-.0012815515655
        f['q50']=f['mean'];f['q90']=f['mean']+.0012815515655
        refs=[]
        for seed in range(3):
            seed_path=path.with_name(path.stem+'seed'+str(seed)+'.parquet')
            f.to_parquet(seed_path,index=False)
            slot=group+str(year)+'GaussianSeed'+str(seed)
            receipt=run/'models/mechanism'/slot/'fit_receipt.json'
            artifact=receipt.with_name('model.synthetic')
            artifact.parent.mkdir(parents=True,exist_ok=True);artifact.write_text('SYNTHETIC_NO_REAL_MODEL_FIT',encoding='utf-8')
            sha='SYNTHETIC_TUPLE_'+slot
            r.save(receipt,dict(slot_id=slot,scientific_tuple_sha256=sha,status='TRAINED',fit_units=1,
                   family=family,group=group,horizon=horizon,year=year,capacity='MID',seed=r.SEEDS[seed],cutoff_exclusive=f'{year}-01-01',
                   model_path=str(artifact),model_sha256=r.fit_owner.sha(artifact),receipt_path=str(receipt),
                   publication=dict(path=str(seed_path),sha256=r.fit_owner.sha(seed_path))))
            r.fit_owner._append(run/'FIT_LOG.jsonl',dict(event='FIT_STARTED',model_id=slot,year=year,
                role='SYNTHETIC_ONLY',reuse_tuple_sha256=sha,budget_bucket='ACTION_VALUE',fit_units=1))
            refs.append(str(receipt))
        extra['seed_receipts']=refs
    f.to_parquet(path,index=False)
    return dict(path=str(path),sha256=r.fit_owner.sha(path),slot_id=path.stem,group=group,family=family,
                capacity='MID',year=year,horizon=horizon,prefix=False,**extra)


def test_complete_study_actual_synthetic_io_budget_blocked_exposure_and_horizon(tmp_path,monkeypatch):
    run,root,design,native,bundle,calls=synthetic_complete_setup(tmp_path,monkeypatch)
    blocked=run/'models/mechanism/synthetic_block/fit_receipt.json'
    r.save(blocked,dict(slot_id='synthetic_block',status='BLOCKED_INPUT',fit_units=0,reason='SYNTHETIC_SOURCE'))
    pubs=[]
    for year in (2024,2025):
        f=frame();f=f.loc[f.signal_date.dt.year.eq(year)].copy();f['mean']=.002
        pubs.append(synthetic_pub(run,f,year=year))
        pubs.append(synthetic_pub(run,f,family='gaussian_mlp',year=year))
        other=f.copy();other['mean']=-.002
        pubs.append(synthetic_pub(run,other,horizon=5,year=year))
    result=e.complete_study(run,design,bundle,native,pubs,risk_result=dict(blocks=[dict(reason='SYNTHETIC_NATIVE_REGIME_UNBOUND')]))
    assert result['status']=='R10_PARTIAL_INPUT_BLOCKED'
    assert result['fit_units_actual']==6 and result['real_account']==0
    assert len(calls)==1
    # Primary and native horizon keep distinct identities; H5 cannot replace
    # the frozen primary MID anchor used by P0.
    assert any('ENTRY|5|hgb' in key for key in calls[0])
    assert any('ENTRY|MEAN|hgb' in key for key in calls[0])
    resolver=pd.read_parquet(result['tables']['resolver_coverage']['path'])
    p0=resolver.loc[resolver.recipe.eq('P0')]
    assert (p0.action_rate==1.).all()
    assert not any('RESOLVER|ENTRY|P9'==key for key in calls[0])
    assert result['information_exposure']['claim_absolute_2026_information_zero_exposure'] is False
    assert result['R9_174_budget_consumed']==0
    report=(root/run.name/'REPORT.md').read_text(encoding='utf-8')
    assert '代码' in report or '源码' in report
    assert '2026 信息零暴露' in report
    assert len(result['questions']['questions'])==15
    assert (run/'EXECUTION_STATUS.json').exists()


def test_complete_study_rejects_foreign_publication_custody(tmp_path,monkeypatch):
    run,root,design,native,bundle,calls=synthetic_complete_setup(tmp_path,monkeypatch)
    foreign=tmp_path/'foreign-synthetic.parquet';frame().to_parquet(foreign,index=False)
    pub=dict(path=str(foreign),sha256=r.fit_owner.sha(foreign),year=2024,group='ENTRY',family='hgb',horizon='MEAN',capacity='MID')
    with pytest.raises(RuntimeError,match='ENGINEERING_RECOVERY_REQUIRED'):
        e.complete_study(run,design,bundle,native,[pub])
    details=r.read_json(root/run.name/'ENGINEERING_BLOCKERS.json')
    assert details['publication_errors'][0]['error'].endswith('OWN_RUN_ARTIFACT_CUSTODY')
    assert not (run/'EXECUTION_STATUS.json').exists()


def test_complete_paired_fusion_templates_no_outcome_member_selection(tmp_path,monkeypatch):
    run,root,design,native,bundle,calls=synthetic_complete_setup(tmp_path,monkeypatch)
    pubs=[]
    for year in (2024,2025):
        f=frame();f=f.loc[f.signal_date.dt.year.eq(year)].copy()
        for family in ('ridge','hgb','fusion_stack_ridge'):
            ff=f.copy();ff['mean']=.002
            pubs.append(synthetic_pub(run,ff,family=family,year=year))
    e.complete_study(run,design,bundle,native,pubs)
    assert 'FUSION_PAIRED|ENTRY|fusion_stack_ridge|vsridge|ENTRY' in calls[0]
    assert 'FUSION_PAIRED|ENTRY|fusion_stack_ridge|vshgb|ENTRY' in calls[0]


def test_complete_learned_risk_r7_and_r0_match_horizon_and_roles(tmp_path,monkeypatch):
    run,root,design,native,bundle,calls=synthetic_complete_setup(tmp_path,monkeypatch)
    pubs=[]
    for year in (2024,2025):
        f=frame();f=f.loc[f.signal_date.dt.year.eq(year)].copy()
        for group in ('ENTRY_R0','ENTRY_R7'):
            ff=f.copy();ff['mean']=.002
            pubs.append(synthetic_pub(run,ff,group=group,year=year))
    e.complete_study(run,design,bundle,native,pubs)
    assert 'LEARNED_RISK_PAIRED|ENTRY_R7|hgb|vsR0|ENTRY' in calls[0]


def gross_native_labels():
    dates=frame().signal_date
    names=tuple('SYN'+str(i) for i in range(20));sids=tuple('SYNTHETIC_SID'+str(i) for i in range(20))
    f=pd.DataFrame(dict(signal_date=dates,label_mature_date=dates+pd.Timedelta(days=21),
              sample_id=['RAW20_'+str(d.date()) for d in dates],basket_y=.01,label_qualified=True,
              raw20_count=20,basket_members=[names]*len(dates),basket_sids=[sids]*len(dates)))
    return {h:f.copy() for h in (3,5,10,20)}


def test_distribution_rebalances_each_valid_metric_date():
    f=frame(2)
    f=pd.concat([f.iloc[[0]]]*10+[f.iloc[[1]]],ignore_index=True)
    f['sample_id']=['SYN_MASK_'+str(i) for i in range(len(f))]
    f['target']=0.
    pred=dict(mean=np.array([10.]+[np.nan]*9+[0.]))
    assert e.distribution_diagnostics(f,pred)['mean_mae']==5.


def test_exact_three_equal_normal_mixture_reduces_to_single_normal():
    f=frame();pred=prediction();n=len(f)
    single=e.distribution_diagnostics(f,pred)
    mixture=dict(mean=np.repeat(pred['mean'][:,None],3,axis=1),
                 sigma=np.repeat(pred['sigma'][:,None],3,axis=1))
    exact=e.distribution_diagnostics(f,pred,mixture=mixture,gaussian_mixture=True)
    assert exact['gaussian_density_role']=='EXACT_EQUAL_THREE_NATIVE_NORMAL_MIXTURE'
    assert exact['gaussian_nll']==pytest.approx(single['gaussian_nll'])
    assert exact['gaussian_crps']==pytest.approx(single['gaussian_crps'])


def test_mixture_moment_match_never_claims_native_density():
    d=e.distribution_diagnostics(frame(),prediction(),gaussian_mixture=True)
    assert d['gaussian_nll'] is None and d['gaussian_crps'] is None
    assert d['gaussian_nll_moment_matched_approx'] is not None


def test_gross_pair_matching_date_alone_is_insufficient():
    f=frame();f['gross_previous_proxy']=1.
    a=e.resolver_streams(f,prediction(),group='ENTRY',gross_predictions={'P8':gross_grid(f)})['P8']
    g=gross_grid(f);g['gross_previous_proxy']=.5
    b=e.resolver_streams(f,prediction(),group='ENTRY',gross_predictions={'P8':g})['P8']
    result=e.paired_stream_contrast(a,b,name='SYNTHETIC_GROSS',gross=True)
    assert result['status']=='BLOCKED_UNMATCHED_COMPLETE_NATIVE_GRID'


def test_complete_missing_batch_refuses_terminal(tmp_path,monkeypatch):
    run,root,design,native,bundle,calls=synthetic_complete_setup(tmp_path,monkeypatch)
    (run/'SEQUENCE_BATCH.json').unlink()
    with pytest.raises(RuntimeError,match='ENGINEERING_RECOVERY_REQUIRED'):
        e.complete_study(run,design,bundle,native,[])
    details=r.read_json(root/run.name/'ENGINEERING_BLOCKERS.json')
    assert any(a.get('error')=='BATCH_NOT_COMPLETE' for a in details['audits'])
    assert not (run/'EXECUTION_STATUS.json').exists()


def test_orphan_fit_start_and_unacknowledged_training_cannot_complete(tmp_path,monkeypatch):
    run,root,design,native,bundle,calls=synthetic_complete_setup(tmp_path,monkeypatch)
    r.fit_owner._append(run/'FIT_LOG.jsonl',dict(event='FIT_STARTED',model_id='orphan',year=2024,
             role='SYNTHETIC_ONLY',reuse_tuple_sha256='synthetic',budget_bucket='ACTION_VALUE',fit_units=1))
    with pytest.raises(RuntimeError,match='ENGINEERING_RECOVERY_REQUIRED'):
        e.complete_study(run,design,bundle,native,[])
    details=r.read_json(root/run.name/'ENGINEERING_BLOCKERS.json')
    assert any(a.get('error')=='UNTERMINATED_FIT_STARTED_OR_RECEIPT_IDENTITY' for a in details['audits'])


def test_sequence_lookbacks_do_not_merge_primary_dates(tmp_path,monkeypatch):
    run,root,design,native,bundle,calls=synthetic_complete_setup(tmp_path,monkeypatch)
    pubs=[]
    for year in (2024,2025):
        f=frame();f=f.loc[f.signal_date.dt.year.eq(year)].copy();f['mean']=.002
        for length in (5,10,20):
            pubs.append(synthetic_pub(run,f,family='tcn',year=year,group='JOINT_SEQUENCE',lookback=length))
    result=e.complete_study(run,design,bundle,native,pubs)
    assert result['status']=='R10_FULL_BREADTH_COMPLETE_NO_SUPPORT'
    assert all(any('JOINT_SEQUENCE|L'+str(length)+'|' in key for key in calls[0]) for length in (5,10,20))


def native_risk_result_for_gross():
    native=gross_native_labels()[5];projections=[]
    for row in native.itertuples():
        request=dict(date=str(row.signal_date.date()),horizon=5,cohort='FROZEN_RAW20_EQUAL',
                     reference_assets=row.basket_members,uids=dict(zip(row.basket_members,row.basket_sids)))
        for rep,features,sigma in (('R1',{},.04),('R4',dict(portfolio_downside_sigma=.02),.03),
                                   ('R5',dict(active_regime=1),.03)):
            projections.append(dict(request=request,representation=rep,
                 projection=dict(features=features,diagnostics=dict(predicted_portfolio_sigma=sigma))))
    return dict(projections=projections)


def test_nonml_gross_g0_g1_g2_continue_when_ml_context_unknown():
    controls=e.nonml_gross_controls(gross_native_labels(),native_risk_result_for_gross())
    status={row['control']:row['status'] for row in controls['summaries']}
    assert status['G0']==status['G1']==status['G2']=='AVAILABLE_PROXY_ONLY'
    assert status['G3']==status['G4']=='BLOCKED_NATIVE_INPUT'
    rows=controls['rows']
    assert (rows.loc[rows.control.eq('G1'),'selected_G']==.5).all()
    assert not rows.account_qualified.any()
    assert controls['new_fit']==0


def test_nonml_gross_any_missing_raw20_constituent_blocks_date():
    packets=gross_native_labels();packets[20].loc[0,'raw20_count']=19
    controls=e.nonml_gross_controls(packets,native_risk_result_for_gross())
    date=packets[20].loc[0,'signal_date']
    assert not controls['rows'].loc[controls['rows'].signal_date.eq(date),'known'].any()


def test_native_quantile_uncertainty_has_no_sigma_fallback():
    f=frame();pred=dict(q50=np.ones(4)*.002,q10=np.ones(4)*-.002)
    c=e.native_distribution_contrasts(f,pred)
    assert c['U1']['status']=='PAIRED_CONDITIONAL_PROXY'
    assert c['U2']['status']=='BLOCKED_NO_NATIVE_CAPABILITY'


@pytest.mark.parametrize('group',('ENTRY','GROSS'))
def test_actual_publisher_missing_custody_metadata_exact_rebind(tmp_path,group):
    f=frame();f['entrant_sid']='SYN_ENTRANT';f['incumbent_sid']='SYN_INCUMBENT'
    f['pre_label_group_weight']=.25;f['source_label_identity']='SYN_ORIGINAL_LABEL'
    if group=='GROSS':
        f['basket_members']=[('A','B')]*len(f);f['basket_sids']=[('SID_A','SID_B')]*len(f);f['raw20_count']=20
        f['gross_previous_proxy']=1.;f['gross_candidate']=.5
    pub=r.publish_prediction(tmp_path,dict(slot_id='actual_synthetic_publisher'),f,dict(mean=np.zeros(len(f))))
    raw=pd.read_parquet(pub['path'])
    assert 'pre_label_group_weight' not in raw and 'source_label_identity' not in raw
    assert 'entrant_sid' not in raw and 'basket_sids' not in raw
    raw.loc[0,'label_qualified']=False
    restored=e.rebind_published_metadata(raw,f)
    assert not restored.loc[0,'label_qualified']
    assert np.array_equal(restored.target,raw.target,equal_nan=True)
    assert np.array_equal(restored['mean'],raw['mean'],equal_nan=True)
    assert restored['source_label_identity'].eq('SYN_ORIGINAL_LABEL').all()
    if group=='GROSS':assert tuple(restored.loc[0,'basket_sids'])==('SID_A','SID_B')


@pytest.mark.parametrize('defect',('target','maturity','sid','key','qualification','metadata'))
def test_metadata_rebind_cannot_overwrite_conflict_or_promote(defect):
    f=frame();f['security_id']='SYN_SID';f['source_label_identity']='SYN_ORIGINAL'
    raw=f.copy();raw['mean']=.123
    if defect=='target':raw.loc[0,'target']+=.1
    elif defect=='maturity':raw.loc[0,'label_mature_date']+=pd.Timedelta(days=1)
    elif defect=='sid':raw.loc[0,'security_id']='OTHER'
    elif defect=='key':raw.loc[0,'sample_id']='OTHER'
    elif defect=='qualification':f.loc[0,'label_qualified']=False
    elif defect=='metadata':raw.loc[0,'source_label_identity']='OTHER'
    with pytest.raises(ValueError,match='PUBLISHED_'):e.rebind_published_metadata(raw,f)


def test_main_oof_footer_guard_runs_before_forbidden_body_read(tmp_path,monkeypatch):
    run,root,design,native,bundle,calls=synthetic_complete_setup(tmp_path,monkeypatch)
    f=frame();f.loc[0,'signal_date']=pd.Timestamp('2026-01-01');f['mean']=.1
    pub=synthetic_pub(run,f)
    called=[]
    monkeypatch.setattr(e.pd,'read_parquet',lambda *a,**k:called.append(a) or (_ for _ in ()).throw(AssertionError('BODY_MUST_NOT_READ')))
    with pytest.raises(RuntimeError,match='ENGINEERING_RECOVERY_REQUIRED'):e.complete_study(run,design,bundle,native,[pub])
    assert not called
    assert not (run/'EXECUTION_STATUS.json').exists()


def test_gaussian_seed_footer_guard_runs_before_forbidden_leaf_body_read(tmp_path,monkeypatch):
    run,root,design,native,bundle,calls=synthetic_complete_setup(tmp_path,monkeypatch)
    f=frame();f=f.loc[f.signal_date.dt.year.eq(2024)].copy();f['mean']=.002
    pub=synthetic_pub(run,f,family='gaussian_mlp')
    receipt=r.read_json(pub['seed_receipts'][0]);leaf=__import__('pathlib').Path(receipt['publication']['path'])
    corrupt=pd.read_parquet(leaf);corrupt.loc[0,'signal_date']=pd.Timestamp('2026-01-01');corrupt.to_parquet(leaf,index=False)
    receipt['publication']['sha256']=r.fit_owner.sha(leaf);r.save(pub['seed_receipts'][0],receipt)
    original=pd.read_parquet;reads=[]
    def read(path,*args,**kwargs):
        if __import__('pathlib').Path(path).resolve()==leaf.resolve():raise AssertionError('LEAF_BODY_MUST_NOT_READ')
        reads.append(str(path));return original(path,*args,**kwargs)
    monkeypatch.setattr(e.pd,'read_parquet',read)
    with pytest.raises(RuntimeError,match='ENGINEERING_RECOVERY_REQUIRED'):e.complete_study(run,design,bundle,native,[pub])
    assert len(reads)==1


def test_existing_owner_risk_numeric_tables_and_sid_stability_without_fit():
    from tests.research.a2.risk.test_mechanism_risk_diagnostics import fixture
    from dataclasses import replace
    state,observations=fixture()
    packet=pd.DataFrame(dict(signal_date=[pd.Timestamp('2024-02-01')],label_mature_date=[pd.Timestamp('2024-02-08')]))
    # The owner's native-observation clock adapter is called with the exact
    # supplied synthetic packet. No estimator/calibrator is involved.
    original=e.inputs.native_risk_observations
    e.inputs.native_risk_observations=lambda f:observations.copy()
    try:
        projections=[]
        for date,uid,v in [('2025-01-02','SID_A',.3),('2024-12-31','SID_A',.2),('2025-01-03','CHANGED',.7)]:
            projections.append(dict(request=dict(date=date,horizon=5,cohort='TEST',assets=['A'],uids={'A':uid}),representation='R6',
                projection=dict(features=dict(normalized_marginal_risk=[v],jackknife_sigma_SE=[.1]),diagnostics=dict(PSD=True))))
        result=e.risk_diagnostic_tables(dict(states=[state],projections=projections,shared_exact_refs=['NOT_RELOADED']),
                                       SimpleNamespace(native_endpoint_labels={5:packet}))
    finally:e.inputs.native_risk_observations=original
    assert result['new_fit']==0 and result['shared_exact_refs_not_reloaded']==['NOT_RELOADED']
    assert result['state_numerical'].iloc[0].status=='PASS_NUMERICAL_DIAGNOSTIC_ONLY'
    assert result['volatility_downside'].iloc[0].status=='PASS_CALIBRATION_DIAGNOSTIC_ONLY'
    rows=result['marginal_stability']
    assert rows.iloc[0].cross_year and rows.iloc[0].mean_abs_normalized_marginal_change==pytest.approx(.1)
    assert rows.iloc[1].status=='BLOCKED_COMMON_SID' and pd.isna(rows.iloc[1].mean_abs_normalized_marginal_change)
    assert not result['projection_quality'].quote_qualified.any()


@pytest.mark.parametrize('approved,match',[(True,True),(False,True),(True,False)])
def test_approved_engineering_source_repair_custody_not_source_pass(tmp_path,monkeypatch,approved,match):
    run,root,design,native,bundle,calls=synthetic_complete_setup(tmp_path,monkeypatch)
    receipt=dict(approved=approved,reviewed=True,risk_fit_started_before_repair=0,
                 old_code_pins={'consumer':'old'},new_code_pins={'consumer':'new'})
    r.save(root/'R10_R3_PCA_CONSUMER_ENGINEERING_REPAIR.json',receipt)
    risk=dict(actual_producer_consumer_code_pins={'consumer':'new' if match else 'different'})
    f=frame();f=f.loc[f.signal_date.dt.year.eq(2024)].copy();f['mean']=.002
    pub=synthetic_pub(run,f)
    if not approved or not match:
        with pytest.raises(RuntimeError,match='R10_RISK_REPAIR'):e.complete_study(run,design,bundle,native,[pub],risk_result=risk)
        assert not (run/'EXECUTION_STATUS.json').exists()
    else:
        result=e.complete_study(run,design,bundle,native,[pub],risk_result=risk)
        custody=pd.read_parquet(result['tables']['source_custody']['path'])
        assert custody.iloc[0].role=='APPROVED_SAME_SCIENCE_PRE_RISK_FIT_ENGINEERING_REPAIR'
        assert not custody.iloc[0].source_authority_upgraded
        assert result['source_activated'] is False


def test_gaussian_mixture_cannot_promote_unqualified_seed(tmp_path,monkeypatch):
    run,root,design,native,bundle,calls=synthetic_complete_setup(tmp_path,monkeypatch)
    f=frame();f=f.loc[f.signal_date.dt.year.eq(2024)].copy();f['mean']=.002
    pub=synthetic_pub(run,f,family='gaussian_mlp')
    receipt=r.read_json(pub['seed_receipts'][0]);leaf=__import__('pathlib').Path(receipt['publication']['path'])
    body=pd.read_parquet(leaf);body.loc[0,'label_qualified']=False;body.to_parquet(leaf,index=False)
    receipt['publication']['sha256']=r.fit_owner.sha(leaf);r.save(pub['seed_receipts'][0],receipt)
    with pytest.raises(RuntimeError,match='ENGINEERING_RECOVERY_REQUIRED'):e.complete_study(run,design,bundle,native,[pub])
    details=r.read_json(root/run.name/'ENGINEERING_BLOCKERS.json')
    assert 'GAUSSIAN_SEED_QUALIFICATION_IDENTITY' in details['publication_errors'][0]['error']


def test_daily_risk_source_owner_consumer_and_chinese_report(tmp_path,monkeypatch):
    from tests.research.a2.risk.test_mechanism_risk_diagnostics import projection_fixture
    run,root,design,native,bundle,calls=synthetic_complete_setup(tmp_path,monkeypatch)
    items,observations=projection_fixture(representation='R7')
    packet=pd.DataFrame(dict(signal_date=[pd.Timestamp('2024-02-01')],label_mature_date=[pd.Timestamp('2024-02-08')]))
    bundle.native_endpoint_labels={5:packet}
    seen=[]
    def adapter(raw):seen.append(raw);return observations.copy()
    monkeypatch.setattr(e.inputs,'native_risk_observations',adapter)
    f=frame();f=f.loc[f.signal_date.dt.year.eq(2024)].copy();f['mean']=.002
    pub=synthetic_pub(run,f)
    result=e.complete_study(run,design,bundle,native,[pub],risk_result=dict(projections=items,states=[]))
    assert len(seen)==1 and seen[0] is packet
    daily=pd.read_parquet(result['tables']['risk_native_request']['path'])
    annual=pd.read_parquet(result['tables']['risk_native_aggregate']['path'])
    assert daily.status.eq('PASS_EXACT_MATURED_REFERENCE_DIAGNOSTIC_ONLY').all()
    assert annual.iloc[0].nominal_N==3 and annual.iloc[0].predicted_downside_sigma_rms is not None
    assert not daily.account_qualified.any() and not annual.quote_qualified.any()
    report=(root/run.name/'REPORT.md').read_text(encoding='utf-8')
    assert '实际 physical fit 为 0' in report
    assert '5 个已登记 non-ML controls' in report
    assert "'method':" not in report and "'paired_values':" not in report
    assert '| 控制 | 状态 | 合法日期 | 2024 增量 | 2025 增量 |' in report
    assert result['report_generation_new_fit']==0


def test_native_uncertainty_error_evidence_is_retained_without_new_fit(tmp_path,monkeypatch):
    run,root,design,native,bundle,calls=synthetic_complete_setup(tmp_path,monkeypatch)
    pubs=[]
    for year in (2024,2025):
        f=native['MEAN']['INCUMBENT'].copy();f=f.loc[f.signal_date.dt.year.eq(year)].copy();f['mean']=.002
        pubs.append(synthetic_pub(run,f,group='INCUMBENT',family='gaussian_mlp',year=year))
    result=e.complete_study(run,design,bundle,native,pubs)
    paired=pd.read_parquet(result['tables']['native_uncertainty_paired']['path'])
    replace=paired.loc[paired.role.eq('REPLACE_EDGE')]
    assert len(replace)==4 and replace.left_wrong_action_rate.notna().all()
    assert replace.right_missed_positive_advantage_rate.notna().all()
    q=result['questions']['questions'][4]['evidence']
    assert len(q['paired_native_gate_values'])==2 and len(q['paired_replacement_error_values'])==4
    assert result['fit_units_actual']==6 and result['report_generation_new_fit']==0


def test_nullable_relation_nulls_share_identity_without_accepting_nonempty_difference():
    canonical=frame();canonical['incumbent']=np.nan;canonical['entrant']=np.nan
    published=canonical.copy();published['incumbent']=pd.Series([None]*len(published),dtype=object)
    published['entrant']=pd.Series([pd.NA]*len(published),dtype=object)
    result=e.rebind_published_metadata(published,canonical)
    assert result.incumbent.isna().all() and result.entrant.isna().all()
    published.loc[0,'incumbent']='NONEMPTY_ID'
    with pytest.raises(ValueError,match='SECURITY_IDENTITY'):e.rebind_published_metadata(published,canonical)


@pytest.mark.parametrize('field,value',(('family','hgb'),('group','INCUMBENT'),('horizon',5),('year',2025),('capacity','LOW'),('cutoff_exclusive','2024-02-01'),('seed',123)))
def test_gaussian_seed_metadata_lineage_is_explicit(tmp_path,monkeypatch,field,value):
    run,root,design,native,bundle,calls=synthetic_complete_setup(tmp_path,monkeypatch)
    f=frame();f=f.loc[f.signal_date.dt.year.eq(2024)].copy();f['mean']=.002
    pub=synthetic_pub(run,f,family='gaussian_mlp')
    receipt=r.read_json(pub['seed_receipts'][0]);receipt[field]=value;r.save(pub['seed_receipts'][0],receipt)
    with pytest.raises(RuntimeError,match='ENGINEERING_RECOVERY_REQUIRED'):e.complete_study(run,design,bundle,native,[pub])
    details=r.read_json(root/run.name/'ENGINEERING_BLOCKERS.json')
    assert 'GAUSSIAN_SEED_' in details['publication_errors'][0]['error']


def test_failed_quantile_receipt_three_physical_units_not_one_slot(tmp_path,monkeypatch):
    run,root,design,native,bundle,calls=synthetic_complete_setup(tmp_path,monkeypatch)
    slot='SYN_FAILED_QUANTILE_3';tsha='SYN_SCIENTIFIC_TUPLE'
    r.save(run/'models/mechanism'/slot/'fit_receipt.json',dict(slot_id=slot,family='hgb_quantile',
         scientific_tuple_sha256=tsha,status='FAILED',fit_units=3,error='SYNTHETIC_ONLY_NO_REAL_FIT'))
    r.fit_owner._append(run/'FIT_LOG.jsonl',dict(event='FIT_STARTED',model_id=slot,year=2024,
         role='SYNTHETIC_ONLY',reuse_tuple_sha256=tsha,budget_bucket='ACTION_VALUE',fit_units=3))
    result=e.complete_study(run,design,bundle,native,[])
    assert result['failed_scientific_slots']==1 and result['failed_started_physical_units']==3
    assert result['fit_units_actual']==3 and result['prediction_failed_slots']==0
    assert 'failed_started_or_prediction_units' not in result
    report=(root/run.name/'REPORT.md').read_text(encoding='utf-8')
    assert '已失败科学 slot：1；失败启动 physical units：3' in report


def test_complete_caller_consumes_only_native_gross_horizons(tmp_path,monkeypatch):
    run,root,design,native,bundle,calls=synthetic_complete_setup(tmp_path,monkeypatch)
    packets=bundle.frames.gross
    expected=e.nonml_gross_controls({h:packets[h] for h in e.inputs.HORIZONS},None)
    class ForbiddenMean:
        def __getattribute__(self,name):
            raise AssertionError('DERIVED_MEAN_MUST_NOT_ENTER_NATIVE_GROSS_CONTROLS')
    packets['MEAN']=ForbiddenMean()
    r.save(run/'models/mechanism/synthetic_source_block/fit_receipt.json',
           dict(slot_id='synthetic_source_block',status='BLOCKED_INPUT',fit_units=0,
                reason='SYNTHETIC_SCHEDULED_RECEIPT_NO_FIT'))
    # The helper stays strict; production bundle's derived fifth packet belongs
    # to another contract. Execute the real completion caller to test routing.
    with pytest.raises(ValueError,match='ALL_NATIVE_GROSS_HORIZONS_REQUIRED'):
        e.nonml_gross_controls(packets,None)
    result=e.complete_study(run,design,bundle,native,[])
    observed=pd.read_parquet(result['tables']['nonml_gross_controls']['path'])
    pd.testing.assert_frame_equal(observed,expected['rows'])
    assert result['fit_units_actual']==0 and result['report_generation_new_fit']==0
    assert all(any('NONML_GROSS|G0'==k for k in call) for call in calls)
    assert list(packets)==[*e.inputs.HORIZONS,'MEAN']
