"""One user command: acquire current inputs, then run the frozen A2 predictor.

Provider snapshots stay separate. Incomplete inputs never become today's Top20.
This is a presentation/acquisition adapter, not a replacement strategy runner.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timedelta, timezone
import importlib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from zoneinfo import ZoneInfo


def emit(message):
    print(json.dumps({'event': 'progress', 'message': message}, ensure_ascii=False), flush=True)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    os.replace(temporary, path)


@contextmanager
def single_update(root):
    """OS-owned lock: released after crashes, shared by UI and command line."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'update.lock').open('a+b') as handle:
        try:
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError('已有更新任务运行中，请等待该任务完成。') from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def live_quota(paths, work):
    # The shared quote owner bounds SDK construction and reconnect-thread life.
    from scripts.common.daily_support import live_quota as query_quota
    return query_quota(paths, work)


def run_provider(paths, module, arguments, log):
    """Reuse the original shared provider owner and its process-tree containment."""
    from scripts.common.daily_support import run_provider as owned_provider
    return owned_provider(paths, module, arguments, log)


def normalize_acquisition_aliases(tickers, members, history):
    """Collapse transport aliases explicitly bound by the securities registry.

    This affects downloads and frequency counts only, never model identities or
    historical prices. Two different registered securities must still fail.
    """
    import re
    owners, aliases = {}, {}
    mappings = {row['ticker']: row for row in members}
    for row in members:
        code = row.get('moomoo_symbol')
        if not code:
            continue
        prior = owners.get(code)
        if prior and prior['ticker'] != row['ticker']:
            if not row.get('security_id') or prior.get('security_id') != row['security_id']:
                raise ValueError('CONFLICTING_REGISTERED_SECURITY_IDENTITIES:' + code)
            aliases[row['ticker']] = prior['ticker']
        else:
            owners[code] = row
    for code, row in owners.items():
        # Only simple tickers get automatic US.<ticker> transport codes in the
        # planner. A registry-bound SQ -> US.XYZ supersedes catalog-only XYZ.
        suffix = code.removeprefix('US.')
        if re.fullmatch(r'[A-Z0-9]+', suffix) and suffix != row['ticker']:
            if suffix in mappings and mappings[suffix].get('security_id') != row.get('security_id'):
                raise ValueError('CONFLICTING_REGISTERED_SECURITY_IDENTITIES:' + code)
            aliases[suffix] = row['ticker']
    normalized = {**history}
    for key in ('records', 'bootstrap_records'):
        normalized[key] = [{**row, 'ticker': aliases.get(row['ticker'], row['ticker'])}
                           for row in history[key]]
    wanted = sorted({aliases.get(ticker, ticker) for ticker in tickers})
    universe = [{'ticker': ticker, 'moomoo_symbol': mappings.get(ticker, {}).get('moomoo_symbol')}
                for ticker in wanted]
    return universe, normalized, aliases


def load_acquisition_notes(paths, target, members, now):
    """Current collection notes only; never alter frozen model membership.

    Validate every note and evidence before applying any. Invalid notes report a
    diagnostic and leave acquisition unchanged, including other valid entries.
    """
    import re
    owner = (paths.daily_root / 'A2_today_recommendation').resolve()
    path = (owner / 'acquisition_notes.json').resolve()
    pointer = owner / 'acquisition_notes_active.json'
    audit = {'status': 'ABSENT', 'path': str(path), 'deferred': []}
    pointer_raw, expected_sha = None, None
    if not pointer.exists() and not pointer.is_symlink() and not path.exists():
        return audit
    try:
        # The pointer selects one immutable document; it is never a source ref.
        # A present but invalid pointer must not fall back to the legacy file.
        if pointer.exists() or pointer.is_symlink():
            if (not pointer.is_file() or pointer.resolve() != pointer
                    or pointer.stat().st_size > 16 * 1024):
                raise ValueError('ACQUISITION_NOTES_ACTIVE_PATH_OR_SIZE_INVALID')
            pointer_raw = pointer.read_bytes()
            if len(pointer_raw) > 16 * 1024:
                raise ValueError('ACQUISITION_NOTES_ACTIVE_PATH_OR_SIZE_INVALID')
            active = json.loads(pointer_raw)
            if (not isinstance(active, dict) or set(active) != {'schema', 'notes'}
                    or active['schema'] != 'USTQ_CURRENT_ACQUISITION_NOTES_ACTIVE_V1'
                    or not isinstance(active['notes'], dict)
                    or set(active['notes']) != {'path', 'sha256'}):
                raise ValueError('ACQUISITION_NOTES_ACTIVE_SCHEMA_INVALID')
            expected_sha = active['notes']['sha256']
            if not isinstance(expected_sha, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_sha):
                raise ValueError('ACQUISITION_NOTES_ACTIVE_HASH_INVALID')
            versions = owner / 'acquisition_notes/versions'
            selected = active['notes']['path']
            expected_path = versions / (expected_sha + '.json')
            if (not isinstance(selected, str) or not Path(selected).is_absolute()
                    or Path(selected) != expected_path or versions.resolve() != versions
                    or expected_path.resolve() != expected_path or not expected_path.is_file()):
                raise ValueError('ACQUISITION_NOTES_ACTIVE_DOCUMENT_PATH_INVALID')
            path = expected_path
            audit['path'] = str(path)
        if not path.is_relative_to(paths.daily_root.resolve()) or path.stat().st_size > 1024 * 1024:
            raise ValueError('ACQUISITION_NOTES_PATH_OR_SIZE_INVALID')
        if now.tzinfo is None:
            raise ValueError('ACQUISITION_NOTES_NOW_REQUIRES_TIMEZONE')
        target_day = datetime.fromisoformat(target).date()
        if target_day.isoformat() != target:
            raise ValueError('ACQUISITION_NOTES_TARGET_DATE_INVALID')
        raw = path.read_bytes()
        audit['sha256'] = hashlib.sha256(raw).hexdigest()
        if expected_sha is not None and (len(raw) > 1024 * 1024 or audit['sha256'] != expected_sha):
            raise ValueError('ACQUISITION_NOTES_ACTIVE_DOCUMENT_HASH_OR_SIZE_INVALID')
        document = json.loads(raw)
        notes = document.get('notes')
        if (document.get('schema') != 'USTQ_CURRENT_ACQUISITION_NOTES_V1'
                or not isinstance(notes, list) or len(notes) > 1000):
            raise ValueError('ACQUISITION_NOTES_SCHEMA_INVALID')
        # Notes cannot supply their own CUSIP authority. Reuse the prior current
        # member artifact, projecting only its three identity fields.
        import io
        import pyarrow.parquet as pq
        member_ref = document['member_binding']
        member_path = Path(member_ref['path']).resolve()
        member_sha = member_ref.get('sha256')
        if (not member_path.is_relative_to(paths.daily_root.resolve()) or not member_path.is_file()
                or member_path.stat().st_size > 2 * 1024 * 1024
                or not isinstance(member_sha, str) or not re.fullmatch(r'[0-9a-f]{64}', member_sha)):
            raise ValueError('ACQUISITION_NOTE_MEMBER_BINDING_PATH_OR_HASH_INVALID')
        member_raw = member_path.read_bytes()
        if hashlib.sha256(member_raw).hexdigest() != member_sha:
            raise ValueError('ACQUISITION_NOTE_MEMBER_BINDING_HASH_MISMATCH')
        fields = ('ticker', 'security_id', 'moomoo_symbol')
        projection = pq.read_table(io.BytesIO(member_raw), columns=list(fields))
        identities = set(zip(*(projection[column].to_pylist() for column in fields)))
        accepted_kinds = {'ACQUISITION_COMPLETED', 'MERGER_COMPLETED_DISTINCT_SECURITY_RIGHTS',
            'MERGER_CLOSED_TRADING_SUSPENDED', 'ACQUISITION_COMPLETED_TRADING_CEASED',
            'ACQUISITION_COMPLETED_DELISTING', 'ACQUISITION_COMPLETED_DISTINCT_SECURITY_RIGHTS',
            'TEMPORARY_EX_DISTRIBUTION_TRANSPORT'}
        checked_notes, seen, evidence_cache = [], set(), {}
        for note in notes:
            identity = tuple(note.get(key) for key in ('ticker', 'security_id', 'moomoo_symbol'))
            ticker, security, code = identity
            if (not isinstance(ticker, str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9._/-]*', ticker)
                    or not isinstance(security, str) or not re.fullmatch(r'[A-Z0-9]{9}', security)
                    or code != 'US.' + ticker or note.get('scope') != 'CURRENT_ACQUISITION_ONLY'):
                raise ValueError('ACQUISITION_NOTE_IDENTITY_OR_SCOPE_INVALID')
            if identity not in identities:
                raise ValueError('ACQUISITION_NOTE_IDENTITY_NOT_IN_BOUND_MEMBERS')
            if ticker in seen:
                raise ValueError('ACQUISITION_NOTE_DUPLICATE_OR_CONFLICTING_TICKER')
            seen.add(ticker)
            until = note.get('inactive_after_date')
            if datetime.fromisoformat(until).date().isoformat() != until:
                raise ValueError('ACQUISITION_NOTE_INACTIVE_DATE_INVALID')
            checked = datetime.fromisoformat(note['checked_at_utc'].replace('Z', '+00:00'))
            if checked.tzinfo is None or checked.utcoffset() != timedelta(0) or checked > now:
                raise ValueError('ACQUISITION_NOTE_CHECK_TIME_INVALID')
            if any(not isinstance(note.get(key), str) or not note[key].strip()
                   for key in ('note_zh', 'retry_condition')):
                raise ValueError('ACQUISITION_NOTE_EXPLANATION_MISSING')
            reference = note['evidence']
            source = Path(reference['path']).resolve()
            expected = reference.get('sha256')
            if (not source.is_relative_to(paths.results_root.resolve()) or not source.is_file()
                    or source.stat().st_size > 2 * 1024 * 1024
                    or not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected)):
                raise ValueError('ACQUISITION_NOTE_EVIDENCE_PATH_OR_HASH_INVALID')
            cache_key = (str(source), expected)
            if cache_key not in evidence_cache:
                source_raw = source.read_bytes()
                if hashlib.sha256(source_raw).hexdigest() != expected:
                    raise ValueError('ACQUISITION_NOTE_EVIDENCE_HASH_MISMATCH')
                evidence_cache[cache_key] = json.loads(source_raw)['primary_security_lifecycle_evidence']
            matches = [row for row in evidence_cache[cache_key] if row.get('ticker') == ticker]
            if len(matches) != 1:
                raise ValueError('ACQUISITION_NOTE_EVIDENCE_AMBIGUOUS_OR_MISSING')
            evidence = matches[0]
            kind = note.get('kind')
            temporary = kind == 'TEMPORARY_EX_DISTRIBUTION_TRANSPORT'
            bound_date = evidence.get('temporary_market_end') if temporary else evidence.get('event_date')
            if (kind != evidence.get('kind') or until != bound_date
                    or kind not in accepted_kinds
                    or evidence.get('security_id', security) != security):
                raise ValueError('ACQUISITION_NOTE_LIFECYCLE_FACT_MISMATCH')
            urls = note.get('official_urls')
            official = evidence.get('urls', [evidence.get('url')])
            if (not isinstance(urls, list) or not urls
                    or any(not isinstance(url, str) or not url.startswith('https://') or url not in official for url in urls)):
                raise ValueError('ACQUISITION_NOTE_OFFICIAL_SOURCE_MISMATCH')
            checked_notes.append(note)
        current = {(row.get('ticker'), row.get('security_id'),
                    row.get('moomoo_symbol', row.get('moomoo_transport_code'))) for row in members}
        if pointer_raw is not None:
            if (not pointer.is_file() or pointer.resolve() != pointer
                    or pointer.stat().st_size > 16 * 1024 or pointer.read_bytes() != pointer_raw
                    or path.resolve() != path or path.stat().st_size > 1024 * 1024
                    or path.read_bytes() != raw):
                raise ValueError('ACQUISITION_NOTES_ACTIVE_CHANGED_DURING_VALIDATION')
        audit.update(status='READY', validated_count=len(checked_notes),
                     deferred=[note for note in checked_notes
                               if tuple(note[key] for key in ('ticker', 'security_id', 'moomoo_symbol')) in current
                               and target > note['inactive_after_date']])
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        audit.update(status='INVALID', error=str(exc), deferred=[])
    return audit


def acquisition_note_context(acquisition_universe, history, members, aliases, audit):
    """Filter collection copies only, preserving source member/rank objects."""
    deferred = {aliases.get(note['ticker'], note['ticker']) for note in audit['deferred']}
    active = lambda row: aliases.get(row['ticker'], row['ticker']) not in deferred
    return ([row for row in acquisition_universe if active(row)],
            {**history, **{key: [row for row in history[key] if active(row)]
                          for key in ('records', 'bootstrap_records')}},
            [row for row in members if active(row)])


def alternate_acquisition_scope(plan, subscriptions, *, aliases=None):
    """Bound Yahoo requests only; preserve original quota, priorities and identities."""
    import re
    from scripts.storage.refresh_demo_benchmarks import ETF_IDENTITIES
    aliases = {} if aliases is None else aliases
    if (not isinstance(aliases, dict) or not isinstance(subscriptions, list)
            or plan.get('pool_supplement_authorized') is not True):
        raise ValueError('ALTERNATE_SCOPE_METADATA_INVALID')
    target = plan.get('as_of_date')
    if not isinstance(target, str) or datetime.fromisoformat(target).date().isoformat() != target:
        raise ValueError('ALTERNATE_SCOPE_DATE_INVALID')
    rows = plan.get('assignments')
    if not isinstance(rows, list):
        raise ValueError('ALTERNATE_SCOPE_ASSIGNMENTS_INVALID')
    required, names = set(), set()
    for row in rows:
        ticker = row.get('ticker')
        if (not isinstance(ticker, str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9._/\-]{0,31}', ticker)
                or ticker in names or type(row.get('in_explicit_refresh_pool')) is not bool
                or type(row.get('frequency_days')) is not int or row['frequency_days'] < 0
                or row.get('provider') not in {'MOOMOO', 'ALTERNATE'}):
            raise ValueError('ALTERNATE_SCOPE_ASSIGNMENTS_INVALID')
        names.add(ticker)
        if row['in_explicit_refresh_pool'] or row['frequency_days'] > 0 or row['provider'] == 'MOOMOO':
            required.add(ticker)
    required.update(names.intersection(ETF_IDENTITIES))
    subscribed = set()
    for row in subscriptions:
        ticker = row.get('ticker')
        ticker = aliases.get(ticker, ticker)
        if not isinstance(ticker, str) or ticker not in names:
            raise ValueError('ALTERNATE_SCOPE_SUBSCRIPTION_UNBOUND')
        subscribed.add(ticker)
    commitment = hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()
    return {'schema': 'A2_DAILY_YAHOO_ACQUISITION_SCOPE_V1', 'target_date': target,
        'assignments_sha256': commitment, 'subscription_tickers': sorted(subscribed),
        'allowed_tickers': sorted(required | subscribed)}


def _validated_alternate_scope(plan, target, scope):
    """Reject stale or incomplete explicit scopes before any provider construction."""
    if not isinstance(scope, dict) or scope.get('target_date') != target:
        raise ValueError('ALTERNATE_SCOPE_BINDING_CHANGED')
    subscriptions = scope.get('subscription_tickers')
    if not isinstance(subscriptions, list):
        raise ValueError('ALTERNATE_SCOPE_BINDING_CHANGED')
    expected = alternate_acquisition_scope(plan, [{'ticker': ticker} for ticker in subscriptions])
    if scope != expected:
        raise ValueError('ALTERNATE_SCOPE_BINDING_CHANGED')
    return set(expected['allowed_tickers'])


def acquire_prices(paths, root, run_dir, plan, start, target, emit_progress=emit, *, alternate_scope=None):
    """Reuse both existing provider adapters; retain their native price bases."""
    import csv
    from types import SimpleNamespace
    from scripts.storage import refresh_market_data
    moomoo = [row for row in plan['assignments'] if row['provider'] == 'MOOMOO']
    alternate = [row['ticker'] for row in plan['assignments'] if row['provider'] == 'ALTERNATE']
    reports = {}
    if alternate_scope is not None:
        allowed = _validated_alternate_scope(plan, target, alternate_scope)
        requested = len(alternate)
        alternate = [ticker for ticker in alternate if ticker in allowed]
        reports['alternate_scope'] = {**alternate_scope, 'requested_before': requested,
            'requested_after': len(alternate), 'catalog_only_skipped': requested - len(alternate)}
    run_key = run_dir.parent.name + '_moomoo_topup' if run_dir.name == 'moomoo_topup' else run_dir.name
    if moomoo:
        emit_progress(f'Moomoo：补齐 {len(moomoo)} 支股票，数据目标 {target}。')
        universe = run_dir / 'moomoo_universe.csv'
        with universe.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=['ticker', 'moomoo_symbol'])
            writer.writeheader()
            writer.writerows({key: row[key] for key in writer.fieldnames} for row in moomoo)
        market_root = paths.cache_root / 'daily_recommendation' / 'moomoo' / target
        items = refresh_market_data.make_plan(refresh_market_data.load_universe(None, universe), start, target, ['raw', 'qfq'])
        # A stale successful interval is immutable. Retry only its ticker in a
        # fresh root; complete checkpoints and new intervals retain normal reuse.
        # read_checkpoint remains the authority for identity/hash validation.
        stale = {item['ticker'] for item in items
                 if (checkpoint := refresh_market_data.read_checkpoint(market_root, item))
                 and checkpoint['latest_date'] < target}
        batches, summaries = [], []
        for name, members, work_root in (
            ('stable', [row for row in moomoo if row['ticker'] not in stale], market_root),
            ('retry', [row for row in moomoo if row['ticker'] in stale], market_root / 'attempts' / run_key),
        ):
            if not members:
                continue
            group_universe = run_dir / f'moomoo_{name}_universe.csv'
            with group_universe.open('w', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=['ticker', 'moomoo_symbol'])
                writer.writeheader()
                writer.writerows({key: row[key] for key in writer.fieldnames} for row in members)
            log_path = run_dir / ('moomoo.log' if name == 'stable' else 'moomoo_retry.log')
            arguments = SimpleNamespace(work_root=work_root, repo_root=paths.repo_root,
                tickers=None, universe_csv=group_universe, start=start, end=target,
                adjustments=['raw', 'qfq'], execute=True, host=None, port=None, max_retries=1)
            try:
                with log_path.open('w', encoding='utf-8') as log, redirect_stdout(log):
                    summary = refresh_market_data.run(arguments)
            except Exception as exc:
                summary = {'status': 'FAILED', 'error': str(exc), 'results': []}
                emit_progress('Moomoo 本次请求未完成，继续处理其他数据源。')
            summary_path = run_dir / f'moomoo_{name}_acquisition.json'
            save(summary_path, summary)
            summaries.append(summary)
            batches.append({'group': name, 'work_root': str(work_root), 'ticker_count': len(members),
                'universe_path': str(group_universe), 'log_path': str(log_path),
                'summary_path': str(summary_path), 'status': summary['status']})
        combined = {**summaries[0], 'batches': batches, 'stale_retry_tickers': sorted(stale)}
        if len(summaries) > 1:
            results = [row for summary in summaries for row in summary.get('results', [])]
            successful = sum(row.get('status') in {'FETCHED_VALIDATED_INTERVAL', 'REUSED_VERIFIED_INTERVAL'} for row in results)
            combined.update(results=results, plan=items,
                status=('ALL_INTERVALS_REUSED' if len(results) == len(items) and all(row.get('status') == 'REUSED_VERIFIED_INTERVAL' for row in results)
                        else 'ACQUIRED' if successful == len(items) else 'PARTIAL' if successful else 'FAILED'))
            for field in ('history_request_count', 'new_unique_security_touch_count', 'pending_leg_count'):
                combined[field] = sum(summary.get(field, 0) for summary in summaries)
            for field in ('request_audit', 'errors', 'recovered_errors'):
                combined[field] = [row for summary in summaries for row in summary.get(field, [])]
            combined['quota_before'] = next((summary['quota_before'] for summary in summaries if summary.get('quota_before')), None)
        reports['moomoo'] = combined
        save(run_dir / 'moomoo_acquisition.json', reports['moomoo'])
        reached = {row['item']['ticker'] for row in reports['moomoo'].get('results', [])
                   if row.get('status') in {'FETCHED_VALIDATED_INTERVAL', 'REUSED_VERIFIED_INTERVAL'}
                   and row.get('item', {}).get('adjustment') == 'raw'
                   and row.get('latest_date', '') >= target}
        # A quota assignment is not a successful download. Delisted/unsupported
        # or incomplete Moomoo responses also get the alternate-provider attempt.
        alternate = sorted(set(alternate) | {row['ticker'] for row in moomoo
                                             if row['ticker'] not in reached})
    if alternate:
        emit_progress(f'其他 API：更新 {len(alternate)} 支股票，保留独立来源及复权口径。')
        alternate_root = paths.cache_root / 'daily_recommendation' / run_key / 'yahoo'
        # Explicit issuer announcements bind these two historical model names
        # to their current Yahoo transport codes. Never infer other aliases.
        known_aliases = {
            'SQ': {'provider_symbol': 'XYZ', 'evidence_url': 'https://investors.block.xyz/investor-news/news-details/2025/Block-Announces-Ticker-Symbol-Change-to-XYZ-To-Report-Fourth-Quarter-Results/default.aspx'},
            'TPX': {'provider_symbol': 'SGI', 'evidence_url': 'https://investor.somnigroup.com/newsroom/news-details/2025/Tempur-Sealy-International-Inc.-to-Change-its-Name-to-Somnigroup-International-Inc/default.aspx'},
        }
        aliases = {ticker: value for ticker, value in known_aliases.items() if ticker in alternate}
        mapping_args = []
        if aliases:
            mapping_path = run_dir / 'yahoo_symbol_map.json'
            save(mapping_path, aliases)
            mapping_args = ['--symbol-map', mapping_path]
        reports['alternate'] = run_provider(paths, 'scripts.storage.refresh_free_market',
            ['--start', start, '--end', target, '--work-root', alternate_root,
             '--events-through', max(target, datetime.now(ZoneInfo('America/New_York')).date().isoformat()),
             *mapping_args, '--workers', '2', '--tickers', *alternate, '--execute'], run_dir / 'alternate.log')
        report_path = alternate_root / 'acquisition_report.json'
        if report_path.is_file():
            reports['alternate']['receipt'] = str(report_path)
            report = json.loads(report_path.read_text(encoding='utf-8'))
            reports['alternate'].update({key: report.get(key) for key in
                ('attempted_symbols', 'successful_symbols', 'target_reached_symbols')})
    return reports


