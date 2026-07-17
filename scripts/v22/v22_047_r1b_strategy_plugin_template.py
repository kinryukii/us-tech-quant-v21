"""The single V22.047 strategy plug-in entry point.

R1F enables the V8.0 reference trend-rotation state machine by passing an
explicit ``r1f_enabled`` context.  Older R1B/R1D callers remain safely
unconfigured.  This module has no account sizing, order, or broker API code.
"""
from __future__ import annotations

import math
from copy import deepcopy
from datetime import datetime
from typing import Any, Mapping, Sequence

CORE_QQQ = 0
LEVERAGED_BULL = 1
TACTICAL_DEFENSE = -1

STATE_NAMES = {CORE_QQQ: "CORE_QQQ", LEVERAGED_BULL: "LEVERAGED_BULL", TACTICAL_DEFENSE: "TACTICAL_DEFENSE"}
STATE_WEIGHTS = {
    CORE_QQQ: {"US.QQQ": 100, "US.TQQQ": 0, "US.SQQQ": 0, "US.IQQQ": 0},
    LEVERAGED_BULL: {"US.QQQ": 75, "US.TQQQ": 25, "US.SQQQ": 0, "US.IQQQ": 0},
    TACTICAL_DEFENSE: {"US.QQQ": 90, "US.TQQQ": 0, "US.SQQQ": 10, "US.IQQQ": 0},
}

PARAMETERS = {
    "periodic_rebalance_days": 21,
    "sma_fast_period": 20,
    "sma_medium_period": 50,
    "sma_slow_period": 200,
    "sma_slow_slope_lookback": 20,
    "momentum_short_days": 21,
    "momentum_medium_days": 63,
    "momentum_long_days": 126,
    "vol_short_days": 20,
    "vol_long_days": 60,
    "bull_confirm_days": 3,
    "bull_exit_confirm_days": 2,
    "bull_vol_ratio_max_pct": 115,
    "bull_exit_vol_ratio_pct": 140,
    "bear_confirm_days": 2,
    "bear_momentum_21_max_pct": -5,
    "sqqq_max_hold_days": 3,
    "sqqq_reentry_cooldown_days": 2,
    "tqqq_hard_stop_pct": 10,
    "sqqq_hard_stop_pct": 6,
    "sqqq_profit_lock_trigger_pct": 8,
    "sqqq_trailing_drawdown_pct": 3,
}


def default_v8_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "active_state": CORE_QQQ,
        "state_entry_day": 0,
        "trading_day_index": 0,
        "bull_confirm_count": 0,
        "bull_exit_count": 0,
        "bear_confirm_count": 0,
        "last_sqqq_exit_day": -10000,
        "last_tqqq_exit_day": -10000,
        "tqqq_entry_reference": 0.0,
        "sqqq_entry_reference": 0.0,
        "sqqq_highest_price": 0.0,
        "last_decision_date": "",
        "last_rebalance_date": "",
        "last_rebalance_day_index": -10000,
        "last_completed_daily_date": "",
    }


def _positive(value: Any) -> bool:
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


def percent_change(new_value: float, old_value: float) -> float:
    return (new_value - old_value) / old_value * 100 if _positive(old_value) else 0.0


def simple_moving_average(values: Sequence[float], period: int, offset: int = 0) -> float:
    end = len(values) - offset
    start = end - period
    if period <= 0 or start < 0 or end <= 0:
        return 0.0
    window = values[start:end]
    return sum(window) / period if len(window) == period and all(_positive(x) for x in window) else 0.0


def momentum_pct(values: Sequence[float], lookback: int) -> float:
    if lookback <= 0 or len(values) <= lookback:
        return 0.0
    return percent_change(float(values[-1]), float(values[-1 - lookback]))


def realized_volatility_pct(values: Sequence[float], period: int) -> float:
    if period <= 1 or len(values) < period + 1:
        return 0.0
    window = values[-(period + 1):]
    if not all(_positive(x) for x in window):
        return 0.0
    returns = [(float(window[i]) - float(window[i - 1])) / float(window[i - 1]) for i in range(1, len(window))]
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / len(returns)
    return max(variance, 0.0) ** 0.5 * (252 ** 0.5) * 100


