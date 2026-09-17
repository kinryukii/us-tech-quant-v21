"""Materialize synthetic provider files through the real temporary storage tree."""
import json
import shutil
import sqlite3

import pandas as pd
import pytest

from scripts.storage.build_data_catalog import SCHEMA, materialize_market, sha256
from scripts.storage.storage_r2a import CATALOG_ROLE, DataStore, StoragePaths


def test_builder_does_not_overwrite_an_unsupported_catalog(tmp_path,monkeypatch):
    from scripts.storage.build_data_catalog import main
    destination=roots(tmp_path,'guard')
    catalog=destination.cache_root/'derived/data_catalog/catalog.sqlite3'
    catalog.parent.mkdir(parents=True)
    with sqlite3.connect(catalog) as conn:
        conn.executescript(SCHEMA)
        conn.executemany('INSERT INTO catalog_metadata VALUES (?,?)',
                         [('schema_version','999'),('catalog_role','ANOTHER_ROLE')])
    before=catalog.read_bytes()
    monkeypatch.setattr('sys.argv',['build_data_catalog','--data-root',str(destination.data_root),
                                  '--cache-root',str(destination.cache_root),'--results-root',str(destination.results_root),
                                  '--report',str(destination.results_root/'report.json')])
    with pytest.raises(ValueError,match='schema_version'):main()
    assert catalog.read_bytes()==before


def test_updates_only_keeps_current_without_scanning_old_sources(tmp_path,monkeypatch):
    source,destination=roots(tmp_path,'source'),roots(tmp_path,'target')
    write_prices(source.data_root/'stocks/ABC/daily_qfq.parquet',['2026-01-02','2026-01-05'])
    store,_=materialize(source,destination)
    before=store.metadata('prices_daily','ABC','qfq')['source_sha256']
    def unexpected_scan(*args):raise AssertionError('old sources must not be scanned')
    monkeypatch.setattr('scripts.storage.build_data_catalog.discover_market',unexpected_scan)
    with sqlite3.connect(store.catalog_path) as conn:
        result=materialize_market(destination,conn,'2026-01-09',updates_only=True)
    assert result['source_files']==0
    assert store.metadata('prices_daily','ABC','qfq')['source_sha256']==before


def roots(tmp_path, prefix):
    names = ["repo_root", "data_root", "cache_root", "daily_root", "backtest_root", "results_root", "envs_root"]
    return StoragePaths(**{name: tmp_path / f"{prefix}_{name}" for name in names})


def write_prices(path, dates, price=10.):
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame({"ticker": "ABC", "date": dates, "open": price, "high": price + 1.,
                          "low": price - 1., "close": price, "volume": 100,
                          "provider_code": "US.ABC", "source": "MOOMOO_OPEND",
                          "fetched_at_utc": "2026-01-10T23:00:00Z", "adjustment": "qfq"})
    if path.suffix == ".parquet":
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)
    return path


def materialize(source, destination, cutoff="2026-01-09"):
    store = DataStore(destination)
    store.catalog_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(store.catalog_path) as connection:
        connection.executescript(SCHEMA)
        connection.executemany("INSERT OR REPLACE INTO catalog_metadata VALUES (?, ?)", [
            ("schema_version", "1"), ("catalog_role", CATALOG_ROLE),
        ])
        report = materialize_market(destination, connection, cutoff, source_paths=source)
    return store, report


