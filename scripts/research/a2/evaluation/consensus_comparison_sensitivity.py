"""Post-selection fee replay: private metadata adapters, unchanged original owners.

No input/model reads or work on import. The acceptance report is a plan; a
separately pinned child scope authorizes each actual fresh account.
"""
from __future__ import annotations
import ast, copy, inspect, json, textwrap
from dataclasses import asdict
from pathlib import Path
from types import FunctionType, SimpleNamespace
import pandas as pd
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.storage.storage_r2a import write_json_atomic
from scripts.research.a2.data.consensus_account_inputs import _JsonProjection
from scripts.research.a2.evaluation import consensus_comparison_run as comparison
from scripts.research.a2.evaluation import consensus_comparison_execution as runtime
from scripts.research.a2.evaluation import consensus_comparison_acceptance as acceptance
from scripts.research.a2.evaluation import consensus_method_extension as extension
from scripts.research.a2.evaluation import consensus_evaluation_run as evaluator
from scripts.research.a2.evaluation import consensus_cash_account as cash
from scripts.research.a2.training import consensus_account_rl as rl

SCHEMA='CONSENSUS_COMPARISON_FEE_CHILD_SCOPE_R1'
GATE='FROZEN_AUTHORIZED_POST_SELECTION_FEE_REPLAY'
MASTER_SHA='4e4e29a67ba09e0a541d5af93e7128556d4ae894bab5b2230fa38575be9d7332'
UPDATE='EXACT_CACHE_REUSE_THEN_ORIGINAL_CAUSAL_UPDATE'
FEES=(dict(tag='cost5',one_way_all_in_bps=5.,fixed_per_fill_usd=0.,lookback_sessions=120),
      dict(tag='cost25',one_way_all_in_bps=25.,fixed_per_fill_usd=0.,lookback_sessions=120),
      dict(tag='ticket50c',one_way_all_in_bps=10.,fixed_per_fill_usd=.5,lookback_sessions=120))
require=comparison.require
ref=comparison.ref


def _pin(reference):
    require(isinstance(reference,dict) and set(reference)=={'path','sha256'},'FEE_EXACT_REF_REQUIRED')
    return comparison.pin(reference)


def _meta(reference,fields=None):
    p=_pin(reference);require(p.stat().st_size<=8*1024*1024,'FEE_BOUNDED_METADATA_REQUIRED')
    if fields is None:return comparison.metadata(p,8*1024*1024)
    with p.open('rb') as f:return _JsonProjection(f).metadata_fields(set(fields))


def _pin_tree(value):
    if isinstance(value,dict):
        if set(value)=={'path','sha256'}:_pin(value)
        else:
            for v in value.values():_pin_tree(v)
    elif isinstance(value,list):
        for v in value:_pin_tree(v)


def code_refs():
    return {name:ref(module.__file__) for name,module in dict(adapter=SimpleNamespace(__file__=__file__),
        runtime=runtime,coordinator=comparison,extension=extension,acceptance=acceptance,
        evaluator=evaluator,cash=cash,consumer=runtime.C,rl=rl,auxiliary=rl.auxiliary).items()}


def child_scope_template(run):
    """PROPOSED only. Root fills final immutable refs after main termination."""
    return dict(schema=SCHEMA,status='PROPOSED',own_run=str(Path(run).resolve()),
        master_scope_ref=None,fee_authorized_ref=None,acceptance_ref=None,parent_freeze_ref=None,
        matrix_scope_ref=None,config_ref=None,source_scope_ref=None,input_freeze_ref=None,
        risk_cache_snapshot_ref=None,forecast_pins_ref=None,account_calendar_ref=None,rl_models={},code_refs=code_refs(),
        conditions=copy.deepcopy(acceptance.CONDITIONS),maximum_extra_accounts=12,
        all_accounts_restarted_empty=True,no_retuning=True,predictor_or_fusion_refit=False,
        rl_refit=False,risk_update_policy=UPDATE,selection_feedback=False)


