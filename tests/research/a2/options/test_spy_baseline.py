"""Synthetic entry-boundary regressions for the single fixed exploratory model."""
import importlib.util
import json
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.options.contracts import Invalid, TEMPLATE
from scripts.research.a2.options.spy_observed_frontier import make_plan

# The same tests can validate the staged file before its reviewed installation.
SOURCE = Path(__file__).parents[4] / 'scripts/research/a2/options/spy_baseline.py'
spec = importlib.util.spec_from_file_location('scripts.research.a2.options.spy_baseline', SOURCE)
b = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = b
spec.loader.exec_module(b)


@pytest.fixture
def data(tmp_path, monkeypatch):
    plan, _ = make_plan()
    monkeypatch.setattr(b, 'resolve', lambda: SimpleNamespace(results_root=tmp_path))
    output = tmp_path / TEMPLATE / 'spy2024_complete_compat_train' / 'synthetic'
    output.mkdir(parents=True)
    manifest = output / 'run_manifest.json'
    evidence = output / 'synthetic_continuity.txt'
    evidence.write_text('SYNTHETIC CONTINUOUS UNITS', encoding='utf-8')
    meta = dict(task_id='OPTIONS_SPY2024_COMPLETE_COMPAT_TRAIN_R1', plan=plan, domain={'tolerance_usd': 0.01}, model_spec=b.SPEC,
                model_candidate_count_added=1, model_spec_frozen_at='SYNTHETIC_PRE_RESULT_FREEZE',
                model_feature_continuity={'status': 'CONTINUOUS_TRADE_BASIS_2024',
                                          'evidence_ref': {'path': str(evidence), 'sha256': b._hash(evidence)}})
    manifest.write_text(json.dumps(meta), encoding='utf-8')
    changes = np.random.default_rng(103).normal(0.0002, 0.008, len(plan))
    prices = pd.DataFrame(dict(date=[r['reference_date'] for r in plan], close=100*np.exp(np.cumsum(changes)),
                               ticker='SPY', currency='USD', adjustment='raw'))
    observed = pd.DataFrame(plan)
    observed['cash_status'], observed['cash_reason'] = 'CLOSED', 'SYNTHETIC'
    observed['conditional_wealth_difference'] = np.where(np.arange(len(plan)) % 2, -2.0, 3.0)
    observed['selected_contract_id'] = 'SAME_CONTRACT_ACROSS_DATES'
    observed_file = output / 'observed_frontier.csv'
    observed.to_csv(observed_file, index=False)
    return SimpleNamespace(prices=prices, observed=observed, observed_file=observed_file,
                           output=output, manifest=manifest, meta=meta)


def run(data):
    return b.run_baseline(data.prices, data.observed_file, data.output, data.manifest)


def test_plan_features_maturity_training_scaler_and_resume(data, monkeypatch):
    # An unresolved future label remains an issued prediction, never a negative label.
    missing = data.observed.entry_date.str.startswith('2024-07')
    data.observed.loc[missing, 'cash_status'] = 'UNRESOLVED'
    data.observed.loc[missing, 'conditional_wealth_difference'] = np.nan
    data.observed.to_csv(data.observed_file, index=False)
    result = run(data)
    assert result['successful_fits'] == result['model_fit_attempts'] == 6
    panel = pd.read_csv(data.output / 'feature_labels.csv')
    oof = pd.read_csv(data.output / 'oof.csv')
    assert len(oof) == 246
    assert panel.feature_status.eq('WARMUP').sum() == 20
    assert oof.loc[missing, 'label'].isna().all()
    assert oof.loc[missing, 'probability'].notna().all()
    first = 20
    close = data.prices.close
    assert panel.loc[first, 'r20'] == pytest.approx(np.log(close.iloc[first]/close.iloc[0]))
    assert panel.loc[first, 'v20'] == pytest.approx(np.log(close).diff().iloc[1:21].std(ddof=1))
    for month, fold in result['folds'].items():
        legal = panel.loc[(panel.exit_date < fold['first_entry']) & panel.label.notna() & panel.feature_status.eq('READY')]
        assert fold['training_label_max'] < fold['first_entry']
        assert fold['scaler_mean'] == pytest.approx(legal[b.FEATURES].mean().to_numpy())
        assert fold['training_positive_rate'] == pytest.approx(legal.label.mean())
    monkeypatch.setattr(b, 'fit_fold', lambda *_: pytest.fail('resume repeated a model fit'))
    assert run(data) == result


