"""C14 current-state boundary controller; original matching/native/fusion owners reused.
Unlike closed C12, no lag fields, early Raw reconstruction, or old model retry.
All preparation is label-free; numeric labels are projected per frozen cutoff.
"""
from __future__ import annotations
import argparse, hashlib, json, os, traceback
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.factors import selector_boundary_pairs as pairs
from scripts.research.a2.training.selector_challenge import putj, sha
from scripts.research.a2.training.stateful_inputs import FEATURES as BASE32

REPO = Path(__file__).resolve().parents[4]
ID = 'V24_C_SELECTOR_MAXIMAL_BREADTH_PRE2026_C14'
BOUNDARY = pd.Timestamp('2026-01-01')
CUTS = ('2023-04-01','2023-07-01','2024-01-01','2024-07-01','2025-01-01')
CAPACITIES = ('LOW','MID','HIGH')
WARMUP = ('LINEAR_SVM','PAIRWISE_RANKER','LAMBDAMART')
FUSION_MEMBERS = ('RIDGE','HGB','XGB','CAT','MLP','QUANTILE_HGB')
META_STOCHASTIC = ('mlp_stack','linear_gate','mlp_gate')
META_SEEDS = (20260928,20260929,20260930)
FUSION_METHODS = ('equal','median','simplex','nnls','ridge_stack','elastic_stack',
                  'hgb_stack','mlp_stack','linear_gate','mlp_gate','ridge_then_hgb','hgb_then_ridge')
CURRENT36 = (*BASE32,'raw_score','raw_rank','current_raw_percentile','raw_score_minus_rank20_score')
PAIR_KEYS = pairs.PAIR_KEYS
KEYS = ('signal_date','security_uid')
CACHE = {}
SOLVES = {}
SOLVE_DAGS = {}


def require(ok, message):
    if not ok: raise ValueError(message)


def now(): return datetime.now(timezone.utc).isoformat()


def content_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),default=str,allow_nan=False).encode()).hexdigest()


def safe_d(path):
    p = Path(path).absolute()
    require(p.drive.upper() == 'D:', 'D_CUSTODY_ONLY_NO_E_F')
    for x in (p,*p.parents):
        if x.exists(): require(not (getattr(x.stat(),'st_file_attributes',0)&0x400), 'REPARSE_SOURCE_OR_OUTPUT_FORBIDDEN')
    return p


def pin(ref):
    p = safe_d(ref['path']); s=p.stat(); identity=(str(p),s.st_size,s.st_mtime_ns,ref['sha256'])
    if identity not in CACHE:
        require(sha(p)==ref['sha256'],'PIN_CHANGED:'+str(p)); CACHE[identity]=True
    return p


def write_json(path,value):
    assert_safe_output_path(path,kind='backtest',paths=resolve(REPO)); putj(safe_d(path),value)


def write_table(path,frame):
    assert_safe_output_path(path,kind='backtest',paths=resolve(REPO))
    path=safe_d(path); path.parent.mkdir(parents=True,exist_ok=True)
    require(not path.exists(),'PRESERVE_EXISTING_PREPARED_ARTIFACT')
    frame.to_parquet(path,index=False)
    return dict(path=str(path),sha256=sha(path),rows=len(frame))


def footer(ref,clocks=('signal_date',),allow_null=()):
    p=pin(ref); f=pq.ParquetFile(p); result={}
    for column in clocks:
        j=f.schema_arrow.get_field_index(column); require(j>=0,'CLOCK_COLUMN_REQUIRED:'+column)
        lo=[];hi=[];nulls=0
        for i in range(f.num_row_groups):
            s=f.metadata.row_group(i).column(j).statistics
            require(s is not None,'CLOCK_FOOTER_REQUIRED:'+column)
            nulls+=s.null_count or 0
            if s.has_min_max: lo.append(pd.Timestamp(s.min));hi.append(pd.Timestamp(s.max))
            elif f.metadata.row_group(i).num_rows != (s.null_count or 0): raise ValueError('CLOCK_RANGE_UNKNOWN')
        require(hi and max(hi)<BOUNDARY,'PHYSICAL_PRE2026_REQUIRED:'+column)
        require(column in allow_null or nulls==0,'MISSING_CLOCK_FORBIDDEN:'+column)
        result[column]=dict(min=str(min(lo)),max=str(max(hi)),nulls=nulls)
    return dict(path=str(p),sha256=ref['sha256'],rows=f.metadata.num_rows,columns=f.schema_arrow.names,clocks=result)


def project(ref,columns,*,start,stop,mature_before=None,mature_field='target_end_date',run=None):
    """A predicate is applied before numeric columns are materialized."""
    numeric_labels={'target','ER_3D','ER_5D','ER_10D','ER_20D','y_open5'}
    if numeric_labels.intersection(columns):
        require(run is not None,'FORMAL_GATE_REQUIRED_FOR_NUMERIC_LABEL_PROJECTION');checked(run)
    require(pd.Timestamp(start)<pd.Timestamp(stop)<=BOUNDARY,'PROJECTION_WINDOW_INVALID')
    clocks=('signal_date',mature_field) if mature_before is not None else ('signal_date',)
    footer(ref,clocks)
    filters=[('signal_date','>=',pd.Timestamp(start)),('signal_date','<',pd.Timestamp(stop))]
    if mature_before is not None:
        require(pd.Timestamp(mature_before)<=pd.Timestamp(stop),'MATURITY_CUTOFF_INVALID')
        filters.append((mature_field,'<',pd.Timestamp(mature_before)))
    path=pin(ref); before=path.stat()
    out=pq.read_table(path,columns=list(columns),filters=filters).to_pandas()
    require((before.st_size,before.st_mtime_ns)==(path.stat().st_size,path.stat().st_mtime_ns),'SOURCE_CHANGED_DURING_READ')
    out['signal_date']=pd.to_datetime(out.signal_date)
    require(out.signal_date.ge(start).all() and out.signal_date.lt(stop).all(),'PREDICATE_BREACH')
    if mature_before is not None: require(pd.to_datetime(out[mature_field]).lt(mature_before).all(),'MATURITY_PREDICATE_BREACH')
    return out


def feature_order(representation='FULL_PAIR'):
    require(representation in ('FULL_PAIR','DELTA_ONLY'),'REPRESENTATION_NOT_FROZEN')
    blocks=('challenger','incumbent','delta') if representation=='FULL_PAIR' else ('delta',)
    values=[f'{b}__{f}' for b in blocks for f in CURRENT36]
    return values+[v+'__missing' for v in values]


def current_frame(raw,features,membership):
    needed=('signal_date','ticker','security_uid','U_t_fingerprint','score','rank','label_end_date')
    require(set(needed).issubset(raw),'CURRENT_RAW_FIELDS_REQUIRED')
    r=raw[list(needed)].rename(columns={'score':'raw_score','rank':'raw_rank'}).copy()
    r['signal_date']=pd.to_datetime(r.signal_date)
    pairs._raw(r,with_score=True)
    require(not r.duplicated(['signal_date','ticker']).any(),'RAW_TICKER_AMBIGUOUS')
    require(not features.duplicated(['signal_date','ticker']).any(),'BASE32_KEY_AMBIGUOUS')
    require(not membership.duplicated(['signal_date','ticker']).any(),'MEMBERSHIP_KEY_AMBIGUOUS')
    bridge=membership[['signal_date','ticker','cusip']].copy()
    require(bridge.cusip.notna().all(),'CUSIP_REQUIRED_NO_NEW_BRIDGE')
    bridge['bridge_uid']='CUSIP:'+bridge.cusip.astype(str).str.strip().str.upper()
    r=r.merge(bridge,on=['signal_date','ticker'],how='left',validate='one_to_one')
    require(r.security_uid.eq(r.bridge_uid).all(),'CURRENT_UID_EXACT_BRIDGE_REQUIRED')
    r=r.merge(features[['signal_date','ticker',*BASE32]],on=['signal_date','ticker'],how='left',validate='one_to_one',indicator=True)
    require(r['_merge'].eq('both').all(),'BASE32_FULL_U_DEPENDENCY_MISSING')
    size=r.groupby('signal_date').raw_rank.transform('size')
    r['current_raw_percentile']=1-(r.raw_rank-1)/(size-1)
    boundary=r.loc[r.raw_rank.eq(20),['signal_date','raw_score']].set_index('signal_date').raw_score
    r['raw_score_minus_rank20_score']=r.raw_score-r.signal_date.map(boundary)
    require(not np.isinf(r[list(CURRENT36)].to_numpy(float)).any(),'INFINITE_CURRENT_INPUT')
    for _,g in r.groupby('signal_date'):
        ordered=g.sort_values(['raw_score','security_uid'],ascending=[False,True],kind='stable')
        require(np.array_equal(ordered.raw_rank.to_numpy(),np.arange(1,len(g)+1)),'CURRENT_UID_TIE_CHANGED')
        require(g.U_t_fingerprint.nunique()==1,'FULL_U_FINGERPRINT_AMBIGUOUS')
    return r.drop(columns=['cusip','bridge_uid','_merge']).sort_values(['signal_date','raw_rank','security_uid']).reset_index(drop=True)


