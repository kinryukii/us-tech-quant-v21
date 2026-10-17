import argparse
import csv
import importlib.util
import json
from pathlib import Path

import pytest

SOURCE = Path(__file__).parents[1] / "scripts/storage/refresh_market_data.py"
SPEC = importlib.util.spec_from_file_location("refresh_market_data", SOURCE)
market = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(market)


def item():
    return market.make_plan(market.load_universe(["AAPL"], None), "2026-08-24", "2026-09-04", ["raw"])[0]


def records():
    return [{"ticker": "AAPL", "moomoo_symbol": "US.AAPL", "market": "US", "date": "2026-09-04",
             "open": 10, "high": 12, "low": 9, "close": 11, "volume": 50, "turnover": 550,
             "adjustment": "raw", "source": "MOOMOO_OPEND", "source_policy": "MOOMOO_ONLY",
             "snapshot_id": "synthetic", "fetched_at_utc": "2026-09-05T00:00:00+00:00"}]


def arguments(tmp_path, execute=False):
    return argparse.Namespace(work_root=tmp_path / "work", repo_root=tmp_path / "repo",
                              tickers=["AAPL"], universe_csv=None, start="2026-08-24", end="2026-09-04",
                              adjustments=["raw"], execute=execute, host=None, port=None, max_retries=0)


def test_dry_run_does_not_import_sdk_or_fetcher(tmp_path, monkeypatch):
    monkeypatch.setattr(market, "load_module", lambda *args: pytest.fail("dry-run imported executable code"))
    result = market.run(arguments(tmp_path))
    assert result["status"] == "DRY_RUN_READY"
    assert result["history_request_count"] == 0
    assert not list(tmp_path.rglob("*.csv"))


def test_failed_tcp_preserves_per_leg_report_without_sdk(tmp_path, monkeypatch):
    class Profile:
        host, port = "127.0.0.1", 18441

    class Connection:
        load_profile = staticmethod(lambda *args: Profile())
        tcp_probe = staticmethod(lambda profile: (False, "TCP_TIMEOUT"))

    monkeypatch.setattr(market, "load_module", lambda *args: Connection())
    monkeypatch.setattr(market.importlib, "import_module", lambda *args: pytest.fail("SDK touched"))
    result = market.run(arguments(tmp_path, execute=True))
    assert result["status"] == "BLOCKED"
    assert result["history_request_count"] == 0
    assert result["results"][0]["status"] == "BLOCKED_CONNECTION_OR_SETUP"


def test_resume_verifies_bytes_and_does_not_call_network(tmp_path, monkeypatch):
    args = arguments(tmp_path, execute=True)
    checkpoint = market.save_interval(args.work_root, item(), records(), "synthetic_source_hash")
    monkeypatch.setattr(market, "load_module", lambda *args: pytest.fail("resume touched network"))
    result = market.run(args)
    assert result["status"] == "ALL_INTERVALS_REUSED"
    assert result["results"][0]["row_count"] == 1
    Path(checkpoint["path"]).write_text("corrupt", encoding="utf-8")
    with pytest.raises(ValueError, match="CHECKPOINT_IDENTITY_FAILED"):
        market.read_checkpoint(args.work_root, item())


def test_crash_after_csv_publication_can_resume(tmp_path):
    checkpoint = market.save_interval(tmp_path, item(), records(), "synthetic_source_hash")
    manifest = Path(checkpoint["path"]).with_suffix(".json")
    value = json.loads(manifest.read_text())
    value["status"] = "PREPARED_INTERVAL"
    manifest.write_text(json.dumps(value), encoding="utf-8")
    assert market.read_checkpoint(tmp_path, item())["status"] == "REUSED_VERIFIED_INTERVAL"


@pytest.mark.parametrize("mutation,reason", [
    ({"date": "2026-09-05"}, "OUT_OF_REQUESTED_DATE_RANGE"),
    ({"moomoo_symbol": "US.MSFT"}, "IDENTITY_OR_ADJUSTMENT_MISMATCH"),
    ({"low": 15}, "INVALID_OHLC_ORDER"),
    ({"volume": -1}, "INVALID_VOLUME"),
])
def test_bad_bars_are_rejected(mutation, reason):
    with pytest.raises(ValueError, match=reason):
        market.validate_records([{**records()[0], **mutation}], item())


