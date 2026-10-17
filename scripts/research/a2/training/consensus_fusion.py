"""Finite consensus packets over the canonical past-OOF fusion owner.

No data or fit on import. Same predictor lock/FIT_LOG/ACK worker; no inherited
A-run fitting identity, calibration-as-OOF, missing-member shrink or retry.
"""
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.storage.storage_r2a import write_json_atomic
from scripts.research.a2.training import consensus_predictors as predictors
from scripts.research.a2.training import stateful_fusion as owner
from scripts.research.a2.data.consensus_training_inputs import ConsensusInputs

values=predictors.values
TASK=predictors.TASK
BOUNDARY=predictors.BOUNDARY
CORE=('ridge','hgb','xgb','lgb','cat')
FIXED_WEIGHTS=(.5,.125,.125,.125,.125)
PACKET_METHODS={'core5':tuple(owner.METHODS.values()),
    'broad29':('equal','median','nnls','convex','stack_ridge'),
    'multih38':('equal','nnls','convex')}
YEARS=(2023,2024,2025,2026)
require=predictors.require
CONTINUATION_RESEARCH_ID='CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2'
CONTINUATION_SCHEMA='CONSENSUS_FUSION_CONTINUATION_R2'
PARENT_RUN=resolve(predictors.REPO).backtest_root/TASK/'20261011T170254+0000_bf592a79'
CONTINUATION_RUN=resolve(predictors.REPO).backtest_root/CONTINUATION_RESEARCH_ID/'20261012T025603+0000_4a58260e'
CONTINUATION_SCOPE_SHA256='0a0220d73bffef0db6b427a79a1e10abd34b3bf9725d68ebe5f6366369a5da41'
LEGACY_SOURCE_SHA256=dict(adapter='b3884abac784b7dee2acc333bfa17ed0cd80fee4834126caea2f7a8047ec807c',
    fusion_owner='a13ce0f728852a76cd47fceaec67670ae0c9683f32b1e4443d1e7807d0c54904')
LEGACY_SOURCE_ARCHIVES=resolve(predictors.REPO).results_root/'_maintenance'/TASK/'account_control_cap_recovery/original_sources'



class PacketUnavailable(ValueError):
    """The declared packet cannot run; never substitute surviving members."""


def member_key(member):return member['model_id']+'_'+str(member['horizon'])+'d'


def packets(spec):
    predictors.planned_slots(spec)
    broad=[dict(model_id=m,horizon=5) for m in spec['model_ids']]
    return {'core5':[dict(model_id=m,horizon=5) for m in CORE], 'broad29':broad,
        'multih38':broad+[dict(model_id=m,horizon=h) for h in (3,10,20) for m in predictors.SECONDARY]}


def planned_slots(spec):
    ps=packets(spec)
    return [dict(packet_id=p,method=m,owner_id=next(k for k,v in owner.METHODS.items() if v==m),year=y,
        members=ps[p]) for p,methods in PACKET_METHODS.items() for m in methods for y in YEARS]


def source_pins():
    return {'adapter':dict(path=str(Path(__file__)),sha256=values.sha(__file__)),
        'fusion_owner':dict(path=str(Path(owner.__file__)),sha256=values.sha(owner.__file__)),
        'native_fusion':dict(path=str(owner.NATIVE),sha256=values.sha(owner.NATIVE)),
        'native_common':dict(path=str(owner.COMMON),sha256=values.sha(owner.COMMON)),
        'predictor_sources':predictors.source_pins()}


def metadata(path,*,max_bytes=262144):
    path=Path(path)
    require(path.is_absolute() and path.resolve(strict=True)==path.absolute() and path.stat().st_size<=max_bytes,'UNSAFE_FUSION_METADATA')
    value=json.loads(path.read_text(encoding='utf-8'))
    require(isinstance(value,dict),'FUSION_METADATA_OBJECT_REQUIRED')
    return value


def _pin(ref,expected):
    path=Path(ref['path'])
    require(path==Path(expected) and path.is_absolute() and path.resolve(strict=True)==path.absolute()
        and values.sha(path)==ref['sha256'],'CONTINUATION_REFERENCE_CHANGED')
    return path


def continuation_slots(spec):
    return [dict(packet_id='core5',method=owner.NNLS_ZERO_ABSTAIN,owner_id='NAMED_NNLS_ZERO_ABSTAIN_R1',
        year=y,members=packets(spec)['core5']) for y in YEARS]