def acquire_other_data(paths, run_dir, target, catalog, emit_progress=emit):
    """Refresh current observations without changing historical research vintages."""
    from scripts.storage.refresh_current_observations import run_current_sources
    try:
        return run_current_sources(paths, 'today_' + run_dir.name,
            datetime.now(timezone.utc).date().isoformat(), target, emit_progress=emit_progress,
            runner=lambda module, args, log: run_provider(paths, module, args, log))
    except Exception as exc:
        emit_progress('公开数据更新尚有未完成项，继续核对 A2 行情输入。')
        return {'status': 'PARTIAL', 'error': str(exc)}


def current_pool_supplement(members, aliases, catalog_prices):
    """Limit additional quota to current verified 13F identities with raw gaps.

    This metadata is only a download priority hint. The acquisition and frozen
    input adapters still verify the actual files, identities and session dates.
    """
    dates = {}
    for row in catalog_prices:
        if row.get('adjustment') != 'raw' or not Path(row['path']).is_file():
            continue
        ticker = aliases.get(row['ticker'], row['ticker'])
        value = row.get('max_date')
        if value:
            day = datetime.fromisoformat(str(value)[:10]).date().isoformat()
            dates[ticker] = max(day, dates.get(ticker, day))
    return [{'ticker': ticker, 'last_price_date': dates.get(ticker)}
            for ticker in sorted({aliases.get(row['ticker'], row['ticker']) for row in members})]


def acquire_pool_prices(paths, root, run_dir, plan, start, target, members, sessions, emit_progress=emit, *, alternate_scope=None):
    """Refresh pool prices and the Massive execution marks needed by DEMO."""
    if alternate_scope is not None:
        _validated_alternate_scope(plan, target, alternate_scope)
    from scripts.storage.refresh_current_massive import refresh_massive_current
    # Priority does not guarantee a Moomoo slot: the live quota or user cap
    # can route even Top20 names to alternate providers. Keep those names in
    # Massive's current scope so cached grouped bars can reach the basis gate.
    moomoo_assigned = {row['ticker'] for row in plan['assignments']
                       if row.get('provider') == 'MOOMOO'}
    execution_marks = {'CAI', 'HIVE', 'SDGR', 'SFIX', 'TEAM', 'TEM', 'XENE'}
    selected = [row for row in members
                if row['ticker'] not in moomoo_assigned or row['ticker'] in execution_marks]
    emit_progress(f'MASSIVE：更新 {len(selected)} 支池内股票（含 DEMO 执行价格所需股票）。')
    try:
        massive = refresh_massive_current(paths, selected, sessions, target, run_dir, progress=emit_progress)
    except Exception as exc:
        # No credentials are passed through an exception string in this caller.
        massive = {'status': 'FAILED', 'error_type': type(exc).__name__}
        emit_progress('MASSIVE 本次未完成，继续其他已配置来源。')
    result = acquire_prices(paths, root, run_dir, plan, start, target, emit_progress,
        **({'alternate_scope': alternate_scope} if alternate_scope is not None else {}))
    result['massive'] = massive
    return result


def acquire_native_current_tail(paths, run_dir, target, members, acquisitions, catalog_prices, sessions, progress=emit):
    """Fill native missing dates with the original bounded RAW/RTH API.

    Metadata selects acquisition scope only. Original publication and frozen
    feature eligibility still verify identity, bytes, rehab and full history.
    Existing native dates are excluded; no history or alternate gate is granted.
    """
    import csv
    from types import SimpleNamespace
    from scripts.storage import refresh_market_data as market
    from scripts.common.storage_paths import assert_safe_output_path
    from scripts.research.a2.inference.current_native_prices import REVIEWED_TRANSPORT_ALIASES, validate_explicit_alias
    dates = {}
    for row in catalog_prices:
        if row.get('adjustment') == 'raw' and Path(row['path']).is_file() and row.get('max_date'):
            day = str(row['max_date'])[:10]
            dates[row['ticker']] = max(day, dates.get(row['ticker'], day))
    from scripts.daily_recommendation_prices import native_missing_interval_starts
    internal_starts = native_missing_interval_starts(paths, members, catalog_prices, target, sessions) if dates else {}
    groups, selected = {}, []
    for member in members:
        ticker = member['ticker']
        if ticker in REVIEWED_TRANSPORT_ALIASES:
            ticker = validate_explicit_alias(REVIEWED_TRANSPORT_ALIASES[ticker], ticker,
                member['moomoo_symbol'], [member['security_id']])
        last = dates.get(ticker)
        if last is None:
            continue
        starts = [internal_starts[ticker]] if ticker in internal_starts else []
        if last < target:
            starts.append((datetime.fromisoformat(last).date() + timedelta(days=1)).isoformat())
        if not starts:
            continue
        start = min(starts)
        available = [day for day in sessions if start <= day <= target]
        if not available or len(available) > market.CURRENT_KLINE_NUM:
            continue
        row = {**{key: member[key] for key in ('security_id', 'moomoo_symbol')}, 'ticker': ticker}
        groups.setdefault(start, []).append(row)
        selected.append({**row, 'logical_ticker': member['ticker'], 'native_latest_date': last, 'requested_start': start})
    if not groups:
        return dict(acquisitions), {'status': 'NOOP', 'target_date': target, 'scope': [],
            'history_request_count': 0, 'trade_requests': 0, 'groups': [],
            'qualified_intervals': 0, 'result_count': 0}
    work = Path(run_dir) / 'native_current_tail'
    assert_safe_output_path(work, paths=paths, kind='daily'); work.mkdir(parents=True, exist_ok=True)
    audit = {'status': 'RUNNING', 'target_date': target, 'scope': selected,
             'history_request_count': 0, 'trade_requests': 0, 'source_policy': 'MOOMOO_ONLY',
             'acquisition_mode': 'current-kline', 'groups': []}
    rows = []
    # Bound owned subscriptions and tables independently of universe size.
    batches = [(start, number, group[offset:offset + 64])
               for start, group in sorted(groups.items())
               for number, offset in enumerate(range(0, len(group), 64))]
    for start, number, group in batches:
        batch_key = start + '_' + str(number).zfill(3)
        cache = paths.cache_root / 'daily_recommendation/native_current_tail' / target / batch_key / Path(run_dir).name
        assert_safe_output_path(cache, paths=paths, kind='cache')
        universe = work / (batch_key + '.csv')
        with universe.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=['ticker', 'security_id', 'moomoo_symbol'])
            writer.writeheader(); writer.writerows(group)
        progress(f'Moomoo 原生补尾：{len(group)} 只，{start} → {target}。')
        try:
            summary = market.run(SimpleNamespace(repo_root=paths.repo_root, work_root=cache,
                tickers=None, universe_csv=universe, start=start, end=target, adjustments=['raw'],
                host=None, port=None, max_retries=0, execute=True, acquisition_mode='current-kline', known_only=False))
            if summary.get('history_request_count', 0) or summary.get('trade_context_opened'):
                raise ValueError('NATIVE_TAIL_UNEXPECTED_API_SCOPE')
        except Exception as exc:
            summary = {'status': 'FAILED', 'error_type': type(exc).__name__, 'results': []}
        receipt = work / (batch_key + '.json'); save(receipt, summary)
        audit['groups'].append({'start': start, 'batch': number, 'members': len(group), 'status': summary['status'],
            'receipt': str(receipt), 'sha256': hashlib.sha256(receipt.read_bytes()).hexdigest()})
        rows.extend(summary.get('results', []))
        refusal_tokens = ('quota', 'permission', 'entitlement', 'rate limit', '频率', '额度', '权限')
        refused = any(token in str(summary.get('error', '')).lower() for token in refusal_tokens) or any(
            row.get('status') == 'BLOCKED_AFTER_PROVIDER_PERMISSION_QUOTA_OR_RATE_LIMIT'
            or any(token in str(row.get('error', '')).lower() for token in refusal_tokens)
            for row in summary.get('results', []))
        if summary['status'] in {'FAILED', 'BLOCKED'} or refused:
            audit['blocked_remaining_groups'] = len(batches) - len(audit['groups'])
            break
    audit['qualified_intervals'] = sum(row.get('status') in {'FETCHED_VALIDATED_INTERVAL', 'REUSED_VERIFIED_INTERVAL'} for row in rows)
    audit['result_count'] = len(rows)
    if groups:
        audit['status'] = 'ACQUIRED' if audit['qualified_intervals'] == len(selected) else 'PARTIAL'
    save(work / 'report.json', audit)
    merged = {**acquisitions}
    if rows:
        old = acquisitions.get('moomoo', {})
        merged['moomoo'] = {**old, 'results': [*old.get('results', []), *rows],
            'native_current_tail': {'path': str(work / 'report.json'),
                                   'sha256': hashlib.sha256((work / 'report.json').read_bytes()).hexdigest()}}
    return merged, audit



def acquire_benchmark_native_inputs(paths, run_dir, target, scope, store, progress=emit, *, execution_date=None):
    """Acquire at most the two bound ETFs after the original cache owner requests it.

    These inputs only extend descriptive benchmark prices. They are never added
    to the A2 universe, quota plan, prediction receipts or trading candidates.
    """
    import csv
    from types import SimpleNamespace
    from scripts.common.storage_paths import assert_safe_output_path
    from scripts.storage import refresh_market_data as market
    from scripts.storage.refresh_demo_benchmarks import ETF_IDENTITIES
    from scripts.research.a2.inference.current_native_prices import _native_raw
    audit = {'status': 'NOOP', 'target_date': target, 'scope': scope,
             'inputs': {}, 'history_request_count': 0, 'trade_requests': 0,
             'new_current_kline_requests': 0, 'rejections': []}
    if scope.get('status') != 'NEEDS_NATIVE':
        return {}, audit
    symbols = scope.get('native_tickers', [])
    required = scope.get('required_dates', [])
    start = scope.get('bridge_start', '')
    if (not symbols or len(symbols) != len(set(symbols)) or set(symbols) != set(ETF_IDENTITIES)
            or not required or required != sorted(set(required)) or required[-1] > target
            or scope.get('target_date') != target
            or start != required[0] or len(required) > market.CURRENT_KLINE_NUM):
        raise ValueError('BENCHMARK_NATIVE_ACQUISITION_SCOPE_INVALID')
    if execution_date is not None:
        from scripts.research.a2.evaluation.demo_performance_prices import execution_open_clock
        execution_open_clock(target, execution_date, scope.get('sessions', []), scope.get('as_of_utc'))
        audit['execution_date'] = execution_date
    inputs, pending = {}, []
    for symbol in symbols:
        identity = ETF_IDENTITIES[symbol]
        try:
            # A closed catalog leaf cannot prove the following official open.
            record = None if execution_date is not None else store.metadata('prices_daily', symbol, 'raw')
        except (KeyError, FileNotFoundError):
            record = None
        if record is not None:
            # Check actual bounded data and original leaves, not max-date alone.
            raw, proof = _native_raw(store, symbol, identity['provider_code'], target)
            actual_dates = set(raw.trade_date.dt.strftime('%Y-%m-%d'))
            if set(required) <= actual_dates:
                inputs[symbol] = {**identity, 'kind': 'CATALOG_RAW',
                    'reference': {'path': proof['path'], 'sha256': proof['sha256']}}
                continue
        pending.append({'ticker': symbol, 'security_id': identity['security_id'],
                        'moomoo_symbol': identity['provider_code']})
    if pending:
        work = Path(run_dir) / 'benchmark_native'
        cache = paths.cache_root / 'daily_recommendation/benchmark_native' / target
        if execution_date is not None:
            # Retain prior immutable SDK responses; never relabel an old interval.
            cache = cache / 'execution_open' / execution_date / uuid.uuid4().hex
        assert_safe_output_path(work, paths=paths, kind='daily')
        assert_safe_output_path(cache, paths=paths, kind='cache')
        work.mkdir(parents=True, exist_ok=True)
        universe = work / 'universe.csv'
        with universe.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=['ticker', 'security_id', 'moomoo_symbol'])
            writer.writeheader(); writer.writerows(pending)
        progress(f'Moomoo 基准补尾：{len(pending)} 只 ETF，{start} → {target}。')
        summary = market.run(SimpleNamespace(repo_root=paths.repo_root, work_root=cache,
            tickers=None, universe_csv=universe, start=start, end=target, adjustments=['raw'],
            host=None, port=None, max_retries=0, execute=True,
            acquisition_mode='current-kline', known_only=False))
        save(work / 'acquisition.json', summary)
        if summary.get('history_request_count', 0) or summary.get('trade_context_opened'):
            raise ValueError('BENCHMARK_NATIVE_UNEXPECTED_API_SCOPE')
        audit['acquisition'] = {'path': str(work / 'acquisition.json'),
            'sha256': hashlib.sha256((work / 'acquisition.json').read_bytes()).hexdigest()}
        audit['new_current_kline_requests'] = summary.get('current_kline_calls', 0)
        audit['qualified_new_intervals'] = sum(row.get('status') == 'FETCHED_VALIDATED_INTERVAL'
                                                  for row in summary.get('results', []))
        expected = {row['ticker']: row for row in pending}
        for row in summary.get('results', []):
            item = row.get('item', {})
            symbol = item.get('ticker')
            if symbol not in expected or row.get('status') not in {'FETCHED_VALIDATED_INTERVAL', 'REUSED_VERIFIED_INTERVAL'}:
                audit['rejections'].append({'ticker': symbol, 'reason': row.get('status', 'UNKNOWN')})
                continue
            if (symbol in inputs or any(item.get(key) != value for key, value in expected[symbol].items())
                    or item.get('adjustment') != 'raw' or item.get('acquisition_method') != 'GET_CUR_KLINE'
                    or item.get('session') != 'RTH' or item.get('planned_start_date') != start
                    or item.get('planned_end_date') != target or row.get('latest_date') != target):
                raise ValueError('BENCHMARK_NATIVE_INTERVAL_IDENTITY_OR_DATE_MISMATCH')
            checkpoint = Path(row['path']).with_suffix('.json').resolve()
            if not checkpoint.is_relative_to(cache.resolve() / 'intervals'):
                raise ValueError('BENCHMARK_NATIVE_CHECKPOINT_OUTSIDE_OWNER_CACHE')
            inputs[symbol] = {**ETF_IDENTITIES[symbol], 'kind': 'CURRENT_KLINE',
                'reference': {'path': str(checkpoint), 'sha256': hashlib.sha256(checkpoint.read_bytes()).hexdigest()}}
    audit['inputs'] = inputs
    audit['status'] = 'READY' if set(inputs) == set(symbols) else 'PARTIAL'
    return inputs, audit


def refresh_daily_benchmarks(paths, run_dir, target, calendar, store, progress=emit):
    """Keep the original cached publisher authoritative and failures independent."""
    from scripts.storage.refresh_demo_benchmarks import benchmark_native_scope, refresh_demo_benchmarks
    scope = benchmark_native_scope(paths, target, calendar)
    try:
        native, audit = acquire_benchmark_native_inputs(paths, run_dir, target, scope, store, progress)
    except Exception as exc:
        native, audit = {}, {'status': 'BLOCKED', 'target_date': target,
            'scope': scope, 'error_type': type(exc).__name__, 'reason': str(exc),
            'history_request_count': 0, 'trade_requests': 0}
        progress('基准备用行情未通过校验，保留原已验证基准截止日。')
    save(Path(run_dir) / 'benchmark_native_acquisition.json', audit)
    if native:
        result = refresh_demo_benchmarks(paths, target, calendar, progress, native_inputs=native)
    else:
        result = refresh_demo_benchmarks(paths, target, calendar, progress)
    result['native_acquisition'] = {'path': str(Path(run_dir) / 'benchmark_native_acquisition.json'),
        'sha256': hashlib.sha256((Path(run_dir) / 'benchmark_native_acquisition.json').read_bytes()).hexdigest()}
    return result


def prediction_after_native_publication(acquisitions, publication, native_count, target):
    """Route successfully published tails to the original full-catalog reader.

    Actual acquisition receipts remain unchanged. A short tail must not shadow
    its complete native history in the legacy fetched-receipt dictionary.
    """
    rows = acquisitions.get('moomoo', {}).get('results', [])
    if not native_count or native_count > len(rows) or publication.get('status') != 'PUBLISHED':
        return acquisitions
    native = rows[-native_count:]
    success = {'FETCHED_VALIDATED_INTERVAL', 'REUSED_VERIFIED_INTERVAL'}
    published = [row for row in native if row.get('status') in success]
    if (publication.get('target_date') != target or publication.get('all_old_dates_preserved') is not True
            or not published or any(row.get('item', {}).get('adjustment') != 'raw'
                or not row.get('item', {}).get('ticker') for row in published)):
        return acquisitions
    names = {row['item']['ticker'] for row in published}
    if (len(names) != len(published) or publication.get('published_intervals') != len(names)
            or publication.get('requested_keys') != len(names)
            or publication.get('raw_reached_target') != len(names)):
        return acquisitions
    # Match the original publisher's complete successful request, including
    # identity, date scope and receipt hashes. Failed symbols remain untouched.
    request_hash = hashlib.sha256(json.dumps({'target_date': target, 'receipts': [
        {key: row.get(key) for key in ('item', 'path', 'sha256')} for row in published
    ]}, sort_keys=True).encode()).hexdigest()
    if publication.get('request_sha256') != request_hash:
        return acquisitions
    filtered = [row for row in rows if not (row.get('status') in success
        and row.get('item', {}).get('adjustment') == 'raw' and row['item']['ticker'] in names)]
    return {**acquisitions, 'moomoo': {**acquisitions['moomoo'], 'results': filtered}}