def _bar_date(bar: Mapping[str, Any]) -> str:
    raw = str(bar.get("time_key") or bar.get("date") or "")
    return raw[:10] if len(raw) >= 10 else ""


def completed_daily_series(bars: Sequence[Mapping[str, Any]], current_et_date: str) -> tuple[list[float], list[str]]:
    by_date: dict[str, float] = {}
    for bar in bars:
        date = _bar_date(bar)
        close = bar.get("close")
        if date and date != current_et_date and _positive(close):
            by_date[date] = float(close)
    dates = sorted(by_date)
    return [by_date[date] for date in dates], dates


def _advance_day_index(state: dict[str, Any], dates: Sequence[str]) -> None:
    if not dates:
        return
    marker = str(state.get("last_completed_daily_date", ""))
    if not marker:
        state["trading_day_index"] = max(int(state.get("trading_day_index", 0)), len(dates))
    else:
        state["trading_day_index"] = int(state.get("trading_day_index", 0)) + sum(date > marker for date in dates)
    state["last_completed_daily_date"] = dates[-1]


def _transition(state: dict[str, Any], target: int, reason: str, prices: Mapping[str, float], decision_date: str) -> None:
    changed = target != int(state["active_state"])
    state["active_state"] = target
    if changed:
        state["state_entry_day"] = int(state["trading_day_index"])
        if target == LEVERAGED_BULL:
            state["tqqq_entry_reference"] = float(prices.get("US.TQQQ", 0.0) or 0.0)
        else:
            state["tqqq_entry_reference"] = 0.0
        if target == TACTICAL_DEFENSE:
            price = float(prices.get("US.SQQQ", 0.0) or 0.0)
            state["sqqq_entry_reference"] = price
            state["sqqq_highest_price"] = price
        else:
            state["sqqq_entry_reference"] = 0.0
            state["sqqq_highest_price"] = 0.0
    state["last_rebalance_date"] = decision_date
    state["last_rebalance_day_index"] = int(state["trading_day_index"])
    state["last_transition_reason"] = reason


def _intraday_risk(state: dict[str, Any], prices: Mapping[str, float], owned: Mapping[str, Any], date: str, p: Mapping[str, Any]) -> str | None:
    active = int(state["active_state"])
    if active == LEVERAGED_BULL and float(owned.get("US.TQQQ", 0) or 0) > 0:
        price = float(prices.get("US.TQQQ", 0) or 0)
        if _positive(price):
            if not _positive(state.get("tqqq_entry_reference")):
                state["tqqq_entry_reference"] = price
            if percent_change(price, float(state["tqqq_entry_reference"])) <= -float(p["tqqq_hard_stop_pct"]):
                state["last_tqqq_exit_day"] = int(state["trading_day_index"])
                state["bull_confirm_count"] = state["bull_exit_count"] = 0
                _transition(state, CORE_QQQ, "TQQQ_DISASTER_STOP_TO_QQQ", prices, date)
                return "TQQQ_DISASTER_STOP_TO_QQQ"
    if active == TACTICAL_DEFENSE and float(owned.get("US.SQQQ", 0) or 0) > 0:
        price = float(prices.get("US.SQQQ", 0) or 0)
        if _positive(price):
            if not _positive(state.get("sqqq_entry_reference")):
                state["sqqq_entry_reference"] = price
            state["sqqq_highest_price"] = max(float(state.get("sqqq_highest_price", 0) or 0), price)
            ret = percent_change(price, float(state["sqqq_entry_reference"]))
            peak = percent_change(float(state["sqqq_highest_price"]), float(state["sqqq_entry_reference"]))
            drawdown = percent_change(price, float(state["sqqq_highest_price"]))
            if ret <= -float(p["sqqq_hard_stop_pct"]):
                reason = "SQQQ_HARD_STOP_TO_QQQ"
            elif peak >= float(p["sqqq_profit_lock_trigger_pct"]) and drawdown <= -float(p["sqqq_trailing_drawdown_pct"]):
                reason = "SQQQ_TRAILING_PROFIT_TO_QQQ"
            else:
                reason = ""
            if reason:
                state["last_sqqq_exit_day"] = int(state["trading_day_index"])
                state["bear_confirm_count"] = 0
                _transition(state, CORE_QQQ, reason, prices, date)
                return reason
    return None


