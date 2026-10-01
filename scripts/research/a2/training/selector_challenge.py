"""Bounded pure-selector challenge; orchestration of canonical components only."""
from __future__ import annotations
import argparse,hashlib,importlib.util,json,os,sys,time,traceback
from pathlib import Path
from datetime import datetime,timezone

REPO=Path(__file__).resolve().parents[4]
BASE=Path('D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1')
RETAINED=REPO/'scripts/research/a2/retained/a2_pto_full_compat_20260928_r2'
DEP=Path('D:/us-tech-quant-envs/frozen_dependency_snapshots/a2_predict_then_optimize_20260928_r1/third_party')
TORCH_DEP=Path('D:/us-tech-quant-envs/frozen_dependency_snapshots/development_contexts/fast3_minute_inventory_r1/fast3_torch_cpu/Lib/site-packages')
SEED=20260928
YEARS=(2021,2022,2023,2024,2025)
MEMBERS=['ridge','hgb','xgb_rank','logistic','cat_uncertainty']
FUSIONS=['equal','median','fixed_weighted','nnls','simplex','ridge_stack','elastic_stack','hgb_stack','mlp_stack','linear_gate','mlp_gate']
RESIDUALS=['ridge_then_hgb','hgb_then_ridge']
EXTRA=['svc','tcn','lstm','gru','pca_ridge','fa_ridge','kmeans_ridge','gmm_ridge','iforest_ridge']
TARGET='MEAN_ER_3D_5D_10D_20D'

def now():return datetime.now(timezone.utc).isoformat()
def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def readj(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def putj(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str,allow_nan=False)+'\n',encoding='utf-8');os.replace(tmp,path)
def emit(**values):print(json.dumps(values,default=str),flush=True)
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);obj=importlib.util.module_from_spec(spec)
    sys.modules[name]=obj;spec.loader.exec_module(obj);return obj

def runtime(run):
    cfg=readj(run/'run_config.json');cache=Path(cfg['cache_directory'])
    for k in ['TEMP','TMP','TMPDIR','JOBLIB_TEMP_FOLDER']:os.environ[k]=str(cache/'temp')
    for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']:os.environ[k]='2'
    for k,n in [('MPLCONFIGDIR','matplotlib'),('TORCH_HOME','torch'),('XDG_CACHE_HOME','package_cache')]:os.environ[k]=str(cache/n)
    for p in [DEP,TORCH_DEP,RETAINED]:
        assert p.is_dir(),f'DEPENDENCY_DIRECTORY_MISSING:{p}'
        if str(p) not in sys.path:sys.path.append(str(p))
    import numpy as np,pandas as pd,joblib,pyarrow.parquet as pq
    bootstrap=module('runtime_bootstrap',RETAINED/'runtime_bootstrap.py')
    predictors=module('_v24_predictors',RETAINED/'predictors.py')
    guard=module('_v24_native_guard',REPO/'scripts/research/a2/retained/a2_predict_then_optimize_20260928_r1/models_native.py')
    original=predictors._make_estimator
    def estimator(name,quantile=None):
        obj=original(name,quantile)
        if name=='ngboost':obj.__class__=guard._fixed_ngboost_class()
        if name=='xgb_rank':obj.set_params(lambdarank_pair_method='mean',lambdarank_num_pair_per_sample=4)
        if name=='lgb_rank':obj.set_params(lambdarank_truncation_level=20,lambdarank_norm=True)
        return obj
    predictors._make_estimator=estimator
    from scripts.research.a2.training import selector_formulations as extra
    shared=module('shared',RETAINED/'shared.py')
    cal=module('_v24_calibration',RETAINED/'calibration_fusion.py')
    from scripts.research.a2.training import selector_cooperation as cooperation
    return cfg,np,pd,pq,joblib,predictors,extra,shared,cal,cooperation

