"""C13 one-run pure membership orchestration, reusing B state and C statistics.

No risk producer, estimator, target miner, account engine or new registry.
Prepare is metadata-only; execute requires independently reviewed formal pins.
Sparse native states never become a fake complete primary series.
"""
from __future__ import annotations
import argparse, ast, json, os, shutil
from dataclasses import asdict
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.data import selector_shared_risk_consumer as consumer
from scripts.research.a2.factors import selector_constrained_membership as rules
from scripts.research.a2.evaluation import selector_constrained_evidence as ev
from scripts.research.a2.evaluation import selector_evidence as shared
from scripts.research.a2.evaluation.selector_account_compare import sha, readj, pre2026
from scripts.research.a2.training.selector_classical_risk import safe_d, pin, put
from scripts.research.a2.training.selector_challenge import now
from scripts.research.a2.risk.shared_risk_budget_r2 import StateBudget, content_hash

REPO=Path(__file__).resolve().parents[4]
ID=ev.RESEARCH_ID
RUN=Path('D:/us-tech-quant-backtests/V24/20261004T041944+0000_c7940913')
C12=Path('D:/us-tech-quant-backtests/V24/20261003T184731+0000_4ad5a591')
FAMILIES={f.split('_')[0]:f for f in consumer.FAMILIES}
KEYS=shared.KEY+['ticker','U_t_fingerprint']


def ref(path):
    return dict(path=str(safe_d(path)),sha256=sha(path))


def paths(root):
    root=safe_d(root); assert_safe_output_path(root,kind='backtest')
    if root!=RUN: raise ValueError('ONLY_AUTHORIZED_SINGLE_C13_RUN')
    cfg=readj(root/'run_config.json')
    if cfg['research_id']!=ID:raise ValueError('RESEARCH_ID_MISMATCH')
    results=safe_d(cfg['results']);cache=safe_d(cfg['cache'])
    assert_safe_output_path(results,kind='results');assert_safe_output_path(cache,kind='cache')
    return root,results,cache


def raw_geometry(raw):
    if not set(KEYS+['score','rank']).issubset(raw) or raw.duplicated(shared.KEY).any():raise ValueError('RAW_FULL_U_REQUIRED')
    shared.validate_rank(raw)
    if len(raw)!=313668 or raw.signal_date.nunique()!=752:raise ValueError('PRESERVE_ORIGINAL_U_CALENDAR')
    raw=raw.sort_values(shared.KEY,kind='stable').reset_index(drop=True)
    for _,g in raw.groupby('signal_date'):
        consumer.current_map(g)
        if not np.array_equal(np.sort(g['rank'].to_numpy()),np.arange(1,len(g)+1)):raise ValueError('RAW_ORDINAL_REQUIRED')
    return raw


def physical_dag(q):
    nodes=[]
    for role in ev.ACTIVE_ROLES:
        r,method=role.split('_')[1:];family=FAMILIES[r]
        for day in q['families'][family]['eligible_dates']:
            state=[s for s in q['state_refs'] if s['record']['method']==consumer.METHODS[family][1] and day in s['eligible_dates']]
            if len(state)!=1:raise ValueError('ONE_NATIVE_STATE_PER_ROLE_DATE')
            s=state[0];record=s['record']
            nodes.append(dict(id=role+'@'+day,candidate_id=role,family=family,method=method,signal_date=day,
                risk_state_id=record['risk_state_id'],artifact=record['artifact'],cutoff=record['cutoff'],as_of=record['as_of'],
                covariance_sha256=record.get('covariance_sha256'),full_u_sha256=q['full_u_day_sha256'][day],
                kind='deterministic_transform',name='optimizer_solve',solves=1,learned_states=0))
    if len(nodes)!=3708 or len({n['id'] for n in nodes})!=3708:raise ValueError('EXACT_FROZEN_3708_DAG')
    reused={n['risk_state_id'] for n in nodes}
    if not 0<len(reused)<=48:raise ValueError('QUALIFIED_REUSED_STATE_BOUND')
    return dict(research_id=ID,nodes=nodes,optimizer_solve_ceiling=3708,optimizer_solve_hard_cap=12000,
        reused_risk_states=len(reused),nominal_native_state_headers=48,new_learned_states=0,learned_state_hard_cap=2400,scientific_retry=0,
        failed_reservations_refunded=False,D01_identity_diagnostic_solve_calls=0,
        D12=dict(status='BLOCKED_BUDGET',bootstrap_draws=500,block_sessions=20,seed=20260928,
            minimum_partial_solves=194*500,complete_primary_solves=732*500,one_role_states_lower_bound=12*500))


