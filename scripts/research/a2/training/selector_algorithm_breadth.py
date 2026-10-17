"""Same-information algorithm breadth: bounded orchestration of existing owners."""
from __future__ import annotations
import argparse, hashlib, json, os, sys, time, traceback
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.training import selector_challenge as prior
from scripts.research.a2.training import selector_algorithm_objectives as objectives
from scripts.research.a2.evaluation.selector_account_compare import sha, pre2026
from scripts.research.a2.evaluation import selector_evidence as evidence
REPO=Path(__file__).resolve().parents[4]
ID='V24_C_SELECTOR_ALGORITHM_BREADTH_R5'
YEARS=(2023,2024,2025)
RAW=evidence.RAW
KEYS=['signal_date','ticker','security_uid','U_t_fingerprint']
BACKEND_MODULES=('numpy','pandas','scipy','sklearn','torch','pyarrow','joblib','xgboost','lightgbm','catboost')
def required_source_paths():
    retained=prior.RETAINED
    return tuple([Path(__file__).resolve(),Path(objectives.__file__),Path(prior.__file__),
        Path(evidence.__file__),REPO/'scripts/research/a2/evaluation/selector_algorithm_breadth_evidence.py',
        REPO/'scripts/research/a2/evaluation/selector_account_compare.py',
        REPO/'scripts/research/a2/evaluation/selector_frozen_history_evidence.py',
        retained/'predictors.py',retained/'runtime_bootstrap.py',retained/'shared.py',
        retained/'calibration_fusion.py',REPO/'scripts/research/a2/training/selector_formulations.py',
        REPO/'scripts/research/a2/training/selector_cooperation.py',
        REPO/'scripts/research/a2/retained/a2_predict_then_optimize_20260928_r1/models_native.py',
        REPO/'scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py',
        REPO/'scripts/common/storage_paths.py',REPO/'scripts/maintenance/audit_repo_size_r1.py'])
def guard_backend(rt,d,metadata=None):
    expected=d['backend_versions']
    actual=rt[5].RUNTIME['modules']
    if set(expected)!=set(BACKEND_MODULES) or any(actual.get(k)!=expected[k] for k in BACKEND_MODULES):
        raise ValueError('FROZEN_BACKEND_VERSION_OR_ORIGIN_CHANGED')
    if metadata is not None:
        b=metadata.get('backend',{});name=b.get('module')
        if name not in expected or any(b.get(k)!=expected[name].get(k) for k in ('version','origin')):
            raise ValueError('FITTED_BACKEND_VERSION_OR_ORIGIN_CHANGED')

def readj(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def putj(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str,allow_nan=False)+'\n',encoding='utf-8')
    os.replace(temporary,path)
def now(): return datetime.now(timezone.utc).isoformat()
def emit(run,**values):
    state={'updated_at':now(),'research_id':ID,'mechanism_research_eligible':True,'strict_PIT_promotion_eligible':False,'test2026_locked':True,**values}
    putj(run/'PIPELINE_STATE.json',state);print(json.dumps(state,default=str),flush=True)