def pair_features(frame,geometry,representation='FULL_PAIR'):
    g=pairs._pairs(geometry); r=pairs._raw(frame,with_score=True)
    require(pairs.pair_key_sha256(pairs.geometry(r))==pairs.pair_key_sha256(g),'GEOMETRY_CURRENT_RAW_MISMATCH')
    values=[]
    for uid in ('challenger_uid','incumbent_uid'):
        joined=g[['signal_date',uid]].merge(frame[[*KEYS,*CURRENT36]],left_on=['signal_date',uid],right_on=list(KEYS),how='left',validate='many_to_one',indicator=True)
        require(joined['_merge'].eq('both').all(),'PAIR_PARTNER_FEATURE_MISSING')
        values.append(joined[list(CURRENT36)].to_numpy(float))
    delta=values[0]-values[1]
    arrays=(*values,delta) if representation=='FULL_PAIR' else (delta,)
    x=np.concatenate(arrays,axis=1); missing=~np.isfinite(x)
    require(not np.isinf(x).any(),'INFINITE_PAIR_COORDINATE')
    x=np.concatenate((np.where(missing,0.,x),missing.astype(float)),axis=1)
    return pd.concat([g.reset_index(drop=True),pd.DataFrame(x,columns=feature_order(representation))],axis=1)


def mature_dates(raw,start,end):
    r=raw.loc[raw.signal_date.ge(pd.Timestamp(start)) & raw.signal_date.lt(pd.Timestamp(end)) & raw.raw_rank.between(11,40)]
    clocks=pd.to_datetime(r.label_end_date)
    legal=clocks.notna() & clocks.lt(pd.Timestamp(end))
    return pd.DatetimeIndex(sorted(r.signal_date[legal.groupby(r.signal_date).transform('all')].unique()))


def prepare(run,design):
    run=safe_d(run); assert_safe_output_path(run,kind='backtest',paths=resolve(REPO))
    require(design['research_id']==ID,'RESEARCH_ID_CHANGED')
    require(not (run/'DESIGN_FREEZE.json').exists() and not (run/'INPUT_QUALIFICATION.json').exists(),'PREPARE_NO_FROZEN_OR_EXISTING_OVERWRITE')
    sources=design['inputs']; receipts={n:footer(sources[n],('signal_date',)) for n in ('raw','features','members','hlabels')}
    footer(sources['raw'],('label_end_date',),allow_null=('label_end_date',))
    raw=project(sources['raw'],['signal_date','ticker','security_uid','U_t_fingerprint','score','rank','label_end_date'],start='2023-01-01',stop='2026-01-01')
    feat=project(sources['features'],['signal_date','ticker',*BASE32],start='2023-01-01',stop='2026-01-01')
    mem=project(sources['members'],['signal_date','ticker','cusip'],start='2023-01-01',stop='2026-01-01')
    frame=current_frame(raw,feat,mem); g=pairs.geometry(frame); x=pair_features(frame,g)
    counts={str(y):frame.loc[frame.signal_date.dt.year.eq(y),'signal_date'].nunique() for y in (2023,2024,2025)}
    require(sum(counts.values())==752 and len(g)==752*200,'ORIGINAL_752_GEOMETRY_REQUIRED')
    require(frame.loc[frame.signal_date.dt.year.eq(2024),'signal_date'].nunique()+frame.loc[frame.signal_date.dt.year.eq(2025),'signal_date'].nunique()<=504,'DECODER_PROPOSAL_OUTER_BOUND')
    train_dates={c:[d.isoformat() for d in mature_dates(frame,'2023-01-01',c)] for c in CUTS}
    validation={f'{a}:{b}':[d.isoformat() for d in mature_dates(frame,a,b)] for a,b in zip(CUTS[1:4],CUTS[2:5])}
    q=dict(status='INPUT_QUALIFIED_LABEL_FREE',research_id=ID,input_sources=receipts,feature_order=feature_order(),current_feature_order=list(CURRENT36),
           pair_key_sha256=pairs.pair_key_sha256(g),full_U_keys_sha256=content_hash(frame[[*KEYS,'U_t_fingerprint','raw_rank']].astype(str).values.tolist()),
           rows=len(frame),calendar_dates=752,year_counts=counts,outer_prediction_dates=counts['2024']+counts['2025'],
           train_dates=train_dates,validation_dates=validation,outer_support_dates=[d.isoformat() for d in mature_dates(frame,'2024-01-01','2026-01-01')],
           preparation_target_value_reads=0,preparation_fit_calls=0,previous_or_lag_input=False,mechanism_research_eligible=True,strict_PIT_promotion_eligible=False,test2026_locked=True)
    q['artifacts']={n:write_table(run/'derived'/f'{n}.parquet',v) for n,v in (('raw_current',frame),('pair_geometry',g),('current_pair_features',x))}
    write_json(run/'PAIR_GEOMETRY_RECEIPT.json',{k:q[k] for k in ('research_id','pair_key_sha256','full_U_keys_sha256','calendar_dates','year_counts','preparation_target_value_reads','preparation_fit_calls')})
    write_json(run/'INPUT_QUALIFICATION.json',q)
    return q


def checked_sources(run, design):
    """Exact reviewed post-fit engineering overlay; original freeze stays intact."""
    run=Path(run); path=run/'SOURCE_CORRECTION.json'
    if not path.exists():
        return {p:sha(pin(dict(path=p,sha256=h))) for p,h in design['sources'].items()}
    assert_safe_output_path(path,kind='backtest',paths=resolve(REPO))
    correction=json.loads(path.read_text(encoding='utf-8'))
    allowed={str(REPO/'scripts/research/a2/training/selector_maximal_breadth.py'),
             str(REPO/'scripts/research/a2/evaluation/selector_maximal_breadth_delivery.py')}
    changes=correction.get('source_changes',{})
    require(correction.get('status')=='PASS' and correction.get('research_id')==ID
        and correction.get('classification')=='POSTFIT_ENGINEERING_ONLY'
        and correction.get('scientific_parameters_changed') is False
        and correction.get('scientific_retry')==0 and correction.get('repair_preparation_outcome_reads')==0
        and set(changes)==allowed and set(changes)<=set(design['sources']), 'UNAPPROVED_POSTFIT_SOURCE_CORRECTION')
    expected_names={'DESIGN_FREEZE.json','PHYSICAL_DAG.json','SOURCE_CLOSURE_RECEIPT.json',
        'FORMAL_FREEZE_RECEIPT.json','FIT_LEDGER.json','ML_ASSEMBLY.json','ML_DELIVERY_COMPLETE.json',
        'SCORE_ASSEMBLY.json','FINAL_PIPELINES_FREEZE.json'}
    require(set(correction.get('terminal_pins',{}))==expected_names,'POSTFIT_TERMINAL_PINS_REQUIRED')
    for name,digest in correction['terminal_pins'].items(): pin(dict(path=run/name,sha256=digest))
    ledger=json.loads((run/'FIT_LEDGER.json').read_text(encoding='utf-8'))
    assembly=json.loads((run/'ML_ASSEMBLY.json').read_text(encoding='utf-8'))
    gate=json.loads((run/'FINAL_PIPELINES_FREEZE.json').read_text(encoding='utf-8'))
    require(all(s['status'] not in ('STARTED','RESERVED') for s in ledger['slots'].values())
        and assembly.get('all_training_terminal') is True and assembly.get('capacity_selection_complete') is True
        and gate.get('status')=='FINAL_PIPELINES_FROZEN' and gate.get('forecast2026_rows')==0
        and gate.get('design_sha256')==sha(run/'DESIGN_FREEZE.json')
        and gate.get('fit_ledger_sha256')==sha(run/'FIT_LEDGER.json')
        and gate.get('score_assembly_sha256')==sha(run/'SCORE_ASSEMBLY.json'), 'POSTFIT_CORRECTION_REQUIRES_TERMINAL_ML')
    review_path=pin(correction['independent_review'])
    require(review_path.is_relative_to(run),'RUN_OWNED_CORRECTION_REVIEW_REQUIRED')
    review=json.loads(review_path.read_text(encoding='utf-8'))
    require(review.get('status')=='PASS' and review.get('classification')=='POSTFIT_ENGINEERING_ONLY'
        and review.get('research_id')==ID and review.get('source_changes')==changes
        and review.get('terminal_pins')==correction['terminal_pins'], 'POSTFIT_CORRECTION_REVIEW_REQUIRED')
    result={}
    for source,original in design['sources'].items():
        if source not in changes: result[source]=sha(pin(dict(path=source,sha256=original))); continue
        change=changes[source]; snapshot=pin(change['original_snapshot'])
        require(snapshot.is_relative_to(run/'source_snapshot') and change['original_sha256']==original
            and change['original_snapshot']['sha256']==original, 'PRESERVED_ORIGINAL_SOURCE_REQUIRED')
        actual=sha(pin(dict(path=source,sha256=change['corrected_sha256'])))
        result[source]=dict(original_sha256=original,original_snapshot=str(snapshot),executed_sha256=actual,
            source_correction_sha256=sha(path))
    return result


def checked(run):
    run=safe_d(run); cfg=json.loads((run/'run_config.json').read_text(encoding='utf-8'))
    d=json.loads((run/'DESIGN_FREEZE.json').read_text(encoding='utf-8')); gate=json.loads((run/'FORMAL_FREEZE_RECEIPT.json').read_text(encoding='utf-8'))
    q=json.loads((run/'INPUT_QUALIFICATION.json').read_text(encoding='utf-8'))
    require(cfg['research_id']==d['research_id']==gate['research_id']==ID,'C14_IDENTITY_REQUIRED')
    require(d.get('official_freeze') is True and d.get('formal_freeze_applied') is True and gate['status']=='PASS','FORMAL_FREEZE_PASS_REQUIRED_BEFORE_LABELS')
    for field,name in (('design_sha256','DESIGN_FREEZE.json'),('physical_dag_sha256','PHYSICAL_DAG.json'),('input_qualification_sha256','INPUT_QUALIFICATION.json')):
        require(gate[field]==sha(run/name),'FREEZE_RECEIPT_PIN_CHANGED:'+name)
    require(d.get('test2026_locked') is True and d.get('strict_PIT_promotion_eligible',False) is False and d.get('new2026_estimation_authorized',False) is False,'RESEARCH_ONLY_2026_LOCK_REQUIRED')
    require(d.get('feature_order',q['feature_order'])==feature_order(),'CURRENT216_ORDER_CHANGED')
    for ref in q['artifacts'].values(): pin(ref)
    checked_sources(run,d)
    return cfg,d,q


