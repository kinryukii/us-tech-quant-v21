"""Pure descriptions of recorded returns, without inference or strategy selection.

Returns, drawdowns and shares are fractions; fields ending in ``_pp`` are
percentage-point differences. Costs retain the source's initial-NAV amount
unit. The initial wealth is immediately BEFORE the first recorded return.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import groupby
from math import fsum, isclose, isfinite, log1p, sqrt
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from apps.demo_console.models import PerformancePoint


@dataclass(frozen=True)
class WealthPoint:
    execution_date: str
    net_wealth: float
    gross_wealth: float
    drawdown: float
    reference_net_wealth: float | None
    reference_gross_wealth: float | None


@dataclass(frozen=True)
class PeriodReturn:
    period: str
    start_date: str
    end_date: str
    observations: int
    net_return: float
    gross_return: float
    reference_net_return: float | None
    reference_gross_return: float | None
    net_difference_pp: float | None
    window_partial: bool
    coverage_boundary: bool


@dataclass(frozen=True)
class RollingReturn:
    start_date: str
    end_date: str
    observations: int
    net_return: float
    reference_net_return: float | None


@dataclass(frozen=True)
class RiskComparisonRow:
    series: str
    net_total_return: float
    max_drawdown: float
    worst_daily_net_return: float
    observations: int


@dataclass(frozen=True)
class DrawdownSummary:
    depth: float = 0.0
    peak_date: str | None = None
    trough_date: str | None = None
    recovery_date: str | None = None
    peak_is_initial: bool = False


@dataclass(frozen=True)
class DailyExtreme:
    execution_date: str
    net_return: float


@dataclass(frozen=True)
class PerformanceSummary:
    observations: int = 0
    start_date: str | None = None
    end_date: str | None = None
    initial_wealth: float = 1.0
    wealth: tuple[WealthPoint, ...] = ()
    net_total_return: float | None = None
    gross_total_return: float | None = None
    total_transaction_cost: float | None = None
    gross_net_difference_pp: float | None = None
    reference_available: bool = False
    reference_net_total_return: float | None = None
    reference_gross_total_return: float | None = None
    reference_total_transaction_cost: float | None = None
    net_difference_pp: float | None = None
    max_drawdown: DrawdownSummary = DrawdownSummary()
    months: tuple[PeriodReturn, ...] = ()
    years: tuple[PeriodReturn, ...] = ()
    positive_log_growth: float | None = None
    negative_log_growth: float | None = None
    top5_positive_log_share: float | None = None
    top10_positive_log_share: float | None = None
    best_day: DailyExtreme | None = None
    worst_day: DailyExtreme | None = None
    autocorrelation_lag1: float | None = None
    autocorrelation_lag5: float | None = None


def _number(value: float, label: str, *, minimum: float | None = None) -> float:
    try:
        valid = not isinstance(value, bool) and isfinite(value)
    except TypeError:
        valid = False
    if not valid or (minimum is not None and value < minimum):
        raise ValueError(f"Invalid {label}.")
    return float(value)


def _dates(values: Sequence[str]) -> tuple[str, ...]:
    result = tuple(values)
    try:
        valid = all(date.fromisoformat(value).isoformat() == value for value in result)
    except (ValueError, TypeError):
        valid = False
    if not valid or any(a >= b for a, b in zip(result, result[1:])):
        raise ValueError("Dates must be unique, ascending ISO dates.")
    return result


def _difference_pp(left: float, right: float | None) -> float | None:
    return _number(100.0 * (left - right), "return difference") if right is not None else None


def _path(returns: Sequence[float], initial: float) -> tuple[float, ...]:
    wealth = initial
    values = []
    for value in returns:
        value = _number(value, "return")
        if value <= -1.0:
            raise ValueError("Returns must preserve strictly positive wealth.")
        wealth *= 1.0 + value
        if not isfinite(wealth) or wealth <= 0.0:
            raise ValueError("Compounded wealth is outside the finite positive range.")
        values.append(wealth)
    return tuple(values)


def _drawdowns(dates: tuple[str, ...], values: tuple[float, ...], initial: float):
    peak, peak_index, worst_index, worst_peak = initial, -1, None, -1
    depth, target_peak = 0.0, initial
    drawdowns = []
    for index, value in enumerate(values):
        if value >= peak:
            peak, peak_index = value, index
        drawdown = value / peak - 1.0
        drawdowns.append(drawdown)
        if drawdown < depth:
            depth, worst_index, worst_peak = drawdown, index, peak_index
            target_peak = peak
    if worst_index is None:
        return tuple(drawdowns), DrawdownSummary()
    recovery = next((dates[i] for i in range(worst_index + 1, len(values))
                     if values[i] >= target_peak
                     or isclose(values[i], target_peak, rel_tol=1e-12)), None)
    return tuple(drawdowns), DrawdownSummary(
        depth, dates[worst_peak] if worst_peak >= 0 else None,
        dates[worst_index], recovery, worst_peak == -1,
    )


def _periods(points: tuple[PerformancePoint, ...], calendar: tuple[str, ...],
             size: int, reference: bool) -> tuple[PeriodReturn, ...]:
    available_counts: dict[str, int] = {}
    for value in calendar:
        key = value[:size]
        available_counts[key] = available_counts.get(key, 0) + 1
    boundaries = {calendar[0][:size], calendar[-1][:size]}
    result = []
    for key, group in groupby(points, key=lambda point: point.execution_date[:size]):
        rows = tuple(group)
        net = _path([row.net_return for row in rows], 1.0)[-1] - 1.0
        gross = _path([row.gross_return for row in rows], 1.0)[-1] - 1.0
        ref_net = (_path([row.reference_net_return for row in rows], 1.0)[-1] - 1.0
                   if reference else None)
        ref_gross = (_path([row.reference_gross_return for row in rows], 1.0)[-1] - 1.0
                     if reference else None)
        result.append(PeriodReturn(
            key, rows[0].execution_date, rows[-1].execution_date, len(rows),
            net, gross, ref_net, ref_gross,
            _difference_pp(net, ref_net),
            len(rows) < available_counts[key], key in boundaries,
        ))
    return tuple(result)


def _autocorrelation(values: tuple[float, ...], lag: int) -> float | None:
    # Twenty paired observations is a display guard, not a significance claim.
    if len(values) - lag < 20:
        return None
    left, right = values[:-lag], values[lag:]
    # Detect constant inputs before rounding in the mean can create a tiny,
    # identical residual at every position and falsely imply correlation 1.
    if min(left) == max(left) or min(right) == max(right):
        return None
    mean_left, mean_right = fsum(left) / len(left), fsum(right) / len(right)
    x = tuple(value - mean_left for value in left)
    y = tuple(value - mean_right for value in right)
    xx, yy = fsum(value * value for value in x), fsum(value * value for value in y)
    if xx == 0.0 or yy == 0.0:
        return None
    correlation = fsum(a * b for a, b in zip(x, y)) / sqrt(xx * yy)
    return max(-1.0, min(1.0, correlation))


def summarize_performance(
    points: Sequence[PerformancePoint], *, initial_wealth: float = 1.0,
    full_history_dates: Sequence[str] | None = None,
) -> PerformanceSummary:
    """Summarize one contiguous recorded window without reading any files.

    ``full_history_dates`` is the complete recorded calendar, not an inferred
    exchange calendar. A period is ``window_partial`` only when the selection
    excludes a known recorded date in that period. ``coverage_boundary`` marks
    periods touching the source calendar's endpoints; it does not assert they
    are incomplete. Without a supplied calendar, only input coverage is known.

    Reference data must include all four optional reference fields on every
    point or none anywhere. The reference is a research control, not a market
    benchmark. Invalid observations are rejected, never skipped or filled.
    Source NAVs are not rebased: paths independently compound the recorded
    returns from the explicit pre-first-return wealth, including day-one costs.
    """
    initial = _number(initial_wealth, "initial wealth")
    if initial <= 0.0:
        raise ValueError("Initial wealth must be positive.")
    rows = tuple(points)
    dates = _dates([row.execution_date for row in rows])
    calendar = _dates(full_history_dates) if full_history_dates is not None else dates
    if not rows:
        return PerformanceSummary(initial_wealth=initial)
    if not set(dates).issubset(calendar):
        raise ValueError("Window dates must belong to the recorded calendar.")
    if calendar[calendar.index(dates[0]):calendar.index(dates[-1]) + 1] != dates:
        raise ValueError("Window must not omit an interior recorded observation.")
    reference_fields = ("reference_nav", "reference_net_return",
                        "reference_gross_return", "reference_transaction_cost")
    reference_values = tuple(getattr(row, field) for row in rows for field in reference_fields)
    reference = any(value is not None for value in reference_values)
    if reference and any(value is None for value in reference_values):
        raise ValueError("Reference coverage must be complete on every window date.")
    costs = tuple(_number(row.transaction_cost, "transaction cost", minimum=0.0) for row in rows)
    net_returns = tuple(row.net_return for row in rows)
    net = _path(net_returns, initial)
    gross = _path([row.gross_return for row in rows], initial)
    ref_net = _path([row.reference_net_return for row in rows], initial) if reference else ()
    ref_gross = _path([row.reference_gross_return for row in rows], initial) if reference else ()
    ref_cost = (fsum(_number(row.reference_transaction_cost, "reference cost", minimum=0.0)
                     for row in rows) if reference else None)
    if reference:
        for row in rows:
            if _number(row.reference_nav, "reference NAV") <= 0.0:
                raise ValueError("Reference NAV must be positive.")
    drawdowns, deepest = _drawdowns(dates, net, initial)
    logs = tuple(log1p(value) for value in net_returns)
    positive = sorted((value for value in logs if value > 0.0), reverse=True)
    positive_total = fsum(positive)
    net_total = _number(net[-1] / initial - 1.0, "total net return")
    gross_total = _number(gross[-1] / initial - 1.0, "total gross return")
    reference_net_total = (_number(ref_net[-1] / initial - 1.0, "reference total return")
                           if reference else None)
    best = max(rows, key=lambda row: row.net_return)
    worst = min(rows, key=lambda row: row.net_return)
    return PerformanceSummary(
        observations=len(rows), start_date=dates[0], end_date=dates[-1], initial_wealth=initial,
        wealth=tuple(WealthPoint(day, net[i], gross[i], drawdowns[i],
                                ref_net[i] if reference else None,
                                ref_gross[i] if reference else None)
                     for i, day in enumerate(dates)),
        net_total_return=net_total, gross_total_return=gross_total,
        total_transaction_cost=fsum(costs),
        gross_net_difference_pp=_difference_pp(gross_total, net_total),
        reference_available=reference, reference_net_total_return=reference_net_total,
        reference_gross_total_return=(_number(ref_gross[-1] / initial - 1.0, "reference gross return")
                                      if reference else None),
        reference_total_transaction_cost=ref_cost,
        net_difference_pp=_difference_pp(net_total, reference_net_total),
        max_drawdown=deepest, months=_periods(rows, calendar, 7, reference),
        years=_periods(rows, calendar, 4, reference), positive_log_growth=positive_total,
        negative_log_growth=fsum(value for value in logs if value < 0.0),
        top5_positive_log_share=fsum(positive[:5]) / positive_total if positive_total else None,
        top10_positive_log_share=fsum(positive[:10]) / positive_total if positive_total else None,
        best_day=DailyExtreme(best.execution_date, best.net_return),
        worst_day=DailyExtreme(worst.execution_date, worst.net_return),
        autocorrelation_lag1=_autocorrelation(net_returns, 1),
        autocorrelation_lag5=_autocorrelation(net_returns, 5),
    )


def rolling_returns(summary: PerformanceSummary, span: int = 63) -> tuple[RollingReturn, ...]:
    """Describe complete rolling windows inside this already selected summary.

    The first window starts before its first included return, so entry costs
    remain included. Later windows use the immediately preceding wealth as
    their baseline. No history outside ``summary.wealth`` fills earlier points.
    Adjacent windows overlap; these are descriptions, not independent trials.
    """
    if isinstance(span, bool) or not isinstance(span, int) or span <= 0:
        raise ValueError("Rolling span must be a positive integer.")
    wealth = summary.wealth
    if len(wealth) < span:
        return ()

    def growth(value, baseline):
        value = _number(value, "rolling wealth")
        baseline = _number(baseline, "rolling baseline")
        if value <= 0 or baseline <= 0:
            raise ValueError("Rolling wealth and baseline must be positive.")
        return _number(value / baseline - 1.0, "rolling return")

    result = []
    for end in range(span - 1, len(wealth)):
        start = end - span + 1
        preceding = wealth[start - 1] if start else None
        net_base = preceding.net_wealth if preceding else summary.initial_wealth
        reference = None
        if summary.reference_available:
            reference_base = (preceding.reference_net_wealth if preceding else summary.initial_wealth)
            reference = growth(wealth[end].reference_net_wealth, reference_base)
        result.append(RollingReturn(
            wealth[start].execution_date, wealth[end].execution_date, span,
            growth(wealth[end].net_wealth, net_base), reference,
        ))
    return tuple(result)


def matched_risk_comparison(summary: PerformanceSummary) -> tuple[RiskComparisonRow, ...]:
    """Describe each net path over the same selected execution observations.

    Both paths are normalized to 1 before their first return, including that
    day's costs. Daily returns come from successive verified net wealth values.
    A missing or incomplete reference produces only the A2 row, never a shorter
    reference period. These risk descriptions are not estimates of alpha.
    """
    if not summary.wealth:
        return ()
    initial = _number(summary.initial_wealth, "initial wealth")
    if initial <= 0:
        raise ValueError("Initial wealth must be positive.")
    dates = tuple(point.execution_date for point in summary.wealth)

    def describe(series, values):
        path = tuple(_number(_number(value, "net wealth") / initial, "normalized net wealth")
                     for value in values)
        if any(value <= 0 for value in path):
            raise ValueError("Net wealth must be positive.")
        daily = tuple(_number(value / previous - 1.0, "daily net return")
                      for previous, value in zip((1.0, *path[:-1]), path))
        _, drawdown = _drawdowns(dates, path, 1.0)
        return RiskComparisonRow(series, path[-1] - 1.0, drawdown.depth, min(daily), len(path))

    result = [describe("Raw A2", (point.net_wealth for point in summary.wealth))]
    if summary.reference_available:
        try:
            reference = describe("Frozen A control", (point.reference_net_wealth for point in summary.wealth))
        except ValueError:
            pass  # Preserve A2 when a reference path is unavailable or incomplete.
        else:
            result.append(reference)
    return tuple(result)
