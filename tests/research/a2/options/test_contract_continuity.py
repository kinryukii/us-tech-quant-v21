"""Invented Dolt rows for source continuity; no ETF, network, or economic run."""
import copy
import hashlib
import json
from types import SimpleNamespace

import pandas as pd
import pytest
import requests

from scripts.research.a2.options import contract_continuity as continuity
from scripts.research.a2.options import public_history as public
from scripts.research.a2.options.contracts import Invalid


VERSION = 'bjodjis75b17vhj1e2ktrq8h7scu6t7q'


@pytest.fixture(autouse=True)
def prohibit_network_and_economic_replay(monkeypatch):
    from scripts.research.a2.options import expression
    def forbidden(*args, **kwargs):
        pytest.fail('Continuity unit tests cannot request sources or calculate economics')
    monkeypatch.setattr(requests.Session, 'request', forbidden)
    monkeypatch.setattr(expression, 'evaluate', forbidden)


def observation(**changes):
    row = dict(source='DOLT', source_file_id='invented-parent-cache-page',
        downloaded_at='2026-09-15T01:00:00Z', date='2025-03-03',
        source_date='2025-03-03', observation_date='2025-03-03',
        act_symbol='TEST', normalized_symbol='TEST', source_contract_id=None,
        expiration='2025-04-17', normalized_expiration='2025-04-17',
        strike='100', normalized_strike='100', call_put='Call', normalized_right='C',
        bid='1.00', ask='1.20', observation_bid=1., observation_ask=1.2,
        observation_bid_size=None, observation_ask_size=None, size_unit='UNKNOWN',
        multiplier=None, deliverable=None, adjustment_status=None,
        underlying_uid=None, historical_uid_status='UNKNOWN',
        quote_timestamp=None, historical_available_at=None, available_at=None,
        quality_status='OBSERVATION_FIELDS_PRESENT_NOT_QUALIFIED', quality_reasons='[]')
    return row | changes


def at_date(day, **changes):
    return observation(date=day, source_date=day, observation_date=day, **changes)


def opportunity(**changes):
    return dict(decision_id='2025-02-28:INVENTED', option_decision_date='2025-03-03',
                planned_exit_date='2025-03-10', entry_ticker='TEST', exit_ticker='TEST') | changes


def frame(*rows):
    return pd.DataFrame(list(rows), dtype=object)


def candidates(*rows, op=None):
    return continuity.entry_candidates(op or opportunity(), frame(*rows), VERSION)


def joined(entry_rows, exit_rows, *, op=None):
    selected = candidates(*entry_rows, op=op)
    return continuity.connect_exits(pd.DataFrame(selected), frame(*exit_rows), VERSION)


def test_source_key_ignores_observation_date_prices_and_cache_file():
    entry = observation()
    later = at_date('2025-03-10', bid='99', ask='100', observation_bid=99.,
                    observation_ask=100., source_file_id='another-invented-page')
    key = continuity.continuity_key(entry, VERSION)
    assert key is not None and key == continuity.continuity_key(later, VERSION)
    assert key != continuity.continuity_key(entry, 'a' * 32)


@pytest.mark.parametrize('changes', [
    {'normalized_strike': '100.00000000000000000001'},
    {'normalized_strike': '100.00000000000000000002'},
    {'normalized_expiration': '2025-04-18'},
    {'normalized_right': 'P'},
    {'act_symbol': 'test'},
    {'act_symbol': 'TEST1'},
    {'act_symbol': 'TEST.A'},
    {'series_id': 'SERIES_A'},
    {'adjustment_id': 'ADJUSTMENT_A'},
])
def test_composite_contract_differences_never_collapse(changes):
    assert continuity.continuity_key(observation(), VERSION) != continuity.continuity_key(observation(**changes), VERSION)


def test_strike_precision_is_not_reduced_to_float_or_a_rounded_bucket():
    one = observation(normalized_strike='100.00000000000000000001')
    two = observation(normalized_strike='100.00000000000000000002')
    assert continuity.continuity_key(one, VERSION) != continuity.continuity_key(two, VERSION)


