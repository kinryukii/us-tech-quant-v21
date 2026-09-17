"""Synthetic export/publication checks; default preparation leaves legacy untouched."""
import csv
import hashlib
import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from scripts.storage import publish_data_snapshot as exporter
from scripts.storage.build_data_catalog import SCHEMA, normalize, register_file
from scripts.storage.storage_r2a import DataStore, StoragePaths, CATALOG_ROLE


@pytest.fixture
def store(tmp_path):
    names = ["repo_root", "data_root", "cache_root", "daily_root", "backtest_root", "results_root", "envs_root"]
    store = DataStore(StoragePaths(**{name: tmp_path / name for name in names}))
    store.catalog_path.parent.mkdir(parents=True)
    with sqlite3.connect(store.catalog_path) as connection:
        connection.executescript(SCHEMA)
        connection.executemany("INSERT INTO catalog_metadata VALUES (?,?)", [
            ("schema_version", "1"), ("catalog_role", CATALOG_ROLE),
        ])
    for ticker in ["ABC", "EXTRA"]:
        for adjustment in ["raw", "qfq"]:
            source = pd.DataFrame({"ticker": ticker, "date": ["2026-09-03", "2026-09-04"],
                                   "open": 10., "high": 11., "low": 9., "close": 10., "volume": 100,
                                   "source": "MOOMOO_OPEND", "provider_code": "US." + ticker})
            frame = normalize(source, adjustment, "synthetic-source", "2026-09-11")
            path = store.paths.data_root / "stocks" / ticker / f"daily_{adjustment}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(path, index=False)
            with sqlite3.connect(store.catalog_path) as connection:
                register_file(connection, "prices_daily", ticker, adjustment, path, len(frame),
                              frame.date.min(), frame.date.max(), "MOOMOO_OPEND", {"synthetic": True})
    return store


def current_pointer(store, symbols=("ABC",), scope=True):
    path = store.paths.daily_root / exporter.POINTER_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(exporter.json_bytes({"policy_version": "V21.231", "source_policy": "MOOMOO_ONLY",
                                          "expected_universe_count": len(symbols), "snapshot_id": "old"}))
    path.with_suffix(".csv").write_bytes(b"key,value\nsnapshot_id,old\n")
    if scope:
        path.with_name("abcde_expected_universe.csv").write_text("ticker\n" + "\n".join(symbols) + "\n", encoding="utf-8")
    return path


def test_prepare_does_not_even_read_broken_current_pointer_and_is_repeatable(store, monkeypatch):
    current = current_pointer(store, scope=False)
    current.write_bytes(b"broken-not-json")
    original, original_csv = current.read_bytes(), current.with_suffix(".csv").read_bytes()
    read_bytes = Path.read_bytes

    def guarded(path):
        if path in {current, current.with_suffix(".csv")}:
            raise AssertionError("prepare must not read the live pointer")
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    root = store.paths.results_root / "export"
    first = exporter.publish(store, "2026-09-04", root)
    again = exporter.publish(store, "2026-09-04", root)
    assert first["mode"] == "PREPARED_ONLY" and first["pointer_changed"] is False
    assert first["snapshot_id"] == again["snapshot_id"]
    assert read_bytes(current) == original and read_bytes(current.with_suffix(".csv")) == original_csv


def test_explicit_publication_without_existing_scope_contract_is_blocked(store):
    current = current_pointer(store, scope=False)
    original = current.read_bytes()
    with pytest.raises(FileNotFoundError):
        exporter.publish(store, "2026-09-04", store.paths.results_root / "export", publish_pointer=True)
    assert current.read_bytes() == original


