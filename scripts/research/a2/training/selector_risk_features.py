"""Pure PIT risk inputs and selector features; no fitting, I/O, or allocation.

The reference is the current complete common pool with equal mass. Its risk
describes that reference, not actual holdings or a portfolio optimizer. The caller
owns source/bundle identity, accepted feature eligibility, and PSD qualification.
"""
from __future__ import annotations
import hashlib
import numpy as np
import pandas as pd
from scripts.research.a2.risk import joint_risk_estimators as joint

UNIT = "ACCEPTED_FROZEN_PIT32_RET_1D_PROXY_FRACTIONAL"
SOURCE_KIND = "RISK_PRIOR_FIT_PIT_FEATURE_PROJECTION"


def _keys(frame, *, returns=False):
    columns = ["signal_date", "ticker", "security_uid"]
    if returns:
        columns.append("ret_1d")
    if not set(columns).issubset(frame.columns):
        raise ValueError("RISK_FEATURE_KEYS_OR_RET_1D_MISSING")
    value = frame.loc[:, columns].copy()
    value["signal_date"] = pd.to_datetime(value.signal_date, errors="raise")
    if value.signal_date.isna().any() or value.signal_date.dt.tz is not None:
        raise ValueError("RISK_SIGNAL_DATES_MUST_BE_NONNULL_NAIVE")
    return value


def _unique_keys(frame):
    if (frame.empty or frame[["ticker", "security_uid"]].isna().any().any()
            or frame.duplicated(["signal_date", "ticker"]).any()
            or frame.duplicated(["signal_date", "security_uid"]).any()):
        raise ValueError("RISK_EMPTY_OR_DUPLICATE_TICKER_UID_KEYS")
    for name in ("ticker", "security_uid"):
        if not frame[name].map(lambda x: isinstance(x, str) and bool(x.strip())).all():
            raise ValueError("RISK_TICKER_UID_MUST_BE_NONEMPTY_STRINGS")


def annual_returns(featureFrame, cutoff):
    """Retain all earlier legal names; use exactly the last 63 feature sessions."""
    cut = pd.Timestamp(cutoff)
    if pd.isna(cut) or cut.tzinfo is not None or cut > pd.Timestamp("2026-01-01"):
        raise ValueError("RISK_INVALID_PRE2026_CUTOFF")
    dates_all = pd.to_datetime(featureFrame["signal_date"], errors="raise")
    if dates_all.isna().any() or dates_all.dt.tz is not None:
        raise ValueError("RISK_SIGNAL_DATES_MUST_BE_NONNULL_NAIVE")
    frame = _keys(featureFrame.loc[dates_all.lt(cut)], returns=True)
    _unique_keys(frame)
    names = sorted(frame.ticker.unique())
    dates = pd.DatetimeIndex(sorted(frame.signal_date.unique())[-63:])
    if len(dates) != 63:
        raise ValueError("RISK_REQUIRES_EXACT63_PRIOR_FEATURE_SESSIONS")
    recent = frame.loc[frame.signal_date.isin(dates)]
    table = recent.pivot(index="signal_date", columns="ticker", values="ret_1d")
    table = table.reindex(index=dates, columns=names).astype(float)
    if np.isinf(table.to_numpy()).any():
        raise ValueError("RISK_INFINITE_RETURN")
    digest = hashlib.sha256(
        pd.util.hash_pandas_object(table, index=True).to_numpy(np.uint64).tobytes()
    ).hexdigest()
    metadata = dict(assets=names, dates=[d.isoformat() for d in dates],
        cutoff_exclusive=cut.isoformat(), returns_sha256=digest,
        source="caller accepted canonical PIT32 ret_1d", return_unit=UNIT,
        return_horizon_sessions=1, window_sessions=63, annual_static=True,
        missing_returns="retained NaN; canonical estimator owns prior fallback",
        labels_used=False, future_membership_used=False, eligibility_upgraded=False)
    return table, metadata


