from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .contracts import (R43B_IDENTITY, R43C_MANIFEST, R43C_VALUES, R43D_MANIFEST,
                        R43D_VALUES, SOURCE_MANIFEST, ContractError, sha256, stable_hash)


WINDOWS = (1, 3, 5, 10, 20, 30, 60)
VOL_WINDOWS = (5, 10, 20, 30, 60)
VOLUME_WINDOWS = (5, 20, 60)
BASE_META = {"candidate_id", "decision_timestamp_utc", "direction", "validation_slice"}


class FeatureError(RuntimeError):
    pass


def _safe_div(a: float, b: float) -> float:
    return float(a / b) if np.isfinite(a) and np.isfinite(b) and abs(b) > 1e-15 else np.nan


def _slope_r2(values: np.ndarray) -> tuple[float, float]:
    if len(values) < 3 or not np.isfinite(values).all():
        return np.nan, np.nan
    x = np.arange(len(values), dtype=float)
    slope, intercept = np.polyfit(x, values, 1)
    fitted = intercept + slope * x
    total = np.square(values - values.mean()).sum()
    r2 = 1.0 - np.square(values - fitted).sum() / total if total > 0 else np.nan
    return float(slope), float(r2)


def _exact_window(bars: pd.DataFrame, position: int, timestamp: pd.Timestamp, minutes: int) -> pd.DataFrame | None:
    start = timestamp - pd.Timedelta(minutes=minutes)
    index = bars.index
    try:
        left = int(index.get_loc(start))
    except KeyError:
        return None
    if left > position or position - left + 1 < minutes + 1:
        return None
    result = bars.iloc[left:position + 1]
    return result if result.index[-1] == timestamp and result.index[0] == start else None


def _ema(values: np.ndarray, span: int) -> float:
    return float(pd.Series(values).ewm(span=span, adjust=False).mean().iloc[-1])


def _technical(history: pd.DataFrame) -> dict[str, float]:
    out: dict[str, float] = {}
    close = history.close.to_numpy(float)
    high = history.high.to_numpy(float)
    low = history.low.to_numpy(float)
    if len(close) < 35 or not np.isfinite(close).all():
        return {name: np.nan for name in ("rsi_14", "stoch_k_14", "stoch_d_3", "stoch_j", "macd_line_12_26",
                                           "macd_signal_9", "macd_hist", "bollinger_position_20", "bollinger_width_20", "atr_14")}
    delta = np.diff(close)
    gains, losses = np.maximum(delta[-14:], 0).mean(), np.maximum(-delta[-14:], 0).mean()
    out["rsi_14"] = 100.0 if losses == 0 and gains > 0 else 0.0 if gains == 0 and losses > 0 else 50.0 if gains == losses == 0 else 100 - 100 / (1 + gains / losses)
    k_values = []
    for end in range(len(close) - 3, len(close)):
        lo, hi = low[end - 13:end + 1].min(), high[end - 13:end + 1].max()
        k_values.append(100 * _safe_div(close[end] - lo, hi - lo))
    out["stoch_k_14"] = k_values[-1]
    out["stoch_d_3"] = float(np.nanmean(k_values)) if np.isfinite(k_values).any() else np.nan
    out["stoch_j"] = 3 * out["stoch_k_14"] - 2 * out["stoch_d_3"]
    series = pd.Series(close)
    macd = series.ewm(span=12, adjust=False).mean() - series.ewm(span=26, adjust=False).mean()
    signal = macd.ewm(span=9, adjust=False).mean()
    out["macd_line_12_26"] = float(macd.iloc[-1] / close[-1])
    out["macd_signal_9"] = float(signal.iloc[-1] / close[-1])
    out["macd_hist"] = float((macd.iloc[-1] - signal.iloc[-1]) / close[-1])
    mean20, std20 = close[-20:].mean(), close[-20:].std(ddof=1)
    out["bollinger_position_20"] = _safe_div(close[-1] - (mean20 - 2 * std20), 4 * std20)
    out["bollinger_width_20"] = _safe_div(4 * std20, mean20)
    previous = close[-15:-1]
    true_range = np.maximum(high[-14:] - low[-14:], np.maximum(np.abs(high[-14:] - previous), np.abs(low[-14:] - previous)))
    out["atr_14"] = float(true_range.mean() / close[-1])
    return out


