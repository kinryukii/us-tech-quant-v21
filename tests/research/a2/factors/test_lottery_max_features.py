"""Synthetic month/calendar/causality tests; no actual market data is read."""

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.factors.lottery_max_features import VALUE_COLUMNS, build_lottery_max_features


def fixture():
    # Explicit synthetic exchange schedule, including omitted holidays/weekends.
    calendar = pd.bdate_range("2019-12-30", "2020-04-03").difference(
        pd.to_datetime(["2020-01-01", "2020-01-20", "2020-02-17"])
    )
    returns = .008 * np.sin(np.arange(len(calendar)) * .61)
    returns[calendar.get_loc("2020-01-17")] = .12
    returns[calendar.get_loc("2020-02-12")] = .20
    rows = []
    for ticker, values in (("ABC", returns), ("QQQ", returns * .2)):
        closes = 100 * np.cumprod(1 + values)
        rows.extend({"ticker": ticker, "trade_date": date, "close": price} for date, price in zip(calendar, closes))
    return pd.DataFrame(rows), calendar, returns


def test_completed_month_end_and_holiday_execution_semantics():
    prices, calendar, returns = fixture()
    result = build_lottery_max_features(prices, calendar).set_index("trade_date")
    jan_end, feb_first = result.loc["2020-01-31"], result.loc["2020-02-03"]
    assert jan_end.next_market_session == pd.Timestamp("2020-02-03")
    assert jan_end.measurement_month == "2020-01"
    assert jan_end.factor_information_end_date == pd.Timestamp("2020-01-31")
    assert jan_end.expected_return_count == jan_end.observed_return_count == 21
    assert jan_end.full_support and jan_end.factor_available
    assert jan_end.lottery_score == pytest.approx(-.12)
    assert feb_first.lottery_score == pytest.approx(jan_end.lottery_score)
    assert result.loc["2020-02-14", "next_market_session"] == pd.Timestamp("2020-02-18")
    assert result.loc["2020-02-28", "measurement_month"] == "2020-02"
    assert result.loc["2020-02-28", "lottery_score"] == pytest.approx(-.20)
    # A signal before month end cannot use the soon-to-complete January sample.
    assert result.loc["2020-01-30", "measurement_month"] == "2019-12"
    assert not result.loc["2020-01-30", "full_support"]  # earliest calendar return has no prior close


def test_hand_computed_population_moments_share_max_support():
    prices, calendar, returns = fixture()
    row = build_lottery_max_features(prices, calendar).set_index("trade_date").loc["2020-01-31"]
    values = returns[calendar.to_period("M") == pd.Period("2020-01")]
    centered = values - values.mean()
    assert row.max_daily_return == pytest.approx(values.max())
    assert row.lottery_month_std == pytest.approx(np.sqrt(np.mean(centered ** 2)))
    assert row.lottery_month_skewness == pytest.approx(np.mean(centered ** 3) / np.mean(centered ** 2) ** 1.5)


def test_missing_session_invalidates_whole_month_and_prevents_return_bridge():
    prices, calendar, _ = fixture()
    missing = prices.loc[~(prices.ticker.eq("ABC") & prices.trade_date.eq("2020-01-16"))]
    result = build_lottery_max_features(missing, calendar).set_index("trade_date")
    row = result.loc["2020-01-31"]
    assert row.expected_return_count == 21
    assert row.observed_return_count == 19  # absent day AND next return are unavailable
    assert not row.full_support
    assert row[list(VALUE_COLUMNS)].isna().all()
    assert not result.loc["2020-01-16", "current_close_available"]
    assert result.loc["2020-02-28", "full_support"]  # independent following month recovers


def test_first_month_return_requires_prior_close_and_final_signal_requires_next_session():
    prices, calendar, _ = fixture()
    truncated = prices.loc[prices.trade_date.ge("2020-01-02")]
    result = build_lottery_max_features(truncated, calendar).set_index("trade_date")
    row = result.loc["2020-01-31"]
    assert row.observed_return_count == row.expected_return_count - 1
    assert not row.full_support
    assert not result.iloc[-1].next_session_known
    assert not result.iloc[-1].factor_available
    assert result.iloc[-1][list(VALUE_COLUMNS)].isna().all()


def test_future_price_and_calendar_extension_prefix_invariance():
    prices, calendar, _ = fixture()
    cutoff = pd.Timestamp("2020-02-14")
    cutoff_position = calendar.get_loc(cutoff)
    prefix_prices = prices.loc[prices.trade_date.le(cutoff)]
    # Both calendars include the known next exchange session for the final signal.
    short_calendar = calendar[:cutoff_position + 2]
    prefix = build_lottery_max_features(prefix_prices, short_calendar)
    all_rows = build_lottery_max_features(prices, calendar)
    pd.testing.assert_frame_equal(prefix, all_rows.loc[all_rows.trade_date.le(cutoff)].reset_index(drop=True))
    perturbed = prices.copy()
    future = perturbed.trade_date.gt(cutoff)
    rng = np.random.default_rng(447)
    perturbed.loc[future, "close"] *= np.exp(rng.normal(0, .6, future.sum()))
    changed = build_lottery_max_features(perturbed, calendar)
    pd.testing.assert_frame_equal(prefix, changed.loc[changed.trade_date.le(cutoff)].reset_index(drop=True))


