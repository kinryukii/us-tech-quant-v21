"""Synthetic technical acceptance; no market files or model fitting."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "trainer_bundle"))
import ledger
from logged_execution import run_logged_replay


def test_partial_sale_and_cash_identity():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    prices = pd.DataFrame({"trade_date": dates, "ticker": ["AAA"] * 3,
                           "open": [10.0] * 3, "close": [10.0] * 3})
    def decide(signal, shares, values, nav):
        target = 0.5 if signal == dates[0] else 0.25
        return {"AAA": target}, {"AAA": {"raw_target_weight": target,
                                             "raw_action_logit": 0.123,
                                             "model_sha256": "synthetic"}}
    replay, decisions, details = run_logged_replay(
        "SYNTH", decide, prices, dates[1:], {dates[1]: dates[0], dates[2]: dates[1]},
        input_identity="synthetic", model_identity="synthetic")
    direct = ledger.replay("SYNTH", lambda s, q, v, n: decide(s, q, v, n)[0],
                           prices, dates[1:], {dates[1]: dates[0], dates[2]: dates[1]})
    assert replay.daily.equals(direct.daily) and replay.trades.equals(direct.trades)
    assert len(decisions) == 2 and len(details) == 2
    buy, sell = details.iloc[0], details.iloc[1]
    assert buy.side == "BUY" and sell.side == "SELL"
    assert 0 < sell.sell_shares_over_before_shares < 1
    assert abs(buy.shares_after_execution - sell.shares_before_execution) < 1e-12
    assert np.allclose(details.groupby("execution_date").transaction_cost.sum().to_numpy(),
                       replay.daily.transaction_cost_amount.to_numpy())
    assert (replay.daily.nav_identity_error.abs() < 1e-12).all()
    assert (details.cash_after_execution_day >= 0).all()


def test_missing_open_is_visible():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    prices = pd.DataFrame({"trade_date": dates, "ticker": ["AAA", "AAA"],
                           "open": [10.0, np.nan], "close": [10.0, 10.0]})
    def decide(signal, shares, values, nav):
        return {"AAA": 0.5}, {"AAA": {"raw_target_weight": 0.5}}
    replay, _, details = run_logged_replay("SYNTH", decide, prices, [dates[1]],
                                           {dates[1]: dates[0]}, input_identity="synthetic",
                                           model_identity="synthetic")
    assert replay.daily.skipped_buy_count.iloc[0] == 1
    assert details.iloc[0].side == "NONE"
    assert details.iloc[0].unfilled_or_unresolved_reason == "missing_open_skipped_entry"


def test_zero_weight_action_is_visible():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    prices = pd.DataFrame({"trade_date": dates, "ticker": ["AAA", "AAA"],
                           "open": [10.0, 10.0], "close": [10.0, 10.0]})
    def decide(signal, shares, values, nav):
        return {}, {"AAA": {"raw_action_logit": -5.0}}
    _, decisions, details = run_logged_replay(
        "SYNTH", decide, prices, [dates[1]], {dates[1]: dates[0]},
        input_identity="synthetic", model_identity="synthetic")
    assert len(decisions) == len(details) == 1
    assert details.iloc[0].side == "NONE" and details.iloc[0].feasible_target_weight == 0
    assert details.iloc[0].raw_action_logit == -5.0


def test_missing_open_blocks_exit():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    prices = pd.DataFrame({"trade_date": dates, "ticker": ["AAA"] * 3,
                           "open": [10.0, 10.0, np.nan], "close": [10.0] * 3})
    def decide(signal, shares, values, nav):
        return ({"AAA": 0.5} if signal == dates[0] else {}), {}
    replay, _, details = run_logged_replay(
        "SYNTH", decide, prices, dates[1:], {dates[1]: dates[0], dates[2]: dates[1]},
        input_identity="synthetic", model_identity="synthetic")
    last = details.iloc[-1]
    assert replay.daily.blocked_sell_count.iloc[-1] == 1
    assert last.side == "NONE" and last.shares_before_execution > 0
    assert last.unfilled_or_unresolved_reason == "missing_open_blocked_exit"
    assert last.shares_after_execution == last.shares_before_execution


def test_cash_scaled_buys():
    signal, execution = pd.to_datetime(["2024-01-02", "2024-01-03"])
    prices = pd.DataFrame({"trade_date": [signal, signal, execution, execution],
                           "ticker": ["AAA", "BBB"] * 2,
                           "open": [10.0] * 4, "close": [10.0] * 4})
    def decide(signal, shares, values, nav):
        return {"AAA": 0.6, "BBB": 0.6}, {}
    replay, _, details = run_logged_replay(
        "SYNTH", decide, prices, [execution], {execution: signal},
        input_identity="synthetic", model_identity="synthetic")
    assert replay.daily.buy_cash_scale.iloc[0] < 1
    assert (details.side == "BUY").all()
    assert (details.unfilled_or_unresolved_reason == "cash_scaled_partial_fill").all()
    assert replay.daily.nav_identity_error.abs().max() < 1e-12


if __name__ == "__main__":
    test_partial_sale_and_cash_identity()
    test_missing_open_is_visible()
    test_zero_weight_action_is_visible()
    test_missing_open_blocks_exit()
    test_cash_scaled_buys()
    print("SYNTHETIC_LOGGED_EXECUTION_PASS")
