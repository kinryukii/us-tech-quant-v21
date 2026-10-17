"""Source-only R6 full-physical-DAG assembly over the existing run and owners.

No provider, estimator, optimizer or account is invoked here. Drafts preserve
unready dependencies; publication requires exact owner/support references.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
from pathlib import Path
import json
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.evaluation import joint_frozen_history_risk_r3 as parent
from scripts.research.a2.evaluation import joint_method_space_design_r6 as design
from scripts.research.a2.evaluation import joint_method_space_runtime_r6 as runtime
from scripts.research.a2.risk import joint_method_space_risk_r6 as risk
from scripts.research.a2.training import joint_method_space_opportunity_r6 as opportunity
from scripts.research.a2.training import joint_method_space_gross_execution_r6 as gross
from scripts.research.a2.inference import joint_method_space_optimizer_r6 as optimizer
from scripts.research.a2.inference import joint_method_space_policy_r6 as policy
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash

SOURCE_SHA='4a87deb43b77d67ac0192045b260d442c972aa0dcbefa231c7631cbdac6c8e19'
CLOCK_SHA='417c9306cd615ced4b2118919dc700a692c0575b33f8d46fbe26a6063a5bae85'
PLAN_SHA='4246d665036d3cc048f22edee41b0e03837a835968939c74ce666d3f65f168a8'
HUMAN=Path('C:/Users/Lenovo/.codex/attachments/b962b9b5-ff6e-496d-9526-3e785f98e958/已粘贴的文本.txt')
HUMAN_SHA='9a327ad0da2e876931f32ed7bfcd2306cc308ef3df2ffff7c4e95502dfa38ee6'
FIT_COMPONENTS=dict(risk=1705,sequence=408,bayesian=8,opportunity_prior_scale=21,gross=24,fusion=107)
ACCOUNT_STATUS_SHA='97bd58e384eef34a99811075c45c23720aa5552ffd13f5ff566cd9e18b1eb99d'
READINESS_KEYS=('owner_final_code_refs','opportunity_catalogue_ref','opportunity_support_ref','opportunity_identity_rows_ref',
                'risk_catalogue_ref','risk_identity_ref','risk_metadata_qualification_ref','risk_engineering_binding_ref',
                'opportunity_engineering_binding_ref','native_oof_identity_audit_ref','opportunity_reader_engineering_binding_ref','opportunity_scaler_count_engineering_binding_ref','policy_provider_status_ref','full_required_policy_support_ref','run_config_ref','input_manifest_ref')
JSON_READ_LIMIT=32*1024*1024

class FreezeBlocked(ValueError):pass

def ref(path):
    p=Path(path).resolve()
    return dict(source_ref=str(p),sha256=parent.sha(p))

def checked_ref(record,*,json_body=False):
    if not isinstance(record,dict) or set(record)-{'source_ref','sha256','semantic_digest'} or not {'source_ref','sha256'}<=set(record):
        raise FreezeBlocked('EXACT_PHYSICAL_REFERENCE_SCHEMA_REQUIRED')
    p=Path(record['source_ref'])
    if p.drive.upper() in ('E:','F:'):raise FreezeBlocked('EF_REFERENCE_FORBIDDEN')
    if not p.is_absolute() or p.resolve()!=p:raise FreezeBlocked('ABSOLUTE_RESOLVED_REFERENCE_REQUIRED')
    parent._pin(p,record['sha256'],'R6_FULL_CONTENT_REFERENCE')
    if json_body:
        if p.stat().st_size>JSON_READ_LIMIT:raise FreezeBlocked('FULL_JSON_READ_BOUND_EXCEEDED')
        return parent.read_json(p)
    return p

def _node(node_id,track,phase,cohort,component,dependencies=(),**details):
    return dict(node_id=node_id,track=track,phase=phase,cohort=cohort,component=component,
                dependencies=list(dependencies),units=1,status='CONDITIONAL_UNSTARTED',
                qualification='ACCEPTED_CANONICAL_R6_AND_FULL_FROZEN_SOURCE_SUPPORT_REQUIRED',**details)

def fit_nodes(events):
    """Expand owner-native physical groups into counted components, never refit."""
    nodes=[];rdag=risk.recipe_dag();registry=rdag['operation_registry']
    if len(registry)!=31 or len(events)!=55:raise FreezeBlocked('EXACT_55_BY_31_RISK_PLAN_REQUIRED')
    for event in events:
        eid=event['event_id'];prefix='RISK:'+eid+':'
        for op,row in sorted(registry.items()):
            nodes.append(_node(prefix+op,'risk',row['phase'],eid,op,
                [prefix+v.removeprefix('r6:') for v in row['dependencies']],
                physical_kind=row['kind'],as_of=event['decision_asof'],cutoff=event['fit_history_cutoff'],
                owner_cohort=row['cohort'],event_dependency=row['event_dependency'],
                applicable_methods=[m for m,v in rdag['methods'].items() if row['name'] in [o['name'] for o in v['operations']]],
                shared_context='ONE_EXACT_FIXED252_CLASSICAL_COHORT_QQQ_SOURCE_ORDERED_UID_EPOCH_CACHE',
                input_support='R6_RISK_METADATA_QUALIFICATION',numerical_dimension_is_model_count=False))
    odag=opportunity.physical_dag();rows=odag['nodes']
    if odag['total_parameter_component_upper']!=544:raise FreezeBlocked('OWNER_OPPORTUNITY_544_COMPONENTS_REQUIRED')
    lookup={row['node_id']:['OPP:'+row['node_id']+':'+c for c in row['component_ids']] for row in rows}
    if len(lookup)!=len(rows):raise FreezeBlocked('OWNER_DUPLICATE_PHYSICAL_GROUP')
    for row in rows:
        stage=row['stage'];track={'sequence':'sequence','sequence_scaler':'sequence','bayes':'bayesian','fusion':'fusion','native_uncertainty':'opportunity_prior_scale'}[stage]
        ids=lookup[row['node_id']];year=row['year'];phase=row.get('phase','ANNUAL_GENUINE_PRIOR');cohort=row.get('cohort',f'ANNUAL_{year}')
        deps=[];choices=[]
        if stage=='sequence':
            if phase=='INNER':deps+=lookup[cohort+'_L'+str(row['lookback'])+':SCALER']
            else:
                choices=[dict(rule='EXACT_SELECTED_WINDOW_ONE_OF_5_20_60',nodes=[lookup[cohort+'_L'+str(w)+':SCALER'][0] for w in opportunity.LOOKBACKS])]
                for fold in opportunity.inner_folds(year):
                    for length in opportunity.LOOKBACKS:deps+=lookup[fold['id']+'_L'+str(length)+':'+row['family']]
        elif stage=='bayes' and row['component_ids'][0]!='B32_SCALER':deps+=lookup[f'ANNUAL_{year}:BayesianRidge:B32_SCALER']
        elif stage=='fusion':
            method=row.get('method')
            if phase in ('probe','full') and method:
                if method in ('ridge_stack','hgb_stack','mlp_stack'):deps+=lookup[f'L_{year}:MEMBER_SCALER:{phase}']
                if method.endswith('_gate'):deps+=lookup[f'L_{year}:CONTEXT_SCALER:{phase}']
                if method in ('simplex','linear_gate','mlp_gate'):deps+=lookup[f'L_{year}:TARGET_RMS:{phase}']
            if row['node_id'].endswith(':RMS') and method not in ('equal','median'):
                for ph in ('probe','full'):deps+=lookup[f'L_{year}:{method}:{ph}']
            if row['node_id'].endswith(':COMPOSITE_RMS'):deps+=lookup[f'R6_RESIDUAL_{year-1}']
        for j,component in enumerate(row['component_ids']):
            n=_node(ids[j],track,phase,cohort,component,deps+ids[:j],
                owner_node_id=row['node_id'],owner_component_index=j,
                input_requirements=row['dependencies'],condition=row.get('conditional'),
                input_blocker=row.get('input_blocker'),model=row.get('family',row.get('member')),method=row.get('method'),
                lookback=row.get('lookback'),cutoff=next((f['cutoff'] for f in opportunity.inner_folds(year) if f['id']==cohort),f'{year}-01-01'),
                backend_group='OPP:'+row['node_id'],owner_backend_calls=row['backend_calls'],same_backend_components_reserved_together=True)
            if choices:n['conditional_dependency_groups']=choices
            nodes.append(n)
    for year in gross.YEARS:
        prior=f'GENUINE_EARLIER_R4_EQUAL_OOF_BEFORE_{year}';prefix=f'GROSS:{year}:'
        nodes.append(_node(prefix+'R4_EQUAL_PRIOR_RMS','gross','GENUINE_PRIOR_R4_EQUAL_OOF',prior,'R4_EQUAL_PRIOR_ERROR_RMS',cutoff=f'{year}-01-01'))
        nodes.append(_node(prefix+'SCALER','gross','TOP20_SELECTED_BEFORE_LABEL_FILTER',prior,'SHARED_GROSS_FEATURE_SCALER',[prefix+'R4_EQUAL_PRIOR_RMS'],cutoff=f'{year}-01-01'))
        for method in gross.g.FAMILIES:
            nodes.append(_node(prefix+method+':MODEL','gross','ANNUAL',prior,'MODEL_TRUNK' if method=='MLP' else 'MODEL_STATE',[prefix+'SCALER'],method=method,cutoff=f'{year}-01-01',backend_group=prefix+method))
            if method=='MLP':nodes.append(_node(prefix+method+':HEAD','gross','ANNUAL',prior,'MODEL_HEAD',[prefix+method+':MODEL'],method=method,backend_group=prefix+method,same_backend_components_reserved_together=True))
    counts={k:sum(n['units'] for n in nodes if n['track']==k) for k in FIT_COMPONENTS}
    if counts!=FIT_COMPONENTS:raise FreezeBlocked('ACTUAL_OWNER_COMPONENT_DAG_MISMATCH:'+str(counts))
    return nodes

def validate_dag(nodes):
    by={n['node_id']:n for n in nodes}
    if len(by)!=len(nodes):raise FreezeBlocked('DUPLICATE_PHYSICAL_NODE')
    visiting=set();done=set()
    def visit(key):
        if key in visiting:raise FreezeBlocked('PHYSICAL_DAG_CYCLE')
        if key in done:return
        visiting.add(key)
        for dep in by[key]['dependencies']:
            if dep not in by:raise FreezeBlocked('UNBOUND_PHYSICAL_DAG_DEPENDENCY:'+dep)
            visit(dep)
        for group in by[key].get('conditional_dependency_groups',[]):
            for dep in group['nodes']:
                if dep not in by:raise FreezeBlocked('UNBOUND_CONDITIONAL_DEPENDENCY')
                visit(dep)
        visiting.remove(key);done.add(key)
    for key in by:visit(key)
    return True

def policy_nodes(space,clock,provider_ready=False):
    solves=[];accounts=[];evaluations=[]
    for path in space['physical_paths']:
        pid=path['path_id'];spec=path['specification']
        for day in clock['q_dates']:
            solves.append(dict(node_id=f'Q:{pid}:{day}',kind='deterministic_optimizer_policy_solve',path_id=pid,decision_date=day,units_upper=1,actual_units_rule='reserve before each real complete backend; analytical/control target may consume zero',dependencies=['CANONICAL_ADMISSION','FULL_REQUIRED_ELIGIBLE_PLUS_HELD_SOURCE','QUALIFIED_FORECAST_RISK_AND_PROVIDER'],source_status='CONDITIONAL_UNSTARTED' if provider_ready else 'BLOCKED_ACCOUNT',context='ACTUAL_CURRENT_LOCKED_BUY_SLOTS_COST_UID_EPOCH_SOURCE; no cross-path assumed reuse'))
        if spec.get('action')=='MPC':
            for day in clock['decision_dates']:
                solves.append(dict(node_id=f'MPC:{pid}:{day}',kind='deterministic_optimizer_policy_solve',path_id=pid,decision_date=day,units_upper=1,horizon=2,dependencies=['CURRENT_FULL_REQUIRED_QUALIFIED_FRAME','FROZEN_CARRIED_Q_OR_SCHEDULED_Q'],source_status='CONDITIONAL_UNSTARTED' if provider_ready else 'BLOCKED_ACCOUNT'))
        accounts.append(dict(node_id='ACCOUNT:'+pid,path_id=pid,kind='account_mechanism_paths',units=1,one_way_bps=path['primary_bps'],persistent_account_owner='continuous_research_account via existing frozen-history shared account wrapper',dependencies=['CANONICAL_ADMISSION','FULL_REQUIRED_POLICY_OOF','QUALIFIED_REAL_PROVIDER','RAW_ACCOUNT_QUALITY_AND_ENTITLEMENTS'],status='CONDITIONAL_UNSTARTED' if provider_ready else 'BLOCKED_ACCOUNT'))
        evaluations.append(dict(path_id=pid,kind='DAILY_ACTION_GROSS_COUNTERSTATE',sessions=len(clock['decision_dates']),units_fit=0,units_solve=0,carried_target='not EXACT optimizer reuse',unfrozen_operational_structure_change='BLOCKED_ACCOUNT_SUPPORT_CHANGE_OUTSIDE_FROZEN_Q_CLOCK'))
    expected=len(space['physical_paths'])*len(clock['q_dates'])+sum(p['specification'].get('action')=='MPC' for p in space['physical_paths'])*len(clock['decision_dates'])
    if len(solves)!=expected or len(accounts)!=len(space['physical_paths']):raise FreezeBlocked('FULL_SOLVE_ACCOUNT_UPPER_REQUIRED')
    return solves,accounts,evaluations

def code_references():
    from scripts.research.a2.evaluation import joint_method_space_risk_execution_r6 as risk_io
    from scripts.research.a2.training import joint_method_space_opportunity_execution_r6 as opportunity_io
    paths={Path(__file__).resolve()}
    for record in risk_io.code_pins():paths.add(Path(record['source_ref']))
    for m in (opportunity_io,opportunity_io.metadata_owner,opportunity_io.old_training,opportunity_io.fit_owner,opportunity_io.mechanism,opportunity_io.old):paths.add(Path(m.__file__).resolve())
    for p in policy.source_pins():paths.add(Path(p))
    for relative in opportunity.source_pins():paths.add(parent.REPO/relative)
    for relative in (
      'scripts/research/a2/training/joint_method_space_opportunity_r6.py',
      'scripts/research/a2/training/joint_method_space_opportunity_execution_r6.py',
      'scripts/research/a2/training/joint_method_space_gross_execution_r6.py',
      'scripts/research/a2/ensemble/joint_fusion_execution_r4.py',
      'scripts/research/a2/data/joint_input_binding.py',
      'scripts/research/a2/evaluation/joint_method_space_risk_execution_r6.py',
      'scripts/research/a2/inference/joint_stateful_policy.py',
      'scripts/research/a2/evaluation/joint_sequential_training.py',
      'scripts/research/a2/retained/a2_pto_full_compat_20260928_r2/rl_control.py'):
        paths.add(parent.REPO/relative)
    return [ref(p) for p in sorted(paths)]

def validate_account_unavailable(value):
    """Typed negative evidence can close science bindings, never admit accounts."""
    if value.get('schema')!='B_R6_POLICY_PROVIDER_UNAVAILABLE_V1' or value.get('research_id')!=design.ID or value.get('status')!='BLOCKED_ACCOUNT':raise FreezeBlocked('TYPED_R6_UNAVAILABLE_PROVIDER_RECEIPT_REQUIRED')
    for key in ('provider_ready','full_required_policy_qualified','real_account_admission','unknown_identity_backfill','future_identity_used','alpha_output_grants_policy_qualification','R5_numeric_economic_read','EF_access','provider_fetch','strict_PIT_promotion_eligible','quote_qualified','certified_nav_qualified'):
        if value.get(key) is not False:raise FreezeBlocked('UNAVAILABLE_RECEIPT_FALSE_GATE_CHANGED:'+key)
    for key in ('unqualified_keys_removed','estimator_fit_count','optimizer_policy_solve_count','account_mechanism_paths','test2026_reads'):
        if type(value.get(key)) is not int or value[key]!=0:raise FreezeBlocked('UNAVAILABLE_RECEIPT_ZERO_BOUNDARY_CHANGED:'+key)
    if value.get('required_domain_preserved') is not True:raise FreezeBlocked('FULL_REQUIRED_DOMAIN_WAS_SHRUNK')
    if value.get('full_required_support')!=dict(rows=1052972,qualified=530075,blocked=522897,reasons=dict(MISSING_EXACT_CURRENT_FEATURE_SECURITY_UID=522577,SOURCE_FEATURE_METADATA_UNQUALIFIED=320)) or value.get('current_eligible_support')!=dict(rows=530075,qualified=530075,blocked=0,reasons={}):raise FreezeBlocked('ACTUAL_FULL_REQUIRED_METADATA_COUNTS_CHANGED')
    return False

def readiness(bindings):
    """Publication binding completeness is separate from account readiness."""
    bindings=bindings or {};missing=[key for key in READINESS_KEYS if key not in bindings]
    for key,value in bindings.items():
        if key.endswith('_ref') and value is not None:checked_ref(value,json_body=Path(value['source_ref']).suffix=='.json')
    if 'owner_final_code_refs' in bindings:
        if bindings['owner_final_code_refs']!=code_references():raise FreezeBlocked('FINAL_OWNER_CODE_CLOSURE_CHANGED')
    if 'policy_provider_status_ref' in bindings:
        status_ref=bindings['policy_provider_status_ref']
        if status_ref['sha256']!=ACCOUNT_STATUS_SHA or Path(status_ref['source_ref']).name!='R6_POLICY_PROVIDER_UNAVAILABLE.json':raise FreezeBlocked('EXACT_ROOT_TYPED_UNAVAILABLE_RECEIPT_REQUIRED')
        status=checked_ref(status_ref,json_body=True);validate_account_unavailable(status)
        if bindings.get('full_required_policy_support_ref')!=status_ref:raise FreezeBlocked('SAME_FULL_NEGATIVE_PROVIDER_AND_REQUIRED_SUPPORT_PROOF_REQUIRED')
        for key in ('opportunity_support_ref','source_authority_ref','source_only_clock_ref'):
            expected=bindings.get(key) if key=='opportunity_support_ref' else dict(source_ref=str(Path(status_ref['source_ref']).parent.parent/('SOURCE_AUTHORITY.json' if key=='source_authority_ref' else 'support/R6_SOURCE_ONLY_CLOCK.json')),sha256=SOURCE_SHA if key=='source_authority_ref' else CLOCK_SHA)
            if status[key]!=expected:raise FreezeBlocked('UNAVAILABLE_SUPPORT_CURRENT_SOURCE_BINDING_MISMATCH')
        if status['identity_rows_ref']!=bindings.get('opportunity_identity_rows_ref') or status['identity_rows_ref']!=bindings.get('risk_identity_ref'):raise FreezeBlocked('SAME_ACTUAL_IDENTITY_SIDECAR_REQUIRED')
        for record in status['existing_account_owner_code_refs']+[status['policy_consumer_code_ref']]:checked_ref(record)
        if {r['source_ref']:r['sha256'] for r in status['existing_account_owner_code_refs']}!=policy.source_pins():raise FreezeBlocked('UNAVAILABLE_PROVIDER_ACTUAL_OWNER_CLOSURE_CHANGED')
    else:missing.append('TYPED_ACCOUNT_UNAVAILABLE_PROOF_NOT_BOUND')
    if 'opportunity_support_ref' in bindings:
        summary=checked_ref(bindings['opportunity_support_ref'],json_body=True)
        if summary.get('schema')!='B_R6_SEQUENCE_IDENTITY_SUPPORT_V1' or summary.get('research_id')!=design.ID or summary.get('status')!='SOURCE_ONLY_METADATA_COMPLETE' or any(summary.get(k)!=0 for k in ('feature_label_prediction_values_read','test2026_reads','R5_results_reads','new_fit')):raise FreezeBlocked('ACTUAL_SOURCE_ONLY_OPPORTUNITY_SUMMARY_REQUIRED')
        r=summary['rows_ref'];normalized=dict(source_ref=str(Path(r['path']).resolve()),sha256=r['sha256'])
        if normalized!=bindings.get('opportunity_identity_rows_ref'):raise FreezeBlocked('OPPORTUNITY_SIDECAR_CUSTODY_CHANGED')
    if 'native_oof_identity_audit_ref' in bindings:
        native=checked_ref(bindings['native_oof_identity_audit_ref'],json_body=True)
        if bindings['native_oof_identity_audit_ref']['sha256']!='082d04481dce937eca49f2b68ca1e5dfce68d144ee5245b5097ea2b825d7193b':raise FreezeBlocked('EXACT_NATIVE32_SOURCE_ONLY_UID_AUDIT_REQUIRED')
    if 'risk_metadata_qualification_ref' in bindings:
        q=checked_ref(bindings['risk_metadata_qualification_ref'],json_body=True)
        if q.get('schema')!='B_R6_RISK_METADATA_QUALIFICATION_V1' or q.get('research_id')!=design.ID or len(q.get('nodes',[]))!=55 or any(q.get(k)!=0 for k in ('numeric_reads','new_fit','R5_results_reads','test2026_reads')):raise FreezeBlocked('ACTUAL55_ZERO_VALUE_RISK_QUALIFICATION_REQUIRED')
        if q['identity_ref']!=bindings.get('risk_identity_ref') or q['event_plan_ref']['sha256']!=PLAN_SHA:raise FreezeBlocked('RISK_QUALIFICATION_CURRENT_IDENTICAL_SOURCE_PLAN_REQUIRED')
    if any(bindings.get(k) is True for k in ('provider_ready','full_required_policy_qualified','real_account_admission')):raise FreezeBlocked('TRUE_BOOL_CANNOT_OVERRIDE_TYPED_UNAVAILABLE_ACCOUNT')
    return missing

def assemble(run,*,revision='R1',bindings=None,publish=False):
    run=Path(run).resolve();paths=resolve(parent.REPO)
    assert_safe_output_path(run,kind='backtest',paths=paths)
    if run.parent!=paths.backtest_root/'V24':raise FreezeBlocked('MANAGED_R6_RUN_REQUIRED')
    if not revision.isalnum() or len(revision)>16:raise FreezeBlocked('BOUNDED_DRAFT_REVISION_REQUIRED')
    source_path=run/'SOURCE_AUTHORITY.json';parent._pin(source_path,SOURCE_SHA,'R6_CURRENT_SOURCE')
    source=parent.read_json(source_path)
    if source.get('research_id')!=design.ID or source.get('test2026_reads')!=0 or any(source.get(k) is not False for k in ('EF_access','network_provider_fetch','R5_numeric_economic_read','quote_qualified','strict_PIT_promotion_eligible','certified_nav_qualified')):raise FreezeBlocked('EXACT_UNCERTIFIED_PRE2026_MECHANISM_BOUNDARY_REQUIRED')
    clock_path=run/'support/R6_SOURCE_ONLY_CLOCK.json';parent._pin(clock_path,CLOCK_SHA,'R6_SOURCE_ONLY_CLOCK');clock=parent.read_json(clock_path)
    plan_path=run/'support/R6_RISK_EVENT_PLAN.json';parent._pin(plan_path,PLAN_SHA,'R6_FIXED55_EVENT_PLAN');plan=parent.read_json(plan_path)
    if len(clock['decision_dates'])!=752 or len(clock['q_dates'])!=143 or clock.get('R5_numeric_economic_read') is not False or any(plan.get(k)!=0 for k in ('numeric_reads','return_value_reads','outcome_reads','test2026_reads')) or plan.get('R5_numeric_economic_read') is not False:raise FreezeBlocked('METADATA_ONLY_CLOCK_EVENT_BODY_REQUIRED')
    if plan['decision_dates']!=clock['decision_dates'] or plan['q_dates']!=clock['q_dates']:raise FreezeBlocked('CLOCK_PLAN_DISAGREEMENT')
    parent._pin(HUMAN,HUMAN_SHA,'FULL_R6_HUMAN_REQUEST');human_text=HUMAN.read_text(encoding='utf-8-sig')
    if len(human_text)<1000:raise FreezeBlocked('FULL_HUMAN_ATTACHMENT_REQUIRED_NOT_SYNOPSIS')
    missing=readiness(bindings)
    if publish and missing:raise FreezeBlocked('FORMAL_FREEZE_INCOMPLETE:'+','.join(missing))
    status='FROZEN_BEFORE_NUMERIC' if publish else 'DRAFT_SOURCE_ONLY_NOT_NUMERIC_AUTHORITY'
    prefix='' if publish else 'work/freeze_drafts/'+revision+'/'
    space=design.policy_space()
    if len(space['roles'])!=93 or len(space['joint_roles'])!=38 or len(space['physical_paths'])>design.CAPS['account_mechanism_paths']:raise FreezeBlocked('CURRENT93_38_FINITE_SPACE_REQUIRED')
    fits=fit_nodes(plan['events']);validate_dag(fits)
    solves,accounts,evaluations=policy_nodes(space,clock,provider_ready=False)
    codes=code_references();bounds=design.budget_proof(space,clock,FIT_COMPONENTS)
    if bounds['fits']!=2273 or bounds['policy_solves_upper']!=len(solves):raise FreezeBlocked('COMPLETE_PHYSICAL_BUDGET_SUM_MISMATCH')
    def write(name,value):
        relative=prefix+name;parent.write(run,relative,value,immutable=True);return ref(run/relative)
    common=dict(research_id=design.ID,status=status,test2026_reads=0,R5_numeric_economic_read=False,real_fit_count=0,real_solve_count=0,real_account_count=0)
    human_ref=write('R6_FULL_HUMAN_REQUEST.json',dict(schema='B_R6_FULL_HUMAN_REQUEST_V1',research_id=design.ID,attachment_ref=ref(HUMAN),encoding='utf-8-sig',full_text=human_text,not_synopsis=True))
    catalogue=write('R6_METHOD_CATALOGUE.json',dict(schema='B_R6_FULL_METHOD_CATALOGUE_V1',**common,
        opportunity=opportunity.specification(),opportunity_physical_dag=opportunity.physical_dag(),risk=risk.specification(),q=optimizer.specification(),policy=policy.specification(),gross=gross.specification(),finite_policy_space=space,
        RL_preregistration=dict(names=['DIRECT_SEQUENTIAL','REINFORCE','PPO'],native_parameters=dict(seed=20260928,epochs=4,learning_rate=.001,weight_decay=.0001,gamma=.99,ppo_clip=.2,noise=.2,chronological_minibatch=32,critic=.5,grad=2),input='32 B features + 8 actually observed account states; continuous past-only trajectory and raw next-Open log reward',RL_ADMISSION=False,admitted_fit_nodes=0,DirectSequential='BLOCKED_SOURCE_NO_R6_TRAIN_PRODUCER',REINFORCE_PPO='BLOCKED_INPUT_AND_SOURCE_NO_FULL_TRAJECTORY_OR_R6_DURABLE_ACK',old_native_2048_cap_not_R6_authority=True)))
    compatibility=[]
    for path in space['physical_paths']:
        spec=path['specification'];risk_method=spec.get('risk');tail=risk_method in ('EMPIRICAL_CVAR','EVT')
        compatibility.append(dict(path_id=path['path_id'],specification=spec,one_way_bps=path['primary_bps'],tail_covariance_auxiliary='POSTERIOR_PREDICTIVE' if tail else None,tail_scenarios='genuine full joint scenarios, never posterior fabricated' if tail else None,
            regime_risk_map=policy.REGIME_RISK_MAP if spec.get('regime')=='RISK_CONDITIONED' else None,tail_no_trade_status='BLOCKED_SOURCE' if spec.get('tail','NONE')!='NONE' else 'NOT_APPLICABLE',
            account_status='BLOCKED_ACCOUNT',full_required_policy_source_mandatory=True,opportunity_alpha_only_not_policy_authority=True))
    compat=write('R6_COMPATIBILITY_MATRIX.json',dict(schema='B_R6_FINITE_PHYSICAL_COMPATIBILITY_V1',**common,paths=compatibility,all_methods_supported_does_not_mean_account_qualified=True))
    reuse=write('R6_EXACT_REUSE_AUDIT.json',dict(schema='B_R6_EXACT_REUSE_FULL_CONTEXT_V1',**common,
        code_and_source_reuse='original pinned code and existing source bytes; not fitted-state equivalence',risk_learned_state_reuse_from_R3_R4_R5=0,
        native_R4_OOF_receipts='32 fixed candidates, only exact target/UID/clock/producer/recipe support can authorize values after admission',
        native_oof_identity_audit_ref=(bindings or {}).get('native_oof_identity_audit_ref'),opportunity_reader_engineering_binding_ref=(bindings or {}).get('opportunity_reader_engineering_binding_ref'),opportunity_scaler_count_engineering_binding_ref=(bindings or {}).get('opportunity_scaler_count_engineering_binding_ref'),
        native32_uid_audit_scope='CURRENT_ELIGIBLE_ALPHA_OOF_ONLY_NOT_FULL_REQUIRED_ELIGIBLE_PLUS_HELD',
        q_aliases=optimizer.specification()['aliases'],q_alias_requirements=optimizer.specification()['context_key'],
        q_alias_zero_new_solve='ONLY EXACT ALL CURRENT LOCKED BUY SLOTS COST AND SOURCE CONTEXT',
        role_aliases=[dict(role=r['role'],path_id=r['path_id']) for r in space['roles']],
        within_event31_primitives='shared once only exact same classical cohort/full UID epoch/QQQ/window/parameters StateCache key',
        fusion_shared_preprocessing='3 exact states per probe/full annual phase; member/context/target; input context unchanged',
        budget_old115_fusion_cap_preserved=True,new_actual_fusion_components_upper=107,failed_fits_nonrefundable=True))
    dag=write('R6_FULL_PHYSICAL_DAG.json',dict(schema='B_R6_FULL_PHYSICAL_DAG_V1',**common,estimator_fit_nodes=fits,optimizer_policy_solve_nodes=solves,account_nodes=accounts,deterministic_daily_evaluations=evaluations,
        graph_validated_acyclic=True,RL_admitted_fit_nodes=[],node_counts=dict(estimator_components=len(fits),whole_solve_upper=len(solves),accounts=len(accounts)),observed_dimension_not_model_count=True,source_blocked_nodes_retained=True))
    proof=write('R6_BUDGET_PROOF.json',dict(schema='B_R6_FULL_PHYSICAL_BUDGET_PROOF_V1',**common,**bounds,budget_caps=design.CAPS,
        counted_fit_components_from_DAG={k:sum(n['units'] for n in fits if n['track']==k) for k in FIT_COMPONENTS},
        actual_backend_calls_upper=dict(sequence=200,bayesian=4,gross=15,fusion=48),
        old_fusion115_conservative_cap=115,actual_fusion107_component_upper=107,
        units='parameter components, backend calls, deterministic transformations, matrix dimension, linear systems and actual account paths are separate',
        metadata_only_freeze_no_spend=True))
    contract=policy.MethodSpacePolicyContract(research_id=design.ID,run_id=run.name,scientific_recipe_sha256=content_hash(policy.specification()),source_sha256=SOURCE_SHA,paths=tuple(space['physical_paths']),decision_dates=tuple(clock['decision_dates']),q_dates=tuple(clock['q_dates']),source_code_pins=policy.source_pins(),
        provider_source_ref='',provider_source_sha256='',
        support_refs={(v['source_ref']):v['sha256'] for k,v in (bindings or {}).items() if k.endswith('_ref') and isinstance(v,dict) and 'source_ref' in v},forecast_lineage=(bindings or {}).get('forecast_lineage',{}))
    contract_body=parent._json(asdict(contract));contract_ref=write('R6_POLICY_CONSUMER_CONTRACT.json',contract_body);contract_ref['semantic_digest']=content_hash(contract_body)
    if contract_ref['semantic_digest']!=contract.digest():raise FreezeBlocked('ACYCLIC_POLICY_CONTRACT_DIGEST_MISMATCH')
    freeze=dict(schema='B_R6_METHOD_SPACE_FULL_PHYSICAL_DAG_V1',**common,budget_caps=design.CAPS,strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False,
        source_authority_ref=ref(source_path),method_catalogue_ref=catalogue,compatibility_matrix_ref=compat,exact_reuse_audit_ref=reuse,full_physical_dag_ref=dag,budget_proof_ref=proof,human_scope_ref=human_ref,full_human_attachment_ref=ref(HUMAN),
        source_code_pins=codes,source_only_clock_ref=ref(clock_path),risk_event_plan_ref=ref(plan_path),policy_consumer_contract_ref=contract_ref,
        policy_provider_ready=False,full_required_policy_qualified=False,real_account_admission=False,account_status='BLOCKED_ACCOUNT',remaining_binding_blockers=missing,remaining_blockers=['FULL_REQUIRED_ELIGIBLE_PLUS_HELD_IDENTITY_AND_SOURCE_CHAIN_INCOMPLETE','QUALIFIED_ACTUAL_POLICY_INPUT_PROVIDER'],
        provider_readiness_cannot_be_boolean_only=True,science_before_numeric_required=True,canonical_admission_separate_required=True,formal_publish_does_not_admit_numeric=True,
        read_boundaries=dict(train_and_development_exclusive='2026-01-01',test2026_locked=True,R5_numeric_economic_read=False,EF_access=False,network_provider_fetch=False))
    for key in READINESS_KEYS:
        if key in (bindings or {}):freeze[key]=(bindings or {})[key]
    return write(runtime.FILENAME,freeze),freeze

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--revision',default='R1');p.add_argument('--bindings');p.add_argument('--publish',action='store_true');a=p.parse_args()
    bindings=parent.read_json(a.bindings) if a.bindings else None
    if a.publish:
        with runtime.stage_writer(Path(a.run),'freeze'):r,f=assemble(a.run,revision=a.revision,bindings=bindings,publish=True)
    else:
        run=Path(a.run).resolve();assert_safe_output_path(run,kind='backtest',paths=resolve(parent.REPO))
        if not a.revision.isalnum() or len(a.revision)>16:raise FreezeBlocked('BOUNDED_DRAFT_REVISION_REQUIRED')
        lease=run/'work/freeze_drafts'/a.revision
        (lease/'work').mkdir(parents=True,exist_ok=True)
        with parent.task_writer(lease):r,f=assemble(run,revision=a.revision,bindings=bindings,publish=False)
    print(json.dumps(dict(freeze_ref=r,status=f['status'],remaining_blockers=f['remaining_blockers'],real_fit_count=0,real_solve_count=0,real_account_count=0),ensure_ascii=False))

if __name__=='__main__':main()