"""Synthetic invariant tests; none selects a strategy or fits on test-year data."""
import numpy as np
import pandas as pd
import pytest

try:
    from .engine import run_replay
except ImportError:
    from engine import run_replay


def sample(days=5, tickers=("A",), signals=(0, 1), price=100.0):
    calendar = pd.bdate_range("2025-01-02", periods=days)
    prices = pd.DataFrame([
        {"trade_date": date, "ticker": ticker, "open": price, "close": price}
        for date in calendar for ticker in tickers
    ])
    features = pd.DataFrame([
        {"signal_date": calendar[i], "ticker": ticker, "score": 1.0,
         "avg_dollar_volume_20d": 1_000_000.0}
        for i in signals for ticker in tickers
    ], columns=["signal_date", "ticker", "score", "avg_dollar_volume_20d"])
    return prices, calendar, features


def dated_policy(calendar, targets):
    def policy(day, weights, cash):
        date = day["signal_date"].iloc[0]
        return targets.get(date, {})
    return policy


def test_future_open_changes_fills_but_not_preceding_close_decision():
    prices, calendar, features = sample(signals=(0,))
    observations = []

    def policy(day, weights, cash):
        assert set(day["signal_date"]) == {calendar[0]}
        assert day.attrs["valuation_clock"] == "signal_close"
        observations.append((weights.copy(), cash))
        return {"A": 0.10 if cash > 0.9 else 0.05}

    original = run_replay(prices, calendar, features, policy)
    changed = prices.copy()
    changed.loc[changed.trade_date >= calendar[1], "open"] *= 3.0
    altered = run_replay(changed, calendar, features, policy)
    pd.testing.assert_frame_equal(original.target_decisions, altered.target_decisions)
    assert observations == [({}, 1.0), ({}, 1.0)]
    assert altered.trades.iloc[0].index_units == pytest.approx(original.trades.iloc[0].index_units / 3)
    assert original.trades.iloc[0].execution_date == calendar[1]


def test_missing_open_never_fills_or_backfills_from_close():
    prices, calendar, features = sample(signals=(0,))
    prices.loc[prices.trade_date == calendar[1], "open"] = np.nan
    result = run_replay(prices, calendar, features, lambda *_: {"A": .1})
    assert result.trades.empty
    assert result.positions.empty
    assert "missing_open_buy" in set(result.diagnostics.code)
    assert (result.daily.cash == 1_000_000).all()


def test_missing_open_blocks_sell_and_retains_units():
    prices, calendar, features = sample(signals=(0, 1))
    prices.loc[prices.trade_date == calendar[2], "open"] = np.nan
    policy = dated_policy(calendar, {calendar[0]: {"A": .1}, calendar[1]: {}})
    result = run_replay(prices, calendar, features, policy)
    assert list(result.trades.side) == ["BUY"]
    assert result.positions.iloc[-1].index_units == pytest.approx(1000)
    assert "missing_open_sell" in set(result.diagnostics.code)


def test_cash_identity_full_cost_each_side_and_no_synthetic_terminal_exit():
    prices, calendar, features = sample(signals=(0, 1))
    result = run_replay(prices, calendar, features,
                        dated_policy(calendar, {calendar[0]: {"A": .1}, calendar[1]: {}}))
    assert list(result.trades.action) == ["BUY", "EXIT"]
    assert list(result.trades.transaction_cost) == pytest.approx([100.0, 100.0])
    assert result.daily.iloc[-1]["nav"] == pytest.approx(999_800.0)
    assert result.daily.iloc[-1].cash == pytest.approx(999_800.0)
    assert result.trades.iloc[0].buy_fraction_nav == pytest.approx(.1)
    assert result.trades.iloc[1].sell_fraction_original_units == pytest.approx(1)
    for column in ("nav_identity_error", "cash_flow_identity_error", "cost_identity_error", "open_self_finance_error"):
        assert result.daily[column].abs().max() < 1e-7


def test_partial_reduction_records_fraction_of_original_position():
    prices, calendar, features = sample(signals=(0, 1))
    result = run_replay(prices, calendar, features,
                        dated_policy(calendar, {calendar[0]: {"A": .1}, calendar[1]: {"A": .05}}),
                        cost_bps=0)
    assert list(result.trades.action) == ["BUY", "REDUCE"]
    sale = result.trades.iloc[1]
    assert sale.sell_fraction_original_units == pytest.approx(.5)
    assert sale.index_units_after == pytest.approx(500)
    assert result.daily.iloc[-1].cash == pytest.approx(950_000)


