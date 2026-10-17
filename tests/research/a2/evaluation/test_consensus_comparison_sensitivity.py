"""Synthetic-only child fee admission and original-owner delegation proofs."""
import copy
import json
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from types import FunctionType, SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.evaluation import consensus_comparison_sensitivity as s
from scripts.research.a2.inference import consensus_joint_policy as joint


def put(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,default=lambda v:v.tolist() if hasattr(v,'tolist') else str(v)),encoding='utf-8');return s.ref(path)


def matrix_scope():
    return dict(schema=s.extension.SCHEMA,research_id='SYNTHETIC_FEE',forecast_packs=['pack'],
        risk_combinations={'LW':dict(members=['LW'],weights=[1.])},decision_methods=['cost_aware','rl_ppo'],
        selection_boundary_exclusive='2026-01-01',initial_cash=3000,prior_fit_units=2063,max_fit_units=10000,
        lookback_sessions=120,controls=list(s.extension.CONTROLS),fee_config=asdict(s.cash.FeeConfig()))


def report_fixture(root,neutral_alias=False):
    coordinates=[]
    for i in range(383):
        coordinates.append(dict(coordinate_id='id'+str(i),forecast_pack='pack'+str(i) if i<4 else 'pack',risk_combination='LW',
            decision_method='cost_aware' if i<4 else 'unused'+str(i),qualified=i<4,
            exact_alias_of='id1' if i==3 and neutral_alias else None,receipt_ref=put(root/('base'+str(i)+'.json'),{'synthetic':True}) if i<4 else {'path':'synthetic://unqualified','sha256':'0'*64}))
    report=dict(schema=s.acceptance.SCHEMA,all_planned_coordinates_terminal=True,planned_labels=383,
        coordinates=coordinates,ranking=['id0','id1','id2'],sensitivity_plan=[])
    bases=['id0','id1','id2']+([] if neutral_alias else ['id3'])
    for base in bases:
        for condition in s.acceptance.CONDITIONS:
            report['sensitivity_plan'].append(dict(base_coordinate_id=base,fee_condition=copy.deepcopy(condition),
                initial_cash=3000,empty_independent_account=True,no_retuning=True,executed=False,
                execution_authorized_by_this_report=False,status='PLANNED_NOT_ATTEMPTED',base_owner_receipt_ref=coordinates[int(base[2:])]['receipt_ref']))
    scope={'comparison':{'neutral_coordinate':['pack3','LW','cost_aware']}}
    return report,scope


@pytest.mark.parametrize('alias,expected',[(False,12),(True,9)])
def test_plan_is_exact_top_three_and_certified_neutral_deduplicated(tmp_path,alias,expected):
    report,scope=report_fixture(tmp_path,alias)
    plan,_=s._plan(report,scope)
    assert len(plan)==expected
    bad=copy.deepcopy(report);bad['sensitivity_plan'].append(copy.deepcopy(plan[0]))
    with pytest.raises(ValueError,match='EXACT_TOP3'):s._plan(bad,scope)


@pytest.mark.parametrize('change',[lambda r:r['ranking'].append('id4'),
    lambda r:r['sensitivity_plan'][0].update(executed=True),
    lambda r:r['sensitivity_plan'][0].update(execution_authorized_by_this_report=True),
    lambda r:r['sensitivity_plan'][0].update(initial_cash=10000),
    lambda r:r['sensitivity_plan'][0]['fee_condition'].update(one_way_all_in_bps=7)])
def test_plan_cannot_expand_qualification_or_recipe(tmp_path,change):
    report,scope=report_fixture(tmp_path);change(report)
    with pytest.raises(ValueError):s._plan(report,scope)


