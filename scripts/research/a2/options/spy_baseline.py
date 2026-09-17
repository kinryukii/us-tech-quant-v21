"""One frozen SPY2024 exploratory logit; completed folds are never fitted again."""
from __future__ import annotations

import hashlib
import argparse
import inspect
import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from scripts.common.storage_paths import resolve
from .contracts import TEMPLATE, calendar, require

FEATURES = ['r5', 'r20', 'v20']
DATES = ['reference_date', 'entry_date', 'exit_date']
PARAMS = dict(C=0.1, solver='lbfgs', fit_intercept=True, class_weight=None, max_iter=2000, tol=1e-6)
SPEC = dict(model='StandardScaler_L2_LogisticRegression', params=PARAMS,
            features=FEATURES, months=[f'2024-{m:02d}' for m in range(7, 13)],
            maturity='exit_date < first_planned_entry_of_month', years=[2024],
            label='CLOSED AND conditional_wealth_difference > domain.tolerance_usd',
            log_loss_clip='numpy.float64 machine epsilon', final_refit=False)


def _hash(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def _save(path, obj):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(obj, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def _dates(frame, columns):
    for column in columns:
        d = pd.to_datetime(frame[column], errors='raise')
        require(d.notna().all() and d.dt.year.eq(2024).all() and
                d.eq(d.dt.normalize()).all(), 'BASELINE_ECONOMIC_DATE_OUTSIDE_2024')


def project(reference_prices, observed_csv, manifest):
    """Date-only CSV projection must pass before any economic label is read."""
    plan = pd.DataFrame(manifest['plan'])[['decision_id'] + DATES]
    _dates(plan, DATES)
    require(len(plan) == 246 and plan.decision_id.is_unique and plan.entry_date.is_unique,
            'BASELINE_PLAN_INVALID')
    require(((plan.reference_date < plan.entry_date) & (plan.entry_date < plan.exit_date)).all(),
            'BASELINE_PLAN_ORDER')
    key = pd.read_csv(observed_csv, usecols=['decision_id'] + DATES)
    require(key.equals(plan[key.columns]), 'BASELINE_OBSERVATION_PLAN_CHANGED')
    prices = reference_prices.sort_values('date').copy()
    _dates(prices, ['date'])
    require(len(prices) == 246 and prices.date.is_unique and
            set(prices.date) == set(plan.reference_date), 'BASELINE_REFERENCE_INCOMPLETE')
    require(prices.ticker.eq('SPY').all() and prices.currency.eq('USD').all() and
            prices.adjustment.eq('raw').all() and np.isfinite(prices.close).all() and
            prices.close.gt(0).all(), 'BASELINE_REFERENCE_NOT_RAW_USD')
    continuity = manifest['model_feature_continuity']
    require(continuity['status'] == 'CONTINUOUS_TRADE_BASIS_2024' and continuity['evidence_ref'],
            'BASELINE_FEATURE_UNIT_CONTINUITY_UNPROVEN')
    evidence = continuity['evidence_ref']
    require(_hash(evidence['path']) == evidence['sha256'], 'BASELINE_CONTINUITY_EVIDENCE_CHANGED')
    sessions = calendar().sessions
    expected = sessions[(sessions >= prices.date.min()) & (sessions <= prices.date.max())]
    require(list(prices.date) == list(expected.strftime('%Y-%m-%d')), 'BASELINE_PRICE_SESSION_GAP')
    changes = np.log(prices.close).diff()
    prices['r5'] = np.log(prices.close / prices.close.shift(5))
    prices['r20'] = np.log(prices.close / prices.close.shift(20))
    prices['v20'] = changes.rolling(20).std(ddof=1)
    labels = pd.read_csv(observed_csv, usecols=['decision_id', 'cash_status', 'cash_reason',
                                              'conditional_wealth_difference'], float_precision='round_trip')
    panel = plan.merge(prices[['date'] + FEATURES], left_on='reference_date', right_on='date',
                       validate='one_to_one').drop(columns='date').merge(labels, validate='one_to_one')
    difference = panel.conditional_wealth_difference
    resolved = panel.cash_status.eq('CLOSED') & np.isfinite(difference)
    require(not (difference.notna() & ~resolved).any(), 'BASELINE_UNRESOLVED_AMOUNT_PRESENT')
    panel['label'] = np.where(resolved, (difference > manifest['domain']['tolerance_usd']).astype(int), np.nan)
    panel['feature_status'] = np.where(panel[FEATURES].notna().all(axis=1), 'READY', 'WARMUP')
    return panel


def fit_fold(train, first_entry):
    """Hard boundary immediately before the real scaler/model fit entry."""
    _dates(train, DATES)
    _dates(pd.DataFrame({'date': [first_entry]}), ['date'])
    require((train.reference_date < train.entry_date).all() and (train.entry_date < train.exit_date).all() and
            (train.exit_date < first_entry).all() and
            train[FEATURES].notna().all().all() and train.label.isin([0, 1]).all() and
            train.label.nunique() == 2, 'BASELINE_FIT_SCOPE_OR_MATURITY')
    modern = inspect.signature(LogisticRegression).parameters['penalty'].default == 'deprecated'
    l2 = {'l1_ratio': 0.0} if modern else {'penalty': 'l2'}
    model = make_pipeline(StandardScaler(), LogisticRegression(**PARAMS, **l2))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        model.fit(train[FEATURES], train.label.astype(int))
    return model, [str(w.message) for w in caught]


def _metrics(rows):
    valid = rows.label.notna() & rows.probability.notna()
    y = rows.loc[valid, 'label'].to_numpy()
    result = {'evaluated': int(valid.sum())}
    for column in ['probability', 'baseline_probability']:
        p = rows.loc[valid, column].to_numpy()
        clipped = np.clip(p, np.finfo(np.float64).eps, 1 - np.finfo(np.float64).eps)
        result[column] = dict(brier=float(np.mean((p-y)**2)) if len(y) else None,
                              log_loss=float(-np.mean(y*np.log(clipped)+(1-y)*np.log1p(-clipped))) if len(y) else None)
    return result


def run_baseline(reference_prices, observed_csv, output, manifest):
    """Use the caller's one frozen manifest; outputs must stay in its results run."""
    output, manifest, observed_csv = Path(output).resolve(), Path(manifest).resolve(), Path(observed_csv).resolve()
    allowed = resolve().results_root / TEMPLATE / 'spy2024_complete_compat_train'
    require(allowed in output.parents and manifest.parent == output, 'BASELINE_OUTPUT_BOUNDARY')
    m = json.loads(manifest.read_text(encoding='utf-8'))
    require(m['model_spec'] == SPEC and m['model_candidate_count_added'] == 1 and
            m['model_spec_frozen_at'], 'BASELINE_SPEC_NOT_FROZEN')
    observed_hash = _hash(observed_csv)
    panel = project(reference_prices, observed_csv, m)
    require(observed_hash == _hash(observed_csv), 'BASELINE_INPUT_CHANGED_DURING_READ')
    fingerprint = hashlib.sha256(panel.to_csv(index=False).encode()).hexdigest()
    state = m.setdefault('model_baseline', dict(status='NOT_RUN', input_sha256=fingerprint,
                         observed_sha256=observed_hash, folds={}, model_fit_attempts=0,
                         sklearn_version=sklearn.__version__, network_requests=0))
    require(state['input_sha256'] == fingerprint and state['observed_sha256'] == observed_hash,
            'BASELINE_RESUME_INPUT_CHANGED')
    if state['status'] in ('COMPLETE', 'NOT_RUN_NO_EXECUTABLE_FOLD'):
        require(all(_hash(output / f) == h for f, h in state['artifacts'].items()), 'BASELINE_ARTIFACT_CHANGED')
        return state
    panel.to_csv(output / 'feature_labels.csv', index=False)
    oof = panel.copy()
    oof['probability'], oof['baseline_probability'] = np.nan, np.nan
    oof['prediction_status'] = 'NOT_VALIDATION_PERIOD'
    gate = {'active': True}
    def deny_network(event, args):
        if gate['active'] and event in ('socket.connect', 'socket.getaddrinfo', 'socket.sendto'):
            raise RuntimeError('BASELINE_NETWORK_FORBIDDEN')
    sys.addaudithook(deny_network)
    try:
        for month in SPEC['months']:
            mask = panel.entry_date.str.startswith(month)
            first = panel.loc[mask, 'entry_date'].min()
            require(isinstance(first, str), 'BASELINE_EMPTY_FIXED_MONTH')
            train = panel.loc[(panel.exit_date < first) & panel.label.notna() & panel.feature_status.eq('READY')]
            valid = mask & panel.feature_status.eq('READY')
            fold = state['folds'].get(month)
            model_file = output / f'model_{month}.joblib'
            if fold is None:
                fold = dict(first_entry=first, training_rows=len(train),
                            training_label_max=train.exit_date.max() if len(train) else None,
                            planned=int(mask.sum()), missing_features=int((mask & ~valid).sum()),
                            missing_labels=int((mask & panel.label.isna()).sum()), status='NOT_FITTED_SINGLE_CLASS_OR_EMPTY')
                state['folds'][month] = fold
                if train.label.nunique() == 2 and valid.any():
                    require(state['model_fit_attempts'] < 6, 'BASELINE_FIT_BUDGET')
                    fold['status'] = 'FIT_STARTED'
                    state['model_fit_attempts'] += 1
                    _save(manifest, m)
                    model, messages = fit_fold(train, first)
                    joblib.dump(model, model_file)
                    scaler, logit = model.steps[0][1], model.steps[1][1]
                    fold.update(status='FITTED', sha256=_hash(model_file), warnings=messages,
                                converged=not any('converg' in w.lower() for w in messages),
                                training_positive_rate=float(train.label.mean()),
                                scaler_mean=scaler.mean_.tolist(), scaler_scale=scaler.scale_.tolist(),
                                coefficients=logit.coef_.tolist(), intercept=logit.intercept_.tolist(),
                                actual_logit_params=logit.get_params(),
                                fitted_at=datetime.now(timezone.utc).isoformat())
                _save(manifest, m)
            # An interrupted fit consumes its attempt; later months remain independently executable.
            oof.loc[mask, 'prediction_status'] = fold['status']
            oof.loc[mask & ~valid, 'prediction_status'] = 'MISSING_FEATURES'
            if fold['status'] == 'FITTED':
                require(_hash(model_file) == fold['sha256'], 'BASELINE_MODEL_CHANGED')
                model = joblib.load(model_file)
                oof.loc[valid, 'probability'] = model.predict_proba(panel.loc[valid, FEATURES])[:, 1]
                oof.loc[valid, 'baseline_probability'] = fold['training_positive_rate']
                oof.loc[valid, 'prediction_status'] = 'PREDICTED'
            fold['metrics'] = _metrics(oof.loc[mask])
        oof.to_csv(output / 'oof.csv', index=False)
        artifacts = ['feature_labels.csv', 'oof.csv'] + [f'model_{m}.joblib' for m, f in state['folds'].items() if f['status'] == 'FITTED']
        fitted = sum(f['status'] == 'FITTED' for f in state['folds'].values())
        uncertain = any(f['status'] == 'FIT_STARTED' for f in state['folds'].values())
        state.update(status='PARTIAL_UNCERTAIN_FIT' if uncertain else ('COMPLETE' if fitted else 'NOT_RUN_NO_EXECUTABLE_FOLD'), successful_fits=fitted,
                     predicted=int(oof.probability.notna().sum()), metrics=_metrics(oof),
                     artifacts={f: _hash(output / f) for f in artifacts},
                     limits=['EXPOSED_SINGLE_YEAR_EXPLORATORY', 'CONDITIONAL_ARCHIVE_LABEL',
                             'COMPLETE_CASE_MISSING_SELECTION', 'SOURCE_RECONSTRUCTED_TIMING'])
        _save(manifest, m)
        return state
    finally:
        gate['active'] = False


def main(argv=None):
    """Resume qualified local checkpoints; acquisition remains the task's recorded source step."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args(argv)
    output = args.output.resolve()
    allowed = resolve().results_root / TEMPLATE / 'spy2024_complete_compat_train'
    require(allowed == output.parent, 'BASELINE_OUTPUT_BOUNDARY')
    registration = json.loads((output / 'run_manifest.json').read_text(encoding='utf-8'))
    require(registration['task_id'] == 'OPTIONS_SPY2024_COMPLETE_COMPAT_TRAIN_R1' and
            registration['model_spec'] == SPEC and registration['model_candidate_count_added'] == 1 and
            registration['model_spec_frozen_at'], 'BASELINE_TASK_OR_REGISTRATION_CHANGED')
    binding_path, observed = output / 'reference_binding.json', output / 'observed'
    if not binding_path.exists():
        print(json.dumps(dict(status='INCOMPLETE_REFERENCE_INPUT', model_fit=0, network_requests=0)))
        return 2
    from .price_basis import STATUS, read_trade_references
    binding = json.loads(binding_path.read_text(encoding='utf-8'))
    additions = binding.get('reference_additions', {})
    if additions.get('qualification', {}).get('status') != STATUS:
        print(json.dumps(dict(status='INCOMPLETE_REFERENCE_INPUT', model_fit=0, network_requests=0)))
        return 2
    observed_manifest = observed / 'run_manifest.json'
    completed = observed_manifest.exists() and json.loads(observed_manifest.read_text(encoding='utf-8')).get('status') == 'COMPLETE_CONDITIONAL_ARCHIVE_DIAGNOSTIC'
    if not completed:
        read_trade_references(additions, additions['allowed_reference_dates'])
        from .cli import main as observed_cli
        command = ['--mode', 'spy2024-observed-frontier', '--output', str(observed), '--offline']
        if not observed_manifest.exists():
            command += ['--reference-override', str(binding_path)]
        require(observed_cli(command) == 0, 'BASELINE_OBSERVED_STAGE_FAILED')
    diagnostic = json.loads(observed_manifest.read_text(encoding='utf-8'))
    require(diagnostic['reference_override']['sha256'] == _hash(binding_path) and
            diagnostic['result_sha256'] == _hash(observed / 'observed_frontier.csv'), 'BASELINE_OBSERVED_CHECKPOINT_CHANGED')
    records = diagnostic['entry_lock']['records']
    encoded = json.dumps(records, sort_keys=True, separators=(',', ':'), allow_nan=False)
    require(hashlib.sha256(encoded.encode()).hexdigest() == diagnostic['entry_lock']['sha256'], 'BASELINE_ENTRY_LOCK_CHANGED')
    references = pd.DataFrame([dict(date=r['reference_date'], close=r['reference_close'], ticker='SPY',
                                   currency='USD', adjustment='raw') for r in records])
    complete = int((references.close.notna() & references.close.gt(0)).sum())
    if complete != 246:
        print(json.dumps(dict(status='INCOMPLETE_REFERENCE_INPUT', complete_references=complete,
                              model_status='NOT_RUN_PRICE_INCOMPLETE', diagnostic='COMPLETE', model_fit=0, network_requests=0)))
        return 2
    result = run_baseline(references, observed / 'observed_frontier.csv', output, output / 'run_manifest.json')
    print(json.dumps(result))
    return 0 if result['status'] == 'COMPLETE' else 2


if __name__ == '__main__':
    raise SystemExit(main())
