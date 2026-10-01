"""Synthetic arrays and source-only hooks; no real OOF/labels/markets read."""
import pickle
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import Ridge,ElasticNet
from sklearn.preprocessing import StandardScaler
from scripts.research.a2.training import stateful_fusion as f


def test_fixed_representatives_no_fit_and_correct_M44_anchor():
    x=np.array([[1.,2.,6.],[-3.,1.,2.]])
    assert np.allclose(f.fixed_prediction('M032',x),x.mean(axis=1))
    assert np.allclose(f.fixed_prediction('M033',x),np.median(x,axis=1))
    assert np.allclose(f.fixed_prediction('M034',x),x@np.array([.5,.25,.25]))
    starts=[]
    model=f._fit_arrays('M032',x,np.array([1.,2.]),None,None,starts.append)
    assert starts==[] and np.allclose(model.predict(x,None),x.mean(axis=1))
    assert f.packet_for('M044')==('ridge','lgb','hgb')


def test_nnls_one_started_and_nonnegative_normalized_no_alias_fit():
    x=np.array([[1.,0.,0.],[0.,1.,0.],[0.,0.,1.],[1.,1.,1.]])
    starts=[];model=f._fit_arrays('M035',x,x@np.array([.5,.3,.2]),None,None,starts.append)
    assert starts==['FUSION_NNLS']
    assert (model.weights>=0).all() and np.isclose(model.weights.sum(),1.)
    assert np.allclose(model.predict(x,None),x@np.array([.5,.3,.2]))
    with pytest.raises(ValueError,match='NNLS_ZERO'):
        f._fit_arrays('M035',x,-np.ones(4),None,None,lambda _:None)


def test_maturity_filter_precedes_numeric_target_checks():
    rows=pd.DataFrame({'signal_date':pd.to_datetime(['2022-06-01','2022-12-30','2023-01-03']),
        'ticker':['a','a','a'],'label_mature_date':pd.to_datetime(['2022-06-09','2023-01-09','2023-01-11']),
        'feature_available':[True]*3,'label_available':[True]*3,'account_event_unhandled':[False]*3,
        'feature_source':[f.ALLOWED_SOURCES[0]]*3,'label_coordinate':[f.LABEL]*3,
        'y_open5':[.01,np.inf,np.inf]})
    legal=f.meta_eligible(rows,'2023-01-01')
    assert len(legal)==1 and np.isfinite(legal.y_open5).all()


def test_packet_keeps_unavailable_inference_key_and_missing_train_rejected():
    base=pd.DataFrame({'signal_date':pd.to_datetime(['2023-01-03']*2),'ticker':['a','b']})
    experts={m:pd.DataFrame({'signal_date':pd.to_datetime(['2023-01-03']),
        'ticker':['a'],'expert_'+m:[.01]}) for m in f.packet_for('M032')}
    joined,x=f.join_packet(base,experts,f.packet_for('M032'))
    assert joined.ticker.tolist()==['a','b'] and np.isfinite(x[0]).all() and np.isnan(x[1]).all()
    with pytest.raises(ValueError,match='INCOMPLETE_REQUIRED'):
        f.join_packet(base,experts,f.packet_for('M032'),True)


def test_state_comes_from_full_inference_pool_before_label_subset(monkeypatch):
    def state_features(frame,x):
        return frame.groupby('signal_date')[['ret_20d','realized_vol_20d','price_vs_ma20','dummy']].transform('mean').to_numpy()
    monkeypatch.setattr(f,'_native',lambda _:SimpleNamespace(state_features=state_features))
    full=pd.DataFrame({'signal_date':pd.to_datetime(['2022-06-01']*2),'ticker':['a','b'],
        'feature_available':[True]*2,'ret_20d':[0.,2.],'realized_vol_20d':[1.,3.],
        'price_vs_ma20':[2.,4.],'dummy':[3.,5.]})
    surface=f.state_surface(full,np.ones((2,3)))
    label_subset=full.iloc[[0]].reset_index(drop=True)
    state=f.join_state(label_subset,surface)
    assert np.allclose(state,np.array([[1.,2.,3.,4.]]))
    assert not np.allclose(state,full.iloc[[0]][['ret_20d','realized_vol_20d','price_vs_ma20','dummy']].to_numpy())


def test_native_pipeline_callbacks_before_actual_fit_and_pickle_clean():
    native=SimpleNamespace(StandardScaler=StandardScaler,Ridge=Ridge,ElasticNet=ElasticNet,
        HistGradientBoostingRegressor=Ridge,MLPRegressor=Ridge,Gate=object,minimize=lambda *a,**kw:None)
    starts=[];x=np.array([[0.,0.],[1.,2.],[2.,1.],[3.,3.]])
    with f._native_starts(native,starts.append):
        scaler=native.StandardScaler();scaled=scaler.fit_transform(x)
        model=native.Ridge(alpha=1.).fit(scaled,np.arange(4,dtype=float))
    assert starts==['FUSION_SCALER','FUSION_PREDICTOR']
    assert 'fit' not in scaler.__dict__ and 'fit' not in model.__dict__
    assert type(model) is Ridge and native.Ridge is Ridge
    restored=pickle.loads(pickle.dumps(model))
    assert np.allclose(restored.predict(scaled),model.predict(scaled))


def test_parent_budget_rejection_prevents_native_fit():
    native=SimpleNamespace(StandardScaler=StandardScaler,Ridge=Ridge,ElasticNet=ElasticNet,
        HistGradientBoostingRegressor=Ridge,MLPRegressor=Ridge,Gate=object,minimize=lambda *a,**kw:None)
    def denied(_):raise RuntimeError('BUDGET_EXHAUSTED')
    with f._native_starts(native,denied):
        model=native.Ridge()
        with pytest.raises(RuntimeError,match='BUDGET_EXHAUSTED'):
            model.fit(np.ones((2,2)),np.ones(2))
        assert not hasattr(model,'coef_')
    assert native.Ridge is Ridge


