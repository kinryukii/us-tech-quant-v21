"""Synthetic transport/continuation wiring; no real credentials or market requests."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

import pandas as pd
import pytest

from scripts.research.a2.options import authenticated_reference as ar
from scripts.research.a2.options.contracts import Invalid, TEMPLATE

SECRET = 'fake-test-only-credential-never-persist-928372'


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bar(day, close=100):
    return {'t': int(pd.Timestamp(day, tz='America/New_York').timestamp()*1000), 'c': close}


def response(*bars, next_url=None):
    value = dict(ticker='SPY', adjusted=False, status='OK', resultsCount=len(bars),
                 queryCount=len(bars), results=list(bars))
    if next_url:
        value['next_url'] = next_url
    return value


def next_page(cursor='second', **changes):
    params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in ar.PARAMS.items()}
    return ar.URL + '?' + urlencode(params | {'cursor': cursor} | changes)


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    import requests
    monkeypatch.setattr(requests, 'get', lambda *a, **k: pytest.fail('real HTTP forbidden'))
    monkeypatch.setattr(requests.Session, 'request', lambda *a, **k: pytest.fail('real HTTP forbidden'))
    monkeypatch.delenv('MASSIVE_API_KEY', raising=False)


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    results, cache_root = tmp_path/'results', tmp_path/'cache'
    output = results/TEMPLATE/'spy2024_reference_completion'/'newrun'
    cache = cache_root/'options_expression_pilot_r1'/'spy2024_reference_completion'/'newrun'
    output.mkdir(parents=True)
    dates = [str(d.date()) for d in pd.date_range('2024-01-02', periods=175)] + ['2024-09-12']
    missing = [dict(decision_id='fake:'+d, reference_date=d, entry_date=d, exit_date=d) for d in dates]
    plan = [r | {'plan_weight': 1/246} for r in missing]
    overlap = ['2024-09-13', '2024-09-16', '2024-09-17']
    rule = {'numeric_equal_abs_usd': 1e-8}
    parent_path = results/TEMPLATE/'spy2024_observed_frontier'/'parent'/'run_manifest.json'
    parent = dict(task_id='OPTIONS_SPY2024_OBSERVED_FRONTIER_DIAGNOSTIC_R1',
        status='COMPLETE_CONDITIONAL_ARCHIVE_DIAGNOSTIC', plan=plan, fees={}, domain={},
        parent_run=str(tmp_path/'public_source'), parent_manifest_sha256='original-public-sha',
        entry_lock={'records': [r | {'selection_reason': 'REFERENCE_MISSING'} for r in missing]
                    + [dict(reference_date=d, reference_close=100, selection_reason='SELECTED') for d in overlap]},
        result_sha256='old-result-sha', summary={'old': True})
    dump(parent_path, parent)
    prior_path = output.parent/'previous'/'run_manifest.json'
    common = dict(plan=plan, missing_reference_keys=missing, overlap_keys=overlap, overlap_rule=rule, fees={}, domain={})
    dump(prior_path, common)
    doc = output/'daily_reference_semantics.md'
    doc.write_text('Synthetic fixed semantics evidence, no economic observations.', encoding='utf-8')
    manifest = dict(task_id=ar.TASK, status='FROZEN_AWAITING_SAFE_LOCAL_CREDENTIAL_INPUT', **common,
        completion_parent_run=str(prior_path.parent), completion_parent_manifest_sha256=digest(prior_path),
        parent_run=str(parent_path.parent), parent_manifest_sha256=digest(parent_path), cache=str(cache),
        request_plan=dict(method='GET', endpoint_if_needed=ar.URL.removeprefix('https://api.massive.com'),
                          **ar.PARAMS, maximum_http_requests_including_pages_recovery=3),
        daily_semantics_evidence={'status': ar.SEMANTICS, 'date_semantics': 'Unix milliseconds -> NY session',
            'session_basis': 'Daily aggregate anchor, execution and first publication unknown',
            'evidence': [{'path': str(doc), 'sha256': digest(doc)}]},
        candidate_registration={'new_candidates_for_this_task': 0, 'cumulative_candidates': 2},
        cumulative_candidates=2, new_scientific_candidates=0, new_training=0,
        browser_attempt={'ui_stopped': True}, http_budget={'document_accesses_completed': 3})
    dump(output/'run_manifest.json', manifest)
    monkeypatch.setattr(ar, 'resolve', lambda: SimpleNamespace(results_root=results, cache_root=cache_root))
    sleeps, cli_calls = [], []
    monkeypatch.setattr(ar.time, 'sleep', sleeps.append)

    def fake_cli(argv):
        cli_calls.append(argv)
        assert argv[:2] == ['--mode', 'spy2024-observed-frontier']
        dest = Path(argv[argv.index('--output')+1])
        if '--offline' in argv:
            source = Path(argv[argv.index('--source-run')+1])
            assert source == output
            result = json.loads((source/'run_manifest.json').read_text())
            result['offline_content_identical'] = True
        else:
            result = json.loads((dest/'run_manifest.json').read_text())
            assert result['parent_manifest_sha256'] == 'original-public-sha'
            assert result['observed_parent']['manifest_sha256'] == digest(parent_path)
            assert result['reference_additions']['allowed_reference_dates'] == dates
        result['status'] = 'COMPLETE_CONDITIONAL_ARCHIVE_DIAGNOSTIC'
        dest.mkdir(parents=True, exist_ok=True)
        (dest/'observed_frontier.csv').write_text('decision_id\nsynthetic\n', encoding='utf-8')
        result['result_sha256'] = digest(dest/'observed_frontier.csv')
        dump(dest/'run_manifest.json', result)
        return 0

    monkeypatch.setattr(ar.cli, 'main', fake_cli)
    return SimpleNamespace(output=output, cache=cache, manifest=manifest, parent=parent,
        ledger=cache.parent/'authenticated_daily_state.json', cli_calls=cli_calls,
        sleeps=sleeps, dates=dates)


def test_main_one_hidden_input_reaches_original_transport_and_both_clis(frozen, monkeypatch, capsys):
    hidden, wire = [], []
    monkeypatch.setattr(ar.cli, '_hidden_massive_key', lambda: hidden.append(True) or SECRET)

    def get(url, **kwargs):
        wire.append((url, kwargs))
        assert kwargs['api_key'] == SECRET
        assert kwargs['params'] == ar.PARAMS and 'Authorization' not in kwargs['headers']
        assert kwargs['allow_redirects'] is False
        return 200, response(bar('2024-01-02'), bar('2024-09-13'), bar('2024-09-16'), bar('2024-09-17'))

    monkeypatch.setattr(ar, '_history_get', get)
    assert ar.main(['--output', str(frozen.output), '--prompt-api-key']) == 0
    assert len(hidden) == len(wire) == 1
    assert len(frozen.cli_calls) == 2 and '--offline' in frozen.cli_calls[1]
    additions = json.loads((frozen.output/'reference_additions.json').read_text())
    assert additions == [dict(ticker='SPY', date='2024-01-02', close=100, adjustment='raw', source='MASSIVE_CUSTOM_BARS', currency='USD')]
    assert SECRET not in capsys.readouterr().out
    for path in frozen.output.parent.parent.parent.rglob('*'):
        if path.is_file():
            assert SECRET.encode() not in path.read_bytes()
    assert json.loads((frozen.output/'authenticated_fetch.json').read_text())['credential_entry'] == 'ORIGINAL_LOCAL_HIDDEN_INPUT'
    current = json.loads((frozen.output/'run_manifest.json').read_text())
    assert current['candidate_registration']['new_candidates_for_this_task'] == 0
    assert current['cumulative_candidates'] == 2 and current['result_root'] == str(frozen.output)
    assert current['http_budget']['public_budget_charged_total'] == 227
    assert current['http_budget']['research_budget_charged_total'] == 240
    assert len(current['reference_additions']['qualification']['response_evidence']) == 1
    report = (frozen.output/'认证续接结论.md').read_text(encoding='utf-8')
    assert report.startswith('1. 凭证') and '2. 本次日线 HTTP' in report and '3. 原176缺口恢复 1' in report
    assert '终点：A：' in report and SECRET not in report


def test_no_credential_no_automatic_prompt_no_http_no_economic_copy(frozen, monkeypatch):
    monkeypatch.setattr(ar.cli, '_hidden_massive_key', lambda: pytest.fail('not opted into prompt'))
    monkeypatch.setattr(ar, '_history_get', lambda *a, **k: pytest.fail('no credential'))
    result = ar.run_authenticated_reference(frozen.output)
    assert result['status'] == 'WAITING_LOCAL_HIDDEN_INPUT'
    assert result['daily_http_shared'] == result['economic_cli_runs'] == 0
    assert not frozen.cli_calls and not (frozen.output/'reference_additions.json').exists()
    assert 'C：等待一次本地隐藏输入，尚未发请求' in (frozen.output/'认证续接结论.md').read_text(encoding='utf-8')


def test_hidden_unavailable_never_falls_back_or_calls_http(frozen, monkeypatch):
    def reject():
        raise Invalid('LOCAL_INTERACTIVE_TERMINAL_REQUIRED')
    monkeypatch.setattr(ar.cli, '_hidden_massive_key', reject)
    monkeypatch.setattr(ar, '_history_get', lambda *a, **k: pytest.fail('hidden input unavailable'))
    assert ar.main(['--output', str(frozen.output), '--prompt-api-key']) == 3
    assert not frozen.cli_calls
    assert not (frozen.cache.parent/'authenticated_daily_state.lock').exists()


@pytest.mark.parametrize('status,reason', [(401, 'AUTHENTICATION_401'), (403, 'PERMISSION_403'),
    (429, 'RATE_LIMIT_429_HEADERS_UNAVAILABLE_NO_RETRY')])
def test_explicit_denial_and_429_stop_shared_path_across_restart(frozen, monkeypatch, status, reason):
    calls = []
    monkeypatch.setattr(ar, '_history_get', lambda *a, **k: (calls.append(True) or status, {'status': 'NOT_ENTITLED' if status == 403 else 'ERROR', 'message': 'denied'}))
    first = ar.run_authenticated_reference(frozen.output, api_key=SECRET)
    second = ar.run_authenticated_reference(frozen.output, api_key=SECRET)
    assert first['status'] == second['status'] == reason
    assert len(calls) == first['daily_http_shared'] == second['daily_http_shared'] == 1
    assert not frozen.cli_calls and not frozen.sleeps
    current = json.loads((frozen.output/'run_manifest.json').read_text())
    assert current['status'] == 'COMPLETED_NO_ADMISSIBLE_REFERENCE'
    assert current['http_budget']['new_daily_actual'] == 1 and len(current['requests']) == 1
    resolution = pd.read_csv(frozen.output/'reference_resolution.csv')
    assert len(resolution) == 176 and resolution.restored.eq(False).all()
    assert resolution.read_at_utc.isna().all()
    assert '终点：B：' in (frozen.output/'认证续接结论.md').read_text(encoding='utf-8')
    assert second['daily_http_this_invocation'] == 0 and not second['credential_entered_request_process']
    assert second['credential_ever_entered_shared_request_process'] is True


def test_plain_403_stops_without_fabricating_entitlement(frozen, monkeypatch):
    monkeypatch.setattr(ar, '_history_get', lambda *a, **k: (403, {}))
    result = ar.run_authenticated_reference(frozen.output, api_key=SECRET)
    assert result['status'] == 'HTTP_403_ENTITLEMENT_UNKNOWN'
    assert result['requests'][0]['http_facts']['entitlement'] == 'UNKNOWN'


def test_existing_env_with_prompt_flag_does_not_prompt_or_mislabel(frozen, monkeypatch):
    monkeypatch.setenv('MASSIVE_API_KEY', SECRET)
    monkeypatch.setattr(ar.cli, '_hidden_massive_key', lambda: pytest.fail('already have env credential'))
    monkeypatch.setattr(ar, '_history_get', lambda *a, **k: (200, response()))
    result = ar.run_authenticated_reference(frozen.output, prompt_api_key=True)
    assert result['credential_entry'] == 'MASSIVE_API_KEY_PROCESS_ENVIRONMENT'


def test_200_empty_is_neither_permission_qualification_nor_cash(frozen, monkeypatch):
    monkeypatch.setattr(ar, '_history_get', lambda *a, **k: (200, response()))
    result = ar.run_authenticated_reference(frozen.output, api_key=SECRET)
    assert result['recovered_reference_keys'] == result['economic_cli_runs'] == 0
    assert result['requests'][0]['scope']['qualification'] == 'EMPTY'


@pytest.mark.parametrize('change', [dict(ticker='QQQ'), dict(adjusted=True), dict(resultsCount=7),
    dict(status='ERROR'), dict(queryCount=-1)])
def test_bad_response_identity_counts_and_business_status_rejected(change):
    rows, scope = ar._page(response(bar('2024-01-02')) | change)
    assert rows == [] and scope['qualification'] == 'REJECTED'


@pytest.mark.parametrize('price', [0, -1, None, float('nan'), float('inf'), True, '100'])
def test_non_finite_non_positive_or_untyped_close_is_not_reference(price):
    rows, scope = ar._page(response(bar('2024-01-02', price)))
    assert not rows and scope['qualification'] == 'NO_QUALIFIED_ROWS'
    assert scope['rejected_dates'] == {'2024-01-02': 'CLOSE_NOT_FINITE_POSITIVE'}


def test_unix_ms_is_new_york_day_and_2026_scope_is_disclosed(frozen, monkeypatch):
    timestamp = int(pd.Timestamp('2024-01-02T05:00:00Z').timestamp()*1000)
    rows, scope = ar._page(response({'t': timestamp, 'c': 100}))
    assert rows[0]['date'] == '2024-01-02'
    monkeypatch.setattr(ar, '_history_get', lambda *a, **k: (200, response(bar('2024-01-02'), bar('2026-01-02', 999))))
    result = ar.run_authenticated_reference(frozen.output, api_key=SECRET)
    assert result['status'] == 'RETURNED_DATE_OUTSIDE_REQUEST_2024'
    assert '2026-01-02' in result['actual_contact_dates']
    assert result['recovered_reference_keys'] == 0
    assert not list(frozen.cache.glob('daily_page_*.json'))


def test_non_midnight_timestamp_is_not_daily_start_even_if_ny_day_is_legal():
    timestamp = int(pd.Timestamp('2024-01-03T01:00:00Z').timestamp()*1000)
    rows, scope = ar._page(response({'t': timestamp, 'c': 100}))
    assert not rows and scope['dates'] == ['2024-01-02']
    assert scope['rejected_dates']['2024-01-02'] == 'DAILY_INTERVAL_START_NOT_MIDNIGHT_NY'


def test_partial_bad_close_and_conflicting_duplicate_only_isolate_affected_keys(frozen, monkeypatch):
    monkeypatch.setattr(ar, '_history_get', lambda *a, **k: (200, response(bar('2024-01-02'),
        bar('2024-01-03', None), bar('2024-01-04', 101), bar('2024-01-04', 102))))
    result = ar.run_authenticated_reference(frozen.output, api_key=SECRET)
    assert result['recovered_reference_keys'] == 1 and len(frozen.cli_calls) == 2
    rows = pd.read_csv(frozen.output/'reference_resolution.csv').set_index('reference_date')
    assert rows.loc['2024-01-03', 'status'] == 'CLOSE_NOT_FINITE_POSITIVE'
    assert rows.loc['2024-01-04', 'status'] == 'CONFLICTING_DUPLICATE_DAY'
    assert bool(rows.loc['2024-01-02', 'restored'])


@pytest.mark.parametrize('url', [next_page().replace('api.massive.com', 'untrusted.invalid'),
    next_page().replace('/ticker/SPY/', '/ticker/QQQ/'), next_page(limit=10), next_page(adjusted='true')])
def test_bad_pagination_stops_but_keeps_qualified_first_page(frozen, monkeypatch, url):
    calls = []
    monkeypatch.setattr(ar, '_history_get', lambda *a, **k: (calls.append(True) or 200, response(bar('2024-01-02'), next_url=url)))
    result = ar.run_authenticated_reference(frozen.output, api_key=SECRET)
    assert len(calls) == 1 and result['status'] == 'PAGINATION_SCOPE_REJECTED'
    assert result['recovered_reference_keys'] == 1 and len(frozen.cli_calls) == 2
    overlap = json.loads((frozen.output/'reference_overlap.json').read_text())
    assert all(row['fetched_close'] is None for row in overlap)


def test_three_http_budget_includes_pages_and_still_continues_partial(frozen, monkeypatch):
    calls = []
    def get(url, **kwargs):
        calls.append(kwargs['params'])
        n = len(calls)
        return 200, response(bar('2024-01-0'+str(n+1)), next_url=next_page('page'+str(n+1)))
    monkeypatch.setattr(ar, '_history_get', get)
    result = ar.run_authenticated_reference(frozen.output, api_key=SECRET)
    assert result['status'] == 'SHARED_THREE_REQUEST_BUDGET_EXHAUSTED'
    assert len(calls) == result['daily_http_shared'] == result['recovered_reference_keys'] == 3
    assert len(frozen.sleeps) == 2 and all(12 <= x <= 12.5 for x in frozen.sleeps)
    again = ar.run_authenticated_reference(frozen.output, api_key=SECRET)
    assert len(calls) == 3 and again['economic_cli_runs'] == 0
    assert again['offline_cli_runs'] == 0 and again['offline_reused'] is True
    assert again['daily_http_this_invocation'] == 0 and not again['credential_entered_request_process']


def test_pending_unknown_never_retries_or_prompts(frozen, monkeypatch):
    dump(frozen.ledger, dict(identity=dict(url=ar.URL, params=ar.PARAMS,
        completion_parent_sha256=frozen.manifest['completion_parent_manifest_sha256']), next_params=ar.PARAMS,
        terminal_reason=None, requests=[dict(number=1, params=ar.PARAMS, status='PENDING', output=str(frozen.output))]))
    monkeypatch.setattr(ar.cli, '_hidden_massive_key', lambda: pytest.fail('unknown request must not prompt'))
    monkeypatch.setattr(ar, '_history_get', lambda *a, **k: pytest.fail('unknown request must not retry'))
    result = ar.run_authenticated_reference(frozen.output, prompt_api_key=True)
    assert result['status'] == 'UNKNOWN_PRIOR_REQUEST_NOT_RETRIED' and result['daily_http_shared'] == 1


def test_exception_url_never_persisted_and_no_retry(frozen, monkeypatch):
    def get(*a, **k):
        raise RuntimeError(ar.URL+'?apiKey='+SECRET)
    monkeypatch.setattr(ar, '_history_get', get)
    first = ar.run_authenticated_reference(frozen.output, api_key=SECRET)
    assert first['requests'][0]['exception_type'] == 'RuntimeError'
    assert first['requests'][0]['status'] == 'UNKNOWN_COMPLETION'
    assert SECRET not in frozen.ledger.read_text()
    assert ar.run_authenticated_reference(frozen.output, api_key=SECRET)['daily_http_shared'] == 1


def test_pagination_credential_removed_before_cache_and_cached_replay_is_offline(frozen, monkeypatch):
    calls = []
    def get(*a, **k):
        calls.append(True)
        return (200, response(bar('2024-01-02'), next_url=next_page()+'&apiKey='+SECRET)) if len(calls) == 1 else (200, response())
    monkeypatch.setattr(ar, '_history_get', get)
    ar.run_authenticated_reference(frozen.output, api_key=SECRET)
    assert len(calls) == 2
    for path in frozen.cache.glob('*.json'):
        assert SECRET not in path.read_text()
    monkeypatch.setattr(ar, '_history_get', lambda *a, **k: pytest.fail('completed cached response must be reused'))
    assert ar.run_authenticated_reference(frozen.output)['recovered_reference_keys'] == 1


def test_conflict_inside_later_page_invalidates_earlier_good_key(frozen, monkeypatch):
    pages = iter([response(bar('2024-01-02'), bar('2024-01-03'), next_url=next_page()),
                  response(bar('2024-01-02', 100), bar('2024-01-02', 101))])
    monkeypatch.setattr(ar, '_history_get', lambda *a, **k: (200, next(pages)))
    result = ar.run_authenticated_reference(frozen.output, api_key=SECRET)
    assert result['conflicting_dates'] == ['2024-01-02']
    additions = json.loads((frozen.output/'reference_additions.json').read_text())
    assert [r['date'] for r in additions] == ['2024-01-03']


def test_response_credential_echo_is_never_cached_or_reported(frozen, monkeypatch):
    monkeypatch.setattr(ar, '_history_get', lambda *a, **k: (200, response(bar('2024-01-02')) | {'message': SECRET}))
    result = ar.run_authenticated_reference(frozen.output, api_key=SECRET)
    assert result['status'] == 'TRANSPORT_OR_SECRET_SAFETY_FAILURE_NO_AUTOMATIC_RETRY'
    assert not frozen.cli_calls and not list(frozen.cache.glob('daily_page_*.json'))
    for base in (frozen.output, frozen.cache.parent):
        for path in base.rglob('*'):
            if path.is_file():
                assert SECRET.encode() not in path.read_bytes()


def test_shared_ledger_does_not_reset_for_another_output_directory(frozen, monkeypatch):
    pages = iter([response(bar('2024-01-02'), next_url=next_page('2')),
                  response(bar('2024-01-03'), next_url=next_page('3')),
                  response(bar('2024-01-04'), next_url=next_page('4'))])
    monkeypatch.setattr(ar, '_history_get', lambda *a, **k: (200, next(pages)))
    ar.run_authenticated_reference(frozen.output, api_key=SECRET)
    sibling = frozen.output.with_name('other_attempt')
    sibling.mkdir()
    another_cache = frozen.cache.with_name(sibling.name)
    monkeypatch.setattr(ar, '_history_get', lambda *a, **k: pytest.fail('same scope budget must not reset'))
    rows, receipt, _ = ar._fetch(frozen.manifest, sibling, frozen.cache.parent, another_cache, SECRET, False)
    assert receipt['daily_http_shared'] == 3 and len(rows) == 3


def test_size_budget_includes_ancillary_test_bytes_before_http(frozen, monkeypatch):
    manifest_path = frozen.output/'run_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['ancillary_artifact_bytes'] = ar.MAX_BYTES
    dump(manifest_path, manifest)
    monkeypatch.setattr(ar, '_history_get', lambda *a, **k: pytest.fail('no request after budget exhausted'))
    with pytest.raises(Invalid, match='ARTIFACT_SIZE_BUDGET'):
        ar.run_authenticated_reference(frozen.output, api_key=SECRET)


def test_incomplete_manifest_bytes_are_preserved_before_cli_retry(frozen, monkeypatch):
    monkeypatch.setattr(ar, '_history_get', lambda *a, **k: (200, response(bar('2024-01-02'))))
    original_cli = ar.cli.main
    def fail_cli(argv):
        manifest_path = frozen.output/'run_manifest.json'
        current = json.loads(manifest_path.read_text())
        current['status'] = 'ENTRY_LOCKED_BEFORE_OPTION_PRICES'
        current['failure_evidence'] = 'synthetic CLI failure before writing result CSV'
        dump(manifest_path, current)
        return 3
    monkeypatch.setattr(ar.cli, 'main', fail_cli)
    with pytest.raises(Invalid, match='ECONOMIC_CLI_FAILED'):
        ar.run_authenticated_reference(frozen.output, api_key=SECRET)
    failed = (frozen.output/'run_manifest.json').read_bytes()
    monkeypatch.setattr(ar.cli, 'main', original_cli)
    monkeypatch.setattr(ar, '_history_get', lambda *a, **k: pytest.fail('must reuse cache on engineering retry'))
    ar.run_authenticated_reference(frozen.output, api_key=SECRET)
    current = json.loads((frozen.output/'run_manifest.json').read_text())
    previous = current['previous_manifest']
    assert Path(previous['path']).read_bytes() == failed
    assert previous['sha256'] == hashlib.sha256(failed).hexdigest()
    assert previous['status'] == 'ENTRY_LOCKED_BEFORE_OPTION_PRICES'


def test_offline_reuse_checks_actual_result_bytes(frozen, monkeypatch):
    monkeypatch.setattr(ar, '_history_get', lambda *a, **k: (200, response(bar('2024-01-02'))))
    ar.run_authenticated_reference(frozen.output, api_key=SECRET)
    offline = frozen.output.with_name(frozen.output.name+'_offline')
    (offline/'observed_frontier.csv').write_text('tampered')
    with pytest.raises(Invalid, match='CACHED_RESULT_BYTES_CHANGED'):
        ar.run_authenticated_reference(frozen.output, api_key=SECRET)


def test_changed_cache_or_document_binding_is_rejected(frozen, monkeypatch):
    monkeypatch.setattr(ar, '_history_get', lambda *a, **k: (200, response()))
    ar.run_authenticated_reference(frozen.output, api_key=SECRET)
    page = next(frozen.cache.glob('daily_page_*.json'))
    page.write_text('{}')
    with pytest.raises(Invalid, match='CACHED_RESPONSE_CHANGED'):
        ar.run_authenticated_reference(frozen.output)
    Path(frozen.manifest['daily_semantics_evidence']['evidence'][0]['path']).write_text('changed')
    with pytest.raises(Invalid, match='SEMANTICS_EVIDENCE_CHANGED'):
        ar.run_authenticated_reference(frozen.output)


def test_main_help_never_prompts(monkeypatch):
    monkeypatch.setattr(ar.cli, '_hidden_massive_key', lambda: pytest.fail('help must not prompt'))
    with pytest.raises(SystemExit) as exc:
        ar.main(['--help'])
    assert exc.value.code == 0
