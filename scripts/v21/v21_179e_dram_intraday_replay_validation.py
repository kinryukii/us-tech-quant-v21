from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.errors import EmptyDataError


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.179E_DRAM_INTRADAY_REPLAY_VALIDATION"
OUT = ROOT / "outputs" / "v21" / STAGE

V175 = ROOT / "outputs" / "v21" / "V21.175_INTRADAY_CONFIRMATION_GATE_FOR_DRAM_R1"
INTRADAY_1M = V175 / "dram_intraday_ohlcv_1m.csv"
V177 = ROOT / "outputs" / "v21" / "V21.177_DAILY_DRAM_PLAN_LEDGER_AND_STALENESS_GATE_R1"
PLAN_LEDGER = V177 / "dram_daily_plan_ledger.csv"
V178 = ROOT / "outputs" / "v21" / "V21.178_DAILY_DRAM_PLAN_CHAIN_ORCHESTRATOR_R1"
LATEST_PLAN = V178 / "dram_daily_chain_final_decision.csv"

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
}

BASELINES = ["DAILY_PLAN_ONLY", "H1_ONLY", "H1_M15_ONLY", "H1_M15_M1_FULL"]
FINAL_PASS = "PASS_V21_179E_INTRADAY_CONFIRMATION_SUPPORTED"
FINAL_PARTIAL = "PARTIAL_PASS_V21_179E_SIGNAL_MIXED_CONTINUE_FORWARD_TRACKING"
FINAL_WARN = "WARN_V21_179E_INTRADAY_DATA_INSUFFICIENT"
FINAL_FAIL = "FAIL_V21_179E_CONFIRMATION_NOT_SUPPORTED"

LEDGER_COLUMNS = [
    "replay_mode",
    "baseline",
    "plan_date",
    "replay_date",
    "signal_timestamp",
    "entry_timestamp",
    "execution_policy",
    "execution_state",
    "entry_price",
    "daily_entry",
    "no_chase",
    "stop",
    "h1_signal",
    "m15_signal",
    "m1_signal",
    "next_30m_return",
    "next_60m_return",
    "eod_return",
    "next_day_return",
    "MAE_30m",
    "MFE_30m",
    "MAE_60m",
    "MFE_60m",
    "hit_stop_after_entry",
    "hit_no_chase_after_entry",
    "false_breakout_flag",
    "missed_good_move_flag",
    "research_only",
    "broker_action_allowed",
    "official_adoption_allowed",
]


@dataclass(frozen=True)
class ReplayConfig:
    execution_policy: str = "NEXT_BAR_OPEN"
    stop_buffer_pct: float = 0.003
    entry_zone_pct: float = 0.01
    false_breakout_horizon: int = 30
    missed_good_move_threshold: float = 0.02


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except EmptyDataError:
        return pd.DataFrame()


