"""Synthetic identity, period-accounting and exact 2026 read boundaries."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime
import hashlib
import json
from pathlib import Path
import struct

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from apps.demo_console.adapters import recorded_2026_reader as reader
from apps.demo_console.adapters.recorded_2026_reader import Recorded2026Config, read_recorded_2026
from apps.demo_console.tests.test_read_only_contract import _ReadWatch


def _fixture_rows():
    days = ("2026-06-30", "2026-07-01", "2026-07-02", "2026-07-03")
    returns = {"A": (0, .01, .005, .02), "A2": (0, .04, -.03, .02), "QQQ": (0, -.01, .006, .001)}
    equities, peaks, rows = {arm: 100.0 for arm in returns}, {arm: 100.0 for arm in returns}, []
    for index, day in enumerate(days):
        row = {"date": datetime.fromisoformat(day)}
        for arm, values in returns.items():
            equities[arm] *= 1 + values[index]
            peaks[arm] = max(peaks[arm], equities[arm])
            row.update({f"{arm}_equity": equities[arm], f"{arm}_daily_return": float(values[index]),
                        f"{arm}_drawdown": equities[arm] / peaks[arm] - 1})
        rows.append(row)
    return rows


def _fixture_summary(rows):
    metrics = {}
    for arm in ("A", "A2", "QQQ"):
        returns = [row[f"{arm}_daily_return"] for row in rows[1:]]
        metrics[arm] = {
            "total_return": rows[-1][f"{arm}_equity"] / 100 - 1,
            "maximum_drawdown": min(row[f"{arm}_drawdown"] for row in rows),
            "worst_day": min(returns), "best_day": max(returns),
            "final_equity": rows[-1][f"{arm}_equity"],
            "positive_day_pct": sum(value > 0 for value in returns) / len(returns),
            "sharpe": 2.0,  # Original summary field only; no new inference is made.
        }
    subperiods = []
    for start, end, part in (("2026-06-30", "2026-06-30", rows[:1]),
                             ("2026-07-01", "2026-07-03", rows[1:])):
        period = {"period_start": start, "period_end": end}
        for arm in metrics:
            wealth = 1.0
            for row in part:
                wealth *= 1 + row[f"{arm}_daily_return"]
            period[f"{arm}_return"] = wealth - 1
        subperiods.append(period)
    return {
        "FROZEN_BASELINE_NAME": reader.BASELINE_ID,
        "A_A2_CLEAN_BASELINE_FREEZE_STATUS": reader._FREEZE_STATUS,
        "A_A2_2026_PRE_RISK_STATUS": reader._SOURCE_STATUS, "FINAL_CLASSIFICATION": "E",
        "anti_bloat_gate": {"status": "FAIL_HARD_GATE", "accounting_complete": False},
        "EFFECTIVE_START_DATE": "2026-06-30", "EFFECTIVE_END_DATE": "2026-07-03",
        "START_EQUITY": 100.0, "PRIMARY_BENCHMARK": "QQQ",
        "metrics": metrics, "subperiods": subperiods,
        "audit_counts": {key: 0 for key in reader._ZERO_COUNTERS},
    }


def _write_json(path, value):
    data = json.dumps(value).encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def recorded_config(artifact_dir):
    def create(*, mutate_rows=None, mutate_summary=None, mutate_audit=None, statistics=True, drop_column=None):
        rows = _fixture_rows()
        summary = _fixture_summary(rows)
        audit = {
            "FROZEN_BASELINE_NAME": reader.BASELINE_ID,
            "A_A2_CLEAN_BASELINE_FREEZE_STATUS": reader._FREEZE_STATUS,
            **{key: 0 for key in reader._ZERO_COUNTERS},
            "MODEL_PREDICT_DURING_THIS_RUN_COUNT": 1,
            "fresh_frozen_hash_verification": {
                "required_count": 2, "match_count": 2, "mismatch_count": 0,
                "checks": [{"artifact_id": f"synthetic_{index}", "expected_sha256": str(index) * 64,
                            "actual_sha256": str(index) * 64, "match": True,
                            "path": f"X:/DO_NOT_OPEN/synthetic_model_{index}.joblib"} for index in (1, 2)],
            },
        }
        if mutate_rows:
            mutate_rows(rows)
        if drop_column:
            for row in rows:
                row.pop(drop_column)
        daily_path = artifact_dir / f"{reader._PREFIX}_daily.parquet"
        pq.write_table(pa.Table.from_pylist(rows), daily_path, write_statistics=statistics, row_group_size=1)
        daily_sha = hashlib.sha256(daily_path.read_bytes()).hexdigest()
        audit_path = artifact_dir / f"{reader._PREFIX}_audit.json"
        if mutate_audit:
            mutate_audit(audit)
        audit_sha = _write_json(audit_path, audit)
        summary["artifact_sha256"] = {daily_path.name: daily_sha, audit_path.name: audit_sha}
        if mutate_summary:
            mutate_summary(summary)
        summary_path = artifact_dir / f"{reader._PREFIX}_summary.json"
        summary_sha = _write_json(summary_path, summary)
        return Recorded2026Config(summary_path, summary_sha, audit_path, audit_sha, daily_path, daily_sha,
                                  "2026-06-30", "2026-07-03", 4, 2)
    return create


def _assert_unavailable(result, code):
    assert result.error and code in result.debug_error
    assert result.points == result.series == result.subperiods == result.source_refs == ()
    assert result.start_date is result.end_date is result.source_status is None
    assert result.return_observations == 0


def test_values_baseline_and_failed_source_status_are_preserved(recorded_config):
    config = recorded_config()
    result = read_recorded_2026(config)
    assert result.error is result.debug_error is None
    assert len(result.points) == 4 and result.return_observations == 3
    assert (result.start_date, result.end_date) == ("2026-06-30", "2026-07-03")
    assert result.source_status == "FAIL_CLOSED_ANTI_BLOAT_HARD_GATE"
    assert result.classification == "E" and result.anti_bloat_status == "FAIL_HARD_GATE"
    assert result.accounting_complete is False
    first = result.points[0]
    assert first.a_equity == first.a2_equity == first.qqq_equity == 100.0
    assert first.a_return == first.a2_return == first.qqq_return == 0.0
    assert [series.key for series in result.series] == ["A", "A2", "QQQ"]
    a = result.series[0]
    # A's three real observations are positive; the artificial zero baseline
    # must not become the worst day or reduce the positive-day frequency.
    assert a.worst_day == .005 and a.positive_day_pct == 1.0
    assert a.total_return == pytest.approx(result.points[-1].a_equity / 100 - 1)
    assert a.recorded_sharpe == 2.0
    assert result.subperiods[0].a_return == 0.0
    assert result.subperiods[1].a2_return == pytest.approx(result.series[1].total_return)
    assert len(result.source_refs) == 3
    with pytest.raises(FrozenInstanceError):
        result.points[0].a_equity = 500


@pytest.mark.parametrize("case,code", [
    ("2025", "DATE_BOUNDARY_MISMATCH"), ("2027", "DATE_BOUNDARY_MISMATCH"),
    ("outside_exact_window", "DATE_BOUNDARY_MISMATCH"),
    ("shorter_window", "EXACT_WINDOW_MISMATCH"),
    ("missing_statistics", "UNPROVEN_DATE_BOUNDARY"), ("null_date", "UNPROVEN_DATE_BOUNDARY"),
    ("missing_date", "DATE_COLUMN_MISSING"), ("missing_value", "COLUMNS_MISSING"),
    ("missing_row", "POINT_COUNT_MISMATCH"),
])
def test_unproven_input_stops_at_exact_footer_before_hash_or_data(recorded_config, monkeypatch, case, code):
    mutations = {
        "2025": lambda rows: rows[1].update(date=datetime(2025, 12, 31)),
        "2027": lambda rows: rows[1].update(date=datetime(2027, 1, 1)),
        "outside_exact_window": lambda rows: rows[1].update(date=datetime(2026, 1, 1)),
        "shorter_window": lambda rows: rows[0].update(date=datetime(2026, 7, 1)),
        "null_date": lambda rows: rows[1].update(date=None),
        "missing_row": lambda rows: rows.pop(),
    }
    config = recorded_config(mutate_rows=mutations.get(case), statistics=case != "missing_statistics",
                             drop_column={"missing_date": "date", "missing_value": "A2_equity"}.get(case))
    raw = config.daily_path.read_bytes()
    footer_start = len(raw) - 8 - struct.unpack("<I", raw[-8:-4])[0]
    spans, opened, original_open = [], [], Path.open
    def watched(path, mode="r", *args, **kwargs):
        assert path == config.daily_path and mode == "rb", "Invalid daily input reached another source"
        opened.append(path)
        return _ReadWatch(original_open(path, mode, *args, **kwargs), spans)
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid date/schema input reached full-file hash or data pages")
    monkeypatch.setattr(Path, "open", watched)
    monkeypatch.setattr(reader.hashlib, "file_digest", forbidden)
    monkeypatch.setattr(reader.pq, "ParquetFile", forbidden)
    _assert_unavailable(read_recorded_2026(config), code)
    assert opened and spans and all(footer_start <= start <= end <= len(raw) for start, end in spans)


@pytest.mark.parametrize("config_field,value,code", [
    ("start_date", "2025-12-31", "INVALID_WINDOW"), ("end_date", "2027-01-01", "INVALID_WINDOW"),
    ("start_date", "2026-99-00", "INVALID_DATE"), ("expected_points", True, "INVALID_COUNT_CONTRACT"),
    ("daily_sha256", "unbound", "INVALID_IDENTITY_CONTRACT"),
])
def test_invalid_read_contract_opens_nothing(recorded_config, monkeypatch, config_field, value, code):
    config = replace(recorded_config(), **{config_field: value})
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid read contract accessed a file")
    monkeypatch.setattr(Path, "open", forbidden)
    _assert_unavailable(read_recorded_2026(config), code)


@pytest.mark.parametrize("field", ["daily", "summary", "audit"])
def test_changed_file_cannot_inherit_pinned_identity(recorded_config, field):
    config = recorded_config()
    path = getattr(config, f"{field}_path")
    data = bytearray(path.read_bytes())
    data[4] ^= 1
    path.write_bytes(data)
    _assert_unavailable(read_recorded_2026(config), "IDENTITY_MISMATCH")


@pytest.mark.parametrize("field,value,code", [
    ("A2_equity", float("nan"), "INVALID_NUMBER"), ("A2_equity", None, "INVALID_NUMBER"),
    ("A2_equity", 0.0, "INVALID_EQUITY_OR_RETURN"),
    ("A2_daily_return", .5, "RETURN_EQUITY_MISMATCH"),
    ("A2_drawdown", -.5, "DRAWDOWN_MISMATCH"),
])
def test_inconsistent_daily_values_discard_every_series(recorded_config, field, value, code):
    config = recorded_config(mutate_rows=lambda rows: rows[1].update({field: value}))
    _assert_unavailable(read_recorded_2026(config), code)


@pytest.mark.parametrize("mutation,code", [
    (lambda rows: rows.reverse(), "DATE_ORDER_OR_DUPLICATE"),
    (lambda rows: rows[1].update(date=rows[0]["date"]), "DATE_ORDER_OR_DUPLICATE"),
    (lambda rows: rows[0].update(A2_equity=101.0), "INITIAL_EQUITY_MISMATCH"),
    (lambda rows: rows[0].update(A2_daily_return=.01), "INITIAL_RETURN_MISMATCH"),
])
def test_invalid_daily_structure_is_not_repaired(recorded_config, mutation, code):
    _assert_unavailable(read_recorded_2026(recorded_config(mutate_rows=mutation)), code)


@pytest.mark.parametrize("field", ["total_return", "maximum_drawdown", "worst_day", "best_day",
                                  "final_equity", "positive_day_pct"])
def test_summary_metrics_must_agree_with_actual_rows(recorded_config, field):
    def mutation(summary):
        summary["metrics"]["A2"][field] += .1
    _assert_unavailable(read_recorded_2026(recorded_config(mutate_summary=mutation)), "SUMMARY_METRIC_MISMATCH")


@pytest.mark.parametrize("mutation,code", [
    (lambda summary: summary.update(FROZEN_BASELINE_NAME="ANOTHER_BASELINE"), "BASELINE_IDENTITY_MISMATCH"),
    (lambda summary: summary.update(A_A2_2026_PRE_RISK_STATUS="PASS_VALID_PROSPECTIVE_HOLDOUT"), "SOURCE_STATUS_MISMATCH"),
    (lambda summary: summary.update(FINAL_CLASSIFICATION="A"), "SOURCE_STATUS_MISMATCH"),
    (lambda summary: summary["anti_bloat_gate"].update(status="PASS"), "ACCEPTANCE_STATUS_MISMATCH"),
    (lambda summary: summary["anti_bloat_gate"].update(accounting_complete=True), "ACCEPTANCE_STATUS_MISMATCH"),
    (lambda summary: summary.update(PRIMARY_BENCHMARK="SPY"), "BENCHMARK_IDENTITY_MISMATCH"),
    (lambda summary: summary.update(EFFECTIVE_START_DATE="2026-01-01"), "SUMMARY_WINDOW_MISMATCH"),
    (lambda summary: summary["artifact_sha256"].clear(), "ARTIFACT_BINDING_MISMATCH"),
    (lambda summary: summary["audit_counts"].update(MODEL_FIT_DURING_THIS_RUN_COUNT=1), "RECORDED_AUDIT_MISMATCH"),
    (lambda summary: summary["subperiods"][1].update(A2_return=.9), "SUBPERIOD_RETURN_MISMATCH"),
    (lambda summary: summary["subperiods"].pop(0), "SUBPERIOD_COVERAGE_MISMATCH"),
    (lambda summary: summary["subperiods"].clear(), "SUBPERIODS_MISSING"),
    (lambda summary: summary["metrics"]["A2"].pop("total_return"), "INVALID_NUMBER"),
])
def test_source_identity_status_and_summary_contradictions_fail_closed(recorded_config, mutation, code):
    _assert_unavailable(read_recorded_2026(recorded_config(mutate_summary=mutation)), code)


@pytest.mark.parametrize("mutation,code", [
    (lambda audit: audit.update(FROZEN_BASELINE_NAME="UNRELATED"), "BASELINE_IDENTITY_MISMATCH"),
    (lambda audit: audit.update(PARAMETER_SEARCH_COUNT=1), "RECORDED_AUDIT_MISMATCH"),
    (lambda audit: audit.update(TRAINING_DATA_AFTER_2025_12_31_COUNT=False), "RECORDED_AUDIT_MISMATCH"),
    (lambda audit: audit["fresh_frozen_hash_verification"].update(mismatch_count=1), "RECORDED_HASH_CHECK_MISMATCH"),
    (lambda audit: audit["fresh_frozen_hash_verification"]["checks"].pop(), "RECORDED_HASH_CHECK_MISMATCH"),
    (lambda audit: audit["fresh_frozen_hash_verification"]["checks"][0].update(match=False), "RECORDED_HASH_CHECK_MISMATCH"),
    (lambda audit: audit["fresh_frozen_hash_verification"]["checks"][0].update(actual_sha256="0" * 64), "RECORDED_HASH_CHECK_MISMATCH"),
])
def test_recorded_audit_is_validated_without_repeating_it(recorded_config, mutation, code):
    _assert_unavailable(read_recorded_2026(recorded_config(mutate_audit=mutation)), code)


def test_only_three_bound_files_are_read_and_all_original_bytes_survive(recorded_config, monkeypatch):
    config = recorded_config()
    paths = (config.daily_path, config.summary_path, config.audit_path)
    before = {path: path.read_bytes() for path in paths}
    opened, original_open = [], Path.open
    def guarded(path, mode="r", *args, **kwargs):
        assert path in paths, f"Followed an unrelated recorded path: {path}"
        assert mode == "rb"
        opened.append(path)
        return original_open(path, mode, *args, **kwargs)
    with monkeypatch.context() as guard:
        guard.setattr(Path, "open", guarded)
        result = read_recorded_2026(config)
    assert result.error is None and set(opened) == set(paths)
    assert {path: path.read_bytes() for path in paths} == before


def test_original_pre2026_reader_still_rejects_new_period_before_io(monkeypatch):
    from apps.demo_console.adapters.performance_reader import read_performance
    def forbidden(*args, **kwargs):
        raise AssertionError("Pre-2026 route reached a 2026 source")
    monkeypatch.setattr(Path, "open", forbidden)
    result = read_performance("2026-06-15")
    assert not result.points and "POST2025_DATE_BLOCKED" in result.debug_error
