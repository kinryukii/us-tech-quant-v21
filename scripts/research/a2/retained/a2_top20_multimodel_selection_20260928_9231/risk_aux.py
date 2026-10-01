"""Fresh stage-specific risk and diagnostic models; never fit on 2026 inputs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import time

import joblib
import numpy as np
import pandas as pd
from scipy.linalg import eigh
import sklearn
from sklearn.cluster import KMeans
from sklearn.covariance import LedoitWolf
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
PRE = WORK / 'a2_latest_effective_joint_20260927/data/pre2026_joint_context.parquet'
PRICE = WORK / 'a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet'
REGISTRY = WORK / 'a2_latest_effective_joint_20260927/models/model_registry.json'
FEATURES = json.loads(REGISTRY.read_text(encoding='utf-8'))['feature_order']
STAGES = {'validation': '2025-01-01', 'final': '2026-01-01'}
RISK_OUT = ROOT / 'risk_artifacts'
AUX_OUT = ROOT / 'aux_artifacts'
SEED = 20260928
UNKNOWN_VOL = .08


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False,
                                    allow_nan=False), encoding='utf-8')


def cutoff_for(stage):
    if stage not in STAGES:
        raise ValueError(f'Unknown stage: {stage}')
    return pd.Timestamp(STAGES[stage])


def risk_returns(frame, cutoff):
    """Filter BEFORE pivot/tail so future observations cannot affect the window."""
    cutoff = pd.Timestamp(cutoff)
    frame = frame.loc[pd.to_datetime(frame.trade_date).lt(cutoff),
                      ['trade_date', 'ticker', 'close']].copy()
    if frame.empty or frame.duplicated(['trade_date', 'ticker']).any():
        raise ValueError('Empty/duplicate risk source')
    frame['trade_date'] = pd.to_datetime(frame.trade_date)
    wide = frame.pivot(index='trade_date', columns='ticker', values='close').sort_index().tail(253)
    if len(wide) != 253:
        raise ValueError('Risk requires 253 closes for 252 returns')
    if not np.isfinite(wide.to_numpy()[wide.notna().to_numpy()]).all() or (wide <= 0).any().any():
        raise ValueError('Invalid risk close prices')
    returns = wide.pct_change(fill_method=None).iloc[1:]
    returns = returns.loc[:, returns.notna().sum().ge(200)]
    if returns.shape[1] < 5 or returns.index.max() >= cutoff:
        raise ValueError('Invalid risk window or insufficient securities')
    return returns


def sample_auxiliary(frame, cutoff, max_rows=20000):
    """Labels never participate in sampling: only eligible date/ticker keys."""
    selected = frame.loc[pd.to_datetime(frame.signal_date).lt(pd.Timestamp(cutoff)),
                         ['signal_date', 'ticker', *FEATURES]].copy()
    if selected.empty or selected.duplicated(['signal_date', 'ticker']).any():
        raise ValueError('Empty/duplicate auxiliary source')
    keys = selected[['signal_date', 'ticker']].copy()
    keys['signal_date'] = pd.to_datetime(keys.signal_date).dt.strftime('%Y-%m-%d')
    keys['ticker'] = keys.ticker.astype(str)
    selected['_key_hash'] = pd.util.hash_pandas_object(keys, index=False).to_numpy()
    selected = selected.sort_values(['_key_hash', 'signal_date', 'ticker'], kind='stable').head(max_rows)
    selected = selected.drop(columns='_key_hash').sort_values(['signal_date', 'ticker']).reset_index(drop=True)
    if not np.isfinite(selected[FEATURES].to_numpy(float)).all():
        raise ValueError('Nonfinite auxiliary features')
    return selected


def fit_risk(stage, frame=None):
    cutoff = cutoff_for(stage)
    out = RISK_OUT / stage
    artifact = out / 'frozen_covariance.npz'
    if artifact.exists() or (out / 'TRAIN_RECEIPT.json').exists():
        raise FileExistsError(f'Frozen risk exists: {stage}')
    out.mkdir(parents=True, exist_ok=True)
    if frame is None:
        frame = pd.read_parquet(PRICE, columns=['ticker', 'trade_date', 'close'])
    if pd.to_datetime(frame.trade_date).max() >= pd.Timestamp('2026-01-01'):
        raise ValueError('Risk source must be physically pre2026')
    returns = risk_returns(frame, cutoff)
    contract = {
        'stage': stage, 'cutoff_exclusive': str(cutoff.date()),
        'train_first': str(returns.index.min().date()), 'train_last': str(returns.index.max().date()),
        'return_days': len(returns), 'securities': len(returns.columns),
        'source_path': str(PRICE), 'source_sha256': sha(PRICE),
        'recipe': 'LedoitWolf standardized correlation, observed volatility rescaling; top five covariance eigenvectors plus diagonal residual',
        'min_observed_returns': 200, 'minimum_daily_vol': .01, 'unknown_daily_vol': UNKNOWN_VOL,
        'risk_only_return_clip': [-.5, .5], 'missing_estimation': 'standardized missing returns imputed zero',
        'fresh_fit': True, 'hyperparameter_search_trials': 0, 'test_rows_read': 0,
        'created_utc': datetime.now(timezone.utc).isoformat(),
    }
    write_json(out / 'PRE_FIT_CONTRACT.json', contract)
    started = time.monotonic()
    raw = returns.to_numpy(float)
    clipped = np.clip(raw, -.5, .5)
    mean = np.nanmean(clipped, axis=0)
    vol = np.maximum(np.nanstd(clipped, axis=0, ddof=1), .01)
    standardized = np.nan_to_num((clipped - mean) / vol, nan=0.)
    with threadpool_limits(limits=2):
        estimator = LedoitWolf().fit(standardized)
        corr = estimator.covariance_
        diagonal = np.sqrt(np.diag(corr))
        corr = corr / np.outer(diagonal, diagonal)
        covariance = corr * np.outer(vol, vol)
        n = len(vol)
        eigenvalues, eigenvectors = eigh(covariance, subset_by_index=[n - 5, n - 1])
        common = (eigenvectors * eigenvalues) @ eigenvectors.T
        residual = np.maximum(np.diag(covariance - common), 1e-8)
        factor = common + np.diag(residual)
        np.linalg.cholesky(covariance)
        np.linalg.cholesky(factor)
    np.savez_compressed(artifact, tickers=returns.columns.to_numpy(str), covariance=covariance,
                        factor_covariance=factor, factor_loadings=eigenvectors,
                        factor_variances=eigenvalues, residual_variance=residual)
    receipt = {
        **contract, 'status': 'PASS', 'fit_seconds': time.monotonic() - started,
        'estimator_fit_calls': 1, 'pca_decompositions': 1, 'fitted_methods': 2,
        'fit_2026_rows': 0, 'clipped_cells': int((np.abs(raw) > .5).sum()),
        'missing_return_cells': int(np.isnan(raw).sum()), 'shrinkage': float(estimator.shrinkage_),
        'factor_variance_share': float(eigenvalues.sum() / np.trace(covariance)),
        'artifact_path': str(artifact), 'artifact_sha256': sha(artifact),
        'python': platform.python_version(), 'sklearn': sklearn.__version__,
        'price_coordinate': 'research affine index; not certified shareholder total return',
    }
    write_json(out / 'TRAIN_RECEIPT.json', receipt)
    return receipt


def fit_auxiliary(stage, frame=None):
    cutoff = cutoff_for(stage)
    out = AUX_OUT / stage
    artifact = out / 'frozen_auxiliary.joblib'
    if artifact.exists() or (out / 'TRAIN_RECEIPT.json').exists():
        raise FileExistsError(f'Frozen auxiliary exists: {stage}')
    out.mkdir(parents=True, exist_ok=True)
    if frame is None:
        frame = pd.read_parquet(PRE, columns=['signal_date', 'ticker', *FEATURES])
    if pd.to_datetime(frame.signal_date).max() >= pd.Timestamp('2026-01-01'):
        raise ValueError('Auxiliary source must be physically pre2026')
    sampled = sample_auxiliary(frame, cutoff)
    keys = sampled[['signal_date', 'ticker']].to_csv(index=False, lineterminator='\n')
    contract = {
        'stage': stage, 'cutoff_exclusive': str(cutoff.date()),
        'train_first': str(sampled.signal_date.min().date()), 'train_last': str(sampled.signal_date.max().date()),
        'train_rows': len(sampled), 'train_signal_days': int(sampled.signal_date.nunique()),
        'source_path': str(PRE), 'source_sha256': sha(PRE), 'features': FEATURES,
        'sample_key_sha256': hashlib.sha256(keys.encode()).hexdigest(),
        'sampling': 'lowest pandas uint64 hashes of date/ticker only, up to 20000 rows',
        'cluster_parameters': {'n_clusters': 5, 'n_init': 10, 'random_state': SEED},
        'anomaly_parameters': {'n_estimators': 100, 'max_samples': 256, 'contamination': .02,
                               'random_state': SEED, 'n_jobs': 1},
        'fresh_fit': True, 'hyperparameter_search_trials': 0, 'test_rows_read': 0,
        'purpose': 'security state and anomaly diagnostics only; never a trading signal or veto',
        'created_utc': datetime.now(timezone.utc).isoformat(),
    }
    write_json(out / 'PRE_FIT_CONTRACT.json', contract)
    started = time.monotonic()
    with threadpool_limits(limits=2):
        scaler = StandardScaler().fit(sampled[FEATURES].to_numpy(float))
        values = scaler.transform(sampled[FEATURES].to_numpy(float))
        cluster = KMeans(**contract['cluster_parameters']).fit(values)
        anomaly = IsolationForest(**contract['anomaly_parameters']).fit(values)
        clusters = cluster.predict(values)
        scores = anomaly.decision_function(values)
        flags = anomaly.predict(values)
    if not np.isfinite(scores).all():
        raise ValueError('Nonfinite training anomaly scores')
    joblib.dump({'scaler': scaler, 'cluster': cluster, 'anomaly': anomaly,
                 'features': FEATURES, 'stage': stage, 'cutoff_exclusive': str(cutoff.date())},
                artifact, compress=3)
    sampled[['signal_date', 'ticker']].to_parquet(out / 'TRAIN_SAMPLE_KEYS.parquet', index=False)
    receipt = {
        **contract, 'status': 'PASS', 'fit_seconds': time.monotonic() - started,
        'estimator_fit_calls': 2, 'scaler_fit_calls': 1, 'fit_2026_rows': 0,
        'cluster_counts': {str(i): int((clusters == i).sum()) for i in range(5)},
        'training_anomaly_count': int((flags == -1).sum()),
        'artifact_path': str(artifact), 'artifact_sha256': sha(artifact),
        'sample_keys_file_sha256': sha(out / 'TRAIN_SAMPLE_KEYS.parquet'),
        'python': platform.python_version(), 'sklearn': sklearn.__version__,
    }
    write_json(out / 'TRAIN_RECEIPT.json', receipt)
    return receipt


class FrozenRisk:
    def __init__(self, stage='final', *, artifact_root=None):
        cutoff = cutoff_for(stage)
        out = (RISK_OUT if artifact_root is None else Path(artifact_root)) / stage
        self.receipt = json.loads((out / 'TRAIN_RECEIPT.json').read_text(encoding='utf-8'))
        path = out / 'frozen_covariance.npz'
        if self.receipt['stage'] != stage or pd.Timestamp(self.receipt['train_last']) >= cutoff:
            raise ValueError('Risk stage/clock mismatch')
        if self.receipt['artifact_sha256'] != sha(path):
            raise ValueError('Risk artifact hash mismatch')
        with np.load(path, allow_pickle=False) as saved:
            self.lookup = {str(t): i for i, t in enumerate(saved['tickers'])}
            self.cov = saved['covariance'].copy()
            self.factor = saved['factor_covariance'].copy()
        self.stage = stage

    def covariance_for(self, names, factor=False):
        if len(set(names)) != len(names):
            raise ValueError('Duplicate names in covariance request')
        source = self.factor if factor else self.cov
        result = np.eye(len(names)) * UNKNOWN_VOL**2
        positions = [(i, self.lookup[str(t)]) for i, t in enumerate(names) if str(t) in self.lookup]
        if positions:
            requested, saved = zip(*positions)
            result[np.ix_(requested, requested)] = source[np.ix_(saved, saved)]
        return result


class FrozenAuxiliary:
    """Read-only transform/predict interface for diagnostics on any inference year."""
    def __init__(self, stage='final', *, artifact_root=None):
        cutoff = cutoff_for(stage)
        out = (AUX_OUT if artifact_root is None else Path(artifact_root)) / stage
        self.receipt = json.loads((out / 'TRAIN_RECEIPT.json').read_text(encoding='utf-8'))
        path = out / 'frozen_auxiliary.joblib'
        if self.receipt['stage'] != stage or pd.Timestamp(self.receipt['train_last']) >= cutoff:
            raise ValueError('Auxiliary stage/clock mismatch')
        if self.receipt['artifact_sha256'] != sha(path):
            raise ValueError('Auxiliary artifact hash mismatch')
        self.models = joblib.load(path)
        if self.models['stage'] != stage or self.models['features'] != FEATURES:
            raise ValueError('Auxiliary payload stage/features mismatch')
        self.stage = stage

    def transform(self, frame):
        raw = frame[FEATURES].to_numpy(float) if isinstance(frame, pd.DataFrame) else np.asarray(frame, dtype=float)
        if raw.ndim != 2 or raw.shape[1] != len(FEATURES) or not np.isfinite(raw).all():
            raise ValueError('Auxiliary inference requires finite 32-column features')
        index = frame.index if isinstance(frame, pd.DataFrame) else pd.RangeIndex(len(raw))
        if not len(raw):
            return pd.DataFrame(index=index, columns=['cluster', 'anomaly_score', 'is_anomaly'])
        with threadpool_limits(limits=2):
            values = self.models['scaler'].transform(raw)
            cluster = self.models['cluster'].predict(values)
            score = self.models['anomaly'].decision_function(values)
            outlier = self.models['anomaly'].predict(values) == -1
        return pd.DataFrame({'cluster': cluster, 'anomaly_score': score, 'is_anomaly': outlier}, index=index)

    def predict(self, frame):
        return self.transform(frame)


AuxiliaryDiagnostics = FrozenAuxiliary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['all', *STAGES], default='all')
    args = parser.parse_args()
    stages = list(STAGES) if args.stage == 'all' else [args.stage]
    for stage in stages:
        for family, trainer in [('risk', fit_risk), ('auxiliary', fit_auxiliary)]:
            receipt = trainer(stage)
            print(json.dumps({'family': family, 'stage': stage, 'status': receipt['status'],
                              'train_last': receipt['train_last'], 'seconds': receipt['fit_seconds']}), flush=True)


if __name__ == '__main__':
    main()