def write_csv(path: Path, frame: pd.DataFrame, columns: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if columns is not None:
        frame = frame.reindex(columns=columns)
    frame.to_csv(path, index=False)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def protected_hashes(root: Path = ROOT) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for base in [root / "outputs", root / "data"]:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or OUT in path.parents:
                continue
            s = rel(path).lower().replace("-", "_")
            protected = any(token in s for token in ["broker", "real_book", "realbook", "trade_action"])
            protected = protected or ("official" in s and any(token in s for token in ["rank", "weight", "allocation", "recommend"]))
            protected = protected or ("abcd" in s and "official" in s)
            if protected:
                hashes[rel(path)] = sha(path)
    return hashes


def normalize_intraday(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["datetime", "ticker", "open", "high", "low", "close", "volume", "bar_end"])
    lower = {str(c).strip().lower(): c for c in df.columns}
    dt = lower.get("datetime") or lower.get("date") or lower.get("time")
    required = [dt, lower.get("open"), lower.get("high"), lower.get("low"), lower.get("close")]
    if any(c is None for c in required):
        return pd.DataFrame(columns=["datetime", "ticker", "open", "high", "low", "close", "volume", "bar_end"])
    out = pd.DataFrame(
        {
            "datetime": pd.to_datetime(df[dt], errors="coerce"),
            "ticker": df[lower["ticker"]].astype(str).str.upper().str.strip() if "ticker" in lower else "DRAM",
            "open": pd.to_numeric(df[lower["open"]], errors="coerce"),
            "high": pd.to_numeric(df[lower["high"]], errors="coerce"),
            "low": pd.to_numeric(df[lower["low"]], errors="coerce"),
            "close": pd.to_numeric(df[lower["close"]], errors="coerce"),
            "volume": pd.to_numeric(df[lower["volume"]], errors="coerce").fillna(0) if "volume" in lower else 0,
        }
    )
    out = out.dropna(subset=["datetime", "open", "high", "low", "close"])
    out = out[out["ticker"].eq("DRAM")]
    out = out[(out["open"] > 0) & (out["high"] >= out[["open", "close", "low"]].max(axis=1)) & (out["low"] <= out[["open", "close", "high"]].min(axis=1))]
    out = out.sort_values("datetime").drop_duplicates("datetime", keep="last").reset_index(drop=True)
    out["bar_end"] = out["datetime"] + pd.Timedelta(minutes=1)
    return out


def normalize_plans(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["plan_date", "replay_date", "ticker", "entry", "no_chase", "stop", "latest_price_date_used"])
    lower = {str(c).strip().lower(): c for c in df.columns}
    plan_col = lower.get("plan_date") or lower.get("latest_plan_date") or lower.get("latest_price_date")
    entry_col = lower.get("planned_entry_base")
    no_chase_col = lower.get("no_chase_above")
    stop_col = lower.get("stop_loss_base")
    if not plan_col or not entry_col or not no_chase_col or not stop_col:
        return pd.DataFrame(columns=["plan_date", "replay_date", "ticker", "entry", "no_chase", "stop", "latest_price_date_used"])
    latest_col = lower.get("latest_price_date_used") or lower.get("latest_price_date")
    target_col = lower.get("target_trade_session")
    out = pd.DataFrame(
        {
            "plan_date": pd.to_datetime(df[plan_col], errors="coerce").dt.strftime("%Y-%m-%d"),
            "ticker": df[lower["ticker"]].astype(str).str.upper().str.strip() if "ticker" in lower else "DRAM",
            "entry": pd.to_numeric(df[entry_col], errors="coerce"),
            "no_chase": pd.to_numeric(df[no_chase_col], errors="coerce"),
            "stop": pd.to_numeric(df[stop_col], errors="coerce"),
            "latest_price_date_used": pd.to_datetime(df[latest_col], errors="coerce").dt.strftime("%Y-%m-%d") if latest_col else "",
            "source_stage": df[lower["source_stage"]].astype(str) if "source_stage" in lower else "",
        }
    )
    if target_col:
        extracted = df[target_col].astype(str).str.extract(r"(\d{4}-\d{2}-\d{2})")[0]
        out["replay_date"] = extracted.fillna(out["plan_date"])
    else:
        out["replay_date"] = out["plan_date"]
    out = out.dropna(subset=["plan_date", "entry", "no_chase", "stop"])
    out = out[out["ticker"].eq("DRAM")]
    return out.drop_duplicates(["plan_date", "replay_date"], keep="last").reset_index(drop=True)


def load_plans(plan_paths: list[Path] | None = None) -> tuple[pd.DataFrame, str]:
    paths = plan_paths or [PLAN_LEDGER, LATEST_PLAN]
    frames = [normalize_plans(read_csv(path)) for path in paths]
    plans = pd.concat([f for f in frames if not f.empty], ignore_index=True) if any(not f.empty for f in frames) else pd.DataFrame()
    if plans.empty:
        return normalize_plans(plans), "DIAGNOSTIC_ONLY"
    plans = plans.drop_duplicates(["plan_date", "replay_date"], keep="last").sort_values(["replay_date", "plan_date"]).reset_index(drop=True)
    strict = bool(plans["source_stage"].astype(str).str.contains("V21.176|V21.177|V21.178", regex=True).any())
    return plans, "PIT_LITE" if strict else "DIAGNOSTIC_ONLY"


def aggregate_completed(bars_1m: pd.DataFrame, as_of: pd.Timestamp, freq: str) -> pd.DataFrame:
    if bars_1m.empty:
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume", "bar_end"])
    minutes = bars_1m[bars_1m["bar_end"].le(as_of)].copy()
    if minutes.empty:
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume", "bar_end"])
    offset = "30min" if freq in {"15min", "60min"} else None
    idx = minutes.set_index("datetime")
    if offset:
        grouped = idx.resample(freq, origin="start_day", offset=offset, label="left", closed="left")
    else:
        grouped = idx.resample(freq, label="left", closed="left")
    out = grouped.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["open", "high", "low", "close"]).reset_index()
    delta = pd.Timedelta(freq)
    out["bar_end"] = out["datetime"] + delta
    out = out[out["bar_end"].le(as_of)].reset_index(drop=True)
    return out


