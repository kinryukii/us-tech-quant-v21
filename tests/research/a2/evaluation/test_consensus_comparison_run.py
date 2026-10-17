"""Generated383 manifest, disk snapshots and canonical fit protocol; no real readers."""
from dataclasses import asdict, replace
from itertools import product, islice
import copy
import importlib.util
import hashlib
import json
import pickle
from pathlib import Path
from types import SimpleNamespace

import joblib
import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.evaluation import consensus_comparison_run as comparison
from scripts.research.a2.evaluation import consensus_evaluation_run as evaluator
from scripts.research.a2.inference import consensus_joint_policy as joint

NATIVE_EVALUATE = comparison.extension.evaluate_flow


@pytest.fixture
def generated(tmp_path,monkeypatch):
    monkeypatch.setattr(comparison,'assert_safe_output_path',lambda path,**kw:
        comparison.require(Path(path).resolve().is_relative_to(tmp_path.resolve()),'SYNTHETIC_OUTPUT_ROOT_ONLY'))
    def save(path,value):
        path=Path(path)
        comparison.require(path.resolve().is_relative_to(tmp_path.resolve()),'SYNTHETIC_OUTPUT_ROOT_ONLY')
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value,sort_keys=True,default=str),encoding='utf-8')
    monkeypatch.setattr(comparison,'write_json_atomic',save)
    run=tmp_path/'SYNTHETIC_COMPARISON_R12';run.mkdir()
    packs={name:dict(packet_id=name.split('__')[0],fusion_method='equal') for name in ('core5__equal','broad29__equal')}
    risks={name:dict(members=[name],weights=[1.]) for name in
        ('LW','DIAG','HISTVOL','OAS','EWMA','PCA','FA','RD','RM','RT','RU','SINGLE_INDEX','INDUSTRY','NONLINEAR_SHRINKAGE')}
    decisions=list(comparison.extension.catalogue()['decision_methods'])
    rows=[dict(comparison_arm='SYNTHETIC',coordinate_id=f'P{i:03}',forecast_pack=p,risk_combination=r,
        decision_method=d,status='PLANNED_NOT_ATTEMPTED') for i,(r,d,p) in enumerate(islice(product(risks,decisions,packs),383))]
    manifest=run/'COMPARISON_COORDINATES.jsonl'
    manifest.write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf-8')
    account=dict(currency='USD',type='CASH',initial_cash=3000,fractional=True,
        independent_empty_account_per_coordinate=True,continuous_replay_years=[2023,2024,2025],max_positions=20,
        max_single_weight=.1,max_gross=.95,minimum_trade_usd=5,one_way_all_in_bps=10,fixed_per_fill_usd=0,
        settlement_enabled=True,decision_clock='AFTER_SIGNAL_CLOSE_THEN_NEXT_LEGAL_OPEN',same_corporate_action_and_quote_qualification=True)
    scope=dict(schema='CONSENSUS_COMPARISON_RESEARCH_SCOPE_R12',research_id=comparison.RESEARCH_ID,output_run=str(run),
        train_and_development_before='2026-01-01',test2026_read_authorized=False,confirmation_read_authorized=False,
        real_trades_authorized=False,old_account_state_reused=False,account=account,
        budget=dict(prior_fit_units=2063,max_fit_units=10000,no_reset=True,failed_attempts_count=True),
        comparison=dict(forecast_packs=packs,risk_combinations=risks,decision_methods=decisions,
            matrix_coordinates_ref=comparison.ref(manifest),total_planned_coordinates=383))
    comparison.write_json_atomic(run/comparison.SCOPE_FILE,scope)
    freeze=dict(root_scope_ref=comparison.ref(run/comparison.SCOPE_FILE),matrix_coordinates_ref=comparison.ref(manifest),
        research_id=comparison.RESEARCH_ID,output_run=str(run))
    comparison.write_json_atomic(run/comparison.FREEZE_FILE,freeze)
    consumer=run/'SYNTHETIC_CONSUMER_FREEZE.json';comparison.write_json_atomic(consumer,dict(synthetic_only=True,method_matrix_scope_ref=comparison.ref(run/comparison.FREEZE_FILE)))
    consumer_ref=comparison.ref(consumer)
    dates=pd.to_datetime(['2023-01-03','2023-01-04','2024-01-02','2024-01-03','2025-01-02','2025-01-03'])
    returns=pd.DataFrame(np.random.default_rng(4).normal(0,.01,(120,2)),
        index=pd.bdate_range(end='2022-12-30',periods=120),columns=['A','B'])
    returns.attrs['source_id']='UNKNOWN'
    loaded=dict(market=SimpleNamespace(dates=dates),returns=returns)
    values=SimpleNamespace(digest=evaluator.values.digest,_events=lambda p:[],_fit_job=lambda *a,**kw:pytest.fail('unexpected fit'))
    runner=SimpleNamespace(joint=joint,values=values,source_pins=lambda:{},compatible_forecasts=evaluator.compatible_forecasts,
        contract=lambda actual:(run,{},consumer_ref),_matrix_evaluation_source=evaluator.evaluate_flow,
        _matrix_execution_guard=lambda function:function,_carryover_fit_started=lambda token:False)
    publications=[];policies=[];calls=[]
    def published(actual,method,year,reader,*,packet_id):
        assert actual==run and year in (2023,2024,2025)
        publications.append((packet_id,method,year))
        frame=pd.DataFrame([dict(signal_date=d,ticker=a,prediction=.02,value_sigma=.01,prediction_qualified=True)
            for d in dates if d.year==year for a in ('A','B')])
        return frame,dict(method=method,packet_id=packet_id,year=year)
    monkeypatch.setattr(comparison.recovery,'published_fusion_forecasts',published)
    def evaluate(runner,coordinate,*args,binding,make_policy,**kwargs):
        actual,pack,risk,decision,forecasts,past,actual_loaded,fr,pins,cache=args
        assert actual==run and fr==consumer_ref and len(pins)==3 and cache is cache_owner[0]
        receipt_path=run/'evaluation/consensus_account'/('matrix__'+coordinate.identity)/'receipt.json'
        receipt_path.parent.mkdir(parents=True)
        receipt=dict(status='COMPLETE',receipt_path=str(receipt_path),matrix_coordinate=asdict(coordinate),fit_units=0,artifacts={})
        policy=make_policy(forecasts,past,binding.PolicyConfig(risk,decision,120),joint.FeeConfig(),run,receipt,cache,coordinate.identity)
        policies.append(policy);calls.append(coordinate)
        assert policy.matrix_coordinate==asdict(coordinate) and not policy.monthly_state_keys
        comparison.write_json_atomic(receipt_path,receipt)
        return receipt
    cache_owner=[]
    def guard(function):
        def guarded(*args,**kwargs):
            if function.__name__=='initialize':cache_owner.append(args[1])
            return function(*args,**kwargs)
        return guarded
    runner._matrix_execution_guard=guard
    monkeypatch.setattr(comparison.extension,'evaluate_flow',evaluate)
    return SimpleNamespace(run=run,scope=scope,runner=runner,loaded=loaded,freeze=consumer_ref,
        rows=rows,calls=calls,policies=policies,publications=publications,cache_owner=cache_owner,tmp=tmp_path)


