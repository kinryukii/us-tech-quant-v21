"""Synthetic-only scientific and temporal checks; never loads project data."""
import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.factors.price_delay_features import _bounded_unit, build_price_delay_features


def test_explicit_returns_equal_price_ratios_when_they_describe_same_series():
    prices = synthetic_prices()
    prices["economic_return"] = prices.groupby("ticker", sort=False).close.pct_change(fill_method=None)
    expected = build_price_delay_features(prices)
    actual = build_price_delay_features(prices, return_column="economic_return")
    pd.testing.assert_frame_equal(actual, expected)


def test_explicit_returns_do_not_use_arbitrary_price_coordinate_ratios():
    prices = synthetic_prices()
    prices["economic_return"] = prices.groupby("ticker", sort=False).close.pct_change(fill_method=None)
    expected = build_price_delay_features(prices, return_column="economic_return")
    prices["close"] = prices.close + np.linspace(1, 100, len(prices))
    actual = build_price_delay_features(prices, return_column="economic_return")
    pd.testing.assert_frame_equal(actual, expected)


def test_explicit_return_gap_is_not_bridged_or_compounded():
    prices = synthetic_prices()
    prices["economic_return"] = prices.groupby("ticker", sort=False).close.pct_change(fill_method=None)
    gap_date = sorted(prices.trade_date.unique())[200]
    prices.loc[prices.ticker.eq("TEST") & prices.trade_date.eq(gap_date), "economic_return"] = np.nan
    out = build_price_delay_features(prices, return_column="economic_return")
    indexed = out.loc[out.ticker.eq("TEST")].set_index("trade_date")
    assert indexed.loc[sorted(prices.trade_date.unique())[221], "price_delay_matched_observations_stale"] == 125
    prefix = prices.loc[prices.trade_date.le(sorted(prices.trade_date.unique())[300])]
    pd.testing.assert_frame_equal(build_price_delay_features(prefix, return_column="economic_return"), out.loc[out.trade_date.le(prefix.trade_date.max())].reset_index(drop=True))


@pytest.mark.parametrize("bad", [np.inf, -np.inf, -1.01])
def test_explicit_return_validation_rejects_impossible_values(bad):
    prices = synthetic_prices()
    prices["economic_return"] = prices.groupby("ticker", sort=False).close.pct_change(fill_method=None)
    prices.loc[100, "economic_return"] = bad
    with pytest.raises(ValueError, match="explicit returns"):
        build_price_delay_features(prices, return_column="economic_return")


def synthetic_prices(n=420, seed=2718, kind="mixed"):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2018-01-01", periods=n)
    market_return = rng.normal(0.0002, 0.012, n)
    market_return[0] = 0
    delayed = np.roll(market_return, 3)
    delayed[:3] = 0
    if kind == "current":
        stock_return = 0.8 * market_return
    elif kind == "delayed":
        stock_return = 1.3 * delayed
    elif kind == "null":
        stock_return = rng.normal(0, 0.014, n)
    else:
        stock_return = 0.6 * market_return + 0.5 * delayed + rng.normal(0, 0.009, n)
    stock_return[0] = 0
    return pd.concat([
        pd.DataFrame({"ticker": ticker, "trade_date": dates,
                      "close": 100 * np.cumprod(1 + returns)})
        for ticker, returns in (("QQQ", market_return), ("TEST", stock_return))
    ], ignore_index=True)


def direct_ols_at(prices, end, window=126, lags=5):
    """Independent least-squares reference from the explicit final design."""
    wide = prices.pivot(index="trade_date", columns="ticker", values="close").sort_index()
    returns = wide.pct_change(fill_method=None)
    design = pd.concat([returns.QQQ.shift(k).rename(f"m{k}") for k in range(lags + 1)], axis=1)
    sample = pd.concat([returns.TEST.rename("y"), design], axis=1).iloc[end - window + 1:end + 1].dropna()
    y = sample.y.to_numpy()
    current = np.column_stack([np.ones(len(sample)), sample.m0])
    full = np.column_stack([np.ones(len(sample)), sample.drop(columns="y")])
    beta0 = np.linalg.lstsq(current, y, rcond=None)[0]
    betaf = np.linalg.lstsq(full, y, rcond=None)[0]
    total = ((y - y.mean()) ** 2).sum()
    r0 = 1 - ((y - current @ beta0) ** 2).sum() / total
    rf = 1 - ((y - full @ betaf) ** 2).sum() / total
    return len(sample), beta0[1], r0, rf, 1 - r0 / rf