def label_pairs(run,d,q,cutoff,start='2023-01-01'):
    checked(run)
    require(cutoff in CUTS or cutoff=='2026-01-01','UNFROZEN_LABEL_CUTOFF')
    fields=[*KEYS,'U_t_fingerprint','target','target_end_date','ER_3D','ER_5D','ER_10D','ER_20D','target_end_date_20d']
    y=project(d['inputs']['hlabels'],fields,start=start,stop=cutoff,mature_before=cutoff,run=run)
    require(not y.duplicated(list(KEYS)).any(),'LABEL_IDENTITY_DUPLICATE')
    require(pd.to_datetime(y.target_end_date).equals(pd.to_datetime(y.target_end_date_20d)),'COMMON_20D_MATURITY_CHANGED')
    require(np.isfinite(y[['target','ER_3D','ER_5D','ER_10D','ER_20D']].to_numpy(float)).all(),'LABEL_FINITE_WHOLE_GEOMETRY_REQUIRED')
    require(np.allclose(y[['ER_3D','ER_5D','ER_10D','ER_20D']].mean(axis=1),y.target,rtol=0,atol=1e-12),'EQUAL_MEAN_TARGET_CHANGED')
    g=pq.read_table(pin(q['artifacts']['pair_geometry']),columns=list(PAIR_KEYS)).to_pandas();g.signal_date=pd.to_datetime(g.signal_date)
    raw=pq.read_table(pin(q['artifacts']['raw_current']),columns=[*KEYS,'U_t_fingerprint','label_end_date','raw_rank']).to_pandas();raw.signal_date=pd.to_datetime(raw.signal_date)
    validate_label_identity_clock(y,raw)
    dates=mature_dates(raw,start,cutoff);g=g.loc[g.signal_date.isin(dates)].reset_index(drop=True)
    sides=[]
    for uid in ('challenger_uid','incumbent_uid'):
        v=g[['signal_date',uid]].merge(y,left_on=['signal_date',uid],right_on=list(KEYS),how='left',validate='many_to_one',indicator=True)
        require(v['_merge'].eq('both').all(),'ALL_200_REQUIRED_LABELS_MISSING')
        sides.append(v)
    scalar=sides[0].target.to_numpy(float)-sides[1].target.to_numpy(float)
    tasks=sides[0][['ER_3D','ER_5D','ER_10D','ER_20D']].to_numpy(float)-sides[1][['ER_3D','ER_5D','ER_10D','ER_20D']].to_numpy(float)
    ends=pd.concat([pd.to_datetime(v.target_end_date) for v in sides],axis=1).max(axis=1)
    require(ends.lt(cutoff).all() and len(g)==len(dates)*200,'WHOLE_DATE_LABEL_MATURITY_REQUIRED')
    receipt=dict(cutoff=cutoff,start=start,dates=len(dates),pairs=len(g),pair_key_sha256=pairs.pair_key_sha256(g),
                 max_label_end=str(ends.max()),source_sha256=d['inputs']['hlabels']['sha256'],target='MEAN_ER_3D_5D_10D_20D',
                 label_key_sha256=content_hash(g.astype(str).values.tolist()),new_2026_rows=0)
    return g,scalar,tasks,ends,receipt


def validate_label_identity_clock(labels,raw):
    """Existing producer UID, full-U identity and mature endpoint must agree."""
    observed=labels[[*KEYS,'U_t_fingerprint','target_end_date']].merge(
        raw[[*KEYS,'U_t_fingerprint','label_end_date']].rename(columns={'U_t_fingerprint':'raw_U_t_fingerprint'}),
        on=list(KEYS),how='left',validate='one_to_one',indicator=True)
    require(observed['_merge'].eq('both').all(),'LABEL_UID_OUTSIDE_CURRENT_FULL_U')
    require(observed.U_t_fingerprint.eq(observed.raw_U_t_fingerprint).all(),'LABEL_FULL_U_IDENTITY_CHANGED')
    require(pd.to_datetime(observed.target_end_date).eq(pd.to_datetime(observed.label_end_date)).all(),'RAW_LABEL_COMMON20D_CLOCK_MISMATCH')


def physical_dag(design,q,component_specs):
    """All reservation slots before fitting; Jan2024 selected outer aliases native node."""
    nodes=[]
    def add(node,kind,**v): nodes.append(dict(node_id=node,kind=kind,**v))
    for c in CUTS: add('SCALER|'+c,'SCALER',cutoff=c)
    for binding in design['role_bindings']:
        p=binding['paradigm']
        cuts=CUTS[:-1] if p in WARMUP else CUTS[1:-1]
        for c in cuts:
            for cap in CAPACITIES:
                for component in component_specs(p):
                    s=component['seed'];quantile=component.get('quantile')
                    add(f'MODEL|{p}|{c}|{cap}|{s}|{quantile}','ESTIMATOR',paradigm=p,cutoff=c,capacity=cap,**component)
        for component in component_specs(p):
            add(f'MODEL|{p}|2025-01-01|SELECTED|{component["seed"]}|{component.get("quantile")}','ESTIMATOR',paradigm=p,cutoff='2025-01-01',capacity='SELECTED',**component)
        if p in FUSION_MEMBERS:
            for component in component_specs(p):
                add(f'MODEL|{p}|2025-01-01|MID|{component["seed"]}|{component.get("quantile")}', 'ESTIMATOR',paradigm=p,cutoff='2025-01-01',capacity='MID',conditional_alias='SELECTED_CAPACITY_IS_MID',**component)
        if p in WARMUP:
            for c in CUTS[1:]:
                for cap in CAPACITIES if c!='2025-01-01' else ('SELECTED',):
                    for kind in ('PLATT','SIGNED_AMPLITUDE'):
                        add(f'{kind}|{p}|{c}|{cap}',kind,paradigm=p,cutoff=c,capacity=cap)
    for year in (2024,2025):
        for method in FUSION_METHODS:
            # Each explicit backend/preprocessor has its own reservation.
            kinds=('META_MODEL','META_SCALER') if method in ('ridge_stack','elastic_stack','hgb_stack','mlp_stack') else ()
            if method in ('simplex','nnls'): kinds=('META_MODEL','META_TARGET_SCALE') if method=='simplex' else ('META_MODEL',)
            if method in ('linear_gate','mlp_gate'): kinds=('META_MODEL','META_SCALER','META_TARGET_SCALE')
            if method in ('ridge_then_hgb','hgb_then_ridge'): kinds=('META_SCALER','META_MODEL')
            for seed in META_SEEDS if method in META_STOCHASTIC else META_SEEDS[:1]:
                suffix=f'|{seed}' if method in META_STOCHASTIC else ''
                for kind in kinds:add(f'{kind}|{method}|{year}{suffix}',kind,method=method,year=year,seed=seed)
    require(len({n['node_id'] for n in nodes})==len(nodes),'DAG_DUPLICATE_PHYSICAL_NODE')
    require(len(nodes)<=1800,'ML_PHYSICAL_CAP_EXCEEDED')
    return dict(research_id=ID,nodes=nodes,backend_reservation=len(nodes),fusion_solver_requests=[f'FUSION_SOLVE|{m}|{y}' for m in ('simplex','nnls') for y in (2024,2025)],hard_cap=1800,scientific_retries=0,failed_reservation_refund=False,
                exact_outer_dates=q['outer_prediction_dates'],feature_order=feature_order(),model_specs_owner='selector_maximal_breadth_estimators',solve_request_ids=ml_solve_requests(design,q))


class Ledger:
    def __init__(self,run,dag):
        self.run=Path(run);self.path=self.run/'FIT_LEDGER.json';self.allowed={n['node_id']:n for n in dag['nodes']}
        if self.path.exists(): self.value=json.loads(self.path.read_text(encoding='utf-8'))
        else:
            self.value=dict(research_id=ID,design_sha256=sha(self.run/'DESIGN_FREEZE.json'),hard_cap=1800,scientific_retries=0,slots={n:dict(status='RESERVED',entered=0,**v) for n,v in self.allowed.items()});self.save()
        require(self.value['design_sha256']==sha(self.run/'DESIGN_FREEZE.json') and set(self.value['slots'])==set(self.allowed),'LEDGER_FREEZE_OR_SLOT_CHANGED')
    def save(self): write_json(self.path,self.value)
    def begin(self,node,identity):
        s=self.value['slots'][node]
        if s['status']=='COMPLETE': require(s['identity']==identity,'EXACT_MODEL_REUSE_IDENTITY_CHANGED');pin(s['artifact']);return False
        require(s['status']=='RESERVED','ZERO_RETRY_RESERVED_ONLY:'+node)
        s.update(status='STARTED',identity=identity);self.save();return True
    def entered(self,node,event=None):
        s=self.value['slots'][node];require(s['status']=='STARTED' and s['entered']==0,'DUPLICATE_BACKEND_ENTER')
        require(sum(v['entered'] for v in self.value['slots'].values())<1800,'BACKEND_CAP_EXHAUSTED')
        s.update(entered=1,event=event);self.save()
    def finish(self,node,status,**details):
        require(status in ('COMPLETE','FAILED','BLOCKED_DEPENDENCY'),'TERMINAL_STATUS_REQUIRED')
        self.value['slots'][node].update(status=status,**details);self.save()


