"""Synthetic execution accounting, authority and read-boundary tests."""
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import struct

import pytest

from apps.demo_console.adapters import artifact_reader, performance_reader
from apps.demo_console.adapters.performance_reader import read_performance
from apps.demo_console.config.demo_config import (
    A_CONFIG_FINGERPRINT, A_SOURCE_FINGERPRINT, A_COEFFICIENT_FINGERPRINT,
    A_FEATURE_SCHEMA_FINGERPRINT,
)
from apps.demo_console.tests.test_authority_identity import _repin_hash_rows, _repin_manifest
from apps.demo_console.tests.test_read_only_contract import _ReadWatch


def _execution_rows(model="A2_HGB"):
    rows, prior_nav, prior_cash = [], 1.0, 1.0
    gross_returns = (0.0, 0.02, -0.01) if model == "A2_HGB" else (0.0, 0.01, -0.005)
    for index, (day, gross) in enumerate(zip(("2025-12-02", "2025-12-03", "2025-12-04"), gross_returns)):
        turnover = 0.25 if index == 1 else 0.5
        pretrade = prior_nav * (1 + gross)
        cost = turnover * pretrade * 0.001
        nav = pretrade - cost
        cash = nav if index == 2 else 0.0
        rows.append({
            "execution_date": day, "model": model, "reconstruction_mode": "POSITION_LEDGER",
            "cash_before": prior_cash, "cash_after": cash, "pretrade_nav": pretrade,
            "reconstructed_nav": nav, "reconstructed_gross_return": gross,
            "reconstructed_daily_return": nav / prior_nav - 1,
            "target_turnover": turnover, "reconstructed_turnover": turnover,
            "reconstructed_transaction_cost": cost, "position_value": nav - cash,
            "actual_risky_name_count": 0 if index == 2 else 20,
            "stale_mark_count": 0, "skipped_buy_count": 0,
            "blocked_sell_or_rebalance_count": 0, "buy_cash_scale": 1.0,
            **{name: 0.0 for name in performance_reader._IDENTITY_FIELDS},
        })
        prior_nav, prior_cash = nav, cash
    return rows


@pytest.fixture
def performance_config(make_overview_config, make_artifact):
    def create(*, reference=True, mutate=None, mutate_reference=None):
        config = make_overview_config()
        rows = _execution_rows()
        if mutate:
            mutate(rows)
        daily = make_artifact(rows, name="performance_a2", date_columns=("execution_date",))
        ref = None
        if reference:
            ref_rows = _execution_rows("A1")
            if mutate_reference:
                mutate_reference(ref_rows)
            ref = make_artifact(ref_rows, name="performance_a", date_columns=("execution_date",))
        config = replace(config, daily=daily, reference_daily=ref)
        def bindings(items):
            for item in items:
                if item["artifact_id"] == "a2_returns":
                    item.update(absolute_path=str(daily.path), sha256=daily.sha256)
            if ref is not None:
                items.append({"artifact_id": "a_returns", "category": "A_RESULT", "role": "A_portfolio_daily",
                              "immutable": "True", "absolute_path": str(ref.path), "sha256": ref.sha256})
        config = _repin_hash_rows(config, bindings)
        def contracts(manifest):
            manifest["contracts"].update({
                "evaluation": {"cost_bps_round_trip": 10,
                               "signal_execution": "close signal -> next US equity session open",
                               "same_U_t": True, "same_cost_model": True, "same_portfolio_construction": True},
                "A": {"config_fingerprint": A_CONFIG_FINGERPRINT, "source_fingerprint": A_SOURCE_FINGERPRINT,
                      "coefficient_fingerprint": A_COEFFICIENT_FINGERPRINT,
                      "feature_schema_fingerprint": A_FEATURE_SCHEMA_FINGERPRINT,
                      "coefficients_fixed": True, "portfolio_mapping": "TOP20_EQUAL_WEIGHT_LONG_ONLY",
                      "score_direction": "descending", "ranking_tie_break": "ticker deterministic"},
            })
        return _repin_manifest(config, contracts)
    return create


