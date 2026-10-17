"""Synthetic C14 input, maturity, OOF and reservation guards; no real research reads."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import selector_maximal_breadth as m


def frames(date='2023-07-03',n=45):
    d=pd.Timestamp(date);rank=np.arange(1,n+1);ticker=[f'T{x:03}' for x in rank];cusip=[f'{x:09}' for x in rank]
    raw=pd.DataFrame(dict(signal_date=d,ticker=ticker,security_uid=['CUSIP:'+c for c in cusip],U_t_fingerprint='U',score=-rank.astype(float),rank=rank,label_end_date=d+pd.Timedelta(days=30)))
    feat=pd.DataFrame(dict(signal_date=d,ticker=ticker));mem=pd.DataFrame(dict(signal_date=d,ticker=ticker,cusip=cusip))
    for j,f in enumerate(m.BASE32):feat[f]=rank.astype(float)+j
    return raw,feat,mem


def current(date='2023-07-03',n=45):return m.current_frame(*frames(date,n))


def test_current_order_counts_and_no_history():
    assert len(m.CURRENT36)==36 and len(m.feature_order())==216 and len(m.feature_order('DELTA_ONLY'))==72
    assert not any('change' in x or 'previous' in x or 'lag' in x for x in m.feature_order())
    assert tuple(m.CURRENT36[:32])==m.BASE32
    with pytest.raises(ValueError):m.feature_order('SEQUENCE')


def test_full_u_percentile_boundary_and_geometry():
    r=current();g=m.pairs.geometry(r);x=m.pair_features(r,g)
    assert len(r)==45 and len(g)==200 and len(x)==200
    assert r.loc[r.raw_rank.eq(21),'current_raw_percentile'].iat[0]==1-20/44
    assert r.loc[r.raw_rank.eq(20),'raw_score_minus_rank20_score'].iat[0]==0
    assert x['delta__raw_score'].iat[0]==-10


def test_missing_values_flagged_without_row_shrink():
    raw,f,mem=frames();f.loc[20,m.BASE32[0]]=np.nan
    r=m.current_frame(raw,f,mem);g=m.pairs.geometry(r);x=m.pair_features(r,g)
    assert len(x)==200 and np.isfinite(x[m.feature_order()].to_numpy(float)).all()
    assert x.loc[:9,'challenger__'+m.BASE32[0]+'__missing'].eq(1).all()
    assert x.loc[:9,'delta__'+m.BASE32[0]+'__missing'].eq(1).all()
    assert x.loc[:9,'challenger__'+m.BASE32[0]].eq(0).all()


@pytest.mark.parametrize('failure',['identity','missing_feature','duplicate_membership','infinite','tie'])
def test_input_failures_preserve_typed_block(failure):
    raw,f,mem=frames()
    if failure=='identity':raw.loc[0,'security_uid']='CUSIP:OTHER'
    if failure=='missing_feature':f=f.iloc[1:]
    if failure=='duplicate_membership':mem=pd.concat([mem,mem.iloc[:1]])
    if failure=='infinite':f.loc[0,m.BASE32[0]]=np.inf
    if failure=='tie':raw.loc[0,'score']=raw.loc[1,'score'];raw.loc[0,'security_uid'],raw.loc[1,'security_uid']=raw.loc[1,'security_uid'],raw.loc[0,'security_uid'];mem.loc[0,'cusip'],mem.loc[1,'cusip']=mem.loc[1,'cusip'],mem.loc[0,'cusip']
    with pytest.raises(ValueError):m.current_frame(raw,f,mem)


def test_future_append_keeps_earlier_input_identical():
    first=frames();future=frames('2025-01-02')
    base=m.current_frame(*first);whole=m.current_frame(*[pd.concat([a,b],ignore_index=True) for a,b in zip(first,future)])
    pd.testing.assert_frame_equal(base,whole.loc[whole.signal_date.eq(base.signal_date.iat[0])].reset_index(drop=True))
    with pytest.raises(ValueError):m.current_frame(*frames('2026-01-02'))


def test_mature_whole_date_without_partner_selection():
    a=current('2023-07-03');b=current('2023-07-05');r=pd.concat([a,b],ignore_index=True)
    r.loc[r.signal_date.eq('2023-07-03')&r.raw_rank.eq(40),'label_end_date']=pd.NaT
    assert m.mature_dates(r,'2023-01-01','2024-01-01').tolist()==[pd.Timestamp('2023-07-05')]
    r.loc[r.signal_date.eq('2023-07-05')&r.raw_rank.eq(11),'label_end_date']=pd.Timestamp('2024-01-01')
    assert len(m.mature_dates(r,'2023-01-01','2024-01-01'))==0


def records(losses):
    return [dict(capacity=c,fit_cutoff='2023-07-01',validation_end='2024-01-01',status='COMPLETE',dates=2,max_label_end='2023-12-20',sum_date_loss=2*v) for c,v in zip(m.CAPACITIES,losses)]


def test_capacity_exact_tie_and_no_epsilon_arbitrage():
    folds=[('2023-07-01','2024-01-01')]
    assert m.choose_capacity(records([1,1,1]),folds)[0]=='LOW'
    assert m.choose_capacity(records([1,1,1-5e-13]),folds)[0]=='HIGH'
    for key,value in [('max_label_end','2024-01-01'),('dates',0),('validation_end','2025-01-01')]:
        r=records([1,2,3]);r[0][key]=value
        assert m.choose_capacity(r,folds)[0]=='MID'


def test_capacity_two_complete_expected_folds_only():
    r=records([1,2,3]);f=[('2023-07-01','2024-01-01'),('2024-01-01','2024-07-01')]
    assert m.choose_capacity(r,f)[0] is None
    for a in records([1,2,3]):a.update(fit_cutoff='2024-01-01',validation_end='2024-07-01',max_label_end='2024-06-01');r.append(a)
    assert m.choose_capacity(r,f)[0]=='LOW'


@pytest.mark.parametrize('rule,values,expected',[('U1_PROB_GT_0_5',{'prob':np.array([.5,.6])},[False,True]),('U2_Q10_GT0_MATCH_Q50',{'q10':np.array([0.,1.]),'q50':np.array([1.,2.])},[False,True]),('U3_MU_MINUS_SIGMA_GT0_MATCH_MU',{'mu':np.array([1.,2.]),'sigma':np.array([1.,1.])},[False,True])])
def test_uncertainty_rules_are_frozen(rule,values,expected):
    score,eligible=m.decision_values(values,rule);assert eligible.tolist()==expected


def test_decoder_preserves_top10_and_only_top40_boundary():
    r=current();g=m.pairs.geometry(r);weights=np.full(200,-1.);weights[0]=2.
    calls=[];panel,matched=m.decode(r,g,weights,'C14_SYNTH',on_solve=lambda:calls.append(1))
    selected=set(panel.loc[panel['rank'].le(20),'security_uid'])
    assert len(selected)==20 and len(matched)==1 and calls==[1]
    assert set(r.loc[r.raw_rank.le(10),'security_uid']).issubset(selected)
    assert not set(r.loc[r.raw_rank.gt(40),'security_uid'])&selected


def test_ledger_deduplicates_and_never_retries_failed(tmp_path,monkeypatch):
    monkeypatch.setattr(m,'write_json',lambda p,v:Path(p).write_text(json.dumps(v),encoding='utf-8'))
    (tmp_path/'DESIGN_FREEZE.json').write_text('{}')
    dag={'nodes':[{'node_id':'N','kind':'ESTIMATOR'}]};ledger=m.Ledger(tmp_path,dag)
    assert ledger.begin('N',{'cutoff':'2024-01-01'})
    ledger.entered('N')
    with pytest.raises(ValueError):ledger.entered('N')
    ledger.finish('N','FAILED',error='synthetic')
    with pytest.raises(ValueError):ledger.begin('N',{'cutoff':'2024-01-01'})
    assert ledger.value['slots']['N']['entered']==1


def test_label_read_cannot_bypass_formal_gate(tmp_path,monkeypatch):
    seen=[];monkeypatch.setattr(m,'project',lambda *a,**k:seen.append(1))
    with pytest.raises((ValueError,FileNotFoundError)):m.label_pairs(tmp_path,{}, {},'2024-01-01')
    assert seen==[]


def test_same_day_midnight_oof_legal_future_cut_rejected():
    r=current('2024-07-01');g=m.pairs.geometry(r);h=m.table_prediction(g,{'margin':np.zeros(200)},'2024-07-01','MID','LINEAR_SVM')
    y=np.zeros(200);ends=pd.Series(pd.Timestamp('2024-08-01'),index=np.arange(200))
    loader=lambda cutoff:(g,y,np.zeros((200,4)),ends,{})
    assert len(m.calibration_history([h],'2025-01-01',loader))==200
    h['source_cutoff']='2024-07-02'
    with pytest.raises(ValueError):m.calibration_history([h],'2025-01-01',loader)
    h['source_cutoff']='2024-07-01';h['source_kind']='RAW_FALLBACK'
    with pytest.raises(ValueError):m.calibration_history([h],'2025-01-01',loader)


def test_shared_scaler_and_model_dag_no_outer_jan24_duplicate(monkeypatch):
    from scripts.research.a2.training import selector_maximal_breadth_estimators as e
    monkeypatch.setattr(m,'ml_solve_requests',lambda d,q:[])
    d={'role_bindings':[{'paradigm':p} for p in e.PARADIGMS]};q={'outer_prediction_dates':502}
    dag=m.physical_dag(d,q,e.component_specs);nodes=dag['nodes'];ids=[v['node_id'] for v in nodes]
    assert len(ids)==len(set(ids)) and len(ids)<1800
    assert len([v for v in nodes if v['kind']=='SCALER'])==5
    assert len([v for v in nodes if v['kind']=='ESTIMATOR' and v['paradigm']=='RIDGE' and v['cutoff']=='2024-01-01'])==3
    assert all(v['capacity'] in ('SELECTED','MID') for v in nodes if v['kind']=='ESTIMATOR' and v['cutoff']=='2025-01-01')
    assert len([v for v in nodes if v['kind']=='ESTIMATOR' and v['cutoff']=='2025-01-01' and v['capacity']=='MID'])==12


def test_runtime_tuple_calibration_owner_index():
    from types import SimpleNamespace
    parts=list(range(10));parts[8]=SimpleNamespace(Fusion=object)
    predictor,cal=m.runtime_parts(parts)
    assert predictor==5 and cal is parts[8]
    parts[8]=8
    with pytest.raises(ValueError):m.runtime_parts(parts)


@pytest.mark.parametrize('paradigm',m.WARMUP)
def test_native_margin_cannot_substitute_loss_without_oof_platt(paradigm):
    with pytest.raises(ValueError):m.objective_loss(paradigm,{'margin':np.ones(2)},np.ones(2),np.ones((2,4)))


def test_full_mid_fusion_oof_bank_no_member_subset():
    r=current('2023-07-03');g=m.pairs.geometry(r)
    rawvalues={p:('q50' if p=='QUANTILE_HGB' else 'point') for p in m.FUSION_MEMBERS}
    bank={p:[m.table_prediction(g,{field:np.ones(200)},'2023-07-01','MID',p)] for p,field in rawvalues.items()}
    loader=lambda c:(g,np.zeros(200),np.zeros((200,4)),pd.Series(pd.Timestamp('2023-08-01'),index=np.arange(200)),{})
    x=m.pair_features(r,g)[m.feature_order()].to_numpy(float)
    answer=m.fusion_history(bank,'2024-01-01',loader,g,x,r)
    assert answer is not None and answer[-1]['genuine_oof'] and answer[-1]['no_raw_fallback']
    bank['MLP']=[]
    assert m.fusion_history(bank,'2024-01-01',loader,g,x,r) is None


def test_numeric_projection_itself_requires_formal_gate_before_io(monkeypatch):
    reads=[];monkeypatch.setattr(m,'footer',lambda *a,**k:reads.append(1))
    with pytest.raises(ValueError):m.project({'path':'unused','sha256':'unused'},['signal_date','target'],start='2023-01-01',stop='2024-01-01')
    assert reads==[]


class IdentityScaler:
    def transform(self,x):return x


def test_jan25_mid_bank_exact_alias_no_duplicate_fit(tmp_path,monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(m,'assert_safe_output_path',lambda *a,**k:None)
    monkeypatch.setattr(m,'write_json',lambda p,v:Path(p).write_text(json.dumps(v),encoding='utf-8'))
    (tmp_path/'DESIGN_FREEZE.json').write_text('{}')
    component={'seed':20260928,'quantile':None};prefix='MODEL|RIDGE|2025-01-01|'
    nodes=[{'node_id':prefix+c+'|20260928|None','kind':'ESTIMATOR'} for c in ('SELECTED','MID')]
    ledger=m.Ledger(tmp_path,{'nodes':nodes});seen=[]
    def fit(*a,**k):seen.append(1);k['on_fit']({'operation':'synthetic_fit'});return {'synthetic_model':1}
    kernel=SimpleNamespace(component_specs=lambda p:[component],capacity_specs=lambda:{'RIDGE':{'MID':{}}},fit_component=fit,predict_component=lambda model,x:{'point':np.zeros(len(x))},combine_predictions=lambda p,v:v[(20260928,None)])
    g=m.pairs.geometry(current());x=np.zeros((200,216));q={'input_sources':{'hlabels':{'sha256':'synthetic'}}}
    for selected in (True,False):
        out=m.fit_bundle(tmp_path,ledger,kernel,'RIDGE','MID','2025-01-01',g,x,np.zeros(200),np.zeros((200,4)),IdentityScaler(),x,None,q,selected=selected)
        assert out['point'].shape==(200,)
    assert seen==[1]
    assert ledger.value['slots'][prefix+'MID|20260928|None']['entered']==0
    assert ledger.value['slots'][prefix+'MID|20260928|None']['alias_of']==prefix+'SELECTED|20260928|None'


def test_stochastic_meta_dag_requires_three_seeds(monkeypatch):
    from scripts.research.a2.training import selector_maximal_breadth_estimators as e
    monkeypatch.setattr(m,'ml_solve_requests',lambda d,q:[])
    dag=m.physical_dag({'role_bindings':[{'paradigm':p} for p in e.PARADIGMS]},{'outer_prediction_dates':502},e.component_specs)
    for method in m.META_STOCHASTIC:
        for year in (2024,2025):
            rows=[n for n in dag['nodes'] if n['kind']=='META_MODEL' and n.get('method')==method and n.get('year')==year]
            assert [n['seed'] for n in rows]==list(m.META_SEEDS)


def test_meta_seed_ensemble_cannot_pick_seed():
    from types import SimpleNamespace
    parts=[{'kind':'linear','model':SimpleNamespace(predict=lambda mu,context,i=i:np.full(len(mu),i))} for i in (1.,2.,3.)]
    obj={'kind':'seed_ensemble','models':parts,'seeds':list(m.META_SEEDS)}
    assert np.array_equal(m.predict_fusion(obj,np.zeros((2,6)),np.zeros((2,216)),np.zeros((2,5))),np.full(2,2.))
    obj['models']=obj['models'][:-1]
    with pytest.raises(ValueError):m.predict_fusion(obj,np.zeros((2,6)),np.zeros((2,216)),np.zeros((2,5)))


@pytest.mark.parametrize('fault',[None,'uid','full_u','endpoint'])
def test_raw_label_identity_and_endpoint_authority(fault):
    raw=current();labels=raw[[*m.KEYS,'U_t_fingerprint','label_end_date']].rename(columns={'label_end_date':'target_end_date'}).copy()
    if fault=='uid':labels.loc[0,'security_uid']='CUSIP:OTHER'
    if fault=='full_u':labels.loc[0,'U_t_fingerprint']='OTHER_U'
    if fault=='endpoint':labels.loc[0,'target_end_date']+=pd.Timedelta(days=1)
    if fault is None:m.validate_label_identity_clock(labels,raw)
    else:
        with pytest.raises(ValueError):m.validate_label_identity_clock(labels,raw)


def checkpoint_fixture(tmp_path,monkeypatch):
    monkeypatch.setattr(m,'assert_safe_output_path',lambda *a,**k:None)
    monkeypatch.setattr(m,'write_json',lambda p,v:Path(p).write_text(json.dumps(v),encoding='utf-8'))
    (tmp_path/'DESIGN_FREEZE.json').write_text('{}')
    raw=current();g=m.pairs.geometry(raw);score=np.full(200,-1.);score[0]=np.nextafter(2.,3.);eligible=score>0
    return raw,g,score,eligible


def test_checkpoint_decoder_resume_reuses_exact_result_no_second_solve(tmp_path,monkeypatch):
    raw,g,score,eligible=checkpoint_fixture(tmp_path,monkeypatch)
    panel,matched=m.checkpoint_decode(tmp_path,'S',raw,g,score,'C14_SYNTH',eligible)
    assert len(m.solve_state(tmp_path)['requests'])==1
    assert m.solve_state(tmp_path)['requests']['S']['status']=='COMPLETE'
    m.SOLVES.pop(str(tmp_path))
    monkeypatch.setattr(m,'decode',lambda *a,**k:pytest.fail('Must not solve a completed request twice'))
    resumed,chosen=m.checkpoint_decode(tmp_path,'S',raw,g,score,'C14_SYNTH',eligible)
    pd.testing.assert_frame_equal(panel,resumed)
    pd.testing.assert_frame_equal(matched,chosen,check_dtype=False)
    assert chosen.predicted_edge.iat[0]==np.nextafter(2.,3.)
    assert len(m.solve_state(tmp_path)['requests'])==1


def test_checkpoint_input_change_rejected(tmp_path,monkeypatch):
    raw,g,score,eligible=checkpoint_fixture(tmp_path,monkeypatch)
    m.checkpoint_decode(tmp_path,'S',raw,g,score,'C14_SYNTH',eligible)
    score[0]+=1
    with pytest.raises(ValueError,match='IDENTITY_CHANGED'):m.checkpoint_decode(tmp_path,'S',raw,g,score,'C14_SYNTH',eligible)


def test_charged_incomplete_decoder_never_retried_independent_token_works(tmp_path,monkeypatch):
    raw,g,score,eligible=checkpoint_fixture(tmp_path,monkeypatch)
    m.solve_callback(tmp_path,'FAILED')
    with pytest.raises(ValueError,match='BLOCKED_CHARGED'):m.checkpoint_decode(tmp_path,'FAILED',raw,g,score,'C14_SYNTH',eligible)
    panel,chosen=m.checkpoint_decode(tmp_path,'OTHER',raw,g,score,'C14_SYNTH',eligible)
    assert len(chosen)==1 and len(panel)==45
    assert len(m.solve_state(tmp_path)['requests'])==2
    assert m.solve_state(tmp_path)['requests']['FAILED']['charged']==1
