import importlib.util
from pathlib import Path
import pandas as pd
import pytest
import json
from copy import deepcopy
from types import SimpleNamespace

from apps.demo_console.adapters import selected_strategies_reader as selected
from apps.demo_console.tests.test_selected_strategies_reader_workspace import package as selected_package

spec = importlib.util.spec_from_file_location('stock_history_subject', Path(__file__).parents[1] / 'adapters/stock_history_reader.py')
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def fixture():
    ledger = pd.DataFrame([{'target_date': day, 'snapshot_id': snap, 'universe_id': snap, 'quarter': '2025Q1'}
        for day, snap in [('2025-01-03', 'a'), ('2025-01-06', 'a'), ('2025-01-07', 'a'), ('2025-01-08', 'b')]])
    members = pd.DataFrame([{'snapshot_id': 'a', 'ticker': t, 'security_id': s, 'issuer_name': t, 'mapping_verified': True}
                           for t, s in [('ABC', 'id1'), ('NEVER', 'id2')]])
    ranked = pd.DataFrame([{'target_date': day, 'ticker': 'ABC', 'security_id': 'id1', 'rank': rank,
                            'score': .1, 'universe_id': 'a'}
                          for day, rank in [('2025-01-03', 12), ('2025-01-07', 4)]])
    return ranked, ledger, members


def test_missing_rank_breaks_episode_and_outside_pool_is_distinct():
    result = subject.query_history(subject.prepare_history(*fixture()), 'abc')
    assert result['summary']['top20_days'] == 2
    assert result['summary']['top20_episodes'] == 2
    assert result['summary']['unranked_pool_days'] == 1
    assert result['summary']['outside_pool_days'] == 1
    assert [r['status'] for r in result['daily']] == ['RANKED', 'NO_VERIFIED_RANK', 'RANKED', 'OUTSIDE_POOL']


def test_never_ranked_in_catalog_has_zero_entries_not_beyond_top40():
    h = subject.prepare_history(*fixture())
    assert 'NEVER' in [r['ticker'] for r in h['catalog']]
    result = subject.query_history(h, 'NEVER')
    assert result['summary']['top40_days'] == 0
    assert result['summary']['ranked_days'] == 0
    assert result['summary']['unranked_pool_days'] == 3
    assert result['summary']['best_rank'] is None
    assert subject.query_history(h, 'UNKNOWN')['status'] == 'NOT_FOUND'


def test_duplicate_ticker_identity_requires_selection():
    ranked, ledger, members = fixture()
    members = pd.concat([members, pd.DataFrame([dict(members.iloc[0], security_id='other')])])
    h = subject.prepare_history(ranked, ledger, members)
    assert subject.query_history(h, 'ABC')['status'] == 'AMBIGUOUS_IDENTITY'
    assert subject.query_history(h, 'ABC', security_id='other')['summary']['ranked_days'] == 0


def test_rx_parent_binding_and_window_counts():
    ranked, ledger, members = fixture()
    rx = ranked.iloc[:1][['target_date', 'ticker', 'security_id', 'rank']]
    h = subject.prepare_history(ranked, ledger, members, rx)
    result = subject.query_history(h, 'ABC', '2025-01-06', '2025-01-08')
    assert result['summary']['top20_days'] == 1
    assert result['summary']['rx_selected_days'] == 0
    assert result['rx_available']
    rx = rx.assign(security_id='bad')
    with pytest.raises(ValueError, match='RX_OUTSIDE'):
        subject.prepare_history(ranked, ledger, members, rx)


def test_rank_not_in_verified_pool_rejected():
    ranked, ledger, members = fixture()
    with pytest.raises(ValueError, match='OUTSIDE_VERIFIED_POOL'):
        subject.prepare_history(ranked.assign(security_id='bad'), ledger, members)


def test_weekend_does_not_break_consecutive_trading_days():
    ranked, ledger, members = fixture()
    ranked.loc[1, 'target_date'] = '2025-01-06'
    result = subject.query_history(subject.prepare_history(ranked, ledger, members), 'ABC')
    assert result['summary']['top20_episodes'] == 1
    assert result['episodes'][0]['trading_days'] == 2


