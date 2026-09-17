"""Synthetic arithmetic/time tests; no financial outcomes are read."""

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.factors.systematic_tail_features import FACTOR_COLUMNS, build_systematic_tail_features


def price_frame(market_returns, stock_returns):
    dates = pd.bdate_range("2020-01-01", periods=len(market_returns) + 1)
    rows = []
    for ticker, returns in (("QQQ", market_returns), ("ABC", stock_returns)):
        closes = 100 * np.cumprod(np.r_[1.0, 1.0 + np.asarray(returns)])
        rows.extend({"ticker": ticker, "trade_date": date, "close": close} for date, close in zip(dates, closes))
    return pd.DataFrame(rows)


def test_hand_computed_quadrants_and_residual_coskewness():
    x = np.array([-.04, -.02, -.01, .01, .02, .06])
    y = np.array([-.02, .03, -.05, -.03, .01, .08])
    result = build_systematic_tail_features(price_frame(x, y), window=6, min_observations=6).iloc[-1]
    denominator = np.sum(x ** 2)
    expected = [np.sum(y.clip(max=0) * x.clip(max=0)), np.sum(y.clip(min=0) * x.clip(min=0)),
                -np.sum(y.clip(min=0) * x.clip(max=0)), -np.sum(y.clip(max=0) * x.clip(min=0))]
    for name, value in zip(("semibeta_n", "semibeta_p", "semibeta_m_minus", "semibeta_m_plus"), expected):
        assert result[name] == pytest.approx(value / denominator, abs=1e-12)
    assert result.beta_uncentered == pytest.approx(np.sum(x * y) / denominator)
    ux, uy = x - x.mean(), y - y.mean()
    beta = np.dot(ux, uy) / np.dot(ux, ux)
    residual = uy - beta * ux
    coskewness = np.mean(residual * ux ** 2) / (np.sqrt(np.mean(residual ** 2)) * np.mean(ux ** 2))
    assert result.beta_centered == pytest.approx(beta)
    assert result.market_coskewness == pytest.approx(coskewness)
    assert result.coskewness_score == pytest.approx(-coskewness)
    assert result.own_skewness == pytest.approx(np.mean(uy ** 3) / np.mean(uy ** 2) ** 1.5)
    assert result.semibeta_signed_score == pytest.approx(np.sum(y[x < 0] * x[x < 0]) / denominator)


def test_prefix_and_future_price_perturbation_invariance():
    rng = np.random.default_rng(9104)
    x = rng.normal(.0001, .01, 190)
    y = .8 * x + rng.normal(0, .01, 190)
    prices = price_frame(x, y)
    cutoff = prices.trade_date.sort_values().unique()[145]
    before = build_systematic_tail_features(prices.loc[prices.trade_date.le(cutoff)])
    all_rows = build_systematic_tail_features(prices)
    pd.testing.assert_frame_equal(before, all_rows.loc[all_rows.trade_date.le(cutoff)].reset_index(drop=True))
    changed = prices.copy()
    future = changed.trade_date.gt(cutoff)
    changed.loc[future, "close"] *= np.exp(rng.normal(0, .4, future.sum()))
    perturbed = build_systematic_tail_features(changed)
    pd.testing.assert_frame_equal(before, perturbed.loc[perturbed.trade_date.le(cutoff)].reset_index(drop=True))


def test_matched_calendar_missing_session_invalidates_two_returns():
    prices = price_frame([.01, -.02, .03, -.04, .05, -.02], [.02, .03, -.01, -.03, .01, .04])
    dates = sorted(prices.trade_date.unique())
    # Removing a stock row must not produce a two-session pct_change bridge.
    prices = prices.loc[~(prices.ticker.eq("ABC") & prices.trade_date.eq(dates[3]))]
    result = build_systematic_tail_features(prices, window=4, min_observations=2).set_index("trade_date")
    assert result.loc[dates[5], "matched_observations"] == 2
    assert not result.loc[dates[3], "current_close_available"]
    assert result.loc[dates[3], list(FACTOR_COLUMNS)].isna().all()
    # At date 5 the four-session window has only pairs for dates 2 and 5.
    x, y = np.array([-.02, .05]), np.array([.03, .01])
    assert result.loc[dates[5], "beta_uncentered"] == pytest.approx(np.dot(x, y) / np.dot(x, x))
    # Matched y values only: the two-value centered third moment is zero.
    assert result.loc[dates[5], "own_skewness"] == pytest.approx(0.0, abs=1e-10)


def test_pairwise_semibeta_identity_and_constant_price_scaling():
    rng = np.random.default_rng(555)
    prices = price_frame(rng.normal(0, .01, 150), rng.normal(0, .02, 150))
    original = build_systematic_tail_features(prices)
    decomposition = original.semibeta_n + original.semibeta_p - original.semibeta_m_minus - original.semibeta_m_plus
    np.testing.assert_allclose(original.beta_uncentered, decomposition, atol=1e-12, equal_nan=True)
    scaled = prices.copy()
    scaled.loc[scaled.ticker.eq("ABC"), "close"] *= 7.0
    transformed = build_systematic_tail_features(scaled)
    np.testing.assert_allclose(original[list(FACTOR_COLUMNS)], transformed[list(FACTOR_COLUMNS)], atol=1e-11, equal_nan=True)


def test_joint_loss_excess_depends_on_pairing_not_only_marginal_losses():
    x = np.array([-.02, -.01, .01, .02])
    aligned = build_systematic_tail_features(price_frame(x, x), window=4, min_observations=4).iloc[-1]
    opposite = build_systematic_tail_features(price_frame(x, -x), window=4, min_observations=4).iloc[-1]
    assert aligned.stock_loss_observations == opposite.stock_loss_observations == 2
    assert aligned.co_loss_excess_diagnostic == pytest.approx(.25)
    assert opposite.co_loss_excess_diagnostic == pytest.approx(-.25)
    assert np.isnan(aligned.market_coskewness)  # a perfect linear asset has zero residual variance


def test_missing_market_price_uses_same_pair_mask_and_zero_variance_is_missing():
    prices = price_frame([.01, -.02, .03, -.04, .05, -.02], [.02, .03, -.01, -.03, .01, .04])
    dates = sorted(prices.trade_date.unique())
    prices.loc[prices.ticker.eq("QQQ") & prices.trade_date.eq(dates[3]), "close"] = np.nan
    result = build_systematic_tail_features(prices, window=4, min_observations=2).set_index("trade_date")
    assert result.loc[dates[5], "matched_observations"] == 2
    assert result.loc[dates[5], "beta_uncentered"] == pytest.approx((-.02*.03 + .05*.01) / (.02**2 + .05**2))
    flat = build_systematic_tail_features(price_frame([0]*5, [.01, -.02, .03, -.01, .02]), window=4, min_observations=4)
    assert flat.beta_uncentered.isna().all()
    assert flat.market_coskewness.isna().all()


def test_rejects_duplicates_invalid_prices_and_unmatched_calendar():
    prices = price_frame([.01, -.01, .02], [.03, -.02, .01])
    with pytest.raises(ValueError, match="duplicate"):
        build_systematic_tail_features(pd.concat([prices, prices.iloc[[0]]]))
    invalid = prices.copy()
    invalid.loc[0, "close"] = 0
    with pytest.raises(ValueError, match="positive"):
        build_systematic_tail_features(invalid)
    extra = prices.iloc[[-1]].copy()
    extra["trade_date"] = prices.trade_date.max() + pd.Timedelta(days=5)
    with pytest.raises(ValueError, match="calendar"):
        build_systematic_tail_features(pd.concat([prices, extra]))
