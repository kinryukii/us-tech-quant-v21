"""R6 fixed risk execution; reuses original projected reader, assembler and memo.
Metadata prepare has no value columns. fit requires accepted R6 whole-freeze
admission before constructing a numeric reader. No R5 bank/result is consumed.
"""
from __future__ import annotations
import argparse
from dataclasses import replace
from pathlib import Path
import json,os,joblib
import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pyarrow.parquet as pq
from threadpoolctl import threadpool_limits
from scripts.common.storage_paths import resolve,assert_safe_output_path
from scripts.research.a2.evaluation import joint_frozen_history_risk_r3 as old
from scripts.research.a2.evaluation import joint_short_risk_execution_r4 as transport
from scripts.research.a2.evaluation import joint_method_space_runtime_r6 as runtime
from scripts.research.a2.evaluation.joint_method_space_design_r6 import ID
from scripts.research.a2.data.joint_held_identity_completion_r5 import _metadata_projection
from scripts.research.a2.data.shared_risk_inputs_r3 import assemble_risk_inputs,_calendar,_clock
from scripts.research.a2.risk.shared_risk_engine_r2 import _panel,META
from scripts.research.a2.risk.shared_risk_budget_r2 import StateBudget,StateCache,LEARNED_KINDS,content_hash
from scripts.research.a2.risk import joint_method_space_risk_r6 as model

PLAN='support/R6_RISK_EVENT_PLAN.json'
QUAL='support/R6_RISK_METADATA_QUALIFICATION_R1.json'
BANK='models/risk/R6_RISK_BANK.json'
SOURCE_SHA='04d17931c7437f9c7bc1277b33820c52ec2e527a995b0f1c587dc26f5b2c2fd8'
PARENT_META_SHA='1244eaa9cf160c7f6566009e33ba35bdd6844fcdd2a69f95e025c07914d2a54f'
IDENTITY_COLUMNS=('signal_date','ticker','security_uid','asset_epoch','segment_start','identity_qualified','source_qualified','class_coordinate_status','is_current_pool')
BACKENDS={'r6:pca':'PCA_FULL_SVD','r6:huber_pca':'PCA_FULL_SVD','r6:market_lw':'LEDOIT_WOLF','r6:graphical_lasso':'GRAPHICAL_LASSO_CD','r6:pooled_gpd_tail':'GPD_L_BFGS_B'}
class Blocked(ValueError):pass

def ref(path):
    p=Path(path);return dict(source_ref=str(p.resolve()),sha256=old.sha(p),bytes=p.stat().st_size)
def _path(r):return Path(r.get('source_ref',r.get('path',''))).resolve()
def _pin_ref(r,label):
    p=_path(r);old._safe_source(p);old._pin(p,r['sha256'],label);return p

def source_binding(run):
    run=Path(run).resolve();paths=resolve(old.REPO);assert_safe_output_path(run,kind='backtest',paths=paths)
    if run.parent!=paths.backtest_root/'V24':raise Blocked('MANAGED_R6_RUN_REQUIRED')
    a=old.read_json(run/'SOURCE_AUTHORITY.json')
    if (a.get('research_id')!=ID or a.get('source_inputs_sha256')!=SOURCE_SHA or a.get('test2026_reads')!=0 or
        any(a.get(k) is not False for k in ('EF_access','network_provider_fetch','R5_numeric_economic_read','quote_qualified','strict_PIT_promotion_eligible','certified_nav_qualified'))):raise Blocked('EXACT_R6_WEAK_SOURCE_BOUNDARY_REQUIRED')
    p=old._safe_source(a['source_inputs_ref']);old._pin(p,SOURCE_SHA,'R3_ORIGINAL_SOURCE_BYTES')
    source=_metadata_projection(p,{'schema','research_id','sources','family_design_freeze_sha256'})
    original=p.parent/'FAMILY_DESIGN_FREEZE.json';old._pin(original,source['family_design_freeze_sha256'],'SOURCE_BYTES_OBSERVATION_FREEZE')
    snapshot=_metadata_projection(original,{'actual_snapshot_timestamp'})['actual_snapshot_timestamp']
    return run,source,a,snapshot

def load_plan(run,plan_ref):
    p=_pin_ref(plan_ref,'R6_EVENT_PLAN')
    if p!=Path(run).resolve()/PLAN:raise Blocked('CURRENT_R6_PLAN_PATH_REQUIRED')
    plan=old.read_json(p) # fixed 15MiB source-only metadata, existing 32MiB bound.
    if (plan.get('schema')!='B_R6_PRIMARY_EVENT_PLAN_METADATA_V1' or plan.get('research_id')!=ID or len(plan.get('events',[]))!=55 or
        len(plan.get('decision_dates',[]))!=752 or len(plan.get('q_dates',[]))!=143 or
        any(plan.get(k)!=0 for k in ('numeric_reads','return_value_reads','outcome_reads','test2026_reads')) or
        plan.get('R5_numeric_economic_read') is not False or plan['source_metadata_parent_ref']['sha256']!=PARENT_META_SHA):raise Blocked('EXACT_R6_ZERO_VALUE_PLAN_REQUIRED')
    old._pin(Path(run)/'SOURCE_AUTHORITY.json',plan['source_authority_ref']['sha256'],'PLAN_R6_AUTHORITY')
    return plan

def validate_event(event,days):
    day=pd.Timestamp(event['decision_date']);i=days.get_indexer([day])[0]
    if i<=0 or day>=old.BOUNDARY:raise Blocked('LEGAL_PRE2026_CURRENT_EVENT_REQUIRED')
    asof,cutoff=_clock(day),_clock(days[i-1]);assets=tuple(event['requested_assets'])
    if (pd.Timestamp(event['decision_asof'])!=asof or pd.Timestamp(event['fit_history_cutoff'])!=cutoff or pd.Timestamp(event['current_identity_available_at'])!=asof):raise Blocked('CURRENT_AND_PRIOR_LEGAL_CLOCKS_REQUIRED')
    if not assets or assets!=tuple(sorted(set(assets))):raise Blocked('FULL_ORDERED_DOMAIN_REQUIRED')
    for key in ('asset_uids','asset_epochs','segment_starts'):
        if set(event[key])!=set(assets) or any(not isinstance(v,str) or not v.strip() or v.strip().upper() in {'UNKNOWN','NONE','NULL','UNBOUND','NAN','?'} for v in event[key].values()):raise Blocked('KNOWN_COMPLETE_CURRENT_UID_EPOCH_REQUIRED')
    if len(set(event['asset_uids'].values()))!=len(assets):raise Blocked('DUPLICATE_CURRENT_UID')
    return asof,cutoff,assets

