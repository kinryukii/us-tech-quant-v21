"""Materialize synthetic provider files through the real temporary storage tree."""
import json
import shutil
import sqlite3
from pathlib import Path

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


def incremental_fixture(tmp_path):
    source, destination = roots(tmp_path, 'incremental_source'), roots(tmp_path, 'incremental_target')
    first = write_prices(source.data_root / 'stocks/ABC/daily_qfq.parquet', ['2026-01-02', '2026-01-05'])
    keep = source.data_root / 'stocks/KEEP/daily_qfq.parquet'
    keep.parent.mkdir(parents=True)
    frame = pd.read_parquet(first)
    frame['ticker'], frame['provider_code'] = 'KEEP', 'US.KEEP'
    frame.to_parquet(keep, index=False)
    store, _ = materialize(source, destination)
    return destination, store


def incoming_interval(root, name, ticker='ABC', dates=None, declared_ticker=None):
    path = write_prices(root / (name + '.csv'), dates or ['2026-01-05', '2026-01-06'])
    frame = pd.read_csv(path)
    frame['ticker'], frame['provider_code'] = ticker, 'US.' + ticker
    frame.to_csv(path, index=False)
    manifest = root / 'intervals' / (name + '.json')
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({'item': {'ticker': declared_ticker or ticker, 'adjustment': 'qfq'},
                                    'path': str(path), 'sha256': sha256(path)}), encoding='utf-8')
    return path


def selected_price_rows(conn):
    return {(row[1], row[2]): row for row in conn.execute(
        "SELECT * FROM data_files WHERE dataset='prices_daily' AND is_current=1")}


