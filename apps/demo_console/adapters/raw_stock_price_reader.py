"""Display-only USD quotes from the same immutable raw leaves as A2 execution.

Raw USD quotes stay untouched; a separate split-only display series is optional.
No requests, publication, or portfolio calculation.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from apps.demo_console.adapters import updated_research_reader as base


def _checked_json(ref):
    path, digest = base._ref(ref)
    if base._hash(path) != digest:
        raise ValueError('RAW_DISPLAY_REFERENCE_HASH_MISMATCH')
    return base._json(path)


def _combine(parts, ticker, start, end):
    from scripts.research.a2.inference.historical_top40_prices import _merge_raw
    frame = _merge_raw(parts)
    frame = frame.loc[frame.trade_date.between(pd.Timestamp(start), pd.Timestamp(end))]
    if frame.empty:
        return ()
    if (frame.trade_date.duplicated().any() or
            not np.isfinite(frame[['open', 'close']].to_numpy(float)).all() or
            (frame[['open', 'close']] <= 0).any().any()):
        raise ValueError('RAW_DISPLAY_INVALID_PRICE')
    return tuple(dict(date=row.trade_date.date().isoformat(), ticker=ticker,
                      raw_open=float(row.open), raw_close=float(row.close),
                      currency='USD', adjustment='RAW') for row in frame.itertuples())


def _split_actions(entry, verify, end):
    ref = entry['rehab']
    path = verify(ref['path'], ref['sha256'])  # Keep the entire-file identity check.
    names = base.pq.read_schema(path).names
    columns = [name for name in ('code', 'ex_div_date', 'join_base', 'join_ert',
        'split_base', 'split_ert', 'forward_adj_factorA', 'forward_adj_factorB') if name in names]
    frame = base.pq.read_table(path, columns=columns).to_pandas()
    frame = frame.loc[frame.code.eq(entry['code'])]
    result = []
    for row in frame.to_dict('records'):
        day = str(row['ex_div_date'])[:10]
        if day > end:
            continue
        old, new = row.get('join_base'), row.get('join_ert')
        kind = 'REVERSE_SPLIT'
        if not (pd.notna(old) and pd.notna(new) and old > 0 and new > 0):
            old, new = row.get('split_base'), row.get('split_ert')
            kind = 'SPLIT'
        if not (pd.notna(old) and pd.notna(new) and old > 0 and new > 0):
            continue
        if old == new:
            continue
        factor = float(old) / float(new)
        # Cash or mixed actions are not guessed into a split-only series.
        factor_a = row.get('forward_adj_factorA')
        if (row.get('forward_adj_factorB') != 0 or not isinstance(factor_a, (int, float)) or
                not np.isfinite(factor_a) or not np.isclose(factor_a, factor, rtol=1e-12, atol=0)):
            result.append(dict(event_date=day, kind='UNSUPPORTED_MIXED_OR_INCONSISTENT_SPLIT',
                old_shares=float(old), new_shares=float(new), price_multiplier=None,
                source_ref={k: ref[k] for k in ('path', 'sha256')}))
            continue
        result.append(dict(event_date=day, kind=kind, old_shares=float(old),
            new_shares=float(new), price_multiplier=factor,
            source_ref={k: ref[k] for k in ('path', 'sha256')}))
    return result


def _with_split_display(rows, actions, basis_date):
    """Historical prices expressed in share units at the selected end date."""
    result = []
    for row in rows:
        factor = float(np.prod([a['price_multiplier'] for a in actions
                                if row['date'] < a['event_date'] <= basis_date]))
        result.append({**row, 'split_adjusted_open': row['raw_open'] * factor,
            'split_adjusted_close': row['raw_close'] * factor,
            'split_basis_date': basis_date})
    return tuple(result)


class _RawDayCache(dict):
    """Keep at most one validated grouped vendor day during one chart read."""
    def __setitem__(self, key, value):
        self.clear()
        super().__setitem__(key, value)


def _identities(entry):
    return {str(value) for value in (entry.get('cusips') or entry.get('security_ids')
            or [entry.get('security_id')]) if value is not None and str(value)}


def _bind_current_identity(entry, historical):
    """Reuse identity only when the exact original raw anchor is unchanged."""
    if _identities(entry):
        return entry
    anchors = {(str(Path(ref['path']).resolve()), ref['sha256'])
               for ref in entry.get('raw_sources', ()) if ref.get('role') == 'ORIGINAL_ANCHOR'}
    matches = [row for row in historical if row['ticker'] == entry['ticker']
               and row.get('code') == entry.get('code')
               and row.get('anchor_date') == entry.get('anchor_date')
               and anchors and anchors == {(str(Path(ref['path']).resolve()), ref['sha256'])
                   for ref in row.get('raw_sources', ()) if ref.get('role') == 'ORIGINAL_ANCHOR'}]
    if len(matches) != 1 or not _identities(matches[0]):
        raise ValueError('RAW_DISPLAY_CURRENT_IDENTITY_ANCHOR_UNPROVEN')
    return {**entry, 'security_ids': sorted(_identities(matches[0]))}


def _execution_bridges(contract, report, ticker):
    if not contract.get('price_inputs'):
        return ()
    inputs = _checked_json(contract['price_inputs'])
    recorded = inputs.get('execution_bridges', [])
    if not isinstance(recorded, list):
        raise ValueError('RAW_DISPLAY_EXECUTION_INPUT_BINDING_INVALID')
    bridges = [row for row in recorded if row.get('ticker') == ticker]
    if not bridges:
        return ()
    if (report is None or inputs.get('end_date') != report['data_date']
            or inputs.get('price_basis') != 'PIT_FORWARD_REHAB_INDEX'):
        raise ValueError('RAW_DISPLAY_EXECUTION_INPUT_BINDING_INVALID')
    if len(bridges) > 1:
        raise ValueError('RAW_DISPLAY_DUPLICATE_EXECUTION_BRIDGE')
    return bridges


def _ranking_identities(reference, ticker, start, end):
    path, digest = base._ref(reference)
    if base._hash(path) != digest:
        raise ValueError('RAW_DISPLAY_RANKINGS_HASH_MISMATCH')
    rows = base.pq.read_table(path, columns=['target_date', 'security_id'],
        filters=[('ticker', '=', ticker), ('target_date', '>=', start),
                 ('target_date', '<=', end)]).to_pylist()
    return {str(row['security_id']) for row in rows if row.get('security_id') is not None
            and start <= str(row['target_date'])[:10] <= end}


def read_raw_stock_prices(a2_reference, ticker, start, end, *, paths=None, security_id=None, identity_chain=None):
    """Return status, rows(date/raw_open/raw_close), source_refs, error.

    Ticker identity is bound to published rankings and accepted price lineage.
    Raw prices are retrospective display quotes, never decision-time knowledge.
    """
    refs = []
    try:
        from scripts.research.a2.evaluation import demo_performance_prices as prices
        from scripts.research.a2.inference.historical_top40_prices import _store
        if paths is None:
            from scripts.common.storage_paths import resolve
            paths = resolve()
        manifest = _checked_json(a2_reference)
        if manifest.get('source_id') != 'A2_UPDATED_RESEARCH':
            raise ValueError('RAW_DISPLAY_A2_PARENT_REQUIRED')
        contract = _checked_json(manifest['evaluation_contract'])
        historical_ref = manifest['ranking_manifest']
        historical = _checked_json(historical_ref)
        if contract['ranking_manifest'] != historical_ref:
            raise ValueError('RAW_DISPLAY_HISTORICAL_BINDING_MISMATCH')
        start, end = str(start)[:10], str(end)[:10]
        if not historical['start_date'] <= start <= end <= manifest['ranking_end_date']:
            raise ValueError('RAW_DISPLAY_OUTSIDE_PUBLISHED_RANGE')
        identities = _ranking_identities(historical['outputs']['ranked'], ticker, start, end)
        if contract.get('rankings'):
            if base._ref(contract['rankings']) != base._ref(manifest['outputs']['rankings']):
                raise ValueError('RAW_DISPLAY_CURRENT_RANKING_BINDING_MISMATCH')
            identities |= _ranking_identities(contract['rankings'], ticker, start, end)
        if not identities:
            raise ValueError('RAW_DISPLAY_TICKER_NOT_IN_PUBLISHED_RANKINGS')
        if security_id is not None:
            if str(security_id) not in identities:
                raise ValueError('RAW_DISPLAY_SECURITY_IDENTITY_MISMATCH')
            identities = {str(security_id)}
        elif len(identities) != 1:
            if identity_chain is None:
                raise ValueError('RAW_DISPLAY_AMBIGUOUS_SECURITY_IDENTITY')
            from apps.demo_console.adapters.stock_identity_display import validate_identity_chain
            chain = validate_identity_chain(identity_chain)
            if (chain['ticker'] != ticker or not identities <= set(chain['security_ids']) or
                    base._ref(chain['parent_a2_manifest']) != base._ref(a2_reference)):
                raise ValueError('RAW_DISPLAY_SECURITY_IDENTITY_MISMATCH')

        def verify(path, expected):
            path = Path(path).resolve()
            if base._hash(path) != expected:
                raise ValueError('RAW_DISPLAY_SOURCE_HASH_MISMATCH')
            refs.append({'path': str(path), 'sha256': expected})
            return path

        inputs = _checked_json(historical['price_manifest'])
        historical_entries = [row for row in inputs['lineage'] if row['ticker'] == ticker]
        entries = list(historical_entries)
        report = None
        current_ref = contract.get('current_report')
        if current_ref:
            _checked_json(current_ref)
            current, report = prices._current_entries(current_ref['path'],
                Path(historical_ref['path']).resolve(), historical_ref['sha256'], verify)
            entries.extend(_bind_current_identity(row, historical_entries)
                           for row in current if row['ticker'] == ticker)
        supplement_ref = contract.get('additional_price_manifest')
        if supplement_ref:
            supplements = prices.read_execution_supplement(supplement_ref['path'],
                historical_ref['sha256'], verify, supplement_ref['sha256'])
            entries.extend(row for row in supplements if row['ticker'] == ticker)
        if not entries:
            raise ValueError('RAW_DISPLAY_ACCEPTED_LINEAGE_MISSING')
        bridges = _execution_bridges(contract, report, ticker)
        parts, actions = [], {}
        raw_cache = _RawDayCache()
        store = _store(paths) if bridges or any(row.get('alternate_bridge') or row.get('execution_bridge') for row in entries) else None
        for entry in entries:
            accepted = _identities(entry)
            if not identities.intersection(accepted):
                continue
            raw = prices._raw(entry, verify, store, raw_cache)
            parts.append(raw)
            action_entries = [entry]
            for bridge in bridges:
                if entry not in historical_entries or entry['raw_end'] != bridge['historical_end']:
                    continue
                parts.append(prices.replay_recorded_execution_bridge(bridge, raw, ticker,
                    report['data_date'], verify, store, raw_cache))
                action_entries.append({**entry, 'rehab': bridge['rehab']})
            for action in (action for source in action_entries
                           for action in _split_actions(source, verify, end)):
                day = action['event_date']
                if day in actions and any(actions[day][key] != action[key] for key in
                        ('kind', 'old_shares', 'new_shares', 'price_multiplier')):
                    raise ValueError('RAW_DISPLAY_SPLIT_EVIDENCE_CONFLICT')
                actions[day] = action
        if not parts:
            raise ValueError('RAW_DISPLAY_SECURITY_IDENTITY_MISMATCH')
        rows = _combine(parts, ticker, start, end)
        all_actions = sorted(actions.values(), key=lambda row: row['event_date'])
        split_actions = [row for row in all_actions if row['price_multiplier'] is not None]
        unsupported = [row for row in all_actions if row['price_multiplier'] is None
                       and start < row['event_date'] <= end]
        rows = _with_split_display(rows, split_actions, end)
        if unsupported:
            rows = tuple({**row, 'split_adjusted_open': None, 'split_adjusted_close': None} for row in rows)
        return dict(status='READY' if rows else 'UNAVAILABLE', rows=rows,
                    source_refs=refs, corporate_actions=split_actions,
                    unsupported_corporate_actions=unsupported,
                    split_display_status='UNAVAILABLE_UNSUPPORTED_ACTION' if unsupported else 'READY',
                    split_basis_date=end,
                    split_display_basis='VERIFIED_SPLITS_ONLY_NOT_TOTAL_RETURN',
                    error=None if rows else 'RAW_DISPLAY_NO_DATES')
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return dict(status='UNAVAILABLE', rows=(), source_refs=refs, error=str(exc))