@pytest.mark.parametrize('field', ['act_symbol', 'normalized_expiration', 'normalized_strike', 'normalized_right'])
@pytest.mark.parametrize('missing', [None, ''])
def test_incomplete_composite_key_is_null_not_a_shared_null_contract(field, missing):
    assert continuity.continuity_key(observation(**{field: missing}), VERSION) is None


def test_source_contract_id_precedes_composite_but_preserves_raw_root():
    identified = observation(source_contract_id='INVENTED-SOURCE-ID')
    key = continuity.continuity_key(identified, VERSION)
    assert key is not None
    incomplete_composite = identified | {'normalized_expiration': None, 'normalized_strike': None, 'normalized_right': None}
    assert continuity.continuity_key(incomplete_composite, VERSION) == key
    assert continuity.continuity_key(identified | {'act_symbol': 'TEST1'}, VERSION) != key
    assert continuity.continuity_key(identified | {'source_contract_id': 'ANOTHER-ID'}, VERSION) != key


def test_source_identity_is_not_inferred_from_normalized_uppercase_symbol():
    row = observation(act_symbol=None, normalized_symbol='TEST')
    assert continuity.continuity_key(row, VERSION) is None
    other = observation(source='OTHER_PUBLIC_DATASET')
    other_key = continuity.continuity_key(other, VERSION)
    assert other_key is None or other_key != continuity.continuity_key(observation(), VERSION)


def test_adjustment_status_is_economic_attribute_not_a_source_key_component():
    standard = observation(adjustment_status='STANDARD')
    adjusted = observation(adjustment_status='ADJUSTED')
    assert continuity.continuity_key(standard, VERSION) == continuity.continuity_key(adjusted, VERSION)


def test_entry_candidates_retain_all_calls_and_compute_only_calendar_dte_and_expiry():
    rows = [observation(normalized_expiration=expiry, expiration=expiry,
                        normalized_strike=str(strike), strike=str(strike))
            for expiry, strike in [('2025-04-01', 99), ('2025-04-02', 100),
                                  ('2025-04-16', 101), ('2025-04-18', 102),
                                  ('2025-05-02', 103), ('2025-05-03', 104)]]
    rows.append(observation(normalized_right='P', call_put='Put'))
    result = candidates(*rows)
    assert len(result) == 6
    by_expiry = {row['expiration']: row for row in result}
    assert {expiry: row['calendar_dte'] for expiry, row in by_expiry.items()} == {
        '2025-04-01': 29, '2025-04-02': 30, '2025-04-16': 44,
        '2025-04-18': 46, '2025-05-02': 60, '2025-05-03': 61}
    assert {expiry for expiry, row in by_expiry.items() if row['dte_30_60']} == {
        '2025-04-02', '2025-04-16', '2025-04-18', '2025-05-02'}
    assert {row['target_expiration'] for row in result} == {'2025-04-16'}
    assert sum(bool(row['in_target_expiration']) for row in result) == 1
    assert all(row['atm_contract_id'] is None for row in result)
    assert all(row['raw_source_date'] == '2025-03-03' for row in result)
    assert all(row['interpreted_market_date'] is None for row in result)


def test_target_expiry_contains_each_strike_without_synthesizing_an_atm_reference():
    rows = [observation(normalized_strike=str(strike), strike=str(strike)) for strike in (90, 100, 110)]
    result = candidates(*rows)
    assert len(result) == 3 and all(row['in_target_expiration'] for row in result)
    assert {row['strike'] for row in result} == {'90', '100', '110'}
    assert all(row['atm_contract_id'] is None for row in result)