def _continuation_facts(run):
    require(Path(run)==CONTINUATION_RUN,'EXACT_CONTINUATION_RUN_REQUIRED')
    scope_ref=dict(path=str(run/'CONTINUATION_SCOPE.json'),sha256=CONTINUATION_SCOPE_SHA256)
    _pin(scope_ref,run/'CONTINUATION_SCOPE.json');scope=metadata(scope_ref['path'])
    require(scope['schema']=='CONSENSUS_PRE2026_SOURCE_COMPLETION_CONTINUATION_SCOPE_R1'
        and scope['task_id']==TASK and scope['research_id']==CONTINUATION_RESEARCH_ID
        and scope['parent_research_id']==TASK and Path(scope['run'])==run
        and scope['original_artifacts_overwritten'] is False,'CONTINUATION_SCOPE_IDENTITY_CHANGED')
    require(scope['scientific_change']['new_named_fusion_candidate']==owner.NNLS_ZERO_ABSTAIN
        and scope['scientific_change']['original_m035_zero_failure_preserved'] is True
        and scope['boundaries']['fit_preprocess_calibration_selection_before']=='2026-01-01'
        and scope['boundaries']['no_new_2026_sample_or_outcome_read_authorized'] is True
        and scope['boundaries']['FAST3_Confirmation_access'] is False,'CONTINUATION_NO_FUTURE_OR_RELABEL_REQUIRED')
    refs=scope['parent_custody'];parent=Path(refs['run']);require(parent==PARENT_RUN,'CONTINUATION_PARENT_CHANGED')
    for key,leaf in [('predictor_freeze_ref','CONSENSUS_PREDICTOR_FREEZE.json'),('fusion_freeze_ref','CONSENSUS_FUSION_FREEZE.json'),
        ('physical_binding_ref','derived/PHYSICAL_SOURCE_BINDING.json'),('membership_ref','derived/consensus100_daily.parquet'),
        ('parent_fit_log_ref','FIT_LOG.jsonl'),('terminal_audit_ref','CONSENSUS_RESEARCH_TERMINAL_AUDIT.json')]:
        _pin(refs[key],parent/leaf)
    _pin(refs['authorized_spec_ref'],predictors.spec_path())
    spec,pf,pf_ref=predictors.contract(parent,'ridge',2024,5)
    require(pf_ref==refs['predictor_freeze_ref'] and pf['authorized_spec']==refs['authorized_spec_ref']
        and pf['input_binding_sha256']==refs['physical_binding_ref']['sha256']
        and pf['membership_sha256']==refs['membership_ref']['sha256'],'CONTINUATION_PARENT_INPUT_CHANGED')
    ff=metadata(refs['fusion_freeze_ref']['path'])
    require(ff['task_id']==TASK and ff['status']=='AUTHORIZED_PRE2026_TRAINING_ONLY'
        and ff['authorized_spec']==refs['authorized_spec_ref'] and ff['predictor_freeze_ref']==pf_ref
        and ff['ordered_slots']==planned_slots(spec) and ff['core5_fixed_weights']==list(FIXED_WEIGHTS)
        and ff['seed']==values.SEED and ff['fit_timeout_seconds']==1800 and ff['max_fit_units']==10000
        and ff['native_capacity']=='UNCHANGED_COMPACT_OWNER_FACTORY' and ff['source_policy']=='FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY'
        and ff['strict_PIT_certified'] is False,
        'CONTINUATION_PARENT_FUSION_RECIPE_CHANGED')
    roles=dict(adapter=(Path(__file__),'historical_fusion_adapter_archive_ref','consensus_fusion_before_source_repair_continuation.py'),
        fusion_owner=(Path(owner.__file__),'historical_owner_archive_ref','stateful_fusion_before_zero_abstention.py'))
    for role,(origin,key,name) in roles.items():
        require(ff['source_pins'][role]==dict(path=str(origin),sha256=LEGACY_SOURCE_SHA256[role])
            and refs[key]['sha256']==LEGACY_SOURCE_SHA256[role],'CONTINUATION_HISTORICAL_SOURCE_ROLE_CHANGED')
        _pin(refs[key],LEGACY_SOURCE_ARCHIVES/name)  # original live path is a historical fact, not a current byte pin.
    for role,path in [('native_fusion',owner.NATIVE),('native_common',owner.COMMON)]:_pin(ff['source_pins'][role],path)
    require(ff['source_pins']['predictor_sources']==pf['source_pins']==predictors.source_pins(),
        'CONTINUATION_PREDICTOR_SOURCES_CHANGED')
    units=events=0
    with Path(refs['parent_fit_log_ref']['path']).open('r',encoding='utf-8') as stream:
        for line in stream:
            require(len(line)<=65536,'CONTINUATION_FIT_LOG_RECORD_TOO_LARGE')
            if not line.strip():continue
            event=json.loads(line);events+=1
            if event.get('event')=='FIT_STARTED':
                require(event.get('fit_units')==1,'CONTINUATION_PHYSICAL_FIT_UNIT_CHANGED');units+=1
    budget=scope['budget']
    require(units==refs['parent_fit_units']==budget['prior_fit_units'] and events==refs['parent_fit_log_events']
        and budget['global_original_fit_unit_limit']==10000 and budget['no_fit_budget_reset'] is True
        and budget['new_fusion_slots']==4,'CONTINUATION_INHERITED_BUDGET_CHANGED')
    audit=metadata(refs['terminal_audit_ref']['path'],max_bytes=16*1024*1024)
    require(audit['task_id']==TASK and Path(audit['run'])==parent and audit['test_2026_numeric_read_authorized'] is False
        and [entry['slot'] for entry in audit['candidate_fusions']]==planned_slots(spec),'CONTINUATION_PARENT_DISPOSITIONS_CHANGED')
    return dict(scope=scope,scope_ref=scope_ref,parent=parent,spec=spec,pf=pf,ff=ff,audit=audit,prior=units)


def continuation_freeze_template(run=CONTINUATION_RUN):
    run=Path(run).resolve();assert_safe_output_path(run,kind='backtest',paths=resolve(predictors.REPO));facts=_continuation_facts(run)
    refs=facts['scope']['parent_custody']
    return dict(schema=CONTINUATION_SCHEMA,status='PROPOSED',task_id=TASK,research_id=CONTINUATION_RESEARCH_ID,
        run=str(run),continuation_scope_ref=facts['scope_ref'],parent_custody=refs,source_pins=source_pins(),
        authorized_spec=refs['authorized_spec_ref'],predictor_freeze_ref=refs['predictor_freeze_ref'],ordered_slots=continuation_slots(facts['spec']),
        prior_fit_units=facts['prior'],parent_fit_log_ref=refs['parent_fit_log_ref'],max_fit_units=10000,seed=values.SEED,
        fit_timeout_seconds=1800,native_capacity='UNCHANGED_COMPACT_OWNER_FACTORY',core5_fixed_weights=list(FIXED_WEIGHTS),
        model_only_fit_authorized=False,final_cutoff_training_only_authorized=False,
        sigma_rule='ONLY_PAST_60_SESSION_RESIDUAL_SAMPLE_STD_NO_MU_SHIFT',source_policy='FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY',strict_PIT_certified=False)


