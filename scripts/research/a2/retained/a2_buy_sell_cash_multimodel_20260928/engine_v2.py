"""Holding-aware, causally separated decisions and next-open execution.

Quantities are price-index units, not raw shareholder shares. No missing model
key means exit. See EXECUTION_SEMANTICS.md for the interface and proof boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any
import json

import numpy as np
import pandas as pd

TOL = 1e-10
WEIGHT_TOL = 1e-7


@dataclass(frozen=True)
class OperationalExit:
    reason: str
    known_at: Any
    source_id: str


@dataclass
class HoldingAwareDecision:
    model_decisions: Mapping[str, float] = field(default_factory=dict)
    operational_exits: Mapping[str, OperationalExit] = field(default_factory=dict)
    raw_model_outputs: Any = None


@dataclass(frozen=True)
class HoldingAwareContext:
    signal_date: pd.Timestamp
    signal_asof: pd.Timestamp
    current_weights: dict[str, float]
    current_units: dict[str, float]
    cash_weight: float
    cash: float
    nav: float
    reserved_tickers: tuple[str, ...]
    reserved_units: dict[str, float]
    reserved_weights: dict[str, float]
    reserved_weight: float
    reserved_slots: int
    reserved_reasons: dict[str, tuple[str, ...]]
    available_slots: int
    available_weight: float
    max_positions: int
    max_weight: float
    max_invested: float
    buy_restricted_tickers: tuple[str, ...]
    sell_restricted_tickers: tuple[str, ...]
    decision_tickers: tuple[str, ...]
    planned_operational_exits: dict[str, OperationalExit]

    @property
    def weights(self):
        return self.current_weights

    @property
    def investable_budget_weight(self):
        return self.available_weight


@dataclass
class ReplayResult:
    daily: pd.DataFrame
    trades: pd.DataFrame
    positions: pd.DataFrame
    target_decisions: pd.DataFrame
    diagnostics: pd.DataFrame
    metadata: dict[str, Any]
    valuation_intervals: pd.DataFrame
    raw_model_outputs: pd.DataFrame
    signal_contexts: pd.DataFrame
    operational_actions: pd.DataFrame
    execution_results: pd.DataFrame


def positive(value):
    try:
        return bool(np.isfinite(float(value)) and float(value) > 0)
    except (TypeError, ValueError):
        return False


def dates(values, name):
    result = pd.DatetimeIndex(pd.to_datetime(values))
    if result.tz is not None or result.hasnans or not result.equals(result.normalize()):
        raise ValueError(f"{name} requires nonmissing naive session dates")
    return result


def encoded(value):
    def convert(item):
        if isinstance(item, (pd.Timestamp, np.datetime64)):
            return str(item)
        if isinstance(item, np.ndarray):
            return item.tolist()
        if isinstance(item, np.generic):
            return item.item()
        if isinstance(item, OperationalExit):
            return {"reason": item.reason, "known_at": str(item.known_at), "source_id": item.source_id}
        raise TypeError(f"unserializable audit value: {type(item).__name__}")
    return json.dumps(value, default=convert, sort_keys=True, ensure_ascii=False, allow_nan=False)


def checked_exits(actions, asof):
    if not isinstance(actions, Mapping):
        raise ValueError("operational_exits must be a mapping")
    result = {}
    for ticker, action in actions.items():
        if (not isinstance(action, OperationalExit) or not isinstance(action.reason, str)
                or not isinstance(action.source_id, str) or not action.reason.strip() or not action.source_id.strip()):
            raise ValueError("OperationalExit requires a nonempty reason and source_id")
        known = pd.Timestamp(action.known_at)
        if pd.isna(known) or known.tzinfo != asof.tzinfo or known > asof:
            raise ValueError(f"operational exit not known at signal: {ticker}")
        result[str(ticker)] = action
    return result


def run_replay(
    prices, calendar, features, policy, *, candidate="model", initial_cash=1_000_000.,
    cost_bps=10., max_weight=.10, max_positions=20, max_invested=.95,
    capacity_fraction=None, adv_column="avg_dollar_volume_20d", initial_positions=None,
    signal_start=None, signal_end=None, capacity_on_sells=False,
    known_restrictions=None, operational_exits_by_signal=None, signal_asof=None,
    missing_signal_policy="hold",
):
    """policy(decision_day, HoldingAwareContext) -> HoldingAwareDecision.

    All held units remain in account state. Decision-day rows exclude reserved
    holdings and new names already known unavailable at this signal. Known
    restrictions are exact-date rows with ticker, signal_date, known_at,
    source_id, reason, and optional sell_restricted/buy_restricted booleans.
    Prices flagged price_quality_warning are never consumed as usable marks.
    """
    cal = dates(calendar, "calendar")
    if len(cal) == 0 or cal.has_duplicates or not cal.is_monotonic_increasing:
        raise ValueError("calendar must be nonempty, unique and increasing")
    if missing_signal_policy != "hold":
        raise ValueError("v2 forbids implicit cash liquidation; use explicit operational exits")
    if not np.isfinite(initial_cash) or initial_cash < 0 or not np.isfinite(cost_bps) or not 0 <= cost_bps < 10_000:
        raise ValueError("invalid initial cash or one-way cost")
    if not 0 < max_weight <= 1 or not 0 < max_invested <= 1 or int(max_positions) != max_positions or max_positions < 1:
        raise ValueError("invalid portfolio constraints")
    if capacity_fraction is not None and (not np.isfinite(capacity_fraction) or not 0 < capacity_fraction <= 1):
        raise ValueError("invalid capacity_fraction")
    for frame, required, name in [(prices, {"ticker", "trade_date", "open", "close"}, "prices"),
                                  (features, {"ticker", "signal_date"}, "features")]:
        if not required.issubset(frame):
            raise ValueError(f"{name} missing {required - set(frame)}")
        if not frame.ticker.map(lambda t: isinstance(t, str) and bool(t.strip())).all():
            raise ValueError(f"invalid {name} ticker")
    px = prices.copy()
    px["trade_date"] = dates(px.trade_date, "trade_date")
    fs = features.copy()
    fs["signal_date"] = dates(fs.signal_date, "signal_date")
    if px.duplicated(["trade_date", "ticker"]).any() or fs.duplicated(["signal_date", "ticker"]).any():
        raise ValueError("duplicate price or feature key")
    if not fs.signal_date.isin(cal).all():
        raise ValueError("slice feature signal dates to supplied calendar")
    if "price_quality_warning" not in px:
        px["price_quality_warning"] = False
    else:
        px["price_quality_warning"] = px.price_quality_warning.fillna(True).astype(bool)
    for c in ["open", "close"]:
        px[c] = pd.to_numeric(px[c], errors="coerce")
    quotes = {d: {r.ticker: (r.open, r.close, bool(r.price_quality_warning)) for r in g.itertuples()}
              for d, g in px.loc[px.trade_date.isin(cal)].groupby("trade_date", sort=False)}
    frames = {d: g.copy() for d, g in fs.groupby("signal_date", sort=False)}
    lo = pd.Timestamp(signal_start) if signal_start is not None else fs.signal_date.min()
    hi = pd.Timestamp(signal_end) if signal_end is not None else fs.signal_date.max()
    if pd.isna(lo) or pd.isna(hi):
        raise ValueError("empty features require an explicit signal_start and signal_end")
    if lo > hi or fs.signal_date.lt(lo).any() or fs.signal_date.gt(hi).any():
        raise ValueError("inconsistent signal window")
    restrictions = {}
    if known_restrictions is not None and len(known_restrictions):
        kr = known_restrictions.copy()
        required = {"signal_date", "ticker", "known_at", "source_id", "reason"}
        if not required.issubset(kr):
            raise ValueError("known restrictions require dated source evidence")
        kr["signal_date"] = dates(kr.signal_date, "restriction signal_date")
        restrictions = {d: g for d, g in kr.groupby("signal_date", sort=False)}
    scheduled_exits = {pd.Timestamp(d): a for d, a in (operational_exits_by_signal or {}).items()}
    asofs = {pd.Timestamp(d): pd.Timestamp(v) for d, v in (signal_asof or {}).items()}
    holdings = {str(t): float(q) for t, q in (initial_positions or {}).items() if float(q) != 0}
    if any(not positive(q) for q in holdings.values()) or len(holdings) > max_positions:
        raise ValueError("invalid initial index units")
    if initial_cash == 0 and not holdings:
        raise ValueError("empty initial account")
    marks = {}
    for r in px.loc[(px.trade_date < cal[0]) & px.ticker.isin(holdings)].sort_values("trade_date").itertuples():
        if not r.price_quality_warning and positive(r.close):
            marks[r.ticker] = (float(r.close), r.trade_date, "close")
    cash, rate = float(initial_cash), float(cost_bps) / 10_000
    last_adv, pending = {}, None
    rows = {k: [] for k in ["daily", "trades", "positions", "target_decisions", "diagnostics",
                            "raw_model_outputs", "signal_contexts", "operational_actions", "execution_results"]}
    previous_nav = previous_certified = np.nan

    def event(date, code, ticker=None, **extra):
        rows["diagnostics"].append(dict(candidate=candidate, date=date, code=code, ticker=ticker, **extra))

    for i, date in enumerate(cal):
        day_quotes = quotes.get(date, {})
        source_day = frames.get(date, fs.iloc[:0])
        signal_adv = dict(zip(source_day.ticker, source_day[adv_column])) if adv_column in source_day else {}
        for ticker, adv in signal_adv.items():
            if positive(adv):
                last_adv[ticker] = (float(adv), date)

        def quote(ticker, which):
            value = day_quotes.get(ticker)
            if value is None:
                return np.nan, "MISSING_PRICE_ROW"
            if value[2]:
                return np.nan, "PRICE_QUALITY_UNCERTIFIED"
            price = value[0 if which == "open" else 1]
            return (float(price), "AVAILABLE") if positive(price) else (np.nan, f"MISSING_OR_INVALID_{which.upper()}")

        opening = {}
        open_stale = open_unknown = 0
        for ticker in holdings:
            value, _ = quote(ticker, "open")
            if positive(value):
                opening[ticker] = value
                marks[ticker] = (value, date, "open")
            elif ticker in marks:
                opening[ticker] = marks[ticker][0]
                open_stale += 1
            else:
                opening[ticker] = np.nan
                open_unknown += 1
        pre_nav = cash + sum(q * opening[t] for t, q in holdings.items()) if not open_unknown else np.nan
        cash_before = cash
        fees = buys_total = sells_total = 0.
        blocked_count = 0
        buy_scale = 1.
        executed_signal = pending["signal_date"] if pending else pd.NaT

        if pending:
            def outcome(ticker, status, reason, side="NONE", notional=0., quantity=0., cost=0.):
                order = pending["orders"][ticker]
                rows["execution_results"].append(dict(
                    candidate=candidate, decision_id=pending["decision_id"], order_id=order["order_id"],
                    signal_date=pending["signal_date"], execution_date=date, ticker=ticker,
                    decision_semantic=order["semantic"], order_type=order["kind"],
                    execution_semantic="EXECUTION_REJECTED" if status == "REJECTED" else status,
                    status=status, reason=reason, side=side, notional=notional, index_units=quantity,
                    transaction_cost=cost, actual_names_at_event=len(holdings)))

            def reject(ticker, reason, side):
                outcome(ticker, "REJECTED", reason, side)
                compatibility = "live_position_limit" if reason == "LIVE_POSITION_LIMIT" else (
                    f"missing_open_{side.lower()}" if reason in {"MISSING_PRICE_ROW", "PRICE_QUALITY_UNCERTIFIED", "MISSING_OR_INVALID_OPEN"} else reason.lower())
                event(date, compatibility, ticker, signal_date=executed_signal, decision_id=pending["decision_id"],
                      phase="EXECUTION", rejection_reason=reason)

            def capped(ticker, notional, side):
                if capacity_fraction is None or (side == "SELL" and not capacity_on_sells):
                    return notional
                adv = pending["adv"].get(ticker, np.nan)
                if side == "SELL" and not positive(adv):
                    adv = pending["last_adv"].get(ticker, (np.nan, pd.NaT))[0]
                if not positive(adv):
                    if side == "SELL":
                        event(date, "sell_capacity_unknown_exit_allowed", ticker, decision_id=pending["decision_id"])
                        return notional
                    return 0.
                return min(notional, float(adv) * capacity_fraction)

            def fill(ticker, side, notional, price):
                before = holdings.get(ticker, 0.)
                quantity = min(before, notional / price) if side == "SELL" else notional / price
                amount = quantity * price
                after = before + quantity * (1 if side == "BUY" else -1)
                if after <= TOL:
                    holdings.pop(ticker, None)
                    after = 0.
                else:
                    holdings[ticker] = after
                cost = amount * rate
                order = pending["orders"][ticker]
                action = ("BUY" if before <= TOL else "INCREASE") if side == "BUY" else ("EXIT" if after <= TOL else "REDUCE")
                adv_info = pending["last_adv"].get(ticker) if side == "SELL" else None
                adv = adv_info[0] if adv_info else pending["adv"].get(ticker, np.nan)
                adv_date = adv_info[1] if adv_info else executed_signal if positive(adv) else pd.NaT
                rows["trades"].append(dict(
                    candidate=candidate, decision_id=pending["decision_id"], order_id=order["order_id"],
                    signal_date=executed_signal, execution_date=date, ticker=ticker, side=side, action=action,
                    decision_semantic=order["semantic"], price=price, notional=amount, index_units=quantity,
                    shares=quantity, index_units_before=before, index_units_after=after, transaction_cost=cost,
                    cost_bps=cost_bps, pretrade_nav=pre_nav, buy_fraction_nav=amount / pre_nav if side == "BUY" else 0.,
                    sell_fraction_original_units=quantity / before if side == "SELL" else 0.,
                    capacity_proxy=capacity_fraction is not None,
                    capacity_enforced=capacity_fraction is not None and (side == "BUY" or capacity_on_sells) and positive(adv),
                    capacity_adv=adv, capacity_adv_source_date=adv_date,
                    capacity_adv_stale=bool(pd.notna(adv_date) and adv_date < executed_signal)))
                outcome(ticker, "FILLED", "ACTUAL_FILL", side, amount, quantity, cost)
                return amount, cost

            if not positive(pre_nav):
                for ticker, order in pending["orders"].items():
                    if order["kind"] == "HOLD_UNITS":
                        outcome(ticker, "PRESERVED_UNITS", "UNKNOWN_NAV_NO_CAPITAL_CREATED")
                    else:
                        reject(ticker, "UNKNOWN_NAV", "NONE")
                        blocked_count += 1
            else:
                wanted = {}
                acted = set()
                for ticker, order in pending["orders"].items():
                    if order["kind"] == "HOLD_UNITS":
                        outcome(ticker, "PRESERVED_UNITS", "MODEL_NO_DECISION_OR_SIGNAL_RESERVATION")
                        acted.add(ticker)
                    else:
                        wanted[ticker] = order["weight"] * pre_nav
                # Known reservations are never implicitly sent as rebalance sells.
                for ticker in sorted(wanted):
                    current = holdings.get(ticker, 0.) * opening.get(ticker, 0.)
                    requested = max(0., current - wanted[ticker])
                    if requested <= TOL:
                        continue
                    acted.add(ticker)
                    price, reason = quote(ticker, "open")
                    if ticker in pending["sell_restricted"]:
                        reject(ticker, "SIGNAL_KNOWN_SELL_RESTRICTION", "SELL")
                        blocked_count += 1
                    elif not positive(price):
                        reject(ticker, reason, "SELL")
                        blocked_count += 1
                    else:
                        amount = capped(ticker, requested, "SELL")
                        if amount > TOL:
                            amount, cost = fill(ticker, "SELL", amount, price)
                            cash += amount - cost
                            sells_total += amount
                            fees += cost
                            if amount < requested - TOL:
                                outcome(ticker, "PARTIALLY_FILLED", "SELL_CAPACITY_LIMIT", "SELL")
                requests = {}
                reserved_names = set(holdings)
                for ticker in sorted(wanted, key=lambda t: (-pending["orders"][t]["weight"], t)):
                    current = holdings.get(ticker, 0.) * opening.get(ticker, 0.)
                    requested = max(0., wanted[ticker] - current)
                    if requested <= TOL:
                        continue
                    acted.add(ticker)
                    price, reason = quote(ticker, "open")
                    if not pending["buy_allowed"].get(ticker, False):
                        reject(ticker, "SIGNAL_BUY_INELIGIBLE", "BUY")
                        blocked_count += 1
                    elif not positive(price):
                        reject(ticker, reason, "BUY")
                        blocked_count += 1
                    elif ticker not in reserved_names and len(reserved_names) >= max_positions:
                        reject(ticker, "LIVE_POSITION_LIMIT", "BUY")
                        blocked_count += 1
                    else:
                        amount = capped(ticker, requested, "BUY")
                        if amount > TOL:
                            requests[ticker] = (amount, price)
                            reserved_names.add(ticker)
                        else:
                            reject(ticker, "MISSING_SIGNAL_ADV", "BUY")
                            blocked_count += 1
                required_cash = sum(v[0] for v in requests.values()) * (1 + rate)
                buy_scale = min(1., max(cash, 0.) / required_cash) if required_cash > 0 else 1.
                for ticker, (amount, price) in requests.items():
                    amount *= buy_scale
                    if amount <= TOL:
                        reject(ticker, "INSUFFICIENT_CASH", "BUY")
                        blocked_count += 1
                        continue
                    amount, cost = fill(ticker, "BUY", amount, price)
                    cash -= amount + cost
                    buys_total += amount
                    fees += cost
                    opening[ticker] = price
                    marks[ticker] = (price, date, "open")
                for ticker in set(pending["orders"]) - acted:
                    outcome(ticker, "NO_ACTION", "TARGET_ALREADY_MET_OR_NO_POSITION")
            pending = None
        if cash < -max(TOL, initial_cash * 1e-12) or len(holdings) > max_positions:
            raise AssertionError("cash/actual-position invariant violated")
        cash = max(cash, 0.)
        open_after = cash + sum(q * opening.get(t, np.nan) for t, q in holdings.items()) if not open_unknown else np.nan
        known_value, stale_count, unknown_count = 0., 0, 0
        position_data = []
        close_values = {}
        for ticker, quantity in sorted(holdings.items()):
            close, close_reason = quote(ticker, "close")
            if positive(close):
                marks[ticker] = (close, date, "close")
            mark = marks.get(ticker)
            unknown = mark is None
            stale = not unknown and not positive(close)
            value = np.nan if unknown else quantity * mark[0]
            unknown_count += int(unknown)
            stale_count += int(stale)
            if not unknown:
                known_value += value
            close_values[ticker] = value
            position_data.append((ticker, quantity, mark, value, stale, unknown, close_reason))
        nav = cash + known_value if unknown_count == 0 else np.nan
        certified = nav if unknown_count == stale_count == 0 else np.nan
        weights = {t: v / nav for t, v in close_values.items()} if positive(nav) else {t: np.nan for t in holdings}
        cash_weight = cash / nav if positive(nav) else np.nan
        for ticker, quantity, mark, value, stale, unknown, reason in position_data:
            rows["positions"].append(dict(candidate=candidate, date=date, ticker=ticker, index_units=quantity, shares=quantity,
                mark=np.nan if mark is None else mark[0], mark_date=pd.NaT if mark is None else mark[1],
                mark_source="unknown" if mark is None else mark[2], market_value=value, weight=weights[ticker],
                stale=stale, unknown=unknown, current_close_reason=reason))
        rows["daily"].append(dict(candidate=candidate, date=date, execution_date=date, signal_date=executed_signal,
            cash=cash, nav=nav, certified_nav=certified, valuation_status="unknown" if unknown_count else "stale" if stale_count else "certified",
            pretrade_nav=pre_nav, open_pretrade_nav=pre_nav, open_posttrade_nav=open_after,
            open_stale_count=open_stale, open_unknown_count=open_unknown, known_position_value=known_value,
            stale_count=stale_count, unknown_count=unknown_count, actual_name_count=len(holdings), cash_weight=cash_weight,
            gross_exposure=known_value / nav if positive(nav) else np.nan,
            net_return=certified / previous_certified - 1 if positive(previous_certified) and positive(certified) else np.nan,
            indicative_return=nav / previous_nav - 1 if positive(previous_nav) and positive(nav) else np.nan,
            transaction_cost_amount=fees, buy_notional=buys_total, sell_notional=sells_total, traded_notional=buys_total+sells_total,
            turnover=.5*(buys_total+sells_total)/pre_nav if positive(pre_nav) else np.nan,
            buy_cash_scale=buy_scale, blocked_order_count=blocked_count,
            nav_identity_error=nav-cash-known_value if positive(nav) else np.nan,
            cash_flow_identity_error=cash-cash_before-(sells_total-buys_total-fees),
            cost_identity_error=fees-(buys_total+sells_total)*rate,
            open_self_finance_error=open_after-pre_nav+fees if np.isfinite(open_after) and np.isfinite(pre_nav) else np.nan))

        if lo <= date <= hi:
            decision_id = f"{candidate}|{date.date()}"
            next_date = cal[i+1] if i+1 < len(cal) else pd.NaT
            asof = asofs.get(date, date)
            if pd.isna(asof) or asof.date() != date.date():
                raise ValueError("signal_asof must lie in its signal session date")
            external_ops = checked_exits(scheduled_exits.get(date, {}), asof)
            input_names = set(source_day.ticker)
            buy_restricted, sell_restricted = set(), set()
            reserve_reasons = {}
            for ticker in set(holdings) | input_names:
                close, reason = quote(ticker, "close")
                if not positive(close):
                    buy_restricted.add(ticker)
                    if ticker in holdings:
                        sell_restricted.add(ticker)
                        reserve_reasons.setdefault(ticker, []).append(f"SIGNAL_CLOSE_UNAVAILABLE:{reason}")
                if ticker in holdings and ticker not in input_names:
                    reserve_reasons.setdefault(ticker, []).append("MODEL_INPUT_ROW_ABSENT")
            for r in restrictions.get(date, pd.DataFrame()).to_dict("records"):
                if pd.isna(r["reason"]) or pd.isna(r["source_id"]):
                    raise ValueError("known restriction has missing source evidence")
                evidence = OperationalExit(str(r["reason"]), r["known_at"], str(r["source_id"]))
                checked_exits({r["ticker"]: evidence}, asof)
                if bool(r.get("buy_restricted", False)):
                    buy_restricted.add(r["ticker"])
                if bool(r.get("sell_restricted", False)):
                    sell_restricted.add(r["ticker"])
                    if r["ticker"] in holdings:
                        reserve_reasons.setdefault(r["ticker"], []).append(f"KNOWN_RESTRICTION:{r['source_id']}")
            for ticker in external_ops:
                if ticker not in sell_restricted:
                    reserve_reasons.pop(ticker, None)
            if not positive(nav):
                reserve_reasons = {t: ["UNKNOWN_ACCOUNT_NAV"] for t in holdings}
            reserved = set(reserve_reasons)
            reserved_weight = sum(weights[t] for t in reserved) if positive(nav) else np.nan
            decision_day = source_day.loc[~source_day.ticker.isin(reserved | set(external_ops)) & ~(
                source_day.ticker.isin(buy_restricted) & ~source_day.ticker.isin(holdings))].copy(deep=True)
            context = HoldingAwareContext(date, asof, weights.copy(), holdings.copy(), cash_weight, cash, nav,
                tuple(sorted(reserved)), {t: holdings[t] for t in reserved}, {t: weights[t] for t in reserved},
                reserved_weight, len(reserved), {t: tuple(v) for t, v in reserve_reasons.items()},
                max(0, max_positions-len(reserved)), max(0., max_invested-reserved_weight) if positive(nav) else 0.,
                max_positions, max_weight, max_invested, tuple(sorted(buy_restricted)), tuple(sorted(sell_restricted)),
                tuple(decision_day.ticker), external_ops.copy())
            # Copy immutable source liquidity and eligibility before callbacks.
            eligible = dict(zip(source_day.ticker, source_day.new_buy_eligible.fillna(False).astype(bool))) if "new_buy_eligible" in source_day else dict.fromkeys(input_names, True)
            buy_allowed = {t: bool(eligible.get(t, False)) and t not in buy_restricted for t in input_names}
            decision_day.attrs.update(signal_date=date, decision_id=decision_id, valuation_clock="signal_close")
            result = policy(decision_day, context) if positive(nav) else HoldingAwareDecision()
            if not isinstance(result, HoldingAwareDecision):
                raise ValueError("v2 policy must return HoldingAwareDecision; a bare weight dict loses omission semantics")
            if not isinstance(result.model_decisions, Mapping):
                raise ValueError("model_decisions must preserve explicit ticker decisions")
            raw = {}
            for ticker, value in result.model_decisions.items():
                if ticker not in context.decision_tickers:
                    raise ValueError(f"model decision has no decision-day input row: {ticker}")
                number = float(value)
                if not np.isfinite(number) or number < 0 or number > max_weight + WEIGHT_TOL:
                    raise ValueError(f"invalid explicit model weight: {ticker}: {number}")
                raw[ticker] = number
            ops = {**external_ops, **checked_exits(result.operational_exits, asof)}
            rows["raw_model_outputs"].append(dict(candidate=candidate, decision_id=decision_id, signal_date=date,
                policy_called=positive(nav), model_decisions_json=encoded(raw), raw_model_outputs_json=encoded(result.raw_model_outputs),
                raw_model_outputs_provided=result.raw_model_outputs is not None,
                original_input_tickers_json=encoded(sorted(input_names)), decision_input_tickers_json=encoded(list(context.decision_tickers)),
                operational_exits_json=encoded(ops)))
            # Omission discovered only after model invocation remains a reservation.
            final_reserved = set(reserved)
            for ticker in holdings:
                if ticker not in raw and ticker not in ops:
                    final_reserved.add(ticker)
                    reserve_reasons.setdefault(ticker, []).append("MODEL_OUTPUT_KEY_ABSENT")
            for ticker in ops:
                if ticker not in sell_restricted:
                    final_reserved.discard(ticker)
            final_reserved_weight = sum(weights[t] for t in final_reserved) if positive(nav) else np.nan
            available_weight = max(0., max_invested-final_reserved_weight) if positive(nav) else 0.
            available_slots = max(0, max_positions-len(final_reserved))
            adapted = {t: min(v, max_weight) for t, v in raw.items() if t not in ops and t not in final_reserved}
            reasons = {t: [] for t in set(raw) | set(holdings) | set(ops)}
            for ticker in adapted:
                if not buy_allowed.get(ticker, False) and adapted[ticker] > weights.get(ticker, 0.):
                    adapted[ticker] = max(0., weights.get(ticker, 0.))
                    reasons[ticker].append("SIGNAL_NEW_CAPITAL_INELIGIBLE")
            positive_names = [t for t, w in adapted.items() if w > 0]
            ordered = sorted(positive_names, key=lambda t: (t not in holdings, -adapted[t], t))
            for ticker in ordered[available_slots:]:
                adapted[ticker] = 0.
                reasons[ticker].append("SIGNAL_RESERVED_SLOT_BUDGET")
            total = sum(adapted.values())
            if total > available_weight and total > 0:
                scale = available_weight / total
                for ticker in adapted:
                    if adapted[ticker] > 0:
                        adapted[ticker] *= scale
                        reasons[ticker].append("SIGNAL_RESERVED_CAPITAL_BUDGET")
            orders = {}
            for ticker in sorted(set(holdings) | set(raw) | set(ops)):
                operational = ticker in ops
                explicit = ticker in raw
                semantic = "OPERATIONAL_EXIT_REQUIRED" if operational else (
                    "MODEL_ACTIVE_EXIT" if explicit and raw[ticker] == 0 and ticker in holdings else
                    "MODEL_ZERO_ALLOCATION" if explicit and raw[ticker] == 0 else
                    "MODEL_TARGET_WEIGHT" if explicit else "MODEL_NO_DECISION")
                if operational:
                    kind, weight = "EXIT", 0.
                elif ticker in final_reserved:
                    kind, weight = "HOLD_UNITS", weights.get(ticker, np.nan)
                else:
                    kind, weight = "TARGET_WEIGHT", adapted.get(ticker, 0.)
                order_id = f"{decision_id}|{ticker}"
                orders[ticker] = dict(kind=kind, weight=weight, semantic=semantic, order_id=order_id)
                rows["target_decisions"].append(dict(candidate=candidate, decision_id=decision_id, order_id=order_id,
                    signal_date=date, execution_date=next_date, ticker=ticker, decision_semantic=semantic, order_type=kind,
                    model_input_row_present=ticker in input_names, decision_input_row_present=ticker in context.decision_tickers,
                    explicit_model_decision=explicit, raw_model_weight=raw.get(ticker, np.nan), target_weight=weight,
                    adapted_target_weight=weight, current_weight=weights.get(ticker, 0.), current_units=holdings.get(ticker, 0.),
                    hold_units=holdings.get(ticker, 0.) if ticker in final_reserved else 0.,
                    signal_reserved=ticker in final_reserved, signal_reservation_reasons="|".join(reserve_reasons.get(ticker, [])),
                    adaptation_reasons="|".join(reasons.get(ticker, [])), cash_weight=cash_weight, signal_close_nav=nav,
                    status="no_next_session" if pd.isna(next_date) else "submitted", signal_day_adv=signal_adv.get(ticker, np.nan),
                    reserved_weight=final_reserved_weight, active_target_sum=sum(adapted.values()),
                    total_signal_committed_weight=final_reserved_weight+sum(adapted.values()) if positive(nav) else np.nan))
            for ticker, action in ops.items():
                rows["operational_actions"].append(dict(candidate=candidate, decision_id=decision_id,
                    order_id=f"{decision_id}|{ticker}", signal_date=date, ticker=ticker, semantic="OPERATIONAL_EXIT_REQUIRED",
                    reason=action.reason, known_at=pd.Timestamp(action.known_at), source_id=action.source_id,
                    had_position=ticker in holdings, signal_sell_restricted=ticker in sell_restricted,
                    reserved_until_execution=ticker in final_reserved))
            rows["signal_contexts"].append(dict(candidate=candidate, decision_id=decision_id, signal_date=date, signal_asof=asof,
                nav=nav, cash=cash, cash_weight=cash_weight, input_count=len(source_day), decision_input_count=len(decision_day),
                current_units_json=encoded(holdings), current_weights_json=encoded(weights) if positive(nav) else None,
                reserved_tickers_json=encoded(list(context.reserved_tickers)), reserved_reasons_json=encoded(context.reserved_reasons),
                reserved_slots=context.reserved_slots, reserved_weight=context.reserved_weight,
                available_slots=context.available_slots, available_weight=context.available_weight,
                final_reserved_tickers_json=encoded(sorted(final_reserved)), final_reserved_slots=len(final_reserved),
                final_reserved_weight=final_reserved_weight, final_available_slots=available_slots,
                final_available_weight=available_weight, active_target_count=sum(w > 0 for w in adapted.values()),
                active_target_weight=sum(adapted.values()), policy_called=positive(nav)))
            if pd.notna(next_date):
                pending = dict(decision_id=decision_id, signal_date=date, orders=orders, buy_allowed=buy_allowed,
                    sell_restricted=sell_restricted.copy(), adv=signal_adv.copy(), last_adv=last_adv.copy())
        previous_nav, previous_certified = nav, certified

    frames_out = {key: pd.DataFrame(value) for key, value in rows.items()}
    # Stable empty schemas keep consumers and parquet output deterministic.
    minimum = {"trades": ["candidate", "decision_id", "order_id", "signal_date", "execution_date", "ticker", "side", "action",
                           "decision_semantic", "price", "notional", "index_units", "shares", "index_units_before", "index_units_after",
                           "transaction_cost", "cost_bps", "pretrade_nav", "buy_fraction_nav", "sell_fraction_original_units",
                           "capacity_proxy", "capacity_enforced", "capacity_adv", "capacity_adv_source_date", "capacity_adv_stale"],
               "positions": ["candidate", "date", "ticker", "index_units", "shares", "mark", "mark_date", "mark_source",
                             "market_value", "weight", "stale", "unknown", "current_close_reason"],
               "target_decisions": ["candidate", "decision_id", "order_id", "signal_date", "execution_date", "ticker", "decision_semantic",
                                    "order_type", "model_input_row_present", "decision_input_row_present", "explicit_model_decision",
                                    "raw_model_weight", "target_weight", "adapted_target_weight", "current_weight", "current_units", "hold_units",
                                    "signal_reserved", "signal_reservation_reasons", "adaptation_reasons", "cash_weight", "signal_close_nav",
                                    "status", "signal_day_adv", "reserved_weight", "active_target_sum", "total_signal_committed_weight"],
               "diagnostics": ["candidate", "date", "code", "ticker", "signal_date", "decision_id"],
               "operational_actions": ["candidate", "decision_id", "order_id", "signal_date", "ticker", "reason", "known_at", "source_id"],
               "execution_results": ["candidate", "decision_id", "order_id", "signal_date", "execution_date", "ticker", "status", "reason"]}
    for key, columns in minimum.items():
        if frames_out[key].empty:
            frames_out[key] = pd.DataFrame(columns=columns)
    intervals, start = [], None
    daily = frames_out["daily"]
    for j in range(len(daily)+1):
        bad = j < len(daily) and daily.iloc[j].valuation_status != "certified"
        if bad and start is None:
            start = j
        if not bad and start is not None:
            part = daily.iloc[start:j]
            intervals.append(dict(start_date=part.iloc[0].date, end_date=part.iloc[-1].date,
                day_count=len(part), stale_days=int(part.stale_count.gt(0).sum()), unknown_days=int(part.unknown_count.gt(0).sum()), resolved=j<len(daily)))
            start = None
    metadata = dict(version="HOLDING_AWARE_EXECUTION_V2", unit="price-index units; shares alias is not raw shares",
        decision_clock="signal close; reserved capital/slots fixed without next-session quotes",
        order_assumption="explicit active targets sized on next-open marked NAV; no-decision holdings preserve units",
        missing_decision_policy="preserve held units, capital and slots", price_quality_gate="warning flags prohibit consuming that date's open/close",
        signal_asof_default="session-date close label; wall-clock evidence requires explicit signal_asof mapping",
        max_positions=max_positions, max_target_weight=max_weight, max_target_invested=max_invested,
        initial_cash=initial_cash, initial_positions=dict(initial_positions or {}), cost_bps_one_way=cost_bps,
        capacity_fraction=capacity_fraction, capacity_on_sells=capacity_on_sells,
        terminal_liquidation=False, shareholder_total_return_certified=False,
        signal_start=str(lo.date()), signal_end=str(hi.date()),
        raw_output_scope="model_decisions always saved exactly including explicit zeros; extra raw scores only when supplied",
        known_limit="fixed-unit reservation weights can drift; unknown NAV creates no investable budget")
    return ReplayResult(**frames_out, metadata=metadata,
        valuation_intervals=pd.DataFrame(intervals, columns=["start_date", "end_date", "day_count", "stale_days", "unknown_days", "resolved"]))


replay = run_replay
