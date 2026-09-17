"""One bounded annual A/B study; annual fitted objects serve inner and outer roles.

The pre-existing command routes here only for the explicit 0945 task identity.
No data acquisition, broker, production registry, or parameter search lives here.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from threadpoolctl import threadpool_limits

from . import calibrated_models as cm
from . import modeling as old_metrics

TASK_ID = 'FAST3_STOCK_0945_INFORMATION_ALGORITHM_STUDY_R1'
YEARS = (2022, 2023, 2024, 2025)
ORDER = ('B0', 'B1', *cm.SPEC_ORDER)
CUTOFF = cm.CUTOFF
MAX_FITS = 160
PLANNED_MAX = 114
META = ['sample_id', 'ticker', 'date', 'security_uid', 'prediction_at_utc',
        'feature_cutoff_utc', 'label_start_utc', 'label_end_utc',
        'label_available_at_utc', 'return_remaining', 'y', 'label_reason']


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, (Path, pd.Timestamp)):
        return str(value)
    return value


def write_json(path, value):
    Path(path).write_text(json.dumps(clean(value), indent=2, ensure_ascii=False,
                                    allow_nan=False, default=str), encoding='utf-8')


def identity(value):
    return hashlib.sha256(json.dumps(clean(value), sort_keys=True, default=str).encode()).hexdigest()


def source_identity():
    root = Path(__file__).parent
    return {name: sha(root / name) for name in
            ('opening_study.py', 'opening_data.py', 'calibrated_models.py',
             'stock_open_3h.py', 'modeling.py', 'pit_inputs.py')}


def validate_panel(panel, config):
    required = set(META) | set(config['feature_columns_B'])
    if missing := required - set(panel):
        raise ValueError(f'Missing panel fields: {sorted(missing)}')
    if panel.sample_id.duplicated().any() or not panel.eligible.all():
        raise ValueError('Prediction universe must be unique historically eligible rows')
    if set(panel.ticker.unique()) != {'NVDA', 'AMD', 'AVGO', 'ENPH'}:
        raise ValueError('Fixed four-stock scope changed')
    for name in [c for c in META if c.endswith('_utc')]:
        panel[name] = pd.to_datetime(panel[name], utc=True)
    if panel.prediction_at_utc.isna().any() or (panel.prediction_at_utc >= CUTOFF).any():
        raise ValueError('Only certified pre-2026 study rows can be read for training')
    for column, clock in [('prediction_at_utc', '09:45'), ('feature_cutoff_utc', '09:44'),
                          ('label_start_utc', '09:46'), ('label_end_utc', '12:30'),
                          ('label_available_at_utc', '12:31')]:
        local = panel[column].dt.tz_convert('America/New_York')
        if not local.dt.strftime('%H:%M').eq(clock).all() or not local.dt.strftime('%Y-%m-%d').eq(panel.date).all():
            raise ValueError(f'Frozen date/clock mismatch: {column}')
    labelled = panel.y.notna()
    if (panel.loc[labelled, 'label_available_at_utc'] >= CUTOFF).any():
        raise ValueError('Training label not mature before cutoff')
    if not panel.loc[labelled, 'y'].eq(panel.loc[labelled, 'return_remaining'].gt(0).astype(int)).all():
        raise ValueError('Frozen label definition mismatch')
    if not set(config['feature_columns_A']).issubset(config['feature_columns_B']):
        raise ValueError('B must preserve A')
    if len(config['feature_columns_A']) != 75 or len(config['feature_columns_B']) != 93:
        raise ValueError('Frozen feature counts changed')
    return panel.sort_values(['date', 'ticker']).reset_index(drop=True)


def split_prefix(panel, boundary):
    """Future label availability never filters the E prediction universe."""
    boundary = pd.Timestamp(boundary)
    if boundary.tzinfo is None:
        raise ValueError('Boundary needs timezone')
    dev = panel.loc[panel.y.notna() & panel.label_available_at_utc.lt(min(boundary, CUTOFF))].copy()
    dates = sorted(dev.date.unique())
    if len(dates) < 180:
        raise cm.FitFailure('INSUFFICIENT_T_C_HISTORY')
    c_first = dates[-60]
    train, calibration = dev[dev.date.lt(c_first)].copy(), dev[dev.date.ge(c_first)].copy()
    if train.date.nunique() < 120 or calibration.date.nunique() != 60:
        raise cm.FitFailure('INSUFFICIENT_T_C_HISTORY')
    if train.label_available_at_utc.max() >= calibration.prediction_at_utc.min():
        raise ValueError('T labels overlap C information interval')
    if calibration.label_available_at_utc.max() >= boundary:
        raise ValueError('C labels overlap E information interval')
    return train, calibration


def segment_record(frame):
    return {'rows': len(frame), 'dates': frame.date.nunique(),
            'first_date': frame.date.min(), 'last_date': frame.date.max(),
            'label_maturity_max': frame.label_available_at_utc.max(),
            'sample_ids_sha256': identity(frame.sample_id.tolist())}


def specs_from(config):
    specs = [cm.make_spec(k, v, config[f'feature_columns_{v}'])
             for v in ('A', 'B') for k in cm.SPEC_ORDER]
    specs += [cm.make_spec('B2', v, config[f'baseline_columns_{v}']) for v in ('A', 'B')]
    return specs


def freeze(dataset, output):
    dataset, output = Path(dataset), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'frozen_protocol.json').exists() or (output / 'fit_events.jsonl').exists():
        raise ValueError('Existing freeze or fit evidence must not be overwritten')
    config = json.loads((dataset / 'data_config.json').read_text(encoding='utf-8'))
    if sha(dataset / 'panel.parquet') != config['panel_sha256']:
        raise ValueError('Panel hash changed')
    panel = validate_panel(pd.read_parquet(dataset / 'panel.parquet'), config)
    specs = specs_from(config)
    folds, ids = [], []
    for year in (*YEARS, 'FINAL'):
        boundary = CUTOFF if year == 'FINAL' else pd.Timestamp(f'{year}-01-01', tz='UTC')
        e = panel.iloc[:0] if year == 'FINAL' else panel[panel.date.str.startswith(str(year))]
        try:
            t, c = split_prefix(panel, boundary)
            enough_e = year == 'FINAL' or e.loc[e.y.notna(), 'date'].nunique() >= 60
            status, reason = ('EXECUTABLE', None) if enough_e else ('SKIPPED_INSUFFICIENT_HISTORY', 'E_HAS_FEWER_THAN_60_EVALUABLE_DATES')
        except cm.FitFailure as exc:
            t = c = panel.iloc[:0]
            status, reason = 'SKIPPED_INSUFFICIENT_HISTORY', str(exc)
        folds.append({'year': year, 'boundary_utc': boundary, 'T': segment_record(t),
                      'C': segment_record(c), 'E_prediction': segment_record(e),
                      'E_evaluable_dates': e.loc[e.y.notna(), 'date'].nunique(),
                      'status': status, 'reason': reason})
        for role, frame in [('T', t), ('C', c), ('E', e)]:
            ids.extend({'year': str(year), 'segment': role, 'sample_id': sid} for sid in frame.sample_id)
    pd.DataFrame(ids).to_parquet(output / 'fold_sample_ids.parquet', index=False)
    plan = [{'year': year, 'id': spec['id'], 'category': 'baseline' if spec['spec_id'] == 'B2' else 'candidate',
             'stages': ['base', 'calibration'], 'status': spec['status']}
            for year in YEARS for spec in specs]
    plan.append({'year': 'FINAL', 'id': 'selected_S_B', 'category': 'final',
                 'stages': ['base', 'calibration'], 'status': 'CONDITIONAL_ON_LEARNER_SELECTION'})
    parameters = {}
    for spec in specs:
        if spec['status'] == 'EXECUTABLE':
            est = cm.factory(spec)
            parameters[spec['id']] = est.get_params(deep=True)
    # String representations of estimators are metadata only; no fit occurs here.
    write_json(output / 'estimator_parameters.json', parameters)
    protocol = {'task_id': TASK_ID, 'created_before_first_fit_utc': datetime.now(timezone.utc).isoformat(),
        'dataset': str(dataset.resolve()), 'data_config_sha256': sha(dataset / 'data_config.json'),
        'panel_sha256': config['panel_sha256'], 'sample_manifest_sha256': config['sample_manifest_sha256'],
        'code_sha256': source_identity(), 'fold_sample_ids_sha256': sha(output / 'fold_sample_ids.parquet'),
        'dependencies': cm.dependency_record(), 'specifications': specs, 'folds': folds, 'fit_plan': plan,
        'fit_budget': {'candidate_base': 48, 'candidate_calibration': 48, 'baseline_base': 8,
                       'baseline_calibration': 8, 'final_base_max': 1, 'final_calibration_max': 1,
                       'planned_supervised_max': PLANNED_MAX, 'hard_supervised_cap': MAX_FITS,
                       'prior_annual_estimates': 4, 'prior_final_estimates_max': 1,
                       'transient_retries_per_stage_max': 2, 'global_retry_reserve': MAX_FITS - PLANNED_MAX,
                       'transient_types': ['TimeoutError', 'OSError'], 'synthetic_fits': 'separate test record'},
        'clock': config.get('opening_contract'), 'views': {'A': config['feature_columns_A'], 'B': config['feature_columns_B']},
        'baselines': {'B0': .5, 'B1': 'T+C day-equal upward fraction',
                      'B2_A': config['baseline_columns_A'], 'B2_B': config['baseline_columns_B']},
        'selection': {'candidate_order': list(ORDER), 'tie_tolerance': 1e-12,
                      'criterion': 'equal_trading_day_log_loss', 'prior_complete_inner_years_only': list(YEARS),
                      'missing_any_inner_fold': 'INELIGIBLE', 'selected_outer_failure': 'B1 fallback; preserve rows/reason',
                      'k_star': 'best A learner on prior complete inner years only'},
        'segments': {'T_min_dates': 120, 'C_exact_dates': 60, 'E_min_evaluable_dates': 60,
                     'maturity': 'max T maturity < first C prediction; max C maturity < E boundary',
                     'embargo': 'none; no overlapping information intervals'},
        'probabilities': {'threshold': .5, 'reliability_edges': [i / 10 for i in range(11)],
                          'main': 'C-only sigmoid calibrated', 'SVC_margin_is_not_probability': True},
        'bootstrap': {'method': 'noncircular_moving_block', 'block_dates': 20,
                      'replications': 1000, 'seed': cm.SEED, 'confidence': .95},
        'verdicts': {'minimum_outer_years': 3, 'minimum_dates': 250,
                    'predictive': 'all S_B-minus-B0/B1/B2_B CI upper < 0 => EXPLORATORY_PREDICTIVE_CANDIDATE; else NO_RELIABLE_ADVANTAGE',
                    'opening': 'k_B-minus-k_A CI upper < 0 with coverage minimum => SUPPORTED; else NOT_SUPPORTED; missing comparison/minimum => INSUFFICIENT',
                    'algorithm': 'S_B-minus-H1_B same CI/minimum rule, auxiliary only',
                    'ADOPTION_ALLOWED': False, 'LIVE_TRADING_ALLOWED': False, 'BROKER_ACTION_ALLOWED': False},
        'failure_rules': 'Single class, insufficient segment, convergence warning, invalid class direction, sigmoid optimizer failure => fixed recorded failure; unexpected implementation errors stop for audited repair; no science changes',
        'reuse': 'one annual T/C fit per identity; stored E predictions later serve completed inner years; no duplicate fitting',
        'history': 'Inherited FAST3 exposure remains; this is exploratory, not pristine holdout or proof against overfitting'}
    write_json(output / 'frozen_protocol.json', protocol)
    print(json.dumps({'freeze': str(output / 'frozen_protocol.json'), 'planned_supervised_max': PLANNED_MAX}), flush=True)
    return protocol


class Budget:
    def __init__(self, path, *, hard_cap=MAX_FITS, retry_cap=MAX_FITS - PLANNED_MAX):
        self.path, self.hard_cap, self.retry_cap = Path(path), hard_cap, retry_cap
        if self.path.exists():
            raise ValueError('Existing fit ledger requires explicit audited resume; automatic retraining forbidden')
        self.calls, self.retries, self.events = 0, 0, []

    def event(self, event):
        event = clean({'at_utc': datetime.now(timezone.utc).isoformat(), **event})
        self.events.append(event)
        with self.path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str, allow_nan=False) + '\n')

    def invoke(self, fn, *, year, model_id, category, stage, cache_key):
        for attempt in range(3):
            if self.calls >= self.hard_cap or (attempt and self.retries >= self.retry_cap):
                raise RuntimeError('SUPERVISED_FIT_BUDGET_EXHAUSTED')
            self.calls += 1
            self.retries += int(attempt > 0)
            fields = dict(fit_number=self.calls, year=str(year), model_id=model_id,
                          category=category, stage=stage, attempt=attempt, cache_key=cache_key)
            self.event({**fields, 'status': 'STARTED'})
            started = time.perf_counter()
            try:
                result = fn()
                self.event({**fields, 'status': 'FINISHED', 'elapsed_seconds': time.perf_counter() - started,
                            'metadata': result.metadata})
                return result
            except Exception as exc:
                self.event({**fields, 'status': 'FAILED', 'elapsed_seconds': time.perf_counter() - started,
                            'error': f'{type(exc).__name__}: {exc}'})
                if isinstance(exc, (OSError, TimeoutError)) and attempt < 2 and self.retries < self.retry_cap:
                    continue
                raise


def choose(history, years, view, *, learners_only=False):
    order = cm.SPEC_ORDER if learners_only else ORDER
    if not years:
        return None, []
    scores = []
    for k in order:
        model_id = k if k in ('B0', 'B1') else f'{k}_{view}'
        pieces = [history.get((year, model_id)) for year in years]
        valid = all(p is not None and len(p) >= 60 and p.log_loss.notna().all() for p in pieces)
        score = float(pd.concat(pieces).log_loss.mean()) if valid else None
        scores.append({'id': model_id, 'score': score, 'eligible': valid, 'inner_years': list(years)})
    best, best_value = None, np.inf
    for item in scores:
        if item['eligible'] and item['score'] < best_value - 1e-12:
            best, best_value = item['id'], item['score']
    return best, scores


def metric(frame, probability):
    keep = frame.y.notna() & np.isfinite(np.asarray(probability, float))
    x = frame.loc[keep].reset_index(drop=True).assign(return_3h=lambda a: a.return_remaining)
    if x.empty:
        return {}, pd.DataFrame()
    p = np.asarray(probability)[keep]
    daily = old_metrics.daily_metrics(x, p)
    total = old_metrics.aggregate_metrics(x, p, daily)
    total['auc_pooled_unweighted'] = float(roc_auc_score(x.y, p)) if x.y.nunique() == 2 else None
    return total, daily


def predictor_rows(bundle, frame, model_id):
    rows = frame.loc[:, META].copy()
    if bundle['kind'] == 'constant':
        p = np.full(len(rows), bundle['p_up'])
        outputs = {'p_up': p, 'p_not_up': 1-p, 'predicted_up': (p >= .5).astype(int),
                   'raw_score': p, 'p_raw': p}
    else:
        outputs = cm.predict(bundle['fitted'], frame)
    for name, values in outputs.items():
        rows[name] = values
    rows['model_id'] = model_id
    rows['base_fit_cutoff'] = bundle.get('base_fit_cutoff')
    rows['calibration_cutoff'] = bundle.get('calibration_cutoff')
    return rows


def fallback_rows(selected, predictions, *, role):
    selected_rows = predictions.get(selected)
    reference = predictions['B1']
    failed = (selected_rows is None or not np.isfinite(selected_rows.p_up).all()
              or selected_rows.sample_id.duplicated().any()
              or set(selected_rows.sample_id) != set(reference.sample_id))
    actual = 'B1' if failed else selected
    result = predictions[actual].copy()
    result['role'] = role
    result['selected_model_id'] = selected
    result['fallback_reason'] = f'SELECTED_MODEL_UNAVAILABLE:{selected}' if failed else None
    return result


def paired(left, right, *, expected_dates=None):
    x = left[['date', 'log_loss']].merge(right[['date', 'log_loss']], on='date',
                                       suffixes=('_left', '_right'), validate='one_to_one')
    if len(x) < 20:
        return {'status': 'INSUFFICIENT', 'dates': len(x)}, x
    delta = (x.log_loss_left - x.log_loss_right).to_numpy()
    rng = np.random.default_rng(cm.SEED)
    starts = rng.integers(0, len(x) - 20 + 1, size=(1000, int(np.ceil(len(x) / 20))))
    indices = (starts[:, :, None] + np.arange(20)).reshape(1000, -1)[:, :len(x)]
    replicates = delta[indices].mean(axis=1)
    low, high = np.quantile(replicates, [.025, .975])
    years = x.date.str[:4].nunique()
    complete = expected_dates is None or len(x) == expected_dates
    x['delta_log_loss'] = delta
    return {'status': 'OK' if complete else 'INCOMPLETE_COMPARISON', 'dates': len(x), 'years': years,
            'delta_log_loss': float(delta.mean()), 'ci95_low': float(low), 'ci95_high': float(high),
            'minimum_met': bool(complete and years >= 3 and len(x) >= 250)}, x


def fit_one(spec, t, c, *, year, protocol, output, budget, category):
    # Deterministic rejects occur before the actual supervised-fit counter starts.
    cm._segment(t.y, t.date, t.label_available_at_utc, kind='T')
    cm._segment(c.y, c.date, c.label_available_at_utc, kind='C')
    cm.features(t, spec['columns'])
    cm.features(c, spec['columns'])
    cm.factory(spec)
    if t.label_available_at_utc.max() >= c.prediction_at_utc.min():
        raise cm.FitFailure('T_C_OVERLAP_OR_UNMATURED_LABEL')
    key = identity({'spec': spec, 'T_ids': t.sample_id.tolist(), 'C_ids': c.sample_id.tolist(),
                    'input': protocol['panel_sha256'], 'code': protocol['code_sha256'],
                    'dependencies': protocol['dependencies']})
    base = budget.invoke(lambda: cm.fit_base(spec, t, t.y, t.date, label_available_at=t.label_available_at_utc),
                         year=year, model_id=spec['id'], category=category, stage='base', cache_key=key)
    calibrated = budget.invoke(lambda: cm.fit_calibrator(base, c, c.y, c.date, label_available_at=c.label_available_at_utc),
                               year=year, model_id=spec['id'], category=category, stage='calibration', cache_key=key)
    bundle = {'kind': 'learner', 'fitted': calibrated, 'model_id': spec['id'], 'task_id': TASK_ID,
              'columns': spec['columns'], 'cache_key': key, 'protocol_sha256': sha(output / 'frozen_protocol.json'),
              'base_fit_cutoff': base.metadata['max_label_available_at'],
              'calibration_cutoff': calibrated.metadata['max_label_available_at'],
              'ADOPTION_ALLOWED': False, 'LIVE_TRADING_ALLOWED': False, 'BROKER_ACTION_ALLOWED': False}
    joblib.dump(bundle, output / 'models' / f'{year}_{spec["id"]}.joblib', compress=3)
    return bundle


def train(dataset, output):
    dataset, output = Path(dataset), Path(output)
    protocol = json.loads((output / 'frozen_protocol.json').read_text(encoding='utf-8'))
    config = json.loads((dataset / 'data_config.json').read_text(encoding='utf-8'))
    if (protocol['task_id'] != TASK_ID or protocol['code_sha256'] != source_identity()
            or protocol['dependencies'] != cm.dependency_record()):
        raise ValueError('Code changed after freeze; no hot change or stale reuse')
    for path, expected in [(dataset / 'panel.parquet', protocol['panel_sha256']),
                           (dataset / 'data_config.json', protocol['data_config_sha256']),
                           (output / 'fold_sample_ids.parquet', protocol['fold_sample_ids_sha256'])]:
        if sha(path) != expected:
            raise ValueError(f'Frozen identity mismatch: {path}')
    panel = validate_panel(pd.read_parquet(dataset / 'panel.parquet'), config)
    if specs_from(config) != protocol['specifications']:
        raise ValueError('Frozen model specs or dependency choice changed')
    (output / 'models').mkdir(exist_ok=True)
    budget = Budget(output / 'fit_events.jsonl')
    history, all_predictions, flow_predictions, diagnostics, selections, failures, prior_estimates = {}, [], [], [], [], [], []
    for year in YEARS:
        # Selection occurs before this year's scoring or outcomes are used by the loop.
        inner_years = [y for y in YEARS if y < year]
        a, scores_a = choose(history, inner_years, 'A')
        b, scores_b = choose(history, inner_years, 'B')
        k, scores_k = choose(history, inner_years, 'A', learners_only=True)
        selection = {'outer_year': year, 'inner_years': inner_years, 'S_A': a, 'S_B': b, 'k_A': k,
                     'scores_A': scores_a, 'scores_B': scores_b, 'scores_k': scores_k,
                     'status': 'SELECTED' if a and b else 'SKIPPED_INSUFFICIENT_HISTORY'}
        selections.append(selection)
        write_json(output / 'selection_audit.json', selections)
        e = panel[panel.date.str.startswith(str(year))].copy()
        try:
            t, c = split_prefix(panel, pd.Timestamp(f'{year}-01-01', tz='UTC'))
        except cm.FitFailure as exc:
            failures.append({'year': year, 'scope': 'annual', 'reason': str(exc)})
            continue
        dev = pd.concat([t, c])
        prior = float(dev.groupby('date').y.mean().mean())
        prior_estimates.append({'year': year, 'p_up': prior, 'segment': segment_record(dev)})
        predictions = {}
        for name, p in [('B0', .5), ('B1', prior)]:
            bundle = {'kind': 'constant', 'task_id': TASK_ID, 'model_id': name, 'p_up': p,
                      'base_fit_cutoff': dev.label_available_at_utc.max().isoformat() if name == 'B1' else None,
                      'calibration_cutoff': None}
            predictions[name] = predictor_rows(bundle, e, name)
            joblib.dump(bundle, output / 'models' / f'{year}_{name}.joblib')
        for spec in protocol['specifications']:
            if spec['status'] != 'EXECUTABLE':
                failures.append({'year': year, 'model_id': spec['id'], 'reason': 'SKIPPED_DEPENDENCY'})
                continue
            print(json.dumps({'year': year, 'model': spec['id'], 'T_rows': len(t), 'C_rows': len(c), 'fits_so_far': budget.calls}), flush=True)
            try:
                bundle = fit_one(spec, t, c, year=year, protocol=protocol, output=output, budget=budget,
                                 category='baseline' if spec['spec_id'] == 'B2' else 'candidate')
                for segment_name, segment in [('T', t), ('C', c), ('E', e)]:
                    rows = predictor_rows(bundle, segment, spec['id'])
                    total, _ = metric(rows, rows.p_up)
                    raw_total, _ = metric(rows, rows.p_raw)
                    diagnostics.append({'year': year, 'model_id': spec['id'], 'segment': segment_name,
                                        'calibrated': total, 'raw_probability': raw_total,
                                        'calibration': bundle['fitted'].metadata})
                    if segment_name == 'E':
                        predictions[spec['id']] = rows
            except cm.FitFailure as exc:
                failures.append({'year': year, 'model_id': spec['id'], 'reason': str(exc)})
            # Unclassified engineering errors stop, preserving the ledger and no altered science.
        for name, rows in predictions.items():
            rows['evaluation_year'] = year
            total, daily = metric(rows, rows.p_up)
            if len(daily) >= 60:
                history[(year, name)] = daily
            all_predictions.append(rows)
        pd.concat(predictions.values(), ignore_index=True).to_parquet(output / f'annual_predictions_{year}.parquet', index=False)
        enough_e = e.loc[e.y.notna(), 'date'].nunique() >= 60
        if not enough_e:
            selection['status'] = 'SKIPPED_INSUFFICIENT_HISTORY'
            selection['reason'] = 'E_HAS_FEWER_THAN_60_EVALUABLE_DATES'
            write_json(output / 'selection_audit.json', selections)
        if a and b and enough_e:
            for role, selected in [('S_A', a), ('S_B', b)]:
                flow_predictions.append(fallback_rows(selected, predictions, role=role))
            for name in ('B0', 'B1', 'B2_A', 'B2_B', 'H1_B'):
                if name in predictions:
                    flow_predictions.append(predictions[name].assign(role=name, selected_model_id=name, fallback_reason=None))
            if k:
                kb = k[:-1] + 'B'
                for name, role in [(k, 'k_A'), (kb, 'k_B')]:
                    if name in predictions:
                        flow_predictions.append(predictions[name].assign(role=role, selected_model_id=name, fallback_reason=None))
        write_json(output / 'failures.json', failures)
        write_json(output / 'diagnostics.json', diagnostics)
    if not flow_predictions:
        raise cm.FitFailure('NO_VALID_OUTER_SELECTION_YEARS')
    annual = pd.concat(all_predictions, ignore_index=True)
    annual.to_parquet(output / 'all_candidate_predictions.parquet', index=False)
    flows = pd.concat(flow_predictions, ignore_index=True)
    flows.to_parquet(output / 'outer_predictions.parquet', index=False)
    final_id, final_scores = choose(history, list(YEARS), 'B')
    if final_id is None:
        final_id = 'B1'
        final_fallback = 'NO_COMPLETE_INTERNAL_CANDIDATE'
    else:
        final_fallback = None
    t, c = split_prefix(panel, CUTOFF)
    if final_id in ('B0', 'B1'):
        dev = pd.concat([t, c])
        probability = .5 if final_id == 'B0' else float(dev.groupby('date').y.mean().mean())
        if final_id == 'B1':
            prior_estimates.append({'year': 'FINAL', 'p_up': probability, 'segment': segment_record(dev)})
        final = {'kind': 'constant', 'model_id': final_id, 'task_id': TASK_ID, 'p_up': probability,
                 'base_fit_cutoff': dev.label_available_at_utc.max().isoformat() if final_id == 'B1' else None,
                 'calibration_cutoff': None, 'columns': [], 'fallback_reason': final_fallback}
    else:
        spec = next(s for s in protocol['specifications'] if s['id'] == final_id)
        try:
            final = fit_one(spec, t, c, year='FINAL', protocol=protocol, output=output, budget=budget, category='final')
        except cm.FitFailure as exc:
            dev = pd.concat([t, c])
            probability = float(dev.groupby('date').y.mean().mean())
            prior_estimates.append({'year': 'FINAL', 'p_up': probability, 'segment': segment_record(dev)})
            final = {'kind': 'constant', 'model_id': 'B1', 'task_id': TASK_ID, 'p_up': probability,
                     'base_fit_cutoff': dev.label_available_at_utc.max().isoformat(), 'calibration_cutoff': None,
                     'columns': [], 'fallback_reason': f'SELECTED_FINAL_FAILED:{final_id}:{exc}'}
            failures.append({'year': 'FINAL', 'model_id': final_id, 'reason': str(exc)})
    final.update(ADOPTION_ALLOWED=False, LIVE_TRADING_ALLOWED=False, BROKER_ACTION_ALLOWED=False,
                 selection_id=final_id, selection_scores=final_scores,
                 role='NO_MODEL_SIGNAL' if final['kind'] == 'constant' else 'RESEARCH_ONLY_CALIBRATED_MODEL')
    joblib.dump(final, output / 'final_research_predictor.joblib', compress=3)
    write_json(output / 'final_model.json', {k: v for k, v in final.items() if k != 'fitted'})
    write_json(output / 'prior_estimates.json', prior_estimates)
    write_json(output / 'failures.json', failures)
    start_events = [x for x in budget.events if x['status'] == 'STARTED']
    counts = {'supervised_total': budget.calls, 'retries': budget.retries, 'prior_estimates': len(prior_estimates),
              'by_category_stage': pd.Series([x['category'] + '_' + x['stage'] for x in start_events]).value_counts().to_dict(),
              'successful_supervised': sum(x['status'] == 'FINISHED' for x in budget.events),
              'failed_supervised': sum(x['status'] == 'FAILED' for x in budget.events),
              'annual_fitted_identity_reuse': 'Stored annual models/predictions used for later inner selection and current outer roles; zero duplicate fits',
              'inner_cache_reference_years': {str(y): [a for a in YEARS if a < y] for y in YEARS},
              'saved_annual_learner_identities': sum(1 for p in (output / 'models').glob('20*_*.joblib') if p.stem.split('_', 1)[1] not in ('B0', 'B1')),
              'saved_annual_constant_identities': sum(1 for p in (output / 'models').glob('20*_*.joblib') if p.stem.split('_', 1)[1] in ('B0', 'B1')),
              'inner_score_table_references': sum(len(s['inner_years']) for item in selections for category in ('scores_A', 'scores_B', 'scores_k') for s in item[category]) + sum(len(s['inner_years']) for s in final_scores),
              'outer_selected_prediction_references': sum(flows.loc[flows.role.eq(role)].evaluation_year.nunique() for role in ('S_A', 'S_B', 'k_A', 'k_B')),
              'planned_candidate_configurations': 12,
              'executable_candidate_configurations': sum(s['status'] == 'EXECUTABLE' and s['spec_id'] != 'B2' for s in protocol['specifications']),
              'successful_candidate_configurations': annual.loc[~annual.model_id.str.startswith('B'), 'model_id'].nunique(),
              'planned_families': 4,
              'executable_families': len({s['family'] for s in protocol['specifications'] if s['status'] == 'EXECUTABLE' and s['spec_id'] != 'B2'})}
    write_json(output / 'fit_counts.json', counts)
    result = evaluate(flows, annual, output)
    result.update(EXECUTION_STATUS='COMPLETED', FINAL_MODEL_ROLE=final['role'], final_model_id=final['model_id'],
                  base_fit_cutoff=final['base_fit_cutoff'], calibration_cutoff=final['calibration_cutoff'],
                  fit_counts=counts, failures=failures, ADOPTION_ALLOWED=False,
                  LIVE_TRADING_ALLOWED=False, BROKER_ACTION_ALLOWED=False)
    write_json(output / 'result.json', result)
    print(json.dumps(clean(result), ensure_ascii=False), flush=True)
    return result


def evaluate(flows, annual, output):
    totals, dailies, grouped, reliability = {}, {}, [], []
    for role, rows in flows.groupby('role', sort=True):
        total, daily = metric(rows, rows.p_up)
        totals[role], dailies[role] = total, daily
        valid = rows.y.notna() & np.isfinite(rows.p_up)
        x = rows.loc[valid].reset_index(drop=True).assign(return_3h=lambda a: a.return_remaining)
        reliability.extend(old_metrics._reliability(x, x.p_up.to_numpy(), role))
        for dimension in ('evaluation_year', 'ticker'):
            for value, piece in rows.groupby(dimension):
                stat, _ = metric(piece, piece.p_up)
                grouped.append({'role': role, 'dimension': dimension, 'value': value, **stat})
    daily_all = pd.concat([d.assign(role=k) for k, d in dailies.items()], ignore_index=True)
    daily_all.to_parquet(output / 'outer_daily_metrics.parquet', index=False)
    write_json(output / 'metrics.json', totals)
    write_json(output / 'grouped_metrics.json', grouped)
    write_json(output / 'reliability.json', reliability)
    comparisons, deltas = {}, []
    n_dates = totals.get('S_B', {}).get('dates', 0)
    for left, right in [('S_B', 'B0'), ('S_B', 'B1'), ('S_B', 'B2_B'), ('S_B', 'S_A'), ('k_B', 'k_A'), ('S_B', 'H1_B')]:
        key = left + '_minus_' + right
        if left in dailies and right in dailies:
            result, data = paired(dailies[left], dailies[right], expected_dates=n_dates)
            comparisons[key] = result
            deltas.append(data.assign(comparison=key))
        else:
            comparisons[key] = {'status': 'INSUFFICIENT', 'minimum_met': False}
    pd.concat(deltas, ignore_index=True).to_parquet(output / 'paired_daily_deltas.parquet', index=False)
    write_json(output / 'comparisons.json', comparisons)
    descriptive = []
    for name, rows in annual.groupby('model_id'):
        # 2022 remains an inner scoring year; descriptive outer comparison uses the same 2023+ dates.
        rows = rows[rows.date.isin(dailies['S_B'].date)]
        stat, _ = metric(rows, rows.p_up)
        descriptive.append({'model_id': name, 'scope': 'descriptive_fixed_outer_dates', **stat})
    write_json(output / 'all_candidate_metrics.json', descriptive)
    ab = {}
    for k in cm.SPEC_ORDER:
        a = annual[(annual.model_id == f'{k}_A') & annual.date.isin(dailies['S_B'].date)]
        b = annual[(annual.model_id == f'{k}_B') & annual.date.isin(dailies['S_B'].date)]
        _, da = metric(a, a.p_up)
        _, db = metric(b, b.p_up)
        ab[k] = paired(db, da, expected_dates=n_dates)[0] if len(da) and len(db) else {'status': 'INSUFFICIENT'}
    write_json(output / 'descriptive_all_spec_AB.json', ab)
    primary = [comparisons['S_B_minus_' + name] for name in ('B0', 'B1', 'B2_B')]
    enough = all(x.get('minimum_met', False) for x in primary)
    predictive = ('EXPLORATORY_PREDICTIVE_CANDIDATE' if all(x['ci95_high'] < 0 for x in primary)
                  else 'NO_RELIABLE_ADVANTAGE') if enough else 'INSUFFICIENT_EVIDENCE'
    def verdict(comparison):
        if not comparison.get('minimum_met', False):
            return 'INSUFFICIENT'
        return 'SUPPORTED' if comparison['ci95_high'] < 0 else 'NOT_SUPPORTED'
    coverage = flows[flows.role == 'S_B']
    return {'PREDICTIVE_VERDICT': predictive,
            'OPENING_INFORMATION_VERDICT': verdict(comparisons['k_B_minus_k_A']),
            'ALGORITHM_COMPARISON_VERDICT': verdict(comparisons['S_B_minus_H1_B']),
            'main_metrics': totals['S_B'], 'comparisons': comparisons,
            'outer_predictions': len(coverage), 'outer_prediction_dates': coverage.date.nunique(),
            'outer_unlabelled_predictions': int(coverage.y.isna().sum()),
            'fallback_rows': int(coverage.fallback_reason.notna().sum()),
            'selection_frequency_by_year': coverage.groupby('evaluation_year').selected_model_id.first().to_dict()}


def predict_final(bundle, frame):
    """Minimal feature-only interface. Historical replay is not additional OOS evidence."""
    if bundle.get('task_id') != TASK_ID:
        raise ValueError('Wrong task model')
    required = ['security_uid', 'ticker', 'date', 'prediction_at_utc', 'feature_cutoff_utc',
                'label_start_utc', 'label_end_utc', *bundle.get('columns', [])]
    if set(required) - set(frame):
        raise ValueError(f'Missing feature/clock fields: {sorted(set(required) - set(frame))}')
    for name, clock in [('prediction_at_utc', '09:45'), ('feature_cutoff_utc', '09:44'),
                        ('label_start_utc', '09:46'), ('label_end_utc', '12:30')]:
        timestamp = pd.to_datetime(frame[name], utc=True).dt.tz_convert('America/New_York')
        if not timestamp.dt.strftime('%H:%M').eq(clock).all() or not timestamp.dt.strftime('%Y-%m-%d').eq(frame.date).all():
            raise ValueError('Inference clock mismatch')
    if bundle['kind'] == 'constant':
        p = np.full(len(frame), bundle['p_up'])
    else:
        p = cm.predict(bundle['fitted'], frame)['p_up']
    out = frame[['security_uid', 'ticker', 'date', 'prediction_at_utc', 'feature_cutoff_utc', 'label_start_utc', 'label_end_utc']].rename(
        columns={'date': 'decision_date', 'prediction_at_utc': 'prediction_timestamp',
                 'feature_cutoff_utc': 'feature_cutoff', 'label_start_utc': 'label_start', 'label_end_utc': 'label_end'})
    out = out.copy()
    out['p_up'], out['p_not_up'], out['predicted_up'] = p, 1-p, (p >= .5).astype(int)
    out['model_id'] = bundle['model_id']
    out['base_fit_cutoff'], out['calibration_cutoff'] = bundle['base_fit_cutoff'], bundle['calibration_cutoff']
    missing = frame[bundle.get('columns', [])].isna().mean(axis=1).fillna(0)
    out['data_quality'] = ['MISSING_FEATURE_FRACTION=' + format(v, '.6f') for v in missing]
    out['fallback_reason'] = bundle.get('fallback_reason')
    return out
