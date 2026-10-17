"""Bounded risk/non-ML selector increment; reuse canonical fits and OOF math.

This binds one new scientific input (prior risk structures) to the existing C
score study. It owns no estimator, universe, account or execution implementation.
"""
from __future__ import annotations
import argparse,copy,hashlib,json,time,traceback,multiprocessing as mp
from pathlib import Path
import numpy as np
import pandas as pd
from scripts.research.a2.training import selector_challenge as prior
from scripts.research.a2.training import selector_risk_features as risk_features
from scripts.research.a2.risk import joint_risk_estimators as risk

REPO=prior.REPO
METHODS=tuple(m for m in risk.CONFIGS if m!='HISTVOL')
CORE=('DIAG','LW','OAS','PCA','EWMA')
HEADS=('ridge','hgb')
MEMBERS=tuple(prior.MEMBERS)
NEW=tuple(f'risk_{m.lower()}_{h}' for m in METHODS for h in HEADS)+('risk_bank_ridge','risk_bank_hgb','risk_bank_sigma_penalty','risk_bank_covariance_penalty')
KEY=['signal_date','security_uid']
REUSE_PATH=Path('D:/us-tech-quant-backtests/A2_STATEFUL_ACTION_AND_CASH_PRE2026_TEST2026_R2/20261001T171850+0000_84ddc481/contracts/RISK_BANK_REUSE_INVENTORY.json')
REUSE_SHA='270df6deb629f9c9dcbf267e30ac6f6404b22f1166e4ec20a98773e6d2f4dbf9'

def state(run,phase,status='RUNNING',**values):
    p=run/'PIPELINE_STATE.json';d=prior.readj(p);d.update(phase=phase,status=status,updated_at=prior.now(),**values)
    prior.putj(p,d)

def checked(run):
    d=prior.checked(run)
    assert d['research_round']=='R2' and d['target']==prior.TARGET
    return d

def _risk_worker(pipe,method,table,market,params):
    try:
        result=risk.fit_risk_estimator(method,table,market_returns=market,params=params)
        pipe.send(('RESULT',result))
    except BaseException as exc:
        pipe.send(('ERROR',type(exc).__name__+':'+str(exc)))
    finally:pipe.close()


def bounded_risk_fit(method,table,market,params,timeout=1800):
    # Same spawn/pipe hard-deadline pattern as stateful_values; no task/data owner import.
    context=mp.get_context('spawn');parent,child=context.Pipe()
    worker=context.Process(target=_risk_worker,args=(child,method,table,market,params))
    worker.start();child.close();deadline=time.monotonic()+timeout
    try:
        while time.monotonic()<deadline:
            if parent.poll(min(.25,max(0,deadline-time.monotonic()))):
                result=parent.recv()
                if result[0]!='RESULT':raise RuntimeError('RISK_WORKER_FAILED:'+result[1])
                worker.join(timeout=5)
                if worker.is_alive() or worker.exitcode!=0:raise RuntimeError('RISK_WORKER_EXIT_AFTER_RESULT')
                return result[1]
            if not worker.is_alive():raise RuntimeError('RISK_WORKER_EXIT_WITHOUT_RESULT:'+str(worker.exitcode))
        raise TimeoutError('RISK_FIXED_1800_SECOND_BUDGET_EXCEEDED')
    finally:
        if worker.is_alive():worker.terminate()
        worker.join(timeout=5);parent.close()


def risk_identity(table,cutoff):
    return dict(fit_cutoff=cutoff.isoformat(),return_unit=risk_features.UNIT,return_horizon_sessions=1,source_id='CANONICAL_C_PIT32_RET1D_STATIC63',information_set_id=hashlib.sha256(pd.util.hash_pandas_object(table,index=True).to_numpy(np.uint64).tobytes()).hexdigest())

