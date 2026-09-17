"""Synthetic display-window accounting without any artifact or market reads."""
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path

import pytest

from apps.demo_console.adapters.recorded_2026_reader import (
    Recorded2026History, Recorded2026Point, Recorded2026Series,
)
from apps.demo_console.components.recorded_2026_window import slice_recorded_2026


def _history():
    dates = ("2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08")
    paths = ((100., 100., 100.), (110., 120., 98.), (99., 90., 97.),
             (103.95, 99., 99.91), (103.95, 94.05, 98.9109))
    points, peaks, previous = [], [100.] * 3, [100.] * 3
    for day, equities in zip(dates, paths):
        returns = tuple(value / prior - 1 for value, prior in zip(equities, previous))
        peaks = [max(peak, value) for peak, value in zip(peaks, equities)]
        drawdowns = tuple(value / peak - 1 for value, peak in zip(equities, peaks))
        points.append(Recorded2026Point(day, *equities, *returns, *drawdowns))
        previous = equities
    return Recorded2026History(points=tuple(points), start_date=dates[0], end_date=dates[-1],
        source_status="SYNTHETIC_FAILED_SOURCE_STATUS", classification="E",
        anti_bloat_status="FAIL_HARD_GATE", accounting_complete=False, return_observations=4,
        source_refs=(("X:/NEVER_OPEN/synthetic_daily.parquet", "ab" * 32),))


def _series(window, key):
    return next(series for series in window.series if series.key == key)


def test_calendar_year_start_keeps_first_actual_date_and_original_source_without_io(monkeypatch):
    source = _history()
    before = asdict(source)
    def forbidden(*args, **kwargs):
        raise AssertionError("A display window must not read an artifact")
    monkeypatch.setattr(Path, "open", forbidden)
    window = slice_recorded_2026(source, "2026-01-01", "2026-12-31")
    assert window.status == "available" and window.error is None
    assert (window.requested_start, window.requested_end) == ("2026-01-01", "2026-12-31")
    assert (window.start_date, window.end_date) == ("2026-01-02", "2026-01-08")
    assert window.baseline_date == "2026-01-02" and window.baseline_is_archive_start
    assert window.points == source.points and window.return_observations == 4
    assert window.source is source and asdict(source) == before
    assert window.source.source_status == "SYNTHETIC_FAILED_SOURCE_STATUS"
    assert window.source.source_refs == source.source_refs and window.source.accounting_complete is False
    assert not hasattr(_series(window, "A2"), "recorded_sharpe")
    with pytest.raises(FrozenInstanceError):
        window.status = "changed"


def test_cropped_window_includes_first_loss_and_rebases_from_immediate_prior_record():
    source = _history()
    before = asdict(source)
    window = slice_recorded_2026(source, "2026-01-06", "2026-01-07")
    assert window.status == "available" and window.baseline_date == "2026-01-05"
    assert not window.baseline_is_archive_start and window.return_observations == 2
    assert tuple(point.date for point in window.points) == ("2026-01-06", "2026-01-07")
    a2 = _series(window, "A2")
    assert [point.a2_equity for point in window.points] == pytest.approx([75., 82.5])
    assert [point.a2_drawdown for point in window.points] == pytest.approx([-.25, -.175])
    assert a2.total_return == pytest.approx(-.175) and a2.maximum_drawdown == pytest.approx(-.25)
    assert a2.worst_day == pytest.approx(-.25) and a2.best_day == pytest.approx(.1)
    assert a2.positive_day_pct == .5 and a2.final_equity == pytest.approx(82.5)
    assert _series(window, "A").total_return == pytest.approx(103.95 / 110 - 1)
    assert _series(window, "QQQ").total_return == pytest.approx(99.91 / 98 - 1)
    assert asdict(source) == before


def test_archive_prefix_keeps_source_rounding_and_full_window_keeps_original_summary_values():
    source = _history()
    source = replace(source, points=(source.points[0], source.points[1],
        replace(source.points[2], a_drawdown=-.1), *source.points[3:]))
    derived = slice_recorded_2026(source, "2026-01-01", "2026-12-31")
    original_series = tuple(Recorded2026Series(
        row.key, round(row.total_return, 8), round(row.maximum_drawdown, 8),
        round(row.worst_day, 8), round(row.best_day, 8), round(row.final_equity, 8),
        row.positive_day_pct, 999.0) for row in derived.series)
    source = replace(source, series=original_series)
    full = slice_recorded_2026(source, "2026-01-01", "2026-12-31")
    prefix = slice_recorded_2026(source, "2026-01-01", "2026-01-06")
    assert all(point is source.points[index] for index, point in enumerate(full.points))
    assert prefix.points == source.points[:3] and prefix.points[2].a_drawdown == -.1
    for actual, original in zip(full.series, original_series):
        assert asdict(actual) == {key: value for key, value in asdict(original).items() if key != "recorded_sharpe"}
    assert _series(prefix, "A2").total_return == pytest.approx(-.1)
    assert prefix.series != full.series