def freeze(run):
    cfg,np,pd,pq,jb,pred,extra,shared,cal,coop=runtime(run)
    candidates=list(pred.NAMES)+EXTRA+FUSIONS+RESIDUALS
    assert len(candidates)==53 and len(set(candidates))==53
    sources=[Path(__file__),Path(extra.__file__),Path(coop.__file__),RETAINED/'predictors.py',RETAINED/'runtime_bootstrap.py',RETAINED/'shared.py',RETAINED/'calibration_fusion.py',REPO/'scripts/research/a2/retained/a2_predict_then_optimize_20260928_r1/models_native.py',REPO/'scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py']
    inputs={'training':{'path':str(BASE/'A2/training_matrix.parquet'),'sha256':'31cc2b3dd2aa7a7c3372d56d5f3f351746b4ad06ef984563de576071913615fb'},'features':{'path':str(BASE/'A/score_rank_ledger.parquet'),'sha256':'0cb9a5acaa0c9f9e2170bf3964292388395c5bfce446fb25a4ad3dcdcc1d1b3b'},'members':{'path':str(BASE/'universe/daily_eligible_universe_membership.parquet'),'sha256':'c03cc35f3569cb968c3d48cefd08488c75c02389e5e430d11526a0284ad2b637'},'raw_oof':{'path':str(BASE/'A2/oof_predictions.parquet'),'sha256':'e336be6c267167356ce3d39fa629f80fe7b2968711112a9c976fdb002c693468'}}
    # Validate every input identity and prove pure-pre2026 date boundaries before rows.
    for key,item in inputs.items():
        assert sha(item['path'])==item['sha256'],f'INPUT_CHANGED:{key}'
        pf=pq.ParquetFile(item['path'])
        for col in (['signal_date','target_end_date'] if key=='training' else ['signal_date']):
            pos=pf.schema_arrow.get_field_index(col);assert pos>=0
            for i in range(pf.num_row_groups):
                st=pf.metadata.row_group(i).column(pos).statistics
                assert st and st.has_min_max and pd.Timestamp(st.max)<pd.Timestamp('2026-01-01'),f'UNPROVEN_READ_BOUNDARY:{key}:{col}'
    design=dict(version='V24',line='C_SELECTOR',freeze_at=now(),candidates=candidates,base=list(pred.NAMES)+EXTRA,features=shared.FEATURES,target=TARGET,target_formula='mean over h in [3,5,10,20] of stock feature-basis Close(t+h)/Close(t)-1 minus QQQ Close(t+h)/Close(t)-1; exact source-bound frozen target reused',feature_basis='FROZEN_RAW_A2_FORWARD_REHAB_PIT32; execution raw Open remains separate',years=list(YEARS),train_cutoff='signal_date < Jan1(year) AND target_end_date < Jan1(year)',prediction_scope='all original qualified date-security UID keys; no model-specific shrink',training_sample=dict(max_rows=40000,method='uniform no-replacement by decision date, same keys for all roles; seed fixed; target never used for sampling',seed=SEED),primary_eval_years=[2023,2024,2025],early_model_oof_years=[2021,2022],base_specs=pred.SPECS,extra_specs=extra.SPEC,cooperation_specs=coop.SPEC,score=dict(point='native predicted target',classification='native P(target>0); SVC decision_function',quantile='Q10 higher first; Q50/Q90 diagnostic only',distribution='location - 0.5 * native scale',ranking='native rank score higher first',auxiliary='fold-local auxiliary+fixed Ridge predicted target',sequence='predicted same target; distinct SEQUENCE_FORMULATION with 8-session canonical UID past-only lag'),rank_transform=dict(group='decision_date',relevance='sampled training date group target pct rank average; floor(rank*5) clipped to 4',pair_weight='unit stock/group; native objective pre-frozen implementation version',xgb=dict(objective='rank:pairwise',pair_method='mean',pairs_per_sample=4,seed=SEED),lgb=dict(objective='lambdarank',label_gain=[0,1,3,7,15],truncation_level=20,norm=True,seed=SEED)),numeric_repairs={'ngboost':'existing bounded line-search <=64 downscales, same native gradient/objective; no boosting-round early stopping','convergence':'only retained predeclared same-objective iteration continuation; failure never silently promoted'},fusion_members=MEMBERS,residual='second stage fits target minus TRUE earlier annual stage1 MODEL_OOF on same32 features; stage1 future prediction from its proper current annual fit',budget=dict(max_learned_fit_calls=2000,max_physical_estimators=650,configurations_per_role=1,seeds_per_role=1,max_primary_candidates=53,max_finalists=3,max_full_account_paths=58,account_count_definition='54 pre2026 paths incl Raw control + up to3 finalist 2026 extensions +1 Raw2026 extension; count extensions separately'),selection_rule=dict(primary='TOP20_REPLACEMENT_EDGE=(sum matured labels entrants - sum matured labels exits)/20',pooled_edge_positive=True,year2025_edge_positive=True,positive_years_min=2,bootstrap=dict(method='shared noncircular 20-session moving blocks; centered studentized one-sided maxT simultaneous lower',repeats=5000,seed=SEED,family_candidates=53,confidence=.95,zero_se='cannot pass'),ordering='eligible pooled edge descending, exact ties candidate ID ascending',none_allowed=True,economic_gate='only complete qualified SAME fixed bridge account can establish economic superiority; absent certification report selection-only, no promotion'),controls=cfg['controls'],inputs=inputs,sources={str(p):sha(p) for p in sources},runtime=pred.RUNTIME,exposure={'R1_two_roles_seen':True,'2023_2024':'exploration','2025':'already-exposed stability replication','2026':'already-exposed A2 scope, task outcome-blind frozen evaluation only after eligible finalist freeze','prior_effective_trial_count':'UNKNOWN; this53-family correction cannot erase prior selection/exposure'},new_research_authorization='explicit human V24 all-method training; preserve previous failures and nine-field differences; registry REVIEW is retained, no global status edit')
    path=run/'DESIGN_FREEZE.json';assert not path.exists(),'DO_NOT_OVERWRITE_FREEZE'
    putj(path,design);putj(run/'DESIGN_FREEZE_SHA.json',{'sha256':sha(path)})
    cfg.update(status='FROZEN_READY_TO_FIT',design_freeze_sha256=sha(path));putj(run/'run_config.json',cfg)
    emit(phase='V24_CANDIDATE_FREEZE',candidates=53,base_and_aux=40,learned_fit_budget=2000,physical_estimator_budget=650)

