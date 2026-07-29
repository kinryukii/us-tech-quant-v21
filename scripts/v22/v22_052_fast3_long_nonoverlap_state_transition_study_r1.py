#!/usr/bin/env python
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

VERSION = "V22.052_FAST3_LONG_NONOVERLAP_STATE_TRANSITION_STUDY_R1"
SIGNAL_SYMBOLS = ("QQQ", "SOXX")
EXECUTION_SYMBOLS = ("TQQQ", "SOXL")
ALL_SYMBOLS = SIGNAL_SYMBOLS + EXECUTION_SYMBOLS
HORIZONS = (30, 60, 120)
ROUND_TRIP_COST = 0.001
RTH_START_MINUTE = 570
RTH_END_MINUTE = 959
SIGNAL_START_MINUTE = 585
SIGNAL_END_MINUTE = 930
FORCED_EXIT_MINUTE = 955
COOLDOWN_MINUTES = 30
MAX_TRADES_PER_DAY = 3
MIN_PIT_BASELINE_COUNT = 20
BOOTSTRAP_REPETITIONS = 2000
BOOTSTRAP_BLOCK_DAYS = 5
MASTER_SEED = 2026072601
PERIODS = (
    "2018-2022_DEVELOPMENT",
    "2023-2024_VALIDATION",
    "2025-2026_YTD_CONFIRMATION",
)


class StudyError(RuntimeError):
    pass


@dataclass
class RunningStats:
    count: int = 0
    total: float = 0.0
    total_sq: float = 0.0

    def add(self, value: float) -> None:
        if np.isfinite(value):
            self.count += 1
            self.total += float(value)
            self.total_sq += float(value) ** 2

    @property
    def mean(self) -> float:
        return self.total / self.count if self.count else np.nan

    @property
    def std(self) -> float:
        if self.count <= 1:
            return np.nan
        var = (self.total_sq - self.total**2 / self.count) / (self.count - 1)
        return math.sqrt(max(var, 0.0))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def utc_z(value: Any) -> str:
    ts = pd.Timestamp(value)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer, np.floating)):
        if isinstance(value, np.floating) and not np.isfinite(value):
            return None
        return value.item()
    if isinstance(value, (pd.Timestamp, datetime)):
        return utc_z(value)
    raise TypeError(type(value).__name__)


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def find_column(frame: pd.DataFrame, candidates: Iterable[str]) -> str:
    mapping = {str(c).lower(): str(c) for c in frame.columns}
    for candidate in candidates:
        if candidate.lower() in mapping:
            return mapping[candidate.lower()]
    raise StudyError(f"Missing columns {list(candidates)}; got {list(frame.columns)}")


def normalize_timestamp_utc(series: pd.Series) -> pd.Series:
    if isinstance(series.dtype, pd.DatetimeTZDtype):
        converted = series.dt.tz_convert("UTC")
    elif pd.api.types.is_datetime64_dtype(series.dtype):
        raise StudyError("timestamp_utc must be timezone-aware UTC")
    else:
        converted = pd.to_datetime(series, utc=True, errors="raise")
    return pd.Series(pd.array(converted, dtype="datetime64[ns, UTC]"), index=series.index, name=series.name)


def validate_v22_051(summary: Mapping[str, Any]) -> None:
    expected = {
        "final_status": "PASS",
        "event_study_completed": True,
        "entry_exit_optimization_executed": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }
    failed = [f"{k}={summary.get(k)!r}" for k, v in expected.items() if summary.get(k) != v]
    if failed:
        raise StudyError("V22.051 validation failed: " + ", ".join(failed))


def symbol_month_from_path(path: Path) -> tuple[str, str, str]:
    symbol = year = month = None
    for part in path.parts:
        m = re.fullmatch(r"symbol=(.+)", part, re.I)
        if m:
            symbol = m.group(1).upper()
        m = re.fullmatch(r"year=(\d{4})", part, re.I)
        if m:
            year = m.group(1)
        m = re.fullmatch(r"month=(\d{1,2})", part, re.I)
        if m:
            month = f"{int(m.group(1)):02d}"
    if not all((symbol, year, month)):
        raise StudyError(f"Cannot parse partition path: {path}")
    return symbol, year, month


