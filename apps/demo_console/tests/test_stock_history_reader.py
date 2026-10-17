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


def test_catalog_preserves_last_names_nan_multiple_securities_and_sorted_tickers():
    ranked, ledger, members = fixture()
    extra = pd.DataFrame([
        {'snapshot_id': 'b', 'ticker': 'ABC', 'security_id': 'id3', 'issuer_name': None, 'mapping_verified': True},
        {'snapshot_id': 'a', 'ticker': 'NAN', 'security_id': 'nanid', 'issuer_name': float('nan'), 'mapping_verified': True},
        {'snapshot_id': 'a', 'ticker': 'XYZ', 'security_id': 'x2', 'issuer_name': 'Old', 'mapping_verified': True},
        {'snapshot_id': 'b', 'ticker': 'XYZ', 'security_id': 'x1', 'issuer_name': 'Final', 'mapping_verified': True},
        {'snapshot_id': 'a', 'ticker': 'IGNORED', 'security_id': 'ignored', 'issuer_name': 'Unverified', 'mapping_verified': False},
    ])
    history = subject.prepare_history(ranked.iloc[::-1], ledger.iloc[::-1], pd.concat([members, extra], ignore_index=True))
    assert history['catalog'] == [
        {'ticker': 'ABC', 'issuer_name': 'nan', 'security_ids': ['id1', 'id3']},
        {'ticker': 'NAN', 'issuer_name': 'nan', 'security_ids': ['nanid']},
        {'ticker': 'NEVER', 'issuer_name': 'NEVER', 'security_ids': ['id2']},
        {'ticker': 'XYZ', 'issuer_name': 'Final', 'security_ids': ['x1', 'x2']},
    ]
    assert history['start_date'] == '2025-01-03' and history['end_date'] == '2025-01-08'


def test_empty_verified_catalog_retains_empty_contract():
    ranked, ledger, members = fixture()
    history = subject.prepare_history(ranked.iloc[:0], ledger.iloc[::-1], members.iloc[:0])
    assert history['status'] == 'READY' and history['catalog'] == []
    assert subject.query_history(history, 'ABC')['status'] == 'NOT_FOUND'


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


def test_bulk_exact_lookup_keeps_input_order_and_missing_raw_observations():
    raw, package = applied_fixture()
    raw['_ranked'] = raw['_ranked'].loc[~(raw['_ranked'].target_date.eq('2026-01-02') & raw['_ranked'].ticker.eq('T01'))].iloc[::-1]
    days = sorted({row['signal_date'] for row in package['shared_scores']['historical']})
    package['shared_scores']['historical'] = [row for day in days
        for row in reversed([row for row in package['shared_scores']['historical'] if row['signal_date'] == day])]
    package['shared_scores']['current']['rows'].reverse()
    history = subject.prepare_applied_history(raw, package, '2026-09-24')
    expected = {(row['ticker'], row['security_id']): row for row in package['shared_scores']['historical']
                if row['signal_date'] == '2026-01-02'}
    assert history['_scores']['2026-01-02'] == expected
    assert history['_scores']['2026-01-02'][('T01', 'id01')]['raw_rank'] == 1
    assert len(history['_scores']['2026-09-24']) == 40
    assert subject._rank_record(history['raw_history'], '2026-01-02', 'T01') is None


def test_empty_shared_scores_keep_raw_lookup_available():
    raw, package = applied_fixture()
    package['shared_scores']['historical'] = []
    package['shared_scores']['current'].update(status='UNAVAILABLE', signal_date=None, rows=[], reason='Synthetic unavailable')
    history = subject.prepare_applied_history(raw, package, '2026-09-24')
    assert history['_scores'] == {}
    assert len(subject.load_applied_rankings('2026-09-24', history=history)['strategies']['RAW_A2']['rows']) == 41


def test_bulk_lookup_preserves_earliest_record_error_precedence():
    raw, package = applied_fixture()
    raw['_ranked'].loc[raw['_ranked'].target_date.eq('2026-01-02') & raw['_ranked'].ticker.eq('T01'), 'score'] = 999
    package['shared_scores']['current']['rows'][0]['security_id'] = 'later_bad_identity'
    with pytest.raises(ValueError, match='RAW_BINDING_MISMATCH'):
        subject.prepare_applied_history(raw, package, '2026-09-24')


def test_applied_scores_cannot_inherit_a_different_raw_score():
    raw, package = applied_fixture()
    raw['_ranked'].loc[(raw['_ranked'].target_date == '2026-01-02') & (raw['_ranked'].ticker == 'T01'), 'score'] = 999
    with pytest.raises(ValueError, match='RAW_BINDING_MISMATCH'):
        subject.prepare_applied_history(raw, package, '2026-09-24')


