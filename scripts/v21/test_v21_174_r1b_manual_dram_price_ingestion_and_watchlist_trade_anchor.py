import json
from pathlib import Path

import pandas as pd

from scripts.v21 import v21_174_r1b_manual_dram_price_ingestion_and_watchlist_trade_anchor as m


def make_rows(n=35, with_ticker=True):
    rows = []
    for i in range(n):
        row = {
            "Date": f"2026-01-{(i % 28) + 1:02d}",
            "Open": 100 + i,
            "High": 102 + i,
            "Low": 99 + i,
            "Adj Close": 101 + i,
            "vol": 1000 + i,
        }
        if with_ticker:
            row["Symbol"] = " dram "
        rows.append(row)
    return pd.DataFrame(rows)


def test_flexible_column_normalization():
    df, warnings, status = m.normalize_manual_ohlcv(make_rows(3))
    assert status == "USABLE"
    assert list(df.columns) == m.BRIDGE_COLUMNS
    assert len(df) == 3
    assert not warnings


def test_ticker_normalization_to_dram():
    raw = make_rows(2)
    raw.loc[1, "Symbol"] = "MU"
    df, _warnings, _status = m.normalize_manual_ohlcv(raw)
    assert len(df) == 1
    assert df["ticker"].iloc[0] == "DRAM"


def test_file_with_no_ticker_column_accepted_as_dram_only_with_warning():
    df, warnings, status = m.normalize_manual_ohlcv(make_rows(2, with_ticker=False))
    assert status == "USABLE"
    assert "WARN_MANUAL_FILE_NO_TICKER_COLUMN" in warnings
    assert set(df["ticker"]) == {"DRAM"}


def test_missing_volume_allowed_and_filled_with_zero():
    raw = make_rows(2).drop(columns=["vol"])
    df, warnings, status = m.normalize_manual_ohlcv(raw)
    assert status == "USABLE"
    assert "WARN_VOLUME_MISSING" in warnings
    assert df["volume"].sum() == 0


def test_invalid_ohlc_rows_are_dropped():
    raw = make_rows(2)
    raw.loc[0, "Open"] = -1
    raw.loc[1, "High"] = 50
    df, warnings, status = m.normalize_manual_ohlcv(raw)
    assert df.empty
    assert "WARN_NO_VALID_DRAM_ROWS" in warnings


def test_fewer_than_30_rows_returns_insufficient_history():
    warnings = []
    bridge, _w, _status = m.normalize_manual_ohlcv(make_rows(10))
    anchor = m.build_anchor(bridge, warnings)
    assert anchor.iloc[0]["final_decision"] == "DRAM_INSUFFICIENT_HISTORY"
    assert "WARN_INSUFFICIENT_DRAM_HISTORY" in warnings


def test_no_manual_file_creates_template_and_empty_bridge(tmp_path):
    out = tmp_path / "out"
    m.main(tmp_path, out)
    summary = json.loads((out / "V21.174_R1B_summary.json").read_text(encoding="utf-8"))
    assert summary["final_status"] == "PARTIAL_PASS_V21_174_R1B_TEMPLATE_CREATED_WAIT_MANUAL_DRAM_DATA"
    assert (out / "manual_dram_daily_ohlcv_TEMPLATE.csv").exists()
    bridge = pd.read_csv(out / "dram_manual_price_bridge_daily_ohlcv.csv")
    assert bridge.empty


def test_usable_manual_file_creates_isolated_bridge_and_tactical_anchor(tmp_path):
    source_dir = tmp_path / "inputs" / "manual_prices"
    source_dir.mkdir(parents=True)
    raw = make_rows(45)
    raw["Date"] = pd.date_range("2026-01-01", periods=45, freq="D").strftime("%Y-%m-%d")
    raw.to_csv(source_dir / "dram_daily_ohlcv.csv", index=False)
    out = tmp_path / "out"
    m.main(tmp_path, out)
    summary = json.loads((out / "V21.174_R1B_summary.json").read_text(encoding="utf-8"))
    assert summary["final_status"] == "PASS_V21_174_R1B_DRAM_MANUAL_ANCHOR_READY"
    assert summary["dram_manual_bridge_created"] is True
    assert summary["dram_tactical_anchor_created"] is True
    assert pd.read_csv(out / "dram_manual_price_bridge_daily_ohlcv.csv").shape[0] == 45
    assert pd.read_csv(out / "dram_daily_tactical_anchor.csv").iloc[0]["final_decision"] == "DRAM_DAILY_TACTICAL_ANCHOR_READY"


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


def test_hard_policy_flags_remain_locked():
    assert m.POLICY["research_only"] is True
    assert m.POLICY["official_adoption_allowed"] is False
    assert m.POLICY["broker_action_allowed"] is False
    assert m.POLICY["protected_outputs_modified"] is False
    assert m.POLICY["canonical_price_panel_modified"] is False


def test_canonical_price_panel_modified_remains_false(tmp_path):
    out = tmp_path / "out"
    m.main(tmp_path, out)
    summary = json.loads((out / "V21.174_R1B_summary.json").read_text(encoding="utf-8"))
    assert summary["canonical_price_panel_modified"] is False
