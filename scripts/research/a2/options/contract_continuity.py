"""Source-local Call continuity diagnostics; no executable quotes or economics."""
from __future__ import annotations

import copy
import json
import math
import shutil
import time
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import requests

from scripts.common.storage_paths import resolve
from .contracts import TEMPLATE, Invalid, calendar, require
from .expression import choose_expiry
from .historical_quotes import _write_json
from .public_history import (PublicSession, _file_digest, acquire_dolt, digest,
                             normalize_observations, utcnow)

COMPLETE = {'COMPLETE', 'COMPLETE_EMPTY'}
ATTRS = ['multiplier', 'deliverable', 'adjustment_status', 'underlying_uid', 'historical_uid_status']
OBS_COLUMNS = ['date', 'act_symbol', 'source', 'source_file_id', 'source_date', 'observation_date',
    'source_contract_id', 'normalized_expiration', 'normalized_strike', 'normalized_right',
    'observation_key', 'observation_bid', 'observation_ask', 'observation_bid_size',
    'observation_ask_size', 'size_unit', 'multiplier', 'deliverable', 'underlying_uid',
    'historical_uid_status', 'adjustment_status', 'series_id', 'adjustment_id']


def absent(value):
    return value is None or (not isinstance(value, (dict, list, tuple)) and bool(pd.isna(value)))


def clean(value):
    if absent(value):
        return None
    if hasattr(value, 'item'):
        return value.item()
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), default=str)


def content_digest(frame):
    rows = [{k: clean(v) for k, v in row.items()} for row in frame.to_dict('records')]
    return digest(canonical(rows).encode())


def checked_date(value):
    require(not absent(value), 'CONTINUITY_DATE_MISSING')
    text = str(value)
    stamp = pd.Timestamp(text)
    require(not pd.isna(stamp) and stamp == stamp.normalize(), 'CONTINUITY_DATE_NOT_DATE_ONLY')
    day = stamp.date().isoformat()
    require('2023-01-01' <= day < '2026-01-01', 'CONTINUITY_DATE_OUTSIDE_PRE2026')
    return day


def raw_symbol(row):
    # Never reuse the parent's upper-cased normalized symbol as contract identity.
    return clean(row.get('act_symbol'))


def continuity_key(row, version):
    source, symbol = clean(row.get('source')), raw_symbol(row)
    if not source or not symbol or not version:
        return None
    source_id = clean(row.get('source_contract_id'))
    extras = [[name, clean(row.get(name))] for name in ('series_id', 'adjustment_id') if not absent(row.get(name))]
    if source_id:
        components = [source, version, symbol, 'SOURCE_ID', source_id, extras]
    else:
        expiry, strike, right = [clean(row.get(name)) for name in
                                ('normalized_expiration', 'normalized_strike', 'normalized_right')]
        if not expiry or not strike or right not in ('C', 'P'):
            return None
        try:
            number = Decimal(str(strike))
            if not number.is_finite():
                return None
        except InvalidOperation:
            return None
        # Exact decimal text is retained, without float conversion or rounding.
        components = [source, version, symbol, 'SOURCE_COMPOSITE', expiry, str(strike), right, extras]
    return canonical(components)


def positive_strike(value):
    try:
        number = Decimal(str(value))
        return number.is_finite() and number > 0
    except InvalidOperation:
        return False


def number_status(value, *, positive=False):
    if absent(value):
        return 'MISSING'
    try:
        number = float(value)
    except (ValueError, TypeError):
        return 'INVALID'
    if not math.isfinite(number):
        return 'NONFINITE'
    if number < 0:
        return 'NEGATIVE'
    if positive and number == 0:
        return 'ZERO_NOT_VALID_ENTRY'
    return 'ZERO_OBSERVED' if number == 0 else 'VALID_POSITIVE'


def crossed(bid, ask):
    if number_status(bid) not in ('VALID_POSITIVE', 'ZERO_OBSERVED') or number_status(ask) not in ('VALID_POSITIVE', 'ZERO_OBSERVED'):
        return None
    return float(bid) > float(ask)


