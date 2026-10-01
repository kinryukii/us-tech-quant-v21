"""M45..M49 annual PIT32 representations; diagnostics only, no allocation input.

Reuse the existing sklearn factory and one parent FIT_START/ACK ledger. Training
uses source-qualified feature keys before the annual heldout60 start, without
reading labels or calibration vectors. No selector, covariance or account fit.
"""
from __future__ import annotations
import argparse,hashlib,json,warnings
from dataclasses import dataclass
from pathlib import Path
import joblib,numpy as np,pandas as pd,sklearn
from sklearn.preprocessing import StandardScaler
from sklearn.exceptions import ConvergenceWarning
from threadpoolctl import threadpool_limits
from scripts.research.a2.training import stateful_values as values,selector_formulations as factory,stateful_fusion as fusion
from scripts.research.a2.training.stateful_inputs import InputReader,FEATURES,ALLOWED_SOURCES
from scripts.storage.storage_r2a import assert_write_path,write_json_atomic

SEED=20260928
ROLE='PIT32_UNSUPERVISED_REPRESENTATION_DIAGNOSTIC_ONLY'
YEARS=(2023,2024,2025)
METHODS=('kmeans','gmm','isolation','pca','fa')
IDS=dict(zip(METHODS,range(45,50)))
REFS={'kmeans':'risk_kmeans','gmm':'risk_gmm','isolation':'risk_isolation','pca':'risk_pca','fa':'risk_fa'}
FACTORY_NAMES={'kmeans':'kmeans_ridge','gmm':'gmm_ridge','isolation':'iforest_ridge','pca':'pca_ridge','fa':'fa_ridge'}
FACTORY_SHA='51e6aff8cd235702333455fcddfa05866b54b7c278732d10412342f21317bbf9'
VALUES_SHA='307169fc3bb7a4b944409246f4ede98aa880370b91f07e941a5b6906958fefa8'
CATALOG_SOURCE=values.REPO/'scripts/research/a2/retained/a2_predict_then_optimize_20260928_r1/risk_models.py'
CATALOG_SOURCE_SHA='8a64073ad62b4891064834c771d56be41bb14fa6dc78c3f5308cb17ca008d06b'
PARAMETERS={
 'kmeans':dict(base_ref='risk_base',n_clusters=3,n_init=10,max_iter=300,random_state=SEED),
 'gmm':dict(base_ref='risk_base',n_components=3,covariance_type='diag',n_init=1,max_iter=100,reg_covar=1e-6,random_state=SEED),
 'isolation':dict(base_ref='risk_base',n_estimators=100,max_samples=256,contamination='auto',random_state=SEED),
 'pca':dict(base_ref='risk_base',n_components=5,solver='full'),
 'fa':dict(base_ref='risk_base',n_components=5,max_iter=100,tol=.001,svd_method='lapack',random_state=SEED)}
_YEAR_INPUTS={}


def specifications(config):
 out={};catalog=config['research_design']['fixed_configuration_catalog']
 for method in METHODS:
  entry=catalog[REFS[method]];parameters=entry['parameters']
  if parameters!=PARAMETERS[method] or entry.get('seed')!=SEED:raise ValueError('AUX_FIXED_CATALOG_PARAMETERS_CHANGED:'+method)
  obj=factory._auxiliary(FACTORY_NAMES[method]);original=obj.get_params(deep=False)
  p={k:v for k,v in parameters.items() if k!='base_ref'}
  if 'solver' in p:p['svd_solver']=p.pop('solver')
  obj.set_params(**p);actual=obj.get_params(deep=False)
  out[method]=dict(method_id=IDS[method],catalog_ref=REFS[method],catalog_parameters=parameters,
   estimator_class=type(obj).__name__,native_factory=FACTORY_NAMES[method],native_parameters_before_binding=original,
   actual_parameters=actual,binding_changes={k:{'factory':original.get(k),'catalog':v} for k,v in actual.items() if original.get(k)!=v},
   binding_correction='CATALOG_SOURCE_LACKED_FACTORY; REUSE_EXISTING_FACTORY_WITH_EXACT_CATALOG_PARAMS',
   role=ROLE,feature_order=list(FEATURES),input_coordinate='FROZEN_ACCEPTED_PIT32',
   missing='train-only StandardScaler; standardized missing becomes center0; no separate imputer fit',
   native_internal_sampling='IsolationForest max_samples=256 is fixed algorithm semantics; caller passes every qualified key',
   labels_used=False,calibration_fit=False,risk_covariance_equivalence_claimed=False,account_input=False,raw_selector_changed=False)
 return out