def test_future_deletion_and_price_perturbation_do_not_change_entry_candidates():
    entry = observation()
    future = at_date('2025-03-10', normalized_expiration='2025-04-16',
                     normalized_strike='101', observation_bid=9999., observation_ask=10000.)
    base = continuity.entry_candidates(opportunity(), frame(entry, future), VERSION)
    changed = future | {'normalized_expiration': '2025-04-17', 'normalized_strike': '100',
                        'observation_bid': 0., 'observation_ask': .01}
    perturbed = continuity.entry_candidates(opportunity(), frame(changed, entry), VERSION)
    missing = continuity.entry_candidates(opportunity(), frame(entry), VERSION)
    assert base == perturbed == missing
    assert len(base) == 1
    # The same fixed candidate is retained with or without an exit observation.
    absent = continuity.connect_exits(pd.DataFrame(base), frame(future), VERSION)
    present = continuity.connect_exits(pd.DataFrame(base), frame(changed), VERSION)
    assert len(absent) == len(present) == 1
    assert absent.iloc[0].exit_match_count == 0 and present.iloc[0].exit_match_count == 1
    assert absent.iloc[0].source_continuity_key == present.iloc[0].source_continuity_key


def test_entry_input_order_does_not_change_candidate_order():
    rows = [observation(normalized_strike=str(strike), strike=str(strike)) for strike in (110, 90, 100)]
    assert candidates(*rows) == candidates(*reversed(rows))


def test_missing_exit_keeps_entry_candidate_and_does_not_substitute_another_contract():
    result = joined([observation()], [at_date('2025-03-10', normalized_strike='105')])
    assert len(result) == 1
    assert result.iloc[0].exit_match_count == 0
    assert not result.iloc[0].source_key_matched
    assert pd.isna(result.iloc[0].exit_bid)


@pytest.mark.parametrize('changes', [
    {'normalized_strike': '101'}, {'normalized_expiration': '2025-04-18'},
    {'normalized_right': 'P'}, {'act_symbol': 'TEST1'}, {'source': 'OTHER_PUBLIC_DATASET'},
    {'series_id': 'ANOTHER_SERIES'}, {'adjustment_id': 'ANOTHER_ADJUSTMENT'},
])
def test_exit_join_does_not_collapse_distinct_contracts_or_sources(changes):
    result = joined([observation()], [at_date('2025-03-10', **changes)])
    assert len(result) == 1 and result.iloc[0].exit_match_count == 0
    assert not result.iloc[0].source_key_matched


def test_null_contract_keys_do_not_match_each_other():
    incomplete = observation(normalized_strike=None)
    result = joined([incomplete], [at_date('2025-03-10', normalized_strike=None)])
    assert len(result) == 1 and pd.isna(result.iloc[0].source_continuity_key)
    assert result.iloc[0].exit_match_count == 0 and not result.iloc[0].source_key_matched


def test_duplicate_exit_matches_are_ambiguous_and_never_last_wins_or_averaged():
    exits = [at_date('2025-03-10', observation_bid=value) for value in (1., 100.)]
    left = joined([observation()], exits)
    right = joined([observation()], list(reversed(exits)))
    for result in (left, right):
        assert len(result) == 1 and result.iloc[0].exit_match_count == 2
        assert result.iloc[0].source_key_matched
        assert result.iloc[0].economic_identity_status == 'AMBIGUOUS'
        assert pd.isna(result.iloc[0].exit_bid)


def test_missing_sizes_and_economic_attributes_do_not_block_source_continuity():
    result = joined([observation()], [at_date('2025-03-10', observation_bid=0.)])
    assert len(result) == 1 and result.iloc[0].source_key_matched
    assert result.iloc[0].exit_match_count == 1
    assert result.iloc[0].exit_bid == 0.  # Observed zero is distinct from absence.
    assert result.iloc[0].economic_identity_status == 'UNKNOWN'


def economic_attributes(**changes):
    return dict(multiplier=100, deliverable='100_UNDERLYING_SHARES',
                adjustment_status='STANDARD', historical_uid_status='VERIFIED',
                underlying_uid='INVENTED-UID') | changes


