#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

VERSION = "V22.055_FAST3_MULTIFACT_DATA_AND_FACTOR_PREFLIGHT_R1"
ETF_SYMBOLS = ("QQQ", "SOXX", "TQQQ", "SQQQ", "SOXL", "SOXS")
RTH_START = 9 * 60 + 30
RTH_END = 15 * 60 + 59
COMMON_VIX_ROOTS = (
    r"D:\us-tech-quant-data\fast3\vix",
    r"D:\us-tech-quant-data\vix",
    r"D:\us-tech-quant-data\market\vix",
    r"D:\us-tech-quant-data\indices\vix",
    r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical\symbol=VIX",
    r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical\symbol=US.VIX",
)

class PreflightError(RuntimeError):
    pass


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def json_default(value: Any) -> Any:
    if isinstance(value, Path): return str(value)
    if isinstance(value, (np.integer, np.floating)):
        if isinstance(value, np.floating) and not np.isfinite(value): return None
        return value.item()
    if isinstance(value, (pd.Timestamp, datetime)): return value.isoformat()
    raise TypeError(type(value).__name__)


def validate_v22_054(summary: Mapping[str, Any]) -> None:
    expected = {
        "final_status": "PASS",
        "final_decision": "FAST3_SIGNAL_FAMILY_TERMINATED_NOT_ROBUST",
        "fast3_signal_family_robust": False,
        "fast3_development_continue": False,
        "paper_trading_allowed": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
    }
    failed = [f"{k}: expected {v!r}, got {summary.get(k)!r}" for k, v in expected.items() if summary.get(k) != v]
    if failed:
        raise PreflightError("V22.054 validation failed: " + "; ".join(failed))


def find_column(columns: Iterable[str], candidates: Iterable[str], required: bool = True) -> str | None:
    mapping = {str(c).strip().lower(): str(c) for c in columns}
    for candidate in candidates:
        if candidate.lower() in mapping:
            return mapping[candidate.lower()]
    if required:
        raise PreflightError(f"Missing column; expected one of {list(candidates)}, got {list(columns)}")
    return None


def supported_files(root: Path) -> list[Path]:
    if root.is_file() and root.suffix.lower() in {".parquet", ".csv"}:
        return [root]
    if not root.exists() or not root.is_dir():
        return []
    return sorted([p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".parquet", ".csv"}])


def candidate_vix_roots(explicit: str | None, data_root: Path) -> list[Path]:
    ordered: list[Path] = []
    def add(value: str | Path | None) -> None:
        if not value: return
        path = Path(value)
        key = str(path).lower()
        if key not in {str(x).lower() for x in ordered}: ordered.append(path)
    add(explicit)
    add(os.environ.get("FAST3_VIX_ROOT"))
    for value in COMMON_VIX_ROOTS: add(value)
    if data_root.exists():
        max_depth = len(data_root.parts) + 5
        for current, dirs, files in os.walk(data_root):
            current_path = Path(current)
            if len(current_path.parts) > max_depth:
                dirs[:] = []
                continue
            if "vix" in current_path.name.lower(): add(current_path)
            for name in files:
                if "vix" in name.lower() and Path(name).suffix.lower() in {".parquet", ".csv"}:
                    add(current_path / name)
    return ordered


def read_schema(path: Path) -> list[str]:
    if path.suffix.lower() == ".parquet":
        import pyarrow.parquet as pq
        return pq.ParquetFile(path).schema.names
    return list(pd.read_csv(path, nrows=0).columns)


def read_market_file(path: Path) -> pd.DataFrame:
    columns = read_schema(path)
    ts_col = find_column(columns, ("timestamp_utc", "timestamp", "datetime", "date_time", "time"))
    close_col = find_column(columns, ("close", "last", "price"))
    open_col = find_column(columns, ("open",), required=False)
    high_col = find_column(columns, ("high",), required=False)
    low_col = find_column(columns, ("low",), required=False)
    volume_col = find_column(columns, ("volume", "vol"), required=False)
    use = [c for c in (ts_col, open_col, high_col, low_col, close_col, volume_col) if c]
    frame = pd.read_parquet(path, columns=use) if path.suffix.lower() == ".parquet" else pd.read_csv(path, usecols=use)
    ts = pd.to_datetime(frame[ts_col], utc=True, errors="coerce")
    close = pd.to_numeric(frame[close_col], errors="coerce")
    result = pd.DataFrame({"timestamp_utc": ts, "close": close})
    result["open"] = pd.to_numeric(frame[open_col], errors="coerce") if open_col else close
    result["high"] = pd.to_numeric(frame[high_col], errors="coerce") if high_col else close
    result["low"] = pd.to_numeric(frame[low_col], errors="coerce") if low_col else close
    result["volume"] = pd.to_numeric(frame[volume_col], errors="coerce").fillna(0.0) if volume_col else 0.0
    return result.dropna(subset=["timestamp_utc", "close"]).sort_values("timestamp_utc").drop_duplicates("timestamp_utc")