def test_known_current_only_response_has_zero_delay_and_recovers_beta():
    out = build_price_delay_features(synthetic_prices(kind="current"))
    valid = out.dropna(subset=["price_delay_d1"])
    assert len(valid) > 200
    np.testing.assert_allclose(valid.price_delay_d1, 0, atol=2e-12)
    np.testing.assert_allclose(valid.price_delay_beta_stale, 0.8, atol=2e-12)
    np.testing.assert_allclose(valid.price_delay_r2_full_stale, 1, atol=2e-12)
    np.testing.assert_allclose(valid.price_delay_r2_restricted_stale, 1, atol=2e-12)
    assert valid.price_delay_full_rank_stale.eq(7).all()


def test_known_lagged_response_is_recovered_by_full_model():
    out = build_price_delay_features(synthetic_prices(kind="delayed"))
    valid = out.dropna(subset=["price_delay_d1"])
    np.testing.assert_allclose(valid.price_delay_r2_full_stale, 1, atol=2e-12)
    assert valid.price_delay_d1.mean() > 0.96
    assert valid.price_delay_r2_restricted_stale.mean() < 0.04


def test_explicit_ols_same_sample_with_missing_prices_and_market_lags():
    prices = synthetic_prices(n=360)
    dates = np.sort(prices.trade_date.unique())
    # Remove an entire stock row; retain a missing market calendar row.
    prices = prices.loc[~(prices.ticker.eq("TEST") & prices.trade_date.eq(dates[236]))].copy()
    prices.loc[prices.ticker.eq("QQQ") & prices.trade_date.eq(dates[243]), "close"] = np.nan
    prices.loc[prices.ticker.eq("TEST") & prices.trade_date.eq(dates[254]), "close"] = np.nan
    out = build_price_delay_features(prices).set_index("trade_date")
    measurement = 300
    actual = out.loc[dates[measurement + 21]]
    count, beta, restricted, full, delay = direct_ols_at(prices, measurement)
    assert count == 115  # 2+2 own-return gaps; 7 market/lag invalid rows.
    assert actual.price_delay_matched_observations_stale == count
    np.testing.assert_allclose(
        [actual.price_delay_beta_stale, actual.price_delay_r2_restricted_stale,
         actual.price_delay_r2_full_stale, actual.price_delay_d1],
        [beta, restricted, full, delay], rtol=2e-10, atol=2e-12)
    # A tempting restricted-only mask would use extra rows and change beta.
    wide = prices.pivot(index="trade_date", columns="ticker", values="close").sort_index()
    pair = wide.pct_change(fill_method=None).iloc[measurement - 125:measurement + 1].dropna()
    alternative = np.linalg.lstsq(np.column_stack([np.ones(len(pair)), pair.QQQ]), pair.TEST, rcond=None)[0][1]
    assert len(pair) > count
    assert abs(alternative - beta) > 1e-4


def test_characteristic_lag_counts_market_sessions_even_when_stock_rows_absent():
    prices = synthetic_prices(n=250)
    dates = np.sort(prices.trade_date.unique())
    absent = dates[[168, 172, 174]]
    prices = prices.loc[~(prices.ticker.eq("TEST") & prices.trade_date.isin(absent))]
    out = build_price_delay_features(prices).set_index("trade_date")
    assert len(out) == len(dates)
    assert out.loc[dates[200], "price_delay_measurement_date"] == dates[179]
    assert out.loc[dates[200], "price_delay_matched_observations_stale"] == 120
    assert out.loc[dates[168], "current_close_available"] == False
    assert np.isnan(out.loc[dates[168], "price_delay_d1"])
    # First complete lagged-design return is session 6; 100th is 105.
    assert out.price_delay_d1.first_valid_index() == pd.Timestamp(dates[126])
    assert out.loc[dates[:21], "price_delay_measurement_date"].isna().all()


