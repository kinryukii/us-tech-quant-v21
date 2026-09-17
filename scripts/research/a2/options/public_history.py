"""Bounded public daily observations for R1; never executable Quote objects."""
from __future__ import annotations
import hashlib
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd
import pyarrow.parquet as pq
import requests

from scripts.common.storage_paths import resolve
from .contracts import TEMPLATE, Invalid, calendar, require
from .historical_quotes import _write_json

PARENT = 'runs/20260914T101900Z'
PARENT_ID = '36436764425114a3dbeed7068f23678995c3676ea3ff5ad714b0fe85ed5cf7a3'
DOLT = 'https://www.dolthub.com/api/v1alpha1/post-no-preference/options'
REPOS = ('SaidBahaDev/options-data', 'anahatsingh-ui/options-dataset-hist')

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

class PublicSession:
    """One task journal and external cache; no account auth or Massive access."""
    def __init__(self, output, offline=False):
        self.output = Path(output).resolve()
        paths = resolve()
        require(self.output.parent == paths.results_root / TEMPLATE / 'public_history', 'PUBLIC_OUTPUT_BOUNDARY')
        self.cache = paths.cache_root / 'options_expression_pilot_r1' / 'public_history' / self.output.name
        self.offline = offline
        self.output.mkdir(parents=True, exist_ok=True)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.path = self.output / 'run_manifest.json'
        if self.path.exists():
            self.manifest = json.loads(self.path.read_bytes())
        else:
            parent = json.loads((paths.results_root / TEMPLATE / PARENT / 'run_manifest.json').read_bytes())
            require(parent['run_identity'] == PARENT_ID and parent['economic_http_requests'] == 12, 'PUBLIC_PARENT_CHANGED')
            started = time.time()
            self.manifest = dict(research_identity=TEMPLATE, mode='public-history', parent_run=PARENT,
                parent_run_identity=PARENT_ID, started_at_utc=utcnow(), started_epoch=started,
                deadline_epoch=started+10800, acquisition_deadline_epoch=started+9000,
                public_request_limit=400, inherited_massive_requests=12, research_total_limit=1200,
                cache_limit_bytes=min(2*1024**3, int(shutil.disk_usage(self.cache).free*.05)),
                requests=[], source_status={}, sources={}, invocation_history=[],
                economic_status='NOT_EVALUATED', evaluate_calls=0, economic_pairs=0,
                new_model_fits=0, new_template_candidates=0, new_parameter_search=0, commercial_spend=0, trades=0)
            self.save()
        require(self.manifest['research_identity'] == TEMPLATE and self.manifest['public_request_limit'] == 400,
                'PUBLIC_MANIFEST_CHANGED')
        self.http = requests.Session()
        self.http.trust_env = False

    def save(self):
        _write_json(self.path, self.manifest)

    def get(self, source, url, *, params=None, method='GET', headers=None, maximum=20*1024**2):
        target = urlsplit(url)
        permitted = (url.startswith(DOLT) or
            any(url.startswith('https://api.github.com/repos/'+repo) for repo in REPOS) or
            any(url.startswith('https://raw.githubusercontent.com/'+repo+'/') for repo in REPOS) or
            url.startswith('https://static.philippdubach.com/data/options/'))
        require(permitted and target.scheme == 'https' and not target.username and not target.query,
                'PUBLIC_URL_BOUNDARY')
        require(method in {'GET', 'HEAD'}, 'PUBLIC_READ_ONLY')
        headers = headers or {}
        require(set(headers) <= {'Range', 'Accept'}, 'PUBLIC_HEADERS_BOUNDARY')
        identity = dict(source=source, method=method, url=url, params=params or {}, headers=headers)
        key = digest(json.dumps(identity, sort_keys=True).encode())
        prior = [r for r in self.manifest['requests'] if r['request_id'] == key]
        start_attempt = 0
        if prior:
            previous = prior[-1]
            if previous['status'] == 'COMPLETE':
                path = self.cache / previous['file']
                require(path.exists() and _file_digest(path) == previous['sha256'], 'PUBLIC_CACHE_CHANGED')
                return previous, path
            repair = self.manifest.get('bounded_latency_repair', {})
            require(not self.offline and len(prior) == 1 and previous['status'] == 'FAILED' and
                    previous.get('exception_type') == 'ReadTimeout' and source == 'DOLT' and
                    key in repair.get('one_retry_request_ids', []), 'PUBLIC_UNCERTAIN_ATTEMPT_NO_RETRY')
            start_attempt = 1
        require(not self.offline, 'OFFLINE_CACHE_MISS')
        for retry in range(start_attempt, 2):
            require(len(self.manifest['requests']) < min(self.manifest.get('direct_request_limit', 400),
                    400-self.manifest.get('inherited_public_requests', 0),
                    1200-self.manifest['inherited_massive_requests']-self.manifest.get('inherited_public_requests', 0)),
                    'PUBLIC_REQUEST_BUDGET')
            read_timeout = self.manifest.get('bounded_latency_repair', {}).get('read_timeout_seconds', 45)
            require(read_timeout in (45, 60), 'PUBLIC_TIMEOUT_BOUNDARY')
            require(time.time()+read_timeout+20 < self.manifest['acquisition_deadline_epoch'], 'PUBLIC_ACQUISITION_TIME_BUDGET')
            used = sum(p.stat().st_size for p in self.cache.rglob('*') if p.is_file())
            maximum = min(maximum, self.manifest['cache_limit_bytes']-used)
            require(maximum > 0, 'PUBLIC_CACHE_BUDGET')
            last = self.manifest['requests'][-1] if self.manifest['requests'] else {}
            time.sleep(max(0., last.get('finished_epoch', 0)+1-time.time()))
            entry = dict(identity, request_id=key, status='PENDING', retry=retry, requested_at_utc=utcnow(), started_epoch=time.time())
            self.manifest['requests'].append(entry)
            self.save()
            path = self.cache / (key+f'.{retry}.raw')
            temporary = path.with_suffix('.partial')
            count = 0
            try:
                with self.http.request(method, url, params=params, headers=headers, stream=True,
                                       allow_redirects=False, timeout=(10, read_timeout)) as response:
                    entry.update(http_status=response.status_code, content_type=response.headers.get('Content-Type'),
                                 content_length=response.headers.get('Content-Length'),
                                 content_range=response.headers.get('Content-Range'),
                                 retry_after=response.headers.get('Retry-After'))
                    if method != 'HEAD' and response.headers.get('Content-Length'):
                        require(int(response.headers['Content-Length']) <= maximum, 'PUBLIC_FILE_SIZE_BUDGET')
                    with temporary.open('xb') as stream:
                        for chunk in response.iter_content(65536):
                            count += len(chunk)
                            require(time.time() < self.manifest['acquisition_deadline_epoch'], 'PUBLIC_ACQUISITION_TIME_BUDGET')
                            require(count <= maximum, 'PUBLIC_FILE_SIZE_BUDGET')
                            stream.write(chunk)
                    temporary.replace(path)
                    entry.update(status='COMPLETE', bytes=count, file=path.name, sha256=_file_digest(path))
            except Exception as exc:
                entry.update(status='FAILED', exception_type=type(exc).__name__, bytes=count,
                             reason=str(exc) if isinstance(exc, Invalid) else 'PUBLIC_NETWORK_OR_IO_ERROR')
            finally:
                entry['finished_epoch'] = time.time()
                self.save()
            require(entry['status'] == 'COMPLETE', entry.get('reason','PUBLIC_REQUEST_FAILED'))
            if entry.get('http_status') != 429 or retry or not self.manifest.get('automatic_429_retry', True):
                return entry, path
            value = entry.get('retry_after')
            try:
                delay = float(value)
            except (TypeError, ValueError):
                from email.utils import parsedate_to_datetime
                try:
                    delay = parsedate_to_datetime(value).timestamp()-time.time()
                except (TypeError, ValueError):
                    delay = 60.
            if delay > 60 or delay < 0:
                return entry, path
            time.sleep(delay)
        return entry, path

    def sql(self, query, *, url=DOLT):
        require(query.startswith(('SHOW ', 'SELECT ')), 'PUBLIC_SQL_READ_ONLY')
        if query.startswith('SELECT ') and 'option_chain' in query:
            require("date >= '2023-01-01'" in query and "date < '2026-01-01'" in query,
                    'PUBLIC_SQL_OBSERVATION_CUTOFF')
        record, path = self.get('DOLT', url, params={'q':query})
        require(record['http_status'] == 200, 'DOLT_HTTP_'+str(record['http_status']))
        body = json.loads(path.read_bytes())
        require(body.get('query_execution_status') in {'Success','RowLimit','Error'}, 'DOLT_STATUS_MISSING')
        return body

