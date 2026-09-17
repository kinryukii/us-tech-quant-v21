"""Explicit daily price units for the SPY archive selector; no provider mutation."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds

from .contracts import Invalid, calendar, require
from .public_history import _file_digest

STATUS = 'QUALIFIED_TRADE_BASIS_USD_DAILY_REFERENCE'
INPUT_COLUMNS = ['identity', 'market_date', 'source_close']
REFERENCE_COLUMNS = ['ticker', 'date', 'close', 'adjustment', 'source', 'currency']


def _positive(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise Invalid('INVALID_PRICE_OR_SPLIT_RATIO') from None
    require(number.is_finite() and number > 0, 'INVALID_PRICE_OR_SPLIT_RATIO')
    return number


def trade_basis(record, qualification):
    """Map one declared source unit; RAW never applies a split transform twice."""
    q = qualification
    day = record['market_date']
    require(isinstance(day, str) and len(day) == 10 and
            '2024-01-01' <= day <= '2024-12-31', 'PRICE_OUTSIDE_2024')
    require(day in set(calendar().sessions.strftime('%Y-%m-%d')), 'PRICE_NOT_MARKET_SESSION')
    require(q.get('identity') == record.get('identity') == 'SPY' and
            q.get('currency') == 'USD' and q.get('session') == 'REGULAR', 'PRICE_IDENTITY_UNITS_INVALID')
    require(all(isinstance(q.get(k), str) and q[k].strip() for k in
                ('provider', 'source_version', 'source_field', 'date_semantics', 'session_basis')),
            'PRICE_SOURCE_CONTRACT_MISSING')
    require(q.get('status') == STATUS and q.get('evidence'), 'PRICE_SOURCE_NOT_QUALIFIED')
    factor, basis = Decimal(1), q.get('source_basis')
    if basis == 'SPLIT_ADJUSTED':
        chain = q.get('split_basis') or {}
        require(chain.get('status') == 'COMPLETE_EVENT_CHAIN' and
                chain.get('direction') == 'C_ADJ_EQUALS_C_RAW_DIV_F' and
                chain.get('evidence_ref') in [e['path'] for e in q['evidence']], 'SPLIT_CHAIN_UNPROVED')
        start, end = chain.get('coverage_start', ''), chain.get('basis_end', '')
        try:
            require(date.fromisoformat(start) <= date.fromisoformat(day) <= date.fromisoformat(end),
                    'SPLIT_CHAIN_COVERAGE_INVALID')
        except (ValueError, TypeError):
            raise Invalid('SPLIT_CHAIN_COVERAGE_INVALID') from None
        events = chain.get('events')
        require(isinstance(events, list) and (events or chain.get('empty_events_certified') is True),
                'EMPTY_SPLIT_CHAIN_UNPROVED')
        seen = set()
        for event in events:
            require(event.get('kind') == 'SPLIT', 'NON_SPLIT_ADJUSTMENT')
            effective = event.get('effective_date')
            try:
                date.fromisoformat(effective)
            except (ValueError, TypeError):
                raise Invalid('SPLIT_EVENT_DATE_INVALID') from None
            require(start <= effective <= end and effective not in seen, 'SPLIT_EVENT_RANGE_OR_DUPLICATE')
            seen.add(effective)
            ratio = _positive(event.get('new_shares')) / _positive(event.get('old_shares'))
            if day < effective:
                factor *= ratio
    else:
        require(basis == 'RAW', 'PRICE_BASIS_NOT_TRADE_COMPATIBLE')
    close = _positive(record.get('source_close'))
    return dict(identity='SPY', market_date=day, source=q['provider'], source_version=q['source_version'],
                source_field=q['source_field'], currency='USD', session='REGULAR', source_close=float(close),
                source_basis=basis, factor_to_trade_basis=float(factor), close_trade_basis=float(close * factor),
                factor_basis='RAW_IDENTITY_NO_SPLIT_TRANSFORM' if basis == 'RAW' else 'BOUND_SPLIT_EVENT_CHAIN',
                basis_status='TRADE_BASIS_QUALIFIED', evidence_ref=[e['path'] for e in q['evidence']])


def read_trade_references(binding, missing):
    """Validate date/identity projection before materializing any economic column."""
    require(binding['allowed_reference_dates'] == missing, 'REFERENCE_ADDITION_SCOPE_CHANGED')
    q, path = binding['qualification'], Path(binding['path'])
    require(q.get('status') == STATUS, 'PRICE_SOURCE_NOT_QUALIFIED')
    for evidence in q.get('evidence', []):
        require(_file_digest(Path(evidence['path'])) == evidence['sha256'], 'REFERENCE_EVIDENCE_CHANGED')
    require(_file_digest(path) == binding['sha256'], 'REFERENCE_ADDITIONS_CHANGED')
    dataset = ds.dataset(path, format='parquet')
    require(set(dataset.schema.names) == set(INPUT_COLUMNS), 'PRICE_INPUT_COLUMNS_CHANGED')
    keys = dataset.to_table(columns=['identity', 'market_date']).to_pandas()
    require(0 < len(keys) <= len(missing) and keys.market_date.is_unique, 'REFERENCE_ADDITIONS_EMPTY_OR_OVERSIZED')
    require(keys.identity.eq('SPY').all() and keys.market_date.map(
        lambda d: isinstance(d, str) and d in missing and '2024-01-01' <= d <= '2024-12-31').all(),
        'PRICE_KEY_OUTSIDE_ALLOWED_2024')
    require(set(keys.market_date) <= set(calendar().sessions.strftime('%Y-%m-%d')), 'PRICE_NOT_MARKET_SESSION')
    require(q.get('identity') == 'SPY' and q.get('currency') == 'USD' and
            q.get('session') == 'REGULAR', 'PRICE_IDENTITY_UNITS_INVALID')
    raw = dataset.to_table(columns=INPUT_COLUMNS).to_pylist()
    view = [trade_basis(record, q) for record in raw]
    return pd.DataFrame([dict(ticker=r['identity'], date=r['market_date'], close=r['close_trade_basis'],
                             adjustment='raw', source=r['source'], currency=r['currency']) for r in view],
                        columns=REFERENCE_COLUMNS)
