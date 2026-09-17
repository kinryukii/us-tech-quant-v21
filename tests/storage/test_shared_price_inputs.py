"""Shared Massive lineage uses exact subsets and never bypasses source validation."""
import json
import sqlite3
from collections import Counter
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds
import pytest

from scripts.storage import storage_r2a, validate_data_catalog as validator
from scripts.storage.build_data_catalog import SCHEMA, register_file
from scripts.storage.storage_r2a import DataStore, StoragePaths, sha256


@pytest.fixture
def store(tmp_path):
    paths = StoragePaths(**{name: tmp_path / name for name in storage_r2a._resolver.DEFAULTS})
    value = DataStore(paths)
    value.catalog_path.parent.mkdir(parents=True)
    with sqlite3.connect(value.catalog_path) as connection:
        connection.executescript(SCHEMA)
        connection.executemany("INSERT INTO catalog_metadata VALUES (?,?)", [
            ("schema_version", "1"), ("catalog_role", "REBUILDABLE_FILE_INDEX")])
    return value


def add_shared(store, *, ticker="ABC", indexes=None):
    inputs = []
    for index, day in enumerate(["2026-09-09", "2026-09-10", "2026-09-11"]):
        path = store.paths.cache_root / "massive" / f"{day}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"status": "OK", "date": day, "results": []}), encoding="utf-8")
        inputs.append({"path": str(path), "sha256": sha256(path), "date": day,
                       "observed_at": f"2026-09-13T00:0{index}:00Z"})
    manifest = {"schema_version": 1, "role": "RAW_INPUT_MANIFEST", "provider": "MASSIVE_GROUPED", "inputs": inputs}
    manifest_path = store.paths.data_root / "shared_inputs" / "inputs.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    reference = {"path": str(manifest_path), "sha256": sha256(manifest_path)}
    if indexes is not None:
        reference["indexes"] = indexes
    selected = inputs if indexes is None else [inputs[index] for index in indexes]
    frame = pd.DataFrame({"ticker": ticker, "date": [item["date"] for item in selected],
                          "open": 10., "high": 12., "low": 9., "close": 11., "volume": 100.,
                          "turnover": None, "adjustment": "raw", "source": "MASSIVE_GROUPED", "provider_code": ticker,
                          "source_id": [item["sha256"] for item in selected],
                          "observed_at": [item["observed_at"] for item in selected]})
    path = store.paths.data_root / "prices" / f"{ticker}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    lineage = {"schema_version": 1, "role": "PROVIDER_DAILY_PRICE_SNAPSHOT", "provider": "MASSIVE_GROUPED",
               "date_column": "date", "price_basis": "RAW", "currency": "USD",
               "exchange_timezone": "America/New_York", "provider_symbol": ticker,
               "vintage_semantics": "CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT", "inputs_manifest": reference}
    with sqlite3.connect(store.catalog_path) as connection:
        for item in inputs:
            connection.execute("INSERT OR IGNORE INTO source_files VALUES (?,?,?,?,?)", (
                item["path"], item["sha256"], Path(item["path"]).stat().st_size, "READ_VALIDATED", ""))
        register_file(connection, "prices_daily_massive", ticker, "raw", path, len(frame),
                      frame.date.min(), frame.date.max(), "MASSIVE_GROUPED", lineage)
    return path, manifest_path, manifest


def update_lineage(store, mutate, ticker="ABC"):
    row = store._catalog_rows("prices_daily_massive", ticker, "raw")[0]
    lineage = json.loads(row["lineage_json"])
    mutate(lineage)
    with sqlite3.connect(store.catalog_path) as connection:
        connection.execute("UPDATE data_files SET lineage_json=? WHERE dataset='prices_daily_massive' AND ticker=?",
                           (json.dumps(lineage), ticker))


