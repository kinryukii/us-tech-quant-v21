"""Minimal PIT-safe R28 multi-signal feature additions.

The engine consumes completed one-minute bars only.  Peer data is joined on an
exact UTC timestamp, never with a forward-looking/as-of join.
"""
from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd


BASELINE_FEATURES: Final = (
    "return_5m", "return_15m", "return_60m", "realized_vol_15m",
    "realized_vol_60m", "relative_volume", "range_position", "symbol_code",
    "direction_code", "session_code",
)
R28_FEATURES: Final = (
    "downside_vol_60m", "intrabar_range_15m", "trend_ema_gap_60m",
    "breakout_position_120m", "volume_zscore_60m", "signed_volume_pressure_15m",
    "peer_return_15m", "relative_return_15m",
)
FEATURE_FAMILIES: Final = {
    "volatility_risk": ("downside_vol_60m", "intrabar_range_15m"),
    "trend_structure": ("trend_ema_gap_60m", "breakout_position_120m"),
    "flow": ("volume_zscore_60m", "signed_volume_pressure_15m"),
    "cross_asset": ("peer_return_15m", "relative_return_15m"),
}
BLOCKED_FACTORS: Final = {
    "vix_level_or_term_structure": "VIX is absent from the approved canonical one-minute source.",
    "spy_relative_return": "SPY is absent from the approved canonical one-minute source.",
    "external_flow_or_options_metrics": "No PIT-safe external flow/options source is present in canonical data.",
}
REQUIRED_COLUMNS: Final = ("timestamp_utc", "open", "high", "low", "close", "volume")


class R28ContractError(ValueError):
    """Raised when an input cannot satisfy the R28 bar-close PIT contract."""


def _normalized_bars(frame: pd.DataFrame) -> pd.DataFrame:
    missing = set(REQUIRED_COLUMNS).difference(frame.columns)
    if missing:
        raise R28ContractError("R28_REQUIRED_COLUMNS_MISSING:" + ",".join(sorted(missing)))
    bars = frame.loc[:, REQUIRED_COLUMNS].copy()
    bars["timestamp_utc"] = pd.to_datetime(bars["timestamp_utc"], utc=True, errors="raise")
    if bars["timestamp_utc"].duplicated().any():
        raise R28ContractError("R28_DUPLICATE_SOURCE_TIMESTAMP")
    if not bars["timestamp_utc"].is_monotonic_increasing:
        raise R28ContractError("R28_SOURCE_TIMESTAMP_NOT_SORTED")
    for column in ("open", "high", "low", "close", "volume"):
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    if (bars["close"] <= 0).any() or (bars["volume"] < 0).any():
        raise R28ContractError("R28_INVALID_BAR_VALUE")
    return bars.reset_index(drop=True)


def build_features(primary: pd.DataFrame, peer: pd.DataFrame) -> pd.DataFrame:
    """Build the fixed eight R28 additions using information available at bar t."""
    bars = _normalized_bars(primary)
    peer_bars = _normalized_bars(peer)
    close = bars["close"]
    returns = close.pct_change()
    log_returns = np.log(close).diff()
    volume = bars["volume"]
    downside = log_returns.where(log_returns < 0.0, 0.0).pow(2).rolling(60, min_periods=60).mean().pow(0.5)
    intrabar_range = ((bars["high"] - bars["low"]) / close).rolling(15, min_periods=15).mean()
    ema = close.ewm(span=60, adjust=False, min_periods=60).mean()
    rolling_low = bars["low"].rolling(120, min_periods=120).min()
    rolling_high = bars["high"].rolling(120, min_periods=120).max()
    volume_mean = volume.rolling(60, min_periods=60).mean()
    volume_std = volume.rolling(60, min_periods=60).std()
    signed_volume = np.sign(returns.fillna(0.0)) * volume
    peer_returns = peer_bars.set_index("timestamp_utc")["close"].pct_change(15)
    peer_at_t = bars["timestamp_utc"].map(peer_returns)
    output = pd.DataFrame({
        "timestamp_utc": bars["timestamp_utc"],
        "downside_vol_60m": downside,
        "intrabar_range_15m": intrabar_range,
        "trend_ema_gap_60m": close / ema - 1.0,
        "breakout_position_120m": (close - rolling_low) / (rolling_high - rolling_low).replace(0.0, np.nan),
        "volume_zscore_60m": (volume - volume_mean) / volume_std.replace(0.0, np.nan),
        "signed_volume_pressure_15m": signed_volume.rolling(15, min_periods=15).sum() / volume.rolling(15, min_periods=15).sum().replace(0.0, np.nan),
        "peer_return_15m": peer_at_t,
        "relative_return_15m": close.pct_change(15) - peer_at_t,
    })
    output["source_timestamp_utc"] = output["timestamp_utc"]
    output["max_feature_timestamp_utc"] = output["timestamp_utc"]
    output["feature_information_available"] = True
    return output


def pit_audit(features: pd.DataFrame) -> dict[str, int | bool]:
    """Verify the emitted lineage is bar-close PIT-safe and deterministic in order."""
    required = {"timestamp_utc", "source_timestamp_utc", "max_feature_timestamp_utc", "feature_information_available", *R28_FEATURES}
    missing = required.difference(features.columns)
    if missing:
        raise R28ContractError("R28_FEATURE_OUTPUT_MISSING:" + ",".join(sorted(missing)))
    decision = pd.to_datetime(features["timestamp_utc"], utc=True, errors="raise")
    source = pd.to_datetime(features["source_timestamp_utc"], utc=True, errors="raise")
    maximum = pd.to_datetime(features["max_feature_timestamp_utc"], utc=True, errors="raise")
    timestamp_order_pass = bool(decision.is_monotonic_increasing and not decision.duplicated().any())
    source_pit_pass = bool((source <= decision).all() and (maximum <= decision).all())
    availability_pass = bool(features["feature_information_available"].all())
    return {
        "row_count": int(len(features)), "timestamp_order_pass": timestamp_order_pass,
        "source_pit_pass": source_pit_pass, "availability_pass": availability_pass,
        "pit_pass": bool(timestamp_order_pass and source_pit_pass and availability_pass),
    }