def _window_features(window: pd.DataFrame, minutes: int, direction_sign: float) -> dict[str, float]:
    close = window.close.to_numpy(float)
    high, low, volume = window.high.to_numpy(float), window.low.to_numpy(float), window.volume.to_numpy(float)
    log_prices = np.log(close)
    returns = np.diff(log_prices)
    slope, r2 = _slope_r2(log_prices)
    total_variation = np.abs(returns).sum()
    lo, hi = low.min(), high.max()
    result = {
        f"cum_return_{minutes}m": float(close[-1] / close[0] - 1),
        f"favorable_return_{minutes}m": float(direction_sign * (close[-1] / close[0] - 1)),
        f"log_return_{minutes}m": float(log_prices[-1] - log_prices[0]),
        f"linear_slope_{minutes}m": slope,
        f"linear_r2_{minutes}m": r2,
        f"path_efficiency_{minutes}m": _safe_div(abs(log_prices[-1] - log_prices[0]), total_variation),
        f"total_variation_{minutes}m": float(total_variation),
        f"drawdown_{minutes}m": float(close[-1] / close.max() - 1),
        f"rebound_{minutes}m": float(close[-1] / close.min() - 1),
        f"distance_high_{minutes}m": float(close[-1] / hi - 1),
        f"distance_low_{minutes}m": float(close[-1] / lo - 1),
        f"range_position_{minutes}m": _safe_div(close[-1] - lo, hi - lo),
        f"positive_bar_fraction_{minutes}m": float(np.mean(returns > 0)) if len(returns) else np.nan,
        f"directional_bar_fraction_{minutes}m": float(np.mean(direction_sign * returns > 0)) if len(returns) else np.nan,
        f"sign_persistence_{minutes}m": float(np.mean(returns[1:] * returns[:-1] > 0)) if len(returns) >= 2 else np.nan,
        f"return_autocorr_{minutes}m": float(np.corrcoef(returns[:-1], returns[1:])[0, 1]) if len(returns) >= 10 and np.std(returns[:-1]) > 0 and np.std(returns[1:]) > 0 else np.nan,
    }
    if minutes in VOL_WINDOWS:
        downside, upside = returns[returns < 0], returns[returns > 0]
        previous = close[:-1]
        true_range = np.maximum(high[1:] - low[1:], np.maximum(np.abs(high[1:] - previous), np.abs(low[1:] - previous)))
        result.update({
            f"realized_volatility_{minutes}m": float(np.std(returns, ddof=1)) if len(returns) >= 2 else np.nan,
            f"downside_semivol_{minutes}m": float(np.sqrt(np.mean(np.square(downside)))) if len(downside) else 0.0,
            f"upside_semivol_{minutes}m": float(np.sqrt(np.mean(np.square(upside)))) if len(upside) else 0.0,
            f"return_skew_{minutes}m": float(pd.Series(returns).skew()) if len(returns) >= 10 else np.nan,
            f"return_kurtosis_{minutes}m": float(pd.Series(returns).kurt()) if len(returns) >= 20 else np.nan,
            f"range_volatility_{minutes}m": float(np.sqrt(np.mean(np.square(np.log(high / low))))) if (low > 0).all() else np.nan,
            f"normalized_atr_{minutes}m": float(true_range.mean() / close[-1]) if len(true_range) else np.nan,
        })
    if minutes in VOLUME_WINDOWS:
        mean, std = volume[:-1].mean(), volume[:-1].std(ddof=1) if len(volume) > 2 else np.nan
        signed = np.sign(returns) * volume[1:]
        result.update({
            f"relative_volume_{minutes}m": _safe_div(volume[-1], mean),
            f"volume_zscore_{minutes}m": _safe_div(volume[-1] - mean, std),
            f"signed_price_volume_{minutes}m": _safe_div(float(signed.sum()), float(volume[1:].sum())),
            f"price_move_per_volume_{minutes}m": _safe_div(abs(close[-1] / close[0] - 1), float(volume[1:].sum())),
        })
        typical = (high + low + close) / 3
        vwap = _safe_div(float((typical * volume).sum()), float(volume.sum()))
        vwap_path = np.cumsum(typical * volume) / np.maximum(np.cumsum(volume), 1e-15)
        vwap_slope, _ = _slope_r2(np.asarray(vwap_path, float))
        result.update({
            f"price_minus_vwap_{minutes}m": _safe_div(close[-1] - vwap, vwap),
            f"vwap_slope_{minutes}m": vwap_slope / close[-1] if np.isfinite(vwap_slope) else np.nan,
            f"price_slope_minus_vwap_slope_{minutes}m": slope - vwap_slope if np.isfinite(slope) and np.isfinite(vwap_slope) else np.nan,
            f"above_vwap_fraction_{minutes}m": float(np.mean(close >= vwap_path)),
            f"vwap_recross_count_{minutes}m": float(np.sum(np.diff(np.sign(close - vwap_path)) != 0)),
        })
    return result


