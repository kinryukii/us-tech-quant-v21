import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

SOURCE = Path(__file__).parents[1] / 'scripts/storage/refresh_minute_data.py'
SPEC = importlib.util.spec_from_file_location('pagination_policy_shadow', SOURCE)
minute = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(minute)
REPO = Path('D:/us-tech-quant')


class Limiter:
    def __init__(self):
        self.audit_rows = []
    def acquire(self, item):
        self.audit_rows.append(item)


class Context:
    def __init__(self):
        self.calls = []
    def request_history_kline(self, **kwargs):
        self.calls.append(kwargs.copy())
        return (0, pd.DataFrame({'code': ['US.NVDA']}), None)


@pytest.mark.parametrize('policy,expected', [('all-requests', 4), ('first-page', 2)])
def test_all_calls_recorded_first_pages_limited_and_request_kwargs_unchanged(policy, expected):
    context, limiter = Context(), Limiter()
    proxy = minute.LimitedQuoteHistory(context, limiter, {'US.NVDA'}, policy)
    requests = [dict(code='US.NVDA'), dict(code='US.NVDA', page_req_key=b'one'),
                dict(code='US.NVDA', page_req_key=b'two'), dict(code='US.NVDA', page_req_key=None)]
    for request in requests:
        proxy.request_history_kline(**request)
    assert context.calls == requests
    assert len(limiter.audit_rows) == expected
    assert len(proxy.audit_rows) == 4
    assert [row['first_page'] for row in proxy.audit_rows] == [True, False, False, True]
    assert all(row['outcome'] == 'RETURNED' for row in proxy.audit_rows)
    assert all('page_req_key' not in row for row in proxy.audit_rows)


@pytest.mark.parametrize('policy', ['all-requests', 'first-page'])
def test_unknown_code_does_not_reach_context_or_limiter(policy):
    context, limiter = Context(), Limiter()
    proxy = minute.LimitedQuoteHistory(context, limiter, {'US.NVDA'}, policy)
    with pytest.raises(ValueError, match='NEW_SECURITY_TOUCH_FORBIDDEN'):
        proxy.request_history_kline(code='US.AMD', page_req_key=b'anything')
    assert not context.calls and not limiter.audit_rows and not proxy.audit_rows


def test_exception_attempt_is_retained_in_all_call_audit():
    context, limiter = Context(), Limiter()
    def fail(**kwargs):
        raise TimeoutError('synthetic')
    context.request_history_kline = fail
    proxy = minute.LimitedQuoteHistory(context, limiter, {'US.NVDA'}, 'first-page')
    with pytest.raises(TimeoutError):
        proxy.request_history_kline(code='US.NVDA', page_req_key=b'next')
    assert len(proxy.audit_rows) == 1 and not limiter.audit_rows
    assert proxy.audit_rows[0]['outcome'] == 'RAISED'
    assert proxy.audit_rows[0]['error_type'] == 'TimeoutError'


def test_existing_paginator_retains_delay_retry_reset_and_exact_requests():
    original = (REPO / minute.MINUTE_SOURCE).read_text(encoding='utf-8')
    function = next(x for x in ast.parse(original).body if isinstance(x, ast.FunctionDef) and x.name == 'call_history')
    sleeps, requests = [], []
    namespace = {'Any': object, 'pd': pd, 'time': SimpleNamespace(sleep=sleeps.append),
                 'CFG': {'page_size': 2, 'retry_attempts': 2, 'retry_base_seconds': 0}}
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<existing-call-history>', 'exec'), namespace)
    class Paged:
        def request_history_kline(self, **kwargs):
            requests.append(kwargs.copy())
            i = len(requests)
            if i == 2:
                return (1, 'synthetic page error', None)
            return (0, pd.DataFrame({'code': ['US.NVDA'], 'sequence': [i]}), b'next' if i in (1, 3) else None)
    api = SimpleNamespace(RET_OK=0, KLType=SimpleNamespace(K_1M='K_1M'), AuType=SimpleNamespace(NONE='NONE'),
                          Session=SimpleNamespace(ALL='ALL'))
    limiter = Limiter()
    proxy = minute.LimitedQuoteHistory(Paged(), limiter, {'US.NVDA'}, 'first-page')
    result = namespace['call_history'](proxy, api, 'US.NVDA', '2020-05-22', '2020-06-21')
    assert result.sequence.tolist() == [3, 4]
    assert len(requests) == len(proxy.audit_rows) == 4 and len(limiter.audit_rows) == 2
    assert [r.get('page_req_key') for r in requests] == [None, b'next', None, b'next']
    assert sleeps == [0.05, 0, 0.05]
    for request in requests:
        assert {k: v for k, v in request.items() if k != 'page_req_key'} == {
            'code': 'US.NVDA', 'start': '2020-05-22', 'end': '2020-06-21', 'ktype': 'K_1M',
            'autype': 'NONE', 'max_count': 2, 'extended_time': False, 'session': 'ALL'}


