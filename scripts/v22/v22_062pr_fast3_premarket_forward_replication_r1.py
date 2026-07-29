#!/usr/bin/env python
r"""
V22.062PR FAST3 premarket independent forward replication R1.

This stage freezes the corporate-action-safe PREMARKET_0925 candidate selected
by V22.062PB. It does not use pre-2026-07-25 outcomes to qualify the strategy.

Frozen research cutoff
----------------------
All data through 2026-07-24 ET is research/model-selection data.
Forward holdout sessions must have session_date > 2026-07-24.

Frozen signal
-------------
Session: 04:00-09:29 ET.
Initial range: 04:00-05:59 ET.
Signal window: 06:00-08:24 ET.
Maximum one trade per completed premarket session.
Entry: exact next-minute open.
Exit: exact 09:25 ET close.

LONG:
- QQQ and SOXX both above their most recent prior exact 15:59 ET closes.
- Both above their corporate-action-safe 04:00-05:59 range highs.
- Both above cumulative premarket typical-price VWAP.
- Both exact 30-minute returns positive.
- Both pass the frozen OHLCV tradability proxy.

SHORT: exact inverse conditions.

Execution selection:
- volatility-normalized 30-minute relative momentum;
- LONG: SOXX stronger -> SOXL, otherwise TQQQ;
- SHORT: SOXX weaker -> SOXS, otherwise SQQQ.

Frozen costs and sizing:
- 5 bps entry and 5 bps exit;
- 20% fixed account weight.

Forward decision gates
----------------------
Interim tracking:
- at least 60 completed holdout sessions and 20 trades.

Final independent replication:
- at least 120 completed holdout sessions and 30 trades;
- mean instrument return > 0;
- median instrument return > 0;
- profit factor > 1.10;
- cumulative account return > 0;
- maximum account drawdown >= -10%;
- top-one positive-profit share <= 35%;
- top-five positive-profit share <= 70%;
- mean ETF-selection excess return >= 0;
- quarantined-session rate <= 5%.

Until all final gates are evaluable, the result remains forward replication in
progress. No paper trading, broker action or official adoption is permitted.
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


VERSION = (
    "V22.062PR_FAST3_PREMARKET_INDEPENDENT_FORWARD_REPLICATION_R1"
)
SPEC_VERSION = "PREMARKET_0925_CORPORATE_ACTION_SAFE_FREEZE_R1"
RESEARCH_CUTOFF_DATE = "2026-07-24"

SIGNAL_SYMBOLS = ("QQQ", "SOXX")
EXECUTION_SYMBOLS = ("TQQQ", "SOXL", "SQQQ", "SOXS")
ALL_SYMBOLS = SIGNAL_SYMBOLS + EXECUTION_SYMBOLS

PREMARKET_START_ET = 4 * 60
PREMARKET_END_ET = 9 * 60 + 29
PREMARKET_LENGTH = 330

INITIAL_RANGE_START = 0
INITIAL_RANGE_END = 119
SIGNAL_START = 120
SIGNAL_END = 264
EXIT_MINUTE = 325
RTH_CLOSE_MINUTE_ET = 15 * 60 + 59

ENTRY_COST = 0.0005
EXIT_COST = 0.0005
FIXED_ACCOUNT_WEIGHT = 0.20

INITIAL_RANGE_MIN_BARS = 60
INITIAL_RANGE_FIRST_MAX = 10
INITIAL_RANGE_LAST_MIN = 110
RECENT_WINDOW = 30
RECENT_MIN_BARS = 15
RECENT_MIN_POSITIVE_VOLUME_BARS = 10
RECENT_MIN_CLOSE_CHANGES = 5
NORMALIZATION_WINDOW = 120
NORMALIZATION_MIN_RETURNS = 30

JUMP_THRESHOLD = 0.20
FACTOR_TOLERANCE = 0.03
ALLOWED_SPLIT_FACTORS = (
    2.0,
    3.0,
    4.0,
    5.0,
    6.0,
    8.0,
    10.0,
    15.0,
    20.0,
    25.0,
    30.0,
    40.0,
    50.0,
    100.0,
)

INTERIM_MIN_COMPLETED_SESSIONS = 60
INTERIM_MIN_TRADES = 20
FINAL_MIN_COMPLETED_SESSIONS = 120
FINAL_MIN_TRADES = 30

FINAL_MIN_PROFIT_FACTOR = 1.10
FINAL_MAX_DRAWDOWN = -0.10
FINAL_MAX_TOP1_SHARE = 0.35
FINAL_MAX_TOP5_SHARE = 0.70
FINAL_MAX_QUARANTINE_RATE = 0.05


class ReplicationError(RuntimeError):
    """V22.062PR cannot continue safely."""


@dataclass(frozen=True)
class ScaleEvent:
    timestamp_utc: pd.Timestamp
    recognized_factor: float
    relative_error: float


def require_columns(
    frame: pd.DataFrame,
    columns: Iterable[str],
    name: str,
) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ReplicationError(
            f"{name} missing required columns: {missing}"
        )


def validate_v22_062pb(summary: Mapping[str, Any]) -> None:
    expected = {
        "final_status": "PASS",
        "final_decision": (
            "PREMARKET_CORPORATE_ACTION_SAFE_CANDIDATE_"
            "REQUIRES_INDEPENDENT_REPLICATION"
        ),
        "v22_062p_validated": True,
        "v22_062pa_validated": True,
        "quarantined_trade_count": 0,
        "full_582_partition_reread": False,
        "strategy_signal_regeneration_executed": False,
        "parameter_sweep_executed": False,
        "threshold_optimization_executed": False,
        "official_corporate_action_data_downloaded": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "new_market_data_cache_created": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
        "next_stage": (
            "V22.062PR_FAST3_PREMARKET_INDEPENDENT_REPLICATION_R1"
        ),
    }
    failures = [
        f"{key}: expected {expected_value!r}, got {summary.get(key)!r}"
        for key, expected_value in expected.items()
        if summary.get(key) != expected_value
    ]
    if failures:
        raise ReplicationError(
            "V22.062PB lineage validation failed: "
            + "; ".join(failures)
        )

    if summary.get("supported_exit_variants_for_replication") != [
        "PREMARKET_0925"
    ]:
        raise ReplicationError(
            "V22.062PB did not freeze PREMARKET_0925 as sole candidate"
        )


def frozen_spec() -> dict[str, Any]:
    return {
        "spec_version": SPEC_VERSION,
        "research_cutoff_date": RESEARCH_CUTOFF_DATE,
        "session_et": ["04:00", "09:29"],
        "initial_range_et": ["04:00", "05:59"],
        "signal_window_et": ["06:00", "08:24"],
        "maximum_entries_per_session": 1,
        "entry_timing": "EXACT_NEXT_MINUTE_OPEN",
        "exit_timing": "EXACT_0925_CLOSE",
        "signal_symbols": list(SIGNAL_SYMBOLS),
        "execution_symbols": list(EXECUTION_SYMBOLS),
        "entry_cost_bps": ENTRY_COST * 10000,
        "exit_cost_bps": EXIT_COST * 10000,
        "fixed_account_weight": FIXED_ACCOUNT_WEIGHT,
        "initial_range_min_bars": INITIAL_RANGE_MIN_BARS,
        "recent_window_minutes": RECENT_WINDOW,
        "recent_min_bars": RECENT_MIN_BARS,
        "recent_min_positive_volume_bars": (
            RECENT_MIN_POSITIVE_VOLUME_BARS
        ),
        "recent_min_close_changes": RECENT_MIN_CLOSE_CHANGES,
        "normalization_window": NORMALIZATION_WINDOW,
        "normalization_min_returns": NORMALIZATION_MIN_RETURNS,
        "jump_threshold": JUMP_THRESHOLD,
        "factor_tolerance": FACTOR_TOLERANCE,
        "allowed_split_factors": list(ALLOWED_SPLIT_FACTORS),
        "interim_min_completed_sessions": (
            INTERIM_MIN_COMPLETED_SESSIONS
        ),
        "interim_min_trades": INTERIM_MIN_TRADES,
        "final_min_completed_sessions": FINAL_MIN_COMPLETED_SESSIONS,
        "final_min_trades": FINAL_MIN_TRADES,
        "final_min_profit_factor": FINAL_MIN_PROFIT_FACTOR,
        "final_max_drawdown": FINAL_MAX_DRAWDOWN,
        "final_max_top1_positive_profit_share": (
            FINAL_MAX_TOP1_SHARE
        ),
        "final_max_top5_positive_profit_share": (
            FINAL_MAX_TOP5_SHARE
        ),
        "final_max_quarantine_rate": FINAL_MAX_QUARANTINE_RATE,
    }


def spec_hash(spec: Mapping[str, Any]) -> str:
    payload = json.dumps(
        spec,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def validate_or_create_freeze_manifest(
    path: Path,
    source_summary_path: Path,
) -> dict[str, Any]:
    spec = frozen_spec()
    digest = spec_hash(spec)

    if path.exists():
        manifest = json.loads(
            path.read_text(encoding="utf-8-sig")
        )
        if manifest.get("frozen_spec_sha256") != digest:
            raise ReplicationError(
                "Frozen specification changed. Forward observation "
                "must be reset in a new result directory."
            )
        if manifest.get("research_cutoff_date") != RESEARCH_CUTOFF_DATE:
            raise ReplicationError("Research cutoff date changed")
        return manifest

    manifest = {
        "version": VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "research_cutoff_date": RESEARCH_CUTOFF_DATE,
        "forward_holdout_rule": (
            "SESSION_DATE_STRICTLY_GREATER_THAN_RESEARCH_CUTOFF"
        ),
        "frozen_spec_sha256": digest,
        "frozen_spec": spec,
        "source_v22_062pb_summary_path": str(source_summary_path),
        "rule_change_requires_reset": True,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }
    atomic_json(path, manifest)
    return manifest


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
        raise ReplicationError(
            f"Cannot parse Canonical path: {path}"
        )
    return symbol, year, month


def index_forward_partitions(
    root: Path,
) -> dict[tuple[str, str, str], Path]:
    cutoff_month = RESEARCH_CUTOFF_DATE[:7].replace("-", "")
    result: dict[tuple[str, str, str], Path] = {}

    for path in sorted(root.rglob("*.parquet")):
        key = symbol_month_from_path(path)
        symbol, year, month = key
        if symbol not in ALL_SYMBOLS:
            continue
        month_key = f"{year}{month}"
        # Keep one month before cutoff for prior-close continuity.
        if month_key < "202606":
            continue
        if key in result:
            raise ReplicationError(
                f"Duplicate Canonical partition: {key}"
            )
        result[key] = path

    symbols_found = {key[0] for key in result}
    missing = set(ALL_SYMBOLS) - symbols_found
    if missing:
        raise ReplicationError(
            f"Missing forward Canonical partitions for {sorted(missing)}"
        )
    return result


def find_column(
    frame: pd.DataFrame,
    aliases: Iterable[str],
) -> str:
    mapping = {
        str(column).strip().lower(): str(column)
        for column in frame.columns
    }
    for alias in aliases:
        if alias.lower() in mapping:
            return mapping[alias.lower()]
    raise ReplicationError(
        f"Missing column from aliases={tuple(aliases)}"
    )


def load_symbol_rows(
    symbol: str,
    partitions: Mapping[tuple[str, str, str], Path],
) -> tuple[pd.DataFrame, list[str]]:
    paths = [
        path
        for (current, _, _), path in sorted(partitions.items())
        if current == symbol
    ]
    frames: list[pd.DataFrame] = []
    paths_read: list[str] = []

    for path in paths:
        raw = pd.read_parquet(path)
        paths_read.append(str(path))
        if raw.empty:
            continue

        timestamp = pd.to_datetime(
            raw[find_column(raw, ("timestamp_utc",))],
            errors="raise",
            utc=True,
        )
        frame = pd.DataFrame(
            {
                "timestamp_utc": timestamp,
                "open": pd.to_numeric(
                    raw[find_column(raw, ("open",))],
                    errors="coerce",
                ),
                "high": pd.to_numeric(
                    raw[find_column(raw, ("high",))],
                    errors="coerce",
                ),
                "low": pd.to_numeric(
                    raw[find_column(raw, ("low",))],
                    errors="coerce",
                ),
                "close": pd.to_numeric(
                    raw[find_column(raw, ("close",))],
                    errors="coerce",
                ),
                "volume": pd.to_numeric(
                    raw[find_column(raw, ("volume",))],
                    errors="coerce",
                ).fillna(0.0),
            }
        ).dropna(
            subset=[
                "timestamp_utc",
                "open",
                "high",
                "low",
                "close",
            ]
        )
        frames.append(frame)

    if not frames:
        return pd.DataFrame(), paths_read

    combined = (
        pd.concat(frames, ignore_index=True)
        .sort_values(
            "timestamp_utc",
            kind="mergesort",
        )
        .drop_duplicates(
            "timestamp_utc",
            keep="last",
        )
        .reset_index(drop=True)
    )
    return combined, paths_read


def candidate_factors() -> np.ndarray:
    values = set(ALLOWED_SPLIT_FACTORS)
    values.update(
        1.0 / value
        for value in ALLOWED_SPLIT_FACTORS
    )
    return np.array(sorted(values), dtype=float)


def snap_split_factor(
    raw_ratio: float,
) -> tuple[float, float] | None:
    if not np.isfinite(raw_ratio) or raw_ratio <= 0:
        return None
    factors = candidate_factors()
    errors = np.abs(factors / raw_ratio - 1.0)
    location = int(np.argmin(errors))
    factor = float(factors[location])
    error = float(errors[location])
    if error <= FACTOR_TOLERANCE:
        return factor, error
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
            raw_change = current_open / previous_close - 1.0
            if abs(raw_change) >= JUMP_THRESHOLD:
                raw_ratio = previous_close / current_open
                snapped = snap_split_factor(raw_ratio)
                record = {
                    "timestamp_utc": timestamp,
                    "previous_timestamp_utc": previous_timestamp,
                    "previous_close": previous_close,
                    "current_open": current_open,
                    "raw_change": raw_change,
                    "raw_ratio": raw_ratio,
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

    local = result["timestamp_utc"].dt.tz_convert(
        "America/New_York"
    )
    result["local_date"] = local.dt.strftime("%Y-%m-%d")
    result["minute_et"] = (
        local.dt.hour * 60 + local.dt.minute
    ).astype(int)

    return (
        result,
        pd.DataFrame(recognized),
        pd.DataFrame(unresolved),
    )


def extract_premarket_table(
    normalized: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    premarket = normalized.loc[
        (normalized["minute_et"] >= PREMARKET_START_ET)
        & (normalized["minute_et"] <= PREMARKET_END_ET)
    ].copy()
    premarket["session_minute"] = (
        premarket["minute_et"] - PREMARKET_START_ET
    ).astype(int)

    closes = normalized.loc[
        normalized["minute_et"] == RTH_CLOSE_MINUTE_ET,
        [
            "local_date",
            "timestamp_utc",
            "normalized_close",
        ],
    ].copy()
    closes = (
        closes.sort_values(
            "timestamp_utc",
            kind="mergesort",
        )
        .drop_duplicates(
            "local_date",
            keep="last",
        )
        .reset_index(drop=True)
    )
    return premarket, closes


def session_grid(day: pd.DataFrame) -> pd.DataFrame:
    grid = pd.DataFrame(index=pd.RangeIndex(PREMARKET_LENGTH))
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
        grid["complete_session"] = False
        return grid

    indexed = (
        day.sort_values(
            "session_minute",
            kind="mergesort",
        )
        .drop_duplicates(
            "session_minute",
            keep="last",
        )
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
    grid["positive_volume"] = (
        grid["volume"].fillna(0.0) > 0
    )
    grid["complete_session"] = bool(
        grid.loc[PREMARKET_END_ET - PREMARKET_START_ET, "observed"]
    )

    typical = (
        grid["normalized_high"]
        + grid["normalized_low"]
        + grid["normalized_close"]
    ) / 3.0
    volume = grid["volume"].fillna(0.0).clip(lower=0.0)
    cumulative_volume = volume.cumsum()
    cumulative_value = (
        typical.fillna(0.0) * volume
    ).cumsum()
    observed_mean = (
        grid["normalized_close"].expanding().mean()
    )
    grid["vwap"] = cumulative_value.divide(
        cumulative_volume.where(cumulative_volume > 0)
    ).fillna(observed_mean)

    grid["ret_1m"] = (
        grid["normalized_close"].pct_change(
            fill_method=None
        )
    )
    grid["ret_30m"] = (
        grid["normalized_close"]
        / grid["normalized_close"].shift(30)
        - 1.0
    )
    grid["recent_observed_count"] = (
        grid["observed"].rolling(
            RECENT_WINDOW,
            min_periods=1,
        ).sum()
    )
    grid["recent_positive_volume_count"] = (
        grid["positive_volume"].rolling(
            RECENT_WINDOW,
            min_periods=1,
        ).sum()
    )

    close_change = (
        grid["normalized_close"].diff().abs().gt(0)
        & grid["normalized_close"].notna()
        & grid["normalized_close"].shift(1).notna()
    )
    grid["recent_close_change_count"] = (
        close_change.rolling(
            RECENT_WINDOW,
            min_periods=1,
        ).sum()
    )
    grid["realized_vol_120m"] = (
        grid["ret_1m"].rolling(
            NORMALIZATION_WINDOW,
            min_periods=NORMALIZATION_MIN_RETURNS,
        ).std(ddof=1)
        * math.sqrt(30.0)
    )
    grid["normalized_momentum_30m"] = (
        grid["ret_30m"]
        / grid["realized_vol_120m"].replace(
            0.0,
            np.nan,
        )
    )

    opening = grid.loc[
        INITIAL_RANGE_START:INITIAL_RANGE_END
    ]
    observed_opening = opening.loc[opening["observed"]]
    count = int(len(observed_opening))

    grid["initial_range_bar_count"] = count
    grid["initial_range_high"] = (
        float(
            observed_opening[
                "normalized_high"
            ].max()
        )
        if count
        else np.nan
    )
    grid["initial_range_low"] = (
        float(
            observed_opening[
                "normalized_low"
            ].min()
        )
        if count
        else np.nan
    )
    grid["initial_range_complete"] = bool(
        count >= INITIAL_RANGE_MIN_BARS
        and int(observed_opening.index.min())
        <= INITIAL_RANGE_FIRST_MAX
        and int(observed_opening.index.max())
        >= INITIAL_RANGE_LAST_MIN
    ) if count else False

    grid["tradability_proxy_pass"] = (
        grid["observed"]
        & grid["normalized_close"].shift(30).notna()
        & (
            grid["recent_observed_count"]
            >= RECENT_MIN_BARS
        )
        & (
            grid["recent_positive_volume_count"]
            >= RECENT_MIN_POSITIVE_VOLUME_BARS
        )
        & (
            grid["recent_close_change_count"]
            >= RECENT_MIN_CLOSE_CHANGES
        )
        & grid["normalized_momentum_30m"].notna()
    )
    return grid


def get_session(
    premarket: pd.DataFrame,
    session_date: str,
) -> pd.DataFrame:
    return (
        premarket.loc[
            premarket["local_date"] == session_date
        ]
        .sort_values(
            "session_minute",
            kind="mergesort",
        )
        .reset_index(drop=True)
    )


def prior_close(
    closes: pd.DataFrame,
    session_date: str,
) -> dict[str, Any] | None:
    cutoff = pd.Timestamp(session_date)
    eligible = closes.loc[
        pd.to_datetime(closes["local_date"]) < cutoff
    ]
    if eligible.empty:
        return None
    row = eligible.iloc[-1]
    return {
        "prior_close_date": str(row["local_date"]),
        "prior_close_timestamp_utc": row["timestamp_utc"],
        "prior_rth_close": float(row["normalized_close"]),
    }


def event_in_window(
    events: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> bool:
    if events.empty:
        return False
    timestamps = pd.to_datetime(
        events["timestamp_utc"],
        utc=True,
    )
    return bool(
        ((timestamps >= start) & (timestamps <= end)).any()
    )


def build_candidate(
    session_date: str,
    qqq_grid: pd.DataFrame,
    soxx_grid: pd.DataFrame,
    qqq_prior: Mapping[str, Any],
    soxx_prior: Mapping[str, Any],
    qqq_recognized: pd.DataFrame,
    qqq_unresolved: pd.DataFrame,
    soxx_recognized: pd.DataFrame,
    soxx_unresolved: pd.DataFrame,
) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []

    if not bool(qqq_grid["complete_session"].iloc[0]):
        reasons.append("QQQ_INCOMPLETE_PREMARKET")
    if not bool(soxx_grid["complete_session"].iloc[0]):
        reasons.append("SOXX_INCOMPLETE_PREMARKET")
    if reasons:
        return None, reasons

    if not bool(
        qqq_grid["initial_range_complete"].iloc[0]
    ):
        reasons.append("QQQ_INITIAL_RANGE_INCOMPLETE")
    if not bool(
        soxx_grid["initial_range_complete"].iloc[0]
    ):
        reasons.append("SOXX_INITIAL_RANGE_INCOMPLETE")
    if reasons:
        return None, reasons

    start = pd.Timestamp(
        f"{session_date} 04:00",
        tz="America/New_York",
    ).tz_convert("UTC")
    signal_end = pd.Timestamp(
        f"{session_date} 08:24",
        tz="America/New_York",
    ).tz_convert("UTC")

    if event_in_window(
        qqq_recognized,
        start,
        signal_end,
    ):
        reasons.append("QQQ_RECOGNIZED_SCALE_EVENT_DURING_SIGNAL")
    if event_in_window(
        soxx_recognized,
        start,
        signal_end,
    ):
        reasons.append("SOXX_RECOGNIZED_SCALE_EVENT_DURING_SIGNAL")
    if event_in_window(
        qqq_unresolved,
        pd.Timestamp(
            qqq_prior["prior_close_timestamp_utc"]
        ),
        signal_end,
    ):
        reasons.append("QQQ_UNRESOLVED_SCALE_EVENT")
    if event_in_window(
        soxx_unresolved,
        pd.Timestamp(
            soxx_prior["prior_close_timestamp_utc"]
        ),
        signal_end,
    ):
        reasons.append("SOXX_UNRESOLVED_SCALE_EVENT")
    if reasons:
        return None, reasons

    signal_slice = pd.RangeIndex(
        SIGNAL_START,
        SIGNAL_END + 1,
    )
    qqq = qqq_grid.loc[signal_slice]
    soxx = soxx_grid.loc[signal_slice]

    qqq_long = (
        qqq["tradability_proxy_pass"]
        & (
            qqq["normalized_close"]
            > float(qqq_prior["prior_rth_close"])
        )
        & (
            qqq["normalized_close"]
            > qqq["initial_range_high"]
        )
        & (qqq["normalized_close"] > qqq["vwap"])
        & (qqq["ret_30m"] > 0)
    ).fillna(False)
    soxx_long = (
        soxx["tradability_proxy_pass"]
        & (
            soxx["normalized_close"]
            > float(soxx_prior["prior_rth_close"])
        )
        & (
            soxx["normalized_close"]
            > soxx["initial_range_high"]
        )
        & (soxx["normalized_close"] > soxx["vwap"])
        & (soxx["ret_30m"] > 0)
    ).fillna(False)

    qqq_short = (
        qqq["tradability_proxy_pass"]
        & (
            qqq["normalized_close"]
            < float(qqq_prior["prior_rth_close"])
        )
        & (
            qqq["normalized_close"]
            < qqq["initial_range_low"]
        )
        & (qqq["normalized_close"] < qqq["vwap"])
        & (qqq["ret_30m"] < 0)
    ).fillna(False)
    soxx_short = (
        soxx["tradability_proxy_pass"]
        & (
            soxx["normalized_close"]
            < float(soxx_prior["prior_rth_close"])
        )
        & (
            soxx["normalized_close"]
            < soxx["initial_range_low"]
        )
        & (soxx["normalized_close"] < soxx["vwap"])
        & (soxx["ret_30m"] < 0)
    ).fillna(False)

    long_state = qqq_long & soxx_long
    short_state = qqq_short & soxx_short
    long_transition = (
        long_state
        & ~long_state.shift(
            1,
            fill_value=False,
        )
    )
    short_transition = (
        short_state
        & ~short_state.shift(
            1,
            fill_value=False,
        )
    )

    triggers = pd.DataFrame(
        {
            "LONG": long_transition,
            "SHORT": short_transition,
        },
        index=signal_slice,
    )
    locations = np.argwhere(
        triggers.to_numpy(dtype=bool)
    )
    if len(locations) == 0:
        return None, []

    row_location, direction_location = locations[0]
    signal_minute = int(
        triggers.index[int(row_location)]
    )
    direction = str(
        triggers.columns[int(direction_location)]
    )

    qqq_row = qqq_grid.loc[signal_minute]
    soxx_row = soxx_grid.loc[signal_minute]
    qqq_momentum = float(
        qqq_row["normalized_momentum_30m"]
    )
    soxx_momentum = float(
        soxx_row["normalized_momentum_30m"]
    )

    if direction == "LONG":
        execution_symbol = (
            "SOXL"
            if soxx_momentum > qqq_momentum
            else "TQQQ"
        )
    else:
        execution_symbol = (
            "SOXS"
            if soxx_momentum < qqq_momentum
            else "SQQQ"
        )

    return {
        "session_date": session_date,
        "calendar_year": int(session_date[:4]),
        "direction": direction,
        "execution_symbol": execution_symbol,
        "signal_session_minute": signal_minute,
        "signal_timestamp_utc": qqq_row[
            "timestamp_utc"
        ],
        "qqq_prior_close_date": qqq_prior[
            "prior_close_date"
        ],
        "soxx_prior_close_date": soxx_prior[
            "prior_close_date"
        ],
        "qqq_prior_rth_close": float(
            qqq_prior["prior_rth_close"]
        ),
        "soxx_prior_rth_close": float(
            soxx_prior["prior_rth_close"]
        ),
        "qqq_signal_close": float(
            qqq_row["normalized_close"]
        ),
        "soxx_signal_close": float(
            soxx_row["normalized_close"]
        ),
        "qqq_gap_at_signal": (
            float(qqq_row["normalized_close"])
            / float(qqq_prior["prior_rth_close"])
            - 1.0
        ),
        "soxx_gap_at_signal": (
            float(soxx_row["normalized_close"])
            / float(soxx_prior["prior_rth_close"])
            - 1.0
        ),
        "qqq_ret_30m": float(qqq_row["ret_30m"]),
        "soxx_ret_30m": float(soxx_row["ret_30m"]),
        "qqq_normalized_momentum_30m": (
            qqq_momentum
        ),
        "soxx_normalized_momentum_30m": (
            soxx_momentum
        ),
        "relative_normalized_momentum": (
            soxx_momentum - qqq_momentum
        ),
    }, []


def return_from_grid(
    grid: pd.DataFrame,
    entry_minute: int,
) -> tuple[float, dict[str, Any]] | None:
    if (
        entry_minute >= PREMARKET_LENGTH
        or EXIT_MINUTE >= PREMARKET_LENGTH
    ):
        return None

    entry = grid.loc[entry_minute]
    exit_row = grid.loc[EXIT_MINUTE]
    if (
        pd.isna(entry["normalized_open"])
        or pd.isna(exit_row["normalized_close"])
        or pd.isna(entry["timestamp_utc"])
        or pd.isna(exit_row["timestamp_utc"])
    ):
        return None

    entry_price = float(entry["normalized_open"])
    exit_price = float(exit_row["normalized_close"])
    value = (
        exit_price * (1.0 - EXIT_COST)
        / (
            entry_price
            * (1.0 + ENTRY_COST)
        )
        - 1.0
    )
    return value, {
        "entry_timestamp_utc": entry["timestamp_utc"],
        "exit_timestamp_utc": exit_row["timestamp_utc"],
        "entry_price_normalized": entry_price,
        "exit_price_normalized": exit_price,
        "holding_minutes": (
            EXIT_MINUTE - entry_minute
        ),
    }


def simulate_candidate(
    candidate: Mapping[str, Any],
    grids: Mapping[str, pd.DataFrame],
    recognized_events: Mapping[str, pd.DataFrame],
    unresolved_events: Mapping[str, pd.DataFrame],
) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    entry_minute = int(
        candidate["signal_session_minute"]
    ) + 1
    execution_symbol = str(
        candidate["execution_symbol"]
    )

    entry_time = pd.Timestamp(
        f"{candidate['session_date']} 04:00",
        tz="America/New_York",
    ).tz_convert("UTC") + pd.Timedelta(
        minutes=entry_minute
    )
    exit_time = pd.Timestamp(
        f"{candidate['session_date']} 09:25",
        tz="America/New_York",
    ).tz_convert("UTC")

    if event_in_window(
        unresolved_events[execution_symbol],
        entry_time,
        exit_time,
    ):
        reasons.append(
            "EXECUTION_UNRESOLVED_SCALE_EVENT_DURING_HOLDING"
        )
        return None, reasons

    selected = return_from_grid(
        grids[execution_symbol],
        entry_minute,
    )
    if selected is None:
        reasons.append("EXECUTION_EXACT_BAR_MISSING")
        return None, reasons

    selected_return, details = selected
    direction = str(candidate["direction"])
    pair = (
        ("TQQQ", "SOXL")
        if direction == "LONG"
        else ("SQQQ", "SOXS")
    )
    pair_returns: list[float] = []
    for symbol in pair:
        result = return_from_grid(
            grids[symbol],
            entry_minute,
        )
        if result is not None:
            pair_returns.append(float(result[0]))

    pair_mean = (
        float(np.mean(pair_returns))
        if len(pair_returns) == 2
        else math.nan
    )
    return {
        **dict(candidate),
        **details,
        "instrument_net_return": selected_return,
        "position_weight": FIXED_ACCOUNT_WEIGHT,
        "account_trade_return": (
            selected_return
            * FIXED_ACCOUNT_WEIGHT
        ),
        "direction_pair_baseline_count": len(
            pair_returns
        ),
        "direction_pair_mean_return": pair_mean,
        "selection_excess_return": (
            selected_return - pair_mean
            if np.isfinite(pair_mean)
            else math.nan
        ),
        "recognized_execution_scale_event_during_holding": (
            event_in_window(
                recognized_events[
                    execution_symbol
                ],
                entry_time,
                exit_time,
            )
        ),
    }, []


def profit_factor(values: pd.Series) -> float:
    clean = pd.to_numeric(
        values,
        errors="coerce",
    ).dropna()
    gains = float(clean.loc[clean > 0].sum())
    losses = float(-clean.loc[clean < 0].sum())
    if losses == 0:
        return math.inf if gains > 0 else math.nan
    return gains / losses


def positive_profit_share(
    values: pd.Series,
    count: int,
) -> float:
    positive = (
        pd.to_numeric(
            values,
            errors="coerce",
        )
        .dropna()
        .loc[lambda series: series > 0]
        .sort_values(ascending=False)
    )
    total = float(positive.sum())
    if total <= 0:
        return math.nan
    return float(
        positive.head(count).sum() / total
    )


def maximum_drawdown(
    values: pd.Series,
) -> float:
    clean = pd.to_numeric(
        values,
        errors="coerce",
    ).fillna(0.0)
    if clean.empty:
        return math.nan
    nav = (
        1.0 + clean
    ).cumprod()
    return float(
        (nav / nav.cummax() - 1.0).min()
    )


def cumulative_return(
    values: pd.Series,
) -> float:
    clean = pd.to_numeric(
        values,
        errors="coerce",
    ).fillna(0.0)
    if clean.empty:
        return math.nan
    return float(
        np.prod(
            1.0
            + clean.to_numpy(dtype=float)
        )
        - 1.0
    )


def evaluate_forward(
    completed_sessions: pd.DataFrame,
    trades: pd.DataFrame,
) -> dict[str, Any]:
    completed_count = int(len(completed_sessions))
    quarantined_count = int(
        completed_sessions[
            "session_quarantined"
        ].sum()
    ) if not completed_sessions.empty else 0
    quarantine_rate = (
        quarantined_count / completed_count
        if completed_count
        else math.nan
    )

    trade_count = int(len(trades))
    if trade_count:
        instrument = trades[
            "instrument_net_return"
        ]
        account = trades[
            "account_trade_return"
        ]
        mean_return = float(instrument.mean())
        median_return = float(instrument.median())
        pf = profit_factor(account)
        cumulative = cumulative_return(account)
        mdd = maximum_drawdown(account)
        top1 = positive_profit_share(account, 1)
        top5 = positive_profit_share(account, 5)
        selection_excess = float(
            trades[
                "selection_excess_return"
            ].dropna().mean()
        )
    else:
        mean_return = math.nan
        median_return = math.nan
        pf = math.nan
        cumulative = math.nan
        mdd = math.nan
        top1 = math.nan
        top5 = math.nan
        selection_excess = math.nan

    interim_evaluable = bool(
        completed_count
        >= INTERIM_MIN_COMPLETED_SESSIONS
        and trade_count >= INTERIM_MIN_TRADES
    )
    final_evaluable = bool(
        completed_count
        >= FINAL_MIN_COMPLETED_SESSIONS
        and trade_count >= FINAL_MIN_TRADES
    )

    gates = {
        "mean_positive": bool(
            final_evaluable
            and mean_return > 0
        ),
        "median_positive": bool(
            final_evaluable
            and median_return > 0
        ),
        "profit_factor_pass": bool(
            final_evaluable
            and pf > FINAL_MIN_PROFIT_FACTOR
        ),
        "cumulative_return_positive": bool(
            final_evaluable
            and cumulative > 0
        ),
        "max_drawdown_pass": bool(
            final_evaluable
            and mdd >= FINAL_MAX_DRAWDOWN
        ),
        "top1_concentration_pass": bool(
            final_evaluable
            and np.isfinite(top1)
            and top1 <= FINAL_MAX_TOP1_SHARE
        ),
        "top5_concentration_pass": bool(
            final_evaluable
            and np.isfinite(top5)
            and top5 <= FINAL_MAX_TOP5_SHARE
        ),
        "selection_excess_nonnegative": bool(
            final_evaluable
            and np.isfinite(selection_excess)
            and selection_excess >= 0
        ),
        "quarantine_rate_pass": bool(
            final_evaluable
            and np.isfinite(quarantine_rate)
            and quarantine_rate
            <= FINAL_MAX_QUARANTINE_RATE
        ),
    }
    final_pass = bool(
        final_evaluable
        and all(gates.values())
    )

    if not interim_evaluable:
        decision = (
            "FORWARD_REPLICATION_IN_PROGRESS_"
            "INSUFFICIENT_INTERIM_SAMPLE"
        )
    elif not final_evaluable:
        decision = (
            "FORWARD_REPLICATION_INTERIM_ONLY_"
            "NOT_FINAL_DECISION_READY"
        )
    elif final_pass:
        decision = (
            "PREMARKET_0925_FORWARD_REPLICATION_PASSED_"
            "RESEARCH_CANDIDATE_ONLY"
        )
    else:
        decision = (
            "PREMARKET_0925_FORWARD_REPLICATION_FAILED"
        )

    return {
        "final_decision": decision,
        "completed_holdout_session_count": completed_count,
        "quarantined_holdout_session_count": quarantined_count,
        "quarantined_holdout_session_rate": quarantine_rate,
        "forward_trade_count": trade_count,
        "interim_evaluable": interim_evaluable,
        "final_evaluable": final_evaluable,
        "forward_mean_instrument_return": mean_return,
        "forward_median_instrument_return": median_return,
        "forward_profit_factor": pf,
        "forward_cumulative_account_return": cumulative,
        "forward_max_drawdown": mdd,
        "forward_top1_positive_profit_share": top1,
        "forward_top5_positive_profit_share": top5,
        "forward_mean_selection_excess_return": selection_excess,
        "final_gate_results": gates,
        "forward_replication_pass": final_pass,
    }


def json_default(value: Any) -> Any:
    if isinstance(
        value,
        (np.integer, np.floating),
    ):
        if (
            isinstance(value, np.floating)
            and not np.isfinite(value)
        ):
            return None
        return value.item()
    if isinstance(
        value,
        (pd.Timestamp, Path),
    ):
        return str(value)
    raise TypeError(
        f"Cannot serialize {type(value)!r}"
    )


def atomic_json(
    path: Path,
    payload: Mapping[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    temp = path.with_name(
        f".{path.name}.{os.getpid()}.tmp"
    )
    try:
        temp.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                default=json_default,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def print_summary(
    evaluation: Mapping[str, Any],
) -> None:
    print()
    print(
        "========== Forward replication status =========="
    )
    fields = (
        "completed_holdout_session_count",
        "quarantined_holdout_session_count",
        "quarantined_holdout_session_rate",
        "forward_trade_count",
        "interim_evaluable",
        "final_evaluable",
        "forward_mean_instrument_return",
        "forward_median_instrument_return",
        "forward_profit_factor",
        "forward_cumulative_account_return",
        "forward_max_drawdown",
        "forward_top1_positive_profit_share",
        "forward_top5_positive_profit_share",
        "forward_mean_selection_excess_return",
        "forward_replication_pass",
    )
    for field in fields:
        print(
            f"{field.upper()}="
            f"{evaluation.get(field)}"
        )


def run_replication(
    v22_062pb_root: Path,
    canonical_root: Path,
    result_dir: Path,
) -> dict[str, Any]:
    pb_summary_path = (
        v22_062pb_root
        / "v22_062pb_summary.json"
    )
    if not pb_summary_path.exists():
        raise ReplicationError(
            f"Missing V22.062PB summary: {pb_summary_path}"
        )
    if not canonical_root.exists():
        raise ReplicationError(
            f"Missing Canonical root: {canonical_root}"
        )

    pb_summary = json.loads(
        pb_summary_path.read_text(
            encoding="utf-8-sig"
        )
    )
    validate_v22_062pb(pb_summary)

    result_dir.mkdir(
        parents=True,
        exist_ok=True,
    )
    freeze_path = (
        result_dir
        / "v22_062pr_freeze_manifest.json"
    )
    freeze = validate_or_create_freeze_manifest(
        freeze_path,
        pb_summary_path,
    )

    partitions = index_forward_partitions(
        canonical_root
    )

    normalized_by_symbol: dict[
        str,
        pd.DataFrame,
    ] = {}
    premarket_by_symbol: dict[
        str,
        pd.DataFrame,
    ] = {}
    closes_by_symbol: dict[
        str,
        pd.DataFrame,
    ] = {}
    recognized_by_symbol: dict[
        str,
        pd.DataFrame,
    ] = {}
    unresolved_by_symbol: dict[
        str,
        pd.DataFrame,
    ] = {}
    paths_read: set[str] = set()

    for symbol in ALL_SYMBOLS:
        raw, symbol_paths = load_symbol_rows(
            symbol,
            partitions,
        )
        paths_read.update(symbol_paths)
        normalized, recognized, unresolved = (
            normalize_scale_series(raw)
        )
        premarket, closes = extract_premarket_table(
            normalized
        )
        normalized_by_symbol[symbol] = normalized
        premarket_by_symbol[symbol] = premarket
        closes_by_symbol[symbol] = closes
        recognized_by_symbol[symbol] = recognized
        unresolved_by_symbol[symbol] = unresolved

    session_sets = {
        symbol: set(
            premarket_by_symbol[symbol][
                "local_date"
            ].unique()
        )
        for symbol in ALL_SYMBOLS
    }
    common_sessions = sorted(
        set.intersection(
            *session_sets.values()
        )
    )
    forward_sessions = [
        date
        for date in common_sessions
        if date > RESEARCH_CUTOFF_DATE
    ]

    session_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []

    for session_date in forward_sessions:
        grids = {
            symbol: session_grid(
                get_session(
                    premarket_by_symbol[symbol],
                    session_date,
                )
            )
            for symbol in ALL_SYMBOLS
        }
        complete = all(
            bool(
                grids[symbol][
                    "complete_session"
                ].iloc[0]
            )
            for symbol in ALL_SYMBOLS
        )
        if not complete:
            continue

        qqq_prior = prior_close(
            closes_by_symbol["QQQ"],
            session_date,
        )
        soxx_prior = prior_close(
            closes_by_symbol["SOXX"],
            session_date,
        )

        reasons: list[str] = []
        if qqq_prior is None:
            reasons.append(
                "QQQ_PRIOR_CLOSE_MISSING"
            )
        if soxx_prior is None:
            reasons.append(
                "SOXX_PRIOR_CLOSE_MISSING"
            )

        candidate = None
        if not reasons:
            candidate, signal_reasons = (
                build_candidate(
                    session_date,
                    grids["QQQ"],
                    grids["SOXX"],
                    qqq_prior,
                    soxx_prior,
                    recognized_by_symbol["QQQ"],
                    unresolved_by_symbol["QQQ"],
                    recognized_by_symbol["SOXX"],
                    unresolved_by_symbol["SOXX"],
                )
            )
            reasons.extend(signal_reasons)

        trade = None
        if candidate is not None and not reasons:
            trade, execution_reasons = (
                simulate_candidate(
                    candidate,
                    grids,
                    recognized_by_symbol,
                    unresolved_by_symbol,
                )
            )
            reasons.extend(execution_reasons)

        quarantined = bool(reasons)
        session_rows.append(
            {
                "session_date": session_date,
                "session_complete": True,
                "signal_generated": (
                    candidate is not None
                ),
                "trade_executed": (
                    trade is not None
                    and not quarantined
                ),
                "session_quarantined": quarantined,
                "quarantine_reasons": "|".join(
                    sorted(set(reasons))
                ),
            }
        )
        if candidate is not None:
            candidate_rows.append(candidate)
        if trade is not None and not quarantined:
            trade_rows.append(trade)

    sessions = pd.DataFrame(session_rows)
    candidates = pd.DataFrame(candidate_rows)
    trades = pd.DataFrame(trade_rows)

    if not sessions.empty:
        sessions = sessions.sort_values(
            "session_date",
            kind="mergesort",
        ).reset_index(drop=True)
    if not candidates.empty:
        candidates = candidates.sort_values(
            "session_date",
            kind="mergesort",
        ).reset_index(drop=True)
    if not trades.empty:
        trades = trades.sort_values(
            "session_date",
            kind="mergesort",
        ).reset_index(drop=True)

    evaluation = evaluate_forward(
        sessions,
        trades,
    )

    outputs = {
        "freeze_manifest": freeze_path,
        "sessions": result_dir
        / "v22_062pr_forward_sessions.csv",
        "candidates": result_dir
        / "v22_062pr_forward_candidates.csv",
        "trades": result_dir
        / "v22_062pr_forward_trades.csv",
        "recognized_events": result_dir
        / "v22_062pr_recognized_scale_events.csv",
        "unresolved_events": result_dir
        / "v22_062pr_unresolved_scale_events.csv",
        "summary": result_dir
        / "v22_062pr_summary.json",
    }

    sessions.to_csv(
        outputs["sessions"],
        index=False,
        encoding="utf-8-sig",
    )
    candidates.to_csv(
        outputs["candidates"],
        index=False,
        encoding="utf-8-sig",
    )
    trades.to_csv(
        outputs["trades"],
        index=False,
        encoding="utf-8-sig",
    )

    recognized_frames = []
    unresolved_frames = []
    for symbol in ALL_SYMBOLS:
        if not recognized_by_symbol[symbol].empty:
            recognized_frames.append(
                recognized_by_symbol[
                    symbol
                ].assign(symbol=symbol)
            )
        if not unresolved_by_symbol[symbol].empty:
            unresolved_frames.append(
                unresolved_by_symbol[
                    symbol
                ].assign(symbol=symbol)
            )

    recognized_all = (
        pd.concat(
            recognized_frames,
            ignore_index=True,
        )
        if recognized_frames
        else pd.DataFrame()
    )
    unresolved_all = (
        pd.concat(
            unresolved_frames,
            ignore_index=True,
        )
        if unresolved_frames
        else pd.DataFrame()
    )

    recognized_all.to_csv(
        outputs["recognized_events"],
        index=False,
        encoding="utf-8-sig",
    )
    unresolved_all.to_csv(
        outputs["unresolved_events"],
        index=False,
        encoding="utf-8-sig",
    )

    summary = {
        "version": VERSION,
        "final_status": "PASS",
        **evaluation,
        "v22_062pb_validated": True,
        "frozen_spec_version": SPEC_VERSION,
        "frozen_spec_sha256": (
            freeze["frozen_spec_sha256"]
        ),
        "research_cutoff_date": (
            RESEARCH_CUTOFF_DATE
        ),
        "forward_holdout_only": True,
        "rule_change_requires_reset": True,
        "sole_exit_variant": "PREMARKET_0925",
        "canonical_partition_count_indexed": int(
            len(partitions)
        ),
        "canonical_partition_count_read": int(
            len(paths_read)
        ),
        "full_582_partition_reread": False,
        "historical_pre_cutoff_outcomes_used_for_qualification": False,
        "parameter_sweep_executed": False,
        "threshold_optimization_executed": False,
        "strategy_rule_change_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "new_market_data_cache_created": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
        "outputs": {
            name: str(path)
            for name, path in outputs.items()
        },
    }
    atomic_json(
        outputs["summary"],
        summary,
    )

    print(
        "=============================================="
    )
    print(
        " V22.062PR premarket forward replication"
    )
    print(
        "=============================================="
    )
    print_summary(evaluation)

    print()
    print("FINAL_STATUS=PASS")
    print(
        f"FINAL_DECISION="
        f"{evaluation['final_decision']}"
    )
    print("V22_062PB_VALIDATED=True")
    print(
        f"RESEARCH_CUTOFF_DATE="
        f"{RESEARCH_CUTOFF_DATE}"
    )
    print("FORWARD_HOLDOUT_ONLY=True")
    print("RULE_CHANGE_REQUIRES_RESET=True")
    print("SOLE_EXIT_VARIANT=PREMARKET_0925")
    print(
        f"COMPLETED_HOLDOUT_SESSION_COUNT="
        f"{evaluation['completed_holdout_session_count']}"
    )
    print(
        f"FORWARD_TRADE_COUNT="
        f"{evaluation['forward_trade_count']}"
    )
    print(
        f"INTERIM_EVALUABLE="
        f"{evaluation['interim_evaluable']}"
    )
    print(
        f"FINAL_EVALUABLE="
        f"{evaluation['final_evaluable']}"
    )
    print(
        f"FORWARD_REPLICATION_PASS="
        f"{evaluation['forward_replication_pass']}"
    )
    print(
        f"CANONICAL_PARTITION_COUNT_READ="
        f"{len(paths_read)}"
    )
    print("FULL_582_PARTITION_REREAD=False")
    print(
        "HISTORICAL_PRE_CUTOFF_OUTCOMES_USED_FOR_QUALIFICATION=False"
    )
    print("PARAMETER_SWEEP_EXECUTED=False")
    print("THRESHOLD_OPTIMIZATION_EXECUTED=False")
    print("STRATEGY_RULE_CHANGE_EXECUTED=False")
    print("CANONICAL_FILES_MODIFIED=False")
    print("RAW_FILES_MODIFIED=False")
    print("NEW_MARKET_DATA_CACHE_CREATED=False")
    print("BROKER_ACTION_ALLOWED=False")
    print("PAPER_TRADING_ALLOWED=False")
    print("OFFICIAL_ADOPTION_ALLOWED=False")
    print(
        f"SUMMARY_PATH="
        f"{outputs['summary']}"
    )
    print(
        f"RESULT_DIRECTORY={result_dir}"
    )
    return summary


def parse_args(
    argv: list[str] | None = None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--v22-062pb-root",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.062PB_FAST3_CORPORATE_ACTION_SAFE_PRICE_NORMALIZATION_R1"
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
            r"\V22.062PR_FAST3_PREMARKET_INDEPENDENT_FORWARD_REPLICATION_R1"
        ),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
    )
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
) -> int:
    args = parse_args(argv)
    if not args.execute:
        print(
            "FINAL_STATUS="
            "BLOCKED_EXECUTE_FLAG_REQUIRED"
        )
        return 2
    try:
        run_replication(
            v22_062pb_root=Path(
                args.v22_062pb_root
            ),
            canonical_root=Path(
                args.canonical_root
            ),
            result_dir=Path(
                args.result_dir
            ),
        )
        return 0
    except Exception as exc:
        print("FINAL_STATUS=FAIL")
        print(
            f"ERROR_TYPE={type(exc).__name__}"
        )
        print(f"ERROR={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