def test_appending_arbitrary_future_data_preserves_entire_prefix():
    prices = synthetic_prices(n=480)
    dates = np.sort(prices.trade_date.unique())
    cutoff = dates[290]
    prefix = build_price_delay_features(prices.loc[prices.trade_date.le(cutoff)])
    changed = prices.copy()
    future = changed.trade_date.gt(cutoff)
    rng = np.random.default_rng(19)
    changed.loc[future, "close"] *= np.exp(rng.normal(0, 0.4, future.sum()))
    expanded = build_price_delay_features(changed)
    pd.testing.assert_frame_equal(prefix, expanded.loc[expanded.trade_date.le(cutoff)].reset_index(drop=True), check_exact=True)


def test_information_after_measurement_close_cannot_change_stale_estimate():
    prices = synthetic_prices(n=350)
    dates = np.sort(prices.trade_date.unique())
    signal, measurement = 300, 279
    original = build_price_delay_features(prices).set_index("trade_date").loc[dates[signal]]
    changed = prices.copy()
    later = changed.trade_date.gt(dates[measurement])
    changed.loc[later, "close"] *= np.linspace(0.7, 1.4, later.sum())
    updated = build_price_delay_features(changed).set_index("trade_date").loc[dates[signal]]
    pd.testing.assert_series_equal(original, updated, check_exact=True)


def test_weak_full_r2_gate_retains_diagnostics_without_creating_signal():
    prices = synthetic_prices(n=170)
    wide = prices.pivot(index="trade_date", columns="ticker", values="close").sort_index()
    market_returns = wide.QQQ.pct_change(fill_method=None)
    design = np.column_stack([np.ones(126), *[market_returns.shift(k).iloc[6:132] for k in range(6)]])
    rng = np.random.default_rng(31)
    noise = rng.normal(0, 0.01, 126)
    residual = noise - design @ np.linalg.lstsq(design, noise, rcond=None)[0]
    stock_returns = np.zeros(len(wide))
    stock_returns[6:132] = residual
    prices.loc[prices.ticker.eq("TEST"), "close"] = 100 * np.cumprod(1 + stock_returns)
    row = build_price_delay_features(prices).set_index("trade_date").loc[wide.index[152]]
    assert row.price_delay_matched_observations_stale == 126
    assert row.price_delay_r2_full_stale < 1e-12
    assert row.price_delay_weak_r2_stale == 1
    assert np.isnan(row.price_delay_d1)


def test_null_delay_is_mechanically_positive_not_evidence_of_premium():
    out = build_price_delay_features(synthetic_prices(n=3000, seed=6101, kind="null"))
    valid = out.dropna(subset=["price_delay_d1"])
    assert len(valid) > 2000
    # Nested OLS adds five regressors: positive D1 under no relation is expected.
    assert valid.price_delay_d1.mean() > 0.6
    assert (valid.price_delay_r2_full_stale >= valid.price_delay_r2_restricted_stale - 1e-12).all()
    assert valid.price_delay_d1.between(0, 1).all()


def test_degenerate_series_yields_missing_estimate_and_no_infinity():
    prices = synthetic_prices(n=260)
    prices.loc[prices.ticker.eq("QQQ"), "close"] = 100
    out = build_price_delay_features(prices)
    assert out.price_delay_d1.isna().all()
    assert out.price_delay_beta_stale.isna().all()
    assert not np.isinf(out.price_delay_d1).any()


def test_only_tiny_roundoff_is_clipped_material_violations_fail():
    np.testing.assert_array_equal(_bounded_unit(np.array([-1e-12, 1 + 1e-12]), "check"), [0, 1])
    for value in (-1e-5, 1 + 1e-5, np.inf, -np.inf):
        with pytest.raises(ArithmeticError):
            _bounded_unit(np.array([value]), "check")


@pytest.mark.parametrize("problem", ["duplicate", "negative", "infinite", "outside_calendar"])
def test_invalid_input_is_rejected(problem):
    prices = synthetic_prices(n=180)
    if problem == "duplicate":
        prices = pd.concat([prices, prices.iloc[[0]]], ignore_index=True)
    elif problem == "negative":
        prices.loc[1, "close"] = -1
    elif problem == "infinite":
        prices.loc[1, "close"] = np.inf
    else:
        prices.loc[prices.ticker.eq("TEST") & prices.trade_date.eq(prices.trade_date.max()), "trade_date"] += pd.Timedelta(days=30)
    with pytest.raises(ValueError):
        build_price_delay_features(prices)
