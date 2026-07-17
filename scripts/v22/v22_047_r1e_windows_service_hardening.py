#!/usr/bin/env python
"""V22.047 R1E Windows autostart, hardened watchdog and Dashboard V2.

This is an infrastructure layer over the existing R1D Engine.  It contains no
strategy logic and never exposes or calls a broker mutation API.
"""
from __future__ import annotations

import argparse
import csv
import ctypes
import importlib.util
import json
import math
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

REVISION = "V22.047_R1E"
STAGE = "V22.047_R1E_WINDOWS_AUTOSTART_SERVICE_HARDENING_AND_DASHBOARD_V2_SHADOW_ONLY"
OUTPUT_FOLDER = STAGE
HOST = "127.0.0.1"
PORT = 8765
ALLOWED_EXECUTION_SYMBOLS = ("US.IQQ", "US.TQQQ", "US.SQQQ")
KNOWN_MARKET_SYMBOLS = ("US.QQQ",) + ALLOWED_EXECUTION_SYMBOLS
BROKER_MUTATION_APIS = ("unlock_trade", "place_order", "modify_order", "cancel_order", "cancel_all_order")


class R1EError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso() -> str:
    return utc_now().isoformat()


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise R1EError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            handle.write("\n")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def ensure_csv(path: Path, fields: Sequence[str]) -> None:
    if path.exists() and path.stat().st_size:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.DictWriter(handle, fieldnames=list(fields)).writeheader()


def append_csv(path: Path, fields: Sequence[str], row: Mapping[str, Any]) -> None:
    ensure_csv(path, fields)
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writerow({key: row.get(key, "") for key in fields})


def timestamp_age(value: Any) -> float:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (utc_now() - parsed.astimezone(timezone.utc)).total_seconds())
    except Exception:
        return math.inf


def pid_from(path: Path) -> int:
    try:
        return int(path.read_text(encoding="ascii").strip())
    except Exception:
        return 0


def tcp_ready(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def network_available() -> bool:
    if os.name == "nt":
        try:
            flags = ctypes.c_ulong()
            return bool(ctypes.windll.wininet.InternetGetConnectedState(ctypes.byref(flags), 0))
        except Exception:
            pass
    try:
        socket.getaddrinfo("www.microsoft.com", 443)
        return True
    except OSError:
        return False


@dataclass(frozen=True)
class Paths:
    repo: Path
    output: Path
    runtime: Path
    r1d_output: Path
    r1d_script: Path
    profile: Path

    @classmethod
    def for_repo(cls, repo_root: Path) -> "Paths":
        repo = repo_root.resolve()
        output = repo / "outputs" / "v22" / OUTPUT_FOLDER
        return cls(
            repo=repo,
            output=output,
            runtime=output / "runtime",
            r1d_output=repo / "outputs" / "v22" / "V22.047_R1D_LIVE_MARKET_ACCOUNT_BRIDGE_AND_LOCAL_DASHBOARD_SHADOW_ONLY",
            r1d_script=repo / "scripts" / "v22" / "v22_047_r1d_live_market_account_bridge.py",
            profile=repo / "config" / "moomoo_opend_connection.json",
        )


AUDIT_FIELDS = (
    "timestamp_utc", "event", "service_status", "watchdog_status", "engine_pid", "ui_pid",
    "opend_tcp", "quote_api", "market_snapshot_fresh", "account_snapshot_fresh",
    "degraded_latched", "switch_mode", "effective_execution_mode", "broker_action_allowed", "trade_api_called", "detail",
)
ERROR_FIELDS = ("timestamp_utc", "severity", "stage", "error", "fail_closed")


def initialize(paths: Paths) -> None:
    paths.runtime.mkdir(parents=True, exist_ok=True)
    (paths.output / "logs").mkdir(parents=True, exist_ok=True)
    ensure_csv(paths.output / "audit_ledger.csv", AUDIT_FIELDS)
    ensure_csv(paths.output / "error_ledger.csv", ERROR_FIELDS)


def audit(paths: Paths, event: str, detail: str = "", **values: Any) -> None:
    row = {
        "timestamp_utc": utc_iso(), "event": event, "detail": detail,
        "effective_execution_mode": "SHADOW_ONLY", "broker_action_allowed": False, "trade_api_called": False,
    }
    row.update(values)
    append_csv(paths.output / "audit_ledger.csv", AUDIT_FIELDS, row)


def record_error(paths: Paths, stage: str, error: str, severity: str = "ERROR") -> None:
    append_csv(paths.output / "error_ledger.csv", ERROR_FIELDS,
               {"timestamp_utc": utc_iso(), "severity": severity, "stage": stage, "error": error, "fail_closed": True})
    audit(paths, "FAIL_CLOSED_ERROR", f"{stage}:{error}")


def connection(paths: Paths) -> tuple[str, int]:
    profile = read_json(paths.profile, {}) or {}
    host, port = str(profile.get("host", "")), int(profile.get("port", 0))
    if host != HOST or port != 18441:
        raise R1EError("OPEND_ENDPOINT_MUST_BE_127_0_0_1_18441")
    if any(profile.get(key) for key in ("password", "trade_password", "account_id")):
        raise R1EError("SENSITIVE_OPEND_PROFILE_FIELD_FORBIDDEN")
    return host, port


def process_alive(r1d: Any, pid: int) -> bool:
    return bool(r1d.SingleInstance.alive(pid))


def set_switch(paths: Paths, mode: str, note: str, *, emergency: bool = False) -> None:
    normalized = mode.upper()
    if normalized not in {"OFF", "SHADOW", "FLATTEN_ONLY"}:
        raise R1EError(f"R1E_MODE_NOT_AVAILABLE:{normalized}")
    atomic_json(paths.r1d_output / "switch_state.json", {
        "schema_version": 1, "mode": normalized, "updated_at_utc": utc_iso(),
        "updated_by": "R1E_HARDENING", "note": note,
    })
    atomic_json(paths.r1d_output / "emergency_stop.json", {
        "active": bool(emergency), "timestamp_utc": utc_iso(), "source": "R1E_HARDENING", "note": note,
    })


def enforce_shadow_default(paths: Paths) -> str:
    state = read_json(paths.r1d_output / "switch_state.json", {}) or {}
    existing = str(state.get("mode", "OFF")).upper()
    latch = bool((read_json(paths.runtime / "degraded_latch.json", {}) or {}).get("active"))
    if existing in {"LIVE", "PAPER"} or existing not in {"OFF", "SHADOW", "FLATTEN_ONLY"}:
        audit(paths, "UNSAFE_MODE_REPLACED", existing)
    if latch:
        set_switch(paths, "SHADOW", "DEGRADED latch retained; shadow display with authorization blocked", emergency=True)
        return "SHADOW"
    set_switch(paths, "SHADOW", "R1E default mode; LIVE/PAPER never restored", emergency=False)
    return "SHADOW"


def power_state(powercfg_text: str | None = None, ac_status: int | None = None) -> dict[str, Any]:
    raw = powercfg_text
    if raw is None:
        try:
            result = subprocess.run(["powercfg", "/a"], capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=10)
            raw = result.stdout or result.stderr
        except Exception as exc:
            raw = f"POWERCFG_FAILED:{type(exc).__name__}:{exc}"
    if ac_status is None:
        ac_status = 255
        if os.name == "nt":
            class SystemPowerStatus(ctypes.Structure):
                _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                            ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                            ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
            value = SystemPowerStatus()
            if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(value)):
                ac_status = int(value.ACLineStatus)
    marker_positions = [pos for marker in ("The following sleep states are not available", "此系统上没有以下睡眠状态")
                        if (pos := raw.find(marker)) >= 0]
    available = raw[:min(marker_positions)] if marker_positions else raw
    sleep_allowed = bool(re.search(r"Standby\s*\(|待机\s*\(|Sleep", available, re.IGNORECASE))
    hibernate_allowed = bool(re.search(r"Hibernate|休眠", available, re.IGNORECASE))
    ac_connected = ac_status == 1
    safe = bool(ac_connected and not sleep_allowed and not hibernate_allowed)
    risks = []
    if not ac_connected: risks.append("AC_POWER_NOT_CONFIRMED")
    if sleep_allowed: risks.append("SYSTEM_SLEEP_ALLOWED")
    if hibernate_allowed: risks.append("SYSTEM_HIBERNATE_ALLOWED")
    if ac_status == 255: risks.append("POWER_SOURCE_UNKNOWN")
    return {
        "schema_version": 1, "timestamp_utc": utc_iso(), "ac_connected": ac_connected,
        "ac_line_status_raw": ac_status, "system_sleep_allowed": sleep_allowed,
        "system_hibernate_allowed": hibernate_allowed, "energy_saving_risk": bool(risks),
        "POWER_SAFE_FOR_BACKGROUND_TRADING": safe, "risk_reasons": risks,
        "power_policy_modified": False, "powercfg_a_output": raw,
    }