@pytest.mark.parametrize('exit_changes,expected', [
    ({'multiplier': 10}, 'CONFLICT'),
    ({'deliverable': 'CASH_AND_SHARES'}, 'CONFLICT'),
    ({'underlying_uid': 'OTHER-INVENTED-UID'}, 'CONFLICT'),
    ({'adjustment_status': 'ADJUSTED'}, 'CHANGED_AFTER_ENTRY'),
])
def test_known_economic_conflict_preserves_source_match(exit_changes, expected):
    entry = observation(**economic_attributes())
    later = at_date('2025-03-10', **economic_attributes(**exit_changes))
    result = joined([entry], [later])
    assert result.iloc[0].source_key_matched and result.iloc[0].exit_match_count == 1
    assert result.iloc[0].economic_identity_status == expected


def test_adjusted_at_entry_does_not_erase_the_observed_contract():
    attrs = economic_attributes(adjustment_status='ADJUSTED')
    result = joined([observation(**attrs)], [at_date('2025-03-10', **attrs)])
    assert len(result) == 1 and result.iloc[0].source_key_matched
    assert result.iloc[0].economic_identity_status == 'ADJUSTED_AT_ENTRY'


def test_equal_complete_endpoint_attributes_do_not_prove_interval_economic_identity():
    attrs = economic_attributes()
    result = joined([observation(**attrs)], [at_date('2025-03-10', **attrs)])
    assert result.iloc[0].source_key_matched
    # Equal endpoint attributes and a stock UID leave option rights between
    # the two observations unproved; they do not certify economic continuity.
    assert result.iloc[0].economic_identity_status == 'UNKNOWN'
    missing = attrs | {'multiplier': None}
    result = joined([observation(**missing)], [at_date('2025-03-10', **missing)])
    assert result.iloc[0].source_key_matched
    assert result.iloc[0].economic_identity_status == 'UNKNOWN'


def test_wrong_and_sparse_exit_dates_are_not_moved_to_the_frozen_target():
    exits = [at_date(day, observation_bid=float(i + 1)) for i, day in enumerate(
        ['2025-03-04', '2025-03-05', '2025-03-06', '2025-03-08', '2025-03-11'])]
    result = joined([observation()], exits)
    assert len(result) == 1 and result.iloc[0].exit_match_count == 0
    assert pd.isna(result.iloc[0].exit_bid)
    assert result.iloc[0].raw_source_date == '2025-03-03'
    assert pd.isna(result.iloc[0].interpreted_market_date)
    assert candidates(at_date('2025-03-02')) == []  # Sunday is not moved to Monday.


@pytest.mark.parametrize('field', ['option_decision_date', 'planned_exit_date'])
def test_2026_plan_dates_are_rejected(field):
    with pytest.raises(Invalid):
        candidates(observation(), op=opportunity(**{field: '2026-01-02'}))


def test_2026_observations_are_rejected_not_silently_filtered():
    with pytest.raises(Invalid):
        candidates(observation(), at_date('2026-01-02'))
    selected = pd.DataFrame(candidates(observation()))
    with pytest.raises(Invalid):
        continuity.connect_exits(selected, frame(at_date('2026-01-02')), VERSION)


def test_2026_contract_expiry_itself_is_not_a_2026_market_observation():
    op = opportunity(option_decision_date='2025-12-01', planned_exit_date='2025-12-08')
    result = candidates(at_date('2025-12-01', expiration='2026-01-15',
                                normalized_expiration='2026-01-15'), op=op)
    assert len(result) == 1 and result[0]['calendar_dte'] == 45
    assert result[0]['dte_30_60'] and result[0]['target_expiration'] == '2026-01-15'
    assert result[0]['atm_contract_id'] is None


def test_connection_does_not_mutate_fixed_entry_rows_or_calculate_returns():
    selected = pd.DataFrame(candidates(observation()))
    exits = frame(at_date('2025-03-10', observation_bid=9999.))
    before_candidates, before_exits = selected.copy(deep=True), exits.copy(deep=True)
    result = continuity.connect_exits(selected, exits, VERSION)
    pd.testing.assert_frame_equal(selected, before_candidates)
    pd.testing.assert_frame_equal(exits, before_exits)
    assert not {'pnl', 'net_pnl', 'return', 'net_wealth', 'increment', 'bid_exit_minus_ask_entry'} & set(result.columns)