def update_manifest(store, path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    update_lineage(store, lambda lineage: lineage["inputs_manifest"].update(sha256=sha256(path)))


def test_shared_read_checks_manifest_and_price_but_does_not_hash_raw(store, monkeypatch):
    path, manifest_path, manifest = add_shared(store)
    hashes = {value: sha256(value) for value in (path, manifest_path, store.catalog_path)}
    raw_paths = {Path(item["path"]) for item in manifest["inputs"]}
    original_hash, original_dataset = storage_r2a.sha256, ds.dataset
    converted = []

    def checked_hash(value):
        assert Path(value) not in raw_paths, "routine reads must not hash all-market raw responses"
        return original_hash(value)

    class Proxy:
        def __init__(self, wrapped):
            self.wrapped, self.schema, self.files = wrapped, wrapped.schema, wrapped.files
        def to_table(self, **kwargs):
            assert kwargs["filter"] is not None
            table = self.wrapped.to_table(**kwargs)
            converted.append(table.num_rows)
            return table

    monkeypatch.setattr(storage_r2a, "sha256", checked_hash)
    monkeypatch.setattr(ds, "dataset", lambda *args, **kwargs: Proxy(original_dataset(*args, **kwargs)))
    frame = store.daily("ABC", "raw", "2026-09-11", "2026-09-11", ["close"], provider="massive")
    assert frame.close.tolist() == [11.] and converted == [1]
    assert all(sha256(value) == digest for value, digest in hashes.items())


def test_selected_subset_deep_verification_and_unmodified_inline_compatibility(store):
    _, _, manifest = add_shared(store, indexes=[1, 2])
    row = store.metadata("prices_daily_massive", "ABC", "raw")
    assert store.resolve_price_inputs(row) == manifest["inputs"][1:]
    # The global manifest can contain a day on which this ticker has no price.
    Path(manifest["inputs"][0]["path"]).write_text("unselected changed raw", encoding="utf-8")
    assert store.resolve_price_inputs(row) == manifest["inputs"][1:]
    Path(manifest["inputs"][1]["path"]).write_text("selected changed raw", encoding="utf-8")
    assert store.daily("ABC", "raw", provider="massive").shape[0] == 2
    with pytest.raises(ValueError, match="raw-input file SHA-256 mismatch"):
        store.resolve_price_inputs(row)


@pytest.mark.parametrize("updates", [
    {"indexes": []}, {"indexes": [True]}, {"indexes": [-1]}, {"indexes": [0, 0]},
    {"indexes": [2, 1]}, {"indexes": [3]}, {"indexes": "all"}, {"sha256": "broken"},
    {"path": "relative.json"}, {"nested_manifest": {}},
])
def test_invalid_manifest_reference_cannot_reach_prices(store, monkeypatch, updates):
    add_shared(store)
    update_lineage(store, lambda lineage: lineage["inputs_manifest"].update(updates))
    monkeypatch.setattr(store, "_read_parquet", lambda *args, **kwargs: pytest.fail("unverified prices read"))
    with pytest.raises(ValueError):
        store.daily("ABC", "raw", provider="massive")


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(schema_version=True),
    lambda value: value.update(provider="YAHOO_CHART"),
    lambda value: value.update(role="PIT_SAFE"),
    lambda value: value.update(inputs=[]),
    lambda value: value["inputs"][0].update(inputs_manifest={"path": "cycle.json"}),
    lambda value: value["inputs"][0].update(observed_at="2026-09-13T00:00:00"),
    lambda value: value["inputs"][0].update(date="2026-02-30"),
    lambda value: value["inputs"].append(dict(value["inputs"][0])),
])
def test_invalid_leaf_manifest_is_rejected_even_with_matching_manifest_hash(store, mutation):
    _, path, manifest = add_shared(store)
    mutation(manifest)
    update_manifest(store, path, manifest)
    with pytest.raises(ValueError):
        store.metadata("prices_daily_massive", "ABC", "raw")


