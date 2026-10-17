"""Read full-pool historical ranking evidence without recomputing any signals."""
from pathlib import Path
from functools import lru_cache
import json
from datetime import date, datetime, timezone
from math import isfinite
import pandas as pd
import pyarrow as pa

from apps.demo_console.adapters import updated_research_reader as base


def _checked_json(ref):
    path, digest = base._ref(ref)
    if base._hash(path) != digest:
        raise ValueError('STOCK_HISTORY_MANIFEST_HASH_MISMATCH')
    result = base._json(path)
    if base._hash(path) != digest:
        raise ValueError('STOCK_HISTORY_MANIFEST_CHANGED_DURING_READ')
    return result


def _frame(ref, parent, columns):
    table = base._arrow_table(ref, columns, parent=parent)
    # The original Python-row conversion discarded dictionary and index metadata.
    for index, field in enumerate(table.schema):
        if pa.types.is_dictionary(field.type):
            table = table.set_column(index, field.with_type(field.type.value_type),
                                     table.column(index).cast(field.type.value_type))
    return table.to_pandas(split_blocks=True, ignore_metadata=True)


def load_history(model, paths=None, *, include_rx=True):
    """Pin full rankings and pool membership to the currently displayed A2 run."""
    try:
        from apps.demo_console.adapters.workspace_reader import source_reference
        from apps.demo_console.adapters import rx_research_reader as rx
        parent_ref = source_reference(model)
        parent = _checked_json(parent_ref)
        hist_ref = parent['ranking_manifest']
        hist = _checked_json(hist_ref)
        rx_ref, rx_error = None, None
        if include_rx:
            try:
                rx_ref = rx.binding(parent_ref, paths)
                rx_manifest = _checked_json(rx_ref)
            except (OSError, ValueError, KeyError) as exc:
                rx_error = str(exc)
        refs = [parent_ref, hist_ref, hist['outputs']['ranked'],
                hist['universe_outputs']['ledger'], hist['universe_outputs']['members']]
        if rx_ref is not None:
            refs.extend([rx_ref, rx_manifest['outputs']['selections']])
        # Rehash even cache hits: timestamps alone cannot prove unchanged evidence.
        stamps = []
        for ref in refs:
            path, digest = base._ref(ref)
            if base._hash(path) != digest:
                raise ValueError('STOCK_HISTORY_SOURCE_HASH_MISMATCH')
            stamps.append(base._stamp(ref))
        result = dict(_cached_history(json.dumps(parent_ref, sort_keys=True),
            json.dumps(hist_ref, sort_keys=True), json.dumps(rx_ref, sort_keys=True), tuple(stamps)))
        if rx_error:
            result['rx_error'] = rx_error
        return result
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'status': 'UNAVAILABLE', 'catalog': [], 'error': str(exc)}


@lru_cache(maxsize=1)
def _cached_history(parent_json, hist_json, rx_json, stamps):
    parent_ref, hist_ref, rx_ref = map(json.loads, (parent_json, hist_json, rx_json))
    parent = _checked_json(parent_ref)
    if parent['ranking_manifest'] != hist_ref:
        raise ValueError('STOCK_HISTORY_PARENT_BINDING_CHANGED')
    hist = _checked_json(hist_ref)
    root = Path(hist_ref['path']).resolve().parent
    ranked = _frame(hist['outputs']['ranked'], root,
        ['target_date', 'ticker', 'security_id', 'rank', 'score', 'universe_id'])
    ledger = _frame(hist['universe_outputs']['ledger'], root,
        ['target_date', 'snapshot_id', 'universe_id', 'quarter'])
    members = _frame(hist['universe_outputs']['members'], root,
        ['snapshot_id', 'ticker', 'security_id', 'issuer_name', 'mapping_verified'])
    selections, rx_error = None, None
    if rx_ref is not None:
        try:
            rx_manifest = _checked_json(rx_ref)
            if base._ref(rx_manifest['parent_a2_manifest']) != base._ref(parent_ref):
                raise ValueError('STOCK_HISTORY_RX_PARENT_CHANGED')
            selections = _frame(rx_manifest['outputs']['selections'],
                Path(rx_ref['path']).resolve().parent, ['target_date', 'ticker', 'security_id', 'rank'])
            counts = selections.groupby('target_date')['rank'].agg(list)
            if (set(counts.index.astype(str)) != set(pd.to_datetime(ledger.target_date).dt.strftime('%Y-%m-%d'))
                    or any(sorted(values) != list(range(1, 21)) for values in counts)):
                raise ValueError('STOCK_HISTORY_RX_INCOMPLETE_CALENDAR')
        except (OSError, ValueError, KeyError) as exc:
            selections, rx_error = None, str(exc)
    result = prepare_history(ranked, ledger, members, selections)
    # Do not cache a mixed read if any input changed while preparing the index.
    for path, digest, size, modified in stamps:
        ref = {'path': path, 'sha256': digest}
        if base._hash(path) != digest or base._stamp(ref) != (path, digest, size, modified):
            raise ValueError('STOCK_HISTORY_SOURCE_CHANGED_DURING_READ')
    result.update(source_refs={'a2': parent_ref, 'historical': hist_ref}, rx_error=rx_error,
                  _source_stamps=stamps)
    return result


def _member_catalog(members):
    issuer_names = members.drop_duplicates('ticker', keep='last').set_index('ticker').issuer_name
    catalog = [{'ticker': ticker, 'issuer_name': str(issuer_names.loc[ticker] or ''),
                'security_ids': sorted(identities.tolist())}
               for ticker, identities in members.groupby('ticker', sort=True).security_id.unique().items()]
    return catalog


def prepare_history(ranked, ledger, members, selections=None):
    """Validate identities and build a read-only index (also used by fixtures)."""
    ranked, ledger, members = ranked.copy(), ledger.copy(), members.copy()
    for frame in (ranked, ledger):
        frame['target_date'] = pd.to_datetime(frame.target_date).dt.strftime('%Y-%m-%d')
    if ledger.empty or ledger.target_date.duplicated().any():
        raise ValueError('STOCK_HISTORY_CALENDAR_INVALID')
    ledger = ledger.sort_values('target_date')
    members = members.loc[members.mapping_verified.eq(True) & members.ticker.notna()
                          & members.security_id.notna()].copy()
    members = members.loc[members.ticker.astype(str).ne('') & members.security_id.astype(str).ne('')]
    if ranked.duplicated(['target_date', 'ticker']).any() or ranked.duplicated(['target_date', 'security_id']).any():
        raise ValueError('STOCK_HISTORY_DUPLICATE_RANK_IDENTITY')
    if not ranked.empty:
        numeric = pd.to_numeric(ranked['rank'], errors='raise')
        if (numeric < 1).any() or (numeric != numeric.astype(int)).any():
            raise ValueError('STOCK_HISTORY_INVALID_RANK')
        joined = ranked.merge(ledger, on='target_date', how='left', suffixes=('', '_ledger'), validate='many_to_one')
        if joined.snapshot_id.isna().any() or not joined.universe_id.eq(joined.universe_id_ledger).all():
            raise ValueError('STOCK_HISTORY_POOL_BINDING_MISMATCH')
        valid = set(zip(members.snapshot_id, members.ticker, members.security_id))
        if any(key not in valid for key in zip(joined.snapshot_id, joined.ticker, joined.security_id)):
            raise ValueError('STOCK_HISTORY_RANK_OUTSIDE_VERIFIED_POOL')
    if selections is not None:
        selections = selections.copy()
        selections['target_date'] = pd.to_datetime(selections.target_date).dt.strftime('%Y-%m-%d')
        if selections.duplicated(['target_date', 'ticker']).any():
            raise ValueError('STOCK_HISTORY_RX_DUPLICATE')
        valid = set(zip(ranked.loc[ranked['rank'].le(40)].target_date,
                        ranked.loc[ranked['rank'].le(40)].ticker,
                        ranked.loc[ranked['rank'].le(40)].security_id))
        if any(key not in valid for key in zip(selections.target_date, selections.ticker, selections.security_id)):
            raise ValueError('STOCK_HISTORY_RX_OUTSIDE_PARENT_TOP40')
    catalog = _member_catalog(members)
    return {'status': 'READY', 'catalog': catalog, 'start_date': ledger.target_date.min(),
            'end_date': ledger.target_date.max(), 'rx_available': selections is not None,
            '_ranked': ranked, '_ledger': ledger, '_members': members, '_rx': selections}