def test_cache_reuses_validated_index_and_stamp_change_reloads(monkeypatch):
    ranked, ledger, members = fixture()
    ref = {'path': 'parent', 'sha256': 'a' * 64}
    hist_ref = {'path': 'historical', 'sha256': 'b' * 64}
    payloads = {'parent': {'ranking_manifest': hist_ref}, 'historical': {
        'outputs': {'ranked': 'r'}, 'universe_outputs': {'ledger': 'l', 'members': 'm'}}}
    monkeypatch.setattr(subject, '_checked_json', lambda r: payloads[r['path']])
    calls = []
    def frame(r, parent, columns):
        calls.append(r)
        return {'r': ranked, 'l': ledger, 'm': members}[r]
    monkeypatch.setattr(subject, '_frame', frame)
    monkeypatch.setattr(subject.base, '_hash', lambda p: 'a' * 64)
    stamp = ['parent', 'a' * 64, 10, 1]
    monkeypatch.setattr(subject.base, '_stamp', lambda r: tuple(stamp))
    subject._cached_history.cache_clear()

    args = (json.dumps(ref), json.dumps(hist_ref), 'null')
    subject._cached_history(*args, (tuple(stamp),))
    subject._cached_history(*args, (tuple(stamp),))
    assert len(calls) == 3
    stamp[-1] = 2
    subject._cached_history(*args, (tuple(stamp),))
    assert len(calls) == 6
    subject._cached_history.cache_clear()


def test_verified_company_preserves_identity_and_continuous_days(monkeypatch):
    ranked, ledger, members = fixture()
    ledger.loc[1:, ['snapshot_id', 'universe_id']] = 'b'
    members = pd.concat([members, pd.DataFrame([dict(members.iloc[0], snapshot_id='b', security_id='id3')])])
    ranked.loc[1, ['target_date', 'security_id', 'universe_id']] = ['2025-01-06', 'id3', 'b']
    h = subject.prepare_history(ranked, ledger, members)
    monkeypatch.setattr(subject, '_company_chain', lambda *args: {'status': 'VERIFIED', 'security_ids': ['id1', 'id3']})
    result = subject.query_history(h, 'ABC', identity_mode='VERIFIED_COMPANY')
    assert result['status'] == 'READY'
    assert result['summary']['top20_days'] == 2
    assert result['summary']['top20_episodes'] == 1
    assert [r['security_id'] for r in result['daily'][:2]] == ['id1', 'id3']


def test_unverified_company_must_not_union_same_ticker(monkeypatch):
    ranked, ledger, members = fixture()
    members = pd.concat([members, pd.DataFrame([dict(members.iloc[0], security_id='other')])])
    h = subject.prepare_history(ranked, ledger, members)
    monkeypatch.setattr(subject, '_company_chain', lambda *args: {'status': 'UNAVAILABLE'})
    assert subject.query_history(h, 'ABC', identity_mode='VERIFIED_COMPANY')['status'] == 'COMPANY_CHAIN_UNAVAILABLE'
    assert subject.query_history(h, 'ABC')['status'] == 'AMBIGUOUS_IDENTITY'


