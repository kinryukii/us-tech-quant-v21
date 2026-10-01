"""Synthetic full-row fusion, chronological uncertainty and source-class reuse."""
import os
import subprocess
import sys
import joblib
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.ensemble import joint_five_day_fusion as fusion

def history(rows_per_date=50):
    rng=np.random.default_rng(7);dates=pd.date_range("2022-01-01",periods=12,freq="MS")+pd.Timedelta(days=2)
    frame=pd.DataFrame({"signal_date":np.repeat(dates,rows_per_date),
        "ticker":[str(i) for i in range(rows_per_date)]*len(dates)})
    frame["label_end_date"]=frame.signal_date+pd.Timedelta(days=5)
    frame["label_mature_date"]=frame.label_end_date
    frame["fit_eligible"]=True;frame["trade_eligible"]=True
    frame["y_open5"]=rng.normal(0,.1,len(frame))
    for name in fusion.MEMBERS:
        frame[name+"__mu"]=rng.normal(0,.1,len(frame))
        frame[name+"__bridge_cutoff"]=pd.Timestamp("2022-01-01")
        frame[name+"__source_cutoff"]=pd.Timestamp("2022-01-01")
        frame[name+"__bridge_label_mature_max"]=pd.Timestamp("2021-12-31")
    for name in fusion.CONTEXT:frame[name]=rng.normal(size=len(frame))
    return frame

def future(frame):
    out=frame.iloc[:10].copy();out["signal_date"]=pd.Timestamp("2023-02-01")
    out.loc[out.index[0],"ridge__mu"]=np.nan
    return out

@pytest.mark.parametrize("method",fusion.METHODS)
def test_all_eleven_existing_handlers_fit_full_legal_rows_and_preserve_missing(method):
    h=history();bundle=fusion.fit_five_day_fusion(h,"2023-01-01",method)
    assert bundle["receipt"]["fit_rows"]==len(h)
    assert bundle["receipt"]["fit_units"]==fusion.fusion_fit_units(method)
    assert bundle["receipt"]["native_base_refits"]==0
    out=fusion.apply_five_day_fusion(future(h),bundle)
    assert len(out)==10 and not out.meta_available.iloc[0]
    assert np.isnan(out.mu.iloc[0]) and out.mu.iloc[1:].notna().all()
    assert out.expected_return_coordinate.eq(fusion.UNIT).all()
    if method not in ("equal","median","fixed_weighted"):
        receipt=bundle["receipt"]
        assert pd.Timestamp(receipt["probe_max_label_mature"])<pd.Timestamp(receipt["probe_boundary"])
        assert receipt["uncertainty_source"]=="chronological second-half true OOF error"

def test_actual_shared_sample_hook_retains_more_than_40000():
    h=history(rows_per_date=3500)
    bundle=fusion.fit_five_day_fusion(h,"2023-01-01","equal")
    assert bundle["receipt"]["fit_rows"]==42000
    assert bundle["receipt"]["full_receipt"]["rows"]==42000

def test_uncertainty_uses_held_probe_error_not_full_fit_residual():
    h=history()
    for name in fusion.MEMBERS:h[name+"__mu"]=0.
    dates=sorted(h.signal_date.unique());boundary=pd.Timestamp(dates[len(dates)//2])
    h["y_open5"]=h.signal_date.ge(boundary).astype(float)
    bundle=fusion.fit_five_day_fusion(h,"2023-01-01","ridge_stack")
    assert bundle["residual_rms"]==pytest.approx(1.)
    assert bundle["model"].predict(np.zeros((2,5)),np.zeros((2,5))).tolist()==pytest.approx([.5,.5])
    assert bundle["receipt"]["fit_units"]==5

def test_member_future_clock_and_test_content_are_rejected():
    h=history();h.loc[0,"ridge__bridge_cutoff"]=pd.Timestamp("2024-01-01")
    with pytest.raises(ValueError,match="CLOCK"):fusion.prepare_fusion_training(h,"2023-01-01")
    h=history();h.loc[0,"label_mature_date"]=pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError,match="TEST_BOUNDARY"):fusion.prepare_fusion_training(h,"2023-01-01")
    h=history();bundle=fusion.fit_five_day_fusion(h,"2023-01-01","equal")
    f=future(h);f.loc[f.index[1],"ridge__source_cutoff"]=pd.Timestamp("2024-01-01")
    with pytest.raises(ValueError,match="FUTURE_MEMBER"):fusion.apply_five_day_fusion(f,bundle)

def test_shared_class_joblib_restores_in_fresh_python(tmp_path):
    bundle=fusion.fit_five_day_fusion(history(),"2023-01-01","ridge_stack")
    path=tmp_path/"synthetic_fusion.joblib";joblib.dump(bundle,path)
    code="import joblib; import scripts.research.a2.ensemble.joint_five_day_fusion; b=joblib.load("+repr(str(path))+"); assert b['receipt']['fit_units']==5; print(type(b['model']).__name__)"
    result=subprocess.run([sys.executable,"-B","-c",code],cwd=str(PathRoot()),env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1"},capture_output=True,text=True,timeout=40)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=="Fusion"

def PathRoot():
    from pathlib import Path
    return Path(__file__).resolve().parents[4]

@pytest.mark.parametrize("method",["ridge_then_hgb","hgb_then_ridge"])
def test_residual_uses_existing_primary_oof_and_canonical32(method):
    h=history();rng=np.random.default_rng(17)
    for name in fusion.FEATURES:h[name]=rng.normal(size=len(h))
    h["Ridge_raw"]=rng.normal(size=len(h));h["HGB_raw"]=rng.normal(size=len(h))
    h["source_fit_cutoff"]=pd.Timestamp("2022-01-01")
    bundle=fusion.fit_oof_residual(h,"2023-01-01",method)
    assert bundle["receipt"]["fit_units"]==2
    assert bundle["receipt"]["primary_refit_units"]==0
    assert bundle["receipt"]["secondary_features"]==list(fusion.FEATURES)
    assert bundle["receipt"]["sigma"] is None
    f=h.iloc[:3].copy();f["signal_date"]=pd.Timestamp("2023-02-01")
    out=fusion.apply_oof_residual(f,bundle)
    assert out[method+"__raw"].notna().all()
    assert "sigma" not in out