@pytest.mark.parametrize("field",["raw_rank","raw_score"])
def test_first_raw_binding_failure_reports_identity_and_roles_without_values(field):
    raw,package=applied_fixture()
    raw["source_refs"]={"a2":{"path":"synthetic-parent.json","sha256":"a"*64},
        "historical":{"path":"synthetic-historical.json","sha256":"b"*64}}
    shared_refs={"frozen/test2026/predictions.parquet":{"path":"synthetic-prefix.parquet","sha256":"c"*64},
        "performance_extension/manifest":{"path":"synthetic-extension.json","sha256":"d"*64}}
    package["source_refs"].update(shared_refs)
    package["source_hashes"].update({name:ref["sha256"] for name,ref in shared_refs.items()})
    column={"raw_rank":"rank","raw_score":"score"}[field]
    raw["_ranked"].loc[(raw["_ranked"].target_date=="2026-01-02")&(raw["_ranked"].ticker=="T01"),column]=999
    with pytest.raises(ValueError,match="RAW_BINDING_MISMATCH") as raised:
        subject.prepare_applied_history(raw,package,"2026-09-24")
    detail=json.loads(str(raised.value).split(":",1)[1])
    assert detail["signal_date"]=="2026-01-02" and detail["ticker"]=="T01" and detail["security_id"]=="id01"
    assert detail["fields"]==[field]
    assert detail["raw_source_roles"]==raw["source_refs"]
    assert detail["shared_score_source_roles"]==shared_refs
    assert "999" not in str(raised.value) and "pred_hgb" not in str(raised.value)
    assert len(str(raised.value))<4200


def test_raw_binding_diagnostic_bounds_source_roles_without_scalar_leaks():
    detail=subject._raw_binding_diagnostic({"source_refs":{"a2":{"path":"x"*5000,"sha256":"a"*64}}},
        {},{"signal_date":"2026-01-05","ticker":"SYN","security_id":"synthetic-id","raw_score":123.456},["raw_score"])
    payload=json.loads(detail.split(":",1)[1])
    assert payload["source_role_size_limit"] is True and payload["raw_source_roles"]=={}
    assert "123.456" not in detail and len(detail)<4200


@pytest.fixture
def accepted_input_vintage(tmp_path,monkeypatch):
    """Synthetic publisher-selected archive, with later Raw coverage completion."""
    import hashlib
    from scripts.research.a2.portfolio import selected_hgb as owner
    raw,package=applied_fixture();day='2026-01-05'
    original=raw['_ranked'].loc[raw['_ranked'].target_date.eq(day)&raw['_ranked'].ticker.ne('T41')].copy()
    mask=raw['_ranked'].target_date.eq(day)
    raw['_ranked'].loc[mask&raw['_ranked'].ticker.ne('T41'),'rank']+=1
    raw['_ranked'].loc[mask&raw['_ranked'].ticker.eq('T41'),['rank','score']]=[1,1.1]
    package['package_path']=str(tmp_path/'latest.json')
    archive_path=tmp_path/'history'/(day+'.json');archive_path.parent.mkdir()
    input_path=tmp_path/'original_input.json'
    feature={'path':str(tmp_path/'features.parquet'),'sha256':'f'*64}
    report={'status':'READY','data_date':day,'generated_at':day+'T20:45:00+00:00','model_id':'A2_HGB','model_sha256':subject.base.MODEL_2026_SHA,
        'coverage':{'eligible_count':40},'selected_hgb_features':feature,
        'universe':{'universe_id':'pool','quarter':'2026Q1','universe_members_sha256':'c'*64},
        'ranked_rows':original.to_dict('records')}
    snapshot={'signal_date':day,'generated_at':day+'T20:50:00+00:00','policy_id':owner.LEGACY_POLICY,
        'shared_scores':{'rows':[{key:value for key,value in row.items() if key!='signal_date'}
            for row in package['shared_scores']['historical'] if row['signal_date']==day]},
        'source_refs':{'current/selected_hgb_features.parquet':feature},
        'report_binding':{'selected_hgb_features':feature}}
    selections=[]
    def write():
        input_path.write_text(json.dumps(report),encoding='utf-8')
        source={'path':str(input_path),'sha256':hashlib.sha256(input_path.read_bytes()).hexdigest()}
        snapshot['source_refs']['current/report.json']=source
        archive_path.write_text(json.dumps(snapshot),encoding='utf-8')
        reference={'path':str(archive_path),'sha256':hashlib.sha256(archive_path.read_bytes()).hexdigest()}
        package['source_refs']['history/'+day+'.json']=reference
        package['source_hashes']['history/'+day+'.json']=reference['sha256']
    write()
    raw['source_refs'].update({'daily/'+day:{'path':str(tmp_path/'canonical.json'),'sha256':'d'*64},
        'daily_members/'+day:{'path':str(tmp_path/'members.parquet'),'sha256':'c'*64}})
    # The publisher authority is stubbed explicitly; no real freeze/model is read.
    def accepted(owner_package,folder,requested,*,report_metadata_loader=None):
        assert report_metadata_loader is subject._repair_report_metadata
        assert owner_package is package and folder==archive_path.parent and requested==day
        selections.append(requested)
        return archive_path,package['source_hashes']['history/'+day+'.json'],None
    monkeypatch.setattr(owner,'_revision_selection',accepted)
    return SimpleNamespace(raw=raw,package=package,day=day,report=report,snapshot=snapshot,
        write=write,input_path=input_path,archive_path=archive_path,selections=selections)


