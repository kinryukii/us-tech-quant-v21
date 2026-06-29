from __future__ import annotations

import hashlib
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

from scripts.v21 import v21_174_realistic_execution_backtest_and_tactical_trade_engine_r1 as v174


STAGE = "V21.176_DAILY_DRAM_PREMARKET_TRADE_PLAN_R1"
OUT = ROOT / "outputs" / "v21" / STAGE
R1C_OUT = ROOT / "outputs" / "v21" / "V21.174_R1C_AUTO_DRAM_PRICE_FETCH_AND_CACHE"
R1C_DAILY = R1C_OUT / "dram_auto_price_bridge_daily_ohlcv.csv"
R1C_ANCHOR = R1C_OUT / "dram_tactical_trade_plan_latest.csv"
PRICE_PATH = v174.PRICE_PATH

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "canonical_price_panel_modified": False,
    "daily_frequency_only": True,
    "intraday_required": False,
}

HORIZONS = {"1D": 1, "2D": 2, "5D": 5}
PLAN_OUTPUT_COLUMNS = [
    "plan_date",
    "target_trade_session",
    "ticker",
    "latest_close",
    "setup_classification",
    "final_decision",
    "position_mode",
    "planned_entry_base",
    "planned_entry_conservative",
    "no_chase_above",
    "stop_loss_base",
    "stop_loss_tight",
    "take_profit_1_base",
    "take_profit_2_base",
    "trade_allowed_daily_plan",
    "invalid_reason",
    "next_required_condition",
    "daily_frequency_only",
    "intraday_required",
    "research_only",
    "broker_action_allowed",
    "official_adoption_allowed",
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


def load_daily(path: Path = R1C_DAILY) -> pd.DataFrame:
    raw = read_csv(path)
    if raw.empty:
        return pd.DataFrame()
    required = {"date", "ticker", "open", "high", "low", "close"}
    if not required.issubset(raw.columns):
        return pd.DataFrame()
    df = raw.copy()
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df = df[df["ticker"].eq("DRAM")].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for c in ["open", "high", "low", "close", "volume"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "volume" not in df.columns:
        df["volume"] = 0
    df = df.dropna(subset=["date", "open", "high", "low", "close"])
    df = df[(df["open"] > 0) & (df["high"] > 0) & (df["low"] > 0) & (df["close"] > 0)]
    df = df[(df["high"] >= df[["open", "low", "close"]].max(axis=1)) & (df["low"] <= df[["open", "high", "close"]].min(axis=1))]
    return df.sort_values("date").drop_duplicates(["date", "ticker"], keep="last").reset_index(drop=True)


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(n, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).rolling(n, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    work = df.sort_values("date").copy()
    prev_close = work["close"].shift(1)
    tr = pd.concat(
        [
            work["high"] - work["low"],
            (work["high"] - prev_close).abs(),
            (work["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    work["atr14"] = tr.rolling(14, min_periods=14).mean()
    work["rsi14"] = rsi(work["close"])
    low9 = work["low"].rolling(9, min_periods=9).min()
    high9 = work["high"].rolling(9, min_periods=9).max()
    work["kdj_rsv"] = 100 * (work["close"] - low9) / (high9 - low9).replace(0, np.nan)
    work["kdj_k"] = work["kdj_rsv"].ewm(alpha=1 / 3, adjust=False, min_periods=1).mean()
    work["kdj_d"] = work["kdj_k"].ewm(alpha=1 / 3, adjust=False, min_periods=1).mean()
    work["kdj_j"] = 3 * work["kdj_k"] - 2 * work["kdj_d"]
    mid = work["close"].rolling(20, min_periods=20).mean()
    std = work["close"].rolling(20, min_periods=20).std()
    work["bb_middle"] = mid
    work["bb_upper"] = mid + 2 * std
    work["bb_lower"] = mid - 2 * std
    work["ema20"] = work["close"].ewm(span=20, adjust=False).mean()
    work["ema50"] = work["close"].ewm(span=50, adjust=False).mean()
    ema12 = work["close"].ewm(span=12, adjust=False).mean()
    ema26 = work["close"].ewm(span=26, adjust=False).mean()
    work["macd"] = ema12 - ema26
    work["macd_signal"] = work["macd"].ewm(span=9, adjust=False).mean()
    work["macd_hist"] = work["macd"] - work["macd_signal"]
    work["daily_return"] = work["close"].pct_change()
    work["gap_proxy"] = work["open"] / work["close"].shift(1) - 1
    vol_avg = work["volume"].rolling(20, min_periods=5).mean()
    work["volume_ratio"] = work["volume"] / vol_avg.replace(0, np.nan)
    return work.reset_index(drop=True)


def kdj_improving(ind: pd.DataFrame) -> bool:
    if len(ind) < 2:
        return False
    prev = ind.iloc[-2]
    cur = ind.iloc[-1]
    return bool(pd.notna(prev["kdj_k"]) and pd.notna(cur["kdj_k"]) and cur["kdj_k"] > prev["kdj_k"])


def bb_lower_bounce(ind: pd.DataFrame) -> bool:
    if ind.empty:
        return False
    cur = ind.iloc[-1]
    return bool(pd.notna(cur["bb_lower"]) and cur["low"] <= cur["bb_lower"] and cur["close"] > cur["bb_lower"])


def recent_20d_high_break(ind: pd.DataFrame) -> bool:
    if len(ind) < 21:
        return False
    latest_close = ind.iloc[-1]["close"]
    prior_high = ind.iloc[-21:-1]["high"].max()
    return bool(pd.notna(prior_high) and latest_close > prior_high)


def prior_breakout(ind: pd.DataFrame) -> bool:
    if len(ind) < 22:
        return False
    prev_close = ind.iloc[-2]["close"]
    prev_ret = ind.iloc[-2]["daily_return"]
    prior_high = ind.iloc[-22:-2]["high"].max()
    return bool((pd.notna(prior_high) and prev_close > prior_high) or (pd.notna(prev_ret) and prev_ret > 0.03))


def continuation_confirmed(ind: pd.DataFrame) -> bool:
    if len(ind) < 2 or not prior_breakout(ind):
        return False
    latest = ind.iloc[-1]
    prev = ind.iloc[-2]
    return bool(latest["close"] > prev["high"] or latest["close"] >= prev["close"])


def classify_daily_setup(ind: pd.DataFrame) -> str:
    if ind.empty or len(ind) < 20:
        return "DAILY_WEAK_NO_TRADE"
    cur = ind.iloc[-1]
    if continuation_confirmed(ind):
        return "DAILY_CONTINUATION_CONFIRMED"
    if recent_20d_high_break(ind) or (pd.notna(cur["daily_return"]) and cur["daily_return"] > 0.03):
        return "DAILY_BREAKOUT_FIRST_DAY"
    if pd.notna(cur["close"]) and pd.notna(cur["ema20"]) and cur["close"] >= cur["ema20"] and pd.notna(cur["rsi14"]) and cur["rsi14"] >= 45:
        return "DAILY_TREND_RECOVERY"
    near_ema20 = pd.notna(cur["ema20"]) and cur["close"] >= cur["ema20"] * 0.96
    near_bb_area = pd.notna(cur["bb_middle"]) and cur["close"] <= cur["bb_middle"] * 1.03
    rsi_not_collapsing = pd.notna(cur["rsi14"]) and cur["rsi14"] >= 40
    if near_ema20 and near_bb_area and rsi_not_collapsing:
        return "DAILY_PULLBACK_SETUP"
    if pd.notna(cur["rsi14"]) and cur["rsi14"] < 45 and (kdj_improving(ind) or bb_lower_bounce(ind)):
        return "DAILY_LOW_REVERSAL_WATCH"
    macd_bad = len(ind) >= 3 and pd.notna(cur["macd_hist"]) and pd.notna(ind.iloc[-3]["macd_hist"]) and cur["macd_hist"] < ind.iloc[-3]["macd_hist"]
    kdj_bad = not kdj_improving(ind)
    below_ema20 = pd.notna(cur["ema20"]) and cur["close"] < cur["ema20"]
    if pd.notna(cur["rsi14"]) and cur["rsi14"] < 45 and below_ema20 and macd_bad and kdj_bad:
        return "DAILY_WEAK_NO_TRADE"
    return "DAILY_WEAK_NO_TRADE"


def next_session_label(ind: pd.DataFrame) -> str:
    if len(ind) < 1:
        return ""
    return "NEXT_DAILY_SESSION_AFTER_" + str(pd.Timestamp(ind.iloc[-1]["date"]).date())


def trade_levels(close: float, atr: float) -> dict[str, float]:
    planned = close - 0.35 * atr
    conservative = close - 0.50 * atr
    stop_base = planned - atr
    stop_tight = planned - 0.6 * atr
    risk_base = planned - stop_base
    risk_tight = planned - stop_tight
    return {
        "planned_entry_base": planned,
        "planned_entry_conservative": conservative,
        "no_chase_above": close * 1.03,
        "stop_loss_base": stop_base,
        "stop_loss_tight": stop_tight,
        "take_profit_1_base": planned + 1.5 * risk_base,
        "take_profit_2_base": planned + 2.5 * risk_base,
        "reward_risk_base": 1.5,
        "reward_risk_tight": 1.2 if risk_tight > 0 else np.nan,
    }


def generate_daily_plan(ind: pd.DataFrame) -> dict[str, Any]:
    if ind.empty:
        return empty_plan("DRAM_DATA_MISSING", "DRAM_DATA_MISSING", "NO_TRADE", "daily data missing")
    if len(ind) < 30 or pd.isna(ind.iloc[-1].get("atr14")):
        return empty_plan("DRAM_INSUFFICIENT_HISTORY", "DRAM_INSUFFICIENT_HISTORY", "WAIT", "insufficient daily history")
    cur = ind.iloc[-1]
    setup = classify_daily_setup(ind)
    levels = trade_levels(float(cur["close"]), float(cur["atr14"]))
    latest_close = float(cur["close"])
    no_chase_block = latest_close > levels["no_chase_above"]
    if no_chase_block:
        decision = "DRAM_WAIT_FOR_PULLBACK"
        mode = "WAIT"
        allowed = False
        reason = "LATEST_CLOSE_ABOVE_NO_CHASE"
        condition = "Wait for daily pullback below no_chase_above."
    elif setup == "DAILY_BREAKOUT_FIRST_DAY":
        decision = "DRAM_NO_CHASE_FIRST_BREAKOUT_DAY"
        mode = "WAIT"
        allowed = False
        reason = "FIRST_BREAKOUT_DAY_NO_CHASE"
        condition = "Wait for pullback or confirmed continuation on a later daily bar."
    elif setup == "DAILY_CONTINUATION_CONFIRMED":
        decision = "DRAM_CONTINUATION_ALLOWED_LIMIT_ONLY"
        mode = "CONTINUATION_LIMIT"
        allowed = True
        reason = ""
        condition = "Use continuation limit only; do not chase above no_chase_above."
    elif setup in {"DAILY_PULLBACK_SETUP", "DAILY_LOW_REVERSAL_WATCH", "DAILY_TREND_RECOVERY"}:
        decision = "DRAM_TRADE_ALLOWED_LIMIT_ONLY"
        mode = "LIMIT_ONLY"
        allowed = True
        reason = ""
        condition = "Place daily limit near planned_entry; no intraday monitoring required."
    else:
        decision = "DRAM_DAILY_WEAK_NO_TRADE"
        mode = "NO_TRADE"
        allowed = False
        reason = "DAILY_WEAK_NO_TRADE"
        condition = "Wait for daily trend, pullback, or reversal setup improvement."
    return {
        "plan_date": str(pd.Timestamp(cur["date"]).date()),
        "target_trade_session": next_session_label(ind),
        "ticker": "DRAM",
        "latest_close": latest_close,
        "setup_classification": setup,
        "final_decision": decision,
        "position_mode": mode,
        **levels,
        "trade_allowed_daily_plan": allowed,
        "invalid_reason": reason,
        "next_required_condition": condition,
        "daily_frequency_only": True,
        "intraday_required": False,
        "research_only": True,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
    }


def empty_plan(decision: str, setup: str, mode: str, reason: str) -> dict[str, Any]:
    return {
        "plan_date": "",
        "target_trade_session": "",
        "ticker": "DRAM",
        "latest_close": np.nan,
        "setup_classification": setup,
        "final_decision": decision,
        "position_mode": mode,
        "planned_entry_base": np.nan,
        "planned_entry_conservative": np.nan,
        "no_chase_above": np.nan,
        "stop_loss_base": np.nan,
        "stop_loss_tight": np.nan,
        "take_profit_1_base": np.nan,
        "take_profit_2_base": np.nan,
        "trade_allowed_daily_plan": False,
        "invalid_reason": reason,
        "next_required_condition": reason,
        "daily_frequency_only": True,
        "intraday_required": False,
        "research_only": True,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
    }


def simulate_plan(plan: dict[str, Any], future: pd.DataFrame, horizon: str) -> dict[str, Any]:
    common = {
        "plan_date": plan["plan_date"],
        "horizon": horizon,
        "ticker": "DRAM",
        "planned_entry": plan["planned_entry_base"],
        "no_chase_above": plan["no_chase_above"],
        "stop_loss": plan["stop_loss_base"],
        "take_profit_1": plan["take_profit_1_base"],
        "take_profit_2": plan["take_profit_2_base"],
        "setup_classification": plan["setup_classification"],
        "final_decision": plan["final_decision"],
    }
    if not plan.get("trade_allowed_daily_plan", False) or future.empty:
        return {
            **common,
            "filled": False,
            "fill_date": "",
            "fill_price": np.nan,
            "exit_date": "",
            "exit_price": np.nan,
            "exit_reason": "INVALID" if not plan.get("trade_allowed_daily_plan", False) else "NO_FILL",
            "realistic_pnl_pct": np.nan,
            "max_adverse_excursion_pct": np.nan,
            "max_favorable_excursion_pct": np.nan,
            "stop_hit": False,
            "tp1_hit": False,
            "tp2_hit": False,
        }
    entry = float(plan["planned_entry_base"])
    fill_idx = None
    for idx, row in future.iterrows():
        if float(row["low"]) <= entry <= float(row["high"]):
            fill_idx = idx
            break
    if fill_idx is None:
        return {
            **common,
            "filled": False,
            "fill_date": "",
            "fill_price": np.nan,
            "exit_date": "",
            "exit_price": np.nan,
            "exit_reason": "NO_FILL",
            "realistic_pnl_pct": 0.0,
            "max_adverse_excursion_pct": np.nan,
            "max_favorable_excursion_pct": np.nan,
            "stop_hit": False,
            "tp1_hit": False,
            "tp2_hit": False,
        }
    path = future.loc[fill_idx:].copy()
    stop = float(plan["stop_loss_base"])
    tp1 = float(plan["take_profit_1_base"])
    tp2 = float(plan["take_profit_2_base"])
    exit_price = float(path.iloc[-1]["close"])
    exit_date = pd.Timestamp(path.iloc[-1]["date"])
    exit_reason = "HORIZON_EXIT"
    stop_hit = tp1_hit = tp2_hit = False
    lows: list[float] = []
    highs: list[float] = []
    for _, bar in path.iterrows():
        low = float(bar["low"])
        high = float(bar["high"])
        lows.append(low)
        highs.append(high)
        if low <= stop:
            stop_hit = True
            exit_price = stop
            exit_date = pd.Timestamp(bar["date"])
            exit_reason = "STOP_LOSS"
            break
        if high >= tp2:
            tp1_hit = True
            tp2_hit = True
            exit_price = tp2
            exit_date = pd.Timestamp(bar["date"])
            exit_reason = "TAKE_PROFIT_2"
            break
        if high >= tp1:
            tp1_hit = True
            exit_price = tp1
            exit_date = pd.Timestamp(bar["date"])
            exit_reason = "TAKE_PROFIT_1"
            break
    return {
        **common,
        "filled": True,
        "fill_date": str(pd.Timestamp(future.loc[fill_idx, "date"]).date()),
        "fill_price": entry,
        "exit_date": str(exit_date.date()),
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "realistic_pnl_pct": exit_price / entry - 1.0,
        "max_adverse_excursion_pct": min(lows) / entry - 1.0 if lows else np.nan,
        "max_favorable_excursion_pct": max(highs) / entry - 1.0 if highs else np.nan,
        "stop_hit": stop_hit,
        "tp1_hit": tp1_hit,
        "tp2_hit": tp2_hit,
    }


def backtest_daily_plans(ind: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if len(ind) < 35:
        return pd.DataFrame(), pd.DataFrame()
    rows: list[dict[str, Any]] = []
    eligible = list(range(29, len(ind) - 1))[-20:]
    for i in eligible:
        hist = ind.iloc[: i + 1].copy()
        plan = generate_daily_plan(hist)
        for horizon, days in HORIZONS.items():
            future = ind.iloc[i + 1 : min(i + 1 + days, len(ind))].copy()
            rows.append(simulate_plan(plan, future, horizon))
    bt = pd.DataFrame(rows)
    if bt.empty:
        return bt, pd.DataFrame()
    filled = bt[bt["filled"].astype(bool)]
    pnl = pd.to_numeric(filled.get("realistic_pnl_pct", pd.Series(dtype=float)), errors="coerce")
    summary = pd.DataFrame(
        [
            {
                "plan_count": int(bt["plan_date"].nunique()),
                "row_count": len(bt),
                "filled_count": int(bt["filled"].astype(bool).sum()),
                "no_fill_count": int(bt["exit_reason"].eq("NO_FILL").sum()),
                "stop_loss_count": int(bt["exit_reason"].eq("STOP_LOSS").sum()),
                "tp1_count": int(bt["exit_reason"].eq("TAKE_PROFIT_1").sum()),
                "tp2_count": int(bt["exit_reason"].eq("TAKE_PROFIT_2").sum()),
                "horizon_exit_count": int(bt["exit_reason"].eq("HORIZON_EXIT").sum()),
                "avg_realistic_pnl": float(pnl.mean()) if not pnl.empty else np.nan,
                "median_realistic_pnl": float(pnl.median()) if not pnl.empty else np.nan,
                "win_rate": float((pnl > 0).mean()) if not pnl.empty else np.nan,
            }
        ]
    )
    return bt, summary


def write_blocked(out_dir: Path, final_status: str, decision: str, warnings: list[str]) -> dict[str, Any]:
    pd.DataFrame().to_csv(out_dir / "dram_daily_signal_indicators.csv", index=False)
    pd.DataFrame([{"setup_classification": "DRAM_DATA_MISSING", "final_decision": "DRAM_DATA_MISSING"}]).to_csv(out_dir / "dram_daily_setup_classification.csv", index=False)
    pd.DataFrame([empty_plan("DRAM_DATA_MISSING", "DRAM_DATA_MISSING", "NO_TRADE", "daily data missing")]).reindex(columns=PLAN_OUTPUT_COLUMNS).to_csv(out_dir / "dram_daily_premarket_trade_plan_latest.csv", index=False)
    pd.DataFrame().to_csv(out_dir / "dram_daily_plan_backtest.csv", index=False)
    pd.DataFrame().to_csv(out_dir / "dram_daily_plan_backtest_summary.csv", index=False)
    summary = {
        "final_status": final_status,
        "decision": decision,
        "latest_dram_date": "",
        "valid_row_count": 0,
        "setup_classification": "DRAM_DATA_MISSING",
        "final_trade_decision": "DRAM_DATA_MISSING",
        "position_mode": "NO_TRADE",
        "trade_allowed_daily_plan": False,
        "planned_entry_base": np.nan,
        "no_chase_above": np.nan,
        "stop_loss_base": np.nan,
        "take_profit_1_base": np.nan,
        "backtest_plan_count": 0,
        "backtest_filled_count": 0,
        "backtest_no_fill_count": 0,
        "backtest_stop_loss_count": 0,
        "backtest_tp1_count": 0,
        "backtest_tp2_count": 0,
        "backtest_avg_realistic_pnl": np.nan,
        "warnings": warnings,
        **POLICY,
    }
    (out_dir / "V21.176_daily_dram_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_report(summary, out_dir)
    return summary


def write_report(summary: dict[str, Any], out_dir: Path = OUT) -> None:
    lines = [
        STAGE,
        f"final_status: {summary['final_status']}",
        f"decision: {summary['decision']}",
        f"latest_dram_date: {summary['latest_dram_date']}",
        f"setup_classification: {summary['setup_classification']}",
        f"final_trade_decision: {summary['final_trade_decision']}",
        f"position_mode: {summary['position_mode']}",
        f"planned_entry_base: {summary['planned_entry_base']}",
        f"no_chase_above: {summary['no_chase_above']}",
        f"stop_loss_base: {summary['stop_loss_base']}",
        f"take_profit_1_base: {summary['take_profit_1_base']}",
        f"trade_allowed_daily_plan: {summary['trade_allowed_daily_plan']}",
        f"backtest filled/no-fill/stop/tp1/tp2: {summary['backtest_filled_count']} / {summary['backtest_no_fill_count']} / {summary['backtest_stop_loss_count']} / {summary['backtest_tp1_count']} / {summary['backtest_tp2_count']}",
        "warnings:",
        *([f"- {w}" for w in summary["warnings"]] if summary["warnings"] else ["- none"]),
        "daily_frequency_only: True",
        "intraday_required: False",
        "research_only: True",
        "broker_action_allowed: False",
        "official_adoption_allowed: False",
    ]
    (out_dir / "V21.176_daily_dram_readable_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(out_dir: Path = OUT, daily_path: Path = R1C_DAILY) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    pre_hash = sha(PRICE_PATH)
    daily = load_daily(daily_path)
    if daily.empty:
        write_blocked(out_dir, "BLOCKED_V21_176_DAILY_DRAM_DATA_MISSING", "DAILY_DRAM_PLAN_BLOCKED_DATA_MISSING", ["WARN_R1C_DAILY_DRAM_DATA_MISSING"])
        return 0
    ind = compute_indicators(daily)
    ind.to_csv(out_dir / "dram_daily_signal_indicators.csv", index=False)
    warnings: list[str] = []
    if len(ind) < 30:
        warnings.append("WARN_INSUFFICIENT_DAILY_HISTORY")
        plan = generate_daily_plan(ind)
        bt, bt_summary = pd.DataFrame(), pd.DataFrame()
        final_status = "WARN_V21_176_DAILY_DRAM_INSUFFICIENT_HISTORY"
        decision = "DAILY_DRAM_PLAN_WAIT_MORE_HISTORY"
    else:
        plan = generate_daily_plan(ind)
        bt, bt_summary = backtest_daily_plans(ind)
        final_status = "PASS_V21_176_DAILY_DRAM_PLAN_READY"
        decision = "DAILY_DRAM_PREMARKET_PLAN_READY_RESEARCH_ONLY"
    pd.DataFrame([{"setup_classification": plan["setup_classification"], "final_decision": plan["final_decision"], "position_mode": plan["position_mode"]}]).to_csv(out_dir / "dram_daily_setup_classification.csv", index=False)
    pd.DataFrame([plan]).reindex(columns=PLAN_OUTPUT_COLUMNS).to_csv(out_dir / "dram_daily_premarket_trade_plan_latest.csv", index=False)
    bt.to_csv(out_dir / "dram_daily_plan_backtest.csv", index=False)
    bt_summary.to_csv(out_dir / "dram_daily_plan_backtest_summary.csv", index=False)
    srow = bt_summary.iloc[0].to_dict() if not bt_summary.empty else {}
    post_hash = sha(PRICE_PATH)
    summary = {
        "final_status": final_status,
        "decision": decision,
        "latest_dram_date": str(pd.Timestamp(ind.iloc[-1]["date"]).date()),
        "valid_row_count": len(ind),
        "setup_classification": plan["setup_classification"],
        "final_trade_decision": plan["final_decision"],
        "position_mode": plan["position_mode"],
        "trade_allowed_daily_plan": bool(plan["trade_allowed_daily_plan"]),
        "planned_entry_base": plan["planned_entry_base"],
        "no_chase_above": plan["no_chase_above"],
        "stop_loss_base": plan["stop_loss_base"],
        "take_profit_1_base": plan["take_profit_1_base"],
        "backtest_plan_count": int(srow.get("plan_count", 0) or 0),
        "backtest_filled_count": int(srow.get("filled_count", 0) or 0),
        "backtest_no_fill_count": int(srow.get("no_fill_count", 0) or 0),
        "backtest_stop_loss_count": int(srow.get("stop_loss_count", 0) or 0),
        "backtest_tp1_count": int(srow.get("tp1_count", 0) or 0),
        "backtest_tp2_count": int(srow.get("tp2_count", 0) or 0),
        "backtest_avg_realistic_pnl": srow.get("avg_realistic_pnl", np.nan),
        "warnings": warnings,
        **{**POLICY, "canonical_price_panel_modified": pre_hash != post_hash},
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(out_dir),
    }
    (out_dir / "V21.176_daily_dram_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_report(summary, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