def material_sources():
    rel=['scripts/common/storage_paths.py','config/storage_paths.json',
        'scripts/research/a2/training/selector_constrained_risk.py',
        'scripts/research/a2/data/selector_shared_risk_consumer.py',
        'scripts/research/a2/data/selector_constrained_outcomes.py',
        'scripts/research/a2/factors/selector_constrained_membership.py',
        'scripts/research/a2/evaluation/selector_constrained_evidence.py',
        'scripts/research/a2/evaluation/selector_constrained_delivery.py',
        'scripts/research/a2/training/selector_classical_risk.py',
        'scripts/research/a2/evaluation/selector_classical_evidence.py',
        'scripts/research/a2/evaluation/selector_evidence.py',
        'scripts/research/a2/evaluation/selector_account_compare.py',
        'scripts/research/a2/training/selector_challenge.py',
        'scripts/research/a2/evaluation/joint_frozen_history_risk_r3.py',
        'scripts/research/a2/data/shared_risk_inputs_r3.py',
        'scripts/research/a2/risk/shared_risk_engine_r2.py',
        'scripts/research/a2/risk/shared_risk_budget_r2.py',
        'scripts/research/a2/risk/shared_risk_extensions_r2.py',
        'scripts/research/a2/risk/short_history_risk_r4.py',
        'scripts/research/a2/risk/joint_risk_estimators.py',
        'scripts/research/a2/portfolio/joint_allocation_methods.py',
        'scripts/research/a2/retained/a2_predict_then_optimize_20260928_r1/optimizers.py',
        'tests/research/a2/training/test_selector_constrained_risk.py',
        'tests/research/a2/data/test_selector_shared_risk_consumer.py',
        'tests/research/a2/data/test_selector_constrained_outcomes.py',
        'tests/research/a2/factors/test_selector_constrained_membership.py',
        'tests/research/a2/evaluation/test_selector_constrained_evidence.py',
        'tests/research/a2/evaluation/test_selector_constrained_delivery.py']
    # Pin reachable local imports, including original HRP and typed-state owners.
    pending=[REPO/p for p in rel];seen=set()
    while pending:
        path=pending.pop()
        if path in seen:continue
        seen.add(path)
        if path.suffix!='.py':continue
        tree=ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            names=([a.name for a in node.names] if isinstance(node,ast.Import) else
                [node.module,*[node.module+'.'+a.name for a in node.names]] if isinstance(node,ast.ImportFrom) and node.module and not node.level else [])
            for name in names:
                if not name.startswith('scripts.'):continue
                local=REPO/Path(*name.split('.')).with_suffix('.py')
                if local.exists():pending.append(local)
    return {str(p):sha(p) for p in sorted(seen)}