def applied_fixture():
    days = ('2026-01-02', '2026-01-05', '2026-01-06', '2026-01-07', '2026-09-23', '2026-09-24')
    members = pd.DataFrame([{'snapshot_id': 'pool', 'ticker': f'T{i:02d}', 'security_id': f'id{i:02d}',
        'issuer_name': f'Company {i}', 'mapping_verified': True} for i in range(1, 42)] +
        [{'snapshot_id': 'pool', 'ticker': 'NEVER', 'security_id': 'never', 'issuer_name': 'Never scored', 'mapping_verified': True}])
    ledger = pd.DataFrame([{'target_date': day, 'snapshot_id': 'pool', 'universe_id': 'pool', 'quarter': '2026Q1'} for day in days])
    ranked = pd.DataFrame([{'target_date': day, 'ticker': f'T{i:02d}', 'security_id': f'id{i:02d}',
        'rank': i, 'score': 1 - i / 1000, 'universe_id': 'pool'} for day in days for i in range(1, 42)])
    raw = subject.prepare_history(ranked, ledger, members)
    raw['source_refs'] = {'a2': {'path': 'parent', 'sha256': 'ab' * 32}}
    package = selected_package()
    package['raw_reference'] = {'strategy_id': 'RAW_A2', 'label': 'Raw A2',
        'performance_period': deepcopy(package['performance_period']),
        **{key: deepcopy(package['strategies']['HGB_DIAG_5'][key]) for key in ('daily', 'summary', 'targets')}}
    for sid, ticker, weight in (('HGB_DIAG_5', 'T01', .1), ('HGB_FACTOR_5', 'T02', .08)):
        strategy = package['strategies'][sid]
        target = {'ticker': ticker, 'target_weight': weight, 'weight_before': 0., 'action': 'BUY'}
        for row in strategy['targets']:
            row['rows'] = [deepcopy(target)]
        strategy['application'].update(rows=[deepcopy(target)], target_cash_weight=1-weight)
    def scores(day):
        return [{'signal_date': day, 'ticker': f'T{i:02d}', 'security_id': f'id{i:02d}',
                 'raw_rank': i, 'raw_score': 1-i/1000, 'pred_hgb': i/1000, 'hgb_rank': 41-i} for i in range(1, 41)]
    package['shared_scores'] = {'model_id': 'HGB_2026092501', 'model_sha256': 'ab' * 32,
        'scoring_scope': 'RAW_TOP40', 'ranking_basis': 'PRED_HGB_DESC_TICKER_ASC',
        'historical': [row for day in ('2026-01-02', '2026-01-05', '2026-01-07') for row in scores(day)],
        'current': {'status': 'READY', 'signal_date': '2026-09-24', 'requested_signal_date': '2026-09-24',
            'rows': [{key: value for key, value in row.items() if key != 'signal_date'} for row in scores('2026-09-24')], 'reason': ''}}
    return raw, selected.validate_package(package)


def test_applied_rankings_share_hgb_model_rank_but_keep_each_risk_target():
    raw, package = applied_fixture()
    history = subject.prepare_applied_history(raw, package, '2026-09-24')
    view = subject.load_applied_rankings('2026-09-24', history=history)
    assert view['status'] == 'READY'
    assert len(view['strategies']['RAW_A2']['rows']) == 41
    diag, factor = (view['strategies'][sid] for sid in selected.STRATEGY_IDS)
    assert [(r['ticker'], r['model_rank'], r['score']) for r in diag['rows']] == [
        (r['ticker'], r['model_rank'], r['score']) for r in factor['rows']]
    assert diag['rows'][0]['ticker'] == 'T40' and diag['rows'][0]['eligible'] is False
    assert diag['rows'][0]['selected'] is False and diag['rows'][0]['target_weight'] == 0
    assert next(r for r in diag['rows'] if r['ticker'] == 'T01')['target_weight'] == .1
    assert next(r for r in factor['rows'] if r['ticker'] == 'T01')['target_weight'] == 0
    assert view['strategies']['RAW_A2']['target_kind'] == 'RAW_RULE_TARGET'
    assert sum(r['target_weight'] for r in view['strategies']['RAW_A2']['rows']) == pytest.approx(1)


def test_applied_exact_day_gap_never_borrows_current_score_or_historical_target():
    raw, package = applied_fixture()
    history = subject.prepare_applied_history(raw, package, '2026-09-24')
    view = subject.load_applied_rankings('2026-09-23', history=history)
    assert view['status'] == 'PARTIAL'
    for sid in selected.STRATEGY_IDS:
        assert view['strategies'][sid]['rows'] == []
        assert view['strategies'][sid]['actual_signal_date'] is None
        assert view['strategies'][sid]['target_status'] == 'NO_RECORDED_TARGET'
    query = subject.query_applied_history(history, 'T01', '2026-09-23', '2026-09-23')
    for row in query['daily']:
        for sid in selected.STRATEGY_IDS:
            assert row['strategies'][sid]['selected'] is None
            assert row['strategies'][sid]['target_weight'] is None
            assert row['strategies'][sid]['weight_date'] is None


def test_applied_scored_date_without_target_has_unknown_selection():
    raw, package = applied_fixture()
    history = subject.prepare_applied_history(raw, package, '2026-09-24')
    result = subject.query_applied_history(history, 'T01', '2026-01-07', '2026-01-07')
    row = result['daily'][0]['strategies']['HGB_DIAG_5']
    assert row['score'] == .001 and row['model_rank'] == 40
    assert row['selected'] is None and row['target_weight'] is None
    assert result['strategy_summary']['HGB_DIAG_5']['known_target_days'] == 0
    outside = subject.query_applied_history(history, 'T40', '2026-01-07', '2026-01-07')['daily'][0]
    assert outside['strategies']['HGB_DIAG_5']['raw_top20'] is False
    assert outside['strategies']['HGB_DIAG_5']['eligible'] is None