def checked(run):
    run=Path(run).resolve(); paths=resolve(REPO);assert_safe_output_path(run,kind='backtest',paths=paths)
    cfg=readj(run/'run_config.json');d=readj(run/'DESIGN_FREEZE.json');digest=sha(run/'DESIGN_FREEZE.json')
    if digest!=readj(run/'DESIGN_FREEZE_SHA.json')['sha256'] or cfg.get('design_freeze_sha256')!=digest: raise ValueError('DESIGN_HASH_REQUIRED')
    if not(d.get('research_id')==ID and d.get('official_freeze') is True and d.get('formal_freeze_applied') is True and d.get('mechanism_research_eligible') is True and d.get('strict_PIT_promotion_eligible') is False and d.get('test2026_locked') is True and d.get('new2026_estimation_authorized') is False):raise ValueError('FORMAL_MECHANISM_ONLY_FREEZE_REQUIRED')
    if tuple(d['roles'])!=tuple(objectives.role_specs()) or d['role_specs']!=objectives.role_specs():raise ValueError('FROZEN_OBJECTIVE_CATALOGUE_REQUIRED')
    if tuple(d['new_fitting_years'])!=YEARS or d['seed']!=20260928 or d['features']!=d['fixed_features'] or len(d['features'])!=32 or d['target']!='MEAN_ER_3D_5D_10D_20D':raise ValueError('FIXED_TIME_FEATURE_TARGET_SEED_REQUIRED')
    if d['fitting_weights']!='fixed day-balanced sampled keys; each input row weight one, no explicit equal-total-date sample_weight':raise ValueError('FIXED_NATIVE_DIRECT_WEIGHTING_REQUIRED')
    if d['budget']!={'model_year_slots':54,'estimator_fit_calls':54,'scaler_fit_calls':54,'backend_fit_calls':108,'scientific_retries':0,'risk_fit_calls':0,'calibration_fit_calls':0,'configs_per_role':1,'seeds_per_role':1,'workers':1,'threads':2}:raise ValueError('EXACT_FINITE_BUDGET_REQUIRED')
    if cfg.get('research_id')!=ID or cfg.get('research_line')!='C_SELECTOR':raise ValueError('RUN_CONFIG_RESEARCH_IDENTITY_REQUIRED')
    if not set(map(str,required_source_paths())).issubset(d['sources']):raise ValueError('FROZEN_SOURCE_CLOSURE_REQUIRED')
    for path,digest in d['sources'].items():
        if sha(path)!=digest:raise ValueError('FROZEN_SOURCE_CHANGED:'+path)
    if sha(d['source_contract']['path'])!=d['source_contract']['sha256']:raise ValueError('SOURCE_CONTRACT_CHANGED')
    source=readj(d['source_contract']['path'])
    if source.get('mechanism_research_eligible') is not True or source.get('strict_PIT_promotion_eligible') is not False or source.get('source_contract_mode')!='FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY':raise ValueError('SOURCE_AUTHORITY_PREMISE_CHANGED')
    if sha(d['physical_dag']['path'])!=d['physical_dag']['sha256']:raise ValueError('FROZEN_DAG_CHANGED')
    activation=readj(run/'FREEZE_ACTIVATION.json')
    if activation['design_freeze_sha256']!=sha(run/'DESIGN_FREEZE.json') or activation['status']!='PASS':raise ValueError('ACTIVATION_REQUIRED')
    for directory,kind in [(cfg['results_directory'],'results'),(cfg['cache_directory'],'cache')]:assert_safe_output_path(Path(directory),kind=kind,paths=paths)
    return cfg,d

def boundary_labels(full_pool):
    """Train-fold target transformation, before shared target-blind sampling."""
    if full_pool.duplicated(['signal_date','security_uid']).any():raise ValueError('DUPLICATE_FULL_TRAIN_POOL')
    ordered=full_pool.sort_values(['signal_date','target','security_uid'],ascending=[True,False,True],kind='stable')
    rank=ordered.groupby('signal_date',sort=False).cumcount()
    return pd.Series((rank<20).to_numpy(np.int8),index=ordered.index).reindex(full_pool.index).to_numpy(np.int8)

def footer_before(path,fields,cutoff='2026-01-01'):
    pf=pq.ParquetFile(path)
    for field in fields:
        at=pf.schema_arrow.get_field_index(field)
        if at<0:raise ValueError('MISSING_FOOTER_CLOCK:'+field)
        for group in range(pf.num_row_groups):
            stats=pf.metadata.row_group(group).column(at).statistics
            if stats is None or stats.null_count!=0 or not stats.has_min_max or pd.Timestamp(stats.max)>=pd.Timestamp(cutoff):raise ValueError('PHYSICAL_BOUNDARY_NOT_PROVEN:'+field)

def read_inputs(run,rt,d):
    for name,pin in d['inputs'].items():
        if sha(pin['path'])!=pin['sha256']:raise ValueError('INPUT_HASH_CHANGED:'+name)
        footer_before(pin['path'],['signal_date'])
    footer_before(d['inputs']['training']['path'],['signal_date','target_end_date'])
    parent=Path(d['parent_run'])
    if sha(parent/'DESIGN_FREEZE.json')!=d['parent_design_sha256']:raise ValueError('PARENT_DESIGN_CHANGED')
    old=readj(parent/'DESIGN_FREEZE.json')
    if old['inputs']!=d['inputs']:raise ValueError('PARENT_ACTUAL_INPUTS_CHANGED')
    if old['features']!=d['features'] or rt[7].FEATURES!=d['features']:raise ValueError('FIXED_SHARED_FEATURES_CHANGED')
    tr,va=prior.data(parent,rt)
    if tr.signal_date.ge('2026-01-01').any() or va.signal_date.ge('2026-01-01').any():raise ValueError('FIXED_SHARED_TIME_CHANGED')
    return tr,va

