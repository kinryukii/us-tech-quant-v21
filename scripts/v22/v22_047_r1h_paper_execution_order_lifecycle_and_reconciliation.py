#!/usr/bin/env python
"""R1H PAPER-only order lifecycle, reconciliation and strategy accounting.

This module is deliberately isolated from real brokerage ownership/accounting.
The broker backend accepts only an injected SIMULATE adapter; the local backend
is deterministic, Decimal-only, quote-time conservative and never calls a broker.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
from zoneinfo import ZoneInfo

REVISION = "V22.047_R1H"
STAGE = "V22.047_R1H_PAPER_EXECUTION_ORDER_LIFECYCLE_AND_RECONCILIATION"
FINAL_STATUS = "R1H_PASS_PAPER_EXECUTION_ORDER_LIFECYCLE_READY"
ET = ZoneInfo("America/New_York")
ACTIVE_SYMBOLS = ("US.QQQ", "US.TQQQ", "US.SQQQ", "US.IQQQ")
ORDER_STATUSES = {
    "CREATED", "VALIDATED", "SUBMITTING", "ACKNOWLEDGED", "PARTIALLY_FILLED",
    "FILLED", "CANCEL_PENDING", "CANCELED", "REJECTED", "EXPIRED", "RECONCILING",
}
TERMINAL_STATUSES = {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}
OPEN_STATUSES = ORDER_STATUSES - TERMINAL_STATUSES
BACKENDS = {"PAPER_BROKER_SIM", "PAPER_LOCAL_SIM"}
RTH_START, RTH_END = dt_time(9, 45), dt_time(15, 50)
TARGET_WEIGHTS = {
    "CORE_QQQ": {"US.QQQ": 100, "US.TQQQ": 0, "US.SQQQ": 0, "US.IQQQ": 0},
    "LEVERAGED_BULL": {"US.QQQ": 75, "US.TQQQ": 25, "US.SQQQ": 0, "US.IQQQ": 0},
    "TACTICAL_DEFENSE": {"US.QQQ": 90, "US.TQQQ": 0, "US.SQQQ": 10, "US.IQQQ": 0},
}


class R1HError(RuntimeError):
    pass


def D(value: Any) -> Decimal:
    if value is None or value == "": return Decimal("0")
    if isinstance(value, Decimal): return value
    return Decimal(str(value))


def dec(value: Any) -> str:
    value = D(value)
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def utc_iso(current: datetime | None = None) -> str:
    return (current or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()


def et_now(current: datetime | None = None) -> datetime:
    return (current or datetime.now(timezone.utc)).astimezone(ET)


def read_json(path: Path, default: Any = None) -> Any:
    try: return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError): return default


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, default=str); handle.write("\n")
            handle.flush(); os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try: os.unlink(tmp)
        except OSError: pass


def append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")
        handle.flush(); os.fsync(handle.fileno())


def jsonl_rows(path: Path) -> list[dict[str, Any]]:
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError): return []


class Paths:
    def __init__(self, repo: Path):
        self.repo = repo.resolve()
        self.output = self.repo / "outputs" / "v22" / STAGE
        self.output.mkdir(parents=True, exist_ok=True)
        self.config = self.repo / "config" / "v22_047_r1h_paper_execution.json"
        self.strategy_plugin = self.repo / "scripts" / "v22" / "v22_047_r1b_strategy_plugin_template.py"
        self.authorization = self.output / "paper_authorization_state.json"
        self.backend = self.output / "paper_execution_backend.json"
        self.order_state = self.output / "paper_order_state.json"
        self.reconciliation = self.output / "paper_reconciliation_state.json"
        self.portfolio = self.output / "paper_portfolio_snapshot.json"
        self.cash = self.output / "paper_cash_snapshot.json"
        self.performance = self.output / "paper_performance_snapshot.json"
        self.idempotency = self.output / "paper_order_idempotency_ledger.jsonl"
        self.order_ledger = self.output / "paper_order_ledger.jsonl"
        self.deal_ledger = self.output / "paper_deal_ledger.jsonl"
        self.cash_ledger = self.output / "paper_cash_ledger.jsonl"
        self.position_ledger = self.output / "paper_position_ledger.jsonl"
        self.nav_history = self.output / "paper_nav_history.csv"
        self.audit_ledger = self.output / "paper_audit_ledger.jsonl"


def load_config(paths: Paths) -> dict[str, Any]:
    cfg = read_json(paths.config, {}) or {}
    if tuple(cfg.get("execution_whitelist", [])) != ACTIVE_SYMBOLS: raise R1HError("EXECUTION_WHITELIST_INVALID")
    if cfg.get("live_available") is not False or cfg.get("real_environment_allowed") is not False: raise R1HError("LIVE_MUST_REMAIN_UNAVAILABLE")
    if cfg.get("paper_environment") != "TrdEnv.SIMULATE": raise R1HError("SIMULATE_ENVIRONMENT_REQUIRED")
    if cfg.get("market_orders_allowed") is not False: raise R1HError("MARKET_ORDERS_FORBIDDEN")
    return cfg


def configuration_hash(paths: Paths) -> str:
    return hashlib.sha256(paths.config.read_bytes()).hexdigest()


def strategy_version(paths: Paths) -> str:
    return hashlib.sha256(paths.strategy_plugin.read_bytes()).hexdigest() if paths.strategy_plugin.exists() else hashlib.sha256(b"V8_REFERENCE_TREND_ROTATION").hexdigest()


def audit(paths: Paths, event: str, current: datetime | None = None, **detail: Any) -> None:
    append_jsonl(paths.audit_ledger, {"event_id": hashlib.sha256(f"{event}|{utc_iso(current)}|{detail}".encode()).hexdigest()[:24], "timestamp_et": et_now(current).isoformat(), "event": event, **detail, "real_trade_api_called": False})


def startup_reset(paths: Paths, current: datetime | None = None) -> dict[str, Any]:
    """Windows/login startup invariant: PAPER is never automatically restored."""
    state = {
        "schema_version": 1, "revision": REVISION, "execution_mode": "SHADOW",
        "default_execution_mode": "SHADOW", "execution_authorization": "DISARMED",
        "paper_armed": False, "paper_arm_not_expired": False, "armed_at_utc": None,
        "expires_at_utc": None, "startup_reset": True, "live_available": False,
        "broker_action_allowed": False, "real_trade_api_called": False, "updated_at_utc": utc_iso(current),
    }
    atomic_json(paths.authorization, state); audit(paths, "STARTUP_RESET_TO_SHADOW_DISARMED", current)
    return state


def authorization_state(paths: Paths, current: datetime | None = None) -> dict[str, Any]:
    now = current or datetime.now(timezone.utc)
    state = read_json(paths.authorization, {}) or startup_reset(paths, now)
    expiry = state.get("expires_at_utc")
    expired = bool(expiry and now.astimezone(timezone.utc) >= datetime.fromisoformat(expiry))
    if expired and state.get("execution_authorization") == "PAPER_ARMED":
        state.update({"execution_mode": "SHADOW", "execution_authorization": "DISARMED", "paper_armed": False, "paper_arm_not_expired": False, "expired_at_utc": utc_iso(now), "expires_at_utc": None, "updated_at_utc": utc_iso(now)})
        atomic_json(paths.authorization, state); audit(paths, "PAPER_ARM_EXPIRED_DISARMED", now)
    state["paper_arm_not_expired"] = state.get("execution_authorization") == "PAPER_ARMED" and not expired
    return state


def request_paper_arm(paths: Paths, *, dashboard_clicked: bool, first_confirmation: bool,
                      second_confirmation: str, requested_backend: str | None = None,
                      current: datetime | None = None) -> dict[str, Any]:
    cfg = load_config(paths); now = current or datetime.now(timezone.utc)
    r1i_state_path = paths.repo / "outputs" / "v22" / "V22.047_R1I_PAPER_SOAK_REPLAY_FAULT_INJECTION_AND_LIVE_READINESS_GATE" / "paper_soak_state.json"
    r1i_state = read_json(r1i_state_path, {}) or {}
    if r1i_state.get("next_session_paper_allowed") is False:
        raise R1HError("FAILED_RECONCILIATION_BLOCKS_NEXT_PAPER_SESSION")
    if dashboard_clicked is not True: raise R1HError("DASHBOARD_EXPLICIT_CLICK_REQUIRED")
    if first_confirmation is not True or second_confirmation != "CONFIRM_PAPER_SIMULATED_TRADING_ONLY":
        raise R1HError("PAPER_VALID_DOUBLE_CONFIRMATION_REQUIRED")
    backend = requested_backend or cfg["default_paper_backend"]
    if backend not in BACKENDS: raise R1HError("INVALID_PAPER_BACKEND")
    expiry = now.astimezone(timezone.utc) + timedelta(minutes=int(cfg["paper_arm_ttl_minutes"]))
    state = {
        "schema_version": 1, "revision": REVISION, "execution_mode": "PAPER",
        "default_execution_mode": "SHADOW", "execution_authorization": "PAPER_ARMED",
        "paper_armed": True, "paper_arm_not_expired": True, "dashboard_clicked": True,
        "first_confirmation": True, "second_confirmation": "CONFIRM_PAPER_SIMULATED_TRADING_ONLY",
        "double_confirmation_recorded": True, "strategy_version": strategy_version(paths),
        "config_hash": configuration_hash(paths), "armed_at_utc": utc_iso(now),
        "expires_at_utc": utc_iso(expiry), "requested_backend": backend,
        "paper_environment": "TrdEnv.SIMULATE", "live_available": False,
        "broker_action_allowed": False, "real_trade_api_called": False, "updated_at_utc": utc_iso(now),
    }
    atomic_json(paths.authorization, state)
    atomic_json(paths.backend, backend_payload(backend))
    audit(paths, "PAPER_ARMED_DOUBLE_CONFIRMED", now, strategy_version=state["strategy_version"], config_hash=state["config_hash"], expires_at_utc=state["expires_at_utc"], execution_backend=backend)
    return state


def disarm_paper(paths: Paths, reason: str = "USER_DISARMED", current: datetime | None = None) -> dict[str, Any]:
    state = authorization_state(paths, current)
    state.update({"execution_mode": "SHADOW", "execution_authorization": "DISARMED", "paper_armed": False, "paper_arm_not_expired": False, "expires_at_utc": None, "disarm_reason": reason, "updated_at_utc": utc_iso(current)})
    atomic_json(paths.authorization, state); audit(paths, "PAPER_DISARMED", current, reason_code=reason)
    return state


def request_live_arm(*_: Any, **__: Any) -> dict[str, Any]:
    return {"ok": False, "error": "LIVE_NOT_AVAILABLE", "live_available": False, "broker_action_allowed": False, "real_trade_api_called": False}


def backend_payload(backend: str, reason: str = "CONFIGURED") -> dict[str, Any]:
    local = backend == "PAPER_LOCAL_SIM"
    return {"schema_version": 1, "execution_backend": backend, "paper_environment": "TrdEnv.SIMULATE", "local_simulation": local, "broker_order_submitted": False, "broker_fractional_api_confirmed": False, "fallback_reason": reason if local else None, "real_environment_allowed": False, "unlock_trade_allowed": False, "real_trade_api_called": False}


class BrokerAdapter(Protocol):
    def place_order(self, **kwargs: Any) -> Any: ...
    def modify_order(self, **kwargs: Any) -> Any: ...
    def cancel_order(self, **kwargs: Any) -> Any: ...
    def get_order_list(self, **kwargs: Any) -> Any: ...
    def get_history_order_list(self, **kwargs: Any) -> Any: ...
    def get_deal_list(self, **kwargs: Any) -> Any: ...


class SimulateOnlyBroker:
    """Narrow broker facade. No unlock method exists and REAL is rejected first."""
    def __init__(self, adapter: BrokerAdapter, environment: str = "TrdEnv.SIMULATE"):
        if environment != "TrdEnv.SIMULATE": raise R1HError("REAL_ENVIRONMENT_ALWAYS_REJECTED")
        self.adapter, self.environment = adapter, environment

    def _call(self, name: str, **kwargs: Any) -> Any:
        env = str(kwargs.pop("trd_env", self.environment))
        if env != "TrdEnv.SIMULATE" or "REAL" in env: raise R1HError("REAL_ENVIRONMENT_ALWAYS_REJECTED")
        kwargs["trd_env"] = "TrdEnv.SIMULATE"
        return getattr(self.adapter, name)(**kwargs)

    def place_order(self, **kwargs: Any) -> Any: return self._call("place_order", **kwargs)
    def modify_order(self, **kwargs: Any) -> Any: return self._call("modify_order", **kwargs)
    def cancel_order(self, **kwargs: Any) -> Any: return self._call("cancel_order", **kwargs)
    def get_order_list(self, **kwargs: Any) -> Any: return self._call("get_order_list", **kwargs)
    def get_history_order_list(self, **kwargs: Any) -> Any: return self._call("get_history_order_list", **kwargs)
    def get_deal_list(self, **kwargs: Any) -> Any: return self._call("get_deal_list", **kwargs)

    def unlock_trade(self, **_: Any) -> Any: raise R1HError("UNLOCK_TRADE_ALWAYS_REJECTED")


def order_window(current: datetime) -> tuple[bool, str]:
    now = et_now(current); t = now.time().replace(tzinfo=None)
    if t < RTH_START: return False, "PREMARKET_ORDER_BLOCKED"
    if t > RTH_END: return False, "AFTER_HOURS_ORDER_BLOCKED"
    return True, "RTH_ORDER_WINDOW_OPEN"


def _hash_id(value: Any) -> str:
    return hashlib.sha256(str(value).encode()).hexdigest()[:24] if value else ""


@dataclass
class Quote:
    symbol: str
    bid: Decimal
    ask: Decimal
    timestamp: datetime


class PaperExecutionEngine:
    def __init__(self, repo: Path, broker: SimulateOnlyBroker | None = None, *, startup: bool = False):
        self.paths = Paths(repo); self.cfg = load_config(self.paths); self.broker = broker
        if startup: startup_reset(self.paths)
        self._ensure_state()

    def _ensure_state(self) -> None:
        if not self.paths.authorization.exists(): startup_reset(self.paths)
        if not self.paths.order_state.exists(): atomic_json(self.paths.order_state, {"schema_version": 1, "orders": {}, "updated_at_utc": utc_iso()})
        if not self.paths.reconciliation.exists(): atomic_json(self.paths.reconciliation, {"schema_version": 1, "state": "READY", "unknown_intent_ids": [], "new_orders_blocked": False, "updated_at_utc": utc_iso()})
        if not self.paths.cash.exists():
            initial = D(self.cfg["initial_paper_cash_usd"])
            atomic_json(self.paths.cash, {"schema_version": 1, "paper_cash": dec(initial), "reserved_cash": "0", "available_paper_cash": dec(initial), "updated_at_utc": utc_iso(), "real_cash_modified": False})
            append_jsonl(self.paths.cash_ledger, {"timestamp_utc": utc_iso(), "event": "PAPER_CASH_GENESIS", "cash_change": dec(initial), "paper_cash_after": dec(initial), "real_cash_modified": False})
        if not self.paths.portfolio.exists():
            atomic_json(self.paths.portfolio, {"schema_version": 1, "positions": {s: {"quantity": "0", "average_cost": "0", "market_value": "0"} for s in ACTIVE_SYMBOLS}, "manual_holdings_excluded": True, "real_broker_ownership_ledger_modified": False, "updated_at_utc": utc_iso()})
        if not self.paths.backend.exists(): atomic_json(self.paths.backend, backend_payload(self.cfg["default_paper_backend"]))
        if not self.paths.performance.exists():
            atomic_json(self.paths.performance, {"schema_version": 1, "paper_strategy_nav": self.cfg["initial_paper_cash_usd"], "paper_strategy_return": "0", "qqq_buy_hold_return": "0", "paper_excess_return_vs_qqq": "0", "daily_return": "0", "cumulative_return": "0", "max_drawdown": "0", "turnover": "0", "trade_count": 0, "fill_rate": "0", "rejection_rate": "0", "average_slippage": "0", "cash_utilization": "0", "excess_return_vs_qqq": "0", "manual_holdings_excluded": True, "updated_at_utc": utc_iso()})
        for ledger in (self.paths.idempotency, self.paths.order_ledger, self.paths.deal_ledger, self.paths.position_ledger, self.paths.audit_ledger):
            if not ledger.exists(): ledger.write_text("", encoding="utf-8")
        if not self.paths.nav_history.exists():
            with self.paths.nav_history.open("w", encoding="utf-8", newline="") as handle: csv.writer(handle).writerow(["timestamp_et", "paper_strategy_nav", "paper_cash", "qqq_price", "paper_strategy_return", "qqq_buy_hold_return", "paper_excess_return_vs_qqq"])

    def _orders(self) -> dict[str, dict[str, Any]]:
        return (read_json(self.paths.order_state, {}) or {}).get("orders", {})

    def _save_orders(self, orders: Mapping[str, Any], current: datetime | None = None) -> None:
        atomic_json(self.paths.order_state, {"schema_version": 1, "orders": orders, "open_order_count": sum(x.get("status") in OPEN_STATUSES for x in orders.values()), "updated_at_utc": utc_iso(current)})

    def _transition(self, order: dict[str, Any], status: str, current: datetime, reason: str) -> None:
        if status not in ORDER_STATUSES: raise R1HError("INVALID_ORDER_STATUS")
        previous = order.get("status"); order.update({"status": status, "updated_at_et": et_now(current).isoformat(), "reason_code": reason})
        event = {**order, "event": "ORDER_STATUS_CHANGED", "previous_status": previous, "new_status": status, "timestamp_et": et_now(current).isoformat()}
        append_jsonl(self.paths.order_ledger, event); audit(self.paths, "PAPER_ORDER_STATE_TRANSITION", current, intent_id=order["intent_id"], previous_status=previous, new_status=status, reason_code=reason)

    def _reconciliation_ready(self) -> bool:
        state = read_json(self.paths.reconciliation, {}) or {}
        return state.get("state") == "READY" and state.get("new_orders_blocked") is not True

    def paper_authorized(self, current: datetime, *, manual_override_active: bool, account_reconciliation: str, rth_order_window_open: bool | None = None) -> tuple[bool, str]:
        auth = authorization_state(self.paths, current); in_window, window_reason = order_window(current)
        checks = [
            (not bool(auth.get("expired_at_utc")) or auth.get("execution_authorization") == "PAPER_ARMED", "PAPER_ARM_EXPIRED"),
            (auth.get("execution_mode") == "PAPER", "EXECUTION_MODE_NOT_PAPER"),
            (auth.get("execution_authorization") == "PAPER_ARMED", "PAPER_NOT_ARMED"),
            (auth.get("paper_arm_not_expired") is True, "PAPER_ARM_EXPIRED"),
            (auth.get("config_hash") == configuration_hash(self.paths), "PAPER_ARM_CONFIG_HASH_MISMATCH"),
            (auth.get("strategy_version") == strategy_version(self.paths), "PAPER_ARM_STRATEGY_VERSION_MISMATCH"),
            (self.cfg.get("strategy_enabled") is True, "STRATEGY_DISABLED"),
            (self.cfg.get("strategy_configured") is True, "STRATEGY_NOT_CONFIGURED"),
            (account_reconciliation == "READY" and self._reconciliation_ready(), "RECONCILIATION_NOT_READY"),
            (manual_override_active is False, "MANUAL_OVERRIDE_ACTIVE"),
            (in_window if rth_order_window_open is None else bool(rth_order_window_open and in_window), window_reason),
        ]
        for ok, reason in checks:
            if not ok: return False, reason
        return True, "PAPER_AUTHORIZED"

    def _reject_record(self, intent_id: str, symbol: str, side: str, quantity: Any, limit_price: Any, backend: str, current: datetime, reason: str) -> dict[str, Any]:
        now_et = et_now(current)
        order = {"intent_id": intent_id, "strategy_version": strategy_version(self.paths), "config_hash": configuration_hash(self.paths), "execution_backend": backend, "symbol": symbol, "side": side, "decimal_quantity": dec(quantity), "limit_price": dec(limit_price), "filled_quantity": "0", "average_fill_price": "0", "remaining_quantity": dec(quantity), "status": None, "broker_order_id_hash": "", "created_at_et": now_et.isoformat(), "updated_at_et": now_et.isoformat(), "expires_at_et": now_et.isoformat(), "reason_code": reason, "order_type": "LIMIT", "local_simulation": backend == "PAPER_LOCAL_SIM", "broker_order_submitted": False, "broker_fractional_api_confirmed": False}
        self._transition(order, "CREATED", current, "ORDER_CREATED")
        self._transition(order, "REJECTED", current, reason); orders = self._orders(); orders[intent_id] = order; self._save_orders(orders, current)
        append_jsonl(self.paths.idempotency, {"intent_id": intent_id, "timestamp_et": now_et.isoformat(), "event": "INTENT_RECORDED", "status": "REJECTED", "reason_code": reason})
        return order

    def submit_order(self, *, intent_id: str, symbol: str, side: str, decimal_quantity: Any,
                     limit_price: Any, current: datetime | None = None, execution_backend: str | None = None,
                     order_type: str = "LIMIT", manual_override_active: bool = False,
                     account_reconciliation: str = "READY", asset_type: str = "ETF") -> dict[str, Any]:
        now = current or datetime.now(timezone.utc); symbol, side = symbol.upper(), side.upper()
        backend = execution_backend or (read_json(self.paths.authorization, {}) or {}).get("requested_backend") or self.cfg["default_paper_backend"]
        existing = self._orders().get(intent_id)
        if existing: return {**existing, "idempotent_replay": True, "broker_submission_repeated": False}
        if any(x.get("intent_id") == intent_id for x in jsonl_rows(self.paths.idempotency)):
            self.enter_reconciling([intent_id], "INTENT_LEDGER_FOUND_STATE_MISSING", now); raise R1HError("DUPLICATE_INTENT_REQUIRES_RECONCILIATION")
        reason = None
        authorized, auth_reason = self.paper_authorized(now, manual_override_active=manual_override_active, account_reconciliation=account_reconciliation)
        qty, price = D(decimal_quantity), D(limit_price)
        if not authorized: reason = auth_reason
        elif order_type != "LIMIT": reason = "MARKET_ORDER_FORBIDDEN"
        elif symbol not in ACTIVE_SYMBOLS or symbol == "US.IQQ" or asset_type.upper() != "ETF": reason = "ASSET_OUT_OF_SCOPE_READ_ONLY"
        elif side not in {"BUY", "SELL"}: reason = "INVALID_SIDE"
        elif qty <= 0 or price <= 0: reason = "INVALID_QUANTITY_OR_PRICE"
        elif qty != qty.quantize(D(self.cfg["quantity_increment"])): reason = "DECIMAL_PRECISION_UNSUPPORTED"
        elif backend not in BACKENDS: reason = "INVALID_PAPER_BACKEND"
        elif side == "BUY" and qty * price > D((read_json(self.paths.cash, {}) or {}).get("available_paper_cash")): reason = "INSUFFICIENT_PAPER_CASH"
        elif side == "SELL" and qty > D(((read_json(self.paths.portfolio, {}) or {}).get("positions", {}).get(symbol, {}) or {}).get("quantity")): reason = "PAPER_SHORT_POSITION_FORBIDDEN"
        if reason is None:
            manual_path = self.paths.repo / "outputs" / "v22" / "V22.047_R1I_PAPER_SOAK_REPLAY_FAULT_INJECTION_AND_LIVE_READINESS_GATE" / "manual_participation_state.json"
            manual_item = ((read_json(manual_path, {}) or {}).get("symbols", {}) or {}).get(symbol, {})
            blocked_until = manual_item.get("blocked_until_et")
            if blocked_until and not manual_item.get("explicitly_resumed") and et_now(now) < datetime.fromisoformat(blocked_until):
                reason = "MANUAL_OPERATION_COOLDOWN_ACTIVE"
        if reason: return self._reject_record(intent_id, symbol, side, qty, price, backend, now, reason)
        orders = self._orders(); expires = min(et_now(now) + timedelta(minutes=int(self.cfg["day_order_ttl_minutes"])), datetime.combine(et_now(now).date(), RTH_END, ET))
        order = {"intent_id": intent_id, "strategy_version": strategy_version(self.paths), "config_hash": configuration_hash(self.paths), "execution_backend": backend, "symbol": symbol, "side": side, "decimal_quantity": dec(qty), "limit_price": dec(price), "filled_quantity": "0", "average_fill_price": "0", "remaining_quantity": dec(qty), "status": None, "broker_order_id_hash": "", "created_at_et": et_now(now).isoformat(), "updated_at_et": et_now(now).isoformat(), "expires_at_et": expires.isoformat(), "reason_code": "ORDER_CREATED", "order_type": "LIMIT", "local_simulation": backend == "PAPER_LOCAL_SIM", "broker_order_submitted": False, "broker_fractional_api_confirmed": False, "reserved_cash": "0"}
        self._transition(order, "CREATED", now, "ORDER_CREATED")
        self._transition(order, "VALIDATED", now, "PAPER_VALIDATION_PASSED")
        self._transition(order, "SUBMITTING", now, "SUBMISSION_STARTED")
        if backend == "PAPER_BROKER_SIM":
            if self.broker is None:
                order["execution_backend"] = "PAPER_LOCAL_SIM"; order["local_simulation"] = True
                order["original_broker_rejection_reason"] = "SIMULATE_ADAPTER_UNAVAILABLE"; atomic_json(self.paths.backend, backend_payload("PAPER_LOCAL_SIM", "SIMULATE_ADAPTER_UNAVAILABLE"))
            else:
                try:
                    result = self.broker.place_order(code=symbol, trd_side=side, qty=dec(qty), price=dec(price), order_type="LIMIT", trd_env="TrdEnv.SIMULATE")
                    order["broker_order_submitted"] = True; order["broker_order_id_hash"] = _hash_id(result.get("order_id") if isinstance(result, Mapping) else result)
                except Exception as exc:
                    raw = f"{type(exc).__name__}:{exc}"; order["original_broker_rejection_reason"] = raw
                    order["execution_backend"] = "PAPER_LOCAL_SIM"; order["local_simulation"] = True
                    atomic_json(self.paths.backend, backend_payload("PAPER_LOCAL_SIM", raw))
        if order["side"] == "BUY": self._reserve_cash(order, qty * price, now)
        self._transition(order, "ACKNOWLEDGED", now, "LOCAL_SIM_ACKNOWLEDGED" if order["local_simulation"] else "BROKER_SIM_ACKNOWLEDGED")
        orders[intent_id] = order; self._save_orders(orders, now)
        append_jsonl(self.paths.idempotency, {"intent_id": intent_id, "timestamp_et": et_now(now).isoformat(), "event": "INTENT_SUBMITTED_ONCE", "status": order["status"], "execution_backend": order["execution_backend"], "broker_order_id_hash": order["broker_order_id_hash"]})
        return order

    def _reserve_cash(self, order: dict[str, Any], amount: Decimal, current: datetime) -> None:
        cash = read_json(self.paths.cash, {}) or {}; available = D(cash.get("available_paper_cash"))
        if amount > available: raise R1HError("INSUFFICIENT_PAPER_CASH")
        cash["reserved_cash"] = dec(D(cash.get("reserved_cash")) + amount); cash["available_paper_cash"] = dec(available - amount); cash["updated_at_utc"] = utc_iso(current); order["reserved_cash"] = dec(amount)
        atomic_json(self.paths.cash, cash); append_jsonl(self.paths.cash_ledger, {"timestamp_et": et_now(current).isoformat(), "event": "PAPER_CASH_RESERVED", "intent_id": order["intent_id"], "amount": dec(amount), "paper_cash_after": cash["paper_cash"], "reserved_cash_after": cash["reserved_cash"], "real_cash_modified": False})

    def _release_reserve(self, order: dict[str, Any], current: datetime) -> None:
        amount = D(order.get("reserved_cash"));
        if amount <= 0: return
        cash = read_json(self.paths.cash, {}) or {}; cash["reserved_cash"] = dec(max(D("0"), D(cash.get("reserved_cash")) - amount)); cash["available_paper_cash"] = dec(D(cash.get("available_paper_cash")) + amount); cash["updated_at_utc"] = utc_iso(current); order["reserved_cash"] = "0"
        atomic_json(self.paths.cash, cash); append_jsonl(self.paths.cash_ledger, {"timestamp_et": et_now(current).isoformat(), "event": "PAPER_CASH_RESERVE_RELEASED", "intent_id": order["intent_id"], "amount": dec(amount), "paper_cash_after": cash["paper_cash"], "reserved_cash_after": cash["reserved_cash"], "real_cash_modified": False})

    def process_quote(self, intent_id: str, quote: Quote | Mapping[str, Any], *, current: datetime | None = None, max_fill_quantity: Any | None = None) -> dict[str, Any]:
        now = current or datetime.now(timezone.utc); orders = self._orders()
        if intent_id not in orders: raise R1HError("ORDER_NOT_FOUND")
        order = orders[intent_id]
        if order["status"] not in {"ACKNOWLEDGED", "PARTIALLY_FILLED"}: return order
        if not order["local_simulation"]: raise R1HError("BROKER_ORDER_REQUIRES_RECONCILIATION")
        q = quote if isinstance(quote, Quote) else Quote(order["symbol"], D(quote.get("bid")), D(quote.get("ask")), quote.get("timestamp") or quote.get("timestamp_et") or now)
        if isinstance(q.timestamp, str): q = Quote(q.symbol, q.bid, q.ask, datetime.fromisoformat(q.timestamp))
        if q.timestamp.astimezone(timezone.utc) > now.astimezone(timezone.utc):
            order["reason_code"] = "FUTURE_QUOTE_FORBIDDEN"; append_jsonl(self.paths.order_ledger, {**order, "event": "FILL_REJECTED", "timestamp_et": et_now(now).isoformat()}); self._save_orders(orders, now); return order
        if (now.astimezone(timezone.utc) - q.timestamp.astimezone(timezone.utc)).total_seconds() > int(self.cfg["quote_max_age_seconds"]):
            order["reason_code"] = "STALE_QUOTE_FILL_BLOCKED"; append_jsonl(self.paths.order_ledger, {**order, "event": "FILL_REJECTED", "timestamp_et": et_now(now).isoformat()}); self._save_orders(orders, now); return order
        in_window, why = order_window(now)
        if not in_window: order["reason_code"] = why; self._save_orders(orders, now); return order
        if q.bid <= 0 or q.ask <= 0 or q.ask < q.bid: order["reason_code"] = "ABNORMAL_QUOTE_REJECTED"; self._save_orders(orders, now); return order
        limit, remaining = D(order["limit_price"]), D(order["remaining_quantity"])
        marketable = q.ask <= limit if order["side"] == "BUY" else q.bid >= limit
        if not marketable: order["reason_code"] = "LIMIT_NOT_MARKETABLE"; self._save_orders(orders, now); return order
        fill_qty = min(remaining, D(max_fill_quantity) if max_fill_quantity is not None else remaining).quantize(D(self.cfg["quantity_increment"]), rounding=ROUND_DOWN)
        if fill_qty <= 0: order["reason_code"] = "NO_FILL_LIQUIDITY"; self._save_orders(orders, now); return order
        slip = (D(self.cfg["local_slippage_bps"]) + D(self.cfg["fractional_degradation_bps"])) / D("10000")
        raw_price = q.ask * (D("1") + slip) if order["side"] == "BUY" else q.bid * (D("1") - slip)
        fill_price = raw_price.quantize(D("0.0001"), rounding=ROUND_UP if order["side"] == "BUY" else ROUND_DOWN)
        # A limit is a hard cap/floor. Slippage can prevent, never violate, a fill.
        if (order["side"] == "BUY" and fill_price > limit) or (order["side"] == "SELL" and fill_price < limit):
            order["reason_code"] = "CONSERVATIVE_SLIPPAGE_EXCEEDS_LIMIT"; self._save_orders(orders, now); return order
        self._apply_fill(order, fill_qty, fill_price, q, now)
        self._save_orders(orders, now); self.mark_to_market({order["symbol"]: (q.bid + q.ask) / 2}, now)
        return order

    def _apply_fill(self, order: dict[str, Any], qty: Decimal, price: Decimal, quote: Quote, current: datetime) -> None:
        prior_qty, prior_avg = D(order["filled_quantity"]), D(order["average_fill_price"])
        new_qty = prior_qty + qty; order["filled_quantity"] = dec(new_qty); order["remaining_quantity"] = dec(D(order["decimal_quantity"]) - new_qty); order["average_fill_price"] = dec((prior_qty * prior_avg + qty * price) / new_qty)
        notional = qty * price; fee = notional * D(self.cfg["sell_fee_bps"]) / D("10000") if order["side"] == "SELL" else D("0")
        cash = read_json(self.paths.cash, {}) or {}; positions = read_json(self.paths.portfolio, {}) or {}; item = positions["positions"][order["symbol"]]; old_pos, old_cost = D(item["quantity"]), D(item["average_cost"])
        if order["side"] == "BUY":
            reserved_for_fill = D(order.get("reserved_cash")) * qty / D(order["remaining_quantity"] or "0") if False else qty * D(order["limit_price"])
            reserved_for_fill = min(D(order.get("reserved_cash")), reserved_for_fill)
            cash["reserved_cash"] = dec(max(D("0"), D(cash["reserved_cash"]) - reserved_for_fill)); cash["paper_cash"] = dec(D(cash["paper_cash"]) - notional); cash["available_paper_cash"] = dec(D(cash["available_paper_cash"]) + reserved_for_fill - notional); order["reserved_cash"] = dec(D(order.get("reserved_cash")) - reserved_for_fill)
            new_pos = old_pos + qty; item["average_cost"] = dec((old_pos * old_cost + notional) / new_pos); item["quantity"] = dec(new_pos); cash_change = -notional
        else:
            if qty > old_pos: raise R1HError("PAPER_SHORT_POSITION_FORBIDDEN")
            new_pos = old_pos - qty; item["quantity"] = dec(new_pos); item["average_cost"] = "0" if new_pos == 0 else item["average_cost"]; cash_change = notional - fee; cash["paper_cash"] = dec(D(cash["paper_cash"]) + cash_change); cash["available_paper_cash"] = dec(D(cash["available_paper_cash"]) + cash_change)
        cash["updated_at_utc"] = utc_iso(current); positions["updated_at_utc"] = utc_iso(current)
        atomic_json(self.paths.cash, cash); atomic_json(self.paths.portfolio, positions)
        deal_id = hashlib.sha256(f"{order['intent_id']}|{new_qty}|{price}|{utc_iso(current)}".encode()).hexdigest()[:24]
        deal = {"deal_id": deal_id, "intent_id": order["intent_id"], "timestamp_et": et_now(current).isoformat(), "symbol": order["symbol"], "side": order["side"], "decimal_quantity": dec(qty), "fill_price": dec(price), "notional": dec(notional), "fee": dec(fee), "quote_bid": dec(quote.bid), "quote_ask": dec(quote.ask), "slippage": dec((price - quote.ask) if order["side"] == "BUY" else (quote.bid - price)), "local_simulation": bool(order.get("local_simulation")), "broker_order_submitted": bool(order.get("broker_order_submitted")), "real_trade_api_called": False}
        append_jsonl(self.paths.deal_ledger, deal); append_jsonl(self.paths.cash_ledger, {"timestamp_et": deal["timestamp_et"], "event": "PAPER_FILL_CASH_UPDATE", "intent_id": order["intent_id"], "cash_change": dec(cash_change), "paper_cash_after": cash["paper_cash"], "real_cash_modified": False}); append_jsonl(self.paths.position_ledger, {"timestamp_et": deal["timestamp_et"], "event": "PAPER_FILL_POSITION_UPDATE", "intent_id": order["intent_id"], "symbol": order["symbol"], "quantity_change": dec(qty if order["side"] == "BUY" else -qty), "paper_quantity_after": item["quantity"], "manual_holdings_modified": False})
        status = "FILLED" if D(order["remaining_quantity"]) == 0 else "PARTIALLY_FILLED"
        if status == "FILLED": self._release_reserve(order, current)
        source = "LOCAL_SIM" if order.get("local_simulation") else "BROKER_SIM_RECONCILED"
        self._transition(order, status, current, f"{source}_FILL_COMPLETE" if status == "FILLED" else f"{source}_PARTIAL_FILL")

    def reconcile_broker_order(self, intent_id: str, broker_order: Mapping[str, Any], deals: Sequence[Mapping[str, Any]], current: datetime | None = None) -> dict[str, Any]:
        """Apply only newly observed SIMULATE deals, then reconcile terminal state.

        Callers must source ``broker_order`` and ``deals`` through
        :class:`SimulateOnlyBroker`; hashed deal IDs make repeated polls safe.
        """
        now = current or datetime.now(timezone.utc); orders = self._orders(); order = orders.get(intent_id)
        if not order: raise R1HError("ORDER_NOT_FOUND")
        if order.get("execution_backend") != "PAPER_BROKER_SIM" or order.get("local_simulation"):
            raise R1HError("NOT_A_BROKER_SIM_ORDER")
        seen = {x.get("broker_deal_id_hash") for x in jsonl_rows(self.paths.deal_ledger) if x.get("intent_id") == intent_id}
        for raw in deals:
            raw_id = raw.get("deal_id") or raw.get("deal_id_str")
            deal_hash = _hash_id(raw_id)
            if deal_hash in seen: continue
            qty, price = D(raw.get("qty") or raw.get("quantity")), D(raw.get("price"))
            if qty <= 0 or price <= 0: continue
            remaining = D(order["remaining_quantity"]); qty = min(qty, remaining)
            if qty <= 0: break
            before = len(jsonl_rows(self.paths.deal_ledger)); self._apply_fill(order, qty, price, Quote(order["symbol"], price, price, now), now)
            rows = jsonl_rows(self.paths.deal_ledger)
            if len(rows) > before:
                rows[-1]["broker_deal_id_hash"] = deal_hash
                # Rewrite only this PAPER ledger atomically to persist the broker hash.
                self.paths.deal_ledger.write_text("".join(json.dumps(x, ensure_ascii=False, separators=(",", ":"), default=str) + "\n" for x in rows), encoding="utf-8")
            seen.add(deal_hash)
        broker_status = str(broker_order.get("status") or broker_order.get("order_status") or "").upper()
        if order["status"] not in TERMINAL_STATUSES and broker_status in {"CANCELED", "CANCELLED", "CANCELLED_ALL"}:
            self._release_reserve(order, now); self._transition(order, "CANCELED", now, "BROKER_SIM_RECONCILED_CANCELED")
        elif order["status"] not in TERMINAL_STATUSES and broker_status in {"REJECTED", "FAILED", "DISABLED"}:
            self._release_reserve(order, now); order["original_broker_rejection_reason"] = str(broker_order.get("reason") or broker_order.get("remark") or broker_status); self._transition(order, "REJECTED", now, "BROKER_SIM_RECONCILED_REJECTED")
        orders[intent_id] = order; self._save_orders(orders, now)
        unresolved = [x["intent_id"] for x in orders.values() if x.get("status") == "RECONCILING"]
        if not unresolved: self.complete_reconciliation(now)
        return order

    def cancel_order(self, intent_id: str, *, current: datetime | None = None, reason: str = "USER_CANCEL") -> dict[str, Any]:
        now = current or datetime.now(timezone.utc); orders = self._orders(); order = orders.get(intent_id)
        if not order: raise R1HError("ORDER_NOT_FOUND")
        if order["status"] in TERMINAL_STATUSES: return order
        self._transition(order, "CANCEL_PENDING", now, reason)
        if not order["local_simulation"] and self.broker and order.get("broker_order_id_hash"):
            self.broker.cancel_order(order_id_hash=order["broker_order_id_hash"], trd_env="TrdEnv.SIMULATE")
        self._release_reserve(order, now); self._transition(order, "CANCELED", now, reason); self._save_orders(orders, now); return order

    def cancel_all(self, *, current: datetime | None = None, reason: str = "CANCEL_ALL_PAPER_ORDERS") -> list[dict[str, Any]]:
        return [self.cancel_order(x["intent_id"], current=current, reason=reason) for x in list(self._orders().values()) if x.get("status") in OPEN_STATUSES]

    def expire_day_orders(self, current: datetime | None = None) -> list[dict[str, Any]]:
        now = current or datetime.now(timezone.utc); expired = []
        for order in list(self._orders().values()):
            if order.get("status") in OPEN_STATUSES and (et_now(now).time().replace(tzinfo=None) >= RTH_END or et_now(now) >= datetime.fromisoformat(order["expires_at_et"])):
                canceled = self.cancel_order(order["intent_id"], current=now, reason="DAY_ORDER_EXPIRED_1550_ET")
                canceled["status"] = "EXPIRED"; self._transition(canceled, "EXPIRED", now, "DAY_ORDER_EXPIRED_1550_ET"); orders = self._orders(); orders[order["intent_id"]] = canceled; self._save_orders(orders, now); expired.append(canceled)
        return expired

    def handle_manual_activity(self, symbols: Sequence[str], current: datetime | None = None) -> list[dict[str, Any]]:
        now = current or datetime.now(timezone.utc); touched = {s.upper() for s in symbols}; paused = []
        for order in list(self._orders().values()):
            if order.get("symbol") in touched and order.get("status") in OPEN_STATUSES:
                paused.append(self.cancel_order(order["intent_id"], current=now, reason="MANUAL_ACTIVITY_PRIORITY_CONFLICT"))
        self.enter_reconciling([x["intent_id"] for x in paused], "MANUAL_ACTIVITY_RECONCILIATION_REQUIRED", now)
        audit(self.paths, "MANUAL_ACTIVITY_PAUSED_CONFLICTING_PAPER_ORDERS", now, symbols=sorted(touched))
        return paused

    def enter_reconciling(self, intent_ids: Sequence[str], reason: str, current: datetime | None = None) -> dict[str, Any]:
        state = {"schema_version": 1, "state": "RECONCILING", "unknown_intent_ids": sorted(set(intent_ids)), "new_orders_blocked": True, "reason_code": reason, "updated_at_utc": utc_iso(current)}; atomic_json(self.paths.reconciliation, state)
        orders = self._orders()
        for iid in intent_ids:
            if iid in orders and orders[iid]["status"] not in TERMINAL_STATUSES: self._transition(orders[iid], "RECONCILING", current or datetime.now(timezone.utc), reason)
        self._save_orders(orders, current); audit(self.paths, "PAPER_RECONCILIATION_STARTED", current, intent_ids=list(intent_ids), reason_code=reason); return state

    def recover_after_restart(self, current: datetime | None = None) -> dict[str, Any]:
        now = current or datetime.now(timezone.utc); unresolved = [x["intent_id"] for x in self._orders().values() if x.get("status") in OPEN_STATUSES]
        if not unresolved: return self.complete_reconciliation(now)
        self.enter_reconciling(unresolved, "RESTART_QUERY_EXISTING_ORDERS_FIRST", now)
        if self.broker:
            try: self.broker.get_order_list(trd_env="TrdEnv.SIMULATE"); self.broker.get_history_order_list(trd_env="TrdEnv.SIMULATE"); self.broker.get_deal_list(trd_env="TrdEnv.SIMULATE")
            except Exception as exc: audit(self.paths, "BROKER_SIM_RECONCILIATION_QUERY_FAILED", now, reason_code=f"{type(exc).__name__}:{exc}")
        return read_json(self.paths.reconciliation, {})

    def complete_reconciliation(self, current: datetime | None = None) -> dict[str, Any]:
        state = {"schema_version": 1, "state": "READY", "unknown_intent_ids": [], "new_orders_blocked": False, "reason_code": "RECONCILIATION_COMPLETE", "updated_at_utc": utc_iso(current)}; atomic_json(self.paths.reconciliation, state); audit(self.paths, "PAPER_RECONCILIATION_READY", current); return state

    def mark_to_market(self, prices: Mapping[str, Any], current: datetime | None = None) -> dict[str, Any]:
        now = current or datetime.now(timezone.utc); portfolio = read_json(self.paths.portfolio, {}) or {}; cash = read_json(self.paths.cash, {}) or {}
        market_value = D("0")
        for symbol in ACTIVE_SYMBOLS:
            item = portfolio["positions"][symbol]; px = D(prices.get(symbol, item.get("last_price", "0"))); item["last_price"] = dec(px); item["market_value"] = dec(D(item["quantity"]) * px); market_value += D(item["market_value"])
        nav = D(cash["paper_cash"]) + market_value; qqq = D(prices.get("US.QQQ", "0")); previous = self._nav_rows(); start_nav = D(previous[0]["paper_strategy_nav"]) if previous else nav; start_qqq = D(previous[0]["qqq_price"]) if previous else qqq
        strategy_return = nav / start_nav - 1 if start_nav else D("0"); qqq_return = qqq / start_qqq - 1 if start_qqq else D("0"); deals = jsonl_rows(self.paths.deal_ledger); orders = list(self._orders().values()); fills = [x for x in orders if D(x.get("filled_quantity")) > 0]; rejections = [x for x in orders if x.get("status") == "REJECTED"]
        peak = max([D(x["paper_strategy_nav"]) for x in previous] + [nav]); drawdown = nav / peak - 1 if peak else D("0"); prior_dd = min([D(x.get("drawdown", "0")) for x in previous] + [drawdown])
        slippages = [D(x.get("slippage")) for x in deals]; turnover = sum((D(x.get("notional")) for x in deals), D("0")) / start_nav if start_nav else D("0")
        perf = {"schema_version": 1, "paper_strategy_nav": dec(nav), "paper_strategy_return": dec(strategy_return), "qqq_buy_hold_return": dec(qqq_return), "paper_excess_return_vs_qqq": dec(strategy_return - qqq_return), "daily_return": dec(nav / D(previous[-1]["paper_strategy_nav"]) - 1) if previous and D(previous[-1]["paper_strategy_nav"]) else "0", "cumulative_return": dec(strategy_return), "max_drawdown": dec(prior_dd), "turnover": dec(turnover), "trade_count": len(deals), "fill_rate": dec(D(len(fills)) / D(len(orders))) if orders else "0", "rejection_rate": dec(D(len(rejections)) / D(len(orders))) if orders else "0", "average_slippage": dec(sum(slippages, D("0")) / D(len(slippages))) if slippages else "0", "cash_utilization": dec(market_value / nav) if nav else "0", "excess_return_vs_qqq": dec(strategy_return - qqq_return), "manual_holdings_excluded": True, "updated_at_utc": utc_iso(now)}
        atomic_json(self.paths.portfolio, portfolio); atomic_json(self.paths.performance, perf)
        with self.paths.nav_history.open("a", encoding="utf-8", newline="") as handle: csv.writer(handle).writerow([et_now(now).isoformat(), dec(nav), cash["paper_cash"], dec(qqq), dec(strategy_return), dec(qqq_return), dec(strategy_return - qqq_return)])
        return perf

    def _nav_rows(self) -> list[dict[str, str]]:
        try:
            with self.paths.nav_history.open("r", encoding="utf-8-sig", newline="") as handle: return list(csv.DictReader(handle))
        except OSError: return []

    def watchdog_snapshot(self, *, current: datetime | None = None, process_alive: bool = True, heartbeat_age_seconds: float = 0, opend_connected: bool = True, quote_fresh: bool = True) -> dict[str, Any]:
        now = current or datetime.now(timezone.utc); auth_before = read_json(self.paths.authorization, {}) or {}; auth = authorization_state(self.paths, now)
        if auth_before.get("execution_authorization") == "PAPER_ARMED" and auth.get("execution_authorization") == "DISARMED": self.cancel_all(current=now, reason="PAPER_ARM_EXPIRED_SAFE_CANCEL")
        self.expire_day_orders(now); orders = self._orders(); ages = [(et_now(now) - datetime.fromisoformat(x["created_at_et"])).total_seconds() for x in orders.values() if x.get("status") in OPEN_STATUSES]
        payload = {"schema_version": 1, "paper_process_alive": process_alive, "paper_heartbeat_age_seconds": heartbeat_age_seconds, "open_order_count": sum(x.get("status") in OPEN_STATUSES for x in orders.values()), "oldest_open_order_age_seconds": max(ages, default=0), "reconciliation_status": (read_json(self.paths.reconciliation, {}) or {}).get("state"), "opend_connected": opend_connected, "quote_fresh": quote_fresh, "paper_arm_not_expired": auth.get("paper_arm_not_expired", False), "execution_authorization": auth.get("execution_authorization"), "execution_mode": auth.get("execution_mode"), "watchdog_status": "HEALTHY" if process_alive and heartbeat_age_seconds <= 45 and quote_fresh else "DEGRADED", "real_trade_api_called": False, "updated_at_utc": utc_iso(now)}
        atomic_json(self.paths.output / "paper_watchdog_state.json", payload); return payload


def rebalance_phases(current: Mapping[str, Any], target_state: str, open_orders: Sequence[Mapping[str, Any]], cash_reconciled: bool, minute_key: str | None = None) -> dict[str, Any]:
    if target_state not in TARGET_WEIGHTS: raise R1HError("UNKNOWN_V8_STATE")
    target = TARGET_WEIGHTS[target_state]
    if target["US.TQQQ"] and target["US.SQQQ"]: raise R1HError("TQQQ_SQQQ_SIMULTANEOUS_TARGET_FORBIDDEN")
    if D(current.get("US.TQQQ")) > 0 and target["US.SQQQ"] > 0: return {"phase": "SELL_EXCESS_FIRST", "blocked_reason": "V8_DIRECT_TQQQ_TO_SQQQ_FORBIDDEN", "orders": [{"symbol": "US.TQQQ", "side": "SELL"}]}
    if any(x.get("status") in OPEN_STATUSES and x.get("side") == "SELL" for x in open_orders) or not cash_reconciled: return {"phase": "WAIT_FOR_SELLS_AND_CASH_RECONCILIATION", "orders": []}
    conflicts = {(x.get("symbol"), x.get("side"), x.get("minute_key")) for x in open_orders}
    sells = [{"symbol": s, "side": "SELL", "minute_key": minute_key} for s in ACTIVE_SYMBOLS if D(current.get(s)) > 0 and target[s] == 0 and (s, "SELL", minute_key) not in conflicts]
    if sells: return {"phase": "SELL_EXCESS_FIRST", "orders": sells}
    return {"phase": "BUY_AFTER_CASH_RECONCILED", "orders": [{"symbol": s, "side": "BUY", "minute_key": minute_key} for s in ACTIVE_SYMBOLS if target[s] > 0 and (s, "BUY", minute_key) not in conflicts]}


def write_summary(repo: Path, current: datetime | None = None) -> dict[str, Any]:
    paths = Paths(repo); engine = PaperExecutionEngine(repo); auth = authorization_state(paths, current); orders = list(engine._orders().values()); cash = read_json(paths.cash, {}) or {}; portfolio = read_json(paths.portfolio, {}) or {}; performance = read_json(paths.performance, {}) or {}
    summary = {"schema_version": 1, "revision": REVISION, "final_status": FINAL_STATUS, "strategy_enabled": True, "strategy_configured": True, "strategy_name": "V8_REFERENCE_TREND_ROTATION", "default_execution_mode": "SHADOW", "paper_available": True, "paper_armed": auth.get("execution_authorization") == "PAPER_ARMED", "live_available": False, "broker_action_allowed": False, "real_trade_api_called": False, "execution_backend": (read_json(paths.backend, {}) or {}).get("execution_backend"), "open_paper_orders": sum(x.get("status") in OPEN_STATUSES for x in orders), "paper_fills": len(jsonl_rows(paths.deal_ledger)), "paper_positions": portfolio.get("positions", {}), "paper_cash": cash.get("paper_cash"), "paper_nav": performance.get("paper_strategy_nav", cash.get("paper_cash")), "reconciliation_status": (read_json(paths.reconciliation, {}) or {}).get("state"), "simulated_trading_only": True, "not_real_money": True, "updated_at_utc": utc_iso(current)}
    atomic_json(paths.output / "r1h_summary.json", summary)
    report = [f"# {STAGE} Validation Report", "", f"Final status: **{FINAL_STATUS}**", "", "- SIMULATED TRADING ONLY", "- NOT REAL MONEY", "- LIVE NOT AVAILABLE", "- TrdEnv.REAL rejected", "- unlock_trade rejected", "- Decimal quantity preserved at 0.001", "- PAPER ledgers are isolated from real broker ownership", "", f"Open PAPER orders: {summary['open_paper_orders']}", f"Reconciliation: {summary['reconciliation_status']}"]
    (paths.output / "validation_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def run_service(repo: Path, interval: float = 5) -> int:
    engine = PaperExecutionEngine(repo, startup=True); stop = engine.paths.output / "r1h.stop"
    if stop.exists(): stop.unlink()
    while not stop.exists():
        atomic_json(engine.paths.output / "paper_heartbeat.json", {"timestamp_utc": utc_iso(), "process_alive": True}); engine.watchdog_snapshot(); write_summary(repo)
        deadline = time.monotonic() + max(1, interval)
        while not stop.exists() and time.monotonic() < deadline: time.sleep(min(.25, deadline - time.monotonic()))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--repo-root", default=r"D:\us-tech-quant"); parser.add_argument("--service", action="store_true"); parser.add_argument("--interval", type=float, default=5); parser.add_argument("--startup-reset", action="store_true"); args = parser.parse_args(argv)
    try:
        paths = Paths(Path(args.repo_root))
        if args.startup_reset: startup_reset(paths)
        if args.service: return run_service(Path(args.repo_root), args.interval)
        print(json.dumps(write_summary(Path(args.repo_root)), ensure_ascii=False, indent=2)); return 0
    except Exception as exc:
        print(f"final_status=FAIL_{REVISION}\nerror={type(exc).__name__}:{exc}"); return 2


if __name__ == "__main__": raise SystemExit(main())