def prepare(root):
    root,results,cache=paths(root)
    if (root/'DESIGN_FREEZE.json').exists():raise FileExistsError('NO_REPREPARE_FROZEN')
    q=readj(results/'C13_SHARED_RISK_QUALIFICATION.json')
    if any(q['counters'].values()):raise ValueError('QUALIFICATION_MUST_HAVE_ZERO_PAYLOAD_FITS')
    dag=physical_dag(q);put(root/'PHYSICAL_DAG.json',dag)
    old=readj(C12/'DESIGN_FREEZE.json')
    c11=Path(old['evaluation']['legacy']['design']['path']).parent
    legacy=dict(evidence=ref(C12/'diagnostics/selector_evidence/SELECTION_EVIDENCE.json'),
        edge=ref(C12/'diagnostics/selector_evidence/PRIMARY_DAILY_EDGE.parquet'),
        clock=ref(C12/'diagnostics/selector_evidence/COMMON_DATE_MATURITY.parquet'),
        maxT=ref(C12/'diagnostics/selector_evidence/BOOTSTRAP_MAXT.parquet'),
        numeric_ids=old['evaluation']['legacy']['numeric_ids'],
        exposure_ids=old['evaluation']['legacy']['exposure_ids']+old['roles'],
        old_design=ref(C12/'DESIGN_FREEZE.json'),old_assembly=ref(C12/'SCORE_ASSEMBLY.json'),
        old_fit_ledger=ref(C12/'FIT_LEDGER.json'),
        control_evidence=ref(c11/'diagnostics/selector_evidence/SELECTION_EVIDENCE.json'),
        old_delivery=ref(C12/'DELIVERY_COMPLETE.json'),
        reviewed_delivery=ref('D:/us-tech-quant-results/V24/C_SELECTOR/C12_RAW_BOUNDARY/REVIEWED_DELIVERY_COMPLETE.json'),
        reviewed_report=ref('D:/us-tech-quant-results/V24/C_SELECTOR/C12_RAW_BOUNDARY/FINAL_REPORT_REVIEWED.md'))
    blocked={}
    for role in ev.ROLES:
        if role in ev.ACTIVE_ROLES:continue
        r,m=role.split('_')[1:]
        blocked[role]='BLOCKED_BUDGET_500_DRAWS_EXCEED_12000_SOLVES_2400_STATES' if m=='D12' else (
            'BLOCKED_INPUT_NO_FULL_PSD_COVARIANCE_REPLICAS' if m=='D08' else q['families'][FAMILIES[r]]['reason'])
    h5=Path('D:/us-tech-quant-results/JOINT_TOP20_PORTFOLIO_POLICY_PRE2026_TEST2026_R1/V24/cache/five_day_shareholder_targets.parquet')
    ai=Path('D:/us-tech-quant-results/A2_STATEFUL_ACTION_AND_CASH_PRE2026_TEST2026_R1/cache')
    d=dict(research_id=ID,official_freeze=True,formal_freeze_applied=True,roles=list(ev.ROLES),active_roles=list(ev.ACTIVE_ROLES),
        blocked_roles=blocked,target=ev.TARGET,primary_eval_years=list(ev.YEARS),
        mechanism_research_eligible=True,strict_PIT_promotion_eligible=False,test2026_locked=True,new2026_estimation_authorized=False,
        independent_holdout=False,development_status='EXPOSED_PRE2026_DEVELOPMENT',source_contract_mode='FROZEN_HISTORY_MECHANISM_ONLY',
        raw_score=q['spec']['raw_keys'],risk_qualification=ref(results/'C13_SHARED_RISK_QUALIFICATION.json'),
        physical_dag=ref(root/'PHYSICAL_DAG.json'),sources=material_sources(),membership=rules.specification(),
        no_cross_identity_stitching=True,full_U_policy='Exact whole domain on qualified dates; no padding or date-calendar shrink',
        horizon='NATIVE_STOCK_H5_ONLY; no sqrt scaling or target change',risk_cadence='NATIVE_PRODUCER_ONLY',seed_policy=[20260928],configs_per_role=1,
        D01='Identity diagnostic: monotone Raw rank objective returns Raw20; zero solve',
        evaluation=dict(primary='MEAN_REPLACEMENT_EDGE',common_mature_date_count=732,original_calendar_dates=752,year_counts=ev.YEAR_COUNTS,
            legacy_numeric=147,legacy_exposure=178,legacy_failed=31,exposure_namespace=226,new_numeric=0,partial_only=True,
            risk_efficiency_support_requires_full732=True,risk_efficiency_alpha_noninferiority_margin=0,
            risk_efficiency_gate='Complete732; simultaneous alphaLB>=0 and risk improvementLB>0; predicted+realized risk lower; >=2of3years',
            bootstrap=dict(draws=5000,block=20,seed=20260928,method=ev.BOOT_METHOD,confidence=.95),legacy=legacy),
        budget=dict(new_learned_state_hard_cap=2400,new_learned_state_active=0,optimizer_solve_hard_cap=12000,optimizer_solve_active_ceiling=3708,
            scientific_retry=0,failures_refunded=False,role_ceiling=48),
        h5_sources=dict(labels=ref(h5),identity=ref(ai/'value_training_panel_shareholder_pitguarded_r1.parquet'),
            membership=ref('D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1/universe/daily_eligible_universe_membership.parquet'),calendar=ref(ai/'calendar_r1.parquet')),
        controls=dict(RAW_TOP20=q['spec']['raw_keys'],
            C11_PARETO=ref(c11/'predictions/scores_C11_A8_PARETO_ALPHA_RISK_pre2026.parquet'),
            C11_MINVOL=ref(c11/'predictions/scores_C11_SANITY_MIN_VOL_pre2026.parquet')),
        pre_freeze_fit_calls=0,pre_freeze_state_estimations=0,pre_freeze_outcome_reads=0,
        user_authorization=dict(path='C:/Users/Lenovo/.codex/attachments/03ac7653-0ac7-4a01-b218-de1c6869cb28/已粘贴的文本.txt',scope='Explicit independent C13 classical risk membership formulation; existing shared owner exact consumption'),
        canonical_registry_status='AUTOMATIC_DECISION_PRESERVED_SEPARATE_HUMAN_C13_FORMULATION',
        c6a='BLOCKED_INPUT',c8='BLOCKED_DEPENDENCY',c11b='BLOCKED_SHARED_RISK',frozen_at=now())
    ev.validate_design(d)
    put(root/'DESIGN_PROPOSAL.json',d)
    proposal=dict(candidate=dict(entity_id=ID,canonical_name=ID,entity_type='RESEARCH_BRANCH',status='OPEN',aliases=[],
        parent_entity_id='RAW_A2_HGB_BASELINE',decision_layer='PURE_SELECTOR',information_family='canonical_raw_score',
        information_source_fingerprint='2381b2d70d63755a4f51e32da048586029db41a234bb2182eb9a7851101bbc15',
        specification=dict(target=ev.TARGET,role_ids=list(ev.ROLES),native_horizon=5,raw_anchor=10,boundary=30,final=20,
            learned_cap=2400,solve_cap=12000,active_solves=3708,active_learned=0,scientific_retry=0),
        mechanism=dict(question='Can explicit covariance-aware classical membership rules improve fixed Raw Top20 boundary?',
            score_coordinate='FIXED_RAW_ORDINAL',formulation='RISK_CONSTRAINED_EQUAL_MEMBERSHIP',new_predictor=False,new_target=False,
            closed_preserved=['R4','R5','C7','C10','C11','C12']),
        metadata=dict(fit_authority=False,formal_freeze_authority=False,test2026_locked=True,strict_PIT_promotion_eligible=False),
        authoritative_artifact_refs=[str(root/'DESIGN_PROPOSAL.json')]),
        change_type='EXPLICIT_HUMAN_NEW_RISK_CONSTRAINED_CLASSICAL_MEMBERSHIP_FORMULATION',parent_entity_id='RAW_A2_HGB_BASELINE')
    put(results/'REGISTRY_PROPOSAL.json',proposal)
    print(json.dumps(dict(phase='DESIGN_PROPOSAL',solves=3708,learned=0,roles=48,active=24)),flush=True)