def admission(tmp_path,monkeypatch):
    run=tmp_path/'run';run.mkdir();report,scope=report_fixture(run/'parents')
    scope['account']=dict(currency='USD',type='CASH',initial_cash=3000,fractional=True,independent_empty_account_per_coordinate=True,
        continuous_replay_years=[2023,2024,2025],max_positions=20,max_single_weight=.1,max_gross=.95,minimum_trade_usd=5,
        one_way_all_in_bps=10,fixed_per_fill_usd=0,settlement_enabled=True,decision_clock='AFTER_SIGNAL_CLOSE_THEN_NEXT_LEGAL_OPEN',same_corporate_action_and_quote_qualification=True)
    scope['budget']=dict(prior_fit_units=2063,max_fit_units=10000,no_reset=True,failed_attempts_count=True)
    scope['comparison'].update(forecast_packs={'pack'+str(i):{} for i in range(4)},risk_combinations={'LW':dict(members=['LW'],weights=[1.])},decision_methods=['cost_aware'])
    scope['sensitivities']=dict(conditions=copy.deepcopy(s.acceptance.CONDITIONS),maximum_extra_accounts=12,no_retuning=True,all_accounts_restarted_empty=True)
    master=put(run/s.comparison.SCOPE_FILE,scope);monkeypatch.setattr(s,'MASTER_SHA',master['sha256'])
    calendar_source=put(run/'calendar_source.json',{'synthetic':True})
    bank_source=put(run/'settlement_source.json',{'synthetic':True})
    reader_scope=put(run/'reader_scope.json',dict(calendar_ref=calendar_source,settlement_calendar_ref=bank_source))
    freeze=put(run/'freeze.json',{'reader_scope_ref':reader_scope});matrix=put(run/s.comparison.FREEZE_FILE,{'synthetic':True})
    input_ref=put(run/'inputs.json',{'synthetic':True});source_ref=put(run/'source.json',{'synthetic':True})
    managed=put(run/'run_config.json',dict(strategy_id='SYNTHETIC_STRATEGY',run_id='SYNTHETIC_MANAGED_RUN',
        dates=dict(start='2023-01-01',end_exclusive='2026-01-01'),broker_action_allowed=False))
    config=dict(schema='SYNTHETIC_PARENT_ACCOUNT_EXECUTION_CONFIG',own_run=str(run),managed_run_config_ref=managed,
        comparison_scope_ref=master,method_matrix_scope_ref=matrix,comparison_input_freeze_ref=input_ref)
    config_ref=put(tmp_path/'parent_account_execution.json',config)
    index=put(run/'parent_index.json',{'synthetic':True})
    report.update(acceptance_source_ref=s.code_refs()['acceptance'],master_scope_ref=master,matrix_scope_ref=matrix,status_index_ref=index,
        read_scope=dict(own_run=str(run),test2026_read=False,confirmation_read=False))
    dates=pd.bdate_range('2023-01-02','2025-12-31');bank_dates=dates.delete(130)
    calendar_ref=put(run/'COMPARISON_QUALIFIED_ACCOUNT_CALENDAR.json',dict(
        schema='CONSENSUS_COMPARISON_ACCOUNT_CALENDAR_R12',master_scope_ref=master,consumer_freeze_ref=freeze,
        full_account_calendar=True,market_values_exported=False,source='ACTUAL_C_QUALIFIED_LOADED_ARRAYS_METADATA_ONLY',
        account_sessions=[str(d.date()) for d in dates],settlement_sessions=[str(d.date()) for d in bank_dates],
        calendar_source_ref=calendar_source,settlement_calendar_source_ref=bank_source))
    for row in report['coordinates']:row['calendar_ref']=calendar_ref
    acceptance_ref=put(run/'acceptance.json',report)
    child=s.child_scope_template(run);child.update(status=s.GATE,master_scope_ref=master,fee_authorized_ref=master,
        acceptance_ref=acceptance_ref,parent_freeze_ref=freeze,account_calendar_ref=calendar_ref,matrix_scope_ref=matrix,config_ref=config_ref,source_scope_ref=source_ref,
        input_freeze_ref=input_ref,risk_cache_snapshot_ref=put(run/'snapshot.json',{'synthetic':True}),forecast_pins_ref=put(run/'forecast_pins.json',{}))
    child_ref=put(run/'child.json',child)
    loaded=dict(market=SimpleNamespace(dates=dates),settlement_calendar=bank_dates,returns=pd.DataFrame({'A':np.full(len(dates),.01)},index=dates),source_scope_ref=source_ref)
    runner=SimpleNamespace(contract=lambda _: (run,{},freeze),_matrix_evaluation_source=lambda:None,_matrix_execution_guard=lambda x:x)
    return run,runner,loaded,freeze,scope,config,acceptance_ref,child_ref


def test_all_metadata_admission_happens_before_provider_or_payload(tmp_path,monkeypatch):
    args=admission(tmp_path,monkeypatch);child,plan,_=s._admit(*args[:3],args[3],args[4],args[5],args[6],args[7])
    assert len(plan)==12 and child['rl_refit'] is False
    calls=[];monkeypatch.setattr(s.runtime,'prepared_publication_provider',lambda *a:calls.append('payload'))
    value=json.loads(Path(args[-1]['path']).read_text());value['rl_refit']=True
    bad=put(Path(args[-1]['path']),value)
    with pytest.raises(ValueError,match='REFIT_OR_SELECTION'):
        s.replay_fee_plan(args[0],args[1],args[2],None,*args[3:7],bad)
    assert calls==[]


