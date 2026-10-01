"""Chronological stacking of fresh linear, tree, quantile and MLP predictions.

Only frozen base outputs and observable state enter the meta feature matrix.
Outcome labels are deliberately absent from all inference interfaces.
"""
from pathlib import Path
import json

import joblib
import numpy as np
import pandas as pd
from scipy.special import expit
import torch

import values as v
from neural import JointPolicy, FEATURES as NEURAL_FEATURES

ROOT = Path(__file__).resolve().parent
OUT = ROOT/'ensemble_artifacts/meta'
BASE_CUTOFFS = {'early': '2024-01-01', 'validation': '2025-01-01', 'final': '2026-01-01'}
STAGES = {'validation': '2025-01-01', 'final': '2026-01-01'}
META_FEATURES = [*[f'base_{name}' for name in v.NAMES], 'mlp_logit', 'mlp_preference',
                 'action_times_mlp_logit', 'action_times_mlp_preference',
                 'negative_squared_action_preference_distance',
                 'current_weight', 'cash_weight', 'age_fraction', 'action_weight',
                 'action_squared', 'absolute_turnover', 'signed_turnover']


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def checked_path(path, expected):
    path = Path(path)
    if v.sha(path) != expected:
        raise RuntimeError(f'ENSEMBLE_DEPENDENCY_HASH_MISMATCH:{path}')
    return path


def require_preboundary(record, boundary, names):
    for name in names:
        value = pd.Timestamp(record[name])
        if pd.isna(value) or value >= pd.Timestamp(boundary):
            raise RuntimeError(f'BASE_PREDICTOR_TIME_LEAKAGE:{name}:{record[name]}:{boundary}')


def meta_feature_matrix(predictions, logits, current, cash, age, action):
    """Unit differences are handled later by the stage-specific fitted scaler."""
    predictions = np.asarray(predictions, float)
    logits, current, cash, age, action = [np.asarray(x, float).reshape(-1)
                                        for x in [logits, current, cash, age, action]]
    count = len(logits)
    if predictions.shape != (count, len(v.NAMES)) or any(len(x) != count for x in [current, cash, age, action]):
        raise ValueError('STACKED_FEATURE_LENGTH_MISMATCH')
    preference = .1*expit(logits)
    matrix = np.column_stack([predictions, logits, preference, action*logits, action*preference,
                              -(action-preference)**2, current, cash, np.minimum(age,252)/252,
                              action, action**2, np.abs(action-current), action-current])
    if matrix.shape != (count, len(META_FEATURES)) or not np.isfinite(matrix).all():
        raise ValueError('INVALID_STACKED_FEATURE_MATRIX')
    return matrix