def launch_python(paths: Paths, arguments: Sequence[str], pid_path: Path) -> int:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen([sys.executable, *arguments], cwd=str(paths.repo),
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=flags)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(process.pid), encoding="ascii")
    return process.pid


def engine_pid(paths: Paths) -> int:
    return pid_from(paths.r1d_output / "runtime" / "engine.lock")


def start_engine(paths: Paths, r1d: Any, interval: float = 10.0) -> tuple[int, bool]:
    current = engine_pid(paths)
    if process_alive(r1d, current):
        audit(paths, "DUPLICATE_ENGINE_START_REJECTED", f"pid={current}", engine_pid=current)
        return current, False
    pid = launch_python(paths, [str(paths.r1d_script), "engine", "--repo-root", str(paths.repo), "--interval", str(interval)],
                        paths.runtime / "engine_launcher.pid")
    audit(paths, "ENGINE_START_REQUESTED", f"pid={pid}", engine_pid=pid)
    return pid, True


def ui_pid(paths: Paths) -> int:
    state = read_json(paths.output / "ui_state.json", {}) or {}
    return int(state.get("pid") or 0)


def start_ui(paths: Paths, r1d: Any, *, desired: bool = True) -> tuple[int, bool]:
    current = ui_pid(paths)
    if process_alive(r1d, current):
        return current, False
    pid = launch_python(paths, [str(Path(__file__).resolve()), "ui", "--repo-root", str(paths.repo)], paths.runtime / "ui_launcher.pid")
    atomic_json(paths.output / "ui_state.json", {
        "schema_version": 1, "timestamp_utc": utc_iso(), "desired_running": desired,
        "actual_running": True, "pid": pid, "bind_host": HOST, "port": PORT,
        "url": f"http://{HOST}:{PORT}", "engine_dependency": False,
    })
    audit(paths, "UI_START_REQUESTED", f"pid={pid}", ui_pid=pid)
    return pid, True


def terminate_pid(r1d: Any, pid: int, timeout: float = 10.0) -> bool:
    if not process_alive(r1d, pid):
        return True
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return not process_alive(r1d, pid)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not process_alive(r1d, pid):
            return True
        time.sleep(0.2)
    return False


def quote_probe(paths: Paths, r1d: Any) -> tuple[bool, str]:
    try:
        profile = r1d.load_connection_profile(paths.profile)
        bridge = r1d.MoomooReadOnlyBridge(profile, paths.output, 15.0)
        market = bridge.market_snapshot()
        return bool(market.get("snapshot_ready")), "QUOTE_API_OK" if market.get("snapshot_ready") else "QUOTE_DATA_NOT_READY"
    except Exception as exc:
        return False, f"{type(exc).__name__}:{exc}"