def test_duplicate_dates_and_ambiguous_mappings_fail_closed(tmp_path):
    with pytest.raises(ValueError, match="DUPLICATE_DAILY_KEY"):
        market.validate_records(records() * 2, item())
    with pytest.raises(ValueError, match="EXPLICIT_PROVIDER_MAPPING_REQUIRED"):
        market.load_universe(["BRK/B"], None)
    universe = tmp_path / "universe.csv"
    universe.write_text("ticker,moomoo_code,security_id\nBRK/B,US.BRK.B,known_id\n", encoding="utf-8")
    assert market.load_universe(None, universe)[0]["moomoo_symbol"] == "US.BRK.B"


def test_reuses_existing_canonical_fetch_normalizer():
    import pandas as pd

    repo = Path(r"D:\us-tech-quant")
    fetcher = market.load_module(repo / market.FETCHER, "synthetic_v21_fetcher")

    class SDK:
        RET_OK = 0
        KLType = type("KLType", (), {"K_DAY": "K_DAY"})
        AuType = type("AuType", (), {"NONE": "NONE", "QFQ": "QFQ"})

    class Context:
        def request_history_kline(self, code, **kwargs):
            assert code == "US.AAPL" and kwargs["autype"] == "NONE"
            return 0, pd.DataFrame([{"code": code, "time_key": "2026-09-04 00:00:00",
                                    "open": 10, "high": 12, "low": 9, "close": 11,
                                    "volume": 50, "turnover": 550}]), None

    limiter = fetcher.HistoryKlineLimiter(min_interval=0)
    result, error, _, _ = fetcher.guarded_moomoo_fetch(
        item(), SDK, market.QuoteHistoryOnly(Context()), 0, "synthetic", limiter, [], [])
    assert not error
    assert market.validate_records(result, item())["row_count"] == 1
    assert len(limiter.audit_rows) == 1


@pytest.mark.parametrize("known_only,known,remaining,expected_status,touches", [
    (True, True, 0, "FETCHED_VALIDATED_INTERVAL", 0),
    (True, False, 300, "BLOCKED_KNOWN_SECURITY_ONLY", 0),
    (False, False, 300, "FETCHED_VALIDATED_INTERVAL", 1),
    (False, False, 0, "BLOCKED_QUOTA", 0),
])
def test_explicit_known_only_keeps_real_quota_and_never_touches_new_security(tmp_path, monkeypatch,
        known_only, known, remaining, expected_status, touches):
    from types import SimpleNamespace
    args = arguments(tmp_path, execute=True)
    args.known_only = known_only
    called = []
    class Context:
        def set_sync_query_connect_timeout(self, value): pass
        def get_history_kl_quota(self, get_detail):
            return 0, (300 - remaining, remaining, [{"code":"US.AAPL"}] if known else [])
        def close(self): pass
    class Limiter:
        def __init__(self): self.audit_rows = []
    def fetch(item, sdk, context, retries, snapshot_id, limiter, errors, recovered):
        called.append(item["moomoo_symbol"])
        limiter.audit_rows.append({"code":item["moomoo_symbol"]})
        return records(), None, None, 0
    profile = SimpleNamespace(load_profile=lambda *a:SimpleNamespace(host="127.0.0.1",port=18441),
                              tcp_probe=lambda *a:(True,"synthetic"))
    fetcher = SimpleNamespace(HistoryKlineLimiter=Limiter,guarded_moomoo_fetch=fetch)
    monkeypatch.setattr(market,"load_module",lambda path,name:profile if path.as_posix().endswith(market.PROFILE) else fetcher)
    monkeypatch.setattr(market,"digest",lambda path:"synthetic_fetcher_hash")
    sdk = SimpleNamespace(RET_OK=0,SysConfig=SimpleNamespace(set_all_thread_daemon=lambda value:None),
                          OpenQuoteContext=lambda **kw:Context())
    monkeypatch.setattr(market.importlib,"import_module",lambda name:sdk)
    result = market.run(args)
    assert result["results"][0]["status"] == expected_status
    assert result["quota_before"]["remaining"] == remaining
    assert result["quota_before"]["known_codes"] == (["US.AAPL"] if known else [])
    assert result["new_unique_security_touch_count"] == touches
    assert len(called) == int(expected_status == "FETCHED_VALIDATED_INTERVAL")
    assert result["history_request_count"] == len(called)
    assert result["trade_context_opened"] is False