def test_fixed40_MLP_warning_is_completion_not_fake_convergence(monkeypatch):
    import warnings
    from sklearn.exceptions import ConvergenceWarning
    class Pipe:
        def __init__(self):self.sent=[]
        def send(self,value):self.sent.append(value)
        def recv(self):return True
        def close(self):pass
    def fixed_fit(method,x,y,state,weights,started,deps):
        started('FUSION_SCALER');started('FUSION_PREDICTOR')
        warnings.warn('Fixed max_iter reached',ConvergenceWarning)
        return SimpleNamespace(model=SimpleNamespace(steps=[('mlp',SimpleNamespace(n_iter_=40))]))
    monkeypatch.setattr(f,'_fit_arrays',fixed_fit);pipe=Pipe()
    f._fusion_worker(pipe,'fusion','stack_mlp',None,None,None,None,(),None,None)
    assert [m[0] for m in pipe.sent]==['FIT_START','FIT_START','RESULT']
    assert pipe.sent[-1][2]['fixed_epochs_completed'] is True


def test_array_worker_reuses_parent_ACK_logger_and_external_receipt(tmp_path,monkeypatch):
    from scripts.research.a2.training import stateful_values as values
    events=[]
    def started(log,auth,prior,model_id,year,component,tuple_sha):
        events.append((model_id,year,component,tuple_sha))
    monkeypatch.setattr(values,'_component_start',started)
    def synthetic_writer(path,data):
        import json
        from pathlib import Path
        assert isinstance(path,Path), 'Production worker must pass Path to atomic storage writer'
        assert path.is_relative_to(tmp_path)
        path.write_text(json.dumps(data),encoding='utf-8')
    monkeypatch.setattr(values,'write_json_atomic',synthetic_writer)
    receipt={'receipt_path':str(tmp_path/'synthetic_receipt.json'),'fit_units':0}
    x=np.array([[1.,0.,0.],[0.,1.,0.],[0.,0.,1.],[1.,1.,1.]])
    model=values._fit_job('fusion','nnls',x,x@np.array([.5,.3,.2]),np.zeros((4,4)),np.ones(4),(),[],None,
        log=tmp_path/'unused_synthetic_log',auth={'max_fit_units':4},prior=0,year=2023,tuple_sha='synthetic',receipt=receipt,worker_target=f._fusion_worker)
    assert events==[('nnls',2023,'FUSION_NNLS','synthetic')]
    assert receipt['fit_units']==1
    assert np.allclose(model.weights,np.array([.5,.3,.2]))
    assert not (tmp_path/'unused_synthetic_log').exists()


def test_value_batch_finished_identity_and_running_guard():
    schedule=[{'model_id':'model'+str(i),'year':2023} for i in range(93)]
    config={'value_training':{'ordered_schedule':schedule}}
    complete={'status':'ATTEMPTS_FINISHED','expected_slots':93,
        'slots':[dict(p,status='TRAINED') for p in schedule]}
    f.validate_value_batch_complete(config,complete)
    with pytest.raises(RuntimeError,match='NO_SHARED_FIT_LOG_RACE'):
        f.validate_value_batch_complete(config,dict(complete,status='RUNNING'))
    wrong=dict(complete,slots=complete['slots'][:-1]+[{'model_id':'wrong','year':2023,'status':'TRAINED'}])
    with pytest.raises(RuntimeError,match='NO_SHARED_FIT_LOG_RACE'):
        f.validate_value_batch_complete(config,wrong)


def test_publication_receipt_binds_prediction_fit_producer_hashes(tmp_path,monkeypatch):
    import json
    from pathlib import Path
    (tmp_path/'input_manifest.json').write_text('{}',encoding='utf-8')
    fit_receipt=tmp_path/'fit_receipt.json';fit_receipt.write_text('{}',encoding='utf-8')
    predictions=pd.DataFrame({'signal_date':pd.to_datetime(['2023-01-03']*2),'ticker':['a','b'],
        'prediction':[.01,np.nan],'value_sigma':[.02,np.nan],'prediction_qualified':[True,False]})
    reader=SimpleNamespace(read_inference=lambda year:pd.DataFrame({'unused':[1]}))
    fitted=SimpleNamespace(run=tmp_path,receipt={'model_id':'equal','year':2023,'reuse_tuple_sha256':'synthetic-tuple','model_sha256':'synthetic-model','receipt_path':str(fit_receipt)},
        predict=lambda frame,reader:predictions.copy())
    monkeypatch.setattr(f,'assert_write_path',lambda path,purpose:None)
    monkeypatch.setattr(f,'write_json_atomic',lambda path,value:Path(path).write_text(json.dumps(value),encoding='utf-8'))
    publication=f.publish_prediction(fitted,reader)
    output=tmp_path/'predictions/fusion/equal/2023.parquet'
    assert publication['sha256']==f.values.sha(output)
    assert publication['fit_receipt_sha256']==f.values.sha(fit_receipt)
    assert publication['producer_source_sha256']==f.values.sha(f.__file__)
    assert publication['prediction_role']=='MODEL_OOF' and publication['rows']==2
    assert publication['qualified_rows']==1 and publication['unavailable_rows']==1
    assert f.publish_prediction(fitted,reader)==publication
    output.write_bytes(b'corrupted synthetic bytes')
    with pytest.raises(RuntimeError,match='PUBLICATION_CHANGED'):
        f.publish_prediction(fitted,reader)