def load_market_bars() -> dict[str, pd.DataFrame]:
    manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    result = {}
    for symbol in ("QQQ", "SOXX"):
        records = [row for row in manifest["files"] if row["symbol"] == symbol and row["timestamp_end_utc"] >= "2019-12-01" and row["timestamp_start_utc"] <= "2025-02-01"]
        pieces = []
        for row in records:
            path = Path(row["path"])
            if not path.is_file() or sha256(path).lower() != row["sha256"].lower():
                raise FeatureError(f"STOP_FAST4_MARKET_SOURCE_HASH:{path}")
            columns = ["timestamp_utc", "timestamp_et", "broker_trade_date", "session", "open", "high", "low", "close", "volume"]
            pieces.append(pd.read_parquet(path, columns=columns))
        bars = pd.concat(pieces, ignore_index=True)
        bars["timestamp_utc"] = pd.to_datetime(bars.timestamp_utc, utc=True, errors="raise")
        bars["timestamp_et"] = pd.to_datetime(bars.timestamp_et, utc=True, errors="raise").dt.tz_convert("America/New_York")
        bars = bars.sort_values("timestamp_utc", kind="mergesort").drop_duplicates("timestamp_utc", keep=False)
        for column in ("open", "high", "low", "close", "volume"):
            bars[column] = pd.to_numeric(bars[column], errors="coerce")
        valid = ((bars.open > 0) & (bars.close > 0) & (bars.high >= bars[["open", "low", "close"]].max(axis=1))
                 & (bars.low <= bars[["open", "high", "close"]].min(axis=1)) & (bars.volume >= 0))
        if not valid.all() or bars.timestamp_utc.duplicated().any():
            raise FeatureError(f"STOP_FAST4_MARKET_BAR_INTEGRITY:{symbol}")
        result[symbol] = bars.set_index("timestamp_utc", drop=False)
    return result