def validate_ledger(run,d,ledger):
    if ledger.get('design_freeze_sha256')!=sha(run/'DESIGN_FREEZE.json'):raise ValueError('LEDGER_DESIGN_CHANGED')
    events=ledger['events'];slots=set();entered_count=completed_count=0
    for e in events:
        slot=f"{e['role']}:{e['year']}"
        if e['role'] not in d['roles'] or e['year'] not in YEARS or e['slot_id']!=slot or slot in slots or e['attempt']!=1 or e['reserved_backend_fit_calls']!=2 or e['status'] not in ('RESERVED','TRAINED','FAILED'):raise ValueError('LEDGER_SLOT_IDENTITY_CHANGED')
        slots.add(slot)
        a,c=e['actual_fit_calls_entered'],e['completed_fit_calls']
        if set(a)!={'scaler','estimator'} or set(c)!={'scaler','estimator'} or any(type(a[k]) is not int or type(c[k]) is not int or not 0<=c[k]<=a[k]<=1 for k in a):raise ValueError('LEDGER_TELEMETRY_CHANGED')
        if e['status']=='TRAINED' and (a!={'scaler':1,'estimator':1} or c!=a):raise ValueError('SUCCESS_CALL_TELEMETRY_CHANGED')
        entered_count+=sum(a.values());completed_count+=sum(c.values())
    if len(events)>54 or ledger['charged_backend_ceiling']!=2*len(events) or ledger['charged_backend_ceiling']>108 or ledger['actual_backend_fit_calls_entered']!=entered_count or ledger['backend_fit_calls_completed']!=completed_count or ledger['scientific_retries']!=0:raise ValueError('LEDGER_COUNTER_OR_BUDGET_CHANGED')
    return ledger

def new_ledger(run,d):
    path=run/'FIT_LEDGER.json'
    if path.exists():
        ledger=readj(path)
        return validate_ledger(run,d,ledger)
    ledger={'design_freeze_sha256':sha(run/'DESIGN_FREEZE.json'),'events':[],'charged_backend_ceiling':0,'actual_backend_fit_calls_entered':0,'backend_fit_calls_completed':0,'scientific_retries':0}
    putj(path,ledger);return ledger

def reserve(run,ledger,role,year):
    slot=f'{role}:{year}'
    if any(e['slot_id']==slot for e in ledger['events']):raise ValueError('SLOT_ATTEMPT_ALREADY_RECORDED')
    if len(ledger['events'])>=54 or ledger['charged_backend_ceiling']+2>108:raise ValueError('BUDGET_EXCEEDED')
    event={'slot_id':slot,'role':role,'year':year,'status':'RESERVED','attempt':1,'reserved_backend_fit_calls':2,'actual_fit_calls_entered':{'scaler':0,'estimator':0},'completed_fit_calls':{'scaler':0,'estimator':0},'started_at':now()}
    ledger['events'].append(event);ledger['charged_backend_ceiling']+=2;putj(run/'FIT_LEDGER.json',ledger);return event

def entered(run,ledger,event,kind):
    if event['actual_fit_calls_entered'][kind]!=0:raise ValueError('MULTIPLE_BACKEND_CALLS_NOT_AUTHORIZED')
    event['actual_fit_calls_entered'][kind]=1;ledger['actual_backend_fit_calls_entered']+=1
    putj(run/'FIT_LEDGER.json',ledger)
def completed(run,ledger,event,kind):
    if event['actual_fit_calls_entered'][kind]!=1 or event['completed_fit_calls'][kind]!=0:raise ValueError('BACKEND_COMPLETION_NOT_MATCHED')
    event['completed_fit_calls'][kind]=1;ledger['backend_fit_calls_completed']+=1;putj(run/'FIT_LEDGER.json',ledger)