def test_stock_constant_price_scale_invariance_and_no_input_mutation():
    prices, calendar, _ = fixture()
    before = prices.copy(deep=True)
    result = build_lottery_max_features(prices, calendar)
    pd.testing.assert_frame_equal(prices, before)
    scaled = prices.copy()
    scaled.loc[scaled.ticker.eq("ABC"), "close"] *= 13.0
    other = build_lottery_max_features(scaled, calendar)
    np.testing.assert_allclose(result[list(VALUE_COLUMNS)], other[list(VALUE_COLUMNS)], atol=1e-10, equal_nan=True)
    available = result.factor_available
    assert result.loc[available, "factor_information_end_date"].le(result.loc[available, "trade_date"]).all()


def test_negative_max_is_not_clipped_and_zero_variance_skew_is_undefined():
    prices, calendar, _ = fixture()
    values = np.full(len(calendar), -.01)
    values[calendar.get_loc("2020-01-17")] = -.001
    prices.loc[prices.ticker.eq("ABC"), "close"] = 100 * np.cumprod(1 + values)
    result = build_lottery_max_features(prices, calendar).set_index("trade_date")
    assert result.loc["2020-01-31", "max_daily_return"] == pytest.approx(-.001)
    assert result.loc["2020-01-31", "lottery_score"] == pytest.approx(.001)
    assert result.loc["2020-02-28", "full_support"]
    assert result.loc["2020-02-28", "lottery_month_std"] == pytest.approx(0.0, abs=1e-12)
    assert np.isnan(result.loc["2020-02-28", "lottery_month_skewness"])


def test_max_and_first_three_moments_are_algebraically_distinct():
    # Artificial small exchange calendar gives four complete January returns.
    calendar = pd.to_datetime(["2019-12-31", "2020-01-02", "2020-01-03", "2020-01-30", "2020-01-31", "2020-02-03"])
    a = .01
    sequences = {"ABC": [-np.sqrt(2)*a, 0, 0, np.sqrt(2)*a], "DEF": [-a, -a, a, a]}
    rows = []
    for ticker, values in sequences.items():
        closes = 100 * np.cumprod(np.r_[1.0, 1 + np.asarray(values), 1.0])
        rows.extend({"ticker": ticker, "trade_date": date, "close": close} for date, close in zip(calendar, closes))
    result = build_lottery_max_features(pd.DataFrame(rows), calendar)
    january = result.loc[result.trade_date.eq("2020-01-31")].set_index("ticker")
    assert january.loc["ABC", "lottery_month_std"] == pytest.approx(january.loc["DEF", "lottery_month_std"])
    assert january.loc["ABC", "lottery_month_skewness"] == pytest.approx(0.0, abs=1e-10)
    assert january.loc["DEF", "lottery_month_skewness"] == pytest.approx(0.0, abs=1e-10)
    assert january.loc["ABC", "max_daily_return"] == pytest.approx(np.sqrt(2) * a)
    assert january.loc["DEF", "max_daily_return"] == pytest.approx(a)


def test_explicit_calendar_and_price_identity_validation():
    prices, calendar, _ = fixture()
    with pytest.raises(ValueError, match="unique increasing"):
        build_lottery_max_features(prices, calendar[::-1])
    with pytest.raises(ValueError, match="duplicate"):
        build_lottery_max_features(pd.concat([prices, prices.iloc[[0]]]), calendar)
    with pytest.raises(ValueError, match="explicit market calendar"):
        build_lottery_max_features(prices, calendar[1:])
    invalid = prices.copy()
    invalid.loc[0, "close"] = -1
    with pytest.raises(ValueError, match="positive"):
        build_lottery_max_features(invalid, calendar)


def test_explicit_return_column_bypasses_raw_split_and_affine_price_changes():
    prices, calendar, returns = fixture()
    prices["economic_return"] = np.tile(returns, 2)
    # Synthetic raw-price discontinuity is deliberately unrelated to the supplied
    # validated economic series. The MAX kernel must use its explicit input.
    prices.loc[prices.trade_date.ge("2020-01-17"), "close"] *= .01
    out = build_lottery_max_features(prices, calendar, return_column="economic_return")
    row = out.set_index("trade_date").loc["2020-01-31"]
    assert row.max_daily_return == pytest.approx(.12)
    assert row.full_support
    changed = prices.copy()
    changed.loc[changed.trade_date.gt("2020-01-31"), "economic_return"] = .9
    future = build_lottery_max_features(changed, calendar, return_column="economic_return")
    pd.testing.assert_frame_equal(out.loc[out.trade_date.le("2020-01-31")].reset_index(drop=True),
                                  future.loc[future.trade_date.le("2020-01-31")].reset_index(drop=True))


def test_explicit_missing_return_invalidates_month_without_poisoning_next_observation():
    prices, calendar, returns = fixture()
    prices["economic_return"] = np.tile(returns, 2)
    prices.loc[prices.ticker.eq("ABC") & prices.trade_date.eq("2020-01-16"), "economic_return"] = np.nan
    out = build_lottery_max_features(prices, calendar, return_column="economic_return").set_index("trade_date")
    assert out.loc["2020-01-31", "observed_return_count"] == 20
    assert not out.loc["2020-01-31", "full_support"]
    assert np.isnan(out.loc["2020-01-31", "lottery_score"])
    assert out.loc["2020-02-28", "full_support"]
    # The explicit return is independent of raw-close completeness, while current
    # close is still required for a currently available signal.
    prices.loc[prices.ticker.eq("ABC") & prices.trade_date.eq("2020-02-28"), "close"] = np.nan
    out = build_lottery_max_features(prices, calendar, return_column="economic_return").set_index("trade_date")
    assert out.loc["2020-02-28", "full_support"]
    assert not out.loc["2020-02-28", "factor_available"]