def _identity_sources():
    """Read pinned identities only; callers must project CSV/Parquet columns."""
    paths = resolve()
    base = paths.results_root / TEMPLATE
    reviewed = base / 'overnight/20260913T032957JST/reviewed'
    pins = {
        'parent_config': (base / 'runs/20260914T101900Z/run_config.json',
                          '36436764425114a3dbeed7068f23678995c3676ea3ff5ad714b0fe85ed5cf7a3'),
        'reviewed_manifest': (reviewed / 'run_manifest.json',
                              'a90d1d4837d8d18774dde05a66133310abba61e4c2169d6ba2365ea5bacef99c'),
        'opportunities': (reviewed / 'real_opportunities.csv',
                          '2ed864e831b05e674d36b859e5e174273776439ea852664c1f1a8bc0664f19ea'),
        'membership': (paths.results_root / 'A_VS_A2_QUARTERLY_13F_R1/universe/daily_eligible_universe_membership.parquet',
                       'c03cc35f3569cb968c3d48cefd08488c75c02389e5e430d11526a0284ad2b637'),
        'original_nine': (reviewed / 'option_evidence/fixed_probe_plan.json',
                          'c71e8ee8701d0c3e8cd339e53eb4ccb4d734c6b519da635328f7e48922b784c5'),
    }
    raw = {}
    for name, (path, expected) in pins.items():
        raw[name] = path.read_bytes()
        require(digest(raw[name]) == expected, 'PUBLIC_IDENTITY_SOURCE_CHANGED:' + name)
    parent = json.loads(raw['parent_config'])
    inherited = json.loads(raw['reviewed_manifest'])
    require(parent['parent_bindings']['reviewed/run_manifest.json'] == pins['reviewed_manifest'][1],
            'PUBLIC_REVIEWED_PARENT_BINDING')
    require(parent['parent_bindings']['reviewed/option_evidence/fixed_probe_plan.json'] == pins['original_nine'][1],
            'PUBLIC_NINE_PARENT_BINDING')
    require(inherited['artifact_sha256']['real_opportunities.csv'] == pins['opportunities'][1],
            'PUBLIC_OPPORTUNITY_PARENT_BINDING')
    require(any(item.get('sha256') == pins['membership'][1] and
                Path(item.get('path', '')).resolve() == pins['membership'][0].resolve()
                for item in inherited['bound_source_reads']), 'PUBLIC_MEMBERSHIP_PARENT_BINDING')
    nine = json.loads(raw['original_nine'])['selected']
    require(nine == parent['selected'] and len(nine) == 9, 'PUBLIC_ORIGINAL_NINE_BINDING')
    bindings = {name: {'path': str(path), 'sha256': expected}
                for name, (path, expected) in pins.items()}
    return raw, bindings, nine


def load_identity_projection():
    """Return original 15,000 identity/date rows, bindings and original nine.

    No score, holding, price or outcome column crosses this reader. Membership
    dates certify the stock identity only, never historical option deliverables.
    """
    import io
    raw, bindings, nine = _identity_sources()
    columns = ['decision_id', 'signal_date', 'underlying_uid', 'ticker',
               'planned_entry', 'input_reason', 'availability_semantics']
    panel = pd.read_csv(io.BytesIO(raw['opportunities']), usecols=columns, dtype=str)
    require(len(panel) == 15000 and panel.decision_id.is_unique and
            panel.signal_date.nunique() == 750 and panel.underlying_uid.nunique() == 377,
            'PUBLIC_ORIGINAL_POPULATION_CHANGED')
    require(panel[columns].notna().all().all(), 'PUBLIC_IDENTITY_FIELDS_MISSING')
    signals = pd.to_datetime(panel.signal_date, errors='raise')
    require(signals.eq(signals.dt.normalize()).all() and
            signals.between('2023-01-01', '2025-12-31').all(), 'PUBLIC_SIGNAL_CUTOFF')
    cal = calendar()
    locations = cal.sessions.get_indexer(signals)
    require((locations >= 0).all(), 'PUBLIC_SIGNAL_NON_SESSION')
    entries, exits = cal.sessions[locations + 1], cal.sessions[locations + 6]
    inherited_entry = pd.to_datetime(panel.planned_entry, utc=True).dt.tz_convert('America/New_York')
    require((entries.strftime('%Y-%m-%d') == inherited_entry.dt.strftime('%Y-%m-%d')).all(),
            'PUBLIC_INHERITED_ENTRY_DATE_CHANGED')
    panel['option_decision_date'] = entries.strftime('%Y-%m-%d')
    panel['planned_exit_date'] = exits.strftime('%Y-%m-%d')
    panel['cutoff_censored'] = panel.planned_exit_date.ge('2026-01-01')
    panel['signal_month'] = signals.dt.strftime('%Y-%m')

    source = pq.ParquetFile(io.BytesIO(raw['membership']))
    wanted = ['signal_date', 'ticker', 'cusip', 'moomoo_transport_code']
    require(set(wanted) <= set(source.schema_arrow.names), 'PUBLIC_MEMBERSHIP_SCHEMA')
    date_column = source.schema_arrow.names.index('signal_date')
    for index in range(source.num_row_groups):
        stats = source.metadata.row_group(index).column(date_column).statistics
        require(stats is not None and stats.has_min_max and
                pd.Timestamp(stats.max) < pd.Timestamp('2026-01-01'),
                'PUBLIC_MEMBERSHIP_PHYSICAL_CUTOFF_UNPROVEN')
    members = source.read(columns=wanted).to_pandas()
    members['signal_date'] = pd.to_datetime(members.signal_date).dt.strftime('%Y-%m-%d')
    require(members.signal_date.lt('2026-01-01').all() and
            not members.duplicated(['signal_date', 'ticker']).any() and
            not members.duplicated(['signal_date', 'cusip']).any(),
            'PUBLIC_MEMBERSHIP_AMBIGUOUS_OR_FUTURE')
    # Prefer the actual unique UID/date ticker. An absent dated UID does not
    # permit replacing the opportunity: retain its original ticker as candidate.
    uid_map = members.set_index(['signal_date', 'cusip'])
    ticker_map = members.set_index(['signal_date', 'ticker'])
    for side, date_field in [('entry', 'option_decision_date'), ('exit', 'planned_exit_date')]:
        uid_keys = pd.MultiIndex.from_arrays([panel[date_field], panel.underlying_uid])
        dated = uid_map.reindex(uid_keys).reset_index(drop=True)
        candidate = dated.ticker.where(dated.ticker.notna(), panel.ticker)
        ticker_keys = pd.MultiIndex.from_arrays([panel[date_field], candidate])
        candidate_ids = ticker_map.reindex(ticker_keys).cusip.reset_index(drop=True)
        verified = candidate_ids.eq(panel.underlying_uid) & dated.ticker.notna()
        status = pd.Series('UNKNOWN', index=panel.index)
        status.loc[candidate_ids.notna() & ~candidate_ids.eq(panel.underlying_uid)] = 'MISMATCH'
        status.loc[verified] = 'VERIFIED_DATED_HISTORICAL_MAPPING'
        panel[side + '_ticker'] = candidate
        panel[side + '_uid_status'] = status
        panel[side + '_dated_uid'] = candidate_ids
        panel[side + '_ticker_basis'] = verified.map({True: 'FROZEN_DATED_UID_MAPPING',
                                                     False: 'ORIGINAL_SIGNAL_TICKER_CANDIDATE_ONLY'})
    panel['date_match_semantics'] = 'PLANNED_SESSION_DATE_CANDIDATE_NOT_SOURCE_DATE_OR_PIT_CERTIFICATION'
    panel['option_identity_status'] = 'UNKNOWN'
    panel['signal_0945_availability_status'] = 'INHERITED_CLOSE_SIGNAL_NEXT_OPEN_HISTORICAL_CONTRACT'
    require(int(panel.cutoff_censored.sum()) == 80, 'PUBLIC_MATURITY_POPULATION_CHANGED')
    return panel, bindings, nine