def _episodes(daily, flag):
    result, current = [], None
    for row in daily:
        if row[flag]:
            if current is None:
                current = {'type': flag, 'start_date': row['date'], 'end_date': row['date'], 'trading_days': 0}
                result.append(current)
            current['end_date'] = row['date']
            current['trading_days'] += 1
        else:
            current = None
    return result


def _company_chain(history, ticker, chain):
    """Only the evidence adapter can authorize joining different securities."""
    try:
        from apps.demo_console.adapters.stock_identity_display import read_identity_chain, validate_identity_chain
        parent_ref = history['source_refs']['a2']
        chain = read_identity_chain(parent_ref, ticker) if chain is None else validate_identity_chain(chain)
        if (chain.get('status') != 'VERIFIED' or chain.get('ticker') != ticker
                or base._ref(chain['parent_a2_manifest']) != base._ref(parent_ref)):
            raise ValueError('STOCK_HISTORY_COMPANY_CHAIN_BINDING_INVALID')
        return chain
    except (ImportError, OSError, ValueError, KeyError, TypeError) as exc:
        return {'status': 'UNAVAILABLE', 'error': str(exc)}


def query_history(history, ticker, start_date=None, end_date=None, security_id=None,
                  *, identity_mode='SECURITY', identity_chain=None):
    if history.get('status') != 'READY':
        return {'status': 'UNAVAILABLE', 'error': history.get('error')}
    ticker = str(ticker).strip().upper()
    candidates = history['_members'].loc[history['_members'].ticker.eq(ticker)]
    identities = sorted(set(candidates.security_id))
    if not identities:
        return {'status': 'NOT_FOUND', 'ticker': ticker, 'identities': []}
    if identity_mode not in {'SECURITY', 'VERIFIED_COMPANY'}:
        return {'status': 'INVALID_IDENTITY_MODE', 'ticker': ticker}
    company_mode = identity_mode == 'VERIFIED_COMPANY'
    if company_mode:
        checked = _company_chain(history, ticker, identity_chain)
        if checked.get('status') != 'VERIFIED':
            return {'status': 'COMPANY_CHAIN_UNAVAILABLE', 'ticker': ticker, 'identities': identities,
                    'error': checked.get('error')}
        selected_ids = checked['security_ids']
        if not set(selected_ids).issubset(identities):
            return {'status': 'COMPANY_CHAIN_UNAVAILABLE', 'ticker': ticker, 'identities': identities}
        security_id = None
    elif security_id is None and len(identities) > 1:
        return {'status': 'AMBIGUOUS_IDENTITY', 'ticker': ticker, 'identities': identities}
    else:
        security_id = security_id or identities[0]
        selected_ids = [security_id]
    if not company_mode and security_id not in identities:
        return {'status': 'NOT_FOUND', 'ticker': ticker, 'identities': identities}
    start = str(start_date or history['start_date'])[:10]
    end = str(end_date or history['end_date'])[:10]
    if start > end:
        return {'status': 'INVALID_RANGE', 'ticker': ticker}
    candidates = candidates.loc[candidates.security_id.isin(selected_ids)]
    snapshots = set(candidates.snapshot_id)
    ranks = history['_ranked']
    ranks = ranks.loc[ranks.ticker.eq(ticker) & ranks.security_id.isin(selected_ids)]
    if ranks.target_date.duplicated().any():
        return {'status': 'COMPANY_IDENTITY_OVERLAP', 'ticker': ticker, 'identities': identities}
    ranks = ranks.set_index('target_date')
    rx = history['_rx']
    rx_days = set(rx.loc[rx.ticker.eq(ticker) & rx.security_id.isin(selected_ids)].target_date) if rx is not None else set()
    daily = []
    ledger = history['_ledger']
    for row in ledger.loc[ledger.target_date.between(start, end)].itertuples():
        rank_row = ranks.loc[row.target_date] if row.target_date in ranks.index else None
        rank = int(rank_row['rank']) if rank_row is not None else None
        in_pool = row.snapshot_id in snapshots
        daily.append({'date': row.target_date, 'quarter': row.quarter, 'in_pool': in_pool,
            'security_id': str(rank_row.security_id) if rank_row is not None else None,
            'pool_security_ids': sorted(set(candidates.loc[candidates.snapshot_id.eq(row.snapshot_id)].security_id)),
            'rank': rank, 'score': float(rank_row.score) if rank_row is not None else None,
            'top20': rank is not None and rank <= 20, 'top40': rank is not None and rank <= 40,
            'rx_selected': row.target_date in rx_days,
            'status': 'RANKED' if rank is not None else 'NO_VERIFIED_RANK' if in_pool else 'OUTSIDE_POOL'})
    episodes = [item for flag in ('top20', 'top40', 'rx_selected') for item in _episodes(daily, flag)]
    ranked_days = [row for row in daily if row['rank'] is not None]
    summary = {'trading_days': len(daily), 'pool_days': sum(row['in_pool'] for row in daily),
        'ranked_days': len(ranked_days), 'unranked_pool_days': sum(row['status'] == 'NO_VERIFIED_RANK' for row in daily),
        'outside_pool_days': sum(not row['in_pool'] for row in daily),
        'best_rank': min((row['rank'] for row in ranked_days), default=None)}
    for flag in ('top20', 'top40', 'rx_selected'):
        dates = [row['date'] for row in daily if row[flag]]
        summary.update({flag + '_days': len(dates), flag + '_episodes': sum(e['type'] == flag for e in episodes),
                        flag + '_first': dates[0] if dates else None, flag + '_last': dates[-1] if dates else None})
    return {'status': 'READY', 'ticker': ticker, 'security_id': security_id, 'identities': identities,
        'identity_mode': identity_mode, 'selected_security_ids': selected_ids,
        'start_date': start, 'end_date': end, 'summary': summary, 'daily': daily, 'episodes': episodes,
        'memberships': candidates.to_dict('records'), 'rx_available': history['rx_available']}


APPLIED_IDS = ('RAW_A2', 'HGB_DIAG_5', 'HGB_FACTOR_5')


def _day(value):
    value = value.isoformat() if isinstance(value, date) else value
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('APPLIED_STOCK_INVALID_DATE')
    return value


def _append_recorded_rankings(history, rows, ledger_row, members, *, scope, coverage, defer_index=False):
    """Extend a verified pool index; never infer an unrecorded score or member."""
    day = _day(ledger_row['target_date'])
    frame = pd.DataFrame(rows, columns=['target_date', 'ticker', 'security_id', 'rank', 'score', 'universe_id'])
    if frame.empty or not frame.target_date.eq(day).all():
        raise ValueError('APPLIED_DAILY_RANKING_DATE_MISMATCH')
    ordered = frame.sort_values('rank')
    if (list(ordered['rank']) != list(range(1, len(frame) + 1))
            or not all(isfinite(float(value)) for value in ordered.score)):
        raise ValueError('APPLIED_DAILY_RANKING_INCOMPLETE_OR_NONFINITE')
    if history is None:
        result = prepare_history(frame, pd.DataFrame([ledger_row]), members)
        result.update(source_refs={}, _archive_end=day,
                      _coverage={day: coverage}, _score_scope={day: scope})
        return result
    old = history['_ranked'].loc[history['_ranked'].target_date.eq(day)]
    if not old.empty:
        common = old.merge(frame, on=['target_date', 'ticker', 'security_id'], suffixes=('_old', '_new'))
        if (len(common) != min(len(old), len(frame)) or not common.rank_old.eq(common.rank_new).all()
                or not common.score_old.eq(common.score_new).all()):
            raise ValueError('APPLIED_DAILY_RANKING_CONFLICT')
    ranked = pd.concat([history['_ranked'].loc[~history['_ranked'].target_date.eq(day)], frame], ignore_index=True)
    ledger = pd.concat([history['_ledger'].loc[~history['_ledger'].target_date.eq(day)],
                        pd.DataFrame([ledger_row])], ignore_index=True)
    member_frame = pd.concat([history['_members'], members], ignore_index=True).drop_duplicates(
        ['snapshot_id', 'ticker', 'security_id'])
    if defer_index:
        # The archive is already verified. Validate this day with the same pool
        # checks before any later full report can replace it, then build the
        # complete history index once in prepare_applied_history.
        result = prepare_history(frame, pd.DataFrame([ledger_row]), member_frame)
        ledger = ledger.sort_values('target_date')
        result.update(_ranked=ranked, _ledger=ledger,
                      start_date=ledger.target_date.min(), end_date=ledger.target_date.max())
    else:
        result = prepare_history(ranked, ledger, member_frame)
    result.update(source_refs=history.get('source_refs', {}),
                  _archive_end=history.get('_archive_end', history['end_date']),
                  _coverage={**history.get('_coverage', {}), day: coverage},
                  _score_scope={**history.get('_score_scope', {}), day: scope})
    return result