def _continuation_contract(run,frozen,*,authorized=True):
    facts=_continuation_facts(run);refs=facts['scope']['parent_custody']
    require(frozen['schema']==CONTINUATION_SCHEMA and frozen['task_id']==TASK
        and frozen['research_id']==CONTINUATION_RESEARCH_ID and Path(frozen['run'])==run
        and frozen['continuation_scope_ref']==facts['scope_ref'] and frozen['parent_custody']==refs
        and frozen['source_pins']==source_pins(),'CONTINUATION_FROZEN_ORIGIN_CHANGED')
    require(frozen['ordered_slots']==continuation_slots(facts['spec']) and frozen['authorized_spec']==refs['authorized_spec_ref']
        and frozen['predictor_freeze_ref']==refs['predictor_freeze_ref'] and frozen['parent_fit_log_ref']==refs['parent_fit_log_ref']
        and frozen['prior_fit_units']==facts['prior'],'CONTINUATION_PLAN_OR_BUDGET_CHANGED')
    require(frozen['seed']==values.SEED and frozen['fit_timeout_seconds']==values.FIT_TIMEOUT==1800
        and frozen['max_fit_units']==10000 and frozen['core5_fixed_weights']==list(FIXED_WEIGHTS)
        and frozen['sigma_rule']=='ONLY_PAST_60_SESSION_RESIDUAL_SAMPLE_STD_NO_MU_SHIFT'
        and frozen['native_capacity']=='UNCHANGED_COMPACT_OWNER_FACTORY'
        and frozen['source_policy']=='FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY' and frozen['strict_PIT_certified'] is False,
        'CONTINUATION_MODEL_RECIPE_CHANGED')
    if authorized:require(frozen['status']=='AUTHORIZED_PRE2026_TRAINING_ONLY' and frozen['model_only_fit_authorized'] is True,'CONTINUATION_FIT_NOT_AUTHORIZED')
    else:require(frozen['status'] in ('PROPOSED','AUTHORIZED_PRE2026_TRAINING_ONLY'),'CONTINUATION_METADATA_STATUS_CHANGED')
    return facts


def reader_run(run):
    run=Path(run).resolve()
    if run!=CONTINUATION_RUN:return run
    path=run/'CONSENSUS_FUSION_FREEZE.json'
    facts=_continuation_contract(run,metadata(path),authorized=False) if path.exists() else _continuation_facts(run)
    return facts['parent']


def freeze_template(run):
    run=Path(run).resolve();assert_safe_output_path(run,kind='backtest',paths=resolve(predictors.REPO))
    spec=metadata(predictors.spec_path());pf=run/'CONSENSUS_PREDICTOR_FREEZE.json'
    return dict(schema='CONSENSUS_FUSION_FREEZE_R1',status='PROPOSED',task_id=TASK,
        source_pins=source_pins(),authorized_spec=dict(path=str(predictors.spec_path()),sha256=values.sha(predictors.spec_path())),
        predictor_freeze_ref=dict(path=str(pf),sha256=values.sha(pf)),ordered_slots=planned_slots(spec),
        core5_fixed_weights=list(FIXED_WEIGHTS),native_capacity='UNCHANGED_COMPACT_OWNER_FACTORY',
        seed=values.SEED,fit_timeout_seconds=values.FIT_TIMEOUT,max_fit_units=10000,
        final_cutoff_training_only_authorized=False,source_policy='FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY',strict_PIT_certified=False)


def contract(run,packet_id,method,year):
    method=owner.method_name(method);run=Path(run).resolve()
    assert_safe_output_path(run,kind='backtest',paths=resolve(predictors.REPO))
    path=run/'CONSENSUS_FUSION_FREEZE.json';f=metadata(path)
    if f.get('schema')==CONTINUATION_SCHEMA:
        facts=_continuation_contract(run,f)
        selected=[s for s in f['ordered_slots'] if (s['packet_id'],s['method'],s['year'])==(packet_id,method,year)]
        require(len(selected)==1,'UNPLANNED_CONTINUATION_SLOT')
        if year==2026:require(f['final_cutoff_training_only_authorized'] is True,'FUSION_FINAL_CUTOFF_ROOT_GATE_REQUIRED')
        return run,method,facts['spec'],f,selected[0],dict(path=str(path),sha256=values.sha(path))
    require(f['task_id']==TASK and f['status']=='AUTHORIZED_PRE2026_TRAINING_ONLY','FUSION_FREEZE_REQUIRED')
    require(f['source_pins']==source_pins(),'FUSION_FROZEN_SOURCE_CHANGED')
    sp=Path(f['authorized_spec']['path']);require(sp==predictors.spec_path() and values.sha(sp)==f['authorized_spec']['sha256'],'FUSION_SPEC_CHANGED')
    spec=metadata(sp);slots=planned_slots(spec)
    require(f['ordered_slots']==slots and f['core5_fixed_weights']==list(FIXED_WEIGHTS),'FUSION_PACKET_RECIPE_CHANGED')
    selected=[s for s in slots if (s['packet_id'],s['method'],s['year'])==(packet_id,method,year)]
    require(len(selected)==1,'UNPLANNED_FUSION_SLOT')
    require(f['seed']==values.SEED and f['fit_timeout_seconds']==values.FIT_TIMEOUT==1800 and f['max_fit_units']==10000,'FUSION_BUDGET_OR_CAPACITY_CHANGED')
    require(f['native_capacity']=='UNCHANGED_COMPACT_OWNER_FACTORY' and f['source_policy']=='FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY' and f['strict_PIT_certified'] is False,'FUSION_SOURCE_POLICY_CHANGED')
    pf=Path(f['predictor_freeze_ref']['path']);require(pf==run/'CONSENSUS_PREDICTOR_FREEZE.json' and values.sha(pf)==f['predictor_freeze_ref']['sha256'],'FUSION_PREDICTOR_FREEZE_CHANGED')
    if year==2026:require(f['final_cutoff_training_only_authorized'] is True,'FUSION_FINAL_CUTOFF_ROOT_GATE_REQUIRED')
    return run,method,spec,f,selected[0],dict(path=str(path),sha256=values.sha(path))


