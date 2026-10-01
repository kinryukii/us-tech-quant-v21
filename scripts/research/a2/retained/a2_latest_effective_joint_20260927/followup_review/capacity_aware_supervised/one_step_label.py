"""One-step full-account counterfactual label; never a replay/account engine.

This computes a *single* already-fixed target from an observed close account
state.  It is checked trade-for-trade against engine.run_replay before any fit.
The durable behavior and evaluation trajectories use the original engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np


FEE = .001
BUY_CAPACITY = .01
TOL = 1e-10


@dataclass(frozen=True)
class CloseState:
    cash: float
    nav: float
    units: dict[str, float]


@dataclass(frozen=True)
class OneStep:
    pretrade_nav: float
    posttrade_nav: float
    following_open_nav: float
    cash: float
    units: dict[str, float]
    trades: tuple[dict, ...]
    buy_cash_scale: float
    blocked_buys: int
    capacity_limited_buys: int


class UnknownMark(ValueError):
    pass


def positive(value: object) -> bool:
    try:
        return bool(np.isfinite(float(value)) and float(value) > 0)
    except (TypeError, ValueError):
        return False


def settle(
    state: CloseState,
    targets: Mapping[str, float],
    next_open: Mapping[str, float],
    following_open: Mapping[str, float],
    signal_adv: Mapping[str, float],
    eligible: Mapping[str, bool],
    *,
    clipped_following_return: bool = False,
) -> OneStep:
    """Exactly mirror engine's known-price sell/cap/cash order for one signal.

    Unknown opens for *existing* positions make the full-account label unknown.
    Missing new-buy opens merely block that purchase, as in the engine.
    """
    if not positive(state.nav) or not np.isfinite(state.cash) or state.cash < 0:
        raise ValueError("INVALID_SIGNAL_CLOSE_ACCOUNT")
    units = {str(t): float(q) for t, q in state.units.items() if q > TOL}
    if any(not positive(next_open.get(t, np.nan)) for t in units):
        raise UnknownMark("UNKNOWN_EXISTING_POSITION_NEXT_OPEN")
    cash = float(state.cash)
    opening_marks = {t: float(next_open[t]) for t in units}
    pretrade_nav = cash + sum(q * opening_marks[t] for t, q in units.items())
    if not positive(pretrade_nav):
        raise UnknownMark("UNKNOWN_PRETRADE_NAV")
    wanted = {str(t): float(w) * pretrade_nav for t, w in targets.items()}
    trades: list[dict] = []
    limited = blocked = 0

    # Original engine settles all sales first, with no sell capacity limit.
    for ticker in sorted(units):
        prior_units = units[ticker]
        current = prior_units * opening_marks[ticker]
        requested = max(0., current - wanted.get(ticker, 0.))
        if requested <= TOL:
            continue
        price = opening_marks[ticker]
        quantity = min(prior_units, requested / price)
        notional = quantity * price
        after = prior_units - quantity
        if after <= TOL:
            units.pop(ticker)
            after = 0.
        else:
            units[ticker] = after
        fee = notional * FEE
        cash += notional - fee
        trades.append(dict(ticker=ticker, side="SELL", notional=notional,
                           index_units=quantity, transaction_cost=fee,
                           index_units_before=prior_units, index_units_after=after))

    # Preserve engine's order and reserve live name slots before cash scaling.
    requests: dict[str, float] = {}
    reserved_names = set(units)
    for ticker in sorted(targets, key=lambda t: (-targets[t], t)):
        current = units.get(ticker, 0.) * opening_marks.get(ticker, 0.)
        requested = max(0., wanted[ticker] - current)
        if requested <= TOL:
            continue
        if not eligible.get(ticker, False):
            blocked += 1
            continue
        price = next_open.get(ticker, np.nan)
        if not positive(price):
            blocked += 1
            continue
        if ticker not in reserved_names and len(reserved_names) >= 20:
            blocked += 1
            continue
        adv = signal_adv.get(ticker, np.nan)
        if not positive(adv):
            blocked += 1
            continue
        limit = BUY_CAPACITY * float(adv)
        if requested > limit + TOL:
            limited += 1
        notional = min(requested, limit)
        if notional > TOL:
            requests[ticker] = notional
            reserved_names.add(ticker)
    requirement = sum(requests.values()) * (1. + FEE)
    buy_scale = min(1., max(0., cash) / requirement) if requirement > 0 else 1.
    for ticker, requested in requests.items():
        notional = requested * buy_scale
        if notional <= TOL:
            continue
        price = float(next_open[ticker])
        quantity = notional / price
        prior_units = units.get(ticker, 0.)
        after = prior_units + quantity
        units[ticker] = after
        opening_marks[ticker] = price
        fee = notional * FEE
        cash -= notional + fee
        trades.append(dict(ticker=ticker, side="BUY", notional=notional,
                           index_units=quantity, transaction_cost=fee,
                           index_units_before=prior_units, index_units_after=after))
    if cash < -max(TOL, state.nav * 1e-12):
        raise AssertionError("NEGATIVE_CASH")
    cash = max(0., cash)
    posttrade_nav = cash + sum(q * opening_marks[t] for t, q in units.items())
    if any(not positive(following_open.get(t, np.nan)) for t in units):
        raise UnknownMark("UNKNOWN_EXISTING_POSITION_FOLLOWING_OPEN")
    if clipped_following_return:
        future_values = {
            t: opening_marks[t] * (1. + np.clip(float(following_open[t]) / opening_marks[t] - 1., -.20, .20))
            for t in units
        }
    else:
        future_values = {t: float(following_open[t]) for t in units}
    following_nav = cash + sum(q * future_values[t] for t, q in units.items())
    return OneStep(pretrade_nav=pretrade_nav, posttrade_nav=posttrade_nav,
                   following_open_nav=following_nav, cash=cash, units=units,
                   trades=tuple(trades), buy_cash_scale=buy_scale,
                   blocked_buys=blocked, capacity_limited_buys=limited)