def _append_parent_top40(history, parent, *, defer_index=False):
    """Keep verified tail Top40 observations when no full daily report exists."""
    import pyarrow.dataset as ds
    ref = parent.get('outputs', {}).get('rankings')
    if not ref:
        return history
    path, digest = base._ref(ref)
    if base._hash(path) != digest:
        raise ValueError('APPLIED_PARENT_RANKING_HASH_MISMATCH')
    tail = ds.dataset(path, format='parquet').to_table(
        columns=['target_date', 'ticker', 'security_id', 'rank', 'score', 'universe_id'],
        filter=ds.field('target_date') > history['end_date']).to_pandas()
    if base._hash(path) != digest:
        raise ValueError('APPLIED_PARENT_RANKING_CHANGED_DURING_READ')
    for day, rows in tail.groupby('target_date', sort=True):
        identities = rows.universe_id.unique()
        if len(identities) != 1:
            raise ValueError('APPLIED_PARENT_POOL_IDENTITY_CONFLICT')
        pool = history['_ledger'].loc[history['_ledger'].universe_id.eq(identities[0])]
        if pool.empty:
            continue  # A later full report must provide its own verified members.
        ledger_row = {**pool.iloc[-1].to_dict(), 'target_date': _day(day)}
        members = history['_members'].loc[history['_members'].snapshot_id.eq(ledger_row['snapshot_id'])]
        history = _append_recorded_rankings(history, rows.to_dict('records'), ledger_row, members,
            scope='RECORDED_TOP40_ONLY', coverage={'status': 'PARTIAL', 'eligible_count': len(rows),
                'reason': '仅绑定补日 Top40；未保存全池排名。'}, defer_index=defer_index)
    return history


def _daily_pool_members(report, previous=None):
    day = _day(report['data_date'])
    universe = report['universe']
    snapshot = 'DAILY:' + day + ':' + universe['universe_id']
    member_ref = {'path': str(Path(universe['report_path']).parent / 'mapped_members.parquet'),
                  'sha256': universe['universe_members_sha256']}
    members = _frame(member_ref, Path(member_ref['path']).parent, ['ticker', 'security_id'])
    if len(members) != report['coverage']['mapped_count']:
        raise ValueError('APPLIED_DAILY_MEMBER_COUNT_MISMATCH')
    names = (previous.drop_duplicates(['ticker', 'security_id'], keep='last').set_index(
        ['ticker', 'security_id']).issuer_name.to_dict() if previous is not None else {})
    members = members.assign(snapshot_id=snapshot, mapping_verified=True,
        issuer_name=[names.get((row.ticker, row.security_id), '') for row in members.itertuples()])
    return members, member_ref


def _append_daily_report(history, reference, as_of, *, defer_index=False):
    report = _checked_json(reference)
    day = _day(report['data_date'])
    if day > as_of or (history is not None and day <= history.get('_archive_end', history['end_date'])):
        return history
    if (report.get('status') != 'READY' or report.get('model_id') != 'A2_HGB'
            or report.get('model_sha256') != base.MODEL_2026_SHA or day < '2026-01-01'):
        return history
    universe = report['universe']
    snapshot = 'DAILY:' + day + ':' + universe['universe_id']
    members, member_ref = _daily_pool_members(report, history['_members'] if history is not None else None)
    records = report.get('ranked_rows', report.get('rows', []))
    rows = [{key: row[key] for key in ('ticker', 'security_id', 'rank', 'score', 'universe_id')}
            | {'target_date': day} for row in records]
    if 'ranked_rows' in report and len(rows) != report['coverage']['eligible_count']:
        raise ValueError('APPLIED_DAILY_SCORE_COUNT_MISMATCH')
    result = _append_recorded_rankings(history, rows,
        {'target_date': day, 'snapshot_id': snapshot, 'universe_id': universe['universe_id'],
         'quarter': universe.get('quarter', '')}, members,
        scope='FULL_VERIFIED_POOL' if 'ranked_rows' in report else 'RECORDED_TOP20_ONLY',
        coverage={**report['coverage'], 'universe_member_count': universe.get('universe_member_count'),
                  'status': 'PARTIAL' if report['coverage'].get('excluded_count') else 'READY'},
        defer_index=defer_index)
    result['source_refs'] = {**result['source_refs'], 'daily/' + day: reference,
                             'daily_members/' + day: member_ref}
    result['_archive_end'] = history.get('_archive_end', history['end_date']) if history is not None else day
    return result


def _raw_binding_diagnostic(raw_history, package, row, fields):
    """One failing identity and pinned roles, never numeric scores or prices."""
    day=row["signal_date"]
    def refs(source,names):
        result={}
        for name in names:
            value=source.get(name)
            if isinstance(value,dict) and isinstance(value.get("path"),str) and isinstance(value.get("sha256"),str):
                result[name]={"path":value["path"],"sha256":value["sha256"]}
        return result
    raw_roles=("a2","historical","daily/"+day,"daily_members/"+day)
    shared_roles=["frozen/test2026/predictions.parquet","performance_extension/manifest",
                  "history/"+day+".json","history_revision/"+day+".json"]
    if package.get("shared_scores",{}).get("current",{}).get("signal_date")==day:
        shared_roles.extend(("current/report.json","current/selected_hgb_features.parquet"))
    detail={"signal_date":day,"ticker":row["ticker"],"security_id":row["security_id"],"fields":fields,
        "raw_source_roles":refs(raw_history.get("source_refs",{}),raw_roles),
        "shared_score_source_roles":refs(package.get("source_refs",{}),shared_roles)}
    encoded=json.dumps(detail,ensure_ascii=True,sort_keys=True,separators=(",",":"))
    if len(encoded)>4096:
        detail.update(raw_source_roles={},shared_score_source_roles={},source_role_size_limit=True)
        encoded=json.dumps(detail,ensure_ascii=True,sort_keys=True,separators=(",",":"))
    return "APPLIED_SHARED_SCORE_RAW_BINDING_MISMATCH:"+encoded


def _project_input_rankings(reference, keys):
    """Decode recorded input columns only for the already accepted Top40 keys."""
    from scripts.common.json_projection import _parser_type, metadata_fields
    path,digest=base._ref(reference)
    if path.stat().st_size>32*1024*1024 or base._hash(path)!=digest:
        raise ValueError('APPLIED_INPUT_SOURCE_SIZE_OR_HASH_MISMATCH')
    result,count={},0
    with path.open('rb') as handle:
        parser=_parser_type()(handle)
        parser.descend(('ranked_rows',));parser.expect(b'[');parser.white()
        while parser.peek()!=b']':
            count+=1
            if count>4096:
                raise ValueError('APPLIED_INPUT_SOURCE_ROW_LIMIT')
            start=parser.tell()
            identity=parser.metadata_fields({'ticker','security_id'})
            end=parser.tell()
            key=(identity.get('ticker'),identity.get('security_id'))
            if key in keys:
                here=handle.tell();handle.seek(start)
                projection=_parser_type()(handle);projection.base=start
                row=projection.metadata_fields({'ticker','security_id','rank','score','universe_id'})
                handle.seek(here)
                if not 0<=start<end<=path.stat().st_size or key in result:
                    raise ValueError('APPLIED_INPUT_SOURCE_KEY_OR_OFFSET_CONFLICT')
                result[key]=row
            parser.white();separator=parser.take()
            if separator==b']':break
            if separator!=b',':
                raise ValueError('APPLIED_INPUT_SOURCE_STRUCTURE_CHANGED')
            parser.white()
        else:parser.take()
    if base._hash(path)!=digest:
        raise ValueError('APPLIED_INPUT_SOURCE_CHANGED_DURING_READ')
    return result,count


def _input_metadata(path, expected, names, *, branch=()):
    from scripts.common.json_projection import _parser_type
    path=Path(path)
    if path.stat().st_size>32*1024*1024 or base._hash(path)!=expected:
        raise ValueError('APPLIED_INPUT_METADATA_SIZE_OR_HASH_MISMATCH')
    with path.open('rb') as handle:
        parser=_parser_type()(handle)
        if branch:parser.descend(tuple(branch))
        result=parser.metadata_fields(set(names))
    if base._hash(path)!=expected:
        raise ValueError('APPLIED_INPUT_METADATA_CHANGED_DURING_READ')
    return result


def _repair_report_metadata(path, expected):
    """The existing acceptance owner consumes only these report metadata fields."""
    return _input_metadata(path,expected,{'run_id','repair_lineage'})