def publication(run,member,year,reader):
    """Validate annual producer clocks/custody before any forecast numeric scan."""
    require(2021<=year<2026,'FUSION_ONLY_PRE2026_EXPERT_OOF')
    run=reader_run(run)
    model,horizon=member['model_id'],member['horizon'];key=member_key(member)
    output=run/'predictions/consensus_predictors'/model/f'{horizon}d/{year}.parquet';rp=output.with_suffix('.receipt.json')
    if not output.exists() or not rp.exists():raise PacketUnavailable('MISSING_MEMBER_PUBLICATION:'+key+':'+str(year))
    pub=metadata(rp)
    if pub.get('status')!='PUBLISHED':raise PacketUnavailable('UNPUBLISHED_MEMBER:'+key+':'+str(year))
    spec,pf,pf_ref=predictors.contract(run,model,year,horizon)
    require((pub['model_id'],pub['year'],pub['horizon'],pub['joint_horizon'])==(model,year,horizon,5),'FUSION_MEMBER_IDENTITY_CHANGED')
    require(Path(pub['path'])==output and pub['sha256']==values.sha(output) and pub['source_pins']==pf['source_pins'] and pub['test_2026_rows_read']==0,'FUSION_MEMBER_PUBLICATION_CUSTODY_CHANGED')
    _,fr,mp,cp=predictors.slot_paths(run,model,year,horizon)
    require(Path(pub['fit_receipt_path'])==fr and pub['fit_receipt_sha256']==values.sha(fr),'FUSION_MEMBER_FIT_RECEIPT_CHANGED')
    fit=metadata(fr);reuse=fit['reuse_tuple'];cut=pd.Timestamp(f'{year}-01-01')
    require(fit['status']=='TRAINED' and (fit['model_id'],fit['year'],fit['horizon'])==(model,year,horizon),'FUSION_MEMBER_FIT_IDENTITY_CHANGED')
    require(reuse['year']==year and reuse['horizon']==horizon and reuse['primary_horizon']==5 and fit['reuse_tuple_sha256']==values.digest(reuse)==pub['reuse_tuple_sha256'],'FUSION_MEMBER_REUSE_TUPLE_CHANGED')
    fold=reader.annual_fold(year)
    require(pd.Timestamp(reuse['calibration_maturity_exclusive'])==cut and pd.Timestamp(reuse['train_maturity_exclusive'])==pd.Timestamp(fold['calibration_start'])<cut and reuse['calibration_sessions']==[str(d) for d in fold['calibration_sessions']],'FUSION_MEMBER_CLOCK_NOT_OOF')
    require(reuse['freeze_ref']==pf_ref and reuse['authorized_spec']==pf['authorized_spec'] and reuse['input_binding_sha256']==pf['input_binding_sha256'] and reuse['membership_sha256']==pf['membership_sha256'],'FUSION_MEMBER_INPUT_ORIGIN_CHANGED')
    require(fit['source_pins']==reuse['source_pins']==pf['source_pins'] and pub['model_sha256']==fit['model_sha256']==values.sha(mp) and fit['calibration_predictions_sha256']==values.sha(cp),'FUSION_MEMBER_MODEL_OR_CALIBRATION_BYTES_CHANGED')
    require(pub.get('prediction_role','MODEL_OOF')=='MODEL_OOF','CALIBRATION_IS_NOT_EXPERT_OOF')
    predictors.reader_integrity(reader,pf)
    pin=dict(member=key,year=year,publication_receipt_sha256=values.sha(rp),prediction_sha256=pub['sha256'],fit_receipt_sha256=pub['fit_receipt_sha256'])
    cache=getattr(reader,'_consensus_fusion_oof_cache',{})
    token=values.digest(pin)
    if token not in cache:
        from scripts.research.a2.data.joint_input_binding import guard_parquet
        _,proof=guard_parquet(output,pub['sha256'],['signal_date'])
        bounds=proof['date_bounds']['signal_date']
        require(proof['rows']==pub['rows'] and (not proof['rows'] or (bounds and all(pd.Timestamp(b['min'])>=cut and pd.Timestamp(b['max'])<pd.Timestamp(f'{year+1}-01-01') for b in bounds))),'FUSION_MEMBER_PHYSICAL_YEAR_CHANGED')
        frame=pq.read_table(output,columns=['signal_date','ticker','prediction','prediction_qualified','year','reuse_tuple_sha256'],filters=[('signal_date','>=',cut),('signal_date','<',pd.Timestamp(f'{year+1}-01-01'))]).to_pandas()
        require(not frame.duplicated(['signal_date','ticker']).any() and frame.year.eq(year).all() and frame.reuse_tuple_sha256.eq(fit['reuse_tuple_sha256']).all(),'FUSION_MEMBER_ROW_PROVENANCE_CHANGED')
        require(frame.prediction_qualified.eq(frame.prediction.notna()).all(),'FUSION_MEMBER_AVAILABILITY_CHANGED')
        frame=frame[['signal_date','ticker','prediction']].rename(columns={'prediction':'expert_'+key})
        cache[token]=frame;reader._consensus_fusion_oof_cache=cache
    return cache[token],pin