def identity_pool(rows,event,days):
    asof,cutoff,assets=validate_event(event,days);day=pd.Timestamp(event['decision_date'])
    if not set(IDENTITY_COLUMNS).issubset(rows):raise Blocked('R6_UID_SIDECAR_SCHEMA_REQUIRED')
    rows=rows.copy();rows.signal_date=pd.to_datetime(rows.signal_date)
    if rows.signal_date.ge(old.BOUNDARY).any() or rows.signal_date.gt(day).any():raise Blocked('NO_FUTURE_IDENTITY_BODY')
    if rows.duplicated(['signal_date','ticker']).any():raise Blocked('AMBIGUOUS_CURRENT_IDENTITY_KEYS')
    now=rows.loc[rows.signal_date.eq(day)]
    if tuple(sorted(now.loc[now.is_current_pool.eq(True),'ticker']))!=assets:raise Blocked('FULL_CURRENT_REQUESTED_POOL_CHANGED_NO_SHRINK')
    now=now.set_index('ticker').loc[list(assets)]
    if not (now.identity_qualified.eq(True)&now.source_qualified.eq(True)&now.class_coordinate_status.eq('EXACT_FROZEN_INTERVAL_COORDINATE_FOR_MECHANISM')).all():raise Blocked('CURRENT_UID_CLASS_SOURCE_UNQUALIFIED')
    if (now.security_uid.to_dict()!=event['asset_uids'] or now.asset_epoch.to_dict()!=event['asset_epochs'] or now.segment_start.to_dict()!=event['segment_starts']):raise Blocked('CURRENT_UID_EPOCH_OR_SEGMENT_CHANGED')
    history=rows.loc[rows.ticker.isin(assets),['ticker','signal_date','security_uid','asset_epoch']].rename(columns={'security_uid':'security_id','asset_epoch':'identity_epoch'})
    history['available_at']=history.signal_date.map(_clock)
    return dict(assets=assets,asset_uids=dict(event['asset_uids']),asset_epochs=dict(event['asset_epochs']),segment_starts=dict(event['segment_starts']),blocked_assets={},history=history),asof,cutoff

def assemble_context(*,labels,base_uids,identity,qqq,source,science,days,event,numeric=False):
    pool,asof,cutoff=identity_pool(identity,event,days)
    if not numeric and any(old.FORBIDDEN.intersection(f.columns) for f in (labels,base_uids,identity,qqq)):raise Blocked('METADATA_VALUE_PROJECTION_FORBIDDEN')
    metadata=labels.loc[:,list(old.LABEL_META)].copy()
    bound=labels.merge(base_uids,on=['ticker','signal_date'],how='left',validate='one_to_one')
    bound=bound.merge(pool['history'][['ticker','signal_date','identity_epoch']],on=['ticker','signal_date'],how='left',validate='many_to_one')
    if not numeric:bound['y_open5']=np.nan # unavailable marker, never an observed zero.
    epoch='R6_OBSERVED_CURRENT_UIDS:'+content_hash(pool['asset_epochs'])
    primary=old._receipt(source,science,cutoff,epoch);benchmark=old._receipt(source,science,cutoff,'EXISTING_QQQ_QFQ_OPEN_PROXY',benchmark=True)
    assembly=assemble_risk_inputs(bound,days,assets=pool['assets'],asset_uids=pool['asset_uids'],asset_epochs=pool['asset_epochs'],identity_epoch=epoch,
        source_receipt=primary,cutoff=cutoff,identity_history=pool['history'],qqq_opens=qqq if numeric else None,qqq_receipt=benchmark if numeric else None)
    typed=assembly.risk_input
    if not numeric:typed=transport.qqq_metadata_only(typed,qqq,source,science,days,cutoff)
    keys=transport.source_support_keys(typed,metadata,base_uids,pool)
    origins=pd.DatetimeIndex(typed.observations.origin_at.unique()).sort_values()[-252:];frozen=event['history_support']
    if len(origins)!=252 or [v.tz_convert('America/New_York').date().isoformat() for v in origins]!=frozen['parent_origins']:raise Blocked('FIXED_PARENT_252_WINDOW_CHANGED')
    exact=keys.loc[keys.origin_at.isin(origins)];counts=exact.loc[exact.qualified].groupby('asset').size();observed={a:int(counts.get(a,0)) for a in pool['assets']}
    if observed!=frozen['nominal_n']:raise Blocked('NOMINAL_METADATA_SUPPORT_CHANGED')
    q=typed.qqq_observations;q_ok=q is not None and set(origins).issubset(set(q.origin_at))
    support=dict(event_id=event['event_id'],primary_signature_sha256=event.get('primary_signature_sha256'),
        QQQ_event_id=event.get('qqq_event_id'),QQQ_signature_sha256=event.get('qqq_signature_sha256'),parent_origin_window=[v.isoformat() for v in origins],parent_origin_window_sha256=content_hash(list(origins)),
        assets=list(pool['assets']),asset_uids=pool['asset_uids'],asset_epochs=pool['asset_epochs'],segment_starts=pool['segment_starts'],nominal_n=observed,
        classical_complete_cohort=[a for a,n in observed.items() if n==252],donors=[a for a,n in observed.items() if n>=60],QQQ_full_window_support=q_ok,
        as_of=asof.isoformat(),cutoff=cutoff.isoformat(),maturity_keys_sha256=content_hash(typed.observations.loc[:,list(META)]),
        primary_source_sha256=primary.source_sha256,benchmark_source_sha256=benchmark.source_sha256,
        strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False)
    support['risk_support_identity']=content_hash(support)
    return typed,support,assembly.support_declarations

