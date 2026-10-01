from __future__ import annotations
import hashlib, json, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
WS = ROOT.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'third_party'))

def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def clean(v):
    if isinstance(v, dict): return {str(k): clean(x) for k,x in v.items()}
    if isinstance(v, (list,tuple)): return [clean(x) for x in v]
    if isinstance(v, np.ndarray): return clean(v.tolist())
    if isinstance(v, np.integer): return int(v)
    if isinstance(v, (np.floating,float)): return float(v) if np.isfinite(v) else None
    if isinstance(v, np.bool_): return bool(v)
    if isinstance(v, Path): return str(v)
    return v

def write(path, value):
    path=Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, default=str, allow_nan=False),encoding='utf-8')

def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))

POINTS = ['ridge','elastic','huber','ebm','rf','extra','hgb','xgb','lgb','cat','mlp','resnet','fttransformer']
PROBS = ['logistic','rf_cls','hgb_cls','xgb_cls','lgb_cls','cat_cls','mlp_cls']
QUANTILES = ['linear_q','hgb_q','xgb_q','lgb_q','cat_q','mlp_q']
DISTRIBUTIONS = ['ngboost','mlp_dist','cat_uncertainty']
RANKERS = ['xgb_rank','lgb_rank']
PROVIDERS = POINTS+PROBS+QUANTILES+DISTRIBUTIONS+RANKERS
COALITIONS = {
 'linear':POINTS[:3], 'random_trees':['rf','extra'],
 'boosting':['hgb','xgb','lgb','cat'], 'neural':['mlp','resnet','fttransformer'],
 'all_points':POINTS, 'probability':PROBS, 'quantiles':QUANTILES,
 'distributions':DISTRIBUTIONS, 'rankers':RANKERS,
 'cross_structure':['ridge','ebm','hgb','resnet','ngboost'], 'all_outputs':PROVIDERS,
}
FUSIONS=['equal','median','convex','stack_ridge','stack_elastic','stack_hgb','stack_mlp','gate_linear','gate_mlp','residual_first_hgb','residual_last_ridge']
RISKS=['diag','historical','lw','oas','pca','fa','lw_hgb_vol','lw_mlp_vol','blend_lw_oas','blend_pca_fa']
OPTIMIZERS=['mv','robust','cvar']

def forecasts():
    return ([dict(forecast_id='single__'+p, coalition='single', members=[p], fusion='identity') for p in PROVIDERS]
       + [dict(forecast_id=g+'__'+f,coalition=g,members=m,fusion=f) for g,m in COALITIONS.items() for f in FUSIONS])

def strategies():
    rows=[]
    for f in forecasts():
        for r in RISKS:
            for o in OPTIMIZERS:
                rows.append(dict(**f,strategy_id=f['forecast_id']+'__'+r+'__'+o, route='prediction_fusion',risk=r,optimizer=o,target_fusion='none'))
        rows.append(dict(**f,strategy_id=f['forecast_id']+'__none__equal_top20',route='prediction_fusion',risk='none',optimizer='equal_top20',target_fusion='none'))
    for g,m in COALITIONS.items():
        for r,o in [(r,o) for r in RISKS for o in OPTIMIZERS]+[('none','equal_top20')]:
            rows.append(dict(strategy_id=g+'__target_blend__'+r+'__'+o,forecast_id=g+'__convex',coalition=g,members=m,
                             fusion='none',route='target_fusion',risk=r,optimizer=o,target_fusion='oof_convex_weights'))
    return rows