def _knowledge_stamp(value):
    if not isinstance(value,str):raise ValueError('APPLIED_INPUT_KNOWLEDGE_CLOCK_REQUIRED')
    stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError('APPLIED_INPUT_KNOWLEDGE_CLOCK_MUST_BE_AWARE')
    return stamp.astimezone(timezone.utc)


def _accepted_input_vintage(raw_history, package, day, rows):
    """Retain the publisher's chosen archive and its own exact Raw input version."""
    from scripts.research.a2.portfolio import selected_hgb as owner
    current=package.get('shared_scores',{}).get('current',{})
    if day>=str(current.get('signal_date') or current.get('requested_signal_date') or ''):
        raise ValueError('APPLIED_ARCHIVED_INPUT_REQUIRES_PAST_SIGNAL')
    reference=package.get('source_refs',{}).get('history/'+day+'.json')
    if reference is None:
        raise ValueError('APPLIED_ARCHIVED_INPUT_REFERENCE_UNAVAILABLE')
    if base._ref(reference)[0].stat().st_size>32*1024*1024:
        raise ValueError('APPLIED_ARCHIVED_INPUT_SIZE_LIMIT')
    folder=Path(package['package_path']).resolve().parent/'history'
    selected_path,selected_hash,receipt=owner._revision_selection(package,folder,day,
        report_metadata_loader=_repair_report_metadata)
    if (selected_path,selected_hash)!=base._ref(reference):
        raise ValueError('APPLIED_ARCHIVED_INPUT_SELECTION_MISMATCH')
    if selected_path.stat().st_size>32*1024*1024:
        raise ValueError('APPLIED_ARCHIVED_INPUT_SIZE_LIMIT')
    snapshot=_checked_json(reference)
    if (snapshot['signal_date']!=day or snapshot.get('policy_id',owner.LEGACY_POLICY)
            !=package.get('policy_id',owner.LEGACY_POLICY)):
        raise ValueError('APPLIED_ARCHIVED_INPUT_DATE_OR_POLICY_MISMATCH')
    archived={(row['ticker'],row['security_id']):row for row in snapshot['shared_scores']['rows']}
    expected={(row['ticker'],row['security_id']):{key:value for key,value in row.items() if key!='signal_date'}
              for row in rows}
    if archived!=expected:
        raise ValueError('APPLIED_ARCHIVED_SHARED_SCORE_BINDING_MISMATCH')
    source=snapshot['source_refs']['current/report.json']
    canonical=raw_history.get('source_refs',{}).get('daily/'+day)
    members=raw_history.get('source_refs',{}).get('daily_members/'+day)
    if canonical is None or members is None or base._ref(source)==base._ref(canonical):
        raise ValueError('APPLIED_ARCHIVED_DISTINCT_INPUT_REFERENCE_REQUIRED')
    source_path,digest=base._ref(source)
    if source_path.stat().st_size>32*1024*1024 or base._hash(source_path)!=digest:
        raise ValueError('APPLIED_ARCHIVED_RAW_SOURCE_HASH_OR_SIZE_MISMATCH')
    metadata=_catalog_report_metadata(source_path,digest,input_binding=True)
    if base._hash(source_path)!=digest:
        raise ValueError('APPLIED_ARCHIVED_RAW_SOURCE_CHANGED_DURING_READ')
    knowledge=_knowledge_stamp(package['generated_at'])
    captured=_knowledge_stamp(snapshot.get('generated_at'))
    produced=_knowledge_stamp(metadata.get('generated_at'))
    if not produced<=captured<=knowledge<=datetime.now(timezone.utc):
        raise ValueError('APPLIED_INPUT_KNOWLEDGE_ORDER_MISMATCH')
    universe=metadata['universe']
    ledger=raw_history['_ledger'].loc[raw_history['_ledger'].target_date.eq(day)]
    if (metadata.get('status')!='READY' or metadata.get('data_date')!=day
            or metadata.get('model_id')!='A2_HGB' or metadata.get('model_sha256')!=base.MODEL_2026_SHA
            or len(ledger)!=1 or universe.get('universe_id')!=ledger.iloc[0].universe_id
            or universe.get('quarter')!=ledger.iloc[0].quarter
            or universe.get('universe_members_sha256')!=members.get('sha256')
            or snapshot['report_binding']['selected_hgb_features']!=
                {key:metadata.get('selected_hgb_features',{}).get(key) for key in ('path','sha256')}):
        raise ValueError('APPLIED_ARCHIVED_RAW_MODEL_POOL_OR_FEATURE_BINDING_MISMATCH')
    inputs,count=_project_input_rankings(source,set(expected))
    if count!=metadata.get('coverage',{}).get('eligible_count') or set(inputs)!=set(expected):
        raise ValueError('APPLIED_ARCHIVED_RAW_INPUT_COVERAGE_MISMATCH')
    for key,row in inputs.items():
        if (row.get('universe_id')!=universe['universe_id'] or row.get('rank')!=expected[key]['raw_rank']
                or row.get('score')!=expected[key]['raw_score']):
            raise ValueError('APPLIED_ARCHIVED_RAW_INPUT_BINDING_MISMATCH')
    verified={name:ref for name,ref in snapshot['source_refs'].items()
        if name not in snapshot.get('observation_only_source_refs',[])}
    verified['accepted_archive']=reference
    if receipt is not None:
        verified['accepted_revision_receipt']=receipt
        receipt_path,receipt_hash=base._ref(receipt)
        lineage=_input_metadata(receipt_path,receipt_hash,{'supersedes','repair_lineage'})
        parent_ref=lineage['supersedes'];parent_path,parent_hash=base._ref(parent_ref)
        previous=_input_metadata(parent_path,parent_hash,{'source_refs','observation_only_source_refs','generated_at'})
        if _knowledge_stamp(previous.get('generated_at'))>captured:
            raise ValueError('APPLIED_INPUT_PARENT_KNOWLEDGE_ORDER_MISMATCH')
        verified['superseded_archive']=parent_ref
        for name,ref in previous['source_refs'].items():
            if name not in previous.get('observation_only_source_refs',[]):verified['parent/'+name]=ref
        audit_ref=lineage['repair_lineage'];audit_path,audit_hash=base._ref(audit_ref)
        audit=_input_metadata(audit_path,audit_hash,{'generated_at','created_at'})
        for field in ('generated_at','created_at'):
            if field in audit and _knowledge_stamp(audit[field])>captured:
                raise ValueError('APPLIED_INPUT_REPAIR_KNOWLEDGE_ORDER_MISMATCH')
        verified['repair_lineage']=audit_ref
    return {'accepted_archive':reference,'raw_input':source,'canonical_raw':canonical,
        'knowledge_as_of':package['generated_at'],'verification_refs':verified}