def add_basic_indicators(bars: pd.DataFrame) -> pd.DataFrame:
    if bars.empty:
        return bars.copy()
    out = bars.copy()
    close = out["close"]
    out["ema8"] = close.ewm(span=8, adjust=False).mean()
    out["ema20"] = close.ewm(span=20, adjust=False).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14, min_periods=3).mean()
    loss = (-delta.clip(upper=0)).rolling(14, min_periods=3).mean()
    out["rsi14"] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))
    out["range_pct"] = (out["high"] - out["low"]) / out["close"].replace(0, np.nan)
    return out


def h1_signal(bars: pd.DataFrame, no_chase: float) -> str:
    ind = add_basic_indicators(bars)
    if ind.empty or len(ind) < 2:
        return "H1_NEUTRAL_WAIT"
    last = ind.iloc[-1]
    prev = ind.iloc[-2]
    if last["close"] >= no_chase:
        return "H1_OVEREXTENDED_NO_CHASE"
    if last["close"] < last["ema20"] and last["close"] < prev["close"]:
        return "H1_BEARISH_BLOCK"
    if last["close"] >= last["ema8"] and last["ema8"] >= last["ema20"]:
        return "H1_BULLISH_CONFIRM"
    return "H1_NEUTRAL_WAIT"


def m15_signal(bars: pd.DataFrame, entry: float, no_chase: float) -> str:
    ind = add_basic_indicators(bars)
    if ind.empty:
        return "M15_WAIT_PULLBACK"
    last = ind.iloc[-1]
    if last["close"] >= no_chase or (pd.notna(last.get("rsi14")) and last["rsi14"] >= 75):
        return "M15_OVERHEATED_BLOCK"
    near_entry = last["low"] <= entry * 1.01 and last["close"] >= entry * 0.985
    recovering = len(ind) >= 2 and last["close"] >= ind.iloc[-2]["close"]
    if near_entry and recovering:
        return "M15_ENTRY_ZONE_VALID"
    return "M15_WAIT_PULLBACK"


def m1_signal(bars: pd.DataFrame, entry: float, no_chase: float) -> str:
    ind = add_basic_indicators(bars)
    if ind.empty or len(ind) < 2:
        return "M1_FALSE_BREAKOUT_WAIT"
    last = ind.iloc[-1]
    prev = ind.iloc[-2]
    if last["close"] >= no_chase:
        return "M1_TOO_LATE_NO_CHASE"
    ready = last["close"] >= max(entry, prev["high"]) or (last["close"] > prev["close"] and last["close"] >= last["ema8"])
    return "M1_TRIGGER_READY" if ready else "M1_FALSE_BREAKOUT_WAIT"


def hard_execution_state(price: float, no_chase: float, stop: float, config: ReplayConfig) -> str:
    if price >= no_chase:
        return "NO_CHASE_BLOCK"
    if price <= stop * (1 + config.stop_buffer_pct):
        return "STOP_RISK_ACTIVE"
    return "ELIGIBLE"


def baseline_passes(baseline: str, h1: str, m15: str, m1: str) -> bool:
    if baseline == "DAILY_PLAN_ONLY":
        return True
    if baseline == "H1_ONLY":
        return h1 == "H1_BULLISH_CONFIRM"
    if baseline == "H1_M15_ONLY":
        return h1 == "H1_BULLISH_CONFIRM" and m15 == "M15_ENTRY_ZONE_VALID"
    if baseline == "H1_M15_M1_FULL":
        return h1 == "H1_BULLISH_CONFIRM" and m15 == "M15_ENTRY_ZONE_VALID" and m1 == "M1_TRIGGER_READY"
    return False


