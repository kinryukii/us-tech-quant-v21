"""Independent cross-check of saved targets, positions, and ledger attribution.

No model loading, fitting, inference, replay, or strategy changes.
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
SOURCE = OUT.parent / 'a2_multimodel_joint_20260928'
ACCOUNT = SOURCE / 'evaluation_2025/cost_10/ensemble_equal_weight'


def main():
    raw = pd.read_parquet(ACCOUNT / 'raw_model_outputs.parquet')
    contexts = pd.read_parquet(ACCOUNT / 'signal_contexts.parquet').set_index('signal_date')
    target = pd.read_parquet(ACCOUNT / 'target_decisions.parquet').set_index(['signal_date', 'ticker'])
    trades = pd.read_parquet(ACCOUNT / 'trades.parquet')
    daily = pd.read_parquet(ACCOUNT / 'daily.parquet').sort_values('date')
    positions = pd.read_parquet(ACCOUNT / 'positions.parquet')
    errors = dict(mean_to_top20=0., raw_to_decisions=0., decisions_to_ledger=0., active_sum=0.)
    targets_checked = 0
    top20_binding_days = 0
    max_names = 0
    for row in raw.itertuples():
        ctx = contexts.loc[row.signal_date]
        detail = json.loads(row.raw_model_outputs_json)
        decisions = json.loads(row.model_decisions_json)
        means = {t: float(np.mean(list(v['member_targets'].values()))) for t, v in detail.items()}
        keep = set(sorted(means, key=lambda t: (-means[t], t))[:int(ctx.available_slots)])
        if sum(w > 1e-10 for w in means.values()) > int(ctx.available_slots):
            top20_binding_days += 1
        for t, value in detail.items():
            expected = means[t] if t in keep else 0.
            saved = float(value['equal_weight_target'])
            errors['mean_to_top20'] = max(errors['mean_to_top20'], abs(expected - saved))
            errors['raw_to_decisions'] = max(errors['raw_to_decisions'], abs(saved - decisions[t]))
            errors['decisions_to_ledger'] = max(errors['decisions_to_ledger'], abs(saved - target.loc[(row.signal_date, t)].adapted_target_weight))
            targets_checked += 1
        errors['active_sum'] = max(errors['active_sum'], abs(sum(decisions.values()) - ctx.active_target_weight))
        max_names = max(max_names, int(ctx.final_reserved_slots) + sum(v > 1e-10 for v in decisions.values()))
    assert max(errors.values()) < 1e-12, errors
    assert max_names <= 20
    assert daily.actual_name_count.max() <= 20

    end = positions[positions.date.eq(daily.date.max())].groupby('ticker').market_value.sum()
    buy = trades[trades.side.eq('BUY')].groupby('ticker').notional.sum()
    sell = trades[trades.side.eq('SELL')].groupby('ticker').notional.sum()
    fees = trades.groupby('ticker').transaction_cost.sum()
    check = pd.concat([end.rename('end'), buy.rename('buy'), sell.rename('sell'), fees.rename('fee')], axis=1).fillna(0)
    check['net'] = check.end + check.sell - check.buy - check.fee
    stock = pd.read_csv(OUT / 'cash_attribution/stock_pnl.csv').set_index('ticker')
    stock_delta = check.net - stock.net_pnl.reindex(check.index)
    assert stock_delta.notna().all()
    assert stock_delta.abs().max() < 1e-6
    nav_delta = check.net.sum() - (daily.nav.iloc[-1] - 1e6)
    assert abs(nav_delta) < 1e-6

    result = dict(status='PASS', scope='2025 frozen saved records only; independent of attribution implementation',
                  signal_dates=len(raw), raw_stock_targets_checked=targets_checked,
                  top20_binding_days=top20_binding_days, max_signal_names_with_reserved=max_names,
                  max_actual_names=int(daily.actual_name_count.max()), max_target_errors=errors,
                  stock_cashflow_identity_max_error=float(stock_delta.abs().max()),
                  terminal_nav_identity_error=float(nav_delta),
                  source_period_daily_rows=len(daily), source_trades=len(trades),
                  model_loading=False, fit_calls=0, replay_calls=0)
    (OUT / 'INDEPENDENT_CHECKS.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
