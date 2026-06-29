from __future__ import annotations

import hashlib
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.errors import EmptyDataError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.v21 import v21_174_r1c_auto_dram_price_fetch_and_cache as r1c


STAGE = "V21.175_INTRADAY_CONFIRMATION_GATE_FOR_DRAM_R1"
OUT = ROOT / "outputs" / "v21" / STAGE
R1C_OUT = ROOT / "outputs" / "v21" / "V21.174_R1C_AUTO_DRAM_PRICE_FETCH_AND_CACHE"
ANCHOR_PATH = R1C_OUT / "dram_tactical_trade_plan_latest.csv"
DAILY_BRIDGE_PATH = R1C_OUT / "dram_auto_price_bridge_daily_ohlcv.csv"
PRICE_PATH = r1c.PRICE_PATH

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "canonical_price_panel_modified": False,
}

OHLCV_COLS = ["datetime", "ticker", "interval", "open", "high", "low", "close", "volume"]
INDICATOR_COLS = OHLCV_COLS + [
    "rsi14",
    "kdj_rsv",
    "kdj_k",
    "kdj_d",
    "kdj_j",
    "bb_upper",
    "bb_middle",
    "bb_lower",
    "macd",
    "macd_signal",
    "macd_hist",
    "ema20",
    "volume_ratio",
]


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def sha(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except EmptyDataError:
        return pd.DataFrame()


def load_anchor(path: Path = ANCHOR_PATH) -> pd.DataFrame:
    df = read_csv(path)
    if df.empty or "ticker" not in df.columns:
        return pd.DataFrame()
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    return df[df["ticker"].eq("DRAM")].tail(1).reset_index(drop=True)


def flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        out = df.copy()
        out.columns = [str([x for x in c if str(x) and str(x).lower() != "nan"][0]) for c in out.columns]
        return out
    return df


def normalize_intraday(raw: pd.DataFrame, interval: str) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=OHLCV_COLS)
    df = flatten_columns(raw).copy()
    if "datetime" not in {str(c).lower() for c in df.columns} and not isinstance(df.index, pd.RangeIndex):
        df = df.reset_index()
    lower = {str(c).strip().lower(): c for c in df.columns}
    dt_col = next((lower[c] for c in ["datetime", "date", "time"] if c in lower), None)
    mapping = {
        "open": next((lower[c] for c in ["open", "o"] if c in lower), None),
        "high": next((lower[c] for c in ["high", "h"] if c in lower), None),
        "low": next((lower[c] for c in ["low", "l"] if c in lower), None),
        "close": next((lower[c] for c in ["close", "adj close", "adj_close", "c"] if c in lower), None),
        "volume": next((lower[c] for c in ["volume", "vol", "v"] if c in lower), None),
    }
    if dt_col is None or any(mapping[k] is None for k in ["open", "high", "low", "close"]):
        return pd.DataFrame(columns=OHLCV_COLS)
    vol = pd.to_numeric(df[mapping["volume"]], errors="coerce").fillna(0) if mapping["volume"] else 0
    out = pd.DataFrame(
        {
            "datetime": pd.to_datetime(df[dt_col], errors="coerce"),
            "ticker": "DRAM",
            "interval": interval,
            "open": pd.to_numeric(df[mapping["open"]], errors="coerce"),
            "high": pd.to_numeric(df[mapping["high"]], errors="coerce"),
            "low": pd.to_numeric(df[mapping["low"]], errors="coerce"),
            "close": pd.to_numeric(df[mapping["close"]], errors="coerce"),
            "volume": vol,
        }
    )
    out = out.dropna(subset=["datetime", "open", "high", "low", "close"])
    out = out[(out["open"] > 0) & (out["high"] > 0) & (out["low"] > 0) & (out["close"] > 0)]
    out = out[(out["high"] >= out[["open", "low", "close"]].max(axis=1)) & (out["low"] <= out[["open", "high", "close"]].min(axis=1))]
    out = out.sort_values("datetime").drop_duplicates(["datetime", "interval"], keep="last")
    out["datetime"] = out["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return out[OHLCV_COLS].reset_index(drop=True)


def fetch_intraday(fetcher: Any | None = None, cache_dir: Path | None = None) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, list[str]]:
    warnings: list[str] = []
    rows = []
    data: dict[str, pd.DataFrame] = {}
    try:
        yf = fetcher if fetcher is not None else importlib.import_module("yfinance")
    except Exception as exc:
        for interval in ["1h", "15m", "1m"]:
            rows.append({"interval": interval, "attempted": True, "success": False, "error_message": f"YFINANCE_IMPORT_FAILED:{type(exc).__name__}:{exc}", "row_count_raw": 0, "row_count_valid": 0, "latest_timestamp": "", "notes": ""})
            data[interval] = pd.DataFrame(columns=OHLCV_COLS)
        warnings.append("WARN_INTRADAY_DATA_MISSING")
        return data, pd.DataFrame(rows), warnings
    cache = cache_dir or (OUT / "yfinance_intraday_cache")
    cache.mkdir(parents=True, exist_ok=True)
    if hasattr(yf, "set_tz_cache_location"):
        yf.set_tz_cache_location(str(cache))
    for interval, period in [("1h", "60d"), ("15m", "30d"), ("1m", "7d")]:
        raw = pd.DataFrame()
        err = ""
        try:
            raw = yf.download("DRAM", period=period, interval=interval, progress=False, auto_adjust=False) if hasattr(yf, "download") else yf.Ticker("DRAM").history(period=period, interval=interval, auto_adjust=False)
            norm = normalize_intraday(raw, interval)
        except Exception as exc:
            norm = pd.DataFrame(columns=OHLCV_COLS)
            err = f"YFINANCE_INTRADAY_FAILED:{type(exc).__name__}:{exc}"
        data[interval] = norm
        rows.append(
            {
                "interval": interval,
                "attempted": True,
                "success": not norm.empty,
                "error_message": err if err else ("" if not norm.empty else "EMPTY_OR_INVALID_INTRADAY_OHLCV"),
                "row_count_raw": len(raw),
                "row_count_valid": len(norm),
                "latest_timestamp": str(norm["datetime"].max()) if not norm.empty else "",
                "notes": f"period={period}",
            }
        )
    if data["1m"].empty:
        warnings.append("WARN_1M_INTRADAY_UNAVAILABLE")
    if data["1h"].empty and data["15m"].empty and data["1m"].empty:
        warnings.append("WARN_INTRADAY_DATA_MISSING")
    return data, pd.DataFrame(rows), warnings


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(n, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).rolling(n, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=INDICATOR_COLS)
    work = df.copy()
    for c in ["open", "high", "low", "close", "volume"]:
        work[c] = pd.to_numeric(work[c], errors="coerce")
    c = work["close"]
    work["rsi14"] = rsi(c)
    low9 = work["low"].rolling(9, min_periods=9).min()
    high9 = work["high"].rolling(9, min_periods=9).max()
    work["kdj_rsv"] = 100 * (c - low9) / (high9 - low9).replace(0, np.nan)
    work["kdj_k"] = work["kdj_rsv"].ewm(alpha=1 / 3, adjust=False, min_periods=1).mean()
    work["kdj_d"] = work["kdj_k"].ewm(alpha=1 / 3, adjust=False, min_periods=1).mean()
    work["kdj_j"] = 3 * work["kdj_k"] - 2 * work["kdj_d"]
    mid = c.rolling(20, min_periods=20).mean()
    std = c.rolling(20, min_periods=20).std()
    work["bb_middle"] = mid
    work["bb_upper"] = mid + 2 * std
    work["bb_lower"] = mid - 2 * std
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    work["macd"] = ema12 - ema26
    work["macd_signal"] = work["macd"].ewm(span=9, adjust=False).mean()
    work["macd_hist"] = work["macd"] - work["macd_signal"]
    work["ema20"] = c.ewm(span=20, adjust=False).mean()
    vol_avg = work["volume"].rolling(20, min_periods=5).mean()
    work["volume_ratio"] = work["volume"] / vol_avg.replace(0, np.nan)
    return work.reindex(columns=INDICATOR_COLS)


