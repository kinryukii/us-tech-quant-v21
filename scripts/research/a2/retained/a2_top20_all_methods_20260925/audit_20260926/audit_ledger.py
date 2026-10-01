"""Short independent share/cash/P&L identity check on saved E5 trades."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

AUDIT = Path(__file__).resolve().parent
ROOT = AUDIT.parent
sys.path.insert(0, str(ROOT))
import rl_policy


def checks(prices, ticker, date, close_wide, open_wide):
    try:
        opened = float(open_wide.at[date, ticker])
    except (KeyError, TypeError, ValueError):
        opened = np.nan
    if np.isfinite(opened) and opened > 0:
        return opened
    if ticker not in close_wide:
        raise RuntimeError(f"NO_MARK:{ticker}:{date}")
    hist = close_wide.loc[close_wide.index < date, ticker].dropna()
    hist = hist.loc[np.isfinite(hist.to_numpy(float)) & (hist.to_numpy(float) > 0)]
    if hist.empty:
        raise RuntimeError(f"NO_MARK:{ticker}:{date}")
    return float(hist.iloc[-1])


def one(name, prices, open_wide, close_wide):
    test = ROOT / "test2026"
    daily = pd.read_parquet(test / f"{name.lower()}_daily.parquet")
    trades = pd.read_parquet(test / f"{name.lower()}_trades.parquet")
    shares: dict[str, float] = {}
    prior_marks: dict[str, float] = {}
    cash = 1.0
    nav = 1.0
    ticker_pnl = defaultdict(float)
    day_rows = []
    raw_sell_buy = trades.assign(side_order=trades.side.map({"SELL": 0, "BUY": 1})).sort_values(
        ["execution_date", "side_order", "ticker"])
    grouped = {d: g for d, g in raw_sell_buy.groupby("execution_date")}
    for day in daily.itertuples():
        date = pd.Timestamp(day.execution_date)
        marks = {t: checks(prices, t, date, close_wide, open_wide) for t in shares}
        market = {t: q * (marks[t] - prior_marks[t]) for t, q in shares.items()}
        gross_pnl = sum(market.values())
        for t, value in market.items():
            ticker_pnl[t] += value
        pre_nav = cash + sum(shares[t] * marks[t] for t in shares)
        if abs(pre_nav - float(day.pretrade_nav)) > 1e-8:
            raise RuntimeError(f"PRE_NAV_MISMATCH:{name}:{date}:{pre_nav}:{day.pretrade_nav}")
        fee = 0.0
        for trade in grouped.get(date, pd.DataFrame()).itertuples():
            t = trade.ticker
            price = checks(prices, t, date, close_wide, open_wide)
            if not np.isfinite(float(open_wide.at[date, t])):
                raise RuntimeError(f"TRADE_WITHOUT_CURRENT_OPEN:{name}:{date}:{t}")
            qty = float(trade.notional / price)
            side = 1 if trade.side == "BUY" else -1
            before = shares.get(t, 0.)
            after = before + side * qty
            if after < -1e-8:
                raise RuntimeError(f"NEGATIVE_SHARES:{name}:{date}:{t}")
            shares[t] = max(0., after)
            if shares[t] == 0:
                del shares[t]
            marks[t] = price
            cash -= side * float(trade.notional)
            cash -= float(trade.transaction_cost)
            fee += float(trade.transaction_cost)
            ticker_pnl[t] -= float(trade.transaction_cost)
        nav_new = cash + sum(shares[t] * marks[t] for t in shares)
        if abs(nav_new - float(day.nav)) > 1e-8 or abs(nav_new - (nav + gross_pnl - fee)) > 1e-8:
            raise RuntimeError(f"NAV_MISMATCH:{name}:{date}:{nav_new}:{day.nav}")
        day_rows.append({"candidate": name, "execution_date": date,
                         "independent_market_pnl": gross_pnl, "independent_fee": fee,
                         "independent_net_delta": nav_new - nav,
                         "saved_nav": day.nav,
                         "absolute_identity_error": abs(nav_new - (nav + gross_pnl - fee))})
        nav = nav_new
        prior_marks = {t: marks[t] for t in shares}
    if abs(sum(ticker_pnl.values()) - (nav - 1)) > 1e-8:
        raise RuntimeError(f"TICKER_PNL_MISMATCH:{name}")
    return pd.DataFrame(day_rows), pd.DataFrame(
        [{"candidate": name, "ticker": t, "net_dollar_pnl": p}
         for t, p in ticker_pnl.items()])


def main():
    pred = pd.read_parquet(ROOT / "test2026" / "predictions.parquet")
    e5 = rl_policy.load_module("audit_e5_ledger", rl_policy.E5)
    _, prices, lineage = e5.load_2026_prices(set(pred.ticker.astype(str)))
    original = json.loads((ROOT / "test2026" / "score_receipt.json").read_text(encoding="utf-8"))
    assert lineage == original["price_lineage"]
    prices = prices.loc[prices.trade_date.le("2026-09-24")]
    open_wide = prices.pivot(index="trade_date", columns="ticker", values="open").sort_index()
    close_wide = prices.pivot(index="trade_date", columns="ticker", values="close").sort_index()
    names = pd.read_csv(ROOT / "test2026" / "summary.csv").candidate.tolist()
    days, tickers = [], []
    for name in names:
        d, t = one(name, prices, open_wide, close_wide)
        days.append(d); tickers.append(t)
        print("LEDGER", name, float(d.saved_nav.iloc[-1]), flush=True)
    day = pd.concat(days, ignore_index=True)
    ticker = pd.concat(tickers, ignore_index=True)
    day.to_csv(AUDIT / "independent_daily_pnl.csv", index=False)
    ticker.to_csv(AUDIT / "independent_ticker_pnl.csv", index=False)
    pivot = ticker.pivot(index="ticker", columns="candidate", values="net_dollar_pnl").fillna(0)
    pivot["hgb_minus_raw"] = pivot.HGB_DIAG_5 - pivot.RAW
    pivot.sort_values("hgb_minus_raw", ascending=False).to_csv(AUDIT / "hgb_relative_ticker_pnl.csv")
    assert abs(pivot.hgb_minus_raw.sum() -
               (float(day.loc[day.candidate.eq("HGB_DIAG_5")].saved_nav.iloc[-1]) -
                float(day.loc[day.candidate.eq("RAW")].saved_nav.iloc[-1]))) < 1e-8
    print("IDENTITY_MAX", day.absolute_identity_error.max())
    print(pivot.hgb_minus_raw.sort_values(ascending=False).head(5).to_string())
    print(pivot.hgb_minus_raw.sort_values().head(5).to_string())


if __name__ == "__main__":
    main()