def test_hgb_held_outside_top20_remains_an_allocation_candidate():
    raw, package = applied_fixture()
    target = package['strategies']['HGB_DIAG_5']['targets'][0]
    target['rows'].append({'ticker': 'T40', 'target_weight': 0., 'weight_before': .07, 'action': 'SELL'})
    history = subject.prepare_applied_history(raw, package, '2026-09-24')
    row = subject.query_applied_history(history, 'T40', '2026-01-02', '2026-01-02')['daily'][0]['strategies']['HGB_DIAG_5']
    assert row['raw_top20'] is False and row['eligible'] is True
    assert row['selected'] is False and row['target_weight'] == 0
    assert row['weight_date'] == '2026-01-02'


def test_applied_unselected_and_never_scored_stock_remain_searchable():
    raw, package = applied_fixture()
    history = subject.prepare_applied_history(raw, package, '2026-09-24')
    outside = subject.query_applied_history(history, 'T41', '2026-09-24', '2026-09-24')['daily'][0]
    assert outside['strategies']['RAW_A2']['model_rank'] == 41
    assert outside['strategies']['RAW_A2']['selected'] is False
    assert outside['strategies']['HGB_DIAG_5']['score_status'] == 'OUTSIDE_RAW_TOP40'
    assert outside['strategies']['HGB_DIAG_5']['model_rank'] is None
    never = subject.query_applied_history(history, 'NEVER', '2026-09-24', '2026-09-24')['daily'][0]
    assert never['status'] == 'NO_VERIFIED_RANK'
    assert never['strategies']['RAW_A2']['selected'] is None
    assert never['strategies']['HGB_DIAG_5']['selected'] is None
    assert subject.query_applied_history(history, 'UNKNOWN')['status'] == 'NOT_FOUND'


def test_applied_cutoff_hides_later_scores_targets_and_dates():
    raw, package = applied_fixture()
    history = subject.prepare_applied_history(raw, package, '2026-09-23')
    result = subject.query_applied_history(history, 'T01', end_date='2026-09-24')
    assert result['end_date'] == '2026-09-23'
    assert all(row['date'] <= '2026-09-23' for row in result['daily'])
    assert history['end_date'] == '2026-09-23'
    with pytest.raises(ValueError, match='EXCEEDS_OBSERVATION_CUTOFF'):
        subject.load_applied_rankings('2026-09-24', history=history)


def test_applied_cusip_ambiguity_and_verified_chain_use_existing_identity_contract(monkeypatch):
    raw, package = applied_fixture()
    raw['_members'] = pd.concat([raw['_members'], pd.DataFrame([
        {'snapshot_id': 'pool', 'ticker': 'T01', 'security_id': 'other', 'issuer_name': 'Other', 'mapping_verified': True}])])
    history = subject.prepare_applied_history(raw, package, '2026-09-24')
    assert subject.query_applied_history(history, 'T01')['status'] == 'AMBIGUOUS_IDENTITY'
    other = subject.query_applied_history(history, 'T01', security_id='other')
    assert all(row['strategies']['HGB_DIAG_5']['score'] is None for row in other['daily'])
    assert all(row['strategies']['HGB_DIAG_5']['selected'] is None for row in other['daily'])
    monkeypatch.setattr(subject, '_company_chain', lambda *a: {'status': 'UNAVAILABLE'})
    assert subject.query_applied_history(history, 'T01', identity_mode='VERIFIED_COMPANY')['status'] == 'COMPANY_CHAIN_UNAVAILABLE'


def test_applied_blocked_current_never_becomes_zero_target():
    raw, package = applied_fixture()
    for sid in selected.STRATEGY_IDS:
        package['strategies'][sid]['application'].update(status='BLOCKED', signal_date=None,
            requested_signal_date='2026-09-24', rows=[], target_cash_weight=None, reason='missing inputs')
    package['shared_scores']['current'].update(status='BLOCKED', signal_date=None, rows=[], reason='missing inputs')
    history = subject.prepare_applied_history(raw, package, '2026-09-24')
    snapshot = subject.load_applied_rankings('2026-09-24', history=history)
    assert snapshot['strategies']['RAW_A2']['status'] == 'AVAILABLE'
    assert snapshot['strategies']['HGB_DIAG_5']['status'] == 'BLOCKED'
    row = subject.query_applied_history(history, 'T01', '2026-09-24', '2026-09-24')['daily'][0]
    assert row['strategies']['HGB_DIAG_5']['target_status'] == 'BLOCKED'
    assert row['strategies']['HGB_DIAG_5']['selected'] is None