def kdj_golden_cross(ind: pd.DataFrame) -> bool:
    if len(ind) < 2 or {"kdj_k", "kdj_d"} - set(ind.columns):
        return False
    prev = ind.iloc[-2]
    cur = ind.iloc[-1]
    return bool(pd.notna(prev["kdj_k"]) and pd.notna(prev["kdj_d"]) and pd.notna(cur["kdj_k"]) and pd.notna(cur["kdj_d"]) and prev["kdj_k"] <= prev["kdj_d"] and cur["kdj_k"] > cur["kdj_d"])


def bollinger_middle_reclaim(ind: pd.DataFrame) -> bool:
    if len(ind) < 2 or {"close", "bb_middle"} - set(ind.columns):
        return False
    prev = ind.iloc[-2]
    cur = ind.iloc[-1]
    return bool(pd.notna(prev["bb_middle"]) and pd.notna(cur["bb_middle"]) and prev["close"] < prev["bb_middle"] and cur["close"] >= cur["bb_middle"])


def rsi_recovery(ind: pd.DataFrame, threshold: float = 45.0) -> bool:
    if len(ind) < 2 or "rsi14" not in ind.columns:
        return False
    prev = ind.iloc[-2]["rsi14"]
    cur = ind.iloc[-1]["rsi14"]
    return bool(pd.notna(prev) and pd.notna(cur) and (prev < threshold <= cur or (prev < 40 and cur > prev)))