def incremental_session(tmp_path, rows):
    cache = (tmp_path / 'invented-incremental-cache').resolve()
    cache.mkdir()
    path = cache / 'invented-observations.parquet'
    frame(*rows).to_parquet(path, index=False, row_group_size=1)
    part = dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    return SimpleNamespace(parent={'normalization': {'parts': []}},
        parent_cache=(tmp_path / 'unused-parent-cache').resolve(), cache=cache,
        manifest={'incremental_parts': [part]})


def test_incremental_2026_footer_is_rejected_before_record_materialization(tmp_path, monkeypatch):
    session = incremental_session(tmp_path, [observation(), at_date('2026-01-02')])
    calls = []
    def forbidden_materialization(*args, **kwargs):
        calls.append((args, kwargs))
        pytest.fail('A 2026 footer must stop the read before market records materialize')
    monkeypatch.setattr(continuity.pd, 'read_parquet', forbidden_materialization)
    with pytest.raises(Invalid, match='CONTINUITY_DATE_OUTSIDE_PRE2026'):
        continuity.read_observations(session, {('2025-03-03', 'TEST')})
    assert calls == []


def test_incremental_entry_projection_pushes_date_and_raw_symbol_filters_into_read(tmp_path, monkeypatch):
    session = incremental_session(tmp_path, [observation(), at_date('2025-03-10'),
                                             observation(act_symbol='TEST1')])
    materialize = pd.read_parquet
    calls = []
    def projected_read(path, **kwargs):
        assert kwargs['filters'] == [[('source_date', '=', '2025-03-03'), ('act_symbol', '=', 'TEST')]]
        assert set(kwargs['columns']) <= set(continuity.OBS_COLUMNS)
        result = materialize(path, **kwargs)
        # The filtered reader itself, before a later pandas projection, must
        # have omitted the exit day and the other raw root.
        assert result.source_date.tolist() == ['2025-03-03']
        assert result.act_symbol.tolist() == ['TEST']
        calls.append(path)
        return result
    monkeypatch.setattr(continuity.pd, 'read_parquet', projected_read)
    result = continuity.read_observations(session, {('2025-03-03', 'TEST')})
    assert len(calls) == 1 and len(result) == 1
    assert result.iloc[0].source_date == result.iloc[0].observation_date == '2025-03-03'


def version_session():
    query = "SELECT date FROM option_chain AS OF '" + VERSION + "' WHERE date < '2026-01-01';"
    return SimpleNamespace(parent={'sources': {'DOLT': {'commit': VERSION}}},
        manifest={'sources': {'DOLT': {'commit': VERSION}},
                  'requests': [{'source': 'DOLT', 'params': {'q': query}}]})


def test_version_validation_accepts_only_pinned_dolt_request_history():
    session = version_session()
    before = copy.deepcopy(session.manifest)
    continuity.validate_version(session)
    assert session.manifest == before


@pytest.mark.parametrize('tamper', ['manifest_commit', 'second_source', 'second_missing_asof', 'second_other_asof'])
def test_version_validation_rejects_changed_commit_or_any_unpinned_request(tamper):
    session = version_session()
    if tamper == 'manifest_commit':
        session.manifest['sources']['DOLT']['commit'] = 'a' * 32
    else:
        record = copy.deepcopy(session.manifest['requests'][0])
        if tamper == 'second_source':
            record['source'] = 'ANOTHER_DATASET'
        elif tamper == 'second_missing_asof':
            record['params']['q'] = 'SELECT date FROM option_chain;'
        else:
            record['params']['q'] = record['params']['q'].replace(VERSION, 'a' * 32)
        session.manifest['requests'].append(record)
    with pytest.raises(Invalid, match='CONTINUITY_(SOURCE|QUERY)_VERSION_CHANGED'):
        continuity.validate_version(session)


