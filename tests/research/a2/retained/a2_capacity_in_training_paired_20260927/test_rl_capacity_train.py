"""Behavior checks for the paired RL training fill change."""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'a2_qualification_holdings_v1_20260927'))

from engine_v2 import HoldingAwareDecision, run_replay
from joint_neural_v2 import execute_targets as original_execute_targets
from rl_capacity_train import execute_targets as capacity_execute_targets


def _tensor(values):
    return torch.tensor(values, dtype=torch.float64)


def test_capital_scaled_adv_partial_buy_matches_frozen_ledger():
    calendar = pd.date_range('2025-01-02', periods=3, freq='B')
    prices = pd.DataFrame([
        {'ticker': 'A', 'trade_date': d, 'open': 100., 'close': 100.} for d in calendar
    ])
    features = pd.DataFrame([{'ticker': 'A', 'signal_date': calendar[0],
                              'new_buy_eligible': True, 'avg_dollar_volume_20d': 1_000_000.}])
    result = run_replay(prices, calendar, features,
        lambda *_: HoldingAwareDecision({'A': .10}), initial_cash=1_000_000.,
        capacity_fraction=.01, cost_bps=10., signal_start=calendar[0], signal_end=calendar[0])
    units, cash, fees, _, _, diagnostic = capacity_execute_targets(
        _tensor([0.]), _tensor(1.), _tensor([100.]), torch.tensor([True]),
        _tensor([.10]), torch.tensor([False]), torch.tensor([True]), _tensor([1_000_000.]))
    trade = result.trades.iloc[0]
    assert trade.side == 'BUY'
    assert trade.notional == pytest.approx(10_000.)
    assert float(units[0]) * 1_000_000. == pytest.approx(trade.index_units)
    assert float(cash) * 1_000_000. == pytest.approx(result.daily.iloc[1].cash)
    assert float(fees) * 1_000_000. == pytest.approx(trade.transaction_cost)
    assert diagnostic['cap_limited_orders'] == 1
    assert diagnostic['requested_buy_notional'] == pytest.approx(.1)
    assert diagnostic['allowed_buy_notional'] == pytest.approx(.01)


def test_actual_partial_units_and_cash_feed_next_step():
    units, cash, *_ = capacity_execute_targets(
        _tensor([0.]), _tensor(1.), _tensor([100.]), torch.tensor([True]),
        _tensor([.10]), torch.tensor([False]), torch.tensor([True]), _tensor([1_000_000.]))
    second_units, second_cash, fees, pre_nav, _, diagnostic = capacity_execute_targets(
        units.detach(), cash.detach(), _tensor([100.]), torch.tensor([True]),
        _tensor([.10]), torch.tensor([False]), torch.tensor([True]), _tensor([1_000_000.]))
    assert float(second_units[0]) == pytest.approx(.0002)
    assert float(pre_nav) == pytest.approx(.99999)
    assert float(second_cash) == pytest.approx(.97998)
    assert float(fees) == pytest.approx(.00001)
    assert diagnostic['cap_limited_orders'] == 1


def test_unbound_cap_and_missing_adv_edges():
    args = (_tensor([0., .002]), _tensor(.8), _tensor([100., 100.]),
            torch.tensor([True, True]), _tensor([.10, .20]),
            torch.tensor([False, False]), torch.tensor([True, True]))
    original = original_execute_targets(*args)
    unbound = capacity_execute_targets(*args, _tensor([1e12, 1e12]))
    for before, after in zip(original[:4], unbound[:4]):
        np.testing.assert_allclose(before.detach().numpy(), after.detach().numpy(), rtol=1e-12, atol=1e-12)
    assert original[4] == unbound[4]
    missing = capacity_execute_targets(*args, _tensor([float('nan'), 0.]))
    np.testing.assert_allclose(missing[0].detach().numpy(), args[0].numpy())
    assert missing[5]['filled_buy_notional'] == 0.