def one_hour_gate(ind: pd.DataFrame, no_chase: float) -> tuple[str, str]:
    if ind.empty:
        return "UNKNOWN_DATA_MISSING", "1h intraday bars unavailable"
    latest = ind.iloc[-1]
    prev = ind.iloc[-2] if len(ind) > 1 else latest
    ema_ok = pd.notna(latest["ema20"]) and (latest["close"] >= latest["ema20"] or (prev["close"] < prev["ema20"] <= latest["close"] if pd.notna(prev["ema20"]) else False))
    rsi_ok = pd.notna(latest["rsi14"]) and latest["rsi14"] >= 45
    hist_ok = True
    if len(ind) >= 3 and pd.notna(ind.iloc[-1]["macd_hist"]) and pd.notna(ind.iloc[-3]["macd_hist"]):
        hist_ok = (ind.iloc[-1]["macd_hist"] - ind.iloc[-3]["macd_hist"]) > -0.75
    no_chase_ok = latest["close"] <= no_chase
    passed = ema_ok and rsi_ok and hist_ok and no_chase_ok
    return ("PASS" if passed else "FAIL", f"ema_ok={ema_ok};rsi_ok={rsi_ok};hist_ok={hist_ok};no_chase_ok={no_chase_ok}")


def fifteen_min_gate(ind: pd.DataFrame) -> tuple[str, str]:
    if ind.empty:
        return "UNKNOWN_DATA_MISSING", "15m intraday bars unavailable"
    latest = ind.iloc[-1]
    checks = {
        "rsi_recovery": rsi_recovery(ind, 45),
        "kdj_cross": kdj_golden_cross(ind),
        "bb_reclaim_or_bounce": bollinger_middle_reclaim(ind) or (pd.notna(latest["bb_lower"]) and latest["low"] <= latest["bb_lower"] and latest["close"] > latest["bb_lower"]),
        "volume_ratio": pd.notna(latest["volume_ratio"]) and latest["volume_ratio"] >= 1.0,
    }
    passed = sum(bool(v) for v in checks.values()) >= 2
    return ("PASS" if passed else "FAIL", ";".join(f"{k}={v}" for k, v in checks.items()))


def one_min_gate(ind: pd.DataFrame, no_chase: float) -> tuple[str, str]:
    if ind.empty:
        return "UNKNOWN_DATA_MISSING", "1m intraday bars unavailable"
    latest = ind.iloc[-1]
    trigger = kdj_golden_cross(ind) or rsi_recovery(ind, 45)
    price_ok = (pd.notna(latest["ema20"]) and latest["close"] >= latest["ema20"]) or (pd.notna(latest["bb_middle"]) and latest["close"] >= latest["bb_middle"])
    no_chase_ok = latest["close"] <= no_chase
    passed = trigger and price_ok and no_chase_ok
    return ("PASS" if passed else "FAIL", f"trigger={trigger};price_ok={price_ok};no_chase_ok={no_chase_ok}")


def final_trade_decision(g1h: str, g15: str, g1m: str, no_chase: bool, any_intraday: bool, anchor_loaded: bool) -> str:
    if not anchor_loaded:
        return "DRAM_DAILY_ANCHOR_MISSING"
    if not any_intraday:
        return "DRAM_INTRADAY_DATA_MISSING"
    if no_chase:
        return "DRAM_NO_CHASE"
    if g1h != "PASS":
        return "DRAM_WAIT_1H_TREND_CONFIRMATION"
    if g15 != "PASS":
        return "DRAM_WAIT_15M_CONFIRMATION"
    if g1m != "PASS":
        return "DRAM_WAIT_1M_TRIGGER"
    return "DRAM_INTRADAY_ENTRY_ALLOWED"


