"""No-estimator-fit tests of the bounded annual FAST3 study control flow."""
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import joblib
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, 'D:/us-tech-quant')
# Permit this file's pre-install staging check while retaining the canonical
# package and existing metrics module. Installed runs resolve installed modules.
package = importlib.import_module('scripts.research.fast3')
if str(Path(__file__).parent) not in package.__path__:
    package.__path__.append(str(Path(__file__).parent))
from scripts.research.fast3 import opening_study as s


def panel(dates):
    x = pd.MultiIndex.from_product([dates, ['AMD', 'AVGO', 'ENPH', 'NVDA']],
                                  names=['date', 'ticker']).to_frame(index=False)
    x['sample_id'] = x.ticker+'|'+x.date
    x['security_uid'], x['eligible'] = x.ticker, True
    for name, clock in [('prediction_at_utc', '09:45'), ('feature_cutoff_utc', '09:44'),
                        ('label_start_utc', '09:46'), ('label_end_utc', '12:30'),
                        ('label_available_at_utc', '12:31')]:
        x[name] = pd.to_datetime(x.date+' '+clock).dt.tz_localize('America/New_York').dt.tz_convert('UTC')
    x['y'] = np.arange(len(x)) % 2
    x['return_remaining'] = np.where(x.y.eq(1), .01, -.01)
    x['label_reason'] = 'OK'
    features = pd.DataFrame({f'f{i}': np.ones(len(x)) for i in range(93)})
    return pd.concat([x, features], axis=1)


def config():
    return {'feature_columns_A': [f'f{i}' for i in range(75)],
            'feature_columns_B': [f'f{i}' for i in range(93)],
            'baseline_columns_A': ['f0'], 'baseline_columns_B': ['f0', 'f75']}


def daily(year=2022, value=.69, n=60):
    return pd.DataFrame({'date': pd.bdate_range(f'{year}-01-03', periods=n).strftime('%Y-%m-%d'),
                         'log_loss': np.full(n, value)})


def invoke(budget, fn):
    return budget.invoke(fn, year=2022, model_id='H1_A', category='candidate', stage='base', cache_key='key')


def test_split_has_complete_days_120_T_and_last_60_C_with_maturity():
    dates = pd.bdate_range('2021-01-04', periods=181).strftime('%Y-%m-%d').tolist()
    x = panel(dates)
    boundary = x.prediction_at_utc.max()+pd.Timedelta(days=1)
    t, c = s.split_prefix(x, boundary)
    assert t.date.nunique() == 121
    assert c.date.nunique() == 60
    assert c.date.min() == dates[-60]
    assert set(t.sample_id).isdisjoint(c.sample_id)
    assert t.groupby('date').size().eq(4).all()
    assert c.groupby('date').size().eq(4).all()
    assert t.label_available_at_utc.max() < c.prediction_at_utc.min()
    assert c.label_available_at_utc.max() < boundary


def test_split_excludes_label_at_boundary_and_refuses_shorter_calibration():
    x = panel(pd.bdate_range('2021-01-04', periods=180).strftime('%Y-%m-%d').tolist())
    boundary = x.label_available_at_utc.max()
    with pytest.raises(s.cm.FitFailure, match='INSUFFICIENT'):
        s.split_prefix(x, boundary)
    with pytest.raises(ValueError, match='timezone'):
        s.split_prefix(x, pd.Timestamp('2022-01-01'))


def test_split_fails_when_train_maturity_overlaps_calibration():
    x = panel(pd.bdate_range('2021-01-04', periods=181).strftime('%Y-%m-%d').tolist())
    x.loc[x.date.eq(x.date.min()), 'label_available_at_utc'] = x.label_available_at_utc.max()
    with pytest.raises(ValueError, match='T labels overlap C'):
        s.split_prefix(x, x.label_available_at_utc.max()+pd.Timedelta(days=1))


def test_validate_allows_missing_labels_but_rejects_2026_or_clock_shift():
    x = panel(['2025-12-31'])
    x.loc[0, ['y', 'return_remaining']] = np.nan
    accepted = s.validate_panel(x.copy(), config())
    assert len(accepted) == 4 and accepted.y.isna().sum() == 1
    with pytest.raises(ValueError, match='pre-2026'):
        s.validate_panel(panel(['2026-01-02']), config())
    x.loc[0, 'label_start_utc'] -= pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match='clock mismatch'):
        s.validate_panel(x, config())