def _serial_finished(run,events,config=None):
 if config is None:config=json.loads((run/'run_config.json').read_text(encoding='utf-8-sig'))
 for stage,count in (('value',93),('fusion',39)):
  p=json.loads((run/f'logs/{stage}_batch_status.json').read_text(encoding='utf-8-sig'))
  slots=p.get('slots',[]);schedule=config.get(stage+'_training',{}).get('ordered_schedule',[])
  if stage=='value':
   fusion.validate_value_batch_complete(config,p)
   identity=lambda item:(item.get('model_id'),item.get('year'))
  else:
   identity=lambda item:(fusion.method_name(item.get('model_id')),item.get('year'))
  actual=[identity(item) for item in slots];expected=[identity(item) for item in schedule]
  if p.get('status')!='ATTEMPTS_FINISHED' or p.get('expected_slots')!=count or len(slots)!=count or len(set(actual))!=count or actual!=expected or any(item.get('status') not in ('TRAINED','EXACT_REUSED','FAILED','ERROR','NOT_ATTEMPTED_COMMON_BLOCK') for item in slots):raise ValueError('AUX_REQUIRES_EXACT_ORDERED_VALUE_AND_FUSION_COMPLETE_SERIAL')
 started={(e.get('model_id'),e.get('year')) for e in events if e.get('event')=='MODEL_YEAR_ATTEMPT_STARTED'}
 finished={(e.get('model_id'),e.get('year')) for e in events if e.get('event') in ('MODEL_YEAR_COMPLETE','MODEL_YEAR_FAILED')}
 if started-finished:raise ValueError('AUX_OUTSTANDING_MODEL_YEAR_NO_SHARED_LOG_RACE')


def _auth_unchanged(run,auth):
 current=json.loads((run/'run_config.json').read_text(encoding='utf-8-sig')).get('aux_training',{})
 if current!=auth:raise ValueError('AUX_AUTH_CHANGED_DURING_FIT')


def frozen_contract(run_dir,method,year):
 run=Path(run_dir).resolve();assert_write_path(run/'models/aux','backtest')
 cfg=json.loads((run/'run_config.json').read_text(encoding='utf-8-sig'));auth=cfg.get('aux_training',{})
 if cfg.get('strategy_version')!='V24' or cfg.get('training_cutoff_exclusive')!='2026-01-01' or auth.get('status')!='FROZEN' or method not in METHODS or year not in YEARS or method not in auth.get('methods',[]) or year not in auth.get('years',[]):raise ValueError('AUX_FROZEN_METHOD_YEAR_REQUIRED')
 pins=dict(module_sha256=values.sha(__file__),factory_source_sha256=values.sha(factory.__file__),catalog_source_sha256=values.sha(CATALOG_SOURCE),fusion_module_sha256=values.sha(fusion.__file__),values_module_sha256=values.sha(values.__file__),input_reader_sha256=values.sha(values.READER_SOURCE),input_manifest_sha256=values.sha(run/'input_manifest.json'))
 if pins['factory_source_sha256']!=FACTORY_SHA or pins['catalog_source_sha256']!=CATALOG_SOURCE_SHA or pins['values_module_sha256']!=VALUES_SHA or any(auth.get(k)!=v for k,v in pins.items()):raise ValueError('AUX_FROZEN_SOURCE_CLOSURE_CHANGED')
 expected=dict(seed=SEED,fit_timeout_seconds=1800,budget_bucket='risk_primary',max_new_bucket_fit_units=72,max_fit_units=882,max_model_year_attempts=201,labels_used=False,account_input=False,binding_correction_before_aux_fit=True)
 if any(auth.get(k)!=v for k,v in expected.items()) or cfg.get('prior_cumulative_fit_units')!=18:raise ValueError('AUX_DIAGNOSTIC_ROLE_OR_FINITE_BUDGET_CHANGED')
 specs=specifications(cfg)
 if auth.get('specifications_sha256')!=values.digest(specs):raise ValueError('AUX_FIXED_FACTORY_BINDING_NOT_FROZEN')
 _serial_finished(run,values._events(run/'FIT_LOG.jsonl'),cfg)
 return run,cfg,auth,pins,specs[method]


