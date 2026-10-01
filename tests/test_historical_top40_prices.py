"""Synthetic price histories exercise the frozen transformations, without APIs."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest


SOURCE = Path(__file__).parents[1] / 'scripts/research/a2/inference/historical_top40_prices.py'
spec = importlib.util.spec_from_file_location('test_historical_prices', SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class EmptyStore:
    def metadata(self, *args):
        raise KeyError(args)


@pytest.fixture
def case(tmp_path, monkeypatch):
    paths = SimpleNamespace(repo_root=tmp_path / 'repo', backtest_root=tmp_path / 'backtests',
        results_root=tmp_path / 'results', cache_root=tmp_path / 'cache', daily_root=tmp_path / 'daily')
    raw_root = paths.cache_root / 'original_raw'
    raw_root.mkdir(parents=True)
    dates = pd.bdate_range('2020-01-02', periods=175)
    close = 100 + np.arange(len(dates)) / 10 + np.sin(np.arange(len(dates)))
    raw = pd.DataFrame({'code': 'US.TEST', 'time_key': dates.astype(str), 'open': close,
                        'high': close + 1, 'low': close - 1, 'close': close, 'volume': 10000 + np.arange(len(dates))})
    raw_path = raw_root / 'US_TEST.parquet'
    raw.to_parquet(raw_path, index=False)
    factors = pd.DataFrame({'code': ['US.TEST'], 'ex_div_date': [dates[30]],
                           'forward_adj_factorA': [0.5], 'forward_adj_factorB': [0.0], 'split_ratio': [2.0]})
    factor_path, status_path = tmp_path / 'old_rehab.parquet', tmp_path / 'old_status.csv'
    factors.to_parquet(factor_path, index=False)
    pd.DataFrame([{'code': 'US.TEST', 'status': 'PASS', 'row_count': 1}]).to_csv(status_path, index=False)
    adapter = module.prices._adapter('2025-12-31')
    adjusted, _ = adapter.adjusted_price_frame('US.TEST', 'TEST', module.prices._raw_frame(raw, 'US.TEST'),
                                              factors, {'event_date': '2025-09-29', 'quantity_multiplier': 0.008352})
    ledger = adjusted[['trade_date', 'ticker', 'close', 'volume']].rename(columns={'trade_date': 'signal_date'}).iloc[120:]
    ledger_path = tmp_path / 'frozen_prices.parquet'
    ledger.to_parquet(ledger_path, index=False)
    cutoff = dates[145]
    coverage = {'raw': {'root': str(raw_root), 'code_map': {}, 'file_sha256': {}},
        'rehab': {'factors_path': str(factor_path), 'factors_sha256': module.prices.digest(factor_path),
                  'status_path': str(status_path), 'status_sha256': module.prices.digest(status_path)},
        'adjustment': {'wolf_event_date': '2025-09-29', 'wolf_new_shares_per_old_share': 0.008352,
                       'required_end_exclusive': (cutoff + pd.Timedelta(days=1)).strftime('%Y-%m-%d')}}
    coverage_path = tmp_path / 'coverage.json'
    coverage_path.write_text(json.dumps(coverage))
    references = {'coverage': {'path': coverage_path, 'sha256': module.prices.digest(coverage_path)},
                  'ledger': {'path': ledger_path, 'sha256': module.prices.digest(ledger_path)},
                  'source': {'path': Path('D:/us-tech-quant/scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py'),
                             'sha256': module.FEATURE_SOURCE_SHA}}
    fresh_path = tmp_path / 'fresh_rehab.parquet'
    factors.to_parquet(fresh_path, index=False)
    end = dates[-1].strftime('%Y-%m-%d')
    rehab = {'source': 'MOOMOO_OPEND_GET_REHAB', 'target_date': end, 'results': [
        {'code': 'US.TEST', 'status': 'PASS', 'path': str(fresh_path), 'sha256': module.prices.digest(fresh_path),
         'row_count': 1, 'fetched_at': end + 'T23:00:00+00:00'}]}
    monkeypatch.setattr(module, '_references', lambda _: references)
    monkeypatch.setattr(module, '_store', lambda _: EmptyStore())
    value = SimpleNamespace(paths=paths, dates=dates, raw=raw, raw_path=raw_path, factors=factors,
        fresh_path=fresh_path, coverage=coverage, coverage_path=coverage_path, refs=references,
        ledger=ledger, ledger_path=ledger_path, rehab=rehab, cutoff=cutoff, adjusted=adjusted)
    value.args = [paths, [{'ticker': 'TEST', 'moomoo_transport_code': 'US.TEST', 'cusip': '123456789'}],
                  dates[120].strftime('%Y-%m-%d'), end, dates.strftime('%Y-%m-%d').tolist(), {}, rehab,
                  paths.backtest_root / 'historical_test']
    return value


def test_expanded_anchor_exact_proof_builds_once_and_verified_resume_skips_recomputation(case):
    source = module._source(case.refs['source'])
    with patch.object(source, 'build_stock_state_features', wraps=source.build_stock_state_features) as build, \
         patch.object(module, '_source', return_value=source):
        frame, lineage, gaps = module.build_price_features(*case.args)
        again, same_lineage, same_gaps = module.build_price_features(*case.args)
    assert build.call_count == 1
    pd.testing.assert_frame_equal(frame, again)
    assert same_lineage == lineage and same_gaps == gaps == []
    assert len(frame) == 55 and len(frame.columns) == 34
    assert lineage[0]['anchor_proof']['compared_rows'] == len(case.ledger)
    assert lineage[0]['anchor_proof']['absolute_error'] == 0
    assert lineage[0]['anchor_date'] == case.dates[0].strftime('%Y-%m-%d')
    manifest = json.loads((case.args[-1] / 'prices/manifest.json').read_text())
    assert manifest['schema'] == 'A2_HISTORICAL_EXPANDED_PRICE_INPUTS_V1'
    assert 'NOT_HISTORICAL_PUBLICATION_VINTAGE' in manifest['vintage_semantics']
    assert manifest['features']['row_count'] == 55


@pytest.mark.parametrize('as_frame', [True, False])
def test_dataframe_universe_optional_missing_metadata_does_not_enter_price_fingerprint(case, as_frame):
    source_row = {'quarter': '2020Q1', 'report_date': pd.Timestamp('2020-03-31'),
        'effective_date': pd.Timestamp('2020-05-22'), 'expiry_date': pd.NaT,
        'cusip': '123456789', 'security_id': pd.NA, 'ticker': 'TEST',
        'moomoo_symbol': np.nan, 'moomoo_transport_code': 'US.TEST',
        'issuer_name': pd.NA, 'manager_count': 2, 'manager_ids': 'one;two',
        'legacy_aggregate_value_usd': np.nan, 'conviction_score': np.nan,
        'identity_source_sha256': pd.NA, 'identity_evidence_effective_date': pd.NaT}
    frame = pd.DataFrame([source_row])
    case.args[1] = frame if as_frame else frame.to_dict('records')
    features, lineage, gaps = module.build_price_features(*case.args)
    assert len(features) == 55 and gaps == []
    assert lineage[0]['cusips'] == ['123456789']
    # The caller binds the entire PIT universe artifact separately. Equivalent
    # identity input must resume the same price cache despite metadata types.
    case.args[1] = [{'ticker': 'TEST', 'moomoo_symbol': 'US.TEST', 'cusip': '123456789', 'security_id': None}]
    again, _, _ = module.build_price_features(*case.args)
    pd.testing.assert_frame_equal(features, again)
    with pytest.raises(ValueError, match='not JSON compliant'):
        module._fingerprint({'unrelated_numeric_contract': np.nan})


def test_missing_dataframe_identity_is_not_stringified_into_an_eligible_anchor(case):
    case.args[1] = pd.DataFrame([{'ticker': 'TEST', 'moomoo_symbol': 'US.TEST',
                                'cusip': np.nan, 'security_id': pd.NA}])
    features, lineage, gaps = module.build_price_features(*case.args)
    assert features.empty and lineage == []
    assert gaps[0]['reasons'] == ['HISTORICAL_MEMBER_IDENTITY_UNBOUND']


@pytest.mark.parametrize('cause', ['different_price', 'no_ledger_rows', 'no_original_rehab'])
def test_same_original_folder_is_insufficient_to_create_an_anchor(case, cause):
    if cause == 'different_price':
        case.raw.loc[130, 'close'] += 0.01
        case.raw.to_parquet(case.raw_path, index=False)
    elif cause == 'no_ledger_rows':
        case.ledger.iloc[:0].to_parquet(case.ledger_path, index=False)
        case.refs['ledger']['sha256'] = module.prices.digest(case.ledger_path)
    else:
        pd.DataFrame([{'code': 'US.TEST', 'status': 'FAIL', 'row_count': 1}]).to_csv(case.coverage['rehab']['status_path'], index=False)
        case.coverage['rehab']['status_sha256'] = module.prices.digest(case.coverage['rehab']['status_path'])
        case.coverage_path.write_text(json.dumps(case.coverage))
        case.refs['coverage']['sha256'] = module.prices.digest(case.coverage_path)
    frame, lineage, gaps = module.build_price_features(*case.args)
    assert frame.empty and lineage == [] and gaps[0]['missing_all_requested_dates']
    assert 'EXPANDED_ANCHOR' in gaps[0]['reasons'][0]


def test_future_event_changes_only_its_date_and_later_features_without_resetting_anchor(case):
    later = pd.concat([case.factors, pd.DataFrame([{'code': 'US.TEST', 'ex_div_date': case.dates[150],
        'forward_adj_factorA': 0.5, 'forward_adj_factorB': 0., 'split_ratio': 2.0}])], ignore_index=True)
    later.to_parquet(case.fresh_path, index=False)
    case.rehab['results'][0].update(sha256=module.prices.digest(case.fresh_path), row_count=2)
    frame, _, _ = module.build_price_features(*case.args)
    source = module._source(case.refs['source'])
    old = source.build_stock_state_features(case.adjusted[['ticker', 'trade_date', 'close', 'volume']])
    early = frame[frame.trade_date < case.dates[150]]
    expected = old[old.trade_date.isin(early.trade_date)][list(frame.columns)].reset_index(drop=True)
    pd.testing.assert_frame_equal(early.reset_index(drop=True), expected)
    # An absolute-volume feature proves the old split before the 121-row window
    # was retained; restarting alpha/volume_scale at the requested start differs.
    assert frame.iloc[0].avg_volume_20d < case.raw.volume.min()


def test_missing_current_rehab_keeps_old_valid_dates_and_marks_later_gaps(case):
    case.rehab['results'] = []
    frame, lineage, gaps = module.build_price_features(*case.args)
    assert frame.trade_date.max() == case.cutoff
    assert lineage[0]['rehab']['kind'] == 'FROZEN_SNAPSHOT'
    assert case.dates[-1].strftime('%Y-%m-%d') in gaps[0]['missing_feature_dates']
    assert 'LATEST_REHAB' in gaps[0]['reasons'][0]


def test_nonconsecutive_raw_history_does_not_get_filled_or_count_as_121_sessions(case):
    # Keep a hash-bound original anchor so the gap tests the continuity gate,
    # not the separate expanded-anchor proof against frozen observations.
    shortened = case.raw.drop(index=130)
    shortened.to_parquet(case.raw_path, index=False)
    code_map = {'US.TEST': {'ticker': 'TEST', 'paths': [str(case.raw_path)],
                            'first_date': case.dates[0].strftime('%Y-%m-%d')}}
    case.coverage['raw'].update(code_map=code_map, file_sha256={str(case.raw_path): module.prices.digest(case.raw_path)})
    case.coverage_path.write_text(json.dumps(case.coverage))
    case.refs['coverage']['sha256'] = module.prices.digest(case.coverage_path)
    frame, _, gaps = module.build_price_features(*case.args)
    assert frame.trade_date.max() == case.dates[129]
    assert case.dates[130].strftime('%Y-%m-%d') in gaps[0]['missing_feature_dates']


def test_conflicting_new_moomoo_data_is_rejected_without_discarding_old_history(case):
    new_path = case.paths.cache_root / 'current.csv'
    changed = case.raw.iloc[-10:].copy()
    changed['volume'] = changed.volume.astype(float)
    changed.loc[changed.index[0], 'volume'] += .1
    changed.to_csv(new_path, index=False)
    case.args[5] = {'moomoo': {'results': [{'status': 'FETCHED_VALIDATED_INTERVAL',
        'item': {'ticker': 'TEST', 'moomoo_symbol': 'US.TEST', 'adjustment': 'raw'},
        'path': str(new_path), 'sha256': module.prices.digest(new_path)}]}}
    frame, lineage, gaps = module.build_price_features(*case.args)
    assert len(frame) == 55
    assert len(lineage[0]['raw_sources']) == 1
    assert gaps[0]['reasons'] == ['CONFLICTING_OVERLAP_RAW_PRICE']


def test_existing_massive_gate_rejection_is_not_rounded_away(case):
    old = case.raw.iloc[:165]
    old.to_parquet(case.raw_path, index=False)
    case.ledger = case.ledger[case.ledger.signal_date <= case.dates[164]]
    case.ledger.to_parquet(case.ledger_path, index=False)
    case.refs['ledger']['sha256'] = module.prices.digest(case.ledger_path)
    candidate = {'ticker': 'TEST', 'max_date': case.args[3]}
    case.args[5] = {'massive': {'catalog_records': [candidate]}}
    with patch.object(module.prices, '_qualified_massive_tail', side_effect=ValueError('MASSIVE_RAW_OVERLAP_MISMATCH:volume')) as gate:
        frame, lineage, gaps = module.build_price_features(*case.args)
    assert gate.call_count == 1 and gate.call_args.args[0] == candidate
    assert frame.trade_date.max() == case.dates[164] and lineage[0]['alternate_bridge'] is None
    assert 'MASSIVE_RAW_OVERLAP_MISMATCH:volume' in gaps[0]['reasons']


@pytest.mark.parametrize('has_gap', [False, True])
def test_current_raw_tail_requires_same_code_and_contiguous_sessions(case, has_gap):
    case.raw.iloc[:165].to_parquet(case.raw_path, index=False)
    case.ledger = case.ledger[case.ledger.signal_date <= case.dates[164]]
    case.ledger.to_parquet(case.ledger_path, index=False)
    case.refs['ledger']['sha256'] = module.prices.digest(case.ledger_path)
    tail = case.raw.iloc[165:].copy()
    if has_gap:
        tail = tail.drop(index=166)
    current = case.paths.cache_root / 'current_tail.csv'
    tail.to_csv(current, index=False)
    case.args[5] = {'moomoo': {'results': [{'status': 'FETCHED_VALIDATED_INTERVAL',
        'item': {'ticker': 'TEST', 'moomoo_symbol': 'US.TEST', 'adjustment': 'raw'},
        'path': str(current), 'sha256': module.prices.digest(current)}]}}
    frame, lineage, gaps = module.build_price_features(*case.args)
    if has_gap:
        assert frame.trade_date.max() == case.dates[164]
        assert 'NEW_RAW_TAIL_SESSION_GAP' in gaps[0]['reasons']
    else:
        assert frame.trade_date.max() == case.dates[-1] and gaps == []
        assert lineage[0]['raw_sources'][-1]['role'] == 'CURRENT_RAW'


def test_resume_rejects_modified_features_or_changed_inputs(case):
    module.build_price_features(*case.args)
    feature_path = case.args[-1] / 'prices/features.parquet'
    feature_path.write_bytes(b'changed')
    with pytest.raises(ValueError, match='PRICE_SOURCE_HASH_MISMATCH'):
        module.build_price_features(*case.args)
    case.args[1][0]['cusip'] = '987654321'
    with pytest.raises(ValueError, match='HISTORICAL_PRICE_RUN_INPUTS_CHANGED'):
        module.build_price_features(*case.args)


@pytest.fixture
def shared_store(tmp_path):
    from scripts.storage.storage_r2a import DataStore
    base = object.__new__(DataStore)
    base._data_roots = (tmp_path.resolve(),)
    base.catalog_path = tmp_path / 'catalog.sqlite3'
    base.catalog_path.touch()
    inputs = []
    for index, day in enumerate(pd.bdate_range('2026-08-01', periods=30)):
        leaf = tmp_path / f'leaf_{index}.json'
        leaf.write_text(str(index))
        inputs.append({'path': str(leaf), 'sha256': module.prices.digest(leaf),
                       'date': str(day.date()), 'observed_at': day.isoformat() + '+00:00'})
    manifest = tmp_path / 'shared.json'
    manifest.write_text(json.dumps({'schema_version': 1, 'role': 'RAW_INPUT_MANIFEST',
                                   'provider': 'MASSIVE_GROUPED', 'inputs': inputs}))
    rows = []
    for ticker in ('AAA', 'BBB', 'CCC'):
        selected = tmp_path / (ticker + '.parquet')
        selected.touch()
        lineage = {'schema_version': 1, 'role': 'PROVIDER_DAILY_PRICE_SNAPSHOT', 'provider': 'MASSIVE_GROUPED',
            'date_column': 'date', 'price_basis': 'RAW', 'currency': 'USD', 'exchange_timezone': 'America/New_York',
            'vintage_semantics': 'CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT', 'provider_symbol': ticker,
            'inputs_manifest': {'path': str(manifest), 'sha256': module.prices.digest(manifest), 'indexes': [0, 29]}}
        rows.append({'dataset': 'prices_daily_massive', 'ticker': ticker, 'adjustment': 'raw', 'format': 'parquet',
                     'source': 'MASSIVE_GROUPED', 'path': str(selected), 'lineage_json': json.dumps(lineage)})
    with patch.object(base, '_catalog_rows', return_value=rows) as catalog, \
         patch.object(base, '_check_data_path', wraps=base._check_data_path) as checked:
        yield SimpleNamespace(base=base, batch=module.ValidatedBatchStore(base), rows=rows,
                              inputs=inputs, manifest=manifest, catalog=catalog, checked=checked)


def test_batch_store_validates_shared_leaves_once_and_preserves_selected_indexes(shared_store):
    value = shared_store
    for ticker in ('AAA', 'BBB', 'CCC'):
        row = value.batch.metadata('prices_daily_massive', ticker, 'raw')
        resolved = value.batch.resolve_price_inputs(row, verify_raw=False)
        assert resolved == [value.inputs[0], value.inputs[29]]
        resolved[0]['date'] = 'untrusted_mutation'
    assert value.catalog.call_count == 1
    leaf_checks = [call for call in value.checked.call_args_list if Path(call.args[0]).name.startswith('leaf_')]
    assert len(leaf_checks) == 30  # Canonical full validation once, not 30 per ticker.
    assert value.batch.resolve_price_inputs(row, verify_raw=False)[0]['date'] == value.inputs[0]['date']


def test_batch_store_detects_shared_bytes_change_after_first_validation(shared_store):
    value = shared_store
    value.batch.metadata('prices_daily_massive', 'AAA', 'raw')
    value.manifest.write_text(value.manifest.read_text() + ' ')
    with pytest.raises(ValueError, match='manifest SHA-256 mismatch'):
        value.batch.metadata('prices_daily_massive', 'BBB', 'raw')


@pytest.mark.parametrize('indexes', [[30], [-1], [0, 0]])
def test_batch_store_checks_each_tickers_indexes_even_after_shared_validation(shared_store, indexes):
    row = shared_store.batch.metadata('prices_daily_massive', 'AAA', 'raw')
    row['lineage']['inputs_manifest']['indexes'] = indexes
    with pytest.raises(ValueError, match='index out of bounds|indexes must be'):
        shared_store.batch.resolve_price_inputs(row, verify_raw=False)


def test_batch_store_changed_manifest_identity_revalidates_paths_and_raw_checks_remain_live(shared_store):
    value = shared_store
    row = value.batch.metadata('prices_daily_massive', 'AAA', 'raw')
    Path(value.inputs[0]['path']).write_text('changed raw file')
    with pytest.raises(ValueError, match='raw-input file SHA-256 mismatch'):
        value.batch.resolve_price_inputs(row, verify_raw=True)
    payload = json.loads(value.manifest.read_text())
    payload['inputs'][-1]['path'] = str(value.manifest.parent.parent / 'escaped.json')
    value.manifest.write_text(json.dumps(payload))
    row['lineage']['inputs_manifest']['sha256'] = module.prices.digest(value.manifest)
    with pytest.raises(ValueError, match='outside configured'):
        value.batch.resolve_price_inputs(row, verify_raw=False)


def test_internal_gap_requests_qualified_source_even_when_target_exists(case):
    case.raw.drop(index=130).to_parquet(case.raw_path, index=False)
    case.coverage['raw'].update(code_map={'US.TEST': {
        'ticker': 'TEST', 'paths': [str(case.raw_path)],
        'first_date': case.dates[0].strftime('%Y-%m-%d')}},
        file_sha256={str(case.raw_path): module.prices.digest(case.raw_path)})
    case.coverage_path.write_text(json.dumps(case.coverage))
    case.refs['coverage']['sha256'] = module.prices.digest(case.coverage_path)
    case.args[5] = {'massive': {'catalog_records': [{'ticker': 'TEST'}]}}
    repaired = module.prices._raw_frame(case.raw.iloc[[130]], 'US.TEST')
    proof = {'provider': 'MASSIVE_GROUPED', 'gap_fill': {'added_dates': [str(case.dates[130].date())]}}
    with patch.object(module.prices, '_qualified_massive_tail', return_value=(repaired, proof)) as gate:
        frame, lineage, gaps = module.build_price_features(*case.args)
    assert gate.call_args.kwargs['gap_dates'] == [str(case.dates[130].date())]
    assert len(frame) == 55 and not gaps
    assert lineage[0]['alternate_bridge'] == proof
