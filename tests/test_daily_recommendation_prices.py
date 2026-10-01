import importlib.util
import json
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import pytest

SPEC = importlib.util.spec_from_file_location("price_inputs_test", Path(__file__).parents[1] / "scripts/daily_recommendation_prices.py")
prices = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prices)


class EmptyStore:
    def metadata(self, *args):
        raise KeyError("No catalog price")


def fixture(tmp_path):
    days = pd.bdate_range("2026-01-02", periods=123)
    target = days[-1].date().isoformat()
    original = pd.DataFrame({"code": "US.AAPL", "time_key": days[:-1].strftime("%Y-%m-%d"),
        "open": 100., "high": 100., "low": 100., "close": 100., "volume": 1000.})
    raw_path = tmp_path / "original.parquet"
    original.to_parquet(raw_path, index=False)
    appended = pd.DataFrame({"ticker": "AAPL", "moomoo_symbol": "US.AAPL", "date": days[-6:].strftime("%Y-%m-%d"),
        "open": 100., "high": 100., "low": 100., "close": 100., "volume": 1000., "adjustment": "raw", "source": "MOOMOO_OPEND"})
    current_path = tmp_path / "current.csv"
    appended.to_csv(current_path, index=False)
    coverage = {"raw": {"code_map": {"US.AAPL": {"ticker": "AAPL", "paths": [str(raw_path)], "first_date": "2026-01-02"}},
        "file_sha256": {str(raw_path): prices.digest(raw_path)}},
        "adjustment": {"wolf_event_date": "2025-09-29", "wolf_new_shares_per_old_share": .008352}}
    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text(json.dumps(coverage))
    # The earlier event lies outside the final 121 rows; its affine coordinate
    # must still be preserved by the original full-history anchor.
    factors = pd.DataFrame([{"code": "US.AAPL", "ex_div_date": days[1], "forward_adj_factorA": 1., "forward_adj_factorB": -1.}])
    factor_path = tmp_path / "rehab.parquet"
    factors.to_parquet(factor_path, index=False)
    rehab = {"source": "MOOMOO_OPEND_GET_REHAB", "target_date": target,
        "results": [{"code": "US.AAPL", "status": "PASS", "path": str(factor_path), "sha256": prices.digest(factor_path),
        "row_count": 1, "fetched_at": target + "T22:00:00+00:00"}]}
    acquisitions = {"moomoo": {"results": [{"item": {"ticker": "AAPL", "adjustment": "raw"},
        "path": str(current_path), "sha256": prices.digest(current_path), "status": "FETCHED_VALIDATED_INTERVAL"}]}}
    kwargs = {"target": target, "members": [{"ticker": "AAPL", "security_id": "123", "moomoo_symbol": "US.AAPL"}],
        "sessions": days.strftime("%Y-%m-%d").tolist(), "acquisitions": acquisitions,
        "store": EmptyStore(), "rehab_receipt": rehab,
        "coverage_reference": {"path": coverage_path, "sha256": prices.digest(coverage_path)}}
    return kwargs, original, appended


def test_uses_original_affine_anchor_before_121_day_window(tmp_path):
    kwargs, _, _ = fixture(tmp_path)
    frame, lineage, missing = prices.load_price_inputs(**kwargs)
    assert not missing and len(frame) == 121
    assert frame.close.eq(101).all() and frame.volume.eq(1000).all()
    assert lineage[0]["price_basis"] == "PIT_FORWARD_REHAB_INDEX"
    assert lineage[0]["applied_event_count"] == 1


def test_old_rehab_is_not_silently_reused(tmp_path):
    kwargs, _, _ = fixture(tmp_path)
    kwargs["rehab_receipt"]["results"][0]["fetched_at"] = "2026-01-01T00:00:00+00:00"
    frame, _, missing = prices.load_price_inputs(**kwargs)
    assert frame.empty and missing[0]["reason"] == "REHAB_RESPONSE_PREDATES_TARGET_CLOSE"


