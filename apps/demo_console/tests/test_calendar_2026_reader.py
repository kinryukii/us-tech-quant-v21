"""Synthetic calendar-replay arithmetic, source identity and window isolation."""
from dataclasses import FrozenInstanceError, asdict, replace
from datetime import datetime
import hashlib
import json
from math import prod
from pathlib import Path
import struct

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from apps.demo_console.adapters import calendar_2026_reader as reader
from apps.demo_console.adapters import recorded_2026_reader as recorded
from apps.demo_console.adapters.recorded_2026_reader import Recorded2026Config
from apps.demo_console.components.recorded_2026_window import slice_recorded_2026
from apps.demo_console.tests.test_read_only_contract import _ReadWatch

_DAYS = ("2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07")
_ORIGINAL_STATUS = "FAIL_CLOSED_ANTI_BLOAT_HARD_GATE"
_ARMS = ("A", "A2", "QQQ", "SPY")


@pytest.fixture(autouse=True)
def no_real_calendar_config(monkeypatch):
    def forbidden():
        raise AssertionError("Synthetic tests must provide their own read contract")
    monkeypatch.setattr(reader, "default_calendar_2026_config", forbidden)


def _rows(days):
    changes = {"A": (0., .01, .005, .02), "A2": (0., .04, -.03, .02),
               "QQQ": (0., -.01, .006, .001), "SPY": (0., -.2, .1, -.1)}
    values, peaks, rows = dict.fromkeys(_ARMS, 100.), dict.fromkeys(_ARMS, 100.), []
    for index, day in enumerate(days):
        row = {"date": datetime.fromisoformat(day)}
        for arm in _ARMS:
            values[arm] *= 1 + changes[arm][index]
            peaks[arm] = max(peaks[arm], values[arm])
            row.update({f"{arm}_equity": values[arm], f"{arm}_daily_return": changes[arm][index],
                        f"{arm}_drawdown": values[arm] / peaks[arm] - 1})
        row["SPY_open"] = values["SPY"] * 4
        rows.append(row)
    return rows


def _summary(rows, days):
    metrics = {}
    for arm in _ARMS:
        returns = [row[f"{arm}_daily_return"] for row in rows[1:]]
        metrics[arm] = {
            "total_return": prod(1 + value for value in returns) - 1,
            "maximum_drawdown": min(row[f"{arm}_drawdown"] for row in rows),
            "worst_day": min(returns), "best_day": max(returns),
            "final_equity": rows[-1][f"{arm}_equity"],
            "positive_day_pct": sum(value > 0 for value in returns) / len(returns), "sharpe": None,
        }
    groups = {}
    for row, day in zip(rows, days):
        groups.setdefault(day[:7], []).append((day, row))
    periods = [{"period_start": part[0][0], "period_end": part[-1][0],
                **{f"{arm}_return": prod(1 + row[f"{arm}_daily_return"] for _, row in part) - 1
                   for arm in _ARMS}} for part in groups.values()]
    return {
        "schema": "DEMO_2026_CALENDAR_REPLAY_V1", "status": reader._STATUS,
        "headline_eligible": True, "baseline_name": reader.BASELINE_ID, "model_sha256": reader._MODEL,
        "cost_bps_round_trip": 10, "top_n": 20, "research_acceptance": "NOT_REASSESSED",
        "historical_identity_status_upgraded": False, "requested_start_date": "2026-01-01",
        "start_date": days[0], "end_date": days[-1], "point_count": len(days),
        "return_observation_count": len(days) - 1, "source_status": _ORIGINAL_STATUS,
        "metrics": metrics, "subperiods": periods,
        "coverage": [{"signal_date": day, "active_quarter": "2025Q3" if day < "2026-02-25"
                      else ("2025Q4" if day < "2026-05-22" else "2026Q1"),
                      "raw_13f_count": 643, "price_eligible_count": 492, "final_U_t_count": 380}
                     for day in days],
    }