def test_validate_rejects_label_direction_and_duplicate_predictions():
    x = panel(['2025-12-31'])
    x.loc[0, 'y'] = 1
    with pytest.raises(ValueError, match='label definition'):
        s.validate_panel(x, config())
    x = panel(['2025-12-31'])
    with pytest.raises(ValueError, match='unique'):
        s.validate_panel(pd.concat([x, x.iloc[:1]], ignore_index=True), config())


@pytest.mark.parametrize('evaluation_days', [59, 260])
def test_real_freeze_E_keeps_unlabelled_predictions_and_marks_short_year(tmp_path, monkeypatch, evaluation_days):
    # Freeze runs actual panel validation, split construction and fold manifest
    # writing. Factories are disabled: no synthetic or historical estimator fit.
    dates = (pd.bdate_range('2021-01-04', '2021-12-31').strftime('%Y-%m-%d').tolist()
             + pd.bdate_range('2022-01-03', periods=evaluation_days).strftime('%Y-%m-%d').tolist())
    x = panel(dates)
    idx = x.index[x.date.eq('2022-01-03')][0]
    missing_id = x.loc[idx, 'sample_id']
    x.loc[idx, ['y', 'return_remaining']] = np.nan
    dataset, output = tmp_path/'data', tmp_path/'eval'
    dataset.mkdir()
    x.to_parquet(dataset/'panel.parquet', index=False)
    cfg = config() | {'panel_sha256': s.sha(dataset/'panel.parquet'), 'sample_manifest_sha256': 'synthetic'}
    (dataset/'data_config.json').write_text(json.dumps(cfg), encoding='utf-8')
    monkeypatch.setattr(s, 'specs_from', lambda _: [])
    monkeypatch.setattr(s, 'source_identity', lambda: {'synthetic': 'no fit'})
    monkeypatch.setattr(s.cm, 'dependency_record', lambda: {'scope': 'synthetic no fit'})
    protocol = s.freeze(dataset, output)
    ids = pd.read_parquet(output/'fold_sample_ids.parquet')
    e = ids[(ids.year == '2022') & (ids.segment == 'E')]
    assert missing_id in set(e.sample_id)
    assert len(e) == int(x.date.str.startswith('2022').sum())
    assert not (output/'fit_events.jsonl').exists()
    fold = next(v for v in protocol['folds'] if v['year'] == 2022)
    assert fold['E_evaluable_dates'] == evaluation_days
    if evaluation_days < 60:
        assert fold['status'] == 'SKIPPED_INSUFFICIENT_HISTORY'
        assert fold['reason'] == 'E_HAS_FEWER_THAN_60_EVALUABLE_DATES'
    else:
        assert fold['status'] == 'EXECUTABLE'


def test_choose_prior_and_constant_can_win_and_ties_favor_B0():
    history = {(2022, 'B0'): daily(value=.69), (2022, 'B1'): daily(value=.68),
               (2022, 'H1_B'): daily(value=.71)}
    assert s.choose(history, [2022], 'B')[0] == 'B1'
    history[(2022, 'B0')] = daily(value=.68+5e-13)
    assert s.choose(history, [2022], 'B')[0] == 'B0'
    assert s.choose(history, [], 'B') == (None, [])


def test_candidate_with_missing_bad_or_short_inner_fold_is_ineligible():
    history = {(2022, 'B0'): daily(), (2023, 'B0'): daily(2023),
               (2022, 'H1_B'): daily(value=.1),
               (2022, 'E1_B'): daily(value=.1), (2023, 'E1_B'): daily(2023, value=.1, n=59),
               (2022, 'S1_B'): daily(value=.1), (2023, 'S1_B'): daily(2023, value=np.nan)}
    selected, scores = s.choose(history, [2022, 2023], 'B')
    assert selected == 'B0'
    assert not any(v['eligible'] for v in scores if v['id'] in ['H1_B', 'E1_B', 'S1_B'])


