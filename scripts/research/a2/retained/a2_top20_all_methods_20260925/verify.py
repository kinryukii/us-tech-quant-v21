"""Boundary checks on the completed frozen study; no fit or score mutation."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import batch2026
import optimize_route

ROOT = Path(__file__).resolve().parent


def main():
    manifest = batch2026.frozen()
    assert manifest["primary_pre2026_selection"] == "RAW"
    trial = pd.read_csv(ROOT / "supervised_trials.csv")
    fitted = trial.loc[trial.fold.eq("FINAL")]
    assert len(trial) == 27 and len(fitted) == 9
    assert pd.to_datetime(trial.train_max_label_end).lt("2026-01-01").all()
    assert pd.to_datetime(fitted.train_max_label_end).max() == pd.Timestamp("2025-12-31")
    test = ROOT / "test2026"
    receipt = json.loads((test / "prediction_receipt.json").read_text(encoding="utf-8"))
    assert receipt["economic_price_reads"] == receipt["model_fit_calls"] == 0
    assert receipt["prediction_sha256"] == batch2026.sha(test / "predictions.parquet")
    summary = pd.read_csv(test / "summary.csv")
    assert len(summary) == 6 and summary.days.eq(156).all()
    for item in summary.itertuples():
        name = item.candidate.lower()
        day = pd.read_parquet(test / f"{name}_daily.parquet")
        trades = pd.read_parquet(test / f"{name}_executed.parquet")
        assert (day.nav > 0).all() and day.cash_weight.min() >= -1e-10
        assert day.gross_exposure.max() <= 1 + 1e-9
        assert day.nav_identity_error.abs().max() < 1e-8
        assert day.cost_identity_error.abs().max() < 1e-8
        assert day.turnover_identity_error.abs().max() < 1e-8
        assert trades.remaining_cash.min() >= -1e-9
        assert trades.sold_shares_over_prior_shares.max() <= 1 + 1e-9
        assert trades.buy_notional_over_pretrade_nav.max() <= .101
    # A stale mark may value an existing position, but cannot execute its sale.
    replay = optimize_route.load_e5()
    dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
    prices = pd.DataFrame([
        {"trade_date": d, "ticker": "QQQ", "open": 1.0, "close": 1.0} for d in dates
    ] + [
        {"trade_date": dates[1], "ticker": "XYZ", "open": 10.0, "close": 10.0},
        {"trade_date": dates[2], "ticker": "XYZ", "open": np.nan, "close": np.nan},
    ])
    result = replay("MISSING_OPEN_TEST", lambda s, *_: {"XYZ": .5} if s == dates[0] else {},
                    prices, list(dates[1:]), {dates[1]: dates[0], dates[2]: dates[1]})
    assert len(result.trades) == 1 and result.trades.iloc[0].side == "BUY"
    assert result.daily.iloc[-1].blocked_sell_count == 1
    assert result.daily.iloc[-1].actual_name_count == 1
    print("VERIFIED frozen hashes, maturity, cash/cost identities, exposure, actual shares, missing-open block")


if __name__ == "__main__":
    main()