def _write_json(path, value):
    content = json.dumps(value).encode("utf-8")
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def calendar_config(artifact_dir):
    def create(*, days=_DAYS, mutate_rows=None, mutate_summary=None, mutate_audit=None,
               statistics=True, drop_column=None):
        rows = _rows(days)
        summary = _summary(rows, days)
        audit = dict.fromkeys(("model_fit_count", "parameter_search_count", "risk_overlay_count",
            "history_download_count", "network_request_count", "source_files_changed",
            "forward_contracts_changed", "missing_price_event_count",
            "held_corporate_action_exception_count", "pit_violation_count",
            "lookahead_violation_count", "training_data_after_2025_12_31_count"), 0)
        audit.update(headline_eligible=True, model_predict_count=1, missing_price_events=[],
            held_corporate_action_exceptions=[], failures=[],
            source_verification_before_and_after="46_RESOLVED_MATCHES",
            source_resolution_sha256=reader._SOURCES, input_coverage_sha256=reader._INPUTS,
            model_artifact_sha256=reader._MODEL,
            accounting_results={"status": "VERIFIED_ACCOUNTING_IDENTITIES", "max_absolute_residual": 0.,
                "models": {arm: {"daily_rows": len(days), "position_rows": len(days) * 20,
                                  "trade_rows": 0} for arm in ("A", "A2")}})
        if mutate_rows:
            mutate_rows(rows)
        if drop_column:
            for row in rows:
                row.pop(drop_column)
        daily = artifact_dir / "daily.parquet"
        pq.write_table(pa.Table.from_pylist(rows), daily, row_group_size=1, write_statistics=statistics)
        daily_hash = hashlib.sha256(daily.read_bytes()).hexdigest()
        if mutate_audit:
            mutate_audit(audit)
        audit_path = artifact_dir / "audit.json"
        audit_hash = _write_json(audit_path, audit)
        summary["artifact_sha256"] = {"daily.parquet": daily_hash, "audit.json": audit_hash}
        if mutate_summary:
            mutate_summary(summary)
        summary_path = artifact_dir / "summary.json"
        summary_hash = _write_json(summary_path, summary)
        return Recorded2026Config(summary_path, summary_hash, audit_path, audit_hash, daily, daily_hash,
                                  days[0], days[-1], len(days), 2)
    return create


def _unavailable(history, code):
    assert history.error and code in history.debug_error
    assert history.points == history.series == history.spy_points == history.coverage == ()
    assert history.subperiods == history.source_refs == () and history.return_observations == 0
    assert history.start_date is history.end_date is history.model_sha256 is None
    assert history.source_status is history.original_source_status is None


@pytest.mark.parametrize("days", [_DAYS, ("2026-06-30", "2026-07-01", "2026-07-02", "2026-07-03")])
def test_four_paths_retain_real_dates_losses_source_limits_and_original_bytes(calendar_config, days):
    config = calendar_config(days=days)
    files = (config.daily_path, config.summary_path, config.audit_path)
    before = {path: path.read_bytes() for path in files}
    history = reader.read_calendar_2026(config)
    assert history.error is history.debug_error is None
    assert tuple(point.date for point in history.points) == days
    assert tuple(point.date for point in history.spy_points) == days
    assert [series.key for series in history.series] == ["A", "A2", "QQQ"]
    assert history.return_observations == 3 and len(history.coverage) == 4
    assert history.original_source_status == _ORIGINAL_STATUS and history.source_status == reader._STATUS
    assert history.classification == "DESCRIPTIVE_ONLY" and history.accounting_complete is False
    assert history.anti_bloat_status == "NOT_REASSESSED" and history.model_sha256 == reader._MODEL
    assert history.spy_points[0].equity == 1 and history.spy_points[0].daily_return == 0
    assert [point.equity for point in history.spy_points] == pytest.approx([1., .8, .88, .792])
    assert history.spy_points[1].drawdown == pytest.approx(-.2)
    assert history.spy_points[-1].drawdown == pytest.approx(-.208)
    assert history.series[0].worst_day == .005 and history.series[0].positive_day_pct == 1
    assert all(series.recorded_sharpe is None for series in history.series)
    assert history.source_refs == tuple((str(path), getattr(config, f"{name}_sha256"))
                                     for name, path in (("summary", config.summary_path),
                                                        ("audit", config.audit_path), ("daily", config.daily_path)))
    assert {path: path.read_bytes() for path in files} == before
    with pytest.raises(FrozenInstanceError):
        history.coverage[0].eligible = 1


