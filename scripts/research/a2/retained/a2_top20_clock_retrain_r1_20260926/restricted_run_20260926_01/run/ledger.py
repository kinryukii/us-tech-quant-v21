"""Whitelisted E5 Replay/safe_div source with the R1 close-clock seam.
No other E5 execution or accounting branch is changed.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
TOL = 1e-10
COST_RATE = 0.001

def safe_div(a: float, b: float) -> float:
    return float(a / b) if b and np.isfinite(b) else float("nan")

@dataclass
class Replay:
    daily: pd.DataFrame
    contributions: pd.DataFrame
    trades: pd.DataFrame

def replay(
    candidate: str,
    targets: dict[pd.Timestamp, dict[str, float]],
    prices: pd.DataFrame,
    execution_dates: list[pd.Timestamp],
    signal_by_execution: dict[pd.Timestamp, pd.Timestamp | None],
    raw_prices: pd.DataFrame | None = None,
    control_targets: dict[pd.Timestamp, dict[str, float]] | None = None,
) -> Replay:
    open_wide = prices.pivot(index="trade_date", columns="ticker", values="open").sort_index()
    close_wide = prices.pivot(index="trade_date", columns="ticker", values="close").sort_index()
    raw_open_wide = None if raw_prices is None else raw_prices.pivot(index="trade_date", columns="ticker", values="open").sort_index()
    raw_close_wide = None if raw_prices is None else raw_prices.pivot(index="trade_date", columns="ticker", values="close").sort_index()
    shares: dict[str, float] = {}
    prior_marks: dict[str, float] = {}
    cash = 1.0
    prior_nav = 1.0
    chained: set[str] = set()
    prior_raw_marks: dict[str, float] = {}
    daily_rows, contribution_rows, trade_rows = [], [], []

    def opening(date: pd.Timestamp, ticker: str) -> float:
        try: value = float(open_wide.at[date, ticker])
        except (KeyError, TypeError, ValueError): return np.nan
        return value if np.isfinite(value) and value > 0 else np.nan

    def mark(date: pd.Timestamp, ticker: str) -> tuple[float, bool, pd.Timestamp]:
        value = opening(date, ticker)
        if np.isfinite(value): return value, False, date
        if ticker not in close_wide.columns: raise RuntimeError(f"unvaluable position:{candidate}:{ticker}:{date}")
        hist = close_wide.loc[close_wide.index < date, ticker].dropna()
        hist = hist.loc[np.isfinite(hist.to_numpy(float)) & (hist.to_numpy(float) > 0)]
        if hist.empty: raise RuntimeError(f"unvaluable position:{candidate}:{ticker}:{date}")
        return float(hist.iloc[-1]), True, pd.Timestamp(hist.index[-1])

    def raw_mark(date: pd.Timestamp, ticker: str) -> float:
        if raw_open_wide is None or raw_close_wide is None:
            raise RuntimeError("raw counterfactual price lineage unavailable")
        try:
            value = float(raw_open_wide.at[date, ticker])
        except (KeyError, TypeError, ValueError):
            value = np.nan
        if np.isfinite(value) and value > 0:
            return value
        if ticker not in raw_close_wide.columns:
            raise RuntimeError(f"unavailable raw counterfactual mark:{candidate}:{ticker}:{date}")
        hist = raw_close_wide.loc[raw_close_wide.index < date, ticker].dropna()
        hist = hist.loc[np.isfinite(hist.to_numpy(float)) & (hist.to_numpy(float) > 0)]
        if hist.empty:
            raise RuntimeError(f"unavailable raw counterfactual mark:{candidate}:{ticker}:{date}")
        return float(hist.iloc[-1])

    for sequence, date0 in enumerate(execution_dates):
        date = pd.Timestamp(date0)
        signal = signal_by_execution.get(date)
        decision_values = {}
        if signal is not None:
            for ticker, qty in shares.items():
                if ticker not in close_wide.columns:
                    raise RuntimeError(f"no signal-close series:{ticker}:{signal}")
                hist = close_wide.loc[close_wide.index <= signal, ticker].dropna()
                hist = hist.loc[np.isfinite(hist.to_numpy(float)) & (hist.to_numpy(float) > 0)]
                if hist.empty:
                    raise RuntimeError(f"no prior signal-close mark:{ticker}:{signal}")
                decision_values[ticker] = qty * float(hist.iloc[-1])
            decision_nav = cash + sum(decision_values.values())
            target = targets(signal, shares.copy(), decision_values.copy(), decision_nav)
        else:
            target = {}
        before = dict(shares)
        cash_before = cash
        marks, mark_dates, stale, pre_values, market_pnl = {}, {}, {}, {}, {}
        for ticker, qty in before.items():
            if ticker in chained:
                raw_value = raw_mark(date, ticker)
                raw_prior = prior_raw_marks[ticker]
                value = prior_marks[ticker] * raw_value / raw_prior
                is_stale, source_date = False, date
                prior_raw_marks[ticker] = raw_value
            else:
                value, is_stale, source_date = mark(date, ticker)
            marks[ticker], mark_dates[ticker], stale[ticker] = value, source_date, is_stale
            pre_values[ticker] = qty * value
            market_pnl[ticker] = 0.0 if sequence == 0 else qty * (value - prior_marks[ticker])
        pretrade_nav = cash_before + sum(pre_values.values())
        gross_return = 0.0 if sequence == 0 else pretrade_nav / prior_nav - 1.0
        # target fixed at signal close
        desired = {t: w * pretrade_nav for t, w in target.items()}
        pre_weights = {t: v / pretrade_nav for t, v in pre_values.items()}
        target_turnover = 0.5 * sum(abs(target.get(t, 0.0) - pre_weights.get(t, 0.0)) for t in set(target) | set(pre_weights))
        sells, buys = {}, {}
        transaction_cost = 0.0
        blocked_sells = skipped_buys = 0
        for ticker in sorted(set(shares) | set(target)):
            current, wanted = pre_values.get(ticker, 0.0), desired.get(ticker, 0.0)
            if current <= wanted + 1e-14: continue
            price = opening(date, ticker)
            if not np.isfinite(price): blocked_sells += 1; continue
            notional = current - wanted
            qty = notional / price
            shares[ticker] = max(0.0, shares[ticker] - qty)
            if shares[ticker] <= 1e-14: shares.pop(ticker, None)
            cash += notional
            sells[ticker] = notional
            cost = 0.5 * notional * COST_RATE
            transaction_cost += cost
            trade_rows.append({"candidate": candidate, "execution_date": date, "signal_date": signal, "ticker": ticker, "side": "SELL", "notional": notional, "transaction_cost": cost})
        post_sell = {t: q * marks[t] for t, q in shares.items()}
        requested = {}
        for ticker in sorted(target):
            current, wanted = post_sell.get(ticker, 0.0), desired[ticker]
            if wanted <= current + 1e-14: continue
            price = opening(date, ticker)
            if not np.isfinite(price): skipped_buys += 1; continue
            requested[ticker] = wanted - current
            marks[ticker], mark_dates[ticker], stale[ticker] = price, date, False
        buy_total = sum(requested.values())
        requirement = buy_total * (1.0 + 0.5 * COST_RATE)
        buy_scale = min(1.0, max(0.0, cash - transaction_cost) / requirement) if requirement > 0 else 1.0
        for ticker, requested_notional in requested.items():
            notional = requested_notional * buy_scale
            if notional <= 1e-14: continue
            price = marks[ticker]
            shares[ticker] = shares.get(ticker, 0.0) + notional / price
            cash -= notional
            buys[ticker] = notional
            cost = 0.5 * notional * COST_RATE
            transaction_cost += cost
            trade_rows.append({"candidate": candidate, "execution_date": date, "signal_date": signal, "ticker": ticker, "side": "BUY", "notional": notional, "transaction_cost": cost})
        cash -= transaction_cost
        if cash < -TOL: raise RuntimeError(f"negative cash:{candidate}:{date}:{cash}")
        cash = max(0.0, cash)
        post_values = {t: q * marks[t] for t, q in shares.items()}
        nav = cash + sum(post_values.values())
        traded = sum(sells.values()) + sum(buys.values())
        turnover = 0.5 * traded / pretrade_nav
        net_return = nav / prior_nav - 1.0
        cost_by_ticker: dict[str, float] = {}
        for t, v in sells.items(): cost_by_ticker[t] = cost_by_ticker.get(t, 0.0) + 0.5 * v * COST_RATE
        for t, v in buys.items(): cost_by_ticker[t] = cost_by_ticker.get(t, 0.0) + 0.5 * v * COST_RATE
        for ticker in sorted(set(before) | set(shares) | set(cost_by_ticker)):
            pnl = market_pnl.get(ticker, 0.0)
            cost = cost_by_ticker.get(ticker, 0.0)
            contribution_rows.append({"candidate": candidate, "execution_date": date, "signal_date": signal, "ticker": ticker,
                                      "gross_contribution": pnl / prior_nav, "cost_contribution": -cost / prior_nav,
                                      "net_contribution": (pnl - cost) / prior_nav, "held_before": ticker in before, "held_after": ticker in shares})
        daily_rows.append({
            "candidate": candidate, "signal_date": signal, "execution_date": date, "pretrade_nav": pretrade_nav, "nav": nav,
            "gross_return": gross_return, "net_return": net_return, "turnover": turnover,
            "transaction_cost_amount": transaction_cost, "transaction_cost_fraction": transaction_cost / pretrade_nav,
            "target_turnover": target_turnover, "gross_exposure": safe_div(sum(post_values.values()), nav), "cash_weight": safe_div(cash, nav),
            "intended_or_executed_name_count": len(target), "actual_name_count": len(shares), "buy_cash_scale": buy_scale,
            "skipped_buy_count": skipped_buys, "blocked_sell_count": blocked_sells,
            "nav_identity_error": nav - (cash + sum(post_values.values())),
            "cost_identity_error": transaction_cost - 0.5 * traded * COST_RATE,
            "turnover_identity_error": turnover - 0.5 * traded / pretrade_nav,
        })
        if candidate != "E0_CONTROL" and control_targets is not None and signal is not None:
            control_names = set(control_targets.get(signal, {}))
            newly_divergent = set(shares) - control_names
            for ticker in newly_divergent - chained:
                prior_raw_marks[ticker] = raw_mark(date, ticker)
            chained |= newly_divergent
            chained &= set(shares)
            prior_raw_marks = {t: v for t, v in prior_raw_marks.items() if t in chained}
        prior_nav = nav
        prior_marks = {t: marks[t] for t in shares}
    return Replay(pd.DataFrame(daily_rows), pd.DataFrame(contribution_rows), pd.DataFrame(trade_rows))
