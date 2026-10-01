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
    frame = base.pq.read_table(verify(ref['path'], ref['sha256'])).to_pandas()
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
        ranking_ref = historical['outputs']['ranked']
        ranking_path, ranking_sha = base._ref(ranking_ref)
        if base._hash(ranking_path) != ranking_sha:
            raise ValueError('RAW_DISPLAY_RANKINGS_HASH_MISMATCH')
        identity_rows = base.pq.read_table(ranking_path, columns=['target_date', 'security_id'],
            filters=[('ticker', '=', ticker)]).to_pylist()
        identities = {str(row['security_id']) for row in identity_rows
                      if start <= str(row['target_date'])[:10] <= end}
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
        entries = [row for row in inputs['lineage'] if row['ticker'] == ticker]
        current_ref = contract.get('current_report')
        if current_ref:
            _checked_json(current_ref)
            current, report = prices._current_entries(current_ref['path'],
                Path(historical_ref['path']).resolve(), historical_ref['sha256'], verify)
            entries.extend(row for row in current if row['ticker'] == ticker)
        if not entries:
            raise ValueError('RAW_DISPLAY_ACCEPTED_LINEAGE_MISSING')
        parts, actions = [], {}
        store = _store(paths) if any(row.get('alternate_bridge') or row.get('execution_bridge') for row in entries) else None
        for entry in entries:
            accepted = set(entry.get('cusips') or entry.get('security_ids') or [entry.get('security_id')])
            if not identities.intersection(accepted):
                continue
            parts.append(prices._raw(entry, verify, store, {}))
            for action in _split_actions(entry, verify, end):
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