def _acceptance(reference):
    top=_meta(reference,('schema','acceptance_source_ref','master_scope_ref','matrix_scope_ref',
        'status_index_ref','all_planned_coordinates_terminal','planned_labels','ranking','sensitivity_plan','read_scope'))
    rows=[]
    with _pin(reference).open('rb') as f:
        q=_JsonProjection(f);q.descend(('coordinates',));q.expect(b'[');q.white()
        while q.peek()!=b']':
            rows.append(q.metadata_fields({'coordinate_id','forecast_pack','risk_combination','decision_method','qualified','exact_alias_of','receipt_ref','calendar_ref'}))
            require(len(rows)<=383,'FEE_ACCEPTANCE_COORDINATE_LIMIT');q.white();sep=q.take()
            if sep==b']':break
            require(sep==b',','FEE_ACCEPTANCE_ARRAY_CHANGED');q.white()
    top['coordinates']=rows;return top


def _plan(report,scope):
    require(report['schema']==acceptance.SCHEMA and report['all_planned_coordinates_terminal'] is True
        and report['planned_labels']==383 and len(report['coordinates'])==383,'FEE_TERMINAL383_ACCEPTANCE_REQUIRED')
    byid={r['coordinate_id']:r for r in report['coordinates']}
    require(len(byid)==383 and len(set(report['ranking']))==len(report['ranking']),'FEE_UNIQUE_ACCEPTANCE_IDS_REQUIRED')
    require(all(byid[x].get('qualified') is True and byid[x].get('exact_alias_of') is None for x in report['ranking']),
        'FEE_ONLY_FULLY_CERTIFIED_REPRESENTATIVES')
    bases=report['ranking'][:3];neutral=tuple(scope['comparison']['neutral_coordinate'])
    matches=[r for r in byid.values() if tuple(r.get(k) for k in ('forecast_pack','risk_combination','decision_method'))==neutral]
    require(len(matches)==1,'FEE_EXACT_NEUTRAL_COORDINATE_REQUIRED')
    if matches[0].get('qualified') is True:
        representative=matches[0].get('exact_alias_of') or matches[0]['coordinate_id']
        require(byid[representative].get('qualified') is True,'FEE_CERTIFIED_NEUTRAL_REPRESENTATIVE_REQUIRED')
        if representative not in bases:bases.append(representative)
    expected=[(base,condition,byid[base]['receipt_ref']) for base in bases for condition in acceptance.CONDITIONS]
    actual=report['sensitivity_plan']
    require(len(actual)==len(expected)<=12 and all((r['base_coordinate_id'],r['fee_condition'],r['base_owner_receipt_ref'])==e
        and r['initial_cash']==3000 and r['empty_independent_account'] is True and r['no_retuning'] is True
        and r['execution_authorized_by_this_report'] is False and r['executed'] is False and r['status']=='PLANNED_NOT_ATTEMPTED' for r,e in zip(actual,expected)),
        'FEE_EXACT_TOP3_NEUTRAL_DEDUP_PLAN_REQUIRED')
    return actual,byid