def exact_mature_values(reader,source,typed_metadata,pool,support,prior_day):
    """Mechanical exact-key adapter over the already pinned ProjectedReader."""
    keys=transport.source_support_keys(typed_metadata,pool['label_metadata'],pool['base_uid_metadata'],pool['identity_pool'])
    keys=keys.loc[keys.qualified & keys.origin_at.isin(pd.DatetimeIndex(support['parent_origin_window'])),['asset','origin_at']]
    if keys.duplicated().any():raise Blocked('DUPLICATE_EXACT_SOURCE_VALUE_KEY')
    pin=source['sources']['extended_shareholder_y5'];d=reader.datasets[str(Path(pin['path']).resolve())]
    expr=None
    # Assets sharing the same observed origin set share one predicate term.
    grouped={}
    for asset,rows in keys.groupby('asset',sort=False):
        dates=tuple(sorted(v.tz_convert('America/New_York').date().isoformat() for v in rows.origin_at))
        grouped.setdefault(dates,[]).append(asset)
    for dates,assets in grouped.items():
        term=ds.field('signal_date').isin([reader._scalar(d,'signal_date',v) for v in dates])&ds.field('ticker').isin(assets)
        expr=term if expr is None else expr|term
    if expr is None:return pd.DataFrame(columns=['ticker','signal_date','y_open5'])
    expr&=ds.field('signal_date')<reader._scalar(d,'signal_date',old.BOUNDARY)
    for c in ('execution_date','label_end_date','label_mature_date'):
        expr&=ds.field(c)<reader._scalar(d,c,prior_day)
    expr&=ds.field('label_available')==True
    expr&=ds.field('endpoint_pair_available')==True
    expr&=ds.field('label_unsupported_common_event')==False
    expr&=ds.field('label_coordinate')==transport.STORED_LABEL_COORDINATE
    result=d.to_table(columns=['ticker','signal_date','y_open5'],filter=expr).to_pandas()
    reader.audit.append(dict(source='extended_shareholder_y5',columns=['ticker','signal_date','y_open5'],
        exact_source_qualified_key_sha256=content_hash(keys),strict_mature_before=str(prior_day),rows=len(result),prebody_exact_uid_epoch_source_predicate=True))
    return result


class InputLoader:
    def __init__(self,run,source,snapshot,identity_ref,*,freeze_sha=None,reader=None,identity_reader=None):
        self.authorised=freeze_sha is not None
        if self.authorised:runtime.guard_numeric(run,freeze_sha) # precedes reader/body.
        self.run=Path(run);self.source=source;self.identity_reader=identity_reader
        self.reader=reader if reader is not None else old.ProjectedReader(source,phase='fit' if self.authorised else 'support')
        self.days,_=_calendar(self.reader.read('calendar',('trade_date',),date_field='trade_date').trade_date)
        if identity_reader is None:
            p=_pin_ref(identity_ref,'R6_IDENTITY_SIDECAR')
            if p!=self.run.resolve()/'support/R6_SEQUENCE_IDENTITY_ROWS.parquet':raise Blocked('CURRENT_R6_UID_SIDECAR_REQUIRED')
            f=pq.ParquetFile(p);ci=f.schema.names.index('signal_date')
            for i in range(f.metadata.num_row_groups):
                st=f.metadata.row_group(i).column(ci).statistics
                if not st or not st.has_min_max or pd.Timestamp(st.max)>=old.BOUNDARY:raise Blocked('PRE2026_UID_FOOTER_REQUIRED')
            self.identity_dataset=ds.dataset(p,format='parquet')
        self.science=dict(scientific_contract_identity=ID,scientific_contract_sha256=freeze_sha or old.sha(self.run/'SOURCE_AUTHORITY.json'),actual_snapshot_timestamp=snapshot)
    def identity(self,start,day):
        if self.identity_reader is not None:return self.identity_reader(start=start,day=day,stop=day+pd.Timedelta(days=1))
        d=self.identity_dataset
        expr=(ds.field('signal_date')>=old.ProjectedReader._scalar(d,'signal_date',start))&(ds.field('signal_date')<=old.ProjectedReader._scalar(d,'signal_date',day))&(ds.field('signal_date')<old.ProjectedReader._scalar(d,'signal_date',old.BOUNDARY))
        return d.to_table(columns=list(IDENTITY_COLUMNS),filter=expr).to_pandas()
    def load(self,event,*,numeric=False,metadata_context=None):
        if numeric and not self.authorised:raise Blocked('R6_NUMERIC_ADMISSION_REQUIRED')
        asof,cutoff,assets=validate_event(event,self.days);day=pd.Timestamp(event['decision_date']);j=self.days.get_loc(day)-1;start=self.days[max(0,j-306)];prior_day=self.days[j]
        identity=self.identity(start,day);identity_pool(identity,event,self.days) # before value request.
        labels=self.reader.read('extended_shareholder_y5',old.LABEL_META,date_field='signal_date',start=start,stop=prior_day,tickers=assets,mature_before=prior_day)
        base=self.reader.read('shareholder_y5',('ticker','signal_date','security_id'),date_field='signal_date',start=start,stop=prior_day,tickers=assets)
        if numeric:
            if metadata_context is None:raise Blocked('PREBODY_QUALIFIED_METADATA_CONTEXT_REQUIRED')
            meta_typed,meta_support=metadata_context
            pool,_,_=identity_pool(identity,event,self.days)
            values=exact_mature_values(self.reader,self.source,meta_typed,
                dict(label_metadata=labels,base_uid_metadata=base,identity_pool=pool),meta_support,prior_day)
            labels=labels.merge(values,on=['ticker','signal_date'],how='left',validate='one_to_one')
        qqq=self.reader.read('qqq_qfq_years',('ticker','trade_date')+(('open',) if numeric else ()),date_field='trade_date',start=self.days[max(0,j-360)],stop=prior_day,tickers=('QQQ',))
        return assemble_context(labels=labels,base_uids=base,identity=identity,qqq=qqq,source=self.source,science=self.science,days=self.days,event=event,numeric=numeric)

