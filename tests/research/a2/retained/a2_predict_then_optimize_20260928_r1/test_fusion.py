import numpy as np
import pandas as pd
from fusion_models import Fusion,state_features
from common import COALITIONS,FUSIONS,PROVIDERS,forecasts,strategies

def test_finite_roster_without_champions():
    assert len(PROVIDERS)==31 and len(forecasts())==152 and len(strategies())==5053
    rows=strategies();assert len({r['strategy_id'] for r in rows})==len(rows)
    for f in forecasts():
        r=[x for x in rows if x['route']=='prediction_fusion' and x['forecast_id']==f['forecast_id']]
        assert len(r)==31
        assert sum(x['optimizer']=='equal_top20' for x in r)==1
        assert len({(x['risk'],x['optimizer']) for x in r})==31

def test_gate_and_convex_weights_are_valid():
    rng=np.random.default_rng(3);x=rng.normal(0,.02,(160,3));y=x@np.array([.6,.3,.1])
    state=rng.normal(size=(160,4));w=np.ones(160);w.flags.writeable=False
    for method in ['convex','gate_linear','gate_mlp']:
        m=Fusion(method).fit(x,y,state,w)
        pred=m.predict(x,state)
        assert np.isfinite(pred).all()
        assert np.all(pred>=x.min(1)-1e-8) and np.all(pred<=x.max(1)+1e-8)
        assert np.isfinite(m.uncertainty(x,np.full_like(x,.02),state)).all()

def test_state_is_signal_day_only():
    f=pd.DataFrame(dict(signal_date=pd.to_datetime(['2024-01-02']*2+['2024-01-03']*2),
       ret_20d=[1,3,4,6],realized_vol_20d=[.02]*4,price_vs_ma20=[-1,1,-1,-1]))
    x=np.arange(12,dtype=float).reshape(4,3)
    result=state_features(f,x)
    assert np.all(result[:2,0]==2) and np.all(result[2:,0]==5)
    f.loc[2:,'ret_20d']=1000
    assert np.array_equal(state_features(f,x)[:2],result[:2])