def test_changed_raw_overlap_is_explicitly_rejected(tmp_path):
    kwargs, _, appended = fixture(tmp_path)
    ref = kwargs["acquisitions"]["moomoo"]["results"][0]
    appended.loc[0, "close"] = 101
    appended.to_csv(ref["path"], index=False)
    ref["sha256"] = prices.digest(ref["path"])
    frame, _, missing = prices.load_price_inputs(**kwargs)
    assert frame.empty and missing[0]["reason"] == "CONFLICTING_OVERLAP_RAW_PRICE"


def test_no_rehab_or_unknown_original_coordinate_produces_no_fake_price(tmp_path):
    kwargs, _, _ = fixture(tmp_path)
    kwargs["members"].append({"ticker": "NEW", "moomoo_symbol": "US.NEW"})
    kwargs["rehab_receipt"]["results"] = []
    frame, _, missing = prices.load_price_inputs(**kwargs)
    assert frame.empty
    assert {row["reason"] for row in missing} == {"LATEST_REHAB_RESPONSE_MISSING", "A2_ORIGINAL_RAW_ANCHOR_UNBOUND"}


def yahoo_fixture(tmp_path, original, appended, target):
    raw = tmp_path / "yahoo.json"
    raw.write_text(json.dumps({"chart": {"result": [{"meta": {"symbol": "AAPL"}, "events": {}}], "error": None}}))
    normalized = tmp_path / "yahoo.parquet"
    frame = appended.copy()
    frame["source"], frame["adjustment"], frame["provider_code"] = "YAHOO_CHART", "split_adjusted", "AAPL"
    frame.to_parquet(normalized, index=False)
    receipt = {"status": "SUCCESS", "rejected_row_count": 0, "max_date": target,
        "contract": {"provider": "YAHOO_CHART", "ticker": "AAPL", "symbol": "AAPL", "start": str(frame.date.min()), "end": target},
        "observed_at": target + "T22:00:00+00:00", "source_url": "https://query1.finance.yahoo.com/chart/AAPL?" + urlencode({"events": "div,splits,capitalGains", "period2": int((pd.Timestamp(target, tz="UTC") + pd.Timedelta(days=1, hours=4)).timestamp())}),
        "catalog_record": {"lineage": {"price_basis": "SPLIT_ADJUSTED", "currency": "USD", "exchange_timezone": "America/New_York"}},
        "files": [{"role": "RAW_HTTP_RESPONSE", "path": str(raw), "sha256": prices.digest(raw)},
                  {"role": "NORMALIZED_DAILY", "path": str(normalized), "sha256": prices.digest(normalized)}]}
    return receipt, prices._raw_frame(original, "US.AAPL")


def test_yahoo_tail_requires_no_splits_and_actual_raw_overlap(tmp_path):
    kwargs, original, appended = fixture(tmp_path)
    receipt, raw = yahoo_fixture(tmp_path, original, appended, kwargs["target"])
    tail, provenance = prices._qualified_yahoo_tail(receipt, raw, "AAPL", kwargs["target"])
    assert len(tail) == 1 and provenance["provider"] == "YAHOO_CHART"
    assert provenance["qualification"] == "NO_SPLITS_IN_GAP_WITH_RAW_OVERLAP"
    kwargs["acquisitions"] = {"alternate": {"results": [receipt]}}
    frame, lineage, missing = prices.load_price_inputs(**kwargs)
    assert not missing and len(frame) == 121
    assert lineage[0]["source"] == "MOOMOO_RAW_PLUS_QUALIFIED_YAHOO_TAIL_PLUS_MOOMOO_REHAB"