def choose_capacity(records,expected_folds):
    losses={}
    for cap in CAPACITIES:
        rows=[r for r in records if r['capacity']==cap]
        if len(rows)!=len(expected_folds) or {(r['fit_cutoff'],r['validation_end']) for r in rows}!=set(expected_folds):continue
        if not all(r['status']=='COMPLETE' and r['dates']>0 and r['max_label_end']<r['validation_end'] and np.isfinite(r['sum_date_loss']) for r in rows):continue
        losses[cap]=sum(r['sum_date_loss'] for r in rows)/sum(r['dates'] for r in rows)
    if not losses:return None,losses
    best=min(losses.values())
    return next(c for c in CAPACITIES if c in losses and losses[c]==best),losses


def decode(raw,g,score,candidate_id,eligible=None,on_solve=None):
    """Thin C14 namespace/membership adapter around the existing exact matcher."""
    r=pairs._raw(raw,with_score=True);p=pairs._pairs(g)
    require(r.signal_date.nunique()==p.signal_date.nunique()==1,'SINGLE_DATE_DECODER')
    require(pairs.pair_key_sha256(pairs.geometry(r))==pairs.pair_key_sha256(p),'CURRENT_GEOMETRY_CHANGED')
    values=np.asarray(score,float);require(values.shape==(200,) and np.isfinite(values).all(),'FINITE_PAIR_UTILITY_REQUIRED')
    if on_solve is not None:on_solve()
    matched=pairs.maximum_weight_matching(p,values,eligible)
    return membership_panel(raw,matched,candidate_id),matched


def membership_panel(raw,matched,candidate_id):
    r=pairs._raw(raw,with_score=True)
    require(len(matched)<=10 and matched.challenger_uid.is_unique and matched.incumbent_uid.is_unique,'ONE_TO_ONE_CACHED_MATCH_REQUIRED')
    swaps=dict(zip(matched.incumbent_uid,matched.challenger_uid))
    top=[swaps.get(u,u) for u in r.loc[r.raw_rank.le(20),'security_uid']]
    require(len(set(top))==20 and set(r.loc[r.raw_rank.le(10),'security_uid']).issubset(top),'RAW_CORE20_CHANGED')
    order=top+[u for u in r.security_uid if u not in set(top)];ranks={u:i+1 for i,u in enumerate(order)}
    out=raw.copy();out['rank']=out.security_uid.map(ranks).astype(int);out['score']=-out['rank'].astype(float);out['candidate_id']=candidate_id
    return out


def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=('prepare','execute'));parser.add_argument('--run',required=True,type=Path)
    args=parser.parse_args()
    if args.command=='prepare': prepare(args.run,json.loads((args.run/'DESIGN_PROPOSAL.json').read_text(encoding='utf-8')))
    else: run(args.run)




def runtime_for(run,cfg):
    cache=safe_d(cfg['cache_directory']);assert_safe_output_path(cache,kind='cache',paths=resolve(REPO))
    for variable in ('TEMP','TMP','TMPDIR','JOBLIB_TEMP_FOLDER'): os.environ[variable]=str(cache/'temp')
    for variable in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[variable]='2'
    (cache/'temp').mkdir(parents=True,exist_ok=True)
    from scripts.research.a2.training.selector_challenge import runtime
    return runtime(Path(run))


def runtime_parts(rt):
    require(len(rt)==10 and hasattr(rt[8],'Fusion'),'SHARED_RUNTIME_TUPLE_CALIBRATION_OWNER_REQUIRED')
    return rt[5],rt[8]


def stored_fit(ledger,node,identity,model_path,fit):
    import joblib
    slot=ledger.value['slots'][node]
    if slot['status'] in ('FAILED','BLOCKED_DEPENDENCY'):return None
    if not ledger.begin(node,identity):return joblib.load(pin(slot['artifact']))
    try:
        from threadpoolctl import threadpool_limits
        with threadpool_limits(limits=2):model=fit(lambda event=None:ledger.entered(node,event))
        model_path=safe_d(model_path);model_path.parent.mkdir(parents=True,exist_ok=True)
        assert_safe_output_path(model_path,kind='backtest',paths=resolve(REPO));joblib.dump(model,model_path)
        ledger.finish(node,'COMPLETE',artifact=dict(path=str(model_path),sha256=sha(model_path)))
        return model
    except Exception as error:
        ledger.finish(node,'BLOCKED_DEPENDENCY' if isinstance(error,(ImportError,ModuleNotFoundError)) or str(error).startswith('BLOCKED_QUALIFIED_NATIVE_RUNTIME') else 'FAILED',error=str(error),traceback=traceback.format_exc())
        print(json.dumps(dict(phase='FIT_FAILED',slot=node,error=str(error))),flush=True)
        return None


def table_prediction(g,values,cutoff,capacity,paradigm):
    out=g[list(PAIR_KEYS)].copy();out['source_cutoff']=cutoff;out['source_capacity']=capacity;out['source_kind']='MODEL_OOF';out['paradigm']=paradigm;out['cutoff_clock']='MIDNIGHT_BEFORE_DECISION_CLOSE'
    for name,array in values.items():
        a=np.asarray(array,float);require(len(a)==len(g) and np.isfinite(a).all(),'WHOLE_NATIVE_PREDICTION_REQUIRED')
        if a.ndim==1:out[name]=a
        else:
            require(name=='tasks' and a.shape[1]==4,'REGISTERED_TASK_MATRIX_REQUIRED')
            for j in range(4):out[f'task_{(3,5,10,20)[j]}D']=a[:,j]
    return out


def values_from_table(frame):
    names=('point','prob','margin','mu','sigma','q10','q50','q90','within_variance','between_variance')
    out={k:frame[k].to_numpy(float) for k in names if k in frame}
    if 'task_3D' in frame:out['tasks']=frame[[f'task_{h}D' for h in (3,5,10,20)]].to_numpy(float)
    return out


def decision_values(values,rule):
    if rule=='U1_PROB_GT_0_5':
        p=np.asarray(values['prob'],float);require(np.isfinite(p).all() and ((p>=0)&(p<=1)).all(),'LEGAL_PROBABILITY_REQUIRED')
        return p-.5,p>.5
    if rule=='U2_Q10_GT0_MATCH_Q50':return np.asarray(values['q50'],float),np.asarray(values['q10'],float)>0
    if rule=='U3_MU_MINUS_SIGMA_GT0_MATCH_MU':return np.asarray(values['mu'],float),np.asarray(values['mu'],float)-np.asarray(values['sigma'],float)>0
    require(rule=='U0_POINT_GT0','OUTPUT_RULE_NOT_FROZEN')
    value=np.asarray(values['point'],float);return value,value>0


def calibration_history(history,cutoff,label_loader):
    if not history:return None
    h=pd.concat(history,ignore_index=True)
    h['signal_date']=pd.to_datetime(h.signal_date);h['source_cutoff']=pd.to_datetime(h.source_cutoff)
    require(h.source_kind.eq('MODEL_OOF').all() and h.cutoff_clock.eq('MIDNIGHT_BEFORE_DECISION_CLOSE').all() and h.source_cutoff.le(h.signal_date).all(),'REAL_OOF_REQUIRED_NO_RAW_OR_INSAMPLE')
    require(not h.duplicated(list(PAIR_KEYS)).any(),'CALIBRATION_OOF_KEYS_DUPLICATE')
    g,y,tasks,ends,receipt=label_loader(cutoff)
    rows=g.assign(target=y,label_end_date=ends.to_numpy())
    h=h.merge(rows,on=list(PAIR_KEYS),how='inner',validate='one_to_one')
    require(h.signal_date.lt(cutoff).all() and pd.to_datetime(h.label_end_date).lt(cutoff).all(),'CALIBRATION_PAST_MATURE_REQUIRED')
    return h


def fit_platt(run,ledger,p,cap,cutoff,history,label_loader):
    from sklearn.linear_model import LogisticRegression
    h=calibration_history(history,cutoff,label_loader)
    if h is None or h.empty or len(np.unique(h.target>0))<2:return None
    identity=dict(paradigm=p,cutoff=cutoff,capacity=cap,source_kind='MODEL_OOF',
                  keys_sha256=pairs.pair_key_sha256(h),prediction_sha256=hashlib.sha256(h.margin.to_numpy('<f8').tobytes()).hexdigest(),
                  label_sha256=hashlib.sha256(h.target.to_numpy('<f8').tobytes()).hexdigest(),max_label_end=str(pd.to_datetime(h.label_end_date).max()),
                  spec=dict(C=1.,max_iter=400,random_state=20260928),date_weights='1/200')
    node=f'PLATT|{p}|{cutoff}|{cap}'
    def fit(entered):
        entered(dict(operation='Platt_logistic_fit'))
        return LogisticRegression(C=1.,max_iter=400,random_state=20260928).fit(h[['margin']],h.target.gt(0),sample_weight=np.full(len(h),.005))
    model=stored_fit(ledger,node,identity,Path(run)/'models'/(content_hash(node)+'.joblib'),fit)
    ampnode=f'SIGNED_AMPLITUDE|{p}|{cutoff}|{cap}'
    def amp_fit(entered):
        entered(dict(operation='OOF_signed_amplitude_estimation'))
        return dict(plus=float(h.loc[h.target.gt(0),'target'].mean()),minus=float(h.loc[h.target.le(0),'target'].mean()))
    amps=stored_fit(ledger,ampnode,identity,Path(run)/'models'/(content_hash(ampnode)+'.joblib'),amp_fit)
    return None if model is None or amps is None else dict(model=model,amplitudes=amps,identity=identity)


