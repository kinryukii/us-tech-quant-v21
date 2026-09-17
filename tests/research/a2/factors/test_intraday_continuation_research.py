"""Synthetic runner integration; real readers are replaced before any phase.

Actual source-only engine rank/ledger and pure R4 fee APIs are reused. Statistical
draws are replaced with deterministic synthetic stubs to test orchestration.
"""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, 'D:/us-tech-quant')
from scripts.research.a2.factors import intraday_continuation_research as runner
from scripts.research.a2.factors import intraday_continuation as pure
from scripts.research.a2.factors import economic_return_preflight as keys
from scripts.research.a2.factors import systematic_tail_research as helpers


@pytest.fixture
def synthetic_runner(tmp_path, monkeypatch):
    result, cache = tmp_path / 'A2_INTRADAY_CONTINUATION_20260913', tmp_path / 'cache'
    result.mkdir(); cache.mkdir()
    monkeypatch.setattr(runner, 'RESULT', result)
    monkeypatch.setattr(runner, 'CACHE', cache)
    dates = pd.bdate_range('2023-01-03', periods=732)
    panel = pd.DataFrame([(date, f'A{n:02}') for date in dates for n in range(40)],
                         columns=['signal_date', 'ticker'])
    cohort = {'rows': len(panel), 'dates': len(dates), 'names_per_date': 40,
              'first_date': str(dates.min().date()), 'last_date': str(dates.max().date()),
              'key_sha256': keys.key_fingerprint(panel)}
    prereg = {'cohort': cohort, 'evidence_role': 'SYNTHETIC_TEST_ONLY'}
    freeze = {'full_cohort': cohort, 'files': {}, 'frozen_utc': '2020-01-01T00:00:00+00:00'}
    (result / 'experiment_freeze.json').write_text(json.dumps(freeze))
    (result / 'data_contract.json').write_text('{}')
    prior = tmp_path / 'A2_SYSTEMATIC_TAIL_DEPENDENCE_20260913'
    prior.mkdir()
    pd.DataFrame([{'block': block, 'p_one_sided': value} for block in (20, 40, 60)
                  for value in (.2, .3, .4)]).to_csv(prior / 'paired_comparisons.csv', index=False)
    engine = runner.load_module('synthetic_intraday_actual_engine',
                                Path('D:/us-tech-quant/scripts/v22/a2_open_research_engine.py'))
    rank_calls, value_calls, bootstrap_calls = [], [], []
    original_rank = engine.stable_rank
    def ranked(frame):
        rank_calls.append(list(frame.columns))
        assert list(frame.columns) == ['signal_date', 'ticker', 'prediction']
        return original_rank(frame)
    engine.stable_rank = ranked
    state = {'missing_target': False, 'raise_on_values': False, 'constant_delta': False,
             'reverse_targets': False}
    def feature(raw, calendar, supplied, *, compute_values=False):
        value_calls.append(bool(compute_values))
        if compute_values and state['raise_on_values']:
            raise RuntimeError('SYNTHETIC_VALUE_PHASE_FAILURE')
        out = supplied[['signal_date', 'ticker']].copy()
        out['feature_available'] = True
        out['target_available'] = True
        if state['missing_target']:
            out.loc[out.index[0], 'target_available'] = False
        out['values_computed'] = bool(compute_values)
        out['next_market_session'] = out.signal_date + pd.offsets.BDay(1)
        out['intraday_continuation_score'] = np.nan
        out['next_session_gross_return'] = np.nan
        if compute_values:
            out['intraday_continuation_score'] = 0.  # all ties: ticker must decide
            if state['constant_delta']:
                out['next_session_gross_return'] = .001
            else:
                name_number = out.ticker.str[1:].astype(int).to_numpy()
                date_number = np.repeat(np.arange(len(dates)), 40)
                out['next_session_gross_return'] = (.001 + .0001 * np.sin(date_number / 4)
                    * (name_number - 19.5))
                if state['reverse_targets']:
                    out['next_session_gross_return'] *= -1
        return out
    def pvalue(values, **kwargs):
        bootstrap_calls.append(kwargs)
        assert len(values) == 732 and np.isfinite(values).all()
        return .6
    r5 = SimpleNamespace(block_bootstrap_pvalue=pvalue,
                         block_bootstrap_mean_interval=lambda *a, **k: (-.01, .01))
    modules = {'keys': keys,
        'factor': SimpleNamespace(build_intraday_continuation=feature, VALUE_COLUMNS=pure.VALUE_COLUMNS,
                                   one_session_group_return=pure.one_session_group_return),
        'helpers': SimpleNamespace(import_path=lambda *a, **k: engine, holm=helpers.holm),
        'reader': SimpleNamespace(load_tail_definitions=lambda: SimpleNamespace(load_sources=lambda: (r5, None, None)))}
    monkeypatch.setattr(runner, 'setup', lambda: (freeze, prereg, modules))
    monkeypatch.setattr(runner, 'read_stage', lambda *a: (None, panel.copy(), panel.copy(), dates,
                                                        {'source_and_input_hashes': {}}))
    monkeypatch.setattr(runner, 'recheck', lambda *a: None)
    return SimpleNamespace(result=result, cache=cache, state=state, rank_calls=rank_calls,
                            value_calls=value_calls, bootstrap_calls=bootstrap_calls)


def test_missing_future_target_stops_whole_scope_before_value_math_or_trial(synthetic_runner):
    case = synthetic_runner
    case.state['missing_target'] = True
    runner.coverage_stage()
    summary = json.loads((case.result / 'coverage_summary.json').read_text())
    assert summary['evaluation_missing_target_rows'] == 1
    assert not summary['evaluation_admitted']
    with pytest.raises(RuntimeError, match='COVERAGE_FAILED'):
        runner.evaluate_stage()
    assert case.value_calls == [False] and not case.rank_calls
    assert not (case.result / 'trial_ledger.parquet').exists()


