from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_095_r7a_api_ninjas_earnings_provider_contract_repair.py"


def load_module():
    spec = importlib.util.spec_from_file_location("v21_095_r7a", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_contract_params_and_retry() -> None:
    module = load_module()
    calls = []

    def attempt(endpoint, params, key):
        calls.append((endpoint, dict(params), key))
        if params.get("show_upcoming") == "true":
            return {
                "http_status": 400, "payload": b"{}",
                "decoded": {"error": "premium parameter"},
                "provider_error_code": "PROVIDER_ERROR",
                "provider_error_message_redacted": "PREMIUM_OR_PLAN_RESTRICTION",
            }
        payload = json.dumps([{
            "ticker": "MU", "date": "2026-07-15",
            "earnings_timing": "after_market",
            "earnings_call_timestamp": 1784160000,
            "actual_eps": 9.9, "estimated_eps": 8.8,
        }]).encode()
        return {
            "http_status": 200, "payload": payload,
            "decoded": json.loads(payload),
            "provider_error_code": "", "provider_error_message_redacted": "",
        }

    rows, diagnostics, snapshots = module.fetch_ticker(
        "earningscalendar", "MU", "2026-06-22", "2026-10-20",
        "secret", False, attempt_fn=attempt,
    )
    assert len(calls) == 2
    assert calls[0][1] == {"ticker": "MU", "show_upcoming": "true"}
    assert calls[1][1] == {"ticker": "MU"}
    assert "start_date" not in calls[0][1] and "date_start" not in calls[0][1]
    assert diagnostics[0]["retry_attempted"] is True
    assert len(rows) == 1 and len(snapshots) == 1

    upcoming = module.build_params(
        "upcomingearnings", "MU", "2026-06-22", "2026-10-20", False
    )
    assert upcoming == {
        "ticker": "MU", "start_date": "2026-06-22",
        "end_date": "2026-10-20", "limit": 100,
    }
    assert "date_start" not in upcoming and upcoming["limit"] <= 100

    ranged = module.build_params(
        "earningscalendar", "MU", "2026-06-22", "2026-10-20", True
    )
    assert ranged["date_start"] == "2026-06-22"
    assert ranged["date_end"] == "2026-10-20"
    assert "start_date" not in ranged


def test_normalization_filters_financial_fields_and_past_rows() -> None:
    module = load_module()
    payload = [{
        "ticker": "MU", "date": "2026-06-01",
        "earnings_timing": "before_market", "actual_eps": 1,
    }, {
        "ticker": "MU", "date": "2026-07-15",
        "earnings_timing": "after_market",
        "earnings_call_timestamp": 1784160000,
        "estimated_eps": 2, "revenue_difference": 3,
    }]
    frame, past = module.normalize(
        payload, "MU", pd.Timestamp("2026-06-22T08:00:00Z"),
        "a" * 64, {"MU"}, pd.Timestamp("2026-06-22T00:00:00Z"),
        pd.Timestamp("2026-10-20T00:00:00Z"), False, 7,
    )
    assert past == 1 and len(frame) == 1
    assert frame.iloc[0]["earnings_session"] == "AFTER_MARKET"
    assert frame.iloc[0]["event_time"] != ""
    assert not bool(frame.iloc[0]["historical_backtest_usable"])
    assert bool(frame.iloc[0]["forward_observation_usable"])
    csv = frame.to_csv(index=False)
    assert "actual_eps" not in csv and "estimated_eps" not in csv
    assert "revenue_difference" not in csv


def test_key_not_persisted_in_mocked_run() -> None:
    module = load_module()
    secret = "R7A_SECRET_MUST_NOT_PERSIST"
    old = os.environ.get("EARNINGS_CALENDAR_API_KEY")
    os.environ["EARNINGS_CALENDAR_API_KEY"] = secret
    try:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "config").mkdir(parents=True)
            (root / module.D_REL.parent).mkdir(parents=True)
            (root / module.CONFIG_REL).write_text(json.dumps([{
                "source_id": module.SOURCE_ID, "enabled": True,
                "api_key_env_vars": list(module.KEY_ENV_VARS),
            }]), encoding="utf-8")
            pd.DataFrame({"ticker": ["MU"]}).to_csv(root / module.D_REL, index=False)

            def fetch_fn(mode, ticker, start, end, key, range_mode):
                assert key == secret and ticker == "MU"
                payload = json.dumps([{
                    "ticker": "MU", "date": "2026-07-15",
                    "earnings_timing": "after_market",
                }]).encode()
                diagnostic = [{
                    "ticker": ticker, "endpoint_mode": mode,
                    "endpoint_path": "/v1/earningscalendar",
                    "sanitized_params": '{"show_upcoming":"true","ticker":"MU"}',
                    "http_status": 200, "fetch_status": "SUCCESS",
                    "retry_attempted": False, "retry_reason": "",
                    "response_row_count": 1, "provider_error_code": "",
                    "provider_error_message_redacted": "",
                    "notes": "headers omitted",
                }]
                return json.loads(payload), diagnostic, [(payload, ticker)]

            summary = module.run(
                root, "earningscalendar", ["MU"], 120, True,
                False, False, False, fetch_fn=fetch_fn,
            )
            assert summary["DECISION"] == "AUTO_TICKER_EVENTS_IMPORTED_READY_FOR_FORWARD_OBSERVATION"
            assert summary["HISTORICAL_RANDOM_BACKTEST_ALLOWED"] is False
            assert summary["REQUESTS_SUCCEEDED"] == 1
            for path in root.rglob("*"):
                if path.is_file():
                    assert secret.encode() not in path.read_bytes()
    finally:
        if old is None:
            os.environ.pop("EARNINGS_CALENDAR_API_KEY", None)
        else:
            os.environ["EARNINGS_CALENDAR_API_KEY"] = old


def test_current_outputs() -> None:
    out = ROOT / "outputs/v21"
    names = [
        "v21_095_r7a_api_ninjas_request_diagnostics.csv",
        "v21_095_r7a_ticker_earnings_events_normalized.csv",
        "v21_095_r7a_auto_event_source_autofiller_report.md",
        "v21_095_r7a_auto_event_source_autofiller_summary.json",
    ]
    assert all((out / name).is_file() for name in names)
    summary = json.loads((out / names[-1]).read_text(encoding="utf-8"))
    assert summary["RESEARCH_ONLY"] is True
    assert summary["OFFICIAL_ADOPTION_ALLOWED"] is False
    assert summary["HISTORICAL_RANDOM_BACKTEST_ALLOWED"] is False
    assert summary["D_BASELINE_PRESERVED"] is True


if __name__ == "__main__":
    test_contract_params_and_retry()
    test_normalization_filters_financial_fields_and_past_rows()
    test_key_not_persisted_in_mocked_run()
    test_current_outputs()
    print("V21.095-R7A API Ninjas contract repair tests passed.")
