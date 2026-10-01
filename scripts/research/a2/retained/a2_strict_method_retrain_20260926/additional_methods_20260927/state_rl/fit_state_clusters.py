"""Causal cross-sectional state clustering; diagnostic only, no trading action."""
from __future__ import annotations
import hashlib, json, platform
from pathlib import Path
import joblib, numpy as np, pandas as pd, sklearn
from sklearn.cluster import KMeans
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

HERE=Path(__file__).resolve().parent
POOL=Path(r'D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\A\score_rank_ledger.parquet')
FEATURES=(
    'ret_1d','ret_3d','ret_5d','ret_10d','ret_20d','ret_40d','ret_60d','ret_120d',
    'price_vs_ma10','price_vs_ma20','price_vs_ma50','price_vs_ma120','ma10_vs_ma20','ma20_vs_ma50','ma50_vs_ma120',
    'realized_vol_5d','realized_vol_10d','realized_vol_20d','realized_vol_60d','downside_vol_20d','upside_vol_20d',
    'distance_from_high_20d','distance_from_high_60d','distance_from_low_20d','distance_from_low_60d',
    'max_drawdown_20d','max_drawdown_60d','avg_volume_20d','avg_volume_60d','volume_ratio_5d_20d','volume_ratio_20d_60d','avg_dollar_volume_20d')
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()

# Read the original eligible dynamic pool's observation-time features only.
source=pd.read_parquet(POOL,columns=['signal_date','ticker',*FEATURES])
assert np.isfinite(source.loc[:,FEATURES].to_numpy(dtype=np.float32)).all()
assert not source.duplicated(['signal_date','ticker']).any()
group=source.groupby('signal_date',sort=True)[list(FEATURES)]
med=group.median(); q75=group.quantile(.75); q25=group.quantile(.25)
state=pd.concat([med.add_prefix('median_'),(q75-q25).add_prefix('iqr_')],axis=1).reset_index()
state['pool_size']=source.groupby('signal_date').size().to_numpy()
state_cols=[x for x in state.columns if x!='signal_date']
assert np.isfinite(state[state_cols].to_numpy(dtype=float)).all()
source.drop(columns=list(FEATURES),inplace=True)
stage_specs=[('DEVELOPMENT',2023),('CONFIRMATION',2024),('FINAL',2025)]
logs=[];labels=[]
for name,year in stage_specs+[('FULL_PRE2026',2026)]:
    train=state.loc[state.signal_date.dt.year.lt(year)]
    eval_rows=state.loc[state.signal_date.dt.year.eq(year)] if year<2026 else state
    assert len(train)>0 and (len(eval_rows)>0)
    model=make_pipeline(StandardScaler(),KMeans(n_clusters=4,n_init=10,random_state=20260927))
    model.fit(train[state_cols].to_numpy(dtype=np.float64))
    assigned=model.predict(eval_rows[state_cols].to_numpy(dtype=np.float64))
    path=HERE/f'state_cluster_{name.lower()}.joblib'
    joblib.dump(model,path,compress=3)
    logs.append({'stage':name,'fit_years':sorted(train.signal_date.dt.year.unique().astype(int).tolist()),'train_days':len(train),
                 'evaluation_days':len(eval_rows),'n_clusters':4,'model_sha256':sha(path),'inertia':float(model[-1].inertia_),
                 'model_fit_calls':1,'scaler_fit_calls':1,'no_outcomes_used':True})
    if year<2026:
        labels.append(pd.DataFrame({'signal_date':eval_rows.signal_date,'stage':name,'cluster_id':assigned.astype(int)}))
pd.concat(labels,ignore_index=True).to_parquet(HERE/'pre2026_oof_state_labels.parquet',index=False)
state.to_parquet(HERE/'pre2026_daily_state_inputs.parquet',index=False)
report={'purpose':'Observation-time market-state diagnostic only; cluster labels are not portfolio scores, actions, or gates.',
        'original_pool_sha256':sha(POOL),'original_pool_rows':530075,'daily_state_days':len(state),'daily_state_columns':state_cols,
        'features':'32 original stock features aggregated per signal date as cross-sectional median and IQR plus current eligible pool size',
        'training_schedule':logs,'python':platform.python_version(),'sklearn':sklearn.__version__,
        'model_fit_calls':4,'preprocessor_fit_calls':4,'2026_data_used_for_fit_or_selection':False,
        'cluster_id_semantics':'Arbitrary per-fit integer; labels across stages are not aligned and must not be compared as identities.'}
(HERE/'STATE_CLUSTER_REPORT.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({'days':len(state),'oof_days':sum(x['evaluation_days'] for x in logs[:3]),'models':4,'fit_counts':[4,4]},indent=2))
