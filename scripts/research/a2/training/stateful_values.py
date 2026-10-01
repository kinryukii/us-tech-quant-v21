"""Frozen Raw-A2 shareholder-value folds; reuse native estimators, not selectors.

No fitting or research-data read happens on import. The input reader owns parquet
access. NativeBundle.fit/predict are deliberately bypassed: their target clipping
and in-sample adapters do not define this task's five-session shareholder target.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import hashlib
import importlib
import json
import multiprocessing as mp
import time
from pathlib import Path
import sys
import warnings

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from scripts.common.storage_paths import resolve
from scripts.storage.storage_r2a import assert_write_path, write_json_atomic

REPO = Path(__file__).resolve().parents[4]
NATIVE = REPO / 'scripts/research/a2/retained/a2_predict_then_optimize_20260928_r1/models_native.py'
FEATURE_SOURCE = REPO / 'scripts/research/a2/retained/a2_pto_full_compat_20260928_r2/shared.py'
FEATURE_CHECK = FEATURE_SOURCE.with_name('build_inputs.py')
LABEL = 'SHAREHOLDER_OPEN_T_PLUS_1_TO_T_PLUS_6_5_SESSION_RETURN_SUPPORTED_EVENTS_FAIL_CLOSED'
SOURCES = frozenset(('FROZEN_RAW_A2_TRAINING_MATRIX_32', 'FROZEN_RAW_A2_FULL_PIT32_LEDGER_PROJECTION'))
READER_SOURCE = Path(__file__).with_name('stateful_inputs.py')
EXTENSION_SOURCE = Path(__file__).with_name('stateful_value_extensions.py')
POINT = ('ridge','elastic','huber','hgb','xgb','lgb','cat','rf','extra','ebm','mlp','resnet','fttransformer')
QUANTILE = ('linear_q','hgb_q','xgb_q','lgb_q','cat_q','mlp_q')
DISTRIBUTION = ('ngboost','mlp_dist','cat_uncertainty')
RANK = ('xgb_rank','lgb_rank')
EXTENSIONS = ('tcn','lstm','gru','svc')
FIRST_MODELS = POINT + ('logistic',) + QUANTILE + DISTRIBUTION + RANK + EXTENSIONS
SCALED = frozenset(('ridge','elastic','huber','logistic','mlp','linear_q','resnet','fttransformer','mlp_q','mlp_dist'))
TORCH = frozenset(('resnet','fttransformer','mlp_q','mlp_dist'))
FIT_TIMEOUT = 1800
SEED = 20260928
ROLE = 'STOCK_VALUE_ENTER_CONTINUE'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def feature_binding():
    def literal(path):
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ('FEATURES', 'FEATURES32') for t in node.targets):
                return ast.literal_eval(node.value)
        raise ValueError('FROZEN_FEATURE_LIST_MISSING')
    features = literal(FEATURE_SOURCE)
    if len(features) != 32 or len(set(features)) != 32 or features != literal(FEATURE_CHECK):
        raise ValueError('FROZEN_FEATURE_IDENTITY_CHANGED')
    return dict(features=features, feature_order_sha256=digest(features),
                source=str(FEATURE_SOURCE), source_sha256=sha(FEATURE_SOURCE),
                check_source=str(FEATURE_CHECK), check_source_sha256=sha(FEATURE_CHECK))


def frame_digest(frame, features):
    columns = ['signal_date', 'ticker', 'label_mature_date', 'y_open5', *features]
    values = pd.util.hash_pandas_object(frame[columns], index=False).to_numpy(np.uint64)
    return hashlib.sha256(values.tobytes()).hexdigest()


def _bool(series, name):
    if series.isna().any() or not series.isin([True, False]).all():
        raise ValueError('INVALID_BOOLEAN:' + name)
    return series.astype(bool)


def guarded_rows(frame, boundary, features, signal_dates=None):
    """Defense after the reader: metadata eligibility precedes vector/target read."""
    required = {'signal_date', 'ticker', 'label_mature_date', 'y_open5', 'label_available',
                'feature_available', 'account_event_unhandled', 'feature_source', 'label_coordinate', *features}
    if not required.issubset(frame.columns):
        raise ValueError('TRAINING_SCHEMA_MISSING:' + str(sorted(required-set(frame.columns))))
    signal = pd.to_datetime(frame.signal_date, errors='raise')
    mature = pd.to_datetime(frame.label_mature_date, errors='coerce')
    boundary = pd.Timestamp(boundary)
    mask = signal.lt(boundary) & mature.lt(boundary)
    if signal_dates is not None:
        mask &= signal.isin(pd.to_datetime(signal_dates))
    mask &= _bool(frame.label_available, 'label_available') & _bool(frame.feature_available, 'feature_available')
    mask &= ~_bool(frame.account_event_unhandled, 'account_event_unhandled')
    if not frame.loc[mask, 'feature_source'].isin(SOURCES).all():
        raise ValueError('UNQUALIFIED_FEATURE_SOURCE')
    if not frame.loc[mask, 'label_coordinate'].eq(LABEL).all():
        raise ValueError('UNQUALIFIED_SHAREHOLDER_TARGET')
    rows = frame.loc[mask].copy()
    rows['signal_date'] = signal.loc[mask]
    rows['label_mature_date'] = mature.loc[mask]
    rows = rows.sort_values(['signal_date', 'ticker'], kind='stable').reset_index(drop=True)
    if rows.duplicated(['signal_date', 'ticker']).any():
        raise ValueError('DUPLICATE_TRAINING_KEYS')
    x, y = rows[list(features)].to_numpy(float), rows.y_open5.to_numpy(float)
    if np.isinf(x).any() or not np.isfinite(y).all():
        raise ValueError('NONFINITE_LEGAL_TRAINING_VALUES')
    return rows


def transform(scaler, values):
    values = np.asarray(values, float)
    if np.isinf(values).any():
        raise ValueError('INFINITE_FEATURE_FAIL_CLOSED')
    if scaler is None:
        if not np.isfinite(values).all():
            raise ValueError('NATIVE_UNSCALED_REQUIRES_FINITE_FEATURES')
        return values
    transformed = scaler.transform(values)
    if np.isinf(transformed).any():
        raise ValueError('NONFINITE_SCALER_OUTPUT')
    return np.where(np.isnan(transformed), 0., transformed)


def raw_fields(model_id, raw):
    raw = np.asarray(raw, float)
    if not np.isfinite(raw).all():
        raise ValueError('NONFINITE_NATIVE_OUTPUT')
    if model_id in QUANTILE:
        if raw.ndim != 2 or raw.shape[1] != 3:
            raise ValueError('QUANTILE_THREE_HEADS_REQUIRED')
        q = np.sort(raw, axis=1)
        return dict(native_mu=q @ np.array([.3,.4,.3]), raw_q10=raw[:,0], raw_q50=raw[:,1], raw_q90=raw[:,2],
                    q10=q[:,0], q50=q[:,1], q90=q[:,2], native_sigma=(q[:,2]-q[:,0])/(2*1.2815515655446004))
    if model_id in DISTRIBUTION:
        if raw.ndim != 2 or raw.shape[1] != 2:
            raise ValueError('DISTRIBUTION_TWO_COORDINATES_REQUIRED')
        loc, scale = raw[:,0], raw[:,1]
        if model_id == 'mlp_dist':
            loc, scale = loc*.1, (np.logaddexp(0., scale)+1e-3)*.1
        if not np.isfinite(loc).all() or not np.isfinite(scale).all() or np.any(scale <= 0):
            raise ValueError('INVALID_NATIVE_DISTRIBUTION')
        return dict(native_mu=loc, native_sigma=scale)
    if raw.ndim != 1:
        raise ValueError('NATIVE_SCALAR_OUTPUT_REQUIRED')
    if model_id == 'logistic':
        if np.any((raw < 0) | (raw > 1)):
            raise ValueError('PROBABILITY_OUT_OF_BOUNDS')
        return dict(p_up=raw)
    if model_id in RANK:
        return dict(rank_score=raw)
    if model_id == 'svc':
        return dict(svc_margin=raw)
    return dict(native_mu=raw)


def diagnostic_columns(model_id):
    if model_id in QUANTILE:
        return ('native_mu','raw_q10','raw_q50','raw_q90','q10','q50','q90','native_sigma')
    if model_id in DISTRIBUTION:
        return ('native_mu','native_sigma')
    return ('p_up',) if model_id == 'logistic' else (('rank_score',) if model_id in RANK else (('svc_margin',) if model_id == 'svc' else ('native_mu',)))


def _calibrated_mean(calibration, raw):
    fields = raw_fields(calibration['model_id'], raw)
    if calibration['kind'] == 'probability':
        p = fields['p_up']
        return p*calibration['positive_mean']+(1-p)*calibration['negative_mean']
    if calibration['kind'] == 'isotonic':
        scores = fields['rank_score'] if 'rank_score' in fields else fields['svc_margin']
        return np.asarray(calibration['isotonic'].predict(scores), float)
    return fields['native_mu']+calibration['offset']


def heldout_calibration(model_id, raw, y, isotonic=None):
    y = np.asarray(y, float)
    fields = raw_fields(model_id, raw)
    if y.ndim != 1 or len(y) < 2 or any(len(v) != len(y) for v in fields.values()) or not np.isfinite(y).all():
        raise ValueError('INVALID_HELDOUT_CALIBRATION')
    cal = dict(model_id=model_id, kind='point', offset=0., scope='CHRONOLOGICAL_HELDOUT_RESIDUAL_SAMPLE_STD_DDOF_1_ONCE',
               native_sigma_calibrated=False)
    if model_id == 'logistic':
        if (y > 0).sum() < 2 or (y <= 0).sum() < 2:
            raise ValueError('HELDOUT_CLASS_AMPLITUDES_REQUIRE_TWO_PER_CLASS')
        cal.update(kind='probability', positive_mean=float(y[y > 0].mean()), negative_mean=float(y[y <= 0].mean()),
                   mapper_scope='CHRONOLOGICAL_HELDOUT_CLASS_AMPLITUDES')
    elif model_id in RANK or model_id == 'svc':
        if isotonic is None:
            raise ValueError('HELDOUT_ISOTONIC_REQUIRED')
        cal.update(kind='isotonic', isotonic=isotonic, mapper_scope='CHRONOLOGICAL_HELDOUT_SCORE_TO_UNCLIPPED_Y5')
    elif model_id == 'huber' or model_id in QUANTILE:
        cal['offset'] = float((y-fields['native_mu']).mean())
        cal['mapper_scope'] = 'CHRONOLOGICAL_HELDOUT_RESIDUAL_MEAN_OFFSET'
    sigma = float(np.std(y-_calibrated_mean(cal, raw), ddof=1))
    if not np.isfinite(sigma) or sigma <= 0:
        raise ValueError('NONPOSITIVE_HELDOUT_RESIDUAL_SIGMA')
    cal['sigma'] = sigma
    return cal


def calibrated_values(calibration, raw):
    mean = _calibrated_mean(calibration, raw)
    return mean, np.full(mean.shape, calibration['sigma'])


def extension_inputs(model_id, reader, frame, features):
    if model_id == 'svc':
        return frame[list(features)].to_numpy(float), None
    from scripts.research.a2.training.stateful_value_extensions import sequence_windows
    window = sequence_windows(reader, frame[['signal_date','ticker']], length=20)
    return window['features'], window['cell_observed']


def _native(dependency_paths=()):
    # Existing frozen dependency snapshots only; never shadow canonical packages.
    for folder in dependency_paths:
        folder = Path(folder).resolve()
        if not folder.is_relative_to(resolve(REPO).envs_root.resolve()) or not folder.is_dir():
            raise ValueError('DEPENDENCY_SNAPSHOT_OUTSIDE_ENVS_ROOT')
        if str(folder) not in sys.path:
            sys.path.append(str(folder))
    saved = list(sys.path)
    try:
        return importlib.import_module('scripts.research.a2.retained.a2_predict_then_optimize_20260928_r1.models_native')
    finally:
        # The old module's optional third_party prepend must not shadow this run.
        sys.path[:] = saved


@dataclass
class ValueFit:
    native: object
    calibration: dict
    receipt: dict

    def predict(self, frame, reader=None):
        pins = self.receipt['reuse_tuple']['source_pins']
        if sha(Path(__file__)) != pins['module_sha256'] or sha(NATIVE) != pins['native_source_sha256'] or sha(READER_SOURCE) != pins['input_reader_sha256']:
            raise ValueError('VALUE_INFERENCE_SOURCE_CHANGED')
        model_id = self.receipt['model_id']
        if model_id in EXTENSIONS and sha(EXTENSION_SOURCE) != pins['extension_source_sha256']:
            raise ValueError('EXTENSION_INFERENCE_SOURCE_CHANGED')
        features = self.receipt['reuse_tuple']['feature_binding']['features']
        signal = pd.to_datetime(frame.signal_date, errors='raise')
        year = self.receipt['year']
        if not (signal.ge(f'{year}-01-01') & signal.lt(f'{year+1}-01-01') & signal.lt('2026-01-01')).all():
            raise ValueError('INFERENCE_OUTSIDE_AUTHORIZED_ANNUAL_PRE2026_SCOPE')
        mask = _bool(frame.feature_available, 'feature_available')
        if 'input_present' in frame:
            mask &= _bool(frame.input_present, 'input_present')
        if not frame.loc[mask, 'feature_source'].isin(SOURCES).all():
            raise ValueError('UNQUALIFIED_INFERENCE_SOURCE')
        out = frame[['signal_date', 'ticker']].copy()
        out['prediction'], out['value_sigma'] = np.nan, np.nan
        for name in diagnostic_columns(model_id):
            out[name] = np.nan
        if mask.any():
            _native(self.receipt['dependency_paths'])
            indices = np.flatnonzero(mask.to_numpy())
            for start in range(0, len(indices), 100_000):
                ids = indices[start:start+100_000]
                rows = frame.iloc[ids]
                if model_id in EXTENSIONS:
                    if reader is None:
                        raise ValueError('EXTENSION_INFERENCE_REQUIRES_FROZEN_READER')
                    from scripts.research.a2.training.stateful_value_extensions import raw_predict
                    x, observed = extension_inputs(model_id, reader, rows, features)
                    raw = raw_predict(self.native, x, observed)
                else:
                    x = transform(self.native.scaler, rows[features].to_numpy(float))
                    with threadpool_limits(limits=1):
                        raw = self.native.raw_predict(x)
                mu, sigma = calibrated_values(self.calibration, raw)
                if not np.isfinite(mu).all() or not np.isfinite(sigma).all() or np.any(sigma <= 0):
                    raise ValueError('NONFINITE_QUALIFIED_VALUE_PREDICTION')
                out.iloc[ids, out.columns.get_loc('prediction')] = mu
                out.iloc[ids, out.columns.get_loc('value_sigma')] = sigma
                for name, values in raw_fields(model_id, raw).items():
                    out.iloc[ids, out.columns.get_loc(name)] = values
        out['prediction_qualified'] = mask.to_numpy()
        out['year'], out['model_id'] = year, model_id
        out['model_reuse_tuple_sha256'] = self.receipt['reuse_tuple_sha256']
        out['model_sha256'] = self.receipt['model_sha256']
        return out


def scientific_tuple(train, calibration, fold, binding):
    return dict(fold='ANNUAL_'+str(fold['year']), role=ROLE, family='RIDGE',
                configuration={'alpha': 1., 'fit_intercept': True}, feature_binding=binding,
                label_definition=LABEL, label_domain='INDIVIDUAL_ELIGIBLE_STOCK',
                cutoff_exclusive=pd.Timestamp(fold['cutoff_exclusive']).isoformat(),
                training_signal_and_label_maturity_exclusive=pd.Timestamp(fold['calibration_start']).isoformat(),
                calibration_sessions=[pd.Timestamp(d).isoformat() for d in fold['calibration_sessions']],
                calibration_label_maturity_exclusive=pd.Timestamp(fold['cutoff_exclusive']).isoformat(),
                calendar_sha256=fold['calendar_sha256'],
                training_input_sha256=frame_digest(train, binding['features']),
                calibration_input_sha256=frame_digest(calibration, binding['features']),
                sklearn_version=sklearn.__version__, preprocessor='StandardScaler_DEFAULTS_NAN_TO_ZERO_AFTER_TRANSFORM',
                uncertainty='CHRONOLOGICAL_HELDOUT_RESIDUAL_SAMPLE_STD_DDOF_1_ONCE')


def exact_ridge_reuse(receipt, expected):
    old = receipt.get('model_reuse_tuple', {})
    return (receipt.get('status') == 'TRAINED' and receipt.get('scientific_target_qualified') is True
            and receipt.get('scientific_feature_pit_qualified') is True
            and receipt.get('generation') == 'SHAREHOLDER_LABEL_REPAIR_R1'
            and all(old.get(key) == value for key, value in expected.items()))


def frozen_contract(run_dir, model_id, year):
    run_dir = Path(run_dir).resolve()
    assert_write_path(run_dir / 'models/value', 'backtest')
    config = json.loads((run_dir / 'run_config.json').read_text(encoding='utf-8-sig'))
    auth = config.get('value_training', {})
    if config.get('strategy_version') != 'V24' or config.get('training_cutoff_exclusive') != '2026-01-01':
        raise ValueError('VALUE_RUN_IDENTITY_OR_TIME_BOUNDARY')
    if auth.get('status') != 'FROZEN' or auth.get('seed') != SEED:
        raise ValueError('VALUE_TRAINING_NOT_FROZEN')
    if model_id not in FIRST_MODELS or model_id not in auth.get('models', []) or year not in auth.get('years', []):
        raise ValueError('MODEL_YEAR_NOT_IN_FROZEN_FIRST_PACKET')
    if year not in (2021, 2022, 2023, 2024, 2025) or (year < 2023 and model_id not in ('ridge', 'hgb', 'lgb')):
        raise ValueError('ANNUAL_EARLY_PACKET_OR_TEST_BOUNDARY')
    pins = {'module_sha256': sha(Path(__file__)), 'native_source_sha256': sha(NATIVE),
            'input_manifest_sha256': sha(run_dir / 'input_manifest.json'), 'input_reader_sha256': sha(READER_SOURCE)}
    if model_id in EXTENSIONS:
        pins['extension_source_sha256'] = sha(EXTENSION_SOURCE)
    if any(auth.get(key) != value for key, value in pins.items()):
        raise ValueError('VALUE_FROZEN_SOURCE_OR_INPUT_MANIFEST_CHANGED')
    if auth.get('fit_timeout_seconds') != FIT_TIMEOUT or config.get('prior_cumulative_fit_units') != 18:
        raise ValueError('VALUE_TIMEOUT_OR_PRIOR_LEDGER_CHANGED')
    if not isinstance(auth.get('max_fit_units'), int) or not isinstance(auth.get('max_model_year_attempts'), int):
        raise ValueError('VALUE_FIT_BUDGET_MISSING')
    return run_dir, config, auth, pins


def _events(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line]


def _append(path, event):
    assert_write_path(path, 'backtest')
    with path.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(event, sort_keys=True, allow_nan=False)+'\n')
        stream.flush()


def _component_start(log, auth, prior, model_id, year, component, tuple_sha):
    used = prior+sum(e.get('fit_units', 0) for e in _events(log) if e.get('event') == 'FIT_STARTED')
    if used >= auth['max_fit_units']:
        raise RuntimeError('CUMULATIVE_FIT_BUDGET_EXHAUSTED')
    bucket = auth.get('budget_bucket', 'value_meta_primary')
    bucket_used = sum(e.get('fit_units',0) for e in _events(log) if e.get('event') == 'FIT_STARTED' and e.get('budget_bucket') == bucket)
    if bucket_used >= auth.get('max_new_bucket_fit_units', auth['max_fit_units']-prior):
        raise RuntimeError('FROZEN_FIT_BUCKET_EXHAUSTED')
    _append(log, dict(event='FIT_STARTED', fit_units=1, model_id=model_id, year=year,
                      role=ROLE, budget_bucket=bucket, component=component, reuse_tuple_sha256=tuple_sha))


def _fit_worker(pipe, operation, model_id, x, y, dates, quantile, dependencies, features, observed):
    def started(component):
        pipe.send(('FIT_START', component))
        if pipe.recv() is not True:
            raise RuntimeError('PARENT_REJECTED_FIT_BUDGET')
    try:
        meta = {}
        with threadpool_limits(limits=1), warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            if operation == 'scaler':
                model = StandardScaler()
                started('SCALER')
                model.fit(x)
                if not np.isfinite(model.mean_).all() or not np.isfinite(model.scale_).all():
                    raise ValueError('NONFINITE_TRAIN_ONLY_SCALER')
            elif operation == 'isotonic':
                from sklearn.isotonic import IsotonicRegression
                model = IsotonicRegression(out_of_bounds='clip')
                started('HELDOUT_ISOTONIC')
                model.fit(x, y)
            elif operation == 'extension':
                _native(dependencies)
                from scripts.research.a2.training.stateful_value_extensions import fit_extension
                model = fit_extension(model_id, x, y, feature_order=features, mask=observed,
                                      dependency_paths=dependencies, on_fit_started=started)
                meta = model.metadata
            else:
                native = _native(dependencies)
                if model_id in TORCH:
                    started('PREDICTOR')
                    model, meta = native.fit_torch(model_id, x, y, np.ones(len(y)))
                    if meta.get('epochs') != 12:
                        raise RuntimeError('NATIVE_NEURAL_FIXED_EPOCHS_NOT_COMPLETED')
                else:
                    model = native.estimator(model_id, quantile=quantile)
                    if model_id == 'ridge':
                        model.set_params(alpha=1., fit_intercept=True)
                    component = 'PREDICTOR' if quantile is None else 'PREDICTOR_Q'+str(int(quantile*100))
                    started(component)
                    if model_id in RANK:
                        groups = native.group_lengths(dates)
                        relevance = native.relevance_for_dates(y, dates)
                        weights = np.ones(len(groups)) if model_id == 'xgb_rank' else np.ones(len(y))
                        model.fit(x, relevance, group=groups, sample_weight=weights)
                        meta['rank_training_groups'] = groups.tolist()
                    else:
                        model.fit(x, (y > 0).astype(int) if model_id == 'logistic' else y)
                    if model_id == 'ngboost' and len(model.base_models) != 100:
                        raise RuntimeError('NATIVE_NGBOOST_ROUNDS_NOT_COMPLETED')
                    if model_id == 'mlp' and model.n_iter_ != 20:
                        raise RuntimeError('NATIVE_MLP_FIXED_EPOCHS_NOT_COMPLETED')
        meta['warnings'] = [dict(category=w.category.__name__, message=str(w.message)) for w in caught]
        if model_id != 'mlp' and any(w.category.__name__ == 'ConvergenceWarning' for w in caught):
            raise RuntimeError('UNRESOLVED_CONVERGENCE_NO_AUTOMATIC_RETRY')
        pipe.send(('RESULT', model, meta))
    except BaseException as exc:
        pipe.send(('ERROR', type(exc).__name__, str(exc)))
    finally:
        pipe.close()


def _fit_job(operation, model_id, x, y, dates, quantile, dependencies, features, observed,
             *, log, auth, prior, year, tuple_sha, receipt, worker_target=None):
    context = mp.get_context('spawn')
    parent, child = context.Pipe()
    worker = context.Process(target=worker_target or _fit_worker,
        args=(child, operation, model_id, x, y, dates, quantile, dependencies, features, observed))
    worker.start()
    child.close()
    deadline = time.monotonic()+FIT_TIMEOUT
    try:
        while True:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('PHYSICAL_FIT_1800_SECONDS_EXCEEDED')
            if not parent.poll(min(.25, remaining)):
                if not worker.is_alive():
                    raise RuntimeError('FIT_WORKER_EXITED_WITHOUT_RESULT:'+str(worker.exitcode))
                continue
            message = parent.recv()
            if message[0] == 'FIT_START':
                _component_start(log, auth, prior, model_id, year, message[1], tuple_sha)
                receipt['fit_units'] += 1
                write_json_atomic(Path(receipt['receipt_path']), receipt)
                deadline = time.monotonic()+FIT_TIMEOUT
                parent.send(True)
            elif message[0] == 'RESULT':
                worker.join(timeout=5)
                if worker.is_alive() or worker.exitcode != 0:
                    raise RuntimeError('FIT_WORKER_DID_NOT_EXIT_CLEANLY_AFTER_RESULT')
                receipt.setdefault('physical_fit_metadata', []).append(
                    dict(operation=operation, quantile=quantile, metadata=message[2]))
                return message[1]
            elif message[0] == 'ERROR':
                raise RuntimeError('FIT_WORKER_FAILED:'+message[1]+':'+message[2])
            else:
                raise RuntimeError('UNKNOWN_FIT_WORKER_MESSAGE')
    finally:
        if worker.is_alive():
            worker.terminate()
        worker.join(timeout=5)
        parent.close()


def validate_fold(fold):
    sessions = pd.DatetimeIndex(fold['calibration_sessions'])
    cutoff, start = pd.Timestamp(fold['cutoff_exclusive']), pd.Timestamp(fold['calibration_start'])
    if cutoff != pd.Timestamp(f"{fold['year']}-01-01") or cutoff > pd.Timestamp('2025-01-01'):
        raise ValueError('ANNUAL_FOLD_CUTOFF_INVALID')
    if len(sessions) != 60 or sessions.has_duplicates or not sessions.is_monotonic_increasing or sessions[0] != start or not (sessions < cutoff).all():
        raise ValueError('CALIBRATION_MUST_BE_60_CHRONOLOGICAL_PRIOR_US_SESSIONS')


def train_annual(model_id, year, run_dir, reader=None):
    """One frozen model/year. Reuse complete exact models; reject partial retries."""
    run_dir, config, auth, pins = frozen_contract(run_dir, model_id, year)
    from scripts.research.a2.training.stateful_inputs import InputReader
    if reader is None:
        reader = InputReader(run_dir)
    elif type(reader) is not InputReader or reader.run != run_dir:
        raise ValueError('CANONICAL_INPUT_READER_REQUIRED')
    fold = dict(reader.annual_fold(year), year=year)
    validate_fold(fold)
    binding = feature_binding()
    train, cal = reader.read_training_fold(year)
    train = guarded_rows(train, fold['calibration_start'], binding['features'])
    cal = guarded_rows(cal, fold['cutoff_exclusive'], binding['features'], fold['calibration_sessions'])
    if len(train) < 2 or len(cal) < 2:
        raise ValueError('BLOCKED_DATA_CHRONOLOGICAL_TRAIN_CALIBRATION')
    expected = scientific_tuple(train, cal, fold, binding)
    reuse = dict(expected, model_id=model_id, family=model_id, source_pins=pins, seed=SEED,
        native_factory='models_native.estimator_or_fit_torch_RAW_PREDICT_ONLY' if model_id not in EXTENSIONS else 'stateful_value_extensions.fit_extension',
        target_clipping='NONE', native_statistics_used=False, weights='UNIFORM_ROWS_NO_SELECTION',
        preprocessing='TRAIN_ONLY_STANDARD_SCALER_NAN_TO_ZERO_AFTER_TRANSFORM' if model_id in SCALED else
                      ('EXTENSION_TRAIN_ONLY_CHANNEL_SCALER_PLUS_MISSING_MASK' if model_id in EXTENSIONS else 'NONE_REQUIRE_FINITE'),
        fit_timeout_seconds=FIT_TIMEOUT)
    if model_id != 'ridge':
        reuse['configuration'] = 'EXACT_PINNED_NATIVE_COMPACT_FACTORY_ONE_CONFIGURATION_NO_SEARCH'
        reuse['preprocessor'] = reuse['preprocessing']
    tuple_sha = digest(reuse)
    slot = run_dir / 'models/value' / model_id / str(year)
    receipt_path, model_path = slot / 'fit_receipt.json', slot / 'model.joblib'
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        if receipt.get('status') not in ('TRAINED', 'EXACT_REUSED') or receipt.get('reuse_tuple_sha256') != tuple_sha or sha(model_path) != receipt.get('model_sha256'):
            raise RuntimeError('EXISTING_VALUE_SLOT_CHANGED_OR_INCOMPLETE_NO_REFIT')
        result = joblib.load(model_path)
        result.receipt = receipt
        return result
    slot.mkdir(parents=True, exist_ok=True)
    log = run_dir / 'FIT_LOG.jsonl'
    events = _events(log)
    attempts = [e for e in events if e.get('event') == 'MODEL_YEAR_ATTEMPT_STARTED']
    if any(e.get('model_id') == model_id and e.get('year') == year for e in attempts):
        raise RuntimeError('MODEL_YEAR_ALREADY_ATTEMPTED_NO_ALIAS_RETRY')
    if len(attempts) >= auth['max_model_year_attempts']:
        raise RuntimeError('MODEL_YEAR_ATTEMPT_BUDGET_EXHAUSTED')
    _append(log, dict(event='MODEL_YEAR_ATTEMPT_STARTED', model_id=model_id, year=year, reuse_tuple_sha256=tuple_sha))
    receipt = dict(status='RUNNING', model_id=model_id, year=year, role=ROLE, seed=SEED,
                   reuse_tuple=reuse, reuse_tuple_sha256=tuple_sha, training_rows=len(train), calibration_rows=len(cal),
                   train_label_maturity_max=train.label_mature_date.max().isoformat(),
                   calibration_label_maturity_max=cal.label_mature_date.max().isoformat(),
                   scientific_target_qualified=True, scientific_feature_pit_qualified=True, fit_units=0,
                   model_path=str(model_path), receipt_path=str(receipt_path), warnings=[],
                   dependency_paths=list(auth.get('dependency_paths', [])))
    write_json_atomic(receipt_path, receipt)
    try:
        native = _native(auth.get('dependency_paths', []))
        bundle = native.NativeBundle(model_id, list(binding['features'])) if model_id not in EXTENSIONS else None
        old_pin = next((p for p in auth.get('ridge_reuse', []) if p['year'] == year), None) if model_id == 'ridge' else None
        if model_id == 'ridge' and year >= 2023 and old_pin is None:
            raise RuntimeError('MANDATORY_ANNUAL_RIDGE_EXACT_REUSE_PIN_MISSING')
        if old_pin is not None:
            old_path, old_model = Path(old_pin['receipt_path']), Path(old_pin['model_path'])
            if sha(old_path) != old_pin['receipt_sha256'] or sha(old_model) != old_pin['model_sha256']:
                raise RuntimeError('FROZEN_RIDGE_REUSE_BYTES_CHANGED')
            old = json.loads(old_path.read_text(encoding='utf-8'))
            if not exact_ridge_reuse(old, expected):
                raise RuntimeError('FROZEN_RIDGE_REUSE_SCIENTIFIC_TUPLE_MISMATCH')
            objects = joblib.load(old_model)
            bundle.estimator_object, bundle.scaler = objects['predictor'], objects['scaler']
            calibration = dict(model_id='ridge', kind='point', offset=0., sigma=float(objects['sigma']), scope=expected['uncertainty'], native_sigma_calibrated=False)
            receipt.update(status='EXACT_REUSED', reused_from=dict(old_pin, old_tuple_sha256=old['model_reuse_tuple_sha256']),
                           trained_backend_source_sha256=old['model_reuse_tuple']['backend_source_sha256'])
        else:
            features = binding['features']
            x, y = train[features].to_numpy(float), train.y_open5.to_numpy(float)
            cy = cal.y_open5.to_numpy(float)
            if model_id in ('logistic','svc') and (len(np.unique(y > 0)) != 2 or (cy > 0).sum() < 2 or (cy <= 0).sum() < 2):
                raise ValueError('BLOCKED_DATA_CLASSIFICATION_TRAIN_CAL_CLASSES')
            dependencies = list(auth.get('dependency_paths', []))
            def fit_job(operation, xx, yy=None, quantile=None, observed=None):
                return _fit_job(operation, model_id, xx, yy, train.signal_date.to_numpy(), quantile,
                    dependencies, features, observed, log=log, auth=auth,
                    prior=config['prior_cumulative_fit_units'], year=year,
                    tuple_sha=tuple_sha, receipt=receipt)
            if model_id in EXTENSIONS:
                from scripts.research.a2.training.stateful_value_extensions import raw_predict
                ex, observed = extension_inputs(model_id, reader, train, features)
                bundle = fit_job('extension', ex, y, observed=observed)
                cx, cal_observed = extension_inputs(model_id, reader, cal, features)
                raw = raw_predict(bundle, cx, cal_observed)
            else:
                if model_id in SCALED:
                    if np.isnan(x).all(axis=0).any():
                        raise ValueError('NO_TRAIN_ONLY_MEAN_FOR_FEATURE')
                    bundle.scaler = fit_job('scaler', x)
                xx = transform(bundle.scaler, x)
                if model_id in QUANTILE and model_id not in TORCH:
                    bundle.estimator_object = [fit_job('predictor', xx, y, quantile=q) for q in (.1,.5,.9)]
                else:
                    bundle.estimator_object = fit_job('predictor', xx, y)
                cx = transform(bundle.scaler, cal[features].to_numpy(float))
                with threadpool_limits(limits=1):
                    raw = bundle.raw_predict(cx)
            fields = raw_fields(model_id, raw)
            isotonic = None
            if model_id in RANK or model_id == 'svc':
                scores = fields['rank_score'] if model_id in RANK else fields['svc_margin']
                isotonic = fit_job('isotonic', scores, cy)
            elif model_id == 'logistic' or model_id == 'huber' or model_id in QUANTILE:
                component = 'HELDOUT_CLASS_AMPLITUDES' if model_id == 'logistic' else 'HELDOUT_MEAN_OFFSET'
                _component_start(log, auth, config['prior_cumulative_fit_units'], model_id, year, component, tuple_sha)
                receipt['fit_units'] += 1
                write_json_atomic(receipt_path, receipt)
            _component_start(log, auth, config['prior_cumulative_fit_units'], model_id, year, 'HELDOUT_RESIDUAL_SIGMA', tuple_sha)
            receipt['fit_units'] += 1
            write_json_atomic(receipt_path, receipt)
            calibration = heldout_calibration(model_id, raw, cy, isotonic=isotonic)
            receipt['status'] = 'TRAINED'
        frozen_contract(run_dir, model_id, year)
        result = ValueFit(bundle, calibration, receipt)
        if hasattr(bundle, '_torch_model'):
            bundle._torch_model = None
        joblib.dump(result, model_path)
        receipt['model_sha256'] = sha(model_path)
        receipt['calibration'] = {k:v for k,v in calibration.items() if k != 'isotonic'}
        write_json_atomic(receipt_path, receipt)
        _append(log, dict(event='MODEL_YEAR_COMPLETE', model_id=model_id, year=year, status=receipt['status'],
                          fit_units=receipt['fit_units'], reuse_tuple_sha256=tuple_sha, model_sha256=receipt['model_sha256']))
        return result
    except Exception as exc:
        receipt.update(status='FAILED', failure={'type': type(exc).__name__, 'message': str(exc)})
        write_json_atomic(receipt_path, receipt)
        _append(log, dict(event='MODEL_YEAR_FAILED', model_id=model_id, year=year, fit_units=receipt['fit_units'], failure=receipt['failure']))
        raise


def publish_prediction(fitted, reader, run_dir, year):
    model_id = fitted.receipt['model_id']
    output = Path(run_dir) / 'predictions/value' / model_id / f'{year}.parquet'
    receipt_path = output.with_suffix('.receipt.json')
    assert_write_path(output, 'backtest')
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        if receipt['sha256'] != sha(output) or receipt['reuse_tuple_sha256'] != fitted.receipt['reuse_tuple_sha256']:
            raise RuntimeError('EXISTING_VALUE_PREDICTION_CHANGED')
        return receipt
    predictions = fitted.predict(reader.read_inference(year), reader=reader)
    predictions.to_parquet(output, index=False)
    receipt = dict(status='PUBLISHED', path=str(output), sha256=sha(output), year=year, model_id=model_id,
                   rows=len(predictions), qualified_rows=int(predictions.prediction_qualified.sum()),
                   unavailable_rows=int((~predictions.prediction_qualified).sum()),
                   reuse_tuple_sha256=fitted.receipt['reuse_tuple_sha256'], model_sha256=fitted.receipt['model_sha256'],
                   fit_receipt_path=fitted.receipt['receipt_path'], fit_receipt_sha256=sha(fitted.receipt['receipt_path']),
                   producer_source_sha256=sha(Path(__file__)), input_manifest_sha256=sha(Path(run_dir)/'input_manifest.json'),
                   numeric_economic_performance_reported=False, test_2026_rows_read=0)
    write_json_atomic(receipt_path, receipt)
    return receipt


def run_batch(run_dir):
    config = json.loads((Path(run_dir)/'run_config.json').read_text(encoding='utf-8-sig'))
    schedule = config['value_training']['ordered_schedule']
    if len(schedule) != 93 or len({(x['model_id'],x['year']) for x in schedule}) != 93:
        raise ValueError('EXACT_29_MAIN_PLUS_6_EARLY_SCHEDULE_REQUIRED')
    for item in schedule:
        frozen_contract(run_dir,item['model_id'],item['year'])
    from scripts.research.a2.training.stateful_inputs import InputReader
    reader = InputReader(run_dir)
    statuses = []
    blocked_families = {}
    progress = Path(run_dir)/'logs/value_batch_status.json'
    progress.parent.mkdir(parents=True,exist_ok=True)
    for item in schedule:
        model_id, year = item['model_id'],item['year']
        try:
            if model_id in blocked_families:
                raise RuntimeError('COMMON_FAMILY_BLOCK_NOT_REATTEMPTED:'+blocked_families[model_id])
            fit = train_annual(model_id,year,run_dir,reader=reader)
            published = publish_prediction(fit,reader,run_dir,year)
            status = dict(**item,status=fit.receipt['status'],fit_units=fit.receipt['fit_units'],prediction_receipt=str(Path(published['path']).with_suffix('.receipt.json')))
        except Exception as exc:
            text = str(exc)
            status = dict(**item,status='NOT_ATTEMPTED_COMMON_BLOCK' if text.startswith('COMMON_FAMILY_BLOCK_NOT_REATTEMPTED:') else 'FAILED',failure={'type':type(exc).__name__,'message':text})
            if 'PHYSICAL_FIT_1800_SECONDS_EXCEEDED' in text or 'No module named' in text or 'NATIVE_DEPENDENCY_UNAVAILABLE:' in text:
                blocked_families[model_id] = text
        statuses.append(status)
        write_json_atomic(progress,dict(status='RUNNING' if len(statuses)<len(schedule) else 'ATTEMPTS_FINISHED',slots=statuses,
                                      expected_slots=len(schedule), prior_fit_units=18,test_2026_rows_read=0))
        print(json.dumps(status,sort_keys=True),flush=True)
        if status['status']=='FAILED' and ('BUDGET_EXHAUSTED' in status['failure']['message'] or 'SOURCE_OR_INPUT_MANIFEST_CHANGED' in status['failure']['message']):
            break
    return statuses


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--model', choices=FIRST_MODELS)
    parser.add_argument('--year', type=int)
    parser.add_argument('--predict', action='store_true')
    parser.add_argument('--batch', action='store_true')
    args = parser.parse_args(argv)
    if args.batch:
        if args.model is not None or args.year is not None:
            parser.error('batch uses only the frozen ordered schedule')
        statuses=run_batch(args.run_dir)
        return 0 if len(statuses)==93 and all(s['status'] in ('TRAINED','EXACT_REUSED') for s in statuses) else 2
    if args.model is None or args.year is None:
        parser.error('single fit requires model and year')
    frozen_contract(args.run_dir,args.model,args.year)
    from scripts.research.a2.training.stateful_inputs import InputReader
    reader=InputReader(args.run_dir)
    fitted=train_annual(args.model,args.year,args.run_dir,reader=reader)
    if args.predict:
        publish_prediction(fitted,reader,args.run_dir,args.year)
    print(json.dumps({k:fitted.receipt[k] for k in ('status','model_id','year','fit_units','model_path')},sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
