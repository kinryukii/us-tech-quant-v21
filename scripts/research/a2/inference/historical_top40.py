"""Recompute displayed daily A2 ranks with dated 13F pools and fixed models.

This runner computes predictions only. It does not evaluate returns, select
parameters, or replace the frozen research artifacts used as its references.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import uuid

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from threadpoolctl import threadpool_limits

from scripts.common.daily_support import emit, save, single_update
from scripts.daily_recommendation_inputs import load_frozen_binding, latest_completed_session

QQQ_CALENDAR_HASHES = {
    2020: 'f9acd32fa2878458577b7fd2a8eff8d3f07acf13fc32c4323754a07265bc24fe',
    2021: 'c8fd7c684fe7ef54705b99c3e6bd59c810d26af94f9dc27cf1ed7df4b32d5865',
    2022: '3b16247910d78e3961ff94c6c9d9030afaf200f3a30ae22205b0c5042483e588',
    2023: 'a5a35422629920b7f5d063acabbb04f0ad410ec9f7e504de7daadd3b9d249bf6',
    2024: '7e14eb6735e7660e6895ab1a9a4ee86fa3ed1bd3ea976c56aeecfd75411e5eb8',
    2025: 'b8a8abb5a8bdd7cbf9cf44ebba2f54bc09b60612c6fd8a7b7951aa064f9abc89',
    2026: '5341bcea299d8b83f7de51daa01e829fa94aa5eb67012a3c76f6f5b4dc5395ff',
}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verified_json(path):
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8-sig'))


def load_sessions(paths):
    """Read only the proven QQQ date projection and the bound exchange calendar."""
    days, references = set(), []
    for year, expected in QQQ_CALENDAR_HASHES.items():
        path = paths.data_root / f'moomoo/source/prices_qfq/year={year}/prices.parquet'
        if digest(path) != expected:
            raise ValueError(f'HISTORICAL_CALENDAR_SOURCE_CHANGED:{year}')
        dates = pq.read_table(path, columns=['trade_date'], filters=[('ticker', '=', 'QQQ')]).to_pandas()
        if digest(path) != expected:
            raise ValueError(f'HISTORICAL_CALENDAR_SOURCE_CHANGED_DURING_READ:{year}')
        days.update(pd.to_datetime(dates.trade_date).dt.strftime('%Y-%m-%d'))
        references.append({'path': str(path), 'sha256': expected, 'columns': ['trade_date'], 'filter_ticker': 'QQQ'})
    binding = load_frozen_binding(paths.repo_root)
    calendar = latest_completed_session(binding)
    calendar_ref = binding['readiness_sources']['trading_calendar']
    contract_path = Path(calendar_ref['path'])
    if digest(contract_path) != calendar_ref['sha256'] or calendar['calendar_sha256'] != calendar_ref['sha256']:
        raise ValueError('BOUND_CALENDAR_CONTRACT_CHANGED')
    contract = verified_json(contract_path)
    rules_path = Path(contract['rules_source'])
    if digest(rules_path) != contract['rules_source_sha256']:
        raise ValueError('BOUND_CALENDAR_RULES_CHANGED')
    generated_sha = hashlib.sha256(json.dumps(calendar['sessions'], sort_keys=True,
        separators=(',', ':'), ensure_ascii=True).encode('utf-8')).hexdigest()
    if generated_sha != contract['sessions_sha256'] or len(calendar['sessions']) != contract['session_count']:
        raise ValueError('BOUND_CALENDAR_SESSION_IDENTITY_MISMATCH')
    days.update(calendar['sessions'])
    days = sorted(days)
    # Keep volatile observation timestamps out of the resume contract. Source
    # identities and the exact merged date set remain reproducible across runs.
    lineage = {'schema': 'HISTORICAL_TOP40_CALENDAR_LINEAGE_V1', 'historical_qqq': references,
        'exchange_calendar': {'path': str(contract_path), 'sha256': calendar_ref['sha256'],
            'calendar_id': calendar['calendar_id'], 'start_date': contract['start_date'],
            'end_date': contract['end_date'], 'session_count': contract['session_count'],
            'sessions_sha256': generated_sha,
            'rules_source': {'path': str(rules_path), 'sha256': contract['rules_source_sha256']}},
        'merged_session_count': len(days), 'merged_start_date': days[0], 'merged_end_date': days[-1],
        'merged_sessions_encoding': 'UTF8_LF_JOINED_ISO_DATES_NO_TRAILING_LF',
        'merged_sessions_sha256': hashlib.sha256('\n'.join(days).encode('utf-8')).hexdigest()}
    return days, {'historical': references, 'current': calendar, 'lineage': lineage}


def ranked_predictions(features, schedule, members, ledger, models, feature_columns,
                       model_loader=joblib.load):
    """Join each date to its own active pool before scoring and ranking."""
    features = features.copy()
    features['target_date'] = pd.to_datetime(features['trade_date']).dt.strftime('%Y-%m-%d')
    if features.duplicated(['target_date', 'ticker']).any():
        raise ValueError('DUPLICATE_PRICE_FEATURE_IDENTITY')
    schedule, members, ledger = schedule.copy(), members.copy(), ledger.copy()
    # Unknown identities remain in the declared pool and coverage denominator,
    # but cannot obtain features through an empty or guessed ticker.
    members = members.loc[members.ticker.notna() & members.security_id.notna()].copy()
    if schedule.snapshot_id.duplicated().any() or ledger.target_date.duplicated().any():
        raise ValueError('DUPLICATE_UNIVERSE_SNAPSHOT_OR_SESSION')
    if members.duplicated(['snapshot_id', 'security_id']).any() or members.duplicated(['snapshot_id', 'ticker']).any():
        raise ValueError('SIMULTANEOUS_SECURITY_OR_TICKER_COLLISION')
    ledger['target_date'] = pd.to_datetime(ledger.target_date).dt.strftime('%Y-%m-%d')
    active = ledger[['target_date', 'snapshot_id']].merge(schedule, on='snapshot_id', how='left', validate='many_to_one')
    known = active.snapshot_id.notna()
    if active.loc[known, 'universe_id'].isna().any():
        raise ValueError('ACTIVE_SNAPSHOT_NOT_FOUND')
    for row in active.loc[known].itertuples(index=False):
        if pd.Timestamp(row.effective_date) > pd.Timestamp(row.target_date):
            raise ValueError('FUTURE_13F_DISCLOSURE_USED')
        identity_effective = getattr(row, 'snapshot_effective_date', row.effective_date)
        if pd.isna(identity_effective) or pd.Timestamp(identity_effective) > pd.Timestamp(row.target_date):
            raise ValueError('FUTURE_UNIVERSE_IDENTITY_SNAPSHOT_USED')
        if pd.Period(row.quarter, freq='Q') >= pd.Period(row.target_date, freq='Q'):
            raise ValueError('SAME_OR_FUTURE_REPORTING_QUARTER_USED')
    eligibility = active.loc[known].merge(members[['snapshot_id', 'security_id', 'ticker']],
                                         on='snapshot_id', how='inner', validate='many_to_many')
    if eligibility.duplicated(['target_date', 'security_id']).any():
        raise ValueError('MORE_THAN_ONE_POOL_ACTIVE_FOR_DATE')
    joined = eligibility.merge(features[['target_date', 'ticker', *feature_columns]],
                               on=['target_date', 'ticker'], how='left', validate='one_to_one')
    usable = np.isfinite(joined[feature_columns].to_numpy(float)).all(axis=1)
    joined = joined.loc[usable].copy()
    joined['model_year'] = pd.to_datetime(joined.target_date).dt.year
    pieces = []
    for year, group in joined.groupby('model_year', sort=True):
        reference = models['artifacts'][str(year)]
        if pd.Timestamp(reference['labelmax']) >= pd.Timestamp(f'{year}-01-01'):
            raise ValueError('MODEL_LABEL_CUTOFF_OVERLAPS_PREDICTION_YEAR')
        if digest(reference['path']) != reference['sha256']:
            raise ValueError('MODEL_BINARY_HASH_CHANGED')
        model = model_loader(reference['path'])
        with threadpool_limits(limits=1):
            values = np.asarray(model.predict(group[feature_columns].to_numpy(float)))
        if values.shape != (len(group),) or not np.isfinite(values).all():
            raise ValueError('INVALID_MODEL_PREDICTION')
        group = group.copy()
        group['score'] = values
        group['model_sha256'] = reference['sha256']
        pieces.append(group)
    ranked = pd.concat(pieces, ignore_index=True) if pieces else joined.assign(score=pd.Series(dtype=float), model_sha256='')
    ranked = ranked.sort_values(['target_date', 'score', 'ticker'], ascending=[True, False, True], kind='mergesort')
    ranked['rank'] = ranked.groupby('target_date', sort=False).cumcount() + 1
    ranked = ranked.rename(columns={'quarter': 'universe_quarter', 'effective_date': 'universe_effective_date'})
    output_columns = ['target_date', 'security_id', 'ticker', 'rank', 'score', 'model_year', 'model_sha256',
                      'universe_id', 'universe_quarter', 'universe_effective_date', 'institution_count']
    ranked = ranked[output_columns].copy()
    ranked['universe_effective_date'] = pd.to_datetime(ranked.universe_effective_date).dt.strftime('%Y-%m-%d')
    ranked['source'] = 'VERIFIED_RAW_AND_EVENT_DATE_REPLAY'
    counts = ranked.groupby('target_date').size().to_dict()
    coverage = []
    for row in active.to_dict('records'):
        count = int(counts.get(row['target_date'], 0))
        has_pool = pd.notna(row.get('snapshot_id'))
        total = int(row['universe_member_count']) if has_pool else 0
        coverage.append({'target_date': row['target_date'],
            'status': 'READY' if count >= 40 and count == total else 'PARTIAL' if count else 'WAITING_DATA',
            'eligible_count': count, 'universe_member_count': total,
            'mapped_count': int(row['mapped_count']) if has_pool else 0,
            'excluded_count': total - count, 'quarter': row['quarter'] if has_pool else '',
            'effective_date': str(pd.Timestamp(row['effective_date']).date()) if has_pool else '',
            'institution_count': int(row['institution_count']) if has_pool else 0,
            'model_year': int(row['target_date'][:4]),
            'reason': '' if count >= 40 and count == total else 'PARTIAL_INPUT_COVERAGE' if count >= 40
                      else 'INSUFFICIENT_VERIFIED_PRICE_FEATURES' if has_pool else 'NO_DISCLOSED_EFFECTIVE_POOL'})
    return ranked.reset_index(drop=True), pd.DataFrame(coverage)


def write_frame(path, frame):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return {'path': str(path), 'sha256': digest(path), 'rows': len(frame)}


def verify_rebuilt_behavior(paths, models):
    """Compare fixed-model outputs on original features, without reading returns."""
    reference = paths.results_root / 'A_VS_A2_QUARTERLY_13F_R1/A2/oof_predictions.parquet'
    expected = 'e336be6c267167356ce3d39fa629f80fe7b2968711112a9c976fdb002c693468'
    if digest(reference) != expected:
        raise ValueError('ORIGINAL_PREDICTIONS_HASH_CHANGED')
    lineage = models['lineage']
    training_path = Path(lineage['training_matrix_path'])
    if digest(training_path) != lineage['training_matrix_sha256']:
        raise ValueError('ORIGINAL_FEATURE_MATRIX_HASH_CHANGED')
    columns = models['feature_columns']
    originals = pq.read_table(reference, columns=['signal_date', 'ticker', 'a2_prediction']).to_pandas()
    matrix = pq.read_table(training_path, columns=['signal_date', 'ticker', *columns]).to_pandas()
    if pd.to_datetime(originals.signal_date).max() >= pd.Timestamp('2026-01-01'):
        raise ValueError('ORIGINAL_BEHAVIOR_REFERENCE_NOT_PRE2026')
    joined = matrix.merge(originals, on=['signal_date', 'ticker'], how='inner', validate='one_to_one')
    checks = []
    for year, group in joined.groupby(pd.to_datetime(joined.signal_date).dt.year, sort=True):
        if str(year) not in models['artifacts']:
            continue
        spec = models['artifacts'][str(year)]
        if digest(spec['path']) != spec['sha256']:
            raise ValueError('REBUILT_MODEL_HASH_CHANGED')
        with threadpool_limits(limits=1):
            predicted = joblib.load(spec['path']).predict(group[columns].to_numpy(float))
        differences = np.abs(predicted - group.a2_prediction.to_numpy(float))
        check = {'year': int(year), 'compared_rows': len(group),
                 'max_absolute_difference': float(differences.max()),
                 'equal_within_1e_minus_12': bool(np.isfinite(differences).all() and (differences <= 1e-12).all())}
        checks.append(check)
    if not checks or not all(row['equal_within_1e_minus_12'] for row in checks):
        raise ValueError('REBUILT_MODEL_DOES_NOT_REPRODUCE_FROZEN_PREDICTIONS:' + json.dumps(checks))
    return {'status': 'PASS', 'comparison_scope': 'Original pre2026 feature rows with mature training-matrix labels; only stored predictions projected.',
            'reference_path': str(reference), 'reference_sha256': expected, 'years': checks,
            'returns_or_2026_labels_read': False}


def publish_current_day(paths, acquired, manifest, ranked, coverage, pool, price_gaps):
    """Make today's displayed result use the completed batch's same daily ranks."""
    day = manifest['end_date']
    if acquired['data_date'] != day or int(day[:4]) != 2026:
        return {'status': 'SKIPPED_NOT_CURRENT_2026_DATA_DATE'}
    current = ranked.loc[ranked.target_date.eq(day)].sort_values('rank')
    if len(current) < 20:
        return {'status': 'SKIPPED_CURRENT_TOP20_UNAVAILABLE'}
    if not current.model_sha256.eq(acquired['model_sha256']).all():
        raise ValueError('CURRENT_PUBLICATION_MODEL_IDENTITY_CHANGED')
    count = coverage.loc[coverage.target_date.eq(day)].iloc[0].to_dict()
    old_rows = acquired.get('ranked_rows', [])
    old_scores = {row['ticker']: float(row['score']) for row in old_rows}
    if (len(old_scores) != len(old_rows) or current.ticker.duplicated().any()
            or not np.isfinite(list(old_scores.values())).all()
            or not np.isfinite(current.score.to_numpy(float)).all()):
        raise ValueError('CURRENT_PUBLICATION_NONFINITE_OR_DUPLICATE_SCORES')
    previous_tickers, current_tickers = set(old_scores), set(current.ticker)
    missing_previous = sorted(previous_tickers - current_tickers)
    newly_eligible = sorted(current_tickers - previous_tickers)
    differences = [abs(float(row.score) - float(old_scores[row.ticker]))
                   for row in current.itertuples() if row.ticker in old_scores]
    if differences and max(differences) > 1e-12:
        raise ValueError('CURRENT_BATCH_AND_DAILY_FEATURE_BEHAVIOR_DIFFER')
    output = paths.daily_root / 'A2_today_recommendation'
    run_id = manifest['run_id'] + '_latest'
    directory = output / 'runs' / run_id
    rehab_source = Path(acquired['report_path']).parent / 'rehab_receipt.json'
    rehab_bytes = rehab_source.read_bytes()
    rehab_sha = hashlib.sha256(rehab_bytes).hexdigest()
    rehab = json.loads(rehab_bytes.decode('utf-8-sig'))
    if (rehab.get('target_date') != day or rehab.get('source') != 'MOOMOO_OPEND_GET_REHAB'
            or not isinstance(rehab.get('results'), list) or digest(rehab_source) != rehab_sha):
        raise ValueError('CURRENT_PUBLICATION_REHAB_RECEIPT_IDENTITY_INVALID')
    rehab_destination = directory / 'rehab_receipt.json'
    directory.mkdir(parents=True, exist_ok=True)
    if rehab_destination.exists():
        if digest(rehab_destination) != rehab_sha:
            raise ValueError('CURRENT_PUBLICATION_REHAB_RECEIPT_CONFLICT')
    else:
        temporary = directory / 'rehab_receipt.json.tmp'
        temporary.write_bytes(rehab_bytes)
        temporary.replace(rehab_destination)
    if digest(rehab_destination) != rehab_sha:
        raise ValueError('CURRENT_PUBLICATION_REHAB_RECEIPT_COPY_MISMATCH')
    rows = current.to_dict('records')
    for row in rows:
        row.update(model_id='A2_HGB', vintage_id=manifest['generated_at'],
                   raw_target_weight=0.05 if row['rank'] <= 20 else 0.0)
    lineage = {'historical_manifest': {'path': manifest['report_path'], 'sha256': digest(manifest['report_path'])},
        'acquisition_report': {'path': acquired['report_path'], 'sha256': digest(acquired['report_path'])},
        'rehab_receipt': {'source': {'path': str(rehab_source), 'sha256': rehab_sha},
                         'published': {'path': str(rehab_destination), 'sha256': rehab_sha}},
        'outputs': manifest['outputs'], 'same_day_prediction_equivalence': {
            'status': ('ALL_PARENT_ROWS_MATCH' if differences and not missing_previous else
                       'PARTIAL_OVERLAP_MATCH' if differences else 'NO_OVERLAP_NOT_VERIFIED'),
            'previous_eligible_count': len(previous_tickers), 'new_eligible_count': len(current_tickers),
            'compared_rows': len(differences), 'max_absolute_difference': max(differences, default=None),
            'missing_previous_count': len(missing_previous), 'missing_previous_tickers': missing_previous,
            'newly_eligible_count': len(newly_eligible), 'newly_eligible_tickers': newly_eligible}}
    save(directory / 'input_lineage.json', lineage)
    members = pool['members'].loc[pool['members'].snapshot_id.eq(
        pool['ledger'].loc[pool['ledger'].target_date.eq(day), 'snapshot_id'].iloc[0])]
    eligible = set(current.ticker)
    prices_by_ticker = {item['ticker']: item for item in price_gaps}
    missing = []
    identity = []
    for item in members.to_dict('records'):
        if pd.isna(item.get('ticker')):
            identity.append({'cusip': item['security_id'], 'reason': item.get('mapping_status', 'IDENTITY_UNPROVEN')})
        elif item['ticker'] not in eligible:
            reasons = prices_by_ticker.get(item['ticker'], {}).get('reasons', ['CURRENT_FEATURES_UNAVAILABLE'])
            missing.append({'ticker': item['ticker'], 'reason': '; '.join(reasons)})
    save(directory / 'excluded.json', {'price_or_feature_gaps': missing, 'identity_gaps': identity})
    result = {**acquired, 'status': 'READY', 'run_id': run_id, 'report_path': str(directory / 'report.json'),
        'generated_at': manifest['generated_at'], 'rows': rows[:20], 'ranked_rows': rows,
        'input_manifest_sha256': digest(directory / 'input_lineage.json'),
        'coverage': {key: count[key] for key in ('eligible_count', 'mapped_count', 'excluded_count', 'status')},
        'universe': {**acquired['universe'], 'universe_id': rows[0]['universe_id'],
            'quarter': count['quarter'], 'effective_date': count['effective_date'],
            'universe_member_count': count['universe_member_count'], 'institution_count': count['institution_count']},
        'historical_recomputation': lineage['historical_manifest'],
        'message': '全历史重新计算已完成；当天 Top20 使用同批次最新排名，缺口股票已明确排除。'}
    save(directory / 'report.json', result)
    save(output / 'history' / (run_id + '.json'), result)
    save(output / 'latest.json', result)
    return {'status': 'PUBLISHED', 'report_path': result['report_path'], 'eligible_count': len(rows)}


def extend_native_2026_prices(paths, pool, features, lineage, gaps, sessions, acquisitions, rehab, start, end):
    """Add verified native candidates only inside their dated 2026 13F pools."""
    signal_days = [day for day in sessions if max(start, '2026-01-01') <= day <= end]
    candidates = {row['ticker'] for row in gaps if row.get('reasons') == ['ORIGINAL_RAW_ANCHOR_UNBOUND']}
    if not signal_days or not candidates:
        return features, lineage, gaps
    from scripts.research.a2.inference.current_native_prices import build_native_2026_feature_candidates
    from scripts.research.a2.inference.historical_top40_prices import _references, _source, _store
    active = pool['ledger'][['target_date', 'snapshot_id']].copy()
    active['target_date'] = pd.to_datetime(active.target_date).dt.strftime('%Y-%m-%d')
    declared = active.merge(pool['members'], on='snapshot_id', how='inner', validate='many_to_many')
    declared = declared.loc[declared.ticker.isin(candidates) & declared.moomoo_symbol.notna()]
    identity = declared.loc[declared.target_date.isin(signal_days)]
    members = identity.drop_duplicates(['security_id', 'ticker', 'moomoo_symbol']).to_dict('records')
    if not members:
        return features, lineage, gaps
    ref = _references(paths)['source']
    extra, native_lineage, native_gaps = build_native_2026_feature_candidates(
        members, signal_days, sessions, acquisitions, _store(paths), rehab, _source(ref), ref,
        gaps, observed_target=end)
    if extra.empty:
        return features, lineage, [*gaps, *({'ticker': row['ticker'], 'reasons': [row['reason']],
            'native_details': row} for row in native_gaps)]
    extra = extra.copy()
    extra['trade_date'] = pd.to_datetime(extra.trade_date)
    extra['target_date'] = extra.trade_date.dt.strftime('%Y-%m-%d')
    if (not set(extra.target_date) <= set(signal_days) or not set(extra.ticker) <= candidates
            or extra.duplicated(['trade_date', 'ticker']).any()):
        raise ValueError('NATIVE_HISTORICAL_CANDIDATE_IDENTITY_INVALID')
    # Restrict even the stored feature artifact, before ranked_predictions does
    # its independent security-id and quarter/effective-date checks.
    allowed = identity[['target_date', 'ticker']].drop_duplicates()
    extra = extra.merge(allowed, on=['target_date', 'ticker'], how='inner', validate='one_to_one')
    extra = extra.drop(columns='target_date')[list(features.columns)]
    combined = pd.concat([features, extra], ignore_index=True)
    if combined.duplicated(['trade_date', 'ticker']).any():
        raise ValueError('NATIVE_HISTORICAL_OVERWRITES_EXISTING_FEATURE')
    accepted = set(extra.ticker)
    proof_tickers = {row['ticker'] for row in native_lineage}
    if not accepted <= proof_tickers:
        raise ValueError('NATIVE_HISTORICAL_PROOF_MISSING')
    merged_gaps = [row for row in gaps if row['ticker'] not in accepted]
    for ticker in sorted(accepted):
        needed = set(declared.loc[declared.ticker.eq(ticker), 'target_date'])
        available = set(extra.loc[extra.ticker.eq(ticker), 'trade_date'].dt.strftime('%Y-%m-%d'))
        missing = sorted(needed - available)
        if missing:
            merged_gaps.append({'ticker': ticker, 'reasons': ['NATIVE_FEATURE_COVERAGE_INCOMPLETE'],
                                'native_scope': '2026_ONLY_PRE2026_FROZEN_PATH_UNCHANGED',
                                'missing_feature_dates': missing})
    merged_gaps.extend({'ticker': row['ticker'], 'reasons': [row['reason']], 'native_details': row}
                       for row in native_gaps if row['ticker'] not in accepted)
    return (combined.sort_values(['trade_date', 'ticker']).reset_index(drop=True),
            [*lineage, *(row for row in native_lineage if row['ticker'] in accepted)], merged_gaps)


def run_rebuild(paths, *, start, end, source_report, sessions, calendar_lineage=None, execute=False, run_id=None):
    """Use completed acquisition receipts; serialize against the daily updater."""
    from scripts.research.a2.inference.historical_top40_models import build_models
    from scripts.research.a2.inference.historical_top40_universe import build_universe_schedule
    from scripts.research.a2.inference.historical_top40_prices import build_price_features
    start, end = str(pd.Timestamp(start).date()), str(pd.Timestamp(end).date())
    if start < '2023-01-03' or end < start or end >= '2027-01-01':
        raise ValueError('UNSUPPORTED_RECOMPUTATION_DATE_RANGE')
    verified_days, verified_calendar = load_sessions(paths)
    dates = sorted({str(pd.Timestamp(day).date()) for day in sessions})
    if dates != verified_days:
        raise ValueError('SUPPLIED_SESSIONS_DIFFER_FROM_VERIFIED_CALENDAR')
    if calendar_lineage is not None and calendar_lineage != verified_calendar['lineage']:
        raise ValueError('SUPPLIED_CALENDAR_LINEAGE_MISMATCH')
    calendar_lineage = verified_calendar['lineage']
    if end > verified_calendar['current']['target_date']:
        raise ValueError('RECOMPUTATION_END_NOT_COMPLETED')
    source_report = Path(source_report).resolve()
    acquired = verified_json(source_report)
    if acquired.get('status') != 'READY' or acquired.get('data_date') != end:
        raise ValueError('COMPLETE_TARGET_DATE_ACQUISITION_REPORT_REQUIRED')
    universe_report = Path(acquired['universe']['report_path'])
    root = paths.daily_root / 'A2_historical_top40'
    run_id = run_id or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '_' + uuid.uuid4().hex[:8]
    if not re.fullmatch(r'[A-Za-z0-9_-]{3,80}', run_id):
        raise ValueError('INVALID_RUN_ID')
    work = root / 'runs' / run_id
    selected_days = [day for day in dates if start <= day <= end]
    if not selected_days or selected_days[-1] != end:
        raise ValueError('TARGET_MISSING_FROM_VERIFIED_CALENDAR')
    contract = {'start_date': start, 'end_date': end, 'source_report': str(source_report),
                'source_report_sha256': digest(source_report), 'universe_report_sha256': digest(universe_report),
                'calendar_lineage': calendar_lineage,
                'institution_policy': 'REGISTRY_EFFECTIVE_QUARTER_AND_VERIFIED_FILINGS',
                'training_cutoff_exclusive': '2026-01-01', 'feature_selection_count': 0, 'model_selection_count': 0,
                'calculate_returns': False, 'broker_action_allowed': False}
    with single_update(paths.daily_root / 'A2_today_recommendation'):
        pool = build_universe_schedule(paths, start, end, dates, str(universe_report), mode='registry25')
        if sorted(pd.to_datetime(pool['ledger'].target_date).dt.strftime('%Y-%m-%d')) != selected_days:
            raise ValueError('UNIVERSE_LEDGER_DOES_NOT_COVER_REQUESTED_SESSIONS')
        years = sorted({int(day[:4]) for day in selected_days})
        if not execute:
            return {'status': 'PLANNED', 'trading_days': len(selected_days), 'contract': contract,
                    'models': build_models(paths, work, years, execute=False)}
        work.mkdir(parents=True, exist_ok=True)
        contract_path = work / 'contract.json'
        if contract_path.exists() and verified_json(contract_path) != contract:
            raise ValueError('RESUME_INPUT_CONTRACT_CHANGED')
        save(contract_path, contract)
        emit(f'历史 Top40：重算 {len(selected_days)} 个交易日，按各日已生效 13F 股票池。')
        universe_outputs = {name: write_frame(work / 'universe' / (name + '.parquet'), pool[name])
                            for name in ('schedule', 'members', 'ledger')}
        save(work / 'universe' / 'lineage.json', {'sources': pool['lineage'], 'gaps': pool['gaps']})
        models = build_models(paths, work, years, execute=True)
        save(work / 'models.json', models)
        if any(year < 2026 for year in years):
            save(work / 'rebuilt_model_equivalence.json', verify_rebuilt_behavior(paths, models))
        all_members = pool['members'].dropna(subset=['ticker', 'moomoo_symbol']).drop_duplicates(['security_id', 'ticker', 'moomoo_symbol']).to_dict('records')
        rehab_path = source_report.parent / 'rehab_receipt.json'
        rehab = verified_json(rehab_path)
        features, lineage, gaps = build_price_features(paths, all_members, start, end, dates,
            acquired['acquisitions'], rehab, work)
        features, lineage, gaps = extend_native_2026_prices(paths, pool, features, lineage, gaps,
            dates, acquired['acquisitions'], rehab, start, end)
        native_module = Path(__file__).with_name('current_native_prices.py')
        save(work / 'price_inputs.json', {'lineage': lineage, 'gaps': gaps,
            'features': write_frame(work / 'inference_features.parquet', features),
            'native_2026_implementation': {'path': str(native_module), 'sha256': digest(native_module)}
                if any(row.get('anchor_proof', {}).get('kind') == 'NEW_13F_MEMBER_NATIVE_RAW_ANCHOR'
                       for row in lineage) else None})
        emit('历史 Top40：逐年使用对应模型预测，并在每日当期股票池内排名。')
        ranked, coverage = ranked_predictions(features, pool['schedule'], pool['members'], pool['ledger'],
                                               models, models['feature_columns'])
        outputs = {'ranked': write_frame(work / 'ranked.parquet', ranked),
                   'top40': write_frame(work / 'top40.parquet', ranked.loc[ranked['rank'].le(40)]),
                   'coverage': write_frame(work / 'coverage.parquet', coverage)}
        manifest = {'schema_version': 1, 'status': 'READY' if coverage.status.eq('READY').all() else 'PARTIAL',
            'run_id': run_id, 'generated_at': datetime.now(timezone.utc).isoformat(), **contract,
            'outputs': outputs, 'universe_outputs': universe_outputs, 'models': models,
            'trading_days': len(coverage), 'top40_complete_days': int(coverage.eligible_count.ge(40).sum()),
            'price_basis_note': 'Original forward event-date adjustment; provider event snapshot retrieved later, not certified historical publication vintages.',
            'price_manifest': {'path': str(work / 'price_inputs.json'), 'sha256': digest(work / 'price_inputs.json')},
            'runner_sha256': digest(__file__), 'report_path': str(work / 'manifest.json')}
        save(work / 'manifest.json', manifest)
        save(root / 'latest.json', manifest)
        publish_current_day(paths, acquired, manifest, ranked, coverage, pool, gaps)
        return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', default='2023-01-03')
    parser.add_argument('--end')
    parser.add_argument('--source-report')
    parser.add_argument('--run-id')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    from scripts.common.storage_paths import resolve
    paths = resolve()
    sessions, calendar = load_sessions(paths)
    latest = verified_json(paths.daily_root / 'A2_today_recommendation/latest.json')
    result = run_rebuild(paths, start=args.start, end=args.end or calendar['current']['target_date'],
        source_report=args.source_report or latest['report_path'], sessions=sessions, calendar_lineage=calendar['lineage'],
        execute=args.execute, run_id=args.run_id)
    print(json.dumps({'status': result['status'], 'trading_days': result.get('trading_days'),
                      'report_path': result.get('report_path'),
                      'top40_complete_days': result.get('top40_complete_days')}, ensure_ascii=False), flush=True)
    return 0 if result['status'] in {'READY', 'PARTIAL', 'PLANNED'} else 2


if __name__ == '__main__':
    raise SystemExit(main())