def outcome_metrics(day_bars: pd.DataFrame, all_bars: pd.DataFrame, entry_idx: int, entry_price: float, no_chase: float, stop: float) -> dict[str, Any]:
    future = day_bars.iloc[entry_idx + 1 :].copy()
    next30 = future.head(30)
    next60 = future.head(60)
    eod = future.tail(1)
    all_pos = all_bars[all_bars["datetime"].gt(day_bars.iloc[entry_idx]["datetime"])]
    next_day = all_pos[all_pos["datetime"].dt.date > day_bars.iloc[entry_idx]["datetime"].date()]
    next_day_close = next_day.groupby(next_day["datetime"].dt.date).tail(1).head(1)

    def ret(frame: pd.DataFrame) -> float:
        return float(frame.iloc[-1]["close"] / entry_price - 1) if not frame.empty else np.nan

    def mae(frame: pd.DataFrame) -> float:
        return float(frame["low"].min() / entry_price - 1) if not frame.empty else np.nan

    def mfe(frame: pd.DataFrame) -> float:
        return float(frame["high"].max() / entry_price - 1) if not frame.empty else np.nan

    stop_hit = bool(not future.empty and future["low"].le(stop).any())
    no_chase_hit = bool(not future.empty and future["high"].ge(no_chase).any())
    mfe30 = mfe(next30)
    return {
        "next_30m_return": ret(next30),
        "next_60m_return": ret(next60),
        "eod_return": ret(eod),
        "next_day_return": ret(next_day_close),
        "MAE_30m": mae(next30),
        "MFE_30m": mfe30,
        "MAE_60m": mae(next60),
        "MFE_60m": mfe(next60),
        "hit_stop_after_entry": stop_hit,
        "hit_no_chase_after_entry": no_chase_hit,
        "false_breakout_flag": bool(stop_hit or (pd.notna(mfe30) and mfe30 < 0.003 and ret(next30) < 0)),
    }


def replay_day(day_bars: pd.DataFrame, all_bars: pd.DataFrame, plan: pd.Series, replay_mode: str, config: ReplayConfig) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ledger: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    entered = {b: False for b in BASELINES}
    entry = float(plan["entry"])
    no_chase = float(plan["no_chase"])
    stop = float(plan["stop"])
    plan_date = str(plan["plan_date"])
    replay_date = str(plan["replay_date"])

    for i in range(1, len(day_bars) - 1):
        ts = pd.Timestamp(day_bars.iloc[i]["datetime"])
        signal_price = float(day_bars.iloc[i - 1]["close"])
        execution_state = hard_execution_state(signal_price, no_chase, stop, config)
        h1 = h1_signal(aggregate_completed(day_bars, ts, "60min"), no_chase)
        m15 = m15_signal(aggregate_completed(day_bars, ts, "15min"), entry, no_chase)
        m1 = m1_signal(day_bars[day_bars["bar_end"].le(ts)], entry, no_chase)
        daily_touch = bool(day_bars.iloc[i - 1]["low"] <= entry * (1 + config.entry_zone_pct) and day_bars.iloc[i - 1]["high"] >= entry * (1 - config.entry_zone_pct))
        events.append(
            {
                "replay_mode": replay_mode,
                "plan_date": plan_date,
                "replay_date": replay_date,
                "signal_timestamp": ts,
                "signal_price": signal_price,
                "execution_state": execution_state,
                "daily_entry_zone_touched": daily_touch,
                "h1_signal": h1,
                "m15_signal": m15,
                "m1_signal": m1,
                "future_bar_count_available_at_signal": int((day_bars["datetime"] > ts).sum()),
                "research_only": True,
                "broker_action_allowed": False,
                "official_adoption_allowed": False,
            }
        )
        if execution_state != "ELIGIBLE" or not daily_touch:
            continue
        for baseline in BASELINES:
            if entered[baseline] or not baseline_passes(baseline, h1, m15, m1):
                continue
            exec_idx = i + 1
            entry_bar = day_bars.iloc[exec_idx]
            entry_price = float(entry_bar["open"] if config.execution_policy == "NEXT_BAR_OPEN" else entry_bar["close"])
            metrics = outcome_metrics(day_bars, all_bars, exec_idx, entry_price, no_chase, stop)
            row = {
                "replay_mode": replay_mode,
                "baseline": baseline,
                "plan_date": plan_date,
                "replay_date": replay_date,
                "signal_timestamp": ts,
                "entry_timestamp": entry_bar["datetime"],
                "execution_policy": config.execution_policy,
                "execution_state": execution_state,
                "entry_price": entry_price,
                "daily_entry": entry,
                "no_chase": no_chase,
                "stop": stop,
                "h1_signal": h1,
                "m15_signal": m15,
                "m1_signal": m1,
                **metrics,
                "missed_good_move_flag": False,
                "research_only": True,
                "broker_action_allowed": False,
                "official_adoption_allowed": False,
            }
            ledger.append(row)
            entered[baseline] = True
    max_move = float(day_bars["high"].max() / entry - 1) if not day_bars.empty and entry > 0 else np.nan
    for baseline in BASELINES:
        if not entered[baseline] and pd.notna(max_move) and max_move >= config.missed_good_move_threshold:
            ledger.append(
                {
                    "replay_mode": replay_mode,
                    "baseline": baseline,
                    "plan_date": plan_date,
                    "replay_date": replay_date,
                    "signal_timestamp": "",
                    "entry_timestamp": "",
                    "execution_policy": config.execution_policy,
                    "execution_state": "MISSED_GOOD_MOVE",
                    "entry_price": np.nan,
                    "daily_entry": entry,
                    "no_chase": no_chase,
                    "stop": stop,
                    "h1_signal": "",
                    "m15_signal": "",
                    "m1_signal": "",
                    "next_30m_return": np.nan,
                    "next_60m_return": np.nan,
                    "eod_return": np.nan,
                    "next_day_return": np.nan,
                    "MAE_30m": np.nan,
                    "MFE_30m": np.nan,
                    "MAE_60m": np.nan,
                    "MFE_60m": np.nan,
                    "hit_stop_after_entry": False,
                    "hit_no_chase_after_entry": False,
                    "false_breakout_flag": False,
                    "missed_good_move_flag": True,
                    "research_only": True,
                    "broker_action_allowed": False,
                    "official_adoption_allowed": False,
                }
            )
    return ledger, events


