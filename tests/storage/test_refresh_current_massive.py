"""Synthetic provider responses and isolated catalogs; no keys or live network."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from scripts.common.storage_paths import StoragePaths
from scripts.storage import refresh_massive_market as provider
from scripts.storage.build_data_catalog import register_file, sha256
from scripts.storage.storage_r2a import CATALOG_SCHEMA_SQL, DataStore

SOURCE = Path(__file__).resolve().parents[2] / "scripts/storage/refresh_current_massive.py"
SPEC = importlib.util.spec_from_file_location("current_massive_subject", SOURCE)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)

OLD = ["2026-09-03", "2026-09-04", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"]
DAYS = OLD + ["2026-09-14", "2026-09-15"]
SECRET = "synthetic-test-key-never-persisted"


class Response:
    def __init__(self, day, symbols=("ABC",), status=200):
        data = {"status": "OK", "adjusted": False, "resultsCount": len(symbols), "results": [
            {"T": symbol, "o": 10, "h": 12, "l": 9, "c": 11, "v": 100,
             "t": int(pd.Timestamp(day, tz="UTC").timestamp() * 1000)} for symbol in symbols]}
        self.content = json.dumps(data if status == 200 else {"status": "NOT_AUTHORIZED"}).encode()
        self.status_code = status
        self.headers = {}


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    paths = StoragePaths(**{name: tmp_path / name for name in
        ("repo_root", "data_root", "cache_root", "daily_root", "backtest_root", "results_root", "envs_root")})
    store = DataStore(paths)
    store.catalog_path.parent.mkdir(parents=True)
    with sqlite3.connect(store.catalog_path) as conn:
        conn.executescript(CATALOG_SCHEMA_SQL)
        conn.executemany("INSERT INTO catalog_metadata VALUES (?,?)", [("schema_version", "1"), ("catalog_role", "REBUILDABLE_FILE_INDEX")])
    legacy = paths.cache_root / "data_acquisition/massive_20260913"
    summary = provider.acquire(OLD, ["ABC"], SECRET, legacy,
        output_root=paths.data_root / "providers/massive/old",
        request_get=lambda url, **kwargs: Response(url.rsplit("/", 1)[1]), gate=lambda root: None)
    compact = provider.compact_acquisition_manifest(summary["manifest_path"], paths.cache_root / "old_compact")
    records = json.loads(Path(compact["manifest"]["path"]).read_bytes())["catalog_records"]
    with sqlite3.connect(store.catalog_path) as conn:
        for row in records:
            register_file(conn, row["dataset"], row["ticker"], row["adjustment"], row["path"], row["row_count"],
                          row["min_date"], row["max_date"], row["source"], row["lineage"])
    monkeypatch.setattr(m, "load_api_key", lambda paths=None, issues=None: SECRET)
    return SimpleNamespace(paths=paths, store=store, legacy=legacy, old=store.metadata(provider.DATASET, "ABC", "raw"),
                           run=paths.daily_root / "run", records=records)


def mocked_acquire(monkeypatch, response=None):
    real = provider.acquire
    calls = []
    def get(url, **kwargs):
        day = url.rsplit("/", 1)[1]
        calls.append(day)
        assert kwargs["headers"]["Authorization"] == "Bearer " + SECRET
        return response(day) if response else Response(day)
    def acquire(*args, **kwargs):
        return real(*args, **kwargs, request_get=get, gate=lambda root: None)
    monkeypatch.setattr(m.massive, "acquire", acquire)
    return calls


def test_incremental_reuses_five_cached_days_retains_history_and_shared_lineage(seeded, monkeypatch):
    calls = mocked_acquire(monkeypatch)
    old_bytes = Path(seeded.old["path"]).read_bytes()
    old_frame = pd.read_parquet(seeded.old["path"])
    old_checkpoint = (seeded.legacy / "days/2026-09-11/checkpoint.json").read_bytes()
    result = m.refresh_massive_current(seeded.paths, [{"ticker": "ABC"}], DAYS, DAYS[-1], seeded.run)
    assert result["status"] == "UPDATED" and calls == DAYS[-2:]
    assert result["network_requests_this_run"] == 2 and result["target_reached_tickers"] == ["ABC"]
    current = seeded.store.metadata(provider.DATASET, "ABC", "raw")
    frame = seeded.store.daily("ABC", "raw", provider="massive")
    assert frame.date.tolist() == DAYS and current["row_count"] == 8
    pd.testing.assert_frame_equal(pd.read_parquet(current["path"]).iloc[:6].reset_index(drop=True), old_frame)
    assert Path(seeded.old["path"]).read_bytes() == old_bytes
    assert (seeded.legacy / "days/2026-09-11/checkpoint.json").read_bytes() == old_checkpoint
    assert "inputs" not in current["lineage"]
    refs = seeded.store.resolve_price_inputs(current)
    assert [row["date"] for row in refs] == DAYS
    assert set(frame.source_id) == {row["sha256"] for row in refs}
    for path in seeded.run.rglob("*.json"):
        assert SECRET not in path.read_text(encoding="utf-8")
    # A second run reuses all successful days and does not rewrite old prices.
    again = m.refresh_massive_current(seeded.paths, [{"ticker": "ABC"}], DAYS, DAYS[-1], seeded.paths.daily_root / "again")
    assert again["network_requests_this_run"] == 0 and calls == DAYS[-2:]
    assert again["catalog_records"] == [] and seeded.store.metadata(provider.DATASET, "ABC", "raw")["path"] == current["path"]


def test_permission_failure_stops_without_attempting_newer_days_but_publishes_earlier_success(seeded, monkeypatch):
    sessions = DAYS + ["2026-09-16"]
    calls = mocked_acquire(monkeypatch, lambda day: Response(day, status=403 if day == "2026-09-15" else 200))
    result = m.refresh_massive_current(seeded.paths, [{"ticker": "ABC"}], sessions, sessions[-1], seeded.run)
    assert calls == ["2026-09-14", "2026-09-15"]
    assert result["status"] == "PARTIAL" and result["latest_available_date"] == "2026-09-14"
    assert {"date": "2026-09-15", "error": "HTTP_403"} in result["issues"]
    assert result["target_reached_tickers"] == []
    assert seeded.store.daily("ABC", "raw", provider="massive").date.tolist() == OLD + ["2026-09-14"]


def test_explicit_full_history_replays_earliest_cached_day_without_redownloading(seeded, monkeypatch):
    calls = mocked_acquire(monkeypatch)
    acquire = m.massive.acquire
    planned = []
    def capture(days, *args, **kwargs):
        planned.extend(days)
        return acquire(days, *args, **kwargs)
    monkeypatch.setattr(m.massive, 'acquire', capture)
    result = m.refresh_massive_current(seeded.paths, [{'ticker': 'ABC'}], DAYS,
        DAYS[-1], seeded.run, full_history=True)
    assert planned == DAYS
    assert calls == DAYS[-2:]
    assert result['history_mode'] == 'FULL_REQUESTED_RANGE'
    assert result['planned_start_date'] == DAYS[0]
    assert result['planned_day_count'] == len(DAYS)
    assert seeded.store.daily('ABC', 'raw', provider='massive').date.tolist() == DAYS


def test_missing_key_returns_verified_catalog_coverage_without_projection_or_network(seeded, monkeypatch):
    monkeypatch.setattr(m, "load_api_key", lambda paths=None, issues=None: None)
    monkeypatch.setattr(provider, "acquire", lambda *a, **kw: pytest.fail("No-key path must never acquire"))
    monkeypatch.setattr(m, "_cached_days", lambda *a, **kw: pytest.fail("No-key path must not scan/reproject old raw"))
    result = m.refresh_massive_current(seeded.paths, [{"ticker": "ABC"}, {"ticker": "MISSING"}], DAYS, DAYS[-1], seeded.run)
    assert result["status"] == "API_KEY_MISSING"
    assert result["cached_latest_date"] == "2026-09-11" and result["latest_available_date"] == "2026-09-11"
    assert result["available_tickers"] == ["ABC"] and result["network_requests_this_run"] == 0
    assert result["target_reached_tickers"] == []
    assert seeded.store.metadata(provider.DATASET, "ABC", "raw")["path"] == seeded.old["path"]


def test_new_member_only_enters_if_provider_actually_returns_its_bars(seeded, monkeypatch):
    mocked_acquire(monkeypatch, lambda day: Response(day, symbols=("ABC", "NEW")))
    result = m.refresh_massive_current(seeded.paths, [{"ticker": name} for name in ["ABC", "NEW", "ABSENT"]], DAYS, DAYS[-1], seeded.run)
    assert result["status"] == "PARTIAL" and result["target_reached_tickers"] == ["ABC", "NEW"]
    assert seeded.store.metadata(provider.DATASET, "NEW", "raw")["row_count"] == 2
    assert {"ticker": "ABSENT", "reason": "MASSIVE_TARGET_BAR_UNAVAILABLE"} in result["issues"]
    with pytest.raises(KeyError):
        seeded.store.metadata(provider.DATASET, "ABSENT", "raw")


def test_hash_changed_old_price_is_blocked_without_replacing_pointer(seeded, monkeypatch):
    Path(seeded.old["path"]).write_bytes(b"damaged")
    monkeypatch.setattr(provider, "acquire", lambda *a, **kw: pytest.fail("Must preserve invalid selected history"))
    result = m.refresh_massive_current(seeded.paths, [{"ticker": "ABC"}], DAYS, DAYS[-1], seeded.run)
    assert result["status"] == "FAILED_LOCAL_VALIDATION"
    assert result["issues"] == [{"ticker": "ABC", "reason": "MASSIVE_CACHED_PRICE_HASH_CHANGED"}]
    assert seeded.store.metadata(provider.DATASET, "ABC", "raw")["path"] == seeded.old["path"]


def test_concurrent_catalog_change_prevents_commit(seeded, monkeypatch):
    mocked_acquire(monkeypatch)
    real = m._publish
    def changed(store, records, previous, *args):
        with sqlite3.connect(store.catalog_path) as conn:
            conn.execute("UPDATE data_files SET source_sha256=? WHERE ticker='ABC'", ("c" * 64,))
        return real(store, records, previous, *args)
    monkeypatch.setattr(m, "_publish", changed)
    with pytest.raises(ValueError, match="CURRENT_POINTER_CHANGED"):
        m.refresh_massive_current(seeded.paths, [{"ticker": "ABC"}], DAYS, DAYS[-1], seeded.run)
    with sqlite3.connect(seeded.store.catalog_path) as conn:
        assert conn.execute("SELECT path FROM data_files WHERE is_current=1").fetchall() == [(seeded.old["path"],)]


def test_target_requires_actual_bar_not_only_max_date(seeded):
    missing_session = "2026-09-07"
    assert seeded.old["min_date"] < missing_session < seeded.old["max_date"]
    assert m._reached_target({"ABC": seeded.old}, missing_session) == []


def test_scope_expansion_recovers_missing_dates_even_when_global_cache_is_current():
    days = pd.bdate_range('2026-09-01', '2026-09-22').strftime('%Y-%m-%d').tolist()
    previous = {'OLD': {'max_date': '2026-09-08'}, 'CURRENT': {'max_date': days[-1]}}
    planned = m._refresh_days(days, days, previous, ['OLD', 'CURRENT'])
    assert set(day for day in days if day > '2026-09-08') <= set(planned)
    assert m._refresh_days(days, days, previous, ['NEW']) == days
    assert m._refresh_days(days, days, previous, ['CURRENT']) == days[-5:]


def test_raw_tampering_outside_five_day_overlap_stops_catalog_publication(seeded, monkeypatch):
    calls = mocked_acquire(monkeypatch)
    first = seeded.store.resolve_price_inputs(seeded.old)[0]
    Path(first["path"]).write_bytes(b"corrupt old source outside requested overlap")
    with pytest.raises(ValueError, match="RAW_SOURCE_HASH_CHANGED"):
        m.refresh_massive_current(seeded.paths, [{"ticker": "ABC"}], DAYS, DAYS[-1], seeded.run)
    assert calls == DAYS[-2:]
    assert seeded.store.metadata(provider.DATASET, "ABC", "raw")["path"] == seeded.old["path"]


def test_unselected_old_catalog_ticker_is_neither_downloaded_nor_republished(seeded, monkeypatch):
    calls = mocked_acquire(monkeypatch, lambda day: Response(day, symbols=("NEW",)))
    result = m.refresh_massive_current(seeded.paths, [{"ticker": "NEW"}], DAYS, DAYS[-1], seeded.run)
    assert calls == DAYS[-2:] and result["target_reached_tickers"] == ["NEW"]
    assert [row["ticker"] for row in result["catalog_records"]] == ["NEW"]
    assert seeded.store.metadata(provider.DATASET, "ABC", "raw")["path"] == seeded.old["path"]


def test_acquisition_exception_does_not_print_or_persist_credentials(seeded, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise RuntimeError("unsafe remote exception echoes " + SECRET)
    monkeypatch.setattr(provider, "acquire", fail)
    result = m.refresh_massive_current(seeded.paths, [{"ticker": "ABC"}], DAYS, DAYS[-1], seeded.run)
    assert result["status"] == "ACQUISITION_FAILED"
    assert result["issues"] == [{"reason": "MASSIVE_ACQUISITION_EXCEPTION", "error_type": "RuntimeError"}]
    assert SECRET not in json.dumps(result)
    assert SECRET not in capsys.readouterr().out
    assert SECRET not in (seeded.run / "massive/refresh_report.json").read_text(encoding="utf-8")


def test_invalid_target_and_changed_provider_identity_fail_before_acquisition(seeded, monkeypatch):
    monkeypatch.setattr(provider, "acquire", lambda *a, **kw: pytest.fail("Invalid contract must not acquire"))
    with pytest.raises(ValueError, match="TARGET_NOT_IN_COMPLETED_SESSIONS"):
        m.refresh_massive_current(seeded.paths, [{"ticker": "ABC"}], DAYS, "2026-09-16", seeded.run)
    with pytest.raises(ValueError, match="MEMBER_MAPPING_CONFLICT"):
        m.refresh_massive_current(seeded.paths, [{"ticker": "ABC", "massive_mapping":
            {"provider_symbol": "OTHER", "evidence_url": "https://issuer.example/change"}}], DAYS, DAYS[-1], seeded.run)


def test_api_key_environment_precedes_named_registry_lookup(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "  process-key  ")
    monkeypatch.setenv("POLYGON_API_KEY", "other-key")
    assert m.load_api_key() == "process-key"


def test_api_key_reads_recent_user_registry_setting_without_enumerating(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    class Handle:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    queried = []
    def query(handle, name):
        queried.append(name)
        if name == "MASSIVE_API_KEY": raise FileNotFoundError
        return "new-user-key", 1
    monkeypatch.setitem(sys.modules, "winreg", SimpleNamespace(HKEY_CURRENT_USER="HKCU", REG_SZ=1, REG_EXPAND_SZ=2,
        OpenKey=lambda root, path: Handle(), QueryValueEx=query))
    assert m.load_api_key() == "new-user-key"
    assert queried == ["MASSIVE_API_KEY", "POLYGON_API_KEY"]


@pytest.fixture
def credential_paths(tmp_path, monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    def absent(*args): raise FileNotFoundError
    monkeypatch.setitem(sys.modules, "winreg", SimpleNamespace(HKEY_CURRENT_USER="HKCU", OpenKey=absent))
    return StoragePaths(**{name: tmp_path / name for name in
        ("repo_root", "data_root", "cache_root", "daily_root", "backtest_root", "results_root", "envs_root")})


@pytest.mark.skipif(os.name != "nt", reason="Real DPAPI is Windows-current-user only")
def test_real_current_user_dpapi_roundtrip_in_test_temp_only(credential_paths):
    try:
        saved = m.save_encrypted_key(credential_paths, SECRET)
    except OSError:
        pytest.skip("Current test process cannot use DPAPI; mock contract tests remain active")
    path = Path(saved["path"])
    assert path == credential_paths.cache_root / "private_credentials/massive_api_key.dpapi"
    assert saved["status"] == "SAVED_CURRENT_USER_DPAPI"
    assert SECRET.encode() not in path.read_bytes()
    issues = []
    assert m.load_api_key(credential_paths, issues=issues) == SECRET and issues == []
    assert not path.with_suffix(".dpapi.tmp").exists()


def test_encrypted_loader_and_save_use_ciphertext_only_with_mock_dpapi(credential_paths, monkeypatch):
    calls = []
    def dpapi(data, *, decrypt=False):
        calls.append(decrypt)
        assert data == (b"synthetic-encrypted-blob" if decrypt else SECRET.encode())
        return SECRET.encode() if decrypt else b"synthetic-encrypted-blob"
    monkeypatch.setattr(m, "_dpapi", dpapi)
    saved = m.save_encrypted_key(credential_paths, SECRET)
    assert Path(saved["path"]).read_bytes() == b"synthetic-encrypted-blob"
    assert SECRET not in json.dumps(saved)
    assert m.load_api_key(credential_paths) == SECRET and calls == [False, True]


@pytest.mark.parametrize("value", ["", "a" * 4097, "line\nfeed", "control\x00key", None],
                         ids=["empty", "oversized", "newline", "nul", "not-string"])
def test_secret_validation_rejects_before_creating_any_file(credential_paths, monkeypatch, value):
    monkeypatch.setattr(m, "_dpapi", lambda *a, **kw: pytest.fail("Invalid key must not reach DPAPI"))
    with pytest.raises(ValueError, match="INVALID_API_KEY"):
        m.save_encrypted_key(credential_paths, value)
    assert not credential_paths.cache_root.exists()


@pytest.mark.parametrize("blob", [b"", b"x" * 65537], ids=["empty", "oversized"])
def test_encrypted_size_limit_returns_missing_with_safe_issue(credential_paths, monkeypatch, blob):
    path = m._credential_path(credential_paths)
    path.parent.mkdir(parents=True)
    path.write_bytes(blob)
    monkeypatch.setattr(m, "_dpapi", lambda *a, **kw: pytest.fail("Invalid ciphertext size must not reach DPAPI"))
    issues = []
    assert m.load_api_key(credential_paths, issues=issues) is None
    assert issues == [{"reason": "MASSIVE_ENCRYPTED_CREDENTIAL_INVALID_SIZE"}]


def test_failed_decryption_never_surfaces_exception_or_overwrites_ciphertext(credential_paths, monkeypatch):
    path = m._credential_path(credential_paths)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"damaged-ciphertext")
    def fail(*args, **kwargs): raise OSError("unsafe exception " + SECRET)
    monkeypatch.setattr(m, "_dpapi", fail)
    issues = []
    assert m.load_api_key(credential_paths, issues=issues) is None
    assert issues == [{"reason": "MASSIVE_ENCRYPTED_CREDENTIAL_UNAVAILABLE_OR_INVALID"}]
    assert SECRET not in json.dumps(issues) and path.read_bytes() == b"damaged-ciphertext"


def test_missing_encrypted_credential_is_quiet_and_does_not_create_directories(credential_paths):
    issues = []
    assert m.load_api_key(credential_paths, issues=issues) is None and issues == []
    assert not credential_paths.cache_root.exists()
