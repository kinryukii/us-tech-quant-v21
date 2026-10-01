"""Synthetic tests for current native 13F prices; no fitting or provider calls."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

SOURCE = Path(__file__).parents[1] / 'scripts/research/a2/inference/current_native_prices.py'
spec = importlib.util.spec_from_file_location('current_native_price_tests', SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Store:
    def __init__(self, paths, record):
        self.paths, self.record = paths, record

    def metadata(self, dataset, ticker, adjustment):
        if dataset != 'prices_daily':
            raise KeyError(dataset)
        return self.record

    def resolve_price_inputs(self, record, verify_raw=True):
        if verify_raw:
            for ref in record['lineage']['inputs']:
                module.prices.verify(ref['path'], ref['sha256'])
        return record['lineage']['inputs']

    def daily(self, ticker, adjustment, end_date=None, columns=None):
        frame = pd.read_parquet(self.record['path'])
        return frame.loc[pd.to_datetime(frame.date).le(pd.Timestamp(end_date)), columns].copy()


@pytest.fixture
def case(tmp_path, monkeypatch):
    from scripts.research.a2.inference.historical_top40_prices import _source, FEATURE_SOURCE_SHA
    paths = SimpleNamespace(backtest_root=tmp_path / 'backtests')
    dates = pd.bdate_range('2025-08-01', periods=170)
    target = dates[-1].strftime('%Y-%m-%d')
    leaf = pd.DataFrame({'ticker': 'NEW', 'moomoo_symbol': 'US.NEW', 'date': dates.astype(str),
        'open': 100. + np.arange(170) / 3., 'close': 100.5 + np.arange(170) / 3.,
        'high': 102. + np.arange(170) / 3., 'low': 99. + np.arange(170) / 3.,
        'volume': 10000 + np.arange(170) * 7, 'source': 'MOOMOO_OPEND', 'adjustment': 'raw'})
    leaf_path = tmp_path / 'native_raw.csv'
    leaf.to_csv(leaf_path, index=False)
    # Use the same round-trip parser as the publication layer.
    normalized = pd.read_csv(leaf_path).rename(columns={'moomoo_symbol': 'provider_code'})
    normalized['source_id'] = module.prices.digest(leaf_path)
    path = tmp_path / 'normalized.parquet'
    normalized.to_parquet(path, index=False)
    record = {'dataset': 'prices_daily', 'ticker': 'NEW', 'adjustment': 'raw', 'source': 'MOOMOO_OPEND',
              'format': 'parquet', 'path': str(path), 'source_sha256': module.prices.digest(path),
              'lineage': {'inputs': [{'path': str(leaf_path), 'sha256': module.prices.digest(leaf_path)}]}}
    coverage = {'raw': {'code_map': {}}, 'adjustment': {'wolf_event_date': '2025-09-29', 'wolf_new_shares_per_old_share': 0.008352}}
    coverage_path = paths.backtest_root / 'research/a2/demo_2026_calendar_replay/input_coverage.json'
    coverage_path.parent.mkdir(parents=True)
    coverage_path.write_text(json.dumps(coverage), encoding='utf-8')
    monkeypatch.setattr(module.prices, 'COVERAGE_SHA', module.prices.digest(coverage_path))
    factors = pd.DataFrame({'code': ['US.NEW'], 'ex_div_date': [dates[80]],
        'forward_adj_factorA': [0.5], 'forward_adj_factorB': [0.0], 'split_ratio': [2.0]})
    factor_path = tmp_path / 'fresh_rehab.parquet'
    factors.to_parquet(factor_path, index=False)
    rehab = {'source': 'MOOMOO_OPEND_GET_REHAB', 'target_date': target, 'results': [
        {'code': 'US.NEW', 'status': 'PASS', 'path': str(factor_path), 'sha256': module.prices.digest(factor_path),
         'row_count': 1, 'fetched_at': target + 'T23:00:00+00:00'}]}
    source_ref = {'path': 'D:/us-tech-quant/scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py', 'sha256': FEATURE_SOURCE_SHA}
    source = _source(source_ref)
    universe = {'current': True, 'universe_id': 'verified_synthetic_pool', 'effective_date': '2026-01-02',
                'members': [{'ticker': 'NEW', 'security_id': 'NEW_CUSIP', 'moomoo_symbol': 'US.NEW'}]}
    args = [universe, target, dates.strftime('%Y-%m-%d').tolist(), {}, Store(paths, record), rehab,
            source, source_ref, [{'ticker': 'NEW', 'reasons': ['ORIGINAL_RAW_ANCHOR_UNBOUND']}]]
    return SimpleNamespace(args=args, dates=dates, raw=leaf, path=path, leaf_path=leaf_path, record=record,
        factors=factors, factor_path=factor_path, coverage=coverage, coverage_path=coverage_path,
        source=source, source_ref=source_ref, universe=universe, rehab=rehab, target=target)


def test_native_features_equal_original_formula_without_frozen_membership_claim(case):
    with patch.object(case.source, 'build_stock_state_features', wraps=case.source.build_stock_state_features) as feature:
        frame, lineage, gaps = module.build_current_native_features(*case.args)
    assert feature.call_count == 1 and len(frame) == 1 and not gaps
    raw, _ = module._native_raw(case.args[4], 'NEW', 'US.NEW', case.target)
    adjusted, _ = module.prices._adapter(case.target).adjusted_price_frame('US.NEW', 'NEW', raw, case.factors,
        {'event_date': '2025-09-29', 'quantity_multiplier': 0.008352})
    expected = case.source.build_stock_state_features(adjusted[['ticker', 'trade_date', 'close', 'volume']])
    pd.testing.assert_frame_equal(frame.reset_index(drop=True), expected.loc[expected.trade_date.eq(pd.Timestamp(case.target)), frame.columns].reset_index(drop=True))
    proof = lineage[0]['anchor_proof']
    assert proof['kind'] == 'NEW_13F_MEMBER_NATIVE_RAW_ANCHOR' and proof['old_frozen_equivalence_claimed'] is False
    assert lineage[0]['raw_sources'][0]['role'] == 'NATIVE_MOOMOO_ANCHOR'
    assert proof['native_source'] == {k: v for k, v in lineage[0]['raw_sources'][0].items() if k != 'role'}
    assert lineage[0]['anchor_date'] == case.dates[0].strftime('%Y-%m-%d')
    assert lineage[0]['raw_end'] == case.target and len(lineage[0]['required_sessions']) == 121


@pytest.mark.parametrize('problem', ['source_hash', 'normalized_values', 'code', 'adjustment', 'source_id', 'source_label', 'missing_session', 'short_history', 'stale_rehab', 'rehab_hash', 'old_anchor'])
def test_native_input_failures_are_explicit_and_never_create_feature_rows(case, problem, monkeypatch):
    if problem == 'source_hash':
        case.leaf_path.write_bytes(b'changed')
    elif problem == 'stale_rehab':
        case.rehab['results'][0]['fetched_at'] = case.target + 'T09:00:00+00:00'
    elif problem == 'rehab_hash':
        case.factor_path.write_bytes(b'changed')
    elif problem == 'old_anchor':
        case.coverage['raw']['code_map'] = {'US.NEW': {'ticker': 'NEW'}}
        case.coverage_path.write_text(json.dumps(case.coverage), encoding='utf-8')
        monkeypatch.setattr(module.prices, 'COVERAGE_SHA', module.prices.digest(case.coverage_path))
    else:
        frame = pd.read_parquet(case.path)
        if problem == 'normalized_values':frame.loc[0, 'close'] += 1
        elif problem == 'code':frame['provider_code'] = 'US.OTHER'
        elif problem == 'adjustment':frame['adjustment'] = 'qfq'
        elif problem == 'source_id':frame['source_id'] = '0' * 64
        elif problem == 'source_label':frame['source'] = 'MASSIVE_GROUPED'
        elif problem == 'missing_session':frame = frame.drop(frame.index[-10])
        elif problem == 'short_history':frame = frame.iloc[-120:]
        frame.to_parquet(case.path, index=False)
        case.record['source_sha256'] = module.prices.digest(case.path)
    frame, lineage, gaps = module.build_current_native_features(*case.args)
    assert frame.empty and not lineage and len(gaps) == 1 and gaps[0]['ticker'] == 'NEW'


@pytest.mark.parametrize('reason', ['EXPANDED_ANCHOR_FROZEN_PRICE_MISMATCH', 'EXPANDED_ANCHOR_ORIGINAL_REHAB_NOT_PASS', 'MASSIVE_RAW_OVERLAP_MISMATCH:volume'])
def test_native_exception_cannot_rescue_existing_frozen_or_overlap_failure(case, reason):
    case.args[-1] = [{'ticker': 'NEW', 'reasons': [reason]}]
    with patch.object(module, '_native_raw', side_effect=AssertionError('MUST_NOT_ENTER')):
        frame, lineage, gaps = module.build_current_native_features(*case.args)
    assert frame.empty and not lineage and not gaps


def test_original_strict_tail_qualifier_is_reused_and_its_lineage_retained(case):
    full = pd.read_parquet(case.path)
    native = full.iloc[:-3].copy()
    native.to_parquet(case.path, index=False)
    case.record['source_sha256'] = module.prices.digest(case.path)
    tail = module.prices._raw_frame(full.iloc[-3:], 'US.NEW')
    bridge = {'provider': 'MASSIVE_GROUPED', 'volume_normalization': {'rule': 'WHOLE_SHARE_FLOOR'}, 'raw_inputs': [{'path': 'synthetic'}]}
    case.args[3] = {'massive': {'catalog_records': [{'ticker': 'NEW'}]}}
    with patch.object(module.prices, '_qualified_massive_tail', return_value=(tail, bridge)) as qualify:
        frame, lineage, gaps = module.build_current_native_features(*case.args)
    assert len(frame) == 1 and not gaps and qualify.call_count == 1
    assert lineage[0]['alternate_bridge'] is bridge
    assert lineage[0]['source'] == 'MOOMOO_RAW_PLUS_QUALIFIED_MASSIVE_TAIL_PLUS_MOOMOO_REHAB'
    with patch.object(module.prices, '_qualified_massive_tail', side_effect=ValueError('STRICT_OVERLAP_REJECTED')):
        frame, lineage, gaps = module.build_current_native_features(*case.args)
    assert frame.empty and not lineage and 'STRICT_OVERLAP_REJECTED' in gaps[0]['reason']


def test_internal_gap_uses_strict_bridge_even_when_native_reaches_target(case):
    full = pd.read_parquet(case.path)
    missing_day = case.dates[-10].strftime('%Y-%m-%d')
    full.drop(full.index[-10]).to_parquet(case.path, index=False)
    case.record['source_sha256'] = module.prices.digest(case.path)
    source_sha = module.prices.digest(case.path)
    fill = module.prices._raw_frame(full.iloc[[-10]], 'US.NEW')
    bridge = {'provider': 'MASSIVE_GROUPED', 'gap_fill': {'rule': 'MISSING_RAW_SESSIONS_ONLY',
        'requested_dates': [missing_day], 'added_dates': [missing_day]}}
    case.args[3] = {'massive': {'catalog_records': [{'ticker': 'NEW'}]}}
    with patch.object(module.prices, '_qualified_massive_tail', return_value=(fill, bridge)) as qualify:
        frame, lineage, gaps = module.build_current_native_features(*case.args)
    assert len(frame) == 1 and not gaps and qualify.call_count == 1
    assert qualify.call_args.kwargs == {'gap_dates': [missing_day]}
    assert lineage[0]['alternate_bridge'] is bridge
    assert module.prices.digest(case.path) == source_sha
    with patch.object(module.prices, '_qualified_massive_tail', side_effect=ValueError('FIVE_SESSION_OVERLAP_FAILED')):
        frame, lineage, gaps = module.build_current_native_features(*case.args)
    assert frame.empty and not lineage and 'FIVE_SESSION_OVERLAP_FAILED' in gaps[0]['reason']


def test_internal_gap_never_extends_native_history_before_first_observation(case):
    full = pd.read_parquet(case.path)
    full.iloc[-120:].to_parquet(case.path, index=False)
    case.record['source_sha256'] = module.prices.digest(case.path)
    case.args[3] = {'massive': {'catalog_records': [{'ticker': 'NEW'}]}}
    with patch.object(module.prices, '_qualified_massive_tail', side_effect=AssertionError('MUST_NOT_BACKFILL_IPO')):
        frame, lineage, gaps = module.build_current_native_features(*case.args)
    assert frame.empty and not lineage and 'CONTIGUOUS_121_SESSIONS_INCOMPLETE' in gaps[0]['reason']


def test_batch_internal_gap_uses_earliest_requested_feature_window(case):
    full = pd.read_parquet(case.path)
    # Index 45 is needed by the first requested day, outside latest-day 121.
    missing_day = case.dates[45].strftime('%Y-%m-%d')
    full.drop(full.index[45]).to_parquet(case.path, index=False)
    case.record['source_sha256'] = module.prices.digest(case.path)
    fill = module.prices._raw_frame(full.iloc[[45]], 'US.NEW')
    signal_dates = case.dates[-8:].strftime('%Y-%m-%d').tolist()
    acquired = {'massive': {'catalog_records': [{'ticker': 'NEW'}]}}
    bridge = {'provider': 'MASSIVE_GROUPED', 'gap_fill': {'requested_dates': [missing_day]}}
    with patch.object(module.prices, '_qualified_massive_tail', return_value=(fill, bridge)) as qualify:
        frame, lineage, gaps = module.build_native_2026_feature_candidates(case.universe['members'], signal_dates,
            case.args[2], acquired, case.args[4], case.rehab, case.source, case.source_ref, case.args[-1], observed_target=case.target)
    assert frame.trade_date.dt.strftime('%Y-%m-%d').tolist() == signal_dates and not gaps
    assert qualify.call_args.kwargs == {'gap_dates': [missing_day]}


def test_batch_2026_candidates_load_once_match_single_day_and_keep_membership_deferred(case):
    signal_dates = case.dates[-8:].strftime('%Y-%m-%d').tolist()
    with patch.object(module, '_native_raw', wraps=module._native_raw) as load, \
         patch.object(case.source, 'build_stock_state_features', wraps=case.source.build_stock_state_features) as feature:
        batch, lineage, gaps = module.build_native_2026_feature_candidates(case.universe['members'], signal_dates,
            case.args[2], {}, case.args[4], case.rehab, case.source, case.source_ref, case.args[-1], observed_target=case.target)
    assert load.call_count == feature.call_count == 1 and len(batch) == 8 and not gaps
    assert lineage[0]['membership_validation'] == 'REQUIRES_DOWNSTREAM_DAILY_PIT_JOIN'
    assert lineage[0]['universe_id'] is None and lineage[0]['feature_rows'] == 8
    args = list(case.args);args[1] = signal_dates[0]
    single, _, _ = module.build_current_native_features(*args, observed_target=case.target)
    pd.testing.assert_frame_equal(single.reset_index(drop=True), batch.iloc[:1].reset_index(drop=True))
    with pytest.raises(ValueError, match='2026_ONLY'):
        module.build_native_2026_feature_candidates(case.universe['members'], ['2025-12-31', *signal_dates],
            case.args[2], {}, case.args[4], case.rehab, case.source, case.source_ref, case.args[-1], observed_target=case.target)


def test_batch_121_gate_only_emits_eligible_dates_without_filling_new_listings(case):
    requested = case.dates[118:125].strftime('%Y-%m-%d').tolist()
    args = list(case.args);args[2] = pd.bdate_range('2025-01-01', case.target).strftime('%Y-%m-%d').tolist()
    batch, lineage, gaps = module.build_native_2026_feature_candidates(case.universe['members'], requested,
        args[2], {}, args[4], case.rehab, case.source, case.source_ref, args[-1], observed_target=case.target)
    assert batch.trade_date.dt.strftime('%Y-%m-%d').tolist() == requested[2:]
    assert gaps[0]['missing_feature_dates'] == requested[:2]


def test_batch_same_transport_identity_changes_remain_for_downstream_pit_join(case):
    members = [*case.universe['members'], {**case.universe['members'][0], 'security_id': 'EARLIER_CUSIP'}]
    with patch.object(module, '_native_raw', wraps=module._native_raw) as load:
        frame, lineage, gaps = module.build_native_2026_feature_candidates(members, [case.target], case.args[2],
            {}, case.args[4], case.rehab, case.source, case.source_ref, case.args[-1], observed_target=case.target)
    assert len(frame) == 1 and load.call_count == 1 and not gaps
    assert lineage[0]['security_id'] is None and lineage[0]['security_ids'] == ['EARLIER_CUSIP', 'NEW_CUSIP']
    case.universe['members'] = members
    frame, lineage, gaps = module.build_current_native_features(*case.args)
    assert frame.empty and 'IDENTITY_AMBIGUOUS' in gaps[0]['reason']


def test_run_cache_reuses_source_projection_but_final_hash_detects_mutation(case):
    import os
    cache = module._RunCache({'US.NEW'})
    with patch.object(pd, 'read_csv', wraps=pd.read_csv) as read:
        first, proof = module._native_raw(case.args[4], 'NEW', 'US.NEW', case.target, cache)
        again, repeated = module._native_raw(case.args[4], 'NEW', 'US.NEW', case.target, cache)
    assert read.call_count == 1 and proof == repeated
    pd.testing.assert_frame_equal(first, again)
    cache.finish()
    before = case.leaf_path.stat()
    content = case.leaf_path.read_bytes()
    changed = content.replace(b'100.5', b'101.5', 1)
    assert changed != content and len(changed) == len(content)
    case.leaf_path.write_bytes(changed)
    os.utime(case.leaf_path, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(ValueError, match='PRICE_SOURCE_HASH_MISMATCH'):
        cache.finish()


@pytest.fixture
def sq_case(case):
    # Provider files remain XYZ. Only the registered logical member is SQ.
    leaf = pd.read_csv(case.leaf_path)
    leaf['ticker'], leaf['moomoo_symbol'] = 'XYZ', 'US.XYZ'
    leaf.to_csv(case.leaf_path, index=False)
    normalized = pd.read_csv(case.leaf_path).rename(columns={'moomoo_symbol': 'provider_code'})
    normalized['source_id'] = module.prices.digest(case.leaf_path)
    normalized.to_parquet(case.path, index=False)
    case.record.update(ticker='XYZ', source_sha256=module.prices.digest(case.path))
    case.record['lineage']['inputs'][0]['sha256'] = module.prices.digest(case.leaf_path)
    case.universe['members'] = [{'ticker': 'SQ', 'security_id': '852234103', 'moomoo_symbol': 'US.XYZ'}]
    case.args[-1] = [{'ticker': 'SQ', 'reasons': ['ORIGINAL_RAW_ANCHOR_UNBOUND']}]
    case.factors['code'] = 'US.XYZ'
    case.factors.to_parquet(case.factor_path, index=False)
    case.rehab['results'][0].update(code='US.XYZ', sha256=module.prices.digest(case.factor_path))
    return case


def test_verified_sq_transport_alias_preserves_provider_source_and_logical_features(sq_case):
    before = {path: module.prices.digest(path) for path in (sq_case.leaf_path, sq_case.path)}
    frame, lineage, gaps = module.build_current_native_features(*sq_case.args)
    assert not gaps and len(frame) == 1 and frame.ticker.tolist() == ['SQ']
    proof = lineage[0]['anchor_proof']['native_source']
    assert proof['transport_alias_proof'] == module.SQ_TRANSPORT_ALIAS
    assert module.validate_explicit_alias(proof['transport_alias_proof'], 'SQ', 'US.XYZ', ['852234103']) == 'XYZ'
    assert lineage[0]['raw_sources'][0] == {**proof, 'role': 'NATIVE_MOOMOO_ANCHOR'}
    assert pd.read_parquet(sq_case.path).ticker.eq('XYZ').all()
    assert all(module.prices.digest(path) == sha for path, sha in before.items())


@pytest.mark.parametrize('problem', ['arbitrary_ticker', 'different_code', 'different_security', 'evidence_drift'])
def test_explicit_alias_rejects_unreviewed_identity_or_evidence(sq_case, problem):
    proof = dict(module.SQ_TRANSPORT_ALIAS)
    ticker, code, ids = 'SQ', 'US.XYZ', ['852234103']
    if problem == 'arbitrary_ticker':
        ticker = 'OTHER'; proof['logical_ticker'] = ticker
    elif problem == 'different_code':
        code = 'US.OTHER'; proof['provider_code'] = code
    elif problem == 'different_security':
        ids = ['OTHER_CUSIP']; proof['security_id'] = ids[0]
    else:
        proof['evidence_url'] = 'https://example.invalid/rebranding'
    with pytest.raises(ValueError, match='EXPLICIT_TRANSPORT_ALIAS_INVALID'):
        module.validate_explicit_alias(proof, ticker, code, ids)
    with pytest.raises(ValueError, match='EXPLICIT_TRANSPORT_ALIAS_INVALID'):
        module._native_raw(sq_case.args[4], ticker, code, sq_case.target, transport_alias_proof=proof)


def test_sq_alias_native_rows_must_still_match_registered_provider_code(sq_case):
    normalized = pd.read_parquet(sq_case.path)
    normalized['provider_code'] = 'US.OTHER'
    normalized.to_parquet(sq_case.path, index=False)
    sq_case.record['source_sha256'] = module.prices.digest(sq_case.path)
    frame, lineage, gaps = module.build_current_native_features(*sq_case.args)
    assert frame.empty and not lineage and 'ROW_PROVENANCE_MISMATCH' in gaps[0]['reason']


@pytest.mark.parametrize('mapped_logical_source', [False, True])
def test_sq_massive_tail_keeps_reviewed_mapping_and_provider_ticker(sq_case, mapped_logical_source):
    full = pd.read_parquet(sq_case.path)
    full.iloc[:-3].to_parquet(sq_case.path, index=False)
    sq_case.record['source_sha256'] = module.prices.digest(sq_case.path)
    tail = module.prices._raw_frame(full.iloc[-3:], 'US.XYZ')
    if mapped_logical_source:
        record = {'ticker': 'SQ', 'lineage': {'provider_mapping': {
            'provider_symbol': 'XYZ', 'evidence_url': module.SQ_TRANSPORT_ALIAS['evidence_url']}}}
    else:
        record = {'ticker': 'XYZ'}
    sq_case.args[3] = {'massive': {'catalog_records': [record]}}
    bridge = {'provider': 'MASSIVE_GROUPED', 'provider_symbol': 'XYZ', 'normalized_sha256': '1' * 64}
    with patch.object(module.prices, '_qualified_massive_tail', return_value=(tail, bridge)) as qualify:
        frame, lineage, gaps = module.build_current_native_features(*sq_case.args)
    assert not gaps and len(frame) == 1 and frame.ticker.tolist() == ['SQ']
    assert qualify.call_count == 1 and qualify.call_args.args[2] == record['ticker']
    expected = bridge if mapped_logical_source else {**bridge, 'transport_alias_proof': module.SQ_TRANSPORT_ALIAS}
    assert lineage[0]['alternate_bridge'] == expected
    if mapped_logical_source:
        record['lineage']['provider_mapping']['evidence_url'] = 'https://example.invalid/alias'
        with patch.object(module.prices, '_qualified_massive_tail', side_effect=AssertionError('MUST_NOT_QUALIFY')):
            frame, lineage, gaps = module.build_current_native_features(*sq_case.args)
        assert frame.empty and not lineage and 'EXPLICIT_MAPPING_REQUIRED' in gaps[0]['reason']


def test_native_feature_reference_path_is_json_serializable(case):
    case.source_ref['path'] = Path(case.source_ref['path'])
    frame, lineage, gaps = module.build_current_native_features(*case.args)
    assert len(frame) == 1 and not gaps
    encoded = json.dumps({'lineage': lineage, 'gaps': gaps}, allow_nan=False)
    assert json.loads(encoded)['lineage'][0]['feature_source']['path'] == str(case.source_ref['path'])