@pytest.mark.parametrize('drift',['forecast_pins_ref','risk_cache_snapshot_ref','source_scope_ref','input_freeze_ref','matrix_scope_ref','parent_freeze_ref'])
def test_each_admitted_ref_drift_rejects_before_numeric(tmp_path,monkeypatch,drift):
    args=admission(tmp_path,monkeypatch)
    child=json.loads(Path(args[-1]['path']).read_text());Path(child[drift]['path']).write_text('{"drift":true}',encoding='utf-8')
    calls=[];monkeypatch.setattr(s.runtime,'prepared_publication_provider',lambda *a:calls.append('payload'))
    with pytest.raises(ValueError):s.replay_fee_plan(args[0],args[1],args[2],None,*args[3:])
    assert calls==[]


@pytest.mark.parametrize('diagnostic',s.FEES)
def test_fee_projection_preserves_original_policy_and_risk_owner(diagnostic):
    scope=matrix_scope();coordinate=s.extension.Coordinate('pack','LW','cost_aware');calls=[]
    def fit(method,past,*,params,dependencies,event):
        calls.append((method,copy.deepcopy(params),copy.deepcopy(event)))
        return joint.risk.fit_risk_estimator(method,past,params=params)
    binding=s.fee_binding(joint,scope,coordinate,diagnostic,{'path':'synthetic','sha256':'a'*64},bank_fit=fit)
    date=pd.Timestamp('2025-07-01');names=tuple('ABCDEF')
    forecast=pd.DataFrame([dict(signal_date=date,ticker=n,mu=.02,sigma=.01,p_up=.7,q10=-.01,q50=.02,q90=.04) for n in names]);forecast.attrs['unit']=joint.UNIT
    past=pd.DataFrame(np.random.default_rng(8).normal(0,.01,(140,6)),index=pd.bdate_range(end=date-pd.Timedelta(days=1),periods=140),columns=names);past.attrs['source_id']='SYNTHETIC'
    fee=s.cash.FeeConfig(one_way_all_in_bps=diagnostic['one_way_all_in_bps'],fixed_per_fill_usd=diagnostic['fixed_per_fill_usd'])
    cache={};first=binding.ConsensusJointPolicy(forecast,past,fee_config=fee,shared_risk_cache=cache)
    first._risk(date,names,fit_assets=names)
    second=binding.ConsensusJointPolicy(forecast,past,fee_config=fee,shared_risk_cache=cache);second._risk(date,names,fit_assets=names)
    assert len(calls)==1 and first.fee_config==fee and first.config.lookback_sessions==120
    changed=binding.ConsensusJointPolicy(forecast,past,fee_config=fee,shared_risk_cache=cache);changed._risk(date,names,fit_assets=names[:-1])
    assert len(calls)==2 and calls[0][1]['fit_cutoff']==date
    with pytest.raises(ValueError,match='ORIGINAL_ACCOUNT_FEES'):s.extension.validate_scope(binding.matrix_scope)
    with pytest.raises(ValueError,match='MATRIX_FEE_CONFIG_CHANGED'):binding.ConsensusJointPolicy(forecast,past)


def test_original_e_and_c_guard_reach_same_account_owner_with_child_fee(tmp_path):
    seen=[];coordinate=s.extension.Coordinate('pack','LW','cost_aware');diagnostic=s.FEES[2]
    def owner(*a,**kw):
        seen.append(('account',kw['fee_config']));raise s.evaluator.NotTestable('SYNTHETIC_STOP_AT_ORIGINAL_OWNER')
    original=s.evaluator.evaluate_flow;ns={**original.__globals__,'shareholder':SimpleNamespace(run_shareholder_cash_account=owner),
        'write_json_atomic':lambda p,v:put(p,v),'_reuse_receipt':lambda *a:None,'_save_artifact':lambda *a:{'path':'synthetic','sha256':'b'*64}}
    source=FunctionType(original.__code__,ns,argdefs=original.__defaults__);source.__kwdefaults__=original.__kwdefaults__
    def guard(fn):
        def invoke(*a,**kw):seen.append('C');return fn(*a,**kw)
        return invoke
    runner=SimpleNamespace(_matrix_evaluation_source=source,_matrix_execution_guard=guard)
    binding=s.fee_binding(joint,matrix_scope(),coordinate,diagnostic,{'path':'synthetic','sha256':'c'*64},bank_fit=lambda *a,**kw:None)
    def policy(forecasts,returns,config,fee,run,receipt,cache,identity):
        return SimpleNamespace(fee_config=fee,diagnostics=[],risk_cache=cache)
    frame=pd.DataFrame({'signal_date':pd.to_datetime(['2025-07-01']),'ticker':['A'],'mu':[.01]})
    loaded=dict(source_scope_ref={'path':'synthetic','sha256':'d'*64},events={},market=SimpleNamespace(),task_authority={},settlement_calendar=[],usable_a=None)
    result=s.fee_evaluate(runner,coordinate,tmp_path,'pack','LW','cost_aware',frame,pd.DataFrame({'A':[.01]},index=pd.to_datetime(['2025-06-30'])),loaded,{},[],{},
        binding=binding,diagnostic=diagnostic,child_scope_ref={},make_policy=policy,on_account_entry=lambda:seen.append('entered'))
    assert seen==['C','entered',('account',s.cash.FeeConfig(fixed_per_fill_usd=.5))]
    assert result['status']=='NOT_TESTABLE' and result['diagnostic_only'] is True
    assert result['flow_id']=='fee__'+coordinate.identity+'__ticket50c'