def test_k_star_uses_only_A_learners_even_if_B_or_prior_looks_better():
    history = {(2022, 'B0'): daily(value=.1), (2022, 'B1'): daily(value=.11),
               (2022, 'H1_A'): daily(value=.70), (2022, 'E1_A'): daily(value=.69),
               (2022, 'H1_B'): daily(value=.01), (2022, 'E1_B'): daily(value=.9)}
    selected, scores = s.choose(history, [2022], 'A', learners_only=True)
    assert selected == 'E1_A'
    assert all(v['id'].endswith('_A') for v in scores)


def test_budget_records_two_transient_retries_and_counts_every_call(tmp_path):
    budget = s.Budget(tmp_path/'ledger.jsonl', hard_cap=160)
    attempts = []
    def transient():
        attempts.append(1)
        if len(attempts) < 3:
            raise TimeoutError('synthetic transient')
        return SimpleNamespace(metadata={'scope': 'no estimator fit'})
    invoke(budget, transient)
    assert budget.calls == 3 and budget.retries == 2
    assert [v['status'] for v in budget.events] == ['STARTED', 'FAILED', 'STARTED', 'FAILED', 'STARTED', 'FINISHED']
    assert [v['attempt'] for v in budget.events if v['status'] == 'STARTED'] == [0, 1, 2]


def test_budget_refuses_161st_fit_and_retries_only_transient_errors(tmp_path):
    budget = s.Budget(tmp_path/'cap.jsonl')
    budget.calls = 160
    with pytest.raises(RuntimeError, match='BUDGET_EXHAUSTED'):
        invoke(budget, lambda: pytest.fail('must not execute'))
    assert budget.calls == 160 and not budget.events
    budget = s.Budget(tmp_path/'ordinary.jsonl')
    def failure():
        raise s.cm.FitFailure('synthetic single class')
    with pytest.raises(s.cm.FitFailure):
        invoke(budget, failure)
    assert budget.calls == 1 and budget.retries == 0


def test_retry_reserve_and_existing_ledger_cannot_be_silently_restarted(tmp_path):
    path = tmp_path/'ledger.jsonl'
    budget = s.Budget(path, retry_cap=0)
    with pytest.raises(TimeoutError):
        invoke(budget, lambda: (_ for _ in ()).throw(TimeoutError('synthetic')))
    assert budget.calls == 1 and budget.retries == 0
    with pytest.raises(ValueError, match='Existing fit ledger'):
        s.Budget(path)


def test_fallback_preserves_all_B1_ids_and_marks_failure():
    rows = panel(['2025-12-31'])[['sample_id', 'date']].assign(p_up=.51, model_id='B1')
    invalid = rows.copy().assign(p_up=np.nan, model_id='H1_B')
    result = s.fallback_rows('H1_B', {'B1': rows, 'H1_B': invalid}, role='S_B')
    assert result.sample_id.tolist() == rows.sample_id.tolist()
    assert result.model_id.eq('B1').all()
    assert result.selected_model_id.eq('H1_B').all()
    assert result.fallback_reason.notna().all()
    assert result.role.eq('S_B').all()


@pytest.mark.parametrize('corruption', ['missing', 'wrong_id', 'duplicate'])
def test_finite_but_incomplete_or_wrong_candidate_ids_must_fall_back(corruption):
    rows = panel(['2025-12-31'])[['sample_id', 'date']].assign(p_up=.51, model_id='B1')
    candidate = rows.copy().assign(model_id='H1_B')
    if corruption == 'missing':
        candidate = candidate.iloc[:-1]
    elif corruption == 'wrong_id':
        candidate.loc[0, 'sample_id'] = 'UNKNOWN|2025-12-31'
    else:
        candidate.loc[0, 'sample_id'] = candidate.loc[1, 'sample_id']
    result = s.fallback_rows('H1_B', {'B1': rows, 'H1_B': candidate}, role='S_B')
    assert result.sample_id.tolist() == rows.sample_id.tolist()
    assert result.model_id.eq('B1').all()
    assert result.fallback_reason.notna().all()


