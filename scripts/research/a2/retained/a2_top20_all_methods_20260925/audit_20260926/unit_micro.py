"""Isolated constant price-unit invariance check, not corporate-action proof."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

AUDIT = Path(__file__).resolve().parent
ROOT = AUDIT.parent
sys.path.insert(0, str(ROOT))
import rl_policy
from close_clock import close_clock_replay


def main():
    e5 = rl_policy.load_module("audit_e5_unit_micro", rl_policy.E5)
    replay = close_clock_replay(e5)
    dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"])
    outcomes = []
    for scale in (1., 2.):
        prices = pd.DataFrame([{"trade_date": d, "ticker": "QQQ", "open": 1., "close": 1.}
                               for d in dates] +
                              [{"trade_date": d, "ticker": "XYZ", "open": p * scale,
                                "close": c * scale} for d, p, c in zip(dates, (10, 12, 11, 13),
                                                                          (11, 12.5, 12, 13.5))])
        signals = {dates[1]: dates[0], dates[2]: dates[1], dates[3]: dates[2]}
        result = replay(f"UNIT_{scale}", lambda signal, *_: {"XYZ": .5}, prices,
                        list(dates[1:]), signals)
        trades = result.trades
        first_qty = float(trades.loc[trades.side.eq("BUY")].iloc[0].notional /
                          (prices.loc[prices.trade_date.eq(dates[1]) & prices.ticker.eq("XYZ"), "open"].iloc[0]))
        outcomes.append({"price_scale": scale, "end_nav": float(result.daily.nav.iloc[-1]),
                         "first_bought_shares": first_qty, "cash_end":
                         float(result.daily.iloc[-1].cash_weight * result.daily.iloc[-1].nav)})
    table = pd.DataFrame(outcomes)
    assert abs(table.end_nav.iloc[0] - table.end_nav.iloc[1]) < 1e-12
    assert abs(table.first_bought_shares.iloc[0] / table.first_bought_shares.iloc[1] - 2) < 1e-12
    table.to_csv(AUDIT / "unit_micro.csv", index=False)
    print(table.to_string(index=False))


if __name__ == "__main__":
    main()