def test_accepted_distinct_input_vintage_keeps_both_exact_rank_roles(accepted_input_vintage):
    e=accepted_input_vintage;before=deepcopy(e.package)
    history=subject.prepare_applied_history(e.raw,e.package,'2026-09-24')
    row=subject.query_applied_history(history,'T01',e.day,e.day)['daily'][0]
    assert row['strategies']['RAW_A2']['model_rank']==2
    assert row['strategies']['HGB_DIAG_5']['raw_rank']==1
    assert row['strategies']['HGB_DIAG_5']['model_rank']==40
    assert row['strategies']['HGB_DIAG_5']['raw_input_source_ref']==e.snapshot['source_refs']['current/report.json']
    assert history['_score_errors']=={} and e.selections==[e.day] and e.package==before


def test_same_input_vintage_conflict_remains_strict(accepted_input_vintage):
    e=accepted_input_vintage
    e.raw['source_refs']['daily/'+e.day]=e.snapshot['source_refs']['current/report.json']
    with pytest.raises(ValueError,match='RAW_BINDING_MISMATCH'):
        subject.prepare_applied_history(e.raw,e.package,'2026-09-24')


@pytest.mark.parametrize('fault',['missing_ref','source_date','source_model','pool','members','feature','raw_rank',
    'raw_score','raw_identity','coverage','archive_shared','archive_date','source_sha'])
def test_unverified_original_input_isolated_to_its_hgb_date(accepted_input_vintage,fault):
    e=accepted_input_vintage
    if fault=='missing_ref':
        e.package['source_refs'].pop('history/'+e.day+'.json');e.package['source_hashes'].pop('history/'+e.day+'.json')
    else:
        if fault=='source_date':e.report['data_date']='2026-09-25'
        elif fault=='source_model':e.report['model_sha256']='e'*64
        elif fault=='pool':e.report['universe']['universe_id']='different'
        elif fault=='members':e.report['universe']['universe_members_sha256']='e'*64
        elif fault=='feature':e.report['selected_hgb_features']={'path':'wrong','sha256':'e'*64}
        elif fault=='raw_rank':e.report['ranked_rows'][0]['rank']=999
        elif fault=='raw_score':e.report['ranked_rows'][0]['score']=999
        elif fault=='raw_identity':e.report['ranked_rows'][0]['security_id']='different'
        elif fault=='coverage':e.report['coverage']['eligible_count']=41
        elif fault=='archive_shared':e.snapshot['shared_scores']['rows'][0]['pred_hgb']=999
        elif fault=='archive_date':e.snapshot['signal_date']='2026-09-25'
        e.write()
        if fault=='source_sha':e.input_path.write_text('{}',encoding='utf-8')
    history=subject.prepare_applied_history(e.raw,e.package,'2026-09-24',isolate_shared_source=True)
    assert history['status']=='READY' and len(history['catalog'])==42
    assert set(history['_score_errors'])=={e.day} and e.day not in history['_scores']
    row=subject.query_applied_history(history,'T01',e.day,e.day)['daily'][0]
    assert row['strategies']['RAW_A2']['model_rank']==2 and row['strategies']['RAW_A2']['target_weight']==.05
    for sid in selected.STRATEGY_IDS:
        assert row['strategies'][sid]['score'] is None and row['strategies'][sid]['target_weight'] is None
        assert row['strategies'][sid]['target_status']=='UNAVAILABLE'
    earlier=subject._cutoff_applied_history(history,'2026-01-02')
    assert earlier['_score_errors']=={} and earlier['_score_source_refs']=={}
    assert subject.query_applied_history(earlier,'T01')['score_source_errors']=={}
    assert history['source_refs']['a2']==e.raw['source_refs']['a2']


def test_cached_input_vintage_rechecks_hash_and_preserves_independent_raw(accepted_input_vintage):
    e=accepted_input_vintage
    history=subject.prepare_applied_history(e.raw,e.package,'2026-09-24')
    # Only actual file references enter this synthetic cache integrity exercise.
    history['_score_source_refs'][e.day]['verification_refs']={
        'accepted_archive':e.package['source_refs']['history/'+e.day+'.json'],
        'raw_input':e.snapshot['source_refs']['current/report.json']}
    assert subject._recheck_input_vintages(history) is history
    e.input_path.write_text('{}',encoding='utf-8')
    refused=subject._recheck_input_vintages(history)
    assert refused['catalog']==history['catalog'] and e.day not in refused['_scores']
    assert e.day in refused['_targets']['RAW_A2'] and e.day not in refused['_targets']['HGB_DIAG_5']
    assert e.day in history['_scores']  # cached snapshot itself remains immutable.