def parent_members(parent,year,cal,coop,cutoff=None):
    frames=[]
    for m in MEMBERS:
        p=parent/f'predictions/calibrated_{m}_{year}.parquet';prior.sha(p)
        f=pd.read_parquet(p)
        if not f.source_kind.eq('CALIBRATED_OOF').all() or not f.source_cutoff.lt(f.signal_date).all():raise ValueError('INVALID_PARENT_CALIBRATED_OOF')
        cc,ml=f'{m}__calibration_cutoff',f'{m}__calibration_max_label_end'
        if not f[cc].lt(f.signal_date).all() or not f[ml].lt(f[cc]).all():raise ValueError('PARENT_CALIBRATION_CLOCK')
        frames.append(f)
    identity=KEY+['ticker','U_t_fingerprint','target','label_end_date']
    base=frames[0].copy()
    for m,f in zip(MEMBERS[1:],frames[1:]):
        if not f[identity].equals(frames[0][identity]):raise ValueError('PARENT_EXACT_COMMON_KEYS')
        base=base.merge(f[KEY+[f'{m}__mu',f'{m}__uncertainty',f'{m}__calibration_cutoff',f'{m}__calibration_max_label_end']],on=KEY,validate='one_to_one')
    return base

def freeze(run):
    rt=prior.runtime(run);cfg,np_,pd_,pq,jb,pred,extra,shared,cal,coop=rt
    parent=Path(cfg['parent_run']);old=prior.readj(parent/'DESIGN_FREEZE.json')
    assert prior.sha(parent/'DESIGN_FREEZE.json')==cfg['parent_design_sha256']
    assert prior.sha(REUSE_PATH)==REUSE_SHA
    # Source/field/date proofs precede any new fitting; identities are immutable.
    for label,item in old['inputs'].items():
        assert prior.sha(item['path'])==item['sha256'],label
        pf=pq.ParquetFile(item['path'])
        for col in (['signal_date','target_end_date'] if label=='training' else ['signal_date']):
            j=pf.schema_arrow.get_field_index(col);assert j>=0
            for i in range(pf.num_row_groups):
                s=pf.metadata.row_group(i).column(j).statistics
                assert s and s.has_min_max and s.null_count==0 and pd.Timestamp(s.max)<pd.Timestamp('2026-01-01')
    sources={str(p):prior.sha(p) for p in [*[Path(z) for z in old['sources']],Path(__file__),Path(risk_features.__file__),Path(risk.__file__),REPO/'scripts/research/a2/retained/a2_pto_full_compat_20260928_r2/risk_models.py',Path(prior.__file__),Path(coop.__file__),prior.RETAINED/'predictors.py',prior.RETAINED/'calibration_fusion.py',prior.RETAINED/'shared.py',REPO/'scripts/research/a2/evaluation/selector_evidence.py',REPO/'scripts/research/a2/evaluation/selector_account_compare.py']}
    reused={}
    ready=prior.readj(parent/'SCORE_ASSEMBLY.json')
    for cid in [ready['raw_candidate_id'],*ready['complete_candidates']]:
        p=parent/f'predictions/scores_{cid}_pre2026.parquet';reused[cid]={'path':str(p),'sha256':prior.sha(p)}
    meta_pins={}
    for y in (2022,2023,2024,2025):
        for m in MEMBERS:
            p=parent/f'predictions/calibrated_{m}_{y}.parquet';receipt=parent/f'models/calibration_{m}/{y}.json';r=prior.readj(receipt)
            assert r['status']=='TRAINED' and r['prediction_sha256']==prior.sha(p) and r['design_sha256']==cfg['parent_design_sha256']
            pf=pq.ParquetFile(p);j=pf.schema_arrow.get_field_index('signal_date');assert j>=0
            for k in range(pf.num_row_groups):
                stat=pf.metadata.row_group(k).column(j).statistics
                assert stat and stat.has_min_max and stat.null_count==0 and pd.Timestamp(stat.min)>=pd.Timestamp(f'{y}-01-01') and pd.Timestamp(stat.max)<pd.Timestamp(f'{y+1}-01-01')
            meta_pins[str(p)]=prior.sha(p);meta_pins[str(receipt)]=prior.sha(receipt)
    d=copy.deepcopy(old);d.update(research_round='R2',research_id=cfg['research_id'],freeze_at=prior.now(),parent_run=str(parent),parent_design_sha256=cfg['parent_design_sha256'],candidates=old['candidates']+list(NEW),new_candidates=list(NEW),sources=sources,score_reuse=reused,parent_meta_pins=meta_pins,risk_reuse={'path':str(REUSE_PATH),'sha256':REUSE_SHA},risk_methods=list(METHODS),risk_specs=risk.specs(),risk_core=list(CORE),risk_fit_years=[2021,2022,2023,2024,2025],risk_info='canonical PIT32 ret_1d; exactly63 sessions before annual cutoff; no target labels; no extra PIT exposures',risk_projection='reference w_i=1/len(current full common UID pool); sigma=sqrt(Sigma_ii); contribution=(Sigma*w)_i/sqrt(w.T*Sigma*w), no w_i multiplier; signed values retained; daily fractional proxy units; annual state applies only signals strictly later than Jan1; unknown independent prior-median variance+flag, no eligibility upgrade; no holding/q/G output',risk_meta={'members':list(MEMBERS),'heads':['Ridge alpha100','retained HGB tree64/depth3/min_leaf100'],'training':'earlier genuine CALIBRATED_OOF, risk fitted before its signal; mature labels before current cutoff; same retained day-balanced40k/date_weights','penalty':{'gamma':.1,'horizon_sigma_multiplier':float(np.sqrt(6.)),'score':'mean five calibrated mu minus gamma*sqrt(6)*mean fixed core sigma or signed covariance contribution; 6=sum squared shared-increment weights for mean(3,5,10,20) under IID daily simple-return approximation; daily stock PIT proxy, not exact QQQ excess-return target uncertainty'},'bank_members':list(CORE),'missing_core':'BLOCKED_DEPENDENCY; never swap member','extra_exposures':'INDUSTRY/FUNDAMENTAL untestable in canonical PIT32-only C; no permission inference'},new_scientific_increment='PTO risk/non-ML score contribution, not more ML names or new architectures',risk_aliases={'HISTVOL':'DIAG'},corporate_event_state='separate bounded source-only side research, no fitting or selection in this frozen run',new_budget={'max_learned_fit_calls':500,'max_physical_estimators':220,'max_risk_state_estimates':510,'max_new_candidates':38,'max_finalists':3,'max_full_account_paths':60,'workers':1,'threads':2,'seeds':1,'configs_per_role':1,'risk_fit_timeout_seconds':1800},stopping='one frozen attempt per scientific slot; technical zero-fit repair bounded; no outcome-driven additions')
    d['budget']=dict(max_learned_fit_calls=500,max_physical_estimators=220,max_risk_state_estimates=510,max_primary_candidates=91,max_finalists=3,max_full_account_paths=60,configs_per_role=1,seeds_per_role=1)
    d['selection_rule']['bootstrap']['family_candidates']=91
    d['selection_rule']['economic_gate']='qualified same fixed account with PRIMARY 10bps hypothetical adverse Open slippage; report0/5/20 sensitivity without picking scenario; no certification no economic promotion'
    d['controls']['slippage_bps']=10
    d['execution_friction']={'primary_bps':10,'sensitivity_bps':[0,5,20],'fee_bps':0,'kind':'FIXED_ADVERSE_OPEN_SLIPPAGE','authority':'HYPOTHETICAL_RESEARCH_SCENARIO','real_quote_certification':False,'mutually_exclusive_with_legacy_cost_bps':True}
    d['primary_account_candidates']=[ready['raw_candidate_id'],'ridge_stack','hgb_stack',*NEW]
    d['account_scenario_plan']={'10':d['primary_account_candidates'],'0_5_20':'Raw plus up to3 frozen selection finalists; if none Raw+ridge_stack+hgb_stack controls only','max_primary':41,'max_sensitivity':12,'reserved_conditional2026':4,'max_total_planned':57,'count':'distinct candidate/bps/prefix, failed attempts charged too'}
    d['selection_rule']['economic_gate']+='; PRIMARY final net NAV must exceed Raw at same10bps; sensitivity is diagnostic only; otherwise no promotion'
    d['exposure'].update(previous_V24_all_results_seen=True,earlier_rounds='single ML -> multi ML -> PTO; same layers each time',current_round='PTO plus risk/non-ML package; scientific target refit already performed in C parent when one-day target changed to Raw meanER')
    assert len(d['candidates'])==len(set(d['candidates']))==91
    dest=run/'DESIGN_FREEZE.json';assert not dest.exists();prior.putj(dest,d);prior.putj(run/'DESIGN_FREEZE_SHA.json',{'sha256':prior.sha(dest)})
    cfg.update(design_freeze_sha256=prior.sha(dest),status='FROZEN_READY_TO_FIT',controls=d['controls'],cost_assumption='FEES0_PRIMARY_HYPOTHETICAL_ADVERSE_OPEN_SLIPPAGE10BPS')
    prior.putj(run/'run_config.json',cfg)
    proof=parent/'CALENDAR_EQUIVALENCE.json';prior.putj(run/'CALENDAR_EQUIVALENCE.json',prior.readj(proof))
    state(run,'FREEZE','FROZEN_READY_TO_FIT',candidate_count=91,new_candidates=38,new_fit_count=0)
    prior.emit(phase='R2_MULTI_RISK_FREEZE',candidates=91,new=38)

