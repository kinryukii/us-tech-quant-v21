"""Synthetic AUX source gates and native algorithms; no actual reader or fit job."""
import json
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import stateful_aux as a


def config():
 return {'research_design':{'fixed_configuration_catalog':{a.REFS[m]:dict(parameters=a.PARAMETERS[m],seed=a.SEED) for m in a.METHODS}}}


@pytest.mark.parametrize('method',a.METHODS)
def test_native_factory_fixed_parameters_two_callback_components_and_embedding(method):
 specs=a.specifications(config());rng=np.random.default_rng(12)
 latent=rng.normal(size=(320,5));x=latent@rng.normal(size=(5,32))+.25*rng.normal(size=(320,32));x[0,0]=np.nan
 starts=[];model,meta=a.fit_arrays(method,x,specs[method],starts.append)
 assert starts==meta['actual_fit_components'] and meta['actual_fit_count']==2
 assert starts[0]=='FEATURE_SCALER' and meta['guarded_rows']==320
 assert not meta['labels_used'] and not meta['calibration_fit'] and not meta['selection_or_allocation']
 out,columns=a.embedding(model,x[:8])
 assert out.shape==(8,{'kmeans':3,'gmm':3,'isolation':1,'pca':5,'fa':5}[method]) and np.isfinite(out).all()
 if method=='gmm':assert np.allclose(out.sum(axis=1),1.)
 for key,value in specs[method]['actual_parameters'].items():assert model.estimator.get_params(deep=False)[key]==value
 assert 'y_open5' not in specs[method]['feature_order']


def fake_reader(missing=False):
 dates=pd.to_datetime(['2022-09-01','2022-09-02','2022-10-06','2023-01-03'])
 flags=pd.DataFrame({'signal_date':dates,'ticker':['A','B','C','D'],'feature_available':[True,True,True,True],'feature_source':[a.ALLOWED_SOURCES[0]]*4,'label_available':[True,False,True,True]})
 columns=[];filters=[]
 def vectors(source,cols,predicate):
  assert source=='value_training_panel';columns.extend(cols);filters.extend(predicate)
  assert 'y_open5' not in cols and 'label_mature_date' not in cols
  assert not any(p[0] in ('label_available','label_mature_date','account_event_unhandled') for p in predicate)
  out=flags.iloc[:(1 if missing else 2)][['signal_date','ticker']].copy()
  for c in a.FEATURES:out[c]=1.
  return out
 fold={'calibration_start':pd.Timestamp('2022-10-06'),'cutoff_exclusive':pd.Timestamp('2023-01-01'),'calendar_sha256':'SYNTHETIC'}
 return SimpleNamespace(train_flags=flags,annual_fold=lambda y:fold,_vectors=vectors),columns,filters


def test_feature_only_projection_keeps_label_missing_key_without_cal_numeric():
 reader,columns,filters=fake_reader();frame,lineage=a.training_inputs(reader,2023)
 assert frame.ticker.tolist()==['A','B'] and len(frame)==2
 assert set(columns)=={'signal_date','ticker',*a.FEATURES}
 assert ('signal_date','<',pd.Timestamp('2022-10-06')) in filters
 assert not lineage['labels_used'] and not lineage['calibration_numeric_read'] and lineage['label_missing_drops']==0
 assert lineage['training_signal_max']<lineage['heldout_calibration_start']


def test_missing_qualified_vector_key_stops_before_fit():
 reader,_,_=fake_reader(missing=True)
 with pytest.raises(ValueError,match='VECTOR_KEYS_NOT_COMPLETE'):a.training_inputs(reader,2023)


def test_pending_gate_stops_before_source_or_reader(tmp_path,monkeypatch):
 (tmp_path/'run_config.json').write_text(json.dumps(dict(strategy_version='V24',training_cutoff_exclusive='2026-01-01',aux_training={'status':'ROOT_PENDING'})))
 monkeypatch.setattr(a,'assert_write_path',lambda *x:None);reads=[]
 monkeypatch.setattr(a.values,'sha',lambda *x:reads.append(True))
 with pytest.raises(ValueError,match='FROZEN_METHOD_YEAR_REQUIRED'):a.frozen_contract(tmp_path,'pca',2023)
 assert reads==[]


