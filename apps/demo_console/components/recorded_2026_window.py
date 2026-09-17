"""Pure display windows over verified 2026 records; no reads or new evaluation.

Calendar bounds select every recorded point in that interval. They neither
assert a trading calendar nor manufacture observations on holidays or gaps.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isclose, isfinite

from apps.demo_console.adapters.recorded_2026_reader import (
    Recorded2026History, Recorded2026Point,
)

_ARMS = ("A", "A2", "QQQ")


@dataclass(frozen=True)
class Recorded2026WindowSeries:
    key: str
    total_return: float
    maximum_drawdown: float
    worst_day: float | None
    best_day: float | None
    final_equity: float
    positive_day_pct: float | None


@dataclass(frozen=True)
class Recorded2026Window:
    source: Recorded2026History
    requested_start: str
    requested_end: str
    points: tuple[Recorded2026Point, ...] = ()
    series: tuple[Recorded2026WindowSeries, ...] = ()
    start_date: str | None = None
    end_date: str | None = None
    baseline_date: str | None = None
    baseline_is_archive_start: bool = False
    return_observations: int = 0
    status: str = "empty"
    error: str | None = None


def _iso(value):
    return isinstance(value, str) and date.fromisoformat(value).isoformat() == value


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError("Invalid recorded number")
    return float(value)


def slice_recorded_2026(history: Recorded2026History, start_date: str,
                        end_date: str) -> Recorded2026Window:
    """Rebase an inclusive calendar selection without changing its source.

    A cropped window uses the immediately preceding *recorded* equity as 100,
    so the first selected return and any initial drawdown remain included.
    When selecting the archive's first point, that point remains the starting
    mark and is excluded from daily-return statistics. Source status, hashes
    and full-history metrics remain accessible only through ``window.source``.
    """
    def unavailable(message, status="invalid"):
        return Recorded2026Window(history, start_date, end_date, status=status, error=message)

    try:
        if not _iso(start_date) or not _iso(end_date) or start_date > end_date:
            raise ValueError("Invalid date interval")
    except (TypeError, ValueError):
        return unavailable("Choose a valid start and end date in chronological order.")
    if history.error:
        return unavailable(history.error)
    if not history.points:
        return unavailable("No verified 2026 observations are available.", "empty")
    try:
        dates = tuple(point.date for point in history.points)
        if (not all(_iso(day) and "2026-01-01" <= day <= "2026-12-31" for day in dates)
                or dates != tuple(sorted(set(dates)))
                or (history.start_date is not None and history.start_date != dates[0])
                or (history.end_date is not None and history.end_date != dates[-1])):
            raise ValueError("Invalid recorded chronology")
        indices = tuple(index for index, day in enumerate(dates) if start_date <= day <= end_date)
        if not indices:
            return unavailable("No recorded observations fall within the selected dates.", "empty")
        first, last = indices[0], indices[-1]
        anchor = history.points[first - 1 if first else 0]
        baselines = {arm: _number(getattr(anchor, f"{arm.lower()}_equity")) for arm in _ARMS}
        if any(value <= 0 for value in baselines.values()):
            raise ValueError("Invalid recorded baseline")
        if not first and any(not isclose(value, 100.0, rel_tol=1e-10, abs_tol=1e-12)
                             for value in baselines.values()):
            raise ValueError("Invalid archive starting mark")
        peaks = dict.fromkeys(_ARMS, 100.0)
        points = []
        for original in history.points[first:last + 1]:
            equities, returns, drawdowns = [], [], []
            for arm in _ARMS:
                prefix = arm.lower()
                original_equity = _number(getattr(original, f"{prefix}_equity"))
                change = _number(getattr(original, f"{prefix}_return"))
                recorded_drawdown = _number(getattr(original, f"{prefix}_drawdown"))
                equity = _number(original_equity * (100.0 / baselines[arm]))
                if (original_equity <= 0 or equity <= 0 or change <= -1
                        or not -1 < recorded_drawdown <= 0):
                    raise ValueError("Invalid recorded equity or return")
                if (not first and original is history.points[0]
                        and not isclose(change, 0.0, rel_tol=1e-10, abs_tol=1e-12)):
                    raise ValueError("The initial archive point must be a baseline")
                peaks[arm] = max(peaks[arm], equity)
                equities.append(equity)
                returns.append(change)
                drawdowns.append(equity / peaks[arm] - 1)
            points.append(Recorded2026Point(original.date, *equities, *returns, *drawdowns))
        if not first:
            # An archive prefix has the original baseline and running peaks.
            # Retain even source rounding; only a cropped start needs new values.
            points = list(history.points[:last + 1])
        return_points = points if first else points[1:]
        series = []
        for arm in _ARMS:
            prefix = arm.lower()
            returns = [getattr(point, f"{prefix}_return") for point in return_points]
            final_equity = getattr(points[-1], f"{prefix}_equity")
            series.append(Recorded2026WindowSeries(
                key=arm, total_return=final_equity / 100.0 - 1,
                maximum_drawdown=min(getattr(point, f"{prefix}_drawdown") for point in points),
                worst_day=min(returns) if returns else None,
                best_day=max(returns) if returns else None,
                final_equity=final_equity,
                positive_day_pct=sum(value > 0 for value in returns) / len(returns) if returns else None,
            ))
        originals = {series.key: series for series in history.series}
        if (first == 0 and last == len(history.points) - 1 and return_points
                and len(history.series) == 3 and set(originals) == set(_ARMS)):
            series = [Recorded2026WindowSeries(arm, *(
                _number(getattr(originals[arm], field)) for field in (
                    "total_return", "maximum_drawdown", "worst_day", "best_day",
                    "final_equity", "positive_day_pct"))) for arm in _ARMS]
        return Recorded2026Window(history, start_date, end_date, tuple(points), tuple(series),
            points[0].date, points[-1].date, anchor.date, first == 0, len(return_points), "available")
    except (AttributeError, ArithmeticError, TypeError, ValueError):
        return unavailable("The selected window cannot be displayed because its recorded dates or values are invalid.")
