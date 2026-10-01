"""Read-only 2025 execution-semantic parity with frozen engine, before any fit."""
from __future__ import annotations

import json
import numpy as np
import pandas as pd
import torch
from torch import nn

from followup_review.capacity_aware_revision.nav_context_adapter import get_engine
from followup_review.capacity_aware_rl.train_capacity_rl import (
    CapacityMarket, CapacityRLAdapter, FEATURES, PRICE, SOURCE,
)


class FixedTarget(nn.Module):
    def forward(self, x):
        return torch.full((len(x),), 20., dtype=torch.float32)


def main():
    # Identity is fixed for semantic QA only, with full 2025 AAPL/ABSI/ADPT
    # coverage. No return, label, or model score is used to select this set.
    selected = ("AAPL", "ABSI", "ADPT")
    panel = pd.read_parquet(SOURCE)
    panel["signal_date"] = pd.to_datetime(panel.signal_date)
    if panel.signal_date.max() >= pd.Timestamp("2026-01-01"):
        raise RuntimeError("PRE2026_PANEL_BOUNDARY")
    fitrows = panel.loc[panel.signal_date.le("2024-12-31")]
    fitrows = fitrows[np.isfinite(fitrows[FEATURES].to_numpy(float)).all(axis=1)]
    x = fitrows[FEATURES].to_numpy(float)
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale[scale < 1e-12] = 1.
    selected_panel = panel.loc[panel.ticker.isin(selected)].copy()
    market = CapacityMarket(selected_panel, "2025-01-01", "2025-12-31", mean, scale)
    _, rows = market.episode(FixedTarget(), trace=True)
    if not rows:
        raise RuntimeError("EMPTY_PRE2026_PARITY_DATES")
    price = pd.read_parquet(PRICE, columns=["ticker", "trade_date", "open", "close"])
    price["trade_date"] = pd.to_datetime(price.trade_date)
    if price.trade_date.max() >= pd.Timestamp("2026-01-01"):
        raise RuntimeError("PRE2026_PRICE_BOUNDARY")
    calendar = pd.DatetimeIndex(sorted(price.loc[
        price.ticker.eq("QQQ") & price.trade_date.ge("2025-01-01") & price.trade_date.le("2025-12-31"),
        "trade_date"].unique()))
    selected_price = price.loc[price.ticker.isin(selected) & price.trade_date.isin(calendar)].copy()
    signals = selected_panel.loc[selected_panel.signal_date.between(
        pd.Timestamp(rows[0]["signal_date"]), pd.Timestamp(rows[-1]["signal_date"]))].copy()
    adapter = CapacityRLAdapter.__new__(CapacityRLAdapter)
    adapter.mean, adapter.scale, adapter.models = mean, scale, [FixedTarget()]
    replay = get_engine().run_replay(
        selected_price, calendar, signals, adapter, candidate="pre2026_capacity_rl_semantic_qa",
        initial_cash=1_000_000., cost_bps=10., max_weight=.1, max_positions=20,
        max_invested=.95, capacity_fraction=.01, missing_signal_policy="cash",
        signal_start=rows[0]["signal_date"], signal_end=rows[-1]["signal_date"],
    )
    daily = replay.daily.set_index("date")
    positions = {(pd.Timestamp(r.date), r.ticker): float(r.index_units)
                 for r in replay.positions.itertuples(index=False)}
    maxerr = dict(cash=0., nav=0., fees=0., buys=0., sells=0., units=0.)
    position_keys = 0
    for row in rows:
        date = pd.Timestamp(row["execution_date"])
        actual = daily.loc[date]
        for key, col in (("cash", "cash"), ("nav", "nav"), ("fees", "transaction_cost_amount"),
                         ("buys", "buy_notional"), ("sells", "sell_notional")):
            want = row["end_close_nav"] if key == "nav" else (
                row["fees"] if key == "fees" else
                row["buy_notional"] if key == "buys" else
                row["sell_notional"] if key == "sells" else row["cash"])
            maxerr[key] = max(maxerr[key], abs(float(actual[col]) - float(want)))
        actual_units = {t: q for (d, t), q in positions.items() if d == date}
        all_names = set(actual_units) | set(row["position_units"])
        for ticker in all_names:
            position_keys += 1
            maxerr["units"] = max(maxerr["units"], abs(
                actual_units.get(ticker, 0.) - row["position_units"].get(ticker, 0.)))
    # This test allows only numerical roundoff on a 1m-dollar account.
    if any(maxerr[k] > 1e-5 for k in ("cash", "nav", "fees", "buys", "sells")) or maxerr["units"] > 1e-7:
        raise RuntimeError(f"PRE2026_ENGINE_SEMANTIC_MISMATCH:{maxerr}")
    missing_opens = int((~np.isfinite(pd.to_numeric(selected_price.open, errors="coerce")) |
                         pd.to_numeric(selected_price.open, errors="coerce").le(0)).sum())
    missing_closes = int((~np.isfinite(pd.to_numeric(selected_price.close, errors="coerce")) |
                          pd.to_numeric(selected_price.close, errors="coerce").le(0)).sum())
    summary = dict(status="PRE2026_RL_ENGINE_SEMANTICS_MATCH", names=list(selected),
                   decision_days=len(rows), position_keys=position_keys,
                   max_absolute_error=maxerr, capacity_limited=sum(r["capacity_limited"] for r in rows),
                   missing_open_source_rows=missing_opens, missing_close_source_rows=missing_closes,
                   synthetic_missing_open_test="test_capacity_rl.py::test_missing_open_does_not_create_position_or_fee",
                   market_fits=0, rl_updates=0, reads_2026=0)
    print(json.dumps(summary, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