def seal(root):
    root,results,_=paths(root);proposal_path=root/'DESIGN_PROPOSAL_REVIEWED.json'
    d=readj(proposal_path)
    audit=readj(results/'FORMAL_FREEZE_INDEPENDENT_AUDIT.json');test=readj(root/'SYNTHETIC_VALIDATION.json')
    if audit.get('status')!='PASS' or audit.get('proposal_sha256')!=sha(proposal_path) or test.get('status')!='PASS':
        raise ValueError('INDEPENDENT_PROPOSAL_AND_SYNTHETIC_PASS_REQUIRED')
    if (root/'DESIGN_FREEZE.json').exists():raise FileExistsError('NO_REFREEZE')
    ev.validate_design(d)
    for p,h in d['sources'].items():pin(dict(path=p,sha256=h))
    for item in [d['raw_score'],d['risk_qualification'],d['physical_dag'],*d['h5_sources'].values(),*d['controls'].values()]:pin(item)
    for p,h in d['sources'].items():
        dest=root/'source_snapshot'/Path(p).relative_to(REPO)
        assert_safe_output_path(dest,kind='backtest');dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():raise FileExistsError('PRESERVE_SNAPSHOT')
        shutil.copyfile(p,dest)
        if sha(dest)!=h:raise ValueError('SNAPSHOT_PIN_MISMATCH')
    put(root/'DESIGN_FREEZE.json',d)
    review=dict(status='PASS',research_id=ID,design_sha256=sha(root/'DESIGN_FREEZE.json'),source_pins=d['sources'],
        independent_audit=ref(results/'FORMAL_FREEZE_INDEPENDENT_AUDIT.json'),synthetic_validation=ref(root/'SYNTHETIC_VALIDATION.json'),
        registry_preflight=ref(results/'REGISTRY_PREFLIGHT.json'),dag=d['physical_dag'],
        before_execution=dict(fits=0,state_estimations=0,optimizer_solves=0,outcome_reads=0))
    put(root/'FORMAL_FREEZE_REVIEW.json',review)
    put(root/'DESIGN_FREEZE_SHA.json',dict(sha256=sha(root/'DESIGN_FREEZE.json'),formal_review_sha256=sha(root/'FORMAL_FREEZE_REVIEW.json')))
    print(json.dumps(dict(phase='FORMAL_FREEZE',status='PASS',sha=sha(root/'DESIGN_FREEZE.json'))),flush=True)


def checked(root):
    root,results,cache=paths(root);d=readj(root/'DESIGN_FREEZE.json');manifest=readj(root/'DESIGN_FREEZE_SHA.json')
    ev.validate_design(d)
    review=readj(root/'FORMAL_FREEZE_REVIEW.json')
    if manifest['sha256']!=sha(root/'DESIGN_FREEZE.json') or manifest['formal_review_sha256']!=sha(root/'FORMAL_FREEZE_REVIEW.json'):
        raise ValueError('FROZEN_DESIGN_CHANGED')
    if review['status']!='PASS' or review['design_sha256']!=manifest['sha256'] or review['source_pins']!=d['sources']:
        raise ValueError('REVIEW_PIN_MISMATCH')
    for p,h in d['sources'].items():
        pin(dict(path=p,sha256=h))
        if sha(root/'source_snapshot'/Path(p).relative_to(REPO))!=h:raise ValueError('FROZEN_SNAPSHOT_CHANGED')
    for k in ('risk_qualification','physical_dag','raw_score'):pin(d[k])
    return root,results,cache,d


def membership_panel(g,chosen,role):
    uids=list(g.sort_values('rank',kind='stable').security_uid)
    ordered=[u for u in uids if u in set(chosen)]+[u for u in uids if u not in set(chosen)]
    if len(chosen)!=20 or len(set(chosen))!=20 or not set(uids[:10]).issubset(chosen) or not set(chosen).issubset(uids[:40]):
        raise ValueError('CORE_BOUNDARY_MEMBERSHIP_INVALID')
    p=g[KEYS].copy();rank={u:i+1 for i,u in enumerate(ordered)}
    p['rank']=p.security_uid.map(rank).astype('int64');p['score']=-p['rank'].astype(float);p['candidate_id']=role
    shared.validate_rank(p)
    return p