def rl_fixture(tmp_path,monkeypatch):
    monkeypatch.setattr(s.runtime,'rl_fit_identity',lambda *a:'synthetic-id')
    source=put(tmp_path/'source.json',{});schedule=put(tmp_path/'schedule.json',{})
    config=dict(rl_source_binding_ref=source,rl_causal_schedule_ref=schedule)
    contract=dict(source_qualified=True,outer_development_rewards_used=False,training_inputs_ref=source,causal_schedule_ref=schedule,training_reward_years=[2022],reset_segments=[{'segment_id':'2022'}])
    recipe=copy.deepcopy(s.rl.auxiliary.RECIPE);recipe['reward_years']=[2022]
    fit=dict(status='FITTED_ACCOUNT_POLICY',recipe=recipe,training_reward_years=[2022],source_contract=contract,updates=[{'synthetic_numeric_loss':'DO_NOT_PROJECT'}])
    folder=tmp_path/'models/consensus_comparison_runtime/rl/synthetic-id';model_ref=put(folder/'policy.joblib',{'not_a_real_model':True})
    receipt=dict(status='FITTED',identity='synthetic-id',coordinate=['pack','LW','rl_ppo'],source_ref=source,schedule_ref=schedule,training_reward_years=[2022],outer_rewards_used=False,model_ref=model_ref,fit_receipt=fit)
    receipt_ref=put(folder/'receipt.json',receipt)
    child=dict(input_freeze_ref={},rl_models={'id0':dict(receipt_ref=receipt_ref,model_ref=model_ref)})
    fitted=s.rl.auxiliary.RLFit('ppo',contract,{},fit)
    return config,child,receipt,fitted


@pytest.mark.parametrize('field',['training_inputs_ref','causal_schedule_ref','training_reward_years','reset_segments'])
def test_rl_contract_drift_rejected_before_whitelisted_payload_decode(tmp_path,monkeypatch,field):
    config,child,receipt,_=rl_fixture(tmp_path,monkeypatch);calls=[]
    receipt['fit_receipt']['source_contract'][field]=[] if field in ('training_reward_years','reset_segments') else {}
    child['rl_models']['id0']['receipt_ref']=put(child['rl_models']['id0']['receipt_ref']['path'],receipt)
    monkeypatch.setattr(s.runtime,'load_checkpoint',lambda *a:calls.append('decode'))
    with pytest.raises(ValueError,match='ACTUAL_TRAINING_CONTRACT'):s._frozen_rl(tmp_path,'id0',s.extension.Coordinate('pack','LW','rl_ppo'),child,config,{})
    assert calls==[]


def test_rl_missing_whitelist_has_no_refit_fallback_and_valid_frozen_model_only_decodes_once(tmp_path,monkeypatch):
    config,child,receipt,fitted=rl_fixture(tmp_path,monkeypatch);calls=[]
    monkeypatch.setattr(s.runtime,'load_checkpoint',lambda *a:(calls.append(a) or fitted))
    with pytest.raises(ValueError,match='MODEL_MISSING'):s._frozen_rl(tmp_path,'id9',s.extension.Coordinate('pack','LW','rl_ppo'),child,config,{})
    assert calls==[]
    assert s._frozen_rl(tmp_path,'id0',s.extension.Coordinate('pack','LW','rl_ppo'),child,config,{}) is fitted
    assert len(calls)==1