def expert_packet(run,members,years,reader):
    experts={};pins=[]
    for member in members:
        frames=[]
        for y in years:
            frame,pin=publication(run,member,y,reader);frames.append(frame);pins.append(pin)
        experts[member_key(member)]=pd.concat(frames,ignore_index=True)
    return experts,pins


def joined_rows(rows,experts,keys,required):
    try:return owner.join_packet(rows,experts,keys,require_complete=required)
    except ValueError as exc:
        if str(exc).startswith('INCOMPLETE_REQUIRED'):raise PacketUnavailable(str(exc)) from exc
        raise


def past_state(reader,experts,keys,years):
    frames=[]
    for year in years:
        frame=reader.read_prediction_year(year)
        joined,x=joined_rows(frame,experts,keys,False)
        frames.append(owner.state_surface(joined,x))
    return pd.concat(frames,ignore_index=True)


def training_packet(run,slot,year,reader):
    fold,train,cal=predictors.guarded_frames(reader,year,5)
    years=list(range(2021,year));members=slot['members'];keys=tuple(map(member_key,members))
    train=train.loc[pd.to_datetime(train.signal_date).dt.year.isin(years)].reset_index(drop=True)
    cal=cal.loc[pd.to_datetime(cal.signal_date).dt.year.isin(years)].reset_index(drop=True)
    if len(train)<2 or len(cal)<2:raise PacketUnavailable('INSUFFICIENT_PRIOR_2021_OOF_TRAIN_CAL')
    experts,pins=expert_packet(run,members,years,reader)
    train,x=joined_rows(train,experts,keys,True);cal,cx=joined_rows(cal,experts,keys,True)
    if owner.state_required(slot['method']):
        surface=past_state(reader,experts,keys,years)
        state=owner.join_state(train,surface);cstate=owner.join_state(cal,surface)
    else:state=np.zeros((len(train),4));cstate=np.zeros((len(cal),4))
    return fold,train,cal,x,cx,state,cstate,pins


def slot_paths(run,packet_id,method,year):
    root=Path(run)/'models/consensus_fusion'/packet_id/method/str(year)
    return root,root/'receipt.json',root/'model.joblib'


@dataclass
class ConsensusFusion:
    native:object
    sigma:float
    receipt:dict
    run:Path

    def predict_frame(self,frame,reader):
        r=self.receipt;_,method,_,_,slot,_=contract(self.run,r['packet_id'],r['model_id'],r['year'])
        dates=pd.to_datetime(frame.signal_date);year=r['year']
        require(year<2026 and dates.ge(f'{year}-01-01').all() and dates.lt(f'{year+1}-01-01').all(),'FUSION_TEST_PREDICTION_NOT_AUTHORIZED')
        experts,_=expert_packet(self.run,slot['members'],[year],reader);keys=tuple(map(member_key,slot['members']))
        joined,x=joined_rows(frame,experts,keys,False)
        valid=values._bool(frame.feature_available,'feature_available').to_numpy() & np.isfinite(x).all(axis=1)
        require(frame.loc[valid,'feature_source'].isin(owner.ALLOWED_SOURCES).all(),'FUSION_CURRENT_FEATURE_SOURCE_CHANGED')
        out=frame[['signal_date','ticker']].copy();out['prediction']=np.nan;out['value_sigma']=np.nan
        if valid.any():
            state=owner.join_state(joined.loc[valid].reset_index(drop=True),owner.state_surface(joined,x)) if owner.state_required(method) else np.zeros((int(valid.sum()),4))
            mu=np.asarray(self.native.predict(x[valid],state),float)
            require(np.isfinite(mu).all() and np.isfinite(self.sigma) and self.sigma>0,'INVALID_FUSION_FORECAST_OR_SIGMA')
            out.loc[valid,'prediction']=mu;out.loc[valid,'value_sigma']=self.sigma
        out['prediction_qualified']=valid;out['prediction_role']='MODEL_OOF';out['year']=year
        out['packet_id']=r['packet_id'];out['model_id']=method;out['owner_id']=r['owner_id'];out['reuse_tuple_sha256']=r['reuse_tuple_sha256']
        return out