def method_qualification(s):
    donor=len(s['donors'])>=5;q=s['QQQ_full_window_support'];cohort=len(s['classical_complete_cohort']);full=cohort==len(s['assets']);result={}
    for m in model.METHODS:
        reason=None
        if m=='NONLINEAR':reason='BLOCKED_DEPENDENCY_GENUINE_NONLINEAR_BACKEND_UNBOUND'
        elif m=='EVT' and not full:reason='BLOCKED_INPUT_FULL_GENUINE_JOINT_EVT_SCENARIOS_INCOMPLETE'
        elif m in {'SEMIVARIANCE','EMPIRICAL_CVAR'} and not full:reason='BLOCKED_INPUT_FULL_JOINT_SCENARIOS_INCOMPLETE'
        elif m in {'EMPIRICAL_CVAR','EVT'} and not (donor and q):reason='BLOCKED_SOURCE_SAME_UID_CUTOFF_POSTERIOR_COVARIANCE_AUXILIARY'
        elif m in {'HIER_POSTERIOR','BAYES_FACTOR','POSTERIOR_PREDICTIVE','AVERAGE'} and not (donor and q):reason='BLOCKED_SOURCE_DONOR_OR_QQQ_PRIOR_UNBOUND'
        elif m not in {'SEMIVARIANCE','EMPIRICAL_CVAR','HIER_POSTERIOR','BAYES_FACTOR','POSTERIOR_PREDICTIVE'}:
            if cohort<(5 if m in {'DYNAMIC_FACTOR','ROBUST_FACTOR','POET','AVERAGE'} else 1):reason='BLOCKED_INPUT_NO_FIXED_CLASSICAL_COMPONENT'
            elif not full and not (donor and q):reason='BLOCKED_SOURCE_FULL_DOMAIN_PRIOR_UNBOUND'
            elif m=='KALMAN' and not q:reason='BLOCKED_SOURCE_QQQ_FACTOR_UNBOUND'
        result[m]=dict(status='METADATA_QUALIFIED_NUMERIC_FINITE_UNKNOWN' if reason is None else 'BLOCKED_SOURCE_OR_INPUT',reason=reason)
    return result

def prepare(run,plan_ref,identity_ref):
    run,source,_,snapshot=source_binding(run);plan=load_plan(run,plan_ref)
    with runtime.stage_writer(run,'qualification'):
        loader=InputLoader(run,source,snapshot,identity_ref);rows=[]
        for event in plan['events']:
            row=dict(event_id=event['event_id'],as_of=event['decision_asof'],cutoff=event['fit_history_cutoff'])
            try:
                _,s,d=loader.load(event);row.update(status='METADATA_PROJECTED',support=s,methods=method_qualification(s),original_inference_support=d['inference_support'])
            except (ValueError,KeyError,TypeError) as error:row.update(status='BLOCKED_METADATA',reason=str(error),methods={m:dict(status='BLOCKED_METADATA',reason=str(error)) for m in model.METHODS})
            rows.append(row)
        out=dict(schema='B_R6_RISK_METADATA_QUALIFICATION_V1',research_id=ID,event_plan_ref=plan_ref,identity_ref=identity_ref,source_authority_ref=ref(run/'SOURCE_AUTHORITY.json'),nodes=rows,
            evt_source_profile=model.specification()['evt_source_requirements'],reader_projection_audit=loader.reader.audit,source_code_pins=code_pins(),numeric_reads=0,new_fit=0,R5_results_reads=0,test2026_reads=0,strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False)
        old.write(run,QUAL,out,immutable=True);return out


def _artifact(run,relative,value):
    p=Path(run)/relative;assert_safe_output_path(p,kind='backtest',paths=resolve(old.REPO));p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():raise Blocked('IMMUTABLE_R6_ARTIFACT_ALREADY_EXISTS')
    temp=p.with_suffix(p.suffix+'.tmp');joblib.dump(value,temp,compress=3)
    with temp.open('r+b') as handle:os.fsync(handle.fileno())
    os.replace(temp,p);return ref(p)