def topup_moomoo_once(paths, root, run_dir, plan, acquisitions, target, start,
                     history, acquisition_universe, pool_supplement, emit_progress=emit):
    """One live-quota replan after two explicit, identity-bound provider refusals.

    The evidence applies only to this acquisition. It never refunds a charged
    slot or creates a persistent unsupported-security list.
    """
    from scripts.storage.top20_quota_plan import build_top20_quota_plan
    if 'moomoo_topup' in acquisitions:
        return acquisitions
    assigned = {row['ticker']: row['moomoo_symbol'] for row in plan['assignments']
                if row['provider'] == 'MOOMOO'}
    first = acquisitions.get('moomoo', {})
    unavailable = []
    for ticker, code in assigned.items():
        rows = [row for row in first.get('results', []) if row.get('item', {}).get('ticker') == ticker]
        allowed_errors = {f'未知股票 {ticker}', '暂不提供美股 OTC 市场行情',
                          f'暂不提供美股 OTC 市场行情 {ticker}'}
        if (len(rows) == 2 and {row['item'].get('adjustment') for row in rows} == {'raw', 'qfq'}
                and all(row.get('status') == 'FAILED_FETCH'
                        and row['item'].get('planned_end_date') == target
                        and row['item'].get('moomoo_symbol') == code
                        and row.get('error') in allowed_errors for row in rows)):
            unavailable.append(code)
    audit = {'status': 'SKIPPED', 'reason': 'NO_CONFIRMED_PROVIDER_REFUSALS',
             'provider_unavailable_codes': sorted(unavailable), 'max_topup_rounds': 1}
    merged = {**acquisitions, 'moomoo_topup': audit}
    if not unavailable:
        return merged
    work = run_dir / 'moomoo_topup'
    work.mkdir(parents=True, exist_ok=True)
    audit['report_path'] = str(work / 'report.json')
    try:
        with (work / 'quota.log').open('w', encoding='utf-8') as log, redirect_stdout(log):
            quota = live_quota(paths, work)
        replanned = build_top20_quota_plan(history['records'], quota, as_of_date=target,
            bootstrap_records=history['bootstrap_records'], universe=acquisition_universe,
            pool_supplement=pool_supplement, provider_unavailable=unavailable,
            lookback_sessions=plan.get('lookback_sessions', 60),
            max_moomoo_symbols=plan.get('max_moomoo_symbols', 300))
        save(work / 'quota_plan.json', replanned)
        audit.update(quota_plan_path=str(work / 'quota_plan.json'), quota=replanned['quota'])
        attempted = set(assigned.values())
        selected = [row for row in replanned['assignments'] if row['provider'] == 'MOOMOO'
                    and row['moomoo_symbol'] not in attempted and row['moomoo_symbol'] not in unavailable]
        audit['selected_tickers'] = [row['ticker'] for row in selected]
        if not selected:
            audit['reason'] = 'NO_NEW_ELIGIBLE_MOOMOO_ASSIGNMENTS'
        else:
            topup_plan = {**replanned, 'assignments': selected}
            save(work / 'acquisition_plan.json', topup_plan)
            emit_progress(f'Moomoo：明确拒绝项不再重复请求，按实时额度一次补位 {len(selected)} 支。')
            added = acquire_prices(paths, root, work, topup_plan, start, target, emit_progress)
            save(work / 'acquisitions.json', added)
            audit.update(status='ATTEMPTED', reason='BOUNDED_LIVE_QUOTA_TOPUP',
                         acquisitions_path=str(work / 'acquisitions.json'))
            extra = added.get('moomoo', {})
            rows = [*first.get('results', []), *extra.get('results', [])]
            successful = sum(row.get('status') in {'FETCHED_VALIDATED_INTERVAL', 'REUSED_VERIFIED_INTERVAL'} for row in rows)
            combined = {**first, 'results': rows,
                'status': 'ACQUIRED' if successful == 2 * (len(assigned) + len(selected)) else 'PARTIAL' if successful else 'FAILED',
                'topup_acquisition_path': str(work / 'moomoo_acquisition.json')}
            for field in ('history_request_count', 'new_unique_security_touch_count', 'pending_leg_count'):
                combined[field] = first.get(field, 0) + extra.get(field, 0)
            for field in ('plan', 'request_audit', 'errors', 'recovered_errors', 'batches'):
                combined[field] = [*first.get(field, []), *extra.get(field, [])]
            merged['moomoo'] = combined
            save(run_dir / 'moomoo_acquisition_with_topup.json', combined)
            if added.get('alternate'):
                # The price loader reads one native Yahoo receipt; retain all
                # rows and source receipts, including failures, in that view.
                sources = [entry for entry in (acquisitions.get('alternate'), added['alternate']) if entry]
                receipts = [json.loads(Path(entry['receipt']).read_text(encoding='utf-8'))
                            if entry.get('receipt') else entry for entry in sources]
                alternate = {'results': [row for receipt in receipts for row in receipt.get('results', [])],
                             'source_reports': sources}
                for field in ('attempted_symbols', 'successful_symbols', 'target_reached_symbols'):
                    alternate[field] = sum(receipt.get(field, 0) or 0 for receipt in receipts)
                receipt_path = work / 'merged_alternate_receipt.json'
                save(receipt_path, alternate)
                merged['alternate'] = {'receipt': str(receipt_path), 'source_reports': sources,
                                       **{field: alternate[field] for field in
                                          ('attempted_symbols', 'successful_symbols', 'target_reached_symbols')}}
    except Exception as exc:
        audit.update(status='FAILED', reason='TOPUP_ERROR', error=str(exc))
        emit_progress('Moomoo 本轮补位未完成，保留已取得的收据并继续发布和校验。')
    save(work / 'report.json', audit)
    return merged


def predict_current(binding, universe, target, sessions, acquisitions, store, rehab_receipt, output_dir=None):
    """Reuse the accepted raw/rehab basis and frozen feature/prediction APIs."""
    import numpy as np
    import pandas as pd
    from scripts.v22.forward_shadow.exact_date_components import run_alpha_single_date
    from scripts.storage.refresh_market_data import load_module
    from scripts.storage.storage_r2a import DataStore
    from scripts.daily_recommendation_prices import load_price_inputs
    if not universe['current']:
        raise ValueError(universe['reason'])
    component = binding['components']['ALPHA']
    source_ref = next(item for item in component['artifacts'] if item['artifact_id'] == 'source')
    source = load_module(Path(source_ref['path']), 'today_frozen_a2_features')
    if type(store) is DataStore:
        from scripts.research.a2.inference.historical_top40_prices import ValidatedBatchStore
        store = ValidatedBatchStore(store)
    prices, lineage, missing = load_price_inputs(target, universe['members'], sessions, acquisitions, store, rehab_receipt)
    features = (source.build_stock_state_features(prices) if not prices.empty else
                pd.DataFrame(columns=['trade_date', 'ticker', *source.FEATURE_COLUMNS]))
    expandable = {row['ticker'] for row in missing if row.get('reason') == 'A2_ORIGINAL_RAW_ANCHOR_UNBOUND'}
    if output_dir is not None and expandable:
        try:
            from scripts.research.a2.inference.historical_top40 import load_sessions
            from scripts.research.a2.inference.historical_top40_prices import build_price_features
            from scripts.daily_recommendation_prices import digest
            paths = getattr(store, 'paths', None)
            if paths is None:
                raise ValueError('EXPANDED_ANCHOR_STORAGE_PATHS_REQUIRED')
            full_sessions, calendar = load_sessions(paths)
            members = [row for row in universe['members'] if row['ticker'] in expandable]
            work = Path(output_dir) / 'expanded_anchor_inputs'
            extra, proof_rows, gaps = build_price_features(paths, members, target, target, full_sessions,
                acquisitions, rehab_receipt, work)
            if (not set(extra.ticker).issubset(expandable) or extra.ticker.duplicated().any()
                    or not pd.to_datetime(extra.trade_date).eq(pd.Timestamp(target)).all()):
                raise ValueError('EXPANDED_ANCHOR_FEATURE_IDENTITY_MISMATCH')
            extra = extra.loc[np.isfinite(extra[list(source.FEATURE_COLUMNS)].to_numpy(float)).all(axis=1)]
            accepted = set(extra.ticker)
            proofs = {row['ticker']: row for row in proof_rows}
            if not accepted.issubset(proofs):
                raise ValueError('EXPANDED_ANCHOR_PRICE_PROOF_MISSING')
            manifest = work / 'prices/manifest.json'
            reference = {'path': str(manifest), 'sha256': digest(manifest)}
            gap_map = {row['ticker']: row for row in gaps}
            extra_lineage = []
            for ticker in sorted(accepted):
                proof = proofs[ticker]
                provider = (proof.get('alternate_bridge') or {}).get('provider')
                label = ('MOOMOO_RAW_PLUS_QUALIFIED_MASSIVE_TAIL_PLUS_MOOMOO_REHAB' if provider == 'MASSIVE_GROUPED'
                         else 'MOOMOO_RAW_PLUS_QUALIFIED_YAHOO_TAIL_PLUS_MOOMOO_REHAB' if provider == 'YAHOO_CHART'
                         else 'MOOMOO_OPEND_RAW_PLUS_REHAB')
                extra_lineage.append({**proof, 'source': label, 'expanded_anchor_manifest': reference,
                    'calendar_lineage': calendar['lineage'], 'price_warnings': gap_map.get(ticker)})
            missing = [{**row, 'expanded_anchor_details': gap_map.get(row['ticker'])}
                       if row['ticker'] in expandable else row for row in missing if row['ticker'] not in accepted]
            features = pd.concat([features, extra], ignore_index=True)
            lineage.extend(extra_lineage)
        except Exception as exc:
            missing = [{**row, 'expanded_anchor_error': str(exc)} if row['ticker'] in expandable else row
                       for row in missing]
    native_gaps = [row['expanded_anchor_details'] for row in missing
                   if (row.get('expanded_anchor_details') or {}).get('reasons') == ['ORIGINAL_RAW_ANCHOR_UNBOUND']]
    if output_dir is not None and str(target).startswith('2026-') and native_gaps:
        try:
            from scripts.research.a2.inference.current_native_prices import build_current_native_features
            native, native_lineage, native_missing = build_current_native_features(
                universe, target, full_sessions, acquisitions, store, rehab_receipt, source, source_ref, native_gaps)
            accepted = set(native.ticker)
            if (not accepted.issubset({row['ticker'] for row in native_gaps}) or native.ticker.duplicated().any()
                    or not pd.to_datetime(native.trade_date).eq(pd.Timestamp(target)).all()
                    or accepted != {row['ticker'] for row in native_lineage}):
                raise ValueError('NATIVE_CURRENT_FEATURE_IDENTITY_MISMATCH')
            failures = {row['ticker']: row for row in native_missing}
            missing = [{**row, 'native_anchor_details': failures.get(row['ticker'])} if row['ticker'] in failures else row
                       for row in missing if row['ticker'] not in accepted]
            features = pd.concat([features, native], ignore_index=True)
            lineage.extend(native_lineage)
            save(Path(output_dir) / 'native_current_price_inputs.json', {'target_date': target,
                'lineage': native_lineage, 'gaps': native_missing, 'training_rows_2026_plus': 0})
        except Exception as exc:
            missing = [{**row, 'native_anchor_error': str(exc)} if row['ticker'] in {item['ticker'] for item in native_gaps}
                       else row for row in missing]
    if features.empty:
        raise ValueError('A2_PRICE_INPUTS_UNAVAILABLE:' + json.dumps(missing[:5], ensure_ascii=False))
    features = features.loc[features.trade_date.eq(pd.Timestamp(target))].merge(
        pd.DataFrame(universe['members'])[['ticker', 'security_id']], on='ticker', validate='one_to_one')
    eligible = np.isfinite(features[list(source.FEATURE_COLUMNS)].to_numpy(float)).all(axis=1)
    missing.extend({'ticker': ticker, 'reason': 'NONFINITE_FROZEN_FEATURE', 'category': 'INSUFFICIENT_HISTORY'}
                   for ticker in features.loc[~eligible, 'ticker'])
    features = features.loc[eligible]
    if len(features) < 20:
        raise ValueError(f'A2_ELIGIBLE_UNIVERSE_BELOW_TOP20:{len(features)}; ' + json.dumps(missing[:5], ensure_ascii=False))
    payload = {'target_date': target, 'feature_rows': features[['security_id', 'ticker', *source.FEATURE_COLUMNS]].to_dict('records'),
        'universe_id': universe['universe_id'], 'vintage_id': datetime.now(timezone.utc).isoformat()}
    rows = list(run_alpha_single_date(target, payload, component, module_loader=load_module))
    sources = {row['ticker']: row['source'] for row in lineage}
    for row in rows:
        row['source'] = sources[row['ticker']]
    if output_dir is not None:
        # Raw32 mathematics is reusable; this snapshot carries no consensus-pool
        # claim. The independent consensus owner binds its own exact dated pool.
        try:
            save_frozen_raw32_features(output_dir, features, target, source_ref, component)
        except Exception as exc:
            save(Path(output_dir) / 'frozen_raw32_features_binding.json',
                 {'status': 'BLOCKED', 'signal_date': target, 'error': str(exc)})
        # A failure in the optional portfolio policies must not invalidate A2.
        try:
            save_selected_hgb_features(output_dir, features, prices, rows, target, sessions, lineage=lineage)
        except Exception as exc:
            save(Path(output_dir) / 'selected_hgb_features_binding.json',
                 {'status': 'BLOCKED', 'signal_date': target, 'error': str(exc)})
    return rows, lineage, missing


def save_frozen_raw32_features(output_dir, features, target, feature_source_ref, component):
    """Date-bounded mathematics snapshot; pool and execution authority stay separate."""
    import hashlib
    import numpy as np
    import pandas as pd
    from scripts.research.a2.training.stateful_inputs import FEATURES
    from scripts.storage.storage_r2a import assert_write_path
    day = pd.Timestamp(target)
    required = ['trade_date', 'ticker', 'security_id', *FEATURES]
    current = features.loc[pd.to_datetime(features.trade_date).eq(day), required].copy().reset_index(drop=True)
    if current.empty or current.ticker.duplicated().any() or current.security_id.isna().any():
        raise ValueError('FROZEN_RAW32_SNAPSHOT_IDENTITY_REQUIRED')
    if not np.isfinite(current[list(FEATURES)].to_numpy(float)).all():
        raise ValueError('FROZEN_RAW32_SNAPSHOT_FINITE_REQUIRED')
    path = Path(output_dir) / 'frozen_raw32_features.parquet'
    assert_write_path(path, 'daily')
    if path.exists():
        if not pd.read_parquet(path).equals(current):
            raise ValueError('FROZEN_RAW32_PRESERVE_EXISTING_SNAPSHOT')
    else:
        current.to_parquet(path, index=False, compression='zstd')
    from scripts.daily_recommendation_inputs import MODEL_SHA256
    model_sha = MODEL_SHA256
    reference = {'schema': 'FROZEN_RAW32_DAILY_MATH_INPUT_V1', 'status': 'READY',
        'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'signal_date': target, 'rows': len(current), 'columns': required,
        'feature_source_ref': {k: feature_source_ref[k] for k in ('path', 'sha256')},
        'frozen_model_sha256': model_sha, 'valuation_basis': 'SIGNAL_CLOSE',
        'pool_authority': 'ORIGINAL_RAW_A2_ONLY_NO_CONSENSUS_CLAIM', 'model_fit_calls': 0}
    save(Path(output_dir) / 'frozen_raw32_features_binding.json', reference)
    return reference


def update_consensus_paper_inputs(paths, result, run_dir, *, reuse_only=False, allow_raw_recovery=True):
    """Independent no-fit source stage under the existing daily updater lock."""
    try:
        snapshot = result.get('frozen_raw32_features', {})
        if snapshot.get('status') != 'READY' or snapshot.get('signal_date') != result.get('data_date'):
            raise ValueError('CURRENT_CONSENSUS_DECLARED_RAW32_SNAPSHOT_REQUIRED')
        if not Path(snapshot['path']).resolve().is_relative_to(paths.daily_root.resolve()):
            raise ValueError('CURRENT_CONSENSUS_RAW32_DAILY_STORAGE_REQUIRED')
        if reuse_only:
            # A same-day recovery may extend an accepted publication, but must
            # never create/rerank the original input surface as a side effect.
            from scripts.research.a2.inference.consensus_paper import load_publication
            base, _ = load_publication(paths, result['data_date'], datetime.now(timezone.utc).isoformat())
            if base.get('status') != 'READY':
                raise ValueError('CURRENT_CONSENSUS_READY_BASE_REQUIRED_FOR_RESUME')
        from scripts.research.a2.inference.consensus_current_inputs import refresh_current_inputs
        return refresh_current_inputs(paths, current_report=result, run_dir=run_dir,
            **({"reuse_only": True} if reuse_only else {}),
            **({"allow_raw_recovery": False} if not allow_raw_recovery else {}))
    except (ImportError, OSError, ValueError, KeyError, TypeError) as exc:
        return {'status': 'BLOCKED', 'signal_date': result.get('data_date'),
                'reason': str(exc), 'model_fit_calls': 0, 'broker_action_allowed': False}


def save_selected_hgb_features(output_dir, features, prices, rows, target, sessions, *, lineage=None):
    """Bind the original Top40 to observed daily returns at signal close.

    The ten return slots use the actual session calendar. Missing slots stay
    missing, so a gap cannot shift an older observation into a newer feature.
    """
    import hashlib
    import numpy as np
    import pandas as pd
    from scripts.research.a2.portfolio.selected_hgb import BASE_FEATURES, complete_close_inputs

    top = pd.DataFrame([row for row in rows if row['rank'] <= 40])
    if len(top) != 40 or top.ticker.duplicated().any() or set(top['rank']) != set(range(1, 41)):
        raise ValueError('SELECTED_HGB_REQUIRES_COMPLETE_TOP40')
    day = pd.Timestamp(target)
    calendar = pd.DatetimeIndex(sorted({pd.Timestamp(value) for value in sessions if pd.Timestamp(value) <= day}))
    if len(calendar) < 11 or calendar[-1] != day:
        raise ValueError('SELECTED_HGB_RETURN_CALENDAR_INCOMPLETE')
    slot_dates = calendar[-11:]
    snapshot = top[['ticker', 'rank', 'score']].rename(columns={'rank': 'raw_rank', 'score': 'raw_score'})
    current = features[['ticker', *BASE_FEATURES]].copy()
    if current.ticker.duplicated().any():
        raise ValueError('SELECTED_HGB_DUPLICATE_CURRENT_FEATURES')
    snapshot = snapshot.merge(current, on='ticker', how='left', validate='one_to_one')
    if lineage is not None:
        prices = complete_close_inputs(prices, lineage, snapshot.ticker.tolist(), target, sessions)
    observed = prices.loc[pd.to_datetime(prices.trade_date).le(day)].copy()
    observed['trade_date'] = pd.to_datetime(observed.trade_date)
    if observed.duplicated(['ticker', 'trade_date']).any():
        raise ValueError('SELECTED_HGB_DUPLICATE_CLOSE')
    for index in range(10):
        snapshot[f'lag_ret_{index:02d}'] = np.nan
    for ticker, group in observed.groupby('ticker'):
        if ticker not in set(snapshot.ticker):
            continue
        closes = group.set_index('trade_date')['close'].reindex(slot_dates)
        returns = closes.pct_change(fill_method=None)
        for index in range(10):
            snapshot.loc[snapshot.ticker.eq(ticker), f'lag_ret_{index:02d}'] = returns.iloc[-1-index]
    snapshot['trade_date'] = day
    path = Path(output_dir) / 'selected_hgb_features.parquet'
    snapshot.to_parquet(path, index=False)
    reference = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                 'signal_date': target, 'valuation_basis': 'SIGNAL_CLOSE', 'rows': 40,
                 'status': 'READY' if np.isfinite(snapshot[[*BASE_FEATURES, *(f'lag_ret_{i:02d}' for i in range(10))]].to_numpy(float)).all() else 'INCOMPLETE'}
    save(Path(output_dir) / 'selected_hgb_features_binding.json', reference)
    return reference


