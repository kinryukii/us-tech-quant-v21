"""Executable ETF labels, deliberately separate from opportunity/direction diagnostics."""
from __future__ import annotations

import hashlib
import pandas as pd

from ..backtest.cost_model import RoundTripCost
from ..backtest.exit_engine import evaluate_exit
from ..common.contracts import ContractViolation, ExecutableContract, assert_confirmation_forbidden


ETF_MAP = {("SOXX", "UP"): "SOXL", ("SOXX", "DOWN"): "SOXS", ("QQQ", "UP"): "TQQQ", ("QQQ", "DOWN"): "SQQQ"}


def stable_event_id(underlying_symbol: str, direction: str, timestamp_et) -> str:
    material = f"FAST3-002|{underlying_symbol}|{direction}|{pd.Timestamp(timestamp_et).isoformat()}"
    return "FAST3-002-" + hashlib.sha256(material.encode()).hexdigest()[:20]


def _bars(frame: pd.DataFrame) -> pd.DataFrame:
    x = frame.copy()
    x["timestamp_et"] = pd.to_datetime(x.timestamp_et, errors="raise")
    x["timestamp_utc"] = pd.to_datetime(x.timestamp_utc, utc=True, errors="raise")
    return x.sort_values("timestamp_utc", kind="mergesort").drop_duplicates("timestamp_utc").reset_index(drop=True)


def _entry_bar(bars: pd.DataFrame, decision_timestamp_et, mode: str):
    decision = pd.Timestamp(decision_timestamp_et)
    # Strictly later timestamp: the decision bar can never be an entry bar.
    next_bars = bars[bars.timestamp_et > decision]
    if next_bars.empty:
        return None, None, None
    row = next_bars.iloc[0]
    if mode == "MODE_A_NEXT_BAR_OPEN":
        return row, float(row.open), "NEXT_BAR_OPEN"
    if mode == "MODE_B_NEXT_BAR_VWAP_PROXY":
        return row, float((row.high + row.low + row.close) / 3.0), "NEXT_BAR_VWAP_PROXY_RESEARCH_ONLY"
    raise ContractViolation("UNKNOWN_ENTRY_MODE")


def diagnostic_labels(entry_price: float, entry_bar: pd.Series, bars: pd.DataFrame, max_holding_minutes: int) -> tuple[int, int]:
    """Opportunity/direction labels never substitute for executable P&L."""
    end = pd.Timestamp(entry_bar.timestamp_et) + pd.Timedelta(minutes=max_holding_minutes)
    path = bars[(bars.timestamp_et >= entry_bar.timestamp_et) & (bars.timestamp_et <= end)]
    if path.empty:
        return 0, 0
    opportunity = int(max(path.high.max() / entry_price - 1, 1 - path.low.min() / entry_price) >= 0.01)
    direction = int(path.iloc[-1].close > entry_price) - int(path.iloc[-1].close < entry_price)
    return opportunity, direction


def build_executable_trade_labels(signals: pd.DataFrame, etf_bars: dict[str, pd.DataFrame], contract: ExecutableContract,
                                  cost_bps: int, entry_mode: str | None = None) -> pd.DataFrame:
    """Build one fully executable ETF label per signal without portfolio acceptance."""
    required = {"decision_timestamp_et", "underlying_symbol", "direction"}
    if missing := required - set(signals.columns):
        raise ContractViolation(f"MISSING_SIGNAL_FIELDS:{sorted(missing)}")
    assert_confirmation_forbidden(signals.decision_timestamp_et, contract.confirmation_start_et)
    mode = entry_mode or contract.default_entry_mode
    if cost_bps not in contract.round_trip_cost_bps:
        raise ContractViolation("UNREGISTERED_COST_SCENARIO")
    cache = {sym: _bars(df) for sym, df in etf_bars.items()}
    out = []
    for signal in signals.itertuples(index=False):
        s = signal._asdict()
        trade_symbol = s.get("trade_symbol") or ETF_MAP.get((s["underlying_symbol"], s["direction"]))
        if trade_symbol is None or trade_symbol not in cache:
            out.append({**s, "event_id": s.get("event_id") or stable_event_id(s["underlying_symbol"], s["direction"], s["decision_timestamp_et"]),
                        "trade_symbol": trade_symbol, "trade_accepted": False, "trade_rejection_reason": "REAL_ETF_DATA_MISSING"})
            continue
        bars = cache[trade_symbol]
        row, price, source = _entry_bar(bars, s["decision_timestamp_et"], mode)
        event_id = s.get("event_id") or stable_event_id(s["underlying_symbol"], s["direction"], s["decision_timestamp_et"])
        if row is None:
            out.append({**s, "event_id": event_id, "trade_symbol": trade_symbol, "trade_accepted": False, "trade_rejection_reason": "NO_NEXT_EXECUTABLE_BAR"})
            continue
        result = evaluate_exit(bars=bars, entry_timestamp_et=row.timestamp_et, entry_price=price,
                               max_holding_minutes=contract.max_holding_minutes, target_net_return=contract.target_net_return,
                               stop_gross_return=contract.stop_gross_return, cost=RoundTripCost(cost_bps))
        opportunity, direction_label = diagnostic_labels(price, row, bars, contract.max_holding_minutes)
        out.append({**s, "event_id": event_id, "trade_symbol": trade_symbol, "entry_timestamp": row.timestamp_et,
                    "entry_timestamp_et": row.timestamp_et, "entry_timestamp_utc": row.timestamp_utc,
                    "entry_price": price, "entry_price_source": source, "opportunity_label": opportunity,
                    "direction_label": direction_label, "executable_trade_label": int(result.net_return > 0),
                    "contract_config_sha256": contract.config_hash, "cost_scenario_bps_round_trip": cost_bps,
                    "priority": s.get("priority", 0), **result.as_dict()})
    return pd.DataFrame(out)