def entry_candidates(opportunity, observations, version):
    """All entry Calls; expiry ordering sees no exit input or quote price."""
    day = checked_date(opportunity['option_decision_date'])
    checked_date(opportunity['planned_exit_date'])
    rows = []
    for row in observations.to_dict('records'):
        source_day = checked_date(row.get('source_date', row.get('observation_date')))
        if source_day != day or raw_symbol(row) != opportunity['entry_ticker'] or row.get('normalized_right') != 'C':
            continue
        expiry = clean(row.get('normalized_expiration'))
        try:
            dte = (pd.Timestamp(expiry).date() - pd.Timestamp(day).date()).days if expiry else None
        except (ValueError, TypeError):
            dte = None
        key = continuity_key(row, version)
        result = dict(decision_id=opportunity['decision_id'], raw_source_date=str(row.get('source_date', source_day)),
            interpreted_market_date=None, observation_time_range=None, date_evidence_status='UNKNOWN_HISTORICAL_BATCH',
            entry_symbol=raw_symbol(row), exit_symbol=opportunity['exit_ticker'],
            planned_exit_date=opportunity['planned_exit_date'], source=row['source'], source_version=version,
            source_continuity_key=key, source_contract_id=clean(row.get('source_contract_id')),
            source_file_id=row.get('source_file_id'), entry_observation_key=row.get('observation_key'),
            expiration=expiry, strike=clean(row.get('normalized_strike')), right='C',
            calendar_dte=dte, dte_30_60=dte is not None and 30 <= dte <= 60,
            dte_semantics='CALENDAR_SCREEN_AGAINST_PLAN_DATE_NOT_CERTIFIED_ENTRY_DTE',
            expiry_buffer_status='UNKNOWN_LAST_TRADE_AND_CONTRACT_TERMS',
            atm_contract_id=None, atm_status='MISSING_BOUND_0945_RAW_UNDERLYING_REFERENCE',
            entry_bid=clean(row.get('observation_bid')), entry_ask=clean(row.get('observation_ask')),
            entry_ask_status=number_status(row.get('observation_ask'), positive=True),
            entry_crossed=crossed(row.get('observation_bid'), row.get('observation_ask')),
            entry_bid_size=clean(row.get('observation_bid_size')), entry_ask_size=clean(row.get('observation_ask_size')),
            entry_size_unit=clean(row.get('size_unit')), entry_non_session_label=source_day not in SESSION_DATES)
        result.update({'entry_'+name: clean(row.get(name)) for name in ATTRS})
        rows.append(result)
    legal = [dict(expiry=r['expiration'], dte=r['calendar_dte']) for r in rows
             if r['dte_30_60'] and positive_strike(r['strike'])]
    chosen = choose_expiry(legal, 45)
    target = chosen['expiry'] if chosen else None
    counts = Counter(r['source_continuity_key'] for r in rows if r['source_continuity_key'])
    for row in rows:
        row.update(target_expiration=target,
                   in_target_expiration=target is not None and row['expiration'] == target and positive_strike(row['strike']),
                   entry_key_rows=counts[row['source_continuity_key']] if row['source_continuity_key'] else 0)
    return sorted(rows, key=lambda r: (r['expiration'] or '', Decimal(r['strike']) if positive_strike(r['strike']) else Decimal('Infinity'),
                                     r['source_continuity_key'] or '', str(r['source_file_id']), str(r['entry_observation_key'])))


SESSION_DATES = set(calendar().sessions.strftime('%Y-%m-%d'))


def economic_identity(entry, exits):
    if entry.get('entry_key_rows', 1) > 1 or len(exits) > 1:
        return 'AMBIGUOUS'
    adjusted = entry.get('entry_adjustment_status')
    if not absent(adjusted) and adjusted not in ('STANDARD', 'UNKNOWN'):
        return 'ADJUSTED_AT_ENTRY'
    if not exits:
        return 'NO_EXIT_OBSERVATION'
    exit_row = exits[0]
    if adjusted == 'STANDARD' and exit_row.get('adjustment_status') not in (None, 'STANDARD', 'UNKNOWN'):
        return 'CHANGED_AFTER_ENTRY'
    for name in ATTRS[:4]:
        a, b = entry.get('entry_'+name), exit_row.get(name)
        if not absent(a) and not absent(b) and a != 'UNKNOWN' and b != 'UNKNOWN' and a != b:
            return 'CONFLICT'
    for before, after in [('expiration', 'normalized_expiration'), ('strike', 'normalized_strike'), ('right', 'normalized_right')]:
        if clean(entry.get(before)) != clean(exit_row.get(after)):
            return 'CONFLICT'
    # Endpoint attributes and a stock UID do not prove option rights across the interval.
    return 'UNKNOWN'