def test_exact383_manifest_separate_policies_aliases_qualification_and_three_year_publications(generated):
    g=generated
    result=comparison.run_all(g.run,g.runner,g.loaded,object(),g.freeze,g.scope)
    frozen,planned,_=comparison.plan(g.run,g.scope)
    expected=[r for r in planned if r['exact_alias_of'] is None and not comparison.qualification(
        comparison.extension.Coordinate(*(r[k] for k in ('forecast_pack','risk_combination','decision_method'))),frozen,
        bank_dependencies=None,r2_fit=None,scenarios=None,references=None,rl_factory=None)]
    assert len(g.calls)==len(expected)<383
    assert len({id(p) for p in g.policies})==len(g.policies)
    assert len({id(p.monthly_state_keys) for p in g.policies})==len(g.policies)
    assert len({id(p.risk_cache) for p in g.policies})==1
    assert len(g.publications)==6 and len(set(g.publications))==6
    index=comparison.metadata(g.run/'evaluation/consensus_comparison/status_index.json')
    assert len(index['coordinates'])==383 and result['all_planned_coordinates_resolved'] is True
    assert any(r['status']=='EXACT_ALIAS_REUSED' and r['alias_is_independent_mechanism'] is False for r in index['coordinates'])
    assert any(r['status']=='INPUT_QUALIFICATION_BLOCKED' for r in index['coordinates'])
    assert not (g.run/'FIT_LOG.jsonl').exists()
    calls=len(g.calls)
    comparison.run_all(g.run,g.runner,g.loaded,object(),g.freeze,g.scope)
    assert len(g.calls)==calls and len(g.publications)==6


@pytest.mark.parametrize('kind',['manifest_hash','cash','future','extra_coordinate'])
def test_changed_manifest_account_or_time_boundary_fails_before_any_publication(generated,kind):
    g=generated;scope=copy.deepcopy(g.scope)
    if kind=='manifest_hash':
        path=g.run/'COMPARISON_COORDINATES.jsonl';path.write_text(path.read_text()+'{}\n')
    elif kind=='cash':scope['account']['initial_cash']=10000
    elif kind=='future':scope['test2026_read_authorized']=True
    else:scope['comparison']['total_planned_coordinates']=384
    if kind!='manifest_hash':comparison.write_json_atomic(g.run/comparison.SCOPE_FILE,scope)
    with pytest.raises(ValueError):comparison.run_all(g.run,g.runner,g.loaded,object(),g.freeze,scope)
    assert g.calls==[] and g.publications==[]


