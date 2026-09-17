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