def qualify_existing_success(run,d,event):
    role,year=event['role'],event['year'];receipt=readj(run/f'models/{role}/{year}.json')
    if event['status']!='TRAINED' or event['actual_fit_calls_entered']!={'scaler':1,'estimator':1} or event['completed_fit_calls']!={'scaler':1,'estimator':1}:raise ValueError('SUCCESS_CALL_TELEMETRY_CHANGED')
    if receipt['status']!='TRAINED' or receipt['design_freeze_sha256']!=sha(run/'DESIGN_FREEZE.json') or receipt['role']!=role or receipt['year']!=year:raise ValueError('SUCCESS_RECEIPT_IDENTITY_CHANGED')
    cutoff=pd.Timestamp(f'{year}-01-01')
    if receipt['objective_spec']!=d['role_specs'][role] or receipt['cutoff']!=str(cutoff.date()) or not pd.Timestamp(receipt['max_train_signal_date'])<cutoff or not pd.Timestamp(receipt['max_train_label_end'])<cutoff or receipt['actual_fit_calls_entered']!=event['actual_fit_calls_entered']:raise ValueError('SUCCESS_RECEIPT_FROZEN_LINEAGE_CHANGED')
    if sha(d['native_reuse_manifest']['path'])!=d['native_reuse_manifest']['sha256']:raise ValueError('REUSE_MANIFEST_CHANGED')
    sample=next(s for s in readj(d['native_reuse_manifest']['path'])['training_samples'] if s['year']==year)
    if receipt['sampled_keys_sha256']!=sample['sha256']:raise ValueError('SUCCESS_SAMPLE_KEYS_CHANGED')
    for key in ('model','prediction'):
        if sha(receipt[key]['path'])!=receipt[key]['sha256']:raise ValueError('SUCCESS_ARTIFACT_CHANGED')
    footer_before(receipt['prediction']['path'],['signal_date','source_cutoff'])
    return receipt