@pytest.mark.parametrize("arm", _ARMS)
@pytest.mark.parametrize("field", ["total_return", "maximum_drawdown", "worst_day", "best_day",
                                  "final_equity", "positive_day_pct"])
def test_every_series_summary_must_match_recorded_values(calendar_config, arm, field):
    def mutate(summary):
        summary["metrics"][arm][field] += .125
    result = reader.read_calendar_2026(calendar_config(mutate_summary=mutate))
    _unavailable(result, "SPY_SUMMARY" if arm == "SPY" else "SUMMARY_METRIC_MISMATCH")


@pytest.mark.parametrize("arm", _ARMS)
@pytest.mark.parametrize("metric,value,code", [("daily_return", .7, "RETURN"),
                                              ("drawdown", -.7, "DRAWDOWN")])
def test_every_series_return_and_drawdown_must_match_its_equity(calendar_config, arm, metric, value, code):
    config = calendar_config(mutate_rows=lambda rows: rows[1].update({f"{arm}_{metric}": value}))
    _unavailable(reader.read_calendar_2026(config), code)


@pytest.mark.parametrize("index,field,value,code", [
    (0, "SPY_equity", 101., "SPY_INITIAL"), (0, "SPY_daily_return", .01, "SPY_RETURN"),
    (1, "SPY_open", 800., "SPY_PRICE"), (0, "SPY_open", 0., "INVALID_SPY"),
    (1, "SPY_equity", float("nan"), "INVALID_NUMBER"),
    (1, "SPY_drawdown", .01, "INVALID_SPY"), (1, "SPY_daily_return", -1., "INVALID_SPY"),
])
def test_spy_baseline_price_units_and_invalid_values_fail_closed(calendar_config, index, field, value, code):
    config = calendar_config(mutate_rows=lambda rows: rows[index].update({field: value}))
    _unavailable(reader.read_calendar_2026(config), code)


@pytest.mark.parametrize("case,code", [("2025", "DATE_BOUNDARY_MISMATCH"),
    ("2027", "DATE_BOUNDARY_MISMATCH"), ("null_date", "UNPROVEN_DATE_BOUNDARY"),
    ("shorter", "EXACT_WINDOW_MISMATCH"), ("missing_row", "POINT_COUNT_MISMATCH"),
    ("no_stats", "UNPROVEN_DATE_BOUNDARY"), ("missing_spy", "COLUMNS_MISSING")])
def test_unproven_date_count_or_extra_columns_stop_at_footer(calendar_config, monkeypatch, case, code):
    changes = {"2025": lambda rows: rows[1].update(date=datetime(2025, 12, 31)),
               "2027": lambda rows: rows[1].update(date=datetime(2027, 1, 1)),
               "null_date": lambda rows: rows[1].update(date=None),
               "shorter": lambda rows: rows[0].update(date=datetime(2026, 1, 5)),
               "missing_row": lambda rows: rows.pop()}
    config = calendar_config(mutate_rows=changes.get(case), statistics=case != "no_stats",
                             drop_column="SPY_open" if case == "missing_spy" else None)
    raw = config.daily_path.read_bytes()
    footer_start = len(raw) - 8 - struct.unpack("<I", raw[-8:-4])[0]
    spans, original_open = [], Path.open
    def watched(path, mode="r", *args, **kwargs):
        assert path == config.daily_path and mode == "rb"
        return _ReadWatch(original_open(path, mode, *args, **kwargs), spans)
    def forbidden(*args, **kwargs):
        raise AssertionError("Failed date/schema proof reached full-file data")
    monkeypatch.setattr(Path, "open", watched)
    monkeypatch.setattr(recorded.hashlib, "file_digest", forbidden)
    monkeypatch.setattr(recorded.pq, "ParquetFile", forbidden)
    _unavailable(reader.read_calendar_2026(config), code)
    assert spans and all(footer_start <= start <= end <= len(raw) for start, end in spans)


