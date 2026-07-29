#!/usr/bin/env python
r"""V22.057 FAST3 multifactor state-machine backtest R1.

Frozen research architecture:
- Prior-day official Cboe VIX regime.
- QQQ/SOXX 5-minute RSI, KDJ, MACD and 30-minute relative strength.
- RTH cumulative VWAP and execution-ETF ATR.
- TQQQ/SOXL/SQQQ/SOXS next-minute-open execution.
- One active position, dynamic risk exits and a fixed-60-minute control.
- No parameter sweep, no broker action and no paper trading.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

VERSION = "V22.057_FAST3_MULTIFACT_STATE_MACHINE_BACKTEST_R1"
SIGNAL_SYMBOLS = ("QQQ", "SOXX")
EXECUTION_SYMBOLS = ("TQQQ", "SOXL", "SQQQ", "SOXS")
ALL_SYMBOLS = SIGNAL_SYMBOLS + EXECUTION_SYMBOLS
VARIANTS = (
    "CORE_FULL",
    "ABLATION_NO_VIX",
    "ABLATION_NO_KDJ",
    "FIXED_60M_EXIT_CONTROL",
)
RTH_START = 9 * 60 + 30
RTH_END = 15 * 60 + 59
SIGNAL_START = 9 * 60 + 50
SIGNAL_END = 15 * 60 + 14
FORCED_EXIT_MINUTE = 15 * 60 + 55
ENTRY_COST = 0.0005
EXIT_COST = 0.0005
RISK_PER_TRADE = 0.0025
MAX_WEIGHT = 0.33
MIN_STOP = 0.006
MAX_STOP = 0.012
TRAIL_ARM = 0.008
MIN_TRAIL = 0.0035
MAX_TRAIL = 0.008
NO_PROGRESS_MINUTES = 15
MAX_HOLD_MINUTES = 120
FIXED_CONTROL_MINUTES = 60
COOLDOWN_MINUTES = 30
MAX_TRADES_PER_DAY = 3
MAX_STOP_EXITS_PER_DAY = 2
MAX_DAILY_ACCOUNT_LOSS = -0.01
RSZ_THRESHOLD = 0.25
MIN_PIT_BASELINE_COUNT = 20
BOOTSTRAP_REPS = 1000
MASTER_SEED = 2026072601
PERIOD_ORDER = {
    "2018-2022_DEVELOPMENT": 0,
    "2023-2024_VALIDATION": 1,
    "2025-2026_YTD_CONFIRMATION": 2,
}


class StudyError(RuntimeError):
    """The backtest cannot continue safely."""


@dataclass
class RunningStats:
    count: int = 0
    total: float = 0.0

    @property
    def mean(self) -> float:
        return self.total / self.count if self.count else math.nan

    def add(self, value: float) -> None:
        if np.isfinite(value):
            self.count += 1
            self.total += float(value)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer, np.floating)):
        if isinstance(value, np.floating) and not np.isfinite(value):
            return None
        return value.item()
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value)!r}")


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=json_default)
            + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def study_period(year: int) -> str:
    if 2018 <= year <= 2022:
        return "2018-2022_DEVELOPMENT"
    if 2023 <= year <= 2024:
        return "2023-2024_VALIDATION"
    if 2025 <= year <= 2026:
        return "2025-2026_YTD_CONFIRMATION"
    return "OUTSIDE_STUDY"


def validate_v22_056(summary: Mapping[str, Any]) -> None:
    expected = {
        "final_status": "PASS",
        "final_decision": (
            "OFFICIAL_CBOE_DAILY_VIX_READY_FOR_PRIOR_DAY_REGIME_FILTER"
        ),
        "v22_055_validated": True,
        "prior_day_shift_validated": True,
        "daily_vix_regime_ready": True,
        "intraday_vix_data_ready": False,
        "intraday_vix_features_allowed": False,
        "vix_proxy_substitution_used": False,
        "data_ready_for_daily_vix_multifactor_backtest": True,
        "multifactor_backtest_executed": False,
        "parameter_sweep_executed": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }
    failures = [
        f"{key}: expected {value!r}, got {summary.get(key)!r}"
        for key, value in expected.items()
        if summary.get(key) != value
    ]
    if failures:
        raise StudyError("V22.056 validation failed: " + "; ".join(failures))


def find_column(frame: pd.DataFrame, aliases: Iterable[str]) -> str:
    mapping = {str(column).strip().lower(): str(column) for column in frame.columns}
    for alias in aliases:
        if alias.lower() in mapping:
            return mapping[alias.lower()]
    raise StudyError(f"Missing required column from aliases={tuple(aliases)}")


def normalize_timestamp_utc(series: pd.Series) -> pd.Series:
    values = pd.to_datetime(series, errors="raise", utc=True)
    if values.dt.tz is None:
        raise StudyError("timestamp_utc must be timezone-aware")
    return values


def symbol_month_from_path(path: Path) -> tuple[str, str, str]:
    symbol = year = month = None
    for part in path.parts:
        match = re.fullmatch(r"symbol=(.+)", part, re.I)
        if match:
            symbol = match.group(1).upper().replace("US.", "")
        match = re.fullmatch(r"year=(\d{4})", part, re.I)
        if match:
            year = match.group(1)
        match = re.fullmatch(r"month=(\d{1,2})", part, re.I)
        if match:
            month = f"{int(match.group(1)):02d}"
    if not all((symbol, year, month)):
        raise StudyError(f"Cannot parse partition path: {path}")
    return symbol, year, month


def index_canonical(root: Path) -> dict[tuple[str, str, str], Path]:
    result: dict[tuple[str, str, str], Path] = {}
    for path in sorted(root.rglob("*.parquet")):
        key = symbol_month_from_path(path)
        if key[0] not in ALL_SYMBOLS:
            continue
        if key in result:
            raise StudyError(f"Duplicate Canonical partition: {key}")
        result[key] = path
    counts = {symbol: 0 for symbol in ALL_SYMBOLS}
    for symbol, _, _ in result:
        counts[symbol] += 1
    missing = {symbol: count for symbol, count in counts.items() if count == 0}
    if missing:
        raise StudyError(f"Missing Canonical symbols: {missing}")
    return result


def load_rth_partition(path: Path) -> pd.DataFrame:
    raw = pd.read_parquet(path)
    if raw.empty:
        return pd.DataFrame(
            columns=[
                "timestamp_utc", "timestamp_et", "trade_date", "minute_et",
                "open", "high", "low", "close", "volume",
            ]
        )
    timestamp = normalize_timestamp_utc(raw[find_column(raw, ("timestamp_utc",))])
    timestamp_et = timestamp.dt.tz_convert("America/New_York")
    minute = timestamp_et.dt.hour * 60 + timestamp_et.dt.minute
    mask = (minute >= RTH_START) & (minute <= RTH_END)
    frame = pd.DataFrame(
        {
            "timestamp_utc": timestamp.loc[mask],
            "timestamp_et": timestamp_et.loc[mask],
            "trade_date": timestamp_et.loc[mask].dt.strftime("%Y-%m-%d"),
            "minute_et": minute.loc[mask].astype(int),
            "open": pd.to_numeric(
                raw.loc[mask, find_column(raw, ("open",))], errors="coerce"
            ),
            "high": pd.to_numeric(
                raw.loc[mask, find_column(raw, ("high",))], errors="coerce"
            ),
            "low": pd.to_numeric(
                raw.loc[mask, find_column(raw, ("low",))], errors="coerce"
            ),
            "close": pd.to_numeric(
                raw.loc[mask, find_column(raw, ("close",))], errors="coerce"
            ),
            "volume": pd.to_numeric(
                raw.loc[mask, find_column(raw, ("volume",))], errors="coerce"
            ).fillna(0.0),
        }
    ).dropna(subset=["timestamp_utc", "open", "high", "low", "close"])
    frame = frame.sort_values("timestamp_utc", kind="mergesort").reset_index(drop=True)
    if frame["timestamp_utc"].duplicated().any():
        raise StudyError(f"Duplicate RTH timestamp in {path}")
    return frame


def aggregate_complete_5m(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    work = frame.copy()
    volume = work["volume"].clip(lower=0.0)
    typical = (work["high"] + work["low"] + work["close"]) / 3.0
    cumulative_volume = volume.groupby(work["trade_date"], sort=False).cumsum()
    cumulative_value = (typical * volume).groupby(work["trade_date"], sort=False).cumsum()
    fallback = (
        work.groupby("trade_date", sort=False)["close"]
        .expanding().mean().reset_index(level=0, drop=True)
    )
    work["vwap"] = cumulative_value.divide(
        cumulative_volume.where(cumulative_volume > 0)
    ).fillna(fallback)
    work["bucket"] = ((work["minute_et"] - RTH_START) // 5).astype(int)
    bars = (
        work.groupby(["trade_date", "bucket"], sort=True)
        .agg(
            timestamp_utc=("timestamp_utc", "max"),
            timestamp_et=("timestamp_et", "max"),
            minute_et=("minute_et", "max"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            vwap=("vwap", "last"),
            minute_count=("close", "size"),
        )
        .reset_index()
    )
    return bars.loc[bars["minute_count"] == 5].reset_index(drop=True)


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    result = 100.0 - 100.0 / (1.0 + rs)
    return result.where(avg_loss != 0.0, 100.0)


def kdj(frame: pd.DataFrame, period: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    lowest = frame["low"].rolling(period, min_periods=period).min()
    highest = frame["high"].rolling(period, min_periods=period).max()
    denominator = (highest - lowest).replace(0.0, np.nan)
    rsv = ((frame["close"] - lowest) / denominator * 100.0).fillna(50.0)
    k = pd.Series(index=frame.index, dtype=float)
    d = pd.Series(index=frame.index, dtype=float)
    previous_k = previous_d = 50.0
    for index, value in rsv.items():
        previous_k = (2.0 / 3.0) * previous_k + (1.0 / 3.0) * float(value)
        previous_d = (2.0 / 3.0) * previous_d + (1.0 / 3.0) * previous_k
        k.loc[index] = previous_k
        d.loc[index] = previous_d
    return k, d, 3.0 * k - 2.0 * d


def atr_wilder(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            (frame["high"] - frame["low"]).abs(),
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(
        alpha=1.0 / period, adjust=False, min_periods=period
    ).mean()


def add_factors(bars: pd.DataFrame) -> pd.DataFrame:
    result = bars.sort_values("timestamp_utc", kind="mergesort").reset_index(drop=True).copy()
    result["rsi14"] = rsi_wilder(result["close"], 14)
    k, d, j = kdj(result, 9)
    result["kdj_k"], result["kdj_d"], result["kdj_j"] = k, d, j
    result["macd_dif"] = ema(result["close"], 12) - ema(result["close"], 26)
    result["macd_dea"] = ema(result["macd_dif"], 9)
    result["macd_hist"] = result["macd_dif"] - result["macd_dea"]
    result["atr14"] = atr_wilder(result, 14)
    result["atr_pct"] = result["atr14"] / result["close"]
    result["ret_5m"] = result["close"].pct_change()
    result["sigma_5m_20"] = result["ret_5m"].rolling(20, min_periods=20).std(ddof=0)

    pieces = []
    for _, day in result.groupby("trade_date", sort=True):
        work = day.copy()
        work["ret_30m"] = work["close"] / work["close"].shift(6) - 1.0
        work["previous_high"] = work["high"].shift(1)
        work["previous_low"] = work["low"].shift(1)
        work["rsi_prev1"] = work["rsi14"].shift(1)
        work["rsi_prior3_min"] = work["rsi14"].shift(1).rolling(3, min_periods=3).min()
        work["rsi_prior3_max"] = work["rsi14"].shift(1).rolling(3, min_periods=3).max()
        work["rsi_prior3_in_long_zone"] = (
            work["rsi14"].shift(1).rolling(3, min_periods=3)
            .apply(lambda values: float(np.any((values >= 45.0) & (values <= 55.0))), raw=True)
            .fillna(0.0).astype(bool)
        )
        work["rsi_prior3_in_short_zone"] = (
            work["rsi14"].shift(1).rolling(3, min_periods=3)
            .apply(lambda values: float(np.any((values >= 45.0) & (values <= 58.0))), raw=True)
            .fillna(0.0).astype(bool)
        )
        work["k_prev1"] = work["kdj_k"].shift(1)
        work["d_prev1"] = work["kdj_d"].shift(1)
        work["j_prev1"] = work["kdj_j"].shift(1)
        work["hist_prev1"] = work["macd_hist"].shift(1)
        work["hist_prev2"] = work["macd_hist"].shift(2)
        work["close_below_vwap"] = work["close"] < work["vwap"]
        prior_below = work["close_below_vwap"].shift(1)
        work["two_consecutive_below_vwap_prior3"] = (
            (prior_below & prior_below.shift(1))
            | (prior_below.shift(1) & prior_below.shift(2))
        ).fillna(False)
        work["close_above_vwap"] = work["close"] > work["vwap"]
        prior_above = work["close_above_vwap"].shift(1)
        work["two_consecutive_above_vwap_prior3"] = (
            (prior_above & prior_above.shift(1))
            | (prior_above.shift(1) & prior_above.shift(2))
        ).fillna(False)
        pieces.append(work)
    return pd.concat(pieces, ignore_index=True) if pieces else result


def build_all_factor_tables(
    canonical_index: Mapping[tuple[str, str, str], Path],
) -> dict[str, pd.DataFrame]:
    tables: dict[str, pd.DataFrame] = {}
    for symbol in ALL_SYMBOLS:
        bars = []
        paths = [
            path for (current, _, _), path in sorted(canonical_index.items())
            if current == symbol
        ]
        for path in paths:
            partition = load_rth_partition(path)
            aggregated = aggregate_complete_5m(partition)
            if not aggregated.empty:
                bars.append(aggregated)
        if not bars:
            raise StudyError(f"No complete 5-minute bars for {symbol}")
        combined = pd.concat(bars, ignore_index=True).sort_values(
            "timestamp_utc", kind="mergesort"
        ).reset_index(drop=True)
        if combined["timestamp_utc"].duplicated().any():
            raise StudyError(f"Duplicate 5-minute timestamps for {symbol}")
        tables[symbol] = add_factors(combined)
    return tables


def prefixed(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
    keep = [
        "timestamp_utc", "timestamp_et", "trade_date", "minute_et", "open",
        "high", "low", "close", "vwap", "rsi14", "kdj_k", "kdj_d",
        "kdj_j", "macd_dif", "macd_dea", "macd_hist", "atr_pct",
        "sigma_5m_20", "ret_30m", "previous_high", "previous_low",
        "rsi_prev1", "rsi_prior3_min", "rsi_prior3_max",
        "rsi_prior3_in_long_zone", "rsi_prior3_in_short_zone", "k_prev1",
        "d_prev1", "j_prev1", "hist_prev1", "hist_prev2",
        "two_consecutive_below_vwap_prior3",
        "two_consecutive_above_vwap_prior3",
    ]
    selected = frame[keep].copy().set_index("timestamp_utc")
    return selected.rename(columns={column: f"{prefix}_{column}" for column in selected.columns})


def build_aligned_factors(tables: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    aligned = prefixed(tables["QQQ"], "qqq").join(
        prefixed(tables["SOXX"], "soxx"), how="inner"
    )
    for symbol in EXECUTION_SYMBOLS:
        execution = tables[symbol][["timestamp_utc", "atr_pct"]].copy()
        execution = execution.set_index("timestamp_utc").rename(
            columns={"atr_pct": f"{symbol.lower()}_atr_pct"}
        )
        aligned = aligned.join(execution, how="left")
    aligned = aligned.loc[
        aligned["qqq_trade_date"] == aligned["soxx_trade_date"]
    ].copy()
    aligned["trade_date"] = aligned["qqq_trade_date"]
    aligned["signal_timestamp_et"] = aligned["qqq_timestamp_et"]
    aligned["minute_et"] = aligned["qqq_minute_et"]
    qvol = aligned["qqq_sigma_5m_20"] * math.sqrt(6.0)
    svol = aligned["soxx_sigma_5m_20"] * math.sqrt(6.0)
    denominator = np.sqrt(qvol.pow(2) + svol.pow(2)).replace(0.0, np.nan)
    aligned["rsz_30"] = (
        aligned["soxx_ret_30m"] - aligned["qqq_ret_30m"]
    ) / denominator
    return aligned.sort_index()


def load_vix_features(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise StudyError(f"VIX feature file not found: {path}")
    frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
    required = [
        "trade_date", "vix_prev_close", "vix_prev_day_return",
        "vix_pctl_252_prior", "vix_long_regime_allowed_p80",
        "vix_short_regime_elevated_p50",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise StudyError(f"VIX feature file missing columns: {missing}")
    result = frame[required].copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="raise").dt.strftime("%Y-%m-%d")
    for column in ["vix_prev_close", "vix_prev_day_return", "vix_pctl_252_prior"]:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    for column in ["vix_long_regime_allowed_p80", "vix_short_regime_elevated_p50"]:
        if result[column].dtype != bool:
            result[column] = result[column].astype(str).str.lower().isin({"true", "1", "yes"})
    return result.drop_duplicates("trade_date", keep="last")


def selected_prefix_and_execution(direction: str, rsz: float) -> tuple[str, str] | None:
    if not np.isfinite(rsz) or abs(rsz) < RSZ_THRESHOLD:
        return None
    if direction == "LONG":
        return ("soxx", "SOXL") if rsz >= RSZ_THRESHOLD else ("qqq", "TQQQ")
    return ("soxx", "SOXS") if rsz <= -RSZ_THRESHOLD else ("qqq", "SQQQ")


def trend_gate(row: pd.Series, direction: str) -> bool:
    if direction == "LONG":
        return bool(
            row["qqq_close"] > row["qqq_vwap"]
            and row["soxx_close"] > row["soxx_vwap"]
            and row["qqq_ret_30m"] > 0
            and row["soxx_ret_30m"] > 0
            and row["qqq_macd_hist"] > 0
            and row["soxx_macd_hist"] > 0
            and row["qqq_macd_hist"] >= row["qqq_hist_prev1"] >= row["qqq_hist_prev2"]
            and row["soxx_macd_hist"] >= row["soxx_hist_prev1"] >= row["soxx_hist_prev2"]
        )
    return bool(
        row["qqq_close"] < row["qqq_vwap"]
        and row["soxx_close"] < row["soxx_vwap"]
        and row["qqq_ret_30m"] < 0
        and row["soxx_ret_30m"] < 0
        and row["qqq_macd_hist"] < 0
        and row["soxx_macd_hist"] < 0
        and row["qqq_macd_hist"] <= row["qqq_hist_prev1"] <= row["qqq_hist_prev2"]
        and row["soxx_macd_hist"] <= row["soxx_hist_prev1"] <= row["soxx_hist_prev2"]
    )


def entry_component_gates(row: pd.Series, direction: str, prefix: str) -> dict[str, bool]:
    if direction == "LONG":
        rsi_gate = bool(
            row[f"{prefix}_rsi_prior3_in_long_zone"]
            and row[f"{prefix}_rsi_prior3_min"] >= 40.0
            and row[f"{prefix}_rsi_prev1"] <= 52.0
            and 52.0 < row[f"{prefix}_rsi14"] < 68.0
        )
        kdj_gate = bool(
            row[f"{prefix}_k_prev1"] <= row[f"{prefix}_d_prev1"]
            and row[f"{prefix}_kdj_k"] > row[f"{prefix}_kdj_d"]
            and row[f"{prefix}_kdj_k"] < 80.0
            and row[f"{prefix}_kdj_j"] > row[f"{prefix}_j_prev1"]
        )
        price_gate = bool(
            not row[f"{prefix}_two_consecutive_below_vwap_prior3"]
            and row[f"{prefix}_close"] > row[f"{prefix}_vwap"]
            and row[f"{prefix}_close"] > row[f"{prefix}_previous_high"]
            and row[f"{prefix}_macd_dif"] > row[f"{prefix}_macd_dea"]
            and row[f"{prefix}_macd_hist"] > row[f"{prefix}_hist_prev1"]
        )
    else:
        rsi_gate = bool(
            row[f"{prefix}_rsi_prior3_in_short_zone"]
            and row[f"{prefix}_rsi_prev1"] >= 48.0
            and 28.0 < row[f"{prefix}_rsi14"] < 48.0
        )
        kdj_gate = bool(
            row[f"{prefix}_k_prev1"] >= row[f"{prefix}_d_prev1"]
            and row[f"{prefix}_kdj_k"] < row[f"{prefix}_kdj_d"]
            and row[f"{prefix}_kdj_k"] > 20.0
            and row[f"{prefix}_kdj_j"] < row[f"{prefix}_j_prev1"]
        )
        price_gate = bool(
            not row[f"{prefix}_two_consecutive_above_vwap_prior3"]
            and row[f"{prefix}_close"] < row[f"{prefix}_vwap"]
            and row[f"{prefix}_close"] < row[f"{prefix}_previous_low"]
            and row[f"{prefix}_macd_dif"] < row[f"{prefix}_macd_dea"]
            and row[f"{prefix}_macd_hist"] < row[f"{prefix}_hist_prev1"]
        )
    return {"rsi": rsi_gate, "kdj": kdj_gate, "price": price_gate}


def build_candidates(aligned: pd.DataFrame, vix: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = aligned.reset_index().merge(vix, on="trade_date", how="left").set_index("timestamp_utc")
    work = work.loc[
        (work["minute_et"] >= SIGNAL_START) & (work["minute_et"] <= SIGNAL_END)
    ].copy()
    rows: list[dict[str, Any]] = []
    funnel = {
        "eligible_5m_bars": int(len(work)),
        "long_trend": 0, "short_trend": 0, "relative_strength_clear": 0,
        "long_rsi": 0, "short_rsi": 0, "long_kdj": 0, "short_kdj": 0,
        "long_price": 0, "short_price": 0,
        "core_long_signal": 0, "core_short_signal": 0,
        "no_vix_signal": 0, "no_kdj_signal": 0,
    }
    for timestamp, row in work.iterrows():
        if study_period(pd.Timestamp(row["signal_timestamp_et"]).year) == "OUTSIDE_STUDY":
            continue
        for direction in ("LONG", "SHORT"):
            trend = trend_gate(row, direction)
            if trend:
                funnel[f"{direction.lower()}_trend"] += 1
            selected = selected_prefix_and_execution(direction, float(row["rsz_30"]))
            if selected is None:
                continue
            funnel["relative_strength_clear"] += 1
            prefix, execution_symbol = selected
            gates = entry_component_gates(row, direction, prefix)
            if gates["rsi"]:
                funnel[f"{direction.lower()}_rsi"] += 1
            if gates["kdj"]:
                funnel[f"{direction.lower()}_kdj"] += 1
            if gates["price"]:
                funnel[f"{direction.lower()}_price"] += 1
            vix_allowed = bool(
                row["vix_long_regime_allowed_p80"] if direction == "LONG"
                else row["vix_short_regime_elevated_p50"]
            )
            full_without_vix = trend and gates["rsi"] and gates["kdj"] and gates["price"]
            core = full_without_vix and vix_allowed
            no_vix = full_without_vix
            no_kdj = trend and gates["rsi"] and gates["price"] and vix_allowed
            if core:
                funnel[f"core_{direction.lower()}_signal"] += 1
            if no_vix:
                funnel["no_vix_signal"] += 1
            if no_kdj:
                funnel["no_kdj_signal"] += 1
            if not (core or no_vix or no_kdj):
                continue
            atr_value = row.get(f"{execution_symbol.lower()}_atr_pct", np.nan)
            rows.append(
                {
                    "signal_timestamp_utc": pd.Timestamp(timestamp),
                    "signal_timestamp_et": pd.Timestamp(row["signal_timestamp_et"]),
                    "trade_date": str(row["trade_date"]),
                    "calendar_year": int(pd.Timestamp(row["signal_timestamp_et"]).year),
                    "study_period": study_period(int(pd.Timestamp(row["signal_timestamp_et"]).year)),
                    "direction": direction,
                    "selected_signal_asset": prefix.upper(),
                    "execution_symbol": execution_symbol,
                    "rsz_30": float(row["rsz_30"]),
                    "vix_prev_close": float(row["vix_prev_close"]) if np.isfinite(row["vix_prev_close"]) else np.nan,
                    "vix_pctl_252_prior": float(row["vix_pctl_252_prior"]) if np.isfinite(row["vix_pctl_252_prior"]) else np.nan,
                    "execution_atr_pct": float(atr_value) if np.isfinite(atr_value) else np.nan,
                    "core_signal": bool(core),
                    "no_vix_signal": bool(no_vix),
                    "no_kdj_signal": bool(no_kdj),
                    "rsi14": float(row[f"{prefix}_rsi14"]),
                    "kdj_k": float(row[f"{prefix}_kdj_k"]),
                    "kdj_d": float(row[f"{prefix}_kdj_d"]),
                    "kdj_j": float(row[f"{prefix}_kdj_j"]),
                    "macd_hist": float(row[f"{prefix}_macd_hist"]),
                    "signal_close": float(row[f"{prefix}_close"]),
                    "signal_vwap": float(row[f"{prefix}_vwap"]),
                }
            )
    candidates = pd.DataFrame(rows)
    if not candidates.empty:
        candidates = candidates.sort_values(
            ["signal_timestamp_utc", "execution_symbol"], kind="mergesort"
        ).drop_duplicates(
            ["signal_timestamp_utc", "direction", "execution_symbol"], keep="first"
        ).reset_index(drop=True)
    funnel_frame = pd.DataFrame([funnel])
    return candidates, funnel_frame


def candidate_mask(candidates: pd.DataFrame, variant: str) -> pd.Series:
    if variant in {"CORE_FULL", "FIXED_60M_EXIT_CONTROL"}:
        return candidates["core_signal"]
    if variant == "ABLATION_NO_VIX":
        return candidates["no_vix_signal"]
    if variant == "ABLATION_NO_KDJ":
        return candidates["no_kdj_signal"]
    raise StudyError(f"Unknown variant: {variant}")


def fill_exit_price(bar: pd.Series, trigger_price: float) -> float:
    open_price = float(bar["open"])
    return min(open_price, float(trigger_price)) if open_price < trigger_price else float(trigger_price)


def exit_invalidation_count(row: pd.Series, direction: str, prefix: str, include_kdj: bool) -> int:
    if direction == "LONG":
        conditions = [
            row[f"{prefix}_close"] < row[f"{prefix}_vwap"],
            row[f"{prefix}_macd_hist"] < 0,
            row[f"{prefix}_rsi14"] < 48.0,
            (row["qqq_ret_30m"] * row["soxx_ret_30m"] <= 0),
        ]
        if include_kdj:
            conditions.append(
                row[f"{prefix}_k_prev1"] >= row[f"{prefix}_d_prev1"]
                and row[f"{prefix}_kdj_k"] < row[f"{prefix}_kdj_d"]
            )
    else:
        conditions = [
            row[f"{prefix}_close"] > row[f"{prefix}_vwap"],
            row[f"{prefix}_macd_hist"] > 0,
            row[f"{prefix}_rsi14"] > 52.0,
            (row["qqq_ret_30m"] * row["soxx_ret_30m"] <= 0),
        ]
        if include_kdj:
            conditions.append(
                row[f"{prefix}_k_prev1"] <= row[f"{prefix}_d_prev1"]
                and row[f"{prefix}_kdj_k"] > row[f"{prefix}_kdj_d"]
            )
    return int(sum(bool(value) for value in conditions if pd.notna(value)))


def simulate_one_trade(
    candidate: Mapping[str, Any],
    minute_table: pd.DataFrame,
    aligned_day: pd.DataFrame,
    variant: str,
) -> dict[str, Any] | None:
    signal_timestamp = pd.Timestamp(candidate["signal_timestamp_utc"])
    entry_timestamp = signal_timestamp + pd.Timedelta(minutes=1)
    minute_index = minute_table.set_index("timestamp_utc", drop=False)
    if entry_timestamp not in minute_index.index:
        return None
    entry_bar = minute_index.loc[entry_timestamp]
    if isinstance(entry_bar, pd.DataFrame):
        raise StudyError("Duplicate execution entry timestamp")
    raw_entry = float(entry_bar["open"])
    if not np.isfinite(raw_entry) or raw_entry <= 0:
        return None
    atr_pct = float(candidate["execution_atr_pct"])
    if not np.isfinite(atr_pct) or atr_pct <= 0:
        return None
    stop_distance = float(np.clip(0.8 * atr_pct, MIN_STOP, MAX_STOP))
    trail_distance = float(np.clip(0.5 * atr_pct, MIN_TRAIL, MAX_TRAIL))
    weight = float(min(MAX_WEIGHT, RISK_PER_TRADE / stop_distance))
    stop_price = raw_entry * (1.0 - stop_distance)
    entry_fill = raw_entry * (1.0 + ENTRY_COST)
    high_water = raw_entry
    low_water = raw_entry
    trail_armed = False
    pending_open_exit: str | None = None
    fixed_control = variant == "FIXED_60M_EXIT_CONTROL"
    include_kdj_exit = variant != "ABLATION_NO_KDJ"
    selected_prefix = str(candidate["selected_signal_asset"]).lower()
    direction = str(candidate["direction"])
    aligned_lookup = aligned_day
    maximum_exit_timestamp = entry_timestamp + pd.Timedelta(minutes=MAX_HOLD_MINUTES)
    fixed_exit_timestamp = entry_timestamp + pd.Timedelta(minutes=FIXED_CONTROL_MINUTES)
    no_progress_check = entry_timestamp + pd.Timedelta(minutes=NO_PROGRESS_MINUTES)
    maximum_favorable = 0.0
    maximum_adverse = 0.0
    exit_timestamp = exit_et = None
    exit_raw = math.nan
    exit_reason = None

    forward = minute_table.loc[minute_table["timestamp_utc"] >= entry_timestamp].sort_values("timestamp_utc")
    for _, bar in forward.iterrows():
        timestamp = pd.Timestamp(bar["timestamp_utc"])
        minute_et = int(bar["minute_et"])
        if pending_open_exit is not None and timestamp > entry_timestamp:
            exit_timestamp = timestamp
            exit_et = pd.Timestamp(bar["timestamp_et"])
            exit_raw = float(bar["open"])
            exit_reason = pending_open_exit
            break

        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])
        high_water = max(high_water, high)
        low_water = min(low_water, low)
        maximum_favorable = max(maximum_favorable, high_water / raw_entry - 1.0)
        maximum_adverse = min(maximum_adverse, low_water / raw_entry - 1.0)

        if low <= stop_price:
            exit_timestamp = timestamp
            exit_et = pd.Timestamp(bar["timestamp_et"])
            exit_raw = fill_exit_price(bar, stop_price)
            exit_reason = "HARD_STOP"
            break

        if maximum_favorable >= TRAIL_ARM:
            trail_armed = True
        if trail_armed:
            trail_price = high_water * (1.0 - trail_distance)
            if low <= trail_price:
                exit_timestamp = timestamp
                exit_et = pd.Timestamp(bar["timestamp_et"])
                exit_raw = fill_exit_price(bar, trail_price)
                exit_reason = "TRAILING_PROTECTION"
                break

        if fixed_control and timestamp >= fixed_exit_timestamp:
            exit_timestamp = timestamp
            exit_et = pd.Timestamp(bar["timestamp_et"])
            exit_raw = close
            exit_reason = "FIXED_60M"
            break

        if not fixed_control and timestamp >= maximum_exit_timestamp:
            exit_timestamp = timestamp
            exit_et = pd.Timestamp(bar["timestamp_et"])
            exit_raw = close
            exit_reason = "MAX_120M"
            break

        if minute_et >= FORCED_EXIT_MINUTE:
            exit_timestamp = timestamp
            exit_et = pd.Timestamp(bar["timestamp_et"])
            exit_raw = close
            exit_reason = "FORCED_1555"
            break

        if not fixed_control and timestamp >= no_progress_check:
            current_return = close / raw_entry - 1.0
            if maximum_favorable < 0.003 and current_return < 0.001:
                pending_open_exit = "NO_PROGRESS_15M"

        if not fixed_control and timestamp in aligned_lookup.index:
            factor_row = aligned_lookup.loc[timestamp]
            if isinstance(factor_row, pd.DataFrame):
                factor_row = factor_row.iloc[-1]
            invalid_count = exit_invalidation_count(
                factor_row, direction, selected_prefix, include_kdj_exit
            )
            if invalid_count >= 2:
                pending_open_exit = "FACTOR_INVALIDATION"

    if exit_timestamp is None or exit_reason is None or not np.isfinite(exit_raw):
        return None
    exit_fill = exit_raw * (1.0 - EXIT_COST)
    instrument_return = exit_fill / entry_fill - 1.0
    account_return = weight * instrument_return
    holding_minutes = int((exit_timestamp - entry_timestamp) / pd.Timedelta(minutes=1))
    return {
        **dict(candidate),
        "variant": variant,
        "entry_timestamp_utc": entry_timestamp,
        "entry_timestamp_et": pd.Timestamp(entry_bar["timestamp_et"]),
        "entry_minute_et": int(entry_bar["minute_et"]),
        "entry_price_raw": raw_entry,
        "entry_price_with_cost": entry_fill,
        "exit_timestamp_utc": exit_timestamp,
        "exit_timestamp_et": exit_et,
        "exit_price_raw": exit_raw,
        "exit_price_after_cost": exit_fill,
        "exit_reason": exit_reason,
        "holding_minutes": holding_minutes,
        "stop_distance": stop_distance,
        "trail_distance": trail_distance,
        "position_weight": weight,
        "instrument_net_return": instrument_return,
        "account_trade_return": account_return,
        "mfe": maximum_favorable,
        "mae": maximum_adverse,
    }


def unconditional_60m_samples(day: pd.DataFrame) -> list[tuple[int, float]]:
    table = day.set_index("timestamp_utc", drop=False)
    rows: list[tuple[int, float]] = []
    for timestamp, bar in table.iterrows():
        minute_et = int(bar["minute_et"])
        if minute_et < SIGNAL_START + 1 or minute_et > SIGNAL_END + 1:
            continue
        exit_timestamp = pd.Timestamp(timestamp) + pd.Timedelta(minutes=60)
        if exit_timestamp not in table.index:
            continue
        exit_bar = table.loc[exit_timestamp]
        if isinstance(exit_bar, pd.DataFrame):
            continue
        if int(exit_bar["minute_et"]) > FORCED_EXIT_MINUTE:
            continue
        entry = float(bar["open"]) * (1.0 + ENTRY_COST)
        exit_value = float(exit_bar["close"]) * (1.0 - EXIT_COST)
        if entry > 0 and np.isfinite(entry) and np.isfinite(exit_value):
            rows.append((minute_et, exit_value / entry - 1.0))
    return rows


def attach_entry_alpha_60m(
    trades: list[dict[str, Any]],
    execution_day: pd.DataFrame,
    baseline: Mapping[tuple[str, int, int], RunningStats],
) -> None:
    table = execution_day.set_index("timestamp_utc", drop=False)
    for trade in trades:
        entry_timestamp = pd.Timestamp(trade["entry_timestamp_utc"])
        exit_timestamp = entry_timestamp + pd.Timedelta(minutes=60)
        key = (
            str(trade["execution_symbol"]),
            int(pd.Timestamp(trade["entry_timestamp_et"]).weekday()),
            int(trade["entry_minute_et"]),
        )
        stats = baseline.get(key, RunningStats())
        trade["pit_baseline_count_60m"] = int(stats.count)
        trade["pit_baseline_mean_60m"] = float(stats.mean) if stats.count else np.nan
        signal_return = np.nan
        if entry_timestamp in table.index and exit_timestamp in table.index:
            entry_bar = table.loc[entry_timestamp]
            exit_bar = table.loc[exit_timestamp]
            if not isinstance(entry_bar, pd.DataFrame) and not isinstance(exit_bar, pd.DataFrame):
                if int(exit_bar["minute_et"]) <= FORCED_EXIT_MINUTE:
                    entry = float(entry_bar["open"]) * (1.0 + ENTRY_COST)
                    exit_value = float(exit_bar["close"]) * (1.0 - EXIT_COST)
                    signal_return = exit_value / entry - 1.0
        trade["entry_signal_60m_net_return"] = signal_return
        eligible = stats.count >= MIN_PIT_BASELINE_COUNT and np.isfinite(signal_return)
        trade["pit_baseline_eligible_60m"] = bool(eligible)
        trade["entry_excess_pit_60m"] = (
            float(signal_return - stats.mean) if eligible else np.nan
        )


def simulate_all(
    candidates: pd.DataFrame,
    aligned: pd.DataFrame,
    canonical_index: Mapping[tuple[str, str, str], Path],
) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame()
    baseline: dict[tuple[str, int, int], RunningStats] = {}
    trade_rows: list[dict[str, Any]] = []
    months = sorted({(year, month) for _, year, month in canonical_index})
    for year, month in months:
        frames = {
            symbol: load_rth_partition(canonical_index[(symbol, year, month)])
            for symbol in EXECUTION_SYMBOLS
            if (symbol, year, month) in canonical_index
        }
        if len(frames) != len(EXECUTION_SYMBOLS):
            raise StudyError(f"Incomplete execution month {year}-{month}")
        dates = sorted(set().union(*(set(frame["trade_date"]) for frame in frames.values())))
        for trade_date in dates:
            aligned_day = aligned.loc[aligned["trade_date"] == trade_date].copy()
            day_candidates = candidates.loc[candidates["trade_date"] == trade_date]
            day_trades_by_symbol: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in EXECUTION_SYMBOLS}
            for variant in VARIANTS:
                variant_candidates = day_candidates.loc[candidate_mask(day_candidates, variant)].sort_values("signal_timestamp_utc")
                active_until = pd.Timestamp.min.tz_localize("UTC")
                cooldown_until = pd.Timestamp.min.tz_localize("UTC")
                trade_count = 0
                stop_count = 0
                daily_factor = 1.0
                for candidate in variant_candidates.to_dict(orient="records"):
                    signal_timestamp = pd.Timestamp(candidate["signal_timestamp_utc"])
                    if signal_timestamp <= active_until or signal_timestamp < cooldown_until:
                        continue
                    if trade_count >= MAX_TRADES_PER_DAY or stop_count >= MAX_STOP_EXITS_PER_DAY:
                        break
                    if daily_factor - 1.0 <= MAX_DAILY_ACCOUNT_LOSS:
                        break
                    symbol = str(candidate["execution_symbol"])
                    minute_day = frames[symbol].loc[frames[symbol]["trade_date"] == trade_date]
                    trade = simulate_one_trade(candidate, minute_day, aligned_day, variant)
                    if trade is None:
                        continue
                    trade_count += 1
                    daily_factor *= 1.0 + float(trade["account_trade_return"])
                    if trade["exit_reason"] == "HARD_STOP":
                        stop_count += 1
                    active_until = pd.Timestamp(trade["exit_timestamp_utc"])
                    cooldown_until = active_until + pd.Timedelta(minutes=COOLDOWN_MINUTES)
                    day_trades_by_symbol[symbol].append(trade)
                    trade_rows.append(trade)

            for symbol in EXECUTION_SYMBOLS:
                minute_day = frames[symbol].loc[frames[symbol]["trade_date"] == trade_date]
                attach_entry_alpha_60m(day_trades_by_symbol[symbol], minute_day, baseline)
            weekday = pd.Timestamp(trade_date).weekday()
            for symbol in EXECUTION_SYMBOLS:
                minute_day = frames[symbol].loc[frames[symbol]["trade_date"] == trade_date]
                for minute_et, value in unconditional_60m_samples(minute_day):
                    baseline.setdefault((symbol, weekday, minute_et), RunningStats()).add(value)
    trades = pd.DataFrame(trade_rows)
    if not trades.empty:
        trades = trades.sort_values(
            ["variant", "entry_timestamp_utc", "execution_symbol"], kind="mergesort"
        ).reset_index(drop=True)
    return trades


def profit_factor(values: pd.Series) -> float:
    positive = values.loc[values > 0].sum()
    negative = values.loc[values < 0].sum()
    if negative == 0:
        return math.inf if positive > 0 else math.nan
    return float(positive / abs(negative))


def max_drawdown(returns: pd.Series) -> float:
    nav = (1.0 + returns.fillna(0.0)).cumprod()
    return float((nav / nav.cummax() - 1.0).min()) if len(nav) else math.nan


def block_bootstrap_mean_ci(values: pd.Series, block: int = 5) -> tuple[float, float]:
    clean = values.dropna().to_numpy(dtype=float)
    if len(clean) < 20:
        return math.nan, math.nan
    rng = np.random.default_rng(MASTER_SEED + len(clean))
    means = np.empty(BOOTSTRAP_REPS, dtype=float)
    blocks_needed = math.ceil(len(clean) / block)
    maximum_start = max(1, len(clean) - block + 1)
    for repetition in range(BOOTSTRAP_REPS):
        starts = rng.integers(0, maximum_start, size=blocks_needed)
        sampled = np.concatenate([clean[start:start + block] for start in starts])[: len(clean)]
        means[repetition] = sampled.mean()
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def build_daily_nav(trades: pd.DataFrame, trading_dates: list[str]) -> pd.DataFrame:
    rows = []
    for variant in VARIANTS:
        nav = 1.0
        subset = trades.loc[trades["variant"] == variant] if not trades.empty else pd.DataFrame()
        by_date = {
            date: group for date, group in subset.groupby("trade_date", sort=True)
        } if not subset.empty else {}
        for trade_date in trading_dates:
            group = by_date.get(trade_date)
            daily_return = 0.0 if group is None else float(
                np.prod(1.0 + group["account_trade_return"].to_numpy(dtype=float)) - 1.0
            )
            nav *= 1.0 + daily_return
            rows.append(
                {
                    "variant": variant,
                    "trade_date": trade_date,
                    "calendar_year": int(trade_date[:4]),
                    "study_period": study_period(int(trade_date[:4])),
                    "trade_count": 0 if group is None else int(len(group)),
                    "daily_return": daily_return,
                    "nav": nav,
                }
            )
    result = pd.DataFrame(rows)
    result["drawdown"] = result.groupby("variant", sort=False)["nav"].transform(
        lambda values: values / values.cummax() - 1.0
    )
    return result


def summarize_periods(trades: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for variant in VARIANTS:
        for period in PERIOD_ORDER:
            tg = trades.loc[(trades["variant"] == variant) & (trades["study_period"] == period)] if not trades.empty else pd.DataFrame()
            dg = daily.loc[(daily["variant"] == variant) & (daily["study_period"] == period)].copy()
            if dg.empty:
                continue
            daily_values = dg["daily_return"]
            cumulative = float(np.prod(1.0 + daily_values.to_numpy(dtype=float)) - 1.0)
            years = max(len(dg) / 252.0, 1.0 / 252.0)
            annualized = float((1.0 + cumulative) ** (1.0 / years) - 1.0) if cumulative > -1 else -1.0
            std = float(daily_values.std(ddof=0))
            sharpe = float(daily_values.mean() / std * math.sqrt(252.0)) if std > 0 else math.nan
            mdd = max_drawdown(daily_values)
            calmar = float(annualized / abs(mdd)) if mdd < 0 else math.nan
            eligible = tg.loc[tg["pit_baseline_eligible_60m"] == True] if not tg.empty else pd.DataFrame()
            ci_low, ci_high = block_bootstrap_mean_ci(daily_values)
            rows.append(
                {
                    "variant": variant,
                    "study_period": period,
                    "trade_count": int(len(tg)),
                    "trade_day_count": int((dg["trade_count"] > 0).sum()),
                    "mean_instrument_net_return": float(tg["instrument_net_return"].mean()) if len(tg) else np.nan,
                    "median_instrument_net_return": float(tg["instrument_net_return"].median()) if len(tg) else np.nan,
                    "positive_rate": float((tg["instrument_net_return"] > 0).mean()) if len(tg) else np.nan,
                    "profit_factor": profit_factor(tg["account_trade_return"]) if len(tg) else np.nan,
                    "mean_position_weight": float(tg["position_weight"].mean()) if len(tg) else np.nan,
                    "mean_holding_minutes": float(tg["holding_minutes"].mean()) if len(tg) else np.nan,
                    "mean_mfe": float(tg["mfe"].mean()) if len(tg) else np.nan,
                    "mean_mae": float(tg["mae"].mean()) if len(tg) else np.nan,
                    "pit_eligible_trade_count_60m": int(len(eligible)),
                    "mean_entry_excess_pit_60m": float(eligible["entry_excess_pit_60m"].mean()) if len(eligible) else np.nan,
                    "cumulative_return": cumulative,
                    "annualized_return": annualized,
                    "sharpe": sharpe,
                    "max_drawdown": mdd,
                    "calmar": calmar,
                    "daily_mean_ci95_lower": ci_low,
                    "daily_mean_ci95_upper": ci_high,
                }
            )
    result = pd.DataFrame(rows)
    if not result.empty:
        result["period_order"] = result["study_period"].map(PERIOD_ORDER)
        result = result.sort_values(["variant", "period_order"]).drop(columns="period_order")
    return result


def summarize_years(trades: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (variant, year), dg in daily.groupby(["variant", "calendar_year"], sort=True):
        if study_period(int(year)) == "OUTSIDE_STUDY":
            continue
        tg = trades.loc[(trades["variant"] == variant) & (trades["calendar_year"] == year)] if not trades.empty else pd.DataFrame()
        cumulative = float(np.prod(1.0 + dg["daily_return"].to_numpy(dtype=float)) - 1.0)
        rows.append(
            {
                "variant": variant,
                "calendar_year": int(year),
                "trade_count": int(len(tg)),
                "cumulative_return": cumulative,
                "max_drawdown": max_drawdown(dg["daily_return"]),
                "mean_instrument_net_return": float(tg["instrument_net_return"].mean()) if len(tg) else np.nan,
                "median_instrument_net_return": float(tg["instrument_net_return"].median()) if len(tg) else np.nan,
                "positive_rate": float((tg["instrument_net_return"] > 0).mean()) if len(tg) else np.nan,
                "profit_factor": profit_factor(tg["account_trade_return"]) if len(tg) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def exit_reason_summary(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    return (
        trades.groupby(["variant", "exit_reason"], sort=True)
        .agg(
            trade_count=("exit_reason", "size"),
            mean_instrument_net_return=("instrument_net_return", "mean"),
            median_instrument_net_return=("instrument_net_return", "median"),
            positive_rate=("instrument_net_return", lambda values: float((values > 0).mean())),
            mean_holding_minutes=("holding_minutes", "mean"),
        )
        .reset_index()
    )


def direction_symbol_summary(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    return (
        trades.groupby(["variant", "direction", "execution_symbol", "study_period"], sort=True)
        .agg(
            trade_count=("instrument_net_return", "size"),
            mean_net_return=("instrument_net_return", "mean"),
            median_net_return=("instrument_net_return", "median"),
            positive_rate=("instrument_net_return", lambda values: float((values > 0).mean())),
            profit_factor=("account_trade_return", profit_factor),
        )
        .reset_index()
    )


def single_year_profit_share(year: pd.DataFrame, variant: str) -> float:
    values = year.loc[year["variant"] == variant, "cumulative_return"]
    positive = values.loc[values > 0]
    return float(positive.max() / positive.sum()) if len(positive) and positive.sum() > 0 else math.nan


def qualification(period: pd.DataFrame, year: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for variant in VARIANTS:
        validation = period.loc[(period["variant"] == variant) & (period["study_period"] == "2023-2024_VALIDATION")]
        confirmation = period.loc[(period["variant"] == variant) & (period["study_period"] == "2025-2026_YTD_CONFIRMATION")]
        if validation.empty or confirmation.empty:
            continue
        validation = validation.iloc[0]
        confirmation = confirmation.iloc[0]
        share = single_year_profit_share(year, variant)
        rows.append(
            {
                "variant": variant,
                "validation_directional_pass": bool(
                    validation["mean_instrument_net_return"] > 0
                    and validation["median_instrument_net_return"] > 0
                    and validation["profit_factor"] > 1.10
                    and validation["mean_entry_excess_pit_60m"] > 0
                ),
                "confirmation_directional_pass": bool(
                    confirmation["mean_instrument_net_return"] > 0
                    and confirmation["median_instrument_net_return"] > 0
                    and confirmation["profit_factor"] > 1.10
                    and confirmation["mean_entry_excess_pit_60m"] > 0
                ),
                "confirmation_trade_count_pass": bool(confirmation["trade_count"] >= 100),
                "confirmation_drawdown_pass": bool(confirmation["max_drawdown"] > -0.15),
                "single_year_profit_share": share,
                "single_year_concentration_pass": bool(np.isfinite(share) and share <= 0.60),
            }
        )
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    fixed_validation = period.loc[(period["variant"] == "FIXED_60M_EXIT_CONTROL") & (period["study_period"] == "2023-2024_VALIDATION"), "cumulative_return"]
    fixed_confirmation = period.loc[(period["variant"] == "FIXED_60M_EXIT_CONTROL") & (period["study_period"] == "2025-2026_YTD_CONFIRMATION"), "cumulative_return"]
    fixed_v = float(fixed_validation.iloc[0]) if len(fixed_validation) else np.nan
    fixed_c = float(fixed_confirmation.iloc[0]) if len(fixed_confirmation) else np.nan
    for index, row in result.iterrows():
        variant = row["variant"]
        current_v = period.loc[(period["variant"] == variant) & (period["study_period"] == "2023-2024_VALIDATION"), "cumulative_return"]
        current_c = period.loc[(period["variant"] == variant) & (period["study_period"] == "2025-2026_YTD_CONFIRMATION"), "cumulative_return"]
        exit_pass = True if variant == "FIXED_60M_EXIT_CONTROL" else bool(
            len(current_v) and len(current_c) and np.isfinite(fixed_v) and np.isfinite(fixed_c)
            and float(current_v.iloc[0]) > fixed_v and float(current_c.iloc[0]) > fixed_c
        )
        result.loc[index, "dynamic_exit_beats_fixed_control"] = exit_pass
        result.loc[index, "candidate_qualified"] = bool(
            row["validation_directional_pass"]
            and row["confirmation_directional_pass"]
            and row["confirmation_trade_count_pass"]
            and row["confirmation_drawdown_pass"]
            and row["single_year_concentration_pass"]
            and exit_pass
        )
    return result


def run_study(
    v22_056_summary_path: Path,
    vix_feature_path: Path,
    canonical_root: Path,
    result_dir: Path,
) -> dict[str, Any]:
    if not v22_056_summary_path.exists():
        raise StudyError(f"V22.056 summary not found: {v22_056_summary_path}")
    v22_056 = json.loads(v22_056_summary_path.read_text(encoding="utf-8-sig"))
    validate_v22_056(v22_056)
    canonical_index = index_canonical(canonical_root)
    factor_tables = build_all_factor_tables(canonical_index)
    aligned = build_aligned_factors(factor_tables)
    vix = load_vix_features(vix_feature_path)
    candidates, funnel = build_candidates(aligned, vix)
    trades = simulate_all(candidates, aligned, canonical_index)
    trading_dates = sorted(
        date for date in factor_tables["QQQ"]["trade_date"].unique()
        if study_period(int(str(date)[:4])) != "OUTSIDE_STUDY"
    )
    daily = build_daily_nav(trades, trading_dates)
    period = summarize_periods(trades, daily)
    year = summarize_years(trades, daily)
    exits = exit_reason_summary(trades)
    direction = direction_symbol_summary(trades)
    qualified = qualification(period, year)
    core_qualified = bool(
        not qualified.empty
        and qualified.loc[qualified["variant"] == "CORE_FULL", "candidate_qualified"].fillna(False).any()
    )
    final_decision = (
        "MULTIFACT_CORE_QUALIFIED_FOR_INDEPENDENT_REPLICATION"
        if core_qualified
        else "NO_MULTIFACT_CORE_CANDIDATE_QUALIFIED"
    )

    result_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "candidates_csv": result_dir / "v22_057_signal_candidates.csv",
        "trades_csv": result_dir / "v22_057_trades.csv",
        "trades_parquet": result_dir / "v22_057_trades.parquet",
        "daily_nav": result_dir / "v22_057_daily_nav.csv",
        "period_summary": result_dir / "v22_057_period_summary.csv",
        "year_summary": result_dir / "v22_057_year_summary.csv",
        "exit_summary": result_dir / "v22_057_exit_reason_summary.csv",
        "direction_summary": result_dir / "v22_057_direction_symbol_summary.csv",
        "qualification": result_dir / "v22_057_qualification_table.csv",
        "signal_funnel": result_dir / "v22_057_signal_funnel.csv",
        "summary": result_dir / "v22_057_summary.json",
        "manifest": result_dir / "v22_057_run_manifest.json",
    }
    candidates.to_csv(outputs["candidates_csv"], index=False, encoding="utf-8-sig")
    trades.to_csv(outputs["trades_csv"], index=False, encoding="utf-8-sig")
    trades.to_parquet(outputs["trades_parquet"], index=False)
    daily.to_csv(outputs["daily_nav"], index=False, encoding="utf-8-sig")
    period.to_csv(outputs["period_summary"], index=False, encoding="utf-8-sig")
    year.to_csv(outputs["year_summary"], index=False, encoding="utf-8-sig")
    exits.to_csv(outputs["exit_summary"], index=False, encoding="utf-8-sig")
    direction.to_csv(outputs["direction_summary"], index=False, encoding="utf-8-sig")
    qualified.to_csv(outputs["qualification"], index=False, encoding="utf-8-sig")
    funnel.to_csv(outputs["signal_funnel"], index=False, encoding="utf-8-sig")

    summary = {
        "version": VERSION,
        "final_status": "PASS",
        "final_decision": final_decision,
        "v22_056_validated": True,
        "vix_mode": "PRIOR_DAY_OFFICIAL_CBOE_ONLY",
        "intraday_vix_used": False,
        "vix_proxy_used": False,
        "canonical_partition_count_read": int(len(canonical_index)),
        "factor_5m_bar_count_by_symbol": {
            symbol: int(len(frame)) for symbol, frame in factor_tables.items()
        },
        "signal_candidate_count": int(len(candidates)),
        "trade_count": int(len(trades)),
        "trade_count_by_variant": {
            variant: int((trades["variant"] == variant).sum()) if not trades.empty else 0
            for variant in VARIANTS
        },
        "core_qualified_for_replication": core_qualified,
        "parameter_sweep_executed": False,
        "entry_threshold_optimization_executed": False,
        "exit_threshold_optimization_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "open_d_called": False,
        "history_download_executed": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
        "v22_056_summary_sha256": sha256_file(v22_056_summary_path),
        "outputs": {key: str(value) for key, value in outputs.items()},
    }
    atomic_json(outputs["summary"], summary)
    manifest = {
        "version": VERSION,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inputs": {
            "v22_056_summary": str(v22_056_summary_path),
            "vix_feature_path": str(vix_feature_path),
            "canonical_root": str(canonical_root),
        },
        "frozen_parameters": {
            "signal_start_minute_et": SIGNAL_START,
            "signal_end_minute_et": SIGNAL_END,
            "rsz_threshold": RSZ_THRESHOLD,
            "risk_per_trade": RISK_PER_TRADE,
            "max_weight": MAX_WEIGHT,
            "stop_range": [MIN_STOP, MAX_STOP],
            "trail_arm": TRAIL_ARM,
            "trail_range": [MIN_TRAIL, MAX_TRAIL],
            "max_hold_minutes": MAX_HOLD_MINUTES,
            "round_trip_cost_approx_bps": 10,
        },
        "guards": {
            "parameter_sweep_executed": False,
            "canonical_files_modified": False,
            "raw_files_modified": False,
            "open_d_called": False,
            "history_download_executed": False,
            "broker_action_allowed": False,
            "paper_trading_allowed": False,
            "official_adoption_allowed": False,
        },
    }
    atomic_json(outputs["manifest"], manifest)
    return {"summary": summary, "outputs": outputs, "result_dir": result_dir}


def print_final(result: Mapping[str, Any]) -> None:
    summary = result["summary"]
    print(f"FINAL_STATUS={summary['final_status']}")
    print(f"FINAL_DECISION={summary['final_decision']}")
    print("V22_056_VALIDATED=True")
    print("VIX_MODE=PRIOR_DAY_OFFICIAL_CBOE_ONLY")
    print("INTRADAY_VIX_USED=False")
    print("VIX_PROXY_USED=False")
    print(f"CANONICAL_PARTITION_COUNT_READ={summary['canonical_partition_count_read']}")
    print(f"SIGNAL_CANDIDATE_COUNT={summary['signal_candidate_count']}")
    print(f"TRADE_COUNT={summary['trade_count']}")
    for variant, count in summary["trade_count_by_variant"].items():
        print(f"TRADE_COUNT_{variant}={count}")
    print(f"CORE_QUALIFIED_FOR_REPLICATION={summary['core_qualified_for_replication']}")
    print("PARAMETER_SWEEP_EXECUTED=False")
    print("ENTRY_THRESHOLD_OPTIMIZATION_EXECUTED=False")
    print("EXIT_THRESHOLD_OPTIMIZATION_EXECUTED=False")
    print("CANONICAL_FILES_MODIFIED=False")
    print("RAW_FILES_MODIFIED=False")
    print("OPEN_D_CALLED=False")
    print("HISTORY_DOWNLOAD_EXECUTED=False")
    print("BROKER_ACTION_ALLOWED=False")
    print("PAPER_TRADING_ALLOWED=False")
    print("OFFICIAL_ADOPTION_ALLOWED=False")
    print(f"SUMMARY_PATH={result['outputs']['summary']}")
    print(f"RESULT_DIRECTORY={result['result_dir']}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--v22-056-summary",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.056_FAST3_CBOE_DAILY_VIX_INGEST_AND_PIT_REGIME_R1"
            r"\v22_056_summary.json"
        ),
    )
    parser.add_argument(
        "--vix-feature-path",
        default=(
            r"D:\us-tech-quant-data\fast3\vix_cboe_daily\features"
            r"\vix_prior_day_regime_features.parquet"
        ),
    )
    parser.add_argument(
        "--canonical-root",
        default=r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical",
    )
    parser.add_argument(
        "--result-dir",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.057_FAST3_MULTIFACT_STATE_MACHINE_BACKTEST_R1"
        ),
    )
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.execute:
        print("FINAL_STATUS=BLOCKED_EXECUTE_FLAG_REQUIRED")
        return 2
    try:
        result = run_study(
            v22_056_summary_path=Path(args.v22_056_summary),
            vix_feature_path=Path(args.vix_feature_path),
            canonical_root=Path(args.canonical_root),
            result_dir=Path(args.result_dir),
        )
        print_final(result)
        return 0
    except Exception as exc:
        print("FINAL_STATUS=FAIL")
        print(f"ERROR_TYPE={type(exc).__name__}")
        print(f"ERROR={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