def test_actual_cli_routes_offline_stage_and_paths_to_contract_continuity(tmp_path, monkeypatch, capsys):
    from scripts.research.a2.options import cli
    source_run, output = tmp_path / 'invented-source-run', tmp_path / 'invented-output'
    calls = []
    def run_stage(source, destination, *, offline=False, recover=False):
        calls.append((source, destination, offline, recover))
        return {'required_stage_success': True, 'stage': 'contract-continuity', 'evaluate_calls': 0}
    def wrong_route(*args, **kwargs):
        pytest.fail('The continuity CLI must not route into public acquisition or economic replay')
    monkeypatch.setattr(continuity, 'run_contract_continuity', run_stage)
    monkeypatch.setattr(public, 'run_public_history', wrong_route)
    monkeypatch.setattr(cli, 'evaluate', wrong_route)
    result = cli.main(['--mode', 'public-history', '--stage', 'contract-continuity',
                       '--source-run', str(source_run), '--output', str(output), '--offline'])
    assert result == 0 and calls == [(source_run, output, True, False)]
    assert json.loads(capsys.readouterr().out)['stage'] == 'contract-continuity'
    assert not source_run.exists() and not output.exists()


def test_offline_recovery_rejected_before_session_or_io(tmp_path, monkeypatch):
    def forbidden_session(*args, **kwargs):
        pytest.fail('Offline recovery must reject before constructing the session')
    monkeypatch.setattr(continuity, 'ContinuitySession', forbidden_session)
    with pytest.raises(Invalid, match='CONTINUITY_OFFLINE_RECOVERY_FORBIDDEN'):
        continuity.run_contract_continuity(tmp_path / 'source', tmp_path / 'output', offline=True, recover=True)


def budget_session(tmp_path, *, inherited_public=170, inherited_massive=12, direct_limit=80,
                   current=0, offline=False):
    session = object.__new__(public.PublicSession)
    session.cache = tmp_path / 'invented-budget-cache'
    session.cache.mkdir()
    session.output = tmp_path
    session.path = tmp_path / 'invented-manifest.json'
    session.offline = offline
    session.manifest = dict(requests=[{'request_id': 'invented-prior-' + str(i), 'source': 'DOLT',
        'status': 'COMPLETE'} for i in range(current)], source_status={},
        sources={'DOLT': {'commit': VERSION}}, inherited_public_requests=inherited_public,
        inherited_massive_requests=inherited_massive, direct_request_limit=direct_limit,
        acquisition_deadline_epoch=10**20, cache_limit_bytes=1024 * 1024)
    session.http = SimpleNamespace(request=lambda *a, **k: pytest.fail('Unexpected transport request'))
    session.save = lambda: None
    return session


@pytest.mark.parametrize('inherited_public,inherited_massive,direct_limit,current', [
    (399, 12, 80, 1),  # The inherited public scope already used the 400th request.
    (170, 12, 80, 80),  # This continuation's independent 80-request cap.
    (299, 900, 80, 1),  # The research-wide 1,200 cap is the tighter limit.
])
def test_get_enforces_each_inherited_budget_before_transport(tmp_path, inherited_public,
                                                           inherited_massive, direct_limit, current):
    session = budget_session(tmp_path, inherited_public=inherited_public,
        inherited_massive=inherited_massive, direct_limit=direct_limit, current=current)
    with pytest.raises(Invalid, match='PUBLIC_REQUEST_BUDGET'):
        session.get('DOLT', public.DOLT, params={'q': 'SHOW TABLES; -- invented new request'})
    assert len(session.manifest['requests']) == current


def test_get_consumes_last_inherited_public_request_once_then_stops(tmp_path, monkeypatch):
    session = budget_session(tmp_path, inherited_public=399)
    calls = []
    payload = b'{"query_execution_status":"Success","rows":[]}'
    class Response:
        status_code = 200
        headers = {'Content-Type': 'application/json', 'Content-Length': str(len(payload))}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def iter_content(self, chunk_size):
            yield payload
    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()
    session.http = SimpleNamespace(request=request)
    monkeypatch.setattr(public.time, 'sleep', lambda seconds: None)
    record, path = session.get('DOLT', public.DOLT, params={'q': 'SHOW TABLES; -- first'})
    assert record['status'] == 'COMPLETE' and path.read_bytes() == payload
    with pytest.raises(Invalid, match='PUBLIC_REQUEST_BUDGET'):
        session.get('DOLT', public.DOLT, params={'q': 'SHOW TABLES; -- second'})
    assert len(calls) == len(session.manifest['requests']) == 1