def write_empty_outputs(out_dir: Path) -> None:
    for name in ["dram_intraday_ohlcv_1h.csv", "dram_intraday_ohlcv_15m.csv", "dram_intraday_ohlcv_1m.csv"]:
        pd.DataFrame(columns=OHLCV_COLS).to_csv(out_dir / name, index=False)
    for name in ["dram_intraday_indicators_1h.csv", "dram_intraday_indicators_15m.csv", "dram_intraday_indicators_1m.csv"]:
        pd.DataFrame(columns=INDICATOR_COLS).to_csv(out_dir / name, index=False)


def write_report(summary: dict[str, Any], out_dir: Path = OUT) -> None:
    lines = [
        STAGE,
        f"final_status: {summary['final_status']}",
        f"decision: {summary['decision']}",
        f"r1c_anchor_loaded: {summary['r1c_anchor_loaded']}",
        f"latest_dram_daily_date: {summary['latest_dram_daily_date']}",
        f"latest_intraday_timestamp: {summary['latest_intraday_timestamp']}",
        f"intraday loaded 1h/15m/1m: {summary['intraday_1h_loaded']} / {summary['intraday_15m_loaded']} / {summary['intraday_1m_loaded']}",
        f"gates 1h/15m/1m: {summary['one_hour_gate']} / {summary['fifteen_min_gate']} / {summary['one_min_gate']}",
        f"no_chase_triggered: {summary['no_chase_triggered']}",
        f"final_trade_decision: {summary['final_trade_decision']}",
        "warnings:",
        *([f"- {w}" for w in summary["warnings"]] if summary["warnings"] else ["- none"]),
        "research_only: True",
        "official_adoption_allowed: False",
        "broker_action_allowed: False",
        "protected_outputs_modified: False",
        "canonical_price_panel_modified: False",
    ]
    (out_dir / "V21.175_readable_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(out_dir: Path = OUT, anchor_path: Path = ANCHOR_PATH, fetcher: Any | None = None) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    pre_hash = sha(PRICE_PATH)
    anchor = load_anchor(anchor_path)
    if anchor.empty:
        write_empty_outputs(out_dir)
        pd.DataFrame(columns=["interval", "attempted", "success", "error_message", "row_count_raw", "row_count_valid", "latest_timestamp", "notes"]).to_csv(out_dir / "dram_intraday_fetch_audit.csv", index=False)
        pd.DataFrame([{"gate": "ALL", "status": "BLOCKED", "details": "R1C anchor missing"}]).to_csv(out_dir / "dram_intraday_gate_status.csv", index=False)
        pd.DataFrame([{"final_trade_decision": "DRAM_DAILY_ANCHOR_MISSING"}]).to_csv(out_dir / "dram_intraday_trade_decision_latest.csv", index=False)
        summary = {
            "final_status": "BLOCKED_V21_175_DAILY_ANCHOR_MISSING",
            "decision": "DRAM_DAILY_ANCHOR_REQUIRED",
            "r1c_anchor_loaded": False,
            "latest_dram_daily_date": "",
            "latest_intraday_timestamp": "",
            "intraday_1h_loaded": False,
            "intraday_15m_loaded": False,
            "intraday_1m_loaded": False,
            "one_hour_gate": "UNKNOWN_DATA_MISSING",
            "fifteen_min_gate": "UNKNOWN_DATA_MISSING",
            "one_min_gate": "UNKNOWN_DATA_MISSING",
            "no_chase_triggered": False,
            "latest_intraday_price": np.nan,
            "planned_entry_base": np.nan,
            "no_chase_above": np.nan,
            "stop_loss_base": np.nan,
            "take_profit_1_base": np.nan,
            "take_profit_2_base": np.nan,
            "final_trade_decision": "DRAM_DAILY_ANCHOR_MISSING",
            "intraday_confirmation_allowed": False,
            "warnings": ["WARN_R1C_DAILY_ANCHOR_MISSING"],
            **POLICY,
        }
        (out_dir / "V21.175_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        write_report(summary, out_dir)
        return 0

    a = anchor.iloc[0]
    no_chase = float(a["no_chase_above"])
    data, fetch_audit, warnings = fetch_intraday(fetcher, out_dir / "yfinance_intraday_cache")
    fetch_audit.to_csv(out_dir / "dram_intraday_fetch_audit.csv", index=False)
    interval_file = {"1h": "1h", "15m": "15m", "1m": "1m"}
    indicators: dict[str, pd.DataFrame] = {}
    for interval, suffix in interval_file.items():
        data[interval].to_csv(out_dir / f"dram_intraday_ohlcv_{suffix}.csv", index=False)
        indicators[interval] = add_indicators(data[interval])
        indicators[interval].to_csv(out_dir / f"dram_intraday_indicators_{suffix}.csv", index=False)

    g1h, d1h = one_hour_gate(indicators["1h"], no_chase)
    g15, d15 = fifteen_min_gate(indicators["15m"])
    g1m, d1m = one_min_gate(indicators["1m"], no_chase)
    latest_frames = [df for df in indicators.values() if not df.empty]
    latest_price = np.nan
    latest_ts = ""
    if latest_frames:
        latest_rows = pd.concat([df.tail(1) for df in latest_frames], ignore_index=True)
        latest_rows["_dt"] = pd.to_datetime(latest_rows["datetime"], errors="coerce")
        row = latest_rows.sort_values("_dt").tail(1).iloc[0]
        latest_price = float(row["close"])
        latest_ts = str(row["datetime"])
    no_chase_triggered = bool(pd.notna(latest_price) and latest_price > no_chase)
    any_intraday = any(not data[x].empty for x in ["1h", "15m", "1m"])
    trade_decision = final_trade_decision(g1h, g15, g1m, no_chase_triggered, any_intraday, True)
    gate_rows = [
        {"gate_name": "1H_TREND_GATE", "status": g1h, "details": d1h},
        {"gate_name": "15M_SETUP_GATE", "status": g15, "details": d15},
        {"gate_name": "1M_TRIGGER_GATE", "status": g1m, "details": d1m},
        {"gate_name": "NO_CHASE_GATE", "status": "FAIL" if no_chase_triggered else "PASS", "details": f"latest_price={latest_price};no_chase_above={no_chase}"},
    ]
    pd.DataFrame(gate_rows).to_csv(out_dir / "dram_intraday_gate_status.csv", index=False)
    pd.DataFrame(
        [
            {
                "latest_intraday_timestamp": latest_ts,
                "latest_intraday_price": latest_price,
                "final_trade_decision": trade_decision,
                "intraday_confirmation_allowed": trade_decision == "DRAM_INTRADAY_ENTRY_ALLOWED",
                "broker_action_allowed": False,
                "research_only": True,
            }
        ]
    ).to_csv(out_dir / "dram_intraday_trade_decision_latest.csv", index=False)

    if not any_intraday:
        final_status = "WARN_V21_175_INTRADAY_DATA_MISSING"
        decision = "DRAM_INTRADAY_DATA_REQUIRED"
    elif data["1h"].empty or data["15m"].empty:
        final_status = "WARN_V21_175_INTRADAY_DATA_MISSING"
        decision = "DRAM_INTRADAY_DATA_REQUIRED"
    elif data["1m"].empty:
        final_status = "PARTIAL_PASS_V21_175_1H_15M_READY_WAIT_1M"
        decision = "DRAM_1H_15M_READY_WAIT_1M_TRIGGER"
    else:
        final_status = "PASS_V21_175_DRAM_INTRADAY_GATE_READY"
        decision = "DRAM_INTRADAY_CONFIRMATION_READY_RESEARCH_ONLY"
    post_hash = sha(PRICE_PATH)
    summary = {
        "final_status": final_status,
        "decision": decision,
        "r1c_anchor_loaded": True,
        "latest_dram_daily_date": str(a.get("latest_date", "")),
        "latest_intraday_timestamp": latest_ts,
        "intraday_1h_loaded": not data["1h"].empty,
        "intraday_15m_loaded": not data["15m"].empty,
        "intraday_1m_loaded": not data["1m"].empty,
        "one_hour_gate": g1h,
        "fifteen_min_gate": g15,
        "one_min_gate": g1m,
        "no_chase_triggered": no_chase_triggered,
        "latest_intraday_price": latest_price,
        "planned_entry_base": float(a["planned_entry_base"]),
        "no_chase_above": no_chase,
        "stop_loss_base": float(a["stop_loss_base"]),
        "take_profit_1_base": float(a["take_profit_1_base"]),
        "take_profit_2_base": float(a["take_profit_2_base"]),
        "final_trade_decision": trade_decision,
        "intraday_confirmation_allowed": trade_decision == "DRAM_INTRADAY_ENTRY_ALLOWED",
        "warnings": sorted(set(warnings)),
        **{**POLICY, "canonical_price_panel_modified": pre_hash != post_hash},
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(out_dir),
    }
    (out_dir / "V21.175_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_report(summary, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
