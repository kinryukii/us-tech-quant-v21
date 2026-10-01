"""Fresh stage-specific covariance, factor, cluster and anomaly estimators.

Risk math follows the previous risk.py; every stage is now fitted separately.
Auxiliary outputs describe states only and never prescribe trades.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import time

import joblib
import numpy as np
import pandas as pd
from scipy.linalg import eigh
from sklearn.cluster import KMeans
from sklearn.covariance import LedoitWolf
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent/'a2_latest_effective_joint_20260927/data/pre2026_joint_context.parquet'
PRICE_SOURCE = ROOT.parent/'a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet'
FEATURE_AUDIT = ROOT.parent/'a2_latest_effective_joint_20260927/data/JOINT_DATA_AUDIT.json'
FEATURES = json.loads(FEATURE_AUDIT.read_text(encoding='utf-8'))['features']
STAGES = {'validation': '2025-01-01', 'final': '2026-01-01'}
RISK_OUT = ROOT/'risk_artifacts'
AUX_OUT = ROOT/'aux_artifacts'
SEED = 20260928


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def prepare_risk_returns(frame, cutoff):
    """Filter the time boundary before finding the last 252 return sessions."""
    selected = frame.loc[pd.to_datetime(frame.trade_date).lt(cutoff)].copy()
    selected['trade_date'] = pd.to_datetime(selected.trade_date)
    if selected.empty or selected.duplicated(['ticker', 'trade_date']).any():
        raise ValueError('EMPTY_OR_DUPLICATE_RISK_INPUT')
    selected.loc[~np.isfinite(selected.close) | selected.close.le(0), 'close'] = np.nan
    wide = selected.pivot(index='trade_date', columns='ticker', values='close').sort_index().tail(253)
    returns = wide.pct_change(fill_method=None).iloc[1:].replace([np.inf, -np.inf], np.nan)
    if len(returns) != 252:
        raise ValueError('RISK_REQUIRES_252_RETURN_DAYS')
    assert returns.index.max() < pd.Timestamp(cutoff)
    return returns


def estimate_covariance(returns):
    retained = returns.loc[:, returns.notna().sum().ge(200)]
    if retained.empty:
        raise ValueError('NO_SECURITY_WITH_200_RISK_OBSERVATIONS')
    raw = retained.to_numpy(float)
    clipped = np.clip(raw, -.5, .5)
    means = np.nanmean(clipped, axis=0)
    vol = np.maximum(np.nanstd(clipped, axis=0, ddof=1), .01)
    z = np.nan_to_num((clipped-means)/vol, nan=0.)
    estimator = LedoitWolf().fit(z)
    corr = estimator.covariance_
    scale = np.sqrt(np.diag(corr))
    corr = corr / np.outer(scale, scale)
    covariance = corr * np.outer(vol, vol)
    count = len(vol)
    vals, vecs = eigh(covariance, subset_by_index=[max(0, count-5), count-1])
    common = (vecs * vals) @ vecs.T
    residual = np.maximum(np.diag(covariance-common), 1e-8)
    factor = common + np.diag(residual)
    np.linalg.cholesky(covariance)
    np.linalg.cholesky(factor)
    arrays = dict(tickers=retained.columns.to_numpy(str), covariance=covariance,
                  factor_covariance=factor, factor_loadings=vecs,
                  factor_variances=vals, residual_variance=residual)
    details = dict(securities=count, factors=len(vals), shrinkage=float(estimator.shrinkage_),
                   factor_variance_share=float(vals.sum()/np.trace(covariance)),
                   clipped_cells=int((np.abs(raw)>.5).sum()),
                   risk_only_return_clip=[-.5, .5], minimum_daily_vol=.01,
                   unknown_daily_vol=.08,
                   missing_estimation='standardized missing returns imputed zero; shrinkage correlation diagonal renormalized')
    return arrays, details


def sample_aux_rows(frame, cutoff, max_rows=20000):
    selected = frame.loc[pd.to_datetime(frame.signal_date).lt(cutoff),
                         ['signal_date', 'ticker', *FEATURES]].copy()
    selected['signal_date'] = pd.to_datetime(selected.signal_date)
    if selected.empty or selected.duplicated(['signal_date', 'ticker']).any():
        raise ValueError('EMPTY_OR_DUPLICATE_AUX_INPUT')
    if not np.isfinite(selected[FEATURES].to_numpy(float)).all():
        raise ValueError('NONFINITE_AUX_FEATURE')
    # Stable key-based hash; no returns, labels, model scores or future prices.
    keys = selected.signal_date.dt.strftime('%Y-%m-%d') + '|' + selected.ticker.astype(str) + f'|{SEED}'
    selected['_sample_hash'] = pd.util.hash_pandas_object(keys, index=False).to_numpy()
    selected = selected.sort_values(['_sample_hash', 'signal_date', 'ticker'], kind='stable').head(max_rows)
    return selected.drop(columns='_sample_hash').sort_values(['signal_date', 'ticker']).reset_index(drop=True)


def fit_stage(stage, frame, prices):
    cutoff = STAGES[stage]
    risk_dir, aux_dir = RISK_OUT/stage, AUX_OUT/stage
    if risk_dir.exists() or aux_dir.exists():
        raise RuntimeError(f'PRESERVE_EXISTING_FIT:{stage}')
    risk_dir.mkdir(parents=True)
    aux_dir.mkdir(parents=True)
    common = dict(stage=stage, cutoff_exclusive=cutoff, fit_2026_rows=0, fit_reused=False,
                  experiment_contract_sha256=sha(ROOT/'EXPERIMENT_CONTRACT.md'),
                  implementation_sha256=sha(__file__), seed=SEED)
    before = time.monotonic()
    returns = prepare_risk_returns(prices, cutoff)
    with threadpool_limits(limits=2):
        arrays, details = estimate_covariance(returns)
    artifact = risk_dir/'frozen_covariance.npz'
    np.savez_compressed(artifact, **arrays)
    receipt = dict(**common, **details, status='PASS', fit_calls=2,
                   fit_methods=['LedoitWolf', '5-leading-eigenvector-factor-model'],
                   source=str(PRICE_SOURCE), source_sha256=sha(PRICE_SOURCE),
                   train_first=str(returns.index.min().date()), train_last=str(returns.index.max().date()),
                   rows=len(returns), artifact_sha256=sha(artifact),
                   fit_seconds=time.monotonic()-before,
                   purpose='frozen risk model; price-index coordinate, not shareholder-return covariance')
    write(risk_dir/'TRAIN_RECEIPT.json', receipt)
    before = time.monotonic()
    sample = sample_aux_rows(frame, cutoff)
    keys_path = aux_dir/'sample_keys.parquet'
    sample[['signal_date', 'ticker']].to_parquet(keys_path, index=False)
    values = sample[FEATURES].to_numpy(float)
    scaler = StandardScaler()
    cluster = KMeans(n_clusters=5, n_init=10, random_state=SEED)
    anomaly = IsolationForest(n_estimators=100, max_samples=256, contamination=.02,
                              random_state=SEED, n_jobs=1)
    with threadpool_limits(limits=2):
        standardized = scaler.fit_transform(values)
        cluster.fit(standardized)
        anomaly.fit(standardized)
    artifact = aux_dir/'auxiliary.joblib'
    joblib.dump(dict(stage=stage, cutoff_exclusive=cutoff, feature_order=FEATURES,
                     scaler=scaler, cluster=cluster, anomaly=anomaly), artifact, compress=3)
    receipt = dict(**common, status='PASS', fit_calls=2, scaler_fit_calls=1,
                   source=str(SOURCE), source_sha256=sha(SOURCE), rows=len(sample),
                   train_days=int(sample.signal_date.nunique()),
                   train_first=str(sample.signal_date.min().date()), train_last=str(sample.signal_date.max().date()),
                   feature_order=FEATURES, sample_keys_sha256=sha(keys_path),
                   sampling='lowest deterministic hash of date|ticker|20260928, at most 20000 rows',
                   cluster_parameters=dict(n_clusters=5, n_init=10, random_state=SEED),
                   anomaly_parameters=dict(n_estimators=100, max_samples=256, contamination=.02,
                                           random_state=SEED, n_jobs=1),
                   artifact_sha256=sha(artifact), fit_seconds=time.monotonic()-before,
                   role='state and quality diagnosis only; no trading signal or veto', test_rows_read=0)
    write(aux_dir/'TRAIN_RECEIPT.json', receipt)
    return dict(stage=stage, risk_securities=details['securities'], risk_days=len(returns),
                risk_last=str(returns.index.max().date()), auxiliary_rows=len(sample),
                auxiliary_last=str(sample.signal_date.max().date()), fit_2026_rows=0)


class FrozenRisk:
    def __init__(self, stage='final'):
        cutoff = STAGES[stage]
        directory = RISK_OUT/stage
        path = directory/'frozen_covariance.npz'
        receipt = json.loads((directory/'TRAIN_RECEIPT.json').read_text(encoding='utf-8'))
        if receipt['stage'] != stage or receipt['cutoff_exclusive'] != cutoff:
            raise ValueError('RISK_STAGE_MISMATCH')
        if pd.Timestamp(receipt['train_last']) >= pd.Timestamp(cutoff) or receipt['fit_2026_rows'] != 0:
            raise ValueError('RISK_TIME_BOUNDARY')
        if sha(path) != receipt['artifact_sha256']:
            raise ValueError('RISK_ARTIFACT_HASH_MISMATCH')
        with np.load(path, allow_pickle=False) as arrays:
            self.lookup = {ticker: index for index, ticker in enumerate(arrays['tickers'])}
            self.cov = arrays['covariance'].copy()
            self.factor = arrays['factor_covariance'].copy()
        self.stage = stage

    def covariance_for(self, names, factor=False):
        if len(set(names)) != len(names):
            raise ValueError('DUPLICATE_RISK_NAMES')
        source = self.factor if factor else self.cov
        result = np.eye(len(names))*.08**2
        ids = [(index, self.lookup[ticker]) for index, ticker in enumerate(names) if ticker in self.lookup]
        if ids:
            target, known = zip(*ids)
            result[np.ix_(target, target)] = source[np.ix_(known, known)]
        return result


@lru_cache(maxsize=2)
def _load_aux(stage):
    cutoff = STAGES[stage]
    directory = AUX_OUT/stage
    path = directory/'auxiliary.joblib'
    receipt = json.loads((directory/'TRAIN_RECEIPT.json').read_text(encoding='utf-8'))
    if receipt['stage'] != stage or receipt['cutoff_exclusive'] != cutoff:
        raise ValueError('AUX_STAGE_MISMATCH')
    if pd.Timestamp(receipt['train_last']) >= pd.Timestamp(cutoff) or receipt['fit_2026_rows'] != 0:
        raise ValueError('AUX_TIME_BOUNDARY')
    if sha(path) != receipt['artifact_sha256']:
        raise ValueError('AUX_ARTIFACT_HASH_MISMATCH')
    model = joblib.load(path)
    if model['stage'] != stage or model['feature_order'] != FEATURES:
        raise ValueError('AUX_MODEL_CONTRACT_MISMATCH')
    return model


def aux_predict(frame, stage='final'):
    model = _load_aux(stage)
    values = frame[FEATURES].to_numpy(float)
    if not np.isfinite(values).all():
        raise ValueError('NONFINITE_AUX_PREDICTION_FEATURE')
    result = frame[[column for column in ['signal_date', 'ticker'] if column in frame]].copy()
    if len(frame) == 0:
        return result.assign(state_cluster=pd.Series(dtype='int64'),
                             anomaly_score=pd.Series(dtype='float64'), is_anomaly=pd.Series(dtype='bool'))
    standardized = model['scaler'].transform(values)
    result['state_cluster'] = model['cluster'].predict(standardized)
    result['anomaly_score'] = model['anomaly'].decision_function(standardized)
    result['is_anomaly'] = result.anomaly_score.lt(0)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['validation', 'final', 'all'], default='all')
    stage = parser.parse_args().stage
    frame = pd.read_parquet(SOURCE, columns=['signal_date', 'ticker', *FEATURES])
    prices = pd.read_parquet(PRICE_SOURCE, columns=['ticker', 'trade_date', 'close'])
    if not frame.signal_date.lt('2026-01-01').all() or not prices.trade_date.lt('2026-01-01').all():
        raise ValueError('PHYSICAL_TRAINING_SOURCE_CONTAINS_2026')
    source_hashes = {str(path): sha(path) for path in [SOURCE, PRICE_SOURCE, ROOT/'EXPERIMENT_CONTRACT.md']}
    for name in STAGES if stage == 'all' else [stage]:
        print(json.dumps(fit_stage(name, frame, prices)), flush=True)
    if any(sha(path) != digest for path, digest in source_hashes.items()):
        raise RuntimeError('TRAINING_INPUT_CHANGED_DURING_FIT')


if __name__ == '__main__':
    main()
