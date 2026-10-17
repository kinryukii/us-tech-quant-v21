"""C12 Raw-anchored pair learning; bounded adapters, not a new selector platform.

Label-free geometry is sealed before labels. An unresolved early full-U tie
identity blocks 2023/24; all nine independently applicable 2025 paradigms run.
"""
from __future__ import annotations
import argparse, hashlib, json, os, platform, shutil, time, traceback
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.preprocessing import StandardScaler
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.training.selector_classical_risk import safe_d, pin, put
from scripts.research.a2.training.selector_challenge import runtime, now, sha, readj, putj
from scripts.research.a2.factors import selector_boundary_pairs as pairs
from scripts.research.a2.training import selector_boundary_estimators as est
from scripts.research.a2.evaluation import selector_evidence as shared
from scripts.research.a2.evaluation.selector_account_compare import pre2026

REPO = Path(__file__).resolve().parents[4]
RESEARCH_ID = 'V24_C_SELECTOR_RAW_ANCHORED_BOUNDARY_DECISION_LEARNING_C12'
C11 = Path('D:/us-tech-quant-backtests/V24/20261003T173443+0000_ed37eea6')
CUTS = ('2024-01-01','2024-07-01','2025-01-01')
KEY = ['signal_date','security_uid']
GAP = 'BLOCKED_INPUT_EARLY_FULL_U_RAW_TIE_IDENTITY'
EXPECTED_DATES = (230,354,482)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()


def components(paradigm):
    return [(s,None) for s in est.SEEDS] if paradigm in est.STOCHASTIC else (
        [(est.SEEDS[0],q) for q in est.QUANTILES] if paradigm=='QUANTILE_HGB' else [(est.SEEDS[0],None)])


def physical_dag():
    slots = [dict(id='SCALER_'+c,kind='scaler',cutoff=c) for c in CUTS]
    for c in CUTS[:2]:
        for p in est.PARADIGMS:
            for cap in est.CAPACITIES:
                for seed,q in components(p):
                    slots.append(dict(id=f'{c}_{p}_{cap}_{seed}_{q}',kind='estimator',cutoff=c,paradigm=p,capacity=cap,seed=seed,quantile=q))
    for p in est.PARADIGMS:
        for seed,q in components(p):
            slots.append(dict(id=f'OUTER_{p}_{seed}_{q}',kind='estimator',cutoff=CUTS[2],paradigm=p,capacity='SELECTED_PAST_INNER',seed=seed,quantile=q))
    assert len(slots)==122 and sum(s['kind']=='estimator' for s in slots)==119
    return dict(active_slots=slots,active_physical_ceiling=122,hard_cap=380,scientific_retry=0,
        blocked_outer_head_years=18,blocked_nominal_estimator_slots=238,blocked_nominal_scaler_slots=6,
        blocked_nominal_slots_are_not_reservations=True,full_naive_reference=366)


def paths(root):
    root=safe_d(root); assert_safe_output_path(root,kind='backtest')
    cfg=readj(root/'run_config.json')
    if cfg['research_id']!=RESEARCH_ID: raise ValueError('EXACT_C12_RUN_REQUIRED')
    for k,kind in [('results_directory','results'),('cache_directory','cache')]:
        assert_safe_output_path(safe_d(cfg[k]),kind=kind)
    return cfg


def frame_from_pins(d):
    raw=pre2026(pin(d['raw_score']),KEY+['ticker','U_t_fingerprint','score','rank'],'signal_date')
    f=pre2026(pin(d['features']),['signal_date','ticker',*pairs.BASE32],'signal_date')
    for a in (raw,f): a['signal_date']=pd.to_datetime(a.signal_date)
    if f.duplicated(['signal_date','ticker']).any(): raise ValueError('DUPLICATE_SOURCE_FEATURE_KEYS')
    raw=raw.rename(columns={'score':'raw_score','rank':'raw_rank'}).sort_values(KEY).reset_index(drop=True)
    out=raw.merge(f,on=['signal_date','ticker'],how='left',validate='one_to_one')
    if len(out)!=313668 or out.signal_date.nunique()!=752 or not np.isfinite(out[list(pairs.BASE32)].to_numpy(float)).all():
        raise ValueError('FULL_U_FINITE_BASE32_REQUIRED_NO_SHRINK')
    if not out[KEY].equals(raw[KEY]): raise ValueError('FULL_U_KEY_PRESERVATION')
    return pairs.add_history(out,pd.DatetimeIndex(sorted(out.signal_date.unique())))