def current_fixture(tmp_path, monkeypatch, damage=None):
    import pandas as pd
    from types import SimpleNamespace
    args = arguments(tmp_path, execute=True)
    args.acquisition_mode = "current-kline"
    args.start, args.end = "2025-09-22", "2025-10-02"
    args.repo_root = Path(r"D:\us-tech-quant")
    universe = tmp_path / "universe.csv"
    universe.write_text("ticker,moomoo_symbol,security_id\nONC,US.ONC,07725L102\n", encoding="utf-8")
    args.tickers, args.universe_csv = None, universe
    original_load = market.load_module
    actual = original_load(args.repo_root / market.FETCHER, "synthetic_current_normalizer")
    class Limiter:
        def __init__(self, **kwargs): self.audit_rows = []
        def acquire(self, item): self.audit_rows.append({"code": item["moomoo_symbol"]})
    fetcher = SimpleNamespace(HistoryKlineLimiter=Limiter, normalize_records=actual.normalize_records)
    profile = SimpleNamespace(load_profile=lambda *a: SimpleNamespace(host="127.0.0.1", port=18441), tcp_probe=lambda *a: (True, "synthetic"))
    class Context:
        closed = False
        def __init__(self): self.owned = set(); self.subs = []; self.unsubs = []; self.gets = []
        def set_sync_query_connect_timeout(self, value): assert value == 10
        def get_history_kl_quota(self, **kwargs): pytest.fail("HISTORY_QUOTA_PATH_FORBIDDEN")
        def request_history_kline(self, *a, **kw): pytest.fail("HISTORY_REQUEST_FORBIDDEN")
        def query_subscription(self, is_all_conn):
            assert is_all_conn is True
            if damage == "query": return -1, "query rejected"
            return 0, {"total_used": 3 + len(self.owned), "own_used": len(self.owned),
                "remain": 0 if damage == "quota" else 97-len(self.owned),
                "sub_list": {"K_DAY": ["US.OTHER", "US.ONC"]}}
        def subscribe(self, codes, types, **kwargs):
            assert types == ["K_DAY"] and kwargs == {"is_first_push": False, "subscribe_push": False, "extended_time": False, "session": "RTH"}
            self.subs.extend(codes)
            if damage == "permission": return -1, "no quote permission"
            self.owned.update(codes); return 0, "subscribed"
        def get_cur_kline(self, code, num, **kwargs):
            assert num == 130 and kwargs == {"ktype": "K_DAY", "autype": "NONE"}
            self.gets.append(code)
            if damage == "get_reject": return -1, "unknown stock"
            rows = [{"code": code, "time_key": day + " 00:00:00", "open": 10, "high": 12, "low": 9,
                "close": 11, "volume": 50, "turnover": 550, "name": "Actual SDK"}
                for day in ["2025-09-30", "2025-10-01", "2025-10-02", "2025-10-03"]]
            rows[-1]["close"] = 999  # uncompleted/post-target must never enter inputs
            if damage == "code": rows[0]["code"] = "US.OTHER"
            elif damage == "duplicate": rows[1]["time_key"] = rows[0]["time_key"]
            elif damage == "ohlc": rows[0]["low"] = 15
            elif damage == "schema": return 0, pd.DataFrame(rows).drop(columns="volume")
            elif damage == "over_num": rows *= 33
            elif damage == "empty": rows = rows[-1:]
            return 0, pd.DataFrame(rows)
        def unsubscribe(self, codes, types, unsubscribe_all):
            assert unsubscribe_all is False and types == ["K_DAY"]
            assert set(codes) <= self.owned and "US.OTHER" not in codes
            self.unsubs.extend(codes)
            if damage == "cleanup": return -1, "cannot release"
            self.owned.difference_update(codes); return 0, "released"
        def close(self): self.closed = True
    context = Context()
    sdk = SimpleNamespace(RET_OK=0, SubType=SimpleNamespace(K_DAY="K_DAY"), KLType=SimpleNamespace(K_DAY="K_DAY"),
        AuType=SimpleNamespace(NONE="NONE"), Session=SimpleNamespace(RTH="RTH"),
        SysConfig=SimpleNamespace(set_all_thread_daemon=lambda value: None), OpenQuoteContext=lambda **kwargs: context)
    monkeypatch.setattr(market, "load_module", lambda path, name: profile if path.as_posix().endswith(market.PROFILE) else fetcher)
    original_import = market.importlib.import_module
    monkeypatch.setattr(market.importlib, "import_module", lambda name, *a, **kw: sdk if name == "moomoo" else original_import(name, *a, **kw))
    monkeypatch.setattr(market.time, "sleep", lambda seconds: None)
    return args, context


