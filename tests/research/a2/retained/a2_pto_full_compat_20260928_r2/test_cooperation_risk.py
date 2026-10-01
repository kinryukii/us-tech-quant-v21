import numpy as np
import pandas as pd
import pytest
import joblib
from shared import *
from calibration_fusion import fit_calibration,fit_fusion
from risk_models import RiskRuntime,build_scenario_adapter

def panel():
    rng=np.random.default_rng(12);n=400
    dates=np.repeat(pd.date_range('2023-07-03',periods=40,freq='B'),10)
    probability=rng.uniform(.05,.95,n)
    y=np.where(rng.uniform(size=n)<probability,.02,-.01)
    return pd.DataFrame({'signal_date':dates,'ticker':np.tile([str(i) for i in range(10)],40),
        'label_end_date':dates+pd.Timedelta(days=3),'y_next_open':y,'logistic__p':probability,
        'huber__raw':y+rng.normal(0,.02,n),'linear_q__q10':-.03,'linear_q__q50':-.002,'linear_q__q90':.06,
        'ridge__mu':rng.normal(.001,.02,n),'elastic__mu':rng.normal(.003,.01,n),
        **{c:rng.normal(size=n) for c in ['ret_1d','ret_20d','realized_vol_20d','realized_vol_60d','volume_ratio_5d_20d']}})

def test_probability_maps_signed_return_not_win_rate():
    frame=panel();obj,receipt=fit_calibration('logistic',frame,'2024-01-01');mu,_,p=obj.predict(frame)
    np.testing.assert_allclose(mu,p*.02+(1-p)*(-.01),atol=1e-12)
    assert not np.allclose(mu,p)
    assert receipt['fit_2026_rows']==0

def test_quantile_median_is_not_mean_adapter():
    frame=panel();obj,_=fit_calibration('linear_q',frame,'2024-01-01');mu,_,_=obj.predict(frame)
    assert not np.allclose(mu,frame.linear_q__q50)

def test_future_calibration_rejected():
    with pytest.raises(ValueError,match='CLOCK_LEAK'):fit_calibration('huber',panel(),'2023-08-01')

def test_simplex_and_missing_member_contract():
    frame=panel();obj,r=fit_fusion('simplex',['ridge','elastic'],frame,'2024-01-01')
    assert np.min(obj.coefficients)>=0 and abs(np.sum(obj.coefficients)-1)<1e-9
    frame['elastic__mu']=np.nan
    with pytest.raises(ValueError,match='UNAVAILABLE_MEMBER'):fit_fusion('equal',['ridge','elastic'],frame,'2024-01-01')

@pytest.mark.parametrize('stage',['validation','final'])
def test_risk_psd_and_historical_scenario(stage):
    adapter=build_scenario_adapter(stage);obj=joblib.load(ROOT/'models'/f'risk_{stage}.joblib')
    tickers=obj['tickers'][:12]+['PTO_UNSEEN_NAME'];runtime=RiskRuntime(obj,tickers)
    frame,_=fit_frame(stage);features=frame[FEATURES].to_numpy(float)[:len(tickers)].copy()
    features[-1]=np.nan;runtime.prepare_day(pd.Timestamp(STAGES[stage]),features)
    selection=np.arange(len(tickers))[None,:]
    for name in RISKS:
        covariance,scale,scenarios=runtime.get(name,selection)
        assert np.isfinite(covariance).all() and np.isfinite(scenarios).all()
        assert np.linalg.eigvalsh(covariance[0]).min()>-1e-9
        assert covariance.shape==(1,len(tickers),len(tickers)) and scenarios.shape==(1,32,len(tickers))
        assert np.all(scale>0)
    assert runtime.scales['lw_hgb_scale'][-1]==runtime.sigma[-1]
    assert read_json(adapter.with_suffix('.json'))['no_parameter_refit']
