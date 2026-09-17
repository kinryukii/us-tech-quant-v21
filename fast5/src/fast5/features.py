from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


class FeatureIntegrityError(RuntimeError):
    pass


def _raw_daily(path: Path) -> pd.DataFrame:
    columns = ["date", "close", "source", "fetched_at_utc"]
    frame = pd.read_parquet(path, columns=columns)
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize().astype("datetime64[ns]")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    if frame.date.duplicated().any() or not frame.date.is_monotonic_increasing:
        raise FeatureIntegrityError(f"NEW_CROSS_ASSET_DUPLICATE_OR_NONMONOTONIC:{path}")
    if frame.close.le(0).any() or frame.close.isna().any():
        raise FeatureIntegrityError(f"NEW_CROSS_ASSET_INVALID_CLOSE:{path}")
    return frame


def build_cross_asset_features(candidate_metadata: pd.DataFrame, data_root: Path,
                               symbols: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build 30 frozen features using only raw daily bars strictly before each candidate date."""
    candidate = candidate_metadata[["candidate_id", "trading_date", "decision_timestamp_utc"]].copy()
    candidate["trading_date"] = pd.to_datetime(candidate.trading_date, errors="raise").dt.normalize().astype("datetime64[ns]")
    output = candidate[["candidate_id"]].copy()
    source_dates: dict[str, pd.Series] = {}
    source_hash_inputs: dict[str, dict[str, Any]] = {}
    one_day: dict[str, pd.Series] = {}
    five_day: dict[str, pd.Series] = {}

    for symbol in symbols:
        path = data_root / "stocks" / symbol / "daily_raw.parquet"
        daily = _raw_daily(path)
        raw_return = daily.close.pct_change()
        corporate_action = raw_return.abs().gt(.35)
        safe_return = raw_return.mask(corporate_action)
        values = pd.DataFrame({"date": daily.date})
        for window in (1, 5, 20):
            compounded = (1.0 + safe_return).rolling(window, min_periods=window).apply(np.prod, raw=True) - 1.0
            contaminated = corporate_action.rolling(window, min_periods=1).max().astype(bool)
            values[f"new_xasset_{symbol.lower()}_ret_{window}d"] = compounded.mask(contaminated)
        values[f"new_xasset_{symbol.lower()}_rv_20d"] = safe_return.rolling(20, min_periods=15).std(ddof=1) * np.sqrt(252.0)
        values["source_date"] = daily.date
        left = candidate[["candidate_id", "trading_date"]].sort_values("trading_date")
        right = values.sort_values("date")
        joined = pd.merge_asof(left, right, left_on="trading_date", right_on="date",
                               direction="backward", allow_exact_matches=False)
        joined = joined.set_index("candidate_id").reindex(candidate.candidate_id)
        staleness = pd.Series([(d - s).days if pd.notna(s) else np.nan
                               for d, s in zip(joined.trading_date, joined.source_date)], index=joined.index)
        if staleness.isna().any() or staleness.gt(7).any() or staleness.le(0).any():
            raise FeatureIntegrityError(f"SOURCE_AVAILABILITY_TIME_VIOLATION:{symbol}")
        feature_columns = [column for column in joined if column.startswith("new_xasset_")]
        for column in feature_columns:
            output[column] = joined[column].to_numpy()
        source_dates[symbol] = joined.source_date.reset_index(drop=True)
        one_day[symbol] = joined[f"new_xasset_{symbol.lower()}_ret_1d"].reset_index(drop=True)
        five_day[symbol] = joined[f"new_xasset_{symbol.lower()}_ret_5d"].reset_index(drop=True)
        source_hash_inputs[symbol] = {
            "path": str(path), "rows": len(daily), "min_date": str(daily.date.min().date()),
            "max_date": str(daily.date.max().date()), "corporate_action_rows": int(corporate_action.sum()),
        }

    one = pd.DataFrame(one_day)
    five = pd.DataFrame(five_day)
    output["new_xasset_breadth_positive_1d"] = one.gt(0).mean(axis=1)
    output["new_xasset_breadth_positive_5d"] = five.gt(0).mean(axis=1)
    output["new_xasset_dispersion_1d"] = one.std(axis=1, ddof=1)
    output["new_xasset_iwm_minus_spy_5d"] = five["IWM"] - five["SPY"]
    output["new_xasset_smh_minus_spy_5d"] = five["SMH"] - five["SPY"]
    output["new_xasset_xlk_minus_xlf_5d"] = five["XLK"] - five["XLF"]
    feature_columns = [column for column in output if column.startswith("new_xasset_")]
    if len(feature_columns) != 30 or output.candidate_id.duplicated().any():
        raise FeatureIntegrityError(f"NEW_FEATURE_BUDGET_OR_ROW_IDENTITY:{len(feature_columns)}")
    if np.isinf(output[feature_columns].to_numpy(dtype=float)).any():
        raise FeatureIntegrityError("NEW_FEATURE_NONFINITE_INFINITY")
    max_source = pd.concat(source_dates, axis=1).max(axis=1)
    if any(source >= trade for source, trade in zip(max_source, candidate.trading_date)):
        raise FeatureIntegrityError("FUTURE_INFORMATION_JOIN_DETECTED")
    audit = {
        "feature_count": len(feature_columns), "feature_order": feature_columns,
        "source_contracts": source_hash_inputs,
        "source_date_strictly_before_candidate_count": int(len(candidate)),
        "source_date_violation_count": 0,
        "maximum_source_staleness_calendar_days": int(max(
            (trade - source).days for trade, source in zip(candidate.trading_date, max_source))),
        "corporate_action_rule": "ABS_RAW_1D_RETURN_GT_0.35_INVALIDATES_TOUCHING_WINDOW",
        "backfill_count": 0,
    }
    return output, audit
