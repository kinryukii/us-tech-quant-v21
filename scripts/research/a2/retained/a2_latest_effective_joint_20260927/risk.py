"""Frozen pre-2026 covariance estimators and bounded portfolio optimization."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
from scipy.linalg import eigh
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / 'a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet'
OUT = ROOT / 'risk'

def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def fit_risk():
    OUT.mkdir(exist_ok=True)
    if (OUT / 'frozen_covariance.npz').exists():
        raise RuntimeError('FROZEN_RISK_EXISTS; load instead of refitting')
    frame = pd.read_parquet(SOURCE, columns=['ticker','trade_date','close'])
    frame['trade_date'] = pd.to_datetime(frame.trade_date)
    assert frame.trade_date.max() < pd.Timestamp('2026-01-01')
    wide = frame.pivot(index='trade_date', columns='ticker', values='close').sort_index().tail(253)
    returns = wide.pct_change(fill_method=None).iloc[1:]
    count = returns.notna().sum()
    returns = returns.loc[:, count >= 200]
    raw = returns.to_numpy(float)
    clipped = np.clip(raw, -.5, .5)
    means = np.nanmean(clipped, axis=0)
    vol = np.maximum(np.nanstd(clipped, axis=0, ddof=1), .01)
    z = np.nan_to_num((clipped-means)/vol, nan=0.)
    estimator = LedoitWolf().fit(z)
    corr = estimator.covariance_
    scale = np.sqrt(np.diag(corr))
    corr = corr / np.outer(scale, scale)
    cov = corr * np.outer(vol, vol)
    n = len(vol)
    vals, vecs = eigh(cov, subset_by_index=[max(0,n-5),n-1])
    common = (vecs * vals) @ vecs.T
    residual = np.maximum(np.diag(cov-common), 1e-8)
    factor = common + np.diag(residual)
    np.linalg.cholesky(cov)
    np.linalg.cholesky(factor)
    np.savez_compressed(OUT/'frozen_covariance.npz', tickers=returns.columns.to_numpy(str), covariance=cov,
                        factor_covariance=factor, factor_loadings=vecs, factor_variances=vals,
                        residual_variance=residual)
    receipt = dict(train_first=str(returns.index.min().date()), train_last=str(returns.index.max().date()),
        rows=len(returns), securities=n, source=str(SOURCE), source_sha256=sha(SOURCE),
        artifact_sha256=sha(OUT/'frozen_covariance.npz'), shrinkage=float(estimator.shrinkage_),
        factor_variance_share=float(vals.sum()/np.trace(cov)), fits=2,
        missing_estimation='standardized missing returns imputed zero; shrinkage correlation diagonal renormalized',
        risk_only_return_clip=[-.5,.5], clipped_cells=int((np.abs(raw)>.5).sum()),
        unknown_daily_vol=.08, minimum_daily_vol=.01, fit_2026_rows=0,
        purpose='frozen risk model; price-index coordinate, not shareholder-return covariance')
    (OUT/'TRAIN_RECEIPT.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(receipt),flush=True)

class FrozenRisk:
    def __init__(self):
        path=OUT/'frozen_covariance.npz'
        receipt=json.loads((OUT/'TRAIN_RECEIPT.json').read_text(encoding='utf-8'))
        assert sha(path)==receipt['artifact_sha256']
        a=np.load(path,allow_pickle=False)
        self.lookup={t:i for i,t in enumerate(a['tickers'])}
        self.cov=a['covariance']; self.factor=a['factor_covariance']

    def covariance_for(self,names, factor=False):
        source=self.factor if factor else self.cov
        result=np.eye(len(names))*.08**2
        ids=[(i,self.lookup[t]) for i,t in enumerate(names) if t in self.lookup]
        if ids:
            ix,src=zip(*ids)
            result[np.ix_(ix,ix)]=source[np.ix_(src,src)]
        return result

    def optimize(self,day,previous, *, factor=False, downside=False, cost_bps=10):
        top=day.sort_values(['hgb','ticker'],ascending=[False,True],kind='stable').head(20)
        names=top.ticker.astype(str).tolist()
        if not names:return {},{'success':True,'reason':'empty'}
        covariance=self.covariance_for(names,factor=factor)*10
        mu=top.hgb.to_numpy(float)
        penalty=np.maximum(0.,-top.q10.to_numpy(float))*.25 if downside else np.zeros(len(names))
        old=np.asarray([previous.get(t,0.) for t in names])
        seed=np.clip(old,0,.1)
        if seed.sum()>.95:seed*=.95/seed.sum()
        # Auxiliary variables make the L1 turnover cost exact and differentiable.
        n=len(names)
        def objective(x):
            w=x[:n]
            return float(5*w@covariance@w-(mu-penalty)@w+cost_bps/10000*x[n:].sum())
        def gradient(x):
            return np.r_[10*covariance@x[:n]-(mu-penalty),np.repeat(cost_bps/10000,n)]
        constraints=[{'type':'ineq','fun':lambda x:.95-x[:n].sum()},
            {'type':'ineq','fun':lambda x:x[n:]-(x[:n]-old)},
            {'type':'ineq','fun':lambda x:x[n:]+(x[:n]-old)}]
        solved=minimize(objective,np.r_[seed,np.abs(seed-old)],jac=gradient,method='SLSQP',
            bounds=[(0,.1)]*n+[(0,1)]*n,constraints=constraints,
            options={'maxiter':100,'ftol':1e-9})
        valid=solved.success and np.isfinite(solved.x).all() and solved.x[:n].sum()<=.950001
        w=np.maximum(0,solved.x[:n]) if valid else seed
        result={t:float(v) for t,v in zip(names,w) if v>1e-8}
        return result,dict(success=bool(valid),iterations=int(solved.nit),
            fallback='prior-feasible-weights' if not valid else None,
            unknown_risk_names=sum(t not in self.lookup for t in names),
            predicted_10d_variance=float(w@covariance@w),
            top_factor_share=None)

if __name__=='__main__':fit_risk()