def update_selected_strategies(paths, result, run_dir, progress=emit, *, held_price_reuse=None):
    """Apply the two user-selected frozen policies independently of A2."""
    if result.get('status') != 'READY':
        return {'status': 'SKIPPED', 'reason': 'RECOMMENDATION_NOT_READY'}
    primary_error = fallback_error = None
    try:
        from scripts.research.a2.portfolio.selected_hgb import build_package, active_policy, DIRECT_POLICY
        source_path = run_dir / 'recommendation_source.json'
        if not source_path.exists():
            save(source_path, {**result, 'report_path': str(source_path)})
        progress('应用 HGB 对角风险与因子／收缩风险策略，生成收盘目标仓位和现金。')
        repair_ref = _validated_repair_ref(result, source_path) if result.get('repair_lineage') else None
        policy, active_output = active_policy(paths)
        output_path = Path(os.environ.get('USTQ_SELECTED_HGB_PACKAGE') or active_output).expanduser().resolve()
        if policy == DIRECT_POLICY:
            from scripts.research.a2.evaluation.hgb_policy_alignment import refresh_direct
            package = refresh_direct(paths, source_path, output_path, progress,
                **({"held_price_reuse": held_price_reuse} if held_price_reuse is not None else {}))
        else:
            package = build_package(paths, current_report_path=source_path, progress=progress)
            from scripts.research.a2.evaluation.selected_performance_update import (
                refresh_selected_performance, publish_current_preserving_replay)
            try:
                package = refresh_selected_performance(paths, package, source_path, output_path, progress,
                    **({"held_price_reuse": held_price_reuse} if held_price_reuse is not None else {}),
                    **({"snapshot_repair": repair_ref} if repair_ref is not None else {}))
            except Exception as primary_exc:
                primary_error = str(primary_exc)
                try:
                    publish_current_preserving_replay(package, output_path, paths=paths,
                        **({"snapshot_repair": repair_ref} if repair_ref is not None else {}))
                except Exception as fallback_exc:
                    fallback_error = str(fallback_exc)
                # A fallback failure must not replace the original replay guard.
                raise
        applications = {name: item['application'] for name, item in package['strategies'].items()}
        ready = all(item['status'] == 'READY' and item['signal_date'] == result['data_date']
                    for item in applications.values())
        extension = package['performance_extension']
        ready = ready and extension['status'] == 'READY' and package['performance_period']['end'] == result['data_date']
        return {'status': 'READY' if ready else 'PARTIAL', 'policy_id': policy,
                'report_path': str(output_path),
                'performance_end_date': package['performance_period']['end'],
                'requested_end_date': extension['requested_end_date'],
                'blocked_next': extension['blocked_next'],
              'strategies': {name: {key: item.get(key) for key in ('status', 'signal_date', 'account_basis', 'reason')}
                             for name, item in applications.items()}}
    except Exception as exc:
        progress('原 A2 更新已保留；HGB 目标或共同绩效同步未完成，查看独立状态与实际曲线截止日。')
        # Keep the original error full; bound only added protocol diagnostics.
        diagnostics = {name: value[:2048 - len(' [diagnostic shortened]')] + ' [diagnostic shortened]' if len(value) > 2048 else value
                       for name, value in (('primary_error', primary_error), ('fallback_error', fallback_error))
                       if value is not None}
        return {'status': 'BLOCKED', 'error': str(exc), **diagnostics}


def update_demo_performance(paths, result, run_dir, progress=emit):
    """Refresh the original demo's ledgers after inference, without changing alpha.

    The immutable source avoids a circular report hash when the final daily
    report receives the resulting performance reference. A failed replay leaves
    the producer's last verified manifest intact and is reported independently.
    """
    if result.get('status') != 'READY':
        return {'status': 'SKIPPED', 'reason': 'RECOMMENDATION_NOT_READY'}
    source_path = run_dir / 'recommendation_source.json'
    snapshot = {**result, 'report_path': str(source_path)}
    save(source_path, snapshot)
    progress('按原持仓、次日开盘执行与交易成本规则，更新展示 DEMO 的绩效与风险。')
    failed_manifest = None
    try:
        from scripts.research.a2.evaluation.demo_performance import canonical_manifest, refresh_demo_performance
        prior_pointer = paths.daily_root / 'A2_updated_research/latest.json'
        prior_manifest = None
        if prior_pointer.exists():
            prior_manifest, _ = canonical_manifest(prior_pointer)
        repair_ref = _validated_repair_ref(result, source_path) if result.get('repair_lineage') else None
        pending_repair = None
        if repair_ref is not None and prior_manifest is not None:
            prior_metadata = json.loads(Path(prior_manifest).read_text(encoding='utf-8'))
            if prior_metadata.get('performance_end_date') == result['data_date']:
                pending_repair = Path(repair_ref['path'])
        manifest = refresh_demo_performance(
            paths,
            historical_manifest_path=paths.daily_root / 'A2_historical_top40/latest.json',
            current_report_path=source_path,
            prior_verified_performance_manifest_path=prior_manifest,
            reuse_same_end_performance=True,
            retain_qualified_prior_open=True,
            **({'pending_signal_revision_path': pending_repair} if pending_repair is not None else {}),
            progress=progress,
        )
        if manifest.get('status') not in {'READY', 'PARTIAL'} or not manifest.get('report_path'):
            failed_manifest = manifest.get('report_path')
            raise ValueError(manifest.get('error') or 'UPDATED_RESEARCH_MANIFEST_NOT_READY')
        summary = {key: manifest[key] for key in (
            'status', 'run_id', 'report_path', 'generated_at', 'ranking_end_date',
            'performance_end_date') if key in manifest}
        summary['source_report'] = str(source_path)
        # RX is independent: a failure must never roll back verified A2.
        try:
            from scripts.research.a2.evaluation.demo_rx_performance import refresh_rx_performance
            from scripts.research.a2.evaluation.demo_performance import digest as performance_digest
            rx = refresh_rx_performance(paths, manifest['ranking_manifest']['path'], source_path,
                manifest['report_path'], paths.daily_root / 'A2_updated_research_rx/runs' / manifest['run_id'])
            if (rx.get('status') in {'READY', 'PARTIAL'} and rx.get('outputs')
                    and rx.get('parent_a2_manifest', {}).get('sha256') == performance_digest(manifest['report_path'])):
                save(paths.daily_root / 'A2_updated_research_rx/latest.json', rx)
            summary['rx'] = {key: rx[key] for key in ('status', 'report_path', 'error', 'performance_end_date') if key in rx}
        except Exception as rx_exc:
            summary['rx'] = {'status': 'BLOCKED', 'error': str(rx_exc)}
        if summary['rx'].get('status') == 'BLOCKED':
            progress('A2 绩效已更新；RX 输入尚未通过验证，保留独立错误记录。')

        progress('展示 DEMO 的排名、持仓和绩效已同步；未执行的新推荐会标为待执行。')
        return summary
    except Exception as exc:
        progress('推荐已生成，但绩效更新未完成；请查看已保存的绩效日期与错误详情。')
        return {'status': 'BLOCKED', 'error': str(exc), 'source_report': str(source_path),
                **({'report_path': failed_manifest} if failed_manifest else {})}


def _performance_worker(paths, kind, source_path, expected_sha256):
    """Fixed actions over the parent's immutable source; never reacquire its lock."""
    if kind not in {'raw', 'selected'}:
        raise ValueError('UNKNOWN_PERFORMANCE_WORKER')
    source_path = Path(source_path).resolve()
    runs = (paths.daily_root / 'A2_today_recommendation/runs').resolve()
    if source_path.name != 'recommendation_source.json' or source_path.parent.parent != runs:
        raise ValueError('PERFORMANCE_SOURCE_OUTSIDE_CANONICAL_RUN')
    if source_path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError('PERFORMANCE_SOURCE_HASH_OR_SIZE_INVALID')
    payload = source_path.read_bytes()
    if len(payload) > 10 * 1024 * 1024 or hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError('PERFORMANCE_SOURCE_HASH_OR_SIZE_INVALID')
    result = json.loads(payload.decode('utf-8'))
    if result.get('status') != 'READY' or result.get('report_path') != str(source_path):
        raise ValueError('PERFORMANCE_SOURCE_NOT_READY_OR_BOUND')
    action = update_demo_performance if kind == 'raw' else update_selected_strategies
    summary = action(paths, result, source_path.parent)
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError('PERFORMANCE_SOURCE_CHANGED_DURING_WORKER')
    return summary


def read_worker_result(log):
    """Both daily phases accept exactly one bounded terminal response."""
    summary = None
    with Path(log).open(encoding='utf-8') as stream:
        while line := stream.readline(1024 * 1024 + 1):
            if len(line) > 1024 * 1024:
                raise ValueError('PERFORMANCE_WORKER_RESPONSE_TOO_LARGE')
            try: event = json.loads(line)
            except ValueError: continue
            if isinstance(event, dict) and event.get('event') == 'performance_result':
                if summary is not None or not isinstance(event.get('result'), dict):
                    raise ValueError('PERFORMANCE_WORKER_RESPONSE_INVALID')
                summary = event['result']
    if summary is None or summary.get('status') not in {'READY', 'PARTIAL', 'BLOCKED', 'SKIPPED'}:
        raise ValueError('PERFORMANCE_WORKER_RESPONSE_MISSING')
    return summary


def update_performance_isolated(paths, result, run_dir, progress=emit, *, reuse_source=False,
                                verified_summaries=None, log_dir=None):
    """Original producers run sequentially over accepted immutable input bytes."""
    source_path = run_dir / 'recommendation_source.json'
    if not reuse_source:
        snapshot = {**result, 'report_path': str(source_path)}
        if source_path.exists():
            if json.loads(source_path.read_text(encoding='utf-8')) != snapshot:
                raise ValueError('PERFORMANCE_SOURCE_ALREADY_ACCEPTED')
        else: save(source_path, snapshot)
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    summaries = []
    for kind in ('raw', 'selected'):
        if verified_summaries and kind in verified_summaries:
            summaries.append(verified_summaries[kind]); continue
        progress('低内存更新：' + ('Raw A2 绩效与参考曲线。' if kind == 'raw' else 'HGB 目标与三策略图表。'))
        log = (log_dir or run_dir) / (kind + '_performance_worker.log')
        try:
            process = run_provider(paths, 'scripts.daily_recommendation',
                ['--performance-worker', kind, '--source-report', source_path,
                 '--source-sha256', source_sha], log)
            if process['exit_code'] != 0:
                raise RuntimeError(process.get('error') or 'PERFORMANCE_WORKER_EXIT:' + str(process['exit_code']))
            summary = read_worker_result(log)
            if hashlib.sha256(source_path.read_bytes()).hexdigest() != source_sha:
                raise ValueError('PERFORMANCE_SOURCE_CHANGED_DURING_WORKER')
        except Exception as exc:
            summary = {'status': 'BLOCKED', 'error': str(exc), 'log_path': str(log)}
        summaries.append(summary)
    return tuple(summaries)


def _verify_nested_refs(document):
    from scripts.research.a2.evaluation.three_strategy_extension import verify_refs
    refs = {}
    def visit(value):
        if isinstance(value, dict):
            if 'path' in value and 'sha256' in value:
                identity = (str(Path(value['path']).resolve()), value['sha256'])
                refs[identity] = {'path': identity[0], 'sha256': identity[1]}
            for child in value.values(): visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
    visit(document); verify_refs(list(refs.values()))


def _accepted_recommendation_source(paths, latest, binding, calendar, now):
    """Validate accepted input identity, model, availability and original receipts."""
    from scripts.research.a2.evaluation.three_strategy_extension import reference, verify_refs
    runs = (paths.daily_root / 'A2_today_recommendation/runs').resolve()
    report = Path(latest['report_path']).resolve()
    if report.name != 'report.json' or report.parent.parent != runs:
        raise ValueError('RESUME_REPORT_OUTSIDE_CANONICAL_RUN')
    source = report.parent / 'recommendation_source.json'
    if source.stat().st_size > 10 * 1024 * 1024: raise ValueError('RESUME_SOURCE_TOO_LARGE')
    ref = reference(source)
    if latest.get('accepted_source') is not None and latest['accepted_source'] != ref:
        raise ValueError('RESUME_ACCEPTED_SOURCE_CHANGED')
    document = json.loads(source.read_text(encoding='utf-8'))
    model = next(item for item in binding['components']['ALPHA']['artifacts'] if item['artifact_id'] == 'model')
    target = calendar['target_date']
    generated = datetime.fromisoformat(document['generated_at'].replace('Z', '+00:00'))
    close = datetime.fromisoformat(target).replace(hour=16, tzinfo=ZoneInfo('America/New_York'))
    if (document.get('status') != 'READY' or document.get('report_path') != str(source)
            or document.get('data_date') != target or not '2026-01-01' <= target < '2027-01-01'
            or document.get('model_sha256') != model['sha256'] or latest.get('model_sha256') != model['sha256']
            or generated.tzinfo is None or not close <= generated <= now or len(document.get('rows', [])) != 20
            or document.get('run_id') != report.parent.name
            or document.get('input_manifest_sha256') != latest.get('input_manifest_sha256')
            or latest.get('rows') != document.get('rows')
            or latest.get('ranked_rows') != document.get('ranked_rows')):
        raise ValueError('RESUME_SOURCE_IDENTITY_OR_AVAILABILITY_INVALID')
    if latest.get('accepted_source') is None:
        from scripts.research.a2.portfolio.selected_hgb import active_policy
        from apps.demo_console.adapters.selected_strategies_reader import load_package
        _, package_path = active_policy(paths)
        package = load_package(package_path)
        if package['source_refs']['current/report.json'] != ref:
            raise ValueError('RESUME_LEGACY_SOURCE_NOT_ACCEPTED_BY_CURRENT_POLICY')
    lineage = json.loads((source.parent / 'input_lineage.json').read_text(encoding='utf-8'))
    if hashlib.sha256(json.dumps(lineage, sort_keys=True).encode()).hexdigest() != document['input_manifest_sha256']:
        raise ValueError('RESUME_INPUT_LINEAGE_CHANGED')
    _verify_nested_refs(lineage)
    features = document['selected_hgb_features']
    if features.get('status') != 'READY' or features.get('signal_date') != target:
        raise ValueError('RESUME_HGB_FEATURE_BINDING_INVALID')
    universe = document['universe']; member = Path(universe['report_path']).parent / 'mapped_members.parquet'
    verify_refs([features, {'path': str(member), 'sha256': universe['universe_members_sha256']}])
    _verify_nested_refs({key: universe[key] for key in ('registry', 'identity_source', 'identity_artifacts') if key in universe})
    rehab = json.loads((source.parent / 'rehab_receipt.json').read_text(encoding='utf-8'))
    if rehab.get('target_date') != target or rehab.get('status') != 'READY':
        raise ValueError('RESUME_REHAB_DATE_OR_STATUS_INVALID')
    _verify_nested_refs(rehab)
    if latest.get('accepted_inputs'): verify_refs(latest['accepted_inputs'])
    return document, ref


def _verified_daily_stage_summaries(paths, source_ref, target, *, diagnostics=None):
    """Read current official publications; stale parent summaries are not authority."""
    from scripts.research.a2.evaluation.demo_performance import canonical_manifest
    from scripts.research.a2.evaluation.three_strategy_extension import reference
    result = {}
    try:
        path, _ = canonical_manifest(paths.daily_root / 'A2_updated_research/latest.json')
        raw = json.loads(path.read_text(encoding='utf-8-sig'))
        if (raw.get('status') not in {'READY', 'PARTIAL'} or raw.get('ranking_end_date') != target
                or raw.get('performance_end_date', '') < target or source_ref not in raw.get('recommendation_reports', [])):
            raise ValueError('RESUME_RAW_SOURCE_OR_DATE_NOT_CURRENT')
        _verify_nested_refs({key: raw.get(key) for key in ('outputs', 'authority_refs', 'input_refs', 'recommendation_reports', 'price_inputs')})
        result['raw'] = {key: raw[key] for key in ('status', 'run_id', 'report_path', 'ranking_end_date', 'performance_end_date')}
        result['raw'].update(action='REUSED_VERIFIED_CURRENT', source_report=source_ref['path'])
    except Exception as exc:
        if diagnostics is not None: diagnostics['raw'] = {'status': 'NOT_REUSED', 'reason': str(exc)}
    try:
        from scripts.research.a2.portfolio import selected_hgb
        policy, package_path = selected_hgb.active_policy(paths)
        package, manifest, _ = _execution_selected_manifest({'package': reference(package_path), 'policy_id': policy})
        if (package.get('policy_id', selected_hgb.LEGACY_POLICY) != policy
                or manifest.get('policy_id', selected_hgb.LEGACY_POLICY) != policy):
            raise ValueError('RESUME_HGB_ACTIVE_POLICY_CHANGED')
        if policy == selected_hgb.LEGACY_POLICY:
            selected_hgb.verify_frozen(selected_hgb._source_root(paths))
        if (package['source_refs']['current/report.json'] != source_ref
                or any(package['strategies'][name]['application'].get('status') != 'READY'
                       or package['strategies'][name]['application'].get('signal_date') != target
                       for name in ('HGB_DIAG_5', 'HGB_FACTOR_5'))
                or manifest['performance_period']['end'] < target):
            raise ValueError('RESUME_HGB_SOURCE_OR_DATE_NOT_CURRENT')
        _verify_nested_refs(manifest['strategies'])
        result['selected'] = {'status': 'READY', 'policy_id': policy, 'report_path': str(package_path),
            'performance_end_date': manifest['performance_period']['end'], 'action': 'REUSED_VERIFIED_CURRENT',
            'strategies': {name: {key: package['strategies'][name]['application'].get(key)
                                 for key in ('status', 'signal_date', 'account_basis', 'reason')}
                           for name in ('HGB_DIAG_5', 'HGB_FACTOR_5')}}
    except Exception as exc:
        if diagnostics is not None: diagnostics['selected'] = {'status': 'NOT_REUSED', 'reason': str(exc)}
    return result


def _delivery_completion(result):
    target = result.get('data_date', ''); raw = result.get('performance_update', {})
    selected = result.get('selected_strategies_update', {}); benchmark = result.get('benchmark_update', {})
    def current_end(value):
        return isinstance(value, str) and bool(target) and target <= value < '2027-01-01'
    strategies = selected.get('strategies', {})
    targets_ready = isinstance(strategies, dict) and all(
        isinstance(strategies.get(name), dict) and strategies[name].get('status') == 'READY'
        and strategies[name].get('signal_date') == target for name in ('HGB_DIAG_5', 'HGB_FACTOR_5'))
    required = {'recommendation': result.get('status') == 'READY',
        'raw_research': raw.get('status') in {'READY', 'PARTIAL'} and raw.get('ranking_end_date') == target and current_end(raw.get('performance_end_date')),
        'hgb_targets_and_charts': selected.get('status') == 'READY' and targets_ready and current_end(selected.get('performance_end_date')),
        'benchmarks': benchmark.get('status') == 'READY' and current_end(benchmark.get('available_end_date'))}
    return {'schema': 'A2_DAILY_COMPLETION_V1', 'status': 'READY' if target and all(required.values()) else 'PARTIAL',
        'target_date': target, 'required_stages': required, 'limitations': {'coverage': result.get('coverage', {}),
        'rx': raw.get('rx', {'status': 'UNVERIFIED', 'reason': 'INDEPENDENT_RX_NOT_REPLAYED'})}}