def test_child_plan_routes_budget_identity_and_cache_guard_before_restore(tmp_path,monkeypatch):
    run=tmp_path/'run';run.mkdir();report,scope=report_fixture(tmp_path/'parents');scope['comparison']['forecast_packs']={'pack'+str(i):{} for i in range(4)}
    child=dict(risk_cache_snapshot_ref=put(run/'snapshot.json',dict(schema='CONSENSUS_EXACT_RISK_CACHE_SNAPSHOT_R12',root=str(run/'evaluation/consensus_comparison/risk_store'),max_resident=2)),
        matrix_scope_ref=put(run/'matrix.json',{}),forecast_pins_ref=put(run/'forecast.json',{'pack'+str(i):[{'year':y} for y in [2023,2024,2025]] for i in range(4)}),rl_models={})
    plan,rows=s._plan(report,scope);child_ref=put(run/'child.json',child);trace=[]
    monkeypatch.setattr(s,'write_json_atomic',lambda p,v:put(p,v))
    monkeypatch.setattr(s,'_admit',lambda *a:(child,plan,rows));monkeypatch.setattr(s.comparison,'extension_scope',lambda *a:matrix_scope())
    monkeypatch.setattr(s,'assert_safe_output_path',lambda *a,**kw:None)
    @contextmanager
    def lock(run):trace.append('lock');yield;trace.append('unlock')
    monkeypatch.setattr(s.runtime.predictors,'fit_lock',lock)
    monkeypatch.setattr(s.runtime,'prepared_publication_provider',lambda *a:trace.append('publisher'))
    class Cache(dict):
        def __init__(self,*a,**kw):super().__init__()
        def snapshot_ref(self):return put(run/'cache.json',{})
    monkeypatch.setattr(s.comparison,'DiskRiskCache',Cache)
    monkeypatch.setattr(s.comparison,'_restore_risk_cache',lambda *a:trace.append('restore') or {})
    monkeypatch.setattr(s,'_setup',lambda *a:(None,None,None,None))
    monkeypatch.setattr(s.comparison,'_publications',lambda *a:(pd.DataFrame(),[{'year':y} for y in [2023,2024,2025]]))
    def budget(runner,actual,receipt,cache,authority,bridges):
        assert authority==child['matrix_scope_ref'];trace.append('budget')
        return lambda *a,**kw:'SYNTHETIC_RISK_RESULT'
    monkeypatch.setattr(s.comparison,'bank_adapter',budget)
    def binding(base,frozen,coordinate,diagnostic,authority,**kw):
        class Policy:
            def __init__(self,*a,**kwargs):
                trace.append('fresh_policy')
                assert kw['bank_fit']('LW',pd.DataFrame(),params={},dependencies={},event={})=='SYNTHETIC_RISK_RESULT'
        return SimpleNamespace(ConsensusJointPolicy=Policy,matrix_scope=s._fee_scope(frozen,diagnostic,authority))
    monkeypatch.setattr(s,'fee_binding',binding)
    def evaluate(runner,coordinate,*args,binding,diagnostic,child_scope_ref,make_policy,on_account_entry):
        path=run/'evaluation/consensus_account'/('fee__'+coordinate.identity+'__'+diagnostic['tag'])/'receipt.json'
        receipt=dict(status='COMPLETE',receipt_path=str(path),diagnostic_only=True,fee_config=asdict(s.cash.FeeConfig(one_way_all_in_bps=diagnostic['one_way_all_in_bps'],fixed_per_fill_usd=diagnostic['fixed_per_fill_usd'])),
            matrix_coordinate=asdict(coordinate),matrix_scope_identity=s.extension._digest(binding.matrix_scope),freeze_ref={})
        make_policy(None,None,None,None,run,receipt,args[-1],None);on_account_entry();put(path,receipt);return receipt
    monkeypatch.setattr(s,'fee_evaluate',evaluate)
    def guard(fn):
        def call(run,cache):assert not cache;trace.append('C_empty');return fn(run,cache)
        return call
    runner=SimpleNamespace(joint=joint,_matrix_execution_guard=guard)
    result=s.replay_fee_plan(run,runner,{'returns':pd.DataFrame()},None,{},scope,{}, {},child_ref)
    assert trace[:5]==['publisher','lock','C_empty','restore','fresh_policy']
    assert trace.count('budget')==12 and trace.count('fresh_policy')==12 and trace[-1]=='unlock'
    assert result['actual_account_attempts']==12 and result['execution_complete'] is True and result['qualified'] is False
    assert result['rl_refits']==result['predictor_or_fusion_refits']==0