def train(run):
    cfg,d=checked(run); rt=prior.runtime(run); guard_backend(rt,d); jb,pred=rt[4],rt[5]
    from sklearn.preprocessing import StandardScaler
    train_pool,frame=read_inputs(run,rt,d); ledger=new_ledger(run,d)
    if sha(d['native_reuse_manifest']['path'])!=d['native_reuse_manifest']['sha256']:raise ValueError('REUSE_MANIFEST_CHANGED')
    manifest=readj(d['native_reuse_manifest']['path'])
    samples={str(v['year']):v for v in manifest['training_samples']}
    for year in YEARS:
        checked(run);cutoff=pd.Timestamp(f'{year}-01-01')
        full=train_pool.loc[train_pool.signal_date.lt(cutoff)&train_pool.target_end_date.lt(cutoff)].copy()
        full['_boundary']=boundary_labels(full)
        sampled=prior.sampled(full,pd,np)
        expected=samples[str(year)]
        if sha(expected['path'])!=expected['sha256']:raise ValueError('SAMPLE_KEY_HASH_CHANGED')
        footer_before(expected['path'],['signal_date','target_end_date'],cutoff)
        old_keys=pre2026(expected['path'],['signal_date','ticker','security_uid','target_end_date'],('signal_date','target_end_date'))
        keys=sampled[['signal_date','ticker','security_uid','target_end_date']].reset_index(drop=True)
        if not keys.equals(old_keys.reset_index(drop=True)):raise ValueError('EXACT_SAMPLED_KEYS_CHANGED')
        valid=frame.loc[frame.signal_date.dt.year.eq(year)].sort_values(['signal_date','security_uid']).reset_index(drop=True)
        if valid.empty or not sampled.target_end_date.lt(cutoff).all():raise ValueError('MATURE_TRAINING_OR_FULL_PREDICTION_POOL_REQUIRED')
        x=sampled[d['features']].to_numpy(float);vx=valid[d['features']].to_numpy(float)
        y=sampled.target.to_numpy(float);b=sampled._boundary.to_numpy(np.int8)
        for role in d['roles']:
            old_event=next((e for e in ledger['events'] if e['slot_id']==f'{role}:{year}'),None)
            if old_event:
                if old_event['status']=='TRAINED':qualify_existing_success(run,d,old_event);continue
                if old_event['status']=='FAILED':continue
                raise ValueError('UNFINISHED_SCIENTIFIC_SLOT_NO_RETRY')
            checked(run);event=reserve(run,ledger,role,year);start=time.monotonic()
            emit(run,phase='TRAINING',status='RUNNING',role=role,year=year)
            try:
                entered(run,ledger,event,'scaler');scaler=StandardScaler().fit(x);completed(run,ledger,event,'scaler')
                def fit_callback(info):
                    if info.get('operation')!='estimator_fit' or info.get('role')!=role:raise ValueError('FIT_CALLBACK_IDENTITY_CHANGED')
                    entered(run,ledger,event,'estimator')
                fitted=objectives.fit(role,scaler.transform(x),y,sampled.signal_date,b,runtime=pred,on_fit_call=fit_callback)
                completed(run,ledger,event,'estimator')
                guard_backend(rt,d,fitted.metadata)
                values=objectives.predict(fitted,scaler.transform(vx))
                if values.shape!=(len(valid),) or not np.isfinite(values).all():raise ValueError('FULL_U_T_PREDICTION_REQUIRED')
                native=valid[KEYS].copy();native['score']=values;native['candidate_id']=role;native['source_kind']='MODEL_OOF';native['source_cutoff']=cutoff
                model=run/f'models/{role}/{year}.joblib';out=run/f'predictions/native_{role}_{year}.parquet';model.parent.mkdir(parents=True,exist_ok=True);out.parent.mkdir(parents=True,exist_ok=True)
                jb.dump({'scaler':scaler,'objective':fitted},model,compress=3);native.to_parquet(out,index=False)
                receipt={'status':'TRAINED','role':role,'year':year,'design_freeze_sha256':sha(run/'DESIGN_FREEZE.json'),'objective_spec':d['role_specs'][role],'max_train_signal_date':str(sampled.signal_date.max()),'max_train_label_end':str(sampled.target_end_date.max()),'cutoff':str(cutoff.date()),'sampled_keys_sha256':expected['sha256'],'rows_train':len(sampled),'rows_prediction':len(valid),'model':{'path':str(model),'sha256':sha(model)},'prediction':{'path':str(out),'sha256':sha(out)},'metadata':fitted.metadata,'actual_fit_calls_entered':event['actual_fit_calls_entered'],'seconds':time.monotonic()-start}
                putj(model.with_suffix('.json'),receipt);event.update(status='TRAINED',completed_at=now(),receipt_path=str(model.with_suffix('.json')));putj(run/'FIT_LEDGER.json',ledger)
                print(json.dumps({'phase':'MODEL_OOF_DONE','role':role,'year':year,'seconds':receipt['seconds']},default=str),flush=True)
            except Exception as exc:
                failure={'status':'FAILED','role':role,'year':year,'design_freeze_sha256':sha(run/'DESIGN_FREEZE.json'),'error':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc(),'actual_fit_calls_entered':event['actual_fit_calls_entered'],'completed_fit_calls':event['completed_fit_calls'],'reservation_retained':2,'scientific_retry_allowed':False}
                putj(run/f'models/{role}/{year}.json',failure);event.update(status='FAILED',completed_at=now(),error=type(exc).__name__,message=str(exc));putj(run/'FIT_LEDGER.json',ledger)
                print(json.dumps({'phase':'FIT_FAILURE_RETAINED','role':role,'year':year,'error':str(exc)}),flush=True)
    putj(run/'TRAINING_COMPLETE.json',{'status':'FINITE_ATTEMPTS_COMPLETE','attempts':len(ledger['events']),'charged_backend_ceiling':ledger['charged_backend_ceiling'],'actual_backend_fit_calls_entered':ledger['actual_backend_fit_calls_entered'],'backend_fit_calls_completed':ledger['backend_fit_calls_completed'],'scientific_retries':0})
    emit(run,phase='TRAINING',status='FINITE_ATTEMPTS_COMPLETE')

