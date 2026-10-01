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
    with patch.object(selected_hgb, 'build_package', side_effect=ValueError('BAD_FEATURE_BINDING')):
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
    with patch.object(selected_hgb, 'build_package', return_value=package), \
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
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        paths = SimpleNamespace(python_exe=Path('python'), repo_root=root)
        with patch.object(module.subprocess, 'run', return_value=SimpleNamespace(returncode=2)) as run:
            result = module.run_provider(paths, 'scripts.storage.refresh_public_sources', ['--target-date', '2026-09-22'], root / 'provider.log')
        args, kwargs = run.call_args
        assert args[0] == ['python', '-B', '-m', 'scripts.storage.refresh_public_sources', '--target-date', '2026-09-22']
        assert not kwargs.get('shell')
        assert result['exit_code'] == 2
        assert Path(result['log_path']).is_file()


def test_provider_timeout_is_failure_not_old_success():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        paths = SimpleNamespace(python_exe=Path('python'), repo_root=root)
        error = module.subprocess.TimeoutExpired(['provider'], 3600)
        with patch.object(module.subprocess, 'run', side_effect=error):
            result = module.run_provider(paths, 'provider', [], root / 'timeout.log')
        assert result['exit_code'] == -1
        assert 'error' in result


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