def checked(run):
    design=readj(run/'DESIGN_FREEZE.json');assert sha(run/'DESIGN_FREEZE.json')==readj(run/'DESIGN_FREEZE_SHA.json')['sha256']
    correction=readj(run/'SOURCE_CORRECTION.json') if (run/'SOURCE_CORRECTION.json').exists() else None
    for p,h in design['sources'].items():
        expected=h
        if correction and Path(p).resolve()==Path(__file__).resolve():
            assert correction['original_sha256']==h and correction['economic_outcome_access'] is False
            expected=correction['corrected_sha256']
        assert sha(p)==expected,f'FROZEN_SOURCE_CHANGED:{p}'
    return design

def reserve(run,name,year,learned,physical,phase):
    path=run/'FIT_LEDGER.json';ledger=readj(path) if path.exists() else dict(learned_fit_calls=0,physical_estimators=0,events=[])
    design=checked(run);assert ledger['learned_fit_calls']+learned<=design['budget']['max_learned_fit_calls'];assert ledger['physical_estimators']+physical<=design['budget']['max_physical_estimators']
    event=dict(id=f'{phase}:{name}:{year}',name=name,year=year,phase=phase,status='FIT_STARTED',started_at=now(),reserved_learned_calls=learned,reserved_physical_estimators=physical)
    assert all(e['id']!=event['id'] for e in ledger['events']),'INCOMPLETE_OR_FINISHED_FIT_ALREADY_RECORDED'
    ledger['learned_fit_calls']+=learned;ledger['physical_estimators']+=physical;ledger['events'].append(event);putj(path,ledger)
    return event['id']
def finish(run,event_id,**result):
    path=run/'FIT_LEDGER.json';ledger=readj(path);event=next(e for e in ledger['events'] if e['id']==event_id);event.update(finished_at=now(),**result);putj(path,ledger)

def data(run,rt):
    cfg,np,pd,pq,jb,pred,extra,shared,cal,coop=rt;d=checked(run);f=shared.FEATURES
    for key,item in d['inputs'].items():assert sha(item['path'])==item['sha256'],f'INPUT_CHANGED_BEFORE_READ:{key}'
    train=pd.read_parquet(d['inputs']['training']['path'],columns=['signal_date','ticker','target','target_end_date',*f])
    frame=pd.read_parquet(d['inputs']['features']['path'],columns=['signal_date','ticker',*f])
    members=pd.read_parquet(d['inputs']['members']['path'],columns=['signal_date','ticker','cusip','U_t_fingerprint'])
    for x in [train,frame,members]:
        x['signal_date']=pd.to_datetime(x.signal_date);assert not x.duplicated(['signal_date','ticker']).any()
    members['security_uid']='CUSIP:'+members.cusip.astype(str).str.strip().str.upper()
    assert not members.duplicated(['signal_date','security_uid']).any()
    frame=frame.merge(members[['signal_date','ticker','security_uid','U_t_fingerprint']],on=['signal_date','ticker'],validate='one_to_one',how='left');assert frame.security_uid.notna().all()
    train['target_end_date']=pd.to_datetime(train.target_end_date)
    frame=frame.merge(train[['signal_date','ticker','target','target_end_date']],on=['signal_date','ticker'],validate='one_to_one',how='left').rename(columns={'target_end_date':'label_end_date'})
    assert np.isfinite(frame[f]).all().all()
    proof=readj(run/'CALENDAR_EQUIVALENCE.json')
    assert proof['equal'] and sha(proof['calendar_path'])==proof['calendar_sha256']
    dates=pd.DatetimeIndex(sorted(frame.signal_date.unique()))
    assert hashlib.sha256('\n'.join(dates.strftime('%Y-%m-%d')).encode()).hexdigest()==proof['date_index_sha256']
    train=train.merge(members[['signal_date','ticker','security_uid']],on=['signal_date','ticker'],how='left',validate='one_to_one');assert train.security_uid.notna().all()
    return train,frame

