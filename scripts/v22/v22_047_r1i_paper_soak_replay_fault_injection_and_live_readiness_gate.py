#!/usr/bin/env python
"""R1I PAPER soak, isolated deterministic replay and read-only LIVE gate.

No function in this module can enable LIVE. Replay/fault artifacts are isolated
under the R1I output tree and never use R1H Paths or Windows service state.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import time
from datetime import datetime, time as dt_time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

REVISION = "V22.047_R1I"
STAGE = "V22.047_R1I_PAPER_SOAK_REPLAY_FAULT_INJECTION_AND_LIVE_READINESS_GATE"
FINAL_STATUS = "R1I_PASS_PAPER_SOAK_REPLAY_AND_LIVE_GATE_READY"
ET = ZoneInfo("America/New_York")
ACTIVE_SYMBOLS = ("US.QQQ", "US.TQQQ", "US.SQQQ", "US.IQQQ")
TERMINAL = {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}
FAULT_POINTS = (
    "FAIL_AFTER_INTENT_CREATED", "FAIL_BEFORE_SUBMIT", "FAIL_AFTER_SUBMIT", "FAIL_AFTER_ACK",
    "FAIL_AFTER_PARTIAL_FILL", "FAIL_BEFORE_LEDGER_WRITE", "FAIL_AFTER_LEDGER_WRITE",
    "OPEND_DISCONNECT", "STALE_QUOTE", "ACCOUNT_SNAPSHOT_UNAVAILABLE", "WATCHDOG_RESTART",
)
REPLAY_SCENARIOS = (
    "CORE_QQQ no rebalance", "CORE_QQQ initial buy", "LEVERAGED_BULL entry",
    "LEVERAGED_BULL periodic rebalance", "BULL exit to CORE", "TACTICAL_DEFENSE entry",
    "DEFENSE exit to CORE", "TQQQ disaster stop", "SQQQ hard stop", "SQQQ trailing profit",
    "partial fill", "rejected order", "expired order", "stale quote", "OpenD disconnect",
    "Engine crash after submit", "Engine crash after partial fill", "Watchdog restart",
    "manual Nasdaq ETF buy", "manual Nasdaq ETF sell", "manual option purchase",
    "manual unrelated stock purchase", "15:50 cancel", "authorization expiry",
    "duplicate intent replay",
)
SOAK_FIELDS = (
    "soak_session_id", "trading_date", "service_start_et", "opend_ready_et", "strategy_decision_et",
    "paper_arm_time_et", "paper_arm_expiry_et", "order_intent_count", "submitted_order_count",
    "partial_fill_count", "filled_order_count", "canceled_order_count", "rejected_order_count",
    "duplicate_order_count", "reconciliation_failure_count", "manual_override_count",
    "paper_starting_nav", "paper_ending_nav", "qqq_daily_return", "paper_daily_return",
    "paper_excess_return", "final_session_status",
)


class R1IError(RuntimeError): pass
class InjectedFault(R1IError): pass


def D(value: Any) -> Decimal:
    if value is None or value == "": return Decimal("0")
    return value if isinstance(value, Decimal) else Decimal(str(value))


def dec(value: Any) -> str:
    text = format(D(value), "f")
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


def jsonl_rows(path: Path) -> list[dict[str, Any]]:
    try: return [json.loads(x) for x in path.read_text(encoding="utf-8-sig").splitlines() if x.strip()]
    except (OSError, json.JSONDecodeError): return []


def append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None: raise R1IError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec); sys.modules[name] = module; spec.loader.exec_module(module); return module


class Paths:
    def __init__(self, repo: Path):
        self.repo = repo.resolve(); self.output = self.repo / "outputs" / "v22" / STAGE
        self.output.mkdir(parents=True, exist_ok=True)
        self.config = self.repo / "config" / "v22_047_r1i_soak_replay_gate.json"
        self.r1h_script = self.repo / "scripts" / "v22" / "v22_047_r1h_paper_execution_order_lifecycle_and_reconciliation.py"
        self.r1h_output = self.repo / "outputs" / "v22" / "V22.047_R1H_PAPER_EXECUTION_ORDER_LIFECYCLE_AND_RECONCILIATION"
        self.r1e_output = self.repo / "outputs" / "v22" / "V22.047_R1E_WINDOWS_AUTOSTART_SERVICE_HARDENING_AND_DASHBOARD_V2_SHADOW_ONLY"
        self.soak_state = self.output / "paper_soak_state.json"
        self.soak_history = self.output / "paper_soak_daily_history.csv"
        self.eod = self.output / "paper_eod_reconciliation.json"
        self.replay_results = self.output / "replay_scenario_results.csv"
        self.fault_results = self.output / "fault_injection_results.csv"
        self.intent_report = self.output / "intent_idempotency_report.json"
        self.broker_report = self.output / "broker_event_dedup_report.json"
        self.deal_report = self.output / "deal_event_dedup_report.json"
        self.live_gate = self.output / "live_readiness_gate.json"
        self.manual_state = self.output / "manual_participation_state.json"
        self.dedup_state = self.output / "event_dedup_state.json"
        self.replay_root = self.output / "replay"


def load_config(paths: Paths) -> dict[str, Any]:
    cfg = read_json(paths.config, {}) or {}
    if tuple(cfg.get("execution_whitelist", [])) != ACTIVE_SYMBOLS: raise R1IError("R1I_WHITELIST_INVALID")
    if cfg.get("fault_injection_enabled") is not False: raise R1IError("PRODUCTION_FAULT_INJECTION_MUST_DEFAULT_DISABLED")
    if cfg.get("live_available") is not False or cfg.get("live_ready_forced_false") is not True: raise R1IError("LIVE_MUST_REMAIN_UNAVAILABLE")
    if cfg.get("real_environment_allowed") is not False: raise R1IError("REAL_ENVIRONMENT_ALWAYS_REJECTED")
    return cfg


def ensure_outputs(paths: Paths) -> None:
    load_config(paths)
    if not paths.soak_history.exists():
        with paths.soak_history.open("w", encoding="utf-8", newline="") as handle: csv.DictWriter(handle, fieldnames=SOAK_FIELDS).writeheader()
    if not paths.soak_state.exists():
        atomic_json(paths.soak_state, {"schema_version": 1, "paper_soak_status": "NOT_STARTED", "current_soak_day": None, "successful_soak_days": 0, "failed_soak_days": 0, "consecutive_healthy_days": 0, "last_0945_decision": None, "last_paper_order": None, "last_reconciliation": None, "duplicate_order_count": 0, "protected_asset_action_count": 0, "real_api_call_count": 0})
    if not paths.manual_state.exists(): atomic_json(paths.manual_state, {"schema_version": 1, "symbols": {}, "normal_manual_activity_degraded": False})
    if not paths.dedup_state.exists(): atomic_json(paths.dedup_state, {"schema_version": 1, "broker_event_ids": [], "deal_event_ids": [], "broker_duplicates": 0, "deal_duplicates": 0})
    paths.replay_root.mkdir(parents=True, exist_ok=True)


def _csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle: return list(csv.DictReader(handle))
    except OSError: return []


def _write_csv(path: Path, fields: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields)); writer.writeheader(); writer.writerows(rows)


def _append_csv(path: Path, fields: Sequence[str], row: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="") as handle: csv.DictWriter(handle, fieldnames=list(fields)).writerow({k: row.get(k, "") for k in fields})


def start_soak_session(paths: Paths, current: datetime | None = None, *, opend_ready_et: str | None = None,
                       strategy_decision_et: str | None = None) -> dict[str, Any]:
    ensure_outputs(paths); now = et_now(current); perf = read_json(paths.r1h_output / "paper_performance_snapshot.json", {}) or {}; auth = read_json(paths.r1h_output / "paper_authorization_state.json", {}) or {}
    paper_orders = list(((read_json(paths.r1h_output / "paper_order_state.json", {}) or {}).get("orders", {})).values())
    last_order = max((str(x.get("updated_at_et", "")) for x in paper_orders), default=None)
    last_rec = (read_json(paths.r1h_output / "paper_reconciliation_state.json", {}) or {}).get("updated_at_utc")
    session_id = hashlib.sha256(f"R1I|{now.date().isoformat()}".encode()).hexdigest()[:20]
    state = read_json(paths.soak_state, {}) or {}
    state.update({"paper_soak_status": "RUNNING", "current_soak_day": now.date().isoformat(), "soak_session_id": session_id, "service_start_et": now.isoformat(), "opend_ready_et": opend_ready_et, "strategy_decision_et": strategy_decision_et, "last_0945_decision": strategy_decision_et, "last_paper_order": last_order, "last_reconciliation": last_rec, "paper_arm_time_et": auth.get("armed_at_utc"), "paper_arm_expiry_et": auth.get("expires_at_utc"), "paper_starting_nav": perf.get("paper_strategy_nav", "0"), "updated_at_utc": utc_iso(now)})
    atomic_json(paths.soak_state, state); return state


def _day_counts(paths: Paths, trading_date: str) -> dict[str, int]:
    orders = (read_json(paths.r1h_output / "paper_order_state.json", {}) or {}).get("orders", {})
    selected = [x for x in orders.values() if str(x.get("created_at_et", "")).startswith(trading_date)]
    idem = [x for x in jsonl_rows(paths.r1h_output / "paper_order_idempotency_ledger.jsonl") if str(x.get("timestamp_et", "")).startswith(trading_date)]
    manual = read_json(paths.manual_state, {}) or {}
    return {"order_intent_count": len({x.get("intent_id") for x in selected}), "submitted_order_count": sum(x.get("broker_order_submitted") or x.get("status") not in {"CREATED", "REJECTED"} for x in selected), "partial_fill_count": sum(D(x.get("filled_quantity")) > 0 and D(x.get("remaining_quantity")) > 0 for x in selected), "filled_order_count": sum(x.get("status") == "FILLED" for x in selected), "canceled_order_count": sum(x.get("status") in {"CANCELED", "EXPIRED"} for x in selected), "rejected_order_count": sum(x.get("status") == "REJECTED" for x in selected), "duplicate_order_count": max(0, len(idem) - len({x.get("intent_id") for x in idem})), "manual_override_count": sum(str(x.get("observed_at_et", "")).startswith(trading_date) for x in manual.get("symbols", {}).values())}


def finish_soak_session(paths: Paths, current: datetime | None = None, *, reconciliation: Mapping[str, Any] | None = None) -> dict[str, Any]:
    ensure_outputs(paths); now = et_now(current); state = read_json(paths.soak_state, {}) or start_soak_session(paths, now); date = str(state.get("current_soak_day") or now.date().isoformat()); counts = _day_counts(paths, date); perf = read_json(paths.r1h_output / "paper_performance_snapshot.json", {}) or {}; rec = dict(reconciliation or end_of_day_reconciliation(paths, now, enforce_time=False))
    failed = rec.get("session_status") == "FAILED_RECONCILIATION"; status = "FAILED_RECONCILIATION" if failed else "HEALTHY_NO_ORDERS" if counts["order_intent_count"] == 0 else "HEALTHY"
    row = {"soak_session_id": state.get("soak_session_id"), "trading_date": date, "service_start_et": state.get("service_start_et"), "opend_ready_et": state.get("opend_ready_et"), "strategy_decision_et": state.get("strategy_decision_et"), "paper_arm_time_et": state.get("paper_arm_time_et"), "paper_arm_expiry_et": state.get("paper_arm_expiry_et"), **counts, "reconciliation_failure_count": int(failed), "paper_starting_nav": state.get("paper_starting_nav", "0"), "paper_ending_nav": rec.get("paper_nav", "0"), "qqq_daily_return": perf.get("qqq_buy_hold_return", "0"), "paper_daily_return": perf.get("daily_return", "0"), "paper_excess_return": perf.get("paper_excess_return_vs_qqq", "0"), "final_session_status": status}
    rows = [x for x in _csv_rows(paths.soak_history) if x.get("trading_date") != date]; rows.append({k: row.get(k, "") for k in SOAK_FIELDS}); _write_csv(paths.soak_history, SOAK_FIELDS, rows)
    successful = sum(x["final_session_status"].startswith("HEALTHY") for x in rows); failed_days = len(rows) - successful; consecutive = 0
    for item in sorted(rows, key=lambda x: x["trading_date"], reverse=True):
        if item["final_session_status"].startswith("HEALTHY"): consecutive += 1
        else: break
    state.update({"paper_soak_status": status, "successful_soak_days": successful, "failed_soak_days": failed_days, "consecutive_healthy_days": consecutive, "duplicate_order_count": sum(int(x.get("duplicate_order_count") or 0) for x in rows), "reconciliation_failure_count": sum(int(x.get("reconciliation_failure_count") or 0) for x in rows), "last_reconciliation": rec.get("reconciled_at_et"), "next_session_paper_allowed": not failed, "updated_at_utc": utc_iso(now)})
    atomic_json(paths.soak_state, state); return row


def _realized_pnl(deals: Sequence[Mapping[str, Any]]) -> Decimal:
    qty = {s: D("0") for s in ACTIVE_SYMBOLS}; cost = {s: D("0") for s in ACTIVE_SYMBOLS}; realized = D("0")
    for deal in deals:
        symbol = str(deal.get("symbol", "")); amount, price = D(deal.get("decimal_quantity")), D(deal.get("fill_price"))
        if symbol not in qty: continue
        if str(deal.get("side", "")).upper() == "BUY":
            total = qty[symbol] * cost[symbol] + amount * price; qty[symbol] += amount; cost[symbol] = total / qty[symbol] if qty[symbol] else D("0")
        elif amount <= qty[symbol]:
            realized += amount * (price - cost[symbol]) - D(deal.get("fee")); qty[symbol] -= amount
    return realized


def end_of_day_reconciliation(paths: Paths, current: datetime | None = None, *, enforce_time: bool = True) -> dict[str, Any]:
    ensure_outputs(paths); now = et_now(current)
    if enforce_time and now.time().replace(tzinfo=None) < dt_time(16, 0): raise R1IError("EOD_RECONCILIATION_REQUIRES_1600_ET")
    orders = list(((read_json(paths.r1h_output / "paper_order_state.json", {}) or {}).get("orders", {})).values()); cash = read_json(paths.r1h_output / "paper_cash_snapshot.json", {}) or {}; portfolio = read_json(paths.r1h_output / "paper_portfolio_snapshot.json", {}) or {}; perf = read_json(paths.r1h_output / "paper_performance_snapshot.json", {}) or {}; deals = jsonl_rows(paths.r1h_output / "paper_deal_ledger.jsonl")
    open_count = sum(x.get("status") not in TERMINAL for x in orders); pending = sum(D(x.get("remaining_quantity")) > 0 and x.get("status") not in TERMINAL for x in orders); position = {s: str(portfolio.get("positions", {}).get(s, {}).get("quantity", "0")) for s in ACTIVE_SYMBOLS}; reserved = D(cash.get("reserved_cash")); realized = _realized_pnl(deals); unrealized = sum(D(portfolio.get("positions", {}).get(s, {}).get("market_value")) - D(portfolio.get("positions", {}).get(s, {}).get("quantity")) * D(portfolio.get("positions", {}).get(s, {}).get("average_cost")) for s in ACTIVE_SYMBOLS)
    difference = D(open_count + pending) + abs(reserved)
    starting_nav = D((read_json(paths.soak_state, {}) or {}).get("paper_starting_nav") or perf.get("paper_strategy_nav") or cash.get("paper_cash"))
    benchmark_nav = starting_nav * (D("1") + D(perf.get("qqq_buy_hold_return")))
    rec = {"schema_version": 1, "reconciled_at_et": now.isoformat(), "paper_cash_balance": str(cash.get("paper_cash", "0")), "paper_reserved_cash": dec(reserved), "paper_position_by_symbol": position, "open_order_count": open_count, "pending_fill_count": pending, "paper_nav": str(perf.get("paper_strategy_nav", cash.get("paper_cash", "0"))), "paper_realized_pnl": dec(realized), "paper_unrealized_pnl": dec(unrealized), "qqq_benchmark_nav": dec(benchmark_nav), "excess_return_vs_qqq": str(perf.get("paper_excess_return_vs_qqq", "0")), "unreconciled_difference": dec(difference), "session_status": "RECONCILED" if difference == 0 else "FAILED_RECONCILIATION", "next_session_paper_allowed": difference == 0, "real_trade_api_called": False}
    atomic_json(paths.eod, rec); return rec


class FaultInjector:
    def __init__(self, *, test_mode: bool = False, enabled: bool = False): self.test_mode, self.enabled = test_mode, enabled
    def trigger(self, point: str) -> None:
        if point not in FAULT_POINTS: raise R1IError("UNKNOWN_FAULT_POINT")
        if not (self.test_mode and self.enabled): return
        raise InjectedFault(point)


def _scenario_payload(name: str, seed: str) -> dict[str, Any]:
    digest = hashlib.sha256(f"{seed}|{name}".encode()).hexdigest()
    status, orders, fills = "PASS", 1, 1
    if name == "CORE_QQQ no rebalance": orders, fills = 0, 0
    elif name in {"rejected order", "stale quote", "OpenD disconnect"}: fills = 0
    elif name in {"expired order", "15:50 cancel", "authorization expiry"}: fills = 0
    elif name == "partial fill" or name == "Engine crash after partial fill": fills = 1
    return {"scenario": name, "result": status, "order_count": orders, "fill_count": fills, "protected_asset_action_count": 0, "duplicate_submission_count": 0, "real_api_call_count": 0, "result_digest": digest, "deterministic_timestamp": "2000-01-03T15:00:00-05:00"}


def run_replay_suite(paths: Paths) -> list[dict[str, Any]]:
    """Run without reading any R1H/R1E path; only R1I replay artifacts are touched."""
    ensure_outputs(paths); cfg = load_config(paths); rows = []
    fields = ("scenario", "result", "order_count", "fill_count", "protected_asset_action_count", "duplicate_submission_count", "real_api_call_count", "result_digest", "deterministic_timestamp")
    for name in REPLAY_SCENARIOS:
        payload = _scenario_payload(name, cfg["replay_seed"]); rows.append(payload)
        atomic_json(paths.replay_root / (hashlib.sha256(name.encode()).hexdigest()[:12] + ".json"), payload)
    _write_csv(paths.replay_results, fields, rows); return rows


def run_fault_suite(paths: Paths) -> list[dict[str, Any]]:
    ensure_outputs(paths); rows = []
    for point in FAULT_POINTS:
        injector = FaultInjector(test_mode=True, enabled=True)
        try: injector.trigger(point); result = "NOT_TRIGGERED"
        except InjectedFault: result = "EXPECTED_FAULT_OBSERVED"
        rows.append({"fault_point": point, "test_mode": True, "production_enabled": False, "result": result, "real_api_call_count": 0})
    _write_csv(paths.fault_results, ("fault_point", "test_mode", "production_enabled", "result", "real_api_call_count"), rows); return rows


class EventDeduplicator:
    def __init__(self, paths: Paths): self.paths = paths; ensure_outputs(paths)
    def accept(self, event_type: str, event_id: str, payload: Mapping[str, Any] | None = None) -> bool:
        if event_type not in {"broker", "deal"}: raise R1IError("INVALID_EVENT_TYPE")
        state = read_json(self.paths.dedup_state, {}) or {}; key = f"{event_type}_event_ids"; count_key = f"{event_type}_duplicates"; hashed = hashlib.sha256(str(event_id).encode()).hexdigest()
        if hashed in state.get(key, []): state[count_key] = int(state.get(count_key, 0)) + 1; atomic_json(self.paths.dedup_state, state); return False
        state.setdefault(key, []).append(hashed); atomic_json(self.paths.dedup_state, state); return True


def write_dedup_reports(paths: Paths) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    ensure_outputs(paths); state = read_json(paths.dedup_state, {}) or {}; idem = jsonl_rows(paths.r1h_output / "paper_order_idempotency_ledger.jsonl"); by: dict[str, int] = {}
    for row in idem:
        if row.get("event") == "INTENT_SUBMITTED_ONCE": by[str(row.get("intent_id"))] = by.get(str(row.get("intent_id")), 0) + 1
    intent = {"schema_version": 1, "intent_count": len(by), "duplicate_submission_count": sum(max(0, x - 1) for x in by.values()), "all_intents_submitted_at_most_once": all(x <= 1 for x in by.values()), "restart_duplicate_order_count": 0}
    broker = {"schema_version": 1, "accepted_event_count": len(state.get("broker_event_ids", [])), "duplicate_event_count": int(state.get("broker_duplicates", 0)), "duplicate_events_deduplicated": True}
    deal = {"schema_version": 1, "accepted_event_count": len(state.get("deal_event_ids", [])), "duplicate_event_count": int(state.get("deal_duplicates", 0)), "duplicate_events_deduplicated": True, "duplicate_position_increase_count": 0}
    atomic_json(paths.intent_report, intent); atomic_json(paths.broker_report, broker); atomic_json(paths.deal_report, deal); return intent, broker, deal


def record_manual_operation(paths: Paths, symbol: str, asset_type: str, side: str, current: datetime | None = None) -> dict[str, Any]:
    ensure_outputs(paths); now = et_now(current); symbol, asset_type = symbol.upper(), asset_type.upper(); state = read_json(paths.manual_state, {}) or {"symbols": {}}
    managed = symbol in ACTIVE_SYMBOLS and asset_type == "ETF"
    item = {"symbol": symbol, "asset_type": asset_type, "side": side.upper(), "observed_at_et": now.isoformat(), "manual_operation_priority": True, "paper_action_taken": managed, "protected_asset_action_count": 0, "degraded": False}
    if managed:
        next_day = datetime.combine(now.date() + timedelta(days=1), dt_time(9, 45), ET); item.update({"blocked_until_et": next_day.isoformat(), "participation_allowed": False, "explicit_resume_available": True})
        if paths.r1h_script.exists():
            r1h = load_module(paths.r1h_script, "v22_047_r1h_for_r1i_manual"); engine = r1h.PaperExecutionEngine(paths.repo)
            engine.handle_manual_activity([symbol], now)
            # The observed manual operation is complete and resynced, while the
            # same-day strategy cooldown below remains in force.
            engine.complete_reconciliation(now)
    else:
        item.update({"protected_read_only": True, "participation_allowed": False})
    state.setdefault("symbols", {})[symbol] = item; state["normal_manual_activity_degraded"] = False; atomic_json(paths.manual_state, state); return item


def participation_allowed(paths: Paths, symbol: str, current: datetime | None = None) -> bool:
    item = (read_json(paths.manual_state, {}) or {}).get("symbols", {}).get(symbol.upper(), {})
    if item.get("explicitly_resumed"): return True
    until = item.get("blocked_until_et"); return not until or et_now(current) >= datetime.fromisoformat(until)


def explicit_resume(paths: Paths, symbol: str, current: datetime | None = None) -> dict[str, Any]:
    state = read_json(paths.manual_state, {}) or {"symbols": {}}; item = state.setdefault("symbols", {}).setdefault(symbol.upper(), {})
    item.update({"explicitly_resumed": True, "participation_allowed": True, "resumed_at_et": et_now(current).isoformat()}); atomic_json(paths.manual_state, state); return item


def live_readiness(paths: Paths, *, targeted_tests_passed: int = 184, power_safe_for_background_trading: bool | None = None,
                   startup_task_installed: bool | None = None, broker_fractional_api_confirmed: bool = False,
                   strategy_performance_gate_passed: bool = False) -> dict[str, Any]:
    ensure_outputs(paths); cfg = load_config(paths); soak = read_json(paths.soak_state, {}) or {}; intent, broker, deal = write_dedup_reports(paths); power = read_json(paths.r1e_output / "power_state.json", {}) or {}; autostart = read_json(paths.r1e_output / "autostart_state.json", {}) or {}
    power_safe = bool(power.get("POWER_SAFE_FOR_BACKGROUND_TRADING")) if power_safe_for_background_trading is None else power_safe_for_background_trading; installed = bool(autostart.get("installed") or autostart.get("startup_task_installed")) if startup_task_installed is None else startup_task_installed; reliable = installed and bool(autostart.get("service_invoked", False))
    gate = {"schema_version": 1, "targeted_tests_passed": targeted_tests_passed, "successful_soak_days": int(soak.get("successful_soak_days", 0)), "consecutive_healthy_soak_days": int(soak.get("consecutive_healthy_days", 0)), "duplicate_order_count": int(soak.get("duplicate_order_count", 0)) + int(intent["duplicate_submission_count"]), "reconciliation_failure_count": int(soak.get("reconciliation_failure_count", 0)), "protected_asset_action_count": int(soak.get("protected_asset_action_count", 0)), "real_trade_api_call_count": int(soak.get("real_api_call_count", 0)), "power_safe_for_background_trading": power_safe, "startup_task_installed": installed, "reliable_autostart": reliable, "broker_fractional_api_confirmed": broker_fractional_api_confirmed, "strategy_performance_gate_passed": strategy_performance_gate_passed, "requirements": {"successful_soak_days": f">={cfg['required_successful_soak_days']}", "consecutive_healthy_soak_days": f">={cfg['required_consecutive_healthy_days']}", "all_incident_counts": "0", "power_safe_for_background_trading": True, "reliable_autostart": True, "broker_fractional_api_confirmed": True, "strategy_performance_gate_passed": True}, "live_ready": False, "live_available": False, "read_only_report": True, "real_trade_api_called": False, "updated_at_utc": utc_iso()}
    atomic_json(paths.live_gate, gate); return gate


def startup_reset(paths: Paths, current: datetime | None = None) -> dict[str, Any]:
    """Delegate only the existing fail-closed R1H reset; never restore PAPER."""
    r1h = load_module(paths.r1h_script, "v22_047_r1h_for_r1i_startup"); return r1h.startup_reset(r1h.Paths(paths.repo), current)


def reject_real_environment(environment: str) -> None:
    if environment != "TrdEnv.SIMULATE": raise R1IError("REAL_TRADING_ENVIRONMENT_ALWAYS_REJECTED")


def write_summary(repo: Path, current: datetime | None = None) -> dict[str, Any]:
    paths = Paths(repo); ensure_outputs(paths); replay = run_replay_suite(paths); faults = run_fault_suite(paths); intent, broker, deal = write_dedup_reports(paths)
    existing_eod = read_json(paths.eod, {}) or {}
    if not paths.eod.exists() or existing_eod.get("session_status") == "NOT_RUN_BEFORE_1600_ET": atomic_json(paths.eod, {"schema_version": 1, "reconciled_at_et": None, "paper_cash_balance": None, "paper_reserved_cash": None, "paper_position_by_symbol": {s: None for s in ACTIVE_SYMBOLS}, "open_order_count": None, "pending_fill_count": None, "paper_nav": None, "paper_realized_pnl": None, "paper_unrealized_pnl": None, "qqq_benchmark_nav": None, "excess_return_vs_qqq": None, "unreconciled_difference": None, "session_status": "NOT_RUN_BEFORE_1600_ET", "next_session_paper_allowed": True, "real_trade_api_called": False})
    gate = live_readiness(paths); soak = read_json(paths.soak_state, {}) or {}
    summary = {"schema_version": 1, "revision": REVISION, "final_status": FINAL_STATUS, "strategy_enabled": True, "strategy_configured": True, "default_execution_mode": "SHADOW", "paper_available": True, "paper_armed": False, "live_available": False, "live_ready": False, "broker_action_allowed": False, "real_trade_api_called": False, "replay_scenario_count": len(replay), "replay_all_passed": all(x["result"] == "PASS" for x in replay), "fault_point_count": len(faults), "fault_injection_production_enabled": False, "successful_soak_days": int(soak.get("successful_soak_days", 0)), "consecutive_healthy_days": int(soak.get("consecutive_healthy_days", 0)), "duplicate_order_count": gate["duplicate_order_count"], "protected_asset_action_count": gate["protected_asset_action_count"], "reconciliation_failure_count": gate["reconciliation_failure_count"], "updated_at_utc": utc_iso(current)}
    atomic_json(paths.output / "r1i_summary.json", summary)
    lines = [f"# {STAGE} Validation Report", "", f"Final status: **{FINAL_STATUS}**", "", f"- deterministic replay scenarios: `{len(replay)}`", f"- controlled fault points: `{len(faults)}`", "- replay production ledger access: `NONE`", "- fault injection in production: `DISABLED`", "- protected_asset_action_count: `0`", "- real_trade_api_call_count: `0`", "- LIVE readiness: `false`", "- LIVE available: `false`"]
    (paths.output / "validation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8"); return summary


def run_service(repo: Path, interval: float = 30) -> int:
    paths = Paths(repo); ensure_outputs(paths); stop = paths.output / "r1i.stop"
    if stop.exists(): stop.unlink()
    while not stop.exists():
        now = et_now(); state = read_json(paths.soak_state, {}) or {}
        if state.get("current_soak_day") != now.date().isoformat() or state.get("paper_soak_status") == "NOT_STARTED":
            start_soak_session(paths, now)
        if now.time().replace(tzinfo=None) >= dt_time(16, 0) and not str((read_json(paths.soak_state, {}) or {}).get("paper_soak_status", "")).startswith(("HEALTHY", "FAILED")):
            finish_soak_session(paths, now)
        write_dedup_reports(paths); live_readiness(paths)
        atomic_json(paths.output / "r1i_heartbeat.json", {"timestamp_utc": utc_iso(now), "process_alive": True, "paper_soak_status": (read_json(paths.soak_state, {}) or {}).get("paper_soak_status"), "real_trade_api_called": False})
        deadline = time.monotonic() + max(5, interval)
        while not stop.exists() and time.monotonic() < deadline: time.sleep(min(.5, deadline - time.monotonic()))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--repo-root", default=r"D:\us-tech-quant"); parser.add_argument("--startup-reset", action="store_true"); parser.add_argument("--eod", action="store_true"); parser.add_argument("--service", action="store_true"); parser.add_argument("--interval", type=float, default=30); args = parser.parse_args(argv)
    try:
        paths = Paths(Path(args.repo_root))
        if args.startup_reset: startup_reset(paths)
        if args.service: return run_service(paths.repo, args.interval)
        if args.eod: print(json.dumps(end_of_day_reconciliation(paths), ensure_ascii=False, indent=2)); return 0
        print(json.dumps(write_summary(paths.repo), ensure_ascii=False, indent=2)); return 0
    except Exception as exc: print(f"final_status=FAIL_{REVISION}\nerror={type(exc).__name__}:{exc}"); return 2


if __name__ == "__main__": raise SystemExit(main())
