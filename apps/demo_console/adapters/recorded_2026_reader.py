"""Read one already exposed 2026 comparison; never evaluate or extend a strategy.

This narrow adapter intentionally does not widen the pre-2026 artifact reader.
It preserves this run's failed acceptance status and its actual observation
window. A verified hash is source identity, not research or trading clearance.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from math import isclose, isfinite
from pathlib import Path
import struct

import pyarrow as pa
import pyarrow.parquet as pq

from apps.demo_console.adapters.artifact_reader import ArtifactError, iso_date
from apps.demo_console.config.demo_config import BASELINE_ID
from scripts.common.storage_paths import resolve


_ARMS = ("A", "A2", "QQQ")
_COLUMNS = ("date", *(f"{arm}_{metric}" for arm in _ARMS
                         for metric in ("equity", "daily_return", "drawdown")))
_SOURCE_STATUS = "FAIL_CLOSED_ANTI_BLOAT_HARD_GATE"
_FREEZE_STATUS = "PASS_FROZEN_IMMUTABLE_RESEARCH_BASELINE"
_PREFIX = "a_a2_vs_qqq_20260615_latest"
_ZERO_COUNTERS = (
    "TRAINING_DATA_AFTER_2025_12_31_COUNT", "MODEL_FIT_DURING_THIS_RUN_COUNT",
    "PARAMETER_SEARCH_COUNT", "RISK_OVERLAY_COUNT", "LOOKAHEAD_VIOLATION_COUNT",
    "PIT_VIOLATION_COUNT", "MISSING_PRICE_EVENT_COUNT", "CORPORATE_ACTION_EXCEPTION_COUNT",
)


@dataclass(frozen=True)
class Recorded2026Config:
    summary_path: Path
    summary_sha256: str
    audit_path: Path
    audit_sha256: str
    daily_path: Path
    daily_sha256: str
    start_date: str = "2026-06-15"
    end_date: str = "2026-08-13"
    expected_points: int = 42
    expected_recorded_hash_checks: int = 46


@dataclass(frozen=True)
class Recorded2026Point:
    date: str
    a_equity: float
    a2_equity: float
    qqq_equity: float
    a_return: float
    a2_return: float
    qqq_return: float
    a_drawdown: float
    a2_drawdown: float
    qqq_drawdown: float


@dataclass(frozen=True)
class Recorded2026Series:
    key: str
    total_return: float
    maximum_drawdown: float
    worst_day: float
    best_day: float
    final_equity: float
    positive_day_pct: float
    recorded_sharpe: float | None


@dataclass(frozen=True)
class Recorded2026Subperiod:
    start_date: str
    end_date: str
    a_return: float
    a2_return: float
    qqq_return: float


@dataclass(frozen=True)
class Recorded2026History:
    points: tuple[Recorded2026Point, ...] = ()
    series: tuple[Recorded2026Series, ...] = ()
    subperiods: tuple[Recorded2026Subperiod, ...] = ()
    start_date: str | None = None
    end_date: str | None = None
    source_status: str | None = None
    classification: str | None = None
    anti_bloat_status: str | None = None
    accounting_complete: bool | None = None
    return_observations: int = 0
    source_refs: tuple[tuple[str, str], ...] = ()
    error: str | None = None
    debug_error: str | None = None


def default_recorded_2026_config() -> Recorded2026Config:
    root = resolve().results_root / "A_A2_2026_PRE_RISK_HOLDOUT_R1"
    return Recorded2026Config(
        root / f"{_PREFIX}_summary.json",
        "2d928d0e86827bb9254d4a64eef08934861703f159cd47d31eea1437bf1a629d",
        root / f"{_PREFIX}_audit.json",
        "3220cb7130d29798693cb6d35d75ff160fc858562f800e05e3a7d32b600af566",
        root / f"{_PREFIX}_daily.parquet",
        "8a4bb4656d92433d184388eb82a76834a6418f032b4b9a327c23aa44255ff203",
    )


def _number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ArtifactError(f"RECORDED2026_INVALID_NUMBER:{field}")
    return float(value)


def _equal(left, right, code):
    if not isclose(left, right, rel_tol=1e-10, abs_tol=1e-12):
        raise ArtifactError(code)


def _bound_config(config):
    start, end = iso_date(config.start_date), iso_date(config.end_date)
    if not "2026-01-01" <= start <= end < "2027-01-01":
        raise ArtifactError("RECORDED2026_INVALID_WINDOW")
    if (type(config.expected_points) is not int or config.expected_points < 2
            or type(config.expected_recorded_hash_checks) is not int
            or config.expected_recorded_hash_checks < 1):
        raise ArtifactError("RECORDED2026_INVALID_COUNT_CONTRACT")
    for digest in (config.summary_sha256, config.audit_sha256, config.daily_sha256):
        if (not isinstance(digest, str) or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)):
            raise ArtifactError("RECORDED2026_INVALID_IDENTITY_CONTRACT")


def _json(path, expected_sha):
    with path.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != expected_sha:
            raise ArtifactError("RECORDED2026_JSON_IDENTITY_MISMATCH")
        handle.seek(0)
        result = json.load(handle)
    if not isinstance(result, dict):
        raise ArtifactError("RECORDED2026_INVALID_JSON_OBJECT")
    return result


def _read_daily(config, *, extra_columns=()):
    # Deliberately mirrors the small footer-only primitive of artifact_reader:
    # the accepted year and the exact configured endpoints are different. No
    # optional bypass is introduced on the established pre-2026 input route.
    with config.daily_path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        if size < 12:
            raise ArtifactError("RECORDED2026_INVALID_PARQUET")
        handle.seek(-8, 2)
        trailer = handle.read(8)
        footer_size = struct.unpack("<I", trailer[:4])[0]
        if trailer[4:] != b"PAR1" or footer_size > size - 12:
            raise ArtifactError("RECORDED2026_INVALID_PARQUET_FOOTER")
        handle.seek(size - 8 - footer_size)
        footer = handle.read(footer_size)
        metadata = pq.read_metadata(pa.BufferReader(b"PAR1" + footer + trailer))
        names = metadata.schema.to_arrow_schema().names
        if metadata.num_rows != config.expected_points:
            raise ArtifactError("RECORDED2026_POINT_COUNT_MISMATCH")
        if "date" not in names:
            raise ArtifactError("RECORDED2026_DATE_COLUMN_MISSING")
        date_index = names.index("date")
        minima, maxima = [], []
        for group in range(metadata.num_row_groups):
            stats = metadata.row_group(group).column(date_index).statistics
            if stats is None or not stats.has_min_max or stats.null_count != 0:
                raise ArtifactError("RECORDED2026_UNPROVEN_DATE_BOUNDARY")
            low, high = iso_date(stats.min), iso_date(stats.max)
            if not "2026-01-01" <= config.start_date <= low <= high <= config.end_date < "2027-01-01":
                raise ArtifactError("RECORDED2026_DATE_BOUNDARY_MISMATCH")
            minima.append(low)
            maxima.append(high)
        if not minima or (min(minima), max(maxima)) != (config.start_date, config.end_date):
            raise ArtifactError("RECORDED2026_EXACT_WINDOW_MISMATCH")
        columns = (*_COLUMNS, *extra_columns)
        if set(columns) - set(names):
            raise ArtifactError("RECORDED2026_COLUMNS_MISSING")
        handle.seek(0)
        if hashlib.file_digest(handle, "sha256").hexdigest() != config.daily_sha256:
            raise ArtifactError("RECORDED2026_DAILY_IDENTITY_MISMATCH")
        rows = pq.ParquetFile(handle).read(columns=list(columns)).to_pylist()
    return rows


def _points(rows, config):
    dates = tuple(iso_date(row["date"]) for row in rows)
    if dates != tuple(sorted(set(dates))) or (dates[0], dates[-1]) != (config.start_date, config.end_date):
        raise ArtifactError("RECORDED2026_DATE_ORDER_OR_DUPLICATE")
    points, previous, peaks = [], {}, {}
    for index, (row, day) in enumerate(zip(rows, dates)):
        equities, returns, drawdowns = [], [], []
        for arm in _ARMS:
            equity = _number(row[f"{arm}_equity"], f"{arm}_equity")
            daily_return = _number(row[f"{arm}_daily_return"], f"{arm}_daily_return")
            drawdown = _number(row[f"{arm}_drawdown"], f"{arm}_drawdown")
            if equity <= 0 or daily_return <= -1 or drawdown > 0 or drawdown <= -1:
                raise ArtifactError("RECORDED2026_INVALID_EQUITY_OR_RETURN")
            if index == 0:
                _equal(equity, 100.0, "RECORDED2026_INITIAL_EQUITY_MISMATCH")
                _equal(daily_return, 0.0, "RECORDED2026_INITIAL_RETURN_MISMATCH")
                peaks[arm] = equity
            else:
                _equal(daily_return, equity / previous[arm] - 1,
                       "RECORDED2026_RETURN_EQUITY_MISMATCH")
            peaks[arm] = max(peaks[arm], equity)
            _equal(drawdown, equity / peaks[arm] - 1, "RECORDED2026_DRAWDOWN_MISMATCH")
            previous[arm] = equity
            equities.append(equity)
            returns.append(daily_return)
            drawdowns.append(drawdown)
        points.append(Recorded2026Point(day, *equities, *returns, *drawdowns))
    return tuple(points)


def _identity(summary, audit, config):
    for record in (summary, audit):
        if (record.get("FROZEN_BASELINE_NAME") != BASELINE_ID
                or record.get("A_A2_CLEAN_BASELINE_FREEZE_STATUS") != _FREEZE_STATUS):
            raise ArtifactError("RECORDED2026_BASELINE_IDENTITY_MISMATCH")
    if (summary.get("A_A2_2026_PRE_RISK_STATUS") != _SOURCE_STATUS
            or summary.get("FINAL_CLASSIFICATION") != "E"):
        raise ArtifactError("RECORDED2026_SOURCE_STATUS_MISMATCH")
    gate = summary.get("anti_bloat_gate", {})
    if gate.get("status") != "FAIL_HARD_GATE" or gate.get("accounting_complete") is not False:
        raise ArtifactError("RECORDED2026_ACCEPTANCE_STATUS_MISMATCH")
    if (summary.get("EFFECTIVE_START_DATE"), summary.get("EFFECTIVE_END_DATE")) != (
            config.start_date, config.end_date):
        raise ArtifactError("RECORDED2026_SUMMARY_WINDOW_MISMATCH")
    if summary.get("PRIMARY_BENCHMARK") != "QQQ":
        raise ArtifactError("RECORDED2026_BENCHMARK_IDENTITY_MISMATCH")
    _equal(_number(summary.get("START_EQUITY"), "START_EQUITY"), 100.0,
           "RECORDED2026_INITIAL_EQUITY_MISMATCH")
    bindings = summary.get("artifact_sha256", {})
    if (bindings.get(config.audit_path.name) != config.audit_sha256
            or bindings.get(config.daily_path.name) != config.daily_sha256):
        raise ArtifactError("RECORDED2026_ARTIFACT_BINDING_MISMATCH")
    for key in _ZERO_COUNTERS:
        for counters in (audit, summary.get("audit_counts", {})):
            if type(counters.get(key)) is not int or counters[key] != 0:
                raise ArtifactError(f"RECORDED2026_RECORDED_AUDIT_MISMATCH:{key}")
    recorded = audit.get("fresh_frozen_hash_verification", {})
    count, checks = config.expected_recorded_hash_checks, recorded.get("checks")
    if (recorded.get("required_count") != count or recorded.get("match_count") != count
            or type(recorded.get("mismatch_count")) is not int or recorded["mismatch_count"] != 0
            or not isinstance(checks, list) or len(checks) != count):
        raise ArtifactError("RECORDED2026_RECORDED_HASH_CHECK_MISMATCH")
    for check in checks:
        expected = check.get("expected_sha256") if isinstance(check, dict) else None
        if (not isinstance(expected, str) or len(expected) != 64
                or any(char not in "0123456789abcdef" for char in expected)
                or check.get("actual_sha256") != expected or check.get("match") is not True):
            raise ArtifactError("RECORDED2026_RECORDED_HASH_CHECK_MISMATCH")


def _series(summary, points):
    result = []
    for arm in _ARMS:
        key = arm.lower()
        metrics = summary["metrics"][arm]
        values = {field: _number(metrics.get(field), f"{arm}.{field}") for field in (
            "total_return", "maximum_drawdown", "worst_day", "best_day", "final_equity", "positive_day_pct")}
        # The first row is the 100-point starting mark, not a return trial.
        returns = [getattr(point, f"{key}_return") for point in points[1:]]
        equity = getattr(points[-1], f"{key}_equity")
        expected = {
            "total_return": equity / 100.0 - 1,
            "maximum_drawdown": min(getattr(point, f"{key}_drawdown") for point in points),
            "worst_day": min(returns), "best_day": max(returns), "final_equity": equity,
            "positive_day_pct": sum(value > 0 for value in returns) / len(returns),
        }
        for field, value in values.items():
            _equal(value, expected[field], f"RECORDED2026_SUMMARY_METRIC_MISMATCH:{arm}.{field}")
        sharpe = metrics["sharpe"]
        if sharpe is not None:
            sharpe = _number(sharpe, f"{arm}.sharpe")
        result.append(Recorded2026Series(arm, **values, recorded_sharpe=sharpe))
    return tuple(result)


def _subperiods(summary, points, config):
    periods, covered, result = summary.get("subperiods"), [], []
    if not isinstance(periods, list) or not periods:
        raise ArtifactError("RECORDED2026_SUBPERIODS_MISSING")
    previous_end = None
    for row in periods:
        start, end = iso_date(row["period_start"]), iso_date(row["period_end"])
        if (not config.start_date <= start <= end <= config.end_date
                or (previous_end is not None and start <= previous_end)):
            raise ArtifactError("RECORDED2026_SUBPERIOD_BOUNDARY_MISMATCH")
        part = [point for point in points if start <= point.date <= end]
        if not part:
            raise ArtifactError("RECORDED2026_EMPTY_SUBPERIOD")
        values = []
        for arm in _ARMS:
            value = _number(row.get(f"{arm}_return"), f"{arm}_subperiod_return")
            wealth = 1.0
            for point in part:
                wealth *= 1 + getattr(point, f"{arm.lower()}_return")
            _equal(value, wealth - 1, "RECORDED2026_SUBPERIOD_RETURN_MISMATCH")
            values.append(value)
        covered.extend(point.date for point in part)
        result.append(Recorded2026Subperiod(start, end, *values))
        previous_end = end
    if (tuple(covered) != tuple(point.date for point in points)
            or result[0].start_date != config.start_date or result[-1].end_date != config.end_date):
        raise ArtifactError("RECORDED2026_SUBPERIOD_COVERAGE_MISMATCH")
    return tuple(result)


def read_recorded_2026(config: Recorded2026Config | None = None) -> Recorded2026History:
    """Return verified recorded values, retaining the run's failed acceptance.

    All three pinned inputs are read-only. Recorded audit paths are displayed
    evidence only: none is followed, rehashed, trained, predicted or replayed.
    A failure discards every number rather than returning partial results.
    """
    try:
        config = config or default_recorded_2026_config()
        _bound_config(config)
        rows = _read_daily(config)
        summary = _json(config.summary_path, config.summary_sha256)
        audit = _json(config.audit_path, config.audit_sha256)
        _identity(summary, audit, config)
        points = _points(rows, config)
        series = _series(summary, points)
        subperiods = _subperiods(summary, points, config)
        return Recorded2026History(
            points=points, series=series, subperiods=subperiods,
            start_date=config.start_date, end_date=config.end_date,
            source_status=summary["A_A2_2026_PRE_RISK_STATUS"], classification=summary["FINAL_CLASSIFICATION"],
            anti_bloat_status=summary["anti_bloat_gate"]["status"],
            accounting_complete=summary["anti_bloat_gate"]["accounting_complete"],
            return_observations=len(points) - 1,
            source_refs=tuple((str(path), digest) for path, digest in (
                (config.summary_path, config.summary_sha256), (config.audit_path, config.audit_sha256),
                (config.daily_path, config.daily_sha256))),
        )
    except Exception as exc:
        return Recorded2026History(
            error="The recorded 2026 comparison is unavailable. Its source identity or recorded values could not be verified.",
            debug_error=f"{type(exc).__name__}: {exc}",
        )