def risk_stages(run):
    rt=prior.runtime(run);cfg,np_,pd_,pq,jb,pred,extra,shared,cal,coop=rt;d=checked(run);_,frame=prior.data(run,rt)
    inventory=prior.readj(REUSE_PATH);lineages=inventory['annual_input_lineages'];slots={(z['method_id'],z['year']):z for z in inventory['receipts']}
    fits=0
    for year in (2021,2022,2023,2024,2025):
        cutoff=pd.Timestamp(f'{year}-01-01');table,line=risk_features.annual_returns(frame,cutoff)
        matches=[x for x in lineages.values() if x['cutoff_exclusive']==cutoff.isoformat() and x['returns_sha256']==line['returns_sha256'] and x['assets']==line['assets'] and x['dates']==line['dates'] and x['return_unit']==line['return_unit'] and x['return_horizon_sessions']==1]
        prior.putj(run/f'derived/risk_input_{year}.json',line);bundles={}
        for method in METHODS:
            mp=run/f'models/risk_{method}/{year}.json';out=run/f'predictions/risk_{method}_{year}.parquet'
            if mp.exists():
                rec=prior.readj(mp)
                assert rec['design_sha256']==prior.sha(run/'DESIGN_FREEZE.json')
                if rec['status']!='FITTED':continue
                assert rec['input_returns_sha256']==line['returns_sha256'] and prior.sha(rec['model_path'])==rec['model_sha256'] and prior.sha(out)==rec['projection_sha256']
                bundles[method]=jb.load(rec['model_path']);continue
            state(run,'RISK',method=method,year=year)
            rec=dict(method=method,year=year,input_returns_sha256=line['returns_sha256'],cutoff_exclusive=str(cutoff.date()),design_sha256=prior.sha(run/'DESIGN_FREEZE.json'))
            event=None
            try:
                if method in ('INDUSTRY','FUNDAMENTAL'):raise risk.RiskEstimatorBlocked('BLOCKED_INPUT:NO_EXTRA_EXPOSURE_IN_CANONICAL_C_PIT32')
                slot=slots.get((method,year));same=slot is not None and method!='SINGLE_INDEX' and any(x is lineages.get(slot['annual_input_lineage_id']) for x in matches)
                if same:
                    assert prior.sha(slot['receipt_path'])==slot['receipt_sha256']
                    pins=inventory['source_pin_sets'][slot['source_pins_id']]
                    assert pins['joint_source_sha256']==prior.sha(risk.__file__) and pins['garch_definition_source_sha256']==prior.sha(REPO/'scripts/research/a2/retained/a2_pto_full_compat_20260928_r2/risk_models.py')
                    assert slot['reuse_tuple']['seed']==prior.SEED and slot['reuse_tuple']['window_sessions']==63 and slot['reuse_tuple']['annual_static']
                    if slot['status']=='FITTED':assert slot['scientific_feature_pit_qualified'] and slot['scientific_return_proxy_qualified']
                    if slot['status']!='FITTED':
                        rec.update(status='FAILED_PRIOR_REUSED',failure=slot.get('failure','producer failed'),producer_slot=slot);prior.putj(mp,rec);continue
                    assert prior.sha(slot['model_path'])==slot['model_sha256'];obj=jb.load(slot['model_path'])
                    assert obj.fitted_state['fit_identity_sha256']==slot['canonical_bundle_identity']
                    rec.update(reuse='EXACT_NUMERIC_INPUT_SOURCE_METHOD_CUTOFF_UNIT',producer_slot=slot,model_path=slot['model_path'],model_sha256=slot['model_sha256'])
                else:
                    if method=='NONLINEAR_SHRINKAGE':raise risk.RiskEstimatorBlocked('BLOCKED_DEPENDENCY:GENUINE_NLS_BACKEND_NOT_SNAPSHOTTED')
                    if method=='ROBUST_COV' and len(table)<=int((table.notna().sum()>=30).sum()):raise risk.RiskEstimatorBlocked('BLOCKED_INPUT:MINCOVDET_ROWS_LE_ASSETS')
                    event=prior.reserve(run,method,year,6,2,'RISK');prior.emit(phase='REAL_RISK_FIT',method=method,year=year,rows=len(table),assets=table.shape[1])
                    start=time.monotonic()
                    if method=='COV_ENSEMBLE':
                        if not all(m in bundles for m in ('LW','OAS')):raise risk.RiskEstimatorBlocked('BLOCKED_DEPENDENCY:LW_OAS')
                        obj=copy.deepcopy(bundles['LW']);parts=[]
                        for m in ('LW','OAS'):
                            b=bundles[m];parts.append(b.covariance-np.eye(len(b.covariance))*b.fitted_state['diagonal_ridge_added'])
                        obj.covariance,psd=risk.validate_covariance(.5*(parts[0]+parts[1]));obj.method_id=method;obj.specification={**risk.specs(method),**risk_identity(table,cutoff)};obj.fitted_state.update(psd,component_reuse=['LW','OAS']);obj.budget.update(preprocessing_estimates=0,estimator_state_estimations=0,total_state_estimations=1,derived_covariance_blend_estimates=1)
                        component_ids={m:bundles[m].fitted_state['fit_identity_sha256'] for m in ('LW','OAS')}
                        obj.fitted_state.update(component_fit_identities=component_ids,fit_identity_sha256=hashlib.sha256(json.dumps({'method':method,'input':line['returns_sha256'],'specification':obj.specification,'components':component_ids},sort_keys=True).encode()).hexdigest())
                    else:
                        market=None
                        if method=='SINGLE_INDEX':
                            index_names=frame.loc[frame.signal_date.eq(table.index[-1]),'ticker'];market=table.reindex(columns=index_names).mean(axis=1);market.attrs['source_id']='FIXED_LAST_PRIOR_COMMON_POOL_EQUAL_INDEX'
                        obj=bounded_risk_fit(method,table,market,risk_identity(table,cutoff),d['new_budget']['risk_fit_timeout_seconds'])
                    rec['estimator_budget']=obj.budget
                    if obj.status!='FITTED':raise risk.RiskEstimatorBlocked(obj.status+':'+obj.failure_reason)
                    if any(w['category']=='ConvergenceWarning' for w in obj.fitted_state.get('warnings',[])):raise risk.RiskEstimatorBlocked('FIT_FAILED:UNRESOLVED_FIXED_ITERATION_WARNING')
                    model=mp.with_suffix('.joblib');model.parent.mkdir(parents=True,exist_ok=True);jb.dump(obj,model,compress=3);rec.update(reuse='NEW_DISTINCT_OR_MISSING_EARLY_FOLD',model_path=str(model),model_sha256=prior.sha(model),seconds=time.monotonic()-start);fits+=1
                if obj.method_id!=method or tuple(obj.fitted_dates)!=tuple(line['dates']) or obj.specification['return_horizon_sessions']!=1 or obj.specification['return_unit']!=risk_features.UNIT:raise ValueError('EXACT_RISK_ARTIFACT_IDENTITY_MISMATCH')
                for k,v in risk.specs(method).items():
                    if obj.specification.get(k)!=v:raise ValueError('RISK_SPEC_DRIFT:'+k)
                current=frame.loc[frame.signal_date.dt.year.eq(year)];projected=risk_features.frame_features(obj,current,year,method);projected.to_parquet(out,index=False)
                rec.update(status='FITTED',projection_path=str(out),projection_sha256=prior.sha(out),unknown_rows=int(projected.risk_unknown_fallback.sum()),rows=len(projected));prior.putj(mp,rec);bundles[method]=obj
                if event:prior.finish(run,event,status='TRAINED',model_path=rec['model_path'])
                prior.emit(phase='RISK_PROJECTION_DONE',method=method,year=year,reuse=rec['reuse'])
            except Exception as exc:
                rec.update(status='FAILED',error=type(exc).__name__,failure=str(exc),traceback=traceback.format_exc());prior.putj(mp,rec)
                if event:prior.finish(run,event,status='FAILED',message=str(exc))
                prior.emit(phase='RISK_FAILURE_RETAINED',method=method,year=year,error=str(exc))
    prior.putj(run/'RISK_COMPLETION.json',dict(status='ATTEMPTS_COMPLETE',new_successful_risk_fits=fits,test2026_rows_read=0))
    state(run,'RISK','ATTEMPTS_COMPLETE')