def resume_published_update(paths, binding, calendar, now, progress=emit):
    """Recover only missing branches under the original lock; never rerank accepted inputs."""
    from scripts.research.a2.evaluation.three_strategy_extension import reference
    from scripts.research.a2.evaluation.hgb_policy_alignment import frozen_contract
    latest_path = paths.daily_root / 'A2_today_recommendation/latest.json'
    if not latest_path.exists(): return None
    if latest_path.stat().st_size > 10 * 1024 * 1024: raise ValueError('RESUME_LATEST_TOO_LARGE')
    latest = json.loads(latest_path.read_text(encoding='utf-8'))
    if latest.get('status') != 'READY' or latest.get('data_date') != calendar['target_date']: return None
    frozen_contract(paths)
    source, source_ref = _accepted_recommendation_source(paths, latest, binding, calendar, now)
    run_dir = Path(source_ref['path']).parent
    work = run_dir / 'recovery' / (now.strftime('%Y%m%dT%H%M%S') + '_' + uuid.uuid4().hex[:8]);work.mkdir(parents=True, exist_ok=False)
    result = {**latest, 'accepted_source': source_ref, 'recovery': {'action': 'RESUME_ACCEPTED_INPUTS',
        'work_dir': str(work), 'acquisition_calls': 0, 'inference_calls': 0, 'broker_calls': 0}}
    progress('同一交易日恢复：核验已接受的输入包，复用合格结果，只恢复未完成阶段。')
    save(work / 'state.json', {'status': 'RUNNING', 'accepted_source': source_ref})
    # The original source remains sealed. Optional paper inputs have their own
    # byte-verified reuse path and otherwise report their own blocker.
    try:
        result['consensus_paper_inputs'] = update_consensus_paper_inputs(paths, source, run_dir, reuse_only=True)
    except Exception as exc:
        result['consensus_paper_inputs'] = {'status': 'BLOCKED', 'signal_date': source['data_date'],
            'reason': (type(exc).__name__ + ':' + str(exc))[:1024],
            'model_fit_calls': 0, 'broker_action_allowed': False}
    diagnostics = {}
    verified = _verified_daily_stage_summaries(paths, source_ref, source['data_date'], diagnostics=diagnostics)
    result['recovery']['reuse_diagnostics'] = diagnostics
    try:
        result['performance_update'], result['selected_strategies_update'] = update_performance_isolated(
            paths, source, run_dir, progress, reuse_source=True, verified_summaries=verified, log_dir=work)
    except Exception as exc:
        result['performance_update'] = {'status': 'BLOCKED', 'error': str(exc)}
        result['selected_strategies_update'] = {'status': 'BLOCKED', 'error': str(exc)}
        result['recovery'].setdefault('errors', {})['performance'] = str(exc)
    try:
        from scripts.storage.storage_r2a import DataStore
        result['benchmark_update'] = refresh_daily_benchmarks(paths, work, source['data_date'], calendar, DataStore(), progress)
    except Exception as exc:
        result['benchmark_update'] = {'status': 'BLOCKED', 'error': str(exc)}
        result['recovery'].setdefault('errors', {})['benchmarks'] = str(exc)
    # Keep a traceable prior limitation; recovery must never claim a new RX success.
    if 'rx' not in result['performance_update']:
        prior_rx = latest.get('performance_update', {}).get('rx')
        if isinstance(prior_rx, dict):
            result['performance_update']['rx'] = {
                'status': 'BLOCKED' if prior_rx.get('status') == 'BLOCKED' else 'UNVERIFIED',
                'qualification': 'PRIOR_REPORTED_NOT_REVALIDATED', 'prior_snapshot': prior_rx,
                'reported_at': latest.get('generated_at'), 'parent_report': reference(run_dir / 'report.json')}
    if reference(source_ref['path']) != source_ref: raise ValueError('RESUME_ACCEPTED_SOURCE_CHANGED_DURING_RECOVERY')
    result['recovery']['reused_stages'] = sorted(verified)
    result['completion'] = _delivery_completion(result);result['generated_at'] = datetime.now(timezone.utc).isoformat()
    result['message'] = ('本交易日推荐、Raw／HGB 图表和基准已核验；独立输入缺口见报告。'
        if result['completion']['status'] == 'READY' else '推荐保留；部分日更阶段尚未完成，查看分支状态与截止日。')
    save(work / 'state.json', {'status': result['completion']['status'], 'accepted_source': source_ref, 'completion': result['completion'], 'recovery': result['recovery']})
    # UI/progress recovery must not change a live plan's accepted parent-report identity.
    result['recovery']['report_path'] = str(work / 'report.json')
    save(work / 'report.json', result)
    return result


def _infer_recommendation(result, binding, universe, target, calendar, prediction_acquisitions, store, rehab, run_dir, notes):
    """Original frozen inference/result writer, also used by routing requalification."""
    rows, lineage, missing = predict_current(binding, universe, target, calendar['sessions'], prediction_acquisitions, store, rehab,
        output_dir=run_dir)
    deferred_notes = {note['ticker']: note for note in notes['deferred']}
    missing = [{**row, 'acquisition_note': {**deferred_notes[row['ticker']],
        'manifest': {key: notes[key] for key in ('path', 'sha256')}}}
        if row['ticker'] in deferred_notes else row for row in missing]
    if len([row for row in rows if row['rank'] <= 20]) != 20:
        raise ValueError('A2_TOP20_CARDINALITY_INVALID')
    import hashlib
    input_hash = hashlib.sha256(json.dumps(lineage, sort_keys=True).encode()).hexdigest()
    result.update(status='READY', rows=[row for row in rows if row['rank'] <= 20],
        ranked_rows=rows, input_manifest_sha256=input_hash,
        coverage={'eligible_count': len(rows), 'mapped_count': len(universe['members']),
                  'excluded_count': len(missing) + universe.get('mapping_gap_count', 0)},
        message='当天 A2 推荐已更新，按可验证的最新股票池与行情生成。')
    selected_binding = run_dir / 'selected_hgb_features_binding.json'
    if selected_binding.exists():
        result['selected_hgb_features'] = json.loads(selected_binding.read_text(encoding='utf-8'))
    raw32_binding = run_dir / 'frozen_raw32_features_binding.json'
    if raw32_binding.exists():
        result['frozen_raw32_features'] = json.loads(raw32_binding.read_text(encoding='utf-8'))
    from scripts.common.storage_paths import resolve
    result['consensus_paper_inputs'] = update_consensus_paper_inputs(resolve(), result, run_dir)
    save(run_dir / 'input_lineage.json', lineage)
    save(run_dir / 'excluded.json', {'price_or_feature_gaps': missing, 'identity_gaps': universe.get('mapping_gaps', [])})


def _publish_recommendation(paths, result, run_dir, root, progress):
    """Original immutable-source and sequential performance publication owner."""
    source_path = run_dir / 'recommendation_source.json'
    save(source_path, {**result, 'report_path': str(source_path)})
    from scripts.research.a2.evaluation.three_strategy_extension import reference
    result['accepted_source'] = reference(source_path)
    result['accepted_inputs'] = [reference(run_dir / name) for name in
        ('input_lineage.json', 'rehab_receipt.json', 'selected_hgb_features_binding.json') if (run_dir / name).is_file()]
    result['phase'] = 'PERFORMANCE_PENDING'
    save(run_dir / 'report.json', result);save(root / 'latest.json', result)
    try:
        result['performance_update'], result['selected_strategies_update'] = update_performance_isolated(
            paths, result, run_dir, progress, reuse_source=True)
    except Exception as exc:
        result['performance_update'] = {'status': 'BLOCKED', 'error': str(exc)}
        result['selected_strategies_update'] = {'status': 'BLOCKED', 'error': str(exc)}
    result['completion'] = _delivery_completion(result)
    result['phase'] = 'COMPLETED' if result['completion']['status'] == 'READY' else 'PARTIAL'
    result['message'] = ('当天推荐、Raw／HGB 图表和基准已同步至最新完成交易日；独立缺口见报告。'
        if result['completion']['status'] == 'READY' else '当天推荐已更新，部分图表或基准未完成；现有曲线保留实际截止日。')
    result['generated_at'] = datetime.now(timezone.utc).isoformat()


def _catalog_input_fingerprint(store):
    """Stream existing index metadata only; never copy or publish price data."""
    import sqlite3
    digest = hashlib.sha256()
    with sqlite3.connect(Path(store.catalog_path).resolve().as_uri() + '?mode=ro', uri=True) as connection:
        for row in connection.execute('SELECT * FROM data_files ORDER BY dataset,ticker,adjustment,path'):
            digest.update(json.dumps(row, ensure_ascii=False, allow_nan=False).encode())
            digest.update(b'\n')
    return digest.hexdigest()


def _validated_repair_ref(result, source_path):
    """Use the original input-repair validator; no parallel repair schema."""
    ref = result.get('repair_lineage')
    if ref is None: return None
    from scripts.research.a2.portfolio import selected_hgb as selected
    from scripts.research.a2.evaluation.three_strategy_extension import reference, verify_refs
    verify_refs([ref])
    parent = result.get('requalification', {}).get('parent_source')
    if not isinstance(parent, dict): raise ValueError('REQUALIFY_PARENT_SOURCE_REQUIRED')
    verify_refs([parent])
    old = json.loads(Path(parent['path']).read_text(encoding='utf-8'))
    if (old.get('status') != 'READY' or old.get('data_date') != result.get('data_date')
            or old.get('model_sha256') != result.get('model_sha256')):
        raise ValueError('REQUALIFY_PARENT_SOURCE_IDENTITY_CHANGED')
    def snapshot(report, report_ref):
        return {'signal_date': report['data_date'], 'source_refs': {
            'current/report.json': report_ref,
            'current/selected_hgb_features.parquet': report['selected_hgb_features']}}
    selected._validate_input_repair(snapshot(result, reference(source_path)), snapshot(old, parent), ref)
    return ref


def _requalify_accepted_inputs(paths, result, run_dir, now, progress):
    """Reapply original qualification to saved inputs; no acquisition or fitting."""
    import pandas as pd
    from scripts import daily_recommendation_inputs as inputs
    from scripts.storage.storage_r2a import DataStore
    from scripts.research.a2.portfolio import selected_hgb as selected
    from apps.demo_console.adapters.selected_strategies_reader import load_package
    from scripts.research.a2.evaluation.hgb_policy_alignment import frozen_contract
    from scripts.research.a2.evaluation.three_strategy_extension import reference, verify_refs
    root = paths.daily_root / 'A2_today_recommendation'
    latest_path = root / 'latest.json'
    frozen_contract(paths)
    binding = inputs.load_frozen_binding(paths.repo_root)
    calendar = inputs.latest_completed_session(binding, now)
    if not latest_path.is_file() or latest_path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError('REQUALIFY_ACCEPTED_LATEST_REQUIRED')
    latest_ref = reference(latest_path)
    latest = json.loads(latest_path.read_text(encoding='utf-8'))
    source, source_ref = _accepted_recommendation_source(paths, latest, binding, calendar, now)
    _verify_nested_refs(source)
    policy, package_path = selected.active_policy(paths)
    if policy != selected.LEGACY_POLICY: raise ValueError('REQUALIFY_ACTIVE_LEGACY_REQUIRED')
    selected.verify_frozen(selected._source_root(paths))
    package_ref = reference(package_path)
    package = load_package(package_path)
    target = calendar['target_date']
    if (package.get('policy_id', selected.LEGACY_POLICY) != policy
            or package.get('source_refs', {}).get('current/report.json') != source_ref
            or any(package['strategies'][sid]['application'].get('status') != 'READY'
                or package['strategies'][sid]['application'].get('signal_date') != target
                for sid in selected.STRATEGY_IDS)):
        raise ValueError('REQUALIFY_CURRENT_POLICY_SOURCE_OR_SIGNAL_CHANGED')
    universe = dict(source['universe'])
    member_path = Path(universe['report_path']).parent / 'mapped_members.parquet'
    universe['members'] = pd.read_parquet(member_path).to_dict('records')
    if (universe.get('status') != 'READY' or universe.get('current') is not True
            or universe.get('inference_ready') is not True or universe.get('target_date') != target
            or len(universe['members']) != universe.get('mapped_member_count')
            or len(universe['members']) < 20):
        raise ValueError('REQUALIFY_ACCEPTED_UNIVERSE_UNQUALIFIED')
    native_count = source.get('native_current_tail', {}).get('result_count', 0)
    acquired = source.get('acquisitions', {})
    routed = prediction_after_native_publication(acquired, source.get('native_market_publication', {}), native_count, target)
    if routed is acquired: raise ValueError('REQUALIFY_NATIVE_PUBLICATION_PROOF_REQUIRED')
    # Both the native proof and every reused raw/rehab/identity reference are
    # accepted originals. Only this in-memory prediction routing view changes.
    rehab_path = Path(source_ref['path']).parent / 'rehab_receipt.json'
    rehab_ref = reference(rehab_path)
    rehab = json.loads(rehab_path.read_text(encoding='utf-8'))
    store = DataStore()
    catalog_before = _catalog_input_fingerprint(store)
    run_dir.mkdir(parents=True, exist_ok=False)
    result.update({key: value for key, value in source.items()
                   if key not in ('run_id', 'report_path', 'generated_at', 'rows', 'ranked_rows',
                                  'input_manifest_sha256', 'selected_hgb_features', 'repair_lineage', 'requalification')})
    result.update(status='BLOCKED', run_id=run_dir.name, report_path=str(run_dir / 'report.json'),
        generated_at=now.isoformat(), data_date=target, rows=[], broker_action_allowed=False,
        requalification={'action': 'INPUT_ROUTING_REQUALIFICATION', 'parent_source': source_ref,
                         'acquisition_calls': 0, 'model_fit_calls': 0, 'parameter_search_count': 0,
                         'interpretation': 'Engineering recovery using already saved inputs; not a new historical PIT forecast.'})
    try:
        progress('仅重资格已接受的保存输入：原模型、原资格门、零下载、零拟合。')
        (run_dir / 'rehab_receipt.json').write_bytes(rehab_path.read_bytes())
        _infer_recommendation(result, binding, universe, target, calendar, routed, store, rehab,
                              run_dir, source.get('acquisition_notes', {'deferred': []}))
        features = result.get('selected_hgb_features', {})
        if features.get('status') != 'READY' or features.get('signal_date') != target:
            raise ValueError('REQUALIFY_HGB_FEATURES_NOT_READY')
        _accepted_recommendation_source(paths, latest, binding, calendar, now)
        _verify_nested_refs(source)
        _verify_nested_refs(json.loads((run_dir / 'input_lineage.json').read_text(encoding='utf-8')))
        verify_refs([latest_ref, package_ref, rehab_ref, features])
        if selected.active_policy(paths) != (policy, package_path):
            raise ValueError('REQUALIFY_ACTIVE_POLICY_CHANGED_DURING_INFERENCE')
        if _catalog_input_fingerprint(store) != catalog_before:
            raise ValueError('REQUALIFY_INPUT_CATALOG_CHANGED_DURING_INFERENCE')
        audit = {'schema': 'A2_OFFLINE_INPUT_REPAIR_V1', 'status': 'INPUTS_VERIFIED',
            'run_id': run_dir.name, 'target_date': target, 'reason': 'INPUT_ROUTING_REQUALIFICATION',
            'network_requests_this_run': 0, 'model_fit_count': 0, 'parameter_search_count': 0,
            'old_date_keys_retained': True, 'old_rows_unchanged': True,
            'unrelated_current_keys_unchanged': True, 'parent_inputs': [source_ref, rehab_ref],
            'catalog_metadata_before_sha256': catalog_before, 'catalog_metadata_after_sha256': catalog_before,
            'evidence': 'All accepted source/input references reverified; original data index metadata exact before/after; no input publisher invoked.'}
        save(run_dir / 'repair_lineage.json', audit)
        result['repair_lineage'] = reference(run_dir / 'repair_lineage.json')
        result['generated_at'] = datetime.now(timezone.utc).isoformat()
        del store, universe, routed, acquired, package
        import gc
        gc.collect()
        _publish_recommendation(paths, result, run_dir, root, progress)
    except Exception as exc:
        result.update(status='BLOCKED', rows=[], message=str(exc), generated_at=datetime.now(timezone.utc).isoformat())
        save(run_dir / 'report.json', result)
        return result  # An input/qualification failure cannot replace accepted latest.
    save(run_dir / 'report.json', result)
    save(root / 'latest.json', result)
    save(root / 'history' / (run_dir.name + '.json'), result)
    return result


