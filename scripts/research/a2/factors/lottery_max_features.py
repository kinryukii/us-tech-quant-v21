"""Pure previous-complete-calendar-month MAX characteristic; no data readers.

At signal close t, measurement uses the calendar month before the month of the
explicit calendar's next session e(t). A month-end signal can therefore use the
newly completed month. ``lottery_score=-MAX`` is a fixed theoretical feature;
it does not constrain a downstream regression coefficient or authorize a sign
flip. Same-month population standard deviation and skewness are shared controls.

The supplied calendar is an external authority, not inferred from present-day
membership or downloaded here. This function cannot prove calendar completeness,
security identity, adjusted-return lineage, finalized timestamps or tradability.

CRITICAL INPUT LIMIT: the campaign's accepted alpha*P+beta forward-affine price
surface is not automatically an economic one-day return index when beta includes
cash distributions. Passing that surface's close levels here does not make their
pct_change a new-position return or reinvested total return. Real MAX evaluation
must wait for a proven return/wealth-index construction from existing corporate-
action accounting. This module and its current tests make only synthetic claims.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


VALUE_COLUMNS = ("max_daily_return", "lottery_score", "lottery_month_std", "lottery_month_skewness")


def _session_index(values, name):
    index = pd.DatetimeIndex(pd.to_datetime(values, errors="raise"))
    if index.hasnans or index.tz is not None or not index.equals(index.normalize()):
        raise ValueError(f"{name}: normalized timezone-naive nonmissing dates required")
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError(f"{name}: unique increasing dates required")
    return index


def build_lottery_max_features(
    prices: pd.DataFrame,
    market_calendar: pd.DatetimeIndex,
    *,
    market_ticker: str = "QQQ",
    variance_epsilon: float = 1e-12,
    return_column: str | None = None,
) -> pd.DataFrame:
    """Compute pure monthly MAX features for every stock / observed date-prefix.

    Input columns are ticker, trade_date, close. With return_column supplied, use
    that already validated one-session arithmetic return directly; unavailable
    observations must be NaN. Raw close then serves only the current-availability
    flag, and no synthetic cumprod index or percent-change bridge is constructed.
    The module cannot authenticate the return's event/identity/currency lineage.
    Without return_column, the caller must prove that ratios
    of these close values encode the intended one-day return, not merely cite an
    accepted affine-adjustment manifest. Prices are aligned to the supplied
    complete market-session calendar before no-fill arithmetic percent changes.
    Output spans all calendar dates through the final supplied price date, with
    rows for each non-market ticker, including missing current closes. Future
    calendar dates may be supplied without future prices: they provide only the
    known exchange schedule needed to identify e(t), never an observed price.

    A complete measurement month requires one finite stock return on EVERY
    expected market session, including the return requiring its first day's prior
    close. One missing close invalidates its return and the next return. A missing
    price, session-boundary context, or next-calendar session yields unavailable
    affected features; maxima over partial samples are never exposed. No clipping
    of negative MAX occurs. Zero monthly variance has defined std=0 and undefined
    skewness=NaN; full_support records data completeness separately from moments.
    """
    calendar = _session_index(market_calendar, "market_calendar")
    if len(calendar) < 2:
        raise ValueError("market_calendar must include at least two sessions")
    if not np.isfinite(variance_epsilon) or variance_epsilon <= 0:
        raise ValueError("variance_epsilon must be finite and positive")
    required = {"ticker", "trade_date", "close"}
    if return_column is not None:
        if not isinstance(return_column, str) or not return_column or return_column in required:
            raise ValueError("return_column must name a separate return column")
        required.add(return_column)
    if not required.issubset(prices.columns):
        raise ValueError(f"missing columns: {sorted(required.difference(prices.columns))}")
    frame = prices[["ticker", "trade_date", "close", *([] if return_column is None else [return_column])]].copy()
    if frame.empty or frame.ticker.isna().any() or frame.ticker.astype(str).str.strip().eq("").any():
        raise ValueError("nonempty prices and ticker identities required")
    frame["ticker"] = frame.ticker.astype(str)
    frame["trade_date"] = pd.to_datetime(frame.trade_date, errors="raise")
    if not frame.trade_date.isin(calendar).all():
        raise ValueError("all price dates must belong to the explicit market calendar")
    if frame.duplicated(["ticker", "trade_date"]).any():
        raise ValueError("duplicate ticker/session price rows")
    frame["close"] = pd.to_numeric(frame.close, errors="raise").astype(float)
    observed_close = frame.close.notna()
    if ((~np.isfinite(frame.loc[observed_close, "close"])) | frame.loc[observed_close, "close"].le(0)).any():
        raise ValueError("observed closes must be finite and positive")
    if return_column is not None:
        frame[return_column] = pd.to_numeric(frame[return_column], errors="raise").astype(float)
        valid_return = frame[return_column].dropna()
        if (~np.isfinite(valid_return)).any() or valid_return.lt(-1.0).any():
            raise ValueError("explicit arithmetic returns must be finite or NaN and at least -1")

    signal_dates = calendar[calendar <= frame.trade_date.max()]
    periods = calendar.to_period("M")
    schedule = pd.DataFrame({"session": calendar, "period": periods})
    expected = schedule.groupby("period", sort=True).agg(
        expected_return_count=("session", "size"),
        measurement_start_date=("session", "min"),
        measurement_end_date=("session", "max"),
    )
    next_session = pd.Series(calendar, index=calendar).shift(-1).reindex(signal_dates)
    measurement_period = next_session.dt.to_period("M") - 1
    metadata = expected.reindex(pd.PeriodIndex(measurement_period, freq="M")).reset_index(drop=True)
    metadata.index = signal_dates
    metadata["expected_return_count"] = metadata.expected_return_count.fillna(0).astype(np.int64)
    metadata["measurement_month"] = measurement_period.astype("string")
    metadata["next_market_session"] = next_session
    metadata["next_session_known"] = next_session.notna()
    metadata["factor_information_end_date"] = metadata.measurement_end_date
    period_is_complete = (metadata.measurement_end_date.le(pd.Series(signal_dates, index=signal_dates))
                          & metadata.next_session_known & metadata.expected_return_count.gt(0))
    outputs = []
    for ticker, group in frame.loc[frame.ticker.ne(market_ticker)].groupby("ticker", sort=True):
        close = group.set_index("trade_date").close.reindex(calendar)
        returns = (close.pct_change(fill_method=None) if return_column is None
                   else group.set_index("trade_date")[return_column].reindex(calendar))
        if np.isinf(returns.to_numpy()).any():
            raise ArithmeticError("nonfinite stock return")
        grouped = returns.groupby(periods, sort=True)
        monthly = grouped.agg(observed_return_count="count", max_daily_return="max")
        deviation = returns - grouped.transform("mean")
        variance = deviation.pow(2).groupby(periods, sort=True).mean()
        monthly["lottery_month_std"] = np.sqrt(variance)
        monthly["lottery_month_skewness"] = deviation.pow(3).groupby(periods, sort=True).mean().div(
            variance.where(variance.gt(variance_epsilon)).pow(1.5)
        )
        aligned = monthly.reindex(pd.PeriodIndex(measurement_period, freq="M")).reset_index(drop=True)
        aligned.index = signal_dates
        out = metadata.copy()
        out["ticker"] = ticker
        out["trade_date"] = signal_dates
        out["observed_return_count"] = aligned.observed_return_count.fillna(0).astype(np.int64)
        out["full_support"] = (period_is_complete & out.observed_return_count.eq(out.expected_return_count))
        out["current_close_available"] = close.reindex(signal_dates).notna()
        out["factor_available"] = out.full_support & out.current_close_available
        out["max_daily_return"] = aligned.max_daily_return.where(out.factor_available)
        out["lottery_score"] = -out.max_daily_return
        out["lottery_month_std"] = aligned.lottery_month_std.where(out.factor_available)
        out["lottery_month_skewness"] = aligned.lottery_month_skewness.where(out.factor_available)
        out["moments_available"] = out.factor_available & out.lottery_month_skewness.notna()
        if (out.loc[out.factor_available, "factor_information_end_date"]
                > out.loc[out.factor_available, "trade_date"]).any():
            raise ArithmeticError("factor information after signal")
        outputs.append(out.reset_index(drop=True))
    if not outputs:
        return pd.DataFrame(columns=["ticker", "trade_date", *VALUE_COLUMNS])
    return pd.concat(outputs, ignore_index=True).sort_values(["trade_date", "ticker"], kind="stable").reset_index(drop=True)