def prepare(root):
    """No y values, label clock or fit. Immutable pair and X receipts first."""
    cfg=paths(root); old=readj(C11/'DESIGN_FREEZE.json')
    if sha(C11/'DESIGN_FREEZE.json')!='3a9e24914e7329da83e9d768cdd584519f75607c6e1793d0e92fabacb5edf70d': raise ValueError('C11_FREEZE_CHANGED')
    d={k:old[k] for k in ('features','raw_score')}
    if (root/'PAIR_GEOMETRY_FREEZE.json').exists():
        receipt=readj(root/'PAIR_GEOMETRY_FREEZE.json')
        pin(receipt['pairs']);pin(receipt['features']);pin(receipt['frame']); return receipt
    out=frame_from_pins(d); geometry=pairs.geometry(out)
    feature=pairs.pair_features(out,geometry,pairs.BASE32)
    receipt=dict(status='PAIR_GEOMETRY_FROZEN_BEFORE_LABEL_VALUES',research_id=RESEARCH_ID,
        pair_key_sha256=pairs.pair_key_sha256(geometry),feature_order=list(pairs.feature_order(pairs.BASE32)),
        feature_order_sha256=digest(list(pairs.feature_order(pairs.BASE32))),pairs_count=len(geometry),dates=752,
        feature_rows=len(feature),feature_columns=114,target_values_read=0,fit_calls=0,
        geometry_policy='RAW21_40_X_RAW11_20_EXACT_200',source_pins=d,created_at=now(),
        history_policy='PREVIOUS_LEGAL_CALENDAR_SESSION_SAME_UID_ONLY',missing_encoding='ZERO_PLUS_TWO_FLAGS')
    for name,value,key in [('boundary_pairs.parquet',geometry,'pairs'),('pair_features.parquet',feature,'features'),('raw_features.parquet',out,'frame')]:
        p=safe_d(root/'derived'/name);assert_safe_output_path(p)
        if p.exists():raise FileExistsError('PRESERVE_PARTIAL_PREPARATION')
        value.attrs={};value.to_parquet(p,index=False);receipt[key]=dict(path=str(p),sha256=sha(p))
    put(root/'PAIR_GEOMETRY_FREEZE.json',receipt)
    print(json.dumps(dict(phase='LABEL_FREE_PAIR_FREEZE',pairs=len(geometry),sha=receipt['pair_key_sha256'],fits=0,y_reads=0)),flush=True)
    return receipt


