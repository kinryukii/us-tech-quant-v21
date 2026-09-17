"""Synthetic checks for file selection and bounded reads; no real research data."""
import importlib.util
import json
import os
import sqlite3
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import pytest


_SOURCE = Path(__file__).resolve().parents[2] / "scripts/storage/storage_r2a.py"
_SPEC = importlib.util.spec_from_file_location("storage_r2a_under_test", _SOURCE)
store_module = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(store_module)


@pytest.fixture
def store(tmp_path):
    paths = store_module.StoragePaths(**{
        key: tmp_path / key for key in store_module._resolver.DEFAULTS
    })
    return store_module.DataStore(paths)


def parquet(path, *, ticker="ABC", date_type=pa.string()):
    path.parent.mkdir(parents=True, exist_ok=True)
    dates = ["2025-12-31", "2026-01-02", "2026-09-04"]
    if pa.types.is_date(date_type):
        dates = [pd.Timestamp(value).date() for value in dates]
    elif pa.types.is_timestamp(date_type):
        dates = [pd.Timestamp(value).to_pydatetime() for value in dates]
    pq.write_table(pa.table({
        "date": pa.array(dates, type=date_type), "ticker": [ticker] * 3, "close": [10.0, 11.0, 12.0],
    }), path, row_group_size=1)
    return path


def catalog(store, rows, *, version="1", schema=None):
    store.catalog_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(store.catalog_path) as connection:
        connection.executescript(schema or store_module.CATALOG_SCHEMA_SQL)
        connection.executemany("INSERT INTO catalog_metadata VALUES (?, ?)", [
            ("schema_version", version), ("catalog_role", store_module.CATALOG_ROLE),
        ])
        for row in rows:
            payload = {"dataset": "prices_daily", "ticker": "ABC", "adjustment": "qfq",
                       "path": str(row["path"]), "is_current": 1, **row}
            payload["path"] = str(payload["path"])
            names = list(payload)
            connection.execute(
                f"INSERT INTO data_files ({','.join(names)}) VALUES ({','.join('?' for _ in names)})",
                [payload[name] for name in names],
            )


@pytest.mark.parametrize("date_type", [pa.string(), pa.date32(), pa.timestamp("us")])
def test_predicate_is_applied_by_arrow_before_conversion(store, monkeypatch, date_type):
    parquet(store.paths.data_root / "stocks/ABC/daily_qfq.parquet", date_type=date_type)
    actual_dataset = ds.dataset
    calls = []

    class DatasetProxy:
        def __init__(self, wrapped):
            self.wrapped, self.schema, self.files = wrapped, wrapped.schema, wrapped.files

        def to_table(self, **kwargs):
            assert kwargs["filter"] is not None
            table = self.wrapped.to_table(**kwargs)
            calls.append({"expression": str(kwargs["filter"]), "rows_before_pandas": table.num_rows})
            return table

    monkeypatch.setattr(ds, "dataset", lambda *args, **kwargs: DatasetProxy(actual_dataset(*args, **kwargs)))
    result = store.daily("abc", "qfq", "2026-01-01", "2026-01-31", columns=["close"])
    assert result.to_dict("list") == {"close": [11.0]}
    assert calls[0]["rows_before_pandas"] == 1
    assert "date" in calls[0]["expression"] and "ticker" in calls[0]["expression"]


def test_current_catalog_selects_file_and_exposes_lineage(store):
    stale = parquet(store.paths.data_root / "stocks/ABC/daily_qfq.parquet")
    current = parquet(store.paths.data_root / "snapshots/recovered/ABC.parquet")
    catalog(store, [{"path": stale, "is_current": 0}, {"path": current, "vintage_id": "snapshot-123",
                      "lineage_json": json.dumps({"source_manifest": "preserved/manifest.json"})}])
    metadata = store.metadata("prices_daily", "ABC", "qfq")
    assert Path(metadata["path"]) == current
    assert metadata["vintage_id"] == "snapshot-123"
    assert metadata["lineage"]["source_manifest"] == "preserved/manifest.json"
    assert store.list_tickers() == ["ABC"]