def unknown_exposure(account: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    unknown_positions = sorted({
        str(item.get("code", "")).upper() for item in account.get("positions_detail", [])
        if isinstance(item, Mapping) and abs(float(item.get("qty") or 0.0)) > 0
        and str(item.get("code", "")).upper() not in ALLOWED_EXECUTION_SYMBOLS
    })
    unknown_orders = sorted({
        str(item.get("code", "")).upper() for item in account.get("open_orders", [])
        if isinstance(item, Mapping) and str(item.get("code", "")).upper() not in ALLOWED_EXECUTION_SYMBOLS
    })
    return unknown_positions, unknown_orders


def latch_degraded(paths: Paths, reasons: Sequence[str], detail: Mapping[str, Any] | None = None) -> dict[str, Any]:
    prior = read_json(paths.runtime / "degraded_latch.json", {}) or {}
    combined = sorted(set(prior.get("reasons", [])) | set(reasons))
    payload = {
        "schema_version": 1, "active": True,
        "latched_at_utc": prior.get("latched_at_utc") or utc_iso(), "updated_at_utc": utc_iso(),
        "reasons": combined, "detail": dict(detail or {}), "automatic_clear_allowed": False,
        "broker_action_allowed": False,
    }
    atomic_json(paths.runtime / "degraded_latch.json", payload)
    return payload


def watchdog_snapshot(paths: Paths, r1d: Any, *, stale_seconds: float = 45.0, restart_engine: bool = True) -> dict[str, Any]:
    host, port = connection(paths)
    market = read_json(paths.r1d_output / "market_snapshot.json", {}) or {}
    account = read_json(paths.r1d_output / "account_snapshot.json", {}) or {}
    strategy = read_json(paths.r1d_output / "strategy_decision.json", {}) or {}
    control = read_json(paths.r1d_output / "control_decision.json", {}) or {}
    heartbeat = read_json(paths.r1d_output / "engine_heartbeat.json", {}) or {}
    engine = engine_pid(paths)
    engine_alive = process_alive(r1d, engine)
    heartbeat_age = timestamp_age(heartbeat.get("timestamp_utc"))
    market_age = timestamp_age(market.get("snapshot_at_utc"))
    account_age = timestamp_age(account.get("snapshot_at_utc"))
    opend = tcp_ready(host, port)
    quote_ok = bool(opend and market.get("snapshot_ready") and market_age <= stale_seconds)
    market_fresh = market_age <= stale_seconds
    account_fresh = bool(account.get("account_snapshot_ready") and account_age <= stale_seconds)
    plugin_ok = bool(strategy.get("plugin_called") and not strategy.get("strategy_error"))
    control_ok = bool(control.get("r1b_control_component_called") and not control.get("control_error"))
    unknown_positions, unknown_orders = unknown_exposure(account)
    latch_reasons = []
    if unknown_positions: latch_reasons.append("UNKNOWN_POSITION")
    if unknown_orders: latch_reasons.append("UNKNOWN_OPEN_ORDER")
    if latch_reasons:
        latch_degraded(paths, latch_reasons, {"unknown_positions": unknown_positions, "unknown_orders": unknown_orders})
        set_switch(paths, "SHADOW", "DEGRADED unknown exposure; authorization blocked", emergency=True)
    latch = read_json(paths.runtime / "degraded_latch.json", {}) or {}
    restart_requested = False
    if (not engine_alive or heartbeat_age > stale_seconds) and restart_engine:
        set_switch(paths, "OFF", "Engine unavailable; fail-closed before restart", emergency=True)
        record_error(paths, "WATCHDOG_ENGINE", f"alive={engine_alive};heartbeat_age={heartbeat_age:.1f}")
        _, restart_requested = start_engine(paths, r1d)
    if not opend:
        set_switch(paths, "OFF", "OpenD disconnected; fail-closed", emergency=True)
    ui_state = read_json(paths.output / "ui_state.json", {}) or {}
    dashboard_pid = int(ui_state.get("pid") or 0)
    dashboard_alive = process_alive(r1d, dashboard_pid)
    ui_restarted = False
    if ui_state.get("desired_running") and not dashboard_alive:
        dashboard_pid, ui_restarted = start_ui(paths, r1d, desired=True)
        dashboard_alive = True
    critical_ready = all((engine_alive, heartbeat_age <= stale_seconds, opend, quote_ok, market_fresh,
                          account_fresh, plugin_ok, control_ok))
    status = "DEGRADED" if latch.get("active") or not critical_ready else "HEALTHY"
    payload = {
        "schema_version": 1, "revision": REVISION, "timestamp_utc": utc_iso(), "watchdog_status": status,
        "engine_pid": engine, "engine_alive": engine_alive, "engine_heartbeat_age_seconds": heartbeat_age,
        "engine_restart_requested": restart_requested, "opend_tcp_ready": opend, "quote_api_ready": quote_ok,
        "market_snapshot_fresh": market_fresh, "market_snapshot_age_seconds": market_age,
        "market_quote_data_fresh": bool(market.get("all_quotes_fresh")),
        "account_snapshot_fresh": account_fresh, "account_snapshot_age_seconds": account_age,
        "strategy_plugin_ready": plugin_ok, "strategy_configured": bool(strategy.get("strategy_configured")),
        "strategy_reason_code": strategy.get("strategy_reason_code"), "r1b_control_ready": control_ok,
        "ui_pid": dashboard_pid or None, "ui_alive": dashboard_alive, "ui_restart_requested": ui_restarted,
        "unknown_positions": unknown_positions, "unknown_open_orders": unknown_orders,
        "degraded_latched": bool(latch.get("active")), "degraded_reasons": latch.get("reasons", []),
        "automatic_degraded_clear_allowed": False, "effective_execution_mode": "SHADOW_ONLY",
        "broker_action_allowed": False, "trade_api_called": False,
    }
    atomic_json(paths.output / "watchdog_state.json", payload)
    audit(paths, "WATCHDOG_CYCLE", watchdog_status=status, engine_pid=engine, ui_pid=dashboard_pid,
          opend_tcp=opend, quote_api=quote_ok, market_snapshot_fresh=market_fresh,
          account_snapshot_fresh=account_fresh, degraded_latched=payload["degraded_latched"],
          switch_mode=(read_json(paths.r1d_output / "switch_state.json", {}) or {}).get("mode"))
    return payload


def write_summary(paths: Paths, service_status: str, watchdog: Mapping[str, Any] | None = None) -> dict[str, Any]:
    strategy = read_json(paths.r1d_output / "strategy_decision.json", {}) or {}
    control = read_json(paths.r1d_output / "control_decision.json", {}) or {}
    switch = read_json(paths.r1d_output / "switch_state.json", {}) or {}
    power = power_state()
    atomic_json(paths.output / "power_state.json", power)
    payload = {
        "schema_version": 1, "revision": REVISION, "stage": STAGE, "timestamp_utc": utc_iso(),
        "final_status": "R1E_PASS_SHADOW_AUTOSTART_AND_DASHBOARD_READY",
        "service_status": service_status, "watchdog_status": (watchdog or {}).get("watchdog_status", "STARTING"),
        "switch_mode": switch.get("mode", "SHADOW"), "effective_execution_mode": "SHADOW_ONLY",
        "strategy_configured": bool(strategy.get("strategy_configured", False)),
        "strategy_action": strategy.get("strategy_action", "HOLD"),
        "strategy_reason_code": strategy.get("strategy_reason_code", "STRATEGY_NOT_CONFIGURED"),
        "r1b_control_component_called": bool(control.get("r1b_control_component_called", False)),
        "broker_action_allowed": False, "trade_api_called": False,
        "dashboard_url": f"http://{HOST}:{PORT}", "dashboard_bind_host": HOST,
        "power_safe_for_background_trading": power["POWER_SAFE_FOR_BACKGROUND_TRADING"],
    }
    atomic_json(paths.output / "v22_047_r1e_summary.json", payload)
    return payload


class Service:
    def __init__(self, repo_root: Path, wait_seconds: float = 1800.0):
        self.paths = Paths.for_repo(repo_root)
        initialize(self.paths)
        self.r1d = load_module(self.paths.r1d_script, "v22_047_r1d_for_r1e_service")
        self.lock = self.r1d.SingleInstance(self.paths.runtime / "service.lock")
        self.wait_seconds = wait_seconds
        self.running = True

    def state(self, status: str, detail: str = "") -> None:
        payload = {
            "schema_version": 1, "revision": REVISION, "timestamp_utc": utc_iso(),
            "service_status": status, "detail": detail, "pid": os.getpid(),
            "network_ready": network_available(), "effective_execution_mode": "SHADOW_ONLY",
            "broker_action_allowed": False, "trade_api_called": False,
        }
        atomic_json(self.paths.output / "service_state.json", payload)
        write_summary(self.paths, status, read_json(self.paths.output / "watchdog_state.json", {}) or {})

    def wait_prerequisites(self) -> None:
        host, port = connection(self.paths)
        deadline = time.monotonic() + self.wait_seconds
        while self.running and time.monotonic() < deadline:
            if not network_available():
                self.state("WAITING_FOR_NETWORK")
                time.sleep(5); continue
            if not tcp_ready(host, port):
                self.state("WAITING_FOR_OPEND", f"{host}:{port}")
                time.sleep(5); continue
            ok, reason = quote_probe(self.paths, self.r1d)
            if ok:
                audit(self.paths, "STARTUP_QUOTE_PROBE_PASS", reason, opend_tcp=True, quote_api=True)
                return
            self.state("WAITING_FOR_QUOTE_API", reason)
            time.sleep(10)
        raise R1EError("STARTUP_PREREQUISITE_TIMEOUT")

    def run(self) -> int:
        self.lock.acquire()
        stop = self.paths.output / "service.stop"
        watchdog_stop = self.paths.output / "watchdog.stop"
        try:
            for flag in (stop, watchdog_stop):
                if flag.exists(): flag.unlink()
            self.paths.runtime.joinpath("service.pid").write_text(str(os.getpid()), encoding="ascii")
            enforce_shadow_default(self.paths)
            autostart = read_json(self.paths.output / "autostart_state.json", {}) or {}
            autostart.update({
                "schema_version": 1, "timestamp_utc": utc_iso(), "service_invoked": True,
                "network_wait_enabled": True, "opend_wait_endpoint": "127.0.0.1:18441",
                "quote_probe_required": True, "default_mode": "SHADOW", "live_auto_restore_allowed": False,
            })
            atomic_json(self.paths.output / "autostart_state.json", autostart)
            self.state("STARTING")
            self.wait_prerequisites()
            start_engine(self.paths, self.r1d)
            r1f_script = self.paths.repo / "scripts" / "v22" / "v22_047_r1f_fractional_protected_sleeve.py"
            r1f_pid = pid_from(self.paths.runtime / "r1f.pid")
            if r1f_script.exists() and not process_alive(self.r1d, r1f_pid):
                r1f_pid = launch_python(self.paths, [str(r1f_script), "--service", "--repo-root", str(self.paths.repo)], self.paths.runtime / "r1f.pid")
            r1g_script = self.paths.repo / "scripts" / "v22" / "v22_047_r1g_shadow_fractional_assumption_and_execution_arming.py"
            r1g_pid = pid_from(self.paths.runtime / "r1g.pid")
            if r1g_script.exists() and not process_alive(self.r1d, r1g_pid):
                r1g_pid = launch_python(self.paths, [str(r1g_script), "--service", "--repo-root", str(self.paths.repo)], self.paths.runtime / "r1g.pid")
            r1h_script = self.paths.repo / "scripts" / "v22" / "v22_047_r1h_paper_execution_order_lifecycle_and_reconciliation.py"
            r1h_pid = pid_from(self.paths.runtime / "r1h.pid")
            if r1h_script.exists() and not process_alive(self.r1d, r1h_pid):
                r1h_pid = launch_python(self.paths, [str(r1h_script), "--service", "--repo-root", str(self.paths.repo)], self.paths.runtime / "r1h.pid")
            r1i_script = self.paths.repo / "scripts" / "v22" / "v22_047_r1i_paper_soak_replay_fault_injection_and_live_readiness_gate.py"
            r1i_pid = pid_from(self.paths.runtime / "r1i.pid")
            if r1i_script.exists() and not process_alive(self.r1d, r1i_pid):
                r1i_pid = launch_python(self.paths, [str(r1i_script), "--service", "--repo-root", str(self.paths.repo)], self.paths.runtime / "r1i.pid")
            watchdog_pid = pid_from(self.paths.runtime / "watchdog.pid")
            if not process_alive(self.r1d, watchdog_pid):
                watchdog_pid = launch_python(self.paths, [str(Path(__file__).resolve()), "watchdog", "--repo-root", str(self.paths.repo)],
                                             self.paths.runtime / "watchdog.pid")
            self.state("RUNNING", f"watchdog_pid={watchdog_pid};r1f_pid={r1f_pid};r1g_pid={r1g_pid};r1h_pid={r1h_pid};r1i_pid={r1i_pid}")
            audit(self.paths, "SERVICE_RUNNING", f"watchdog_pid={watchdog_pid}", service_status="RUNNING")
            while self.running and not stop.exists():
                watchdog_pid = pid_from(self.paths.runtime / "watchdog.pid")
                if not process_alive(self.r1d, watchdog_pid):
                    record_error(self.paths, "SERVICE", "WATCHDOG_PROCESS_DIED")
                    watchdog_pid = launch_python(self.paths, [str(Path(__file__).resolve()), "watchdog", "--repo-root", str(self.paths.repo)],
                                                 self.paths.runtime / "watchdog.pid")
                r1f_pid = pid_from(self.paths.runtime / "r1f.pid")
                if r1f_script.exists() and not process_alive(self.r1d, r1f_pid):
                    record_error(self.paths, "SERVICE", "R1F_PROCESS_DIED")
                    r1f_pid = launch_python(self.paths, [str(r1f_script), "--service", "--repo-root", str(self.paths.repo)], self.paths.runtime / "r1f.pid")
                r1g_pid = pid_from(self.paths.runtime / "r1g.pid")
                if r1g_script.exists() and not process_alive(self.r1d, r1g_pid):
                    record_error(self.paths, "SERVICE", "R1G_PROCESS_DIED")
                    r1g_pid = launch_python(self.paths, [str(r1g_script), "--service", "--repo-root", str(self.paths.repo)], self.paths.runtime / "r1g.pid")
                r1h_pid = pid_from(self.paths.runtime / "r1h.pid")
                if r1h_script.exists() and not process_alive(self.r1d, r1h_pid):
                    record_error(self.paths, "SERVICE", "R1H_PROCESS_DIED")
                    r1h_pid = launch_python(self.paths, [str(r1h_script), "--service", "--repo-root", str(self.paths.repo)], self.paths.runtime / "r1h.pid")
                r1i_pid = pid_from(self.paths.runtime / "r1i.pid")
                if r1i_script.exists() and not process_alive(self.r1d, r1i_pid):
                    record_error(self.paths, "SERVICE", "R1I_PROCESS_DIED")
                    r1i_pid = launch_python(self.paths, [str(r1i_script), "--service", "--repo-root", str(self.paths.repo)], self.paths.runtime / "r1i.pid")
                self.state("RUNNING", f"watchdog_pid={watchdog_pid};r1f_pid={r1f_pid};r1g_pid={r1g_pid};r1h_pid={r1h_pid};r1i_pid={r1i_pid}")
                time.sleep(5)
            self.state("STOPPING")
            return 0
        except Exception as exc:
            set_switch(self.paths, "OFF", "R1E service exception fail-closed", emergency=True)
            record_error(self.paths, "SERVICE", f"{type(exc).__name__}:{exc}")
            self.state("FAILED", f"{type(exc).__name__}:{exc}")
            return 2
        finally:
            self.lock.release()


def run_watchdog(repo_root: Path, interval: float = 5.0, once: bool = False) -> int:
    paths = Paths.for_repo(repo_root); initialize(paths)
    r1d = load_module(paths.r1d_script, "v22_047_r1d_for_r1e_watchdog")
    lock = r1d.SingleInstance(paths.runtime / "watchdog.lock")
    lock.acquire()
    stop = paths.output / "watchdog.stop"
    try:
        while not stop.exists():
            watchdog_snapshot(paths, r1d)
            if once: break
            time.sleep(max(1.0, interval))
        return 0
    finally:
        lock.release()


DASHBOARD_HTML = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>R1E Dashboard V2</title><!-- R1D fallback remains STRATEGY_NOT_CONFIGURED; R1F V8 is configured. LIVE_NOT_AVAILABLE. --><style>
:root{color-scheme:dark;--bg:#07101d;--panel:#101d30;--line:#253a56;--text:#e9f1fb;--muted:#91a5bf;--green:#49d49d;--amber:#ffc861;--red:#ff7373;--blue:#71a9ff}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 10% 0,#17365c,#07101d 45%);font:14px system-ui;color:var(--text)}header{position:sticky;top:0;z-index:4;background:#07101df2;border-bottom:1px solid var(--line);padding:12px 18px}.top{display:grid;grid-template-columns:repeat(8,minmax(105px,1fr));gap:7px}.badge{background:#102039;border:1px solid var(--line);border-radius:8px;padding:8px}.badge small{display:block;color:var(--muted);font-size:10px}.badge b{font-size:12px}.good{color:var(--green)}.warn{color:var(--amber)}.bad{color:var(--red)}main{max-width:1500px;margin:auto;padding:18px}.truth{display:flex;gap:9px;flex-wrap:wrap;margin:0 0 14px}.truth span{border:1px solid var(--line);border-radius:20px;padding:6px 10px;background:#102039}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:12px}.card{grid-column:span 6;background:#101d30eb;border:1px solid var(--line);border-radius:12px;padding:14px}.wide{grid-column:span 12}h2{font-size:14px;color:#bad6ff;margin:0 0 10px}.kv{display:grid;grid-template-columns:210px 1fr;border-bottom:1px solid #1b2b42;padding:5px}.kv span:first-child{color:var(--muted)}table{width:100%;border-collapse:collapse}th,td{padding:7px;border-bottom:1px solid var(--line);text-align:left}th{color:var(--muted)}button{padding:9px 12px;margin:4px;border:1px solid #3b5476;border-radius:7px;background:#172a44;color:var(--text)}button:disabled{opacity:.45}.emergency{position:fixed;right:20px;bottom:20px;background:#521e28;border:2px solid #ff7373;z-index:5;font-weight:700}@media(max-width:900px){.top{grid-template-columns:repeat(2,1fr)}.card{grid-column:span 12}}</style></head><body>
<header><div class="top" id="top"></div></header><main><div class="truth"><span>V8_REFERENCE_TREND_ROTATION</span><span>SHADOW_ONLY</span><span>USER_CONFIRMED_RTH_APP</span><span>SHADOW ASSUMPTION ACTIVE</span><span>SIMULATED TRADING ONLY</span><span>NOT REAL MONEY</span><span>LIVE NOT AVAILABLE</span><span style="display:none">PAPER_NOT_AVAILABLE legacy R1E boundary</span></div><div class="grid"><section class="card" id="system"><h2>SYSTEM</h2></section><section class="card" id="strategy"><h2>STRATEGY</h2></section><section class="card wide" id="market"><h2>MARKET</h2></section><section class="card" id="account"><h2>ACCOUNT</h2></section><section class="card" id="benchmark"><h2>QQQ BENCHMARK</h2></section><section class="card wide" id="planning"><h2>SHADOW FRACTIONAL PLANNING</h2></section><section class="card wide" id="paper"><h2>PAPER EXECUTION</h2></section><section class="card wide" id="audit"><h2>AUDIT</h2></section></div></main><button class="emergency" onclick="emergency()">EMERGENCY STOP</button><script>
const e=v=>v===null||v===undefined?'—':v,kv=(k,v)=>`<div class="kv"><span>${k}</span><span>${e(v)}</span></div>`,badge=(k,v,c='')=>`<div class="badge"><small>${k}</small><b class="${c}">${e(v)}</b></div>`;
async function post(path,body={}){let r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});return r.json()}async function emergency(){await post('/api/emergency-stop',{mode:'OFF'});load()}async function paperArm(){if(!confirm('PAPER ARM uses simulation only. Continue?'))return;let second=prompt('Type CONFIRM_PAPER_SIMULATE_ONLY');if(second!=='CONFIRM_PAPER_SIMULATE_ONLY')return;await post('/api/r1g/paper-arm',{first_confirmation:true,second_confirmation:second});load()}async function paperArmH(){if(!confirm('SIMULATED TRADING ONLY. NOT REAL MONEY. Continue?'))return;let second=prompt('Type CONFIRM_PAPER_SIMULATED_TRADING_ONLY');if(second!=='CONFIRM_PAPER_SIMULATED_TRADING_ONLY')return;await post('/api/r1h/paper-arm',{dashboard_clicked:true,first_confirmation:true,second_confirmation:second,execution_backend:'PAPER_LOCAL_SIM'});load()}async function load(){let d=await(await fetch('/api/state',{cache:'no-store'})).json(),s=d.summary||{},svc=d.service||{},w=d.watchdog||{},p=d.power||{},m=d.market||{},q=m.quotes||{},a=d.account||{},x=d.strategy||{},c=d.control||{},b=c.benchmark_metrics||{},r=d.r1f||{},rs=r.summary||{},rc=r.control||{},cap=(r.capability||{}).symbols||{},g=d.r1g||{},gs=g.summary||{},ga=g.assumption||{},gz=g.authorization||{},gt=g.target||{},gp=g.plan||{},gc=g.cash||{},h=d.r1h||{},hs=h.summary||{},ha=h.authorization||{},hb=h.backend||{},ho=(h.orders||{}).orders||{},hp=(h.portfolio||{}).positions||{},hc=h.cash||{},hf=h.performance||{},hr=h.reconciliation||{};
let rd=r.decision||{},rm=rd.metadata||{};document.querySelector('#top').innerHTML=badge('ENGINE',w.engine_alive?'RUNNING':'STOPPED',w.engine_alive?'good':'bad')+badge('WATCHDOG',w.watchdog_status,w.watchdog_status==='HEALTHY'?'good':'warn')+badge('OPEND',w.opend_tcp_ready?'CONNECTED':'DOWN',w.opend_tcp_ready?'good':'bad')+badge('MODE',s.effective_execution_mode,'good')+badge('STRATEGY',rm.strategy_name||x.strategy_reason_code,rm.strategy_configured?'good':'warn')+badge('SESSION',m.session_type)+badge('HEARTBEAT',w.engine_heartbeat_age_seconds)+badge('POWER STATE',p.POWER_SAFE_FOR_BACKGROUND_TRADING?'SAFE':'RISK',p.POWER_SAFE_FOR_BACKGROUND_TRADING?'good':'warn');
document.querySelector('#system').innerHTML='<h2>SYSTEM</h2>'+kv('Service',svc.service_status)+kv('Engine PID',w.engine_pid)+kv('UI PID',w.ui_pid)+kv('OpenD','127.0.0.1:18441')+kv('DEGRADED latch',w.degraded_latched)+kv('Reasons',(w.degraded_reasons||[]).join(', '))+kv('POWER_SAFE_FOR_BACKGROUND_TRADING',p.POWER_SAFE_FOR_BACKGROUND_TRADING)+kv('AC connected',p.ac_connected)+kv('Sleep allowed',p.system_sleep_allowed)+kv('Hibernate allowed',p.system_hibernate_allowed);
document.querySelector('#strategy').innerHTML='<h2>STRATEGY</h2>'+kv('Plugin',x.plugin_path)+kv('CURRENT V8 STATE',gs.current_v8_state||rs.active_state)+kv('TARGET PORTFOLIO',JSON.stringify(gt.target_weights||{}))+kv('STRATEGY CASH POOL',rs.strategy_cash_pool)+kv('STRATEGY SLEEVE NAV',rs.strategy_sleeve_nav)+kv('FRACTIONAL CAPABILITY STATUS',gs.fractional_capability_status)+kv('USER CONFIRMED RTH APP SUPPORT',ga.user_confirmed_rth_app_support)+kv('BROKER API CONFIRMED = FALSE',gs.broker_fractional_api_confirmed)+kv('SHADOW ASSUMPTION ACTIVE',gs.execution_assumption_only)+kv('EXECUTION AUTHORIZATION',gs.execution_authorization)+kv('Reason',(r.decision||{}).reason_code)+kv('R1B control called',rc.r1b_control_component_called)+kv('Broker action allowed',false)+kv('Real trade API called',false);
let qr=['US.QQQ','US.TQQQ','US.SQQQ','US.IQQQ','US.IQQ'].map(z=>{let r=q[z]||{};return `<tr><td>${z}</td><td>${e(r.latest_price)}</td><td>${e(r.bid)}</td><td>${e(r.ask)}</td><td>${e(r.spread_absolute)}</td><td>${e(r.quote_age_seconds)}</td><td>${e(r.data_fresh)}</td></tr>`}).join('');document.querySelector('#market').innerHTML='<h2>MARKET</h2><table><tr><th>Symbol</th><th>Last</th><th>Bid</th><th>Ask</th><th>Spread</th><th>Age</th><th>Fresh</th></tr>'+qr+'</table>';
let pos=(a.positions_detail||[]).map(r=>`<tr><td>${e(r.code)}</td><td>${e(r.qty)}</td><td>${e(r.market_val)}</td><td>${e(r.today_pl_val)}</td></tr>`).join(''),resume=['US.QQQ','US.TQQQ','US.SQQQ','US.IQQQ'].map(z=>`<button onclick="post('/api/r1f/resume-automation',{symbol:'${z}'}).then(load)">RESUME ${z}</button>`).join('');document.querySelector('#account').innerHTML='<h2>ACCOUNT</h2>'+kv('ACCOUNT TOTAL NAV',a.net_liquidation_value_usd)+kv('AVAILABLE CASH',rs.available_cash)+kv('STRATEGY CASH POOL',rs.strategy_cash_pool)+kv('NASDAQ ETF MANAGED SLEEVE',JSON.stringify(rs.nasdaq_etf_managed_sleeve||{}))+kv('OUT OF SCOPE PROTECTED POSITIONS',JSON.stringify(rs.out_of_scope_protected_positions||{}))+kv('MANUAL OVERRIDE ACTIVE',rs.manual_override_active)+kv('MANUAL OVERRIDE UNTIL',JSON.stringify(rs.manual_override_until||{}))+kv('FRACTIONAL CAPABILITY',JSON.stringify(cap))+kv('IQQ WAITING FOR MOOMOO AVAILABILITY',rs.iqq_status)+'<div><b>RESUME AUTOMATION NOW</b>'+resume+'</div>'+kv('System can manage','QQQ/TQQQ/SQQQ/IQQQ long positions and available cash')+kv('System can never manage','Non-Nasdaq stocks, options, unrelated ETFs and other assets')+'<table><tr><th>ACCOUNT TOTAL</th><th>Qty</th><th>Value</th><th>Today P/L</th></tr>'+pos+'</table>';
document.querySelector('#benchmark').innerHTML='<h2>QQQ BENCHMARK</h2>'+kv('Strategy return',b.strategy_return)+kv('QQQ return',b.qqq_return)+kv('Excess return',b.excess_return)+kv('Status',b.status);
let orders=(gp.intents||[]).map(o=>`<tr><td>${e(o.symbol)}</td><td>${e(o.side)}</td><td>${e(o.decimal_quantity)}</td><td>${e(o.limit_price)}</td><td>${e(o.cash_after_expected)}</td><td>SHADOW PLAN ONLY / NOT SENT TO BROKER</td></tr>`).join('');document.querySelector('#planning').innerHTML='<h2>PLANNED FRACTIONAL ORDERS</h2>'+kv('SHADOW PLAN ONLY',gp.shadow_plan_only)+kv('NOT SENT TO BROKER',gp.not_sent_to_broker)+kv('EXPECTED CASH AFTER',gc.cash_after_expected)+kv('Cash reserved',gc.cash_reserved)+kv('Cash used',gc.cash_used)+kv('Total target notional',gc.total_target_notional)+kv('Uninvested cash',gc.uninvested_cash)+'<table><tr><th>Symbol</th><th>Side</th><th>Decimal Qty</th><th>Limit</th><th>Cash After</th><th>Status</th></tr>'+orders+'</table>';
let po=Object.values(ho).map(o=>`<tr><td>${e(o.intent_id)}</td><td>${e(o.symbol)}</td><td>${e(o.side)}</td><td>${e(o.decimal_quantity)}</td><td>${e(o.filled_quantity)}</td><td>${e(o.remaining_quantity)}</td><td>${e(o.status)}</td></tr>`).join('');document.querySelector('#paper').innerHTML='<h2>PAPER EXECUTION — SIMULATED TRADING ONLY / NOT REAL MONEY</h2><button onclick="paperArmH()">PAPER ARM</button><button onclick="post(\'/api/r1h/cancel-all\').then(load)">CANCEL ALL PAPER ORDERS</button><button onclick="post(\'/api/r1h/disarm\').then(load)">DISARM PAPER</button>'+kv('PAPER ARM STATUS',ha.execution_authorization)+kv('PAPER ARM EXPIRY',ha.expires_at_utc)+kv('PAPER EXECUTION BACKEND',hb.execution_backend)+kv('OPEN PAPER ORDERS',hs.open_paper_orders)+kv('PAPER FILLS',hs.paper_fills)+kv('PAPER POSITIONS',JSON.stringify(hp))+kv('PAPER CASH',hc.paper_cash)+kv('PAPER NAV',hf.paper_strategy_nav)+kv('QQQ BENCHMARK',hf.qqq_buy_hold_return)+kv('PAPER EXCESS RETURN',hf.paper_excess_return_vs_qqq)+kv('PARTIAL FILLS',Object.values(ho).filter(o=>o.status===\'PARTIALLY_FILLED\').length)+kv('REJECTED ORDERS',Object.values(ho).filter(o=>o.status===\'REJECTED\').length)+kv('RECONCILIATION STATUS',hr.state)+'<table><tr><th>Intent</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Filled</th><th>Remaining</th><th>Status</th></tr>'+po+'</table>';
let ri=d.r1i||{},so=ri.soak||{},lg=ri.live_gate||{},ie=ri.intent||{},bd=ri.broker_dedup||{},dd=ri.deal_dedup||{};document.querySelector('#paper').innerHTML+='<h2>PAPER SOAK / LIVE READINESS</h2>'+kv('PAPER SOAK STATUS',so.paper_soak_status)+kv('CURRENT SOAK DAY',so.current_soak_day)+kv('SUCCESSFUL SOAK DAYS',so.successful_soak_days)+kv('FAILED SOAK DAYS',so.failed_soak_days)+kv('CONSECUTIVE HEALTHY DAYS',so.consecutive_healthy_days)+kv('LAST 09:45 DECISION',so.last_0945_decision)+kv('LAST PAPER ORDER',so.last_paper_order)+kv('LAST RECONCILIATION',so.last_reconciliation)+kv('DUPLICATE ORDER COUNT',lg.duplicate_order_count)+kv('PROTECTED ASSET ACTION COUNT',lg.protected_asset_action_count)+kv('REAL API CALL COUNT',lg.real_trade_api_call_count)+kv('QQQ DAILY RETURN',hf.qqq_buy_hold_return)+kv('PAPER DAILY RETURN',hf.daily_return)+kv('PAPER EXCESS RETURN',hf.paper_excess_return_vs_qqq)+kv('LIVE READY',lg.live_ready);
document.querySelector('#audit').innerHTML='<h2>AUDIT</h2><button onclick="post(\'/api/control\',{mode:\'SHADOW\'}).then(load)">SHADOW</button><button onclick="post(\'/api/control\',{mode:\'OFF\'}).then(load)">OFF</button><button onclick="post(\'/api/emergency-stop\',{mode:\'FLATTEN_ONLY\'}).then(load)">FLATTEN_ONLY CONTROL</button><button onclick="paperArm()">PAPER ARM</button><button disabled>LIVE NOT AVAILABLE</button>'+kv('Execution authorization',gz.execution_authorization)+kv('Paper expires',gz.expires_at_utc)+kv('Paper environment',gz.paper_environment)+kv('Audit rows',d.audit_tail_count)+kv('Last event',(d.audit_tail||[]).slice(-1)[0]);}
load();setInterval(load,3000);</script></body></html>"""


def csv_tail(path: Path, count: int = 20) -> list[str]:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace").splitlines()[-count:]
    except OSError:
        return []


class DashboardV2Handler(BaseHTTPRequestHandler):
    paths: Paths

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def send_json(self, payload: Mapping[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route == "/":
            body = DASHBOARD_HTML.encode("utf-8"); self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body); return
        if route == "/api/state":
            r1d, out = self.paths.r1d_output, self.paths.output
            r1f = self.paths.repo / "outputs" / "v22" / "V22.047_R1F_V8_REFERENCE_ROTATION_FRACTIONAL_RTH_PROTECTED_SLEEVE_SHADOW"
            r1g = self.paths.repo / "outputs" / "v22" / "V22.047_R1G_SHADOW_FRACTIONAL_ASSUMPTION_AND_EXECUTION_ARMING"
            r1h = self.paths.repo / "outputs" / "v22" / "V22.047_R1H_PAPER_EXECUTION_ORDER_LIFECYCLE_AND_RECONCILIATION"
            r1i = self.paths.repo / "outputs" / "v22" / "V22.047_R1I_PAPER_SOAK_REPLAY_FAULT_INJECTION_AND_LIVE_READINESS_GATE"
            tail = csv_tail(out / "audit_ledger.csv")
            self.send_json({
                "summary": read_json(out / "v22_047_r1e_summary.json", {}) or {},
                "service": read_json(out / "service_state.json", {}) or {},
                "watchdog": read_json(out / "watchdog_state.json", {}) or {},
                "power": read_json(out / "power_state.json", {}) or {},
                "market": read_json(r1d / "market_snapshot.json", {}) or {},
                "account": read_json(r1d / "account_snapshot.json", {}) or {},
                "strategy": read_json(r1d / "strategy_decision.json", {}) or {},
                "control": read_json(r1d / "control_decision.json", {}) or {},
                "r1f": {"summary": read_json(r1f / "v22_047_r1f_summary.json", {}) or {},
                         "decision": read_json(r1f / "strategy_decision.json", {}) or {},
                         "control": read_json(r1f / "control_decision.json", {}) or {},
                         "capability": read_json(r1f / "fractional_capability.json", {}) or {},
                         "performance": read_json(r1f / "sleeve_performance_state.json", {}) or {}},
                "r1g": {"summary": read_json(r1g / "r1g_summary.json", {}) or {},
                         "assumption": read_json(r1g / "fractional_assumption.json", {}) or {},
                         "authorization": read_json(r1g / "execution_authorization_state.json", {}) or {},
                         "target": read_json(r1g / "target_portfolio_snapshot.json", {}) or {},
                         "plan": read_json(r1g / "shadow_fractional_order_intents.json", {}) or {},
                         "cash": read_json(r1g / "shadow_cash_projection.json", {}) or {}},
                "r1h": {"summary": read_json(r1h / "r1h_summary.json", {}) or {},
                         "authorization": read_json(r1h / "paper_authorization_state.json", {}) or {},
                         "backend": read_json(r1h / "paper_execution_backend.json", {}) or {},
                         "orders": read_json(r1h / "paper_order_state.json", {}) or {},
                         "reconciliation": read_json(r1h / "paper_reconciliation_state.json", {}) or {},
                         "portfolio": read_json(r1h / "paper_portfolio_snapshot.json", {}) or {},
                         "cash": read_json(r1h / "paper_cash_snapshot.json", {}) or {},
                         "performance": read_json(r1h / "paper_performance_snapshot.json", {}) or {}},
                "r1i": {"summary": read_json(r1i / "r1i_summary.json", {}) or {},
                         "soak": read_json(r1i / "paper_soak_state.json", {}) or {},
                         "eod": read_json(r1i / "paper_eod_reconciliation.json", {}) or {},
                         "intent": read_json(r1i / "intent_idempotency_report.json", {}) or {},
                         "broker_dedup": read_json(r1i / "broker_event_dedup_report.json", {}) or {},
                         "deal_dedup": read_json(r1i / "deal_event_dedup_report.json", {}) or {},
                         "live_gate": read_json(r1i / "live_readiness_gate.json", {}) or {}},
                "audit_tail": tail, "audit_tail_count": len(tail),
            }); return
        self.send_json({"error": "NOT_FOUND"}, 404)

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 4096)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self.send_json({"error": "INVALID_JSON"}, 400); return
        mode = str(payload.get("mode", "OFF")).upper()
        if route in {"/api/r1h/paper-arm", "/api/r1h/cancel-all", "/api/r1h/disarm", "/api/r1h/live-arm"}:
            script = self.paths.repo / "scripts" / "v22" / "v22_047_r1h_paper_execution_order_lifecycle_and_reconciliation.py"
            try:
                module = load_module(script, "v22_047_r1h_dashboard_action")
                paths = module.Paths(self.paths.repo)
                if route == "/api/r1h/paper-arm":
                    result = module.request_paper_arm(paths, dashboard_clicked=payload.get("dashboard_clicked") is True,
                        first_confirmation=payload.get("first_confirmation") is True,
                        second_confirmation=str(payload.get("second_confirmation", "")),
                        requested_backend=str(payload.get("execution_backend", "PAPER_LOCAL_SIM")))
                    audit(self.paths, "R1H_PAPER_ARMED_SIMULATED_ONLY", result.get("config_hash", ""))
                elif route == "/api/r1h/cancel-all":
                    result = {"ok": True, "canceled_orders": module.PaperExecutionEngine(self.paths.repo).cancel_all(reason="DASHBOARD_CANCEL_ALL")}
                    audit(self.paths, "R1H_CANCEL_ALL_PAPER_ORDERS", str(len(result["canceled_orders"])))
                elif route == "/api/r1h/disarm":
                    engine = module.PaperExecutionEngine(self.paths.repo); canceled = engine.cancel_all(reason="DASHBOARD_DISARM")
                    result = {**module.disarm_paper(paths, "DASHBOARD_DISARM"), "canceled_order_count": len(canceled)}
                    audit(self.paths, "R1H_PAPER_DISARMED", str(len(canceled)))
                else:
                    result = module.request_live_arm(); self.send_json(result, 409); return
            except Exception as exc:
                self.send_json({"error": str(exc), "execution_authorization": "DISARMED", "live_available": False, "real_trade_api_called": False}, 409); return
            self.send_json({"ok": True, **result, "live_available": False, "real_trade_api_called": False}); return
        if route == "/api/r1g/paper-arm":
            script=self.paths.repo/"scripts"/"v22"/"v22_047_r1g_shadow_fractional_assumption_and_execution_arming.py"
            try:
                module=load_module(script,"v22_047_r1g_dashboard_paper_arm"); state=module.request_paper_arm(module.Paths(self.paths.repo),first_confirmation=payload.get("first_confirmation") is True,second_confirmation=str(payload.get("second_confirmation","")))
            except Exception as exc:
                self.send_json({"error":str(exc),"execution_authorization":"DISARMED","broker_action_allowed":False,"real_trade_api_called":False},409); return
            audit(self.paths,"R1G_PAPER_ARMED_SIMULATE_ONLY",state.get("configuration_hash",""))
            self.send_json({"ok":True,**state,"effective_execution_mode":"SHADOW_ONLY","broker_action_allowed":False,"real_trade_api_called":False}); return
        if route == "/api/r1g/live-arm":
            script=self.paths.repo/"scripts"/"v22"/"v22_047_r1g_shadow_fractional_assumption_and_execution_arming.py"; module=load_module(script,"v22_047_r1g_dashboard_live_block"); result=module.request_live_arm(module.Paths(self.paths.repo))
            audit(self.paths,"R1G_LIVE_ARM_REJECTED","LIVE_NOT_AVAILABLE"); self.send_json(result,409); return
        if route == "/api/r1f/resume-automation":
            symbol = str(payload.get("symbol", "")).upper()
            if symbol not in {"US.QQQ", "US.TQQQ", "US.SQQQ", "US.IQQQ"}:
                self.send_json({"error": "INVALID_R1F_SYMBOL"}, 400); return
            script=self.paths.repo/"scripts"/"v22"/"v22_047_r1f_fractional_protected_sleeve.py"
            module=load_module(script,"v22_047_r1f_dashboard_resume"); state=module.resume_automation_now(module.Paths(self.paths.repo),symbol)
            audit(self.paths, "R1F_RESUME_AUTOMATION_NOW", symbol)
            self.send_json({"ok": True, "symbol": symbol, "manual_override_state": state.get("system_state"), "broker_action_allowed": False, "trade_api_called": False}); return
        if mode in {"LIVE", "PAPER"}:
            self.send_json({"error": f"{mode}_NOT_AVAILABLE", "broker_action_allowed": False}, 409); return
        latch = bool((read_json(self.paths.runtime / "degraded_latch.json", {}) or {}).get("active"))
        if route == "/api/emergency-stop":
            if mode not in {"OFF", "FLATTEN_ONLY"}: mode = "OFF"
            set_switch(self.paths, mode, "Dashboard V2 Emergency Stop", emergency=True)
            audit(self.paths, "EMERGENCY_STOP", mode, switch_mode=mode)
            self.send_json({"ok": True, "mode": mode, "effective_execution_mode": "SHADOW_ONLY",
                            "broker_action_allowed": False, "trade_api_called": False}); return
        if route == "/api/control":
            if mode not in {"OFF", "SHADOW", "FLATTEN_ONLY"}:
                self.send_json({"error": "INVALID_MODE"}, 400); return
            if mode == "SHADOW" and latch:
                self.send_json({"error": "DEGRADED_LATCH_REQUIRES_MANUAL_REVIEW", "broker_action_allowed": False}, 409); return
            set_switch(self.paths, mode, "Dashboard V2 control", emergency=mode != "SHADOW")
            audit(self.paths, "DASHBOARD_CONTROL", mode, switch_mode=mode)
            self.send_json({"ok": True, "mode": mode, "effective_execution_mode": "SHADOW_ONLY",
                            "broker_action_allowed": False, "trade_api_called": False}); return
        self.send_json({"error": "NOT_FOUND"}, 404)


def run_ui(repo_root: Path) -> int:
    paths = Paths.for_repo(repo_root); initialize(paths)
    if HOST != "127.0.0.1": raise R1EError("DASHBOARD_MUST_BIND_LOOPBACK")
    handler = type("R1EDashboardV2Handler", (DashboardV2Handler,), {"paths": paths})
    server = ThreadingHTTPServer((HOST, PORT), handler)
    atomic_json(paths.output / "ui_state.json", {
        "schema_version": 1, "timestamp_utc": utc_iso(), "desired_running": True,
        "actual_running": True, "pid": os.getpid(), "bind_host": HOST, "port": PORT,
        "url": f"http://{HOST}:{PORT}", "engine_dependency": False,
    })
    audit(paths, "UI_RUNNING", f"pid={os.getpid()}", ui_pid=os.getpid())
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        prior = read_json(paths.output / "ui_state.json", {}) or {}
        prior.update({"actual_running": False, "stopped_at_utc": utc_iso(), "pid": None})
        atomic_json(paths.output / "ui_state.json", prior)
    return 0


def service_status(repo_root: Path) -> dict[str, Any]:
    paths = Paths.for_repo(repo_root); initialize(paths)
    r1d = load_module(paths.r1d_script, "v22_047_r1d_for_r1e_status")
    service_pid = pid_from(paths.runtime / "service.pid")
    watchdog_pid = pid_from(paths.runtime / "watchdog.pid")
    engine = engine_pid(paths); dashboard = ui_pid(paths)
    r1f_pid = pid_from(paths.runtime / "r1f.pid")
    r1g_pid = pid_from(paths.runtime / "r1g.pid")
    r1f_summary = read_json(paths.repo / "outputs" / "v22" / "V22.047_R1F_V8_REFERENCE_ROTATION_FRACTIONAL_RTH_PROTECTED_SLEEVE_SHADOW" / "v22_047_r1f_summary.json", {}) or {}
    r1g_summary = read_json(paths.repo / "outputs" / "v22" / "V22.047_R1G_SHADOW_FRACTIONAL_ASSUMPTION_AND_EXECUTION_ARMING" / "r1g_summary.json", {}) or {}
    payload = {
        "schema_version": 1, "timestamp_utc": utc_iso(),
        "service_pid": service_pid or None, "service_running": process_alive(r1d, service_pid),
        "watchdog_pid": watchdog_pid or None, "watchdog_running": process_alive(r1d, watchdog_pid),
        "engine_pid": engine or None, "engine_running": process_alive(r1d, engine),
        "ui_pid": dashboard or None, "ui_running": process_alive(r1d, dashboard),
        "r1f_pid": r1f_pid or None, "r1f_running": process_alive(r1d, r1f_pid),
        "r1g_pid": r1g_pid or None, "r1g_running": process_alive(r1d, r1g_pid),
        "switch_mode": (read_json(paths.r1d_output / "switch_state.json", {}) or {}).get("mode", "OFF"),
        "execution_mode": r1f_summary.get("execution_mode", "SHADOW"),
        "effective_execution_mode": "SHADOW_ONLY",
        "strategy_enabled": r1f_summary.get("strategy_enabled") is True,
        "strategy_configured": r1f_summary.get("strategy_configured") is True,
        "strategy_name": r1f_summary.get("strategy_name", "V8_REFERENCE_TREND_ROTATION"),
        "fractional_capability_status": r1g_summary.get("fractional_capability_status", "USER_CONFIRMED_RTH_APP"),
        "execution_authorization": r1g_summary.get("execution_authorization", "DISARMED"),
        "broker_action_allowed": False, "trade_api_called": False, "real_trade_api_called": False,
    }
    atomic_json(paths.output / "service_state.json", {**payload, "service_status": "RUNNING" if payload["service_running"] else "STOPPED"})
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("service", "watchdog", "ui", "status", "power", "watchdog-once"):
        p = sub.add_parser(name); p.add_argument("--repo-root", default=r"D:\us-tech-quant")
        if name == "service": p.add_argument("--wait-seconds", type=float, default=1800.0)
        if name in {"watchdog", "watchdog-once"}: p.add_argument("--interval", type=float, default=5.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv); repo = Path(args.repo_root)
    try:
        if args.command == "service":
            service = Service(repo, args.wait_seconds)
            def stop(*_: Any) -> None: service.running = False
            signal.signal(signal.SIGINT, stop)
            if hasattr(signal, "SIGTERM"): signal.signal(signal.SIGTERM, stop)
            return service.run()
        if args.command in {"watchdog", "watchdog-once"}:
            return run_watchdog(repo, args.interval, once=args.command == "watchdog-once")
        if args.command == "ui": return run_ui(repo)
        if args.command == "status": print(json.dumps(service_status(repo), ensure_ascii=False, indent=2)); return 0
        if args.command == "power":
            paths = Paths.for_repo(repo); initialize(paths); value = power_state(); atomic_json(paths.output / "power_state.json", value)
            print(json.dumps(value, ensure_ascii=True, indent=2)); return 0
        return 2
    except Exception as exc:
        print(f"final_status=FAIL_{REVISION}", file=sys.stderr)
        print(f"error={type(exc).__name__}:{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