def _commit_exact_paid_cache(run,ledger,row):
    """Commit only canonically bound, already-computed own temp; no fit authority."""
    run=Path(run).resolve()
    paid=runtime.guard_io_recovery(run,ledger.freeze_sha) # full canonical/code guard before any joblib body.
    required={'key','node_id','result_sha256','cache_event_sha256','temp_ref','final_path',
              'recovery_receipt_relative','failed_ledger_snapshot_ref','custody_ref','io_equivalence_ref'}
    if not isinstance(paid,dict) or set(paid)!=required:raise Blocked('EXACT_CANONICAL_PAID_RECOVERY_SCHEMA_REQUIRED')
    before=content_hash(ledger.status);key=paid['key'];event=row.get('details',{}).get('cache_event',{})
    if (row.get('node_id')!='risk:'+key or paid['node_id']!=row['node_id'] or row.get('status')!='FAILED_NONREFUNDABLE'
        or row.get('kind')!='estimator_learned_state_fit' or row.get('physical_kind')!='scaler' or row.get('units')!=1
        or event.get('name')!='r6:market_mean' or event.get('kind')!='scaler' or event.get('status')!='FAILED'
        or event.get('key')!=key or event.get('result_sha256')!=paid['result_sha256']
        or row['details'].get('error_type')!='OSError' or row['details'].get('error')!='[Errno 9] Bad file descriptor'
        or row['details'].get('backend_invocations')!=0):raise Blocked('EXACT_PAID_PUBLICATION_FAILURE_REQUIRED')
    if (content_hash(event)!=paid['cache_event_sha256'] or
        content_hash({k:event[k] for k in ('kind','name','context','inputs_sha256','parameters')})!=key):
        raise Blocked('PAID_SCIENTIFIC_KEY_OR_EVENT_PROOF_CHANGED')
    snapshot=_pin_ref(paid['failed_ledger_snapshot_ref'],'PAID_FAILURE_SNAPSHOT')
    if snapshot!=run/'work/risk_io_failure/R6_PHYSICAL_LEDGER_AT_FAILURE_R1.json':raise Blocked('OWN_FIXED_FAILURE_SNAPSHOT_REQUIRED')
    frozen=old.read_json(snapshot)
    if (frozen.get('freeze_sha256')!=ledger.freeze_sha or ledger.status.get('freeze_sha256')!=ledger.freeze_sha
        or frozen.get('research_id')!=ID or len(frozen.get('physical_events',[]))!=1
        or content_hash(frozen['physical_events'][0])!=content_hash(row)
        or frozen['actual_counts'].get('estimator_learned_state_fit')!=1
        or any(ledger.status['actual_counts'].get(k,-1)<v for k,v in frozen['actual_counts'].items())):
        raise Blocked('ORIGINAL_FAILURE_AND_NONREFUNDABLE_DEBIT_REQUIRED')
    custody_path=_pin_ref(paid['custody_ref'],'PAID_FAILURE_CUSTODY')
    if custody_path!=run/'work/R6_RISK_IO_FAILURE_CUSTODY_R1.json':raise Blocked('OWN_PAID_FAILURE_CUSTODY_REQUIRED')
    custody=old.read_json(custody_path);proof=custody.get('cache_operation',{})
    if (custody.get('research_id')!=ID or custody.get('status')!='STOPPED_ENGINEERING_IO_FAILURE_NO_RESTART'
        or custody['original_science_freeze_ref']['sha256']!=ledger.freeze_sha
        or custody['immutable_failed_ledger_snapshot_ref']['sha256']!=paid['failed_ledger_snapshot_ref']['sha256']
        or content_hash(custody['paid_event'])!=content_hash({k:row[k] for k in custody['paid_event']})
        or any(proof.get(k)!=event.get(k) for k in ('key','name','kind','status','inputs_sha256','result_sha256'))
        or proof.get('context_sha256')!=content_hash(event['context'])
        or proof.get('parameters_sha256')!=content_hash(event['parameters'])
        or proof.get('scientific_key_rederived') is not True):
        raise Blocked('FULL_ORIGINAL_PAID_CUSTODY_CHANGED')
    io_path=_pin_ref(paid['io_equivalence_ref'],'CANONICAL_IO_EQUIVALENCE')
    if io_path!=run/'R6_EXECUTION_IO_EQUIVALENCE_R1.json':raise Blocked('OWN_CANONICAL_IO_EQUIVALENCE_REQUIRED')
    final=run/'models/risk/primitives'/f'{key}.joblib';temp=final.with_suffix('.joblib.tmp')
    if (Path(paid['final_path']).resolve()!=final or _path(paid['temp_ref'])!=temp
        or paid['recovery_receipt_relative']!='work/R6_PAID_CACHE_RECOVERY_R1.json'
        or paid['temp_ref'].get('bytes')!=25
        or custody['serialized_temp_ref']['sha256']!=paid['temp_ref']['sha256']
        or custody['serialized_temp_ref']['bytes']!=paid['temp_ref']['bytes']
        or Path(custody['serialized_temp_ref']['path']).resolve()!=temp
        or Path(custody['intended_final_path']).resolve()!=final):
        raise Blocked('EXACT_OWN_TEMP_DESTINATION_CUSTODY_REQUIRED')
    assert_safe_output_path(final,kind='backtest',paths=resolve(old.REPO))
    if final.exists():
        if temp.exists():raise Blocked('PAID_FINAL_AND_TEMP_COLLISION')
        old._pin(final,paid['temp_ref']['sha256'],'PAID_EXACT_PREVIOUSLY_RENAMED_FILE')
        if final.stat().st_size!=paid['temp_ref']['bytes']:raise Blocked('PAID_RENAMED_SIZE_CHANGED')
        source=final # exact rename-before-receipt crash recovery, not a fit retry.
    else:
        source=_pin_ref(paid['temp_ref'],'PAID_SERIALIZED_TEMP')
        if source.stat().st_size!=paid['temp_ref']['bytes']:raise Blocked('PAID_SERIALIZED_SIZE_CHANGED')
    value=joblib.load(source) # only canonical-bound own paid artifact after all metadata proofs.
    if content_hash(value)!=paid['result_sha256']:raise Blocked('PAID_VALUE_PROOF_CHANGED_NO_REESTIMATION')
    if content_hash(ledger.status)!=before:raise Blocked('PAID_FAILURE_LEDGER_MUTATED')
    if source==temp:
        with temp.open('r+b') as handle:os.fsync(handle.fileno())
        os.replace(temp,final)
    artifact=ref(final)
    if artifact['sha256']!=paid['temp_ref']['sha256'] or artifact['bytes']!=paid['temp_ref']['bytes']:
        raise Blocked('PAID_COMMIT_PHYSICAL_PROOF_CHANGED')
    receipt=dict(schema='B_R6_PAID_CACHE_RECOVERY_RECEIPT_V1',research_id=ID,whole_freeze_sha256=ledger.freeze_sha,
        status='EXACT_PAID_ARTIFACT_COMMITTED_NO_NEW_FIT',node_id=row['node_id'],key=key,
        io_equivalence_ref=paid['io_equivalence_ref'],canonical_paid_binding_sha256=content_hash(paid),
        failure_snapshot_ref=paid['failed_ledger_snapshot_ref'],failure_custody_ref=paid['custody_ref'],
        original_cache_event_sha256=paid['cache_event_sha256'],result_sha256=paid['result_sha256'],artifact_ref=artifact,
        producer_ref=ref(Path(__file__)),original_status='FAILED_NONREFUNDABLE',original_failure_preserved=True,
        paid_units=1,new_reservations=0,new_compute_invocations=0,new_backend_invocations=0,scientific_retry=0,
        refund=False,original_failed_row_sha256=content_hash(row),original_failed_snapshot_sha256=paid['failed_ledger_snapshot_ref']['sha256'],strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False)
    old.write(run,paid['recovery_receipt_relative'],receipt,immutable=True)
    if content_hash(ledger.status)!=before:raise Blocked('PAID_FAILURE_LEDGER_MUTATED')
    return dict(status='SUCCEEDED',value=value,result_sha256=paid['result_sha256']),ref(run/paid['recovery_receipt_relative'])

