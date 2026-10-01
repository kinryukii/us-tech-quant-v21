"""Pure descriptions of recorded returns, without inference or strategy selection.

Returns, drawdowns and shares are fractions; fields ending in ``_pp`` are
percentage-point differences. Costs retain the source's initial-NAV amount
unit. The initial wealth is immediately BEFORE the first recorded return.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import groupby
from math import expm1, fsum, isclose, isfinite, log, log1p, sqrt
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
    annualized_sharpe: float | None = None


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


def annualized_sharpe(returns) -> float | None:
    """Descriptive sqrt(252)*mean/sample SD, daily risk-free return zero."""
    values=tuple(_number(value,'Sharpe daily return') for value in returns)
    if len(values)<2:return None
    mean=fsum(values)/len(values)
    variance=fsum((value-mean)**2 for value in values)/(len(values)-1)
    if variance<=0:return None
    return sqrt(252)*mean/sqrt(variance)


def summarize_nav_window(daily, start, end):
    """Describe a recorded NAV window, retaining its real preceding NAV.

    Daily risk ratios use 252 observations/year, sample SD and zero risk-free
    return. Sortino uses a zero daily target and all observations in its lower
    partial second moment. Optional execution fields never become zero by default.
    """
    daily = tuple(daily)
    _dates(tuple(point["date"] for point in daily))
    indexes = [i for i, point in enumerate(daily) if start <= point["date"] <= end]
    if not indexes:
        return None
    first = indexes[0]
    baseline = _number(daily[first - 1]["nav"] if first else 1.0, "window baseline", minimum=0)
    if baseline <= 0:
        raise ValueError("Window baseline must be positive.")
    rows = []
    for index in indexes:
        point = daily[index]
        nav = _number(point["nav"], "recorded NAV", minimum=0)
        previous = _number(daily[index - 1]["nav"] if index else 1.0, "previous NAV", minimum=0)
        cash = _number(point["cash_weight"], "cash weight", minimum=0)
        if nav <= 0 or previous <= 0 or cash > 1:
            raise ValueError("NAV must be positive and cash weight within [0, 1].")
        net = nav / previous - 1.0
        if point.get("net_return") is not None and not isclose(
                _number(point["net_return"], "recorded return"), net, rel_tol=1e-8, abs_tol=1e-10):
            raise ValueError("Recorded daily return does not match NAV.")
        rows.append({**point, "execution_date": point["date"], "value": nav / baseline,
                     "nav": nav, "net_return": net, "cash_weight": cash})
    dates = tuple(row["execution_date"] for row in rows)
    values = tuple(row["value"] for row in rows)
    drawdowns, drawdown = _drawdowns(dates, values, 1.0)
    for row, depth in zip(rows, drawdowns):
        row["drawdown"] = depth
    returns = tuple(row["net_return"] for row in rows)
    count, mean = len(rows), fsum(returns) / len(rows)
    volatility = sqrt(fsum((r - mean) ** 2 for r in returns) / (count - 1)) * sqrt(252) if count > 1 else None
    downside = sqrt(fsum(min(r, 0.0) ** 2 for r in returns) / count)
    try:
        annual_return = expm1(log(values[-1]) * 252 / count)
    except OverflowError:
        annual_return = None
    if annual_return is not None and not isfinite(annual_return):
        annual_return = None
    longest, current = 0, 0
    for depth in drawdowns:
        current = current + 1 if depth < -1e-12 else 0
        longest = max(longest, current)
    peak_index = dates.index(drawdown.peak_date) if drawdown.peak_date else -1
    recovery_days = (dates.index(drawdown.recovery_date) - peak_index if drawdown.recovery_date else None)
    months = []
    archive_months = (daily[0]["date"][:7], daily[-1]["date"][:7])
    for month, group in groupby(rows, key=lambda row: row["execution_date"][:7]):
        part = tuple(group)
        available_count = sum(point["date"][:7] == month for point in daily)
        months.append({"period": month, "start": part[0]["execution_date"], "end": part[-1]["execution_date"],
                       "days": len(part), "return": _path(tuple(row["net_return"] for row in part), 1.0)[-1] - 1,
                       "partial": len(part) != available_count or month in archive_months})
    def complete(field):
        return all(row.get(field) is not None for row in rows)
    gross = (_path(tuple(_number(row["gross_return"], "gross return") for row in rows), 1.0)[-1] - 1
             if complete("gross_return") else None)
    fees = fsum(_number(row["transaction_cost_amount"], "fee", minimum=0) for row in rows) / baseline if complete("transaction_cost_amount") else None
    turnover = fsum(_number(row["turnover"], "turnover", minimum=0) for row in rows) if complete("turnover") else None
    cash = fsum(row["cash_weight"] for row in rows) / count
    return {"rows": rows, "start": dates[0], "end": dates[-1], "days": count,
            "end_nav": values[-1], "cumulative_return": values[-1] - 1,
            "max_drawdown": drawdown.depth, "peak_date": drawdown.peak_date,
            "trough_date": drawdown.trough_date, "recovery_date": drawdown.recovery_date,
            "recovery_days": recovery_days, "longest_underwater_days": longest,
            "mean_cash": cash, "mean_exposure": 1 - cash, "end_cash": rows[-1]["cash_weight"],
            "worst_return": min(returns), "best_return": max(returns),
            "positive_day_fraction": sum(r > 0 for r in returns) / count,
            "sharpe": annualized_sharpe(returns), "annualized_return": annual_return,
            "annualized_volatility": volatility,
            "sortino": sqrt(252) * mean / downside if downside > 0 and count > 1 else None,
            "calmar": annual_return / abs(drawdown.depth) if drawdown.depth < 0 and annual_return is not None else None,
            "gross_return": gross, "cost_fraction": fees,
            "gross_net_difference_pp": 100 * (gross - (values[-1] - 1)) if gross is not None else None,
            "turnover": turnover, "mean_turnover": turnover / count if turnover is not None else None,
            "best_month_return": max(month["return"] for month in months),
            "worst_month_return": min(month["return"] for month in months),
            **{field: sum(row[field] for row in rows) if complete(field) else None for field in
               ("skipped_buy_count","blocked_sell_count","stale_mark_count")},
            "months": months, "positive_month_fraction": sum(month["return"] > 0 for month in months) / len(months),
            "mean_holding_count": fsum(row["holding_count"] for row in rows) / count if complete("holding_count") else None}


def matched_risk_comparison(summary: PerformanceSummary, *, skip_initial_cash_baseline=False) -> tuple[RiskComparisonRow, ...]:
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
        return RiskComparisonRow(series, path[-1] - 1.0, drawdown.depth, min(daily), len(path),
                                 annualized_sharpe(daily[1:] if skip_initial_cash_baseline else daily))

    result = [describe("Raw A2", (point.net_wealth for point in summary.wealth))]
    if summary.reference_available:
        try:
            reference = describe("Frozen A control", (point.reference_net_wealth for point in summary.wealth))
        except ValueError:
            pass  # Preserve A2 when a reference path is unavailable or incomplete.
        else:
            result.append(reference)
    return tuple(result)
