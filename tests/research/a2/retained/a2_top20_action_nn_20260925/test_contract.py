from __future__ import annotations

import importlib.util
import sys

import numpy as np
import pandas as pd
import pytest

import safe_inputs
import score_corrected
import train


def e5_module():
    spec = importlib.util.spec_from_file_location("a2_e5_contract_test", train.E5)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_physical_future_label_date_rejected(tmp_path):
    path = tmp_path / "dates.parquet"
    pd.DataFrame({"label_end_date": pd.to_datetime(["2025-12-31", "2026-01-02"])}).to_parquet(path)
    with pytest.raises(RuntimeError, match="PHYSICAL_DATE_BOUNDARY_UNPROVEN"):
        safe_inputs.physical_before_cutoff(path, "label_end_date")


def test_sequence_ends_at_signal_and_label_needs_future_session():
    dates = pd.bdate_range("2025-01-02", periods=40)
    close = np.arange(100.0, 140.0)
    prices = pd.concat([
        pd.DataFrame({"ticker": "AAA", "trade_date": dates, "open": close + 0.5, "close": close}),
        pd.DataFrame({"ticker": "QQQ", "trade_date": dates, "open": 1.0, "close": 1.0}),
    ], ignore_index=True)
    signal = dates[15]
    panel = pd.DataFrame({"signal_date": [signal], "target_end_date": [dates[36]],
                          "ticker": ["AAA"], "raw_rank": [1]})
    row = train.make_panel(panel, prices)[0].iloc[0]
    assert row.lag_ret_00 == pytest.approx(close[15] / close[14] - 1)
    assert row.lag_ret_01 == pytest.approx(close[14] / close[13] - 1)
    assert row.entry_date == dates[16] and row.label_end_date_exec == dates[36]
    assert row.y_exec20 == pytest.approx((close[36] + .5) / (close[16] + .5) - 1)
    assert not any("target" in column or "future" in column for column in train.FEATURES)


def test_e5_actual_share_state_after_skipped_buy_and_cost_identity():
    e5 = e5_module()
    dynamic = score_corrected.dynamic_e5_replay(e5)
    dates = pd.to_datetime(["2026-01-05", "2026-01-06"])
    prices_missing = pd.DataFrame([
        {"ticker": "QQQ", "trade_date": dates[0], "open": 1.0, "close": 1.0},
        {"ticker": "QQQ", "trade_date": dates[1], "open": 1.0, "close": 1.0},
        {"ticker": "AAA", "trade_date": dates[1], "open": 10.0, "close": 10.0},
    ])
    states = []

    def callback(signal, shares, pre_values, nav):
        states.append(set(shares))
        return {"AAA": .05} if len(states) == 1 else {}

    signals = {dates[0]: pd.Timestamp("2026-01-02"), dates[1]: dates[0]}
    result = dynamic("TEST_MISSING", callback, prices_missing, list(dates), signals)
    assert states == [set(), set()]
    assert result.daily.skipped_buy_count.tolist() == [1, 0]
    assert result.trades.empty
    prices_full = prices_missing.copy()
    prices_full.loc[len(prices_full)] = {"ticker": "AAA", "trade_date": dates[0], "open": 10.0, "close": 10.0}

    def buy_then_exit(signal, shares, pre_values, nav):
        return {"AAA": .05} if signal == pd.Timestamp("2026-01-02") else {}

    done = dynamic("TEST_COST", buy_then_exit, prices_full, list(dates), signals)
    assert done.trades.side.tolist() == ["BUY", "SELL"]
    assert float(done.daily.cost_identity_error.abs().max()) < 1e-12
    assert float(done.daily.nav_identity_error.abs().max()) < 1e-12
