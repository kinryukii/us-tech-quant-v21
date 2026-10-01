import numpy as np
import pandas as pd
from fusion import interface_x,fit_fusion,predict_fusion,adapt

def test_probability_quantile_rank_semantics():
    date=pd.Timestamp('2024-01-02')
    f=pd.DataFrame({'signal_date':[date]*3,'ticker':['A','B','C'],'mu':[99]*3,'p_up':[.2,.5,.8],
        'q10':[-.04,-.02,-.01],'q50':[0,.01,.02],'q90':[.04,.06,.08],'rank_score':[20,10,30]})
    assert np.allclose(interface_x('prob_hgb',f).ravel(),[.2,.5,.8])
    assert interface_x('quant_hgb',f).shape==(3,3)
    assert np.allclose(interface_x('rank_xgb',f).ravel(),[2/3,1/3,1])

def test_simplex_weights_are_nonnegative_and_sum_to_one():
    rng=np.random.default_rng(2);x=rng.normal(0,.01,(200,3));y=x@np.array([.2,.7,.1])
    m=fit_fusion('simplex',x,y,None,pd.date_range('2024-07-01',periods=200))
    assert (m['weights']>=0).all() and abs(m['weights'].sum()-1)<1e-9
    mu,w=predict_fusion(m,x,None)
    assert np.mean((mu-y)**2)<1e-10 and w.shape==x.shape

def test_residual_anchor_never_trains_on_residual_half_labels():
    rng=np.random.default_rng(4);x=rng.normal(0,.01,(240,3));y=x[:,0]*.5+x[:,1]*.2
    dates=pd.date_range('2024-07-01',periods=240)
    first=fit_fusion('ridge_then_hgb',x,y,np.zeros((240,5)),dates)
    changed=y.copy();changed[120:]+=.1
    second=fit_fusion('ridge_then_hgb',x,changed,np.zeros((240,5)),dates)
    assert np.array_equal(first['anchor'].predict(x),second['anchor'].predict(x))
    assert first['nested_training'] and pd.Timestamp(first['anchor_end'])<pd.Timestamp(first['residual_end'])

def test_gate_weights_obey_convex_expert_interface():
    rng=np.random.default_rng(5);x=rng.normal(0,.01,(128,3));context=rng.normal(size=(128,5));y=x.mean(1)
    for name in ['linear_gate','mlp_gate']:
        m=fit_fusion(name,x,y,context,pd.date_range('2024-07-01',periods=128))
        mu,w=predict_fusion(m,x,context)
        assert np.isfinite(mu).all() and (w>=0).all() and np.allclose(w.sum(1),1,atol=1e-6)
        assert np.allclose(mu,(w*x).sum(1))