class RiskOperations:
    """StateCache is sole memo; existing R6Ledger is sole durable authority."""
    def __init__(self,ledger,run,*,persist=True):
        self.ledger,self.run,self.persist=ledger,Path(run),persist
        self.budget=StateBudget(1705,reserve_callback=self.reserve);self.cache=None;self.restored={}
        for row in ledger.status['physical_events']:
            if not row['node_id'].startswith('risk:'):continue
            key=row['node_id'][5:];kind=row['physical_kind']
            if kind not in self.budget.counts or row['units']!=int(kind in LEARNED_KINDS):raise Blocked('EXACT_R6_RISK_PHYSICAL_DEBIT_REQUIRED')
            details=row.get('details',{});event=details.get('cache_event',dict(key=key,kind=kind,name='INTERRUPTED_BEFORE_COMMIT',context={}))
            if event.get('key')!=key or event.get('kind')!=kind:raise Blocked('R6_LEDGER_CACHE_EVENT_CHANGED')
            self.budget.counts[kind]+=1;self.budget._keys.add(key)
            event=dict(event,status='SUCCEEDED' if row['status']=='COMPLETE' else 'FAILED');self.budget.events.append(event);record=dict(status='FAILED')
            if row['status']=='COMPLETE':
                if not self.persist:record=details['synthetic_cache_record']
                else:
                    a=details['artifact_ref'];p=_pin_ref(a,'R6_OWN_COMPLETED_LEARNED_STATE')
                    if p.parent!=self.run.resolve()/'models/risk/primitives':raise Blocked('R6_ONLY_PRIMITIVE_CUSTODY_REQUIRED')
                    value=joblib.load(p) # guarded current R6 completed states only.
                    if content_hash(value)!=event['result_sha256']:raise Blocked('R6_STATE_VALUE_PROOF_CHANGED')
                    record=dict(status='SUCCEEDED',value=value,result_sha256=event['result_sha256'])
            self.restored[key]=record
        self._restore_exact_paid_cache()
    def _restore_exact_paid_cache(self):
        self.io_recovery_refs=[]
        if not self.persist:return
        key='fa55063abf9fd62d7ac8a2588ec6cefc46832bc9ea365bcb0442cae7d76801bb'
        rows=[r for r in self.ledger.status['physical_events'] if r['node_id']=='risk:'+key and r['status']=='FAILED_NONREFUNDABLE']
        if not rows:return
        if len(rows)!=1:raise Blocked('SINGLE_CANONICAL_PAID_IO_RECOVERY_REQUIRED')
        record,receipt=_commit_exact_paid_cache(self.run,self.ledger,rows[0])
        self.restored[key]=record;self.io_recovery_refs.append(receipt)
    def reserve(self,e):
        self.ledger.reserve('estimator_learned_state_fit','risk:'+e['key'],int(e['kind'] in LEARNED_KINDS),physical_kind=e['kind'])
        if e['kind']=='deterministic_transform':self.ledger.deterministic('risk_deterministic_transform',1)
    def bind(self,i,s):
        if not i.synthetic:
            runtime.guard_numeric(self.run,self.ledger.freeze_sha)
        context=dict(source_identity=dict(id=ID,version='R6_FIXED_SOURCE_RECIPE',sha256=i.source_sha256,risk_support_identity=s['risk_support_identity']),
            cutoff=model._utc(i.cutoff).isoformat(),assets=tuple(i.returns.columns),return_coordinate='shareholder_value_open_return',horizon=5,
            identity_epoch=dict(uids=i.asset_uids,epochs=i.identity_epochs),synthetic=i.synthetic,mechanism=not i.synthetic)
        if self.cache is None:self.cache=StateCache(self.budget,**context,_records=self.restored)
        else:self.cache=self.cache.bind(**context)
    def learn(self,kind,name,inputs,compute):
        before=len(self.budget.events)
        try:
            value=self.cache.learn(kind,name,inputs,compute)
            for e in self.budget.events[before:]:
                record=self.cache._records[e['key']];details=dict(cache_event=e,backend_invocations=int(name in BACKENDS),backend=BACKENDS.get(name),
                    operation_semantics='joint parameter/latent state estimate' if kind in LEARNED_KINDS else 'deterministic construction')
                if self.persist:details['artifact_ref']=_artifact(self.run,'models/risk/primitives/'+e['key']+'.joblib',value)
                else:details['synthetic_cache_record']=record
                self.ledger.complete('risk:'+e['key'],**details)
            return value
        except BaseException as error:
            for e in self.budget.events[before:]:
                e['status']='FAILED';self.cache._records[e['key']]['status']='FAILED';node='risk:'+e['key']
                row=next((r for r in self.ledger.status['physical_events'] if r['node_id']==node),None)
                if row is not None and row['status']=='STARTED':self.ledger.fail(node,cache_event=e,error_type=type(error).__name__,error=str(error),backend_invocations=int(name in BACKENDS))
            raise