def test_yahoo_end_must_cover_new_york_retrieval_date(tmp_path):
    kwargs, original, appended = fixture(tmp_path)
    receipt, raw = yahoo_fixture(tmp_path, original, appended, kwargs["target"])
    receipt["observed_at"] = (pd.Timestamp(kwargs["target"], tz="UTC") + pd.Timedelta(days=1, hours=10)).isoformat()
    with pytest.raises(ValueError, match="YAHOO_SPLIT_EVENT_REQUEST_DOES_NOT_COVER_RETRIEVAL_DATE"):
        prices._qualified_yahoo_tail(receipt, raw, "AAPL", kwargs["target"])


def test_yahoo_split_or_wrong_prices_never_become_raw(tmp_path):
    kwargs, original, appended = fixture(tmp_path)
    receipt, raw = yahoo_fixture(tmp_path, original, appended, kwargs["target"])
    original_ref = receipt["files"][0]
    payload = json.loads(Path(original_ref["path"]).read_text())
    payload["chart"]["result"][0]["events"]["splits"] = {"a": {"date": int(pd.Timestamp(kwargs["target"], tz="UTC").timestamp())}}
    Path(original_ref["path"]).write_text(json.dumps(payload))
    original_ref["sha256"] = prices.digest(original_ref["path"])
    with pytest.raises(ValueError, match="YAHOO_SPLIT_IN_OVERLAP_OR_GAP"):
        prices._qualified_yahoo_tail(receipt, raw, "AAPL", kwargs["target"])


def test_shared_raw_byte_drift_is_not_repaired_or_ignored(tmp_path):
    kwargs, _, _ = fixture(tmp_path)
    path = tmp_path / "original.parquet"
    path.write_bytes(b"changed")
    frame, _, missing = prices.load_price_inputs(**kwargs)
    assert frame.empty and "PRICE_SOURCE_HASH_MISMATCH" in missing[0]["reason"]


def test_yahoo_explicit_events_window_can_cover_later_retrieval(tmp_path):
    kwargs, original, appended = fixture(tmp_path)
    receipt, raw = yahoo_fixture(tmp_path, original, appended, kwargs["target"])
    observed = pd.Timestamp(kwargs["target"], tz="UTC") + pd.Timedelta(days=1, hours=10)
    receipt["observed_at"] = observed.isoformat()
    receipt["contract"]["events_through"] = observed.date().isoformat()
    receipt["source_url"] = "https://query1.finance.yahoo.com/chart/AAPL?" + urlencode(
        {"events": "div,splits,capitalGains", "period2": int((observed + pd.Timedelta(days=1)).timestamp())})
    tail, _ = prices._qualified_yahoo_tail(receipt, raw, "AAPL", kwargs["target"])
    assert len(tail) == 1
    receipt["source_url"] = "https://query1.finance.yahoo.com/chart/AAPL?" + urlencode(
        {"events": "div,splits,capitalGains", "period2": int(observed.timestamp()) - 1})
    with pytest.raises(ValueError, match="YAHOO_EVENT_REQUEST_PERIOD2_PRECEDES_RETRIEVAL"):
        prices._qualified_yahoo_tail(receipt, raw, "AAPL", kwargs["target"])


