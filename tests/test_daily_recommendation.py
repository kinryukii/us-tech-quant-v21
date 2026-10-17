"""Behavior checks for the user-command coordinator; no provider calls."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import pytest

SOURCE = Path(__file__).parents[1] / 'scripts/daily_recommendation.py'
spec = importlib.util.spec_from_file_location('today_coordinator', SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_selected_policy_return_slots_use_only_signal_close_and_keep_calendar_gaps(tmp_path):
    import numpy as np
    import pandas as pd
    from scripts.research.a2.portfolio.selected_hgb import BASE_FEATURES

    dates = pd.bdate_range('2026-09-01', periods=13)
    target = dates[-2].strftime('%Y-%m-%d')
    tickers = [f'T{index:02}' for index in range(40)]
    rows = [{'ticker': ticker, 'rank': index + 1, 'score': .01 * index}
            for index, ticker in enumerate(tickers)]
    features = pd.DataFrame([{'ticker': ticker, **{key: .1 for key in BASE_FEATURES}} for ticker in tickers])
    prices = pd.DataFrame([{'ticker': ticker, 'trade_date': day, 'close': 100 * 1.01 ** index}
                           for ticker in tickers for index, day in enumerate(dates)])
    # A later close must never revise today's target inputs.
    prices.loc[prices.trade_date.eq(dates[-1]), 'close'] = 1000000
    # A gap cannot turn the previous observed return into the missing slot.
    prices = prices.loc[~(prices.ticker.eq('T00') & prices.trade_date.eq(dates[-5]))]
    binding = module.save_selected_hgb_features(tmp_path, features, prices, rows, target, dates)
    frame = pd.read_parquet(binding['path']).set_index('ticker')
    np.testing.assert_allclose(frame.loc['T01', [f'lag_ret_{i:02d}' for i in range(10)]].to_numpy(float), .01)
    assert np.isnan(frame.at['T00', 'lag_ret_03'])
    assert np.isnan(frame.at['T00', 'lag_ret_02'])
    assert frame.trade_date.max() == dates[-2]
    assert binding['status'] == 'INCOMPLETE'


def test_selected_policy_failure_preserves_original_recommendation(tmp_path):
    from scripts.research.a2.portfolio import selected_hgb

    original = {'status': 'READY', 'data_date': '2026-09-24', 'rows': [{'ticker': 'A'}]}
    paths = SimpleNamespace(daily_root=tmp_path)
    with patch.object(selected_hgb, 'active_policy', return_value=('LEGACY_FROZEN_TEST', tmp_path / 'legacy_package.json')), \
         patch.object(selected_hgb, 'build_package', side_effect=ValueError('BAD_FEATURE_BINDING')):
        result = module.update_selected_strategies(paths, original, tmp_path, progress=lambda _: None)
    assert result == {'status': 'BLOCKED', 'error': 'BAD_FEATURE_BINDING'}
    assert original['status'] == 'READY' and original['rows'] == [{'ticker': 'A'}]
    assert json.loads((tmp_path / 'recommendation_source.json').read_text(encoding='utf-8'))['data_date'] == '2026-09-24'


def test_selected_policy_producer_reports_the_same_package_path_it_publishes(monkeypatch, tmp_path):
    from scripts.research.a2.portfolio import selected_hgb
    from scripts.research.a2.evaluation import selected_performance_update

    output = tmp_path / 'selected' / 'latest.json'
    monkeypatch.setenv('USTQ_SELECTED_HGB_PACKAGE', str(output))
    package = {'strategies': {sid: {'application': {'status': 'READY', 'signal_date': '2026-09-24'}}
                             for sid in selected_hgb.STRATEGY_IDS},
               'performance_period': {'end': '2026-09-24'},
               'performance_extension': {'status': 'READY', 'requested_end_date': '2026-09-24', 'blocked_next': None}}
    with patch.object(selected_hgb, 'active_policy', return_value=('LEGACY_FROZEN_TEST', output)), \
         patch.object(selected_hgb, 'build_package', return_value=package), \
         patch.object(selected_performance_update, 'refresh_selected_performance', return_value=package) as refresh:
        result = module.update_selected_strategies(SimpleNamespace(daily_root=tmp_path),
            {'status': 'READY', 'data_date': '2026-09-24'}, tmp_path, progress=lambda _: None)
    assert result['status'] == 'READY'
    assert Path(result['report_path']) == output.resolve()
    assert refresh.call_args.args[3] == output.resolve()


def _saved_prior_performance(tmp_path):
    root = tmp_path / 'A2_updated_research'
    immutable = root / 'runs/prior/manifest.json'
    module.save(immutable, {'status': 'PARTIAL', 'report_path': str(immutable)})
    pointer = root / 'latest.json'
    pointer.write_bytes(immutable.read_bytes())
    return pointer, immutable


def _mock_performance_manifest(tmp_path):
    return {'status': 'READY', 'run_id': 'new',
            'report_path': str(tmp_path / 'A2_updated_research/runs/new/manifest.json'),
            'ranking_manifest': {'path': str(tmp_path / 'A2_historical_top40/latest.json')}}


def test_performance_first_run_passes_no_prior_and_preserves_recommendation(tmp_path):
    from scripts.research.a2.evaluation import demo_performance, demo_rx_performance

    original = {'status': 'READY', 'data_date': '2026-09-29', 'rows': [{'ticker': 'A'}]}
    run_dir = tmp_path / 'today'
    with patch.object(demo_performance, 'refresh_demo_performance',
                      return_value=_mock_performance_manifest(tmp_path)) as refresh, \
         patch.object(demo_rx_performance, 'refresh_rx_performance', return_value={'status': 'BLOCKED'}):
        result = module.update_demo_performance(SimpleNamespace(daily_root=tmp_path), original, run_dir,
                                                progress=lambda _: None)
    assert result['status'] == 'READY'
    assert refresh.call_args.kwargs['prior_verified_performance_manifest_path'] is None
    assert refresh.call_args.kwargs['current_report_path'] == run_dir / 'recommendation_source.json'
    assert original == {'status': 'READY', 'data_date': '2026-09-29', 'rows': [{'ticker': 'A'}]}
    assert not (tmp_path / 'A2_updated_research/latest.json').exists()


def test_performance_official_pointer_routes_verified_immutable_prior(tmp_path):
    from scripts.research.a2.evaluation import demo_performance, demo_rx_performance

    pointer, immutable = _saved_prior_performance(tmp_path)
    before = pointer.read_bytes()
    with patch.object(demo_performance, 'refresh_demo_performance',
                      return_value=_mock_performance_manifest(tmp_path)) as refresh, \
         patch.object(demo_rx_performance, 'refresh_rx_performance', return_value={'status': 'BLOCKED'}):
        result = module.update_demo_performance(SimpleNamespace(daily_root=tmp_path),
            {'status': 'READY', 'data_date': '2026-09-29'}, tmp_path / 'today', progress=lambda _: None)
    assert result['status'] == 'READY'
    assert refresh.call_args.kwargs['prior_verified_performance_manifest_path'] == immutable.resolve()
    assert pointer.read_bytes() == before


def test_performance_bad_official_pointer_blocks_before_replay(tmp_path):
    from scripts.research.a2.evaluation import demo_performance

    pointer, immutable = _saved_prior_performance(tmp_path)
    module.save(pointer, {'status': 'READY', 'report_path': str(immutable)})
    before = pointer.read_bytes()
    with patch.object(demo_performance, 'refresh_demo_performance') as refresh:
        result = module.update_demo_performance(SimpleNamespace(daily_root=tmp_path),
            {'status': 'READY', 'data_date': '2026-09-29'}, tmp_path / 'today', progress=lambda _: None)
    assert result['status'] == 'BLOCKED'
    assert result['error'] == 'HISTORICAL_POINTER_CANONICAL_HASH_MISMATCH'
    refresh.assert_not_called()
    assert pointer.read_bytes() == before


@pytest.mark.parametrize('error', ['PRIOR_PERFORMANCE_IDENTITY_OR_CLOCK_MISMATCH',
                                 'PRIOR_PERFORMANCE_PREFIX_CHANGED:rankings'])
def test_performance_prior_conflict_does_not_retry_without_prior(tmp_path, error):
    from scripts.research.a2.evaluation import demo_performance

    pointer, immutable = _saved_prior_performance(tmp_path)
    before = pointer.read_bytes()
    with patch.object(demo_performance, 'refresh_demo_performance', side_effect=ValueError(error)) as refresh:
        result = module.update_demo_performance(SimpleNamespace(daily_root=tmp_path),
            {'status': 'READY', 'data_date': '2026-09-29'}, tmp_path / 'today', progress=lambda _: None)
    assert result['status'] == 'BLOCKED' and result['error'] == error
    refresh.assert_called_once()
    assert refresh.call_args.kwargs['prior_verified_performance_manifest_path'] == immutable.resolve()
    assert pointer.read_bytes() == before


def test_os_lock_blocks_overlap_and_releases_after_failure():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        try:
            with module.single_update(root):
                try:
                    with module.single_update(root):
                        raise AssertionError('a second updater entered')
                except RuntimeError:
                    pass
                raise ValueError('failure during acquisition')
        except ValueError:
            pass
        with module.single_update(root):
            assert (root / 'update.lock').exists()


def test_provider_uses_literal_arguments_and_retains_nonzero_status():
    from scripts.common import daily_support
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        paths = SimpleNamespace(python_exe=Path('python'), repo_root=root)
        arguments = ['--target-date', '2026-09-22']
        expected = {'module': 'scripts.storage.refresh_public_sources', 'exit_code': 2,
                    'log_path': str(root / 'provider.log')}
        with patch.object(daily_support, 'run_provider', return_value=expected) as run:
            result = module.run_provider(paths, expected['module'], arguments, root / 'provider.log')
        run.assert_called_once_with(paths, expected['module'], arguments, root / 'provider.log')
        assert result is expected and arguments == ['--target-date', '2026-09-22']


def test_provider_timeout_is_failure_not_old_success():
    from scripts.common import daily_support
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        paths = SimpleNamespace(python_exe=Path('python'), repo_root=root)
        expected = {'module': 'provider', 'exit_code': -1, 'log_path': str(root / 'timeout.log'),
                    'error': 'SYNTHETIC_ORIGINAL_OWNER_TIMEOUT'}
        with patch.object(daily_support, 'run_provider', return_value=expected) as run:
            result = module.run_provider(paths, 'provider', [], root / 'timeout.log')
        run.assert_called_once_with(paths, 'provider', [], root / 'timeout.log')
        assert result is expected and result['exit_code'] == -1 and 'error' in result


def test_atomic_result_does_not_leave_previous_ready_on_failure():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'latest.json'
        module.save(path, {'status': 'READY', 'rows': [{'ticker': 'OLD'}]})
        module.save(path, {'status': 'WAITING_DATA', 'rows': []})
        assert json.loads(path.read_text()) == {'status': 'WAITING_DATA', 'rows': []}
        assert not path.with_suffix('.json.tmp').exists()


def test_registered_alias_collapses_download_identity_and_history():
    history = {'records': [{'date': '2026-09-22', 'ticker': 'XYZ', 'rank': 4}],
               'bootstrap_records': [{'date': '2026-08-13', 'ticker': 'SQ', 'rank': 8}]}
    rows, normalized, aliases = module.normalize_acquisition_aliases(
        ['SQ', 'XYZ', 'AAPL'], [{'ticker': 'SQ', 'moomoo_symbol': 'US.XYZ', 'security_id': 'block'}], history)
    assert rows == [{'ticker': 'AAPL', 'moomoo_symbol': None}, {'ticker': 'SQ', 'moomoo_symbol': 'US.XYZ'}]
    assert aliases == {'XYZ': 'SQ'}
    assert normalized['records'][0]['ticker'] == 'SQ'
    assert history['records'][0]['ticker'] == 'XYZ'


def test_registered_alias_rejects_different_security_ids():
    import pytest
    with pytest.raises(ValueError, match='CONFLICTING_REGISTERED_SECURITY_IDENTITIES'):
        module.normalize_acquisition_aliases(['SQ', 'XYZ'], [
            {'ticker': 'SQ', 'moomoo_symbol': 'US.XYZ', 'security_id': 'one'},
            {'ticker': 'XYZ', 'moomoo_symbol': 'US.XYZ', 'security_id': 'two'}],
            {'records': [], 'bootstrap_records': []})


def test_transport_punctuation_is_not_invented():
    rows, _, aliases = module.normalize_acquisition_aliases(['BRK.B', 'BRK-B'],
        [{'ticker': 'BRK-B', 'moomoo_symbol': 'US.BRK.B', 'security_id': 'brkb'}],
        {'records': [], 'bootstrap_records': []})
    assert aliases == {}
    assert len(rows) == 2


def test_alternate_request_preserves_model_ticker_and_uses_verified_alias():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        paths = SimpleNamespace(cache_root=root, repo_root=root)
        plan = {'assignments': [{'ticker': ticker, 'provider': 'ALTERNATE'} for ticker in ('SQ', 'TPX', 'AAPL')]}
        with patch.object(module, 'run_provider', return_value={'exit_code': 0}) as runner:
            module.acquire_prices(paths, root, root, plan, '2025-08-18', '2026-09-22', lambda _: None)
        arguments = runner.call_args.args[2]
        assert '--events-through' in arguments
        aliases = json.loads(Path(arguments[arguments.index('--symbol-map') + 1]).read_text())
        assert aliases['SQ']['provider_symbol'] == 'XYZ'
        assert aliases['TPX']['provider_symbol'] == 'SGI'
        assert 'AAPL' not in aliases
        assert 'SQ' in arguments and 'TPX' in arguments


def test_public_source_failure_is_reported_without_blocking_price_inference():
    with patch('scripts.storage.refresh_current_observations.run_current_sources', side_effect=ValueError('SOURCE_DOWN')):
        result = module.acquire_other_data(SimpleNamespace(), Path('test_run'), '2026-09-22', {}, lambda _: None)
    assert result == {'status': 'PARTIAL', 'error': 'SOURCE_DOWN'}


def test_pool_supplement_uses_only_current_identities_existing_raw_and_aliases():
    with tempfile.TemporaryDirectory() as directory:
        price = Path(directory) / 'raw.csv'
        price.write_text('verified later')
        rows = module.current_pool_supplement(
            [{'ticker': 'SQ'}, {'ticker': 'NEW'}, {'ticker': 'MISSING'}, {'ticker': 'QFQ'}],
            {'XYZ': 'SQ'}, [
                {'ticker': 'XYZ', 'adjustment': 'raw', 'path': str(price), 'max_date': '2026-09-22'},
                {'ticker': 'OLD_ONLY', 'adjustment': 'raw', 'path': str(price), 'max_date': '2026-09-22'},
                {'ticker': 'MISSING', 'adjustment': 'raw', 'path': str(price) + '.gone', 'max_date': '2026-09-22'},
                {'ticker': 'QFQ', 'adjustment': 'qfq', 'path': str(price), 'max_date': '2026-09-22'},
            ])
        assert rows == [
            {'ticker': 'MISSING', 'last_price_date': None},
            {'ticker': 'NEW', 'last_price_date': None},
            {'ticker': 'QFQ', 'last_price_date': None},
            {'ticker': 'SQ', 'last_price_date': '2026-09-22'},
        ]


def test_failed_moomoo_assignment_also_attempts_alternate_provider():
    from scripts.storage import refresh_market_data as provider
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        paths = SimpleNamespace(cache_root=root, repo_root=root)
        plan = {'assignments': [{'ticker': 'AAPL', 'moomoo_symbol': 'US.AAPL', 'provider': 'MOOMOO'}]}
        with patch.object(provider, 'run', side_effect=RuntimeError('history not available')), \
             patch.object(module, 'run_provider', return_value={'exit_code': 0}) as alternate:
            result = module.acquire_prices(paths, root, root, plan, '2025-08-18', '2026-09-22', lambda _: None)
        assert result['moomoo']['status'] == 'FAILED'
        assert 'AAPL' in alternate.call_args.args[2]


def test_massive_runs_first_by_actual_provider_assignment_and_execution_marks():
    import sys
    import types
    calls = []
    fake = types.ModuleType('scripts.storage.refresh_current_massive')
    def massive(paths, members, sessions, target, work, progress):
        calls.append(('massive', [row['ticker'] for row in members]))
        return {'status': 'CACHE_ONLY'}
    fake.refresh_massive_current = massive
    plan = {'assignments': [
        {'ticker': 'FREQ', 'priority_tier': 'TOP20', 'provider': 'MOOMOO'},
        {'ticker': 'FICO', 'priority_tier': 'TOP20', 'provider': 'ALTERNATE',
         'reason': 'PROVIDER_REMAINING_OR_USER_CAP_EXHAUSTED'},
        {'ticker': 'HIVE', 'priority_tier': 'TOP20', 'provider': 'MOOMOO'},
        {'ticker': 'SFIX', 'priority_tier': 'TOP20', 'provider': 'MOOMOO'},
        {'ticker': 'FORTY', 'priority_tier': 'TOP40', 'provider': 'ALTERNATE'},
        {'ticker': 'POOL', 'priority_tier': 'POOL_REFRESH', 'provider': 'ALTERNATE'},
        {'ticker': 'NATIVE_POOL', 'priority_tier': 'POOL_REFRESH', 'provider': 'MOOMOO'},
        {'ticker': 'OLD', 'priority_tier': None, 'provider': 'ALTERNATE'},
    ]}
    def other(*args):
        calls.append(('other', None))
        return {'moomoo': {'status': 'READY'}}
    with patch.dict(sys.modules, {'scripts.storage.refresh_current_massive': fake}), \
         patch.object(module, 'acquire_prices', side_effect=other):
        result = module.acquire_pool_prices(None, None, None, plan, '2025-08-18', '2026-09-22',
            [{'ticker': ticker} for ticker in ('FREQ', 'FICO', 'HIVE', 'SFIX', 'FORTY', 'POOL', 'NATIVE_POOL', 'ALT')], [], lambda _: None)
    assert calls == [('massive', ['FICO', 'HIVE', 'SFIX', 'FORTY', 'POOL', 'ALT']), ('other', None)]
    assert result['massive']['status'] == 'CACHE_ONLY'


def moomoo_checkpoint_fixture(root, tickers):
    from scripts.storage import refresh_market_data as provider
    start, target = '2025-08-18', '2026-09-22'
    paths = SimpleNamespace(cache_root=root / 'cache', repo_root=root)
    cache = paths.cache_root / 'daily_recommendation/moomoo' / target
    assignments = [{'ticker': ticker, 'moomoo_symbol': 'US.' + ticker, 'provider': 'MOOMOO'} for ticker in tickers]
    items = provider.make_plan(provider.load_universe(tickers, None), start, target, ['raw', 'qfq'])

    def write(work_root, item, day):
        record = {'ticker': item['ticker'], 'moomoo_symbol': item['moomoo_symbol'],
            'market': 'US', 'date': day, 'open': 100., 'high': 100., 'low': 100., 'close': 100.,
            'volume': 1000., 'turnover': 100000., 'adjustment': item['adjustment'],
            'source': 'MOOMOO_OPEND', 'source_policy': 'MOOMOO_ONLY', 'snapshot_id': 'test',
            'fetched_at_utc': '2026-09-23T01:00:00+00:00'}
        return provider.save_interval(work_root, item, [record], 'a' * 64)

    for item in items:
        if item['ticker'] == 'AAPL':
            write(cache, item, target)
        elif item['ticker'] == 'TALK':
            write(cache, item, '2026-09-18' if item['adjustment'] == 'raw' else target)
    return provider, paths, cache, {'assignments': assignments}, start, target, write


def test_only_stale_ticker_retries_while_complete_and_new_use_stable_root():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        provider, paths, cache, plan, start, target, write = moomoo_checkpoint_fixture(root, ['AAPL', 'TALK', 'NEW'])
        original_files = {path: path.read_bytes() for path in cache.glob('intervals/*')}
        calls = []

        def acquire(args):
            universe = provider.load_universe(None, args.universe_csv)
            calls.append((args.work_root, [row['ticker'] for row in universe]))
            print('group=' + ','.join(row['ticker'] for row in universe))
            results = [provider.read_checkpoint(args.work_root, item) or write(args.work_root, item, target)
                       for item in provider.make_plan(universe, start, target, args.adjustments)]
            return {'status': 'ACQUIRED', 'results': results,
                'history_request_count': sum(row['status'] == 'FETCHED_VALIDATED_INTERVAL' for row in results),
                'new_unique_security_touch_count': 0, 'pending_leg_count': 0, 'request_audit': []}

        with patch.object(provider, 'run', side_effect=acquire), \
             patch.object(module, 'run_provider') as alternate:
            result = module.acquire_prices(paths, root, root, plan, start, target, lambda _: None)
        assert calls == [(cache, ['AAPL', 'NEW']), (cache / 'attempts' / root.name, ['TALK'])]
        assert not alternate.called
        merged = result['moomoo']
        assert len(merged['results']) == 6 and merged['history_request_count'] == 4
        assert {row['status'] for row in merged['results'] if row['item']['ticker'] == 'AAPL'} == {'REUSED_VERIFIED_INTERVAL'}
        assert merged['stale_retry_tickers'] == ['TALK'] and merged['status'] == 'ACQUIRED'
        assert all(path.read_bytes() == old for path, old in original_files.items())
        for batch in merged['batches']:
            assert Path(batch['log_path']).read_text().startswith('group=')
            assert json.loads(Path(batch['summary_path']).read_text())['results']


def test_retry_batch_failure_preserves_complete_receipts_and_falls_back():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        provider, paths, cache, plan, start, target, _ = moomoo_checkpoint_fixture(root, ['AAPL', 'TALK'])

        def acquire(args):
            if args.work_root != cache:
                raise RuntimeError('unsupported old ticker')
            rows = provider.load_universe(None, args.universe_csv)
            results = [provider.read_checkpoint(cache, item) for item in provider.make_plan(rows, start, target, args.adjustments)]
            return {'status': 'ALL_INTERVALS_REUSED', 'results': results}

        with patch.object(provider, 'run', side_effect=acquire), \
             patch.object(module, 'run_provider', return_value={'exit_code': 0}) as alternate:
            result = module.acquire_prices(paths, root, root, plan, start, target, lambda _: None)
        assert result['moomoo']['status'] == 'PARTIAL'
        assert len(result['moomoo']['results']) == 2
        arguments = alternate.call_args.args[2]
        assert 'TALK' in arguments and 'AAPL' not in arguments
        retry = next(row for row in result['moomoo']['batches'] if row['group'] == 'retry')
        assert 'unsupported old ticker' in json.loads(Path(retry['summary_path']).read_text())['error']


def test_damaged_checkpoint_is_not_bypassed_with_a_fresh_root():
    import pytest
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        provider, paths, cache, plan, start, target, _ = moomoo_checkpoint_fixture(root, ['AAPL'])
        next(cache.glob('intervals/*.csv')).write_text('changed')
        with patch.object(provider, 'run') as acquire, patch.object(module, 'run_provider') as alternate:
            with pytest.raises(ValueError, match='CHECKPOINT_IDENTITY_FAILED'):
                module.acquire_prices(paths, root, root, plan, start, target, lambda _: None)
        assert not acquire.called and not alternate.called


def topup_fixture(root):
    spec = importlib.util.spec_from_file_location('topup_test_planner', SOURCE.parent / 'storage/top20_quota_plan.py')
    planner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(planner)
    target = '2026-09-22'
    history = {'records': [{'ticker': ticker, 'date': target, 'rank': rank,
                            'record_kind': 'daily_recommendation'} for rank, ticker in enumerate(('BAD', 'OLD'), 1)],
               'bootstrap_records': []}
    universe = [{'ticker': ticker, 'moomoo_symbol': 'US.' + ticker} for ticker in ('OLD', 'BAD', 'NEXT')]
    pool = [{'ticker': row['ticker'], 'last_price_date': None} for row in universe]
    quota = {'used': 1, 'remaining': 1, 'details': [{'code': 'US.OLD'}]}
    plan = planner.build_top20_quota_plan(history['records'], quota, as_of_date=target,
        universe=universe, pool_supplement=pool, max_moomoo_symbols=2)
    rows = [{'status': 'FAILED_FETCH' if ticker == 'BAD' else 'FETCHED_VALIDATED_INTERVAL',
             'error': '未知股票 BAD' if ticker == 'BAD' else None,
             'item': {'ticker': ticker, 'moomoo_symbol': 'US.' + ticker,
                      'adjustment': adjustment, 'planned_end_date': target}}
            for ticker in ('OLD', 'BAD') for adjustment in ('raw', 'qfq')]
    acquisitions = {'moomoo': {'status': 'PARTIAL', 'results': rows, 'history_request_count': 4},
                    'massive': {'status': 'ACQUIRED'}}
    args = (SimpleNamespace(), root, root, plan, acquisitions, target, '2025-08-18', history, universe, pool)
    return planner, quota, acquisitions, args


@pytest.mark.parametrize('refusal', ['未知股票 BAD', '暂不提供美股 OTC 市场行情 BAD'])
def test_explicit_two_leg_refusal_fills_once_with_new_candidate_and_preserves_receipts(refusal):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        planner, quota, initial, args = topup_fixture(root)
        for row in initial['moomoo']['results'][2:]:
            row['error'] = refusal
        old_yahoo = {'results': [{'status': 'SUCCESS', 'contract': {'ticker': 'NEXT'}}],
                     'attempted_symbols': 1, 'successful_symbols': 1, 'target_reached_symbols': 1}
        module.save(root / 'first_yahoo.json', old_yahoo)
        initial['alternate'] = {'receipt': str(root / 'first_yahoo.json')}
        before = json.dumps(initial, sort_keys=True)

        def acquire(paths, unused_root, work, plan, start, target, progress):
            assert work == root / 'moomoo_topup'
            assert [row['ticker'] for row in plan['assignments']] == ['NEXT']
            assert all(row['provider'] == 'MOOMOO' for row in plan['assignments'])
            results = [{'status': 'FAILED_FETCH', 'error': 'network timeout',
                        'item': {'ticker': 'NEXT', 'moomoo_symbol': 'US.NEXT',
                                 'adjustment': adjustment, 'planned_end_date': target}} for adjustment in ('raw', 'qfq')]
            extra_yahoo = {'results': [{'status': 'FAILED', 'contract': {'ticker': 'NEXT'}}],
                           'attempted_symbols': 1, 'successful_symbols': 0, 'target_reached_symbols': 0}
            module.save(work / 'yahoo.json', extra_yahoo)
            return {'moomoo': {'status': 'PARTIAL', 'results': results, 'history_request_count': 2},
                    'alternate': {'receipt': str(work / 'yahoo.json')}}

        with patch('scripts.storage.top20_quota_plan.build_top20_quota_plan', wraps=planner.build_top20_quota_plan) as replan, \
             patch.object(module, 'live_quota', return_value=quota) as live, \
             patch.object(module, 'acquire_prices', side_effect=acquire) as fetch:
            result = module.topup_moomoo_once(*args, emit_progress=lambda _: None)
            repeated = module.topup_moomoo_once(*args[:4], result, *args[5:], emit_progress=lambda _: None)
        assert repeated is result and live.call_count == fetch.call_count == replan.call_count == 1
        assert replan.call_args.kwargs['provider_unavailable'] == ['US.BAD']
        assert json.dumps(initial, sort_keys=True) == before
        assert len(result['moomoo']['results']) == 6
        assert result['moomoo']['results'][:4] == initial['moomoo']['results']
        assert result['moomoo']['history_request_count'] == 6
        assert result['massive'] == initial['massive']
        assert result['moomoo_topup']['status'] == 'ATTEMPTED'
        assert Path(result['moomoo_topup']['acquisitions_path']).is_file()
        combined_yahoo = json.loads(Path(result['alternate']['receipt']).read_text())
        assert [row['status'] for row in combined_yahoo['results']] == ['SUCCESS', 'FAILED']
        assert combined_yahoo['attempted_symbols'] == 2 and len(combined_yahoo['source_reports']) == 2


@pytest.mark.parametrize('error', ['network timeout', '权限不足', '额度不足', 'EMPTY_RESPONSE', '未知股票 BAD2'])
def test_transient_or_nonexact_errors_never_release_topup_candidates(error):
    with tempfile.TemporaryDirectory() as directory:
        _, _, initial, args = topup_fixture(Path(directory))
        for row in initial['moomoo']['results'][2:]:
            row['error'] = error
        with patch.object(module, 'live_quota') as live, patch.object(module, 'acquire_prices') as fetch:
            result = module.topup_moomoo_once(*args, emit_progress=lambda _: None)
        assert not live.called and not fetch.called
        assert result['moomoo'] == initial['moomoo']
        assert result['moomoo_topup']['reason'] == 'NO_CONFIRMED_PROVIDER_REFUSALS'


@pytest.mark.parametrize('change', ['target', 'code', 'one_leg', 'successful_leg'])
def test_unbound_or_incomplete_refusal_cannot_trigger_topup(change):
    with tempfile.TemporaryDirectory() as directory:
        _, _, initial, args = topup_fixture(Path(directory))
        rows = initial['moomoo']['results']
        if change == 'target':
            rows[-1]['item']['planned_end_date'] = '2026-09-21'
        elif change == 'code':
            rows[-1]['item']['moomoo_symbol'] = 'US.OTHER'
        elif change == 'one_leg':
            rows.pop()
        else:
            rows[-1]['status'] = 'FETCHED_VALIDATED_INTERVAL'
        with patch.object(module, 'live_quota') as live, patch.object(module, 'acquire_prices') as fetch:
            result = module.topup_moomoo_once(*args, emit_progress=lambda _: None)
        assert not live.called and not fetch.called
        assert result['moomoo'] == initial['moomoo']


def test_topup_live_quota_failure_retains_first_pass_without_download():
    with tempfile.TemporaryDirectory() as directory:
        _, _, initial, args = topup_fixture(Path(directory))
        with patch.object(module, 'live_quota', side_effect=RuntimeError('QUOTA_DOWN')) as live, \
             patch.object(module, 'acquire_prices') as fetch:
            result = module.topup_moomoo_once(*args, emit_progress=lambda _: None)
        assert live.call_count == 1 and not fetch.called
        assert result['moomoo'] == initial['moomoo'] and result['massive'] == initial['massive']
        assert result['moomoo_topup']['status'] == 'FAILED'
        assert result['moomoo_topup']['error'] == 'QUOTA_DOWN'
        assert json.loads(Path(result['moomoo_topup']['report_path']).read_text())['error'] == 'QUOTA_DOWN'


def test_topup_acquisition_failure_preserves_first_pass_and_records_error():
    with tempfile.TemporaryDirectory() as directory:
        planner, quota, initial, args = topup_fixture(Path(directory))
        with patch('scripts.storage.top20_quota_plan.build_top20_quota_plan', wraps=planner.build_top20_quota_plan), \
             patch.object(module, 'live_quota', return_value=quota), \
             patch.object(module, 'acquire_prices', side_effect=RuntimeError('FETCH_DOWN')):
            result = module.topup_moomoo_once(*args, emit_progress=lambda _: None)
        assert result['moomoo'] == initial['moomoo']
        assert result['moomoo_topup']['status'] == 'FAILED'
        assert result['moomoo_topup']['selected_tickers'] == ['NEXT']


def test_topup_alternate_cache_is_distinct_between_parent_runs():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        paths = SimpleNamespace(cache_root=root / 'cache', repo_root=root)
        plan = {'assignments': [{'ticker': 'NEXT', 'provider': 'ALTERNATE'}]}
        with patch.object(module, 'run_provider', return_value={'exit_code': 0}) as fetch:
            for name in ('first_run', 'second_run'):
                work = root / name / 'moomoo_topup'
                work.mkdir(parents=True)
                module.acquire_prices(paths, root, work, plan, '2025-08-18', '2026-09-22', lambda _: None)
        roots = [call.args[2][call.args[2].index('--work-root') + 1] for call in fetch.call_args_list]
        assert roots == [paths.cache_root / 'daily_recommendation' / (name + '_moomoo_topup') / 'yahoo'
                         for name in ('first_run', 'second_run')]


@pytest.mark.parametrize('mode', ['enabled', 'default', 'proof_failure', 'wrong_date'])
def test_daily_expanded_anchors_join_one_common_prediction_and_preserve_other_gates(mode):
    import sys
    import types
    import pandas as pd
    from scripts import daily_recommendation_prices as daily_prices
    target = '2026-09-22'
    base = pd.DataFrame({'trade_date': [pd.Timestamp(target)] * 20,
                         'ticker': [f'B{i:02}' for i in range(20)], 'value': list(range(20))})
    members = [{'ticker': ticker, 'security_id': ticker, 'moomoo_symbol': 'US.' + ticker}
               for ticker in [*base.ticker, 'X0', 'X1', 'REHAB_GAP']]
    universe = {'current': True, 'universe_id': 'test_universe', 'members': members}
    binding = {'components': {'ALPHA': {'artifacts': [{'artifact_id': 'source', 'path': 'test_source.py'}]}}}
    source = SimpleNamespace(FEATURE_COLUMNS=('value',), build_stock_state_features=lambda prices: prices.copy())
    existing_lineage = [{'ticker': ticker, 'source': 'MOOMOO_OPEND_RAW_PLUS_REHAB'} for ticker in base.ticker]
    missing = [{'ticker': ticker, 'reason': 'A2_ORIGINAL_RAW_ANCHOR_UNBOUND'} for ticker in ('X0', 'X1')]
    missing.append({'ticker': 'REHAB_GAP', 'reason': 'LATEST_REHAB_RESPONSE_MISSING'})
    calendar_module = types.ModuleType('scripts.research.a2.inference.historical_top40')
    price_module = types.ModuleType('scripts.research.a2.inference.historical_top40_prices')
    calendar_module.load_sessions = lambda paths: (['2020-01-02', target], {'lineage': {'source': 'verified_calendar'}})
    calls = []

    def expand(paths, wanted, start, end, dates, acquisitions, rehab, output):
        calls.append(wanted)
        assert {row['ticker'] for row in wanted} == {'X0', 'X1'}
        assert start == end == target
        if mode == 'proof_failure':
            raise ValueError('FROZEN_PRICE_SOURCE_HASH_CHANGED')
        manifest = output / 'prices/manifest.json'
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{}')
        extra = pd.DataFrame([{'ticker': 'X0', 'trade_date': pd.Timestamp('2026-09-21' if mode == 'wrong_date' else target), 'value': 100.}])
        return extra, [{'ticker': 'X0', 'anchor_proof': {'kind': 'FROZEN_PRE2026_PRICE_EQUIVALENCE'},
                        'alternate_bridge': None}], [{'ticker': 'X1', 'reasons': ['EXPANDED_ANCHOR_NO_FROZEN_PRICE_ROWS']}]

    price_module.build_price_features = expand

    def predict(day, payload, component, module_loader):
        ranked = sorted(payload['feature_rows'], key=lambda row: row['value'], reverse=True)
        return [{'ticker': row['ticker'], 'security_id': row['security_id'], 'rank': rank, 'score': row['value']}
                for rank, row in enumerate(ranked, 1)]

    with tempfile.TemporaryDirectory() as directory, \
         patch.dict(sys.modules, {calendar_module.__name__: calendar_module, price_module.__name__: price_module}), \
         patch.object(daily_prices, 'load_price_inputs', return_value=(base, existing_lineage, missing)), \
         patch('scripts.storage.refresh_market_data.load_module', return_value=source), \
         patch('scripts.v22.forward_shadow.exact_date_components.run_alpha_single_date', side_effect=predict) as model:
        kwargs = {} if mode == 'default' else {'output_dir': Path(directory)}
        rows, lineage, excluded = module.predict_current(binding, universe, target, [target], {},
            SimpleNamespace(paths=SimpleNamespace()), {}, **kwargs)
    assert model.call_count == 1
    assert any(row['ticker'] == 'REHAB_GAP' for row in excluded)
    if mode == 'enabled':
        assert len(rows) == 21 and rows[0]['ticker'] == 'X0' and rows[0]['rank'] == 1
        assert not any(row['ticker'] == 'X0' for row in excluded)
        proof = next(row for row in lineage if row['ticker'] == 'X0')
        assert proof['anchor_proof']['kind'] == 'FROZEN_PRE2026_PRICE_EQUIVALENCE'
        assert proof['source'] == 'MOOMOO_OPEND_RAW_PLUS_REHAB'
        assert proof['expanded_anchor_manifest']['sha256']
        assert next(row for row in excluded if row['ticker'] == 'X1')['expanded_anchor_details']['reasons']
    else:
        assert len(rows) == 20 and not any(row['ticker'] == 'X0' for row in lineage)
        if mode == 'default':
            assert calls == []
        else:
            assert next(row for row in excluded if row['ticker'] == 'X0')['expanded_anchor_error']


@pytest.mark.parametrize('kind', ['real', 'fake', 'mock'])
def test_current_prices_share_batch_validation_only_for_real_datastore(kind):
    from unittest.mock import Mock
    from scripts import daily_recommendation_prices as daily_prices
    from scripts.storage.storage_r2a import DataStore
    from scripts.research.a2.inference.historical_top40_prices import ValidatedBatchStore
    store = (object.__new__(DataStore) if kind == 'real' else
             Mock(spec=DataStore) if kind == 'mock' else SimpleNamespace())
    binding = {'components': {'ALPHA': {'artifacts': [{'artifact_id': 'source', 'path': 'synthetic_source.py'}]}}}
    with patch('scripts.storage.refresh_market_data.load_module', return_value=SimpleNamespace()), \
         patch.object(daily_prices, 'load_price_inputs', side_effect=RuntimeError('PRICE_LOAD_SENTINEL')) as load:
        with pytest.raises(RuntimeError, match='PRICE_LOAD_SENTINEL'):
            module.predict_current(binding, {'current': True, 'members': []}, '2026-09-22', [], {}, store, {})
    selected = load.call_args.args[4]
    if kind == 'real':
        assert isinstance(selected, ValidatedBatchStore) and selected._store is store
    else:
        assert selected is store


def _worker_source(tmp_path):
    import hashlib
    source = tmp_path / 'A2_today_recommendation/runs/synthetic/recommendation_source.json'
    module.save(source, {'status': 'READY', 'data_date': '2025-01-03', 'report_path': str(source)})
    return source, hashlib.sha256(source.read_bytes()).hexdigest()


@pytest.mark.parametrize('kind,action_name', [('raw', 'update_demo_performance'), ('selected', 'update_selected_strategies')])
def test_fixed_performance_worker_dispatches_existing_producer_without_daily_lock(tmp_path, monkeypatch, kind, action_name):
    source, sha = _worker_source(tmp_path)
    paths = SimpleNamespace(daily_root=tmp_path)
    calls = []
    monkeypatch.setattr(module, 'single_update', lambda *_: pytest.fail('Child reacquired parent lock'))
    monkeypatch.setattr(module, action_name,
        lambda actual_paths, result, run_dir: calls.append((actual_paths, result, run_dir)) or {'status': 'READY'})
    assert module._performance_worker(paths, kind, source, sha) == {'status': 'READY'}
    assert calls[0][0] is paths and calls[0][2] == source.parent
    assert calls[0][1]['data_date'] == '2025-01-03'


@pytest.mark.parametrize('defect', ['path', 'hash', 'not_ready', 'report_binding', 'oversize', 'action'])
def test_performance_worker_rejects_unbound_input_before_producer(tmp_path, monkeypatch, defect):
    import hashlib
    source, sha = _worker_source(tmp_path)
    kind = 'raw'
    if defect == 'path':
        wrong = tmp_path / 'recommendation_source.json'
        wrong.write_bytes(source.read_bytes())
        source = wrong
    elif defect == 'hash':
        sha = '0' * 64
    elif defect in {'not_ready', 'report_binding'}:
        body = json.loads(source.read_text())
        body['status' if defect == 'not_ready' else 'report_path'] = 'invalid'
        module.save(source, body)
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
    elif defect == 'oversize':
        source.write_bytes(b' ' * (10 * 1024 * 1024 + 1))
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
    else:
        kind = 'arbitrary_function'
    monkeypatch.setattr(module, 'update_demo_performance', lambda *_: pytest.fail('Invalid input reached producer'))
    with pytest.raises(ValueError):
        module._performance_worker(SimpleNamespace(daily_root=tmp_path), kind, source, sha)


def test_performance_worker_detects_source_mutation_after_producer(tmp_path, monkeypatch):
    source, sha = _worker_source(tmp_path)
    def producer(*_):
        source.write_text('{}')
        return {'status': 'READY'}
    monkeypatch.setattr(module, 'update_demo_performance', producer)
    with pytest.raises(ValueError, match='CHANGED_DURING'):
        module._performance_worker(SimpleNamespace(daily_root=tmp_path), 'raw', source, sha)


@pytest.mark.parametrize('first_defect', [None, 'nonzero', 'missing', 'duplicate', 'oversize', 'malformed'])
def test_isolated_performance_runs_sequentially_and_selected_survives_raw_failure(tmp_path, monkeypatch, first_defect):
    paths = SimpleNamespace(daily_root=tmp_path)
    run_dir = tmp_path / 'A2_today_recommendation/runs/new'
    actions = []
    def provider(actual_paths, module_name, argv, log):
        assert actual_paths is paths and module_name == 'scripts.daily_recommendation'
        kind = argv[1]; actions.append(kind)
        assert argv[0] == '--performance-worker' and argv[2] == '--source-report'
        assert argv[4] == '--source-sha256'
        assert Path(argv[3]).parent == run_dir
        defect = first_defect if kind == 'raw' else None
        event = json.dumps({'event': 'performance_result', 'result': {'status': 'READY', 'kind': kind}})
        content = event
        if defect == 'missing': content = '{}'
        if defect == 'duplicate': content = event + '\n' + event
        if defect == 'oversize': content = ' ' * (1024 * 1024 + 1)
        if defect == 'malformed': content = json.dumps({'event': 'performance_result', 'result': []})
        log.write_text(content + '\n', encoding='utf-8')
        return {'exit_code': 2 if defect == 'nonzero' else 0}
    monkeypatch.setattr(module, 'run_provider', provider)
    raw, selected = module.update_performance_isolated(paths, {'status': 'READY'}, run_dir, lambda _: None)
    assert actions == ['raw', 'selected']
    assert raw['status'] == ('BLOCKED' if first_defect else 'READY')
    assert selected == {'status': 'READY', 'kind': 'selected'}


def test_performance_main_private_action_does_not_collect_data(tmp_path, monkeypatch, capsys):
    from scripts.common import storage_paths
    source, sha = _worker_source(tmp_path)
    paths = SimpleNamespace(daily_root=tmp_path)
    monkeypatch.setattr(storage_paths, 'resolve', lambda: paths)
    monkeypatch.setattr(module, 'run_update', lambda *_: pytest.fail('Private action collected data'))
    monkeypatch.setattr(module, 'update_demo_performance', lambda *_: {'status': 'READY'})
    assert module.main(['--performance-worker', 'raw', '--source-report', str(source), '--source-sha256', sha]) == 0
    assert json.loads(capsys.readouterr().out)['event'] == 'performance_result'


def test_isolated_performance_real_children_use_canonical_module_and_exit(tmp_path):
    import os
    import sys
    repo = tmp_path / 'repo'
    common = repo / 'scripts/common'
    common.mkdir(parents=True)
    (repo / 'scripts/__init__.py').write_text('')
    (common / '__init__.py').write_text('')
    (common / 'daily_support.py').write_bytes((SOURCE.parent / 'common/daily_support.py').read_bytes())
    daily = tmp_path / 'daily'
    (common / 'storage_paths.py').write_text(
        'from pathlib import Path\nfrom types import SimpleNamespace\n'
        + 'def resolve(): return SimpleNamespace(daily_root=Path(' + repr(str(daily)) + '))\n')
    worker_code = SOURCE.read_text(encoding='utf-8')
    stubs = (
        "\ndef update_demo_performance(paths, result, run_dir, progress=emit):\n"
        "    print('合成中文 stderr 诊断', file=sys.stderr)\n"
        "    return {'status': 'READY', 'pid': os.getpid(), 'data_date': result['data_date']}\n"
        "def update_selected_strategies(paths, result, run_dir, progress=emit):\n"
        "    return {'status': 'READY', 'pid': os.getpid(), 'data_date': result['data_date']}\n")
    worker_code = worker_code.replace("if __name__ == '__main__':", stubs + "\nif __name__ == '__main__':")
    (repo / 'scripts/daily_recommendation.py').write_text(worker_code, encoding='utf-8')
    paths = SimpleNamespace(repo_root=repo, daily_root=daily, python_exe=Path(sys.executable))
    raw, selected = module.update_performance_isolated(paths,
        {'status': 'READY', 'data_date': '2025-01-03'}, daily / 'A2_today_recommendation/runs/synthetic', lambda _: None)
    assert raw['status'] == selected['status'] == 'READY'
    assert raw['data_date'] == selected['data_date'] == '2025-01-03'
    assert raw['pid'] != selected['pid'] and raw['pid'] != os.getpid()


def acquisition_notes_fixture(tmp_path, *, all_retired=False):
    import hashlib
    from datetime import datetime, timezone
    paths = SimpleNamespace(daily_root=tmp_path / 'daily', results_root=tmp_path / 'results',
                            cache_root=tmp_path / 'cache', repo_root=tmp_path / 'repo',
                            backtest_root=tmp_path / 'backtests')
    retired = ('APGE', 'AVB', 'BLD', 'DBRG', 'EA', 'GBTG', 'GTLS', 'NUVL', 'OLPX',
               'SILA', 'TALK', 'TMHC', 'WBS', 'GE.WI') if all_retired else ('OLD',)
    evidence = paths.results_root / 'synthetic_lifecycle.json'
    evidence.parent.mkdir(parents=True)
    facts = [{'ticker': ticker, 'kind': 'ACQUISITION_COMPLETED', 'event_date': '2026-10-01',
              'url': 'https://issuer.example/synthetic/' + ticker} for ticker in retired]
    if all_retired:
        facts[-1].update(kind='TEMPORARY_EX_DISTRIBUTION_TRANSPORT',
                         temporary_market_end='2024-04-01')
    evidence.write_text(json.dumps({'primary_security_lifecycle_evidence': facts}))
    ref = {'path': str(evidence), 'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest()}
    notes = [{'ticker': fact['ticker'], 'security_id': f'{i:09d}',
              'moomoo_symbol': 'US.' + fact['ticker'], 'kind': fact['kind'],
              'inactive_after_date': fact.get('temporary_market_end', fact['event_date']),
              'checked_at_utc': '2026-10-02T20:30:00Z', 'note_zh': '合成测试停用事实',
              'retry_condition': '仅身份变化或人工复核', 'scope': 'CURRENT_ACQUISITION_ONLY',
              'evidence': ref.copy(), 'official_urls': [fact['url']]} for i, fact in enumerate(facts)]
    members = [{key: note[key] for key in ('ticker', 'security_id', 'moomoo_symbol')} for note in notes]
    path = paths.daily_root / 'A2_today_recommendation/acquisition_notes.json'
    path.parent.mkdir(parents=True)
    import pandas as pd
    binding = path.parent / 'synthetic_members.parquet'
    pd.DataFrame(members).to_parquet(binding, index=False)
    document = {'schema': 'USTQ_CURRENT_ACQUISITION_NOTES_V1', 'notes': notes,
                'member_binding': {'path': str(binding), 'sha256': hashlib.sha256(binding.read_bytes()).hexdigest()}}
    path.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
    return paths, path, document, members, datetime(2026, 10, 6, tzinfo=timezone.utc)


@pytest.mark.parametrize('target,expected', [('2026-09-30', 0), ('2026-10-01', 0), ('2026-10-02', 1)])
def test_acquisition_note_only_applies_after_inactive_date(tmp_path, target, expected):
    paths, _, _, members, now = acquisition_notes_fixture(tmp_path)
    audit = module.load_acquisition_notes(paths, target, members, now)
    assert audit['status'] == 'READY'
    assert len(audit['deferred']) == expected


@pytest.mark.parametrize('change', ['security_id', 'moomoo_symbol', 'ticker', 'absent_member'])
def test_acquisition_note_requires_same_current_identity_not_catalog_name(tmp_path, change):
    paths, _, _, members, now = acquisition_notes_fixture(tmp_path)
    if change == 'absent_member': members = []
    else: members[0][change] = 'NEW' if change != 'moomoo_symbol' else 'US.NEW'
    assert not module.load_acquisition_notes(paths, '2026-10-02', members, now)['deferred']


def test_temporary_ge_note_does_not_suppress_regular_ge(tmp_path):
    paths, _, _, members, now = acquisition_notes_fixture(tmp_path, all_retired=True)
    regular = {**members[-1], 'ticker': 'GE', 'moomoo_symbol': 'US.GE'}
    audit = module.load_acquisition_notes(paths, '2026-10-02', members[:-1] + [regular], now)
    assert len(audit['deferred']) == 13
    assert all(note['ticker'] != 'GE.WI' for note in audit['deferred'])


@pytest.mark.parametrize('damage', ['schema', 'duplicate', 'conflict', 'hash', 'outside', 'fact_date',
                                     'fact_kind', 'future_check', 'scope', 'urls', 'security', 'malformed',
                                     'member_hash', 'member_outside', 'unbound_cusip', 'announced'])
def test_bad_acquisition_note_invalidates_whole_manifest_without_skipping(tmp_path, damage):
    paths, path, document, members, now = acquisition_notes_fixture(tmp_path, all_retired=True)
    note = document['notes'][-1]
    if damage == 'schema': document['schema'] = 'UNKNOWN'
    elif damage in {'duplicate', 'conflict'}:
        repeated = note.copy()
        if damage == 'conflict': repeated['security_id'] = '999999999'
        document['notes'].append(repeated)
    elif damage == 'hash': note['evidence']['sha256'] = '0' * 64
    elif damage == 'outside': note['evidence']['path'] = str(path)
    elif damage == 'fact_date': note['inactive_after_date'] = '2024-04-02'
    elif damage == 'fact_kind': note['kind'] = 'SAME_CUSIP_RENAMED_TRANSPORT'
    elif damage == 'future_check': note['checked_at_utc'] = '2026-10-07T00:00:00Z'
    elif damage == 'scope': note['scope'] = 'MODEL_ELIGIBILITY'
    elif damage == 'urls': note['official_urls'] = ['https://other.example/fact']
    elif damage == 'security': note['security_id'] = ''
    elif damage == 'member_hash': document['member_binding']['sha256'] = '0' * 64
    elif damage == 'member_outside': document['member_binding']['path'] = note['evidence']['path']
    elif damage == 'unbound_cusip':
        note['security_id'] = '999999999'
        members[-1]['security_id'] = '999999999'
    elif damage == 'announced':
        import hashlib
        evidence = Path(note['evidence']['path'])
        facts = json.loads(evidence.read_text())
        facts['primary_security_lifecycle_evidence'][-1]['kind'] = 'MERGER_ANNOUNCED'
        evidence.write_text(json.dumps(facts))
        digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
        for entry in document['notes']: entry['evidence']['sha256'] = digest
        note.update(kind='MERGER_ANNOUNCED', inactive_after_date='2026-10-01')
    if damage == 'malformed': path.write_text('{')
    else: path.write_text(json.dumps(document), encoding='utf-8')
    audit = module.load_acquisition_notes(paths, '2026-10-02', members, now)
    assert audit['status'] == 'INVALID' and audit['deferred'] == [] and audit['error']


def test_absent_notes_keep_original_acquisition_objects_and_history_values(tmp_path):
    from datetime import datetime, timezone
    paths = SimpleNamespace(daily_root=tmp_path)
    members = [{'ticker': 'OLD', 'security_id': '000000000', 'moomoo_symbol': 'US.OLD'}]
    acquisition = [{'ticker': 'OLD', 'moomoo_symbol': 'US.OLD'}]
    history = {'records': [{'ticker': 'OLD', 'rank': 1, 'score': .123}], 'bootstrap_records': []}
    audit = module.load_acquisition_notes(paths, '2026-10-02', members, datetime.now(timezone.utc))
    active, copied, active_members = module.acquisition_note_context(acquisition, history, members, {}, audit)
    assert audit['status'] == 'ABSENT' and active == acquisition and copied == history and active_members == members
    assert active_members[0] is members[0] and copied['records'][0] is history['records'][0]


def test_daily_notes_remove_fourteen_from_all_collection_entries_but_keep_model_universe(tmp_path, monkeypatch):
    import sys
    import types
    from scripts import daily_recommendation_inputs as inputs, daily_recommendation_universe as identity
    from scripts import daily_recommendation_prices as prices
    from scripts.storage import storage_r2a, manage_data, refresh_market_data as market, refresh_demo_benchmarks
    paths, _, _, retired, _ = acquisition_notes_fixture(tmp_path, all_retired=True)
    good = [{'ticker': f'T{i:02}', 'security_id': f'{i+100:09d}', 'moomoo_symbol': f'US.T{i:02}'} for i in range(20)]
    universe = {'current': True, 'universe_id': 'ORIGINAL_FROZEN_IDENTITY', 'members': retired + good}
    before = json.dumps(universe, sort_keys=True)
    target = '2026-10-02'
    model = {'components': {'ALPHA': {'artifacts': [{'artifact_id': 'model', 'sha256': 'a' * 64}]}}}
    history = {'records': [{'ticker': row['ticker'], 'rank': i + 1, 'date': target,
                           'record_kind': 'daily', 'model_id': 'frozen', 'source_id': 'synthetic'}
                          for i, row in enumerate(retired + good)], 'bootstrap_records': []}
    original_history = json.dumps(history, sort_keys=True)
    monkeypatch.setattr(inputs, 'load_frozen_binding', lambda *_: model)
    monkeypatch.setattr(inputs, 'latest_completed_session', lambda *_: {'target_date': target, 'sessions': [target]})
    monkeypatch.setattr(inputs, 'load_bound_universe', lambda *_: universe)
    monkeypatch.setattr(inputs, 'load_priority_history', lambda *_: history)
    monkeypatch.setattr(identity, 'refresh_universe', lambda *a, **kw: universe)
    monkeypatch.setattr(storage_r2a, 'DataStore', lambda: object())
    monkeypatch.setattr(manage_data, 'status', lambda *_: {})
    monkeypatch.setattr(manage_data, 'acquisition_tickers', lambda *_: [row['ticker'] for row in retired + good] + ['CATALOG_ONLY'])
    monkeypatch.setattr(manage_data, 'read_catalog', lambda *_: ([], []))
    monkeypatch.setattr(module, 'live_quota', lambda *_: (299, 1, [{'code': f'US.K{i:03}'} for i in range(299)]))
    calls = {}
    def history_api(args):
        import csv
        with args.universe_csv.open() as stream: calls['moomoo'] = list(csv.DictReader(stream))
        raise RuntimeError('synthetic history unavailable')
    monkeypatch.setattr(market, 'run', history_api)
    def alternate(paths, owner, args, log):
        assert owner == 'scripts.storage.refresh_free_market'
        calls['alternate'] = args[args.index('--tickers') + 1:]
        return {'status': 'SYNTHETIC'}
    monkeypatch.setattr(module, 'run_provider', alternate)
    fake = types.ModuleType('scripts.storage.refresh_current_massive')
    def massive(paths, members, *a, **kw):
        calls['massive'] = members
        return {'status': 'SYNTHETIC'}
    fake.refresh_massive_current = massive
    monkeypatch.setitem(sys.modules, 'scripts.storage.refresh_current_massive', fake)
    monkeypatch.setattr(prices, 'publish_acquired_prices', lambda *a, **kw: {'status': 'SYNTHETIC'})
    monkeypatch.setattr(refresh_demo_benchmarks, 'refresh_demo_benchmarks', lambda *a: {})
    monkeypatch.setattr(module, 'acquire_other_data', lambda *a: {})
    def rehab(paths, members, *a, **kw):
        calls['rehab'] = members
        return {'status': 'SYNTHETIC'}
    monkeypatch.setattr(prices, 'refresh_rehab', rehab)
    def predict(binding, original, *a, **kw):
        assert original is universe and json.dumps(original, sort_keys=True) == before
        return ([{'ticker': row['ticker'], 'rank': i+1, 'score': .001} for i, row in enumerate(good)], [],
                [{'ticker': row['ticker'], 'reason': 'ORIGINAL_INPUT_GAP'} for row in retired])
    monkeypatch.setattr(module, 'predict_current', predict)
    monkeypatch.setattr(module, 'update_performance_isolated', lambda *a: (
        {'status': 'READY', 'performance_end_date': target}, {'status': 'READY', 'performance_end_date': target}))
    result = module.run_update(paths, execute=True, emit_progress=lambda *_: None)
    assert result['status'] == 'READY'
    assert len(result['acquisition_notes']['deferred']) == 14
    retired_names = {row['ticker'] for row in retired}
    assert calls.keys() == {'moomoo', 'alternate', 'massive', 'rehab'}
    assert not retired_names.intersection(calls['alternate'])
    for key in ('moomoo', 'massive', 'rehab'):
        assert not retired_names.intersection(row['ticker'] for row in calls[key])
    assert 'CATALOG_ONLY' in calls['alternate']  # No current CUSIP: never infer an inactive note.
    assert len(result['ranked_rows']) == 20 and result['coverage']['mapped_count'] == 34
    assert json.dumps(universe, sort_keys=True) == before and json.dumps(history, sort_keys=True) == original_history
    missing = json.loads((Path(result['report_path']).parent / 'excluded.json').read_text())['price_or_feature_gaps']
    assert len(missing) == 14 and all(row['reason'] == 'ORIGINAL_INPUT_GAP' and row['acquisition_note']['evidence'] for row in missing)


def test_acquisition_note_member_anchor_projects_only_identity_columns(tmp_path, monkeypatch):
    import pyarrow.parquet as pq
    paths, _, _, members, now = acquisition_notes_fixture(tmp_path)
    original = pq.read_table
    reads = []
    def read_table(*args, **kwargs):
        reads.append(kwargs['columns'])
        return original(*args, **kwargs)
    monkeypatch.setattr(pq, 'read_table', read_table)
    audit = module.load_acquisition_notes(paths, '2026-10-02', members, now)
    assert audit['status'] == 'READY' and len(audit['deferred']) == 1
    assert reads == [['ticker', 'security_id', 'moomoo_symbol']]


def test_execution_chart_noop_uses_global_lock_and_never_starts_worker(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from scripts.common import storage_paths
    events = []
    @contextmanager
    def locked(root):
        events.append('enter'); yield; events.append('exit')
    paths = SimpleNamespace(daily_root=tmp_path)
    context = {'status': 'READY', 'signal_date': '2026-10-02', 'execution_date': '2026-10-05',
               'package': {'sha256': 'a' * 64}, 'source_report': {'path': 'source', 'sha256': 'b' * 64}}
    monkeypatch.setattr(module, 'single_update', locked)
    monkeypatch.setattr(module, '_execution_chart_context', lambda *args: context)
    monkeypatch.setattr(module, '_execution_charts_current', lambda *args: True)
    monkeypatch.setattr(module, 'run_provider', lambda *args: pytest.fail('no provider or replay'))
    monkeypatch.setattr(storage_paths, 'assert_safe_output_path', lambda *args, **kwargs: None)
    result = module.run_execution_charts(paths)
    assert result['status'] == 'READY' and result['provider_calls'] == result['replay_calls'] == 0
    assert events == ['enter', 'exit']
    assert json.loads(next(tmp_path.glob('A2_today_recommendation/execution_charts/*/*/state.json')).read_text()) == result


@pytest.mark.parametrize('status', ['WAITING_OPEN', 'WAITING_SOURCE'])
def test_execution_chart_unavailable_clock_never_writes_or_starts_provider(tmp_path, monkeypatch, status):
    from contextlib import nullcontext
    monkeypatch.setattr(module, 'single_update', lambda root: nullcontext())
    monkeypatch.setattr(module, '_execution_chart_context', lambda *args: {'status': status})
    monkeypatch.setattr(module, 'run_provider', lambda *args: pytest.fail('not yet available'))
    assert module.run_execution_charts(SimpleNamespace(daily_root=tmp_path)) == {'status': status}
    assert not list(tmp_path.iterdir())


def test_execution_open_union_includes_research_only_and_retired_held_identity(tmp_path, monkeypatch):
    import pandas as pd
    from scripts.research.a2.evaluation import three_strategy_extension as extension
    source = tmp_path / 'source.json'; source.write_text(json.dumps({'ranked_rows': [{'ticker': 'RAW', 'rank': 1}]}))
    mapping = tmp_path / 'mapped.parquet'
    pd.DataFrame([{'ticker': ticker, 'security_id': str(i).zfill(9), 'moomoo_symbol': 'US.' + ticker}
        for i, ticker in enumerate(['RAW', 'CUR', 'OLD', 'LEAF'])]).to_parquet(mapping, index=False)
    old = tmp_path / 'historical.json'
    old.write_text(json.dumps({'lineage': [
        {'ticker': 'HELD', 'code': 'US.HELD', 'cusips': ['123456789']},
        {'ticker': 'INVEST', 'code': 'US.INVEST', 'cusips': ['987654321']}]}))
    positions = tmp_path / 'positions.parquet'
    pd.DataFrame({'date': pd.to_datetime(['2026-10-02']), 'ticker': ['HELD'], 'shares_after': [1.]}).to_parquet(positions)
    raw = tmp_path / 'raw.json'; raw.write_text(json.dumps({'performance_end_date': '2026-10-02',
        'outputs': {'positions': extension.reference(positions)}}))
    context = {'source_report': extension.reference(source), 'raw_manifest': extension.reference(raw),
        'identity_binding': extension.reference(mapping), 'historical_identity_binding': extension.reference(old),
        'signal_date': '2026-10-02'}
    package = {'shared_scores': {'current': {'rows': [{'ticker': 'CUR'}]}}}
    replay = {'shared_scores_historical': [{'ticker': 'OLD', 'signal_date': '2026-10-02'}],
        'strategies': {'X': {'targets': [{'rows': [
            {'ticker': 'HELD', 'target_weight': .1},
            {'ticker': 'INVEST', 'target_weight': .2},
            {'ticker': 'SOLD', 'target_weight': 0.}]}]}}}
    replay['source_refs'] = [{'path': 'synthetic-leaf', 'sha256': 'a' * 64}]
    monkeypatch.setattr(extension, 'prior_price_capture', lambda value: ({}, {'execution_open': {'qualified_tickers': ['LEAF']}}))
    monkeypatch.setattr(module, '_execution_selected_manifest', lambda value: (package, replay, {}))
    rows = module._execution_open_members(None, context)
    assert {row['ticker'] for row in rows} == {'RAW', 'CUR', 'OLD', 'HELD', 'INVEST', 'LEAF'}
    # SOLD has no bound identity and no shares: it must not trigger an API touch
    # or an identity error. Positive research-only INVEST remains required.
    assert 'SOLD' not in {row['ticker'] for row in rows}
    assert next(row for row in rows if row['ticker'] == 'INVEST')['security_id'] == '987654321'
    assert next(row for row in rows if row['ticker'] == 'HELD')['security_id'] == '123456789'
    old.write_text(json.dumps({'lineage': []})); context['historical_identity_binding'] = extension.reference(old)
    with pytest.raises(ValueError, match='HELD_IDENTITY_UNBOUND'):
        module._execution_open_members(None, context)


def test_execution_worker_path_guard_precedes_real_provider(tmp_path, monkeypatch):
    paths = SimpleNamespace(daily_root=tmp_path)
    monkeypatch.setattr(module, '_execution_open_acquire', lambda *args: pytest.fail('bad path'))
    with pytest.raises(ValueError, match='OUTSIDE_DAILY_OWNER'):
        module._execution_chart_worker(paths, 'execution-inputs', tmp_path / 'outside.json', 'a' * 64)


def test_execution_chart_cli_cannot_be_combined_with_daily_acquisition():
    with pytest.raises(SystemExit):
        module.main(['--execution-charts', '--execute'])


def test_execution_open_retry_reuses_provider_receipts_and_preserves_every_old_hash(tmp_path, monkeypatch):
    import pandas as pd
    from scripts.common import storage_paths
    from scripts.storage import refresh_market_data
    from scripts import daily_recommendation_prices
    from scripts.research.a2.evaluation import three_strategy_extension as extension
    paths = SimpleNamespace(cache_root=tmp_path / 'cache', repo_root=tmp_path / 'repo')
    paths.cache_root.mkdir(); paths.repo_root.mkdir()
    sdk = tmp_path / 'sdk.parquet'
    pd.DataFrame({'time_key': ['2026-10-02 00:00:00', '2026-10-05 00:00:00'],
        'code': ['US.AA'] * 2, 'open': [10., 11.]}).to_parquet(sdk, index=False)
    raw = tmp_path / 'raw.csv'; raw.write_text('real synthetic completed prefix')
    row = {'status': 'FETCHED_VALIDATED_INTERVAL', 'item': {'moomoo_symbol': 'US.AA'},
        **extension.reference(raw), 'current_kline_provenance': {'sdk_response': extension.reference(sdk)}}
    factor_file = tmp_path / 'factor.parquet'; pd.DataFrame({'code': []}).to_parquet(factor_file)
    factors = {'code': 'US.AA', 'status': 'PASS', **extension.reference(factor_file)}
    calls = []
    def acquire(args):
        calls.append(args)
        return {'results': [row]}
    monkeypatch.setattr(refresh_market_data, 'run', acquire)
    monkeypatch.setattr(daily_recommendation_prices, 'refresh_rehab', lambda *args: {'results': [factors]})
    monkeypatch.setattr(storage_paths, 'assert_safe_output_path', lambda *args, **kwargs: None)
    monkeypatch.setattr(module, '_execution_open_members', lambda *args: [
        {'ticker': 'AA', 'security_id': '123456789', 'moomoo_symbol': 'US.AA'}])
    context = {'execution_date': '2026-10-05', 'signal_date': '2026-10-02',
        'sessions': ['2026-09-28', '2026-09-29', '2026-09-30', '2026-10-01', '2026-10-02'],
        'package': {'sha256': 'a' * 64}, 'source_report': {'path': 'source', 'sha256': 'b' * 64},
        'identity_binding': {'path': 'mapped', 'sha256': 'c' * 64},
        'historical_identity_binding': {'path': 'historical', 'sha256': 'd' * 64}}
    first = module._execution_open_acquire(paths, context, tmp_path)
    old_manifest = Path(first['manifest']['path']).read_bytes()
    old = json.loads(old_manifest)
    second = module._execution_open_acquire(paths, context, tmp_path)
    assert first['status'] == second['status'] == 'READY' and len(calls) == 1
    assert Path(first['manifest']['path']).read_bytes() == old_manifest
    extension.verify_refs([first['manifest'], old['acquisition_manifest'], old['rehab_receipt']])
    assert calls[0].acquisition_mode == 'current-kline' and calls[0].adjustments == ['raw']
    assert calls[0].max_retries == 0 and calls[0].start == '2026-09-28' and calls[0].end == '2026-10-02'
    assert first['manifest'] != second['manifest']


@pytest.mark.parametrize('now,generated,expected', [
    ('2026-10-05T13:29:00+00:00', '2026-10-02T20:01:00+00:00', 'WAITING_OPEN'),
    ('2026-10-04T13:31:00+00:00', '2026-10-02T20:01:00+00:00', 'WAITING_OPEN'),
    ('2026-10-05T13:31:00+00:00', '2026-10-02T19:59:00+00:00', 'ERROR')])
def test_execution_context_has_no_before_open_or_preclose_source_access(tmp_path, monkeypatch, now, generated, expected):
    from datetime import datetime
    from scripts import daily_recommendation_inputs
    from scripts.research.a2.portfolio import selected_hgb
    from scripts.research.a2.evaluation import three_strategy_extension as extension
    source = tmp_path / 'source.json'; source.write_text(json.dumps({'status': 'READY', 'data_date': '2026-10-02',
        'generated_at': generated}))
    package = tmp_path / 'package.json'; package.write_text(json.dumps({'policy_id': 'HGB_TOP20_RISK_R1', 'source_refs': {'current/report.json': extension.reference(source)},
        'strategies': {'D': {'application': {'signal_date': '2026-10-02'}}}}))
    monkeypatch.setattr(selected_hgb, 'active_policy', lambda paths: ('HGB_TOP20_RISK_R1', package))
    monkeypatch.setattr(daily_recommendation_inputs, 'load_frozen_binding', lambda path: {})
    monkeypatch.setattr(daily_recommendation_inputs, 'latest_completed_session', lambda *args:
        {'target_date': '2026-10-02', 'sessions': ['2026-10-02', '2026-10-05']})
    paths = SimpleNamespace(repo_root=tmp_path)
    if expected == 'ERROR':
        with pytest.raises(ValueError, match='SIGNAL_AVAILABILITY_INVALID'):
            module._execution_chart_context(paths, datetime.fromisoformat(now))
    else:
        assert module._execution_chart_context(paths, datetime.fromisoformat(now))['status'] == expected


@pytest.mark.parametrize('stamp', ['2099-10-05T13:31:00+00:00', '2026-10-05T13:31:00'])
def test_private_execution_input_worker_rejects_future_and_naive_binding_before_api(tmp_path, monkeypatch, stamp):
    from scripts.research.a2.evaluation import three_strategy_extension as extension
    binding = tmp_path / 'A2_today_recommendation/execution_charts/2026-10-05/abc/binding.json'
    binding.parent.mkdir(parents=True)
    binding.write_text(json.dumps({'as_of_utc': stamp}))
    monkeypatch.setattr(module, '_execution_open_acquire', lambda *args: pytest.fail('no API'))
    monkeypatch.setattr(module, '_execution_chart_context', lambda *args: pytest.fail('no context reads'))
    with pytest.raises(ValueError, match='WORKER_ASOF_INVALID'):
        module._execution_chart_worker(SimpleNamespace(daily_root=tmp_path), 'execution-inputs', binding,
                                       extension.reference(binding)['sha256'])


@pytest.mark.parametrize('status,exit_code', [('READY', 0), ('WAITING_SOURCE', 2), ('WAITING_OPEN', 2), ('BLOCKED', 2)])
def test_chart_job_exit_zero_only_for_verified_completion(monkeypatch, status, exit_code):
    monkeypatch.setattr(module, 'run_execution_charts', lambda *args: {'status': status})
    assert module.main(['--execution-charts']) == exit_code



@pytest.mark.parametrize('policy', ['HGB_TOP20_RISK_R1', 'RAW_TOP20_FROZEN_LEGACY'])
def test_open_chart_context_uses_original_historical_price_manifest_owner_after_open(tmp_path, monkeypatch, policy):
    from datetime import datetime
    from scripts import daily_recommendation_inputs
    from scripts.research.a2.portfolio import selected_hgb
    from scripts.research.a2.evaluation import three_strategy_extension as extension, demo_performance
    historical_inputs = tmp_path / 'price_inputs.json'
    historical_inputs.write_text(json.dumps({'lineage': [{'ticker': 'AA', 'cusips': ['123456789']}]}))
    historical = tmp_path / 'historical_manifest.json'
    # Match the original historical producer: price_manifest is the field;
    # price_inputs.json is only the underlying immutable filename.
    historical.write_text(json.dumps({'price_manifest': extension.reference(historical_inputs)}))
    raw = tmp_path / 'raw_manifest.json'; raw.write_text('{}')
    source = tmp_path / 'source.json'; source.write_text(json.dumps({'status': 'READY', 'data_date': '2026-10-02',
        'generated_at': '2026-10-02T20:01:00+00:00', 'universe': {'report_path': str(tmp_path / 'universe_report.json'),
        'universe_members_sha256': 'b' * 64}}))
    package = tmp_path / 'package.json'; package.write_text(json.dumps({'policy_id': policy, 'source_refs': {'current/report.json': extension.reference(source)},
        'strategies': {'D': {'application': {'signal_date': '2026-10-02'}}}}))
    monkeypatch.setattr(selected_hgb, 'active_policy', lambda paths: (policy, package))
    monkeypatch.setattr(daily_recommendation_inputs, 'load_frozen_binding', lambda path: {})
    monkeypatch.setattr(daily_recommendation_inputs, 'latest_completed_session', lambda *args:
        {'target_date': '2026-10-02', 'sessions': ['2026-10-02', '2026-10-05']})
    def canonical(path):
        target = historical if 'A2_historical_top40' in str(path) else raw
        return target, extension.reference(target)
    monkeypatch.setattr(demo_performance, 'canonical_manifest', canonical)
    context = module._execution_chart_context(SimpleNamespace(repo_root=tmp_path, daily_root=tmp_path),
        datetime.fromisoformat('2026-10-05T13:31:00+00:00'))
    assert context['status'] == 'READY' and context['execution_date'] == '2026-10-05'
    assert context['historical_identity_binding'] == extension.reference(historical_inputs)
    assert context['source_report'] == extension.reference(source)
    assert context['historical_manifest'] == extension.reference(historical)


def _native_tail_fixture(tmp_path, monkeypatch):
    from scripts.common import storage_paths
    from scripts.storage import refresh_market_data as market
    from scripts import daily_recommendation_prices as price_api
    monkeypatch.setattr(price_api, 'native_missing_interval_starts', lambda *args: {})
    monkeypatch.setattr(storage_paths, 'assert_safe_output_path', lambda *a, **kw: None)
    paths = SimpleNamespace(repo_root=Path(__file__).parents[1], daily_root=tmp_path / 'daily', cache_root=tmp_path / 'cache')
    run = paths.daily_root / 'runs' / 'synthetic'
    run.mkdir(parents=True)
    leaf = tmp_path / 'old_raw.parquet'; leaf.write_bytes(b'synthetic metadata leaf')
    return paths, run, leaf, market


def test_daily_native_tail_fills_only_missing_dates_and_preserves_original_receipts(tmp_path, monkeypatch):
    import csv
    paths, run, leaf, market = _native_tail_fixture(tmp_path, monkeypatch)
    members = [{'ticker': name, 'security_id': f'{i:09d}', 'moomoo_symbol': 'US.' + name}
               for i, name in enumerate(('MISSING', 'CURRENT', 'NO_NATIVE', 'QFQ_ONLY', 'TOO_OLD'), 1)]
    catalog = [{'ticker': name, 'adjustment': 'raw', 'path': str(leaf), 'max_date': last}
               for name, last in (('MISSING', '2026-10-02'), ('CURRENT', '2026-10-05'), ('TOO_OLD', '2026-01-01'))]
    catalog.append({'ticker': 'QFQ_ONLY', 'adjustment': 'qfq', 'path': str(leaf), 'max_date': '2026-10-02'})
    import pandas as pd
    sessions = list(pd.bdate_range('2026-01-01', periods=180).strftime('%Y-%m-%d')) + ['2026-10-05']
    old = {'moomoo': {'results': [{'status': 'ORIGINAL_RECEIPT'}]}, 'massive': {'status': 'PARTIAL'}}
    before = json.dumps(old, sort_keys=True)
    calls = []
    def collect(args):
        with args.universe_csv.open() as stream: rows = list(csv.DictReader(stream))
        calls.append((args, rows))
        return {'status': 'ACQUIRED', 'history_request_count': 0, 'trade_context_opened': False,
                'results': [{'status': 'FETCHED_VALIDATED_INTERVAL', 'item': rows[0]}]}
    monkeypatch.setattr(market, 'run', collect)
    merged, audit = module.acquire_native_current_tail(paths, run, '2026-10-05', members, old, catalog, sessions, lambda *_: None)
    assert len(calls) == 1 and calls[0][1][0]['ticker'] == 'MISSING'
    args = calls[0][0]
    assert args.start == '2026-10-03' and args.end == '2026-10-05'
    assert args.adjustments == ['raw'] and args.max_retries == 0 and args.acquisition_mode == 'current-kline'
    assert audit['qualified_intervals'] == 1 and audit['status'] == 'ACQUIRED'
    assert json.dumps(old, sort_keys=True) == before
    assert merged['moomoo']['results'][0] == old['moomoo']['results'][0]
    assert audit['history_request_count'] == audit['trade_requests'] == 0


def test_daily_native_tail_alias_uses_exact_registered_source_identity(tmp_path, monkeypatch):
    import csv
    from scripts.research.a2.inference.current_native_prices import REVIEWED_TRANSPORT_ALIASES
    paths, run, leaf, market = _native_tail_fixture(tmp_path, monkeypatch)
    proof = REVIEWED_TRANSPORT_ALIASES['SQ']
    member = {'ticker': 'SQ', 'security_id': proof['security_id'], 'moomoo_symbol': proof['provider_code']}
    catalog = [{'ticker': 'XYZ', 'adjustment': 'raw', 'path': str(leaf), 'max_date': '2026-10-02'}]
    observed = []
    def collect(args):
        with args.universe_csv.open() as stream: observed.extend(csv.DictReader(stream))
        return {'status': 'ACQUIRED', 'results': [{'status': 'FETCHED_VALIDATED_INTERVAL'}]}
    monkeypatch.setattr(market, 'run', collect)
    _, audit = module.acquire_native_current_tail(paths, run, '2026-10-05', [member], {}, catalog, ['2026-10-05'], lambda *_: None)
    assert observed == [{'ticker': 'XYZ', 'security_id': proof['security_id'], 'moomoo_symbol': 'US.XYZ'}]
    assert audit['scope'][0]['logical_ticker'] == 'SQ'
    with pytest.raises(ValueError, match='NATIVE_EXPLICIT_TRANSPORT_ALIAS_INVALID'):
        module.acquire_native_current_tail(paths, run, '2026-10-05', [{**member, 'security_id': '999999999'}], {}, catalog, ['2026-10-05'], lambda *_: None)


def test_daily_native_tail_noop_uses_no_sdk_and_permission_stops_later_groups(tmp_path, monkeypatch):
    paths, run, leaf, market = _native_tail_fixture(tmp_path, monkeypatch)
    member = {'ticker': 'A', 'security_id': '111111111', 'moomoo_symbol': 'US.A'}
    monkeypatch.setattr(market, 'run', lambda *_: pytest.fail('NOOP must not call SDK'))
    original = {'moomoo': {'results': []}}
    merged, audit = module.acquire_native_current_tail(paths, run, '2026-10-05', [member], original,
        [{'ticker': 'A', 'adjustment': 'raw', 'path': str(leaf), 'max_date': '2026-10-05'}], ['2026-10-05'], lambda *_: None)
    assert merged == original and audit['status'] == 'NOOP' and audit['result_count'] == 0
    second = {'ticker': 'B', 'security_id': '222222222', 'moomoo_symbol': 'US.B'}
    calls = []
    def refusal(args):
        calls.append(args)
        return {'status': 'PARTIAL', 'results': [{'status': 'FAILED_CURRENT_KLINE', 'error': 'SUBSCRIBE_REJECTED:permission denied'}]}
    monkeypatch.setattr(market, 'run', refusal)
    _, audit = module.acquire_native_current_tail(paths, run, '2026-10-05', [member, second], original,
        [{'ticker': name, 'adjustment': 'raw', 'path': str(leaf), 'max_date': day}
         for name, day in (('A', '2026-10-01'), ('B', '2026-10-02'))], ['2026-10-02', '2026-10-05'], lambda *_: None)
    assert len(calls) == 1 and audit['blocked_remaining_groups'] == 1 and audit['status'] == 'PARTIAL'


@pytest.mark.parametrize('bad_scope', [{'history_request_count': 1}, {'trade_context_opened': True}])
def test_daily_native_tail_rejects_unexpected_api_scope_without_merging_receipts(tmp_path, monkeypatch, bad_scope):
    paths, run, leaf, market = _native_tail_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(market, 'run', lambda *_: {'status': 'ACQUIRED', 'results': [{'status': 'FETCHED_VALIDATED_INTERVAL'}], **bad_scope})
    original = {'moomoo': {'results': [{'status': 'ORIGINAL'}]}}
    merged, audit = module.acquire_native_current_tail(paths, run, '2026-10-05',
        [{'ticker': 'A', 'security_id': '111111111', 'moomoo_symbol': 'US.A'}], original,
        [{'ticker': 'A', 'adjustment': 'raw', 'path': str(leaf), 'max_date': '2026-10-02'}], ['2026-10-05'], lambda *_: None)
    assert merged == original and audit['qualified_intervals'] == 0 and audit['status'] == 'PARTIAL'


def test_daily_native_tail_bounds_owned_subscriptions_across_large_scope(tmp_path, monkeypatch):
    import csv
    paths, run, leaf, market = _native_tail_fixture(tmp_path, monkeypatch)
    members = [{'ticker': f'T{i:03}', 'security_id': f'{i:09d}', 'moomoo_symbol': f'US.T{i:03}'} for i in range(130)]
    catalog = [{'ticker': row['ticker'], 'adjustment': 'raw', 'path': str(leaf), 'max_date': '2026-10-02'} for row in members]
    batch_sizes = []
    def collect(args):
        with args.universe_csv.open() as stream: rows = list(csv.DictReader(stream))
        batch_sizes.append(len(rows))
        return {'status': 'ACQUIRED', 'results': [{'status': 'FETCHED_VALIDATED_INTERVAL', 'item': row} for row in rows],
                'history_request_count': 0, 'trade_context_opened': False, 'owned_subscriptions_released': True}
    monkeypatch.setattr(market, 'run', collect)
    _, audit = module.acquire_native_current_tail(paths, run, '2026-10-05', members, {}, catalog, ['2026-10-05'], lambda *_: None)
    assert batch_sizes == [64, 64, 2] and audit['qualified_intervals'] == 130 and audit['status'] == 'ACQUIRED'
    assert len({group['receipt'] for group in audit['groups']}) == 3


@pytest.mark.parametrize('provider_summary', [
    {'status': 'BLOCKED', 'error': 'SUBSCRIPTION_QUERY_REJECTED:permission denied',
     'results': [{'status': 'BLOCKED_CONNECTION_OR_SETUP'}]},
    {'status': 'BLOCKED', 'results': [{'status': 'BLOCKED_CONNECTION_OR_SETUP'}]},
    {'status': 'PARTIAL', 'error': 'query quota exceeded', 'results': [{'status': 'FAILED_CURRENT_KLINE'}]},
    {'status': 'PARTIAL', 'results': [{'status': 'FAILED_CURRENT_KLINE', 'error': '\u6743\u9650\u88ab\u62d2\u7edd'}]},
])
def test_daily_native_tail_provider_setup_or_top_level_refusal_stops_all_later_batches(tmp_path, monkeypatch, provider_summary):
    paths, run, leaf, market = _native_tail_fixture(tmp_path, monkeypatch)
    members = [{'ticker': name, 'security_id': f'{i:09d}', 'moomoo_symbol': 'US.' + name}
               for i, name in enumerate(('A', 'B'), 1)]
    catalog = [{'ticker': name, 'adjustment': 'raw', 'path': str(leaf), 'max_date': day}
               for name, day in (('A', '2026-10-01'), ('B', '2026-10-02'))]
    calls = []
    def collect(args):
        calls.append(args)
        return provider_summary
    monkeypatch.setattr(market, 'run', collect)
    _, audit = module.acquire_native_current_tail(paths, run, '2026-10-05', members, {}, catalog,
        ['2026-10-02', '2026-10-05'], lambda *_: None)
    assert len(calls) == 1 and audit['blocked_remaining_groups'] == 1
    assert audit['qualified_intervals'] == 0 and audit['status'] == 'PARTIAL'


@pytest.mark.parametrize('universe', [
    {'current': False, 'members': [], 'reason': '13F_REFRESH_FAILED:synthetic acceptance conflict'},
    {'current': True, 'members': [], 'reason': ''},
])
def test_daily_failed_or_empty_current_universe_stops_before_all_acquisition(tmp_path, monkeypatch, universe):
    from scripts import daily_recommendation_inputs as inputs, daily_recommendation_universe as identity
    from scripts.storage import storage_r2a
    paths = SimpleNamespace(repo_root=tmp_path, daily_root=tmp_path / 'daily')
    binding = {'components': {'ALPHA': {'artifacts': [{'artifact_id': 'model', 'sha256': 'a' * 64}]}}}
    monkeypatch.setattr(inputs, 'load_frozen_binding', lambda *_: binding)
    monkeypatch.setattr(inputs, 'latest_completed_session', lambda *_: {'target_date': '2026-10-05'})
    monkeypatch.setattr(inputs, 'load_bound_universe', lambda *_: {'current': True, 'members': []})
    monkeypatch.setattr(identity, 'refresh_universe', lambda *a, **kw: universe)
    monkeypatch.setattr(inputs, 'load_priority_history', lambda *_: pytest.fail('no history/acquisition after universe failure'))
    monkeypatch.setattr(storage_r2a, 'DataStore', lambda *_: pytest.fail('no data store after universe failure'))
    monkeypatch.setattr(module, 'live_quota', lambda *_: pytest.fail('no quote SDK'))
    monkeypatch.setattr(module, 'predict_current', lambda *_: pytest.fail('no inference'))
    result = module.run_update(paths, execute=True, emit_progress=lambda *_: None)
    assert result['status'] == 'BLOCKED' and result['rows'] == []
    assert result['universe'] == {k: v for k, v in universe.items() if k != 'members'}
    assert 'acquisitions' not in result and not result['broker_action_allowed']
    assert Path(result['report_path']).is_file()


def _native_routing_publication(rows, target='2026-10-05', **overrides):
    import hashlib
    success = {'FETCHED_VALIDATED_INTERVAL', 'REUSED_VERIFIED_INTERVAL'}
    published = [row for row in rows if row.get('status') in success]
    count = len(published)
    request_hash = hashlib.sha256(json.dumps({'target_date': target, 'receipts': [
        {key: row.get(key) for key in ('item', 'path', 'sha256')} for row in published
    ]}, sort_keys=True).encode()).hexdigest()
    return {'status': 'PUBLISHED', 'target_date': target, 'all_old_dates_preserved': True,
            'published_intervals': count, 'requested_keys': count, 'raw_reached_target': count,
            'request_sha256': request_hash, **overrides}


@pytest.mark.parametrize('status,expected_filtered', [('PUBLISHED', True), ('PARTIAL', False), ('BLOCKED', False)])
def test_native_publication_routes_prediction_to_full_catalog_without_changing_evidence(status, expected_filtered):
    def raw(ticker, path):
        return {'status': 'FETCHED_VALIDATED_INTERVAL', 'item': {'ticker': ticker, 'adjustment': 'raw'}, 'path': path}
    original = {'moomoo': {'results': [raw('A', 'full121.csv'), raw('SQ', 'logical.csv'), raw('XYZ', 'transport121.csv'),
        {'status': 'FAILED_CURRENT_KLINE', 'item': {'ticker': 'B', 'adjustment': 'raw'}},
        {'status': 'FETCHED_VALIDATED_INTERVAL', 'item': {'ticker': 'A', 'adjustment': 'qfq'}},
        raw('A', 'tail1.csv'), raw('XYZ', 'transport_tail1.csv')]}, 'alternate': {'receipt': 'original.json'}}
    before = json.dumps(original, sort_keys=True)
    publication = _native_routing_publication(original['moomoo']['results'][-2:], status=status)
    result = module.prediction_after_native_publication(original, publication, 2, '2026-10-05')
    assert json.dumps(original, sort_keys=True) == before
    if expected_filtered:
        assert [row.get('path') for row in result['moomoo']['results']] == ['logical.csv', None, None]
        assert result['alternate'] is original['alternate']
    else:
        assert result is original


@pytest.mark.parametrize('invalid', [{'all_old_dates_preserved': False}, {'target_date': '2026-10-02'},
                                    {'published_intervals': 0}, {'requested_keys': 0}])
def test_native_prediction_catalog_routing_requires_complete_original_publication(invalid):
    acquisitions = {'moomoo': {'results': [{'status': 'FETCHED_VALIDATED_INTERVAL',
        'item': {'ticker': 'A', 'adjustment': 'raw'}}]}}
    publication = _native_routing_publication(acquisitions['moomoo']['results'], **invalid)
    assert module.prediction_after_native_publication(acquisitions, publication, 1, '2026-10-05') is acquisitions


def test_native_partial_acquisition_routes_all369_published_tails_and_preserves_failed_wbd():
    def raw(ticker, path):
        return {'status': 'FETCHED_VALIDATED_INTERVAL', 'path': path, 'sha256': 'a' * 64,
                'item': {'ticker': ticker, 'adjustment': 'raw', 'security_id': ticker + '_CID',
                         'moomoo_symbol': 'US.' + ticker, 'planned_end_date': '2026-10-05'}}
    native = [raw('T' + str(i), 'tail_' + str(i)) for i in range(369)]
    failed = {'status': 'FAILED_CURRENT_KLINE', 'error': 'EMPTY_RESPONSE',
              'item': {'ticker': 'WBD', 'adjustment': 'raw', 'security_id': '934423104'}}
    native.insert(175, failed)
    full = raw('T0', 'full121.csv')
    other = raw('SQ', 'logical_alias.csv')
    original = {'moomoo': {'results': [full, other] + native}, 'alternate': {'status': 'UNAVAILABLE'}}
    before = json.dumps(original, sort_keys=True)
    result = module.prediction_after_native_publication(original, _native_routing_publication(native), 370, '2026-10-05')
    assert result['moomoo']['results'] == [other, failed]
    assert result['moomoo']['results'][1] is failed
    assert result['alternate'] is original['alternate']
    assert json.dumps(original, sort_keys=True) == before
    # The original qualifier now takes its canonical-catalog branch for the
    # published transport tickers. This adds no history or eligibility rule.
    assert not any(row.get('status') == 'FETCHED_VALIDATED_INTERVAL'
                   and row['item']['ticker'].startswith('T') for row in result['moomoo']['results'])


@pytest.mark.parametrize('field,value', [('security_id', 'DIFFERENT_CID'),
    ('moomoo_symbol', 'US.NEW'), ('ticker', 'NEW'), ('planned_end_date', '2026-10-06')])
def test_native_partial_catalog_routing_rejects_receipt_identity_or_date_drift(field, value):
    row = {'status': 'FETCHED_VALIDATED_INTERVAL', 'path': 'tail.csv', 'sha256': 'a' * 64,
           'item': {'ticker': 'A', 'adjustment': 'raw', 'security_id': '111111111',
                    'moomoo_symbol': 'US.A', 'planned_end_date': '2026-10-05'}}
    failed = {'status': 'FAILED_CURRENT_KLINE', 'item': {'ticker': 'B', 'adjustment': 'raw'}}
    acquisitions = {'moomoo': {'results': [row, failed]}}
    publication = _native_routing_publication(acquisitions['moomoo']['results'])
    row['item'][field] = value
    assert module.prediction_after_native_publication(acquisitions, publication, 2, '2026-10-05') is acquisitions


@pytest.mark.parametrize('change', ['path', 'sha256', 'request_sha256', 'raw_reached_target', 'duplicate', 'qfq', 'all_failed'])
def test_native_partial_catalog_routing_retains_original_on_unbound_or_incomplete_publication(change):
    row = {'status': 'REUSED_VERIFIED_INTERVAL', 'path': 'tail.csv', 'sha256': 'a' * 64,
           'item': {'ticker': 'A', 'adjustment': 'raw'}}
    failed = {'status': 'FAILED_CURRENT_KLINE', 'item': {'ticker': 'B', 'adjustment': 'raw'}}
    acquisitions = {'moomoo': {'results': [row, failed]}}
    publication = _native_routing_publication(acquisitions['moomoo']['results'])
    if change in {'path', 'sha256'}:
        row[change] = 'tampered'
    elif change in {'request_sha256', 'raw_reached_target'}:
        publication[change] = None
    elif change == 'duplicate':
        acquisitions['moomoo']['results'].append(dict(row))
        publication = _native_routing_publication(acquisitions['moomoo']['results'])
    elif change == 'qfq':
        row['item']['adjustment'] = 'qfq'
        publication = _native_routing_publication(acquisitions['moomoo']['results'])
    else:
        row['status'] = 'FAILED_CURRENT_KLINE'
        publication = _native_routing_publication(acquisitions['moomoo']['results'])
    assert module.prediction_after_native_publication(acquisitions, publication,
        len(acquisitions['moomoo']['results']), '2026-10-05') is acquisitions


@pytest.mark.parametrize('last,internal,expected_start', [
    ('2026-10-05', {'A': '2026-08-17'}, '2026-08-17'),
    ('2026-10-02', {'A': '2026-08-17'}, '2026-08-17'),
    ('2026-10-02', {}, '2026-10-03'),
])
def test_daily_native_tail_combines_internal_gaps_with_missing_final_tail(tmp_path, monkeypatch, last, internal, expected_start):
    from scripts import daily_recommendation_prices as price_api
    paths, run, leaf, market = _native_tail_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(price_api, 'native_missing_interval_starts', lambda *args: internal)
    calls = []
    def collect(args):
        calls.append(args)
        return {'status': 'ACQUIRED', 'results': [{'status': 'FETCHED_VALIDATED_INTERVAL'}]}
    monkeypatch.setattr(market, 'run', collect)
    _, audit = module.acquire_native_current_tail(paths, run, '2026-10-05',
        [{'ticker': 'A', 'security_id': '111111111', 'moomoo_symbol': 'US.A'}], {},
        [{'ticker': 'A', 'adjustment': 'raw', 'path': str(leaf), 'max_date': last}],
        ['2026-08-17', '2026-08-18', '2026-10-05'], lambda *_: None)
    assert len(calls) == 1 and calls[0].start == expected_start and calls[0].end == '2026-10-05'
    assert calls[0].acquisition_mode == 'current-kline' and calls[0].max_retries == 0
    assert audit['scope'][0]['native_latest_date'] == last


def _benchmark_native_fixture(tmp_path, monkeypatch):
    from scripts.storage import refresh_demo_benchmarks as owner, refresh_market_data as market
    from scripts.research.a2.inference import current_native_prices as native
    from scripts.common import storage_paths
    identities = {name: {'security_id': sid, 'provider_code': 'US.' + name, 'currency': 'USD'}
                  for name, sid in [('QQQ', '46090E103'), ('SPY', '78462F103')]}
    monkeypatch.setattr(owner, 'ETF_IDENTITIES', identities, raising=False)
    monkeypatch.setattr(storage_paths, 'assert_safe_output_path', lambda *a, **kw: None)
    paths = SimpleNamespace(repo_root=Path(__file__).parents[1], daily_root=tmp_path / 'daily', cache_root=tmp_path / 'cache')
    run = paths.daily_root / 'runs' / 'benchmark_test'; run.mkdir(parents=True)
    dates = ['2026-09-25', '2026-09-28', '2026-09-29', '2026-09-30', '2026-10-01', '2026-10-02', '2026-10-05']
    scope = {'status': 'NEEDS_NATIVE', 'target_date': dates[-1], 'bridge_start': dates[0],
             'required_dates': dates, 'native_tickers': ['QQQ', 'SPY']}
    return paths, run, scope, identities, owner, market, native


@pytest.mark.parametrize('status', ['NOOP', 'MASSIVE_READY', 'BLOCKED'])
def test_benchmark_auxiliary_no_scope_never_opens_sdk_or_catalog(tmp_path, monkeypatch, status):
    paths, run, scope, identities, owner, market, native = _benchmark_native_fixture(tmp_path, monkeypatch)
    def forbidden(*args, **kwargs): raise AssertionError('unexpected data or SDK access')
    monkeypatch.setattr(market, 'run', forbidden)
    monkeypatch.setattr(native, '_native_raw', forbidden)
    inputs, audit = module.acquire_benchmark_native_inputs(paths, run, '2026-10-05', {**scope, 'status': status}, object())
    assert inputs == {} and audit['status'] == 'NOOP'
    assert audit['history_request_count'] == audit['trade_requests'] == audit['new_current_kline_requests'] == 0


def test_benchmark_auxiliary_verifies_actual_catalog_dates_and_reuses_original_reference(tmp_path, monkeypatch):
    import pandas as pd
    paths, run, scope, identities, owner, market, native = _benchmark_native_fixture(tmp_path, monkeypatch)
    proof = {'path': str(tmp_path / 'immutable.parquet'), 'sha256': 'a' * 64}
    calls = []
    def actual(store, symbol, code, target):
        calls.append((symbol, code, target)); return pd.DataFrame({'trade_date': pd.to_datetime(scope['required_dates'])}), proof
    monkeypatch.setattr(native, '_native_raw', actual)
    monkeypatch.setattr(market, 'run', lambda *_: pytest.fail('already complete benchmark requested SDK'))
    store = SimpleNamespace(metadata=lambda *a: {'max_date': '2026-10-05'})
    inputs, audit = module.acquire_benchmark_native_inputs(paths, run, '2026-10-05', scope, store)
    assert audit['status'] == 'READY' and len(calls) == 2
    for symbol in identities:
        assert inputs[symbol] == {**identities[symbol], 'kind': 'CATALOG_RAW', 'reference': proof}


def test_benchmark_auxiliary_missing_native_uses_one_bounded_raw_rth_batch_and_keeps_receipt(tmp_path, monkeypatch):
    import csv
    paths, run, scope, identities, owner, market, native = _benchmark_native_fixture(tmp_path, monkeypatch)
    calls = []
    def absent(*args): raise KeyError('no native catalog')
    def collect(args):
        with args.universe_csv.open() as stream: rows = list(csv.DictReader(stream))
        calls.append((args, rows)); results = []
        for row in rows:
            item = {**row, 'planned_start_date': args.start, 'planned_end_date': args.end,
                    'adjustment': 'raw', 'acquisition_method': 'GET_CUR_KLINE', 'session': 'RTH'}
            path = args.work_root / 'intervals' / (row['ticker'] + '.csv'); path.parent.mkdir(parents=True, exist_ok=True)
            checkpoint = path.with_suffix('.json'); checkpoint.write_text(json.dumps({'item': item}))
            results.append({'item': item, 'status': 'REUSED_VERIFIED_INTERVAL', 'path': str(path), 'latest_date': args.end})
        return {'status': 'ALL_INTERVALS_REUSED', 'history_request_count': 0, 'trade_context_opened': False, 'results': results}
    monkeypatch.setattr(market, 'run', collect)
    store = SimpleNamespace(metadata=absent)
    inputs, audit = module.acquire_benchmark_native_inputs(paths, run, '2026-10-05', scope, store)
    args, rows = calls[0]
    assert len(calls) == 1 and rows == [{'ticker': s, 'security_id': identities[s]['security_id'], 'moomoo_symbol': 'US.' + s} for s in ('QQQ', 'SPY')]
    assert args.acquisition_mode == 'current-kline' and args.adjustments == ['raw'] and args.max_retries == 0
    assert args.start == scope['bridge_start'] and args.end == '2026-10-05'
    assert audit['status'] == 'READY' and audit['new_current_kline_requests'] == 0
    assert {item['kind'] for item in inputs.values()} == {'CURRENT_KLINE'}
    assert Path(audit['acquisition']['path']).is_file()


@pytest.mark.parametrize('mutation', ['ticker', 'duplicate', 'future', 'too_long'])
def test_benchmark_auxiliary_rejects_unbound_or_unbounded_scope_before_api(tmp_path, monkeypatch, mutation):
    paths, run, scope, identities, owner, market, native = _benchmark_native_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(market, 'run', lambda *_: pytest.fail('invalid scope reached SDK'))
    if mutation == 'ticker': scope['native_tickers'] = ['QQQ', 'AMD']
    if mutation == 'duplicate': scope['native_tickers'] = ['QQQ', 'QQQ']
    if mutation == 'future': scope['required_dates'].append('2026-10-06')
    if mutation == 'too_long': scope['required_dates'] = [f'2025-{i:03}' for i in range(131)] + ['2026-10-05']; scope['bridge_start'] = scope['required_dates'][0]
    with pytest.raises(ValueError, match='BENCHMARK_NATIVE_ACQUISITION_SCOPE_INVALID'):
        module.acquire_benchmark_native_inputs(paths, run, '2026-10-05', scope, object())


def test_benchmark_native_provider_denial_is_reported_without_affecting_stock_inputs(tmp_path, monkeypatch):
    paths, run, scope, identities, owner, market, native = _benchmark_native_fixture(tmp_path, monkeypatch)
    def absent(*args): raise KeyError('no native catalog')
    monkeypatch.setattr(market, 'run', lambda *_: {'status': 'FAILED', 'history_request_count': 0,
        'trade_context_opened': False, 'current_kline_calls': 1, 'results': [{'item': {'ticker': 'QQQ'}, 'status': 'FAILED_CURRENT_KLINE'}]})
    inputs, audit = module.acquire_benchmark_native_inputs(paths, run, '2026-10-05', scope, SimpleNamespace(metadata=absent))
    assert not inputs and audit['status'] == 'PARTIAL'
    assert audit['rejections'] == [{'ticker': 'QQQ', 'reason': 'FAILED_CURRENT_KLINE'}]
    assert audit['new_current_kline_requests'] == 1 and audit['qualified_new_intervals'] == 0


def test_daily_benchmark_owner_retains_authoritative_failure_and_audit(tmp_path, monkeypatch):
    paths, run, scope, identities, owner, market, native = _benchmark_native_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(owner, 'benchmark_native_scope', lambda *a: scope, raising=False)
    def invalid(*args): raise ValueError('SYNTHETIC_NATIVE_HASH_CHANGED')
    monkeypatch.setattr(module, 'acquire_benchmark_native_inputs', invalid)
    calls = []
    def refresh(*args, **kwargs):
        calls.append(kwargs); return {'status': 'BLOCKED', 'reason': 'NATIVE_SOURCE_REQUIRED', 'requested_end_date': '2026-10-05'}
    monkeypatch.setattr(owner, 'refresh_demo_benchmarks', refresh)
    result = module.refresh_daily_benchmarks(paths, run, '2026-10-05', {}, object(), lambda *_: None)
    assert result['status'] == 'BLOCKED' and calls == [{}]
    audit = json.loads(Path(result['native_acquisition']['path']).read_text())
    assert audit['reason'] == 'SYNTHETIC_NATIVE_HASH_CHANGED' and audit['status'] == 'BLOCKED'


def test_benchmark_native_prior_failed_day_can_reuse_catalog_when_latest_day_is_primary_ready(tmp_path, monkeypatch):
    import pandas as pd
    paths, run, scope, identities, owner, market, native = _benchmark_native_fixture(tmp_path, monkeypatch)
    # Latest target is primary SUCCESS; only the earlier failed day needs native.
    target = '2026-10-06'
    scope['target_date'] = target
    monkeypatch.setattr(native, '_native_raw', lambda *a: (pd.DataFrame({'trade_date': pd.to_datetime(scope['required_dates'])}),
        {'path': str(tmp_path / 'old_native.parquet'), 'sha256': 'a' * 64}))
    monkeypatch.setattr(market, 'run', lambda *_: pytest.fail('unneeded target ETF SDK call'))
    inputs, audit = module.acquire_benchmark_native_inputs(paths, run, target, scope,
        SimpleNamespace(metadata=lambda *a: {'max_date': '2026-10-05'}))
    assert audit['status'] == 'READY' and set(inputs) == {'QQQ', 'SPY'}


def test_benchmark_auxiliary_requires_both_original_etfs_before_any_api(tmp_path, monkeypatch):
    paths, run, scope, identities, owner, market, native = _benchmark_native_fixture(tmp_path, monkeypatch)
    scope['native_tickers'] = ['QQQ']
    monkeypatch.setattr(market, 'run', lambda *_: pytest.fail('incomplete ETF scope reached API'))
    with pytest.raises(ValueError, match='BENCHMARK_NATIVE_ACQUISITION_SCOPE_INVALID'):
        module.acquire_benchmark_native_inputs(paths, run, '2026-10-05', scope, object())



@pytest.mark.parametrize('failure', ['mkdir', 'open'])
def test_provider_log_io_failure_is_a_returned_failure_before_child_start(tmp_path, monkeypatch, failure):
    log = tmp_path / 'owned_log' / 'worker.log'
    original_mkdir, original_open = Path.mkdir, Path.open
    def mkdir(path, *args, **kwargs):
        if path == log.parent and failure == 'mkdir':
            raise PermissionError('SYNTHETIC_LOG_MKDIR_DENIED')
        return original_mkdir(path, *args, **kwargs)
    def opening(path, *args, **kwargs):
        if path == log and failure == 'open':
            raise PermissionError('SYNTHETIC_LOG_OPEN_DENIED')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'mkdir', mkdir)
    monkeypatch.setattr(Path, 'open', opening)
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **kw: pytest.fail('log failure must not start child'))
    result = module.run_provider(SimpleNamespace(python_exe=Path('unused'), repo_root=tmp_path),
                                 'scripts.daily_recommendation', [], log)
    assert result['exit_code'] == -1 and result['log_path'] == str(log)
    assert 'SYNTHETIC_LOG_' in result['error']


def test_isolated_runner_exception_keeps_other_stage_and_immutable_source(tmp_path, monkeypatch):
    from hashlib import sha256
    run = tmp_path / 'A2_today_recommendation/runs/synthetic'; run.mkdir(parents=True)
    calls, observed = [], []
    def runner(paths, name, argv, log):
        calls.append(argv[1])
        source = Path(argv[3]); observed.append(sha256(source.read_bytes()).hexdigest())
        assert observed[-1] == argv[5]
        if argv[1] == 'raw':
            raise PermissionError('SYNTHETIC_RAW_RUNNER_LOG_FAILURE')
        log.write_text(json.dumps({'event': 'performance_result', 'result': {'status': 'READY', 'kind': 'selected'}}) + '\n')
        return {'exit_code': 0, 'log_path': str(log)}
    monkeypatch.setattr(module, 'run_provider', runner)
    raw, selected = module.update_performance_isolated(SimpleNamespace(daily_root=tmp_path),
        {'status': 'READY', 'data_date': '2025-01-03'}, run, lambda *_: None)
    assert calls == ['raw', 'selected'] and observed[0] == observed[1]
    assert sha256((run / 'recommendation_source.json').read_bytes()).hexdigest() == observed[0]
    assert raw['status'] == 'BLOCKED' and 'SYNTHETIC_RAW_RUNNER_LOG_FAILURE' in raw['error']
    assert selected['status'] == 'READY'


def _opening_response_fixture(tmp_path, monkeypatch):
    from scripts.common import storage_paths
    from scripts.research.a2.evaluation import hgb_policy_alignment, demo_performance, three_strategy_extension as extension
    daily = tmp_path / 'daily'; daily.mkdir()
    package = daily / 'canonical_package.json'; package.write_text('{}')
    source = daily / 'immutable_source.json'; source.write_text('{}')
    previous = daily / 'previous_raw_manifest.json'; previous.write_text('{}')
    context = {'status': 'READY', 'signal_date': '2026-10-02', 'execution_date': '2026-10-05',
        'as_of_utc': '2026-10-05T13:31:00+00:00', 'policy_id': 'HGB_TOP20_RISK_R1', 'package': extension.reference(package),
        'source_report': extension.reference(source), 'raw_manifest': extension.reference(previous)}
    paths = SimpleNamespace(daily_root=daily)
    checks = []
    def current(*args):
        checks.append(True); return len(checks) > 1
    monkeypatch.setattr(module, '_execution_chart_context', lambda *_: context)
    monkeypatch.setattr(module, '_execution_charts_current', current)
    monkeypatch.setattr(module, '_execution_chart_reference_status', lambda *_: {'status': 'SYNTHETIC'})
    monkeypatch.setattr(storage_paths, 'assert_safe_output_path', lambda *a, **kw: None)
    monkeypatch.setattr(hgb_policy_alignment, 'frozen_contract', lambda *_: ({}, {}))
    monkeypatch.setattr(demo_performance, 'canonical_manifest', lambda *_: (previous, extension.reference(previous)))
    return paths, context


@pytest.mark.parametrize('defect', ['oversized', 'array_event', 'array_result', 'duplicate', 'runner_raises'])
def test_opening_worker_invalid_response_is_terminal_and_fail_closed(tmp_path, monkeypatch, defect):
    from hashlib import sha256
    paths, context = _opening_response_fixture(tmp_path, monkeypatch)
    before = {value['path']: sha256(Path(value['path']).read_bytes()).hexdigest()
              for value in (context['package'], context['source_report'], context['raw_manifest'])}
    calls = []
    def runner(actual, name, argv, log):
        kind = argv[1]; calls.append(kind)
        summary = {'status': 'READY', 'performance_end_date': context['execution_date']}
        if kind == 'execution-inputs':
            if defect == 'runner_raises': raise PermissionError('SYNTHETIC_OPENING_LOG_DENIED')
            if defect == 'oversized': summary['oversized_noise'] = 'x' * (1024 * 1024 + 1)
            event = {'event': 'performance_result', 'result': summary}
            content = json.dumps(event)
            if defect == 'array_event': content = json.dumps([])
            if defect == 'array_result': content = json.dumps({'event': 'performance_result', 'result': [{'status': 'READY'}]})
            if defect == 'duplicate': content += '\n' + json.dumps(event)
        else: content = json.dumps({'event': 'performance_result', 'result': summary})
        log.write_text(content + '\n', encoding='utf-8')
        return {'exit_code': 0, 'log_path': str(log)}
    monkeypatch.setattr(module, 'run_provider', runner)
    result = module.run_execution_charts(paths, progress=lambda *_: None)
    assert result['status'] == 'BLOCKED' and result['broker_action_allowed'] is False
    assert calls == ['execution-inputs']  # Invalid opening input cannot reach replay.
    state = next(paths.daily_root.glob('A2_today_recommendation/execution_charts/*/*/state.json'))
    assert json.loads(state.read_text()) == result and result['status'] != 'RUNNING'
    assert all(sha256(Path(path).read_bytes()).hexdigest() == digest for path, digest in before.items())


def _ready_daily_without_external_work(tmp_path, monkeypatch):
    from scripts import daily_recommendation_inputs as inputs, daily_recommendation_universe as identity, daily_recommendation_prices as prices
    from scripts.storage import storage_r2a, manage_data, top20_quota_plan
    target = '2026-10-05'
    members = [{'ticker': f'T{i:02}', 'security_id': f'{i:09}', 'moomoo_symbol': f'US.T{i:02}'} for i in range(20)]
    universe = {'current': True, 'members': members, 'mapping_gap_count': 0}
    paths = SimpleNamespace(repo_root=tmp_path, daily_root=tmp_path / 'daily', cache_root=tmp_path / 'cache',
                            results_root=tmp_path / 'results', backtest_root=tmp_path / 'backtests')
    binding = {'components': {'ALPHA': {'artifacts': [{'artifact_id': 'model', 'sha256': 'a' * 64}]}}}
    monkeypatch.setattr(inputs, 'load_frozen_binding', lambda *_: binding)
    monkeypatch.setattr(inputs, 'latest_completed_session', lambda *_: {'target_date': target, 'sessions': [target]})
    monkeypatch.setattr(inputs, 'load_bound_universe', lambda *_: universe)
    monkeypatch.setattr(inputs, 'load_priority_history', lambda *_: {'records': [], 'bootstrap_records': []})
    monkeypatch.setattr(identity, 'refresh_universe', lambda *a, **kw: universe)
    monkeypatch.setattr(storage_r2a, 'DataStore', lambda: object())
    monkeypatch.setattr(manage_data, 'status', lambda *_: {})
    monkeypatch.setattr(manage_data, 'acquisition_tickers', lambda *_: [])
    monkeypatch.setattr(manage_data, 'read_catalog', lambda *_: ([], []))
    monkeypatch.setattr(top20_quota_plan, 'build_top20_quota_plan', lambda *a, **kw:
        {'counts': {}, 'history_date_start': target, 'history_date_end': target,
         'bootstrap_used': False, 'max_moomoo_symbols': 300})
    monkeypatch.setattr(module, 'live_quota', lambda *_: (0, 0, []))
    monkeypatch.setattr(module, 'acquire_pool_prices', lambda *a, **kw: {'moomoo': {'results': []}})
    monkeypatch.setattr(module, 'topup_moomoo_once', lambda paths, root, run, plan, acquisitions, *a: acquisitions)
    monkeypatch.setattr(prices, 'publish_acquired_prices', lambda *a, **kw: {'status': 'NOOP'})
    monkeypatch.setattr(module, 'acquire_native_current_tail', lambda paths, run, target, members, acquisitions, *a:
        (acquisitions, {'result_count': 0, 'qualified_intervals': 0}))
    monkeypatch.setattr(module, 'refresh_daily_benchmarks', lambda *a, **kw: {'status': 'BLOCKED', 'error': 'SYNTHETIC_BENCHMARK_UNAVAILABLE'})
    monkeypatch.setattr(module, 'acquire_other_data', lambda *a, **kw: {})
    monkeypatch.setattr(prices, 'refresh_rehab', lambda *a, **kw: {'status': 'SYNTHETIC'})
    monkeypatch.setattr(module, 'predict_current', lambda *a, **kw:
        ([{'ticker': row['ticker'], 'rank': i + 1, 'score': .001} for i, row in enumerate(members)], [], []))
    monkeypatch.setattr(module, 'resume_published_update', lambda *a, **kw: None, raising=False)
    return paths


@pytest.mark.parametrize('failure', [RuntimeError, PermissionError])
def test_unexpected_chart_stage_error_still_persists_ready_recommendation_and_failure(tmp_path, monkeypatch, failure):
    paths = _ready_daily_without_external_work(tmp_path, monkeypatch)
    def broken(*a, **kw): raise failure('SYNTHETIC_STAGE_ORCHESTRATION_FAILURE')
    monkeypatch.setattr(module, 'update_performance_isolated', broken)
    result = module.run_update(paths, execute=True, emit_progress=lambda *_: None)
    assert result['status'] == 'READY' and len(result['rows']) == 20
    assert result['broker_action_allowed'] is False
    assert json.loads(Path(result['report_path']).read_text(encoding='utf-8')) == result
    assert json.loads((paths.daily_root / 'A2_today_recommendation/latest.json').read_text(encoding='utf-8')) == result
    assert result['performance_update']['status'] == 'BLOCKED'
    assert result['selected_strategies_update']['status'] == 'BLOCKED'
    assert 'SYNTHETIC_STAGE_ORCHESTRATION_FAILURE' in json.dumps(result)
    assert result['completion']['status'] == 'PARTIAL'



def _accepted_daily_fixture(tmp_path, monkeypatch):
    """Complete tiny synthetic receipts, verified by the real SHA checker."""
    from datetime import datetime, timezone
    from hashlib import sha256
    from scripts.research.a2.evaluation import hgb_policy_alignment, three_strategy_extension as extension
    paths = SimpleNamespace(repo_root=tmp_path / 'repo', daily_root=tmp_path / 'daily',
        cache_root=tmp_path / 'cache', results_root=tmp_path / 'results', backtest_root=tmp_path / 'backtests')
    run = paths.daily_root / 'A2_today_recommendation/runs/synthetic_accepted'
    run.mkdir(parents=True)
    evidence = run / 'synthetic_provider_receipt.json'; evidence.write_text('{"synthetic":true}')
    rehab_leaf = run / 'synthetic_rehab_receipt.json'; rehab_leaf.write_text('{"synthetic_rehab":true}')
    feature = run / 'synthetic_features.parquet'; feature.write_bytes(b'synthetic feature bytes')
    member = run / 'universe/mapped_members.parquet'; member.parent.mkdir(); member.write_bytes(b'synthetic member bytes')
    features = {**extension.reference(feature), 'status': 'READY', 'signal_date': '2026-10-05'}
    lineage = [{'ticker': 'SYNTHETIC', 'raw': extension.reference(evidence)}]
    lineage_hash = sha256(json.dumps(lineage, sort_keys=True).encode()).hexdigest()
    module.save(run / 'input_lineage.json', lineage)
    module.save(run / 'rehab_receipt.json', {'status': 'READY', 'target_date': '2026-10-05',
        'results': [{'receipt': extension.reference(rehab_leaf)}]})
    module.save(run / 'selected_hgb_features_binding.json', features)
    source_path = run / 'recommendation_source.json'
    source = {'status': 'READY', 'run_id': run.name, 'report_path': str(source_path),
        'generated_at': '2026-10-05T21:00:00+00:00', 'data_date': '2026-10-05',
        'model_sha256': 'a' * 64, 'input_manifest_sha256': lineage_hash,
        'rows': [{'ticker': f'S{i:02}', 'rank': i + 1, 'score': 0} for i in range(20)],
        'selected_hgb_features': features,
        'universe': {'report_path': str(member.parent / 'report.json'),
            'universe_members_sha256': extension.reference(member)['sha256']},
        'coverage': {'eligible_count': 20, 'mapped_count': 21, 'excluded_count': 1}}
    module.save(source_path, source)
    latest = {**source, 'report_path': str(run / 'report.json'),
        'accepted_source': extension.reference(source_path),
        'accepted_inputs': [extension.reference(run / name) for name in
            ('input_lineage.json', 'rehab_receipt.json', 'selected_hgb_features_binding.json')]}
    module.save(run / 'report.json', latest)
    module.save(paths.daily_root / 'A2_today_recommendation/latest.json', latest)
    binding = {'components': {'ALPHA': {'artifacts': [{'artifact_id': 'model', 'sha256': 'a' * 64}]}}}
    calendar = {'target_date': '2026-10-05', 'sessions': ['2026-10-02', '2026-10-05']}
    now = datetime(2026, 10, 6, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(hgb_policy_alignment, 'frozen_contract', lambda *_: ({}, {}))
    return paths, latest, source, binding, calendar, now, evidence, feature, member


def test_accepted_daily_bundle_uses_real_byte_bindings_and_original_input_hash(tmp_path, monkeypatch):
    from scripts.research.a2.evaluation.three_strategy_extension import reference
    paths, latest, source, binding, calendar, now, *_ = _accepted_daily_fixture(tmp_path, monkeypatch)
    document, ref = module._accepted_recommendation_source(paths, latest, binding, calendar, now)
    assert document == source and ref == reference(source['report_path'])


@pytest.mark.parametrize('damage', ['source_bytes', 'model_binding', 'source_model', 'before_close',
    'future_generated', 'naive_generated', 'lineage_document', 'lineage_leaf', 'feature_leaf',
    'member_leaf', 'rehab_leaf', 'rehab_target', 'rehab_not_ready', 'outside_run',
    'source_report_path', 'cardinality', 'latest_input_hash', 'accepted_input_hash'])
def test_same_date_recovery_invalid_bundle_never_falls_back_to_acquisition(tmp_path, monkeypatch, damage):
    from scripts import daily_recommendation_inputs as inputs
    from scripts.research.a2.evaluation.three_strategy_extension import reference
    fixture = _accepted_daily_fixture(tmp_path, monkeypatch)
    paths, latest, source, binding, calendar, now, evidence, feature, member = fixture
    original_source = Path(source['report_path'])
    if damage == 'source_bytes': original_source.write_bytes(original_source.read_bytes() + b' ')
    elif damage == 'model_binding': binding['components']['ALPHA']['artifacts'][0]['sha256'] = 'b' * 64
    elif damage == 'source_model': source['model_sha256'] = 'b' * 64
    elif damage == 'before_close': source['generated_at'] = '2026-10-05T19:59:59+00:00'
    elif damage == 'future_generated': source['generated_at'] = '2099-01-01T00:00:00+00:00'
    elif damage == 'naive_generated': source['generated_at'] = '2026-10-05T21:00:00'
    elif damage == 'lineage_document': module.save(original_source.parent / 'input_lineage.json', [])
    elif damage == 'lineage_leaf': evidence.write_bytes(b'changed provider bytes')
    elif damage == 'rehab_leaf': (original_source.parent / 'synthetic_rehab_receipt.json').write_bytes(b'changed rehab bytes')
    elif damage == 'feature_leaf': feature.write_bytes(b'changed feature bytes')
    elif damage == 'member_leaf': member.write_bytes(b'changed member bytes')
    elif damage in ('rehab_target', 'rehab_not_ready'):
        rehab = original_source.parent / 'rehab_receipt.json'; document = json.loads(rehab.read_text())
        document['target_date' if damage == 'rehab_target' else 'status'] = '2026-10-02' if damage == 'rehab_target' else 'BLOCKED'
        module.save(rehab, document)
    elif damage == 'outside_run': latest['report_path'] = str(paths.daily_root / 'outside/report.json')
    elif damage == 'source_report_path': source['report_path'] = str(paths.daily_root / 'outside/recommendation_source.json')
    elif damage == 'cardinality': source['rows'] = source['rows'][:-1]
    elif damage == 'latest_input_hash': latest['input_manifest_sha256'] = 'b' * 64
    elif damage == 'accepted_input_hash': latest['accepted_inputs'][0]['sha256'] = 'b' * 64
    if damage in ('source_model', 'before_close', 'future_generated', 'naive_generated', 'source_report_path', 'cardinality'):
        module.save(original_source, source); latest['accepted_source'] = reference(original_source)
    latest_path = paths.daily_root / 'A2_today_recommendation/latest.json'; module.save(latest_path, latest)
    before = latest_path.read_bytes()
    monkeypatch.setattr(inputs, 'load_frozen_binding', lambda *_: binding)
    monkeypatch.setattr(inputs, 'latest_completed_session', lambda *_: calendar)
    monkeypatch.setattr(module, 'acquire_pool_prices', lambda *a, **kw: pytest.fail('invalid accepted bundle reacquired'))
    monkeypatch.setattr(module, 'predict_current', lambda *a, **kw: pytest.fail('invalid accepted bundle reranked'))
    with pytest.raises((ValueError, FileNotFoundError, TypeError)):
        module.run_update(paths, execute=True, emit_progress=lambda *_: None)
    assert latest_path.read_bytes() == before
    assert not list(original_source.parent.glob('recovery/*/state.json'))


def _complete_synthetic_stages(target='2026-10-05', end='2026-10-05'):
    raw = {'status': 'PARTIAL', 'ranking_end_date': target, 'performance_end_date': end,
        'rx': {'status': 'BLOCKED', 'reason': 'SYNTHETIC_FROZEN_BOUNDARY'}}
    selected = {'status': 'READY', 'performance_end_date': end,
        'strategies': {sid: {'status': 'READY', 'signal_date': target}
            for sid in ('HGB_DIAG_5', 'HGB_FACTOR_5')}}
    return {'raw': raw, 'selected': selected}


@pytest.mark.parametrize('missing_stage', [None, 'selected'])
def test_same_date_recovery_reuses_immutable_source_and_only_runs_missing_worker(tmp_path, monkeypatch, missing_stage):
    from scripts import daily_recommendation_inputs as inputs
    from scripts.storage import storage_r2a
    paths, latest, source, binding, calendar, now, *_ = _accepted_daily_fixture(tmp_path, monkeypatch)
    original = Path(source['report_path']).read_bytes()
    canonical = [Path(latest['report_path']), paths.daily_root / 'A2_today_recommendation/latest.json']
    original_canonical = {path: path.read_bytes() for path in canonical}
    verified = _complete_synthetic_stages(); expected = []
    if missing_stage: verified.pop(missing_stage); expected = [missing_stage]
    monkeypatch.setattr(inputs, 'load_frozen_binding', lambda *_: binding)
    monkeypatch.setattr(inputs, 'latest_completed_session', lambda *_: calendar)
    monkeypatch.setattr(module, '_verified_daily_stage_summaries', lambda *a, **kw: verified)
    monkeypatch.setattr(module, 'acquire_pool_prices', lambda *a, **kw: pytest.fail('same date acquisition'))
    monkeypatch.setattr(module, 'predict_current', lambda *a, **kw: pytest.fail('same date inference'))
    monkeypatch.setattr(storage_r2a, 'DataStore', lambda: object())
    monkeypatch.setattr(module, 'refresh_daily_benchmarks', lambda *a, **kw:
        {'status': 'READY', 'available_end_date': source['data_date'], 'action': 'REUSED_SYNTHETIC'})
    calls = []
    def worker(actual, name, argv, log):
        calls.append(argv[1])
        assert argv[3] == Path(source['report_path']) and argv[5] == latest['accepted_source']['sha256']
        log.write_text(json.dumps({'event': 'performance_result', 'result': _complete_synthetic_stages()[argv[1]]}) + '\n')
        return {'exit_code': 0, 'log_path': str(log)}
    monkeypatch.setattr(module, 'run_provider', worker)
    result = module.run_update(paths, execute=True, emit_progress=lambda *_: None)
    assert calls == expected and Path(source['report_path']).read_bytes() == original
    assert result['rows'] == source['rows'] and result['accepted_source'] == latest['accepted_source']
    assert result['completion']['status'] == 'READY'
    assert result['completion']['limitations']['coverage'] == source['coverage']
    assert result['recovery']['reused_stages'] == sorted(verified)
    assert result['recovery']['acquisition_calls'] == result['recovery']['inference_calls'] == result['recovery']['broker_calls'] == 0
    state = json.loads(next(Path(source['report_path']).parent.glob('recovery/*/state.json')).read_text(encoding='utf-8'))
    assert state['status'] == 'READY' and state['completion'] == result['completion']
    assert result['report_path'] == latest['report_path']
    assert json.loads(Path(result['recovery']['report_path']).read_text(encoding='utf-8')) == result
    assert all(path.read_bytes() == data for path, data in original_canonical.items())
    # The simulated publication from the first missing worker is now visible.
    verified.update(_complete_synthetic_stages())
    again = module.run_update(paths, execute=True, emit_progress=lambda *_: None)
    assert calls == expected and again['accepted_source'] == result['accepted_source']
    assert again['recovery']['report_path'] != result['recovery']['report_path']
    assert again['recovery']['acquisition_calls'] == again['recovery']['inference_calls'] == 0
    assert Path(source['report_path']).read_bytes() == original
    assert all(path.read_bytes() == data for path, data in original_canonical.items())


@pytest.mark.parametrize('prior', ['absent', 'different_day', 'not_ready'])
def test_recovery_nonapplicable_inputs_return_none_without_verification_or_workers(tmp_path, monkeypatch, prior):
    from datetime import datetime, timezone
    paths = SimpleNamespace(daily_root=tmp_path)
    if prior != 'absent':
        module.save(tmp_path / 'A2_today_recommendation/latest.json',
            {'status': 'READY' if prior == 'different_day' else 'WAITING_DATA',
             'data_date': '2026-10-02' if prior == 'different_day' else '2026-10-05'})
    monkeypatch.setattr(module, '_accepted_recommendation_source', lambda *a: pytest.fail('unrelated source verification'))
    monkeypatch.setattr(module, 'update_performance_isolated', lambda *a, **kw: pytest.fail('nonapplicable replay'))
    assert module.resume_published_update(paths, {}, {'target_date': '2026-10-05'},
        datetime(2026, 10, 6, tzinfo=timezone.utc), lambda *_: None) is None


def test_explicit_refresh_data_bypasses_recovery_but_preserves_prior_input_bytes(tmp_path, monkeypatch):
    paths = _ready_daily_without_external_work(tmp_path, monkeypatch)
    root = paths.daily_root / 'A2_today_recommendation'; old_source = root / 'runs/previous/recommendation_source.json'
    module.save(old_source, {'status': 'READY', 'data_date': '2026-10-05', 'synthetic': True})
    module.save(root / 'latest.json', {'status': 'READY', 'data_date': '2026-10-05'})
    before = old_source.read_bytes()
    monkeypatch.setattr(module, 'resume_published_update', lambda *a, **kw: pytest.fail('force flag used recovery'))
    calls = []
    monkeypatch.setattr(module, 'acquire_pool_prices', lambda *a, **kw:
        (calls.append('new_acquisition') or {'moomoo': {'results': []}}))
    monkeypatch.setattr(module, 'update_performance_isolated', lambda *a, **kw: tuple(_complete_synthetic_stages().values()))
    result = module.run_update(paths, execute=True, emit_progress=lambda *_: None, refresh_data=True)
    assert calls == ['new_acquisition'] and result['status'] == 'READY'
    assert old_source.read_bytes() == before and Path(result['report_path']).parent != old_source.parent


@pytest.mark.parametrize('defect', [None, 'raw_ranking_old', 'selected_wrong_source', 'nested_selected_hash'])
def test_verified_stage_recovery_keeps_opening_extension_and_rejects_unbound_stage(tmp_path, monkeypatch, defect):
    from scripts.research.a2.evaluation import demo_performance, three_strategy_extension as extension
    from scripts.research.a2.portfolio import selected_hgb
    source = tmp_path / 'accepted_source.json'; source.write_text('{"synthetic":true}')
    source_ref = extension.reference(source)
    raw_path = tmp_path / 'raw_manifest.json'
    raw = {'status': 'PARTIAL', 'run_id': 'synthetic_raw', 'report_path': str(raw_path),
        'ranking_end_date': '2026-10-02' if defect == 'raw_ranking_old' else '2026-10-05',
        'performance_end_date': '2026-10-06', 'recommendation_reports': [source_ref]}
    module.save(raw_path, raw)
    package_path = tmp_path / 'package.json'; package_path.write_text('{}')
    leaf = tmp_path / 'executed_ledger.csv'; leaf.write_text('synthetic immutable rows')
    package = {'policy_id': 'HGB_TOP20_RISK_R1', 'source_refs': {'current/report.json': {**source_ref, 'sha256': 'b' * 64}
        if defect == 'selected_wrong_source' else source_ref},
        'strategies': {sid: {'application': {'status': 'READY', 'signal_date': '2026-10-05'}}
            for sid in ('HGB_DIAG_5', 'HGB_FACTOR_5')}}
    manifest = {'policy_id': 'HGB_TOP20_RISK_R1', 'performance_period': {'end': '2026-10-06'},
        'strategies': {'HGB_DIAG_5': {'ledger': extension.reference(leaf)}}}
    if defect == 'nested_selected_hash': leaf.write_text('changed synthetic immutable rows')
    monkeypatch.setattr(demo_performance, 'canonical_manifest', lambda *_: (raw_path, extension.reference(raw_path)))
    monkeypatch.setattr(selected_hgb, 'active_policy', lambda *_: ('HGB_TOP20_RISK_R1', package_path))
    monkeypatch.setattr(module, '_execution_selected_manifest', lambda *_: (package, manifest, {}))
    result = module._verified_daily_stage_summaries(SimpleNamespace(daily_root=tmp_path), source_ref, '2026-10-05')
    assert ('raw' in result) == (defect != 'raw_ranking_old')
    assert ('selected' in result) == (defect not in ('selected_wrong_source', 'nested_selected_hash'))
    assert all(stage['performance_end_date'] == '2026-10-06' for stage in result.values())
    assert all(stage['action'] == 'REUSED_VERIFIED_CURRENT' for stage in result.values())


@pytest.mark.parametrize('defect', [None, 'old_raw_ranking', 'old_raw_curve', 'hgb_partial', 'old_hgb_curve',
    'old_benchmark', 'benchmark_blocked', 'recommendation_blocked', 'no_target',
    'old_hgb_signal', 'missing_hgb_strategy', 'blocked_hgb_strategy'])
def test_completion_requires_all_core_stages_and_preserves_independent_limitations(defect):
    stages = _complete_synthetic_stages(end='2026-10-06')
    result = {'status': 'READY', 'data_date': '2026-10-05', 'coverage': {'eligible_count': 20, 'mapped_count': 21},
        'performance_update': stages['raw'], 'selected_strategies_update': stages['selected'],
        'benchmark_update': {'status': 'READY', 'available_end_date': '2026-10-05'}}
    if defect == 'old_raw_ranking': result['performance_update']['ranking_end_date'] = '2026-10-02'
    elif defect == 'old_raw_curve': result['performance_update']['performance_end_date'] = '2026-10-02'
    elif defect == 'hgb_partial': result['selected_strategies_update']['status'] = 'PARTIAL'
    elif defect == 'old_hgb_curve': result['selected_strategies_update']['performance_end_date'] = '2026-10-02'
    elif defect == 'old_hgb_signal': result['selected_strategies_update']['strategies']['HGB_FACTOR_5']['signal_date'] = '2026-10-02'
    elif defect == 'missing_hgb_strategy': result['selected_strategies_update']['strategies'].pop('HGB_FACTOR_5')
    elif defect == 'blocked_hgb_strategy': result['selected_strategies_update']['strategies']['HGB_FACTOR_5']['status'] = 'BLOCKED'
    elif defect == 'old_benchmark': result['benchmark_update']['available_end_date'] = '2026-10-02'
    elif defect == 'benchmark_blocked': result['benchmark_update']['status'] = 'BLOCKED'
    elif defect == 'recommendation_blocked': result['status'] = 'BLOCKED'
    elif defect == 'no_target': result.pop('data_date')
    completion = module._delivery_completion(result)
    assert completion['status'] == ('READY' if defect is None else 'PARTIAL')
    assert completion['schema'] == 'A2_DAILY_COMPLETION_V1'
    assert completion['limitations']['coverage'] == result['coverage']
    assert completion['limitations']['rx']['status'] == 'BLOCKED'
    if defect is None: assert all(completion['required_stages'].values())


@pytest.mark.parametrize('completion,expected_exit', [('READY', 0), ('PARTIAL', 2)])
def test_main_preserves_ready_recommendation_but_returns_incomplete_delivery_exit(tmp_path, monkeypatch, capsys, completion, expected_exit):
    from scripts.common import storage_paths
    paths = SimpleNamespace(daily_root=tmp_path)
    monkeypatch.setattr(storage_paths, 'resolve', lambda: paths)
    calls = []
    def run(actual, execute, **kwargs):
        calls.append((actual, execute, kwargs)); return {'status': 'READY', 'completion': {'status': completion}}
    monkeypatch.setattr(module, 'run_update', run)
    assert module.main(['--execute']) == expected_exit
    assert calls == [(paths, True, {})]
    response = json.loads(capsys.readouterr().out)['result']
    assert response['status'] == 'READY' and response['completion']['status'] == completion


def test_main_explicit_refresh_data_forwards_only_the_existing_execute_flag(tmp_path, monkeypatch, capsys):
    from scripts.common import storage_paths
    paths = SimpleNamespace(daily_root=tmp_path)
    monkeypatch.setattr(storage_paths, 'resolve', lambda: paths)
    calls = []
    monkeypatch.setattr(module, 'run_update', lambda *args, **kwargs:
        (calls.append((args, kwargs)) or {'status': 'READY', 'completion': {'status': 'READY'}}))
    assert module.main(['--execute', '--refresh-data']) == 0
    assert calls == [((paths, True), {'refresh_data': True})]
    capsys.readouterr()


@pytest.mark.parametrize('argv', [['--refresh-data'], ['--execute', '--refresh-data', '--execution-charts'],
    ['--performance-worker', 'raw', '--source-report', 'synthetic.json', '--source-sha256', 'a' * 64, '--refresh-data']])
def test_main_incompatible_refresh_modes_reject_before_any_owner_action(monkeypatch, argv):
    monkeypatch.setattr(module, 'run_update', lambda *a, **kw: pytest.fail('invalid mode acquired'))
    monkeypatch.setattr(module, '_performance_worker', lambda *a, **kw: pytest.fail('invalid mode replayed'))
    monkeypatch.setattr(module, 'run_execution_charts', lambda *a, **kw: pytest.fail('invalid mode opening'))
    with pytest.raises(SystemExit) as rejected: module.main(argv)
    assert rejected.value.code == 2



@pytest.mark.parametrize('scenario,accepted,ready', [
    ('ready', True, True), ('partial', True, False), ('running', True, True), ('half_running', False, False),
    ('owner_reject', False, False), ('wrong_signal', False, False), ('wrong_execution', False, False),
    ('missing_sid', False, False), ('legacy_sid', False, False), ('date', False, False), ('future_year', False, False)])
def test_powershell_delivery_guard_prepares_only_bound_targets_even_when_charts_incomplete(tmp_path, scenario, accepted, ready):
    """The PS delegates model/source/account eligibility to the original prepare owner."""
    import runpy
    helper = runpy.run_path(str(SOURCE.parents[1] / 'tests/test_manual_daily_entrypoint.py'))
    response = helper['run_prepare_case'](tmp_path, scenario)
    assert response['accepted'] is accepted and response['ready'] is ready
    if scenario in {'date', 'future_year'}: assert response['calls'] == []
    elif scenario == 'half_running': assert response['calls'] == ['GET:/api/applied/maintenance-status']
    else: assert response['calls'][0] == 'GET:/api/applied/maintenance-status'
    assert not any('start' in call or 'order' in call for call in response['calls'])
    if not accepted: assert response['failure']


@pytest.mark.parametrize('failed_stage', ['performance', 'benchmark'])
def test_recovery_stage_exceptions_are_independent_and_preserve_successful_branches(tmp_path, monkeypatch, failed_stage):
    from scripts.storage import storage_r2a
    paths, latest, source, binding, calendar, now, *_ = _accepted_daily_fixture(tmp_path, monkeypatch)
    original = Path(source['report_path']).read_bytes()
    canonical = [Path(latest['report_path']), paths.daily_root / 'A2_today_recommendation/latest.json']
    original_canonical = {path: path.read_bytes() for path in canonical}
    monkeypatch.setattr(module, '_verified_daily_stage_summaries', lambda *a, **kw: {})
    monkeypatch.setattr(storage_r2a, 'DataStore', lambda: object())
    calls = []
    def performance(*a, **kw):
        calls.append('performance')
        if failed_stage == 'performance': raise PermissionError('SYNTHETIC_PERFORMANCE_ORCHESTRATION_FAILED')
        return tuple(_complete_synthetic_stages().values())
    def benchmark(*a, **kw):
        calls.append('benchmark')
        if failed_stage == 'benchmark': raise PermissionError('SYNTHETIC_BENCHMARK_ORCHESTRATION_FAILED')
        return {'status': 'READY', 'available_end_date': '2026-10-05'}
    monkeypatch.setattr(module, 'update_performance_isolated', performance)
    monkeypatch.setattr(module, 'refresh_daily_benchmarks', benchmark)
    result = module.resume_published_update(paths, binding, calendar, now, lambda *_: None)
    assert calls == ['performance', 'benchmark'] and Path(source['report_path']).read_bytes() == original
    assert result['status'] == 'READY' and result['completion']['status'] == 'PARTIAL'
    if failed_stage == 'benchmark':
        assert result['performance_update']['status'] == 'PARTIAL'
        assert result['selected_strategies_update']['status'] == 'READY'
        assert result['benchmark_update']['status'] == 'BLOCKED'
    else:
        assert result['performance_update']['status'] == result['selected_strategies_update']['status'] == 'BLOCKED'
        assert result['benchmark_update']['status'] == 'READY'
    assert result['report_path'] == latest['report_path']
    assert json.loads(Path(result['recovery']['report_path']).read_text(encoding='utf-8')) == result
    assert all(path.read_bytes() == data for path, data in original_canonical.items())


@pytest.mark.parametrize('field', ['rows', 'ranked_rows'])
def test_recovery_rejects_mutated_latest_recommendation_values_even_with_unchanged_source(tmp_path, monkeypatch, field):
    paths, latest, source, binding, calendar, now, *_ = _accepted_daily_fixture(tmp_path, monkeypatch)
    if field == 'ranked_rows':
        source[field] = source['rows'].copy(); module.save(Path(source['report_path']), source)
        from scripts.research.a2.evaluation.three_strategy_extension import reference
        latest['accepted_source'] = reference(source['report_path'])
    latest[field] = [{'ticker': 'MUTATED', 'rank': 1, 'score': 0}]
    with pytest.raises(ValueError):
        module._accepted_recommendation_source(paths, latest, binding, calendar, now)



def test_real_verified_stage_recovery_keeps_prior_rx_failure_trace_without_claiming_rx_ready(tmp_path, monkeypatch):
    from scripts.research.a2.evaluation import demo_performance, three_strategy_extension as extension
    from scripts.research.a2.portfolio import selected_hgb
    from scripts.storage import storage_r2a
    paths, latest, source, binding, calendar, now, *_ = _accepted_daily_fixture(tmp_path, monkeypatch)
    latest['performance_update'] = {'status': 'PARTIAL', 'rx': {
        'status': 'BLOCKED', 'error': 'SYNTHETIC_RX_FIT_BOUNDARY'}}
    module.save(paths.daily_root / 'A2_today_recommendation/latest.json', latest)
    module.save(Path(latest['report_path']), latest)
    prior_ref = extension.reference(latest['report_path'])
    raw_path = tmp_path / 'raw_manifest.json'
    module.save(raw_path, {'status': 'PARTIAL', 'run_id': 'synthetic_raw', 'report_path': str(raw_path),
        'ranking_end_date': '2026-10-05', 'performance_end_date': '2026-10-05',
        'recommendation_reports': [latest['accepted_source']]})
    package_path = tmp_path / 'package.json'; package_path.write_text('{}')
    package = {'policy_id': 'HGB_TOP20_RISK_R1', 'source_refs': {'current/report.json': latest['accepted_source']},
        'strategies': {sid: {'application': {'status': 'READY', 'signal_date': '2026-10-05'}}
            for sid in ('HGB_DIAG_5', 'HGB_FACTOR_5')}}
    manifest = {'policy_id': 'HGB_TOP20_RISK_R1', 'performance_period': {'end': '2026-10-05'}, 'strategies': {}}
    monkeypatch.setattr(demo_performance, 'canonical_manifest', lambda *_: (raw_path, extension.reference(raw_path)))
    monkeypatch.setattr(selected_hgb, 'active_policy', lambda *_: ('HGB_TOP20_RISK_R1', package_path))
    monkeypatch.setattr(module, '_execution_selected_manifest', lambda *_: (package, manifest, {}))
    monkeypatch.setattr(storage_r2a, 'DataStore', lambda: object())
    monkeypatch.setattr(module, 'refresh_daily_benchmarks', lambda *a, **kw:
        {'status': 'READY', 'available_end_date': '2026-10-05'})
    monkeypatch.setattr(module, 'run_provider', lambda *a, **kw: pytest.fail('verified stages need no workers'))
    result = module.resume_published_update(paths, binding, calendar, now, lambda *_: None)
    rx = result['completion']['limitations']['rx']
    assert 'SYNTHETIC_RX_FIT_BOUNDARY' in json.dumps(rx)
    assert rx['status'] != 'READY'  # Reported limitation is not a new RX qualification.
    assert prior_ref['sha256'] in json.dumps(rx)
    assert 'prior_snapshot' in rx
    assert result['recovery']['reused_stages'] == ['raw', 'selected']
    assert result['recovery']['inference_calls'] == result['recovery']['acquisition_calls'] == 0


@pytest.mark.parametrize('active,package_policy,manifest_policy,expected', [
    ('RAW_TOP20_FROZEN_LEGACY', 'RAW_TOP20_FROZEN_LEGACY', 'RAW_TOP20_FROZEN_LEGACY', True),
    ('HGB_TOP20_RISK_R1', 'HGB_TOP20_RISK_R1', 'HGB_TOP20_RISK_R1', True),
    ('HGB_TOP20_RISK_R1', 'RAW_TOP20_FROZEN_LEGACY', 'RAW_TOP20_FROZEN_LEGACY', False),
    ('RAW_TOP20_FROZEN_LEGACY', 'HGB_TOP20_RISK_R1', 'HGB_TOP20_RISK_R1', False),
    ('RAW_TOP20_FROZEN_LEGACY', 'RAW_TOP20_FROZEN_LEGACY', 'HGB_TOP20_RISK_R1', False)])
def test_legacy_stage_recovery_requires_active_package_and_research_policy(tmp_path, monkeypatch, active, package_policy, manifest_policy, expected):
    from scripts.research.a2.portfolio import selected_hgb
    from scripts.research.a2.evaluation import demo_performance, three_strategy_extension as extension
    source = tmp_path / 'source.json'; source.write_text('{"synthetic":true}')
    package_path = tmp_path / 'package.json'; package_path.write_text('{}')
    source_ref = extension.reference(source)
    package = {'policy_id': package_policy, 'source_refs': {'current/report.json': source_ref},
        'strategies': {sid: {'application': {'status': 'READY', 'signal_date': '2026-10-05'}} for sid in selected_hgb.STRATEGY_IDS}}
    manifest = {'policy_id': manifest_policy, 'performance_period': {'end': '2026-10-05'}, 'strategies': {}}
    monkeypatch.setattr(selected_hgb, 'active_policy', lambda *_: (active, package_path))
    monkeypatch.setattr(module, '_execution_selected_manifest', lambda *_: (package, manifest, {}))
    monkeypatch.setattr(demo_performance, 'canonical_manifest', lambda *_: (_ for _ in ()).throw(ValueError('synthetic no Raw')))
    frozen = []
    monkeypatch.setattr(selected_hgb, '_source_root', lambda *_: 'synthetic-frozen-owner')
    monkeypatch.setattr(selected_hgb, 'verify_frozen', lambda root: frozen.append(root))
    diagnostics = {}
    result = module._verified_daily_stage_summaries(SimpleNamespace(daily_root=tmp_path), source_ref, '2026-10-05', diagnostics=diagnostics)
    assert ('selected' in result) is expected
    assert frozen == (['synthetic-frozen-owner'] if expected and active == selected_hgb.LEGACY_POLICY else [])
    if expected:
        assert result['selected']['policy_id'] == active
    else:
        assert diagnostics['selected']['reason'] == 'RESUME_HGB_ACTIVE_POLICY_CHANGED'


def test_legacy_opening_context_rejects_wrong_policy_before_loading_inputs(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from scripts.research.a2.portfolio import selected_hgb
    from scripts import daily_recommendation_inputs
    package = tmp_path / 'package.json'; package.write_text('{"policy_id":"HGB_TOP20_RISK_R1"}')
    monkeypatch.setattr(selected_hgb, 'active_policy', lambda *_: (selected_hgb.LEGACY_POLICY, package))
    monkeypatch.setattr(daily_recommendation_inputs, 'load_frozen_binding', lambda *_: pytest.fail('wrong policy must reject before inputs'))
    with pytest.raises(ValueError, match='EXECUTION_CHART_ACTIVE_POLICY_CHANGED'):
        module._execution_chart_context(SimpleNamespace(repo_root=tmp_path), datetime(2026, 10, 6, 14, tzinfo=timezone.utc))


@pytest.mark.parametrize('shell_name', ['pwsh', 'powershell.exe'])
def test_powershell_open_demo_only_calls_original_interface(tmp_path, shell_name):
    import runpy, shutil
    shell = shutil.which(shell_name)
    if not shell: pytest.skip('PowerShell unavailable for original DEMO entry')
    helper = runpy.run_path(str(SOURCE.parents[1] / 'tests/test_manual_daily_entrypoint.py'))
    opened = (SOURCE.parents[1] / '打开DEMO.ps1').read_text(encoding='utf-8-sig')
    assert 'apps/demo_console/start.ps1' in opened and 'daily_recommendation' not in opened
    code = "$tokens=$null;$issues=$null;[Management.Automation.Language.Parser]::ParseFile('" + str(SOURCE.parents[1] / '打开DEMO.ps1').replace("'", "''") + "',[ref]$tokens,[ref]$issues)|Out-Null;@{errors=$issues.Count}|ConvertTo-Json -Compress"
    assert helper['_ps'](code, shell=shell)['errors'] == 0


def _requalification_fixture(tmp_path, monkeypatch):
    import hashlib
    import pandas as pd
    import sqlite3
    from scripts import daily_recommendation_inputs as inputs
    from scripts.storage import storage_r2a
    from scripts.research.a2.portfolio import selected_hgb as selected
    from scripts.research.a2.evaluation.three_strategy_extension import reference
    from apps.demo_console.adapters import selected_strategies_reader as reader
    paths, latest, source, binding, calendar, now, evidence, feature, member = _accepted_daily_fixture(tmp_path, monkeypatch)
    members = [{'ticker': f'S{i:02}', 'security_id': f'SID{i:02}', 'moomoo_symbol': f'US.S{i:02}'} for i in range(40)]
    pd.DataFrame(members).to_parquet(member, index=False)
    source['universe'].update(status='READY', current=True, inference_ready=True,
        target_date=calendar['target_date'], mapped_member_count=len(members), universe_id='bound-synthetic',
        universe_members_sha256=reference(member)['sha256'])
    rows = []
    for i in range(2):
        leaf = member.parent / (f'raw{i}.csv'); leaf.write_text('immutable synthetic raw input')
        rows.append({'status': 'FETCHED_VALIDATED_INTERVAL', 'item': {'ticker': f'S{i:02}', 'adjustment': 'raw',
            'security_id': f'SID{i:02}', 'moomoo_symbol': f'US.S{i:02}', 'planned_end_date': calendar['target_date']}, **reference(leaf)})
    source['acquisitions'] = {'moomoo': {'results': [dict(rows[0]), *rows]}, 'yahoo': {'status': 'OLD_ACCEPTED_ONLY'}}
    source['native_current_tail'] = {'result_count': 2}
    source['native_market_publication'] = {'status': 'PUBLISHED', 'target_date': calendar['target_date'],
        'all_old_dates_preserved': True, 'published_intervals': 2, 'requested_keys': 2, 'raw_reached_target': 2,
        'request_sha256': hashlib.sha256(json.dumps({'target_date': calendar['target_date'], 'receipts': [
            {key: row.get(key) for key in ('item', 'path', 'sha256')} for row in rows]}, sort_keys=True).encode()).hexdigest()}
    source['benchmark_update'] = {'status': 'READY', 'available_end_date': calendar['target_date']}
    source_path = Path(source['report_path']); module.save(source_path, source)
    latest = {**latest, **source, 'report_path': str(source_path.parent / 'report.json'), 'accepted_source': reference(source_path)}
    module.save(Path(latest['report_path']), latest)
    module.save(paths.daily_root / 'A2_today_recommendation/latest.json', latest)
    package_path = paths.daily_root / 'A2_selected_hgb/latest.json'; module.save(package_path, {'synthetic': True})
    package = {'policy_id': selected.LEGACY_POLICY, 'source_refs': {'current/report.json': reference(source_path)},
        'strategies': {sid: {'application': {'status': 'READY', 'signal_date': calendar['target_date']}} for sid in selected.STRATEGY_IDS}}
    monkeypatch.setattr(inputs, 'load_frozen_binding', lambda *_: binding)
    monkeypatch.setattr(inputs, 'latest_completed_session', lambda *_: calendar)
    monkeypatch.setattr(selected, 'active_policy', lambda *_: (selected.LEGACY_POLICY, package_path))
    monkeypatch.setattr(selected, 'verify_frozen', lambda *_: tmp_path)
    monkeypatch.setattr(reader, 'load_package', lambda *_: package)
    catalog = tmp_path / 'catalog.sqlite3'
    with sqlite3.connect(catalog) as connection:
        connection.execute('CREATE TABLE data_files(dataset,ticker,adjustment,path,source_sha256)')
        connection.execute('INSERT INTO data_files VALUES(?,?,?,?,?)', ('prices_daily','S00','raw',str(evidence),reference(evidence)['sha256']))
    monkeypatch.setattr(storage_r2a, 'DataStore', lambda: SimpleNamespace(catalog_path=catalog))
    # The explicit repair branch must never reach any ordinary acquisition owner.
    for name in ('live_quota', 'acquire_pool_prices', 'topup_moomoo_once', 'acquire_native_current_tail',
                 'refresh_daily_benchmarks', 'acquire_other_data'):
        monkeypatch.setattr(module, name, lambda *a, **kw: pytest.fail('offline repair acquired'))
    from scripts import daily_recommendation_prices, daily_recommendation_universe
    monkeypatch.setattr(daily_recommendation_prices, 'refresh_rehab', lambda *a, **kw: pytest.fail('offline repair refreshed rehab'))
    monkeypatch.setattr(daily_recommendation_prices, 'publish_acquired_prices', lambda *a, **kw: pytest.fail('offline repair republished prices'))
    monkeypatch.setattr(daily_recommendation_universe, 'refresh_universe', lambda *a, **kw: pytest.fail('offline repair refreshed universe'))
    return paths, latest, source, calendar, package, catalog


def test_explicit_requalification_reuses_saved_inputs_and_original_publisher_without_download_or_fit(tmp_path, monkeypatch):
    from scripts.research.a2.evaluation.three_strategy_extension import reference
    paths, latest, source, calendar, package, catalog = _requalification_fixture(tmp_path, monkeypatch)
    old_paths = [Path(source['report_path']), Path(latest['report_path'])]
    old = {p: p.read_bytes() for p in old_paths}
    original_acquisitions = json.loads(json.dumps(source['acquisitions']))
    calls = []
    def predict(binding, universe, target, sessions, acquisitions, store, rehab, output_dir=None):
        calls.append((target, sessions, acquisitions, rehab))
        assert acquisitions['moomoo']['results'] == []
        assert universe['members'][0]['security_id'] == 'SID00' and rehab['target_date'] == target
        feature = output_dir / 'new_feature.parquet'; feature.write_bytes(b'new genuine synthetic feature output')
        module.save(output_dir / 'selected_hgb_features_binding.json',
            {**reference(feature), 'status': 'READY', 'signal_date': target})
        return ([{'ticker': f'S{i:02}', 'rank': i + 1, 'score': .1, 'security_id': f'SID{i:02}'} for i in range(40)],
                [{'ticker': 'S00', 'input': reference(Path(source['report_path']))}], [])
    monkeypatch.setattr(module, 'predict_current', predict)
    observed = []
    def stages(paths, result, run_dir, progress, **kwargs):
        immutable = json.loads((run_dir / 'recommendation_source.json').read_text(encoding='utf-8'))
        assert immutable['repair_lineage'] == result['repair_lineage']
        assert module._validated_repair_ref(immutable, run_dir / 'recommendation_source.json') == result['repair_lineage']
        observed.append(immutable)
        return tuple(_complete_synthetic_stages().values())
    monkeypatch.setattr(module, 'update_performance_isolated', stages)
    result = module.run_update(paths, execute=True, requalify_inputs=True, emit_progress=lambda *_: None)
    assert result['status'] == result['completion']['status'] == 'READY' and len(calls) == len(observed) == 1
    assert result['run_id'] != source['run_id'] and len(result['ranked_rows']) == 40
    assert source['acquisitions'] == original_acquisitions == result['acquisitions']
    assert all(p.read_bytes() == content for p, content in old.items())
    assert json.loads((paths.daily_root / 'A2_today_recommendation/latest.json').read_text(encoding='utf-8')) == result
    repair = json.loads(Path(result['repair_lineage']['path']).read_text(encoding='utf-8'))
    assert repair['schema'] == 'A2_OFFLINE_INPUT_REPAIR_V1' and repair['reason'] == 'INPUT_ROUTING_REQUALIFICATION'
    assert repair['parent_inputs'][0] == latest['accepted_source']
    assert repair['network_requests_this_run'] == repair['model_fit_count'] == repair['parameter_search_count'] == 0
    assert all(repair[key] for key in ('old_date_keys_retained', 'old_rows_unchanged', 'unrelated_current_keys_unchanged'))
    assert repair['catalog_metadata_before_sha256'] == repair['catalog_metadata_after_sha256']
    assert (Path(result['report_path']).parent / 'rehab_receipt.json').read_bytes() == (old_paths[0].parent / 'rehab_receipt.json').read_bytes()


@pytest.mark.parametrize('failure', ['predict', 'catalog_change', 'old_leaf_change', 'feature_blocked'])
def test_requalification_failure_preserves_previous_latest_and_all_accepted_reports(tmp_path, monkeypatch, failure):
    import sqlite3
    from scripts.research.a2.evaluation.three_strategy_extension import reference
    paths, latest, source, calendar, package, catalog = _requalification_fixture(tmp_path, monkeypatch)
    originals = {p: p.read_bytes() for p in (paths.daily_root / 'A2_today_recommendation/latest.json',
        Path(latest['report_path']), Path(source['report_path']))}
    def predict(*args, **kwargs):
        if failure == 'predict': raise ValueError('SYNTHETIC_FROZEN_PREDICT_FAILURE')
        output = kwargs['output_dir']; leaf = output / 'new_features'; leaf.write_bytes(b'synthetic features')
        module.save(output / 'selected_hgb_features_binding.json', {**reference(leaf),
            'status': 'BLOCKED' if failure == 'feature_blocked' else 'READY', 'signal_date': calendar['target_date']})
        if failure == 'catalog_change':
            with sqlite3.connect(catalog) as connection: connection.execute("UPDATE data_files SET source_sha256='changed'")
        if failure == 'old_leaf_change':
            Path(source['selected_hgb_features']['path']).write_bytes(b'tampered old input')
        return ([{'ticker': f'S{i:02}', 'rank': i + 1, 'score': 0} for i in range(20)], [], [])
    monkeypatch.setattr(module, 'predict_current', predict)
    monkeypatch.setattr(module, 'update_performance_isolated', lambda *a, **kw: pytest.fail('failed qualification published'))
    result = module.run_update(paths, execute=True, requalify_inputs=True, emit_progress=lambda *_: None)
    assert result['status'] == 'BLOCKED' and result['rows'] == []
    assert all(p.read_bytes() == content for p, content in originals.items())
    assert not (Path(result['report_path']).parent / 'recommendation_source.json').exists()


@pytest.mark.parametrize('failure', ['wrong_policy', 'wrong_source', 'wrong_signal', 'publication_proof', 'stale_target', 'acquisition_leaf'])
def test_requalification_rejects_unaccepted_or_wrong_policy_inputs_before_prediction(tmp_path, monkeypatch, failure):
    from scripts.research.a2.portfolio import selected_hgb as selected
    from scripts.research.a2.evaluation.three_strategy_extension import reference
    paths, latest, source, calendar, package, catalog = _requalification_fixture(tmp_path, monkeypatch)
    latest_path = paths.daily_root / 'A2_today_recommendation/latest.json'
    if failure == 'wrong_policy': package['policy_id'] = selected.DIRECT_POLICY
    elif failure == 'wrong_source': package['source_refs']['current/report.json']['sha256'] = '0' * 64
    elif failure == 'wrong_signal': package['strategies']['HGB_FACTOR_5']['application']['signal_date'] = '2026-10-02'
    elif failure == 'stale_target': calendar['target_date'] = '2026-10-06'
    elif failure == 'acquisition_leaf': Path(source['acquisitions']['moomoo']['results'][-1]['path']).write_bytes(b'changed')
    else:
        source['native_market_publication']['request_sha256'] = '0' * 64
        module.save(Path(source['report_path']), source)
        latest['accepted_source'] = reference(Path(source['report_path']));module.save(latest_path, latest)
    original = latest_path.read_bytes()
    monkeypatch.setattr(module, 'predict_current', lambda *a, **kw: pytest.fail('invalid inputs inferred'))
    with pytest.raises((ValueError, FileNotFoundError)):
        module.run_update(paths, execute=True, requalify_inputs=True, emit_progress=lambda *_: None)
    assert latest_path.read_bytes() == original


def test_main_requalification_flag_is_explicit_and_does_not_change_refresh_or_resume(monkeypatch, capsys):
    from scripts.common import storage_paths
    paths = SimpleNamespace()
    monkeypatch.setattr(storage_paths, 'resolve', lambda: paths)
    calls = []
    monkeypatch.setattr(module, 'run_update', lambda *a, **kw: calls.append((a, kw)) or {'status': 'READY'})
    assert module.main(['--execute', '--requalify-inputs']) == 0
    assert calls == [((paths, True), {'requalify_inputs': True})]
    capsys.readouterr()


@pytest.mark.parametrize('argv', [['--requalify-inputs'], ['--execute', '--refresh-data', '--requalify-inputs'],
    ['--execute', '--requalify-inputs', '--execution-charts'],
    ['--performance-worker', 'raw', '--source-report', 'synthetic.json', '--source-sha256', 'a' * 64, '--requalify-inputs']])
def test_requalification_incompatible_modes_reject_without_owner_actions(monkeypatch, argv):
    monkeypatch.setattr(module, 'run_update', lambda *a, **kw: pytest.fail('invalid mode ran'))
    monkeypatch.setattr(module, '_performance_worker', lambda *a, **kw: pytest.fail('invalid mode worked'))
    with pytest.raises(SystemExit) as error: module.main(argv)
    assert error.value.code == 2


@pytest.mark.parametrize('performance_end,forward_pending', [('2026-10-05', False), ('2026-10-06', True)])
def test_offline_repair_raw_forwarding_distinguishes_unexecuted_new_signal_from_recorded_cutoff(tmp_path, monkeypatch, performance_end, forward_pending):
    from scripts.research.a2.evaluation import demo_performance, demo_rx_performance
    pointer, immutable = _saved_prior_performance(tmp_path)
    module.save(immutable, {'status': 'PARTIAL', 'report_path': str(immutable),
        'ranking_end_date': '2026-10-06', 'performance_end_date': performance_end})
    pointer.write_bytes(immutable.read_bytes())
    repair = tmp_path / 'repair.json'; repair.write_text('{}')
    repair_ref = {'path': str(repair), 'sha256': 'synthetic_bound_by_original_validator'}
    monkeypatch.setattr(module, '_validated_repair_ref', lambda *a: repair_ref)
    calls = []
    monkeypatch.setattr(demo_performance, 'refresh_demo_performance', lambda *a, **kw:
        calls.append(kw) or _mock_performance_manifest(tmp_path))
    monkeypatch.setattr(demo_rx_performance, 'refresh_rx_performance', lambda *a, **kw: {'status': 'BLOCKED'})
    result = module.update_demo_performance(SimpleNamespace(daily_root=tmp_path),
        {'status': 'READY', 'data_date': '2026-10-06', 'repair_lineage': repair_ref}, tmp_path / 'new_run', lambda *_: None)
    assert result['status'] == 'READY' and len(calls) == 1
    assert ('pending_signal_revision_path' in calls[0]) is forward_pending
    if forward_pending: assert calls[0]['pending_signal_revision_path'] == repair
    assert calls[0]['prior_verified_performance_manifest_path'] == immutable.resolve()


def acquisition_notes_pointer_fixture(paths, document, *, suffix=''):
    import hashlib
    leaf_document = json.loads(json.dumps(document))
    if suffix:
        leaf_document['notes'][0]['note_zh'] += suffix
    raw = (json.dumps(leaf_document, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    digest = hashlib.sha256(raw).hexdigest()
    owner = paths.daily_root / 'A2_today_recommendation'
    leaf = owner / 'acquisition_notes/versions' / (digest + '.json')
    leaf.parent.mkdir(parents=True, exist_ok=True)
    if leaf.exists(): assert leaf.read_bytes() == raw
    else: leaf.write_bytes(raw)
    pointer = owner / 'acquisition_notes_active.json'
    active = {'schema': 'USTQ_CURRENT_ACQUISITION_NOTES_ACTIVE_V1',
              'notes': {'path': str(leaf), 'sha256': digest}}
    pointer.write_text(json.dumps(active), encoding='utf-8')
    return pointer, leaf, active


def test_acquisition_notes_active_routes_only_immutable_ref_and_preserves_legacy(tmp_path):
    import hashlib
    paths, legacy, document, members, now = acquisition_notes_fixture(tmp_path)
    old = legacy.read_bytes()
    baseline = module.load_acquisition_notes(paths, '2026-10-02', members, now)
    assert baseline['path'] == str(legacy.resolve()) and baseline['sha256'] == hashlib.sha256(old).hexdigest()
    pointer, leaf, active = acquisition_notes_pointer_fixture(paths, document)
    audit = module.load_acquisition_notes(paths, '2026-10-02', members, now)
    assert audit['status'] == 'READY' and audit['validated_count'] == 1 and len(audit['deferred']) == 1
    assert audit['path'] == str(leaf) and audit['sha256'] == active['notes']['sha256']
    assert str(pointer) not in json.dumps(audit) and legacy.read_bytes() == old
    module._verify_nested_refs({'acquisition_notes': baseline})
    module._verify_nested_refs({'acquisition_notes': audit})


def test_acquisition_notes_pointer_switch_keeps_old_source_and_plan_refs_verifiable(tmp_path):
    paths, legacy, document, members, now = acquisition_notes_fixture(tmp_path)
    legacy_bytes = legacy.read_bytes()
    baseline = module.load_acquisition_notes(paths, '2026-10-02', members, now)
    pointer, first, _ = acquisition_notes_pointer_fixture(paths, document)
    accepted = module.load_acquisition_notes(paths, '2026-10-02', members, now)
    first_bytes = first.read_bytes()
    _, second, _ = acquisition_notes_pointer_fixture(paths, document, suffix='；新版本说明')
    current = module.load_acquisition_notes(paths, '2026-10-02', members, now)
    assert current['status'] == 'READY' and current['path'] == str(second) and first != second
    assert first.read_bytes() == first_bytes and legacy.read_bytes() == legacy_bytes
    # Original recursive verifier sees immutable documents/evidence, never the mutable pointer.
    for source_or_plan in ({'acquisition_notes': baseline}, {'source': {'acquisition_notes': accepted}},
                           {'acquisition_notes': current}):
        module._verify_nested_refs(source_or_plan)
    assert str(pointer) not in json.dumps([baseline, accepted, current])


@pytest.mark.parametrize('damage', ['schema', 'extra_field', 'missing_field', 'invalid_hash', 'hash',
    'outside', 'relative', 'wrong_name', 'owner_sibling', 'missing_leaf', 'directory_leaf',
    'pointer_directory', 'pointer_oversize', 'leaf_oversize', 'malformed', 'leaf_tamper',
    'leaf_schema', 'member_hash', 'identity', 'evidence_hash'])
def test_acquisition_notes_invalid_active_never_falls_back_to_valid_legacy(tmp_path, damage):
    paths, legacy, document, members, now = acquisition_notes_fixture(tmp_path)
    legacy_bytes = legacy.read_bytes()
    pointer, leaf, active = acquisition_notes_pointer_fixture(paths, document)
    if damage == 'schema': active['schema'] = 'UNKNOWN'
    elif damage == 'extra_field': active['fallback'] = str(legacy)
    elif damage == 'missing_field': del active['notes']['sha256']
    elif damage == 'invalid_hash': active['notes']['sha256'] = 'not-a-digest'
    elif damage == 'hash': active['notes']['sha256'] = '0' * 64
    elif damage == 'outside': active['notes']['path'] = str(paths.results_root / leaf.name)
    elif damage == 'relative': active['notes']['path'] = 'acquisition_notes/versions/' + leaf.name
    elif damage == 'wrong_name': active['notes']['path'] = str(leaf.with_name('notes.json'))
    elif damage == 'owner_sibling': active['notes']['path'] = str(leaf.parent.parent / leaf.name)
    elif damage == 'missing_leaf': leaf.unlink()
    elif damage == 'directory_leaf': leaf.unlink(); leaf.mkdir()
    elif damage == 'pointer_directory': pointer.unlink(); pointer.mkdir()
    elif damage == 'pointer_oversize': pointer.write_bytes(b' ' * (16 * 1024 + 1))
    elif damage == 'leaf_oversize': leaf.write_bytes(b' ' * (1024 * 1024 + 1))
    elif damage == 'malformed': pointer.write_text('{')
    elif damage == 'leaf_tamper': leaf.write_bytes(leaf.read_bytes() + b' ')
    elif damage in {'leaf_schema', 'member_hash', 'identity', 'evidence_hash'}:
        if damage == 'leaf_schema': document['schema'] = 'UNKNOWN'
        elif damage == 'member_hash': document['member_binding']['sha256'] = '0' * 64
        elif damage == 'identity': document['notes'][0]['security_id'] = '999999999'
        else: document['notes'][0]['evidence']['sha256'] = '0' * 64
        pointer, leaf, active = acquisition_notes_pointer_fixture(paths, document)
    if damage not in {'pointer_directory', 'pointer_oversize', 'malformed'}:
        pointer.write_text(json.dumps(active), encoding='utf-8')
    audit = module.load_acquisition_notes(paths, '2026-10-02', members, now)
    assert audit['status'] == 'INVALID' and audit['deferred'] == [] and audit['error']
    assert legacy.read_bytes() == legacy_bytes


@pytest.mark.parametrize('redirect', ['pointer', 'versions', 'leaf'])
def test_acquisition_notes_active_rejects_resolved_path_redirection(tmp_path, monkeypatch, redirect):
    paths, _, document, members, now = acquisition_notes_fixture(tmp_path)
    pointer, leaf, _ = acquisition_notes_pointer_fixture(paths, document)
    redirected = {'pointer': pointer, 'versions': leaf.parent, 'leaf': leaf}[redirect]
    original = Path.resolve
    def resolve(value, *args, **kwargs):
        if value == redirected: return paths.results_root / value.name
        return original(value, *args, **kwargs)
    monkeypatch.setattr(Path, 'resolve', resolve)
    audit = module.load_acquisition_notes(paths, '2026-10-02', members, now)
    assert audit['status'] == 'INVALID' and audit['deferred'] == []


@pytest.mark.parametrize('change', ['pointer', 'leaf'])
def test_acquisition_notes_active_refuses_change_during_validation(tmp_path, monkeypatch, change):
    paths, _, document, members, now = acquisition_notes_fixture(tmp_path)
    pointer, leaf, _ = acquisition_notes_pointer_fixture(paths, document)
    selected = pointer if change == 'pointer' else leaf
    original = Path.read_bytes
    reads = 0
    def read_bytes(value):
        nonlocal reads
        result = original(value)
        if value == selected:
            reads += 1
            if reads == 2: return result + b' '
        return result
    monkeypatch.setattr(Path, 'read_bytes', read_bytes)
    audit = module.load_acquisition_notes(paths, '2026-10-02', members, now)
    assert audit['status'] == 'INVALID' and audit['deferred'] == []
    assert audit['error'] == 'ACQUISITION_NOTES_ACTIVE_CHANGED_DURING_VALIDATION'


@pytest.mark.parametrize('target,expected', [('2026-10-06', 0), ('2026-10-07', 1)])
def test_acquisition_notes_active_wbd_preserves_original_event_date_boundary(tmp_path, target, expected):
    import hashlib
    import pandas as pd
    from datetime import datetime, timezone
    paths, _, document, members, _ = acquisition_notes_fixture(tmp_path)
    note = document['notes'][0]
    note.update(ticker='WBD', security_id='934423104', moomoo_symbol='US.WBD',
                kind='MERGER_CLOSED_TRADING_SUSPENDED', inactive_after_date='2026-10-06',
                checked_at_utc='2026-10-07T05:41:46Z')
    members = [{key: note[key] for key in ('ticker', 'security_id', 'moomoo_symbol')}]
    member = Path(document['member_binding']['path']); pd.DataFrame(members).to_parquet(member, index=False)
    document['member_binding']['sha256'] = hashlib.sha256(member.read_bytes()).hexdigest()
    evidence = Path(note['evidence']['path'])
    evidence.write_text(json.dumps({'primary_security_lifecycle_evidence': [{
        'ticker': 'WBD', 'security_id': '934423104', 'kind': note['kind'], 'event_date': '2026-10-06',
        'url': note['official_urls'][0]}]}))
    note['evidence']['sha256'] = hashlib.sha256(evidence.read_bytes()).hexdigest()
    acquisition_notes_pointer_fixture(paths, document)
    audit = module.load_acquisition_notes(paths, target, members, datetime(2026, 10, 7, 6, tzinfo=timezone.utc))
    assert audit['status'] == 'READY' and len(audit['deferred']) == expected


def test_acquisition_notes_legacy_keeps_original_resolved_path_boundary(tmp_path, monkeypatch):
    paths, legacy, document, members, now = acquisition_notes_fixture(tmp_path)
    outside = paths.results_root / 'notes_outside_daily.json'
    outside.write_bytes(legacy.read_bytes())
    original = Path.resolve
    def resolve(value, *args, **kwargs):
        if value == legacy: return outside
        return original(value, *args, **kwargs)
    monkeypatch.setattr(Path, 'resolve', resolve)
    audit = module.load_acquisition_notes(paths, '2026-10-02', members, now)
    assert audit['status'] == 'INVALID' and audit['deferred'] == []
    assert audit['error'] == 'ACQUISITION_NOTES_PATH_OR_SIZE_INVALID'


@pytest.mark.parametrize('case,code,error',[('nonzero_empty',5,'EXECUTION_CHART_WORKER_EXIT:5'),
    ('native_crash_empty',-1073741819,'EXECUTION_CHART_WORKER_EXIT:-1073741819'),
    ('setup_failed',-1,'OSError:SYNTHETIC_CONTAINMENT_FAILED'),
    ('zero_empty',0,'PERFORMANCE_WORKER_RESPONSE_MISSING'),
    ('runner_raises',None,'SYNTHETIC_BEFORE_PROCESS_RECEIPT'),
    ('explicit_blocked',0,'SYNTHETIC_INPUT_GAP')])
def test_opening_worker_process_diagnostics_preserve_exit_and_fail_closed(tmp_path,monkeypatch,case,code,error):
    from hashlib import sha256
    paths,context=_opening_response_fixture(tmp_path,monkeypatch)
    before={v['path']:sha256(Path(v['path']).read_bytes()).hexdigest()
            for v in (context['package'],context['source_report'],context['raw_manifest'])}
    calls=[]
    def runner(actual,name,argv,log):
        calls.append(argv[1]);assert argv[1]=='execution-inputs'
        log.write_text('',encoding='utf-8')
        if case=='runner_raises':raise PermissionError(error)
        if case=='explicit_blocked':
            log.write_text(json.dumps({'event':'performance_result','result':{'status':'BLOCKED','error':error}})+'\n',encoding='utf-8')
        result={'module':name,'exit_code':code,'log_path':str(log),'lifecycle':'SYNTHETIC_OWNED_PROCESS'}
        if case=='setup_failed':result['error']=error
        return result
    monkeypatch.setattr(module,'run_provider',runner)
    result=module.run_execution_charts(paths,progress=lambda *_:None)
    assert calls==['execution-inputs'] and result['status']=='BLOCKED'
    assert result['broker_action_allowed'] is False and result['inputs']['error']==error
    assert result['failed_stages']==['inputs']
    if case in {'runner_raises','explicit_blocked'}:
        assert 'worker_process' not in result['inputs']
    else:
        process=result['inputs']['worker_process']
        assert process['exit_code']==code and process['lifecycle']=='SYNTHETIC_OWNED_PROCESS'
        assert process['log_path']==result['inputs']['log_path']
        if case=='setup_failed':assert process['error']==error
    saved=next(paths.daily_root.glob('A2_today_recommendation/execution_charts/*/*/state.json'))
    assert json.loads(saved.read_text(encoding='utf-8'))==result
    assert all(sha256(Path(path).read_bytes()).hexdigest()==value for path,value in before.items())



def _benchmark_open_wiring_fixture(tmp_path,monkeypatch,*,current=False,defect=None):
    import csv
    from datetime import datetime,timezone
    from scripts.research.a2.evaluation import three_strategy_extension as extension
    paths,run,_,identities,owner,market,native=_benchmark_native_fixture(tmp_path,monkeypatch)
    paths.results_root=tmp_path/'results'
    package=paths.daily_root/'package.json';source=paths.daily_root/'source.json'
    module.save(package,{'explicit_synthetic_package':True});module.save(source,{'explicit_synthetic_source':True})
    context={'status':'READY','signal_date':'2026-10-05','execution_date':'2026-10-06',
        'as_of_utc':'2026-10-06T13:31:00+00:00','policy_id':'HGB_TOP20_RISK_R1',
        'sessions':['2026-09-29','2026-09-30','2026-10-01','2026-10-02','2026-10-05','2026-10-06'],
        'package':extension.reference(package),'source_report':extension.reference(source)}
    calls={'batches':[],'published':[],'current':current,'scopes':[]}
    def reference_status(*args):
        return {'status':'CURRENT' if calls['current'] else 'REFERENCE_OPEN_NOT_AVAILABLE',
                'available_end_date':context['execution_date'] if calls['current'] else context['signal_date'],
                'requested_execution_date':context['execution_date'],'provider_fallback_or_purchase_attempted':False}
    monkeypatch.setattr(module,'_execution_chart_reference_status',reference_status)
    def scope(*args):
        calls['scopes'].append(args)
        return {'status':'NOOP','available_end_date':('2026-10-02' if defect=='old_benchmark' else context['signal_date'])}
    monkeypatch.setattr(owner,'benchmark_native_scope',scope)
    def collect(args):
        members=list(csv.DictReader(args.universe_csv.open(encoding='utf-8')))
        calls['batches'].append({'args':args,'members':members,'observed_after':datetime.now(timezone.utc).isoformat()})
        if defect=='collector_raises':raise RuntimeError('SYNTHETIC_COLLECTOR_TERMINATED_AFTER_START')
        results=[]
        for row in members:
            if defect=='one_etf' and row['ticker']=='SPY':
                results.append({'item':row,'status':'FAILED_CURRENT_KLINE'});continue
            item={**row,'planned_start_date':args.start,'planned_end_date':args.end,'adjustment':'raw',
                  'acquisition_method':'GET_CUR_KLINE','session':'RTH'}
            path=args.work_root/'intervals'/(row['ticker']+'.csv');path.parent.mkdir(parents=True,exist_ok=True)
            path.with_suffix('.json').write_text(json.dumps({'item':item,'synthetic':True}),encoding='utf-8')
            results.append({'item':item,'status':'FETCHED_VALIDATED_INTERVAL','path':str(path),'latest_date':args.end})
        if defect=='package_changed':module.save(package,{'explicit_synthetic_package':'CHANGED'})
        return {'status':'ACQUIRED','history_request_count':0,'trade_context_opened':False,'current_kline_calls':2,'results':results}
    monkeypatch.setattr(market,'run',collect)
    monkeypatch.setattr(native,'_native_raw',lambda *args:pytest.fail('execution mode reused closed catalog'))
    def publish(actual,target,calendar,progress,*args,**kwargs):
        calls['published'].append(kwargs)
        if defect=='publisher':return {'status':'BLOCKED','error':'SYNTHETIC_ETF_OPEN_PRICE_CHANGED'}
        if not current:
            assert set(kwargs['native_inputs'])=={'QQQ','SPY'}
            assert all(v['kind']=='CURRENT_KLINE' for v in kwargs['native_inputs'].values())
            phase=kwargs['execution_open']
            assert phase['signal_date']==context['signal_date'] and phase['execution_date']==target
            assert phase['as_of_utc']>=calls['batches'][-1]['observed_after']>context['as_of_utc']
            assert calendar['as_of_utc']==phase['as_of_utc'] and calendar['target_date']==target
        else:assert kwargs=={}
        calls['current']=True
        return {'status':'READY','end_date':target,'reused':current}
    monkeypatch.setattr(owner,'refresh_demo_benchmarks',publish)
    return paths,run,context,calls


def test_benchmark_open_collector_forces_two_current_receipts_and_isolates_execution_cache(tmp_path,monkeypatch):
    paths,run,context,calls=_benchmark_open_wiring_fixture(tmp_path,monkeypatch)
    # Complete old catalog is intentionally not consulted for a following open.
    store=SimpleNamespace(metadata=lambda *a:pytest.fail('old catalog used as opening evidence'))
    scope={'status':'NEEDS_NATIVE','target_date':context['signal_date'],'bridge_start':context['sessions'][0],
        'required_dates':context['sessions'][:-1],'native_tickers':['QQQ','SPY'],
        'sessions':context['sessions'],'as_of_utc':context['as_of_utc']}
    for _ in range(2):
        inputs,audit=module.acquire_benchmark_native_inputs(paths,run,context['signal_date'],scope,store,
            progress=lambda *_:None,execution_date=context['execution_date'])
        assert audit['status']=='READY' and audit['new_current_kline_requests']==2
        assert all(x['kind']=='CURRENT_KLINE' for x in inputs.values())
    assert len(calls['batches'])==2
    first,second=[x['args'] for x in calls['batches']]
    assert first.work_root!=second.work_root
    assert all('/execution_open/2026-10-06/' in x.work_root.as_posix() for x in [first,second])
    for entry in calls['batches']:
        args=entry['args'];assert args.end=='2026-10-05' and args.start=='2026-09-29'
        assert args.adjustments==['raw'] and args.acquisition_mode=='current-kline' and args.max_retries==0
        assert [row['ticker'] for row in entry['members']]==['QQQ','SPY']


@pytest.mark.parametrize('current',[False,True])
def test_benchmark_open_helper_uses_original_publisher_and_real_completion_asof(tmp_path,monkeypatch,current):
    paths,run,context,calls=_benchmark_open_wiring_fixture(tmp_path,monkeypatch,current=current)
    before={v['path']:Path(v['path']).read_bytes() for v in [context['package'],context['source_report']]}
    result=module.refresh_execution_benchmarks(paths,context,run,progress=lambda *_:None)
    assert result['status']=='CURRENT' and result['refresh']['status']=='READY'
    assert result['provider_calls']==(0 if current else 2) and result['history_request_count']==result['trade_requests']==0
    assert len(calls['batches'])==(0 if current else 1) and len(calls['published'])==1
    assert all(Path(k).read_bytes()==v for k,v in before.items())
    if not current:
        # The aggregate itself preserves the actual after-acquisition timestamp.
        phase_path=Path(result['refresh']['acquisition_inputs']['path'])
        phase=json.loads(phase_path.read_text(encoding='utf-8'))
        assert phase['as_of_utc']==calls['published'][0]['execution_open']['as_of_utc']
        assert phase['source_report']==context['source_report'] and phase['package']==context['package']


@pytest.mark.parametrize('defect',['one_etf','publisher','old_benchmark','package_changed','before_open','calendar_missing','collector_raises'])
def test_benchmark_open_helper_failure_never_claims_current_or_changes_signal_source(tmp_path,monkeypatch,defect):
    paths,run,context,calls=_benchmark_open_wiring_fixture(tmp_path,monkeypatch,defect=defect)
    before=Path(context['source_report']['path']).read_bytes()
    if defect=='before_open':context['as_of_utc']='2026-10-06T13:29:59+00:00'
    if defect=='calendar_missing':context['sessions'].remove(context['signal_date'])
    result=module.refresh_execution_benchmarks(paths,context,run,progress=lambda *_:None)
    assert result['status'] in {'UNAVAILABLE','REFERENCE_OPEN_NOT_AVAILABLE'} and result['refresh']['status']=='BLOCKED'
    assert Path(context['source_report']['path']).read_bytes()==before
    if defect in {'one_etf','old_benchmark','package_changed','before_open','calendar_missing'}:assert not calls['published']
    if defect in {'old_benchmark','before_open','calendar_missing'}:assert not calls['batches']
    if defect=='collector_raises':assert result['provider_calls'] is None and result['history_request_count'] is None


def test_benchmark_open_current_artifact_validation_failure_is_not_current(tmp_path,monkeypatch):
    paths,run,context,calls=_benchmark_open_wiring_fixture(tmp_path,monkeypatch,current=True,defect='publisher')
    result=module.refresh_execution_benchmarks(paths,context,run,progress=lambda *_:None)
    assert result['status']=='UNAVAILABLE' and result['refresh']['error']=='SYNTHETIC_ETF_OPEN_PRICE_CHANGED'
    assert not calls['batches'] and result['provider_calls']==0


@pytest.mark.parametrize('reuse',[False,True])
def test_benchmark_open_single_owner_wiring_covers_reused_and_normal_charts(tmp_path,monkeypatch,reuse):
    from contextlib import nullcontext
    from scripts.research.a2.evaluation import hgb_policy_alignment,demo_performance,three_strategy_extension as extension
    paths,run,context,calls=_benchmark_open_wiring_fixture(tmp_path,monkeypatch)
    previous=paths.daily_root/'previous_raw.json';module.save(previous,{'synthetic':True})
    context['raw_manifest']=extension.reference(previous)
    monkeypatch.setattr(module,'single_update',lambda *_:nullcontext())
    monkeypatch.setattr(module,'_execution_chart_context',lambda *_:context)
    checks=[]
    def current(*args):checks.append(True);return reuse or len(checks)>1
    monkeypatch.setattr(module,'_execution_charts_current',current)
    monkeypatch.setattr(hgb_policy_alignment,'frozen_contract',lambda *_:({},{}))
    monkeypatch.setattr(demo_performance,'canonical_manifest',lambda *_:(previous,extension.reference(previous)))
    workers=[]
    def worker(*args):
        kind=args[2][1];workers.append(kind)
        args[3].write_text(json.dumps({'event':'performance_result','result':{'status':'READY','performance_end_date':context['execution_date']}})+'\n',encoding='utf-8')
        return {'exit_code':0}
    monkeypatch.setattr(module,'run_provider',worker)
    result=module.run_execution_charts(paths,progress=lambda *_:None)
    assert result['status']=='READY' and result['benchmark_reference']['status']=='CURRENT'
    assert len(calls['batches'])==len(calls['published'])==1 and len(calls['batches'][0]['members'])==2
    assert workers==([] if reuse else ['execution-inputs','execution-raw','execution-selected'])
    if reuse:assert result['provider_calls']==2 and result['replay_calls']==0
    assert result['broker_action_allowed'] is False


def test_benchmark_open_failed_etf_does_not_mask_normal_chart_worker_result(tmp_path,monkeypatch):
    from contextlib import nullcontext
    from scripts.research.a2.evaluation import hgb_policy_alignment,demo_performance,three_strategy_extension as extension
    paths,run,context,calls=_benchmark_open_wiring_fixture(tmp_path,monkeypatch,defect='one_etf')
    previous=paths.daily_root/'previous_raw.json';module.save(previous,{'synthetic':True});context['raw_manifest']=extension.reference(previous)
    monkeypatch.setattr(module,'single_update',lambda *_:nullcontext())
    monkeypatch.setattr(module,'_execution_chart_context',lambda *_:context)
    checks=[]
    # First check must be false; final check is true for verified normal charts.
    def current(*_):checks.append(True);return len(checks)>1
    monkeypatch.setattr(module,'_execution_charts_current',current)
    monkeypatch.setattr(hgb_policy_alignment,'frozen_contract',lambda *_:({},{}))
    monkeypatch.setattr(demo_performance,'canonical_manifest',lambda *_:(previous,extension.reference(previous)))
    def worker(*args):
        args[3].write_text(json.dumps({'event':'performance_result','result':{'status':'READY','performance_end_date':context['execution_date']}})+'\n',encoding='utf-8')
        return {'exit_code':0}
    monkeypatch.setattr(module,'run_provider',worker)
    result=module.run_execution_charts(paths,progress=lambda *_:None)
    assert result['status']=='READY' and result['benchmark_reference']['status']=='REFERENCE_OPEN_NOT_AVAILABLE'
    assert result['benchmark_reference']['refresh']['status']=='BLOCKED' and result['broker_action_allowed'] is False


def test_benchmark_open_status_retained_when_normal_open_input_worker_fails(tmp_path,monkeypatch):
    from contextlib import nullcontext
    from scripts.research.a2.evaluation import hgb_policy_alignment,three_strategy_extension as extension
    paths,run,context,calls=_benchmark_open_wiring_fixture(tmp_path,monkeypatch,defect='one_etf')
    previous=paths.daily_root/'previous_raw.json';module.save(previous,{'synthetic':True});context['raw_manifest']=extension.reference(previous)
    monkeypatch.setattr(module,'single_update',lambda *_:nullcontext())
    monkeypatch.setattr(module,'_execution_chart_context',lambda *_:context)
    monkeypatch.setattr(module,'_execution_charts_current',lambda *_:False)
    monkeypatch.setattr(hgb_policy_alignment,'frozen_contract',lambda *_:({},{}))
    def worker(*args):
        args[3].write_text('',encoding='utf-8');return {'exit_code':5}
    monkeypatch.setattr(module,'run_provider',worker)
    result=module.run_execution_charts(paths,progress=lambda *_:None)
    assert result['status']=='BLOCKED' and result['failed_stages']==['inputs']
    assert result['inputs']['error']=='EXECUTION_CHART_WORKER_EXIT:5'
    assert result['benchmark_reference']['status']=='REFERENCE_OPEN_NOT_AVAILABLE'
    assert result['benchmark_reference']['refresh']['error']=='BENCHMARK_OFFICIAL_OPEN_BOTH_ETF_RECEIPTS_REQUIRED'


# Yahoo request-scope checks use synthetic metadata and fail-mocked providers only.
def _yahoo_scope_plan():
    def row(name, *, pool=False, frequency=0, provider='ALTERNATE'):
        return dict(ticker=name, moomoo_symbol='US.'+name, in_explicit_refresh_pool=pool,
                    frequency_days=frequency, provider=provider)
    return dict(as_of_date='2025-12-05', pool_supplement_authorized=True, assignments=[
        row('CUR', pool=True), row('HIST', frequency=1), row('SUB'), row('CATALOG'),
        row('MOO', provider='MOOMOO')])


def test_yahoo_scope_preserves_original_plan_and_each_required_role():
    import copy
    plan=_yahoo_scope_plan();before=copy.deepcopy(plan)
    scope=module.alternate_acquisition_scope(plan,[{'ticker':'SUB'}])
    assert scope['allowed_tickers']==['CUR','HIST','MOO','SUB']
    assert plan==before
    assert module._validated_alternate_scope(plan,plan['as_of_date'],scope)=={'CUR','HIST','MOO','SUB'}


@pytest.mark.parametrize('name',['CUR','HIST','MOO','SUB'])
def test_yahoo_scope_cannot_drop_required_role(name):
    plan=_yahoo_scope_plan();scope=module.alternate_acquisition_scope(plan,[{'ticker':'SUB'}])
    scope['allowed_tickers'].remove(name)
    with pytest.raises(ValueError,match='SCOPE_BINDING'):
        module._validated_alternate_scope(plan,plan['as_of_date'],scope)


@pytest.mark.parametrize('change',['date','assignment','extra_key','schema','duplicate_allowed'])
def test_yahoo_scope_rejects_stale_or_mutated_explicit_binding(change):
    plan=_yahoo_scope_plan();scope=module.alternate_acquisition_scope(plan,[])
    if change=='date':scope['target_date']='2025-12-04'
    if change=='assignment':plan['assignments'][0]['moomoo_symbol']='US.OTHER'
    if change=='extra_key':scope['unbound']=True
    if change=='schema':scope['schema']='OTHER'
    if change=='duplicate_allowed':scope['allowed_tickers'].append('CUR')
    with pytest.raises(ValueError,match='SCOPE_BINDING'):
        module._validated_alternate_scope(plan,plan['as_of_date'],scope)


@pytest.mark.parametrize('change',['unknown_pool','absent_pool','missing_flag','invalid_flag','negative_frequency','duplicate','provider','unknown_subscription','invalid_subscriptions'])
def test_yahoo_scope_unknown_metadata_never_becomes_empty_permission(change):
    plan=_yahoo_scope_plan();subs=[]
    if change=='unknown_pool':plan['pool_supplement_authorized']=False
    if change=='absent_pool':plan.pop('pool_supplement_authorized')
    if change=='missing_flag':plan['assignments'][0].pop('in_explicit_refresh_pool')
    if change=='invalid_flag':plan['assignments'][0]['in_explicit_refresh_pool']=1
    if change=='negative_frequency':plan['assignments'][0]['frequency_days']=-1
    if change=='duplicate':plan['assignments'].append(dict(plan['assignments'][0]))
    if change=='provider':plan['assignments'][0]['provider']='UNKNOWN'
    if change=='unknown_subscription':subs=[{'ticker':'UNBOUND'}]
    if change=='invalid_subscriptions':subs=None
    with pytest.raises(ValueError,match='ALTERNATE_SCOPE_'):
        module.alternate_acquisition_scope(plan,subs)


def test_yahoo_scope_subscription_alias_is_original_caller_mapping():
    plan=_yahoo_scope_plan()
    scope=module.alternate_acquisition_scope(plan,[{'ticker':'OLD_SUB'}],aliases={'OLD_SUB':'SUB'})
    assert scope['subscription_tickers']==['SUB'] and 'SUB' in scope['allowed_tickers']
    with pytest.raises(ValueError,match='SUBSCRIPTION_UNBOUND'):
        module.alternate_acquisition_scope(plan,[{'ticker':'OLD_SUB'}])


@pytest.mark.parametrize('bounded',[False,True])
@pytest.mark.parametrize('native_reached',[False,True])
def test_yahoo_acquisition_filters_only_initial_alternate_and_preserves_native_fallback(tmp_path,monkeypatch,bounded,native_reached):
    import csv,copy
    from scripts.storage import refresh_market_data as market
    plan=_yahoo_scope_plan();before=copy.deepcopy(plan);calls={}
    paths=SimpleNamespace(repo_root=tmp_path,cache_root=tmp_path/'cache')
    def native(args):
        with args.universe_csv.open() as stream: calls['native']=list(csv.DictReader(stream))
        assert args.adjustments==['raw','qfq']
        return {'status':'ACQUIRED' if native_reached else 'FAILED','results':[
            {'item':{'ticker':'MOO','adjustment':'raw'},'status':'FETCHED_VALIDATED_INTERVAL','latest_date':plan['as_of_date']}
        ] if native_reached else []}
    monkeypatch.setattr(market,'run',native)
    monkeypatch.setattr(market,'read_checkpoint',lambda *a:None)
    def provider(paths,owner,args,log):
        assert owner=='scripts.storage.refresh_free_market'
        assert args[args.index('--workers')+1]=='2'
        calls['alternate']=args[args.index('--tickers')+1:-1]
        return {'status':'SYNTHETIC_NO_NETWORK'}
    monkeypatch.setattr(module,'run_provider',provider)
    scope=module.alternate_acquisition_scope(plan,[{'ticker':'SUB'}]) if bounded else None
    result=module.acquire_prices(paths,tmp_path,tmp_path,plan,'2025-01-01',plan['as_of_date'],lambda *a:None,alternate_scope=scope)
    expected={'CUR','HIST','SUB'}|({'CATALOG'} if not bounded else set())|({'MOO'} if not native_reached else set())
    assert set(calls['alternate'])==expected
    assert calls['native']==[{'ticker':'MOO','moomoo_symbol':'US.MOO'}]
    assert plan==before
    assert ('alternate_scope' in result)==bounded


@pytest.mark.parametrize('entry',['prices','pool'])
def test_yahoo_explicit_bad_scope_precedes_all_provider_construction(tmp_path,monkeypatch,entry):
    import sys,types
    from scripts.storage import refresh_market_data as market
    plan=_yahoo_scope_plan();scope=module.alternate_acquisition_scope(plan,[]);scope['target_date']='2025-12-04'
    monkeypatch.setattr(market,'run',lambda *a:pytest.fail('native provider called'))
    monkeypatch.setattr(module,'run_provider',lambda *a:pytest.fail('alternate provider called'))
    fake=types.ModuleType('scripts.storage.refresh_current_massive')
    fake.refresh_massive_current=lambda *a,**kw:pytest.fail('Massive provider called')
    monkeypatch.setitem(sys.modules,'scripts.storage.refresh_current_massive',fake)
    args=(SimpleNamespace(repo_root=tmp_path,cache_root=tmp_path/'cache'),tmp_path,tmp_path,plan,'2025-01-01',plan['as_of_date'])
    with pytest.raises(ValueError,match='SCOPE_BINDING'):
        if entry=='prices':module.acquire_prices(*args,alternate_scope=scope)
        else:module.acquire_pool_prices(*args,[],[],alternate_scope=scope)


def test_yahoo_scope_default_none_standalone_plan_remains_compatible(tmp_path,monkeypatch):
    calls=[];plan={'assignments':[{'ticker':'CATALOG','provider':'ALTERNATE'}]}
    monkeypatch.setattr(module,'run_provider',lambda paths,owner,args,log:(calls.append(args) or {}))
    result=module.acquire_prices(SimpleNamespace(cache_root=tmp_path),tmp_path,tmp_path,plan,'2025-01-01','2025-12-05',lambda *a:None)
    assert calls[0][calls[0].index('--tickers')+1:-1]==['CATALOG']
    assert 'alternate_scope' not in result


def test_yahoo_note_deferred_subscriptions_follow_original_filter_and_aliases():
    plan=_yahoo_scope_plan();subscriptions=[{'ticker':'OLD_RETIRED'},{'ticker':'SUB'}]
    aliases={'OLD_RETIRED':'RETIRED'};audit={'deferred':[{'ticker':'RETIRED'}]}
    with pytest.raises(ValueError,match='SUBSCRIPTION_UNBOUND'):
        module.alternate_acquisition_scope(plan,subscriptions,aliases=aliases)
    active,_,_=module.acquisition_note_context(subscriptions,{'records':[],'bootstrap_records':[]},[],aliases,audit)
    scope=module.alternate_acquisition_scope(plan,active,aliases=aliases)
    assert active==[{'ticker':'SUB'}]
    assert scope['subscription_tickers']==['SUB'] and 'RETIRED' not in scope['allowed_tickers']
    assert subscriptions==[{'ticker':'OLD_RETIRED'},{'ticker':'SUB'}]


def test_yahoo_catalog_only_request_is_not_daily_input(tmp_path,monkeypatch):
    plan=_yahoo_scope_plan();plan['assignments']=[row for row in plan['assignments'] if row['provider']=='ALTERNATE']
    calls=[]
    monkeypatch.setattr(module,'run_provider',lambda paths,owner,args,log:(calls.append(args[args.index('--tickers')+1:-1]) or {}))
    # The old coordinator lacks the scope factory and takes its normal path;
    # this same behavior case exposes its unnecessary CATALOG request.
    scope=(module.alternate_acquisition_scope(plan,[{'ticker':'SUB'}])
           if hasattr(module,'alternate_acquisition_scope') else None)
    module.acquire_prices(SimpleNamespace(cache_root=tmp_path),tmp_path,tmp_path,plan,'2025-01-01','2025-12-05',lambda *a:None,
        **({'alternate_scope':scope} if scope is not None else {}))
    assert set(calls[0])=={'CUR','HIST','SUB'}


# Retain the current publisher benchmark configuration, without creating new assignments.
@pytest.mark.parametrize('ticker',['QQQ','SPY'])
def test_yahoo_scope_configured_benchmarks_catalog_only(ticker):
    import copy
    plan=_yahoo_scope_plan(); row=dict(plan['assignments'][3],ticker=ticker,moomoo_symbol='US.'+ticker)
    plan['assignments'].append(row); before=copy.deepcopy(plan)
    scope=module.alternate_acquisition_scope(plan,[])
    assert ticker in scope['allowed_tickers'] and 'CATALOG' not in scope['allowed_tickers']
    assert plan==before


def test_yahoo_scope_configured_benchmarks_absent_does_not_create_assignment():
    plan=_yahoo_scope_plan(); scope=module.alternate_acquisition_scope(plan,[])
    assert not {'QQQ','SPY'}.intersection(scope['allowed_tickers'])
    assert set(scope['allowed_tickers'])=={'CUR','HIST','MOO'}


@pytest.mark.parametrize('ticker',['QQQ','SPY'])
def test_yahoo_scope_configured_benchmarks_cannot_be_removed(ticker):
    plan=_yahoo_scope_plan();plan['assignments'].append(dict(plan['assignments'][3],ticker=ticker,moomoo_symbol='US.'+ticker))
    scope=module.alternate_acquisition_scope(plan,[]);scope['allowed_tickers'].remove(ticker)
    with pytest.raises(ValueError,match='SCOPE_BINDING'):
        module._validated_alternate_scope(plan,plan['as_of_date'],scope)


def test_yahoo_scope_configured_benchmarks_moomoo_success_not_duplicated(tmp_path,monkeypatch):
    import csv,copy
    from scripts.storage import refresh_market_data as market
    plan=_yahoo_scope_plan(); plan['assignments']=[row for row in plan['assignments'] if row['ticker']!='MOO']
    plan['assignments'].extend([dict(plan['assignments'][3],ticker='QQQ',moomoo_symbol='US.QQQ',provider='MOOMOO'),dict(plan['assignments'][3],ticker='SPY',moomoo_symbol='US.SPY')])
    before=copy.deepcopy(plan); calls={}
    def native(args):
        with args.universe_csv.open() as stream:calls['native']=list(csv.DictReader(stream))
        return {'status':'ACQUIRED','results':[{'item':{'ticker':'QQQ','adjustment':'raw'},'status':'FETCHED_VALIDATED_INTERVAL','latest_date':plan['as_of_date']}]}
    monkeypatch.setattr(market,'run',native);monkeypatch.setattr(market,'read_checkpoint',lambda *a:None)
    def alternate(paths,owner,args,log):
        assert owner=='scripts.storage.refresh_free_market'
        calls['alternate']=args[args.index('--tickers')+1:-1];return {}
    monkeypatch.setattr(module,'run_provider',alternate)
    scope=module.alternate_acquisition_scope(plan,[{'ticker':'SUB'}])
    module.acquire_prices(SimpleNamespace(repo_root=tmp_path,cache_root=tmp_path/'cache'),tmp_path,tmp_path,plan,'2025-01-01',plan['as_of_date'],lambda *a:None,alternate_scope=scope)
    assert calls['native']==[{'ticker':'QQQ','moomoo_symbol':'US.QQQ'}]
    assert set(calls['alternate'])=={'CUR','HIST','SUB','SPY'} and plan==before



def _compact_synthetic_cli_result(tmp_path, *, completion='READY', recovered=False):
    import hashlib
    original = tmp_path / 'original' / 'report.json'; original.parent.mkdir()
    result = {'status': 'READY', 'phase': 'COMPLETED', 'run_id': 'synthetic',
        'data_date': '2026-10-08', 'generated_at': '2026-10-09T00:00:00+00:00',
        'model_id': 'A2_HGB', 'model_sha256': 'a' * 64, 'message': 'Synthetic daily output',
        'report_path': str(original), 'broker_action_allowed': False,
        'rows': [{'rank': index + 1, 'ticker': f'T{index:02}', 'score': index / 100.,
                  'source': 'frozen', 'feature_inputs': ['not-terminal'] * 30} for index in range(20)],
        'coverage': {'eligible_count': 620, 'mapped_count': 635, 'excluded_count': 15, 'large_details': ['excluded'] * 1000},
        'acquisitions': {'moomoo': {'status': 'COMPLETE', 'results': [{'large_raw': 'raw'}] * 2000},
            'alternate': {'status': 'COMPLETE', 'attempted_symbols': 352, 'target_reached_symbols': 352},
            'massive': {'selected_tickers': 25, 'target_reached_tickers': ['A', 'B'], 'issues': ['ONE_GAP'],
                        'large_rows': ['not-terminal'] * 2000}},
        'other_data': {'status': 'PARTIAL', 'results': ['not-terminal'] * 1000},
        'benchmark_update': {'status': 'READY', 'available_end_date': '2026-10-08'},
        'performance_update': {'status': 'READY', 'run_id': 'synthetic_raw', 'ranking_end_date': '2026-10-08',
            'performance_end_date': '2026-10-08', 'report_path': str(tmp_path / 'raw_manifest.json')},
        'selected_strategies_update': {'status': 'PARTIAL' if completion == 'PARTIAL' else 'READY',
            'policy_id': 'RAW_TOP20_FROZEN_LEGACY', 'report_path': str(tmp_path / 'package.json'),
            'performance_end_date': '2026-10-07' if completion == 'PARTIAL' else '2026-10-08',
            'error': 'SYNTHETIC_PRICE_GAP' if completion == 'PARTIAL' else '',
            'strategies': {name: {'status': 'READY', 'signal_date': '2026-10-08', 'target_rows': ['not-terminal'] * 1000}
                           for name in ('HGB_DIAG_5', 'HGB_FACTOR_5')}},
        'completion': {'schema': 'A2_DAILY_COMPLETION_V1', 'status': completion, 'target_date': '2026-10-08',
            'required_stages': {'recommendation': True, 'raw_research': True,
                'hgb_targets_and_charts': completion == 'READY', 'benchmarks': True},
            'limitations': {'coverage': {'eligible_count': 620, 'mapped_count': 635, 'excluded_count': 15},
                'rx': {'status': 'BLOCKED', 'reason': 'INDEPENDENT_RX_INPUT_MISSING'}}},
        'accepted_source': {'path': str(tmp_path / 'recommendation_source.json'), 'sha256': 'b' * 64},
        'catalog_before': {'payload': 'not-terminal' * 50000}, 'lineage': ['not-terminal'] * 10000}
    original.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    if recovered:
        recovery = tmp_path / 'recovery' / 'report.json'; recovery.parent.mkdir()
        result['recovery'] = {'action': 'RESUME_ACCEPTED_INPUTS', 'report_path': str(recovery),
            'acquisition_calls': 0, 'inference_calls': 0, 'broker_calls': 0}
        recovery.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    return result


@pytest.mark.parametrize('recovered', [False, True])
@pytest.mark.parametrize('completion,expected_exit', [('READY', 0), ('PARTIAL', 2)])
def test_compact_cli_preserves_full_reports_source_identity_and_delivery_exit(tmp_path, monkeypatch, capsys, recovered, completion, expected_exit):
    from copy import deepcopy
    from scripts.common import storage_paths
    result = _compact_synthetic_cli_result(tmp_path, completion=completion, recovered=recovered)
    snapshot = deepcopy(result); original = Path(result['report_path']); original_bytes = original.read_bytes()
    current = Path(result.get('recovery', {}).get('report_path', result['report_path'])); current_bytes = current.read_bytes()
    paths = SimpleNamespace(daily_root=tmp_path); monkeypatch.setattr(storage_paths, 'resolve', lambda: paths)
    calls = []
    monkeypatch.setattr(module, 'run_update', lambda *a, **kw: (calls.append((a, kw)) or result))
    assert module.main(['--execute', '--compact-output']) == expected_exit
    raw = capsys.readouterr().out; response = json.loads(raw)
    assert response['event'] == 'result'; summary = response['result']
    assert summary['compact_output'] is True and summary['status'] == 'READY'
    assert summary['completion']['status'] == completion
    assert summary['completion']['required_stages'] == result['completion']['required_stages']
    assert summary['completion']['limitations'] == result['completion']['limitations']
    assert summary['model_sha256'] == result['model_sha256']
    assert summary['report_path'] == str(original) and summary['full_report_ref']['path'] == str(current.resolve())
    import hashlib
    assert summary['full_report_ref']['sha256'] == hashlib.sha256(current_bytes).hexdigest()
    assert summary['accepted_source'] == result['accepted_source']
    assert summary['row_count'] == 20 and len(summary['rows']) == 20
    assert all(set(row) == {'rank', 'ticker', 'score', 'source'} for row in summary['rows'])
    assert 'catalog_before' not in summary and 'lineage' not in summary
    assert 'results' not in summary['acquisitions']['moomoo']
    assert summary['acquisitions']['massive']['target_reached_count'] == 2
    assert summary['acquisitions']['massive']['issue_count'] == 1
    assert len(raw.encode('utf-8')) < 16000 and len(raw) < len(json.dumps(result)) / 10
    assert result == snapshot and original.read_bytes() == original_bytes and current.read_bytes() == current_bytes
    assert calls == [((paths, True), {})]


@pytest.mark.parametrize('argv,execute,forward', [([], False, {}), (['--execute', '--refresh-data'], True, {'refresh_data': True}),
    (['--execute', '--requalify-inputs'], True, {'requalify_inputs': True})])
def test_compact_optional_flag_forwards_only_original_daily_actions(monkeypatch, capsys, argv, execute, forward):
    from scripts.common import storage_paths
    paths = SimpleNamespace(); monkeypatch.setattr(storage_paths, 'resolve', lambda: paths)
    calls = []; result = {'status': 'PLANNED' if not execute else 'READY', 'completion': {'status': 'READY'}}
    monkeypatch.setattr(module, 'run_update', lambda *a, **kw: (calls.append((a, kw)) or result))
    assert module.main([*argv, '--compact-output']) == 0
    assert calls == [((paths, execute), forward)]
    assert json.loads(capsys.readouterr().out)['result']['compact_output'] is True


@pytest.mark.parametrize('status,completion,expected_exit', [('READY', 'PARTIAL', 2), ('READY', 'READY', 0),
    ('WAITING_DATA', 'PARTIAL', 2), ('BLOCKED', 'PARTIAL', 2), ('PLANNED', 'READY', 0)])
def test_compact_default_output_remains_exact_full_result_without_flag(monkeypatch, capsys, status, completion, expected_exit):
    from scripts.common import storage_paths
    monkeypatch.setattr(storage_paths, 'resolve', lambda: SimpleNamespace())
    result = {'status': status, 'completion': {'status': completion}, 'rows': [{'ticker': 'A', 'full': 'retained'}],
        'catalog_before': {'unknown': ['kept']}, 'message': 'Original full protocol'}
    monkeypatch.setattr(module, 'run_update', lambda *a, **k: result)
    monkeypatch.setattr(module, '_compact_terminal_result', lambda *a: pytest.fail('default touched compact projection'))
    assert module.main(['--execute']) == expected_exit
    assert json.loads(capsys.readouterr().out) == {'event': 'result', 'result': result}


@pytest.mark.parametrize('mode', ['private', 'opening'])
def test_compact_internal_worker_and_opening_protocols_stay_exact(monkeypatch, capsys, mode):
    from scripts.common import storage_paths
    monkeypatch.setattr(storage_paths, 'resolve', lambda: SimpleNamespace())
    result = {'status': 'READY', 'full_state': {'kept': [1, 2, 3]}, 'signal_date': '2026-10-07', 'execution_date': '2026-10-08'}
    monkeypatch.setattr(module, '_compact_terminal_result', lambda *a: pytest.fail('internal protocol compacted'))
    monkeypatch.setattr(module, 'run_update', lambda *a, **k: pytest.fail('internal branch called daily update'))
    if mode == 'private':
        monkeypatch.setattr(module, '_performance_worker', lambda *a: result)
        args = ['--performance-worker', 'raw', '--source-report', 'synthetic.json', '--source-sha256', 'a' * 64]
        event = 'performance_result'
    else:
        monkeypatch.setattr(module, 'run_execution_charts', lambda *a: result)
        args = ['--execution-charts']; event = 'result'
    assert module.main([*args, '--compact-output']) == 0
    assert json.loads(capsys.readouterr().out) == {'event': event, 'result': result}


def test_compact_missing_recovery_report_does_not_silently_bind_stale_report(tmp_path):
    result = _compact_synthetic_cli_result(tmp_path, recovered=True)
    Path(result['recovery']['report_path']).unlink()
    summary = module._compact_terminal_result(result)
    assert 'full_report_ref' not in summary and summary['full_report_ref_error']
    assert summary['report_path'] == result['report_path']
    assert summary['recovery']['report_path'] == result['recovery']['report_path']
    assert summary['status'] == result['status'] and summary['completion']['status'] == result['completion']['status']


@pytest.mark.parametrize('none_field', ['selected_strategies_update', 'completion', 'coverage', 'acquisitions', 'other_data'])
def test_compact_nullable_optional_stages_do_not_change_failure_semantics(none_field):
    result = {'status': 'BLOCKED', 'error': 'SYNTHETIC_FAILURE', none_field: None}
    summary = module._compact_terminal_result(result)
    assert summary['status'] == 'BLOCKED' and summary['error'] == 'SYNTHETIC_FAILURE'
    assert summary.get('completion', {}).get('status') != 'READY'


def test_compact_unknown_large_payload_is_not_traversed_or_reinterpreted():
    class Poison:
        def __iter__(self): raise AssertionError('not a terminal field')
        def __str__(self): raise AssertionError('not a terminal field')
    result = {'status': 'BLOCKED', 'catalog_before': Poison(), 'lineage': Poison(),
        'completion': {'status': 'PARTIAL', 'required_stages': {'recommendation': False},
                       'limitations': {'rx': {'status': 'BLOCKED', 'reason': 'ORIGINAL_REASON'}}}}
    summary = module._compact_terminal_result(result)
    assert summary['completion']['status'] == 'PARTIAL'
    assert summary['completion']['required_stages']['recommendation'] is False
    assert summary['completion']['limitations']['rx']['reason'] == 'ORIGINAL_REASON'
    json.dumps(summary, allow_nan=False)


@pytest.mark.parametrize('compact,expected', [(False, (1, 2)), (True, (3, 4))])
def test_compact_ps_massive_count_compatibility_uses_only_pure_expressions(tmp_path, compact, expected):
    import re,shutil,subprocess
    shell = shutil.which('pwsh') or shutil.which('powershell')
    if not shell: pytest.skip('PowerShell unavailable for count-only synthetic check')
    launch = (SOURCE.parents[1] / '更新今日推荐.ps1').read_text(encoding='utf-8-sig')
    reached = next(line.strip() for line in launch.splitlines() if line.strip().startswith('$reached ='))
    missing = next(line.strip() for line in launch.splitlines() if line.strip().startswith('$missing ='))
    massive = {'target_reached_tickers': ['A', '', None], 'issues': ['X', 'Y']}
    if compact: massive.update(target_reached_count=3, issue_count=4)
    payload = json.dumps(massive).replace("'", "''")
    code = f"$massive = '{payload}' | ConvertFrom-Json; {reached}; {missing}; @($reached,$missing) | ConvertTo-Json -Compress"
    process = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-Command', code], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
    assert process.returncode == 0, process.stderr
    assert tuple(json.loads(process.stdout)) == expected



@pytest.mark.parametrize('field', ['massive', 'other_data'])
def test_compact_explicit_null_preserves_original_no_section_semantics(field):
    result = {'status': 'BLOCKED', 'completion': {'status': 'PARTIAL'}}
    if field == 'massive': result['acquisitions'] = {'massive': None}
    else: result['other_data'] = None
    summary = module._compact_terminal_result(result)
    assert (summary['acquisitions']['massive'] if field == 'massive' else summary['other_data']) is None
    assert json.loads(json.dumps(summary)) == summary
    assert summary['status'] == 'BLOCKED' and summary['completion']['status'] == 'PARTIAL'


@pytest.fixture
def selected_error_synthetic_case(tmp_path, monkeypatch):
    from copy import deepcopy
    from scripts.research.a2.portfolio import selected_hgb
    from scripts.research.a2.evaluation import selected_performance_update as owner
    output = tmp_path/'selected'/'latest.json'
    monkeypatch.setenv('USTQ_SELECTED_HGB_PACKAGE', str(output))
    paths = SimpleNamespace(daily_root=tmp_path)
    result = {'status': 'READY', 'data_date': '2025-09-24', 'rows': [{'ticker': 'SYNTHETIC'}]}
    package = {'strategies': {sid: {'application': {'status': 'READY', 'signal_date': '2025-09-24'}}
                              for sid in selected_hgb.STRATEGY_IDS},
               'performance_period': {'end': '2025-09-24'},
               'performance_extension': {'status': 'READY', 'requested_end_date': '2025-09-24', 'blocked_next': None}}
    monkeypatch.setattr(selected_hgb, 'active_policy', lambda _: ('LEGACY_FROZEN_TEST', output))
    monkeypatch.setattr(selected_hgb, 'build_package', lambda *a, **kw: package)
    state = {'refresh_calls': [], 'fallback_calls': []}
    def run(primary=None, fallback=None):
        def refresh(*args, **kwargs):
            state['refresh_calls'].append((args, kwargs))
            if primary is not None: raise primary
            return package
        def publish(*args, **kwargs):
            state['fallback_calls'].append((args, kwargs))
            if fallback is not None: raise fallback
        monkeypatch.setattr(owner, 'refresh_selected_performance', refresh)
        monkeypatch.setattr(owner, 'publish_current_preserving_replay', publish)
        before_result, before_package = deepcopy(result), deepcopy(package)
        answer = module.update_selected_strategies(paths, result, tmp_path, progress=lambda _: None)
        assert result == before_result and package == before_package
        return answer
    return SimpleNamespace(run=run, state=state, result=result, package=package,
                           paths=paths, output=output, selected=selected_hgb, owner=owner)


def test_selected_error_context_dual_failure_preserves_primary_guard(selected_error_synthetic_case):
    case = selected_error_synthetic_case
    answer = case.run(ValueError('PRIMARY_EXECUTED_PREFIX_CHANGED'), RuntimeError('FALLBACK_SAME_SIGNAL_CHANGED'))
    assert answer == {'status': 'BLOCKED', 'error': 'PRIMARY_EXECUTED_PREFIX_CHANGED',
                      'primary_error': 'PRIMARY_EXECUTED_PREFIX_CHANGED',
                      'fallback_error': 'FALLBACK_SAME_SIGNAL_CHANGED'}
    assert len(case.state['refresh_calls']) == len(case.state['fallback_calls']) == 1
    args, kwargs = case.state['fallback_calls'][0]
    assert args == (case.package, case.output.resolve()) and kwargs == {'paths': case.paths}


def test_selected_error_context_successful_fallback_still_reports_primary_failure(selected_error_synthetic_case):
    case = selected_error_synthetic_case
    answer = case.run(ValueError('PRIMARY_PRICE_QUALIFICATION_FAILED'))
    assert answer == {'status': 'BLOCKED', 'error': 'PRIMARY_PRICE_QUALIFICATION_FAILED',
                      'primary_error': 'PRIMARY_PRICE_QUALIFICATION_FAILED'}
    assert len(case.state['fallback_calls']) == 1


def test_selected_error_context_success_does_not_create_error_fields_or_call_fallback(selected_error_synthetic_case):
    case = selected_error_synthetic_case
    answer = case.run()
    assert answer['status'] == 'READY' and answer['report_path'] == str(case.output.resolve())
    assert 'error' not in answer and 'primary_error' not in answer and 'fallback_error' not in answer
    assert case.state['fallback_calls'] == []


def test_selected_error_context_nonready_recommendation_remains_skipped(selected_error_synthetic_case):
    case = selected_error_synthetic_case; case.result['status'] = 'BLOCKED'
    assert case.run() == {'status': 'SKIPPED', 'reason': 'RECOMMENDATION_NOT_READY'}
    assert case.state['refresh_calls'] == case.state['fallback_calls'] == []


@pytest.mark.parametrize('stage_key', ['selected_strategies_update', 'selected'])
def test_selected_error_context_compact_stage_retains_both_failures(stage_key):
    original = {'status': 'READY', stage_key: {'status': 'BLOCKED', 'error': 'PRIMARY_GUARD',
                'primary_error': 'PRIMARY_GUARD', 'fallback_error': 'FALLBACK_GUARD'},
                'completion': {'status': 'PARTIAL'}}
    summary = module._compact_terminal_result(original)
    assert summary[stage_key] == original[stage_key]
    assert summary['completion']['status'] == 'PARTIAL'


def test_selected_error_context_compact_long_errors_are_bounded_and_full_context_stays_exact():
    primary, fallback = 'PRIMARY_'+'x'*5000, 'FALLBACK_'+'y'*5000
    stage = {'status': 'BLOCKED', 'error': primary, 'primary_error': primary, 'fallback_error': fallback}
    original = {'status': 'READY', 'selected_strategies_update': stage, 'completion': {'status': 'PARTIAL'}}
    summary = module._compact_terminal_result(original)['selected_strategies_update']
    for key in ('error', 'primary_error', 'fallback_error'):
        assert len(summary[key]) < 2200 and '[terminal shortened; see full_report_ref]' in summary[key]
    assert original['selected_strategies_update'] == stage
    assert stage['primary_error'] == primary and stage['fallback_error'] == fallback


@pytest.mark.parametrize('compact', [False, True])
def test_selected_error_context_cli_failure_cannot_become_success(monkeypatch, capsys, compact):
    from scripts.common import storage_paths
    monkeypatch.setattr(storage_paths, 'resolve', lambda: SimpleNamespace())
    stage = {'status': 'BLOCKED', 'error': 'PRIMARY_GUARD', 'primary_error': 'PRIMARY_GUARD',
             'fallback_error': 'FALLBACK_GUARD'}
    result = {'status': 'READY', 'selected_strategies_update': stage, 'completion': {'status': 'PARTIAL'}}
    monkeypatch.setattr(module, 'run_update', lambda *a, **kw: result)
    assert module.main(['--execute', *(['--compact-output'] if compact else [])]) == 2
    returned = json.loads(capsys.readouterr().out)['result']
    assert returned['selected_strategies_update'] == stage
    assert returned['completion']['status'] == 'PARTIAL'


def test_selected_error_context_direct_policy_failure_remains_original_shape(selected_error_synthetic_case, monkeypatch):
    from scripts.research.a2.evaluation import hgb_policy_alignment
    case = selected_error_synthetic_case
    monkeypatch.setattr(case.selected, 'active_policy', lambda _: (case.selected.DIRECT_POLICY, case.output))
    def reject(*args, **kwargs): raise ValueError('DIRECT_ORIGINAL_GUARD')
    monkeypatch.setattr(hgb_policy_alignment, 'refresh_direct', reject)
    assert case.run() == {'status': 'BLOCKED', 'error': 'DIRECT_ORIGINAL_GUARD'}
    assert case.state['refresh_calls'] == case.state['fallback_calls'] == []


def test_selected_error_context_cancellation_is_not_swallowed(selected_error_synthetic_case):
    case = selected_error_synthetic_case
    with pytest.raises(KeyboardInterrupt): case.run(KeyboardInterrupt())
    assert len(case.state['refresh_calls']) == 1 and case.state['fallback_calls'] == []



def test_selected_error_context_long_dual_errors_keep_original_worker_protocol(selected_error_synthetic_case, tmp_path):
    primary = 'PRIMARY_'+('p'*(600*1024)); fallback = 'FALLBACK_'+('f'*(600*1024))
    answer = selected_error_synthetic_case.run(ValueError(primary), ValueError(fallback))
    assert answer['status'] == 'BLOCKED' and answer['error'] == primary
    log = tmp_path/'synthetic_worker.log'
    log.write_text(json.dumps({'event': 'performance_result', 'result': answer})+'\n', encoding='utf-8')
    assert module.read_worker_result(log) == answer


def test_selected_error_context_only_new_diagnostics_bound_and_explicitly_marked(selected_error_synthetic_case):
    primary = 'PRIMARY_'+('p'*5000); fallback = 'FALLBACK_'+('f'*5000)
    answer = selected_error_synthetic_case.run(ValueError(primary), ValueError(fallback))
    assert answer['status'] == 'BLOCKED' and answer['error'] == primary
    for name, original in (('primary_error', primary), ('fallback_error', fallback)):
        marker = ' [diagnostic shortened]'
        assert answer[name] == original[:2048-len(marker)]+marker
        assert len(answer[name]) <= 2048 and 'full_report_ref' not in answer[name]
        compact = module._compact_terminal_result({'status': 'READY', 'selected_strategies_update': answer})
        assert compact['selected_strategies_update'][name] == answer[name]


# This coordinator fixture supplies only small synthetic metadata and fake owners.
# Original scope/identity/CA algorithms remain covered by their existing owner tests.
@pytest.fixture
def main_ca_prepare(monkeypatch, tmp_path):
    from contextlib import contextmanager
    from copy import deepcopy
    import hashlib
    import sys
    from types import ModuleType
    from scripts.common import storage_paths

    owner = ModuleType('scripts.research.a2.evaluation.consensus_paper_performance')
    consumer = ModuleType('scripts.research.a2.inference.consensus_paper')
    prices = ModuleType('scripts.daily_recommendation_prices')
    for fake in (owner, consumer, prices):
        monkeypatch.setitem(sys.modules, fake.__name__, fake)
    paths = SimpleNamespace(daily_root=tmp_path / 'daily')
    target = '2026-10-15'; calls = []; stable = []
    def ref(path):
        path = Path(path).resolve()
        return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    def artifact(name, value):
        path = tmp_path / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
        return ref(path)
    pool = artifact('pool.json', {'tickers': ['LIVE']})
    publication = artifact('publication.json', {'synthetic': 'publication'})
    capture = artifact('capture.json', {'synthetic': 'capture'})
    report = artifact('report.json', {'synthetic': 'accepted-source binding'})
    accepted = artifact('accepted.json', {'synthetic': 'accepted-input identity'})
    market = artifact('market.json', {'tickers': ['LIVE', 'RETIRED', 'UNRANKED']})
    stable.extend((pool, publication, capture, report, accepted, market))
    document = {'source_bundle_ref': accepted, 'flags_ref': accepted}
    calendar = {'target_session': target, 'tail_sessions': ['2026-10-09', target]}
    preflight = {'end': target, 'publication_ref': publication, 'baselines': {'fixed': accepted},
        'originals': {'RIDGE': {'inference': {'market_source': {'bars_ref': market}}}}}
    state = SimpleNamespace(paths=paths, target=target, calls=calls, pool=pool, stable=stable,
        refs={}, locator_refs={}, need_ca=True, typed='none', drift=False, locked=False,
        original_domain={'LIVE', 'RETIRED', 'UNRANKED'}, artifact=artifact, reference=ref)
    def need(value, reason):
        if not value: raise ValueError(reason)
    def binding(*args, **kwargs):
        calls.append(('binding', kwargs['target_session']))
        need(kwargs['target_session'] == target and kwargs['publication_ref'] == publication
             and kwargs['capture_ref'] == capture and kwargs['daily_report_ref'] == report, 'BINDING_CHANGED')
        for value in stable:
            need(ref(value['path']) == value, 'PAPER_EXTENSION_REFERENCE_CHANGED')
        return {'synthetic': 'exact-current-binding'}, deepcopy(calendar)
    def resolve(*args, **kwargs):
        binding(*args, **kwargs)
        day = kwargs['target_session']; calls.append(('resolve', day))
        return {'locator_ref': state.locator_refs.get(day), 'ca_receipt_refs': list(state.refs.get(day, []))}
    def register(*args, **kwargs):
        assert not state.locked, 'original register must acquire its own daily lock'
        binding(*args, **kwargs); calls.append(('register', kwargs['target_session']))
        day = kwargs['target_session']; state.refs[day] = list(kwargs['ca_receipt_refs'])
        state.locator_refs[day] = artifact(day + '/supplemental_refs.json', {'refs': state.refs[day]})
        return {'locator_ref': state.locator_refs[day], 'ca_receipt_refs': state.refs[day]}
    def project(value, columns, date_column, first, last):
        assert value == market and columns == ['ticker'] and date_column == 'trade_date'
        assert (first, last) == (owner.START, owner.PREFIX_END)
        calls.append(('domain', tuple(columns)))
        class Tickers:
            def astype(self, kind):
                assert kind is str
                return sorted(state.original_domain)
        return SimpleNamespace(ticker=Tickers())
    def qualify(*args, **kwargs):
        assert state.locked
        assert kwargs['document'] == document and kwargs['baselines'] == preflight['baselines']
        assert kwargs['domain'] == state.original_domain and kwargs['calendar_qualification'] == calendar
        refs = kwargs['ca_receipt_refs']; calls.append(('qualify', deepcopy(kwargs)))
        covered = {code for value in refs for code in json.loads(Path(value['path']).read_text())['codes']}
        missing = ['US.CARRY'] if state.need_ca and 'US.CARRY' not in covered else []
        terms = {'US.SYNTHETIC': ['2026-10-14']} if state.typed == 'existing' or (state.typed == 'new' and covered) else {}
        ca = {'status': 'BLOCKED' if missing or terms else 'READY', 'missing_codes': missing,
            'typed_event_terms_required': terms}
        return object(), {'status': ca['status'], 'missing_raw_dates': {}, 'ca_qualification': ca}
    def refresh(received_paths, members, work, day, progress=None):
        assert state.locked and received_paths is paths and day == target
        assert [row['moomoo_symbol'] for row in members] == ['US.CARRY']
        calls.append(('fetch', deepcopy(members)))
        receipt = artifact(str(work.relative_to(paths.daily_root)) + '/rehab_receipt.json',
            {'status': 'READY', 'codes': ['US.CARRY'], 'target_date': day})
        if state.drift:
            Path(accepted['path']).write_text('{"synthetic":"changed input"}', encoding='utf-8')
        return {'status': 'READY', 'history_requests': 0, 'trade_requests': 0,
            'results': [{'code': 'US.CARRY', 'status': 'PASS'}], 'receipt_path': receipt['path'], 'receipt_sha256': receipt['sha256']}
    @contextmanager
    def lock(root):
        assert root == paths.daily_root / 'A2_today_recommendation' and not state.locked
        state.locked = True
        try: yield
        finally: state.locked = False
    owner.IDS = ('ELASTIC', 'RIDGE', 'R7'); owner.START = '2026-01-02'; owner.PREFIX_END = '2026-10-08'
    owner.need = need; owner.reference = ref; owner.canonical = lambda x: json.dumps(x, sort_keys=True)
    owner.completed_calendar = lambda *a: deepcopy(calendar)
    owner.already_current = lambda *a, **k: None
    owner.resolve_current_capture = lambda *a: deepcopy(capture)
    owner.metadata_preflight = lambda *a, **k: deepcopy(preflight)
    owner.check_resources = lambda *a, **k: pytest.fail('source-only CA preparation added a model/replay resource floor')
    owner._tail_proof_chain = lambda *a: calls.append(('chain',))
    owner._current_quote_source = lambda *a: {'report_ref': deepcopy(report)}
    owner._ca_locator_origin = binding; owner.resolve_supplemental_ca_receipts = resolve
    owner.register_supplemental_ca_receipts = register; owner.qualify_current_tail = qualify
    # Reaching any model/authority/replay path fails this fixture immediately.
    owner._original_authority = owner.original_runtime_custody = owner.qualified_inputs = lambda *a, **k: pytest.fail('model/authority/replay owner called')
    consumer.load_publication = lambda *a: (deepcopy(document), deepcopy(publication))
    consumer.bounded_frame = project; prices.refresh_rehab = refresh
    monkeypatch.setattr(module, 'single_update', lock)
    def output_guard(path, *, kind, paths):
        assert kind == 'daily' and path.is_relative_to(state.paths.daily_root)
    monkeypatch.setattr(storage_paths, 'assert_safe_output_path', output_guard)
    monkeypatch.setattr(storage_paths, 'resolve', lambda: paths)
    for name in ('run_update', 'acquire_prices', 'run_execution_charts'):
        monkeypatch.setattr(module, name, lambda *a, **k: pytest.fail('unrelated daily/pool/history action called'))
    return state


def test_prepare_main_ca_retired_carry_uses_original_scope_not_current_pool(main_ca_prepare):
    state = main_ca_prepare
    before = {value['path']: Path(value['path']).read_bytes() for value in state.stable}
    result = module.prepare_main_ca(state.paths, state.target, progress=lambda _: None)
    assert result['status'] == 'READY' and result['reason'] == 'SOURCE_CA_READY_NOT_MAIN_ADMISSION'
    assert result['rehab_requests'] == 1 and result['main_qualification_ready'] is False
    assert [value[1] for value in state.calls if value[0] == 'fetch'] == [[{'moomoo_symbol': 'US.CARRY'}]]
    assert len([value for value in state.calls if value[0] == 'qualify']) == 2
    assert {name: Path(name).read_bytes() for name in before} == before


def test_prepare_main_ca_current_receipt_reuse_has_zero_queries(main_ca_prepare):
    state = main_ca_prepare
    receipt = state.artifact('existing_current.json', {'codes': ['US.CARRY']})
    state.refs[state.target] = [receipt]
    state.locator_refs[state.target] = state.artifact('existing_locator.json', {'synthetic': 'current'})
    before = Path(receipt['path']).read_bytes()
    result = module.prepare_main_ca(state.paths, state.target)
    assert result['status'] == 'READY' and result['rehab_requests'] == 0
    assert result['locator_ref'] == state.locator_refs[state.target]
    assert len([value for value in state.calls if value[0] == 'binding']) == 1
    assert not [value for value in state.calls if value[0] in ('fetch', 'register')]
    assert Path(receipt['path']).read_bytes() == before


def test_prepare_main_ca_prior_day_locator_is_never_inherited(main_ca_prepare):
    state = main_ca_prepare; old_day = '2026-10-13'
    old = state.artifact('old_receipt.json', {'codes': ['US.CARRY']})
    state.refs[old_day] = [old]; state.locator_refs[old_day] = state.artifact('old_locator.json', {'refs': [old]})
    before = {value['path']: Path(value['path']).read_bytes() for value in (old, state.locator_refs[old_day])}
    result = module.prepare_main_ca(state.paths, state.target)
    assert result['status'] == 'READY' and result['rehab_requests'] == 1
    assert all(value[1] == state.target for value in state.calls if value[0] in ('resolve', 'register'))
    assert old not in state.refs[state.target]
    assert {name: Path(name).read_bytes() for name in before} == before


def test_prepare_main_ca_source_drift_after_fetch_rejects_locator_publication(main_ca_prepare):
    state = main_ca_prepare; state.drift = True
    with pytest.raises(ValueError, match='PAPER_EXTENSION_REFERENCE_CHANGED'):
        module.prepare_main_ca(state.paths, state.target)
    assert len([value for value in state.calls if value[0] == 'fetch']) == 1
    assert state.target not in state.refs and state.target not in state.locator_refs


@pytest.mark.parametrize('when', ['existing', 'new'])
def test_prepare_main_ca_typed_terms_remain_blocked_without_models_or_replay(main_ca_prepare, when):
    state = main_ca_prepare; state.typed = when
    result = module.prepare_main_ca(state.paths, state.target)
    assert result['status'] == 'SOURCE_CA_TERMS_BLOCKED'
    assert result['reason'].startswith('PAPER_EXTENSION_IN_SCOPE_NEW_CA_TERMS_REQUIRED:')
    assert result['rehab_requests'] == (0 if when == 'existing' else 1)
    assert result['models_loaded'] == result['account_replays'] == result['model_fit_calls'] == 0
    assert result['main_qualification_ready'] is result['broker_action_allowed'] is False


def test_prepare_main_ca_explicit_cli_preserves_pool_and_rejects_other_actions(main_ca_prepare, capsys):
    state = main_ca_prepare; state.need_ca = False
    pool_bytes = Path(state.pool['path']).read_bytes()
    assert module.main(['--prepare-main-ca', '--expected-signal-date', state.target]) == 0
    result = json.loads(capsys.readouterr().out)['result']
    assert result['action'] == 'PREPARE_MAIN_CA' and result['rehab_requests'] == 0
    assert result['main_qualification_ready'] is False
    for extra in (['--execute'], ['--execution-charts'], ['--refresh-data'], ['--requalify-inputs'],
                  ['--performance-worker', 'raw'], ['--source-report', 'synthetic.json']):
        with pytest.raises(SystemExit):
            module.main(['--prepare-main-ca', '--expected-signal-date', state.target, *extra])
    with pytest.raises(SystemExit): module.main(['--prepare-main-ca'])
    with pytest.raises(SystemExit): module.main(['--expected-signal-date', state.target])
    assert Path(state.pool['path']).read_bytes() == pool_bytes
    assert not [value for value in state.calls if value[0] in ('fetch', 'register')]


@pytest.mark.parametrize('extra_event', [False, True])
def test_prepare_main_ca_finite_ref_uses_only_explicit_exact_terms_and_zero_queries(main_ca_prepare, monkeypatch, capsys, extra_event):
    import sys
    from types import ModuleType
    from unittest.mock import Mock
    state = main_ca_prepare; state.need_ca = False; state.typed = 'existing'
    admission = state.artifact('finite_admission.json', {'synthetic': 'separately admitted finite identity'})
    finite = ModuleType('scripts.research.a2.evaluation.consensus_paper_ca_continuation')
    terms = {'US.OTHER': ['2026-10-14']} if extra_event else {'US.SYNTHETIC': ['2026-10-14']}
    finite.qualify_admission = Mock(return_value={'admission_ref': admission, 'admitted_event_terms': terms})
    finite.already_current = Mock(return_value=None)
    monkeypatch.setitem(sys.modules, finite.__name__, finite)
    assert module.main(['--prepare-main-ca', '--expected-signal-date', state.target,
        '--finite-ca-admission-ref', json.dumps(admission)]) == (2 if extra_event else 0)
    result = json.loads(capsys.readouterr().out)['result']
    assert result['status'] == ('SOURCE_CA_TERMS_BLOCKED' if extra_event else 'READY')
    assert result['finite_ca_admission_ref'] == admission and result['rehab_requests'] == 0
    assert result['main_qualification_ready'] is False
    assert finite.qualify_admission.call_count == 1
    assert not [value for value in state.calls if value[0] in ('fetch', 'register')]
    with pytest.raises(SystemExit): module.main(['--finite-ca-admission-ref', json.dumps(admission)])


@pytest.fixture
def completed_main_ca(main_ca_prepare, monkeypatch):
    """Only small synthetic published metadata; no source values or model imports."""
    import sys
    from copy import deepcopy
    from unittest.mock import Mock
    state = main_ca_prepare
    state.owner = sys.modules['scripts.research.a2.evaluation.consensus_paper_performance']
    state.consumer = sys.modules['scripts.research.a2.inference.consensus_paper']
    state.prices = sys.modules['scripts.daily_recommendation_prices']
    state.completions = {sid: state.artifact(sid + '_completion.json', {'source_refs': {}})
        for sid in state.owner.IDS}
    state.manifest = state.artifact('current_main_manifest.json', {'extensions': state.completions})
    state.current_proof = {'status': 'ALREADY_CURRENT_PREFIX_VERIFIED', 'end': state.target,
        'manifest_ref': state.manifest, 'models_loaded': 0, 'account_replays': 0,
        'ledger_values_decoded': 0, 'model_fit_calls': 0, 'broker_action_allowed': False}
    def current(paths, calendar, clock):
        assert state.locked and paths is state.paths and calendar['target_session'] == state.target
        state.calls.append(('already_current', calendar['target_session']))
        return deepcopy(state.current_proof)
    def projected(ref, fields):
        assert state.reference(ref['path']) == ref
        value = json.loads(Path(ref['path']).read_text(encoding='utf-8'))
        return {key: value[key] for key in fields if key in value}
    monkeypatch.setattr(state.owner, 'already_current', Mock(side_effect=current))
    monkeypatch.setattr(state.owner, 'projected_metadata', projected, raising=False)
    return state


@pytest.mark.parametrize('finite', [False, True])
def test_prepare_main_ca_completed_owner_proof_skips_all_source_scans(completed_main_ca, monkeypatch, finite):
    import sys
    from copy import deepcopy
    from types import ModuleType
    from unittest.mock import Mock
    state = completed_main_ca
    kwargs = {}
    if finite:
        admission = state.artifact('explicit_finite.json', {'synthetic': 'explicit exact admission'})
        driver = ModuleType('scripts.research.a2.evaluation.consensus_paper_ca_continuation')
        proof = {**deepcopy(state.current_proof), 'finite_ca_admission_ref': admission}
        def current(paths, calendar, clock, *, finite_ca_admission_ref):
            assert state.locked and paths is state.paths and calendar['target_session'] == state.target
            assert finite_ca_admission_ref == admission
            return deepcopy(proof)
        driver.already_current = Mock(side_effect=current)
        driver.qualify_admission = lambda *a, **k: pytest.fail('completed proof must not rescan finite source qualification')
        monkeypatch.setitem(sys.modules, driver.__name__, driver)
        kwargs['finite_ca_admission_ref'] = admission
    for owner, names in ((state.owner, ('resolve_current_capture', 'metadata_preflight',
            '_tail_proof_chain', '_current_quote_source', 'resolve_supplemental_ca_receipts',
            '_ca_locator_origin', 'qualify_current_tail', 'register_supplemental_ca_receipts')),
            (state.consumer, ('load_publication', 'bounded_frame')),
            (state.prices, ('refresh_rehab',))):
        for name in names:
            monkeypatch.setattr(owner, name, lambda *a, **k: pytest.fail('completed owner proof must skip capture/domain/qualify/fetch'))
    before = {ref['path']: Path(ref['path']).read_bytes() for ref in state.stable}
    result = module.prepare_main_ca(state.paths, state.target, **kwargs)
    assert result['status'] == 'READY' and result['reason'] == 'CURRENT_MAIN_OWNER_PROOF_REUSED_NOT_NEW_QUALIFICATION'
    assert result['main_manifest_ref'] == state.manifest
    assert result['main_qualification_ready'] is result['broker_action_allowed'] is False
    for field in ('rehab_requests', 'history_requests', 'trade_requests', 'models_loaded', 'account_replays', 'model_fit_calls'):
        assert type(result[field]) is int and result[field] == 0
    assert {name: Path(name).read_bytes() for name in before} == before
    if finite:
        assert result['finite_ca_admission_ref'] == admission
        driver.already_current.assert_called_once()
        state.owner.already_current.assert_not_called()
    else:
        state.owner.already_current.assert_called_once()


def test_prepare_main_ca_no_matching_completion_keeps_original_scope_and_fetch(completed_main_ca):
    state = completed_main_ca; state.current_proof = None
    result = module.prepare_main_ca(state.paths, state.target)
    assert result['status'] == 'READY' and result['reason'] == 'SOURCE_CA_READY_NOT_MAIN_ADMISSION'
    assert result['rehab_requests'] == 1
    assert len([value for value in state.calls if value[0] == 'domain']) == 1
    assert len([value for value in state.calls if value[0] == 'qualify']) == 2
    assert len([value for value in state.calls if value[0] == 'fetch']) == 1


def test_prepare_main_ca_no_matching_source_revalidates_and_rejects_drift(completed_main_ca):
    state = completed_main_ca; state.current_proof = None
    Path(state.stable[0]['path']).write_text('{"synthetic":"drifted source"}', encoding='utf-8')
    with pytest.raises(ValueError, match='PAPER_EXTENSION_REFERENCE_CHANGED'):
        module.prepare_main_ca(state.paths, state.target)
    assert any(value[0] == 'binding' for value in state.calls)
    assert not [value for value in state.calls if value[0] in ('domain', 'qualify', 'fetch', 'register')]


@pytest.mark.parametrize('mismatch', ['calendar', 'completion', 'source_hash'])
def test_prepare_main_ca_current_proof_mismatch_never_becomes_noop(completed_main_ca, monkeypatch, mismatch):
    from unittest.mock import Mock
    state = completed_main_ca
    if mismatch == 'calendar':
        expected = '2026-10-14'; reason = 'MAIN_CA_EXPECTED_SIGNAL_DATE_CHANGED'
    elif mismatch == 'completion':
        expected = state.target; state.current_proof['end'] = '2026-10-14'
        reason = 'MAIN_CA_CURRENT_COMPLETION_MISMATCH'
    else:
        expected = state.target; reason = 'PAPER_EXTENSION_PREVIOUS_MANIFEST_CHANGED'
        monkeypatch.setattr(state.owner, 'already_current', Mock(side_effect=ValueError(reason)))
    monkeypatch.setattr(state.owner, 'resolve_current_capture',
        lambda *a: pytest.fail('changed completed proof must not continue to acquisition'))
    with pytest.raises(ValueError, match=reason):
        module.prepare_main_ca(state.paths, expected)
    assert not [value for value in state.calls if value[0] in ('domain', 'qualify', 'fetch', 'register')]
    if mismatch == 'calendar':
        state.owner.already_current.assert_not_called()


@pytest.mark.parametrize('mismatch', ['owner_rejects', 'returned_identity'])
def test_prepare_main_ca_completed_finite_proof_requires_same_explicit_admission(completed_main_ca, monkeypatch, mismatch):
    import sys
    from types import ModuleType
    from unittest.mock import Mock
    state = completed_main_ca
    admission = state.artifact('requested_finite.json', {'synthetic': 'requested identity'})
    other = state.artifact('different_finite.json', {'synthetic': 'other identity'})
    driver = ModuleType('scripts.research.a2.evaluation.consensus_paper_ca_continuation')
    driver.already_current = (Mock(side_effect=ValueError('FINITE_CA_CURRENT_ADMISSION_CHANGED'))
        if mismatch == 'owner_rejects' else Mock(return_value={**state.current_proof, 'finite_ca_admission_ref': other}))
    monkeypatch.setitem(sys.modules, driver.__name__, driver)
    monkeypatch.setattr(state.owner, 'resolve_current_capture',
        lambda *a: pytest.fail('finite identity mismatch must stop before scans'))
    with pytest.raises(ValueError, match='FINITE_CA_CURRENT_ADMISSION_CHANGED'):
        module.prepare_main_ca(state.paths, state.target, finite_ca_admission_ref=admission)
    state.owner.already_current.assert_not_called()
    assert not [value for value in state.calls if value[0] in ('domain', 'qualify', 'fetch', 'register')]


def test_prepare_main_ca_default_does_not_inherit_finite_published_permission(completed_main_ca):
    state = completed_main_ca; state.need_ca = False; state.typed = 'existing'
    admission = state.artifact('unrequested_finite.json', {'synthetic': 'not requested'})
    sid = state.owner.IDS[0]
    state.completions[sid] = state.artifact('finite_completion.json',
        {'source_refs': {'finite_ca_admission_ref': admission}})
    state.manifest = state.artifact('finite_current_manifest.json', {'extensions': state.completions})
    state.current_proof['manifest_ref'] = state.manifest
    result = module.prepare_main_ca(state.paths, state.target)
    assert result['status'] == 'SOURCE_CA_TERMS_BLOCKED'
    assert 'finite_ca_admission_ref' not in result and 'main_manifest_ref' not in result
    assert result['main_qualification_ready'] is result['broker_action_allowed'] is False
    assert any(value[0] == 'domain' for value in state.calls)
    assert any(value[0] == 'qualify' for value in state.calls)
    assert not [value for value in state.calls if value[0] in ('fetch', 'register')]


def test_same_day_resume_rechecks_optional_paper_source_with_reuse_only(tmp_path, monkeypatch):
    from scripts.storage import storage_r2a
    paths, latest, source, binding, calendar, now, *_ = _accepted_daily_fixture(tmp_path, monkeypatch)
    before = Path(source['report_path']).read_bytes()
    calls = []
    def optional(actual_paths, actual_source, actual_run, *, reuse_only):
        calls.append(reuse_only)
        assert actual_paths is paths and actual_source == source
        assert actual_run == Path(source['report_path']).parent
        return {'status':'READY', 'source_reused':True, 'optional_stage':'READY'}
    monkeypatch.setattr(module, 'update_consensus_paper_inputs', optional)
    monkeypatch.setattr(module, '_verified_daily_stage_summaries', lambda *a, **kw: _complete_synthetic_stages())
    monkeypatch.setattr(module, 'run_provider', lambda *a, **kw: pytest.fail('completed chart worker restarted'))
    monkeypatch.setattr(storage_r2a, 'DataStore', lambda: object())
    monkeypatch.setattr(module, 'refresh_daily_benchmarks', lambda *a, **kw:
        {'status':'READY', 'available_end_date':source['data_date']})
    result = module.resume_published_update(paths, binding, calendar, now, lambda *_:None)
    assert calls == [True] and result['consensus_paper_inputs']['optional_stage'] == 'READY'
    assert Path(source['report_path']).read_bytes() == before
    assert result['recovery']['inference_calls'] == result['recovery']['acquisition_calls'] == 0


def test_optional_paper_resume_requires_ready_original_base_before_builder(tmp_path, monkeypatch):
    from scripts.research.a2.inference import consensus_paper, consensus_current_inputs
    paths = SimpleNamespace(daily_root=tmp_path)
    result = {'data_date':'2026-10-14', 'frozen_raw32_features':
        {'status':'READY', 'signal_date':'2026-10-14', 'path':str(tmp_path/'features.parquet')}}
    monkeypatch.setattr(consensus_paper, 'load_publication', lambda *a, **kw: ({'status':'BLOCKED'}, {}))
    monkeypatch.setattr(consensus_current_inputs, 'refresh_current_inputs', lambda *a, **kw: pytest.fail('unaccepted base rebuilt'))
    report = module.update_consensus_paper_inputs(paths, result, tmp_path, reuse_only=True)
    assert report['status'] == 'BLOCKED' and report['reason'] == 'CURRENT_CONSENSUS_READY_BASE_REQUIRED_FOR_RESUME'


@pytest.mark.parametrize("error", [RuntimeError, MemoryError])
def test_same_day_optional_exception_does_not_interrupt_reused_charts(tmp_path, monkeypatch, error):
    from scripts.storage import storage_r2a
    paths, latest, source, binding, calendar, now, *_ = _accepted_daily_fixture(tmp_path, monkeypatch)
    before = Path(source['report_path']).read_bytes()
    def fail_optional(*args, **kwargs): raise error("SYNTHETIC_OPTIONAL_FAILURE")
    monkeypatch.setattr(module, 'update_consensus_paper_inputs', fail_optional)
    monkeypatch.setattr(module, '_verified_daily_stage_summaries', lambda *a, **kw: _complete_synthetic_stages())
    monkeypatch.setattr(module, 'run_provider', lambda *a, **kw: pytest.fail('completed chart worker restarted'))
    monkeypatch.setattr(storage_r2a, 'DataStore', lambda: object())
    monkeypatch.setattr(module, 'refresh_daily_benchmarks', lambda *a, **kw:
        {'status':'READY', 'available_end_date':source['data_date']})
    result = module.resume_published_update(paths, binding, calendar, now, lambda *_:None)
    assert result['consensus_paper_inputs']['status'] == 'BLOCKED'
    assert result['consensus_paper_inputs']['reason'].startswith(error.__name__ + ':')
    assert result['completion']['status'] == 'READY'
    assert Path(source['report_path']).read_bytes() == before


@pytest.fixture
def explicit_current_inputs(tmp_path, monkeypatch):
    """Real accepted-source checks and daily lock; synthetic producer only."""
    from contextlib import contextmanager
    from copy import deepcopy
    from scripts import daily_recommendation_inputs as inputs
    from scripts.common import storage_paths
    from scripts.research.a2.evaluation.three_strategy_extension import reference
    from scripts.research.a2.inference import consensus_current_inputs, consensus_paper
    paths, latest, source, binding, calendar, now, evidence, feature, _ = _accepted_daily_fixture(tmp_path, monkeypatch)
    source['frozen_raw32_features'] = {**reference(feature), 'status': 'READY', 'signal_date': source['data_date']}
    module.save(Path(source['report_path']), source)
    latest.update(frozen_raw32_features=source['frozen_raw32_features'], accepted_source=reference(source['report_path']))
    module.save(Path(latest['report_path']), latest)
    module.save(paths.daily_root / 'A2_today_recommendation/latest.json', latest)
    base = {'status': 'READY', 'signal_date': source['data_date'], 'strategy_status': {'R10_DIRECT_H5_RIDGE_MID': {'status': 'READY'}}}
    base_ref = {'path': str(tmp_path/'synthetic_publication.json'), 'sha256': 'c'*64}
    duration_ref = {'path': str(tmp_path/'synthetic_duration.json'), 'sha256': 'd'*64}
    state = SimpleNamespace(paths=paths, source=source, ref=reference(source['report_path']), target=source['data_date'],
        binding=binding, calendar=calendar, evidence=evidence, calls=[], locked=False, existing=False,
        base=base, base_ref=base_ref, duration_ref=duration_ref, after=None, blocked=None)
    original_lock = module.single_update
    @contextmanager
    def lock(root):
        assert root == paths.daily_root / 'A2_today_recommendation'
        with original_lock(root):
            state.locked = True
            try: yield
            finally: state.locked = False
    monkeypatch.setattr(module, 'single_update', lock)
    monkeypatch.setattr(inputs, 'load_frozen_binding', lambda *_: deepcopy(state.binding))
    monkeypatch.setattr(inputs, 'latest_completed_session', lambda *_: deepcopy(state.calendar))
    monkeypatch.setattr(storage_paths, 'resolve', lambda: paths)
    for name in ('run_provider', 'predict_current', 'run_update', 'acquire_pool_prices'):
        monkeypatch.setattr(module, name, lambda *a, **kw: pytest.fail('unrelated daily work invoked'))
    def refresh(actual, *, current_report, run_dir, **kwargs):
        assert state.locked and actual is paths and current_report == source
        assert run_dir == Path(source['report_path']).parent and kwargs == {'allow_raw_recovery': False}
        state.calls.append('reuse' if state.existing else 'build')
        if state.after: state.after()
        if state.blocked == 'resource': raise ValueError('CONSENSUS_RESOURCE_FLOOR')
        extension = {'status': 'BLOCKED' if state.blocked == 'duration' else 'READY',
            'publication_ref': duration_ref, 'reason': 'SYNTHETIC_DURATION_RESOURCE_FLOOR' if state.blocked == 'duration' else None}
        return {'status': 'READY', 'signal_date': state.target, 'publication': {**deepcopy(base), 'paper_current_extension': extension}}
    def load(actual, day, as_of, *, paper_current=False):
        assert state.locked and actual is paths and day == state.target
        state.calls.append('read_duration' if paper_current else 'read_base')
        if paper_current:
            return {**deepcopy(base), 'strategy_status': {'R6_DURATION_TREE': {'status': 'READY'}}}, deepcopy(duration_ref)
        return deepcopy(base), deepcopy(base_ref)
    monkeypatch.setattr(consensus_current_inputs, 'refresh_current_inputs', refresh)
    monkeypatch.setattr(consensus_paper, 'load_publication', load)
    return state


@pytest.mark.parametrize('existing', [False, True])
def test_explicit_current_inputs_uses_original_producer_under_lock(explicit_current_inputs, existing):
    state = explicit_current_inputs; state.existing = existing
    before = Path(state.ref['path']).read_bytes()
    result = module.prepare_current_inputs(state.paths, state.target, state.ref['path'], state.ref['sha256'], lambda _: None)
    assert result['status'] == 'READY' and result['paper_current_status'] == 'READY'
    assert result['publication_ref'] == state.base_ref and result['duration_publication_ref'] == state.duration_ref
    assert result['source_report'] == state.ref and result['signal_date'] == state.target
    assert result['acquisition_calls'] == result['raw_inference_calls'] == result['model_fit_calls'] == result['trade_requests'] == 0
    assert result['broker_action_allowed'] is False and not state.locked
    assert state.calls == ['reuse' if existing else 'build', 'read_base', 'read_duration']
    assert Path(state.ref['path']).read_bytes() == before


@pytest.mark.parametrize('defect', ['date', 'hash', 'path', 'source_drift', 'lineage_drift', 'calendar_drift', 'binding_drift', 'latest_drift'])
def test_explicit_current_inputs_rejects_bound_input_drift(explicit_current_inputs, defect):
    state = explicit_current_inputs; target = state.target; ref = dict(state.ref)
    if defect == 'date': target = '2026-10-06'
    elif defect == 'hash': ref['sha256'] = '0'*64
    elif defect == 'path': ref['path'] = str(state.paths.daily_root/'foreign.json')
    elif defect == 'source_drift':
        state.after = lambda: Path(state.ref['path']).write_bytes(Path(state.ref['path']).read_bytes()+b' ')
    elif defect == 'lineage_drift': state.after = lambda: state.evidence.write_text('changed synthetic evidence')
    elif defect == 'calendar_drift': state.after = lambda: state.calendar.update(target_date='2026-10-06')
    elif defect == 'binding_drift': state.after = lambda: state.binding.update(synthetic_changed=True)
    else:
        path = state.paths.daily_root/'A2_today_recommendation/latest.json'
        state.after = lambda: path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError):
        module.prepare_current_inputs(state.paths, target, ref['path'], ref['sha256'], lambda _: None)
    assert state.calls == ([] if defect in ('date', 'hash', 'path') else ['build'])
    assert not state.locked


@pytest.mark.parametrize('failure', ['resource', 'duration'])
def test_explicit_current_inputs_incomplete_sources_are_not_ready(explicit_current_inputs, failure):
    state = explicit_current_inputs; state.blocked = failure
    result = module.prepare_current_inputs(state.paths, state.target, state.ref['path'], state.ref['sha256'], lambda _: None)
    assert result['status'] == 'BLOCKED' and 'RESOURCE_FLOOR' in result['reason']
    assert result['source_status'] == ('BLOCKED' if failure == 'resource' else 'READY')
    assert result['paper_current_status'] == ('BLOCKED' if failure == 'duration' else None)
    assert 'publication_ref' not in result and state.calls == ['build']


def test_explicit_current_inputs_cli_rejects_mixed_actions_and_returns_blocked(explicit_current_inputs, capsys):
    state = explicit_current_inputs
    args = ['--prepare-current-inputs', '--expected-signal-date', state.target,
        '--source-report', state.ref['path'], '--source-sha256', state.ref['sha256']]
    for extra in (['--execute'], ['--refresh-data'], ['--requalify-inputs'], ['--execution-charts'],
                  ['--performance-worker', 'raw'], ['--prepare-main-ca'], ['--finite-ca-admission-ref', '{}']):
        with pytest.raises(SystemExit): module.main([*args, *extra])
    for missing in ('--expected-signal-date', '--source-report', '--source-sha256'):
        partial = args.copy(); index = partial.index(missing); del partial[index:index+2]
        with pytest.raises(SystemExit): module.main(partial)
    assert state.calls == []
    state.blocked = 'resource'
    assert module.main(args) == 2
    result = json.loads(capsys.readouterr().out.splitlines()[-1])['result']
    assert result['status'] == 'BLOCKED' and result['reason'] == 'CONSENSUS_RESOURCE_FLOOR'
    state.blocked = None
    assert module.main(args) == 0
    assert json.loads(capsys.readouterr().out.splitlines()[-1])['result']['publication_ref'] == state.base_ref


@pytest.mark.parametrize('paper_status', ['READY', 'BLOCKED'])
def test_compact_current_input_summary_keeps_optional_status_without_payload(paper_status):
    source = {'status': 'READY', 'signal_date': '2026-10-16', 'reason': None,
        'publication': {'status': 'READY', 'input_refs': {'large': list(range(1000))},
            'paper_current_extension': {'status': paper_status, 'large': list(range(1000))}}}
    result = module._compact_terminal_result({'consensus_paper_inputs': source})
    assert result['consensus_paper_inputs'] == {'status': 'READY', 'signal_date': '2026-10-16',
        'reason': None, 'paper_current_status': paper_status}


@pytest.mark.parametrize('prior,execute,refresh', [
    ('different_day', True, False), ('absent', True, False),
    ('different_day', True, True), ('different_day', False, False)])
def test_single_update_reuses_verified_binding_and_calendar_only_within_invocation(tmp_path, monkeypatch, prior, execute, refresh):
    from scripts import daily_recommendation_inputs as inputs
    paths = _ready_daily_without_external_work(tmp_path, monkeypatch)
    if prior != 'absent':
        module.save(paths.daily_root / 'A2_today_recommendation/latest.json',
                    {'status': 'READY', 'data_date': '2026-10-02'})
    binding = inputs.load_frozen_binding(paths.repo_root)
    calendar = inputs.latest_completed_session(binding)
    calls = []
    def load_binding(actual):
        assert actual == paths.repo_root
        calls.append('binding')
        return binding
    def load_calendar(actual, now):
        assert actual is binding
        calls.append('calendar')
        return calendar
    monkeypatch.setattr(inputs, 'load_frozen_binding', load_binding)
    monkeypatch.setattr(inputs, 'latest_completed_session', load_calendar)
    monkeypatch.setattr(module, 'update_consensus_paper_inputs', lambda *a, **kw: {'status': 'SKIPPED'})
    monkeypatch.setattr(module, '_publish_recommendation', lambda *a, **kw: None)
    result = module.run_update(paths, execute=execute, refresh_data=refresh, emit_progress=lambda *_: None)
    assert result['status'] == ('READY' if execute else 'PLANNED')
    assert result['data_date'] == calendar['target_date']
    assert calls == ['binding', 'calendar']
    # A later invocation still revalidates; there is no persistent binding cache.
    module.run_update(paths, execute=execute, refresh_data=refresh, emit_progress=lambda *_: None)
    assert calls == ['binding', 'calendar', 'binding', 'calendar']


@pytest.mark.parametrize('failure', ['binding', 'calendar'])
def test_recovery_probe_invalid_binding_or_calendar_never_falls_back_to_acquisition(tmp_path, monkeypatch, failure):
    from scripts import daily_recommendation_inputs as inputs
    paths = _ready_daily_without_external_work(tmp_path, monkeypatch)
    module.save(paths.daily_root / 'A2_today_recommendation/latest.json',
                {'status': 'READY', 'data_date': '2026-10-02'})
    name = 'load_frozen_binding' if failure == 'binding' else 'latest_completed_session'
    def invalid(*_):
        raise ValueError('SYNTHETIC_FROZEN_IDENTITY_INVALID')
    monkeypatch.setattr(inputs, name, invalid)
    monkeypatch.setattr(module, 'acquire_pool_prices', lambda *a, **kw: pytest.fail('invalid identity reached acquisition'))
    with pytest.raises(ValueError, match='SYNTHETIC_FROZEN_IDENTITY_INVALID'):
        module.run_update(paths, emit_progress=lambda *_: None)


def test_single_update_catalog_capture_is_reused_only_before_acquisition(tmp_path, monkeypatch):
    from scripts.storage import manage_data
    paths = _ready_daily_without_external_work(tmp_path, monkeypatch)
    before = ([{'ticker': 'BEFORE'}], [])
    after = ([{'ticker': 'AFTER'}], [])
    stage = ['before']
    reads, seen = [], []
    def capture(_):
        reads.append(stage[0])
        return before if stage[0] == 'before' else after
    def report_status(_, snapshot):
        assert snapshot is before
        return {}
    def acquisition_tickers(_, snapshot):
        assert snapshot is before
        return ['BEFORE']
    def supplement(members, aliases, prices):
        assert prices is before[0]
        return {}
    def acquire(*a, **kw):
        stage[0] = 'after'
        return {'moomoo': {'results': []}}
    def native_tail(paths, run, target, members, acquisitions, prices, *a):
        seen.append(prices)
        return acquisitions, {'result_count': 0, 'qualified_intervals': 0}
    monkeypatch.setattr(manage_data, 'read_catalog', capture)
    monkeypatch.setattr(manage_data, 'status', report_status)
    monkeypatch.setattr(manage_data, 'acquisition_tickers', acquisition_tickers)
    monkeypatch.setattr(module, 'current_pool_supplement', supplement)
    monkeypatch.setattr(module, 'acquire_pool_prices', acquire)
    monkeypatch.setattr(module, 'acquire_native_current_tail', native_tail)
    monkeypatch.setattr(module, 'update_consensus_paper_inputs', lambda *a, **kw: {'status': 'SKIPPED'})
    monkeypatch.setattr(module, '_publish_recommendation', lambda *a, **kw: None)
    result = module.run_update(paths, emit_progress=lambda *_: None)
    assert result['status'] == 'READY'
    assert reads == ['before', 'after']
    assert seen == [after[0]]
