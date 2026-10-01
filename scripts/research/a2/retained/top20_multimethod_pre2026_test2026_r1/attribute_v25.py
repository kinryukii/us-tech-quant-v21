"""Arithmetic terminal-wealth contribution on the same price index coordinate."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from policy_engine import Account, PriceStore, HERE, FEE


def main() -> None:
    weights = pd.read_parquet(HERE / "V25_WEIGHTS.parquet")
    extra = HERE / "V25_P10_WEIGHTS.parquet"
    if extra.exists():
        weights = pd.concat([weights, pd.read_parquet(extra)], ignore_index=True)
    panel = pd.read_parquet(HERE / "PRE2026_SHARED_PANEL.parquet")
    panel["signal_date"] = pd.to_datetime(panel.signal_date)
    source_days = {date: block.sort_values("ticker") for date, block in panel.groupby("signal_date")}
    store = PriceStore(pd.read_parquet(HERE / "PRE2026_PRICE_COORDINATE.parquet"))
    detail = []
    checks = {}
    for policy, policy_weights in weights.groupby("policy", sort=True):
        account = Account(store)
        prior_exec = None
        for day, block in policy_weights.groupby("signal_date", sort=True):
            block = block.sort_values("ticker")
            origin = source_days[pd.Timestamp(day)]
            execution = pd.Timestamp(origin.execution_date.iloc[0])
            if block.ticker.tolist() != origin.ticker.tolist():
                raise RuntimeError(f"TARGET_CANDIDATE_MISMATCH:{policy}:{day}")
            for ticker, shares in account.shares.items():
                if prior_exec is not None:
                    pnl = shares * (store.open[(execution, ticker)] - store.open[(prior_exec, ticker)])
                    detail.append({"policy": policy, "execution_date": execution,
                                   "ticker": ticker, "market_pnl": pnl, "fee": 0.})
            transaction = account.execute(pd.Timestamp(day), execution,
                                          block.ticker.tolist(), block.target_weight.to_numpy(float))
            for trade in transaction["trades"]:
                detail.append({"policy": policy, "execution_date": execution,
                               "ticker": trade["ticker"], "market_pnl": 0.,
                               "fee": FEE * trade["notional"]})
            prior_exec = execution
        terminal = pd.Timestamp(origin.label_end_date.iloc[0])
        for ticker, shares in account.shares.items():
            pnl = shares * (store.open[(terminal, ticker)] - store.open[(prior_exec, ticker)])
            detail.append({"policy": policy, "execution_date": terminal,
                           "ticker": ticker, "market_pnl": pnl,
                           "fee": FEE * shares * store.open[(terminal, ticker)]})
        terminal_result = account.liquidate(terminal)
        native = pd.read_parquet(HERE / "V25_POLICY_DAILY.parquet")
        if policy == "P10":
            native = pd.read_parquet(HERE / "V25_P10_DAILY.parquet")
        expected = float(native.loc[native.policy.eq(policy)].net_nav_at_execution.iloc[-1])
        if abs(account.cash - expected) > 1e-10:
            raise RuntimeError(f"REPLAY_TERMINAL_MISMATCH:{policy}")
        checks[policy] = {"terminal_nav": expected,
                          "terminal_fee": terminal_result["fee"]}
    table = pd.DataFrame(detail)
    grouped = table.groupby(["policy", "ticker"], as_index=False)[["market_pnl", "fee"]].sum()
    grouped["net_terminal_wealth_contribution"] = grouped.market_pnl - grouped.fee
    for policy, part in grouped.groupby("policy"):
        error = float(part.net_terminal_wealth_contribution.sum() - (checks[policy]["terminal_nav"] - 1))
        if abs(error) > 1e-9:
            raise RuntimeError(f"CONTRIBUTION_IDENTITY:{policy}:{error}")
        checks[policy]["contribution_identity_error"] = error
    baseline = grouped.loc[grouped.policy.eq("B0"), ["ticker", "net_terminal_wealth_contribution"]].set_index("ticker")
    primary = grouped.loc[grouped.policy.eq("P6"), ["ticker", "net_terminal_wealth_contribution"]].set_index("ticker")
    relative = (primary.reindex(primary.index.union(baseline.index), fill_value=0)
                - baseline.reindex(primary.index.union(baseline.index), fill_value=0))
    relative = relative.rename(columns={"net_terminal_wealth_contribution": "P6_minus_B0_terminal_wealth_contribution"})
    relative.to_csv(HERE / "V25_P6_MINUS_B0_CONTRIBUTIONS.csv")
    grouped.to_csv(HERE / "V25_CONTRIBUTIONS.csv", index=False)
    (HERE / "V25_ATTRIBUTION_CHECK.json").write_text(json.dumps({
        "status": "PASS", "coordinate": "INDEX_COORDINATE_DIAGNOSTIC",
        "shareholder_net_return": "NOT_IDENTIFIABLE", "checks": checks,
        "P6_minus_B0_terminal_delta": checks["P6"]["terminal_nav"] - checks["B0"]["terminal_nav"],
        "relative_top_positive": relative.nlargest(5, "P6_minus_B0_terminal_wealth_contribution").reset_index().to_dict("records"),
        "relative_top_negative": relative.nsmallest(5, "P6_minus_B0_terminal_wealth_contribution").reset_index().to_dict("records")}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "policies": len(checks),
                      "P6_minus_B0_terminal_delta": checks["P6"]["terminal_nav"] - checks["B0"]["terminal_nav"]}))


if __name__ == "__main__":
    main()