def prepare_applied_history(raw_history, package, as_of, *, current_only=False, isolate_shared_source=False):
    """Join only recorded score/target dates to the existing security index."""
    from apps.demo_console.adapters import selected_strategies_reader as selected
    package = selected.validate_package(package)
    as_of = _day(as_of)
    ledger = raw_history['_ledger'].loc[raw_history['_ledger'].target_date.le(as_of)]
    if ledger.empty:
        return {'status': 'UNAVAILABLE', 'catalog': [], 'error': '所查日期前没有股票池记录。'}
    ranked = raw_history['_ranked'].loc[raw_history['_ranked'].target_date.le(as_of)]
    members = raw_history['_members'].loc[raw_history['_members'].snapshot_id.isin(ledger.snapshot_id)]
    bounded = prepare_history(ranked, ledger, members)
    bounded.update(source_refs=raw_history.get('source_refs', {}),
                   _coverage=raw_history.get('_coverage', {}), _score_scope=raw_history.get('_score_scope', {}))
    bounded['_rank_index'] = _ranked_index(ranked)
    bounded['_raw_target_dates'] = {day for day, values in ranked.groupby('target_date')['rank']
                                    if set(range(1, 21)).issubset(set(values))}
    scores = [] if current_only else selected.score_history(package=package, end_date=as_of)
    current = package.get('shared_scores', {}).get('current', {})
    if current.get('status') == 'READY' and _day(current['signal_date']) <= as_of:
        snapshot = selected.score_snapshot(current['signal_date'], package=package)
        # score_snapshot selects the accepted current revision for this day.
        # Keep the replay's earlier input in the package, but never mix it into
        # the same-day stock view before binding the selected current rows.
        scores = [row for row in scores if row['signal_date'] != snapshot['signal_date']]
        scores.extend({**row, 'signal_date': snapshot['signal_date']} for row in snapshot['rows'])
    # Resolve the same exact tuple keys once; retain ordered per-record checks.
    index = bounded['_rank_index']
    score_keys = pd.MultiIndex.from_tuples(
        [(row['signal_date'], row['ticker']) for row in scores], names=index.index.names)
    raw_positions = index.index.get_indexer(score_keys)
    raw_ranks, raw_scores = index['rank'].to_numpy(), index['score'].to_numpy()
    raw_identities = index['security_id'].to_numpy(copy=False)
    by_day,source_bindings,score_errors = {},{},{}
    score_days={}
    for row in scores:
        score_days.setdefault(row['signal_date'],[]).append(row)
    for ordinal, row in enumerate(scores):
        day = _day(row['signal_date'])
        if day <= as_of:
            key = (row['ticker'], row['security_id'])
            previous = by_day.setdefault(day, {}).get(key)
            if previous is not None and previous != row:
                raise ValueError('APPLIED_SHARED_SCORE_DATE_CONFLICT')
            position = raw_positions[ordinal]
            if position >= 0 and raw_identities[position] != row['security_id']:
                position = -1
            if position >= 0:
                fields=[name for name,mismatch in (("raw_rank",raw_ranks[position]!=row["raw_rank"]),
                    ("raw_score",raw_scores[position]!=row["raw_score"])) if mismatch]
                if fields and day not in source_bindings and day not in score_errors:
                    try:
                        source_bindings[day]=_accepted_input_vintage(bounded,package,day,score_days[day])
                    except (OSError,ValueError,KeyError,TypeError) as exc:
                        error=_raw_binding_diagnostic(bounded,package,row,fields)
                        if not isolate_shared_source:
                            raise ValueError(error) from exc
                        score_errors[day]=error+';input_vintage='+str(exc)
                        by_day.pop(day,None)
            recorded = _rank_record(bounded, day, row['ticker'])
            identity = recorded['security_id'] if recorded is not None else None
            if identity is not None and identity != row['security_id']:
                if not isolate_shared_source:
                    raise ValueError('APPLIED_SHARED_SCORE_SECURITY_BINDING_MISMATCH')
                score_errors[day]='APPLIED_SHARED_SCORE_SECURITY_BINDING_MISMATCH'
                by_day.pop(day,None)
            if day not in score_errors:
                by_day[day][key] = row
    by_day={day:rows for day,rows in by_day.items() if day not in score_errors}
    targets = {sid: {} for sid in APPLIED_IDS}
    for sid in APPLIED_IDS:
        strategy = package.get('raw_reference', {}) if sid == 'RAW_A2' else package['strategies'][sid]
        for target in strategy.get('targets', []):
            day = _day(target['signal_date'])
            if day <= as_of:
                targets[sid][day] = {'status': 'READY', 'signal_date': day,
                    'kind': 'RAW_RULE_TARGET' if sid == 'RAW_A2' else 'HISTORICAL_SIGNAL_TARGET',
                    'rows': {row['ticker']: row for row in target['rows']}}
        for target in strategy.get('application_history', []):
            day = _day(target['signal_date'])
            if day <= as_of:
                targets[sid][day] = {'status': 'READY', 'signal_date': day,
                    'kind': 'ARCHIVED_CASH_START_TARGET', 'account_basis': 'CASH_START',
                    'execution_status': 'TARGET_ONLY', 'source_ref': target['source_ref'],
                    'rows': {row['ticker']: row for row in target['rows']}}
        application = strategy.get('application', {})
        day = application.get('signal_date') or application.get('requested_signal_date')
        if day and _day(day) <= as_of:
            ready = application.get('status') in ('READY', 'LATEST_AVAILABLE_SIGNAL') and application.get('signal_date') == day
            targets[sid][day] = {'status': 'READY' if ready else 'BLOCKED',
                'signal_date': application.get('signal_date'), 'kind': 'CURRENT_CASH_START_TARGET',
                'reason': application.get('reason'),
                'rows': {row['ticker']: row for row in application.get('rows', [])} if ready else {}}
    for sid in APPLIED_IDS[1:]:
        targets[sid]={day:target for day,target in targets[sid].items() if day not in score_errors}
    observed = set(ledger.target_date) | set(by_day)
    observed.update(day for days in targets.values() for day in days)
    requested = current.get('requested_signal_date') or current.get('signal_date')
    if requested and _day(requested) <= as_of:
        observed.add(requested)
    return {'status': 'READY', 'catalog': bounded['catalog'], 'start_date': min(observed),
            'end_date': max(observed), 'as_of': as_of, 'available_dates': tuple(sorted(observed)),
            'source_refs': {**bounded.get('source_refs', {}), 'selected': {
                'path': package.get('package_path'), 'sha256': package.get('package_sha256')}},
            'raw_history': bounded, '_package': package, '_scores': by_day, '_targets': targets,
            '_score_source_refs':source_bindings,'_score_errors':score_errors}


def _recheck_input_vintages(history):
    """Cached input bindings retain exact hashes without hiding independent data."""
    errors=dict(history.get('_score_errors',{}));checked={}
    for day,binding in history.get('_score_source_refs',{}).items():
        for reference in binding.get('verification_refs',{}).values():
            try:
                path,digest=base._ref(reference)
                key=(path,digest)
                if key not in checked:checked[key]=base._hash(path)==digest
                if not checked[key]:raise ValueError('APPLIED_ARCHIVED_INPUT_SOURCE_HASH_MISMATCH')
            except (OSError,ValueError,KeyError,TypeError) as exc:
                errors[day]=str(exc);break
    if errors==history.get('_score_errors',{}):return history
    return {**history,'_score_errors':errors,
        '_scores':{day:rows for day,rows in history['_scores'].items() if day not in errors},
        '_targets':{sid:{day:target for day,target in targets.items() if sid=='RAW_A2' or day not in errors}
                    for sid,targets in history['_targets'].items()}}


def _catalog_report_metadata(path, expected, *, input_binding=False):
    """C-level explicit metadata projection; unknown arrays never become objects.

    Project only the existing consumer fields for a directory or accepted input
    binding. All source identity, vintage, PIT and numeric guards stay downstream.
    """
    import pyarrow.json as arrow_json
    path = Path(path)
    size = path.stat().st_size
    if size > 32 * 1024 * 1024 or base._hash(path) != expected:
        raise ValueError('APPLIED_INPUT_METADATA_SIZE_OR_HASH_MISMATCH')
    stamp = base._stamp({'path': str(path), 'sha256': expected})
    universe = [('universe_members_sha256', pa.string()), ('universe_id', pa.string()), ('quarter', pa.string())]
    fields = [('data_date', pa.string()), ('status', pa.string()),
        ('model_id', pa.string()), ('model_sha256', pa.string())]
    if input_binding:
        fields += [('generated_at', pa.string()), ('universe', pa.struct(universe)),
            ('coverage', pa.struct([('eligible_count', pa.int64())])),
            ('selected_hgb_features', pa.struct([('path', pa.string()), ('sha256', pa.string())]))]
    else:
        fields += [('universe', pa.struct([('report_path', pa.string()), *universe])),
            ('coverage', pa.struct([('mapped_count', pa.int64())]))]
    schema = pa.schema(fields)
    with path.open('rb') as stream:
        # The installed Arrow parser can terminate on a top-level null. The existing lexical owner
        # rejects every non-object before any native decoder sees the source.
        from scripts.common.json_projection import _parser_type
        _parser_type()(stream).expect(b'{')
        stream.seek(0)
        table = arrow_json.read_json(stream,
            read_options=arrow_json.ReadOptions(block_size=max(65536, 1 << max(0, size - 1).bit_length()), use_threads=False),
            parse_options=arrow_json.ParseOptions(explicit_schema=schema,
                unexpected_field_behavior='ignore', newlines_in_values=True))
    if table.num_rows != 1:
        raise ValueError('APPLIED_STOCK_CATALOG_SINGLE_JSON_OBJECT_REQUIRED')
    if base._hash(path) != expected or base._stamp({'path': str(path), 'sha256': expected}) != stamp:
        raise ValueError('APPLIED_INPUT_METADATA_CHANGED_DURING_READ')
    result = table.to_pylist()[0]
    if input_binding and any(not isinstance(result.get(name), dict)
            for name in ('universe', 'coverage', 'selected_hgb_features')):
        raise ValueError('APPLIED_INPUT_METADATA_REQUIRED_BINDING_OBJECT')
    return result



