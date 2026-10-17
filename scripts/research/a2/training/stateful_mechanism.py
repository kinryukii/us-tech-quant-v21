"""R10 local mechanism study: one thin experimental consumer, no account engine.

Inputs, native estimators, physical-fit workers and shared risk producers retain
ownership. This module freezes/dispatches only the expressly authorized study.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time
import joblib
import numpy as np
import pandas as pd
from scripts.research.a2.training import stateful_values as fit_owner
from scripts.research.a2.training import stateful_mechanism_inputs as inputs
from scripts.common.storage_paths import resolve
from scripts.storage.storage_r2a import write_json_atomic

TASK = 'V24_A_STATEFUL_ACTION_RISK_FULL_BREADTH_R10'
IDENTITY = inputs.IDENTITY
RESULT = resolve(fit_owner.REPO).results_root / '_maintenance' / TASK
CAPS = dict(ACTION_VALUE=420, HAZARD_SEQUENCE=220, SHARED_RISK_LEARNED=220,
            RISK_ACTION=160, GROSS_CASH=100, FUSION_GATING=80)
SEEDS = (20260928, 20260929, 20260930)
YEARS = (2024, 2025)
CAPACITIES = ('LOW', 'MID', 'HIGH')
SINGLE = (*inputs.FEATURES, *inputs.STATE)
PAIR = tuple(p+c for p in ('e_', 'i_', 'delta_') for c in SINGLE)
STOCHASTIC = ('catboost', 'mlp', 'resnet', 'ft_transformer', 'gaussian_mlp', 'gaussian_mlp4h', 'tcn', 'gru', 'lstm')
AUTHORITY = {**{k:False for k in inputs.FALSE_AUTHORITY}, '2026_locked':True}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False,default=str).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def clean(value):
    if isinstance(value, dict): return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(tuple,list,np.ndarray)): return [clean(v) for v in value]
    if isinstance(value,(float,np.floating)): return float(value) if np.isfinite(value) else None
    if isinstance(value,(bool,np.bool_)): return bool(value)
    if isinstance(value,(int,np.integer)): return int(value)
    return value


def save(path, value):
    path=Path(path)
    if path.resolve().is_relative_to(RESULT.resolve()):
        from scripts.common.storage_paths import assert_safe_output_path
        from scripts.maintenance.research_inventory import _atomic_write
        assert_safe_output_path(path,kind='results')
        _atomic_write(path,json.dumps(clean(value),indent=2,ensure_ascii=False,allow_nan=False,default=str)+'\n')
    else:write_json_atomic(path,clean(value))


def structured_action_frame(frames, horizon):
    """A single incumbent action learner; replace is an exact output interface."""
    packet = frames.heads[horizon]
    entry = packet['ENTRY'].copy()
    entry['sample_id'] = entry.signal_date.astype(str)+'|ENTRY|'+entry.ticker
    entry['base_weight'] = 1.
    entry['reference_action'] = 1.
    sell = packet['INCUMBENT'].copy()
    additions={}
    for c in SINGLE:
        additions['i_'+c]=sell[c]
        additions['e_'+c]=0.
        additions['delta_'+c]=0.
    sell=pd.concat([sell,pd.DataFrame(additions,index=sell.index)],axis=1)
    sell['action_type'] = 0.
    sell['sample_id'] = sell.signal_date.astype(str)+'|SELL|'+sell.ticker
    sell['base_weight'] = 1.
    replace = packet['REPLACE'].copy()
    replace['sample_id'] = replace.pair_id.astype(str)
    replace['ticker'] = replace.incumbent
    replace['security_id'] = replace.incumbent_sid
    replace['action_type'] = 1.
    replace['base_weight'] = replace.supported_training_group_weight
    replace['entrant_ticker'] = replace.entrant.astype(str)
    replace['entrant'] = replace.i_entrant
    sell['entrant_ticker'] = None
    incumbent = pd.concat([sell,replace],ignore_index=True,sort=False)
    incumbent['reference_action'] = 0.
    action_groups=incumbent.groupby(['signal_date','ticker','security_id'],dropna=False,sort=False)
    incumbent['required_actionset_count']=action_groups.sample_id.transform('size')
    incumbent['required_actionset_sha256']=action_groups.sample_id.transform(lambda ids:digest(sorted(ids.astype(str).tolist())))
    continuation = packet['CONTINUATION'].copy()
    continuation['sample_id'] = continuation.signal_date.astype(str)+'|CONTINUE|'+continuation.ticker
    continuation['base_weight'] = 1.
    continuation['reference_action'] = 1.
    return {'ENTRY':entry,'INCUMBENT':incumbent,'CONTINUATION':continuation}


def encode(frame, columns):
    raw = frame[list(columns)].to_numpy(float)
    if np.isinf(raw).any(): raise ValueError('INFINITE_FEATURE')
    x = np.concatenate([raw,np.isnan(raw).astype(float)],axis=1)
    return x, tuple(columns)+tuple('missing_'+c for c in columns)


def mature_train(frame, cutoff):
    legal = inputs.legal_rows(frame,cutoff)
    if legal.sample_id.duplicated().any(): raise ValueError('TRAINING_DUPLICATE_ID')
    return legal.sort_values(['signal_date','sample_id']).reset_index(drop=True)


def outer(frame, year):
    if year not in YEARS:raise ValueError('REGISTERED_OUTER_YEAR_REQUIRED')
    start,end = pd.Timestamp(f'{year}-01-01'),pd.Timestamp(f'{year+1}-01-01')
    return frame.loc[frame.signal_date.ge(start)&frame.signal_date.lt(end)].copy().reset_index(drop=True)


def local_regret(frame, action, *, score=None):
    """Paired binary local regret; never a full multi-action oracle or account NAV."""
    a = np.asarray(action,float)
    if a.shape!=(len(frame),) or np.any(np.isfinite(a)&((a<0)|(a>1))):raise ValueError('ACTION_OUTSIDE_UNIT_INTERVAL')
    inputs._pre2026(frame.signal_date)
    inputs._pre2026(frame.label_mature_date,nullable=True)
    good = frame.label_qualified.eq(True).to_numpy() & frame.label_mature_date.notna().to_numpy() & np.isfinite(frame.target.to_numpy(float)) & np.isfinite(a)
    f = frame.loc[good].copy()
    y = f.target.to_numpy(float); take = a[good]
    reference = f.reference_action.to_numpy(float)
    f['regret'] = np.maximum(y,0)-take*y
    f['reference_regret'] = np.maximum(y,0)-reference*y
    f['improvement'] = f.reference_regret-f.regret
    # Fixed prelabel entrant/date mass, then normalize the observed conditional mass.
    base = f.base_weight.to_numpy(float) if 'base_weight' in f else np.ones(len(f))
    if not np.isfinite(base).all() or np.any(base<=0):raise ValueError('INVALID_EVALUATION_MASS')
    f['mass'] = base
    f=f.reset_index(drop=True)
    f['action_mass']=take*f.mass
    for column in ('improvement','regret','reference_regret'):
        f[column+'_mass']=f[column]*f.mass
    sums=f.groupby('signal_date',sort=True)[['mass','improvement_mass','regret_mass','reference_regret_mass','action_mass']].sum()
    daily=pd.DataFrame({c:sums[c+'_mass']/sums.mass for c in ('improvement','regret','reference_regret')})
    daily['action_rate']=sums.action_mass/sums.mass
    metrics={'rows':len(frame),'legal_rows':len(f),'coverage':len(f)/len(frame) if len(frame) else 0,
             'metric_role':'LOCAL_CONDITIONAL_BINARY_ACTION_NOT_ACCOUNT_OR_FULL_ORACLE',
             'dates':len(daily),'date_balanced_regret':daily.regret.mean() if len(daily) else None,
             'date_balanced_improvement':daily.improvement.mean() if len(daily) else None,
             'action_rate':daily.action_rate.mean() if len(daily) else None}
    if score is not None and len(f):
        s=np.asarray(score,float)[good]
        metrics['mae']=float(np.average(np.abs(s-y),weights=inputs.date_equal_weights(f,base_column='base_weight')))
    return daily,clean(metrics)


def simultaneous_bounds(series, *, bootstrap=9999, block=20, seed=20261004):
    """Year-stratified circular shared-date max-T; historical mechanism evidence."""
    if not series:return {}
    table=pd.concat({k:v for k,v in series.items()},axis=1).sort_index()
    inputs._pre2026(table.index)
    table=table.loc[pd.DatetimeIndex(table.index).year.isin((2024,2025))]
    dates=pd.DatetimeIndex(table.index)
    if len(table)==0:return {k:{'status':'NO_SUPPORT','ci_status':'CI_NOT_TESTABLE'} for k in series}
    if dates.max()>=inputs.BOUNDARY:raise ValueError('CI_2026_LOCKED')
    x=table.to_numpy(float); counts=np.isfinite(x).sum(axis=0)
    means=np.nanmean(x,axis=0)
    rng=np.random.default_rng(seed); samples=np.full((bootstrap,len(table.columns)),np.nan)
    groups=[np.flatnonzero(dates.year==y) for y in (2023,2024,2025)]
    for b in range(bootstrap):
        chosen=[]
        for group in groups:
            if len(group):
                starts=rng.integers(0,len(group),size=int(np.ceil(len(group)/block)))
                ix=((starts[:,None]+np.arange(block)[None,:])%len(group)).ravel()[:len(group)]
                chosen.extend(group[ix])
        sample=x[chosen]
        n=np.isfinite(sample).sum(axis=0)
        samples[b]=np.divide(np.nansum(sample,axis=0),n,out=np.full(len(n),np.nan),where=n>0)
    se=np.nanstd(samples,axis=0,ddof=1)
    valid=(counts>=40)&np.isfinite(se)&(se>0)
    t=np.divide(samples-means,se,out=np.full_like(samples,np.nan),where=valid[None,:])
    critical=float(np.nanquantile(np.nanmax(t,axis=1),.95)) if valid.any() else None
    out={}
    for j,key in enumerate(table.columns):
        yearly={str(y):float(np.nanmean(x[dates.year==y,j])) if np.isfinite(x[dates.year==y,j]).any() else None for y in (2023,2024,2025)}
        lower=float(means[j]-critical*se[j]) if valid[j] else None
        positive=sum(yearly[str(y)] is not None and yearly[str(y)]>0 for y in (2024,2025))
        supported=bool(lower is not None and lower>0 and means[j]>0 and yearly['2025'] is not None and yearly['2025']>0 and positive>=2)
        out[key]=clean(dict(pooled_improvement=means[j],yearly_improvement=yearly,simultaneous_lower95=lower,
                           bootstrap_se=se[j],critical_max_t=critical,dates=int(counts[j]),
                           status='MECHANISM_SUPPORTED' if supported else 'NO_SUPPORT',
                           ci_status='PASS' if valid[j] else 'CI_NOT_TESTABLE', independent_holdout=False))
    return out


def authority_check(cfg):
    if cfg.get('scientific_identity')!=IDENTITY or any(cfg.get(k) is not v for k,v in AUTHORITY.items()):
        raise ValueError('R10_AUTHORITY_OR_BOUNDARY_CHANGED')
    if cfg.get('account_authorized') is not False or cfg.get('source_activated') is not False:
        raise ValueError('R10_ACCOUNT_FORBIDDEN')


def physical_job(run, design, spec, x, target, weights, dates, features, *, operation='mechanism', worker=None, observed=None,payload_extra=None):
    """Use the existing unique physical worker/ACK owner; failed slots never refit."""
    authority_check(design)
    if spec.get('bucket') not in CAPS or spec.get('year') not in (2023,2024,2025):raise ValueError('FROZEN_BUDGET_OR_YEAR')
    slot=run/'models/mechanism'/spec['slot_id']; rp=slot/'fit_receipt.json'; mp=slot/'model.joblib'
    identity={**spec,'design_sha256':fit_owner.sha(run/'FROZEN_DESIGN.json'),
              'dates_sha256':hashlib.sha256(np.ascontiguousarray(dates).tobytes()).hexdigest(),
              'target_sha256':hashlib.sha256(np.ascontiguousarray(target,dtype=float).tobytes()).hexdigest(),
              'x_shape':list(x.shape),'target_shape':list(np.asarray(target).shape),
              'x_sha256':hashlib.sha256(np.ascontiguousarray(x).tobytes()).hexdigest(),
              'weights_sha256':hashlib.sha256(np.ascontiguousarray(weights).tobytes()).hexdigest(),
              'features':list(features),
              'runtime_numeric_dependency_hashes':{k:hashlib.sha256(np.ascontiguousarray(v).tobytes()).hexdigest() for k,v in (payload_extra or {}).items() if isinstance(v,np.ndarray)}}
    tsha=digest(identity)
    if rp.exists():
        old=read_json(rp)
        if old['scientific_tuple_sha256']!=tsha:raise ValueError('EXISTING_SCIENTIFIC_IDENTITY_CHANGED')
        if old['status']=='TRAINED':
            if fit_owner.sha(mp)!=old['model_sha256']:raise ValueError('REUSE_ARTIFACT_CHANGED')
            if operation == 'fusion':
                from scripts.research.a2.training import stateful_fusion as native_fusion_owner
                native_fusion_owner._native(tuple(design['dependency_paths']))
            return joblib.load(mp),old
        if old['status']=='RUNNING':
            save(slot/'interrupted_original_receipt.json',old)
            old.update(status='FAILED',error='INTERRUPTED_ORPHAN_NO_SCIENTIFIC_RETRY')
            save(rp,old)
        return None,old
    slot.mkdir(parents=True,exist_ok=True)
    receipt={**spec,'scientific_tuple':identity,'scientific_tuple_sha256':tsha,'fit_units':0,
             'receipt_path':str(rp),'training_rows':len(x),'status':'RUNNING','automatic_scientific_retry':False}
    save(rp,receipt)
    fit_owner._append(run/'FIT_LOG.jsonl',dict(event='MODEL_YEAR_ATTEMPT_STARTED',model_id=spec['slot_id'],year=spec['year'],scientific_tuple_sha256=tsha,budget_bucket=spec['bucket']))
    payload={**spec,'target':target,'weights':weights,'source_pins':design['model_specifications']['source_pins'],**(payload_extra or {})}
    auth=dict(max_fit_units=1200,max_new_bucket_fit_units=CAPS[spec['bucket']],budget_bucket=spec['bucket'])
    start=time.monotonic()
    try:
        if operation == 'fusion':
            from scripts.research.a2.training import stateful_fusion as native_fusion_owner
            native_fusion_owner._native(tuple(design['dependency_paths']))
        model=fit_owner._fit_job(operation,spec['slot_id'],x,payload,dates,None,design['dependency_paths'],features,observed,
            log=run/'FIT_LOG.jsonl',auth=auth,prior=0,year=spec['year'],tuple_sha=tsha,receipt=receipt,worker_target=worker)
        joblib.dump(model,mp)
        receipt.update(status='TRAINED',model_path=str(mp),model_sha256=fit_owner.sha(mp))
    except Exception as exc:
        model=None;receipt.update(status='FAILED',error=type(exc).__name__+':'+str(exc))
    receipt['runtime_seconds']=time.monotonic()-start
    save(rp,receipt)
    fit_owner._append(run/'FIT_LOG.jsonl',dict(event='MODEL_YEAR_ATTEMPT_'+receipt['status'],model_id=spec['slot_id'],year=spec['year'],fit_units=receipt['fit_units'],scientific_tuple_sha256=tsha,budget_bucket=spec['bucket']))
    print(json.dumps(clean({k:receipt.get(k) for k in ('slot_id','status','fit_units','runtime_seconds','error')})),flush=True)
    return model,receipt


def scaler_job(run,design,bucket,key,year,x,dates,features,weights=None):
    spec=dict(slot_id=key,family='SCALER',capacity='SHARED',seed=None,objective='PREPROCESSOR',year=year,bucket=bucket)
    from scripts.research.a2.training import stateful_mechanism_models as models
    weight=np.ones(len(x)) if weights is None else np.asarray(weights,float)
    model,receipt=physical_job(run,design,spec,x,np.zeros(len(x)),weight,dates,features,operation='mechanism_scaler',worker=models.fit_worker)
    return model,receipt


def publish_prediction(run,spec,frame,prediction):
    columns=[c for c in ('signal_date','sample_id','ticker','security_id','incumbent','entrant','entrant_ticker','action_type',
                        'label_qualified','label_mature_date','target','reference_action','base_weight','e_y','i_y',
                        'basket_y','gross_previous_proxy','gross_candidate','cohort_age_sessions','label_value',
                        'required_actionset_count','required_actionset_sha256','cohort_id','probe_age',
                        'hazard_at_risk','right_censored_unknown') if c in frame]
    out=frame[columns].copy()
    for k,v in prediction.items():
        if isinstance(v,np.ndarray) and v.ndim==1:out[k]=v
        elif isinstance(v,np.ndarray) and v.shape==(len(out),4) and k in ('mean_h','sigma_h'):
            for j,h in enumerate(inputs.HORIZONS):out[k+'_H'+str(h)]=v[:,j]
        elif isinstance(v,np.ndarray) and v.shape==(len(out),4,3) and k=='marginal_quantiles':
            for j,h in enumerate(inputs.HORIZONS):
                for z,q in enumerate((10,50,90)):out['q'+str(q)+'_H'+str(h)]=v[:,j,z]
    path=run/'predictions/mechanism'/spec['slot_id']/ 'oof.parquet'
    path.parent.mkdir(parents=True,exist_ok=True)
    out.to_parquet(path,index=False)
    return dict(path=str(path),sha256=fit_owner.sha(path),rows=len(out),prediction_role='GENUINE_PAST_ONLY_R10_OOF')


def blocked(run,spec,reason,**details):
    path=run/'models/mechanism'/spec['slot_id']/'fit_receipt.json'
    if path.exists():return read_json(path)
    row={**spec,'status':'BLOCKED_INPUT','reason':reason,'fit_units':0,**details}
    path.parent.mkdir(parents=True,exist_ok=True);save(path,row)
    return row

def role_weights(frame):
    """Key/flag-only date and role balance, without absolute outcome weighting."""
    w=np.zeros(len(frame),float)
    dates=frame.signal_date.to_numpy()
    roles=frame.action_type.to_numpy() if 'action_type' in frame else np.zeros(len(frame))
    for date in pd.unique(dates):
        day=np.flatnonzero(dates==date); present=pd.unique(roles[day])
        for role in present:
            ix=day[roles[day]==role]
            base=frame.iloc[ix].base_weight.to_numpy(float) if 'base_weight' in frame else np.ones(len(ix))
            w[ix]=base/base.sum()/len(present)
    # Relative weights normalize to row count, preserving date equal objective.
    return w*len(w)/w.sum() if len(w) else w


def seed_list(family):
    return SEEDS if family in STOCHASTIC else (SEEDS[0],)


def model_role(run,design,frame,columns,*,bucket,group,horizon,year,families,capacities,
               prefix=False,objective='advantage',target_columns=None,extra_spec=None):
    from scripts.research.a2.training import stateful_mechanism_models as models
    cutoff=pd.Timestamp('2023-10-01') if prefix else pd.Timestamp(f'{year}-01-01')
    train=mature_train(frame,cutoff)
    evaluate=frame.loc[frame.signal_date.ge(cutoff)&frame.signal_date.lt('2024-01-01')].reset_index(drop=True) if prefix else outer(frame,year)
    name=f'{bucket}_{group}_H{horizon}_{"PREFIX" if prefix else year}'
    x,feature_names=encode(train,columns);ex,_=encode(evaluate,columns)
    receipts=[];publications=[]
    if len(train)<20:
        for family in families:
            for capacity in capacities:
                for seed in seed_list(family):
                    spec=dict(slot_id=f'{name}_{family}_{capacity}_{seed}',family=family,capacity=capacity,seed=seed,
                              group=group,horizon=horizon,year=year,bucket=bucket,objective=objective,**(extra_spec or {}))
                    receipts.append(blocked(run,spec,'INSUFFICIENT_LEGAL_PRE_CUTOFF_ROWS',training_rows=len(train)))
        return receipts,publications
    target=train[list(target_columns)].to_numpy(float) if target_columns else train.target.to_numpy(float)
    weight=role_weights(train); dates=train.signal_date.to_numpy()
    needs_scaler=any(models.canonical_family(f) in models.SCALED_FAMILIES for f in families)
    scaler=None
    if needs_scaler:
        scaler,sr=scaler_job(run,design,bucket,name+'_SCALER',year,x,dates,feature_names,weights=weight);receipts.append(sr)
    for family in families:
        for capacity in capacities:
            seed_predictions=[];seed_receipts=[]
            spec=dict(slot_id='',family=family,capacity=capacity,seed=None,group=group,horizon=horizon,
                      year=year,bucket=bucket,objective=objective,cutoff_exclusive=str(cutoff.date()),**(extra_spec or {}))
            for seed in seed_list(family):
                one={**spec,'slot_id':f'{name}_{family}_{capacity}_{seed}','seed':seed}
                if models.canonical_family(family) in models.SCALED_FAMILIES and scaler is None:
                    receipt=blocked(run,one,'SHARED_SCALER_FAILED');model=None
                else:
                    tx=np.nan_to_num(scaler.transform(x),nan=0.) if models.canonical_family(family) in models.SCALED_FAMILIES else np.nan_to_num(x,nan=0.)
                    px=np.nan_to_num(scaler.transform(ex),nan=0.) if models.canonical_family(family) in models.SCALED_FAMILIES else np.nan_to_num(ex,nan=0.)
                    model,receipt=physical_job(run,design,one,tx,target,weight,dates,feature_names,worker=models.fit_worker)
                    if model is not None:
                        try:
                            prediction=models.predict(model,px)
                            if any(isinstance(v,np.ndarray) and not np.isfinite(v).all() for v in prediction.values()):
                                raise ValueError('NONFINITE_PREDICTION_NO_CAPABILITY_FABRICATION')
                            supported=(evaluate.e_friction.notna() & evaluate.i_friction.notna()).to_numpy() if 'action_type' in evaluate else np.ones(len(evaluate),bool)
                            for k,v in prediction.items():
                                if isinstance(v,np.ndarray) and v.ndim==1:v[~supported]=np.nan
                            pub=publish_prediction(run,one,evaluate,prediction)
                            receipt['publication']=pub;save(receipt['receipt_path'],receipt)
                            seed_predictions.append(prediction)
                        except Exception as exc:
                            receipt['prediction_status']='FAILED';receipt['prediction_error']=type(exc).__name__+':'+str(exc)
                            save(receipt['receipt_path'],receipt)
                receipts.append(receipt);seed_receipts.append(receipt)
                update_progress(run,design)
            ensemble_spec={**spec,'slot_id':f'{name}_{family}_{capacity}_ENSEMBLE','seed':'EQUAL_FIXED_SEEDS'}
            if len(seed_predictions)==len(seed_list(family)):
                prediction={}
                for key in seed_predictions[0]:
                    parts=[p[key] for p in seed_predictions]
                    prediction[key]=None if any(p is None for p in parts) else (parts[0] if isinstance(parts[0],str) else np.mean(parts,axis=0))
                if prediction.get('sigma') is not None and prediction.get('mean') is not None:
                    mus=np.stack([p['mean'] for p in seed_predictions]);sigs=np.stack([p['sigma'] for p in seed_predictions])
                    for q,key in ((.1,'q10'),(.5,'q50'),(.9,'q90')):prediction[key]=normal_mixture_quantile(mus,sigs,q)
                if prediction.get('mean_h') is not None:
                    mus=np.stack([p['mean_h'] for p in seed_predictions]);sigs=np.stack([p['sigma_h'] for p in seed_predictions])
                    prediction['sigma_h']=np.sqrt(np.maximum(np.mean(sigs**2+mus**2,axis=0)-prediction['mean_h']**2,0))
                    prediction['marginal_quantiles']=np.stack([normal_mixture_quantile(mus,sigs,q) for q in (.1,.5,.9)],axis=-1)
                # Mixture variance = within-seed variance + between-seed mean variance.
                if prediction.get('sigma') is not None and prediction.get('mean') is not None:
                    mus=np.stack([p['mean'] for p in seed_predictions]); sigs=np.stack([p['sigma'] for p in seed_predictions])
                    prediction['sigma']=np.sqrt(np.maximum(np.mean(sigs**2+mus**2,axis=0)-prediction['mean']**2,0))
                pub=publish_prediction(run,ensemble_spec,evaluate,prediction)
                pub.update(slot_id=ensemble_spec['slot_id'],group=group,horizon=horizon,year=year,family=family,
                           capacity=capacity,seed_receipts=[r['receipt_path'] for r in seed_receipts],prefix=prefix,
                           dependency_role='ZERO_FIT_EQUAL_ENSEMBLE_NO_BEST_SEED')
                if prediction.get('mean') is not None:score=prediction['mean'];action=score>0
                elif prediction.get('q50') is not None:score=prediction['q50'];action=score>0
                elif prediction.get('probability') is not None:score=None;action=prediction['probability']>.5
                else:score=None;action=None
                if action is not None and objective in ('advantage','multitask'):
                    if score is not None:action=np.where(np.isfinite(score),np.asarray(action,float),np.nan)
                    elif prediction.get('probability') is not None:action=np.where(np.isfinite(prediction['probability']),np.asarray(action,float),np.nan)
                    daily,metric=local_regret(evaluate,action,score=score)
                    daily_path=Path(pub['path']).with_name('daily_regret.parquet');daily.to_parquet(daily_path)
                    pub.update(metrics=metric,daily_path=str(daily_path),daily_sha256=fit_owner.sha(daily_path))
                publications.append(pub)
                save(Path(pub['path']).with_suffix('.receipt.json'),pub)
            else:
                publications.append(dict(**ensemble_spec,status='BLOCKED_MEMBER_FAILURE',required_seed_count=len(seed_list(family)),
                                         successful_seeds=len(seed_predictions)))
    return receipts,publications


def update_progress(run,design):
    events=fit_owner._events(run/'FIT_LOG.jsonl')
    starts=[e for e in events if e.get('event')=='FIT_STARTED']
    buckets=Counter({b:0 for b in CAPS})
    for e in starts:buckets[e.get('budget_bucket')]+=int(e.get('fit_units',0))
    if sum(buckets.values())>1200 or any(buckets[b]>CAPS[b] for b in CAPS):raise RuntimeError('PHYSICAL_BUDGET_INVARIANT')
    save(run/'EXECUTION_STATUS.json',dict(status='R10_RUNNING',started_physical_fits=sum(buckets.values()),
         bucket_usage=dict(buckets),bucket_caps=CAPS,last_event=events[-1] if events else None,
         real_accounts=0,real_account_candidates=0,**AUTHORITY))


def action_schedule():
    from scripts.research.a2.training import stateful_mechanism_models as models
    schedule=[]
    for group in ('ENTRY','INCUMBENT'):
        columns=SINGLE if group=='ENTRY' else (*PAIR,'action_type')
        for year in YEARS:
            schedule.append(dict(bucket='ACTION_VALUE',group=group,horizon='MEAN',year=year,
                                 families=['ridge','elasticnet','huber','logistic','hgb','xgb','lgb','catboost','extratrees','mlp','resnet','ft_transformer','hgb_quantile','ngboost','gaussian_mlp'],capacities=list(CAPACITIES),columns=columns))
            for h in inputs.HORIZONS:
                schedule.append(dict(bucket='ACTION_VALUE',group=group,horizon=h,year=year,
                                     families=['ridge','hgb'],capacities=['MID'],columns=columns))
            schedule.append(dict(bucket='ACTION_VALUE',group=group,horizon='MEAN',year=year,
                                 families=['gaussian_mlp4h'],capacities=list(CAPACITIES),columns=columns,
                                 objective='multitask',target_columns=['target_H'+str(h) for h in inputs.HORIZONS],
                                 extra_spec={'formal_multitask':True,'science_role':'FOUR_NATIVE_MARGINAL_GAUSSIAN'}))
        schedule.append(dict(bucket='ACTION_VALUE',group=group,horizon='MEAN',year=2023,
                             families=['ridge','hgb'],capacities=['MID'],columns=columns,prefix=True))
    return schedule


def run_actions(run,design,bundle):
    frames={h:structured_action_frame(bundle.frames,h) for h in (*inputs.HORIZONS,'MEAN')}
    for group in ('ENTRY','INCUMBENT'):
        base=frames['MEAN'][group]
        for h in inputs.HORIZONS:
            lookup=frames[h][group].set_index('sample_id').target
            base['target_H'+str(h)]=base.sample_id.map(lookup)
        base['label_qualified'] &= np.isfinite(base[['target_H'+str(h) for h in inputs.HORIZONS]].to_numpy()).all(axis=1)
    receipts=[];publications=[]
    for item in action_schedule():
        args=dict(item);group=args['group'];h=args['horizon'];cols=args.pop('columns')
        r,p=model_role(run,design,frames[h][group],cols,**args)
        receipts.extend(r);publications.extend(p)
        save(run/'ACTION_BATCH.json',dict(status='RUNNING',receipts=receipts,publications=publications))
    save(run/'ACTION_BATCH.json',dict(status='COMPLETE',receipts=receipts,publications=publications,
                                    replace_head='EXACT_INCUMBENT_REPLACE_INTERFACE_ALIAS'))
    return frames,receipts,publications

def run_continuation_hazard(run,design,bundle,frames):
    from scripts.research.a2.training import stateful_mechanism_models as models
    receipts=[];publications=[]
    for h in inputs.HORIZONS:
        frame=frames[h]['CONTINUATION']
        for year in YEARS:
            r,p=model_role(run,design,frame,SINGLE,bucket='HAZARD_SEQUENCE',group='CONTINUATION',horizon=h,
                           year=year,families=['ridge','hgb'],capacities=['MID'])
            receipts.extend(r);publications.extend(p)
    hazard=inputs.hazard_probes(bundle.frames.heads[5]['CONTINUATION'],bundle.reader.calendar,ages=(0,7,14),stride=7)
    hazard['sample_id']=hazard.signal_date.astype(str)+'|HAZARD|'+hazard.cohort_id
    hazard['base_weight']=1.;hazard['reference_action']=0.
    for year in YEARS:
        r,p=model_role(run,design,hazard,(*SINGLE,'probe_age'),bucket='HAZARD_SEQUENCE',group='HAZARD',horizon=5,
                       year=year,families=['logistic','hgb','xgb','catboost','mlp'],capacities=list(CAPACITIES),objective='HAZARD')
        receipts.extend(r);publications.extend(p)
        # This is not an alternate dependency installation or surrogate Cox target.
        for capacity in CAPACITIES:
            spec=dict(slot_id=f'HAZARD_SEQUENCE_HAZARD_H5_{year}_cox_{capacity}_{SEEDS[0]}',
                      family='cox',capacity=capacity,seed=SEEDS[0],year=year,bucket='HAZARD_SEQUENCE',objective='HAZARD')
            receipts.append(blocked(run,spec,'BLOCKED_DEPENDENCY_OR_VALID_SURVIVAL_SCHEMA',
                                      required='Existing reliable lifelines and full event/censor times; sparse probes alone do not manufacture event time'))
    save(run/'HAZARD_CONTINUATION_BATCH.json',dict(status='COMPLETE',receipts=receipts,publications=publications))
    return receipts,publications


def sequence_dataset(bundle,frame,length):
    history=bundle.prediction_history.copy()
    history['raw_rank']=history.raw_a2_rank;history['raw_score']=history.raw_a2_prediction
    by=history.groupby(['ticker','security_id'],sort=False,dropna=False)
    history['rank_change']=history.raw_rank-by.raw_rank.shift(1)
    history['score_change']=history.raw_score-by.raw_score.shift(1)
    state=bundle.frames.state[['signal_date','ticker','security_id','cohort_age_sessions','entrant']]
    history=history.merge(state,on=['signal_date','ticker','security_id'],how='left',validate='one_to_one')
    history['raw_member']=history.is_raw_top20.astype(float);history['friction']=.001
    # Missing historical proxy state is a structural mask, never a fabricated age.
    parts=[];complete=[]
    for side in ('e','i'):
        keys=frame[['signal_date']].copy()
        if side=='i':
            keys['ticker']=np.where(frame.action_type.eq(1),frame.incumbent,frame.ticker)
            keys['security_id']=np.where(frame.action_type.eq(1),frame.incumbent_sid,frame.security_id)
        else:
            keys['ticker']=frame.entrant_ticker.where(frame.action_type.eq(1),'STRUCTURAL_NO_ENTRANT')
            keys['security_id']=frame.entrant_sid.where(frame.action_type.eq(1),'STRUCTURAL_NO_ENTRANT')
        block=inputs.sequence_blocks(history,keys,bundle.reader.calendar,length,SINGLE)
        a=block.values
        structural=frame.action_type.ne(1).to_numpy() if side=='e' else np.zeros(len(frame),bool)
        a[structural]=0.
        missing=np.isnan(a).astype(float)
        parts.extend([a,missing]);complete.append(block.window_complete|structural)
    token=np.broadcast_to(frame.action_type.to_numpy()[:,None,None],(len(frame),length,1))
    x=np.concatenate([*parts,token],axis=2)
    valid=np.logical_and.reduce(complete)
    return x,valid,tuple(f'{s}_{c}' for s in ('e','e_missing','i','i_missing') for c in SINGLE)+('action_type',)


def run_sequences(run,design,bundle,frames):
    from scripts.research.a2.training import stateful_mechanism_models as models
    joint=frames['MEAN']['INCUMBENT'].copy()
    continuation=frames['MEAN']['CONTINUATION'].copy()
    for c in SINGLE:
        continuation['i_'+c]=continuation[c];continuation['e_'+c]=0.;continuation['delta_'+c]=0.
    continuation['action_type']=-1.
    joint=pd.concat([joint,continuation],ignore_index=True,sort=False)
    all_receipts=[];publications=[]
    for length in (5,10,20):
        x,valid,names=sequence_dataset(bundle,joint,length)
        input_supported=joint.copy();input_supported['sequence_input_supported']=valid
        for year,prefix in ((2024,False),(2025,False),(2023,True)):
            if prefix and length!=20:continue
            cutoff=pd.Timestamp('2023-10-01') if prefix else pd.Timestamp(f'{year}-01-01')
            train_mask=valid & joint.label_qualified.eq(True).to_numpy() & np.isfinite(joint.target.to_numpy(float)) & joint.signal_date.lt(cutoff).to_numpy() & joint.label_mature_date.lt(cutoff).to_numpy()
            eval_mask=joint.signal_date.ge(cutoff).to_numpy() & joint.signal_date.lt('2024-01-01' if prefix else f'{year+1}-01-01').to_numpy()
            training=joint.loc[train_mask].copy();evaluation=joint.loc[eval_mask].copy().reset_index(drop=True)
            eval_input=valid[eval_mask]
            tx=x[train_mask];ex=x[eval_mask];dates=training.signal_date.to_numpy();weight=role_weights(training)
            key=f'HAZARD_SEQUENCE_JOINTSEQ_L{length}_{"PREFIX" if prefix else year}'
            scaler=None
            if len(training)>=20:
                flat=tx.reshape(-1,tx.shape[2]);fd=np.repeat(dates,length);fw=np.repeat(weight/length,length)
                scaler,sr=scaler_job(run,design,'HAZARD_SEQUENCE',key+'_SCALER',year,flat,fd,names,weights=fw)
                all_receipts.append(sr)
            # Same-support static anchor; does not consume a more favorable mask.
            static=joint.copy();static['label_qualified'] &= valid
            r,p=model_role(run,design,static,(*PAIR,'action_type'),bucket='HAZARD_SEQUENCE',group=f'SEQUENCE_STATIC_L{length}',
                           horizon='MEAN',year=year,families=['hgb'],capacities=['MID'],prefix=prefix)
            all_receipts.extend(r);publications.extend(p)
            for family in ('tcn','gru','lstm'):
                capacities=['MID'] if length!=20 or prefix else list(CAPACITIES)
                for capacity in capacities:
                    predictions=[];member_receipts=[]
                    for seed in SEEDS:
                        spec=dict(slot_id=f'{key}_{family}_{capacity}_{seed}',family=family,capacity=capacity,seed=seed,
                                  group='JOINT_SEQUENCE',lookback=length,horizon='MEAN',year=year,bucket='HAZARD_SEQUENCE',objective='ADVANTAGE',
                                  cutoff_exclusive=str(cutoff.date()),prefix=prefix)
                        if scaler is None:
                            receipt=blocked(run,spec,'INSUFFICIENT_SAME_SID_COMPLETE_SEQUENCE_OR_SCALER',training_rows=len(training))
                        else:
                            xx=np.nan_to_num(scaler.transform(tx.reshape(-1,tx.shape[2])).reshape(tx.shape),nan=0.)
                            px=np.nan_to_num(scaler.transform(ex.reshape(-1,ex.shape[2])).reshape(ex.shape),nan=0.)
                            model,receipt=physical_job(run,design,spec,xx,training.target.to_numpy(float),weight,dates,names,worker=models.fit_worker)
                            if model is not None:
                                pred=models.predict(model,px)
                                # Unknown inference sequences remain unknown; no fake point output.
                                for k,v in pred.items():
                                    if isinstance(v,np.ndarray) and v.ndim==1:v[~eval_input]=np.nan
                                pub=publish_prediction(run,spec,evaluation,pred);receipt['publication']=pub
                                save(receipt['receipt_path'],receipt);predictions.append(pred)
                        all_receipts.append(receipt);member_receipts.append(receipt);update_progress(run,design)
                    if len(predictions)==3:
                        pred={k:None if v is None else np.mean([p[k] for p in predictions],axis=0) for k,v in predictions[0].items()}
                        ensemble={**spec,'slot_id':key+'_'+family+'_'+capacity+'_ENSEMBLE','seed':'EQUAL_FIXED_SEEDS'}
                        pub=publish_prediction(run,ensemble,evaluation,pred)
                        # Boolean threshold of NaN is not an executable action.
                        a=np.where(np.isfinite(pred['mean']),(pred['mean']>0).astype(float),np.nan)
                        daily,metric=local_regret(evaluation,a,score=pred['mean'])
                        path=Path(pub['path']).with_name('daily_regret.parquet');daily.to_parquet(path)
                        pub.update(slot_id=ensemble['slot_id'],group='JOINT_SEQUENCE',horizon='MEAN',year=year,
                                   family=family,capacity=capacity,lookback=length,prefix=prefix,metrics=metric,daily_path=str(path),
                                   daily_sha256=fit_owner.sha(path),seed_receipts=[r['receipt_path'] for r in member_receipts])
                        save(Path(pub['path']).with_suffix('.receipt.json'),pub);publications.append(pub)
                    else:
                        publications.append(dict(slot_id=key+'_'+family+'_'+capacity+'_ENSEMBLE',status='BLOCKED_MEMBER_FAILURE'))
        save(run/'SEQUENCE_BATCH.json',dict(status='RUNNING',receipts=all_receipts,publications=publications))
    save(run/'SEQUENCE_BATCH.json',dict(status='COMPLETE',receipts=all_receipts,publications=publications))
    return all_receipts,publications

def full_incumbent_oracle(frame, scores):
    """Complete predeclared actionset only; unknown label never removes a rival."""
    inputs._pre2026(frame.signal_date)
    inputs._pre2026(frame.label_mature_date,nullable=True)
    score=np.asarray(scores,float)
    if score.shape!=(len(frame),):raise ValueError('ACTION_SCORE_SHAPE')
    rows=frame.copy();rows['score']=score
    output=[]
    for (date,ticker,sid),group in rows.groupby(['signal_date','ticker','security_id'],sort=True,dropna=False):
        labels=group.label_qualified.eq(True)&np.isfinite(group.target)&group.label_mature_date.notna()
        fixed_count=group.required_actionset_count if 'required_actionset_count' in group else pd.Series(dtype=int)
        fixed_sha=group.required_actionset_sha256 if 'required_actionset_sha256' in group else pd.Series(dtype=str)
        fixed=bool(len(fixed_count)==len(group) and fixed_count.eq(len(group)).all() and len(fixed_sha)==len(group)
                   and fixed_sha.eq(digest(sorted(group.sample_id.astype(str).tolist()))).all())
        complete=bool(labels.all() and fixed and inputs._sid(sid))
        available=group.loc[np.isfinite(group.score)&group.score.gt(0)].sort_values(['score','sample_id'],ascending=[False,True])
        chosen=available.iloc[0] if len(available) else None
        realized=float(chosen.target) if complete and chosen is not None else 0. if complete else np.nan
        best=max(0.,float(group.target.max())) if complete else np.nan
        output.append(dict(signal_date=date,ticker=ticker,security_id=sid,complete_action_labels=complete,
                           planned_actions=len(group),known_action_labels=int(labels.sum()),
                           chosen_sample_id=chosen.sample_id if chosen is not None else 'HOLD_REFERENCE',
                           local_regret=best-realized if complete else np.nan,
                           oracle_advantage=best,realized_local_advantage=realized,
                           status='LOCAL_COMPLETE_ORACLE' if complete else 'BLOCKED_UNKNOWN_REQUIRED_ACTION_LABEL'))
    return pd.DataFrame(output)


def publication_index(publications):
    return {(p.get('group'),str(p.get('horizon')),p.get('family'),p.get('capacity'),p.get('year'),bool(p.get('prefix'))):p
            for p in publications if p.get('path')}


def ensemble_forecasts(publication):
    f=pd.read_parquet(publication['path'])
    if f.signal_date.ge(inputs.BOUNDARY).any():raise ValueError('PUBLICATION_2026_LOCKED')
    return f


def fusion_packet(base,index,group,year,prefix=False):
    parts=[]
    for family in ('ridge','hgb'):
        key=(group,'MEAN',family,'MID',year,prefix)
        p=index.get(key)
        if p is None:return None
        f=ensemble_forecasts(p)
        if 'mean' not in f:return None
        parts.append(f[['sample_id','mean']].rename(columns={'mean':family}))
    out=base.copy()
    for part in parts:out=out.merge(part,on='sample_id',how='left',validate='one_to_one')
    x=out[['ridge','hgb']].to_numpy(float)
    valid=np.isfinite(x).all(axis=1)
    out['virtual_equal']=(out.ridge+out.hgb)/2
    experts=out[['ridge','virtual_equal','hgb']].to_numpy(float)
    # Four predecision gating features, not targets/residuals.
    rank=out.raw_rank.to_numpy(float) if group=='ENTRY' else out.i_raw_rank.to_numpy(float)
    vol=out.realized_vol_20d.to_numpy(float) if group=='ENTRY' else out.i_realized_vol_20d.to_numpy(float)
    age=out.cohort_age_sessions.to_numpy(float) if group=='ENTRY' else out.i_cohort_age_sessions.to_numpy(float)
    state=np.column_stack([np.nan_to_num(rank,nan=0),np.nan_to_num(vol,nan=0),np.nan_to_num(age,nan=0),np.std(experts,axis=1)])
    return out,experts,state,valid


def run_fusions(run,design,frames,action_publications):
    from scripts.research.a2.training import stateful_mechanism_models as models
    index=publication_index(action_publications);receipts=[];publications=[]
    methods=('nnls','convex','stack_ridge','stack_elastic','stack_hgb','stack_mlp','gate_linear','gate_mlp','residual_first_hgb','residual_last_ridge')
    for group in ('ENTRY','INCUMBENT'):
        for year in YEARS:
            pieces=[]
            for past,prefix in ((2023,True),(2024,False)):
                if past>=year:continue
                base=frames['MEAN'][group]
                start='2023-10-01' if prefix else '2024-01-01'
                sub=base.loc[base.signal_date.ge(start)&base.signal_date.lt(f'{past+1}-01-01')].reset_index(drop=True)
                packet=fusion_packet(sub,index,group,past,prefix)
                if packet is not None:
                    f,x,z,valid=packet
                    legal=valid & f.label_qualified.eq(True).to_numpy() & np.isfinite(f.target) & f.label_mature_date.lt(f'{year}-01-01').to_numpy()
                    pieces.append((f.loc[legal].reset_index(drop=True),x[legal],z[legal]))
            current=fusion_packet(outer(frames['MEAN'][group],year),index,group,year)
            if not pieces or current is None or sum(len(p[0]) for p in pieces)<20:
                for method in methods:
                    spec=dict(slot_id=f'FUSION_{group}_{year}_{method}',family='FUSION',method=method,capacity='MID',seed=SEEDS[0],year=year,bucket='FUSION_GATING',group=group)
                    receipts.append(blocked(run,spec,'BLOCKED_GENUINE_SAME_TARGET_OOF'))
                continue
            train=pd.concat([p[0] for p in pieces],ignore_index=True);x=np.concatenate([p[1] for p in pieces]);z=np.concatenate([p[2] for p in pieces])
            evaluation,ex,ez,valid=current;dates=train.signal_date.to_numpy();weight=role_weights(train)
            scalers={}
            for name,array in (('expert',x),('state',z),('combined',np.column_stack([x,z]))):
                scaler,r=scaler_job(run,design,'FUSION_GATING',f'FUSION_{group}_{year}_{name}_SCALER',year,array,dates,tuple(name+str(i) for i in range(array.shape[1])),weights=weight)
                receipts.append(r);scalers[name]=scaler
            for method in methods:
                seed_predictions=[];members=[]
                for seed in (SEEDS if method in ('stack_mlp','gate_mlp') else (SEEDS[0],)):
                    spec=dict(slot_id=f'FUSION_{group}_{year}_{method}_{seed}',family='FUSION',method=method,capacity='MID',seed=seed,year=year,
                              bucket='FUSION_GATING',group=group,objective='FUSION',shared_scalers=scalers,state=z)
                    audit_spec={k:v for k,v in spec.items() if k not in ('shared_scalers','state')}
                    if any(v is None for v in scalers.values()):
                        r=blocked(run,audit_spec,'SHARED_META_SCALER_FAILED');m=None
                    else:
                        # Shared scaler objects are runtime dependencies, not JSON audit values.
                        m,r=physical_job(run,design,audit_spec,x,train.target.to_numpy(float),weight,dates,('ridge','virtual_equal','hgb'),
                                         operation='fusion',worker=models.fusion_worker,payload_extra={'method':method,'state':z,'shared_scalers':scalers})
                        if m is not None:
                            native_prediction=models.predict_fusion(m,{'experts':ex,'state':ez})
                            pred=np.where(valid,native_prediction['mean'],np.nan);seed_predictions.append(pred)
                    receipts.append(r);members.append(r)
                if len(seed_predictions)==len(members):
                    mean=np.mean(seed_predictions,axis=0)
                    ps={**audit_spec,'slot_id':f'FUSION_{group}_{year}_{method}_ENSEMBLE'}
                    pub=publish_prediction(run,ps,evaluation,{'mean':mean})
                    action=np.where(np.isfinite(mean),(mean>0).astype(float),np.nan)
                    daily,metric=local_regret(evaluation,action,score=mean)
                    path=Path(pub['path']).with_name('daily_regret.parquet');daily.to_parquet(path)
                    pub.update(slot_id=ps['slot_id'],group=group,horizon='MEAN',family='fusion_'+method,capacity='MID',year=year,
                               metrics=metric,daily_path=str(path),daily_sha256=fit_owner.sha(path),uncertainty_capability='POINT_ONLY',
                               two_independent_experts=True,virtual_expert_fit_units=0,seed_receipts=[r.get('receipt_path') for r in members])
                    save(Path(pub['path']).with_suffix('.receipt.json'),pub);publications.append(pub)
            save(run/'FUSION_BATCH.json',dict(status='RUNNING',receipts=receipts,publications=publications))
    publications.extend(run_deterministic_fusions(run,frames,index))
    save(run/'FUSION_BATCH.json',dict(status='COMPLETE',receipts=receipts,publications=publications))
    return receipts,publications


def run_deterministic_fusions(run,frames,index):
    publications=[]
    for group in ('ENTRY','INCUMBENT'):
        for year in YEARS:
            # Nonfitted 14-family point locations; missing required family means unavailable.
            base=outer(frames['MEAN'][group],year)
            all_point=[]
            point_families=[f for f in ('ridge','elasticnet','huber','hgb','xgb','lgb','catboost','extratrees','mlp','resnet','ft_transformer','hgb_quantile','ngboost','gaussian_mlp')]
            for family in point_families:
                p=index.get((group,'MEAN',family,'MID',year,False))
                if p is None:break
                f=ensemble_forecasts(p).set_index('sample_id');column='mean' if 'mean' in f else 'q50'
                if column not in f:break
                all_point.append(f[column].reindex(base.sample_id).to_numpy(float))
            if len(all_point)==len(point_families):
                stack=np.stack(all_point);good=np.isfinite(stack).all(axis=0)
                for method in ('equal','median'):
                    mu=(np.mean(stack,axis=0) if method=='equal' else np.median(stack,axis=0));mu[~good]=np.nan
                    ps=dict(slot_id=f'FUSION_{group}_{year}_ALL14_{method}',group=group,year=year,family='fusion_'+method,capacity='MID',horizon='MEAN')
                    pub=publish_prediction(run,ps,base,{'mean':mu})
                    daily,metric=local_regret(base,np.where(good,(mu>0).astype(float),np.nan),score=mu)
                    path=Path(pub['path']).with_name('daily_regret.parquet');daily.to_parquet(path)
                    pub.update(ps,metrics=metric,daily_path=str(path),daily_sha256=fit_owner.sha(path),fit_units=0,
                               input_interpretation='14 point locations including native quantile median; excludes probability-only Logistic')
                    save(Path(pub['path']).with_suffix('.receipt.json'),pub);publications.append(pub)
    return publications


def normal_mixture_quantile(mus,sigmas,q):
    from scipy.special import ndtr
    mu=np.asarray(mus,float);sd=np.asarray(sigmas,float)
    if mu.shape!=sd.shape or mu.ndim<2 or not 0<q<1 or np.any(np.isfinite(sd)&(sd<=0)):
        raise ValueError('NORMAL_MIXTURE_INPUT')
    low=np.min(mu-12*sd,axis=0);high=np.max(mu+12*sd,axis=0)
    for _ in range(80):
        middle=(low+high)/2
        cdf=np.mean(ndtr((middle[None,...]-mu)/sd),axis=0)
        low=np.where(cdf<q,middle,low);high=np.where(cdf>=q,middle,high)
    return (low+high)/2

GROSS_RISK_COLUMNS=('portfolio_sigma','downside_sigma','regime_probability','covariance_disagreement','turnover_pressure')


def forecast_raw20(run,design,bundle):
    """Annual frozen head projections, never a modification of Raw buy eligibility."""
    from scripts.research.a2.training import stateful_mechanism_models as models
    hist=bundle.prediction_history.copy()
    hist['raw_rank']=hist.raw_a2_rank;hist['raw_score']=hist.raw_a2_prediction
    groups=hist.groupby(['ticker','security_id'],sort=False,dropna=False)
    hist['rank_change']=hist.raw_rank-groups.raw_rank.shift(1)
    hist['score_change']=hist.raw_score-groups.raw_score.shift(1)
    raw=hist.loc[hist.is_raw_top20.eq(True)].copy()
    raw['cohort_age_sessions']=0.;raw['entrant']=1.;raw['raw_member']=1.;raw['friction']=.001
    parts=[]
    for year in YEARS:
        f=raw.loc[raw.signal_date.dt.year.eq(year)].reset_index(drop=True)
        x,names=encode(f,SINGLE)
        key=f'ACTION_VALUE_ENTRY_HMEAN_{year}'
        scaler_path=run/'models/mechanism'/(key+'_SCALER')/'model.joblib'
        required=[run/'models/mechanism'/(key+f'_hgb_MID_{SEEDS[0]}')/'model.joblib',
                  *[run/'models/mechanism'/(key+f'_gaussian_mlp_MID_{seed}')/'model.joblib' for seed in SEEDS]]
        out=f[['signal_date','ticker','security_id']].copy();out['pointAdvantage']=np.nan;out['nativeSigma']=np.nan
        if scaler_path.exists() and all(p.exists() for p in required):
            scaler=joblib.load(scaler_path);xx=np.nan_to_num(scaler.transform(x),nan=0.)
            point=models.predict(joblib.load(required[0]),np.nan_to_num(x,nan=0.))['mean']
            mixtures=[models.predict(joblib.load(p),xx) for p in required[1:]]
            mu=np.mean([p['mean'] for p in mixtures],axis=0)
            sigma=np.sqrt(np.maximum(np.mean([p['sigma']**2+p['mean']**2 for p in mixtures],axis=0)-mu**2,0))
            supported=f.feature_available.eq(True).to_numpy()
            out['pointAdvantage']=np.where(supported,point,np.nan);out['nativeSigma']=np.where(supported,sigma,np.nan)
        parts.append(out)
    result=pd.concat(parts,ignore_index=True)
    path=run/'predictions/mechanism/RAW20_OOF_OPPORTUNITY_CONTEXT.parquet';path.parent.mkdir(parents=True,exist_ok=True)
    result.to_parquet(path,index=False)
    save(path.with_suffix('.receipt.json'),dict(role='HYPOTHETICAL_ENTRY_PROJECTION_WITHOUT_SELECTOR_CHANGE',
         feature_conditioning='age0/entrant1/raw_member1; original Raw20 and eligible bit unchanged',
         limitation='Proxy/OOD for current incumbents; not account action value',source_model='FIXED_MID_HGB+GAUSSIAN_EQUAL3SEEDS',
         annual_training_cutoff='strictly before own Jan1',rows=len(result),sha256=fit_owner.sha(path),**AUTHORITY))
    return result


def gross_regret(frame,predicted_utility):
    f=frame.copy();f['predicted_utility']=np.asarray(predicted_utility,float)
    rows=[]
    for (date,previous),g in f.groupby(['signal_date','gross_previous_proxy'],sort=True):
        complete=bool(len(g)==5 and set(g.gross_candidate)=={0.,.25,.5,.75,1.} and g.label_qualified.eq(True).all()
                      and np.isfinite(g.target).all() and np.isfinite(g.predicted_utility).all())
        if not complete:continue
        winner=g.sort_values(['predicted_utility','gross_candidate'],ascending=[False,True]).iloc[0]
        reference=g.loc[g.gross_candidate.eq(1.)].iloc[0]
        best=float(g.target.max())
        rows.append(dict(signal_date=date,gross_previous_proxy=previous,selected_G=float(winner.gross_candidate),
                         regret=best-float(winner.target),reference_regret=best-float(reference.target),
                         improvement=float(winner.target-reference.target)))
    table=pd.DataFrame(rows)
    daily=table.groupby('signal_date')[['regret','reference_regret','improvement','selected_G']].mean() if len(table) else pd.DataFrame(columns=['regret','reference_regret','improvement','selected_G'])
    metrics=clean(dict(metric_role='DATE_BALANCED_GROSS_PROXY_REGRET_NOT_ACCOUNT',legal_dates=len(daily),
                       observed_proxy_state_rows=len(table),planned_grid_rows=len(frame),
                       date_balanced_regret=daily.regret.mean() if len(daily) else None,
                       date_balanced_improvement=daily.improvement.mean() if len(daily) else None,
                       mean_G=daily.selected_G.mean() if len(daily) else None))
    return daily,metrics


def run_gross(run,design,bundle,risk_context):
    forecasts=forecast_raw20(run,design,bundle)
    dates=pd.DatetimeIndex(bundle.prediction_history.loc[bundle.prediction_history.signal_date.ge('2023-01-01'),'signal_date'].unique()).sort_values()
    frame=inputs.gross_decision_frame({h:bundle.frames.gross[h] for h in inputs.HORIZONS},forecasts,risk_context,
                                      risk_columns=GROSS_RISK_COLUMNS,decision_dates=dates)
    frame_path=run/'derived/GROSS_MEAN_NATIVE_UTILITY_GRID.parquet';frame.to_parquet(frame_path,index=False)
    columns=frame.attrs['feature_columns'];receipts=[];publications=[]
    for year in YEARS:
        r,p=model_role(run,design,frame,columns,bucket='GROSS_CASH',group='GROSS',horizon='MEAN',year=year,
                       families=['ridge','hgb','catboost','mlp','hgb_quantile'],capacities=list(CAPACITIES),objective='GROSS_UTILITY')
        receipts.extend(r)
        for publication in p:
            if not publication.get('path'):publications.append(publication);continue
            f=ensemble_forecasts(publication);value=f['mean'].to_numpy() if 'mean' in f else f['q50'].to_numpy()
            # The audit grid label is read from the existing derived R10 object.
            exact=outer(frame,year).set_index('sample_id').reindex(f.sample_id).reset_index()
            daily,metric=gross_regret(exact,value)
            path=Path(publication['path']).with_name('daily_regret.parquet');daily.to_parquet(path)
            publication.update(metrics=metric,daily_path=str(path),daily_sha256=fit_owner.sha(path))
            save(Path(publication['path']).with_suffix('.receipt.json'),publication);publications.append(publication)
    save(run/'GROSS_BATCH.json',dict(status='COMPLETE',receipts=receipts,publications=publications,
                                   derived_grid_path=str(frame_path),derived_grid_sha256=fit_owner.sha(frame_path),
                                   information_supported_rows=int(frame.information_supported.sum()),
                                   all20_four_horizon_required=True,no_q_learning=True))
    return frame,receipts,publications


def run_risk_action(run,design,frames,risk_features):
    """A consumes annual causal shared projections; unknown risk never becomes zero."""
    receipts=[];publications=[]
    anchors=['ridge','hgb','xgb','catboost','mlp','hgb_quantile']
    for group in ('ENTRY','INCUMBENT'):
        base=frames['MEAN'][group]
        columns=SINGLE if group=='ENTRY' else (*PAIR,'action_type')
        admitted=[]
        for representation in ('R1','R2','R3','R4','R5','R6','R7'):
            projection=risk_features.get((group,representation))
            if projection is None or projection.empty:
                admitted.append(None);continue
            if projection.sample_id.duplicated().any():raise ValueError('RISK_FEATURE_DUPLICATE_KEY')
            state_cols=[c for c in projection if c not in ('sample_id','signal_date','risk_qualified')]
            joined=base.merge(projection,on=['signal_date','sample_id'],how='left',validate='one_to_one')
            supported=joined.risk_qualified.eq(True)&np.isfinite(joined[state_cols].to_numpy(float)).all(axis=1)
            admitted.append((joined,state_cols,supported))
        common=np.ones(len(base),bool)
        for projection in admitted:
            if projection is None:common[:]=False
            else:common &= projection[2].to_numpy()
        for year in YEARS:
            # Main effects retain identical keys for NO_RISK vs R7.
            for representation in ('R0','R7'):
                frame=base.copy() if representation=='R0' else (admitted[-1][0].copy() if admitted[-1] else base.copy())
                frame['label_qualified'] &= common
                extra=() if representation=='R0' else (tuple(admitted[-1][1]) if admitted[-1] else ())
                r,p=model_role(run,design,frame,(*columns,*extra),bucket='RISK_ACTION',group=group+'_'+representation,
                               horizon='MEAN',year=year,families=anchors,capacities=['MID'])
                receipts.extend(r);publications.extend(p)
            if group=='INCUMBENT':
                for k,representation in enumerate(('R1','R2','R3','R4','R5','R6')):
                    projection=admitted[k]
                    frame=projection[0].copy() if projection else base.copy();extra=tuple(projection[1]) if projection else ()
                    # Independent executable role uses its own fixed input domain if full7 is unavailable.
                    fold_common=bool((common & base.signal_date.lt(f'{year}-01-01').to_numpy()).any())
                    mask=common if fold_common else (projection[2].to_numpy() if projection else np.zeros(len(base),bool))
                    frame['label_qualified'] &= mask
                    r,p=model_role(run,design,frame,(*columns,*extra),bucket='RISK_ACTION',group=group+'_'+representation,
                                   horizon='MEAN',year=year,families=['ridge','hgb'],capacities=['MID'],
                                   extra_spec={'matched_all7_domain':fold_common,'support_role':'COMMON7' if fold_common else 'ROLE_SPECIFIC_INPUT_DOMAIN'})
                    receipts.extend(r);publications.extend(p)
        save(run/'RISK_ACTION_BATCH.json',dict(status='RUNNING',receipts=receipts,publications=publications))
    save(run/'RISK_ACTION_BATCH.json',dict(status='COMPLETE',receipts=receipts,publications=publications))
    return receipts,publications



def run_sequence_fusions(run,design,sequence_publications):
    """Frozen S0/S1/S2 and four joint-architecture Ridge S3 identities.

    Independent point comparisons never depend on S3 admission. S3 consumes
    genuine same-target mature OOF only, and at most four scaler plus four
    estimator fits. No sequence, seed, capacity or architecture selection.
    """
    from scripts.research.a2.training import stateful_mechanism_models as models
    architectures=('tcn','gru','lstm')
    identities=((20,2024),(20,2025),(5,2025),(10,2025))
    columns=('static_forecast','sequence_forecast','arch_tcn','arch_gru','arch_lstm')
    receipts=[];publications=[];fitted={}
    def publication(group,family,year,prefix,length):
        hits=[p for p in sequence_publications
              if p.get('group')==group and p.get('family')==family
              and p.get('capacity')=='MID' and p.get('year')==year
              and bool(p.get('prefix'))==prefix and p.get('path')
              and (group!='JOINT_SEQUENCE' or p.get('lookback')==length)]
        if len(hits)>1:raise ValueError('S3_AMBIGUOUS_FROZEN_OOF_PUBLICATION')
        return hits[0] if hits else None
    def packet(length,year,prefix,require_all):
        static=publication('SEQUENCE_STATIC_L'+str(length),'hgb',year,prefix,length)
        if static is None:return None
        base=ensemble_forecasts(static)
        if 'mean' not in base:return None
        pieces=[]
        for arch in architectures:
            src=publication('JOINT_SEQUENCE',arch,year,prefix,length)
            if src is None:
                if require_all:return None
                continue
            seq=ensemble_forecasts(src)
            required=['sample_id','signal_date','security_id','target',
                      'label_qualified','label_mature_date','mean']
            if not set(required).issubset(base) or not set(required).issubset(seq):
                raise ValueError('S3_SAME_TARGET_SOURCE_SCHEMA')
            keys=['sample_id','signal_date','security_id']
            side=seq[required].rename(columns={
                'target':'sequence_target','label_qualified':'sequence_label_qualified',
                'label_mature_date':'sequence_label_mature_date','mean':'sequence_forecast'})
            p=base.rename(columns={'mean':'static_forecast'}).merge(
                side,on=keys,how='left',validate='one_to_one')
            jointly=p.label_qualified.eq(True)&p.sequence_label_qualified.eq(True)
            finite=np.isfinite(p.target)&np.isfinite(p.sequence_target)
            if not np.array_equal(p.loc[jointly&finite,'target'].to_numpy(),
                                  p.loc[jointly&finite,'sequence_target'].to_numpy()):
                raise ValueError('S3_DIFFERENT_NATIVE_ACTION_TARGET')
            p['label_qualified']=jointly&finite&p.label_mature_date.notna()&p.sequence_label_mature_date.notna()
            p['label_mature_date']=pd.concat(
                [pd.to_datetime(p.label_mature_date),
                 pd.to_datetime(p.sequence_label_mature_date)],axis=1).max(axis=1)
            p['architecture']=arch
            for one in architectures:p['arch_'+one]=float(arch==one)
            p['original_sample_id']=p.sample_id
            p['sample_id']=p.sample_id.astype(str)+'|ARCH='+arch
            pieces.append(p)
        return pd.concat(pieces,ignore_index=True) if pieces else None
    for length in (5,10):
        spec=dict(slot_id=f'FUSION_SEQUENCE_S3_L{length}_2024',family='ridge',capacity='MID',
                  seed=SEEDS[0],year=2024,bucket='FUSION_GATING',objective='ADVANTAGE',
                  group='S3_SEQUENCE',lookback=length)
        receipts.append(blocked(run,spec,'BLOCKED_GENUINE_2023_PREFIX_OOF_NO_EXTRA_FIT'))
    for length,year in identities:
        name=f'FUSION_SEQUENCE_S3_L{length}_{year}'
        spec=dict(slot_id=name,family='ridge',capacity='MID',seed=SEEDS[0],year=year,
                  bucket='FUSION_GATING',objective='ADVANTAGE',group='S3_SEQUENCE',
                  lookback=length,meta_members=['STATIC_HGB_MID','TCN_MID','GRU_MID','LSTM_MID'],
                  meta_parameter='RIDGE_MID_ALPHA10')
        past=[]
        for prior,prefix in ((2023,True),(2024,False)):
            if prior>=year or (length!=20 and prefix):continue
            p=packet(length,prior,prefix,require_all=True)
            if p is not None:past.append(p)
        if not past:
            receipts.append(blocked(run,spec,'BLOCKED_GENUINE_SAME_TARGET_OOF'));continue
        train=mature_train(pd.concat(past,ignore_index=True),f'{year}-01-01')
        # Fixed three-architecture matched rows give equal architecture weight.
        # Unknown source forecast drops its entire ex-ante source key; no replacement.
        train['all_input_known']=np.isfinite(train[list(columns)].to_numpy(float)).all(axis=1)
        complete=train.groupby(['signal_date','original_sample_id'],sort=False).all_input_known.agg(['all','size'])
        allowed=complete.index[complete['all']&complete['size'].eq(3)]
        key=pd.MultiIndex.from_frame(train[['signal_date','original_sample_id']])
        train=train.loc[key.isin(allowed)].reset_index(drop=True)
        if len(train)<20:
            receipts.append(blocked(run,spec,'INSUFFICIENT_ALL_LEGAL_SAME_TARGET_OOF',
                                    training_rows=len(train)));continue
        x=train[list(columns)].to_numpy(float)
        weight=role_weights(train);dates=train.signal_date.to_numpy()
        scaler,sr=scaler_job(run,design,'FUSION_GATING',name+'_SCALER',year,
                            x,dates,columns,weights=weight)
        receipts.append(sr)
        if scaler is None:
            receipts.append(blocked(run,spec,'SHARED_S3_SCALER_FAILED'));continue
        model,mr=physical_job(run,design,spec,scaler.transform(x),
                              train.target.to_numpy(float),weight,dates,columns,
                              worker=models.fit_worker)
        receipts.append(mr)
        if model is not None:fitted[(length,year)]=(scaler,model,mr,spec)
        update_progress(run,design)
    # All six lookback/year pairs independently publish S0/S1/S2 whenever their
    # own static+sequence OOF sources exist, including L5/L10 in 2024.
    for length in (5,10,20):
        for year in (2024,2025):
            evaluation=packet(length,year,False,require_all=False)
            if evaluation is None:continue
            meta=fitted.get((length,year))
            raw=evaluation[list(columns)].to_numpy(float)
            input_known=np.isfinite(raw).all(axis=1)
            if meta is not None:
                scaler,model,mr,spec=meta
                transformed=scaler.transform(raw)
                score=models.predict(model,np.nan_to_num(transformed,nan=0.))['mean']
                s3=np.where(input_known,score,np.nan)
            else:s3=None;mr=None
            for arch in architectures:
                pick=evaluation.architecture.eq(arch).to_numpy()
                if not pick.any():continue
                f=evaluation.loc[pick].copy().reset_index(drop=True)
                f['sample_id']=f.original_sample_id
                point={'S0':f.static_forecast.to_numpy(float),
                       'S1':f.sequence_forecast.to_numpy(float),
                       'S2':(f.static_forecast.to_numpy(float)+f.sequence_forecast.to_numpy(float))/2}
                if s3 is not None:point['S3']=s3[pick]
                shared=input_known[pick]
                for variant,score in point.items():
                    score=np.where(shared,score,np.nan)
                    ps=dict(slot_id=f'FUSION_SEQUENCE_L{length}_{year}_{arch}_{variant}',
                            family=arch+'_'+variant,capacity='MID',seed='EQUAL_FIXED_SEEDS',
                            year=year,bucket='FUSION_GATING',objective='ADVANTAGE',
                            group='SEQUENCE_COMPARISON',lookback=length,meta_fit_units=0)
                    pub=publish_prediction(run,ps,f,{'mean':score})
                    daily,metrics=local_regret(
                        f,np.where(np.isfinite(score),(score>0).astype(float),np.nan),score=score)
                    path=Path(pub['path']).with_name('daily_regret.parquet')
                    daily.to_parquet(path)
                    pub.update(slot_id=ps['slot_id'],group='SEQUENCE_COMPARISON',horizon='MEAN',
                               lookback=length,year=year,architecture=arch,variant=variant,
                               metrics=metrics,daily_path=str(path),daily_sha256=fit_owner.sha(path),
                               dependency_meta_receipt=mr.get('receipt_path') if variant=='S3' else None,
                               uncertainty_capability='POINT_ONLY',
                               meta_parameter='RIDGE_MID_ALPHA10' if variant=='S3' else None,
                               architecture_selection=False,source_account_authority_upgraded=False)
                    save(Path(pub['path']).with_suffix('.receipt.json'),pub);publications.append(pub)
    save(run/'SEQUENCE_FUSION_BATCH.json',dict(
        status='COMPLETE',receipts=receipts,publications=publications,
        max_new_physical_fits=8,scaler_count_max=4,estimator_count_max=4,
        independent_point_comparison_not_blocked_by_meta=True))
    return receipts,publications


def risk_consumer_tables(result,frames,bundle):
    """Deterministic projections of shared-owner arrays; never a risk estimator."""
    lookup={};context=[];rows={}
    for item in result['projections']:
        req=item['request'];rep=item['representation']
        if req['horizon']!=5 or rep=='R0':continue
        date=pd.Timestamp(req['date']);value=item['projection'];assets=tuple(req['assets'])
        fields={};features=value['features']
        for k,v in features.items():
            if isinstance(v,(float,int,np.number)) and not isinstance(v,(bool,np.bool_)):fields[k]=np.repeat(float(v),len(assets))
            elif isinstance(v,np.ndarray) and v.shape==(len(assets),):fields[k]=v
        for group,f in features.get('group_features',{}).items():
            for k,v in f.items():
                if isinstance(v,(float,int,np.number)) and not isinstance(v,(bool,np.bool_)):fields[group+'_'+k]=np.repeat(float(v),len(assets))
                elif isinstance(v,np.ndarray) and v.shape==(len(assets),):fields[group+'_'+k]=v
        fields['portfolio_sigma']=np.repeat(value['diagnostics']['predicted_portfolio_sigma'],len(assets))
        lookup[(date,req['cohort'],rep)]=(assets,req['uids'],fields,value)
    flat_r7=[]
    for group in ('ENTRY','INCUMBENT'):
        base=frames['MEAN'][group]
        for rep in ('R1','R2','R3','R4','R5','R6','R7'):
            output=[]
            for date,day in base.groupby('signal_date',sort=True):
                item=lookup.get((date,'A_PROXY_INCUMBENT_COHORT_EQUAL',rep))
                if item is None:continue
                assets,uids,fields,value=item;positions={a:j for j,a in enumerate(assets)}
                for row in day.itertuples(index=False):
                    name=row.ticker
                    if name not in positions or uids[name]!=row.security_id:continue
                    r=dict(signal_date=date,sample_id=row.sample_id,risk_qualified=True)
                    i=positions[name]
                    for k,v in fields.items():r[k]=float(v[i])
                    marginal=fields['normalized_marginal_risk']
                    if group=='ENTRY':r['risk_delta']=float(marginal[i])
                    elif row.action_type==1:
                        e=row.entrant_ticker
                        if e not in positions or uids[e]!=row.entrant_sid:continue
                        r['risk_delta']=float(marginal[positions[e]]-marginal[i])
                        for k,v in fields.items():r['entrant_'+k]=float(v[positions[e]])
                    else:
                        r['risk_delta']=-float(marginal[i])
                        for k in fields:r['entrant_'+k]=0.
                    output.append(r)
                    if rep=='R7':flat_r7.append({**r,'group':group})
            rows[(group,rep)]=pd.DataFrame(output)
    raw=bundle.prediction_history.loc[bundle.prediction_history.is_raw_top20.eq(True)]
    previous=set()
    for date,day in raw.groupby('signal_date',sort=True):
        item=lookup.get((date,'FROZEN_RAW20_EQUAL','R7'));members=set(day.ticker)
        r=dict(signal_date=date,risk_context_qualified=False,**{c:np.nan for c in GROSS_RISK_COLUMNS},replacement_proxy=np.nan)
        if item is not None:
            assets,uids,fields,value=item;groups=value['features'].get('group_features',{})
            r['portfolio_sigma']=value['diagnostics']['predicted_portfolio_sigma']
            # Regime indicator is preserved as indicator, never renamed a probability.
            r['regime_probability']=groups.get('R5',{}).get('p_high_vol_regime',np.nan)
            r['covariance_disagreement']=float(np.mean(groups.get('R6',{}).get('covariance_disagreement',[np.nan])))
            r['downside_sigma']=np.nan # full source-owned downside matrix required, not diagonal shortcut
            r['turnover_pressure']=len(members-previous)/20
            r['replacement_proxy']=len(members-previous)/20
            r['risk_context_qualified']=bool(np.isfinite([r[c] for c in (*GROSS_RISK_COLUMNS,'replacement_proxy')]).all())
        context.append(r);previous=members
    return rows,pd.DataFrame(context),pd.DataFrame(flat_r7)


def run_shared_risk(run,design,bundle,frames):
    from scripts.research.a2.risk import mechanism_risk_adapter as risk
    receipt_path=run/'SHARED_RISK_BATCH.json';artifact=run/'models/risk_shared/STUDY_RESULT.joblib'
    if receipt_path.exists():
        old=read_json(receipt_path)
        if old['status']=='COMPLETE' and fit_owner.sha(artifact)==old['sha256']:
            result=joblib.load(artifact)
            return result,*risk_consumer_tables(result,frames,bundle)
        raise RuntimeError('RISK_EXISTING_ATTEMPT_NOT_RETRIED')
    reservations=[]
    def reserve(plan):
        events=fit_owner._events(run/'FIT_LOG.jsonl')
        actual=sum(int(e.get('fit_units',0)) for e in events if e.get('event')=='FIT_STARTED' and e.get('budget_bucket')=='SHARED_RISK_LEARNED')
        units=plan['required_units']
        if actual+units>CAPS['SHARED_RISK_LEARNED']:raise ValueError('RISK_FINITE_RESERVATION_CAP')
        ack=dict(ack=True,plan_sha256=plan['plan_sha256'],reserved_units=units,reservation_id=digest(plan))
        reservations.append(ack);fit_owner._append(run/'RISK_RESERVATION_LOG.jsonl',ack)
        return ack
    def started(event):
        events=fit_owner._events(run/'FIT_LOG.jsonl');starts=[e for e in events if e.get('event')=='FIT_STARTED']
        used=sum(int(e.get('fit_units',0)) for e in starts);risk_used=sum(int(e.get('fit_units',0)) for e in starts if e.get('budget_bucket')=='SHARED_RISK_LEARNED')
        units=int(event['units'])
        if used+units>1200 or risk_used+units>CAPS['SHARED_RISK_LEARNED']:raise ValueError('RISK_ACTUAL_START_CAP')
        fit_owner._append(run/'FIT_LOG.jsonl',dict(event='FIT_STARTED',role='SHARED_OWNER_RISK',model_id=event.get('name'),budget_bucket='SHARED_RISK_LEARNED',fit_units=units,scientific_tuple_sha256=event['plan_sha256'],risk_owner_event=event))
        update_progress(run,design);return dict(ack=True)
    save(receipt_path,dict(status='RUNNING',scientific_retry=0))
    result=risk.produce_study_risk(bundle,design,reserve_callback=reserve,on_component_start=started)
    artifact.parent.mkdir(parents=True,exist_ok=True);joblib.dump(result,artifact)
    summary={k:v for k,v in result.items() if k not in ('states','projections','production_receipts')}
    summary.update(status='COMPLETE',path=str(artifact),sha256=fit_owner.sha(artifact),states=len(result['states']),projections=len(result['projections']),reservations=reservations,
        production_receipts=[{k:v for k,v in r.items() if k not in ('states',)} for r in result['production_receipts']])
    save(receipt_path,summary)
    return result,*risk_consumer_tables(result,frames,bundle)


def prepare_run():
    from scripts.research.a2.training import stateful_mechanism_models as models
    sys.path.insert(0,str(fit_owner.REPO/'scripts/storage'))
    from scripts.storage.backtest_run_manager import create_backtest_run
    task_path=RESULT/'TASK_RECORD.json';task=read_json(task_path) if task_path.exists() else {}
    if task.get('run_directory'):
        return Path(task['run_directory'])
    reviews=read_json(RESULT/'R10_DESIGN_BUDGET_REVIEW.json')
    source=read_json(RESULT/'R10_INPUT_SOURCE_MANIFEST.json')
    risk_spec=read_json(RESULT/'R10_RISK_STUDY_SPEC.json')
    design=dict(schema='R10_FROZEN_DESIGN_R1',scientific_identity=IDENTITY,task_id=TASK,
        account_authorized=False,source_activated=False,**AUTHORITY,bucket_caps=CAPS,hard_cap=1200,scientific_retry=0,
        review=reviews,model_specifications=models.specifications(),fusion_specifications=models.fusion_specifications(),
        action_schedule=[{k:list(v) if isinstance(v,tuple) else v for k,v in i.items()} for i in action_schedule()],
        risk_study_spec=risk_spec,input_source_manifest=source,
        dependency_paths=['D:/us-tech-quant-envs/frozen_dependency_snapshots/a2_predict_then_optimize_20260928_r1/third_party','D:/us-tech-quant-envs/frozen_dependency_snapshots/development_contexts/fast3_minute_inventory_r1/fast3_torch_cpu/Lib/site-packages'],
        human_request_path='C:/Users/Lenovo/.codex/attachments/fda9e546-74c6-4dc7-96ec-5488ca4acb2d/已粘贴的文本.txt',human_request_sha256='b21c051fd55475e02949cbbf76887359c22de65cbf4b466af7a9220b36ccf351',
        source_semantics='EXPOSED_PRE2026_FROZEN_HISTORY_MECHANISM_ONLY_NOT_CERTIFIED_PIT',
        gross_support='2024 no native annual2023 uncertainty: BLOCKED_INPUT; any regime probability missing blocks required Gross input; no indicator/probability substitution',
        protected_source_pins=read_json(RESULT/'R10_PROTECTED_SOURCE_PINS.json'))
    if fit_owner.sha(design['human_request_path'])!=design['human_request_sha256']:raise ValueError('HUMAN_REQUEST_SHA')
    save(RESULT/'R10_PREREGISTERED_DESIGN.json',design)
    proposal=dict(change_type='EXPLICIT_HUMAN_SAME_INFORMATION_NEW_STATEFUL_MECHANISM_OBJECTIVES',claimed_novelty='NEW_ACTION_MEAN4_SEQUENCE_RISK_CONDITIONED_TARGET_NOT_NEW_SOURCE',
        candidate=dict(entity_id=TASK,canonical_name=TASK,specification_fingerprint=digest(design),information_source_fingerprint=digest(source['source_hashes']),
                       information_family='FROZEN_RAW_A2_PIT32_SHAREHOLDER_PROXY_STATE',mechanism_fingerprint=digest(dict(target=reviews['target_contract'],time=reviews['time_contract'],roles=design['action_schedule'])),decision_layer='STATEFUL_ACTION_GROSS_LOCAL_MECHANISM'))
    save(RESULT/'R10_REGISTRY_PROPOSAL.json',proposal)
    from scripts.maintenance import research_registry as registry
    # The canonical CLI owns preflight; proposal classification is retained honestly.
    import subprocess
    cp=subprocess.run([sys.executable,'-B','-m','scripts.maintenance.research_registry','preflight-proposal','--proposal',str(RESULT/'R10_REGISTRY_PROPOSAL.json'),'--output',str(RESULT/'R10_REGISTRY_PREFLIGHT.json')],cwd=fit_owner.REPO,capture_output=True,text=True)
    if not (RESULT/'R10_REGISTRY_PREFLIGHT.json').exists():raise RuntimeError('REGISTRY_PREFLIGHT_FAILED:'+cp.stdout+cp.stderr)
    decision=read_json(RESULT/'R10_REGISTRY_PREFLIGHT.json')
    if str(decision.get('decision','')).startswith('BLOCKED_'):raise ValueError('REGISTRY_HARD_BLOCK:'+decision['decision'])
    # No generic PASS, source novelty, or registry admission is fabricated.
    save(RESULT/'R10_SCIENTIFIC_AUTHORIZATION.json',dict(authority='EXPLICIT_CURRENT_HUMAN_REQUEST_AND_INDEPENDENT_PREOUTCOME_REVIEW',human_request_sha256=design['human_request_sha256'],registry_decision=decision,registry_override=False,scientific_identity=IDENTITY,**AUTHORITY))
    run=create_backtest_run(TASK,'RESEARCH_WORKTREE_LOCAL_NO_COMMIT','2023-01-01','2025-12-31',[])
    save(run/'FROZEN_DESIGN.json',design)
    cfg=read_json(run/'run_config.json');cfg.update(strategy_version='V24_R10',scientific_identity=IDENTITY,account_authorized=False,source_activated=False,**AUTHORITY,
        frozen_design_sha256=fit_owner.sha(run/'FROZEN_DESIGN.json'),new_fit_cap=1200,physical_bucket_caps=CAPS,scientific_retry=0,source_account_authority_slots='ALL_FIVE_UNBOUND',R9_174_budget_consumed=0)
    save(run/'run_config.json',cfg)
    auth=dict(scientific_identity=IDENTITY,frozen_design_sha256=cfg['frozen_design_sha256'],real_numeric_read_authorized=True,cutoff_exclusive='2026-01-01',source_hashes=source['source_hashes'],human_request_sha256=design['human_request_sha256'],**AUTHORITY)
    save(run/'READ_AUTHORIZATION.json',auth)
    task.update(status='R10_FROZEN_EXECUTION_AUTHORIZED',run_directory=str(run),frozen_design_sha256=cfg['frozen_design_sha256'],real_scientific_fits=0,real_accounts=0,**AUTHORITY)
    save(task_path,task);print(str(run),flush=True);return run


def execute(run):
    from scripts.research.a2.training.stateful_execution import continuation_lock
    design=read_json(run/'FROZEN_DESIGN.json');cfg=read_json(run/'run_config.json');authority_check(design)
    if fit_owner.sha(run/'FROZEN_DESIGN.json')!=cfg['frozen_design_sha256']:raise ValueError('FROZEN_DESIGN_CHANGED')
    with continuation_lock(run,fit_owner.sha(__file__),namespace=TASK):
        permit=inputs.ReadPermit.from_files(run/'FROZEN_DESIGN.json',cfg['frozen_design_sha256'],run/'READ_AUTHORIZATION.json',fit_owner.sha(run/'READ_AUTHORIZATION.json'))
        print('R10 INPUT BUILD START',flush=True)
        bundle=inputs.build_real_frames(permit,design);save(run/'INPUT_COVERAGE.json',bundle.metadata_coverage)
        print(json.dumps(clean(bundle.metadata_coverage)),flush=True)
        frames,action_receipts,action_publications=run_actions(run,design,bundle)
        h_receipts,h_publications=run_continuation_hazard(run,design,bundle,frames)
        seq_receipts,seq_publications=run_sequences(run,design,bundle,frames)
        result,risk_features,risk_context,risk_flat=run_shared_risk(run,design,bundle,frames)
        risk_receipts,risk_publications=run_risk_action(run,design,frames,risk_features)
        f_receipts,f_publications=run_fusions(run,design,frames,action_publications)
        s3_receipts,s3_publications=run_sequence_fusions(run,design,seq_publications)
        gross_frame,gross_receipts,gross_publications=run_gross(run,design,bundle,risk_context)
        from scripts.research.a2.training import stateful_mechanism_evaluation as evaluation
        evaluation.complete_study(run,design,bundle,frames,action_publications+h_publications+seq_publications+risk_publications+f_publications+s3_publications+gross_publications,
                                  risk_result=result,risk_features=risk_features,risk_flat=risk_flat,risk_context=risk_context,gross_frame=gross_frame)


def complete_existing(run):
    """Report-only recovery from terminal own-run batches; never invokes a fit."""
    from scripts.research.a2.training.stateful_execution import continuation_lock
    from scripts.research.a2.training import stateful_mechanism_evaluation as evaluation
    run=Path(run).resolve();design=read_json(run/'FROZEN_DESIGN.json')
    cfg=read_json(run/'run_config.json');authority_check(design)
    if fit_owner.sha(run/'FROZEN_DESIGN.json')!=cfg['frozen_design_sha256']:
        raise ValueError('FROZEN_DESIGN_CHANGED')
    names=('ACTION_BATCH','HAZARD_CONTINUATION_BATCH','SEQUENCE_BATCH','SHARED_RISK_BATCH',
           'RISK_ACTION_BATCH','FUSION_BATCH','SEQUENCE_FUSION_BATCH','GROSS_BATCH')
    batches={name:read_json(run/(name+'.json')) for name in names}
    if any(value.get('status')!='COMPLETE' for value in batches.values()):
        raise ValueError('COMPLETION_ONLY_REQUIRES_ALL_TERMINAL_BATCHES')
    publications=[pub for name in names for pub in batches[name].get('publications',[])]
    def artifact(path,expected):
        path=Path(path).resolve()
        if not path.is_relative_to(run) or not expected or fit_owner.sha(path)!=expected:
            raise ValueError('COMPLETION_ARTIFACT_CUSTODY_OR_SHA')
        return path
    risk_receipt=batches['SHARED_RISK_BATCH']
    risk_path=artifact(risk_receipt['path'],risk_receipt['sha256'])
    gross_receipt=batches['GROSS_BATCH']
    gross_path=artifact(gross_receipt['derived_grid_path'],gross_receipt['derived_grid_sha256'])
    fit_log_sha=fit_owner.sha(run/'FIT_LOG.jsonl')
    batch_pins={name:fit_owner.sha(run/(name+'.json')) for name in names}
    with continuation_lock(run,fit_owner.sha(__file__),namespace=TASK):
        permit=inputs.ReadPermit.from_files(run/'FROZEN_DESIGN.json',cfg['frozen_design_sha256'],
                    run/'READ_AUTHORIZATION.json',fit_owner.sha(run/'READ_AUTHORIZATION.json'))
        print('R10 COMPLETION ONLY: frozen inputs and terminal publications',flush=True)
        bundle=inputs.build_real_frames(permit,design)
        frames={h:structured_action_frame(bundle.frames,h) for h in (*inputs.HORIZONS,'MEAN')}
        risk_result=joblib.load(risk_path)
        risk_features,risk_context,risk_flat=risk_consumer_tables(risk_result,frames,bundle)
        records=inputs.guard_sources({'OWN_GROSS':dict(path=str(gross_path),
            sha256=gross_receipt['derived_grid_sha256'],
            date_columns=['signal_date','label_mature_date'],
            required_columns=['sample_id','target','label_qualified'])})
        gross_frame=pd.read_parquet(gross_path)
        stat=gross_path.stat()
        if records['OWN_GROSS']['file_fingerprint']!={'size':stat.st_size,'mtime_ns':stat.st_mtime_ns}:
            raise ValueError('OWN_GROSS_CHANGED_DURING_READ')
        print('R10 COMPLETION ONLY: diagnostic owner start',flush=True)
        summary=evaluation.complete_study(run,design,bundle,frames,publications,
            risk_result=risk_result,risk_features=risk_features,risk_flat=risk_flat,
            risk_context=risk_context,gross_frame=gross_frame)
        if fit_owner.sha(run/'FIT_LOG.jsonl')!=fit_log_sha or any(
                fit_owner.sha(run/(name+'.json'))!=pin for name,pin in batch_pins.items()):
            raise RuntimeError('COMPLETION_ONLY_CHANGED_SCIENTIFIC_LEDGER')
        print('R10 COMPLETION ONLY FINISHED: '+str(summary.get('status')),flush=True)
        return summary


def main():
    parser=argparse.ArgumentParser();parser.add_argument('operation',choices=('prepare','execute','complete'));parser.add_argument('--run');args=parser.parse_args()
    if args.operation=='prepare':prepare_run()
    elif args.operation=='execute':execute(Path(args.run))
    else:complete_existing(Path(args.run))


if __name__=='__main__':main()
