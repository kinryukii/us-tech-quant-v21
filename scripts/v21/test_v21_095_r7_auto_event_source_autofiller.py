from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_095_r7_auto_event_source_autofiller.py"


def load_module():
    spec = importlib.util.spec_from_file_location("v21_095_r7", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_security_and_normalization() -> None:
    module = load_module()
    fake_key = "R7_TEST_SECRET_KEY_MUST_NEVER_APPEAR"
    old = os.environ.get("EARNINGS_CALENDAR_API_KEY")
    os.environ["EARNINGS_CALENDAR_API_KEY"] = fake_key
    try:
        config = {
            "api_key_env_vars": ["EARNINGS_CALENDAR_API_KEY", "API_NINJAS_API_KEY"]
        }
        value, name = module.resolve_api_key(config)
        assert value == fake_key and name == "EARNINGS_CALENDAR_API_KEY"
        fingerprint = module.hashlib.sha256(fake_key.encode()).hexdigest()[:8]
        assert fake_key not in fingerprint
        payload = json.dumps([{
            "ticker": "MU", "date": "2026-07-15",
            "earnings_timing": "after_market",
            "eps_estimated": 9.99, "revenue_estimated": 123,
        }]).encode()
        normalized = module.normalize_events(
            json.loads(payload), "MU", pd.Timestamp("2026-06-22T08:00:00Z"),
            module.sha256_bytes(payload), "provider", "https://example.invalid",
            {"MU"}, pd.Timestamp("2026-06-22T00:00:00Z"),
            pd.Timestamp("2026-10-20T00:00:00Z"),
        )
        assert len(normalized) == 1
        row = normalized.iloc[0]
        assert row["earnings_session"] == "AFTER_MARKET"
        assert row["event_time"] == ""
        assert bool(row["forward_observation_usable"])
        assert not bool(row["historical_backtest_usable"])
        text = normalized.to_csv(index=False)
        assert fake_key not in text
        assert "eps_estimated" not in text and "revenue_estimated" not in text
    finally:
        if old is None:
            os.environ.pop("EARNINGS_CALENDAR_API_KEY", None)
        else:
            os.environ["EARNINGS_CALENDAR_API_KEY"] = old


def test_mocked_full_fetch_never_persists_key() -> None:
    module = load_module()
    fake_key = "R7_FULL_RUN_SECRET_KEY"
    old = os.environ.get("EARNINGS_CALENDAR_API_KEY")
    os.environ["EARNINGS_CALENDAR_API_KEY"] = fake_key
    try:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "config").mkdir(parents=True)
            (root / module.D_REL.parent).mkdir(parents=True)
            config = [{
                "source_id": module.SOURCE_ID, "source_category": "earnings",
                "event_type": "ticker_earnings", "source_name": "Mock provider",
                "source_type": "API_NINJAS_UPCOMING_EARNINGS",
                "source_url_or_provider": "https://example.invalid/v1/upcomingearnings",
                "enabled": True, "requires_network": True, "requires_api_key": True,
                "api_key_env_vars": list(module.ALLOWED_KEY_ENV_VARS),
                "supports_future_calendar": True, "supports_historical_pit": False,
                "pit_policy": "retrieval_timestamp_as_known_as_of",
                "source_confidence_default": "LOW",
            }]
            (root / module.CONFIG_REL).write_text(json.dumps(config), encoding="utf-8")
            pd.DataFrame({"ticker": ["MU"]}).to_csv(root / module.D_REL, index=False)

            def fake_fetcher(endpoint, ticker, start, end, api_key):
                assert api_key == fake_key
                payload = json.dumps([{
                    "ticker": ticker, "date": "2026-07-15",
                    "earnings_timing": "before_market",
                    "eps_estimated": 1.23,
                }]).encode()
                return payload, json.loads(payload), 200

            summary = module.run(
                root, "api", ["MU"], 120, True, False, fetcher=fake_fetcher
            )
            assert summary["DECISION"] == "AUTO_TICKER_EVENTS_IMPORTED_READY_FOR_FORWARD_OBSERVATION"
            assert summary["API_KEY_PRESENT"] is True
            assert summary["HISTORICAL_RANDOM_BACKTEST_ALLOWED"] is False
            assert summary["CERTIFIED_TICKER_EVENT_ROWS"] == 1
            for path in root.rglob("*"):
                if path.is_file():
                    assert fake_key.encode() not in path.read_bytes()
            normalized = pd.read_csv(
                root / module.OUT_REL / "v21_095_r7_ticker_earnings_events_normalized.csv"
            )
            assert "eps_estimated" not in normalized.columns
            assert normalized["historical_backtest_usable"].astype(str).str.upper().eq("FALSE").all()
    finally:
        if old is None:
            os.environ.pop("EARNINGS_CALENDAR_API_KEY", None)
        else:
            os.environ["EARNINGS_CALENDAR_API_KEY"] = old


def test_missing_key_outputs() -> None:
    summary_path = ROOT / "outputs/v21/v21_095_r7_auto_event_source_autofiller_summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["RESEARCH_ONLY"] is True
        assert summary["OFFICIAL_ADOPTION_ALLOWED"] is False
        assert summary["HISTORICAL_RANDOM_BACKTEST_ALLOWED"] is False
        serialized = json.dumps(summary)
        for name in module_key_names():
            value = os.environ.get(name, "")
            if value:
                assert value not in serialized


def module_key_names():
    return ("EARNINGS_CALENDAR_API_KEY", "API_NINJAS_API_KEY")


if __name__ == "__main__":
    test_security_and_normalization()
    test_mocked_full_fetch_never_persists_key()
    test_missing_key_outputs()
    print("V21.095-R7 secure earnings API autofiller tests passed.")