def training_inputs(reader,year):
 fold=reader.annual_fold(year);flags=reader.train_flags
 legal=flags.feature_available&flags.feature_source.isin(ALLOWED_SOURCES)&flags.signal_date.lt(fold['calibration_start'])
 expected=flags.loc[legal,['signal_date','ticker']].sort_values(['signal_date','ticker']).reset_index(drop=True)
 if expected.empty:raise ValueError('AUX_NO_PRIOR_FEATURE_QUALIFIED_KEYS')
 columns=['signal_date','ticker',*FEATURES]
 f=reader._vectors('value_training_panel',columns,[('feature_available','==',True),('feature_source','in',list(ALLOWED_SOURCES)),('signal_date','<',fold['calibration_start'])]).sort_values(['signal_date','ticker']).reset_index(drop=True)
 if not f[['signal_date','ticker']].equals(expected):raise ValueError('AUX_LEGAL_VECTOR_KEYS_NOT_COMPLETE')
 if not f.signal_date.lt(fold['calibration_start']).all() or np.isinf(f[list(FEATURES)].to_numpy(float)).any():raise ValueError('AUX_FEATURE_VALUES_OR_INFORMATION_CLOCK')
 lineage=dict(guarded_rows=len(f),training_signal_max=f.signal_date.max().isoformat(),training_exclusive=fold['calibration_start'].isoformat(),heldout_calibration_start=fold['calibration_start'].isoformat(),annual_cutoff_exclusive=fold['cutoff_exclusive'].isoformat(),calendar_sha256=fold['calendar_sha256'],keys_sha256=hashlib.sha256(pd.util.hash_pandas_object(f[['signal_date','ticker']],index=False).to_numpy(np.uint64).tobytes()).hexdigest(),feature_frame_sha256=hashlib.sha256(pd.util.hash_pandas_object(f,index=False).to_numpy(np.uint64).tobytes()).hexdigest(),source_features=list(FEATURES),labels_used=False,label_missing_drops=0,calibration_numeric_read=False,all_qualified_keys_used=True)
 return f,lineage


@dataclass
class AuxModel:
 method:str
 scaler:object
 estimator:object


def embedding(model,x):
 z=values.transform(model.scaler,np.asarray(x,float));est=model.estimator
 if model.method=='kmeans':
  out=est.transform(z);columns=[f'cluster_distance_{i}' for i in range(out.shape[1])]
 elif model.method=='gmm':
  out=est.predict_proba(z);columns=[f'component_probability_{i}' for i in range(out.shape[1])]
 elif model.method=='isolation':out=est.score_samples(z)[:,None];columns=['native_anomaly_score']
 else:
  out=est.transform(z);columns=[f'{model.method}_component_{i+1}' for i in range(out.shape[1])]
 if not np.isfinite(out).all():raise ValueError('NONFINITE_AUX_EMBEDDING')
 return out,columns