def freeze(root):
    cfg=paths(root); receipt=readj(root/'PAIR_GEOMETRY_FREEZE.json')
    if receipt['target_values_read']!=0 or receipt['pairs_count']!=150400: raise ValueError('PAIR_BEFORE_Y_REQUIRED')
    if (root/'DESIGN_FREEZE.json').exists(): raise FileExistsError('NO_REFREEZE')
    validation=readj(root/'SYNTHETIC_VALIDATION.json')
    if validation.get('status')!='PASS' or validation.get('real_outcome_reads')!=0:raise ValueError('SYNTHETIC_PASS_REQUIRED')
    qualification=readj(root/'INPUT_QUALIFICATION.json')
    rt=runtime(root);pred=rt[5]
    old=readj(C11/'DESIGN_FREEZE.json'); assembly=readj(C11/'SCORE_ASSEMBLY.json')
    legacy=dict(design=dict(path=str(C11/'DESIGN_FREEZE.json'),sha256=sha(C11/'DESIGN_FREEZE.json')),
        assembly=dict(path=str(C11/'SCORE_ASSEMBLY.json'),sha256=sha(C11/'SCORE_ASSEMBLY.json')),
        evidence=dict(path=str(C11/'diagnostics/selector_evidence/SELECTION_EVIDENCE.json'),sha256=sha(C11/'diagnostics/selector_evidence/SELECTION_EVIDENCE.json')),
        edge=dict(path=str(C11/'diagnostics/selector_evidence/PRIMARY_DAILY_EDGE.parquet'),sha256=sha(C11/'diagnostics/selector_evidence/PRIMARY_DAILY_EDGE.parquet')),
        clock=dict(path=str(C11/'diagnostics/selector_evidence/COMMON_DATE_MATURITY.parquet'),sha256=sha(C11/'diagnostics/selector_evidence/COMMON_DATE_MATURITY.parquet')),
        numeric_ids=[*old['evaluation']['legacy']['numeric_ids'],*assembly['complete_candidates']],
        exposure_ids=[*old['evaluation']['legacy']['exposure_ids'],*old['roles']],
        failed_or_untestable={**old['evaluation']['legacy']['failed_or_untestable'],**assembly['failed_or_untestable']},sources=old['sources'])
    if (len(legacy['numeric_ids']),len(legacy['exposure_ids']),len(legacy['failed_or_untestable']))!=(147,169,22):raise ValueError('LATEST_C11_EXPOSURE_REQUIRED')
    dag=physical_dag();put(root/'PHYSICAL_DAG.json',dag)
    own=[Path(__file__),Path(pairs.__file__),Path(est.__file__),REPO/'scripts/research/a2/evaluation/selector_boundary_evidence.py',
        REPO/'tests/research/a2/factors/test_selector_boundary_pairs.py',REPO/'tests/research/a2/training/test_selector_boundary_estimators.py',
        REPO/'tests/research/a2/training/test_selector_boundary_decision.py',REPO/'tests/research/a2/evaluation/test_selector_boundary_evidence.py',
        REPO/'scripts/research/a2/training/stateful_inputs.py',REPO/'scripts/research/a2/evaluation/selector_boundary_delivery.py',REPO/'tests/research/a2/evaluation/test_selector_boundary_delivery.py']
    source={**old['sources'],**{str(p):sha(p) for p in own}}
    d=dict(research_id=RESEARCH_ID,roles=list(pairs.ROLES),paradigms=list(est.PARADIGMS),
        official_freeze=True,formal_freeze_applied=True,target='MEAN_ER_3D_5D_10D_20D',primary_eval_years=[2023,2024,2025],
        mechanism_research_eligible=True,strict_PIT_promotion_eligible=False,test2026_locked=True,new2026_estimation_authorized=False,
        independent_holdout=False,development_status='EXPOSED_PRE2026_DEVELOPMENT',
        raw_score=old['raw_score'],features=old['features'],inputs=old['inputs'],
        horizon_labels=dict(path='D:/us-tech-quant-backtests/V24/20261003T092314+0000_4d0ba1cd/derived/horizon_labels.parquet',sha256='e32bb2ecf57e7cb5bf1931481055e7ddee5969082fc89ee101aaf9e62441aa61'),
        pair_freeze=dict(path=str(root/'PAIR_GEOMETRY_FREEZE.json'),sha256=sha(root/'PAIR_GEOMETRY_FREEZE.json')),
        input_qualification=dict(path=str(root/'INPUT_QUALIFICATION.json'),sha256=sha(root/'INPUT_QUALIFICATION.json')),
        physical_dag=dict(path=str(root/'PHYSICAL_DAG.json'),sha256=sha(root/'PHYSICAL_DAG.json')),
        sources=source,capacity_specs=est.capacity_specs(pred),capacities=list(est.CAPACITIES),seed_policy={p:[s for s,q in components(p)] for p in est.PARADIGMS},
        feature_order=receipt['feature_order'],pair_key_sha256=receipt['pair_key_sha256'],sample_policy='ALL_LEGAL_PRE_CUTOFF_PAIRS_NO_CAP',
        weight_policy=est.WEIGHT_POLICY,missing_encoding='ZERO_PLUS_TWO_FLAGS',regularization_policy=est.REGULARIZATION_POLICY,
        scaler='ONE_WEIGHTED_STANDARD_SCALER_PER_EXACT_CUT_SHARED_ALL_HEADS',scaler_cutoffs=list(CUTS),
        training_cutoff='signal_date < cutoff AND max pair 20D label_end_date < cutoff',
        blocked_outer_years={'2023':GAP,'2024':GAP},applicable_outer_years=[2025],
        inner_folds=[dict(cutoff=CUTS[i],validation_start=CUTS[i],validation_end=CUTS[i+1]) for i in range(2)],
        capacity_selection='date-equal sum matched realized scalar edges /20; both inner folds combined; 1e-12 tie -> LOW then MID then HIGH',
        resolver=dict(core=list(range(1,11)),incumbents=list(range(11,21)),challengers=list(range(21,41)),tie=pairs.TIE_POLICY,
            p1='P>.5; weight P-.5',p2_p8='pred>0; weight pred',p9='q10>0 AND q50>0; weight q50; NO quantile reorder'),
        budget=dict(physical_fit_hard_cap=380,active_physical_ceiling=122,estimator_ceiling=119,scaler_ceiling=3,scientific_retry=0,failures_refunded=False),
        evaluation=dict(primary=old['evaluation']['primary'],common_mature_date_count=732,original_calendar_dates=752,year_counts={'2023':250,'2024':252,'2025':230},
            exposure_namespace=178,numeric_ceiling=156,legacy=legacy,bootstrap={**old['evaluation']['bootstrap'],'family_candidates':156},
            inherited_selection_requirements=old['evaluation']['inherited_selection_requirements']),
        pre_freeze_outcome_reads=0,pre_freeze_fit_calls=0,source_contract=old['source_contract'],
        user_authorization=dict(path='C:/Users/Lenovo/.codex/attachments/5563e720-d5fe-46c0-881f-58eab4f8fc07/已粘贴的文本.txt',scope='Explicit independent C12 new local decision formulation; partial applicable training authorized'),
        canonical_registry_status='BLOCKED_CLOSED_BRANCH',registry_override_scope='Separate current human C12 authority; no reopening or changing accepted registry',
        c6a='BLOCKED_INPUT',c8='BLOCKED_DEPENDENCY',c11b='BLOCKED_SHARED_RISK',frozen_at=now())
    d['2026_rows_read']=0
    d['2026_predictions']=0
    d['2026_state_estimation']=0
    d['2026_evaluation']=0
    from scripts.research.a2.evaluation import selector_boundary_evidence as ev
    ev.validate_design(d)
    for h in ('raw_score','features','horizon_labels','pair_freeze','input_qualification','physical_dag'):pin(d[h])
    for p,h in source.items():pin(dict(path=p,sha256=h))
    for p,h in source.items():
        rel=Path(p).relative_to(REPO);dest=root/'source_snapshot'/rel;safe_d(dest).parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():raise FileExistsError('PRESERVE_SOURCE_SNAPSHOT')
        shutil.copyfile(p,dest)
    put(root/'DESIGN_FREEZE.json',d)
    review=dict(status='PASS',research_id=RESEARCH_ID,design_sha256=sha(root/'DESIGN_FREEZE.json'),source_pins=source,
        pair_geometry_sha256=d['pair_key_sha256'],dag_sha256=d['physical_dag']['sha256'],pre_execution_counters=dict(fits=0,outcome_reads=0),
        synthetic_validation=dict(path=str(root/'SYNTHETIC_VALIDATION.json'),sha256=sha(root/'SYNTHETIC_VALIDATION.json')),
        limited_scope='2025 applicable; 2023/24 remain blocked; no arbitrary early Raw tie reconstruction',registry_status_preserved='BLOCKED_CLOSED_BRANCH')
    put(root/'FORMAL_FREEZE_REVIEW.json',review)
    put(root/'DESIGN_FREEZE_SHA.json',dict(sha256=sha(root/'DESIGN_FREEZE.json'),formal_review_sha256=sha(root/'FORMAL_FREEZE_REVIEW.json')))
    ledger=dict(research_id=RESEARCH_ID,design_sha256=sha(root/'DESIGN_FREEZE.json'),hard_cap=380,active_ceiling=122,scientific_retry=0,
        slots={s['id']:{**s,'status':'PENDING','charged':False,'backend_entered':False} for s in dag['active_slots']})
    put(root/'FIT_LEDGER.json',ledger)
    print(json.dumps(dict(phase='FORMAL_FREEZE',status='PASS',sha=sha(root/'DESIGN_FREEZE.json'),active_ceiling=122)),flush=True)