def write_stages(tmp_path):
 (tmp_path/'logs').mkdir();cfg={}
 for stage,count in [('value',93),('fusion',39)]:
  if stage=='value':
   schedule=[dict(model_id=f'SYNTHETIC_{i}',year=2023) for i in range(count)]
   slots=[dict(item,status='FAILED') for item in schedule]
  else:
   schedule=[dict(model_id=f'M{mid}',year=year) for mid in a.fusion.METHODS for year in a.YEARS]
   slots=[dict(model_id=a.fusion.method_name(item['model_id']),year=item['year'],status='ERROR') for item in schedule]
  cfg[stage+'_training']={'ordered_schedule':schedule}
  (tmp_path/f'logs/{stage}_batch_status.json').write_text(json.dumps(dict(status='ATTEMPTS_FINISHED',expected_slots=count,slots=slots)))
 (tmp_path/'run_config.json').write_text(json.dumps(cfg))


def test_serial_failed_slots_finished_but_outstanding_fit_blocks(tmp_path):
 write_stages(tmp_path);a._serial_finished(tmp_path,[])
 events=[dict(event='MODEL_YEAR_ATTEMPT_STARTED',model_id='SYNTHETIC_BUSY',year=2024)]
 with pytest.raises(ValueError,match='OUTSTANDING_MODEL_YEAR'):a._serial_finished(tmp_path,events)
 events.append(dict(event='MODEL_YEAR_FAILED',model_id='SYNTHETIC_BUSY',year=2024));a._serial_finished(tmp_path,events)


def test_worker_budget_rejection_precedes_scaler_fit(monkeypatch):
 class Pipe:
  def __init__(self):self.messages=[];self.closed=False
  def send(self,item):self.messages.append(item)
  def recv(self):return False
  def close(self):self.closed=True
 pipe=Pipe();monkeypatch.setattr(a.values,'sha',lambda p:'WORKER' if str(p)==a.__file__ else a.FACTORY_SHA if str(p)==a.factory.__file__ else a.VALUES_SHA)
 calls=[];monkeypatch.setattr(a.StandardScaler,'fit',lambda *x,**k:calls.append(True))
 a.aux_worker(pipe,'auxiliary','AUX::pca',np.zeros((8,32)),dict(worker_source_sha256='WORKER',specification=a.specifications(config())['pca']),None,None,[],list(a.FEATURES),None)
 assert pipe.closed and calls==[] and pipe.messages[0]==('FIT_START','AUX::FEATURE_SCALER')
 assert pipe.messages[-1][0]=='ERROR' and 'PARENT_REJECTED' in pipe.messages[-1][-1]


@pytest.mark.parametrize('stage',['value','fusion'])
def test_same_count_unique_progress_with_wrong_order_is_rejected(tmp_path,stage):
 write_stages(tmp_path);p=tmp_path/f'logs/{stage}_batch_status.json'
 progress=json.loads(p.read_text());progress['slots'][0],progress['slots'][1]=progress['slots'][1],progress['slots'][0]
 p.write_text(json.dumps(progress))
 with pytest.raises(ValueError,match='EXACT_ORDERED'):a._serial_finished(tmp_path,[])


def test_postfit_authority_change_rejected_but_other_run_metadata_can_change(tmp_path):
 auth=dict(status='FROZEN',account_input=False,labels_used=False)
 p=tmp_path/'run_config.json';p.write_text(json.dumps(dict(aux_training=auth,other_phase='OLD')))
 a._auth_unchanged(tmp_path,auth)
 p.write_text(json.dumps(dict(aux_training=auth,other_phase='UPDATED')));a._auth_unchanged(tmp_path,auth)
 p.write_text(json.dumps(dict(aux_training=dict(auth,labels_used=True))))
 with pytest.raises(ValueError,match='AUTH_CHANGED'):a._auth_unchanged(tmp_path,auth)