def test_window_drawdown_resets_old_peak_but_does_not_discard_first_selected_return():
    window = slice_recorded_2026(_history(), "2026-01-07", "2026-01-08")
    assert window.baseline_date == "2026-01-06"
    assert [point.a2_equity for point in window.points] == pytest.approx([110., 104.5])
    assert _series(window, "A2").maximum_drawdown == pytest.approx(-.05)
    assert _series(window, "A2").total_return == pytest.approx(.045)
    assert window.points[0].a2_return == pytest.approx(.1)


def test_baseline_only_window_has_no_daily_risk_observations_or_fabricated_zero_rates():
    window = slice_recorded_2026(_history(), "2026-01-01", "2026-01-04")
    assert window.status == "available" and window.return_observations == 0
    assert len(window.points) == 1 and window.points[0].date == "2026-01-02"
    for series in window.series:
        assert series.total_return == series.maximum_drawdown == 0 and series.final_equity == 100
        assert series.worst_day is series.best_day is series.positive_day_pct is None


def test_one_cropped_record_is_one_return_and_keeps_its_drawdown():
    window = slice_recorded_2026(_history(), "2026-01-06", "2026-01-06")
    assert window.status == "available" and window.return_observations == 1
    series = _series(window, "A2")
    assert series.total_return == series.maximum_drawdown == series.worst_day == series.best_day == -.25
    assert series.positive_day_pct == 0 and series.final_equity == 75


@pytest.mark.parametrize("start,end", [("2026-01-03", "2026-01-04"),
    ("2026-04-01", "2026-06-30"), ("2026-01-01", "2026-01-01")])
def test_empty_weekend_quarter_or_holiday_is_explicit_and_never_selects_a_nearby_record(start, end):
    window = slice_recorded_2026(_history(), start, end)
    assert window.status == "empty" and window.error
    assert window.requested_start == start and window.requested_end == end
    assert not window.points and not window.series and window.start_date is window.end_date is None
    assert window.baseline_date is None and window.return_observations == 0


@pytest.mark.parametrize("start,end", [("2026-01-08", "2026-01-02"),
    ("2026-1-2", "2026-01-08"), ("2026-02-30", "2026-03-01"), (None, "2026-01-08")])
def test_invalid_calendar_bounds_fail_closed(start, end):
    window = slice_recorded_2026(_history(), start, end)
    assert window.status == "invalid" and window.error and not window.points and not window.series


def test_unavailable_source_preserves_its_failure_and_does_not_return_numbers():
    source = replace(_history(), error="Synthetic source identity failure")
    window = slice_recorded_2026(source, "2026-01-01", "2026-12-31")
    assert window.status == "invalid" and window.error == source.error and window.source is source
    assert not window.points and not window.series
    empty = slice_recorded_2026(Recorded2026History(), "2026-01-01", "2026-12-31")
    assert empty.status == "empty" and empty.error and not empty.points


@pytest.mark.parametrize("mutation", [
    lambda source: replace(source, points=tuple(reversed(source.points))),
    lambda source: replace(source, points=(source.points[0], *source.points)),
    lambda source: replace(source, start_date="2026-01-01"),
    lambda source: replace(source, points=(replace(source.points[0], date="2025-12-31"), *source.points[1:])),
    lambda source: replace(source, points=(replace(source.points[0], a2_return=.05), *source.points[1:])),
    lambda source: replace(source, points=(replace(source.points[0], a2_equity=0), *source.points[1:])),
    lambda source: replace(source, points=(*source.points[:2], replace(source.points[2], qqq_equity=float("nan")), *source.points[3:])),
    lambda source: replace(source, points=(*source.points[:2], replace(source.points[2], a_return=float("inf")), *source.points[3:])),
    lambda source: replace(source, points=(*source.points[:2], replace(source.points[2], a2_drawdown=float("nan")), *source.points[3:])),
    lambda source: replace(source, points=(*source.points[:2], replace(source.points[2], qqq_drawdown=.1), *source.points[3:])),
])
def test_invalid_source_chronology_or_used_values_do_not_return_partial_numbers(mutation):
    window = slice_recorded_2026(mutation(_history()), "2026-01-01", "2026-12-31")
    assert window.status == "invalid" and window.error and not window.points and not window.series
