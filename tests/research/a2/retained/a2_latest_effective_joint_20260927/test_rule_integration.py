"""Regression coverage for the one changed rule and unchanged execution gate."""
import json
import numpy as np
import pandas as pd
import pytest

try:
    from .engine import run_replay
    from .verify_suite import latest_effective_eligibility, check_run, maxerr
except ImportError:
    from engine import run_replay
    from verify_suite import latest_effective_eligibility, check_run, maxerr


def timing():
    return pd.DataFrame({"quarter": ["2025Q4", "2026Q1"],
                         "quarter_effective_date": pd.to_datetime(["2026-02-25", "2026-05-22"]),
                         "latest_filing_date": pd.to_datetime(["2026-02-18", "2026-05-15"])})


def panel_for(dates):
    frame = pd.DataFrame([
        {"signal_date": date, "ticker": ticker, "quarter": quarter, "avg_dollar_volume_20d": 1e9}
        for date in pd.DatetimeIndex(dates) for ticker, quarter in [("OLD", "2025Q4"), ("NEW", "2026Q1")]
    ])
    frame["new_buy_eligible"] = latest_effective_eligibility(frame, timing(), "quarter").expected_new_buy_eligible.to_numpy()
    return frame


def prices_for(calendar):
    return pd.DataFrame([{"trade_date": date, "ticker": ticker, "open": 100., "close": 100.}
                         for date in calendar for ticker in ["OLD", "NEW"]])


def test_calendar_quarter_boundary_does_not_expire_last_effective_pool():
    frame = panel_for(["2026-03-31", "2026-04-01", "2026-05-21", "2026-05-22"])
    old = frame.loc[frame.ticker.eq("OLD")]
    new = frame.loc[frame.ticker.eq("NEW")]
    assert old.new_buy_eligible.tolist() == [True, True, True, False]
    assert new.new_buy_eligible.tolist() == [False, False, False, True]
    # A later published-but-not-effective filing does not revoke the old pool.
    assert old.loc[old.signal_date.eq("2026-05-21"), "new_buy_eligible"].item()


def test_cross_quarter_old_effective_member_can_open_and_increase():
    calendar = pd.DatetimeIndex(["2026-03-31", "2026-04-01", "2026-04-02", "2026-04-06"])
    frame = panel_for(calendar[:-1])

    def policy(day, _weights, _cash):
        index = calendar.get_loc(day.signal_date.iloc[0])
        return {"OLD": .025 * (index + 1)}

    result = run_replay(prices_for(calendar), calendar, frame, policy)
    assert result.trades.action.tolist() == ["BUY", "INCREASE", "INCREASE"]
    assert result.trades.execution_date.tolist() == list(calendar[1:])
    assert result.trades.ticker.eq("OLD").all()
    assert result.trades.iloc[-1].index_units_after > result.trades.iloc[0].index_units_after


def test_only_true_effective_switch_blocks_removed_member_increase():
    calendar = pd.DatetimeIndex(["2026-05-21", "2026-05-22", "2026-05-26", "2026-05-27"])
    frame = panel_for(calendar[:2])

    def policy(day, _weights, _cash):
        return {"OLD": .05} if day.signal_date.iloc[0] == calendar[0] else {"OLD": .10, "NEW": .05}

    result = run_replay(prices_for(calendar), calendar, frame, policy)
    assert result.trades.ticker.tolist() == ["OLD", "NEW"]
    assert result.trades.execution_date.tolist() == [calendar[1], calendar[2]]
    blocked = result.diagnostics.loc[result.diagnostics.code.eq("buy_ineligible_blocked")]
    assert blocked.ticker.tolist() == ["OLD"]
    assert blocked.signal_date.tolist() == [calendar[1]]
    old_units = result.positions.loc[result.positions.ticker.eq("OLD"), "index_units"]
    assert old_units.nunique() == 1  # Existing units remain; no prohibited addition.


def test_unpublished_or_not_effective_future_quarter_never_backfills():
    frame = panel_for(["2026-02-20", "2026-02-25", "2026-05-15", "2026-05-21"])
    assert not frame.loc[frame.signal_date.eq("2026-02-20"), "new_buy_eligible"].any()
    assert not frame.loc[frame.ticker.eq("NEW"), "new_buy_eligible"].any()
    invalid = timing()
    invalid.loc[1, "quarter_effective_date"] = pd.Timestamp("2026-05-14")
    with pytest.raises(AssertionError, match="predates public filing"):
        latest_effective_eligibility(frame, invalid, "quarter")


def save_result(result, directory):
    for name in ["daily", "trades", "positions", "target_decisions"]:
        getattr(result, name).to_parquet(directory / f"{name}.parquet", index=False)
    (directory / "metadata.json").write_text(json.dumps(result.metadata), encoding="utf-8")


def test_independent_auditor_reconstructs_daily_units_and_catches_tampering(tmp_path):
    calendar = pd.DatetimeIndex(["2026-03-31", "2026-04-01", "2026-04-02"])
    frame = panel_for(calendar[:2])
    prices = prices_for(calendar)
    result = run_replay(prices, calendar, frame, lambda *_: {"OLD": .05}, capacity_fraction=.01)
    save_result(result, tmp_path)
    assert check_run(tmp_path, frame, prices, calendar, 2026)["status"] == "PASS"
    forged = result.positions.copy()
    forged.loc[forged.index[-1], "index_units"] *= 2
    forged.to_parquet(tmp_path / "positions.parquet", index=False)
    with pytest.raises(AssertionError, match="accumulated actual trade units"):
        check_run(tmp_path, frame, prices, calendar, 2026)


def test_independent_auditor_rejects_infinity_instead_of_skipping_it():
    with pytest.raises(AssertionError, match="infinite"):
        maxerr([np.inf], [np.inf])
