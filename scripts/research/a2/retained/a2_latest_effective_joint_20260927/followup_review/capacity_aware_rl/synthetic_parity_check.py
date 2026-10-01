"""Pure-stdlib/PyTorch synthetic parity; fixed image need not ship pytest."""
import json
import numpy as np
import pandas as pd
import torch
from torch import nn
from engine import run_replay
from followup_review.capacity_aware_rl.train_capacity_rl import CapacityMarket, capacity_ratio, FEATURES


class FixedTarget(nn.Module):
    def forward(self, x):
        return torch.full((len(x),), 20., dtype=torch.float32)


def day(date, execution, adv=5_000_000., fill=True):
    return dict(date=date, execution_date=execution, ids=torch.tensor([0]),
                x=torch.zeros((1, len(FEATURES)), dtype=torch.float32),
                eligible=torch.tensor([True]), close=torch.tensor([100.], dtype=torch.float64),
                opening=torch.tensor([100.], dtype=torch.float64), ending=np.array([100.]),
                fill=torch.tensor([fill]), vol=torch.tensor([.01], dtype=torch.float64),
                adv=np.array([adv]))


def run():
    market = CapacityMarket.__new__(CapacityMarket)
    market.tickers, market.lookup = ["A"], {"A": 0}
    market.days = [day("2025-01-02", "2025-01-03"), day("2025-01-03", "2025-01-04")]
    _, rows = market.episode(FixedTarget(), trace=True)
    dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-04"])
    prices = pd.DataFrame([dict(ticker="A", trade_date=d, open=100., close=100.) for d in dates])
    features = pd.DataFrame([dict(ticker="A", signal_date=d, avg_dollar_volume_20d=5_000_000.,
                                  new_buy_eligible=True) for d in dates[:2]])
    result = run_replay(
        prices, pd.DatetimeIndex(dates), features, lambda *_: {"A": .1},
        initial_cash=1_000_000., cost_bps=10., max_weight=.1, max_positions=20,
        max_invested=.95, capacity_fraction=.01, missing_signal_policy="cash",
        signal_start="2025-01-02", signal_end="2025-01-03")
    daily = result.daily.set_index("date")
    max_error = 0.
    for row in rows:
        actual = daily.loc[pd.Timestamp(row["execution_date"])]
        for ours, theirs in (("cash", "cash"), ("end_close_nav", "nav"),
                             ("fees", "transaction_cost_amount"), ("buy_notional", "buy_notional")):
            max_error = max(max_error, abs(float(row[ours]) - float(actual[theirs])))
        expected_units = row["position_units"].get("A", 0.)
        actual_units = result.positions.loc[
            result.positions.date.eq(pd.Timestamp(row["execution_date"])), "index_units"]
        max_error = max(max_error, abs(expected_units - float(actual_units.iloc[0])))
    assert max_error < 1e-6, max_error
    assert rows[0]["capacity_limited"] == 1 and rows[0]["buy_notional"] == 50_000.
    assert abs(rows[0]["fees"] - 50.) < 1e-9 and abs(rows[0]["cash"] - 949_950.) < 1e-6
    assert rows[0]["risk_penalty"] < rows[0]["target_risk_proxy_penalty"]
    assert capacity_ratio(np.array([5_000_000.]), 2_000_000.).item() == .025
    missing = CapacityMarket.__new__(CapacityMarket)
    missing.tickers, missing.lookup = ["A"], {"A": 0}
    missing.days = [day("2025-01-02", "2025-01-03", fill=False)]
    _, nofill = missing.episode(FixedTarget())
    assert nofill[0]["buy_notional"] == 0 and nofill[0]["fees"] == 0
    print(json.dumps(dict(status="SYNTHETIC_ENGINE_SEMANTICS_MATCH", max_absolute_error=max_error,
                          partial_buy_notional=rows[0]["buy_notional"], fees=rows[0]["fees"],
                          missing_open_buy_notional=nofill[0]["buy_notional"],
                          market_fits=0, rl_updates=0, reads_2026=0)), flush=True)


if __name__ == "__main__":
    run()