def test_future_labels_and_prices_cannot_change_earlier_fold(data):
    result = run(data)
    original = pd.read_csv(data.output / 'oof.csv')
    data.observed.loc[data.observed.exit_date.ge('2024-08-01'), 'conditional_wealth_difference'] *= -1
    data.observed.to_csv(data.observed_file, index=False)
    with pytest.raises(Invalid, match='RESUME_INPUT_CHANGED'):
        run(data)
    # A separate synthetic comparison preserves the same preregistered specification.
    data.output = data.output.parent / 'synthetic_future_mutated'
    data.output.mkdir()
    data.manifest = data.output / 'run_manifest.json'
    data.manifest.write_text(json.dumps(data.meta), encoding='utf-8')
    data.prices.loc[data.prices.date.ge('2024-08-01'), 'close'] *= 2
    mutated = run(data)
    later = pd.read_csv(data.output / 'oof.csv')
    july = original.entry_date.str.startswith('2024-07')
    assert mutated['folds']['2024-07']['coefficients'] == result['folds']['2024-07']['coefficients']
    assert mutated['folds']['2024-07']['scaler_mean'] == result['folds']['2024-07']['scaler_mean']
    pd.testing.assert_series_equal(original.loc[july, 'probability'], later.loc[july, 'probability'])


@pytest.mark.parametrize('column', b.DATES)
def test_real_fit_entry_rejects_2026_and_unmatured_labels(data, column):
    panel = b.project(data.prices, data.observed_file, data.meta)
    train = panel.loc[panel.feature_status.eq('READY')].head(8).copy()
    train.loc[train.index[0], column] = '2026-01-01'
    with pytest.raises(Invalid, match='OUTSIDE_2024'):
        b.fit_fold(train, '2024-07-01')
    train = panel.loc[panel.feature_status.eq('READY')].head(8).copy()
    train.loc[train.index[0], 'exit_date'] = '2024-07-01'
    with pytest.raises(Invalid, match='FIT_SCOPE_OR_MATURITY'):
        b.fit_fold(train, '2024-07-01')


def test_date_projection_rejects_future_before_economic_read(data, monkeypatch):
    data.observed.loc[0, 'exit_date'] = '2026-01-01'
    data.observed.to_csv(data.observed_file, index=False)
    calls, original = [], b.pd.read_csv
    def capture(*args, **kwargs):
        calls.append(kwargs.get('usecols'))
        return original(*args, **kwargs)
    monkeypatch.setattr(b.pd, 'read_csv', capture)
    with pytest.raises(Invalid, match='OBSERVATION_PLAN_CHANGED'):
        run(data)
    assert calls == [['decision_id'] + b.DATES]


def test_only_one_class_does_not_fit_and_uncertain_fit_never_retries(data, monkeypatch):
    data.observed['conditional_wealth_difference'] = 3.0
    data.observed.to_csv(data.observed_file, index=False)
    monkeypatch.setattr(b, 'fit_fold', lambda *_: pytest.fail('single class model fit'))
    result = run(data)
    assert result['status'] == 'NOT_RUN_NO_EXECUTABLE_FOLD'
    assert result['model_fit_attempts'] == result['successful_fits'] == 0
    assert all(f['status'] == 'NOT_FITTED_SINGLE_CLASS_OR_EMPTY' for f in result['folds'].values())


def test_network_block_and_failed_started_checkpoint_prevent_refit(data, monkeypatch):
    real_fit = b.fit_fold
    def attempted_network(*_):
        socket.getaddrinfo('example.invalid', 443)
    monkeypatch.setattr(b, 'fit_fold', attempted_network)
    with pytest.raises(RuntimeError, match='BASELINE_NETWORK_FORBIDDEN'):
        run(data)
    meta = json.loads(data.manifest.read_text())
    assert meta['model_baseline']['model_fit_attempts'] == 1
    assert meta['model_baseline']['folds']['2024-07']['status'] == 'FIT_STARTED'
    first_entries = []
    def capture_fit(train, first_entry):
        first_entries.append(first_entry)
        return real_fit(train, first_entry)
    monkeypatch.setattr(b, 'fit_fold', capture_fit)
    result = run(data)
    assert result['status'] == 'PARTIAL_UNCERTAIN_FIT'
    assert result['successful_fits'] == 5
    assert len(first_entries) == 5 and all(e >= '2024-08-01' for e in first_entries)
    assert result['model_fit_attempts'] == 6


def test_single_class_earlier_fold_does_not_block_later_months(data):
    data.observed.loc[data.observed.entry_date.lt('2024-07-01'), 'conditional_wealth_difference'] = 3.0
    data.observed.to_csv(data.observed_file, index=False)
    result = run(data)
    assert result['folds']['2024-07']['status'] == 'NOT_FITTED_SINGLE_CLASS_OR_EMPTY'
    assert result['successful_fits'] == 5