def test_increase_classification():
    prices, calendar, features = sample(signals=(0, 1))
    result = run_replay(prices, calendar, features,
                        dated_policy(calendar, {calendar[0]: {"A": .05}, calendar[1]: {"A": .1}}),
                        cost_bps=0)
    assert list(result.trades.action) == ["BUY", "INCREASE"]


@pytest.mark.parametrize("targets,error", [
    ({"A": .10001}, "max_weight"),
    ({"A": -.1}, "negative"),
    ({"A": np.nan}, "nonfinite"),
    ({f"S{i}": .01 for i in range(21)}, "max_positions"),
    ({f"S{i}": .096 for i in range(10)}, "max_invested"),
])
def test_target_constraints_fail_clearly(targets, error):
    prices, calendar, features = sample(signals=(0,))
    with pytest.raises(ValueError, match=error):
        run_replay(prices, calendar, features, lambda *_: targets)


def test_fully_invested_reference_pays_cost_from_cash_without_leverage():
    names = tuple(f"T{i}" for i in range(20))
    prices, calendar, features = sample(tickers=names, signals=(0,))
    result = run_replay(prices, calendar, features, lambda *_: {t: .05 for t in names},
                        max_invested=1.0, cost_bps=100)
    assert result.daily.cash.min() >= 0
    assert result.daily.iloc[1].buy_cash_scale == pytest.approx(1 / 1.01)
    assert result.trades.notional.sum() + result.trades.transaction_cost.sum() == pytest.approx(1_000_000)
    assert result.daily.actual_name_count.max() == 20


def test_terminal_valuation_does_not_call_policy_or_create_trade():
    prices, calendar, features = sample(signals=(0,))
    called = []

    def policy(day, *_):
        called.append(day.attrs["signal_date"])
        return {"A": .1}

    prices.loc[prices.trade_date == calendar[-1], "close"] = 150.0
    result = run_replay(prices, calendar, features, policy)
    assert called == [calendar[0]]
    assert len(result.trades) == 1
    assert result.trades.execution_date.max() < calendar[-1]
    assert result.daily.iloc[-1]["nav"] == pytest.approx(1_049_900)
    assert result.positions.iloc[-1].index_units == 1000


def test_unknown_position_is_not_zeroed_and_certification_recovers():
    prices, calendar, features = sample(signals=(0, 1, 2))
    prices.loc[prices.trade_date < calendar[2], ["open", "close"]] = np.nan
    calls = []

    def policy(day, weights, cash):
        calls.append(day.attrs["signal_date"])
        return {"A": .05}

    result = run_replay(prices, calendar, features, policy, initial_positions={"A": 10})
    assert result.daily.iloc[:2]["nav"].isna().all()
    assert result.daily.iloc[:2].certified_nav.isna().all()
    assert result.positions.iloc[:2].index_units.tolist() == [10, 10]
    assert result.positions.iloc[:2].market_value.isna().all()
    assert calls == [calendar[2]]
    assert np.isfinite(result.daily.iloc[2].certified_nav)
    assert result.valuation_intervals.iloc[0].day_count == 2
    assert result.valuation_intervals.iloc[0].resolved
    assert pd.isna(result.daily.iloc[2].net_return)


def test_stale_marks_are_visible_and_not_certified():
    prices, calendar, features = sample(signals=(0,))
    prices.loc[prices.trade_date == calendar[2], ["open", "close"]] = np.nan
    result = run_replay(prices, calendar, features, lambda *_: {"A": .1})
    stale_day = result.daily.iloc[2]
    assert stale_day.stale_count == 1
    assert np.isfinite(stale_day["nav"])
    assert pd.isna(stale_day.certified_nav)
    assert pd.isna(stale_day.net_return)
    assert pd.isna(result.daily.iloc[3].net_return)
    assert result.valuation_intervals.iloc[0].stale_days == 1
    stale_position = result.positions.loc[result.positions.date == calendar[2]].iloc[0]
    assert stale_position.mark_date == calendar[1]


