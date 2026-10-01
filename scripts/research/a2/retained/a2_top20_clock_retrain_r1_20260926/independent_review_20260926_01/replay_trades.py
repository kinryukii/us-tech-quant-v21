"""Reconstruct pre-2026 fills from sealed targets with the sealed ledger."""
from __future__ import annotations

import gc
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/bundle")
OUT = Path("/out")
sys.path.insert(0, str(ROOT))
import ledger  # noqa: E402


def check_one(prefix: str, daily_path: Path, target_path: Path,
              target_col: str, prices: pd.DataFrame, opens: pd.Series) -> tuple[dict, pd.DataFrame]:
    original = pd.read_parquet(daily_path)
    targets_frame = pd.read_parquet(target_path)
    if original.empty or targets_frame.empty:
        raise RuntimeError(f"EMPTY_REPLAY_INPUT:{prefix}")
    targets = {}
    before = {}
    for signal, day in targets_frame.groupby("signal_date", sort=True):
        signal = pd.Timestamp(signal)
        if day.ticker.duplicated().any():
            raise RuntimeError(f"DUPLICATE_TARGET_TICKER:{prefix}:{signal}")
        targets[signal] = dict(zip(day.ticker.astype(str), day[target_col].astype(float)))
        before[signal] = dict(zip(day.ticker.astype(str), day.shares_before.astype(float)))
    signal_map = {pd.Timestamp(row.execution_date): pd.Timestamp(row.signal_date)
                  for row in original.itertuples() if pd.notna(row.signal_date)}
    execution_dates = [pd.Timestamp(date) for date in original.execution_date]

    def callback(signal, shares, values, nav):
        if signal not in targets:
            raise RuntimeError(f"TARGET_DATE_ABSENT:{prefix}:{signal}")
        recorded = before[signal]
        for ticker in set(shares) | set(recorded):
            if abs(shares.get(ticker, 0.0) - recorded.get(ticker, 0.0)) > 1e-8:
                raise RuntimeError(f"POSITION_PATH_CHANGED:{prefix}:{signal}:{ticker}")
        return {ticker: weight for ticker, weight in targets[signal].items() if weight > 0}

    result = ledger.replay(str(original.candidate.iloc[0]), callback, prices,
                           execution_dates, signal_map)
    if len(result.daily) != len(original):
        raise RuntimeError(f"DAILY_LENGTH_CHANGED:{prefix}")
    numeric = ("nav", "pretrade_nav", "cash_weight", "gross_exposure",
               "transaction_cost_amount", "turnover")
    differences = {col: float(np.max(np.abs(result.daily[col].to_numpy(float)
                                              - original[col].to_numpy(float)))) for col in numeric}
    if any(value > 1e-10 for value in differences.values()):
        raise RuntimeError(f"REPLAY_DIVERGENCE:{prefix}:{differences}")

    rows = []
    day_info = original.set_index("execution_date")
    for trade in result.trades.itertuples():
        signal = pd.Timestamp(trade.signal_date)
        execution = pd.Timestamp(trade.execution_date)
        ticker = str(trade.ticker)
        price = float(opens.loc[(execution, ticker)])
        if not np.isfinite(price) or price <= 0:
            raise RuntimeError(f"INVALID_EXECUTION_PRICE:{prefix}:{execution}:{ticker}")
        old_qty = before[signal].get(ticker, 0.0)
        quantity = float(trade.notional / price)
        new_qty = old_qty + (quantity if trade.side == "BUY" else -quantity)
        day = day_info.loc[execution]
        rows.append({"policy": prefix, "signal_date": signal,
                     "execution_date": execution, "ticker": ticker,
                     "side": trade.side, "execution_open": price,
                     "shares_before": old_qty, "actual_trade_shares": quantity,
                     "shares_after": max(0.0, new_qty),
                     "sell_shares_over_before_shares":
                     quantity / old_qty if trade.side == "SELL" and old_qty > 0 else np.nan,
                     "buy_notional_over_pretrade_nav":
                     trade.notional / day.pretrade_nav if trade.side == "BUY" else np.nan,
                     "notional": trade.notional, "transaction_cost": trade.transaction_cost,
                     "cash_after_execution_day": day.cash_weight * day.nav})
    detail = pd.DataFrame(rows)
    if detail.empty:
        raise RuntimeError(f"NO_TRADES:{prefix}")
    receipt = {"policy": prefix, "daily_rows": len(original),
               "trade_rows": len(detail), "max_daily_difference": differences,
               "partial_sells": int(((detail.side == "SELL")
                                      & detail.sell_shares_over_before_shares.between(1e-9, 1-1e-9)).sum()),
               "full_exits": int(((detail.side == "SELL")
                                  & detail.sell_shares_over_before_shares.ge(1-1e-9)).sum())}
    return receipt, detail


def main() -> None:
    prices = pd.read_parquet(ROOT / "data/prices.parquet")
    if prices.trade_date.max() >= pd.Timestamp("2026-01-01"):
        raise RuntimeError("POST_CUTOFF_PRICE")
    opens = prices.set_index(["trade_date", "ticker"]).open
    if opens.index.has_duplicates:
        raise RuntimeError("DUPLICATE_PRICE_KEY")
    all_receipts, all_details = [], []
    for path in sorted((ROOT / "opt_artifacts").glob("*_daily.parquet")):
        prefix = path.name.removesuffix("_daily.parquet")
        receipt, detail = check_one(prefix, path,
                                    ROOT / "opt_artifacts" / f"{prefix}_decisions.parquet",
                                    "feasible_target_weight", prices, opens)
        all_receipts.append(receipt)
        all_details.append(detail)
        gc.collect()
    for path in sorted((ROOT / "rl_artifacts").glob("*_outer_daily.parquet")):
        prefix = path.name.removesuffix("_daily.parquet")
        receipt, detail = check_one(prefix, path,
                                    ROOT / "rl_artifacts" / f"{prefix}_targets.parquet",
                                    "target_weight", prices, opens)
        all_receipts.append(receipt)
        all_details.append(detail)
        gc.collect()
    if len(all_receipts) != 16:
        raise RuntimeError(f"POLICY_REPLAY_COUNT:{len(all_receipts)}")
    combined = pd.concat(all_details, ignore_index=True)
    combined.to_parquet(OUT / "pre2026_trade_details.parquet", index=False)
    receipt = {"status": "FROZEN_TARGET_REPLAY_MATCH", "policy_count": len(all_receipts),
               "trade_rows": len(combined), "policies": all_receipts,
               "scope": "pre-2026 sealed targets/prices/ledger; no model fit or 2026 source"}
    (OUT / "trade_replay_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "policy_count": len(all_receipts),
                      "trade_rows": len(combined),
                      "max_nav_difference": max(x["max_daily_difference"]["nav"] for x in all_receipts)}))


if __name__ == "__main__":
    main()