def load_applied_catalog(*, package=None, raw_model=None, as_of=None):
    """Pool directory only: no rank/score, HGB archive or MAIN numeric history.

    CATALOG_READY proves the directory sources, not a historical score query.
    The original full loader remains mandatory after a ticker is selected.
    """
    from apps.demo_console.adapters import selected_strategies_reader as selected, workspace_reader as workspace
    try:
        package = selected.load_package() if package is None else selected.validate_package(package)
        raw_model = workspace.load_overview(source=workspace.LATEST) if raw_model is None else raw_model
        if not workspace.is_updated(raw_model) or raw_model.error:
            raise ValueError('APPLIED_STOCK_REQUIRES_INDEPENDENT_RAW_REFERENCE')
        as_of = _day(as_of or raw_model.decision_date)
        parent_ref = workspace.source_reference(raw_model)
        parent = _checked_json(parent_ref)
        hist_ref = parent['ranking_manifest']
        hist = _checked_json(hist_ref)
        refs = [parent_ref, hist_ref, hist['outputs']['ranked'],
                hist['universe_outputs']['ledger'], hist['universe_outputs']['members']]
        root = Path(hist_ref['path']).resolve().parent
        ledger = _frame(hist['universe_outputs']['ledger'], root,
            ['target_date', 'snapshot_id', 'universe_id', 'quarter'])
        ledger['target_date'] = pd.to_datetime(ledger.target_date).dt.strftime('%Y-%m-%d')
        if ledger.empty or ledger.target_date.duplicated().any():
            raise ValueError('STOCK_HISTORY_CALENDAR_INVALID')
        ledger = ledger.sort_values('target_date')
        archive_end = ledger.target_date.max()
        members = _frame(hist['universe_outputs']['members'], root,
            ['snapshot_id', 'ticker', 'security_id', 'issuer_name', 'mapping_verified'])
        members = members.loc[members.mapping_verified.eq(True) & members.ticker.notna() & members.security_id.notna()].copy()
        members = members.loc[members.ticker.astype(str).ne('') & members.security_id.astype(str).ne('')]
        # This is the original tail's date/pool binding only. Never decode its
        # ticker/rank/score columns before the user requests an actual history.
        tail_ref = parent.get('outputs', {}).get('rankings')
        if tail_ref:
            refs.append(tail_ref)
            tail = _frame(tail_ref, Path(parent_ref['path']).resolve().parent, ['target_date', 'universe_id'])
            tail['target_date'] = pd.to_datetime(tail.target_date).dt.strftime('%Y-%m-%d')
            for day, rows in tail.loc[tail.target_date.gt(archive_end) & tail.target_date.le(as_of)].groupby('target_date', sort=True):
                identities = rows.universe_id.unique()
                if len(identities) != 1:
                    raise ValueError('APPLIED_PARENT_POOL_IDENTITY_CONFLICT')
                pool = ledger.loc[ledger.universe_id.eq(identities[0])]
                if not pool.empty:
                    ledger = pd.concat([ledger, pd.DataFrame([{**pool.iloc[-1].to_dict(), 'target_date': day}])], ignore_index=True)
        source_refs = {'a2': parent_ref, 'historical': hist_ref}
        for reference in _applied_report_refs(parent, package):
            path, digest = base._ref(reference)
            report = _catalog_report_metadata(path, digest)
            refs.append(reference)
            day = _day(report['data_date'])
            if (day > as_of or day <= archive_end or report.get('status') != 'READY'
                    or report.get('model_id') != 'A2_HGB' or report.get('model_sha256') != base.MODEL_2026_SHA
                    or day < '2026-01-01'):
                continue
            added, member_ref = _daily_pool_members(report, members)
            refs.append(member_ref)
            universe = report['universe']
            ledger = pd.concat([ledger.loc[~ledger.target_date.eq(day)], pd.DataFrame([{
                'target_date': day, 'snapshot_id': added.snapshot_id.iloc[0],
                'universe_id': universe['universe_id'], 'quarter': universe.get('quarter', '')}])], ignore_index=True)
            members = pd.concat([members, added], ignore_index=True).drop_duplicates(['snapshot_id', 'ticker', 'security_id'])
            source_refs.update({'daily/' + day: reference, 'daily_members/' + day: member_ref})
        ledger = ledger.loc[ledger.target_date.le(as_of)]
        if ledger.empty:
            return {'status': 'UNAVAILABLE', 'catalog': [], 'error': '所查日期前没有股票池记录。'}
        members = members.loc[members.snapshot_id.isin(ledger.snapshot_id)]
        dates = set(ledger.target_date)
        # Only already validated package clocks; no archive rows or performance
        # numerical history is read. The full loader confirms these on query.
        dates.update(day for day in selected.workspace_dates(package) if day <= as_of)
        stamps = []
        for ref in refs:
            path, digest = base._ref(ref)
            if base._hash(path) != digest:
                raise ValueError('APPLIED_STOCK_CATALOG_SOURCE_HASH_MISMATCH')
            stamps.append(base._stamp(ref))
        return {'status': 'CATALOG_READY', 'catalog': _member_catalog(members),
            'start_date': min(dates), 'end_date': max(dates), 'as_of': as_of,
            'source_refs': source_refs, '_catalog_only': True, '_catalog_source_stamps': tuple(stamps)}
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        return {'status': 'UNAVAILABLE', 'catalog': [], 'error': str(exc)}


def bind_catalog_history(catalog, history):
    """A light directory can never be substituted for the original full checks."""
    if history.get('status') != 'READY':
        return history
    try:
        for path, digest, size, modified in catalog.get('_catalog_source_stamps', ()):
            ref = {'path': path, 'sha256': digest}
            if base._hash(path) != digest or base._stamp(ref) != (path, digest, size, modified):
                raise ValueError('APPLIED_STOCK_CATALOG_SOURCE_CHANGED')
        if catalog['catalog'] != history['catalog'] or catalog['as_of'] != history['as_of']:
            raise ValueError('APPLIED_STOCK_CATALOG_BINDING_CHANGED')
        return history
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'status': 'UNAVAILABLE', 'catalog': [], 'error': str(exc)}


def load_applied_history(*, package=None, raw_model=None, as_of=None):
    """Load existing full-pool evidence and the selected package; no inference."""
    from apps.demo_console.adapters import selected_strategies_reader as selected, workspace_reader as workspace
    try:
        package = selected.load_package() if package is None else selected.validate_package(package)
        raw_model = workspace.load_overview(source=workspace.LATEST) if raw_model is None else raw_model
        if not workspace.is_updated(raw_model) or raw_model.error:
            raise ValueError('APPLIED_STOCK_REQUIRES_INDEPENDENT_RAW_REFERENCE')
        as_of = _day(as_of or raw_model.decision_date)
        raw = load_history(raw_model, include_rx=False)
        if raw['status'] != 'READY':
            return raw
        parent_ref = workspace.source_reference(raw_model)
        hist_ref = raw['source_refs']['historical']
        parent, hist = _checked_json(parent_ref), _checked_json(hist_ref)
        extra = [ref for ref in (hist.get('outputs', {}).get('coverage'),
                                 parent.get('outputs', {}).get('rankings')) if ref]
        for ref in _applied_report_refs(parent, package):
            report = _checked_json(ref)
            extra.append(ref)
            if (report.get('data_date', '') > raw['end_date'] and report.get('status') == 'READY'
                    and report.get('model_id') == 'A2_HGB'
                    and report.get('model_sha256') == base.MODEL_2026_SHA):
                universe = report['universe']
                extra.append({'path': str(Path(universe['report_path']).parent / 'mapped_members.parquet'),
                              'sha256': universe['universe_members_sha256']})
        # Reuse the existing validated index and hash/stamp cache contract. A focus
        # or cutoff change does not change the immutable source binding.
        stamps, seen = [], set()
        for ref in extra:
            path, digest = base._ref(ref)
            if (path, digest) in seen:
                continue
            if base._hash(path) != digest:
                raise ValueError('APPLIED_STOCK_SOURCE_HASH_MISMATCH')
            stamps.append(base._stamp(ref))
            seen.add((path, digest))
        complete = _cached_applied_history(json.dumps(parent_ref, sort_keys=True),
            json.dumps(hist_ref, sort_keys=True), json.dumps(package, sort_keys=True),
            tuple(raw['_source_stamps']), tuple(stamps))
        return _cutoff_applied_history(_recheck_input_vintages(complete), as_of)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'status': 'UNAVAILABLE', 'catalog': [], 'error': str(exc)}