def run_update(paths, execute=True, emit_progress=emit, *, refresh_data=False, requalify_inputs=False):
    from scripts import daily_recommendation_inputs as inputs
    from scripts.storage.top20_quota_plan import build_top20_quota_plan
    from scripts.storage.storage_r2a import DataStore
    from scripts.storage.manage_data import status, acquisition_tickers, read_catalog
    now = datetime.now(timezone.utc)
    result = {'status': 'BLOCKED', 'generated_at': now.isoformat(), 'recommendation_date': now.astimezone(ZoneInfo('Asia/Tokyo')).date().isoformat(),
        'data_date': '', 'model_id': 'A2_HGB', 'rows': [], 'message': '', 'broker_action_allowed': False}
    root = paths.daily_root / 'A2_today_recommendation'
    run_id = now.strftime('%Y%m%dT%H%M%S') + '_' + uuid.uuid4().hex[:8]
    run_dir = root / 'runs' / run_id
    if requalify_inputs and (not execute or refresh_data):
        raise ValueError('REQUALIFY_REQUIRES_EXECUTE_WITHOUT_REFRESH')
    with single_update(root):
        if requalify_inputs:
            return _requalify_accepted_inputs(paths, result, run_dir, now, emit_progress)
        # This invocation has one fixed as-of time. Reuse its verified binding
        # and calendar if the recovery probe finds no applicable same-day source.
        binding = calendar = None
        if execute and not refresh_data and (root / 'latest.json').exists():
            binding = inputs.load_frozen_binding(paths.repo_root)
            calendar = inputs.latest_completed_session(binding, now)
            recovered = resume_published_update(paths, binding, calendar, now, emit_progress)
            if recovered is not None: return recovered
        run_dir.mkdir(parents=True, exist_ok=False)
        result.update(run_id=run_id, report_path=str(run_dir / 'report.json'))
        try:
            emit_progress('核对冻结 A2 模型、交易日及最新可靠 Top20 / Top40 记录。')
            if binding is None:
                binding = inputs.load_frozen_binding(paths.repo_root)
            model = next(item for item in binding['components']['ALPHA']['artifacts'] if item['artifact_id'] == 'model')
            result['model_sha256'] = model['sha256']
            if calendar is None:
                calendar = inputs.latest_completed_session(binding, now)
            target = result['data_date'] = calendar['target_date']
            universe = inputs.load_bound_universe(binding, target)
            if execute:
                from scripts.daily_recommendation_universe import refresh_universe
                emit_progress('按既有机构和证券注册表，更新最新已披露 13F 股票池。')
                universe = refresh_universe(paths, target, run_dir, execute=True)
                result['universe'] = {key: value for key, value in universe.items() if key != 'members'}
                if not universe.get('current') or not universe.get('members'):
                    raise ValueError(universe.get('reason') or 'CURRENT_UNIVERSE_EMPTY_OR_UNQUALIFIED')
            history = inputs.load_priority_history(paths.backtest_root / 'research/a2/demo_2026_calendar_replay', root / 'history', model['sha256'])
            store = DataStore()
            # One ephemeral metadata capture for planning; publication consumers
            # below re-read the catalog after actual acquisition.
            catalog_snapshot = read_catalog(store)
            catalog = status(store, catalog_snapshot)
            result['catalog_before'] = catalog
            tickers = sorted(set(acquisition_tickers(store, catalog_snapshot)) | {row['ticker'] for row in universe['members']})
            acquisition_universe, history, aliases = normalize_acquisition_aliases(tickers, universe['members'], history)
            result['acquisition_aliases'] = aliases
            notes = load_acquisition_notes(paths, target, universe['members'], now)
            result['acquisition_notes'] = notes
            acquisition_universe, history, acquisition_members = acquisition_note_context(
                acquisition_universe, history, universe['members'], aliases, notes)
            if notes['status'] == 'INVALID':
                emit_progress('证券采集备注校验失败，保留原采集流程：' + notes['error'])
            elif notes['deferred']:
                emit_progress(f"按已核实证券生命期备注，暂缓 {len(notes['deferred'])} 支停用旧证券的重复采集。")
            quota = None
            if execute:
                try:
                    # SDK logging captures stdout at its first import; keep it
                    # bound to the live CLI stream instead of a closed local file.
                    quota = live_quota(paths, run_dir)
                    save(run_dir / 'quota.log', {'status': 'QUOTA_QUERY_SUCCESS',
                        'queried_at': datetime.now(timezone.utc).isoformat(), 'source': 'MOOMOO_OPEND'})
                except Exception as exc:
                    result['moomoo_error'] = str(exc)
                    emit_progress(str(exc))
            pool_supplement = current_pool_supplement(acquisition_members, aliases, catalog_snapshot[0])
            del catalog_snapshot
            plan = build_top20_quota_plan(history['records'], quota, as_of_date=target,
                bootstrap_records=history['bootstrap_records'], universe=acquisition_universe,
                pool_supplement=pool_supplement,
                lookback_sessions=60, max_moomoo_symbols=300)
            save(run_dir / 'quota_plan.json', plan)
            scope_subscriptions = (acquisition_note_context(catalog['subscriptions'],
                {'records': [], 'bootstrap_records': []}, [], aliases, notes)[0]
                if 'subscriptions' in catalog else None)
            alternate_scope = (alternate_acquisition_scope(plan, scope_subscriptions, aliases=aliases)
                               if scope_subscriptions is not None else None)
            result['alternate_acquisition_scope'] = (alternate_scope if alternate_scope is not None else
                {'status': 'LEGACY_SCOPE_UNCHANGED', 'reason': 'SUBSCRIPTION_METADATA_UNAVAILABLE'})
            result['quota_plan_summary'] = {key: plan[key] for key in
                ('counts', 'history_date_start', 'history_date_end', 'bootstrap_used', 'max_moomoo_symbols')}
            result['universe'] = {key: value for key, value in universe.items() if key != 'members'}
            if execute and universe['current']:
                save(root / 'current_universe.json', result['universe'])
            if not execute:
                result.update(status='PLANNED', message='更新计划已生成，尚未请求行情。')
            else:
                start = (datetime.fromisoformat(target).date() - timedelta(days=400)).isoformat()
                result['acquisitions'] = acquire_pool_prices(paths, root, run_dir, plan, start, target,
                    acquisition_members, calendar['sessions'], emit_progress,
                    **({'alternate_scope': alternate_scope} if alternate_scope is not None else {}))
                result['acquisitions'] = topup_moomoo_once(paths, root, run_dir, plan, result['acquisitions'],
                    target, start, history, acquisition_universe, pool_supplement, emit_progress)
                from scripts.daily_recommendation_prices import publish_acquired_prices
                result['market_publication'] = publish_acquired_prices(
                    paths, result['acquisitions'], target, run_dir, progress=emit_progress)
                result['acquisitions'], result['native_current_tail'] = acquire_native_current_tail(
                    paths, run_dir, target, acquisition_members, result['acquisitions'],
                    read_catalog(store)[0], calendar['sessions'], emit_progress)
                native_count = result['native_current_tail']['result_count']
                if result['native_current_tail']['qualified_intervals']:
                    result['native_market_publication'] = publish_acquired_prices(
                        paths, {'moomoo': {'results': result['acquisitions']['moomoo']['results'][-native_count:]}},
                        target, run_dir / 'native_current_tail', progress=emit_progress)
                result['benchmark_update'] = refresh_daily_benchmarks(
                    paths, run_dir, target, calendar, store, emit_progress)
                save(run_dir / 'benchmark_update.json', result['benchmark_update'])
                result['other_data'] = acquire_other_data(paths, run_dir, target, catalog, emit_progress)
                emit_progress('核对当天 A2 全股票池及输入完整性，生成推荐。')
                try:
                    from scripts.daily_recommendation_prices import refresh_rehab
                    rehab = refresh_rehab(paths, acquisition_members, run_dir / 'rehab', target, progress=emit_progress)
                    save(run_dir / 'rehab_receipt.json', rehab)
                    prediction_acquisitions = prediction_after_native_publication(result['acquisitions'],
                        result.get('native_market_publication', {}), native_count, target)
                    _infer_recommendation(result, binding, universe, target, calendar, prediction_acquisitions, store, rehab, run_dir, notes)
                except Exception as exc:
                    result.update(status='WAITING_DATA', rows=[], message='数据更新已尝试，A2 推荐尚缺完整输入：' + str(exc))
            result['generated_at'] = datetime.now(timezone.utc).isoformat()
        except Exception as exc:
            result.update(status='BLOCKED', rows=[], message=str(exc), generated_at=datetime.now(timezone.utc).isoformat())
        if execute and result['status'] == 'READY':
            # Acquisition inputs are no longer needed by either replay producer.
            del history, universe, plan, store, acquisition_universe, acquisition_members, pool_supplement
            import gc
            gc.collect()
            _publish_recommendation(paths, result, run_dir, root, emit_progress)
        save(run_dir / 'report.json', result)
        if execute:
            save(root / 'latest.json', result)
        if result['status'] == 'READY':
            save(root / 'history' / (run_id + '.json'), result)
    return result


def _execution_chart_context(paths, now):
    """Bind one observed opening to the last completed frozen signal."""
    from scripts import daily_recommendation_inputs as inputs
    from scripts.research.a2.portfolio.selected_hgb import active_policy
    from scripts.research.a2.evaluation.three_strategy_extension import reference, verify_refs
    from scripts.research.a2.evaluation.demo_performance import canonical_manifest
    if now.tzinfo is None:
        raise ValueError('EXECUTION_CHART_ASOF_TIMEZONE_REQUIRED')
    policy, package_path = active_policy(paths)
    package_path = Path(package_path).resolve()
    package_ref = reference(package_path)
    package = json.loads(package_path.read_text(encoding='utf-8-sig'))
    from scripts.research.a2.portfolio.selected_hgb import LEGACY_POLICY
    if package.get('policy_id', LEGACY_POLICY) != policy:
        raise ValueError('EXECUTION_CHART_ACTIVE_POLICY_CHANGED')
    source_ref = package['source_refs']['current/report.json']
    verify_refs([package_ref, source_ref])
    source = json.loads(Path(source_ref['path']).read_text(encoding='utf-8-sig'))
    binding = inputs.load_frozen_binding(paths.repo_root)
    calendar = inputs.latest_completed_session(binding, now)
    signal = source['data_date']
    if source.get('status') != 'READY' or signal != calendar['target_date']:
        return {'status': 'WAITING_SOURCE', 'signal_date': signal,
                'required_signal_date': calendar['target_date']}
    close = datetime.fromisoformat(signal).replace(hour=16, tzinfo=ZoneInfo('America/New_York'))
    generated = datetime.fromisoformat(source['generated_at'].replace('Z', '+00:00'))
    if (generated.tzinfo is None or not close <= generated <= now
            or any(item['application'].get('signal_date') != signal for item in package['strategies'].values())):
        raise ValueError('EXECUTION_CHART_SIGNAL_AVAILABILITY_INVALID')
    days = calendar['sessions']
    index = days.index(signal)
    if index + 1 >= len(days):
        raise ValueError('EXECUTION_CHART_CALENDAR_END')
    execution = days[index + 1]
    opening = datetime.fromisoformat(execution).replace(hour=9, minute=30,
                                                       tzinfo=ZoneInfo('America/New_York'))
    if now < opening or now.astimezone(opening.tzinfo).date().isoformat() != execution:
        return {'status': 'WAITING_OPEN', 'signal_date': signal, 'execution_date': execution}
    historical, _ = canonical_manifest(paths.daily_root / 'A2_historical_top40/latest.json')
    historical_data = json.loads(historical.read_text(encoding='utf-8-sig'))
    historical_inputs = historical_data['price_manifest']
    mapping = Path(source['universe']['report_path']).parent / 'mapped_members.parquet'
    mapping_ref = {'path': str(mapping.resolve()), 'sha256': source['universe']['universe_members_sha256']}
    raw, _ = canonical_manifest(paths.daily_root / 'A2_updated_research/latest.json')
    return {'status': 'READY', 'signal_date': signal, 'execution_date': execution,
        'as_of_utc': now.astimezone(timezone.utc).isoformat(), 'sessions': days,
        'policy_id': policy, 'package': package_ref, 'source_report': source_ref,
        'identity_binding': mapping_ref, 'historical_identity_binding': historical_inputs,
        'historical_manifest': reference(historical), 'raw_manifest': reference(raw)}


def _execution_selected_manifest(context):
    """Reuse the original reader's exact target bytes and display-reference guard."""
    from scripts.research.a2.evaluation.three_strategy_extension import _capture_json
    from apps.demo_console.adapters import selected_strategies_reader as reader
    source = Path(context['package']['path'])
    package = reader.load_package(source)  # Explicit reads never merge chart overlays.
    from scripts.research.a2.portfolio.selected_hgb import LEGACY_POLICY
    policy = package.get('policy_id', LEGACY_POLICY)
    if context.get('policy_id', policy) != policy:
        raise ValueError('EXECUTION_CHART_ACTIVE_POLICY_CHANGED')
    if package['package_sha256'] != context['package']['sha256']:
        raise ValueError('EXECUTION_CHART_BASE_TARGET_CHANGED')
    ref = package['performance_extension']['manifest']
    overlay = reader._display_reference(source, context['package']['sha256'])
    if overlay is not None:
        _, value, _ = overlay
        if value['policy_id'] != package['policy_id']:
            raise ValueError('EXECUTION_CHART_DISPLAY_POLICY_CHANGED')
        ref = value['performance_manifest']
    manifest, _ = _capture_json(ref['path'], ref['sha256'])
    return package, manifest, ref


def _execution_charts_current(context):
    from scripts.research.a2.evaluation.three_strategy_extension import _capture_json, verify_refs
    _, selected, selected_ref = _execution_selected_manifest(context)
    raw, _ = _capture_json(context['raw_manifest']['path'], context['raw_manifest']['sha256'])
    if (raw.get('performance_end_date') != context['execution_date']
            or selected['performance_period']['end'] != context['execution_date']):
        return False
    for phase in (raw.get('execution_open'), selected.get('execution_open')):
        if phase is not None:
            if phase.get('signal_end_date') != context['signal_date'] or phase.get('execution_end_date') != context['execution_date']:
                raise ValueError('EXECUTION_CHART_CURRENT_CLOCK_CHANGED')
            opened, _ = _capture_json(phase['manifest']['path'], phase['manifest']['sha256'])
            if opened.get('current_report') != context['source_report']:
                raise ValueError('EXECUTION_CHART_CURRENT_SOURCE_CHANGED')
    if selected.get('policy_id') != context['policy_id'] or selected.get('blocked_next') or raw.get('blocking_input'):
        return False
    from scripts.research.a2.evaluation.selected_performance_update import merge_extension
    package, _, _ = _execution_selected_manifest(context)
    merge_extension(package, selected, selected_ref['path'], history_root=Path(context['package']['path']).parent / 'history')
    refs = [*raw['outputs'].values(), *selected['source_refs'], selected_ref]
    for strategy in selected['strategies'].values():
        refs.extend(strategy['outputs'].values())
    verify_refs(refs)
    return True


def _execution_open_members(paths, context):
    """Union current candidates and research holdings, preserving each identity."""
    import pandas as pd
    import pyarrow.parquet as pq
    from scripts.research.a2.evaluation.three_strategy_extension import _capture_json, verify_refs
    source, _ = _capture_json(context['source_report']['path'], context['source_report']['sha256'])
    package, replay, _ = _execution_selected_manifest(context)
    names = {row['ticker'] for row in source['ranked_rows'] if row['rank'] <= 40}
    names.update(row['ticker'] for row in package['shared_scores']['current']['rows'])
    names.update(row['ticker'] for row in replay['shared_scores_historical']
                 if row['signal_date'] == context['signal_date'])
    # Prior captured opens also need their now-mature signal close for the next
    # replay; this is a bounded accepted set, not a whole-universe request.
    names.update(replay.get('execution_open', {}).get('qualified_tickers', []))
    if replay.get('source_refs'):
        from scripts.research.a2.evaluation.three_strategy_extension import prior_price_capture
        _, captured = prior_price_capture(replay)
        names.update(captured.get('execution_open', {}).get('qualified_tickers', []))
    for strategy in replay['strategies'].values():
        if strategy['targets']:
            names.update(row['ticker'] for row in strategy['targets'][-1]['rows'] if row['target_weight'] > 0)
    raw, _ = _capture_json(context['raw_manifest']['path'], context['raw_manifest']['sha256'])
    position = raw['outputs']['positions']; verify_refs([position, context['identity_binding'], context['historical_identity_binding']])
    held = pq.read_table(position['path'], columns=['date', 'ticker', 'shares_after'],
        filters=[('date', '=', pd.Timestamp(raw['performance_end_date']).to_pydatetime())]).to_pandas()
    names.update(held.loc[held.shares_after.gt(0), 'ticker'])
    mapped = pq.read_table(context['identity_binding']['path'],
        columns=['ticker', 'security_id', 'moomoo_symbol']).to_pandas()
    if mapped.ticker.duplicated().any():
        raise ValueError('EXECUTION_CHART_AMBIGUOUS_CURRENT_IDENTITY')
    identities = {str(row.ticker): {'ticker': str(row.ticker), 'security_id': str(row.security_id),
                                  'moomoo_symbol': str(row.moomoo_symbol)} for row in mapped.itertuples()}
    historical, _ = _capture_json(context['historical_identity_binding']['path'],
                                 context['historical_identity_binding']['sha256'])
    for ticker in sorted(names - set(identities)):
        matches = [row for row in historical['lineage'] if row.get('ticker') == ticker and len(row.get('cusips', [])) == 1]
        if len(matches) != 1:
            raise ValueError('EXECUTION_CHART_HELD_IDENTITY_UNBOUND:' + ticker)
        row = matches[0]
        identities[ticker] = {'ticker': ticker, 'security_id': row['cusips'][0], 'moomoo_symbol': row['code']}
    return [identities[ticker] for ticker in sorted(names)]


def _execution_open_acquire(paths, context, work):
    """Reuse native receipts; requery only securities without an observed open."""
    import csv
    import pandas as pd
    import pyarrow.parquet as pq
    from types import SimpleNamespace
    from scripts.storage import refresh_market_data as market
    from scripts.daily_recommendation_prices import refresh_rehab
    from scripts.research.a2.evaluation.three_strategy_extension import reference, verify_refs
    from scripts.common.storage_paths import assert_safe_output_path
    members = _execution_open_members(paths, context)
    cache = paths.cache_root / 'A2_today_recommendation/execution_charts' / context['execution_date'] / context['package']['sha256'][:16]
    assert_safe_output_path(cache, paths=paths, kind='cache'); cache.mkdir(parents=True, exist_ok=True)
    saved = cache / 'latest.json'
    acquired, factors = {}, {}
    if saved.exists():
        old_ref = json.loads(saved.read_text(encoding='utf-8-sig'))
        verify_refs([old_ref])
        old = json.loads(Path(old_ref['path']).read_text(encoding='utf-8-sig'))
        if old['current_report'] != context['source_report'] or old['identity_binding'] != context['identity_binding']:
            raise ValueError('EXECUTION_OPEN_RETRY_BINDING_CHANGED')
        for key, destination in (('acquisition_manifest', acquired), ('rehab_receipt', factors)):
            verify_refs([old[key]])
            document = json.loads(Path(old[key]['path']).read_text(encoding='utf-8-sig'))
            for row in document['results']:
                destination[row.get('code') or row['item']['moomoo_symbol']] = row
    def has_open(row):
        if not row or row.get('status') != 'FETCHED_VALIDATED_INTERVAL':
            return False
        ref = row['current_kline_provenance']['sdk_response']; verify_refs([ref, row])
        # Read only the terminal official open; intraday OHLCV remain quarantined.
        schema = pq.read_schema(ref['path']); field = schema.field('time_key').type
        import pyarrow as pa
        lo = pd.Timestamp(context['execution_date']); hi = lo + pd.Timedelta(days=1)
        lower, upper = ((lo.to_pydatetime(), hi.to_pydatetime()) if pa.types.is_timestamp(field)
                        else (str(lo.date()), str(hi.date())))
        frame = pq.read_table(ref['path'], columns=['code', 'open'],
            filters=[('time_key', '>=', lower), ('time_key', '<', upper)]).to_pandas()
        import math
        value = float(frame.iloc[0]['open']) if len(frame) == 1 else float('nan')
        return len(frame) == 1 and frame.iloc[0]['code'] == row['item']['moomoo_symbol'] and math.isfinite(value) and value > 0
    pending = [member for member in members if not has_open(acquired.get(member['moomoo_symbol']))
               or factors.get(member['moomoo_symbol'], {}).get('status') != 'PASS']
    attempt = cache / ('attempt_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '_' + uuid.uuid4().hex[:6])
    attempt.mkdir()
    if pending:
        universe = attempt / 'members.csv'
        with universe.open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=['ticker', 'security_id', 'moomoo_symbol'])
            writer.writeheader(); writer.writerows(pending)
        native = market.run(SimpleNamespace(repo_root=paths.repo_root, work_root=attempt / 'native',
            tickers=None, universe_csv=universe, start=context['sessions'][context['sessions'].index(context['signal_date']) - 4],
            end=context['signal_date'], adjustments=['raw'], host=None, port=None, max_retries=0,
            execute=True, acquisition_mode='current-kline', known_only=False))
        rehab = refresh_rehab(paths, pending, attempt / 'rehab', context['execution_date'])
        for row in native['results']:
            if row.get('status') == 'FETCHED_VALIDATED_INTERVAL':
                acquired[row['item']['moomoo_symbol']] = row
        for row in rehab['results']:
            factors[row['code']] = row
    native_path, rehab_path = attempt / 'native_union.json', attempt / 'rehab_union.json'
    save(native_path, {'source_policy': 'MOOMOO_ONLY', 'acquisition_mode': 'current-kline',
        'trade_context_opened': False, 'semantics': 'DERIVED_UNION_OF_ACTUAL_SDK_RECEIPTS_NOT_WIRE_RESPONSE',
        'results': list(acquired.values())})
    save(rehab_path, {'source': 'MOOMOO_OPEND_GET_REHAB', 'target_date': context['execution_date'],
        'semantics': 'DERIVED_UNION_OF_ACTUAL_REHAB_RECEIPTS', 'results': list(factors.values())})
    manifest = {'schema': 'A2_EXECUTION_OPEN_INPUTS_V1', 'signal_end_date': context['signal_date'],
        'execution_end_date': context['execution_date'], 'as_of_utc': datetime.now(timezone.utc).isoformat(),
        'current_report': context['source_report'], 'identity_binding': context['identity_binding'],
        'historical_identity_binding': context['historical_identity_binding'],
        'acquisition_manifest': reference(native_path), 'rehab_receipt': reference(rehab_path),
        'records': [{'ticker': member['ticker'], 'code': member['moomoo_symbol'], 'security_id': member['security_id']}
                    for member in members if has_open(acquired.get(member['moomoo_symbol']))
                    and factors.get(member['moomoo_symbol'], {}).get('status') == 'PASS']}
    immutable = attempt / 'execution_open_manifest.json'
    save(immutable, manifest); save(saved, reference(immutable))
    if len(manifest['records']) != len(members):
        return {'status': 'BLOCKED', 'reason': 'EXECUTION_OPEN_PROVIDER_INPUTS_INCOMPLETE',
                'qualified_receipt_count': len(manifest['records']), 'requested_count': len(members),
                'manifest': reference(immutable)}
    return {'status': 'READY', 'manifest': reference(immutable), 'requested_count': len(members)}