def connect_exits(candidates, exits, version):
    index = {}
    for row in exits.to_dict('records'):
        day = checked_date(row.get('source_date', row.get('observation_date')))
        key = continuity_key(row, version)
        if key is not None:
            index.setdefault((day, raw_symbol(row), key), []).append(row)
    output = []
    for entry in candidates.to_dict('records'):
        key = clean(entry['source_continuity_key'])
        matches = index.get((entry['planned_exit_date'], entry['exit_symbol'], key), []) if key else []
        unique = matches[0] if len(matches) == 1 else {}
        result = dict(entry, exit_match_count=len(matches), source_key_matched=bool(matches),
            source_match_status='MISSING_ENTRY_KEY' if key is None else ('AMBIGUOUS' if len(matches)>1 or entry['entry_key_rows']>1 else 'MATCHED' if matches else 'NO_EXACT_EXIT_KEY'),
            economic_identity_status=economic_identity(entry, matches),
            economic_identity_evidence_reason='NO_BOUND_OPTION_IDENTITY_AND_INTERVAL_CORPORATE_ACTION_EVIDENCE',
            exit_source_refs=canonical([dict(file=r.get('source_file_id'), observation_key=r.get('observation_key')) for r in matches]),
            exit_observations=canonical([{k: clean(r.get(k)) for k in
                ['observation_bid','observation_ask','observation_bid_size','observation_ask_size',*ATTRS]} for r in matches]),
            exit_raw_source_date=clean(unique.get('source_date')), exit_interpreted_market_date=None,
            exit_bid=clean(unique.get('observation_bid')), exit_ask=clean(unique.get('observation_ask')),
            exit_bid_status='AMBIGUOUS' if len(matches)>1 else number_status(unique.get('observation_bid')),
            exit_crossed=crossed(unique.get('observation_bid'), unique.get('observation_ask')),
            exit_bid_size=clean(unique.get('observation_bid_size')), exit_size_unit=clean(unique.get('size_unit')),
            executable_quote_status='NOT_QUALIFIED_CLOCK_IDENTITY_SIZE', economic_pair=False)
        output.append(result)
    return pd.DataFrame(output)


class ContinuitySession(PublicSession):
    """Reuse the public transport/journal, with a read-only parent and new scope."""
    def __init__(self, source_run, output, offline):
        paths = resolve()
        self.source_run, self.output = Path(source_run).resolve(), Path(output).resolve()
        require(self.source_run.parent == paths.results_root / TEMPLATE / 'public_history', 'CONTINUITY_SOURCE_BOUNDARY')
        require(self.output.parent == paths.results_root / TEMPLATE / 'public_history_continuity', 'CONTINUITY_OUTPUT_BOUNDARY')
        self.parent = json.loads((self.source_run/'run_manifest.json').read_bytes())
        require(self.parent['research_identity'] == TEMPLATE, 'CONTINUITY_PARENT_IDENTITY')
        self.parent_cache = paths.cache_root/'options_expression_pilot_r1'/'public_history'/self.source_run.name
        self.cache = paths.cache_root/'options_expression_pilot_r1'/'public_history_continuity'/self.output.name
        self.output.mkdir(parents=True, exist_ok=True)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.path, self.offline = self.output/'run_manifest.json', offline
        if self.path.exists():
            self.manifest = json.loads(self.path.read_bytes())
            require(self.manifest['parent_manifest_sha256'] == _file_digest(self.source_run/'run_manifest.json'), 'CONTINUITY_PARENT_CHANGED')
        else:
            started = time.time()
            parent_public = len(self.parent['requests'])
            increment_cap = min(100*1024**2, self.parent['cache_limit_bytes']-self.parent['cache_bytes'], int(shutil.disk_usage(self.cache).free*.05))
            self.manifest = dict(research_identity=TEMPLATE, mode='public-history', stage='contract-continuity',
                source_run=str(self.source_run), parent_cache=str(self.parent_cache), cache=str(self.cache),
                parent_manifest_sha256=_file_digest(self.source_run/'run_manifest.json'),
                started_at_utc=utcnow(), started_epoch=started, deadline_epoch=started+7200,
                acquisition_deadline_epoch=started+6000, public_request_limit=400, research_total_limit=1200,
                inherited_public_requests=parent_public, inherited_massive_requests=12, automatic_429_retry=False,
                direct_request_limit=min(80,400-parent_public,1200-parent_public-12),
                cache_limit_bytes=increment_cap, requests=[], source_status={}, sources=copy.deepcopy(self.parent['sources']),
                acquisition_policy={'count_key_batch':1,'page_size':100},
                bounded_latency_repair={'read_timeout_seconds':60,'one_retry_request_ids':[]},
                invocation_history=[], economic_status='NOT_EVALUATED', evaluate_calls=0, economic_pairs=0,
                new_model_fits=0, new_parameter_search=0, new_template_candidates=0, commercial_spend=0, trades=0,
                date_semantics='UNKNOWN_HISTORICAL_BATCH', atm_reference='BOUND_PROJECTION_HAS_NO_0945_RAW_SPOT_OR_TIMESTAMP',
                exposure='Previously read historical observations and inherited aggregate exposure; not a blind sample',
                artifact_sha256={})
            self.save()
        require(self.manifest['source_run'] == str(self.source_run), 'CONTINUITY_SOURCE_CHANGED')
        validate_version(self)
        self.http = requests.Session()
        self.http.trust_env = False