def apply_platt(values,calibrator):
    require(calibrator is not None,'BLOCKED_GENUINE_OOF_PLATT_REQUIRED')
    out={k:np.asarray(v).copy() for k,v in values.items()};out['prob']=calibrator['model'].predict_proba(pd.DataFrame({'margin':out['margin']}))[:,1]
    a=calibrator['amplitudes'];out['calibrated_edge']=out['prob']*a['plus']+(1-out['prob'])*a['minus']
    return out


def objective_loss(paradigm,values,y,tasks):
    if paradigm=='LOGIT' or paradigm in WARMUP and 'prob' in values:return (values['prob']-(y>0))**2
    if paradigm in WARMUP:raise ValueError('BLOCKED_GENUINE_OOF_PLATT_REQUIRED_FOR_FROZEN_BRIER')
    if paradigm=='QUANTILE_HGB':
        return np.mean([np.maximum(q*(y-values[name]),(q-1)*(y-values[name])) for q,name in ((.1,'q10'),(.5,'q50'),(.9,'q90'))],axis=0)
    if paradigm=='GAUSSIAN_MLP':return np.log(values['sigma'])+.5*((y-values['mu'])/values['sigma'])**2
    if paradigm.startswith('MT_'):return np.mean((values['tasks']-tasks)**2,axis=1)
    return (values['point']-y)**2


def aligned_training(g,all_g,xx):
    index=pd.MultiIndex.from_frame(all_g[list(PAIR_KEYS)]).get_indexer(pd.MultiIndex.from_frame(g[list(PAIR_KEYS)]))
    require((index>=0).all(),'TRAIN_KEY_NOT_IN_FROZEN_GEOMETRY')
    return xx[index]


def model_identity(p,capacity,cutoff,g,xx,y,tasks,spec,component,q):
    return dict(research_id=ID,paradigm=p,capacity=capacity,cutoff=cutoff,pair_key_sha256=pairs.pair_key_sha256(g),
                feature_sha256=hashlib.sha256(np.ascontiguousarray(xx,dtype='<f8').tobytes()).hexdigest(),
                target_sha256=hashlib.sha256(np.ascontiguousarray(tasks if p.startswith('MT_') else y,dtype='<f8').tobytes()).hexdigest(),
                feature_order=feature_order(),weight_policy='all200 date_mass1',component=component,spec=spec,
                source_input_sha256=q['input_sources']['hlabels']['sha256'],source_kind='CHRONOLOGICAL_PAST_FIT')


def scaler_at(run,ledger,c,g,xx,q):
    from sklearn.preprocessing import StandardScaler
    node='SCALER|'+c
    identity=dict(cutoff=c,feature_order=feature_order(),pair_key_sha256=pairs.pair_key_sha256(g),
                  feature_sha256=hashlib.sha256(np.ascontiguousarray(xx,dtype='<f8').tobytes()).hexdigest(),weight_policy='date_mass1;all200equal')
    def fit(entered):entered(dict(operation='weighted_scaler_fit'));return StandardScaler().fit(xx,sample_weight=np.full(len(xx),.005))
    return stored_fit(ledger,node,identity,Path(run)/'models'/(content_hash(node)+'.joblib'),fit)


def fit_bundle(run,ledger,kernel,p,cap,c,train,xx,y,tasks,scaler,vx,runtime,q,selected=False):
    if scaler is None:return None
    values={};spec=kernel.capacity_specs()[p][cap]
    for component in kernel.component_specs(p):
        seed=component['seed'];quantile=component.get('quantile');capacity_node='SELECTED' if selected else cap
        node=f'MODEL|{p}|{c}|{capacity_node}|{seed}|{quantile}'
        identity=model_identity(p,cap,c,train,xx,y,tasks,spec,component,q)
        if c==CUTS[-1] and not selected and cap=='MID' and p in FUSION_MEMBERS and ledger.value['slots'][node]['status']=='RESERVED':
            original=f'MODEL|{p}|{c}|SELECTED|{seed}|{quantile}';source=ledger.value['slots'][original]
            if source['status']=='COMPLETE' and source['identity']==identity:
                ledger.value['slots'][node].update(status='COMPLETE',identity=identity,artifact=source['artifact'],alias_of=original,entered=0);ledger.save()
        def fit(entered):
            return kernel.fit_component(p,scaler.transform(xx),y,tasks,train.signal_date,train.challenger_uid,train.incumbent_uid,cap,seed,quantile,runtime=runtime,on_fit=entered)
        model=stored_fit(ledger,node,identity,Path(run)/'models'/(content_hash(node)+'.joblib'),fit)
        if model is not None:values[(seed,quantile)]=kernel.predict_component(model,vx)
    if len(values)!=len(kernel.component_specs(p)):return None
    return kernel.combine_predictions(p,values)


def solve_state(run):
    run=Path(run);path=run/'SOLVE_LEDGER.json';journal=run/'SOLVE_EVENTS.jsonl'
    if str(run) not in SOLVES:
        ledger=json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(research_id=ID,hard_cap=30000,requests={})
        if journal.exists():
            with journal.open(encoding='utf-8') as stream:
                for line in stream:
                    row=json.loads(line);ledger['requests'][row['token']]=row['receipt']
        require(ledger['research_id']==ID and ledger['hard_cap']==30000,'SOLVE_IDENTITY_CHANGED')
        SOLVES[str(run)]=ledger
    return SOLVES[str(run)]


def append_solve(run,token,row):
    journal=Path(run)/'SOLVE_EVENTS.jsonl'
    assert_safe_output_path(journal,kind='backtest',paths=resolve(REPO))
    with safe_d(journal).open('a',encoding='utf-8') as stream:
        stream.write(json.dumps(dict(token=token,receipt=row),separators=(',',':'),default=str)+'\n');stream.flush()


def solve_callback(run,token):
    """Append-only charged requests plus bounded snapshots; no failed refund."""
    run=Path(run);ledger=solve_state(run);requests=ledger['requests']
    require(token not in requests,'DUPLICATE_SOLVE_REQUEST_NO_RETRY')
    require(len(requests)<30000,'SOLVE_CAP_EXHAUSTED')
    dagpath=run/'PHYSICAL_DAG.json'
    if dagpath.exists():
        stamp=(dagpath.stat().st_size,dagpath.stat().st_mtime_ns)
        if str(run) not in SOLVE_DAGS:
            dag=json.loads(dagpath.read_text(encoding='utf-8'));allowed=dag.get('solve_request_ids',dag.get('ml',{}).get('solve_request_ids'))
            require(allowed is not None,'FROZEN_SOLVER_REQUESTS_REQUIRED');SOLVE_DAGS[str(run)]=(stamp,set(allowed))
        require(SOLVE_DAGS[str(run)][0]==stamp and token in SOLVE_DAGS[str(run)][1],'UNFROZEN_SOLVER_REQUEST')
    row=dict(status='ENTERED',charged=1);requests[token]=row;append_solve(run,token,row)
    if len(requests)%50==0:flush_solve_ledger(run)


def complete_solve(run,token,**receipt):
    state=solve_state(run);row=state['requests'][token]
    require(row['status'] in ('ENTERED','COMPLETE'),'SOLVE_TERMINAL_FAILURE_NOT_RETRYABLE')
    row.update(status='COMPLETE',**receipt);append_solve(run,token,row)
    if len(state['requests'])%50==0:flush_solve_ledger(run)


def checkpoint_decode(run,token,raw,g,score,cid,eligible):
    values=np.asarray(score,dtype='<f8');ok=np.asarray(eligible,bool)
    identity=dict(design_sha256=sha(Path(run)/'DESIGN_FREEZE.json'),pair_key_sha256=pairs.pair_key_sha256(g),candidate_id=cid,
                  full_U_keys_sha256=content_hash(raw[[*KEYS,'raw_rank','U_t_fingerprint']].astype(str).values.tolist()),
                  score_sha256=hashlib.sha256(values.tobytes()).hexdigest(),eligibility_sha256=hashlib.sha256(ok.tobytes()).hexdigest())
    old=solve_state(run)['requests'].get(token)
    if old is not None:
        require(old['status']=='COMPLETE' and 'matching_records' in old,'BLOCKED_CHARGED_DECODER_NO_COMPLETE_CACHE')
        require(old['identity']==identity,'DECODER_CHECKPOINT_IDENTITY_CHANGED')
        records=old['matching_records'];require(content_hash(records)==old['matching_sha256'],'DECODER_CHECKPOINT_BYTES_CHANGED')
        matched=pd.DataFrame(records,columns=[*PAIR_KEYS,'predicted_edge'])
        if len(matched):
            matched.signal_date=pd.to_datetime(matched.signal_date)
            linked=matched.merge(g.assign(_input_score=values,_eligible=ok),on=list(PAIR_KEYS),validate='one_to_one',how='left')
            require(linked._input_score.notna().all() and np.array_equal(linked.predicted_edge.to_numpy(float),linked._input_score.to_numpy(float)) and linked._eligible.all() and linked.predicted_edge.gt(0).all(),'CACHED_MATCH_NOT_IN_IDENTICAL_INPUT')
        return membership_panel(raw,matched,cid),matched
    panel,matched=decode(raw,g,values,cid,ok,on_solve=lambda:solve_callback(run,token))
    # Preserve exact Python float roundtrips in the compact journal.
    records=[]
    for row in matched.to_dict('records'):
        records.append({k:(v.isoformat() if isinstance(v,pd.Timestamp) else int(v) if isinstance(v,np.integer) else float(v) if isinstance(v,np.floating) else v) for k,v in row.items()})
    complete_solve(run,token,identity=identity,matching_records=records,matching_sha256=content_hash(records))
    return panel,matched