def test_applied_scores_cannot_inherit_a_different_raw_score():
    raw, package = applied_fixture()
    raw['_ranked'].loc[(raw['_ranked'].target_date == '2026-01-02') & (raw['_ranked'].ticker == 'T01'), 'score'] = 999
    with pytest.raises(ValueError, match='RAW_BINDING_MISMATCH'):
        subject.prepare_applied_history(raw, package, '2026-09-24')


@pytest.mark.parametrize('defer_index', [False, True])
def test_daily_full_rankings_replace_only_bound_top40_tail_and_keep_excluded_members(monkeypatch, defer_index):
    raw, _ = applied_fixture()
    raw = subject.prepare_history(raw['_ranked'].loc[raw['_ranked'].target_date.eq('2026-01-02')],
        raw['_ledger'].loc[raw['_ledger'].target_date.eq('2026-01-02')], raw['_members'])
    raw['_archive_end'] = raw['end_date']
    rows = [{'target_date': '2026-09-24', 'ticker': f'T{i:02d}', 'security_id': f'id{i:02d}',
             'rank': i, 'score': 1-i/1000, 'universe_id': 'pool'} for i in range(1, 42)]
    raw = subject._append_recorded_rankings(raw, rows[:40],
        {'target_date': '2026-09-24', 'snapshot_id': 'pool', 'universe_id': 'pool', 'quarter': '2026Q2'},
        raw['_members'], scope='RECORDED_TOP40_ONLY', coverage={'status': 'PARTIAL'}, defer_index=defer_index)
    report = {'status': 'READY', 'data_date': '2026-09-24', 'model_id': 'A2_HGB',
        'model_sha256': subject.base.MODEL_2026_SHA, 'ranked_rows': rows,
        'coverage': {'mapped_count': 42, 'eligible_count': 41, 'excluded_count': 1},
        'universe': {'report_path': 'C:/synthetic/universe_report.json', 'universe_members_sha256': 'ab'*32,
                     'universe_id': 'pool', 'quarter': '2026Q2', 'universe_member_count': 42}}
    monkeypatch.setattr(subject, '_checked_json', lambda ref: report)
    monkeypatch.setattr(subject, '_frame', lambda *a: raw['_members'][['ticker', 'security_id']].copy())
    merged = subject._append_daily_report(raw, {'path': 'report', 'sha256': 'cd'*32}, '2026-09-24',
        defer_index=defer_index)
    assert len(merged['_ranked'].loc[merged['_ranked'].target_date.eq('2026-09-24')]) == 41
    assert merged['_score_scope']['2026-09-24'] == 'FULL_VERIFIED_POOL'
    never = subject.query_history(merged, 'NEVER', '2026-09-24', '2026-09-24')
    assert never['daily'][0]['status'] == 'NO_VERIFIED_RANK'
    assert merged['_coverage']['2026-09-24']['excluded_count'] == 1


@pytest.mark.parametrize('defer_index', [False, True])
def test_daily_overlay_rejects_changed_same_date_top40(monkeypatch, defer_index):
    raw, _ = applied_fixture()
    rows = raw['_ranked'].loc[raw['_ranked'].target_date.eq('2026-09-24')].to_dict('records')
    rows[0]['score'] = 999
    with pytest.raises(ValueError, match='RANKING_CONFLICT'):
        subject._append_recorded_rankings(raw, rows,
            {'target_date': '2026-09-24', 'snapshot_id': 'pool', 'universe_id': 'pool', 'quarter': '2026Q2'},
            raw['_members'], scope='FULL_VERIFIED_POOL', coverage={}, defer_index=defer_index)