def joined(run,parent,year,methods,cal,coop):
    base=parent_members(parent,year,cal,coop)
    for m in methods:
        p=run/f'predictions/risk_{m}_{year}.parquet'
        if not p.exists():raise ValueError(f'RISK_DEPENDENCY_UNAVAILABLE:{m}:{year}')
        r=pd.read_parquet(p);r=r.sort_values(KEY).reset_index(drop=True);base=base.sort_values(KEY).reset_index(drop=True)
        if not r[KEY+['ticker']].equals(base[KEY+['ticker']]):raise ValueError('RISK_FULL_COMMON_POOL_CHANGED')
        if not r.risk_cutoff.lt(r.signal_date).all() or r.eligibility_upgraded.any():raise ValueError('RISK_CLOCK_OR_ELIGIBILITY')
        cols=[c for c in r if c.startswith(m+'__')];base=base.merge(r[KEY+cols],on=KEY,validate='one_to_one')
    return base

def heads(run):
    rt=prior.runtime(run);cfg,np_,pd_,pq,jb,pred,extra,shared,cal,coop=rt;d=checked(run);parent=Path(cfg['parent_run'])
    for p,h in d['parent_meta_pins'].items():assert prior.sha(p)==h
    for cid in NEW:
        for year in (2023,2024,2025):
            mp=run/f'models/{cid}/{year}.json';dst=run/f'predictions/native_{cid}_{year}.parquet'
            if mp.exists():
                r=prior.readj(mp)
                assert r['design_sha256']==prior.sha(run/'DESIGN_FREEZE.json')
                if r['status']=='TRAINED':
                    assert prior.sha(dst)==r['prediction_sha256']
                    if r.get('model_path'):assert prior.sha(r['model_path'])==r['model_sha256']
                continue
            cutoff=pd.Timestamp(f'{year}-01-01');event=None;state(run,'RISK_SCORE',candidate=cid,year=year)
            try:
                methods=list(CORE) if cid.startswith('risk_bank_') else [cid.removeprefix('risk_').rsplit('_',1)[0].upper()]
                cur=joined(run,parent,year,methods,cal,coop)
                if cid.endswith('_penalty'):
                    suffix='marginal_sigma' if cid.endswith('sigma_penalty') else 'pool_covariance_normalized'
                    values=cur[[m+'__mu' for m in MEMBERS]].mean(axis=1).to_numpy(float)-.1*np.sqrt(6.)*cur[[m+'__'+suffix for m in methods]].mean(axis=1).to_numpy(float)
                    meta=dict(status='TRAINED',physical_fit_count=0,learned_fit_count=0,formula=d['risk_meta']['penalty'])
                else:
                    parts=[joined(run,parent,y,methods,cal,coop) for y in range(2022,year)]
                    history=pd.concat(parts,ignore_index=True);history=history.loc[history.label_end_date.lt(cutoff)&history.target.notna()].copy()
                    h,_=coop._guard(history,cutoff,'CALIBRATED_OOF');h=cal.sample(h)
                    columns=[m+'__mu' for m in MEMBERS]+[m+'__'+z for m in methods for z in ('marginal_sigma','pool_covariance_normalized','unknown_flag')]
                    x=h[columns].to_numpy(float);y=h.target.to_numpy(float);w=cal.date_weights(h.signal_date)
                    if not np.isfinite(x).all() or not np.isfinite(y).all():raise ValueError('META_NONFINITE')
                    event=prior.reserve(run,cid,year,2,1,'RISK_META')
                    from sklearn.preprocessing import StandardScaler
                    from sklearn.linear_model import Ridge
                    from threadpoolctl import threadpool_limits
                    scaler=StandardScaler().fit(x,sample_weight=w);model=Ridge(alpha=100.) if cid.endswith('_ridge') else cal.tree()
                    with threadpool_limits(limits=2):model.fit(scaler.transform(x),y,sample_weight=w)
                    values=model.predict(scaler.transform(cur[columns].to_numpy(float)))
                    artifact=mp.with_suffix('.joblib');artifact.parent.mkdir(parents=True,exist_ok=True);jb.dump({'scaler':scaler,'model':model,'columns':columns},artifact,compress=3)
                    meta=dict(status='TRAINED',model_path=str(artifact),model_sha256=prior.sha(artifact),columns=columns,rows=len(h),max_train_label_end=str(h.label_end_date.max()),source_kind='CALIBRATED_OOF_WITH_PRIOR_RISK_FEATURES',physical_fit_count=1,learned_fit_count=2)
                if not np.isfinite(values).all():raise ValueError('FINITE_FULL_SCORE_REQUIRED')
                part=cur[KEY+['ticker','U_t_fingerprint','target','label_end_date']].copy();part['score']=values;part['candidate_id']=cid;part['source_cutoff']=cutoff;part['source_kind']='PIPELINE_OOF';part.to_parquet(dst,index=False)
                meta.update(design_sha256=prior.sha(run/'DESIGN_FREEZE.json'),prediction_path=str(dst),prediction_sha256=prior.sha(dst));prior.putj(mp,meta)
                if event:prior.finish(run,event,status='TRAINED',prediction_path=str(dst))
                prior.emit(phase='RISK_SCORE_DONE',candidate=cid,year=year)
            except Exception as exc:
                prior.putj(mp,dict(status='FAILED_UNTESTABLE',candidate=cid,year=year,design_sha256=prior.sha(run/'DESIGN_FREEZE.json'),error=str(exc),traceback=traceback.format_exc()))
                if event:prior.finish(run,event,status='FAILED',message=str(exc))
                prior.emit(phase='RISK_META_FAILURE_RETAINED',candidate=cid,year=year,error=str(exc))
    state(run,'RISK_SCORE','ATTEMPTS_COMPLETE')

