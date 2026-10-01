"""Frozen-expert static and conditional action-utility stacking.

M0 and M1 share 12 existing expert features, five existing action basis terms,
four observable states, and one train-only date-weighted main scaler. M1 adds
only the 48 expert-by-state products. Coefficients convert heterogeneous
outputs into action utility; they are never portfolio funding percentages.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
OLD_ROOT = ROOT.parent / 'a2_multimodel_joint_20260928'
OUT = ROOT / 'meta_artifacts'
EXPERT_FEATURES = ['base_ridge', 'base_elastic_net', 'base_logistic', 'base_hgb',
    'base_q10', 'base_q50', 'base_q90', 'mlp_logit', 'mlp_preference',
    'action_times_mlp_logit', 'action_times_mlp_preference',
    'negative_squared_action_preference_distance']
BASIS_FEATURES = ['age_fraction', 'action_weight', 'action_squared',
                  'absolute_turnover', 'signed_turnover']
STATE_FEATURES = ['cash_weight', 'current_weight', 'available_slots', 'realized_vol_20d']
MAIN_FEATURES = EXPERT_FEATURES + BASIS_FEATURES + STATE_FEATURES
INTERACTION_FEATURES = [f'{expert}__times__{state}'
                        for expert in EXPERT_FEATURES for state in STATE_FEATURES]
STAGE_CUTOFFS = {'validation': '2025-01-01', 'final': '2026-01-01'}
ALPHA_MAIN = 100.
INTERACTION_MULTIPLIERS = (4., 16., 64.)
CHUNK_ROWS = 32768


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def checked_path(path, digest):
    path = Path(path)
    if sha(path) != digest:
        raise RuntimeError(f'CONTEXTUAL_ARTIFACT_HASH_MISMATCH:{path}')
    return path


def scaler_array_sha256(scaler):
    digest = hashlib.sha256()
    digest.update(json.dumps(scaler.feature_order,ensure_ascii=False).encode('utf-8'))
    for name in ('mean_','scale_','var_','min_','max_'):
        digest.update(np.ascontiguousarray(getattr(scaler,name),dtype='<f8').tobytes())
    return digest.hexdigest()


def _chunks(length):
    for start in range(0, length, CHUNK_ROWS):
        yield start, min(start + CHUNK_ROWS, length)


def _validated_inputs(p, z, basis):
    arrays = [np.asarray(a, dtype=float) for a in (p, z, basis)]
    length = len(arrays[0])
    for array, width in zip(arrays, (12, 4, 5)):
        if array.shape != (length, width) or not np.isfinite(array).all():
            raise ValueError('INVALID_CONTEXTUAL_INPUT_SHAPE_OR_VALUE')
    return arrays


def main_matrix(p, z, basis):
    p, z, basis = _validated_inputs(p, z, basis)
    return np.column_stack([p, basis, z])


def date_equal_weights(row_dates, allowed=None, base_weights=None):
    """Normalize each date to one, preserving supplied within-date path weights."""
    dates = np.asarray(row_dates).reshape(-1)
    feasible = np.ones(len(dates), bool) if allowed is None else np.asarray(allowed, bool).reshape(-1)
    if len(feasible) != len(dates) or not feasible.any():
        raise ValueError('EMPTY_OR_INVALID_DATE_WEIGHT_MASK')
    _, inverse = np.unique(dates, return_inverse=True)
    base = feasible.astype(float) if base_weights is None else np.asarray(base_weights, float).reshape(-1).copy()
    if len(base) != len(dates) or not np.isfinite(base).all() or (base < 0).any():
        raise ValueError('INVALID_BASE_DATE_WEIGHT')
    base[~feasible] = 0.
    counts = np.bincount(inverse, weights=base)
    if ((counts[inverse[feasible]] <= 0) | (base[feasible] <= 0)).any():
        raise ValueError('FEASIBLE_ROW_ZERO_WEIGHT')
    weights = np.zeros(len(dates), float)
    weights[feasible] = base[feasible] / counts[inverse[feasible]]
    return weights


@dataclass
class WeightedScaler:
    feature_order: list[str]
    mean_: np.ndarray
    scale_: np.ndarray
    var_: np.ndarray
    min_: np.ndarray
    max_: np.ndarray
    weight_sum_: float
    positive_rows_: int

    @classmethod
    def fit_chunks(cls, length, read_chunk, weights, feature_order):
        weights = np.asarray(weights, float).reshape(-1)
        if len(weights) != length or not np.isfinite(weights).all() or (weights < 0).any():
            raise ValueError('INVALID_SCALER_WEIGHTS')
        total = float(weights.sum())
        if total <= 0:
            raise ValueError('ZERO_SCALER_WEIGHT')
        width = len(feature_order)
        weighted_sum = np.zeros(width)
        minimum, maximum = np.full(width, np.inf), np.full(width, -np.inf)
        for start, stop in _chunks(length):
            values = np.asarray(read_chunk(start, stop), float)
            if values.shape != (stop-start, width) or not np.isfinite(values).all():
                raise ValueError('INVALID_SCALER_CHUNK')
            w = weights[start:stop]
            weighted_sum += (values * w[:, None]).sum(axis=0)
            if (w > 0).any():
                selected = values[w > 0]
                minimum = np.minimum(minimum, selected.min(axis=0))
                maximum = np.maximum(maximum, selected.max(axis=0))
        mean = weighted_sum / total
        variance_sum = np.zeros(width)
        for start, stop in _chunks(length):
            centered = np.asarray(read_chunk(start, stop), float) - mean
            variance_sum += (centered**2 * weights[start:stop, None]).sum(axis=0)
        variance = np.maximum(variance_sum / total, 0.)
        constant = minimum == maximum
        variance[constant] = 0.
        mean[constant] = minimum[constant]
        scale = np.sqrt(variance)
        scale[scale <= np.finfo(float).eps] = 1.
        return cls(list(feature_order), mean, scale, variance, minimum, maximum,
                   total, int(np.count_nonzero(weights)))

    def transform(self, matrix):
        matrix = np.asarray(matrix, float)
        if matrix.ndim != 2 or matrix.shape[1] != len(self.mean_):
            raise ValueError('SCALER_WIDTH_MISMATCH')
        return (matrix - self.mean_) / self.scale_

    def state(self):
        return dict(feature_order=self.feature_order, mean=self.mean_.tolist(),
            scale=self.scale_.tolist(), variance=self.var_.tolist(),
            minimum=self.min_.tolist(), maximum=self.max_.tolist(),
            weight_sum=self.weight_sum_, positive_rows=self.positive_rows_)


def fit_scalers(p, z, basis, weights):
    p, z, basis = _validated_inputs(p, z, basis)
    main_reader = lambda start, stop: np.column_stack([p[start:stop], basis[start:stop], z[start:stop]])
    main = WeightedScaler.fit_chunks(len(p), main_reader, weights, MAIN_FEATURES)

    def interactions(start, stop):
        normalized = main.transform(main_reader(start, stop))
        return (normalized[:, :12, None] * normalized[:, None, 17:21]).reshape(-1, 48)

    interaction = WeightedScaler.fit_chunks(len(p), interactions, weights, INTERACTION_FEATURES)
    return main, interaction


@dataclass
class FittedMeta:
    kind: str
    stage: str
    main_scaler: WeightedScaler
    interaction_scaler: WeightedScaler
    coefficients: np.ndarray
    intercept: float
    alpha_main: float
    interaction_multiplier: float
    metadata: dict

    @property
    def feature_order(self):
        return MAIN_FEATURES + (INTERACTION_FEATURES if self.kind == 'M1' else [])

    def design_chunk(self, p, z, basis):
        normalized = self.main_scaler.transform(main_matrix(p, z, basis))
        if self.kind == 'M0':
            return normalized
        product = (normalized[:, :12, None] * normalized[:, None, 17:21]).reshape(-1, 48)
        return np.column_stack([normalized, self.interaction_scaler.transform(product)])

    def predict(self, p, z, basis):
        p, z, basis = _validated_inputs(p, z, basis)
        result = np.empty(len(p), float)
        for start, stop in _chunks(len(p)):
            design = self.design_chunk(p[start:stop], z[start:stop], basis[start:stop])
            result[start:stop] = self.intercept + design @ self.coefficients
        if not np.isfinite(result).all():
            raise RuntimeError('NONFINITE_CONTEXTUAL_PREDICTION')
        return result

    def effective_coefficients(self, z):
        """Derivatives for standardized and raw p, including product scaling."""
        z = np.asarray(z, float)
        if z.ndim == 1:
            z = z[None, :]
        if z.ndim != 2 or z.shape[1] != 4 or not np.isfinite(z).all():
            raise ValueError('INVALID_EFFECTIVE_COEFFICIENT_STATE')
        state = (z-self.main_scaler.mean_[17:21]) / self.main_scaler.scale_[17:21]
        standardized = np.broadcast_to(self.coefficients[:12], (len(z), 12)).copy()
        if self.kind == 'M1':
            gamma = (self.coefficients[21:] / self.interaction_scaler.scale_).reshape(12, 4)
            standardized += state @ gamma.T
        raw = standardized / self.main_scaler.scale_[:12]
        return dict(standardized=standardized, raw=raw)

    def diagnostic_frame(self, p, z, basis):
        p, z, basis = _validated_inputs(p, z, basis)
        values = main_matrix(p, z, basis)
        normalized = self.main_scaler.transform(values)
        effective = self.effective_coefficients(z)
        prediction = self.predict(p, z, basis)
        main_value = self.intercept + normalized @ self.coefficients[:21]
        if self.kind == 'M1':
            # Product centering shifts the conditional intercept as well as slopes.
            centering = -float((self.coefficients[21:] *
                self.interaction_scaler.mean_ / self.interaction_scaler.scale_).sum())
        else:
            centering = 0.
        expert_contributions = normalized[:, :12] * effective['standardized']
        basis_contribution = normalized[:, 12:17] @ self.coefficients[12:17]
        state_contribution = normalized[:, 17:21] @ self.coefficients[17:21]
        decomposition = self.intercept + centering + expert_contributions.sum(axis=1) + basis_contribution + state_contribution
        if not np.allclose(prediction, decomposition, rtol=1e-10, atol=1e-12):
            raise RuntimeError('CONTEXTUAL_CONTRIBUTION_RECONCILIATION')
        columns = {name: values[:, index] for index, name in enumerate(MAIN_FEATURES)}
        columns.update(prediction_utility=prediction, main_utility=main_value,
            interaction_utility=prediction-main_value,
            conditional_intercept=np.full(len(p), self.intercept+centering),
            basis_contribution=basis_contribution, state_contribution=state_contribution,
            any_main_out_of_range=((values < self.main_scaler.min_) | (values > self.main_scaler.max_)).any(axis=1),
            any_state_out_of_range=((z < self.main_scaler.min_[17:21]) | (z > self.main_scaler.max_[17:21])).any(axis=1))
        for index, expert in enumerate(EXPERT_FEATURES):
            columns[f'effective_standardized_{expert}'] = effective['standardized'][:, index]
            columns[f'effective_raw_{expert}'] = effective['raw'][:, index]
            columns[f'contribution_{expert}'] = expert_contributions[:, index]
        for index, state in enumerate(STATE_FEATURES):
            columns[f'out_of_range_{state}'] = (z[:, index] < self.main_scaler.min_[17+index]) | (z[:, index] > self.main_scaler.max_[17+index])
        return pd.DataFrame(columns)


def fit_meta(kind, stage, p, z, basis, target, row_dates, allowed, main_scaler,
             interaction_scaler, interaction_multiplier=0., metadata=None, sample_weight=None):
    """One weighted ridge solve. The unpenalized intercept is fitted jointly."""
    if kind not in ('M0', 'M1') or stage not in ('internal', 'validation', 'final'):
        raise ValueError('INVALID_CONTEXTUAL_FIT_IDENTITY')
    if kind == 'M1' and interaction_multiplier not in INTERACTION_MULTIPLIERS:
        raise ValueError('UNPLANNED_INTERACTION_PENALTY')
    p, z, basis = _validated_inputs(p, z, basis)
    target = np.asarray(target, float).reshape(-1)
    dates = np.asarray(row_dates).reshape(-1)
    if len(target) != len(p) or len(dates) != len(p) or not np.isfinite(target).all():
        raise ValueError('INVALID_CONTEXTUAL_TARGET_OR_DATE')
    # This guard is repeated here so callers cannot bypass train_meta chronology.
    cutoff = '2024-10-01' if stage == 'internal' else STAGE_CUTOFFS[stage]
    if (pd.to_datetime(dates) >= pd.Timestamp(cutoff)).any():
        raise RuntimeError('CONTEXTUAL_FIT_SIGNAL_TIME_LEAKAGE')
    if metadata and 'train_label_end_max' in metadata and pd.Timestamp(metadata['train_label_end_max']) >= pd.Timestamp(cutoff):
        raise RuntimeError('CONTEXTUAL_FIT_LABEL_MATURITY_LEAKAGE')
    years = set(pd.to_datetime(dates).year)
    if not years.issubset({2024} if stage in ('internal', 'validation') else {2024, 2025}):
        raise RuntimeError('CONTEXTUAL_FIT_UNPLANNED_YEAR')
    weights = date_equal_weights(dates, allowed, sample_weight)
    if not np.isclose(main_scaler.weight_sum_, weights.sum(), rtol=1e-10, atol=1e-10):
        raise RuntimeError('CONTEXTUAL_SCALER_WEIGHT_POPULATION_MISMATCH')
    width = 21 if kind == 'M0' else 69
    model = FittedMeta(kind, stage, main_scaler, interaction_scaler,
        np.zeros(width), 0., ALPHA_MAIN, float(interaction_multiplier), dict(metadata or {}))
    gram, rhs = np.zeros((width+1, width+1)), np.zeros(width+1)
    for start, stop in _chunks(len(p)):
        design = model.design_chunk(p[start:stop], z[start:stop], basis[start:stop])
        augmented = np.column_stack([np.ones(stop-start), design])
        weighted = augmented * weights[start:stop, None]
        gram += augmented.T @ weighted
        rhs += weighted.T @ target[start:stop]
    penalties = np.r_[0., np.full(21, ALPHA_MAIN),
        np.full(48, ALPHA_MAIN*interaction_multiplier) if kind == 'M1' else []]
    system = gram + np.diag(penalties)
    solution = np.linalg.solve(system, rhs)
    model.intercept, model.coefficients = float(solution[0]), solution[1:]
    stationary = system @ solution - rhs
    relative_residual = float(np.linalg.norm(stationary) / max(np.linalg.norm(rhs), np.finfo(float).tiny))
    if not np.isfinite(solution).all() or relative_residual > 1e-9:
        raise RuntimeError('CONTEXTUAL_RIDGE_SOLUTION_NOT_STATIONARY')
    model.metadata.update(fit_rows=len(p), feasible_rows=int(np.count_nonzero(weights)),
        train_days=int(len(np.unique(dates[weights>0]))), weight_sum=float(weights.sum()),
        signal_max=str(pd.Timestamp(pd.to_datetime(dates).max()).date()),
        alpha_main=ALPHA_MAIN, interaction_multiplier=float(interaction_multiplier),
        solver='date-weighted float64 penalized normal equations; unpenalized intercept',
        stationarity_relative_residual=relative_residual, finite=True, converged=True,
        fit_2026_rows=0, objective='sum_dates mean_feasible_squared_error + 100*main_L2 + 100*multiplier*interaction_L2')
    return model


def date_error_frame(row_dates, target, predictions, allowed, sample_weight=None):
    dates = pd.to_datetime(np.asarray(row_dates).reshape(-1))
    target, predictions = np.asarray(target, float), np.asarray(predictions, float)
    feasible = np.asarray(allowed, bool)
    if not (len(dates) == len(target) == len(predictions) == len(feasible)):
        raise ValueError('ERROR_FRAME_LENGTH_MISMATCH')
    weights = date_equal_weights(dates, feasible, sample_weight)
    error = predictions-target
    frame = pd.DataFrame(dict(signal_date=dates[feasible], squared_error=error[feasible]**2*weights[feasible],
        absolute_error=np.abs(error[feasible])*weights[feasible], prediction=predictions[feasible]*weights[feasible],
        target=target[feasible]*weights[feasible]))
    result = frame.groupby('signal_date', as_index=False).agg(mse=('squared_error','sum'),
        mae=('absolute_error','sum'), rows=('squared_error','size'),
        mean_prediction=('prediction','sum'), mean_target=('target','sum'))
    return result


def _same_scaler(left, right):
    return left.feature_order == right.feature_order and all(np.array_equal(getattr(left, name), getattr(right, name))
        for name in ('mean_', 'scale_', 'var_', 'min_', 'max_'))


class ContextualMeta:
    """Hash-checked explicitly staged model; inference has no outcome argument."""
    def __init__(self, kind='M1', stage='final'):
        if kind not in ('M0', 'M1') or stage not in STAGE_CUTOFFS:
            raise ValueError('INVALID_CONTEXTUAL_LOAD_IDENTITY')
        receipt_path = OUT/'FIT_RECEIPT.json'
        receipt = read(receipt_path)
        if receipt['status'] != 'PASS' or receipt['fit_2026_rows'] != 0:
            raise RuntimeError('CONTEXTUAL_FIT_RECEIPT_NOT_COMPLETE')
        records = [r for r in receipt['fits'] if r['stage'] == stage and r['kind'] == kind]
        if len(records) != 1:
            raise RuntimeError('CONTEXTUAL_STAGE_MODEL_NOT_UNIQUE')
        record = records[0]
        cutoff = pd.Timestamp(STAGE_CUTOFFS[stage])
        if pd.Timestamp(record['train_signal_max']) >= cutoff or pd.Timestamp(record['train_label_end_max']) >= cutoff:
            raise RuntimeError('CONTEXTUAL_LOAD_TIME_LEAKAGE')
        expected_years = [2024] if stage == 'validation' else [2024, 2025]
        if record['oof_years'] != expected_years:
            raise RuntimeError('CONTEXTUAL_MODEL_OOF_STAGE_MISMATCH')
        contract_path = checked_path(receipt['pre_fit_contract_path'], receipt['pre_fit_contract_sha256'])
        artifact_path = checked_path(record['artifact'], record['artifact_sha256'])
        main_path = checked_path(record['main_scaler_artifact'], record['main_scaler_sha256'])
        interaction_path = checked_path(record['interaction_scaler_artifact'], record['interaction_scaler_sha256'])
        self.model = joblib.load(artifact_path)
        main, interaction = joblib.load(main_path), joblib.load(interaction_path)
        if self.model.kind != kind or self.model.stage != stage or self.model.feature_order != record['feature_order']:
            raise RuntimeError('CONTEXTUAL_DESERIALIZED_IDENTITY_MISMATCH')
        if not _same_scaler(main, self.model.main_scaler) or not _same_scaler(interaction, self.model.interaction_scaler):
            raise RuntimeError('CONTEXTUAL_SCALER_DESERIALIZATION_MISMATCH')
        if main.feature_order != MAIN_FEATURES or interaction.feature_order != INTERACTION_FEATURES:
            raise RuntimeError('CONTEXTUAL_SCALER_FEATURE_ORDER_MISMATCH')
        for name, scaler in [('main',main),('interaction',interaction)]:
            if scaler_array_sha256(scaler) != record[f'{name}_scaler_array_sha256']:
                raise RuntimeError('CONTEXTUAL_SCALER_ARRAY_RECEIPT_MISMATCH')
        if sha(__file__) != receipt['source_sha256'][str(Path(__file__).resolve())]:
            raise RuntimeError('CONTEXTUAL_INFERENCE_SOURCE_CHANGED')
        self.kind, self.stage, self.receipt = kind, stage, receipt
        self.loaded_receipt = dict(kind=kind, stage=stage, cutoff_exclusive=STAGE_CUTOFFS[stage],
            oof_years=expected_years, model_artifact=str(artifact_path),
            actual_loaded_hashes={str(artifact_path):sha(artifact_path), str(main_path):sha(main_path),
                str(interaction_path):sha(interaction_path), str(receipt_path):sha(receipt_path),
                str(contract_path):sha(contract_path), str(Path(__file__).resolve()):sha(__file__)},
            main_feature_order=MAIN_FEATURES, interaction_feature_order=INTERACTION_FEATURES,
            interaction_multiplier=self.model.interaction_multiplier,
            embedded_main_scaler_array_sha256=scaler_array_sha256(self.model.main_scaler),
            embedded_interaction_scaler_array_sha256=scaler_array_sha256(self.model.interaction_scaler),
            coefficient_semantics='action-utility slopes of heterogeneous outputs, not funding weights',
            train_signal_max=record['train_signal_max'], train_label_end_max=record['train_label_end_max'])

    def predict(self, p, z, basis):
        return self.model.predict(p, z, basis)

    def effective_coefficients(self, z):
        return self.model.effective_coefficients(z)

    def diagnostic_frame(self, p, z, basis):
        return self.model.diagnostic_frame(p, z, basis)


class ContextualPolicy:
    def __init__(self, kind='M1', stage='final'):
        if str(OLD_ROOT) not in sys.path:
            sys.path.insert(0, str(OLD_ROOT))
        import ensemble as old_ensemble
        import values as old_values
        if old_ensemble.META_FEATURES[:12] != EXPERT_FEATURES or old_ensemble.META_FEATURES[14:] != BASIS_FEATURES:
            raise RuntimeError('CONTEXTUAL_EXISTING_EXPERT_INTERFACE_CHANGED')
        self.meta = ContextualMeta(kind, stage)
        self.base = old_ensemble.BaseBundle(stage)
        if self.base.hashes != self.meta.receipt['inference_dependencies'][stage]:
            raise RuntimeError('CONTEXTUAL_FROZEN_EXPERT_DEPENDENCIES_CHANGED')
        self.loaded_receipt = dict(self.meta.loaded_receipt)
        self.loaded_receipt['actual_loaded_hashes'] = dict(self.meta.loaded_receipt['actual_loaded_hashes'])
        self.loaded_receipt['actual_loaded_hashes'].update(self.base.hashes)
        self.loaded_receipt['actual_loaded_hashes'].update({str(OLD_ROOT/name):sha(OLD_ROOT/name)
            for name in ('ensemble.py', 'values.py', 'neural.py')})
        self.loaded_receipt['base_stage'] = stage
        self.loaded_receipt['base_predictor_clocks'] = self.base.predictor_clocks
        self.values = old_values
        self.kind, self.stage = kind, stage
        self.last_features = None

    def _features(self, day, current_array, cash, age_array, available_slots):
        n = len(day)
        current_array, age_array = np.asarray(current_array, float), np.asarray(age_array, float)
        if current_array.shape != (n,) or age_array.shape != (n,):
            raise ValueError('CONTEXTUAL_POLICY_STATE_LENGTH_MISMATCH')
        if not (np.isfinite(cash) and 0 <= cash <= 1+1e-10 and 0 <= available_slots <= 20):
            raise ValueError('CONTEXTUAL_POLICY_ACCOUNT_STATE_INVALID')
        if n == 0:
            return np.empty((0,12)), np.empty((0,4)), np.empty((0,5))
        x = day[self.values.FEATURES].to_numpy(float)
        old_matrix = self.base.matrix(np.repeat(x,5,axis=0), np.repeat(current_array,5),
            np.full(n*5,float(cash)), np.repeat(age_array,5), np.tile(self.values.ACTIONS,n))
        z = np.column_stack([np.full(n*5,float(cash)), np.repeat(current_array,5),
            np.full(n*5,float(available_slots)), np.repeat(day['realized_vol_20d'].to_numpy(float),5)])
        return old_matrix[:, :12], z, old_matrix[:, 14:]

    def score_actions(self, day, current_array, cash, age_array, available_slots):
        self.last_features = self._features(day,current_array,cash,age_array,available_slots)
        return self.meta.predict(*self.last_features).reshape(len(day),5)

    def score_actions_with_diagnostics(self, day, current_array, cash, age_array, available_slots):
        scores = self.score_actions(day,current_array,cash,age_array,available_slots)
        diagnostic = self.meta.diagnostic_frame(*self.last_features)
        diagnostic.insert(0, 'ticker', np.repeat(day.ticker.astype(str).to_numpy(),5))
        diagnostic.insert(1, 'kind', self.kind)
        diagnostic.insert(2, 'stage', self.stage)
        return scores, diagnostic


def verify_meta_artifacts():
    """Read-only hashes, clocks, nesting receipts and actual staged loading."""
    receipt = read(OUT/'FIT_RECEIPT.json')
    if receipt['status']!='PASS' or receipt['meta_fit_calls']!=8 or receipt['fit_2026_rows']!=0 or receipt['new_base_expert_fit_calls']!=0:
        raise RuntimeError('CONTEXTUAL_COMPLETION_COUNTS_INVALID')
    if receipt['internal_selection']['selection_year']!=2024 or receipt['internal_selection']['selection_2025_rows']!=0 or receipt['internal_selection']['selection_2026_rows']!=0:
        raise RuntimeError('CONTEXTUAL_SELECTION_TIME_INVALID')
    checked = set()
    for path, digest in receipt['input_sha256'].items():
        checked_path(path,digest)
        checked.add(path)
    for record in receipt['fits']:
        stage=record['stage']
        cutoff='2024-10-01' if stage=='internal' else STAGE_CUTOFFS[stage]
        if pd.Timestamp(record['train_signal_max'])>=pd.Timestamp(cutoff) or pd.Timestamp(record['train_label_end_max'])>=pd.Timestamp(cutoff):
            raise RuntimeError('CONTEXTUAL_RECEIPT_TRAIN_CLOCK_INVALID')
        for artifact, digest in [('artifact','artifact_sha256'),('coefficient_artifact','coefficient_sha256'),
                                 ('main_scaler_artifact','main_scaler_sha256'),('interaction_scaler_artifact','interaction_scaler_sha256')]:
            checked_path(record[artifact],record[digest])
            checked.add(record[artifact])
        if not record['finite'] or not record['converged'] or record['stationarity_relative_residual']>1e-9:
            raise RuntimeError('CONTEXTUAL_RECEIPT_NUMERIC_INVALID')
    if not all(record['status']=='PASS' and record['maximum_absolute_error']<=1e-12 for record in receipt['nested_checks']):
        raise RuntimeError('CONTEXTUAL_NESTED_RECEIPT_INVALID')
    loads=[]
    for stage in STAGE_CUTOFFS:
        for kind in ('M0','M1'):
            loaded=ContextualMeta(kind,stage)
            loads.append(dict(kind=kind,stage=stage,loaded_hashes=loaded.loaded_receipt['actual_loaded_hashes']))
    return dict(status='PASS',meta_fit_calls=8,new_base_expert_fit_calls=0,fit_2026_rows=0,
        selected_multiplier=receipt['selected_interaction_multiplier'],unique_hashes_checked=len(checked),
        main_scaler_fit_calls=receipt['main_scaler_fit_calls'],interaction_scaler_fit_calls=receipt['interaction_scaler_fit_calls'],
        maximum_stationarity_residual=max(record['stationarity_relative_residual'] for record in receipt['fits']),loads=loads)