def test_disk_risk_cache_snapshot_is_immutable_bounded_small_and_tampering_never_refits(generated):
    g=generated;cache=comparison.DiskRiskCache(g.run/'store',max_resident=2)
    for i in range(2):cache[('state',i)]=np.full(100000,i,dtype=float)
    state=g.run/'cell_state.joblib';joblib.dump(dict(risk_cache=cache,account_units=[0.]),state)
    assert state.stat().st_size<5000
    cache[('state',2)]=np.full(100000,2.,dtype=float)
    assert len(cache._resident)<=2
    old=joblib.load(state)['risk_cache']
    assert isinstance(old,dict) and len(old)==2 and ('state',2) not in old and len(cache)==3
    np.testing.assert_array_equal(old[('state',1)],np.full(100000,1.))
    assert len(old._resident)<=2
    reference=dict.__getitem__(old,('state',1));Path(reference['path']).write_bytes(b'TAMPERED')
    with pytest.raises(ValueError,match='PIN_CHANGED'):old[('state',1)]
    assert not (g.run/'FIT_LOG.jsonl').exists()


def bank_case(g):
    forecasts=pd.DataFrame([dict(signal_date=pd.Timestamp('2023-02-01'),ticker=a,mu=.02,sigma=.01,
        p_up=.7,q10=-.01,q50=.02,q90=.04) for a in ('A','B')]);forecasts.attrs['unit']=joint.UNIT
    old=joint.ConsensusJointPolicy(forecasts,g.loaded['returns']);old._risk(pd.Timestamp('2023-02-01'),('A','B'))
    legacy_key,bundle=next(iter(old.risk_cache.items()));events=[]
    def capture(method,past,*,params,dependencies,event):events.append((method,past,params,dependencies,event));return bundle
    frozen=comparison.extension_scope(g.scope)
    binding=comparison.extension.bind_joint(joint,scope=frozen,
        coordinate=comparison.extension.Coordinate('core5__equal','LW','cost_aware'),bank_fit=capture)
    binding.ConsensusJointPolicy(forecasts,g.loaded['returns'])._risk(pd.Timestamp('2023-02-01'),('A','B'))
    return legacy_key,bundle,events[0],binding,forecasts,events


def test_bank_fit_exact_legacy_bridge_and_failed_checkpoint_keep_state_without_refit(generated):
    g=generated;key,bundle,(method,past,params,dependencies,event),_,_,_=bank_case(g)
    bridges=[];g.runner._carryover_fit_started=lambda token:True
    fit=comparison.bank_adapter(g.runner,g.run,{}, {key:bundle},g.freeze,bridges)
    assert fit(method,past,params=params,dependencies=dependencies,event=event) is bundle
    assert bridges[0]['disposition']=='EXACT_INPUT_DOMAIN_PARAMS_SOURCE_CACHE_BRIDGE'
    failed=replace(bundle,status='FIT_FAILED',covariance=None,failure_reason='SYNTHETIC_OLD_FAILED_ATTEMPT')
    fit=comparison.bank_adapter(g.runner,g.run,{}, {key:failed},g.freeze,[])
    assert fit(method,past,params=params,dependencies=dependencies,event=event).status=='FIT_FAILED'
    fit=comparison.bank_adapter(g.runner,g.run,{}, {},g.freeze,[])
    with pytest.raises(ValueError,match='OLD_FAILED_OR_UNBRIDGED'):
        fit(method,past,params=params,dependencies=dependencies,event=event)


def test_new_bank_fit_uses_canonical_worker_prior_log_and_never_retries_started_token(generated):
    g=generated;_,bundle,(method,past,params,dependencies,event),_,_,_=bank_case(g)
    entries=[];calls=[];receipt=dict(receipt_path=str(g.run/'fit_receipt.json'),fit_units=0)
    g.runner.values._events=lambda path:entries
    def job(*args,**kwargs):
        calls.append((args,kwargs));entries.append(dict(event='FIT_STARTED',fit_units=1,reuse_tuple_sha256=kwargs['tuple_sha']))
        return bundle
    g.runner.values._fit_job=job
    fit=comparison.bank_adapter(g.runner,g.run,receipt,{},g.freeze,[])
    assert fit(method,past,params=params,dependencies=dependencies,event=event) is bundle
    args,kwargs=calls[0]
    assert args[0:2]==('risk','LW') and args[6] is dependencies
    assert kwargs['worker_target'] is comparison.extension.risk_fit_worker
    assert kwargs['prior']==2063 and kwargs['auth']['max_fit_units']==10000 and kwargs['log']==g.run/'FIT_LOG.jsonl'
    with pytest.raises(ValueError,match='MATRIX_FAILED_OR_UNCHECKPOINTED'):
        fit(method,past,params=params,dependencies=dependencies,event=event)
    assert len(calls)==1