def index_canonical(root: Path) -> dict[tuple[str, str, str], Path]:
    out: dict[tuple[str, str, str], Path] = {}
    for path in sorted(root.rglob("*.parquet")):
        key = symbol_month_from_path(path)
        if key[0] not in ALL_SYMBOLS:
            continue
        if key in out:
            raise StudyError(f"Duplicate partition {key}")
        out[key] = path
    return out


def load_rth_partition(path: Path) -> pd.DataFrame:
    raw = pd.read_parquet(path)
    if raw.empty:
        return pd.DataFrame(columns=["timestamp_utc", "timestamp_et", "trade_date", "open", "high", "low", "close", "volume"])
    ts = normalize_timestamp_utc(raw[find_column(raw, ("timestamp_utc",))])
    et = ts.dt.tz_convert("America/New_York")
    minute = et.dt.hour * 60 + et.dt.minute
    mask = (minute >= RTH_START_MINUTE) & (minute <= RTH_END_MINUTE)
    frame = pd.DataFrame({
        "timestamp_utc": ts.loc[mask],
        "timestamp_et": et.loc[mask],
        "trade_date": et.loc[mask].dt.strftime("%Y-%m-%d"),
        "open": pd.to_numeric(raw.loc[mask, find_column(raw, ("open",))], errors="coerce"),
        "high": pd.to_numeric(raw.loc[mask, find_column(raw, ("high",))], errors="coerce"),
        "low": pd.to_numeric(raw.loc[mask, find_column(raw, ("low",))], errors="coerce"),
        "close": pd.to_numeric(raw.loc[mask, find_column(raw, ("close",))], errors="coerce"),
        "volume": pd.to_numeric(raw.loc[mask, find_column(raw, ("volume",))], errors="coerce").fillna(0.0),
    }).dropna(subset=["timestamp_utc", "open", "high", "low", "close"])
    frame = frame.sort_values("timestamp_utc", kind="mergesort").reset_index(drop=True)
    if frame["timestamp_utc"].duplicated().any():
        raise StudyError(f"Duplicate RTH timestamp in {path}")
    return frame


def add_daily_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.set_index("timestamp_utc").copy()
    vol = result["volume"].clip(lower=0)
    typical = (result["high"] + result["low"] + result["close"]) / 3.0
    cum_vol = vol.groupby(result["trade_date"], sort=False).cumsum()
    cum_val = (typical * vol).groupby(result["trade_date"], sort=False).cumsum()
    fallback = result.groupby("trade_date", sort=False)["close"].expanding().mean().reset_index(level=0, drop=True)
    result["vwap"] = cum_val.divide(cum_vol.where(cum_vol > 0)).fillna(fallback)
    ret = pd.Series(np.nan, index=result.index, dtype=float)
    for _, day in result.groupby("trade_date", sort=False):
        close = day["close"]
        prior = close.reindex(close.index - pd.Timedelta(minutes=15)).to_numpy(dtype=float)
        current = close.to_numpy(dtype=float)
        values = np.full(len(day), np.nan)
        valid = np.isfinite(prior) & np.isfinite(current) & (prior > 0)
        values[valid] = current[valid] / prior[valid] - 1.0
        ret.loc[day.index] = values
    result["ret_15m"] = ret
    return result


def build_aligned_signal_frame(qqq: pd.DataFrame, soxx: pd.DataFrame) -> pd.DataFrame:
    q = add_daily_indicators(qqq)[["timestamp_et", "trade_date", "close", "vwap", "ret_15m"]].rename(columns={
        "timestamp_et": "signal_timestamp_et", "close": "qqq_close", "vwap": "qqq_vwap", "ret_15m": "qqq_ret_15m"
    })
    s = add_daily_indicators(soxx)[["trade_date", "close", "vwap", "ret_15m"]].rename(columns={
        "trade_date": "soxx_trade_date", "close": "soxx_close", "vwap": "soxx_vwap", "ret_15m": "soxx_ret_15m"
    })
    merged = q.join(s, how="inner")
    merged = merged.loc[merged["trade_date"] == merged["soxx_trade_date"]].copy()
    minute = merged["signal_timestamp_et"].dt.hour * 60 + merged["signal_timestamp_et"].dt.minute
    return merged.loc[(minute >= SIGNAL_START_MINUTE) & (minute <= SIGNAL_END_MINUTE)].sort_index()