def validate_terminal_solver(dag,ledger,assembly):
    planned=[n['id'] for n in dag['nodes']];events=ledger['events'];ids=[e['key'] for e in events]
    if (len(planned)!=3708 or len(ids)!=len(set(ids)) or set(ids)!=set(planned)
        or ledger['learned_total']!=0 or ledger.get('new_state_estimations',0)!=0
        or ledger.get('charged_reservations')!=len(planned)
        or ledger.get('actual_solver_calls')!=sum(e.get('backend_entered',False) for e in events)
        or ledger.get('success_count')!=sum(e['status']=='SUCCEEDED' for e in events)
        or ledger.get('failed_count')!=sum(e['status']=='FAILED' for e in events)
        or ledger.get('counts',{}).get('deterministic_transform')!=len(planned)):
        raise ValueError('EXACT_TERMINAL_DAG_LEDGER_REQUIRED')
    for event in events:
        if event['status'] not in ('SUCCEEDED','FAILED') or type(event.get('backend_entered')) is not bool:
            raise ValueError('EXACT_TERMINAL_DAG_LEDGER_REQUIRED')
        if event['status']=='SUCCEEDED' and not event['backend_entered']:
            raise ValueError('SUCCEEDED_SOLVER_MUST_HAVE_ENTERED')
    if (assembly.get('complete_candidates')!=[] or not set(assembly.get('panels',{})).issubset(ev.ACTIVE_ROLES)
        or set(assembly.get('failed_or_untestable',{}))!=set(ev.ROLES)):
        raise ValueError('ALL48_EXPOSURES_NO_COMPLETE_PRIMARY_REQUIRED')


def decision_gate(root,d,assembly,ledger,requested):
    validate_terminal_solver(readj(pin(d['physical_dag'])),ledger,assembly)
    return dict(schema='C13_POSTDECISION_H5_GATE_V1',status='PASS',research_id=ID,
        design_sha256=sha(root/'DESIGN_FREEZE.json'),review_sha256=sha(root/'FORMAL_FREEZE_REVIEW.json'),decision_frozen=True,
        outcome_reads_before_gate=0,requested_keys_sha256=content_hash(requested.sort_values(shared.KEY).reset_index(drop=True)),
        score_assembly_ref=ref(root/'SCORE_ASSEMBLY.json'),solve_ledger_ref=ref(root/'SOLVE_LEDGER.json'),
        fit_ledger_ref=ref(root/'FIT_LEDGER.json'),optimizer_receipts_ref=ref(root/'derived/OPTIMIZER_RECEIPTS.json'),all_decisions_terminal=True,
        requested_keys_ref=ref(root/'derived/H5_REQUEST_KEYS.parquet'),strict_PIT_promotion_eligible=False)


def validate_postdecision_gate(root,d):
    gate=readj(root/'FINAL_DECISIONS_FREEZE.json')
    if (gate.get('status')!='PASS' or gate.get('research_id')!=ID or gate.get('decision_frozen') is not True
        or gate.get('all_decisions_terminal') is not True or gate.get('outcome_reads_before_gate')!=0
        or gate.get('design_sha256')!=sha(root/'DESIGN_FREEZE.json')
        or gate.get('review_sha256')!=sha(root/'FORMAL_FREEZE_REVIEW.json')):
        raise ValueError('NO_OUTCOME_BEFORE_VERIFIED_TERMINAL_GATE')
    pinned={k:pin(gate[k]) for k in ('score_assembly_ref','solve_ledger_ref','fit_ledger_ref','requested_keys_ref','optimizer_receipts_ref')}
    ledger=readj(pinned['solve_ledger_ref']);assembly=readj(pinned['score_assembly_ref']);fit=readj(pinned['fit_ledger_ref'])
    validate_terminal_solver(readj(pin(d['physical_dag'])),ledger,assembly)
    if fit.get('new_learned_states')!=0 or fit.get('new_backend_fit_calls')!=0:raise ValueError('NO_NEW_FITS_IN_THIS_DAG')
    keys=pd.read_parquet(pinned['requested_keys_ref']).sort_values(shared.KEY).reset_index(drop=True)
    if gate['requested_keys_sha256']!=content_hash(keys):raise ValueError('REQUESTED_KEYS_CHANGED_BEFORE_Y')
    records=readj(pinned['optimizer_receipts_ref'])['records']
    successes={e['key'] for e in ledger['events'] if e['status']=='SUCCEEDED'}
    receipts=[r['candidate_id']+'@'+r['signal_date'] for r in records]
    if len(receipts)!=len(set(receipts)) or set(receipts)!=successes:raise ValueError('SUCCESS_RECEIPT_DAG_BINDING')
    for item in assembly['panels'].values():pin(item)
    return gate


