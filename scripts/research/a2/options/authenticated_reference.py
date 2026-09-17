"""One bounded, authenticated recovery of the frozen SPY 2024 reference gaps."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from scripts.common.storage_paths import resolve
from . import cli
from .contracts import Invalid, TEMPLATE, require
from .historical_quotes import (_history_get, _next_request, _remove_next_credentials,
                                _require_secret_safe, _write_json, classify_http)

TASK = 'OPTIONS_SPY2024_AUTHENTICATED_REFERENCE_FETCH_AND_CONTINUE_R1'
URL = 'https://api.massive.com/v2/aggs/ticker/SPY/range/1/day/2024-01-02/2024-09-17'
PARAMS = {'adjusted': False, 'sort': 'asc', 'limit': 50000}
COLUMNS = ['ticker', 'date', 'close', 'adjustment', 'source', 'currency']
SEMANTICS = 'DOCUMENTED_DAILY_REFERENCE_SEMANTICS'
MAX_BYTES = 20 * 1024 * 1024


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path):
    return json.loads(Path(path).read_bytes())


def _now():
    return datetime.now(timezone.utc).isoformat()


def _context(output):
    paths = resolve()
    root = paths.results_root / TEMPLATE / 'spy2024_reference_completion'
    require(output.parent == root, 'OUTPUT_BOUNDARY')
    frozen = output / 'authenticated_freeze.json'
    manifest_path = frozen if frozen.exists() else output / 'run_manifest.json'
    m = _read(manifest_path)
    require(m['task_id'] == TASK, 'TASK_CHANGED')
    require(m['status'] == 'FROZEN_AWAITING_SAFE_LOCAL_CREDENTIAL_INPUT', 'FROZEN_REQUEST_REQUIRED')
    prior = Path(m['completion_parent_run']) / 'run_manifest.json'
    require(_sha(prior) == m['completion_parent_manifest_sha256'], 'COMPLETION_PARENT_CHANGED')
    old = _read(prior)
    for key in ('plan', 'missing_reference_keys', 'overlap_keys', 'overlap_rule', 'fees', 'domain'):
        require(m[key] == old[key], 'INHERITED_FREEZE_CHANGED')
    parent_path = Path(m['parent_run']) / 'run_manifest.json'
    require(_sha(parent_path) == m['parent_manifest_sha256'], 'OBSERVED_PARENT_CHANGED')
    parent = _read(parent_path)
    missing = [r['reference_date'] for r in m['missing_reference_keys']]
    expected = [r['reference_date'] for r in parent['entry_lock']['records']
                if r.get('selection_reason') == 'REFERENCE_MISSING']
    require(missing == expected and len(missing) == 176 and len(set(missing)) == 176,
            'FROZEN_MISSING_KEYS_CHANGED')
    require(m['overlap_keys'] == ['2024-09-13', '2024-09-16', '2024-09-17'], 'OVERLAP_CHANGED')
    require(min(missing) == '2024-01-02' and max(missing) == '2024-09-12', 'MISSING_RANGE_CHANGED')
    p = m['request_plan']
    require(p['method'] == 'GET' and p['endpoint_if_needed'] == URL.removeprefix('https://api.massive.com')
            and all(p[k] == v for k, v in PARAMS.items())
            and p['maximum_http_requests_including_pages_recovery'] == 3, 'REQUEST_SCOPE_CHANGED')
    evidence = m['daily_semantics_evidence']
    require(evidence['status'] in {SEMANTICS,
        'DOCUMENTED_DAILY_AGGREGATE_CLOSE_COMPATIBLE_WITH_PARENT_CONDITIONAL_ANCHOR'}, 'SEMANTICS_NOT_DOCUMENTED')
    require(bool(evidence.get('evidence')), 'SEMANTICS_EVIDENCE_MISSING')
    require(all(isinstance(evidence.get(k), str) and evidence[k].strip()
                for k in ('date_semantics', 'session_basis')), 'SEMANTICS_TEXT_MISSING')
    for item in evidence['evidence']:
        require(_sha(item['path']) == item['sha256'], 'SEMANTICS_EVIDENCE_CHANGED')
    cache_root = paths.cache_root / 'options_expression_pilot_r1' / 'spy2024_reference_completion'
    cache = Path(m['cache']).resolve()
    require(cache == cache_root / output.name, 'CACHE_BOUNDARY')
    return m, parent, missing, cache_root, cache


def _page(payload):
    """Validate the whole returned page before accepting its 2024 references."""
    scope = {'raw_rows': 0, 'dates': [], 'qualification': 'REJECTED'}
    if not isinstance(payload, dict):
        return [], scope | {'reason': 'RESPONSE_OBJECT_REQUIRED'}
    raw = payload.get('results', [])
    scope['raw_rows'] = len(raw) if isinstance(raw, list) else 0
    dates, rows, rejected, reason = [], {}, {}, None
    if isinstance(raw, list):
        for item in raw:
            try:
                t = item['t']
                require(isinstance(t, int) and not isinstance(t, bool), 'TIMESTAMP_NOT_UNIX_MS')
                stamp = pd.Timestamp(t, unit='ms', tz='UTC').tz_convert('America/New_York')
                day = stamp.date().isoformat()
                dates.append(day)
            except (Invalid, ValueError, KeyError, TypeError, OverflowError):
                reason = 'TIMESTAMP_SCOPE_UNDETERMINED'
                continue
            if stamp != stamp.normalize():
                rejected[day] = 'DAILY_INTERVAL_START_NOT_MIDNIGHT_NY'
                continue
            c = item.get('c')
            if not (isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c) and c > 0):
                rejected[day] = 'CLOSE_NOT_FINITE_POSITIVE'
                continue
            row = dict(ticker='SPY', date=day, close=c, adjustment='raw', source='MASSIVE_CUSTOM_BARS', currency='USD')
            if day in rows and rows[day] != row:
                rejected[day] = 'CONFLICTING_DUPLICATE_DAY'
            rows[day] = row
    scope['dates'] = sorted(set(dates))
    if dates:
        scope.update(date_min=min(dates), date_max=max(dates))
    valid_count = payload.get('resultsCount')
    if not (isinstance(raw, list) and isinstance(valid_count, int) and not isinstance(valid_count, bool)
            and valid_count == len(raw)):
        reason = reason or 'RESULT_COUNT_INVALID'
    if payload.get('ticker') != 'SPY' or payload.get('adjusted') is not False:
        reason = reason or 'TICKER_OR_ADJUSTMENT_INVALID'
    if payload.get('status') != 'OK':
        reason = reason or 'PROVIDER_STATUS_NOT_OK'
    if payload.get('queryCount') is not None and not (isinstance(payload['queryCount'], int)
            and not isinstance(payload['queryCount'], bool) and payload['queryCount'] >= scope['raw_rows']):
        reason = reason or 'QUERY_COUNT_INVALID'
    if any(not ('2024-01-02' <= day <= '2024-09-17') for day in dates):
        reason = 'RETURNED_DATE_OUTSIDE_REQUEST_2024'
    for day in rejected:
        rows.pop(day, None)
    scope.update(rejected_dates=rejected, duplicate_rows=len(dates)-len(set(dates)),
                 reason=reason or ('EMPTY_RESPONSE' if not raw else 'NO_QUALIFIED_ROWS' if not rows else 'PARTIALLY_QUALIFIED_ROWS' if rejected else 'QUALIFIED_ROWS'),
                 qualified_rows=0 if reason else len(rows),
                 qualification='REJECTED' if reason else ('EMPTY' if not raw else 'NO_QUALIFIED_ROWS' if not rows else 'QUALIFIED'))
    return ([] if reason else list(rows.values())), scope


def _budget_size(output, cache, ancillary=0):
    size = sum(p.stat().st_size for root in (output, output.with_name(output.name+'_offline'), cache) if root.exists()
               for p in root.rglob('*') if p.is_file())
    ledger = cache.parent / 'authenticated_daily_state.json'
    size += (ledger.stat().st_size if ledger.exists() else 0) + ancillary
    require(size <= MAX_BYTES - 2 * 1024 * 1024, 'ARTIFACT_SIZE_BUDGET')


def _fetch(m, output, cache_root, cache, api_key, prompt_api_key):
    cache.mkdir(parents=True, exist_ok=True)
    ledger = cache_root / 'authenticated_daily_state.json'
    lock = cache_root / 'authenticated_daily_state.lock'
    # A stale lock is deliberately not stolen: an interrupted HTTP can be unknown.
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise Invalid('AUTHENTICATED_FETCH_ALREADY_RUNNING_OR_UNRESOLVED') from None
    key = None
    try:
        identity = dict(url=URL, params=PARAMS, completion_parent_sha256=m['completion_parent_manifest_sha256'])
        state = _read(ledger) if ledger.exists() else dict(identity=identity, requests=[], next_params=PARAMS, terminal_reason=None)
        require(state['identity'] == identity and len(state['requests']) <= 3, 'SHARED_BUDGET_IDENTITY_CHANGED')
        start_count = len(state['requests'])
        for request in state['requests']:
            if request['status'] in {'PENDING', 'UNKNOWN_COMPLETION'}:
                state['terminal_reason'] = 'UNKNOWN_PRIOR_REQUEST_NOT_RETRIED'
        if not state['terminal_reason'] and len(state['requests']) >= 3:
            state['terminal_reason'] = 'SHARED_THREE_REQUEST_BUDGET_EXHAUSTED'
        key = api_key or os.environ.get('MASSIVE_API_KEY')
        credential_entry = 'EXPLICIT_IN_MEMORY_ARGUMENT' if api_key else ('MASSIVE_API_KEY_PROCESS_ENVIRONMENT' if key else 'NONE')
        if not state['terminal_reason'] and not key and prompt_api_key:
            key = cli._hidden_massive_key()
            credential_entry = 'ORIGINAL_LOCAL_HIDDEN_INPUT'
        while not state['terminal_reason'] and state['next_params'] is not None:
            if len(state['requests']) >= 3:
                state['terminal_reason'] = 'SHARED_THREE_REQUEST_BUDGET_EXHAUSTED'
                break
            if not key:
                break
            if state['requests']:
                last = state['requests'][-1].get('completed_at_epoch')
                if last is not None:
                    time.sleep(max(0, 12.5 - (time.time() - last)))
            params = state['next_params']
            require(not any(r['params'] == params for r in state['requests']), 'PAGINATION_CYCLE_REJECTED')
            _budget_size(output, cache, m.get('ancillary_artifact_bytes', 0))
            request = dict(number=len(state['requests']) + 1, url=URL, params=params,
                           status='PENDING', started_at_utc=_now(), output=str(output))
            state['requests'].append(request)
            _write_json(ledger, state, api_key=key)
            try:
                request['credential_passed_to_transport'] = True
                status, payload = _history_get(URL, params=params, api_key=key,
                    headers={'Accept': 'application/json'}, timeout=(10, 45), allow_redirects=False)
                payload = _remove_next_credentials(payload)
                _require_secret_safe(payload, key, 'RESPONSE_CONTAINS_CREDENTIAL_NOT_PERSISTED')
            except Exception as exc:
                request.update(status='UNKNOWN_COMPLETION', exception_type=type(exc).__name__,
                               completed_at_epoch=time.time())
                state['terminal_reason'] = 'TRANSPORT_OR_SECRET_SAFETY_FAILURE_NO_AUTOMATIC_RETRY'
                _write_json(ledger, state, api_key=key)
                break
            request.update(status='COMPLETED', http_status=status, completed_at_epoch=time.time(),
                           provider_status=payload.get('status') if isinstance(payload, dict) else None)
            explicit = status == 403 and isinstance(payload, dict) and any(payload.get(field) in {
                'NOT_AUTHORIZED', 'NOT_ENTITLED', 'SUBSCRIPTION_REQUIRED', 'PERMISSION_DENIED', 'PLAN_NOT_SUPPORTED'}
                for field in ('status', 'error', 'code') if isinstance(payload.get(field), str))
            request['http_facts'] = classify_http(status, row_count=len(payload.get('results', []))
                if isinstance(payload, dict) and isinstance(payload.get('results', []), list) else 0,
                permission_explicit=explicit)
            if status != 200:
                state['terminal_reason'] = {401: 'AUTHENTICATION_401', 403: 'PERMISSION_403' if explicit else 'HTTP_403_ENTITLEMENT_UNKNOWN',
                    429: 'RATE_LIMIT_429_HEADERS_UNAVAILABLE_NO_RETRY'}.get(status, 'HTTP_NOT_200_NO_AUTOMATIC_RETRY')
                request['response_metadata'] = {k: payload[k] for k in ('status', 'error', 'message') if isinstance(payload, dict) and k in payload}
            else:
                rows, scope = _page(payload)
                request['scope'] = scope
                if scope['qualification'] != 'REJECTED':
                    page_path = cache / ('daily_page_%d.json' % request['number'])
                    _write_json(page_path, payload, api_key=key)
                    request.update(cache_path=str(page_path), cache_sha256=_sha(page_path))
                else:
                    state['terminal_reason'] = scope['reason']
                try:
                    state['next_params'] = _next_request(payload.get('next_url') if isinstance(payload, dict) else None, URL, PARAMS)
                    if state['next_params'] is None:
                        state['terminal_reason'] = state['terminal_reason'] or 'RESPONSE_PAGINATION_COMPLETE'
                    elif any(r['params'] == state['next_params'] for r in state['requests']):
                        state['terminal_reason'] = 'PAGINATION_CYCLE_REJECTED'
                except (Invalid, TypeError, ValueError):
                    state['terminal_reason'] = state['terminal_reason'] or 'PAGINATION_SCOPE_REJECTED'
            _write_json(ledger, state, api_key=key)
        _write_json(ledger, state, api_key=key)
        rows, read_times, conflicted = {}, {}, set()
        for request in state['requests']:
            if 'cache_path' not in request:
                continue
            path = Path(request['cache_path'])
            require(path.parent.parent == cache_root and _sha(path) == request['cache_sha256'], 'CACHED_RESPONSE_CHANGED')
            accepted, scope = _page(_read(path))
            require(scope['qualification'] != 'REJECTED', 'CACHED_RESPONSE_NO_LONGER_QUALIFIED')
            conflicted.update(day for day, reason in scope.get('rejected_dates', {}).items()
                              if reason == 'CONFLICTING_DUPLICATE_DAY')
            for row in accepted:
                if row['date'] in rows and rows[row['date']] != row:
                    conflicted.add(row['date'])
                rows[row['date']] = row
                read_times.setdefault(row['date'], datetime.fromtimestamp(request['completed_at_epoch'], timezone.utc).isoformat())
        for day in conflicted:
            rows.pop(day, None)
            read_times.pop(day, None)
        receipt = dict(status=state['terminal_reason'] or 'WAITING_LOCAL_HIDDEN_INPUT',
            credential_entry=credential_entry, credential_entered_request_process=any(
                r.get('credential_passed_to_transport') is True for r in state['requests'][start_count:]),
            credential_ever_entered_shared_request_process=any(r.get('credential_passed_to_transport') is True for r in state['requests']),
            daily_http_this_invocation=len(state['requests'])-start_count,
            daily_http_shared=len(state['requests']), requests=state['requests'], conflicting_dates=sorted(conflicted),
            daily_http_completed=sum(r.get('http_status') is not None for r in state['requests']),
            daily_http_unknown=sum(r['status'] in {'PENDING', 'UNKNOWN_COMPLETION'} for r in state['requests']),
            qualified_reference_read_at=read_times,
            response_unique_qualified_dates=len(rows), actual_contact_dates=sorted({d for r in state['requests'] for d in r.get('scope', {}).get('dates', [])}),
            credential_printed=False, credential_hashed=False, credential_written_to_file_or_command_line=False)
        _write_json(output / 'authenticated_fetch.json', receipt, api_key=key)
        return rows, receipt, key
    finally:
        os.close(fd)
        lock.unlink()


def _report(output, result, parent, key):
    """Render existing statistics; this adds no economic calculation or comparison."""
    current = _read(output/'run_manifest.json')
    summary = current.get('summary') or parent.get('summary', {})
    groups = current.get('continuation', {}).get('groups', {})
    statuses = dict(Counter(str(r.get('http_status', 'UNKNOWN')) for r in result['requests']))
    value = lambda item, field: '未计算' if item.get(field) is None else str(item[field])
    lines = [
        f"1. 凭证本次实际进入请求进程：{result['credential_entered_request_process']}；入口：{result['credential_entry']}。仅复用缓存时不计作重新注入。",
        f"2. 本次日线 HTTP 预算计次 {result['daily_http_this_invocation']}；所有尝试/重启累计 {result['daily_http_shared']}/3；已获响应 {result['daily_http_completed']}、完成未知 {result['daily_http_unknown']}。固定范围 SPY 2024-01-02—2024-09-17，adjusted=false；状态 {statuses}；返回行数 {sum(r.get('scope', {}).get('raw_rows', 0) for r in result['requests'])}。",
        f"3. 原176缺口恢复 {result['recovered_reference_keys']}；固定246母体不变。原67/246条件金额覆盖变为 {value(summary.get('cash', {}), 'count')}/246；q覆盖 {value(summary.get('q', {}), 'count')}/246。",
        '4. 下表只引用原runner的描述性汇总。旧结果按父身份分组并对账；新增结果不能解释为独立确认，两组均值差不是因果纠偏。',
        '', '| 组别 | q数量/日/月 | q均值/中位数 | q正/负/零 | 金额数量/日/月 | 金额均值/中位数 | 金额正/负/零 | q正金额负 |',
        '|---|---|---|---|---|---|---|---|']
    old = groups.get('prior_reconciled', {}).get('summary') or parent.get('summary', {})
    new = groups.get('newly_referenced', {}).get('summary') or {}
    for name, group in [('原完整案例', old), ('新增完整案例', new), ('合并完整案例', summary)]:
        q, cash = group.get('q', {}), group.get('cash', {})
        cells = [name]
        for stat in (q, cash):
            cells.extend('/'.join(value(stat, field) for field in fields) for fields in
                [('count', 'decision_days', 'months'), ('mean', 'median'), ('positive', 'negative', 'zero')])
        lines.append('| '+' | '.join(cells+[value(group, 'q_positive_cash_negative')])+' |')
    outcome = 'A：合格新增已接续原CLI与离线核对' if result['recovered_reference_keys'] else (
        'C：等待一次本地隐藏输入，尚未发请求' if not result['daily_http_shared'] else 'B：本次响应无可接续新增；不把缺失当作持现金')
    lines += ['', f"终点：{outcome}。端点/恢复状态：{result['status']}。",
        f"本次实际经济 CLI {result['economic_cli_runs']} 次，离线 CLI {result['offline_cli_runs']} 次；离线缓存复用 {result.get('offline_reused', False)}。未获条件金额评价的固定计划权重：{value(summary.get('cash', {}), 'unidentified_weight')}。",
        '历史首发/接收可得性、正式执行、显示数量及逐系列经济权利仍未知；这是归档条件诊断。半日市时刻歧义、未解决头寸及缺价按原规则保留。',
        '原70项参考价和选择不替换；固定3日重叠差异见 reference_overlap.json。无新增时仅引用父结果；有新增时旧70/67/69对账与新增分组见 run_manifest.json。',
        '训练、校准、参数搜索、商业支出与交易均为0；本次不生成2025/2026评价，不自动续查或扩展候选。']
    text = '\n'.join(lines)+'\n'
    _require_secret_safe(text, key, 'REPORT_CONTAINS_CREDENTIAL')
    (output/'认证续接结论.md').write_text(text, encoding='utf-8')


def _continue(output, m, parent, missing, rows, receipt, key):
    additions = [rows[day] for day in missing if day in rows]
    old_references = {r['reference_date']: r.get('reference_close') for r in parent['entry_lock']['records']}
    overlaps = []
    for day in m['overlap_keys']:
        old, new = old_references.get(day), rows.get(day, {}).get('close')
        overlaps.append(dict(date=day, old_close=old, fetched_close=new,
            difference=None if old is None or new is None else new-old,
            equal_at_frozen_tolerance=None if old is None or new is None else abs(new-old) <= m['overlap_rule']['numeric_equal_abs_usd'],
            old_reference_replaced=False))
    _write_json(output / 'reference_overlap.json', overlaps, api_key=key)
    receipt.update(recovered_reference_keys=len(additions), inherited_missing_reference_keys=len(missing))
    _write_json(output / 'authenticated_fetch.json', receipt, api_key=key)
    rejected = {day: reason for request in receipt['requests']
                for day, reason in request.get('scope', {}).get('rejected_dates', {}).items()}
    rejected.update({day: 'CONFLICTING_DUPLICATE_DAY' for day in receipt['conflicting_dates']})
    resolution = [record | dict(source=rows.get(record['reference_date'], {}).get('source'),
        raw_close=rows.get(record['reference_date'], {}).get('close'), evidence=str(output/'authenticated_fetch.json'),
        status='RESTORED_QUALIFIED_REFERENCE' if record['reference_date'] in rows else rejected.get(record['reference_date'], receipt['status']),
        read_at_utc=receipt['qualified_reference_read_at'].get(record['reference_date']),
        restored=record['reference_date'] in rows) for record in m['missing_reference_keys']]
    resolution_text = pd.DataFrame(resolution).to_csv(index=False,
        columns=['decision_id', 'reference_date', 'entry_date', 'exit_date', 'source', 'raw_close', 'evidence', 'status', 'read_at_utc', 'restored'])
    _require_secret_safe(resolution_text, key, 'RESOLUTION_CONTAINS_CREDENTIAL')
    (output/'reference_resolution.csv').write_text(resolution_text, encoding='utf-8')
    current_fields = {field: copy.deepcopy(m[field]) for field in (
        'candidate_registration', 'cumulative_candidates', 'new_scientific_candidates', 'new_training',
        'new_search', 'new_calibration', 'commercial_spend', 'trades', 'research_identity',
        'completion_parent_run', 'completion_parent_manifest_sha256', 'browser_attempt',
        'daily_semantics_evidence', 'request_plan', 'started_at_utc', 'frozen_at_utc', 'ancillary_artifact_bytes') if field in m}
    current_fields.update(result_root=str(output), cache=m['cache'], requests=receipt['requests'],
        authenticated_fetch=receipt, reference_resolution_sha256=_sha(output/'reference_resolution.csv'),
        http_budget=m['http_budget'] | {'new_daily_actual': receipt['daily_http_shared'],
            'research_budget_charged_total': 239+receipt['daily_http_shared'], 'public_budget_charged_total': 227})
    current = _read(output/'run_manifest.json')
    complete = current.get('status') == 'COMPLETE_CONDITIONAL_ARCHIVE_DIAGNOSTIC'
    if complete:
        require(current['reference_resolution_sha256'] == _sha(output/'reference_resolution.csv'), 'CACHED_RESOLUTION_CHANGED')
    if not complete:
        original = (output/'run_manifest.json').read_bytes()
        if original != (output/'authenticated_freeze.json').read_bytes():
            digest = hashlib.sha256(original).hexdigest()
            previous = output/('previous_manifest_'+digest+'.json')
            _require_secret_safe(original, key, 'PREVIOUS_MANIFEST_CONTAINS_CREDENTIAL')
            if not previous.exists():
                previous.write_bytes(original)
            current_fields['previous_manifest'] = dict(path=str(previous), sha256=digest, status=current.get('status'))
    if not additions:
        require(not complete, 'PRESERVE_COMPLETED_ECONOMIC_RESULTS')
        end = copy.deepcopy(m)
        end.update(current_fields, status='WAITING_LOCAL_HIDDEN_INPUT' if receipt['status'] == 'WAITING_LOCAL_HIDDEN_INPUT'
                   else 'COMPLETED_NO_ADMISSIBLE_REFERENCE', endpoint_stop_reason=receipt['status'],
                   recovered_reference_keys=0, economic_cli_runs=0, offline_cli_runs=0)
        _write_json(output/'run_manifest.json', end, api_key=key)
        _budget_size(output, Path(m['cache']), m.get('ancillary_artifact_bytes', 0))
        return receipt | {'economic_cli_runs': 0, 'offline_cli_runs': 0}
    response_evidence = [{'path': r['cache_path'], 'sha256': r['cache_sha256'],
        'request': {'url': r['url'], 'params': r['params']}, 'scope': r['scope']} for r in receipt['requests']
        if 'cache_path' in r]
    qualification = dict(status='QUALIFIED_RAW_USD_DAILY_REFERENCE', provider='MASSIVE', adjusted=False,
        currency='USD', date_semantics=m['daily_semantics_evidence']['date_semantics'],
        session_basis=m['daily_semantics_evidence']['session_basis'],
        evidence=m['daily_semantics_evidence']['evidence'] + [{'path': e['path'], 'sha256': e['sha256']} for e in response_evidence],
        response_evidence=response_evidence, response_checks='ticker, adjusted, status, counts, NY midnight timestamp, finite positive close',
        overlap_evidence=str(output / 'reference_overlap.json'),
        overlap_evidence_sha256=_sha(output/'reference_overlap.json'), historical_first_publication='UNKNOWN')
    _write_json(output / 'reference_qualification.json', qualification, api_key=key)
    additions_path = output / 'reference_additions.json'
    _write_json(additions_path, additions, api_key=key)
    if not complete:
        require(not (output / 'observed_frontier.csv').exists(), 'PRESERVE_PARTIAL_ECONOMIC_RESULTS')
        economic = copy.deepcopy(parent)
        for field in ('entry_lock', 'summary', 'calls', 'result_sha256', 'completed_at_utc', 'actual_loaded_sources'):
            economic.pop(field, None)
        economic.update(current_fields)
        economic.update(task_id=TASK, status='FROZEN_BEFORE_ENTRY_SELECTION',
            observed_parent={'run': m['parent_run'], 'manifest_sha256': m['parent_manifest_sha256']},
            authenticated_request_freeze={'path': str(output / 'authenticated_freeze.json'), 'sha256': _sha(output / 'authenticated_freeze.json')},
            reference_additions={'path': str(additions_path), 'sha256': _sha(additions_path), 'columns': COLUMNS,
                'allowed_reference_dates': missing, 'qualification': qualification})
        _write_json(output / 'run_manifest.json', economic, api_key=key)
        require(cli.main(['--mode', 'spy2024-observed-frontier', '--output', str(output)]) == 0, 'ECONOMIC_CLI_FAILED')
    offline = output.with_name(output.name + '_offline')
    offline_runs = 0
    if offline.exists():
        saved, evaluated = _read(offline/'run_manifest.json'), _read(output/'run_manifest.json')
        require(saved.get('offline_content_identical') is True, 'PRESERVE_INCOMPLETE_OFFLINE_RUN')
        require((output/'observed_frontier.csv').is_file() and (offline/'observed_frontier.csv').is_file(), 'CACHED_RESULT_FILE_MISSING')
        require(_sha(output/'observed_frontier.csv') == evaluated.get('result_sha256')
                and _sha(offline/'observed_frontier.csv') == saved.get('result_sha256'), 'CACHED_RESULT_BYTES_CHANGED')
        require(saved.get('result_sha256') == evaluated.get('result_sha256')
                and saved.get('entry_lock', {}).get('sha256') == evaluated.get('entry_lock', {}).get('sha256'), 'CACHED_OFFLINE_CONTENT_CHANGED')
    else:
        require(cli.main(['--mode', 'spy2024-observed-frontier', '--output', str(offline),
                          '--source-run', str(output), '--offline']) == 0, 'OFFLINE_CLI_FAILED')
        offline_runs = 1
    _budget_size(output, Path(m['cache']), m.get('ancillary_artifact_bytes', 0))
    return receipt | {'economic_cli_runs': 0 if complete else 1, 'offline_cli_runs': offline_runs,
                      'offline_reused': offline_runs == 0,
                      'economic_status': _read(output / 'run_manifest.json')['status'], 'offline_run': str(offline)}


def run_authenticated_reference(output, *, api_key=None, prompt_api_key=False):
    output = Path(output).resolve()
    m, parent, missing, cache_root, cache = _context(output)
    frozen = output / 'authenticated_freeze.json'
    if not frozen.exists():
        raw = (output / 'run_manifest.json').read_bytes()
        _require_secret_safe(raw, api_key, 'FREEZE_CONTAINS_CREDENTIAL')
        frozen.write_bytes(raw)
    rows, receipt, key = _fetch(m, output, cache_root, cache, api_key, prompt_api_key)
    try:
        result = _continue(output, m, parent, missing, rows, receipt, key)
        _report(output, result, parent, key)
        _budget_size(output, cache, m.get('ancillary_artifact_bytes', 0))
        return result
    finally:
        key = None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--prompt-api-key', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = run_authenticated_reference(args.output, prompt_api_key=args.prompt_api_key)
        print(json.dumps({k: result[k] for k in ('status', 'daily_http_shared', 'recovered_reference_keys', 'economic_cli_runs', 'offline_cli_runs')}))
        return 0 if result.get('economic_cli_runs') or result.get('economic_status') else 3
    except Invalid as exc:
        # Only the fixed internal reason is emitted; no HTTP exception URL is rendered.
        print(json.dumps({'status': 'STOPPED', 'reason': str(exc)}))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