def checked(root):
    cfg=paths(root);d=readj(root/'DESIGN_FREEZE.json');manifest=readj(root/'DESIGN_FREEZE_SHA.json');review=readj(root/'FORMAL_FREEZE_REVIEW.json')
    from scripts.research.a2.evaluation import selector_boundary_evidence as ev
    ev.validate_design(d)
    if sha(root/'DESIGN_FREEZE.json')!=manifest['sha256'] or sha(root/'FORMAL_FREEZE_REVIEW.json')!=manifest['formal_review_sha256'] or review['status']!='PASS' or review['design_sha256']!=manifest['sha256'] or review['source_pins']!=d['sources']:
        raise ValueError('EXACT_FORMAL_REVIEW_REQUIRED')
    required_owners={str(Path(__file__)),str(Path(pairs.__file__)),str(Path(est.__file__)),
        str(REPO/'scripts/research/a2/evaluation/selector_boundary_evidence.py'),
        str(REPO/'scripts/research/a2/evaluation/selector_boundary_delivery.py'),
        str(REPO/'scripts/research/a2/training/stateful_inputs.py')}
    if not required_owners<=set(d['sources']):raise ValueError('C12_SOURCE_CLOSURE_REQUIRED')
    for p,h in d['sources'].items():pin(dict(path=p,sha256=h))
    for h in ('raw_score','features','horizon_labels','pair_freeze','input_qualification','physical_dag'):pin(d[h])
    receipt=readj(pin(d['pair_freeze']))
    for k in ('pairs','features','frame'):pin(receipt[k])
    if receipt['pair_key_sha256']!=d['pair_key_sha256'] or receipt['target_values_read']!=0 or d['capacity_specs']!=est.capacity_specs(runtime(root)[5]):raise ValueError('EXACT_PAIR_NATIVE_SPECS_REQUIRED')
    if readj(pin(d['physical_dag']))!=physical_dag():raise ValueError('PHYSICAL_DAG_CHANGED')
    return cfg,d,receipt


def required_dates(pair_meta,start,end):
    """Window membership only clock-driven; any missing clock is blocked."""
    dates=pd.to_datetime(pair_meta.signal_date);ends=pd.to_datetime(pair_meta.label_end_date)
    in_window=dates.lt(pd.Timestamp(end)) & (dates.ge(pd.Timestamp(start)) if start else True)
    if ends.loc[in_window].isna().any():raise ValueError('BLOCKED_LABEL_MISSING_REQUIRED_MATURITY')
    mature=in_window & ends.lt(pd.Timestamp(end))
    # All 200 required partners are known and strictly mature together per date.
    group=mature.groupby(dates).transform('all')
    return np.flatnonzero((in_window & group).to_numpy())