def raw_features_for_candidates(candidates: pd.DataFrame, market: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict[str, Any]]:
    day_cache: dict[str, dict[str, Any]] = {}
    for symbol, bars in market.items():
        dates = bars.broker_trade_date.astype(str)
        first_open = bars.groupby(dates, sort=False).open.first()
        rth = bars.loc[bars.session.astype(str).str.upper().eq("RTH")]
        rth_last = rth.groupby(rth.broker_trade_date.astype(str), sort=False).close.last()
        ordered_dates = list(first_open.index)
        prior_rth = {}
        last = np.nan
        for date in ordered_dates:
            prior_rth[date] = last
            if date in rth_last.index:
                last = float(rth_last.loc[date])
        day_cache[symbol] = {"first_open": first_open.to_dict(), "prior_rth": prior_rth}

    rows, max_sources = [], []
    for record in candidates.itertuples(index=False):
        symbol = str(record.underlying_symbol)
        bars = market[symbol]
        timestamp = pd.Timestamp(record.decision_timestamp_utc)
        if timestamp not in bars.index:
            raise FeatureError(f"STOP_FAST4_DECISION_BAR_MISSING:{record.candidate_id}")
        loc = bars.index.get_loc(timestamp)
        if not isinstance(loc, (int, np.integer)):
            raise FeatureError("STOP_FAST4_DUPLICATE_DECISION_BAR")
        position = int(loc)
        direction_sign = 1.0 if record.head == "UP" else -1.0
        row: dict[str, Any] = {"candidate_id": record.candidate_id}
        windows: dict[int, pd.DataFrame | None] = {}
        for minutes in WINDOWS:
            windows[minutes] = _exact_window(bars, position, timestamp, minutes)
            if windows[minutes] is not None:
                row.update(_window_features(windows[minutes], minutes, direction_sign))
        row["momentum_acceleration_5v20"] = row.get("favorable_return_5m", np.nan) - row.get("favorable_return_20m", np.nan) / 4
        row["momentum_acceleration_10v30"] = row.get("favorable_return_10m", np.nan) - row.get("favorable_return_30m", np.nan) / 3
        row["volatility_ratio_5v60"] = _safe_div(row.get("realized_volatility_5m", np.nan), row.get("realized_volatility_60m", np.nan))
        row["volatility_ratio_10v30"] = _safe_div(row.get("realized_volatility_10m", np.nan), row.get("realized_volatility_30m", np.nan))
        row["volume_acceleration_5v20"] = _safe_div(row.get("relative_volume_5m", np.nan), row.get("relative_volume_20m", np.nan))

        history = _exact_window(bars, position, timestamp, 120)
        if history is None:
            history = bars.iloc[0:0]
        row.update(_technical(history))
        current = bars.iloc[position]
        et = current.timestamp_et
        minute = et.hour * 60 + et.minute
        row.update({
            "time_sin": float(np.sin(2 * np.pi * minute / 1440)),
            "time_cos": float(np.cos(2 * np.pi * minute / 1440)),
            "minutes_since_rth_open": float(minute - 570),
            "minutes_to_rth_close": float(960 - minute),
            "session_premarket": float(str(current.session).upper() in {"PRE", "PREMARKET"}),
            "session_regular": float(str(current.session).upper() == "RTH"),
            "session_afterhours": float(str(current.session).upper() in {"POST", "AFTERHOURS"}),
            "day_of_week": float(et.dayofweek),
        })
        date = str(current.broker_trade_date)
        first_open = day_cache[symbol]["first_open"].get(date, np.nan)
        previous_close = day_cache[symbol]["prior_rth"].get(date, np.nan)
        row["overnight_gap"] = _safe_div(first_open - previous_close, previous_close)
        row["opening_gap"] = row["overnight_gap"] if minute >= 570 else np.nan
        day_rows = bars.loc[(bars.broker_trade_date.astype(str).eq(date)) & (bars.timestamp_utc <= timestamp)]
        row["distance_intraday_high"] = float(current.close / day_rows.high.max() - 1)
        row["distance_intraday_low"] = float(current.close / day_rows.low.min() - 1)
        row["intraday_cumulative_volume"] = float(day_rows.volume.sum())

        peer = "SOXX" if symbol == "QQQ" else "QQQ"
        peer_bars = market[peer]
        if timestamp not in peer_bars.index:
            raise FeatureError(f"STOP_FAST4_PEER_DECISION_BAR_MISSING:{record.candidate_id}")
        peer_pos = int(peer_bars.index.get_loc(timestamp))
        for minutes in (5, 15, 30, 60):
            own_window, peer_window = windows.get(minutes), _exact_window(peer_bars, peer_pos, timestamp, minutes)
            own_ret = own_window.close.iloc[-1] / own_window.close.iloc[0] - 1 if own_window is not None else np.nan
            peer_ret = peer_window.close.iloc[-1] / peer_window.close.iloc[0] - 1 if peer_window is not None else np.nan
            row[f"peer_return_{minutes}m_raw"] = peer_ret
            row[f"relative_strength_{minutes}m"] = own_ret - peer_ret
            row[f"cross_asset_momentum_disagreement_{minutes}m"] = float(np.sign(own_ret) != np.sign(peer_ret)) if np.isfinite(own_ret) and np.isfinite(peer_ret) else np.nan
            if minutes in (30, 60) and own_window is not None and peer_window is not None:
                own_vol = np.std(np.diff(np.log(own_window.close)), ddof=1)
                peer_vol = np.std(np.diff(np.log(peer_window.close)), ddof=1)
                row[f"cross_asset_volatility_disagreement_{minutes}m"] = own_vol - peer_vol
        rows.append(row)
        max_sources.append(timestamp)
    output = pd.DataFrame(rows)
    output["max_source_timestamp_utc"] = max_sources
    audit = {
        "row_count": len(output), "duplicate_candidate_count": int(output.candidate_id.duplicated().sum()),
        "future_source_timestamp_count": int((pd.to_datetime(output.max_source_timestamp_utc, utc=True) > pd.to_datetime(candidates.decision_timestamp_utc, utc=True)).sum()),
        "source_symbols": sorted(market), "raw_feature_count": len(output.columns) - 2,
    }
    if audit["duplicate_candidate_count"] or audit["future_source_timestamp_count"]:
        raise FeatureError("STOP_FAST4_RAW_FEATURE_PIT_INTEGRITY")
    return output, audit