def test_deferred_daily_preparation_preserves_complete_applied_view():
    original, package = applied_fixture()
    first = original['_ledger'].target_date.min()
    archive = subject.prepare_history(original['_ranked'].loc[original['_ranked'].target_date.eq(first)],
        original['_ledger'].loc[original['_ledger'].target_date.eq(first)], original['_members'])
    archive['_archive_end'] = first
    complete = []
    for deferred in (False, True):
        history = archive
        for day in original['_ledger'].target_date.loc[lambda values: values.ne(first)]:
            records = original['_ranked'].loc[original['_ranked'].target_date.eq(day)].to_dict('records')
            ledger_row = original['_ledger'].loc[original['_ledger'].target_date.eq(day)].iloc[0].to_dict()
            for rows, scope in ((records[:40], 'RECORDED_TOP40_ONLY'), (records, 'FULL_VERIFIED_POOL')):
                history = subject._append_recorded_rankings(history, rows, ledger_row,
                    original['_members'], scope=scope, coverage={'status': 'READY'}, defer_index=deferred)
        complete.append(subject.prepare_applied_history(history, package, '2026-09-24'))
    for key in ('catalog', 'available_dates', 'start_date', 'end_date', 'source_refs', '_scores', '_targets'):
        assert complete[0][key] == complete[1][key]
    for key in ('_ranked', '_ledger', '_members', '_rank_index'):
        pd.testing.assert_frame_equal(complete[0]['raw_history'][key], complete[1]['raw_history'][key])
    for ticker in ('T01', 'T40', 'T41', 'NEVER'):
        assert subject.query_applied_history(complete[0], ticker) == subject.query_applied_history(complete[1], ticker)


@pytest.mark.parametrize('defer_index', [False, True])
@pytest.mark.parametrize('fault,error', [('identity', 'DUPLICATE_RANK_IDENTITY'),
    ('pool', 'POOL_BINDING_MISMATCH'), ('member', 'RANK_OUTSIDE_VERIFIED_POOL'),
    ('rank', 'RANKING_INCOMPLETE_OR_NONFINITE'), ('score', 'RANKING_INCOMPLETE_OR_NONFINITE')])
def test_daily_preparation_rejects_invalid_overlay_before_later_replacement(defer_index, fault, error):
    raw, _ = applied_fixture()
    rows = raw['_ranked'].loc[raw['_ranked'].target_date.eq('2026-09-24')].to_dict('records')
    raw = subject.prepare_history(raw['_ranked'].loc[raw['_ranked'].target_date.eq('2026-01-02')],
        raw['_ledger'].loc[raw['_ledger'].target_date.eq('2026-01-02')], raw['_members'])
    members = raw['_members'].assign(snapshot_id='new')
    if fault == 'identity':
        rows[1]['security_id'] = rows[0]['security_id']
    elif fault == 'pool':
        rows[0]['universe_id'] = 'other'
    elif fault == 'member':
        members = members.loc[members.ticker.ne('T01')]
    elif fault == 'rank':
        rows[0]['rank'] = 2
    else:
        rows[0]['score'] = float('nan')
    with pytest.raises(ValueError, match=error):
        subject._append_recorded_rankings(raw, rows,
            {'target_date': '2026-09-24', 'snapshot_id': 'new', 'universe_id': 'pool', 'quarter': '2026Q2'},
            members, scope='RECORDED_TOP40_ONLY', coverage={}, defer_index=defer_index)