def _admit(run,runner,loaded,freeze_ref,scope,config,acceptance_ref,child_scope_ref):
    child=_meta(child_scope_ref)
    require(child['schema']==SCHEMA and child['status']==GATE and child['own_run']==str(run),'FEE_AUTHORIZED_CHILD_REQUIRED')
    master=ref(run/comparison.SCOPE_FILE)
    require(master['sha256']==MASTER_SHA and child['master_scope_ref']==child['fee_authorized_ref']==master
        and _meta(master)==scope and config['comparison_scope_ref']==master,'FEE_EXACT_MASTER_AUTHORITY_REQUIRED')
    s=scope['sensitivities']
    require(s['conditions']==child['conditions']==acceptance.CONDITIONS and s['maximum_extra_accounts']==child['maximum_extra_accounts']==12
        and all(x is True for x in (s['no_retuning'],s['all_accounts_restarted_empty'],child['no_retuning'],child['all_accounts_restarted_empty'])),'FEE_MASTER_RECIPE_CHANGED')
    require(child['predictor_or_fusion_refit'] is child['rl_refit'] is child['selection_feedback'] is False
        and child['risk_update_policy']==UPDATE,'FEE_REFIT_OR_SELECTION_FORBIDDEN')
    require(child['code_refs']==code_refs(),'FEE_REVIEWED_CODE_PINS_REQUIRED')
    require(child['parent_freeze_ref']==freeze_ref and child['acceptance_ref']==acceptance_ref
        and _meta(child['config_ref'])==config
        and config['managed_run_config_ref']==ref(run/'run_config.json')
        and child['matrix_scope_ref']==config['method_matrix_scope_ref']==ref(run/comparison.FREEZE_FILE)
        and child['input_freeze_ref']==config['comparison_input_freeze_ref']
        and child['source_scope_ref']==loaded['source_scope_ref'],'FEE_PARENT_INPUT_AND_FREEZE_REFS_CHANGED')
    for k in ('parent_freeze_ref','matrix_scope_ref','input_freeze_ref','source_scope_ref','risk_cache_snapshot_ref','forecast_pins_ref','account_calendar_ref'):_pin(child[k])
    actual,_,frozen=runner.contract(run)
    require(Path(actual).resolve()==run and frozen==freeze_ref
        and callable(getattr(runner,'_matrix_evaluation_source',None))
        and callable(getattr(runner,'_matrix_execution_guard',None)),'FEE_ORIGINAL_C_GUARDED_RUNNER_REQUIRED')
    report=_acceptance(acceptance_ref)
    require(report['acceptance_source_ref']==child['code_refs']['acceptance'] and report['master_scope_ref']==master
        and report['matrix_scope_ref']==child['matrix_scope_ref'] and report['read_scope']['own_run']==str(run)
        and report['read_scope']['test2026_read'] is False and report['read_scope']['confirmation_read'] is False,
        'FEE_ACCEPTANCE_PROVENANCE_CHANGED')
    _pin(report['status_index_ref']);plan,rows=_plan(report,scope)
    dates=pd.DatetimeIndex(loaded['market'].dates);returns=loaded['returns']
    require(not dates.empty and dates.min()>=pd.Timestamp('2023-01-01') and dates.max()<pd.Timestamp('2026-01-01')
        and set(dates.year)=={2023,2024,2025} and isinstance(returns,pd.DataFrame) and not returns.empty
        and isinstance(returns.index,pd.DatetimeIndex) and returns.index.max()<pd.Timestamp('2026-01-01'),
        'FEE_SAME_2023_2025_PRE2026_INPUTS_REQUIRED')
    for r in plan:
        _pin(r['base_owner_receipt_ref'])
        require(rows[r['base_coordinate_id']]['calendar_ref']==child['account_calendar_ref'],'FEE_PARENT_CERTIFIED_CALENDAR_CHANGED')
    calendar=acceptance._calendar(run,child['account_calendar_ref'],master)
    require(dates.equals(calendar[0]) and calendar[2]['consumer_freeze_ref']==freeze_ref,'FEE_FULL_PARENT_ACCOUNT_CALENDAR_REQUIRED')
    return child,plan,rows


def _fee_scope(parent_scope,diagnostic,child_scope_ref):
    expected=extension.validate_scope(parent_scope)
    expected['fee_config'].update(one_way_all_in_bps=diagnostic['one_way_all_in_bps'],fixed_per_fill_usd=diagnostic['fixed_per_fill_usd'])
    expected['fee_authorized_child_scope_ref']=copy.deepcopy(child_scope_ref)
    return expected


def _check_receipt(value,run,coordinate,diagnostic,expected_scope,child_scope_ref,parent_ref,freeze_ref):
    path=run/'evaluation/consensus_account'/('fee__'+coordinate.identity+'__'+diagnostic['tag'])/'receipt.json'
    require(Path(value['receipt_path']).resolve()==path and value['fee_config']==expected_scope['fee_config']
        and value['diagnostic_only'] is True and value['fee_child_scope_ref']==child_scope_ref
        and value['parent_base_receipt_ref']==parent_ref and value['freeze_ref']==freeze_ref
        and value['matrix_coordinate']==asdict(coordinate)
        and value['matrix_scope_identity']==extension._digest(expected_scope),'FEE_ACTUAL_RECEIPT_IDENTITY_CHANGED')
    return path