def execute(root):
    root,results,cache,d=checked(root)
    if (root/'EXECUTION_START.json').exists():raise FileExistsError('NO_DUPLICATE_EXECUTE_NO_SCIENTIFIC_RETRY')
    put(root/'EXECUTION_START.json',dict(research_id=ID,at=now(),pid=os.getpid(),design_sha256=sha(root/'DESIGN_FREEZE.json')))
    q=readj(pin(d['risk_qualification']));dag=readj(pin(d['physical_dag']))
    raw=raw_geometry(pre2026(pin(d['raw_score']),KEYS+['score','rank'],'signal_date'))
    groups={t:g.reset_index(drop=True) for t,g in raw.groupby('signal_date',sort=True)}
    artifacts={};state_cache={};receipts=[];failures=[]
    def journal(event):
        p=root/'logs/optimizer_calls.jsonl';assert_safe_output_path(p,kind='backtest')
        with p.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(event,default=str,allow_nan=False)+'\n');stream.flush();os.fsync(stream.fileno())
    budget=StateBudget(2400,limits={'deterministic_transform':12000},reserve_callback=journal)
    assembly=dict(research_id=ID,partial_candidates=[],complete_candidates=[],failed_or_untestable=dict(d['blocked_roles']),panels={})
    for role in ev.ACTIVE_ROLES:
        nodes=[n for n in dag['nodes'] if n['candidate_id']==role];panels=[]
        for node in nodes:
            g=groups[pd.Timestamp(node['signal_date'])];at=consumer.decision_close(node['signal_date'])
            s,order=consumer.admit_state(q,node['family'],g,at);sid=node['risk_state_id']
            event=budget.reserve(node['id'],'deterministic_transform','optimizer_solve',
                dict(synthetic=False,mechanism=True,research_id=ID,decision_at=at.isoformat(),full_u_sha256=node['full_u_sha256']),
                node['artifact']['sha256'],dict(method=node['method'],family=node['family'],risk_state_id=sid,membership=d['membership']))
            event['backend_entered']=False
            try:
                if sid not in state_cache:
                    state,loaded=consumer.load_state(node['family'],design_ref=ref(root/'DESIGN_FREEZE.json'),
                        review_ref=ref(root/'FORMAL_FREEZE_REVIEW.json'),qualification_ref=d['risk_qualification'],current_u=g,decision_at=at)
                    state_cache[sid]=(state,loaded)
                state,loaded=state_cache[sid]
                if loaded['ordered_consumer_uids']!=order['ordered_consumer_uids']:raise ValueError('STATE_CACHE_IDENTITY_CHANGED')
                top=g.sort_values('rank',kind='stable').iloc[:40];uids=list(top.security_uid)
                ix=[order['ordered_consumer_uids'].index(u) for u in uids]
                cov=np.asarray(state.covariance)[np.ix_(ix,ix)]
                event['backend_entered']=True;journal(event)
                out=rules.select(node['method'],cov,uids,uids,list(top['rank']),decision_at=at,state_cutoff=state.cutoff)
                panels.append(membership_panel(g,out['chosen_uids'],role))
                receipts.append(dict(candidate_id=role,signal_date=node['signal_date'],risk_state_id=sid,
                    predicted_risk=out['predicted_risk'],alpha_sacrifice=out['alpha_sacrifice'],receipt=out['receipt']))
                event.update(status='SUCCEEDED',result_sha256=content_hash(out));journal(event)
            except Exception as exc:
                event.update(status='FAILED',exception_type=type(exc).__name__,error=str(exc));journal(event)
                failures.append(dict(slot=node['id'],candidate_id=role,error=str(exc)))
        if panels:
            path=root/'predictions'/('scores_'+role+'_pre2026.parquet');assert_safe_output_path(path,kind='backtest')
            if path.exists():raise FileExistsError('PRESERVE_PANEL')
            pd.concat(panels,ignore_index=True).sort_values(shared.KEY).to_parquet(path,index=False)
            assembly['partial_candidates'].append(role);assembly['panels'][role]=dict(**ref(path),dates=len(panels),full_U_preserved=True)
        assembly['failed_or_untestable'][role]='NO_COMPLETE_COMMON_732_NATIVE_SHARED_STATE; descriptive only'
        shared.putj(root/'PIPELINE_STATE.json',dict(research_id=ID,phase='OPTIMIZER_EXECUTION',last_role=role,
            optimizer_solves=budget.counts['deterministic_transform'],new_risk_fits=0,outcome_reads=0,at=now()))
        print(json.dumps(dict(role=role,dates=len(panels),solves=budget.counts['deterministic_transform'],failures=len(failures))),flush=True)
    ledger=budget.snapshot();ledger.update(research_id=ID,design_sha256=sha(root/'DESIGN_FREEZE.json'),failures=failures,
        backend_entered_count=sum(e.get('backend_entered',False) for e in ledger['events']),
        actual_solver_calls=sum(e.get('backend_entered',False) for e in ledger['events']),charged_reservations=len(ledger['events']),
        success_count=sum(e['status']=='SUCCEEDED' for e in ledger['events']),failed_count=sum(e['status']=='FAILED' for e in ledger['events']),
        reused_state_ids=sorted(state_cache),reused_state_count=len(state_cache),new_state_estimations=0)
    ledger['membership_deterministic_transform_calls']=sum(r['receipt']['deterministic_transform_calls'] for r in receipts)
    ledger['bootstrap_estimations']=0;ledger['bootstrap_optimizer_solves']=0
    put(root/'SOLVE_LEDGER.json',ledger)
    put(root/'FIT_LEDGER.json',dict(research_id=ID,new_learned_states=0,new_backend_fit_calls=0,base_refits=0,calibration_refits=0,
        counts={k:0 for k in ('DIAG','Sample','LW','OAS','CC','EWMA','PCA','factor','QQQ','FF48','GARCH','GJR','downside','CVaR','regime','jackknife','disagreement','posterior','EB')},
        reused_states_by_family={f:len({n['risk_state_id'] for n in dag['nodes'] if n['family']==f}) for f in consumer.METHODS},
        learned_state_hard_cap=2400,charged_learned_reservations=0,scientific_retry=0))
    put(root/'SCORE_ASSEMBLY.json',assembly);put(root/'derived/OPTIMIZER_RECEIPTS.json',dict(records=receipts))
    requested=[]
    for role,info in assembly['panels'].items():
        p=pre2026(pin(info),KEYS+['rank'],'signal_date');joined=raw.merge(p[shared.KEY+['rank']],on=shared.KEY,suffixes=('_raw','_new'),how='inner',validate='one_to_one')
        requested.append(joined.loc[joined.rank_raw.le(20)|joined.rank_new.le(20),shared.KEY+['ticker']])
    requested=pd.concat(requested,ignore_index=True).drop_duplicates(shared.KEY).sort_values(shared.KEY).reset_index(drop=True) if requested else raw.iloc[:0][shared.KEY+['ticker']]
    requested.to_parquet(root/'derived/H5_REQUEST_KEYS.parquet',index=False)
    gate=decision_gate(root,d,assembly,ledger,requested);put(root/'FINAL_DECISIONS_FREEZE.json',gate)
    print(json.dumps(dict(phase='FINAL_DECISIONS_FREEZE',status='PASS',solves=len(ledger['events']),new_fit=0)),flush=True)
    evaluate(root,d,raw,q,state_cache,receipts)
    from scripts.research.a2.evaluation.selector_constrained_delivery import delivery
    delivery(root)