def test_materialize_revisits_disjoint_qfq_after_bridge_and_records_actual_lineage(tmp_path):
    source, destination = roots(tmp_path, "source"), roots(tmp_path, "target")
    base = write_prices(source.data_root / "stocks/ABC/daily_qfq.parquet", ["2026-01-02", "2026-01-05"])
    disjoint = write_prices(source.cache_root / "canonical/moomoo_ohlcv/snapshot/canonical_moomoo_ohlcv_daily_qfq.csv",
                            ["2026-01-07", "2026-01-08"])
    bridge = write_prices(source.cache_root / "raw/moomoo/daily_qfq/snapshot_id=moomoo_only_20260110/ABC.csv",
                          ["2026-01-05", "2026-01-06", "2026-01-07"])
    source_hashes = {str(path.resolve()): sha256(path) for path in [base, disjoint, bridge]}
    store, report = materialize(source, destination)
    assert report["rejected_sources"] == []
    frame = store.daily("ABC", "qfq")
    assert frame.date.tolist() == ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
    assert not frame.duplicated(["ticker", "date"]).any()
    metadata = store.metadata("prices_daily", "ABC", "qfq")
    inputs = {item["path"]: item["sha256"] for item in metadata["lineage"]["inputs"]}
    assert inputs == source_hashes
    assert set(frame.source_id) == set(inputs.values())
    assert metadata["lineage"]["unbridged_interval_count"] == 0
    for path in [base, disjoint, bridge]:
        assert sha256(path) == source_hashes[str(path.resolve())]
    first_path, first_digest = metadata["path"], metadata["source_sha256"]
    again, _ = materialize(source, destination)
    repeated = again.metadata("prices_daily", "ABC", "qfq")
    assert (repeated["path"], repeated["source_sha256"]) == (first_path, first_digest)
    with sqlite3.connect(store.catalog_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM data_files WHERE is_current=1").fetchone()[0] == 1


def test_incomplete_conflicting_vintage_preserves_old_dates_and_excludes_unused_lineage(tmp_path):
    source, destination = roots(tmp_path, "source"), roots(tmp_path, "target")
    old = write_prices(source.data_root / "stocks/ABC/daily_qfq.parquet", ["2026-01-02", "2026-01-05", "2026-01-06"])
    rejected = write_prices(source.cache_root / "canonical/moomoo_ohlcv/snapshot/canonical_moomoo_ohlcv_daily_qfq.csv",
                            ["2026-01-02", "2026-01-05", "2026-01-07", "2026-01-08"], price=20.)
    store, _ = materialize(source, destination)
    frame = store.daily("ABC", "qfq")
    assert frame.date.tolist() == ["2026-01-02", "2026-01-05", "2026-01-06"]
    assert set(frame.close) == {10.}
    lineage = store.metadata("prices_daily", "ABC", "qfq")["lineage"]
    assert lineage["inputs"] == [{"path": str(old.resolve()), "sha256": sha256(old)}]
    assert any(item["reason"] == "PRICE_VINTAGE_CONFLICT" for item in lineage["issues"])
    assert rejected.is_file()


def test_complete_new_vintage_replaces_as_a_whole_with_only_its_actual_source(tmp_path):
    source, destination = roots(tmp_path, "source"), roots(tmp_path, "target")
    old = write_prices(source.data_root / "stocks/ABC/daily_qfq.parquet", ["2026-01-02", "2026-01-05"])
    new = write_prices(source.cache_root / "canonical/moomoo_ohlcv/snapshot/canonical_moomoo_ohlcv_daily_qfq.csv",
                       ["2026-01-02", "2026-01-05", "2026-01-06"], price=20.)
    old_hash = sha256(old)
    store, _ = materialize(source, destination)
    frame = store.daily("ABC", "qfq")
    assert set(frame.close) == {20.}
    assert frame.date.tolist() == ["2026-01-02", "2026-01-05", "2026-01-06"]
    lineage = store.metadata("prices_daily", "ABC", "qfq")["lineage"]
    assert lineage["inputs"] == [{"path": str(new.resolve()), "sha256": sha256(new)}]
    assert set(frame.source_id) == {sha256(new)}
    assert sha256(old) == old_hash


def test_rebuild_retains_current_after_original_source_directories_disappear(tmp_path):
    source, destination = roots(tmp_path, "source"), roots(tmp_path, "target")
    old = write_prices(source.data_root / "stocks/ABC/daily_qfq.parquet", ["2026-01-02", "2026-01-05"])
    newer = write_prices(source.cache_root / "canonical/moomoo_ohlcv/snapshot/canonical_moomoo_ohlcv_daily_qfq.csv",
                         ["2026-01-05", "2026-01-06"])
    store, _ = materialize(source, destination)
    before = store.metadata("prices_daily", "ABC", "qfq")
    source_ids = set(store.daily("ABC").source_id)
    # These two directories were created only by this test. Verify the exact
    # resolved destinations before recursive removal; output roots are separate.
    for directory in [source.data_root, source.cache_root]:
        target = directory.resolve()
        assert target.parent == tmp_path.resolve()
        assert target.name in {"source_data_root", "source_cache_root"}
        assert target != destination.data_root.resolve()
        shutil.rmtree(target)
    assert not old.exists() and not newer.exists()
    again, report = materialize(source, destination)
    after = again.metadata("prices_daily", "ABC", "qfq")
    assert report["source_files"] == 0
    assert after["path"] == before["path"]
    assert after["source_sha256"] == before["source_sha256"]
    assert after["lineage"]["inputs"] == before["lineage"]["inputs"]
    assert set(again.daily("ABC").source_id) == source_ids
    assert again.daily("ABC").date.tolist() == ["2026-01-02", "2026-01-05", "2026-01-06"]


def test_rebuild_refuses_earlier_cutoff_and_changed_current_without_demoting(tmp_path):
    source, destination = roots(tmp_path, "source"), roots(tmp_path, "target")
    write_prices(source.data_root / "stocks/ABC/daily_qfq.parquet", ["2026-01-02", "2026-01-08"])
    store, _ = materialize(source, destination)
    selected = store.metadata("prices_daily", "ABC", "qfq")
    with pytest.raises(ValueError, match="truncate"):
        materialize(source, destination, cutoff="2026-01-07")
    assert store.metadata("prices_daily", "ABC", "qfq")["path"] == selected["path"]
    # Corruption is synthetic and isolated to this test's selected output file.
    with open(selected["path"], "ab") as handle:
        handle.write(b"synthetic-corruption")
    with pytest.raises(ValueError, match="missing or changed"):
        materialize(source, destination)
    with sqlite3.connect(store.catalog_path) as connection:
        assert connection.execute("SELECT path FROM data_files WHERE is_current=1").fetchone()[0] == selected["path"]