def publication_fixture(tmp_path, monkeypatch):
    import sqlite3
    from types import SimpleNamespace
    monkeypatch.syspath_prepend("D:/us-tech-quant")
    from scripts.storage import build_data_catalog as api
    from scripts.storage import refresh_market_data as refresh
    from scripts.common import daily_support as main
    from scripts import daily_recommendation_inputs as inputs
    paths = SimpleNamespace(repo_root=Path("D:/us-tech-quant"), cache_root=tmp_path / "cache", data_root=tmp_path / "data")
    catalog = paths.cache_root / "derived/data_catalog/catalog.sqlite3"
    catalog.parent.mkdir(parents=True)
    target = "2026-09-22"
    old_dates, new_dates = ["2026-09-17", "2026-09-18"], ["2026-09-18", "2026-09-21", target]

    def receipt(name, adjustment, days, value):
        frame = pd.DataFrame({"ticker": "AAPL", "date": days, "open": value, "high": value,
            "low": value, "close": value, "volume": 1000., "adjustment": adjustment,
            "source": "MOOMOO_OPEND", "provider_code": "US.AAPL"})
        path = tmp_path / (name + ".csv")
        frame.to_csv(path, index=False)
        return {"item": {"ticker": "AAPL", "moomoo_symbol": "US.AAPL", "adjustment": adjustment},
            "path": str(path), "sha256": prices.digest(path), "status": "FETCHED_VALIDATED_INTERVAL"}

    old_paths = []
    with sqlite3.connect(catalog) as conn:
        conn.executescript(api.SCHEMA)
        for adjustment in ("raw", "qfq"):
            row = receipt("old_" + adjustment, adjustment, old_dates, 100.)
            normalized = api.normalize(pd.read_csv(row["path"]), adjustment, row["sha256"], target)
            out = tmp_path / ("old_" + adjustment + ".parquet")
            normalized.to_parquet(out, index=False)
            conn.execute("INSERT INTO source_files VALUES(?,?,?,?,?)", (row["path"], row["sha256"], 1, "READ_VALIDATED", ""))
            api.register_file(conn, "prices_daily", "AAPL", adjustment, out, 2, old_dates[0], old_dates[-1], "MOOMOO_OPEND", {})
            old_paths.append((out, prices.digest(out)))
        support = tmp_path / "frozen_universe.parquet"
        pd.DataFrame({"ticker": ["AAPL"]}).to_parquet(support, index=False)
        api.register_file(conn, "13f_universe", "", "", support, 1, None, None, "SEC", {"frozen": True})
    current = [receipt("new_raw", "raw", new_dates, 100.), receipt("new_qfq", "qfq", new_dates, 50.)]
    whole = receipt("whole_qfq", "qfq", sorted(set(old_dates + new_dates)), 50.)
    calls = []
    def fake_refresh(args):
        calls.append(args)
        return {"status": "ACQUIRED", "results": [whole], "new_unique_security_touch_count": 0}
    monkeypatch.setattr(refresh, "run", fake_refresh)
    monkeypatch.setattr(main, "live_quota", lambda *args: (1, 299, [{"code": "US.AAPL"}]))
    monkeypatch.setattr(inputs, "load_frozen_binding", lambda *args: {"frozen": True})
    return paths, catalog, target, {"moomoo": {"results": current}}, old_paths, calls, api, main


def test_publication_repairs_known_qfq_without_losing_history(tmp_path, monkeypatch):
    import sqlite3
    paths, catalog, target, acquisitions, old, calls, _, _ = publication_fixture(tmp_path, monkeypatch)
    result = prices.publish_acquired_prices(paths, acquisitions, target, tmp_path / "run")
    assert result["status"] == "PUBLISHED" and result["raw_reached_target"] == result["qfq_reached_target"] == 1
    assert len(calls) == 1 and calls[0].start == "2026-09-17" and calls[0].adjustments == ["qfq"]
    assert all(prices.digest(path) == expected for path, expected in old)
    with sqlite3.connect(catalog) as conn:
        assert conn.execute("SELECT count(*) FROM data_files WHERE dataset='13f_universe' AND is_current=1").fetchone()[0] == 1
        path = conn.execute("SELECT path FROM data_files WHERE dataset='prices_daily' AND adjustment='qfq' AND is_current=1").fetchone()[0]
    frame = pd.read_parquet(path)
    assert len(frame) == 4 and frame.close.eq(50).all()
    reused = prices.publish_acquired_prices(paths, acquisitions, target, tmp_path / "run")
    assert reused["status"] == "PUBLISHED" and len(calls) == 1
    acquisitions["moomoo"]["results"][0]["sha256"] = "changed"
    stale = prices.publish_acquired_prices(paths, acquisitions, target, tmp_path / "run")
    assert stale["status"] == "BLOCKED" and "INPUTS_CHANGED" in stale["error"]


