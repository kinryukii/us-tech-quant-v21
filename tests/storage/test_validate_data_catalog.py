"""Synthetic catalog acceptance tests; no broker, research outcome, or live data."""
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.storage.build_data_catalog import SCHEMA, register_file
from scripts.storage.storage_r2a import DataStore, StoragePaths, sha256
from scripts.storage.validate_data_catalog import validate_catalog


@pytest.fixture
def store(tmp_path):
    paths = StoragePaths(**{name: tmp_path / name for name in (
        "repo_root", "data_root", "cache_root", "daily_root", "backtest_root", "results_root", "envs_root")})
    value = DataStore(paths)
    value.catalog_path.parent.mkdir(parents=True)
    with sqlite3.connect(value.catalog_path) as connection:
        connection.executescript(SCHEMA)
        connection.executemany("INSERT INTO catalog_metadata VALUES (?,?)", [
            ("schema_version", "1"), ("catalog_role", "REBUILDABLE_FILE_INDEX")])
    return value


def add_price(store, ticker="ABC", adjustment="raw", dates=None, mutate=None):
    dates = dates or ["2026-09-09", "2026-09-10", "2026-09-11"]
    source = store.paths.cache_root / "source" / f"{ticker}_{adjustment}.csv"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(f"synthetic original source,{ticker},{adjustment}\n", encoding="utf-8")
    source_hash = sha256(source)
    frame = pd.DataFrame({"ticker": ticker, "date": dates, "open": 10., "high": 12., "low": 9.,
                          "close": 11., "volume": 100., "turnover": 1100., "adjustment": adjustment,
                          "source": "MOOMOO_OPEND", "provider_code": "US." + ticker,
                          "source_id": source_hash, "observed_at": "2026-09-12T00:00:00Z"})
    if mutate:
        frame = mutate(frame)
    path = store.paths.data_root / "stocks" / ticker / f"daily_{adjustment}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    with sqlite3.connect(store.catalog_path) as connection:
        connection.execute("INSERT INTO source_files VALUES (?,?,?,?,?)", (str(source), source_hash,
                           source.stat().st_size, "READ_VALIDATED", ""))
        register_file(connection, "prices_daily", ticker, adjustment, path, len(frame),
                      str(frame.date.min()), str(frame.date.max()), "MOOMOO_OPEND",
                      {"inputs": [{"path": str(source), "sha256": source_hash}]})
    return path, source


def errors(report):
    return [error for item in report["files"] for error in item["errors"]]


def test_pass_checks_content_and_lineage_without_changing_files(store):
    raw, source = add_price(store)
    qfq, _ = add_price(store, adjustment="qfq")
    hashes = {path: sha256(path) for path in [raw, qfq, source, store.catalog_path]}
    report = validate_catalog(store, "2026-09-11")
    assert report["integrity_status"] == "PASS"
    assert report["coverage_status"] == "OBSERVED_SESSIONS_COVERED_LIFECYCLE_UNVERIFIED"
    assert report["raw_qfq_differences"] == []
    assert report["referenced_source_files_checked"] == 2
    assert all(sha256(path) == digest for path, digest in hashes.items())
    json.dumps(report, allow_nan=False)


def test_session_gaps_ignore_labor_day_and_do_not_assume_delisting(store):
    add_price(store, dates=["2026-09-04", "2026-09-08", "2026-09-10"])
    report = validate_catalog(store, "2026-09-11")
    coverage = report["files"][0]["coverage"]
    assert report["integrity_status"] == "PASS"
    assert coverage["potential_internal_missing_sessions"] == 1
    assert coverage["potential_internal_missing_spans"] == [{"start": "2026-09-09", "end": "2026-09-09", "sessions": 1}]
    assert coverage["potential_tail_missing_sessions"] == 1
    assert coverage["lifecycle_status"] == "UNKNOWN"
    assert coverage["leading_history_before_first_observation"] == "NOT_INFERRED"