def fit_arrays(method,x,spec,on_fit_started):
 x=np.asarray(x,float)
 if tuple(spec['feature_order'])!=FEATURES or x.ndim!=2 or x.shape[1]!=32 or len(x)<5 or np.isinf(x).any():raise ValueError('AUX_ALL_KEYS_ORDERED32_INPUT_REQUIRED')
 estimator=factory._auxiliary(FACTORY_NAMES[method]);estimator.set_params(**spec['actual_parameters']);scaler=StandardScaler()
 with threadpool_limits(limits=2),warnings.catch_warnings(record=True) as caught:
  warnings.simplefilter('always');on_fit_started('FEATURE_SCALER');scaler.fit(x)
  z=values.transform(scaler,x);on_fit_started('UNSUPERVISED_'+type(estimator).__name__);estimator.fit(z)
 messages=[dict(category=w.category.__name__,message=str(w.message)) for w in caught]
 if any(issubclass(w.category,ConvergenceWarning) for w in caught):raise RuntimeError('UNRESOLVED_AUX_CONVERGENCE_NO_RETRY:'+json.dumps(messages))
 if method=='gmm' and not estimator.converged_:raise RuntimeError('GMM_DID_NOT_CONVERGE_NO_RETRY')
 return AuxModel(method,scaler,estimator),dict(actual_fit_count=2,actual_fit_components=['FEATURE_SCALER','UNSUPERVISED_'+type(estimator).__name__],warnings=messages,guarded_rows=len(x),missing_cells=int(np.isnan(x).sum()),labels_used=False,calibration_fit=False,selection_or_allocation=False,sklearn_version=sklearn.__version__,representation_role=ROLE)


def aux_worker(pipe,operation,model_id,x,y,dates,quantile,dependencies,features,observed):
 def started(component):
  pipe.send(('FIT_START','AUX::'+component))
  if pipe.recv() is not True:raise RuntimeError('PARENT_REJECTED_AUX_FIT_BUDGET')
 try:
  if values.sha(__file__)!=y['worker_source_sha256'] or values.sha(factory.__file__)!=FACTORY_SHA or values.sha(values.__file__)!=VALUES_SHA or tuple(features)!=FEATURES:raise ValueError('AUX_WORKER_SOURCE_CHANGED')
  model,metadata=fit_arrays(model_id.removeprefix('AUX::'),x,y['specification'],started)
  pipe.send(('RESULT',model,metadata))
 except BaseException as exc:pipe.send(('ERROR',type(exc).__name__,str(exc)))
 finally:pipe.close()