def _execution_chart_worker(paths, kind, context_path, expected_sha):
    from scripts.research.a2.evaluation.three_strategy_extension import _capture_json, reference
    context_path = Path(context_path).resolve()
    if not context_path.is_relative_to((paths.daily_root / 'A2_today_recommendation/execution_charts').resolve()):
        raise ValueError('EXECUTION_CHART_BINDING_OUTSIDE_DAILY_OWNER')
    context, _ = _capture_json(context_path, expected_sha)
    declared = datetime.fromisoformat(context['as_of_utc'].replace('Z', '+00:00'))
    if declared.tzinfo is None or declared > datetime.now(timezone.utc):
        raise ValueError('EXECUTION_CHART_WORKER_ASOF_INVALID')
    actual = _execution_chart_context(paths, declared)
    if (actual.get('status') != 'READY' or context_path.name != 'binding.json'
            or any(actual.get(key) != context.get(key) for key in actual
                   if key not in {'as_of_utc', 'raw_manifest'})):
        raise ValueError('EXECUTION_CHART_WORKER_CONTEXT_CHANGED')
    if not Path(context['raw_manifest']['path']).resolve().is_relative_to((paths.daily_root / 'A2_updated_research/runs').resolve()):
        raise ValueError('EXECUTION_CHART_PRIOR_OUTSIDE_RAW_OWNER')
    _capture_json(context['raw_manifest']['path'], context['raw_manifest']['sha256'])
    work = context_path.parent
    if kind == 'execution-inputs':
        return _execution_open_acquire(paths, context, work)
    state = json.loads((work / 'state.json').read_text(encoding='utf-8-sig'))
    opening = state['inputs']['manifest']; _capture_json(opening['path'], opening['sha256'])
    if kind == 'execution-raw':
        from scripts.research.a2.evaluation.demo_performance import refresh_demo_performance, canonical_manifest
        latest_path, _ = canonical_manifest(paths.daily_root / 'A2_updated_research/latest.json')
        latest, _ = _capture_json(latest_path)
        if latest.get('performance_end_date') == context['execution_date']:
            from scripts.research.a2.evaluation.three_strategy_extension import verify_refs
            verify_refs(list(latest['outputs'].values()))
            return {'status': 'READY', 'action': 'REUSED_VERIFIED_CURRENT_CHARTS',
                    'report_path': str(latest_path), 'performance_end_date': context['execution_date']}
        result = refresh_demo_performance(paths, historical_manifest_path=context['historical_manifest']['path'],
            current_report_path=context['source_report']['path'],
            prior_verified_performance_manifest_path=context['raw_manifest']['path'],
            execution_open_manifest=opening['path'], execution_end=context['execution_date'],
            retain_qualified_prior_open=True)
        return {key: result.get(key) for key in ('status', 'report_path', 'performance_end_date', 'blocking_input', 'error')}
    if kind != 'execution-selected':
        raise ValueError('UNKNOWN_EXECUTION_CHART_WORKER')
    from scripts.research.a2.evaluation import three_strategy_extension as extension
    from scripts.research.a2.evaluation.hgb_policy_alignment import TASK_ID
    from scripts.research.a2.evaluation.selected_performance_update import replay_with_held_updates, publish_display_performance
    sys.path.insert(0, str(paths.repo_root / 'scripts/storage'))
    from backtest_run_manager import create_backtest_run
    git = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=paths.repo_root, check=True,
        capture_output=True, text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    git_commit = git.stdout.strip()
    if len(git_commit) != 40 or any(ch not in '0123456789abcdef' for ch in git_commit):
        raise ValueError('EXECUTION_CHART_GIT_IDENTITY_INVALID')
    root = create_backtest_run(TASK_ID, git_commit, '2026-01-01', context['signal_date'], [])
    config_path = root / 'run_config.json'
    config = json.loads(config_path.read_text(encoding='utf-8'))
    config.update(execution_end_date=context['execution_date'], chart_only=True,
        source_implementations={name: reference(paths.repo_root / name) for name in (
            'scripts/daily_recommendation.py', 'scripts/research/a2/evaluation/selected_performance_update.py',
            'scripts/research/a2/evaluation/three_strategy_extension.py')})
    save(config_path, config)
    _, _, prior_research_ref = _execution_selected_manifest(context)
    prices, inputs = extension.capture_full_prices(root / 'derived/inputs', repo_root=paths.repo_root,
        current_report_path=context['source_report']['path'], execution_open_manifest=opening['path'],
        execution_end=context['execution_date'], prior_research_manifest=prior_research_ref)
    manifest, manifest_path = replay_with_held_updates(paths, root / 'derived', prices, inputs,
        context['signal_date'], policy=context['policy_id'], execution_open_manifest=opening['path'],
        execution_end=context['execution_date'], prior_research_manifest=prior_research_ref)
    if manifest['performance_period']['end'] != context['execution_date'] or manifest.get('blocked_next'):
        return {'status': 'BLOCKED', 'reason': 'EXECUTION_CHART_REPLAY_INCOMPLETE', 'manifest': reference(manifest_path),
                'performance_end_date': manifest['performance_period']['end'], 'blocking_input': manifest.get('blocked_next')}
    ref = publish_display_performance(paths, context['package']['path'], manifest_path)
    return {'status': 'READY', 'display_reference': ref, 'performance_end_date': context['execution_date']}


def _execution_chart_reference_status(paths, execution_date):
    """Report independent price-reference coverage; never mask strategy progress."""
    from scripts.research.a2.evaluation.three_strategy_extension import _capture_json
    try:
        pointer, _ = _capture_json(paths.results_root / 'demo-console/benchmarks/updated_reference.json')
        manifest, _ = _capture_json(pointer['path'], pointer['sha256'])
        end = manifest['end_date']
        return {'status': 'CURRENT' if end >= execution_date else 'REFERENCE_OPEN_NOT_AVAILABLE',
                'available_end_date': end, 'requested_execution_date': execution_date,
                'reference': pointer, 'provider_fallback_or_purchase_attempted': False}
    except (OSError, ValueError, KeyError, AttributeError) as exc:
        return {'status': 'UNAVAILABLE', 'reason': type(exc).__name__,
                'requested_execution_date': execution_date}


def refresh_execution_benchmarks(paths, context, work, progress=emit):
    """Extend the one ETF reference independently; no A2 input or plan changes."""
    from scripts.storage.refresh_demo_benchmarks import benchmark_native_scope, refresh_demo_benchmarks
    from scripts.research.a2.evaluation.demo_performance_prices import execution_open_clock
    from scripts.research.a2.evaluation.three_strategy_extension import reference, verify_refs
    signal, execution = context['signal_date'], context['execution_date']
    stage = _execution_chart_reference_status(paths, execution)
    audit = {'new_current_kline_requests': 0, 'history_request_count': 0, 'trade_requests': 0}
    previous_verified = False
    try:
        execution_open_clock(signal, execution, context['sessions'], context['as_of_utc'])
        verify_refs([context['package'], context['source_report']])
        calendar = {'target_date': execution, 'sessions': context['sessions'], 'as_of_utc': context['as_of_utc']}
        if stage.get('status') == 'CURRENT':
            # Reuse still traverses the original manifest/artifact/source gates.
            updated = refresh_demo_benchmarks(paths, execution, calendar, progress)
        else:
            scope = benchmark_native_scope(paths, signal, {**calendar, 'target_date': signal})
            if scope.get('status') != 'NOOP' or scope.get('available_end_date') != signal:
                raise ValueError('BENCHMARK_OFFICIAL_OPEN_MATURE_SIGNAL_REFERENCE_REQUIRED')
            previous_verified = True
            latest_five = [day for day in context['sessions'] if day <= signal][-5:]
            if len(latest_five) != 5:
                raise ValueError('BENCHMARK_OFFICIAL_OPEN_FIVE_SESSIONS_REQUIRED')
            native_scope = {**scope, 'status': 'NEEDS_NATIVE', 'target_date': signal,
                'bridge_start': latest_five[0], 'required_dates': latest_five,
                'native_tickers': ['QQQ', 'SPY'], 'sessions': context['sessions'],
                'as_of_utc': context['as_of_utc']}
            attempt = Path(work) / 'benchmark_open' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '_' + uuid.uuid4().hex[:8])
            from scripts.common.storage_paths import assert_safe_output_path
            assert_safe_output_path(attempt, paths=paths, kind='daily'); attempt.mkdir(parents=True)
            # If collection raises after starting, request counts are UNKNOWN.
            audit = {'new_current_kline_requests': None, 'history_request_count': None, 'trade_requests': None}
            native, audit = acquire_benchmark_native_inputs(paths, attempt, signal, native_scope,
                None, progress, execution_date=execution)
            audit_path = attempt / 'acquisition_audit.json'; save(audit_path, audit)
            if audit.get('status') != 'READY':
                raise ValueError('BENCHMARK_OFFICIAL_OPEN_BOTH_ETF_RECEIPTS_REQUIRED')
            verify_refs([context['package'], context['source_report']])
            # This is the real aggregate completion clock, never the earlier binding clock.
            phase = {'signal_date': signal, 'execution_date': execution,
                     'as_of_utc': datetime.now(timezone.utc).isoformat()}
            phase_path = attempt / 'execution_open_inputs.json'
            save(phase_path, {'schema': 'ETF_BENCHMARK_OFFICIAL_OPEN_INPUTS_V1', **phase,
                'source_report': context['source_report'], 'package': context['package'],
                'native_inputs': native, 'acquisition_audit': reference(audit_path)})
            updated = refresh_demo_benchmarks(paths, execution, {**calendar, 'as_of_utc': phase['as_of_utc']},
                progress, native_inputs=native, execution_open=phase)
            updated['acquisition_inputs'] = reference(phase_path)
        verify_refs([context['package'], context['source_report']])
        if updated.get('status') != 'READY' or updated.get('end_date') < execution:
            raise ValueError(updated.get('error') or 'BENCHMARK_OFFICIAL_OPEN_REFERENCE_NOT_VERIFIED')
        stage = _execution_chart_reference_status(paths, execution)
        if stage.get('status') != 'CURRENT':
            raise ValueError('BENCHMARK_OFFICIAL_OPEN_PUBLICATION_NOT_CURRENT')
        stage['refresh'] = updated
    except Exception as exc:
        # A valid chart cannot turn a missing/failed ETF reference into CURRENT.
        stage['status'] = 'REFERENCE_OPEN_NOT_AVAILABLE' if previous_verified else 'UNAVAILABLE'
        stage['refresh'] = {'status': 'BLOCKED', 'error': str(exc)}
    stage['provider_calls'] = audit.get('new_current_kline_requests', 0)
    stage['history_request_count'] = audit.get('history_request_count', 0)
    stage['trade_requests'] = audit.get('trade_requests', 0)
    return stage


def run_execution_charts(paths, *, now=None, progress=emit):
    """Original daily owner: one chart-only opening action, no plan/order change."""
    from scripts.common.storage_paths import assert_safe_output_path
    from scripts.research.a2.evaluation.three_strategy_extension import reference
    clock = now or datetime.now(timezone.utc)
    root = paths.daily_root / 'A2_today_recommendation'
    with single_update(root):
        context = _execution_chart_context(paths, clock)
        if context['status'] != 'READY':
            return context
        work = root / 'execution_charts' / context['execution_date'] / context['package']['sha256'][:16]
        assert_safe_output_path(work, paths=paths, kind='daily'); work.mkdir(parents=True, exist_ok=True)
        state_path = work / 'state.json'
        # One owner call covers both the verified-reuse and normal chart branches.
        benchmark = refresh_execution_benchmarks(paths, context, work, progress)
        if _execution_charts_current(context):
            result = {'schema': 'A2_EXECUTION_CHART_REFRESH_STATE_V1', 'status': 'READY', 'action': 'REUSED_VERIFIED_CURRENT_CHARTS',
                'signal_date': context['signal_date'], 'execution_date': context['execution_date'],
                'package_sha256': context['package']['sha256'], 'source_report': context['source_report'],
                'broker_action_allowed': False, 'provider_calls': benchmark['provider_calls'], 'replay_calls': 0,
                'benchmark_reference': benchmark}
            save(state_path, result); return result
        from scripts.research.a2.evaluation.hgb_policy_alignment import frozen_contract
        frozen_contract(paths)
        from scripts.research.a2.portfolio import selected_hgb
        if context['policy_id'] == selected_hgb.LEGACY_POLICY:
            selected_hgb.verify_frozen(selected_hgb._source_root(paths))
        binding = work / 'binding.json'
        # Bind once per exact package/source identity; volatile retry time is not authority.
        if binding.exists():
            existing = json.loads(binding.read_text(encoding='utf-8-sig'))
            if any(existing.get(key) != context.get(key) for key in context if key not in {'as_of_utc', 'raw_manifest'}):
                raise ValueError('EXECUTION_CHART_RETRY_CONTEXT_CHANGED')
        else:
            save(binding, context)
        context = json.loads(binding.read_text(encoding='utf-8-sig'))
        state = {'schema': 'A2_EXECUTION_CHART_REFRESH_STATE_V1', 'status': 'RUNNING', 'signal_date': context['signal_date'], 'execution_date': context['execution_date'],
                 'package_sha256': context['package']['sha256'], 'source_report': context['source_report'],
                 'broker_action_allowed': False, 'benchmark_reference': benchmark, 'started_at': clock.isoformat()}
        save(state_path, state)
        for kind, key in (('execution-inputs', 'inputs'), ('execution-raw', 'raw'), ('execution-selected', 'selected')):
            log = work / (kind + '.log')
            process = None
            try:
                process = run_provider(paths, 'scripts.daily_recommendation', ['--performance-worker', kind,
                    '--source-report', binding, '--source-sha256', reference(binding)['sha256']], log)
                if process['exit_code'] != 0:
                    raise RuntimeError(process.get('error') or 'EXECUTION_CHART_WORKER_EXIT:' + str(process['exit_code']))
                state[key] = read_worker_result(log)
            except Exception as exc:
                state[key] = {'status': 'BLOCKED', 'error': str(exc), 'log_path': str(log)}
                if isinstance(process, dict):
                    state[key]['worker_process'] = {field: process[field] for field in
                        ('module', 'exit_code', 'lifecycle', 'log_path', 'error') if field in process}
            if (state[key].get('status') not in {'READY', 'PARTIAL'}
                    or (key in {'raw', 'selected'} and state[key].get('performance_end_date') != context['execution_date'])):
                state.setdefault('failed_stages', []).append(key)
                state.update(status='BLOCKED'); save(state_path, state)
                if key == 'inputs': return state
                continue
            save(state_path, state)
        if reference(context['package']['path']) != context['package']:
            raise ValueError('EXECUTION_CHART_CANONICAL_TARGET_CHANGED')
        from scripts.research.a2.evaluation.demo_performance import canonical_manifest
        latest_raw, _ = canonical_manifest(paths.daily_root / 'A2_updated_research/latest.json')
        final_context = {**context, 'raw_manifest': reference(latest_raw)}
        verified_current = _execution_charts_current(final_context)
        state.update(status='READY' if verified_current else 'BLOCKED',
                     benchmark_reference=benchmark,
                     completed_at=datetime.now(timezone.utc).isoformat())
        save(state_path, state)
        return state


def _compact_terminal_result(result):
    """Project only terminal presentation; saved reports and execution stay original."""
    def fields(value, names):
        if not isinstance(value, dict): return {}
        output = {}
        for key in names:
            if key not in value: continue
            item = value[key]
            if not isinstance(item, (str, bool, int, float, type(None))): continue
            output[key] = (item[:2048] + ' [terminal shortened; see full_report_ref]'
                if key in {'message', 'error', 'reason', 'primary_error', 'fallback_error'} and isinstance(item, str) and len(item) > 2048 else item)
        return output
    def stage(value):
        output = fields(value, ('status', 'schema', 'run_id', 'report_path', 'log_path', 'policy_id',
            'ranking_end_date', 'performance_end_date', 'available_end_date', 'signal_date',
            'execution_date', 'action', 'error', 'primary_error', 'fallback_error', 'message', 'reason', 'provider_calls', 'replay_calls'))
        if isinstance(value, dict):
            for key in ('blocking_input', 'blocked_next', 'blocked_next_window'):
                if isinstance(value.get(key), dict):
                    output[key] = fields(value[key], ('status', 'reason', 'signal_date', 'execution_date'))
        return output
    summary = {'schema': 'A2_DAILY_TERMINAL_SUMMARY_V1', 'compact_output': True,
        **fields(result, ('status', 'phase', 'run_id', 'data_date', 'recommendation_date',
            'generated_at', 'model_id', 'model_sha256', 'message', 'error', 'report_path',
            'signal_date', 'execution_date', 'package_sha256', 'broker_action_allowed'))}
    rows = result.get('rows')
    if isinstance(rows, list):
        summary['row_count'] = len(rows)
        summary['rows'] = [fields(row, ('rank', 'ticker', 'score', 'source')) for row in rows[:20]]
    summary['coverage'] = fields(result.get('coverage'), ('eligible_count', 'mapped_count', 'excluded_count'))
    for key in ('performance_update', 'selected_strategies_update', 'benchmark_update',
                'benchmark_reference', 'other_data', 'inputs', 'raw', 'selected'):
        if key in result: summary[key] = None if result[key] is None else stage(result[key])
    current_inputs = result.get('consensus_paper_inputs')
    if isinstance(current_inputs, dict):
        summary['consensus_paper_inputs'] = fields(current_inputs, ('status', 'signal_date', 'reason'))
        publication = current_inputs.get('publication', {})
        extension = publication.get('paper_current_extension', {}) if isinstance(publication, dict) else {}
        summary['consensus_paper_inputs']['paper_current_status'] = fields(extension, ('status',)).get('status')
    selected = result.get('selected_strategies_update')
    if isinstance(selected, dict) and isinstance(selected.get('strategies'), dict):
        summary['selected_strategies_update']['strategies'] = {
            name: stage(result['selected_strategies_update']['strategies'][name])
            for name in ('HGB_DIAG_5', 'HGB_FACTOR_5') if name in result['selected_strategies_update']['strategies']}
    completion = result.get('completion')
    if isinstance(completion, dict):
        summary['completion'] = fields(completion, ('schema', 'status', 'target_date'))
        summary['completion']['required_stages'] = fields(completion.get('required_stages'),
            ('recommendation', 'raw_research', 'hgb_targets_and_charts', 'benchmarks'))
        limitations = completion.get('limitations')
        limitations = limitations if isinstance(limitations, dict) else {}
        summary['completion']['limitations'] = {
            'coverage': fields(limitations.get('coverage'), ('eligible_count', 'mapped_count', 'excluded_count')),
            'rx': stage(limitations.get('rx'))}
    recovery = result.get('recovery')
    if isinstance(recovery, dict):
        summary['recovery'] = fields(recovery, ('action', 'report_path', 'work_dir',
            'acquisition_calls', 'inference_calls', 'broker_calls'))
    acquisitions = result.get('acquisitions', {})
    if isinstance(acquisitions, dict):
        summary['acquisitions'] = {key: None if acquisitions[key] is None else fields(acquisitions.get(key),
            ('status', 'attempted_symbols', 'target_reached_symbols', 'selected_tickers'))
            for key in ('moomoo', 'alternate', 'massive') if key in acquisitions}
        massive = acquisitions.get('massive')
        if isinstance(massive, dict):
            for source_key, count_key in (('target_reached_tickers', 'target_reached_count'), ('issues', 'issue_count')):
                if isinstance(massive.get(source_key), list):
                    summary['acquisitions']['massive'][count_key] = sum(bool(item) for item in massive[source_key])
    for key in ('accepted_source', 'source_report', 'display_reference', 'repair_lineage'):
        if isinstance(result.get(key), dict): summary[key] = fields(result[key], ('path', 'sha256'))
    # Recovery keeps the old report identity for current-target binding.
    # Its current full completion is saved in the separate recovery report.
    full_report = recovery.get('report_path') if isinstance(recovery, dict) else None
    full_report = full_report or result.get('report_path')
    if full_report:
        try:
            from scripts.research.a2.evaluation.three_strategy_extension import reference
            summary['full_report_ref'] = reference(full_report)
        except Exception as exc:
            summary['full_report_ref_error'] = str(exc)[:2048]
    return summary