def test_hash_failure_does_not_read_replacement_prices(store, monkeypatch):
    path, _ = add_price(store)
    with path.open("ab") as handle:
        handle.write(b"synthetic replacement")
    monkeypatch.setattr(store, "_read_parquet", lambda *args: pytest.fail("unverified bytes read"))
    report = validate_catalog(store, "2026-09-11")
    assert "SELECTED_FILE_SHA256_MISMATCH" in errors(report)
    assert report["integrity_status"] == "FAIL"


@pytest.mark.parametrize("mutation,issue", [
    (lambda f: pd.concat([f, f.iloc[:1]], ignore_index=True), "DUPLICATE_TICKER_DATE_ADJUSTMENT"),
    (lambda f: f.assign(volume=np.inf), "INVALID_OHLCV"),
    (lambda f: f.assign(high=8.), "INVALID_OHLCV"),
    (lambda f: f.assign(ticker="OTHER"), "CATALOG_FILE_IDENTITY_MISMATCH"),
    (lambda f: f.assign(source="UNVERIFIED_PROVIDER"), "UNVERIFIED_MARKET_SOURCE"),
    (lambda f: f.assign(provider_code="BAD"), "INVALID_PROVIDER_CODE"),
    (lambda f: f.assign(source_id="unregistered"), "ROW_SOURCE_ID_LINEAGE_MISMATCH"),
    (lambda f: f.drop(columns=["observed_at"]), "PRICE_SCHEMA_MISSING_COLUMNS:observed_at"),
])
def test_corrupt_content_cannot_pass_matching_catalog_hash(store, mutation, issue):
    add_price(store, mutate=mutation)
    report = validate_catalog(store, "2026-09-11")
    assert report["integrity_status"] == "FAIL"
    assert issue in errors(report)


def test_mutated_lineage_source_fails_even_when_selected_prices_are_intact(store):
    _, source = add_price(store)
    source.write_text("changed synthetic source", encoding="utf-8")
    report = validate_catalog(store, "2026-09-11")
    assert report["integrity_status"] == "FAIL"
    assert any("source file SHA-256 mismatch" in error for error in errors(report))


def test_duplicate_keys_are_checked_after_date_normalization(store):
    def duplicate_day(frame):
        additional = frame.iloc[:1].copy()
        additional["date"] = "2026-09-09T00:00:00"
        return pd.concat([frame, additional], ignore_index=True)

    add_price(store, mutate=duplicate_day)
    report = validate_catalog(store, "2026-09-11")
    assert "DUPLICATE_TICKER_DATE_ADJUSTMENT" in errors(report)


def test_selected_file_mutation_during_read_is_detected(store, monkeypatch):
    path, _ = add_price(store)
    original = store._read_parquet

    def reader(*args):
        frame = original(*args)
        with path.open("ab") as handle:
            handle.write(b"synthetic concurrent mutation")
        return frame

    monkeypatch.setattr(store, "_read_parquet", reader)
    report = validate_catalog(store, "2026-09-11")
    assert "SELECTED_FILE_CHANGED_DURING_VALIDATION" in errors(report)


def test_raw_qfq_missing_leg_and_date_differences_are_reported_without_fill(store):
    raw, _ = add_price(store)
    add_price(store, adjustment="qfq", dates=["2026-09-10", "2026-09-11"])
    original = sha256(raw)
    report = validate_catalog(store, "2026-09-11")
    difference = report["raw_qfq_differences"][0]
    assert difference["raw_only_date_count"] == 1
    assert difference["qfq_only_date_count"] == 0
    assert sha256(raw) == original


def test_support_metadata_checked_without_loading_other_columns(store, monkeypatch):
    add_price(store)
    path = store.paths.results_root / "support.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame({"filed_date": ["2026-09-11"], "unrelated_payload": ["do not load"]}).to_parquet(path)
    with sqlite3.connect(store.catalog_path) as connection:
        register_file(connection, "sec_submissions", "", "", path, 1, "2026-09-11", "2026-09-11",
                      "EXISTING_LOCAL_SOURCE", {"date_column": "filed_date"})
    original = store._read_parquet

    def reader(selected, start, end, columns, *args):
        if selected == path:
            assert columns == ["filed_date"]
        return original(selected, start, end, columns, *args)

    monkeypatch.setattr(store, "_read_parquet", reader)
    assert validate_catalog(store, "2026-09-11")["integrity_status"] == "PASS"


