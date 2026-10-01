"""Causal, self-financing research replay in per-security price-index units.

Policy inputs are signal-day feature rows and weights marked at that day's
close. A fixed target-weight order executes at the next supplied calendar open.
The next open may size that already-fixed order; it never enters the policy.
This is an explicit target-weight-order assumption, not an executable share
order submitted at the preceding close. Prices are supplied index coordinates:
``index_units`` (and the compatibility alias ``shares``) are NOT raw shares.
No dividends, corporate actions, cash interest, or shareholder-return claims
are inferred by this engine.

Target limits apply at decision time. Market moves, transaction costs and
blocked sells can move realized weights outside those limits. Cash cannot go
negative, and new entries cannot exceed the live-position count limit.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable, Mapping
from typing import Any

import numpy as np
import pandas as pd

TOL = 1e-10
WEIGHT_TOL = 1e-7  # Float32 policy outputs; accepted residuals are clipped below.
Policy = Callable[[pd.DataFrame, dict[str, float], float], Mapping[str, float]]


@dataclass
class ReplayResult:
    daily: pd.DataFrame
    trades: pd.DataFrame
    positions: pd.DataFrame
    target_decisions: pd.DataFrame
    diagnostics: pd.DataFrame
    metadata: dict[str, Any]
    valuation_intervals: pd.DataFrame


def _positive(value: Any) -> bool:
    try:
        return bool(np.isfinite(float(value)) and float(value) > 0)
    except (TypeError, ValueError):
        return False


def _dates(values: Any, name: str) -> pd.DatetimeIndex:
    result = pd.DatetimeIndex(pd.to_datetime(values))
    if result.tz is not None:
        raise ValueError(f"{name}: timezone-aware dates are unsupported; supply session dates")
    if result.hasnans or not result.equals(result.normalize()):
        raise ValueError(f"{name}: expected nonmissing, midnight session dates")
    return result


def _validate_targets(
    targets: Mapping[str, float], max_weight: float, max_positions: int, max_invested: float
) -> dict[str, float]:
    if not isinstance(targets, Mapping):
        raise ValueError("policy must return a ticker -> weight mapping")
    clean: dict[str, float] = {}
    for ticker, weight in targets.items():
        if not isinstance(ticker, str) or not ticker.strip():
            raise ValueError("target ticker must be a nonempty string")
        try:
            value = float(weight)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid target weight for {ticker}: {weight!r}") from exc
        if not np.isfinite(value) or value < 0:
            raise ValueError(f"nonfinite or negative target weight for {ticker}: {weight}")
        if value > max_weight + WEIGHT_TOL:
            raise ValueError(f"target weight for {ticker} exceeds max_weight={max_weight}: {value}")
        if value > 0:
            clean[ticker] = min(value, max_weight)
    if len(clean) > max_positions:
        raise ValueError(f"target has {len(clean)} positions, exceeds max_positions={max_positions}")
    total = sum(clean.values())
    if total > max_invested + WEIGHT_TOL:
        raise ValueError(f"target invested sum exceeds max_invested={max_invested}")
    if total > max_invested:
        clean = {t: w * max_invested / total for t, w in clean.items()}
    return clean


def run_replay(
    prices: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    features: pd.DataFrame,
    policy: Policy,
    *,
    candidate: str = "model",
    initial_cash: float = 1_000_000.0,
    cost_bps: float = 10.0,
    max_weight: float = 0.10,
    max_positions: int = 20,
    max_invested: float = 0.95,
    capacity_fraction: float | None = None,
    adv_column: str = "avg_dollar_volume_20d",
    initial_positions: Mapping[str, float] | None = None,
    missing_signal_policy: str = "hold",
    signal_start: str | pd.Timestamp | None = None,
    signal_end: str | pd.Timestamp | None = None,
    capacity_on_sells: bool = False,
) -> ReplayResult:
    """Replay close decisions -> next-calendar-open fills -> close valuation.

    Required price columns: ticker, trade_date, open, close. Required feature
    columns: ticker, signal_date. Only feature dates trigger decisions; other
    calendar dates (including terminal dates) only execute pending orders and
    mark holdings. Each policy receives a defensive copy of that signal day's
    rows; its ``attrs`` describe the valuation clock. The caller remains
    responsible for making feature columns and any policy closure point-in-time.

    If capacity_fraction is supplied, each security's trade notional is capped
    by that fraction of signal-day ``adv_column``. Missing/nonpositive ADV blocks
    its buy order. Sales default to unrestricted risk exits and disclose their
    available ADV. With capacity_on_sells=True, sales use current or last-known
    ADV; a sale without any ADV still exits, explicitly flagged unverified.
    ADV must use raw-price dollar notional units;
    index-coordinate prices and units make this a capacity proxy only.

    missing_signal_policy='cash' submits an empty target on featureless calendar
    days in [signal_start, signal_end] (default: first/last feature date). The
    policy is not called with an empty array. Dates outside that signal window
    only mark or execute pending orders, making terminal valuation independent.
    If new_buy_eligible exists, its signal-day mask also blocks increases at
    execution. A close-weight cap alone cannot prevent an overnight rebalance
    purchase of a stock that is no longer eligible for new capital.

    Missing opens never fill. Last observed prices may provide an explicitly
    stale indicative mark; neither stale nor unknown close NAV is certified.
    Unknown holdings are retained, full NAV is NaN (not zero), and decisions or
    pending executions requiring their unknown NAV are skipped until recovery.
    """
    cal = _dates(calendar, "calendar")
    if len(cal) == 0 or cal.has_duplicates or not cal.is_monotonic_increasing:
        raise ValueError("calendar must be nonempty, unique and increasing")
    if not np.isfinite(initial_cash) or initial_cash < 0:
        raise ValueError("initial_cash must be finite and nonnegative")
    if not np.isfinite(cost_bps) or not 0 <= cost_bps < 10_000:
        raise ValueError("cost_bps must be finite and in [0, 10000)")
    if not 0 < max_weight <= 1 or not 0 < max_invested <= 1:
        raise ValueError("max_weight and max_invested must be in (0, 1]")
    if isinstance(max_positions, bool) or int(max_positions) != max_positions or max_positions < 1:
        raise ValueError("max_positions must be a positive integer")
    if capacity_fraction is not None and (
        not np.isfinite(capacity_fraction) or not 0 < capacity_fraction <= 1
    ):
        raise ValueError("capacity_fraction must be None or in (0, 1]")
    if missing_signal_policy not in {"hold", "cash"}:
        raise ValueError("missing_signal_policy must be 'hold' or 'cash'")
    for frame, required, name in (
        (prices, {"ticker", "trade_date", "open", "close"}, "prices"),
        (features, {"ticker", "signal_date"}, "features"),
    ):
        if not required.issubset(frame.columns):
            raise ValueError(f"{name} missing columns: {sorted(required - set(frame.columns))}")
        if frame["ticker"].isna().any() or not frame["ticker"].map(
            lambda x: isinstance(x, str) and bool(x.strip())
        ).all():
            raise ValueError(f"{name}: tickers must be nonempty strings")
    px = prices[["ticker", "trade_date", "open", "close"]].copy()
    px["trade_date"] = _dates(px["trade_date"], "trade_date")
    fs = features.copy()
    fs["signal_date"] = _dates(fs["signal_date"], "signal_date")
    if px.duplicated(["trade_date", "ticker"]).any():
        raise ValueError("duplicate prices for (trade_date, ticker)")
    if fs.duplicated(["signal_date", "ticker"]).any():
        raise ValueError("duplicate features for (signal_date, ticker)")
    if not fs["signal_date"].isin(cal).all():
        raise ValueError("all feature signal_date values must be in calendar; slice features first")
    signal_lo = _dates([signal_start], "signal_start")[0] if signal_start is not None else fs["signal_date"].min()
    signal_hi = _dates([signal_end], "signal_end")[0] if signal_end is not None else fs["signal_date"].max()
    if missing_signal_policy == "cash" and (pd.isna(signal_lo) or pd.isna(signal_hi)):
        raise ValueError("empty features with missing_signal_policy='cash' require signal_start and signal_end")
    if not pd.isna(signal_lo) and not pd.isna(signal_hi) and signal_lo > signal_hi:
        raise ValueError("signal_start must not follow signal_end")
    if (not pd.isna(signal_lo) and fs["signal_date"].lt(signal_lo).any()) or (
        not pd.isna(signal_hi) and fs["signal_date"].gt(signal_hi).any()
    ):
        raise ValueError("features occur outside the explicit signal window")
    for column in ("open", "close"):
        px[column] = pd.to_numeric(px[column], errors="coerce")
    opens, closes = {}, {}
    for date, group in px.loc[px["trade_date"].isin(cal)].groupby("trade_date", sort=False):
        opens[date] = dict(zip(group["ticker"], group["open"]))
        closes[date] = dict(zip(group["ticker"], group["close"]))
    signal_frames = {d: g.copy() for d, g in fs.groupby("signal_date", sort=False)}
    holdings = {str(t): float(q) for t, q in (initial_positions or {}).items()}
    if any(not np.isfinite(q) or q < 0 for q in holdings.values()):
        raise ValueError("initial_positions must contain finite nonnegative index units")
    holdings = {t: q for t, q in holdings.items() if q > 0}
    if len(holdings) > max_positions:
        raise ValueError("initial_positions exceeds max_positions")
    if initial_cash == 0 and not holdings:
        raise ValueError("initial portfolio must have positive capital")
    # Seed only pre-calendar closes. There is no backward fill from future rows.
    last_marks: dict[str, tuple[float, pd.Timestamp, str]] = {}
    historical = px.loc[(px["trade_date"] < cal[0]) & px["ticker"].isin(holdings)].sort_values("trade_date")
    for row in historical.itertuples(index=False):
        if _positive(row.close):
            last_marks[row.ticker] = (float(row.close), row.trade_date, "close")
    cash = float(initial_cash)
    rate = float(cost_bps) / 10_000.0
    pending: dict[str, Any] | None = None
    latest_adv: dict[str, tuple[float, pd.Timestamp]] = {}
    daily_rows, trade_rows, position_rows, decision_rows, events = [], [], [], [], []
    previous_nav = previous_certified_nav = np.nan

    def event(date: pd.Timestamp, code: str, ticker: str | None = None, **detail: Any) -> None:
        events.append({"candidate": candidate, "date": date, "code": code, "ticker": ticker, **detail})

    for sequence, date in enumerate(cal):
        day_open = opens.get(date, {})
        day_close = closes.get(date, {})
        source_frame = signal_frames.get(date)
        signal_adv = dict(zip(source_frame["ticker"], source_frame[adv_column])) if (
            source_frame is not None and adv_column in source_frame
        ) else {}
        # Keep liquidity independent of any callback mutation, and snapshot it
        # into each order. Today's data cannot modify yesterday's pending order.
        for ticker, value in signal_adv.items():
            if _positive(value):
                latest_adv[ticker] = (float(value), date)
        cash_before = cash
        fees = buy_notional = sell_notional = 0.0
        blocked_orders = 0
        buy_scale = 1.0
        executed_signal = None if pending is None else pending["signal_date"]
        opening_marks: dict[str, float] = {}
        opening_stale = 0
        opening_unknown = 0
        for ticker in holdings:
            value = day_open.get(ticker, np.nan)
            if _positive(value):
                opening_marks[ticker] = float(value)
                last_marks[ticker] = (float(value), date, "open")
            elif ticker in last_marks:
                opening_marks[ticker] = last_marks[ticker][0]
                opening_stale += 1
            else:
                opening_marks[ticker] = np.nan
                opening_unknown += 1
        pretrade_nav = (
            cash + sum(q * opening_marks[t] for t, q in holdings.items())
            if opening_unknown == 0 else np.nan
        )

        if pending is not None:
            targets = pending["targets"]
            if not np.isfinite(pretrade_nav) or pretrade_nav <= 0:
                event(date, "execution_blocked_unknown_nav", signal_date=executed_signal)
                blocked_orders += len(set(targets) | set(holdings))
            else:
                wanted = {t: w * pretrade_nav for t, w in targets.items()}

                def cap(ticker: str, requested: float, side: str) -> float:
                    nonlocal blocked_orders
                    if capacity_fraction is None:
                        return requested
                    adv_info = pending["sell_adv"].get(ticker) if side == "SELL" else None
                    adv = adv_info[0] if adv_info else pending["adv"].get(ticker, np.nan)
                    if side == "SELL" and not capacity_on_sells:
                        if not _positive(adv):
                            event(date, "sell_capacity_unknown_exit_allowed", ticker, signal_date=executed_signal)
                        return requested
                    if not _positive(adv):
                        if side == "SELL":
                            event(date, "sell_capacity_unknown_exit_allowed", ticker, signal_date=executed_signal)
                            return requested
                        event(date, "missing_signal_day_adv", ticker, signal_date=executed_signal)
                        blocked_orders += 1
                        return 0.0
                    limit = float(adv) * capacity_fraction
                    if requested > limit + TOL:
                        event(date, "capacity_limited", ticker, requested_notional=requested,
                              allowed_notional=limit, signal_date=executed_signal)
                    return min(requested, limit)

                def record(ticker: str, side: str, notional: float, quantity: float,
                           prior_units: float, after_units: float, cost: float) -> None:
                    action = ("BUY" if prior_units <= TOL else "INCREASE") if side == "BUY" else (
                        "EXIT" if after_units <= TOL else "REDUCE")
                    adv_info = pending["sell_adv"].get(ticker) if side == "SELL" else None
                    trade_adv = adv_info[0] if adv_info else pending["adv"].get(ticker, np.nan)
                    adv_date = adv_info[1] if adv_info else (executed_signal if _positive(trade_adv) else pd.NaT)
                    trade_rows.append({
                        "candidate": candidate, "signal_date": executed_signal,
                        "execution_date": date, "ticker": ticker, "side": side, "action": action,
                        "price": float(day_open[ticker]), "notional": notional,
                        "index_units": quantity, "shares": quantity,
                        "index_units_before": prior_units, "index_units_after": after_units,
                        "transaction_cost": cost, "cost_bps": cost_bps,
                        "pretrade_nav": pretrade_nav,
                        "buy_fraction_nav": notional / pretrade_nav if side == "BUY" else 0.0,
                        "sell_fraction_original_units": quantity / prior_units if side == "SELL" else 0.0,
                        "capacity_proxy": capacity_fraction is not None,
                        "capacity_enforced": capacity_fraction is not None and (side == "BUY" or capacity_on_sells) and _positive(trade_adv),
                        "capacity_adv": trade_adv, "capacity_adv_source_date": adv_date,
                        "capacity_adv_stale": bool(not pd.isna(adv_date) and adv_date < executed_signal),
                    })

                # Sales settle before purchases; each side pays its full one-way cost.
                for ticker in sorted(holdings):
                    current = holdings[ticker] * opening_marks[ticker]
                    requested = max(0.0, current - wanted.get(ticker, 0.0))
                    if requested <= TOL:
                        continue
                    if not _positive(day_open.get(ticker, np.nan)):
                        event(date, "missing_open_sell", ticker, signal_date=executed_signal)
                        blocked_orders += 1
                        continue
                    notional = cap(ticker, requested, "SELL")
                    if notional <= TOL:
                        continue
                    prior_units = holdings[ticker]
                    quantity = min(prior_units, notional / float(day_open[ticker]))
                    notional = quantity * float(day_open[ticker])
                    after_units = prior_units - quantity
                    if after_units <= TOL:
                        holdings.pop(ticker)
                    else:
                        holdings[ticker] = after_units
                    fee = notional * rate
                    cash += notional - fee
                    fees += fee
                    sell_notional += notional
                    record(ticker, "SELL", notional, quantity, prior_units, max(0.0, after_units), fee)

                requests = {}
                reserved_names = set(holdings)
                for ticker in sorted(targets, key=lambda t: (-targets[t], t)):
                    current = holdings.get(ticker, 0.0) * opening_marks.get(ticker, 0.0)
                    requested = max(0.0, wanted[ticker] - current)
                    if requested <= TOL:
                        continue
                    if pending["buy_eligibility"] is not None and not pending["buy_eligibility"].get(ticker, False):
                        event(date, "buy_ineligible_blocked", ticker, signal_date=executed_signal)
                        blocked_orders += 1
                        continue
                    price = day_open.get(ticker, np.nan)
                    if not _positive(price):
                        event(date, "missing_open_buy", ticker, signal_date=executed_signal)
                        blocked_orders += 1
                        continue
                    if ticker not in reserved_names and len(reserved_names) >= max_positions:
                        event(date, "live_position_limit", ticker, signal_date=executed_signal)
                        blocked_orders += 1
                        continue
                    notional = cap(ticker, requested, "BUY")
                    if notional > TOL:
                        requests[ticker] = notional
                        reserved_names.add(ticker)
                requirement = sum(requests.values()) * (1.0 + rate)
                buy_scale = min(1.0, max(0.0, cash) / requirement) if requirement > 0 else 1.0
                for ticker, requested in requests.items():
                    notional = requested * buy_scale
                    if notional <= TOL:
                        continue
                    price = float(day_open[ticker])
                    quantity = notional / price
                    prior_units = holdings.get(ticker, 0.0)
                    holdings[ticker] = prior_units + quantity
                    last_marks[ticker] = (price, date, "open")
                    opening_marks[ticker] = price
                    fee = notional * rate
                    cash -= notional + fee
                    fees += fee
                    buy_notional += notional
                    record(ticker, "BUY", notional, quantity, prior_units, holdings[ticker], fee)
        if cash < -max(TOL, initial_cash * 1e-12):
            raise AssertionError(f"negative cash violates self financing: {date}: {cash}")
        if cash < 0:
            cash = 0.0  # Floating-point residual only; never an economic funding source.
        if len(holdings) > max_positions:
            raise AssertionError("live position count exceeded")
        pending = None
        open_posttrade_nav = (
            cash + sum(q * opening_marks.get(t, np.nan) for t, q in holdings.items())
            if opening_unknown == 0 else np.nan
        )

        known_value = 0.0
        close_values: dict[str, float] = {}
        marks_for_rows = []
        stale_count = unknown_count = 0
        for ticker, quantity in sorted(holdings.items()):
            fresh_close = day_close.get(ticker, np.nan)
            if _positive(fresh_close):
                last_marks[ticker] = (float(fresh_close), date, "close")
            mark = last_marks.get(ticker)
            unknown = mark is None
            stale = not unknown and not _positive(fresh_close)
            if unknown:
                unknown_count += 1
                value = np.nan
                event(date, "unknown_position_valuation", ticker)
            else:
                value = quantity * mark[0]
                known_value += value
                stale_count += int(stale)
            close_values[ticker] = value
            marks_for_rows.append((ticker, quantity, mark, value, stale, unknown))
        nav = cash + known_value if unknown_count == 0 else np.nan
        certified = unknown_count == 0 and stale_count == 0 and np.isfinite(nav)
        certified_nav = nav if certified else np.nan
        status = "unknown" if unknown_count else "stale" if stale_count else "certified"
        cash_weight = cash / nav if np.isfinite(nav) and nav > 0 else np.nan
        close_weights = {t: v / nav for t, v in close_values.items()} if np.isfinite(nav) and nav > 0 else {}
        for ticker, quantity, mark, value, stale, unknown in marks_for_rows:
            position_rows.append({
                "candidate": candidate, "date": date, "ticker": ticker,
                "index_units": quantity, "shares": quantity,
                "mark": np.nan if mark is None else mark[0],
                "mark_date": pd.NaT if mark is None else mark[1],
                "mark_source": "unknown" if mark is None else mark[2],
                "market_value": value, "weight": close_weights.get(ticker, np.nan),
                "stale": stale, "unknown": unknown,
            })
        daily_rows.append({
            "candidate": candidate, "date": date, "execution_date": date,
            "signal_date": executed_signal, "cash": cash, "nav": nav,
            "certified_nav": certified_nav, "valuation_status": status,
            "open_pretrade_nav": pretrade_nav, "pretrade_nav": pretrade_nav,
            "open_posttrade_nav": open_posttrade_nav,
            "open_stale_count": opening_stale, "open_unknown_count": opening_unknown,
            "known_position_value": known_value, "stale_count": stale_count,
            "unknown_count": unknown_count, "actual_name_count": len(holdings),
            "cash_weight": cash_weight,
            "gross_exposure": known_value / nav if np.isfinite(nav) and nav > 0 else np.nan,
            "net_return": certified_nav / previous_certified_nav - 1.0
                if _positive(previous_certified_nav) and np.isfinite(certified_nav) else np.nan,
            "indicative_return": nav / previous_nav - 1.0
                if _positive(previous_nav) and np.isfinite(nav) else np.nan,
            "transaction_cost_amount": fees, "buy_notional": buy_notional,
            "sell_notional": sell_notional, "traded_notional": buy_notional + sell_notional,
            "turnover": 0.5 * (buy_notional + sell_notional) / pretrade_nav
                if _positive(pretrade_nav) else np.nan,
            "one_way_traded_fraction": (buy_notional + sell_notional) / pretrade_nav
                if _positive(pretrade_nav) else np.nan,
            "buy_cash_scale": buy_scale, "blocked_order_count": blocked_orders,
            "nav_identity_error": nav - (cash + known_value) if np.isfinite(nav) else np.nan,
            "cash_flow_identity_error": cash - cash_before - (sell_notional - buy_notional - fees),
            "cost_identity_error": fees - (buy_notional + sell_notional) * rate,
            "open_self_finance_error": open_posttrade_nav - pretrade_nav + fees
                if np.isfinite(open_posttrade_nav) and np.isfinite(pretrade_nav) else np.nan,
            "realized_max_weight": max(close_weights.values(), default=0.0)
                if np.isfinite(nav) else np.nan,
            "target_cap_drift": any(w > max_weight + TOL for w in close_weights.values()),
        })

        # This block is deliberately after close valuation and before reading
        # any next-date prices. A terminal date without features has no policy call.
        missing_cash_signal = missing_signal_policy == "cash" and signal_lo <= date <= signal_hi and date not in signal_frames
        if date in signal_frames or missing_cash_signal:
            next_date = cal[sequence + 1] if sequence + 1 < len(cal) else pd.NaT
            if not np.isfinite(nav) or nav <= 0:
                event(date, "decision_blocked_unknown_nav")
                decision_rows.append({
                    "candidate": candidate, "signal_date": date, "execution_date": next_date,
                    "ticker": None, "target_weight": np.nan, "current_weight": np.nan,
                    "cash_weight": np.nan, "signal_close_nav": nav,
                    "status": "blocked_unknown_valuation", "target_sum": np.nan,
                })
            else:
                frame = signal_frames[date].copy(deep=True) if date in signal_frames else fs.iloc[:0].copy(deep=True)
                frame.attrs.update(signal_date=date, valuation_clock="signal_close",
                                   stale_count=stale_count, unknown_count=unknown_count,
                                   valuation_status=status, unit="price_index_units")
                targets = _validate_targets({} if missing_cash_signal else policy(frame, close_weights.copy(), float(cash_weight)),
                                            max_weight, max_positions, max_invested)
                adv = signal_adv.copy()
                for ticker in sorted(set(targets) | set(holdings)) or [None]:
                    decision_rows.append({
                        "candidate": candidate, "signal_date": date, "execution_date": next_date,
                        "ticker": ticker, "target_weight": targets.get(ticker, 0.0),
                        "current_weight": close_weights.get(ticker, 0.0),
                        "cash_weight": cash_weight, "signal_close_nav": nav,
                        "status": "no_next_session" if pd.isna(next_date) else "submitted",
                        "target_sum": sum(targets.values()),
                        "signal_stale_count": stale_count,
                        "signal_day_adv": adv.get(ticker, np.nan),
                        "missing_signal_cash": missing_cash_signal,
                    })
                if not pd.isna(next_date):
                    eligibility = dict(zip(source_frame["ticker"], source_frame["new_buy_eligible"].fillna(False).astype(bool))) if (
                        source_frame is not None and "new_buy_eligible" in source_frame
                    ) else None
                    pending = {"signal_date": date, "targets": targets, "adv": adv,
                               "sell_adv": latest_adv.copy(), "buy_eligibility": eligibility}
        previous_nav, previous_certified_nav = nav, certified_nav

    daily = pd.DataFrame(daily_rows)
    intervals = []
    interval_start: int | None = None
    for i in range(len(daily) + 1):
        bad = i < len(daily) and daily.iloc[i]["valuation_status"] != "certified"
        if bad and interval_start is None:
            interval_start = i
        if not bad and interval_start is not None:
            segment = daily.iloc[interval_start:i]
            intervals.append({
                "candidate": candidate, "start_date": segment.iloc[0]["date"],
                "end_date": segment.iloc[-1]["date"], "day_count": len(segment),
                "unknown_days": int((segment["unknown_count"] > 0).sum()),
                "stale_days": int((segment["stale_count"] > 0).sum()),
                "resolved": i < len(daily),
            })
            interval_start = None
    metadata = {
        "unit": "per-security price-index units; shares is a compatibility alias, not raw shares",
        "return_interpretation": "index-coordinate research return, not certified shareholder total return",
        "decision_clock": "signal_date close; only same-date features passed to policy",
        "execution_clock": "next supplied calendar session open",
        "order_assumption": "target weights fixed at signal close; quantities sized on next-open marked pretrade NAV",
        "valuation_clock": "daily session close; fresh close required for certified_nav",
        "unknown_valuation": "preserve holdings; full NAV NaN; skip dependent decisions/executions",
        "stale_valuation": "last observed price only; indicative nav retained, certified_nav and net_return withheld",
        "cost_bps_one_way": cost_bps,
        "cost_scope": "fee and slippage combined proxy charged to actual buy and sell notionals",
        "initial_cash": initial_cash, "max_target_weight": max_weight,
        "max_positions": max_positions, "max_target_invested": max_invested,
        "target_roundoff_tolerance": WEIGHT_TOL,
        "target_roundoff_handling": "tiny float32 excess clipped to exact target limits; material excess raises",
        "new_capital_eligibility": "signal-day new_buy_eligible, if supplied, blocks both new entries and increases",
        "capacity_fraction": capacity_fraction,
        "capacity_on_sells": capacity_on_sells,
        "capacity_adv_column": adv_column,
        "capacity_interpretation": "signal-day raw-dollar ADV notional proxy; not an exact raw-share capacity model",
        "sell_liquidity_assumption": "unrestricted exits" if not capacity_on_sells else "last-known ADV cap; missing ADV exits allowed with diagnostic",
        "missing_signal_policy": missing_signal_policy,
        "signal_start": None if pd.isna(signal_lo) else str(signal_lo.date()),
        "signal_end": None if pd.isna(signal_hi) else str(signal_hi.date()),
        "unmodeled": ["cash interest", "corporate-action entitlement ledger", "shareholder total return"],
        "caller_responsibility": "point-in-time feature columns, price provenance, and policy closure",
        "uncertified_days": int((daily["valuation_status"] != "certified").sum()),
        "terminal_liquidation": False,
    }
    trade_columns = ["candidate", "signal_date", "execution_date", "ticker", "side", "action", "price",
                     "notional", "index_units", "shares", "index_units_before", "index_units_after",
                     "transaction_cost", "cost_bps", "pretrade_nav", "buy_fraction_nav",
                     "sell_fraction_original_units", "capacity_proxy", "capacity_enforced",
                     "capacity_adv", "capacity_adv_source_date", "capacity_adv_stale"]
    position_columns = ["candidate", "date", "ticker", "index_units", "shares", "mark", "mark_date",
                        "mark_source", "market_value", "weight", "stale", "unknown"]
    decision_columns = ["candidate", "signal_date", "execution_date", "ticker", "target_weight",
                        "current_weight", "cash_weight", "signal_close_nav", "status", "target_sum",
                        "signal_stale_count", "signal_day_adv", "missing_signal_cash"]
    interval_columns = ["candidate", "start_date", "end_date", "day_count", "unknown_days", "stale_days", "resolved"]
    return ReplayResult(
        daily=daily, trades=pd.DataFrame(trade_rows, columns=trade_columns),
        positions=pd.DataFrame(position_rows, columns=position_columns),
        target_decisions=pd.DataFrame(decision_rows, columns=decision_columns),
        diagnostics=pd.DataFrame(events) if events else pd.DataFrame(columns=["candidate", "date", "code", "ticker"]),
        metadata=metadata, valuation_intervals=pd.DataFrame(intervals, columns=interval_columns),
    )


replay = run_replay