def test_does_not_fall_back_when_current_catalog_file_is_missing(store):
    parquet(store.paths.data_root / "stocks/ABC/daily_qfq.parquet")
    catalog(store, [{"path": store.paths.data_root / "missing.parquet"}])
    with pytest.raises(FileNotFoundError, match="selected data file is missing"):
        store.daily("ABC")


def test_slash_symbol_is_resolved_only_through_catalog(store):
    with pytest.raises(ValueError, match="single component"):
        store.daily("LEN/B")
    path = parquet(store.paths.data_root / "stocks/LEN_B/registered.parquet", ticker="LEN/B")
    catalog(store, [{"ticker": "LEN/B", "path": path}])
    assert store.daily("LEN/B", end_date="2025-12-31").ticker.tolist() == ["LEN/B"]


def test_rejects_path_traversal_and_parameterizes_dataset_selection(store):
    with pytest.raises(ValueError, match="invalid ticker"):
        store.daily("../../ABC")
    path = parquet(store.paths.data_root / "stocks/ABC/daily_qfq.parquet")
    catalog(store, [{"path": path}])
    with pytest.raises(KeyError):
        store.read("prices_daily' OR 1=1 --", "ABC", "qfq")
    with sqlite3.connect(store.catalog_path) as connection:
        connection.execute("UPDATE data_files SET path = ?", (str(store.paths.repo_root / "bad.parquet"),))
    with pytest.raises(ValueError, match="outside configured"):
        store.daily("ABC")


@pytest.mark.parametrize("version", ["", "999"])
def test_unknown_catalog_version_is_explicit_error(store, version):
    catalog(store, [], version=version)
    with pytest.raises(ValueError, match="schema_version"):
        store.list_tickers()


@pytest.mark.parametrize("schema", ["", "CREATE TABLE data_files (dataset TEXT);"])
def test_missing_catalog_tables_do_not_fall_back(store, schema):
    store.catalog_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(store.catalog_path) as connection:
        connection.executescript(schema)
    with pytest.raises(ValueError, match="invalid data catalog"):
        store.daily("ABC")


def test_duplicate_current_rows_are_rejected_without_relying_on_index(store):
    path = parquet(store.paths.data_root / "stocks/ABC/daily_qfq.parquet")
    duplicate = parquet(store.paths.data_root / "stocks/ABC/second.parquet")
    schema = store_module.CATALOG_SCHEMA_SQL.split("CREATE UNIQUE INDEX")[0]
    catalog(store, [{"path": path}, {"path": duplicate}], schema=schema)
    with pytest.raises(ValueError, match="multiple current files"):
        store.daily("ABC")


def test_generic_hive_partitioned_dataset_supports_explicit_date_column(store):
    folder = store.paths.data_root / "filings/normalized"
    folder.mkdir(parents=True)
    table = pa.table({"year": [2025, 2026], "accepted_date": ["2025-12-31", "2026-01-02"],
                      "accession": ["OLD", "NEW"]})
    ds.write_dataset(table, folder, format="parquet", partitioning=["year"], partitioning_flavor="hive")
    catalog(store, [{"dataset": "sec_filings", "ticker": "", "adjustment": "", "path": folder}])
    frame = store.read("sec_filings", end_date="2025-12-31", date_column="accepted_date", partitioning="hive")
    assert frame.accession.tolist() == ["OLD"]
    assert frame.year.tolist() == [2025]


def test_existing_function_signatures_remain_usable(store, monkeypatch):
    parquet(store.paths.data_root / "stocks/ABC/daily_raw.parquet")
    monkeypatch.setattr(store_module, "resolve_storage_paths", lambda: store.paths)
    frame = store_module.load_ticker_daily("ABC", "raw", "2026-09-04", "2026-09-04")
    assert frame.close.tolist() == [12.0]
    assert store_module.scan_universe_daily(["ABC"], "raw", end_date="2025-12-31").close.tolist() == [10.0]
    with pytest.raises(ValueError, match="adjustment"):
        store_module.load_ticker_daily("ABC", "invalid")