def test_publication_keeps_old_qfq_when_symbol_is_not_already_charged(tmp_path, monkeypatch):
    import sqlite3
    paths, catalog, target, acquisitions, old, calls, _, main = publication_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "live_quota", lambda *args: (0, 300, []))
    result = prices.publish_acquired_prices(paths, acquisitions, target, tmp_path / "run")
    assert result["status"] == "PARTIAL" and not calls
    assert result["raw_reached_target"] == 1 and result["qfq_reached_target"] == 0
    with sqlite3.connect(catalog) as conn:
        assert conn.execute("SELECT max_date FROM data_files WHERE dataset='prices_daily' AND adjustment='qfq' AND is_current=1").fetchone()[0] == "2026-09-18"
    assert all(prices.digest(path) == expected for path, expected in old)


def test_publication_rolls_back_if_other_dataset_pointer_changes(tmp_path, monkeypatch):
    import sqlite3
    paths, catalog, target, acquisitions, _, _, api, _ = publication_fixture(tmp_path, monkeypatch)
    original = api.materialize_market
    def changed_support(paths, conn, *args, **kwargs):
        report = original(paths, conn, *args, **kwargs)
        conn.execute("UPDATE data_files SET is_current=0 WHERE dataset='13f_universe'")
        return report
    monkeypatch.setattr(api, "materialize_market", changed_support)
    result = prices.publish_acquired_prices(paths, acquisitions, target, tmp_path / "run")
    assert result["status"] == "BLOCKED" and "NONMARKET_POINTERS" in result["error"]
    with sqlite3.connect(catalog) as conn:
        assert conn.execute("SELECT count(*) FROM data_files WHERE dataset='13f_universe' AND is_current=1").fetchone()[0] == 1
        assert conn.execute("SELECT max(max_date) FROM data_files WHERE dataset='prices_daily' AND is_current=1").fetchone()[0] == "2026-09-18"


def massive_fixture(tmp_path, monkeypatch, *, source_volume=1000., source_sessions=6):
    monkeypatch.syspath_prepend("D:/us-tech-quant")
    from scripts.storage.refresh_massive_market import ENDPOINT
    kwargs, original, appended = fixture(tmp_path)
    if source_sessions != 6:
        template = appended.iloc[-1].to_dict()
        appended = pd.DataFrame([{**template, "date": day} for day in kwargs['sessions'][-source_sessions:]])
    rows, refs = [], []
    for item in appended.to_dict("records"):
        day = item["date"]
        observed = day + "T22:00:00+00:00"
        stamp = int(pd.Timestamp(day + "T20:00:00Z").timestamp() * 1000)
        raw = {"T": "AAPL", "o": 100., "h": 100., "l": 100., "c": 100., "v": source_volume, "t": stamp}
        directory = tmp_path / "massive" / "days" / day
        directory.mkdir(parents=True)
        path = directory / "response.json"
        path.write_text(json.dumps({"status": "OK", "adjusted": False, "resultsCount": 1, "results": [raw]}))
        ref = {"path": str(path), "sha256": prices.digest(path), "date": day, "observed_at": observed}
        refs.append(ref)
        (directory / "checkpoint.json").write_text(json.dumps({"status": "SUCCESS", "observed_at": observed,
            "contract": {"date": day, "url": ENDPOINT + day, "params": {"adjusted": "false", "include_otc": "false"}},
            "raw": {"path": str(path), "sha256": ref["sha256"]}}))
        rows.append({**item, "volume": source_volume, "source": "MASSIVE_GROUPED", "adjustment": "raw", "provider_code": "AAPL",
                     "source_id": ref["sha256"], "observed_at": observed, "source_timestamp_ms": stamp, "currency": "USD"})
    path = tmp_path / "massive_normalized.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    record = {"dataset": "prices_daily_massive", "ticker": "AAPL", "source": "MASSIVE_GROUPED",
        "adjustment": "raw", "format": "parquet", "path": str(path), "source_sha256": prices.digest(path),
        "max_date": kwargs["target"], "lineage": {"provider": "MASSIVE_GROUPED", "price_basis": "RAW",
        "currency": "USD", "exchange_timezone": "America/New_York", "provider_symbol": "AAPL",
        "provider_mapping": {"provider_symbol": "AAPL"}, "inputs": refs}}
    class Store(EmptyStore):
        def metadata(self, dataset, *args):
            if dataset == "prices_daily_massive": return record
            raise KeyError("No Moomoo catalog entry")
        def resolve_price_inputs(self, row, **kwargs): return row["lineage"]["inputs"]
    kwargs["store"] = Store()
    kwargs["acquisitions"] = {"massive": {"catalog_records": [record]}}
    return kwargs, record, prices._raw_frame(original, "US.AAPL")