def family_for(name: str) -> str:
    if name.startswith(("vix_", "soxx_")):
        return "regime"
    if name in {"return_acceleration_5v15", "trend_efficiency_15m", "trend_efficiency_60m", "predecision_mfe_15m", "predecision_mae_15m", "drawdown_from_favorable_extreme_15m", "close_location_15m", "directional_path_consistency_15m"}:
        return "r43d_path_shape"
    if name.startswith(("realized_volatility_", "downside_semivol_", "upside_semivol_", "return_skew_", "return_kurtosis_", "range_volatility_", "normalized_atr_", "volatility_ratio_")):
        return "volatility_distribution"
    if name.startswith(("relative_volume_", "volume_zscore_", "signed_price_volume_", "price_move_per_volume_", "volume_acceleration_", "intraday_cumulative_volume")):
        return "volume_liquidity"
    if "vwap" in name:
        return "vwap_geometry"
    if name.startswith(("rsi_", "stoch_", "macd_", "bollinger_", "atr_")):
        return "technical"
    if name.startswith(("time_", "minutes_", "session_", "day_of_week", "overnight_gap", "opening_gap")):
        return "time_session"
    if name.startswith(("peer_", "relative_strength_", "cross_asset_")):
        return "cross_asset"
    if name.startswith("missing_family_"):
        return "missingness"
    if name in {"return_5m", "return_15m", "return_60m", "realized_vol_15m", "realized_vol_60m", "relative_volume", "range_position", "symbol_code", "direction_code", "session_code", "volume_zscore_60m", "signed_volume_pressure_15m", "peer_return_15m", "relative_return_15m"}:
        return "r43b_baseline"
    return "return_path_shape"