def _applied_report_refs(parent, package):
    refs = list(parent.get('recommendation_reports', []))
    current = package.get('source_refs', {}).get('current/report.json')
    if current:
        refs.append(current)
    unique = {}
    for ref in refs:
        unique.setdefault(base._ref(ref), ref)
    return list(unique.values())


@lru_cache(maxsize=1)
def _cached_applied_history(parent_json, hist_json, package_json, source_stamps, extra_stamps):
    """Memoize a joined view of existing evidence, never a mutable latest pointer."""
    from apps.demo_console.adapters import selected_strategies_reader as selected
    parent_ref, hist_ref, package = map(json.loads, (parent_json, hist_json, package_json))
    parent, hist = _checked_json(parent_ref), _checked_json(hist_ref)
    raw = dict(_cached_history(parent_json, hist_json, 'null', source_stamps))
    raw['_archive_end'] = raw['end_date']
    coverage_ref = hist.get('outputs', {}).get('coverage')
    if coverage_ref:
        coverage = _frame(coverage_ref, Path(coverage_ref['path']).parent,
            ['target_date', 'status', 'eligible_count', 'universe_member_count', 'mapped_count', 'excluded_count'])
        raw['_coverage'] = {str(row['target_date']): row for row in coverage.to_dict('records')}
    raw = _append_parent_top40(raw, parent, defer_index=True)
    refs = _applied_report_refs(parent, package)
    days = [raw['end_date'], *selected.workspace_dates(package)]
    days.extend(_day(_checked_json(ref)['data_date']) for ref in refs)
    full_cutoff = max(days)
    for ref in refs:
        raw = _append_daily_report(raw, ref, full_cutoff, defer_index=True)
    complete = prepare_applied_history(raw, package, full_cutoff, isolate_shared_source=True)
    for path, digest, size, modified in (*source_stamps, *extra_stamps):
        ref = {'path': path, 'sha256': digest}
        if base._hash(path) != digest or base._stamp(ref) != (path, digest, size, modified):
            raise ValueError('APPLIED_STOCK_SOURCE_CHANGED_DURING_READ')
    return complete


def _cutoff_applied_history(history, as_of):
    """Slice the verified snapshot; later observations cannot leak into queries."""
    observed = tuple(day for day in history.get('available_dates', ()) if day <= as_of)
    if not observed:
        return {'status': 'UNAVAILABLE', 'catalog': [], 'error': '所查日期前没有股票池记录。'}
    raw = history['raw_history']
    if as_of >= history['end_date']:
        return {**history, 'as_of': as_of, 'raw_history': dict(raw)}
    ledger = raw['_ledger'].loc[raw['_ledger'].target_date.le(as_of)]
    if ledger.empty:
        return {'status': 'UNAVAILABLE', 'catalog': [], 'error': '所查日期前没有股票池记录。'}
    members = raw['_members'].loc[raw['_members'].snapshot_id.isin(ledger.snapshot_id)]
    catalog = _member_catalog(members)
    refs = {key: ref for key, ref in raw.get('source_refs', {}).items()
            if not key.startswith(('daily/', 'daily_members/')) or key.rsplit('/', 1)[-1] <= as_of}
    bounded = {**raw, 'catalog': catalog, 'end_date': ledger.target_date.max(),
        '_ledger': ledger, '_members': members,
        '_ranked': raw['_ranked'].loc[raw['_ranked'].target_date.le(as_of)],
        '_rank_index': raw['_rank_index'].loc[raw['_rank_index'].index.get_level_values(0) <= as_of],
        '_raw_target_dates': {day for day in raw['_raw_target_dates'] if day <= as_of},
        '_coverage': {day: rows for day, rows in raw.get('_coverage', {}).items() if day <= as_of},
        '_score_scope': {day: scope for day, scope in raw.get('_score_scope', {}).items() if day <= as_of},
        'source_refs': refs}
    return {**history, 'catalog': catalog, 'as_of': as_of, 'end_date': observed[-1],
        'available_dates': observed, 'raw_history': bounded,
        'source_refs': {**refs, 'selected': history['source_refs']['selected']},
        '_scores': {day: rows for day, rows in history['_scores'].items() if day <= as_of},
        '_score_source_refs':{day:refs for day,refs in history.get('_score_source_refs',{}).items() if day<=as_of},
        '_score_errors':{day:error for day,error in history.get('_score_errors',{}).items() if day<=as_of},
        '_targets': {sid: {day: rows for day, rows in targets.items() if day <= as_of}
                     for sid, targets in history['_targets'].items()}}


def _ranked_index(ranked):
    """One exact day/ticker index holds identity and numeric lookup values."""
    return ranked[['target_date', 'ticker', 'security_id', 'rank', 'score']].set_index(
        ['target_date', 'ticker'])


def _rank_record(raw, day, ticker):
    index = raw['_rank_index']
    key = (day, ticker)
    return index.loc[key] if key in index.index else None


def _strategy_row(history, day, ticker, security_id, company='', in_pool=None):
    raw = history['raw_history']
    recorded = _rank_record(raw, day, ticker)
    found = recorded if recorded is not None and recorded['security_id'] == security_id else None
    rank = int(found['rank']) if found is not None else None
    raw_score = float(found['score']) if found is not None else None
    score = history['_scores'].get(day, {}).get((ticker, security_id))
    expected_identity = recorded['security_id'] if recorded is not None else None
    if expected_identity is None:
        scored = [identity for name, identity in history['_scores'].get(day, {}) if name == ticker]
        expected_identity = scored[0] if len(scored) == 1 else None
    if expected_identity is None and in_pool is True:
        ledger = raw['_ledger'].loc[raw['_ledger'].target_date.eq(day)]
        if not ledger.empty:
            ids = set(raw['_members'].loc[raw['_members'].snapshot_id.eq(ledger.iloc[0].snapshot_id)
                      & raw['_members'].ticker.eq(ticker), 'security_id'])
            expected_identity = next(iter(ids)) if len(ids) == 1 else None
    result = {}
    for sid in APPLIED_IDS:
        hgb = sid != 'RAW_A2'
        model_rank = score['hgb_rank'] if hgb and score else rank if not hgb else None
        model_score = score['pred_hgb'] if hgb and score else raw_score if not hgb else None
        score_status = ('SCORED' if model_score is not None else 'OUTSIDE_RAW_TOP40' if hgb and rank and rank > 40
                        else 'NO_VERIFIED_SCORE')
        target = history['_targets'][sid].get(day)
        if sid == 'RAW_A2' and target is None and rank is not None:
            if day in raw['_raw_target_dates']:
                target = {'status': 'READY', 'signal_date': day, 'kind': 'RAW_RULE_TARGET', 'rows': {}}
        refused=hgb and day in history.get('_score_errors',{})
        target_status = 'UNAVAILABLE' if refused else target['status'] if target else 'NO_RECORDED_TARGET'
        if refused:score_status='NO_VERIFIED_SCORE'
        explicit_target = target is not None and ticker in target['rows']
        known_identity = (security_id is not None and security_id == expected_identity
                          and (score is not None or rank is not None or explicit_target))
        known = target is not None and target['status'] == 'READY' and known_identity
        input_rank=score['raw_rank'] if hgb and score else rank if not hgb else None
        raw_top20=input_rank<=20 if input_rank is not None else None
        eligible = raw_top20
        if hgb and raw_top20 is not True:
            eligible = (float(target['rows'].get(ticker, {}).get('weight_before', 0.)) > 0) if known else None
        weight = None
        if known:
            if sid == 'RAW_A2':
                weight = .05 if rank is not None and rank <= 20 else 0. if rank is not None else None
            else:
                weight = float(target['rows'].get(ticker, {}).get('target_weight', 0.))
        result[sid] = {'ticker': ticker, 'security_id': security_id, 'company': company,
            'raw_rank':input_rank,'raw_input_score':score['raw_score'] if hgb and score else None,
            'raw_input_source_ref':history.get('_score_source_refs',{}).get(day,{}).get('raw_input') if hgb else None,
            'model_rank': model_rank, 'score': model_score,
            'raw_top20': raw_top20, 'eligible': eligible,
            'selected': weight > 0 if weight is not None else None, 'target_weight': weight,
            'target_kind': target['kind'] if target else None,
            'account_basis': target.get('account_basis') if target else None,
            'execution_status': target.get('execution_status', 'TARGET_ONLY') if target else None,
            'weight_date': target['signal_date'] if target else None,
            'status': 'SCORED' if model_score is not None else score_status,
            'score_status': score_status, 'target_status': target_status}
    return result