def fit_annual(method,year,run_dir,reader=None):
 run,cfg,auth,pins,spec=frozen_contract(run_dir,method,year)
 if reader is None:reader=InputReader(run)
 elif type(reader) is not InputReader or reader.run!=run:raise ValueError('CANONICAL_AUX_READER_REQUIRED')
 base=dict(method=method,method_id=IDS[method],year=year,role=ROLE,source_pins=pins,specification=spec,seed=SEED,fold=f'ANNUAL_{year}',labels_used=False,calibration_fit=False,target_used=False)
 identity=values.digest(base);folder=run/'models/aux'/method/str(year);rp=folder/'fit_receipt.json';mp=folder/'model.joblib';log=run/'FIT_LOG.jsonl'
 if rp.exists():
  old=json.loads(rp.read_text(encoding='utf-8-sig'))
  if old.get('status')!='FITTED' or old.get('base_tuple_sha256')!=identity or values.sha(mp)!=old.get('model_sha256'):raise RuntimeError('EXISTING_AUX_SLOT_PRESERVED_NO_RETRY')
  return joblib.load(mp),dict(old,status='EXACT_REUSED',fit_units=0,original_fit_units=old['fit_units'])
 events=values._events(log);attempts=[e for e in events if e.get('event')=='MODEL_YEAR_ATTEMPT_STARTED']
 if any(e.get('model_id')=='AUX::'+method and e.get('year')==year for e in attempts) or len(attempts)>=201:raise RuntimeError('AUX_SLOT_OR_GLOBAL_ATTEMPT_BUDGET')
 values._append(log,dict(event='MODEL_YEAR_ATTEMPT_STARTED',model_id='AUX::'+method,year=year,role=ROLE,budget_bucket='risk_primary',reuse_tuple_sha256=identity))
 folder.mkdir(parents=True,exist_ok=True);receipt=dict(status='RUNNING',method=method,method_id=IDS[method],year=year,role=ROLE,source_pins=pins,base_tuple_sha256=identity,reuse_tuple=base,reuse_tuple_sha256=identity,receipt_path=str(rp),model_path=str(mp),fit_units=0,labels_used=False,account_input=False,scientific_feature_pit_qualified=False,transport_legacy_fit_log_role=values.ROLE)
 write_json_atomic(rp,receipt)
 try:
  key=(str(run),year,pins['input_manifest_sha256'])
  if key not in _YEAR_INPUTS:_YEAR_INPUTS[key]=training_inputs(reader,year)
  frame,lineage=_YEAR_INPUTS[key];reuse=dict(base,input_lineage=lineage);identity=values.digest(reuse);receipt.update(reuse_tuple=reuse,reuse_tuple_sha256=identity)
  model=values._fit_job('auxiliary','AUX::'+method,frame[list(FEATURES)].to_numpy(float),dict(worker_source_sha256=pins['module_sha256'],specification=spec),frame.signal_date.to_numpy(),None,[],list(FEATURES),None,log=log,auth=auth,prior=18,year=year,tuple_sha=identity,receipt=receipt,worker_target=aux_worker)
  meta=receipt['physical_fit_metadata'][-1]['metadata']
  if receipt['fit_units']!=meta['actual_fit_count'] or receipt['fit_units']!=2:raise RuntimeError('AUX_CHILD_ACK_COUNT_MISMATCH')
  # Recheck source pins only: this slot's own outstanding event is expected here.
  current={k:values.sha(p) for k,p in dict(module_sha256=__file__,factory_source_sha256=factory.__file__,catalog_source_sha256=CATALOG_SOURCE,fusion_module_sha256=fusion.__file__,values_module_sha256=values.__file__,input_reader_sha256=values.READER_SOURCE,input_manifest_sha256=run/'input_manifest.json').items()}
  if current!=pins:raise ValueError('AUX_SOURCE_CHANGED_DURING_FIT')
  _auth_unchanged(run,auth)
  joblib.dump(model,mp);receipt.update(status='FITTED',model_sha256=values.sha(mp),scientific_feature_pit_qualified=True,scientific_feature_role=ROLE,guarded_rows=len(frame),heldoutboundary=lineage['heldout_calibration_start'])
  write_json_atomic(rp,receipt);values._append(log,dict(event='MODEL_YEAR_COMPLETE',model_id='AUX::'+method,year=year,role=ROLE,status='FITTED',fit_units=receipt['fit_units'],reuse_tuple_sha256=identity))
  return model,receipt
 except Exception as exc:
  receipt.update(status='FAILED',failure=dict(type=type(exc).__name__,message=str(exc)));write_json_atomic(rp,receipt)
  values._append(log,dict(event='MODEL_YEAR_FAILED',model_id='AUX::'+method,year=year,role=ROLE,fit_units=receipt['fit_units'],failure=receipt['failure']));raise