def test_massive_raw_tail_uses_per_session_asof_and_original_a2_anchor(tmp_path, monkeypatch):
    kwargs, record, _ = massive_fixture(tmp_path, monkeypatch)
    # Historical responses precede the target close but each follows its own close.
    assert record["lineage"]["inputs"][0]["observed_at"] < kwargs["target"]
    frame, lineage, missing = prices.load_price_inputs(**kwargs)
    assert not missing and len(frame) == 121
    assert frame.close.eq(101).all()  # original affine anchor, including pre-window event
    assert lineage[0]["alternate_bridge"]["provider"] == "MASSIVE_GROUPED"
    assert lineage[0]["source"] == "MOOMOO_RAW_PLUS_QUALIFIED_MASSIVE_TAIL_PLUS_MOOMOO_REHAB"


def test_massive_raw_overlap_volume_must_match(tmp_path, monkeypatch):
    kwargs, record, original = massive_fixture(tmp_path, monkeypatch)
    original.loc[original.index[-1], "volume"] = 1001.
    with pytest.raises(ValueError, match="MASSIVE_RAW_OVERLAP_MISMATCH:volume"):
        prices._qualified_massive_tail(record, original, "AAPL", kwargs["target"], kwargs["store"])


def test_massive_current_bar_cannot_precede_close(tmp_path, monkeypatch):
    kwargs, record, original = massive_fixture(tmp_path, monkeypatch)
    record["lineage"]["inputs"][-1]["observed_at"] = kwargs["target"] + "T12:00:00+00:00"
    with pytest.raises(ValueError, match="MASSIVE_BAR_OBSERVED_BEFORE_SESSION_CLOSE"):
        prices._qualified_massive_tail(record, original, "AAPL", kwargs["target"], kwargs["store"])


def test_massive_source_byte_drift_never_qualifies(tmp_path, monkeypatch):
    kwargs, record, original = massive_fixture(tmp_path, monkeypatch)
    Path(record["lineage"]["inputs"][-1]["path"]).write_text("changed")
    with pytest.raises(ValueError, match="PRICE_SOURCE_HASH_MISMATCH"):
        prices._qualified_massive_tail(record, original, "AAPL", kwargs["target"], kwargs["store"])


def test_massive_stale_target_can_fall_back_to_qualified_yahoo(tmp_path, monkeypatch):
    kwargs, record, original = massive_fixture(tmp_path, monkeypatch)
    record["max_date"] = (pd.Timestamp(kwargs["target"]) - pd.Timedelta(days=1)).date().isoformat()
    receipt, _ = yahoo_fixture(tmp_path, original, pd.read_parquet(record["path"]), kwargs["target"])
    kwargs["acquisitions"]["alternate"] = {"results": [receipt]}
    frame, lineage, missing = prices.load_price_inputs(**kwargs)
    assert len(frame) == 121 and not missing
    assert lineage[0]["alternate_bridge"]["provider"] == "YAHOO_CHART"
    assert lineage[0]["alternate_rejections"] == [
        {"provider": "MASSIVE_GROUPED", "reason": "MASSIVE_TARGET_SESSION_UNAVAILABLE"}]