def freeze_plan(session):
    """Freeze once before prices; resume validates bytes without reselection."""
    plan_path = session.output / 'plan.json'
    projection_path = session.output / 'identity_projection.parquet'
    prior = session.manifest.get('plan_freeze')
    if prior:
        require(prior.get('state') == 'FROZEN', 'PUBLIC_PLAN_FREEZE_INCOMPLETE_PRESERVE_FILES')
        _, bindings, _ = _identity_sources()
        require(bindings == prior['source_bindings'], 'PUBLIC_PLAN_SOURCE_BINDINGS_CHANGED')
        require(digest(plan_path.read_bytes()) == prior['plan_sha256'] and
                digest(projection_path.read_bytes()) == prior['identity_projection_sha256'],
                'PUBLIC_FROZEN_PLAN_BYTES_CHANGED')
        plan = json.loads(plan_path.read_bytes())
        require(plan['source_bindings'] == bindings and
                plan['identity_projection_sha256'] == prior['identity_projection_sha256'],
                'PUBLIC_PLAN_PROJECTION_BINDING_CHANGED')
        panel = pd.read_parquet(projection_path)
        require(len(panel) == 15000 and panel.decision_id.is_unique, 'PUBLIC_FROZEN_POPULATION_CHANGED')
        return plan, panel

    require(not session.offline, 'PUBLIC_OFFLINE_PLAN_MISSING')
    require(not plan_path.exists() and not projection_path.exists(), 'PUBLIC_UNBOUND_PLAN_FILES_PRESERVED')
    for item in session.manifest.get('requests', []):
        query = str(item.get('params', {}).get('q', '')).upper()
        structural_zero_rows = query.strip().rstrip(';').rstrip().endswith('LIMIT 0')
        sql_price = not structural_zero_rows and query.startswith('SELECT ') and 'OPTION_CHAIN' in query and any(
            token in query for token in ('BID', 'ASK', 'DELTA', 'GAMMA', 'THETA', 'VEGA', 'RHO', 'VOL', 'SELECT *'))
        url = str(item.get('url', '')).lower().split('?', 1)[0]
        file_price = url.endswith(('.parquet', '.parquet.gz', '.csv', '.csv.gz', '.zip')) and item.get('method') != 'HEAD'
        failed_http = item.get('http_status') is not None and not 200 <= item['http_status'] < 300
        require(failed_http or (not sql_price and not file_price), 'PUBLIC_PLAN_MUST_PRECEDE_PRICE_REQUESTS')
    panel, bindings, nine = load_identity_projection()
    lookup = panel.set_index('decision_id', drop=False)
    priority = [item['decision_id'] for item in nine]
    require(len(set(priority)) == 9 and set(priority) <= set(lookup.index), 'PUBLIC_NINE_OUTSIDE_POPULATION')
    for item in nine:
        row = lookup.loc[item['decision_id']]
        require(not bool(row.cutoff_censored) and row.underlying_uid == item['underlying_uid'] and
                row.ticker == item['underlying_symbol'] and row.signal_date == item['signal_date'],
                'PUBLIC_NINE_IDENTITY_CHANGED')
    mature = panel[~panel.cutoff_censored].copy()
    months = sorted(mature.signal_month.unique())
    require(len(months) == 36, 'PUBLIC_MATURE_MONTH_SET_CHANGED')
    mature['selection_hash'] = mature.decision_id.map(lambda value: digest((TEMPLATE + value).encode('utf-8')))
    allocations, by_month = [], {}
    for index, month in enumerate(months):
        quota = 240 // 36 + int(index < 240 % 36)
        candidates = mature[mature.signal_month.eq(month)].sort_values(['selection_hash', 'decision_id'])
        selected = candidates.head(quota).decision_id.tolist()
        by_month[month] = selected
        allocations.append({'month': month, 'quota': quota, 'available': len(candidates),
                            'selected': len(selected), 'unfilled': quota-len(selected)})
    monthly = [by_month[month][rank] for rank in range(max(map(len, by_month.values())))
               for month in months if rank < len(by_month[month])]
    selected_ids = list(dict.fromkeys(priority + monthly))
    require(len(monthly) <= 240 and len(selected_ids) <= 249, 'PUBLIC_PLAN_SIZE')
    panel['planned'] = panel.decision_id.isin(selected_ids)
    panel['selection_roles'] = panel.decision_id.map(lambda key: '|'.join(
        role for role, cohort in [('ORIGINAL_NINE_QUALIFICATION', priority), ('MONTH_BALANCED_240', monthly)]
        if key in cohort))
    panel['planning_status'] = panel.planned.map({True: 'PLANNED', False: 'NOT_SELECTED'})
    panel.loc[panel.cutoff_censored, 'planning_status'] = 'CUTOFF_CENSORED_NOT_REQUESTABLE'
    ordered_keys, key_index = [], {}
    # The selected_ids order keeps original nine first and then the unchanged
    # month-roundrobin 240. Shared code/date keys generate one public request.
    for decision_id in selected_ids:
        row = lookup.loc[decision_id]
        for side, date_field in [('entry', 'option_decision_date'), ('exit', 'planned_exit_date')]:
            ticker, day = str(row[side + '_ticker']), str(row[date_field])
            require(day < '2026-01-01', 'PUBLIC_REQUEST_KEY_CUTOFF')
            key = (ticker, day)
            reference = {'decision_id': decision_id, 'side': side,
                         'underlying_uid': str(row.underlying_uid), 'uid_status': str(row[side + '_uid_status'])}
            if key not in key_index:
                key_index[key] = len(ordered_keys)
                ordered_keys.append({'request_key_id': digest((ticker + '|' + day).encode('utf-8')),
                                     'ticker': ticker, 'date': day, 'opportunity_references': []})
            ordered_keys[key_index[key]]['opportunity_references'].append(reference)
    rules = {'identity': TEMPLATE, 'role': 'PUBLIC_OBSERVATION_ACQUISITION_ONLY_NOT_R1_ECONOMIC_SAMPLE',
             'cutoff_exclusive': '2026-01-01', 'entry_offset_sessions_from_signal': 1,
             'exit_offset_sessions_from_signal': 6, 'original_nine_priority': True,
             'monthly_limit': 240, 'month_basis': 'MATURE_SIGNAL_MONTH', 'month_count': 36,
             'base_quota': 6, 'extra_first_ascending_months': 24,
             'within_month_sort': ['SHA256_UTF8_TEMPLATE_PLUS_DECISION_ID_NO_SEPARATOR', 'decision_id'],
             'shortfall': 'LEAVE_UNUSED_NO_REALLOCATION_OR_REPLACEMENT',
             'nine_excluded_from_monthly_selection': False, 'merge': 'PRIORITY_NINE_THEN_MONTH_ROUNDROBIN_DEDUPLICATED',
             'query_keys': 'ENTRY_THEN_EXIT_PER_OPPORTUNITY_DEDUPLICATED_BY_TICKER_DATE',
             'unknown_uid': 'RETAIN_ORIGINAL_TICKER_AS_CANDIDATE_WITH_SEPARATE_STATUS',
             'no_outcome_price_or_exit_availability_selection': True}
    session.manifest['plan_freeze'] = {'state': 'PREPARING', 'source_bindings': bindings}
    session.save()
    temporary = projection_path.with_suffix('.parquet.partial')
    require(not temporary.exists(), 'PUBLIC_PARTIAL_PROJECTION_PRESERVED')
    panel.to_parquet(temporary, index=False)
    temporary.replace(projection_path)
    projection_hash = digest(projection_path.read_bytes())
    plan = {'research_identity': TEMPLATE, 'recorded_at_utc': utcnow(), 'rules': rules, 'source_bindings': bindings,
            'identity_projection_sha256': projection_hash, 'original_opportunities': len(panel),
            'mature_opportunities': len(mature), 'cutoff_censored_opportunities': int(panel.cutoff_censored.sum()),
            'original_nine': priority, 'monthly_selected': monthly, 'month_allocations': allocations,
            'selected_decision_ids': selected_ids, 'selected_count': len(selected_ids),
            'request_keys': ordered_keys, 'request_key_count': len(ordered_keys),
            'price_payloads_read_before_freeze': 0, 'economic_plan_count': 0}
    _write_json(plan_path, plan)
    session.manifest['plan_freeze'] = {'state': 'FROZEN', 'source_bindings': bindings,
        'plan_file': plan_path.name, 'plan_sha256': digest(plan_path.read_bytes()),
        'identity_projection_file': projection_path.name, 'identity_projection_sha256': projection_hash,
        'selected_count': len(selected_ids), 'request_key_count': len(ordered_keys),
        'price_payloads_read_before_freeze': 0}
    session.save()
    return plan, panel

def _sql_literal(value):
    require(isinstance(value, str) and len(value) <= 64 and not any(ord(c) < 32 for c in value),
            'PUBLIC_SQL_VALUE_INVALID')
    return "'" + value.replace("'", "''") + "'"