def mathematical_inputs(typed,s):
    cutoff=pd.Timestamp(s['cutoff']);source=typed.source_receipt;origins=pd.DatetimeIndex(s['parent_origin_window'])
    frame=_panel(typed.observations,typed.assets,typed.asset_uids,typed.identity_epoch,source,typed.sessions,cutoff,5).reindex(index=origins,columns=typed.assets)
    finite_counts={a:int(np.isfinite(frame[a].to_numpy()).sum()) for a in typed.assets}
    if finite_counts!=s['nominal_n']:raise Blocked('SOURCE_QUALIFIED_VALUE_NONFINITE_NO_SILENT_N_DOWNGRADE')
    q=None
    if typed.qqq_observations is not None and not typed.qqq_observations.empty:
        q=_panel(typed.qqq_observations,('QQQ',),{'QQQ':'QQQ'},typed.qqq_receipt.identity_epoch,typed.qqq_receipt,typed.sessions,cutoff,5)['QQQ'].reindex(origins)
        if not np.isfinite(q.to_numpy()).all():
            if s['QQQ_full_window_support']:raise Blocked('SOURCE_QUALIFIED_QQQ_VALUE_NONFINITE')
            q=None # absent source factor, not a zero.
    mature=typed.observations.loc[typed.observations.origin_at.isin(origins),'matured_at'].max()
    digest=content_hash(dict(primary=source.cache_identity(),benchmark=typed.qqq_receipt.cache_identity() if typed.qqq_receipt else None,risk_support_identity=s['risk_support_identity']))
    frame.attrs.update(source_sha256=digest,asset_uids=dict(typed.asset_uids),asset_epochs=s['asset_epochs'])
    if q is not None:q.attrs.update(source_sha256=digest,coordinate=typed.qqq_receipt.return_coordinate)
    return model.RiskInputs(frame,cutoff,s['as_of'],dict(typed.asset_uids),digest,mature,q,False,
        len(s['classical_complete_cohort'])==len(s['assets']) and q is not None and s['QQQ_full_window_support'] and len(s['donors'])>=5,dict(s['asset_epochs']))

def estimate_signature(e):
    return content_hash(dict(method=e.method,assets=e.assets,covariance=e.covariance,scenarios=e.scenarios,tail_state=e.tail_state,
        source={k:e.notes[k] for k in ('source_sha256','asset_uids','identity_epochs','as_of','cutoff','risk_support_identity')}))

def execute_group(inputs,support,qualification,operations,*,on_result=None):
    operations.bind(inputs,support);results={};rows=[];prior=None;prior_dependencies=[];prior_ref=None
    order=('POSTERIOR_PREDICTIVE',)+tuple(m for m in model.METHODS if m!='POSTERIOR_PREDICTIVE')
    for m in order:
        q=qualification[m];start=len(operations.cache.usage_log);row=dict(method=m,status=q['status'],risk_support_identity=support['risk_support_identity'])
        if q['status']=='METADATA_QUALIFIED_NUMERIC_FINITE_UNKNOWN':
            try:
                e=model.compute_risk(m,inputs,learn=operations.learn,prior_covariance=prior)
                e=replace(e,notes=dict(e.notes,risk_support_identity=support['risk_support_identity'],source_qualification='FROZEN_HISTORY_MECHANISM_SOURCE_BOUND_R6',
                    source_receipt=support.get('primary_source_sha256'),full_uid_domain_qualified=True,observations_fabricated=False))
                if m=='POSTERIOR_PREDICTIVE':prior=e
                if m in {'EMPIRICAL_CVAR','EVT'}:
                    if prior is None:raise Blocked('TAIL_COVARIANCE_AUXILIARY_UNAVAILABLE')
                    e=replace(e,notes=dict(e.notes,covariance_auxiliary_method=prior.method,covariance_auxiliary_source_sha256=prior.notes['source_sha256'],covariance_auxiliary_is_not_tail_scenarios=True,covariance_auxiliary_ref=prior_ref))
                results[m]=e;row.update(status='COMPLETE_CONDITIONAL_MECHANISM',scientific_method=e.method,representation=e.representation,
                    source_sha256=inputs.source_sha256,asset_uids_sha256=content_hash(inputs.asset_uids),asset_epochs_sha256=content_hash(inputs.identity_epochs),as_of=model._utc(inputs.as_of).isoformat(),cutoff=model._utc(inputs.cutoff).isoformat(),
                    backend_invocations=e.notes.get('backend_calls',0),coefficient_linear_systems=e.notes.get('coefficient_systems',0),scientific_output_sha256=estimate_signature(e))
                if on_result is not None:row['artifact_ref']=on_result(m,e,row)
            except (ValueError,RuntimeError,np.linalg.LinAlgError) as error:row.update(status='FAILED_OR_BLOCKED_NONRETRY',reason=str(error),error_type=type(error).__name__)
        else:row['reason']=q.get('reason')
        row['fit_dependency_ids']=list(dict.fromkeys(operations.cache.usage_log[start:]))
        if m=='POSTERIOR_PREDICTIVE' and row['status']=='COMPLETE_CONDITIONAL_MECHANISM':
            prior_dependencies=row['fit_dependency_ids'];prior_ref=row.get('artifact_ref')
        elif row['status']=='COMPLETE_CONDITIONAL_MECHANISM' and (m in {'EMPIRICAL_CVAR','EVT'} or 'completion' in results[m].notes):
            row['posterior_completion_or_auxiliary_dependency_ids']=list(prior_dependencies)
            row['fit_dependency_ids']=list(dict.fromkeys(row['fit_dependency_ids']+prior_dependencies))
            row['posterior_completion_or_auxiliary_ref']=prior_ref
        rows.append(row)
    return results,rows