def materialize_feature_matrix(targets: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    base = pd.read_csv(R43B_IDENTITY)
    base["decision_timestamp_utc"] = pd.to_datetime(base.decision_timestamp_utc, utc=True, errors="raise")
    regime = pd.read_parquet(R43C_VALUES)
    path = pd.read_parquet(R43D_VALUES)
    if len(base) != len(targets) or base.candidate_id.duplicated().any() or regime.candidate_id.duplicated().any() or path.candidate_id.duplicated().any():
        raise FeatureError("STOP_FAST4_PRECOMPUTED_FEATURE_IDENTITY")
    identity = targets[["candidate_id", "decision_timestamp_utc", "head", "underlying_symbol"]].merge(
        base, on="candidate_id", validate="one_to_one", suffixes=("_target", "_base"))
    if not (pd.to_datetime(identity.decision_timestamp_utc_target, utc=True).to_numpy() == pd.to_datetime(identity.decision_timestamp_utc_base, utc=True).to_numpy()).all():
        raise FeatureError("STOP_FAST4_BASE_FEATURE_TIMESTAMP_IDENTITY")
    candidates = identity[["candidate_id", "decision_timestamp_utc_target", "head", "underlying_symbol"]].rename(columns={"decision_timestamp_utc_target": "decision_timestamp_utc"})
    raw1, raw_audit = raw_features_for_candidates(candidates, load_market_bars())
    raw2, _ = raw_features_for_candidates(candidates, load_market_bars())
    raw_hash_one = hashlib.sha256(pd.util.hash_pandas_object(raw1, index=False).values.tobytes()).hexdigest()
    raw_hash_two = hashlib.sha256(pd.util.hash_pandas_object(raw2, index=False).values.tobytes()).hexdigest()
    if raw_hash_one != raw_hash_two:
        raise FeatureError("STOP_FAST4_NONDETERMINISTIC_FEATURE_GENERATION")
    path_check = candidates[["candidate_id", "decision_timestamp_utc"]].merge(path[["candidate_id", "max_source_timestamp_utc"]], on="candidate_id", validate="one_to_one")
    if (pd.to_datetime(path_check.max_source_timestamp_utc, utc=True) > path_check.decision_timestamp_utc).any():
        raise FeatureError("STOP_FAST4_R43D_PATH_SOURCE_TIMESTAMP")
    path = path.drop(columns=["max_source_timestamp_utc"])
    raw1 = raw1.drop(columns=["max_source_timestamp_utc"])
    frame = base.merge(regime, on="candidate_id", validate="one_to_one").merge(path, on="candidate_id", validate="one_to_one").merge(raw1, on="candidate_id", validate="one_to_one")
    frame["decision_timestamp_utc"] = pd.to_datetime(frame.decision_timestamp_utc, utc=True)
    feature_columns = [c for c in frame.columns if c not in BASE_META | {"max_source_timestamp_utc"}]
    for family in sorted({family_for(c) for c in feature_columns}):
        members = [c for c in feature_columns if family_for(c) == family]
        frame[f"missing_family_{family}"] = frame[members].isna().any(axis=1).astype(float)
    audit = {**raw_audit, "r43b_identity_sha256": sha256(R43B_IDENTITY), "r43c_manifest_sha256": sha256(R43C_MANIFEST),
             "r43d_manifest_sha256": sha256(R43D_MANIFEST), "option_feature_family_status": "SKIPPED_NO_HISTORICAL_PIT_OVERLAP"}
    return frame, audit


def quality_audit(frame: pd.DataFrame, target: pd.Series) -> tuple[pd.DataFrame, dict[str, Any], dict[str, str]]:
    nonfeatures = BASE_META | {"max_source_timestamp_utc"}
    features = [c for c in frame.columns if c not in nonfeatures]
    numeric = frame[features].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    constants = [c for c in features if numeric[c].nunique(dropna=False) <= 1]
    near_constants = [c for c in features if c not in constants and numeric[c].value_counts(dropna=False, normalize=True).iloc[0] > 0.999]
    duplicate_of: dict[str, str] = {}
    signatures: dict[str, str] = {}
    for column in features:
        if column in constants or column in near_constants:
            continue
        signature = hashlib.sha256(pd.util.hash_pandas_object(numeric[column], index=False).values.tobytes()).hexdigest()
        if signature in signatures and numeric[column].equals(numeric[signatures[signature]]):
            duplicate_of[column] = signatures[signature]
        else:
            signatures[signature] = column
    kept = [c for c in features if c not in set(constants) | set(near_constants) | set(duplicate_of)]
    suspicious = {}
    y = pd.Series(target, index=frame.index, dtype=float)
    for column in kept:
        valid = numeric[column].notna() & y.notna()
        if valid.sum() >= 30 and numeric.loc[valid, column].nunique() > 1:
            correlation = float(numeric.loc[valid, column].corr(y.loc[valid]))
            if abs(correlation) >= 0.98:
                suspicious[column] = correlation
            if np.array_equal(numeric.loc[valid, column].to_numpy(), y.loc[valid].to_numpy()):
                raise FeatureError(f"STOP_FAST4_EXACT_TARGET_LEAKAGE:{column}")
    if suspicious:
        raise FeatureError(f"STOP_FAST4_SUSPICIOUS_NEAR_PERFECT_TARGET_CORRELATION:{suspicious}")
    output = frame[[c for c in frame.columns if c in nonfeatures] + kept].copy()
    output[kept] = numeric[kept]
    families = {c: family_for(c) for c in kept}
    audit = {
        "input_feature_count": len(features), "output_feature_count": len(kept),
        "constant_columns": constants, "near_constant_columns": near_constants,
        "duplicate_columns": duplicate_of, "infinite_value_count_before_normalization": int(np.isinf(frame[features].select_dtypes(include=[np.number]).to_numpy()).sum()),
        "nan_count": int(output[kept].isna().sum().sum()), "exact_target_leakage_count": 0,
        "suspicious_near_perfect_target_correlation_count": 0,
        "family_count": len(set(families.values())), "families": sorted(set(families.values())),
    }
    return output, audit, families
