"""Post hoc description of saved main-2025 paths; no fit/inference/replay."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'cash_diagnostic'
SOURCE = ROOT.parent / 'a2_latest_effective_joint_20260927/data/pre2026_joint_context.parquet'


def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def describe(method):
    folder = ROOT / 'evaluation_2025/cost_10' / method
    assert (folder / 'DONE.json').exists()
    columns = ['signal_date', 'ticker', 'action_weight', 'prediction_utility',
               'action_allowed', 'chosen_action', 'chosen_weight']
    blocks = []
    for batch in pq.ParquetFile(folder / 'action_diagnostics.parquet').iter_batches(
            columns=columns, batch_size=100000):
        frame = batch.to_pandas()
        # Each batch is a multiple of the five contiguous per-stock actions.
        assert len(frame) % 5 == 0
        assert np.array_equal(frame.action_weight.to_numpy().reshape(-1, 5),
                              np.tile([0., .025, .05, .075, .1], (len(frame)//5, 1)))
        utility = frame.prediction_utility.to_numpy().reshape(-1, 5)
        gain = utility - utility[:, :1]
        allowed = frame.action_allowed.to_numpy(bool).reshape(-1, 5)
        chosen = frame.chosen_action.to_numpy(bool).reshape(-1, 5)
        assert chosen.sum(axis=1).tolist() == [1] * len(chosen)
        max_gain = np.where(allowed[:, 1:], gain[:, 1:], -np.inf).max(axis=1)
        row = frame.iloc[::5][['signal_date', 'ticker', 'chosen_weight']].copy()
        row['positive_feasible_gain'] = max_gain > 1e-12
        row['max_feasible_gain'] = max_gain
        row['selected_gain'] = gain[chosen]
        row['nonzero_target'] = row.chosen_weight > 1e-12
        blocks.append(row)
    candidates = pd.concat(blocks, ignore_index=True)
    assert not candidates.duplicated(['signal_date', 'ticker']).any()
    daily_gain = candidates.groupby('signal_date').agg(
        candidates=('ticker', 'size'), positive_feasible_candidates=('positive_feasible_gain', 'sum'),
        selected_names=('nonzero_target', 'sum'), allocated_weight=('chosen_weight', 'sum'),
        max_feasible_gain=('max_feasible_gain', 'max'), chosen_gain_sum=('selected_gain', 'sum'))
    audit = pd.read_parquet(folder / 'daily_meta_audit.parquet').set_index('signal_date')
    contexts = pd.read_parquet(folder / 'signal_contexts.parquet').set_index('signal_date')
    assert np.allclose(daily_gain.allocated_weight, audit.active_target_weight, atol=1e-12, rtol=0)
    assert np.array_equal(daily_gain.selected_names.to_numpy(), audit.active_target_names.to_numpy())
    daily_gain['signal_actual_cash_weight'] = audit.actual_cash_weight
    daily_gain['reserved_weight'] = audit.reserved_weight
    daily_gain['target_cash_weight'] = audit.total_target_cash_weight
    daily_gain['available_weight'] = contexts.available_weight
    daily_gain['available_slots'] = contexts.available_slots
    daily_gain.reset_index().to_csv(OUT / f'{method}_cash_stages_daily.csv', index=False)
    candidates.loc[candidates.nonzero_target].to_csv(OUT / f'{method}_nonzero_targets.csv', index=False)
    days = pd.read_parquet(folder / 'daily.parquet')
    trades = pd.read_parquet(folder / 'trades.parquet')
    summary = dict(signals=len(daily_gain), valuation_days=len(days),
        dates_no_positive_feasible_gain=int(daily_gain.positive_feasible_candidates.eq(0).sum()),
        dates_zero_target=int(daily_gain.selected_names.eq(0).sum()),
        positive_feasible_candidate_days=int(daily_gain.positive_feasible_candidates.sum()),
        selected_stockdays=int(daily_gain.selected_names.sum()),
        max_selected_names=int(daily_gain.selected_names.max()),
        target_cash_date_mean=float(daily_gain.target_cash_weight.mean()),
        signal_actual_cash_date_mean=float(daily_gain.signal_actual_cash_weight.mean()),
        closing_actual_cash_date_mean=float(days.cash_weight.mean()),
        reserved_weight_max=float(daily_gain.reserved_weight.max()),
        available_slots_min=int(daily_gain.available_slots.min()),
        target_investment_max=float(daily_gain.allocated_weight.max()),
        actual_nonzero_holding_days=int(days.actual_name_count.gt(0).sum()),
        buys=int(trades.side.eq('BUY').sum()), sells=int(trades.side.eq('SELL').sum()),
        traded_tickers=sorted(trades.ticker.unique().tolist()),
        net_pnl=float(days.nav.iloc[-1] - 1e6), fees=float(trades.transaction_cost.sum()))
    return summary, trades


def main():
    OUT.mkdir(exist_ok=True)
    records = {}
    for method in ('M0', 'M1'):
        records[method], trades = describe(method)
        if method == 'M1':
            # This saved path consists exclusively of separate BUY / EXIT pairs.
            trades = trades.sort_values(['execution_date', 'ticker']).reset_index(drop=True)
            assert len(trades) % 2 == 0
            rounds = []
            for i in range(0, len(trades), 2):
                buy, sell = trades.iloc[i], trades.iloc[i+1]
                assert buy.side == 'BUY' and sell.side == 'SELL' and buy.ticker == sell.ticker
                assert abs(buy.index_units - sell.index_units) < 1e-6
                gross = float(sell.notional - buy.notional)
                fee = float(buy.transaction_cost + sell.transaction_cost)
                rounds.append(dict(ticker=buy.ticker, buy_signal=buy.signal_date,
                    buy_execution=buy.execution_date, sell_signal=sell.signal_date,
                    sell_execution=sell.execution_date, buy_price=buy.price, sell_price=sell.price,
                    buy_notional=buy.notional, sell_notional=sell.notional,
                    gross_price_pnl=gross, fees=fee, net_pnl=gross-fee))
            rounds = pd.DataFrame(rounds)
            assert abs(rounds.net_pnl.sum() - records[method]['net_pnl']) < 1e-6
            rounds.to_csv(OUT / 'M1_roundtrips.csv', index=False)
            by_stock = rounds.groupby('ticker').agg(rounds=('ticker', 'size'),
                gross_price_pnl=('gross_price_pnl', 'sum'), fees=('fees', 'sum'), net_pnl=('net_pnl', 'sum'))
            by_stock.reset_index().to_csv(OUT / 'M1_stock_pnl.csv', index=False)
            records[method]['roundtrips'] = len(rounds)
            records[method]['stock_pnl'] = by_stock.reset_index().to_dict(orient='records')
            warnings = pd.read_parquet(SOURCE, columns=['signal_date', 'ticker', 'label_price_warning'])
            warnings = warnings.loc[warnings.label_price_warning.astype(bool)
                                    & warnings.signal_date.dt.year.eq(2025)]
            keys = set(zip(warnings.signal_date, warnings.ticker))
            records[method]['trade_signal_keys_with_inherited_label_warning'] = sum(
                (row.signal_date, row.ticker) in keys for row in trades.itertuples())
            records[method]['warning_ticker_shared'] = sorted(set(trades.ticker) & set(warnings.ticker))
    result = dict(status='PASS', role='POST_HOC_DESCRIPTION_OF_SAVED_MAIN_2025_PATHS',
        fit_calls=0, inference_calls=0, replay_calls=0, used_for_selection=False, models=records,
        tolerance=1e-12,
        mean_cash_caveat='Signal/target means cover 248 dates; close mean covers 250 dates. Their subtraction is not a causal execution-cost attribution.',
        warning_caveat='Sharing a warning ticker across different signal dates does not prove the executed losses were caused by price errors.',
        hashes={str(ROOT/'evaluation_2025/cost_10'/m/f): sha(ROOT/'evaluation_2025/cost_10'/m/f)
                for m in ('M0', 'M1') for f in ('DONE.json', 'action_diagnostics.parquet',
                    'daily_meta_audit.parquet', 'signal_contexts.parquet', 'daily.parquet', 'trades.parquet')})
    (OUT / 'CASH_DIAGNOSTIC_RECEIPT.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(status='PASS', models=records), ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
