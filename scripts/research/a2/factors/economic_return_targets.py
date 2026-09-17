"""The existing four-horizon ordinal target over explicit economic daily returns.

No price loader or model is owned here. Unlike a cumulative index with skipped
missing returns, every forward interval must contain all adjacent daily returns.
Incomplete cross-sections retain every key and receive no partial rank labels.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HORIZONS = (3, 5, 10, 20)


def attach_economic_targets(panel: pd.DataFrame, returns: pd.DataFrame,
                            calendar: pd.DatetimeIndex, *,
                            return_column: str = 'gross_accrual_return',
                            expected_names_per_date: int = 40,
                            compute_values: bool = True) -> pd.DataFrame:
    """Preserve exact panel keys, with ordinal labels only for complete universes.

    The target is the within-date average-tie percentile of the equal mean of
    stock compounded3/5/10/20session gross accrual returns. Subtracting a common
    same-date QQQ blend cannot change these ranks. This equivalence does not
    certify QQQ market features, raw-share financing, or execution returns.
    With compute_values=False, emit only forward-validity masks: no compound
    return values or within-date target rankings are computed.
    """
    calendar = pd.DatetimeIndex(calendar)
    if calendar.empty or calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise ValueError('invalid authoritative calendar')
    if panel.duplicated(['signal_date', 'ticker']).any():
        raise ValueError('duplicate target keys')
    if not panel.groupby('signal_date').size().eq(expected_names_per_date).all():
        raise ValueError('panel universe cardinality changed')
    if not pd.DatetimeIndex(panel.signal_date.unique()).isin(calendar).all():
        raise ValueError('target signal outside calendar')
    if returns.duplicated(['trade_date', 'ticker']).any():
        raise ValueError('duplicate daily returns')
    if not pd.DatetimeIndex(returns.trade_date.unique()).isin(calendar).all():
        raise ValueError('daily return outside calendar')
    values = pd.to_numeric(returns[return_column], errors='raise').to_numpy(float)
    if np.isinf(values).any() or (values[np.isfinite(values)] < -1).any():
        raise ValueError('invalid economic return')
    wide = returns.pivot(index='trade_date', columns='ticker', values=return_column).reindex(calendar)
    if not set(panel.ticker).issubset(wide.columns):
        raise ValueError('missing panel return ticker')
    date_positions = calendar.get_indexer(panel.signal_date)
    ticker_positions = wide.columns.get_indexer(panel.ticker)
    out = panel.copy()
    maturity = pd.Series(calendar, index=calendar).shift(-max(HORIZONS))
    expected_maturity = out.signal_date.map(maturity)
    if 'target_end_date' in out and not out.target_end_date.reset_index(drop=True).equals(expected_maturity.reset_index(drop=True)):
        raise ValueError('inherited target maturity differs from pinned calendar')
    out['target_end_date'] = expected_maturity
    growth = pd.DataFrame(1.0, index=wide.index, columns=wide.columns)
    valid_growth = pd.DataFrame(True, index=wide.index, columns=wide.columns)
    components, flags = [], []
    for step in range(1, max(HORIZONS) + 1):
        valid_growth &= wide.notna().shift(-step, fill_value=False)
        if compute_values:
            growth = growth * (1.0 + wide.shift(-step))
        if step in HORIZONS:
            column = f'economic_stock_return_{step}d'
            flag = column + '_valid'
            out[flag] = valid_growth.to_numpy()[date_positions, ticker_positions]
            flags.append(flag)
            if compute_values:
                # Direct key lookup preserves missing cells without index bridging.
                out[column] = (growth.to_numpy() - 1.0)[date_positions, ticker_positions]
                components.append(column)
    valid = out[flags].all(axis=1) & out.target_end_date.notna()
    out['target_valid'] = valid
    out['target_component_count'] = out[flags].sum(axis=1)
    out['target_universe_complete'] = valid.groupby(out.signal_date).transform('all')
    if compute_values:
        mean_return = out[components].mean(axis=1).where(valid)
        ranks = mean_return.groupby(out.signal_date).rank(method='average', pct=True)
        out['target'] = ranks.where(out.target_universe_complete)
    else:
        out['target'] = np.nan
    return out