def baseline_comparison(ledger: pd.DataFrame, events: pd.DataFrame, skipped_day_count: int) -> pd.DataFrame:
    rows = []
    for baseline in BASELINES:
        sub = ledger[ledger["baseline"].eq(baseline)] if not ledger.empty else pd.DataFrame()
        entries = sub[pd.to_numeric(sub["entry_price"], errors="coerce").notna()] if not sub.empty else pd.DataFrame()
        ev_count = int(len(events)) if not events.empty else 0
        avg_30 = pd.to_numeric(entries.get("next_30m_return", pd.Series(dtype=float)), errors="coerce").mean() if not entries.empty else np.nan
        avg_60 = pd.to_numeric(entries.get("next_60m_return", pd.Series(dtype=float)), errors="coerce").mean() if not entries.empty else np.nan
        false_rate = entries["false_breakout_flag"].astype(bool).mean() if not entries.empty else np.nan
        rows.append(
            {
                "baseline": baseline,
                "signal_count": ev_count,
                "entry_count": int(len(entries)),
                "skipped_day_count": skipped_day_count,
                "avg_next_30m_return": avg_30,
                "avg_next_60m_return": avg_60,
                "avg_eod_return": pd.to_numeric(entries.get("eod_return", pd.Series(dtype=float)), errors="coerce").mean() if not entries.empty else np.nan,
                "false_breakout_rate": false_rate,
                "missed_good_move_count": int(sub["missed_good_move_flag"].astype(bool).sum()) if not sub.empty else 0,
                "research_only": True,
                "broker_action_allowed": False,
                "official_adoption_allowed": False,
            }
        )
    return pd.DataFrame(rows)


def final_status(comp: pd.DataFrame, intraday_rows: int, plan_count: int) -> str:
    if intraday_rows == 0 or plan_count == 0:
        return FINAL_WARN
    if comp.empty:
        return FINAL_WARN
    simple = comp.loc[comp["baseline"].eq("DAILY_PLAN_ONLY"), "avg_next_60m_return"]
    full = comp.loc[comp["baseline"].eq("H1_M15_M1_FULL"), "avg_next_60m_return"]
    if simple.empty or full.empty or pd.isna(full.iloc[0]):
        return FINAL_PARTIAL
    if full.iloc[0] > simple.iloc[0]:
        return FINAL_PASS
    if full.iloc[0] == simple.iloc[0] or bool(comp["entry_count"].sum()):
        return FINAL_PARTIAL
    return FINAL_FAIL