def publish_diagnostics(model,receipt,reader):
 year=receipt['year'];frame=reader.read_inference(year)
 folder=reader.run/'diagnostics/aux'/model.method;path=folder/f'{year}.parquet';rp=path.with_suffix('.receipt.json')
 assert_write_path(path,'backtest')
 if path.exists():
  old=json.loads(rp.read_text(encoding='utf-8-sig'))
  if old.get('sha256')!=values.sha(path) or old.get('reuse_tuple_sha256')!=receipt['reuse_tuple_sha256']:raise RuntimeError('EXISTING_AUX_DIAGNOSTICS_PRESERVED')
  return old
 # Keep all original keys; unavailable features never enter the transformer.
 mask=frame.feature_available&frame.feature_source.isin(ALLOWED_SOURCES)
 columns={'kmeans':[f'cluster_distance_{i}' for i in range(3)],'gmm':[f'component_probability_{i}' for i in range(3)],'isolation':['native_anomaly_score'],'pca':[f'pca_component_{i+1}' for i in range(5)],'fa':[f'fa_component_{i+1}' for i in range(5)]}[model.method]
 output=frame[['signal_date','ticker']].copy()
 for c in columns:output[c]=np.nan
 if mask.any():
  numeric,names=embedding(model,frame.loc[mask,list(FEATURES)].to_numpy(float))
  if names!=columns:raise ValueError('AUX_OUTPUT_SCHEMA_CHANGED')
  output.loc[mask,columns]=numeric
 output['diagnostic_qualified']=mask;output['role']=ROLE;output['model_sha256']=receipt['model_sha256'];output['model_reuse_tuple_sha256']=receipt['reuse_tuple_sha256']
 folder.mkdir(parents=True,exist_ok=True);output.to_parquet(path,index=False)
 pub=dict(status='PUBLISHED_DIAGNOSTIC_ONLY',path=str(path),sha256=values.sha(path),year=year,method_id=IDS[model.method],rows=len(output),qualified_rows=int(mask.sum()),unavailable_rows=int((~mask).sum()),role=ROLE,model_sha256=receipt['model_sha256'],reuse_tuple_sha256=receipt['reuse_tuple_sha256'],producer_source_sha256=values.sha(__file__),labels_used=False,account_input=False,raw_selector_changed=False,risk_covariance_equivalence_claimed=False,test_2026_rows_read=0)
 write_json_atomic(rp,pub);return pub


def run_batch(run_dir):
 run=Path(run_dir).resolve();cfg=json.loads((run/'run_config.json').read_text(encoding='utf-8-sig'));auth=cfg.get('aux_training',{})
 expected=[dict(method=method,year=year) for method in METHODS for year in YEARS]
 if auth.get('ordered_schedule')!=expected:raise ValueError('AUX_EXACT15_SLOT_SCHEDULE_REQUIRED')
 # Gate before the first canonical reader is constructed.
 frozen_contract(run,METHODS[0],YEARS[0]);reader=InputReader(run);statuses=[]
 for slot in expected:
  method,year=slot['method'],slot['year']
  try:
   model,receipt=fit_annual(method,year,run,reader);pub=publish_diagnostics(model,receipt,reader)
   status=dict(method_id=IDS[method],method=method,year=year,status=receipt['status'],fit_units=receipt['fit_units'],prediction_role=ROLE,diagnostic_receipt=pub['path'].replace('.parquet','.receipt.json'))
  except Exception as exc:status=dict(method_id=IDS[method],method=method,year=year,status='FAILED',failure=dict(type=type(exc).__name__,message=str(exc)))
  statuses.append(status);write_json_atomic(run/'logs/aux_batch_status.json',dict(status='ATTEMPTS_FINISHED' if len(statuses)==15 else 'RUNNING',slots=statuses,expected_slots=15,labels_used=False,account_input=False,test_2026_rows_read=0));print(json.dumps(status,sort_keys=True),flush=True)
 return statuses


def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--batch',action='store_true');args=p.parse_args(argv)
 if not args.batch:p.error('only the fixed fifteen diagnostic slots are supported')
 return 0 if all(s['status'] in ('FITTED','EXACT_REUSED') for s in run_batch(args.run_dir)) else 2
if __name__=='__main__':raise SystemExit(main())
