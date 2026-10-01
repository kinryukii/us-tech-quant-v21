"""Shared, pre-registered contracts. Importing this module never reads test data."""
from pathlib import Path
import os, sys, json, hashlib
os.environ.setdefault('OMP_NUM_THREADS', '2')
os.environ.setdefault('MKL_NUM_THREADS', '2')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')
ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / 'vendor'
sys.path.insert(0, str(VENDOR))
GBDT_SITE = Path(r'D:\us-tech-quant-envs\us-tech-quant-main\Lib\site-packages')
if GBDT_SITE.exists():
    sys.path.append(str(GBDT_SITE))
import numpy as np
import pandas as pd
SEED = SAMPLING_SEED = 20260928
DATA_SOURCE = ROOT / 'data/pre.parquet'
OUT_DIR = ROOT
FEATURES = ['ret_1d','ret_3d','ret_5d','ret_10d','ret_20d','ret_40d','ret_60d','ret_120d',
 'price_vs_ma10','price_vs_ma20','price_vs_ma50','price_vs_ma120','ma10_vs_ma20','ma20_vs_ma50','ma50_vs_ma120',
 'realized_vol_5d','realized_vol_10d','realized_vol_20d','realized_vol_60d','downside_vol_20d','upside_vol_20d',
 'distance_from_high_20d','distance_from_high_60d','distance_from_low_20d','distance_from_low_60d',
 'max_drawdown_20d','max_drawdown_60d','avg_volume_20d','avg_volume_60d','volume_ratio_5d_20d',
 'volume_ratio_20d_60d','avg_dollar_volume_20d']
CUTOFFS = {'development':'2024-01-01', 'validation':'2025-01-01', 'final':'2026-01-01'}
POINT = ['ridge','elastic','huber','ebm','rf','et','hgb','xgb','lgb','cat','mlp','resnet','ft_transformer']
CLASSIFIERS = ['prob_logistic','prob_rf','prob_hgb','prob_xgb','prob_lgb','prob_cat','prob_mlp']
QUANTILES = ['quant_linear','quant_hgb','quant_xgb','quant_lgb','quant_cat','quant_mlp']
DISTRIBUTIONS = ['dist_ngboost','dist_mlp','dist_cat']
RANKERS = ['rank_xgb','rank_lgb']
MEMBERS = POINT + CLASSIFIERS + QUANTILES + DISTRIBUTIONS + RANKERS
BUNDLES = {'linear':POINT[:3], 'trees':['ebm','rf','et','hgb','xgb','lgb','cat'],
 'neural':['mlp','resnet','ft_transformer'], 'all_interfaces':MEMBERS}
FUSIONS = ['equal','median','simplex','ridge_stack','elastic_stack','hgb_stack','mlp_stack',
 'linear_gate','mlp_gate','ridge_then_hgb','hgb_then_ridge']
RISKS = ['diagonal','samplecov','lw','oas','pca5','fa5','lw_oas','lw_hgb','lw_mlp',
 'lw_scale_equal','lw_garch11','lw_gjr11']
OPTIMIZERS = ['mean_variance','robust','cvar']
AXES = ['joint','buy','sell','cash']

def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def write_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding='utf-8')

def training_sample(frame, cutoff, per_day=80):
    """Same finite mature rows and hash sample for every supervised learning target."""
    x = frame.copy()
    x['signal_date'] = pd.to_datetime(x.signal_date)
    x['label_end_date'] = pd.to_datetime(x.label_end_date)
    valid = x.signal_date.lt(cutoff) & x.label_end_date.gt(x.signal_date) & x.label_end_date.lt(cutoff)
    valid &= x.label_available.fillna(False) & x.new_buy_eligible.fillna(False)
    valid &= np.isfinite(x[FEATURES].to_numpy(float)).all(axis=1) & np.isfinite(x.y_next_open.to_numpy(float))
    x = x.loc[valid].copy()
    keys = x.signal_date.dt.strftime('%Y-%m-%d') + '|' + x.ticker + '|' + str(SEED)
    x['_sample_key'] = keys.map(lambda s: hashlib.sha256(s.encode()).hexdigest())
    x = x.sort_values(['signal_date','_sample_key']).groupby('signal_date', sort=False).head(per_day)
    return x.drop(columns='_sample_key').sort_values(['signal_date','ticker']).reset_index(drop=True)

def registry():
    streams = [{'stream':m,'bundle':'singleton','fusion':'identity','members':[m]} for m in MEMBERS]
    streams += [{'stream':b+'__'+f,'bundle':b,'fusion':f,'members':ms} for b,ms in BUNDLES.items() for f in FUSIONS]
    paths = []
    for s in streams:
        for r in RISKS:
            for o in OPTIMIZERS:
                for a in AXES:
                    paths.append(dict(strategy=f"{s['stream']}__{r}__{o}__{a}",**s,risk=r,optimizer=o,axis=a,target_fusion='none'))
    # Position fusion is a separate decision layer. Every expert sees the same actual account.
    for f in ['target_equal','target_median']:
        for r in RISKS:
            for o in OPTIMIZERS:
                for a in AXES:
                    paths.append(dict(strategy=f'{f}__{r}__{o}__{a}',stream='point_experts',bundle='point13',
                        fusion='none',members=POINT,risk=r,optimizer=o,axis=a,target_fusion=f))
    return streams, paths
