"""Synthetic semantic equivalence check; no market files or model fitting."""
from __future__ import annotations

import importlib.util
import json

import numpy as np
import pandas as pd

from nav_context_adapter import ENGINE, get_engine


def original_engine():
    spec = importlib.util.spec_from_file_location("joint_original_engine_nav_test", ENGINE)
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sample():
    days = pd.bdate_range("2025-01-02", periods=4)
    quotes = {"A": [(100, 101), (103, 104), (98, 99), (102, 103)],
              "B": [(50, 51), (51, 50), (52, 54), (55, 56)]}
    prices = pd.DataFrame([
        {"ticker": ticker, "trade_date": day, "open": pair[0], "close": pair[1]}
        for ticker, values in quotes.items()
        for day, pair in zip(days, values)
    ])
    features = pd.DataFrame([
        {"ticker": ticker, "signal_date": day, "new_buy_eligible": True,
         "avg_dollar_volume_20d": 300_000.0 if ticker == "A" else 200_000.0}
        for day in days[:3] for ticker in quotes
    ])
    return days, prices, features


def replay(module, observe_nav):
    days, prices, features = sample()
    seen = []
    targets = ({"A": .10, "B": .10}, {"A": .05, "B": .10}, {"A": .10})

    def policy(frame, weights, cash_weight):
        index = days.get_loc(pd.Timestamp(frame.attrs["signal_date"]))
        if observe_nav:
            seen.append((pd.Timestamp(frame.attrs["signal_date"]),
                         float(frame.attrs["signal_close_nav"]),
                         dict(weights), float(cash_weight)))
        return targets[index]

    result = module.run_replay(
        prices, days, features, policy, candidate="nav_context_synthetic",
        initial_cash=1_000_000.0, cost_bps=10.0, max_weight=.10,
        max_positions=20, max_invested=.95, capacity_fraction=.01,
        capacity_on_sells=False, missing_signal_policy="hold",
        signal_start="2025-01-02", signal_end=str(days[2].date()),
    )
    return result, seen


def main():
    base, _ = replay(original_engine(), False)
    adapted, seen = replay(get_engine(), True)
    for field in ("daily", "trades", "positions", "target_decisions",
                  "diagnostics", "valuation_intervals"):
        pd.testing.assert_frame_equal(getattr(base, field), getattr(adapted, field),
                                      check_exact=True)
    assert base.metadata == adapted.metadata
    daily_nav = dict(zip(adapted.daily.date, adapted.daily.nav))
    assert len(seen) == 3
    for date, nav, weights, cash_weight in seen:
        assert np.isclose(nav, daily_nav[date], atol=1e-9, rtol=0)
        assert abs(sum(weights.values()) + cash_weight - 1.0) < 1e-10
    first_day_trades = adapted.trades.loc[adapted.trades.execution_date.eq(
        pd.Timestamp("2025-01-03"))]
    assert len(first_day_trades) == 2
    assert first_day_trades.loc[first_day_trades.ticker.eq("A"), "notional"].iloc[0] <= 3_000.0
    assert first_day_trades.loc[first_day_trades.ticker.eq("B"), "notional"].iloc[0] <= 2_000.0
    assert adapted.daily.cash_flow_identity_error.abs().max() < 1e-6
    assert adapted.daily.cost_identity_error.abs().max() < 1e-6
    print(json.dumps({"status": "NAV_CONTEXT_LEDGER_EQUIVALENCE_PASS",
                      "decision_count": len(seen), "capacity_limited_first_buys": 2,
                      "identical_output_frames": 6,
                      "max_cash_error": adapted.daily.cash_flow_identity_error.abs().max()},
                     allow_nan=False))


if __name__ == "__main__":
    main()