@pytest.mark.parametrize('field',['fee_child_scope_ref','parent_base_receipt_ref','matrix_scope_identity','freeze_ref'])
def test_old_receipt_cannot_claim_current_child_identity(tmp_path,field):
    coordinate=s.extension.Coordinate('pack','LW','cost_aware');diagnostic=s.FEES[0]
    child={'path':'synthetic://child','sha256':'a'*64};parent={'path':'synthetic://parent','sha256':'b'*64};freeze={}
    expected=s._fee_scope(matrix_scope(),diagnostic,child)
    path=tmp_path/'evaluation/consensus_account'/('fee__'+coordinate.identity+'__cost5')/'receipt.json'
    receipt=dict(receipt_path=str(path),fee_config=expected['fee_config'],diagnostic_only=True,fee_child_scope_ref=child,
        parent_base_receipt_ref=parent,freeze_ref=freeze,matrix_coordinate=asdict(coordinate),matrix_scope_identity=s.extension._digest(expected))
    assert s._check_receipt(receipt,tmp_path,coordinate,diagnostic,expected,child,parent,freeze)==path
    receipt[field]='wrong'
    with pytest.raises(ValueError,match='RECEIPT_IDENTITY'):s._check_receipt(receipt,tmp_path,coordinate,diagnostic,expected,child,parent,freeze)


def test_child_fee_qualification_reuses_original_owner_audit_and_ledger_checks(tmp_path,monkeypatch):
    import importlib.util
    import joblib
    from scripts.research.a2.evaluation import consensus_shareholder_account as shareholder
    from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays,TargetDecision
    args=admission(tmp_path,monkeypatch);run,_,loaded,freeze,scope,config,acceptance_ref,child_ref=args
    report=s._acceptance(acceptance_ref);base=report['coordinates'][0]
    coordinate=s.extension.Coordinate(*(base[k] for k in ('forecast_pack','risk_combination','decision_method')))
    diagnostic=s.FEES[2];fee=s.cash.FeeConfig(fixed_per_fill_usd=.5)
    frozen=s.comparison.extension_scope(scope)
    expected=s._fee_scope(frozen,diagnostic,child_ref)
    flow='fee__'+coordinate.identity+'__ticket50c';root=run/'evaluation/consensus_account'/flow;root.mkdir(parents=True)
    helper_path=Path(__file__).with_name('test_consensus_shareholder_account.py')
    spec=importlib.util.spec_from_file_location('_fee_owner_fixture',helper_path);helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    dates=pd.DatetimeIndex(loaded['market'].dates);prices=np.linspace(100,125,len(dates))[:,None]
    market=MarketArrays(dates,['S'],prices.copy(),prices.copy(),adv=np.full(prices.shape,1e9),signal_mask=np.arange(len(dates))<len(dates)-1)
    def policy(di,ctx):
        mask=np.full_like(ctx.decision_mask,di in (0,len(dates)-4),dtype=bool)
        return TargetDecision(np.full_like(ctx.current_units,.05 if di==0 else 0.),mask,'synthetic fee audit')
    (run/'synthetic_authority').mkdir()
    replay=shareholder.run_shareholder_cash_account(market,[flow],policy,task_authority=helper.binding(run/'synthetic_authority',()),
        settlement_calendar=loaded['settlement_calendar'],fee_config=fee,entitlement_events=(),entitlement_security_tickers={},entitlement_source_binding=helper.source_binding((),{}))
    for module in (s.comparison,s.acceptance):
        monkeypatch.setattr(module,'assert_safe_output_path',lambda path,**kw:None)
    monkeypatch.setattr(s.comparison,'write_json_atomic',lambda p,v:put(p,v))
    cache=s.comparison.DiskRiskCache(run/'evaluation/consensus_comparison/risk_store')
    artifacts={}
    for name in s.acceptance.LEDGERS:
        if name=='state':continue
        frame=pd.DataFrame([{'json':json.dumps({'status':'OK'})}]) if name=='diagnostics' else getattr(replay,name)
        file=root/(name+'.parquet');frame.to_parquet(file,index=False);artifacts[name]=s.ref(file)
    file=root/'state.joblib';joblib.dump(dict(risk_cache=cache,metadata=replay.metadata,audit=replay.audit,final_state=replay.final_state,freeze_ref=freeze),file);artifacts['state']=s.ref(file)
    receipt=dict(status='COMPLETE',flow_id=flow,matrix_coordinate=asdict(coordinate),matrix_scope_identity=s.extension._digest(expected),receipt_path=str(root/'receipt.json'),
        freeze_ref=freeze,artifacts=artifacts,fee_config=asdict(fee),diagnostic_only=True,fee_child_scope_ref=child_ref,parent_base_receipt_ref=base['receipt_ref'])
    row=dict(base,coordinate_id=flow,status='COMPLETE',actual_account_attempted=True,receipt_ref=put(root/'receipt.json',receipt))
    plan,_=s._plan(report,scope)
    cells=[dict(base_coordinate_id=p['base_coordinate_id'],fee_condition=p['fee_condition'],status='NOT_TESTABLE',actual_account_attempted=False) for p in plan]
    cells[2].update(status='COMPLETE',actual_account_attempted=True,receipt_ref=row['receipt_ref'])
    index_ref=put(run/'evaluation/consensus_fee_sensitivity/status_index.json',dict(identity=s.extension._digest(dict(child=child_ref,acceptance=acceptance_ref)),cells=cells))
    (run/'FIT_LOG.jsonl').write_text('',encoding='utf-8')
    child=s._meta(child_ref);calendar=s.acceptance._calendar(run,child['account_calendar_ref'],config['comparison_scope_ref'])
    monkeypatch.setattr(s.acceptance,'_immutable_json',lambda path,value,kind:put(path,value))
    result,_=s.qualify_fee_account(run,row,frozen,index_ref,config['comparison_scope_ref'],calendar,None,diagnostic,child_ref)
    assert result['qualified'] is True and result['trade_fees']>0
    proof_path=root/'owner_audit.json';proof=json.loads(proof_path.read_text());proof['metadata']['fee_config']=asdict(s.cash.FeeConfig())
    proof_ref=put(proof_path,proof)
    with pytest.raises(s.acceptance.Unqualified,match='ACCOUNT_CONTRACT'):
        s.qualify_fee_account(run,row,frozen,index_ref,config['comparison_scope_ref'],calendar,proof_ref,diagnostic,child_ref)


