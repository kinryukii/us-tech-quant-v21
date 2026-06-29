import json
from pathlib import Path

import pandas as pd

from scripts.v21 import v21_174_r1c_auto_dram_price_fetch_and_cache as m


class MockYF:
    @staticmethod
    def download(*_args, **_kwargs):
        return make_ohlcv(45)


class FailingYF:
    @staticmethod
    def download(*_args, **_kwargs):
        raise RuntimeError("network down")


def make_ohlcv(n=45, ticker=True):
    rows = []
    dates = pd.date_range("2026-04-01", periods=n, freq="D")
    for i, d in enumerate(dates):
        row = {
            "Date": d,
            "Open": 20 + i * 0.1,
            "High": 20.5 + i * 0.1,
            "Low": 19.8 + i * 0.1,
            "Close": 20.2 + i * 0.1,
            "Volume": 10000 + i,
        }
        if ticker:
            row["Symbol"] = "DRAM"
        rows.append(row)
    return pd.DataFrame(rows)


def write_manual(root: Path, n=45):
    d = root / "inputs" / "manual_prices"
    d.mkdir(parents=True)
    make_ohlcv(n).to_csv(d / "dram_daily_ohlcv.csv", index=False)


def test_yfinance_fetch_function_can_be_mocked_successfully():
    df, audit = m.fetch_yfinance(MockYF)
    assert audit["success"] is True
    assert len(df) == 45
    assert audit["latest_date"] == "2026-05-15"


def test_yfinance_failure_falls_back_to_manual_input(tmp_path):
    write_manual(tmp_path, 45)
    out = tmp_path / "out"
    m.main(tmp_path, out, FailingYF)
    summary = json.loads((out / "V21.174_R1C_summary.json").read_text(encoding="utf-8"))
    assert summary["auto_fetch_success"] is False
    assert summary["manual_fallback_used"] is True
    assert summary["source_method_used"] == "MANUAL_FALLBACK"
    assert summary["final_status"] == "PARTIAL_PASS_V21_174_R1C_USED_MANUAL_FALLBACK"


def test_no_yfinance_installed_should_not_crash(monkeypatch):
    real_import = m.importlib.import_module

    def fake_import(name):
        if name == "yfinance":
            raise ModuleNotFoundError("no module")
        return real_import(name)

    monkeypatch.setattr(m.importlib, "import_module", fake_import)
    df, audit = m.fetch_yfinance(None)
    assert df.empty
    assert audit["success"] is False
    assert "YFINANCE_IMPORT_FAILED" in audit["error_message"]


def test_flexible_manual_fallback_column_normalization():
    raw = pd.DataFrame({"time": ["2026-01-01"], "code": [" dram "], "o": [10], "h": [11], "l": [9], "c": [10.5], "v": [100]})
    df, warnings, status = m.r1b.normalize_manual_ohlcv(raw)
    assert status == "USABLE"
    assert df["ticker"].iloc[0] == "DRAM"
    assert not warnings


def test_insufficient_history_produces_warn_status(tmp_path):
    write_manual(tmp_path, 10)
    out = tmp_path / "out"
    m.main(tmp_path, out, FailingYF)
    summary = json.loads((out / "V21.174_R1C_summary.json").read_text(encoding="utf-8"))
    assert summary["final_status"] == "WARN_V21_174_R1C_INSUFFICIENT_DRAM_HISTORY"
    assert "WARN_INSUFFICIENT_DRAM_HISTORY" in summary["warnings"]


def test_valid_data_creates_bridge_and_tactical_anchor(tmp_path):
    out = tmp_path / "out"
    m.main(tmp_path, out, MockYF)
    summary = json.loads((out / "V21.174_R1C_summary.json").read_text(encoding="utf-8"))
    assert summary["final_status"] == "PASS_V21_174_R1C_AUTO_DRAM_PRICE_READY"
    assert summary["dram_price_bridge_created"] is True
    assert summary["dram_tactical_anchor_created"] is True
    assert pd.read_csv(out / "dram_auto_price_bridge_daily_ohlcv.csv")["source_method"].iloc[0] == "AUTO_YFINANCE"


def test_execution_replay_creates_non_empty_results_when_enough_history_exists(tmp_path):
    out = tmp_path / "out"
    m.main(tmp_path, out, MockYF)
    replay = pd.read_csv(out / "dram_execution_simulation_results.csv")
    assert not replay.empty
    assert {"BASE", "TIGHT"}.issubset(set(replay["variant"]))


def test_same_day_stop_and_tp_prioritizes_stop():
    path = pd.DataFrame([{"date": pd.Timestamp("2026-01-02"), "open": 98, "high": 106, "low": 94, "close": 100}])
    plan = {
        "trade_date": "",
        "ranking_date": "2026-01-01",
        "ticker": "DRAM",
        "strategy_state": "manual_watchlist_tactical_anchor",
        "planned_entry": 98.0,
        "no_chase_above": 103.0,
        "stop_loss": 95.0,
        "take_profit_1": 102.5,
        "take_profit_2": 105.5,
        "risk_per_share": 3.0,
        "trade_allowed": True,
        "invalid_reason": "",
    }
    sim, _audit = m.v174.simulate_trade(plan, path, "5D", 5)
    assert sim["exit_reason"] == "STOP_LOSS"


def test_all_hard_policy_flags_remain_locked():
    assert m.POLICY["research_only"] is True
    assert m.POLICY["official_adoption_allowed"] is False
    assert m.POLICY["broker_action_allowed"] is False
    assert m.POLICY["protected_outputs_modified"] is False
    assert m.POLICY["canonical_price_panel_modified"] is False


def test_failed_auto_fetch_and_missing_manual_fallback_returns_warn(tmp_path):
    out = tmp_path / "out"
    m.main(tmp_path, out, FailingYF)
    summary = json.loads((out / "V21.174_R1C_summary.json").read_text(encoding="utf-8"))
    assert summary["final_status"] == "WARN_V21_174_R1C_AUTO_FETCH_FAILED_WAIT_MANUAL_INPUT"
    assert summary["decision"] == "WAIT_MANUAL_DRAM_DAILY_OHLCV_INPUT"
    assert summary["canonical_price_panel_modified"] is False