def provider_file_and_row(store, *, provider="yahoo", lineage_updates=None):
    source, adjustment, price_basis = {"yahoo": ("YAHOO_CHART", "split_adjusted", "SPLIT_ADJUSTED"),
                                       "massive": ("MASSIVE_GROUPED", "raw", "RAW")}[provider]
    path = store.paths.data_root / f"providers/{provider}/ABC.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame({"ticker": ["ABC"] * 2, "date": ["2025-12-31", "2026-09-11"],
                          "open": [10., 20.], "high": [12., 22.], "low": [9., 19.], "close": [11., 21.],
                          "volume": 100., "turnover": None, "source": source,
                          "provider_code": "ABC", "adjustment": adjustment, "source_id": "f" * 64,
                          "observed_at": "2026-09-12T00:00:00Z"})
    if provider == "yahoo":
        frame["adjusted_close"] = [7., 17.]
    frame.to_parquet(path, index=False)
    lineage = {"schema_version": 1, "role": "PROVIDER_DAILY_PRICE_SNAPSHOT", "provider": source,
               "date_column": "date", "price_basis": price_basis, "currency": "USD",
               "exchange_timezone": "America/New_York", "provider_symbol": "ABC",
               "vintage_semantics": "CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT",
               "inputs": [{"path": str(store.paths.cache_root / f"raw_{provider}.json"), "sha256": "f" * 64}],
               **(lineage_updates or {})}
    return path, {"path": path, "dataset": f"prices_daily_{provider}", "adjustment": adjustment,
                  "source": source, "lineage_json": json.dumps(lineage)}


def test_explicit_provider_selection_preserves_moomoo_default_and_basis(store):
    moomoo = parquet(store.paths.data_root / "stocks/ABC/daily_qfq.parquet")
    _, yahoo = provider_file_and_row(store)
    _, massive = provider_file_and_row(store, provider="massive")
    catalog(store, [{"path": moomoo}, yahoo, massive])
    assert store.daily("ABC").close.tolist() == [10., 11., 12.]
    result = store.daily("ABC", "split_adjusted", provider="yahoo")
    assert result.close.tolist() == [11., 21.]
    assert result.adjusted_close.tolist() == [7., 17.]
    massive_result = store.daily("ABC", "raw", provider="massive")
    assert massive_result.close.tolist() == [11., 21.] and "adjusted_close" not in massive_result
    assert massive_result.source.unique().tolist() == ["MASSIVE_GROUPED"]
    for provider, adjustment in [("yahoo", "qfq"), ("yahoo", "raw"), ("moomoo", "split_adjusted"), ("massive", "qfq"), ("massive", "split_adjusted"), ("unknown", "raw")]:
        with pytest.raises(ValueError):
            store.daily("ABC", adjustment, provider=provider)


@pytest.mark.parametrize("provider,adjustment", [("yahoo", "split_adjusted"), ("massive", "raw")])
def test_missing_provider_never_falls_back_to_moomoo(store, provider, adjustment):
    path = parquet(store.paths.data_root / "stocks/ABC/daily_qfq.parquet")
    catalog(store, [{"path": path}])
    with pytest.raises(KeyError, match=f"prices_daily_{provider}"):
        store.daily("ABC", adjustment, provider=provider)


@pytest.mark.parametrize("provider,adjustment", [("yahoo", "split_adjusted"), ("massive", "raw")])
def test_provider_date_predicate_still_applies_before_pandas(store, monkeypatch, provider, adjustment):
    _, row = provider_file_and_row(store, provider=provider)
    catalog(store, [row])
    actual_dataset = ds.dataset
    observed = []

    class Proxy:
        def __init__(self, wrapped):
            self.wrapped, self.schema, self.files = wrapped, wrapped.schema, wrapped.files
        def to_table(self, **kwargs):
            assert kwargs["filter"] is not None
            table = self.wrapped.to_table(**kwargs)
            observed.append(table.num_rows)
            return table

    monkeypatch.setattr(ds, "dataset", lambda *args, **kwargs: Proxy(actual_dataset(*args, **kwargs)))
    result = store.daily("ABC", adjustment, "2026-09-01", "2026-09-11", ["close"], provider=provider)
    assert result.close.tolist() == [21.] and observed == [1]


