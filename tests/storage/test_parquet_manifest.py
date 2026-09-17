"""Synthetic fragment identity, schema promotion and predicate checks."""
import json
import sqlite3

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import pytest

from scripts.storage.build_data_catalog import SCHEMA, register_file
from scripts.storage.build_parquet_manifest import load_manifest, prepare
from scripts.storage.storage_r2a import DataStore, StoragePaths, sha256
from scripts.storage.validate_data_catalog import validate_catalog


@pytest.fixture
def store(tmp_path):
    store = DataStore(StoragePaths(**{name: tmp_path / name for name in (
        "repo_root", "data_root", "cache_root", "daily_root", "backtest_root", "results_root", "envs_root")}))
    store.catalog_path.parent.mkdir(parents=True)
    with sqlite3.connect(store.catalog_path) as connection:
        connection.executescript(SCHEMA)
        connection.executemany("INSERT INTO catalog_metadata VALUES (?,?)", [
            ("schema_version", "1"), ("catalog_role", "REBUILDABLE_FILE_INDEX")])
    return store


def fragment(store, name, stamp, *, unit="us", tz="UTC", large=False, symbol="QQQ", number_type=pa.float64()):
    path = store.paths.data_root / "minute" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    instant = pd.Timestamp(stamp)
    instant = instant.tz_localize(tz) if tz else instant
    pq.write_table(pa.table({
        "symbol": pa.array([symbol], type=pa.large_string() if large else pa.string()),
        "timestamp_utc": pa.array([instant], type=pa.timestamp(unit, tz)),
        "close": pa.array([10], type=number_type),
        "source": ["moomoo_opend"], "adjustment_type": ["NONE"],
    }), path)
    return path


def build(store, files):
    return prepare(store, files, store.paths.results_root / "minute_manifests",
                   dataset="prices_intraday_1m", ticker="QQQ", adjustment="raw",
                   date_column="timestamp_utc", ticker_column="symbol", source="MOOMOO_OPEND",
                   expected_values={"symbol": "QQQ", "source": "moomoo_opend", "adjustment_type": "NONE"})


def register(store, result):
    with sqlite3.connect(store.catalog_path) as connection:
        register_file(connection, **result["catalog_record"])


def test_mixed_resolution_and_string_width_promote_without_rewriting(store, monkeypatch):
    old = fragment(store, "old.parquet", "2025-12-31 14:30:00")
    new = fragment(store, "new.parquet", "2026-09-11 14:30:00.000000001", unit="ns", large=True)
    original = {path: sha256(path) for path in (old, new, store.catalog_path)}
    result = build(store, [old, new])
    assert all(sha256(path) == digest for path, digest in original.items())
    assert build(store, [new, old]) == result
    register(store, result)
    actual_dataset = ds.dataset
    calls = []

    class Proxy:
        def __init__(self, dataset):
            self.dataset, self.schema, self.files = dataset, dataset.schema, dataset.files
        def to_table(self, **kwargs):
            assert kwargs["filter"] is not None
            table = self.dataset.to_table(**kwargs)
            calls.append(table.num_rows)
            return table

    monkeypatch.setattr(ds, "dataset", lambda *a, **kw: Proxy(actual_dataset(*a, **kw)))
    data = store.read("prices_intraday_1m", "QQQ", "raw", "2026-09-11T14:30:00.000000001Z",
                      "2026-09-11T14:30:00.000000001Z", columns=["symbol", "timestamp_utc"])
    assert calls == [1]
    assert data.timestamp_utc.iloc[0].nanosecond == 1
    assert data.symbol.tolist() == ["QQQ"]
    assert all(sha256(path) == original[path] for path in (old, new))


@pytest.mark.parametrize("kwargs,pattern", [
    ({"tz": None}, "timezone conflict"),
    ({"tz": "America/New_York"}, "timezone conflict"),
    ({"number_type": pa.int64()}, "incompatible fragment schema"),
    ({"symbol": "WRONG"}, "identity/source contract mismatch"),
])
def test_conflicting_schemas_and_identity_fail(store, kwargs, pattern):
    first = fragment(store, "old.parquet", "2025-12-31 14:30:00")
    second = fragment(store, "new.parquet", "2026-09-11 14:30:00", **kwargs)
    with pytest.raises(ValueError, match=pattern):
        build(store, [first, second])


def test_duplicate_and_overlapping_fragments_rejected(store):
    first = fragment(store, "a.parquet", "2026-09-11 14:30:00")
    second = fragment(store, "b.parquet", "2026-09-11 14:30:00")
    with pytest.raises(ValueError, match="duplicate fragment"):
        build(store, [first, first])
    with pytest.raises(ValueError, match="overlapping fragment"):
        build(store, [first, second])