def validate_version(session):
    pinned = session.parent['sources']['DOLT']['commit']
    require(session.manifest['sources']['DOLT']['commit'] == pinned, 'CONTINUITY_SOURCE_VERSION_CHANGED')
    for record in session.manifest['requests']:
        query = record.get('params', {}).get('q', '')
        require(record.get('source') == 'DOLT' and ("AS OF '"+pinned+"'") in query,
                'CONTINUITY_QUERY_VERSION_CHANGED')


def read_parent(session):
    freeze = session.parent['plan_freeze']
    for name, expected in [(freeze['plan_file'], freeze['plan_sha256']),
                           (freeze['identity_projection_file'], freeze['identity_projection_sha256'])]:
        require(_file_digest(session.source_run/name) == expected, 'CONTINUITY_FROZEN_INPUT_CHANGED')
    plan = json.loads((session.source_run/freeze['plan_file']).read_bytes())
    panel = pd.read_parquet(session.source_run/freeze['identity_projection_file'])
    require(len(panel) == 15000 and len(plan['selected_decision_ids']) == 249 and len(set(plan['selected_decision_ids'])) == 249,
            'CONTINUITY_PARENT_SCOPE')
    require(set(panel.loc[panel.planned,'decision_id']) == set(plan['selected_decision_ids']), 'CONTINUITY_PLAN_MEMBERSHIP')
    session.manifest['plan_freeze'] = copy.deepcopy(freeze)
    session.manifest['selected_decision_ids'] = plan['selected_decision_ids']
    session.manifest['dolt_keys'] = session.manifest.get('dolt_keys', copy.deepcopy(session.parent['dolt_keys']))
    return panel, plan


def read_observations(session, wanted):
    """Footer/date proof before reads; DOLT parts only, then entry/exit projection."""
    frames = []
    def project(frame):
        require(frame['source'].eq('DOLT').all(), 'CONTINUITY_SOURCE_MIX')
        for value in frame['source_date'].unique():
            checked_date(value)
        mask = [(str(day),symbol) in wanted for day,symbol in zip(frame.source_date, frame.act_symbol)]
        return frame.loc[mask].copy()
    parts = [(session.parent_cache, part) for part in session.parent['normalization']['parts'] if part['source'] == 'DOLT']
    parts += [(session.cache, part) for part in session.manifest.get('incremental_parts', [])]
    filters = [[('source_date','=',day),('act_symbol','=',symbol)] for day,symbol in sorted(wanted)]
    for base, part in parts:
        path = (base/part['file']).resolve()
        require(path.is_relative_to(base), 'CONTINUITY_CACHE_PATH')
        require(_file_digest(path) == part['sha256'], 'CONTINUITY_PART_CHANGED')
        file = pq.ParquetFile(path)
        names = file.schema_arrow.names
        for group in range(file.metadata.num_row_groups):
            stats = file.metadata.row_group(group).column(names.index('source_date')).statistics
            require(stats and stats.has_min_max, 'CONTINUITY_FOOTER_DATE_UNKNOWN')
            checked_date(stats.min); checked_date(stats.max)
        columns = [name for name in OBS_COLUMNS if name in names]
        # The same footer gate and pushdown apply to parent AND incremental parts.
        frame = pd.read_parquet(path, columns=columns, filters=filters) if wanted else pd.DataFrame(columns=columns)
        frames.append(project(frame))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=OBS_COLUMNS)