@pytest.mark.parametrize("field", ["summary", "audit", "daily"])
def test_changed_bytes_cannot_inherit_the_pinned_identity(calendar_config, field):
    config = calendar_config()
    path = getattr(config, f"{field}_path")
    raw = bytearray(path.read_bytes())
    raw[4] ^= 1
    path.write_bytes(raw)
    _unavailable(reader.read_calendar_2026(config), "IDENTITY_MISMATCH")


@pytest.mark.parametrize("field,value,code", [("start_date", "2025-12-31", "INVALID_WINDOW"),
    ("end_date", "2027-01-01", "INVALID_WINDOW"), ("expected_points", 1, "INVALID_COUNT_CONTRACT"),
    ("expected_points", True, "INVALID_COUNT_CONTRACT"), ("daily_sha256", "PENDING", "INVALID_IDENTITY_CONTRACT")])
def test_invalid_contract_reads_nothing(calendar_config, monkeypatch, field, value, code):
    config = replace(calendar_config(), **{field: value})
    def forbidden(*args, **kwargs):
        raise AssertionError("An invalid read contract accessed a source")
    monkeypatch.setattr(Path, "open", forbidden)
    _unavailable(reader.read_calendar_2026(config), code)


@pytest.mark.parametrize("mutation,code", [
    (lambda summary: summary.update(headline_eligible=False), "IDENTITY_OR_SCOPE"),
    (lambda summary: summary.update(headline_eligible=1), "IDENTITY_OR_SCOPE"),
    (lambda summary: summary.update(model_sha256="ff" * 32), "IDENTITY_OR_SCOPE"),
    (lambda summary: summary.update(research_acceptance="PASS"), "IDENTITY_OR_SCOPE"),
    (lambda summary: summary.update(source_status="PASS"), "IDENTITY_OR_SCOPE"),
    (lambda summary: summary.update(historical_identity_status_upgraded=True), "IDENTITY_OR_SCOPE"),
    (lambda summary: summary.update(requested_start_date="2026-06-15"), "IDENTITY_OR_SCOPE"),
    (lambda summary: summary.update(cost_bps_round_trip=0), "IDENTITY_OR_SCOPE"),
    (lambda summary: summary.update(return_observation_count=4), "WINDOW"),
    (lambda summary: summary.update(end_date="2026-08-13"), "WINDOW"),
    (lambda summary: summary["artifact_sha256"].update(**{"audit.json": "ff" * 32}), "ARTIFACT_BINDING"),
    (lambda summary: summary["subperiods"][0].update(A2_return=.99), "SUBPERIOD_RETURN_MISMATCH"),
    (lambda summary: summary["subperiods"].clear(), "SUBPERIODS_MISSING"),
])
def test_identity_scope_and_period_contradictions_discard_every_output(calendar_config, mutation, code):
    _unavailable(reader.read_calendar_2026(calendar_config(mutate_summary=mutation)), code)


@pytest.mark.parametrize("value", [False, 1, None])
def test_audit_without_explicit_headline_acceptance_cannot_publish_numbers(calendar_config, value):
    result = reader.read_calendar_2026(calendar_config(mutate_audit=lambda audit: audit.update(headline_eligible=value)))
    _unavailable(result, "AUDIT_NOT_ACCEPTED")


