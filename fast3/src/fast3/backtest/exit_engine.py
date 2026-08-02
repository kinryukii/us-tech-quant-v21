"""Conservative OHLC exit engine for the frozen FAST3-002 contract."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import pandas as pd

from .cost_model import RoundTripCost


@dataclass(frozen=True)
class ExitResult:
    exit_timestamp_et: object
    exit_timestamp_utc: object
    exit_price: float
    exit_reason: str
    gross_return: float
    entry_cost: float
    exit_cost: float
    total_cost: float
    net_return: float
    mfe: float
    mae: float
    holding_minutes: float
    target_hit: bool
    stop_hit: bool
    exit_ambiguity: bool

    def as_dict(self) -> dict:
        return asdict(self)


def _valid(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x["timestamp_et"] = pd.to_datetime(x["timestamp_et"], errors="raise")
    x["timestamp_utc"] = pd.to_datetime(x["timestamp_utc"], utc=True, errors="raise")
    x = x.sort_values("timestamp_utc", kind="mergesort")
    good = (x[["open", "high", "low", "close"]] > 0).all(axis=1)
    good &= x["high"] >= x[["open", "low", "close"]].max(axis=1)
    good &= x["low"] <= x[["open", "high", "close"]].min(axis=1)
    return x.loc[good].reset_index(drop=True)


def evaluate_exit(*, bars: pd.DataFrame, entry_timestamp_et, entry_price: float,
                  max_holding_minutes: int, target_net_return: float,
                  stop_gross_return: float, cost: RoundTripCost,
                  force_exit_sessions: tuple[str, ...] = ()) -> ExitResult:
    """Exit on real ETF OHLC. Same-bar target/stop is frozen stop-first."""
    x = _valid(bars)
    entry_ts = pd.Timestamp(entry_timestamp_et)
    path = x[x.timestamp_et >= entry_ts].copy()
    if path.empty:
        raise ValueError("NO_EXECUTABLE_EXIT_BAR")
    deadline = entry_ts + pd.Timedelta(minutes=max_holding_minutes)
    target_gross = (1.0 + target_net_return) * (1.0 + cost.total_cost) - 1.0
    target_price, stop_price = entry_price * (1.0 + target_gross), entry_price * (1.0 + stop_gross_return)
    seen = path[path.timestamp_et <= deadline]
    if seen.empty:
        seen = path.iloc[:1]
    mfe = float(seen.high.max() / entry_price - 1.0)
    mae = float(seen.low.min() / entry_price - 1.0)
    chosen = None
    for row in seen.itertuples(index=False):
        target, stop = row.high >= target_price, row.low <= stop_price
        forced = str(getattr(row, "session", "")) in force_exit_sessions
        if target or stop:
            # OHLC cannot establish order: a collision is always treated as stop.
            price = stop_price if stop else target_price
            chosen = (row, price, "STOP" if stop else "TARGET", bool(target and stop), bool(target), bool(stop))
            break
        if forced:
            chosen = (row, float(row.open), "SESSION_FORCED", False, False, False)
            break
    if chosen is None:
        timeout = path[path.timestamp_et >= deadline]
        if not timeout.empty:
            row = timeout.iloc[0]
            chosen = (row, float(row.open), "TIMEOUT", False, False, False)
        else:
            row = path.iloc[-1]
            chosen = (row, float(row.close), "DATA_END_CLOSE_PROXY", False, False, False)
    row, price, reason, ambiguity, target_hit, stop_hit = chosen
    gross = float(price / entry_price - 1.0)
    return ExitResult(
        exit_timestamp_et=row.timestamp_et, exit_timestamp_utc=row.timestamp_utc,
        exit_price=float(price), exit_reason=reason, gross_return=gross,
        entry_cost=cost.entry_cost, exit_cost=cost.exit_cost, total_cost=cost.total_cost,
        net_return=cost.net_return(gross), mfe=mfe, mae=mae,
        holding_minutes=float((pd.Timestamp(row.timestamp_et) - entry_ts).total_seconds() / 60.0),
        target_hit=target_hit, stop_hit=stop_hit, exit_ambiguity=ambiguity,
    )