def _dolt_from(session):
    commit = session.manifest['sources']['DOLT']['commit']
    require(len(commit) == 32 and commit.isalnum(), 'PUBLIC_DOLT_COMMIT_INVALID')
    return ' FROM option_chain AS OF ' + _sql_literal(commit)


def _key_where(keys):
    return " WHERE date >= '2023-01-01' AND date < '2026-01-01' AND (" + ' OR '.join(
        '(date = ' + _sql_literal(k['date']) + ' AND act_symbol = ' + _sql_literal(k['ticker']) + ')'
        for k in keys) + ')'


def count_query(session, keys):
    require(0 < len(keys) <= 24 and all('2023-01-01' <= k['date'] < '2026-01-01' for k in keys),
            'PUBLIC_COUNT_KEYS_BOUNDARY')
    return ('SELECT date, act_symbol, COUNT(*) AS row_count' + _dolt_from(session) + _key_where(keys) +
            ' GROUP BY date, act_symbol ORDER BY date, act_symbol LIMIT 500;')


def page_query(session, key, after=None, *, page_size=500):
    require(page_size in (100,500), "PUBLIC_PAGE_SIZE_BOUNDARY")
    require('2023-01-01' <= key['date'] < '2026-01-01', 'PUBLIC_PAGE_KEY_CUTOFF')
    query = ('SELECT date, act_symbol, expiration, strike, call_put, bid, ask, vol, delta, gamma, theta, vega, rho' +
             _dolt_from(session) + _key_where([key]))
    if after is not None:
        from decimal import Decimal
        strike = str(Decimal(str(after[3])))
        require(Decimal(strike).is_finite(), 'PUBLIC_KEYSET_STRIKE')
        query += ' AND (date, act_symbol, expiration, strike, call_put) > (' + ', '.join(
            [_sql_literal(after[0]), _sql_literal(after[1]), _sql_literal(after[2]), strike, _sql_literal(after[4])]) + ')'
    return query + f' ORDER BY date, act_symbol, expiration, strike, call_put LIMIT {page_size};'


def _page_key(row):
    from decimal import Decimal
    return (str(row['date']), str(row['act_symbol']), str(row['expiration']), Decimal(str(row['strike'])), str(row['call_put']))


def acquire_dolt(session, plan):
    """Count fixed scopes then keyset pages; count equality proves completeness."""
    states = session.manifest.setdefault('dolt_keys', {})
    keys = plan['request_keys']
    for key in keys:
        states.setdefault(key['request_key_id'], dict(ticker=key['ticker'], date=key['date'],
            status='PLANNED_NOT_REQUESTED', pages=[], downloaded_rows=0, expected_rows=None))
    session.save()
    def budget():
        return sum(r['source'] == 'DOLT' for r in session.manifest['requests']) < 360
    def attempts_for(query):
        return [r for r in session.manifest['requests'] if r.get('source') == 'DOLT' and r.get('params', {}).get('q') == query]
    def timed_out(query):
        attempts = attempts_for(query)
        return bool(attempts and attempts[-1]['status'] == 'FAILED' and attempts[-1].get('exception_type') == 'ReadTimeout')
    # All scopes retain frozen order; no chain/expiry/right filtering is applied.
    batch_size = session.manifest['acquisition_policy'].get('count_key_batch', 24)
    require(batch_size in (8, 24) or (batch_size == 1 and session.manifest.get('stage') == 'contract-continuity'), 'PUBLIC_COUNT_BATCH_BOUNDARY')
    page_size = session.manifest['acquisition_policy'].get('page_size', 500)
    dependency_failure = None
    for start in range(0, len(keys), batch_size):
        batch = keys[start:start+batch_size]
        if all(states[k['request_key_id']]['expected_rows'] is not None for k in batch):
            continue
        if not budget():
            break
        query = count_query(session, batch)
        if timed_out(query):
            # Preserve the failed scope; another fixed scope is independent.
            continue
        try:
            body = session.sql(query)
            require(body['query_execution_status'] == 'Success', 'DOLT_COUNT_' + body['query_execution_status'])
            rows = body.get('rows')
            require(isinstance(rows, list) and len(rows) <= len(batch), 'DOLT_COUNT_ROWS_INVALID')
            expected = {(k['date'], k['ticker']): k for k in batch}
            counts = {}
            for row in rows:
                pair = (str(row['date']), str(row['act_symbol']))
                require(pair in expected and pair not in counts, 'DOLT_COUNT_SCOPE_OR_DUPLICATE')
                count = int(row['row_count'])
                require(count >= 0, 'DOLT_COUNT_NEGATIVE')
                counts[pair] = count
            for pair, key in expected.items():
                state = states[key['request_key_id']]
                state.update(expected_rows=counts.get(pair, 0), count_query_sha256=digest(query.encode()),
                             status='COMPLETE_EMPTY' if counts.get(pair, 0) == 0 else 'COUNTED_NOT_DOWNLOADED')
        except Exception as exc:
            for key in batch:
                states[key['request_key_id']].update(status='COUNT_ERROR', error=str(exc) if isinstance(exc, Invalid) else type(exc).__name__)
            session.save()
            if timed_out(query):
                continue
            # Permission, schema, range and global-budget failures stop the
            # dependency; only a proven per-query ReadTimeout is isolated.
            dependency_failure = str(exc) if isinstance(exc, Invalid) else type(exc).__name__
            break
        session.save()
    page_failure = False
    page_dependency_stop_reason = None
    for key in ([] if dependency_failure else keys):
        state = states[key['request_key_id']]
        if state['expected_rows'] in (None, 0) or state['status'] == 'COMPLETE':
            continue
        query = page_query(session, key, state.get('after'), page_size=page_size)
        attempts = attempts_for(query)
        if timed_out(query):
            permitted = session.manifest.get('bounded_latency_repair', {}).get('one_retry_request_ids', [])
            if len(attempts) != 1 or attempts[-1]['request_id'] not in permitted:
                continue
        while state['downloaded_rows'] < state['expected_rows']:
            if not budget():
                state['status'] = 'BUDGET_PARTIAL' if state['downloaded_rows'] else 'BUDGET_NOT_DOWNLOADED'
                break
            try:
                query = page_query(session, key, state.get('after'), page_size=page_size)
                body = session.sql(query)
                result_status = body['query_execution_status']
                require(result_status in {'Success', 'RowLimit'}, 'DOLT_PAGE_' + result_status)
                rows = body.get('rows')
                require(isinstance(rows, list) and len(rows) <= page_size, 'DOLT_PAGE_ROWS_INVALID')
                parsed = [_page_key(row) for row in rows]
                require(all(p[0] == key['date'] and p[1] == key['ticker'] for p in parsed), 'DOLT_PAGE_SCOPE')
                require(parsed == sorted(set(parsed)), 'DOLT_PAGE_KEY_ORDER_OR_DUPLICATE')
                if state.get('after') and parsed:
                    previous = _page_key(dict(zip(('date','act_symbol','expiration','strike','call_put'), state['after'])))
                    require(parsed[0] > previous, 'DOLT_KEYSET_DID_NOT_ADVANCE')
                require(rows, 'DOLT_EMPTY_BEFORE_EXPECTED_COUNT')
                request = next(r for r in reversed(session.manifest['requests']) if r.get('params', {}).get('q') == query)
                state['pages'].append(dict(file=request['file'], sha256=request['sha256'], rows=len(rows),
                    status=result_status, downloaded_at=request['requested_at_utc']))
                state['downloaded_rows'] += len(rows)
                require(state['downloaded_rows'] <= state['expected_rows'], 'DOLT_COUNT_OVERRUN')
                state['after'] = [str(item) for item in parsed[-1]]
                state['status'] = 'COMPLETE' if state['downloaded_rows'] == state['expected_rows'] else 'PARTIAL'
                state['completeness_basis'] = 'PINNED_COMMIT_COUNT_EQUALS_KEYSET_ROWS' if state['status'] == 'COMPLETE' else None
            except Exception as exc:
                state.update(status='PAGE_ERROR_PARTIAL' if state['downloaded_rows'] else 'PAGE_ERROR',
                    error=str(exc) if isinstance(exc, Invalid) else type(exc).__name__)
                page_failure = not timed_out(query)
                if page_failure:
                    page_dependency_stop_reason = str(exc) if isinstance(exc, Invalid) else type(exc).__name__
                break
            finally:
                session.save()
        if page_failure:
            break
    session.manifest['source_status']['DOLT'] = dict(
        status='BOUNDED_ACQUISITION_FINISHED',
        dependency_stop_reason=dependency_failure, page_dependency_stop_reason=page_dependency_stop_reason,
        keys=len(states), complete=sum(s['status'] == 'COMPLETE' for s in states.values()),
        complete_empty=sum(s['status'] == 'COMPLETE_EMPTY' for s in states.values()),
        downloaded_rows=sum(s['downloaded_rows'] for s in states.values()))
    session.save()