def flush_solve_ledger(run):
    if str(Path(run)) in SOLVES:write_json(Path(run)/'SOLVE_LEDGER.json',SOLVES[str(Path(run))])


def decode_days(run,raw,g,values,rule,cid,prefix):
    score,eligible=decision_values(values,rule); panels=[];matched=[]
    for date,ix in g.groupby('signal_date',sort=True).indices.items():
        r=raw.loc[raw.signal_date.eq(date)].copy();day=g.iloc[ix]
        out,matches=checkpoint_decode(run,f'{prefix}|{date.isoformat()}',r,day,score[ix],cid,eligible[ix])
        panels.append(out);matched.append(matches)
    return pd.concat(panels,ignore_index=True),pd.concat(matched,ignore_index=True)


def inner_record(run,p,cap,c,end,g,values,y,tasks,ends,raw):
    dates=g.signal_date.nunique();require(len(g)==dates*200 and np.isfinite(y).all(),'COMPLETE_INNER_GEOMETRY_REQUIRED')
    if p=='LISTWISE_MLP':
        panel,chosen=decode_days(run,raw,g,values,'U0_POINT_GT0','INNER',f'INNER|{p}|{cap}|{c}')
        truth=g.assign(realized_edge=y);chosen=chosen.merge(truth,on=list(PAIR_KEYS),validate='one_to_one')
        daily=-(chosen.groupby('signal_date').realized_edge.sum().reindex(sorted(g.signal_date.unique()),fill_value=0)/20)
    else:
        losses=objective_loss(p,values,y,tasks);require(np.isfinite(losses).all(),'FINITE_NATIVE_VALIDATION_LOSS_REQUIRED')
        daily=pd.Series(losses).groupby(g.signal_date.reset_index(drop=True)).mean()
    return dict(paradigm=p,capacity=cap,fit_cutoff=c,validation_end=end,status='COMPLETE',dates=dates,
                max_label_end=str(pd.to_datetime(ends).max()),sum_date_loss=float(daily.sum()),
                native_loss='negative_exact_matched_edge_sum_over20' if p=='LISTWISE_MLP' else 'fixed_native_objective',
                validation_key_sha256=pairs.pair_key_sha256(g))


def fusion_identity(method,year,g,mu,y,xx,contexts):
    return dict(method=method,year=year,members=list(FUSION_MEMBERS),source_kind='MODEL_OOF',
                pair_key_sha256=pairs.pair_key_sha256(g),mu_sha256=hashlib.sha256(np.ascontiguousarray(mu,dtype='<f8').tobytes()).hexdigest(),
                target_sha256=hashlib.sha256(np.ascontiguousarray(y,dtype='<f8').tobytes()).hexdigest(),
                x_sha256=hashlib.sha256(np.ascontiguousarray(xx,dtype='<f8').tobytes()).hexdigest(),
                context_sha256=hashlib.sha256(np.ascontiguousarray(contexts,dtype='<f8').tobytes()).hexdigest(),
                date_weights='1/200; full earlier genuineOOF; no sampling',capacity='FIXED_MID_META')


def fit_fusion_full(run,ledger,cal,method,year,g,mu,y,xx,context,seed=None):
    """Reuse retained statistical objects; adapt six members/full OOF/residual source."""
    from scipy.optimize import minimize, nnls
    from scripts.research.a2.training.selector_cooperation import LinearFusion
    from sklearn.preprocessing import StandardScaler
    if method in META_STOCHASTIC and seed is None:
        models=[fit_fusion_full(run,ledger,cal,method,year,g,mu,y,xx,context,seed=s) for s in META_SEEDS]
        return None if any(v is None for v in models) else dict(kind='seed_ensemble',models=models,seeds=list(META_SEEDS))
    seed=META_SEEDS[0] if seed is None else seed
    w=np.full(len(g),.005);identity=fusion_identity(method,year,g,mu,y,xx,context);identity['seed']=seed
    suffix=f'|{seed}' if method in META_STOCHASTIC else ''
    if method in ('equal','median'):return dict(kind='native',model=cal.Fusion(method,list(FUSION_MEMBERS)))
    modelnode=f'META_MODEL|{method}|{year}{suffix}';scnode=f'META_SCALER|{method}|{year}{suffix}'
    def aux(kind,fit):
        node=f'{kind}|{method}|{year}{suffix}'
        return stored_fit(ledger,node,identity,Path(run)/'models'/(content_hash(node)+'.joblib'),fit)
    if method=='nnls':
        def fit(entered):
            entered(dict(operation='NNLS_full_OOF'));solve_callback(run,f'FUSION_SOLVE|{method}|{year}');root=np.sqrt(w)
            coef,_=nnls(mu*root[:,None],y*root)
            return dict(kind='linear',model=LinearFusion(method,list(FUSION_MEMBERS),coef))
        return stored_fit(ledger,modelnode,identity,Path(run)/'models'/(content_hash(modelnode)+'.joblib'),fit)
    if method=='simplex':
        def scale_fit(entered):entered(dict(operation='target_RMS_estimation'));return max(float(np.sqrt(np.average(y*y,weights=w))),1e-6)
        scale=aux('META_TARGET_SCALE',scale_fit)
        if scale is None:return None
        def fit(entered):
            entered(dict(operation='SLSQP_simplex_full_OOF'));solve_callback(run,f'FUSION_SOLVE|{method}|{year}');x=mu/scale;target=y/scale
            result=minimize(lambda a:float(np.average((x@a-target)**2,weights=w)),np.full(6,1/6),
                jac=lambda a:2*x.T@(w*(x@a-target))/w.sum(),method='SLSQP',bounds=[(0.,1.)]*6,
                constraints=[dict(type='eq',fun=lambda a:a.sum()-1,jac=lambda a:np.ones_like(a))],options=dict(maxiter=500,ftol=1e-10))
            require(result.success,'SIMPLEX_NOT_CONVERGED_NO_RETRY')
            return dict(kind='linear',model=LinearFusion(method,list(FUSION_MEMBERS),result.x))
        return stored_fit(ledger,modelnode,identity,Path(run)/'models'/(content_hash(modelnode)+'.joblib'),fit)
    if method in ('linear_gate','mlp_gate'):
        # The retained composite owns its scaler, target RMS and network fit.
        # Reserve all three before entering; failures retain conservative charge.
        auxiliary=(scnode,f'META_TARGET_SCALE|{method}|{year}{suffix}')
        for node in auxiliary:
            if ledger.value['slots'][node]['status']=='RESERVED':
                ledger.begin(node,identity);ledger.entered(node,dict(operation='retained_Gate_composite_state_reservation'))
        def fit(entered):
            from types import FunctionType
            entered(dict(operation='retained_Gate_full_OOF_fit',seed=seed))
            original=cal.Gate.fit;isolated=FunctionType(original.__code__,dict(original.__globals__,SEED=seed),original.__name__,original.__defaults__,original.__closure__)
            gate=cal.Gate(method=='mlp_gate');isolated(gate,mu,context,y,w)
            return dict(kind='gate',model=gate,seed=seed)
        obj=stored_fit(ledger,modelnode,identity,Path(run)/'models'/(content_hash(modelnode)+'.joblib'),fit)
        for node in auxiliary:
            if ledger.value['slots'][node]['status']=='STARTED':
                if obj is None:ledger.finish(node,'FAILED',error='RETAINED_GATE_DEPENDENCY_FAILURE_CONSERVATIVE_RESERVATION')
                else:ledger.finish(node,'COMPLETE',artifact=ledger.value['slots'][modelnode]['artifact'],composite_owner_state=True)
        return obj
    residual=method in ('ridge_then_hgb','hgb_then_ridge')
    source=xx if residual else mu
    def scaler_fit(entered):entered(dict(operation='meta_weighted_scaler_fit'));return StandardScaler().fit(source,sample_weight=w)
    scaler=aux('META_SCALER',scaler_fit)
    if scaler is None:return None
    target=y-mu[:,0 if method=='ridge_then_hgb' else 1] if residual else y
    def fit(entered):
        if method in ('ridge_stack','hgb_then_ridge'):model=cal.Ridge(alpha=100.)
        elif method=='elastic_stack':model=cal.ElasticNet(alpha=1e-5,l1_ratio=.35,max_iter=2500,tol=1e-5,random_state=20260928)
        elif method in ('hgb_stack','ridge_then_hgb'):model=cal.tree()
        elif method=='mlp_stack':model=cal.MLPRegressor(hidden_layer_sizes=(32,),max_iter=10,batch_size=512,learning_rate_init=.001,alpha=.0001,random_state=seed,early_stopping=False)
        else:raise ValueError('FUSION_NOT_FROZEN')
        entered(dict(operation='residual_stage2_genuineOOF' if residual else 'meta_model_full_OOF'))
        model.fit(scaler.transform(source),target,sample_weight=w)
        return dict(kind='residual' if residual else 'stack',model=model,scaler=scaler,base_index=0 if method=='ridge_then_hgb' else 1)
    return stored_fit(ledger,modelnode,identity,Path(run)/'models'/(content_hash(modelnode)+'.joblib'),fit)