def fee_binding(base_joint,parent_scope,coordinate,diagnostic,child_scope_ref,**kwargs):
    """Project only the already-authorized fee literal; all other scope checks stay."""
    require(diagnostic in FEES,'FEE_EXACT_THREE_CONDITIONS_REQUIRED')
    original=extension.validate_scope(parent_scope,coordinate);expected=_fee_scope(original,diagnostic,child_scope_ref)
    def validate(value,coord=None):
        require(value==expected,'FEE_SCOPE_PROJECTION_CHANGED')
        restored=copy.deepcopy(value);restored.pop('fee_authorized_child_scope_ref');restored['fee_config']=copy.deepcopy(original['fee_config'])
        extension.validate_scope(restored,coord);return copy.deepcopy(expected)
    bind=FunctionType(extension.bind_joint.__code__,{**extension.bind_joint.__globals__,'validate_scope':validate},argdefs=extension.bind_joint.__defaults__)
    bind.__kwdefaults__=extension.bind_joint.__kwdefaults__
    return bind(base_joint,scope=expected,coordinate=coordinate,**kwargs)


def fee_evaluate(runner,coordinate,*args,binding,diagnostic,child_scope_ref,make_policy,on_account_entry=None):
    """Original E and C guard; only explicit diagnostic tag/flow identity differ."""
    require(diagnostic in FEES,'FEE_EXACT_THREE_CONDITIONS_REQUIRED')
    source=runner._matrix_evaluation_source;owner=source.__globals__['shareholder']
    def account(*a,**kw):
        if on_account_entry is not None:on_account_entry()
        return owner.run_shareholder_cash_account(*a,**kw)
    proxy=SimpleNamespace(**{**vars(owner),'run_shareholder_cash_account':account})
    source=FunctionType(source.__code__,{**source.__globals__,'shareholder':proxy},argdefs=source.__defaults__);source.__kwdefaults__=runner._matrix_evaluation_source.__kwdefaults__
    local=SimpleNamespace(**{**vars(runner),'_matrix_evaluation_source':source})
    tree=ast.parse(textwrap.dedent(inspect.getsource(extension.evaluate_flow)))
    flow=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='flow_id');edits=0
    for n in ast.walk(flow):
        if isinstance(n,ast.Compare) and isinstance(n.left,ast.Name) and n.left.id=='diagnostic':
            require(len(n.ops)==1 and isinstance(n.ops[0],ast.Is) and isinstance(n.comparators[0],ast.Constant) and n.comparators[0].value is None,'FEE_FLOW_TAG_ANCHOR_CHANGED')
            n.ops=[ast.Eq()];n.comparators=[ast.Constant(value=diagnostic['tag'])];edits+=1
    ret=next(n for n in flow.body if isinstance(n,ast.Return));require(ast.unparse(ret.value)=="'matrix__' + coordinate.identity" and edits==1,'FEE_FLOW_ID_ANCHOR_CHANGED')
    ret.value=ast.Constant(value='fee__'+coordinate.identity+'__'+diagnostic['tag'])
    ns=vars(extension).copy();exec(compile(ast.fix_missing_locations(tree),__file__,'exec'),ns)
    return ns['evaluate_flow'](local,coordinate,*args,binding=binding,make_policy=make_policy,diagnostic=diagnostic)