def inspect_parquet(path, *, year=None):
    """Inspect magic/footer/stats before reading any market record batch."""
    require(path.stat().st_size >= 12, 'PUBLIC_TRUNCATED_PARQUET')
    with path.open('rb') as stream:
        prefix = stream.read(128)
        require(not prefix.startswith(b'version https://git-lfs.github.com/spec/v1'), 'PUBLIC_LFS_POINTER')
        require(prefix[:4] == b'PAR1', 'PUBLIC_NOT_PARQUET_MAGIC')
        stream.seek(-8, 2)
        require(stream.read(8)[-4:] == b'PAR1', 'PUBLIC_TRUNCATED_PARQUET')
    source = pq.ParquetFile(path)
    require('date' in source.schema_arrow.names, 'PUBLIC_PARQUET_DATE_MISSING')
    column = source.schema_arrow.names.index('date')
    groups = []
    for index in range(source.num_row_groups):
        stats = source.metadata.row_group(index).column(column).statistics
        require(stats is not None and stats.has_min_max and stats.null_count == 0, 'PUBLIC_PARQUET_DATE_STATS_UNKNOWN')
        lo, hi = pd.Timestamp(stats.min).date().isoformat(), pd.Timestamp(stats.max).date().isoformat()
        require('2023-01-01' <= lo <= hi < '2026-01-01', 'PUBLIC_PARQUET_DATE_SCOPE')
        if year:
            require(lo.startswith(str(year)) and hi.startswith(str(year)), 'PUBLIC_ANNUAL_FILE_SCOPE')
        groups.append(dict(row_group=index, rows=source.metadata.row_group(index).num_rows, date_min=lo, date_max=hi))
    return source, dict(rows=source.metadata.num_rows, columns=source.schema_arrow.names, row_groups=groups)


def acquire_etf(session):
    if 'ETF_2024' in session.manifest['source_status']:
        return
    repo = REPOS[1]
    binding = session.manifest['sources'][repo]
    tree = json.loads((session.cache / binding['tree_file']).read_bytes())
    match = next(item for item in tree['tree'] if item['path'] == 'spy/options_2024.parquet')
    url = 'https://raw.githubusercontent.com/' + repo + '/' + binding['commit'] + '/' + match['path']
    status = dict(repository=repo, commit=binding['commit'], path=match['path'], git_blob_sha=match['sha'],
                  metadata_size=match['size'], role='INDEPENDENT_ETF_INGESTION_CHECK')
    session.manifest['etf_file_binding'] = status.copy()
    session.save()
    try:
        head, _ = session.get('ETF_2024', url, method='HEAD')
        require(head['http_status'] == 200, 'ETF_HEAD_HTTP_' + str(head['http_status']))
        record, path = session.get('ETF_2024', url, maximum=match['size'])
        require(record['http_status'] == 200 and record['bytes'] == match['size'], 'ETF_DOWNLOAD_SIZE_OR_HTTP')
        raw = path.read_bytes()
        require(hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == match['sha'], 'ETF_GIT_BLOB_MISMATCH')
        _, footer = inspect_parquet(path, year=2024)
        status.update(status='FOOTER_VERIFIED_READY_FOR_BATCH_READ', file=record['file'], sha256=record['sha256'],
                      downloaded_at=record['requested_at_utc'], bytes=record['bytes'], footer=footer)
    except Exception as exc:
        status.update(status='ERROR', reason=str(exc) if isinstance(exc, Invalid) else type(exc).__name__)
    session.manifest['source_status']['ETF_2024'] = status
    session.save()


def acquire_stock_file_check(session, panel):
    if 'PUBLIC_STOCK_FILES' in session.manifest['source_status']:
        return
    source = session.manifest['sources'][REPOS[0]]
    url = 'https://raw.githubusercontent.com/' + REPOS[0] + '/' + source['commit'] + '/README.md'
    record, path = session.get('SOURCE_DOCS', url)
    text = path.read_text(encoding='utf-8')
    import re
    # Read the actual pinned README's Available Tickers fenced list only.
    section = text.split('## Available Tickers', 1)[1].split('## Data Format', 1)[0]
    block = section.split('```')[1]
    published = set(block.split())
    require(len(published) == 104 and all(re.fullmatch(r'[a-z]{1,5}(?:\.b)?', v) for v in published),
            'PUBLIC_PUBLISHED_TICKER_SCHEMA_CHANGED')
    candidates = sorted(set(panel.ticker.str.lower()) & published)[:3]
    require(len(candidates) == 3, 'PUBLIC_STOCK_PUBLISHED_INTERSECTION_UNPROVEN')
    status = dict(candidates=candidates, rule='LEXICAL_FIRST_THREE_PUBLISHED_AND_ORIGINAL_INTERSECTION',
                  source_commit=source['commit'], attempts=[], status='PLANNED')
    session.manifest['stock_file_plan'] = status.copy()
    session.save()
    for ticker in candidates:
        url = 'https://static.philippdubach.com/data/options/' + ticker + '/options.parquet'
        try:
            head, _ = session.get('PUBLIC_STOCK_FILES', url, method='HEAD')
            attempt = dict(ticker=ticker, http_status=head['http_status'], content_length=head.get('content_length'),
                           content_type=head.get('content_type'))
            status['attempts'].append(attempt)
            require(head['http_status'] == 200, 'PUBLIC_STOCK_FILE_HEAD_HTTP_' + str(head['http_status']))
            require(head.get('content_length') is not None, 'PUBLIC_STOCK_FILE_SIZE_UNKNOWN')
            # The repository declares 2008-2025 mixed history. This task reads
            # only 2023-2025; no full-file download absent physical row selection.
            status['status'] = 'REMOTE_PRESENT_MIXED_HISTORY_RANGE_READER_REQUIRED'
            status['remaining'] = 'FOOTER_RANGE_AND_PRE2026_2023PLUS_ROW_GROUP_VERIFICATION'
            break
        except Exception as exc:
            status.update(status='HOST_PATH_STOPPED_AFTER_FIRST_FAILURE',
                          reason=str(exc) if isinstance(exc, Invalid) else type(exc).__name__)
            break
    session.manifest['source_status']['PUBLIC_STOCK_FILES'] = status
    session.save()

from decimal import Decimal, InvalidOperation
import hashlib
import json
import math

import pandas as pd

from .contracts import Invalid, calendar, require