def data_before_2025(root,d,receipt):
    """Projection filters exclude all 2025 targets from training/inner context."""
    g=pre2026(pin(receipt['pairs']),list(pairs.PAIR_KEYS),'signal_date')
    if pairs.pair_key_sha256(g)!=d['pair_key_sha256']:raise ValueError('PRE_LABEL_PAIR_SHA_CHANGED')
    x=pre2026(pin(receipt['features']),list(pairs.PAIR_KEYS)+d['feature_order'],'signal_date')
    frame=pre2026(pin(receipt['frame']),KEY+['ticker','U_t_fingerprint','raw_rank','raw_score'],'signal_date')
    shared.prove_label_boundary(pin(d['raw_score']),'label_end_date',allow_null=True)
    meta=pre2026(pin(d['raw_score']),KEY+['label_end_date'],'signal_date')
    meta=meta.loc[pd.to_datetime(meta.signal_date).lt('2025-01-01')].copy()
    for a in (g,x,frame,meta):a['signal_date']=pd.to_datetime(a.signal_date)
    hpath=pin(d['horizon_labels']);shared.prove_label_boundary(hpath,'target_end_date')
    shared.prove_label_boundary(hpath,'signal_date')
    columns=KEY+['target','target_end_date','ER_3D','ER_5D','ER_10D','ER_20D','target_end_date_20d']
    labels=pq.read_table(hpath,columns=columns,filters=[('signal_date','>=',pd.Timestamp('2023-01-01')),('signal_date','<',pd.Timestamp('2025-01-01')),('target_end_date','<',pd.Timestamp('2025-01-01'))]).to_pandas()
    labels['signal_date']=pd.to_datetime(labels.signal_date)
    if labels.duplicated(KEY).any() or (pd.to_datetime(labels.target_end_date)>=pd.Timestamp('2025-01-01')).any():raise ValueError('TRAIN_LABEL_FILTER_BREACH')
    if not np.allclose(labels[['ER_3D','ER_5D','ER_10D','ER_20D']].mean(axis=1),labels.target,rtol=0,atol=1e-12) or not pd.to_datetime(labels.target_end_date).equals(pd.to_datetime(labels.target_end_date_20d)):
        raise ValueError('EXACT_FOUR_HORIZON_SCALAR_MATURITY_REQUIRED')
    aligned_clock=labels[KEY+['target_end_date']].merge(meta,on=KEY,how='left',validate='one_to_one')
    if aligned_clock.label_end_date.isna().any() or not pd.to_datetime(aligned_clock.target_end_date).equals(pd.to_datetime(aligned_clock.label_end_date)):
        raise ValueError('BLOCKED_LABEL_RAW_HORIZON_MATURITY_MISMATCH')
    gpre=g.loc[g.signal_date.lt('2025-01-01')].copy()
    sides=[];end_sides=[]
    for uid in ('challenger_uid','incumbent_uid'):
        sides.append(gpre[['signal_date',uid]].merge(labels,left_on=['signal_date',uid],right_on=KEY,how='left',validate='many_to_one'))
        end_sides.append(gpre[['signal_date',uid]].merge(meta,left_on=['signal_date',uid],right_on=KEY,how='left',validate='many_to_one')['label_end_date'])
    pair_meta=gpre.copy();pair_meta['label_end_date']=pd.concat(end_sides,axis=1).max(axis=1)
    # A missing side cannot be hidden by the other side's maximum.
    pair_meta.loc[pd.concat(end_sides,axis=1).isna().any(axis=1),'label_end_date']=pd.NaT
    yy=sides[0].target.to_numpy(float)-sides[1].target.to_numpy(float)
    tasks=sides[0][['ER_3D','ER_5D','ER_10D','ER_20D']].to_numpy(float)-sides[1][['ER_3D','ER_5D','ER_10D','ER_20D']].to_numpy(float)
    xx=x.loc[x.signal_date.lt('2025-01-01'),d['feature_order']].to_numpy(float)
    if not gpre.reset_index(drop=True).equals(x.loc[x.signal_date.lt('2025-01-01'),list(pairs.PAIR_KEYS)].reset_index(drop=True)):raise ValueError('FROZEN_PAIR_FEATURE_ORDER_REQUIRED')
    for i,c in enumerate(CUTS):
        ix=required_dates(pair_meta,None,c)
        if len(ix)!=EXPECTED_DATES[i]*200 or not np.isfinite(yy[ix]).all() or not np.isfinite(tasks[ix]).all():raise ValueError('BLOCKED_LABEL_ALL_REQUIRED_GEOMETRY:'+c)
    return g,x,frame,pair_meta,xx,yy,tasks


def validate_ledger(value,design_sha,dag):
    if value.get('design_sha256')!=design_sha or value.get('hard_cap')!=380 or value.get('active_ceiling')!=122 or value.get('scientific_retry')!=0:
        raise ValueError('FIT_LEDGER_DESIGN_BUDGET_BINDING')
    expected={s['id']:s for s in dag['active_slots']}
    if set(value['slots'])!=set(expected):raise ValueError('FIT_LEDGER_EXACT_DAG_REQUIRED')
    for sid,spec in expected.items():
        row=value['slots'][sid]
        if any(row.get(k)!=v for k,v in spec.items()):raise ValueError('FIT_LEDGER_SLOT_IDENTITY_CHANGED')
        if row.get('backend_entered') and not row.get('charged'):raise ValueError('BACKEND_REQUIRES_CHARGED_RESERVATION')
        if row['status']=='RESERVED' and not row.get('charged'):raise ValueError('RESERVED_REQUIRES_CHARGE')
        if row['status']=='BLOCKED' and row.get('backend_entered'):raise ValueError('BLOCKED_CANNOT_ENTER_BACKEND')
        if row['status']=='COMPLETE' and not(row.get('charged') and row.get('backend_entered')):
            raise ValueError('COMPLETE_REQUIRES_ACTUAL_BACKEND_ENTRY')
        if row['status']=='PENDING' and (row.get('charged') or row.get('backend_entered')):
            raise ValueError('PENDING_CANNOT_CONSUME_RESERVATION')
        if row['status'] not in ('PENDING','RESERVED','COMPLETE','FAILED','BLOCKED'):
            raise ValueError('FROZEN_LEDGER_STATUS_REQUIRED')
    if sum(s['charged'] for s in value['slots'].values())>122:raise ValueError('FIT_LEDGER_CAP_BREACH')