def assemble(run):
    cfg,d=checked(run);ledger=validate_ledger(run,d,readj(run/'FIT_LEDGER.json'))
    if sha(d['score_reuse'][RAW]['path'])!=d['score_reuse'][RAW]['sha256']:raise ValueError('RAW_HASH_CHANGED')
    raw=pre2026(d['score_reuse'][RAW]['path'],KEYS,'signal_date').sort_values(['signal_date','security_uid','ticker']).reset_index(drop=True)
    complete=[];failed={};bindings={RAW:d['score_reuse'][RAW]}
    for role in d['roles']:
        selected=[e for e in ledger['events'] if e['role']==role]
        if len(selected)!=3 or set(e['year'] for e in selected)!=set(YEARS) or any(e['status']!='TRAINED' for e in selected):failed[role]='MISSING_COMPLETE_THREE_YEAR_NATIVE_OOF';continue
        receipts=[qualify_existing_success(run,d,e) for e in sorted(selected,key=lambda e:e['year'])]
        parts=[]
        for rec in receipts:
            part=pre2026(rec['prediction']['path'],KEYS+['score','candidate_id','source_kind','source_cutoff'],('signal_date','source_cutoff'))
            if not part.source_kind.eq('MODEL_OOF').all() or not pd.to_datetime(part.source_cutoff).lt(pd.to_datetime(part.signal_date)).all():raise ValueError('OOF_LINEAGE_REQUIRED')
            parts.append(part)
        panel=pd.concat(parts,ignore_index=True).sort_values(['signal_date','security_uid','ticker']).reset_index(drop=True)
        if not panel[KEYS].equals(raw) or not np.isfinite(panel.score).all():failed[role]='FULL_U_T_KEYS_OR_FINITE_SCORE_FAILED';continue
        panel=prior.rank_panel(panel,pd);out=run/f'predictions/scores_{role}_pre2026.parquet';panel.to_parquet(out,index=False)
        bindings[role]={'path':str(out),'sha256':sha(out)};complete.append(role)
    assembly={'schema':'C_ALGORITHM_BREADTH_SCORE_ASSEMBLY_V1','complete_candidates':complete,'failed_or_untestable':failed,'score_paths':bindings,'common_rows':len(raw),'common_dates':raw.signal_date.nunique(),'forecast2026_rows':0,'design_freeze_sha256':sha(run/'DESIGN_FREEZE.json')}
    putj(run/'SCORE_ASSEMBLY.json',assembly)
    from scripts.research.a2.evaluation import selector_algorithm_breadth_evidence as runner
    sources=[Path(runner.__file__),Path(evidence.__file__),REPO/'scripts/research/a2/evaluation/selector_account_compare.py']
    if any(d['sources'].get(str(p))!=sha(p) for p in sources):raise ValueError('EVIDENCE_SOURCE_FREEZE_CHANGED')
    putj(run/'EVALUATION_CODE_ACTIVATION.json',{'design_freeze_sha256':sha(run/'DESIGN_FREEZE.json'),'score_assembly_sha256':sha(run/'SCORE_ASSEMBLY.json'),'sources':{str(p):sha(p) for p in sources}})
    emit(run,phase='ASSEMBLY',status='COMPLETE',complete_roles=len(complete),failed_roles=len(failed))

