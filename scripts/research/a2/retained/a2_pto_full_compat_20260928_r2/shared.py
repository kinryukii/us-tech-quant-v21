"""Independent PTO batch. No learning function may read the 2026 inputs."""
from pathlib import Path
import hashlib, json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
WS = ROOT.parent
SEED = 20260928
FEATURES = ['ret_1d','ret_3d','ret_5d','ret_10d','ret_20d','ret_40d','ret_60d','ret_120d',
 'price_vs_ma10','price_vs_ma20','price_vs_ma50','price_vs_ma120','ma10_vs_ma20',
 'ma20_vs_ma50','ma50_vs_ma120','realized_vol_5d','realized_vol_10d','realized_vol_20d',
 'realized_vol_60d','downside_vol_20d','upside_vol_20d','distance_from_high_20d',
 'distance_from_high_60d','distance_from_low_20d','distance_from_low_60d',
 'max_drawdown_20d','max_drawdown_60d','avg_volume_20d','avg_volume_60d',
 'volume_ratio_5d_20d','volume_ratio_20d_60d','avg_dollar_volume_20d']
PRE_PANEL = ROOT/'data/pre_panel.parquet'
PRE_PRICES = ROOT/'data/pre_prices.parquet'
STAGES = {'inner':'2023-07-01','early':'2024-01-01','validation':'2025-01-01','final':'2026-01-01'}
MAX_ROWS = 40000
POINTS = ['ridge','elastic','huber','ebm','rf','extra','hgb','xgb','lgb','cat','mlp','resnet','fttransformer']
PROB = ['logistic','rf_class','hgb_class','xgb_class','lgb_class','cat_class','mlp_class']
QUANTILE = ['linear_q','hgb_q','xgb_q','lgb_q','cat_q','mlp_q']
DISTRIBUTION = ['ngboost','gaussian_mlp','cat_uncertainty']
RANK = ['xgb_rank','lgb_rank']
PREDICTORS = POINTS+PROB+QUANTILE+DISTRIBUTION+RANK
GROUPS = {'linear':POINTS[:3], 'interpretable':POINTS[:4], 'random_trees':['rf','extra'],
 'boosting':['hgb','xgb','lgb','cat'], 'neural':POINTS[10:], 'all_points':POINTS,
 'probability':PROB, 'quantile':QUANTILE, 'distribution':DISTRIBUTION,
 'ranking':RANK, 'all_outputs':PREDICTORS}
FUSIONS = ['equal','median','simplex','ridge_stack','elastic_stack','hgb_stack','mlp_stack',
 'linear_gate','mlp_gate','ridge_then_hgb','hgb_then_ridge']
RISKS = ['diagonal','sample','ledoit_wolf','oas','pca','factor_analysis',
 'lw_hgb_scale','lw_mlp_scale','garch','gjr_garch','lw_oas_average','pca_fa_average','lw_learned_scale_average']
OPTIMIZERS = ['positive_equal','mean_variance','robust_mv','cvar']
TARGET_FUSIONS = ['target_equal','target_median']

def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()
def read_json(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write_json(p,value):
    Path(p).parent.mkdir(parents=True,exist_ok=True)
    Path(p).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str,allow_nan=False),encoding='utf-8')
def fit_frame(stage):
    p=pd.read_parquet(PRE_PANEL)
    assert p.signal_date.lt('2026-01-01').all()
    cutoff=pd.Timestamp(STAGES[stage])
    valid=p.label_available & p.label_end_date.lt(cutoff) & p.signal_date.lt(cutoff)
    valid &= np.isfinite(p[FEATURES+['y_next_open']].to_numpy(float)).all(axis=1)
    p=p.loc[valid].sort_values(['signal_date','ticker']).reset_index(drop=True)
    rng=np.random.default_rng(SEED)
    quota=max(1,MAX_ROWS//p.signal_date.nunique())
    picks=[]
    for _,g in p.groupby('signal_date',sort=True):
        picks.extend(sorted(rng.choice(g.index,size=min(len(g),quota),replace=False)))
    if len(picks)>MAX_ROWS: picks=sorted(rng.choice(picks,size=MAX_ROWS,replace=False))
    p=p.loc[picks].reset_index(drop=True)
    assert p.label_end_date.lt(cutoff).all()
    keys=p[['signal_date','ticker','label_end_date']].copy()
    return p,keys

def paths():
    rows=[]
    for name in PREDICTORS:
        for risk in RISKS:
            for opt in OPTIMIZERS:
                rows.append(dict(path_id=f'{name}__identity__{risk}__{opt}',members=name,
                    group=name,fusion='identity',risk=risk,optimizer=opt,layer='pto'))
    for group,members in GROUPS.items():
        for fusion in FUSIONS:
            for risk in RISKS:
                for opt in OPTIMIZERS:
                    rows.append(dict(path_id=f'{group}__{fusion}__{risk}__{opt}',members='|'.join(members),
                        group=group,fusion=fusion,risk=risk,optimizer=opt,layer='pto'))
    for fusion in FUSIONS:
        for risk in RISKS:
            for tf in TARGET_FUSIONS:
                rows.append(dict(path_id=f'all_outputs__{fusion}__{risk}__{tf}',members='|'.join(PREDICTORS),
                    group='all_outputs',fusion=fusion,risk=risk,optimizer=tf,layer='target_fusion'))
    for rl in ['reinforce','reinforce_zero','ppo','ppo_zero']:
        rows.append(dict(path_id=rl,members='32_market_features+account_state',group='rl',fusion='none',
            risk='implicit',optimizer=rl,layer='rl_control'))
    return pd.DataFrame(rows)