class Ledger:
    def __init__(self,root):
        self.root=root;self.path=root/'FIT_LEDGER.json';self.value=readj(self.path)
        validate_ledger(self.value,sha(root/'DESIGN_FREEZE.json'),physical_dag())
    def save(self):
        putj(safe_d(self.path),self.value)
        rows=list(self.value['slots'].values())
        putj(self.root/'PIPELINE_STATE.json',dict(status='C12_TRAINING_RUNNING',at=now(),
            charged=sum(r['charged'] for r in rows),physical_backend_entered=sum(r['backend_entered'] for r in rows),
            completed=sum(r['status']=='COMPLETE' for r in rows),failed=sum(r['status']=='FAILED' for r in rows),
            pending=sum(r['status']=='PENDING' for r in rows),test2026_locked=True))
    def claim(self,sid):
        s=self.value['slots'][sid]
        if s['status']!='PENDING':return False
        count=sum(r['charged'] for r in self.value['slots'].values())
        if count>=min(self.value['hard_cap'],self.value['active_ceiling']):raise RuntimeError('C12_BUDGET_EXHAUSTED')
        s.update(status='RESERVED',charged=True,started_at=now());self.save();return True
    def enter(self,sid,event):
        s=self.value['slots'][sid]
        if s['status']!='RESERVED' or s['backend_entered']:raise ValueError('ONE_BACKEND_ENTRY_ONLY')
        s.update(backend_entered=True,backend_event=event);self.save()
    def finish(self,sid,status,**values):
        s=self.value['slots'][sid]
        if s['status'] not in ('RESERVED','PENDING'):raise ValueError('PRESERVE_TERMINAL_FIT_STATUS')
        if status=='COMPLETE' and not(s['charged'] and s['backend_entered']):raise ValueError('NO_BACKEND_NO_COMPLETE')
        if status not in ('COMPLETE','FAILED','BLOCKED'):raise ValueError('TERMINAL_STATUS_REQUIRED')
        s.update(status=status,finished_at=now(),**values);self.save()