def test_publication_uses_only_existing_scope_and_updates_both_mirrors(store):
    current = current_pointer(store)
    original = current.read_bytes()
    result = exporter.publish(store, "2026-09-04", store.paths.results_root / "export", publish_pointer=True)
    assert result["mode"] == "PUBLISHED" and result["paired_symbols"] == 1
    assert Path(result["prior_pointer_backup"]).read_bytes() == original
    pointer = json.loads(current.read_bytes())
    assert pointer["canonical_as_of_date"] == "2026-09-04"
    assert pointer["canonical_complete_universe_date"] == "2026-09-04"
    assert set(pd.read_csv(pointer["canonical_raw_path"]).ticker) == {"ABC"}
    manifest = json.loads(Path(pointer["canonical_manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["latest_date"] == "2026-09-04" and manifest["model_safe_count"] is None
    with current.with_suffix(".csv").open(newline="", encoding="utf-8") as handle:
        rows = dict((row["key"], row["value"]) for row in csv.DictReader(handle))
    assert rows["snapshot_id"] == pointer["snapshot_id"]


def test_incomplete_target_coverage_cannot_publish(store):
    current = current_pointer(store)
    original = current.read_bytes()
    with pytest.raises(ValueError, match="INCOMPLETE_SCOPE"):
        exporter.publish(store, "2026-09-11", store.paths.results_root / "export", publish_pointer=True)
    assert current.read_bytes() == original


def test_capture_path_does_not_reselect_current_during_export(store, monkeypatch):
    original_read = store._read_parquet
    captured = []

    def read(path, *args, **kwargs):
        captured.append(path)
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(store, "_read_parquet", read)
    monkeypatch.setattr(store, "daily", lambda *args, **kwargs: pytest.fail("must not reselect current"))
    exporter.publish(store, "2026-09-04", store.paths.results_root / "export")
    assert len(captured) == 4


def test_concurrent_pointer_change_is_not_overwritten(store, monkeypatch):
    current = current_pointer(store)
    other_writer = b'{"snapshot_id":"independent-new-writer"}'
    original_read = store._read_parquet

    def read(*args, **kwargs):
        frame = original_read(*args, **kwargs)
        current.write_bytes(other_writer)
        return frame

    monkeypatch.setattr(store, "_read_parquet", read)
    with pytest.raises(ValueError, match="CHANGED_DURING_PREPARATION"):
        exporter.publish(store, "2026-09-04", store.paths.results_root / "export", publish_pointer=True)
    assert current.read_bytes() == other_writer


def test_existing_bad_backup_is_rejected_before_pointer_change(store):
    current = current_pointer(store)
    original = current.read_bytes()
    root = store.paths.results_root / "export"
    root.mkdir(parents=True)
    backup = root / f"prior_canonical_pointer_json_{hashlib.sha256(original).hexdigest()[:20]}.backup"
    backup.write_bytes(b"incorrect-backup")
    with pytest.raises(ValueError, match="backup content mismatch"):
        exporter.publish(store, "2026-09-04", root, publish_pointer=True)
    assert current.read_bytes() == original


def test_actual_raw_qfq_sets_are_computed_after_cutoff_and_report_cannot_enter_repo(store):
    with sqlite3.connect(store.catalog_path) as connection:
        selected = connection.execute("SELECT path FROM data_files WHERE ticker='EXTRA' AND adjustment='qfq'").fetchone()[0]
        frame = pd.read_parquet(selected)
        frame["date"] = ["2026-09-07", "2026-09-08"]
        frame.to_parquet(selected, index=False)
        connection.execute("UPDATE data_files SET source_sha256=? WHERE path=?", (exporter.sha256(selected), selected))
    result = exporter.publish(store, "2026-09-04", store.paths.results_root / "export")
    pointer = json.loads(Path(result["candidate_pointer"]).read_text(encoding="utf-8"))
    assert pointer["raw_qfq_ticker_set_exact_match"] is False
    assert result["coverage_status"] == "INCOMPLETE_TARGET_DATE"
    with pytest.raises(ValueError, match="outside configured"):
        exporter.publish(store, "2026-09-04", store.paths.repo_root / "export")


def test_verified_provider_price_type_input_retains_moomoo_source_label(store):
    with sqlite3.connect(store.catalog_path) as connection:
        path = connection.execute("SELECT path FROM data_files WHERE ticker='EXTRA' AND adjustment='raw'").fetchone()[0]
        frame = pd.read_parquet(path).drop(columns=["source"])
        frame["provider"] = "MOOMOO"
        frame["price_type"] = "RAW_DAILY"
        normalized = normalize(frame, "raw", "verified-provider-source", "2026-09-11")
        assert set(normalized.source) == {"MOOMOO"}
        normalized.to_parquet(path, index=False)
        connection.execute("UPDATE data_files SET source_sha256=? WHERE path=?", (exporter.sha256(path), path))
    result = exporter.publish(store, "2026-09-04", store.paths.results_root / "export")
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["source_labels"] == ["MOOMOO", "MOOMOO_OPEND"]
    assert manifest["source"] == "MOOMOO"
    raw = pd.read_csv(manifest["files"]["raw"]["path"])
    assert set(raw.loc[raw.ticker.eq("EXTRA"), "source"]) == {"MOOMOO"}
    assert set(raw.loc[raw.ticker.eq("ABC"), "source"]) == {"MOOMOO_OPEND"}


@pytest.mark.parametrize("source", ["UNKNOWN", "YAHOO"])
def test_unknown_or_non_moomoo_sources_still_block_export(store, source):
    with sqlite3.connect(store.catalog_path) as connection:
        path = connection.execute("SELECT path FROM data_files WHERE ticker='EXTRA' AND adjustment='raw'").fetchone()[0]
        frame = pd.read_parquet(path)
        frame["source"] = source
        frame.to_parquet(path, index=False)
        connection.execute("UPDATE data_files SET source_sha256=? WHERE path=?", (exporter.sha256(path), path))
    with pytest.raises(ValueError, match="source or adjustment"):
        exporter.publish(store, "2026-09-04", store.paths.results_root / "export")
