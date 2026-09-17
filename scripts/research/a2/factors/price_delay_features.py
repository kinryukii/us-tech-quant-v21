"""One trailing price-delay characteristic, with no readers or outcome fitting.

Daily adaptation: 126 market sessions, >=100 common complete observations,
current market return plus lags 1..5, and a 21-market-session characteristic lag.
The sole candidate is 1-R2_restricted/R2_full. The full-model R2>=0.01 gate is
fixed before evaluation, not a tuned return filter. Positive in-sample delay is
mechanically possible under the null because the full model is nested.

This is not a replication of Hou-Moskowitz's weekly/prior-year specification,
not a forecast of the next market move, and not a lead-inclusive Dimson beta.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_COLUMNS = ("price_delay_d1",)
DIAGNOSTIC_COLUMNS = (
    "price_delay_beta_stale", "price_delay_r2_restricted_stale",
    "price_delay_r2_full_stale", "price_delay_matched_observations_stale",
    "price_delay_full_rank_stale", "price_delay_condition_stale",
    "price_delay_weak_r2_stale",
)
ROUNDING_TOLERANCE = 1e-9


def _rolling_sum(values: np.ndarray, window: int) -> np.ndarray:
    result = np.cumsum(values, axis=0)
    result[window:] -= result[:-window].copy()
    return result


def _bounded_unit(values: np.ndarray, name: str) -> np.ndarray:
    if np.isinf(values).any():
        raise ArithmeticError(f"infinite {name}")
    finite = np.isfinite(values)
    if ((values[finite] < -ROUNDING_TOLERANCE)
            | (values[finite] > 1 + ROUNDING_TOLERANCE)).any():
        raise ArithmeticError(f"material {name} outside [0,1]")
    return np.clip(values, 0.0, 1.0)


def _rolling_models(y: np.ndarray, x: np.ndarray, window: int, minimum: int, min_r2: float) -> dict[str, np.ndarray]:
    """Centered OLS moments on one common mask; adding the intercept is exact."""
    valid = np.isfinite(y) & np.isfinite(x).all(axis=1)
    clean_x = np.where(valid[:, None], x, 0.0)
    clean_y = np.where(valid, y, 0.0)
    count = _rolling_sum(valid.astype(float), window)
    divisor = np.where(count > 0, count, np.nan)
    sx = _rolling_sum(clean_x, window)
    sy = _rolling_sum(clean_y, window)
    sxx = _rolling_sum(clean_x[:, :, None] * clean_x[:, None, :], window)
    sxy = _rolling_sum(clean_x * clean_y[:, None], window)
    syy = _rolling_sum(clean_y ** 2, window)
    centered_xx = sxx - sx[:, :, None] * sx[:, None, :] / divisor[:, None, None]
    centered_xy = sxy - sx * sy[:, None] / divisor[:, None]
    sst = syy - sy ** 2 / divisor
    nrows, width = x.shape
    empty = lambda: np.full(nrows, np.nan)
    beta, r2_zero, r2_full, d1 = empty(), empty(), empty(), empty()
    ranks, condition = empty(), empty()
    diagonal = np.diagonal(centered_xx, axis1=1, axis2=2)
    enough = count >= minimum
    # A degenerate series is not an informative zero-delay observation.
    usable = enough & (sst > 1e-16) & (diagonal > 1e-16).all(axis=1)
    indexes = np.flatnonzero(usable)
    if len(indexes):
        gram = centered_xx[indexes]
        scales = np.sqrt(diagonal[indexes])
        correlation = gram / (scales[:, :, None] * scales[:, None, :])
        correlation = (correlation + correlation.swapaxes(1, 2)) / 2.0
        eigenvalues = np.linalg.eigvalsh(correlation)
        rank = (eigenvalues > 1e-10).sum(axis=1)
        ranks[indexes] = rank + 1  # includes the intercept
        full_rank = rank == width
        condition[indexes] = np.divide(eigenvalues[:, -1], eigenvalues[:, 0], out=np.full(len(indexes), np.inf), where=eigenvalues[:, 0] > 0)
        # Restricted beta/R2 use EXACTLY the full design's matched rows.
        beta[indexes] = centered_xy[indexes, 0] / gram[:, 0, 0]
        r2_zero[indexes] = _bounded_unit(centered_xy[indexes, 0] ** 2 / gram[:, 0, 0] / sst[indexes], "restricted R2")
        solved_indexes = indexes[full_rank]
        if len(solved_indexes):
            rhs = centered_xy[solved_indexes] / scales[full_rank]
            coefficients = np.linalg.solve(correlation[full_rank], rhs[..., None])[..., 0]
            explained = np.einsum("ij,ij->i", rhs, coefficients)
            full = _bounded_unit(explained / sst[solved_indexes], "full R2")
            if (full + ROUNDING_TOLERANCE < r2_zero[solved_indexes]).any():
                raise ArithmeticError("nested R2 ordering failure")
            r2_full[solved_indexes] = full
            accepted = full >= min_r2
            selected = solved_indexes[accepted]
            positive = r2_full[selected] > 0
            selected = selected[positive]
            d1[selected] = _bounded_unit(1.0 - r2_zero[selected] / r2_full[selected], "D1")
    weak = np.where(np.isfinite(r2_full), (r2_full < min_r2).astype(float), np.nan)
    return {"price_delay_d1": d1, "price_delay_beta_stale": beta,
            "price_delay_r2_restricted_stale": r2_zero,
            "price_delay_r2_full_stale": r2_full,
            "price_delay_matched_observations_stale": count,
            "price_delay_full_rank_stale": ranks,
            "price_delay_condition_stale": condition,
            "price_delay_weak_r2_stale": weak}


def build_price_delay_features(
    prices: pd.DataFrame, *, market_ticker: str = "QQQ", window: int = 126,
    min_observations: int = 100, lags: int = 5, characteristic_lag: int = 21,
    min_full_r2: float = 0.01, return_column: str | None = None,
) -> pd.DataFrame:
    """One row per stock/market session; all regression diagnostics are stale.

    Estimation includes the measurement date's close, then shifts the entire
    characteristic and diagnostics by 21 MARKET CALENDAR rows. Consequently
    date t has no measurement later than t-21; missing stock observations never
    compress the lag. The trailing window also counts market calendar rows,
    retaining only joint-complete observations for BOTH nested models. A gap
    invalidates two own returns; a market gap propagates across its five lags.

    Finite positive observed closes are an input contract. If return_column is
    supplied, both market and stock regressions use that explicit one-session
    return without compounding or bridging a gap. The caller must establish its
    economic/event semantics. Otherwise close ratios are used, which alone do
    not certify total-return semantics for an arbitrary adjusted price index.
    Missing closes remain NaN. Current missing closes suppress model
    estimates; stale counts/measurement dates remain visible. Upstream owns PIT
    universe membership and exact calendar completeness. Overrides only support
    synthetic testing; the single intended real-data specification is default.
    """
    for name, value in (("window", window), ("min_observations", min_observations), ("lags", lags), ("characteristic_lag", characteristic_lag)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")
    if lags < 1 or window <= lags + 2 or not lags + 2 < min_observations <= window or characteristic_lag < 0:
        raise ValueError("invalid regression window/count/lag")
    if not np.isfinite(min_full_r2) or not 0 <= min_full_r2 <= 1:
        raise ValueError("min_full_r2 must be finite in [0,1]")
    required = {"ticker", "trade_date", "close"}
    if return_column is not None:
        if not isinstance(return_column, str) or not return_column or return_column in required:
            raise ValueError("return_column must name a distinct return field")
        required.add(return_column)
    if not required.issubset(prices):
        raise ValueError(f"missing columns: {sorted(required - set(prices))}")
    frame = prices[["ticker", "trade_date", "close", *([] if return_column is None else [return_column])]].copy()
    if frame.ticker.isna().any() or frame.ticker.astype(str).str.strip().eq("").any():
        raise ValueError("ticker must be nonempty")
    frame["ticker"] = frame.ticker.astype(str)
    frame["trade_date"] = pd.to_datetime(frame.trade_date, errors="raise")
    if frame.trade_date.isna().any() or frame.trade_date.dt.tz is not None or not frame.trade_date.eq(frame.trade_date.dt.normalize()).all():
        raise ValueError("trade_date must be normalized timezone-naive session dates")
    if frame.duplicated(["ticker", "trade_date"]).any():
        raise ValueError("duplicate ticker/session rows")
    frame["close"] = pd.to_numeric(frame.close, errors="raise").astype(float)
    present = frame.close.notna()
    if ((~np.isfinite(frame.loc[present, "close"])) | frame.loc[present, "close"].le(0)).any():
        raise ValueError("observed closes must be finite and positive")
    if return_column is not None:
        frame[return_column] = pd.to_numeric(frame[return_column], errors="raise").astype(float)
        observed_returns = frame[return_column].notna()
        values = frame.loc[observed_returns, return_column]
        if ((~np.isfinite(values)) | values.lt(-1)).any():
            raise ValueError("explicit returns must be finite and at least minus one")
        if (observed_returns & ~present).any():
            raise ValueError("explicit return cannot be present without current close")
    market = frame.loc[frame.ticker.eq(market_ticker)].set_index("trade_date").close.sort_index()
    if market.empty:
        raise ValueError("market ticker absent")
    calendar = market.index
    if not frame.trade_date.isin(calendar).all():
        raise ValueError("stock dates outside supplied market calendar")
    market_return = (market.pct_change(fill_method=None) if return_column is None else
                     frame.loc[frame.ticker.eq(market_ticker)].set_index("trade_date")[return_column].reindex(calendar))
    x = np.column_stack([market_return.shift(k).to_numpy() for k in range(lags + 1)])
    outputs = []
    for ticker, group in frame.loc[frame.ticker.ne(market_ticker)].groupby("ticker", sort=True):
        stock = group.set_index("trade_date").close.reindex(calendar)
        y = (stock.pct_change(fill_method=None).to_numpy() if return_column is None else
             group.set_index("trade_date")[return_column].reindex(calendar).to_numpy())
        measurements = pd.DataFrame(_rolling_models(y, x, window, min_observations, min_full_r2), index=calendar)
        measurements["price_delay_measurement_date"] = calendar
        out = measurements.shift(characteristic_lag)
        current = stock.notna() & market.notna()
        estimates = ["price_delay_d1", "price_delay_beta_stale", "price_delay_r2_restricted_stale", "price_delay_r2_full_stale"]
        out.loc[~current, estimates] = np.nan
        out["current_close_available"] = current
        out["ticker"] = ticker
        out["trade_date"] = calendar
        outputs.append(out.reset_index(drop=True))
    if not outputs:
        return pd.DataFrame(columns=["ticker", "trade_date", *FEATURE_COLUMNS, *DIAGNOSTIC_COLUMNS, "price_delay_measurement_date", "current_close_available"])
    return pd.concat(outputs, ignore_index=True).sort_values(["trade_date", "ticker"], kind="stable").reset_index(drop=True)