def run_stage(
    out_dir: Path = OUT,
    intraday_path: Path = INTRADAY_1M,
    plan_paths: list[Path] | None = None,
    config: ReplayConfig = ReplayConfig(),
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()
    intraday = normalize_intraday(read_csv(intraday_path))
    plans, replay_mode = load_plans(plan_paths)
    skipped = 0
    ledger_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []

    if not intraday.empty and not plans.empty:
        intraday["replay_date"] = intraday["datetime"].dt.strftime("%Y-%m-%d")
        for _, plan in plans.iterrows():
            day = intraday[intraday["replay_date"].eq(str(plan["replay_date"]))].copy().reset_index(drop=True)
            if len(day) < 3:
                skipped += 1
                continue
            rows, events = replay_day(day, intraday, plan, replay_mode, config)
            ledger_rows.extend(rows)
            event_rows.extend(events)
    else:
        skipped = int(len(plans)) if not plans.empty else 0

    ledger = pd.DataFrame(ledger_rows)
    events = pd.DataFrame(event_rows)
    comparison = baseline_comparison(ledger, events, skipped)
    if ledger.empty:
        ledger = pd.DataFrame(columns=LEDGER_COLUMNS)
    write_csv(out_dir / "dram_intraday_replay_ledger.csv", ledger, LEDGER_COLUMNS)
    write_csv(out_dir / "dram_intraday_signal_events.csv", events)
    write_csv(out_dir / "dram_intraday_baseline_comparison.csv", comparison)

    dq_rows = [
        {
            "input_name": "historical_dram_1m_ohlcv",
            "path": rel(intraday_path),
            "exists": intraday_path.exists(),
            "row_count": int(len(intraday)),
            "first_timestamp": "" if intraday.empty else str(intraday["datetime"].min()),
            "last_timestamp": "" if intraday.empty else str(intraday["datetime"].max()),
            "status": "PASS" if not intraday.empty else "WARN_MISSING_INTRADAY_DATA",
        },
        {
            "input_name": "daily_dram_trade_plans",
            "path": "|".join(rel(p) for p in (plan_paths or [PLAN_LEDGER, LATEST_PLAN])),
            "exists": bool(plan_count := len(plans)),
            "row_count": int(plan_count),
            "first_timestamp": "" if plans.empty else str(plans["plan_date"].min()),
            "last_timestamp": "" if plans.empty else str(plans["plan_date"].max()),
            "status": "PASS_PIT_LITE" if replay_mode == "PIT_LITE" and not plans.empty else ("WARN_DIAGNOSTIC_ONLY" if not plans.empty else "WARN_MISSING_DAILY_PLANS"),
        },
    ]
    write_csv(out_dir / "dram_intraday_data_quality_report.csv", pd.DataFrame(dq_rows))

    after = protected_hashes()
    changed = [path for path, digest in before.items() if after.get(path) != digest]
    status = final_status(comparison, len(intraday), len(plans))
    if changed:
        status = FINAL_FAIL
    decision = "CONTINUE_FORWARD_TRACKING_RESEARCH_ONLY" if status in {FINAL_PASS, FINAL_PARTIAL} else "DO_NOT_SUPPORT_CONFIRMATION_SEQUENCE"
    summary = {
        "stage": STAGE,
        "final_status": status,
        "decision": decision,
        "replay_mode": replay_mode,
        "execution_policy": config.execution_policy,
        "intraday_1m_row_count": int(len(intraday)),
        "daily_plan_count": int(len(plans)),
        "signal_event_count": int(len(events)),
        "entry_count": int(pd.to_numeric(ledger.get("entry_price", pd.Series(dtype=float)), errors="coerce").notna().sum()) if not ledger.empty else 0,
        "skipped_day_count": skipped,
        "protected_output_mutation_count": len(changed),
        "changed_protected_paths": changed,
        **{**POLICY, "protected_outputs_modified": bool(changed)},
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(out_dir),
    }
    write_json(out_dir / "manifest.json", summary)
    report = [
        STAGE,
        f"FINAL_STATUS={status}",
        f"DECISION={decision}",
        f"replay_mode={replay_mode}",
        f"execution_policy={config.execution_policy}",
        f"intraday_1m_row_count={len(intraday)}",
        f"daily_plan_count={len(plans)}",
        f"signal_event_count={summary['signal_event_count']}",
        f"entry_count={summary['entry_count']}",
        f"skipped_day_count={skipped}",
        "policy_flags=research_only=true;official_adoption_allowed=false;broker_action_allowed=false;protected_outputs_modified=false",
        "baseline_comparison:",
        comparison.to_string(index=False) if not comparison.empty else "none",
    ]
    (out_dir / "V21.179E_readable_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    summary = run_stage()
    print(json.dumps(summary, indent=2, default=str))
    return 0 if not str(summary.get("final_status", "")).startswith("FAIL") else 1


if __name__ == "__main__":
    raise SystemExit(main())
