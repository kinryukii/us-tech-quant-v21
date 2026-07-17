#!/usr/bin/env python
"""V22.047 R1D loopback-only Moomoo read bridge and shadow engine.

The module deliberately contains no strategy rules and no broker mutation API.
It adapts read-only Moomoo data to the existing R1B strategy plug-in and control
component, then writes shadow-only state for the independent local dashboard.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from datetime import datetime, time as dt_time, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

REVISION = "V22.047_R1D"
STAGE = "V22.047_R1D_LIVE_MARKET_ACCOUNT_BRIDGE_AND_LOCAL_DASHBOARD_SHADOW_ONLY"
OUTPUT_FOLDER = STAGE
HOST = "127.0.0.1"
UI_PORT = 8765
BENCHMARK_SYMBOL = "US.QQQ"
EXECUTION_SYMBOLS = ("US.IQQ", "US.TQQQ", "US.SQQQ")
R1F_ADDITIONAL_QUOTE_SYMBOLS = ("US.IQQQ",)
QUOTE_SYMBOLS = (BENCHMARK_SYMBOL,) + EXECUTION_SYMBOLS + R1F_ADDITIONAL_QUOTE_SYMBOLS
SWITCH_MODES = ("OFF", "SHADOW", "PAPER", "LIVE", "FLATTEN_ONLY")
KLINE_TYPES = ("K_1M", "K_5M", "K_15M", "K_30M", "K_60M", "K_DAY")
INCOMPLETE_ORDER_STATUSES = {
    "UNSUBMITTED", "WAITING_SUBMIT", "SUBMITTING", "SUBMITTED",
    "FILLED_PART", "PENDING", "SUSPENDED", "TIMEOUT",
    "CANCELLING_PART", "CANCELLING_ALL",
}


class R1DError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso() -> str:
    return utc_now().isoformat()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            handle.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return default


def append_csv(path: Path, fields: Sequence[str], row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in fields})


def ensure_csv(path: Path, fields: Sequence[str]) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.DictWriter(handle, fieldnames=list(fields)).writeheader()


def safe_number(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def scalar(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def rows(data: Any) -> list[dict[str, Any]]:
    if hasattr(data, "to_dict"):
        try:
            return [{str(k): scalar(v) for k, v in row.items()} for row in data.to_dict("records")]
        except Exception:
            pass
    if isinstance(data, list):
        return [{str(k): scalar(v) for k, v in item.items()} for item in data if isinstance(item, Mapping)]
    return []


def api_rows(result: Any, operation: str) -> list[dict[str, Any]]:
    if not isinstance(result, tuple) or len(result) < 2:
        raise R1DError(f"{operation}_UNEXPECTED_RESULT")
    ret, data = result[0], result[1]
    if ret != 0 and str(ret).upper() not in {"RET_OK", "OK", "0"}:
        raise R1DError(f"{operation}_FAILED:{data}")
    return rows(data)


def masked_id(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
    return f"MASKED_{digest}"


def safe_trade_rows(items: Sequence[Mapping[str, Any]], *, deal: bool = False, include_audit_references: bool = False) -> list[dict[str, Any]]:
    """Remove account/order/deal identifiers before data reaches disk or UI."""
    allowed = (
        ("code", "stock_name", "qty", "price", "trd_side", "create_time", "status")
        if deal else
        ("code", "stock_name", "trd_side", "order_type", "order_status", "qty", "price",
         "create_time", "updated_time", "dealt_qty", "dealt_avg_price", "last_err_msg")
    )
    result = []
    for item in items:
        row = {key: item.get(key) for key in allowed}
        if include_audit_references:
            row["remark"] = item.get("remark")
            row["order_reference"] = masked_id(item.get("order_id"))
            if deal:
                row["deal_reference"] = masked_id(item.get("deal_id"))
        result.append(row)
    return result


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise R1DError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_connection_profile(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise R1DError(f"CONNECTION_PROFILE_INVALID:{path}")
    host = str(payload.get("host", ""))
    port = int(payload.get("port", 0))
    if host != HOST:
        raise R1DError("OPEND_HOST_MUST_BE_127_0_0_1")
    if port != 18441:
        raise R1DError("OPEND_PORT_MUST_BE_18441")
    if payload.get("trade_password") or payload.get("password") or payload.get("account_id"):
        raise R1DError("SENSITIVE_CONNECTION_FIELDS_FORBIDDEN")
    return payload


def parse_quote_time(value: Any, now: datetime) -> tuple[str | None, float | None]:
    if value in (None, "", "N/A"):
        return None, None
    text = str(value).strip().replace("Z", "+00:00")
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return str(value), None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("America/New_York"))
    age = max(0.0, (now - parsed.astimezone(timezone.utc)).total_seconds())
    return parsed.astimezone(timezone.utc).isoformat(), age


def us_session(now: datetime | None = None) -> tuple[str, str]:
    current = (now or utc_now()).astimezone(ZoneInfo("America/New_York"))
    if current.weekday() >= 5:
        return "CLOSED", "WEEKEND"
    t = current.time()
    if dt_time(4, 0) <= t < dt_time(9, 30):
        return "PRE_MARKET", "PRE_MARKET"
    if dt_time(9, 30) <= t < dt_time(16, 0):
        return "REGULAR", "REGULAR"
    if dt_time(16, 0) <= t < dt_time(20, 0):
        return "AFTER_HOURS", "AFTER_HOURS"
    return "CLOSED", "CLOSED"


class MoomooReadOnlyBridge:
    """The only SDK adapter. Exposes query methods and no mutation methods."""

    def __init__(self, profile: Mapping[str, Any], output_dir: Path, max_quote_age: float = 15.0):
        self.host = str(profile["host"])
        self.port = int(profile["port"])
        self.output_dir = output_dir
        self.max_quote_age = max_quote_age
        self.moomoo: Any = None

    def _sdk(self) -> Any:
        if self.moomoo is None:
            appdata = self.output_dir / "runtime" / "moomoo_appdata"
            appdata.mkdir(parents=True, exist_ok=True)
            os.environ["appdata"] = str(appdata)
            import moomoo  # type: ignore
            self.moomoo = moomoo
        return self.moomoo

    def tcp_ready(self) -> bool:
        try:
            with socket.create_connection((self.host, self.port), timeout=2.0):
                return True
        except OSError:
            return False

    def market_snapshot(self) -> dict[str, Any]:
        sdk = self._sdk()
        context = None
        now = utc_now()
        default_status, session = us_session(now)
        try:
            context = sdk.OpenQuoteContext(host=self.host, port=self.port)
            snapshot_rows = api_rows(context.get_market_snapshot(list(QUOTE_SYMBOLS)), "MARKET_SNAPSHOT")
            by_symbol = {str(r.get("code", "")).upper(): r for r in snapshot_rows}
            quotes: dict[str, Any] = {}
            for symbol in QUOTE_SYMBOLS:
                raw = by_symbol.get(symbol, {})
                latest = safe_number(raw.get("last_price"))
                bid = safe_number(raw.get("bid_price"))
                ask = safe_number(raw.get("ask_price"))
                mid = (bid + ask) / 2.0 if bid and ask and bid > 0 and ask >= bid else None
                spread = ask - bid if mid is not None else None
                ratio = spread / mid if spread is not None and mid else None
                quote_ts, age = parse_quote_time(raw.get("update_time") or raw.get("data_date"), now)
                market_status = str(raw.get("market_state") or default_status)
                fresh = bool(latest and latest > 0 and bid and ask and bid > 0 and ask >= bid and age is not None and age <= self.max_quote_age)
                quotes[symbol] = {
                    "symbol": symbol,
                    "latest_price": latest,
                    "bid": bid,
                    "ask": ask,
                    "mid": mid,
                    "spread_absolute": spread,
                    "spread_ratio": ratio,
                    "quote_timestamp": quote_ts,
                    "quote_age_seconds": age,
                    "market_status": market_status,
                    "session_type": session,
                    "data_fresh": fresh,
                }
            klines: dict[str, Any] = {}
            for ktype in KLINE_TYPES:
                try:
                    result = context.request_history_kline(
                        code=BENCHMARK_SYMBOL,
                        ktype=getattr(sdk.KLType, ktype),
                        autype=sdk.AuType.QFQ,
                        max_count=320 if ktype == "K_DAY" else 120,
                    )
                    klines[ktype] = {"ready": True, "bars": api_rows(result, f"QQQ_{ktype}")}
                except Exception as exc:
                    klines[ktype] = {"ready": False, "bars": [], "error": f"{type(exc).__name__}:{exc}"}
            qqq = quotes[BENCHMARK_SYMBOL]
            execution = {
                symbol: {
                    "bid": quotes[symbol]["bid"],
                    "ask": quotes[symbol]["ask"],
                    "age_seconds": quotes[symbol]["quote_age_seconds"],
                }
                for symbol in EXECUTION_SYMBOLS
            }
            return {
                "schema_version": 1,
                "snapshot_at_utc": now.isoformat(),
                "snapshot_ready": all(bool(quotes[s]["latest_price"]) for s in QUOTE_SYMBOLS),
                "all_quotes_fresh": all(bool(quotes[s]["data_fresh"]) for s in QUOTE_SYMBOLS),
                "market_status": default_status,
                "session_type": session,
                "quotes": quotes,
                "qqq_klines": klines,
                "benchmark": {"symbol": BENCHMARK_SYMBOL, "last": qqq["latest_price"]},
                "execution_quotes": execution,
                "source": "MOOMOO_OPEND_READ_ONLY",
            }
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass

    def account_snapshot(self) -> dict[str, Any]:
        sdk = self._sdk()
        context = None
        try:
            context = sdk.OpenSecTradeContext(
                filter_trdmarket=sdk.TrdMarket.US,
                host=self.host,
                port=self.port,
            )
            accounts = api_rows(context.get_acc_list(), "ACCOUNT_LIST")
            if not accounts:
                raise R1DError("NO_US_ACCOUNT_AVAILABLE")
            real = [row for row in accounts if str(row.get("trd_env", "")).upper() == "REAL"]
            selected = (real or accounts)[0]
            env_name = str(selected.get("trd_env", "REAL")).upper()
            trd_env = sdk.TrdEnv.REAL if env_name == "REAL" else sdk.TrdEnv.SIMULATE
            acc_id = int(selected.get("acc_id") or 0)
            common = {"trd_env": trd_env, "acc_id": acc_id, "refresh_cache": True}
            info_rows = api_rows(context.accinfo_query(currency=sdk.Currency.USD, **common), "ACCOUNT_INFO")
            position_rows = api_rows(context.position_list_query(currency=sdk.Currency.USD, **common), "POSITIONS")
            order_rows = api_rows(context.order_list_query(**common), "ORDERS")
            deal_rows = api_rows(context.deal_list_query(**common), "DEALS")
            info = info_rows[0] if info_rows else {}
            positions_map = {symbol: 0.0 for symbol in EXECUTION_SYMBOLS}
            positions_detail: list[dict[str, Any]] = []
            for row in position_rows:
                symbol = str(row.get("code", "")).upper()
                qty = safe_number(row.get("qty"), 0.0) or 0.0
                if symbol in positions_map:
                    positions_map[symbol] = qty
                positions_detail.append({
                    key: row.get(key) for key in (
                        "code", "stock_name", "qty", "can_sell_qty", "cost_price", "market_val",
                        "nominal_price", "pl_val", "pl_ratio", "today_pl_val", "unrealized_pl", "realized_pl", "currency"
                    )
                })
            open_orders = [r for r in order_rows if str(r.get("order_status", "")).upper() in INCOMPLETE_ORDER_STATUSES]
            today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
            today_deals = [r for r in deal_rows if str(r.get("create_time", "")).startswith(today)]
            today_orders = [r for r in order_rows if str(r.get("create_time", "")).startswith(today)]
            remark_by_order = {str(r.get("order_id", "")): str(r.get("remark", "") or "") for r in order_rows}
            for deal in today_deals:
                deal["remark"] = remark_by_order.get(str(deal.get("order_id", "")), "")
            realized = safe_number(info.get("realized_pl"), 0.0) or 0.0
            unrealized = safe_number(info.get("unrealized_pl"), 0.0) or 0.0
            return {
                "schema_version": 1,
                "snapshot_at_utc": utc_iso(),
                "account_snapshot_ready": True,
                "account_type": env_name,
                "account_reference": masked_id(acc_id),
                "net_liquidation_value_usd": safe_number(info.get("total_assets"), 0.0),
                "available_cash_usd": safe_number(info.get("cash") or info.get("available_funds"), 0.0),
                "buying_power_usd": safe_number(info.get("power") or info.get("net_cash_power"), 0.0),
                "positions": positions_map,
                "positions_detail": positions_detail,
                "open_order_count": len(open_orders),
                "open_orders": safe_trade_rows(open_orders, include_audit_references=True),
                "today_orders": safe_trade_rows(today_orders, include_audit_references=True),
                "today_deals": safe_trade_rows(today_deals, deal=True, include_audit_references=True),
                "realized_pnl_today_usd": realized,
                "unrealized_pnl_today_usd": unrealized,
                "realized_pnl_week_usd": realized,
                "today_pnl_usd": realized + unrealized,
                "source": "MOOMOO_OPEND_ACCOUNT_QUERY_READ_ONLY",
            }
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass


def failed_market(error: str) -> dict[str, Any]:
    status, session = us_session()
    return {
        "schema_version": 1, "snapshot_at_utc": utc_iso(), "snapshot_ready": False,
        "all_quotes_fresh": False, "market_status": status, "session_type": session,
        "quotes": {s: {"symbol": s, "latest_price": None, "bid": None, "ask": None,
                       "mid": None, "spread_absolute": None, "spread_ratio": None,
                       "quote_timestamp": None, "quote_age_seconds": None,
                       "market_status": status, "session_type": session, "data_fresh": False} for s in QUOTE_SYMBOLS},
        "qqq_klines": {k: {"ready": False, "bars": []} for k in KLINE_TYPES},
        "benchmark": {"symbol": BENCHMARK_SYMBOL, "last": None}, "execution_quotes": {},
        "source": "MOOMOO_OPEND_READ_ONLY", "error": error,
    }


def failed_account(error: str) -> dict[str, Any]:
    return {
        "schema_version": 1, "snapshot_at_utc": utc_iso(), "account_snapshot_ready": False,
        "account_type": "UNAVAILABLE", "account_reference": "", "net_liquidation_value_usd": None,
        "available_cash_usd": None, "buying_power_usd": None,
        "positions": {s: 0.0 for s in EXECUTION_SYMBOLS}, "positions_detail": [],
        "open_order_count": 0, "open_orders": [], "today_orders": [], "today_deals": [],
        "realized_pnl_today_usd": None, "unrealized_pnl_today_usd": None,
        "realized_pnl_week_usd": None, "today_pnl_usd": None,
        "source": "MOOMOO_OPEND_ACCOUNT_QUERY_READ_ONLY", "error": error,
    }


class SingleInstance:
    def __init__(self, path: Path):
        self.path = path
        self.acquired = False

    @staticmethod
    def alive(pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            try:
                import ctypes
                handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
                if not handle:
                    return False
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            except Exception:
                return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="ascii") as handle:
                    handle.write(str(os.getpid()))
                self.acquired = True
                return
            except FileExistsError:
                try:
                    pid = int(self.path.read_text(encoding="ascii").strip())
                except Exception:
                    pid = -1
                if self.alive(pid):
                    raise R1DError(f"ENGINE_ALREADY_RUNNING:{pid}")
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
        raise R1DError("SINGLE_INSTANCE_LOCK_FAILED")

    def release(self) -> None:
        if self.acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self.acquired = False


class Engine:
    def __init__(self, repo_root: Path, interval: float = 10.0, bridge: Any = None):
        self.repo_root = repo_root.resolve()
        self.output_dir = self.repo_root / "outputs" / "v22" / OUTPUT_FOLDER
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.interval = max(1.0, interval)
        self.profile_path = self.repo_root / "config" / "moomoo_opend_connection.json"
        self.control_config_path = self.repo_root / "config" / "v22_047_r1b_auto_trading_control.json"
        self.plugin_path = self.repo_root / "scripts" / "v22" / "v22_047_r1b_strategy_plugin_template.py"
        self.control_path = self.repo_root / "scripts" / "v22" / "v22_047_r1b_auto_trading_control_component.py"
        self.switch_path = self.output_dir / "switch_state.json"
        self.emergency_path = self.output_dir / "emergency_stop.json"
        self.stop_path = self.output_dir / "engine.stop"
        self.lock = SingleInstance(self.output_dir / "runtime" / "engine.lock")
        self.profile = load_connection_profile(self.profile_path)
        self.control = load_module(self.control_path, "v22_047_r1b_control_for_r1d")
        cfg = self.control.load_config(self.control_config_path)
        self.max_quote_age = float(cfg["risk"]["max_quote_age_seconds"])
        self.bridge = bridge or MoomooReadOnlyBridge(self.profile, self.output_dir, self.max_quote_age)
        self.previous_state = read_json(self.output_dir / "engine_state.json", {}) or {}
        self.running = True
        ensure_csv(self.output_dir / "error_ledger.csv",
                   ("timestamp_utc", "severity", "stage", "error", "fail_closed"))
        ensure_csv(self.output_dir / "audit_ledger.csv",
                   ("timestamp_utc", "event", "opend_status", "switch_mode", "effective_execution_mode",
                    "strategy_action", "strategy_reason_code", "order_intent_created", "broker_action_allowed", "trade_api_called"))

    def _log(self, level: str, event: str, detail: str = "") -> None:
        path = self.output_dir / "logs" / "engine.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"{utc_iso()} level={level} event={event} detail={detail}\n")

    def _write_error(self, stage: str, error: str, severity: str = "ERROR") -> None:
        self._log(severity, stage, error)
        atomic_json(self.output_dir / "exception_state.json",
                    {"active": True, "timestamp_utc": utc_iso(), "severity": severity,
                     "stage": stage, "error": error, "fail_closed": True})
        append_csv(self.output_dir / "error_ledger.csv",
                   ("timestamp_utc", "severity", "stage", "error", "fail_closed"),
                   {"timestamp_utc": utc_iso(), "severity": severity, "stage": stage,
                    "error": error, "fail_closed": True})

    def _switch(self) -> dict[str, Any]:
        state = read_json(self.switch_path)
        if not isinstance(state, dict):
            state = {"schema_version": 1, "mode": "OFF", "updated_at_utc": utc_iso(),
                     "updated_by": "R1D_INITIALIZER", "note": "Fail-closed default"}
            atomic_json(self.switch_path, state)
        mode = str(state.get("mode", "OFF")).upper()
        if mode not in SWITCH_MODES:
            mode = "OFF"
        state["mode"] = mode
        return state

    def _strategy_and_control(self, market: Mapping[str, Any], account: Mapping[str, Any], switch: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        cfg = self.control.load_config(self.control_config_path)
        runtime_path = self.output_dir / "r1b_runtime_state.json"
        runtime = self.control.load_runtime_state(runtime_path)
        nav = safe_number(account.get("net_liquidation_value_usd"), 0.0) or 0.0
        qqq = safe_number(market.get("benchmark", {}).get("last"), 0.0) or 0.0
        benchmark = None
        if nav > 0 and qqq > 0:
            benchmark = self.control.compute_benchmark_metrics(runtime, nav, qqq, cfg)
        else:
            benchmark = self.control.BenchmarkMetrics(
                status="DATA_NOT_READY", observation_count=len(runtime.samples), strategy_return=None,
                qqq_return=None, excess_return=None,
                underperformance_threshold=float(cfg["benchmark"]["underperformance_threshold_pct"]),
                block_new_entries=True, reason_code="MARKET_OR_ACCOUNT_NOT_READY")
        context = {
            "revision": REVISION,
            "component_name": "R1D_BRIDGE_TO_EXISTING_R1B_CONTROL",
            "timestamp_utc": utc_iso(), "benchmark_symbol": BENCHMARK_SYMBOL,
            "benchmark_metrics": asdict(benchmark), "allowed_execution_symbols": list(EXECUTION_SYMBOLS),
            "symbol_roles": self.control.SYMBOL_ROLES, "market": market, "account": account,
            "strategy_parameters": cfg["strategy_plugin"].get("parameters", {}),
            "switch_mode": switch["mode"],
        }
        strategy_error = ""
        try:
            callable_ = self.control.load_strategy_callable(self.plugin_path, str(cfg["strategy_plugin"]["entrypoint"]))
            decision = self.control.parse_strategy_decision(callable_(context))
        except Exception as exc:
            decision = self.control.StrategyDecision(action="HOLD", symbol=None, target_notional_usd=0.0,
                                                      confidence=0.0, reason_code="STRATEGY_PLUGIN_ERROR")
            strategy_error = f"{type(exc).__name__}:{exc}"
            self._write_error("STRATEGY_PLUGIN", strategy_error)
        strategy_configured = decision.reason_code != "STRATEGY_NOT_CONFIGURED"
        emergency = bool((read_json(self.emergency_path, {}) or {}).get("active", False))
        ready = (
            bool(account.get("account_snapshot_ready"))
            and bool(market.get("snapshot_ready"))
            and bool(market.get("all_quotes_fresh"))
            and nav > 0
            and qqq > 0
        )
        if ready:
            try:
                self.control.validate_snapshots(market, account, cfg)
            except Exception as exc:
                ready = False
                self._write_error("R1B_SNAPSHOT_VALIDATION", f"{type(exc).__name__}:{exc}")
        effective_switch = "SHADOW" if ready and not emergency else "OFF"
        try:
            authorization = self.control.build_authorization(
                effective_switch, decision, account, benchmark, cfg,
                execute_requested=False, live_confirmation="")
            raw_intent = self.control.build_order_intent(decision, authorization, market, account, benchmark, cfg) if ready else None
            control_called = True
            control_error = ""
        except Exception as exc:
            raw_intent = None
            control_called = True
            control_error = f"{type(exc).__name__}:{exc}"
            self._write_error("R1B_CONTROL_COMPONENT", control_error)
            authorization = self.control.Authorization(
                switch_mode="OFF", requested_action="HOLD", broker_action_allowed=False,
                order_intent_allowed=False, new_entry_allowed=False, exit_allowed=False,
                effective_mode="OFF", reason_code="R1D_FAIL_CLOSED", checks={"r1d_data_ready": False})
        strategy_payload = {
            "schema_version": 1, "timestamp_utc": utc_iso(), "plugin_path": str(self.plugin_path),
            "plugin_called": True, "strategy_configured": strategy_configured,
            "strategy_action": decision.action, "strategy_symbol": decision.symbol,
            "target_notional_usd": decision.target_notional_usd, "confidence": decision.confidence,
            "strategy_reason_code": decision.reason_code, "metadata": decision.metadata,
            "strategy_error": strategy_error,
            "display_message": "当前策略尚未填写" if not strategy_configured else "策略插件已配置",
        }
        control_payload = {
            "schema_version": 1, "timestamp_utc": utc_iso(), "r1b_control_component_path": str(self.control_path),
            "r1b_control_component_called": control_called, "control_error": control_error,
            "switch_mode": switch["mode"], "effective_execution_mode": "SHADOW_ONLY",
            "authorization": asdict(authorization), "benchmark_metrics": asdict(benchmark),
            "broker_action_allowed": False, "trade_api_called": False,
            "account_snapshot_ready": bool(account.get("account_snapshot_ready")),
        }
        intent_payload = {
            "schema_version": 1, "timestamp_utc": utc_iso(),
            "order_intent_created": raw_intent is not None, "intent": asdict(raw_intent) if raw_intent else None,
            "duplicate_suppressed": False, "broker_action_allowed": False, "trade_api_called": False,
            "effective_execution_mode": "SHADOW_ONLY",
        }
        if raw_intent is not None:
            fingerprint = hashlib.sha256(json.dumps({
                "action": raw_intent.action, "symbol": raw_intent.symbol, "quantity": raw_intent.quantity,
                "limit_price": raw_intent.limit_price, "strategy_reason_code": raw_intent.strategy_reason_code,
            }, sort_keys=True).encode("utf-8")).hexdigest()
            prior = read_json(self.output_dir / "runtime" / "intent_dedup.json", {}) or {}
            if prior.get("fingerprint") == fingerprint:
                intent_payload.update({"order_intent_created": False, "intent": None, "duplicate_suppressed": True})
            else:
                atomic_json(self.output_dir / "runtime" / "intent_dedup.json",
                            {"fingerprint": fingerprint, "intent_id": raw_intent.intent_id, "recorded_at_utc": utc_iso()})
        if nav > 0 and qqq > 0:
            runtime.samples.append({"timestamp_utc": utc_iso(), "nav": nav, "qqq": qqq})
            runtime.samples = runtime.samples[-max(2, int(cfg["benchmark"]["lookback_observations"])):]
            runtime.cycle_count += 1
            runtime.last_cycle_at_utc = utc_iso()
            runtime.last_decision_action = decision.action
            runtime.last_decision_symbol = decision.symbol or ""
            runtime.last_intent_id = raw_intent.intent_id if raw_intent else ""
            runtime.benchmark_pause_active = benchmark.block_new_entries
            atomic_json(runtime_path, asdict(runtime))
        return strategy_payload, control_payload, intent_payload

    def cycle(self) -> dict[str, Any]:
        started = utc_iso()
        self._log("INFO", "CYCLE_START", f"pid={os.getpid()}")
        atomic_json(self.output_dir / "exception_state.json",
                    {"active": False, "timestamp_utc": started, "severity": "NONE",
                     "stage": "CYCLE_START", "error": "", "fail_closed": True})
        switch = self._switch()
        opend_ready = self.bridge.tcp_ready()
        try:
            market = self.bridge.market_snapshot() if opend_ready else failed_market("OPEND_TCP_UNAVAILABLE")
        except Exception as exc:
            error = f"{type(exc).__name__}:{exc}"
            self._write_error("MARKET_BRIDGE", error)
            market = failed_market(error)
        try:
            account = self.bridge.account_snapshot() if opend_ready else failed_account("OPEND_TCP_UNAVAILABLE")
        except Exception as exc:
            error = f"{type(exc).__name__}:{exc}"
            self._write_error("ACCOUNT_BRIDGE", error)
            account = failed_account(error)
        strategy, control, intent = self._strategy_and_control(market, account, switch)
        recovered = bool(self.previous_state) and self.previous_state.get("engine_status") not in {"STOPPED", "CLEAN_STOP"}
        reconciled = bool(account.get("account_snapshot_ready"))
        state = {
            "schema_version": 1, "revision": REVISION, "stage": STAGE,
            "engine_status": "RUNNING", "cycle_started_at_utc": started, "last_heartbeat_utc": utc_iso(),
            "pid": os.getpid(), "opend_status": "CONNECTED" if opend_ready else "DISCONNECTED",
            "opend_endpoint": f"{self.profile['host']}:{self.profile['port']}",
            "switch_mode": switch["mode"], "effective_execution_mode": "SHADOW_ONLY",
            "market_session": market.get("session_type"), "account_snapshot_ready": account.get("account_snapshot_ready"),
            "crash_recovery_detected": recovered, "account_reconciled_after_recovery": reconciled,
            "broker_action_allowed": False, "trade_api_called": False,
        }
        benchmark = control["benchmark_metrics"]
        summary = {
            **state, "final_status": "PASS_R1D_SHADOW_CYCLE" if strategy["strategy_reason_code"] == "STRATEGY_NOT_CONFIGURED" else "WARN_R1D_REVIEW",
            "strategy_configured": strategy["strategy_configured"], "strategy_action": strategy["strategy_action"],
            "strategy_reason_code": strategy["strategy_reason_code"], "order_intent_created": intent["order_intent_created"],
            "benchmark_status": benchmark["status"], "strategy_return": benchmark["strategy_return"],
            "qqq_return": benchmark["qqq_return"], "excess_return": benchmark["excess_return"],
            "ui_url": f"http://{HOST}:{UI_PORT}", "ui_bind_host": HOST,
            "background_independent_of_ui": True,
        }
        for name, payload in (
            ("market_snapshot.json", market), ("account_snapshot.json", account),
            ("strategy_decision.json", strategy), ("control_decision.json", control),
            ("shadow_order_intent.json", intent), ("engine_state.json", state),
            ("engine_heartbeat.json", {"timestamp_utc": state["last_heartbeat_utc"], "pid": os.getpid(), "status": "ALIVE"}),
            ("v22_047_r1d_summary.json", summary),
        ):
            atomic_json(self.output_dir / name, payload)
        append_csv(self.output_dir / "audit_ledger.csv",
                   ("timestamp_utc", "event", "opend_status", "switch_mode", "effective_execution_mode",
                    "strategy_action", "strategy_reason_code", "order_intent_created", "broker_action_allowed", "trade_api_called"),
                   {"timestamp_utc": utc_iso(), "event": "SHADOW_CYCLE", "opend_status": state["opend_status"],
                    "switch_mode": switch["mode"], "effective_execution_mode": "SHADOW_ONLY",
                    "strategy_action": strategy["strategy_action"], "strategy_reason_code": strategy["strategy_reason_code"],
                    "order_intent_created": intent["order_intent_created"], "broker_action_allowed": False,
                    "trade_api_called": False})
        self._log("INFO", "CYCLE_COMPLETE", f"opend={state['opend_status']} strategy={strategy['strategy_reason_code']}")
        self.previous_state = state
        return summary

    def run(self, once: bool = False) -> int:
        self.lock.acquire()
        try:
            if self.stop_path.exists():
                self.stop_path.unlink()
            while self.running and not self.stop_path.exists():
                self.cycle()
                if once:
                    break
                deadline = time.monotonic() + self.interval
                while self.running and not self.stop_path.exists() and time.monotonic() < deadline:
                    time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
            state = read_json(self.output_dir / "engine_state.json", {}) or {}
            state.update({"engine_status": "CLEAN_STOP", "stopped_at_utc": utc_iso(), "broker_action_allowed": False, "trade_api_called": False})
            atomic_json(self.output_dir / "engine_state.json", state)
            return 0
        finally:
            self.lock.release()


HTML = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>V22.047 R1D Shadow Console</title><style>
:root{color-scheme:dark;--bg:#08111f;--card:#111d2f;--line:#263750;--text:#e8f0fb;--muted:#91a3bb;--good:#42d392;--warn:#ffcc66;--bad:#ff6b6b;--accent:#6ea8fe}*{box-sizing:border-box}body{margin:0;background:linear-gradient(150deg,#07101d,#10223b);font:14px system-ui;color:var(--text)}main{max-width:1400px;margin:auto;padding:22px}h1{font-size:22px;margin:0 0 5px}.sub{color:var(--muted);margin-bottom:18px}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:12px}.card{grid-column:span 6;background:rgba(17,29,47,.96);border:1px solid var(--line);border-radius:12px;padding:15px}.wide{grid-column:span 12}h2{font-size:15px;margin:0 0 12px;color:#bcd5fb}.kv{display:grid;grid-template-columns:190px 1fr;gap:8px;padding:5px 0;border-bottom:1px solid #1c2b40}.kv span:first-child{color:var(--muted)}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px;border-bottom:1px solid var(--line)}th{color:var(--muted);font-weight:500}.good{color:var(--good)}.bad{color:var(--bad)}.warn{color:var(--warn)}button{margin:4px;padding:8px 12px;border:1px solid #385070;border-radius:7px;background:#192b43;color:var(--text);cursor:pointer}button.danger{border-color:#8b3942;color:#ff9696}button:disabled{opacity:.45;cursor:not-allowed}.notice{padding:10px;background:#302812;border:1px solid #665522;border-radius:7px;color:var(--warn);margin-top:8px}@media(max-width:850px){.card{grid-column:span 12}.kv{grid-template-columns:145px 1fr}}</style></head>
<body><main><h1>V22.047 R1D · SHADOW ONLY</h1><div class="sub">本地只读行情/账户桥 · 券商动作永久禁用</div><div class="grid">
<section class="card" id="system"><h2>系统状态</h2></section><section class="card" id="strategy"><h2>策略</h2></section>
<section class="card wide" id="market"><h2>行情</h2></section><section class="card" id="account"><h2>账户</h2></section>
<section class="card" id="benchmark"><h2>QQQ 基准</h2></section><section class="card wide" id="control"><h2>控制</h2></section>
</div></main><script>
const e=x=>x===null||x===undefined?'—':x, kv=(k,v)=>`<div class="kv"><span>${k}</span><span>${e(v)}</span></div>`;
async function mode(m){await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:m})});load()}
async function emergency(){await fetch('/api/emergency-stop',{method:'POST'});load()}
async function load(){let d=await (await fetch('/api/state',{cache:'no-store'})).json(),s=d.summary||{},st=d.engine||{},q=(d.market||{}).quotes||{},a=d.account||{},x=d.strategy||{},c=d.control||{},b=c.benchmark_metrics||{};
document.querySelector('#system').innerHTML='<h2>系统状态</h2>'+kv('Engine',st.engine_status)+kv('OpenD',st.opend_status)+kv('Endpoint',st.opend_endpoint)+kv('当前模式',st.switch_mode)+kv('有效执行模式',st.effective_execution_mode)+kv('最后心跳',st.last_heartbeat_utc)+kv('美股时段',st.market_session);
document.querySelector('#strategy').innerHTML='<h2>策略</h2>'+kv('插件路径',x.plugin_path)+kv('strategy_configured',x.strategy_configured)+kv('action',x.strategy_action)+kv('symbol',x.strategy_symbol)+kv('target_notional_usd',x.target_notional_usd)+kv('confidence',x.confidence)+kv('reason_code',x.strategy_reason_code)+'<div class="notice">'+e(x.display_message)+'</div>';
let rows=['US.QQQ','US.IQQ','US.TQQQ','US.SQQQ'].map(z=>{let r=q[z]||{};return `<tr><td>${z}</td><td>${e(r.latest_price)}</td><td>${e(r.bid)}</td><td>${e(r.ask)}</td><td>${e(r.spread_absolute)}</td><td>${e(r.quote_age_seconds)}</td><td>${e(r.market_status)}</td></tr>`}).join('');document.querySelector('#market').innerHTML='<h2>行情</h2><table><thead><tr><th>标的</th><th>最新价</th><th>Bid</th><th>Ask</th><th>Spread</th><th>Quote age(s)</th><th>Market status</th></tr></thead><tbody>'+rows+'</tbody></table>';
let positions=(a.positions_detail||[]).map(p=>`<tr><td>${e(p.code)}</td><td>${e(p.qty)}</td><td>${e(p.market_val)}</td><td>${e(p.today_pl_val)}</td></tr>`).join('');document.querySelector('#account').innerHTML='<h2>账户</h2>'+kv('账户类型',a.account_type)+kv('净值',a.net_liquidation_value_usd)+kv('现金',a.available_cash_usd)+kv('购买力',a.buying_power_usd)+kv('未完成订单',a.open_order_count)+kv('今日成交',(a.today_deals||[]).length)+kv('今日已实现盈亏',a.realized_pnl_today_usd)+kv('今日未实现盈亏',a.unrealized_pnl_today_usd)+'<table><thead><tr><th>当前持仓</th><th>数量</th><th>市值</th><th>今日盈亏</th></tr></thead><tbody>'+positions+'</tbody></table>';
document.querySelector('#benchmark').innerHTML='<h2>QQQ 基准</h2>'+kv('策略账户收益',b.strategy_return)+kv('QQQ同期收益',b.qqq_return)+kv('超额收益',b.excess_return)+kv('benchmark_status',b.status);
document.querySelector('#control').innerHTML='<h2>控制</h2><button onclick="mode(\'OFF\')">OFF</button><button onclick="mode(\'SHADOW\')">SHADOW</button><button disabled>PAPER · NOT AVAILABLE IN R1D</button><button disabled>LIVE · NOT AVAILABLE IN R1D</button><button onclick="mode(\'FLATTEN_ONLY\')">FLATTEN_ONLY (SHADOW)</button><button class="danger" onclick="emergency()">EMERGENCY STOP</button>'+kv('broker_action_allowed',c.broker_action_allowed)+kv('trade_api_called',c.trade_api_called)}
load();setInterval(load,3000);</script></body></html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    output_dir: Path

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _json(self, payload: Mapping[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            body = HTML.encode("utf-8"); self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body); return
        if path == "/api/state":
            names = {"summary": "v22_047_r1d_summary.json", "engine": "engine_state.json", "market": "market_snapshot.json",
                     "account": "account_snapshot.json", "strategy": "strategy_decision.json", "control": "control_decision.json",
                     "intent": "shadow_order_intent.json"}
            self._json({k: read_json(self.output_dir / v, {}) or {} for k, v in names.items()}); return
        self._json({"error": "NOT_FOUND"}, 404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/emergency-stop":
            atomic_json(self.output_dir / "emergency_stop.json", {"active": True, "timestamp_utc": utc_iso(), "source": "LOCAL_UI"})
            atomic_json(self.output_dir / "switch_state.json", {"schema_version": 1, "mode": "OFF", "updated_at_utc": utc_iso(), "updated_by": "LOCAL_UI", "note": "EMERGENCY STOP"})
            self._json({"ok": True, "mode": "OFF", "broker_action_allowed": False}); return
        if path == "/api/control":
            try:
                length = min(int(self.headers.get("Content-Length", "0")), 4096)
                payload = json.loads(self.rfile.read(length) or b"{}")
                mode = str(payload.get("mode", "")).upper()
            except Exception:
                self._json({"error": "INVALID_JSON"}, 400); return
            if mode in {"PAPER", "LIVE"}:
                self._json({"error": "NOT_AVAILABLE_IN_R1D", "broker_action_allowed": False}, 409); return
            if mode not in {"OFF", "SHADOW", "FLATTEN_ONLY"}:
                self._json({"error": "INVALID_MODE"}, 400); return
            atomic_json(self.output_dir / "switch_state.json", {"schema_version": 1, "mode": mode, "updated_at_utc": utc_iso(), "updated_by": "LOCAL_UI", "note": "R1D shadow control"})
            if mode != "OFF" and (self.output_dir / "emergency_stop.json").exists():
                atomic_json(self.output_dir / "emergency_stop.json", {"active": False, "timestamp_utc": utc_iso(), "source": "LOCAL_UI_RESET"})
            self._json({"ok": True, "mode": mode, "effective_execution_mode": "SHADOW_ONLY", "broker_action_allowed": False}); return
        self._json({"error": "NOT_FOUND"}, 404)


def run_ui(repo_root: Path, port: int = UI_PORT) -> int:
    if HOST != "127.0.0.1":
        raise R1DError("UI_BIND_MUST_BE_LOOPBACK")
    output_dir = repo_root.resolve() / "outputs" / "v22" / OUTPUT_FOLDER
    output_dir.mkdir(parents=True, exist_ok=True)
    handler = type("R1DDashboardHandler", (DashboardHandler,), {"output_dir": output_dir})
    server = ThreadingHTTPServer((HOST, port), handler)
    print(f"ui_url=http://{HOST}:{port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def status(repo_root: Path) -> int:
    output = repo_root.resolve() / "outputs" / "v22" / OUTPUT_FOLDER
    state = read_json(output / "engine_state.json", {}) or {}
    heartbeat = read_json(output / "engine_heartbeat.json", {}) or {}
    lock = output / "runtime" / "engine.lock"
    pid = int(lock.read_text().strip()) if lock.exists() else 0
    payload = {
        "engine_process_running": SingleInstance.alive(pid), "engine_pid": pid or None,
        "engine_status": state.get("engine_status", "NOT_STARTED"), "opend_status": state.get("opend_status", "UNKNOWN"),
        "last_heartbeat_utc": heartbeat.get("timestamp_utc"), "effective_execution_mode": "SHADOW_ONLY",
        "broker_action_allowed": False, "trade_api_called": False, "ui_url": f"http://{HOST}:{UI_PORT}",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2)); return 0 if payload["engine_process_running"] else 1


def watchdog(repo_root: Path, stale_seconds: float = 45.0) -> int:
    output = repo_root.resolve() / "outputs" / "v22" / OUTPUT_FOLDER
    output.mkdir(parents=True, exist_ok=True)
    stop = output / "watchdog.stop"
    if stop.exists(): stop.unlink()
    while not stop.exists():
        lock = output / "runtime" / "engine.lock"
        try: pid = int(lock.read_text().strip())
        except Exception: pid = 0
        heartbeat = read_json(output / "engine_heartbeat.json", {}) or {}
        age = math.inf
        try: age = (utc_now() - datetime.fromisoformat(str(heartbeat.get("timestamp_utc")))).total_seconds()
        except Exception: pass
        if not SingleInstance.alive(pid) or age > stale_seconds:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "engine", "--repo-root", str(repo_root)],
                             cwd=str(repo_root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        time.sleep(10)
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("engine", "ui", "status", "watchdog"):
        child = sub.add_parser(name); child.add_argument("--repo-root", default=r"D:\us-tech-quant")
        if name == "engine": child.add_argument("--once", action="store_true"); child.add_argument("--interval", type=float, default=10.0)
        if name == "ui": child.add_argument("--port", type=int, default=UI_PORT)
        if name == "watchdog": child.add_argument("--stale-seconds", type=float, default=45.0)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    repo = Path(args.repo_root)
    try:
        if args.command == "engine":
            engine = Engine(repo, interval=args.interval)
            def stop_handler(*_: Any) -> None: engine.running = False
            signal.signal(signal.SIGINT, stop_handler)
            if hasattr(signal, "SIGTERM"): signal.signal(signal.SIGTERM, stop_handler)
            return engine.run(once=args.once)
        if args.command == "ui": return run_ui(repo, args.port)
        if args.command == "status": return status(repo)
        if args.command == "watchdog": return watchdog(repo, args.stale_seconds)
        return 2
    except Exception as exc:
        print(f"final_status=FAIL_{REVISION}", file=sys.stderr)
        print(f"error={type(exc).__name__}:{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