def qualify_fee_account(run,row,frozen,index_ref,master,calendar,owner_ref,diagnostic,child_scope_ref):
    """Explicit post-run observer; original ledger/audit checks under child fees."""
    require(diagnostic in FEES,'FEE_EXACT_THREE_CONDITIONS_REQUIRED')
    child=_meta(child_scope_ref)
    require(child['schema']==SCHEMA and child['status']==GATE and child['own_run']==str(Path(run).resolve())
        and child['master_scope_ref']==child['fee_authorized_ref']==master and master['sha256']==MASTER_SHA
        and child['code_refs']==code_refs(),'FEE_AUTHORIZED_CHILD_REQUIRED')
    _pin(master)
    require(master==ref(Path(run)/comparison.SCOPE_FILE),'FEE_EXACT_MASTER_AUTHORITY_REQUIRED')
    parent_scope=_meta(master);report=_acceptance(child['acceptance_ref']);plan,rows=_plan(report,parent_scope)
    require(frozen==comparison.extension_scope(parent_scope) and report['master_scope_ref']==master
        and report['matrix_scope_ref']==child['matrix_scope_ref']
        and report['acceptance_source_ref']==child['code_refs']['acceptance'],'FEE_PARENT_CERTIFIED_PLAN_CHANGED')
    condition={k:diagnostic[k] for k in ('fixed_per_fill_usd','one_way_all_in_bps')}
    matches=[p for p in plan if p['fee_condition']==condition and all(row[k]==rows[p['base_coordinate_id']][k]
        for k in ('forecast_pack','risk_combination','decision_method'))]
    require(len(matches)==1,'FEE_ONLY_EXACT_PLANNED_CHILD_MAY_QUALIFY');planned=matches[0]
    require(Path(index_ref['path']).resolve()==Path(run)/'evaluation/consensus_fee_sensitivity/status_index.json','FEE_OWN_CHILD_STATUS_INDEX_REQUIRED')
    index=_meta(index_ref)
    require(index['identity']==extension._digest(dict(child=child_scope_ref,acceptance=child['acceptance_ref']))
        and [(r['base_coordinate_id'],r['fee_condition']) for r in index['cells']]==[(r['base_coordinate_id'],r['fee_condition']) for r in plan]
        and all(r['status'] in acceptance.TERMINAL for r in index['cells']),'FEE_TERMINAL_EXACT_CHILD_PLAN_REQUIRED')
    cell=next(r for r in index['cells'] if r['base_coordinate_id']==planned['base_coordinate_id'] and r['fee_condition']==condition)
    require(cell.get('receipt_ref')==row['receipt_ref'] and cell['status']==row['status']=='COMPLETE'
        and cell['actual_account_attempted'] is row['actual_account_attempted'] is True,'FEE_ACTUAL_COMPLETE_ACCOUNT_REQUIRED')
    acceptance._budget(Path(run))
    expected=_fee_scope(frozen,diagnostic,child_scope_ref)
    fee=cash.FeeConfig(**expected['fee_config'])
    private_cash=SimpleNamespace(**{**vars(cash),'FeeConfig':lambda:fee})
    proof=FunctionType(acceptance._owner_proof.__code__,{**acceptance._owner_proof.__globals__,'cash':private_cash},argdefs=acceptance._owner_proof.__defaults__)
    tree=ast.parse(textwrap.dedent(inspect.getsource(acceptance._receipt)))
    flow=next(n for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='flow' for t in n.targets))
    require(ast.unparse(flow.value)=="'matrix__' + coordinate.identity",'FEE_ACCEPTANCE_FLOW_ANCHOR_CHANGED')
    flow.value=ast.parse("'fee__'+coordinate.identity+'__'+"+repr(diagnostic['tag']),mode='eval').body
    ns=vars(acceptance).copy();exec(compile(ast.fix_missing_locations(tree),__file__,'exec'),ns)
    def receipt(*args):
        root,value=ns['_receipt'](*args)
        require(value['fee_child_scope_ref']==child_scope_ref and value['diagnostic_only'] is True
            and value['fee_config']==asdict(fee) and value['parent_base_receipt_ref']==planned['base_owner_receipt_ref'],
            'FEE_CHILD_RECEIPT_AUTHORITY_REQUIRED')
        return root,value
    check=FunctionType(acceptance._account.__code__,{**acceptance._account.__globals__,
        'cash':private_cash,'_owner_proof':proof,'_receipt':receipt},argdefs=acceptance._account.__defaults__)
    run=Path(run).resolve()
    actual_calendar=acceptance._calendar(run,child['account_calendar_ref'],master)
    require(calendar[-1]==actual_calendar[-1] and calendar[0].equals(actual_calendar[0])
        and calendar[1].equals(actual_calendar[1]),'FEE_PARENT_CERTIFIED_CALENDAR_CHANGED')
    if owner_ref is None:
        require(row['status']=='COMPLETE' and row['actual_account_attempted'] is True,'FEE_ACTUAL_COMPLETE_ACCOUNT_REQUIRED')
        context=lambda *args:(run,None,expected,child['matrix_scope_ref'],master,index_ref,[dict(row,exact_alias_of=None)])
        export=FunctionType(acceptance.export_owner_audits.__code__,{**acceptance.export_owner_audits.__globals__,
            '_context':context,'_receipt':receipt},argdefs=acceptance.export_owner_audits.__defaults__)
        owner_ref=export(run,index_ref)['owner_audit_refs'][row['coordinate_id']]
    return check(run,row,expected,index_ref,master,actual_calendar,owner_ref)