def _obs_absent(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _obs_text(value):
    return None if _obs_absent(value) else str(value).strip()


def _obs_decimal(value):
    """Canonical exact decimal text, without context-sensitive rounding."""
    if _obs_absent(value):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    result = format(number, 'f')
    if '.' in result:
        result = result.rstrip('0').rstrip('.')
    return '0' if number.is_zero() else result


def _obs_number(value, field, reasons, *, required=False):
    # Do not equate a supplied NaN/Infinity with an absent cell. A DataFrame that
    # already coerced None to NaN has lost that distinction before this reader.
    if value is None or value is pd.NA or value is pd.NaT or (
            isinstance(value, str) and not value.strip()):
        if required:
            reasons.append('MISSING_' + field)
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        reasons.append('INVALID_NUMERIC_' + field)
        return None
    if not number.is_finite():
        reasons.append('NON_FINITE_' + field)
        return None
    result = float(number)
    if not math.isfinite(result):
        reasons.append('NON_FINITE_' + field)
        return None
    return result


def normalize_observations(frame, source, source_file_id, downloaded_at):
    """Retain one batch of 2023-2025 daily observations, including bad rows.

    Only an invalid/missing/out-of-scope observation date rejects the batch.
    Other data defects become quality_reasons (a JSON array), never row filters.
    observation_key has source scope, ignores source_file_id, and is null when
    neither a source contract nor a complete composite identity is available.
    Null-key rows must not be collapsed by a downstream deduplication writer.
    """
    require(isinstance(frame, pd.DataFrame), 'PUBLIC_OBSERVATIONS_FRAME_REQUIRED')
    require(frame.columns.is_unique, 'PUBLIC_DUPLICATE_INPUT_COLUMNS')
    require(all(isinstance(name, str) for name in frame.columns),
            'PUBLIC_INPUT_COLUMNS_MUST_BE_STRINGS')
    require('date' in frame.columns, 'PUBLIC_OBSERVATION_DATE_MISSING')
    require(bool(_obs_text(source)) and bool(_obs_text(source_file_id)) and
            bool(_obs_text(downloaded_at)), 'PUBLIC_OBSERVATION_PROVENANCE_MISSING')

    # Validate every observation date before normalization, with no cutoff filter.
    dates = []
    for value in frame['date']:
        try:
            require(not _obs_absent(value), 'PUBLIC_OBSERVATION_DATE_INVALID')
            stamp = pd.Timestamp(value)
            require(not pd.isna(stamp), 'PUBLIC_OBSERVATION_DATE_INVALID')
            day = stamp.date().isoformat()
            require('2023-01-01' <= day < '2026-01-01',
                    'PUBLIC_OBSERVATION_DATE_OUTSIDE_2023_2025')
        except Invalid:
            raise
        except (TypeError, ValueError, OverflowError) as exc:
            raise Invalid('PUBLIC_OBSERVATION_DATE_INVALID') from exc
        dates.append(day)

    columns = {name.casefold(): name for name in frame.columns}
    require(len(columns) == len(frame.columns), 'PUBLIC_CASE_AMBIGUOUS_INPUT_COLUMNS')

    def value_of(row, *names):
        for name in names:
            if name.casefold() in columns:
                return row[columns[name.casefold()]]
        return None

    sessions = set(calendar().sessions.strftime('%Y-%m-%d'))
    metadata_columns = [
        'source', 'source_file_id', 'downloaded_at', 'source_date',
        'observation_date', 'normalized_symbol', 'source_contract_id',
        'normalized_expiration', 'normalized_strike', 'normalized_right',
        'contract_identity', 'contract_identity_kind', 'observation_key',
        'observation_bid', 'observation_ask', 'observation_bid_size',
        'observation_ask_size', 'observation_volume',
        'observation_implied_volatility', 'vol_raw', 'vol_semantics',
        'snapshot_delta', 'snapshot_gamma', 'snapshot_vega', 'snapshot_theta',
        'snapshot_rho', 'greeks_semantics', 'delta_qualification',
        'quote_timestamp', 'available_at', 'historical_available_at',
        'multiplier', 'deliverable', 'size_unit', 'underlying_uid',
        'historical_uid_status', 'observation_semantics', 'quality_status',
        'quality_reasons',
    ]
    require(not (set(metadata_columns) & set(frame.columns)),
            'PUBLIC_RESERVED_NORMALIZED_COLUMN_COLLISION')
    records = []
    for row, day in zip(frame.to_dict('records'), dates):
        reasons = []
        symbol = _obs_text(value_of(row, 'act_symbol', 'symbol'))
        symbol = symbol.upper() if symbol else None
        if symbol is None:
            reasons.append('MISSING_SYMBOL')
        contract = _obs_text(value_of(row, 'contract_id', 'contractSymbol'))
        right_raw = _obs_text(value_of(row, 'call_put', 'type', 'option_type'))
        right = {'c': 'C', 'call': 'C', 'p': 'P', 'put': 'P'}.get(
            right_raw.casefold() if right_raw else '')
        if right is None:
            reasons.append('MISSING_RIGHT' if right_raw is None else 'UNKNOWN_RIGHT')
        strike_raw = value_of(row, 'strike')
        strike = _obs_decimal(strike_raw)
        if strike is None:
            _obs_number(strike_raw, 'STRIKE', reasons, required=True)
        elif Decimal(strike) < 0:
            reasons.append('NEGATIVE_STRIKE')
        elif Decimal(strike) == 0:
            reasons.append('ZERO_STRIKE')

        expiry = None
        expiry_raw = value_of(row, 'expiration', 'expiry')
        if _obs_absent(expiry_raw):
            reasons.append('MISSING_EXPIRATION')
        else:
            try:
                expiry_stamp = pd.Timestamp(expiry_raw)
                if pd.isna(expiry_stamp):
                    raise ValueError('NaT')
                expiry = expiry_stamp.date().isoformat()
            except (TypeError, ValueError, OverflowError):
                reasons.append('INVALID_EXPIRATION')
        if expiry is not None and expiry < day:
            reasons.append('EXPIRATION_BEFORE_OBSERVATION_DATE')
        if day not in sessions:
            reasons.append('NON_TRADING_DAY')

        bid = _obs_number(value_of(row, 'bid'), 'BID', reasons, required=True)
        ask = _obs_number(value_of(row, 'ask'), 'ASK', reasons, required=True)
        for name, price in [('BID', bid), ('ASK', ask)]:
            if price is not None and price < 0:
                reasons.append('NEGATIVE_' + name)
            if price == 0:
                reasons.append('ZERO_' + name)
        if bid is not None and ask is not None and bid > ask:
            reasons.append('BID_GREATER_THAN_ASK')
        sizes = {}
        for side in ('bid', 'ask'):
            size = _obs_number(value_of(row, side + '_size', side + 'Size'),
                               side.upper() + '_SIZE', reasons)
            if size is not None and size < 0:
                reasons.append('NEGATIVE_' + side.upper() + '_SIZE')
            sizes[side] = size
        generic_size = _obs_number(value_of(row, 'size'), 'SIZE', reasons)
        if generic_size is not None and generic_size < 0:
            reasons.append('NEGATIVE_SIZE')
        volume = _obs_number(value_of(row, 'volume', 'trade_volume'),
                             'VOLUME', reasons)
        if volume is not None and volume < 0:
            reasons.append('NEGATIVE_VOLUME')
        iv = _obs_number(value_of(row, 'implied_volatility', 'impliedVolatility'),
                         'IMPLIED_VOLATILITY', reasons)
        if iv is not None and iv < 0:
            reasons.append('NEGATIVE_IMPLIED_VOLATILITY')
        greeks = {name: _obs_number(value_of(row, name), name.upper(), reasons)
                  for name in ('delta', 'gamma', 'vega', 'theta', 'rho')}

        identity_kind = 'SOURCE_CONTRACT_ID' if contract else 'OBS_COMPOSITE'
        identity = contract
        key = None
        if contract is None and symbol is not None and expiry and strike and right:
            identity = 'OBS_COMPOSITE:' + json.dumps(
                [symbol, expiry, strike, right], separators=(',', ':'),
                ensure_ascii=True)
        if symbol is not None and identity is not None:
            components = [str(source), symbol, identity_kind, identity, day]
            key = hashlib.sha256(json.dumps(components, separators=(',', ':'),
                                           ensure_ascii=True).encode('utf-8')).hexdigest()
        else:
            reasons.append('OBSERVATION_KEY_NOT_IDENTIFIABLE')
        record = dict(
            source=str(source), source_file_id=str(source_file_id),
            downloaded_at=str(downloaded_at), source_date=str(row['date']),
            observation_date=day, normalized_symbol=symbol,
            source_contract_id=contract, normalized_expiration=expiry,
            normalized_strike=strike, normalized_right=right,
            contract_identity=identity, contract_identity_kind=identity_kind,
            observation_key=key, observation_bid=bid, observation_ask=ask,
            observation_bid_size=sizes['bid'], observation_ask_size=sizes['ask'],
            observation_volume=volume, observation_implied_volatility=iv,
            vol_raw=value_of(row, 'vol'), vol_semantics='UNKNOWN',
            **{'snapshot_' + name: number for name, number in greeks.items()},
            greeks_semantics='SNAPSHOT_DERIVED_NOT_QUALIFIED',
            delta_qualification='NOT_QUALIFIED_HISTORICAL_DECISION_DELTA',
            quote_timestamp=None, available_at=None, historical_available_at=None,
            multiplier=None, deliverable=None, size_unit='UNKNOWN',
            underlying_uid=None, historical_uid_status='UNKNOWN',
            observation_semantics='PUBLIC_DAILY_OBSERVATION_NOT_EXECUTABLE_QUOTE',
            quality_status=('OBSERVATION_HAS_QUALITY_FLAGS' if reasons else
                            'OBSERVATION_FIELDS_PRESENT_NOT_QUALIFIED'),
            quality_reasons=json.dumps(list(dict.fromkeys(reasons)),
                                       separators=(',', ':')),
        )
        records.append(record)
    result = frame.copy(deep=True)
    normalized = pd.DataFrame.from_records(records, columns=metadata_columns)
    for name in metadata_columns:
        # Positional assignment also preserves duplicate/non-default input index.
        result[name] = normalized[name].to_numpy()
    return result

def _file_digest(path):
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def public_source_payload(session):
    """The already selected public commits and actual tree/blob evidence."""
    result = {'DOLT': {'commit': session.manifest['sources']['DOLT']['commit']}}
    for repo in REPOS:
        source = session.manifest['sources'][repo]
        result[repo] = dict(commit=source['commit'], tree_sha256=_file_digest(session.cache / source['tree_file']))
    result['etf_file_binding'] = session.manifest['etf_file_binding']
    return result


def validate_public_sources(session):
    lock = session.manifest.get('public_source_lock')
    require(lock is not None, 'PUBLIC_SOURCE_LOCK_REQUIRED')
    payload = public_source_payload(session)
    require(digest(json.dumps(payload, sort_keys=True).encode()) == lock['sha256'], 'PUBLIC_SOURCE_VERSION_CHANGED')
    commit = payload['DOLT']['commit']
    for request in session.manifest['requests']:
        query = request.get('params', {}).get('q', '')
        if 'option_chain AS OF' in query:
            require("option_chain AS OF '" + commit + "'" in query, 'PUBLIC_COUNT_PAGE_VERSION_MIX')


def _raw_batches(session):
    for state in session.manifest.get('dolt_keys', {}).values():
        for page in state['pages']:
            path = session.cache / page['file']
            require(_file_digest(path) == page['sha256'], 'PUBLIC_RAW_PAGE_CHANGED')
            body = json.loads(path.read_bytes())
            yield 'DOLT', page['file'], page['downloaded_at'], 0, pd.DataFrame(body['rows'], dtype=object)
    etf = session.manifest['source_status'].get('ETF_2024', {})
    if etf.get('status') in {'FOOTER_VERIFIED_READY_FOR_BATCH_READ', 'NORMALIZED_AND_REREAD'}:
        path = session.cache / etf['file']
        require(_file_digest(path) == etf['sha256'], 'PUBLIC_ETF_RAW_CHANGED')
        parquet, footer = inspect_parquet(path, year=2024)
        require(footer == etf['footer'], 'PUBLIC_ETF_FOOTER_CHANGED')
        for index, batch in enumerate(parquet.iter_batches(batch_size=25000)):
            yield 'ETF_2024', etf['file'], etf['downloaded_at'], index, batch.to_pandas()


def normalize_cache(session):
    """One flat observation schema; retain raw provenance and conflicting rows."""
    state = session.manifest.setdefault('normalization', dict(parts=[], status='PENDING', raw_rows=0,
        normalized_rows=0, exact_duplicate_rows=0, conflict_keys=0, schema_version=1))
    inventory = [(p['file'], p['sha256']) for s in session.manifest.get('dolt_keys', {}).values() for p in s['pages']]
    etf = session.manifest['source_status'].get('ETF_2024', {})
    if etf.get('file'):
        inventory.append((etf['file'], etf['sha256']))
    inventory_hash = digest(json.dumps(inventory, sort_keys=True).encode())
    if state['status'] == 'COMPLETE' and state.get('input_inventory_sha256') == inventory_hash:
        return
    require(not session.offline, 'PUBLIC_OFFLINE_NORMALIZATION_INCOMPLETE')
    folder = session.cache / 'normalized'
    folder.mkdir(exist_ok=True)
    # SHA256 indices avoid holding the full file in memory. Metadata and file
    # ids are excluded from exact-row equality; source remains part of scope.
    seen, conflict_keys = {}, set()
    existing = {p['part_id']: p for p in state['parts']}
    raw_count = output_count = duplicate_count = 0
    from collections import Counter
    by_source = {}
    for source, raw_file, downloaded_at, batch_index, frame in _raw_batches(session):
        normalized = normalize_observations(frame, source, raw_file, downloaded_at)
        keep = []
        for index, (raw, key) in enumerate(zip(frame.to_dict('records'), normalized.observation_key)):
            fingerprint = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(',', ':'), default=str,
                                                   ensure_ascii=True).encode()).digest()
            identity = bytes.fromhex(key) if isinstance(key, str) else hashlib.sha256(
                (source + raw_file + str(batch_index) + str(index)).encode()).digest()
            previous = seen.get(identity)
            if previous is None:
                seen[identity] = {fingerprint}
                keep.append(index)
            elif fingerprint in previous:
                duplicate_count += 1
            else:
                previous.add(fingerprint)
                conflict_keys.add(key)
                keep.append(index)
        output = normalized.iloc[keep].copy()
        raw_count += len(frame)
        output_count += len(output)
        summary = by_source.setdefault(source, dict(raw_rows=0, normalized_rows=0, exact_duplicate_rows=0))
        summary['raw_rows'] += len(frame)
        summary['normalized_rows'] += len(output)
        summary['exact_duplicate_rows'] += len(frame)-len(output)
        part_id = digest((source + '|' + raw_file + '|' + str(batch_index)).encode())
        destination = folder / (part_id + '.parquet')
        if part_id in existing:
            old = existing[part_id]
            require(_file_digest(destination) == old['sha256'] and len(output) == old['rows'], 'PUBLIC_NORMALIZED_RESUME_CHANGED')
        else:
            require(not destination.exists(), 'PUBLIC_UNJOURNALED_NORMALIZED_FILE_PRESERVED')
            used = sum(p.stat().st_size for p in session.cache.rglob('*') if p.is_file())
            require(used + int(output.memory_usage(deep=True).sum())*2 < session.manifest['cache_limit_bytes'],
                    'PUBLIC_NORMALIZED_CACHE_BUDGET')
            temporary = destination.with_suffix('.partial')
            require(not temporary.exists(), 'PUBLIC_NORMALIZED_PARTIAL_PRESERVED')
            output.to_parquet(temporary, index=False)
            temporary.replace(destination)
            state['parts'].append(dict(part_id=part_id, source=source, raw_file=raw_file, batch_index=batch_index,
                file=destination.relative_to(session.cache).as_posix(), sha256=_file_digest(destination), rows=len(output)))
        state.update(status='PARTIAL', raw_rows=raw_count, normalized_rows=output_count,
                     exact_duplicate_rows=duplicate_count, conflict_keys=len(conflict_keys), by_source=by_source)
        session.save()
    state.update(status='COMPLETE', input_inventory_sha256=inventory_hash,
                 conflict_key_values=sorted(k for k in conflict_keys if k), finished_at_utc=utcnow())
    session.save()