class BaseBundle:
    """Load only the explicitly named chronological base stage, with receipts."""
    def __init__(self, stage):
        boundary = BASE_CUTOFFS[stage]
        early = stage == 'early'
        value_dir = ROOT/'ensemble_artifacts/early_values' if early else ROOT/'value_artifacts'
        neural_dir = ROOT/'ensemble_artifacts/early_neural' if early else ROOT/'neural_artifacts'
        value_receipt_path = value_dir/'FIT_RECEIPT.json'
        neural_receipt_path = neural_dir/'TRAIN_RECEIPT.json'
        vr, nr = read(value_receipt_path), read(neural_receipt_path)
        if vr['status'] != 'PASS' or vr['fit_2026_rows'] != 0 or nr['fit_2026_rows'] != 0:
            raise RuntimeError('BASE_RECEIPT_NOT_COMPLETE_OR_NOT_PRE2026')
        self.stage, self.boundary, self.models = stage, boundary, {}
        self.hashes = {str(p): v.sha(p) for p in [value_receipt_path, neural_receipt_path]}
        self.predictor_clocks = []
        for name in v.NAMES:
            records = [r for r in vr['fits'] if r['name'] == name and r['stage'] == stage]
            if len(records) != 1 or not records[0]['converged']:
                raise RuntimeError(f'MISSING_OR_UNCONVERGED_BASE:{stage}:{name}')
            record = records[0]
            require_preboundary(record, boundary, ['train_signal_max', 'train_label_end_max'])
            path = checked_path(record['artifact'], record['artifact_sha256'])
            self.hashes[str(path)] = record['artifact_sha256']
            self.models[name] = joblib.load(path)
            self.predictor_clocks.append(dict(name=name, stage=stage,
                signal_max=record['train_signal_max'], label_end_max=record['train_label_end_max'],
                cutoff_exclusive=boundary))
        models = [r for r in nr['artifacts'] if r['method'] == 'direct' and r['stage'] == stage]
        norms = [r for r in nr['stages'] if r['stage'] == stage]
        if len(models) != 1 or len(norms) != 1:
            raise RuntimeError(f'MISSING_DIRECT_MLP_OR_NORMALIZER:{stage}')
        model, norm = models[0], norms[0]
        require_preboundary(model, boundary, ['fit_signal_max', 'fit_label_end_max', 'consumed_price_max'])
        require_preboundary(norm['normalization'], boundary, ['signal_max', 'label_end_max'])
        if list(nr['specification']['feature_order']) != list(v.FEATURES) or list(NEURAL_FEATURES) != list(v.FEATURES):
            raise RuntimeError('STACKING_BASE_FEATURE_ORDER_MISMATCH')
        path = checked_path(model['path'], model['sha256'])
        normalizer = checked_path(norm['normalization_path'], norm['normalization_sha256'])
        self.hashes[str(path)] = model['sha256']
        self.hashes[str(normalizer)] = norm['normalization_sha256']
        with np.load(normalizer, allow_pickle=False) as arrays:
            self.mean, self.scale = arrays['mean'].copy(), arrays['scale'].copy()
        if not np.isfinite(self.mean).all() or not np.isfinite(self.scale).all() or not (self.scale > 0).all():
            raise RuntimeError('INVALID_STACKING_BASE_NORMALIZER')
        self.neural = JointPolicy()
        self.neural.load_state_dict(torch.load(path, weights_only=True, map_location='cpu'))
        self.neural.eval()
        self.predictor_clocks.append(dict(name='direct_mlp', stage=stage,
            signal_max=model['fit_signal_max'], label_end_max=model['fit_label_end_max'],
            price_max=model['consumed_price_max'], normalizer=norm['normalization'],
            cutoff_exclusive=boundary))

    def matrix(self, x, current, cash, age, action):
        x = np.asarray(x, float)
        current, cash, age, action = [np.asarray(a, float).reshape(-1) for a in [current,cash,age,action]]
        features = v.mapped_features(x, current, cash, age, action)
        predictions = np.column_stack([v.predict_values(self.models[name], name, features) for name in v.NAMES])
        normalized = np.clip((x-self.mean)/self.scale, -8, 8)
        obs = torch.tensor(np.column_stack([normalized,current,cash,current>0]), dtype=torch.float32)
        with torch.no_grad():
            logits = self.neural(obs).numpy()
        return meta_feature_matrix(predictions, logits, current, cash, age, action)


class StackedPolicy:
    def __init__(self, stage='final'):
        cutoff = STAGES[stage]
        receipt = read(OUT/'FIT_RECEIPT.json')
        if receipt['status'] != 'PASS' or receipt['fit_2026_rows'] != 0:
            raise RuntimeError('META_RECEIPT_NOT_COMPLETE')
        records = [r for r in receipt['fits'] if r['stage'] == stage]
        if len(records) != 1:
            raise RuntimeError('MISSING_STAGE_META_MODEL')
        record = records[0]
        require_preboundary(record, cutoff, ['train_signal_max', 'train_label_end_max'])
        if record['feature_order'] != META_FEATURES:
            raise RuntimeError('META_FEATURE_ORDER_MISMATCH')
        self.model = joblib.load(checked_path(record['artifact'],record['artifact_sha256']))
        self.base = BaseBundle(stage)
        if self.base.hashes != receipt['inference_dependencies'][stage]:
            raise RuntimeError('STACKED_INFERENCE_BASE_CHANGED')
        self.stage = stage

    def score_actions(self, day, current_array, cash, age_array):
        n = len(day)
        if len(current_array) != n or len(age_array) != n:
            raise ValueError('STACKED_STATE_LENGTH_MISMATCH')
        if not n:
            return np.empty((0,5), dtype=float)
        matrix = self.base.matrix(np.repeat(day[v.FEATURES].to_numpy(float),5,axis=0),
            np.repeat(current_array,5), np.full(n*5,float(cash)), np.repeat(age_array,5), np.tile(v.ACTIONS,n))
        scores = self.model.predict(matrix).reshape(n,5)
        if not np.isfinite(scores).all():
            raise RuntimeError('NONFINITE_STACKED_ACTION_SCORE')
        return scores


