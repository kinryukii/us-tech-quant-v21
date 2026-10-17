"""Missing-key Raw control inference using unchanged annual frozen estimators.

The caller binds source/model bytes and the separate equivalence proof before
loading them. This adapter changes the declared held-input domain, not Raw A2
weights, fit objective, buy universe, or an existing OOF row.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from scripts.research.a2.data.joint_input_binding import FEATURES


def _session_day(value, field):
    try:
        day = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("INVALID_RAW_MANIFEST_DATE:" + field) from exc
    if pd.isna(day) or day.tzinfo is not None or day != day.normalize():
        raise ValueError("INVALID_RAW_MANIFEST_DATE:" + field)
    return day


def _key_dates(frame):
    if frame.ticker.isna().any() or any(
        not isinstance(ticker, str) or not ticker.strip() or ticker != ticker.strip()
        for ticker in frame.ticker
    ):
        raise ValueError("INVALID_RAW_CONTROL_TICKER")
    try:
        dates = pd.to_datetime(frame.signal_date, format="mixed")
    except (TypeError, ValueError) as exc:
        raise ValueError("INVALID_RAW_CONTROL_DATE") from exc
    if (dates.isna().any() or not pd.api.types.is_datetime64_any_dtype(dates.dtype)
        or dates.dt.tz is not None or not dates.equals(dates.dt.normalize())):
        raise ValueError("INVALID_RAW_CONTROL_DATE")
    return dates


def infer_missing_raw_keys(held_features, existing_raw, model, manifest):
    """Infer a deployed annual cohort; existing keys, including NaN, are final.

    Same-year feature keys earlier than the original annual deployment date
    are outside the model's legal inference domain and are excluded solely by
    that frozen input clock. No target, endpoint or future outcome is consulted.
    """
    required={"signal_date","ticker",*FEATURES}
    if not required.issubset(held_features) or not {"signal_date","ticker","a2_prediction"}.issubset(existing_raw):
        raise ValueError("MISSING_RAW_HELD_INFERENCE_INPUT")
    features=held_features.copy()
    features["signal_date"]=_key_dates(features)
    dates=_key_dates(existing_raw)
    old_keys=existing_raw[["signal_date","ticker"]].assign(signal_date=dates)
    if features.duplicated(["signal_date","ticker"]).any() or old_keys.duplicated(["signal_date","ticker"]).any():
        raise ValueError("DUPLICATE_RAW_CONTROL_KEY")
    contract=manifest["contract"]
    year=int(contract["year"])
    if year not in (2023,2024,2025) or contract["feature_columns"]!=list(FEATURES):
        raise ValueError("UNBOUND_RAW_ANNUAL_FEATURE_IDENTITY")
    cutoff=pd.Timestamp(year,1,1)
    train_end=_session_day(contract["train_end"],"train_end")
    labelmax=_session_day(contract["labelmax"],"labelmax")
    prediction_min=_session_day(contract["prediction_min_date"],"prediction_min_date")
    if train_end>=cutoff or labelmax>=cutoff:
        raise ValueError("RAW_ANNUAL_FIT_MATURITY_VIOLATION")
    if prediction_min.year!=year or prediction_min<cutoff:
        raise ValueError("INVALID_RAW_ANNUAL_DEPLOYMENT_DATE")
    if features.signal_date.ge(pd.Timestamp("2026-01-01")).any() or dates.ge(pd.Timestamp("2026-01-01")).any():
        raise ValueError("TEST_CONTENT_IN_RAW_CONTROL_EXTENSION")
    features=features.loc[features.signal_date.dt.year.eq(year)&features.signal_date.ge(prediction_min)].copy()
    # Presence, rather than finiteness, is authoritative for the old OOF key.
    existing=pd.MultiIndex.from_frame(old_keys)
    keys=pd.MultiIndex.from_frame(features[["signal_date","ticker"]])
    missing=features.loc[~keys.isin(existing)].copy()
    if not np.isfinite(missing[list(FEATURES)].to_numpy(float)).all():
        raise ValueError("NONFINITE_SOURCE_BACKED_RAW_HELD_FEATURE")
    scores=np.asarray(model.predict(missing[list(FEATURES)].to_numpy(float)),float) if len(missing) else np.empty(0)
    if scores.shape!=(len(missing),) or not np.isfinite(scores).all():
        raise ValueError("NONFINITE_OR_WRONG_RAW_INFERENCE_OUTPUT")
    out=missing[["signal_date","ticker"]].copy()
    out["a2_prediction"]=scores
    out["raw_uncertainty"]=0.
    out["source_fit_cutoff"]=cutoff
    out["source_kind"]="FROZEN_RAW_ANNUAL_MISSING_HELD_KEY_INFERENCE"
    out["feature_source"]=missing.feature_source if "feature_source" in missing else "CALLER_BOUND_SOURCE"
    return out.sort_values(["signal_date","ticker"],kind="stable").reset_index(drop=True)
