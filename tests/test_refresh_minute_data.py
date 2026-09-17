import importlib.util
from pathlib import Path

import pandas as pd
import pytest

SOURCE = Path(__file__).parents[1] / "scripts/storage/refresh_minute_data.py"
SPEC = importlib.util.spec_from_file_location("refresh_minute_data", SOURCE)
minute = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(minute)


def test_plan_has_no_segment_overlap_and_honors_target():
    plan = minute.plan_intervals(["QQQ", "QQQ", "SOXX"], "2026-08-04", "2026-09-11")
    assert len(plan) == 12
    for code in ["US.QQQ", "US.SOXX"]:
        dates = [d for item in plan if item["code"] == code for d in pd.date_range(item["start"], item["end"])]
        assert len(dates) == len(set(dates)) == 39
        assert max(dates) == pd.Timestamp("2026-09-11")


def test_new_security_never_reaches_underlying_context():
    class Context:
        def request_history_kline(self, **kwargs):
            pytest.fail("new security was requested")
    proxy = minute.LimitedQuoteHistory(Context(), None, {"US.QQQ"})
    with pytest.raises(ValueError, match="NEW_SECURITY_TOUCH_FORBIDDEN"):
        proxy.request_history_kline(code="US.SOXX")


def test_every_page_is_limited():
    calls = []
    class Context:
        def request_history_kline(self, **kwargs):
            calls.append(kwargs)
            return "ok"
    class Limiter:
        def acquire(self, item):
            calls.append(item)
    proxy = minute.LimitedQuoteHistory(Context(), Limiter(), {"US.QQQ"})
    assert proxy.request_history_kline(code="US.QQQ", page_req_key="next") == "ok"
    assert calls[0]["frequency"] == "1m"
    assert calls[1]["page_req_key"] == "next"


def test_dry_run_neither_writes_nor_imports_sdk(tmp_path, monkeypatch):
    monkeypatch.setattr(minute.importlib, "import_module", lambda *args: pytest.fail("SDK imported"))
    root = tmp_path / "unused"
    assert minute.main(["--work-root", str(root), "--tickers", "QQQ", "--start", "2026-08-04", "--end", "2026-09-11"]) == 0
    assert not root.exists()


@pytest.mark.parametrize("changed_column,allowed,expected", [
    ("volume", False, "BLOCKED"), ("volume", True, "VERIFIED_TAIL"),
    ("open", True, "BLOCKED")])
def test_tail_gate_preserves_ohlc_boundary(tmp_path, monkeypatch, changed_column, allowed, expected):
    root = tmp_path / "acquisition"
    root.mkdir()
    (root / "acquisition_report.json").write_text("{}")
    old_dir = tmp_path / "canonical/symbol=QQQ/year=2026/month=08"
    old_dir.mkdir(parents=True)
    timestamps = pd.date_range("2026-08-04T14:00:00Z", periods=3, freq="min")
    incoming = pd.DataFrame({"timestamp_utc": timestamps, "calendar_date_et": ["2026-08-04"] * 3,
                             "code": ["US.QQQ"] * 3, "session": ["RTH"] * 3,
                             "open": [10.] * 3, "high": [12.] * 3, "low": [9.] * 3,
                             "close": [11.] * 3, "volume": [100.] * 3, "turnover": [1100.] * 3})
    old = incoming.iloc[:2].copy()
    old.to_parquet(old_dir / "data.parquet", index=False)
    old_hash = minute.digest(old_dir / "data.parquet")
    incoming.loc[0, changed_column] += 1
    new_path = root / "incoming.parquet"
    incoming.to_parquet(new_path, index=False)
    item = {"ticker": "QQQ", "code": "US.QQQ", "start": "2026-08-04", "end": "2026-08-04"}
    checkpoint = {"item": item, "raw": {"path": str(new_path)}, "output": {"path": str(new_path)}}
    monkeypatch.setattr(minute, "read_checkpoint", lambda *args: checkpoint)
    report = minute.build_tails(root, tmp_path / "canonical", [item], allowed)
    row = report["results"][0]
    assert row["status"] == expected
    assert minute.digest(old_dir / "data.parquet") == old_hash
    assert Path(row["overlap_comparison"]["row_level_differences"]["csv_path"]).exists()
    if expected == "VERIFIED_TAIL":
        assert row["output"]["row_count"] == 1
        assert row["warnings"] == ["VOLUME_TURNOVER_REVISIONS_OBSERVED"]
    else:
        assert "output" not in row



def revision_fixture():
    timestamps = pd.date_range("2026-08-04T14:00:00Z", periods=6, freq="min")
    frame = pd.DataFrame({"symbol": "SOXX", "code": "US.SOXX", "timestamp_utc": timestamps,
                          "timestamp_et": timestamps.tz_convert("America/New_York"),
                          "timestamp_jst": timestamps.tz_convert("Asia/Tokyo"),
                          "calendar_date_et": "2026-08-04", "broker_trade_date": "2026-08-04", "session": "RTH",
                          "open": 10.0, "high": 12.0, "low": 9.0, "close": 11.0, "volume": 100.0,
                          "turnover": 1100.0, "source": "moomoo_opend", "adjustment_type": "NONE",
                          "downloaded_at_utc": "2026-08-08T00:00:00Z"})
    old = frame.iloc[:4].copy()
    incoming = frame.iloc[2:].copy().reset_index(drop=True)
    incoming.loc[0, "open"] = 10.5
    incoming["downloaded_at_utc"] = "2026-09-12T17:00:00Z"
    confirmation = incoming.iloc[:2].copy()
    confirmation["downloaded_at_utc"] = "2026-09-12T18:00:00Z"
    return old, incoming, confirmation