def _current_applied_history(day, package, raw_model):
    """Read one accepted current decision; historical vintages keep their own binding."""
    from apps.demo_console.adapters import selected_strategies_reader as selected, workspace_reader as workspace
    package = selected.validate_package(package)
    current = package.get('shared_scores', {}).get('current', {})
    if current.get('status') != 'READY' or not current.get('signal_date'):
        return None
    day = _day(day or current['signal_date'])
    if day != current['signal_date']:
        return None
    if not '2026-01-01' <= day < '2027-01-01':
        raise ValueError('APPLIED_CURRENT_SIGNAL_OUTSIDE_TEST_BOUNDARY')
    raw_model = workspace.load_overview(source=workspace.LATEST) if raw_model is None else raw_model
    if (not workspace.is_updated(raw_model) or raw_model.error
            or raw_model.decision_date != day):
        raise ValueError('APPLIED_CURRENT_RAW_REFERENCE_UNAVAILABLE')
    parent_ref = workspace.source_reference(raw_model)
    parent = _checked_json(parent_ref)
    report_ref = package.get('source_refs', {}).get('current/report.json')
    if (not report_ref or parent.get('ranking_end_date') != day
            or base._ref(report_ref) not in {base._ref(ref) for ref in parent.get('recommendation_reports', [])}):
        raise ValueError('APPLIED_CURRENT_REPORT_PARENT_BINDING_MISMATCH')
    report = _checked_json(report_ref)
    if (report.get('status') != 'READY' or report.get('data_date') != day
            or report.get('model_id') != 'A2_HGB'
            or report.get('model_sha256') != base.MODEL_2026_SHA
            or 'ranked_rows' not in report):
        raise ValueError('APPLIED_CURRENT_REPORT_IDENTITY_MISMATCH')
    raw = _append_daily_report(None, report_ref, day)
    ranked = raw['_ranked']
    top = ranked.loc[ranked['rank'].le(40)]
    expected = {(row.ticker, row.security_id) for row in top.itertuples()}
    snapshot = selected.score_snapshot(day, package=package)
    if len(top) != 40 or expected != {(row['ticker'], row['security_id']) for row in snapshot['rows']}:
        raise ValueError('APPLIED_CURRENT_TOP40_BINDING_MISMATCH')
    recorded = sorted((row.ticker, int(row.rank), float(row.score)) for row in top.itertuples())
    displayed = sorted((row.ticker, row.rank, row.score) for row in raw_model.ranking)
    if displayed != recorded:
        raise ValueError('APPLIED_CURRENT_RAW_RANKING_BINDING_MISMATCH')
    raw['source_refs']['a2'] = parent_ref
    # The one-day index is joined only to this package's accepted current score.
    # No historical rank is rewritten, inferred, or silently accepted here.
    result = prepare_applied_history(raw, package, day, current_only=True)
    for ref in (parent_ref, report_ref, raw['source_refs']['daily_members/' + day]):
        path, digest = base._ref(ref)
        if base._hash(path) != digest:
            raise ValueError('APPLIED_CURRENT_SOURCE_CHANGED_DURING_READ')
    return result


def load_applied_rankings(day, *, package=None, raw_model=None, history=None):
    from apps.demo_console.adapters import selected_strategies_reader as selected
    try:
        if package is not None or history is None:
            package = selected.load_package() if package is None else package
            current = _current_applied_history(day, package, raw_model)
            if current is not None:
                history = current
        if history is None:
            history = load_applied_history(package=package, raw_model=raw_model, as_of=day)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        history = {'status': 'UNAVAILABLE', 'error': str(exc)}
    if history.get('status') != 'READY':
        return {'status': 'UNAVAILABLE', 'requested_date': day, 'actual_signal_date': None,
                'source_refs': history.get('source_refs', {}), 'coverage': {},
                'error': history.get('error'), 'strategies': {sid: {'status': 'UNAVAILABLE', 'rows': []} for sid in APPLIED_IDS}}
    day = _day(day or history['end_date'])
    if day > history['as_of']:
        raise ValueError('APPLIED_RANKING_EXCEEDS_OBSERVATION_CUTOFF')
    raw = history['raw_history']
    records = raw['_ranked'].loc[raw['_ranked'].target_date.eq(day)]
    scores = history['_scores'].get(day, {})
    names = {(row.ticker, row.security_id) for row in records.itertuples()} | set(scores)
    members = raw['_members']
    companies = members.drop_duplicates(['ticker', 'security_id'], keep='last').set_index(
        ['ticker', 'security_id']).issuer_name.to_dict()
    rows = {sid: [] for sid in APPLIED_IDS}
    for ticker, identity in sorted(names):
        views = _strategy_row(history, day, ticker, identity, companies.get((ticker, identity), ''), True)
        for sid, row in views.items():
            if sid == 'RAW_A2' and row['score'] is not None or sid != 'RAW_A2' and (ticker, identity) in scores:
                rows[sid].append(row)
    snapshot = selected.score_snapshot(day, package=history['_package'])
    strategies = {}
    for sid in APPLIED_IDS:
        current = rows[sid]
        target = history['_targets'][sid].get(day)
        status = 'AVAILABLE' if current else 'BLOCKED' if sid != 'RAW_A2' and snapshot.get('status') == 'BLOCKED' else 'UNAVAILABLE'
        raw_scope = raw.get('_score_scope', {}).get(day, 'FULL_VERIFIED_POOL')
        strategies[sid] = {'status': status, 'actual_signal_date': day if current else None,
            'scope': raw_scope if sid == 'RAW_A2' else 'RAW_TOP40',
            'rank_kind': 'RAW_MODEL_SCORE' if sid == 'RAW_A2' else 'SHARED_HGB_MODEL_SCORE',
            'target_status': target['status'] if target else 'READY' if sid == 'RAW_A2' and current and
                set(range(1, 21)).issubset({r['raw_rank'] for r in current}) else 'NO_RECORDED_TARGET',
            'target_kind': 'RAW_RULE_TARGET' if sid == 'RAW_A2' else target['kind'] if target else None,
            'account_basis': target.get('account_basis') if target else None,
            'execution_status': target.get('execution_status', 'TARGET_ONLY') if target else None,
            'weight_date': target['signal_date'] if target else day if sid == 'RAW_A2' and current else None,
            'rows': sorted(current, key=lambda row: (row['model_rank'], row['ticker']))}
    return {'status': 'READY' if all(leaf['status'] == 'AVAILABLE' for leaf in strategies.values()) else 'PARTIAL',
            'requested_date': day, 'actual_signal_date': day if names else None,
            'coverage': raw.get('_coverage', {}).get(day, {}), 'source_refs': history['source_refs'],
            'strategies': strategies}


def query_applied_history(history, ticker, start_date=None, end_date=None, security_id=None,
                          *, identity_mode='SECURITY', identity_chain=None):
    if history.get('status') != 'READY':
        return {'status': 'UNAVAILABLE', 'error': history.get('error')}
    end = min(_day(end_date or history['as_of']), history['as_of'])
    start = _day(start_date or history['start_date'])
    result = query_history(history['raw_history'], ticker, start, end, security_id,
                           identity_mode=identity_mode, identity_chain=identity_chain)
    if result['status'] != 'READY':
        return result
    raw_rows = {row['date']: row for row in result['daily']}
    identities = result['selected_security_ids']
    daily = []
    for day in history['available_dates']:
        if not start <= day <= end:
            continue
        row = raw_rows.get(day, {'date': day, 'in_pool': None, 'pool_security_ids': [], 'status': 'NO_POOL_RECORD'})
        active = [identity for identity in identities if (result['ticker'], identity) in history['_scores'].get(day, {})]
        identity = row.get('security_id') or (row['pool_security_ids'][0] if len(row['pool_security_ids']) == 1 else
                    active[0] if len(active) == 1 else identities[0] if len(identities) == 1 else None)
        company = next((member['issuer_name'] for member in result['memberships'] if member['security_id'] == identity), '')
        daily.append({**row, 'strategies': _strategy_row(history, day, result['ticker'], identity, company, row['in_pool'])})
    summary = {}
    for sid in APPLIED_IDS:
        values = [row['strategies'][sid] for row in daily]
        summary[sid] = {'scored_days': sum(row['score'] is not None for row in values),
                        'known_target_days': sum(isinstance(row['selected'], bool) for row in values),
                        'selected_days': sum(row['selected'] is True for row in values)}
    return {**result, 'start_date': start, 'end_date': end, 'daily': daily,
            'source_refs': history['source_refs'], 'strategy_summary': summary,
            'score_source_errors':{day:error for day,error in history.get('_score_errors',{}).items() if start<=day<=end}}