def guard_price_reads(monkeypatch, forbidden):
    from scripts.storage import build_data_catalog as api
    original, reads, scans = api.pq.ParquetFile, [], []
    forbidden = {str(Path(path).resolve()) for path in forbidden}

    class GuardedParquet:
        def __init__(self, path, *args, **kwargs):
            self.path = str(Path(path).resolve())
            self.inner = original(path, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def read(self, *args, **kwargs):
            reads.append((self.path, kwargs.get('columns')))
            assert self.path not in forbidden, 'untouched full Parquet loader called'
            return self.inner.read(*args, **kwargs)

        def iter_batches(self, *args, **kwargs):
            scans.append((self.path, kwargs.get('columns')))
            assert kwargs.get('columns') == ['date'], 'untouched scan decoded price columns'
            return self.inner.iter_batches(*args, **kwargs)

    monkeypatch.setattr(api.pq, 'ParquetFile', GuardedParquet)
    return reads, scans


def test_incremental_noop_retains_exact_catalog_rows_without_price_decoding(tmp_path, monkeypatch):
    destination, store = incremental_fixture(tmp_path)
    with sqlite3.connect(store.catalog_path) as conn:
        before = selected_price_rows(conn)
        reads, scans = guard_price_reads(monkeypatch, [row[3] for row in before.values()])
        report = materialize_market(destination, conn, '2026-01-09', updates_only=True)
        assert selected_price_rows(conn) == before
    assert not reads and not scans
    assert report['materialized_price_files'] == 0 and report['retained_price_files'] == 2
    assert len(report['price_files']) == 2


def test_incremental_only_materializes_touched_old_and_new_keys(tmp_path, monkeypatch):
    destination, store = incremental_fixture(tmp_path)
    extra = destination.cache_root / 'incoming'
    incoming_interval(extra, 'tail')
    incoming_interval(extra, 'new', ticker='NEW')
    old = store.metadata('prices_daily', 'ABC', 'qfq')
    keep = store.metadata('prices_daily', 'KEEP', 'qfq')
    reads, scans = guard_price_reads(monkeypatch, [keep['path']])
    writes, original_write = [], pd.DataFrame.to_parquet

    def counted_write(frame, *args, **kwargs):
        writes.extend(frame.ticker.unique().tolist())
        assert not frame.ticker.eq('KEEP').any(), 'untouched frame was reserialized'
        return original_write(frame, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, 'to_parquet', counted_write)
    with sqlite3.connect(store.catalog_path) as conn:
        before = selected_price_rows(conn)
        report = materialize_market(destination, conn, '2026-01-09', extra_root=extra, updates_only=True)
        after = selected_price_rows(conn)
    assert after[('KEEP', 'qfq')] == before[('KEEP', 'qfq')]
    assert sha256(keep['path']) == keep['source_sha256']
    assert sha256(old['path']) == old['source_sha256']
    assert [path for path, _ in reads] == [str(Path(old['path']).resolve())]
    assert not scans and sorted(writes) == ['ABC', 'NEW']
    assert store.daily('ABC', 'qfq').date.tolist() == ['2026-01-02', '2026-01-05', '2026-01-06']
    assert store.daily('NEW', 'qfq').date.tolist() == ['2026-01-05', '2026-01-06']
    assert report['materialized_price_files'] == 2 and report['retained_price_files'] == 1
    assert len(report['price_files']) == 3 and report['rejected_sources'] == []


def test_incremental_rejects_declared_identity_mismatch_without_touching_current(tmp_path, monkeypatch):
    destination, store = incremental_fixture(tmp_path)
    extra = destination.cache_root / 'incoming'
    incoming_interval(extra, 'wrong', declared_ticker='KEEP')
    with sqlite3.connect(store.catalog_path) as conn:
        before = selected_price_rows(conn)
        reads, scans = guard_price_reads(monkeypatch, [row[3] for row in before.values()])
        report = materialize_market(destination, conn, '2026-01-09', extra_root=extra, updates_only=True)
        assert selected_price_rows(conn) == before
    assert not reads and not scans and report['materialized_price_files'] == 0
    assert len(report['rejected_sources']) == 1
    assert 'declared identity' in report['rejected_sources'][0]['reason']


@pytest.mark.parametrize('damage', ['missing', 'changed'])
def test_incremental_still_verifies_untouched_file_hashes(tmp_path, monkeypatch, damage):
    destination, store = incremental_fixture(tmp_path)
    keep = Path(store.metadata('prices_daily', 'KEEP', 'qfq')['path'])
    if damage == 'missing':
        keep.unlink()
    else:
        with keep.open('ab') as stream:
            stream.write(b'synthetic-corruption')
    with sqlite3.connect(store.catalog_path) as conn:
        before = selected_price_rows(conn)
        guard_price_reads(monkeypatch, [row[3] for row in before.values()])
        with pytest.raises(ValueError, match='missing or changed'):
            materialize_market(destination, conn, '2026-01-09', updates_only=True)
        assert selected_price_rows(conn) == before


def test_incremental_checks_actual_footer_dates_not_stale_catalog_bounds(tmp_path, monkeypatch):
    destination, store = incremental_fixture(tmp_path)
    with sqlite3.connect(store.catalog_path) as conn:
        conn.execute("UPDATE data_files SET max_date='2026-01-03' WHERE dataset='prices_daily'")
        before = selected_price_rows(conn)
        reads, scans = guard_price_reads(monkeypatch, [row[3] for row in before.values()])
        with pytest.raises(ValueError, match='truncate'):
            materialize_market(destination, conn, '2026-01-03', updates_only=True)
        assert selected_price_rows(conn) == before
    assert not reads and not scans


def test_incremental_statistics_missing_falls_back_to_bounded_date_only_scan(tmp_path, monkeypatch):
    import pyarrow.parquet as pq
    destination, store = incremental_fixture(tmp_path)
    keep = Path(store.metadata('prices_daily', 'KEEP', 'qfq')['path'])
    table = pq.read_table(keep)
    pq.write_table(table, keep, write_statistics=False)
    with sqlite3.connect(store.catalog_path) as conn:
        conn.execute('UPDATE data_files SET source_sha256=? WHERE path=?', (sha256(keep), str(keep)))
        before = selected_price_rows(conn)
        reads, scans = guard_price_reads(monkeypatch, [row[3] for row in before.values()])
        report = materialize_market(destination, conn, '2026-01-09', updates_only=True)
        assert selected_price_rows(conn) == before
        with pytest.raises(ValueError, match='truncate'):
            materialize_market(destination, conn, '2026-01-03', updates_only=True)
    assert not reads
    assert (str(keep.resolve()), ['date']) in scans
    assert all(columns == ['date'] for _, columns in scans)
    assert report['materialized_price_files'] == 0


def test_incremental_same_hash_receipt_cannot_claim_a_different_identity(tmp_path):
    destination, store = incremental_fixture(tmp_path)
    extra = destination.cache_root / 'incoming'
    first = incoming_interval(extra, 'first')
    second = extra / 'second.csv'
    second.write_bytes(first.read_bytes())
    (extra / 'intervals/second.json').write_text(json.dumps({
        'item': {'ticker': 'KEEP', 'adjustment': 'qfq'}, 'path': str(second), 'sha256': sha256(second)}), encoding='utf-8')
    with sqlite3.connect(store.catalog_path) as conn:
        before = selected_price_rows(conn)
        report = materialize_market(destination, conn, '2026-01-09', extra_root=extra, updates_only=True)
        assert selected_price_rows(conn)[('KEEP', 'qfq')] == before[('KEEP', 'qfq')]
    assert report['materialized_price_files'] == 1 and len(report['rejected_sources']) == 1
    assert 'declared identity' in report['rejected_sources'][0]['reason']


def test_incremental_conflicting_qfq_keeps_old_dates_and_future_rows_excluded(tmp_path):
    destination, store = incremental_fixture(tmp_path)
    extra = destination.cache_root / 'incoming'
    receipt = incoming_interval(extra, 'conflict', dates=['2026-01-05', '2026-01-06', '2026-01-12'])
    frame = pd.read_csv(receipt)
    frame[['open', 'high', 'low', 'close']] = [20., 21., 19., 20.]
    frame.to_csv(receipt, index=False)
    manifest = extra / 'intervals/conflict.json'
    record = json.loads(manifest.read_text(encoding='utf-8'))
    record['sha256'] = sha256(receipt)
    manifest.write_text(json.dumps(record), encoding='utf-8')
    with sqlite3.connect(store.catalog_path) as conn:
        report = materialize_market(destination, conn, '2026-01-09', extra_root=extra, updates_only=True)
    assert store.daily('ABC', 'qfq').date.tolist() == ['2026-01-02', '2026-01-05']
    assert any(item['reason'] == 'PRICE_VINTAGE_CONFLICT' for item in store.metadata('prices_daily', 'ABC', 'qfq')['lineage']['issues'])
    assert report['materialized_price_files'] == 1 and report['retained_price_files'] == 1


def test_incremental_bad_first_identity_does_not_poison_later_valid_same_hash(tmp_path):
    destination, store = incremental_fixture(tmp_path)
    extra = destination.cache_root / 'incoming'
    bad = incoming_interval(extra, 'first_bad', declared_ticker='KEEP')
    good = incoming_interval(extra, 'second_good')
    assert sha256(bad) == sha256(good)
    with sqlite3.connect(store.catalog_path) as conn:
        before = selected_price_rows(conn)
        report = materialize_market(destination, conn, '2026-01-09', extra_root=extra, updates_only=True)
        assert selected_price_rows(conn)[('KEEP', 'qfq')] == before[('KEEP', 'qfq')]
        statuses = dict(conn.execute('SELECT path,status FROM source_files WHERE path IN (?,?)', (str(bad), str(good))))
    assert statuses == {str(bad): 'REJECTED', str(good): 'READ_VALIDATED'}
    assert report['materialized_price_files'] == 1 and len(report['rejected_sources']) == 1
    assert store.daily('ABC', 'qfq').date.tolist() == ['2026-01-02', '2026-01-05', '2026-01-06']