@pytest.mark.parametrize('drift',['frozen','coordinate','index_path','index_identity','index_cells','index_not_terminal','actual_attempt','parent'])
def test_qualification_metadata_drift_precedes_any_ledger_or_state_decode(tmp_path,monkeypatch,drift):
    args=admission(tmp_path,monkeypatch);run,_,_,freeze,scope,config,acceptance_ref,child_ref=args
    report=s._acceptance(acceptance_ref);base=report['coordinates'][0];plan,_=s._plan(report,scope)
    coordinate=s.extension.Coordinate(*(base[k] for k in ('forecast_pack','risk_combination','decision_method')))
    diagnostic=s.FEES[0];frozen=s.comparison.extension_scope(scope);expected=s._fee_scope(frozen,diagnostic,child_ref)
    flow='fee__'+coordinate.identity+'__cost5';root=run/'evaluation/consensus_account'/flow
    receipt=dict(flow_id=flow,matrix_coordinate=asdict(coordinate),matrix_scope_identity=s.extension._digest(expected),
        receipt_path=str(root/'receipt.json'),freeze_ref=freeze,fee_child_scope_ref=child_ref,diagnostic_only=True,
        fee_config=expected['fee_config'],parent_base_receipt_ref=base['receipt_ref'],status='COMPLETE')
    if drift=='parent':receipt['parent_base_receipt_ref']={}
    row=dict(base,coordinate_id=flow,status='COMPLETE',actual_account_attempted=True,receipt_ref=put(root/'receipt.json',receipt))
    cells=[dict(base_coordinate_id=p['base_coordinate_id'],fee_condition=p['fee_condition'],status='NOT_TESTABLE',actual_account_attempted=False) for p in plan]
    cells[0].update(status='COMPLETE',actual_account_attempted=True,receipt_ref=row['receipt_ref'])
    index=dict(identity=s.extension._digest(dict(child=child_ref,acceptance=acceptance_ref)),cells=cells)
    if drift=='frozen':frozen['lookback_sessions']=119
    if drift=='coordinate':row['forecast_pack']='unplanned'
    if drift=='index_identity':index['identity']='wrong'
    if drift=='index_cells':index['cells'][1]['base_coordinate_id']='unplanned'
    if drift=='index_not_terminal':index['cells'][1]['status']='IN_PROGRESS'
    if drift=='actual_attempt':index['cells'][0]['actual_account_attempted']=False
    path=run/'evaluation/consensus_fee_sensitivity/status_index.json'
    if drift=='index_path':path=run/'other.json'
    index_ref=put(path,index);(run/'FIT_LOG.jsonl').write_text('',encoding='utf-8')
    child=s._meta(child_ref);calendar=s.acceptance._calendar(run,child['account_calendar_ref'],config['comparison_scope_ref'])
    calls=[]
    monkeypatch.setattr(s.acceptance,'_frame',lambda *a,**kw:calls.append('ledger'))
    monkeypatch.setattr(s.acceptance.joblib,'load',lambda *a,**kw:calls.append('state'))
    with pytest.raises(ValueError):s.qualify_fee_account(run,row,frozen,index_ref,config['comparison_scope_ref'],calendar,{},diagnostic,child_ref)
    assert calls==[]


