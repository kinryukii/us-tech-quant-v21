"""Independently reconcile new complete paths without model inference or fitting."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent


def verify(folder, price_index, calendar):
    daily = pd.read_parquet(folder / 'daily.parquet').sort_values('date')
    trades = pd.read_parquet(folder / 'trades.parquet')
    positions = pd.read_parquet(folder / 'positions.parquet')
    targets = pd.read_parquet(folder / 'target_decisions.parquet')
    assert pd.DatetimeIndex(daily.date).equals(calendar)
    next_day = dict(zip(calendar[:-1], calendar[1:]))
    assert trades.execution_date.eq(trades.signal_date.map(next_day)).all()
    quote_keys = pd.MultiIndex.from_frame(trades[['ticker', 'execution_date']])
    quote_keys = quote_keys.set_names(['ticker', 'trade_date'])
    expected_open = price_index.open.reindex(quote_keys).to_numpy()
    assert np.isfinite(expected_open).all()
    open_price_error = float(np.abs(trades.price.to_numpy()-expected_open).max(initial=0.))
    assert open_price_error < 1e-10
    cost = float(folder.parent.name.removeprefix('cost_'))
    fees = np.abs(trades.transaction_cost.to_numpy() - trades.notional.to_numpy() * cost / 10000)
    fees_error = float(fees.max(initial=0.))
    flow = trades.assign(signed=np.where(trades.side.eq('SELL'), trades.notional, -trades.notional))
    changes = flow.groupby('execution_date').signed.sum() - flow.groupby('execution_date').transaction_cost.sum()
    expected_cash = 1e6 + changes.reindex(daily.date, fill_value=0.).cumsum().to_numpy()
    cash_error = float(np.max(np.abs(daily.cash.to_numpy() - expected_cash)))
    end = positions[positions.date.eq(daily.date.max())].groupby('ticker').market_value.sum()
    buys = trades[trades.side.eq('BUY')].groupby('ticker').notional.sum()
    sells = trades[trades.side.eq('SELL')].groupby('ticker').notional.sum()
    cost_by_stock = trades.groupby('ticker').transaction_cost.sum()
    stock = pd.concat([end.rename('end'), buys.rename('buy'), sells.rename('sell'), cost_by_stock.rename('fees')], axis=1).fillna(0.)
    stock['net_pnl'] = stock.end + stock.sell - stock.buy - stock.fees
    pnl_error = float(stock.net_pnl.sum() - (daily.nav.iloc[-1] - 1e6))
    identity_fields = ['nav_identity_error', 'cash_flow_identity_error', 'cost_identity_error', 'open_self_finance_error']
    identity_errors = {name: float(daily[name].abs().max()) for name in identity_fields}
    target_rows = targets[targets.order_type.ne('HOLD_UNITS')]
    target_max = float(target_rows.adapted_target_weight.max()) if len(target_rows) else 0.
    target_min = float(target_rows.adapted_target_weight.min()) if len(target_rows) else 0.
    if len(trades):
        buys_detail = trades[trades.side.eq('BUY')]
        cap_error = float(np.maximum(buys_detail.notional.to_numpy() - .01 * buys_detail.capacity_adv.to_numpy(), 0.).max(initial=0.))
    else:
        cap_error = 0.
    assert fees_error < 1e-6 and cash_error < 1e-6 and abs(pnl_error) < 1e-6
    assert all(value < 1e-6 for value in identity_errors.values())
    assert target_max <= .1 + 1e-7 and target_min >= -1e-7
    assert daily.actual_name_count.max() <= 20 and daily.cash.min() >= -1e-6
    assert cap_error < 1e-6
    return dict(folder=str(folder), days=len(daily), trades=len(trades),
                net_pnl=float(daily.nav.iloc[-1] - 1e6), cash_flow_error=cash_error,
                stock_pnl_identity_error=pnl_error, fee_error=fees_error,
                ledger_identity_errors=identity_errors, target_max=target_max,
                max_actual_names=int(daily.actual_name_count.max()), min_cash=float(daily.cash.min()),
                buy_capacity_error=cap_error,
                next_session_execution_exact=True, open_price_max_abs_error=open_price_error,
                uncertified_days=int(daily.certified_nav.isna().sum()))


def main():
    folders = [ROOT / f'evaluation_{year}/cost_{cost}/{model}'
               for year in (2025,2026) for cost in (5,10,25) for model in ('M0','M1')]
    assert all((folder/'DONE.json').is_file() for folder in folders), 'All 12 paths must be complete'
    records = []
    for year in (2025, 2026):
        path = (ROOT.parent/'a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet'
                if year == 2025 else ROOT.parent/'a2_multimodel_joint_20260928/data/test_prices.parquet')
        prices = pd.read_parquet(path, columns=['ticker','trade_date','open'])
        if year == 2025:
            calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq('QQQ')
                & prices.trade_date.ge('2025-01-01'), 'trade_date'].unique()))
        else:
            clock = pd.read_parquet(ROOT.parent/'a2_latest_effective_joint_20260927/data/calendar.parquet')
            calendar = pd.DatetimeIndex(clock.loc[clock.is_test, 'trade_date'])
        assert not prices.duplicated(['ticker','trade_date']).any()
        price_index = prices.set_index(['ticker','trade_date'])
        records.extend(verify(folder, price_index, calendar) for folder in folders
                       if folder.parent.parent.name == f'evaluation_{year}')
    result = dict(status='PASS', independent_ledger_reconciliations=records,
                  fits=0, inference_calls=0, replay_calls=0,
                  scope='Original price-index ledger identities; uncertified valuations remain uncertified')
    (ROOT / 'INDEPENDENT_LEDGER_CHECKS.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(status='PASS', paths=len(records), max_cash_error=max(r['cash_flow_error'] for r in records),
                          max_pnl_error=max(abs(r['stock_pnl_identity_error']) for r in records)), ensure_ascii=False))


if __name__ == '__main__': main()