def test_fit_cache_identity_binds_T_C_code_input_dependency_and_spec(tmp_path):
    (tmp_path/'models').mkdir()
    (tmp_path/'frozen_protocol.json').write_text('{}')
    x = panel(pd.bdate_range('2021-01-04', periods=180).strftime('%Y-%m-%d').tolist())
    t, c = x.iloc[:480].copy(), x.iloc[480:].copy()
    spec = s.cm.make_spec('H1', 'A', ['f0'])
    protocol = {'panel_sha256': 'input1', 'code_sha256': {'entry.py': 'code1'},
                'dependencies': {'scikit-learn': 'synthetic-version-1'}}
    keys = []
    class FakeBudget:
        def invoke(self, fn, **kw):
            # The fit closure is intentionally never executed.
            keys.append(kw['cache_key'])
            return SimpleNamespace(metadata={'max_label_available_at': '2021-01-05T17:31:00Z'})
    def call(a, b, p, sp):
        return s.fit_one(sp, a, b, year=2022, protocol=p, output=tmp_path,
                         budget=FakeBudget(), category='candidate')['cache_key']
    original = call(t, c, protocol, spec)
    assert call(t, c, protocol, spec) == original
    changed_t, changed_c = t.copy(), c.copy()
    changed_t.loc[0, 'sample_id'] += 'different'
    changed_c.loc[changed_c.index[0], 'sample_id'] += 'different'
    changes = [call(changed_t, c, protocol, spec), call(t, changed_c, protocol, spec),
        call(t, c, protocol | {'panel_sha256': 'input2'}, spec),
        call(t, c, protocol | {'code_sha256': {'entry.py': 'code2'}}, spec),
        call(t, c, protocol | {'dependencies': {'scikit-learn': 'synthetic-version-2'}}, spec),
        call(t, c, protocol, s.cm.make_spec('H1', 'B', ['f0']))]
    assert original not in changes and len(set(changes)) == len(changes)
    assert all(keys[i] == keys[i+1] for i in range(0, len(keys), 2))


def test_metrics_equal_dates_not_stock_rows_and_pairs_reject_duplicates():
    x = panel(['2023-01-03', '2023-01-04'])
    x = pd.concat([x.iloc[:4], x.iloc[4:5]], ignore_index=True)
    x['y'], x['return_remaining'] = 1., .01
    p = np.array([.9]*4+[.1])
    total, d = s.metric(x, p)
    assert total['log_loss'] == pytest.approx((-np.log(.9)-np.log(.1))/2)
    assert len(d) == 2
    duplicate = pd.concat([daily(), daily().iloc[:1]], ignore_index=True)
    with pytest.raises(pd.errors.MergeError):
        s.paired(duplicate, daily())


def test_paired_bootstrap_fixed_daily_difference_and_missing_dates_marked():
    a = pd.concat([daily(y, value=.60, n=100) for y in [2023, 2024, 2025]], ignore_index=True)
    b = a.assign(log_loss=.61)
    score, values = s.paired(a, b, expected_dates=300)
    assert score['dates'] == 300 and score['minimum_met']
    assert score['delta_log_loss'] == pytest.approx(-.01)
    assert score['ci95_high'] == pytest.approx(-.01)
    assert values.delta_log_loss.eq(values.delta_log_loss.iloc[0]).all()
    incomplete, _ = s.paired(a.iloc[1:], b, expected_dates=300)
    assert incomplete['status'] == 'INCOMPLETE_COMPARISON' and not incomplete['minimum_met']


def test_predict_final_saved_constant_replays_feature_only_and_keeps_missing_label_rows(tmp_path):
    x = panel(['2025-12-31']).drop(columns=['y', 'return_remaining', 'label_reason'])
    bundle = {'task_id': s.TASK_ID, 'kind': 'constant', 'p_up': .5, 'model_id': 'B0', 'columns': [],
              'base_fit_cutoff': None, 'calibration_cutoff': None, 'fallback_reason': None}
    before = s.predict_final(bundle, x)
    path = tmp_path/'predictor.joblib'
    joblib.dump(bundle, path)
    after = s.predict_final(joblib.load(path), x)
    pd.testing.assert_frame_equal(before, after, check_exact=True)
    assert len(after) == 4 and after.predicted_up.eq(1).all()
    assert np.allclose(after.p_up+after.p_not_up, 1.)
    assert 'p_down' not in after
    assert after.prediction_timestamp.equals(x.prediction_at_utc)
    assert after.label_start.equals(x.label_start_utc)
    assert after.label_end.equals(x.label_end_utc)
    bad = x.copy()
    bad.feature_cutoff_utc += pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match='Inference clock'):
        s.predict_final(bundle, bad)