def summarize(panel):
    rows = []
    metrics = ['scope_count','entry_chain_present','exit_chain_present','both_date_chains','same_key_call_exit','entry_dte_candidates','target_expiration_known',
               'atm_known','target_expiration_same_key_exit','economic_identity_evidenced','both_chains_without_same_call']
    groups = [('ALL_249',panel.planned),('ORIGINAL_9',panel.selection_roles.str.contains('ORIGINAL_NINE')),
              ('MONTHLY_240',panel.planned & ~panel.selection_roles.str.contains('ORIGINAL_NINE')),
              ('POPULATION_15000',pd.Series(True,index=panel.index)),('INCIDENTAL_UNPLANNED',~panel.planned)]
    for scope, selected in groups:
        subset = panel.loc[selected]
        for metric in metrics:
            mask = pd.Series(True,index=subset.index) if metric == 'scope_count' else subset[metric].fillna(False).astype(bool)
            found = subset.loc[mask]
            rows.append(dict(scope=scope,metric=metric,denominator=len(subset),opportunities=len(found),
                new_york_decision_days=found.option_decision_date.nunique(),symbols=found.entry_ticker.nunique(),
                unknown_or_false=len(subset)-len(found),
                not_counted_reason_counts=canonical(dict(Counter(reason for value in subset.loc[~mask,'missing_reason'] for reason in json.loads(value))))))
    return rows