def predict_fusion(model,mu,xx,context):
    if model['kind']=='seed_ensemble':
        require(model['seeds']==list(META_SEEDS) and len(model['models'])==3,'ALL_META_SEEDS_REQUIRED_NO_PICKING')
        return np.mean([predict_fusion(v,mu,xx,context) for v in model['models']],axis=0)
    if model['kind'] in ('native','linear'):return model['model'].predict(mu,context)
    if model['kind']=='gate':return model['model'].predict(mu,context)
    if model['kind']=='residual':return mu[:,model['base_index']]+model['model'].predict(model['scaler'].transform(xx))
    return model['model'].predict(model['scaler'].transform(mu))


def fusion_history(oof,cutoff,label_loader,all_g,xx,frame):
    fixed=[]
    for p in FUSION_MEMBERS:
        if p not in oof or not oof[p]:return None
        h=pd.concat(oof[p],ignore_index=True)
        require(h.source_kind.eq('MODEL_OOF').all() and h.cutoff_clock.eq('MIDNIGHT_BEFORE_DECISION_CLOSE').all() and pd.to_datetime(h.source_cutoff).le(pd.to_datetime(h.signal_date)).all(),'FUSION_TRUE_OOF_NOT_RAW_OR_INSAMPLE')
        require(not h.duplicated(list(PAIR_KEYS)).any(),'FUSION_OOF_DUPLICATE')
        fixed.append(h)
    basekeys=fixed[0][list(PAIR_KEYS)]
    if not all(basekeys.equals(h[list(PAIR_KEYS)]) for h in fixed[1:]):return None
    g,y,tasks,ends,receipt=label_loader(cutoff)
    target=g.assign(target=y,label_end_date=ends.to_numpy())
    h=basekeys.merge(target,on=list(PAIR_KEYS),how='inner',validate='one_to_one')
    require(len(h)>0 and pd.to_datetime(h.label_end_date).lt(cutoff).all(),'FUSION_PAST_MATURE_KEYS_REQUIRED')
    indices=pd.MultiIndex.from_frame(basekeys).get_indexer(pd.MultiIndex.from_frame(h[list(PAIR_KEYS)]));require((indices>=0).all(),'OOF_ALIGNMENT_REQUIRED')
    mu=np.column_stack([v['q50'].to_numpy(float)[indices] if p=='QUANTILE_HGB' else v['point'].to_numpy(float)[indices] for p,v in zip(FUSION_MEMBERS,fixed)])
    require(np.isfinite(mu).all(),'ALL_SIX_FUSION_MEMBERS_REQUIRED')
    x=aligned_training(h,all_g,xx)
    contexts=context_features(frame,h)
    lineage=dict(member_prediction_sha256={p:content_hash(v[list(PAIR_KEYS)+['source_cutoff','source_capacity']].astype(str).values.tolist()) for p,v in zip(FUSION_MEMBERS,fixed)},
                 cutoff=cutoff,dates=h.signal_date.nunique(),pairs=len(h),max_label_end=str(pd.to_datetime(h.label_end_date).max()),
                 genuine_oof=True,no_raw_fallback=True,no_in_sample=True,member_order=list(FUSION_MEMBERS))
    return h[list(PAIR_KEYS)],mu,h.target.to_numpy(float),x,contexts,lineage


def context_features(frame,g):
    fields=('ret_1d','ret_20d','realized_vol_20d','realized_vol_60d','volume_ratio_5d_20d')
    a=g[['signal_date','challenger_uid']].merge(frame[[*KEYS,*fields]],left_on=['signal_date','challenger_uid'],right_on=list(KEYS),how='left',validate='many_to_one')
    b=g[['signal_date','incumbent_uid']].merge(frame[[*KEYS,*fields]],left_on=['signal_date','incumbent_uid'],right_on=list(KEYS),how='left',validate='many_to_one')
    context=a[list(fields)].to_numpy(float)-b[list(fields)].to_numpy(float)
    require(not np.isinf(context).any(),'CONTEXT_INFINITY_FORBIDDEN')
    return np.where(np.isfinite(context),context,0.)


def terminalize_unused(ledger):
    for slot in ledger.value['slots'].values():
        if slot['status']=='RESERVED':slot.update(status='BLOCKED_DEPENDENCY',reason='UNENTERED_DEPENDENCY_OR_UNUSED_RESERVED_NODE')
    ledger.save()