def prepare_current_inputs(paths, expected_signal_date, source_report, source_sha256, progress=emit):
    """Finish current inputs without daily.predict_current; frozen scoring is retained."""
    from scripts import daily_recommendation_inputs as inputs
    from scripts.research.a2.evaluation.hgb_policy_alignment import frozen_contract
    from scripts.research.a2.evaluation.three_strategy_extension import reference, verify_refs
    from scripts.research.a2.inference import consensus_paper
    root = paths.daily_root / 'A2_today_recommendation'
    result = {'action': 'PREPARE_CURRENT_INPUTS', 'status': 'BLOCKED', 'target_date': expected_signal_date,
        'acquisition_calls': 0, 'raw_inference_calls': 0, 'model_fit_calls': 0, 'trade_requests': 0,
        'broker_action_allowed': False}
    with single_update(root):
        now = datetime.now(timezone.utc)
        binding = inputs.load_frozen_binding(paths.repo_root)
        calendar = inputs.latest_completed_session(binding, now)
        if calendar['target_date'] != expected_signal_date:
            raise ValueError('CURRENT_INPUTS_EXPECTED_SIGNAL_DATE_CHANGED')
        frozen_contract(paths)
        latest_path = root / 'latest.json'
        if latest_path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError('RESUME_LATEST_TOO_LARGE')
        latest_ref = reference(latest_path)
        latest = json.loads(latest_path.read_text(encoding='utf8'))
        if latest.get('status') != 'READY' or latest.get('data_date') != expected_signal_date:
            raise ValueError('CURRENT_INPUTS_ACCEPTED_DAILY_REQUIRED')
        source, source_ref = _accepted_recommendation_source(paths, latest, binding, calendar, now)
        requested = {'path': str(Path(source_report).resolve()), 'sha256': source_sha256}
        if source_ref != requested:
            raise ValueError('CURRENT_INPUTS_BOUND_SOURCE_CHANGED')
        result['source_report'] = source_ref
        progress('显式恢复当前策略输入：复用已接受的日线和冻结特征，仅补未完成的原输入发布。')
        stage = update_consensus_paper_inputs(paths, source, Path(source_ref['path']).parent, allow_raw_recovery=False)
        # Neither a successful producer nor an old publication can mask drift.
        now = datetime.now(timezone.utc)
        current_binding = inputs.load_frozen_binding(paths.repo_root)
        current_calendar = inputs.latest_completed_session(current_binding, now)
        if current_binding != binding or current_calendar['target_date'] != expected_signal_date:
            raise ValueError('CURRENT_INPUTS_BINDING_OR_CALENDAR_CHANGED')
        frozen_contract(paths)
        verify_refs([latest_ref, source_ref])
        _, checked_ref = _accepted_recommendation_source(paths, latest, current_binding, current_calendar, now)
        if checked_ref != source_ref:
            raise ValueError('CURRENT_INPUTS_BOUND_SOURCE_CHANGED')
        publication = stage.get('publication', {})
        extension = publication.get('paper_current_extension', {})
        result.update(signal_date=stage.get('signal_date'), source_status=stage.get('status'),
            paper_current_status=extension.get('status'))
        if (stage.get('status') != 'READY' or stage.get('signal_date') != expected_signal_date
                or publication.get('status') != 'READY' or extension.get('status') != 'READY'):
            result['reason'] = stage.get('reason') or extension.get('reason') or 'CURRENT_INPUTS_PUBLICATION_INCOMPLETE'
            return result
        base, base_ref = consensus_paper.load_publication(paths, expected_signal_date, now.isoformat())
        current, duration_ref = consensus_paper.load_publication(paths, expected_signal_date, now.isoformat(), paper_current=True)
        if (base != {key: value for key, value in publication.items() if key != 'paper_current_extension'}
                or base.get('status') != 'READY' or base.get('signal_date') != expected_signal_date
                or current.get('strategy_status', {}).get('R6_DURATION_TREE', {}).get('status') != 'READY'
                or duration_ref != extension.get('publication_ref')):
            raise ValueError('CURRENT_INPUTS_PUBLICATION_READBACK_CHANGED')
        result.update(status='READY', publication_ref=base_ref, duration_publication_ref=duration_ref)
        return result


def prepare_main_ca(paths, expected_signal_date, progress=emit, *, finite_ca_admission_ref=None):
    """Explicit manual acquisition only; CA completeness grants no MAIN admission."""
    from scripts.common.storage_paths import assert_safe_output_path
    owner = importlib.import_module('scripts.research.a2.evaluation.consensus_paper_performance')
    consumer = importlib.import_module('scripts.research.a2.inference.consensus_paper')
    finite_owner = (importlib.import_module('scripts.research.a2.evaluation.consensus_paper_ca_continuation')
        if finite_ca_admission_ref is not None else None)
    admission = None
    result = {'action': 'PREPARE_MAIN_CA', 'status': 'BLOCKED', 'target_date': expected_signal_date,
        'rehab_requests': 0, 'history_requests': 0, 'trade_requests': 0, 'model_fit_calls': 0,
        'models_loaded': 0, 'account_replays': 0, 'broker_action_allowed': False,
        'main_qualification_ready': False}

    def finish(qualification):
        ca = qualification['ca_qualification']
        admitted_terms = admission['admitted_event_terms'] if admission is not None else {}
        terms_admitted = bool(ca['typed_event_terms_required']) and all(
            set(days) <= set(admitted_terms.get(code, ())) for code, days in ca['typed_event_terms_required'].items())
        if ca['typed_event_terms_required'] and not terms_admitted:
            result.update(status='SOURCE_CA_TERMS_BLOCKED', reason='PAPER_EXTENSION_IN_SCOPE_NEW_CA_TERMS_REQUIRED:'
                + owner.canonical(ca['typed_event_terms_required']))
        elif qualification['missing_raw_dates']:
            result.update(status='SOURCE_RAW_BLOCKED', reason='PAPER_EXTENSION_REQUIRED_CURRENT_RAW_QUOTE_GAP:'
                + owner.canonical(qualification['missing_raw_dates']))
        elif ca['missing_codes']:
            result.update(status='MISSING_CA_RECEIPTS', reason='PAPER_EXTENSION_CURRENT_CA_RESPONSE_MISSING:'
                + ','.join(ca['missing_codes']))
        elif terms_admitted:
            result.update(status='READY', reason='FINITE_SOURCE_CA_PREPARED_NOT_MAIN_ADMISSION')
        elif qualification['status'] == 'READY' and ca['status'] == 'READY':
            result.update(status='READY', reason='SOURCE_CA_READY_NOT_MAIN_ADMISSION')
        else:
            result.update(status='BLOCKED', reason='PAPER_EXTENSION_CURRENT_NATIVE_QUOTE_NOT_READY')
        return result

    # The original register owns the same lock itself. Fetch under the daily lock,
    # then let register independently revalidate all original input identities.
    with single_update(paths.daily_root / 'A2_today_recommendation'):
        clock = datetime.now(timezone.utc).isoformat()
        calendar = owner.completed_calendar(paths, clock)
        owner.need(calendar['target_session'] == expected_signal_date, 'MAIN_CA_EXPECTED_SIGNAL_DATE_CHANGED')
        driver = finite_owner or owner
        current = driver.already_current(paths, calendar, clock, **(
            {'finite_ca_admission_ref': finite_ca_admission_ref} if finite_owner is not None else {}))
        if current is not None and finite_owner is None:
            # A completed finite extension does not grant opt-in CA authority
            # to the default source preparer. Retain its original qualification.
            completed = owner.projected_metadata(current['manifest_ref'], ('extensions',))
            for sid in owner.IDS:
                refs = owner.projected_metadata(completed['extensions'][sid], ('source_refs',))['source_refs']
                if 'finite_ca_admission_ref' in refs:
                    current = None
                    break
        if current is not None:
            owner.need(current.get('status') == 'ALREADY_CURRENT_PREFIX_VERIFIED'
                and current.get('end') == expected_signal_date, 'MAIN_CA_CURRENT_COMPLETION_MISMATCH')
            if finite_owner is not None:
                owner.need(current.get('finite_ca_admission_ref') == finite_ca_admission_ref,
                    'FINITE_CA_CURRENT_ADMISSION_CHANGED')
                result['finite_ca_admission_ref'] = current['finite_ca_admission_ref']
            result.update(status='READY', reason='CURRENT_MAIN_OWNER_PROOF_REUSED_NOT_NEW_QUALIFICATION',
                main_manifest_ref=current['manifest_ref'])
            return result
        capture = owner.resolve_current_capture(paths, calendar)
        preflight = owner.metadata_preflight(paths, capture_ref=capture, as_of=clock)
        owner.need(preflight['end'] == expected_signal_date, 'MAIN_CA_EXPECTED_SIGNAL_DATE_CHANGED')
        if finite_owner is not None:
            admission = finite_owner.qualify_admission(paths, finite_ca_admission_ref, as_of=clock, preflight=preflight)
            result['finite_ca_admission_ref'] = admission['admission_ref']
        document, publication = consumer.load_publication(paths, preflight['end'], clock)
        owner.need(publication == preflight['publication_ref'], 'PAPER_EXTENSION_CURRENT_PUBLICATION_CHANGED')
        owner._tail_proof_chain(document, calendar, clock)
        source = owner._current_quote_source(paths, document, preflight['end'], clock)
        locator_inputs = dict(target_session=preflight['end'], publication_ref=publication,
            capture_ref=capture, daily_report_ref=source['report_ref'])
        existing = owner.resolve_supplemental_ca_receipts(paths, **locator_inputs, as_of=clock)
        if existing['locator_ref'] is None:
            # A present locator is already bound by the original resolver.
            owner._ca_locator_origin(paths, **locator_inputs, as_of=clock)
        # metadata_preflight already authenticates this original Ridge reader view.
        # MAIN separately requires its equality with the original R7 quote source.
        market_ref = preflight['originals'][owner.IDS[1]]['inference']['market_source']['bars_ref']
        frame = consumer.bounded_frame(market_ref, ['ticker'], 'trade_date', owner.START, owner.PREFIX_END)
        domain = set(frame.ticker.astype(str)); del frame
        owner.need(bool(domain), 'PAPER_EXTENSION_ORIGINAL_MARKET_DOMAIN_REQUIRED')
        tail, qualification = owner.qualify_current_tail(paths, document=document, baselines=preflight['baselines'],
            domain=domain, as_of=clock, calendar_qualification=calendar, ca_receipt_refs=existing['ca_receipt_refs'])
        del tail
        result['locator_ref'] = existing['locator_ref']
        finish(qualification)
        if result['status'] != 'MISSING_CA_RECEIPTS':
            return result
        codes = sorted(set(qualification['ca_qualification']['missing_codes']))
        work = paths.daily_root / 'A2_consensus_paper/current_tail_ca/runs' / (
            datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '_' + uuid.uuid4().hex[:8])
        assert_safe_output_path(work, kind='daily', paths=paths)
        prices = importlib.import_module('scripts.daily_recommendation_prices')
        receipt = prices.refresh_rehab(paths, [{'moomoo_symbol': code} for code in codes], work,
            expected_signal_date, progress=progress)
        result['rehab_requests'] = len(receipt.get('results', []))
        owner.need(receipt.get('history_requests') == 0 and receipt.get('trade_requests') == 0,
            'MAIN_CA_ONLY_REHAB_RECEIPT_REQUIRED')
        if receipt.get('status') != 'READY':
            result.update(status='BLOCKED', reason='MAIN_CA_REHAB_NOT_READY:' + str(receipt.get('error', receipt.get('status'))))
            return result
        receipt_ref = owner.reference(receipt['receipt_path'])
        owner.need(receipt_ref['sha256'] == receipt['receipt_sha256'], 'PAPER_EXTENSION_REFERENCE_CHANGED')
        refs = [*existing['ca_receipt_refs'], receipt_ref]

    clock = datetime.now(timezone.utc).isoformat()
    owner.register_supplemental_ca_receipts(paths, **locator_inputs, as_of=clock, ca_receipt_refs=refs)
    with single_update(paths.daily_root / 'A2_today_recommendation'):
        clock = datetime.now(timezone.utc).isoformat()
        current = owner.resolve_supplemental_ca_receipts(paths, **locator_inputs, as_of=clock)
        if finite_owner is not None:
            admission = finite_owner.qualify_admission(paths, finite_ca_admission_ref, as_of=clock, preflight=preflight)
        tail, qualification = owner.qualify_current_tail(paths, document=document, baselines=preflight['baselines'],
            domain=domain, as_of=clock, calendar_qualification=calendar, ca_receipt_refs=current['ca_receipt_refs'])
        del tail
        result['locator_ref'] = current['locator_ref']
        return finish(qualification)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--compact-output', action='store_true', help='Print a small daily terminal summary; retain full reports. Internal performance and opening-chart protocols stay unchanged.')
    parser.add_argument('--refresh-data', action='store_true', help='Reacquire same-day inputs instead of recovering accepted inputs.')
    parser.add_argument('--requalify-inputs', action='store_true', help='Requalify accepted same-day saved inputs without acquisition or fitting.')
    parser.add_argument('--execution-charts', action='store_true', help='Update opening research charts only; preserve current execution targets.')
    parser.add_argument('--prepare-main-ca', action='store_true', help='Explicitly complete current MAIN native CA receipts; no model, replay or MAIN admission.')
    parser.add_argument('--prepare-current-inputs', action='store_true', help='Explicitly finish current strategy inputs from the exact accepted daily source; no acquisition or Raw inference.')
    parser.add_argument('--expected-signal-date', help='Required current completed session for an explicit prepare action.')
    parser.add_argument('--finite-ca-admission-ref', help='Explicit JSON {path,sha256} for the separately admitted finite MAIN CA continuation.')
    parser.add_argument('--performance-worker', choices=('raw', 'selected', 'execution-inputs', 'execution-raw', 'execution-selected'), help=argparse.SUPPRESS)
    parser.add_argument('--source-report', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--source-sha256', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    from scripts.common.storage_paths import resolve
    for output_stream in (sys.stdout, sys.stderr):
        if hasattr(output_stream, 'reconfigure'):
            output_stream.reconfigure(encoding='utf-8')
    if args.finite_ca_admission_ref and not args.prepare_main_ca:
        parser.error('Finite CA admission requires --prepare-main-ca.')
    if args.expected_signal_date and not (args.prepare_main_ca or args.prepare_current_inputs):
        parser.error('Expected signal date requires an explicit prepare action.')
    if args.prepare_current_inputs:
        if (not args.expected_signal_date or not args.source_report or not args.source_sha256
                or args.prepare_main_ca or args.finite_ca_admission_ref or args.execute or args.refresh_data
                or args.requalify_inputs or args.execution_charts or args.performance_worker):
            parser.error('Prepare current inputs requires only its explicit expected date, accepted source and hash.')
        try:
            result = prepare_current_inputs(resolve(), args.expected_signal_date, args.source_report, args.source_sha256)
        except Exception as exc:
            result = {'action': 'PREPARE_CURRENT_INPUTS', 'status': 'BLOCKED', 'target_date': args.expected_signal_date,
                'error': str(exc), 'broker_action_allowed': False}
        print(json.dumps({'event': 'result', 'result': result}, ensure_ascii=False, allow_nan=False), flush=True)
        return 0 if result['status'] == 'READY' else 2
    if args.prepare_main_ca:
        if (not args.expected_signal_date or args.execute or args.refresh_data or args.requalify_inputs
                or args.execution_charts or args.performance_worker or args.source_report or args.source_sha256):
            parser.error('Prepare MAIN CA requires only its explicit expected signal date.')
        try:
            result = prepare_main_ca(resolve(), args.expected_signal_date, **(
                {'finite_ca_admission_ref': json.loads(args.finite_ca_admission_ref)} if args.finite_ca_admission_ref else {}))
        except Exception as exc:
            result = {'action': 'PREPARE_MAIN_CA', 'status': 'BLOCKED', 'target_date': args.expected_signal_date,
                'error': str(exc), 'broker_action_allowed': False, 'main_qualification_ready': False}
        print(json.dumps({'event': 'result', 'result': result}, ensure_ascii=False, allow_nan=False), flush=True)
        return 0 if result['status'] == 'READY' else 2
    if args.performance_worker:
        if args.execute or args.refresh_data or args.requalify_inputs or args.execution_charts or not args.source_report or not args.source_sha256:
            parser.error('Performance worker requires only its bound source and hash.')
        try:
            worker = _execution_chart_worker if args.performance_worker.startswith('execution-') else _performance_worker
            summary = worker(resolve(), args.performance_worker, args.source_report, args.source_sha256)
        except Exception as exc:
            summary = {'status': 'BLOCKED', 'error': str(exc)}
        print(json.dumps({'event': 'performance_result', 'result': summary}, ensure_ascii=False, allow_nan=False), flush=True)
        return 0
    if args.source_report or args.source_sha256:
        parser.error('Source arguments require a fixed performance worker action.')
    if args.refresh_data and not args.execute:
        parser.error('Refresh data requires --execute.')
    if args.requalify_inputs and (not args.execute or args.refresh_data or args.execution_charts):
        parser.error('Requalify inputs requires only --execute; it cannot refresh or update opening charts.')
    if args.execution_charts:
        if args.execute or args.refresh_data:
            parser.error('Execution charts cannot acquire or replace daily predictions.')
        try:
            result = run_execution_charts(resolve())
        except Exception as exc:
            result = {'status': 'BLOCKED', 'error': str(exc), 'broker_action_allowed': False}
        print(json.dumps({'event': 'result', 'result': result}, ensure_ascii=False, allow_nan=False), flush=True)
        return 0 if result['status'] == 'READY' else 2
    try:
        result = run_update(resolve(), args.execute, **({"refresh_data": True} if args.refresh_data else {"requalify_inputs": True} if args.requalify_inputs else {}))
    except Exception as exc:
        result = {'status': 'BLOCKED', 'message': str(exc), 'rows': [], 'generated_at': datetime.now(timezone.utc).isoformat()}
    print(json.dumps({'event': 'result', 'result': _compact_terminal_result(result) if args.compact_output else result}, ensure_ascii=False, allow_nan=False), flush=True)
    return 0 if result['status'] in {'READY', 'PLANNED'} and result.get('completion', {}).get('status', 'READY') == 'READY' else 2


if __name__ == '__main__':
    raise SystemExit(main())