def test_mask_tamper_is_rejected_before_any_value_or_rank(synthetic_runner):
    case = synthetic_runner
    runner.coverage_stage()
    mask_path = case.cache / 'coverage_masks.parquet'
    masks = pd.read_parquet(mask_path)
    masks.loc[0, 'target_available'] = False
    masks.to_parquet(mask_path, index=False)
    with pytest.raises(RuntimeError, match='COVERAGE_MASK_CHANGED'):
        runner.evaluate_stage()
    assert case.value_calls == [False] and not case.rank_calls


def test_changed_freeze_between_phases_rejects_old_coverage_permission(synthetic_runner):
    case = synthetic_runner
    runner.coverage_stage()
    path = case.result / 'experiment_freeze.json'
    path.write_text(path.read_text() + ' ')
    with pytest.raises(RuntimeError, match='FREEZE'):
        runner.evaluate_stage()
    assert case.value_calls == [False] and not case.rank_calls
    assert not (case.result / 'trial_ledger.parquet').exists()


def test_full_pairing_rank_is_target_blind_and_counts_one_comparison(synthetic_runner):
    case = synthetic_runner
    case.state['reverse_targets'] = True
    runner.coverage_stage()
    runner.evaluate_stage()
    measured = pd.read_parquet(case.cache / 'measured_panel.parquet')
    daily = pd.read_parquet(case.cache / 'daily_group_cost_scenarios.parquet')
    assert len(measured) == 29280 and len(daily) == 732 * 2 * 2
    assert set(measured.loc[measured.group.eq('TOP20'), 'ticker']) == {f'A{n:02}' for n in range(20)}
    assert measured.groupby(['signal_date', 'group']).size().eq(20).all()
    assert case.value_calls == [False, True] and len(case.rank_calls) == 1
    assert [call['block'] for call in case.bootstrap_calls] == [20, 40, 60]
    assert all(call['seed'] == 20260913 and call['repetitions'] == 5000 for call in case.bootstrap_calls)
    summary = json.loads((case.result / 'summary.json').read_text())
    assert summary['new_predictive_fits'] == 0 and summary['new_candidate_comparisons'] == 1
    assert summary['campaign_candidate_comparisons'] == 4 and not summary['automatic_advancement']
    ledger = pd.read_parquet(case.result / 'trial_ledger.parquet')
    assert ledger.status.tolist() == ['STARTED', 'COMPLETED']
    with pytest.raises(RuntimeError, match='EVALUATION_ALREADY_STARTED'):
        runner.evaluate_stage()


def test_constant_effect_has_explicit_null_autocorrelation_and_valid_json(synthetic_runner):
    case = synthetic_runner
    case.state['constant_delta'] = True
    runner.coverage_stage()
    runner.evaluate_stage()
    summary = json.loads((case.result / 'summary.json').read_text())
    assert all(value is None for value in summary['delta_autocorrelation'].values())
    assert not summary['automatic_advancement']


def test_value_phase_failure_remains_recorded_and_cannot_silently_retry(synthetic_runner):
    case = synthetic_runner
    runner.coverage_stage()
    case.state['raise_on_values'] = True
    with pytest.raises(RuntimeError, match='SYNTHETIC_VALUE_PHASE_FAILURE'):
        runner.evaluate_stage()
    ledger = pd.read_parquet(case.result / 'trial_ledger.parquet')
    assert 'STARTED' in set(ledger.status)
    assert 'FAILED' in set(ledger.status)
    assert ledger.loc[ledger.status.eq('FAILED'), 'failure_reason'].str.contains('SYNTHETIC_VALUE_PHASE_FAILURE').all()
    with pytest.raises(RuntimeError, match='EVALUATION_ALREADY_STARTED'):
        runner.evaluate_stage()


def test_missing_freeze_dependency_fails_before_module_import(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'RESULT', tmp_path)
    freeze = {'files': {str(Path(runner.__file__).resolve()): runner.sha(runner.__file__)}}
    (tmp_path / 'experiment_freeze.json').write_text(json.dumps(freeze))
    monkeypatch.setattr(runner, 'load_module', lambda *a, **k: pytest.fail('import before dependency freeze'))
    with pytest.raises(RuntimeError, match='REQUIRED_FREEZE_DEPENDENCY_MISSING'):
        runner.setup()


def test_post_commit_reporting_failure_preserves_completed_count(synthetic_runner, monkeypatch):
    case = synthetic_runner
    runner.coverage_stage()
    def committed_then_failed(freeze, prereg, modules, raw, panel, calendar, lineage, engine, r5, ledger, start):
        runner.append_trial(engine, ledger, suffix='COMPLETE', status='COMPLETED', count=len(panel),
            runtime=0, input_hash='synthetic', code_hash='synthetic', metrics={})
        raise OSError('SYNTHETIC_REPORT_WRITE_FAILURE')
    monkeypatch.setattr(runner, 'evaluate_started', committed_then_failed)
    with pytest.raises(OSError, match='SYNTHETIC_REPORT_WRITE_FAILURE'):
        runner.evaluate_stage()
    ledger = pd.read_parquet(case.result / 'trial_ledger.parquet')
    assert ledger.status.tolist() == ['STARTED', 'COMPLETED', 'REPORTING_FAILED']
    failure = json.loads((case.result / 'evaluation_failure.json').read_text())
    assert failure['candidate_comparisons_started'] == failure['candidate_comparisons_completed'] == 1