def fit_one(run,packet_id,method,year,reader=None):
    run,method,spec,frozen,slot,freeze_ref=contract(run,packet_id,method,year)
    root,rp,mp=slot_paths(run,packet_id,method,year)
    existing=metadata(rp) if rp.exists() else None
    if existing and existing['status']!='TRAINED':return existing
    data_run=reader_run(run)
    reader=reader or ConsensusInputs(data_run,data_run/'derived/consensus100_daily.parquet')
    _,pf,_=predictors.contract(data_run,'ridge',year,5);predictors.reader_integrity(reader,pf)
    try:fold,train,cal,x,cx,state,cstate,pins=training_packet(run,slot,year,reader)
    except PacketUnavailable as exc:
        require(existing is None,'COMPLETED_FUSION_PACKET_BECAME_UNAVAILABLE')
        with predictors.fit_lock(run):
            require(not root.exists(),'UNRECEIPTED_FUSION_SLOT_PRESERVE')
            root.mkdir(parents=True);receipt=dict(status='NOT_TESTABLE',task_id=TASK,packet_id=packet_id,model_id=method,owner_id=slot['owner_id'],year=year,
                members=slot['members'],reason=str(exc),fit_units=0,source_pins=frozen['source_pins'],freeze_ref=freeze_ref)
            write_json_atomic(rp,receipt)
        return receipt
    reuse=dict(task_id=TASK,packet_id=packet_id,model_id=method,owner_id=slot['owner_id'],year=year,members=slot['members'],
        source_pins=frozen['source_pins'],freeze_ref=freeze_ref,predictor_freeze_ref=frozen['predictor_freeze_ref'],
        past_publication_pins=pins,train_frame_sha256=predictors.frame_hash(train),calibration_frame_sha256=predictors.frame_hash(cal),
        train_maturity_exclusive=str(fold['calibration_start']),calibration_maturity_exclusive=str(fold['cutoff_exclusive']),
        calibration_sessions=[str(d) for d in fold['calibration_sessions']],seed=values.SEED,
        fixed_weights=list(FIXED_WEIGHTS) if method=='fixed_weight' else None,target_definition=values.LABEL,
        state_basis='FULL_CAUSAL_INFERENCE_POOL_BEFORE_LABEL_SUBSET' if owner.state_required(method) else 'UNUSED',weights='UNIFORM_LEGAL_ROWS',native_uncertainty_used=False,target_clip='NONE')
    if frozen.get('schema')==CONTINUATION_SCHEMA:
        reuse.update(research_id=CONTINUATION_RESEARCH_ID,continuation_scope_ref=frozen['continuation_scope_ref'],prior_fit_units=frozen['prior_fit_units'])
    tuple_sha=values.digest(reuse)
    if existing:
        require(existing['reuse_tuple']==reuse and existing['reuse_tuple_sha256']==tuple_sha and existing['model_sha256']==values.sha(mp),'COMPLETED_FUSION_CHECKPOINT_CHANGED')
        owner._native(spec['dependency_paths']);result=joblib.load(mp);result.receipt=existing;return result
    require(not root.exists(),'UNRECEIPTED_FUSION_SLOT_PRESERVE')
    log=run/'FIT_LOG.jsonl';prior=frozen.get('prior_fit_units',0);auth=dict(max_fit_units=10000,budget_bucket='consensus_fusion_'+packet_id)
    receipt=dict(status='IN_PROGRESS',task_id=TASK,packet_id=packet_id,model_id=method,owner_id=slot['owner_id'],year=year,
        reuse_tuple=reuse,reuse_tuple_sha256=tuple_sha,source_pins=frozen['source_pins'],receipt_path=str(rp),model_path=str(mp),fit_units=0,
        train_rows=len(train),calibration_rows=len(cal),strict_PIT_certified=False,source_policy=frozen['source_policy'],
        uncertainty_authority='PAST_60_SESSION_HELDOUT_SAMPLE_RESIDUAL_STD_ONLY',calibration_is_oof=False)
    with predictors.fit_lock(run):
        root.mkdir(parents=True);write_json_atomic(rp,receipt)
        values._append(log,dict(event='CONSENSUS_FUSION_SLOT_STARTED',packet_id=packet_id,model_id=method,year=year,reuse_tuple_sha256=tuple_sha))
        try:
            y=train.y_open5.to_numpy(float);cy=cal.y_open5.to_numpy(float)
            options=dict(packet_width=len(slot['members']),fixed_weights=list(FIXED_WEIGHTS) if method=='fixed_weight' else None)
            if method in ('equal','median','fixed_weight'):native=owner._fit_arrays(method,x,y,state,np.ones(len(y)),lambda _:None,**options)
            else:native=values._fit_job('fusion',method,x,y,state,None,spec['dependency_paths'],list(map(member_key,slot['members'])),options,
                log=log,auth=auth,prior=prior,year=year,tuple_sha=tuple_sha,receipt=receipt,worker_target=owner._fusion_worker)
            raw=native.predict(cx,cstate)
            values._component_start(log,auth,prior,method,year,'HELDOUT_RESIDUAL_SIGMA',tuple_sha);receipt['fit_units']+=1;write_json_atomic(rp,receipt)
            sigma=values.heldout_calibration('ridge',raw,cy)['sigma']
            contract(run,packet_id,method,year)
            receipt.update(status='TRAINED',sigma=sigma)
            if method==owner.NNLS_ZERO_ABSTAIN:receipt['zero_abstention_certificate']=native.zero_abstention_certificate
            result=ConsensusFusion(native,sigma,receipt,run);joblib.dump(result,mp)
            receipt['model_sha256']=values.sha(mp);write_json_atomic(rp,receipt)
            values._append(log,dict(event='CONSENSUS_FUSION_SLOT_COMPLETE',packet_id=packet_id,model_id=method,year=year,fit_units=receipt['fit_units'],reuse_tuple_sha256=tuple_sha))
            return result
        except Exception as exc:
            receipt.update(status='FAILED',failure=dict(type=type(exc).__name__,message=str(exc)));write_json_atomic(rp,receipt)
            values._append(log,dict(event='CONSENSUS_FUSION_SLOT_FAILED',packet_id=packet_id,model_id=method,year=year,fit_units=receipt['fit_units'],failure=receipt['failure']))
            return receipt