def verify_ensemble_artifacts():
    """Read-only hash/date audit of the 7 early values, 1 MLP and 2 meta fits."""
    receipt = read(OUT/'FIT_RECEIPT.json')
    if receipt['status'] != 'PASS' or receipt['fit_2026_rows'] != 0 or receipt['meta_fit_calls'] != 2:
        raise RuntimeError('META_COMPLETION_RECEIPT_FAILED')
    checked = set()
    for path, digest in receipt['input_sha256'].items():
        checked_path(path,digest);checked.add(str(path))
    checked_path(OUT/'PRE_FIT_CONTRACT.json',receipt['pre_fit_contract_sha256'])
    stages=[]
    for stage,cutoff in STAGES.items():
        record=next(r for r in receipt['fits'] if r['stage']==stage)
        require_preboundary(record,cutoff,['train_signal_max','train_label_end_max'])
        expected_years=[2024] if stage=='validation' else [2024,2025]
        if record['oof_years']!=expected_years or record['feature_order']!=META_FEATURES:
            raise RuntimeError('META_STAGE_OR_FEATURE_CONTRACT_MISMATCH')
        checked_path(record['artifact'],record['artifact_sha256']);checked.add(record['artifact'])
        stages.append(dict(stage=stage,rows=record['train_rows'],
                           stock_date_rows=record['independent_stock_date_rows'],
                           label_end_max=record['train_label_end_max']))
    for year in [2024,2025]:
        audit=receipt['oof_sampling'][str(year)]
        checked_path(audit['sample_keys_path'],audit['sample_keys_sha256'])
        checked_path(audit['matrix_path'],audit['matrix_sha256'])
        checked.update([audit['sample_keys_path'],audit['matrix_path']])
        keys=pd.read_parquet(audit['sample_keys_path'])
        if keys.duplicated(['signal_date','ticker']).any() or len(keys)>6000:
            raise RuntimeError('OOF_SAMPLE_KEYS_INVALID')
        if not keys.signal_date.dt.year.eq(year).all() or not keys.label_end_date.lt(f'{year+1}-01-01').all():
            raise RuntimeError('OOF_SAMPLE_TIME_BOUNDARY')
        if keys.signal_date.nunique()!=audit['eligible_dates']:
            raise RuntimeError('OOF_MATURE_DATE_COVERAGE_LOST')
        with np.load(audit['matrix_path'],allow_pickle=False) as matrix:
            if matrix['features'].shape!=(len(keys)*15,len(META_FEATURES)) or matrix['target'].shape!=(len(keys)*15,):
                raise RuntimeError('OOF_MATRIX_SHAPE_CHANGED')
            if matrix['feature_order'].tolist()!=META_FEATURES or not np.isfinite(matrix['features']).all() or not np.isfinite(matrix['target']).all():
                raise RuntimeError('OOF_MATRIX_FEATURE_CONTRACT')
        for clock in receipt['oof_predictor_clocks'][str(year)]:
            require_preboundary(clock,f'{year}-01-01',['signal_max','label_end_max'])
    early_values=read(ROOT/'ensemble_artifacts/early_values/FIT_RECEIPT.json')
    early_neural=read(ROOT/'ensemble_artifacts/early_neural/TRAIN_RECEIPT.json')
    if len(early_values['fits'])!=7 or len(early_neural['artifacts'])!=1:
        raise RuntimeError('EARLY_FIT_COUNT_MISMATCH')
    for record in early_values['fits']:
        require_preboundary(record,'2024-01-01',['train_signal_max','train_label_end_max'])
        checked_path(record['artifact'],record['artifact_sha256']);checked.add(record['artifact'])
    for record in early_neural['artifacts']:
        require_preboundary(record,'2024-01-01',['fit_signal_max','fit_label_end_max','consumed_price_max'])
        checked_path(record['path'],record['sha256']);checked.add(record['path'])
        checked_path(record['zero_path'],record['zero_sha256']);checked.add(record['zero_path'])
        checked_path(record['last_episode_path'],record['last_episode_sha256']);checked.add(record['last_episode_path'])
    for record in early_neural['stages']:
        require_preboundary(record['normalization'],'2024-01-01',['signal_max','label_end_max'])
        checked_path(record['normalization_path'],record['normalization_sha256'])
    return dict(status='PASS',early_supervised_fits=7,early_neural_fits=1,meta_fits=2,
                new_ensemble_training_fits=10,unique_hashes_checked=len(checked),
                fit_2026_rows=0,oof_years=[2024,2025],stages=stages)