def test_massive_fractional_share_representation_uses_exact_floor_and_preserves_sources(tmp_path, monkeypatch):
    kwargs, record, original = massive_fixture(tmp_path, monkeypatch, source_volume=1000.936259)
    source_paths = [Path(record['path']), *(Path(ref['path']) for ref in record['lineage']['inputs'])]
    before = {str(path): prices.digest(path) for path in source_paths}
    tail, lineage = prices._qualified_massive_tail(record, original, 'AAPL', kwargs['target'], kwargs['store'])
    assert tail.volume.tolist() == [1000.]
    normalization = lineage['volume_normalization']
    assert normalization['rule'] == 'WHOLE_SHARE_FLOOR'
    assert normalization['scope'] == 'DERIVED_MODEL_TAIL_ONLY'
    assert normalization['qualification'] == 'FIVE_SESSION_EXACT_FLOOR_EQUALITY'
    assert normalization['source_values_preserved'] is True
    assert len(normalization['overlap']) == 5
    assert all(row['massive_source_volume'] == 1000.936259 and row['moomoo_volume'] == 1000.
               for row in normalization['overlap'])
    assert lineage['normalized_sha256'] == record['source_sha256']
    assert len(lineage['raw_inputs']) == 6
    assert {str(path): prices.digest(path) for path in source_paths} == before
    assert pd.read_parquet(record['path']).volume.eq(1000.936259).all()


def test_massive_fractional_quantity_cannot_hide_one_whole_share_difference(tmp_path, monkeypatch):
    kwargs, record, original = massive_fixture(tmp_path, monkeypatch, source_volume=1001.01)
    with pytest.raises(ValueError, match='MASSIVE_RAW_OVERLAP_MISMATCH:volume'):
        prices._qualified_massive_tail(record, original, 'AAPL', kwargs['target'], kwargs['store'])


@pytest.mark.parametrize('bad_volume', [1000.25, -1., float('nan'), float('inf')])
def test_massive_whole_share_bridge_rejects_noninteger_or_invalid_moomoo(tmp_path, monkeypatch, bad_volume):
    kwargs, record, original = massive_fixture(tmp_path, monkeypatch, source_volume=1000.25)
    original.loc[original.index[-1], 'volume'] = bad_volume
    with pytest.raises(ValueError, match='MOOMOO_RAW_VOLUME_NOT_NONNEGATIVE_WHOLE_SHARES'):
        prices._qualified_massive_tail(record, original, 'AAPL', kwargs['target'], kwargs['store'])


def test_massive_fractional_bridge_preserves_strict_price_and_five_day_requirements(tmp_path, monkeypatch):
    kwargs, record, original = massive_fixture(tmp_path, monkeypatch, source_volume=1000.9)
    changed = original.copy()
    changed.loc[changed.index[-1], 'close'] += .01
    with pytest.raises(ValueError, match='MASSIVE_RAW_OVERLAP_MISMATCH:close'):
        prices._qualified_massive_tail(record, changed, 'AAPL', kwargs['target'], kwargs['store'])
    with pytest.raises(ValueError, match='MASSIVE_RAW_OVERLAP_FEWER_THAN_FIVE_SESSIONS'):
        prices._qualified_massive_tail(record, original.tail(4), 'AAPL', kwargs['target'], kwargs['store'])


@pytest.mark.parametrize('bad_volume', [-.5, float('nan'), float('inf')])
def test_massive_normalization_never_accepts_invalid_source_volume(tmp_path, monkeypatch, bad_volume):
    kwargs, record, original = massive_fixture(tmp_path, monkeypatch, source_volume=bad_volume)
    with pytest.raises(ValueError, match='MASSIVE_INVALID_OHLCV'):
        prices._qualified_massive_tail(record, original, 'AAPL', kwargs['target'], kwargs['store'])