def test_fragment_change_fails_before_scan(store, monkeypatch):
    path = fragment(store, "a.parquet", "2026-09-11 14:30:00")
    result = build(store, [path]); register(store, result)
    with path.open("ab") as handle:
        handle.write(b"synthetic mutation")
    monkeypatch.setattr(store, "_read_parquet", lambda *a, **kw: pytest.fail("changed fragment scanned"))
    with pytest.raises(ValueError, match="metadata/hash mismatch"):
        store.read("prices_intraday_1m", "QQQ", "raw")


def test_manifest_mutation_and_outside_fragment_fail(store, monkeypatch):
    path = fragment(store, "a.parquet", "2026-09-11 14:30:00")
    result = build(store, [path]); register(store, result)
    manifest_path = result["catalog_record"]["path"]
    from pathlib import Path
    manifest = json.loads(Path(manifest_path).read_text())
    manifest["files"][0]["path"] = str(store.paths.repo_root / "forbidden.parquet")
    Path(manifest_path).write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest SHA-256 mismatch"):
        store.read("prices_intraday_1m", "QQQ", "raw")
    row = store.metadata("prices_intraday_1m", "QQQ", "raw")
    row["source_sha256"] = sha256(Path(manifest_path))
    with pytest.raises(ValueError, match="outside configured"):
        load_manifest(store, row)


def test_validator_uses_footer_hash_and_never_scans_fragment_payload(store, monkeypatch):
    first = fragment(store, "a.parquet", "2026-09-11 14:30:00")
    result = build(store, [first]); register(store, result)
    monkeypatch.setattr(store, "_read_parquet", lambda *a, **kw: pytest.fail("fragment payload scanned"))
    report = validate_catalog(store, "2026-09-11")
    record = report["files"][0]
    assert record["errors"] == [] and record["fragment_count"] == 1
    assert record["validation_scope"] == "FILE_HASH_FOOTER_SCHEMA_IDENTITY_AND_NONOVERLAPPING_RANGES"
    assert "INTERNAL_GAPS_NOT_AUDITED" in record["warnings"][0]
    assert report["integrity_status"] == "FAIL"  # full catalog still requires daily prices


def test_append_creates_new_manifest_and_preserves_prior_selection(store):
    old = fragment(store, "old.parquet", "2025-12-31 14:30:00")
    first = build(store, [old]); register(store, first)
    prior_hash = sha256(store.catalog_path)
    new = fragment(store, "new.parquet", "2026-09-11 14:30:00")
    second = build(store, [old, new])
    assert second["path"] != first["path"]
    assert sha256(store.catalog_path) == prior_hash
    assert store.metadata("prices_intraday_1m", "QQQ", "raw")["path"] == first["path"]
    register(store, second)
    assert len(store.read("prices_intraday_1m", "QQQ", "raw")) == 2


def test_changed_fragment_during_read_is_detected(store, monkeypatch):
    path = fragment(store, "a.parquet", "2026-09-11 14:30:00")
    result = build(store, [path]); register(store, result)
    original = store._read_parquet

    def reader(*args, **kwargs):
        frame = original(*args, **kwargs)
        with path.open("ab") as handle:
            handle.write(b"synthetic concurrent change")
        return frame

    monkeypatch.setattr(store, "_read_parquet", reader)
    with pytest.raises(ValueError, match="fragment SHA-256 mismatch"):
        store.read("prices_intraday_1m", "QQQ", "raw")


def test_supporting_reconciliation_manifest_is_pinned(store, monkeypatch):
    path = fragment(store, "a.parquet", "2026-09-11 14:30:00")
    evidence = store.paths.cache_root / "reconciliation.json"
    evidence.write_text('{"overlap_conflicts":0}', encoding="utf-8")
    result = prepare(store, [path], store.paths.results_root / "manifests",
                     dataset="prices_intraday_1m", ticker="QQQ", adjustment="raw",
                     date_column="timestamp_utc", ticker_column="symbol", source="MOOMOO_OPEND",
                     expected_values={"symbol": "QQQ"}, supporting_manifests=[evidence])
    register(store, result)
    evidence.write_text('{"overlap_conflicts":1}', encoding="utf-8")
    monkeypatch.setattr(store, "_read_parquet", lambda *a, **kw: pytest.fail("unverified evidence scanned"))
    with pytest.raises(ValueError, match="supporting manifest SHA-256"):
        store.read("prices_intraday_1m", "QQQ", "raw")
