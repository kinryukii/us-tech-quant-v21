"""Synthetic-only full-stock OOF fusion and actual-state callback acceptance."""
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import selector_cooperation as c


def full_oof():
    dates=np.repeat(pd.to_datetime(["2023-07-03","2023-07-05"]).to_numpy(),[23,31]);n=len(dates)
    uids=[f"UID:{i:03}" for i in range(23)]+[f"UID:{i:03}" for i in range(31)]
    h=pd.DataFrame(dict(signal_date=dates,security_uid=uids,U_t_fingerprint=["FULL"]*n,label_end_date=dates+pd.Timedelta(days=30),target=np.linspace(-.03,.03,n)))
    for i,m in enumerate(c.FULL_STOCK_MEMBERS):
        h[m+"__mu"]=h.target*(.7+i*.1);h[m+"__source_kind"]="MODEL_OOF";h[m+"__source_cutoff"]=pd.Timestamp("2023-07-01")
        h[m+"__source_capacity"]="MID";h[m+"__max_train_label_end"]=pd.Timestamp("2023-06-29");h[m+"__cutoff_clock"]="MIDNIGHT_BEFORE_DECISION_CLOSE"
    rng=np.random.default_rng(14);x=rng.normal(size=(n,32));context=x[:,:5].copy()
    expected={day:tuple(g.security_uid) for day,g in h.groupby("signal_date")}
    return h,x,context,expected


@pytest.mark.parametrize("bad",["insample","raw","capacity","maturity","train_label_future","member_missing","uid_axis","unknown","cutoff_clock"])
def test_full_fusion_bad_dependency_before_state(bad):
    h,x,context,expected=full_oof();m=c.FULL_STOCK_MEMBERS[0];events=[]
    if bad=="insample":h[m+"__source_cutoff"]=pd.Timestamp("2023-07-04")
    elif bad=="raw":h[m+"__source_kind"]="RAW_FALLBACK"
    elif bad=="capacity":h[m+"__source_capacity"]="LOW"
    elif bad=="maturity":h.label_end_date=pd.Timestamp("2024-01-01")
    elif bad=="train_label_future":h[m+"__max_train_label_end"]=pd.Timestamp("2023-07-01")
    elif bad=="member_missing":h.loc[0,m+"__mu"]=np.nan
    elif bad=="uid_axis":expected[h.signal_date.iloc[0]]+=("UID:999",)
    elif bad=="unknown":h.loc[0,"security_uid"]="UNKNOWN"
    else:h[m+"__cutoff_clock"]="AFTER_DECISION"
    with pytest.raises(ValueError):c.fit_full_stock_fusion(None,"equal",h,"2024-01-01",x,context,expected_full_day_uids=expected,on_state=events.append)
    assert not events


def test_full_fusion_equal_median_zero_learned_operations():
    from types import SimpleNamespace
    class Native:
        def __init__(self,method,members):self.method=method
        def predict(self,mu,context):return mu.mean(1) if self.method=="equal" else np.median(mu,axis=1)
    module=SimpleNamespace(Fusion=Native);h,x,context,expected=full_oof();mu=h[[m+"__mu" for m in c.FULL_STOCK_MEMBERS]].to_numpy()
    for method in ("equal","median"):
        events=[];fit,receipt=c.fit_full_stock_fusion(module,method,h,"2024-01-01",x,context,expected_full_day_uids=expected,on_state=events.append)
        assert not events and receipt["model_fit_count"]==receipt["scaler_fit_count"]==receipt["target_scale_count"]==0
        assert len(c.predict_full_stock_fusion(fit,mu,x,context))==len(h)


def test_full_fusion_residual_uses_existing_true_oof_mu(monkeypatch):
    from types import SimpleNamespace
    class SpyModel:
        def __init__(self,**kwargs):pass
        def fit(self,x,y,sample_weight):self.y=y.copy();self.weights=sample_weight.copy();return self
        def predict(self,x):return np.zeros(len(x))
    module=SimpleNamespace(Ridge=SpyModel,tree=SpyModel);h,x,context,expected=full_oof()
    for method,index in (("ridge_then_hgb",0),("hgb_then_ridge",1)):
        events=[];fit,receipt=c.fit_full_stock_fusion(module,method,h,"2024-01-01",x,context,expected_full_day_uids=expected,on_state=events.append)
        np.testing.assert_allclose(fit.model.y,h.target-h[c.FULL_STOCK_MEMBERS[index]+"__mu"])
        assert [e["kind"] for e in events]==["META_SCALER","META_MODEL"]
        assert fit.model.weights[:23].sum()==pytest.approx(fit.model.weights[23:].sum())
        assert receipt["residual_source"]=="TRUE_PAST_OOF_mu"


def test_full_fusion_actual_methods_have32_28_14_nodes(retained_calibration):
    h,x,context,expected=full_oof();events=[];mu=h[[m+"__mu" for m in c.FULL_STOCK_MEMBERS]].to_numpy()
    for method in c.FULL_STOCK_METHODS:
        model,receipt=c.fit_full_stock_fusion(retained_calibration,method,h,"2024-01-01",x,context,expected_full_day_uids=expected,on_state=events.append)
        pred=c.predict_full_stock_fusion(model,mu,x,context)
        assert pred.shape==(len(h),) and np.isfinite(pred).all()
    assert {k:sum(e["kind"]==k for e in events) for k in ("META_MODEL","META_SCALER","META_TARGET_SCALE")}==dict(META_MODEL=16,META_SCALER=14,META_TARGET_SCALE=7)
    assert len({e["node_id"] for e in events})==37


@pytest.fixture
def retained_calibration():
    from scripts.research.a2.training.selector_challenge import module,RETAINED,DEP,TORCH_DEP
    import sys
    for folder in (RETAINED,DEP,TORCH_DEP):
        if str(folder) not in sys.path:sys.path.append(str(folder))
    return module("_full_stock_synthetic_calibration",RETAINED/"calibration_fusion.py")