def test_applied_cache_reuses_binding_across_cutoffs_and_rechecks_hashes(monkeypatch):
    from apps.demo_console.adapters import workspace_reader as workspace
    raw, package = applied_fixture()
    parent_ref = {'path': 'parent', 'sha256': 'a' * 64}
    hist_ref = {'path': 'historical', 'sha256': 'b' * 64}
    top40_ref = {'path': 'top40', 'sha256': 'e' * 64}
    payloads = {'parent': {'ranking_manifest': hist_ref, 'outputs': {'rankings': top40_ref}}, 'historical': {}}
    digests = {'parent': 'a' * 64, 'historical': 'b' * 64, 'top40': 'e' * 64}
    stamp_version = {'top40': 1}
    def stamp(ref):
        path, digest = subject.base._ref(ref)
        return str(path), digest, 10, stamp_version.get(path.name, 1)
    monkeypatch.setattr(subject.base, '_hash', lambda path: digests[Path(path).name])
    monkeypatch.setattr(subject.base, '_stamp', stamp)
    monkeypatch.setattr(subject, '_checked_json', lambda ref: payloads[Path(ref['path']).name])
    raw.update(source_refs={'a2': parent_ref, 'historical': hist_ref},
               _source_stamps=(stamp(parent_ref), stamp(hist_ref)))
    monkeypatch.setattr(subject, 'load_history', lambda *a, **k: dict(raw))
    monkeypatch.setattr(subject, '_cached_history', lambda *a: dict(raw))
    monkeypatch.setattr(workspace, 'source_reference', lambda model: parent_ref)
    monkeypatch.setattr(workspace, 'is_updated', lambda model: True)
    calls = []
    monkeypatch.setattr(subject, '_append_parent_top40',
        lambda history, parent, **kwargs: calls.append(kwargs.get('defer_index')) or history)
    model = SimpleNamespace(error=None, decision_date='2026-09-24')
    subject._cached_applied_history.cache_clear()
    try:
        first = subject.load_applied_history(package=package, raw_model=model, as_of='2026-09-24')
        same = subject.load_applied_history(package=package, raw_model=model, as_of='2026-09-24')
        earlier = subject.load_applied_history(package=package, raw_model=model, as_of='2026-09-23')
        assert first['status'] == same['status'] == earlier['status'] == 'READY'
        assert calls == [True]
        assert earlier['end_date'] == '2026-09-23'
        assert '2026-09-24' not in earlier['_scores']
        assert all('2026-09-24' not in targets for targets in earlier['_targets'].values())
        assert earlier['raw_history']['_rank_index'].index.get_level_values(0).max() == '2026-09-23'
        changed = deepcopy(package)
        changed['strategies']['HGB_DIAG_5']['application']['rows'][0]['target_weight'] = .2
        changed['strategies']['HGB_DIAG_5']['application']['target_cash_weight'] = .8
        fresh = subject.load_applied_history(package=changed, raw_model=model, as_of='2026-09-24')
        assert fresh['_targets']['HGB_DIAG_5']['2026-09-24']['rows']['T01']['target_weight'] == .2
        assert len(calls) == 2
        stamp_version['top40'] = 2
        assert subject.load_applied_history(package=changed, raw_model=model, as_of='2026-09-24')['status'] == 'READY'
        assert len(calls) == 3
        digests['top40'] = 'f' * 64
        failed = subject.load_applied_history(package=changed, raw_model=model, as_of='2026-09-24')
        assert failed['status'] == 'UNAVAILABLE' and 'HASH_MISMATCH' in failed['error']
        assert len(calls) == 3
    finally:
        subject._cached_applied_history.cache_clear()


def test_cached_cutoff_excludes_future_only_members_and_daily_source_refs():
    raw, package = applied_fixture()
    ledger = raw['_ledger'].copy()
    ledger.loc[ledger.target_date.eq('2026-09-24'), 'snapshot_id'] = 'new_pool'
    members = pd.concat([raw['_members'], raw['_members'].assign(snapshot_id='new_pool'), pd.DataFrame([
        {'snapshot_id': 'new_pool', 'ticker': 'FUTURE', 'security_id': 'future',
         'issuer_name': 'Future member', 'mapping_verified': True}])], ignore_index=True)
    ranked = pd.concat([raw['_ranked'], pd.DataFrame([{'target_date': '2026-09-24',
        'ticker': 'FUTURE', 'security_id': 'future', 'rank': 42, 'score': -.1, 'universe_id': 'pool'}])], ignore_index=True)
    raw = subject.prepare_history(ranked, ledger, members)
    raw['source_refs'] = {'a2': {'path': 'parent', 'sha256': 'ab'*32},
                         'daily/2026-09-24': {'path': 'daily', 'sha256': 'cd'*32},
                         'daily_members/2026-09-24': {'path': 'members', 'sha256': 'ef'*32}}
    complete = subject.prepare_applied_history(raw, package, '2026-09-24')
    earlier = subject._cutoff_applied_history(complete, '2026-09-23')
    assert 'FUTURE' not in {row['ticker'] for row in earlier['catalog']}
    assert subject.query_applied_history(earlier, 'FUTURE')['status'] == 'NOT_FOUND'
    assert not any(key.startswith(('daily/', 'daily_members/')) for key in earlier['source_refs'])
    assert subject.query_applied_history(complete, 'FUTURE', '2026-09-24')['status'] == 'READY'
    assert complete['end_date'] == '2026-09-24'