def evaluate(root,d,raw,q,state_cache,receipts):
    root,results,_=paths(root);gate=validate_postdecision_gate(root,d)
    assembly=readj(pin(gate['score_assembly_ref']))
    if assembly['panels']:
        shared.prove_label_boundary(pin(d['raw_score']),'label_end_date',allow_null=True)
        labels=pre2026(pin(d['raw_score']),shared.KEY+['target','label_end_date'],'signal_date')
        raw=raw.merge(labels,on=shared.KEY,how='left',validate='one_to_one')
    raw['raw_rank']=raw['rank']
    old=d['evaluation']['legacy'];old_evidence=readj(pin(old['evidence']))
    clock=pre2026(pin(old['clock']),['signal_date','included'],'signal_date')
    from scripts.research.a2.data.selector_constrained_outcomes import read_h5
    requested=pd.read_parquet(pin(gate['requested_keys_ref']))
    if len(requested):
        realized,h5_receipt=read_h5(ref(root/'DESIGN_FREEZE.json'),ref(root/'FORMAL_FREEZE_REVIEW.json'),ref(root/'FINAL_DECISIONS_FREEZE.json'),requested)
    else:
        realized=pd.DataFrame(columns=shared.KEY+['return_value','qualified'])
        h5_receipt=dict(status='BLOCKED_NO_REQUESTED_KEYS',research_id=ID,source_refs=d['h5_sources'],
            numeric_origin_keys=0,qualified_finite_keys=0,blocked_keys=0,new_fits=0,new_state_estimations=0,
            outcome_reads_before_gate=0,test2026_reads=0,strict_PIT_promotion_eligible=False)
    put(results/'REALIZED_H5_SOURCE_RECEIPT.json',h5_receipt)
    assembly=readj(root/'SCORE_ASSEMBLY.json');summaries=[];all_daily=[];all_risk=[]
    for role,info in assembly['panels'].items():
        p=pre2026(pin(info),KEYS+['rank','score','candidate_id'],'signal_date')
        daily=ev.daily_diagnostics(role,raw,p,clock);pred={}
        family=FAMILIES[role.split('_')[1]]
        for day,g in p.groupby('signal_date'):
            s,order=consumer.admit_state(q,family,g,consumer.decision_close(day));state,_=state_cache[s['record']['risk_state_id']]
            pred[day]=dict(covariance=state.covariance,asset_uids=order['ordered_consumer_uids'])
        risk,risk_summary=ev.risk_diagnostics(role,raw,p,clock,realized_h5=realized,predicted_risk=pred)
        rr=[r for r in receipts if r['candidate_id']==role]
        mature=daily.loc[daily.common_mature_date]
        summary=dict(candidate_id=role,status='PARTIAL_DESCRIPTIVE',applicable_dates=len(daily),common_mature_dates=len(mature),
            mean_edge_bp=float(mature.replacement_edge.mean()*10000) if len(mature) else None,
            edge_by_year_bp={str(y):float(g.replacement_edge.mean()*10000) for y,g in mature.groupby('year')},
            mean_predicted_variance_ratio=float(np.mean([r['predicted_risk']['variance']/r['predicted_risk']['raw_variance'] for r in rr if r['predicted_risk']['raw_variance']>0])),
            mean_raw_overlap=float(daily.raw_overlap.mean()),mean_replacements=float(daily.replacement_count.mean()),
            mean_raw_rank_sacrifice=float(np.mean([r['alpha_sacrifice']['rank_loss'] for r in rr])),realized_summary=risk_summary,
            calibration='Realized H5 basket variance divided by mean predicted H5 variance: descriptive, overlap/mean/bias retained; no recalibration fit',
            pooled_primary_edge=None,simultaneous_lower95=None,selector_supported=False,risk_efficiency_supported=False)
        summaries.append(summary);all_daily.append(daily);all_risk.append(risk)
    diag=root/'diagnostics/selector_evidence';diag.mkdir(parents=True,exist_ok=True)
    for name,frames in [('PARTIAL_DAILY_DIAGNOSTICS',all_daily),('RISK_DAILY_DIAGNOSTICS',all_risk)]:
        pd.concat(frames,ignore_index=True).to_parquet(diag/(name+'.parquet'),index=False) if frames else None
    tests,boot=ev.reuse_statistics(old_evidence['bootstrap'],old['numeric_ids'],old['exposure_ids'],failed=assembly['failed_or_untestable'])
    evidence=dict(status='C13_PARTIAL_SHARED_RISK_BLOCKED',research_id=ID,tests=tests,bootstrap=boot,legacy=old,
        common_mature_date_count=732,original_calendar_dates=752,numeric_complete_series=147,new_numeric=0,new_numeric_complete_series=0,exposure_namespace=226,complete_common_732_candidates=[],
        supported=[],risk_efficiency_supported=[],finalist='FINALIST_NONE',promotion='NO_PROMOTION',
        mechanism_research_eligible=True,strict_PIT_promotion_eligible=False,test2026_locked=True,
        outcome2026_reads=0,fit2026_rows=0,new2026_state_estimations=0,evaluation2026_rows=0)
    put(results/'ROLE_DESCRIPTIVE_SUMMARY.json',dict(roles=summaries));put(results/'SELECTION_EVIDENCE.json',evidence)
    controls=[]
    control_evidence=readj(pin(old['control_evidence']))
    for name,item in d['controls'].items():
        # Old numeric/control output is opened only after C13 decisions are sealed.
        controls.append(dict(name=name,artifact=item,exact_reuse=True,new_fit=0,new_exposure=False,
            old_statistics=[t for t in control_evidence.get('tests',[]) if t.get('candidate_id') in ('C11_A8_PARETO_ALPHA_RISK','C11_SANITY_MIN_VOL')]) )
    put(results/'CONTROL_REUSE.json',dict(controls=controls,C11_reselected=False))
    protected=dict(d['sources'])
    refs=[d['raw_score'],d['risk_qualification'],*d['h5_sources'].values(),*d['controls'].values(),
        *q['spec'].values(),*[v for v in old.values() if isinstance(v,dict) and 'path' in v]]
    refs += [s['record']['source_contract'] for s in q['state_refs']]
    reused=set(readj(root/'SOLVE_LEDGER.json')['reused_state_ids'])
    refs += [s['record']['artifact'] for s in q['state_refs'] if s['record']['risk_state_id'] in reused]
    for item in refs:
        p,h=item['path'],item['sha256']
        if p in protected and protected[p]!=h:raise ValueError('CONFLICTING_SOURCE_PIN')
        protected[p]=h
    checks=[]
    for p,h in protected.items():
        actual=sha(p);checks.append(dict(path=p,expected_sha256=h,observed_sha256=actual,unchanged=actual==h))
    if not all(c['unchanged'] for c in checks):raise ValueError('SOURCE_OR_C12_PRESERVATION_FAILED')
    put(results/'SOURCE_PRESERVATION.json',dict(status='PASS',checks=checks,no_C_business_output=True,no_EF_access=True,no_provider_fetch=True,
        no_canonical_data_write=True,C12_unchanged=True,resolved_roots={k:str(v) for k,v in asdict(resolve(REPO)).items()}))
    ledger=readj(root/'SOLVE_LEDGER.json')
    execution=dict(research_id=ID,status='C13_PARTIAL_SHARED_RISK_BLOCKED',design=ref(root/'DESIGN_FREEZE.json'),
        final_gate=ref(root/'FINAL_DECISIONS_FREEZE.json'),ledger=ref(root/'SOLVE_LEDGER.json'),assembly=ref(root/'SCORE_ASSEMBLY.json'),
        success_solves=ledger['success_count'],failed_solves=ledger['failed_count'],new_learned_states=0,reused_state_count=ledger['reused_state_count'],
        completed_at=now(),evaluation=ref(results/'SELECTION_EVIDENCE.json'),summary=ref(results/'ROLE_DESCRIPTIVE_SUMMARY.json'),
        C12_unchanged=True,mechanism_research_eligible=True,strict_PIT_promotion_eligible=False,read2026=0,fit2026=0,state2026=0,evaluation2026=0)
    put(results/'EXECUTION_RECEIPT.json',execution);put(root/'EXECUTION_RECEIPT.json',execution)
    shared.putj(root/'PIPELINE_STATE.json',dict(research_id=ID,phase='EVALUATION_COMPLETE',status=execution['status'],at=now(),optimizer_solves=len(ledger['events']),new_fit=0,test2026_reads=0))


def main():
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['prepare','seal','execute']);p.add_argument('--run',default=str(RUN));a=p.parse_args()
    globals()[a.phase](safe_d(a.run))

if __name__=='__main__':main()