def fit(run,freeze_sha,plan_ref,identity_ref,qualification_ref):
    run=runtime.guard_numeric(run,freeze_sha);run,source,_,snapshot=source_binding(run);freeze=old.read_json(run/runtime.FILENAME)
    for key,r in (('risk_event_plan_ref',plan_ref),('risk_identity_ref',identity_ref),('risk_metadata_qualification_ref',qualification_ref)):
        f=freeze.get(key)
        if not f or _path(f)!=_path(r) or f['sha256']!=r['sha256']:raise Blocked('FROZEN_R6_RISK_INPUT_REF_REQUIRED:'+key)
    plan=load_plan(run,plan_ref);p=_pin_ref(qualification_ref,'R6_RISK_METADATA_QUALIFICATION');qual=old.read_json(p)
    if p!=run/QUAL or qual.get('research_id')!=ID or qual.get('numeric_reads')!=0 or qual.get('R5_results_reads')!=0:raise Blocked('EXACT_R6_PRENUMERIC_QUALIFICATION_REQUIRED')
    if _path(qual['event_plan_ref'])!=_path(plan_ref) or qual['event_plan_ref']['sha256']!=plan_ref['sha256'] or qual['identity_ref']['sha256']!=identity_ref['sha256']:raise Blocked('QUALIFICATION_EXACT_PLAN_IDENTITY_BINDING_REQUIRED')
    with runtime.stage_writer(run,'risk'),threadpool_limits(limits=1):
        ledger=runtime.R6Ledger(run,freeze_sha);ops=RiskOperations(ledger,run);loader=InputLoader(run,source,snapshot,identity_ref,freeze_sha=freeze_sha)
        qualified={r['event_id']:r for r in qual['nodes']};nodes=[];previous=old.read_json(run/BANK) if (run/BANK).exists() else {}
        old_rows={(g['event_id'],r['method']):r for g in previous.get('nodes',[]) for r in g.get('methods',[]) if isinstance(r,dict) and r.get('status')=='COMPLETE_CONDITIONAL_MECHANISM'}
        for event in plan['events']:
            proof=qualified[event['event_id']]
            if proof['status']!='METADATA_PROJECTED':nodes.append(dict(event_id=event['event_id'],status='BLOCKED_METADATA',reason=proof['reason']));continue
            try:
                # Exact support recheck before any numerical label/Open projection.
                meta_typed,s,_=loader.load(event)
                if content_hash(s)!=content_hash(proof['support']):raise Blocked('PREBODY_SOURCE_METADATA_SUPPORT_CHANGED')
                typed,actual,_=loader.load(event,numeric=True,metadata_context=(meta_typed,s))
                if content_hash(actual)!=content_hash(s):raise Blocked('NUMERIC_PROJECTION_METADATA_CHANGED')
                inputs=mathematical_inputs(typed,actual)
                def publish(m,value,row):
                    prior=old_rows.get((event['event_id'],m))
                    if prior is not None:
                        if prior['scientific_output_sha256']!=row['scientific_output_sha256']:raise Blocked('R6_COMPLETED_OUTPUT_CHANGED_NO_RETRY')
                        _pin_ref(prior['artifact_ref'],'R6_RETAINED_ESTIMATE');return prior['artifact_ref']
                    return _artifact(run,'models/risk/estimates/'+event['event_id']+'_'+m+'.joblib',value)
                _,rows=execute_group(inputs,s,proof['methods'],ops,on_result=publish);nodes.append(dict(event_id=event['event_id'],support=s,methods=rows))
            except (ValueError,RuntimeError,KeyError,TypeError) as error:nodes.append(dict(event_id=event['event_id'],status='BLOCKED_GROUP',reason=str(error)))
            bank=dict(schema='B_R6_RISK_BANK_V1',research_id=ID,whole_freeze_sha256=freeze_sha,plan_ref=plan_ref,identity_ref=identity_ref,qualification_ref=qualification_ref,
                source_code_pins=code_pins(),nodes=nodes,status='IN_PROGRESS',risk_learned_reserved=ops.budget.learned_total,test2026_reads=0,R5_results_reads=0,
                strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False)
            old.write(run,BANK,bank)
        bank=dict(schema='B_R6_RISK_BANK_V1',research_id=ID,whole_freeze_sha256=freeze_sha,plan_ref=plan_ref,identity_ref=identity_ref,qualification_ref=qualification_ref,
            nodes=nodes,status='FINITE_QUEUE_TERMINAL_WITH_RETAINED_BLOCKS_AND_FAILURES',risk_learned_reserved=ops.budget.learned_total,reserved_by_kind=ops.budget.counts,
            actual_backend_invocations=sum(r.get('details',{}).get('backend_invocations',0) for r in ledger.status['physical_events'] if r['node_id'].startswith('risk:')),
            source_code_pins=code_pins(),new_account_attempts=0,test2026_reads=0,R5_results_reads=0,strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False)
        old.write(run,BANK,bank);return dict(bank_ref=ref(run/BANK),risk_learned_reserved=ops.budget.learned_total,status=bank['status'])

def code_pins():
    from scripts.research.a2.data import shared_risk_inputs_r3 as assembly
    from scripts.research.a2.risk import shared_risk_engine_r2 as engine,shared_risk_budget_r2 as cache
    from scripts.research.a2.data import joint_held_identity_completion_r5 as projection_owner
    paths=[Path(__file__),Path(old.__file__),Path(transport.__file__),Path(runtime.__file__),Path(assembly.__file__),Path(engine.__file__),Path(cache.__file__),Path(projection_owner.__file__),old.REPO/'scripts/common/storage_paths.py']
    return [ref(p) for p in paths]+[dict(source_ref=p['path'],sha256=p['sha256']) for p in model.code_pins()]

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',required=True);p.add_argument('--phase',choices=('prepare','fit'),required=True)
    p.add_argument('--plan-sha',required=True);p.add_argument('--identity-sha',required=True);p.add_argument('--qualification-sha');p.add_argument('--freeze-sha');a=p.parse_args();run=Path(a.run)
    plan=dict(source_ref=str(run/PLAN),sha256=a.plan_sha);identity=dict(source_ref=str(run/'support/R6_SEQUENCE_IDENTITY_ROWS.parquet'),sha256=a.identity_sha)
    if a.phase=='prepare':out=prepare(run,plan,identity);summary=dict(status='R6_METADATA_PREPARED',events=len(out['nodes']),new_fit=0,numeric_reads=0)
    else:
        if not a.freeze_sha or not a.qualification_sha:p.error('fit requires whole freeze SHA and metadata qualification SHA')
        summary=fit(run,a.freeze_sha,plan,identity,dict(source_ref=str(run/QUAL),sha256=a.qualification_sha))
    print(json.dumps(summary),flush=True)
if __name__=='__main__':main()