def evaluate_v8_reference(
    closes: Sequence[float], dates: Sequence[str], prior_state: Mapping[str, Any], prices: Mapping[str, float],
    strategy_owned_qty: Mapping[str, Any], decision_date: str, *, decision_due: bool,
    parameters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    p = {**PARAMETERS, **dict(parameters or {})}
    state = {**default_v8_state(), **deepcopy(dict(prior_state or {}))}
    _advance_day_index(state, dates)
    risk_reason = _intraday_risk(state, prices, strategy_owned_qty, decision_date, p)
    if risk_reason:
        return {"state": state, "reason_code": risk_reason, "rebalance_requested": True, "indicators": {}}
    if not decision_due:
        return {"state": state, "reason_code": "OUTSIDE_DAILY_DECISION_POINT", "rebalance_requested": False, "indicators": {}}
    if state.get("last_decision_date") == decision_date:
        return {"state": state, "reason_code": "DAILY_DECISION_ALREADY_COMPLETED", "rebalance_requested": False, "indicators": {}}
    state["last_decision_date"] = decision_date
    minimum = int(p["sma_slow_period"]) + int(p["sma_slow_slope_lookback"]) + 2
    if len(closes) < minimum:
        requested = int(state["active_state"]) != CORE_QQQ
        if requested:
            _transition(state, CORE_QQQ, "INSUFFICIENT_HISTORY", prices, decision_date)
        return {"state": state, "reason_code": "INSUFFICIENT_HISTORY", "rebalance_requested": requested, "indicators": {"bars": len(closes), "required": minimum}}

    close = float(closes[-1]); sma20 = simple_moving_average(closes, int(p["sma_fast_period"])); sma50 = simple_moving_average(closes, int(p["sma_medium_period"]))
    sma200 = simple_moving_average(closes, int(p["sma_slow_period"])); sma200_old = simple_moving_average(closes, int(p["sma_slow_period"]), int(p["sma_slow_slope_lookback"]))
    mom5 = momentum_pct(closes, 5); mom21 = momentum_pct(closes, int(p["momentum_short_days"])); mom63 = momentum_pct(closes, int(p["momentum_medium_days"])); mom126 = momentum_pct(closes, int(p["momentum_long_days"]))
    vol20 = realized_volatility_pct(closes, int(p["vol_short_days"])); vol60 = realized_volatility_pct(closes, int(p["vol_long_days"]))
    if not all(_positive(x) for x in (close, sma20, sma50, sma200, sma200_old, vol20, vol60)):
        return {"state": state, "reason_code": "INDICATOR_DATA_INVALID", "rebalance_requested": False, "indicators": {}}
    ratio = vol20 / vol60 * 100
    bull = close > sma200 and close > sma20 and sma50 > sma200 and sma200 > sma200_old and mom63 > 0 and mom126 > 0 and ratio <= float(p["bull_vol_ratio_max_pct"])
    bull_exit = close < sma50 or mom63 <= 0 or ratio >= float(p["bull_exit_vol_ratio_pct"])
    bear = close < sma200 and close < sma20 and sma50 < sma200 and sma200 < sma200_old and mom63 < 0 and mom21 <= float(p["bear_momentum_21_max_pct"])
    state["bull_confirm_count"] = int(state["bull_confirm_count"]) + 1 if bull else 0
    state["bear_confirm_count"] = int(state["bear_confirm_count"]) + 1 if bear else 0
    state["bull_exit_count"] = int(state["bull_exit_count"]) + 1 if bull_exit else 0
    hold_days = int(state["trading_day_index"]) - int(state["state_entry_day"])
    indicators = {"close":close,"sma20":sma20,"sma50":sma50,"sma200":sma200,"sma200_old":sma200_old,"momentum5":mom5,"momentum21":mom21,"momentum63":mom63,"momentum126":mom126,"vol20":vol20,"vol60":vol60,"vol_ratio_pct":ratio,"bull_raw":bull,"bull_exit_raw":bull_exit,"bear_raw":bear,"state_hold_days":hold_days}
    active = int(state["active_state"]); reason = "V8_STATE_HOLD"; requested = False
    if active == LEVERAGED_BULL:
        if int(state["bull_exit_count"]) >= int(p["bull_exit_confirm_days"]):
            reason, requested = "BULL_TREND_EXIT_TO_QQQ", True; _transition(state, CORE_QQQ, reason, prices, decision_date)
        elif int(p["periodic_rebalance_days"]) > 0 and int(state["trading_day_index"]) - int(state["state_entry_day"]) >= int(p["periodic_rebalance_days"]):
            reason, requested = "PERIODIC_BULL_REBALANCE", True; _transition(state, LEVERAGED_BULL, reason, prices, decision_date)
    elif active == TACTICAL_DEFENSE:
        if hold_days >= int(p["sqqq_max_hold_days"]) or close > sma20 or mom5 > 0 or not bear:
            state["last_sqqq_exit_day"] = int(state["trading_day_index"])
            reason, requested = "TACTICAL_DEFENSE_EXIT_TO_QQQ", True; _transition(state, CORE_QQQ, reason, prices, decision_date)
    else:
        if int(state["bull_confirm_count"]) >= int(p["bull_confirm_days"]):
            reason, requested = "LOW_VOL_BULL_TREND_CONFIRMED", True; _transition(state, LEVERAGED_BULL, reason, prices, decision_date)
        elif int(state["bear_confirm_count"]) >= int(p["bear_confirm_days"]) and int(state["trading_day_index"]) - int(state["last_sqqq_exit_day"]) >= int(p["sqqq_reentry_cooldown_days"]):
            reason, requested = "TACTICAL_BEAR_DEFENSE_CONFIRMED", True; _transition(state, TACTICAL_DEFENSE, reason, prices, decision_date)
        elif int(p["periodic_rebalance_days"]) > 0 and int(state["trading_day_index"]) - int(state.get("last_rebalance_day_index", -10000)) >= int(p["periodic_rebalance_days"]):
            reason, requested = "PERIODIC_CORE_REBALANCE", True; _transition(state, CORE_QQQ, reason, prices, decision_date)
    return {"state": state, "reason_code": reason, "rebalance_requested": requested, "indicators": indicators}


def generate_decision(context: Mapping[str, Any]) -> dict[str, Any]:
    if not context.get("r1f_enabled"):
        return {"action":"HOLD","symbol":None,"target_notional_usd":0.0,"confidence":0.0,"reason_code":"STRATEGY_NOT_CONFIGURED","metadata":{}}
    market = context.get("market", {}); bars = market.get("qqq_klines", {}).get("K_DAY", {}).get("bars", [])
    current_date = str(context.get("current_et_date") or datetime.utcnow().date().isoformat())
    closes, dates = completed_daily_series(bars, current_date)
    result = evaluate_v8_reference(closes, dates, context.get("r1f_state", {}), context.get("prices", {}),
                                   context.get("strategy_owned_qty", {}), current_date,
                                   decision_due=bool(context.get("decision_due")), parameters=context.get("strategy_parameters", {}))
    state = result["state"]; active = int(state["active_state"])
    return {
        "action":"HOLD", "symbol":None, "target_notional_usd":0.0, "confidence":1.0,
        "reason_code":str(result["reason_code"]),
        "metadata":{"strategy_configured":True,"strategy_name":"V8_REFERENCE_TREND_ROTATION","active_state":active,
                    "active_state_name":STATE_NAMES[active],"target_weights":STATE_WEIGHTS[active],
                    "rebalance_requested":bool(result["rebalance_requested"]),"updated_state":state,"indicators":result["indicators"]},
    }
