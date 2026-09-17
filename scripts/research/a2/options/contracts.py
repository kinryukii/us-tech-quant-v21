"""Immutable R1 inputs: decision information is separate from future labels."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from math import isfinite

import exchange_calendars as xcals
import pandas as pd

TEMPLATE = "OPTIONS_EXPRESSION_PILOT_R1"
CUTOFF = pd.Timestamp("2026-01-01", tz="America/New_York")
GRADES = {"REAL_HISTORICAL_QUOTES", "INDICATIVE_OR_AGGREGATE", "MODEL_SCENARIO", "SYNTHETIC"}


class Invalid(ValueError):
    """A localized data/contract rejection, never silent imputation."""


def require(value: bool, reason: str) -> None:
    if not value:
        raise Invalid(reason)


def finite(value: float, *, positive: bool = False) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and (value > 0 if positive else value >= 0)


def ts(value: str | datetime | pd.Timestamp) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    require(not pd.isna(stamp) and stamp.tzinfo is not None, "TIMEZONE_REQUIRED")
    return stamp.tz_convert("UTC")


def pre2026(value: str | datetime | pd.Timestamp) -> pd.Timestamp:
    stamp = ts(value)
    require(stamp < CUTOFF, "ECONOMIC_TIME_NOT_PRE2026")
    return stamp


@lru_cache(maxsize=1)
def calendar():
    # Calendar rules are non-economic metadata; only contract cutoffs may use 2026.
    return xcals.get_calendar("XNYS", start="2000-01-01", end="2026-12-31")


def clock(day: str, offset: int = 0) -> pd.Timestamp:
    cal = calendar()
    try:
        base = cal.sessions.get_loc(pd.Timestamp(day))
        target = cal.sessions[base + offset]
    except (KeyError, IndexError) as exc:
        raise Invalid("SESSION_UNAVAILABLE") from exc
    require(offset >= 0, "NEGATIVE_SESSION_OFFSET")
    return pre2026(pd.Timestamp(str(target.date()) + " 09:45", tz="America/New_York"))


@lru_cache(maxsize=512)
def session_bounds(day: str) -> tuple:
    if pd.Timestamp(day) not in calendar().sessions:
        return (None, None)
    row = calendar().schedule.loc[day]
    return row["open"], row["close"]


def in_session(value: str | datetime | pd.Timestamp, *, economic: bool = True) -> bool:
    stamp = pre2026(value) if economic else ts(value)
    day = stamp.tz_convert("America/New_York").date().isoformat()
    opened, closed = session_bounds(day)
    return bool(opened is not None and opened <= stamp <= closed)


@dataclass(frozen=True)
class Opportunity:
    decision_id: str
    underlying_uid: str
    signal_available_at: str
    decision_at: str
    feature_available_at: str
    source_id: str
    rank: int
    score: float
    train_cutoff: str
    fold: str
    spot: float
    spot_at: str
    evidence_grade: str = "SYNTHETIC"
    capital: float = 10000.0
    oof_profile: str | None = None


@dataclass(frozen=True)
class Contract:
    contract_id: str
    underlying_uid: str
    strike: float
    expiry: str
    last_trade_at: str
    available_at: str
    right: str = "CALL"
    multiplier: int = 100
    deliverable: str = "100_UNDERLYING_SHARES"
    exercise_style: str = "AMERICAN"
    settlement_type: str = "PHYSICAL"
    adjustment_status: str = "STANDARD"
    currency: str = "USD"
    source: str = "SYNTHETIC"
    version: str = "1"


@dataclass(frozen=True)
class Quote:
    instrument_id: str
    underlying_uid: str
    event_at: str
    available_at: str
    ingested_at: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    underlying_price: float
    underlying_at: str
    evidence_grade: str = "SYNTHETIC"
    feed_kind: str = "SYNTHETIC"
    quote_kind: str = "BBO"
    size_unit: str = "CONTRACTS"
    currency: str = "USD"
    source: str = "SYNTHETIC"
    version: str = "1"
    delta: float | None = None
    delta_at: str | None = None
    delta_source: str | None = None
    delta_kind: str | None = None
    delta_unit: str | None = None
    delta_style: str | None = None
    iv: float | None = None


@dataclass(frozen=True)
class Mark:
    underlying_uid: str
    event_at: str
    available_at: str
    price: float
    source: str = "SYNTHETIC"
    evidence_grade: str = "SYNTHETIC"
    identity_status: str = "VERIFIED"
    action_status: str = "UNCHANGED"


@dataclass(frozen=True)
class LifecycleEvent:
    contract_id: str
    event_at: str
    kind: str


@dataclass(frozen=True)
class Fees:
    option_per_contract: float = .65
    stock_per_share: float = .005
    minimum: float = 1.0
    option_slippage: float = 0.0
    stock_slippage: float = 0.0

    def order(self, quantity: float, option: bool) -> float:
        require(all(finite(v) for v in (self.option_per_contract, self.stock_per_share, self.minimum,
                                      self.option_slippage, self.stock_slippage)), "INVALID_FEES")
        require(finite(quantity), "INVALID_QUANTITY")
        return max(self.minimum, quantity * (self.option_per_contract if option else self.stock_per_share)) if quantity else 0.0


def validate_opportunity(o: Opportunity) -> None:
    decision = pre2026(o.decision_at)
    require(bool(o.decision_id and o.underlying_uid and o.source_id and o.fold), "MISSING_PROVENANCE")
    require(o.evidence_grade in GRADES, "INVALID_EVIDENCE_GRADE")
    require(pre2026(o.signal_available_at) <= decision, "FUTURE_SIGNAL")
    require(pre2026(o.feature_available_at) <= decision, "FUTURE_FEATURE")
    require(pre2026(o.train_cutoff) < decision, "TRAIN_CUTOFF")
    require(isinstance(o.score, (int, float)) and not isinstance(o.score, bool) and isfinite(o.score), "INVALID_SCORE")
    require(type(o.rank) is int and 1 <= o.rank <= 20, "NOT_RAW_TOP20")
    require(finite(o.spot, positive=True) and finite(o.capital, positive=True), "INVALID_BUDGET_OR_SPOT")
    require(timedelta(0) <= decision - pre2026(o.spot_at) <= timedelta(seconds=1), "DECISION_SPOT_CLOCK")
    require(decision == clock(str(decision.tz_convert('America/New_York').date())), "DECISION_CLOCK")
    clock(str(decision.tz_convert('America/New_York').date()), 5)


def validate_quote(q: Quote, uid: str, instrument: str, *, option: bool, grade: str) -> None:
    require(q.instrument_id == instrument and q.underlying_uid == uid, "QUOTE_IDENTITY")
    require(q.currency == "USD" and q.size_unit == ("CONTRACTS" if option else "SHARES"), "QUOTE_UNITS")
    require(q.evidence_grade == grade and grade in {"SYNTHETIC", "REAL_HISTORICAL_QUOTES"}, "NON_EXECUTABLE_EVIDENCE")
    require(q.quote_kind == "BBO" and q.feed_kind in {"SYNTHETIC", "HISTORICAL_BBO"}, "NON_EXECUTABLE_QUOTE")
    if grade == "REAL_HISTORICAL_QUOTES":
        require(q.feed_kind == "HISTORICAL_BBO" and q.source not in {"", "SYNTHETIC"}, "NON_EXECUTABLE_EVIDENCE")
    require(all(finite(v) for v in (q.bid, q.ask, q.bid_size, q.ask_size)), "INVALID_BIDASK")
    require(q.ask >= q.bid and q.ask > 0, "CROSSED_OR_EMPTY_QUOTE")
    require(finite(q.underlying_price, positive=True) and bool(q.source and q.version), "QUOTE_SOURCE")
    event, available = pre2026(q.event_at), pre2026(q.available_at)
    require(timedelta(0) <= available - event <= timedelta(seconds=2), "STALE_OR_DELAYED_QUOTE")
    require(ts(q.ingested_at) >= available, "INGEST_BEFORE_AVAILABLE")
    require(abs(event - pre2026(q.underlying_at)) <= timedelta(seconds=1), "UNDERLYING_CLOCK")
    require(ts(q.underlying_at) <= available, "FUTURE_UNDERLYING_PRICE")
    require(in_session(event) and in_session(available), "OUTSIDE_SESSION")
