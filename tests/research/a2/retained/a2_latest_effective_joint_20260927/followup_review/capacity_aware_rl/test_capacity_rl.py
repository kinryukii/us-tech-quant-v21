"""Synthetic, non-economic checks of capacity fills and causality."""
import numpy as np
import pandas as pd
import pytest
import torch
from torch import nn

from engine import run_replay
from followup_review.capacity_aware_rl.train_capacity_rl import CapacityMarket, capacity_ratio
import joint_neural as original


class FixedTarget(nn.Module):
    def forward(self, x):
        return torch.full((len(x),), 20., dtype=torch.float32)


def synthetic_market(adv=5_000_000., missing_second_open=False):
    market = CapacityMarket.__new__(CapacityMarket)
    market.tickers = ["A"]
    market.lookup = {"A": 0}
    market.days = []
    for i in range(2):
        market.days.append(dict(
            date=f"2025-01-0{i + 2}", execution_date=f"2025-01-0{i + 3}",
            ids=torch.tensor([0]), x=torch.zeros((1, len(original.FEATURES)), dtype=torch.float32),
            eligible=torch.tensor([True]), close=torch.tensor([100.], dtype=torch.float64),
            opening=torch.tensor([100.], dtype=torch.float64), ending=np.array([100.]),
            fill=torch.tensor([not (missing_second_open and i == 1)]),
            vol=torch.tensor([.01], dtype=torch.float64), adv=np.array([adv]),
        ))
    return market


def test_capacity_input_uses_current_nav_and_missing_adv_blocks():
    assert capacity_ratio(np.array([5_000_000., -1., np.nan]), 1_000_000.).tolist() == [.05, 0., 0.]
    assert capacity_ratio(np.array([5_000_000.]), 2_000_000.).tolist() == [.025]
    with pytest.raises(RuntimeError, match="UNKNOWN_SIGNAL_NAV"):
        capacity_ratio(np.array([1.]), float("nan"))


def test_partial_fill_fee_cash_and_next_day_state_match_existing_engine():
    _, rows = synthetic_market().episode(FixedTarget())
    dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-04"])
    prices = pd.DataFrame([dict(ticker="A", trade_date=d, open=100., close=100.) for d in dates])
    features = pd.DataFrame([dict(ticker="A", signal_date=d, avg_dollar_volume_20d=5_000_000.,
                                  new_buy_eligible=True) for d in dates[:2]])
    result = run_replay(
        prices, pd.DatetimeIndex(dates), features, lambda *_: {"A": .1},
        initial_cash=1_000_000., cost_bps=10, max_weight=.1, max_positions=20,
        max_invested=.95, capacity_fraction=.01, missing_signal_policy="cash",
        signal_start="2025-01-02", signal_end="2025-01-03",
    )
    got = result.daily.set_index("date")
    for row in rows:
        day = got.loc[pd.Timestamp(row["execution_date"])]
        assert row["cash"] == pytest.approx(float(day["cash"]), abs=1e-6)
        assert row["end_close_nav"] == pytest.approx(float(day["nav"]), abs=1e-6)
        assert row["fees"] == pytest.approx(float(day["transaction_cost_amount"]), abs=1e-6)
    assert rows[0]["capacity_limited"] == 1
    assert rows[0]["buy_notional"] == pytest.approx(50_000.)
    assert rows[0]["fees"] == pytest.approx(50.)
    assert rows[0]["cash"] == pytest.approx(949_950.)
    assert rows[0]["risk_penalty"] < rows[0]["target_risk_proxy_penalty"]
    assert rows[1]["buy_notional"] == pytest.approx(49_995.)
    assert rows[1]["cash"] >= 0


def test_missing_open_does_not_create_position_or_fee():
    _, rows = synthetic_market(missing_second_open=True).episode(FixedTarget())
    assert rows[1]["buy_notional"] == 0
    assert rows[1]["fees"] == 0


def test_reward_not_matured_beyond_next_signal_close():
    _, rows = synthetic_market().episode(FixedTarget())
    for row in rows:
        assert pd.Timestamp(row["execution_date"]) > pd.Timestamp(row["signal_date"])
        assert row["reward"] == pytest.approx(np.log(row["end_close_nav"] / row["signal_close_nav"]))