def test_invalid_catalog_and_empty_catalog_are_not_success(store):
    assert validate_catalog(store, "2026-09-11")["integrity_status"] == "FAIL"
    with sqlite3.connect(store.catalog_path) as connection:
        connection.execute("UPDATE catalog_metadata SET value='unsupported' WHERE key='schema_version'")
    report = validate_catalog(store, "2026-09-11")
    assert report["errors"][0]["issue"] == "CATALOG_UNREADABLE_OR_INVALID"


def add_provider(store, ticker="ABC", provider_symbol=None, mutate=None, lineage_updates=None, adjustment=None, provider="yahoo"):
    source_label, default_adjustment, price_basis = {"yahoo": ("YAHOO_CHART", "split_adjusted", "SPLIT_ADJUSTED"),
                                                    "massive": ("MASSIVE_GROUPED", "raw", "RAW")}[provider]
    adjustment = adjustment or default_adjustment
    provider_symbol = provider_symbol or ticker
    source = store.paths.cache_root / provider / f"{ticker}.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(json.dumps({"synthetic_provider_symbol": provider_symbol}), encoding="utf-8")
    digest = sha256(source)
    inputs = [{"path": str(source), "sha256": digest}]
    source_ids, observations = [digest] * 3, ["2026-09-12T00:00:00Z"] * 3
    if provider == "massive":
        for index in (1, 2):
            grouped = source.with_name(f"{ticker}_{index}.json")
            grouped.write_text(json.dumps({"synthetic_provider_symbol": provider_symbol, "day_offset": index}), encoding="utf-8")
            source_ids[index] = sha256(grouped)
            observations[index] = f"2026-09-12T00:0{index}:00Z"
            inputs.append({"path": str(grouped), "sha256": source_ids[index]})
    frame = pd.DataFrame({"ticker": [ticker] * 3, "date": ["2026-09-09", "2026-09-10", "2026-09-11"],
                          "open": 10., "high": 12., "low": 9., "close": 11., "volume": 100., "turnover": None,
                          "adjustment": adjustment, "source": source_label,
                          "provider_code": provider_symbol, "source_id": source_ids, "observed_at": observations})
    if provider == "yahoo":
        frame["adjusted_close"] = 7.
    if mutate:
        frame = mutate(frame)
    path = store.paths.data_root / "providers" / provider / f"{ticker}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    lineage = {"schema_version": 1, "role": "PROVIDER_DAILY_PRICE_SNAPSHOT", "provider": source_label,
               "date_column": "date", "price_basis": price_basis, "currency": "USD",
               "exchange_timezone": "America/New_York", "provider_symbol": provider_symbol,
               "vintage_semantics": "CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT",
               "inputs": inputs, **(lineage_updates or {})}
    with sqlite3.connect(store.catalog_path) as connection:
        for item in inputs:
            connection.execute("INSERT INTO source_files VALUES (?,?,?,?,?)", (item["path"], item["sha256"], Path(item["path"]).stat().st_size, "READ_VALIDATED", ""))
        register_file(connection, f"prices_daily_{provider}", ticker, adjustment, path, len(frame),
                      str(frame.date.min()), str(frame.date.max()), source_label, lineage)
    return path, source