@pytest.mark.parametrize('at_target', [False, True])
def test_massive_fills_only_requested_internal_gap_without_overwriting_raw(tmp_path, monkeypatch, at_target):
    kwargs, record, raw = massive_fixture(tmp_path, monkeypatch, source_volume=1000.9, source_sessions=10)
    gap = raw.trade_date.iloc[-3]
    raw = raw.loc[raw.trade_date.ne(gap)].copy()
    if at_target:
        raw = pd.concat([raw, pd.DataFrame([{**raw.iloc[-1].to_dict(), 'trade_date': pd.Timestamp(kwargs['target'])}])],ignore_index=True)
    before = raw.copy(deep=True)
    added, proof = prices._qualified_massive_tail(record,raw,'AAPL',kwargs['target'],kwargs['store'],gap_dates=[str(gap.date())])
    assert gap in set(added.trade_date) and not set(added.trade_date)&set(raw.trade_date)
    assert added.volume.eq(1000.).all()
    assert proof['gap_fill']['requested_dates']==[str(gap.date())]
    assert proof['gap_fill']['added_dates']==added.trade_date.dt.strftime('%Y-%m-%d').tolist()
    pd.testing.assert_frame_equal(raw,before)
    raw.loc[raw.index[-1],'open'] += .01
    with pytest.raises(ValueError,match='OVERLAP_MISMATCH:open'):
        prices._qualified_massive_tail(record,raw,'AAPL',kwargs['target'],kwargs['store'],gap_dates=[str(gap.date())])


def test_massive_gap_cannot_add_pre_anchor_or_replace_existing(tmp_path,monkeypatch):
    kwargs,record,raw=massive_fixture(tmp_path,monkeypatch)
    for day in [raw.trade_date.min()-pd.Timedelta(days=1),raw.trade_date.max()]:
        with pytest.raises(ValueError,match='GAP_OUTSIDE'):
            prices._qualified_massive_tail(record,raw,'AAPL',kwargs['target'],kwargs['store'],gap_dates=[day])


def test_price_loader_attempts_gap_bridge_when_raw_already_reaches_target(tmp_path,monkeypatch):
    kwargs,record,raw=massive_fixture(tmp_path,monkeypatch,source_sessions=10)
    original=pd.read_parquet(tmp_path/'original.parquet')
    gap=original.time_key.iloc[-3]
    original=pd.concat([original.loc[original.time_key.ne(gap)],pd.DataFrame([{**original.iloc[-1].to_dict(),'time_key':kwargs['target']}])],ignore_index=True)
    original.to_parquet(tmp_path/'original.parquet',index=False)
    ref=kwargs['coverage_reference'];coverage=json.loads(Path(ref['path']).read_text())
    coverage['raw']['file_sha256'][str(tmp_path/'original.parquet')]=prices.digest(tmp_path/'original.parquet')
    Path(ref['path']).write_text(json.dumps(coverage));ref['sha256']=prices.digest(ref['path'])
    frame,lineage,missing=prices.load_price_inputs(**kwargs)
    assert not missing and len(frame)==121
    assert lineage[0]['alternate_bridge']['gap_fill']['requested_dates']==[gap]


def test_massive_gap_requires_five_exact_prefix_sessions(tmp_path,monkeypatch):
    kwargs,record,raw=massive_fixture(tmp_path,monkeypatch,source_sessions=12)
    gap=raw.trade_date.iloc[-3]
    raw=raw.loc[raw.trade_date.ne(gap)].copy()
    prefix=raw.loc[raw.trade_date.lt(gap)].tail(5).index[0]
    raw.loc[prefix,'open']+=.01
    with pytest.raises(ValueError,match='OVERLAP_MISMATCH:open'):
        prices._qualified_massive_tail(record,raw,'AAPL',kwargs['target'],kwargs['store'],gap_dates=[str(gap.date())])