def test_changed_full_fit_domain_is_legal_new_tuple_and_budget_exhaustion_is_not_success(generated):
    g=generated;_,bundle,(_,_,_,_,_),binding,forecasts,events=bank_case(g)
    binding.ConsensusJointPolicy(forecasts,g.loaded['returns'])._risk(pd.Timestamp('2023-02-01'),('A','B','OUTSIDE'),
        fit_assets=('A','B','OUTSIDE'))
    method,past,params,dependencies,event=events[-1]
    g.runner._carryover_fit_started=lambda token:True
    calls=[];g.runner.values._fit_job=lambda *a,**kw:(calls.append(kw),bundle)[1]
    fit=comparison.bank_adapter(g.runner,g.run,{}, {},g.freeze,[])
    assert fit(method,past,params=params,dependencies=dependencies,event=event) is bundle and len(calls)==1
    g.runner.values._events=lambda path:[dict(event='FIT_STARTED',fit_units=1)]*7937
    receipt={};fit=comparison.bank_adapter(g.runner,g.run,receipt,{},g.freeze,[])
    with pytest.raises(RuntimeError,match='CUMULATIVE_FIT_BUDGET_EXHAUSTED'):
        fit(method,past,params=params,dependencies=dependencies,event=event)
    assert receipt['budget_exhausted'] is True and len(calls)==1


@pytest.mark.parametrize('risk,decision,reason',[
    ('RD','cost_aware','TYPED_R2'),('SINGLE_INDEX','cost_aware','DEPENDENCIES'),
    ('NONLINEAR_SHRINKAGE','cost_aware','BACKEND'),('LW','mean_es','SCENARIOS'),
    ('LW','tracking_error','REFERENCE'),('LW','rl_ppo','RL_POLICY_FACTORY')])
def test_each_unqualified_provider_explicitly_blocks_without_fallback(generated,risk,decision,reason):
    g=generated
    coordinate=comparison.extension.Coordinate('core5__equal',risk,decision)
    actual=comparison.qualification(coordinate,comparison.extension_scope(g.scope),
        bank_dependencies=None,r2_fit=None,scenarios=None,references=None,rl_factory=None)
    assert reason in actual and g.calls==[] and g.publications==[]


def test_original_E_shareholder_account_writes_disk_cache_snapshot_and_reuses_without_new_fit(generated,monkeypatch):
    from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays
    g=generated
    fixture_path=Path(__file__).with_name('test_consensus_shareholder_account.py')
    spec=importlib.util.spec_from_file_location('_comparison_shareholder_generated_fixture',fixture_path)
    fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    dates=g.loaded['market'].dates
    market=MarketArrays(dates,['A','B'],np.full((6,2),100.),np.full((6,2),100.),
        adv=np.full((6,2),1e7),signal_mask=np.array([True,True,True,True,True,False]))
    loaded=dict(market=market,events=dict(entitlement_events=(),entitlement_security_tickers={},
        entitlement_source_binding=fixture.source_binding((),{})),task_authority=fixture.binding(g.run,()),
        settlement_calendar=dates,usable_a=np.zeros_like(market.quality),
        source_scope_ref={'path':'synthetic://scope','sha256':'c'*64})
    forecasts,_=comparison._publications(g.run,'core5__equal',g.scope['comparison']['forecast_packs']['core5__equal'],object(),g.runner)
    cache=comparison.DiskRiskCache(g.run/'real_E_risk_store',max_resident=2)
    calls=[]
    def fit(method,past,*,params,dependencies,event):
        calls.append((method,event['cutoff']))
        return joint.risk.fit_risk_estimator(method,past,params=params)
    coordinate=comparison.extension.Coordinate('core5__equal','LW','cost_aware')
    binding=comparison.extension.bind_joint(joint,scope=comparison.extension_scope(g.scope),coordinate=coordinate,bank_fit=fit)
    def factory(forecasts,returns,config,fee_config,run,receipt,shared_cache,identity):
        return binding.ConsensusJointPolicy(forecasts,returns,config=config,fee_config=fee_config,shared_risk_cache=shared_cache)
    monkeypatch.setattr(evaluator,'write_json_atomic',comparison.write_json_atomic)
    def save(path,value,kind):
        value.to_parquet(path,index=False) if kind=='frame' else joblib.dump(value,path)
        return comparison.ref(path)
    monkeypatch.setattr(evaluator,'_save_artifact',save)
    result=NATIVE_EVALUATE(g.runner,coordinate,g.run,'core5__equal','LW','cost_aware',forecasts,
        g.loaded['returns'],loaded,g.freeze,[],cache,binding=binding,make_policy=factory)
    assert result['status']=='COMPLETE',result.get('failure')
    state=joblib.load(result['artifacts']['state']['path'])
    assert isinstance(state['risk_cache'],comparison.DiskRiskCache) and len(state['risk_cache'])==len(cache)
    assert len(cache._resident)<=2 and len(result['statistics']['annual_statistics'])==3
    count=len(calls)
    repeated=NATIVE_EVALUATE(g.runner,coordinate,g.run,'core5__equal','LW','cost_aware',forecasts,
        g.loaded['returns'],loaded,g.freeze,[],cache,binding=binding,
        make_policy=lambda *args:pytest.fail('completed exact E receipt must reuse without policy/refit'))
    assert repeated['identity_sha256']==result['identity_sha256'] and len(calls)==count