def long_condition_and_branch(row: pd.Series) -> tuple[bool, str | None]:
    vals = [row[k] for k in ("qqq_ret_15m", "soxx_ret_15m", "qqq_close", "qqq_vwap", "soxx_close", "soxx_vwap")]
    if not all(np.isfinite(v) for v in vals):
        return False, None
    condition = (
        row["qqq_ret_15m"] > 0 and row["soxx_ret_15m"] > 0
        and row["qqq_close"] > row["qqq_vwap"]
        and row["soxx_close"] > row["soxx_vwap"]
    )
    if not condition:
        return False, None
    return True, ("SOXL" if row["soxx_ret_15m"] > row["qqq_ret_15m"] else "TQQQ")


def state_transition_candidates(aligned: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for trade_date, day in aligned.groupby("trade_date", sort=True):
        previous = False
        for timestamp_utc, row in day.sort_index().iterrows():
            current, branch = long_condition_and_branch(row)
            if current and not previous:
                et = pd.Timestamp(row["signal_timestamp_et"])
                rows.append({
                    "signal_timestamp_utc": pd.Timestamp(timestamp_utc),
                    "signal_timestamp_et": et,
                    "trade_date": str(trade_date),
                    "weekday": int(et.weekday()),
                    "signal_minute_et": int(et.hour * 60 + et.minute),
                    "execution_symbol": branch,
                    "qqq_ret_15m": float(row["qqq_ret_15m"]),
                    "soxx_ret_15m": float(row["soxx_ret_15m"]),
                    "qqq_vwap_deviation_bps": (float(row["qqq_close"]) / float(row["qqq_vwap"]) - 1) * 10000,
                    "soxx_vwap_deviation_bps": (float(row["soxx_close"]) / float(row["soxx_vwap"]) - 1) * 10000,
                })
            previous = current
    return pd.DataFrame(rows)


def study_period(year: int) -> str:
    if 2018 <= year <= 2022:
        return PERIODS[0]
    if 2023 <= year <= 2024:
        return PERIODS[1]
    if year >= 2025:
        return PERIODS[2]
    return "PRE_2018_REFERENCE"


def time_bucket(ts: pd.Timestamp) -> str:
    minute = ts.hour * 60 + ts.minute
    if 585 <= minute <= 629:
        return "09:45-10:29"
    if 630 <= minute <= 719:
        return "10:30-11:59"
    if 720 <= minute <= 839:
        return "12:00-13:59"
    if 840 <= minute <= 930:
        return "14:00-15:30"
    return "OUTSIDE"


def schedule_nonoverlap_trades(candidates: pd.DataFrame, executions: Mapping[str, pd.DataFrame], horizon: int) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for trade_date, day in candidates.groupby("trade_date", sort=True):
        active_until = cooldown_until = None
        count = 0
        indexed = {symbol: frame.loc[frame["trade_date"] == trade_date].set_index("timestamp_utc", drop=False) for symbol, frame in executions.items()}
        for candidate in day.sort_values("signal_timestamp_utc").to_dict(orient="records"):
            if count >= MAX_TRADES_PER_DAY:
                break
            signal_ts = pd.Timestamp(candidate["signal_timestamp_utc"])
            if active_until is not None and signal_ts < active_until:
                continue
            if cooldown_until is not None and signal_ts < cooldown_until:
                continue
            entry_ts = signal_ts + pd.Timedelta(minutes=1)
            exit_ts = entry_ts + pd.Timedelta(minutes=horizon)
            table = indexed[str(candidate["execution_symbol"])]
            if entry_ts not in table.index or exit_ts not in table.index:
                continue
            entry = table.loc[entry_ts]
            exit_ = table.loc[exit_ts]
            if isinstance(entry, pd.DataFrame) or isinstance(exit_, pd.DataFrame):
                raise StudyError("Duplicate execution timestamp")
            exit_et = pd.Timestamp(exit_["timestamp_et"])
            if exit_et.hour * 60 + exit_et.minute > FORCED_EXIT_MINUTE:
                continue
            entry_price, exit_price = float(entry["open"]), float(exit_["close"])
            if not (np.isfinite(entry_price) and np.isfinite(exit_price) and entry_price > 0 and exit_price > 0):
                continue
            entry_et = pd.Timestamp(entry["timestamp_et"])
            gross = exit_price / entry_price - 1.0
            rows.append({
                **candidate,
                "entry_timestamp_utc": entry_ts,
                "entry_timestamp_et": entry_et,
                "entry_minute_et": int(entry_et.hour * 60 + entry_et.minute),
                "exit_timestamp_utc": exit_ts,
                "exit_timestamp_et": exit_et,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "gross_return": gross,
                "net_return": gross - ROUND_TRIP_COST,
                "horizon_minutes": horizon,
                "calendar_year": entry_et.year,
                "study_period": study_period(entry_et.year),
                "time_bucket": time_bucket(pd.Timestamp(candidate["signal_timestamp_et"])),
                "trade_number_in_day": count + 1,
            })
            count += 1
            active_until = exit_ts
            cooldown_until = exit_ts + pd.Timedelta(minutes=COOLDOWN_MINUTES)
    return pd.DataFrame(rows)


def compute_unconditional_day_returns(day: pd.DataFrame, horizon: int) -> pd.DataFrame:
    if day.empty:
        return pd.DataFrame()
    table = day.set_index("timestamp_utc", drop=False)
    rows = []
    for entry_ts, entry in table.iterrows():
        exit_ts = pd.Timestamp(entry_ts) + pd.Timedelta(minutes=horizon)
        if exit_ts not in table.index:
            continue
        exit_ = table.loc[exit_ts]
        if isinstance(exit_, pd.DataFrame):
            raise StudyError("Duplicate unconditional timestamp")
        exit_et = pd.Timestamp(exit_["timestamp_et"])
        if exit_et.hour * 60 + exit_et.minute > FORCED_EXIT_MINUTE:
            continue
        entry_price, exit_price = float(entry["open"]), float(exit_["close"])
        if not (np.isfinite(entry_price) and np.isfinite(exit_price) and entry_price > 0 and exit_price > 0):
            continue
        entry_et = pd.Timestamp(entry["timestamp_et"])
        rows.append({
            "weekday": int(entry_et.weekday()),
            "entry_minute_et": int(entry_et.hour * 60 + entry_et.minute),
            "horizon_minutes": horizon,
            "net_return": exit_price / entry_price - 1.0 - ROUND_TRIP_COST,
        })
    return pd.DataFrame(rows)


def baseline_key(symbol: str, weekday: int, entry_minute: int, horizon: int) -> tuple[str, int, int, int]:
    return str(symbol), int(weekday), int(entry_minute), int(horizon)


def assign_pit_baseline(trades: pd.DataFrame, stats: Mapping[tuple[str, int, int, int], RunningStats]) -> pd.DataFrame:
    out = trades.copy()
    counts, means = [], []
    for row in out.itertuples(index=False):
        s = stats.get(baseline_key(row.execution_symbol, row.weekday, row.entry_minute_et, row.horizon_minutes), RunningStats())
        counts.append(s.count)
        means.append(s.mean if s.count else np.nan)
    out["matched_pit_count"] = counts
    out["matched_unconditional_pit_net"] = means
    out["signal_excess_pit_net"] = out["net_return"] - out["matched_unconditional_pit_net"]
    out["pit_baseline_eligible"] = out["matched_pit_count"] >= MIN_PIT_BASELINE_COUNT
    return out


def update_baselines(day_returns: pd.DataFrame, symbol: str, prior: dict, global_: dict) -> None:
    for row in day_returns.itertuples(index=False):
        key = baseline_key(symbol, row.weekday, row.entry_minute_et, row.horizon_minutes)
        prior.setdefault(key, RunningStats()).add(row.net_return)
        global_.setdefault(key, RunningStats()).add(row.net_return)


def assign_loo(trades: pd.DataFrame, global_: Mapping[tuple[str, int, int, int], RunningStats]) -> pd.DataFrame:
    out = trades.copy()
    counts, means = [], []
    for row in out.itertuples(index=False):
        s = global_.get(baseline_key(row.execution_symbol, row.weekday, row.entry_minute_et, row.horizon_minutes), RunningStats())
        count = max(s.count - 1, 0)
        mean = (s.total - float(row.net_return)) / count if count else np.nan
        counts.append(count)
        means.append(mean)
    out["matched_loo_count"] = counts
    out["matched_unconditional_loo_net"] = means
    out["signal_excess_loo_net"] = out["net_return"] - out["matched_unconditional_loo_net"]
    return out


def circular_block_bootstrap_mean(values: np.ndarray, repetitions: int, block_length: int, seed: int) -> tuple[float, float, float]:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return np.nan, np.nan, np.nan
    if values.size == 1:
        value = float(values[0])
        return value, value, value
    rng = np.random.default_rng(seed)
    n = values.size
    block_length = min(max(block_length, 1), n)
    blocks = math.ceil(n / block_length)
    offsets = np.arange(block_length)
    means = np.empty(repetitions)
    for i in range(repetitions):
        starts = rng.integers(0, n, size=blocks)
        idx = ((starts[:, None] + offsets[None, :]) % n).ravel()[:n]
        means[i] = values[idx].mean()
    return float(values.mean()), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def build_summaries(trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    eligible = trades.loc[trades["pit_baseline_eligible"] & trades["signal_excess_pit_net"].notna()].copy()
    daily_rows = []
    for keys, group in eligible.groupby(["execution_symbol", "horizon_minutes", "study_period", "trade_date"], sort=True):
        symbol, horizon, period, trade_date = keys
        daily_rows.append({
            "execution_symbol": symbol,
            "horizon_minutes": int(horizon),
            "study_period": period,
            "trade_date": trade_date,
            "trade_count": len(group),
            "daily_compound_net_return": float(np.prod(1 + group["net_return"].to_numpy()) - 1),
            "daily_compound_excess_pit": float(np.prod(1 + group["signal_excess_pit_net"].to_numpy()) - 1),
        })
    daily = pd.DataFrame(daily_rows)

    period_rows, bootstrap_rows = [], []
    for keys, group in trades.groupby(["execution_symbol", "horizon_minutes", "study_period"], sort=True):
        symbol, horizon, period = keys
        pit = group.loc[group["pit_baseline_eligible"] & group["signal_excess_pit_net"].notna()]
        net = group["net_return"]
        excess = pit["signal_excess_pit_net"]
        dg = daily.loc[(daily["execution_symbol"] == symbol) & (daily["horizon_minutes"] == horizon) & (daily["study_period"] == period)].sort_values("trade_date")
        seed = MASTER_SEED + int(horizon) * 100 + (1 if symbol == "SOXL" else 2) + (PERIODS.index(period) * 10 if period in PERIODS else 0)
        point, lower, upper = circular_block_bootstrap_mean(dg["daily_compound_excess_pit"].to_numpy() if not dg.empty else np.empty(0), BOOTSTRAP_REPETITIONS, BOOTSTRAP_BLOCK_DAYS, seed)
        gate = (
            len(group) >= 500 and len(pit) >= 500
            and net.mean() > 0 and net.median() > 0 and (net > 0).mean() > 0.50
            and excess.mean() > 0 and excess.median() > 0
            and (not np.isfinite(lower) or lower >= -0.0005)
        )
        period_rows.append({
            "execution_symbol": symbol,
            "horizon_minutes": int(horizon),
            "study_period": period,
            "trade_count": len(group),
            "pit_eligible_trade_count": len(pit),
            "trade_day_count": group["trade_date"].nunique(),
            "mean_net_return": net.mean(),
            "median_net_return": net.median(),
            "positive_rate": (net > 0).mean(),
            "mean_excess_pit": excess.mean() if len(excess) else np.nan,
            "median_excess_pit": excess.median() if len(excess) else np.nan,
            "excess_pit_positive_rate": (excess > 0).mean() if len(excess) else np.nan,
            "mean_excess_loo": group["signal_excess_loo_net"].mean(),
            "period_gate_pass": bool(gate),
        })
        bootstrap_rows.append({
            "execution_symbol": symbol,
            "horizon_minutes": int(horizon),
            "study_period": period,
            "daily_observation_count": len(dg),
            "bootstrap_repetitions": BOOTSTRAP_REPETITIONS,
            "block_length_trade_days": BOOTSTRAP_BLOCK_DAYS,
            "mean_daily_excess_pit": point,
            "ci95_lower": lower,
            "ci95_upper": upper,
        })
    period = pd.DataFrame(period_rows)
    bootstrap = pd.DataFrame(bootstrap_rows)

    final_rows = []
    for (symbol, horizon), group in period.groupby(["execution_symbol", "horizon_minutes"], sort=True):
        mapping = {r.study_period: bool(r.period_gate_pass) for r in group.itertuples(index=False)}
        qualified = all(mapping.get(p, False) for p in PERIODS)
        final_rows.append({
            "execution_symbol": symbol,
            "horizon_minutes": int(horizon),
            "development_pass": mapping.get(PERIODS[0], False),
            "validation_pass": mapping.get(PERIODS[1], False),
            "confirmation_pass": mapping.get(PERIODS[2], False),
            "candidate_qualified_for_v22_053": qualified,
        })
    final = pd.DataFrame(final_rows)

    year = trades.groupby(["execution_symbol", "horizon_minutes", "calendar_year"], sort=True).agg(
        trade_count=("net_return", "size"),
        mean_net_return=("net_return", "mean"),
        median_net_return=("net_return", "median"),
        positive_rate=("net_return", lambda s: float((s > 0).mean())),
        mean_excess_pit=("signal_excess_pit_net", "mean"),
    ).reset_index()
    bucket = trades.groupby(["execution_symbol", "horizon_minutes", "time_bucket"], sort=True).agg(
        trade_count=("net_return", "size"),
        mean_net_return=("net_return", "mean"),
        median_net_return=("net_return", "median"),
        positive_rate=("net_return", lambda s: float((s > 0).mean())),
        mean_excess_pit=("signal_excess_pit_net", "mean"),
    ).reset_index()
    return daily, period, bootstrap, final, year, bucket


def baseline_table(global_: Mapping[tuple[str, int, int, int], RunningStats]) -> pd.DataFrame:
    rows = []
    for (symbol, weekday, minute, horizon), s in sorted(global_.items()):
        rows.append({
            "execution_symbol": symbol,
            "weekday": weekday,
            "entry_minute_et": minute,
            "horizon_minutes": horizon,
            "observation_count": s.count,
            "mean_unconditional_net_return": s.mean,
            "std_unconditional_net_return": s.std,
        })
    return pd.DataFrame(rows)


def run_study(v22_051_summary_path: Path, canonical_root: Path, result_dir: Path) -> dict[str, Any]:
    if not v22_051_summary_path.exists():
        raise StudyError(f"Missing V22.051 summary: {v22_051_summary_path}")
    v22_051 = json.loads(v22_051_summary_path.read_text(encoding="utf-8-sig"))
    validate_v22_051(v22_051)

    index = index_canonical(canonical_root)
    months = sorted({(year, month) for symbol, year, month in index if symbol in ALL_SYMBOLS})
    missing = [(symbol, year, month) for year, month in months for symbol in ALL_SYMBOLS if (symbol, year, month) not in index]
    if not months or missing:
        raise StudyError(f"Missing required partitions: {missing[:10]}")

    paths = [index[(symbol, year, month)] for year, month in months for symbol in ALL_SYMBOLS]
    before = {str(p): sha256_file(p) for p in paths}
    prior: dict[tuple[str, int, int, int], RunningStats] = {}
    global_: dict[tuple[str, int, int, int], RunningStats] = {}
    trade_chunks: list[pd.DataFrame] = []
    total_candidates = 0
    total_trades = 0

    for i, (year, month) in enumerate(months, 1):
        frames = {symbol: load_rth_partition(index[(symbol, year, month)]) for symbol in ALL_SYMBOLS}
        candidates = state_transition_candidates(build_aligned_signal_frame(frames["QQQ"], frames["SOXX"]))
        total_candidates += len(candidates)
        scheduled_parts = [schedule_nonoverlap_trades(candidates, {"TQQQ": frames["TQQQ"], "SOXL": frames["SOXL"]}, h) for h in HORIZONS]
        scheduled_parts = [x for x in scheduled_parts if not x.empty]
        month_trades = pd.concat(scheduled_parts, ignore_index=True) if scheduled_parts else pd.DataFrame()

        dates = sorted(set(frames["TQQQ"]["trade_date"]) | set(frames["SOXL"]["trade_date"]))
        for trade_date in dates:
            day_trades = month_trades.loc[month_trades["trade_date"] == trade_date].copy() if not month_trades.empty else pd.DataFrame()
            if not day_trades.empty:
                assigned = assign_pit_baseline(day_trades, prior)
                trade_chunks.append(assigned)
                total_trades += len(assigned)
            for symbol in EXECUTION_SYMBOLS:
                day = frames[symbol].loc[frames[symbol]["trade_date"] == trade_date]
                for horizon in HORIZONS:
                    values = compute_unconditional_day_returns(day, horizon)
                    if not values.empty:
                        update_baselines(values, symbol, prior, global_)
        print(f"[NONOVERLAP] month={year}-{month} progress={i}/{len(months)} month_candidates={len(candidates)} total_candidates={total_candidates} total_trades={total_trades}", flush=True)

    if not trade_chunks:
        raise StudyError("No trades generated")
    trades = assign_loo(pd.concat(trade_chunks, ignore_index=True), global_)
    trades = trades.sort_values(["entry_timestamp_utc", "horizon_minutes", "execution_symbol"], kind="mergesort").reset_index(drop=True)
    if trades.duplicated(["entry_timestamp_utc", "horizon_minutes", "execution_symbol"]).any():
        raise StudyError("Duplicate trade rows")

    daily, period, bootstrap, final, year_summary, bucket_summary = build_summaries(trades)
    baselines = baseline_table(global_)
    qualified = final.loc[final["candidate_qualified_for_v22_053"]]
    ready = not qualified.empty

    result_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "trades_parquet": result_dir / "v22_052_trades.parquet",
        "trades_csv": result_dir / "v22_052_trades.csv",
        "daily": result_dir / "v22_052_daily_returns.csv",
        "period": result_dir / "v22_052_candidate_period_summary.csv",
        "bootstrap": result_dir / "v22_052_block_bootstrap_summary.csv",
        "final": result_dir / "v22_052_final_candidate_table.csv",
        "year": result_dir / "v22_052_year_summary.csv",
        "bucket": result_dir / "v22_052_time_bucket_summary.csv",
        "baseline": result_dir / "v22_052_matched_unconditional_baseline.csv",
        "summary": result_dir / "v22_052_summary.json",
        "manifest": result_dir / "v22_052_run_manifest.json",
    }
    trades.to_parquet(outputs["trades_parquet"], index=False)
    trades.to_csv(outputs["trades_csv"], index=False, encoding="utf-8-sig")
    daily.to_csv(outputs["daily"], index=False, encoding="utf-8-sig")
    period.to_csv(outputs["period"], index=False, encoding="utf-8-sig")
    bootstrap.to_csv(outputs["bootstrap"], index=False, encoding="utf-8-sig")
    final.to_csv(outputs["final"], index=False, encoding="utf-8-sig")
    year_summary.to_csv(outputs["year"], index=False, encoding="utf-8-sig")
    bucket_summary.to_csv(outputs["bucket"], index=False, encoding="utf-8-sig")
    baselines.to_csv(outputs["baseline"], index=False, encoding="utf-8-sig")

    after = {str(p): sha256_file(p) for p in paths}
    if before != after:
        raise StudyError("Canonical changed during read-only study")

    summary = {
        "version": VERSION,
        "final_status": "PASS",
        "final_decision": "LONG_NONOVERLAP_CANDIDATE_QUALIFIED_FOR_V22_053" if ready else "NO_LONG_NONOVERLAP_CANDIDATE_QUALIFIED",
        "v22_051_validated": True,
        "v22_051_summary_path": str(v22_051_summary_path),
        "v22_051_summary_sha256": sha256_file(v22_051_summary_path),
        "canonical_file_count_read": len(paths),
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "open_d_called": False,
        "history_download_executed": False,
        "short_branch_removed": True,
        "state_transition_only": True,
        "nonoverlap_enforced": True,
        "cooldown_minutes": COOLDOWN_MINUTES,
        "max_trades_per_day": MAX_TRADES_PER_DAY,
        "horizons_minutes": list(HORIZONS),
        "round_trip_cost": ROUND_TRIP_COST,
        "state_transition_candidate_count": int(total_candidates),
        "trade_count": int(len(trades)),
        "trade_count_by_symbol_horizon": {f"{s}_{h}": int(len(g)) for (s, h), g in trades.groupby(["execution_symbol", "horizon_minutes"], sort=True)},
        "qualified_candidates": qualified.to_dict(orient="records"),
        "data_ready_for_v22_053": bool(ready),
        "entry_filter_optimization_executed": False,
        "exit_optimization_executed": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }
    atomic_json(outputs["summary"], summary)
    atomic_json(outputs["manifest"], {
        "version": VERSION,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "outputs": {k: str(v) for k, v in outputs.items()},
        "read_only_guards": {"canonical_files_modified": False, "raw_files_modified": False, "open_d_called": False, "history_download_executed": False},
        "policy_gates": {"entry_filter_optimization_executed": False, "exit_optimization_executed": False, "broker_action_allowed": False, "paper_trading_allowed": False, "official_adoption_allowed": False},
    })
    return {"summary": summary, "outputs": outputs, "result_dir": result_dir}


def print_final(result: Mapping[str, Any]) -> None:
    s = result["summary"]
    print(f"FINAL_STATUS={s['final_status']}")
    print(f"FINAL_DECISION={s['final_decision']}")
    print("FILES_MODIFIED=None")
    print("V22_051_VALIDATED=True")
    print("CANONICAL_FILES_MODIFIED=False")
    print("RAW_FILES_MODIFIED=False")
    print("OPEN_D_CALLED=False")
    print("HISTORY_DOWNLOAD_EXECUTED=False")
    print("SHORT_BRANCH_REMOVED=True")
    print("STATE_TRANSITION_ONLY=True")
    print("NONOVERLAP_ENFORCED=True")
    print(f"STATE_TRANSITION_CANDIDATE_COUNT={s['state_transition_candidate_count']}")
    print(f"TRADE_COUNT={s['trade_count']}")
    print("TRADE_COUNT_BY_SYMBOL_HORIZON=" + json.dumps(s["trade_count_by_symbol_horizon"], ensure_ascii=False))
    print("QUALIFIED_CANDIDATES=" + json.dumps(s["qualified_candidates"], ensure_ascii=False))
    print(f"DATA_READY_FOR_V22_053={s['data_ready_for_v22_053']}")
    print("ENTRY_FILTER_OPTIMIZATION_EXECUTED=False")
    print("EXIT_OPTIMIZATION_EXECUTED=False")
    print("BROKER_ACTION_ALLOWED=False")
    print("PAPER_TRADING_ALLOWED=False")
    print("OFFICIAL_ADOPTION_ALLOWED=False")
    print(f"SUMMARY_PATH={result['outputs']['summary']}")
    print(f"RESULT_DIRECTORY={result['result_dir']}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v22-051-summary", default=r"D:\us-tech-quant-results\v22\V22.051_FAST3_RTH_BASELINE_EVENT_STUDY_R1\v22_051_summary.json")
    parser.add_argument("--canonical-root", default=r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical")
    parser.add_argument("--result-dir", default=r"D:\us-tech-quant-results\v22\V22.052_FAST3_LONG_NONOVERLAP_STATE_TRANSITION_STUDY_R1")
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.execute:
        print("FINAL_STATUS=BLOCKED_EXECUTE_FLAG_REQUIRED")
        return 2
    try:
        result = run_study(Path(args.v22_051_summary), Path(args.canonical_root), Path(args.result_dir))
        print_final(result)
        return 0
    except Exception as exc:
        print("FINAL_STATUS=FAIL")
        print(f"ERROR_TYPE={type(exc).__name__}")
        print(f"ERROR={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