def _frozen_rl(run,base_id,coordinate,child,config,scope):
    entry=child['rl_models'].get(base_id);require(isinstance(entry,dict),'FEE_FROZEN_RL_MODEL_MISSING')
    key=(coordinate.forecast_pack,coordinate.risk_combination,coordinate.decision_method)
    identity=runtime.rl_fit_identity(key,config,child['input_freeze_ref'],scope)
    folder=run/'models/consensus_comparison_runtime/rl'/identity
    require(Path(entry['receipt_ref']['path']).resolve()==folder/'receipt.json'
        and Path(entry['model_ref']['path']).resolve()==folder/'policy.joblib','FEE_RL_EXACT_MODEL_WHITELIST_PATH_REQUIRED')
    meta=_meta(entry['receipt_ref'],('status','identity','coordinate','source_ref','schedule_ref','training_reward_years','outer_rewards_used','model_ref'))
    require(meta.get('status')=='FITTED' and meta['identity']==identity and meta['coordinate']==list(key)
        and meta['model_ref']==entry['model_ref'] and meta['source_ref']==config['rl_source_binding_ref']
        and meta['schedule_ref']==config['rl_causal_schedule_ref'] and meta['training_reward_years']==[2022]
        and meta['outer_rewards_used'] is False,'FEE_RL_FROZEN_SOURCE_AND_IDENTITY_REQUIRED')
    _pin(meta['source_ref']);_pin(meta['schedule_ref'])
    with _pin(entry['receipt_ref']).open('rb') as f:
        q=_JsonProjection(f);q.descend(('fit_receipt',));fitmeta=q.metadata_fields({'status','recipe','training_reward_years','source_contract'})
    recipe=copy.deepcopy(rl.auxiliary.RECIPE);recipe['reward_years']=[2022]
    require(fitmeta.get('status')=='FITTED_ACCOUNT_POLICY' and fitmeta['recipe']==recipe
        and fitmeta['training_reward_years']==[2022] and fitmeta['source_contract']['outer_development_rewards_used'] is False,
        'FEE_RL_ORIGINAL_FROZEN_2022_RECIPE_REQUIRED')
    contract=fitmeta['source_contract']
    require(contract.get('training_inputs_ref')==config['rl_source_binding_ref']
        and contract.get('causal_schedule_ref')==config['rl_causal_schedule_ref']
        and contract.get('training_reward_years')==[2022] and contract.get('source_qualified') is True
        and [s['segment_id'] for s in contract.get('reset_segments',[])]==['2022'],
        'FEE_RL_ACTUAL_TRAINING_CONTRACT_SOURCE_REQUIRED')
    fitted=runtime.load_checkpoint(entry['model_ref'],folder/'policy.joblib')
    require(isinstance(fitted,rl.auxiliary.RLFit) and fitted.method==coordinate.decision_method.removeprefix('rl_')
        and fitted.contract==fitmeta['source_contract'] and fitted.receipt['recipe']==recipe
        and fitted.receipt['training_reward_years']==[2022],'FEE_RL_MODEL_RECEIPT_PAYLOAD_CHANGED')
    return fitted


def _setup(run,runner,loaded,child,config,cache):
    provider=runtime.inputs.ComparisonInputProvider(child['input_freeze_ref'])
    provider.native_source_provider=runtime.NativeSource(provider)
    counted=runtime.CountedStates(run,runner,child['input_freeze_ref']);r2=runtime.CountedR2(provider.typed_r2,counted)
    dates=pd.DatetimeIndex(loaded['market'].dates);market=loaded['market']
    def scenarios(date,full,required):
        if not required:return None
        return provider.scenario(date,required,mean_state_provider=counted.scenario_mean,account_assets=full,
            inactive_zero_padding_assets=tuple(a for a in full if a not in set(required)))
    def references(date,full,required):
        require(tuple(map(str,market.tickers))==full,'FEE_REFERENCE_ACCOUNT_ORDER_CHANGED')
        return provider.reference(market,int(dates.get_loc(pd.Timestamp(date))))
    return provider.bank_dependencies,r2,scenarios,references