def test_input_projection_skips_unrelated_numeric_values_and_preserves_absolute_offsets(tmp_path,monkeypatch):
    import hashlib
    from scripts.common import json_projection
    path=tmp_path/'large_input.json'
    path.write_text(json.dumps({'unused':'y'*70000,'ranked_rows':[
        {'ticker':'UNRELATED','security_id':'other','rank':'x'*100000,'score':'z'*100000},
        {'ticker':'SYN','security_id':'id','rank':8,'score':.125,'universe_id':'pool','unused':'q'*70000}]}),encoding='utf-8')
    reference={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    loads=json_projection.json.loads
    def bounded(value,*args,**kwargs):
        assert len(value)<100,'unrelated wide/numeric evidence was decoded'
        return loads(value,*args,**kwargs)
    monkeypatch.setattr(json_projection.json,'loads',bounded)
    rows,count=subject._project_input_rankings(reference,{('SYN','id')})
    assert rows=={('SYN','id'):{'ticker':'SYN','security_id':'id','rank':8,'score':.125,'universe_id':'pool'}} and count==2


def test_accepted_current_revision_replaces_only_its_same_day_stock_view():
    raw, package = applied_fixture()
    day = package['shared_scores']['current']['signal_date']
    stale = [{**row, 'signal_date': day} for row in deepcopy(package['shared_scores']['current']['rows'])]
    stale[0]['raw_rank'], stale[1]['raw_rank'] = stale[1]['raw_rank'], stale[0]['raw_rank']
    package['shared_scores']['historical'].extend(stale)
    original = deepcopy(package)
    history = subject.prepare_applied_history(raw, package, day)
    expected = {(row['ticker'], row['security_id']): {**row, 'signal_date': day}
                for row in selected.score_snapshot(day, package=package)['rows']}
    assert history['_scores'][day] == expected
    assert len(history['_scores'][day]) == 40
    assert package == original  # The replay's original inputs and records remain immutable.
    assert package['shared_scores']['historical'][-40:] == stale
    rankings = subject.load_applied_rankings(day, history=history)
    for sid in selected.STRATEGY_IDS:
        assert len(rankings['strategies'][sid]['rows']) == 40
        assert all(row['raw_rank'] == expected[(row['ticker'], row['security_id'])]['raw_rank']
                   for row in rankings['strategies'][sid]['rows'])


@pytest.mark.parametrize('field,error', [('raw_rank', 'RAW_BINDING_MISMATCH'),
    ('raw_score', 'RAW_BINDING_MISMATCH'), ('security_id', 'SECURITY_BINDING_MISMATCH')])
def test_current_revision_retains_exact_raw_and_security_binding(field, error):
    raw, package = applied_fixture()
    current = package['shared_scores']['current']
    day = current['signal_date']
    package['shared_scores']['historical'].extend({**row, 'signal_date': day} for row in deepcopy(current['rows']))
    if field == 'raw_rank':
        current['rows'][0][field], current['rows'][1][field] = current['rows'][1][field], current['rows'][0][field]
    elif field == 'raw_score':
        current['rows'][0][field] += .001
    else:
        current['rows'][0][field] = 'different_security'
    with pytest.raises(ValueError, match=error):
        subject.prepare_applied_history(raw, package, day)


@pytest.mark.parametrize('status', ['BLOCKED', 'UNAVAILABLE'])
def test_missing_current_never_replaces_existing_same_day_history(status):
    raw, package = applied_fixture()
    current = package['shared_scores']['current']
    day = current['signal_date']
    recorded = [{**row, 'signal_date': day} for row in deepcopy(current['rows'])]
    package['shared_scores']['historical'].extend(recorded)
    current.update(status=status, signal_date=None, rows=[], reason='Synthetic current unavailable')
    history = subject.prepare_applied_history(raw, package, day)
    assert history['_scores'][day] == {(row['ticker'], row['security_id']): row for row in recorded}
    assert selected.score_snapshot(day, package=package)['status'] == status


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


@pytest.fixture
def current_ranking_evidence(tmp_path):
    """One immutable accepted decision with an independently bound Raw parent."""
    import hashlib
    from apps.demo_console.adapters import workspace_reader as workspace
    raw, package = applied_fixture()
    day = package['shared_scores']['current']['signal_date']
    members = raw['_members'][['ticker', 'security_id']].drop_duplicates()
    universe_dir = tmp_path / 'universe'
    universe_dir.mkdir()
    member_path = universe_dir / 'mapped_members.parquet'
    members.to_parquet(member_path, index=False)
    report_path, parent_path = tmp_path / 'recommendation_source.json', tmp_path / 'manifest.json'
    report = {'status': 'READY', 'data_date': day, 'model_id': 'A2_HGB',
        'model_sha256': subject.base.MODEL_2026_SHA,
        'ranked_rows': raw['_ranked'].loc[raw['_ranked'].target_date.eq(day)].to_dict('records'),
        'coverage': {'eligible_count': 41, 'mapped_count': 42, 'excluded_count': 1},
        'universe': {'universe_id': 'pool', 'quarter': '2026Q2', 'universe_member_count': 42,
                    'report_path': str(universe_dir / 'universe_report.json'),
                    'universe_members_sha256': hashlib.sha256(member_path.read_bytes()).hexdigest()}}
    package['source_refs'] = {key: {'path': str(tmp_path / ('unused_' + str(i))), 'sha256': digest}
                             for i, (key, digest) in enumerate(package['source_hashes'].items())}
    model = SimpleNamespace(source_id=workspace.LATEST, error=None, decision_date=day,
        source_manifest_path=str(parent_path), source_manifest_sha256=None,
        ranking=tuple(SimpleNamespace(ticker=row['ticker'], rank=row['rank'], score=row['score'])
                      for row in report['ranked_rows'] if row['rank'] <= 40))
    parent = {'ranking_end_date': day, 'recommendation_reports': []}
    def sync():
        report_path.write_text(json.dumps(report), encoding='utf-8')
        ref = {'path': str(report_path), 'sha256': hashlib.sha256(report_path.read_bytes()).hexdigest()}
        package['source_refs']['current/report.json'] = ref
        package['source_hashes']['current/report.json'] = ref['sha256']
        parent['recommendation_reports'] = [ref]
        parent_path.write_text(json.dumps(parent), encoding='utf-8')
        model.source_manifest_sha256 = hashlib.sha256(parent_path.read_bytes()).hexdigest()
    sync()
    return SimpleNamespace(raw=raw, package=package, day=day, model=model, parent=parent,
        report=report, report_path=report_path, parent_path=parent_path,
        member_path=member_path, sync=sync)


@pytest.mark.parametrize('supplied_history', [False, True])
def test_current_rankings_use_exact_current_evidence_without_loading_conflicting_history(
        current_ranking_evidence, monkeypatch, supplied_history):
    e = current_ranking_evidence
    old = e.package['shared_scores']['historical']
    old[0]['raw_rank'], old[1]['raw_rank'] = old[1]['raw_rank'], old[0]['raw_rank']
    with pytest.raises(ValueError, match='RAW_BINDING_MISMATCH'):
        subject.prepare_applied_history(e.raw, e.package, e.day)
    before = deepcopy(e.package)
    def forbidden(*args, **kwargs):
        raise AssertionError('current ranking must not load a full historical index')
    monkeypatch.setattr(subject, 'load_applied_history', forbidden)
    monkeypatch.setattr(subject, '_cached_history', forbidden)
    history = {'status': 'UNAVAILABLE', 'error': 'APPLIED_SHARED_SCORE_RAW_BINDING_MISMATCH'} if supplied_history else None
    result = subject.load_applied_rankings(e.day, package=e.package, raw_model=e.model, history=history)
    assert result['status'] == 'READY'
    assert result['coverage']['eligible_count'] == 41
    assert len(result['strategies']['RAW_A2']['rows']) == 41
    for sid in selected.STRATEGY_IDS:
        assert len(result['strategies'][sid]['rows']) == 40
        assert result['strategies'][sid]['actual_signal_date'] == e.day
    assert e.package == before


@pytest.mark.parametrize('fault,error', [
    ('report_hash', 'MANIFEST_HASH_MISMATCH'), ('parent_hash', 'MANIFEST_HASH_MISMATCH'),
    ('member_hash', 'OUTPUT_HASH_MISMATCH'), ('missing_ref', 'REPORT_PARENT_BINDING_MISMATCH'),
    ('parent_ref', 'REPORT_PARENT_BINDING_MISMATCH'), ('parent_day', 'REPORT_PARENT_BINDING_MISMATCH'),
    ('model_day', 'RAW_REFERENCE_UNAVAILABLE'), ('report_day', 'REPORT_IDENTITY_MISMATCH'),
    ('model_sha', 'REPORT_IDENTITY_MISMATCH'), ('report_status', 'REPORT_IDENTITY_MISMATCH'),
    ('report_sid', 'RANK_OUTSIDE_VERIFIED_POOL'), ('shared_sid', 'TOP40_BINDING_MISMATCH'),
    ('shared_rank', 'RAW_BINDING_MISMATCH'), ('shared_score', 'RAW_BINDING_MISMATCH'),
    ('parent_score', 'RAW_RANKING_BINDING_MISMATCH'), ('universe', 'POOL_BINDING_MISMATCH'),
    ('member_count', 'MEMBER_COUNT_MISMATCH'), ('score_count', 'SCORE_COUNT_MISMATCH')])
def test_current_rankings_reject_changed_or_unbound_evidence(current_ranking_evidence, monkeypatch, fault, error):
    e = current_ranking_evidence
    if fault == 'report_day':
        e.report['data_date'] = '2026-09-23'
    elif fault == 'model_sha':
        e.report['model_sha256'] = '0' * 64
    elif fault == 'report_status':
        e.report['status'] = 'BLOCKED'
    elif fault == 'report_sid':
        e.report['ranked_rows'][0]['security_id'] = 'unbound'
    elif fault == 'universe':
        e.report['ranked_rows'][0]['universe_id'] = 'other'
    elif fault == 'member_count':
        e.report['coverage']['mapped_count'] += 1
    elif fault == 'score_count':
        e.report['coverage']['eligible_count'] += 1
    e.sync()
    if fault in ('report_hash', 'parent_hash', 'member_hash'):
        path = {'report_hash': e.report_path, 'parent_hash': e.parent_path, 'member_hash': e.member_path}[fault]
        path.write_bytes(path.read_bytes() + b' ')
    elif fault == 'missing_ref':
        e.package['source_refs'].pop('current/report.json')
        e.package['source_hashes'].pop('current/report.json')
    elif fault in ('parent_ref', 'parent_day'):
        if fault == 'parent_ref':
            e.parent['recommendation_reports'] = []
        else:
            e.parent['ranking_end_date'] = '2026-09-23'
        e.parent_path.write_text(json.dumps(e.parent), encoding='utf-8')
        import hashlib
        e.model.source_manifest_sha256 = hashlib.sha256(e.parent_path.read_bytes()).hexdigest()
    elif fault == 'model_day':
        e.model.decision_date = '2026-09-23'
    elif fault == 'shared_sid':
        e.package['shared_scores']['current']['rows'][0]['security_id'] = 'unbound'
    elif fault == 'shared_rank':
        rows = e.package['shared_scores']['current']['rows']
        rows[0]['raw_rank'], rows[1]['raw_rank'] = rows[1]['raw_rank'], rows[0]['raw_rank']
    elif fault == 'shared_score':
        e.package['shared_scores']['current']['rows'][0]['raw_score'] += .001
    elif fault == 'parent_score':
        e.model.ranking[0].score += .001
    monkeypatch.setattr(subject, 'load_applied_history', lambda **kwargs: pytest.fail('must not fall back after invalid current evidence'))
    result = subject.load_applied_rankings(e.day, package=e.package, raw_model=e.model,
        history={'status': 'READY', 'should_not_be_used': True})
    assert result['status'] == 'UNAVAILABLE'
    assert error in result['error']
    assert all(leaf['rows'] == [] for leaf in result['strategies'].values())


@pytest.mark.parametrize('day', ['2026-09-23', '2026-09-25'])
def test_current_rankings_never_borrow_current_for_old_or_future_dates(current_ranking_evidence, monkeypatch, day):
    e = current_ranking_evidence
    seen = []
    def history(**kwargs):
        seen.append(kwargs['as_of'])
        return {'status': 'UNAVAILABLE', 'error': 'ORIGINAL_HISTORICAL_BINDING_FAILURE'}
    monkeypatch.setattr(subject, 'load_applied_history', history)
    monkeypatch.setattr(subject, '_checked_json', lambda ref: pytest.fail('different date must not read current evidence'))
    result = subject.load_applied_rankings(day, package=e.package, raw_model=e.model)
    assert seen == [day]
    assert result['status'] == 'UNAVAILABLE' and result['error'] == 'ORIGINAL_HISTORICAL_BINDING_FAILURE'
    assert all(leaf['rows'] == [] for leaf in result['strategies'].values())


def test_current_rankings_keep_blocked_targets_unknown(current_ranking_evidence):
    e = current_ranking_evidence
    for sid in selected.STRATEGY_IDS:
        e.package['strategies'][sid]['application'].update(status='BLOCKED', signal_date=None,
            requested_signal_date=e.day, rows=[], target_cash_weight=None, reason='missing risk inputs')
    result = subject.load_applied_rankings(e.day, package=e.package, raw_model=e.model,
        history={'status': 'UNAVAILABLE', 'error': 'unrelated historical conflict'})
    assert result['status'] == 'READY'
    for sid in selected.STRATEGY_IDS:
        leaf = result['strategies'][sid]
        assert leaf['target_status'] == 'BLOCKED'
        assert all(row['target_weight'] is None and row['selected'] is None for row in leaf['rows'])


def test_current_rankings_recheck_hash_after_a_prior_success(current_ranking_evidence):
    e = current_ranking_evidence
    first = subject.load_applied_rankings(e.day, package=e.package, raw_model=e.model)
    assert first['status'] == 'READY'
    e.report_path.write_bytes(e.report_path.read_bytes() + b' ')
    second = subject.load_applied_rankings(e.day, package=e.package, raw_model=e.model)
    assert second['status'] == 'UNAVAILABLE' and 'HASH_MISMATCH' in second['error']


def test_current_rankings_detect_source_changes_during_preparation(current_ranking_evidence, monkeypatch):
    e = current_ranking_evidence
    original = subject.prepare_applied_history
    def prepare(*args, **kwargs):
        result = original(*args, **kwargs)
        e.report_path.write_bytes(e.report_path.read_bytes() + b' ')
        return result
    monkeypatch.setattr(subject, 'prepare_applied_history', prepare)
    result = subject.load_applied_rankings(e.day, package=e.package, raw_model=e.model)
    assert result['status'] == 'UNAVAILABLE' and 'SOURCE_CHANGED_DURING_READ' in result['error']


def test_isolated_hgb_source_keeps_independent_active_stock_records(accepted_input_vintage,monkeypatch):
    from apps.demo_console.adapters import workspace_reader as workspace, new_strategy_stock_history_reader as native
    from apps.moomoo_trading_component.moomoo_component.strategy import ACTIVE_PAPER_STRATEGY_IDS
    e=accepted_input_vintage
    e.package['source_refs'].pop('history/'+e.day+'.json');e.package['source_hashes'].pop('history/'+e.day+'.json')
    history=subject.prepare_applied_history(e.raw,e.package,'2026-09-24',isolate_shared_source=True)
    history.update(_active_account_state={},_native_stock_sources={})
    monkeypatch.setattr(workspace,'query_applied_stock_history',subject.query_applied_history)
    monkeypatch.setattr(native,'query',lambda *args,**kwargs:{'note':'Synthetic recorded inputs','strategies':{
        sid:{'daily':{e.day:{'research_weight':.05,'native_action':'BUY'}},'source_refs':{},'error':None}
        for sid in ACTIVE_PAPER_STRATEGY_IDS[2:]}})
    result=workspace.query_active_stock_history(history,'T01',e.day,e.day)
    assert result['status']=='READY' and set(result['daily'][0]['strategies'])==set(ACTIVE_PAPER_STRATEGY_IDS)
    assert result['daily'][0]['strategies']['RAW_A2']['model_rank']==2
    assert result['daily'][0]['strategies']['HGB_DIAG_5']['score'] is None
    assert all(result['daily'][0]['strategies'][sid]['research_weight']==.05 for sid in ACTIVE_PAPER_STRATEGY_IDS[2:])
    assert result['source_refs']['a2']==e.raw['source_refs']['a2'] and e.day in result['score_source_errors']


@pytest.mark.parametrize('fault',['source_missing','source_naive','source_after_capture','capture_after_package','package_future'])
def test_input_vintage_knowledge_clock_is_independent_of_observation_day(accepted_input_vintage,fault):
    from datetime import datetime,timezone,timedelta
    e=accepted_input_vintage
    if fault=='source_missing':e.report.pop('generated_at')
    elif fault=='source_naive':e.report['generated_at']=e.day+'T20:45:00'
    elif fault=='source_after_capture':e.report['generated_at']=e.day+'T21:00:00+00:00'
    elif fault=='capture_after_package':e.snapshot['generated_at']='2026-09-26T20:00:00+00:00'
    elif fault=='package_future':e.package['generated_at']=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    e.write()
    result=subject.prepare_applied_history(e.raw,e.package,'2026-09-24',isolate_shared_source=True)
    assert result['status']=='READY' and e.day in result['_score_errors'] and e.day not in result['_scores']


@pytest.fixture
def input_repair_revision(accepted_input_vintage,monkeypatch):
    """Exercise the real selection/repair branch; mock only unchanged snapshot validation."""
    import hashlib
    from scripts.research.a2.portfolio import selected_hgb as owner
    e=accepted_input_vintage;folder=e.archive_path.parent
    # The isolated test has no training artifact reads. Reader model/pool/input gates stay real.
    # Restore the actual function saved from module code, rather than the base fixture stub.
    import importlib.util
    spec=importlib.util.spec_from_file_location('synthetic_repair_acceptance_owner',Path(owner.__file__))
    authority=importlib.util.module_from_spec(spec);spec.loader.exec_module(authority)
    feature_path=Path(e.report['selected_hgb_features']['path']);feature_path.write_bytes(b'synthetic frozen features')
    e.report['selected_hgb_features']['sha256']=hashlib.sha256(feature_path.read_bytes()).hexdigest()
    old_source_path=folder/'old_source.json'
    old_source=deepcopy(e.report);old_source['generated_at']=e.day+'T20:35:00+00:00'
    old_source_path.write_text(json.dumps(old_source),encoding='utf-8')
    old_source_ref={'path':str(old_source_path),'sha256':hashlib.sha256(old_source_path.read_bytes()).hexdigest()}
    old_snapshot=deepcopy(e.snapshot);old_snapshot['generated_at']=e.day+'T20:40:00+00:00'
    old_snapshot['source_refs']['current/report.json']=old_source_ref
    old_snapshot['snapshot_sha256']=authority._snapshot_hash(old_snapshot)
    old_path=folder/(e.day+'.json');old_path.write_text(json.dumps(old_snapshot),encoding='utf-8')
    old_ref={'path':str(old_path),'sha256':hashlib.sha256(old_path.read_bytes()).hexdigest()}
    audit_path=folder/'input_repair.json'
    audit={'schema':'A2_OFFLINE_INPUT_REPAIR_V1','network_requests_this_run':0,'status':'INPUTS_VERIFIED',
        'target_date':e.day,'run_id':'synthetic-repair','model_fit_count':0,'parameter_search_count':0,
        'old_date_keys_retained':True,'old_rows_unchanged':True,'unrelated_current_keys_unchanged':True,
        'reason':'Synthetic late input repair','parent_inputs':[old_source_ref],'created_at':e.day+'T20:43:00+00:00'}
    audit_path.write_text(json.dumps(audit),encoding='utf-8')
    audit_ref={'path':str(audit_path),'sha256':hashlib.sha256(audit_path.read_bytes()).hexdigest()}
    e.report.update(run_id=audit['run_id'],repair_lineage=audit_ref)
    e.input_path.write_text(json.dumps(e.report),encoding='utf-8')
    new_source_ref={'path':str(e.input_path),'sha256':hashlib.sha256(e.input_path.read_bytes()).hexdigest()}
    e.snapshot['source_refs']['current/report.json']=new_source_ref
    e.snapshot['snapshot_sha256']=authority._snapshot_hash(e.snapshot)
    revision_path=folder/'revisions'/e.day/(e.snapshot['snapshot_sha256']+'.json');revision_path.parent.mkdir(parents=True)
    revision_path.write_text(json.dumps(e.snapshot),encoding='utf-8')
    reference={'path':str(revision_path),'sha256':hashlib.sha256(revision_path.read_bytes()).hexdigest()}
    receipt={'schema_version':1,'kind':'INPUT_REPAIR','signal_date':e.day,'supersedes':old_ref,
        'replacement':reference,'repair_lineage':audit_ref}
    receipt_path=revision_path.with_suffix('.receipt.json');receipt_path.write_text(json.dumps(receipt),encoding='utf-8')
    receipt_ref={'path':str(receipt_path),'sha256':hashlib.sha256(receipt_path.read_bytes()).hexdigest()}
    for name,ref in [('history/'+e.day+'.json',reference),('history_revision/'+e.day+'.json',receipt_ref)]:
        e.package['source_refs'][name]=ref;e.package['source_hashes'][name]=ref['sha256']
    monkeypatch.setattr(authority,'_validate_snapshot',lambda value:value)
    parsed=[];original_json=authority._json
    def no_full_raw_report(path):
        assert Path(path).resolve()!=e.input_path.resolve(),'acceptance chain decoded the full Raw report'
        parsed.append(Path(path).resolve())
        return original_json(path)
    monkeypatch.setattr(authority,'_json',no_full_raw_report)
    monkeypatch.setattr(owner,'_revision_selection',authority._revision_selection)
    e.authority=authority;e.parsed=parsed;e.audit_path=audit_path;e.old_path=old_path
    e.old_source_path=old_source_path;e.receipt_path=receipt_path;e.audit=audit
    return e


def test_input_repair_selection_uses_bounded_metadata_hook_and_full_hash_closure(input_repair_revision):
    e=input_repair_revision
    history=subject.prepare_applied_history(e.raw,e.package,'2026-09-24')
    refs=history['_score_source_refs'][e.day]['verification_refs']
    assert e.input_path.resolve() not in e.parsed
    assert e.audit_path.resolve() in e.parsed and e.old_path.resolve() in e.parsed
    assert refs['repair_lineage']['path']==str(e.audit_path)
    assert refs['superseded_archive']['path']==str(e.old_path)
    assert refs['parent/current/report.json']['path']==str(e.old_source_path)
    assert subject._recheck_input_vintages(history) is history
    assert history['_score_source_refs'][e.day]['knowledge_as_of']==e.package['generated_at']


@pytest.mark.parametrize('target',['audit_path','old_path','old_source_path','receipt_path'])
def test_cached_repair_closure_tamper_only_refuses_its_hgb_date(input_repair_revision,target):
    e=input_repair_revision
    history=subject.prepare_applied_history(e.raw,e.package,'2026-09-24')
    getattr(e,target).write_text('{}',encoding='utf-8')
    partial=subject._recheck_input_vintages(history)
    assert partial['catalog']==history['catalog'] and e.day in partial['_score_errors']
    assert e.day in partial['_targets']['RAW_A2'] and e.day not in partial['_targets']['HGB_DIAG_5']
    assert subject._cutoff_applied_history(partial,'2026-01-02')['_score_errors']=={}


def test_input_repair_default_report_loader_retains_original_behavior(input_repair_revision,monkeypatch):
    e=input_repair_revision;owner=e.authority;calls=[]
    original=owner._json
    def default_report(path):
        calls.append(Path(path).resolve())
        if Path(path).resolve()==e.input_path.resolve():return e.report
        return original(path)
    monkeypatch.setattr(owner,'_json',default_report)
    folder=e.old_path.parent
    path,digest,receipt=owner._revision_selection(e.package,folder,e.day)
    assert e.input_path.resolve() in calls and path.is_file() and digest and receipt


def test_late_accepted_archive_uses_package_knowledge_not_observation_day(accepted_input_vintage):
    e=accepted_input_vintage
    e.snapshot['generated_at']='2026-01-06T20:50:00+00:00'
    e.write()
    history=subject.prepare_applied_history(e.raw,e.package,e.day)
    assert history['as_of']==e.day and history['_score_errors']=={}
    assert history['_score_source_refs'][e.day]['knowledge_as_of']==e.package['generated_at']
    assert subject.query_applied_history(history,'T01',e.day,e.day)['daily'][0]['strategies']['HGB_DIAG_5']['raw_rank']==1