@pytest.mark.parametrize("provider,adjustment,basis,required_field", [
    ("yahoo", "split_adjusted", "SPLIT_ADJUSTED", "adjusted_close"), ("massive", "raw", "RAW", "source_id")])
def test_provider_reader_requires_metadata_and_schema_even_for_narrow_projection(store, provider, adjustment, basis, required_field):
    path, row = provider_file_and_row(store, provider=provider, lineage_updates={"price_basis": "QFQ"})
    catalog(store, [row])
    with pytest.raises(ValueError, match="lineage schema/source/price-basis"):
        store.read(f"prices_daily_{provider}", "ABC", adjustment, columns=["close"])
    with sqlite3.connect(store.catalog_path) as connection:
        lineage = json.loads(row["lineage_json"])
        lineage["price_basis"] = basis
        connection.execute("UPDATE data_files SET lineage_json=?", (json.dumps(lineage),))
    frame = pq.ParquetFile(path).read().to_pandas().drop(columns=[required_field])
    frame.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="daily price schema missing columns: " + required_field):
        store.daily("ABC", adjustment, columns=["close"], provider=provider)


def directory_link(link, target):
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def remove_directory_link(link):
    if os.name == "nt":
        link.rmdir()
    else:
        link.unlink()


def test_data_path_resolves_once_per_access_and_preserves_missing_checks(store, monkeypatch):
    path = store.paths.data_root / "file.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    actual = Path.resolve
    calls = []
    def tracked(self, *args, **kwargs):
        calls.append(self)
        return actual(self, *args, **kwargs)
    monkeypatch.setattr(Path, "resolve", tracked)
    assert store._check_data_path(path) == path
    assert calls == [path]
    path.unlink()
    with pytest.raises(FileNotFoundError):
        store._check_data_path(path)
    assert store._check_data_path(path, must_exist=False) == path
    assert calls == [path] * 3


def test_changed_child_link_is_resolved_again_and_cannot_escape(store, tmp_path):
    inside = store.paths.data_root / "inside"
    outside = tmp_path / "outside"
    for target in (inside, outside):
        target.mkdir(parents=True)
        (target / "file.json").write_text("identical bytes")
    link = store.paths.data_root / "link"
    directory_link(link, inside)
    try:
        assert store._check_data_path(link / "file.json") == inside / "file.json"
        remove_directory_link(link)
        directory_link(link, outside)
        with pytest.raises(ValueError, match="outside configured"):
            store._check_data_path(link / "file.json")
    finally:
        remove_directory_link(link)
    assert (inside / "file.json").exists() and (outside / "file.json").exists()


def test_configured_root_target_is_pinned_but_paths_and_validation_stay_compatible(tmp_path):
    roots = {name: tmp_path / name for name in store_module._resolver.DEFAULTS}
    original = tmp_path / "original_data"
    replacement = tmp_path / "replacement_data"
    for target in (original, replacement):
        target.mkdir(); (target / "file.json").write_text("{}")
    directory_link(roots["data_root"], original)
    paths = store_module.StoragePaths(**roots)
    try:
        store = store_module.DataStore(paths)
        assert store.paths is paths
        assert store._check_data_path(paths.data_root / "file.json") == original / "file.json"
        remove_directory_link(roots["data_root"])
        directory_link(roots["data_root"], replacement)
        with pytest.raises(ValueError, match="outside configured"):
            store._check_data_path(paths.data_root / "file.json")
        assert store._check_data_path(original / "file.json") == original / "file.json"
    finally:
        remove_directory_link(roots["data_root"])
    with pytest.raises(ValueError, match="must not nest repo_root"):
        store_module.DataStore(store_module.StoragePaths(**{**roots, "data_root": roots["repo_root"] / "data"}))