def test_current_kline_real_normalizer_raw_cutoff_owned_cleanup_and_resume(tmp_path, monkeypatch):
    import pandas as pd
    args, context = current_fixture(tmp_path, monkeypatch)
    result = market.run(args)
    assert result["status"] == "ACQUIRED" and context.closed
    assert result["history_request_count"] == result["new_unique_security_touch_count"] == 0
    assert context.subs == context.gets == context.unsubs == ["US.ONC"]
    assert result["owned_subscriptions_released"] and result["subscription_after"]["total_used"] == 3
    row = result["results"][0]
    assert row["row_count"] == 3 and row["latest_date"] == "2025-10-02"
    with Path(row["path"]).open(newline="") as handle: published = list(csv.DictReader(handle))
    assert len(published) == 3 and all(float(x["close"]) == 11 for x in published)
    raw = row["current_kline_provenance"]["sdk_response"]
    original = pd.read_parquet(raw["path"])
    assert len(original) == 4 and original.iloc[-1]["close"] == 999
    assert row["current_kline_provenance"]["isolation"]["post_target_dates"] == ["2025-10-03"]
    monkeypatch.setattr(market, "load_module", lambda *a: pytest.fail("resume contacted SDK"))
    assert market.run(args)["status"] == "ALL_INTERVALS_REUSED"
    Path(raw["path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="SDK_RESPONSE_CHECKPOINT_CHANGED"): market.run(args)


@pytest.mark.parametrize("damage", ["query", "quota", "permission", "get_reject", "code", "duplicate", "ohlc", "schema", "over_num", "empty", "cleanup"])
def test_current_kline_rejection_closes_and_never_uses_history_or_other_subscriptions(tmp_path, monkeypatch, damage):
    args, context = current_fixture(tmp_path, monkeypatch, damage)
    result = market.run(args)
    assert result["status"] in {"PARTIAL", "BLOCKED"} and context.closed
    assert result["history_request_count"] == result["new_unique_security_touch_count"] == 0
    if damage != "cleanup": assert not context.owned
    else: assert result["owned_subscriptions_released"] is False
    if damage in {"query", "quota", "permission"}: assert not context.gets
    assert context.unsubs == ([] if damage in {"query", "quota", "permission"} else ["US.ONC"])
    if damage not in {"cleanup"}: assert not list((args.work_root / "intervals").glob("*.csv"))


@pytest.mark.parametrize("change", ["security", "adjustment", "retries", "mode"])
def test_current_kline_explicit_guard_precedes_network(tmp_path, monkeypatch, change):
    args, _ = current_fixture(tmp_path, monkeypatch)
    if change == "security": args.universe_csv.write_text("ticker,moomoo_symbol,security_id\nONC,US.ONC,\n")
    elif change == "adjustment": args.adjustments = ["qfq"]
    elif change == "retries": args.max_retries = 1
    else: args.acquisition_mode = "alternate-history"
    monkeypatch.setattr(market, "load_module", lambda *a: pytest.fail("network before contract guard"))
    with pytest.raises(ValueError): market.run(args)


def test_current_kline_dry_run_does_not_import_sdk(tmp_path, monkeypatch):
    args, _ = current_fixture(tmp_path, monkeypatch); args.execute = False
    monkeypatch.setattr(market, "load_module", lambda *a: pytest.fail("dryrun SDK import"))
    result = market.run(args)
    assert result["status"] == "DRY_RUN_READY" and result["plan"][0]["num"] == 130
    assert result["plan"][0]["session"] == "RTH" and result["trade_context_opened"] is False