def test_rl_factory_receives_same_P_R_base_policy_cache_and_per_cell_bounded_bank_fit(generated,monkeypatch):
    g=generated
    # All383 remain frozen. Put the two registered RL directions first so the
    # same orchestration path is exercised without changing the admission gate.
    rows=copy.deepcopy(g.rows)
    for i,method in enumerate(('rl_ppo','rl_reinforce')):
        existing=next(r for r in rows if r['forecast_pack']=='core5__equal' and r['risk_combination']=='LW' and r['decision_method']==method)
        row_index=rows.index(existing);rows[i],rows[row_index]=rows[row_index],rows[i]
    path=g.run/'COMPARISON_COORDINATES.jsonl';path.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
    g.scope['comparison']['matrix_coordinates_ref']=comparison.ref(path)
    comparison.write_json_atomic(g.run/comparison.SCOPE_FILE,g.scope)
    freeze=comparison.metadata(g.run/comparison.FREEZE_FILE)
    freeze.update(root_scope_ref=comparison.ref(g.run/comparison.SCOPE_FILE),matrix_coordinates_ref=comparison.ref(path))
    comparison.write_json_atomic(g.run/comparison.FREEZE_FILE,freeze)
    consumer=Path(g.freeze['path']);comparison.write_json_atomic(consumer,dict(synthetic_only=True,
        method_matrix_scope_ref=comparison.ref(g.run/comparison.FREEZE_FILE)))
    g.freeze=comparison.ref(consumer)
    g.runner.contract=lambda actual:(g.run,{},g.freeze)
    calls=[]
    class FrozenActivity:
        def __init__(self,base):self.base_policy=base
        def __call__(self,di,ctx):return self.base_policy(di,ctx)
    def factory(method,forecasts,past_daily_returns,*,config,fee_config,base_policy,**owner_kwargs):
        assert method==config.allocation_method and base_policy.config.allocation_method=='cost_aware'
        assert base_policy.config.risk_method==config.risk_method=='LW'
        assert base_policy.risk_cache is owner_kwargs['shared_risk_cache'] is g.cache_owner[0]
        # The base's true risk fit calls the same per-cell canonical bounded
        # adapter; an uncheckpointed tuple must never fall back to inline fit.
        calls.append((method,base_policy))
        return FrozenActivity(base_policy)
    # generated's saved consumer ref is captured by its evaluator stub; replace
    # that stub's contract check with the actual newly frozen consumer identity.
    def evaluate(runner,coordinate,*args,binding,make_policy,**kwargs):
        run,pack,risk,decision,forecasts,past,loaded,fr,pins,cache=args
        receipt_path=g.run/'evaluation/consensus_account'/('matrix__'+coordinate.identity)/'receipt.json'
        receipt_path.parent.mkdir(parents=True,exist_ok=True)
        receipt=dict(status='COMPLETE',receipt_path=str(receipt_path),artifacts={})
        make_policy(forecasts,past,binding.PolicyConfig(risk,decision,120),joint.FeeConfig(),g.run,receipt,cache,coordinate.identity)
        comparison.write_json_atomic(receipt_path,receipt)
        return receipt
    monkeypatch.setattr(comparison.extension,'evaluate_flow',evaluate)
    publication_calls=[]
    def publication(run,method,year,reader,*,packet_id):
        publication_calls.append((packet_id,year))
        frame=pd.DataFrame([dict(signal_date=pd.Timestamp(f'{year}-01-03'),ticker=a,prediction=.02,
            value_sigma=.01,prediction_qualified=True) for a in ('A','B')])
        return frame,dict(packet_id=packet_id,method=method,year=year)
    comparison.run_all(g.run,g.runner,g.loaded,object(),g.freeze,g.scope,rl_factory=factory,
        publication_provider=publication)
    assert {method for method,base in calls}=={'rl_ppo','rl_reinforce'}
    assert len(publication_calls)==6 and len(set(publication_calls))==6