@pytest.mark.parametrize("field,value,code", [
    ("model_fit_count", 1, "AUDIT_VIOLATION"),
    ("network_request_count", False, "AUDIT_VIOLATION"),
    ("model_predict_count", True, "AUDIT_NOT_ACCEPTED"),
    ("missing_price_events", [{"ticker": "SYNTH", "date": _DAYS[1]}], "AUDIT_NOT_ACCEPTED"),
    ("held_corporate_action_exceptions", [{"ticker": "SYNTH"}], "AUDIT_NOT_ACCEPTED"),
    ("failures", ["SYNTHETIC_FAILURE"], "AUDIT_NOT_ACCEPTED"),
    ("source_verification_before_and_after", "45_RESOLVED_MATCHES", "AUDIT_NOT_ACCEPTED"),
    ("source_resolution_sha256", "ff" * 32, "AUDIT_NOT_ACCEPTED"),
    ("input_coverage_sha256", "ff" * 32, "AUDIT_NOT_ACCEPTED"),
    ("model_artifact_sha256", "ff" * 32, "AUDIT_NOT_ACCEPTED"),
])
def test_audit_counts_events_and_provenance_cannot_contradict_acceptance(calendar_config, field, value, code):
    config = calendar_config(mutate_audit=lambda audit: audit.update({field: value}))
    _unavailable(reader.read_calendar_2026(config), code)


@pytest.mark.parametrize("mutation,code", [
    (lambda value: value.update(max_absolute_residual=1.01e-9), "ACCOUNTING_FAILURE"),
    (lambda value: value.update(max_absolute_residual=-1e-15), "ACCOUNTING_FAILURE"),
    (lambda value: value.update(max_absolute_residual=float("nan")), "INVALID_NUMBER"),
    (lambda value: value.update(status="NOT_VERIFIED"), "ACCOUNTING_FAILURE"),
    (lambda value: value["models"].pop("A"), "ACCOUNTING_FAILURE"),
    (lambda value: value["models"]["A"].update(daily_rows=3), "ACCOUNTING_COUNTS"),
    (lambda value: value["models"]["A2"].update(trade_rows=True), "ACCOUNTING_COUNTS"),
    (lambda value: value["models"]["A"].update(position_rows=-1), "ACCOUNTING_COUNTS"),
])
def test_accounting_status_residuals_and_arm_counts_are_verified(calendar_config, mutation, code):
    config = calendar_config(mutate_audit=lambda audit: mutation(audit["accounting_results"]))
    _unavailable(reader.read_calendar_2026(config), code)


def test_accounting_tolerance_accepts_rounding_without_upgrading_source_status(calendar_config):
    config = calendar_config(mutate_audit=lambda audit:
                             audit["accounting_results"].update(max_absolute_residual=1e-9))
    history = reader.read_calendar_2026(config)
    assert history.error is None and history.original_source_status == _ORIGINAL_STATUS
    assert history.anti_bloat_status == "NOT_REASSESSED"


@pytest.mark.parametrize("mutation,code", [
    (lambda rows: rows.reverse(), "COVERAGE_DATES"),
    (lambda rows: rows.pop(), "COVERAGE_DATES"),
    (lambda rows: rows[1].update(signal_date=rows[0]["signal_date"]), "COVERAGE_DATES"),
    (lambda rows: rows[1].update(signal_date="2026-01-05T12:00:00"), "INVALID_DATE"),
    (lambda rows: rows[1].update(signal_date="2026-01-05T00:00:00+00:00"), "INVALID_DATE"),
    (lambda rows: rows[1].update(active_quarter="2026Q2"), "PIT_QUARTER"),
    (lambda rows: rows[1].update(final_U_t_count=19), "COVERAGE_COUNTS"),
    (lambda rows: rows[1].update(final_U_t_count=493), "COVERAGE_COUNTS"),
    (lambda rows: rows[1].update(price_eligible_count=644), "COVERAGE_COUNTS"),
    (lambda rows: rows[1].update(raw_13f_count=901), "COVERAGE_COUNTS"),
    (lambda rows: rows[1].update(final_U_t_count=True), "COVERAGE_COUNTS"),
    (lambda rows: rows[1].update(final_U_t_count=380.), "COVERAGE_COUNTS"),
])
def test_coverage_has_exact_recorded_dates_order_and_integer_count_hierarchy(calendar_config, mutation, code):
    config = calendar_config(mutate_summary=lambda summary: mutation(summary["coverage"]))
    _unavailable(reader.read_calendar_2026(config), code)


