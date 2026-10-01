"""One user command: acquire current inputs, then run the frozen A2 predictor.

Provider snapshots stay separate. Incomplete inputs never become today's Top20.
This is a presentation/acquisition adapter, not a replacement strategy runner.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timedelta, timezone
import importlib
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
    from scripts.storage.refresh_market_data import load_module, PROFILE
    profile_module = load_module(paths.repo_root / PROFILE, 'today_quote_profile')
    profile = profile_module.load_profile(paths.repo_root / 'config/moomoo_opend_connection.json', dict(os.environ))
    connected, reason = profile_module.tcp_probe(profile)
    if not connected:
        raise ConnectionError('Moomoo OpenD 未连接：' + str(reason))
    appdata = work / 'sdk_appdata'
    appdata.mkdir(parents=True, exist_ok=True)
    os.environ['APPDATA'] = str(appdata)
    sdk = importlib.import_module('moomoo')
    sdk.SysConfig.set_all_thread_daemon(True)
    context = sdk.OpenQuoteContext(host=profile.host, port=profile.port, is_async_connect=True)
    try:
        context.set_sync_query_connect_timeout(10)
        code, quota = context.get_history_kl_quota(get_detail=True)
        if code != sdk.RET_OK:
            raise RuntimeError('MOOMOO_QUOTA_QUERY_FAILED')
        return quota
    finally:
        context.close()


def run_provider(paths, module, arguments, log):
    """Only fixed modules and argv, never an input string interpreted by a shell."""
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('w', encoding='utf-8') as stream:
        try:
            process = subprocess.run([str(paths.python_exe), '-B', '-m', module, *map(str, arguments)],
                cwd=paths.repo_root, stdout=stream, stderr=subprocess.STDOUT,
                timeout=3600, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            return {'module': module, 'exit_code': process.returncode, 'log_path': str(log)}
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {'module': module, 'exit_code': -1, 'log_path': str(log), 'error': str(exc)}


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


def acquire_prices(paths, root, run_dir, plan, start, target, emit_progress=emit):
    """Reuse both existing provider adapters; retain their native price bases."""
    import csv
    from types import SimpleNamespace
    from scripts.storage import refresh_market_data
    moomoo = [row for row in plan['assignments'] if row['provider'] == 'MOOMOO']
    alternate = [row['ticker'] for row in plan['assignments'] if row['provider'] == 'ALTERNATE']
    reports = {}
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


def acquire_pool_prices(paths, root, run_dir, plan, start, target, members, sessions, emit_progress=emit):
    """Refresh pool prices and the Massive execution marks needed by DEMO."""
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
    result = acquire_prices(paths, root, run_dir, plan, start, target, emit_progress)
    result['massive'] = massive
    return result


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
        # A failure in the optional portfolio policies must not invalidate A2.
        try:
            save_selected_hgb_features(output_dir, features, prices, rows, target, sessions, lineage=lineage)
        except Exception as exc:
            save(Path(output_dir) / 'selected_hgb_features_binding.json',
                 {'status': 'BLOCKED', 'signal_date': target, 'error': str(exc)})
    return rows, lineage, missing


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
    try:
        from scripts.research.a2.portfolio.selected_hgb import build_package
        source_path = run_dir / 'recommendation_source.json'
        if not source_path.exists():
            save(source_path, {**result, 'report_path': str(source_path)})
        progress('应用 HGB 对角风险与因子／收缩风险策略，生成收盘目标仓位和现金。')
        output_path = Path(os.environ.get('USTQ_SELECTED_HGB_PACKAGE') or
                           paths.daily_root / 'A2_selected_hgb/latest.json').expanduser().resolve()
        package = build_package(paths, current_report_path=source_path, progress=progress)
        from scripts.research.a2.evaluation.selected_performance_update import (
            refresh_selected_performance, publish_current_preserving_replay)
        try:
            package = refresh_selected_performance(paths, package, source_path, output_path, progress,
                **({"held_price_reuse": held_price_reuse} if held_price_reuse is not None else {}))
        except Exception:
            publish_current_preserving_replay(package, output_path)
            raise
        applications = {name: item['application'] for name, item in package['strategies'].items()}
        ready = all(item['status'] == 'READY' and item['signal_date'] == result['data_date']
                    for item in applications.values())
        extension = package['performance_extension']
        ready = ready and extension['status'] == 'READY' and package['performance_period']['end'] == result['data_date']
        return {'status': 'READY' if ready else 'PARTIAL',
                'report_path': str(output_path),
                'performance_end_date': package['performance_period']['end'],
                'requested_end_date': extension['requested_end_date'],
                'blocked_next': extension['blocked_next'],
              'strategies': {name: {key: item.get(key) for key in ('status', 'signal_date', 'account_basis', 'reason')}
                             for name, item in applications.items()}}
    except Exception as exc:
        progress('原 A2 更新已保留；HGB 目标或共同绩效同步未完成，查看独立状态与实际曲线截止日。')
        return {'status': 'BLOCKED', 'error': str(exc)}


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
        manifest = refresh_demo_performance(
            paths,
            historical_manifest_path=paths.daily_root / 'A2_historical_top40/latest.json',
            current_report_path=source_path,
            prior_verified_performance_manifest_path=prior_manifest,
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


def run_update(paths, execute=True, emit_progress=emit):
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
    with single_update(root):
        run_dir.mkdir(parents=True, exist_ok=False)
        result.update(run_id=run_id, report_path=str(run_dir / 'report.json'))
        try:
            emit_progress('核对冻结 A2 模型、交易日及最新可靠 Top20 / Top40 记录。')
            binding = inputs.load_frozen_binding(paths.repo_root)
            model = next(item for item in binding['components']['ALPHA']['artifacts'] if item['artifact_id'] == 'model')
            result['model_sha256'] = model['sha256']
            calendar = inputs.latest_completed_session(binding, now)
            target = result['data_date'] = calendar['target_date']
            universe = inputs.load_bound_universe(binding, target)
            if execute:
                from scripts.daily_recommendation_universe import refresh_universe
                emit_progress('按既有机构和证券注册表，更新最新已披露 13F 股票池。')
                universe = refresh_universe(paths, target, run_dir, execute=True)
            history = inputs.load_priority_history(paths.backtest_root / 'research/a2/demo_2026_calendar_replay', root / 'history', model['sha256'])
            store = DataStore()
            catalog = status(store)
            result['catalog_before'] = catalog
            tickers = sorted(set(acquisition_tickers(store)) | {row['ticker'] for row in universe['members']})
            acquisition_universe, history, aliases = normalize_acquisition_aliases(tickers, universe['members'], history)
            result['acquisition_aliases'] = aliases
            quota = None
            if execute:
                try:
                    with (run_dir / 'quota.log').open('w', encoding='utf-8') as log, redirect_stdout(log):
                        quota = live_quota(paths, run_dir)
                except Exception as exc:
                    result['moomoo_error'] = str(exc)
                    emit_progress(str(exc))
            pool_supplement = current_pool_supplement(universe['members'], aliases, read_catalog(store)[0])
            plan = build_top20_quota_plan(history['records'], quota, as_of_date=target,
                bootstrap_records=history['bootstrap_records'], universe=acquisition_universe,
                pool_supplement=pool_supplement,
                lookback_sessions=60, max_moomoo_symbols=300)
            save(run_dir / 'quota_plan.json', plan)
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
                    universe['members'], calendar['sessions'], emit_progress)
                result['acquisitions'] = topup_moomoo_once(paths, root, run_dir, plan, result['acquisitions'],
                    target, start, history, acquisition_universe, pool_supplement, emit_progress)
                from scripts.daily_recommendation_prices import publish_acquired_prices
                result['market_publication'] = publish_acquired_prices(
                    paths, result['acquisitions'], target, run_dir, progress=emit_progress)
                from scripts.storage.refresh_demo_benchmarks import refresh_demo_benchmarks
                result['benchmark_update'] = refresh_demo_benchmarks(paths, target, calendar, emit_progress)
                save(run_dir / 'benchmark_update.json', result['benchmark_update'])
                result['other_data'] = acquire_other_data(paths, run_dir, target, catalog, emit_progress)
                emit_progress('核对当天 A2 全股票池及输入完整性，生成推荐。')
                try:
                    from scripts.daily_recommendation_prices import refresh_rehab
                    rehab = refresh_rehab(paths, universe['members'], run_dir / 'rehab', target, progress=emit_progress)
                    save(run_dir / 'rehab_receipt.json', rehab)
                    rows, lineage, missing = predict_current(binding, universe, target, calendar['sessions'], result['acquisitions'], store, rehab,
                        output_dir=run_dir)
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
                    save(run_dir / 'input_lineage.json', lineage)
                    save(run_dir / 'excluded.json', {'price_or_feature_gaps': missing, 'identity_gaps': universe.get('mapping_gaps', [])})
                except Exception as exc:
                    result.update(status='WAITING_DATA', rows=[], message='数据更新已尝试，A2 推荐尚缺完整输入：' + str(exc))
            result['generated_at'] = datetime.now(timezone.utc).isoformat()
        except Exception as exc:
            result.update(status='BLOCKED', rows=[], message=str(exc), generated_at=datetime.now(timezone.utc).isoformat())
        if execute and result['status'] == 'READY':
            result['performance_update'] = update_demo_performance(paths, result, run_dir, emit_progress)
            result['selected_strategies_update'] = update_selected_strategies(paths, result, run_dir, emit_progress)
            if (result['performance_update']['status'] in {'READY', 'PARTIAL'}
                    and result['performance_update'].get('performance_end_date') == result['data_date']
                    and result['selected_strategies_update']['status'] == 'READY'
                    and result['selected_strategies_update'].get('performance_end_date') == result['data_date']):
                result['message'] = '当天 A2 推荐、DEMO 历史绩效、三策略图表及日期范围已同步至最新可验证交易日。'
            else:
                result['message'] = '当天 A2 推荐已更新，绩效更新未完成；现有曲线仍保留其实际截止日期。'
            result['generated_at'] = datetime.now(timezone.utc).isoformat()
        save(run_dir / 'report.json', result)
        if execute:
            save(root / 'latest.json', result)
        if result['status'] == 'READY':
            save(root / 'history' / (run_id + '.json'), result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    from scripts.common.storage_paths import resolve
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        result = run_update(resolve(), args.execute)
    except Exception as exc:
        result = {'status': 'BLOCKED', 'message': str(exc), 'rows': [], 'generated_at': datetime.now(timezone.utc).isoformat()}
    print(json.dumps({'event': 'result', 'result': result}, ensure_ascii=False, allow_nan=False), flush=True)
    return 0 if result['status'] in {'READY', 'PLANNED'} else 2


if __name__ == '__main__':
    raise SystemExit(main())