def assemble(run):
    rt=prior.runtime(run);cfg,np_,pd_,pq,jb,pred,extra,shared,cal,coop=rt;d=checked(run);parent=Path(cfg['parent_run']);old=prior.readj(parent/'SCORE_ASSEMBLY.json')
    complete=old['complete_candidates'].copy();failed=old['failed_or_untestable'].copy()
    for cid in NEW:
        parts=[run/f'predictions/native_{cid}_{y}.parquet' for y in (2023,2024,2025)]
        if not all(p.exists() for p in parts):failed[cid]='MISSING_COMPLETE_THREE_YEAR_RISK_OOF';continue
        p=run/f'predictions/scores_{cid}_pre2026.parquet'
        if not p.exists():prior.rank_panel(pd.concat([pd.read_parquet(z) for z in parts],ignore_index=True),pd).to_parquet(p,index=False)
        complete.append(cid)
    prior.putj(run/'SCORE_ASSEMBLY.json',dict(complete_candidates=complete,failed_or_untestable=failed,common_rows=old['common_rows'],common_dates=old['common_dates'],raw_candidate_id=old['raw_candidate_id'],forecast2026_rows=0,reused_scores=d['score_reuse']))
    prior.putj(run/'EVALUATION_CODE_ACTIVATION.json',dict(sources={str(p):prior.sha(p) for p in [REPO/'scripts/research/a2/evaluation/selector_evidence.py',REPO/'scripts/research/a2/evaluation/selector_account_compare.py',Path(prior.__file__)]},score_assembly_sha256=prior.sha(run/'SCORE_ASSEMBLY.json')))
    state(run,'ASSEMBLY','COMPLETE',complete_candidates=len(complete),failed_candidates=len(failed))

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--phase',choices=['freeze','risk','heads','assemble','all'],required=True);a=p.parse_args();run=a.run.resolve()
    if a.phase=='freeze':freeze(run);return
    if a.phase in ('risk','all'):risk_stages(run)
    if a.phase in ('heads','all'):heads(run)
    if a.phase in ('assemble','all'):assemble(run)
    if a.phase=='all':
        from scripts.research.a2.evaluation.selector_evidence import run as evaluate
        result=evaluate(run);state(run,'SELECTION_EVIDENCE','COMPLETE',selection_status=result['status'],finalists=result['finalists'],exact_resume_point='activate B shared account interface SHA and replay frozen cost scenarios; do not refit completed risk/meta')
if __name__=='__main__':
    try:main()
    except Exception as exc:
        import sys
        if '--run' in sys.argv:
            state(Path(sys.argv[sys.argv.index('--run')+1]).resolve(),'PIPELINE_EXCEPTION','FAILED',error=str(exc),traceback=traceback.format_exc())
        raise