def test_confirmed_revision_keeps_all_original_keys_and_download_times():
    old, incoming, confirmation = revision_fixture()
    merged, differences, report = minute.reconcile_revision_frames(old, incoming, confirmation)
    assert len(merged) == 6
    assert set(old.timestamp_utc).issubset(set(merged.timestamp_utc))
    assert merged.iloc[0].downloaded_at_utc == old.iloc[0].downloaded_at_utc
    assert merged.loc[merged.timestamp_utc.eq(incoming.iloc[0].timestamp_utc), "open"].iloc[0] == 10.5
    assert len(differences) == 1 and differences.previous_value.iloc[0] == 10.0
    assert differences.confirmation_downloaded_at_utc.iloc[0] == "2026-09-12T18:00:00Z"
    assert report["original_keys_missing_from_output"] == 0 and report["new_tail_rows"] == 2


@pytest.mark.parametrize("issue,match", [("missing_old", "OLD_MINUTES_NOT_RETURNED"),
                                         ("not_confirmed", "OHLC_REVISION_NOT_IN_CONFIRMATION"),
                                         ("different_confirmation", "CONFIRMATION_VALUES_DISAGREE")])
def test_revision_fails_for_missing_original_or_unconfirmed_changes(issue, match):
    old, incoming, confirmation = revision_fixture()
    if issue == "missing_old":
        incoming = incoming.drop(index=1)
    elif issue == "not_confirmed":
        confirmation = confirmation.iloc[1:].copy()
    else:
        confirmation.loc[0, "volume"] += 1
    with pytest.raises(ValueError, match=match):
        minute.reconcile_revision_frames(old, incoming, confirmation)


def test_revision_reports_new_overlap_keys_without_dropping_existing_minutes():
    old, incoming, confirmation = revision_fixture()
    old = old.drop(index=3)
    merged, _, report = minute.reconcile_revision_frames(old, incoming, confirmation)
    assert report["new_overlap_keys_not_in_old"] == 0
    old, incoming, confirmation = revision_fixture()
    old = old.drop(index=2)
    incoming.loc[1, "open"] = 10.6
    confirmation = incoming.iloc[:2].copy()
    confirmation["downloaded_at_utc"] = "2026-09-12T18:00:00Z"
    merged, _, report = minute.reconcile_revision_frames(old, incoming, confirmation)
    assert report["new_overlap_keys_not_in_old"] == 1
    assert set(old.timestamp_utc).issubset(set(merged.timestamp_utc))


def test_materialized_revision_pins_fragments_evidence_and_is_idempotent(tmp_path):
    import json
    from scripts.storage.build_parquet_manifest import prepare
    class Store:
        def _ticker(self, value): return value
        def _check_data_path(self, path, must_exist=True):
            path = Path(path).resolve()
            assert path.is_relative_to(tmp_path)
            if must_exist: assert path.exists()
            return path
    store = Store()
    old, incoming, confirmation = revision_fixture()
    old_path = tmp_path / "old.parquet"
    old.to_parquet(old_path, index=False)
    old_hash = minute.digest(old_path)
    expected = {"symbol": "SOXX", "code": "US.SOXX", "source": "moomoo_opend", "adjustment_type": "NONE"}
    baseline = prepare(store, [old_path], tmp_path / "baseline", dataset="prices_intraday_1m", ticker="SOXX",
                       adjustment="raw", date_column="timestamp_utc", ticker_column="symbol", source="MOOMOO_OPEND", expected_values=expected)
    item = {"ticker": "SOXX", "code": "US.SOXX", "start": "2026-08-04", "end": "2026-08-04"}
    roots = []
    for role, frame in [("incoming", incoming), ("confirmation", confirmation)]:
        root = tmp_path / role
        base, manifest = minute.interval_paths(root, item)
        base.mkdir(parents=True)
        path = base / "minute.parquet"
        frame.to_parquet(path, index=False)
        ref = {"path": str(path), "sha256": minute.digest(path), "row_count": len(frame)}
        minute.write_json(manifest, {"status": "ACQUIRED", "item": item, "raw": ref, "output": ref})
        minute.write_json(root / "acquisition_report.json", {"status": "ACQUIRED", "plan": [item]})
        roots.append(root)
    args = (store, Path(baseline["path"]), roots[0], roots[1], tmp_path / "output", "SOXX", "2026-08-04", "2026-08-04")
    result = minute.materialize_current_revision(*args)
    assert result["snapshot"]["catalog_record"]["row_count"] == 6
    assert result["catalog_written"] is False
    evidence = json.loads(Path(result["reconciliation_manifest"]).read_text(encoding="utf-8"))
    assert evidence["provider_revision_published_at"] is None
    assert evidence["availability_policy"] == "PRESERVE_ROW_DOWNLOAD_TIMES_NOT_HISTORICAL_PIT_CORRECTION"
    assert minute.digest(old_path) == old_hash
    assert minute.materialize_current_revision(*args) == result