@pytest.mark.parametrize("case", ["mixed", "cycle", "outside_leaf", "outside_manifest", "unsupported_provider"])
def test_shared_manifest_never_adds_recursion_or_expands_allowed_paths(store, case):
    _, path, manifest = add_shared(store)
    if case == "mixed":
        update_lineage(store, lambda lineage: lineage.update(inputs=[]))
    elif case in {"cycle", "outside_leaf"}:
        manifest["inputs"][0]["path"] = str(path if case == "cycle" else store.paths.repo_root / "raw.json")
        update_manifest(store, path, manifest)
    elif case == "outside_manifest":
        update_lineage(store, lambda lineage: lineage["inputs_manifest"].update(path=str(store.paths.repo_root / "manifest.json")))
    else:
        with sqlite3.connect(store.catalog_path) as connection:
            connection.execute("UPDATE data_files SET dataset='prices_daily_yahoo'")
    with pytest.raises(ValueError):
        store.metadata("prices_daily_yahoo" if case == "unsupported_provider" else "prices_daily_massive", "ABC", "raw")


@pytest.mark.parametrize("changed", ["manifest", "price"])
def test_manifest_and_selected_price_are_checked_again_after_query(store, monkeypatch, changed):
    path, manifest_path, _ = add_shared(store)
    original_read = store._read_parquet

    def reader(*args, **kwargs):
        frame = original_read(*args, **kwargs)
        with (manifest_path if changed == "manifest" else path).open("ab") as handle:
            handle.write(b" ")
        return frame

    monkeypatch.setattr(store, "_read_parquet", reader)
    with pytest.raises(ValueError, match="SHA-256 mismatch|changed during read"):
        store.daily("ABC", "raw", provider="massive")


def test_full_validation_checks_registered_raw_once_across_exact_ticker_subsets(store, monkeypatch):
    _, _, manifest = add_shared(store)
    add_shared(store, ticker="IPO", indexes=[2])
    calls = Counter()
    original = validator.sha256
    raw_paths = {Path(item["path"]) for item in manifest["inputs"]}

    def count_hash(path):
        if Path(path) in raw_paths:
            calls[Path(path)] += 1
        return original(path)

    monkeypatch.setattr(validator, "sha256", count_hash)
    report = validator.validate_catalog(store, "2026-09-11")
    assert not any(item["errors"] for item in report["files"])
    assert report["shared_raw_input_manifests_checked"] == 1
    assert report["referenced_source_files_checked"] == 3
    assert calls == Counter({path: 1 for path in raw_paths})
    assert len(report["files"]) == 2


@pytest.mark.parametrize("case,expected", [
    ("raw", "SOURCE_LINEAGE_INVALID:"), ("registry", "SOURCE_ID_NOT_IN_VALID_SOURCE_REGISTRY:"),
    ("source_set", "ROW_SOURCE_ID_LINEAGE_MISMATCH"),
    ("source_date", "ROW_SOURCE_DATE_LINEAGE_MISMATCH"),
    ("observed_at", "ROW_SOURCE_OBSERVATION_LINEAGE_MISMATCH"),
])
def test_shared_resolution_preserves_full_source_and_row_checks(store, case, expected):
    path, _, manifest = add_shared(store)
    if case == "raw":
        Path(manifest["inputs"][0]["path"]).write_text("changed raw", encoding="utf-8")
    elif case == "registry":
        with sqlite3.connect(store.catalog_path) as connection:
            connection.execute("DELETE FROM source_files")
    elif case == "source_set":
        update_lineage(store, lambda lineage: lineage["inputs_manifest"].update(indexes=[0, 1]))
    else:
        frame = pd.read_parquet(path)
        column = "source_id" if case == "source_date" else "observed_at"
        frame[column] = frame[column].iloc[::-1].tolist()
        frame.to_parquet(path, index=False)
        with sqlite3.connect(store.catalog_path) as connection:
            connection.execute("UPDATE data_files SET source_sha256=?", (sha256(path),))
    report = validator.validate_catalog(store, "2026-09-11")
    assert any(expected in error for item in report["files"] for error in item["errors"])