@pytest.mark.parametrize("days,quarters", [
    (("2026-02-23", "2026-02-24", "2026-02-25", "2026-02-26"),
     ("2025Q3", "2025Q3", "2025Q4", "2025Q4")),
    (("2026-05-20", "2026-05-21", "2026-05-22", "2026-05-26"),
     ("2025Q4", "2025Q4", "2026Q1", "2026Q1")),
])
def test_coverage_changes_only_on_recorded_pit_effective_dates(calendar_config, days, quarters):
    history = reader.read_calendar_2026(calendar_config(days=days))
    assert history.error is None
    assert tuple(row.quarter for row in history.coverage) == quarters


def test_exact_midnight_coverage_dates_match_the_same_recorded_days(calendar_config):
    def mutate(summary):
        for row in summary["coverage"]:
            row["signal_date"] += "T00:00:00"
    history = reader.read_calendar_2026(calendar_config(mutate_summary=mutate))
    assert history.error is None
    assert tuple(row.date for row in history.coverage) == _DAYS


def test_reader_opens_only_its_three_synthetic_files(calendar_config, monkeypatch):
    config = calendar_config()
    paths = {config.daily_path, config.summary_path, config.audit_path}
    opened, original_open = [], Path.open
    def watched(path, mode="r", *args, **kwargs):
        assert path in paths and mode == "rb", f"Unexpected source read: {path}"
        opened.append(path)
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", watched)
    assert reader.read_calendar_2026(config).error is None
    assert set(opened) == paths


def test_spy_window_keeps_first_loss_and_all_three_strategy_paths_unchanged(calendar_config):
    history = reader.read_calendar_2026(calendar_config())
    before = asdict(history)
    window = slice_recorded_2026(history, _DAYS[1], _DAYS[-1])
    window_before = asdict(window)
    markets = reader.calendar_market_window(history, window)
    assert markets.error is None and markets.baseline_date == _DAYS[0]
    assert (markets.start_date, markets.end_date) == (_DAYS[1], _DAYS[-1])
    spy = markets.series[0]
    assert tuple(point.date for point in spy.points) == tuple(point.date for point in window.points)
    assert [point.equity for point in spy.points] == pytest.approx([.8, .88, .792])
    assert spy.points[0].daily_return == pytest.approx(-.2)
    assert spy.points[0].drawdown == pytest.approx(-.2)
    assert spy.total_return == spy.max_drawdown == pytest.approx(-.208)
    assert spy.source_refs == history.source_refs
    assert asdict(history) == before and asdict(window) == window_before


@pytest.mark.parametrize("index", [0, 1, 2])
def test_one_selected_date_has_correct_spy_baseline_and_first_return(calendar_config, index):
    history = reader.read_calendar_2026(calendar_config())
    before = asdict(history)
    window = slice_recorded_2026(history, _DAYS[index], _DAYS[index])
    markets = reader.calendar_market_window(history, window)
    assert len(markets.series[0].points) == 1
    point = markets.series[0].points[0]
    expected = (1., .8, 1.1)[index]
    assert point.equity == pytest.approx(expected)
    assert markets.series[0].total_return == pytest.approx(expected - 1)
    assert point.drawdown == pytest.approx(min(expected - 1, 0))
    assert markets.baseline_date == (None if index == 0 else _DAYS[index - 1])
    assert asdict(history) == before


@pytest.mark.parametrize("case", ["empty", "invalid_window", "source_error"])
def test_unavailable_window_never_builds_a_partial_spy_curve(calendar_config, case):
    history = reader.read_calendar_2026(calendar_config())
    window = slice_recorded_2026(history, "2026-02-01", "2026-02-28") if case == "empty" else (
        slice_recorded_2026(history, "2026-01-07", "2026-01-02") if case == "invalid_window"
        else slice_recorded_2026(history, _DAYS[0], _DAYS[-1]))
    if case == "source_error":
        history = replace(history, error="Synthetic source failure")
    before, window_before = asdict(history), asdict(window)
    markets = reader.calendar_market_window(history, window)
    assert markets.error and markets.series == ()
    assert markets.start_date is markets.end_date is None
    assert asdict(history) == before and asdict(window) == window_before