def test_full_and_cutoff_preserve_entry_cost_terminal_row_and_archive_calendar(performance_config):
    config = performance_config()
    full = read_performance(config=config)
    assert full.error is full.reference_error is None
    assert full.reference_available and full.reference_identity == "A1"
    assert len(full.points) == 3 and full.initial_nav == 1.0
    assert full.available_dates == ("2025-12-02", "2025-12-03", "2025-12-04")
    assert (full.archive_start, full.archive_end, full.effective_end_date) == ("2025-12-02", "2025-12-04", "2025-12-04")
    assert full.points[0].net_return < 0 and full.points[0].gross_return == 0
    assert full.points[0].transaction_cost == 0.0005
    assert full.points[-1].holding_count == 0 and full.points[-1].cash == full.points[-1].nav
    assert full.points[1].reference_nav != full.points[1].nav
    cut = read_performance("2025-12-03", config)
    assert cut.points == full.points[:2] and cut.available_dates == full.available_dates
    assert cut.archive_end == full.archive_end and cut.effective_end_date == "2025-12-03"
    assert cut.requested_end_date == "2025-12-03"
    early = read_performance("2025-12-01", config)
    assert not early.points and early.error and early.archive_end == full.archive_end
    with pytest.raises(FrozenInstanceError):
        full.points[0].nav = 999


@pytest.mark.parametrize("end_date,code", [("2026-01-01", "POST2025_DATE_BLOCKED"),
                                           ("2027-03-01", "POST2025_DATE_BLOCKED"),
                                           ("not-a-date", "INVALID_DATE")])
def test_invalid_end_date_opens_no_input(monkeypatch, end_date, code):
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid cutoff reached file access")
    monkeypatch.setattr(Path, "open", forbidden)
    result = read_performance(end_date)
    assert not result.points and code in result.debug_error


@pytest.mark.parametrize("field,value,code", [
    ("reconstructed_nav", float("nan"), "INVALID_PERFORMANCE_NUMBER"),
    ("reconstructed_nav", 0.0, "INVALID_PERFORMANCE_NAV_OR_RETURN"),
    ("reconstructed_daily_return", -1.0, "INVALID_PERFORMANCE_NAV_OR_RETURN"),
    ("reconstructed_daily_return", 0.5, "PERFORMANCE_GROSS_NET_COST_MISMATCH"),
    ("reconstructed_turnover", 0.0, "PERFORMANCE_COST_RATE_MISMATCH"),
    ("NAV_ACCOUNTING_IDENTITY_ERROR", 0.01, "PERFORMANCE_RECORDED_ACCOUNTING_ERROR"),
    ("cash_after", 0.5, "PERFORMANCE_NAV_ACCOUNTING_MISMATCH"),
    ("cash_before", 0.5, "PERFORMANCE_CASH_CONTINUITY_MISMATCH"),
    ("stale_mark_count", -1, "INVALID_PERFORMANCE_NUMBER"),
    ("buy_cash_scale", 2.0, "INVALID_BUY_CASH_SCALE"),
    ("model", "UNBOUND_STRATEGY", "PERFORMANCE_MODEL_IDENTITY_MISMATCH"),
])
def test_invalid_a2_accounting_or_identity_fails_closed(performance_config, field, value, code):
    config = performance_config(mutate=lambda rows: rows[1].update({field: value}))
    result = read_performance(config=config)
    assert result.error and not result.points and not result.reference_available
    assert code in result.debug_error
    assert str(config.daily.path) not in result.error


@pytest.mark.parametrize("mutation,code", [
    (lambda rows: rows.reverse(), "PERFORMANCE_DATE_ORDER_OR_DUPLICATE"),
    (lambda rows: rows[1].update(execution_date=rows[0]["execution_date"]), "PERFORMANCE_DATE_ORDER_OR_DUPLICATE"),
    (lambda rows: rows[-1].update(actual_risky_name_count=20), "PERFORMANCE_TERMINAL_LIQUIDATION_MISSING"),
    (lambda rows: [row.pop("reconstructed_gross_return") for row in rows], "MISSING_COLUMNS"),
])
def test_invalid_archive_structure_is_not_silently_trimmed(performance_config, mutation, code):
    result = read_performance("2025-12-02", performance_config(mutate=mutation))
    assert result.error and not result.points and code in result.debug_error


def test_mixed_year_archive_is_rejected_before_hash_or_data_pages(performance_config, monkeypatch):
    config = performance_config(mutate=lambda rows: rows[-1].update(execution_date="2026-01-02"))
    raw = config.daily.path.read_bytes()  # Synthetic fixture, before interception.
    footer_start = len(raw) - 8 - struct.unpack("<I", raw[-8:-4])[0]
    spans, original_open = [], Path.open
    def watched(path, mode="r", *args, **kwargs):
        handle = original_open(path, mode, *args, **kwargs)
        return _ReadWatch(handle, spans) if path == config.daily.path else handle
    def forbidden(*args, **kwargs):
        raise AssertionError("Mixed-year performance reached a data page or full-file hash")
    monkeypatch.setattr(Path, "open", watched)
    monkeypatch.setattr(artifact_reader.hashlib, "file_digest", forbidden)
    monkeypatch.setattr(artifact_reader.pq, "ParquetFile", forbidden)
    result = read_performance("2025-12-02", config)
    assert result.error and "POST2025_ARTIFACT_BLOCKED" in result.debug_error
    assert spans and all(footer_start <= start <= end <= len(raw) for start, end in spans)