def analyse(session, panel, plan):
    version = session.parent['sources']['DOLT']['commit']
    selected = panel.set_index('decision_id').loc[plan['selected_decision_ids']].reset_index()
    entry_wanted = set(zip(selected.option_decision_date,selected.entry_ticker))
    entry = read_observations(session,entry_wanted)
    candidates = []
    for opportunity in selected.to_dict('records'):
        projection = entry.loc[entry.source_date.eq(opportunity['option_decision_date']) & entry.act_symbol.eq(opportunity['entry_ticker'])]
        candidates.extend(entry_candidates(opportunity,projection,version))
    candidate_frame = pd.DataFrame(candidates)
    entry_hash = content_digest(candidate_frame)
    session.manifest.setdefault('entry_projection_freezes',[]).append(dict(recorded_at_utc=utcnow(),content_sha256=entry_hash,
        rows=len(candidate_frame),before_exit_projection=True,not_blind_sample=True))
    session.save()
    # Future observations first materialized after ALL fixed entry candidates exist.
    exit_wanted = set(zip(selected.planned_exit_date,selected.exit_ticker))
    exits = read_observations(session,exit_wanted)
    contracts = connect_exits(candidate_frame,exits,version)
    require(content_digest(candidate_frame) == entry_hash,'CONTINUITY_ENTRY_MUTATED')
    exit_only = exits.loc[[(str(day), symbol) not in entry_wanted for day,symbol in zip(exits.source_date,exits.act_symbol)]]
    all_obs = pd.concat([entry,exit_only],ignore_index=True)
    chains = all_obs.groupby(['source_date','act_symbol']).size().to_dict()
    key_states = {(v['date'],v['ticker']):v for v in session.manifest['dolt_keys'].values()}
    result = panel.copy()
    require(_file_digest(session.source_run/'opportunity_coverage.parquet') == session.parent['artifact_sha256']['opportunity_coverage.parquet'], 'CONTINUITY_PARENT_COVERAGE_CHANGED')
    old = pd.read_parquet(session.source_run/'opportunity_coverage.parquet',columns=['decision_id','both_candidate_dates_present'])
    old_both = dict(zip(old.decision_id,old.both_candidate_dates_present))
    result['parent_both_date_chains'] = result.decision_id.map(old_both)
    records = []
    contract_groups = {k:g for k,g in contracts.groupby('decision_id')} if len(contracts) else {}
    for o in result.to_dict('records'):
        record = dict(o)
        for side,daycol in [('entry','option_decision_date'),('exit','planned_exit_date')]:
            pair = (o[daycol],o[side+'_ticker'])
            state = key_states.get(pair, {'status':'NOT_REQUESTED'})
            record[side+'_query_status'] = state['status']
            record[side+'_source_rows'] = chains.get(pair,0)
            record[side+'_chain_present'] = chains.get(pair,0)>0
            record[side+'_range_complete'] = state['status'] in COMPLETE
        record['both_date_chains'] = record['entry_chain_present'] and record['exit_chain_present']
        record.update(raw_date_semantics='RAW_LABEL_EQUALITY_ONLY',interpreted_market_date=None,
            observation_time_range=None,atm_known=False if o['planned'] else None,
            atm_reason='NO_BOUND_0945_RAW_REFERENCE_OR_AVAILABLE_AT',economic_pair=False,
            incidental_coverage=not o['planned'] and (record['entry_chain_present'] or record['exit_chain_present']))
        group = contract_groups.get(o['decision_id'])
        record.update(entry_call_candidates=len(group) if group is not None else 0 if o['planned'] else None,
            same_key_call_exit=bool(group.source_key_matched.any()) if group is not None else False if o['planned'] else None,
            entry_dte_candidates=bool(group.dte_30_60.any()) if group is not None else False if o['planned'] else None,
            target_expiration_known=bool(group.target_expiration.notna().any()) if group is not None else False if o['planned'] else None,
            target_expiration=next(iter(group.target_expiration.dropna()),None) if group is not None else None,
            target_expiration_same_key_exit=bool((group.in_target_expiration & group.source_key_matched).any()) if group is not None else False if o['planned'] else None,
            same_key_call_count=int(group.source_key_matched.sum()) if group is not None else 0 if o['planned'] else None,
            target_expiration_strike_count=int(group.loc[group.in_target_expiration,'strike'].nunique()) if group is not None else 0 if o['planned'] else None,
            economic_identity_evidenced=bool(group.economic_identity_status.eq('CONTINUOUS_EVIDENCE').any()) if group is not None else False if o['planned'] else None)
        record['both_chains_without_same_call'] = record['both_date_chains'] and not record['same_key_call_exit'] if o['planned'] else None
        record['missing_reason'] = canonical([f'{s}:{record[s+"_query_status"]}' for s in ('entry','exit') if not record[s+'_range_complete']] +
            ([] if record['entry_chain_present'] else ['NO_ENTRY_OBSERVED_CHAIN']) +
            ([] if record['exit_chain_present'] else ['NO_EXIT_OBSERVED_CHAIN']) + ['DATE_SEMANTICS_UNKNOWN','ATM_RAW_REFERENCE_MISSING','ECONOMIC_TERMS_UNKNOWN'])
        records.append(record)
    return contracts,pd.DataFrame(records),entry_hash


def recover_failed(session, plan):
    validate_version(session)
    if session.manifest.get('recovery_finished_at_utc'):
        return
    failed = [key for key in plan['request_keys'] if session.parent['dolt_keys'][key['request_key_id']]['status'] not in COMPLETE]
    session.manifest['recovery_plan'] = [dict(key, parent_status=session.parent['dolt_keys'][key['request_key_id']]['status'],
        impact='ENTRY_CANDIDATE_COMPLETENESS_OR_EXACT_EXIT_OBSERVATION',
        repair_basis='ONE_KEY_COUNT_AND_100_ROW_KEYSET_PAGE_REDUCE_ORIGINAL_TIMEOUT_SCOPE') for key in failed]
    session.manifest['recovery_plan_recorded_at_utc'] = utcnow()
    session.save()
    # Both sides remain in parent request order; no price or counterpart lookup.
    for key in failed:
        prior_requests = len(session.manifest['requests'])
        acquire_dolt(session,{'request_keys':[key]})
        recent = session.manifest['requests'][prior_requests:]
        stop = (session.manifest['source_status']['DOLT'].get('dependency_stop_reason') or
                session.manifest['source_status']['DOLT'].get('page_dependency_stop_reason'))
        if stop or any(r.get('http_status') in (401,403) for r in recent):
            break
        if len(session.manifest['requests']) >= session.manifest['direct_request_limit']:
            break
    session.manifest['incremental_parts'] = []
    for key in failed:
        state = session.manifest['dolt_keys'][key['request_key_id']]
        for page in state['pages']:
            path = session.cache/page['file']
            if not path.exists():
                continue  # Parent pages remain referenced in the parent index.
            require(_file_digest(path) == page['sha256'],'CONTINUITY_RECOVERY_RAW_CHANGED')
            body = json.loads(path.read_bytes())
            norm = normalize_observations(pd.DataFrame(body['rows']),'DOLT',str(path),page['downloaded_at'])
            name = page['sha256']+'.parquet'
            target = session.cache/name
            if not target.exists():
                norm.to_parquet(target,index=False)
            session.manifest['incremental_parts'].append(dict(file=name,sha256=_file_digest(target),rows=len(norm),raw_file=page['file']))
    session.manifest['recovery_finished_at_utc'] = utcnow()
    session.save()


