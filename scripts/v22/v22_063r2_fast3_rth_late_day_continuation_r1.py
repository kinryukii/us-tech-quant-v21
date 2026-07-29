#!/usr/bin/env python
r"""
V22.063R2 FAST3 RTH late-day continuation baseline R1.

Frozen design
-------------
RTH session: 09:30-15:59 ET.
Warm-up: 09:30-13:29.
Signal window: 13:30-14:54.
Maximum one trade per RTH date.
Entry: exact next-minute open.

LONG:
- QQQ and SOXX are both above cumulative RTH typical-price VWAP;
- both exact 60-minute returns are positive;
- both exact 15-minute returns are positive;
- both closes are above their previous 15-minute rolling highs;
- both pass the frozen OHLCV tradability proxy.

SHORT: exact inverse.

The synchronized state must transition from false to true.

Execution selection
-------------------
Normalized 60-minute momentum =
exact 60-minute return / trailing 120-minute realized one-minute volatility.

LONG:
- stronger normalized SOXX -> SOXL;
- otherwise TQQQ.

SHORT:
- weaker normalized SOXX -> SOXS;
- otherwise SQQQ.

Exits
-----
- FIXED_30M
- FIXED_60M
- SESSION_1555

Costs and sizing
----------------
- 5 bps per side.
- 20% fixed account weight.

Corporate-action safety
-----------------------
Only frozen split/reverse-split factors are recognized.
Any recognized or unresolved price-scale event inside the signal/holding
interval quarantines the affected session.

No parameter sweep, no signal-window sweep, no momentum-threshold sweep,
no exit optimization, no RSI/MACD/KDJ/VIX gate, no data download, and no
RAW/Canonical mutation.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


VERSION = "V22.063R2_FAST3_RTH_LATE_DAY_CONTINUATION_BASELINE_R1"

SIGNAL_SYMBOLS = ("QQQ", "SOXX")
EXECUTION_SYMBOLS = ("TQQQ", "SOXL", "SQQQ", "SOXS")
ALL_SYMBOLS = SIGNAL_SYMBOLS + EXECUTION_SYMBOLS
EXIT_VARIANTS = ("FIXED_30M", "FIXED_60M", "SESSION_1555")

RTH_START_ET = 9 * 60 + 30
RTH_END_ET = 15 * 60 + 59
RTH_LENGTH = 390

SIGNAL_START = 240   # 13:30 ET
SIGNAL_END = 324     # 14:54 ET
SESSION_EXIT_MINUTE = 385  # 15:55 ET

RECENT_WINDOW = 60
RECENT_MIN_OBSERVED = 45
RECENT_MIN_POSITIVE_VOLUME = 40
RECENT_MIN_CLOSE_CHANGES = 20
VOL_WINDOW = 120
VOL_MIN_RETURNS = 60

ENTRY_COST = 0.0005
EXIT_COST = 0.0005
FIXED_ACCOUNT_WEIGHT = 0.20

JUMP_THRESHOLD = 0.20
FACTOR_TOLERANCE = 0.03
ALLOWED_SPLIT_FACTORS = (
    2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0,
    15.0, 20.0, 25.0, 30.0, 40.0, 50.0, 100.0,
)

MIN_FULL_HISTORY_TRADES = 100
MIN_VALIDATION_TRADES = 30
MIN_CONFIRMATION_TRADES = 30
MAX_TOP1_SHARE = 0.50
MAX_TOP5_SHARE = 0.80
MAX_POSITIVE_YEAR_SHARE = 0.60

PERIODS = (
    "2018-2022_DEVELOPMENT",
    "2023-2024_VALIDATION",
    "2025-2026_YTD_CONFIRMATION",
)
PERIOD_ORDER = {period: index for index, period in enumerate(PERIODS)}


class StudyError(RuntimeError):
    pass


def study_period(year: int) -> str:
    if 2018 <= year <= 2022:
        return "2018-2022_DEVELOPMENT"
    if 2023 <= year <= 2024:
        return "2023-2024_VALIDATION"
    if 2025 <= year <= 2026:
        return "2025-2026_YTD_CONFIRMATION"
    return "OUTSIDE_STUDY"


def validate_lineage(
    rth_mean_reversion: Mapping[str, Any],
    after_hours: Mapping[str, Any],
    forward: Mapping[str, Any],
) -> None:
    checks = [
        (
            rth_mean_reversion,
            {
                "final_status": "PASS",
                "final_decision": (
                    "NO_RTH_VWAP_MEAN_REVERSION_CANDIDATE_QUALIFIED"
                ),
                "v22_062pr_validated": True,
                "premarket_forward_chain_modified": False,
                "parameter_sweep_executed": False,
                "canonical_files_modified": False,
                "raw_files_modified": False,
                "broker_action_allowed": False,
                "paper_trading_allowed": False,
                "official_adoption_allowed": False,
            },
            "V22.063R1",
        ),
        (
            after_hours,
            {
                "final_status": "PASS",
                "final_decision": (
                    "NO_AFTER_HOURS_CLOSE_CONTINUATION_CANDIDATE_QUALIFIED"
                ),
                "v22_062pr_validated": True,
                "premarket_forward_chain_modified": False,
                "parameter_sweep_executed": False,
                "canonical_files_modified": False,
                "raw_files_modified": False,
                "broker_action_allowed": False,
                "paper_trading_allowed": False,
                "official_adoption_allowed": False,
            },
            "V22.063A",
        ),
        (
            forward,
            {
                "final_status": "PASS",
                "v22_062pb_validated": True,
                "research_cutoff_date": "2026-07-24",
                "forward_holdout_only": True,
                "rule_change_requires_reset": True,
                "sole_exit_variant": "PREMARKET_0925",
                "historical_pre_cutoff_outcomes_used_for_qualification": False,
                "parameter_sweep_executed": False,
                "canonical_files_modified": False,
                "raw_files_modified": False,
                "broker_action_allowed": False,
                "paper_trading_allowed": False,
                "official_adoption_allowed": False,
            },
            "V22.062PR",
        ),
    ]
    failures: list[str] = []
    for summary, expected, name in checks:
        for key, value in expected.items():
            if summary.get(key) != value:
                failures.append(
                    f"{name}.{key}: expected {value!r}, "
                    f"got {summary.get(key)!r}"
                )
    if failures:
        raise StudyError("Lineage validation failed: " + "; ".join(failures))


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
        raise StudyError(f"Cannot parse Canonical path: {path}")
    return symbol, year, month


def index_canonical(
    root: Path,
) -> dict[tuple[str, str, str], Path]:
    result: dict[tuple[str, str, str], Path] = {}
    for path in sorted(root.rglob("*.parquet")):
        key = symbol_month_from_path(path)
        if key[0] not in ALL_SYMBOLS:
            continue
        if key in result:
            raise StudyError(f"Duplicate Canonical partition: {key}")
        result[key] = path

    counts = {
        symbol: sum(1 for current, _, _ in result if current == symbol)
        for symbol in ALL_SYMBOLS
    }
    if any(value == 0 for value in counts.values()):
        raise StudyError(f"Missing Canonical symbol: {counts}")
    if len(set(counts.values())) != 1 or len(result) != 582:
        raise StudyError(
            f"Expected balanced 582 partitions; got {len(result)}, {counts}"
        )
    return result


def find_column(frame: pd.DataFrame, aliases: Iterable[str]) -> str:
    mapping = {
        str(column).strip().lower(): str(column)
        for column in frame.columns
    }
    for alias in aliases:
        if alias.lower() in mapping:
            return mapping[alias.lower()]
    raise StudyError(f"Missing column from aliases={tuple(aliases)}")


def load_symbol_rth(
    symbol: str,
    canonical: Mapping[tuple[str, str, str], Path],
) -> tuple[pd.DataFrame, list[str]]:
    frames: list[pd.DataFrame] = []
    paths_read: list[str] = []

    for (current, _, _), path in sorted(canonical.items()):
        if current != symbol:
            continue
        raw = pd.read_parquet(path)
        paths_read.append(str(path))
        if raw.empty:
            continue

        timestamp = pd.to_datetime(
            raw[find_column(raw, ("timestamp_utc",))],
            errors="raise",
            utc=True,
        )
        local = timestamp.dt.tz_convert("America/New_York")
        minute_et = local.dt.hour * 60 + local.dt.minute
        mask = (minute_et >= RTH_START_ET) & (minute_et <= RTH_END_ET)

        frame = pd.DataFrame(
            {
                "timestamp_utc": timestamp.loc[mask],
                "trade_date": local.loc[mask].dt.strftime("%Y-%m-%d"),
                "session_minute": (
                    minute_et.loc[mask] - RTH_START_ET
                ).astype(int),
                "open": pd.to_numeric(
                    raw.loc[mask, find_column(raw, ("open",))],
                    errors="coerce",
                ),
                "high": pd.to_numeric(
                    raw.loc[mask, find_column(raw, ("high",))],
                    errors="coerce",
                ),
                "low": pd.to_numeric(
                    raw.loc[mask, find_column(raw, ("low",))],
                    errors="coerce",
                ),
                "close": pd.to_numeric(
                    raw.loc[mask, find_column(raw, ("close",))],
                    errors="coerce",
                ),
                "volume": pd.to_numeric(
                    raw.loc[mask, find_column(raw, ("volume",))],
                    errors="coerce",
                ).fillna(0.0),
            }
        ).dropna(
            subset=["timestamp_utc", "open", "high", "low", "close"]
        )
        frames.append(frame)

    if not frames:
        return pd.DataFrame(), paths_read

    combined = (
        pd.concat(frames, ignore_index=True)
        .sort_values("timestamp_utc", kind="mergesort")
        .drop_duplicates("timestamp_utc", keep="last")
        .reset_index(drop=True)
    )
    if combined.duplicated(["trade_date", "session_minute"]).any():
        raise StudyError(f"Duplicate RTH session minute for {symbol}")
    if (
        (combined["low"] > combined["high"]).any()
        or (combined["close"] < combined["low"]).any()
        or (combined["close"] > combined["high"]).any()
    ):
        raise StudyError(f"Invalid OHLC for {symbol}")
    return combined, paths_read


def split_candidates() -> np.ndarray:
    values = set(ALLOWED_SPLIT_FACTORS)
    values.update(1.0 / value for value in ALLOWED_SPLIT_FACTORS)
    return np.array(sorted(values), dtype=float)


def snap_split_factor(
    raw_ratio: float,
) -> tuple[float, float] | None:
    if not np.isfinite(raw_ratio) or raw_ratio <= 0:
        return None
    factors = split_candidates()
    errors = np.abs(factors / raw_ratio - 1.0)
    index = int(np.argmin(errors))
    if float(errors[index]) <= FACTOR_TOLERANCE:
        return float(factors[index]), float(errors[index])
    return None


def normalize_scale_series(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if frame.empty:
        return frame.copy(), pd.DataFrame(), pd.DataFrame()

    result = frame.sort_values(
        "timestamp_utc",
        kind="mergesort",
    ).reset_index(drop=True).copy()

    multiplier = 1.0
    multipliers: list[float] = []
    recognized: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    previous_close: float | None = None
    previous_timestamp: pd.Timestamp | None = None

    for _, row in result.iterrows():
        timestamp = pd.Timestamp(row["timestamp_utc"])
        current_open = float(row["open"])
        if (
            previous_close is not None
            and previous_close > 0
            and current_open > 0
        ):
            change = current_open / previous_close - 1.0
            if abs(change) >= JUMP_THRESHOLD:
                ratio = previous_close / current_open
                snapped = snap_split_factor(ratio)
                record = {
                    "timestamp_utc": timestamp,
                    "previous_timestamp_utc": previous_timestamp,
                    "raw_change": change,
                    "raw_ratio": ratio,
                }
                if snapped is None:
                    unresolved.append(record)
                else:
                    factor, error = snapped
                    multiplier *= factor
                    recognized.append(
                        {
                            **record,
                            "recognized_factor": factor,
                            "relative_error": error,
                        }
                    )
        multipliers.append(multiplier)
        previous_close = float(row["close"])
        previous_timestamp = timestamp

    result["scale_multiplier"] = multipliers
    for column in ("open", "high", "low", "close"):
        result[f"normalized_{column}"] = (
            result[column] * result["scale_multiplier"]
        )
    return result, pd.DataFrame(recognized), pd.DataFrame(unresolved)


def get_day(frame: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    return (
        frame.loc[frame["trade_date"] == trade_date]
        .sort_values("session_minute", kind="mergesort")
        .reset_index(drop=True)
    )


def session_grid(day: pd.DataFrame) -> pd.DataFrame:
    grid = pd.DataFrame(index=pd.RangeIndex(RTH_LENGTH))
    grid.index.name = "session_minute"

    if day.empty:
        for column in (
            "timestamp_utc",
            "normalized_open",
            "normalized_high",
            "normalized_low",
            "normalized_close",
            "volume",
        ):
            grid[column] = np.nan
        grid["observed"] = False
        grid["session_complete"] = False
        return grid

    indexed = (
        day.sort_values("session_minute", kind="mergesort")
        .drop_duplicates("session_minute", keep="last")
        .set_index("session_minute")
    )
    grid = grid.join(
        indexed[
            [
                "timestamp_utc",
                "normalized_open",
                "normalized_high",
                "normalized_low",
                "normalized_close",
                "volume",
            ]
        ],
        how="left",
    )

    grid["observed"] = grid["normalized_close"].notna()
    grid["session_complete"] = bool(grid["observed"].sum() == RTH_LENGTH)
    grid["positive_volume"] = grid["volume"].fillna(0.0) > 0

    typical = (
        grid["normalized_high"]
        + grid["normalized_low"]
        + grid["normalized_close"]
    ) / 3.0
    volume = grid["volume"].fillna(0.0).clip(lower=0.0)
    cumulative_volume = volume.cumsum()
    cumulative_value = (typical.fillna(0.0) * volume).cumsum()
    fallback = grid["normalized_close"].expanding().mean()
    grid["vwap"] = cumulative_value.divide(
        cumulative_volume.where(cumulative_volume > 0)
    ).fillna(fallback)

    grid["ret_1m"] = grid["normalized_close"].pct_change(fill_method=None)
    grid["ret_15m"] = (
        grid["normalized_close"]
        / grid["normalized_close"].shift(15)
        - 1.0
    )
    grid["ret_60m"] = (
        grid["normalized_close"]
        / grid["normalized_close"].shift(60)
        - 1.0
    )
    grid["realized_vol_120m"] = (
        grid["ret_1m"]
        .rolling(VOL_WINDOW, min_periods=VOL_MIN_RETURNS)
        .std(ddof=1)
        * math.sqrt(60.0)
    )
    grid["normalized_momentum_60m"] = (
        grid["ret_60m"]
        / grid["realized_vol_120m"].replace(0.0, np.nan)
    )
    grid["prior_15m_high"] = (
        grid["normalized_high"]
        .shift(1)
        .rolling(15, min_periods=15)
        .max()
    )
    grid["prior_15m_low"] = (
        grid["normalized_low"]
        .shift(1)
        .rolling(15, min_periods=15)
        .min()
    )

    grid["recent_observed_count"] = (
        grid["observed"].rolling(RECENT_WINDOW, min_periods=1).sum()
    )
    grid["recent_positive_volume_count"] = (
        grid["positive_volume"]
        .rolling(RECENT_WINDOW, min_periods=1)
        .sum()
    )
    close_change = (
        grid["normalized_close"].diff().abs().gt(0)
        & grid["normalized_close"].notna()
        & grid["normalized_close"].shift(1).notna()
    )
    grid["recent_close_change_count"] = (
        close_change.rolling(RECENT_WINDOW, min_periods=1).sum()
    )

    grid["tradability_proxy_pass"] = (
        grid["observed"]
        & grid["normalized_close"].shift(60).notna()
        & (
            grid["recent_observed_count"]
            >= RECENT_MIN_OBSERVED
        )
        & (
            grid["recent_positive_volume_count"]
            >= RECENT_MIN_POSITIVE_VOLUME
        )
        & (
            grid["recent_close_change_count"]
            >= RECENT_MIN_CLOSE_CHANGES
        )
        & grid["normalized_momentum_60m"].notna()
    )
    return grid


def event_in_window(
    events: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> bool:
    if events.empty:
        return False
    timestamps = pd.to_datetime(events["timestamp_utc"], utc=True)
    return bool(((timestamps >= start) & (timestamps <= end)).any())


def build_candidate(
    trade_date: str,
    qqq: pd.DataFrame,
    soxx: pd.DataFrame,
    recognized: Mapping[str, pd.DataFrame],
    unresolved: Mapping[str, pd.DataFrame],
) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    if not bool(qqq["session_complete"].iloc[0]):
        reasons.append("QQQ_INCOMPLETE_RTH")
    if not bool(soxx["session_complete"].iloc[0]):
        reasons.append("SOXX_INCOMPLETE_RTH")
    if reasons:
        return None, reasons

    signal_start_ts = pd.Timestamp(
        f"{trade_date} 13:30",
        tz="America/New_York",
    ).tz_convert("UTC")
    signal_end_ts = pd.Timestamp(
        f"{trade_date} 14:54",
        tz="America/New_York",
    ).tz_convert("UTC")

    for symbol in SIGNAL_SYMBOLS:
        if event_in_window(
            recognized[symbol], signal_start_ts, signal_end_ts
        ):
            reasons.append(f"{symbol}_RECOGNIZED_SCALE_EVENT")
        if event_in_window(
            unresolved[symbol], signal_start_ts, signal_end_ts
        ):
            reasons.append(f"{symbol}_UNRESOLVED_SCALE_EVENT")
    if reasons:
        return None, reasons

    signal_slice = pd.RangeIndex(SIGNAL_START, SIGNAL_END + 1)
    q = qqq.loc[signal_slice]
    s = soxx.loc[signal_slice]

    q_long = (
        q["tradability_proxy_pass"]
        & (q["normalized_close"] > q["vwap"])
        & (q["ret_60m"] > 0)
        & (q["ret_15m"] > 0)
        & (q["normalized_close"] > q["prior_15m_high"])
    ).fillna(False)
    s_long = (
        s["tradability_proxy_pass"]
        & (s["normalized_close"] > s["vwap"])
        & (s["ret_60m"] > 0)
        & (s["ret_15m"] > 0)
        & (s["normalized_close"] > s["prior_15m_high"])
    ).fillna(False)

    q_short = (
        q["tradability_proxy_pass"]
        & (q["normalized_close"] < q["vwap"])
        & (q["ret_60m"] < 0)
        & (q["ret_15m"] < 0)
        & (q["normalized_close"] < q["prior_15m_low"])
    ).fillna(False)
    s_short = (
        s["tradability_proxy_pass"]
        & (s["normalized_close"] < s["vwap"])
        & (s["ret_60m"] < 0)
        & (s["ret_15m"] < 0)
        & (s["normalized_close"] < s["prior_15m_low"])
    ).fillna(False)

    long_state = q_long & s_long
    short_state = q_short & s_short
    long_transition = long_state & ~long_state.shift(
        1, fill_value=False
    )
    short_transition = short_state & ~short_state.shift(
        1, fill_value=False
    )

    triggers = pd.DataFrame(
        {"LONG": long_transition, "SHORT": short_transition},
        index=signal_slice,
    )
    locations = np.argwhere(triggers.to_numpy(dtype=bool))
    if len(locations) == 0:
        return None, []

    row_location, direction_location = locations[0]
    signal_minute = int(triggers.index[int(row_location)])
    direction = str(triggers.columns[int(direction_location)])

    q_row = qqq.loc[signal_minute]
    s_row = soxx.loc[signal_minute]
    q_norm = float(q_row["normalized_momentum_60m"])
    s_norm = float(s_row["normalized_momentum_60m"])

    if direction == "LONG":
        execution_symbol = "SOXL" if s_norm > q_norm else "TQQQ"
    else:
        execution_symbol = "SOXS" if s_norm < q_norm else "SQQQ"

    return {
        "trade_date": trade_date,
        "calendar_year": int(trade_date[:4]),
        "study_period": study_period(int(trade_date[:4])),
        "direction": direction,
        "execution_symbol": execution_symbol,
        "signal_session_minute": signal_minute,
        "signal_timestamp_utc": q_row["timestamp_utc"],
        "qqq_ret_15m": float(q_row["ret_15m"]),
        "soxx_ret_15m": float(s_row["ret_15m"]),
        "qqq_ret_60m": float(q_row["ret_60m"]),
        "soxx_ret_60m": float(s_row["ret_60m"]),
        "qqq_close_vs_vwap": (
            float(q_row["normalized_close"]) / float(q_row["vwap"]) - 1.0
        ),
        "soxx_close_vs_vwap": (
            float(s_row["normalized_close"]) / float(s_row["vwap"]) - 1.0
        ),
        "qqq_normalized_momentum_60m": q_norm,
        "soxx_normalized_momentum_60m": s_norm,
        "relative_normalized_momentum": s_norm - q_norm,
    }, []


def exit_minute(variant: str, entry_minute: int) -> int:
    if variant == "FIXED_30M":
        return entry_minute + 30
    if variant == "FIXED_60M":
        return entry_minute + 60
    if variant == "SESSION_1555":
        return SESSION_EXIT_MINUTE
    raise StudyError(f"Unknown exit variant: {variant}")


def return_from_grid(
    grid: pd.DataFrame,
    entry_minute: int,
    target_minute: int,
) -> tuple[float, dict[str, Any]] | None:
    if (
        entry_minute >= RTH_LENGTH
        or target_minute >= RTH_LENGTH
        or target_minute <= entry_minute
    ):
        return None

    entry = grid.loc[entry_minute]
    exit_row = grid.loc[target_minute]
    if (
        pd.isna(entry["normalized_open"])
        or pd.isna(exit_row["normalized_close"])
        or pd.isna(entry["timestamp_utc"])
        or pd.isna(exit_row["timestamp_utc"])
    ):
        return None

    entry_price = float(entry["normalized_open"])
    exit_price = float(exit_row["normalized_close"])
    net_return = (
        exit_price * (1.0 - EXIT_COST)
        / (entry_price * (1.0 + ENTRY_COST))
        - 1.0
    )
    return net_return, {
        "entry_timestamp_utc": entry["timestamp_utc"],
        "exit_timestamp_utc": exit_row["timestamp_utc"],
        "entry_price_normalized": entry_price,
        "exit_price_normalized": exit_price,
        "holding_minutes": target_minute - entry_minute,
    }


def simulate_candidate(
    candidate: Mapping[str, Any],
    grids: Mapping[str, pd.DataFrame],
    recognized: Mapping[str, pd.DataFrame],
    unresolved: Mapping[str, pd.DataFrame],
) -> tuple[list[dict[str, Any]], list[str]]:
    entry_minute = int(candidate["signal_session_minute"]) + 1
    direction = str(candidate["direction"])
    execution_symbol = str(candidate["execution_symbol"])
    pair_symbols = (
        ("TQQQ", "SOXL")
        if direction == "LONG"
        else ("SQQQ", "SOXS")
    )

    rows: list[dict[str, Any]] = []
    reasons: list[str] = []

    for variant in EXIT_VARIANTS:
        target = exit_minute(variant, entry_minute)
        selected = return_from_grid(
            grids[execution_symbol], entry_minute, target
        )
        if selected is None:
            reasons.append(f"{variant}_EXACT_EXECUTION_BAR_MISSING")
            continue
        selected_return, details = selected

        start = pd.Timestamp(details["entry_timestamp_utc"])
        end = pd.Timestamp(details["exit_timestamp_utc"])
        variant_reasons: list[str] = []
        for symbol in ALL_SYMBOLS:
            if event_in_window(unresolved[symbol], start, end):
                variant_reasons.append(
                    f"{variant}_{symbol}_UNRESOLVED_SCALE_EVENT"
                )
            if event_in_window(recognized[symbol], start, end):
                variant_reasons.append(
                    f"{variant}_{symbol}_RECOGNIZED_SCALE_EVENT"
                )
        if variant_reasons:
            reasons.extend(variant_reasons)
            continue

        pair_returns: list[float] = []
        for symbol in pair_symbols:
            result = return_from_grid(grids[symbol], entry_minute, target)
            if result is not None:
                pair_returns.append(float(result[0]))
        pair_mean = (
            float(np.mean(pair_returns))
            if len(pair_returns) == 2
            else math.nan
        )

        rows.append(
            {
                **dict(candidate),
                "exit_variant": variant,
                "entry_session_minute": entry_minute,
                "exit_session_minute": target,
                **details,
                "instrument_net_return": selected_return,
                "position_weight": FIXED_ACCOUNT_WEIGHT,
                "account_trade_return": (
                    selected_return * FIXED_ACCOUNT_WEIGHT
                ),
                "direction_pair_baseline_count": len(pair_returns),
                "direction_pair_mean_return": pair_mean,
                "selection_excess_return": (
                    selected_return - pair_mean
                    if np.isfinite(pair_mean)
                    else math.nan
                ),
            }
        )
    return rows, sorted(set(reasons))


def profit_factor(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    gains = float(clean.loc[clean > 0].sum())
    losses = float(-clean.loc[clean < 0].sum())
    if losses == 0:
        return math.inf if gains > 0 else math.nan
    return gains / losses


def positive_profit_share(values: pd.Series, top_n: int) -> float:
    positive = (
        pd.to_numeric(values, errors="coerce")
        .dropna()
        .loc[lambda series: series > 0]
        .sort_values(ascending=False)
    )
    total = float(positive.sum())
    if total <= 0:
        return math.nan
    return float(positive.head(top_n).sum() / total)


def cumulative_return(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").fillna(0.0)
    if clean.empty:
        return math.nan
    return float(np.prod(1.0 + clean.to_numpy(dtype=float)) - 1.0)


def maximum_drawdown(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").fillna(0.0)
    if clean.empty:
        return math.nan
    nav = (1.0 + clean).cumprod()
    return float((nav / nav.cummax() - 1.0).min())


def daily_returns(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, group in trades.groupby(
        ["exit_variant", "study_period", "trade_date"],
        sort=True,
    ):
        variant, period, trade_date = keys
        rows.append(
            {
                "exit_variant": variant,
                "study_period": period,
                "trade_date": trade_date,
                "calendar_year": int(str(trade_date)[:4]),
                "daily_return": float(
                    np.prod(
                        1.0
                        + group["account_trade_return"].to_numpy(
                            dtype=float
                        )
                    )
                    - 1.0
                ),
            }
        )
    return pd.DataFrame(rows)


def summarize_periods(
    trades: pd.DataFrame,
    daily: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for variant in EXIT_VARIANTS:
        for period in PERIODS:
            group = trades.loc[
                (trades["exit_variant"] == variant)
                & (trades["study_period"] == period)
            ]
            days = daily.loc[
                (daily["exit_variant"] == variant)
                & (daily["study_period"] == period)
            ]
            if group.empty:
                continue

            instrument = group["instrument_net_return"]
            account = group["account_trade_return"]
            excess = group["selection_excess_return"].dropna()
            rows.append(
                {
                    "exit_variant": variant,
                    "study_period": period,
                    "trade_count": int(len(group)),
                    "long_trade_count": int(
                        (group["direction"] == "LONG").sum()
                    ),
                    "short_trade_count": int(
                        (group["direction"] == "SHORT").sum()
                    ),
                    "mean_instrument_return": float(instrument.mean()),
                    "median_instrument_return": float(instrument.median()),
                    "positive_rate": float((instrument > 0).mean()),
                    "profit_factor": profit_factor(account),
                    "cumulative_return": cumulative_return(
                        days["daily_return"]
                    ),
                    "max_drawdown": maximum_drawdown(
                        days["daily_return"]
                    ),
                    "top1_positive_profit_share": positive_profit_share(
                        account, 1
                    ),
                    "top5_positive_profit_share": positive_profit_share(
                        account, 5
                    ),
                    "selection_excess_count": int(len(excess)),
                    "mean_selection_excess_return": (
                        float(excess.mean()) if len(excess) else math.nan
                    ),
                    "mean_signal_session_minute": float(
                        group["signal_session_minute"].mean()
                    ),
                    "mean_holding_minutes": float(
                        group["holding_minutes"].mean()
                    ),
                }
            )

    result = pd.DataFrame(rows)
    if not result.empty:
        result["period_order"] = result["study_period"].map(PERIOD_ORDER)
        result = result.sort_values(
            ["exit_variant", "period_order"],
            kind="mergesort",
        ).drop(columns=["period_order"])
    return result


def summarize_years(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, group in trades.groupby(
        ["exit_variant", "calendar_year"],
        sort=True,
    ):
        variant, year = keys
        rows.append(
            {
                "exit_variant": variant,
                "calendar_year": int(year),
                "trade_count": int(len(group)),
                "account_return_sum": float(
                    group["account_trade_return"].sum()
                ),
            }
        )
    return pd.DataFrame(rows)


def period_row(
    frame: pd.DataFrame,
    variant: str,
    period: str,
) -> pd.Series | None:
    rows = frame.loc[
        (frame["exit_variant"] == variant)
        & (frame["study_period"] == period)
    ]
    return None if rows.empty else rows.iloc[0]


def build_qualification(
    period: pd.DataFrame,
    year: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for variant in EXIT_VARIANTS:
        variant_rows = period.loc[period["exit_variant"] == variant]
        full_count = int(variant_rows["trade_count"].sum())
        validation = period_row(
            period, variant, "2023-2024_VALIDATION"
        )
        confirmation = period_row(
            period, variant, "2025-2026_YTD_CONFIRMATION"
        )
        validation_count = (
            int(validation["trade_count"])
            if validation is not None
            else 0
        )
        confirmation_count = (
            int(confirmation["trade_count"])
            if confirmation is not None
            else 0
        )

        sample_pass = bool(
            full_count >= MIN_FULL_HISTORY_TRADES
            and validation_count >= MIN_VALIDATION_TRADES
            and confirmation_count >= MIN_CONFIRMATION_TRADES
        )
        mean_pass = bool(
            sample_pass
            and float(validation["mean_instrument_return"]) > 0
            and float(confirmation["mean_instrument_return"]) > 0
        )
        median_pass = bool(
            sample_pass
            and float(validation["median_instrument_return"]) > 0
            and float(confirmation["median_instrument_return"]) > 0
        )
        pf_pass = bool(
            sample_pass
            and float(validation["profit_factor"]) > 1.0
            and float(confirmation["profit_factor"]) > 1.0
        )
        cumulative_pass = bool(
            sample_pass
            and float(validation["cumulative_return"]) > 0
            and float(confirmation["cumulative_return"]) > 0
        )
        selection_pass = bool(
            sample_pass
            and float(validation["mean_selection_excess_return"]) >= 0
            and float(confirmation["mean_selection_excess_return"]) >= 0
        )
        concentration_pass = bool(
            sample_pass
            and float(validation["top1_positive_profit_share"])
            <= MAX_TOP1_SHARE
            and float(confirmation["top1_positive_profit_share"])
            <= MAX_TOP1_SHARE
            and float(validation["top5_positive_profit_share"])
            <= MAX_TOP5_SHARE
            and float(confirmation["top5_positive_profit_share"])
            <= MAX_TOP5_SHARE
        )

        yearly = year.loc[year["exit_variant"] == variant]
        positive = yearly.loc[
            yearly["account_return_sum"] > 0,
            "account_return_sum",
        ]
        year_share = (
            float(positive.max() / positive.sum())
            if len(positive) and float(positive.sum()) > 0
            else math.nan
        )
        year_pass = bool(
            np.isfinite(year_share)
            and year_share <= MAX_POSITIVE_YEAR_SHARE
        )
        candidate = bool(
            sample_pass
            and mean_pass
            and median_pass
            and pf_pass
            and cumulative_pass
            and selection_pass
            and concentration_pass
            and year_pass
        )

        rows.append(
            {
                "exit_variant": variant,
                "full_history_trade_count": full_count,
                "validation_trade_count": validation_count,
                "confirmation_trade_count": confirmation_count,
                "sample_pass": sample_pass,
                "mean_positive_both_periods": mean_pass,
                "median_positive_both_periods": median_pass,
                "profit_factor_pass_both_periods": pf_pass,
                "cumulative_return_positive_both_periods": cumulative_pass,
                "selection_excess_nonnegative_both_periods": selection_pass,
                "trade_concentration_pass": concentration_pass,
                "single_positive_year_profit_share": year_share,
                "year_concentration_pass": year_pass,
                "research_candidate_for_independent_replication": candidate,
            }
        )
    return pd.DataFrame(rows)


def choose_decision(
    qualification: pd.DataFrame,
) -> tuple[str, list[str]]:
    supported = qualification.loc[
        qualification[
            "research_candidate_for_independent_replication"
        ],
        "exit_variant",
    ].astype(str).tolist()

    if supported:
        return (
            "RTH_LATE_DAY_CONTINUATION_CANDIDATE_"
            "REQUIRES_INDEPENDENT_REPLICATION",
            supported,
        )
    if not bool(qualification["sample_pass"].any()):
        return (
            "RTH_LATE_DAY_CONTINUATION_"
            "INCONCLUSIVE_INSUFFICIENT_SAMPLE",
            [],
        )
    return (
        "NO_RTH_LATE_DAY_CONTINUATION_CANDIDATE_QUALIFIED",
        [],
    )


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating)):
        if isinstance(value, np.floating) and not np.isfinite(value):
            return None
        return value.item()
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value)!r}")


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                default=json_default,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def format_value(column: str, value: Any) -> str:
    if pd.isna(value):
        return ""
    if column in {
        "mean_instrument_return",
        "median_instrument_return",
        "cumulative_return",
        "max_drawdown",
        "mean_selection_excess_return",
        "account_return_sum",
    }:
        return f"{float(value) * 10000:.2f}"
    if column in {
        "positive_rate",
        "top1_positive_profit_share",
        "top5_positive_profit_share",
        "single_positive_year_profit_share",
    }:
        return f"{float(value) * 100:.2f}"
    if column == "profit_factor":
        number = float(value)
        return "INF" if np.isinf(number) else f"{number:.3f}"
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.3f}"
    return str(value)


def print_table(title: str, frame: pd.DataFrame) -> None:
    print()
    print(f"========== {title} ==========")
    if frame.empty:
        print("NO_ROWS")
        return
    display = frame.copy()
    for column in display.columns:
        display[column] = [
            format_value(column, value)
            for value in display[column]
        ]
    print(display.to_string(index=False))


def run_study(
    rth_summary_path: Path,
    after_hours_summary_path: Path,
    forward_summary_path: Path,
    canonical_root: Path,
    result_dir: Path,
) -> dict[str, Any]:
    for path in (
        rth_summary_path,
        after_hours_summary_path,
        forward_summary_path,
        canonical_root,
    ):
        if not path.exists():
            raise StudyError(f"Missing required input: {path}")

    rth_summary = json.loads(
        rth_summary_path.read_text(encoding="utf-8-sig")
    )
    after_hours_summary = json.loads(
        after_hours_summary_path.read_text(encoding="utf-8-sig")
    )
    forward_summary = json.loads(
        forward_summary_path.read_text(encoding="utf-8-sig")
    )
    validate_lineage(rth_summary, after_hours_summary, forward_summary)

    canonical = index_canonical(canonical_root)
    normalized_by_symbol: dict[str, pd.DataFrame] = {}
    recognized_by_symbol: dict[str, pd.DataFrame] = {}
    unresolved_by_symbol: dict[str, pd.DataFrame] = {}
    paths_read: set[str] = set()

    for symbol in ALL_SYMBOLS:
        raw, symbol_paths = load_symbol_rth(symbol, canonical)
        paths_read.update(symbol_paths)
        normalized, recognized, unresolved = normalize_scale_series(raw)
        normalized_by_symbol[symbol] = normalized
        recognized_by_symbol[symbol] = recognized
        unresolved_by_symbol[symbol] = unresolved

    date_sets = {
        symbol: set(normalized_by_symbol[symbol]["trade_date"].unique())
        for symbol in ALL_SYMBOLS
    }
    common_dates = sorted(set.intersection(*date_sets.values()))

    session_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []

    for trade_date in common_dates:
        grids = {
            symbol: session_grid(
                get_day(normalized_by_symbol[symbol], trade_date)
            )
            for symbol in ALL_SYMBOLS
        }

        candidate, reasons = build_candidate(
            trade_date,
            grids["QQQ"],
            grids["SOXX"],
            recognized_by_symbol,
            unresolved_by_symbol,
        )
        rows: list[dict[str, Any]] = []
        if candidate is not None and not reasons:
            rows, execution_reasons = simulate_candidate(
                candidate,
                grids,
                recognized_by_symbol,
                unresolved_by_symbol,
            )
            reasons.extend(execution_reasons)

        quarantined = bool(reasons)
        session_rows.append(
            {
                "trade_date": trade_date,
                "signal_generated": candidate is not None,
                "trade_record_count": (
                    len(rows) if not quarantined else 0
                ),
                "session_quarantined": quarantined,
                "quarantine_reasons": "|".join(
                    sorted(set(reasons))
                ),
            }
        )
        if candidate is not None:
            candidate_rows.append(candidate)
        if not quarantined:
            trade_rows.extend(rows)

    sessions = pd.DataFrame(session_rows)
    candidates = pd.DataFrame(candidate_rows)
    trades = pd.DataFrame(trade_rows)

    if candidates.empty:
        raise StudyError("No RTH late-day candidate generated")
    if trades.empty:
        raise StudyError("No executable RTH late-day trades generated")

    candidates = candidates.sort_values(
        "trade_date",
        kind="mergesort",
    ).reset_index(drop=True)
    trades = trades.sort_values(
        ["trade_date", "exit_variant"],
        kind="mergesort",
    ).reset_index(drop=True)

    daily = daily_returns(trades)
    period = summarize_periods(trades, daily)
    year = summarize_years(trades)
    qualification = build_qualification(period, year)
    final_decision, supported = choose_decision(qualification)

    result_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "sessions": result_dir / "v22_063r2_sessions.csv",
        "candidates": result_dir / "v22_063r2_candidates.csv",
        "trades": result_dir / "v22_063r2_trades.csv",
        "daily": result_dir / "v22_063r2_daily_returns.csv",
        "period": result_dir / "v22_063r2_period_summary.csv",
        "year": result_dir / "v22_063r2_year_summary.csv",
        "qualification": result_dir / "v22_063r2_qualification.csv",
        "recognized_events": result_dir
        / "v22_063r2_recognized_scale_events.csv",
        "unresolved_events": result_dir
        / "v22_063r2_unresolved_scale_events.csv",
        "summary": result_dir / "v22_063r2_summary.json",
    }

    sessions.to_csv(outputs["sessions"], index=False, encoding="utf-8-sig")
    candidates.to_csv(
        outputs["candidates"], index=False, encoding="utf-8-sig"
    )
    trades.to_csv(outputs["trades"], index=False, encoding="utf-8-sig")
    daily.to_csv(outputs["daily"], index=False, encoding="utf-8-sig")
    period.to_csv(outputs["period"], index=False, encoding="utf-8-sig")
    year.to_csv(outputs["year"], index=False, encoding="utf-8-sig")
    qualification.to_csv(
        outputs["qualification"], index=False, encoding="utf-8-sig"
    )

    recognized_frames = []
    unresolved_frames = []
    for symbol in ALL_SYMBOLS:
        if not recognized_by_symbol[symbol].empty:
            recognized_frames.append(
                recognized_by_symbol[symbol].assign(symbol=symbol)
            )
        if not unresolved_by_symbol[symbol].empty:
            unresolved_frames.append(
                unresolved_by_symbol[symbol].assign(symbol=symbol)
            )

    recognized_all = (
        pd.concat(recognized_frames, ignore_index=True)
        if recognized_frames
        else pd.DataFrame()
    )
    unresolved_all = (
        pd.concat(unresolved_frames, ignore_index=True)
        if unresolved_frames
        else pd.DataFrame()
    )
    recognized_all.to_csv(
        outputs["recognized_events"], index=False, encoding="utf-8-sig"
    )
    unresolved_all.to_csv(
        outputs["unresolved_events"], index=False, encoding="utf-8-sig"
    )

    summary = {
        "version": VERSION,
        "final_status": "PASS",
        "final_decision": final_decision,
        "v22_063r1_validated": True,
        "v22_063a_validated": True,
        "v22_062pr_validated": True,
        "premarket_forward_chain_modified": False,
        "session_name": "RTH_LATE_DAY",
        "signal_start_et": "13:30",
        "signal_end_et": "14:54",
        "maximum_entries_per_session": 1,
        "entry_timing": "EXACT_NEXT_MINUTE_OPEN",
        "exit_variants": list(EXIT_VARIANTS),
        "entry_cost_bps": ENTRY_COST * 10000,
        "exit_cost_bps": EXIT_COST * 10000,
        "fixed_account_weight": FIXED_ACCOUNT_WEIGHT,
        "tradability_proxy_used": True,
        "corporate_action_safe_normalization_used": True,
        "signal_candidate_count": int(len(candidates)),
        "long_candidate_count": int(
            (candidates["direction"] == "LONG").sum()
        ),
        "short_candidate_count": int(
            (candidates["direction"] == "SHORT").sum()
        ),
        "trade_record_count": int(len(trades)),
        "trade_count_by_exit_variant": {
            variant: int(
                (trades["exit_variant"] == variant).sum()
            )
            for variant in EXIT_VARIANTS
        },
        "supported_exit_variants_for_replication": supported,
        "canonical_partition_count_indexed": int(len(canonical)),
        "canonical_partition_count_read": int(len(paths_read)),
        "parameter_sweep_executed": False,
        "signal_window_sweep_executed": False,
        "momentum_threshold_sweep_executed": False,
        "liquidity_threshold_sweep_executed": False,
        "exit_threshold_optimization_executed": False,
        "rsi_entry_gate_used": False,
        "macd_entry_gate_used": False,
        "kdj_entry_gate_used": False,
        "vix_entry_gate_used": False,
        "vix_risk_scaling_used": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "new_market_data_cache_created": False,
        "history_download_executed": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
        "outputs": {
            name: str(path)
            for name, path in outputs.items()
        },
    }
    atomic_json(outputs["summary"], summary)

    print("==============================================")
    print(" V22.063R2 RTH late-day continuation")
    print("==============================================")
    print_table(
        "Validation / Confirmation performance",
        period.loc[
            period["study_period"].isin(
                [
                    "2023-2024_VALIDATION",
                    "2025-2026_YTD_CONFIRMATION",
                ]
            )
        ],
    )
    print_table("Qualification", qualification)

    print()
    print("FINAL_STATUS=PASS")
    print(f"FINAL_DECISION={final_decision}")
    print("V22_063R1_VALIDATED=True")
    print("V22_063A_VALIDATED=True")
    print("V22_062PR_VALIDATED=True")
    print("PREMARKET_FORWARD_CHAIN_MODIFIED=False")
    print(f"SIGNAL_CANDIDATE_COUNT={len(candidates)}")
    print(
        f"LONG_CANDIDATE_COUNT="
        f"{int((candidates['direction'] == 'LONG').sum())}"
    )
    print(
        f"SHORT_CANDIDATE_COUNT="
        f"{int((candidates['direction'] == 'SHORT').sum())}"
    )
    for variant in EXIT_VARIANTS:
        print(
            f"TRADE_COUNT_{variant}="
            f"{int((trades['exit_variant'] == variant).sum())}"
        )
    print(
        "SUPPORTED_EXIT_VARIANTS_FOR_REPLICATION="
        f"{supported}"
    )
    print(
        f"CANONICAL_PARTITION_COUNT_READ="
        f"{len(paths_read)}"
    )
    print("PARAMETER_SWEEP_EXECUTED=False")
    print("SIGNAL_WINDOW_SWEEP_EXECUTED=False")
    print("MOMENTUM_THRESHOLD_SWEEP_EXECUTED=False")
    print("LIQUIDITY_THRESHOLD_SWEEP_EXECUTED=False")
    print("EXIT_THRESHOLD_OPTIMIZATION_EXECUTED=False")
    print("CANONICAL_FILES_MODIFIED=False")
    print("RAW_FILES_MODIFIED=False")
    print("NEW_MARKET_DATA_CACHE_CREATED=False")
    print("BROKER_ACTION_ALLOWED=False")
    print("PAPER_TRADING_ALLOWED=False")
    print("OFFICIAL_ADOPTION_ALLOWED=False")
    print(f"SUMMARY_PATH={outputs['summary']}")
    print(f"RESULT_DIRECTORY={result_dir}")

    return summary


def parse_args(
    argv: list[str] | None = None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--v22-063r1-summary",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.063R1_FAST3_RTH_VWAP_MEAN_REVERSION_BASELINE_R1"
            r"\v22_063r1_summary.json"
        ),
    )
    parser.add_argument(
        "--v22-063a-summary",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.063A_FAST3_AFTER_HOURS_CLOSE_CONTINUATION_BASELINE_R1"
            r"\v22_063a_summary.json"
        ),
    )
    parser.add_argument(
        "--v22-062pr-summary",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.062PR_FAST3_PREMARKET_INDEPENDENT_FORWARD_REPLICATION_R1"
            r"\v22_062pr_summary.json"
        ),
    )
    parser.add_argument(
        "--canonical-root",
        default=(
            r"D:\us-tech-quant-data\fast3"
            r"\moomoo_24h_1m\canonical"
        ),
    )
    parser.add_argument(
        "--result-dir",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.063R2_FAST3_RTH_LATE_DAY_CONTINUATION_BASELINE_R1"
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
        run_study(
            rth_summary_path=Path(args.v22_063r1_summary),
            after_hours_summary_path=Path(args.v22_063a_summary),
            forward_summary_path=Path(args.v22_062pr_summary),
            canonical_root=Path(args.canonical_root),
            result_dir=Path(args.result_dir),
        )
        return 0
    except Exception as exc:
        print("FINAL_STATUS=FAIL")
        print(f"ERROR_TYPE={type(exc).__name__}")
        print(f"ERROR={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
