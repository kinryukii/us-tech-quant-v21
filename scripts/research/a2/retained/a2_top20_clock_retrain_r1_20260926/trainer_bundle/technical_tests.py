"""No market fitting: corrected clock, partial sale, missing open and date gates."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

import ledger
import rl_train
import safe_inputs

ROOT = Path(__file__).resolve().parent


def run_case(prices: pd.DataFrame):
    signals = {pd.Timestamp("2024-01-03"): pd.Timestamp("2024-01-02"),
               pd.Timestamp("2024-01-04"): pd.Timestamp("2024-01-03")}
    seen = []

    def target(signal, shares, values, nav):
        seen.append((str(signal.date()), dict(shares), dict(values), nav))
        return {"AAA": .8 if signal == pd.Timestamp("2024-01-02") else .4}

    result = ledger.replay("CLOCK_MICRO", target, prices,
                           list(signals), signals)
    return result, seen


def clock_micro():
    base = pd.DataFrame({"ticker": ["AAA"] * 3,
                         "trade_date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
                         "open": [100., 100., 100.], "close": [100., 100., 100.]})
    normal, normal_seen = run_case(base)
    changed = base.copy()
    changed.loc[changed.trade_date.eq("2024-01-04"), "open"] = 200.
    perturbed, changed_seen = run_case(changed)
    if normal_seen[1] != changed_seen[1]:
        raise AssertionError("future execution open changed decision input")
    if normal.trades.side.tolist() != ["BUY", "SELL"]:
        raise AssertionError("partial sell not executed")
    if not (0 < normal.trades.iloc[1].notional < 1):
        raise AssertionError("partial sale amount invalid")
    if normal.daily.nav_identity_error.abs().max() > 1e-10:
        raise AssertionError("cash/share NAV identity")
    if normal.daily.cost_identity_error.abs().max() > 1e-10:
        raise AssertionError("cost identity")
    missing = base.copy()
    missing.loc[missing.trade_date.eq("2024-01-04"), "open"] = np.nan
    blocked, blocked_seen = run_case(missing)
    if normal_seen[1] != blocked_seen[1]:
        raise AssertionError("missing execution open changed target")
    if len(blocked.trades) != 1 or int(blocked.daily.blocked_sell_count.iloc[-1]) != 1:
        raise AssertionError("missing open did not block sale")
    return {"target_invariant_under_future_open": True, "partial_sale": True,
            "missing_open_blocks_sale": True, "cash_cost_identity": True}


def real_prefix():
    panel = safe_inputs.guarded_parquet(ROOT / "data" / "panel.parquet", "signal_date")
    prices = safe_inputs.guarded_parquet(ROOT / "data" / "prices.parquet", "trade_date")
    signals = sorted(pd.Timestamp(d) for d in panel.loc[panel.signal_date.dt.year.eq(2024), "signal_date"].unique())[:3]
    calendar = sorted(pd.Timestamp(d) for d in prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique())
    following = dict(zip(calendar[:-1], calendar[1:]))
    ticker = str(panel.loc[panel.signal_date.eq(signals[0]) & panel.raw_rank.eq(1), "ticker"].iloc[0])
    execution = [following[d] for d in signals[:2]]
    local = prices.loc[prices.ticker.eq(ticker) & prices.trade_date.le(execution[-1])]
    local = local.loc[local.trade_date.ge(signals[0])].copy()
    if len(local) < 3 or local.open.isna().any() or local.close.isna().any():
        raise RuntimeError("PRE2026_PREFIX_PRICE_UNAVAILABLE")
    mapping = dict(zip(execution, signals[:2]))

    def replay_once(frame):
        captured = []
        def target(signal, shares, values, nav):
            captured.append((signal, dict(shares), dict(values), nav))
            return {ticker: .08 if signal == signals[0] else .04}
        return ledger.replay("REAL_PREFIX", target, frame, execution, mapping), captured

    original, before = replay_once(local)
    altered = local.copy()
    altered.loc[altered.trade_date.eq(execution[-1]), "open"] *= 1.25
    _, after = replay_once(altered)
    if before[-1] != after[-1]:
        raise AssertionError("real pre-2026 next open changed target input")
    if original.daily.nav_identity_error.abs().max() > 1e-10:
        raise AssertionError("real prefix NAV identity")
    return {"ticker": ticker, "first_signal": str(signals[0].date()),
            "last_execution": str(execution[-1].date()), "future_open_invariance": True}


def rl_ensemble_micro():
    class Constant(torch.nn.Module):
        def __init__(self, logit):
            super().__init__()
            self.logit = logit

        def forward(self, x):
            return torch.full((len(x),), self.logit)

    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    prices = pd.DataFrame({"ticker": ["AAA", "AAA", "QQQ", "QQQ"],
                           "trade_date": [dates[0], dates[1], dates[0], dates[1]],
                           "open": [100., 100., 1., 1.], "close": [100., 100., 1., 1.]})
    days = {dates[0]: (["AAA"], np.array([1]), np.zeros((1, 11)))}
    result, targets = rl_train.evaluate_ensemble([Constant(-1.), Constant(0.)],
                                                  days, [dates[0]], prices, "RL_MICRO")
    if abs(targets.target_weight.iloc[0] - .025) > 1e-8:
        raise AssertionError("RL ensemble did not average target on shared account")
    if len(result.trades) != 1 or result.daily.nav_identity_error.abs().max() > 1e-10:
        raise AssertionError("RL ensemble ledger identity")
    across = pd.DataFrame({"signal_date": pd.to_datetime(["2023-12-29", "2024-01-02"])})
    calendar = pd.DataFrame({"ticker": "QQQ",
                             "trade_date": pd.to_datetime(["2023-12-29", "2024-01-02", "2024-01-03"])})
    try:
        rl_train.eligible_days(across, calendar, "2023-01-01", "2024-01-01")
    except RuntimeError as exc:
        if "NO_COMPLETE_RL_DATES" not in str(exc):
            raise
    else:
        raise AssertionError("cross-year reward trajectory admitted")
    return {"shared_account_target_average": True, "cross_year_reward_rejected": True}


def main():
    result = {"clock_micro": clock_micro(), "real_pre2026_prefix": real_prefix(),
              "rl_ensemble_micro": rl_ensemble_micro()}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