def scaler_for(root,ledger,c,xx,meta,order,jb):
    sid='SCALER_'+c;s=ledger.value['slots'][sid];ix=required_dates(meta,None,c)
    identity=dict(pair_key_sha256=pairs.pair_key_sha256(meta.iloc[ix]),feature_order=order,
        feature_sha256=hashlib.sha256(np.ascontiguousarray(xx[ix],dtype='<f8').tobytes()).hexdigest(),
        weight_sha256=hashlib.sha256(np.full(len(ix),1/200,dtype='<f8').tobytes()).hexdigest(),cutoff=c,
        missing_encoding='ZERO_PLUS_TWO_FLAGS',runtime_version=platform.python_version(),sklearn_version=__import__('sklearn').__version__)
    p=root/'models'/f'scaler_{c}.joblib'
    if s['status']=='COMPLETE':
        if s['identity']!=identity:raise ValueError('SCALER_REUSE_IDENTITY_CHANGED')
        pin(s['model']);return jb.load(p),ix
    if not ledger.claim(sid):return None,ix
    try:
        model=StandardScaler();ledger.enter(sid,dict(operation='scaler_fit'))
        model.fit(xx[ix],sample_weight=np.full(len(ix),1/200));jb.dump(model,safe_d(p))
        ledger.finish(sid,'COMPLETE',identity=identity,model=dict(path=str(p),sha256=sha(p)),training_rows=len(ix),training_dates=len(ix)//200)
        return model,ix
    except Exception as e:
        ledger.finish(sid,'FAILED',error=str(e),traceback=traceback.format_exc());return None,ix


def fit_component(root,ledger,p,cap,c,seed,q,scaler,ix,xx,yy,tasks,meta,pred,jb,outer=False):
    sid=f'OUTER_{p}_{seed}_{q}' if outer else f'{c}_{p}_{cap}_{seed}_{q}'
    s=ledger.value['slots'][sid];path=root/'models'/f'{sid}.joblib'
    if s['status']=='COMPLETE':
        if s.get('selected_capacity')!=cap:raise ValueError('REUSE_CAPACITY_CHANGED')
        pin(s['model']);return jb.load(path)
    if not ledger.claim(sid):return None
    try:
        y=tasks[ix] if p=='MULTITASK_MLP' else yy[ix]
        train=meta.iloc[ix]
        if pd.to_datetime(train.label_end_date).max()>=pd.Timestamp(c):raise ValueError('FIT_LABEL_BOUNDARY_BREACH')
        obj=est.fit(p,scaler.transform(xx[ix]),y,train.signal_date,train.challenger_uid,train.incumbent_uid,cap,
            runtime=pred,seed=seed,quantile=q,on_fit_call=lambda event:ledger.enter(sid,event))
        jb.dump(obj,safe_d(path))
        ledger.finish(sid,'COMPLETE',model=dict(path=str(path),sha256=sha(path)),selected_capacity=cap,
            training_pairs=len(ix),training_dates=len(ix)//200,max_train_label_end=str(pd.to_datetime(train.label_end_date).max()),metadata=obj.metadata)
        return obj
    except Exception as e:
        ledger.finish(sid,'FAILED',error=str(e),traceback=traceback.format_exc(),selected_capacity=cap)
        print(json.dumps(dict(phase='FIT_FAILED',slot=sid,error=str(e))),flush=True);return None


def prediction_bundle(root,ledger,p,cap,c,scaler,ix,xx,yy,tasks,meta,vx,pred,jb,outer=False):
    values={};missing=[]
    for seed,q in components(p):
        model=fit_component(root,ledger,p,cap,c,seed,q,scaler,ix,xx,yy,tasks,meta,pred,jb,outer)
        if model is None:missing.append((seed,q));continue
        values[q if p=='QUANTILE_HGB' else seed]=est.predict(model,vx)
    if missing:return None,dict(missing_components=missing)
    details=dict(complete_components=list(values))
    if p=='MULTITASK_MLP':details['horizon_predictions']=np.mean([np.asarray(v,dtype=float) for v in values.values()],axis=0)
    return est.combine_predictions(p,values),details


def resolve_days(raw,g,prediction,role):
    panels=[];matches=[];raw_index=raw.groupby('signal_date',sort=True).indices
    for date,ix in g.groupby('signal_date',sort=True).indices.items():
        pred=prediction[ix];median=pred[:,1] if role==pairs.ROLES[-1] else pred
        panel=pairs.resolve(raw.iloc[raw_index[date]],g.iloc[ix],median,role,q10=pred[:,0] if role==pairs.ROLES[-1] else None)
        matches.extend(panel.attrs['matched_pairs']);panel.attrs={}
        panels.append(panel)
    out=pd.concat(panels,ignore_index=True).merge(raw[KEY+['ticker','U_t_fingerprint']],on=KEY,how='left',validate='one_to_one')
    return out,pd.DataFrame(matches,columns=[*pairs.PAIR_KEYS,'predicted_edge'])


def matching_utility(g,prediction,role,realized,raw):
    """Actual anchored Top20 utility, never mean over selected pairs."""
    if not np.isfinite(realized).all():raise ValueError('BLOCKED_LABEL_REQUIRED_INNER_PAIRS')
    panel,matched=resolve_days(raw,g,prediction,role)
    source=g[list(pairs.PAIR_KEYS)].assign(realized_edge=realized)
    linked=matched.merge(source,on=list(pairs.PAIR_KEYS),validate='one_to_one')
    daily=linked.groupby('signal_date').realized_edge.sum().reindex(pd.DatetimeIndex(sorted(g.signal_date.unique())),fill_value=0)/20
    return dict(sum_daily_utility=float(daily.sum()),dates=len(daily),mean_utility=float(daily.mean()),matched_pairs=len(matched))


def choose_capacity(records):
    scores={}
    for cap in est.CAPACITIES:
        rows=[r for r in records if r['capacity']==cap]
        if (len(rows)==2 and {r.get('fold_cutoff') for r in rows}==set(CUTS[:2])
                and all(r['status']=='COMPLETE' and r['dates']>0 for r in rows)):
            scores[cap]=sum(r['sum_daily_utility'] for r in rows)/sum(r['dates'] for r in rows)
    if not scores:return None,scores
    best=max(scores.values());return next(c for c in est.CAPACITIES if c in scores and scores[c]>=best-1e-12),scores


def train(root):
    cfg,d,receipt=checked(root);rt=runtime(root);jb,pred=rt[4],rt[5]
    if (root/'FINAL_PIPELINES_FREEZE.json').exists():raise FileExistsError('NO_RETRAIN_AFTER_FINAL_PIPELINES_FREEZE')
    g,x,raw,meta,xx,yy,tasks=data_before_2025(root,d,receipt);ledger=Ledger(root)
    scalers={}
    for c in CUTS:scalers[c]=scaler_for(root,ledger,c,xx,meta,d['feature_order'],jb)
    capacities=[];outer_status={};bindings={};diagbindings={}
    for role,p in zip(pairs.ROLES,est.PARADIGMS):
        records=[]
        for i,c in enumerate(CUTS[:2]):
            sc,ix=scalers[c];vi=required_dates(meta,c,CUTS[i+1]);vg=meta.iloc[vi][list(pairs.PAIR_KEYS)].reset_index(drop=True)
            vx=sc.transform(xx[vi]) if sc is not None else None
            for cap in est.CAPACITIES:
                record=dict(candidate_id=role,paradigm=p,capacity=cap,fold_cutoff=c,validation_end=CUTS[i+1],status='BLOCKED')
                print(json.dumps(dict(phase='INNER',paradigm=p,capacity=cap,cutoff=c,train_pairs=len(ix),validation_pairs=len(vi))),flush=True)
                if sc is not None:
                    pr,detail=prediction_bundle(root,ledger,p,cap,c,sc,ix,xx,yy,tasks,meta,vx,pred,jb)
                    detail.pop('horizon_predictions',None)
                    record.update(detail)
                    if pr is not None:
                        rp=root/'predictions'/f'inner_{p}_{cap}_{c}.parquet'
                        arr=pr if pr.ndim==2 else pr[:,None]
                        vp=vg.copy()
                        for j in range(arr.shape[1]):vp[f'prediction_{j}']=arr[:,j]
                        vp.to_parquet(safe_d(rp),index=False)
                        record.update(status='COMPLETE',prediction=dict(path=str(rp),sha256=sha(rp)),**matching_utility(vg,pr,role,yy[vi],raw))
                records.append(record)
        selected,utilities=choose_capacity(records)
        cp=dict(candidate_id=role,outer_year=2025,selected_capacity=selected,inner_capacity_utilities=utilities,records=records,
            model_selection_uses='ONLY_2024_DATE_EQUAL_ACTUAL_MATCHING_UTILITY',outer_y_values_read=0)
        caps_path=root/'models'/f'capacity_{p}_2025.json';put(caps_path,cp);capacities.append(cp)
        if selected is None:
            outer_status[role]=dict(status='BLOCKED_CAPACITY_NO_COMPLETE_TWO_FOLDS',year=2025)
            for s,q in components(p):ledger.finish(f'OUTER_{p}_{s}_{q}','BLOCKED',reason='NO_ELIGIBLE_PAST_CAPACITY')
            continue
        sc,ix=scalers[CUTS[-1]];gx=g.loc[g.signal_date.dt.year.eq(2025)].reset_index(drop=True)
        ox=x.loc[x.signal_date.dt.year.eq(2025),d['feature_order']].to_numpy(float)
        if sc is None:
            outer_status[role]=dict(status='BLOCKED_SCALER',year=2025);continue
        prediction,detail=prediction_bundle(root,ledger,p,selected,CUTS[-1],sc,ix,xx,yy,tasks,meta,sc.transform(ox),pred,jb,True)
        horizons=detail.pop('horizon_predictions',None)
        if prediction is None:outer_status[role]=dict(status='FAILED_REQUIRED_OUTER_COMPONENT',year=2025,**detail);continue
        panel,matched=resolve_days(raw,gx,prediction,role)
        pp=root/'predictions'/f'scores_{role}_2025.parquet';panel.to_parquet(safe_d(pp),index=False)
        mp=root/'diagnostics'/f'matched_{role}_2025.parquet';matched.to_parquet(safe_d(mp),index=False)
        arr=prediction if prediction.ndim==2 else prediction[:,None];pv=gx.copy()
        for j in range(arr.shape[1]):pv[f'prediction_{j}']=arr[:,j]
        if horizons is not None:
            for j,h in enumerate((3,5,10,20)):pv[f'horizon_prediction_{h}d']=horizons[:,j]
        vp=root/'predictions'/f'pairs_{role}_2025.parquet';pv.to_parquet(safe_d(vp),index=False)
        bindings[role]=dict(path=str(pp),sha256=sha(pp));diagbindings[role]=dict(pairs=dict(path=str(vp),sha256=sha(vp)),matched=dict(path=str(mp),sha256=sha(mp)))
        outer_status[role]=dict(status='COMPLETE_2025_ONLY',year=2025,selected_capacity=selected,**detail)
        print(json.dumps(dict(phase='OUTER',candidate_id=role,status='COMPLETE_2025_ONLY',capacity=selected)),flush=True)
    for s in ledger.value['slots'].values():
        if s['status']=='PENDING':ledger.finish(s['id'],'BLOCKED',reason='FAILED_OR_UNAVAILABLE_REQUIRED_DEPENDENCY')
    if not all(s['status'] in ('COMPLETE','FAILED','BLOCKED') for s in ledger.value['slots'].values()):
        raise ValueError('NO_FINAL_FREEZE_WITH_UNRESOLVED_RESERVED_SLOT')
    validate_ledger(ledger.value,sha(root/'DESIGN_FREEZE.json'),physical_dag())
    final=dict(status='FINAL_PIPELINES_FROZEN',research_id=RESEARCH_ID,design_sha256=sha(root/'DESIGN_FREEZE.json'),
        capacity_selection_complete=True,all_training_terminal=True,roles=list(pairs.ROLES),
        role_statuses={cid:'PARTIAL_INPUT_BLOCKED' if outer_status[cid]['status']=='COMPLETE_2025_ONLY' else 'FAILED' for cid in pairs.ROLES},
        outer_pipeline_status=outer_status,blocked_years=d['blocked_outer_years'],
        capacity_receipts={p:dict(path=str(root/'models'/f'capacity_{p}_2025.json'),sha256=sha(root/'models'/f'capacity_{p}_2025.json')) for p in est.PARADIGMS},
        fit_ledger_sha256=sha(root/'FIT_LEDGER.json'),outer_labels_read=0,freeze_at=now(),oracle_allowed_after_this=True)
    put(root/'FINAL_PIPELINES_FREEZE.json',final)
    put(root/'SCORE_ASSEMBLY.json',dict(status='C12_PARTIAL_2025_ASSEMBLY',design_freeze_sha256=sha(root/'DESIGN_FREEZE.json'),
        final_pipelines_freeze=dict(path=str(root/'FINAL_PIPELINES_FREEZE.json'),sha256=sha(root/'FINAL_PIPELINES_FREEZE.json')),
        complete_2025_candidates=list(bindings),complete_common_732_candidates=[],failed_or_untestable={cid:GAP for cid in pairs.ROLES},
        outer_pipeline_status=outer_status,score_paths=bindings,diagnostic_paths=diagbindings,forecast2026_rows=0))
    putj(root/'PIPELINE_STATE.json',dict(status='TRAINING_COMPLETE_EVALUATION_PENDING',at=now(),completed_2025=len(bindings),terminal='C12_PARTIAL_INPUT_BLOCKED'))
    return final


def execute(root):
    train(root)
    from scripts.research.a2.evaluation import selector_boundary_delivery as delivery
    delivery.run(root)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['prepare','freeze','train','execute']);parser.add_argument('--run',required=True)
    args=parser.parse_args();{'prepare':prepare,'freeze':freeze,'train':train,'execute':execute}[args.stage](safe_d(args.run))