@pytest.mark.parametrize('raw', [pd.DataFrame({'code': ['US.AMD']}),
                                pd.DataFrame({'code': ['US.NVDA', 'US.AMD']}),
                                pd.DataFrame({'code': pd.Series(['US.NVDA', pd.NA], dtype='string')}),
                                pd.DataFrame({'open': [10.0]})])
def test_wrong_or_absent_raw_identity_fails_before_normalize_and_preserves_raw(tmp_path, raw):
    item = dict(ticker='NVDA', code='US.NVDA', start='2020-05-22', end='2020-05-22')
    fake = SimpleNamespace(call_history=lambda *args: raw,
                           normalize=lambda *args: pytest.fail('raw identity relabelled before validation'))
    with pytest.raises(ValueError, match='Unexpected raw provider identity'):
        minute.acquire_interval(tmp_path, item, fake, None, None)
    base, manifest = minute.interval_paths(tmp_path, item)
    assert (base / 'raw.parquet').exists()
    assert not manifest.exists() and not (base / 'minute.parquet').exists()


def test_raw_validation_does_not_modify_good_provider_data():
    raw = pd.DataFrame({'code': ['US.NVDA'], 'open': [353.01], 'time_key': ['2020-05-22 09:31:00']})
    before = raw.copy(deep=True)
    minute.validate_raw_identity(raw, {'code': 'US.NVDA'})
    pd.testing.assert_frame_equal(raw, before)


def test_main_records_total_api_calls_separately_from_limited_calls(tmp_path, monkeypatch):
    context = Context()
    context.set_sync_query_connect_timeout = lambda *args: None
    context.get_history_kl_quota = lambda **kw: (0, (1, 99, [{'code': 'US.NVDA'}])) if kw.get('get_detail') else (0, (1, 99))
    context.close = lambda: None
    sdk = SimpleNamespace(RET_OK=0, OpenQuoteContext=lambda **kw: context,
                          SysConfig=SimpleNamespace(set_all_thread_daemon=lambda *a: None))
    monkeypatch.setattr(minute.importlib, 'import_module', lambda *a: sdk)
    monkeypatch.setattr(minute, 'version', lambda *a: 'synthetic')
    monkeypatch.setattr(minute, 'load_module', lambda path, name: SimpleNamespace(HistoryKlineLimiter=Limiter))
    def acquire(root, item, helper, api, quote):
        quote.request_history_kline(code=item['code'])
        quote.request_history_kline(code=item['code'], page_req_key=b'one')
        quote.request_history_kline(code=item['code'], page_req_key=b'two')
        return {'status': 'ACQUIRED', 'item': item, 'output': {'row_count': 3}}
    monkeypatch.setattr(minute, 'acquire_interval', acquire)
    args = ['--repo', str(REPO), '--work-root', str(tmp_path / 'acquire'), '--tickers', 'NVDA',
            '--start', '2020-05-22', '--end', '2020-05-22', '--execute', '--pagination-rate-policy', 'first-page']
    assert minute.main(args) == 0
    report = json.loads((tmp_path / 'acquire/acquisition_report.json').read_text())
    assert report['history_request_count'] == len(report['request_audit']) == 3
    assert report['rate_limited_request_count'] == len(report['rate_limit_audit']) == 1
    assert report['pagination_rate_policy'] == 'first-page'


def test_cli_default_is_legacy_all_requests_and_dry_run_has_no_sdk_or_writes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(minute.importlib, 'import_module', lambda *a: pytest.fail('SDK imported'))
    root = tmp_path / 'absent'
    assert minute.main(['--work-root', str(root), '--tickers', 'NVDA', '--start', '2020-05-22', '--end', '2020-05-22']) == 0
    assert json.loads(capsys.readouterr().out)['pagination_rate_policy'] == 'all-requests'
    assert not root.exists()


def test_invalid_policy_rejected():
    with pytest.raises(ValueError, match='Unknown pagination rate policy'):
        minute.LimitedQuoteHistory(Context(), Limiter(), {'US.NVDA'}, 'fast')
