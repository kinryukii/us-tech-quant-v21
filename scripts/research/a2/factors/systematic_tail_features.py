"""Pure trailing daily-price features for two preregisterable hypothesis families.

No reader, result access, fitting to labels, trial search, portfolio, or execution
implementation lives here. ``close`` must already have authoritative PIT lineage.
The QQQ rows supply the market-session calendar; missing entire calendar rows
cannot be detected here. Returns use a zero reference, not a risk-free series.

``beta_uncentered`` is the sum-of-products / market-squares ratio and decomposes
exactly into four nonnegative semibetas. ``beta_centered`` is the OLS slope with
an intercept and is not generally equal to that ratio. ``semibeta_signed_score``
is N-Mminus: algebraically a downside-beta contribution, NOT independent proof
that four quadrants are priced differently. No all-four-plus-beta regression is
identified. ``coskewness_score`` is negative normalized *residual* coskewness.
``co_loss_excess_diagnostic`` is a dependence diagnostic, not another candidate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


FACTOR_COLUMNS = (
    "beta_uncentered", "beta_centered", "semibeta_n", "semibeta_p",
    "semibeta_m_minus", "semibeta_m_plus", "semibeta_signed_score",
    "market_coskewness", "coskewness_score", "own_skewness", "co_loss_excess_diagnostic",
)
COUNT_COLUMNS = (
    "matched_observations", "market_loss_observations", "stock_loss_observations",
    "joint_loss_observations",
)


def build_systematic_tail_features(
    prices: pd.DataFrame,
    *,
    market_ticker: str = "QQQ",
    window: int = 126,
    min_observations: int = 100,
    variance_epsilon: float = 1e-12,
) -> pd.DataFrame:
    """Return one row per stock / supplied market session, sorted chronologically.

    Every estimate uses the last ``window`` calendar rows, counting only matched
    stock/market returns, with no forward fill. Missing prices invalidate that
    session's return AND the next return; no missing-session bridge is possible.
    Ratios share identical paired masks. Unavailable estimates remain NaN, not
    zero; observation counts remain visible. At a missing current stock or market
    close all features are suppressed. A valid close immediately after a gap can
    have estimates from other pairs, but its unavailable one-day return is never
    invented. Upstream decides tradability and authoritative universe membership.

    Coskewness estimates center both returns and remove their OLS relationship
    within the trailing window available at the signal close. Values for an
    earlier *signal* date never use later returns. Small-window overrides exist
    for synthetic tests; production defaults are a single fixed specification.
    """
    if isinstance(window, bool) or not isinstance(window, int) or window < 2:
        raise ValueError("window must be an integer >= 2")
    if (isinstance(min_observations, bool) or not isinstance(min_observations, int)
            or not 2 <= min_observations <= window):
        raise ValueError("min_observations must be an integer in [2, window]")
    if not np.isfinite(variance_epsilon) or variance_epsilon <= 0:
        raise ValueError("variance_epsilon must be finite and positive")
    required = {"ticker", "trade_date", "close"}
    if not required.issubset(prices.columns):
        raise ValueError(f"missing columns: {sorted(required.difference(prices.columns))}")
    frame = prices[["ticker", "trade_date", "close"]].copy()
    if frame.ticker.isna().any() or frame.ticker.astype(str).str.strip().eq("").any():
        raise ValueError("ticker must be nonempty")
    frame["ticker"] = frame.ticker.astype(str)
    frame["trade_date"] = pd.to_datetime(frame.trade_date, errors="raise")
    if frame.trade_date.isna().any():
        raise ValueError("trade_date must be nonmissing")
    if frame.trade_date.dt.tz is not None:
        raise ValueError("trade_date must be timezone-naive session dates")
    if not frame.trade_date.eq(frame.trade_date.dt.normalize()).all():
        raise ValueError("trade_date must be normalized session dates")
    if frame.duplicated(["ticker", "trade_date"]).any():
        raise ValueError("duplicate ticker/session rows")
    frame["close"] = pd.to_numeric(frame.close, errors="raise").astype(float)
    observed = frame.close.notna()
    if ((~np.isfinite(frame.loc[observed, "close"]))
            | frame.loc[observed, "close"].le(0)).any():
        raise ValueError("observed closes must be finite and positive")
    market_close = frame.loc[frame.ticker.eq(market_ticker)].set_index("trade_date").close.sort_index()
    if market_close.empty:
        raise ValueError(f"market ticker absent: {market_ticker}")
    calendar = market_close.index
    if not frame.trade_date.isin(calendar).all():
        raise ValueError("stock dates outside supplied market calendar")
    market_returns = market_close.pct_change(fill_method=None)
    outputs: list[pd.DataFrame] = []

    for ticker, group in frame.loc[frame.ticker.ne(market_ticker)].groupby("ticker", sort=True):
        stock_close = group.set_index("trade_date").close.reindex(calendar)
        stock_returns = stock_close.pct_change(fill_method=None)
        matched = stock_returns.notna() & market_returns.notna()
        x = market_returns.where(matched)
        y = stock_returns.where(matched)
        count = matched.astype(float).rolling(window, min_periods=1).sum()

        def mean(values: pd.Series) -> pd.Series:
            return values.rolling(window, min_periods=1).sum().div(count.where(count.gt(0)))

        enough = count.ge(min_observations)
        current_available = stock_close.notna() & market_close.notna()
        admissible = enough & current_available
        ex, ey = mean(x), mean(y)
        ex2, ey2, exy = mean(x.pow(2)), mean(y.pow(2)), mean(x * y)
        market_variance = (ex2 - ex.pow(2)).clip(lower=0.0)
        stock_variance = (ey2 - ey.pow(2)).clip(lower=0.0)
        covariance = exy - ex * ey
        denominator = ex2.where(ex2.gt(variance_epsilon) & admissible)
        centered_denominator = market_variance.where(market_variance.gt(variance_epsilon) & admissible)
        beta_centered = covariance.div(centered_denominator)

        xn, xp = x.clip(upper=0.0), x.clip(lower=0.0)
        yn, yp = y.clip(upper=0.0), y.clip(lower=0.0)
        n = mean(yn * xn).div(denominator)
        p = mean(yp * xp).div(denominator)
        m_minus = -mean(yp * xn).div(denominator)
        m_plus = -mean(yn * xp).div(denominator)

        # E[(y-Ey)(x-Ex)^2] and E[(x-Ex)^3], evaluated from trailing moments.
        centered_y_x2 = mean(y * x.pow(2)) - 2 * ex * exy - ey * ex2 + 2 * ey * ex.pow(2)
        centered_x3 = mean(x.pow(3)) - 3 * ex * ex2 + 2 * ex.pow(3)
        centered_y3 = mean(y.pow(3)) - 3 * ey * ey2 + 2 * ey.pow(3)
        own_skewness = centered_y3.div(
            stock_variance.where(stock_variance.gt(variance_epsilon) & admissible).pow(1.5)
        )
        residual_variance = (stock_variance - covariance * beta_centered).clip(lower=0.0)
        residual_coskewness = (centered_y_x2 - beta_centered * centered_x3).div(
            np.sqrt(residual_variance.where(residual_variance.gt(variance_epsilon))) * centered_denominator
        )
        market_loss = x.lt(0).astype(float).where(matched)
        stock_loss = y.lt(0).astype(float).where(matched)
        joint_loss = (x.lt(0) & y.lt(0)).astype(float).where(matched)
        joint_excess = (mean(joint_loss) - mean(market_loss) * mean(stock_loss)).where(admissible)

        out = pd.DataFrame({
            "ticker": ticker,
            "trade_date": calendar,
            "beta_uncentered": exy.div(denominator).to_numpy(),
            "beta_centered": beta_centered.to_numpy(),
            "semibeta_n": n.to_numpy(), "semibeta_p": p.to_numpy(),
            "semibeta_m_minus": m_minus.to_numpy(), "semibeta_m_plus": m_plus.to_numpy(),
            "semibeta_signed_score": (n - m_minus).to_numpy(),
            "market_coskewness": residual_coskewness.to_numpy(),
            "coskewness_score": (-residual_coskewness).to_numpy(),
            "own_skewness": own_skewness.to_numpy(),
            "co_loss_excess_diagnostic": joint_excess.to_numpy(),
            "matched_observations": count.to_numpy(dtype=np.int64),
            "market_loss_observations": market_loss.fillna(0).rolling(window, min_periods=1).sum().to_numpy(dtype=np.int64),
            "stock_loss_observations": stock_loss.fillna(0).rolling(window, min_periods=1).sum().to_numpy(dtype=np.int64),
            "joint_loss_observations": joint_loss.fillna(0).rolling(window, min_periods=1).sum().to_numpy(dtype=np.int64),
            "current_close_available": current_available.to_numpy(),
        })
        outputs.append(out)
    if not outputs:
        return pd.DataFrame(columns=["ticker", "trade_date", *FACTOR_COLUMNS, *COUNT_COLUMNS, "current_close_available"])
    result = pd.concat(outputs, ignore_index=True).sort_values(["trade_date", "ticker"], kind="stable").reset_index(drop=True)
    numeric = result.loc[:, list(FACTOR_COLUMNS)].to_numpy(dtype=float)
    if np.isinf(numeric).any():
        raise ArithmeticError("nonfinite ratio: check input magnitudes")
    return result
