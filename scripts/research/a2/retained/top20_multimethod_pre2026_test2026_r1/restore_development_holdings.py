"""Reconstruct native shares/cash from saved targets without another QP call."""
from __future__ import annotations

import numpy as np
import pandas as pd

from policy_engine import Account, PriceStore, HERE


def main(fold: str) -> None:
    prefix = f"DEVELOPMENT_{fold}" if fold in ("D1", "D2") else "V25" if fold == "V25" else "FINAL_INSAMPLE"
    target_path = HERE / f"{prefix}_WEIGHTS.parquet"
    target = pd.read_parquet(target_path)
    existing = pd.read_parquet(HERE / f"{prefix}_POLICY_DAILY.parquet")
    panel = pd.read_parquet(HERE / "PRE2026_SHARED_PANEL.parquet")
    panel["signal_date"] = pd.to_datetime(panel.signal_date)
    panel["execution_date"] = pd.to_datetime(panel.execution_date)
    panel["label_end_date"] = pd.to_datetime(panel.label_end_date)
    store = PriceStore(pd.read_parquet(HERE / "PRE2026_PRICE_COORDINATE.parquet"))
    rows = []
    action_rows = []
    for policy, part in target.groupby("policy", sort=True):
        account = Account(store)
        for day, block in part.groupby("signal_date", sort=True):
            block = block.sort_values("ticker")
            source = panel.loc[panel.signal_date.eq(day)].sort_values("ticker")
            assert block.ticker.tolist() == source.ticker.tolist()
            execution = pd.Timestamp(source.execution_date.iloc[0])
            transaction = account.execute(day, execution, block.ticker.tolist(), block.target_weight.to_numpy(float))
            for ticker in sorted(set(block.ticker) | set(transaction["shares_before"])):
                before = transaction["shares_before"].get(ticker, 0.)
                after = transaction["shares_after"].get(ticker, 0.)
                change = after - before
                if before <= 1e-14 and after <= 1e-14:
                    action = "WAIT"
                elif before <= 1e-14:
                    action = "BUY"
                elif after <= 1e-14:
                    action = "EXIT"
                elif change > 1e-14:
                    action = "ADD"
                elif change < -1e-14:
                    action = "REDUCE"
                else:
                    action = "HOLD"
                action_rows.append({"fold": fold, "policy": policy,
                                    "signal_date": day, "execution_date": execution,
                                    "ticker": ticker, "action_from_actual_quantity": action,
                                    "shares_before": before, "shares_after": after,
                                    "quantity_change": change,
                                    "out_of_list": ticker not in set(block.ticker)})
            for ticker, shares in transaction["shares_after"].items():
                rows.append({"fold": fold, "policy": policy, "signal_date": day,
                             "execution_date": execution, "ticker": ticker,
                             "shares_after_execution": shares,
                             "execution_open": store.open[(execution, ticker)],
                             "position_value_after_execution": shares * store.open[(execution, ticker)],
                             "cash_after_execution": transaction["cash"],
                             "nav_after_execution": transaction["net_nav"]})
            recorded = existing.loc[existing.policy.eq(policy) & existing.signal_date.eq(day)]
            assert len(recorded) == 1
            assert abs(transaction["net_nav"] - recorded.net_nav_at_execution.iloc[0]) < 1e-10
            assert abs(transaction["cash"] - recorded.cash_at_execution.iloc[0]) < 1e-10
        terminal = pd.Timestamp(source.label_end_date.iloc[0])
        liquidation = account.liquidate(terminal)
        saved_end = existing.loc[existing.policy.eq(policy) & existing.fallback.eq("TERMINAL_LIQUIDATION")]
        assert len(saved_end) == 1
        assert abs(liquidation["net_nav"] - saved_end.net_nav_at_execution.iloc[0]) < 1e-10
    pd.DataFrame(rows).to_parquet(HERE / f"{prefix}_HOLDINGS.parquet", index=False)
    pd.DataFrame(action_rows).to_parquet(HERE / f"{prefix}_ACTIONS.parquet", index=False)
    print(fold, len(rows), "holdings rows; exact daily cash/NAV restoration PASS")


if __name__ == "__main__":
    import sys
    requested = sys.argv[1:] or ["D1", "D2"]
    for f in requested:
        main(f)