@pytest.fixture(scope="module")
def tiny_typed_bundle():
    # The original typed engine receives synthetic input only; no real reader.
    path=Path(__file__).with_name('test_consensus_method_extension.py')
    spec=importlib.util.spec_from_file_location('_cache_semantic_typed_fixture',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    typed,asof=module.source_r2_fixture();events=[]
    hook=comparison.extension.R2FitHook(lambda *args:(typed,asof),durable_reserve=events.append)
    bundle,_=hook('RD',cutoff=asof,assets=typed.assets)
    assert bundle.status=='FITTED' and events
    return bundle


@pytest.mark.parametrize('kind',['state','bundle'])
def test_disk_cache_preserves_original_blob_after_true_typed_state_or_bundle_joblib_roundtrip(generated,tiny_typed_bundle,kind):
    g=generated
    value=tiny_typed_bundle if kind=='bundle' else tiny_typed_bundle.fitted_state['typed_state']
    cache=comparison.DiskRiskCache(g.run/'semantic_cache',max_resident=2);key=('EXACT',kind)
    cache[key]=value;original=copy.deepcopy(dict.__getitem__(cache,key))
    restored=joblib.load(original['path'])
    roundtrip=g.run/'roundtrip.joblib';joblib.dump(restored,roundtrip)
    assert comparison.ref(roundtrip)['sha256']!=original['sha256']  # The serialization counterexample.
    assert comparison.content_hash(restored)==comparison.content_hash(value)
    snapshot=cache.snapshot_ref();blobs=set(cache.root.glob('*.joblib'))
    cache[key]=restored
    assert dict.__getitem__(cache,key)==original and cache.snapshot_ref()==snapshot
    assert set(cache.root.glob('*.joblib'))==blobs and len(cache._resident)<=2
    checkpoint=g.run/'checkpoint.joblib';joblib.dump(cache,checkpoint)
    resumed=joblib.load(checkpoint);resumed[key]=restored
    assert dict.__getitem__(resumed,key)==original and resumed.snapshot_ref()==snapshot
    assert comparison.content_hash(resumed[key])==comparison.content_hash(value)
    assert not (g.run/'FIT_LOG.jsonl').exists()


@pytest.mark.parametrize('kind',['state','bundle'])
@pytest.mark.parametrize('change',['covariance','dtype','source','fit_metadata'])
def test_disk_cache_complete_semantics_reject_covariance_dtype_source_or_fit_metadata_change(generated,tiny_typed_bundle,kind,change):
    g=generated
    original=copy.deepcopy(tiny_typed_bundle if kind=='bundle' else tiny_typed_bundle.fitted_state['typed_state'])
    cache=comparison.DiskRiskCache(g.run/'semantic_reject',max_resident=2);cache['exact']=original
    reference=copy.deepcopy(dict.__getitem__(cache,'exact'));changed=joblib.load(reference['path'])
    if change in ('covariance','dtype'):
        covariance=np.asarray(changed.covariance).copy()
        if change=='covariance':covariance[0,0]+=.0001
        else:covariance=covariance.astype(np.float32)
        if kind=='state':changed=replace(changed,covariance=covariance)
        else:changed.covariance=covariance
    elif change=='source':
        if kind=='state':changed=replace(changed,source_receipt={**changed.source_receipt,'source_sha256':'b'*64})
        else:changed.specification={**changed.specification,'source_id':'CHANGED_PHYSICAL_SOURCE'}
    else:
        if kind=='state':changed=replace(changed,fit_dependency_ids=changed.fit_dependency_ids+('CHANGED_FIT_DEPENDENCY',))
        else:changed.fitted_state={**changed.fitted_state,'changed_fit_metadata':1}
    with pytest.raises(ValueError,match='EXACT_KEY_CONTENT_CHANGED'):cache['exact']=changed
    assert dict.__getitem__(cache,'exact')==reference and comparison.ref(reference['path'])==reference
    assert len(list(cache.root.glob('*.joblib')))==1 and not list(cache.root.glob('pending_*'))
    assert not (g.run/'FIT_LOG.jsonl').exists()


def test_disk_cache_compares_physical_original_even_if_caller_mutates_resident_alias(generated,tiny_typed_bundle):
    g=generated;value=copy.deepcopy(tiny_typed_bundle)
    cache=comparison.DiskRiskCache(g.run/'alias_reject',max_resident=2);cache['exact']=value
    reference=copy.deepcopy(dict.__getitem__(cache,'exact'))
    value.covariance[0,0]+=.0001  # Both caller and old resident point at this object.
    with pytest.raises(ValueError,match='EXACT_KEY_CONTENT_CHANGED'):cache['exact']=value
    assert dict.__getitem__(cache,'exact')==reference
    assert comparison.content_hash(cache['exact'])==comparison.content_hash(tiny_typed_bundle)


def test_disk_cache_same_key_unrepresentable_semantics_fail_closed_without_new_blob(generated):
    g=generated;cache=comparison.DiskRiskCache(g.run/'unknown_semantics',max_resident=2)
    value=SimpleNamespace(opaque_state='not covered by the authoritative normalizer')
    cache['exact']=value;reference=copy.deepcopy(dict.__getitem__(cache,'exact'))
    with pytest.raises(ValueError,match='UNHASHABLE_STATE_INPUT'):cache['exact']=value
    assert dict.__getitem__(cache,'exact')==reference and len(list(cache.root.glob('*.joblib')))==1
@pytest.fixture
def real_storage_matrix_case(monkeypatch):
    """Actual storage owner under a resolver-approved synthetic BACKTEST root."""
    import uuid
    from scripts.common.storage_paths import resolve, assert_safe_output_path
    from scripts.storage import storage_r2a as storage
    from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays
    paths=resolve()
    run=paths.backtest_root/'_synthetic'/'CONSENSUS_COMPARISON_BRIDGE_STORAGE'/uuid.uuid4().hex
    assert_safe_output_path(run,kind='backtest',paths=paths);run.mkdir(parents=True)
    assert comparison.write_json_atomic is storage.write_json_atomic
    assert evaluator.write_json_atomic is storage.write_json_atomic
    writer=storage.write_json_atomic
    packs={f'p{i:03}':dict(packet_id='core5',fusion_method='equal') for i in range(323)}
    rows=[dict(coordinate_id=f'C{i:03}',comparison_arm='SYNTHETIC_STORAGE',forecast_pack=pack,
        risk_combination='LW',decision_method='cost_aware',status='PLANNED_NOT_ATTEMPTED') for i,pack in enumerate(packs)]
    rows.extend(dict(rows[i],coordinate_id=f'A{i:03}',risk_combination='LW_ALIAS') for i in range(60))
    manifest=run/'COMPARISON_COORDINATES.jsonl';manifest.write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf8')
    account=dict(currency='USD',type='CASH',initial_cash=3000,fractional=True,
        independent_empty_account_per_coordinate=True,continuous_replay_years=[2023,2024,2025],max_positions=20,
        max_single_weight=.1,max_gross=.95,minimum_trade_usd=5,one_way_all_in_bps=10,fixed_per_fill_usd=0,
        settlement_enabled=True,decision_clock='AFTER_SIGNAL_CLOSE_THEN_NEXT_LEGAL_OPEN',same_corporate_action_and_quote_qualification=True)
    scope=dict(schema='CONSENSUS_COMPARISON_RESEARCH_SCOPE_R12',research_id=comparison.RESEARCH_ID,output_run=str(run),
        train_and_development_before='2026-01-01',test2026_read_authorized=False,confirmation_read_authorized=False,
        real_trades_authorized=False,old_account_state_reused=False,account=account,
        budget=dict(prior_fit_units=2063,max_fit_units=10000,no_reset=True,failed_attempts_count=True),
        comparison=dict(forecast_packs=packs,risk_combinations={name:dict(members=['LW'],weights=[1.]) for name in ('LW','LW_ALIAS')},
            decision_methods=['cost_aware'],matrix_coordinates_ref=comparison.ref(manifest),total_planned_coordinates=383))
    writer(run/comparison.SCOPE_FILE,scope)
    writer(run/comparison.FREEZE_FILE,dict(root_scope_ref=comparison.ref(run/comparison.SCOPE_FILE),
        matrix_coordinates_ref=comparison.ref(manifest),research_id=comparison.RESEARCH_ID,output_run=str(run)))
    consumer=run/'SYNTHETIC_CONSUMER.json';writer(consumer,dict(synthetic_only=True,method_matrix_scope_ref=comparison.ref(run/comparison.FREEZE_FILE)))
    freeze=comparison.ref(consumer)
    dates=pd.to_datetime(['2023-01-03','2023-01-04','2024-01-02','2024-01-03','2025-01-02','2025-01-03'])
    market=MarketArrays(dates,['A'],np.full((6,1),100.),np.full((6,1),100.),adv=np.full((6,1),1e7),
        signal_mask=np.array([True,True,True,True,True,False]))
    fixture_spec=importlib.util.spec_from_file_location('_bridge_storage_pure_authority',Path(__file__).with_name('test_consensus_shareholder_account.py'))
    helper=importlib.util.module_from_spec(fixture_spec);fixture_spec.loader.exec_module(helper)
    returns=pd.DataFrame(np.zeros((120,1)),index=pd.bdate_range(end='2022-12-30',periods=120),columns=['A'])
    loaded=dict(market=market,returns=returns,settlement_calendar=dates,usable_a=np.ones_like(market.quality,dtype=bool),
        events=dict(entitlement_events=(),entitlement_security_tickers={},entitlement_source_binding=helper.source_binding((),{})),
        task_authority=helper.binding(run,()),source_scope_ref={'path':'synthetic://scope','sha256':'c'*64})
    values=SimpleNamespace(_fit_job=lambda *a,**kw:pytest.fail('synthetic no-forecast account must never fit'),
        digest=evaluator.values.digest,_events=lambda path:[])
    guards=[]
    def runner():
        cache_holder=[]
        def guard(function):
            def guarded(*args,**kwargs):
                assert Path(args[0]).resolve()==run
                cache=args[-1]
                if function.__name__=='initialize':
                    assert not cache and isinstance(cache,comparison.DiskRiskCache)
                    cache_holder.append(cache)
                else:assert cache is cache_holder[0]
                guards.append(function.__name__)
                return function(*args,**kwargs)
            return guarded
        return SimpleNamespace(joint=joint,values=values,source_pins=lambda:{},compatible_forecasts=evaluator.compatible_forecasts,
            contract=lambda actual:(run,{},freeze),_matrix_evaluation_source=evaluator.evaluate_flow,
            _matrix_execution_guard=guard,_carryover_fit_started=lambda token:False)
    def publication(actual,method,year,reader,*,packet_id):
        assert actual==run and year in (2023,2024,2025)
        # Deliberately no matching decision date: original J returns exact
        # NO_FORECAST holds, so real E/cash/storage run with zero model fits.
        frame=pd.DataFrame([dict(signal_date=pd.Timestamp(f'{year}-12-05'),ticker='A',prediction=.01,value_sigma=.02,prediction_qualified=True)])
        return frame,dict(method=method,year=year,packet_id=packet_id)
    native_qualification=comparison.qualification
    monkeypatch.setattr(comparison,'qualification',lambda coordinate,*a,**kw:
        native_qualification(coordinate,*a,**kw) if coordinate.forecast_pack=='p000' else 'SYNTHETIC_OTHER_COORDINATES_NOT_EXECUTED')
    return SimpleNamespace(run=run,scope=scope,freeze=freeze,loaded=loaded,writer=writer,runner=runner,
        publication=publication,guards=guards,bridge_path=run/'evaluation/consensus_comparison/cache_bridges.json')


def test_bridge_envelope_uses_real_storage_writer_at_legal_backtest_root(real_storage_matrix_case):
    g=real_storage_matrix_case
    record=dict(schema=comparison.BRIDGES_SCHEMA,bridges=[dict(synthetic_only=True,disposition='EXACT_METADATA_BRIDGE')])
    g.writer(g.bridge_path,record)
    assert comparison.metadata(g.bridge_path)==record
    assert not g.bridge_path.with_suffix('.json.tmp').exists()
    assert g.bridge_path.resolve().is_relative_to(comparison.resolve().backtest_root)


def test_run_all_reaches_first_real_E_and_persists_bridge_envelope_without_mock_storage(real_storage_matrix_case,monkeypatch):
    g=real_storage_matrix_case;calls=[]
    seed=dict(synthetic_only=True,disposition='EXACT_METADATA_BRIDGE')
    g.writer(g.bridge_path,dict(schema=comparison.BRIDGES_SCHEMA,bridges=[seed]))
    def first_evaluator(runner,coordinate,*args,**kwargs):
        assert coordinate==comparison.extension.Coordinate('p000','LW','cost_aware')
        assert args[0]==g.run and args[5] is g.loaded['returns'] and args[6] is g.loaded
        assert args[7]==g.freeze and callable(kwargs['make_policy'])
        calls.append(coordinate)
        result=NATIVE_EVALUATE(runner,coordinate,*args,**kwargs)
        assert result['status']=='COMPLETE',result.get('failure')
        return result
    monkeypatch.setattr(comparison.extension,'evaluate_flow',first_evaluator)
    result=comparison.run_all(g.run,g.runner(),g.loaded,object(),g.freeze,g.scope,publication_provider=g.publication)
    assert len(calls)==1 and result['actual_account_attempts']==1 and result['all_planned_coordinates_resolved']
    index=comparison.metadata(g.run/'evaluation/consensus_comparison/status_index.json')
    assert index['coordinates'][0]['actual_account_attempted'] is True and index['coordinates'][0]['status']=='COMPLETE'
    assert comparison.metadata(g.bridge_path)==dict(schema=comparison.BRIDGES_SCHEMA,bridges=[seed])
    assert result['exact_cache_bridges']==[seed] and 'evaluate_flow' in g.guards
    assert not (g.run/'FIT_LOG.jsonl').exists() # Synthetic fixture only, not a claim about the actual run.
    repeated=comparison.run_all(g.run,g.runner(),g.loaded,object(),g.freeze,g.scope,publication_provider=g.publication)
    assert len(calls)==1 and repeated['exact_cache_bridges']==[seed]
    assert repeated['coordinates_ref']==result['coordinates_ref']


@pytest.mark.parametrize('bad',[[],dict(schema='WRONG',bridges=[]),dict(schema='CONSENSUS_COMPARISON_CACHE_BRIDGES_R12',bridges={})])
def test_bridge_reader_rejects_untyped_or_changed_envelope_before_evaluation(real_storage_matrix_case,monkeypatch,bad):
    g=real_storage_matrix_case;g.bridge_path.parent.mkdir(parents=True,exist_ok=True)
    # Intentionally malformed synthetic input, not an output through the owner.
    g.bridge_path.write_text(json.dumps(bad),encoding='utf8')
    monkeypatch.setattr(comparison.extension,'evaluate_flow',lambda *a,**kw:pytest.fail('bad bridge envelope must reject before account'))
    with pytest.raises(ValueError,match='EXACT_COMPARISON_CACHE_BRIDGES_SCHEMA_REQUIRED'):
        comparison.run_all(g.run,g.runner(),g.loaded,object(),g.freeze,g.scope,publication_provider=g.publication)