def replay_fee_plan(run,runner,loaded,reader,freeze_ref,scope,config,acceptance_ref,child_scope_ref):
    """Execute the finite admitted plan; prediction/RL fitting has no entry here."""
    run=Path(run).resolve();child,plan,rows=_admit(run,runner,loaded,freeze_ref,scope,config,acceptance_ref,child_scope_ref)
    publisher=runtime.prepared_publication_provider(run)
    with runtime.predictors.fit_lock(run):
        frozen=comparison.extension_scope(scope);root=run/'evaluation/consensus_fee_sensitivity'
        assert_safe_output_path(root,kind='backtest',paths=resolve());root.mkdir(parents=True,exist_ok=True)
        identity=extension._digest(dict(child=child_scope_ref,acceptance=acceptance_ref))
        ip=root/'status_index.json'
        index=comparison.metadata(ip) if ip.exists() else dict(identity=identity,cells=[dict(base_coordinate_id=r['base_coordinate_id'],fee_condition=r['fee_condition'],status='PLANNED_NOT_ATTEMPTED',actual_account_attempted=False) for r in plan])
        require(index['identity']==identity and len(index['cells'])==len(plan) and all(
            (cell['base_coordinate_id'],cell['fee_condition'])==(item['base_coordinate_id'],item['fee_condition'])
            for cell,item in zip(index['cells'],plan)),'FEE_RESUME_IDENTITY_CHANGED')
        for cell in index['cells']:
            if cell['status']=='IN_PROGRESS':cell.update(status='FAILED_NO_RETRY',failure=dict(reason='UNFINISHED_CHILD_ACCOUNT_NO_AUTOMATIC_RETRY'))
        write_json_atomic(ip,index)
        snapshot=_meta(child['risk_cache_snapshot_ref'],('schema','root','max_resident'))
        cache_root=run/'evaluation/consensus_comparison/risk_store'
        require(snapshot['schema']=='CONSENSUS_EXACT_RISK_CACHE_SNAPSHOT_R12' and Path(snapshot['root']).resolve()==cache_root
            and snapshot['max_resident']==2,'FEE_ORIGINAL_EXACT_RISK_STORE_REQUIRED')
        cache=comparison.DiskRiskCache(cache_root,max_resident=2)
        def initialize(run,cache):return cache
        runner._matrix_execution_guard(initialize)(run,cache)
        cache.update(comparison._restore_risk_cache(child['risk_cache_snapshot_ref']))
        if index.get('risk_cache_snapshot_ref'):
            own_snapshot=_meta(index['risk_cache_snapshot_ref'],('schema','root','max_resident'))
            require(own_snapshot==snapshot,'FEE_CHILD_CACHE_STORE_CHANGED')
            cache.update(comparison._restore_risk_cache(index['risk_cache_snapshot_ref']))
        dependencies,r2,scenarios,references=_setup(run,runner,loaded,child,config,cache)
        publications=_meta(child['forecast_pins_ref']);packs={};bridges=[]
        for slot,planned in zip(index['cells'],plan):
            row=rows[planned['base_coordinate_id']];coordinate=extension.Coordinate(*(row[k] for k in ('forecast_pack','risk_combination','decision_method')))
            diagnostic=next(x for x in FEES if {k:x[k] for k in ('fixed_per_fill_usd','one_way_all_in_bps')}==planned['fee_condition'])
            if slot['status']!='PLANNED_NOT_ATTEMPTED':
                if slot.get('receipt_ref'):
                    value=_meta(slot['receipt_ref'],('status','receipt_path','fee_config','diagnostic_only','fee_child_scope_ref',
                        'parent_base_receipt_ref','freeze_ref','matrix_coordinate','matrix_scope_identity'))
                    _check_receipt(value,run,coordinate,diagnostic,_fee_scope(frozen,diagnostic,child_scope_ref),child_scope_ref,planned['base_owner_receipt_ref'],freeze_ref)
                    require(value['status']==slot['status'],'FEE_RESUMED_RECEIPT_STATUS_CHANGED')
                continue
            slot['status']='IN_PROGRESS';write_json_atomic(ip,index);active={}
            try:
                expected=publications[coordinate.forecast_pack];require(len(expected)==3 and [r['year'] for r in expected]==[2023,2024,2025],'FEE_FROZEN_FORECAST_YEARS_REQUIRED');_pin_tree(expected)
                if coordinate.forecast_pack not in packs:
                    value=comparison._publications(run,coordinate.forecast_pack,scope['comparison']['forecast_packs'][coordinate.forecast_pack],reader,runner,publisher)
                    require(value[1]==expected,'FEE_FROZEN_FORECAST_PUBLICATIONS_CHANGED');packs[coordinate.forecast_pack]=value
                forecasts,pins=packs[coordinate.forecast_pack]
                fitted=_frozen_rl(run,planned['base_coordinate_id'],coordinate,child,config,scope) if coordinate.decision_method in extension.EXTERNAL_DECISION_METHODS else None
                def bank_fit(method,past,*,params,dependencies,event):
                    require('receipt' in active,'FEE_ACTUAL_RECEIPT_REQUIRED_BEFORE_RISK_FIT')
                    return comparison.bank_adapter(runner,run,active['receipt'],cache,child['matrix_scope_ref'],bridges)(method,past,params=params,dependencies=dependencies,event=event)
                common=dict(bank_fit=bank_fit,bank_dependencies=dependencies,r2_fit=r2,scenarios=scenarios,references=references)
                def external(method,forecasts,past_daily_returns,*,config,fee_config,**kwargs):
                    require(fitted is not None,'FEE_FROZEN_RL_MODEL_REQUIRED_NO_FIT_FALLBACK')
                    basecoord=extension.Coordinate(coordinate.forecast_pack,coordinate.risk_combination,'cost_aware')
                    base=fee_binding(runner.joint,frozen,basecoord,diagnostic,child_scope_ref,**common)
                    policy=base.ConsensusJointPolicy(forecasts,past_daily_returns,config=base.PolicyConfig(coordinate.risk_combination,'cost_aware',120),fee_config=fee_config,**kwargs)
                    return rl.FrozenActivityPolicy(policy,fitted,runtime.causal_context_observation,rl.activity_delta_gate)
                binding=fee_binding(runner.joint,frozen,coordinate,diagnostic,child_scope_ref,external_policy_factory=external if fitted is not None else None,**common)
                def factory(forecasts,returns,config,fee_config,actual,receipt,shared_cache,cell_identity):
                    require(Path(actual).resolve()==run and shared_cache is cache,'FEE_ONE_C_GUARDED_CACHE_REQUIRED');active['receipt']=receipt
                    receipt.update(fee_child_scope_ref=child_scope_ref,parent_base_receipt_ref=planned['base_owner_receipt_ref'],selection_feedback=False,frozen_rl_model_ref=child['rl_models'].get(planned['base_coordinate_id']))
                    return binding.ConsensusJointPolicy(forecasts,returns,config=config,fee_config=fee_config,shared_risk_cache=cache)
                def entered():slot['actual_account_attempted']=True;write_json_atomic(ip,index)
                result=fee_evaluate(runner,coordinate,run,coordinate.forecast_pack,coordinate.risk_combination,coordinate.decision_method,forecasts,loaded['returns'],loaded,freeze_ref,pins,cache,
                    binding=binding,diagnostic=diagnostic,child_scope_ref=child_scope_ref,make_policy=factory,on_account_entry=entered)
                expected_path=_check_receipt(result,run,coordinate,diagnostic,binding.matrix_scope,child_scope_ref,planned['base_owner_receipt_ref'],freeze_ref)
                slot.update(status=result['status'],receipt_ref=ref(expected_path),budget_exhausted=bool(result.get('budget_exhausted',False)))
            except Exception as error:
                slot.update(status='NOT_TESTABLE' if isinstance(error,(ValueError,KeyError,evaluator.NotTestable)) else 'FAILED_NO_RETRY',failure=dict(type=type(error).__name__,reason=str(error)))
            index['risk_cache_snapshot_ref']=cache.snapshot_ref();write_json_atomic(ip,index)
        summary=dict(schema='CONSENSUS_COMPARISON_FEE_REPLAY_RESULT_R1',child_scope_ref=child_scope_ref,acceptance_ref=acceptance_ref,index_ref=ref(ip),
            planned_accounts=len(plan),actual_account_attempts=sum(r['actual_account_attempted'] for r in index['cells']),
            execution_complete=bool(plan) and all(r['status']=='COMPLETE' and r['actual_account_attempted'] for r in index['cells']),
            selection_feedback=False,predictor_or_fusion_refits=0,rl_refits=0,risk_updates=UPDATE,independent_initial_cash=3000,continuous_years=[2023,2024,2025],qualified=False,account_certification='PENDING_ORIGINAL_OWNER_LEDGER_AUDIT')
        write_json_atomic(root/'summary.json',summary);return summary