def reread_and_cover(session, panel, plan):
    """Read installed flat Parquet parts, aggregate observations, join 15k ids."""
    from collections import Counter, defaultdict
    sources, monthly, pairs = {}, {}, defaultdict(lambda: dict(rows=0, calls=0, valid_bid_ask=0))
    total = 0
    samples = []
    for part in session.manifest['normalization']['parts']:
        path = session.cache / part['file']
        require(_file_digest(path) == part['sha256'], 'PUBLIC_NORMALIZED_CACHE_CHANGED')
        source = part['source']
        summary = sources.setdefault(source, dict(rows=0, observation_keys=set(), contracts=set(), symbols=set(),
            dates=set(), quality=Counter(), missing=Counter(), bid_min=None, bid_max=None, ask_min=None, ask_max=None))
        # A part is <=25,000 ETF or <=500 Dolt records; read actual output.
        frame = pd.read_parquet(path)
        require(len(frame) == part['rows'] and frame.observation_date.between('2023-01-01','2025-12-31').all(),
                'PUBLIC_NORMALIZED_ROW_OR_DATE_CHANGED')
        require(frame.observation_semantics.eq('PUBLIC_DAILY_OBSERVATION_NOT_EXECUTABLE_QUOTE').all(), 'PUBLIC_OBSERVATION_LEVEL_CHANGED')
        total += len(frame)
        summary['rows'] += len(frame)
        summary['observation_keys'].update(frame.observation_key.dropna())
        summary['contracts'].update(frame.contract_identity.dropna())
        summary['symbols'].update(frame.normalized_symbol.dropna())
        summary['dates'].update(frame.observation_date)
        for value in frame.quality_reasons:
            summary['quality'].update(json.loads(value))
        for field in ['quote_timestamp', 'available_at', 'historical_available_at', 'multiplier', 'deliverable',
                      'underlying_uid', 'observation_bid', 'observation_ask', 'observation_bid_size', 'observation_ask_size',
                      'observation_implied_volatility']:
            summary['missing'][field] += int(frame[field].isna().sum())
        for price in ('bid','ask'):
            values = frame['observation_'+price].dropna()
            if len(values):
                lower, upper = float(values.min()), float(values.max())
                summary[price+'_min'] = lower if summary[price+'_min'] is None else min(summary[price+'_min'], lower)
                summary[price+'_max'] = upper if summary[price+'_max'] is None else max(summary[price+'_max'], upper)
        for month, group in frame.groupby(frame.observation_date.str[:7], sort=True):
            item = monthly.setdefault((source,month), dict(rows=0, dates=set(), symbols=set(), quality_rows=0))
            item['rows'] += len(group)
            item['dates'].update(group.observation_date)
            item['symbols'].update(group.normalized_symbol.dropna())
            item['quality_rows'] += int(group.quality_reasons.ne('[]').sum())
        if source == 'DOLT':
            for (symbol, day), group in frame.groupby(['normalized_symbol','observation_date']):
                item = pairs[(symbol,day)]
                item['rows'] += len(group)
                item['calls'] += int(group.normalized_right.eq('C').sum())
                item['valid_bid_ask'] += int((group.observation_bid.notna() & group.observation_ask.notna() &
                    group.observation_bid.ge(0) & group.observation_ask.ge(group.observation_bid)).sum())
        # At most 10 rows per source; never a full presentation CSV.
        n = sum(row['source'] == source for row in samples)
        if n < 10:
            sample_fields = ['source','source_file_id','observation_date','normalized_symbol','normalized_expiration',
                'normalized_strike','normalized_right','observation_bid','observation_ask','observation_bid_size',
                'observation_ask_size','vol_raw','vol_semantics','size_unit','quote_timestamp','quality_reasons']
            samples.extend(frame[sample_fields].head(10-n).to_dict('records'))
    require(total == session.manifest['normalization']['normalized_rows'], 'PUBLIC_REREAD_TOTAL_MISMATCH')
    quality = []
    for source, summary in sources.items():
        for kind in ('observation_keys','contracts','symbols','dates'):
            values = summary[kind]
            if kind == 'dates':
                summary['date_min'], summary['date_max'] = min(values), max(values)
            summary[kind] = len(values)
        for category in ('quality','missing'):
            for reason, count in sorted(summary[category].items()):
                quality.append(dict(source=source, category=category, reason=reason, rows=count))
            summary[category] = dict(summary[category])
    monthly_rows = [dict(source=source, month=month, rows=s['rows'], distinct_dates=len(s['dates']),
        distinct_symbols=len(s['symbols']), flagged_rows=s['quality_rows']) for (source,month), s in sorted(monthly.items())]
    coverage = panel.copy()
    states = {(s['ticker'],s['date']):s for s in session.manifest.get('dolt_keys',{}).values()}
    for side, day_field in [('entry','option_decision_date'),('exit','planned_exit_date')]:
        records = []
        for row in coverage.itertuples(index=False):
            pair = (getattr(row,side+'_ticker'),getattr(row,day_field))
            state = states.get(pair)
            counts = pairs.get(pair, dict(rows=0,calls=0,valid_bid_ask=0))
            records.append(dict(query_status=state['status'] if state else 'NOT_REQUESTED',
                requested=bool(state and state['status'] != 'PLANNED_NOT_REQUESTED'),
                range_complete=bool(state and state['status'] in {'COMPLETE','COMPLETE_EMPTY'}),
                source_rows=counts['rows'], call_rows=counts['calls'], bid_ask_rows=counts['valid_bid_ask'],
                candidate_date_observation_present=bool(counts['rows']),
                source_date_semantics='UNKNOWN', exact_0945_eligible=False))
        for field in records[0]:
            coverage[side+'_'+field] = [r[field] for r in records]
    coverage['both_candidate_dates_present'] = (coverage.entry_candidate_date_observation_present &
                                                coverage.exit_candidate_date_observation_present)
    coverage['both_dated_uid_verified'] = (coverage.entry_uid_status.eq('VERIFIED_DATED_HISTORICAL_MAPPING') &
                                           coverage.exit_uid_status.eq('VERIFIED_DATED_HISTORICAL_MAPPING'))
    coverage['economic_pair'] = False
    coverage.to_parquet(session.output / 'opportunity_coverage.parquet', index=False)
    pd.DataFrame(quality).to_csv(session.output / 'quality_counts.csv', index=False)
    pd.DataFrame(monthly_rows).to_csv(session.output / 'monthly_observation_coverage.csv', index=False)
    pd.DataFrame(samples[:20]).to_csv(session.output / 'sample_20_rows.csv', index=False)
    result = dict(population_opportunities=len(coverage), population_signal_days=coverage.signal_date.nunique(),
        population_uids=coverage.underlying_uid.nunique(), planned_opportunities=int(coverage.planned.sum()),
        requested_entry_opportunities=int(coverage.entry_requested.sum()), requested_exit_opportunities=int(coverage.exit_requested.sum()),
        entry_candidate_present=int(coverage.entry_candidate_date_observation_present.sum()),
        exit_candidate_present=int(coverage.exit_candidate_date_observation_present.sum()),
        both_candidate_present=int(coverage.both_candidate_dates_present.sum()),
        both_candidate_and_dated_uid_verified=int((coverage.both_candidate_dates_present & coverage.both_dated_uid_verified).sum()),
        candidate_decision_days=int(coverage.loc[coverage.both_candidate_dates_present,'option_decision_date'].nunique()),
        candidate_uids=int(coverage.loc[coverage.entry_candidate_date_observation_present | coverage.exit_candidate_date_observation_present,'underlying_uid'].nunique()),
        exact_0945_eligible=0, economic_pairs=0)
    session.manifest['observations'] = sources
    session.manifest['coverage'] = result
    session.manifest['reread_rows'] = total
    for name in ('opportunity_coverage.parquet','quality_counts.csv','monthly_observation_coverage.csv','sample_20_rows.csv'):
        session.manifest.setdefault('artifact_sha256',{})[name] = _file_digest(session.output/name)
    if 'ETF_2024' in sources:
        session.manifest['source_status']['ETF_2024']['status'] = 'NORMALIZED_AND_REREAD'
    session.save()
    return total


