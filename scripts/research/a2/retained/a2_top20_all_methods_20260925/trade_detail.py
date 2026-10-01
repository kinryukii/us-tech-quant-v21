"""Derive executed share counts and action ratios from E5's immutable trade ledger."""
from __future__ import annotations

import numpy as np
import pandas as pd


def detail(trades: pd.DataFrame, daily: pd.DataFrame, prices: pd.DataFrame,
           targets: pd.DataFrame | None = None) -> pd.DataFrame:
    opened = prices.set_index(["trade_date", "ticker"]).open
    prices_index = opened.index
    if prices_index.has_duplicates:
        raise RuntimeError("DUPLICATE_EXECUTION_PRICE")
    frame = trades.sort_values(["execution_date", "side", "ticker"],
                               key=lambda s: s.map({"SELL": 0, "BUY": 1}) if s.name == "side" else s)
    nav = daily.set_index("execution_date")
    shares: dict[str, float] = {}
    cash = 1.0
    rows = []
    for date, group in frame.groupby("execution_date", sort=True):
        day = nav.loc[pd.Timestamp(date)]
        for row in group.itertuples():
            key = (pd.Timestamp(date), row.ticker)
            price = float(opened.loc[key]) if key in prices_index else np.nan
            if not np.isfinite(price) or price <= 0:
                raise RuntimeError(f"TRADE_WITHOUT_OPEN:{date}:{row.ticker}")
            before = shares.get(row.ticker, 0.0)
            quantity = float(row.notional / price)
            sign = -1 if row.side == "SELL" else 1
            after = before + sign * quantity
            if after < -1e-8:
                raise RuntimeError("SHARES_BELOW_ZERO")
            shares[row.ticker] = max(0.0, after)
            cash += -sign * row.notional - row.transaction_cost
            rows.append({"candidate": row.candidate, "signal_date": row.signal_date,
                         "execution_date": date, "ticker": row.ticker, "side": row.side,
                         "execution_open": price, "shares_before": before, "trade_shares": sign * quantity,
                         "shares_after": shares[row.ticker], "notional": row.notional,
                         "transaction_cost": row.transaction_cost, "remaining_cash": cash,
                         "buy_notional_over_pretrade_nav": row.notional / day.pretrade_nav if sign > 0 else 0.0,
                         "sold_shares_over_prior_shares": quantity / before if sign < 0 and before > 0 else 0.0})
        expected_cash = float(day.cash_weight * day.nav)
        if abs(cash - expected_cash) > 1e-8:
            raise RuntimeError(f"CASH_NOT_CONSERVED:{date}:{cash}:{expected_cash}")
    answer = pd.DataFrame(rows)
    if targets is not None and not answer.empty:
        columns = [c for c in ("candidate", "signal_date", "ticker", "raw_target_weight",
                               "feasible_target_weight", "pretrade_weight", "target_weight") if c in targets]
        if all(c in columns for c in ("candidate", "signal_date", "ticker")):
            answer = answer.merge(targets[columns].drop_duplicates(["candidate", "signal_date", "ticker"]),
                                  on=["candidate", "signal_date", "ticker"], how="left", validate="many_to_one")
    return answer