def sampled(frame,pd,np):
    frame=frame.sort_values(['signal_date','security_uid']).reset_index(drop=True);rng=np.random.default_rng(SEED)
    quota=max(1,40000//frame.signal_date.nunique());indices=[]
    for _,g in frame.groupby('signal_date',sort=True):indices.extend(sorted(rng.choice(g.index,min(quota,len(g)),replace=False)))
    if len(indices)>40000:indices=sorted(rng.choice(indices,40000,replace=False))
    return frame.loc[indices].reset_index(drop=True)

def lags(frame,rows,features,pd,np):
    dates=pd.DatetimeIndex(sorted(frame.signal_date.unique()));positions=dates.get_indexer(rows.signal_date);assert (positions>=0).all()
    lookup=frame.set_index(['signal_date','security_uid'])[features];values=[];masks=[]
    for lag in reversed(range(8)):
        ix=positions-lag;valid=ix>=0;ds=dates[np.maximum(ix,0)]
        index=pd.MultiIndex.from_arrays([ds,rows.security_uid],names=['signal_date','security_uid'])
        a=lookup.reindex(index).to_numpy(dtype=float,copy=True);a[~valid]=np.nan;missing=~np.isfinite(a)
        values.append(np.nan_to_num(a,nan=0.));masks.append(missing.astype('float32'))
    return np.stack(values,axis=1),np.stack(masks,axis=1)

def score(raw,name,pred,np):
    if name in pred.PROBABILITY_NAMES:return raw['p']
    if name in pred.QUANTILE_NAMES:return raw['q10']
    if name in pred.DISTRIBUTION_NAMES:return raw['location']-.5*raw['scale']
    if name in pred.RANK_NAMES:return raw['rank']
    return raw['raw']

def train_base(run):
    rt=runtime(run);cfg,np,pd,pq,jb,pred,extra,shared,cal,coop=rt;design=checked(run);train,frame=data(run,rt);features=shared.FEATURES
    keys=['signal_date','ticker','security_uid','U_t_fingerprint','target','label_end_date']
    for year in YEARS:
        cutoff=pd.Timestamp(f'{year}-01-01');tr=sampled(train.loc[train.signal_date.lt(cutoff)&train.target_end_date.lt(cutoff)],pd,np);va=frame.loc[frame.signal_date.dt.year.eq(year)].sort_values(['signal_date','security_uid']).reset_index(drop=True)
        assert len(tr) and len(va);sample_path=run/f'derived/training_keys_{year}.parquet'
        sample_keys=tr[['signal_date','ticker','security_uid','target_end_date']]
        if sample_path.exists():assert pd.read_parquet(sample_path).equals(sample_keys),'RESUME_SAMPLE_KEYS_CHANGED'
        else:sample_keys.to_parquet(sample_path,index=False)
        xx=tr[features].to_numpy(float);vv=va[features].to_numpy(float);y=tr.target.to_numpy(float)
        seq_train=seq_valid=None
        for name in list(pred.NAMES)+EXTRA:
            out=run/f'predictions/native_{name}_{year}.parquet';meta=run/f'models/{name}/{year}.json';modelpath=meta.with_suffix('.joblib')
            expected=dict(name=name,year=year,seed=SEED,target=TARGET,features=features,cutoff=str(cutoff.date()),training_sha256=design['inputs']['training']['sha256'],feature_sha256=design['inputs']['features']['sha256'],sampled_keys_sha256=sha(sample_path),design_sha256=sha(run/'DESIGN_FREEZE.json'))
            repair=False
            if meta.exists() and name in extra.SEQUENCE_NAMES:
                prior=readj(meta)
                assert all(prior['spec'].get(k)==v for k,v in expected.items()),'ORIGINAL_FAILED_FIT_IDENTITY_CHANGED'
                repair=prior['status']=='FAILED' and prior.get('message')=='assignment destination is read-only' and (run/'SOURCE_CORRECTION.json').exists()
                if repair:meta=meta.with_name(f'{year}_repair1.json');modelpath=meta.with_suffix('.joblib')
            if meta.exists():
                rec=readj(meta)

                assert all(rec['spec'].get(k)==v for k,v in expected.items()),'RESUME_FIT_IDENTITY_CHANGED'
                if rec['status']=='FAILED':continue
                assert sha(modelpath)==rec['model_sha256'] and sha(out)==rec['prediction_sha256'];continue
            physical=3 if name in pred.QUANTILE_NAMES else 1
            # Reserve model, preprocessing, neural target estimates and allowed numeric continuation.
            learned=physical+1+(2*physical if name in ['mlp','resnet','fttransformer','mlp_q','gaussian_mlp'] else 0)+(1 if name in ['elastic','huber','logistic'] else 0)
            if name in extra.AUXILIARY_NAMES:learned=4;physical=2
            if name in extra.SEQUENCE_NAMES:learned=4
            if name=='cat_uncertainty':learned+=2
            event=reserve(run,name,year,learned,physical+(1 if name in ['elastic','huber','logistic'] else 0),'BASE_INPUT_REPAIR' if repair else 'BASE');started=time.monotonic();emit(phase='REAL_FIT',name=name,year=year,rows=len(tr))
            spec=dict(name=name,year=year,sampled_keys_sha256=sha(sample_path),training_sha256=design['inputs']['training']['sha256'],feature_sha256=design['inputs']['features']['sha256'],cutoff=str(cutoff.date()),max_train_label_end=str(tr.target_end_date.max()),features=features,target=TARGET,seed=SEED,design_sha256=sha(run/'DESIGN_FREEZE.json'),executed_orchestrator_sha256=sha(__file__),source_correction_sha256=sha(run/'SOURCE_CORRECTION.json') if (run/'SOURCE_CORRECTION.json').exists() else None)
            details=None
            try:
                if name in pred.NAMES:
                    fitted=pred.fit(name,xx,y,tr.signal_date);details=fitted.fit_status;raw=pred.predict_raw(fitted,vv,va.signal_date)
                    if any(z['status']!='TRAINED' for z in details):raise RuntimeError('FAILED_PHYSICAL_SPEC')
                elif name in extra.SEQUENCE_NAMES:
                    from sklearn.preprocessing import StandardScaler
                    if seq_train is None:seq_train=lags(frame,tr,features,pd,np);seq_valid=lags(frame,va,features,pd,np)
                    scaler=StandardScaler().fit(xx)
                    a=(seq_train[0]-scaler.mean_[None,None,:])/scaler.scale_[None,None,:]
                    b=(seq_valid[0]-scaler.mean_[None,None,:])/scaler.scale_[None,None,:]
                    estimator=extra.fit(name,a,y,missing_mask=seq_train[1]);raw={'raw':estimator.predict(b,missing_mask=seq_valid[1])};fitted={'estimator':estimator,'scaler':scaler};details=estimator.metadata
                else:
                    fitted=extra.fit(name,xx,y);raw={'raw':fitted.predict(vv)};details=fitted.metadata
                values=score(raw,name,pred,np);assert values.shape==(len(va),) and np.isfinite(values).all()
                part=va[keys].copy();part['source_kind']='MODEL_OOF';part['source_cutoff']=cutoff
                for col,v in raw.items():part[f'{name}__{col}']=v
                part['score']=values;part['candidate_id']=name
                out.parent.mkdir(parents=True,exist_ok=True);modelpath.parent.mkdir(parents=True,exist_ok=True)
                jb.dump(fitted,modelpath,compress=3);part.to_parquet(out,index=False)
                receipt=dict(status='TRAINED',spec=spec,details=details,model_path=str(modelpath),model_sha256=sha(modelpath),prediction_path=str(out),prediction_sha256=sha(out),rows=len(part),seconds=time.monotonic()-started)
                putj(meta,receipt);finish(run,event,status='TRAINED',model_path=str(modelpath),prediction_path=str(out),seconds=receipt['seconds'])
                emit(phase='MODEL_OOF_DONE',name=name,year=year,rows=len(part),seconds=receipt['seconds'])
            except Exception as e:
                failure=dict(status='FAILED',spec=spec,details=details,error=type(e).__name__,message=str(e),traceback=traceback.format_exc(),seconds=time.monotonic()-started)
                putj(meta,failure);finish(run,event,status='FAILED',error=type(e).__name__,message=str(e));emit(phase='FIT_FAILURE_RETAINED',name=name,year=year,error=str(e))
        emit(phase='ANNUAL_BASE_WAVE_FINISHED',year=year)
    putj(run/'BASE_COMPLETION.json',dict(finished_at=now(),phase='BASE_ATTEMPTS_COMPLETE',years=list(YEARS),candidates=40,test2026_read=False))


def resume_cooperation(run,meta):
    if not meta.exists():return False
    rec=readj(meta)
    if rec['status'] in ['FAILED','BLOCKED_DEPENDENCY']:return True
    assert rec['status']=='TRAINED' and rec.get('design_sha256')==sha(run/'DESIGN_FREEZE.json'),'RESUME_COOP_IDENTITY_CHANGED'
    assert sha(rec['model_path'])==rec['model_sha256'] and sha(rec['prediction_path'])==rec['prediction_sha256'],'RESUME_COOP_ARTIFACT_CHANGED'
    return True

def train_cooperation(run):
    rt=runtime(run);cfg,np,pd,pq,jb,pred,extra,shared,cal,coop=rt;d=checked(run);train,features=data(run,rt)
    context=cal.SPEC['context'];context_frame=features[['signal_date','security_uid',*context,*[f for f in shared.FEATURES if f not in context]]]
    for name in d['base']:
        for year in (2022,2023,2024,2025):
            dst=run/f'predictions/calibrated_{name}_{year}.parquet';meta=run/f'models/calibration_{name}/{year}.json';artifact=meta.with_suffix('.joblib')
            if resume_cooperation(run,meta):continue
            current=run/f'predictions/native_{name}_{year}.parquet'
            earlier=[run/f'predictions/native_{name}_{y}.parquet' for y in YEARS if y<year]
            if not current.exists() or not all(p.exists() for p in earlier):
                putj(meta,dict(status='BLOCKED_DEPENDENCY',reason='earlier or current model failed; do not drop/swap member'));continue
            cutoff=pd.Timestamp(f'{year}-01-01');history=pd.concat([pd.read_parquet(p) for p in earlier],ignore_index=True)
            history=history.loc[history.label_end_date.lt(cutoff)&history.target.notna()].copy()
            learned=8 if name in pred.PROBABILITY_NAMES else 6
            event=reserve(run,name,year,learned,2,'CALIBRATION');started=time.monotonic()
            try:
                obj,receipt=coop.fit_calibration(cal,name,history,cutoff)
                current_frame=pd.read_parquet(current);mu,uncertainty,p=obj.predict(current_frame)
                out=current_frame[['signal_date','ticker','security_uid','U_t_fingerprint','target','label_end_date']].copy()
                out['source_kind']='CALIBRATED_OOF';out['source_cutoff']=cutoff;out[f'{name}__mu']=mu;out[f'{name}__uncertainty']=uncertainty
                out[f'{name}__calibration_cutoff']=cutoff;out[f'{name}__calibration_max_label_end']=history.label_end_date.max()
                out=out.merge(context_frame,on=['signal_date','security_uid'],validate='one_to_one',how='left')
                assert np.isfinite(out[f'{name}__mu']).all() and np.isfinite(out[f'{name}__uncertainty']).all()
                artifact.parent.mkdir(parents=True,exist_ok=True);jb.dump(obj,artifact,compress=3);out.to_parquet(dst,index=False)
                putj(meta,dict(status='TRAINED',receipt=receipt,design_sha256=sha(run/'DESIGN_FREEZE.json'),executed_orchestrator_sha256=sha(__file__),model_path=str(artifact),model_sha256=sha(artifact),prediction_path=str(dst),prediction_sha256=sha(dst),seconds=time.monotonic()-started))
                finish(run,event,status='TRAINED',model_path=str(artifact),prediction_path=str(dst));emit(phase='CALIBRATED_OOF_DONE',name=name,year=year)
            except Exception as e:
                putj(meta,dict(status='FAILED',message=str(e),traceback=traceback.format_exc()));finish(run,event,status='FAILED',message=str(e));emit(phase='CALIBRATION_FAILURE',name=name,year=year,error=str(e))
    def combined(year):
        frames=[]
        for m in MEMBERS:
            p=run/f'predictions/calibrated_{m}_{year}.parquet'
            if not p.exists():raise ValueError(f'FROZEN_MEMBER_UNAVAILABLE:{m}:{year}')
            frames.append(pd.read_parquet(p))
        result=frames[0]
        identity=['signal_date','security_uid','ticker','U_t_fingerprint','target','label_end_date']
        for m,part in zip(MEMBERS[1:],frames[1:]):
            assert part[identity].equals(frames[0][identity]),f'FUSION_MEMBER_COMMON_POOL_CHANGED:{m}:{year}'
            result=result.merge(part[['signal_date','security_uid',f'{m}__mu',f'{m}__calibration_cutoff',f'{m}__calibration_max_label_end']],on=['signal_date','security_uid'],how='left',validate='one_to_one')
        return result
    for year in (2023,2024,2025):
        cutoff=pd.Timestamp(f'{year}-01-01')
        try:
            current=combined(year);earlier=pd.concat([combined(y) for y in (2022,2023,2024) if y<year],ignore_index=True)
            history=earlier.loc[earlier.label_end_date.lt(cutoff)&earlier.target.notna()].copy()
        except Exception as e:
            for name in FUSIONS:
                meta=run/f'models/{name}/{year}.json'
                if not meta.exists():putj(meta,dict(status='BLOCKED_DEPENDENCY',message=str(e)))
                else:resume_cooperation(run,meta)
            current=history=None
        for name in FUSIONS:
            if current is None:continue
            meta=run/f'models/{name}/{year}.json';dst=run/f'predictions/native_{name}_{year}.parquet';artifact=meta.with_suffix('.joblib')
            if resume_cooperation(run,meta):continue
            learned=0 if name in ['equal','median','fixed_weighted'] else 3 if name in ['nnls','simplex'] else 4
            physical=0 if name in ['equal','median','fixed_weighted','nnls','simplex'] else 1
            event=reserve(run,name,year,learned,physical,'FUSION')
            try:
                obj,receipt=coop.fit_fusion(cal,name,MEMBERS,history,cutoff)
                values=obj.predict(current[[f'{m}__mu' for m in MEMBERS]].to_numpy(float),current[context].to_numpy(float));assert np.isfinite(values).all()
                out=current[['signal_date','ticker','security_uid','U_t_fingerprint','target','label_end_date']].copy();out['source_kind']='PIPELINE_OOF';out['source_cutoff']=cutoff;out['score']=values;out['candidate_id']=name
                artifact.parent.mkdir(parents=True,exist_ok=True);jb.dump(obj,artifact,compress=3);out.to_parquet(dst,index=False)
                putj(meta,dict(status='TRAINED',receipt=receipt,design_sha256=sha(run/'DESIGN_FREEZE.json'),executed_orchestrator_sha256=sha(__file__),model_path=str(artifact),model_sha256=sha(artifact),prediction_path=str(dst),prediction_sha256=sha(dst)))
                finish(run,event,status='TRAINED',prediction_path=str(dst));emit(phase='FUSION_OOF_DONE',name=name,year=year)
            except Exception as e:
                putj(meta,dict(status='FAILED',message=str(e),traceback=traceback.format_exc()));finish(run,event,status='FAILED',message=str(e))
        for name in RESIDUALS:
            first,second=('ridge','hgb') if name=='ridge_then_hgb' else ('hgb','ridge')
            meta=run/f'models/{name}/{year}.json';dst=run/f'predictions/native_{name}_{year}.parquet';artifact=meta.with_suffix('.joblib')
            if resume_cooperation(run,meta):continue
            files=[run/f'predictions/native_{first}_{y}.parquet' for y in YEARS if y<year];current_path=run/f'predictions/native_{first}_{year}.parquet'
            if not all(p.exists() for p in files+[current_path]):putj(meta,dict(status='BLOCKED_DEPENDENCY'));continue
            event=reserve(run,name,year,2,1,'RESIDUAL')
            try:
                h=pd.concat([pd.read_parquet(p) for p in files],ignore_index=True);h=h.loc[h.label_end_date.lt(cutoff)&h.target.notna()].copy()
                assert h.source_cutoff.lt(h.signal_date).all() and h.source_kind.eq('MODEL_OOF').all()
                h=h.merge(context_frame,on=['signal_date','security_uid'],validate='one_to_one');h=sampled(h,pd,np)
                target=h.target.to_numpy(float)-h[f'{first}__raw'].to_numpy(float)
                obj=pred.fit(second,h[shared.FEATURES].to_numpy(float),target,h.signal_date)
                cur=pd.read_parquet(current_path).merge(context_frame,on=['signal_date','security_uid'],validate='one_to_one')
                values=cur[f'{first}__raw'].to_numpy(float)+pred.predict_raw(obj,cur[shared.FEATURES].to_numpy(float))['raw'];assert np.isfinite(values).all()
                out=cur[['signal_date','ticker','security_uid','U_t_fingerprint','target','label_end_date']].copy();out['source_kind']='PIPELINE_OOF';out['source_cutoff']=cutoff;out['score']=values;out['candidate_id']=name
                artifact.parent.mkdir(parents=True,exist_ok=True);jb.dump(obj,artifact,compress=3);out.to_parquet(dst,index=False)
                putj(meta,dict(status='TRAINED',design_sha256=sha(run/'DESIGN_FREEZE.json'),executed_orchestrator_sha256=sha(__file__),stage1=first,stage2=second,residual_source='TRUE_ANNUAL_MODEL_OOF',rows=len(h),max_label_end=str(h.label_end_date.max()),model_path=str(artifact),model_sha256=sha(artifact),prediction_path=str(dst),prediction_sha256=sha(dst)))
                finish(run,event,status='TRAINED',prediction_path=str(dst));emit(phase='RESIDUAL_OOF_DONE',name=name,year=year)
            except Exception as e:
                putj(meta,dict(status='FAILED',message=str(e),traceback=traceback.format_exc()));finish(run,event,status='FAILED',message=str(e))
    putj(run/'COOPERATION_COMPLETION.json',dict(finished_at=now(),phase='COOPERATION_ATTEMPTS_COMPLETE',test2026_read=False))


def rank_panel(frame,pd):
    frame=frame.sort_values(['signal_date','score','security_uid'],ascending=[True,False,True],kind='stable').copy()
    frame['rank']=frame.groupby('signal_date',sort=False).cumcount()+1
    return frame.sort_values(['signal_date','security_uid']).reset_index(drop=True)

def assemble_scores(run):
    rt=runtime(run);cfg,np,pd,pq,jb,pred,extra,shared,cal,coop=rt;d=checked(run);train,frame=data(run,rt)
    raw=pd.read_parquet(d['inputs']['raw_oof']['path'],columns=['signal_date','ticker','a2_prediction'])
    raw=raw.merge(frame[['signal_date','ticker','security_uid','U_t_fingerprint','target','label_end_date']],on=['signal_date','ticker'],validate='one_to_one')
    raw['score']=raw.a2_prediction;raw['candidate_id']='RAW_A2_SCORE_IN_COMMON_13F_UNIVERSE';raw=rank_panel(raw,pd)
    raw.to_parquet(run/'predictions/scores_RAW_A2_SCORE_IN_COMMON_13F_UNIVERSE_pre2026.parquet',index=False)
    keys=raw[['signal_date','security_uid']];valid=[];failed={}
    for name in d['candidates']:
        parts=[run/f'predictions/native_{name}_{y}.parquet' for y in (2023,2024,2025)]
        if not all(p.exists() for p in parts):
            failed[name]='MISSING_REQUIRED_ANNUAL_OOF';continue
        out=pd.concat([pd.read_parquet(p) for p in parts],ignore_index=True)
        assert out[['signal_date','security_uid']].sort_values(['signal_date','security_uid']).reset_index(drop=True).equals(keys)
        assert out.source_cutoff.lt(out.signal_date).all() and np.isfinite(out.score).all()
        out=rank_panel(out,pd);out.to_parquet(run/f'predictions/scores_{name}_pre2026.parquet',index=False);valid.append(name)
    putj(run/'SCORE_ASSEMBLY.json',dict(complete_candidates=valid,failed_or_untestable=failed,common_rows=len(raw),common_dates=raw.signal_date.nunique(),raw_candidate_id='RAW_A2_SCORE_IN_COMMON_13F_UNIVERSE',forecast2026_rows=0))
    emit(phase='ALL_SCORE_RANKS_ASSEMBLED',valid=len(valid),failed=len(failed),rows=len(raw))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True);parser.add_argument('--phase',choices=['freeze','base','cooperation','assemble'],required=True);args=parser.parse_args()
    from scripts.common.storage_paths import resolve
    paths=resolve(REPO);run=args.run.resolve();assert run.is_relative_to(paths.backtest_root.resolve()) and (run/'run_config.json').is_file()
    {'freeze':freeze,'base':train_base,'cooperation':train_cooperation,'assemble':assemble_scores}[args.phase](run)
if __name__=='__main__':main()