def run_public_history(output, *, offline=False):
    require(output is not None, 'PUBLIC_OUTPUT_REQUIRED')
    session = PublicSession(output, offline=offline)
    invocation = dict(started_at_utc=utcnow(), offline=offline, http_before=len(session.manifest['requests']),
        module_path=str(Path(__file__).resolve()), module_sha256=_file_digest(Path(__file__)),
        cli_path=str(Path(__file__).with_name('cli.py').resolve()), cli_sha256=_file_digest(Path(__file__).with_name('cli.py')),
        canonical_python=__import__('sys').executable, evaluate_calls=0, status='RUNNING')
    session.manifest['invocation_history'].append(invocation)
    session.save()
    try:
        validate_public_sources(session)
        plan, panel = freeze_plan(session)
        require('acquisition_policy' in session.manifest and 'DOLT' in session.manifest['sources'], 'PUBLIC_SOURCE_PLAN_NOT_BOUND')
        if not offline:
            # Completed scopes and objects are cache hits, never repeated HTTP.
            acquire_dolt(session, plan)
            acquire_stock_file_check(session, panel)
            acquire_etf(session)
        normalize_cache(session)
        rows = reread_and_cover(session, panel, plan)
        require(rows > 0, 'PUBLIC_NO_REAL_OBSERVATIONS')
        invocation.update(status='COMPLETE', normalized_rows=rows, required_stage_success=True)
    except Exception as exc:
        invocation.update(status='FAILED', required_stage_success=False,
            reason=str(exc) if isinstance(exc, Invalid) else type(exc).__name__)
        raise
    finally:
        invocation.update(finished_at_utc=utcnow(), http_after=len(session.manifest['requests']),
                          actual_http=len(session.manifest['requests'])-invocation['http_before'])
        session.manifest['public_http_requests'] = len(session.manifest['requests'])
        session.manifest['research_cumulative_http'] = 12 + len(session.manifest['requests'])
        session.manifest['cache_bytes'] = sum(p.stat().st_size for p in session.cache.rglob('*') if p.is_file())
        session.save()
        session.http.close()
    return dict(required_stage_success=True, data_status='REAL_PUBLIC_OBSERVATIONS_NORMALIZED_AND_REREAD',
        economic_status='NOT_EVALUATED', evaluate_calls=0, economic_pairs=0,
        planned_acquisition_opportunities=plan['selected_count'], raw_observation_rows=session.manifest['normalization']['raw_rows'],
        normalized_rows=rows, public_http_requests=len(session.manifest['requests']), actual_http_this_invocation=invocation['actual_http'],
        coverage=session.manifest['coverage'], output=str(session.output))