def predict_one(run,packet_id,method,year,reader=None):
    require(year<2026,'FUSION_2026_PREDICTION_REQUIRES_SEPARATE_ROOT_GATE')
    run,method,_,frozen,_,_=contract(run,packet_id,method,year)
    data_run=reader_run(run)
    reader=reader or ConsensusInputs(data_run,data_run/'derived/consensus100_daily.parquet')
    fitted=fit_one(run,packet_id,method,year,reader)
    if isinstance(fitted,dict):return fitted
    frame=reader.read_prediction_year(year);keys=reader.prediction_keys(year)
    output=run/'predictions/consensus_fusion'/packet_id/method/f'{year}.parquet';rp=output.with_suffix('.receipt.json')
    frame_sha=predictors.frame_hash(frame);keys_sha=predictors.frame_hash(keys)
    if output.exists() or rp.exists():
        require(output.exists() and rp.exists(),'INCOMPLETE_FUSION_PUBLICATION_PRESERVE')
        old=metadata(rp)
        require(old['status']=='PUBLISHED' and old['reuse_tuple_sha256']==fitted.receipt['reuse_tuple_sha256'] and old['source_pins']==frozen['source_pins'] and old['sha256']==values.sha(output) and old['frame_sha256']==frame_sha and old['keys_sha256']==keys_sha and old['model_sha256']==fitted.receipt['model_sha256'] and old['fit_receipt_sha256']==values.sha(fitted.receipt['receipt_path']),'FUSION_PUBLICATION_CHECKPOINT_CHANGED')
        return old
    try:pred=fitted.predict_frame(frame,reader)
    except PacketUnavailable as exc:return dict(status='NOT_TESTABLE',packet_id=packet_id,model_id=method,year=year,reason=str(exc),fit_receipt_path=fitted.receipt['receipt_path'])
    out=keys[['signal_date','ticker']].merge(pred,on=['signal_date','ticker'],how='left',validate='one_to_one')
    require(len(out)==len(keys) and len(pred)==out.prediction_qualified.notna().sum(),'FUSION_CAUSAL_POOL_KEYS_CHANGED')
    out['prediction_qualified']=out.prediction_qualified.eq(True)
    out['prediction_role']='MODEL_OOF';out['year']=year;out['packet_id']=packet_id;out['model_id']=method
    out['owner_id']=fitted.receipt['owner_id'];out['reuse_tuple_sha256']=fitted.receipt['reuse_tuple_sha256']
    output.parent.mkdir(parents=True,exist_ok=True);out.to_parquet(output,index=False)
    receipt=dict(status='PUBLISHED',prediction_role='MODEL_OOF',path=str(output),sha256=values.sha(output),packet_id=packet_id,model_id=method,year=year,
        rows=len(out),frame_sha256=frame_sha,keys_sha256=keys_sha,reuse_tuple_sha256=fitted.receipt['reuse_tuple_sha256'],model_sha256=fitted.receipt['model_sha256'],
        fit_receipt_path=fitted.receipt['receipt_path'],fit_receipt_sha256=values.sha(fitted.receipt['receipt_path']),source_pins=frozen['source_pins'],test_2026_rows_read=0)
    write_json_atomic(rp,receipt);return receipt