@pytest.mark.parametrize('field',['calendar_source_ref','settlement_calendar_source_ref'])
def test_final_parent_calendar_source_drift_rejects_before_provider(tmp_path,monkeypatch,field):
    args=admission(tmp_path,monkeypatch);run,runner,loaded,freeze,scope,config,acceptance_ref,child_ref=args
    child=s._meta(child_ref);calendar=s._meta(child['account_calendar_ref'])
    assert len(set(calendar['account_sessions'])-set(calendar['settlement_sessions']))==1
    calendar[field]=put(run/'wrong_source.json',{'synthetic':'drift'})
    child['account_calendar_ref']=put(run/'COMPARISON_QUALIFIED_ACCOUNT_CALENDAR.json',calendar)
    report=json.loads(Path(acceptance_ref['path']).read_text())
    for row in report['coordinates']:row['calendar_ref']=child['account_calendar_ref']
    child['acceptance_ref']=put(acceptance_ref['path'],report);child_ref=put(child_ref['path'],child)
    calls=[];monkeypatch.setattr(s.runtime,'prepared_publication_provider',lambda *a:calls.append('numeric'))
    with pytest.raises(ValueError,match='CALENDAR_SOURCE_REFS'):
        s.replay_fee_plan(run,runner,loaded,None,freeze,scope,config,child['acceptance_ref'],child_ref)
    assert calls==[]



def test_split_config_uses_pinned_parent_execution_and_separate_managed_metadata(tmp_path,monkeypatch):
    args=admission(tmp_path,monkeypatch);run,runner,loaded,freeze,scope,config,acceptance_ref,child_ref=args
    child=s._meta(child_ref);managed=s._meta(config['managed_run_config_ref'])
    assert child['config_ref']['path']!=config['managed_run_config_ref']['path']
    assert config['managed_run_config_ref']==s.ref(run/'run_config.json')
    assert 'method_matrix_scope_ref' not in managed and 'comparison_input_freeze_ref' not in managed
    assert s._meta(child['config_ref'])==config and 'fee_child_scope_ref' not in config
    assert len(s._admit(run,runner,loaded,freeze,scope,config,acceptance_ref,child_ref)[1])==12


@pytest.mark.parametrize('drift',['managed_bytes','managed_path','execution_bytes','managed_as_execution','dispatch_as_parent'])
def test_split_config_drift_rejects_before_any_provider_or_model_decode(tmp_path,monkeypatch,drift):
    args=admission(tmp_path,monkeypatch);run,runner,loaded,freeze,scope,config,acceptance_ref,child_ref=args
    child=s._meta(child_ref)
    if drift=='managed_bytes':put(run/'run_config.json',{'broker_action_allowed':True,'synthetic':'drift'})
    if drift=='managed_path':
        config['managed_run_config_ref']=put(tmp_path/'same_bytes_wrong_managed_path.json',s._meta(config['managed_run_config_ref']))
        child['config_ref']=put(child['config_ref']['path'],config);child_ref=put(child_ref['path'],child)
    if drift=='execution_bytes':put(child['config_ref']['path'],{'synthetic':'drift'})
    if drift=='managed_as_execution':
        child['config_ref']=config['managed_run_config_ref'];child_ref=put(child_ref['path'],child)
    if drift=='dispatch_as_parent':config=dict(config,fee_child_scope_ref=child_ref)
    calls=[]
    monkeypatch.setattr(s.runtime,'prepared_publication_provider',lambda *a:calls.append('provider'))
    monkeypatch.setattr(s.runtime,'load_checkpoint',lambda *a:calls.append('model'))
    with pytest.raises(ValueError):s.replay_fee_plan(run,runner,loaded,None,freeze,scope,config,acceptance_ref,child_ref)
    assert calls==[]