def inventory_vix(candidates: list[Path]) -> pd.DataFrame:
    rows = []
    for root in candidates:
        files = supported_files(root)
        row = {"candidate_root": str(root), "exists": root.exists(), "file_count": len(files), "readable": False, "timestamp_column": None, "close_column": None, "error": None}
        if files:
            try:
                cols = read_schema(files[0])
                row["timestamp_column"] = find_column(cols, ("timestamp_utc", "timestamp", "datetime", "date_time", "time"), required=False)
                row["close_column"] = find_column(cols, ("close", "last", "price"), required=False)
                row["readable"] = bool(row["timestamp_column"] and row["close_column"])
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
    return pd.DataFrame(rows)


def select_vix_source(inventory: pd.DataFrame) -> Path | None:
    ready = inventory.loc[(inventory["file_count"] > 0) & inventory["readable"]]
    if ready.empty: return None
    return Path(ready.iloc[0]["candidate_root"])


def load_vix_source(root: Path) -> pd.DataFrame:
    files = supported_files(root)
    if not files: raise PreflightError(f"No supported VIX files under {root}")
    chunks = []
    for i, path in enumerate(files, start=1):
        chunks.append(read_market_file(path))
        if i % 25 == 0 or i == len(files):
            print(f"[VIX_SCAN] processed={i}/{len(files)} rows={sum(len(x) for x in chunks)}", flush=True)
    frame = pd.concat(chunks, ignore_index=True).sort_values("timestamp_utc").drop_duplicates("timestamp_utc")
    et = frame["timestamp_utc"].dt.tz_convert("America/New_York")
    frame["timestamp_et"] = et
    frame["trade_date"] = et.dt.strftime("%Y-%m-%d")
    frame["minute_et"] = et.dt.hour * 60 + et.dt.minute
    return frame.reset_index(drop=True)


def vix_daily_percentile(vix: pd.DataFrame) -> pd.DataFrame:
    rth = vix.loc[(vix["minute_et"] >= RTH_START) & (vix["minute_et"] <= RTH_END)].copy()
    daily = rth.sort_values("timestamp_utc").groupby("trade_date", sort=True).tail(1)[["trade_date", "close"]].rename(columns={"close": "vix_daily_close"})
    daily = daily.sort_values("trade_date").reset_index(drop=True)
    def percentile_last(window: np.ndarray) -> float:
        if len(window) < 252 or not np.isfinite(window[-1]): return np.nan
        return float(np.mean(window <= window[-1]))
    daily["vix_close_percentile_252_unshifted"] = daily["vix_daily_close"].rolling(252, min_periods=252).apply(percentile_last, raw=True)
    daily["vix_pctl_252_for_next_session"] = daily["vix_close_percentile_252_unshifted"].shift(1)
    return daily


def aggregate_5m(frame: pd.DataFrame) -> pd.DataFrame:
    rth = frame.loc[(frame["minute_et"] >= RTH_START) & (frame["minute_et"] <= RTH_END)].copy()
    if rth.empty: return pd.DataFrame()
    minute = rth["minute_et"]
    rth["bucket"] = ((minute - RTH_START) // 5).astype(int)
    grouped = rth.groupby(["trade_date", "bucket"], sort=True)
    bars = grouped.agg(timestamp_utc=("timestamp_utc", "max"), timestamp_et=("timestamp_et", "max"), open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), volume=("volume", "sum"), minute_count=("close", "size")).reset_index()
    return bars.loc[bars["minute_count"] == 5].reset_index(drop=True)


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    result = 100.0 - 100.0 / (1.0 + rs)
    result = result.where(avg_loss != 0.0, 100.0)
    return result


