"""Read-only adapters for future complete-pool inference; no fit methods."""
from __future__ import annotations
from pathlib import Path
import json
import joblib, numpy as np, pandas as pd, torch

HERE=Path(__file__).resolve().parent

def policy_rank_full_pre2026(day:pd.DataFrame,previous_target_names:set[str]|None=None)->pd.DataFrame:
    """Rank one fully-qualified signal-day pool using the saved RL policy.

    The caller, not this function, must establish the original full candidate
    qualification gate. No future execution or valuation prices are read.
    """
    artifact=torch.load(HERE/'policy_full_pre2026.pt',map_location='cpu',weights_only=True)
    scaler=joblib.load(HERE/'policy_full_pre2026_scaler.joblib')
    features=list(artifact['feature_order'])
    assert len(day)>=20 and day.ticker.notna().all() and day.ticker.is_unique
    assert set(features).issubset(day.columns)
    assert day.signal_date.nunique()==1
    x=day.loc[:,features].to_numpy(dtype=np.float64)
    assert np.isfinite(x).all()
    x=np.clip(scaler.transform(x),-10,10)
    previous_target_names=previous_target_names or set()
    held=day.ticker.astype(str).isin(previous_target_names).to_numpy(dtype=np.float64).reshape(-1,1)
    w=artifact['weight'].numpy().astype(np.float64)
    score=np.column_stack([x,held])@w
    result=day[['signal_date','ticker']].copy()
    result['prediction']=score
    result=result.sort_values(['prediction','ticker'],ascending=[False,True],kind='mergesort').reset_index(drop=True)
    result['rank']=np.arange(1,len(result)+1,dtype=np.int32)
    return result

def state_cluster_full_pre2026(day:pd.DataFrame)->int:
    """Return a diagnostic cluster ID from one complete qualified day."""
    state_columns=json.loads((HERE/'STATE_CLUSTER_REPORT.json').read_text(encoding='utf-8'))['daily_state_columns']
    features=[col.removeprefix('median_') for col in state_columns if col.startswith('median_')]
    assert len(features)==32
    assert day.signal_date.nunique()==1 and len(day)>=20
    x=day.loc[:,features].to_numpy(dtype=np.float64)
    assert np.isfinite(x).all()
    med=np.median(x,axis=0)
    iqr=np.quantile(x,.75,axis=0)-np.quantile(x,.25,axis=0)
    state=np.r_[med,iqr,len(day)].reshape(1,-1)
    model=joblib.load(HERE/'state_cluster_full_pre2026.joblib')
    return int(model.predict(state)[0])