def published_fusion_forecasts(run,method,year,reader=None,*,packet_id='core5'):
    """Read complete pre2026 OOF keys from immutable parent facts or the new child."""
    require(year in (2023,2024,2025),'FUSION_2026_PREDICTION_REQUIRES_SEPARATE_ROOT_GATE')
    run=Path(run).resolve();method=owner.method_name(method)
    expected=None
    if run==CONTINUATION_RUN:
        child=metadata(run/'CONSENSUS_FUSION_FREEZE.json');facts=_continuation_contract(run,child)
        data_run=facts['parent']
        if method==owner.NNLS_ZERO_ABSTAIN:
            origin,_,_,frozen,slot,freeze_ref=contract(run,packet_id,method,year)
        else:
            frozen=facts['ff'];origin=data_run;freeze_ref=facts['scope']['parent_custody']['fusion_freeze_ref']
            entries=[e for e in facts['audit']['candidate_fusions'] if (e['slot']['packet_id'],e['slot']['method'],e['slot']['year'])==(packet_id,method,year)]
            require(len(entries)==1,'UNPLANNED_PARENT_FUSION_PUBLICATION');expected=entries[0];slot=expected['slot']
            if expected['status']!='TRAINED' or 'publication' not in expected:
                raise PacketUnavailable('PARENT_FUSION_PUBLICATION_UNAVAILABLE:'+method+':'+str(year))
    else:
        origin,_,_,frozen,slot,freeze_ref=contract(run,packet_id,method,year);data_run=origin
    reader=reader or ConsensusInputs(data_run,data_run/'derived/consensus100_daily.parquet')
    _,pf,_=predictors.contract(data_run,'ridge',year,5);predictors.reader_integrity(reader,pf)
    output=origin/'predictions/consensus_fusion'/packet_id/method/f'{year}.parquet';rp=output.with_suffix('.receipt.json')
    if not output.exists() or not rp.exists():raise PacketUnavailable('MISSING_FUSION_PUBLICATION:'+method+':'+str(year))
    pub=metadata(rp);_,fr,mp=slot_paths(origin,packet_id,method,year)
    if expected is not None:
        _pin(expected['publication'],rp);_pin(expected['prediction'],output);_pin(expected['receipt'],fr)
        _pin(expected['artifacts']['model'],mp)
    fit=metadata(fr);reuse=fit['reuse_tuple'];cut=pd.Timestamp(f'{year}-01-01');stop=pd.Timestamp(f'{year+1}-01-01')
    require(pub['status']=='PUBLISHED' and pub['prediction_role']=='MODEL_OOF' and pub['test_2026_rows_read']==0
        and Path(pub['path'])==output and (pub['packet_id'],pub['model_id'],pub['year'])==(packet_id,method,year)
        and pub['source_pins']==frozen['source_pins'],'FUSION_PUBLISHED_IDENTITY_OR_SOURCE_CHANGED')
    require(fit['status']=='TRAINED' and fit['task_id']==TASK and (fit['packet_id'],fit['model_id'],fit['owner_id'],fit['year'])
        ==(packet_id,method,slot['owner_id'],year) and Path(fit['receipt_path'])==fr and Path(fit['model_path'])==mp
        and fit['source_pins']==reuse['source_pins']==frozen['source_pins'],'FUSION_PUBLISHED_FIT_ORIGIN_CHANGED')
    require(Path(pub['fit_receipt_path'])==fr and pub['fit_receipt_sha256']==values.sha(fr)
        and fit['reuse_tuple_sha256']==values.digest(reuse)==pub['reuse_tuple_sha256']
        and fit['model_sha256']==pub['model_sha256']==values.sha(mp) and pub['sha256']==values.sha(output),
        'FUSION_PUBLISHED_MODEL_REUSE_OR_BYTES_CHANGED')
    fold=reader.annual_fold(year)
    require(reuse['freeze_ref']==freeze_ref and reuse['predictor_freeze_ref']==frozen['predictor_freeze_ref']
        and reuse['members']==slot['members'] and reuse['seed']==values.SEED
        and (reuse['packet_id'],reuse['model_id'],reuse['owner_id'],reuse['year'])==(packet_id,method,slot['owner_id'],year)
        and reuse['target_definition']==values.LABEL and reuse['weights']=='UNIFORM_LEGAL_ROWS'
        and reuse['target_clip']=='NONE' and reuse['native_uncertainty_used'] is False,
        'FUSION_PUBLISHED_REUSE_CONTRACT_CHANGED')
    require(pd.Timestamp(reuse['calibration_maturity_exclusive'])==cut
        and pd.Timestamp(reuse['train_maturity_exclusive'])==pd.Timestamp(fold['calibration_start'])<cut
        and reuse['calibration_sessions']==[str(d) for d in fold['calibration_sessions']]
        and fit['calibration_is_oof'] is False and np.isfinite(fit['sigma']) and fit['sigma']>0,
        'FUSION_PUBLISHED_CALIBRATION_CLOCK_OR_SIGMA_CHANGED')
    if frozen.get('schema')==CONTINUATION_SCHEMA:
        require(reuse['research_id']==CONTINUATION_RESEARCH_ID and reuse['continuation_scope_ref']==frozen['continuation_scope_ref']
            and reuse['prior_fit_units']==frozen['prior_fit_units'],'FUSION_PUBLISHED_CONTINUATION_CHANGED')
    _,past=expert_packet(data_run,slot['members'],range(2021,year),reader)
    require(reuse['past_publication_pins']==past,'FUSION_PUBLISHED_PAST_MEMBER_CUSTODY_CHANGED')
    frame=reader.read_prediction_year(year);keys=reader.prediction_keys(year)
    require(pub['frame_sha256']==predictors.frame_hash(frame) and pub['keys_sha256']==predictors.frame_hash(keys),
        'FUSION_PUBLISHED_CAUSAL_KEYS_CHANGED')
    experts,current=expert_packet(data_run,slot['members'],[year],reader)
    _,x=joined_rows(frame,experts,tuple(map(member_key,slot['members'])),False)
    qualified=frame[['signal_date','ticker']].copy()
    qualified['expected']=values._bool(frame.feature_available,'feature_available').to_numpy() & np.isfinite(x).all(axis=1)
    require(frame.loc[qualified.expected,'feature_source'].isin(owner.ALLOWED_SOURCES).all(),'FUSION_PUBLISHED_FEATURE_SOURCE_CHANGED')
    expected_mask=keys[['signal_date','ticker']].merge(qualified,on=['signal_date','ticker'],how='left',validate='one_to_one').expected.eq(True)
    from scripts.research.a2.data.joint_input_binding import guard_parquet
    _,proof=guard_parquet(output,pub['sha256'],['signal_date']);bounds=proof['date_bounds']['signal_date']
    require(proof['rows']==pub['rows']==len(keys) and (not proof['rows'] or (bounds and all(
        pd.Timestamp(b['min'])>=cut and pd.Timestamp(b['max'])<stop for b in bounds))), 'FUSION_PUBLISHED_PHYSICAL_YEAR_CHANGED')
    out=pq.read_table(output,columns=['signal_date','ticker','prediction','value_sigma','prediction_qualified','prediction_role',
        'year','packet_id','model_id','owner_id','reuse_tuple_sha256'],filters=[('signal_date','>=',cut),('signal_date','<',stop)]).to_pandas()
    require(not out.duplicated(['signal_date','ticker']).any() and len(out)==len(keys)
        and out[['signal_date','ticker']].equals(keys[['signal_date','ticker']].reset_index(drop=True))
        and out.prediction_role.eq('MODEL_OOF').all() and out.year.eq(year).all()
        and out.packet_id.eq(packet_id).all() and out.model_id.eq(method).all() and out.owner_id.eq(slot['owner_id']).all()
        and out.reuse_tuple_sha256.eq(fit['reuse_tuple_sha256']).all(),'FUSION_PUBLISHED_ROW_PROVENANCE_CHANGED')
    require(out.prediction_qualified.eq(expected_mask.to_numpy()).all()
        and np.isfinite(out.loc[expected_mask.to_numpy(),['prediction','value_sigma']].to_numpy(float)).all()
        and out.loc[expected_mask.to_numpy(),'value_sigma'].eq(fit['sigma']).all()
        and out.loc[~expected_mask.to_numpy(),['prediction','value_sigma']].isna().to_numpy().all(),'FUSION_PUBLISHED_PACKET_COMPLETENESS_CHANGED')
    pin=dict(method=method,packet_id=packet_id,year=year,origin_run=str(origin),publication_receipt_ref=dict(path=str(rp),sha256=values.sha(rp)),
        prediction_ref=dict(path=str(output),sha256=pub['sha256']),fit_receipt_ref=dict(path=str(fr),sha256=values.sha(fr)),
        current_member_publication_pins=current,source_role='PARENT_IMMUTABLE_PUBLISHED_FACT' if expected is not None else 'CURRENT_AUTHORIZED_MODEL_OOF')
    return out,pin