def report(run):
    cfg,d=checked(run);results=Path(cfg['results_directory']);ev=readj(results/'SELECTION_EVIDENCE.json');ledger=validate_ledger(run,d,readj(run/'FIT_LEDGER.json'))
    eval_path=REPO/'scripts/research/a2/evaluation/selector_algorithm_breadth_evidence.py'
    if (ev.get('schema')!='C_ALGORITHM_BREADTH_SELECTION_EVIDENCE_V1' or ev.get('status')!='MECHANISM_EVIDENCE_COMPLETE' or ev.get('research_id')!=ID or ev.get('design_freeze_sha256')!=sha(run/'DESIGN_FREEZE.json') or ev.get('score_assembly_sha256')!=sha(run/'SCORE_ASSEMBLY.json') or ev.get('evaluation_source_sha256')!=sha(eval_path) or ev.get('strict_PIT_promotion_eligible') is not False or ev.get('financial_verified') is not False or ev.get('economic_promotion_allowed') is not False or ev.get('finalists')!=[] or ev.get('test2026_locked') is not True or ev.get('new2026_estimation_authorized') is not False or ev.get('test2026_rows_read')!=0 or ev.get('test2026_rows_read_by_this_runner')!=0):raise ValueError('DELIVERY_EVIDENCE_LINEAGE_OR_AUTHORITY_CHANGED')
    status_counts={v:sum(e['status']==v for e in ledger['events']) for v in ('TRAINED','FAILED','RESERVED')}
    header=['# V24 C Algorithm Breadth Study：同信息集学习目标广度研究','',f'研究身份：`{ID}`；完成时间：{now()}。','',f"18个预冻结角色，完整统计资格以评价receipt为准；机制支持角色：{ev.get('research_supported_roles',[])}。生产晋级继续锁定。",'', '## 目标与固定条件','', '检验同一Raw A2的32个冻结结构化特征下，新的Top20边界、pairwise、listwise及原生排序训练目标能否改进选择。底层目标保持MEAN_ER_3D_5D_10D_20D。既有31个direct角色已经尝试，本轮不把历史叙述为仅Ridge/HGB。R4封存为R4_CLOSED_NO_MECHANISM_SUPPORT；未读详细attribution来选择新模型。','', '固定股票池、CUSIP UID、特征、标签成熟、Jan1 chronological OOF、同年度采样keys与每行等权、Top20构造、Raw A2 benchmark、2023/24/25全部共同成熟日期、replacement edge、共享maxT及seed。新角色仅32原特征，不增加R4 risk或coverage、lag、fusion或校准。','', '来源是授权的frozen-history机制研究；historical revision/vintage/available_at尚未证明。mechanism_research_eligible=true，strict_PIT_promotion_eligible=false。2025已暴露、2026锁定；不称独立holdout或真实执行净收益。','', '## 实际训练与复用','',f"槽位状态：{status_counts}；backend reservation={ledger['charged_backend_ceiling']}/108；durable进入fit调用={ledger['actual_backend_fit_calls_entered']}；成功完成fit调用={ledger['backend_fit_calls_completed']}。失败reservation不退款，科学retry=0。",'', '模型54+scaler54上限；模型容量固定、每角色1配置、seed20260928、单worker/2threads。Neural固定10epochs、最终epoch，不架构搜索；native ranker objective/version/transform参数均预冻。旧完整native OOF及固定point references直接复用；旧FAILED保留、不重训。','', '旧direct实际使用固定day-balanced sample与每行等权，不具有显式equal-total-date sample_weight。本轮沿用真实口径。Top20 BCE标签在完整成熟训练pool中先计算再取共同sample；pair construction不看y选partner，ties零loss；listwise无正样本group零loss、保留rows。','', '## 标签层结果（bp）','', '| 新角色 | 2023 | 2024 | 2025 | pooled | simultaneous lower | 机制支持 |','|---|---:|---:|---:|---:|---:|---|']
    candidates=ev.get('candidates',ev.get('new_candidates',[]))
    if isinstance(candidates,dict):candidates=list(candidates.values())
    by_id={c.get('test_id',c.get('candidate_id')):c for c in candidates}
    def bp(v):return '—' if v is None else f'{10000*float(v):+.2f}'
    for role in d['roles']:
        item=by_id.get(role,{})
        yr=item.get('year_edges',{})
        header.append('| '+' | '.join([role,*[bp(yr.get(str(year))) for year in YEARS],bp(item.get('pooled_edge')),bp(item.get('simultaneous_lower_95')),str(item.get('mechanism_supported',False))])+' |')
    header+=['','## 评价与结论边界','', '原752calendar positions及732共同成熟日期（250/252/230）保留；旧R4的87真实numeric series/99 exposure，加18新角色，全部完整时105 numeric/117 exposure。失败/untestable不填零，不删除2023或缩日期。5000共享20session noncircular block/maxT，逐draw和critical不得低于旧R4。旧R2/R4不重新挑finalist。','', '本轮正结果可以支持在同信息条件下某个冻结learner/objective有效；负结果只表示这一有限冻结算法目标族未建立优势，不能证明信息集已到上限。所有指标为Top20 replacement label edge，不是净NAV、滑点或生产升级。','', '## 故障、未完成与后续','', f"失败/untestable：{ev.get('failed_or_untestable',{})}。原失败及新失败如实保留；未重试科学槽位，未扩参数、seed、信息集或风险表示。",'', '未开展2026读取/动态state estimation/推断/评价；未运行新账户、RL或改变risk representation。后续研究需独立问题与冻结；本轮不根据正点估计继续加模型或放宽门槛。','', '## 验证、存储与审计','', '开发验证见SYNTHETIC_TEST_RECEIPT.json和FORMAL_FREEZE_REVIEW.json；新代码复用既有模型架构、sampling、rank binding和selector统计owner。所有模型/prediction/ledger在唯一backtest run，报告在results、临时与可重建cache在external cache，无聊天C盘业务产物。','',f'run：{run}',f'results：{results}',f"DESIGN_SHA：{sha(run/'DESIGN_FREEZE.json')}",f"source_contract：{d['source_contract']}"]
    report_path=results/'FINAL_REPORT.md';report_path.write_text('\n'.join(header)+'\n',encoding='utf-8')
    source_check={p:sha(p)==h for p,h in d['sources'].items()};legacy_check={key:sha(pin['path'])==pin['sha256'] for key,pin in d['evaluation']['legacy'].items() if isinstance(pin,dict) and 'path' in pin and 'sha256' in pin}
    if not all(source_check.values()) or not all(legacy_check.values()) or len(ledger['events'])!=54 or ledger['charged_backend_ceiling']>108 or ledger['actual_backend_fit_calls_entered']>108:raise ValueError('DELIVERY_AUDIT_FAILED')
    putj(results/'EXECUTION_RECEIPT.json',{'slot_counts':status_counts,'charged_backend_ceiling':ledger['charged_backend_ceiling'],'actual_backend_fit_calls_entered':ledger['actual_backend_fit_calls_entered'],'backend_fit_calls_completed':ledger['backend_fit_calls_completed'],'source_pins':source_check,'legacy_pins':legacy_check,'base_reference_refits':0,'calibration_refits':0,'risk_fits':0,'scientific_retries':0})
    from scripts.maintenance.audit_repo_size_r1 import audit as audit_repository
    audit=audit_repository(REPO);putj(results/'STORAGE_AUDIT.json',audit)
    if audit.get('violations') or not audit.get('accounting_complete') or not audit.get('hard_limit_passed'):raise ValueError('ANTI_BLOAT_AUDIT_FAILED')
    putj(run/'MODEL_UPDATE_GATE.json',{'status':'LOCKED','production_promotion_allowed':False,'new_training_or_state_estimation_in_2026':False,'mechanism_research_eligible':True,'strict_PIT_promotion_eligible':False,'test2026_locked':True})
    marker={'status':'FINITE_TRAINING_EVIDENCE_REPORT_COMPLETE','research_id':ID,'completed_at':now(),'report_path':str(report_path),'report_sha256':sha(report_path),'selection_evidence_sha256':sha(results/'SELECTION_EVIDENCE.json'),'successful_roles':sum(c.get('status')=='COMPLETE' for c in candidates),'research_supported_roles':ev.get('research_supported_roles',[]),'finalists':[],'strict_PIT_promotion_eligible':False,'test2026_locked':True,'charged_backend_ceiling':ledger['charged_backend_ceiling'],'actual_backend_fit_calls_entered':ledger['actual_backend_fit_calls_entered'],'backend_fit_calls_completed':ledger['backend_fit_calls_completed'],'source_pins_match':all(source_check.values()),'legacy_pins_match':all(legacy_check.values()),'anti_bloat_violations':audit.get('violations',[])}
    putj(run/'DELIVERY_COMPLETE.json',marker);emit(run,phase='DELIVERED',status='COMPLETE',delivery=marker)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',required=True);parser.add_argument('--phase',choices=('train','assemble','evidence','report','all'),default='all');args=parser.parse_args();root=Path(args.run).resolve()
    checked(root)
    if args.phase in ('train','all'):train(root)
    if args.phase in ('assemble','all'):assemble(root)
    if args.phase in ('evidence','all'):
        from scripts.research.a2.evaluation.selector_algorithm_breadth_evidence import run as evaluate
        evaluate(root)
    if args.phase in ('report','all'):report(root)
if __name__=='__main__':main()