def project(bundle, requested_tickers):
    """Return sigma, Cov(asset,equal-pool)/sigma(pool), and unknown indicator."""
    if bundle.status != "FITTED" or bundle.covariance is None:
        raise joint.RiskEstimatorBlocked("RISK_BUNDLE_NOT_FITTED")
    names = tuple(requested_tickers)
    if (not names or len(set(names)) != len(names)
            or any(not isinstance(n, str) or not n.strip() for n in names)):
        raise ValueError("RISK_REQUESTED_TICKERS_MUST_BE_UNIQUE_NONEMPTY")
    estimated = tuple(bundle.estimated_assets)
    covariance = np.asarray(bundle.covariance, dtype=float)
    if len(set(estimated)) != len(estimated) or covariance.shape != (len(estimated), len(estimated)):
        raise ValueError("RISK_BUNDLE_ASSET_MATRIX_MISMATCH")
    fallback = float(bundle.fallback_variance)
    if not np.isfinite(fallback) or fallback <= 0:
        raise ValueError("RISK_PRIOR_FALLBACK_VARIANCE_INVALID")
    lookup = {name: i for i, name in enumerate(estimated)}
    known = np.array([name in lookup for name in names])
    dest = np.flatnonzero(known)
    source = [lookup[names[i]] for i in dest]
    marginal = np.full(len(names), fallback)
    row_sum = np.full(len(names), fallback)
    if len(source):
        submatrix = covariance[np.ix_(source, source)]
        marginal[dest] = np.diag(submatrix)
        row_sum[dest] = submatrix.sum(axis=1)
    contribution = row_sum / len(names)
    pool_variance = float(contribution.sum() / len(names))
    if (not np.isfinite(marginal).all() or np.any(marginal < 0)
            or not np.isfinite(contribution).all() or not np.isfinite(pool_variance)
            or pool_variance <= 0):
        raise ValueError("RISK_PROJECTION_NONFINITE_OR_NONPOSITIVE_POOL_VARIANCE")
    # Negative covariance contributions are legal and deliberately preserved.
    return np.column_stack((np.sqrt(marginal),
                            contribution / np.sqrt(pool_variance), (~known).astype(float)))


def frame_features(bundle, frame, year, method):
    """Project every supplied common key; never drop a model-specific subset."""
    method = joint.canonical_method(method)
    if bundle.method_id != method and not (method == "HISTVOL" and bundle.method_id == "DIAG"):
        raise ValueError("RISK_BUNDLE_METHOD_MISMATCH")
    cutoff = pd.Timestamp(bundle.specification.get("fit_cutoff"))
    if (year not in range(2021, 2026) or pd.isna(cutoff)
            or cutoff != pd.Timestamp(f"{year}-01-01")):
        raise ValueError("RISK_ANNUAL_FIT_CUTOFF_MISMATCH")
    out = _keys(frame)
    _unique_keys(out)
    dates = out.signal_date
    if not (dates.gt(cutoff) & dates.lt(pd.Timestamp(f"{year+1}-01-01"))).all():
        raise ValueError("RISK_PROJECTION_CLOCK_NOT_STRICTLY_AFTER_ANNUAL_FIT")
    columns = [f"{method}__marginal_sigma", f"{method}__pool_covariance_normalized",
               f"{method}__unknown_flag"]
    result = np.empty((len(out), 3))
    for positions in out.groupby("signal_date", sort=True).indices.values():
        result[positions] = project(bundle, out.iloc[positions].ticker.tolist())
    for i, name in enumerate(columns):
        out[name] = result[:, i]
    out["risk_cutoff"] = cutoff
    out["risk_source_kind"] = SOURCE_KIND
    out["risk_method"] = method
    out["risk_estimator_method"] = bundle.method_id
    out["risk_asset_observed"] = result[:, 2] == 0
    out["risk_unknown_fallback"] = result[:, 2] == 1
    out["eligibility_upgraded"] = False
    return out