def test_complete_cache_reuse_does_not_consume_exhausted_budget(tmp_path):
    session = budget_session(tmp_path, inherited_public=399, offline=True)
    params = {'q': 'SHOW TABLES; -- invented cached request'}
    identity = dict(source='DOLT', method='GET', url=public.DOLT, params=params, headers={})
    request_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    path = session.cache / 'invented-complete.raw'
    path.write_bytes(b'{"query_execution_status":"Success","rows":[]}')
    record = dict(identity, request_id=request_id, status='COMPLETE', file=path.name,
                  sha256=hashlib.sha256(path.read_bytes()).hexdigest(), http_status=200)
    session.manifest['requests'].append(record)
    actual, cached = session.get('DOLT', public.DOLT, params=params)
    assert actual == record and cached == path
    assert session.manifest['requests'] == [record]


def two_precounted_keys():
    keys = [dict(request_key_id='invented-' + str(index), date=day, ticker='TEST')
            for index, day in enumerate(['2025-03-03', '2025-03-10'])]
    states = {key['request_key_id']: dict(ticker=key['ticker'], date=key['date'],
        status='COUNTED_NOT_DOWNLOADED', expected_rows=1, downloaded_rows=0, pages=[])
        for key in keys}
    return keys, states


def test_non_timeout_page_error_retains_reason_and_stops_next_key():
    keys, states = two_precounted_keys()
    session = SimpleNamespace(manifest=dict(dolt_keys=states, requests=[], source_status={},
        sources={'DOLT': {'commit': VERSION}}, stage='contract-continuity',
        acquisition_policy={'count_key_batch': 1, 'page_size': 100}), save=lambda: None)
    calls = []
    def fail_page(query):
        calls.append(query)
        session.manifest['requests'].append(dict(source='DOLT', params={'q': query},
            status='COMPLETE', http_status=403, request_id='invented-denied-page'))
        raise Invalid('DOLT_HTTP_403')
    session.sql = fail_page
    public.acquire_dolt(session, {'request_keys': keys})
    assert len(calls) == 1
    assert states[keys[0]['request_key_id']]['status'] == 'PAGE_ERROR'
    assert states[keys[0]['request_key_id']]['error'] == 'DOLT_HTTP_403'
    assert states[keys[1]['request_key_id']]['status'] == 'COUNTED_NOT_DOWNLOADED'
    assert session.manifest['source_status']['DOLT']['page_dependency_stop_reason'] == 'DOLT_HTTP_403'


def test_recovery_stops_next_fixed_key_on_page_dependency_reason(tmp_path, monkeypatch):
    keys, states = two_precounted_keys()
    for state in states.values():
        state['status'] = 'PAGE_ERROR'
    session = version_session()
    session.parent['dolt_keys'] = copy.deepcopy(states)
    session.manifest.update(dolt_keys=states, source_status={'DOLT': {}}, direct_request_limit=80)
    session.cache = tmp_path
    session.save = lambda: None
    untouched_second = copy.deepcopy(states[keys[1]['request_key_id']])
    calls = []
    def fail_dependency(current_session, plan):
        assert current_session is session
        calls.extend(plan['request_keys'])
        session.manifest['source_status']['DOLT'] = {'page_dependency_stop_reason': 'DOLT_PAGE_SCOPE'}
    monkeypatch.setattr(continuity, 'acquire_dolt', fail_dependency)
    continuity.recover_failed(session, {'request_keys': keys})
    assert calls == [keys[0]]
    assert [key['request_key_id'] for key in session.manifest['recovery_plan']] == [key['request_key_id'] for key in keys]
    assert states[keys[1]['request_key_id']] == untouched_second
    assert session.manifest['incremental_parts'] == []