def run(run):
    run=Path(run);require(not (run/'SOURCE_CORRECTION.json').exists(),'POSTFIT_CORRECTION_FORBIDS_TRAINING')
    cfg,d,q=checked(run)
    require(not (run/'ML_DELIVERY_COMPLETE.json').exists(),'NO_RESTART_COMPLETED_C14_ML')
    from scripts.research.a2.training import selector_maximal_breadth_estimators as kernel
    rt=runtime_for(run,cfg);pred,cal=runtime_parts(rt)
    dag=json.loads((run/'PHYSICAL_DAG.json').read_text(encoding='utf-8'));ml_dag=dag.get('ml',dag)
    ledger=Ledger(run,ml_dag)
    raw=pq.read_table(pin(q['artifacts']['raw_current'])).to_pandas();raw.signal_date=pd.to_datetime(raw.signal_date)
    all_g=pq.read_table(pin(q['artifacts']['pair_geometry'])).to_pandas();all_g.signal_date=pd.to_datetime(all_g.signal_date)
    features=pq.read_table(pin(q['artifacts']['current_pair_features'])).to_pandas();xx=features[feature_order()].to_numpy(float)
    require(pairs.pair_key_sha256(all_g)==q['pair_key_sha256'] and features[list(PAIR_KEYS)].equals(all_g[list(PAIR_KEYS)]),'PREPARED_GEOMETRY_CHANGED')
    label_cache={}
    def labels(c):
        if c not in label_cache:label_cache[c]=label_pairs(run,d,q,c)
        return label_cache[c]
    roles=d['role_bindings'];native={};calibrators={};histories={};oof={};scalers={};records=[];choices={};outer={};fixed_banks={};lineage={};oof_receipts={}
    for i,c in enumerate(CUTS):
        train,y,tasks,ends,label_receipt=labels(c)
        require(ends.lt(c).all(),'TRAIN_MATURITY_BREACH')
        tx=aligned_training(train,all_g,xx);scaler=scaler_at(run,ledger,c,train,tx,q);scalers[c]=scaler
        write_json(run/'diagnostics'/f'LABEL_READ_{c}.json',label_receipt)
        end=CUTS[i+1] if i<len(CUTS)-1 else '2026-01-01'
        vg=all_g.loc[all_g.signal_date.ge(c)&all_g.signal_date.lt(end)].reset_index(drop=True)
        vx=aligned_training(vg,all_g,xx);scaled=scaler.transform(vx) if scaler is not None else None
        for binding in roles:
            p=binding['paradigm'];cid=binding['candidate_id']
            if c==CUTS[0] and p not in WARMUP:continue
            caps=CAPACITIES if c!=CUTS[-1] else (choices.get((2025,p)),)
            for cap in caps:
                if cap is None or scaled is None:continue
                progress(run,ledger,'C14_FIT',cutoff=c,paradigm=p,capacity=cap,train_pairs=len(train),prediction_pairs=len(vg))
                values=fit_bundle(run,ledger,kernel,p,cap,c,train,tx,y,tasks,scaler,scaled,pred,q,selected=c==CUTS[-1])
                if values is None:continue
                table=table_prediction(vg,values,c,cap,p)
                native[(p,c,cap)]=table
                if p in WARMUP:
                    calibrator=fit_platt(run,ledger,p,'SELECTED' if c==CUTS[-1] else cap,c,histories.get((p,cap),[]),labels) if c!=CUTS[0] else None
                    calibrators[(p,c,cap)]=calibrator
                    histories.setdefault((p,cap),[]).append(table)
                    if calibrator is not None:values=apply_platt(values,calibrator)
                native_path=run/'predictions'/'native_oof'/f'{p}_{c}_{cap}.parquet'
                if not native_path.exists():write_table(native_path,table)
                oof_receipts[f'{p}|{c}|{cap}']=dict(prediction=dict(path=str(native_path),sha256=sha(native_path)),cutoff=c,cutoff_clock='MIDNIGHT_BEFORE_DECISION_CLOSE',capacity=cap,source_kind='MODEL_OOF',pair_key_sha256=pairs.pair_key_sha256(vg),train_pair_key_sha256=pairs.pair_key_sha256(train),spec=kernel.capacity_specs()[p][cap],component_nodes=[f'MODEL|{p}|{c}|{"SELECTED" if c==CUTS[-1] else cap}|{s["seed"]}|{s.get("quantile")}' for s in kernel.component_specs(p)],scaler_node='SCALER|'+c,no_raw_fallback=True,no_in_sample=True)
                if c in CUTS[1:4]:
                    valid,vy,vt,ve,vr=labels(end)
                    valid=valid.loc[valid.signal_date.ge(c)].reset_index(drop=True)
                    rowindex=pd.MultiIndex.from_frame(labels(end)[0][list(PAIR_KEYS)]).get_indexer(pd.MultiIndex.from_frame(valid[list(PAIR_KEYS)]))
                    predindex=pd.MultiIndex.from_frame(vg[list(PAIR_KEYS)]).get_indexer(pd.MultiIndex.from_frame(valid[list(PAIR_KEYS)]))
                    require((predindex>=0).all() and (rowindex>=0).all(),'VALIDATION_WHOLE_KEY_ALIGNMENT')
                    vv={k:a[predindex] for k,a in values.items()}
                    if p in WARMUP and 'prob' not in vv:
                        record=dict(paradigm=p,capacity=cap,fit_cutoff=c,validation_end=end,status='BLOCKED_DEPENDENCY',dates=valid.signal_date.nunique(),max_label_end=str(pd.to_datetime(ve.iloc[rowindex]).max()),reason='GENUINE_OOF_PLATT_REQUIRED_FOR_FIXED_BRIER')
                    else:
                        try:record=inner_record(run,p,cap,c,end,valid,vv,vy[rowindex],vt[rowindex],ve.iloc[rowindex],raw)
                        except ValueError as error:
                            if not str(error).startswith('BLOCKED_CHARGED_DECODER_NO_COMPLETE_CACHE'):raise
                            record=dict(paradigm=p,capacity=cap,fit_cutoff=c,validation_end=end,status='FAILED',dates=valid.signal_date.nunique(),max_label_end=str(pd.to_datetime(ve.iloc[rowindex]).max()),reason=str(error))
                    records.append(record)
                if p in FUSION_MEMBERS and (c==CUTS[1] and cap=='MID' or c in CUTS[2:4] and cap=='MID'):
                    oof.setdefault(p,[]).append(table)
            if c==CUTS[1]:
                selected,losses=choose_capacity([r for r in records if r['paradigm']==p],[(CUTS[1],CUTS[2])]);choices[(2024,p)]=selected
            if c==CUTS[3]:
                selected,losses=choose_capacity([r for r in records if r['paradigm']==p and r['fit_cutoff'] in CUTS[2:4]],[(CUTS[2],CUTS[3]),(CUTS[3],CUTS[4])]);choices[(2025,p)]=selected
        if c in (CUTS[2],CUTS[4]):
            year=int(c[:4]);yearg=all_g.loc[all_g.signal_date.dt.year.eq(year)].reset_index(drop=True)
            futurex=scaler.transform(aligned_training(yearg,all_g,xx)) if scaler is not None else None
            for binding in roles:
                p=binding['paradigm'];cap=choices.get((year,p))
                if cap is None or futurex is None:continue
                values=values_from_table(native[(p,c,cap)]) if year==2025 and (p,c,cap) in native else fit_bundle(run,ledger,kernel,p,cap,c,train,tx,y,tasks,scaler,futurex,pred,q,selected=year==2025)
                if values is None:continue
                if p in WARMUP:
                    calibrator=calibrators.get((p,c,cap))
                    if calibrator is None:continue
                    values=apply_platt(values,calibrator)
                outer[(p,year)]=(yearg,values,table_prediction(yearg,values,c,cap,p))
            fh=fusion_history(oof,c,labels,all_g,xx,raw)
            if fh is not None and futurex is not None:
                for member in FUSION_MEMBERS:
                    prediction=fit_bundle(run,ledger,kernel,member,'MID',c,train,tx,y,tasks,scaler,futurex,pred,q,selected=False)
                    if prediction is not None:fixed_banks[(member,year)]=prediction
            if fh is not None and all((p,year) in fixed_banks for p in FUSION_MEMBERS):
                hg,mu,hy,hx,hcontext,receipt=fh;receipt['all_base_capacities']='MID';lineage[str(year)]=receipt
                future_mu=np.column_stack([fixed_banks[(p,year)]['q50' if p=='QUANTILE_HGB' else 'point'] for p in FUSION_MEMBERS])
                future_x=aligned_training(yearg,all_g,xx);future_context=context_features(raw,yearg)
                for binding in d['fusion_bindings']:
                    method=binding['method'].lower().replace('ridge_hgb_residual','ridge_then_hgb').replace('hgb_ridge_residual','hgb_then_ridge')
                    model=fit_fusion_full(run,ledger,cal,method,year,hg,mu,hy,hx,hcontext)
                    if model is None:continue
                    value=np.asarray(predict_fusion(model,future_mu,future_x,future_context),float)
                    require(value.shape==(len(yearg),) and np.isfinite(value).all(),'COMPLETE_FUSION_OUTPUT_REQUIRED')
                    outer[(binding['candidate_id'],year)]=(yearg,dict(point=value),table_prediction(yearg,dict(point=value),c,'FIXED_MID_META',binding['candidate_id']))
        write_json(run/'CAPACITY_SELECTION.json',dict(records=records,choices={f'{y}|{p}':cap for (y,p),cap in choices.items()},fusion_oof_lineage=lineage))
        write_json(run/'OOF_LINEAGE.json',oof_receipts)
        flush_solve_ledger(run)
    panels={};natives={};failures={};raw2023=raw.loc[raw.signal_date.dt.year.eq(2023)].copy()
    for binding in roles+d['fusion_bindings']:
        cid=binding['candidate_id'];p=binding.get('paradigm',cid);rule=binding.get('output_rule','U0_POINT_GT0')
        if not all((p,year) in outer for year in (2024,2025)):
            failures[cid]='BLOCKED_INCOMPLETE_LEARNED_OUTER_OR_MEMBER_DEPENDENCY';continue
        forecasts=[];matches=[];native_tables=[]
        fallback=raw2023.copy();fallback['score']=fallback.raw_score;fallback['rank']=fallback.raw_rank;fallback['candidate_id']=cid
        forecasts.append(fallback)
        decoder_failed=False
        for year in (2024,2025):
            g,values,table=outer[(p,year)]
            try:panel,match=decode_days(run,raw,g,values,rule,cid,f'MAIN|{cid}')
            except ValueError as error:
                if not str(error).startswith('BLOCKED_CHARGED_DECODER_NO_COMPLETE_CACHE'):raise
                failures[cid]=str(error);decoder_failed=True;break
            forecasts.append(panel);matches.append(match);native_tables.append(table)
        if decoder_failed:continue
        panel=pd.concat(forecasts,ignore_index=True);native_table=pd.concat(native_tables,ignore_index=True);matched=pd.concat(matches,ignore_index=True)
        panel=panel[[*KEYS,'ticker','U_t_fingerprint','score','rank','candidate_id']]
        panels[cid]=write_table(run/'predictions'/f'scores_{cid}_pre2026.parquet',panel)
        panels[cid].update(calendar_dates=752,common_rows=len(raw),raw_fallback_2023_exact=True)
        native_ref=write_table(run/'predictions'/f'native_pairs_{cid}_pre2026.parquet',native_table)
        match_ref=write_table(run/'predictions'/f'matching_{cid}_pre2026.parquet',matched)
        natives[cid]=dict(native_ref,kind=rule,matching_path=match_ref['path'],matching_sha256=match_ref['sha256'])
    terminalize_unused(ledger);flush_solve_ledger(run)
    assembly=dict(status='ML_ASSEMBLY_COMPLETE',research_id=ID,design_freeze_sha256=sha(run/'DESIGN_FREEZE.json'),
        pair_key_sha256=q['pair_key_sha256'],full_U_keys_sha256=q['full_U_keys_sha256'],complete_candidates=list(panels),
        failed_or_untestable=failures,panels=panels,native_pair_predictions=natives,forecast2026_rows=0,
        current_input=True,previous_or_lag_input=False,all_training_terminal=True,capacity_selection_complete=True,
        fit_ledger_sha256=sha(run/'FIT_LEDGER.json'),capacity_selection_sha256=sha(run/'CAPACITY_SELECTION.json'),oof_lineage_sha256=sha(run/'OOF_LINEAGE.json'),
        genuine_fusion_oof_lineage=lineage,scientific_retry=0,source_preservation={p:sha(pin(dict(path=p,sha256=s))) for p,s in d['sources'].items()})
    write_json(run/'ML_ASSEMBLY.json',assembly)
    write_json(run/'ML_DELIVERY_COMPLETE.json',dict(status='ML_COMPLETE',research_id=ID,assembly_sha256=sha(run/'ML_ASSEMBLY.json'),fit_ledger_sha256=sha(run/'FIT_LEDGER.json')))
    progress(run,ledger,'ML_COMPLETE',complete_candidates=len(panels),failed_or_untestable=len(failures))
    return assembly

def ml_solve_requests(design,q):
    raw=pq.read_table(pin(q['artifacts']['raw_current']),columns=['signal_date']).to_pandas()
    outer=sorted(pd.to_datetime(raw.signal_date).loc[pd.to_datetime(raw.signal_date).ge('2024-01-01')].unique())
    tokens=[f'MAIN|{b["candidate_id"]}|{pd.Timestamp(day).isoformat()}' for b in design['role_bindings']+design['fusion_bindings'] for day in outer]
    for window,dates in q['validation_dates'].items():
        cut=window.split(':')[0]
        for cap in CAPACITIES:
            tokens.extend(f'INNER|LISTWISE_MLP|{cap}|{cut}|{pd.Timestamp(day).isoformat()}' for day in dates)
    tokens.extend(f'FUSION_SOLVE|{m}|{year}' for m in ('simplex','nnls') for year in (2024,2025))
    require(len(tokens)==len(set(tokens)),'DUPLICATE_FROZEN_SOLVE_TOKEN')
    return tokens


def progress(run,ledger,phase,**metadata):
    counts={state:sum(s['status']==state for s in ledger.value['slots'].values()) for state in ('COMPLETE','FAILED','BLOCKED_DEPENDENCY','STARTED','RESERVED')}
    row=dict(research_id=ID,phase=phase,updated_at=now(),entered=sum(s['entered'] for s in ledger.value['slots'].values()),counts=counts,
             fit_budget_cap=1800,scientific_retry=0,test2026_locked=True,outcome_metrics_in_state=False,**metadata)
    write_json(Path(run)/'PIPELINE_STATE.json',row);print(json.dumps(row),flush=True)

if __name__=='__main__': main()