@pytest.mark.parametrize("date_columns,nullable", [((), ()), (("other_date",), ()),
                                                   (("execution_date",), ("execution_date",))])
def test_execution_date_boundary_cannot_be_replaced_by_another_column(performance_config, monkeypatch,
                                                                     date_columns, nullable):
    config = performance_config()
    config = replace(config, daily=replace(config.daily, date_columns=date_columns, nullable_date_columns=nullable))
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid temporal contract reached Parquet access")
    monkeypatch.setattr(performance_reader, "read_frozen_parquet", forbidden)
    result = read_performance(config=config)
    assert not result.points and "PERFORMANCE_EXECUTION_DATE_BOUNDARY_REQUIRED" in result.debug_error


def test_changed_data_bytes_cannot_inherit_the_frozen_identity(performance_config):
    config = performance_config()
    changed = bytearray(config.daily.path.read_bytes())
    changed[4] ^= 1  # Task-owned synthetic data page; preserve its footer.
    config.daily.path.write_bytes(changed)
    result = read_performance(config=config)
    assert result.error and not result.points and "ARTIFACT_IDENTITY_MISMATCH" in result.debug_error


@pytest.mark.parametrize("failure", ["model", "calendar", "accounting", "contract", "comparison", "role", "missing"])
def test_reference_failures_only_degrade_reference(performance_config, monkeypatch, failure):
    mutation = None
    if failure == "model":
        mutation = lambda rows: rows[0].update(model="A2_HGB")
    elif failure == "calendar":
        mutation = lambda rows: rows[0].update(execution_date="2025-12-01")
    elif failure == "accounting":
        mutation = lambda rows: rows[1].update(reconstructed_daily_return=0.75)
    config = performance_config(mutate_reference=mutation)
    if failure == "contract":
        config = _repin_manifest(config, lambda m: m["contracts"]["A"].update(coefficients_fixed=False))
    elif failure == "comparison":
        config = _repin_manifest(config, lambda m: m["contracts"]["evaluation"].update(same_cost_model=False))
    elif failure == "role":
        config = _repin_hash_rows(config, lambda rows: rows[-1].update(category="A2_RESULT"))
    elif failure == "missing":
        original = performance_reader.read_frozen_parquet
        def missing(spec, *args, **kwargs):
            if spec == config.reference_daily:
                raise FileNotFoundError(f"Synthetic private source: {spec.path}")
            return original(spec, *args, **kwargs)
        monkeypatch.setattr(performance_reader, "read_frozen_parquet", missing)
    result = read_performance(config=config)
    assert result.error is None and len(result.points) == 3
    assert not result.reference_available and result.reference_error and result.reference_debug_error
    assert all(point.reference_nav is point.reference_net_return is None for point in result.points)
    assert str(config.reference_daily.path) not in result.reference_error
    assert str(config.reference_daily.path) not in {path for path, _ in result.source_refs}


def test_missing_optional_reference_keeps_primary_performance(performance_config):
    result = read_performance(config=performance_config(reference=False))
    assert result.error is None and len(result.points) == 3
    assert not result.reference_available and result.reference_debug_error is None


def test_performance_reads_only_bound_inputs_and_preserves_original_bytes(performance_config, monkeypatch):
    config = performance_config()
    paths = (config.manifest_path, config.hash_manifest_path, config.daily.path, config.reference_daily.path)
    before = {path: path.read_bytes() for path in paths}
    opened, original_open = [], Path.open
    def guarded(path, mode="r", *args, **kwargs):
        assert path in paths, f"Unrelated source accessed: {path}"
        assert mode == "rb"
        opened.append(path)
        return original_open(path, mode, *args, **kwargs)
    with monkeypatch.context() as guard:
        guard.setattr(Path, "open", guarded)
        result = read_performance(config=config)
    assert result.error is None and result.reference_available
    assert set(opened) == set(paths)
    assert config.ranking.path not in opened and config.positions.path not in opened
    assert {path: path.read_bytes() for path in paths} == before