def kdj(frame: pd.DataFrame, n: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    lowest = frame["low"].rolling(n, min_periods=n).min()
    highest = frame["high"].rolling(n, min_periods=n).max()
    denom = (highest - lowest).replace(0.0, np.nan)
    rsv = ((frame["close"] - lowest) / denom * 100.0).fillna(50.0)
    k = pd.Series(index=frame.index, dtype=float)
    d = pd.Series(index=frame.index, dtype=float)
    prev_k = prev_d = 50.0
    for idx, value in rsv.items():
        prev_k = (2.0 / 3.0) * prev_k + (1.0 / 3.0) * float(value)
        prev_d = (2.0 / 3.0) * prev_d + (1.0 / 3.0) * prev_k
        k.loc[idx] = prev_k
        d.loc[idx] = prev_d
    j = 3.0 * k - 2.0 * d
    return k, d, j


def atr_wilder(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = frame["close"].shift(1)
    tr = pd.concat([(frame["high"] - frame["low"]).abs(), (frame["high"] - prev_close).abs(), (frame["low"] - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def factor_readiness(bars: pd.DataFrame) -> dict[str, Any]:
    if bars.empty: return {"bar_count": 0, "factor_ready_count": 0, "factor_ready_share": 0.0}
    work = bars.copy()
    work["rsi14"] = rsi_wilder(work["close"], 14)
    k, d, j = kdj(work, 9)
    work["kdj_k"], work["kdj_d"], work["kdj_j"] = k, d, j
    dif = ema(work["close"], 12) - ema(work["close"], 26)
    dea = ema(dif, 9)
    work["macd_dif"], work["macd_dea"], work["macd_hist"] = dif, dea, dif - dea
    work["atr14"] = atr_wilder(work, 14)
    columns = ["rsi14", "kdj_k", "kdj_d", "kdj_j", "macd_dif", "macd_dea", "macd_hist", "atr14"]
    ready = work[columns].notna().all(axis=1)
    return {"bar_count": int(len(work)), "factor_ready_count": int(ready.sum()), "factor_ready_share": float(ready.mean()), "first_ready_timestamp_utc": work.loc[ready, "timestamp_utc"].iloc[0].isoformat() if ready.any() else None}


def requirements_payload() -> dict[str, Any]:
    return {
        "required_instrument": "CBOE Volatility Index (VIX), not VXX/VIXY/UVXY",
        "required_frequency": "1-minute preferred; timestamped intraday OHLC required",
        "required_timezone": "timezone-aware UTC timestamps or unambiguous timestamps convertible to UTC",
        "required_period": "2017-07-01 or earlier through latest available date; at least 252 prior daily closes before 2018-07 research start",
        "required_columns": ["timestamp_utc", "open", "high", "low", "close"],
        "optional_columns": ["volume"],
        "accepted_formats": ["Parquet", "CSV"],
        "accepted_layouts": ["single file", "multiple files", "symbol/year/month partitioned files"],
        "forbidden_substitutions": ["VXX", "VIXY", "UVXY", "synthetic VIX inferred from ETFs"],
        "suggested_root": r"D:\us-tech-quant-data\fast3\vix\canonical",
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    summary_path = Path(args.v22_054_summary)
    if not summary_path.exists(): raise PreflightError(f"Missing V22.054 summary: {summary_path}")
    prior = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    validate_v22_054(prior)

    canonical_root = Path(args.canonical_root)
    etf_counts = {}
    for symbol in ETF_SYMBOLS:
        roots = [canonical_root / f"symbol={symbol}", canonical_root / f"symbol=US.{symbol}"]
        files = []
        for root in roots:
            if root.exists(): files.extend(root.rglob("*.parquet"))
        etf_counts[symbol] = len(set(files))
    etf_ready = all(count > 0 for count in etf_counts.values())

    result_dir = Path(args.result_dir)
    result_dir.mkdir(parents=True, exist_ok=True)
    inventory = inventory_vix(candidate_vix_roots(args.vix_root, Path(args.data_root)))
    inventory_path = result_dir / "v22_055_vix_candidate_inventory.csv"
    inventory.to_csv(inventory_path, index=False, encoding="utf-8-sig")
    requirements = requirements_payload()
    req_path = result_dir / "v22_055_vix_data_requirements.json"
    atomic_json(req_path, requirements)

    selected = select_vix_source(inventory)
    feature_rows = []
    vix_metrics = {}
    if selected is not None:
        vix = load_vix_source(selected)
        daily = vix_daily_percentile(vix)
        bars = aggregate_5m(vix)
        vix_metrics = {
            "selected_vix_root": str(selected),
            "vix_row_count": int(len(vix)),
            "vix_first_timestamp_utc": vix["timestamp_utc"].min().isoformat() if len(vix) else None,
            "vix_last_timestamp_utc": vix["timestamp_utc"].max().isoformat() if len(vix) else None,
            "vix_trade_date_count": int(vix["trade_date"].nunique()),
            "vix_daily_pctl_ready_days": int(daily["vix_pctl_252_for_next_session"].notna().sum()),
            "vix_complete_5m_bar_count": int(len(bars)),
        }
        feature_rows.append({"instrument": "VIX", **factor_readiness(bars)})

    feature_df = pd.DataFrame(feature_rows)
    feature_path = result_dir / "v22_055_factor_readiness.csv"
    feature_df.to_csv(feature_path, index=False, encoding="utf-8-sig")

    vix_ready = bool(selected is not None and vix_metrics.get("vix_daily_pctl_ready_days", 0) > 0 and vix_metrics.get("vix_complete_5m_bar_count", 0) > 0)
    ready = bool(etf_ready and vix_ready)
    final_status = "PASS" if ready else "BLOCKED"
    final_decision = "DATA_READY_FOR_FAST3_MULTIFACT_STATE_MACHINE" if ready else "VIX_MINUTE_DATA_REQUIRED_OR_INVALID"
    summary = {
        "version": VERSION,
        "final_status": final_status,
        "final_decision": final_decision,
        "v22_054_validated": True,
        "new_architecture": "VIX_MACD_RSI_KDJ_VWAP_ATR_STATE_MACHINE",
        "old_simple_fast3_family_reopened": False,
        "etf_canonical_root": str(canonical_root),
        "etf_partition_count_by_symbol": etf_counts,
        "etf_data_ready": etf_ready,
        "vix_source_found": selected is not None,
        "vix_data_ready": vix_ready,
        **vix_metrics,
        "data_ready_for_multifactor_backtest": ready,
        "multifactor_backtest_executed": False,
        "parameter_sweep_executed": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
        "requirements_path": str(req_path),
        "inventory_path": str(inventory_path),
        "factor_readiness_path": str(feature_path),
    }
    out = result_dir / "v22_055_summary.json"
    atomic_json(out, summary)
    return {"summary": summary, "summary_path": out, "result_dir": result_dir}


def print_final(result: Mapping[str, Any]) -> None:
    s = result["summary"]
    print(f"FINAL_STATUS={s['final_status']}")
    print(f"FINAL_DECISION={s['final_decision']}")
    print("V22_054_VALIDATED=True")
    print(f"ETF_PARTITION_COUNT_BY_SYMBOL={json.dumps(s['etf_partition_count_by_symbol'])}")
    print(f"ETF_DATA_READY={s['etf_data_ready']}")
    print(f"VIX_SOURCE_FOUND={s['vix_source_found']}")
    print(f"VIX_DATA_READY={s['vix_data_ready']}")
    if s.get("selected_vix_root"): print(f"SELECTED_VIX_ROOT={s['selected_vix_root']}")
    if s.get("vix_row_count") is not None: print(f"VIX_ROW_COUNT={s['vix_row_count']}")
    if s.get("vix_daily_pctl_ready_days") is not None: print(f"VIX_DAILY_PCTL_READY_DAYS={s['vix_daily_pctl_ready_days']}")
    print(f"DATA_READY_FOR_MULTIFACT_BACKTEST={s['data_ready_for_multifactor_backtest']}")
    print("MULTIFACTOR_BACKTEST_EXECUTED=False")
    print("PARAMETER_SWEEP_EXECUTED=False")
    print("BROKER_ACTION_ALLOWED=False")
    print("PAPER_TRADING_ALLOWED=False")
    print("OFFICIAL_ADOPTION_ALLOWED=False")
    print(f"REQUIREMENTS_PATH={s['requirements_path']}")
    print(f"SUMMARY_PATH={result['summary_path']}")
    print(f"RESULT_DIRECTORY={result['result_dir']}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--v22-054-summary", default=r"D:\us-tech-quant-results\v22\V22.054_FAST3_TERMINATION_AND_ATTRIBUTION_AUDIT_R1\v22_054_summary.json")
    p.add_argument("--canonical-root", default=r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical")
    p.add_argument("--data-root", default=r"D:\us-tech-quant-data")
    p.add_argument("--vix-root", default=None)
    p.add_argument("--result-dir", default=r"D:\us-tech-quant-results\v22\V22.055_FAST3_MULTIFACT_DATA_AND_FACTOR_PREFLIGHT_R1")
    p.add_argument("--execute", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.execute:
        print("FINAL_STATUS=BLOCKED_EXECUTE_FLAG_REQUIRED")
        return 2
    try:
        result = run(args)
        print_final(result)
        return 0
    except Exception as exc:
        print("FINAL_STATUS=FAIL")
        print(f"ERROR_TYPE={type(exc).__name__}")
        print(f"ERROR={exc}")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