def test_capacity_buys_use_signal_adv_and_sell_discloses_last_legal_adv():
    prices, calendar, features = sample(signals=(0, 2))
    features.loc[features.signal_date == calendar[2], "avg_dollar_volume_20d"] = 900_000_000
    # The middle signal has no features: missing universe triggers cash exit.
    result = run_replay(prices, calendar, features, lambda *_: {"A": .1},
                        capacity_fraction=.01, missing_signal_policy="cash",
                        signal_start=calendar[0], signal_end=calendar[2])
    entry, exit_trade = result.trades.iloc[0], result.trades.iloc[1]
    assert entry.notional == pytest.approx(10_000)
    assert entry.capacity_adv == 1_000_000
    assert entry.capacity_adv_source_date == calendar[0]
    assert exit_trade.action == "EXIT"
    assert exit_trade.capacity_adv == 1_000_000
    assert exit_trade.capacity_adv_source_date == calendar[0]
    assert exit_trade.capacity_adv_stale
    assert not exit_trade.capacity_enforced
    assert result.target_decisions.signal_date.max() == calendar[2]
    assert calendar[-1] not in set(result.target_decisions.signal_date)


def test_missing_current_adv_blocks_buy_but_does_not_lock_exit():
    prices, calendar, features = sample(signals=(0, 1))
    features["avg_dollar_volume_20d"] = np.nan
    result = run_replay(prices, calendar, features,
                        dated_policy(calendar, {calendar[0]: {}, calendar[1]: {"A": .1}}),
                        initial_positions={"A": 100}, capacity_fraction=.01)
    assert list(result.trades.side) == ["SELL"]
    assert "sell_capacity_unknown_exit_allowed" in set(result.diagnostics.code)
    assert "missing_signal_day_adv" in set(result.diagnostics.code)


def test_blocked_sale_cannot_push_live_positions_over_limit():
    prices, calendar, features = sample(tickers=("A", "B"), signals=(0, 1))
    prices.loc[(prices.trade_date == calendar[2]) & (prices.ticker == "A"), "open"] = np.nan
    result = run_replay(prices, calendar, features,
                        dated_policy(calendar, {calendar[0]: {"A": .1}, calendar[1]: {"B": .1}}),
                        max_positions=1)
    assert result.daily.actual_name_count.max() == 1
    assert list(result.trades.ticker) == ["A"]
    assert "live_position_limit" in set(result.diagnostics.code)


def test_duplicate_prices_rejected_instead_of_choosing_convenient_quote():
    prices, calendar, features = sample()
    with pytest.raises(ValueError, match="duplicate prices"):
        run_replay(pd.concat([prices, prices.iloc[:1]]), calendar, features, lambda *_: {})


def test_empty_signal_window_can_explicitly_liquidate_prior_holding():
    prices, calendar, features = sample(signals=())
    result = run_replay(prices, calendar, features,
                        lambda *_: pytest.fail("empty-frame liquidation must not run a model"),
                        initial_positions={"A": 100}, missing_signal_policy="cash",
                        signal_start=calendar[0], signal_end=calendar[1])
    assert len(result.trades) == 1
    assert result.trades.iloc[0].action == "EXIT"
    assert result.trades.iloc[0].execution_date == calendar[1]
    assert result.daily.iloc[-1].actual_name_count == 0


def test_policy_mutation_cannot_inflate_liquidity_or_change_source_features():
    prices, calendar, features = sample(signals=(0,))
    original = features.copy(deep=True)

    def policy(day, *_):
        day.loc[:, "avg_dollar_volume_20d"] = 1e15
        day.loc[:, "score"] = -999
        return {"A": .1}

    result = run_replay(prices, calendar, features, policy, capacity_fraction=.01)
    assert result.trades.iloc[0].notional == pytest.approx(10_000)
    pd.testing.assert_frame_equal(features, original)


def test_ineligible_held_stock_cannot_be_bought_after_overnight_relative_fall():
    prices, calendar, features = sample(signals=(0,))
    features["new_buy_eligible"] = False
    prices.loc[prices.trade_date >= calendar[1], ["open", "close"]] = 50.0
    result = run_replay(prices, calendar, features, lambda *_: {"A": .1},
                        initial_cash=900_000, initial_positions={"A": 1_000})
    assert result.trades.empty
    assert result.positions.index_units.eq(1_000).all()
    assert "buy_ineligible_blocked" in set(result.diagnostics.code)
    assert result.daily.iloc[1].cash == pytest.approx(900_000)


def test_float32_roundoff_is_clipped_but_target_limits_remain_exact():
    tickers = tuple(f"A{i}" for i in range(20))
    prices, calendar, features = sample(tickers=tickers, signals=(0,))
    result = run_replay(prices, calendar, features, lambda *_: {t: .0475000005 for t in tickers})
    assert result.target_decisions.target_weight.sum() <= .95 + 1e-14
    assert result.target_decisions.target_sum.max() <= .95 + 1e-14
