"""Thin action/fill recorder around the sealed R1 ledger; no model fitting.

The caller supplies a frozen decision callback returning (targets, per_ticker_metadata).
Metadata may include raw_target_weight, raw_action_logit, model_sha256 and
input_sha256. All fills and account values come from ledger.replay itself.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import ledger


def run_logged_replay(candidate, decide, prices, execution_dates,
                      signal_by_execution, *, input_identity, model_identity,
                      **ledger_kwargs):
    decisions = []

    def capture(signal, shares, values, nav):
        target, metadata = decide(signal, shares, values, nav)
        if not isinstance(target, dict) or not isinstance(metadata, dict):
            raise TypeError("decision must return (target_dict, metadata_dict)")
        if any(not isinstance(m, dict) for m in metadata.values()):
            raise TypeError("per-ticker metadata must be a dict")
        reserved = {"candidate", "signal_date", "execution_date", "ticker",
                    "shares_at_decision", "weight_at_decision", "decision_nav",
                    "feasible_target_weight", "side", "actual_trade_shares",
                    "transaction_cost", "shares_after_execution", "input_identity",
                    "model_identity", "execution_open", "actual_notional",
                    "cash_after_execution_day", "unfilled_or_unresolved_reason"}
        if any(reserved & set(m) for m in metadata.values()):
            raise ValueError("metadata overrides an accounting field")
        # Include zero-weight RL slots so a learned wait/exit remains visible.
        for ticker in sorted(set(target) | set(shares) | set(metadata)):
            m = metadata.get(ticker, {})
            decisions.append({"candidate": candidate, "signal_date": pd.Timestamp(signal),
                              "decision_clock": "signal_close_after_data",
                              "input_identity": input_identity,
                              "model_identity": model_identity,
                              "ticker": ticker, "shares_at_decision": float(shares.get(ticker, 0.0)),
                              "weight_at_decision": float(values.get(ticker, 0.0) / nav),
                              "decision_nav": float(nav),
                              "raw_target_weight": float(m.get("raw_target_weight", target.get(ticker, 0.0))),
                              "raw_action_logit": float(m.get("raw_action_logit", np.nan)),
                              "feasible_target_weight": float(target.get(ticker, 0.0)),
                              **m})
        return target

    result = ledger.replay(candidate, capture, prices, execution_dates,
                           signal_by_execution, **ledger_kwargs)
    decision_frame = pd.DataFrame(decisions)
    records = action_fill_records(result, decision_frame, prices)
    return result, decision_frame, records


def action_fill_records(result, decisions, prices):
    """Join actual ledger fills to decisions, including unfilled target actions."""
    if prices.duplicated(["trade_date", "ticker"]).any():
        raise ValueError("duplicate execution price key")
    opens = prices.set_index(["trade_date", "ticker"])["open"]
    fills = {(pd.Timestamp(r.execution_date), str(r.ticker)): r
             for r in result.trades.itertuples(index=False)}
    if len(fills) != len(result.trades):
        raise ValueError("more than one fill for one ticker/day")
    by_signal = {}
    for r in decisions.itertuples(index=False):
        signal, ticker = pd.Timestamp(r.signal_date), str(r.ticker)
        day_map = by_signal.setdefault(signal, {})
        if ticker in day_map:
            raise ValueError("duplicate decision key")
        day_map[ticker] = r._asdict()
    if sum(map(len, by_signal.values())) != len(decisions):
        raise ValueError("duplicate decision key")
    shares = {}
    rows = []
    for day in result.daily.itertuples(index=False):
        date = pd.Timestamp(day.execution_date)
        signal = pd.Timestamp(day.signal_date) if pd.notna(day.signal_date) else None
        day_decisions = by_signal.get(signal, {}) if signal is not None else {}
        tickers = set(shares) | set(day_decisions)
        for ticker in sorted(tickers):
            m = day_decisions.get(ticker, {})
            before = float(shares.get(ticker, 0.0))
            try:
                price = float(opens.loc[(date, ticker)])
            except KeyError:
                price = float("nan")
            if not np.isfinite(price) or price <= 0:
                price = float("nan")
            fill = fills.pop((date, ticker), None)
            if fill is not None and not np.isfinite(price):
                raise ValueError(f"ledger fill lacks valid execution open:{date}:{ticker}")
            qty = float(fill.notional / price) if fill is not None else 0.0
            side = fill.side if fill is not None else "NONE"
            if side == "SELL" and qty > before + 1e-8:
                raise AssertionError("logged sale exceeds actual shares")
            after = max(0.0, before + qty * (1 if side == "BUY" else -1))
            if after <= 1e-14:
                shares.pop(ticker, None)
            else:
                shares[ticker] = after
            target = float(m.get("feasible_target_weight", 0.0))
            weight = float(m.get("weight_at_decision", 0.0))
            intended = abs(target - weight) > 1e-10
            reason = None
            if fill is None and intended:
                if not np.isfinite(price):
                    reason = ("missing_open_blocked_exit" if before > 0 and target == 0 else
                              "missing_open_skipped_entry" if before == 0 and target > 0 else
                              "missing_open_action_unresolved")
                else:
                    reason = "no_fill_after_open_revaluation_or_tolerance"
            elif side == "BUY" and day.buy_cash_scale < 1 - 1e-10:
                reason = "cash_scaled_partial_fill"
            row = {**m, "candidate": day.candidate, "signal_date": signal,
                   "execution_date": date, "execution_clock": "next_session_open", "ticker": ticker,
                   "shares_before_execution": before, "execution_open": price,
                   "planned_delta_weight_at_decision": target - weight,
                   "side": side, "actual_trade_shares": qty,
                   "sell_shares_over_before_shares": qty / before if side == "SELL" and before > 0 else np.nan,
                   "buy_notional_over_pretrade_nav": float(fill.notional / day.pretrade_nav) if side == "BUY" else np.nan,
                   "actual_notional": float(fill.notional) if fill is not None else 0.0,
                   "transaction_cost": float(fill.transaction_cost) if fill is not None else 0.0,
                   "shares_after_execution": after,
                   "cash_after_execution_day": float(day.cash_weight * day.nav),
                   "buy_cash_scale_day": float(day.buy_cash_scale),
                   "unfilled_or_unresolved_reason": reason}
            rows.append(row)
        if len(shares) != int(day.actual_name_count):
            raise AssertionError("logged shares differ from ledger name count")
    if fills:
        raise ValueError(f"unmatched ledger fills: {len(fills)}")
    details = pd.DataFrame(rows)
    if not details.empty:
        costs = details.groupby("execution_date").transaction_cost.sum()
        expected = result.daily.set_index("execution_date").transaction_cost_amount
        if not np.allclose(costs.reindex(expected.index, fill_value=0), expected, atol=1e-10, rtol=0):
            raise AssertionError("logged fees differ from ledger")
    return details