def test_continuity_evidence_is_bound_and_missing_reference_cli_never_fits(data, monkeypatch, capsys):
    monkeypatch.setattr(b, 'run_baseline', lambda *_: pytest.fail('incomplete references reached training'))
    assert b.main(['--output', str(data.output), '--offline']) == 2
    assert json.loads(capsys.readouterr().out) == dict(status='INCOMPLETE_REFERENCE_INPUT', model_fit=0, network_requests=0)
    proof = Path(data.meta['model_feature_continuity']['evidence_ref']['path'])
    proof.write_text('CHANGED', encoding='utf-8')
    with pytest.raises(Invalid, match='CONTINUITY_EVIDENCE_CHANGED'):
        b.project(data.prices, data.observed_file, data.meta)


def test_cli_completed_diagnostic_is_hash_checked_and_not_rerun(data, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, 'scripts.research.a2.options.price_basis',
                        SimpleNamespace(STATUS='SYNTHETIC_QUALIFIED', read_trade_references=lambda *_: pytest.fail('reread completed stage')))
    binding = data.output / 'reference_binding.json'
    binding.write_text(json.dumps({'reference_additions': {'qualification': {'status': 'SYNTHETIC_QUALIFIED'}}}))
    observed = data.output / 'observed'
    observed.mkdir()
    data.observed.to_csv(observed / 'observed_frontier.csv', index=False)
    records = [dict(reference_date=r.date, reference_close=r.close) for r in data.prices.itertuples()]
    encoded = json.dumps(records, sort_keys=True, separators=(',', ':'), allow_nan=False)
    meta = dict(status='COMPLETE_CONDITIONAL_ARCHIVE_DIAGNOSTIC',
                reference_override={'sha256': b._hash(binding)},
                result_sha256=b._hash(observed / 'observed_frontier.csv'),
                entry_lock={'records': records, 'sha256': b.hashlib.sha256(encoded.encode()).hexdigest()})
    (observed / 'run_manifest.json').write_text(json.dumps(meta))
    calls = []
    def train(references, observed_csv, output, manifest):
        calls.append(references)
        assert len(references) == 246 and references.currency.eq('USD').all()
        return {'status': 'COMPLETE'}
    monkeypatch.setattr(b, 'run_baseline', train)
    assert b.main(['--output', str(data.output), '--offline']) == 0
    assert len(calls) == 1
    (observed / 'observed_frontier.csv').write_text('CHANGED')
    with pytest.raises(Invalid, match='OBSERVED_CHECKPOINT_CHANGED'):
        b.main(['--output', str(data.output), '--offline'])


def test_partial_references_still_reach_full_plan_diagnostic_but_not_fit(data, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, 'scripts.research.a2.options.price_basis',
                        SimpleNamespace(STATUS='SYNTHETIC_QUALIFIED', read_trade_references=lambda *_: data.prices.head(1)))
    binding = data.output / 'reference_binding.json'
    binding.write_text(json.dumps({'reference_additions': {'qualification': {'status': 'SYNTHETIC_QUALIFIED'},
                                                          'allowed_reference_dates': [data.prices.iloc[0].date]}}))
    cli_calls = []
    def observed_cli(command):
        cli_calls.append(command)
        observed = data.output / 'observed'
        observed.mkdir()
        data.observed.to_csv(observed / 'observed_frontier.csv', index=False)
        records = [dict(reference_date=r.date, reference_close=r.close if i < 71 else None)
                   for i, r in enumerate(data.prices.itertuples())]
        encoded = json.dumps(records, sort_keys=True, separators=(',', ':'), allow_nan=False)
        meta = dict(status='COMPLETE_CONDITIONAL_ARCHIVE_DIAGNOSTIC', reference_override={'sha256': b._hash(binding)},
                    result_sha256=b._hash(observed / 'observed_frontier.csv'),
                    entry_lock={'records': records, 'sha256': b.hashlib.sha256(encoded.encode()).hexdigest()})
        (observed / 'run_manifest.json').write_text(json.dumps(meta))
        return 0
    monkeypatch.setitem(sys.modules, 'scripts.research.a2.options.cli', SimpleNamespace(main=observed_cli))
    monkeypatch.setattr(b, 'run_baseline', lambda *_: pytest.fail('partial references reached fit'))
    assert b.main(['--output', str(data.output), '--offline']) == 2
    assert len(cli_calls) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['complete_references'] == 71 and result['diagnostic'] == 'COMPLETE'
    assert result['model_status'] == 'NOT_RUN_PRICE_INCOMPLETE' and result['model_fit'] == 0