def test_yahoo_is_fully_validated_and_never_replaces_moomoo_coverage(store):
    raw, _ = add_price(store)
    qfq, _ = add_price(store, adjustment="qfq")
    original = {path: sha256(path) for path in (raw, qfq)}
    add_provider(store)
    add_provider(store, ticker="ONLYYAHOO")
    add_provider(store, provider="massive", provider_symbol="ABC.A")
    report = validate_catalog(store, "2026-09-11")
    assert report["integrity_status"] == "PASS"
    assert report["raw_qfq_differences"] == []
    assert report["adjustments"]["raw"]["selected_files"] == 1
    assert report["supplemental_price_datasets"]["prices_daily_yahoo"]["target_session_present"] == 2
    assert report["supplemental_price_datasets"]["prices_daily_massive"]["target_session_present"] == 1
    assert store.metadata("prices_daily", "ABC", "raw")["path"] == str(raw)
    assert all(sha256(path) == digest for path, digest in original.items())
    assert store.daily("ABC", "split_adjusted", provider="yahoo").close.tolist() == [11.] * 3
    assert store.daily("ABC", "split_adjusted", provider="yahoo").adjusted_close.tolist() == [7.] * 3
    massive = store.daily("ABC", "raw", provider="massive")
    assert "adjusted_close" not in massive
    assert massive.provider_code.unique().tolist() == ["ABC.A"]
    assert massive.source_id.nunique() == 3 and massive.observed_at.nunique() == 3


@pytest.mark.parametrize("mutation,issue", [
    (lambda f: f.assign(high=8.), "INVALID_OHLCV"),
    (lambda f: f.assign(volume=np.inf), "INVALID_OHLCV"),
    (lambda f: pd.concat([f, f.iloc[:1]], ignore_index=True), "DUPLICATE_TICKER_DATE_ADJUSTMENT"),
    (lambda f: f.assign(source="MOOMOO_OPEND"), "UNVERIFIED_MARKET_SOURCE"),
    (lambda f: f.assign(provider_code="US.ABC"), "PROVIDER_CODE_DIFFERS_FROM_RETURNED_META_SYMBOL"),
    (lambda f: f.assign(ticker="OTHER"), "CATALOG_FILE_IDENTITY_MISMATCH"),
    (lambda f: f.assign(adjusted_close=-1.), "INVALID_AUXILIARY_ADJUSTED_CLOSE"),
    (lambda f: f.assign(adjusted_close="7"), "PRICE_SCHEMA_NONNUMERIC:adjusted_close"),
    (lambda f: f.drop(columns=["adjusted_close"]), "PRICE_SCHEMA_MISSING_COLUMNS:adjusted_close"),
    (lambda f: f.assign(source_id="unregistered"), "ROW_SOURCE_ID_LINEAGE_MISMATCH"),
    (lambda f: f.assign(observed_at=None), "YAHOO_RETRIEVAL_TIMESTAMP_MISSING_OR_INVALID"),
    (lambda f: f.assign(observed_at=123), "YAHOO_RETRIEVAL_TIMESTAMP_REQUIRES_EXPLICIT_TIMEZONE"),
    (lambda f: f.assign(observed_at="2026-09-12T00:00:00"), "YAHOO_RETRIEVAL_TIMESTAMP_REQUIRES_EXPLICIT_TIMEZONE"),
])
def test_yahoo_does_not_bypass_price_or_lineage_validation(store, mutation, issue):
    add_provider(store, mutate=mutation)
    report = validate_catalog(store, "2026-09-11")
    assert issue in errors(report)


@pytest.mark.parametrize("updates", [{"price_basis": "QFQ"}, {"provider": "UNKNOWN"}, {"schema_version": 2},
                                     {"currency": "HKD"}, {"exchange_timezone": "UTC"},
                                     {"vintage_semantics": "PIT_SAFE"}, {"inputs": []}])
def test_yahoo_metadata_conflicts_fail_before_price_payload_read(store, monkeypatch, updates):
    add_provider(store, lineage_updates=updates)
    monkeypatch.setattr(store, "_read_parquet", lambda *args, **kwargs: pytest.fail("unverified provider payload read"))
    report = validate_catalog(store, "2026-09-11")
    assert any("FILE_VALIDATION_FAILED:" in issue for issue in errors(report))


