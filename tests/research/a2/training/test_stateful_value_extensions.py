"""Small synthetic CPU-only extension checks; no research vectors or outputs."""
from types import SimpleNamespace
import pickle
import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import StandardScaler
from scripts.research.a2.training import stateful_value_extensions as ext

PATHS=(str(ext.TORCH_SNAPSHOT),)

def test_masked_standardization_is_train_only_and_not_fake_observation():
    x=np.tile(np.arange(32,dtype=float),(4,20,1))
    x[1]+=1.;mask=np.isfinite(x);mask[0,0,0]=False
    x[0,0,0]=999999.
    values,observed=ext._observed(x,mask,True)
    scaler=StandardScaler().fit(values.reshape(-1,32))
    mean=scaler.mean_.copy();a=ext._standardized(scaler,x,mask,True)
    x[0,0,0]=-999999.;b=ext._standardized(scaler,x,mask,True)
    assert np.array_equal(a,b) and a[0,0,0]==0. and a[0,0,32]==1.
    ext._standardized(scaler,x+100.,mask,True)
    assert np.array_equal(scaler.mean_,mean)
    with pytest.raises(ValueError,match='FROZEN_ORDERED'):ext._feature_order(tuple(reversed(ext.FEATURES)))


def test_native_svc_parameters_and_no_probability_cv():
    model=ext._svc(ext.FEATURES)
    p=model.get_params()
    assert p['kernel']=='rbf' and p['C']==1. and p['gamma']=='scale'
    assert p['probability'] is False and p['cache_size']==512 and p['max_iter']==100000
    assert p['random_state']==20260928
    assert ext.specs()['svc']['inherited_pipeline_used'] is False


def test_l20_batch_keys_past_boundary_and_calendar_start_masks():
    cal=pd.bdate_range('2020-01-02',periods=25)
    flags=pd.DataFrame({'signal_date':cal,'ticker':['A']*25,'feature_available':[True]*25})
    vectors=flags[['signal_date','ticker']].copy()
    for f in ext.FEATURES:vectors[f]=np.arange(25,dtype=float)
    reader=SimpleNamespace(calendar=cal,pred_flags=flags)
    def read(source,columns,filters):
        start=filters[0][2];end=filters[1][2]
        return vectors.loc[vectors.signal_date.between(start,end),columns]
    reader._vectors=read
    keys=pd.DataFrame({'signal_date':cal[[2,22]],'ticker':['A','A']})
    result=ext.sequence_windows(reader,keys)
    assert result['keys'].equals(keys.reset_index(drop=True))
    assert result['features'].shape==(2,20,32) and result['left_pad_sessions'].tolist()==[17,0]
    assert not result['cell_observed'][0,:17].any() and np.isnan(result['features'][0,:17]).all()
    assert result['features'][0,-1,0]==2. and result['features'][1,-1,0]==22.
    assert (result['dates'][1]<=keys.signal_date.iloc[1].to_datetime64()).all()
    vectors.loc[vectors.signal_date>keys.signal_date.iloc[-1],list(ext.FEATURES)]=1e10
    changed=ext.sequence_windows(reader,keys)
    assert np.array_equal(result['features'],changed['features'],equal_nan=True)


def test_daily_tcn_left_padding_is_causal_without_fit():
    torch=ext._torch(PATHS);torch.manual_seed(ext.SEED)
    model=ext._network('tcn',torch);model.eval()
    x=torch.randn(2,20,64)
    def hidden(v):
        z=v.transpose(1,2)
        for layer,padding in zip(model.layers,(2,4,8,16)):
            z=torch.relu(layer(torch.nn.functional.pad(z,(padding,0))))
        return z
    before=hidden(x);x[:,15:]+=100.;after=hidden(x)
    assert torch.equal(before[:,:,:15],after[:,:,:15])
    assert model(x).shape==(2,) and ext.specs()['minute_empirical_coverage'] is False
    assert ext.specs()['sequence']['tcn']['receptive_field']>=20


@pytest.mark.parametrize('method',ext.NAMES)
def test_synthetic_single_fit_callbacks_and_state_pickle(method):
    rng=np.random.default_rng(5)
    x=rng.normal(size=(8,32) if method=='svc' else (8,20,32))
    mask=np.isfinite(x);mask.reshape(-1,32)[0,0]=False;x.reshape(-1,32)[0,0]=np.nan
    y=np.array([-.02,.01,-.01,.03,-.03,.02,-.01,.01])
    events=[]
    fitted=ext.fit_extension(method,x,y,feature_order=ext.FEATURES,mask=mask,
        dependency_paths=PATHS,on_fit_started=events.append)
    assert events==['FEATURE_SCALER','PREDICTOR']
    assert fitted.metadata['actual_fit_components']==events and fitted.metadata['predictor_fit_count']==1
    assert fitted.metadata['training_rows']==len(x) and fitted.metadata['target_scaler_fit_count']==0
    predicted=ext.raw_predict(fitted,x,mask)
    restored=pickle.loads(pickle.dumps(fitted))
    assert np.array_equal(predicted,ext.raw_predict(restored,x,mask))
    assert predicted.shape==(len(x),) and np.isfinite(predicted).all()
    if method!='svc':assert fitted.metadata['epochs']==12 and fitted.metadata['optimizer_steps']==12
    empty=x[:0]
    assert ext.raw_predict(fitted,empty,mask[:0]).shape==(0,)