def run_contract_continuity(source_run, output, *, offline=False, recover=False):
    require(source_run is not None and output is not None,'CONTINUITY_PATHS_REQUIRED')
    require(not (offline and recover),'CONTINUITY_OFFLINE_RECOVERY_FORBIDDEN')
    session = ContinuitySession(source_run,output,offline)
    invocation = dict(started_at_utc=utcnow(),offline=offline,recover_failed=recover,status='RUNNING',
        loaded_modules={str(p):_file_digest(p) for p in [Path(__file__),Path(__file__).with_name('public_history.py'),Path(__file__).with_name('cli.py')]})
    session.manifest['invocation_history'].append(invocation)
    before = len(session.manifest['requests'])
    session.save()
    try:
        panel,plan = read_parent(session)
        if 'before_recovery_summary' not in session.manifest:
            contracts,opportunities,entry_hash = analyse(session,panel,plan)
            session.manifest['before_recovery_summary'] = summarize(opportunities)
            session.manifest['before_recovery_content'] = {'contracts':content_digest(contracts),'opportunities':content_digest(opportunities)}
            session.save()
        if recover:
            recover_failed(session,plan)
        contracts,opportunities,entry_hash = analyse(session,panel,plan)
        summary = summarize(opportunities)
        hashes = {'contract_continuity':content_digest(contracts),'opportunity_continuity':content_digest(opportunities),'summary':digest(canonical(summary).encode())}
        prior_hashes = session.manifest.get('content_sha256')
        if offline and prior_hashes:
            require(prior_hashes == hashes,'CONTINUITY_OFFLINE_CONTENT_CHANGED')
        if not prior_hashes or prior_hashes != hashes:
            contracts.to_parquet(session.output/'contract_continuity.parquet',index=False)
            opportunities.to_parquet(session.output/'opportunity_continuity.parquet',index=False)
            pd.DataFrame(summary).to_csv(session.output/'continuity_summary.csv',index=False)
        session.manifest.update(content_sha256=hashes,summary=summary,
            rows={'contracts':len(contracts),'opportunities':len(opportunities)},
            inherited_public_requests=len(session.parent['requests']),
            public_http_requests=len(session.parent['requests'])+len(session.manifest['requests']),
            research_cumulative_http=12+len(session.parent['requests'])+len(session.manifest['requests']),
            recovery_key_status_counts=dict(Counter(session.manifest['dolt_keys'][k['request_key_id']]['status'] for k in plan['request_keys'])),
            exact_0945_eligible=0)
        for name in ['contract_continuity.parquet','opportunity_continuity.parquet','continuity_summary.csv']:
            session.manifest['artifact_sha256'][name]=_file_digest(session.output/name)
        invocation.update(status='COMPLETE',required_stage_success=True,content_sha256=hashes)
    except Exception as exc:
        invocation.update(status='FAILED',exception_type=type(exc).__name__,reason=str(exc))
        raise
    finally:
        invocation.update(finished_at_utc=utcnow(),actual_http=len(session.manifest['requests'])-before,evaluate_calls=0)
        session.manifest['owned_process_status']={'stage_finished':invocation['status']!='RUNNING','background_services_started':0,
            'pending_http_entries':sum(r['status']=='PENDING' for r in session.manifest['requests'])}
        session.save()
        session.http.close()
    return dict(required_stage_success=True,stage='contract-continuity',rows=session.manifest['rows'],
        actual_http_this_invocation=invocation['actual_http'],public_http_requests=session.manifest['public_http_requests'],
        content_sha256=hashes,evaluate_calls=0,economic_pairs=0)