def test_yahoo_wrong_adjustment_and_mutated_raw_response_fail(store):
    _, source = add_provider(store, adjustment="qfq")
    assert any("catalog source/adjustment/format" in issue for issue in errors(validate_catalog(store, "2026-09-11")))
    with sqlite3.connect(store.catalog_path) as connection:
        connection.execute("DELETE FROM data_files WHERE dataset='prices_daily_yahoo'")
        connection.execute("DELETE FROM source_files WHERE path=?", (str(source),))
    _, source = add_provider(store)
    source.write_text("changed synthetic response", encoding="utf-8")
    assert any("SOURCE_LINEAGE_INVALID:" in issue for issue in errors(validate_catalog(store, "2026-09-11")))


@pytest.mark.parametrize("mutation,issue", [
    (lambda f: f.assign(high=8.), "INVALID_OHLCV"),
    (lambda f: f.assign(volume=np.inf), "INVALID_OHLCV"),
    (lambda f: f.assign(open="10"), "PRICE_SCHEMA_NONNUMERIC:open"),
    (lambda f: pd.concat([f, f.iloc[:1]], ignore_index=True), "DUPLICATE_TICKER_DATE_ADJUSTMENT"),
    (lambda f: f.assign(date="2026-09-11T01:00:00"), "INVALID_DAILY_DATES"),
    (lambda f: f.assign(source="YAHOO_CHART"), "UNVERIFIED_MARKET_SOURCE"),
    (lambda f: f.assign(provider_code="US.ABC"), "PROVIDER_CODE_DIFFERS_FROM_RETURNED_META_SYMBOL"),
    (lambda f: f.assign(adjustment="qfq"), "CATALOG_FILE_IDENTITY_MISMATCH"),
    (lambda f: f.assign(ticker="OTHER"), "CATALOG_FILE_IDENTITY_MISMATCH"),
    (lambda f: f.assign(source_id=f.source_id.iloc[0]), "ROW_SOURCE_ID_LINEAGE_MISMATCH"),
    (lambda f: f.assign(observed_at=None), "MASSIVE_RETRIEVAL_TIMESTAMP_MISSING_OR_INVALID"),
    (lambda f: f.assign(observed_at=123), "MASSIVE_RETRIEVAL_TIMESTAMP_REQUIRES_EXPLICIT_TIMEZONE"),
    (lambda f: f.assign(observed_at="2026-09-12T00:00:00"), "MASSIVE_RETRIEVAL_TIMESTAMP_REQUIRES_EXPLICIT_TIMEZONE"),
])
def test_massive_reuses_strict_full_price_and_per_day_lineage_validation(store, mutation, issue):
    add_provider(store, provider="massive", mutate=mutation)
    assert issue in errors(validate_catalog(store, "2026-09-11"))


@pytest.mark.parametrize("updates", [{"price_basis": "SPLIT_ADJUSTED"}, {"provider": "YAHOO_CHART"},
                                     {"schema_version": 2}, {"currency": "HKD"}, {"exchange_timezone": "UTC"},
                                     {"vintage_semantics": "PIT_SAFE"}, {"inputs": []}, {"provider_symbol": "../ABC"}])
def test_massive_metadata_conflicts_fail_before_price_payload_read(store, monkeypatch, updates):
    add_provider(store, provider="massive", lineage_updates=updates)
    monkeypatch.setattr(store, "_read_parquet", lambda *args, **kwargs: pytest.fail("unverified provider payload read"))
    assert any("FILE_VALIDATION_FAILED:" in issue for issue in errors(validate_catalog(store, "2026-09-11")))


def test_massive_rejects_adjusted_catalog_basis_and_changed_grouped_response(store):
    _, source = add_provider(store, provider="massive", adjustment="split_adjusted")
    assert any("catalog source/adjustment/format" in issue for issue in errors(validate_catalog(store, "2026-09-11")))
    with sqlite3.connect(store.catalog_path) as connection:
        connection.execute("UPDATE data_files SET adjustment='raw' WHERE dataset='prices_daily_massive'")
    source.write_text("changed synthetic grouped response", encoding="utf-8")
    issues = errors(validate_catalog(store, "2026-09-11"))
    assert any("SOURCE_LINEAGE_INVALID:" in issue for issue in issues)
